"""PAD-479 proof shots: a game's own limits on the Modes form read grey, not yellow.

    python scripts/shot_pad479.py <repo> <out_dir> <prefix> <screen> [<screen> ...]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Each
<screen> is a key of SCREENS: a project on that build's stock card with one form mode open on one page of the form.
Writes <out_dir>/<prefix>_<screen>.png, the form card alone.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

CARDS = r"D:\Pinball\images\Stern\spike2"

#: screen -> (card file, project name, title key, form page)
SCREENS = {
    "john_wick_le_sounds": ("john_wick_le-1_02_0.Release.16G.sdcard.raw", "John Wick LE 1.02 Extract",
                            "john_wick_le_1_02", "Sounds"),
    "beatles_sounds": ("beatles-1_29_0.Release.8G.sdcard.raw", "The Beatles 1.29 Extract", "beatles_1_29", "Sounds"),
    "beatles_mode": ("beatles-1_29_0.Release.8G.sdcard.raw", "The Beatles 1.29 Extract", "beatles_1_29", "Mode"),
    "star_wars_le_sounds": ("star_wars_le-1_31_0.Release.8G.sdcard.raw", "Star Wars LE 1.31 Extract",
                            "star_wars_le_1_31", "Sounds"),
}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    print("serving", repo, flush=True)

    for screen in sys.argv[4:]:
        card, name, title, tab = SCREENS[screen]
        scratch = tempfile.mkdtemp(prefix="pad479-")
        project = S._project(scratch, name)
        with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": os.path.join(CARDS, card), "input_name": card}, f)
        spec = MP.blank_spec(MP.profiles()[title], name="TIME TEST")
        slug, _path = MP.new_mode(project, spec=spec)
        proc, url = S._serve(repo, scratch, project)
        try:
            def shoot(page):
                webui_shot.api(url, "modes.select", slug, "form")
                time.sleep(float(os.environ.get("SHOT_WAIT", "4")))
                page.evaluate("""(n) => { const t = [...document.querySelectorAll('.modes-editor button[role=tab]')]
                    .find((e) => e.textContent.trim() === n); if (t) t.click(); }""", tab)
                time.sleep(1.5)
                for r in page.evaluate("""() => [...document.querySelectorAll('.modes-reason')].map((e) =>
                        [e.className, getComputedStyle(e).color, e.textContent])"""):
                    print("  reason", r, flush=True)
                path = os.path.join(out_dir, "%s_%s.png" % (prefix, screen))
                page.locator(".modes-editor").screenshot(path=path)
                print("shot", path, flush=True)
            S._shoot(url, shoot, height=int(os.environ.get("SHOT_H", "1500")))
        finally:
            proc.terminate()


if __name__ == "__main__":
    main()
