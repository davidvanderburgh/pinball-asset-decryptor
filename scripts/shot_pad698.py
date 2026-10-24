"""PAD-698 proof shot: the Modes page's Insider Connected note, on a Godzilla LE 1.16 project.

    python scripts/shot_pad698.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Writes
<out_dir>/<prefix>_modes_insider_note.png: the top of the Modes page, a form mode open, the note under the title.
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
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad698-")
    project = os.path.join(scratch, "GZ 1.16 LE Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    spec = MP.blank_spec(MP.profile("godzilla_le_1_16"), "KAIJU RUSH")
    slug, _ = MP.new_mode(project, spec=spec)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            time.sleep(4)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            note = page.locator(".modes-note")
            if note.count():
                note.first.scroll_into_view_if_needed()
                print("note:", note.first.inner_text(), flush=True)
            else:
                print("no .modes-note on the page", flush=True)
            time.sleep(1)
            out = os.path.join(out_dir, "%s_modes_insider_note.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, go, height=900)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
