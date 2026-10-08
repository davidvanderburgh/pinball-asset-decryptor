"""PAD-447 proof shot: a click on a picture or a line of text whose mouse jiggles a pixel or
two picks it without moving it.

    python scripts/shot_pad447.py <repo> <godzilla project> <out_png> [--drag]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes on the jackpot-meter scene, and clicks the biggest picture and then the
title line the way a hand does: down, a jiggle of 2 to 4 screen px while the button is held,
up.  Prints each layer's X and Y before and after and the edits the clicks left in
scene_edits.json (none, once a click is a click), then snaps the page.  --drag also drags
the title 60 px to the right, which must still move it.
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
from shot_pad383 import SCENE, LINE  # noqa: E402

# what a hand does with the button held: screen px from where it went down
JIGGLE = [(1, 0), (2, 1), (3, 2), (2, 3), (3, 2)]


def _ops(project):
    p = os.path.join(project, "images", "scene_textures", "scene_edits.json")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for v in data.values():
        out.extend(v if isinstance(v, list) else v.get("ops", []) if isinstance(v, dict) else [])
    return out


def _area(pts):
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1]
                   for i in range(len(pts)))) / 2


def main():
    repo, source, out = sys.argv[1:4]
    drag = "--drag" in sys.argv[4:]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad447-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json", "scene_edits_carried.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    settle = lambda: (time.sleep(1.2), rig._wait(lambda: not state().get("tree_busy"), 60))  # noqa: E731
    from playwright.sync_api import sync_playwright
    print("repo", repo, flush=True)
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
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state().get("alive"), 30)
            assert api("text_scenes.select", SCENE)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            tv = state()["tree_view"]
            W, H = tv["stage"][0], tv["stage"][1]
            c = page.locator(".tree-canvas").bounding_box()
            to = lambda x, y: (c["x"] + x * c["width"] / W, c["y"] + y * c["height"] / H)  # noqa: E731
            print("stage %dx%d drawn %dx%d px: 1 screen px = %.2f stage px"
                  % (W, H, c["width"], c["height"], W / c["width"]), flush=True)
            layers = tv["layers"]
            title = [l for l in layers if l["name"] == LINE][-1]["id"]
            pics = [h for h in tv["hits"] if h["kind"] != "Text" and h["id"] != title]
            pic = max(pics, key=lambda h: _area(h["pts"]))

            def where(nid):
                api("text_scenes.tree_select", nid)
                settle()
                pr = state()["tree_view"]["props"]
                return pr["x"], pr["y"]

            def click(nid, at):
                api("text_scenes.tree_select", None)
                settle()
                x0, y0 = to(*at)
                page.mouse.move(x0, y0)
                page.mouse.down()
                for dx, dy in JIGGLE:
                    page.mouse.move(x0 + dx, y0 + dy)
                    time.sleep(0.02)
                page.mouse.up()
                settle()

            for nid, name, at in (
                    (pic["id"], "picture %r" % pic["name"],
                     (sum(q[0] for q in pic["pts"]) / len(pic["pts"]),
                      sum(q[1] for q in pic["pts"]) / len(pic["pts"]))),
                    (title, "title line", None)):
                x, y = where(nid)
                if at is None:
                    pr = state()["tree_view"]["props"]
                    at = (pr["x"] + pr["w"] / 2, pr["y"] + pr["h"] / 2)
                click(nid, at)
                nx, ny = where(nid)
                print("%s: before (%s, %s) after a jiggly click (%s, %s): %s"
                      % (name, x, y, nx, ny, "MOVED" if (x, y) != (nx, ny) else "stayed put"),
                      flush=True)
            if drag:
                pr = state()["tree_view"]["props"]
                x0, y0 = to(pr["x"] + pr["w"] / 2, pr["y"] + pr["h"] / 2)
                x1 = x0 + 60 * c["width"] / W
                page.mouse.move(x0, y0)
                page.mouse.down()
                for i in range(1, 11):
                    page.mouse.move(x0 + (x1 - x0) * i / 10, y0)
                    time.sleep(0.03)
                page.mouse.up()
                settle()
                nx, ny = where(title)
                print("title dragged 60 stage px right: now (%s, %s)" % (nx, ny), flush=True)
            # the title stays picked for the shot: its X / Y are in the inspector
            api("text_scenes.tree_select", title)
            settle()
            row = [r for r in state().get("scenes", []) if r.get("d") == SCENE]
            print("scene state:", [r.get("state") for r in row] or "?", flush=True)
            print("edits left by the clicks:", json.dumps(_ops(project)), flush=True)
            print("page errors:", errors, flush=True)
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
