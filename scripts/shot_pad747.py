"""PAD-747 proof shots: a mode that starts once the player has completed some of the game's own modes, on the Modes tab.

    python scripts/shot_pad747.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A project
on the stock Uncanny X-Men LE 0.98 card holding a form mode, MINI WIZARD, that starts once 4 of the game's eight
missions are completed, and a blocks mode, BIG WIZARD, whose When the player has completed hat waits for all eight.
Writes into <out_dir>:

- <prefix>_form.png       the form mode's Starts on (the new "the player completing" row and its ticks)
- <prefix>_blocks.png     the blocks mode's page: its script, the new hat, beside the palette's When list
"""

import json
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

CARD = r"D:\Pinball\images\Stern\spike2\uncanny_xmen_le-0_98_0.Release.16G.sdcard.raw"
MISSIONS = list(range(3, 11))          # A Fiery Assault .. Stopping a Juggernaut

PROGRAM = {
    "name": "BIG WIZARD", "seconds": 90, "ends_on_drain": True,
    "scripts": [
        {"hat": {"kind": "completed", "count": 8, "modes": MISSIONS}, "do": [{"op": "start_mode"}]},
    ],
}


def _project(scratch):
    project = os.path.join(scratch, "X-Men 0.98 LE Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    print("serving", repo, flush=True)

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad747-")
    project = _project(scratch)
    form, _blank = MP.new_mode(project, "MINI WIZARD")
    spec = MP.blank_spec(MP.profile("uncanny_xmen_le_0_98"), "MINI WIZARD")    # the card's own shots
    if hasattr(spec, "done_count"):
        spec.starts_on, spec.done_count, spec.done_modes = "completed", 4, list(MISSIONS)
    spec.seconds = 45
    MP.save(project, form, spec)
    slug, _c = BM.new_blocks_mode(project, "BIG WIZARD", [])
    if "completed" in BM.HATS:
        BM.save(project, slug, PROGRAM)
    print("modes", os.listdir(os.path.join(project, "modes")), flush=True)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(4)
            S6._hide_log(page)
            row = page.locator(".modes-list .li", has_text=re.compile("MINI WIZARD"))
            if row.count():
                row.first.click()
                time.sleep(3)
                note = page.get_by_text("the player completing", exact=False)
                if not note.count():                     # before: the last start the tab offered
                    note = page.get_by_text("the game starting its", exact=False)
                print("form row:", note.count(), flush=True)
                if note.count():
                    note.first.evaluate("e => e.scrollIntoView({block: 'center'})")
                page.mouse.move(5, 1090)
                time.sleep(1)
                shot(page, "form")
            row = page.locator(".modes-list .li", has_text=re.compile("BIG WIZARD"))
            if not row.count():
                print("no blocks row", flush=True)
                return
            row.first.click()
            time.sleep(3)
            tab = page.locator("button, [role=tab]", has_text="Blocks")
            if tab.count():
                tab.first.click()
                time.sleep(1.5)
            hat = page.locator(".bk-script").first
            if hat.count():
                hat.evaluate("e => e.scrollIntoView({block: 'start'})")
            pal = page.get_by_text("When the player has completed some of the game's modes", exact=False)
            print("palette hat on the page:", pal.count(), flush=True)
            page.mouse.move(5, 1090)
            time.sleep(1)
            shot(page, "blocks")
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
