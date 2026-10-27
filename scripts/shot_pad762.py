r"""PAD-762 proof: the top bar's Donate button without the running total.

    python scripts/shot_pad762.py --out <dir> --tag before|after

Serves THIS tree's app against PAD-754's seeded stand-in for the donations
Worker (a $4,320 tally), waits until the app knows the total, and shoots the
top bar in the dark and the light theme.  Fails if the button still shows
the total ("after") or the total never arrived.
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
    scratch = tempfile.mkdtemp(prefix="pad762-")
    proc, url = webui_shot.start_server("", scratch,
                                        extra_env={"PAD_DONATIONS_URL": service})
    errors = []
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.on("console", lambda m: errors.append("console.error: %s" % m.text)
                    if m.type == "error" else None)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            keys = [m["key"] for m in webui_shot.state(url)["shell"]["mfrs"]]
            pick = [k for k in keys if "stern" in k.lower()] or keys
            webui_shot.api(url, "ui.pick_manufacturer", pick[0])
            known = False
            for _ in range(40):
                d = webui_shot.state(url).get("shellx", {}).get("donations")
                if d and d.get("known"):
                    known = True
                    break
                time.sleep(0.25)
            if not known:
                errors.append("the app never learned the tally")
            time.sleep(1.5)
            label = page.inner_text(".sx-don-btn").strip()
            print("button reads %r" % label)
            if args.tag == "after" and "$" in label:
                errors.append("the Donate button still shows an amount: %r" % label)
            tip = page.get_attribute(".sx-don-btn", "aria-label")
            print("aria-label %r" % tip)

            def shoot(name):
                path = os.path.join(args.out, "%s_%s.png" % (args.tag, name))
                page.screenshot(path=path, clip={"x": 0, "y": 0, "width": 1440, "height": 56})
                print("shot", path, flush=True)

            shoot("topbar")
            webui_shot.api(url, "ui.set_theme", "light")
            time.sleep(1.5)
            shoot("topbar_light")
            webui_shot.api(url, "ui.set_theme", "dark")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    for e in errors:
        print("ERROR", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
