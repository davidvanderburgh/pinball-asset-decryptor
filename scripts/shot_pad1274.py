"""PAD-1274 proof shots: the clips of one of the game's own modes play on a click.

    python scripts/shot_pad1274.py <repo> <outdir> <prefix> [<mode id>] [<project>]

The PAD-1064 rig (scripts/shot_pad1064.py: the Godzilla Pro 1.16 card, a video-only extract of it) on the Modes tab,
the game's mode <mode id> (default 1, Godzilla Multiball). Three shots, <prefix>_<screen>.png in <outdir>:

  modes_how    the page's How it works with its "Clips it plays" (after: each one a button)
  clip_player  the first clip clicked (after: a player plays it, Previous / Next, the list to pick from)
  video_tab    "Open on the Video tab" pressed (after: the Video tab, the clip picked); before: the Video tab as a
               user would go to it by hand, nothing picked

Prints what the player did (the <video>'s source, its time after a few seconds) so a shot is not the only proof.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"
PROJECT = r"D:\Pinball\pad1064_gzpro116"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    outdir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    mode_id = sys.argv[4] if len(sys.argv) > 4 else "1"
    project = sys.argv[5] if len(sys.argv) > 5 else PROJECT
    print("repo", repo, flush=True)
    os.makedirs(outdir, exist_ok=True)
    shot = lambda page, name: (page.mouse.move(5, 1290), time.sleep(1),
                               page.screenshot(path=os.path.join(outdir, "%s_%s.png" % (prefix, name))),
                               print("shot", name, flush=True))
    scratch = tempfile.mkdtemp(prefix="pad1274-")
    launcher = os.path.join(scratch, "launch1274.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            deadline = time.time() + 240
            while time.time() < deadline and not webui_shot.api(url, "modes.select", mode_id, "game"):
                time.sleep(3)
            page.wait_for_selector("text=Sounds and callouts it plays", timeout=180000)
            time.sleep(3)
            shot(page, "modes_how")
            first = page.locator(".modes-how-clips .modes-how-clip").first
            name = first.inner_text().strip()
            print("first clip", name, "tag", first.evaluate("e => e.tagName"),
                  "clickable", page.locator("button.modes-how-clip").count(), flush=True)
            first.click()
            time.sleep(1)
            dialog = page.locator(".modal, [role=dialog]").filter(has=page.locator("video, .hint"))
            if dialog.count():
                try:
                    page.wait_for_function(
                        "(() => { const v = document.querySelector('.modes-clip-player video');"
                        " return v && v.currentTime > 1; })()", timeout=90000)
                except Exception as e:                       # noqa: BLE001
                    print("player did not reach 1 s:", e, flush=True)
                info = page.evaluate("(() => { const v = document.querySelector('.modes-clip-player video');"
                                     " return v ? {src: decodeURIComponent(v.currentSrc).split('&p=')[1],"
                                     " t: v.currentTime, w: v.videoWidth, h: v.videoHeight, err: v.error && v.error.code}"
                                     " : {hint: (document.querySelector('.modes-clip-player') || {}).innerText}; })()")
                print("player", json.dumps(info), flush=True)
                page.locator("button", has_text="Next").first.click()
                time.sleep(2)
                print("after Next title", page.locator(".modal .hd, .modal-title, .modal h2").first.inner_text()
                      if page.locator(".modal .hd, .modal-title, .modal h2").count() else "?", flush=True)
                page.locator("button", has_text="Previous").first.click()
                time.sleep(4)
            else:
                print("no player opened", flush=True)
            shot(page, "clip_player")
            jump = page.locator("button", has_text="Open on the Video tab")
            if jump.count():
                jump.first.click()
            else:
                page.keyboard.press("Escape")
                webui_shot.api(url, "ui.select_tab", "video")
            try:
                page.wait_for_selector("text=%s" % name, timeout=60000)
            except Exception:                                # noqa: BLE001
                pass
            time.sleep(6)
            shot(page, "video_tab")
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
