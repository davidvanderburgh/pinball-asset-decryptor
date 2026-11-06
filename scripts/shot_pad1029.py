"""PAD-1029 proof shot: the update banner while the new version installs in
the background.

    python scripts/shot_pad1029.py <repo> <out_dir> <prefix>

Serves <repo>'s app (an older tree for the before shot) against a scratch
settings folder, with the release check answering "v9.9.9", a stand-in
download, and a stand-in background install that takes ~12 s and reports how
far it is (when <repo>'s stage_install takes a progress_cb).  Nothing real is
fetched or installed.  Saves <prefix>_banner_installing.png halfway through
the install.
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
import os, sys, time
sys.path.insert(0, %r)
from pinball_decryptor.core import updater, update_slots
SIZE = 1024 * 1024

def fake_check(current_version, repo=None, not_ready_cb=None):
    return ("9.9.9", "https://example.invalid/releases/v9.9.9", "notes", {
        "name": "Pinball_Asset_Decryptor_v9.9.9_Windows.exe",
        "url": "https://example.invalid/setup.exe", "size": SIZE,
        "sha256": None, "kind": "windows-installer"})

def fake_download(url, dest, expected_sha256=None, progress_cb=None,
                  cancel_cb=None, opener=None):
    with open(dest, "wb") as f:
        f.write(b"x" * SIZE)
    if progress_cb:
        progress_cb(SIZE)
    return SIZE

updater.check_for_update = fake_check
updater.download_installer = fake_download
updater.launch_installer_windows = lambda path, shell_execute=None: False
APP = os.path.join(os.environ["TEMP"], "Pinball Asset Decryptor")

def fake_stage(setup, app, version, run=None, cancel_cb=None,
               progress_cb=None):
    for i in range(1, 25):
        time.sleep(0.5)
        if progress_cb:
            progress_cb(min(100, i * 4))
    os.makedirs(update_slots.next_dir(app), exist_ok=True)
    return True, []
update_slots.installed_app_dir = lambda *a, **k: APP
update_slots.stage_install = fake_stage
update_slots.staged_install_ok = lambda app, v: False
update_slots.start_swap = lambda *a, **k: (False, "capture")
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo, out_dir, prefix = sys.argv[1:4]
    print("repo:", repo, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1029-")
    tmp = os.path.join(scratch, "temp")
    os.makedirs(tmp)
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch1029.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "theme": "dark",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PAD_UI_NO_UPDATE_CHECK": "", "TEMP": tmp, "TMP": tmp})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            page.wait_for_function(
                "document.body.innerText.includes('installing in the background')",
                timeout=60000)
            time.sleep(6.0)
            shot = os.path.join(out_dir, prefix + "_banner_installing.png")
            page.screenshot(path=shot)
            print("shot:", shot, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
