"""PAD-1410 proof shot: New mode > C, the step that hands a mode to an AI agent.

    python scripts/shot_pad1410.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). An
Uncanny X-Men LE 0.98 project with one blocks mode. Writes <out_dir>/<prefix>_new_c.png: the C step, with "It is a
game I wrote in MPF" ticked where the page has it (after: the porting guide beside the SDK's guide).
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

CARD = r"D:\Pinball\images\Stern\spike2\uncanny_xmen_le-0_98_0.Release.16G.sdcard.raw"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    scratch = tempfile.mkdtemp(prefix="pad1410-")
    project = os.path.join(scratch, "X-Men LE 0.98 Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    BM.new_blocks_mode(project, "DANGER ROOM")
    proc, url = S._serve(repo, scratch, project)
    try:
        def new_c(page):
            time.sleep(4)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            page.locator(".modes-list .hd button", has_text="New").first.click()
            time.sleep(1)
            page.locator('.nmw-tile[data-kind="c"]').first.click()
            time.sleep(0.8)
            page.locator("#nmw-c-name").fill("UNCANNY STORY")
            page.locator(".nmw-brief").fill("Port my MPF game (config.yaml and modes/) to PAD: the whole game.")
            mpf = page.locator(".nmw-mpf input")
            if mpf.count():
                mpf.first.check()
            time.sleep(0.8)
            out = os.path.join(out_dir, "%s_new_c.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, new_c)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
