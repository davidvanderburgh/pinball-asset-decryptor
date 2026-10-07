"""PAD-438 proof shots: a color profile on Scenes text, as on pictures.

    python scripts/shot_pad438.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project with the individual files profile
set to Black and white (so a corrected line is plainly grey), opens Battle Select in
Scenes, ticks "Unlock extracted images", adds a green line of text, clicks the Color
switch of every text layer and photographs, under the same names before and after:

- scenes_text.png          the scene and its Layers list
- scenes_text_tip.png      the added line's Color button hovered

Before (main) a text layer has no Color switch, so the clicks do nothing and the text keeps
its colours; after (the ticket branch) each line's switch is on and the preview draws it
through the profile.

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


def _layers(state):
    tv = (state().get("text_scenes") or {}).get("tree_view") or {}
    return tv.get("layers") or []


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad438-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "assets")
            time.sleep(1)
            print("preset bw:", api("color.preset", "bw"), flush=True)
            time.sleep(1)
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            print("unlock:", api("text_scenes.tree_color_unlocked", True), flush=True)
            time.sleep(2)
            texts = [l for l in _layers(state) if l.get("kind") == "Text"]
            tokyo = next((l["id"] for l in texts if (l.get("text") or "") == "TOKYO"),
                         texts[0]["id"] if texts else None)
            print("add text:", api("text_scenes.tree_add_text", "MY OWN LINE", tokyo),
                  flush=True)
            time.sleep(3)
            added = [l for l in _layers(state) if l.get("kind") == "Text" and l.get("added")]
            if added:
                print("tint:", api("text_scenes.tree_tint", added[0]["id"], "#3ce03c", 100),
                      flush=True)
                time.sleep(3)
            for l in [l for l in _layers(state) if l.get("kind") == "Text"]:
                print("switch", l["id"], l["name"],
                      api("text_scenes.tree_color", l["id"], True), flush=True)
            time.sleep(6)
            for l in _layers(state):
                if l.get("kind") == "Text":
                    print("layer", l["id"], l["name"], l.get("color"), flush=True)
            page.screenshot(path=out("scenes_text.png"))
            if added:
                # its Color button where it has one, else its name (the row's own tooltip)
                row = '.ly-item[data-node="%s"]' % added[0]["id"]
                el = (page.query_selector(row + " .ly-color")
                      or page.query_selector(row + " .sc-t"))
                print("tip target:", bool(el), flush=True)
                if el:
                    el.scroll_into_view_if_needed()
                    el.hover()
                    time.sleep(1.6)
            page.screenshot(path=out("scenes_text_tip.png"))
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
