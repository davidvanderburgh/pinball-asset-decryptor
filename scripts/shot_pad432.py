"""PAD-432 proof shots: modes taken from a card image.

    python scripts/shot_pad432.py <repo> <out_dir> [--after] [--card <image>]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots). A Godzilla Premium 1.16 project with one mode of its own is made in a scratch
folder. Photographs, under the same names before and after:

- modes_menu.png       the Modes tab's Save / load menu, open
- modes_load_card.png  (--card, after only) Load modes from a card image... of <image>: the
                       message the app answers with

Needs Playwright (PAD_PWLIB or the user site-packages one), the installed Edge.
"""
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
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    card = sys.argv[sys.argv.index("--card") + 1] if "--card" in sys.argv else ""
    sys.path.insert(0, repo)
    if os.environ.get("PAD_PWLIB"):
        sys.path.insert(0, os.environ["PAD_PWLIB"])
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    from pinball_decryptor.plugins.stern import mode_project as MP
    scratch = tempfile.mkdtemp(prefix="pad432-")
    mine = p396._project(scratch, "Heisei GZ 1.16 Premium", p396.LE_CARD)
    spec = MP.ModeSpec(name="KAIJU RUSH", title="godzilla_le_1_16")
    spec.start_shot, spec.start_count = "Right ramp", 2
    spec.scoring_shots = ["Right ramp"]
    MP.new_mode(mine, spec=spec)
    proc, url = p396._serve(repo, scratch, mine, [mine])
    try:
        def shoot(page):
            time.sleep(2)
            page.get_by_role("button", name="Save / load").first.click()
            time.sleep(1)
            page.screenshot(path=out("modes_menu.png"))
            page.keyboard.press("Escape")
            time.sleep(0.5)
            if card and after:
                threading.Thread(target=webui_shot.api, args=(url, "modes.load_card", card),
                                 daemon=True).start()
                time.sleep(20)
                modal = page.query_selector(".modal")
                if modal:
                    print("dialog:", modal.inner_text().replace("\n", " | "), flush=True)
                page.mouse.move(5, 990)
                page.screenshot(path=out("modes_load_card.png"))
                btn = page.query_selector('.modal .ft button:has-text("OK")')
                if btn:
                    btn.click()
        p396.S._shoot(url, shoot, height=1000)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
