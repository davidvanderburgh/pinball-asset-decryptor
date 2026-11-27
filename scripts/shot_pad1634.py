"""PAD-1634 capture: the service buttons of a machine whose card has no remote buttons, on My machines' Remote
panel and on the Network tab.

    python scripts/shot_pad1634.py --out <dir> --prefix before_|after_ [--address 192.168.4.166] [--press]

Like shot_pad1632.py this reads a REAL machine through a scratch copy of this computer's settings and remote
access records (deleted afterwards): its status and one picture of its screen.  --press also presses Enter the
way the page does, which on a card WITHOUT remote buttons only asks the machine whether it has them (nothing is
pressed); never pass it for a machine that has them and whose coin door is open.  Two screens:

* <prefix>buttons_machines.png - My machines, the machine's Remote panel;
* <prefix>buttons_network.png  - the Network tab pointed at the same machine.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import webui_shot as ws  # noqa: E402


#: --fake: the app, with remote access answered by a machine whose card has no remote buttons
FAKE = """import os, runpy, sys
sys.path.insert(0, os.getcwd())                         # the repo the rig started it in
from pinball_decryptor.core import remote_send


class Machine:
    def sh(self, script, timeout=20, check=True):
        return 0, "up 5000\\ncard off\\nnone\\n"

    def close(self):
        pass


remote_send.connect = lambda address, log=None: Machine()
sys.argv = ["pinball_decryptor.webui.host"] + sys.argv[1:]
runpy.run_module("pinball_decryptor.webui.host", run_name="__main__")
"""


def _net(url):
    return ws.state(url).get("network") or {}


def _until(url, ok, tries=160):
    for _ in range(tries):
        if ok(_net(url)):
            return True
        time.sleep(0.25)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--address", default="192.168.4.166")
    ap.add_argument("--press", action="store_true")
    ap.add_argument("--fake", action="store_true",
                    help="no machine is on: a stand-in that answers as a card without remote buttons does")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("REPO", REPO)
    real = os.path.join(os.environ["APPDATA"], "pinball_decryptor")
    scratch = tempfile.mkdtemp(prefix="padshot1634-")
    shutil.copytree(os.path.join(real, "remote_access"),
                    os.path.join(scratch, "cfg", "pinball_decryptor", "remote_access"))
    env = {"PAD_SHOT_ONLINE": a.address}
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    cmd = None
    if a.fake:
        launcher = os.path.join(scratch, "fake_machine_app.py")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write(FAKE)
        cmd = [sys.executable, launcher]
    proc, url = ws.start_server(os.path.join(real, "settings.json"), scratch, extra_env=env, app_cmd=cmd)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": a.width, "height": a.height})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for _ in range(240):
                if "stern" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            page.locator("button.sx-mach-open").first.click()
            for _ in range(60):
                if ((ws.state(url).get("shellx") or {}).get("machines") or {}).get("online"):
                    break
                time.sleep(0.25)
            print("remote", ws.api(url, "shellx.machines_remote", a.address))
            if not a.fake:
                print("status", ws.api(url, "network.machine_status"))
                _until(url, lambda n: n.get("care_status") or n.get("care_kind") == "err")
                print("capture", ws.api(url, "network.capture_screen"))
                _until(url, lambda n: n.get("screen_path") or n.get("screen_kind") == "err")
            if a.press:
                print("press", ws.api(url, "network.press_button", "enter"))
                time.sleep(0.3)
                _until(url, lambda n: not n.get("buttons_busy"))
            n = _net(url)
            print(json.dumps({k: n.get(k) for k in ("address", "buttons_note", "buttons_kind", "buttons_need")}))
            time.sleep(1.5)
            page.screenshot(path=os.path.join(a.out, a.prefix + "buttons_machines.png"), full_page=True)
            print("network tab", ws.api(url, "shellx.machines_go_network", a.address))
            time.sleep(2.5)
            col = page.locator(".net-btn-row").first
            if col.count():
                col.scroll_into_view_if_needed()
            time.sleep(1.0)
            page.screenshot(path=os.path.join(a.out, a.prefix + "buttons_network.png"))
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
