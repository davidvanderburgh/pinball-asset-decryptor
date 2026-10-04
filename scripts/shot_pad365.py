"""PAD-365 proof shots: exporting a scene, and every listed scene, as a video.

    python scripts/shot_pad365.py <repo> <project> <out_dir> <prefix> [search]

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig
selects and exports, never edits), opens Scenes on Godzilla's credits scene (120 frames),
narrows the list with <search> (default "credits") and writes:

- <prefix>_scenes_export.png       the Scenes page as it opens: the export buttons in the head
- <prefix>_scenes_export_done.png  after "Export all videos…" (or, on a build without it,
                                   "Export all pictures…") ran into a scratch folder: the
                                   caption under the preview says what was written
- <prefix>_notes.txt               what landed in the scratch folder
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402
from shot_pad261 import CREDITS  # noqa: E402


def main():
    repo, project, out, prefix = sys.argv[1:5]
    search = sys.argv[5] if len(sys.argv) > 5 else "credits"
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad365-")
    dest = os.path.join(scratch, "exported")
    os.makedirs(dest)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = ["code: %s" % repo]
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
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", CREDITS)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 60)
            if search:
                api("text_scenes.set_search", search)
                time.sleep(0.5)
            listed = len(state()["text_scenes"].get("scenes") or [])
            notes.append("listed scenes (search %r): %d" % (search, listed))
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out, "%s_scenes_export.png" % prefix))
            videos = page.get_by_role("button", name="Export all videos…")
            if videos.count():
                button, label = videos.first, "Export all videos…"
            else:
                button, label = page.get_by_role(
                    "button", name="Export all pictures…").first, "Export all pictures…"
            notes.append("pressed: %s" % label)
            button.click()
            # the page's own folder browser: type the scratch folder, Enter, Choose
            modal = page.locator(".modal")
            modal.wait_for(timeout=10000)
            field = modal.locator("input").first
            field.fill(dest)
            field.press("Enter")
            time.sleep(0.5)
            modal.get_by_role("button", name="Choose this folder").click()
            t0 = time.time()
            rig._wait(lambda: (state()["text_scenes"].get("caption") or "").startswith(
                ("Saved", "Could not", "Stopped")), 900, 0.5)
            took = time.time() - t0
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out, "%s_scenes_export_done.png" % prefix))
            notes.append("caption: %s" % state()["text_scenes"].get("caption"))
            notes.append("took %.1f s" % took)
            files = sorted(os.listdir(dest))
            notes.append("written: %s" % ", ".join(
                "%s (%d KB)" % (f, os.path.getsize(os.path.join(dest, f)) // 1024)
                for f in files))
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    with open(os.path.join(out, prefix + "_notes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))


if __name__ == "__main__":
    main()
