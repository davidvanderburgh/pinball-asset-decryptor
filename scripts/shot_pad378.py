"""PAD-378 proof shot: Undo and Redo in the block editor, with Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z.

    python scripts/shot_pad378.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot). Opens MASER BARRAGE (shot_pad377's program) in the block editor, takes a block
out with its x and writes <out_dir>/<prefix>_blocks_undo.png. Then it drives the keys and prints
one CHECK line each: Ctrl+Z puts the block back (on the page and in blocks.json), Ctrl+Y and
Ctrl+Shift+Z take it out again, the Undo button puts it back, and Ctrl+Z inside the Name box is
left to the box, and one Undo takes back a run of typing in a box.
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad377 as P  # noqa: E402
import webui_shot  # noqa: E402


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    scratch = tempfile.mkdtemp(prefix="pad378-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    slug, _path = BM.new_blocks_mode(project, "MASER BARRAGE", example="ramps")
    p = P.maser_program()
    p["scripts"] = p["scripts"][2:] + p["scripts"][:2]
    BM.save(project, slug, p)
    proc, url = S._serve(repo, scratch, project)
    fails = []

    def check(what, ok):
        print("CHECK %s %s" % ("pass" if ok else "FAIL", what), flush=True)
        if not ok:
            fails.append(what)

    def saved_blocks():
        time.sleep(1.5)                                    # the page saves 450 ms after a change
        prog = BM.load(project, slug)

        def count(stack):
            return sum(1 + count(b.get("then") or []) + count(b.get("else") or []) for b in stack or [])
        return sum(count(s.get("do")) for s in prog["scripts"])

    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            n = lambda: page.locator(".bk-scripts .bk:not(.bk-hat)").count()   # noqa: E731
            start = n()
            page.locator(".bk-scripts .bk:not(.bk-hat) .bk-x[aria-label='Take this block out']").nth(1).click()
            time.sleep(0.5)
            check("the x takes a block out (%d -> %d)" % (start, n()), n() == start - 1)
            page.mouse.move(5, 5)
            time.sleep(0.6)
            out = os.path.join(out_dir, "%s_blocks_undo.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)

            page.evaluate("document.activeElement && document.activeElement.blur()")
            page.keyboard.press("Control+z")
            time.sleep(0.4)
            check("Ctrl+Z puts it back on the page", n() == start)
            check("... and in blocks.json", saved_blocks() == start)
            page.keyboard.press("Control+y")
            time.sleep(0.4)
            check("Ctrl+Y takes it out again", n() == start - 1)
            page.keyboard.press("Control+z")
            page.keyboard.press("Control+Shift+z")
            time.sleep(0.4)
            check("Ctrl+Shift+Z redoes too", n() == start - 1)
            undo = page.locator(".bk-bar button", has_text="Undo")
            check("an Undo button", undo.count() == 1)
            if undo.count():
                undo.click()
                time.sleep(0.4)
                check("the Undo button puts it back", n() == start)
                check("... and in blocks.json", saved_blocks() == start)
            name = page.locator("#bk-name")
            name.click()
            page.keyboard.press("End")
            page.keyboard.type("X")
            page.keyboard.press("Control+z")
            time.sleep(0.4)
            check("Ctrl+Z in the Name box is the box's own (blocks unchanged)", n() == start)
            name.fill("MASER BARRAGE")
            name.press("End")
            page.keyboard.type(" TWO", delay=80)
            page.evaluate("document.activeElement && document.activeElement.blur()")
            time.sleep(0.3)
            before = name.input_value()
            undo.click()
            time.sleep(0.4)
            check("one Undo takes back a run of typing (%r -> %r)" % (before, name.input_value()),
                  before.endswith(" TWO") and not name.input_value().endswith("T"))
        S._shoot(url, blocks, height=1100)
    finally:
        proc.terminate()
    print("VERDICT", "pass" if not fails else "fail: " + "; ".join(fails), flush=True)


if __name__ == "__main__":
    main()
