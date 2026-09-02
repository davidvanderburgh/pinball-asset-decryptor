#!/usr/bin/env python3
"""QEMU=qemu-arm-static padsw_test.py ROOT BIN T TABLES [FONT]

Drives codeselect --input padsw the way padglhost does: a 4096-byte padsw
file (magic 'PADS', gen at 4, held[] at 8), RIGHT held for 100 ms then
released, then START held. Expects '[select] key: right', '[select] chose 1'
and a choice file holding 1 (highlight started at 0).

The sound path is exercised the way the rig's player would see it: the test
creates the FIFO and holds its read end open (non-blocking) before the
selector starts, and the selector runs with --audio fifo:<that> and
--audio-fmt. Checks: the fmt file says '44100 2'; nothing but silence flows
before RIGHT; the move sound follows RIGHT; the confirm sound follows START
and the program only exits once it has played (>= 0.9 s for a 1.0 s WAV);
the --audio-dump holds the same non-silent mix. A second run with a FIFO
that does not exist still exits 0 in the countdown time. A third run loses
its reader mid-way (the read end is closed, as the rig's relay does when its
Windows player dies, and the fmt file is removed, as a restarted playaudio.sh
does) and gets it back 4 s later: the loss and the 3 s gap are logged, the
fmt file is rewritten, the selector reconnects and drops only the gap.

The emulator comes from the environment ($QEMU, exported by the Makefile),
not argv: the rig's teardown does pkill -f 'arm-binfmt|qemu-arm' and this
script's own command line must not match it."""
import os
import re
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmedia  # noqa: E402

MAGIC = 0x53444150
OFF_GEN = 4
OFF_HELD = 8


def table_ids(path):
    ids = {}
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split(None, 4)
            if len(parts) < 4:
                continue
            sid, _num, node, bit = (int(x) for x in parts[:4])
            ids[(node, bit)] = sid
    return ids


def set_held(path, sid, value):
    with open(path, "r+b") as f:
        f.seek(OFF_HELD + sid)
        f.write(bytes([value]))
        f.seek(OFF_GEN)
        gen = struct.unpack("<I", f.read(4))[0]
        f.seek(OFF_GEN)
        f.write(struct.pack("<I", gen + 1))


class FifoReader(threading.Thread):
    """Drains the FIFO like padrelay would and keeps every chunk with the time
    it arrived, so the test can ask 'was there sound after t?'. drop_end()
    closes the read end (the selector's next write gets EPIPE, as when the
    rig's relay loses its player); take_end() opens it again."""

    def __init__(self, fd):
        super().__init__(daemon=True)
        self.fd = fd
        self.chunks = []          # (monotonic time, bytes)
        self.stop = False

    def run(self):
        while not self.stop:
            fd = self.fd
            if fd < 0:
                time.sleep(0.005)
                continue
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                time.sleep(0.005)
                continue
            except OSError:         # the end was dropped under this read
                time.sleep(0.005)
                continue
            if data:
                self.chunks.append((time.monotonic(), data))
            else:
                time.sleep(0.005)   # no writer yet / writer gone: EOF-ish

    def drop_end(self):
        fd, self.fd = self.fd, -1
        time.sleep(0.02)            # a read in flight returns first
        os.close(fd)

    def take_end(self, path):
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)

    def loud_since(self, t):
        """True when a chunk that arrived after t holds a non-zero sample."""
        return any(any(d) for (ts, d) in self.chunks if ts >= t)

    def total(self):
        return sum(len(d) for _, d in self.chunks)

    def total_since(self, t):
        return sum(len(d) for (ts, d) in self.chunks if ts >= t)


def main():
    root, binp, t, tables = sys.argv[1:5]
    qemu = os.environ.get("QEMU", "qemu-arm-static")
    font = sys.argv[5] if len(sys.argv) > 5 and os.path.isfile(sys.argv[5]) else \
        os.path.join(root, "usr/local/spike/VeraMono.ttf")
    os.makedirs(t, exist_ok=True)
    media = os.path.join(t, "padsw_media")
    mkmedia.make(media)
    conf = os.path.join(t, "padsw.conf")
    with open(conf, "w") as f:
        f.write("image=p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code|art0.png||\n"
                "image=p7|TMNT 1987|1.59.0 - upscaled cartoon retheme|art1.png|anim1.gif|\n"
                "sound_move=move.wav\nsound_confirm=confirm.wav\nvolume=60\n"
                "default=0\ntimeout=10\n")
    ids = table_ids(tables)
    right = ids.get((8, 24))
    start = ids.get((1, 11))
    if right is None or start is None:
        raise SystemExit("padsw_test: %s has no (8,24)/(1,11) rows" % tables)
    print("padsw_test: ids from %s: right %d start %d" % (tables, right, start))

    padsw = os.path.join(t, "padsw")
    with open(padsw, "wb") as f:
        f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
    choice = os.path.join(t, "padsw.choice")
    last = os.path.join(t, "padsw.last")
    fifo = os.path.join(t, "audio.fifo")
    fmt = os.path.join(t, "audio.fmt")
    dump = os.path.join(t, "padsw_mix.raw")
    for p in (choice, last, fifo, fmt, dump):
        if os.path.exists(p):
            os.unlink(p)
    os.mkfifo(fifo)
    rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    reader = FifoReader(rfd)
    reader.start()

    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "padsw.ppm"), "--conf", conf,
           "--input", "padsw", "--padsw", padsw, "--tables", tables, "--timeout", "4",
           "--out", choice, "--last", last, "--log", os.path.join(t, "padsw.log"),
           "--font", font, "--no-invert", "--media", media,
           "--audio", "fifo:" + fifo, "--audio-fmt", fmt, "--audio-dump", dump]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    quiet_before = reader.total()
    quiet_loud = reader.loud_since(0)
    t_right = time.monotonic()
    set_held(padsw, right, 1)
    time.sleep(0.1)
    set_held(padsw, right, 0)
    time.sleep(0.5)
    loud_after_right = reader.loud_since(t_right)
    t_start = time.monotonic()
    set_held(padsw, start, 1)
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("padsw_test: FAIL codeselect did not exit\n%s\n%s" % (out, err))
    t_exit = time.monotonic()
    time.sleep(0.3)                     # let the reader drain the tail
    reader.stop = True
    reader.join(timeout=2)
    os.close(rfd)
    dt = t_exit - t0
    confirm_wait = t_exit - t_start
    sys.stdout.write(out)
    ok = True
    if proc.returncode != 0:
        print("padsw_test: FAIL exit %d" % proc.returncode)
        ok = False
    got = open(choice).read().strip() if os.path.exists(choice) else None
    if got != "1":
        print("padsw_test: FAIL choice file holds %r, expected '1'" % got)
        ok = False
    for want in ("[select] key: right", "[select] key: start", "[select] chose 1"):
        if want not in out:
            print("padsw_test: FAIL stdout lacks %r" % want)
            ok = False
    if "[select] key: left" in out:
        print("padsw_test: FAIL a spurious left key")
        ok = False
    # --- sound ---
    fmt_got = open(fmt).read().strip() if os.path.exists(fmt) else None
    if fmt_got != "44100 2":
        print("padsw_test: FAIL audio.fmt holds %r, expected '44100 2'" % fmt_got)
        ok = False
    if quiet_before == 0:
        print("padsw_test: FAIL nothing reached the FIFO before RIGHT (silence should stream)")
        ok = False
    if quiet_loud:
        print("padsw_test: FAIL the FIFO was not silent before the first key")
        ok = False
    if not loud_after_right:
        print("padsw_test: FAIL no move sound after RIGHT (%d bytes drained)" % reader.total())
        ok = False
    if not reader.loud_since(t_start):
        print("padsw_test: FAIL no confirm sound after START")
        ok = False
    if confirm_wait < 0.9:
        print("padsw_test: FAIL exited %.2f s after START; the 1.0 s confirm sound must finish first" % confirm_wait)
        ok = False
    if confirm_wait > 4.0:
        print("padsw_test: FAIL exited %.2f s after START (cap is 8 s, expected ~1.2 s)" % confirm_wait)
        ok = False
    mix = open(dump, "rb").read() if os.path.exists(dump) else b""
    if len(mix) < 4 * 44100 or not any(mix):
        print("padsw_test: FAIL the mix dump is missing, short or silent (%d bytes)" % len(mix))
        ok = False
    for want in ("audio: fifo %s open" % fifo, "media: 2 art, 1 anim (4 frames), 0 music, move=y confirm=y",
                 " frames written, "):
        if want not in err:
            print("padsw_test: FAIL log lacks %r" % want)
            ok = False
    if " 0 dropped" not in err:
        print("padsw_test: note: some frames were dropped (the reader thread was slow):",
              [l for l in err.splitlines() if "dropped" in l])
    if not ok:
        sys.stderr.write(err)
        raise SystemExit(1)
    print("padsw_test: OK (right -> highlight 1, start -> chose 1, confirm held exit %.2f s, "
          "%d FIFO bytes, %.1f s, exit 0)" % (confirm_wait, reader.total(), dt))

    # --- a FIFO that does not exist: still exits 0 on the countdown ---
    for p in (choice, last):
        if os.path.exists(p):
            os.unlink(p)
    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "padsw2.ppm"), "--conf", conf,
           "--input", "none", "--timeout", "1", "--out", choice, "--last", last,
           "--log", os.path.join(t, "padsw2.log"), "--font", font, "--no-invert", "--media", media,
           "--audio", "fifo:/nonexistent/dir/audio.fifo", "--audio-fmt", os.path.join(t, "audio2.fmt")]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("padsw_test: FAIL (no fifo) codeselect did not exit")
    dt = time.monotonic() - t0
    if proc.returncode != 0 or "[select] chose 0" not in out:
        sys.stderr.write(err)
        raise SystemExit("padsw_test: FAIL (no fifo) exit %d\n%s" % (proc.returncode, out))
    if "audio: fifo /nonexistent/dir/audio.fifo: " not in err:
        sys.stderr.write(err)
        raise SystemExit("padsw_test: FAIL (no fifo) the missing FIFO was not logged")
    print("padsw_test: OK (missing fifo: chose 0 on the countdown, %.1f s, exit 0)" % dt)

    # --- the reader goes away and comes back: EPIPE, ENXIO retries, reopen ---
    # What happened in the rig on 2026-09-02: the relay closed the read end
    # when its Windows player died 31 s in (and there, nothing ever reopened
    # it). Here it comes back after 4 s. The selector must log the loss once,
    # name the 3 s gap, keep the fmt file alive (a restarted playaudio.sh
    # removes it and waits for a fresh one), reconnect within its 100 ms
    # retry, and drop only the gap.
    for p in (choice, last):
        if os.path.exists(p):
            os.unlink(p)
    fifo3 = os.path.join(t, "audio3.fifo")
    fmt3 = os.path.join(t, "audio3.fmt")
    for p in (fifo3, fmt3):
        if os.path.exists(p):
            os.unlink(p)
    os.mkfifo(fifo3)
    reader = FifoReader(os.open(fifo3, os.O_RDONLY | os.O_NONBLOCK))
    reader.start()
    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "padsw3.ppm"), "--conf", conf,
           "--input", "none", "--timeout", "7", "--out", choice, "--last", last,
           "--log", os.path.join(t, "padsw3.log"), "--font", font, "--no-invert", "--media", media,
           "--audio", "fifo:" + fifo3, "--audio-fmt", fmt3]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    had_before = reader.total()
    reader.drop_end()                   # the relay's player died
    t_lost = time.monotonic()
    time.sleep(0.3)
    os.unlink(fmt3)                     # a restarted playaudio.sh's rm -f
    time.sleep(3.7)                     # 4 s without a reader in all
    fmt_back = open(fmt3).read().strip() if os.path.exists(fmt3) else None
    reader.take_end(fifo3)              # a fresh player attached: the relay reopened
    t_back = time.monotonic()
    try:
        out, err = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("padsw_test: FAIL (reader loss) codeselect did not exit\n%s\n%s" % (out, err))
    time.sleep(0.3)
    reader.stop = True
    reader.join(timeout=2)
    os.close(reader.fd)
    gap = t_back - t_lost
    ok = True
    if proc.returncode != 0 or "[select] chose 0" not in out:
        print("padsw_test: FAIL (reader loss) exit %d\n%s" % (proc.returncode, out))
        ok = False
    if had_before == 0:
        print("padsw_test: FAIL (reader loss) nothing flowed before the drop")
        ok = False
    if err.count("audio: fifo reader went away, reopening") != 1:
        print("padsw_test: FAIL (reader loss) the loss was not logged exactly once")
        ok = False
    if err.count("audio: fifo %s open" % fifo3) != 2:
        print("padsw_test: FAIL (reader loss) expected two opens (start, and after the reader came back)")
        ok = False
    if "audio: fifo %s open again after" % fifo3 not in err:
        print("padsw_test: FAIL (reader loss) the reopen was not logged as one")
        ok = False
    if "audio: no fifo reader for 3 s (it went away" not in err:
        print("padsw_test: FAIL (reader loss) the 3 s gap was not named")
        ok = False
    if fmt_back != "44100 2":
        print("padsw_test: FAIL (reader loss) the removed fmt file was not rewritten (holds %r)" % fmt_back)
        ok = False
    if "(rewritten: it had been removed)" not in err:
        print("padsw_test: FAIL (reader loss) the fmt rewrite was not logged")
        ok = False
    after = reader.total_since(t_back)
    if after < 4 * 44100:               # >= 1 s of audio once the reader was back
        print("padsw_test: FAIL (reader loss) only %d bytes reached the reader after it came back" % after)
        ok = False
    if not reader.loud_since(t_back):
        print("padsw_test: FAIL (reader loss) no confirm sound after the reader came back")
        ok = False
    m = re.search(r"audio: (\d+) frames written, (\d+) dropped", err)
    written, dropped = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
    lo, hi = int(gap * 44100 * 0.8), int((gap + 1.0) * 44100)
    if not lo <= dropped <= hi:
        print("padsw_test: FAIL (reader loss) %d frames dropped for a %.1f s gap (expected %d..%d)"
              % (dropped, gap, lo, hi))
        ok = False
    if written < 3 * 44100:
        print("padsw_test: FAIL (reader loss) only %d frames written" % written)
        ok = False
    if not ok:
        sys.stderr.write(err)
        raise SystemExit(1)
    print("padsw_test: OK (reader loss: EPIPE at %.1f s, %.1f s without a reader, reconnected, "
          "%d frames dropped = %.2f s, %d bytes after, %.1f s, exit 0)"
          % (t_lost - t0, gap, dropped, dropped / 44100.0, after, time.monotonic() - t0))


if __name__ == "__main__":
    main()
