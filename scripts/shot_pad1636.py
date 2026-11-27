"""PAD-1636 (PR #52) proof shots: the Test card tab's lists and the Scenes tab's layered tests.

    python scripts/shot_pad1636.py <repo to run> <project> <out dir> --prefix before|after

Serves <repo> on scratch settings (Stern picked) with a scratch copy of <project> (an extract with scenes: its
images, text and spine, and four of its videos; never the project itself, whose caches a server rewrites) and a
scratch test card list: a picture, a video, a scene and two layered tests over the project's videos.  Shoots

* <prefix>_testcard.png - the Test card tab's "On the card" lists;
* <prefix>_scenes.png   - the Scenes tab, a scene picked (the PR: the Layered tests list under the scene list);
* <prefix>_layered_dialog.png - the layered test dialog (main: Layered test… with that scene; the PR: Edit on
  the first layered test).

Nothing is built and nothing talks to a machine.
"""
import json
import os
import shutil
import site
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

W, H = 1600, 1000
SKIP = ("audio", "build", "logs", "modes", "video", ".write_cache", ".hashcache.json")
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _project(src, scratch):
    dst = os.path.join(scratch, "project")
    shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if d == src and n in SKIP])
    vids = []
    for root, _dirs, files in os.walk(os.path.join(src, "video")):
        for f in files:
            if f.lower().endswith((".mp4", ".mov")):
                vids.append((os.path.getsize(os.path.join(root, f)), f))
    os.makedirs(os.path.join(dst, "video"))
    picked = [f for _s, f in sorted(vids)[10:14]]
    for f in picked:
        shutil.copy2(os.path.join(src, "video", f), os.path.join(dst, "video", f))
    return dst, picked


def _scenes(project):
    with open(os.path.join(project, "images", "scene_textures", "scene_tree.json"), encoding="utf-8") as f:
        tree = json.load(f)
    return sorted(os.path.dirname(k) for k in tree)


def _list(scratch, project, clips):
    from PIL import Image
    pic = os.path.join(scratch, "my_picture.png")
    Image.new("RGB", (1360, 768), (200, 40, 40)).save(pic)
    dirs = _scenes(project)
    game = os.path.basename(project)
    rel = lambda f: "video/" + f                                    # noqa: E731
    items = [
        {"kind": "image", "label": "Red screen", "path": pic},
        {"kind": "video", "label": clips[0].rsplit(".", 1)[0], "path": os.path.join(project, "video", clips[0]),
         "project": project, "rel": rel(clips[0]), "game": game},
        {"kind": "scene", "label": "A scene", "project": project, "rel": dirs[2], "game": game},
        {"kind": "video", "label": "Score panel over " + clips[1].rsplit(".", 1)[0],
         "path": os.path.join(project, "video", clips[1]), "project": project, "rel": rel(clips[1]), "game": game,
         "layers": [os.path.basename(dirs[0]), os.path.basename(dirs[1]) + "@0"]},
        {"kind": "video", "label": "Two scenes over " + clips[2].rsplit(".", 1)[0],
         "path": os.path.join(project, "video", clips[2]), "project": project, "rel": rel(clips[2]), "game": game,
         "layers": [os.path.basename(dirs[3]), os.path.basename(dirs[4])]},
    ]
    store = os.path.join(scratch, "testcard.json")
    with open(store, "w", encoding="utf-8") as f:
        json.dump({"items": items, "source": "", "out": "", "network": {}}, f, indent=1)
    return store, dirs


def main():
    repo, src, out = (os.path.abspath(a) for a in sys.argv[1:4])
    prefix = sys.argv[sys.argv.index("--prefix") + 1] if "--prefix" in sys.argv else "after"
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1636-")
    project, clips = _project(src, scratch)
    store, dirs = _list(scratch, project, clips)
    launcher = os.path.join(scratch, "launch.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD_TESTCARD_STORE": store, "PAD_UI_NO_RIG": "1"})
    api = lambda m, *a: webui_shot.api(url, m, *a)                  # noqa: E731
    from playwright.sync_api import sync_playwright
    shot = lambda page, name: page.screenshot(path=os.path.join(out, "%s_%s.png" % (prefix, name)))  # noqa: E731
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": W, "height": H})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0');"
                                 " localStorage.setItem('pad.colorbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "testcard")
            time.sleep(4)
            page.mouse.move(5, 5)
            shot(page, "testcard")
            api("ui.select_tab", "scenes")
            time.sleep(4)
            api("text_scenes.select", dirs[0])
            time.sleep(10)
            page.mouse.move(5, 5)
            shot(page, "scenes")
            edit = page.locator(".lt-test button", has_text="Edit")
            if edit.count():
                edit.first.click()
            else:
                page.get_by_role("button", name="Layered test…").first.click()
            time.sleep(10)                                          # the dialog reads the project, thumbnails
            page.mouse.move(5, 5)
            shot(page, "layered_dialog")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
    print("shots in", out, "server log", os.path.join(scratch, "server.log"), flush=True)


if __name__ == "__main__":
    main()
