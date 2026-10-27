r"""PAD-765 proof: the Animal shelters window's country list, before/after.

    python scripts/shot_pad765.py --out <dir> --tag before|after

Serves THIS tree's app against shot_pad754's seeded stand-in for the
donations Worker, opens the window and shows the Country list opened out
(the select drawn as a tall list box, since a headless browser never
paints a native drop-down), then shoots the form.  Prints the order too.
"""

import argparse
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
from shot_pad754 import Fake  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    service = Fake().start().url
    scratch = tempfile.mkdtemp(prefix="pad765-")
    proc, url = webui_shot.start_server("", scratch,
                                        extra_env={"PAD_DONATIONS_URL": service})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            keys = [m["key"] for m in webui_shot.state(url)["shell"]["mfrs"]]
            pick = [k for k in keys if "stern" in k.lower()] or keys
            webui_shot.api(url, "ui.pick_manufacturer", pick[0])
            for _ in range(40):
                d = webui_shot.state(url).get("shellx", {}).get("donations")
                if d and d.get("known"):
                    break
                time.sleep(0.25)
            webui_shot.api(url, "ui.settings_action", "donations")
            page.wait_for_selector(".sx-don-form .sx-don-country select", timeout=15000)
            time.sleep(1.0)
            sel = ".sx-don-form .sx-don-country select"
            labels = page.eval_on_selector(
                sel, "s => Array.from(s.options).map(o => o.textContent)")
            print("order:", " | ".join(labels), flush=True)
            page.eval_on_selector(sel, """s => {
                s.size = s.options.length; s.style.height = 'auto';
                s.style.maxHeight = 'none'; s.style.position = 'relative';
                s.style.zIndex = 50; s.scrollIntoView({block: 'start'}); }""")
            time.sleep(0.5)
            box = page.eval_on_selector(sel, """s => {
                const r = s.getBoundingClientRect();
                return {x: r.x, y: r.y, w: r.width, h: r.height}; }""")
            pad = 16
            clip = {"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                    "width": box["w"] + 2 * pad, "height": box["h"] + 2 * pad}
            path = os.path.join(args.out, "%s_country_list.png" % args.tag)
            page.screenshot(path=path, clip=clip)
            print("shot", path, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
