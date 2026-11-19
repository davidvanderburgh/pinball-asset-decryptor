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
    # PAD-1406 run 2: a second mode - the Sentinel's own devices (on a tree without them: a log line there)
    slug2, _path = BM.new_blocks_mode(project, "SENTINEL", example="ramps")
    q = BM.load(project, slug2)
    q["game_modes"] = "own_game"
    dev = "pulse" in BM.STATEMENTS
    jaw = ([{"op": "hold", "what": "sentinel_jaw", "ms": num(4000)}] if dev
           else [{"op": "log", "text": "the Sentinel jaw: no way to hold it"}])
    kick = ([{"op": "pulse", "what": "sentinel_kick"}] if dev
            else [{"op": "log", "text": "the kicking target: no way to fire it"}])
    q["scripts"] = [
        {"hat": {"kind": "shot", "shot": "Left ramp tgt", "when": "running"}, "do": [{"op": "score", "points": num(500000)}] + jaw},
        {"hat": {"kind": "shot", "shot": "Right ramp tgt", "when": "running"}, "do": [{"op": "score", "points": num(250000)}] + kick},
    ]
    BM.save(project, slug2, q)
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
            webui_shot.api(url, "modes.select", slug2, "code")
            time.sleep(3)
            page.evaluate("""() => { const w = document.querySelector('.bk-ws'); if (w) w.scrollTop = w.scrollHeight;
                const pal = document.querySelector('.bk-palette'); if (pal) {
                  const h = [...pal.querySelectorAll('*')].find((e) => /^Mechanisms/.test(e.textContent || '')
                    && e.children.length === 0); if (h) h.scrollIntoView(); } }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_devices.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1100)
    finally:
        proc.terminate()
    # PAD-1406 run 4: a whole-game mode on Turtles Pro 1.59 that holds the balls in its upper lock and lets them go
    scratch2 = tempfile.mkdtemp(prefix="pad1406t-")
    project2 = os.path.join(scratch2, "TMNT Pro 1.59 Extract")
    os.makedirs(project2)
    card = "turtles_pro-1_59_0.Release.16G.sdcard.raw"
    with open(os.path.join(project2, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project2, card), "input_name": card}, f)
    slug3, _path = BM.new_blocks_mode(project2, "LOCKS", example="ramps")
    r = BM.load(project2, slug3)
    r["game_modes"] = "own_game"
    dev = "device" in BM.STATEMENTS
    hold = ([{"op": "device", "what": "UPPER_LOCK", "keep": "hold"}] if dev
            else [{"op": "log", "text": "the upper lock: no way to hold its balls"}])
    go = ([{"op": "device", "what": "UPPER_LOCK", "keep": "let_go"}] if dev
          else [{"op": "log", "text": "the upper lock: no way to let its balls go"}])
    r["scripts"] = [{"hat": {"kind": "mode_start"}, "do": hold},
                    {"hat": {"kind": "every", "seconds": 30}, "do": [{"op": "score", "points": num(1000000)}] + go}]
    BM.save(project2, slug3, r)
    proc, url = S._serve(repo, scratch2, project2)
    try:
        def locks(page):
            webui_shot.api(url, "modes.select", slug3, "code")
            time.sleep(3)
            page.evaluate("""() => { const pal = document.querySelector('.bk-palette'); if (pal) {
                  const h = [...pal.querySelectorAll('*')].find((e) => /^Mechanisms/.test(e.textContent || '')
                    && e.children.length === 0); if (h) h.scrollIntoView(); } }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_locks.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, locks, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
