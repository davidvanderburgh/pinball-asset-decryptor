"""PAD-827 proof shot: the Video tab's "When it plays" column, filled from what the emulator saw.

    python scripts/shot_pad827.py <repo> <out_dir> [--after] [--seen <emulator_seen.json>]

Serves <repo> on a SCRATCH copy of a Godzilla LE 1.16 project holding the in-game bank's Gigan
clips (``PAD827_PROJECT``, default ``C:\\tmp\\PAD-827\\gzle116``: built off the stock card by
``C:\\tmp\\PAD-827\\mkproj.py``), recording the stock card as its source so the Video tab reads
its game program. The list is put on the Battle vs Gigan's clips and one row is selected.
``--seen`` copies an emulator run's record into the scratch project first (the after shot).
Writes ``before_video_battle.png`` / ``after_video_battle.png``. Needs Playwright (the user
site-packages one) and the installed Edge.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

PROJECT = os.environ.get("PAD827_PROJECT", r"C:\tmp\PAD-827\gzle116e")
CARD = os.environ.get("PAD827_CARD", r"D:\Pinball\images\Stern\spike2"
                      r"\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
MODE = os.environ.get("PAD827_MODE", "cmode_battle_vs_ebirah")
ROW = os.environ.get("PAD827_ROW", "ebirah_vs_godzilla22.mp4")


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch827.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(base.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    import json
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project,
                                               "extract_input": CARD}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PAD_TITLE_CACHE": os.path.join(os.path.dirname(scratch), "pad827-titles")})


def main():
    repo, out = sys.argv[1:3]
    after = "--after" in sys.argv
    seen = sys.argv[sys.argv.index("--seen") + 1] if "--seen" in sys.argv else None
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad827-")
    project = os.path.join(scratch, "gzle116")
    shutil.copytree(PROJECT, project)
    if seen:
        shutil.copy2(seen, os.path.join(project, "video", "emulator_seen.json"))
    proc, url = _serve(repo, scratch, project)
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
                " localStorage.setItem('pad.colorbar.open.video', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video")
            deadline = time.time() + 300
            while time.time() < deadline:
                if ((state().get("video") or {}).get("modes") or {}).get("ready"):
                    break
                time.sleep(1)
            api("video.set_mode_filter", MODE)
            time.sleep(2)
            if os.environ.get("PAD827_SEARCH"):
                api("ui.set", "video", "search", os.environ["PAD827_SEARCH"])
                time.sleep(2)
            api("video.select", "video/" + ROW)
            time.sleep(3)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=os.path.join(out, ("after_" if after else "before_")
                                              + "video_battle.png"))
            v = state().get("video") or {}
            print("rows:", [(r.get("rel"), r.get("seen")) for r in v.get("rows") or []][:40],
                  flush=True)
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
