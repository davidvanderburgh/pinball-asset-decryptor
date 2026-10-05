"""PAD-386 proof shots: the Tips window on the Modes tab, and its "What a mode can and can't do".

    python scripts/shot_pad386.py <repo> <out_dir> <prefix> [--link]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots). A Godzilla Pro 1.15 project with no mode yet. Writes into <out_dir>:

- <prefix>_tips_top.png     the ? button's Tips window, at the top of the Modes tips
- <prefix>_tips_limits.png  what a mode can and can't do: with --link, through the first
                            mode's page's link (the ticket's change); without it, the
                            window's own contents entry (main's link hands the file to
                            another app, which a shot must not open)
- <prefix>_tips_making.png  Making a mode
- <prefix>_tips_tryit.png   Try it
- <prefix>_tips_which.png   Which games
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


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    link = "--link" in sys.argv[4:]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)

    scratch = tempfile.mkdtemp(prefix="pad386-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    proc, url = S._serve(repo, scratch, project)
    try:
        def tips(page):
            if link:
                page.get_by_role("button", name="What a mode can and can't do").first.click()
                time.sleep(2)
                _shot(page, out_dir, prefix, "tips_limits")
                page.keyboard.press("Escape")
                time.sleep(0.8)
            page.locator(".sx-help").first.click()
            time.sleep(2)
            _shot(page, out_dir, prefix, "tips_top")
            if not link:
                _toc(page, "can't do")
                _shot(page, out_dir, prefix, "tips_limits")
            _toc(page, "Making a mode")
            _shot(page, out_dir, prefix, "tips_making")
            _toc(page, "Try it")
            _shot(page, out_dir, prefix, "tips_tryit")
            _toc(page, "Which games")
            _shot(page, out_dir, prefix, "tips_which")
        S._shoot(url, tips, height=1000)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
