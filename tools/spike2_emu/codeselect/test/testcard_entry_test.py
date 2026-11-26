#!/usr/bin/env python3
"""QEMU=qemu-arm-static testcard_entry_test.py ROOT BIN T [FONT]

THE TEST CARD ENTRY on a game card (Simon, 2026-11-23: "a 1.16 vanilla plus the test
card ... default to the test card on first boot, but show the menu").  An image line
whose device is the word `testcard` is a menu entry like a game's, but boots nothing:

  1. default= names it, so the countdown opens the test card screens - and the
     last-choice file remembers it while they are up;
  2. ACTION on their top screen comes back to the menu, on the entry;
  3. LEFT + START then boots the game: the choice file and the last-choice file
     both say the game, and nothing was ever handed over for the entry;
  4. a card that remembers the entry and has no menu at power-up (boot_menu=hidden)
     opens the test card screens by itself after the start-up screen.

Driven through the rig's keyboard file by button name, as settings_test.py does
(no switch table, no PIL).  The emulator comes from the environment ($QEMU), never
argv: the rig's teardown does pkill -f 'arm-binfmt|qemu-arm'."""
import os
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmedia  # noqa: E402

MAGIC = 0x53444150
OFF_CAB = 1068
CAB_IDX = {"left": 0, "right": 1, "start": 2, "action": 3, "select": 4,
           "plus": 5, "minus": 6, "back": 7}


def fail(msg, *more):
    print("testcard_entry_test: FAIL %s" % msg)
    for m in more:
        print(m)
    raise SystemExit(1)


def press(sw, button, held=0.15, after=0.6):
    with open(sw, "r+b") as f:
        f.seek(OFF_CAB + CAB_IDX[button])
        f.write(b"\x01")
    time.sleep(held)
    with open(sw, "r+b") as f:
        f.seek(OFF_CAB + CAB_IDX[button])
        f.write(b"\x00")
    time.sleep(after)


def main():
    root, binp, t = sys.argv[1:4]
    qemu = os.environ.get("QEMU", "qemu-arm-static")
    font = sys.argv[4] if len(sys.argv) > 4 and os.path.isfile(sys.argv[4]) else \
        os.path.join(root, "usr/local/spike/VeraMono.ttf")
    t = os.path.join(t, "testcard_entry")
    os.makedirs(t, exist_ok=True)
    media = os.path.join(t, "media")
    mkmedia.make(media)
    tdir = os.path.join(t, "padtest")
    os.makedirs(tdir, exist_ok=True)
    with open(os.path.join(media, "art0.png"), "rb") as s, open(os.path.join(tdir, "art0.png"), "wb") as d:
        d.write(s.read())
    no_list = os.path.join(t, "no_such_table_dir", "switch_list.txt")
    env = dict(os.environ, PAD_SETTINGS_IDLE_MS="2000")

    def start(name, extra_conf):
        conf = os.path.join(t, name + ".conf")
        with open(conf, "w") as f:
            f.write("image=p3|STERN STOCK|original Stern code||\n"
                    "image=testcard|TEST CARD|test pictures||\n"
                    "test_dir=%s\ntest_image=art0.png|Red square\ntimeout=2\n%s" % (tdir, extra_conf))
        sw = os.path.join(t, name + ".padsw")
        with open(sw, "wb") as f:
            f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
        out, last = os.path.join(t, name + ".choice"), os.path.join(t, name + ".last")
        if os.path.exists(out):
            os.unlink(out)
        return conf, sw, out, last

    def run(conf, sw, out, last, flag):
        return subprocess.Popen([qemu, "-L", root, binp, "--headless", os.path.join(t, "entry.ppm"),
                                 "--conf", conf, "--input", "padsw", "--padsw", sw, "--tables", no_list,
                                 "--timeout", "2", "--out", out, "--last", last,
                                 "--font", font, "--no-invert", "--media", media, "--audio", "none",
                                 "--color-file", os.path.join(t, "entry.color")],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=dict(env, CODESELECT_MENU_FLAG=flag))

    def finish(p, name):
        try:
            return p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            o, e = p.communicate()
            fail("(%s) codeselect did not exit" % name, o, e)

    flag = os.path.join(t, "no_menu_flag")
    # 1-3: the menu, default= the entry
    conf, sw, out, last = start("menu", "default=1\n")
    if os.path.exists(last):
        os.unlink(last)
    p = run(conf, sw, out, last, flag)
    time.sleep(4.5)                                   # the countdown runs out on the entry
    last_mid = open(last).read().strip() if os.path.exists(last) else None
    press(sw, "right")                                # a row of the test card menu
    press(sw, "action", after=1.6)                    # back to the games
    # RIGHT wraps to STERN STOCK: two cards, no SETTINGS tile - the entry's own lists
    # (test_image=) are not the tile's, which would show the same screens twice
    press(sw, "right")
    press(sw, "start")
    o, e = finish(p, "menu")
    for want in ("highlight 1 (TEST CARD) from conf default",
                 "-> 0 (STERN STOCK), card 1/2 - wrap",
                 "[select] testcard entry: card 2 (TEST CARD): the test card screens",
                 "[select] settings: the test card menu",
                 "[select] test card: back to the games",
                 "[select] testcard entry: back to the menu",
                 "[select] chose 0 STERN STOCK"):
        if want not in o + e:                         # the highlight moves are the log's (stderr)
            fail("(menu) no %r" % want, o, e)
    if last_mid != "1":
        fail("(menu) the last-choice file held %r inside the test card, expected 1" % last_mid, o, e)
    if (open(out).read().strip() if os.path.exists(out) else None) != "0":
        fail("(menu) the choice file does not hold 0", o, e)
    if open(last).read().strip() != "0":
        fail("(menu) the last-choice file is not 0 after the game was chosen", o, e)
    print("testcard_entry_test: menu OK")

    # 4: boot_menu=hidden and the entry remembered: the start-up screen, then the test card
    conf, sw, out, last = start("hidden", "default=0\nboot_menu=hidden\n")
    with open(last, "w") as f:
        f.write("1\n")
    p = run(conf, sw, out, last, flag)
    time.sleep(6)
    press(sw, "action", after=1.6)                    # back to the games: the menu
    press(sw, "left")
    press(sw, "start")
    o, e = finish(p, "hidden")
    for want in ("[select] boot menu hidden: 2500 ms to hold the right flipper, else card 2 (TEST CARD)",
                 "[select] boot menu hidden: no right flipper - booting card 2",
                 "[select] testcard entry: card 2 (TEST CARD): the test card screens",
                 "[select] testcard entry: back to the menu",
                 "[select] chose 0 STERN STOCK"):
        if want not in o:
            fail("(hidden) no %r" % want, o, e)
    print("testcard_entry_test: hidden OK")
    print("testcard_entry_test: OK")


if __name__ == "__main__":
    main()
