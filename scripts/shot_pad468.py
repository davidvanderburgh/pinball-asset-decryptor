"""PAD-468 proof shot: every line of text in the scenes, one after another, fixed in place.

    python scripts/shot_pad468.py <repo> <godzilla project> <out_png> [words]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes with the search box empty, picks the language screen's "Tokyo, Japan"
line and prints what the search row and the Selected panel offer.  With ``words`` (a build
that has the Words box) the line's words are typed into it and applied, then Next line is
pressed and Previous line brings it back, so the shot shows the fixed line in the preview
with its place in the walk ("n of N").
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
NEW_WORDS = os.environ.get("PAD468_WORDS") or "Osaka, Japan"


def main():
    repo, source, out = sys.argv[1:4]
    words = "words" in sys.argv[4:]
    print("repo:", repo, flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad468-")
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

            def settle():
                time.sleep(0.6)
                rig._wait(lambda: not state().get("tree_busy"), 60)

            api("text_scenes.tree_select", node)
            settle()
            if words:
                box = page.locator(".tree-words input").first
                box.click()
                box.fill(NEW_WORDS)
                box.press("Enter")
                settle()
                print("words:", (state()["tree_view"]["props"] or {}).get("words"), flush=True)
                page.get_by_label("Next line").first.click()
                settle()
                print("next:", state().get("sel"), (state()["tree_view"]["props"] or {}).get("name"),
                      state().get("find"), flush=True)
                page.get_by_label("Previous line").first.click()
                settle()
            s = state()
            print("search:", repr(s.get("search")), "find:", s.get("find"), flush=True)
            print("selected:", (s["tree_view"]["props"] or {}).get("name"), flush=True)
            print("arrows by the search:", page.locator(".scenes-search").get_by_label(
                "Next match").count(), flush=True)
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
