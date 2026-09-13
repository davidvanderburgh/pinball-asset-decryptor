#!/usr/bin/env python3
"""jjpio_test.py BIN T [FONT] - drives jjpselect --input jjpio through a pty
that stands in for a JJP machine's /dev/jjpio100.

The board side of the protocol is what jjpcrt (JJP's own installer helper)
expects of the real driver: a 64-byte IN frame per read, whose bytes 0..3
are the cabinet buttons active LOW (idle 0xff), and a 64-byte all-zero OUT
frame written back after every read.  The test plays the board: it streams
idle frames at 100 Hz, holds a bit low for ~100 ms to press a button, and
drains + inspects what the selector writes.

  1. buttons: RIGHT -> highlight 1, LEFT -> 0, RIGHT -> 1, START -> chose 1;
     '[select] key: right/left/start' in order, the choice file holds 1,
     exit 0, and every frame the selector wrote back was 64 zero bytes.
  2. --learn logs the cabinet bytes on change: 'ff fe ff ff' for LEFT.
  3. key_*= in the conf move a button: with key_left=2.5, byte 1 bit 0 is no
     longer LEFT (nothing happens) and byte 2 bit 5 is (key: left).
  4. no board at all (--jjpio names a path that does not exist): the menu
     still runs, times out and writes the default - a dead button never
     keeps a machine from booting - and the log says so once.
"""
import os
import subprocess
import sys
import threading
import time
import tty

FRAME = 64
IDLE = bytes([0xff, 0xff, 0xff, 0xff]) + bytes(FRAME - 4)


class Board(threading.Thread):
    """The I/O board on a pty: streams the current frame to the selector at
    100 Hz and keeps everything the selector writes back."""

    def __init__(self):
        super().__init__(daemon=True)
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        tty.setraw(self.master)
        os.set_blocking(self.master, False)
        self.path = os.ttyname(self.slave)
        self.frame = bytearray(IDLE)
        self.written = bytearray()
        self.stop = False
        self.lock = threading.Lock()

    def run(self):
        while not self.stop:
            with self.lock:
                f = bytes(self.frame)
            try:
                os.write(self.master, f)
            except (BlockingIOError, OSError):
                pass
            try:
                while True:
                    d = os.read(self.master, 4096)
                    if not d:
                        break
                    self.written += d
            except (BlockingIOError, OSError):
                pass
            time.sleep(0.01)

    def press(self, byte, bit, hold=0.12):
        with self.lock:
            self.frame[byte] &= ~(1 << bit) & 0xff
        time.sleep(hold)
        with self.lock:
            self.frame[byte] |= 1 << bit
        time.sleep(0.15)


def run_sel(binp, t, font, conf, tag, board, extra, timeout):
    choice = os.path.join(t, "jjpio_%s.choice" % tag)
    last = os.path.join(t, "jjpio_%s.last" % tag)
    log = os.path.join(t, "jjpio_%s.log" % tag)
    for p in (choice, last, log):
        if os.path.exists(p):
            os.unlink(p)
    cmd = [binp, "--headless", os.path.join(t, "jjpio_%s.ppm" % tag), "--conf", conf,
           "--input", "jjpio", "--jjpio", board.path if board else "/nonexistent/jjpio",
           "--timeout", str(timeout), "--out", choice, "--last", last, "--log", log,
           "--font", font, "--no-invert", "--audio", "none", "--default", "0"] + extra
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True), choice, log


def finish(proc, tag, limit=20):
    try:
        out, err = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("jjpio_test: FAIL [%s] the selector did not exit\n%s\n%s" % (tag, out, err))
    sys.stdout.write(out)
    return proc.returncode, out, err


def main():
    binp, t = sys.argv[1:3]
    font = sys.argv[3] if len(sys.argv) > 3 and os.path.isfile(sys.argv[3]) else \
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    os.makedirs(t, exist_ok=True)
    conf = os.path.join(t, "jjpio.conf")
    with open(conf, "w") as f:
        f.write("image=rootA|GUNS N' ROSES 3.03|Stock JJP code\n"
                "image=rootB|CHAKA'S LOTLJ|Land of the Lost Jungle retheme\n"
                "default=0\ntimeout=10\n")
    ok = True

    # --- 1. the buttons, at jjpcrt's positions ---
    board = Board()
    board.start()
    proc, choice, log = run_sel(binp, t, font, conf, "buttons", board, ["--learn"], 12)
    time.sleep(1.5)                       # the menu is up and the board is streaming
    board.press(1, 2)                     # RIGHT
    board.press(1, 0)                     # LEFT
    board.press(1, 2)                     # RIGHT
    board.press(3, 0)                     # START
    rc, out, err = finish(proc, "buttons")
    board.stop = True
    board.join(timeout=2)
    got = open(choice).read().strip() if os.path.exists(choice) else None
    if rc != 0:
        print("jjpio_test: FAIL exit %d\n%s" % (rc, err))
        ok = False
    if got != "1":
        print("jjpio_test: FAIL choice file holds %r, expected '1'" % got)
        ok = False
    keys = [l.split("key: ", 1)[1].strip() for l in out.splitlines() if "[select] key: " in l]
    if keys != ["right", "left", "right", "start"]:
        print("jjpio_test: FAIL key sequence %r, expected right, left, right, start" % keys)
        ok = False
    if "[select] chose 1" not in out:
        print("jjpio_test: FAIL stdout lacks '[select] chose 1'")
        ok = False
    w = bytes(board.written)
    if len(w) < FRAME:
        print("jjpio_test: FAIL the selector wrote %d bytes back, expected whole idle frames" % len(w))
        ok = False
    elif any(w):
        print("jjpio_test: FAIL the selector wrote a NON-ZERO byte to the board (%d bytes, first non-zero at %d)"
              % (len(w), next(i for i, b in enumerate(w) if b)))
        ok = False
    else:
        print("jjpio_test: %d zero bytes written back (%d idle frames)" % (len(w), len(w) // FRAME))
    logtxt = open(log).read() if os.path.exists(log) else ""
    for want in ("jjpio: %s open (LEFT 1.0, RIGHT 1.2, START 3.0, active low)" % board.path,
                 "jjpio: learn: cabinet bytes ff fe ff ff",      # LEFT held
                 "jjpio: learn: cabinet bytes ff fb ff ff",      # RIGHT held
                 "jjpio: learn: cabinet bytes ff ff ff fe",      # START held
                 "frames read,"):
        if want not in logtxt:
            print("jjpio_test: FAIL log lacks %r" % want)
            ok = False

    # --- 3. key_*= moves a button ---
    conf2 = os.path.join(t, "jjpio_keys.conf")
    with open(conf2, "w") as f:
        f.write("image=rootA|A|a\nimage=rootB|B|b\ndefault=0\ntimeout=10\n"
                "key_left=2.5\nkey_start=9.9\n")     # the second is refused: bit 9
    board = Board()
    board.start()
    proc, choice, log = run_sel(binp, t, font, conf2, "keys", board, [], 12)
    time.sleep(1.5)
    board.press(1, 0)                     # the OLD left: nothing
    board.press(2, 5)                     # the NEW left: highlight 0 -> 1 (wraps)
    board.press(3, 0)                     # START, still at the default position
    rc, out, err = finish(proc, "keys")
    board.stop = True
    board.join(timeout=2)
    got = open(choice).read().strip() if os.path.exists(choice) else None
    keys = [l.split("key: ", 1)[1].strip() for l in out.splitlines() if "[select] key: " in l]
    if rc != 0 or got != "1" or keys != ["left", "start"]:
        print("jjpio_test: FAIL key_left=2.5: exit %d, choice %r, keys %r (expected 0, '1', [left, start])"
              % (rc, got, keys))
        ok = False
    logtxt = open(log).read() if os.path.exists(log) else ""
    if "LEFT 2.5, RIGHT 1.2, START 3.0" not in logtxt:
        print("jjpio_test: FAIL the remapped positions are not in the log")
        ok = False
    if "key_start=9.9 is not <0-63>.<0-7>: the default position is used" not in logtxt:
        print("jjpio_test: FAIL a bad key_start= was not warned about")
        ok = False

    # --- 4. no board ---
    proc, choice, log = run_sel(binp, t, font, conf, "noboard", None, [], 2)
    t0 = time.monotonic()
    rc, out, err = finish(proc, "noboard", limit=10)
    dt = time.monotonic() - t0
    got = open(choice).read().strip() if os.path.exists(choice) else None
    logtxt = open(log).read() if os.path.exists(log) else ""
    if rc != 0 or got != "0":
        print("jjpio_test: FAIL without a board: exit %d, choice %r (expected 0, '0')" % (rc, got))
        ok = False
    if dt > 6:
        print("jjpio_test: FAIL without a board the 2 s countdown took %.1f s" % dt)
        ok = False
    if logtxt.count("jjpio: no I/O board node") != 1:
        print("jjpio_test: FAIL the missing board was logged %d times, expected once"
              % logtxt.count("jjpio: no I/O board node"))
        ok = False

    if not ok:
        raise SystemExit(1)
    print("jjpio_test: OK")


if __name__ == "__main__":
    main()
