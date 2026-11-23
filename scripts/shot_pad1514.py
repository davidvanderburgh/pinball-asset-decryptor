"""PAD-1514 proof shots: a card image opened from Explorer.

    python scripts/shot_pad1514.py <out_dir> <image> [<name>]
    python scripts/shot_pad1514.py <out_dir> --gear [<name>]

Starts this checkout's app the way Explorer's double-click does (the image's
path on the command line), on scratch settings that last had JJP open, and
shoots the window once it settles (out_dir/<name>.png, default "opened").
On the ticket branch it is on the image's manufacturer with the Flash image
dialog open on it; on main the path was ignored.

Needs Playwright (the user site-packages one) and the installed Edge.
--gear shoots the gear menu's Card images submenu instead (out_dir/gear.png),
as the installed app shows it.

Nothing is written: the shot never presses Start, and the gear shot never
clicks the switch.
"""
import json
import os
import site
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402


GEAR_LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import open_image
open_image.install_dir = lambda: r"C:\Program Files\Pinball Asset Decryptor"
# the menu as installed, but never the association itself: a shot must not
# write this PC's registry
open_image.register_association = lambda *a, **k: False
open_image.unregister_association = lambda *a, **k: False
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def gear(out_dir, name):
    repo = os.path.dirname(HERE)
    scratch = tempfile.mkdtemp(prefix="pad1514-")
    launcher = os.path.join(scratch, "launch1514.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(GEAR_LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True,
                   "last_manufacturer": "stern"}, f)
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(
        settings, scratch, extra_env=env,
        app_cmd=[sys.executable, launcher])
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 800})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(3)
            page.mouse.click(1370, 25)
            time.sleep(1)
            page.get_by_text("Card images", exact=True).first.hover()
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, name + ".png"))
            browser.close()
    finally:
        proc.terminate()


def main():
    out_dir = os.path.abspath(sys.argv[1])
    os.makedirs(out_dir, exist_ok=True)
    if sys.argv[2] == "--gear":
        return gear(out_dir, sys.argv[3] if len(sys.argv) > 3 else "gear")
    image = os.path.abspath(sys.argv[2])
    name = sys.argv[3] if len(sys.argv) > 3 else "opened"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1514-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp"},
                  f)
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(
        settings, scratch, extra_env=env,
        app_cmd=[sys.executable, "-m", "pinball_decryptor.webui.host",
                 image])
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(6)
            page.screenshot(path=os.path.join(out_dir, name + ".png"))
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
