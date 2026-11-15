"""PAD-1288 proof shot: the Modes tab's Tips, "Which games", where the table ends.

    python scripts/shot_pad1287.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). A
Godzilla Pro 1.15 project with no mode yet (shot_pad232's). Writes <out_dir>/<prefix>_tips_which.png: the table's rows
around Elvira and Foo Fighters (Fallout LE 0.82 (Spike 3) between them when its port ships).
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)

    scratch = tempfile.mkdtemp(prefix="pad1288-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    proc, url = S._serve(repo, scratch, project)
    try:
        def tips(page):
            page.locator(".sx-help").first.click()
            time.sleep(2)
            page.locator(".sx-toc button", has_text="Which games").first.click()
            time.sleep(0.8)
            loc = page.get_by_text("Dungeons & Dragons Pro", exact=False).first
            loc.scroll_into_view_if_needed()
            loc.evaluate("e => e.scrollIntoView({block: 'start'})")
            time.sleep(0.6)
            out = os.path.join(out_dir, "%s_tips_which.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, tips, height=700)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
