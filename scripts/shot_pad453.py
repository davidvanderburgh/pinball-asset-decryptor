"""PAD-453 proof shots: Undo / Redo on the Video tab.

    python scripts/shot_pad453.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Godzilla Pro 1.16 project made from a videos-only extract of the
stock card (PAD446_EXTRACT, default C:\\tmp\\pad446\\gzpro116; a few of its clips copied, the
manifest, baseline and extract record with them). Mothra's ball save and the Megalon intro
have replacements picked. The rig selects Mothra's row, clicks "Clear replacement" under the
players, then presses Ctrl+Z. Writes, under the same names before and after:

- <before_|after_>video_cleared.png   the tab just after the Clear
- <before_|after_>video_undo.png      the tab after Ctrl+Z

Before (main) there is no Undo: Ctrl+Z does nothing and the cleared pick stays gone.
After (--after, the ticket branch) Undo and Redo sit in the page head; Ctrl+Z puts the pick
back and Redo lights up.

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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
EXTRACT = os.environ.get("PAD446_EXTRACT", r"C:\tmp\pad446\gzpro116")
CLIPS = ("ATTRACT_LOOP1.mov", "GodzillaVsTitanosaurus_Intro.mp4", "GodzillaVsMegalon_Intro.mp4",
         "Mecha_Multiball_Intro.mp4", "mothra_ball_save.mp4", "ball_save2.mp4",
         "EndOfBallBonus_BackgroundLoop.mov")
SLOT = "video/mothra_ball_save.mp4"


def _project(scratch):
    dst = os.path.join(scratch, "gz_pro_116")
    os.makedirs(os.path.join(dst, "video"))
    for name in (".extract_source.json", ".checksums.md5"):
        shutil.copy2(os.path.join(EXTRACT, name), os.path.join(dst, name))
    with open(os.path.join(EXTRACT, "video", "manifest.txt"), encoding="utf-8") as f:
        rows = [l for l in f if l.startswith("#") or l.split("\t", 1)[0] in CLIPS]
    with open(os.path.join(dst, "video", "manifest.txt"), "w", encoding="utf-8") as f:
        f.writelines(rows)
    for name in CLIPS:
        shutil.copy2(os.path.join(EXTRACT, "video", name), os.path.join(dst, "video", name))
    mine = os.path.join(scratch, "My Godzilla clips")
    os.makedirs(mine)
    save = os.path.join(mine, "Mothra saves the ball.mp4")
    shutil.copy2(os.path.join(EXTRACT, "video", "ball_save2.mp4"), save)
    megalon = os.path.join(mine, "Megalon intro - take 2.mp4")
    shutil.copy2(os.path.join(EXTRACT, "video", "Mecha_Multiball_Intro.mp4"), megalon)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"video": {SLOT: save, "video/GodzillaVsMegalon_Intro.mp4": megalon}},
                  f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch453.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _wait_scan(state, limit=180):
    deadline = time.time() + limit
    while time.time() < deadline:
        st = state().get("video") or {}
        if st.get("rows") and not st.get("scanning") and "still checking" not in (st.get("status") or ""):
            return st
        time.sleep(1)
    return state().get("video") or {}


def _row(state):
    st = state().get("video") or {}
    r = next((x for x in st.get("rows") or [] if x["rel"] == SLOT), {})
    return {"rep": r.get("rep"), "undo": st.get("undo")}


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad453-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    tag = "after_" if after else "before_"
    out = lambda n: os.path.join(out_dir, tag + n)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(2)
            st = _wait_scan(state)
            print("video rows:", [r["rel"] for r in st.get("rows") or []], flush=True)
            page.locator(".vid-tbl .tr:has-text('mothra_ball_save')").first.click()
            time.sleep(4)
            page.evaluate("() => document.querySelectorAll('video').forEach((v) => { v.pause(); })")
            print("picked:", _row(state), flush=True)
            page.locator(".vid-panehead button:has-text('Clear replacement')").first.click()
            time.sleep(2)
            page.evaluate("() => document.querySelectorAll('video').forEach((v) => { v.pause(); })")
            print("cleared:", _row(state), flush=True)
            page.screenshot(path=out("video_cleared.png"))
            page.locator(".vid-tbl .tr:has-text('mothra_ball_save')").first.click()
            time.sleep(1)
            page.keyboard.press("Control+z")
            time.sleep(3)
            page.evaluate("() => document.querySelectorAll('video').forEach((v) => { v.pause(); })")
            time.sleep(0.5)
            print("after Ctrl+Z:", _row(state), flush=True)
            page.screenshot(path=out("video_undo.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
