"""PAD-355 round 2 proof shots: the colour switch is worded as a color profile attached to
the file (or not), in the Scenes Layers tooltip and the gear menu.

    python scripts/shot_pad355_words.py <repo> <godzilla project> <out_dir> <before|after>

Same scratch set-up as shot_pad355.py (KAIJU BATTLE SELECT's background replaced, its
switch red).  Snaps <out_dir>/<tag>_layers_tip.png with the red switch's tooltip open, then
<out_dir>/<tag>_gear_menu.png with the gear menu's setting hovered.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402
from shot_pad339_scenes import SCENE  # noqa: E402
from shot_pad355 import SEA  # noqa: E402


def main():
    repo, source, out, tag = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad355w-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    mine = os.path.join(scratch, "my_sea.png")
    shutil.copy(os.path.join(project, *SEA.split("/")), mine)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"image": {SEA: mine}}, f)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state().get("alive"), 30)
            assert api("text_scenes.select", SCENE)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            time.sleep(3)
            page.locator("button.ly-color.off").first.hover()
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out, tag + "_layers_tip.png"))
            page.mouse.move(5, 500)
            time.sleep(0.5)
            page.get_by_role("button", name="Settings").first.click()
            time.sleep(1.2)
            box = page.get_by_text(
                re.compile(r"own colors|color profile attached")).first.bounding_box()
            page.mouse.move(box["x"] + box["width"] - 10, box["y"] + box["height"] / 2)
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out, tag + "_gear_menu.png"))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
