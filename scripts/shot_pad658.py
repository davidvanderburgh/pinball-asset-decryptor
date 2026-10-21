"""PAD-658 proof shots: the modes in blocks on a Godzilla Premium/LE 1.16 project.

    python scripts/shot_pad658.py <repo> <out_dir> <prefix> [films_dir]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
Godzilla LE 1.16 project on the stock card. Where the tree has blocks examples (block_modes.example_names) every
one is added as blocks (cut from the films in films_dir when given); otherwise the C examples are added, as a
project had them before. Writes into <out_dir>:

- <prefix>_new_blocks.png   New, then Blocks: the wizard's step that makes a blocks mode (after: and its examples)
- <prefix>_modes_list.png   the project's list of modes
- <prefix>_destoroyah.png   DESTOROYAH open (before: its C; after: its blocks)
- <prefix>_<slug>.png       after only: each new mode open in the block editor (king_caesar, kumonga, minilla,
                            kamacuras)
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

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
NEW = ("king_caesar", "kumonga", "minilla", "kamacuras")


def _project(scratch):
    project = os.path.join(scratch, "GZ 1.16 LE Extract")
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
    films = sys.argv[4] if len(sys.argv) > 4 else ""
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import code_modes as CM

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad658-")
    project = _project(scratch)
    blocks = hasattr(BM, "example_names")
    dirs = [films] if films else []
    if blocks:
        for name in BM.example_names():
            BM.add_example(project, name, dirs=dirs)
    else:
        for name in CM.example_names():
            CM.add_example(project, name, dirs=dirs)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            time.sleep(4)
            _hide_log(page)
            shot(page, "modes_list")
            page.locator(".modes-list .hd button", has_text="New").first.click()
            time.sleep(1)
            page.locator('.nmw-tile[data-kind="blocks"]').first.click()
            time.sleep(0.8)
            ex = page.locator(".nmw-ex", has_text="DESTOROYAH")
            if ex.count():                         # its tooltip: what the blocks lost
                ex.first.hover()
                time.sleep(1.2)
            shot(page, "new_blocks")
            page.locator(".nmw button", has_text="Cancel").first.click()
            time.sleep(0.5)
            for slug in ("destoroyah",) + (NEW if blocks else ()):
                row = page.locator(".modes-list .li", has_text=slug.replace("_", " ").upper())
                if not row.count():
                    print("no row for", slug, flush=True)
                    continue
                row.first.click()
                time.sleep(2.5)
                if slug in NEW:                    # the new ones as their rules read: the Rule cards view
                    tab = page.locator("button, [role=tab]", has_text="Rule cards")
                    if tab.count():
                        tab.first.click()
                        time.sleep(1.5)
                shot(page, slug)
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
