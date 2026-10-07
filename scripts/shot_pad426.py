"""PAD-426 proof shots: does the app tell an official Stern card from a build of it?

    python scripts/shot_pad426.py <repo> <out_dir>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for
the "before" shots).  Two shots, each of one card on the page:

* ``select_card.png`` - Select card's "Card details" for a shared custom Godzilla card
  (DragonRR's Heisei build; its update index still says Godzilla LE 1.16).
* ``extract.png`` - the Extract tab's "This project" card for a scratch project
  extracted from that card.  Its ``.extract_source.json`` carries the verdict an
  extract stamps (the "before" code ignores the key).

Set PAD426_CARD to another card image to point the shots at it.
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

CARD = os.environ.get("PAD426_CARD") or os.path.expanduser(
    r"~\OneDrive\Desktop\Godzilla Premium 1.16 Heisei Custom V1.93 Orchestral Edition.raw")
STAMP = os.environ.get("PAD426_STAMP") or ""


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad426-")
    project = os.path.join(scratch, "Heisei")
    os.makedirs(os.path.join(project, "audio"))
    rec = {"input_path": CARD, "input_name": os.path.basename(CARD),
           "size": os.path.getsize(CARD), "mtime": int(os.path.getmtime(CARD)),
           "card_version": "1.16.0"}
    if STAMP:
        with open(STAMP, encoding="utf-8") as f:
            rec["stock"] = json.load(f)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)
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
            webui_shot.api(url, "ui.select_tab", "card")
            time.sleep(2)
            webui_shot.api(url, "card.look", CARD, True)
            for _ in range(120):
                time.sleep(1)
                if page.locator(".c-info").count() and "loading" not in (
                        page.locator(".c-info").inner_text() or "").lower():
                    if "Firmware" in page.locator(".c-info").inner_text():
                        break
            time.sleep(2)
            page.locator(".c-info").screenshot(path=os.path.join(out_dir, "select_card.png"))
            print("shot select_card", flush=True)
            webui_shot.api(url, "ui.select_tab", "extract")
            time.sleep(2)
            webui_shot.api(url, "extract.refresh_project")
            time.sleep(6)
            page.locator(".x-project").screenshot(path=os.path.join(out_dir, "extract.png"))
            print("shot extract", flush=True)
            browser.close()
            if errors:
                print("PAGE ERRORS:", errors, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
