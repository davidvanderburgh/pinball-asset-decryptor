"""PAD-502 proof shots: a project colored without replacing a picture, saved with pictures, text
and color profiles, then loaded into a stock project.

    python scripts/shot_pad502.py <repo> <out_dir> [--after]

<repo> is the source tree to serve and save with (the ticket branch, or a ``git archive`` of
main for the "before" shots).  The project saved is a copy of shot_pad312's Godzilla project
colored the way DragonRR had his 70th Anniversary look: the game's own pictures unlocked and
every one switched on with Black and white as the individual files profile, his two lines of
KAIJU BATTLE SELECT with their own profiles, his two shadows.  <repo>'s own code saves it
("Save every scene with pictures, text and color profiles"), and the page loads it into a
stock copy of the same project.  Photographs, under the same names before and after:

- scenes_loaded.png  Scenes on KAIJU BATTLE SELECT just after Load scene edits from a file
- images_loaded.png  the Images tab on the battle scene's portrait after the same load

Needs Playwright (PAD_PWLIB or the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

CARD = base.BATTLE + "/scene.radium"
YELLOW = {"name": "Yellow", "gain": [3.19, 3.17, 0.14], "gamma": [0.22, 0.22, 3.85],
          "lift": [0.0, 0.0, 0.0], "saturation": 1.0}
MINE = {"name": "My profile", "gain": [3.19, 3.17, 3.15], "gamma": [0.221, 0.219, 0.23],
        "lift": [0.0, 0.0, 0.0], "saturation": 1.0}
BW = {"name": "Black and white", "gamma": [1.0, 1.0, 1.0], "gain": [1.0, 1.0, 1.0],
      "lift": [0.0, 0.0, 0.0], "saturation": 0.0}
SAVE = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
from pinball_decryptor.plugins.stern import scene_edit, scene_share
print("saved", scene_share.export_all(sys.argv[2], sys.argv[3], None,
                                      scene_edit.trees_of(sys.argv[2])),
      os.path.getsize(sys.argv[3]), "bytes")
'''


def _project(scratch, name):
    """A stock copy of the Godzilla project: no picks, no scene edits, no profiles."""
    dst = os.path.join(scratch, name)
    shutil.copytree(base.SOURCE, dst, ignore=lambda d, names: [
        n for n in names if n in base.SKIP or n.startswith("scene_edits")])
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({}, f)
    return dst


def _colour_it(project):
    pics = []
    for d, _dirs, files in os.walk(os.path.join(project, "images")):
        pics += [os.path.relpath(os.path.join(d, f), project).replace("\\", "/")
                 for f in files if f.endswith(".png")]
    lines = {"%s#%d" % (CARD, n): True for n in (1239, 1241)}
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"image_color_unlocked": True, "asset_color_profile": BW,
                   "image_color_slots": {r: True for r in sorted(pics)},
                   "text_color_slots": lines,
                   "text_color_profiles": {"%s#1239" % CARD: YELLOW, "%s#1241" % CARD: MINE}},
                  f, indent=2)
    shadow = {"dx": 4.0, "dy": 4.0, "mul": [0.0, 0.0, 0.0, 0.6], "op": "shadow"}
    edits = {CARD: [dict(shadow, id=2130706433, node=1241), dict(shadow, id=2130706435,
                                                                    node=1239)]}
    with open(os.path.join(project, "images", "scene_textures", "scene_edits.json"), "w",
              encoding="utf-8") as f:
        json.dump(edits, f, indent=1)
    return len(pics)


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad502-")
    theirs = _project(scratch, "Godzilla")
    print("colored", _colour_it(theirs), "game pictures", flush=True)
    save = os.path.join(scratch, "Godzilla scenes with pictures.zip")
    subprocess.run([sys.executable, "-c", SAVE, repo, theirs, save], check=True)
    project = _project(scratch, "gzho")
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
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.removeItem('pad.fontbar.open'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            time.sleep(8)
            t = threading.Thread(target=api, args=("text_scenes.edits_load", save), daemon=True)
            t.start()
            t.join(120)
            time.sleep(1)
            modal = page.query_selector(".modal")
            if modal:
                print("dialog:", modal.inner_text().replace("\n", " | "), flush=True)
                page.screenshot(path=out("scenes_load_dialog.png"))
                btn = page.query_selector('.modal .ft button:has-text("OK")')
                if btn:
                    btn.click()
            time.sleep(8)
            print("caption:", (state().get("text_scenes") or {}).get("caption_full"), flush=True)
            with open(os.path.join(project, ".staged_changes.json"), encoding="utf-8") as f:
                side = json.load(f)
            print("loaded: unlocked", side.get("image_color_unlocked"), "picture switches",
                  len(side.get("image_color_slots") or {}), "files profile",
                  (side.get("asset_color_profile") or {}).get("name"), "line switches",
                  len(side.get("text_color_slots") or {}), flush=True)
            page.mouse.move(5, 990)
            time.sleep(1)
            page.screenshot(path=out("scenes_loaded.png"))
            api("ui.select_tab", "images")
            time.sleep(4)
            base._wait_scan(state, "images")
            api("images.select", base.PORTRAIT)
            time.sleep(5)
            page.mouse.move(5, 990)
            page.screenshot(path=out("images_loaded.png"))
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
