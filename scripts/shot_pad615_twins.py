"""PAD-615 round 3 proof shot: a Bond LE 1.06 project where BOND VS SUMO is a new challenge of its own twice, as a form
mode and as a blocks mode (the reporter's project).

    python scripts/shot_pad615_twins.py <repo> <out_dir> <prefix>

Writes <prefix>_twin_status.png: the form mode's page. On the branch its status says the other mode is the same
challenge and the menu would list it twice; before it, it reads Ready to build.
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


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad615t-")
    project = S._project(scratch, "Bond LE 1.06 Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="BOND VS SUMO", title="james_bond_le_1_06")
    spec.start_shot, spec.scoring_shots = "Right ramp exit opto", ["Right ramp exit opto", "Side ramp enter opto"]
    spec.seconds = 60
    spec.starts_on, spec.challenge = "challenge", MP.CHALLENGE_NEW
    slug, _path = MP.new_mode(project, spec=spec)
    bslug, _bpath = BM.new_blocks_mode(project, "BOND VS SUMO")
    BM.save(project, bslug, {"name": "BOND VS SUMO", "seconds": 60, "screen": False, "game_modes": "block",
                             "scripts": [{"hat": {"kind": "challenge", "challenge": BM.CHALLENGE_NEW},
                                          "do": [{"op": "start_mode"}]}]})
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_twin_status.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=900)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
