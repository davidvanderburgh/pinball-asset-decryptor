"""PAD-383 round 2 proof shot: a three-line title replaced with one line, box fitted.

    python scripts/shot_pad383.py <repo> <godzilla project> <out_png> [--fit]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes on the jackpot-meter scene DragonRR sent (its title line's box runs off
the screen), selects that title line and snaps the page to <out_png>.  With --fit it then
presses "Fit box to text" first.  Prints the line's X, Y, W, H before and after.
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

SCENE = ("/godzilla_le/assets/lcd/auto_loaded/c65ecc5e2f5769bdc59851eb951a1c781b53deb8/"
         "e19f1b5fd7a3ca41e2945839f4d35bb5bd6ab597")
LINE = "Title_Instance"
WORDS = "GODZILLA AND JET JAGUAR VS. MEGALON AND GIGAN"


def main():
    repo, source, out = sys.argv[1:4]
    fit = "--fit" in sys.argv[4:]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad383-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    # DragonRR's edit: a shorter title in the same box
    tsv = os.path.join(project, "text", "strings.tsv")
    with open(tsv, encoding="utf-8") as f:
        rows = f.read().split("\n")
    rows = [r + "GODZILLA VS. GIGAN" if r.startswith(SCENE) and
            r.endswith("\t" + WORDS + "\t") else r for r in rows]
    with open(tsv, "w", encoding="utf-8") as f:
        f.write("\n".join(rows))
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
            # the scene's own title line (the last one of that name: not inside a meter)
            node = [l for l in layers if l["name"] == LINE][-1]["id"]
            api("text_scenes.tree_select", node)
            time.sleep(1)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            pass      # moved right, as DragonRR had it
            time.sleep(1)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            pr = state()["tree_view"]["props"]
            print("before:", pr["x"], pr["y"], pr["w"], pr["h"], flush=True)
            if fit:
                page.get_by_text("Fit box to text", exact=True).click()
                time.sleep(1)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                pr = state()["tree_view"]["props"]
                print("after:", pr["x"], pr["y"], pr["w"], pr["h"], flush=True)
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
