"""PAD-433 proof shot: a line of text's box set taller, and where its words sit in it.

    python scripts/shot_pad433.py <repo> <godzilla project> <out_png> [middle]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes on the Gigan battle intro, selects its "BATTLE FOR TOKYO" line
(Line1_Instance) and makes its box 160 px taller, as DragonRR did.  With ``middle`` (a build
that has the alignment buttons) the line is then set to the middle of its box.
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

SCENE = ("/godzilla_le/assets/lcd/auto_loaded/a248977badd032e625ee2480e8cc6d0b2f645d1f/"
         "e5793bce06a18e840f98aca8e14dbdbd0547ab60")
LINE = "Line1_Instance"


def main():
    repo, source, out = sys.argv[1:4]
    middle = "middle" in sys.argv[4:]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad433-")
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
            rig._wait(lambda: not state().get("rebuilding"), 600)
            assert rig._wait(lambda: api("text_scenes.select", SCENE), 120, 1)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            node = next(l["id"] for l in state()["tree_view"]["layers"] if l["name"] == LINE)

            def pick():
                api("text_scenes.tree_select", node)
                time.sleep(0.5)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                return state()["tree_view"]["props"]
            pr = pick()
            print("box:", pr["x"], pr["y"], pr["w"], pr["h"], flush=True)
            api("text_scenes.tree_set_box", node, pr["x"], pr["y"], pr["w"], pr["h"] + 160)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            if middle:
                api("text_scenes.tree_text_align", node, None, "middle")
                rig._wait(lambda: not state().get("tree_busy"), 60)
            pr = pick()
            print("box:", pr["x"], pr["y"], pr["w"], pr["h"], pr.get("valign"), flush=True)
            # the Selected panel scrolled down to its text buttons
            page.get_by_text("Fit box to text").first.scroll_into_view_if_needed()
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
