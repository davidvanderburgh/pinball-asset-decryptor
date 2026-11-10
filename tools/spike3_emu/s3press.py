#!/usr/bin/env python3
"""s3press.py - press the Spike 3 game's cabinet buttons (PAD-1090).

The CPU board's SPI chain (s3spid, /dev/spidev4.0) carries the cabinet
inputs: 8 bytes, every bit ACTIVE LOW (0xff = all released; at 0x00 every
button reads held and the game boots into its service path). s3spid answers
each transfer from the slot's spi.in, so writing that file presses a button.

    s3press.py press SLOT BIT [MS]     hold bit BIT (0..63) for MS (200) ms
    s3press.py hold SLOT BIT           hold it until `release`
    s3press.py release SLOT [BIT]      release one bit, or all
    s3press.py scan SLOT [FIRST LAST]  press each bit in turn and score how
                                       much the screen changed (needs frame
                                       dumps: PAD_GL_FRAME_EVERY small)
    s3press.py guided SLOT             walk a fresh machine's Guided Setup to
                                       Save & Exit (needs frame dumps)
    s3press.py node SLOT NODE BIT [MS] close a node board's switch input (its
                                       ff reply word; start/flippers are node 1)
    s3press.py set SLOT NODE BIT 0|1   leave a node switch closed (1) or open
    s3press.py drain SLOT              a ball in play drains to the trough
    s3press.py sw SLOT NAME [MS]       press a switch by the title's own name
                                       ("START BUTTON", "ACTION BUTTON",
                                       "LEFT FLIPPER BUTTON", "LEFT SLINGSHOT")
    s3press.py coin SLOT [N]           N coins, 3 s apart (closer ones are lost)

A GAME (pokemon_le, measured): `coin 4` -> CREDITS 1, `sw START BUTTON`
-> BALL 1 (s3balls answers the trough eject: the ball reaches the shooter
lane), `sw ACTION BUTTON` launches (the auto plunger fires), switches
score, `drain` ends the ball: bonus, then BALL 2.
    s3press.py autoguide SLOT [SECS]   walk it every time it comes up (s3run.sh
                                       --bus --bridge runs this)

The coin door: SPI bit 15 is COIN DOOR POWER INTERLOCK (device group 5
index 23; the service buttons are indices 8..11 = bits 0..3). At rest it
reads OPEN - service buttons live, 48 V off, no coil fires. `hold SLOT 15`
closes the door, and only then do coils fire (Spike 2 behaves the same).

Bit b is byte b // 8, mask 1 << (b % 8). Measured on pokemon_le 0.82.0 in
Guided Setup (scan): the coin-door service buttons are byte 0 -
    bit 0 SELECT   bit 1 NEXT (down)   bit 2 PREVIOUS (up)   bit 3 BACK
"""
SELECT, NEXT, PREV, BACK = 0, 1, 2, 3
import glob
import os
import sys
import time

BASE = "/var/tmp/pad-s3/slot%s"


def path(slot):
    return os.path.join(BASE % slot, "spi.in")


def setbit(slot, bit, down):
    p = path(slot)
    b = bytearray(open(p, "rb").read())
    if down:
        b[bit // 8] &= ~(1 << (bit % 8)) & 0xFF
    else:
        b[bit // 8] |= 1 << (bit % 8)
    with open(p, "r+b") as f:     # in place: s3spid maps this very file
        f.write(bytes(b))


def press(slot, bit, ms=200):
    setbit(slot, bit, True)
    time.sleep(ms / 1000.0)
    setbit(slot, bit, False)


def frames(slot):
    """The slot's frame dumps, OLDEST FIRST. The names are frame_<n>.png,
    not zero-padded, so a plain sort put frame_999 after frame_1000: past
    the thousandth frame "the newest" was a stale one, and autoguide read -
    and pressed BACK/SELECT on - a Guided Setup long gone, mid-game."""
    def num(f):
        try:
            return int(os.path.basename(f)[6:-4])
        except ValueError:
            return -1
    return sorted(glob.glob(os.path.join(BASE % slot, "frames", "frame_*.png")), key=num)


def newest_frame(slot):
    """The newest FINISHED frame: the newest file may still be being written."""
    fs = frames(slot)
    return fs[-2] if len(fs) > 1 else None


def _frame_no(f):
    try:
        return int(os.path.basename(f)[6:-4])
    except (TypeError, ValueError):
        return -1


def frame_after(slot, before, timeout=30.0, gap=2):
    """The newest finished frame at least GAP dumps past BEFORE (a path),
    waiting up to TIMEOUT s for the renderer to get there; the newest
    there is when it does not."""
    n0 = _frame_no(before)
    end = time.time() + timeout
    while True:
        f = newest_frame(slot)
        if f and _frame_no(f) >= n0 + gap:
            return f
        if time.time() >= end:
            return f
        time.sleep(0.5)


def thumb(f):
    from PIL import Image
    im = Image.open(f).convert("RGB")
    reg = os.environ.get("S3_SCAN_REGION")      # x0,y0,x1,y1: score only that
    if reg:
        box = tuple(int(v) for v in reg.split(","))
        r = im.crop(box)
        return r, r.resize((max(1, r.width // 8), max(1, r.height // 8)))
    # the Guided Setup rows below the animated first label, and every value
    return im.crop((0, 330, 1920, 980)).resize((240, 82)), im.crop((820, 240, 1920, 330)).resize((138, 12))


def diff(a, b):
    import numpy as np
    return float(np.abs(np.asarray(a, np.int16) - np.asarray(b, np.int16)).mean())


def scan(slot, first=0, last=63, hold_ms=250, settle=1.8):
    out = os.path.join(BASE % slot, "scan")
    os.makedirs(out, exist_ok=True)
    log = open(os.path.join(out, "scan.log"), "a", buffering=1)
    for bit in range(first, last + 1):
        f0 = newest_frame(slot)
        if not f0:
            print("no frames in", BASE % slot, "- run with PAD_GL_FRAME_EVERY small")
            return
        r0, v0 = thumb(f0)
        t = time.time()
        press(slot, bit, hold_ms)
        time.sleep(settle)
        f1 = newest_frame(slot)
        r1, v1 = thumb(f1)
        d = diff(r0, r1) + diff(v0, v1)
        r1.save(os.path.join(out, "bit%02d.png" % bit))
        line = "%.3f bit %2d (byte %d mask 0x%02x): screen change %.2f  %s -> %s" % (
            t, bit, bit // 8, 1 << (bit % 8), d, os.path.basename(f0), os.path.basename(f1))
        print(line, flush=True)
        log.write(line + "\n")
        # keep the disk: drop every frame but the newest two (newest_frame
        # reads the second newest - the newest may still be being written)
        for f in frames(slot)[:-2]:
            try:
                os.remove(f)
            except OSError:
                pass


def highlighted_row(f):
    """Which Guided Setup row (0 = the first) is drawn in the highlight
    colour, measured off the left column: cyan text, (~0, 220+, 220+)."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(f).convert("RGB")).astype(np.int16)
    col = a[240:960, 20:600]
    cyan = (col[:, :, 0] < 90) & (col[:, :, 1] > 170) & (col[:, :, 2] > 170)
    rows = cyan.sum(axis=1)
    if rows.max() < 20:
        return None
    y = int(np.argmax(rows)) + 240
    return (y - 240) // 85                 # rows are ~85 px apart from y=240


def guided(slot, max_steps=12):
    """Back to the top of Guided Setup, NEXT until Save & Exit (the last
    row) is highlighted, then SELECT."""
    press(slot, BACK)
    time.sleep(1.5)
    last = None
    for i in range(max_steps):
        f = newest_frame(slot)
        r = highlighted_row(f) if f else None
        print("guided: step %d highlighted row %s" % (i, r), flush=True)
        if r is not None and r >= 7:
            press(slot, SELECT)
            print("guided: SELECT on Save & Exit", flush=True)
            return True
        if r is not None and r == last and i > 2:
            pass
        last = r
        press(slot, NEXT)
        time.sleep(1.2)
    print("guided: never reached Save & Exit", flush=True)
    return False


def is_guided_setup(f):
    """Guided Setup, full screen: the white title across the top centre and a
    highlighted (cyan) row in the left column. Tech Alerts (an 800x480 panel
    at the top left) has its title elsewhere, attract has no cyan. The
    service menu's pages look the same - white title, cyan row - but their
    right column is a GREY description, where Guided Setup shows each row's
    value in WHITE (English, U.S.A., Yes): measured 0.06 of that area white
    on Guided Setup, 0.0 on the main menu and every Diagnostics page.
    Pressing BACK there threw an operator out of the menu."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(f).convert("RGB")).astype(np.int16)
    title = a[70:180, 680:1240]
    white = ((title[:, :, 0] > 220) & (title[:, :, 1] > 220) & (title[:, :, 2] > 220)).mean()
    if not (white > 0.08 and highlighted_row(f) is not None):
        return False
    vals = a[240:700, 800:1400]
    return ((vals[:, :, 0] > 220) & (vals[:, :, 1] > 220) & (vals[:, :, 2] > 220)).mean() > 0.02


def autoguide(slot, secs=0, keep=60):
    """Walk Guided Setup every time it comes up, for SECS (0 = for ever).
    The game shows it at every boot of a fresh rig slot (and again on later
    boots - this emulator's machine reports no valid identity), and it holds
    the machine there until an operator presses Save & Exit: BACK puts the
    highlight on Save & Exit, SELECT leaves. Old frame dumps are pruned to
    the newest KEEP, so dumping can run for the whole session."""
    t0 = time.time()
    walked = 0
    while not secs or time.time() - t0 < secs:
        time.sleep(2.0)
        fs = frames(slot)
        for f in fs[:-keep]:
            try:
                os.remove(f)
            except OSError:
                pass
        f = newest_frame(slot)
        try:
            if not f or not is_guided_setup(f):
                continue
        except (OSError, ValueError):
            continue
        press(slot, BACK)
        time.sleep(1.5)
        # a frame drawn AFTER the press: star_wars_2025_pro draws ~0.5 fps
        # under emulation, and the newest frame 1.5 s on still showed the
        # highlight on Language - autoguide pressed BACK for ever
        g = frame_after(slot, f)
        try:
            r = highlighted_row(g) if g else None
        except (OSError, ValueError):
            r = None
        if r is not None and r >= 7:
            press(slot, SELECT)
            walked += 1
            print("[autoguide] Guided Setup: Save & Exit (%d)" % walked, flush=True)
            time.sleep(6.0)
            frame_after(slot, g, gap=3)     # past the screen it just left


def main_node_press(slot, node, bit, ms):
    """Close a node switch for MS ms (nodesw is logical: 1 = closed)."""
    p = os.path.join(BASE % slot, "nodesw")
    off = 8 * node + bit // 8
    with open(p, "r+b") as f:
        f.seek(off); v = f.read(1)[0]
        f.seek(off); f.write(bytes([v | (1 << (bit % 8))])); f.flush()
        time.sleep(ms / 1000.0)
        f.seek(off); f.write(bytes([v & ~(1 << (bit % 8)) & 0xFF])); f.flush()


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 2
    cmd, slot = a[0], a[1]
    if cmd == "press":
        press(slot, int(a[2]), int(a[3]) if len(a) > 3 else 200)
    elif cmd == "hold":
        setbit(slot, int(a[2]), True)
    elif cmd == "release":
        if len(a) > 2:
            setbit(slot, int(a[2]), False)
        else:
            p = path(slot)
            n = len(open(p, "rb").read())
            with open(p, "r+b") as f:
                f.write(b"\xff" * n)
    elif cmd == "node":
        # a node board's switch input (s3bridge.py's nodesw: 8 bytes a node,
        # 1 = closed): node NODE bit BIT (0..63) held for MS ms
        node, bit = int(a[2]), int(a[3])
        ms = int(a[4]) if len(a) > 4 else 200
        p = os.path.join(BASE % slot, "nodesw")
        off = 8 * node + bit // 8
        with open(p, "r+b") as f:
            f.seek(off); v = f.read(1)[0]
            f.seek(off); f.write(bytes([v | (1 << (bit % 8))])); f.flush()
            time.sleep(ms / 1000.0)
            f.seek(off); f.write(bytes([v & ~(1 << (bit % 8)) & 0xFF])); f.flush()
    elif cmd == "set":
        # a node board switch left closed (1) or open (0): balls resting in
        # the trough, say. set SLOT NODE BIT 0|1
        node, bit, v = int(a[2]), int(a[3]), int(a[4])
        p = os.path.join(BASE % slot, "nodesw")
        off = 8 * node + bit // 8
        with open(p, "r+b") as f:
            f.seek(off); b = f.read(1)[0]
            b = (b | (1 << (bit % 8))) if v else (b & ~(1 << (bit % 8)) & 0xFF)
            f.seek(off); f.write(bytes([b])); f.flush()
    elif cmd in ("sw", "coin"):
        # by NAME from the title's own device tables (s3bridge writes
        # DIR/switches.json): `sw SLOT "START BUTTON" [MS]`, `coin SLOT [N]`
        import json
        table = json.load(open(os.path.join(BASE % slot, "switches.json")))
        if cmd == "coin":
            name, count, ms = "LEFT COIN", int(a[2]) if len(a) > 2 else 1, 150
        else:
            name, count, ms = a[2].strip().upper(), 1, int(a[3]) if len(a) > 3 else 300
        if name not in table:
            print("no switch named %r (%d known)" % (name, len(table)))
            return 1
        node, idx = table[name]
        for k in range(count):
            if k:
                # coins closer than ~3 s apart are not all counted (pokemon_le:
                # 4 coins 2 s apart made 1/4 credit, 3 s apart a whole one)
                time.sleep(3.0)
            if node == 0:
                press(slot, idx - 8, ms)          # CPU board: the SPI chain
            else:
                main_node_press(slot, node, idx, ms)
        return 0
    elif cmd == "drain":
        # a ball in play drains: the lowest-numbered OPEN trough position
        # closes (s3balls.py's stack; balls.json says which switches)
        import json
        w = json.load(open(os.path.join(BASE % slot, "balls.json")))
        p = os.path.join(BASE % slot, "nodesw")
        with open(p, "r+b") as f:
            for node, bit in w["trough"]:
                off = 8 * node + bit // 8
                f.seek(off); b = f.read(1)[0]
                if not b & (1 << (bit % 8)):
                    f.seek(off); f.write(bytes([b | (1 << (bit % 8))])); f.flush()
                    print("drain: node %d bit %d closes" % (node, bit))
                    break
            else:
                print("drain: the trough is full")
                return 1
    elif cmd == "guided":
        return 0 if guided(slot) else 1
    elif cmd == "autoguide":
        autoguide(slot, int(a[2]) if len(a) > 2 else 0)
    elif cmd == "scan":
        scan(slot, int(a[2]) if len(a) > 2 else 0, int(a[3]) if len(a) > 3 else 63)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
