"""PAD-981 proof shot: a Battle Select laid out before v1.301 over its pictures' own size.

    python scripts/shot_pad981.py <repo> <project> <out_dir> [--after]

The project is a one-scene extract of Godzilla LE 1.16's Kaiju Battle Select (``cac32730...``)
with the Heisei V2.1 card's pictures (grid 544x840, portraits 632x828, at their own size)
and a ``scene_edits.json`` written before PAD-865 (no ``_fit``) holding the moves that centred
them.  One shot, ``before_``/``after_scenes.png``: the Scenes tab on that scene.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

SCENE = "/godzilla_le/assets/lcd/auto_loaded/cac32730af42b9d26d26c4bb6e667b07da53113e"


def main():
    repo, source, out_dir = sys.argv[1:4]
    pre = "after_" if "--after" in sys.argv else "before_"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad981-")
    project = os.path.join(scratch, "gz")
    shutil.copytree(source, project)
    print("serving", repo, "project", project, flush=True)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    scenes = lambda: state().get("text_scenes") or {}        # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "scenes")
            time.sleep(3)
            api("text_scenes.select", SCENE)
            rig._wait(lambda: not scenes().get("rebuilding"), 600)
            rig._wait(lambda: scenes().get("tree_view") and scenes().get("frames"), 120)
            rig._wait(lambda: not scenes().get("tree_busy"), 60)
            time.sleep(4)
            page.screenshot(path=os.path.join(out_dir, pre + "scenes.png"))
            print("errors:", errors, flush=True)
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
