"""PAD-382 proof shot: a Text-tab edit of a scene line with line breaks shows in Scenes.

    python scripts/shot_pad382.py <repo> <godzilla LE project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), applies DragonRR's edit there (MEGALON -> SPACEGODZILLA on the versus card's title),
opens Scenes on that card and snaps the page to <out_png>.
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
ORIGINAL = "GODZILLA AND JET JAGUAR VS. MEGALON AND GIGAN"
NEW = "GODZILLA AND JET JAGUAR VS. SPACEGODZILLA AND GIGAN"


def main():
    repo, source, out = sys.argv[1:4]
    print("repo:", repo, flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad382-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    sys.path.insert(0, repo)
    from pinball_decryptor.core import text_manifest
    rows = text_manifest.load(project)
    hit = [r for r in rows if r["path"] == SCENE + "/scene.radium" and r["original"] == ORIGINAL]
    assert len(hit) == 1, hit
    hit[0]["replacement"] = NEW
    text_manifest.save(project, rows)
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
            time.sleep(4)
            page.screenshot(path=out)
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
