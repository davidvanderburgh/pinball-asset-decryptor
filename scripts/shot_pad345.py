"""PAD-345 proof shot: unticking the Scenes "Unlock the game's own pictures" box puts back
a game picture a build corrected, when the Images tab has not scanned the folder.

    python scripts/shot_pad345.py <repo> <out_png>

Serves <repo> on a settings copy whose Stern project is a scratch copy of the Godzilla
project (shot_pad312's).  Before the app starts, the project is left the way a build with
Battle Select's background switched on leaves it: the box ticked, the background's switch
on, its pristine bytes in .orig/ and the project's file corrected with the individual files
profile.  The Scenes window is opened from the Text tab (the Images tab never scans), the
box is unticked, and the Scenes window is photographed.  The background should be back in
its own colours.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

BACKGROUND = "images/scene_textures/radimg_Shape_1360x768_254531f8.png"


def _built(project, repo):
    """The project as a build with the background switched on leaves it."""
    sys.path.insert(0, repo)
    from PIL import Image
    from pinball_decryptor.core import colour_profile as cp, staged_changes, staged_originals
    staged_originals.snapshot(project, BACKGROUND, None)
    path = os.path.join(project, *BACKGROUND.split("/"))
    cp.asset_profile(project).apply_image(Image.open(path)).save(path)
    data = staged_changes.load(project)
    data[cp.STOCK_IMAGES_KEY] = True
    data[cp.IMAGE_SLOTS_KEY] = {BACKGROUND: True}
    staged_changes.save(project, data)


def main():
    repo, out_png = sys.argv[1:3]
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad345-")
    project = base._project(scratch)
    _built(project, repo)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "text")
            time.sleep(2)
            base._wait_scan(state, "text")
            opts = (state().get("text") or {}).get("scene_options") or []
            api("text.set_scene", next(o for o in opts if o.startswith("cac32")))
            time.sleep(2)
            view = (state().get("text") or {}).get("view") or []
            assert api("text.show_in_scene", view[0])
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            print("images tab folder:", repr((state().get("images") or {}).get("dir")))
            print("untick:", api("text_scenes.tree_color_unlocked", False), flush=True)
            time.sleep(6)
            page.screenshot(path=out_png)
            print("project file matches .orig gone:",
                  not os.path.exists(os.path.join(project, ".orig", *BACKGROUND.split("/"))))
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
