"""PAD-1301 proof shots: a file of scene edits saved from a project of the card this project's
own edits were Written to (Kaiju Battle Select), loaded in Scenes.

    python scripts/shot_pad1301.py <repo> <project> <zip> <out.png>

*project* (COPIED to a scratch folder first) holds Godzilla's scenes and its own edits of the
Battle Select scene, added pictures among them; *zip* is the file.  Scenes is opened on the
scene, the file loaded (each question answered "load"), and the window shot.  Needs
Playwright (the user site-packages one) and the installed Edge.
"""
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad1278 as base  # noqa: E402

SCENE = "/godzilla_pro/assets/lcd/auto_loaded/cac32730af42b9d26d26c4bb6e667b07da53113e"


def main():
    repo, source, zp, out = sys.argv[1:5]
    scratch = tempfile.mkdtemp(prefix="pad1301-")
    project = os.path.join(scratch, "Godzilla")
    shutil.copytree(source, project)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            for ns in ("text_scenes", "scenes"):
                try:
                    api("ui.select_tab", ns)
                    break
                except Exception:                       # noqa: BLE001
                    continue
            time.sleep(4)
            api("text_scenes.select", SCENE)
            time.sleep(5)
            t = threading.Thread(target=api, args=("text_scenes.edits_load", zp), daemon=True)
            t.start()
            for _ in range(12):
                time.sleep(2)
                if not t.is_alive():
                    break
                btns = page.query_selector_all(".modal .ft button")
                if not btns:
                    continue
                texts = [b.inner_text() for b in btns]
                print("question:", texts, flush=True)
                pick = next((b for w in ("replace all", "yes", "ok") for b, s in zip(btns, texts)
                             if w in s.lower()), btns[-1])
                pick.click()
            t.join(60)
            for _ in range(3):
                btn = page.query_selector('.modal .ft button')
                if btn:
                    print("note:", btn.inner_text(), flush=True)
                    btn.click()
                    time.sleep(1)
            api("text_scenes.select", SCENE)
            time.sleep(6)
            cap = (state().get("text_scenes") or {}).get("caption_full")
            print("caption:", cap, flush=True)
            page.mouse.move(5, 990)
            page.screenshot(path=out)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    added = os.path.join(project, "images", "scene_textures", "added")
    print("added pictures now:", sorted(os.listdir(added)) if os.path.isdir(added) else [])
    shutil.rmtree(scratch, ignore_errors=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
