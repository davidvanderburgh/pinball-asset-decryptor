"""PAD-451 proof shots: a line of text in a font with colours of its own shares its palette.

    python scripts/shot_pad451.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project with the individual files profile
set to Black and white, opens Battle Select in Scenes, ticks "Unlock extracted images and
text", clicks the palette of EBIRAH (orange GameFont_Secondary, whose letters sit on three
font pictures) and photographs, under the same names before and after:

- scenes_font_rows.png     the Layers list on the lines in that font, nothing hovered
- scenes_font_tip.png      the Layers list, EBIRAH's palette hovered
- scenes_font_colors.png   the Colors bar open on EBIRAH
- images_font_page.png     the Images tab on the font's second picture (G, H, K, M-Z)

Before (main) the palette is that of the font's first picture alone and reads like any
other; after (the ticket branch) it is marked shared, names the font and what it reaches,
lights the lines that share it, and switches every picture of the font.

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

PAGE2 = "images/scene_textures/radimg_512x512_1a9486f2.png"


def _layers(state):
    tv = (state().get("text_scenes") or {}).get("tree_view") or {}
    return tv.get("layers") or []


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad451-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1150})
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
            time.sleep(3)
            ebirah = next(l for l in _layers(state) if l.get("text") == "EBIRAH")
            print("switch EBIRAH:", api("text_scenes.tree_color", ebirah["id"], True),
                  flush=True)
            time.sleep(6)
            for l in _layers(state):
                if (l.get("color") or {}).get("font") is not None:
                    print("layer", l["id"], l["name"], l.get("text"), l.get("color"),
                          flush=True)
            # the list on the font's lines, from GIGAN down (EBIRAH's row in view)
            row = '.ly-item[data-node="%s"]' % ebirah["id"]
            page.eval_on_selector(row, "e => e.scrollIntoView({block: 'start'})")
            time.sleep(1)
            page.screenshot(path=out("scenes_font_rows.png"))
            el = page.query_selector(row + " .ly-color")
            print("palette:", bool(el), flush=True)
            if el:
                el.hover()
                time.sleep(1.6)
            page.screenshot(path=out("scenes_font_tip.png"))
            page.mouse.move(5, 5)
            time.sleep(0.5)
            api("text_scenes.tree_select", ebirah["id"])
            time.sleep(3)
            handle = page.query_selector(".cpd-handle")
            if handle:
                handle.click()
                time.sleep(3)
            print("color file:", (state().get("color") or {}).get("file"), flush=True)
            page.screenshot(path=out("scenes_font_colors.png"))
            if handle:
                handle.click()
                time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            api("ui.set", "images", "search", "1a9486f2")
            time.sleep(2)
            api("images.select", PAGE2)
            time.sleep(3)
            page.screenshot(path=out("images_font_page.png"))
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
