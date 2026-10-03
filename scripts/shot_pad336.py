"""PAD-336 proof shot: the Video tab's Advanced box unlocks the game's own clips.

    python scripts/shot_pad336.py <repo> <out_dir> <prefix> [--after]

shot_pad334's scratch Godzilla project (one replaced clip corrected, one replaced and
kept in its own colors, one left as the game's own clip), Color profile tab on "Adjust
individual files" with Every replaced video ticked.  With --after, Advanced is ticked and
the game's own clip is switched on before the Video tab is shot as <prefix>_video.png.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402
import shot_pad334 as pad334  # noqa: E402


def main():
    repo, out, prefix = sys.argv[1:4]
    after = "--after" in sys.argv[4:]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad336-")
    project = pad334._project(scratch)
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
            base._wait_scan(state, "video")
            if after:
                print("advanced:", api("video.set_color_stock", True), flush=True)
                print("stock on:", api("video.set_color", pad334.STOCK, True), flush=True)
                time.sleep(1)
            for r in (state().get("video") or {}).get("rows") or []:
                print(r.get("rel"), r.get("col"), r.get("col_own"), r.get("col_lock"),
                      r.get("col_stock"), flush=True)
            time.sleep(2)
            page.screenshot(path=os.path.join(out, prefix + "_video.png"))
            if after:
                box = page.locator(".vid-color.on").last
                box.hover()
                time.sleep(1)
                page.screenshot(path=os.path.join(out, prefix + "_video_tip.png"))
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
