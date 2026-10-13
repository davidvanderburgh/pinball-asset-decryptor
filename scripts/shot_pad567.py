"""PAD-567 proof shot: the Scenes tab's Contents list, a picture's row clicked in the scene
editor.  Before, the row only went blue (the preview and the Selected panel stayed as they
were) and every row had a second column of hints; now the row picks its layer on the
preview, drawn on top, and each picture row starts with a small copy of the picture.

    python scripts/shot_pad567.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch copy of the Godzilla project (Kaiju Battle Select)
and writes <out_dir>/(before|after)_scenes_contents.png.  The editor's selection before and
after the click goes to the console.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

ROW = "radimg_530x726_3889d8a2.png"


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    row = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--row=")), ROW)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, ("after_" if after else "before_") + "scenes_contents.png")
    scratch = tempfile.mkdtemp(prefix="pad567-")
    project = base._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    tv = lambda: (webui_shot.state(url).get("text_scenes") or {}).get("tree_view") or {}  # noqa: E731
    from playwright.sync_api import sync_playwright

    def wait_for(page, sel, n, limit=120):
        deadline = time.time() + limit
        while time.time() < deadline and page.locator(sel).count() < n:
            time.sleep(1)
        return page.locator(sel).count()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "scenes")
            wait_for(page, ".scenes-list .tr.click", 4)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE)
            wait_for(page, ".tree-layers .ly-item", 8, 90)
            time.sleep(4)
            page.locator(".sc-views button", has_text="Contents").click()
            time.sleep(2)
            rows = page.locator(".scenes-contents:not(.tree-layers) .sc-item:not(.note)")
            names = [t.strip() for t in rows.locator(".sc-t").all_inner_texts()]
            print("contents rows:", len(names), names[:12], flush=True)
            print("selection before:", tv().get("sel"), flush=True)
            rows.filter(has_text=row).first.locator(".sc-t").click()
            time.sleep(4)
            st = tv()
            props = st.get("props") or {}
            print("selection after:", st.get("sel"), props.get("name"), props.get("kind"), flush=True)
            print("item:", (webui_shot.state(url).get("text_scenes") or {}).get("item"), flush=True)
            page.mouse.move(5, 990)
            time.sleep(1.5)
            page.screenshot(path=out)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("wrote", out, "server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
