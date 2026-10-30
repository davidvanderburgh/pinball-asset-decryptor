"""PAD-865 proof shots: a picture kept at its own size, in the original's place.

    python scripts/shot_pad865.py <repo> <one-scene project> <out_dir> [--after]

The project is a one-scene extract of Godzilla LE 1.16's in-game Tokyo map
(``34856963...``).  Both tank icon pictures (147x105 on the screen) get a 588x420 test
card with Keep size ticked (DragonRR's case: a bigger, sharper picture), and two shots are
taken as ``before_``/``after_<screen>.png``:

- ``scenes``: the Scenes tab on the map, the tank icon's layer picked;
- ``images_keep``: the Images tab's preview of the tank icon and its Keep size line.

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
import shot_pad251_tab as rig  # noqa: E402
import shot_pad312 as base  # noqa: E402

SCENE = "/godzilla_le/assets/lcd/auto_loaded/34856963ab6044d7ca3e1d26b71f70996b2b3ca1"
RELS = ("images/scene_textures/radimg_150x106_248bb540.png",
        "images/scene_textures/radimg_unnamed_instance_77_150x106_88c4b927.png")


def _card(path, w=588, h=420):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    d = ImageDraw.Draw(im)
    cols = [(220, 30, 30), (30, 200, 60), (40, 90, 230), (230, 200, 30)]
    for i, (x, y) in enumerate([(0, 0), (w // 2, 0), (0, h // 2), (w // 2, h // 2)]):
        d.rectangle([x, y, x + w // 2 - 1, y + h // 2 - 1], fill=cols[i] + (255,))
    f = ImageFont.truetype("arialbd.ttf", h // 5)
    for t, (x, y) in zip(["TL", "TR", "BL", "BR"], [(w // 8, h // 10), (5 * w // 8, h // 10),
                                                    (w // 8, 6 * h // 10),
                                                    (5 * w // 8, 6 * h // 10)]):
        d.text((x, y), t, font=f, fill=(255, 255, 255, 255))
    d.rectangle([0, 0, w - 1, h - 1], outline=(255, 255, 255, 255), width=w // 60)
    im.save(path)


def _project(scratch, source):
    project = os.path.join(scratch, "gz")
    shutil.copytree(source, project)
    mine = os.path.join(scratch, "Tank icon 588x420.png")
    _card(mine)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"image": {r: mine for r in RELS}, "image_keep_size": list(RELS),
                   "image_change_filter": "All", "image_source_filter": "All sources"}, f)
    return project


def main():
    repo, source, out_dir = sys.argv[1:4]
    pre = "after_" if "--after" in sys.argv else "before_"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad865-")
    project = _project(scratch, source)
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
            time.sleep(2)
            tv = scenes().get("tree_view") or {}
            layer = next((l for l in tv.get("layers") or ()
                          if l["name"] == "IconTanks_Instance"), None)
            if layer is not None:
                api("text_scenes.tree_select", layer["id"])
                rig._wait(lambda: not scenes().get("tree_busy"), 60)
            time.sleep(3)
            page.screenshot(path=os.path.join(out_dir, pre + "scenes.png"))
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.set", "images", "search", "150x106_248bb540")
            time.sleep(2.5)
            page.locator(".img-tbl .tr:has-text('248bb540')").first.click()
            time.sleep(3)
            print("keep row:", (state().get("images") or {}).get("preview", {}).get("keep"),
                  flush=True)
            page.screenshot(path=os.path.join(out_dir, pre + "images_keep.png"))
            print("errors:", errors, flush=True)
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
