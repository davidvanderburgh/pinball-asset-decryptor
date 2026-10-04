"""PAD-370 proof shots: the rainbow Colors tab's words, and filled color palettes.

    python scripts/shot_pad370.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project (one Battle Select portrait and one
clip replaced, both with the color profile attached) and photographs, under the same names
before and after, at twice the size so the small icons can be read:

- images_palettes.png   the Images tab's Color column (green and red palettes) and the
                        rainbow Colors tab on the page's right edge
- video_palettes.png    the same on the Video tab
- scenes_palettes.png   Battle Select in Scenes: the layer list's palettes and the tab

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
import shot_pad312 as base  # noqa: E402
import shot_pad360 as saved  # noqa: E402


def _right_side(page, path, width=760):
    """The right part of the page: the Color column / layer list and the rainbow tab."""
    page.mouse.move(5, 990)
    time.sleep(0.5)
    page.screenshot(path=path, clip={"x": 1600 - width, "y": 60, "width": width, "height": 700})


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad370-")
    project = base._project(scratch)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    data["image_color_slots"] = {base.PORTRAIT: True}
    data["video_color_slots"] = {base.VIDEO: True}
    data["image_color_unlocked"] = True
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    with open(os.path.join(folder, "Godzilla LE.txt"), "w", encoding="utf-8") as f:
        f.write(saved.GODZILLA)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000},
                                    device_scale_factor=2)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.removeItem('pad.colorbar.open.images');"
                " localStorage.removeItem('pad.colorbar.open.video');"
                " localStorage.removeItem('pad.colorbar.open.scenes'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.set", "images", "search", "530x726")
            time.sleep(2)
            api("images.select", base.PORTRAIT)
            time.sleep(2)
            _right_side(page, out("images_palettes.png"))
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video")
            time.sleep(2)
            _right_side(page, out("video_palettes.png"))
            api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            tv = (state().get("text_scenes") or {}).get("tree_view") or {}
            print("layers with a color:", sum(1 for l in tv.get("layers") or [] if l.get("color")),
                  flush=True)
            _right_side(page, out("scenes_palettes.png"), width=900)
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
