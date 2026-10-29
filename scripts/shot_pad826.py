"""PAD-826 proof shots: spare switches and outputs in a blocks mode, on the Modes tab.

    python scripts/shot_pad826.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A project
on the stock Godzilla Pro 1.16 card holding a blocks mode, SPARE TOY: a mod's own switch, wired to board 9 input 24,
starts it and fires a mod's own toy on board 9 output 4. Main has neither block, so its page shows the mode with a
plain When the mode starts script. Writes into <out_dir>:

- <prefix>_blocks.png     the blocks mode's page: its script, beside the palette's When list and Mechanisms
"""

import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad666 as S6  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"

PROGRAM = {
    "name": "SPARE TOY", "seconds": 30, "ends_on_drain": True,
    "scripts": [
        {"hat": {"kind": "spare_switch", "node": 9, "input": 24, "closed": "low", "when": "idle"},
         "do": [{"op": "start_mode"},
                {"op": "spare_drive", "node": 9, "output": 4, "power": 255, "ms": 40, "hold_power": 128,
                 "hold_ms": 500}]},
        {"hat": {"kind": "spare_switch", "node": 9, "input": 24, "closed": "low", "when": "running"},
         "do": [{"op": "score", "points": {"k": "num", "v": 1000000}},
                {"op": "spare_drive", "node": 9, "output": 4, "power": 255, "ms": 40, "hold_power": 0,
                 "hold_ms": 0}]},
    ],
}
PLAIN = {"name": "SPARE TOY", "seconds": 30, "ends_on_drain": True,
         "scripts": [{"hat": {"kind": "mode_start"}, "do": [{"op": "score", "points": {"k": "num", "v": 1000000}}]}]}


def _project(scratch):
    project = os.path.join(scratch, "Godzilla Pro 1.16 Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    print("serving", repo, flush=True)

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad826-")
    project = _project(scratch)
    slug, _c = BM.new_blocks_mode(project, "SPARE TOY", [])
    BM.save(project, slug, PROGRAM if "spare_switch" in BM.HATS else PLAIN)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(4)
            S6._hide_log(page)
            row = page.locator(".modes-list .li", has_text=re.compile("SPARE TOY"))
            if not row.count():
                print("no blocks row", flush=True)
                return
            row.first.click()
            time.sleep(3)
            tab = page.locator("button, [role=tab]", has_text="Blocks")
            if tab.count():
                tab.first.click()
                time.sleep(1.5)
            hat = page.locator(".bk-script").first
            if hat.count():
                hat.evaluate("e => e.scrollIntoView({block: 'start'})")
            for words in ("When a spare switch closes", "Drive a spare output"):
                print("palette %r on the page:" % words, page.get_by_text(words, exact=False).count(), flush=True)
            page.mouse.move(5, 1090)
            time.sleep(1)
            shot(page, "blocks")
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
