"""PAD-1279 round 2 proof shots: the Test card as a tab of its own.

    python scripts/shot_pad1279_testcard.py <repo to run> <out dir> <project> <list.json>

Runs the app's server from <repo> against a scratch settings folder whose Stern project is
<project>, with <list.json> as the test card list, and photographs (each skipped where the
repo has no such screen - a BEFORE run from main has no Test card tab):
  menu.png      Multi-boot > Menu settings (main: a Test pictures list; now: none)
  testcard.png  the Test card tab
  scenes.png    the Scenes tab's scene list (now: a Test column)
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

W, H = 1500, 1000


def main():
    repo, out, project, listing = (os.path.abspath(a) for a in sys.argv[1:5])
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1279b-")
    cfg = os.path.join(scratch, "cfg", "pinball_decryptor")
    os.makedirs(cfg, exist_ok=True)
    shutil.copyfile(listing, os.path.join(cfg, "testcard.json"))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"write_assets": project, "extract_output": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, extra_env={"PYTHONPATH": repo + os.pathsep + site.getusersitepackages(),
                                      "PAD_UI_NO_RIG": "1"},
        app_cmd=[sys.executable, "-c", "import sys; sys.path.insert(0, %r); "
                 "from pinball_decryptor.webui import host; sys.exit(host.main(sys.argv[1:]))" % repo])
    print("repo", repo, "url", url, flush=True)
    from playwright.sync_api import sync_playwright
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": W, "height": H})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            tabs = webui_shot.state(url).get("shell", {}).get("tabs") or []
            have = {t.get("ns") for t in tabs if isinstance(t, dict)} if tabs else None

            # Multi-boot > Menu settings
            webui_shot.api(url, "ui.select_tab", "multiboot")
            time.sleep(4)
            webui_shot.api(url, "multiboot.menu_settings")
            time.sleep(3)
            dlg = page.locator(".mb-dlg-menu")
            (dlg.first if dlg.count() else page).screenshot(path=os.path.join(out, "menu.png"))
            webui_shot.api(url, "multiboot.menu_cancel")
            time.sleep(1)

            # the Test card tab
            try:
                webui_shot.api(url, "ui.select_tab", "testcard")
                time.sleep(3)
                page.screenshot(path=os.path.join(out, "testcard.png"), full_page=True)
            except Exception as exc:                            # noqa: BLE001
                print("no Test card tab here:", exc, flush=True)

            # the Scenes tab's list
            webui_shot.api(url, "ui.select_tab", "scenes")
            time.sleep(6)
            lst = page.locator(".scenes-left")
            (lst.first if lst.count() else page).screenshot(path=os.path.join(out, "scenes.png"))
            browser.close()
        print("tabs:", sorted(have) if have else "?", flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
