"""PAD-375 proof shot: the block editor with the mode's HUD.

    python scripts/shot_pad375.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot). Writes <out_dir>/<prefix>_blocks_hud.png: MASER BARRAGE rebuilt in blocks on a
Godzilla Pro 1.15 project, open in the editor. On a tree with the HUD (block_modes.HUD_ICONS) its
HUD is switched on (three counters, the MASER timer badge, a CHAIN gauge) and its scripts write
the HUD (the instruction line, a counter, the gauge, an award line).
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    scratch = tempfile.mkdtemp(prefix="pad375-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    slug, _path = BM.new_blocks_mode(project, "MASER BARRAGE", example="ramps")
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    var = lambda n: {"k": "var", "name": n}                         # noqa: E731
    p = BM.load(project, slug)
    p["seconds"] = 40
    p["vars"] = [{"name": "step", "reset": "mode"}, {"name": "mult", "reset": "mode"},
                 {"name": "barrages", "reset": "mode"}]
    hud = hasattr(BM, "HUD_ICONS")
    step_done = [{"op": "change", "var": "step", "by": num(1)},
                 {"op": "score", "points": {"k": "op", "op": "*", "a": num(1000000), "b": var("mult")}}]
    if hud:
        step_done += [{"op": "hud_text", "which": "line", "text": "NOW SHOOT THE RIGHT RAMP", "value": None}]
    p["scripts"] = [
        {"hat": {"kind": "shot", "shot": "Maser target", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": [
            {"op": "set", "var": "mult", "value": num(1)},
            {"op": "light_shot", "shot": "Left ramp", "color": "#0080ff", "pattern": "blink"}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": step_done},
        {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [
            {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("step"), "b": num(2)}, "then": [
                {"op": "change", "var": "barrages", "by": num(1)},
                {"op": "change", "var": "mult", "by": num(1)},
                {"op": "set", "var": "step", "value": num(0)}]
             + ([{"op": "hud_award", "text": "BARRAGE", "value": var("barrages"), "sub": "MULTIPLIER UP",
                  "seconds": 2}] if hud else []), "else": None}]},
        {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [{"op": "callout", "role": "ten_seconds"}]},
    ]
    if hud:
        p["hud"] = {"on": True, "line": "LEFT RAMP  >  RIGHT RAMP  >  BUILDING",
                    "counters": [{"label": "MULTIPLIER", "sub": "MAX X5", "value": var("mult")},
                                 {"label": "BARRAGES", "sub": "", "value": var("barrages")},
                                 {"label": "POINTS", "sub": "THIS MODE", "value": {"k": "total"}}],
                    "timer": {"on": True, "label": "MASER", "icon": "maser"},
                    "gauge": {"on": True, "label": "CHAIN", "kind": "diamond", "count": 3,
                              "color": "#008cff", "value": var("step")}}
    BM.save(project, slug, p)
    proc, url = S._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_blocks_hud.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1400)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
