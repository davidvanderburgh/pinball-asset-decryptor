"""PAD-427 proof shot: does the project say which revision it is, wherever it lives?

    python scripts/shot_pad427.py <repo> <out_dir>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for
the "before" shot).  One shot, ``extract.png``: the Extract tab's "This project" card for
a scratch project extracted from the official Godzilla Pro 1.16 card and built twice
since, then copied to another folder (the extract card's path no longer exists there).
Its ``.pad-lineage.json`` is the record a build leaves (the "before" code ignores it).

Set PAD427_CARD to another official card image to point the shot at it.
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

CARD = os.environ.get("PAD427_CARD") or \
    r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"

HEISEI = os.environ.get("PAD427_HEISEI") or \
    r"C:\tmp\pad167\Godzilla Premium 1.16 Heisei Custom V1.5 Orchestral Edition"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad427-")
    project = os.path.join(scratch, "Godzilla moved here")
    os.makedirs(os.path.join(project, "audio"))
    # Extracted on another computer: the card path it names is not on this one.
    gone = r"E:\Users\someone\Pinball\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"
    rec = {"input_path": gone, "input_name": os.path.basename(gone),
           "size": os.path.getsize(CARD), "mtime": 1700000000,
           "card_version": "1.16.0",
           "stock": {"status": "official", "label": "Godzilla Pro 1.16",
                     "sidx": "godzilla_pro-1_16_0.sidx",
                     "text": "Official Godzilla Pro 1.16 - every file matches the "
                             "card Stern released."}}
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)
    stock = "s" * 40
    lin = {"format": 1, "id": "5f1c0d2e9a7b4c3d8e6f0a1b2c3d4e5f",
           "stock": {"sidx": "godzilla_pro-1_16_0.sidx", "label": "Godzilla Pro 1.16",
                     "print": stock},
           "source": {"print": stock, "name": rec["input_name"], "status": "official",
                      "label": "Godzilla Pro 1.16", "rev": 0},
           "revs": [
               {"rev": 1, "print": "a" * 40, "parent": stock, "parent_rev": 0,
                "name": "Godzilla mods.raw", "built": "2026-10-05 21:12",
                "host": "GARAGE-PC", "app": "1.128.0"},
               {"rev": 2, "print": "b" * 40, "parent": "a" * 40, "parent_rev": 1,
                "name": "Godzilla mods.raw", "built": "2026-10-07 09:40",
                "host": "GARAGE-PC", "app": "1.129.0"}]}
    if os.environ.get("PAD427_RICH"):
        # a longer history: rev 3 went back to rev 1 on a laptop, rev 4 built on it,
        # and a mod pack from another project came in
        lin["revs"] += [
            {"rev": 3, "print": "c" * 40, "parent": "a" * 40, "parent_rev": 1,
             "name": "Godzilla louder callouts.raw", "built": "2026-10-08 18:05",
             "host": "LAPTOP", "app": "1.130.0"},
            {"rev": 4, "print": "d" * 40, "parent": "c" * 40, "parent_rev": 3,
             "name": "Godzilla louder callouts.raw", "built": "2026-10-09 20:31",
             "host": "LAPTOP", "app": "1.130.0"}]
        lin["imported"] = [{"id": "9" * 32, "from": "official Godzilla Pro 1.16",
                            "rev": 6, "print": "e" * 40, "pack": "kaiju lights.zip",
                            "at": "2026-10-08 17:50"}]
    with open(os.path.join(project, ".pad-lineage.json"), "w", encoding="utf-8") as f:
        json.dump(lin, f)
    with open(os.path.join(project, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("d41d8cd98f00b204e9800998ecf8427e  audio/x.wav\n")
    proc, url = S._serve(repo, scratch, project)
    try:
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1400})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "extract.use_recent", "input", CARD)
            webui_shot.api(url, "ui.select_tab", "extract")
            time.sleep(2)
            webui_shot.api(url, "extract.refresh_project")
            time.sleep(6)
            page.locator(".x-project").screenshot(path=os.path.join(out_dir, "extract.png"))
            print("shot extract", flush=True)
            if os.path.isdir(HEISEI):
                # the real Heisei extract's sidecars: what its card already carried
                heisei = os.path.join(scratch, "Heisei 1.5")
                os.makedirs(os.path.join(heisei, "video"))
                for rel in (".extract_source.json", ".checksums.md5",
                            os.path.join("video", "manifest.txt")):
                    shutil.copy(os.path.join(HEISEI, rel), os.path.join(heisei, rel))
                webui_shot.api(url, "extract.use_recent", "output", heisei)
                time.sleep(2)
                webui_shot.api(url, "extract.refresh_project")
                time.sleep(6)
                page.locator(".x-project").screenshot(
                    path=os.path.join(out_dir, "extract_offstock.png"))
                print("shot extract_offstock", flush=True)
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
