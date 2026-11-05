"""PAD-1014 proof shots: snapping in the Scenes editor.

    python scripts/shot_pad1014.py <repo> <project> <out_dir> [--after]

The project is any Spike 2 extract with scenes (copied to a scratch folder first).  Two shots,
``before_``/``after_<screen>.png``:

* ``scenes_snap``: the preview's bar under it, with the Snap menu open (after).
* ``scenes_drag``: a picture held mid-drag a few pixels off another one's left edge; with
  snapping on (after) it has jumped onto that edge, the guide line drawn and the grid shown.

``--resize`` then drags the part's bottom-right corner to 3 px past b's top edge and prints
where its edges landed (the corner snaps onto the nearest part line, across or down).

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

SNAP = {"grid": True, "size": 20, "objects": True, "handle": "tl"}


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _inside(pts, x, y):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        (xi, yi), (xj, yj) = pts[i], pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _pair(hits, W, H):
    """Two parts that are neither tiny nor the whole screen: (moved, target)."""
    boxes = {}
    for h in hits:
        x, y, w, hh = _bbox(h["pts"])
        if (h.get("kind") != "Text" and 40 < w < W * 0.4 and 40 < hh < H * 0.5
                and h["id"] not in boxes):
            boxes[h["id"]] = (x, y, w, hh)
    def top_at(x, y):                                       # the canvas's pick: last hit wins
        for h in reversed(hits):
            if _inside(h["pts"], x, y):
                return h["id"]
        return None
    ids = [i for i in sorted(boxes, key=lambda i: -boxes[i][2] * boxes[i][3])
           if top_at(boxes[i][0] + boxes[i][2] / 2, boxes[i][1] + boxes[i][3] / 2) == i]
    for a in ids:
        for b in ids:
            if (a != b and 40 < abs(boxes[a][0] - boxes[b][0]) < W * 0.4
                    and boxes[b][0] + 4 + boxes[a][2] < W
                    and abs(boxes[a][1] - boxes[b][1]) > max(boxes[a][3], boxes[b][3])):
                return a, boxes[a], b, boxes[b]
    return None


def main():
    repo, source, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    pre = "after_" if after else "before_"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1014-")
    project = os.path.join(scratch, "proj")
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
                " localStorage.setItem('pad.fontbar.open', '0');"
                " localStorage.setItem('pad.scenes.snap', %r); } catch (e) {}" % json.dumps(SNAP))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "scenes")
            time.sleep(3)
            rig._wait(lambda: scenes().get("scenes"), 120)
            want = os.environ.get("PAD1014_SCENE")
            rows = scenes()["scenes"]
            cands = [r["d"] for r in sorted(rows, key=lambda r: -(r.get("imgs") or 0))]
            if want:
                cands = [want]
            got = None
            for d in cands[:25]:
                api("text_scenes.select", d)
                rig._wait(lambda: not scenes().get("rebuilding"), 600)
                rig._wait(lambda: scenes().get("tree_view") and scenes().get("frames")
                          and scenes()["tree_view"].get("hits"), 60)
                rig._wait(lambda: not scenes().get("tree_busy"), 60)
                t = scenes().get("tree_view") or {}
                if not t.get("hits"):
                    continue
                W, H = t["stage"]
                got = _pair(t["hits"], W, H)
                if got:
                    print("scene", d, flush=True)
                    break
            assert got, "no scene with two parts to line up"
            a, ba, b, bb = got
            print("move", a, ba, "onto", b, bb, flush=True)
            time.sleep(3)
            cv = page.locator(".tree-canvas").first.bounding_box()
            k = cv["width"] / W
            scr = lambda x, y: (cv["x"] + x * k, cv["y"] + y * k)  # noqa: E731
            # the Snap menu (after) / the bar with nothing of the kind (before)
            if after:
                page.get_by_role("button", name="Snap").first.click()
                time.sleep(0.8)
            page.screenshot(path=os.path.join(out_dir, pre + "scenes_snap.png"))
            page.keyboard.press("Escape")
            time.sleep(0.5)
            # grab the middle of a, carry it across so its left edge sits 4 glass px right of b's
            gx, gy = ba[0] + ba[2] / 2, ba[1] + ba[3] / 2
            dx = bb[0] + 4 - ba[0]
            dy = 0                       # straight across, under or over b (they do not overlap)
            page.mouse.move(*scr(gx, gy))
            page.mouse.down()
            steps = 12
            for i in range(1, steps + 1):
                page.mouse.move(*scr(gx + dx * i / steps, gy + dy * i / steps))
                time.sleep(0.03)
            time.sleep(1.0)
            page.screenshot(path=os.path.join(out_dir, pre + "scenes_drag.png"))
            page.mouse.up()
            time.sleep(3)
            pr = (scenes().get("tree_view") or {}).get("props") or {}
            print("dropped", pr.get("id"), "at", pr.get("x"), pr.get("y"),
                  "(target left edge %s)" % bb[0], flush=True)
            # and a corner: the bottom-right one dragged to 3 glass px past b's top edge
            if "--resize" in sys.argv and pr.get("w"):
                cx0, cy0 = pr["x"] + pr["w"], pr["y"] + pr["h"]
                cv = page.locator(".tree-canvas").first.bounding_box()    # the edit chip moves it
                k = cv["width"] / W
                ty = bb[1] + 3
                tx = cx0 + (ty - cy0) * pr["w"] / pr["h"]
                page.mouse.move(*scr(cx0, cy0))
                page.mouse.down()
                for i in range(1, steps + 1):
                    page.mouse.move(*scr(cx0 + (tx - cx0) * i / steps, cy0 + (ty - cy0) * i / steps))
                    time.sleep(0.03)
                time.sleep(0.5)
                page.mouse.up()
                time.sleep(3)
                tv = scenes().get("tree_view") or {}
                print("after resize sel", tv.get("sel"), tv.get("sels"), "msg", scenes().get("canvas_msg"),
                      "edits", tv.get("edits"), flush=True)
                pr = tv.get("props") or {}
                print("resized to y %s h %s (bottom edge %s, target %s)" % (
                    pr.get("y"), pr.get("h"), (pr.get("y") or 0) + (pr.get("h") or 0),
                    bb[1]), flush=True)
                lines = sorted({round(v, 1) for h in t["hits"] if h["id"] != pr.get("id")
                                for bx, by, bw, bh in [_bbox(h["pts"])] for v in (bx, bx + bw / 2, bx + bw)})
                right = (pr.get("x") or 0) + (pr.get("w") or 0)
                print("right edge %s; part lines across near it: %s" % (
                    right, [v for v in lines if abs(v - right) < 20]), flush=True)
            print("errors:", errors, flush=True)
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
