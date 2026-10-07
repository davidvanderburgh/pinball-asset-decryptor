"""PAD-429 proof shots: the Scenes and Text search boxes step through their matches.

    python scripts/shot_pad429.py <repo> <godzilla project> <out_dir> <before|after>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), types WORDS into the Scenes search box and into the Text tab's, and (after) presses
the search's Next button (PRESSES times on Scenes, twice on Text).  Writes
<prefix>_scenes.png and <prefix>_text.png.
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

WORDS = os.environ.get("PAD429_WORDS") or "TERROR"
#: Next presses on Scenes: the 5th TERROR match is the Godzilla Powerup choice scene
PRESSES = int(os.environ.get("PAD429_PRESSES") or 5)


def main():
    repo, source, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad429-")
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
    st = lambda ns: webui_shot.state(url)[ns]                # noqa: E731
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
            # --- Scenes
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: st("text_scenes").get("alive"), 30)
            rig._wait(lambda: not st("text_scenes").get("rebuilding"), 600)
            box = page.locator(".scenes-search input").first
            box.click()
            box.press_sequentially(WORDS, delay=120)
            time.sleep(1.5)
            if prefix == "after":
                for _ in range(PRESSES):
                    page.get_by_label("Next match").first.click()
                    time.sleep(0.8)
            rig._wait(lambda: st("text_scenes").get("frames"), 120)
            rig._wait(lambda: not st("text_scenes").get("tree_busy"), 60)
            s = st("text_scenes")
            print("scenes:", len(s["scenes"]), "sel", s["sel"], "find", s.get("find"),
                  "item", s.get("item"), "tree sel", (s.get("tree_view") or {}).get("sel"),
                  flush=True)
            page.mouse.move(5, 995)
            time.sleep(3)
            page.screenshot(path=os.path.join(out, "%s_scenes.png" % prefix))
            # --- Text
            page.locator(".rail").get_by_text("Text", exact=True).first.click()
            rig._wait(lambda: st("text").get("total"), 120)
            box = page.locator(".text-card .search input").first
            box.click()
            box.press_sequentially(WORDS, delay=120)
            box.press("Enter")
            time.sleep(1.5)
            if prefix == "after":
                for _ in range(2):
                    page.locator(".text-card").get_by_label("Next match").first.click()
                    time.sleep(0.8)
            t = st("text")
            print("text: shown", len(t["view"]), "sel", t.get("sel"), flush=True)
            page.mouse.move(5, 995)
            time.sleep(2)
            page.screenshot(path=os.path.join(out, "%s_text.png" % prefix))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
