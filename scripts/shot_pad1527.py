"""PAD-1527 proof shots: "Play sequentially" on the Video tab.

    python scripts/shot_pad1527.py <repo> <out_dir> [--after]

PAD-634's Deadpool LE 1.16 project (``shot_pad624``'s rig).  The first row is
played and sent to its last half second; the shot is taken once that clip has
ended.  With --after the toolbar's "Play sequentially" box is ticked first, so
the list has moved on to the next row and is playing it; before, the box is not
there and the list stays on the first row.  Writes video_play_sequentially.png.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad634 as rig634  # noqa: E402,F401  (sets the PAD-634 projects up on the rig)
import shot_pad624 as rig  # noqa: E402

rig.SOURCE = os.environ.get("PAD1527_SOURCE", r"C:\tmp\PAD-1524\proj_src")
rig.SCRATCH = os.environ.get("PAD1527_SCRATCH", r"C:\tmp\PAD-1527\shot_scratch")
rig.PROJECTS = {k: v for k, v in rig.PROJECTS.items() if k == "deadpool"}

_JUMP = """() => { const v = document.querySelector('.vid-pane video');
  if (!v || !(v.duration > 1)) return null;
  v.currentTime = v.duration - 0.5; return v.duration; }"""
_PLAYING = """() => [...document.querySelectorAll('.vid-pane video')]
  .some((v) => !v.paused && !v.ended && v.currentTime > 0)"""


def _one(repo, out, pre, after):
    import json
    import shutil
    import tempfile
    import time
    import webui_shot
    os.makedirs(rig.SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1527-", dir=rig.SCRATCH)
    project = rig._project(scratch, "deadpool", False)
    proc, url = rig._serve(repo, scratch, project, os.path.join(rig.CARDS, rig.PROJECTS["deadpool"][0]))
    state = lambda: webui_shot.state(url)                    # noqa: E731
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    print("repo:", repo, flush=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--autoplay-policy=no-user-gesture-required",
                                                                "--mute-audio"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open.video', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            rig.base._wait_scan(state, "video")
            time.sleep(2)
            if after:
                page.locator(".vid-opts >> text=Play sequentially").first.click()
                time.sleep(0.5)
            st = state().get("video") or {}
            rows = st.get("rows") or []
            view = [rows[i]["rel"] for i in st.get("view") or []]
            print("first rows:", view[:3], "play_through:", st.get("play_through"), flush=True)
            page.locator(".vid-tbl .tr").nth(1).click()
            time.sleep(1.5)
            page.locator(".vid-pane .vid-transport button >> text=Play").first.click()
            page.wait_for_function(_PLAYING, timeout=30000)
            print("clip length:", page.evaluate(_JUMP), flush=True)
            time.sleep(4)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=os.path.join(out, pre + "video_play_sequentially.png"))
            st = state().get("video") or {}
            print("on show:", (st.get("preview") or {}).get("rel"), "select:", st.get("select"),
                  "playing:", page.evaluate(_PLAYING), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
        _ = json


if __name__ == "__main__":
    repo, out = sys.argv[1:3]
    os.makedirs(out, exist_ok=True)
    after = "--after" in sys.argv
    _one(repo, out, "after_" if after else "before_", after)
