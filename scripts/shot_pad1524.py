"""PAD-1524 proof shots: the Video tab sorted by its Played in column.

    python scripts/shot_pad1524.py <repo> <out_dir> [--after]

PAD-634's Deadpool LE 1.16 project (``shot_pad634``'s rig), the Played in header clicked once, so
the after shot shows the rows grouped by mode (A-Z, "Other parts of the game" and "Not played"
after them) and the before shot the same click doing nothing. Writes video_played_in_sort.png.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad634 as rig634  # noqa: E402,F401  (sets the PAD-634 projects up on the rig)
import shot_pad624 as rig  # noqa: E402

rig.SOURCE = os.environ.get("PAD1524_SOURCE", r"C:\tmp\PAD-1524\proj_src")
rig.SCRATCH = os.environ.get("PAD1524_SCRATCH", r"C:\tmp\PAD-1524\shot_scratch")
rig.PROJECTS = {k: v for k, v in rig.PROJECTS.items() if k == "deadpool"}


def _one(repo, out, pre):
    import json
    import shutil
    import tempfile
    import time
    import webui_shot
    os.makedirs(rig.SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1524-", dir=rig.SCRATCH)
    project = rig._project(scratch, "deadpool", False)
    proc, url = rig._serve(repo, scratch, project, os.path.join(rig.CARDS, rig.PROJECTS["deadpool"][0]))
    state = lambda: webui_shot.state(url)                    # noqa: E731
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
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
            deadline = time.time() + 600
            while time.time() < deadline:
                if ((state().get("video") or {}).get("modes") or {}).get("ready"):
                    break
                time.sleep(1)
            time.sleep(2)
            page.locator(".vid-tbl .th >> text=Played in").first.click()
            time.sleep(2)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=os.path.join(out, pre + "video_played_in_sort.png"))
            st = state().get("video") or {}
            rows = st.get("rows") or []
            print("sort:", st.get("sort"), flush=True)
            print("order:", json.dumps([(rows[i].get("rel"), rows[i].get("modes"), rows[i].get("other"),
                                         rows[i].get("unplayed")) for i in st.get("view") or []]), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    repo, out = sys.argv[1:3]
    os.makedirs(out, exist_ok=True)
    _one(repo, out, "after_" if "--after" in sys.argv else "before_")
