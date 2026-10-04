"""PAD-364 proof shots: the Color profiles bar on the Images and Video tabs.

    python scripts/shot_pad364.py <repo> <out_dir> <prefix> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project (one Battle Select portrait and
one clip replaced) with two profile files in the folder the Saved profiles list reads,
and photographs two screens:

- <prefix>_images_colors.png   the Images tab on the replaced portrait
- <prefix>_video_colors.png    the Video tab on the replaced clip

With --after (the ticket branch) the rainbow Colors tab on each page's right edge is
clicked first, the bar put on Files and "Godzilla LE" picked from its Saved profiles
list, so the pair shows the bar in use beside the asset's own color switch.  Before
(main) there is no tab to click: the page is photographed as it is.

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
import shot_pad360 as saved  # noqa: E402


def _open_bar(page, api, state):
    """Click the rainbow tab if the page has one; put the bar on Files and pick the
    saved profile.  Says what it found."""
    handle = page.query_selector(".cpd-handle")
    print("bar handle:", bool(handle), flush=True)
    if not handle:
        return False
    handle.click()
    time.sleep(1.2)
    tab = page.query_selector(".cpd-tabs button:has-text('Files')")
    if tab:
        tab.click()
        time.sleep(1)
    folder = state().get("color", {}).get("saved") or []
    pick = next((o["value"] for o in folder if "Godzilla" in o.get("label", "")), None)
    if pick:
        print("use_saved:", api("color.use_saved", pick), flush=True)
        time.sleep(1.5)
    page.eval_on_selector(".cpd-body", "el => { el.scrollTop = 0; }")
    return True


def main():
    repo, out_dir, prefix = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad364-")
    project = base._project(scratch)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    for name, text in (("Godzilla LE.txt", saved.GODZILLA), ("Black playfield.txt", saved.DARK)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
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
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.removeItem('pad.colorbar.open.images');"
                " localStorage.removeItem('pad.colorbar.open.video'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            # the Images tab on the replaced portrait
            api("ui.select_tab", "images")
            time.sleep(2)
            st = base._wait_scan(state, "images")
            print("images:", st.get("status"), flush=True)
            api("ui.set", "images", "search", "530x726")
            time.sleep(2)
            api("images.select", base.PORTRAIT)
            time.sleep(3)
            if after:
                _open_bar(page, api, state)
            page.mouse.move(5, 990)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir, prefix + "_images_colors.png"))
            c = state().get("color") or {}
            print("color:", {k: c.get(k) for k in ("mode", "name", "saved_on", "asset_counts")},
                  flush=True)
            # the Video tab on the replaced clip
            api("ui.select_tab", "video")
            time.sleep(2)
            st = base._wait_scan(state, "video")
            print("video rows:", len(st.get("rows") or []), flush=True)
            api("video.select", base.VIDEO, None)
            time.sleep(3)
            if after:
                _open_bar(page, api, state)
            page.mouse.move(5, 990)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir, prefix + "_video_colors.png"))
            v = state().get("video") or {}
            print("video look:", (v.get("look") or {}).get("parts"), flush=True)
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
