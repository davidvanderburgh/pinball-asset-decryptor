"""PAD-720 proof shot: the Modes tab on a card whose file was renamed in Stern's form after another title.

    python scripts/shot_pad720.py <repo> <out_dir> <prefix> <card> [--moved]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
<card> is a Spike 2 card image whose file name parses as a Stern name of a game no card has, e.g. a copy of the
stock X-Men LE 0.98 card saved as ``silentcorp_ANIMATED_SERIES_xmen_le-0_98_0.raw`` (the reporter's file name). A
project extracted from it opens on the Modes tab. Its record carries what the extract stamps into it: the card's
version and its own index name (``stock.sidx``). With ``--moved`` the record names the card in a folder it is no
longer in (the reporter's state: no "[card] read" line in their log). Writes ``<out_dir>/<prefix>_modes.png``.
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
import shot_pad666 as S6  # noqa: E402


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    card = os.path.abspath(sys.argv[4])
    moved = "--moved" in sys.argv[5:]
    os.makedirs(out_dir, exist_ok=True)
    print("serving", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad720-")
    project = os.path.join(scratch, "New_Extract 4")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        path = os.path.join(r"E:\Pinball Code\Xmen", os.path.basename(card)) if moved else card
        json.dump({"input_path": path, "input_name": os.path.basename(card), "card_version": "0.98.0",
                   "stock": {"status": "modified", "label": "Uncanny Xmen LE 0.98",
                             "sidx": "uncanny_xmen_le-0_98_0.sidx",
                             "text": "Uncanny Xmen LE 0.98, modified"}}, f)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            S6._hide_log(page)
            # the card's own index is read off the UI loop: wait for the head to settle
            for _ in range(60):
                text = page.inner_text("body")
                if "Reading which game" not in text:
                    break
                time.sleep(1)
            time.sleep(3)
            body = page.inner_text("body")
            for line in body.splitlines():
                if "Card:" in line or "can't be made" in line:
                    print("page:", line.strip()[:300], flush=True)
            page.mouse.move(5, 1090)
            time.sleep(1)
            out = os.path.join(out_dir, "%s_modes.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
