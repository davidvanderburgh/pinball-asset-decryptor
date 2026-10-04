"""PAD-368 proof shots: one color profile per file.

    python scripts/shot_pad368.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project (one Battle Select portrait and
one clip replaced, the portrait's color profile attached) with two profile files in the
folder the Saved profiles list reads, and photographs, under the same names before and
after:

- images_bar.png        the Images tab, the portrait clicked, the Colors bar open on Files
                        with "Godzilla LE" picked from Saved profiles
- images_tooltip.png    the portrait's Color palette hovered
- video_tooltip.png     the clip's Color palette hovered
- scenes_tooltip.png    Battle Select in Scenes, the portrait's layer hovered

Before (main) the pick changes the project's one files profile; after (the ticket branch)
it is the portrait's own, so the tooltips name it.

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


def _hover_tip(page, selector, path):
    el = page.query_selector(selector)
    print("hover", selector, bool(el), flush=True)
    if el:
        el.scroll_into_view_if_needed()
        el.hover()
        time.sleep(1.6)
    page.screenshot(path=path)
    page.mouse.move(5, 990)
    time.sleep(0.4)


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad368-")
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
            st = base._wait_scan(state, "images")
            print("images:", st.get("status"), flush=True)
            api("ui.set", "images", "search", "530x726")
            time.sleep(2)
            api("images.select", base.PORTRAIT)
            time.sleep(3)
            # the bar, opened with the portrait clicked, on Files; a saved profile picked
            page.click(".cpd-handle")
            time.sleep(1.5)
            tab = page.query_selector(".cpd-tabs button:has-text('Files')")
            if tab:
                tab.click()
                time.sleep(1)
            c = state().get("color") or {}
            pick = next((o["value"] for o in c.get("saved") or []
                         if "Godzilla" in o.get("label", "")), None)
            print("use_saved:", api("color.use_saved", pick), flush=True)
            time.sleep(2)
            page.eval_on_selector(".cpd-body", "el => { el.scrollTop = 0; }")
            page.mouse.move(5, 990)
            time.sleep(0.5)
            page.screenshot(path=out("images_bar.png"))
            c = state().get("color") or {}
            print("color:", {k: c.get(k) for k in ("mode", "name", "file", "own_names",
                                                   "asset_name")}, flush=True)
            page.click(".cpd-handle")                     # close it again for the tooltips
            time.sleep(1)
            name = base.PORTRAIT.split("/")[-1]
            _hover_tip(page, ".img-tbl .tr:has-text('%s') .img-color" % name,
                       out("images_tooltip.png"))
            # the Video tab: the clip's palette
            api("ui.select_tab", "video")
            time.sleep(2)
            st = base._wait_scan(state, "video")
            print("video rows:", len(st.get("rows") or []), flush=True)
            time.sleep(2)
            _hover_tip(page, ".vid-color", out("video_tooltip.png"))
            # Scenes: Battle Select, the portrait's layer
            api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            tv = (state().get("text_scenes") or {}).get("tree_view") or {}
            lay = next((l for l in tv.get("layers") or []
                        if (l.get("color") or {}).get("rel") == base.PORTRAIT), None)
            print("layer:", lay and (lay["id"], lay["name"], lay["color"]), flush=True)
            if lay:
                _hover_tip(page, "[data-node='%s'] .sc-t" % lay["id"], out("scenes_tooltip.png"))
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
