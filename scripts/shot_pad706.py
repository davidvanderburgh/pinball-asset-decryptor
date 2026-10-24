"""PAD-706 proof shots: a blocks mode in one of Godzilla's battles, on the Modes tab.

    python scripts/shot_pad706.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
project on the stock Godzilla Premium/LE 1.16 card holding one blocks mode, GIGAN STAGES: picked in Gigan's slot on
the battle selection screen (``{"kind": "battle", "slot": 2}``), two Buildings win it (End the mode, the battle won).
Writes into <out_dir>:

- <prefix>_blocks.png     the mode's page: its scripts (the battle hat and the End block) beside the palette's When
                          list (where the battle hat is offered)
- <prefix>_form.png       a form mode, GIGAN RUSH, started by the player picking Gigan: what its Starts on says
"""

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

PROGRAM = {
    "name": "GIGAN STAGES", "seconds": 60, "ends_on_drain": True,
    "vars": [{"name": "stage", "reset": "mode"}],
    "scripts": [
        {"hat": {"kind": "battle", "slot": 2, "name": "Gigan"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [
            {"op": "score", "points": {"k": "num", "v": 1000000}},
            {"op": "change", "var": "stage", "by": {"k": "num", "v": 1}},
            {"op": "if", "cond": {"k": "cmp", "op": ">", "a": {"k": "var", "name": "stage"}, "b": {"k": "num", "v": 1}},
             "then": [{"op": "end_mode", "won": True}]}]},
    ],
}


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

    scratch = tempfile.mkdtemp(prefix="pad706-")
    project = S6._project(scratch)
    slug, _c = BM.new_blocks_mode(project, "GIGAN STAGES", ["Building", "Left ramp"])
    BM.save(project, slug, PROGRAM)
    form, spec = MP.new_mode(project, "GIGAN RUSH")
    spec.starts_on, spec.roster_slot, spec.seconds = "battle", 2, 40
    MP.save(project, form, spec)
    print("mode", slug, os.listdir(os.path.join(project, "modes")), flush=True)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(4)
            S6._hide_log(page)
            row = page.locator(".modes-list .li", has_text=re.compile("GIGAN STAGES"))
            if not row.count():
                print("no row", flush=True)
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
            page.mouse.move(5, 1090)
            time.sleep(1)
            whens = page.get_by_text("When the player picks", exact=False)
            print("'When the player picks' on the page:", whens.count(), flush=True)
            shot(page, "blocks")
            row = page.locator(".modes-list .li", has_text=re.compile("GIGAN RUSH"))
            if row.count():
                row.first.click()
                time.sleep(3)
                note = page.get_by_text("the player picking", exact=False)
                if note.count():
                    note.first.evaluate("e => e.scrollIntoView({block: 'center'})")
                page.mouse.move(5, 1090)
                time.sleep(1)
                shot(page, "form")
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
