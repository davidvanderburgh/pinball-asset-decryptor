"""PAD-383 round 3 proof shot: dragging a text's corner handle resizes its box, not its words.

    python scripts/shot_pad383_box.py <repo> <godzilla project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes on the jackpot-meter scene (its title "GODZILLA & ANGUIRIS VS KING
GHIDORAH & GIGAN" in a 1200 px box), selects the title, drags the box's bottom-right handle
to make it about 520 px narrower and 60 px taller, and snaps the page once the redraw is in.
Prints the line's X, Y, W, H and Size % before and after.
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
from shot_pad383 import SCENE, LINE  # noqa: E402


def main():
    repo, source, out = sys.argv[1:4]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad383b-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright
    print("repo", repo, flush=True)
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
            layers = state()["tree_view"]["layers"]
            node = [l for l in layers if l["name"] == LINE][-1]["id"]
            api("text_scenes.tree_select", node)
            time.sleep(1)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            tv = state()["tree_view"]
            pr = tv["props"]
            print("before:", pr["x"], pr["y"], pr["w"], pr["h"], "size", pr["scale"], flush=True)
            W, H = tv["stage"][0], tv["stage"][1]
            c = page.locator(".tree-canvas").bounding_box()
            to = lambda x, y: (c["x"] + x * c["width"] / W, c["y"] + y * c["height"] / H)  # noqa: E731
            x0, y0 = to(pr["x"] + pr["w"], pr["y"] + pr["h"])
            x1, y1 = to(pr["x"] + pr["w"] - 520, pr["y"] + pr["h"] + 60)
            page.mouse.move(x0, y0)
            page.mouse.down()
            for i in range(1, 11):
                page.mouse.move(x0 + (x1 - x0) * i / 10, y0 + (y1 - y0) * i / 10)
                time.sleep(0.03)
            page.mouse.up()
            time.sleep(1.5)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            pr = state()["tree_view"]["props"]
            print("after:", pr["x"], pr["y"], pr["w"], pr["h"], "size", pr["scale"], flush=True)
            page.mouse.move(5, 995)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
