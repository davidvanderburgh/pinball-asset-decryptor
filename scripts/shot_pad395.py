"""PAD-395 proof shots: the block editor's Mechanisms blocks (hold the magnet, a mechanism, a ball in the scoop).

    python scripts/shot_pad395.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Writes into <out_dir>:

- <prefix>_blocks_le116.png  a blocks mode on a Godzilla Premium/LE 1.16 project: the first slingshot starts
  it, the Godzilla target holds the magnet 2 s, the left ramp the bridge 3 s, it holds the next ball in the
  scoop 5 s as it starts (on a tree with the blocks; on one without, the same mode with none of them)
- <prefix>_blocks_pro115.png  the same on a Godzilla Pro 1.15 project, where none of it can be held: the
  Mechanisms blocks are greyed, each saying why
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

CARDS = {"le116": ("GZ 1.16 Premium Extract", "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"),
         "pro115": ("GZ 1.15 Pro Extract", "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw")}


def program(BM):
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    has = "hold" in BM.STATEMENTS
    start = [{"op": "start_mode"}]
    on_start = [{"op": "log", "text": "COIL TEST"}]
    target = [{"op": "score", "points": num(1000000)}]
    ramp = [{"op": "score", "points": num(500000)}]
    if has:
        on_start.append({"op": "scoop_hold", "ms": num(5000), "which": "next"})
        target.append({"op": "hold", "what": "magnet", "ms": num(2000)})
        ramp.append({"op": "hold", "what": "bridge", "ms": num(3000)})
    return {
        "name": "COIL TEST", "seconds": 0, "ends_on_drain": True, "screen": False,
        "scripts": [
            {"hat": {"kind": "shot", "shot": "Slingshot", "when": "idle"}, "do": start},
            {"hat": {"kind": "mode_start"}, "do": on_start},
            {"hat": {"kind": "shot", "shot": "Godzilla target", "when": "running"}, "do": target},
            {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": ramp},
        ]}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    for screen, (folder, card) in CARDS.items():
        scratch = tempfile.mkdtemp(prefix="pad395-")
        project = os.path.join(scratch, folder)
        os.makedirs(project)
        with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
        slug, _path = BM.new_blocks_mode(project, "COIL TEST")
        BM.save(project, slug, program(BM))
        proc, url = S._serve(repo, scratch, project)
        try:
            def blocks(page, screen=screen):
                webui_shot.api(url, "modes.select", slug, "code")
                time.sleep(3)
                out = os.path.join(out_dir, "%s_blocks_%s.png" % (prefix, screen))
                page.screenshot(path=out)
                print("shot", out, flush=True)
            S._shoot(url, blocks, height=1350)
        finally:
            proc.terminate()


if __name__ == "__main__":
    main()
