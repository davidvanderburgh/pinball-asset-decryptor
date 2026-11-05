"""PAD-1012 proof shot: the Jukebox help topic says a song in two pools is not played twice in one game.

    python scripts/shot_pad1012.py <repo> <out.png>

Serves <repo> on an empty scratch project, opens Help on Replace Audio's Jukebox section and shows its
Pools line. Before (main) it says a song wanted in two pools is added to each; after it also says that once
it has played in one pool it is not picked in another in the same game.

Needs Playwright (the user site-packages one) and the installed Edge.
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
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1012-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch1012.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project, "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            page.locator(".sx-help").first.click()
            time.sleep(2)
            page.locator(".sx-tips .hd select").select_option(value="Replace Audio")
            time.sleep(1.5)
            page.locator(".sx-tips").get_by_text("Jukebox", exact=True).first.click()
            time.sleep(1)
            line = page.locator(".sx-tips").get_by_text("wanted in two pools", exact=False).first
            line.scroll_into_view_if_needed()
            page.evaluate("(el) => el.scrollIntoView({block: 'center'})", line.element_handle())
            time.sleep(1)
            print("line:", line.text_content(), flush=True)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
