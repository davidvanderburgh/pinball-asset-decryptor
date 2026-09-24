"""PAD-211 proof shots: a project holding another card's extract (Extract Both
into the project folder) - the Audio tab's list and the Write tab's
"Before you build" notes.

    python scripts/shot_pad211.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (a pre-fix export for the before shots).
Writes <out_dir>/<prefix>_audio.png and <prefix>_write.png from a scratch
Stern project: four sounds, a clip and a picture, baselined, plus a nested
``star_wars_le-1_27_0.Boris_Release.8G.sdcard`` extract with its own baseline.
"""

import json
import os
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

NESTED = "star_wars_le-1_27_0.Boris_Release.8G.sdcard"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _wav(path, n):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(bytes([n % 250, 1]) * 22050)


def _blob(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _extract(folder, seed, video, picture):
    for i in range(4):
        _wav(os.path.join(folder, "audio", "idx%04d.wav" % i), seed + i)
    _blob(os.path.join(folder, "video", video), b"mov %d" % seed)
    _blob(os.path.join(folder, "images", picture), b"png %d" % seed)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.core import checksums
    scratch = tempfile.mkdtemp(prefix="pad211-")
    project = os.path.join(scratch, "SW_131_Sep26")
    _extract(project, 10, "Attract_BackgroundLoop.mov", "SternLogo.png")
    checksums.generate_checksums(project)
    nested = os.path.join(project, NESTED)
    _extract(nested, 90, "AM_SCENE_001.mov", "boot_screen/SternLogo.png")
    checksums.generate_checksums(nested)

    launcher = os.path.join(scratch, "launch211.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1560, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            for tab in ("video", "images", "audio"):
                webui_shot.api(url, "ui.select_tab", tab)
                time.sleep(5)
            out = os.path.join(out_dir, "%s_audio.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            webui_shot.api(url, "ui.select_tab", "write")
            time.sleep(6)
            out = os.path.join(out_dir, "%s_write.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
