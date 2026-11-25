"""PAD-1556 proof shot: the Flash dialog's drive list on a PC whose
PowerShell ``Get-Disk`` answers nothing.

    python scripts/shot_pad1556.py <repo> <out.png>

Serves <repo> (the ticket branch, or a ``git archive`` of main for the
"before" shot) on a scratch settings folder and opens the Write tab's Build /
flash dialog on a scratch 1 MB image.  Every PowerShell ``Get-Disk`` call the
app makes is answered with nothing at all, the way it is on a PC whose
storage management service is off: before, the picker says "(no drives found
- click Refresh)" although Windows shows the card; after, the drives are
listed from the disks themselves.  Nothing is written anywhere: the shot is
taken with the dialog open and Start never pressed.  Needs Playwright
(PAD_PWLIB or the user site) and Edge.
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
import subprocess, sys
sys.path.insert(0, %(repo)r)
print("PAD1556 serving", %(repo)r, flush=True)
_real_run = subprocess.run
def _run(cmd, *a, **kw):
    if isinstance(cmd, (list, tuple)) and any("Get-Disk" in str(c) for c in cmd):
        print("PAD1556 Get-Disk answered with nothing", flush=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return _real_run(cmd, *a, **kw)
subprocess.run = _run
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1556-")
    project = os.path.join(scratch, "GZ 1.16 Premium Extract")
    os.makedirs(project)
    original = os.path.join(scratch, "godzilla_le-1_16_0.img")
    with open(original, "wb") as f:
        f.truncate(1 << 20)
    builds = os.path.join(scratch, "builds")
    os.makedirs(builds)
    image = os.path.join(builds, "Godzilla Premium 1.16 multi.raw")
    with open(image, "wb") as f:
        f.write(os.urandom(1 << 20))
    launcher = os.path.join(scratch, "launch1556.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project,
                       "write_original": original,
                       "write_assets": project,
                       "write_output": builds}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1360, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            webui_shot.api(url, "ui.select_tab", "write")
            time.sleep(1)
            webui_shot.api(url, "write.primary")
            time.sleep(3)
            webui_shot.api(url, "write.flash_set", "build", False)
            webui_shot.api(url, "write.flash_set", "image_path", image)
            time.sleep(1)
            webui_shot.api(url, "write.flash_refresh_drives")
            for _ in range(40):
                time.sleep(1)
                if "Detecting drives" not in json.dumps(webui_shot.state(url)):
                    break
            time.sleep(2)
            page.screenshot(path=out)
            print("shot", out, os.path.getsize(out), flush=True)
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
