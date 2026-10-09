"""PAD-474 proof shots: a mode shakes the cabinet on the other Spike 2 titles with a shaker, not only Godzilla.

    python scripts/shot_pad474.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Writes into <out_dir>:

- <prefix>_form_shaker.png   a form mode on a Teenage Mutant Ninja Turtles LE 1.59 project, scrolled to its Shaker
  section: a shake as it starts, on a shot and as it ends (before: greyed, "has not found how ... shakes")
- <prefix>_blocks_shaker.png a blocks mode on an Aerosmith 1.16 project that shakes the cabinet as it starts and
  with one of the game's own shakes on a shot (before: the blocks refused, the game's shakes "not on this game")
- <prefix>_jp_shaker.png     a form mode on a Jurassic Park LE 1.16 project (a title whose shaker is the optional kit's,
  found in its test menu's device record): before, no Shaker section at all; after, the section, live
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

TMNT = "turtles_le-1_59_0.Release.8G.sdcard.raw"
JP = "jurassic_park_le-1_16_0.Release.8G.sdcard.raw"
AERO = "aerosmith-1_16_0.Release.8G.sdcard.raw"


def _card_project(scratch, name, card):
    project = S._project(scratch, name)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    return project


def program(MP, title):
    p = MP.profile(title)
    shots = [n for n, _m in p.shots] if p is not None else []
    start, hit = (shots + ["", ""])[:2]
    games = [n for n, _l in getattr(p, "shakes", ())] if p is not None else []
    on_start = [{"op": "log", "text": "QUAKE"},
                {"op": "shake", "ms": {"k": "num", "v": 800}, "strength": "hard"}]
    on_hit = [{"op": "score", "points": {"k": "num", "v": 500000}},
              {"op": "shake_game", "shake": games[0] if games else "jackpot"}]
    return {
        "name": "QUAKE", "seconds": 30, "screen": False,
        "scripts": [
            {"hat": {"kind": "shot", "shot": start, "when": "idle"}, "do": [{"op": "start_mode"}]},
            {"hat": {"kind": "mode_start"}, "do": on_start},
            {"hat": {"kind": "shot", "shot": hit, "when": "running"}, "do": on_hit},
        ]}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    only = sys.argv[4:]                     # screens to shoot (form, blocks, jp); none = all
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP
    print("repo", repo, "mode_project", MP.__file__, flush=True)
    if "jp" in only or not only:
        jp_shot(repo, out_dir, prefix, MP, S, webui_shot)
    if only and "form" not in only and "blocks" not in only:
        return

    # the form: TMNT LE 1.59
    scratch = tempfile.mkdtemp(prefix="pad474-")
    project = _card_project(scratch, "TMNT 1.59 LE Extract", TMNT)
    p = MP.profile("turtles_le_1_59")
    print("turtles_le_1_59 can shaker:", p.can("shaker"), "|", p.why_not("shaker"), "| shakes", p.shakes,
          "| max", p.shake_max_ms, flush=True)
    shots = [n for n, _m in p.shots]
    spec = MP.ModeSpec(name="QUAKE", title="turtles_le_1_59")
    spec.start_shot, spec.scoring_shots = shots[0], shots[1:3]
    games = [n for n, _l in p.shakes]
    spec.shakes = [["start", 800, 0, ""], ["shot", games[0] if games else 500, 0, shots[1]],
                   ["end", 1000, 0, ""]]
    slug, _path = MP.new_mode(project, spec=spec)
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.evaluate("""() => { const leaf = (t) => [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === t);
                const h = leaf('Shaker') || leaf('Ball save');
                if (h) h.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_form_shaker.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=1500)
    finally:
        proc.terminate()

    # the blocks: Aerosmith 1.16
    scratch = tempfile.mkdtemp(prefix="pad474b-")
    project = _card_project(scratch, "Aerosmith 1.16 Extract", AERO)
    a = MP.profile("aerosmith_1_16")
    print("aerosmith_1_16 can shaker:", a.can("shaker"), "|", a.why_not("shaker"), "| shakes", a.shakes,
          "| max", a.shake_max_ms, flush=True)
    bslug, _bpath = BM.new_blocks_mode(project, "QUAKE BLOCKS")
    BM.save(project, bslug, program(MP, "aerosmith_1_16"))
    proc, url = S._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", bslug, "code")
            time.sleep(3)
            page.evaluate("""() => { const leaf = [...document.querySelectorAll('*')].filter((e) =>
                e.children.length === 0 && /^(Shake the cabinet:|When the mode starts)$/.test(e.textContent.trim()));
                const t = leaf.find((e) => e.textContent.trim() === 'Shake the cabinet:') || leaf[leaf.length - 1];
                if (t) t.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_shaker.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, blocks, height=1350)
    finally:
        proc.terminate()


def jp_shot(repo, out_dir, prefix, MP, S, webui_shot):
    scratch = tempfile.mkdtemp(prefix="pad474j-")
    project = _card_project(scratch, "JP 1.16 LE Extract", JP)
    p = MP.profile("jurassic_park_le_1_16")
    print("jurassic_park_le_1_16 can shaker:", p.can("shaker"), "|", p.why_not("shaker"), "| absent", p.absent,
          flush=True)
    shots = [n for n, _m in p.shots]
    spec = MP.ModeSpec(name="QUAKE", title="jurassic_park_le_1_16")
    spec.start_shot, spec.scoring_shots = shots[0], shots[1:3]
    if p.can("shaker"):
        spec.shakes = [["start", 500, 0, ""], ["end", 1000, 1, ""]]
    slug, _path = MP.new_mode(project, spec=spec)
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.evaluate("""() => { const leaf = (t) => [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === t);
                const h = leaf('Shaker') || leaf('Other mechanisms') || leaf('Ball save');
                if (h) h.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_jp_shaker.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=1500)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
