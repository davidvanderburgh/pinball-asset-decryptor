"""PAD-387 proof shots: a whole-look save (pictures and text) loaded into a stock project.

    python scripts/shot_pad387.py <repo> <out_dir> <save.zip> [--after]

Serves <repo> on a light copy of a stock Godzilla LE 1.16 project (shot_pad385's), opens
Battle Select in Scenes and loads <save.zip>, a "Save every scene with pictures, text and color
profiles" file made in the project of a card built with other words and pictures.
Photographs, under the same names before and after:

- menu.png      the Save / load edits menu
- load.png      the page as the load finishes (its message, when it has one)
- battle.png    Battle Select after the load
- title.png     a battle title scene after the load

Needs Playwright (PAD_PWLIB or the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad385 as p385  # noqa: E402

TITLE = ("/godzilla_le/assets/lcd/auto_loaded/99cd5ccc01720c43f3d3bc1ccecd9cb40ae3f7e4/"
         "8c7375ac48347abb7177bdff15a7f106554e086c")


def main():
    repo, out_dir, save = sys.argv[1:4]
    after = "--after" in sys.argv
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad387-")
    project = p385._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "text")
            time.sleep(2)
            base._wait_scan(state, "images")
            base._wait_scan(state, "text")
            api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            time.sleep(8)
            page.click("text=Save / load edits")
            time.sleep(1)
            page.screenshot(path=out("menu.png"))
            page.keyboard.press("Escape")
            time.sleep(0.5)
            got = []
            t = threading.Thread(target=lambda: got.append(api("text_scenes.edits_load", save)))
            t.start()
            time.sleep(8)
            for _ in range(4):
                modal = page.query_selector(".modal")
                if not modal:
                    break
                print("dialog:", modal.inner_text().replace("\n", " | "), flush=True)
                page.mouse.move(5, 990)
                page.screenshot(path=out("load.png"))
                page.click(".modal .ft button")
                time.sleep(4)
            t.join(120)
            print("loaded scenes:", got, flush=True)
            print("caption:", (state().get("text_scenes") or {}).get("caption"), flush=True)
            for name, scene in (("battle.png", base.BATTLE), ("title.png", TITLE)):
                api("text_scenes.select", scene)
                time.sleep(8)
                page.mouse.move(5, 990)
                page.screenshot(path=out(name))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
