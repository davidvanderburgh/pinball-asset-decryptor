"""PAD-439 proof shots: "Apply to all videos" / "Apply to all images" on the Colors bar.

    python scripts/shot_pad439.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project with three clips replaced (none
with a color profile attached) and the Battle Select portrait replaced, with two profile
files in the folder the Saved profiles list reads.  The first clip is given "Godzilla LE"
from that list (its own profile, attached), then, under the same names before and after:

- video_bar.png      the Video tab, the first clip clicked, the Colors bar open on it
- video_applied.png  the third clip's Color palette hovered.  After: once the rig has
                     pressed "Apply to all videos" and answered Yes.  Before there is no
                     such button, so the clip is as it was.
- images_bar.png     the Images tab, the portrait clicked, the Colors bar open on it

and after only:

- video_confirm.png  the "Are you sure?" question the button asks

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad360 as saved  # noqa: E402

MORE = (("video/pad439_mothra.mp4", "mothra_s_song"),
        ("video/pad439_shin.mp4", "shin_godzilla"))


def _hover_tip(page, selector, path):
    el = page.query_selector(selector)
    print("hover", selector, bool(el), flush=True)
    if el:
        el.scroll_into_view_if_needed()
        el.hover()
        time.sleep(1.6)
    page.screenshot(path=path)
    page.mouse.move(5, 990)
    time.sleep(0.4)


def _project(scratch):
    project = base._project(scratch)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    for rel, mode in MORE:
        clip = os.path.join(base.SOURCE, "modes", mode, "clip.mp4")
        if not os.path.isfile(clip):
            clip = os.path.join(base.SOURCE, "modes", "atomic_breath", "clip.mp4")
        shutil.copy2(clip, os.path.join(project, rel))
        mine = os.path.join(scratch, "my_" + rel.split("/")[-1])
        shutil.copy2(clip, mine)
        data.setdefault("video", {})[rel] = mine
    for k in ("video_color_slots", "image_color_slots", "video_color_profiles",
              "image_color_profiles", "color_all_videos", "color_all_images"):
        data.pop(k, None)
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return project


def _bar_on(page, api, state):
    """Open the Colors bar (on Files) and pick Godzilla LE from Saved profiles."""
    page.click(".cpd-handle")
    time.sleep(1.5)
    tab = page.query_selector(".cpd-tabs button:has-text('Files')")
    if tab:
        tab.click()
        time.sleep(1)
    c = state().get("color") or {}
    pick = next((o["value"] for o in c.get("saved") or []
                 if "Godzilla" in o.get("label", "")), None)
    print("use_saved:", api("color.use_saved", pick), flush=True)
    time.sleep(2)
    page.eval_on_selector(".cpd-body", "el => { el.scrollTop = 0; }")
    page.mouse.move(5, 990)
    time.sleep(0.5)


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad439-")
    project = _project(scratch)
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
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
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
            api("ui.select_tab", "images")
            time.sleep(2)
            st = base._wait_scan(state, "images")
            print("images:", st.get("status"), flush=True)
            # the Video tab: the first clip clicked, the bar open on it
            api("ui.select_tab", "video")
            time.sleep(2)
            st = base._wait_scan(state, "video")
            print("video rows:", len(st.get("rows") or []), flush=True)
            time.sleep(2)
            first = base.VIDEO.split("/")[-1]
            page.click(".vid-name:has-text('%s')" % first)
            time.sleep(2)
            _bar_on(page, api, state)
            page.screenshot(path=out("video_bar.png"))
            c = state().get("color") or {}
            print("color:", {k: c.get(k) for k in ("mode", "name", "file", "own_names")},
                  flush=True)
            if after:
                btn = page.query_selector(".cpd-file-all button")
                print("apply button:", bool(btn), flush=True)
                if btn:
                    btn.click()
                    time.sleep(1.5)
                    page.screenshot(path=out("video_confirm.png"))
                    page.click(".modal button:has-text('Yes')")
                    time.sleep(3)
            v = state().get("video") or {}
            print("rows col:", [(r["rel"], r.get("col")) for r in v.get("rows") or []
                                if r.get("col") is not None], flush=True)
            print("own names:", (state().get("color") or {}).get("own_names"), flush=True)
            page.click(".cpd-handle")                     # close it for the tooltip
            time.sleep(1)
            last = MORE[-1][0].split("/")[-1]
            _hover_tip(page, ".tr:has-text('%s') .vid-color" % last, out("video_applied.png"))
            # the Images tab: the portrait clicked, the bar open on it
            api("ui.select_tab", "images")
            time.sleep(2)
            api("ui.set", "images", "search", "530x726")
            time.sleep(2)
            api("images.select", base.PORTRAIT)
            time.sleep(3)
            page.click(".cpd-handle")
            time.sleep(1.5)
            tab = page.query_selector(".cpd-tabs button:has-text('Files')")
            if tab:
                tab.click()
                time.sleep(1)
            page.eval_on_selector(".cpd-body", "el => { el.scrollTop = 0; }")
            page.mouse.move(5, 990)
            time.sleep(0.5)
            page.screenshot(path=out("images_bar.png"))
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
