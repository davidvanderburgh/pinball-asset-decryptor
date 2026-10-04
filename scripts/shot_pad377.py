"""PAD-377 proof shot: the block editor with shared variables, a timer in ms, the wait-out-a-
multiball start and the display priority.

    python scripts/shot_pad377.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot). Writes <out_dir>/<prefix>_blocks_state.png: MASER BARRAGE's chain rebuilt in
blocks - a 7000 ms window between steps that shrinks by 1000 ms a barrage, "maser played" and
"maser won" shared with the other modes (FINAL WARS reads them), the start waiting out a
multiball, display priority 180 - open in the editor with the palette beside it.
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402


def maser_program(name="MASER BARRAGE"):
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    var = lambda n: {"k": "var", "name": n}                         # noqa: E731
    eq = lambda a, b: {"k": "cmp", "op": "=", "a": a, "b": b}       # noqa: E731
    return {
        "name": name, "seconds": 40, "ends_on_drain": True, "screen": False,
        "wait_multiball": True, "priority": 180,
        "vars": [{"name": "step", "reset": "mode"}, {"name": "mult", "reset": "mode"},
                 {"name": "window", "reset": "mode"},
                 {"name": "maser played", "reset": "game", "shared": True},
                 {"name": "maser won", "reset": "game", "shared": True}],
        "timers": [{"name": "chain"}],
        "scripts": [
            {"hat": {"kind": "shot", "shot": "Maser target", "when": "idle"}, "do": [
                {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "hits", "shot": "Maser target"},
                                      "b": num(3)},
                 "then": [{"op": "start_mode"}], "else": None}]},
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "set", "var": "maser played", "value": num(1)},
                {"op": "set", "var": "mult", "value": num(1)},
                {"op": "set", "var": "window", "value": num(7000)}]},
            {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
                {"op": "if", "cond": eq(var("step"), num(0)), "then": [
                    {"op": "score", "points": {"k": "op", "op": "*", "a": num(1000000), "b": var("mult")}},
                    {"op": "set", "var": "step", "value": num(1)},
                    {"op": "timer_start", "timer": "chain", "ms": var("window")}], "else": None}]},
            {"hat": {"kind": "shot", "shot": "Building", "when": "running"}, "do": [
                {"op": "if", "cond": {"k": "and", "a": eq(var("step"), num(1)),
                                      "b": {"k": "cmp", "op": ">", "a": {"k": "timer_left", "timer": "chain"},
                                            "b": num(0)}}, "then": [
                    {"op": "score", "points": {"k": "op", "op": "*", "a": num(5000000), "b": var("mult")}},
                    {"op": "set", "var": "maser won", "value": num(1)},
                    {"op": "change", "var": "mult", "by": num(1)},
                    {"op": "change", "var": "window", "by": num(-1000)},
                    {"op": "set", "var": "step", "value": num(0)},
                    {"op": "timer_stop", "timer": "chain"}], "else": None}]},
            {"hat": {"kind": "timer_done", "timer": "chain"}, "do": [
                {"op": "set", "var": "mult", "value": num(1)},
                {"op": "set", "var": "step", "value": num(0)},
                {"op": "log", "text": "CHAIN BROKEN"}]},
        ]}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    scratch = tempfile.mkdtemp(prefix="pad377-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    slug, _path = BM.new_blocks_mode(project, "MASER BARRAGE", example="ramps")
    p = maser_program()
    p["scripts"] = p["scripts"][2:] + p["scripts"][:2]     # the timer's scripts first, so they are on screen
    BM.save(project, slug, p)
    proc, url = S._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_blocks_state.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1350)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
