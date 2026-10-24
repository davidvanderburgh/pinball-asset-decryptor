"""PAD-707 proof shots: a blocks mode as a monster on MORE KAIJU, on the Modes tab.

    python scripts/shot_pad707.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
project on the stock Godzilla Premium/LE 1.16 card holding one blocks mode, MOTHRA, whose When is a pick on MORE
KAIJU in Ebirah's place (``{"kind": "battle", "slot": 0, "more": true, "picture": "monster.png"}``). Writes into
<out_dir>:

- <prefix>_hat.png       the mode's page: its scripts, the battle hat first
- <prefix>_choices.png   the same, with the hat's battle list opened out (where MORE KAIJU is offered)
- <prefix>_form.png      a form mode, KUMONGA, on MORE KAIJU: its Starts on's battle list opened out
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
    "name": "MOTHRA", "seconds": 40, "ends_on_drain": True,
    "vars": [{"name": "stage", "reset": "mode"}],
    "scripts": [
        {"hat": {"kind": "battle", "slot": 0, "name": "Ebirah", "more": True, "picture": "monster.png"},
         "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [
            {"op": "score", "points": {"k": "num", "v": 1000000}},
            {"op": "change", "var": "stage", "by": {"k": "num", "v": 1}},
            {"op": "if", "cond": {"k": "cmp", "op": ">", "a": {"k": "var", "name": "stage"}, "b": {"k": "num", "v": 1}},
             "then": [{"op": "end_mode", "won": True}]}]},
    ],
}


def _picture(path):
    """A picture of our own for the monster (wings on a night sky): nothing of a manufacturer's."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (400, 340), (10, 10, 40, 255))
    d = ImageDraw.Draw(img)
    for y in range(340):
        d.line((0, y, 400, y), fill=(10 + y // 6, 10 + y // 10, 60 + y // 5, 255))
    for box, fill in (((60, 60, 200, 230), (255, 170, 30)), ((200, 60, 340, 230), (255, 170, 30)),
                      ((90, 90, 170, 180), (200, 40, 40)), ((230, 90, 310, 180), (200, 40, 40)),
                      ((185, 70, 215, 280), (90, 60, 30))):
        d.ellipse(box, fill=fill + (255,))
    img.save(path)


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

    scratch = tempfile.mkdtemp(prefix="pad707-")
    project = S6._project(scratch)
    slug, _c = BM.new_blocks_mode(project, "MOTHRA", ["Building", "Left ramp"])
    _picture(os.path.join(MP.mode_folder(project, slug), "monster.png"))
    BM.save(project, slug, PROGRAM)
    form, spec = MP.new_mode(project, "KUMONGA")
    spec.starts_on, spec.roster_slot, spec.seconds = "battle", 0, 25
    spec.roster_more = True                    # (main has no such field: there it starts on Ebirah's place itself)
    MP.save(project, form, spec)
    print("mode", slug, os.listdir(os.path.join(project, "modes")), flush=True)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(4)
            S6._hide_log(page)
            row = page.locator(".modes-list .li", has_text=re.compile("MOTHRA"))
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
            print("hat words:", hat.locator(".bk-line").first.inner_text() if hat.count() else "-", flush=True)
            shot(page, "hat")
            # the battle list opened out in place (a native list cannot be shot open): every choice it offers
            sel = hat.locator("select").first if hat.count() else None
            if sel is not None and sel.count():
                n = sel.evaluate("e => { e.size = e.options.length; e.style.height = 'auto'; e.scrollIntoView({block: 'center'}); return e.options.length; }")
                print("choices:", n, flush=True)
                time.sleep(0.5)
                shot(page, "choices")
            # the form mode KUMONGA: its Starts on, the battle list opened out
            row = page.locator(".modes-list .li", has_text=re.compile("KUMONGA"))
            if row.count():
                row.first.click()
                time.sleep(3)
                n = page.evaluate("""() => {
                    const s = [...document.querySelectorAll('select')].find(e => [...e.options].some(o => o.text === 'Titanosaurus'));
                    if (!s) return -1;
                    s.size = s.options.length; s.style.height = 'auto'; s.scrollIntoView({block: 'center'});
                    return s.options.length; }""")
                print("form choices:", n, flush=True)
                page.mouse.move(5, 1090)
                time.sleep(1)
                shot(page, "form")
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
