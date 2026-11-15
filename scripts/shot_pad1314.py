"""PAD-1314 proof shots: Build / make USB install stick names the stick size.

    python scripts/shot_pad1314.py <repo> <out_dir>

Serves <repo> (the ticket branch, or a ``git archive`` of main for the
"before" shots) on a scratch settings folder with a JJP project, and opens
the Write tab's Build / make USB install stick dialog.  The original ISO
reads as 3.80 GB and a built one as 4.20 GB (``os.path.getsize`` answers
those sizes; nothing that big is written), and the only drive listed is a
stand-in 4 GB USB stick (no real drive is ever listed or touched; Start is
never pressed).  Three shots:

* ``first_build.png``  - Build and Prepare both ticked, nothing built yet;
* ``build_ticked.png`` - the same over an earlier 4.20 GB build;
* ``iso_picked.png``   - Prepare only, the 4.20 GB built ISO picked.

Needs Playwright (PAD_PWLIB or the user site) and Edge.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import os, sys
sys.path.insert(0, %(repo)r)
print("PAD1314 serving", %(repo)r, flush=True)
SIZES = {os.path.normcase(%(original)r): 3800000000,
         os.path.normcase(%(built)r): 4200000000}
_getsize = os.path.getsize
os.path.getsize = lambda p: SIZES.get(os.path.normcase(str(p))) or _getsize(p)
from pinball_decryptor.core.drives import PhysicalDrive
from pinball_decryptor.webui import write_dialogs as wd
from pinball_decryptor.webui import host
STICK = PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE97",
                      model="SanDisk Cruzer Blade", size_bytes=4000000000,
                      bus_type="USB", mount_label="F:")
wd._enumerate = lambda prefer: ([STICK], (STICK, "high", ""))
wd.FlashDialog.start = lambda self: False
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1314-")
    project = os.path.join(scratch, "Elton John Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".checksums.md5"), "w") as f:
        f.write("")
    original = os.path.join(scratch, "eltonjohn-1.21.0.iso")
    with open(original, "wb") as f:
        f.write(b"\0" * 4096)
    builds = os.path.join(scratch, "builds")
    os.makedirs(builds)
    built = os.path.join(builds, "eltonjohn-1.21.0-modified.iso")
    launcher = os.path.join(scratch, "launch1314.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo, "original": original,
                            "built": built})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {
                       "extract_output": project,
                       "write_original": original,
                       "write_assets": project,
                       "write_output": builds}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
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
            webui_shot.api(url, "write.flash_set", "build", True)
            webui_shot.api(url, "write.flash_set", "write", True)
            time.sleep(1.5)
            shot = os.path.join(out_dir, "first_build.png")
            page.screenshot(path=shot)
            print("shot", shot, flush=True)
            # an earlier build now sits at the build path
            with open(built, "wb") as f:
                f.write(b"x" * 4096)
            webui_shot.api(url, "write.flash_set", "write", False)
            webui_shot.api(url, "write.flash_set", "write", True)
            time.sleep(1.5)
            shot = os.path.join(out_dir, "build_ticked.png")
            page.screenshot(path=shot)
            print("shot", shot, flush=True)
            webui_shot.api(url, "write.flash_set", "build", False)
            webui_shot.api(url, "write.flash_set", "image_path", built)
            time.sleep(1.5)
            shot = os.path.join(out_dir, "iso_picked.png")
            page.screenshot(path=shot)
            print("shot", shot, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
