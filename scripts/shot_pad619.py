"""PAD-619 proof shots: a mode in the game's challenges beyond James Bond - Rush Pro 1.19 (the game's own challenges,
taken by their flags) and Deadpool Pro 1.16 (only challenges of the modes' own, on the start menu).

    python scripts/shot_pad619.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots).
Writes into <out_dir>:

- <prefix>_rush_starts.png      a form mode's page at Starts on, Rush Pro 1.19: on the branch, a challenge game of
                                Cygnus Book 1; before it, the same mode (main had no challenge start on Rush)
- <prefix>_deadpool_starts.png  the same on Deadpool Pro 1.16: on the branch, A new challenge of its own
- <prefix>_jaws_starts.png      the same on Jaws Pro 1.02: on the branch, a challenge game of 4th of July (the game-play
                                mode's index)
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

CARDS = {"rush": ("rush_pro-1_19_0.Release.16G.sdcard.raw", "Rush Pro 1.19 Extract", "rush_pro_1_19"),
         "deadpool": ("deadpool_pro-1_16_0.Release.8G.sdcard.raw", "Deadpool Pro 1.16 Extract", "deadpool_pro_1_16"),
         "jaws": ("jaws_pro-1_02_0.Release.16G.sdcard.raw", "Jaws Pro 1.02 Extract", "jaws_pro_1_02")}


def _scroll_to(page, text, block="start"):
    page.evaluate("""([t, b]) => { const h = [...document.querySelectorAll('*')].find((e) =>
        e.children.length === 0 && e.textContent.trim() === t);
        if (h) h.scrollIntoView({ block: b }); }""", [text, block])
    time.sleep(1)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    which = sys.argv[4:] or sorted(CARDS)
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    for name in which:
        card, folder, title = CARDS[name]
        scratch = tempfile.mkdtemp(prefix="pad619-")
        project = S._project(scratch, folder)
        with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
        spec = MP.ModeSpec(name="PAD CHALLENGE", title=title)
        spec.seconds = 60
        prof = MP.profiles(MP.PORTS_DIR).get(title)
        if prof is not None and prof.can("challenge"):
            spec.starts_on = "challenge"
            spec.challenge = 0 if prof.challenges else MP.CHALLENGE_NEW
        slug, _path = MP.new_mode(project, spec=spec)
        proc, url = S._serve(repo, scratch, project)
        try:
            def form(page):
                webui_shot.api(url, "modes.select", slug, "form")
                time.sleep(3)
                _scroll_to(page, "Starts on")
                _scroll_to(page, "and also", "end")
                out = os.path.join(out_dir, "%s_%s_starts.png" % (prefix, name))
                page.screenshot(path=out)
                print("shot", out, flush=True)
            S._shoot(url, form, height=1100)
        finally:
            proc.terminate()


if __name__ == "__main__":
    main()
