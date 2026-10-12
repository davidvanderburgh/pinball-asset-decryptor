"""PAD-552 proof shots: a file of scene edits saved from the project of a card built with
changes (DragonRR's 70th_BETA_1.zip, from his own built card) loaded into a project of the
stock card.

    python scripts/shot_pad552.py <repo> <out_dir> <file.zip> [--after] [--leftovers <dir>]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  The page loads <file.zip> into a stock copy of shot_pad312's Godzilla project
and photographs, under the same name before and after:

- scenes_load_dialog.png  the message Load scene edits from a file shows when it is done
- scenes_leftovers.png    with --leftovers: the battle scene after the load, in a project folder
                          that still holds the radimg_*.png pictures of <dir> (an earlier
                          extraction of his built card into the same folder)

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
import shot_pad502  # noqa: E402


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    share = os.path.abspath(sys.argv[3])
    after = "--after" in sys.argv
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad552-")
    project = shot_pad502._project(scratch, "gzho")
    leftovers = (sys.argv[sys.argv.index("--leftovers") + 1] if "--leftovers" in sys.argv
                 else None)
    if leftovers:
        tex = os.path.join(project, "images", "scene_textures")
        for name in os.listdir(leftovers):
            if name.startswith("radimg_") and not os.path.exists(os.path.join(tex, name)):
                shutil.copy(os.path.join(leftovers, name), tex)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.removeItem('pad.fontbar.open'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            time.sleep(8)
            t = threading.Thread(target=api, args=("text_scenes.edits_load", share), daemon=True)
            t.start()
            modal = None
            for _ in range(240):
                modal = page.query_selector(".modal")
                if modal or not t.is_alive():
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            modal = page.query_selector(".modal")
            if modal:
                print("dialog:", modal.inner_text().replace("\n", " | "), flush=True)
                if not leftovers:
                    page.screenshot(path=out("scenes_load_dialog.png"))
                btn = page.query_selector('.modal .ft button:has-text("OK")')
                if btn:
                    btn.click()
            else:
                print("no dialog", flush=True)
            t.join(120)
            if leftovers:
                time.sleep(10)
                page.mouse.move(5, 990)
                page.screenshot(path=out("scenes_leftovers.png"))
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
