"""PAD-668 proof shots: the Modes tab's Light shows preview with the Real LEDs / All RGB switch and Insert colours.

    python scripts/shot_pad668.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). PAD-646's
Godzilla Pro 1.15 project on the stock card (scripts/shot_pad646.py), its Kaiju roar show part-way through the burst.
The insert colours go to a scratch home, never the real ~/.pad_playfield.json. Writes into <out_dir>:

- <prefix>_ls_real.png    the preview as it opens (after: Real LEDs - single-colour inserts white at the show's level)
- <prefix>_ls_rgb.png     after only: All RGB pressed - every insert in the show's colour, as before
- <prefix>_ls_lens.png    after only: Insert colours open, a few colours set, one row hovered (its insert ringed)
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad646 as P  # noqa: E402
import webui_shot  # noqa: E402

#: example colours for the shot - NOT Godzilla's real insert colours
EXAMPLE = {"LEFT OUTLANE": "#ff2a1a", "RIGHT OUTLANE": "#ff2a1a", "MASER": "#ffb000", "TANK 1": "#30e060",
           "TANK 2": "#30e060", "HEAT RAY L1": "#2a7fff", "HEAT RAY L2": "#2a7fff", "HEAT RAY L3": "#2a7fff"}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM, mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad668-")
    home = os.path.join(scratch, "home")
    os.makedirs(home)
    real_home = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = os.environ["HOME"] = home          # the server inherits it: a scratch state file
    project = os.path.join(scratch, "GZ 1.15 Pro Extract")
    os.makedirs(project)
    import json
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": P.CARD, "input_name": os.path.basename(P.CARD)}, f)
    slug, _path = BM.new_blocks_mode(project, "KAIJU LIGHTS", example="ramps")
    BM.save(project, slug, P._program(BM, MP, True))
    proc, url = S._serve(repo, scratch, project)
    for k, v in real_home.items():                                   # the browser wants the real one
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    def shot(page, name):
        out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        page.screenshot(path=out)
        print("shot", out, flush=True)

    try:
        def shots(page):
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            page.get_by_role("tab", name="Light shows").first.click()
            page.wait_for_selector(".ls-field .pf-art, .ls-field .pf-none", timeout=120000)
            pause = lambda: page.locator(".ls-play").first.click()        # noqa: E731
            time.sleep(1.0)
            pause()                                                       # hold the burst still for every shot
            time.sleep(0.5)
            shot(page, "ls_real")
            if not page.locator(".ls-look").count():
                return
            page.get_by_role("button", name="All RGB").click()
            time.sleep(0.8)
            shot(page, "ls_rgb")
            page.get_by_role("button", name="Real LEDs").click()
            page.locator(".ls-lens-hd").click()
            time.sleep(0.5)
            for name, colour in EXAMPLE.items():
                page.evaluate("""([n, c]) => { const r = [...document.querySelectorAll('.ls-lens-row')]
                    .find((x) => x.textContent.trim().startsWith(n) && x.textContent.trim().length < n.length + 3);
                    if (!r) return; const i = r.querySelector('input');
                    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    set.call(i, c); i.dispatchEvent(new Event('change', { bubbles: true })); }""", [name, colour])
                time.sleep(0.15)
            time.sleep(0.8)
            page.locator(".ls-lens-row", has_text="MASER").first.hover()
            time.sleep(0.6)
            shot(page, "ls_lens")
            with open(os.path.join(home, ".pad_playfield.json"), encoding="utf-8") as f:
                print("saved", json.load(f), flush=True)
        S._shoot(url, shots, height=1150)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
