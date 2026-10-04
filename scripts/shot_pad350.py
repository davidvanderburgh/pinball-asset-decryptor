"""PAD-350 proof shots: the Color profiles pop-out bar on the Scenes tab.

    python scripts/shot_pad350.py <repo> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is a scratch copy of the Godzilla
project (shot_pad312's), opens the Scenes tab on Battle Select and photographs the page
twice: <prefix>_scenes_tab.png as it opens (the rainbow tab on the right edge), then
<prefix>_scenes_panel.png after a click on that tab (the bar out, on its Machine screen tab,
with a slider moved so the scene is drawn through it).  Before the change there is no tab:
both shots are the plain page.

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


def main():
    repo, out_dir, prefix = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad350-")
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
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "display")
            time.sleep(1)
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            page.screenshot(path=os.path.join(out_dir, prefix + "_scenes_tab.png"))
            handle = page.query_selector(".cpd-handle")
            print("handle:", bool(handle), flush=True)
            if handle:
                handle.click()
                time.sleep(1)
                page.click(".cpd-tabs button:has-text('Machine screen')")
                time.sleep(1.5)
                # move Blue's middle shades so the scene is drawn again through it
                box = page.query_selector(".cpd-panel .cp-slider.b input[type=number]")
                if box:
                    box.fill("1.6")
                    box.press("Enter")
                time.sleep(8)
                ts = (state().get("text_scenes") or {})
                print("look:", (ts.get("look") or {}).get("parts"), flush=True)
            page.screenshot(path=os.path.join(out_dir, prefix + "_scenes_panel.png"))
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
