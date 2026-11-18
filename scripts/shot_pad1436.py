"""PAD-1436 proof shot: the app when a Send's connection to the machine drops part way.

    python scripts/shot_pad1436.py <out-dir> <name>

writes <out-dir>/<name>.png: the app with a Send started from the Network tab, shot a few seconds after its
connection dropped under an in-place update.  The machine is the app's own SshMachine over a stand-in link (no
network) that drops once, with paramiko's own "Server connection dropped" error, the way the report's did.  Before
PAD-1436 the Send ended there ("Unexpected error: Server connection dropped"); after it, the app connects again and
the Send carries on.  The server runs from THIS tree against a scratch settings folder (the shot_pad1433.py rig).
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
import paramiko
from pinball_decryptor.core import remote_send as R
from pinball_decryptor.webui import compat, host
from pinball_decryptor.webui import window as W

class Link:
    up = True
    def is_active(self):
        return self.up
    def close(self):
        self.up = False

class File:
    def __init__(self, m):
        self.m = m
    def __enter__(self):
        return self
    def __exit__(self, *e):
        return False
    def set_pipelined(self, on):
        pass
    def seek(self, off):
        pass
    def flush(self):
        pass
    def write(self, data):
        self.m.writes += 1
        if self.m.writes == 3:
            self.m.t.up = False
            raise paramiko.SSHException("Server connection dropped: ")
        time.sleep(0.4)

class Sftp:
    def __init__(self, m):
        self.m = m
    def open(self, path, mode):
        return File(self.m)
    def close(self):
        pass

class Machine(R.SshMachine):
    def __init__(self):
        self.host, self.port, self._timeout, self.writes, self._boot = "192.168.4.130", 22, 15, 0, "b1"
        self._dial()
    def _dial(self):
        time.sleep(1.5)
        self.t, self.sftp = Link(), Sftp(self)
    def sh(self, script, stdin=b"", timeout=600, check=True):
        return 0, "b1\n" if "boot_id" in script else ""

def fake_send_image(image, machine, log=None, progress=None, cancel=None):
    log("Comparing everything on the machine with %%s..." %% image, "info")
    for i in range(0, 41, 4):
        progress(i, 100, "Comparing")
        time.sleep(0.2)
    total = 64 << 20
    log("Sending 3 change(s): 3 file(s) (64.0 MB), 0 link(s), 0 removal(s).", "info")
    base = "/games/godzilla_le/assets/lcd/auto_loaded/60ed7e5036b8ce09d35a3e101ea6fc1380b37d97/scene.assets/2.asset/"
    for n, name in enumerate(("630.asset", "631.asset", "632.asset")):
        log("Updating %%s%%s (21.3 MB; only the parts that differ are sent)..." %% (base, name), "info")
        machine.write_ranges(base + name, [(i << 20, b"x") for i in range(4)])
        progress((n + 1) * total // 3, total, "Updating")
    time.sleep(120)
    return "done"

R.connect = lambda address, log=None: Machine()
R.send_image = fake_send_image
compat.messagebox.askyesno = lambda *a, **k: True
W.WebWindow.ask_open = lambda self, *a, **k: r"C:\cards\Godzilla Premium 1.16 Heisei Custom V2.1 Kaiju Edition.raw"
sys.exit(host.main(sys.argv[1:]))
'''


def shoot(out_dir, name):
    scratch = tempfile.mkdtemp(prefix="pad1436-")
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
            time.sleep(14)
            page.screenshot(path=os.path.join(out_dir, "%s.png" % name))
            print("shot in", out_dir, flush=True)
            browser.close()
    finally:
        proc.terminate()


def main():
    out_dir, name = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    shoot(out_dir, name)


if __name__ == "__main__":
    main()
