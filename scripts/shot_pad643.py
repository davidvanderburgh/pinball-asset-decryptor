"""PAD-643 proof shots: who launches a challenge game's ball, on a James Bond LE 1.06 project.

    python scripts/shot_pad643.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots).
Writes into <out_dir>:

- <prefix>_page_starts.png       a form mode's page at Starts on, a challenge game of its own: on the branch with its
                                 ball launched 6 seconds after it starts; before it, the same mode (no such row)
- <prefix>_blocks_challenge.png  a blocks mode whose When the player picks the challenge script starts it: on the
                                 branch the hat also says its ball is launched when its start clip is over
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

CARD = "james_bond_le-1_06_0.Release.16G.sdcard.raw"


def _scroll_to(page, text, block="start"):
    page.evaluate("""([t, b]) => { const h = [...document.querySelectorAll('*')].find((e) =>
        e.children.length === 0 && e.textContent.trim() === t);
        if (h) h.scrollIntoView({ block: b }); }""", [text, block])
    time.sleep(1)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    print("serving", repo, "launch setting:", hasattr(MP.ModeSpec(), "challenge_launch"), flush=True)

    scratch = tempfile.mkdtemp(prefix="pad643-")
    project = S._project(scratch, "Bond LE 1.06 Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="YOLT WIZARD", title="james_bond_le_1_06")
    spec.start_shot, spec.scoring_shots = "Right ramp exit opto", ["Right ramp exit opto", "Side ramp enter opto"]
    spec.seconds = 60
    spec.starts_on, spec.challenge = "challenge", MP.CHALLENGE_NEW
    if hasattr(spec, "challenge_launch"):       # PAD-643: 6 s after it starts
        spec.challenge_launch = 6000
    slug, _path = MP.new_mode(project, spec=spec)
    bslug, _bpath = BM.new_blocks_mode(project, "DAF WIZARD")
    scripts = [{"hat": {"kind": "event", "event": "film_daf", "when": "any"}, "do": [
        {"op": "light_mode", "shot": "Right ramp exit opto", "insert": "BLOFELD", "color": "#00ff00",
         "pattern": "solid"}]}]
    scripts.append({"hat": {"kind": "challenge", "challenge": BM.CHALLENGE_NEW}, "do": [{"op": "start_mode"}]})
    scripts.append({"hat": {"kind": "mode_start"}, "do": [{"op": "log", "text": "DAF running"}]})
    BM.save(project, bslug, {"name": "DAF WIZARD", "seconds": 60, "screen": False, "game_modes": "block",
                             "scripts": scripts})
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            _scroll_to(page, "Starts on")
            _scroll_to(page, "and also", "end")       # the bottom of Starts on, where the challenge row is
            out = os.path.join(out_dir, "%s_page_starts.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)

        def blocks(page):
            webui_shot.api(url, "modes.select", bslug, "code")
            time.sleep(3)
            page.evaluate("""() => { const all = [...document.querySelectorAll('.bk-script')];
                const ch = all.find((e) => e.textContent.includes('picks the challenge'));
                if (ch) ch.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_challenge.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=1100)
        S._shoot(url, blocks, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
