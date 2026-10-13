"""PAD-555 proof shot: the Video tab's More > "Save settings to a file..." on a project with
one replaced clip.

    python scripts/shot_pad555.py <repo> <out_dir> [--after]

<repo> is the source tree to serve. The project is a scratch folder of clip-named stand-in
files (the scan never opens them) with video/intro.mp4 replaced. The rig opens More, picks
Save settings, types a file name into the save box and presses Save, then writes
(before_ or after_) video_save_settings.png: what the page shows once the save is done
(main: the AttributeError toast; the branch: the saved settings file).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

CLIPS = ("video/attract.mp4", "video/intro.mp4", "video/ball_save.mp4",
         "video/jackpot.mp4", "video/sub/boss.mp4")


def _clip(path, src="testsrc2=size=1280x720:rate=30"):
    """A 3 s clip of *src* (real video, so the players show a picture)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src + ":duration=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)


def _project(scratch):
    root = os.path.join(scratch, "proj")
    lines = []
    for rel in CLIPS:
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _clip(p)
        with open(p, "rb") as f:
            lines.append("%s\t%s\n" % (rel, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(root, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("".join(lines))
    mine = os.path.join(scratch, "my_intro.mp4")
    _clip(mine, "smptehdbars=size=1280x720:rate=30")
    with open(os.path.join(root, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"video": {"video/intro.mp4": mine}}, f)
    return root


def main():
    repo, out_dir = (os.path.abspath(a) for a in sys.argv[1:3])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, ("after_" if after else "before_") + "video_save_settings.png")
    scratch = tempfile.mkdtemp(prefix="pad555-")
    project = _project(scratch)
    target = os.path.join(scratch, "my video settings.json")
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script("try { localStorage.setItem('pad.log.open', '1'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video", limit=120)
            api("video.select", "video/intro.mp4")
            time.sleep(2)
            page.locator('.pagehead [aria-label="More"]:visible').first.click()
            time.sleep(1)
            page.get_by_text("Save settings to a file", exact=False).first.click()
            time.sleep(2)
            page.mouse.move(700, 120)
            time.sleep(1)
            page.screenshot(path=os.path.join(scratch, "dialog.png"))
            if after:
                # the page's own save box: a path field and a Save button
                box = page.locator("dialog[open], .modal:visible, [role=dialog]:visible").last
                field = box.locator("input[type=text], input:not([type])").last
                field.fill(target)
                box.get_by_role("button", name="Save").last.click()
                time.sleep(3)
                page.mouse.move(700, 120)
                time.sleep(1)
            page.screenshot(path=out)
            print("saved file exists:", os.path.isfile(target), flush=True)
            if os.path.isfile(target):
                with open(target, encoding="utf-8") as f:
                    print(f.read()[:400], flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))
    print("wrote", out)


if __name__ == "__main__":
    main()
