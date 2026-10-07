"""PAD-400 proof shots: our modes run alone on the other Spike 2 titles too - the Modes tab lists the game's
features that keep counting while a mode runs, read from each title's own program.

    python scripts/shot_pad400.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot).
A new form mode on each title, open on its page, scrolled to the end of "The game's own modes":

- <prefix>_venom_game_modes.png (Venom LE 1.07). Before: the game's modes only - no list of its features, so
  they all went on counting while the mode ran. After: its 19 features, none ticked (only the mode counts).
- <prefix>_deadpool_game_modes.png (Deadpool LE 1.14): the same, its 12 features.
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

TITLES = (("venom", "Venom LE Extract", "venom_le-1_07_0.Release.8G.sdcard.raw", "venom_le-1.07"),
          ("deadpool", "Deadpool LE Extract", "deadpool_le-1_14_0.Release.8G.sdcard.raw", "deadpool_le-1.14"))


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP

    for key, name, card, port in TITLES:
        scratch = tempfile.mkdtemp(prefix="pad400-")
        project = S._project(scratch, name)
        with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
        prof = MP.profile_from_port(os.path.join(repo, "tools", "spike2_emu", "modes", "sdk", "ports", port + ".port"))
        title = prof.key
        shots = [s[0] if isinstance(s, tuple) else s for s in prof.shots]
        spec = MP.ModeSpec(name="ALONE", title=title)
        spec.start_shot, spec.scoring_shots = shots[0], shots[1:3]
        slug, _path = MP.new_mode(project, spec=spec)
        proc, url = S._serve(repo, scratch, project)
        try:
            def form(page, key=key, slug=slug):
                webui_shot.api(url, "modes.select", slug, "form")
                time.sleep(3)
                # the features list comes after the game's modes (55 on Venom); on main there is none, so the
                # same place: the end of the modes list
                page.evaluate("""() => { const all = [...document.querySelectorAll('*')].filter((e) =>
                    e.children.length === 0);
                    const h = all.find((e) => e.textContent.trim() === "The game's features that keep counting while it runs")
                        || all.find((e) => e.textContent.trim() === "Can run during the game's own modes");
                    if (h) { h.scrollIntoView({ block: 'start' }); window.scrollBy(0, -260); } }""")
                time.sleep(1)
                out = os.path.join(out_dir, "%s_%s_game_modes.png" % (prefix, key))
                page.screenshot(path=out)
                print("shot", out, flush=True)
            S._shoot(url, form, height=2150)
        finally:
            proc.terminate()


if __name__ == "__main__":
    main()
