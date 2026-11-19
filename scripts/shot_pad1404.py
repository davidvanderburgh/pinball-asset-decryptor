"""PAD-1404 proof shot: the block editor with a menu the player picks from with the flippers.

    python scripts/shot_pad1404.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Writes
<out_dir>/<prefix>_blocks_menus.png (the mode's settings: on a tree with menus, its EPISODE menu - title, items,
default, seconds, how the ball is held) and <prefix>_blocks_menu_scripts.png (its scripts: on a tree with menus,
Open the menu EPISODE at the mode's start and When the player picks from EPISODE, branching on the item picked).
EPISODE PICK is a blocks mode on an Uncanny X-Men LE 0.98 project.
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

ITEMS = ["DAYS OF FUTURE PAST", "DARK PHOENIX", "AGE OF APOCALYPSE", "SENTINELS", "DANGER ROOM"]


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

    scratch = tempfile.mkdtemp(prefix="pad1404-")
    project = _project(scratch, "X-Men LE 0.98 Extract")
    slug, _path = BM.new_blocks_mode(project, "EPISODE PICK", example="ramps")
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    menus = hasattr(BM, "MENUS_MAX")
    p = BM.load(project, slug)
    p["seconds"] = 0
    p["vars"] = [{"name": "episode", "reset": "game"}]
    pick = {"k": "menu_pick", "menu": "EPISODE"} if menus else num(1)
    branch = lambda n, words: {"op": "if", "cond": {"k": "cmp", "op": "=", "a": pick, "b": num(n)},   # noqa: E731
                               "then": [{"op": "words", "text": words}], "else": None}
    start = [{"op": "menu_open", "menu": "EPISODE"}] if menus else [{"op": "log", "text": "EPISODE PICK began"}]
    p["scripts"] = [
        {"hat": {"kind": "shot", "shot": "Xjet tgt", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "mode_start"}, "do": start},
    ]
    if menus:
        p["menus"] = [{"name": "EPISODE", "title": "CHOOSE YOUR EPISODE", "items": ITEMS, "default": 1,
                       "seconds": 10, "hold": "lane"}]
        p["scripts"].append({"hat": {"kind": "menu_pick", "menu": "EPISODE"}, "do": [
            {"op": "set", "var": "episode", "value": pick},
            branch(1, "DAYS OF FUTURE PAST"), branch(2, "DARK PHOENIX")]})
    BM.save(project, slug, p)
    proc, url = S._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                /^Menus/.test(e.textContent || '') && e.children.length === 0); if (h) h.scrollIntoView(); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_menus.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            page.evaluate("""() => { const w = document.querySelector('.bk-ws'); if (w) w.scrollTop = w.scrollHeight;
                const pal = document.querySelector('.bk-palette'); if (pal) {
                  const h = [...pal.querySelectorAll('*')].find((e) => /^Menus$/.test(e.textContent || '')
                    && e.children.length === 0); if (h) h.scrollIntoView(); } }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_menu_scripts.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1400)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
