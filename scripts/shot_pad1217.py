"""PAD-1217 proof shots: the Colors bar on a file with no color profile attached.

    python scripts/shot_pad1217.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project with no file switched on (a newly
brought in picture), and photographs, under the same names before and after:

- scenes_bar.png   Battle Select in Scenes, the portrait's layer picked, the Colors bar
                   open on Files: nothing attached
- scenes_bar_set.png   the same after picking Black and white: attached, in use
- images_bar.png   the Images tab, the portrait clicked, the Colors bar open on Files

Before, the Start from row lights Recommended although nothing is attached; after, no
starting point is lit and the row says None set, until one is picked.

Needs Playwright (the user site-packages one) and the installed Edge.
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
import shot_pad360 as saved  # noqa: E402


def _bar(page, state, api, page_cls):
    shell = ".cpd-shell:has(.%s) " % page_cls
    if not page.locator(shell + ".cpd.open:has(.cpd-handle:has-text('Colors'))").count():
        page.locator(shell + ".cpd > .cpd-handle:has-text('Colors')").click()
        time.sleep(1.5)
    api("color.set_mode", "assets")
    time.sleep(1.5)
    page.eval_on_selector_all(".cpd-body", "els => els.forEach((el) => { el.scrollTop = 0; })")
    page.mouse.move(5, 990)
    time.sleep(0.6)
    c = state().get("color") or {}
    print("color:", {k: c.get(k) for k in ("mode", "name", "file", "active", "preset_on",
                                           "in_use")}, flush=True)


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1217-")
    project = base._project(scratch)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    for k in list(data):
        if "color" in k or "colour" in k or k.startswith("files\n"):
            data.pop(k)
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    proc, url = saved._serve(repo, scratch, project, folder)
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
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); localStorage.setItem('pad.fontbar.open', '0');"
                " localStorage.removeItem('pad.colorbar.open');"
                " localStorage.removeItem('pad.colorbar.open.images');"
                " localStorage.removeItem('pad.colorbar.open.video'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "images")
            time.sleep(2)
            base._wait_scan(state, "images")
            api("ui.set", "images", "search", "530x726")
            time.sleep(2)
            api("images.select", base.PORTRAIT)
            time.sleep(3)
            _bar(page, state, api, "img-page")
            page.screenshot(path=out("images_bar.png"))
            page.locator(".cpd-shell:has(.img-page) .cpd > .cpd-handle:has-text('Colors')").click()
            time.sleep(1)
            # Scenes: Battle Select, the portrait's layer
            api("images.open_scenes", base.PORTRAIT)
            time.sleep(2)
            api("text_scenes.select", base.BATTLE + "/scene.radium") or api(
                "text_scenes.select", base.BATTLE)
            time.sleep(8)
            tv = (state().get("text_scenes") or {}).get("tree_view") or {}
            lay = next((l for l in tv.get("layers") or []
                        if (l.get("color") or {}).get("rel") == base.PORTRAIT), None)
            print("layer:", lay and (lay["id"], lay["name"], lay.get("color")), flush=True)
            if lay:
                api("text_scenes.tree_select", lay["id"], "")
                time.sleep(2)
            _bar(page, state, api, "scenes-page")
            page.screenshot(path=out("scenes_bar.png"))
            api("color.preset", "bw")
            time.sleep(2.5)
            _bar(page, state, api, "scenes-page")
            page.screenshot(path=out("scenes_bar_set.png"))
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
