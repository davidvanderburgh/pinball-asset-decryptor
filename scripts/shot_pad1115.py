"""PAD-1115 proof shots: the Video tab's Length cell flags a clip a game screen shows for a fixed time (the game's
time, amber when the clip freezes on its last frame or is cut), before and after.

    python scripts/shot_pad1115.py <repo> <out_png> <project> <search> <row clip> [hover]

Serves <repo> on <project> (a video extract of a Stern card, its .extract_source.json naming the card), opens the
Video tab, types <search> in Search, selects the row whose file is <row clip> and, with ``hover``, hovers that row's
screen-time tag so its words show. Needs Playwright (the user site-packages one) and the installed Edge.
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
    repo, out_png, project, search, row = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                                           os.path.abspath(sys.argv[3]), sys.argv[4], sys.argv[5])
    hover = len(sys.argv) > 6 and sys.argv[6] == "hover"
    with open(os.path.join(project, ".extract_source.json"), encoding="utf-8") as f:
        card = json.load(f)["input_path"]
    scratch = tempfile.mkdtemp(prefix="pad1115-")
    launcher = os.path.join(scratch, "launch1115.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 820})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(15)                      # the scan, its probe pass and the game program's screens
            box = page.get_by_placeholder("Search").first
            box.fill(search)
            time.sleep(3)
            page.locator(".vid-name", has_text=row).first.click()
            time.sleep(4)
            if hover and page.locator(".vid-scr").count():
                cell = page.locator("tr:has-text('%s') .vid-scr" % row).first
                if not cell.count():
                    cell = page.locator(".vid-scr").first
                cell.hover()
                time.sleep(1.5)
            else:
                page.mouse.move(5, 815)
                time.sleep(1)
            page.screenshot(path=out_png)
            browser.close()
        print("shot", out_png, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
