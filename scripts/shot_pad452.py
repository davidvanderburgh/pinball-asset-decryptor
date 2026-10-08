"""PAD-452 proof shot: a line of text's font, size and spacing on the Scenes tab's Font bar.

    python scripts/shot_pad452.py <repo> <godzilla project> <out_png> [font]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes on the language screen and selects its "Tokyo, Japan" line.  With ``font``
(a build that has the Font bar) the bar is opened and the line is set in the scene's other
font at 72 px, its letters 6 px further apart; without, the shot is the line as shipped, with
the Selected panel as it was.
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

SCENE = "/godzilla_le/assets/lcd/demand_loaded/762a9b99fc0c933b6c6c4822cb48911fa92bbd97"
LINE = "Line1_Instance"


def main():
    repo, source, out = sys.argv[1:4]
    font = "font" in sys.argv[4:]
    print("repo:", repo, flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad452-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        if os.path.isdir(os.path.join(source, sub)):
            shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json", "scene_edits_carried.json"):
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
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
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
            if font:
                print("font:", {k: v for k, v in pr["font"].items() if k != "styles"}, flush=True)
                assert api("text_scenes.tree_text_font", node, "GameFont_Secondary")
                rig._wait(lambda: not state().get("tree_busy"), 60)
                assert api("text_scenes.tree_text_size", node, 72)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                assert api("text_scenes.tree_text_spacing", node, 6, None)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                pr = pick()
                print("box:", pr["x"], pr["y"], pr["w"], pr["h"], flush=True)
                print("font:", {k: v for k, v in pr["font"].items() if k != "styles"}, flush=True)
                print("edits:", [l["edits"] for l in state()["tree_view"]["layers"]
                                 if l["id"] == node], flush=True)
                page.locator(".fnt-handle").click()
            # the Selected panel scrolled down to its text buttons
            page.locator(".tree-side").get_by_text("Fit box to text").first                 .scroll_into_view_if_needed()
            page.mouse.move(5, 995)
            time.sleep(3)
            page.screenshot(path=out)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
