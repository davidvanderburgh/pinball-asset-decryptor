"""PAD-401 proof shots: a modder's whole-look save loaded into the project of their built card.

    python scripts/shot_pad401.py <repo> <out_dir> <save.zip> <built text dir> [--after]

Serves <repo> on a light copy of the Godzilla LE project shot_pad312 uses, with its text/
replaced by <built text dir> (the text/ of a project extracted from the card built from the
file, whose program lines already read the new words), opens Scenes and loads <save.zip>.
Photographs, under the same names before and after:

- load.png      the message the load ends with

Needs Playwright (PAD_PWLIB or the user site-packages one) and the installed Edge.
"""
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
import shot_pad385 as p385  # noqa: E402


def main():
    repo, out_dir, save, text_dir = sys.argv[1:5]
    after = "--after" in sys.argv
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad401-")
    project = p385._project(scratch)
    shutil.rmtree(os.path.join(project, "text"), ignore_errors=True)
    shutil.copytree(text_dir, os.path.join(project, "text"))
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
            got = []
            t = threading.Thread(target=lambda: got.append(api("text_scenes.edits_load", save)))
            t.start()
            time.sleep(10)
            for _ in range(4):
                modal = page.query_selector(".modal")
                if not modal:
                    break
                print("dialog:", modal.inner_text().replace("\n", " | "), flush=True)
                page.mouse.move(5, 990)
                page.screenshot(path=out("load.png"))
                page.click(".modal .ft button")
                time.sleep(4)
            t.join(180)
            print("loaded scenes:", got, flush=True)
            print("caption:", (state().get("text_scenes") or {}).get("caption_full"), flush=True)
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
