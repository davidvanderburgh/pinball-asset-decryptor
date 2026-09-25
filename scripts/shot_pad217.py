"""PAD-217 proof shots: the Stern Build / flash dialog, as it opens and (on a
tree that has it) with "Skip verify" ticked.

    python scripts/shot_pad217.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive``
of the commit before it for the "before" shots).  Writes
<out_dir>/<prefix>_flash_dialog.png and <prefix>_flash_dialog_skip_ticked.png
(the second is the same as the first on a tree without the tick).  The
Write tab points at scratch paths, so nothing real is built or flashed; the
SD card picker lists this PC's real drives.
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
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    scratch = tempfile.mkdtemp(prefix="pad217-")
    project = os.path.join(scratch, "GZ 1.16 Pro Extract")
    os.makedirs(project)
    original = os.path.join(scratch, "godzilla_pro-1_16_0.img")
    with open(original, "wb") as f:
        f.truncate(1 << 20)
    builds = os.path.join(scratch, "builds")
    os.makedirs(builds)
    launcher = os.path.join(scratch, "launch217.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
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
            time.sleep(6)                       # the drive list settles
            out = os.path.join(out_dir, "%s_flash_dialog.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, os.path.getsize(out), flush=True)
            webui_shot.api(url, "write.flash_set", "skip_verify", True)
            time.sleep(1)
            out = os.path.join(out_dir,
                               "%s_flash_dialog_skip_ticked.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, os.path.getsize(out), flush=True)
            webui_shot.api(url, "write.flash_close")
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
