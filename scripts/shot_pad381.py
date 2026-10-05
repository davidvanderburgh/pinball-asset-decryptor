"""PAD-381 proof shot: the Modes tab's Magnet, Scoop and Other mechanisms sections.

    python scripts/shot_pad381.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Writes <out_dir>/<prefix>_mechanisms.png: a form mode on a Godzilla Premium/LE 1.16 project, open on its
page and scrolled to the sections between Ball save and Multiball. On a tree with the mechanisms
(ModeSpec.magnet_ms) the mode holds the magnet 2 s, a ball in the scoop 5 s, the Mechagodzilla magnet 2 s as
it starts and the bridge 3 s on the left ramp - the round-2 machine test's mode.
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
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad381-")
    project = S._project(scratch, "GZ 1.16 Premium Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="COIL TEST 2", title="godzilla_le_1_16")
    spec.start_shot, spec.scoring_shots = "Slingshot", ["Right ramp"]
    if hasattr(spec, "magnet_ms"):
        spec.magnet_ms = 2000
        spec.scoop_hold_ms = 5000
        spec.coil_holds = [["mg_magnet", 2000, ""], ["bridge", 3000, "Left ramp"]]
    slug, _path = MP.new_mode(project, spec=spec)
    proc, url = S._serve(repo, scratch, project)
    try:
        def mechanisms(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.get_by_text("Ball save", exact=True).first.scroll_into_view_if_needed()
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === 'Ball save');
                if (h) h.scrollIntoView({ block: 'start' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_mechanisms.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, mechanisms, height=1300)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
