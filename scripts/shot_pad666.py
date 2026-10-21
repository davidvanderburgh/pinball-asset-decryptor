"""PAD-666 proof shots: a blank new mode's start shot beside MASER BARRAGE.

    python scripts/shot_pad666.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
Godzilla LE 1.16 project on the stock card holding the blocks example MASER BARRAGE (it starts on the Maser
target). Writes into <out_dir>:

- <prefix>_new_form_mode.png   New > Form > Blank mode: the new mode open, its Starts on shot showing
- <prefix>_new_blocks_mode.png New > Blocks, named NEW BLOCKS: the starter program's start shot
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
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    print("serving", repo, flush=True)

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad666-")
    project = _project(scratch)
    BM.add_example(project, "MASER BARRAGE")
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            time.sleep(4)
            _hide_log(page)
            page.locator(".modes-list .hd button", has_text="New").first.click()
            time.sleep(1)
            page.locator('.nmw-tile[data-kind="form"]').first.click()
            time.sleep(0.8)
            page.locator(".nmw-ex.big", has_text="Blank mode").first.click()
            time.sleep(3)
            start = page.get_by_text("Starts on", exact=False)
            if start.count():
                start.first.scroll_into_view_if_needed()
                time.sleep(0.5)
            shot(page, "new_form_mode")
            page.locator(".modes-list .hd button", has_text="New").first.click()
            time.sleep(1)
            page.locator('.nmw-tile[data-kind="blocks"]').first.click()
            time.sleep(0.8)
            page.locator("#nmw-blocks-name, .nmw input").first.fill("NEW BLOCKS")
            page.locator(".nmw button", has_text="Make it").first.click()
            time.sleep(3)
            tab = page.locator("button, [role=tab]", has_text="Rule cards")
            if tab.count():
                tab.first.click()
                time.sleep(1.5)
            shot(page, "new_blocks_mode")
        S._shoot(url, go, height=1100)
        for slug in sorted(os.listdir(os.path.join(project, "modes"))):
            print("mode", slug, flush=True)
            for fn in ("mode.json", "blocks.json"):
                path = os.path.join(project, "modes", slug, fn)
                if os.path.isfile(path):
                    d = json.load(open(path, encoding="utf-8"))
                    if fn == "mode.json":
                        print("   start", d.get("start_shot"), d.get("start_count"), "scoring", d.get("scoring_shots"))
                    else:
                        idle = [(s.get("hat") or {}).get("shot") for s in d.get("scripts", [])
                                if (s.get("hat") or {}).get("when") == "idle"]
                        print("   idle hats", idle)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
