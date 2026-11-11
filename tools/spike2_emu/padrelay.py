#!/usr/bin/env python3
"""padrelay.py <fifo> <port> [ctl] - hand the guest's PCM to a socket. That is all.

THE POINT OF THIS FILE IS EVERYTHING IT DOES NOT DO. Its predecessor,
audiotcp.py, filled silence against wall time, trimmed what it judged to be
surplus, and kept a running `sent` total that it re-baselined forward after a
read gap. That last part is why it appeared to send 10% more than the far end
ever received - a "shortfall" that cost hours and was pure bookkeeping, since
`sent` advanced for bytes that were never put on the wire. The pacing was just
as misguided: it was a second clock competing with the sound card's, and the
audible result was music that skipped.

TCP does not lose bytes and the sound card is the only clock with a vote, so a
relay has nothing to decide. It copies. padplay.py holds the cushion, because
that is where the device is.

Measured end to end against the source, same file and capture rig throughout:
audiotcp.py + ffplay scored +16 dB of damage; this + padplay.py scores -14.8 dB,
level with Windows playing the file directly.

THE ONE EXCEPTION IS THE VOLUME, AND ONLY ON A MAC (PAD-957). There the far end
is ffplay, which has no way to be told a new level while it plays, so the
Emulate tab's Volume and Mute did nothing at all. On a Mac the box's
playaudio.sh hands this a third argument, the volume file padbox.sh keeps in
step with the tab's audio_ctl.json ({"gain": 0-1, "muted": bool}), and the
samples are scaled here on their way through. The Windows bridge passes none:
padplay.py scales its own, and doing it twice would square the level.

EVERY 30 s IT SAYS WHAT IT SENT AND HOW LOUD (PAD-1109). A Mac user heard
nothing with the Volume at 100% while every counter the app's log could show
read healthy: the game wrote its sound, nothing was dropped, the FIFO never
backed up. Whether that sound left the box as silence or as music, and whether
a player was even attached, was said only in padaudio.log inside the box,
which the user cannot send. The [padrelay] lines are now carried into the
app's log, and this one answers both: bytes handed to the player and their
loudest sample, after the volume.
"""
import json
import math
import os
import socket
import stat
import sys
import time
from array import array

#: how often the volume file is looked at, as padplay.py's poll_gain() does
CTL_POLL_S = 0.25


def read_gain(path):
    """The level the volume file asks for: 0 when muted, else its gain held
    to 0-1. None when there is no file or it cannot be read, which leaves the
    level as it was (a file being replaced is no reason to jump to full)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        g = 0.0 if data.get("muted") else float(data.get("gain", 1.0))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return max(0.0, min(1.0, g))


def scale(b, g):
    """s16le samples at gain g. Unity and silence cost nothing; anything in
    between goes through array, because the box has no numpy and audioop
    left the stdlib in 3.13. Little-endian is assumed, as the box is."""
    if g >= 1.0:
        return b
    if g <= 0.0:
        return bytes(len(b))
    a = array("h")
    a.frombytes(b)
    return array("h", [int(s * g) for s in a]).tobytes()


class Volume:
    """The gain the volume file says, re-read at most every CTL_POLL_S and
    only when the file has changed. A pass-through when there is no file."""

    def __init__(self, path):
        self.path = path
        self.gain = 1.0
        self._seen = None
        self._next = 0.0

    def poll(self, now=None):
        if not self.path:
            return self.gain
        now = time.monotonic() if now is None else now
        if now < self._next:
            return self.gain
        self._next = now + CTL_POLL_S
        try:
            st = os.stat(self.path)
            seen = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return self.gain
        if seen == self._seen:
            return self.gain
        self._seen = seen
        g = read_gain(self.path)
        if g is not None and g != self.gain:
            self.gain = g
            print("[padrelay] volume -> %.2f" % g, flush=True)
        return self.gain


#: how often the relay says what it sent, matching the guest's [aud] summary
REPORT_S = 30.0


def peak_dbfs(peak):
    """A sample magnitude as dBFS text; 0 is digital silence, said as such."""
    if peak <= 0:
        return "digital silence"
    return "loudest %.1f dBFS" % (20 * math.log10(min(peak, 32768) / 32768.0))


class Meter:
    """Bytes and loudest sample handed to the player, said every REPORT_S."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.t0 = clock()
        self.bytes = 0
        self.peak = 0

    def add(self, b):
        n = len(b) & ~1
        if n:
            a = array("h")
            a.frombytes(b[:n])
            self.peak = max(self.peak, max(a), -min(a))
        self.bytes += len(b)

    def line(self, now=None):
        """The report line once REPORT_S has passed, else None (and resets)."""
        now = self.clock() if now is None else now
        secs = now - self.t0
        if secs < REPORT_S:
            return None
        s = ("[padrelay] last %.0f s: %d KB to the player (%.0f KB/s), %s"
             % (secs, self.bytes // 1024, self.bytes / 1024.0 / secs,
                peak_dbfs(self.peak)))
        self.t0, self.bytes, self.peak = now, 0, 0
        return s


#: how long --pipe waits for playaudio.sh to make the FIFO
PIPE_WAIT_S = 60.0


def pump(read, write, vol, say, meter=None):
    """Copy until read() ends: whole samples (a sample cut in two by the read
    waits for its other half), at the volume, metered. Returns the bytes
    written. A write error (the player went away) propagates."""
    meter = meter or Meter()
    total = 0
    odd = b""
    while True:
        b = read(65536)
        if not b:
            return total
        if vol.path:
            b = odd + b
            n = len(b) & ~1
            b, odd = b[:n], b[n:]
            b = scale(b, vol.poll())
        write(b)
        total += len(b)
        meter.add(b)
        said = meter.line()
        if said:
            say(said)


#: how far ahead of real time the paced stream runs (the cushion the Mac's
#: player eats from while the source hiccups), and how far the source may
#: run ahead before the oldest sound is dropped (padplay.py's PAD-456 rule)
LEAD_MS = 350
MAX_LATE_MS = 750
PERIOD_MS = 10


def read_fmt(path, default=(44100, 2)):
    """The guest's PCM format off its fmt file ("44100 2"), else the default."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            rate, ch = f.read().split()[:2]
        rate, ch = int(rate), int(ch)
        if rate > 0 and ch > 0:
            return rate, ch
    except (OSError, ValueError):
        pass
    return default


def paced_pump(fd, write, vol, say, rate, ch, lead_ms, clock=time.monotonic,
               sleep=time.sleep, max_late_ms=MAX_LATE_MS, period_ms=PERIOD_MS):
    """The FIFO to write() as a CONTINUOUS real-time stream (PAD-1109).

    THE MAC'S PLAYER MUST NEVER WAIT FOR SOUND. ffplay's audio callback blocks
    until it has a frame, SDL runs that callback inside the audio queue's own
    callback, and CoreAudio stops using an audio queue it is not fed fast
    enough (SDL issue 2459, in its maintainers' words) - the callback goes on
    firing, so ffplay goes on consuming, and nothing is heard again. A game's
    sound starves a player constantly: nothing at all for seconds at boot and
    between sounds, then 10 ms pieces with no lead. A file or a short tone
    never does, which is why every test played and every run was silent.

    So the FIFO is read by a thread into a buffer, and this writes exactly
    real-time bytes every period, lead_ms ahead of the clock: the game's
    sound when the buffer has it, digital silence when it has not. The
    source running more than max_late_ms ahead (a stall let go at once) is
    cut back to the lead, one skip, as padplay.py does."""
    import threading
    frame = 2 * ch
    bps = rate * frame
    lead = bps * lead_ms // 1000 // frame * frame
    ceiling = bps * max(max_late_ms, lead_ms + 100) // 1000
    period = bps * period_ms // 1000 // frame * frame
    buf = bytearray()
    lock = threading.Lock()
    done = threading.Event()
    meter = Meter(clock=clock)
    filled = [0]

    def reader():
        try:
            while True:
                b = os.read(fd, 65536)
                if not b:
                    break
                with lock:
                    buf.extend(b)
        except OSError:
            pass
        finally:
            done.set()

    threading.Thread(target=reader, daemon=True).start()
    t0 = clock()
    written = 0

    def report(chunk, fill):
        meter.add(chunk)
        filled[0] += fill
        said = meter.line()
        if said:
            if filled[0]:
                said += ", %.1f s of silence filled in" % (filled[0] / bps)
                filled[0] = 0
            say(said)

    while True:
        if done.is_set():
            # the run is over (the FIFO's writer closed): the rest goes at
            # once, and no silence after it
            with lock:
                chunk = bytes(buf[:len(buf) // frame * frame])
                buf.clear()
            if vol.path and chunk:
                chunk = scale(chunk, vol.poll())
            if chunk:
                write(chunk)
                written += len(chunk)
                report(chunk, 0)
            return written
        due = int((clock() - t0) * bps) // frame * frame + lead
        if due - written < period:
            sleep(max(0.0, (period - (due - written)) / bps))
            continue
        with lock:
            if len(buf) > ceiling:
                del buf[:(len(buf) - lead) // frame * frame]
            take = min(due - written, len(buf) // frame * frame)
            chunk = bytes(buf[:take])
            del buf[:take]
        if vol.path and chunk:
            chunk = scale(chunk, vol.poll())
        fill = due - written - len(chunk)
        write(chunk + bytes(fill))
        written += len(chunk) + fill
        report(chunk, fill)


def pipe_main(argv, out=None, clock=time.monotonic, sleep=time.sleep):
    """padrelay.py --pipe <fifo> [ctl]: the FIFO to stdout (PAD-1109).

    THE MAC'S SPEAKER READS THIS OVER `docker exec`, NOT OVER A PORT. Colima
    publishes a box port through Lima's port forwarder, and on a Mac that
    forwarder took the relay's whole stream - 11 minutes of it, at full rate,
    nothing dropped - while ffplay at the far end received 310 KB, under two
    seconds, and then nothing. A docker exec's output travels the Docker
    socket that every other step of the run already uses, and it pushes back:
    a player that stops reading stops this, and the guest's own dropped count
    then says so instead of the sound vanishing in a buffer nobody can see.
    Everything said goes to stderr; stdout is the sound."""
    out = out or sys.stdout.buffer
    if not argv:
        print("usage: padrelay.py --pipe <fifo> [ctl]", file=sys.stderr)
        return 2
    fifo = argv[0]
    vol = Volume(argv[1] if len(argv) > 1 and argv[1] else None)
    vol.poll()

    def say(s):
        print(s, file=sys.stderr, flush=True)

    t0 = clock()
    while not (os.path.exists(fifo) and stat.S_ISFIFO(os.stat(fifo).st_mode)):
        if clock() - t0 >= PIPE_WAIT_S:
            say("[padrelay] no %s after %.0f s; this run is silent"
                % (fifo, PIPE_WAIT_S))
            return 1
        sleep(0.25)
    rate, ch = read_fmt(os.path.join(os.path.dirname(fifo), "audio.fmt"))
    # PLAIN BY DEFAULT: the pacing belongs on the Mac, after the transport
    # (see pace_main); a lead here is opt-in for a transport that needs it
    lead_ms = int(os.environ.get("PAD_AUDIO_LEAD_MS", "0"))
    say("[padrelay] the player is reading %s over docker exec: %d Hz x %d ch%s"
        % (fifo, rate, ch, ", paced %d ms ahead" % lead_ms if lead_ms > 0 else ""))
    fd = os.open(fifo, os.O_RDONLY)
    total = [0]

    def write(b):
        out.write(b)
        out.flush()
        total[0] += len(b)
    try:
        if lead_ms > 0:
            paced_pump(fd, write, vol, say, rate, ch, lead_ms,
                       clock=clock, sleep=sleep)
        else:
            pump(lambda n: os.read(fd, n), write, vol, say)
    except (BrokenPipeError, OSError) as exc:
        say("[padrelay] player went away: %s" % exc)
        if out is getattr(sys.stdout, "buffer", None):
            # or the exit's own flush of the dead pipe prints a traceback
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    finally:
        say("[padrelay] %d bytes forwarded" % total[0])
        os.close(fd)
    return 0


def pace_main(argv, fd=0, out=None, clock=time.monotonic, sleep=time.sleep):
    """padrelay.py --pace <rate> <ch>: stdin to stdout, paced (PAD-1109).

    THE MAC'S OWN CUSHION, after the transport. The box's stream reaches the
    Mac through docker exec from a container that can be starved (Colima's
    machine has 2 CPUs unless told otherwise, and the renderer ran at 14 fps
    there), in lumps; a lead put on before the transport is eaten by it. Run
    by the app's own binary on the Mac (pyinstaller_entry.py's --pace) between
    docker exec and ffplay, this reads whatever arrives and writes exactly
    real-time bytes, LEAD_MS ahead, silence for what has not arrived yet:
    ffplay is never starved, however the lumps fall. The volume was applied
    in the box already, so none is applied here."""
    out = out or sys.stdout.buffer
    try:
        rate = int(argv[0]) if argv else 44100
        ch = int(argv[1]) if len(argv) > 1 else 2
    except ValueError:
        print("usage: padrelay.py --pace <rate> <channels>", file=sys.stderr)
        return 2
    lead_ms = int(os.environ.get("PAD_AUDIO_LEAD_MS", str(LEAD_MS)))

    def say(s):
        print(s, file=sys.stderr, flush=True)

    def write(b):
        out.write(b)
        out.flush()
    say("[padrelay] pacing the stream on the Mac: %d Hz x %d ch, %d ms ahead"
        % (rate, ch, lead_ms))
    total = 0
    try:
        total = paced_pump(fd, write, Volume(None), say, rate, ch, lead_ms,
                           clock=clock, sleep=sleep)
    except (BrokenPipeError, OSError) as exc:
        say("[padrelay] player went away: %s" % exc)
        if out is getattr(sys.stdout, "buffer", None):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    finally:
        say("[padrelay] %d bytes paced to the player" % total)
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--pace":
        raise SystemExit(pace_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--pipe":
        raise SystemExit(pipe_main(sys.argv[2:]))
    if len(sys.argv) < 3:
        print("usage: padrelay.py <fifo> <port> [ctl] | --pipe <fifo> [ctl]"
              " | --pace <rate> <ch>", file=sys.stderr)
        raise SystemExit(2)
    fifo, port = sys.argv[1], int(sys.argv[2])
    vol = Volume(sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None)
    vol.poll()

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # SAID IN A [play] LINE, the tag watch.sh carries into the app's log. A
    # bare traceback here stayed in padaudio.log, and the run went on with
    # picture, switches and no sound and nothing anywhere saying why
    # (PAD-978: a Spike 1 speaker left up on the same port).
    try:
        srv.bind(("0.0.0.0", port))
    except OSError as exc:
        print("[play] NO SOUND this run: the speaker's port %d is taken (%s)"
              % (port, exc.strerror or exc), flush=True)
        raise SystemExit(3)
    srv.listen(1)
    print("[padrelay] listening on %d for a player" % port, flush=True)

    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("[padrelay] player connected from %s" % (addr,), flush=True)

        # OPENED ONLY NOW, and that ordering is load-bearing. Opening a FIFO for
        # read blocks until a writer exists, so an ffmpeg told to read the FIFO and
        # listen on a socket would sit on the empty FIFO and never open the socket
        # at all - the player would find nothing to connect to and the run was
        # silent. Listen first, open second.
        fd = os.open(fifo, os.O_RDONLY)
        total = [0]

        def send(b, conn=conn):
            conn.sendall(b)
            total[0] += len(b)
        try:
            pump(lambda n: os.read(fd, n), send, vol,
                 lambda s: print(s, flush=True))
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            print("[padrelay] player went away: %s" % exc, flush=True)
        finally:
            print("[padrelay] %d bytes forwarded" % total[0], flush=True)
            os.close(fd)
            conn.close()


if __name__ == "__main__":
    main()
