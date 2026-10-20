"""PAD-652 proof shots: making a new mode on the Modes tab.

    python scripts/shot_pad652.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
Godzilla Pro 1.15 project on the stock card. Writes into <out_dir>:

- <prefix>_first_mode.png   a project with no mode yet: the page that offers the ways to make one
- <prefix>_new_mode.png     a project with a mode: New pressed (before, its drop-down; after, the wizard's tiles)
- <prefix>_new_blocks.png   after only: the wizard's second step for Blocks (name + where it starts from)
- <prefix>_new_form.png     after only: the wizard's second step for Form (blank, or a form example)
- <prefix>_new_c.png        after only: the wizard's second step for C
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

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"


def _project(scratch):
    project = os.path.join(scratch, "GZ 1.15 Pro Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    return project


def _hide_log(page):
    hide = page.get_by_text("Hide log")
    if hide.count():
        hide.first.click()
        time.sleep(1)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    # 1. no mode yet
    scratch = tempfile.mkdtemp(prefix="pad652a-")
    project = _project(scratch)
    proc, url = S._serve(repo, scratch, project)
    try:
        def first(page):
            time.sleep(4)
            _hide_log(page)
            shot(page, "first_mode")
        S._shoot(url, first)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)

    # 2. one mode: New
    scratch = tempfile.mkdtemp(prefix="pad652b-")
    project = _project(scratch)
    BM.new_blocks_mode(project, "KAIJU RAMPS", example="ramps")
    proc, url = S._serve(repo, scratch, project)
    try:
        def new(page):
            time.sleep(4)
            _hide_log(page)
            page.locator(".modes-list .hd button", has_text="New").first.click()
            time.sleep(1)
            shot(page, "new_mode")
            tiles = page.locator(".nmw-tile")
            if not tiles.count():
                return
            for kind, name in (("blocks", "new_blocks"), ("c", "new_c"), ("form", "new_form")):
                page.locator('.nmw-tile[data-kind="%s"]' % kind).first.click()
                time.sleep(0.8)
                shot(page, name)
                page.locator(".nmw button", has_text="Back").first.click()
                time.sleep(0.5)
        S._shoot(url, new)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
