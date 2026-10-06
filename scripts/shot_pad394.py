"""PAD-394 proof shot: the Modes tab's Magnet, Scoop and Other mechanisms sections on another Spike 2 build.

    python scripts/shot_pad394.py <repo> <out_dir> <prefix> pro115|kingkong

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
Writes <out_dir>/<prefix>_<screen>.png: a form mode on a Godzilla Pro 1.15 or King Kong LE 0.97 project, open on
its page and scrolled to the sections between Ball save and Multiball - greyed with the reason before, offered after
(on Pro 1.15 the mode holds the magnet 2 s and a ball in the scoop 4 s; on King Kong the spider magnet 2 s as it
starts and the log diverter 3 s).
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

BUILDS = {
    "pro115": ("godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw", "GZ 1.15 Pro Extract", "godzilla_pro_1_15",
               "magnet"),
    "kingkong": ("king_kong_le-0_97_0.Release.16G.sdcard.raw", "King Kong LE 0.97 Extract", "king_kong_le_0_97",
                 "mechanisms"),
}


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    card, name, title, screen = BUILDS[sys.argv[4]]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad394-")
    project = S._project(scratch, name)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    p = MP.profiles(MP.PORTS_DIR).get(title) or MP.PROFILES[title]
    spec = MP.blank_spec(p, name="COIL TEST")
    if p.can("magnet"):
        spec.magnet_ms = 2000
    if p.can("scoop"):
        spec.scoop_hold_ms = 4000
    held = dict(p.held_coils) if p.can("coils") else {}
    if "spider_magnet" in held:
        spec.coil_holds = [["spider_magnet", 2000, ""], ["log_diverter", 3000, ""]]
    slug, _path = MP.new_mode(project, spec=spec)
    proc, url = S._serve(repo, scratch, project)
    try:
        def mechanisms(page):
            webui_shot.api(url, "modes.select", slug, "form")
            time.sleep(3)
            page.evaluate("""() => { const h = [...document.querySelectorAll('*')].find((e) =>
                e.children.length === 0 && e.textContent.trim() === 'Ball save');
                if (h) h.scrollIntoView({ block: 'start' }); }""")
            time.sleep(1)
            out = os.path.join(out_dir, "%s_%s.png" % (prefix, screen))
            page.screenshot(path=out)
            print("shot", out, flush=True)
        S._shoot(url, mechanisms, height=1300)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
