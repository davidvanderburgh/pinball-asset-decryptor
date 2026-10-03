"""PAD-339 proof shot: the gear menu's "Switched-off files in their own colors" on a fresh
settings file (off by default since PAD-339, so Scenes draws the whole frame through the
Machine screen, an added test card included).

    python scripts/shot_pad339_gear.py <repo> <out_png>
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
    scratch = tempfile.mkdtemp(prefix="pad339g-")
    project = os.path.join(scratch, "proj")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch339g.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    print("serving", repo, flush=True)
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
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
            time.sleep(1.5)
            page.get_by_role("button", name="Settings").first.click()
            time.sleep(1.2)
            item = page.get_by_text("Switched-off files in their own colors").first
            item.hover()
            time.sleep(1.5)
            page.screenshot(path=out_png)
            it = [i for i in webui_shot.state(url)["shell"]["settings_items"]
                  if i.get("id") == "toggle_scenes_own_colours"]
            print("checked:", it and it[0].get("checked"), flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
