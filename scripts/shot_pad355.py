"""PAD-355 proof shot: the Machine screen reaches the user's own pictures whose colour switch
is off, with the gear's "Switched-off files in their own colors" left off.

    python scripts/shot_pad355.py <repo> <godzilla project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one) and picks a copy of KAIJU BATTLE SELECT's background as its replacement, colour switch
off (red).  Opens Scenes on that scene with the Machine screen on its default and snaps the
preview to <out_png>.  Prints the sea's colour from the preview frame, and the same pixel of
the replacement file, so the two can be compared.
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
from shot_pad339_scenes import SCENE, _frame  # noqa: E402

SEA = "images/scene_textures/radimg_Shape_1360x768_254531f8.png"
SPOT = (0.85, 0.15)


def _px(path, spot):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    x, y = int(w * spot[0]), int(h * spot[1])
    px = [im.getpixel((x + dx, y + dy)) for dx in range(-2, 3) for dy in range(-2, 3)]
    return tuple(round(sum(c[i] for c in px) / len(px)) for i in range(3))


def main():
    repo, source, out = sys.argv[1:4]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad355-")
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
            time.sleep(4)
            page.screenshot(path=out)
            frame = _frame(state())
            if frame:
                print("sea in the preview:", _px(frame, SPOT), flush=True)
            print("sea in the file:   ", _px(mine, SPOT), flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
