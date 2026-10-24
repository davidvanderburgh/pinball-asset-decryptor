"""PAD-708 proof shots: King Caesar's TAG TEAM combo in the Blocks view, on a Godzilla Premium/LE 1.16 project.

    python scripts/shot_pad708.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Writes
<prefix>_combo_blocks.png into <out_dir>: a blocks mode with the combo open in the editor - before: built by hand
from two timers, a variable and a script per shot (as TAG TEAM is in David's project); after: one When block for
the combo, the combos in a row in its score, the palette's new When and value blocks.
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad658 as G  # noqa: E402
import webui_shot  # noqa: E402


def num(v):
    return {"k": "num", "v": v}


LIGHTS = [{"op": "light_shot", "shot": "Pop bumper", "color": "#ffb000", "pattern": "chase", "rate": num(100)},
          {"op": "light_shot", "shot": "Mecha exit bottom", "color": "#ffb000", "pattern": "chase", "rate": num(100)}]
OUT = [{"op": "lights_off", "shot": "Pop bumper"}, {"op": "lights_off", "shot": "Mecha exit bottom"}]
HUD = {"on": True, "line": "SHOOT THE GODZILLA TARGET"}
START = {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]}


def by_hand():
    """TAG TEAM as David's project builds it: the target starts a 20 s window; a pop or the Mecha lane starts a 1 ms
    timer whose script counts the combo while the window runs."""
    return {"name": "TAG TEAM", "seconds": 60, "game_modes": "stack", "hud": HUD,
            "vars": [{"name": "combos", "reset": "mode"}], "timers": [{"name": "combo"}, {"name": "caesar"}],
            "scripts": [
                START,
                {"hat": {"kind": "shot", "shot": "Godzilla target", "when": "running"},
                 "do": [{"op": "timer_start", "timer": "combo", "ms": num(20000)}] + LIGHTS},
                {"hat": {"kind": "shot", "shot": "Pop bumper", "when": "running"},
                 "do": [{"op": "timer_start", "timer": "caesar", "ms": num(1)}]},
                {"hat": {"kind": "shot", "shot": "Mecha exit bottom", "when": "running"},
                 "do": [{"op": "timer_start", "timer": "caesar", "ms": num(1)}]},
                {"hat": {"kind": "timer_done", "timer": "caesar"}, "do": [
                    {"op": "if", "cond": {"k": "cmp", "op": ">", "a": {"k": "timer_left", "timer": "combo"},
                                          "b": num(0)},
                     "then": [{"op": "timer_stop", "timer": "combo"},
                              {"op": "change", "var": "combos", "by": num(1)},
                              {"op": "score", "points": {"k": "op", "op": "*", "a": num(2000000),
                                                         "b": {"k": "var", "name": "combos"}}},
                              {"op": "hud_award", "text": "TAG TEAM COMBO", "value": {"k": "var", "name": "combos"},
                               "sub": "", "seconds": 3}] + OUT,
                     "else": None}]},
                {"hat": {"kind": "timer_done", "timer": "combo"}, "do": OUT},
            ]}


def as_block():
    """The same with the combo block: a lit shot within 20 s of the Godzilla target."""
    return {"name": "TAG TEAM", "seconds": 60, "game_modes": "stack", "hud": HUD, "vars": [], "timers": [],
            "scripts": [
                START,
                {"hat": {"kind": "shot", "shot": "Godzilla target", "when": "running"}, "do": LIGHTS},
                {"hat": {"kind": "combo", "shots": ["Godzilla target", "lit"], "seconds": 20, "when": "running",
                         "name": "TAG TEAM"}, "do": [
                    {"op": "score", "points": {"k": "op", "op": "*", "a": num(2000000), "b": {"k": "combo_chain"}}},
                    {"op": "hud_award", "text": "TAG TEAM COMBO", "value": {"k": "combo_chain"}, "sub": "",
                     "seconds": 3}] + OUT},
            ]}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    after = "combo" in BM.HATS
    scratch = tempfile.mkdtemp(prefix="pad708-")
    project = G._project(scratch)
    slug, _path = BM.new_blocks_mode(project, "TAG TEAM")
    BM.save(project, slug, as_block() if after else by_hand())
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            time.sleep(4)
            G._hide_log(page)
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(4)
            out = os.path.join(out_dir, "%s_combo_blocks.png" % prefix)
            page.screenshot(path=out, full_page=True)
            print("shot", out, flush=True)
        S._shoot(url, go, height=2500)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
