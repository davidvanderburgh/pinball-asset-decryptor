"""PAD-642 proof shot: James Bond 007 LE 1.06's own lit-shot flash offered among its light shows on the Modes tab.

    python scripts/shot_pad642.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Writes <out_dir>/<prefix>_form_lights.png: a form mode on a James Bond 007 LE 1.06 project open on its Lights
page, "The game's light shows" section in view with the list of shows open (on the ticket's tree from its "When a
shot is hit" box, with the Lit shot flash shows in it; before it, the "When it starts" box's list).
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
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad642-")
    project = S._project(scratch, "Bond LE 1.06 Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="GOLDEN GUN", title="james_bond_le_1_06")
    spec.start_shot, spec.scoring_shots = "Left orbit", ["Left orbit", "Right orbit"]
    has = hasattr(spec, "show_hit")
    if has:
        spec.show_hit = "Lit shot flash red"
    slug, _path = MP.new_mode(project, spec=spec)
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.evaluate("""() => { const t = [...document.querySelectorAll('button[role=tab]')].find((e) =>
                e.textContent.trim() === 'Lights'); if (t) t.click(); }""")
            time.sleep(1.5)
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === 'The shots that score');
                if (h) h.scrollIntoView({ block: 'start' }); }""")
            time.sleep(1)
            label = "When a shot is hit" if has else "When it starts"
            # a native <select> list cannot be screenshotted open: lay its list out in place for the shot
            picked = page.evaluate("""(label) => { const l = [...document.querySelectorAll('span.lbl')].find((e) =>
                e.textContent.trim() === label); const sel = l && l.nextElementSibling.querySelector('select');
                if (!sel) return ''; const n = sel.querySelectorAll('option, optgroup').length;
                sel.size = n; sel.style.height = 'auto'; sel.style.overflow = 'hidden';
                const w = sel.parentElement; w.style.height = 'auto'; w.style.width = '320px';
                const c = w.querySelector('.caret'); if (c) c.style.display = 'none'; return sel.value; }""", label)
            time.sleep(1.5)
            out = os.path.join(out_dir, "%s_form_lights.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, "- the box's value:", picked, flush=True)
        S._shoot(url, form, height=1900)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
