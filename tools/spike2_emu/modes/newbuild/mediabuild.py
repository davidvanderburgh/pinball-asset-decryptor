"""mediabuild.py <key> <card> <card version> <out dir> - a build's Try it set for the media proof (mediajob.sh): one
mode, MEDIA TEST, with its own screen and a 4 s title-card clip at its start, both magenta, built as the Modes tab's
Try it builds it (mode_tryit.build_set) against the build's shipped port. PAD-1555 (PAD-420's media/build2.py, re-made).

The proof comes before the proven flag, so for this build only, in this process, TITLE_SCENES' screen_proven /
clip_proven are taken as set and the mode maker's preview switch as on. Prints the set's run env and stage dir."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
from pinball_decryptor.core import preview  # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402
from pinball_decryptor.plugins.stern import mode_tryit as MT  # noqa: E402
from pinball_decryptor.plugins.stern import mode_write as MW  # noqa: E402

MAGENTA = "#ff00ff"


def main(key, card, version, out):
    real = preview.enabled
    preview.enabled = lambda feature: feature == "modes" or real(feature)
    MW.host_refusal = lambda platform=None: ""
    if key in MP.TITLE_SCENES:
        MP.TITLE_SCENES[key] = dict(MP.TITLE_SCENES[key], screen_proven=True, clip_proven=True)
    MP._profiles_cache = None if hasattr(MP, "_profiles_cache") else None
    pkey = key.replace("-", "_").replace(".", "_")
    prof = MP.profile(pkey)
    project = os.path.join(out, "proj")
    os.makedirs(project, exist_ok=True)
    name = os.path.basename(card)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": card, "input_name": name, "size": 1, "mtime": 1, "card_version": version}, f)
    cannot = [c[0] for c in prof.cannot if c[0] in ("screen", "clip")]
    if cannot:
        print("REFUSED: %s still cannot %s" % (key, ", ".join(cannot)))
        return 2
    MP.new_mode(project, "MEDIA TEST", MP.ModeSpec(
        name="MEDIA TEST", title=prof.key, start_shot=prof.example_start_shot,
        scoring_shots=[n for n, _m in prof.shots][:2], screen=True, panel_color=MAGENTA, title_color=MAGENTA,
        clip="title", clip_seconds=4.0, clip_when="start"))
    ts = MT.build_set(project, card, base=os.path.join(out, "try"))
    print("STAGE", ts.stage_dir)
    print("ENV", " ".join(MT.run_env(ts)))
    print("FILES", len(ts.files))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:5]))
