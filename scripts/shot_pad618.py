"""PAD-618 proof shots: a blocks mode's challenge rule (PAD-615) in the Rule cards and Story views, Bond LE 1.06.

    python scripts/shot_pad618.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots).
Writes <prefix>_cards.png (the same before and after: cards use the Blocks wording) and <prefix>_story.png into
<out_dir>: before, the rule's When read the bare word "challenge" and Story put it among the rules that work while the mode runs; after, it reads "When the player
picks the challenge Duel on the Disco Volante" and sits in the box of rules that work before the mode starts.
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

CARD = "james_bond_le-1_06_0.Release.16G.sdcard.raw"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    scratch = tempfile.mkdtemp(prefix="pad618-")
    project = S._project(scratch, "Bond LE 1.06 Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    bslug, _bpath = BM.new_blocks_mode(project, "DAF WIZARD")
    scripts = [{"hat": {"kind": "challenge", "challenge": "Duel on the Disco Volante"}, "do": [{"op": "start_mode"}]},
               {"hat": {"kind": "mode_start"}, "do": [{"op": "log", "text": "DAF running"}]},
               {"hat": {"kind": "every", "seconds": 10}, "do": [{"op": "log", "text": "tick"}]}]
    BM.save(project, bslug, {"name": "DAF WIZARD", "seconds": 60, "screen": False, "game_modes": "block",
                             "scripts": scripts})
    proc, url = S._serve(repo, scratch, project)
    try:
        def views(page):
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            webui_shot.api(url, "modes.select", bslug, "code")
            time.sleep(3)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            for key, label in (("cards", "Rule cards"), ("story", "Story")):
                page.get_by_role("tab", name=label, exact=True).first.click()
                time.sleep(1.5)
                page.locator(".bk-pane").first.evaluate("(el) => el.scrollIntoView({block: 'start'})")
                page.mouse.move(5, 5)
                time.sleep(0.6)
                out = os.path.join(out_dir, "%s_%s.png" % (prefix, key))
                page.screenshot(path=out)
                print("shot", out, flush=True)
        S._shoot(url, views, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
