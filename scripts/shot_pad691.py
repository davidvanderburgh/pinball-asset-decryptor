"""PAD-691 proof shots: New mode's Form and C steps on a Godzilla Premium/LE 1.16 project.

    python scripts/shot_pad691.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). Writes
into <out_dir>:

- <prefix>_new_form.png    New, then Form: the examples it offers (before: Godzilla's four; after: TARGET RUSH)
- <prefix>_new_c.png       New, then C: the C examples beside the blank mode (before: Godzilla's; after: none)
- <prefix>_new_blocks.png  New, then Blocks: TARGET RUSH, as before
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
    scratch = tempfile.mkdtemp(prefix="pad691-")
    project = G._project(scratch)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            time.sleep(4)
            G._hide_log(page)
            for kind in ("form", "c", "blocks"):
                # a project with no modes: its first-mode page has the wizard's tiles
                page.locator('.nmw-tile[data-kind="%s"]' % kind).first.click(timeout=15000)
                time.sleep(1)
                out = os.path.join(out_dir, "%s_new_%s.png" % (prefix, kind))
                page.screenshot(path=out)
                print("shot", out, flush=True)
                page.get_by_role("button", name="Cancel").last.click(timeout=5000)
                time.sleep(1)
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
