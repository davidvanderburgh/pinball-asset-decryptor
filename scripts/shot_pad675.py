"""PAD-675 proof shot: New mode > Blocks on a Godzilla Premium/LE 1.16 project.

    python scripts/shot_pad675.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Writes
<prefix>_new_blocks.png into <out_dir>: the wizard's Blocks step with the examples it offers (before: the Godzilla
modes converted from C; after: TARGET RUSH alone).
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad658 as G  # noqa: E402


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad675-")
    project = G._project(scratch)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            time.sleep(4)
            G._hide_log(page)
            # a project with no modes: its first-mode page has the wizard's tiles; Blocks opens its step
            page.locator('.nmw-tile[data-kind="blocks"]').first.click(timeout=15000)
            time.sleep(1)
            out = os.path.join(out_dir, "%s_new_blocks.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
