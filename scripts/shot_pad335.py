"""PAD-335 proof shot: the Images tab's Color column, locked / red / green like Video.

    python scripts/shot_pad335.py <repo> <out_dir> <prefix> [--after]

Same scratch Godzilla project as shot_pad312 (one Battle Select portrait replaced).  The
Color profile tab is put on "Adjust individual files" with Every replaced picture ticked,
then the Images tab is shot on the 530x726 portraits as <prefix>_images.png.  With
--after the advanced "Unlock the game's own pictures" box is ticked and one stock portrait
is switched on, shot as <prefix>_images_unlocked.png.
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
    repo, out, prefix = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad335-")
    project = base._project(scratch)
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
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "assets")
            api("color.set_all", "images", True)
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(1)
            api("ui.set", "images", "search", "530x726")
            time.sleep(2)
            api("images.select", base.PORTRAIT)
            time.sleep(3)
            page.screenshot(path=os.path.join(out, prefix + "_images.png"))
            if after:
                assert api("images.set_color_unlocked", True)
                time.sleep(1)
                st = state().get("images") or {}
                stock = None
                for chunk in (st.get("chunks") or {}).values():
                    for row in chunk or ():
                        if (row and "530x726" in row.get("r", "")
                                and row["r"] != base.PORTRAIT):
                            stock = row["r"]
                            break
                    if stock:
                        break
                print("stock:", stock, flush=True)
                if stock:
                    assert api("images.set_color", stock, True)
                    api("images.select", stock)
                time.sleep(3)
                page.screenshot(path=os.path.join(out, prefix + "_images_unlocked.png"))
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
