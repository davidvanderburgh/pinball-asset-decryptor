"""PAD-664 proof shots: the Modes tab's Rules sheet... on David's 14 Heisei modes.

    python scripts/shot_pad664.py <repo> <out_dir> <prefix> [<modes folder>]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
Godzilla LE 1.16 project on the stock card holding a copy of the modes in <modes folder> (default: David's
"HEISEI v1.99D + daveyvandy modes"; only their settings and sources are copied - no clips or sounds - so his folder
is never touched). Writes into <out_dir>:

- <prefix>_modes_tab.png     the Modes tab with the 14 modes (the list's buttons under it)
- <prefix>_rules_dialog.png  Rules sheet... open: the modes on the left, the sheet as it prints on the right (only
                             when the served tree has the button)
- <prefix>_rules_words.png   the same with KAMACURAS's own words open (a tag and a start of David's)
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad666 as S6  # noqa: E402

HEISEI = r"C:\Users\david\OneDrive\Desktop\HEISEI v1.99D + daveyvandy modes\modes"
KEEP = (".json", ".c", ".h")


def _copy_modes(src, project):
    dst = os.path.join(project, "modes")
    for slug in sorted(os.listdir(src)):
        folder = os.path.join(src, slug)
        if not os.path.isdir(folder):
            continue
        os.makedirs(os.path.join(dst, slug))
        for name in os.listdir(folder):
            if name.endswith(KEEP):
                shutil.copy2(os.path.join(folder, name), os.path.join(dst, slug, name))
    return sorted(os.listdir(dst))


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    src = sys.argv[4] if len(sys.argv) > 4 else HEISEI
    os.makedirs(out_dir, exist_ok=True)
    print("serving", repo, flush=True)

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad664-")
    project = S6._project(scratch)
    print("modes", _copy_modes(src, project), flush=True)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            def said(m):
                if m.type in ("error", "warning"):
                    print("console:", m.type, m.text, flush=True)

            def asked(r):                                   # the dialog's calls, to see an edit reach Python
                if "sheet_" in (r.post_data or ""):
                    print("rpc:", r.post_data[:160], flush=True)
            page.on("console", said)
            page.on("request", asked)
            time.sleep(5)
            S6._hide_log(page)
            page.locator(".modes-list .li", has_text="KAMACURAS").first.click()
            time.sleep(3)
            shot(page, "modes_tab")
            btn = page.locator(".modes-list-acts button", has_text="Rules sheet")
            if not btn.count():
                print("no Rules sheet button in this tree", flush=True)
                return
            btn.first.click()
            page.wait_for_selector(".rs-preview iframe", timeout=120000)
            time.sleep(3)
            shot(page, "rules_dialog")
            page.locator(".rs-mode", has_text="KAMACURAS").locator(".rs-name").first.click()
            time.sleep(1)
            fields = page.locator(".rs-mode.open .rs-words")
            fields.nth(0).fill("Top spinner 50 / 100 / 150 lights the Right scoop")
            fields.nth(3).fill("REWORKED")
            fields.nth(3).press("Enter")
            page.locator(".rs-sheet-fields .rs-words").first.click()     # leave the field: it is kept
            page.mouse.move(5, 990)                                       # no tooltip over the shot
            time.sleep(4)
            shot(page, "rules_words")
            words = os.path.join(project, "modes", "kamacuras", "sheet.json")
            print("kamacuras sheet.json:", open(words, encoding="utf-8").read() if os.path.isfile(words) else None,
                  flush=True)
        S._shoot(url, go, height=1000)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
