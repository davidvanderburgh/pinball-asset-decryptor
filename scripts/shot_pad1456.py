"""PAD-1456 proof shots: Find my machine on a stand-in of David's mesh, where the sweep misses a machine just
switched on.

    python scripts/shot_pad1456.py <repo> <out_dir> [--card <raw>] [--project <dir>] [--before]

Serves <repo> on scratch settings with the card and a project, and runs the repo's own scan
(``machine_scan.scan``) over a stand-in 192.168.4.0/22: a Raspberry Pi at .26 always answers, the Godzilla at .135
answers only an unhurried ask (the sweep's burst of ARP lost its answer on David's network).  Shoots the Network tab
while the scan runs (out_dir/network_scan_running.png) and when it is done (out_dir/network_scan.png).  Before
(main) the scan lists only the Pi; after, it looks again slowly and finds the Godzilla.

Needs Playwright (the user site-packages one), the installed Edge and the card.
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

LAUNCHER = r'''
import ipaddress, os, sys, time
sys.path.insert(0, %r)
from pinball_decryptor.core import pad_ssh_key, machine_scan as ms
pad_ssh_key.KEY_DIR = os.path.join(%r, "remote_access")
PI, GODZILLA = "192.168.4.26", "192.168.4.135"
ms.networks = lambda *a, **k: [ipaddress.IPv4Network("192.168.4.0/22")]
ms.local_addresses = lambda: [ipaddress.IPv4Address("192.168.4.162")]
ms.neighbours = lambda: []
CAREFUL = getattr(ms, "CAREFUL_TIMEOUT", None)

def banner(host, port, timeout):
    host = str(host)
    time.sleep(0.4 if timeout == CAREFUL else 0.3)
    if host == PI:
        return "SSH-2.0-OpenSSH_7.9p1 Raspbian-10+deb10u1"
    if host == GODZILLA and timeout == CAREFUL:
        return "SSH-2.0-dropbear_2025.88"
    return None
ms._banner = banner
ms.probe = lambda host, port=22, timeout=8: (
    dict(lets_in=True, game="godzilla_le", host_key=("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIGodzillaKing"), note="")
    if host == GODZILLA else dict(lets_in=False, game="", host_key=None, note="doesn't let this computer in"))
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    os.makedirs(out_dir, exist_ok=True)
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    src_project = _arg("--project", r"C:\tmp\PAD-1397\proj_B")
    scratch = tempfile.mkdtemp(prefix="pad1456-")
    project = os.path.join(scratch, "project")
    shutil.copytree(src_project, project)
    launcher = os.path.join(scratch, "launch1456.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, scratch))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1400})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "extract")
            webui_shot.api(url, "extract.use_recent", "input", card)
            time.sleep(6)
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(3)
            try:
                page.get_by_text("Hide log").first.click(timeout=3000)
            except Exception:                                            # noqa: BLE001
                pass
            time.sleep(1)
            webui_shot.api(url, "network.scan")
            # mid-scan: the careful pass when there is one (after), else halfway through the sweep (before)
            if "--before" in sys.argv:
                time.sleep(1.5)
            else:
                page.get_by_text("Looking again").first.wait_for(timeout=20000)
                time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, "network_scan_running.png"), full_page=True)
            for _ in range(240):
                time.sleep(0.5)
                if not webui_shot.api(url, "network.scan_state"):
                    break
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "network_scan.png"), full_page=True)
            print("saved", out_dir, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
