"""PAD-339 end-to-end proof: the Scenes preview draws through the Machine screen's colour
ranges and curves, on a real Godzilla scene.

    python scripts/shot_pad339_scenes.py <repo> <godzilla project> <out_dir>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), stores a Machine screen with no ranges or curves, opens Scenes on KAIJU BATTLE SELECT
and snaps <out_dir>/scenes_plain.png.  Then, through the Color profile tab's own calls,
adds a cyan-blue sea range and a master curve that darkens the dark greys, goes back to
Scenes and snaps <out_dir>/scenes_ranges.png.  Prints the preview frame's sea and grey
pixels from both, read from the frame files the page shows.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

SCENE = "/godzilla_le/assets/lcd/auto_loaded/cac32730af42b9d26d26c4bb6e667b07da53113e"
SCREEN = {"name": "My screen", "gamma": [0.91, 0.83, 0.74], "gain": [1.0, 1.0, 1.0],
          "lift": [0.0, 0.0, 0.0], "saturation": 1.11}
RANGES = [[195, 50, 35, 14, 0.75, 0.85, 0.15]]
CURVES = {"rgb": [[0, 0], [48, 30], [128, 122], [255, 255]]}


def _frame(state):
    """The newest preview frame file the page was handed."""
    for key in ("frames", "srcs"):
        v = state.get(key)
        if isinstance(v, list) and v and isinstance(v[-1], str) and os.path.isfile(v[-1]):
            return v[-1]
    return ""


def main():
    repo, source, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad339s-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"screen_profile": SCREEN}, f)
    print("scratch project", project, flush=True)
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
            assert api("text_scenes.select", SCENE)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            time.sleep(4)
            print("state keys:", sorted(state().keys()), flush=True)
            page.screenshot(path=os.path.join(out, "scenes_plain.png"))
            first = _frame(state())
            if first:
                shutil.copy(first, os.path.join(scratch, "plain_frame.png"))
            # the Color profile tab's own calls, as the page makes them
            api("ui.select_tab", "color")
            time.sleep(1.5)
            assert api("color.set_mode", "screen") == "screen"
            assert api("color.set_params", {"ranges": RANGES, "curves": CURVES})
            time.sleep(1)
            print("stored:", json.load(open(os.path.join(project, ".staged_changes.json"),
                                            encoding="utf-8"))["screen_profile"], flush=True)
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            time.sleep(2)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            time.sleep(5)
            page.screenshot(path=os.path.join(out, "scenes_ranges.png"))
            second = _frame(state())
            if first and second:
                from PIL import Image
                a = Image.open(os.path.join(scratch, "plain_frame.png")).convert("RGB")
                b = Image.open(second).convert("RGB")
                print("frame size", a.size, b.size, flush=True)
                for name, xy in (("sea", (0.08, 0.35)), ("sea2", (0.90, 0.22)),
                                 ("frame", (0.02, 0.97))):
                    pt = (int(xy[0] * a.size[0]), int(xy[1] * a.size[1]))
                    print(name, pt, a.getpixel(pt), "->", b.getpixel(pt), flush=True)
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
