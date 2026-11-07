"""PAD-1040 proof shot: the Expression lights tab - the cabinet's light shows, made from a song.

    python scripts/shot_pad1040.py <repo> <out.png> [--tab attract|lights] [--auto STYLE] [--at SECONDS] [--step]

Serves <repo> on a scratch project made from the Led Zeppelin LE 1.22 card (its .extract_source.json names it), whose
audio folder holds one song at a Zeppelin song slot (a stand-in music file: the project has no extract of its own), and
shows the tab. Before (main) the rail has no Expression lights; after, the tab with a show made from the song
(--auto), the cabinet drawn as the card's program places its blades and speaker lights, played to --at seconds.

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
SLOT = 384
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, dflt):
    a = sys.argv[3:]
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else dflt


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    tab = _arg("--tab", "lights")
    style = _arg("--auto", "")
    at = float(_arg("--at", "0"))
    scratch = tempfile.mkdtemp(prefix="pad1040-")
    project = os.path.join(scratch, "project")
    os.makedirs(os.path.join(project, "audio"))
    shutil.copyfile(SONG, os.path.join(project, "audio", "idx%04d.wav" % SLOT))
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.22.0"}, f)
    launcher = os.path.join(scratch, "launch1040.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", tab)
            time.sleep(8)
            if tab == "lights":
                webui_shot.api(url, "audio.scan")
                for _ in range(60):                     # the cabinet's lights read off the card (cached after)
                    time.sleep(1)
                    if page.locator(".xl-cab").count():
                        break
                webui_shot.api(url, "lights.new_show", "rock", SLOT)
                time.sleep(2)
                if style:
                    webui_shot.api(url, "lights.auto_show", 0, style)
                    page.wait_for_function("!document.body.innerText.includes('Listening…')", timeout=180000)
                    time.sleep(2)
                if at > 0:
                    page.fill(".xl-scrub", str(int(at * 1000)))
                    page.dispatch_event(".xl-scrub", "input")
                    time.sleep(1)
                if "--step" in sys.argv[3:]:
                    bars = page.locator(".xl-lane").first.locator(".xl-bar")
                    if bars.count() > 4:
                        bars.nth(4).click()
                        time.sleep(1)
                page.mouse.move(5, 995)
                time.sleep(1)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
