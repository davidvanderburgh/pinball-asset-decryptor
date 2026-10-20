"""PAD-646 proof shots: the light-show editor of a blocks mode on the Modes tab.

    python scripts/shot_pad646.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). A
Godzilla Pro 1.15 project on the stock card (its playfield picture is read off it), with a blocks mode whose start
runs a light show of its own steps. Writes into <out_dir>:

- <prefix>_light_shows.png  the place a show is made: before, the Light show block's own steps in the Blocks tab;
                            after, the Light shows tab (the mode's shows, the presets, the timeline, the preview)
- <prefix>_blocks_show.png  the Blocks tab's When the mode starts rule with its Light show block
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

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"


def _program(BM, MP, has_shows):
    shots = [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
    prog = BM.starter("KAIJU LIGHTS", shots)
    steps = [{"fx": "strobe", "ms": 450, "a": "#ffffff", "b": "#ff3000", "at": "center", "rate": 55, "gi": "flash"},
             {"fx": "burst", "ms": 800, "a": "#ffd000", "b": "#ff3000", "at": "center", "rate": 0, "gi": "dark"},
             {"fx": "spin", "ms": 1600, "a": "#00c0ff", "b": "#000000", "at": "center", "rate": 110, "gi": "dark"},
             {"fx": "fade", "ms": 400, "a": "#00c0ff", "b": "#000000", "at": "center", "rate": 0, "gi": "keep"}]
    start = next(s for s in prog["scripts"] if s["hat"]["kind"] == "mode_start")
    if has_shows:
        prog["shows"] = [
            {"name": "Kaiju roar", "steps": steps},
            {"name": "Atomic spiral", "steps": [
                {"fx": "spiral_out", "ms": 1800, "a": "#40a0ff", "b": "#001030", "at": "center", "rate": 120,
                 "gi": "dark"},
                {"fx": "fade_in", "ms": 600, "a": "#ffffff", "b": "#000000", "at": "center", "rate": 0, "gi": "dark",
                 "blend": 200},
                {"fx": "fade", "ms": 500, "a": "#ffffff", "b": "#000000", "at": "center", "rate": 0, "gi": "keep",
                 "blend": 150}]},
            {"name": "Victory", "steps": [dict(s) for s in BM.SHOWS["rainbow"][1]], "repeat": 2}]
        start["do"].insert(0, {"op": "show", "show": "mine", "name": "Kaiju roar"})
        end = next(s for s in prog["scripts"] if s["hat"]["kind"] == "mode_end")
        end["do"].insert(0, {"op": "show", "show": "mine", "name": "Victory"})
    else:
        start["do"].insert(0, {"op": "show", "show": "own", "steps": steps})
    return prog


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM, mode_project as MP

    has_shows = "shows" in BM.normalize({})
    scratch = tempfile.mkdtemp(prefix="pad646-")
    project = os.path.join(scratch, "GZ 1.15 Pro Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD)}, f)
    slug, _path = BM.new_blocks_mode(project, "KAIJU LIGHTS", example="ramps")
    BM.save(project, slug, _program(BM, MP, has_shows))
    proc, url = S._serve(repo, scratch, project)
    try:
        def shots(page):
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            # the When the mode starts rule, in view
            page.evaluate("""() => { const h = [...document.querySelectorAll('.bk-w, .bk-hat *')].find((e) =>
                /Run the light show|Run a light show of the mode's/.test(e.textContent));
                if (h) h.scrollIntoView({ block: 'center' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_blocks_show.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            tab = page.get_by_role("tab", name="Light shows")
            if tab.count():
                tab.first.click()
                page.wait_for_selector(".ls-field .pf-art, .ls-field .pf-none", timeout=120000)
                time.sleep(2.2)          # the preview plays: catch it part-way through the burst
            out = os.path.join(out_dir, "%s_light_shows.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, shots, height=1150)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
