"""PAD-815 proof shots: the Discord button in the top bar.

    python scripts/shot_pad815.py <repo> <out_dir>

Serves <repo> on a scratch settings folder with Stern picked, then shoots
``topbar.png`` (the whole top bar) and, where the button exists,
``topbar_hover.png`` (its tooltip showing) and clicks it: the app's
``desktop.open_url`` is swapped for a recorder, so the click proves which
link would open without starting a browser.  The link it got is printed and
written to ``<out_dir>/opened.txt``.  Needs Playwright (PAD_PWLIB or the
user site) and Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

# the launcher: the real app, with the browser opener recording instead
HOST = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import desktop
def _record(url, env=None):
    with open(%(log)r, "a", encoding="utf-8") as f:
        f.write(url + "\n")
    return True, ""
desktop.open_url = _record
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    repo, out_dir = sys.argv[1:3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad815-")
    log = os.path.join(scratch, "opened.txt")
    launcher = os.path.join(scratch, "launch815.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo, "log": log})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PAD_REPORTS_URL": "http://127.0.0.1:9"})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(4)
            page.screenshot(path=os.path.join(out_dir, "topbar.png"),
                            clip={"x": 0, "y": 0, "width": 1500, "height": 64})
            print("shot topbar.png", flush=True)
            btn = page.locator("header.topbar button.sx-discord-btn")
            if btn.count():
                btn.hover()
                time.sleep(1)
                page.screenshot(path=os.path.join(out_dir, "topbar_hover.png"),
                                clip={"x": 600, "y": 0, "width": 900, "height": 130})
                print("shot topbar_hover.png", flush=True)
                btn.click()
                for _ in range(80):
                    if os.path.exists(log):
                        break
                    time.sleep(0.25)
                got = open(log, encoding="utf-8").read().strip() if os.path.exists(log) else ""
                print("opened:", got or "(nothing)", flush=True)
                with open(os.path.join(out_dir, "opened.txt"), "w", encoding="utf-8") as f:
                    f.write(got + "\n")
            else:
                print("no Discord button in this build", flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            pass
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
