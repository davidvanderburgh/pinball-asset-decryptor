"""make_examples.py - write the blocks examples' JSON (PAD-658) from their Python, and check them.

    python make_examples.py                 write <slug>.json for every src_<slug>.py, then check them all
    python make_examples.py --check         check the JSON files as they are (nothing written)
    python make_examples.py [slug ...]      only those
    python make_examples.py --desk [slug]   also play each example's desk scenarios (needs Linux or WSL: gcc and the
                                            desk harness; on Windows it runs itself under WSL)

Each ``src_<slug>.py`` has ``build()`` -> the example (blk.py's words; block_modes.py's "the blocks examples" says
the shape) and, optionally, ``DESK``: [(what, [harness args], [lines the output must hold])]. The film recipe of
its own clips, sounds and music is ``recipes/<slug>.json`` (film_recipes.json's shape), when there is one.

The check: the program normalises to itself, block_modes.problems() finds nothing on Godzilla Premium/LE 1.16
(its shots, events, mechanisms, inserts, the game's light shows and shakes), every clip and sound has a recipe
cue and every recipe cue a clip or sound, and the C it makes compiles in the desk harness with no warning.
"""
import glob
import importlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(SDK, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
from pinball_decryptor.plugins.stern import block_modes as BM  # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402

TITLE = "godzilla_le_1_16"


def sources():
    return sorted(os.path.basename(p)[4:-3] for p in glob.glob(os.path.join(HERE, "src_*.py")))


def build(slug):
    mod = importlib.import_module("src_" + slug)
    ex = mod.build()
    rp = os.path.join(HERE, "recipes", slug + ".json")
    if os.path.isfile(rp):
        with open(rp, encoding="utf-8") as f:
            ex["recipe"] = json.load(f)
    ex["program"] = BM.normalize(ex["program"])
    return ex


def write(ex):
    path = os.path.join(HERE, ex["slug"] + ".json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ex, f, indent=1)
        f.write("\n")
    return path


def check(ex):
    """Every reason the example is not fit to offer, as sentences."""
    out = []
    p = ex["program"]
    if BM.normalize(p) != p:
        out.append("the program does not normalise to itself")
    prof = MP.profile(TITLE)
    out += BM.problems(p, **BM.card_checks(prof))
    r = ex.get("recipe") or {}
    clips = {c["name"] for c in p["clips"]}
    sounds = {c["name"] for c in p["sounds"]}
    if r:
        if clips != set(r.get("clips") or {}):
            out.append("clips %s but the recipe cuts %s" % (sorted(clips), sorted(r.get("clips") or {})))
        if sounds != set(r.get("calls") or {}):
            out.append("sounds %s but the recipe cuts %s" % (sorted(sounds), sorted(r.get("calls") or {})))
        if bool(p["music"]) != bool(r.get("music")):
            out.append("music and the recipe disagree")
        from pinball_decryptor.plugins.stern import code_modes as CM
        for k in BM.example_films(ex):
            if k not in CM.FILMS:
                out.append("film %s is not in film_recipes.json's films" % k)
    elif clips or sounds or p["music"]:
        out.append("it has its own clips or sounds but no recipe to cut them from")
    for c in p["clips"]:
        if c["file"] != c["name"] + ".mp4":
            out.append("clip %s's file is not %s.mp4" % (c["name"], c["name"]))
    for c in p["sounds"]:
        if c["file"] != c["name"] + ".wav":
            out.append("sound %s's file is not %s.wav" % (c["name"], c["name"]))
    if p["music"] not in ("", "music.wav"):
        out.append("music is not music.wav")
    n_blocks = sum(1 for s in p["scripts"] for _b in BM._walk(s.get("do") or []))
    if len(p["scripts"]) > BM.MAX_SCRIPTS or n_blocks > BM.MAX_BLOCKS:
        out.append("%d scripts / %d blocks: past the editor's limits" % (len(p["scripts"]), n_blocks))
    return out


def _wsl_path(p):
    p = os.path.abspath(p).replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:]


def desk(slugs, examples):
    """Build every example's C into ONE desk harness (as a card carries them) and play each one's scenarios."""
    if os.name == "nt":
        cmd = ["wsl.exe", "-d", "Ubuntu", "--", "python3", _wsl_path(__file__), "--desk-here"] + list(slugs)
        env = dict(os.environ, MSYS_NO_PATHCONV="1")
        return subprocess.call(cmd, env=env)
    work = os.path.join("/tmp", "pad658_desk", "-".join(slugs) or "all")   # one folder per run: agents run at once
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    srcs = []
    for ex in examples:
        src = os.path.join(work, ex["slug"] + ".c")
        with open(src, "w") as f:
            f.write(BM.to_c(ex["program"], ex["slug"]))
        srcs.append(src)
    shutil.copy(os.path.join(SDK, "examples", BM.KIT_FILE), work)
    exe = os.path.join(work, "harness")
    r = subprocess.run(["gcc", "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK, "-I", work,
                        "-o", exe, os.path.join(SDK, "examples", "desk_harness.c")] + srcs,
                       capture_output=True, text=True)
    if r.returncode or "warning" in r.stderr.lower():
        print(r.stderr)
        return 1
    bad = 0
    for ex in examples:
        if slugs and ex["slug"] not in slugs:
            continue
        mod = importlib.import_module("src_" + ex["slug"])
        for what, args, want in getattr(mod, "DESK", ()):
            r = subprocess.run([exe, "new_game"] + [str(a) for a in args], capture_output=True, text=True, timeout=120)
            log = os.path.join(work, "%s_%s.txt" % (ex["slug"], what.replace(" ", "_")))
            with open(log, "w") as f:
                f.write(r.stdout + r.stderr)
            missing = [w for w in want if w not in r.stdout]
            ok = r.returncode == 0 and not missing
            bad += not ok
            print("%-12s %-40s %s%s" % (ex["slug"], what, "ok" if ok else "FAILED", "" if ok else
                                         " (missing: %s; rc %d) see %s" % (missing, r.returncode, log)))
    return 1 if bad else 0


def main(argv):
    only = [a for a in argv if not a.startswith("--")]
    if "--desk-here" in argv:
        examples = [build(s) for s in (only or sources())]
        return desk(only, examples)
    if "--check" in argv:
        examples = []
        for p in sorted(glob.glob(os.path.join(HERE, "*.json"))):
            with open(p, encoding="utf-8") as f:
                examples.append(json.load(f))
    else:
        examples = [build(s) for s in (only or sources())]   # named: only those (others may be mid-edit)
        for ex in examples:
            write(ex)
    bad = 0
    for ex in examples:
        probs = check(ex)
        n = sum(1 for s in ex["program"]["scripts"] for _b in BM._walk(s.get("do") or []))
        print("%-18s %2d scripts %3d blocks  %s" % (ex["slug"], len(ex["program"]["scripts"]), n,
                                                    "ok" if not probs else "PROBLEMS"))
        for t in probs:
            print("    " + t)
        for t in BM.notes(ex["program"]):
            print("    note: " + t)
        bad += bool(probs)
    if "--desk" in argv:
        bad += desk(only, examples)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
