"""PAD-414 proof shots: a mode shakes the cabinet, from the form and from blocks.

    python scripts/shot_pad414.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Both on a Godzilla Premium/LE 1.16 project. Writes into <out_dir>:

- <prefix>_form_shaker.png   a form mode open on its page, scrolled to the mechanisms: on a tree with the
  shaker (ModeSpec.shakes) its Shaker section, a big shake as it starts and the game's jackpot shake on a
  shot; before it, the same mode with no such section
- <prefix>_blocks_shaker.png a blocks mode that shakes the cabinet as it starts and on a ramp (on a tree
  without the block, the same mode without it), its start script in view
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
    has = "shake" in BM.STATEMENTS
    on_start = [{"op": "log", "text": "QUAKE"}]
    on_ramp = [{"op": "score", "points": {"k": "num", "v": 500000}}]
    if has:
        on_start.append({"op": "shake", "ms": {"k": "num", "v": 800}, "strength": "hard"})
        on_ramp.append({"op": "shake_game", "shake": "jackpot"})
    return {
        "name": "QUAKE", "seconds": 30, "screen": False,
        "scripts": [
            {"hat": {"kind": "shot", "shot": "Maser target", "when": "idle"}, "do": [{"op": "start_mode"}]},
            {"hat": {"kind": "mode_start"}, "do": on_start},
            {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": on_ramp},
        ]}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad414-")
    project = S._project(scratch, "GZ 1.16 Premium Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="QUAKE", title="godzilla_le_1_16")
    spec.start_shot, spec.scoring_shots = "Maser target", ["Left ramp", "Right ramp"]
    if hasattr(spec, "shakes"):
        spec.shakes = [["start", 1500, 2, ""], ["shot", "jackpot", 0, "Left ramp"], ["end", 1000, 3, ""]]
    slug, _path = MP.new_mode(project, spec=spec)
    bslug, _bpath = BM.new_blocks_mode(project, "QUAKE BLOCKS")
    BM.save(project, bslug, program(BM))
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.evaluate("""() => { const leaf = (t) => [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === t);
                const h = leaf('Shaker') || leaf('Shield targets') || leaf('Ball save');
                if (h) h.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_form_shaker.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)

        def blocks(page):
            webui_shot.api(url, "modes.select", bslug, "code")
            time.sleep(3)
            page.evaluate("""() => { const leaf = [...document.querySelectorAll('*')].filter((e) =>
                e.children.length === 0 && /^(Shake the cabinet:|When the mode starts)$/.test(e.textContent.trim()));
                const t = leaf.find((e) => e.textContent.trim() === 'Shake the cabinet:') || leaf[leaf.length - 1];
                if (t) t.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_shaker.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=1500)
        S._shoot(url, blocks, height=1350)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
