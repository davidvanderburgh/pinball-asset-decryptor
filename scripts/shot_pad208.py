"""PAD-208 proof shots: the right-click menu on an Images, Video and Audio row.

    python scripts/shot_pad208.py <out_dir> <prefix>

Writes <out_dir>/<prefix>_images.png, _video.png, _audio.png.  A scratch JJP
project of loose files (a few PNGs, WAVs and MP4s made on the spot); no card.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402


def _make_project(project):
    from PIL import Image
    for sub in ("images", "audio", "video"):
        os.makedirs(os.path.join(project, sub))
    for k in range(4):
        Image.new("RGB", (320, 180), (40 * k, 80, 140)).save(
            os.path.join(project, "images", "attract_%02d.png" % k))
        with wave.open(os.path.join(project, "audio",
                                    "callout_%02d.wav" % k), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\0\0" * 22050)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             "testsrc=size=320x180:rate=30:duration=1",
             "-pix_fmt", "yuv420p",
             os.path.join(project, "video", "clip_%02d.mp4" % k)],
            check=True)
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(project)


def main():
    out_dir = os.path.abspath(sys.argv[1])
    prefix = sys.argv[2]
    print("repo", REPO, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad208-")
    project = os.path.join(scratch, "Sonic Extracted")
    _make_project(project)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {
                       "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch,
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            for tab in ("images", "video", "audio"):
                webui_shot.api(url, "ui.select_tab", tab)
                webui_shot.api(url, "%s.scan" % tab)
                time.sleep(5)
                row = page.locator(".tbl .tr.click:visible").nth(1)
                row.click()
                time.sleep(1)
                box = row.bounding_box()
                page.mouse.click(box["x"] + 120, box["y"] + box["height"] / 2,
                                 button="right")
                time.sleep(1.5)
                out = os.path.join(out_dir, "%s_%s.png" % (prefix, tab))
                page.screenshot(path=out)
                print("shot", out, os.path.getsize(out), flush=True)
                page.keyboard.press("Escape")
                time.sleep(0.5)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
