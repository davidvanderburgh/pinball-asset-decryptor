r"""PAD-819 proof shots: Settings > Manage disk space, and its Move to another drive prompt.

    python scripts/shot_pad819_disk.py <app tree> <out_dir> <prefix>

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after"). Nothing runs
in WSL and nothing moves: the scan is answered with a stand-in for a user whose C: is nearly full - the app's Linux
(48 GB) and the emulators' data disk (6 GB) on C:, a roomy D:, and a Google Drive letter WSL cannot use.
Writes <prefix>disk_space.png (the window, scrolled to its foot) and, on a tree that has it, <prefix>move_prompt.png.
"""

import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %(tree)r)
GB = 2 ** 30
from pinball_decryptor.core import host_temp, wsl_disk
host_temp.usage = lambda: {"total": 476 * GB, "used": 464 * GB, "free": 12 * GB, "pct": 97, "drive": "C:"}
host_temp.scan = lambda: []
wsl_disk.available = lambda: (True, "")
wsl_disk.usage = lambda: {"total": 1007 * GB, "used": 41 * GB, "free": 966 * GB, "pct": 4}
wsl_disk.scan_staging = lambda: []
wsl_disk.scan_rigs = lambda: []
RT = r"C:\Users\simon\AppData\Local\pinball_decryptor"
wsl_disk.vhdx_info = lambda: {"distro": "PAD-Runtime", "path": RT + r"\runtime\ext4.vhdx",
                              "size": 48 * GB, "reclaimable": 7 * GB}
try:
    from pinball_decryptor.core import wsl_place
    wsl_place.items = lambda: [
        {"key": "distro", "distro": "PAD-Runtime", "label": "the app's Linux (PAD-Runtime)",
         "path": RT + r"\runtime\ext4.vhdx", "size": 48 * GB, "pinned": ""},
        {"key": "data", "label": "the emulators' data disk", "path": RT + r"\data\pad-data.vhdx",
         "size": 6 * GB, "pinned": ""}]
    wsl_place.move_supported = lambda: (True, "")
    wsl_place.drives = lambda: [
        {"letter": "C:", "label": "Windows", "fs": "NTFS", "free": 12 * GB, "total": 476 * GB, "ok": True, "why": ""},
        {"letter": "D:", "label": "Data", "fs": "NTFS", "free": 1210 * GB, "total": 1863 * GB, "ok": True, "why": ""},
        {"letter": "G:", "label": "Google Drive", "fs": "FAT32", "free": 100 * GB, "total": 200 * GB,
         "ok": False, "why": "FAT32: WSL needs NTFS"}]
    wsl_place.move = lambda *a, **k: []
except ImportError:
    pass
from pinball_decryptor.webui import shellx_disk, emu_cache
shellx_disk._probes_allowed = lambda: True
emu_cache.scan_emu_cache = lambda: ([], None)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    tree, out_dir, prefix = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad819-")
    launcher = os.path.join(scratch, "launch819.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "", "PAD_UI_NO_PREREQS": "",
           "PAD_SPACE_KEEPER": "0", "PAD_SPACE_STATE": os.path.join(scratch, "keeper.json")}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env, app_cmd=[sys.executable, launcher])
    print("tree", tree)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1300, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.settings_action", "disk_space")
            for _ in range(60):
                d = (webui_shot.state(url).get("shellx") or {}).get("disk") or {}
                if d and not d.get("busy") and str(d.get("status", "")).startswith("No leftover"):
                    break
                time.sleep(0.5)
            time.sleep(1)
            # the foot of the window, where Reclaim / Resize (and now Move) are
            page.evaluate("""() => { for (const el of document.querySelectorAll('.modal *')) {
                if (el.scrollHeight > el.clientHeight + 4) el.scrollTop = el.scrollHeight; } }""")
            time.sleep(0.5)
            shot = os.path.join(out_dir, prefix + "disk_space.png")
            page.locator(".modal").last.screenshot(path=shot)
            print("shot", shot)
            btn = page.get_by_role("button", name="Move to another drive…")
            if btn.count():
                btn.click()
                page.get_by_role("button", name="Move…").wait_for(timeout=20000)
                time.sleep(0.8)
                shot = os.path.join(out_dir, prefix + "move_prompt.png")
                page.locator(".modal").last.screenshot(path=shot)
                print("shot", shot)
                # Move… asks first: shoot the question, answer No
                page.get_by_role("button", name="Move…").click()
                page.get_by_role("button", name="No", exact=True).wait_for(timeout=20000)
                time.sleep(0.8)
                shot = os.path.join(out_dir, prefix + "move_confirm.png")
                page.locator(".modal").last.screenshot(path=shot)
                print("shot", shot)
                page.get_by_role("button", name="No", exact=True).click()
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
