"""PAD-1024 proof shots: an update found while the app runs.

    python scripts/shot_pad1024.py <repo> <out_dir> <prefix>

Serves <repo>'s app (an older tree for the before shots) against a scratch
settings folder, with the release check answering "v9.9.9" and the download
writing a stand-in file slowly into a scratch TEMP, so nothing real is fetched
or installed.  Saves into <out_dir>:

    <prefix>_banner_downloading.png  a few seconds after the check
    <prefix>_banner.png              once the download has had time to finish
    <prefix>_updates_menu.png        Settings > Updates open

On main the banner offers Install update throughout; with PAD-1024 it shows
the background download, then Restart to update, and the menu has the
"Download updates in the background" switch.
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
import sys, time
sys.path.insert(0, %r)
from pinball_decryptor.core import updater
SIZE = 4 * 1024 * 1024

def fake_check(current_version, repo=None, not_ready_cb=None):
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
            time.sleep(12.0)
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
