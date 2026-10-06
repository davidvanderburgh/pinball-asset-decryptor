"""PAD-402 proof shots: a shared file loaded over the user's own edits (Scenes and Modes).

    python scripts/shot_pad402.py <repo> <out_dir> [--after]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots). Photographs, under the same names before and after:

- scenes_load.png  Scenes > Load from a file... of a save whose battle scene and GIGAN line the
                   user has edited differently, beside a scene they have not touched
- modes_load.png   Modes > Load from a file... of a KAIJU RUSH the project already has

Needs Playwright (PAD_PWLIB or the user site-packages one), the installed Edge and the Godzilla
project shot_pad312 copies.
"""
import json
import os
import sys
import tempfile
import threading
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad385 as p385  # noqa: E402
import shot_pad396 as p396  # noqa: E402

CARD = base.BATTLE + "/scene.radium"
OTHER = ("/godzilla_le/assets/lcd/auto_loaded/6bb2a76422a5f6a5c0354a79f19fc14ac4f6b2cb/"
         "c0a449da288e94a869f1c3e2cee7915d43b4de8b/scene.radium")


def _modal_shot(page, path, expand=False):
    modal = page.query_selector(".modal")
    if not modal:
        print("no dialog", flush=True)
        page.screenshot(path=path)
        return
    print("dialog:", modal.inner_text().replace("\n", " | "), flush=True)
    if expand:
        boxes = page.query_selector_all(".modal input[type=checkbox]")
        if boxes:
            boxes[0].click()                     # tick the first conflict: one replaced
            time.sleep(0.5)
    page.mouse.move(5, 990)
    page.screenshot(path=path)
    for name in ("Cancel", "No", "OK"):
        btn = page.query_selector('.modal .ft button:has-text("%s")' % name)
        if btn:
            btn.click()
            return


def scenes(repo, out):
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import scene_edit
    scratch = tempfile.mkdtemp(prefix="pad402s-")
    project = p385._project(scratch)
    # theirs: the battle scene's select box moved left, another scene's line moved, GIGAN -> GIGA
    save = os.path.join(scratch, "Battle from Sam.zip")
    with zipfile.ZipFile(save, "w") as z:
        z.writestr(scene_edit.SHARE_MANIFEST, json.dumps({
            "format": 1, "kind": scene_edit.SHARE_KIND,
            "scenes": {CARD: [{"op": "move", "node": 1043, "dx": -40, "dy": 0}],
                       OTHER: [{"op": "move", "node": 211, "dx": 0, "dy": 12}]},
            "pictures": {}, "added": {},
            "text": [{"path": CARD, "original": "GIGAN", "new": "GIGA", "near": None}]}))
    # mine: the same scene edited another way, GIGAN -> GIG
    scene_edit.save(project, {CARD: [{"op": "move", "node": 1043, "dx": 25, "dy": 0},
                                     {"op": "move", "node": 1039, "dx": 0, "dy": 8}]})
    rows = text_manifest.load(project)
    for r in rows:
        if r["path"] == CARD and r["original"] == "GIGAN":
            r["replacement"] = "GIG"
    text_manifest.save(project, rows)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "text")
            time.sleep(2)
            base._wait_scan(state, "images")
            base._wait_scan(state, "text")
            api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            time.sleep(6)
            t = threading.Thread(target=api, args=("text_scenes.edits_load", save), daemon=True)
            t.start()
            time.sleep(6)
            _modal_shot(page, out("scenes_load.png"), expand=True)
            t.join(60)
            browser.close()
    finally:
        proc.terminate()


def modes(repo, out):
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad402m-")
    friend = p396._project(scratch, "Sam GZ 1.16 Premium", p396.LE_CARD)
    mine = p396._project(scratch, "GZ 1.16 Premium", p396.LE_CARD)
    for project, shot, points in ((friend, "Left ramp", 900000), (mine, "Right ramp", 250000)):
        spec = MP.ModeSpec(name="KAIJU RUSH", title="godzilla_le_1_16")
        spec.start_shot, spec.start_count = shot, 2
        spec.scoring_shots = [shot]
        MP.new_mode(project, spec=spec)
    spec = MP.ModeSpec(name="MOTHRA HUNT", title="godzilla_le_1_16")
    spec.start_shot, spec.start_count = "Left ramp", 1
    MP.new_mode(friend, spec=spec)
    save = os.path.join(scratch, "Sam modes.zip")
    MP.export_modes(friend, save)
    proc, url = p396._serve(repo, scratch, mine, [mine])
    try:
        def load(page):
            threading.Thread(target=webui_shot.api, args=(url, "modes.load_file", save),
                             daemon=True).start()
            time.sleep(5)
            _modal_shot(page, out("modes_load.png"))
            time.sleep(2)
        p396.S._shoot(url, load, height=1000)
    finally:
        proc.terminate()


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    sys.path.insert(0, repo)
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    if "--modes" not in sys.argv:
        scenes(repo, out)
    if "--scenes" not in sys.argv:
        modes(repo, out)


if __name__ == "__main__":
    main()
