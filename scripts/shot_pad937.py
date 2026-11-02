"""PAD-937 proof shots: Settings > Updates on an AppImage, where the Old
versions choices were added.

    python scripts/shot_pad937.py <repo> <out_png> [--pick]

Serves <repo>'s app (it may be an older tree, for the before shot) against a
scratch settings folder with APPIMAGE pointing at a stand-in AppImage beside
three older ones, so the page draws what a Linux AppImage user sees.  With
--pick it then clicks "Delete them" and prints what is left in the folder.
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
    repo, out_png = sys.argv[1:3]
    pick = "--pick" in sys.argv[3:]
    print("repo:", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad937-")
    sys.path.insert(0, repo)
    from pinball_decryptor import __version__
    apps = os.path.join(scratch, "Apps")
    os.makedirs(apps)
    name = "Pinball_Asset_Decryptor_v%s_Linux_x86_64.AppImage"
    for v in ("1.290.0", "1.305.4", "1.312.0", __version__):
        with open(os.path.join(apps, name % v), "wb") as f:
            f.write(b"x")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch937.py")
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
                   "APPIMAGE": os.path.join(apps, name % __version__)})
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
            time.sleep(2.0)
            page.get_by_role("button", name="Settings").first.click()
            time.sleep(1.2)
            page.locator(".menu button.mi", has_text="Updates").first.hover()
            time.sleep(1.2)
            page.screenshot(path=out_png)
            print("shot:", out_png, flush=True)
            if pick:
                webui_shot.api(url, "ui.settings_action", "old_versions", 0)
                time.sleep(2.0)
                print("left in Apps:", sorted(os.listdir(apps)), flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
