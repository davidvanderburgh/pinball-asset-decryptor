"""PAD-1468 capture: Ultraman's (or Halloween's) virtual playfield window
(tools/spooky_emu/spkpf.py -> tools/ap_emu/appf.py), served as the window
serves it but against a stand-in rig (the game "up", the given switches
made), and shown to a headless Edge instead of on the desktop.

    python scripts/shot_pad1468_um_switches.py --out <png> [--title um] [--made 66,41]
"""
import argparse
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "spooky_emu"))
import spkpf  # noqa: E402
import spkswitches  # noqa: E402


class StandIn:
    def __init__(self, made):
        self.made = made
        self.asked = []

    def ask(self, line):
        if line != "state":
            self.asked.append(line)
        if line == "state":
            return {"up": True, "switches": {str(n): 1 for n in self.made}}
        return {}

    def close(self):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="um")
    ap.add_argument("--made", default="")
    ap.add_argument("--hold", default="", help="x,y on the page: hover there (tooltip shot), "
                    "then hold the mouse button down and say what the rig was asked")
    args = ap.parse_args()
    made = [int(x) for x in args.made.split(",") if x.strip()]
    table = spkswitches.table(key=args.title)
    spkpf.Rig = lambda _distro, _slot: StandIn(made)   # never the real board
    app, _rig, host = spkpf.serve(table)
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page(viewport={"width": 1000, "height": 980})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(host.url())
        time.sleep(4)
        page.screenshot(path=args.out)
        if args.hold:
            x, y = (int(v) for v in args.hold.split(","))
            page.mouse.move(x, y)
            time.sleep(1.2)
            page.screenshot(path=args.out.replace(".png", "_tip.png"))
            page.mouse.down()
            time.sleep(0.6)
            page.mouse.up()
            time.sleep(0.6)
            print("rig asked:", app.rig.asked)
        b.close()
    app.stopping = True
    host.stop()
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
