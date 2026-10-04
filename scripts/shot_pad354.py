"""PAD-354 proof shots: the Scenes tab's Color profiles bar (DragonRR's second round).

    python scripts/shot_pad354.py <repo> <out_dir> <prefix>

Serves <repo> on shot_pad350's scratch Godzilla project, opens Scenes with the bar on
Files and photographs:
  <prefix>_numbox.png  Red's Middle shades typed as 2.81, then the slider moved with the
                       arrow keys and dragged: the number box should follow the slider
  <prefix>_bar.png     the bar after Recommended / No change clicks, an Undo and the
                       divider dragged wider (where the branch has them), with the scene
                       list's tab on the left
  <prefix>_list.png    the scene list brought back while the bar is open
and prints what the number box and its label read, and the note's height on each preset.

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

RED = ".cpd-panel .cp-slider.r"  # the first: Middle shades


def main():
    repo, out_dir, prefix = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad354-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(lambda: webui_shot.state(url), "images")
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "assets")
            time.sleep(1)
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(6)
            page.click(".cpd-handle")
            time.sleep(1.5)

            def red():
                el = page.query_selector(RED)
                return (el.query_selector("input[type=number]").input_value(),
                        el.query_selector(".cp-sl-val").inner_text())

            # the number box, then the slider by keyboard, then by mouse
            box = page.query_selector(RED + " input[type=number]")
            box.click()
            box.press("Control+a")
            page.keyboard.type("2.81", delay=60)
            print("typed 2.81:", red(), flush=True)
            page.keyboard.press("Tab")                   # onto the slider
            for _ in range(5):
                page.keyboard.press("ArrowLeft")
            time.sleep(0.6)
            print("arrow keys:", red(), flush=True)
            rng = page.query_selector(RED + " input[type=range]")
            b = rng.bounding_box()
            page.mouse.move(b["x"] + b["width"] * 0.8, b["y"] + b["height"] / 2)
            page.mouse.down()
            page.mouse.move(b["x"] + b["width"] * 0.62, b["y"] + b["height"] / 2, steps=6)
            page.mouse.up()
            time.sleep(1)
            print("slider dragged:", red(), flush=True)
            page.mouse.move(400, 990)
            time.sleep(0.3)
            page.screenshot(path=os.path.join(out_dir, prefix + "_numbox.png"),
                            clip={"x": 900, "y": 0, "width": 700, "height": 1000})

            # the note's height as the starting points are clicked
            for label in ("Recommended", "No change", "Recommended", "No change"):
                page.click(".cpd-panel .cp-row button:has-text('%s')" % label)
                time.sleep(1.5)
                note = page.query_selector(".cpd-body .note")
                ctl = page.query_selector(".cpd-body .cp-controls")
                print(label, "note h:", note and note.bounding_box()["height"],
                      "controls y:", ctl and ctl.bounding_box()["y"],
                      "red:", red(), flush=True)
            undo = page.query_selector(".cpd-panel button:has-text('Undo')")
            print("undo button:", bool(undo), flush=True)
            if undo:
                undo.click()
                time.sleep(1.5)
                note = page.query_selector(".cpd-body .note")
                print("after Undo:", note.inner_text()[:60], "red:", red(), flush=True)
            grip = page.query_selector(".cpd-grip")
            print("grip:", bool(grip), flush=True)
            if grip:
                g = grip.bounding_box()
                page.mouse.move(g["x"] + 4, g["y"] + 300)
                page.mouse.down()
                page.mouse.move(g["x"] - 100, g["y"] + 300, steps=8)
                page.mouse.up()
                time.sleep(1)
                print("bar width:", page.query_selector(".cpd").bounding_box()["width"], flush=True)
            page.mouse.move(400, 990)
            time.sleep(0.3)
            page.screenshot(path=os.path.join(out_dir, prefix + "_bar.png"))
            # the scene list back: the tab on the left edge (the button under the preview before)
            tab = page.query_selector(".sc-list-tab")
            print("list tab:", bool(tab), flush=True)
            (tab or page.query_selector("button[aria-label='Show the scene list']")).click()
            time.sleep(1.5)
            print("hide caret:", bool(page.query_selector(".sc-list-hide")), flush=True)
            page.mouse.move(400, 990)
            time.sleep(0.3)
            page.screenshot(path=os.path.join(out_dir, prefix + "_list.png"))
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
