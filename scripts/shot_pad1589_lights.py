"""PAD-1589 proof shot: the Modes tab's Light shows preview with the Color-blind switch.

    python scripts/shot_pad1589_lights.py <repo> <out.png> [red_green|blue_yellow]

PAD-646's Godzilla Pro 1.15 project on the stock card (scripts/shot_pad646.py), its Kaiju roar show held part-way
through the burst (as scripts/shot_pad668.py). Before (main) the view has no Color-blind switch; after, the preset
named is pressed and the RGB inserts show its colors. The state file goes to a scratch home, never the real one.
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
import shot_pad646 as P  # noqa: E402
import webui_shot  # noqa: E402

LABELS = {"red_green": "Red-green", "blue_yellow": "Blue-yellow"}


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    preset = sys.argv[3] if len(sys.argv) > 3 else "red_green"
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM, mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad1589l-")
    home = os.path.join(scratch, "home")
    os.makedirs(home)
    real_home = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = os.environ["HOME"] = home          # the server inherits it: a scratch state file
    project = os.path.join(scratch, "GZ 1.15 Pro Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": P.CARD, "input_name": os.path.basename(P.CARD)}, f)
    slug, _path = BM.new_blocks_mode(project, "KAIJU LIGHTS", example="ramps")
    BM.save(project, slug, P._program(BM, MP, True))
    proc, url = S._serve(repo, scratch, project)
    for k, v in real_home.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
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
            time.sleep(1.0)
            page.locator(".ls-play").first.click()                       # hold the burst still
            time.sleep(0.5)
            page.evaluate("""() => { const r = document.querySelector('.ls-scrub');
                const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                set.call(r, '900'); r.dispatchEvent(new Event('input', { bubbles: true })); }""")   # the orange step
            time.sleep(0.8)
            if os.environ.get("PAD1589_OFF_TOO") and page.get_by_role("button", name="Off").count():
                page.get_by_role("button", name="Off").first.click()
                time.sleep(0.8)
                page.screenshot(path=out.replace(".png", "_off.png"))
            b = page.get_by_role("button", name=LABELS[preset])
            if b.count():
                b.first.click()
                time.sleep(0.8)
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, shots, height=1150)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
