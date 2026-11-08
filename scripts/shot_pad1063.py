"""PAD-1063 proof shots: the Expression lights tab with the game's own shows.

    python scripts/shot_pad1063.py <repo> <out dir> <before|after>

Serves <repo> on a scratch project made from the Led Zeppelin LE 1.22 card (as scripts/shot_pad1040.py), its audio
folder holding a stand-in song at slot 291 (the song Led Zeppelin plays by request 63) and writes two shots:

  <before|after>_lights.png       the tab, nothing picked: before, "No shows yet" (BEN's screenshot); after, the game's
                                  own shows listed under the project's, request 63's Original picked and played 30 s in
  <before|after>_lights_step.png  a show's step: before, a ready-made show's; after, a show made from the game's own
                                  (Make it a show of mine), its game step open

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
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

CARD = r"D:\Pinball\images\Stern\spike2\led_zeppelin_le-1_22_0.Release.8G.sdcard.raw"
SONG = r"D:\Pinball\pad455_extract\gzpro116\audio\idx0095.wav"
SLOT = 291
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _top(page):
    page.evaluate("document.querySelectorAll('*').forEach((e) => { if (e.scrollTop) e.scrollTop = 0; })")
    time.sleep(0.5)


def _scrub(page, ms):
    page.fill(".xl-scrub", str(int(ms)))
    page.dispatch_event(".xl-scrub", "input")
    time.sleep(1.5)


def main():
    repo, outdir, which = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(outdir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1063-")
    project = os.path.join(scratch, "project")
    os.makedirs(os.path.join(project, "audio"))
    shutil.copyfile(SONG, os.path.join(project, "audio", "idx%04d.wav" % SLOT))
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.22.0"}, f)
    launcher = os.path.join(scratch, "launch1063.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1250})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "lights")
            time.sleep(4)
            webui_shot.api(url, "audio.scan")
            for _ in range(90):                         # the cabinet's lights read off the card (cached after)
                time.sleep(1)
                if page.locator(".xl-cab").count():
                    break
            if which == "after":                        # the game's own shows: seconds, once per card
                page.wait_for_selector(".xl-li-game", timeout=240000)
                page.locator(".xl-li-game").nth(1).click()          # request 63: the song at slot 291
                time.sleep(3)
                _scrub(page, 30000)
            else:
                time.sleep(4)
            page.mouse.move(5, 1245)
            _top(page)
            page.screenshot(path=os.path.join(outdir, "%s_lights.png" % which))
            if which == "after":
                page.get_by_text("Make it a show of mine").click()
            else:
                webui_shot.api(url, "lights.new_show", "rock", SLOT)
            time.sleep(3)
            page.locator(".xl-lane").first.locator(".xl-bar").first.click()
            time.sleep(1)
            _scrub(page, 30000)
            page.mouse.move(5, 1245)
            _top(page)
            page.screenshot(path=os.path.join(outdir, "%s_lights_step.png" % which))
            print("shots in", outdir, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
