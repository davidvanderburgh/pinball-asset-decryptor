"""PAD-1003 proof shot: the Jukebox window plays a song's intro video.

    python scripts/shot_pad1003.py <repo> <out_dir> [--after]

The PAD-1000 rig (shot_pad1000: a scratch Stern project whose jukebox has 20 songs, most with an
intro video), with song 2's intro made an MPEG-2 .mpg the page's engine cannot play as it is. Writes:

- <before_|after_>audio_jukebox.png        the Jukebox window
- <before_|after_>jukebox_intro_video.png  song 1's "More" menu (before: no way to see the video);
                                           after: song 1's intro video playing in its own window
- after_jukebox_intro_copy.png             song 2's .mpg intro playing from a preview copy

Needs Playwright (the user site-packages one), the installed Edge and ffmpeg.
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1000 as J  # noqa: E402
import webui_shot  # noqa: E402


def _mpg_intro(project):
    """Song 2's intro becomes an MPEG-2 .mpg (no engine plays it), in the sidecar too."""
    import json
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        d = json.load(f)
    g = d["jukebox"]["songs"][1]
    mpg = os.path.splitext(g["video"])[0] + ".mpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", g["video"], "-t", "6", "-vf", "scale=680:384",
                    "-c:v", "mpeg2video", "-q:v", "4", "-c:a", "mp2", mpg], check=True)
    g["video"] = mpg
    with open(side, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def _frame_shown(page):
    """Wait until the preview's <video> is playing with a picture; return its facts."""
    for _ in range(120):
        got = page.evaluate("""() => { const v = document.querySelector('.modal video');
          return v ? {src: decodeURIComponent(v.currentSrc || ''), t: v.currentTime, w: v.videoWidth,
                      paused: v.paused, err: v.error ? v.error.code : 0} : null; }""")
        if got and got["w"] and got["t"] > 1.0 and not got["paused"]:
            return got
        time.sleep(0.5)
    return got


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    pre = "after_" if after else "before_"
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1003-")
    project = J._project(scratch)
    _mpg_intro(project)
    print("serving", repo, "project", project, flush=True)
    proc, url = J._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); "
                                 "localStorage.removeItem('pad.modal.jukebox'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            J._open(page, state)
            page.screenshot(path=os.path.join(out_dir, pre + "audio_jukebox.png"))
            rows = page.locator(".modal .aud-juke tbody tr")
            if not after:
                rows.nth(0).locator("button[aria-label='More for this song']").click()
                time.sleep(0.6)
                page.screenshot(path=os.path.join(out_dir, pre + "jukebox_intro_video.png"))
            else:
                rows.nth(0).locator("button[aria-label='Watch this intro video']").click()
                page.wait_for_selector(".modal video", timeout=20000)
                print("song 1:", _frame_shown(page), flush=True)
                page.screenshot(path=os.path.join(out_dir, pre + "jukebox_intro_video.png"))
                page.keyboard.press("Escape")
                time.sleep(0.5)
                rows.nth(1).locator("button[aria-label='Watch this intro video']").click()
                page.wait_for_selector(".modal video", timeout=20000)
                print("song 2 (.mpg):", _frame_shown(page), flush=True)
                page.screenshot(path=os.path.join(out_dir, pre + "jukebox_intro_copy.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
