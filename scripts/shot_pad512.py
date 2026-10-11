"""PAD-512 proof shots: a click on a line of text under a see-through picture picks the line.

    python scripts/shot_pad512.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project set up the way DragonRR had his: the
individual files profile Black and white, the game's own lines unlocked, and every layer of
the OXYGEN DESTROYER screen (scene 39455fd1) switched on.  That screen's top layer is a
full-screen picture of the score panel, see-through everywhere but the panel.  Then a real
mouse click (Playwright, the installed Edge) on the title in the preview, under the same name
before and after:

- scenes_click_title.png   Before: the click picks the full-screen picture on top, so a colour
                           set then lands on it.  After: it picks the title.

After only: scenes_title_colors_bar.png, his own way on from there: the Colors bar beside
the scene is on the title the click picked, and a colour set in it goes on the title alone.

The click's pick goes to the console.  Needs Playwright (the user site-packages one).
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

SCENE = ("/godzilla_le/assets/lcd/auto_loaded/477760ac3cc07d1aec810758d9fd83b7bc86ee72/"
         "39455fd1cfe1f4e2827846a64e58799c65f3a067")
#: the screen's lines (Time, Info, Title) and the full-screen picture on top of them
LAYERS = (319, 323, 327, 329)
TITLE = 327


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad512-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tv = lambda: (state().get("text_scenes") or {}).get("tree_view") or {}  # noqa: E731
    from playwright.sync_api import sync_playwright

    def settle(page, wait=1.5):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                               # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 1100)
        time.sleep(wait)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1150})
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
            api("text_scenes.select", SCENE + "/scene.radium") or api("text_scenes.select", SCENE)
            time.sleep(8)
            print("unlocked:", api("text_scenes.tree_color_unlocked", True), flush=True)
            time.sleep(3)
            for nid in LAYERS:
                api("text_scenes.tree_color", nid, True)
            time.sleep(4)
            view = tv()
            hit = next(h for h in view.get("hits") or [] if h["id"] == TITLE)
            xs, ys = [q[0] for q in hit["pts"]], [q[1] for q in hit["pts"]]
            sx, sy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
            W, H = view["stage"]
            r = page.locator(".tree-canvas").first.bounding_box()
            cx, cy = r["x"] + sx * r["width"] / W, r["y"] + sy * r["height"] / H
            page.mouse.click(cx, cy)
            time.sleep(4)
            props = tv().get("props") or {}
            print("clicked the title at stage (%d, %d): picked %s (%s)" % (
                sx, sy, props.get("name"), props.get("kind")), flush=True)
            settle(page)
            page.screenshot(path=out("scenes_click_title.png"))
            if after and props.get("id") == TITLE:
                # his own way: the Colors bar beside the scene, on the line the click picked
                page.locator('button.cpd-handle[aria-label="Color profiles"]').first.click()
                deadline = time.time() + 20
                while time.time() < deadline and not (state().get("color") or {}).get("file"):
                    time.sleep(0.5)
                f = (state().get("color") or {}).get("file") or {}
                print("colors bar file:", f.get("kind"), f.get("rel"), flush=True)
                if not f:
                    raise SystemExit("the Colors bar is not on the title")
                print("preset none:", api("color.preset", "none"), flush=True)
                time.sleep(1)
                print("gain:", api("color.set_params", {"gain": [1.0, 0.35, 0.1]}), flush=True)
                time.sleep(6)
                settle(page)
                page.screenshot(path=out("scenes_title_colors_bar.png"))
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
