"""PAD-1068 proof shot: the game's own expression light show plays with its song after a slow Audio scan.

    python scripts/shot_pad1068.py <repo> <out dir> <before|after>

BEN (Led Zeppelin 1.21): the page offered to play the song with the lights but he heard nothing; his log had an
Audio scan that ran 117 s. The page waited at most 120 s for the scan and never looked again. This serves <repo> on a
scratch project made from the Led Zeppelin LE 1.22 card (as scripts/shot_pad1063.py), a stand-in song at slot 382
(the song the game's 4:49 show plays with), the Audio scan held back 130 s as a slow PC's would be, then opens the
Expression lights tab, picks the game's first show, presses Play and writes <before|after>_lights.png. It prints
whether the page's <audio> is playing.

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
SLOT = 382
SCAN_DELAY = 130
LAUNCHER = r'''
import sys, time
sys.path.insert(0, %r)
from pinball_decryptor.core import audio_slots
_scan = audio_slots.scan_audio_slots
def slow_scan(*a, **k):                                 # a slow PC's first scan (BEN's took 117 s and more)
    time.sleep(%d)
    return _scan(*a, **k)
audio_slots.scan_audio_slots = slow_scan
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _top(page):
    page.evaluate("document.querySelectorAll('*').forEach((e) => { if (e.scrollTop) e.scrollTop = 0; })")
    time.sleep(0.5)


def main():
    repo, outdir, which = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    print("serving", repo, flush=True)
    os.makedirs(outdir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1068-")
    project = os.path.join(scratch, "project")
    os.makedirs(os.path.join(project, "audio"))
    shutil.copyfile(SONG, os.path.join(project, "audio", "idx%04d.wav" % SLOT))
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.22.0"}, f)
    launcher = os.path.join(scratch, "launch1068.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, SCAN_DELAY))
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
            browser = p.chromium.launch(channel="msedge", args=["--autoplay-policy=no-user-gesture-required",
                                                                "--mute-audio"])
            page = browser.new_page(viewport={"width": 1500, "height": 1250})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            t0 = time.time()
            webui_shot.api(url, "ui.select_tab", "lights")     # the page starts the Audio scan itself
            page.wait_for_selector(".xl-li-game", timeout=300000)
            while time.time() - t0 < SCAN_DELAY + 30:          # the scan is in, and the page's old wait is over
                time.sleep(2)
            page.locator(".xl-li-game").first.click()
            time.sleep(2)
            page.get_by_role("button", name="Play").first.click()
            time.sleep(8)
            playing = page.evaluate("(() => { const a = document.querySelector('.xl-stage audio');"
                                    " return a ? {src: a.getAttribute('src') || '', paused: a.paused,"
                                    " t: a.currentTime} : null; })()")
            print("audio element:", playing, flush=True)
            print("not one of this project's songs shown:",
                  page.get_by_text("not one of this project's songs").count() > 0, flush=True)
            page.mouse.move(5, 1245)
            _top(page)
            page.screenshot(path=os.path.join(outdir, "%s_lights.png" % which))
            print("shot in", outdir, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
