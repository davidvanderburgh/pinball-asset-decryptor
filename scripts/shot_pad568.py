"""PAD-568 proof shots: No change on a line of text in a font with colours of its own.

    python scripts/shot_pad568.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project set up as DragonRR had it: the
individual files profile Black and white, the game's own pictures unlocked with
GameFont_Secondary's three font pictures switched on (so every orange title line is drawn
B&W through its font), and the JET FIGHTER COLLECTED! line (scene 017aa70d, node 309)
switched on with No change as its own profile.  Under the same names before and after:

- line_no_change.png    That line selected, the Colors bar open on it.  Before: grey, as the
                        font's pictures make it.  After: the game's own orange.
- apply_all_confirm.png Apply to all lines of text with No change: the question.  Before: the
                        lines in that font are left out.  After: they are counted in.
- apply_all_done.png    Answered Yes, JET FIGHTER DESTROYED! (scene a137a54d, node 319), a
                        line nobody touched by hand.  Before: still grey.  After: orange.

Needs Playwright (the user site-packages one).
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

ROOT = "/godzilla_le/assets/lcd/auto_loaded/9fb470d4e77248ffd13c7830adfe66fdea70ed87/"
SCENE = ROOT + "017aa70dbac986280b47795bc96305b155aed375/scene.radium"
LINE = 309
OTHER = ROOT + "a137a54dd29cb6c778b5368165a974b88d9c7d4e/scene.radium"
OTHER_LINE = 319
FONT_PICS = ("scene_textures/radimg_GameFont_Secondary_512x512_115d03b4.png",
             "scene_textures/radimg_512x512_1a9486f2.png",
             "scene_textures/radimg_512x512_9d77fb3f.png")


def _setup(project):
    from pinball_decryptor.core import colour_profile as cp
    side = os.path.join(project, ".staged_changes.json")
    try:
        with open(side, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data[cp.ASSET_KEY] = cp._profile_dict(cp.Profile(name="Black and white", saturation=0.0))
    data[cp.STOCK_IMAGES_KEY] = True
    slots = dict(data.get(cp.IMAGE_SLOTS_KEY) or {})
    slots.update({"images/" + r: True for r in FONT_PICS})
    data[cp.IMAGE_SLOTS_KEY] = slots
    rel = cp.text_rel(SCENE, LINE)
    data[cp.TEXT_SLOTS_KEY] = {rel: True}
    data[cp.FILE_PROFILES_KEY["text"]] = {rel: cp._profile_dict(cp.Profile(name="No change"))}
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad568-")
    project = base._project(scratch)
    _setup(project)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright

    def settle(page, wait=1.5):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                               # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 1100)
        time.sleep(wait)

    def pick(card, node):
        where = card[:-len("/scene.radium")]
        api("text_scenes.select", where) or api("text_scenes.select", card)
        time.sleep(8)
        tv = (state().get("text_scenes") or {}).get("tree_view") or {}
        for l in tv.get("layers") or []:
            if (l.get("color") or {}).get("line"):
                print(" ", l["id"], l["name"], l.get("text"),
                      {k: v for k, v in l["color"].items() if k != "font_pictures"},
                      flush=True)
        print("selected:", api("text_scenes.tree_select", node), flush=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1150})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            assert api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            pick(SCENE, LINE)
            time.sleep(4)
            handle = page.query_selector("button.cpd-handle[aria-label='Color profiles']")
            if handle:
                handle.click()
                time.sleep(3)
            print("color file:", (state().get("color") or {}).get("file"), flush=True)
            settle(page, 3)
            page.screenshot(path=out("line_no_change.png"))

            btn = page.query_selector(
                ".cpd-file-all button:has-text('Apply to all lines of text')")
            print("apply to all lines button:", bool(btn), flush=True)
            if btn:
                btn.click()
                time.sleep(2)
                page.screenshot(path=out("apply_all_confirm.png"))
                page.click(".modal button:has-text('Yes')")
                time.sleep(8)
            if handle:
                handle.click()
                time.sleep(2)
            pick(OTHER, OTHER_LINE)
            time.sleep(4)
            settle(page, 3)
            page.screenshot(path=out("apply_all_done.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
