"""PAD-798 proof shots: the game's own modes' AWARD numbers on the Modes tab (TMNT LE 1.59's Turtle Power).

    python scripts/shot_pad798.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
project on the stock TMNT LE 1.59 card; the Modes tab lists the game's own modes, and Turtle Power's page shows its
numbers. Before PAD-798 a crule title's award record numbers were read-only ("which part of the award record this
is isn't decoded"); after, each level's value, growth and cap is its own editable row. Writes into <out_dir>:

- <prefix>_game_mode_awards.png    Turtle Power's page on the Modes tab
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

CARD = r"D:\Pinball\images\Stern\spike2\turtles_le-1_59_0.Release.8G.sdcard.raw"
MODE = "Turtle Power"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    print("serving", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad798-")
    S6.CARD = CARD
    project = S6._project(scratch)
    os.rename(project, os.path.join(scratch, "TMNT LE 1.59 Extract"))
    project = os.path.join(scratch, "TMNT LE 1.59 Extract")
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(6)
            S6._hide_log(page)
            group = page.get_by_text(re.compile(r"the game's own", re.I))
            if group.count():
                group.first.click()             # the game's own modes are folded under their heading
                time.sleep(2)
            for _ in range(30):                 # the card's rules are read on first open
                row = page.locator(".modes-list .li", has_text=re.compile(r"^\s*%s\s*$|%s" % (MODE, MODE)))
                if row.count():
                    break
                time.sleep(2)
            print("rows for %s:" % MODE, row.count(), flush=True)
            if row.count():
                row.first.click()
                time.sleep(3)
            label = page.get_by_text("Award level 1 value", exact=False)
            if not label.count():
                label = page.get_by_text("award value", exact=False)
            print("award rows on the page:", label.count(), flush=True)
            if label.count():
                label.first.evaluate("e => e.scrollIntoView({block: 'start'})")
            page.mouse.move(5, 1090)
            time.sleep(1)
            out = os.path.join(out_dir, "%s_game_mode_awards.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
