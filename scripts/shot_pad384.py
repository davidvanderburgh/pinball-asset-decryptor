"""PAD-384 proof shots: a Scenes text layer's button to its words on the Replace Text tab.

    python scripts/shot_pad384.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project, opens Battle Select in Scenes,
selects its first text layer and photographs, under the same names before and after:

- scenes_layers.png   the Layers list, the text layer's button hovered (after: its tip)
- text_tab.png        the Replace Text tab after that button is clicked (before: the
                      page as it stays, since there is no button to click)

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


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad384-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "text")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            tv = (state().get("text_scenes") or {}).get("tree_view") or {}
            lay = next((l for l in tv.get("layers") or [] if l.get("kind") == "Text"), None)
            print("text layer:", lay and (lay["id"], lay["name"], lay.get("text")), flush=True)
            if lay:
                api("text_scenes.tree_select", lay["id"], "")
                time.sleep(2)
            row = page.query_selector("[data-node='%s']" % lay["id"]) if lay else None
            btn = row.query_selector(".ly-txt") if row else None
            print("button:", bool(btn), flush=True)
            if row:
                row.scroll_into_view_if_needed()
            if btn:
                btn.hover()
                time.sleep(1.6)
            box = page.query_selector(".tree-layers")
            b = box.bounding_box() if box else None
            page.screenshot(path=out("scenes_layers.png"), clip={
                "x": max(0, b["x"] - 20), "y": max(0, b["y"] - 20),
                "width": b["width"] + 300, "height": min(b["height"] + 40, 700)} if b else None)
            if btn:
                btn.click()
                time.sleep(4)
            page.mouse.move(5, 990)
            time.sleep(0.5)
            page.screenshot(path=out("text_tab.png"))
            print("text tab search:", (state().get("text") or {}).get("text_search_var"),
                  flush=True)
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
