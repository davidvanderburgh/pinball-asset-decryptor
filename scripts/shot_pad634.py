"""PAD-634 proof shots: the Video tab's Played in on the plain-C titles and Deadpool.

    python scripts/shot_pad634.py <repo> <out_dir> [--after] [--only=<screen>]

PAD-624's rig (``shot_pad624``) on other SCRATCH projects, copied off the stock cards (read only)
into ``PAD634_SOURCE`` once and copied again for every run, so before and after see the same
files. Writes, under the same names before and after:

- video_aerosmith.png        Aerosmith Pro 1.16, LoveInAnElevator_LadyEnters_1 selected
- video_stranger_things.png  Stranger Things LE 1.13, ST_BustOutModeStart_LCD_PRO selected
- video_deadpool.png         Deadpool LE 1.16, JuggernautModeTotal selected

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad624 as rig  # noqa: E402

rig.SOURCE = os.environ.get("PAD634_SOURCE", r"C:\tmp\PAD-634\proj_src")
rig.SCRATCH = os.environ.get("PAD634_SCRATCH", r"C:\tmp\PAD-634\shot_scratch")
rig.PROJECTS = {
    "aerosmith": ("aerosmith-1_16_0.Release.8G.sdcard.raw",
                  ("LoveInAnElevator_LadyEnters_1", "LoveInAnElevator_shaft", "ToysInTheAttic_Intro",
                   "ragdollBeatsJacky_Smack", "MedleyMultiball", "FinalTour_Start",
                   "SupersStart_Lanes", "Kick_Hey1", "Jacky_BallSave")),
    "stranger_things": ("stranger_things_le-1_13_0.Release.8G.sdcard.raw",
                        ("ST_BustOutModeStart_LCD_PRO", "ST_CantStopThis_ModeStart_LCD_PRO",
                         "ST_JunkYardModeTotal_LCD_PRO", "ST_WheresBarbIntro_LCD_PRO",
                         "ST_MonsterHuntingStart_LCD_PRO", "ST_BallSave_LCD_PRO", "ST_Match_00")),
    "deadpool": ("deadpool_le-1_16_0.Release.8G.sdcard.raw",
                 ("JuggernautModeTotal", "Deadpool_Juggernaut_Uppercut", "MystiqueModeTotal",
                  "DiscoMultiBall_IntroVideo", "mechSuitMultiBallIntro", "NinjaMBSuperJackpot",
                  "TRexQuest_ModeTotal", "LilDeadpool_BallSaved")),
}
rig.SHOTS = (("video_aerosmith", "aerosmith", "LoveInAnElevator_LadyEnters_1.mp4", False),
             ("video_stranger_things", "stranger_things", "ST_BustOutModeStart_LCD_PRO.mp4", False),
             ("video_deadpool", "deadpool", "JuggernautModeTotal.mp4", False))
rig.EXTRACT_NAMED = ()


def _one(repo, out, pre, screen, key, rel, gone):
    """shot_pad624's, but the row is clicked where it is (these lists fit on the page), so the
    shot shows every clip's Played in."""
    import json
    import shutil
    import tempfile
    import time
    import webui_shot
    os.makedirs(rig.SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad634-", dir=rig.SCRATCH)
    project = rig._project(scratch, key, gone)
    proc, url = rig._serve(repo, scratch, project, os.path.join(rig.CARDS, rig.PROJECTS[key][0]))
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
                md = (state().get("video") or {}).get("modes") or {}
                if md.get("ready"):
                    break
                time.sleep(1)
            page.locator(".vid-tbl .tr:has-text('%s')" % rel).first.click()
            time.sleep(3)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=os.path.join(out, pre + screen + ".png"))
            st = state().get("video") or {}
            md = st.get("modes") or {}
            print(screen, "modes:", json.dumps({k: md.get(k) for k in ("note", "list", "why")}),
                  flush=True)
            print(screen, "rows:", json.dumps({r.get("rel"): r.get("modes") for r in
                                               (st.get("rows") or []) if isinstance(r, dict)}),
                  flush=True)
            print(screen, "page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


rig._one = _one

if __name__ == "__main__":
    rig.main()
