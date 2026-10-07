"""PAD-418 proof shots: the game's own light shows picked on the Modes tab, from the form and from blocks.

    python scripts/shot_pad418.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Both on a Godzilla Premium/LE 1.16 project. Writes into <out_dir>:

- <prefix>_form_lights.png   a form mode open on its Lights page: on a tree with the light shows
  (ModeSpec.show_start / show_end) its "The game's light shows" section, Strobe burst at the start and Blue fade
  at the end; before it, the same page without that section
- <prefix>_blocks_game_show.png  a blocks mode that plays the game's Strobe burst as it starts and its Ember fade
  as it ends (on a tree without the block, the same mode without it), the Show palette group in view
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


def program(BM):
    has = "game_show" in BM.STATEMENTS
    on_start = [{"op": "log", "text": "LIGHT SHOW"}]
    on_end = [{"op": "log", "text": "the end"}]
    if has:
        on_start.append({"op": "game_show", "name": "Strobe burst"})
        on_end.append({"op": "game_show", "name": "Ember fade"})
    return {
        "name": "LIGHT SHOW", "seconds": 30, "screen": False,
        "scripts": [
            {"hat": {"kind": "shot", "shot": "Maser target", "when": "idle"}, "do": [{"op": "start_mode"}]},
            {"hat": {"kind": "mode_start"}, "do": on_start},
            {"hat": {"kind": "mode_end"}, "do": on_end},
        ]}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad418-")
    project = S._project(scratch, "GZ 1.16 Premium Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="LIGHT SHOW", title="godzilla_le_1_16")
    spec.start_shot, spec.scoring_shots = "Maser target", ["Left ramp", "Right ramp"]
    if hasattr(spec, "show_start"):
        spec.show_start, spec.show_end = "Strobe burst", "Blue fade"
    slug, _path = MP.new_mode(project, spec=spec)
    bslug, _bpath = BM.new_blocks_mode(project, "LIGHT SHOW BLOCKS")
    BM.save(project, bslug, program(BM))
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.evaluate("""() => { const t = [...document.querySelectorAll('button[role=tab]')].find((e) =>
                e.textContent.trim() === 'Lights'); if (t) t.click(); }""")
            time.sleep(1.5)
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === 'Sweep the playfield');
                if (h) h.scrollIntoView({ block: 'start' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_form_lights.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)

        def blocks(page):
            webui_shot.api(url, "modes.select", bslug, "code")
            time.sleep(3)
            page.evaluate("""() => { const all = [...document.querySelectorAll('*')].filter((e) =>
                e.children.length === 0 && /^(Play the game's light show|When the mode starts)$/.test(e.textContent.trim()));
                const b = all.filter((e) => !e.closest('button'));
                const t = b.find((e) => e.textContent.trim() === "Play the game's light show") || b[0];
                if (t) t.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_game_show.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=1300)
        S._shoot(url, blocks, height=1350)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
