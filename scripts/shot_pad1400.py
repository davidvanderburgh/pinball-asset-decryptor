"""PAD-1400 proof shots: a mode can switch Stern's own game off for a whole game.

    python scripts/shot_pad1400.py <repo> <out_dir> [prefix]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). On an
Uncanny X-Men LE 0.98 project:

- <prefix>form_game_modes.png: a form mode open on its page, scrolled to "The game's own modes", with the choice's
  list opened out. Before: may start / may start and end this one / cannot start. After: a fourth choice, the whole
  game (Stern's rules off, the mode lasting every ball and player).
- <prefix>blocks_game_modes.png: a blocks mode open in the editor, its settings row at the top: the same choice.

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
WHOLE = os.environ.get("PAD1400_WHOLE") == "1"     # after: the form mode set to the whole game


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

    scratch = tempfile.mkdtemp(prefix="pad1400-")
    project = _project(scratch)
    form, _blank = MP.new_mode(project, "UNCANNY GAME")
    spec = MP.blank_spec(MP.profile("uncanny_xmen_le_0_98"), "UNCANNY GAME")
    if WHOLE and "own_game" in MP.GAME_MODES:
        spec.game_modes = "own_game"
    MP.save(project, form, spec)
    bslug, _c = BM.new_blocks_mode(project, "SENTINEL WAR", [])
    if WHOLE and "own_game" in BM.GAME_MODES:
        prog = BM.load(project, bslug)
        prog["game_modes"] = "own_game"
        BM.save(project, bslug, prog)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            page.on("console", lambda m: m.type == "error" and print("console:", m.text, flush=True))
            time.sleep(4)
            S6._hide_log(page)
            row = page.locator(".modes-list .li", has_text=re.compile("UNCANNY GAME"))
            if row.count():
                row.first.click()
                time.sleep(3)
                page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                    e.children.length === 0 && e.textContent.trim() === "The game's own modes");
                    if (h) h.scrollIntoView({ block: 'start' }); }""")
                opts = page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                    e.children.length === 0 && e.textContent.trim() === "The game's own modes");
                    const sec = h && h.closest('section, .sec, fieldset, div');
                    const sel = sec && (sec.parentElement || sec).querySelector('select');
                    return sel ? [...sel.options].map((o) => o.textContent) : []; }""")
                print("form choices:", opts, flush=True)
                page.mouse.move(5, 1090)
                time.sleep(1)
                shot(page, "form_game_modes")
            row = page.locator(".modes-list .li", has_text=re.compile("SENTINEL WAR"))
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
                print("blocks choices:", gm.locator("select").first.evaluate(
                    "s => [...s.options].map((o) => o.textContent)") if gm.locator("select").count() else [], flush=True)
            page.mouse.move(5, 1090)
            time.sleep(1)
            shot(page, "blocks_game_modes")
        S._shoot(url, go, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
