"""PAD-412 proof shot: a line of text sits in its box where the machine puts it.

    python scripts/shot_pad412.py <repo> <godzilla project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes on the Godzilla Powerup choice scene and selects the "START / TERROR OF /
+3 SECONDS" choice: three lines in a 300 px box the game centres them in (VerticalAlignment
middle).  The shot shows the box and where the words are drawn inside it.

A project whose scene_tree.json is older than the app's manifest is re-read from the card
first: set PAD251_CARD to the card it came from (Godzilla LE 1.16) and PAD412_TREE_V to the
manifest version to wait for (4).
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

SCENE = "/godzilla_le/assets/lcd/auto_loaded/c0a08ffdc93a1042a3361d9bd8e2e8c837d52a59"
LINE = "Choice_Instance"
WORDS = "START"


def _tree_v(path):
    import json
    try:
        trees = json.load(open(path, encoding="utf-8"))
        return int(next(iter(trees.values())).get("v") or 0)
    except Exception:                                   # noqa: BLE001
        return 0


def main():
    repo, source, out = sys.argv[1:4]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad412-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        if os.path.isdir(os.path.join(source, sub)):
            shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright
    print("repo", repo, flush=True)
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
            # a manifest older than the app's is re-read from the card first (PAD251_CARD =
            # the card the project came from); wait for the new one
            want = int(os.environ.get("PAD412_TREE_V", "0") or 0)
            tree = os.path.join(project, "images", "scene_textures", "scene_tree.json")
            if want:
                print("tree v", want, rig._wait(lambda: _tree_v(tree) >= want, 900, 2),
                      flush=True)
            rig._wait(lambda: not state().get("rebuilding"), 600)
            assert api("text_scenes.select", SCENE)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            layers = state()["tree_view"]["layers"]
            picked = None
            for l in [l for l in layers if l["name"] == LINE]:
                api("text_scenes.tree_select", l["id"])
                time.sleep(0.5)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                pr = state()["tree_view"]["props"]
                if WORDS in str(pr.get("text", "")):
                    picked = l["id"]
                    break
            print("picked", picked, flush=True)
            pr = state()["tree_view"]["props"]
            print("box:", pr["x"], pr["y"], pr["w"], pr["h"], flush=True)
            page.mouse.move(5, 995)
            time.sleep(3)
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
