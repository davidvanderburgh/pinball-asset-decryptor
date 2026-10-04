"""PAD-376 proof shot: the block editor with the light-show block and a shot's blink rate.

    python scripts/shot_pad376.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot). Writes <out_dir>/<prefix>_blocks_lights.png: a blocks mode on Godzilla whose start
runs KING GHIDORAH's start show (its own steps: lightning, a strobe, a burst from the Building, a
fade) and lights the Building blinking every 500 ms, faster (250, then 100 ms) as the clock runs
down, and whose end runs a ready-made show; open in the editor with the palette beside it.
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

    scratch = tempfile.mkdtemp(prefix="pad376-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    slug, _path = BM.new_blocks_mode(project, "KING GHIDORAH", example="ramps")
    p = BM.load(project, slug)
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    step = lambda fx, ms, a, b, at, rate, gi: {"fx": fx, "ms": ms, "a": a, "b": b, "at": at,  # noqa: E731
                                               "rate": rate, "gi": gi}
    light = lambda ms: {"op": "light_shot", "shot": "Building", "color": "#ffb000",  # noqa: E731
                        "pattern": "blink", "rate": num(ms)}
    p["scripts"] = [
        {"hat": {"kind": "mode_start"}, "do": [
            {"op": "show", "show": "own", "steps": [
                step("bolts", 1500, "#ffb000", "#000000", "center", 190, "dark"),
                step("strobe", 500, "#ffffff", "#ffb000", "center", 60, "flash"),
                step("burst", 800, "#ffb000", "#ff4000", "top", 0, "dark"),
                step("fade", 400, "#ff4000", "#000000", "center", 0, "keep")]},
            light(500)]},
        {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [light(250)]},
        {"hat": {"kind": "seconds_left", "seconds": 4}, "do": [light(100)]},
        {"hat": {"kind": "mode_end"}, "do": [{"op": "show", "show": "rainbow"}]},
    ] + p["scripts"]
    BM.save(project, slug, p)
    proc, url = S._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_blocks_lights.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1500)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
