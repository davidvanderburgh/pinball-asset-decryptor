"""PAD-1278 proof shots: an added picture in Scenes, animated (fade / pulse / flipbook).

    python scripts/shot_pad1278.py <repo> <project> <out_dir> <before|after>

*project* is a Stern project holding Godzilla's scenes (scene_tree.json; any extract of a
Godzilla card).  It is COPIED to a scratch folder first, so the real one is never touched.
On the copy, the Bounty scene (``aac1134f...``, 540 frames: "BOUNTY VALUE:" fading in) gets
an added "BOUNTY" picture; Scenes is opened on it with that picture picked.  With ``after``
the picture is given a fade like the game's own line and a pulse, and the panel's Animation
box is shown.  Writes ``<tag>_scenes_picture.png`` (the window) and
``<tag>_scenes_picture_panel.png`` (the right-hand panel, cropped).

Needs Playwright (the user site-packages one) and the installed Edge.
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
BOUNTY = ("/godzilla_pro/assets/lcd/auto_loaded/81c210aaf9d4bf5172a278644e7a1d3fe8ef1bf7/"
          "aac1134f04d1c7b5be51757c4e2dcada48d29f7c/scene.radium")
NID = 0x7F000001


def _picture(path, word="BOUNTY", hue=(255, 140, 0)):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGBA", (520, 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("arialbd.ttf", 72)
    except OSError:
        f = ImageFont.load_default()
    d.rounded_rectangle([2, 2, 517, 87], 18, fill=(40, 10, 0, 220), outline=hue + (255,), width=5)
    d.text((260, 46), word, font=f, fill=hue + (255,), anchor="mm")
    im.save(path)


def _project(scratch, source):
    dst = os.path.join(scratch, "Godzilla")
    shutil.copytree(source, dst)
    open(os.path.join(dst, ".checksums.md5"), "w").close()      # an extracted project
    added = os.path.join(dst, "images", "scene_textures", "added")
    os.makedirs(added, exist_ok=True)
    _picture(os.path.join(added, "bounty_1.png"))
    _picture(os.path.join(added, "bounty_2.png"), "BOUNTY!", (255, 220, 40))
    with open(os.path.join(dst, "images", "scene_textures", "scene_edits.json"), "w",
              encoding="utf-8") as f:
        json.dump({BOUNTY: [{"op": "add_picture", "parent": None, "index": 1 << 20, "id": NID,
                             "name": "PAD_bounty", "image": "scene_textures/added/bounty_1.png",
                             "w": 520, "h": 90, "x": 420, "y": 300}]}, f)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch1278.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def main():
    repo, source, out, tag = sys.argv[1:5]
    after = tag == "after"
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1278-")
    project = _project(scratch, source)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
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
            for ns in ("text_scenes", "scenes"):
                try:
                    api("ui.select_tab", ns)
                    break
                except Exception:                       # noqa: BLE001
                    continue
            time.sleep(4)
            print("select:", api("text_scenes.select", BOUNTY.rsplit("/", 1)[0]), flush=True)
            time.sleep(6)
            if after:
                line = None
                for n in (state().get("text_scenes") or {}).get("tree_view", {}).get(
                        "layers") or []:
                    if "Line1" in str(n.get("name")):
                        line = n.get("id")
                        break
                print("line1:", line, flush=True)
                print("anim:", api("text_scenes.tree_anim", NID,
                                   {"follow": line, "pulse": 0.4, "period": 30}), flush=True)
                time.sleep(3)
            api("text_scenes.tree_moment", "200")
            time.sleep(2)
            api("text_scenes.tree_select", NID)
            time.sleep(4)
            box = page.locator("#ts-anim")
            if after and box.count():
                box.first.scroll_into_view_if_needed()
                time.sleep(1)
            page.screenshot(path=os.path.join(out, tag + "_scenes_picture.png"))
            tv = (state().get("text_scenes") or {}).get("tree_view") or {}
            print("edits:", tv.get("edits"), "page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))
    shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
