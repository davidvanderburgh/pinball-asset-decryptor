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
that does not exist still exits 0 in the countdown time.

The emulator comes from the environment ($QEMU, exported by the Makefile),
not argv: the rig's teardown does pkill -f 'arm-binfmt|qemu-arm' and this
script's own command line must not match it."""
import os
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
    it arrived, so the test can ask 'was there sound after t?'."""

    def __init__(self, fd):
        super().__init__(daemon=True)
        self.fd = fd
        self.chunks = []          # (monotonic time, bytes)
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                time.sleep(0.005)
                continue
            if data:
                self.chunks.append((time.monotonic(), data))
            else:
                time.sleep(0.005)   # no writer yet / writer gone: EOF-ish

    def loud_since(self, t):
        """True when a chunk that arrived after t holds a non-zero sample."""
        return any(any(d) for (ts, d) in self.chunks if ts >= t)

    def total(self):
        return sum(len(d) for _, d in self.chunks)


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


if __name__ == "__main__":
    main()
