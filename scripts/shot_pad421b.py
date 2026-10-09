"""PAD-421 round 4 proof shots: the Extract tab when the picked card was BUILT by PAD.

    python scripts/shot_pad421b.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  Writes into <out_dir>:

- <prefix>_moved_project.png  DragonRR's case: the 1.96 card was built from a project folder
  that was then copied next to it, and the first folder deleted; the copy is open.
- <prefix>_card_project.png   a card built from another project that is still on disk, with a
  different project open.

Stand-in card files of a few bytes; the build records are written the way a build writes them.
"""

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

STOCK = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
CUSTOM = "Godzilla Premium 1.16 Heisei Custom V1.96 Standard Edition.raw"


def _card(path, n):
    with open(path, "wb") as f:
        f.write(b"\0" * n)


def _extracted(folder, card):
    os.makedirs(os.path.join(folder, "audio"))
    st = os.stat(card)
    with open(os.path.join(folder, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card),
                   "size": st.st_size, "mtime": int(st.st_mtime)}, f)
    with open(os.path.join(folder, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("d41d8cd98f00b204e9800998ecf8427e  audio/x.wav\n")


def _built(card, project, stock):
    st = os.stat(stock)
    with open(card + ".pad-build.json", "w", encoding="utf-8") as f:
        json.dump({"version": 1, "building": False, "complete": True, "assets": project,
                   "stock": {"path": stock, "size": st.st_size, "mtime_ns": st.st_mtime_ns}}, f)


def _shoot(repo, scratch, project, card, out):
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
            webui_shot.api(url, "extract.use_recent", "input", card)
            time.sleep(4)
            webui_shot.api(url, "extract.refresh_project")
            time.sleep(3)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]

    # 1. DragonRR: built from a folder since copied beside the card and deleted
    scratch = tempfile.mkdtemp(prefix="pad421b-")
    stock = os.path.join(scratch, STOCK)
    _card(stock, 64)
    old = os.path.join(scratch, "BRAND NEW TEST 1.16 OG", "EXTRACTED")
    _extracted(old, stock)
    clean = os.path.join(scratch, "1.96 TEST CLEAN")
    os.makedirs(clean)
    custom = os.path.join(clean, CUSTOM)
    _card(custom, 96)
    _built(custom, old, stock)
    copy = os.path.join(clean, "EXTRACTED")
    shutil.copytree(old, copy)
    shutil.rmtree(os.path.dirname(old))
    _shoot(repo, scratch, copy, custom, os.path.join(out_dir, "%s_moved_project.png" % prefix))

    # 2. a card built from another project still on disk, a different project open
    scratch = tempfile.mkdtemp(prefix="pad421c-")
    stock = os.path.join(scratch, STOCK)
    _card(stock, 64)
    pro = os.path.join(scratch, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
    _card(pro, 80)
    heisei = os.path.join(scratch, "Heisei 1.96", "EXTRACTED")
    _extracted(heisei, stock)
    custom = os.path.join(scratch, CUSTOM)
    _card(custom, 96)
    _built(custom, heisei, stock)
    other = os.path.join(scratch, "Godzilla Pro mods", "EXTRACTED")
    _extracted(other, pro)
    _shoot(repo, scratch, other, custom, os.path.join(out_dir, "%s_card_project.png" % prefix))


if __name__ == "__main__":
    main()
