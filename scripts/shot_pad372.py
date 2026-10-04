"""PAD-372 proof shot: the block editor with the clock blocks.

    python scripts/shot_pad372.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot). Writes <out_dir>/<prefix>_blocks_clock.png: a blocks mode whose Maser target
script holds MASER BARRAGE's rule (under 10 s left, the clock goes back to 10) and whose jackpot
adds a value of seconds, open in the editor with the palette beside it.
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

    scratch = tempfile.mkdtemp(prefix="pad372-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    slug, _path = BM.new_blocks_mode(project, "MASER BARRAGE", example="ramps")
    p = BM.load(project, slug)
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    for s in p["scripts"]:
        for b in s.get("do") or []:
            if b.get("op") == "add_time":           # the jackpot adds combo x 2 seconds
                b["seconds"] = {"k": "op", "op": "*", "a": {"k": "var", "name": "combo"}, "b": num(2)}
    # the two clock scripts first, so they are on screen
    jack = [s for s in p["scripts"] if any(b.get("op") == "add_time" for b in s.get("do") or [])]
    p["scripts"] = jack + [s for s in p["scripts"] if s not in jack]
    p["scripts"].insert(0, {"hat": {"kind": "shot", "shot": "Maser target", "when": "running"}, "do": [
        {"op": "if", "cond": {"k": "cmp", "op": "<", "a": {"k": "secs_left"}, "b": num(10)},
         "then": [{"op": "set_time", "seconds": num(10)}], "else": None}]})
    BM.save(project, slug, p)
    proc, url = S._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_blocks_clock.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1250)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
