"""PAD-417 proof shot: the pictures a loaded scene file copies into the project's
"Shared pictures" folder are the user's picks, not slots the card is missing.

    python scripts/shot_pad417.py <repo> <out_png>

Same scratch Godzilla project as shot_pad312.  Before the app starts a scene file's
load is laid down the way scene_share.import_extras leaves it: a portrait copied into
``Shared pictures/FOR THE SHOW V3/`` and picked for the 530x726 Battle Select portrait.
The Images tab is shot on "Shared pictures": before, the copy lists as a row of its own
flagged "not on this card"; after, it is not listed (the slot it replaces still is).
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

SHARED = "Shared pictures/FOR THE SHOW V3/radimg_530x726_10a34f06.png"


def _shared(project):
    from PIL import Image, ImageDraw
    path = os.path.join(project, *SHARED.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = Image.new("RGBA", (632, 828), (20, 40, 90, 255))
    d = ImageDraw.Draw(im)
    for i in range(12):
        d.ellipse([40 + i * 30, 60 + i * 40, 240 + i * 25, 260 + i * 40],
                  fill=(200, 150 + i * 8, 40, 255))
    im.save(path)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    data["image"] = {base.PORTRAIT: path}
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    repo, out_png = sys.argv[1:3]
    print("repo:", repo, flush=True)
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad417-")
    project = base._project(scratch)
    _shared(project)
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
            time.sleep(6)                    # the change scan marks the foreign rows
            api("ui.set", "images", "search", "530x726")
            time.sleep(4)
            st = state().get("images") or {}
            print("total:", st.get("total"), flush=True)
            if not api("images.select", SHARED):
                api("images.select", base.PORTRAIT)
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
