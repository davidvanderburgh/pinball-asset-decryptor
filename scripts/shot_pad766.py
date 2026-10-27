"""PAD-766 proof shots: Ctrl + the mouse wheel zooms the whole app.

    python scripts/shot_pad766.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive``
of main for the "before" shots).  Writes <out_dir>/<prefix>_wheel.png (the
app after two Ctrl + wheel-up notches) and <prefix>_zoom_menu.png (the gear
menu's Zoom cascade, open).  Settings are a scratch copy: the zoom it saves
never reaches the real settings.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    scratch = tempfile.mkdtemp(prefix="pad766-")
    launcher = os.path.join(scratch, "launch766.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1360, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            page.mouse.move(680, 450)
            page.keyboard.down("Control")
            for _ in range(2):
                page.mouse.wheel(0, -100)     # one notch up on Windows
                time.sleep(0.4)
            page.keyboard.up("Control")
            time.sleep(1.5)
            print("zoom:", page.evaluate("document.documentElement.style.zoom || '1'"), flush=True)
            print("saved:", json.load(open(os.path.join(
                scratch, "cfg", "pinball_decryptor", "settings.json"),
                encoding="utf-8")).get("ui_zoom"), flush=True)
            out = os.path.join(out_dir, "%s_wheel.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            page.get_by_role("button", name="Settings").first.click()
            time.sleep(0.6)
            page.get_by_role("menuitem", name="Zoom").first.hover()
            time.sleep(0.8)
            out = os.path.join(out_dir, "%s_zoom_menu.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
