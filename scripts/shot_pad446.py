"""PAD-446 proof shots: a clip the game plays one of several of, at random.

    python scripts/shot_pad446.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Godzilla Pro 1.16 project made from a videos-only extract of the
stock card (PAD446_EXTRACT, default C:\\tmp\\pad446\\gzpro116; seven of its clips copied, the
manifest, baseline and extract record with them). Titanosaurus' battle intro is given two
random clips (copies of two other kaiju intros), Mothra's ball save a replacement, and the
attract loop nothing. Writes, under the same names before and after:

- <before_|after_>video_tab.png    the Video tab on the Titanosaurus intro
- <before_|after_>video_menu.png   its right-click menu, "Random clips" opened where it is

Before (main) the tab knows nothing of the random clips the sidecar holds: one clip per slot.
After (--after, the ticket branch) the row carries a shuffle badge "+2", the note under the
players names the three clips, and the menu has "Random clips" with each one listed.

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
SLOT = "video/GodzillaVsTitanosaurus_Intro.mp4"
TAKES = (("Titanosaurus intro - take 2.mp4", "GodzillaVsMegalon_Intro.mp4"),
         ("Titanosaurus intro - take 3.mp4", "Mecha_Multiball_Intro.mp4"))


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
    takes = []
    for name, src in TAKES:
        shutil.copy2(os.path.join(EXTRACT, "video", src), os.path.join(mine, name))
        takes.append(os.path.join(mine, name))
    save = os.path.join(mine, "Mothra saves the ball.mp4")
    shutil.copy2(os.path.join(EXTRACT, "video", "ball_save2.mp4"), save)
    with open(os.path.join(dst, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"video": {"video/mothra_ball_save.mp4": save},
                   "video_variants": {SLOT: takes}}, f, indent=2)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch446.py")
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


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad446-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
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
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            st = _wait_scan(state)
            print("video rows:", [r["rel"] for r in st.get("rows") or []], flush=True)
            print("status:", st.get("status"), flush=True)
            row = page.locator(".vid-tbl .tr:has-text('GodzillaVsTitanosaurus_Intro')").first
            row.click()
            time.sleep(4)
            page.evaluate("() => document.querySelectorAll('video').forEach((v) => { v.pause(); })")
            time.sleep(0.5)
            st = state().get("video") or {}
            r = next((x for x in st.get("rows") or [] if x["rel"] == SLOT), {})
            print("row:", {k: r.get(k) for k in ("rep", "var", "var_tip")}, flush=True)
            print("note:", (st.get("preview") or {}).get("note"), flush=True)
            page.screenshot(path=out("video_tab.png"))
            row.click(button="right")
            time.sleep(1)
            item = page.locator(".menu .mi:has-text('Random clips')").first
            if item.count():
                item.hover()
                time.sleep(0.8)
            else:
                page.locator(".menu .mi:has-text(\"This clip's length\")").first.hover()
                time.sleep(0.8)
            print("menu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            page.screenshot(path=out("video_menu.png"))
            page.keyboard.press("Escape")
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
