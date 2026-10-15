"""PAD-589 proof shots: the Modes tab's Tips, where they said "not yet".

    python scripts/shot_pad589.py <repo> <out_dir> <prefix> [--page]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots). A Godzilla Pro 1.15 project with no mode yet. Writes into <out_dir>:

- <prefix>_tips_which.png     "Which games": the Deadpool LE 1.14 / Iron Maiden LE 1.16 rows and the notes
- <prefix>_tips_machine.png   "What a mode can and can't do", The machine: Move the building
- <prefix>_tips_slot.png      Example 1, the battle slot
- <prefix>_tips_asking.png    "Asking for more"
- <prefix>_slot_page.png      (--page) a Godzilla Premium/LE 1.16 mode's page at its battle slot
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402


def _shot(page, out_dir, prefix, name):
    out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
    page.screenshot(path=out)
    print("shot", out, flush=True)


def _toc(page, words):
    page.locator(".sx-toc button", has_text=words).first.click()
    time.sleep(0.8)


def _to(page, text):
    """Scroll the Tips window so the first element saying ``text`` is near its top."""
    loc = page.get_by_text(text, exact=False).first
    loc.scroll_into_view_if_needed()
    loc.evaluate("e => e.scrollIntoView({block: 'start'})")
    time.sleep(0.6)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)

    scratch = tempfile.mkdtemp(prefix="pad589-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    proc, url = S._serve(repo, scratch, project)
    try:
        def tips(page):
            page.locator(".sx-help").first.click()
            time.sleep(2)
            _toc(page, "Which games")
            _to(page, "Deadpool LE 1.14")
            _shot(page, out_dir, prefix, "tips_which")
            _to(page, "Countdown no:")
            _shot(page, out_dir, prefix, "tips_which_notes")
            _toc(page, "can't do")
            _to(page, "Hold the ball on Godzilla")
            _shot(page, out_dir, prefix, "tips_machine")
            _to(page, "You can take over a slot instead")
            _shot(page, out_dir, prefix, "tips_slot")
            _to(page, "Hit a wall that isn't here")
            _shot(page, out_dir, prefix, "tips_asking")
        S._shoot(url, tips, height=1000)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
