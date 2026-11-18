"""PAD-1401 proof shots: several of my modes running at once (layers).

    python scripts/shot_pad1401.py <repo> <out_dir> [prefix]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). On an
Uncanny X-Men LE 0.98 project with FUTURE (a form mode that is the whole game), STORM (a form mode set to run over
the others, inside FUTURE, keeping the shots) and WOLVERINE (a blocks mode set to run over them, at priority 30):

- <prefix>form_my_modes.png: STORM open on its page, scrolled to "The game's own modes". Before: nothing about my
  other modes (one at a time, always). After: "My other modes" under it - over them, as a layer, at priority 20,
  inside FUTURE, the shots its alone.
- <prefix>blocks_my_modes.png: WOLVERINE in the blocks editor, its settings at the game's modes row. After: "With my
  other modes, it runs over them, as a layer at priority 30".

Needs Playwright (the user site-packages one, or PAD_PWLIB) and the installed Edge.
"""
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad666 as S6  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\uncanny_xmen_le-0_98_0.Release.16G.sdcard.raw"


def _project(scratch):
    project = os.path.join(scratch, "X-Men 0.98 LE Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3] if len(sys.argv) > 3 else ""
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    print("serving", repo, flush=True)

    def shot(page, name):
        out = os.path.join(out_dir, "%s%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    scratch = tempfile.mkdtemp(prefix="pad1401-")
    project = _project(scratch)
    prof = MP.profile("uncanny_xmen_le_0_98")
    base, _b = MP.new_mode(project, "FUTURE")
    spec = MP.blank_spec(prof, "FUTURE")
    spec.game_modes = "own_game"
    MP.save(project, base, spec)
    form, _f = MP.new_mode(project, "STORM")
    spec = MP.blank_spec(prof, "STORM")
    spec.game_modes = "stack"
    if hasattr(spec, "layer"):                       # the ticket's branch: a layer inside FUTURE
        spec.layer, spec.layer_priority, spec.layer_shots, spec.inside = True, 20, True, "FUTURE"
    MP.save(project, form, spec)
    bslug, _c = BM.new_blocks_mode(project, "WOLVERINE", [])
    prog = BM.load(project, bslug)
    prog.update({"game_modes": "stack", "layer": True, "layer_priority": 30})
    BM.save(project, bslug, prog)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(4)
            S6._hide_log(page)
            row = page.locator(".modes-list .li", has_text=re.compile("STORM"))
            if row.count():
                row.first.click()
                time.sleep(3)
                page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                    e.children.length === 0 && e.textContent.trim() === "The game's own modes");
                    if (h) h.scrollIntoView({ block: 'start' }); }""")
                print("my other modes section:", page.evaluate("""() => !![...document.querySelectorAll('*')].find((e) =>
                    e.children.length === 0 && e.textContent.trim() === "My other modes")"""), flush=True)
                page.mouse.move(5, 1090)
                time.sleep(1)
                shot(page, "form_my_modes")
            row = page.locator(".modes-list .li", has_text=re.compile("WOLVERINE"))
            if not row.count():
                print("no blocks row", flush=True)
                return
            row.first.click()
            time.sleep(3)
            tab = page.locator("button, [role=tab]", has_text="Blocks")
            if tab.count():
                tab.first.click()
                time.sleep(1.5)
            gm = page.locator(".bk-gamemodes").first
            if gm.count():
                gm.evaluate("e => e.scrollIntoView({block: 'start'})")
                page.evaluate("() => window.scrollBy(0, -60)")
            print("blocks rows:", page.locator(".bk-gamemodes").count(), flush=True)
            page.mouse.move(5, 1090)
            time.sleep(1)
            shot(page, "blocks_my_modes")
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
