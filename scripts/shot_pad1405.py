"""PAD-1405 proof shot: the block editor with a mode's bar meters and its screen fade.

    python scripts/shot_pad1405.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Writes
<out_dir>/<prefix>_blocks_meters.png (the mode's settings: on a tree with meters, three of them - CYCLOPS, ENERGY,
TIME) and <prefix>_blocks_fade.png (its scripts and the palette's Show and sound group: on a tree with it, the Fade
the screen blocks of an Optic Blast). OPTIC is a blocks mode on an Uncanny X-Men LE 0.98 project.
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


def _project(scratch, name):
    project = os.path.join(scratch, name)
    os.makedirs(project)
    card = "uncanny_xmen_le-0_98_0.Release.16G.sdcard.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    scratch = tempfile.mkdtemp(prefix="pad1405-")
    project = _project(scratch, "X-Men LE 0.98 Extract")
    slug, _path = BM.new_blocks_mode(project, "OPTIC", example="ramps")
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    var = lambda n: {"k": "var", "name": n}                         # noqa: E731
    p = BM.load(project, slug)
    p["seconds"] = 40
    p["vars"] = [{"name": "hp", "reset": "mode"}, {"name": "energy", "reset": "mode"}]
    meters = hasattr(BM, "fade_layers")
    blast = [{"op": "set", "var": "energy", "value": num(0)}]
    if meters:
        blast = [{"op": "fade", "color": "#000000", "style": "flat", "to": num(80), "ms": num(1500)},
                 {"op": "fade", "color": "#ff0000", "style": "glow", "to": num(100), "ms": num(1500)}] + blast
    p["scripts"] = [
        {"hat": {"kind": "shot", "shot": "Xjet tgt", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [{"op": "set", "var": "hp", "value": num(5)},
                                               {"op": "set", "var": "energy", "value": num(0)}]},
        {"hat": {"kind": "shot", "shot": "Left ramp tgt", "when": "running"}, "do": [
            {"op": "change", "var": "energy", "by": num(25)},
            {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("energy"), "b": num(100)}, "then": blast,
             "else": None}]},
        {"hat": {"kind": "shot", "shot": "Right ramp tgt", "when": "running"}, "do": [
            {"op": "change", "var": "hp", "by": num(-1)}]
            + ([{"op": "fade", "color": "#000000", "style": "flat", "to": num(0), "ms": num(600)},
                {"op": "fade", "color": "#ff0000", "style": "glow", "to": num(0), "ms": num(600)}] if meters else [])},
    ]
    if meters:
        p["meters"] = [{"label": "CYCLOPS", "color": "#e02020", "value": var("hp"), "max": num(5), "numbers": True},
                       {"label": "ENERGY", "color": "#20b0ff", "value": var("energy"), "max": num(100)},
                       {"label": "TIME", "color": "#ffcc00", "value": {"k": "secs_left"}, "max": num(40)}]
    BM.save(project, slug, p)
    proc, url = S._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_blocks_meters.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            page.evaluate("""() => { const w = document.querySelector('.bk-ws'); if (w) w.scrollTop = w.scrollHeight;
                const pal = document.querySelector('.bk-palette'); if (pal) {
                  const h = [...pal.querySelectorAll('*')].find((e) => /Show and sound/.test(e.textContent || '')
                    && e.children.length === 0); if (h) h.scrollIntoView(); } }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_fade.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1400)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
