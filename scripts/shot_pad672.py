"""PAD-672 capture: the virtual playfield window's side panel, as first opened.

    python scripts/shot_pad672.py --tables <dir holding godzilla_le/> --out <dir>
        [--prefix after_] [--repo <checkout>] [--no-padball]

Serves Godzilla LE's playfield page over a FAKE dump (scripts/shot_pad450.py's
rig: nothing reaches wsl.exe or a rig) in a 1100x900 window and shoots it
unscrolled, with the key panel built from the rig's padbinds and padball
(they sit beside --tables): <prefix>emulator_panel.png. --repo picks the checkout served, so a
`git archive` of main gives the before shot.
"""
import argparse
import os
import shutil
import struct
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = "godzilla_le"
TROUGH_HOME = (75, 74, 73, 72, 71)  # TROUGH 1..5 made: five balls home
DOOR = 33                           # Coin Door Power Interlock


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--repo", default=os.path.dirname(HERE))
    ap.add_argument("--no-padball", action="store_true",
                    help="no feeder status: the BALLS note is empty")
    a = ap.parse_args(argv)
    rig = os.path.join(a.repo, "tools", "spike2_emu")
    os.makedirs(a.out, exist_ok=True)

    root = tempfile.mkdtemp(prefix="pad672-")
    dump = os.path.join(root, "root", "dump")
    tables = os.path.join(root, "tables")
    os.makedirs(dump)
    shutil.copytree(os.path.join(a.tables, GAME), os.path.join(tables, GAME))
    # the key panel arrives with padbinds (playfield.attach_key_panel): the
    # rig's own, written by padglhost for this title, beside --tables
    # and the ball feeder's status lines (padball), so the BALLS note is real
    for name in ("padbinds",) + (() if a.no_padball else ("padball",)):
        shutil.copy(os.path.join(os.path.dirname(os.path.normpath(a.tables)),
                                 name), os.path.join(dump, name))
    os.environ.update(PAD_ROOT=os.path.join(root, "root"), PAD_TABLES=tables,
                      PAD_GAME=GAME)
    sys.path.insert(0, rig)

    import padsw
    sw_path = os.path.join(dump, "padsw")
    sw_lock = threading.Lock()
    held = bytearray(padsw.MAX_ID)
    for sid in TROUGH_HOME + (DOOR,):
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

    import coilmap
    led = os.path.join(dump, "padled")
    fires = bytearray(256)
    stop = threading.Event()

    def led_loop():
        dec = 0
        while not stop.is_set():
            b = bytearray(8192)
            struct.pack_into("<I", b, 0, coilmap.PADLED_MAGIC)
            struct.pack_into("<I", b, 4, 5)
            dec += 7
            struct.pack_into("<I", b, 12, dec)
            b[coilmap.COIL_OFF:coilmap.COIL_OFF + 256] = fires
            struct.pack_into("<I", b, coilmap.GEN_OFF + 4, 9)
            tmp = led + ".tmp"
            try:
                with open(tmp, "wb") as f:
                    f.write(b)
                os.replace(tmp, led)
            except OSError:
                pass
            time.sleep(1 / 30.0)
    threading.Thread(target=led_loop, daemon=True).start()

    sys.argv = ["playfield.py", GAME]
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
            return R("id=%d -> %d" % (sid, val))
        return R("%s ran (capture)" % script)

    playfield.wsl_run = fake_wsl_run
    playfield.raise_existing = lambda: False
    playfield.fine_timers()
    ctl = playfield.Playfield()
    host = playfield.pfweb.WebHost(os.path.join(playfield.HERE, "pfpage"), ctl,
                                   title=playfield.WINDOW_TITLE)
    ctl.host = host
    host.start()
    ctl.start()
    host._ready = True
    host.backend = playfield.pfweb.BrowserBackend(host)
    host.backend.open = lambda *a_, **k_: None
    url = host.url()

    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:                       # noqa: BLE001 - no bundled browser
            b = p.chromium.launch(channel="msedge")
        pg = b.new_page(viewport={"width": 1100, "height": 900},
                        device_scale_factor=1.25)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(url)
        pg.wait_for_selector(".pf-panel", timeout=20000)
        pg.wait_for_timeout(2500)
        order = pg.evaluate("""() => [...document.querySelectorAll('.pf-panel > *')]
            .map(e => (e.querySelector('.kp-group, .h, .t') || e).textContent.trim().split(" ")[0])""")
        print("panel order:", order)
        pg.screenshot(path=os.path.join(a.out, a.prefix + "emulator_panel.png"))
        b.close()
    stop.set()
    print("page errors:", errors)
    os._exit(1 if errors else 0)


if __name__ == "__main__":
    main()
