"""PAD-1494 proof shots: Godzilla's Match screen title in the Scenes preview.

    python scripts/shot_pad1494.py <repo> <project> <out_dir> [--after]

<project> is a SCRATCH Godzilla Pro extract (images + text).  Picks the Match scene's MATCH title
box (one the game fills) and takes, under before_/after_:

- scenes_match.png        the preview and the Selected panel, the box picked.
- match_closeup.png       the box on the preview, 4x.

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

MATCH = "/godzilla_pro/assets/lcd/demand_loaded/0335207f5e840d81afa158c6c2bb6e3fa02653b4"


def main():
    repo, project, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad1494-")
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
            api("text_scenes.select", MATCH)
            time.sleep(12)
            page.locator("button", has_text="Hide list").first.click()
            time.sleep(2)
            hits = tv().get("hits") or []
            box = next(h["id"] for h in hits if h.get("name") == "Title_Instance")
            other = next(h["id"] for h in tv()["hits"] if h["id"] != box)
            props = pick(box)
            print("box", box, props.get("name"), "try:", props.get("try"),
                  "words:", props.get("text") or props.get("words"), flush=True)
            full(page, "scenes_match.png")
            pick(other)
            closeup(page, "match_closeup.png", box)
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
