"""PAD-369 proof shots: color profile quality of life.

    python scripts/shot_pad369.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project (one Battle Select portrait and one
clip replaced, both with the color profile attached) with two profile files in the folder the
Saved profiles list reads, gives the portrait its own "Godzilla LE" profile, and photographs,
under the same names before and after:

- images_rep_tooltip.png    the Images tab, the portrait's Replacement name hovered
- video_rep_tooltip.png     the Video tab, the clip's Replacement name hovered
- scenes_files_switch.png   Battle Select in Scenes, the portrait's layer selected, the
                            preview's Individual files switch turned off, then "Black
                            playfield" picked for it from the Colors bar's Saved profiles
- scenes_layer_tooltip.png  the portrait's layer hovered
- scenes_hide.png           the caret under the preview that hides the scene list, the
                            Colors bar open (DragonRR's screenshot)
- scenes_hide_search.png    the scene list's search row and its hide button
- scenes_save_menu.png      the Save / load edits menu open

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


def _hover_tip(page, selector, path, clip=None):
    el = page.query_selector(selector)
    print("hover", selector, bool(el), flush=True)
    if el:
        el.scroll_into_view_if_needed()
        el.hover()
        time.sleep(1.6)
    page.screenshot(path=path, clip=clip)
    page.mouse.move(5, 990)
    time.sleep(0.4)


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad369-")
    project = base._project(scratch)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    data["image_color_slots"] = {base.PORTRAIT: True}
    data["video_color_slots"] = {base.VIDEO: True}
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    for name, text in (("Godzilla LE.txt", saved.GODZILLA), ("Black playfield.txt", saved.DARK)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731

    def pick(label):
        c = state().get("color") or {}
        path = next((o["value"] for o in c.get("saved") or [] if label in o.get("label", "")),
                    None)
        print("use_saved", label, api("color.use_saved", path), flush=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.removeItem('pad.colorbar.open.images');"
                " localStorage.removeItem('pad.colorbar.open.video'); } catch (e) {}")
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
            # the portrait's own profile, picked with the bar open on it
            page.click(".cpd-handle")
            time.sleep(1.5)
            api("color.set_file", "images", base.PORTRAIT, "my_portrait.png", True,
                {"ns": "images"})
            time.sleep(1)
            pick("Godzilla")
            time.sleep(1.5)
            page.click(".cpd-handle")
            time.sleep(1)
            name = base.PORTRAIT.split("/")[-1]
            _hover_tip(page, ".img-tbl .tr:has-text('%s') .img-rep" % name,
                       out("images_rep_tooltip.png"))
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video")
            time.sleep(2)
            _hover_tip(page, ".vid-rep.picked, .vid-rep.ondisk", out("video_rep_tooltip.png"))
            # Scenes: Battle Select, the portrait's layer selected, Individual files off
            api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            tv = (state().get("text_scenes") or {}).get("tree_view") or {}
            lay = next((l for l in tv.get("layers") or []
                        if (l.get("color") or {}).get("rel") == base.PORTRAIT), None)
            print("layer:", lay and (lay["id"], lay["name"], lay["color"]), flush=True)
            api("text_scenes.set_look_part", "files", False)
            time.sleep(2)
            if lay:
                api("text_scenes.tree_select", lay["id"], "")
                time.sleep(2)
            page.click(".cpd-handle")
            time.sleep(2)
            pick("Black playfield")
            time.sleep(5)
            look = (state().get("text_scenes") or {}).get("look") or {}
            print("scenes look switches:", look.get("sw"), flush=True)
            page.mouse.move(5, 990)
            page.screenshot(path=out("scenes_files_switch.png"))
            # the caret under the preview (DragonRR's screenshot), the bar open as there
            bar = page.query_selector(".scenes-stagebar")
            if bar:
                b = bar.bounding_box()
                page.screenshot(path=out("scenes_hide.png"), clip={
                    "x": max(0, b["x"] - 60), "y": max(0, b["y"] - 50),
                    "width": 520, "height": b["height"] + 110})
            page.click(".cpd-handle")
            time.sleep(1.5)
            if lay:
                _hover_tip(page, "[data-node='%s'] .sc-t" % lay["id"],
                           out("scenes_layer_tooltip.png"))
            # the scene list shown again, its search row and hide button
            box = page.query_selector(".scenes-search")
            if box:
                b = box.bounding_box()
                page.screenshot(path=out("scenes_hide_search.png"), clip={
                    "x": max(0, b["x"] - 20), "y": max(0, b["y"] - 60),
                    "width": b["width"] + 240, "height": b["height"] + 160})
            page.click("button:has-text('Save / load edits')")
            time.sleep(1)
            page.screenshot(path=out("scenes_save_menu.png"))
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
