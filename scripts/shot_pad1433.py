"""PAD-1433 proof shot: the status bar while a Send to machine runs.

    python scripts/shot_pad1433.py <out-dir> <name>

writes <out-dir>/<name>-compare.png and <name>-send.png: the app with a Send started from the Network tab, shot
while it compares and while it sends.  The machine is a stand-in (no network): the Send's own progress is replayed
the way a real full Send reports it (the compare of the game files, then the bytes going over), so the shot is the
app's own footer, chips and progress text for that run.  Before PAD-1433 the footer showed the Write build's chips,
none lit; after it, the Send's own Connect / Compare / Send / Finish, the one it is on lit, and the rate and time
left while it sends.  The server runs from THIS tree against a scratch settings folder (the shot_pad980.py rig).
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

HOST = r'''
import sys, time
sys.path.insert(0, %(repo)r)
from pinball_decryptor.core import remote_send as R
from pinball_decryptor.webui import compat, host
from pinball_decryptor.webui import window as W

class Stand:
    def close(self):
        pass

def fake_send_image(image, machine, log=None, progress=None, cancel=None):
    log("Comparing everything on the machine with %%s..." %% image, "info")
    for i in range(0, 41, 4):
        progress(i, 100, "Comparing the game files" if hasattr(R, "SEND_PHASES") else "Comparing")
        time.sleep(0.3)
    time.sleep(6)
    total = 8800 << 20
    log("Sending 917 change(s): 902 file(s) (8.8 GB), 15 removal(s), and the boot partition.", "info")
    done = 0
    for _ in range(40):
        done += 1536 << 10
        progress(done, total, "Updating")
        time.sleep(0.5)
    time.sleep(120)
    return "done"

R.connect = lambda address, log=None: Stand()
R.send_image = fake_send_image
compat.messagebox.askyesno = lambda *a, **k: True
W.WebWindow.ask_open = lambda self, *a, **k: r"C:\cards\Godzilla Premium 1.16 Heisei Custom V2.3 Kaiju Edition.raw"
sys.exit(host.main(sys.argv[1:]))
'''


def shoot(out_dir, name):
    scratch = tempfile.mkdtemp(prefix="pad1433-")
    host = os.path.join(scratch, "host.py")
    with open(host, "w", encoding="utf-8") as f:
        f.write(HOST % {"repo": REPO})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, host],
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
                   "PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python")})
    print("repo", REPO, "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "network")
        webui_shot.api(url, "network.set_address", "192.168.4.130")
        time.sleep(3)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            print("send_image ->", webui_shot.api(url, "network.send_image"), flush=True)
            time.sleep(5)
            page.screenshot(path=os.path.join(out_dir, "%s-compare.png" % name))
            time.sleep(16)
            page.screenshot(path=os.path.join(out_dir, "%s-send.png" % name))
            print("shots in", out_dir, flush=True)
            browser.close()
    finally:
        proc.terminate()


def main():
    out_dir, name = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    shoot(out_dir, name)


if __name__ == "__main__":
    main()
