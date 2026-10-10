"""The virtual playfield with NO emulator: a demo title, a live fake LED show.

    python scripts/playfield_demo.py [field|schematic|waiting] [--lcd]
        [--cabinet] [--art PNG] [--window webview|gtk|app|browser|none]
        [--seconds N]

It builds a title "demo_pf" in a temp dir - device table, switch list, key
binds, a ball-feeder status - and animates dump/padled (an attract-style show,
a2 pulses, coil fires), dump/padsw (five balls home, the coin door closed) and,
with --lcd, a villain-vision block with three synthetic clips. --cabinet adds
the cabinet's own lighting (PAD-500) the way the real tables carry it: blades
on the playfield picture's edges, speakers on no picture, a topper on one of
its own, the strip boards in a node directory, and a show on them that runs
past each board's first 96 channels. Every WSL helper
is stubbed: a click writes the fake switch block, so the page shows the switch
made, and nothing reaches wsl.exe, a rig, or the user's real state file.

The artwork is --art when given (any title's *_playfield.png), else a drawing
made here, so the demo runs on a CI runner with no card on it.

--window none serves the page only and prints its two URLs (URL, LCDURL) for a
browser or a capture script to open; the other values pick pfweb's window.
"""
import argparse
import math
import os
import random
import shutil
import struct
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="field",
                    choices=("field", "schematic", "waiting"))
    ap.add_argument("--lcd", action="store_true")
    ap.add_argument("--cabinet", action="store_true")
    ap.add_argument("--art")
    ap.add_argument("--window", default="webview")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="leave after this long (0 = until the window closes)")
    a = ap.parse_args(argv)

    root = tempfile.mkdtemp(prefix="pfdemo-")
    dump = os.path.join(root, "root", "dump")
    tables = os.path.join(root, "tables")
    game = "demo_pf"
    tdir = os.path.join(tables, game)
    os.makedirs(dump)
    os.makedirs(tdir)
    sys.path.insert(0, RIG)
    rnd = random.Random(7)

    # ---- the artwork -------------------------------------------------------
    art = os.path.join(tdir, "playfield.png")
    if a.art and os.path.isfile(a.art):
        shutil.copyfile(a.art, art)
    else:
        from PIL import Image, ImageDraw
        W, H = 313, 710
        im = Image.new("RGB", (W, H), (245, 245, 240))
        d = ImageDraw.Draw(im)
        d.rectangle((6, 6, W - 7, H - 7), outline=(40, 40, 40), width=3)
        for k in range(9):
            y = 80 + k * 60
            d.arc((30 + k * 4, y, W - 30 - k * 4, y + 140), 200, 340,
                  fill=(60, 60, 60), width=2)
        d.polygon(((70, 560), (120, 640), (70, 640)), outline=(40, 40, 40))
        d.polygon(((W - 70, 560), (W - 120, 640), (W - 70, 640)),
                  outline=(40, 40, 40))
        d.line((110, 660, 150, 690), fill=(30, 30, 30), width=6)
        d.line((W - 110, 660, W - 150, 690), fill=(30, 30, 30), width=6)
        for cx, cy in ((110, 220), (190, 200), (150, 280)):
            d.ellipse((cx - 22, cy - 22, cx + 22, cy + 22),
                      outline=(40, 40, 40), width=3)
        im.save(art)
    import gameinfo
    W, H = gameinfo.png_size(art)

    # ---- the tables --------------------------------------------------------
    names = ["TROUGH %d" % i for i in range(1, 7)] + [
        "SHOOTER LANE", "LEFT SLING", "RIGHT SLING", "LEFT INLANE",
        "RIGHT INLANE", "LEFT OUTLANE", "RIGHT OUTLANE", "POP BUMPER 1",
        "POP BUMPER 2", "LEFT RAMP ENTER", "RIGHT RAMP ENTER", "RIGHT SCOOP",
        "SPINNER", "TARGET 1", "TARGET 2", "TARGET 3", "TARGET 4",
        "CENTER LOOP", "START BUTTON", "ACTION BUTTON", "COIN DOOR CLOSED",
        "ANGLE SENSOR THRESHOLD"]   # PAD-259: a spinning disc, no position
    rows, nid = [], 40
    for i, name in enumerate(names):
        if name.startswith("TROUGH"):
            sid = 76 - int(name.split()[1])            # 75..70, like godzilla
        elif name == "COIN DOOR CLOSED":
            sid = 33
        else:
            sid, nid = nid, nid + 1
        node, bit = (0, 23) if sid == 33 else (8, 32 + i)
        rows.append((sid, i + 1, node, bit, name))
    start_id = [r[0] for r in rows if r[4] == "START BUTTON"][0]
    if a.mode != "waiting":
        with open(os.path.join(tdir, "switch_list.txt"), "w") as f:
            for r in rows:
                f.write("%d %d %d %d %s\n" % r)
    dev, img = [], "Test/scaled_playfield"
    # --cabinet lays the title out the way Rush is: group 6 is its speaker
    # lights, so the playfield's two boards are groups 7 and 8 (PAD-500)
    pg = 1 if a.cabinet else 0
    for k, (sid, num, node, bit, name) in enumerate(rows):
        if name in ("START BUTTON", "ACTION BUTTON", "COIN DOOR CLOSED",
                    "ANGLE SENSOR THRESHOLD"):
            continue
        if name.startswith("TROUGH"):
            x, y = 190 + int(name.split()[1]) * 12, H - 40
        else:
            x, y = rnd.randint(30, W - 30), rnd.randint(60, H - 110)
        dev.append("switch %s %d %d 10 10 %d %d - %s"
                   % (name, x, y, 6 + pg, k, img))
    for k in range(56):
        x, y = rnd.randint(25, W - 25), rnd.randint(40, H - 110)
        if k % 7 == 0:
            for c, idx in zip("RGB", (k, k + 60, k + 120)):
                dev.append("led SHIELD %d-%s %d %d 8 8 %d %d - %s"
                           % (k, c, x + rnd.randint(-2, 2), y, 6 + pg,
                              idx % 96, img))
        else:
            dev.append("led INSERT %d %d %d 8 8 %d %d - %s"
                       % (k, x, y, (7 if k % 2 else 6) + pg, k, img))
    for k, name in enumerate(("LEFT SLINGSHOT", "RIGHT SLINGSHOT",
                              "POP BUMPER 1", "POP BUMPER 2", "TROUGH",
                              "AUTO PLUNGER", "RIGHT SCOOP", "LEFT FLIPPER",
                              "RIGHT FLIPPER")):
        x, y = rnd.randint(40, W - 40), rnd.randint(120, H - 130)
        # with a node directory (--cabinet) the coil groups are what map the
        # playfield groups onto its boards, so both have to carry one
        grp = (7 if a.cabinet and k % 2 else 6) + pg
        dev.append("coil %s %d %d 10 10 %d %d - %s" % (name, x, y, grp, k, img))
    # the cabinet's shaker, off the artwork, where the real tables put it
    dev.append("coil SHAKER MOTOR 0 0 0 0 5 0 - -")
    if a.cabinet:
        # PAD-500: the blades on the playfield picture's edges (John Wick, King
        # Kong and Metallica draw them there), the speakers on no picture
        # (Rush, Venom), a topper on a picture of its own (Bond) - one RGB pixel
        # a name, its channels in the strips' G, R, B wire order. The blades
        # are 48 pixels a side, 1-48 up the left and 49-96 up the right, the
        # way King Kong's picture places them; the right side and the topper's
        # 40 pixels run past index 95, into the board's next banks.
        for side, x, first in (("L", 9, 0), ("R", W - 9, 48)):
            for n in range(48):
                y = (H - 170) - n * (H - 262) / 47.0
                for c, o in (("G", 0), ("R", 1), ("B", 2)):
                    dev.append("led EXPRESSIVE LIGHTING %s %d-%s %d %d 4 4 1 %d - %s"
                               % (side, first + n + 1, c, x, y,
                                  (first + n) * 3 + o, img))
        for n in range(23):
            for c, o in (("G", 0), ("R", 1), ("B", 2)):
                dev.append("led SPEAKER %d-%s 0 0 0 0 6 %d - -"
                           % (n + 1, c, n * 3 + o))
        for n in range(40):
            row, k = divmod(n, 20)
            x = 20 + k * 14
            y = 30 + row * 26 + int(10 * math.sin(k / 19.0 * math.pi))
            for c, o in (("G", 0), ("R", 1), ("B", 2)):
                dev.append("led TOPPER %d-%s %d %d 4 4 9 %d - Test/scaled_topper"
                           % (n + 1, c, x, y, n * 3 + o))
        # the node directory in the order a real title's runs, each board
        # with its place (= its device-table group) and its own name
        with open(os.path.join(tdir, "node_ident.txt"), "w") as f:
            f.write("# nbdir v2 elf=game nodes=8 src=demo\n")
            for nid, typ, grp, name in (
                    (2, "ws2812node", 1, "Cabinet Lights"),
                    (4, "node4", 2, "QR Scanner"),
                    (14, "ws2812node", 3, "Topper Lights"),
                    (1, "pinnode", 5, "Cabinet"),
                    (7, "ws2812node", 6, "Backbox Speaker Lights"),
                    (8, "pinnode", 7, "Lower Playfield"),
                    (9, "pinnode", 8, "Upper Playfield"),
                    (12, "ws2812node", 9, "Topper")):
                f.write("node=%d type=%s group=%d name=%s\n"
                        % (nid, typ, grp, name))
    with open(os.path.join(tdir, "device_xy.txt"), "w") as f:
        f.write("# demo\n" + ("\n".join(dev) + "\n"
                              if a.mode == "field" else ""))
    if a.mode != "field":
        os.remove(art)
    with open(os.path.join(dump, "padbinds"), "w") as f:
        f.write("\n".join([
            "# key\tflags\tids\tlabel",
            "Enter\tc\t25\tService Select", "=\tc\t26\tService Plus",
            "-\tc\t27\tService Minus", "Bksp\tc\t28\tService Back",
            "1\tc\t%d\tStart Button" % start_id, "5\tc\t39\tLeft Coin",
            "C\tct\t33\tCoin Door Closed", "Left\t-\t30\tLeft Flipper",
            "Right\t-\t31\tRight Flipper", "Space\t-\t32\tAction Button",
            "Q\t-\t34\tTilt", "B\tt\t70,71,72,73,74,75\t6 balls in trough",
        ]) + "\n")
    with open(os.path.join(dump, "padball"), "w") as f:
        f.write("fed 2\nfeeder: trough full, waiting for a game\n")
    os.environ.update(PAD_ROOT=os.path.join(root, "root"), PAD_TABLES=tables,
                      PAD_GAME=game)
    if a.window != "none":
        os.environ["PAD_PF_WINDOW"] = a.window

    # ---- the fake switch block ---------------------------------------------
    import padsw
    sw_path = os.path.join(dump, "padsw")
    sw_lock = threading.Lock()
    held = bytearray(padsw.MAX_ID)
    for sid in (70, 71, 72, 73, 74, 33):     # five balls home, door closed
        held[sid] = 1

    def write_sw():
        with sw_lock:
            b = bytearray(padsw.SIZE)
            struct.pack_into("<I", b, 0, padsw.MAGIC)
            struct.pack_into("<I", b, padsw.OFF_MRG_GEN, 1)
            b[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID] = held
            tmp = sw_path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(b)
            os.replace(tmp, sw_path)
    write_sw()

    # ---- the fake LED block ------------------------------------------------
    import coilmap
    led = os.path.join(dump, "padled")
    fade_head = coilmap.GEN_OFF + 8
    fade_ent = fade_head + 4
    seen = fade_ent + 96 * 12
    size = 8192                     # padled version 5: the drive table too
    version = 5
    # version 6 (PAD-500): a strip board's channels past its first 96
    hi_off = getattr(coilmap, "HI_OFF", coilmap.DRIVE_READ)
    hi_idx = getattr(coilmap, "HI_IDX", 384)
    if a.cabinet:
        size, version = 16384, 6
    stop = threading.Event()
    #: the shaker's commands over a 7 s cycle: (at s, ms, power) - a long soft
    #: shake, then the jackpot-sized hard ones (PAD-424)
    shakes = ((0.4, 1500, 31), (2.6, 500, 51), (3.5, 200, 51), (4.3, 334, 36))
    shaker = 1 * 16 + 0             # node 1 coil 0

    def led_loop():
        t0, fires, head, dec = time.time(), [0] * 256, 0, 0
        cmd, cyc = None, -1
        while not stop.is_set():
            t = time.time() - t0
            b = bytearray(size)
            struct.pack_into("<I", b, 0, coilmap.PADLED_MAGIC)
            struct.pack_into("<I", b, 4, version)
            c, ph = int(t // 7), t % 7
            for k, (at, ms, pwr) in enumerate(shakes):
                if ph >= at and (c, k) > (cyc, cmd if cmd is not None else -1):
                    cyc, cmd = c, k
                    until = int(t * 1000) + ms
                    drive = (until, ms // 10, pwr)
                    fires[shaker] = (fires[shaker] + 1) & 0xFF
            if cmd is not None:
                until, ticks, pwr = drive
                struct.pack_into("<I", b, coilmap.DRIVE_TPS_OFF, 100)
                struct.pack_into("<I", b, coilmap.DRIVE_UNTIL_OFF + 4 * shaker, until)
                struct.pack_into("<H", b, coilmap.DRIVE_PULSE_T_OFF + 2 * shaker, ticks)
                b[coilmap.DRIVE_PULSE_PWR_OFF + shaker] = pwr
            for node in (8, 9):
                for idx in range(96):
                    ph = (idx * 0.37 + t * (1.7 if node == 8 else 1.1)) % (2 * math.pi)
                    v = int(max(0.0, math.sin(ph)) ** 2 * 255)
                    if idx % 5 == 0:
                        v = 255 if int(t * 2 + idx) % 3 == 0 else 0
                    b[20 + node * 96 + idx] = v
                    b[seen + node * 96 + idx] = 1
            if a.cabinet:
                def strip(node, idx, rgb):
                    # G, R, B on the wire, like the real strips
                    for o, v in enumerate((rgb[1], rgb[0], rgb[2])):
                        i = idx + o
                        if i < 96:
                            b[20 + node * 96 + i] = v
                            b[seen + node * 96 + i] = 1
                        else:
                            b[hi_off + node * hi_idx + i - 96] = v

                def hue(h, k=1.0):
                    h = (h % 1.0) * 6
                    i, f = int(h), h - int(h)
                    q = [(1, f, 0), (1 - f, 1, 0), (0, 1, f), (0, 1 - f, 1),
                         (f, 0, 1), (1, 0, 1 - f)][i % 6]
                    return [int(c * 255 * k) for c in q]
                # the blades: a rainbow running up both sides
                for side in (0, 1):
                    for n in range(48):
                        strip(2, (side * 48 + n) * 3, hue(n / 24.0 - t * 0.4))
                # the speakers: a soft amber breath
                k = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(t * 2.4))
                for n in range(23):
                    strip(7, n * 3, [int(255 * k), int(120 * k), 0])
                # the topper: a white sweep over blue
                for n in range(40):
                    lit = abs((n % 20) - (t * 8) % 20) < 2
                    strip(12, n * 3, [255, 255, 255] if lit else [0, 40, 200])
            dec += 7
            struct.pack_into("<I", b, 12, dec)
            if int(t * 3) % 4 == 0:
                n = rnd.randrange(9)
                fires[8 * 16 + n] = (fires[8 * 16 + n] + 1) & 0xFF
            for i in range(256):
                b[coilmap.COIL_OFF + i] = fires[i]
            struct.pack_into("<I", b, coilmap.GEN_OFF + 4, 9)
            if rnd.random() < 0.05:
                e = fade_ent + (head % 96) * 12
                struct.pack_into("<I8B", b, e, int(t * 1000), 9, 0, 20, 0,
                                 255, 10, 30, 0)
                head += 1
            struct.pack_into("<I", b, fade_head, head)
            tmp = led + ".tmp"
            try:
                with open(tmp, "wb") as f:
                    f.write(b)
                os.replace(tmp, led)
            except OSError:
                pass
            time.sleep(1 / 30.0)
    threading.Thread(target=led_loop, daemon=True).start()

    # ---- the villain vision block (--lcd) ----------------------------------
    if a.lcd:
        from PIL import Image, ImageDraw
        lcd_art = os.path.join(tables, game, "lcd")
        os.makedirs(lcd_art)
        for i in (54, 55, 56):
            base = Image.new("RGB", (240, 180), (40 * (i - 50), 60, 120))
            ImageDraw.Draw(base).text((90, 80), "asset %d" % i,
                                      fill=(255, 255, 255))
            base.save(os.path.join(lcd_art, "%d.png" % i))
            frames = []
            for k in range(10):
                fr = base.copy()
                ImageDraw.Draw(fr).rectangle((k * 20, 150, k * 20 + 18, 170),
                                             fill=(255, 200, 0))
                frames.append(fr)
            frames[0].save(os.path.join(lcd_art, "%d.webp" % i),
                           save_all=True, append_images=frames[1:],
                           duration=100, loop=0, lossless=True)

        def lcd_loop():
            n = 0
            while not stop.is_set():
                asset = (54, 55, 56)[(n // 30) % 3]
                br = 0 if n % 30 == 28 else 255
                with open(os.path.join(dump, "padlcd"), "wb") as f:
                    f.write(struct.pack("<14I", 0x44434c50, 4, n, n, asset, 0,
                                        10, 1, 0, 0, 0, br, 15, n * 100))
                n += 1
                time.sleep(0.1)
        threading.Thread(target=lcd_loop, daemon=True).start()

    # ---- the playfield, with WSL stubbed -----------------------------------
    sys.argv = ["playfield.py", game, "--savestates"]
    import playfield
    playfield.STATE = os.path.join(root, "pad_playfield.json")

    class R:
        def __init__(self, out):
            self.stdout, self.stderr, self.returncode = out.encode(), b"", 0

    def fake_wsl_run(script, *args):
        if script == "swhold.py":
            sid, val = int(args[0]), int(args[1])
            with sw_lock:
                held[sid] = val
            write_sw()
            return R("id=%d was %d -> %d" % (sid, 1 - val, val))
        if script == "plunge.py":
            return R("%s pressed (demo)" % args[0])
        return R("%s ran (demo)" % script)

    class FakePipe(playfield.SwitchPipe):
        def _ensure(self):
            return True

        def _send(self, line):
            p = line.decode().split()
            if p[0] != "cab":
                with sw_lock:
                    held[int(p[0])] = int(p[1])
                write_sw()
            return True

    playfield.wsl_run = fake_wsl_run
    playfield.state_run = lambda s, slot, label=None: R(
        "[savegame] saved to %s (demo)" % slot)
    playfield.state_slots = lambda: {"slot1": "before the boss", "slot3": ""}
    playfield.SwitchPipe = FakePipe
    playfield.raise_existing = lambda: False
    print("demo root:", root, flush=True)
    if a.seconds:
        threading.Timer(a.seconds, lambda: os._exit(0)).start()
    if a.window == "none":
        playfield.fine_timers()         # what main() asks for around a session
        ctl = playfield.Playfield()
        host = playfield.pfweb.WebHost(os.path.join(playfield.HERE, "pfpage"),
                                       ctl, title=playfield.WINDOW_TITLE)
        ctl.host = host
        host.start()
        ctl.start()
        host._ready = True              # no window system: open nothing
        host.backend = playfield.pfweb.BrowserBackend(host)
        host.backend.open = lambda *a_, **k_: None
        print("URL", host.url(), flush=True)
        print("LCDURL", host.url("lcd"), flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        playfield.main()
    stop.set()
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
