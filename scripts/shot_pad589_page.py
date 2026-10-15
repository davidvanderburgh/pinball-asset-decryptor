"""PAD-589 proof shots: the Mode page's new choices, on a Godzilla Premium/LE 1.16 project.

    python scripts/shot_pad589_page.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots).
Writes into <out_dir>:

- <prefix>_page_starts.png    a form mode's page at Starts on: on the branch, set to the player picking Ebirah on
                              the battle selection screen; before it, the same mode with no such choice
- <prefix>_page_building.png  the same page at the machine's parts: on the branch, Building set to floor 3; before
                              it, the same mode with no Building section
- <prefix>_blocks_building.png a blocks mode that moves the building as it starts, its Mechanisms palette in view
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


def _scroll_to(page, text, block="start"):
    page.evaluate("""([t, b]) => { const h = [...document.querySelectorAll('*')].find((e) =>
        e.children.length === 0 && e.textContent.trim() === t);
        if (h) h.scrollIntoView({ block: b }); }""", [text, block])
    time.sleep(1)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad589p-")
    project = S._project(scratch, "GZ 1.16 Premium Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="MOTHRA", title="godzilla_le_1_16")
    spec.start_shot, spec.scoring_shots = "Left ramp", ["Left ramp", "Right ramp"]
    if hasattr(spec, "roster_slot"):
        spec.starts_on, spec.roster_slot = "battle", 0
    if hasattr(spec, "building_floor"):
        spec.building_floor = 3
    slug, _path = MP.new_mode(project, spec=spec)
    has_block = "building" in BM.STATEMENTS
    bslug, _bpath = BM.new_blocks_mode(project, "TOWER")
    on_start = [{"op": "log", "text": "TOWER"}] + ([{"op": "building", "floor": "3"}] if has_block else [])
    BM.save(project, bslug, {"name": "TOWER", "seconds": 30, "screen": False, "scripts": [
        {"hat": {"kind": "shot", "shot": "Maser target", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": on_start}]})
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            _scroll_to(page, "Starts on")
            out = os.path.join(out_dir, "%s_page_starts.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            _scroll_to(page, "Shield targets")
            out = os.path.join(out_dir, "%s_page_building.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)

        def blocks(page):
            webui_shot.api(url, "modes.select", bslug, "code")
            time.sleep(3)
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim().toUpperCase() === 'MECHANISMS');
                if (h) h.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_building.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=1100)
        S._shoot(url, blocks, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
