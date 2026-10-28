"""PAD-780 proof shots: Report a problem in the top bar, on an error box, and its window.

    python scripts/shot_pad780.py <repo> <out_dir>

Serves <repo> on a scratch settings folder with Stern picked, then shoots:
``topbar.png`` (the top bar: after PAD-780 it carries a Report a problem button),
``errorbox.png`` (an error box the app's own messagebox raised: after, it has a
"Report a problem…" link) and, where the window exists, ``report.png`` (the window
opened from that link, the error's words carried in, the record previewed).
Needs Playwright (PAD_PWLIB or the user site) and Edge.
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

# the launcher: the real app, plus a thread that raises a real error box
# (through the app's own messagebox shim) when the driver drops a marker
HOST = r'''
import os, sys, threading, time
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import compat, host
MARK = %(mark)r
def _poke():
    while not os.path.exists(MARK):
        time.sleep(0.3)
    compat.messagebox.showerror(
        "Write failed",
        "The card could not be written: the device is in use by another program.")
threading.Thread(target=_poke, daemon=True).start()
sys.exit(host.main(sys.argv[1:]))
'''


def main():
    repo, out_dir = sys.argv[1:3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad780-")
    mark = os.path.join(scratch, "show_error")
    launcher = os.path.join(scratch, "launch780.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": repo, "mark": mark})
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
            with open(mark, "w") as f:
                f.write("now")
            page.wait_for_selector("div[role=alertdialog]", timeout=20000)
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, "errorbox.png"))
            print("shot errorbox.png", flush=True)
            link = page.locator("div[role=alertdialog] button.dlg-report")
            if link.count():
                link.first.click()
                page.wait_for_selector("#sx-rep-text", timeout=20000)
                page.fill("#sx-rep-text", page.input_value("#sx-rep-text")
                          + "pressing Write on my Godzilla LE card after "
                          "replacing two songs.")
                page.locator("details.sx-rep-facts summary").click()
                page.wait_for_selector("pre.sx-rep-pre", timeout=20000)
                time.sleep(1.5)
                page.screenshot(path=os.path.join(out_dir, "report.png"))
                print("shot report.png", flush=True)
            else:
                page.locator("div[role=alertdialog] button", has_text="OK").click()
                print("no report window in this build", flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
