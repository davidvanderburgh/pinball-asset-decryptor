"""PAD-351 proof shots: a new pick on a picture an earlier build grew keeps its own size.

    python scripts/shot_pad351.py <repo> <out_dir> <prefix>

Same scratch Godzilla project as shot_pad312.  Before the app starts, Battle Select's
kaiju grid is left the way DragonRR's earlier build left it: grown to 544x840 in the
project folder, Stern's 444x740 picture in .orig/, the sidecar naming it.  The app's file
dialog is replaced by one that answers with a new 544x840 grid picture, the grid is picked
again on the Images tab, and two shots are written:

- <prefix>_images.png  the Images tab on the grid, its Keep size row under the preview
- <prefix>_scenes.png  the Scenes tab on Battle Select, drawing the new pick

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

GRID = "images/scene_textures/radimg_unnamed_instance_26_444x740_0d6857fd.png"

LAUNCHER = r'''
import os, sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import compat
compat.filedialog.askopenfilename = lambda **kw: os.environ["PAD351_PICK"]
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _grid_art(src, size, tint):
    """The stock grid, grown and tinted so the shot reads as the user's own picture."""
    from PIL import Image, ImageOps
    im = Image.open(src).convert("RGBA").resize(size, Image.LANCZOS)
    a = im.getchannel("A")
    rgb = ImageOps.colorize(ImageOps.grayscale(im), (10, 10, 30), tint)
    rgb.putalpha(a)
    return rgb


def _built(project, scratch, repo):
    sys.path.insert(0, repo)
    from pinball_decryptor.core import staged_changes, staged_originals
    path = os.path.join(project, *GRID.split("/"))
    staged_originals.snapshot(project, GRID, None)
    _grid_art(path, (544, 840), (240, 240, 255)).save(path)
    data = staged_changes.load(project)
    names = dict(data.get("replacement_names") or {})
    names[GRID] = "Battle Select Screen Grey V7wb.png"
    data["replacement_names"] = names
    staged_changes.save(project, data)
    pick = os.path.join(scratch, "Battle Select Screen Grey V7wb NEW AMPED.png")
    _grid_art(os.path.join(project, ".orig", *GRID.split("/")), (544, 840),
              (255, 220, 160)).save(pick)
    return pick


def _serve(repo, scratch, project, pick):
    import json
    import site
    launcher = os.path.join(scratch, "launch351.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD351_PICK": pick})


def main():
    repo, out_dir, prefix = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad351-")
    project = base._project(scratch)
    pick = _built(project, scratch, repo)
    proc, url = _serve(repo, scratch, project, pick)
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
            api("ui.set", "images", "search", "444x740")
            time.sleep(4)
            api("images.select", GRID)
            time.sleep(2)
            print("choose:", api("images.choose", GRID), flush=True)
            time.sleep(3)
            page.screenshot(path=os.path.join(out_dir, prefix + "_images.png"))
            api("images.open_scenes", GRID)
            time.sleep(12)
            page.screenshot(path=os.path.join(out_dir, prefix + "_scenes.png"))
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
