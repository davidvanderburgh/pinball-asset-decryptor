"""PAD-452 round 2 proof shot: the Font bar's Style and Drop shadow sections, and the Selected
panel's one Font controls button.

    python scripts/shot_pad452b.py <repo> <godzilla project> <out_png> [new]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes on the language screen, selects its "Tokyo, Japan" line and opens the
Font bar.  With ``new`` (a build with round 2) the line is made Italic, its letters 85 %
wide, and given a drop shadow; without, the shot is the bar and the Selected panel as
round 1 left them.
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
    new = "new" in sys.argv[4:]
    print("repo:", repo, flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad452b-")
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
    idle = lambda: rig._wait(lambda: not state().get("tree_busy"), 60)  # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1150})
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
            idle()
            node = next(l["id"] for l in state()["tree_view"]["layers"] if l["name"] == LINE)
            api("text_scenes.tree_select", node)
            time.sleep(0.5)
            idle()
            if new:
                assert api("text_scenes.tree_text_italic", node, True)
                idle()
                assert api("text_scenes.tree_text_width", node, 85)
                idle()
                assert api("text_scenes.tree_shadow", node)
                idle()
                api("text_scenes.tree_select", node)          # the line again, not its shadow
                time.sleep(0.5)
                idle()
                font = state()["tree_view"]["props"]["font"]
                print("font:", {k: v for k, v in font.items() if k != "styles"}, flush=True)
                print("edits:", [l["edits"] for l in state()["tree_view"]["layers"]
                                 if l["id"] == node or l["name"].endswith("_Shadow")], flush=True)
            page.locator(".fnt-handle").click()
            time.sleep(1)
            # the Selected panel scrolled down to its last row (the text buttons)
            page.locator(".tree-side .tree-row").last.scroll_into_view_if_needed()
            page.mouse.move(5, 1145)
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
