"""PAD-385 proof shots: a scene save with pictures, loaded into a project of another card.

    python scripts/shot_pad385.py <repo> <out_dir> <save.zip> [--after]

Serves <repo> on a light copy of a stock Godzilla LE 1.16 project (PAD312_PROJECT, as
shot_pad312), opens Battle Select in Scenes and loads <save.zip> - a "Save every scene with
pictures" file made in the project of a card BUILT with replaced portraits, so its pictures
are named after the built card's bytes.  Photographs, under the same names before and after:

- load.png      the page as the load finishes (before: the "left out" message)
- scene.png     Battle Select in Scenes after the load (before: the stock portraits)

Needs Playwright (PAD_PWLIB or the user site-packages one) and the installed Edge.
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
import shot_pad312 as base  # noqa: E402


def _project(scratch):
    """The stock project as extracted: no picks, no scene edits, no profiles."""
    dst = os.path.join(scratch, "gzho")
    shutil.copytree(base.SOURCE, dst, ignore=lambda d, names: [
        n for n in names if n in base.SKIP or n.startswith("scene_edits")])
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({}, f)
    return dst


def main():
    repo, out_dir, save = sys.argv[1:4]
    after = "--after" in sys.argv
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad385-")
    project = _project(scratch)
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
            api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            got = []
            t = threading.Thread(target=lambda: got.append(api("text_scenes.edits_load", save)))
            t.start()
            time.sleep(8)
            page.mouse.move(5, 990)
            page.screenshot(path=out("load.png"))
            modal = page.query_selector(".modal")
            if modal:
                print("dialog:", modal.inner_text().replace("\n", " | "), flush=True)
                page.click(".modal .ft button")
            t.join(120)
            print("loaded scenes:", got, flush=True)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(10)
            page.mouse.move(5, 990)
            page.screenshot(path=out("scene.png"))
            picks = sorted((json.load(open(os.path.join(project, ".staged_changes.json"),
                                           encoding="utf-8")).get("image") or {}))
            print("picks after the load:", picks, flush=True)
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
