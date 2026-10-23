"""examples.py - the Godzilla blocks programs (PAD-658), the block compiler's test material (PAD-691: moved here from
the SDK's ``blocks_examples`` and block_modes.py, which the app never offered since PAD-675; nothing here ships).

One JSON file each in this folder: {"name", "slug", "order", "titles" (game_dir prefixes), "about", "based_on" (the C
example it was rebuilt from, tests/mode_examples/c/, or ""), "lost" [sentences], "program" (blocks.json; its clips,
sounds and music are files named after their cue: <cue>.mp4, <cue>.wav, music.wav), "recipe" (where each was cut from
in the films, kept as a record)}. ``make_examples.py`` beside them writes the files from their Python.
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402
from pinball_decryptor.plugins.stern.block_modes import (CALLOUT_ROLES, SLUG_RE, BlocksError, _int_ok,  # noqa: E402
                                                         card_checks, problems, save)


def examples_dir():
    return HERE


def _load_examples():
    out = []
    folder = examples_dir()
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(folder, n), "r", encoding="utf-8") as f:
                ex = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(ex, dict) and ex.get("name") and SLUG_RE.match(str(ex.get("slug") or "")) \
                and isinstance(ex.get("program"), dict):
            out.append(ex)
    out.sort(key=lambda e: (int(e.get("order", 999)), e["name"]))
    return out


EXAMPLES = _load_examples()


def example_names(game_dir=None):
    """The blocks examples' names, in the order the wizard lists them; with ``game_dir`` only the ones made for
    that title (its port's game directory, "godzilla_le" ...)."""
    return [e["name"] for e in EXAMPLES
            if game_dir is None or any(str(game_dir).startswith(t) for t in e.get("titles") or ())]


def example(name):
    for e in EXAMPLES:
        if e["name"] == name:
            return e
    return None


def example_films(ex):
    """The film keys an example's recipe cuts from, in the order first used."""
    out = []
    r = ex.get("recipe") or {}
    parts = [r.get("clip"), r.get("art"), r.get("music")] + list((r.get("calls") or {}).values())
    parts += list((r.get("beds") or {}).values()) + list((r.get("clips") or {}).values())
    for p in parts:
        if p and p.get("film") not in out:
            out.append(p["film"])
    return out


def without_media(program):
    """``program`` with none of its own clips, sounds or music: a clip block goes, a sound block becomes its
    fallback callout (or goes). What a blocks example plays until its films are found."""
    out = copy.deepcopy(program)
    out["clips"], out["sounds"], out["music"], out["beds"] = [], [], "", []

    def strip(stack):
        kept = []
        for b in stack or []:
            if not isinstance(b, dict):
                continue
            if b.get("op") in ("clip", "music"):
                continue
            if b.get("op") == "sound":
                fb = b.get("fallback")
                if fb in CALLOUT_ROLES:
                    kept.append({"op": "callout", "role": fb})
                elif _int_ok(fb, 1, 65535):
                    kept.append({"op": "callout", "id": int(fb)})
                continue
            if b.get("op") == "if":
                b = dict(b, then=strip(b.get("then")), **({"else": strip(b.get("else"))} if b.get("else") else {}))
            kept.append(b)
        return kept

    for s in out.get("scripts") or []:
        s["do"] = strip(s.get("do"))
    return out


def _rename_shots(stack, names):
    for b in stack or []:
        if not isinstance(b, dict):
            continue
        for key in ("shot",):
            if b.get(key) in names:
                b[key] = names[b[key]]
        for key in ("points", "value", "by", "seconds", "ms", "rate", "cond", "a", "b"):
            if isinstance(b.get(key), dict):
                _rename_shots([b[key]], names)
        if b.get("k") == "hits" and b.get("shot") in names:
            b["shot"] = names[b["shot"]]
        _rename_shots(b.get("then"), names)
        _rename_shots(b.get("else"), names)


def adapt(ex, profile):
    """Example ``ex``'s program for the card's title ``profile`` (PAD-658: Premium/LE and Pro get the same modes, with
    alternate rules where the Pro's layout and mechanisms differ).

    ``title_alt`` (``{game_dir prefix: {"shots": {name: name or None}, "shows": {name: name or None},
    "inserts": {name: name or None}, "words": {words: words}}}``) names the title's alternates: a shot it calls otherwise or replaces with
    another (Premium's "Shield ramp spinner" is a Pro's "Right spinner"; its "Shield target center" a Pro has not),
    the game's own light show it plays instead, the insert it lights instead. None takes the shot (its scripts and
    lights), show or insert out. ``title_shots`` (round 1's) is the same as ``title_alt``'s "shots". "words"
    (PAD-658) swaps whole strings the HUD shows (a line, an award, a counter's words), so a line names the shot the
    title has instead ("SHOOT THE CENTER SHIELD" -> "SHOOT THE MASER TARGET").

    Then what the card's game cannot do at all is left out, as a person would take the block away: turning the
    shield platform (a Pro's shields are fixed, facing the player), moving the building, holding a mechanism the
    game has not, a game light show or insert it has not. :func:`fits` says whether what is left builds."""
    program = copy.deepcopy(ex["program"])
    if profile is None:
        return program
    game_dir = str(getattr(profile, "game_dir", "") or "")
    alt = {"shots": {}, "shows": {}, "inserts": {}, "words": {}}
    for prefix, m in (ex.get("title_shots") or {}).items():
        if game_dir.startswith(prefix):
            alt["shots"].update(m)
    for prefix, a in (ex.get("title_alt") or {}).items():
        if game_dir.startswith(prefix):
            for k in alt:
                alt[k].update((a or {}).get(k) or {})
    card = card_checks(profile)
    shots = set(card.get("shots") or ())
    shows = set(card.get("game_shows") or ())
    inserts = set(card.get("inserts") or ())
    mechs = card.get("mechs") or {}
    gone_shots = {n for n, v in alt["shots"].items() if v is None}
    names = {n: v for n, v in alt["shots"].items() if v}

    def shot_ok(name):
        return name not in gone_shots

    words = alt["words"]

    def reword(b):
        for k in ("text", "sub", "label"):
            if isinstance(b.get(k), str) and b[k] in words:
                b[k] = words[b[k]]

    if words and isinstance(program.get("hud"), dict):
        h = program["hud"]
        if h.get("line") in words:
            h["line"] = words[h["line"]]
        for c in h.get("counters") or []:
            if isinstance(c, dict):
                reword(c)

    def keep(stack):
        out = []
        for b in stack or []:
            if not isinstance(b, dict):
                continue
            b = copy.deepcopy(b)
            op = b.get("op")
            if words and op in ("hud_text", "hud_award", "hud_counter"):
                reword(b)
            if op == "shield" and card.get("shield") is False:
                continue
            if op == "building" and card.get("building") is False:
                continue
            if op == "hold" and b.get("what") not in mechs:
                continue
            if op == "game_show":
                name = alt["shows"].get(b.get("name"), b.get("name"))
                if not name or (shows and name not in shows):
                    continue
                b["name"] = name
            if op in ("light_shot", "lights_off") and b.get("insert"):
                name = alt["inserts"].get(b["insert"], b["insert"])
                if not name or (inserts and name not in inserts):
                    continue
                b["insert"] = name
            if op in ("light_shot", "lights_off", "set_hits") and b.get("shot") and not shot_ok(b["shot"]):
                continue
            if op == "light_mode":
                if not shot_ok(b.get("shot")):
                    continue
                kept = [n for n in (alt["inserts"].get(x.strip(), x.strip())
                                    for x in str(b.get("insert") or "").split(",") if x.strip())
                        if n and (not inserts or n in inserts)]
                b["insert"] = ",".join(kept)
            if op == "if":
                b["then"] = keep(b.get("then"))
                if b.get("else"):
                    b["else"] = keep(b.get("else"))
            out.append(b)
        return out

    scripts = []
    for s in program.get("scripts") or []:
        hat = s.get("hat") or {}
        if hat.get("kind") == "shot" and not shot_ok(hat.get("shot")):
            continue
        if names:
            if hat.get("shot") in names:
                hat["shot"] = names[hat["shot"]]
            _rename_shots(s.get("do"), names)
        s["do"] = keep(s.get("do"))
        scripts.append(s)
    program["scripts"] = scripts
    return program


def fits(ex, profile):
    """Does example ``ex`` build on ``profile``'s card once adapted (the wizard offers only the ones that do)?"""
    try:
        return not problems(adapt(ex, profile), **card_checks(profile))
    except Exception:                                   # noqa: BLE001 - an example that cannot be read is not offered
        return False


def add_example(project, name, profile=None):
    """Put example ``name`` in the project as ``modes/<slug>/``: its blocks (:func:`adapt`-ed to ``profile``, the
    card's title, when given) and the C they make, with none of its own media (:func:`without_media`: nothing is cut
    from the films any more). Returns the slug. Refuses a folder that is already there."""
    ex = example(name)
    if ex is None:
        raise BlocksError("there is no blocks example called %s" % name)
    if not project or not os.path.isdir(project):
        raise BlocksError(MP.NO_PROJECT_HELP)
    slug = ex["slug"]
    folder = MP.mode_folder(project, slug)
    if os.path.exists(folder):
        raise BlocksError("%s is already in this project (modes/%s)." % (ex["name"], slug))
    os.makedirs(folder)
    save(project, slug, without_media(adapt(ex, profile)))
    return slug
