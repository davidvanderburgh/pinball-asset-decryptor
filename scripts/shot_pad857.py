"""PAD-857 proof shot: Keep size on a picture the game draws as a fixed fill.

    python scripts/shot_pad857.py <repo> <one-scene project> <out_dir> [--after]

The project is a one-scene extract of Godzilla's Kaiju Battle Select scene
(``cac32730...``): its full-screen overlay ``radimg_Shape_1360x768_2838c52d.png`` is
drawn by three Shapes at a fixed 1360x768.  A copy of it gets a 6573x3712 replacement
with Keep size ticked (DragonRR's case), and the Images tab's preview is photographed
as ``before_``/``after_images_keep.png``.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad360 as saved  # noqa: E402

REL = "images/scene_textures/radimg_Shape_1360x768_2838c52d.png"


def _project(scratch, source):
    project = os.path.join(scratch, "proj")
    shutil.copytree(source, project)
    from PIL import Image, ImageDraw
    big = Image.new("RGBA", (6573, 3712), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    for i in range(0, 220, 20):
        d.rectangle([i, i, 6572 - i, 3711 - i], outline=(40, 220, 90, 255), width=8)
    mine = os.path.join(scratch, "Retro Alien Monitor QHD - V2.png")
    big.save(mine)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"image": {REL: mine}, "image_keep_size": [REL],
                   "image_change_filter": "All", "image_source_filter": "All sources"}, f)
    return project


def main():
    repo, source, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad857-")
    project = _project(scratch, source)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    name = ("after_" if after else "before_") + "images_keep.png"
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
            api("ui.set", "images", "search", "Shape_1360")
            time.sleep(2.5)
            page.locator(".img-tbl .tr:has-text('2838c52d')").first.click()
            time.sleep(3)
            keep = (state().get("images") or {}).get("preview", {}).get("keep")
            print("keep row:", keep, flush=True)
            page.screenshot(path=os.path.join(out_dir, name))
            print("errors:", errors, flush=True)
            browser.close()
    finally:
        webui_shot.stop_server(proc) if hasattr(webui_shot, "stop_server") else proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
