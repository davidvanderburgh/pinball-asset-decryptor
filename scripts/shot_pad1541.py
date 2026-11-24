"""PAD-1541 proof shots: Elvira 3 1.13 offers an intro and outro for its own Houses, on the Modes tab.

    python scripts/shot_pad1541.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A project
on the stock Elvira 3 1.13 card holding a form mode, HOUSE INTRO, set to run with the game's own Houses (mode 0):
main greys that start out (the build was never seen to start a game on the rig), the branch offers it. Writes into
<out_dir>:

- <prefix>_form.png       the form mode's Starts on ("with the game's" row)
- <prefix>_gamemode.png   the game's own Houses page (its Intro and outro section)
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

CARD = r"D:\Pinball\images\Stern\spike2\elvira3-1_13_0.Release.16G.sdcard.raw"
TITLE = "elvira3_1_13"
JET = 0                                # Houses (whichever House is selected)


def _project(scratch):
    project = os.path.join(scratch, "Elvira 3 1.13 Extract")
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
    from pinball_decryptor.plugins.stern import mode_project as MP
    print("serving", repo, flush=True)

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad1541-")
    project = _project(scratch)
    form, _blank = MP.new_mode(project, "HOUSE INTRO")
    spec = MP.blank_spec(MP.profile(TITLE), "HOUSE INTRO")
    if hasattr(spec, "with_mode"):
        spec.starts_on, spec.with_mode = "with_game", JET
        spec.seconds = 0
    MP.save(project, form, spec)
    print("modes", os.listdir(os.path.join(project, "modes")), flush=True)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(4)
            S6._hide_log(page)
            row = page.locator(".modes-list .li", has_text=re.compile("HOUSE INTRO"))
            if row.count():
                row.first.click()
                time.sleep(3)
                note = page.get_by_text("(its intro and outro)", exact=False)
                if not note.count():                     # before: the last start the tab offered
                    note = page.get_by_text("the game starting its", exact=False)
                print("form row:", note.count(), flush=True)
                if note.count():
                    note.first.evaluate("e => e.scrollIntoView({block: 'center'})")
                radio = page.locator("input[name='m-starts'][value='with_game']")
                print("with radio disabled:", radio.count() and radio.first.is_disabled(), flush=True)
                page.mouse.move(5, 1090)
                time.sleep(1)
                shot(page, "form")
            fold = page.locator("[title^='Show the game\\'s own modes']")
            if fold.count():
                fold.first.click()
                time.sleep(1.5)
            row = page.locator(".modes-list .li", has_text=re.compile("Houses"))
            print("game mode row:", row.count(), flush=True)
            if not row.count():
                return
            row.first.click()
            time.sleep(3)
            sec = page.get_by_text("Intro and outro", exact=False)
            print("intro section:", sec.count(), flush=True)
            if sec.count():
                sec.first.evaluate("e => e.scrollIntoView({block: 'center'})")
            page.mouse.move(5, 1090)
            time.sleep(1)
            shot(page, "gamemode")
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
