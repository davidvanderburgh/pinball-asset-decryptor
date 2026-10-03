"""PAD-334 proof shot: the Video tab's Color column, locked / red / green like Scenes.

    python scripts/shot_pad334.py <repo> <out_dir> <prefix>

Same scratch Godzilla project as shot_pad312, with three video slots: one replaced and
corrected (the Color profile tab's box), one replaced and kept in its own colors, and one
left as the game's own clip.  The Color profile tab is put on "Adjust individual files" with
Every replaced video ticked, then the Video tab is shot as <prefix>_video.png.
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

OWN = "video/pad334_own.mp4"
STOCK = "video/pad334_stock.mp4"


def _project(scratch):
    dst = base._project(scratch)
    side = os.path.join(dst, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    clip = os.path.join(dst, base.VIDEO)
    for rel in (OWN, STOCK):
        shutil.copy2(clip, os.path.join(dst, rel))
    mine = os.path.join(scratch, "my_own_clip.mp4")
    shutil.copy2(clip, mine)
    data["video"][OWN] = mine
    data["video_color_slots"] = {OWN: False}
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return dst


def main():
    repo, out, prefix = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad334-")
    project = _project(scratch)
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
            api("ui.select_tab", "color")
            time.sleep(1)
            api("color.set_mode", "assets")
            api("color.set_all", "videos", True)
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            st = base._wait_scan(state, "video")
            for r in st.get("rows") or []:
                print(r.get("rel"), r.get("col"), r.get("col_own"), r.get("col_lock"),
                      flush=True)
            time.sleep(2)
            page.screenshot(path=os.path.join(out, prefix + "_video.png"))
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
