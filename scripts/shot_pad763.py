r"""PAD-763 proof: the Modes tab for every Stern Spike 2 user, no preview code.

    python scripts/shot_pad763.py --out <dir> --tag before|after

Serves THIS tree's app on a copy of David's settings with every preview code
taken out (what an ordinary user's copy holds), picks Stern, and shoots the
window on the Write tab (the tab rail shows whether Modes is there), the
Modes tab itself, and the Settings menu.  Fails "after" when the Modes tab is
not offered, or the Settings menu still offers Preview features.
"""

import argparse
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    print("serving", webui_shot.REPO)
    scratch = tempfile.mkdtemp(prefix="pad763-")
    real = os.path.expandvars(r"%APPDATA%\pinball_decryptor\settings.json")
    with open(real, encoding="utf-8") as f:
        settings = json.load(f)
    settings.pop("preview_codes", None)
    settings["last_manufacturer"] = "stern"
    src = os.path.join(scratch, "settings.json")
    with open(src, "w", encoding="utf-8") as f:
        json.dump(settings, f)
    proc, url = webui_shot.start_server(
        src, os.path.join(scratch, "srv"),
        extra_env={"PYTHONUSERBASE": os.path.expandvars(os.path.join(r"%APPDATA%", "Python"))})
    errors = []
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1.0)
            tabs = {t["ns"]: t["visible"]
                    for t in webui_shot.state(url)["shell"]["tabs"]}
            print("tabs", tabs)
            modes = [ns for ns in tabs if ns.lower() == "modes"]
            on = bool(modes and tabs[modes[0]])
            print("Modes tab offered:", on)
            if args.tag == "after" and not on:
                errors.append("the Modes tab is not offered without a code")

            def shoot(name):
                time.sleep(2.5)
                path = os.path.join(args.out, "%s_%s.png" % (args.tag, name))
                page.screenshot(path=path)
                print("shot", path, flush=True)

            webui_shot.api(url, "ui.select_tab", "write")
            shoot("tabs")
            if on:
                webui_shot.api(url, "ui.select_tab", modes[0])
                shoot("modes")
            items = (webui_shot.state(url).get("shell", {})
                     .get("settings_items") or [])
            ids = [i.get("id") for i in items]
            print("settings menu", ids)
            if args.tag == "after" and "preview_features" in ids:
                errors.append("Settings still offers Preview features")
            page.click(".sx-gear button[aria-label='Settings']")
            shoot("settings")
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
