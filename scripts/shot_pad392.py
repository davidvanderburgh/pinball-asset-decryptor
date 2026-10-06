"""PAD-392 proof shots: the shield targets turned toward the player, from the form and from blocks.

    python scripts/shot_pad392.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Both on a Godzilla Premium/LE 1.16 project. Writes into <out_dir>:

- <prefix>_form_shield.png   a form mode open on its page, scrolled to the mechanisms: on a tree with the
  shield (ModeSpec.shield) its Shield targets section, ticked; before it, the same mode with no such section
- <prefix>_blocks_shield.png a blocks mode that turns the shield targets toward the player as it starts and
  stops keeping them with 10 s left (on a tree without the block, the same mode without it), its Mechanisms
  palette group in view
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

CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


def program(BM):
    has = "shield" in BM.STATEMENTS
    on_start = [{"op": "log", "text": "SHIELDS UP"}]
    late = [{"op": "log", "text": "ten seconds left"}]
    if has:
        on_start.append({"op": "shield", "where": "toward"})
        late.append({"op": "shield", "where": "leave"})
    return {
        "name": "SHIELDS UP", "seconds": 30, "screen": False,
        "scripts": [
            {"hat": {"kind": "shot", "shot": "Maser target", "when": "idle"}, "do": [{"op": "start_mode"}]},
            {"hat": {"kind": "mode_start"}, "do": on_start},
            {"hat": {"kind": "seconds_left", "seconds": 10}, "do": late},
        ]}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad392-")
    project = S._project(scratch, "GZ 1.16 Premium Extract")
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    spec = MP.ModeSpec(name="SHIELD TARGETS", title="godzilla_le_1_16")
    spec.start_shot, spec.scoring_shots = "Maser target", ["Shield target left", "Shield target center",
                                                           "Shield target right"]
    if hasattr(spec, "shield"):
        spec.shield = True
    slug, _path = MP.new_mode(project, spec=spec)
    bslug, _bpath = BM.new_blocks_mode(project, "SHIELDS UP")
    BM.save(project, bslug, program(BM))
    proc, url = S._serve(repo, scratch, project)
    try:
        def form(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === 'Ball save');
                if (h) h.scrollIntoView({ block: 'start' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_form_shield.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)

        def blocks(page):
            webui_shot.api(url, "modes.select", bslug, "code")
            time.sleep(3)
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim().toUpperCase() === 'MECHANISMS');
                if (h) h.scrollIntoView({ block: 'center' }); }""")
            page.evaluate("""() => { const all = [...document.querySelectorAll('*')].filter((e) =>
                e.children.length === 0 && /^(Turn the shield targets|SHIELDS UP)$/.test(e.textContent.trim()));
                const b = all.filter((e) => !e.closest('button'));
                const t = b.find((e) => e.textContent.trim() === 'Turn the shield targets') || b[b.length - 1];
                if (t) t.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_shield.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, form, height=1500)
        S._shoot(url, blocks, height=1350)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
