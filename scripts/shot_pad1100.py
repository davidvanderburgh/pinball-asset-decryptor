"""PAD-1100 proof shots: Load modes on a dual-boot Godzilla card recorded as the wrong build.

    python scripts/shot_pad1100.py <repo> <out_dir> <card> [--after]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot). <card> is a Godzilla Pro 1.16 card image whose ``/spk/index`` also keeps a 1.13
index (and a second image under ``img1/``), as Brombomb's dual-boot card did: before PAD-1100
its extract recorded it as godzilla_pro 1.13.0, so the project made here carries that record.
A modes file made for Godzilla Pro 1.16 is then loaded with Load modes from a file...

- load_modes.png   the Modes tab with the Load modes answer on it

Needs Playwright (PAD_PWLIB or the user site-packages one), the installed Edge.
"""
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad396 as p396  # noqa: E402


def main():
    repo, out_dir, card = (os.path.abspath(a) for a in sys.argv[1:4])
    after = "--after" in sys.argv
    sys.path.insert(0, repo)
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad1100-")
    # the reporter's project: the old extract's record of the dual-boot card
    mine = os.path.join(scratch, "GZ Heisei dual boot")
    os.makedirs(mine)
    with open(os.path.join(mine, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": os.path.basename(card),
                   "size": os.path.getsize(card), "card_version": "1.13.0"}, f)
    # the modes pack: one mode made for Godzilla Pro 1.16
    pack_src = p396._project(scratch, "pack", p396.PRO_CARD)
    spec = MP.ModeSpec(name="MOTHRA HUNT", title="godzilla_pro_1_16")
    spec.start_shot, spec.start_count = "Right ramp", 2
    spec.scoring_shots = ["Right ramp"]
    MP.new_mode(pack_src, spec=spec)
    pack = os.path.join(scratch, "daveyvandy modes.zip")
    MP.export_modes(pack_src, pack)
    proc, url = p396._serve(repo, scratch, mine, [mine])
    try:
        def shoot(page):
            time.sleep(25)                       # the card's read: program, port, own modes
            threading.Thread(target=webui_shot.api, args=(url, "modes.load_file", pack),
                             daemon=True).start()
            time.sleep(8)
            modal = page.query_selector(".modal")
            if modal:
                print("dialog:", modal.inner_text().replace("\n", " | "), flush=True)
            page.mouse.move(5, 990)
            page.screenshot(path=out("load_modes.png"))
            rec = json.load(open(os.path.join(mine, ".extract_source.json"), encoding="utf-8"))
            print("record card_version:", rec.get("card_version"), flush=True)
            print("modes:", sorted(os.listdir(MP.modes_dir(mine)))
                  if os.path.isdir(MP.modes_dir(mine)) else [], flush=True)
            btn = page.query_selector('.modal .ft button:has-text("OK")')
            if btn:
                btn.click()
        p396.S._shoot(url, shoot, height=1000)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
