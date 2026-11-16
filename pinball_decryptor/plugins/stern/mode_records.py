"""Records of your own on the game's high-score table (PAD-1280).

Peanutsfr: "create custom High Score entries in the HSTD section, including for the machine's built-in modes" - a
name, a description, the mode it belongs to, and whether it is a score or a count of shots or objectives, which ones
the owner picks. Each record here is one such entry. On the card (``records.cfg`` beside the runtime,
pad_mode_runtime.c "records of the owner's own") the runtime counts each player's value through the game and, at
the game's end, runs the game's own initials entry for a player who beat the record, under the record's name, and
shows its champion in the attract mode after the game's own champions (the way a mode's challenge champion is kept:
PAD-640/663, in ``/dump/pad_challenge_scores``). The game's own high scores and champions are never touched.

A record (one dict, kept in the project's sidecar under :data:`STAGED_KEY`)::

    key          "r1", "r2", ... (stable: an edit keeps it)
    name         the page's title: capitals, at most MAX_WORDS
    description  the owner's note about it (the app shows it; the machine does not)
    mode         "" the whole game | "game:<id>" one of the game's own modes | "own:<NAME>" one of the project's
    measure      "points" | "count"
    counts       ["audit:<id>" | "champion:<cat>", ...]   (a count record's; [] for points)
    per          "run" the best single play of its mode | "game" all of it in one game ("game" when mode is "")

The choices a card offers (:func:`choices`) are read off its game program and its port: the game's modes the
runtime can see running (a C++ title's ``block_obj_<id>``, whose ACTIVE virtual it asks), and what can be counted -
the framework's audits (every shot audit, each mode's STARTED / COMPLETED, ball saves, ...) and the game's own
champion counts (Godzilla's JET FIGHTER, GODZILLA POWERUP), as co-op awards read them (:mod:`.coop_play`).
"""

import re

STAGED_KEY = "mode_records"
CFG_NAME = "records.cfg"
#: the most records a card carries (the runtime's REC_MAX)
MAX_RECORDS = 12
#: the longest name a champion page's title takes (the runtime's chg title, as co-op awards)
MAX_WORDS = 27
#: the most counts one record adds up (the runtime's REC_IDS)
MAX_IDS = 32
#: of which champion counts at most (the runtime's REC_CATS)
MAX_CATS = 8
#: the longest description kept
MAX_DESC = 160
#: the longest own mode name the runtime compares (its pm_mode names)
MAX_OWN = 39

MEASURES = ("points", "count")
PERS = ("run", "game")

#: why a card cannot carry records
NO_TITLE = "The app cannot tell which game this project is for, so it cannot add records to its high scores."
NO_PORT = ("The app does not know where %s files its high scores yet, so it cannot add records of your own to "
           "them.")
NO_CARD = ("The app reads the game's modes and what it counts off the card, and this project's card image is not on "
           "this computer.")

#: what the dialog says a record is
HOW = ("Records of your own go on the game's high-score table: after a game, a player who beat one enters their "
       "initials for it the way they do for the game's own champions, and the attract mode shows its champion after "
       "the game's. Each counts points, or the shots and goals you tick, during one of the game's modes, one of "
       "yours, or the whole game. The game's own high scores are not changed.")

#: the port names a card needs for records (pad_mode_runtime.c rec_arm and the champion framework's, PAD-663)
PORT_SITES = ("challenge_scores", "challenge_score_entry")
PORT_DATA = ("challenge_scores_table",)
PORT_VALUES = ("challenge_scores_cat",)


class RecordError(ValueError):
    """A record that cannot be kept as asked; the message says why."""


# ---- the project's records ------------------------------------------------------------------------
def load(project):
    """The project's records, each cleaned (:func:`clean`), in the order they were made. [] when none."""
    if not project:
        return []
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return []
    out = []
    for r in raw if isinstance(raw, list) else []:
        try:
            out.append(clean(r))
        except RecordError:
            continue
    return out


def _store(project, recs):
    from ...core import staged_changes
    data = staged_changes.load(project)
    if recs:
        data[STAGED_KEY] = recs
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)


def save_record(project, key, rec):
    """Keep *rec* (a dict as above) as record *key*, or as a new one when *key* is empty. Returns its key. Raises
    :class:`RecordError` when it cannot be kept (no name, a name another record has, no counts ticked, too many)."""
    recs = load(project)
    rec = clean(dict(rec or {}, key=key or ""))
    for r in recs:
        if r["key"] != key and r["name"] == rec["name"]:
            raise RecordError("Another record is called %s: each needs a name of its own (the machine keeps its "
                              "champion by its name)." % rec["name"])
    if key and any(r["key"] == key for r in recs):
        recs = [rec if r["key"] == key else r for r in recs]
    else:
        if len(recs) >= MAX_RECORDS:
            raise RecordError("A card takes at most %d records of your own." % MAX_RECORDS)
        used = {r["key"] for r in recs}
        n = 1
        while "r%d" % n in used:
            n += 1
        rec["key"] = "r%d" % n
        recs.append(rec)
    _store(project, recs)
    return rec["key"]


def delete_record(project, key):
    """Take record *key* out of the project. Returns the record taken, or None when there was none."""
    recs = load(project)
    gone = next((r for r in recs if r["key"] == key), None)
    if gone is not None:
        _store(project, [r for r in recs if r["key"] != key])
    return gone


def clean_name(name):
    """A record's name as its page shows it: capitals, one space between words, at most :data:`MAX_WORDS`, only
    what the game's fonts draw (letters, digits, spaces and . , ' - ! ? # & /)."""
    s = " ".join(re.sub(r"[^A-Z0-9 .,'\-!?#&/]", "", str(name or "").upper()).split())
    return s[:MAX_WORDS].strip()


def clean(rec):
    """*rec* with every field as the card takes it. Raises :class:`RecordError` for a record that cannot be."""
    name = clean_name(rec.get("name"))
    if not name:
        raise RecordError("A record needs a name: the title its champion shows under.")
    mode = str(rec.get("mode") or "").strip()
    if mode.startswith("game:"):
        if not mode[5:].isdigit():
            raise RecordError("That is not one of the game's modes.")
        mode = "game:%d" % int(mode[5:])
    elif mode.startswith("own:"):
        own = " ".join(mode[4:].split())[:MAX_OWN]
        if not own:
            raise RecordError("That is not one of your modes.")
        mode = "own:" + own
    elif mode:
        raise RecordError("That is not a mode a record can count in.")
    measure = rec.get("measure") if rec.get("measure") in MEASURES else "points"
    counts = []
    for c in rec.get("counts") or []:
        c = str(c)
        kind, _, n = c.partition(":")
        if kind in ("audit", "champion") and n.isdigit() and c not in counts:
            counts.append("%s:%d" % (kind, int(n)))
    if measure == "count":
        if not counts:
            raise RecordError("Tick at least one shot or goal for a record that counts them.")
        if len(counts) > MAX_IDS:
            raise RecordError("A record adds up at most %d counts." % MAX_IDS)
        if sum(1 for c in counts if c.startswith("champion:")) > MAX_CATS:
            raise RecordError("A record adds up at most %d of the game's own counts." % MAX_CATS)
    else:
        counts = []
    per = rec.get("per") if rec.get("per") in PERS else "run"
    if not mode:
        per = "game"
    desc = " ".join(str(rec.get("description") or "").split())[:MAX_DESC]
    return {"key": str(rec.get("key") or ""), "name": name, "description": desc, "mode": mode,
            "measure": measure, "counts": counts, "per": per}


# ---- what a card offers ---------------------------------------------------------------------------
def title_refusal(prof):
    """Why *prof*'s card cannot carry records, or ``""``."""
    if prof is None:
        return NO_TITLE
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_PORT % prof.label
    return "" if port_ok(port) else NO_PORT % prof.label


def port_ok(port):
    """1 when the port names what the runtime files a record with (the champion framework's names, PAD-663) and
    sees the game's end with."""
    return (all(s in port.get("site", {}) for s in PORT_SITES)
            and all(d in port.get("data", {}) for d in PORT_DATA)
            and all((port.get("value", {}).get(v) or 0) > 0 for v in PORT_VALUES))


def active_slot_known(port):
    """1 when the port says which virtual tells that one of the game's modes runs (``value mode_slot_active`` /
    ``stock_slot_active``, or ``site stock_any_running`` for the runtime to read it off)."""
    values, sites = port.get("value", {}), port.get("site", {})
    return (values.get("mode_slot_active", -1) >= 0 or values.get("stock_slot_active", -1) >= 0
            or "stock_any_running" in sites)


def game_modes(game_elf, port):
    """``[(id, name, object)]``: the game's own modes a record can count in, multiballs too - every mode the stock
    scanner finds in a C++ rule title's program (its id, readable name and static object, whose ACTIVE virtual the
    runtime asks), when the port says which virtual that is (:func:`active_slot_known`); in id order. [] for a
    plain-C title (no C++ mode manager) or a program the scanner cannot read."""
    if not active_slot_known(port):
        return []
    from . import stock_scan as S
    from . import stock_scan_cpp as C
    try:
        prog = S.Program(game_elf)
        model = S.class_model(prog)
        if not C.family(model):
            return []
        reading = C.read(prog, model)
    except Exception:                                   # noqa: BLE001 - not a C++ rule title: no game modes
        return []
    out, seen = [], set()
    for m in sorted(reading.modes, key=lambda m: m.id):
        if m.obj and m.obj not in seen and 0 <= m.id < 100000:
            seen.add(m.obj)
            out.append((int(m.id), (m.name or m.cls or "mode %d" % m.id).strip(), int(m.obj)))
    return out


def _words(s):
    """AUD_SHOT_LEFT_RAMP's tail as words: Left Ramp."""
    out = []
    for w in s.split("_"):
        if not w:
            continue
        out.append(w if w in ("VUK", "KOTM", "TOTC", "MB", "X") or len(w) <= 2 and not w.isalpha() else w.title())
    return " ".join(out)


#: the framework audits a record may count beside the shots and the modes: (name, words)
OTHER_AUDITS = (("AUD_TOTAL_BALLS_SAVED", "Balls saved"), ("AUD_TOTAL_EXTRA_BALLS", "Extra balls"),
                ("AUD_MYSTERY_AWARDS", "Mystery awards"), ("AUD_LEFT_SLINGSHOT", "Left slingshot"),
                ("AUD_RIGHT_SLINGSHOT", "Right slingshot"), ("AUD_TOTAL_TILT_WARNINGS", "Tilt warnings"),
                ("AUD_TOTAL_SPECIALS", "Specials"), ("AUD_TOTAL_BALL_SEARCHES", "Ball searches"))


def count_choices(game_elf):
    """``[{"key", "label", "group"}]``: what a record of the card's game can count, grouped as the dialog lists them -
    Shots (each AUD_SHOT_* audit), Modes (each mode's started / completed audit), Other (ball saves, extra balls,
    ...), and The game's own counts (its champion categories that count play)."""
    from . import coop_play as CP
    from . import stock_scan as S
    from .mode_framework import audit_add
    from .portchallenge import Elf
    out = []
    ids = CP._audit_ids(S.Program(game_elf)) if audit_add(Elf(game_elf)) else {}
    by_id = sorted(ids.items(), key=lambda kv: kv[1])
    for n, i in by_id:
        if n.startswith("AUD_SHOT_"):
            tail = n[len("AUD_SHOT_"):]
            label = (_words(tail[:-len("_SPIN")]) + " spins" if tail.endswith("_SPIN")
                     else _words(tail[:-len("_HIT")]) + " hits" if tail.endswith("_HIT")
                     else _words(tail))
            out.append({"key": "audit:%d" % i, "label": label, "group": "Shots"})
    for n, i in by_id:
        m = re.match(r"AUD_MODE_(.+)_(STARTED|COMPLETED|COMPLETES|COMPLETE)$", n)
        if m:
            out.append({"key": "audit:%d" % i, "group": "Modes",
                        "label": "%s %s" % (_words(m.group(1)), "started" if m.group(2) == "STARTED" else "won")})
    for n, words in OTHER_AUDITS:
        if n in ids:
            out.append({"key": "audit:%d" % ids[n], "label": words, "group": "Other"})
    for cat, name in CP._champions(game_elf):
        words = name[:-len(" CHAMPION")] if name.endswith(" CHAMPION") else name
        out.append({"key": "champion:%d" % cat, "label": words.title().replace("Vs.", "vs."),
                    "group": "The game's own counts"})
    return out


def choices(game_elf, port):
    """Everything the dialog offers for this card: ``{"modes": [{"value", "label"}], "counts": [...]}`` (the game's
    modes as ``game:<id>``; the project's own are the tab's). PAD-1327: a Spike 3 card's 64-bit program offers neither
    yet (its audits, champion counts and mode objects are read off 32-bit code): its records count points, in the
    whole game or in a mode of the project's own."""
    if bytes(game_elf[:5]) == b"\x7fELF\x02":
        return {"modes": [], "counts": []}
    return {"modes": [{"value": "game:%d" % i, "label": n} for i, n, _o in game_modes(game_elf, port)],
            "counts": count_choices(game_elf)}


def project_choices(project):
    """``(why, choices)`` for the Modes tab: :func:`choices` of the project's card, cached per card; *why* says why
    there are none (no card here, a card whose high scores the app cannot reach), "" when there are."""
    import hashlib
    import json
    import os
    from . import mode_project as MP
    from . import title_reader as TR
    prof = project_title(project)
    why = title_refusal(prof)
    if why:
        return why, {"modes": [], "counts": []}
    got = MP.project_card(project) if project else None
    card = getattr(got, "image", "") if got is not None else ""
    if not card or not os.path.isfile(card):
        return NO_CARD, {"modes": [], "counts": []}
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_PORT % prof.label, {"modes": [], "counts": []}
    key = "%s|%d|%d|%s" % (card, os.path.getsize(card), int(os.path.getmtime(card)), prof.port)
    cache = os.path.join(TR.cache_dir("mode_records"), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")
    try:
        with open(cache, encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("key") == key and raw.get("v") == 1:
            return "", raw["choices"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        got = choices(TR.game_program(card)[2], port)
    except Exception as e:                              # noqa: BLE001 - an unreadable card: say so
        return "The game program could not be read from the card: %s" % e, {"modes": [], "counts": []}
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "key": key, "choices": got}, f)
    except OSError:
        pass
    return "", got


def project_title(project, probe=False):
    """The profile of the card *project* was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe) if project else None


# ---- the card -------------------------------------------------------------------------------------
def describe(rec, mode_names=None):
    """One line saying what *rec* counts, for the dialog's list and the build's log: "points in King of the Monsters
    (its best play)", "Left Ramp and Right Ramp in a whole game"."""
    mode = rec["mode"]
    where = ("a whole game" if not mode
             else (mode_names or {}).get(mode) or (mode[4:] if mode.startswith("own:") else "the game's mode %s"
                                                   % mode[5:]))
    what = "points" if rec["measure"] == "points" else "%d count%s" % (len(rec["counts"]),
                                                                       "" if len(rec["counts"]) == 1 else "s")
    tail = "" if not mode else " (its best play)" if rec["per"] == "run" else " (all of it in one game)"
    return "%s in %s%s" % (what, where, tail)


def cfg_text(recs, modes=None):
    """``records.cfg`` for *recs* (cleaned): one ``rec`` line each, an ``own`` line after one counting in a mode of
    the project's::

        rec <n> <points|count> <run|game> <-|g<id>:0x<object>|own> <-|a<id>,c<cat>,...> <NAME>
        own <n> <the mode's name>

    *modes* (:func:`game_modes` of the card being written) gives a game's mode its object; a record counting in a
    mode the card's program has not is left out (said in the file's comment). Raises :class:`RecordError` when no
    record is left."""
    lines = ["# PAD-1280: records of the owner's own on the game's high-score table (pad_mode_runtime.c)"]
    objs = {i: o for i, _n, o in (modes or ())}
    n = 0
    for r in recs[:MAX_RECORDS]:
        mode = r["mode"]
        if mode.startswith("game:") and int(mode[5:]) not in objs:
            lines.append("# %s left out: this card's game program has no mode %s the runtime can see running"
                         % (r["name"], mode[5:]))
            continue
        ids = ",".join(("a" if c.startswith("audit:") else "c") + c.split(":", 1)[1] for c in r["counts"]) or "-"
        where = ("-" if not mode else "own" if mode.startswith("own:")
                 else "g%s:0x%x" % (mode[5:], objs[int(mode[5:])]))
        n += 1
        lines.append("rec %d %s %s %s %s %s" % (n, r["measure"], r["per"], where, ids, r["name"]))
        if mode.startswith("own:"):
            lines.append("own %d %s" % (n, mode[4:]))
    if not n:
        raise RecordError("No record can go on this card.")
    return "\n".join(lines) + "\n"
