"""PAD-1406 proof shot: the block editor's Flippers block, in a mode that is the whole game.

    python scripts/shot_pad1406.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Writes
<out_dir>/<prefix>_blocks_flippers.png: UNCANNY, a blocks mode that is the whole game on an Uncanny X-Men LE 0.98
project, its scripts and the palette's Mechanisms group. On a tree with the block, the Left ramp switches the flippers
off and the Right ramp back on (and the palette offers Flippers off / Flippers back on); before it, the same mode
with only a log line there (no block can do it).
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

    scratch = tempfile.mkdtemp(prefix="pad1406-")
    project = _project(scratch, "X-Men LE 0.98 Extract")
    slug, _path = BM.new_blocks_mode(project, "UNCANNY", example="ramps")
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    has = "flippers" in BM.STATEMENTS
    p = BM.load(project, slug)
    p["game_modes"] = "own_game"
    off = [{"op": "flippers", "to": "off"}] if has else [{"op": "log", "text": "flippers off: no block for it"}]
    on = [{"op": "flippers", "to": "on"}] if has else [{"op": "log", "text": "flippers on: no block for it"}]
    p["scripts"] = [
        {"hat": {"kind": "shot", "shot": "Left ramp tgt", "when": "running"}, "do": [
            {"op": "score", "points": num(500000)}] + off},
        {"hat": {"kind": "shot", "shot": "Right ramp tgt", "when": "running"}, "do": [
            {"op": "score", "points": num(250000)}] + on},
    ]
    BM.save(project, slug, p)
    proc, url = S._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            page.evaluate("""() => { const pal = document.querySelector('.bk-palette'); if (pal) {
                  const h = [...pal.querySelectorAll('*')].find((e) => /^Mechanisms/.test(e.textContent || '')
                    && e.children.length === 0); if (h) h.scrollIntoView(); } }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_flippers.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
