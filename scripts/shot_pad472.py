"""PAD-472 proof shots: Undo after hiding layers with their eyes on Scenes.

    python scripts/shot_pad472.py <repo> <godzilla LE project> <out_dir> <prefix>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one, its scene edits are dropped), opens Scenes on KAIJU BATTLE SELECT and does what DragonRR
did: a drag that is undone (so Redo is lit), then three layers hidden with their eyes, clicked
as a user would.  Writes:

- <prefix>_eye_hides.png  the three layers hidden with their eyes (the Undo button's state)
- <prefix>_eye_undo.png   after Ctrl+Z once

and prints the Undo / Redo state and which eyes are shut after each step.
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

# lines of text on the screen; the first three drawn ones are hidden with their eyes
LINES = ("Ebirah_Textbox", "Line1_Instance", "Line2_Instance")


def main():
    repo, source, out_dir, prefix = sys.argv[1:5]
    print("repo:", os.path.abspath(repo), flush=True)
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad472-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    # the extract's checksums mark the folder as extracted (no "nothing extracted" banner)
    if os.path.isfile(os.path.join(source, ".checksums.md5")):
        shutil.copy2(os.path.join(source, ".checksums.md5"), project)
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright

    def report(what):
        tv = state()["tree_view"]
        shut = [l["name"] for l in tv["layers"] if l["view_off"]]
        print("%s: can_undo=%s can_redo=%s eyes shut=%s edits=%s" % (
            what, tv["can_undo"], tv["can_redo"], shut, tv["edits"]), flush=True)

    def settle(page):
        time.sleep(1.0)
        rig._wait(lambda: not state().get("tree_busy"), 60)
        page.mouse.move(5, 995)
        time.sleep(3)

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
            print("drawn text layers:", [l["name"] for l in layers
                                         if l["drawn"] and l["kind"] == "Text"], flush=True)
            # an edit taken back, as in DragonRR's shot: Redo is lit
            first = [l for l in layers if l["drawn"]][0]
            assert api("text_scenes.tree_move", first["id"], 10, 0)
            assert api("text_scenes.tree_undo")
            settle(page)
            report("after a move and its undo")
            picks = [l for l in layers if l["drawn"]
                     and any(l["name"].startswith(n) for n in LINES)][:3]
            for l in picks:
                row = page.locator('.tree-layers [data-node="%s"]' % l["id"])
                row.evaluate("el => el.scrollIntoView({block: 'center'})")
                time.sleep(0.3)
                row.locator(".ly-eye").click()
                time.sleep(1.0)
                rig._wait(lambda: not state().get("tree_busy"), 60)
            settle(page)
            report("after %d eye hides (%s)" % (len(picks), [l["name"] for l in picks]))
            page.screenshot(path=os.path.join(out_dir, "%s_eye_hides.png" % prefix))
            page.keyboard.press("Control+z")
            settle(page)
            report("after Ctrl+Z")
            page.screenshot(path=os.path.join(out_dir, "%s_eye_undo.png" % prefix))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
