"""PAD-566 proof shots: a picture's Apply to all in the Scenes Colors bar.

    python scripts/shot_pad566.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project with the game's own pictures
unlocked, opens Scenes on the Kaiju battle select scene, selects a picture there, opens the
Colors bar and gives that picture "No change" (DragonRR's case: the card's own colors
back).  Under the same names before and after:

- scenes_picture_colors.png  the Colors bar on that picture: before, its This file box has
                             no Apply to all; after, Apply to all profiled images / Apply to
                             all images, as on the Images tab

After only: scenes_picture_apply_all.png, the question Apply to all images asks; Yes is
answered and the number of pictures given "No change" is printed.

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



def _layers(state):
    tv = (state().get("text_scenes") or {}).get("tree_view") or {}
    return tv.get("layers") or []


def _owns(project):
    with open(os.path.join(project, ".staged_changes.json"), encoding="utf-8") as f:
        data = json.load(f)
    return data


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad566-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
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
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.removeItem('pad.fontbar.open'); } catch (e) {}")
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
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api("text_scenes.select", base.BATTLE)
            time.sleep(8)
            print("unlocked:", api("text_scenes.tree_color_unlocked", True), flush=True)
            time.sleep(4)
            pics = [l for l in _layers(state) if (l.get("color") or {}).get("rel")
                    and not (l.get("color") or {}).get("locked")
                    and (l.get("color") or {}).get("kind", "images") == "images"]
            print("pictures:", [(l["id"], l["name"], l["color"]) for l in pics], flush=True)
            pic = next((l for l in pics if l["name"] == "unnamed_instance_25"), pics[0])
            api("text_scenes.tree_select", pic["id"])
            time.sleep(3)
            handle = page.query_selector("button.cpd-handle[aria-label='Color profiles']")
            if handle:
                handle.click()
                time.sleep(3)
            print("color file:", (state().get("color") or {}).get("file"), flush=True)
            print("preset none:", api("color.preset", "none"), flush=True)
            time.sleep(3)
            settle(page)
            page.screenshot(path=out("scenes_picture_colors.png"))
            btn = page.query_selector(".cpd-file-all button:has-text('Apply to all images')")
            print("apply to all images button:", bool(btn), flush=True)
            if btn:
                btn.click()
                time.sleep(1.5)
                page.screenshot(path=out("scenes_picture_apply_all.png"))
                page.click(".modal button:has-text('Yes')")
                time.sleep(6)
                data = _owns(project)
                own = (data.get("colour_profile_files") or data.get("color_files") or {})
                print("sidecar keys:", sorted(data), flush=True)
                print("image switches on:", sum(1 for v in (data.get("image_color_slots")
                                                            or {}).values() if v), flush=True)
                print("own profiles:", json.dumps(own)[:400], flush=True)
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
