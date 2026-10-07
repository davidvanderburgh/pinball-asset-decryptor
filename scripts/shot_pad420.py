"""PAD-420 proof shots: a mode on the newest Spike 2 builds, every page of the form, with no "Not on this game" text.

    python scripts/shot_pad420.py <repo> <out_dir> <prefix> <screen> [<screen> ...]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Each
<screen> is a key of SCREENS: a project on that build's stock card with one form mode, open; the shot is the whole
form, every page stacked (Basics, Show, Lights, Sound, Mechanisms...), so any yellow "Not on this game" line shows.
Writes <out_dir>/<prefix>_<screen>.png.
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

CARDS = r"D:\Pinball\images\Stern\spike2"

#: screen -> (card file, project name, title key)
SCREENS = {
    "james_bond_pro": ("james_bond_pro-1_06_0.Release.16G.sdcard.raw", "James Bond Pro 1.06 Extract", "james_bond_pro_1_06"),
    "rush_le": ("rush_le-1_19_0.Release.16G.sdcard.raw", "Rush LE 1.19 Extract", "rush_le_1_19"),
    "rush_pro": ("rush_pro-1_19_0.Release.16G.sdcard.raw", "Rush Pro 1.19 Extract", "rush_pro_1_19"),
    "jurassic_park_le": ("jurassic_park_le-1_16_0.Release.8G.sdcard.raw", "Jurassic Park LE 1.16 Extract",
                         "jurassic_park_le_1_16"),
    "deadpool_pro": ("deadpool_pro-1_16_0.Release.8G.sdcard.raw", "Deadpool Pro 1.16 Extract", "deadpool_pro_1_16"),
    "godzilla_pro": ("godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw", "Godzilla Pro 1.16 Extract",
                     "godzilla_pro_1_16"),
}

#: every page of the form, in its tab order: each is clicked and shot on its own
PAGES_JS = """() => [...document.querySelectorAll('.modes-editor button[role=tab]')].map((e) => e.textContent.trim())"""


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP
    from PIL import Image

    for screen in sys.argv[4:]:
        card, name, title = SCREENS[screen]
        scratch = tempfile.mkdtemp(prefix="pad420-")
        project = S._project(scratch, name)
        with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": os.path.join(CARDS, card), "input_name": card}, f)
        p = MP.profiles().get(title)
        if p is not None:
            spec = MP.blank_spec(p, name="SWEEP TEST")
            slug, _path = MP.new_mode(project, spec=spec)
        else:
            slug = ""
        proc, url = S._serve(repo, scratch, project)
        try:
            def shoot(page):
                if slug:
                    webui_shot.api(url, "modes.select", slug, "form")
                time.sleep(float(os.environ.get("SHOT_WAIT", "4")))
                names = page.evaluate(PAGES_JS) if slug else []
                parts = []
                for i, n in enumerate(names or [""]):
                    if n:
                        page.evaluate("""(n) => { const t = [...document.querySelectorAll('.modes-editor button[role=tab]')]
                            .find((e) => e.textContent.trim() === n); if (t) t.click(); }""", n)
                        time.sleep(1.2)
                    part = os.path.join(scratch, "page%02d.png" % i)
                    page.screenshot(path=part, full_page=True)
                    parts.append(part)
                ims = [Image.open(x) for x in parts]
                w = max(i.width for i in ims)
                out = Image.new("RGB", (w, sum(i.height for i in ims)), "white")
                y = 0
                for im in ims:
                    out.paste(im, (0, y))
                    y += im.height
                path = os.path.join(out_dir, "%s_%s.png" % (prefix, screen))
                out.save(path)
                print("shot", path, names, flush=True)
            S._shoot(url, shoot, height=int(os.environ.get("SHOT_H", "3000")))
        finally:
            proc.terminate()


if __name__ == "__main__":
    main()
