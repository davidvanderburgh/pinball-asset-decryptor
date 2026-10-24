"""PAD-715 proof shots: the plain-C game modes that had no books (James Bond's Bird One Multiball, Jurassic Park The
Pin's Restore Power) on the Modes tab's Starts on > the game starting its <mode>.

    python scripts/shot_pad715.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). Per title a
project on its stock card with one form mode set to start in that game mode's place. Writes into <out_dir>:

- <prefix>_bond_form.png   James Bond LE 1.06: BIRD ONE STAND IN, in the place of Bird One Multiball (29)
- <prefix>_jp_form.png     Jurassic Park The Pin 1.05: POWER STAND IN, in the place of Restore Power (5)

and prints the modes the menu offers (the options of the select beside "the game starting its").
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

CARDS = r"D:\Pinball\images\Stern\spike2"
SHOTS = (
    ("bond_form", "james_bond_le-1_06_0.Release.16G.sdcard.raw", "BOND 1.06 LE Extract", "BIRD ONE STAND IN", 29),
    ("jp_form", "jurassic_park_the_pin-1_05_0.Release.8G.sdcard.raw", "JP 1.05 Extract", "POWER STAND IN", 5),
)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    print("serving", repo, flush=True)
    for screen, card, folder, name, mid in SHOTS:
        scratch = tempfile.mkdtemp(prefix="pad715-")
        project = os.path.join(scratch, folder)
        os.makedirs(project)
        with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": os.path.join(CARDS, card), "input_name": card}, f)
        form, spec = MP.new_mode(project, name)
        spec.starts_on, spec.place_mode = "game_mode", mid
        spec.seconds = 40
        MP.save(project, form, spec)
        proc, url = S._serve(repo, scratch, project)
        try:
            def go(page, screen=screen, name=name):
                page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
                time.sleep(4)
                S6._hide_log(page)
                row = page.locator(".modes-list .li", has_text=re.compile(name))
                if not row.count():
                    print("no row", flush=True)
                    return
                row.first.click()
                time.sleep(3)
                note = page.get_by_text("the game starting its", exact=False)
                print(screen, "'the game starting its' on the page:", note.count(), flush=True)
                if note.count():
                    note.first.evaluate("e => e.scrollIntoView({block: 'center'})")
                    opts = note.first.evaluate(
                        "e => { let r = e.closest('label, div'); for (let i = 0; i < 4 && r; i++, r = r.parentElement) {"
                        " const s = r.querySelector('select'); if (s) return [s.value, Array.from(s.options).map("
                        "o => o.value + '=' + o.textContent.trim())]; } return null; }")
                    print(screen, "offered:", opts, flush=True)
                page.mouse.move(5, 1090)
                time.sleep(1)
                out = os.path.join(out_dir, "%s_%s.png" % (prefix, screen))
                page.screenshot(path=out)
                print("shot", out, flush=True)
            S._shoot(url, go, height=1100)
        finally:
            proc.terminate()
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
