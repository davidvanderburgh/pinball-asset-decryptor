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
  5. the front Volume+ / Volume- buttons (byte 1 bits 5 / 6, item 120): they
     step the menu's level by 5 within volume_max=, never move the highlight,
     play the move sound at the new level (the --audio-dump's clicks peak at
     exactly the tone times each gain), draw the indicator (the headless frame
     differs from an untouched menu's in the middle of the card row, and is
     the untouched frame again once it has gone), and the settled level is
     kept in --volume-file and used by the next run; --volume above the
     ceiling is cut to it.  The file names the card's volume= it was set
     under (PAD-216): a card with another volume=, or a file with no card
     level (an older menu's), starts at the card's own volume= instead.
"""
import math
import os
import re
import struct
import subprocess
import sys
import threading
import time
import tty
import wave

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


def ppm_region(path, x0, y0, x1, y1):
    """The RGB bytes of one rectangle of a P6 frame (gfx_write_ppm's header)."""
    data = open(path, "rb").read()
    m = re.match(rb"P6\n(\d+) (\d+)\n255\n", data)
    if not m:
        raise SystemExit("jjpio_test: FAIL %s is not a P6 frame" % path)
    w = int(m.group(1))
    px = data[m.end():]
    return b"".join(px[(y * w + x0) * 3:(y * w + x1) * 3] for y in range(y0, y1))


def click_peaks(dump):
    """Each move sound in a raw s16le stereo mix: the left channel's non-zero
    runs, split wherever 50 ms of silence falls, and the peak of each."""
    raw = open(dump, "rb").read() if os.path.exists(dump) else b""
    n = len(raw) // 4
    left = struct.unpack("<%dh" % (2 * n), raw[:4 * n])[0::2]
    peaks, cur, quiet = [], 0, 0
    for s in left:
        if s:
            cur = max(cur, abs(s))
            quiet = 0
        elif cur:
            quiet += 1
            if quiet > 2205:
                peaks.append(cur)
                cur, quiet = 0, 0
    if cur:
        peaks.append(cur)
    return peaks


def volume_buttons(binp, t, font):
    ok = True
    media = os.path.join(t, "jjpio_media")
    os.makedirs(media, exist_ok=True)
    tone = [int(16000 * math.sin(2 * math.pi * 1000 * i / 44100.0)) for i in range(int(0.04 * 44100))]
    tone_peak = max(abs(x) for x in tone)
    with wave.open(os.path.join(media, "move.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"".join(struct.pack("<hh", x, x) for x in tone))
    conf = os.path.join(t, "jjpio_vol.conf")

    def write_conf(level):
        with open(conf, "w") as f:
            f.write("image=rootA|A|a\nimage=rootB|B|b\ndefault=0\ntimeout=10\n"
                    "media=%s\nsound_move=move.wav\nvolume=%d\nvolume_max=40\n" % (media, level))
    write_conf(20)
    volfile = os.path.join(t, "jjpio.volume")
    if os.path.exists(volfile):
        os.unlink(volfile)

    def run(tag, presses, extra=()):
        dump = os.path.join(t, "jjpio_%s.raw" % tag)
        board = Board()
        board.start()
        proc, choice, log = run_sel(binp, t, font, conf, tag, board,
                                    ["--volume-file", volfile, "--audio-dump", dump] + list(extra), 12)
        time.sleep(1.5)
        for p in presses:
            if p == "wait":
                time.sleep(2.6)                   # past the indicator's 2 s
            else:
                board.press(1, 5 if p == "+" else 6)
        board.press(3, 0)                         # START
        rc, out, err = finish(proc, tag)
        board.stop = True
        board.join(timeout=2)
        got = open(choice).read().strip() if os.path.exists(choice) else None
        logtxt = open(log).read() if os.path.exists(log) else ""
        keys = [l.split("key: ", 1)[1].strip() for l in out.splitlines() if "[select] key: " in l]
        kept = open(volfile).read().split("\n")[0].strip() if os.path.exists(volfile) else None
        return rc, got, out, logtxt, keys, kept, dump, os.path.join(t, "jjpio_%s.ppm" % tag)

    def fail(msg):
        print("jjpio_test: FAIL (volume) " + msg)
        return False

    # A: up, up, down, the indicator goes, up again, START
    rc, got, out, logtxt, keys, kept, dump, _ = run("vol", ["+", "+", "-", "wait", "+"])
    if rc != 0 or got != "0":
        ok = fail("exit %d, choice %r: a volume button moved the highlight (expected '0')" % (rc, got))
    if keys != ["plus", "plus", "minus", "plus", "start"]:
        ok = fail("key sequence %r" % keys)
    for want in ("[select] volume: 20 -> 25 (of 40)", "[select] volume: 25 -> 30 (of 40)",
                 "[select] volume: 30 -> 25 (of 40)"):
        if want not in out:
            ok = fail("stdout lacks %r" % want)
    for want in ("volume: 20 of 40 (conf volume=); Volume+/- step it by 5, kept in " + volfile,
                 "volume: indicator off at 25", "volume: 25 remembered in " + volfile,
                 "volume: 30 remembered in " + volfile):
        if want not in logtxt:
            ok = fail("log lacks %r" % want)
    if kept != "30":
        ok = fail("%s holds %r, expected '30' (the level at START)" % (volfile, kept))
    whole = open(volfile).read() if os.path.exists(volfile) else None
    if whole != "30\nconf 20\n":
        ok = fail("%s is %r, expected the level and the card's volume=20 under it" % (volfile, whole))
    peaks = click_peaks(dump)
    want_peaks = [tone_peak * g // 256 for g in (64, 76, 64, 76)]   # gain_q8 of 25, 30, 25, 30
    if len(peaks) != 4 or any(abs(a - b) > 2 for a, b in zip(peaks, want_peaks)):
        ok = fail("move-sound peaks %r, expected %r (tone %d times each level's gain)"
                  % (peaks, want_peaks, tone_peak))
    else:
        print("jjpio_test: volume steps heard at peaks %r (tone %d)" % (peaks, tone_peak))

    # B: the remembered 30 is used; up to the cap and one past it; START with the indicator up
    rc, got, out, logtxt, keys, kept, _, ppm_up = run("voltop", ["+", "+", "+"])
    if "volume: 30 of 40 (remembered in %s)" % volfile not in logtxt:
        ok = fail("the second run did not start at the remembered 30:\n%s"
                  % "\n".join(l for l in logtxt.splitlines() if "volume" in l))
    for want in ("[select] volume: 35 -> 40 (of 40)", "[select] volume: 40 -> 40 (of 40), at the top"):
        if want not in out:
            ok = fail("stdout lacks %r" % want)
    if kept != "40":
        ok = fail("%s holds %r after the cap, expected '40'" % (volfile, kept))

    # C: down once, let the indicator go, START - the frame is the untouched menu again
    rc, got, out, logtxt, keys, kept, _, ppm_gone = run("volgone", ["-", "wait"])
    if kept != "35":
        ok = fail("%s holds %r, expected '35'" % (volfile, kept))

    # D: nothing pressed, and --volume past the ceiling
    rc, got, out, logtxt, keys, kept, _, ppm_none = run("volnone", [], ["--volume", "90"])
    if "volume: 90 (--volume) is above the ceiling, 40 is used" not in logtxt:
        ok = fail("--volume 90 was not cut to the ceiling")
    if kept != "35":
        ok = fail("an untouched menu rewrote %s (%r, expected '35')" % (volfile, kept))

    # E (PAD-216): the card is rebuilt with volume=8 and perm kept - the 35
    # remembered under volume=20 is not used; the card's 8 is, and stays until
    # a button is pressed
    write_conf(8)
    rc, got, out, logtxt, keys, kept, _, _ = run("volnewconf", [])
    if "volume: remembered 35 was set under volume=20; this card says 8" not in logtxt:
        ok = fail("the rebuilt card did not set the old remembered level aside:\n%s"
                  % "\n".join(l for l in logtxt.splitlines() if "volume" in l))
    if "volume: 8 of 40 (conf volume=)" not in logtxt:
        ok = fail("the rebuilt card did not start at its own volume=8")
    rc, got, out, logtxt, keys, kept, _, _ = run("volnewconf2", ["+"])
    if "[select] volume: 8 -> 10 (of 40)" not in out:
        ok = fail("Volume+ on the rebuilt card did not step from 8")
    whole = open(volfile).read() if os.path.exists(volfile) else None
    if whole != "10\nconf 8\n":
        ok = fail("%s is %r after a press on the volume=8 card, expected 10 under volume=8" % (volfile, whole))
    rc, got, out, logtxt, keys, kept, _, _ = run("volnewconf3", [])
    if "volume: 10 of 40 (remembered in %s)" % volfile not in logtxt:
        ok = fail("a level set under the same card's volume= was not remembered")

    # F: a file an older menu wrote (a level, no card level) is not used
    with open(volfile, "w") as f:
        f.write("40\n")
    rc, got, out, logtxt, keys, kept, _, _ = run("vollegacy", [])
    if "names no card level" not in logtxt or "volume: 8 of 40 (conf volume=)" not in logtxt:
        ok = fail("an older menu's remembered 40 was used over the card's volume=8:\n%s"
                  % "\n".join(l for l in logtxt.splitlines() if "volume" in l))
    if kept != "40":
        ok = fail("an untouched menu rewrote the older file (%r)" % kept)

    box = (400, 300, 960, 440)       # the middle of the card row at 1360x768 (draw_volume)
    up, gone, none = (ppm_region(p, *box) for p in (ppm_up, ppm_gone, ppm_none))
    if up == none:
        ok = fail("no indicator in the frame drawn while it was up")
    if gone != none:
        ok = fail("the indicator was still in the frame after it should have gone")
    if ok:
        print("jjpio_test: volume OK (20 -> 25 -> 30 -> 25 -> 30 kept; remembered 30 -> cap 40; "
              "indicator up and gone; --volume 90 cut to 40; a new card's volume= beats the old level)")
    return ok


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
    for want in ("jjpio: %s open (LEFT 1.0, RIGHT 1.2, START 3.0, VOL+ 1.5, VOL- 1.6, active low)" % board.path,
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

    # --- 5. the volume buttons ---
    if not volume_buttons(binp, t, font):
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
