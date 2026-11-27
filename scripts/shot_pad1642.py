"""PAD-1642 proof shots: a whole-card flash that keeps "my network settings" but not the card's own settings,
and the Network tab's Find my machine finding nothing afterwards.

    python scripts/shot_pad1642.py <repo> <out_dir>

Serves <repo> (the ticket branch, or a ``git archive`` of main for the before shots) on scratch settings.  The
project is made to have remote access on (network_keep.options stubbed), so the Build / flash dialog offers "Keep
my network settings on this card" ticked with "Keep the SD card's settings, audits and high scores" not ticked, as
the reporter's flash was: out_dir/flash_dialog.png.  Then the Network tab's Find my machine runs over a stubbed
scan that finds nothing (the reporter's 253 addresses on a /24): out_dir/network_find.png.  Nothing is built,
flashed or scanned for real.
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
import os, sys
sys.path.insert(0, %r)
from pinball_decryptor.core import pad_ssh_key, network_keep, machine_scan
pad_ssh_key.KEY_DIR = os.path.join(%r, "remote_access")
network_keep.options = lambda project: {"ssh": {"enabled": True}}

def _scan(progress=None, cancel=None, report=None, note=None):
    if report is not None:
        report.update(addresses=253, networks=["192.168.68.0/24"], known=1, careful=253)
    if progress:
        progress(253, 253)
    return []
machine_scan.scan = _scan
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1642-")
    project = os.path.join(scratch, "IronMaiden2.0")
    os.makedirs(project)
    original = os.path.join(scratch, "iron_maiden_le-1_18_0.Release.8G.sdcard.raw")
    with open(original, "wb") as f:
        f.truncate(1 << 20)
    builds = os.path.join(scratch, "multi")
    os.makedirs(builds)
    image = os.path.join(builds, "IronMaiden2.0.multi.raw")
    with open(image, "wb") as f:
        f.truncate(1 << 20)
    launcher = os.path.join(scratch, "launch1642.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, scratch))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project, "write_original": original,
                       "write_assets": project, "write_output": builds}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1360, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "write")
            time.sleep(1)
            webui_shot.api(url, "write.primary")
            time.sleep(6)                       # the drive list settles
            webui_shot.api(url, "write.flash_set", "build", False)
            webui_shot.api(url, "write.flash_set", "image_path", image)
            time.sleep(1.5)
            out = os.path.join(out_dir, "flash_dialog.png")
            page.screenshot(path=out)
            print("shot", out, flush=True)
            webui_shot.api(url, "write.flash_close")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(3)
            try:
                page.get_by_text("Hide log").first.click(timeout=3000)
            except Exception:                                            # noqa: BLE001
                pass
            webui_shot.api(url, "network.scan")
            time.sleep(3)
            note = page.get_by_text("Found no device with remote login").first
            note.scroll_into_view_if_needed()
            time.sleep(1)
            box = note.bounding_box()
            out = os.path.join(out_dir, "network_find.png")
            top = max(0, box["y"] - 420)
            page.screenshot(path=out, clip={"x": 0, "y": top, "width": 1360,
                                            "height": min(1000 - top, box["y"] - top + box["height"] + 40)})
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
