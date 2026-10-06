"""PAD-407 proof shot: a layer hidden in the game with its card mark leaves the Scenes preview.

    python scripts/shot_pad407.py <repo> <godzilla LE project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one, its scene edits are dropped), opens Scenes on KAIJU BATTLE SELECT, clicks the card mark
on the Ebirah_Textbox_instance text row (the monster name DragonRR hid) as a user would and
snaps the page to <out_png>.  Prints whether the line is still drawn in the preview.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402
from shot_pad339_scenes import SCENE  # noqa: E402

LINE = "Ebirah_Textbox_instance"


def main():
    repo, source, out = sys.argv[1:4]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad407-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state().get("alive"), 30)
            assert api("text_scenes.select", SCENE)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            layers = state()["tree_view"]["layers"]
            line = [l for l in layers if l["name"].startswith(LINE)][0]
            row = page.locator('.tree-layers [data-node="%s"]' % line["id"])
            row.evaluate("el => el.scrollIntoView({block: 'center'})")
            time.sleep(0.5)
            row.locator(".ly-game").click()
            time.sleep(1.5)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            page.mouse.move(5, 995)
            time.sleep(4)
            got = [l for l in state()["tree_view"]["layers"] if l["id"] == line["id"]][0]
            print(LINE, "hidden in game:", got["hidden"], "eye shut:", got["view_off"],
                  "drawn:", got["drawn"], flush=True)
            page.screenshot(path=out)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
