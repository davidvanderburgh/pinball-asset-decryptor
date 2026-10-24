"""PAD-710 proof shots: a mode in the place of one of the game's own modes, on the Modes tab.

    python scripts/shot_pad710.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
project on the stock Godzilla Premium/LE 1.16 card holding one blocks mode, JET STAND IN: when the game starts its
Jet Fighter Attack (``{"kind": "game_mode", "mode": 21}``) it runs instead, and a Left ramp completes it (End the
mode, completed); and a form mode, JET RUSH, started the same way. Writes into <out_dir>:

- <prefix>_blocks.png     the blocks mode's page: its scripts beside the palette's When list (where the new hat is)
- <prefix>_form.png       the form mode's Starts on
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
    "name": "JET STAND IN", "seconds": 60, "ends_on_drain": True,
    "scripts": [
        {"hat": {"kind": "game_mode", "mode": 21, "name": "Jet Fighter Attack"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
            {"op": "score", "points": {"k": "num", "v": 2000000}},
            {"op": "end_mode", "won": True}]},
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

    scratch = tempfile.mkdtemp(prefix="pad710-")
    project = S6._project(scratch)
    slug, _c = BM.new_blocks_mode(project, "JET STAND IN", ["Left ramp", "Building"])
    BM.save(project, slug, PROGRAM)
    form, spec = MP.new_mode(project, "JET RUSH")
    if hasattr(spec, "place_mode"):
        spec.starts_on, spec.place_mode = "game_mode", 21
    spec.seconds = 40
    MP.save(project, form, spec)
    print("mode", slug, os.listdir(os.path.join(project, "modes")), flush=True)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(4)
            S6._hide_log(page)
            row = page.locator(".modes-list .li", has_text=re.compile("JET STAND IN"))
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
            pal = page.get_by_text("When the game starts one of its modes", exact=False)
            print("'When the game starts one of its modes' on the page:", pal.count(), flush=True)
            if pal.count():
                pal.first.evaluate("e => e.scrollIntoView({block: 'end'})")
            page.mouse.move(5, 1090)
            time.sleep(1)
            shot(page, "blocks")
            row = page.locator(".modes-list .li", has_text=re.compile("JET RUSH"))
            if row.count():
                row.first.click()
                time.sleep(3)
                note = page.get_by_text("the game starting its", exact=False)
                if not note.count():
                    note = page.get_by_text("Starts on", exact=False)
                print("form row:", note.count(), flush=True)
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
