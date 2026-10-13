"""PAD-557 proof shots: a picture resized on Scenes keeps its X and Y.

    python scripts/shot_pad557.py <repo> <godzilla LE project> <out_dir> [--after]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one, its scene edits are dropped), opens Scenes on KAIJU BATTLE SELECT, selects a kaiju's
body picture and sets its Size % to 60 in the inspector, then takes, under the same names
before and after:

- resize.png  The preview and the Selected panel after the resize.  Before: the picture
              shrank toward its middle, so X and Y changed.  After: its top-left corner (X, Y)
              stayed put, and the new "Resize from" switch shows Top-left picked.
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
from shot_pad339_scenes import SCENE  # noqa: E402

PIC = "unnamed_instance"


def main():
    repo, source, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad557-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    print("serving", repo, flush=True)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
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
            pick = None
            for l in state()["tree_view"]["layers"]:
                if not l["name"].startswith(PIC):
                    continue
                api("text_scenes.tree_select", l["id"])
                time.sleep(0.5)
                pr = state()["tree_view"].get("props") or {}
                if (pr.get("pic") and pr.get("x") is not None and not pr.get("peek")
                        and pr["x"] >= 0 and pr["y"] >= 0 and 150 < pr["w"] < 700):
                    pick = pr
                    break
            assert pick, "no body picture on the glass"
            print("picked", pick["name"], "x/y/w/h", pick["x"], pick["y"], pick["w"], pick["h"],
                  flush=True)
            size = page.locator(".tree-side label.tree-num", has_text="Size %").locator("input")
            size.fill("60")
            size.press("Enter")
            size.blur()
            time.sleep(1)
            rig._wait(lambda: state()["tree_view"]["props"]["scale"] == 60, 60)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            time.sleep(3)
            pr = state()["tree_view"]["props"]
            print("after Size 60%: x/y/w/h", pr["x"], pr["y"], pr["w"], pr["h"],
                  "scale", pr["scale"], flush=True)
            size.evaluate("el => el.scrollIntoView({block: 'center'})")
            page.mouse.move(5, 1095)
            time.sleep(1)
            page.screenshot(path=out("resize.png"))
            print("page errors:", errors, flush=True)
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
