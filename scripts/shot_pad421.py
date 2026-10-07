"""PAD-421 proof shot: the Extract tab with a card picked that is not the one the project
folder was extracted from.

    python scripts/shot_pad421.py <repo> <out.png>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot).  A scratch project holds an extract of the stock Godzilla LE 1.16 card (its
``.extract_source.json`` and ``.checksums.md5``); the Extract tab's card is a different
Godzilla card (DragonRR's custom one, by name; a stand-in file of a few bytes).
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

STOCK = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
CUSTOM = "Godzilla Premium 1.16 Heisei Custom V1.96 Standard Edition.raw"


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad421-")
    project = os.path.join(scratch, "EXTRACTED")
    os.makedirs(os.path.join(project, "audio"))
    stock = os.path.join(scratch, STOCK)
    custom = os.path.join(scratch, CUSTOM)
    for p, n in ((stock, 64), (custom, 96)):
        with open(p, "wb") as f:
            f.write(b"\0" * n)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": stock, "input_name": STOCK, "size": 64}, f)
    with open(os.path.join(project, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("d41d8cd98f00b204e9800998ecf8427e  audio/x.wav\n")
    proc, url = S._serve(repo, scratch, project)
    try:
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 760})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "extract")
            time.sleep(2)
            webui_shot.api(url, "extract.use_recent", "input", custom)
            time.sleep(4)
            webui_shot.api(url, "extract.refresh_project")
            time.sleep(3)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
