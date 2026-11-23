"""PAD-1532 proof shots: "Show unused" on the Video tab.

    python scripts/shot_pad1532.py <repo> <out_dir> [--after]

PAD-634's Deadpool LE 1.16 project (``shot_pad624``'s rig), PAD-1527's clips plus three
the card's program never plays.  The Video
tab is shown once the card's "Played in" reading is in.  With --after the toolbar's
"Show unused" box is unticked first, so the clips the game never plays leave the
list; before, the box is not there.  Writes video_show_unused.png.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad634 as rig634  # noqa: E402,F401  (sets the PAD-634 projects up on the rig)
import shot_pad624 as rig  # noqa: E402

rig.SOURCE = os.environ.get("PAD1532_SOURCE", r"C:\tmp\PAD-1532\proj_src")
rig.SCRATCH = os.environ.get("PAD1532_SCRATCH", r"C:\tmp\PAD-1532\shot_scratch")
#: PAD-1527's eight clips (each one some mode's) and three the game never plays
_card, _clips = rig.PROJECTS["deadpool"]
rig.PROJECTS = {"deadpool": (_card, tuple(_clips) + ("CloneMultiballStart", "MegQuest_Intro",
                                                     "Megakrakolodonus_Background"))}


def _one(repo, out, pre, after):
    import shutil
    import tempfile
    import time
    import webui_shot
    os.makedirs(rig.SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1532-", dir=rig.SCRATCH)
    project = rig._project(scratch, "deadpool", False)
    proc, url = rig._serve(repo, scratch, project, os.path.join(rig.CARDS, rig.PROJECTS["deadpool"][0]))
    state = lambda: webui_shot.state(url)                    # noqa: E731
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    print("repo:", repo, flush=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", args=["--mute-audio"])
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
            for _ in range(240):
                if ((state().get("video") or {}).get("modes") or {}).get("ready"):
                    break
                time.sleep(0.5)
            time.sleep(1.5)
            if after:
                api("video.set_hide_unused", False)       # start from the default: ticked
                time.sleep(0.5)
                page.locator(".toolbar >> text=Show unused").first.click()
                time.sleep(1)
            st = state().get("video") or {}
            md = st.get("modes") or {}
            print("ready:", md.get("ready"), "list:", [(m["id"], m["n"]) for m in md.get("list") or []],
                  flush=True)
            print("status:", st.get("status"), "hide_unused:", st.get("hide_unused"),
                  "shown:", (st.get("counts") or {}).get("shown"), flush=True)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=os.path.join(out, pre + "video_show_unused.png"))
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
    after = "--after" in sys.argv
    _one(repo, out, "after_" if after else "before_", after)
