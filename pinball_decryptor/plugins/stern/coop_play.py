"""Co-op play on a Spike 2 card (PAD-1017; sdk/MODE_SDK.md "Co-op play", docs/plans/pad1017_coop.md).

daveyvandy: co-op on the games that have none, 2-4 players sharing progress, with high score boards of its own. The
game plays one player, whose progress and score are the team's, and the mode runtime takes the teammates in turn, a
ball each (pad_mode_runtime.c "co-op play"; the port lines are portcoop.py's). A teammate joins when Start is pressed
with the right flipper button held; a plain Start adds a competing player as the game always has.

The Modes tab's tick (the project sidecar's ``coop_play: {"on": true}``) puts ``coop.cfg`` beside the runtime on the
card: ``coop on`` and the right flipper button's switch id, read off the card's own game program.

Round 2 (DoomWalrus666, David): ``coop_play: {"on": true, "menu": true}`` also gives the game's own service menu a
CO-OP PLAY row (Off/On like the game's CUSTOM MESSAGE, stored 0 and 1; :mod:`.menu_settings`, on a spare setting), and ``coop.cfg`` names its live value
(``setting <address>``): teammates join only while it says On, and on a card of co-op and nothing else (no mode, no
attract item) the Insider Connected gate holds back only while it says On - Off, the card is the game's own on Insider
Connected."""
from . import sound_modes as _SMo

#: the project sidecar's key: ``{"on": true}``
STAGED_KEY = "coop_play"
#: the runtime's file beside it on the card
CFG_NAME = "coop.cfg"
#: the port lines the runtime needs (portcoop.py)
PORT_SITES = ("coop_player_change", "coop_add_player")
PORT_DATA = ("coop_player", "coop_players")
#: the titles with co-op of their own: they keep theirs (TMNT, Venom, Mandalorian, D&D, Jaws, Jurassic Park, King
#: Kong, Bond 60th), by their title keys' stems
OWN_COOP = ("turtles_", "venom_", "mando_", "dungeons_and_dragons_", "jaws_", "jurassic_park_le", "jurassic_park_pro",
            "king_kong_", "james_bond_60th_")

NO_TITLE = ("The app cannot tell which game this project is for, so it cannot give it co-op play.")
OWN = "%s has co-op play of its own, so the app does not add another."
NO_PORT = ("The app does not know where %s keeps its players yet, so it cannot give it co-op play.")
NO_BUTTON = "The game program names no right flipper button, so a teammate could not join."
#: round 2: the service menu's row (menu_settings.COOP_PLAY): its values, and its help line in the game's own menu
MENU_VALUES = 2
#: (David) the row shows Off/On; the help says what On costs first (63 characters: the spare help lines' room)
MENU_HELP = "On disables most Insider Connected features; R flip+Start joins"
#: how a teammate joins, for the tab and the log
HOW = ("hold the right flipper button and press Start to add a teammate (2-4 players share one game); "
       "a plain Start adds a competing player as always")


class CoopError(ValueError):
    """The card's game program cannot take co-op play; the message says why."""


def load(project):
    """Whether the project's sidecar asks for co-op play."""
    if not project:
        return False
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: no
        return False
    return bool(isinstance(raw, dict) and raw.get("on"))


def menu_asked(project):
    """Round 2: whether co-op is switched in the service menu (CO-OP PLAY) rather than always on."""
    if not load(project):
        return False
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: no
        return False
    return bool(isinstance(raw, dict) and raw.get("menu"))


def save(project, on, menu=None):
    """Ask (or stop asking) for co-op play; *menu* (round 2) True/False sets whether it is switched in the service
    menu, None keeps it. Returns what ``on`` was before. PAD-1028: the award choices stay, for when it is ticked
    again."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    raw = data.get(STAGED_KEY) if isinstance(data.get(STAGED_KEY), dict) else {}
    was = bool(raw.get("on"))
    keep = {k: v for k, v in raw.items() if k == "awards"}
    if on and (raw.get("menu") if menu is None else menu):
        keep["menu"] = True
    if on or keep:
        data[STAGED_KEY] = dict(keep, on=bool(on))
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return was


def title_refusal(prof):
    """Why ``prof``'s title cannot have co-op play, or ``""``."""
    if prof is None:
        return NO_TITLE
    key = _SMo.title_key(prof)
    if key.startswith(OWN_COOP):
        return OWN % prof.label
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_PORT % prof.label
    if not all(s in port.get("site", {}) for s in PORT_SITES) or not all(d in port.get("data", {}) for d in PORT_DATA):
        return NO_PORT % prof.label
    return ""


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def cfg_text(game_elf, awards=None, setting=0, only=False):
    """``coop.cfg`` for the card whose game program is *game_elf* (bytes): co-op on, the right flipper button,
    (round 2) *setting*, the CO-OP PLAY row's live value, when the service menu switches it; *only* when the card
    carries no modes (then the Insider Connected gate holds back only while CO-OP PLAY says On), and (PAD-1028) an
    ``award`` line for each award ticked (*awards*: the project's choices, :func:`load_awards`)."""
    buttons = _SMo.flipper_buttons(game_elf)
    if len(buttons) != 2:
        raise CoopError(NO_BUTTON)
    return ("coop on\nbutton %d\n" % buttons[1] + ("setting 0x%08x\n" % setting if setting else "")
            + ("only\n" if setting and only else "")
            + "".join(line + "\n" for line in award_lines(game_elf, awards)))

# ---- PAD-1028: a co-op game's awards -----------------------------------------------------------------------------
# DoomWalrus666: "At the end of a co-op mode game, could we show different awards for the players? Player that destroyed
# the most jets, player that used the most ball save, player that collected the most power-ups ..."; David: "on rails
# with the awards ahead of time ... a generic skinning of them so they look good in all games ... customizable per
# game". The game plays one player for the team; the runtime gives each teammate what the team's counts did during
# their turns (pad_mode_runtime.c "a co-op game's awards") and shows each award on a champion page of the game's own in
# the attract mode after the game: its words, "PLAYER 2", the count. What can be counted is read off the card's own
# program: the points, the longest ball, the framework's audits (every Spike 2 build names them the same) and the
# game's own champion categories (Godzilla's JET FIGHTER CHAMPION counts the jet fighters destroyed).

#: the most awards a card carries (the runtime's COOP_AWARDS)
MAX_AWARDS = 16
#: the longest words a champion page's title takes (the runtime's chg_title_max)
MAX_WORDS = 27
#: the most audits one award adds up (the runtime's COOP_AWARD_IDS)
MAX_IDS = 48


def _ramp(n):
    return n.startswith("AUD_SHOT_") and "RAMP" in n


#: the awards counted from the framework's audits: (key, words, on by default, what it counts, the audit names' test;
#: None: the game's mode audits)
AUDIT_AWARDS = (
    ("balls_saved", "MOST BALL SAVES", True, "balls a ball save gave back", lambda n: n == "AUD_TOTAL_BALLS_SAVED"),
    ("modes_started", "MOST MODES STARTED", True, "the game's modes started", None),
    ("extra_balls", "MOST EXTRA BALLS", True, "extra balls", lambda n: n == "AUD_TOTAL_EXTRA_BALLS"),
    ("ramps", "MOST RAMPS", True, "ramp shots", _ramp),
    ("modes_won", "MOST MODES WON", False, "the game's modes completed", None),
    ("spins", "MOST SPINNER SPINS", False, "spinner spins",
     lambda n: n.startswith("AUD_SHOT_") and n.endswith("SPINNER_SPIN")),
    ("pops", "MOST POP BUMPERS", False, "pop bumper hits",
     lambda n: n.startswith("AUD_SHOT_") and "POP_BUMPER" in n),
    ("slings", "MOST SLINGSHOTS", False, "slingshot hits", lambda n: n in ("AUD_LEFT_SLINGSHOT", "AUD_RIGHT_SLINGSHOT")),
    ("mystery", "MOST MYSTERIES", False, "mystery awards", lambda n: n == "AUD_MYSTERY_AWARDS"),
    ("tilt_warnings", "MOST TILT WARNINGS", False, "tilt warnings", lambda n: n == "AUD_TOTAL_TILT_WARNINGS"),
)
#: the runtime's own: (key, words, on by default, what it counts)
OWN_AWARDS = (("score", "MOST POINTS", True, "points scored in their balls, bonus included"),
              ("time", "LONGEST BALL (SEC)", True, "their longest ball, in seconds"))
#: champion categories that count no play: the score boards, the challenge games', co-op boards, times
_NOT_AWARDS = ("HIGH SCORE", "CHALLENGE", "COOP", "CO-OP", "TEAM HIGH", "FASTEST", "CODE CHAMPION", "GRAND CHAMPION")


def _audit_ids(prog):
    from . import stock_scan_c as SC
    return {n: i for i, n in SC.audit_ids(prog)[1].items() if n}


def _mode_audits(ids, completed):
    """The ids of the game's mode audits: each mode's STARTED one, or with *completed* its COMPLETED one."""
    from . import stock_scan_c as SC
    out = []
    for _key, name in SC.mode_audits(sorted(ids, key=ids.get)):
        if name.endswith(("_SHOT", "_SHOTS")):           # AUD_MODE_MONSTER_RAMPAGE_SHOT: a shot in one, not a start
            continue
        if completed:
            stem = name.rsplit("_", 1)[0]
            name = next((stem + s for s in ("_COMPLETED", "_COMPLETES", "_COMPLETE") if stem + s in ids), None)
        if name in ids:
            out.append(ids[name])
    return out


def _champions(game_elf):
    """``[(category, name)]``: the game's own champion categories that count play (Godzilla: JET FIGHTER CHAMPION,
    SAUCER CHAMPION, GODZILLA POWERUP CHAMPION, ...), each name once."""
    from .portchallenge import Elf, _scores_fn
    e = Elf(game_elf)
    got = _scores_fn(e)
    if not got:
        return []
    _top, _ents, _cats, count_at, table = got
    out, seen = [], set()
    for c in range(2, min(e.word(count_at) or 0, 64)):
        at = table + 36 * c
        tl = e.word(at + 24) if e.off(at + 24) is not None else 0
        name = e.cstr(e.word(tl)) if tl and e.off(tl) is not None else None
        get = e.word(at + 4)
        if not name or not name.isprintable() or any(w in name for w in _NOT_AWARDS) or name in seen \
                or not get or e.off(get) is None:
            continue
        seen.add(name)
        out.append((c, name.replace("/'", "'")))
    return out


def award_choices(game_elf):
    """Every award the card's game program can count, in the order the Modes tab lists them:
    ``[{"key", "words", "on", "counts", "kind", "ids"}]`` (``on``: ticked by default; ``kind``: score, time, audit,
    champion; ``ids``: the audit ids or the champion category, for coop.cfg)."""
    from . import stock_scan as S
    from .mode_framework import audit_add
    from .portchallenge import Elf
    out = [{"key": k, "words": w, "on": on, "counts": c, "kind": k, "ids": []} for k, w, on, c in OWN_AWARDS]
    ids = _audit_ids(S.Program(game_elf)) if audit_add(Elf(game_elf)) else {}
    for key, words, on, counts, test in AUDIT_AWARDS:
        got = (_mode_audits(ids, key == "modes_won") if test is None
               else [i for n, i in sorted(ids.items(), key=lambda kv: kv[1]) if test(n)])
        if got:
            out.append({"key": "audit:" + key, "words": words, "on": on, "counts": counts, "kind": "audit",
                        "ids": got})
    for cat, name in _champions(game_elf):
        out.append({"key": "champion:" + name, "words": short_words(name), "on": False,
                    "counts": "the game's own %s count" % name.title(), "kind": "champion", "ids": [cat]})
    return out


def load_awards(project):
    """The project's award choices: ``{key: {"on": bool, "words": str}}``, those changed from the defaults."""
    if not project:
        return {}
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: the defaults
        return {}
    got = raw.get("awards") if isinstance(raw, dict) else None
    return {k: v for k, v in got.items() if isinstance(v, dict)} if isinstance(got, dict) else {}


def save_award(project, key, on=None, words=None):
    """Tick, untick or rename one award; with *key* None every award as the game's defaults again."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    raw = dict(data.get(STAGED_KEY)) if isinstance(data.get(STAGED_KEY), dict) else {"on": False}
    chosen = dict(raw.get("awards") or {}) if key is not None else {}
    if key is not None:
        cur = dict(chosen.get(key) or {})
        if on is not None:
            cur["on"] = bool(on)
        if words is not None:
            cur["words"] = clean_words(words)
        chosen[key] = cur
    if chosen:
        raw["awards"] = chosen
    else:
        raw.pop("awards", None)
    data[STAGED_KEY] = raw
    staged_changes.save(project, data)


def clean_words(words):
    """An award's words as a page shows them: capitals, one space between words, at most :data:`MAX_WORDS`."""
    return " ".join(str(words or "").upper().split())[:MAX_WORDS]


def short_words(name):
    """A champion category's name as an award's words: whole when it fits, else without " CHAMPION", else cut at the
    last whole word that fits (MECHAGODZILLA MULTIBALL CHAMPION -> MECHAGODZILLA MULTIBALL)."""
    name = " ".join(name.upper().split())
    if len(name) <= MAX_WORDS:
        return name
    if name.endswith(" CHAMPION"):
        name = name[:-len(" CHAMPION")]
    while len(name) > MAX_WORDS and " " in name:
        name = name.rsplit(" ", 1)[0].rstrip(",.")
    return name[:MAX_WORDS]


def awards(game_elf, chosen=None):
    """:func:`award_choices` with the project's *chosen* (:func:`load_awards`) applied: each one's ``on`` and
    ``words`` (and ``stock_words``, the game's default)."""
    return _apply(award_choices(game_elf), chosen)


def award_lines(game_elf, chosen=None):
    """coop.cfg's ``award`` lines: ``award <kind> <ids, or -> <words>`` for each award ticked, up to
    :data:`MAX_AWARDS`."""
    out = []
    for a in awards(game_elf, chosen):
        if a["on"] and a["words"]:
            out.append("award %s %s %s" % (a["kind"], ",".join(str(i) for i in a["ids"][:MAX_IDS]) or "-", a["words"]))
    return out[:MAX_AWARDS]


#: why the Modes tab cannot list a project's awards
NO_CARD = ("The app reads the awards a game can count off its card, and this project's card image is not on this "
           "computer. The awards ticked by default go on the card at Write.")


def project_awards(project):
    """``(why, awards)`` for the Modes tab: the project's awards (:func:`awards`, its choices applied) read off its
    card's game program, cached per card; ``why`` says why there are none ("" when there are)."""
    import hashlib
    import json
    import os
    from . import mode_project as MP
    from . import title_reader as TR
    got = MP.project_card(project) if project else None
    card = getattr(got, "image", "") if got is not None else ""
    if not card or not os.path.isfile(card):
        return NO_CARD, []
    key = "%s|%d|%d" % (card, os.path.getsize(card), int(os.path.getmtime(card)))
    cache = os.path.join(TR.cache_dir("coop_awards"), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")
    choices = None
    try:
        with open(cache, encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("key") == key and raw.get("v") == 1:
            choices = raw["choices"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if choices is None:
        try:
            choices = award_choices(TR.game_program(card)[2])
        except Exception as e:                          # noqa: BLE001 - an unreadable card: say so
            return "The game program could not be read from the card: %s" % e, []
        try:
            with open(cache, "w", encoding="utf-8") as f:
                json.dump({"v": 1, "key": key, "choices": choices}, f)
        except OSError:
            pass
    return "", _apply(choices, load_awards(project))


def _apply(choices, chosen):
    out = []
    for a in choices:
        c = (chosen or {}).get(a["key"]) or {}
        a = dict(a, stock_words=a["words"])
        if "on" in c:
            a["on"] = bool(c["on"])
        if c.get("words"):
            a["words"] = clean_words(c["words"])
        out.append(a)
    return out
