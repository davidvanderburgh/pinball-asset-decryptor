"""PAD-1338 proof shots: "Show it with" on a box the game fills (Godzilla's score panel).

    python scripts/shot_pad1338.py <repo> <project> <out_dir> [--after]

<project> is a SCRATCH Godzilla Pro extract with the score panel (9d578751) and a text list read
from the game program (it is edited: Shrink to fit is switched on for the third pair).  Picks
the inactive player-1 username box (player 2 is up on the preview) ("Inactive Player") and takes, under before_/after_:

- scenes_inactive_player.png  the preview and the Selected panel, the box picked.  After: the
                              panel's "Show it with" row lists the game's lines.
- box_closeup.png             the box on the preview, 4x.  After: drawn with PLAYER 1 - LOG IN,
                              as the machine does (running out to the frame).
- box_narrower_shrink.png     the same with the box 20 px narrower (W px), Wrap off and the Font
                              bar's "Shrink the words to fit the box" on (left on the scratch
                              project: clear its scene edits before the next run).

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

SCORE = "/godzilla_pro/assets/lcd/auto_loaded/9d57875196c613785a1eee010c55223a0f1aa821"
WORDS = "PLAYER 1 - LOG IN"


def main():
    repo, project, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad1338-")
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tv = lambda: (state().get("text_scenes") or {}).get("tree_view") or {}  # noqa: E731
    from playwright.sync_api import sync_playwright
    from PIL import Image

    def pick(nid):
        api("text_scenes.tree_select", nid)
        deadline = time.time() + 30
        while time.time() < deadline and (tv().get("props") or {}).get("id") != nid:
            time.sleep(0.5)
        return tv().get("props") or {}

    def full(page, name):
        page.mouse.move(5, 1750)
        time.sleep(3)
        a = page.locator(".tree-canvas").first.bounding_box()
        b = page.locator(".tree-side").first.bounding_box()
        x0, y0 = a["x"] - 12, min(a["y"], b["y"]) - 12
        x1, y1 = b["x"] + b["width"] + 12, max(a["y"] + a["height"], b["y"] + b["height"]) + 12
        page.screenshot(path=out(name), clip={"x": x0, "y": y0, "width": x1 - x0,
                                              "height": y1 - y0})

    def closeup(page, name, nid):
        """The box's frame on the preview, 4x (the selection outline off: another layer
        picked)."""
        view = tv()
        hit = next(h for h in view["hits"] if h["id"] == nid)
        xs, ys = [q[0] for q in hit["pts"]], [q[1] for q in hit["pts"]]
        W, H = view["stage"]
        r = page.locator(".tree-canvas").first.bounding_box()
        sx, sy = r["width"] / W, r["height"] / H
        x0, x1 = r["x"] + (min(xs) - 70) * sx, r["x"] + (max(xs) + 50) * sx
        y0, y1 = r["y"] + (min(ys) - 14) * sy, r["y"] + (max(ys) + 14) * sy
        page.mouse.move(5, 1750)
        time.sleep(3)
        tmp = out(name) + ".tmp.png"
        page.screenshot(path=tmp, clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})
        img = Image.open(tmp)
        img.resize((img.width * 4, img.height * 4), Image.LANCZOS).save(out(name))
        img.close()
        os.remove(tmp)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1800})
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
            api("text_scenes.select", SCORE)
            time.sleep(12)
            page.locator("button", has_text="Hide list").first.click()
            time.sleep(2)
            hits = [h for h in tv().get("hits") or []
                    if h["name"] == "InActivePlayer_Username_Instance"]
            print("username boxes drawn:", [h["id"] for h in hits], flush=True)
            # player 1's box (player 2 is up): the first drawn, under P1_InActiveScore_Instance
            box = hits[0]["id"]
            other = next(h["id"] for h in tv()["hits"] if h["name"] == "score")
            props = pick(box)
            print("box", box, props.get("name"), "try:", props.get("try"), flush=True)
            if after:
                api("text_scenes.tree_try_words", box, WORDS)
                time.sleep(4)
            full(page, "scenes_inactive_player.png")
            pick(other)
            closeup(page, "box_closeup.png", box)
            pick(box)
            # the fix for a long line: the box 20 px narrower than the frame, no wrap, shrink on
            b = props["box"]
            api("text_scenes.tree_set_box", box, b[0], b[1], b[2] - 20, b[3])
            time.sleep(2)
            api("text_scenes.tree_text_flow", box, None, False, True)
            time.sleep(4)
            pick(other)
            closeup(page, "box_narrower_shrink.png", box)
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
