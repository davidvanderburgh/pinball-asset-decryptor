"""PAD-1088 shots: Capcom on the Extract tab (the Basic box, every sound out
of the sound ROMs), and the same tab after a Basic extract ran.

    python scripts/shot_pad1088.py <out.png> <rom.zip> <project dir> [--run]

The server runs from the repo this script sits in (copy it into a
``git archive`` export for the BEFORE shot), against scratch settings.
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import webui_shot as ws  # noqa: E402


def main():
    out, rom, project = sys.argv[1:4]
    run = "--run" in sys.argv
    scratch = tempfile.mkdtemp(prefix="padshot1088-")
    # pip --user packages live under the real APPDATA (Crypto, PIL)
    env = {"PYTHONUSERBASE": os.path.join(os.environ["APPDATA"], "Python")}
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True,
                   "getting_started_at_launch": False}, f)
    proc, url = ws.start_server(settings, scratch, extra_env=env)
    from playwright.sync_api import sync_playwright
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            ws.api(url, "ui.pick_manufacturer", "capcom")
            ws.api(url, "ui.set", "extract", "output", project)
            ws.api(url, "ui.set", "extract", "input", rom)
            ws.api(url, "ui.select_tab", "extract")
            st = ws.state(url)
            print("tabs", [t["ns"] for t in st["shell"]["tabs"]
                           if t["visible"]])
            if run:
                # Basic only: the capture box off
                for name, val in (("capture", False), ("static", True)):
                    try:
                        ws.api(url, "ui.set", "extract", name, val)
                    except RuntimeError as e:
                        print("set", name, "->", e)
                ws.api(url, "extract.start")
                deadline = time.time() + 600
                while time.time() < deadline:
                    if not ws.state(url)["shell"].get("running"):
                        break
                    time.sleep(1)
                ws.api(url, "extract.refresh_project")
                print("footer", ws.state(url)["shell"].get("footer"))
            time.sleep(3)
            page.screenshot(path=out)
            print("shot", out)
            browser.close()
    finally:
        proc.terminate()
    for e in errors:
        print("PAGE ERROR", e)
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
