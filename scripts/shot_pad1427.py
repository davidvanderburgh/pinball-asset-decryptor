"""PAD-1427 proof shots: the Network tab's remote access, made friendly (Stern Spike 2, Deadpool LE).

    python scripts/shot_pad1427.py <repo> <out_dir> [--card <raw>] [--project <dir>] [--scan]

Serves <repo> on scratch settings with the card and a project, then shoots the Network tab (out_dir/network.png).
With --scan (after only) it also runs a scan of a stand-in network (PAD_SCAN_FAKE) and shoots the result
(out_dir/network_scan.png).  Before (main) the tab asks for keys and an IP address up front; after, it has a
one-button card setup and a Find my machine scan, the manual fields folded under Advanced.

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
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import pad_ssh_key
import os
pad_ssh_key.KEY_DIR = os.path.join(%r, "remote_access")
if os.environ.get("PAD1427_STANDIN"):
    # the after shots: an SD card in the reader, and a home network with the machine on it (stand-ins)
    from pinball_decryptor.core import drives, machine_scan
    drives.list_physical_drives = lambda: [drives.PhysicalDrive("\\\\.\\PhysicalDrive3", "Generic SD/MMC",
                                                                7948206080, "USB")]
    machine_scan.scan = lambda **k: [
        dict(address="192.168.1.57", banner="dropbear", lets_in=True, game="deadpool_le",
             host_key=("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIKDaXqujG6r80I"), note=""),
        dict(address="192.168.1.62", banner="dropbear", lets_in=True, game="guardians_le",
             host_key=("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIGuardiansGuard"), note=""),
        dict(address="192.168.1.73", banner="dropbear", lets_in=True, game="james_bond_007_le",
             host_key=("ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIBondJamesBond0"), note="")]
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
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\deadpool_le-1_16_0.Release.8G.sdcard.raw")
    src_project = _arg("--project", r"C:\tmp\PAD-1397\proj_B")
    scratch = tempfile.mkdtemp(prefix="pad1427-")
    project = os.path.join(scratch, "project")
    shutil.copytree(src_project, project)
    launcher = os.path.join(scratch, "launch1427.py")
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
    if "--scan" in sys.argv:
        env["PAD1427_STANDIN"] = "1"
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
            page.screenshot(path=os.path.join(out_dir, "network.png"), full_page=True)
            if "--scan" in sys.argv:
                webui_shot.api(url, "network.scan")
                for _ in range(40):
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
