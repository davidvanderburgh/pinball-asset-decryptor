"""PAD-699 proof shots: the Modes tab's pages of the game's own battles on David's Heisei card.

    python scripts/shot_pad699.py <repo> <out_dir> <prefix> [<stock.json>]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
project on David's "Godzilla Premium 1.16 Heisei Custom V1.99D Kaiju Edition" card holding a copy of the modes in
"HEISEI v1.99D + daveyvandy modes" (settings and sources only, no clips or sounds - his folder is never touched) and,
when given, <stock.json> as its modes/stock.json (the shot changes of the game's own modes). Writes into <out_dir>:

- <prefix>_gigan.png       Battle vs Gigan's page (its Shots section)
- <prefix>_megalon.png     Battle vs Megalon's page (SpaceGodzilla on the Heisei card)
- <prefix>_ebirah.png      Battle vs Ebirah's page (Biollante on the Heisei card)
"""

import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad664 as S664  # noqa: E402
import shot_pad666 as S6  # noqa: E402

CARD = r"C:\Users\david\OneDrive\Desktop\Godzilla Premium 1.16 Heisei Custom V1.99D Kaiju Edition.raw"
PAGES = (("gigan", "Battle vs Gigan"), ("megalon", "Battle vs Megalon"), ("ebirah", "Battle vs Ebirah"))


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    stock = sys.argv[4] if len(sys.argv) > 4 else ""
    os.makedirs(out_dir, exist_ok=True)
    print("serving", repo, flush=True)
    S6.CARD = CARD
    scratch = tempfile.mkdtemp(prefix="pad699-")
    project = S6._project(scratch)
    print("modes", S664._copy_modes(S664.HEISEI, project), flush=True)
    if stock:
        shutil.copy2(stock, os.path.join(project, "modes", "stock.json"))
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(5)
            S6._hide_log(page)
            grp = page.locator("button.modes-list-grp", has_text="The game's own")
            if grp.count() and grp.first.get_attribute("aria-expanded") == "false":
                grp.first.click()
                time.sleep(1)
            for name, label in PAGES:
                row = page.locator(".modes-list .li", has_text=re.compile("^%s$" % re.escape(label)))
                if not row.count():
                    print("no row", label, flush=True)
                    continue
                row.first.click()
                time.sleep(3)
                shots = page.locator(".modes-editor .modes-sec", has_text="Shots")
                if shots.count():
                    shots.first.scroll_into_view_if_needed()
                page.mouse.move(5, 990)
                time.sleep(1)
                out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
                page.screenshot(path=out)
                print("shot", out, flush=True)
        S._shoot(url, go, height=1000)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
