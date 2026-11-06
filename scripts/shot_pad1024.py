"""PAD-1024 proof shots: an update found while the app runs.

    python scripts/shot_pad1024.py <repo> <out_dir> <prefix>

Serves <repo>'s app (an older tree for the before shots) against a scratch
settings folder, with the release check answering "v9.9.9" and the download
writing a stand-in file slowly into a scratch TEMP, so nothing real is fetched
or installed.  Saves into <out_dir>:

    <prefix>_banner_downloading.png  a few seconds after the check
    <prefix>_banner_installing.png   once the download is done
    <prefix>_banner.png              once the install has had time to finish
    <prefix>_updates_menu.png        Settings > Updates open
    <prefix>_banner_newer_release.png  (PAD-1024 tree only) v9.9.10 released
                                     after v9.9.9 got ready, then Restart to
                                     update pressed

On main the banner offers Install update throughout; with PAD-1024 it shows
the background download, then the background install (standing in for an
installed copy), then Restart to update, and the menu has the "Download and
install updates in the background" switch.
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
from pinball_decryptor.core import updater
SIZE = 4 * 1024 * 1024

NEWER = os.path.join(os.environ["TEMP"], "newer_released")

def fake_check(current_version, repo=None, not_ready_cb=None):
    if os.path.exists(NEWER):
        return ("9.9.10", "https://example.invalid/releases/v9.9.10", "notes", {
            "name": "Pinball_Asset_Decryptor_v9.9.10_Windows.exe",
            "url": "https://example.invalid/setup.exe", "size": SIZE,
            "sha256": None, "kind": "windows-installer"})
    return ("9.9.9", "https://example.invalid/releases/v9.9.9", "notes", {
        "name": "Pinball_Asset_Decryptor_v9.9.9_Windows.exe",
        "url": "https://example.invalid/setup.exe", "size": SIZE,
        "sha256": None, "kind": "windows-installer"})

def fake_download(url, dest, expected_sha256=None, progress_cb=None,
                  cancel_cb=None, opener=None):
    done = 0
    with open(dest, "wb") as f:
        while done < SIZE:
            time.sleep(0.5)
            f.write(b"x" * (SIZE // 20))
            done += SIZE // 20
            if progress_cb:
                progress_cb(done)
    return done

updater.check_for_update = fake_check
updater.download_installer = fake_download
# never install or relaunch anything from a capture
updater.launch_installer_windows = lambda path, shell_execute=None: False
try:
    # blue-green (PAD-1024 part 2): pretend to be an installed copy whose
    # background install takes a few seconds; main has no such module
    import os
    from pinball_decryptor.core import update_slots
    APP = os.path.join(os.environ["TEMP"], "Pinball Asset Decryptor")

    def fake_stage(setup, app, version, run=None, cancel_cb=None):
        time.sleep(8)
        os.makedirs(update_slots.next_dir(app), exist_ok=True)
        return True, []
    update_slots.installed_app_dir = lambda *a, **k: APP
    update_slots.stage_install = fake_stage
    update_slots.staged_install_ok = lambda app, v: False
    update_slots.start_swap = lambda *a, **k: (False, "capture")
except ImportError:
    pass
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo, out_dir, prefix = sys.argv[1:4]
    print("repo:", repo, flush=True)
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1024-")
    tmp = os.path.join(scratch, "temp")
    os.makedirs(tmp)
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch1024.py")
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
            time.sleep(5.0)
            shot = os.path.join(out_dir, prefix + "_banner_downloading.png")
            page.screenshot(path=shot)
            print("shot:", shot, flush=True)
            time.sleep(8.0)
            shot = os.path.join(out_dir, prefix + "_banner_installing.png")
            page.screenshot(path=shot)
            print("shot:", shot, flush=True)
            time.sleep(10.0)
            shot = os.path.join(out_dir, prefix + "_banner.png")
            page.screenshot(path=shot)
            print("shot:", shot, flush=True)
            page.get_by_role("button", name="Settings").first.click()
            time.sleep(1.2)
            page.locator(".menu button.mi", has_text="Updates").first.hover()
            time.sleep(1.2)
            shot = os.path.join(out_dir, prefix + "_updates_menu.png")
            page.screenshot(path=shot)
            print("shot:", shot, flush=True)
            page.keyboard.press("Escape")
            time.sleep(0.5)
            if os.path.isfile(os.path.join(repo, "pinball_decryptor", "core",
                                           "update_slots.py")):
                # v9.9.10 comes out, then Restart to update is pressed
                open(os.path.join(tmp, "newer_released"), "w").close()
                webui_shot.api(url, "ui.banner_action", "update", "install")
                time.sleep(4.0)
                shot = os.path.join(out_dir,
                                    prefix + "_banner_newer_release.png")
                page.screenshot(path=shot)
                print("shot:", shot, flush=True)
            print("temp:", sorted(os.listdir(tmp)), flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
