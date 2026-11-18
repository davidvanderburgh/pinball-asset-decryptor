"""PAD-1402 proof shots: saved progress (a variable that a mode remembers between games).

    python scripts/shot_pad1402.py <repo> <out_dir> <before|after>

A scratch Godzilla LE 1.16 project with one blocks mode, STORY, whose variables are a chapter (each player's), an
unlock (the machine's) and a hit count (each ball); HANDICAP ticked so the Service menu tab has a page to draw.
before (main): the variables can only reset each ball, mode or game, so the chapter and unlock are "each game".
after: they are "saved between games" and "saved for everyone", and the Service menu tab shows SAVED PROGRESS.
Writes <out_dir>/<kind>_variables.png and <kind>_service_menu.png. Playwright + the installed Edge (webui_shot.py).
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

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


def story_program(kind):
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    var = lambda n: {"k": "var", "name": n}                         # noqa: E731
    keep, everyone = ("game", "game") if kind == "before" else ("saved", "saved_all")
    return {
        "name": "STORY", "seconds": 0, "ends_on_drain": True, "screen": False,
        "vars": [{"name": "chapter", "reset": keep}, {"name": "unlocked", "reset": everyone},
                 {"name": "hits", "reset": "ball"}],
        "timers": [],
        "scripts": [
            {"hat": {"kind": "shot", "shot": "Left ramp", "when": "any"}, "do": [
                {"op": "change", "var": "hits", "by": num(1)},
                {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("hits"), "b": num(3)}, "then": [
                    {"op": "change", "var": "chapter", "by": num(1)},
                    {"op": "set", "var": "hits", "value": num(0)},
                    {"op": "log", "text": "CHAPTER UP"}], "else": None}]},
            {"hat": {"kind": "shot", "shot": "Building", "when": "any"}, "do": [
                {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("chapter"), "b": num(5)}, "then": [
                    {"op": "set", "var": "unlocked", "value": num(1)}], "else": None}]},
        ]}


def make_project(scratch):
    project = os.path.join(scratch, "Godzilla LE project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"handicap": {"on": True}}, f)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM

    scratch = tempfile.mkdtemp(prefix="pad1402-")
    project = make_project(scratch)
    slug, _path = BM.new_blocks_mode(project, "STORY", example="ramps")
    BM.save(project, slug, story_program(kind))
    proc, url = S._serve(repo, scratch, project)
    try:
        def shots(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            vars_row = page.locator(".bk-vars").first
            vars_row.scroll_into_view_if_needed()
            vars_row.evaluate("e => e.scrollIntoView({block: 'center'})")
            time.sleep(0.8)
            out = os.path.join(out_dir, "%s_variables.png" % kind)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            webui_shot.api(url, "ui.select_tab", "svcmenu")
            end = time.time() + 180
            s = {}
            while time.time() < end:
                s = webui_shot.state(url).get("svcmenu") or {}
                if s.get("menu") or s.get("why"):
                    break
                time.sleep(1)
            print("why:", s.get("why"), "refused:", (s.get("menu") or {}).get("refused"), flush=True)
            time.sleep(1.5)
            rows = page.locator(".sm-row", has_text="Saved Progress")
            if rows.count():
                rows.first.click()
                time.sleep(0.5)
            out = os.path.join(out_dir, "%s_service_menu.png" % kind)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, shots, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
