"""PAD-207 proof shot: the Images tab sorted by Resolution (largest first).

    python scripts/shot_pad207.py <out.png>

A scratch project of plain PNGs at the ticket's resolutions (892x760 has more
pixels than 1920x316, which is the case the reporter tripped on); no card.
"""

import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402

SIZES = [(1920, 1080), (1920, 700), (1920, 316), (1920, 100), (1360, 1000),
         (892, 760), (720, 1200), (1080, 1920), (640, 360), (64, 64)]


def main():
    out = os.path.abspath(sys.argv[1])
    scratch = tempfile.mkdtemp(prefix="pad207-")
    project = os.path.join(scratch, "Godzilla Extracted")
    img = os.path.join(project, "images")
    os.makedirs(img)
    from PIL import Image
    for k, (w, h) in enumerate(SIZES):
        Image.new("RGB", (w, h), (20 * k, 60, 120)).save(
            os.path.join(img, "picture_%02d.png" % k))
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(project)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project,
                       "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch,
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "images")
        webui_shot.api(url, "images.scan")
        time.sleep(4)
        webui_shot.api(url, "images.sort", "res")
        time.sleep(1)
        st = webui_shot.state(url)["images"]
        print("sort", st.get("sort"), "status", st.get("status"), flush=True)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1280, "height": 1400})
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            time.sleep(3)
            page.screenshot(path=out)
            browser.close()
        print("shot", out, os.path.getsize(out), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
