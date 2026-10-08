"""PAD-450 capture: James Bond LE's RIGHT VUK on the virtual playfield.

    python scripts/shot_pad450.py --tables <dir holding james_bond_le/> --out <dir>
        [--prefix after_] [--repo <checkout>]

Serves the playfield page for james_bond_le from that title's own tables (the
device table, switch lists and artwork mktables wrote on this machine - read in
place, never shipped) over a FAKE dump, the way scripts/playfield_demo.py does:
a click writes the fake switch block and the coil counters are this script's to
bump, so nothing reaches wsl.exe or a rig. Three shots:

  <prefix>vuk_tip.png    the RIGHT VUK coil marker hovered: what its tooltip says
  <prefix>vuk_click.png  a 170 ms click on RIGHT VUK OPTO (the click in the
                         user's log), 1.5 s after the mouse let go
  <prefix>vuk_kick.png   the game fires RIGHT VUK (its counter bumped), 1 s later

--repo picks the checkout whose playfield is served, so a `git archive` of main
gives the before shots.
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
GAME = "james_bond_le"
VUK_SWITCH = 101                    # RIGHT VUK OPTO
VUK_COIL = (9, 1)                   # RIGHT VUK: device group 8 index 1 -> node 9
TROUGH_HOME = (75, 74, 73, 72, 71)  # TROUGH 1..5 made: five balls home
DOOR = 33                           # Coin Door Power Interlock


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--repo", default=os.path.dirname(HERE))
    a = ap.parse_args(argv)
    rig = os.path.join(a.repo, "tools", "spike2_emu")
    os.makedirs(a.out, exist_ok=True)

    root = tempfile.mkdtemp(prefix="pad450-")
    dump = os.path.join(root, "root", "dump")
    tables = os.path.join(root, "tables")
    os.makedirs(dump)
    shutil.copytree(os.path.join(a.tables, GAME), os.path.join(tables, GAME))
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

    # where on the canvas the page's own hit test (pfHit) lands on a marker
    find = """([kind, want]) => {
        const cv = document.querySelector('.pf-stage canvas');
        const r = cv.getBoundingClientRect();
        return fetch('/state?t=' + new URLSearchParams(location.search).get('t'))
          .then(x => x.json()).then(st => {
            const V = st.view, sc = r.width / V.base[0];
            const list = kind === 'coil' ? V.coils : V.switches;
            const m = list.find(e => String(e[3]) === String(want));
            if (!m) return null;
            const [k, x, y] = m;
            for (let d = 0; d < 16; d += 0.5)
              for (const [dx, dy] of [[d, 0], [0, d], [-d, 0], [0, -d], [d, d], [-d, -d]]) {
                const px = x * sc + dx, py = y * sc + dy;
                const h = pfHit(V, {}, sc, px, py);
                if (h && h[0] === kind && h[1] === k) return [r.left + px, r.top + py];
              }
            return null;
          });
    }"""
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:                       # noqa: BLE001 - no bundled browser
            b = p.chromium.launch(channel="msedge")
        pg = b.new_page(viewport={"width": 760, "height": 980},
                        device_scale_factor=1.5)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(url)
        pg.wait_for_selector(".pf-stage canvas", timeout=20000)
        pg.wait_for_timeout(2500)
        coil_at = pg.evaluate(find, ["coil", "%d:%d" % VUK_COIL])
        sw_at = pg.evaluate(find, ["switch", VUK_SWITCH])
        print("coil marker at", coil_at, "switch marker at", sw_at)
        if not coil_at or not sw_at:
            sys.exit("the RIGHT VUK markers are not on the page")
        pg.mouse.move(*coil_at)
        pg.wait_for_timeout(1200)
        pg.screenshot(path=os.path.join(a.out, a.prefix + "vuk_tip.png"))
        pg.mouse.move(*sw_at)
        pg.wait_for_timeout(400)
        pg.mouse.down()
        pg.wait_for_timeout(170)
        pg.mouse.up()
        pg.mouse.move(20, 970)
        pg.wait_for_timeout(1500)
        print("after the click: switch %d %s" % (
            VUK_SWITCH, "MADE" if held[VUK_SWITCH] else "open"))
        pg.screenshot(path=os.path.join(a.out, a.prefix + "vuk_click.png"))
        n = VUK_COIL[0] * 16 + VUK_COIL[1]
        fires[n] = (fires[n] + 1) & 0xFF
        pg.wait_for_timeout(1000)
        print("after the coil fired: switch %d %s" % (
            VUK_SWITCH, "MADE" if held[VUK_SWITCH] else "open"))
        pg.screenshot(path=os.path.join(a.out, a.prefix + "vuk_kick.png"))
        b.close()
    stop.set()
    print("page errors:", errors)
    os._exit(1 if errors else 0)


if __name__ == "__main__":
    main()
