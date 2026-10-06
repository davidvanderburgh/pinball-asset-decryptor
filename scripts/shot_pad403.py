"""PAD-403 proof shot: a scene save loaded into the project of the card built from it.

    python scripts/shot_pad403.py <repo> <out_dir> <save.zip> [--after]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot).  The Godzilla project shot_pad312 copies stands in for the card built from
<save.zip>: its battle-intro scene (``e19f1b5f``) gets the file's edits put into its tree, as
a Write puts them on the card and an Extract reads them back.  Scenes > Load from a file...
then loads <save.zip> into it (DragonRR's FOR THE SHOW V1.zip: a title moved, resized and
re-boxed) and the title is photographed selected:

- scene_title.png  before: drawn with the file's edits twice (moved right, grown); after: once,
                   where the card has it, and the load says the scene already had them
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

CARD = ("/godzilla_le/assets/lcd/auto_loaded/c65ecc5e2f5769bdc59851eb951a1c781b53deb8/"
        "e19f1b5fd7a3ca41e2945839f4d35bb5bd6ab597/scene.radium")
TITLE = 321


def main():
    repo, out_dir, save = (os.path.abspath(a) for a in sys.argv[1:4])
    after = "--after" in sys.argv
    sys.path.insert(0, repo)
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    from pinball_decryptor.plugins.stern import scene_edit
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, ("after_" if after else "before_") + "scene_title.png")
    with zipfile.ZipFile(save) as z:
        scenes = json.loads(z.read(scene_edit.SHARE_MANIFEST))["scenes"]
    ops = [v for c, v in scenes.items() if c.split("/")[-2] == CARD.split("/")[-2]][0]
    scratch = tempfile.mkdtemp(prefix="pad403-")
    project = p385._project(scratch)
    # the card built from the file: its scene already shows the file's edits
    tp = os.path.join(project, *scene_edit.RELDIR, "scene_tree.json")
    with open(tp, encoding="utf-8") as f:
        trees = json.load(f)
    trees[CARD], notes = scene_edit.apply_manifest(trees[CARD], ops)
    assert not notes, notes
    with open(tp, "w", encoding="utf-8") as f:
        json.dump(trees, f, separators=(",", ":"))
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
            api("text_scenes.select", CARD.rsplit("/", 1)[0])
            time.sleep(4)
            t = threading.Thread(target=api, args=("text_scenes.edits_load", save), daemon=True)
            t.start()
            time.sleep(8)
            for name in ("OK", "Close"):             # a "left out" note, if any
                btn = page.query_selector('.modal .ft button:has-text("%s")' % name)
                if btn:
                    btn.click()
            t.join(60)
            api("text_scenes.select", CARD.rsplit("/", 1)[0])
            time.sleep(4)
            api("text_scenes.tree_moment", 120)
            time.sleep(2)
            api("text_scenes.tree_select", TITLE)
            time.sleep(3)
            page.mouse.move(5, 990)
            page.screenshot(path=out)
            browser.close()
    finally:
        proc.terminate()
    print("wrote", out)


if __name__ == "__main__":
    main()
