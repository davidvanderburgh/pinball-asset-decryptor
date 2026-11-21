"""PAD-1481 (PR #41) proof shots: themes on the Write tab, Keep size per theme, the Scenes side panel.

    python scripts/shot_pad1481.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad1462's scratch King Kong LE project, with a theme "Dark" (theme 2) giving one scene
picture a picture of its own (a 640x480 recolored copy, so Keep size means something) and IMAGE SET ticked on the
Service menu tab. Photographs, under the same names before and after:

- write_tab.png     the Write tab's pending changes (after: a "Pending (Themes)" row for the theme's picture)
- images_keep.png   the Images tab with theme 2 picked and that picture's row clicked (after: its own Keep size)
- scenes_panel.png  the Scenes tab on the scene holding the picture, the picture's layer selected (after: the side
                    panel in panels of its own, "Show pixel for pixel")

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
import shot_pad1462 as themes  # noqa: E402,F401 - sets the King Kong scratch source on shot_pad312
import shot_pad312 as base  # noqa: E402
import shot_pad360 as saved  # noqa: E402
import shot_pad463 as imgs  # noqa: E402


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad1481-")
    project = imgs._project(scratch)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)

    # the theme, written before the app starts (the same calls the Images tab's theme picker makes)
    sys.path.insert(0, repo)
    from PIL import Image
    from pinball_decryptor.plugins.stern import scene_variants as SV
    with Image.open(os.path.join(project, *base.PORTRAIT.split("/"))) as im:
        r, g, b, a = im.convert("RGBA").split()
        dark = Image.merge("RGBA", (r.point(lambda v: v // 3), g.point(lambda v: v // 3), b, a)).resize((640, 480))
    mine = os.path.join(scratch, "dark_theme_picture.png")
    dark.save(mine)
    SV.set_themes_on(project, True)
    SV.add_set(project, "Dark")
    SV.set_picture(project, 2, base.PORTRAIT, mine)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    data["service_menu"] = {"on": ["image_set"]}
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    tv = lambda: (state().get("text_scenes") or {}).get("tree_view") or {}  # noqa: E731

    def settle(page, wait=2.0):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                                   # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 990)
        time.sleep(wait)

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open.images', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)

            # 1. the Write tab
            api("ui.select_tab", "write")
            time.sleep(10)
            settle(page)
            rows = [r for r in ((state().get("write") or {}).get("rows") or []) if "heme" in json.dumps(r)]
            print("write theme rows:", rows[:4], flush=True)
            page.screenshot(path=out("write_tab.png"))

            # 2. the Images tab, theme 2 picked, the picture's row clicked
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.set", "images", "search", base.PORTRAIT.split("_")[-1][:8])
            time.sleep(2)
            api("imgsets.pick", 2)
            time.sleep(2.5)
            page.locator(".img-tbl .tr:has-text('%s')" % base.PORTRAIT.split("_")[-1][:8]).first.click()
            time.sleep(2.5)
            settle(page)
            st = state()
            print("imgsets:", {k: (st.get("imgsets") or {}).get(k) for k in ("enabled", "names", "current")},
                  flush=True)
            page.screenshot(path=out("images_keep.png"))

            # 3. the Scenes tab on the picture's scene, its layer selected (theme 1 shown)
            api("imgsets.pick", 1)
            time.sleep(1.5)
            print("open scenes:", api("images.open_scenes", base.PORTRAIT), flush=True)
            end = time.time() + 40
            while time.time() < end and not tv().get("hits"):
                time.sleep(1)
            layers = tv().get("layers") or []
            bitmaps = [ly for ly in layers if ly.get("kind") == "Bitmap" and ly.get("pics")]
            pics = [ly for ly in bitmaps if base.PORTRAIT in ly["pics"]] or bitmaps
            print("layers with the picture:", [(ly["id"], ly["name"], ly["kind"]) for ly in pics][:5], flush=True)
            if pics:
                api("text_scenes.tree_select", pics[0]["id"])
                time.sleep(5)
            props = tv().get("props") or {}
            print("picked:", props.get("name"), props.get("kind"), props.get("pic"), flush=True)
            settle(page, 2.5)
            page.screenshot(path=out("scenes_panel.png"))
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
