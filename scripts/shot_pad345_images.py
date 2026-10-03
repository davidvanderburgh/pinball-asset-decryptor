"""PAD-345 proof shot: a picture an earlier build replaced, its pick gone ("changed on
disk (name)"), is the user's own on the Images tab, not a locked game picture.

    python scripts/shot_pad345_images.py <repo> <out_png>

Same scratch Godzilla project as shot_pad312.  Before the app starts a second Battle
Select portrait is left the way a build with its pick since cleared leaves it: Stern's
bytes in .orig/, the user's picture in the project folder, the sidecar naming it.  The
Color profile tab goes on "Adjust individual files"; the Images tab is shot on the
530x726 portraits with that row selected.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

BUILT = "images/scene_textures/radimg_530x726_9cebb09d.png"


def _built(project, repo):
    sys.path.insert(0, repo)
    from PIL import Image, ImageDraw
    from pinball_decryptor.core import staged_changes, staged_originals
    staged_originals.snapshot(project, BUILT, None)
    path = os.path.join(project, *BUILT.split("/"))
    im = Image.new("RGBA", (530, 726), (20, 40, 90, 255))
    d = ImageDraw.Draw(im)
    for i in range(12):
        d.ellipse([40 + i * 30, 60 + i * 40, 240 + i * 20, 260 + i * 35],
                  fill=(80 + i * 14, 120, 220 - i * 10, 255))
    im.save(path)
    data = staged_changes.load(project)
    names = dict(data.get("replacement_names") or {})
    names[BUILT] = "Biollante PORTRAIT FIXED v7w.png"
    data["replacement_names"] = names
    staged_changes.save(project, data)


def main():
    repo, out_png = sys.argv[1:3]
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad345i-")
    project = base._project(scratch)
    _built(project, repo)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
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
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "assets")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(1)
            api("ui.set", "images", "search", "530x726")
            time.sleep(4)
            api("images.select", BUILT)
            time.sleep(3)
            page.screenshot(path=out_png)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
