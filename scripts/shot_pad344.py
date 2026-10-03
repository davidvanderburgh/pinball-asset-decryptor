"""PAD-344 proof shot: the Scenes Layers list's Color switches on the game's own pictures.

    python scripts/shot_pad344.py <repo> <out_png> [--after]

Serves <repo> on a settings copy whose Stern project is a scratch copy of the Godzilla
project (shot_pad312's), puts the Color profile tab on the individual files mode, opens
the Scenes window on Battle Select and photographs the Layers list.  With --after the
Layers list's advanced "Unlock the game's own pictures" box is ticked and the first two
game pictures are switched on, so the pair shows blue locks against green/red palettes.

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


def _colors(state):
    tv = (state().get("text_scenes") or {}).get("tree_view") or {}
    return [(l["id"], l["name"], l.get("color")) for l in tv.get("layers") or []
            if l.get("color")]


def main():
    repo, out_png = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad344-")
    project = base._project(scratch)
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
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "assets")
            time.sleep(1)
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            if after:
                print("unlock:", api("text_scenes.tree_color_unlocked", True), flush=True)
                time.sleep(2)
                stock = [i for i, _n, c in _colors(state) if c.get("stock")]
                for nid in stock[:2]:
                    print("switch", nid, api("text_scenes.tree_color", nid, True), flush=True)
                time.sleep(4)
            for row in _colors(state):
                print("layer", row, flush=True)
            page.screenshot(path=out_png)
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
