"""PAD-352 proof shot: the Scenes preview's Machine screen leaves text alone.

    python scripts/shot_pad352.py <repo> <godzilla project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), leaves the Machine screen on its default (Recommended screen), opens Scenes on KAIJU
BATTLE SELECT and snaps the page to <out_png>.  Prints the title text's colour, read from
the preview frame the page shows.
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
from shot_pad339_scenes import SCENE, _frame  # noqa: E402


def main():
    repo, source, out = sys.argv[1:4]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad352-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
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
            frame = _frame(state())
            if frame:
                from PIL import Image
                im = Image.open(frame).convert("RGB")
                w, h = im.size
                # the title's letters: the brightest pixels across its band
                band = im.crop((int(w * 0.05), int(h * 0.04), int(w * 0.55), int(h * 0.12)))
                px = sorted(band.getdata(), key=sum)[-200:]
                print("title colour (top 200 mean):",
                      tuple(round(sum(c[i] for c in px) / len(px)) for i in range(3)),
                      flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
