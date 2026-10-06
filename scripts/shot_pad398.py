"""PAD-398 proof shots: a new mode runs alone, and the person picks what of the game's keeps counting.

    python scripts/shot_pad398.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Both on a Godzilla Premium/LE 1.16 project, each mode as it is made (nothing chosen):

- <prefix>_form_game_modes.png: a form mode open on its page, scrolled to "The game's own modes". Before:
  "may start" was what a new mode did. After: "cannot start", every one of the game's modes ticked, and the
  list of the game's features that keep counting while it runs (none ticked: only this mode counts).
- <prefix>_blocks_game_modes.png: a blocks mode open in the editor, its settings row at the top - the same
  choice and the same two lists.
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

CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad398-")
    project = S._project(scratch, "GZ 1.16 Premium Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="SPACEGODZILLA", title="godzilla_le_1_16")
    spec.start_shot, spec.scoring_shots = "Building", ["Right ramp", "Left ramp"]
    slug, _path = MP.new_mode(project, spec=spec)
    bslug, _bpath = BM.new_blocks_mode(project, "MASER BARRAGE", example="ramps")
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === "The game's own modes");
                if (h) h.scrollIntoView({ block: 'start' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_form_game_modes.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)

        def blocks(page):
            webui_shot.api(url, "modes.select", bslug, "code")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_blocks_game_modes.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=2150)
        S._shoot(url, blocks, height=1250)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
