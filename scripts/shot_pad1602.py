"""PAD-1602 proof shot: the Load modes dialog's backup line.

    python scripts/shot_pad1602.py <repo> <out_dir>

Serves <repo> (the ticket branch, or a ``git archive`` of main for the
"before" shot) on a scratch settings folder and a scratch project, has the
Modes tab's Load from a file... find two modes of the file named like two of
the project's (the conflict list is stubbed, nothing is loaded), and shoots
the conflicts dialog it opens: ``<out_dir>/<prefix>_load_dialog.png``
(``PAD_SHOT_PREFIX``, default ``shot``).  The dialog is then cancelled.
Needs Playwright (PAD_PWLIB or the user site) and Edge.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import os, sys
sys.path.insert(0, %(repo)r)
PROJECT = %(project)r
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.webui.tabs import modes as MT
from pinball_decryptor.webui import host
MT.ModesTab.project = lambda self: PROJECT
MT.ModesTab._save_if_edited = lambda self: None
MP.share_conflicts = lambda path, project: ([
    {"slug": "kaiju_rush", "file": "Kaiju Rush", "here": "Kaiju Rush",
     "changed": "2026-11-24 21:10", "saved": "2026-11-20 18:02"},
    {"slug": "mecha_frenzy", "file": "Mecha Frenzy", "here": "Mecha Frenzy",
     "changed": "2026-11-23 09:41", "saved": "2026-11-20 18:02"}], [])
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = os.environ.get("PAD_SHOT_PREFIX", "shot")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1602-")
    project = os.path.join(scratch, "GZ 1.16 Premium Extract")
    os.makedirs(project)
    friend = os.path.join(scratch, "Friend's modes.zip")
    launcher = os.path.join(scratch, "launch1602.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo, "project": project})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
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
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(1.5)
            t = threading.Thread(target=lambda: webui_shot.api(
                url, "modes.load_file", friend), daemon=True)
            t.start()
            page.get_by_text("Replace ticked only").wait_for(timeout=30000)
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir,
                                              prefix + "_load_dialog.png"))
            page.get_by_role("button", name="Cancel", exact=True).last.click()
            t.join(20)
            print("shots in", out_dir, flush=True)
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
