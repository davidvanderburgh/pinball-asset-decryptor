"""PAD-834 proof shots: the game's own modes in the Modes tab's list, every one of them.

    python scripts/shot_pad834.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a checkout of main for the "before" shots). A
project on the stock Jurassic Park LE 1.16 card, then one on Iron Maiden LE 1.18; the Modes tab's list with
"The game's own" unfolded. Before PAD-834 the reader found 11 of Jurassic Park's 24 modes and the list left out
every mode with nothing to change (Jurassic Park showed Escape Nublar alone, Iron Maiden no Two Minutes to
Midnight). The game rules are read into a scratch title cache, so each tree reads them with its own reader.
Writes into <out_dir>:

- <prefix>_modes_list_jurassic_park.png
- <prefix>_modes_list_iron_maiden.png
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
import shot_pad666 as S6  # noqa: E402

CARDS = {
    "jurassic_park": (r"D:\Pinball\images\Stern\spike2\jurassic_park_le-1_16_0.Release.8G.sdcard.raw",
                      "JP LE 1.16 Extract"),
    "iron_maiden": (r"D:\Pinball\images\Stern\spike2\iron_maiden_le-1_18_0.Release.8G.sdcard.raw",
                    "Iron Maiden LE 1.18 Extract"),
}


def shoot(repo, out_dir, prefix, key):
    card, name = CARDS[key]
    scratch = tempfile.mkdtemp(prefix="pad834-")
    os.environ["PAD_TITLE_CACHE"] = os.path.join(scratch, "titles")
    S6.CARD = card
    project = S6._project(scratch)
    os.rename(project, os.path.join(scratch, name))
    project = os.path.join(scratch, name)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            S6._hide_log(page)
            group = page.locator(".modes-list .modes-list-grp", has_text=re.compile(r"the game's own", re.I))
            for _ in range(60):                 # the card's rules are read on first open
                if group.count():
                    break
                time.sleep(2)
            time.sleep(2)
            if group.count() and group.first.get_attribute("aria-expanded") == "false":
                group.first.click()             # folded when there are many
                time.sleep(2)
            rows = page.locator(".modes-list .li.game")
            print(key, "game rows:", rows.count(), flush=True)
            print("  ", [t.strip() for t in rows.all_inner_texts()], flush=True)
            page.mouse.move(5, 1590)
            time.sleep(1)
            out = os.path.join(out_dir, "%s_modes_list_%s.png" % (prefix, key))
            page.locator(".modes-list").screenshot(path=out)
            print("shot", out, flush=True)
            bare = page.locator(".modes-list .li.game.bare")
            if bare.count():                    # a mode with nothing to change opens and says why
                bare.last.click()
                time.sleep(2)
                print("  opened", bare.last.inner_text().strip(), "->",
                      [t for t in page.locator("main").all_inner_texts()
                       if "nothing" in t.lower()][:1] and "says nothing to change" or "no reason shown",
                      flush=True)
        S._shoot(url, go, height=1600)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    print("serving", repo, flush=True)
    for key in sys.argv[4:] or CARDS:
        shoot(repo, out_dir, prefix, key)


if __name__ == "__main__":
    main()
