"""PAD-366 proof shot: a long scene path folds inside the scene list's tooltip.

    python scripts/shot_pad366.py <repo> <godzilla project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the
real one), opens Scenes, hovers the first scene-list row whose path is a demand_loaded
hash chain (the longest kind: /<game>/assets/lcd/demand_loaded/<40 hex>/<40 hex>) and
snaps the page with the tooltip up.  Prints the tooltip box's width against its text's
scroll width: before the fix the text runs past the box.
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


def main():
    repo, source, out = sys.argv[1:4]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad366-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    print("repo", repo, "scratch project", project, flush=True)
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
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state().get("alive"), 30)
            rig._wait(lambda: state().get("scenes"), 60)
            # the list is sorted by name; put the demand_loaded scenes at the top
            api("text_scenes.set_search", "demand_loaded")
            time.sleep(2)
            rows = [r for r in (state().get("scenes") or []) if "demand_loaded" in r.get("d", "")]
            print("demand_loaded rows:", len(rows), flush=True)
            cell = page.locator('.scenes-list .c[title*="demand_loaded"]').first
            cell.wait_for(timeout=30000)
            box = cell.bounding_box()
            page.mouse.move(box["x"] + 60, box["y"] + box["height"] / 2)
            time.sleep(1.5)
            tipbox = page.evaluate(
                "() => { const t = document.querySelector('.tip'); if (!t) return null;"
                " return { text: t.textContent, width: t.offsetWidth, scroll: t.scrollWidth,"
                " height: t.offsetHeight, right: t.getBoundingClientRect().right }; }")
            print("tip:", tipbox, flush=True)
            page.screenshot(path=out)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("scratch", scratch)


if __name__ == "__main__":
    main()
