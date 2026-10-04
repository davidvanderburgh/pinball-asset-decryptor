"""PAD-356 proof shot: Recommended on the individual files while the whole screen overlay is
Recommended too (DragonRR: "Recommended disables the preview").

    python scripts/shot_pad356.py <repo> <out_png>

Serves <repo> on shot_pad312's scratch Godzilla project, stages the Recommended overlay,
switches every picture on for the individual files profile, opens Scenes on KAIJU BATTLE
SELECT with the Color profiles bar on Files and clicks its Recommended.  Snaps the page and
prints the note and the preview row's Individual files name.
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
    repo, out = sys.argv[1:3]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad356-")
    project = base._project(scratch)
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
            api("color.set_mode", "display")
            time.sleep(0.5)
            api("color.preset", "recommended")
            time.sleep(1)
            api("color.set_mode", "assets")
            time.sleep(0.5)
            api("color.set_all", "images", True)
            time.sleep(1)
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(6)
            page.click(".cpd-handle")
            time.sleep(1.5)
            page.click(".cpd-panel .cp-row button:has-text('No change')")
            time.sleep(1.5)
            page.click(".cpd-panel .cp-row button:has-text('Recommended')")
            time.sleep(2.5)
            note = page.query_selector(".cpd-body .note")
            print("note:", note and note.inner_text(), flush=True)
            row = page.query_selector(".look-row")
            print("row:", row and row.inner_text(), flush=True)
            page.mouse.move(400, 990)
            time.sleep(0.3)
            page.screenshot(path=out)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
