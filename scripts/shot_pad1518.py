"""PAD-1518 proof shot: the warning Card images > Open card images with PAD
logs when Windows' own choice for .raw is another app.

    python scripts/shot_pad1518.py <out_dir> [<name>]

Starts this checkout's app on scratch settings, ticks the gear switch and
shoots the window with the log showing (out_dir/<name>.png, default
"warning") plus the log line itself (out_dir/<name>.txt).  The association
is never written (register/unregister are stubbed); only this PC's real
UserChoice for .raw is read, so on a PC where Photos has .raw the line names
it.  Needs Playwright (the user site-packages one) and the installed Edge.
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import open_image
open_image.install_dir = lambda: r"C:\Program Files\Pinball Asset Decryptor"
open_image.register_association = lambda *a, **k: False
open_image.unregister_association = lambda *a, **k: False
open_image.ask_windows = lambda *a, **k: False   # never a real dialog
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    out_dir = os.path.abspath(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else "warning"
    os.makedirs(out_dir, exist_ok=True)
    repo = os.path.dirname(HERE)
    scratch = tempfile.mkdtemp(prefix="pad1518-")
    launcher = os.path.join(scratch, "launch1518.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
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
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(3)
            page.mouse.click(1370, 25)
            time.sleep(1)
            page.get_by_text("Card images", exact=True).first.hover()
            time.sleep(1)
            page.get_by_text("Open card images with PAD",
                             exact=True).first.click()
            time.sleep(2)
            line = page.get_by_text("Card images", exact=False).last
            line.scroll_into_view_if_needed()
            time.sleep(1)
            with open(os.path.join(out_dir, name + ".txt"), "w",
                      encoding="utf-8") as f:
                f.write(line.inner_text().strip() + "\n")
            page.screenshot(path=os.path.join(out_dir, name + ".png"))
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
