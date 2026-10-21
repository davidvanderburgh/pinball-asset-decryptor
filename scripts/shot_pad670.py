"""PAD-670 proof shots: the Modes tab's two shaker tooltips, on a Godzilla Premium/LE 1.16 project.

    python scripts/shot_pad670.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). Writes
into <out_dir>:

- <prefix>_form_shaker_tip.png    a form mode's Shaker section, its tooltip up (the ceiling's sentence)
- <prefix>_blocks_shake_tip.png   KING CAESAR's blocks, the Shake the cabinet block's tooltip up
"""

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad670-")
    project = os.path.join(scratch, "GZ 1.16 LE Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    spec = MP.blank_spec(MP.profile("godzilla_le_1_16"), "SHAKE IT")
    form_slug, _ = MP.new_mode(project, spec=spec)
    kc_slug, _ = BM.add_example(project, "KING CAESAR")
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            time.sleep(4)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            webui_shot.api(url, "modes.select", form_slug, "form")
            time.sleep(3)
            box = page.get_by_text("Shake the cabinet as it starts")
            box.first.scroll_into_view_if_needed()
            time.sleep(0.8)
            box.first.hover()
            time.sleep(1.5)
            shot(page, "form_shaker_tip")
            webui_shot.api(url, "modes.select", kc_slug, "code")
            time.sleep(3)
            word = page.locator(".bk-w", has_text="Shake the cabinet")
            if word.count():
                word.first.scroll_into_view_if_needed()
                time.sleep(0.8)
                word.first.hover()
                time.sleep(1.5)
            else:
                print("no Shake the cabinet block", flush=True)
            shot(page, "blocks_shake_tip")
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
