"""PAD-391 proof shot (--delete: round 2, the Delete key in Layers asks first): a layer dragged into another group in Scenes > Layers.

    python scripts/shot_pad391.py <repo> <godzilla project> <out_png> [--drag]

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens Scenes on the Battle Select scene DragonRR sent (T1_1_Art, T1_2_Art and the
Line1/Line2_Instructions lines), adds a line of text (it lands at the end of the list, on
the scene's top level) and snaps the page to <out_png>.  With --drag it first drags that
line's row with the mouse onto the T1_1_Art row, as a user would.  Prints the line's
depth and group before and after.
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

SCENE_HASH = "cac32730af42b9d26d26c4bb6e667b07da53113e"
GROUP = "T1_1_Art"


def main():
    repo, source, out = sys.argv[1:4]
    drag = "--drag" in sys.argv[4:]
    delete = "--delete" in sys.argv[4:]          # round 2: Delete pressed in Layers
    print("repo:", repo, flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad391-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
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
            base = "/godzilla_le/assets/lcd/auto_loaded/" + SCENE_HASH
            ok = any(api("text_scenes.select", k) for k in (base, base + "/scene.radium"))
            if not ok:
                st = state()
                keys = [k for k in st.get("scenes_index", st) if SCENE_HASH in str(k)]
                print("scene keys:", keys, sorted(st)[:40], flush=True)
                raise SystemExit("scene not found")
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            api("text_scenes.tree_select", None)
            assert api("text_scenes.tree_add_text", "LOOK UP")
            time.sleep(1)
            rig._wait(lambda: not state().get("tree_busy"), 60)

            def show(tag):
                ls = state()["tree_view"]["layers"]
                for l in ls:
                    if l["added"]:
                        print(tag, l["name"], "depth", l["depth"], "parent", l.get("parent"),
                              l["edits"], flush=True)
                return ls

            layers = show("before:")
            added = [l for l in layers if l["added"]][-1]["id"]
            group = [l for l in layers if l["name"].startswith(GROUP)][0]["id"]
            api("text_scenes.tree_select", None)
            time.sleep(1)
            src = page.locator('.tree-layers [data-node="%s"]' % added)
            src.scroll_into_view_if_needed()
            if delete:
                src.evaluate("el => el.scrollIntoView({block: 'end'})")
                src.click()
                time.sleep(1.5)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                page.mouse.move(5, 995)
                page.keyboard.press("Delete")
                time.sleep(3)
                page.screenshot(path=out)
                print("layers left:", [l["name"] for l in state()["tree_view"]["layers"]
                                       if l["added"]], flush=True)
                browser.close()
                return
            if drag:
                dst = page.locator('.tree-layers [data-node="%s"]' % group)
                sb, db = src.bounding_box(), dst.bounding_box()
                # drag up the list by hand: the list scrolls itself near its top edge
                page.mouse.move(sb["x"] + 60, sb["y"] + sb["height"] / 2)
                page.mouse.down()
                page.mouse.move(sb["x"] + 70, sb["y"] + sb["height"] / 2 - 10, steps=5)
                for _ in range(60):
                    db = dst.bounding_box()
                    if db and db["y"] > page.locator(".tree-layers").bounding_box()["y"] + 40:
                        break
                    lb = page.locator(".tree-layers").bounding_box()
                    page.mouse.move(sb["x"] + 70, lb["y"] + 8, steps=2)
                    time.sleep(0.05)
                db = dst.bounding_box()
                page.mouse.move(db["x"] + 80, db["y"] + db["height"] / 2, steps=8)
                time.sleep(0.3)
                page.mouse.up()
                time.sleep(1)
                rig._wait(lambda: not state().get("tree_busy"), 60)
                show("after:")
                api("text_scenes.tree_select", added)
                time.sleep(1)
                rig._wait(lambda: not state().get("tree_busy"), 60)
            else:
                api("text_scenes.tree_select", added)
                time.sleep(1)
            page.locator('.tree-layers [data-node="%s"]' % added).evaluate(
                "el => el.scrollIntoView({block: 'end'})")
            page.mouse.move(5, 995)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
