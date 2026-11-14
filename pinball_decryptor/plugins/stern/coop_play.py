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
Connected.

PAD-1031: ``coop_play: {"characters": ...}`` gives the team characters to pick from (the pick, their abilities and
their select cards: the second half of this module).

PAD-1042 (DoomWalrus666): the CO-OP PLAY row has a third value, Team 2v2 (stored 0 Off, 1 Co-op, 2 Team 2v2, shown as
those numbers with the names in its help line; an Off/On row's 0 and 1 keep their meaning). Set to 2, the game's start menu
offers TEAM PLAY 2 VS 2 and one Start adds all four players, as on Stern's own team games (PAD-1052: before it each
Start in the first ball added the next; a plain Start is still a one-player game): players 1 and 3 are
one team, 2 and 4 the other, each team with its own score and its own progress (the game plays two players, a team
each) and the turns alternating the teams, P1 P2 P3 P4 (pad_mode_runtime.c "TEAM 2V2"). The characters' pick works as
in co-op: each player picks at their first ball, no two the same.

PAD-1065 (DoomWalrus666): Co-op, Team 2v2 and Team 2v1 without the characters' abilities. CO-OP PLAY 4, 5 and 6 are
those games Classic (1, 2 and 3 are now called Enhanced): the players still pick a character, but none has an
ability; the pick shows each card with a patch over its ability badge that says NO SPECIAL ABILITY
(:func:`classic_patch`).

PAD-1073 (DoomWalrus666: "the service menu options to simply be Co-op/Team: Off, Classic, Enhanced"): CO-OP PLAY is
0 Off, 1 Classic, 2 Enhanced, and the game is picked on the start menu alone: at 1 or 2 it offers CO-OP PLAY, TEAM
PLAY 2 VS 2 and TEAM PLAY 2 VS 1 all three (pad_mode_runtime.c "PAD-1073"; a store an older row left reads 3 as
Enhanced, 4-6 as Classic)."""
import re
import struct

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
#: round 2: the service menu's row (menu_settings.COOP_PLAY): its values, and its help line in the game's own menu.
#: PAD-1042: four, 0 Off, 1 Co-op, 2 Team 2v2, 3 Team 2v1 (daveyvandy: "a designated option for 2V1"; the row shows
#: the number; Off/On had 0 and 1 and v1.360.0's row 0-2, so a pick is kept). PAD-1065: seven, 1-3 the Enhanced
#: games (the characters' abilities hold) and 4-6 the same games Classic (a pick, no abilities). PAD-1073: three,
#: 0 Off, 1 Classic, 2 Enhanced (DoomWalrus666); which game is the start menu's pick
MENU_VALUES = 3
MENU_OFF, MENU_CLASSIC, MENU_ENHANCED = 0, 1, 2
#: the help names the values and says what they cost (63 characters: the spare help lines' room)
MENU_HELP = "0 Off. 1 Classic. 2 Enhanced. Games on start menu. Insider off"
#: how a teammate joins, for the tab and the log
HOW = ("pick CO-OP PLAY on the start menu (both flipper buttons in attract) and each Start in the first ball adds "
       "a teammate, or hold the right flipper button and press Start to add one (2-4 players share one game); "
       "a plain Start adds a competing player as always; with characters, a player starting a game alone with the "
       "right flipper button held picks one")
#: PAD-1042: how a team game is played, for the tab and the log
TEAMS_HOW = ("pick TEAM PLAY 2 VS 2 on the start menu (both flipper buttons in attract) and one Start adds all "
             "four players: players 1 and 3 against players 2 and 4, each team with its own score and progress, the "
             "teams taking turns; TEAM PLAY 2 VS 1 is the same with three players, players 1 and 3 against player 2, "
             "who plays both of team 2's turns; TEAM PLAY 3 VS 1 (PAD-1224) is the four-player one with players 1, "
             "3 and 4 against player 2, who plays all three of team 2's turns")
#: PAD-1224: how ENHANCED STANDARD is played, for the tab and the log
STANDARD_HOW = ("at 2 (Enhanced) the start menu also offers ENHANCED STANDARD: the game's own game for up to four "
                "competing players, each Start in the first ball adding one, each with their own score and progress "
                "and nothing shared; each player picks a character at their first ball and its ability holds while "
                "they are up")
#: PAD-1065: what Classic is, for the tab and the log (PAD-1073: CO-OP PLAY 1)
CLASSIC_HOW = ("1 (Classic) plays co-op and the team games with no special abilities: the players still pick a "
               "character, but none of them has its ability; 2 (Enhanced) plays them with the abilities")


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
    again; PAD-1031: so do the characters."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    raw = data.get(STAGED_KEY) if isinstance(data.get(STAGED_KEY), dict) else {}
    was = bool(raw.get("on"))
    keep = {k: v for k, v in raw.items() if k in ("awards", "characters")}
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


def cfg_text(game_elf, awards=None, characters=None, sites=(), values=None, setting=0, only=False):
    """``coop.cfg`` for the card whose game program is *game_elf* (bytes): co-op on, the right flipper button,
    (round 2) *setting*, the CO-OP PLAY row's live value, when the service menu switches it; *only* when the card
    carries no modes (then the Insider Connected gate holds back only while CO-OP PLAY says On); (PAD-1028) an
    ``award`` line for each award ticked (*awards*: the project's choices, :func:`load_awards`); and (PAD-1031) the
    characters' lines (*characters*: :func:`load_characters`; *sites* / *values*: the port's site names and value
    lines)."""
    buttons = _SMo.flipper_buttons(game_elf)
    if len(buttons) != 2:
        raise CoopError(NO_BUTTON)
    return ("coop on\nbutton %d\n" % buttons[1] + ("setting 0x%08x\n" % setting if setting else "")
            + ("only\n" if setting and only else "")
            + "".join(line + "\n" for line in insider_lines(game_elf))
            + "".join(line + "\n" for line in award_lines(game_elf, awards))
            + "".join(line + "\n" for line in character_lines(game_elf, characters, sites, values)))


# ---- PAD-1108: the Insider Connected login of the teammate up ------------------------------------------------------
# DoomWalrus666 (3-player co-op): "achievements earned by player 2 and 3 were shown as earned by Player 1. Player 1
# username displayed on End of Ball Bonus for all 3 players. High score attributed only to Player 1". The game plays one
# player for the team and asks its user manager for player 1's login all game; the runtime swaps the login tables'
# entries so the teammate up has it (pad_mode_runtime.c "PAD-1108"), and refuses the game's achievement award while
# Insider Connected is held back. Both are read off the card's own program: every Spike 2 build measured has one of
# each, in the same shape (the users on all 54 newest builds, the award on 53: Star Wars ELG has no audit add found).

#: the manager's lookup: ldr ip, [r0, #A]; cmp r3, #1; ldr r0, [r0, #B]; movne r0, ip; b <table lookup>
_USERS_HEAD = (0xE590C000, 0xE3530001, 0xE5900000, 0x11A0000C)
#: the table lookup's words: sub r3, r1, #1; cmp r3, #3; add r1, r1, r1, lsl #2; add r0, r0, r1, lsl #2;
#: add r4, r0, #4 - player p's entry at table + 20p + 4 (the runtime's COOP_USER_ENTRY)
_TABLE_WORDS = (0xE2413001, 0xE3530003, 0xE0811101, 0xE0800101, 0xE2804004)


def _branch_to(e, k, link):
    w = e.words[k]
    if (w >> 24) != (0xEB if link else 0xEA):
        return None
    off = (w & 0xFFFFFF) << 2
    if off & 0x2000000:
        off -= 0x4000000
    return e.text_va + 4 * k + 8 + off


def users_lookup(e):
    """PAD-1267: the va of the user manager's lookup (``_USERS_HEAD``, the one function every read of a player's login
    goes through), or None when there is not exactly one. ``e``: a portchallenge.Elf."""
    w = e.words
    found = [e.text_va + 4 * k for k in range(len(w) - 5)
             if (w[k] & 0xFFFFF000) == _USERS_HEAD[0] and w[k + 1] == _USERS_HEAD[1]
             and (w[k + 2] & 0xFFFFF000) == _USERS_HEAD[2] and w[k + 3] == _USERS_HEAD[3]]
    return found[0] if len(found) == 1 else None


def insider_users(game_elf):
    """``(manager, A, B)`` - the game's user manager (a global) and the fields of its two login tables - or None."""
    from .portchallenge import Elf
    e = Elf(game_elf)
    w = e.words
    found = []
    for k in range(len(w) - 5):
        if (w[k] & 0xFFFFF000) != _USERS_HEAD[0] or w[k + 1] != _USERS_HEAD[1] \
                or (w[k + 2] & 0xFFFFF000) != _USERS_HEAD[2] or w[k + 3] != _USERS_HEAD[3]:
            continue
        to = _branch_to(e, k + 4, False)
        if to is None or not e.text_va <= to < e.text_va + 4 * (len(w) - 12):
            continue
        j = (to - e.text_va) // 4
        if w[j + 1] != _TABLE_WORDS[0] or w[j + 2] != _TABLE_WORDS[1] \
                or not all(x in w[j:j + 12] for x in _TABLE_WORDS[2:]):
            continue
        found.append((e.text_va + 4 * k, w[k] & 0xFFF, w[k + 2] & 0xFFF))
    if len(found) != 1:
        return None
    look, a, b = found[0]
    managers = set()
    for k in range(len(w)):
        if _branch_to(e, k, True) != look:
            continue
        lo = hi = None
        for j in range(k - 1, max(k - 8, 0), -1):                 # movw / movt r0 just before the call
            x = w[j]
            if lo is None and (x & 0xFFF0F000) == 0xE3000000:
                lo = ((x >> 4) & 0xF000) | (x & 0xFFF)
            if hi is None and (x & 0xFFF0F000) == 0xE3400000:
                hi = ((x >> 4) & 0xF000) | (x & 0xFFF)
        if lo is not None and hi is not None:
            managers.add(lo | hi << 16)
    if len(managers) != 1:
        return None
    return (managers.pop(), a, b)


def achievement_award(game_elf):
    """The game's achievement award (the one function counting AUD_CONNECTIVITY_ACHIEVEMENTS_GIVEN), or None."""
    from . import stock_scan as S, stock_scan_c as SC
    from .mode_framework import audit_add
    from .portchallenge import Elf
    e = Elf(game_elf)
    add = audit_add(e)
    if not add:
        return None
    ids = {n: i for i, n in SC.audit_ids(S.Program(game_elf))[1].items() if n}
    aid = ids.get("AUD_CONNECTIVITY_ACHIEVEMENTS_GIVEN")
    if aid is None or aid > 0xFF:
        return None
    w = e.words
    hits = [k for k in range(4, len(w)) if _branch_to(e, k, True) == add
            and (0xE3A00000 | aid) in w[k - 4:k] and 0xE3A01001 in w[k - 4:k]]
    if len(hits) != 1:
        return None
    k = hits[0]
    while k > 0 and not (w[k - 1] == 0xE12FFF1E or (w[k - 1] & 0xFFFF8000) == 0xE8BD8000):   # bx lr / pop {.., pc}
        k -= 1
    if w[k] != 0xE590C004 or (w[k + 1] & 0xFFFF4000) != 0xE92D4000:   # ldr ip, [r0, #4]; push {.., lr}
        return None
    return e.text_va + 4 * k


def insider_lines(game_elf):
    """coop.cfg's ``users`` and ``achievements`` lines for this program (each left out when not found)."""
    out = []
    try:
        u = insider_users(game_elf)
    except Exception:                                                # noqa: BLE001 - a build the finder cannot read
        u = None
    if u:
        out.append("users 0x%08x 0x%x 0x%x" % u)
    try:
        a = achievement_award(game_elf)
    except Exception:                                                # noqa: BLE001
        a = None
    if a:
        out.append("achievements 0x%08x" % a)
    return out


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


# ---- PAD-1031: co-op characters -------------------------------------------------------------------------------------
# DoomWalrus666 (Godzilla): each player picks a Godzilla at the start of their ball 1 (or Random), no two the same, each
# with an ability of its own; daveyvandy: a generic entry point, the Godzilla set delivered beside it. The game plays one
# player for the team, so an ability is what holds while its teammate is up (pad_mode_runtime.c "co-op characters"): an
# adjustment the game reads differently (the getter is wrapped; NVRAM never changes) or a ball save on the Action
# button. Each ability is offered where the card's own program has what it needs (its adjustment, by name).

#: the most characters a card carries (the runtime's COOP_CHARS)
MAX_CHARACTERS = 16
#: the longest name, and the longest words for what one does, the game's top line shows (the runtime's 28-byte fields)
MAX_NAME = 27
#: PAD-1056: the longest sub header under a name on the pick and award cards (only the cards show it, never the game's
#: top line, so it keeps the case it was typed in); PAD-1075: GMK's film title runs to 72 (the card shrinks it)
MAX_SUB = 80
#: PAD-1044: the seconds a teammate has to pick (the runtime's COOP_PICK_MS when coop.cfg names none), and the
#: choices the Characters dialog offers; 0 is no time limit (the Action button takes one)
PICK_TIME = 30
PICK_TIMES = (15, 20, 30, 45, 60, 90, 0)
#: the presets beside this module: ``coop_presets/<title stem>.json`` (the customization file per game)
PRESET_DIR = "coop_presets"

#: PAD-1075: Godzilla's multiballs' own ball save timers and their bounds, each read when its multiball starts (the
#: add-a-ball's too): the longer-save ability doubles them (its top doubled too)
_MULTIBALL_SAVES = (
    ("AD_GODZILLA_MULTIBALL_BALL_SAVE_TIMER", 10, 30),
    ("AD_MECHAGODZILLA_MULTIBALL_BALL_SAVE_TIMER", 10, 30),
    ("AD_BRIDGE_ATTACK_MULTIBALL_BALL_SAVE_TIMER", 13, 20),
    ("AD_TANK_ATTACK_MULTIBALL_BALL_SAVE_TIMER", 15, 30),
    ("AD_SAUCER_ATTACK_MULTIBALL_BALL_SAVE_TIMER", 20, 30),
    ("AD_PLANET_X_MULTIBALL_BALL_SAVE_TIMER", 30, 60),
    ("AD_BATTLE_VS_KING_GHIDORAH_BALL_SAVE_TIMER", 28, 40),
    ("AD_BATTLE_VS_GHIDORAH_AND_GIGAN_BALL_SAVE_TIMER", 28, 40),
    ("AD_BATTLE_VS_MEGALON_AND_GIGAN_MB_BALL_SAVE_TIMER", 14, 25),
    ("AD_MONSTER_ZERO_BALL_SAVE_TIMER", 28, 40),
    ("AD_KING_OF_THE_MONSTERS_MB_BALL_SAVE_TIMER", 28, 40),
    ("AD_ADD_A_BALL_SAVE_TIMER", 5, 10),
)

#: Round 6 (David, 2026-11-08: "give the end user the flexibility to customize this themselves ... available in the app
#: itself"): a character carries a list of POWERS, each one thing the runtime does, composed in the Characters dialog;
#: the old single abilities (:data:`ABILITIES`) are bundles of them. A power is (key, group, badge words, the card's
#: line in the player's words, what it does, how); how is ("adj", adjustment name, "x<pct>" | "x<pct>:<lo>:<hi>" |
#: "+<n>:<lo>:<hi>" | "min" | "max"), ("cache", adjustment name, "min"): an adjustment the game copies into a player's
#: record at the game's start (the port's ``coop_cache_<id>`` names the copy), ("boost", pct): the port's ``coop_boost``
#: call adds pct %, ("gift", adjustment name): the game's own one-shot feature at the pick and every turn (the port's
#: ``coop_adj_changed``), ("count", name, n) / ("set", name, n): a rule's count for the player raised by n or made n at
#: the pick (the port's ``coop_count_<name>``), ("double", name): that count rises two at a time, ("steps", name): a
#: rule's steps come two a shot, ("keep", name, v) / ("floor", name, v): a word of the game's held at v / at least v,
#: ("perk", id): one of the game's own power-ups owned from the pick (Godzilla: the perks picked at the scoop, one bit
#: each in the word the port's ``coop_keep_perks_obj`` names; the rules test their own bits), ("eb", ball): an extra
#: ball as the character's ball n begins (the game's own award, the port's ``coop_eb_award``), ("save", seconds),
#: ("addball", n): Action twice with one ball in play (modes too, PAD-1265) serves n more balls, ("spot", rules value name), ("unlock", adjustment
#: name, rules value name or None), ("lit", name) + ("yes", name): a shot held lit / a check of the game's answering
#: yes (the port's ``coop_lit_<name>`` / ``coop_yes_<name>``), or ("many", [hows]): all of them or none.
_MB_SAVES = tuple((m, lo, hi) for m, lo, hi in _MULTIBALL_SAVES if m != "AD_ADD_A_BALL_SAVE_TIMER")
_BATTLE_TIMERS = (("AD_BATTLE_VS_EBIRAH_TIMER", 80), ("AD_BATTLE_VS_TITANOSAURUS_TIMER", 80),
                  ("AD_BATTLE_VS_GIGAN_TIMER", 80), ("AD_BATTLE_VS_MEGALON_TIMER", 80),
                  ("AD_BATTLE_VS_KING_GHIDORAH_TIMER", 100), ("AD_BATTLE_VS_GHIDORAH_AND_GIGAN_TIMER", 100))
POWERS = (
    ("ball_save_x2", "Ball save", "LONGER BALL SAVE", "Twice the ball save at the start of every ball.",
     "The ball save at each of their balls lasts twice the game's BALL SAVE TIME (at most its top).",
     ("adj", "AD_BALL_SAVE_TIME", "x200")),
    ("multiball_saves_x2", "Ball save", "LONGER MULTIBALL SAVES", "Twice the ball save in multiball modes.",
     "Every multiball's and wizard mode's own ball save lasts twice its timer (Godzilla: 13 of them, read through the "
     "getter as each begins).", ("many", [("adj", m, "x200:%d:%d" % (lo, 2 * hi)) for m, lo, hi in _MB_SAVES])),
    ("addball_save_x2", "Ball save", "LONGER SAVE AFTER AN ADDED BALL",
     "Ten seconds of ball save after every added ball, Anguirus's included.",
     "The ball save after any added ball (Anguirus's, a multiball's add-a-ball) lasts twice its ADD A BALL SAVE "
     "TIMER: 5 to 10 seconds.", ("adj", "AD_ADD_A_BALL_SAVE_TIMER", "x200:5:20")),
    ("o2_x2", "Ball save", "LONGER OXYGEN DESTROYER", "Longer Oxygen Destroyer.",
     "The Oxygen Destroyer timer runs twice its setting.", ("adj", "AD_O2_DESTROYER_TIMER", "x200:8:40")),
    ("action_save", "Action button", "ACTION BUTTON BALL SAVE", "Press Action twice for a 10 second ball save, once a ball.",
     "A 10 second ball save when they press the Action button twice quickly, once a ball.", ("save", 10)),
    ("addball", "Action button", "ADD A BALL", "Press Action twice to add a ball, once a ball, not in multiball.",
     "Two quick presses of the Action button put another ball in play, once a ball - in a battle or other mode too, "
     "not during a multiball.", ("addball", 1)),
    ("spot", "Action button", "SPOT A BATTLE SHOT", "Press Action twice in a battle to hit its next shot, once per battle.",
     "Two quick presses of the Action button during a battle count as its next lit shot, once in each battle they start "
     "(every ball, every battle).", ("spot", "coop_battle_rules")),
    ("easy_battles", "Battles", "EASIER BATTLES", "One ramp lights a battle.",
     "The ramps light a battle as on the game's easiest LIGHT BATTLE DIFFICULTY.", ("cache", "AD_LIGHT_BATTLE_DIFFICULTY", "min")),
    ("battle_timers_10", "Battles", "LONGER BATTLE TIMERS", "10 seconds more on battle timers.",
     "Every battle timer gets 10 seconds more.", ("many", [("adj", m, "+10:30:%d" % hi) for m, hi in _BATTLE_TIMERS])),
    ("tier2", "Battles", "TIER 2 ALWAYS OPEN", "Every battle is open to you, tier 2 included.",
     "Every battle on the selection screen is open while they are up, tier 2 included (the game's UNLOCK ALL MONSTER "
     "BATTLES reads On for them).", ("unlock", "AD_BATTLE_UNLOCK_ALL_MONSTER_BATTLES", None)),
    ("heat_ray", "Heat ray and trains", "HEAT RAY READY, EASIER HEAT RAY",
     "Heat ray ready at your first spin. Recharges in half the spins.",
     "The heat ray is one spin from ready when they pick (the first spinner spin of their first ball lights HEAT RAY "
     "READY, the game's own way) and it charges in half the spinner spins a level (HEAT RAY SPINS PER LEVEL).",
     ("many", [("adj", "AD_HEAT_RAY_SPINS_PER_LEVEL", "x50"), ("set", "heatlevel", 3), ("set", "heatspins", 9)])),
    ("train_lit", "Heat ray and trains", "TRAINS ALWAYS LIT", "A train is lit at every one of your balls.",
     "A train is lit at each of their balls (the game's own LIGHT TRAIN).", ("gift", "AD_LIGHT_TRAIN")),
    ("building_x2", "Multiballs", "BUILDING MULTIBALL", "Building damage two steps a shot.",
     "Every building or ramp shot takes two of the building's six stability steps (on the game's easiest BUILDING "
     "DIFFICULTY).", ("many", [("cache", "AD_BUILDING_DIFFICULTY", "min"), ("steps", "building")])),
    ("mecha_x2", "Multiballs", "MECHA MULTIBALL", "Mecha spins and shield hits count twice.",
     "Toward Mechagodzilla Multiball every spin counts twice and every shield target hit counts twice.",
     ("many", [("double", "spins"), ("double", "shield")])),
    ("saucer_x2", "Multiballs", "SAUCER MULTIBALL", "Pop hits count twice for an earlier Saucer Attack Multiball.",
     "Every pop bumper hit counts twice toward Saucer Attack, so its multiball comes sooner.", ("double", "saucer")),
    ("easy_bridge", "Multiballs", "EASIER BRIDGE", "The bridge falls faster.",
     "The bridge falls as on the game's easiest BRIDGE ATTACK DIFFICULTY.", ("cache", "AD_BRIDGE_ATTACK_DIFFICULTY", "min")),
    ("powerups_x2", "Power-ups", "DOUBLE POWER-UPS", "Power-ups count twice.",
     "Every Godzilla power-up the game gives counts twice.", ("boost", 200)),
    ("rampage_x2", "Power-ups", "DOUBLE RAMPAGE", "Rampage letters count twice.",
     "Every RAMPAGE letter collected counts as two.", ("double", "rampage")),
    ("dj_2x", "Power-ups", "+1X JACKPOT", "Destruction Jackpot at least 2X.",
     "The Destruction Jackpot multiplier is never below 2X for them.", ("floor", "djmult", 1)),
    ("dj_lit", "Power-ups", "DESTRUCTION JACKPOT LIT", "Destruction Jackpot lit at every one of your balls.",
     "The Destruction Jackpot is lit at each of their balls (the game's own LIGHT DESTRUCTION JACKPOT).",
     ("gift", "AD_LIGHT_LIGHT_DESTRUCTION_JACKPOT")),
    ("ally_lit", "Allies", "AN ALLY EVERY BALL", "An ally lit at every one of your balls.",
     "An ally is lit at each of their balls: the game's next unlit one of Mothra, Rodan and Anguirus (its LIGHT ALLY), "
     "at the pick and at every later turn.", ("gift", "AD_LIGHT_ALLY")),
    ("rodan_x2", "Allies", "LONGER RODAN", "Rodan lasts twice as long.",
     "Rodan's playfield multiplier runs twice its timer.", ("adj", "AD_RODAN_PLAYFIELD_MULTIPLIER_TIMER", "x200:40:120")),
    ("hedorah", "Allies", "HEDORAH STARTS", "Hedorah starts on each of your turns.",
     "Hedorah starts at each of their turns (the game's own START HEDORAH).", ("gift", "AD_START_HEDORAH")),
    ("maser_lit", "Maser", "MASER LIT", "Maser lit while you are up.",
     "The Maser cannon target is lit the whole time they are up (in regular play and for all of Tank Attack).",
     ("many", [("lit", "maser"), ("yes", "maser")])),
    ("magna_grab", "Maser", "MAGNA GRAB LIT", "Magna Grab lit while you are up.", "Magna Grab is kept lit.",
     ("keep", "magna", 1)),
    ("powerlines_x2", "Maser", "DOUBLE POWERLINES", "Powerline hits count double.",
     "Every powerline target hit counts as two targets.", ("steps", "powerline")),
    ("jets_4", "Tanks and jets", "STARTS WITH 4 JETS", "Starts with 4 jet fighters destroyed.",
     "Four jet fighters count as destroyed when they pick (JET FIGHTER CHAMPION and the bonus count them).",
     ("count", "jets", 4)),
    ("tanks_4", "Tanks and jets", "STARTS WITH 4 TANKS", "Starts with 4 tanks destroyed.",
     "Four tanks count as destroyed when they pick: the city map's TANKS n/10 starts at 4.", ("count", "tanks", 4)),
    ("tanks_x2", "Tanks and jets", "DOUBLE TANKS", "Tanks count two at a time.",
     "Every tank destroyed counts as two.", ("double", "tanks")),
    ("jets_x2", "Tanks and jets", "DOUBLE JETS", "Jets count two at a time.",
     "Every jet destroyed counts as two.", ("double", "jets")),
    ("extra_ball_3", "Extra ball", "EXTRA BALL AFTER BALL 3", "An extra ball as your ball 3 begins.",
     "As their ball 3 begins the game awards them an extra ball, its own way (SHOOT AGAIN lit; it counts in the "
     "game's extra ball audit and limit; off or at the limit, the game gives its consolation points instead).",
     ("eb", 3)),
    ("extra_ball_1", "Extra ball", "EXTRA BALL AFTER BALL 1", "An extra ball as your ball 1 begins.",
     "As their first ball begins the game awards them an extra ball, its own way.", ("eb", 1)),
    # the game's own power-ups (Godzilla: the perks a player picks at the scoop), owned from the pick
    ("perk_loop_2x", "Power-up perks", "LOOP VALUE 2X", "Every loop scores double.",
     "They own the game's LOOP VALUE 2X power-up from the pick: every loop scores double.", ("perk", 8)),
    ("perk_loop_250k", "Power-up perks", "LOOP VALUE +250K", "Every loop scores 250K more.",
     "They own the game's LOOP VALUE +250K power-up from the pick.", ("perk", 7)),
    ("perk_spinner_2x", "Power-up perks", "SUPER SPINNER +2X", "Super spinner at 2X more.",
     "They own the game's SUPER SPINNER +2X power-up from the pick.", ("perk", 22)),
    ("perk_magna_2x", "Power-up perks", "MAGNA GRAB 2X", "Magna Grab awards double.",
     "They own the game's MAGNA GRAB 2X power-up from the pick.", ("perk", 21)),
    ("perk_rodan_15", "Power-up perks", "RODAN +15 SECONDS", "Every Rodan runs 15 seconds longer.",
     "They own the game's RODAN TIMER +15 SECONDS power-up from the pick: each Rodan summon adds 15 seconds.",
     ("perk", 20)),
    ("perk_dj_2x", "Power-up perks", "DESTRUCTION JACKPOT +2X", "Destruction Jackpot at +2X.",
     "They own the game's DESTRUCTION JACKPOT +2X power-up from the pick.", ("perk", 19)),
    ("perk_dj_3s", "Power-up perks", "DESTRUCTION JACKPOT +3 SECONDS", "Three more seconds on the Destruction Jackpot.",
     "They own the game's DESTRUCTION JACKPOT +3 SECONDS power-up from the pick.", ("perk", 18)),
    ("perk_rage_3s", "Power-up perks", "RAGE COMBO +3 SECONDS", "Three more seconds for Rage Combos.",
     "They own the game's RAGE COMBO +3 SECONDS power-up from the pick.", ("perk", 11)),
    ("perk_saucer_3s", "Power-up perks", "SAUCER ATTACK +3 SECONDS", "Three more seconds in Saucer Attack.",
     "They own the game's SAUCER ATTACK +3 SECONDS power-up from the pick.", ("perk", 10)),
    ("perk_saucer_500k", "Power-up perks", "SAUCER VALUE +500K", "Saucer hits score 500K more.",
     "They own the game's SAUCER VALUE +500K power-up from the pick.", ("perk", 9)),
    ("perk_tier1_20s", "Power-up perks", "TIER 1 BATTLE TIMERS +20 SECONDS", "Twenty more seconds in tier 1 battles.",
     "They own the game's TIER 1 BATTLE TIMERS +20 SECONDS power-up from the pick.", ("perk", 15)),
    ("perk_tier1_bonus_5x", "Power-up perks", "TIER 1 BATTLE TIME BONUS +5X", "Tier 1 battle time bonus at 5X.",
     "They own the game's TIER 1 BATTLE TIME BONUS +5X power-up from the pick.", ("perk", 16)),
    ("perk_tier2_20s", "Power-up perks", "TIER 2 BATTLE TIMERS +20 SECONDS", "Twenty more seconds in tier 2 battles.",
     "They own the game's TIER 2 BATTLE TIMERS +20 SECONDS power-up from the pick.", ("perk", 17)),
    ("perk_skill_1x", "Power-up perks", "SKILL SHOT +1X MULTIPLIER", "Every skill shot adds another 1X.",
     "They own the game's SKILL SHOT +1X MULTIPLIER power-up from the pick.", ("perk", 2)),
    ("perk_rampage_1x", "Power-up perks", "MONSTER RAMPAGE +1X", "Monster Rampage at +1X.",
     "They own the game's MONSTER RAMPAGE +1X power-up from the pick.", ("perk", 25)),
    ("perk_jets_250k", "Power-up perks", "JET FIGHTER ATTACK +250K", "Jet Fighter Attack shots score 250K more.",
     "They own the game's JET FIGHTER ATTACK VALUES +250K power-up from the pick.", ("perk", 24)),
    ("perk_gzmb_250k", "Power-up perks", "GODZILLA MULTIBALL JACKPOT +250K", "Godzilla Multiball jackpots start 250K higher.",
     "They own the game's GODZILLA MULTIBALL BASE JACKPOT +250K power-up from the pick.", ("perk", 5)),
    ("perk_mechamb_500k", "Power-up perks", "MECHA MULTIBALL JACKPOT +500K",
     "Mechagodzilla Multiball jackpots start 500K higher.",
     "They own the game's MECHAGODZILLA MULTIBALL BASE JACKPOT +500K power-up from the pick.", ("perk", 6)),
)
#: the dialog's groups, in order
POWER_GROUPS = ("Ball save", "Action button", "Battles", "Heat ray and trains", "Multiballs", "Power-ups", "Allies",
                "Maser", "Tanks and jets", "Extra ball", "Power-up perks")
#: the single abilities of rounds 1-5 (PAD-1075: DoomWalrus666's list), now bundles of powers: (key, words the pick
#: shows, what it does, [power keys]). A character saved with one of these gets its powers; the dialog offers each as
#: a starting point.
ABILITIES = (
    ("longer_save", "LONGER BALL SAVE, LONGER TIMERS",
     "The ball save at each of their balls lasts twice the game's BALL SAVE TIME (at most its top); on Godzilla the "
     "Oxygen Destroyer timer is twice its setting and every multiball's ball save lasts twice its timer.",
     ["ball_save_x2", "o2_x2", "multiball_saves_x2", "addball_save_x2"]),
    ("action_save", "ACTION BUTTON BALL SAVE",
     "A 10 second ball save when they press the Action button twice quickly, once a ball.", ["action_save"]),
    ("heat_ray", "HEAT RAY READY, EASIER HEAT RAY, TRAINS ALWAYS LIT", "The heat ray is one spin from ready when they "
     "pick (the first spinner spin of their first ball lights HEAT RAY READY, the game's own way), it charges in half "
     "the spinner spins a level (HEAT RAY SPINS PER LEVEL), and a train is lit at each of their balls (the game's own "
     "LIGHT TRAIN).", ["heat_ray", "train_lit"]),
    ("battles", "EASIER BATTLES", "The ramps light a battle as on the game's easiest LIGHT BATTLE DIFFICULTY.",
     ["easy_battles"]),
    ("building", "BUILDING AND MECHA MULTIBALLS", "Every building or ramp shot takes two of the building's six "
     "stability steps (on the game's easiest BUILDING DIFFICULTY), and toward Mechagodzilla Multiball every spin "
     "counts twice and every shield target hit counts twice.", ["building_x2", "mecha_x2"]),
    ("powerups", "DOUBLE POWER-UPS, SAUCER, RAMPAGE, +1X JACKPOT", "Every Godzilla power-up the game gives counts "
     "twice, every hit on the saucer (the pop bumper) counts twice toward Saucer Attack, every RAMPAGE letter collected "
     "counts as two, and the Destruction Jackpot multiplier is never below 2X for them.",
     ["powerups_x2", "saucer_x2", "rampage_x2", "dj_2x"]),
    ("ally", "AN ALLY EVERY BALL, LONGER RODAN, HEDORAH STARTS", "An ally is lit at each of their balls: the game's "
     "next unlit one of Mothra, Rodan and Anguirus (its LIGHT ALLY), at the pick and at every later turn; Rodan's "
     "playfield multiplier runs twice its timer; Hedorah starts at each of their turns (the game's own START HEDORAH); "
     "and the ball save after an added ball, Anguirus's included, lasts twice its timer (round 6).",
     ["ally_lit", "rodan_x2", "hedorah", "addball_save_x2"]),
    ("jets", "STARTS WITH 4 JETS", "Four jet fighters count as destroyed when they pick (JET FIGHTER CHAMPION and "
     "the bonus count them).", ["jets_4"]),
    ("spot", "SPOT A BATTLE SHOT, LONGER BATTLE TIMERS", "Two quick presses of the Action button during a battle "
     "count as its next lit shot, once in each battle they start (every ball, every battle); on Godzilla every battle "
     "timer gets 10 seconds more.", ["spot", "battle_timers_10"]),
    ("tier2", "TIER 2 ALWAYS OPEN", "Every battle on the selection screen is open while they are up, tier 2 included "
     "(the game's UNLOCK ALL MONSTER BATTLES reads On for them).", ["tier2"]),
    ("addball", "ADD A BALL", "Two quick presses of the Action button put another ball in play, once a ball - in a battle "
     "or other mode too, not during a multiball.", ["addball"]),
    ("maser", "MASER, MAGNA GRAB, AND DESTRUCTION JACKPOT LIT, DOUBLE POWERLINES AND POP HITS", "The Maser cannon "
     "target is lit the whole time they are up (in regular play and for all of Tank Attack), Magna Grab is kept lit, "
     "every powerline target hit counts as two targets, every pop bumper hit counts twice toward Saucer Attack, and "
     "the Destruction Jackpot is lit at each of their balls (the game's own LIGHT DESTRUCTION JACKPOT).",
     ["maser_lit", "magna_grab", "powerlines_x2", "saucer_x2", "dj_lit"]),
    ("bridge", "EASIER BRIDGE, DOUBLE TANKS AND JETS", "The bridge falls as on the game's easiest BRIDGE ATTACK "
     "DIFFICULTY, and every tank or jet destroyed counts as two.", ["easy_bridge", "tanks_x2", "jets_x2"]),
    ("tanks", "STARTS WITH 4 TANKS", "Four tanks count as destroyed when they pick: the city map's TANKS n/10 starts "
     "at 4.", ["tanks_4"]),
)
_POWER = {p[0]: p for p in POWERS}
#: what the pick's card says each bundle does, in the player's words: its powers' lines
CARD_LINES = {key: " ".join(_POWER[k][3] for k in keys) for key, _w, _d, keys in ABILITIES}
#: the most parts of each kind one character takes (the runtime's coop_char_line: COOP_CHAR_ADJ, COOP_GIFTS,
#: COOP_CH_N for count/keep/steps/lit/yes, COOP_CH_DBL) and the longest abilities text (its tok[])
LIMITS = {"adj": 24, "gift": 6, "count": 4, "keep": 4, "steps": 4, "lit": 4, "yes": 4, "double": 6}
MAX_CFG = 767
#: the longest badge the card shows (PAD-1075: a long one shrinks and takes three lines)
MAX_HEADER = 96
#: PAD-1083: the badge's smallest size on the pick card (px at scale 1) and its words' room there: the card's words
#: column (CARD_SIZE wide less the portrait and margins, pick_card's iw) less the pill's ends
BADGE_LEAST = 14
BADGE_ROOM = 1280 - (40 + 380 + 44) - 44 - 40

#: why an ability is not offered on a card
NO_ADJ = "%s's game program has no %s setting."
NO_ACTION = "%s has no Action button."
NO_SITE = "The app does not know where %s keeps this yet."

_ACTION = re.compile(r"^(LOCKDOWN|ACTION) BUTTON( \(OPTIONAL\))?$")
#: PAD-1045: the plunger's lane (not an upper one): the Action button launches from it on Godzilla, so the save's double
#: press counts once the ball is out
_LANE = re.compile(r"^SHOOTER LANE( OPTO)?$")


def _switch_named(game_elf, pattern):
    from . import portgen as G
    from . import portswitch as PS
    try:
        sws = PS.switches(G.Elf(bytes(game_elf)))
    except (G.PortgenError, ValueError, struct.error, IndexError):
        return None
    for sw in sws:
        if pattern.match(" ".join(str(sw["name"]).upper().split())):
            return int(sw["id"])
    return None


def timed_plunger(game_elf):
    """PAD-1114: the id of the game's TIMED PLUNGER adjustment (AD_TIMED_PLUNGER: "Autolaunches a ball in the Shooter
    Lane after a specified amount of idle time"), or None. The runtime answers it 0 (off) while the co-op intro, the ball's
    wait and the language window keep the ball in the lane: on Godzilla LE 1.16 (emulator) it launched the ball some 18 s
    after it came, cutting the pick short."""
    from .adjustments import AdjustmentTable
    try:
        return AdjustmentTable(game_elf).by_name.get("AD_TIMED_PLUNGER")
    except Exception:                                   # noqa: BLE001 - a program the table cannot be read off
        return None


def action_button(game_elf):
    """The switch id of the Action button (the lockdown bar's: LOCKDOWN BUTTON, ACTION BUTTON) in the game program
    *game_elf* (bytes), or None."""
    return _switch_named(game_elf, _ACTION)


def shooter_lane(game_elf):
    """The switch id of the shooter lane (SHOOTER LANE, SHOOTER LANE OPTO) in the game program *game_elf* (bytes), or
    None."""
    return _switch_named(game_elf, _LANE)


def abilities(game_elf, label="This game", sites=(), values=None):
    """Every ability, as the card *game_elf* (bytes) can have it: ``[{"key", "words", "does", "cfg", "why"}]``; ``cfg``
    is the runtime's ability text (``adj:94x200:0:15``), ``""`` with ``why`` when the card cannot have it. *sites*:
    the site names of the build's port (the cache, boost and gift abilities need theirs); *values*: its ``value``
    lines (``{name: number}``; the spot and unlock abilities need the rules they watch)."""
    sites = set(sites or ())
    values = dict(values or {})
    from .adjustments import AdjustmentTable
    try:
        table = AdjustmentTable(bytes(game_elf))
    except (ValueError, struct.error, IndexError):
        table = None
    action = action_button(game_elf)
    parts = {p["key"]: p for p in powers(game_elf, label, sites, values, table=table, action=action)}
    out = []
    for key, words, does, keys in ABILITIES:
        got = compose(keys, parts)
        out.append({"key": key, "words": words, "does": does, "cfg": got["cfg"], "why": got["why"],
                    "powers": list(keys)})
    return out


def powers(game_elf, label="This game", sites=(), values=None, table=None, action=None):
    """Round 6: every power, as the card *game_elf* (bytes) can have it: ``[{"key", "group", "words", "line", "does",
    "cfg", "why"}]``; ``cfg`` the runtime's text for it (a perk's is ``perk:0x<bit>``, folded by :func:`compose`),
    ``""`` with ``why`` when the card cannot have it. *sites* / *values* as for :func:`abilities`."""
    sites = set(sites or ())
    values = dict(values or {})
    if table is None:
        from .adjustments import AdjustmentTable
        try:
            table = AdjustmentTable(bytes(game_elf))
        except (ValueError, struct.error, IndexError):
            table = None
    if action is None:
        action = action_button(game_elf)
    out = []
    for key, group, words, line, does, how in POWERS:
        cfg, why = _ability_part(how, table, action, sites, values, label)
        out.append({"key": key, "group": group, "words": words, "line": line, "does": does, "cfg": cfg, "why": why})
    return out


def compose(keys, parts):
    """Round 6: a character's powers *keys* (in order) as one ability for the runtime, from *parts* (:func:`powers`'
    entries by key): ``{"cfg", "words", "line", "missing", "over", "why"}``. ``cfg`` is the tokens of the powers the
    card has, each once, the perks folded into one ``keep:perks|=<mask>``; ``words`` the badge (their words, comma
    separated) and ``line`` the card's line (their lines) for those; ``missing`` the keys the card cannot have (and
    ``why`` the first one's reason, when the FIRST power is missing: none of the ability then, as a bundle's core);
    ``over`` the kinds past :data:`LIMITS` (the runtime drops the rest of that kind without a word)."""
    toks, words, lines, missing, why, perks = [], [], [], [], "", 0
    for i, k in enumerate(keys):
        p = parts.get(k)
        if not p or not p["cfg"]:
            missing.append(k)
            if i == 0:
                why = (p or {}).get("why") or NO_POWER % k
            continue
        for tok in p["cfg"].split(","):
            if tok.startswith("perk:"):
                perks |= int(tok[5:], 0)
            elif tok not in toks:
                toks.append(tok)
        words.append(p["words"])
        lines.append(p["line"])
    if perks:
        toks.append("keep:perks|=0x%x" % perks)
    if why:
        toks, words, lines = [], [], []
    cfg = ",".join(toks)
    counts = {}
    for tok in toks:
        kind = tok.split(":")[0]
        counts[kind] = counts.get(kind, 0) + 1
    over = sorted(k for k, n in counts.items() if n > LIMITS.get(k, 99))
    if len(cfg) > MAX_CFG:
        over.append("length")
    return {"cfg": cfg, "words": ", ".join(words), "line": " ".join(lines), "missing": missing, "over": over, "why": why}


#: why a power named in a file is not one
NO_POWER = "There is no power called %s."
#: round 6: a bundle's powers by its key
ABILITY_POWERS = {key: list(keys) for key, _w, _d, keys in ABILITIES}


def _powers_of(got):
    """A saved character's powers: its ``powers`` list (the keys known, each once, in order), or its old single
    ``ability``'s bundle."""
    if isinstance(got.get("powers"), list):
        out = []
        for k in got["powers"]:
            k = str(k)
            if k in _POWER and k not in out:
                out.append(k)
        return out
    return list(ABILITY_POWERS.get(str(got.get("ability") or ""), []))


def bundle_of(keys):
    """The bundle key whose powers are exactly *keys*, or ``""``."""
    for key, _w, _d, want in ABILITIES:
        if list(want) == list(keys):
            return key
    return ""


def clean_header(header):
    """A character's own badge words (round 6: in place of its powers' words): capitals, one space between words, no
    ``|``, at most :data:`MAX_HEADER`."""
    return " ".join(str(header or "").upper().replace("|", " ").split())[:MAX_HEADER]


def character_words(character, words_for=None):
    """The badge the pick's card shows for *character*: its own header, or its powers' words (*words_for*: key ->
    words, :func:`words_for`; a power not in it is left out)."""
    if character.get("header"):
        return character["header"]
    wf = words_for if words_for is not None else {p[0]: p[2] for p in POWERS}
    keys = [k for k in character.get("powers") or [] if k in wf]
    bundle = bundle_of(keys)                                # exactly one of the old abilities: its shorter badge
    if bundle:
        return dict((a[0], a[1]) for a in ABILITIES)[bundle]
    return ", ".join(wf[k] for k in keys)


def badge_label(draw, character, label, words_for, room, S):
    """PAD-1083: the badge *label* as the pick card shows it in *room* px at its smallest size (``BADGE_LEAST * S``):
    ``(label, cut)``. A label that fits is as it is; past that, a character's powers' words keep as many whole powers
    as fit and say how many more (``MASER LIT, MAGNA GRAB LIT +4 MORE``), and its own words (or one power's too long
    alone) stop at the last whole word that fits, with ``...``. *cut* is True when it was shortened."""
    f = _face(_TEXT_FONTS, BADGE_LEAST * S)
    fits = lambda t: draw.textlength(t, font=f) <= room                      # noqa: E731
    if fits(label):
        return label, False
    if not character.get("header"):
        wf = words_for if words_for is not None else {p[0]: p[2] for p in POWERS}
        words = [wf[k] for k in character.get("powers") or [] if k in wf]
        if ", ".join(words) == label:                                       # its powers' words, one by one
            for n in range(len(words) - 1, 0, -1):
                t = "%s +%d MORE" % (", ".join(words[:n]), len(words) - n)
                if fits(t):
                    return t, True
    words = label.split()
    while len(words) > 1 and not fits(" ".join(words) + "..."):
        words.pop()
    t = " ".join(words)
    while t and not fits(t + "..."):
        t = t[:-1]
    return t.rstrip(" ,") + "...", True


def badge_on_card(character, words_for=None):
    """PAD-1083: ``(label, cut)``, the badge the pick card shows for *character* (:func:`badge_label` at the card's
    own size), for the Characters dialog to say when it is too long."""
    from PIL import Image, ImageDraw
    S = 2
    label = character_words(character, words_for) or "NO SPECIAL ABILITY"
    return badge_label(ImageDraw.Draw(Image.new("L", (1, 1))), character, label, words_for, BADGE_ROOM * S, S)


def character_line(character, words_for=None):
    """The card's line for *character*: its powers' lines in the player's words (the powers in *words_for*)."""
    wf = words_for if words_for is not None else {p[0]: p[2] for p in POWERS}
    return " ".join(_POWER[k][3] for k in character.get("powers") or [] if k in wf and k in _POWER)


def _ability_part(how, table, action, sites, values, label):
    """One ``how`` of :data:`ABILITIES` as the runtime's text and why not: ``(cfg, why)``."""
    cfg, why = "", ""
    if how[0] == "many":
        parts = [_ability_part(h, table, action, sites, values, label) for h in how[1]]
        bad = [w for c, w in parts if not c]
        return ("" if bad else ",".join(c for c, w in parts)), (bad[0] if bad else "")
    if how[0] == "some":                       # the first part is the ability; the rest come along where the game has them
        parts = [_ability_part(h, table, action, sites, values, label) for h in how[1]]
        if not parts[0][0]:
            return "", parts[0][1]
        return ",".join(c for c, w in parts if c), ""
    if True:
        if how[0] == "save":
            cfg, why = ("save:%d" % how[1], "") if action is not None else ("", NO_ACTION % label)
        elif how[0] == "boost":
            cfg, why = ("boost:%d" % how[1], "") if "coop_boost" in sites else ("", NO_SITE % label)
        elif how[0] == "addball":
            cfg, why = ("addball:%d" % how[1], "") if action is not None else ("", NO_ACTION % label)
        elif how[0] == "yes":
            cfg, why = ("yes:%s" % how[1], "") if "coop_yes_%s" % how[1] in sites else ("", NO_SITE % label)
        elif how[0] == "lit":
            mask = values.get("coop_lit_%s_mask" % how[1])
            cfg, why = (("lit:%s=0x%x" % (how[1], mask), "") if mask and "coop_lit_%s" % how[1] in sites
                        else ("", NO_SITE % label))
        elif how[0] == "double":
            cfg, why = (("double:%s" % how[1], "")
                        if {"coop_count_%s" % how[1], "coop_count_%s_rule" % how[1]} & sites
                        or "coop_count_%s_obj" % how[1] in values
                        else ("", NO_SITE % label))
        elif how[0] == "spot":
            rules = values.get(how[1])
            cfg, why = (("spot:0x%x" % rules, "") if rules and action is not None and "shot_dispatch" in sites
                        else ("", NO_ACTION % label if action is None else NO_SITE % label))
        elif how[0] in ("count", "set"):
            cfg, why = (("count:%s%s%d" % (how[1], "=" if how[0] == "set" else "+", how[2]), "")
                        if {"coop_count_%s" % how[1], "coop_count_%s_rule" % how[1]} & sites
                        or "coop_count_%s_obj" % how[1] in values
                        else ("", NO_SITE % label))
        elif how[0] == "steps":
            cfg, why = (("steps:%s" % how[1], "") if "coop_steps_%s_obj" % how[1] in values
                        else ("", NO_SITE % label))
        elif how[0] in ("keep", "floor"):
            cfg, why = (("keep:%s%s=%d" % (how[1], ">" if how[0] == "floor" else "", how[2]), "")
                        if "coop_keep_%s_obj" % how[1] in values else ("", NO_SITE % label))
        elif how[0] == "perk":                                  # round 6: compose() folds the perks into one keep:perks|=
            cfg, why = (("perk:0x%x" % (1 << how[1]), "") if "coop_keep_perks_obj" in values else ("", NO_SITE % label))
        elif how[0] == "eb":
            cfg, why = ("eb:%d" % how[1], "") if "coop_eb_award" in sites else ("", NO_SITE % label)
        else:
            idx = table.by_name.get(how[1]) if table is not None else None
            if idx is None:
                why = NO_ADJ % (label, how[1][3:].replace("_", " "))
            elif how[0] == "unlock":
                rules = values.get(how[2]) if how[2] else None
                cfg, why = (("unlock:%d" % idx, "") if not how[2]
                            else ("unlock:%d@0x%x" % (idx, rules), "") if rules else ("", NO_SITE % label))
            elif how[0] == "gift":
                cfg, why = ("gift:%d" % idx, "") if "coop_adj_changed" in sites else ("", NO_SITE % label)
            elif how[0] == "cache" and "coop_cache_%d" % idx not in sites:
                why = NO_SITE % label
            else:
                e = table.entry(idx)
                lo, hi = int(e["min"]), int(e["max"])
                if how[2] == "min":
                    cfg = "adj:%d=%d" % (idx, lo)
                elif how[2] == "max":
                    cfg = "adj:%d=%d" % (idx, hi)
                elif ":" in how[2]:                                # its own bounds: a timer past the setting's top
                    cfg = "adj:%d%s" % (idx, how[2])
                else:
                    cfg = "adj:%d%s:%d:%d" % (idx, how[2], lo, hi)
                if how[1] == "AD_BALL_SAVE_TIME":                  # read when a ball is served: the ball-1 pick's
                    cfg += ",bs:%d" % idx                          # ball gets it at the pick
    return cfg, why


def clean_name(name):
    """A character's name as the top line shows it: capitals, one space between words, no ``|``, at most
    :data:`MAX_NAME`."""
    return " ".join(str(name or "").upper().replace("|", " ").split())[:MAX_NAME]


def clean_sub(sub):
    """PAD-1056: a character's sub header (GODZILLA VS BIOLLANTE's "Godzilla vs Biollante (1989)") as the cards show it:
    one space between words, the case it was typed in, at most :data:`MAX_SUB`."""
    return " ".join(str(sub or "").split())[:MAX_SUB]


def load_characters(project):
    """The project's characters: ``{"pick": bool, "time": seconds, "list": [{"name", "sub", "ability", "picture"}]}``
    (``sub`` the line under the name on its cards, PAD-1056;
    ``ability`` a key of :data:`ABILITIES` or ``""``; ``picture`` the owner's file, for the pick screens that show
    one; ``time`` one of :data:`PICK_TIMES`)."""
    if not project:
        return {"pick": False, "time": PICK_TIME, "list": []}
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return {"pick": False, "time": PICK_TIME, "list": []}
    return _characters(raw.get("characters") if isinstance(raw, dict) else None)


def pick_time(got):
    """PAD-1044: the pick's seconds *got* asks for, one of :data:`PICK_TIMES` (:data:`PICK_TIME` when it is none)."""
    try:
        t = int(got)
    except (TypeError, ValueError):
        return PICK_TIME
    return t if t in PICK_TIMES else PICK_TIME


def _characters(got):
    if not isinstance(got, dict):
        return {"pick": False, "time": PICK_TIME, "list": []}
    out = []
    for c in got.get("list") or []:
        if isinstance(c, dict) and clean_name(c.get("name")):
            keys = _powers_of(c)                            # round 6: a list of powers (an old ability: its bundle)
            out.append({"name": clean_name(c.get("name")), "sub": clean_sub(c.get("sub")),
                        "powers": keys, "header": clean_header(c.get("header")),
                        "ability": bundle_of(keys),         # the bundle these are, for the dialog's starting points
                        "picture": str(c.get("picture") or ""), "colour": clean_colour(c.get("colour")),
                        "video": str(c.get("video") or ""),
                        # PAD-1123: what plays full screen once it is picked, and the sound with it
                        "picked_clip": str(c.get("picked_clip") or ""),
                        "picked_sound": str(c.get("picked_sound") or "")})
    theme = got.get("theme") if isinstance(got.get("theme"), dict) else {}
    out = {"pick": bool(got.get("pick")), "time": pick_time(got.get("time")), "list": out[:MAX_CHARACTERS]}
    if got.get("intro"):                                # PAD-1114: the co-op and team games' intro video
        out["intro"] = str(got["intro"])
    if got.get("ceremony"):                             # PAD-1219: the awards ceremony's background video
        out["ceremony"] = str(got["ceremony"])
    if got.get("bonus"):                                # PAD-1123: the teammate's character on their End of Ball Bonus
        out["bonus"] = True
    if theme:
        out["theme"] = {k: (int(v) if k == "dim" and str(v).isdigit() else str(v)) for k, v in theme.items()
                        if k in THEME and v is not None and v != ""}
    return out


def save_characters(project, characters):
    """Store the project's characters (:func:`load_characters`' shape); returns them as stored."""
    from ...core import staged_changes
    chars = _characters(characters)
    data = staged_changes.load(project)
    raw = dict(data.get(STAGED_KEY)) if isinstance(data.get(STAGED_KEY), dict) else {"on": False}
    if chars["list"] or chars["pick"] or chars.get("intro") or chars.get("ceremony") or chars.get("bonus"):
        raw["characters"] = chars
    else:
        raw.pop("characters", None)
    data[STAGED_KEY] = raw
    staged_changes.save(project, data)
    return chars


def character_lines(game_elf, characters=None, sites=(), values=None):
    """coop.cfg's character lines: ``pick on``, ``left``/``action`` (the buttons the pick and the save use), ``lane``
    (the shooter lane: the save's presses count once the ball is out of it, PAD-1045) and
    ``character <abilities> <name>|<what it does>`` for each character, an ability the card cannot have left out
    (``-``). None when *characters* has no pick or no characters."""
    chars = _characters(characters)
    picks = chars["pick"] and chars["list"]
    if not picks and not chars.get("intro"):            # PAD-1114: an intro wants the buttons (its skip, the language)
        return []
    out = ["pick on", "pick_time %d" % chars["time"]] if picks else []
    buttons = _SMo.flipper_buttons(game_elf)
    if len(buttons) == 2:
        out.append("left %d" % buttons[0])
    action = action_button(game_elf)
    if action is not None:
        out.append("action %d" % action)
        lane = shooter_lane(game_elf)
        if lane is not None:
            out.append("lane %d" % lane)
    if chars.get("intro"):
        hold = timed_plunger(game_elf)
        if hold is not None:
            out.append("intro_hold %d" % hold)      # PAD-1114: no auto-launch while the intro holds the ball
    from .handicap import start_button
    start = start_button(game_elf)
    if start is not None:                           # round 3: a Start while ball 1 waits adds a teammate; PAD-1215:
        out.append("intro_start %d" % start)        # the same while a pick holds a player's first ball back
    if not picks:
        return out
    parts = {p["key"]: p for p in powers(game_elf, sites=sites, values=values)}
    wf = {k: p["words"] for k, p in parts.items() if p["cfg"]}
    for c in chars["list"]:
        got = compose(c["powers"], parts)
        out.append("character %s %s|%s" % (got["cfg"] or "-", c["name"],
                                           character_words(c, wf) if got["cfg"] else ""))
    return out


def presets():
    """``{title stem: path}`` of the customization files shipped beside this module."""
    import os
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), PRESET_DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return {}
    return {n[:-5]: os.path.join(d, n) for n in names if n.endswith(".json")}


def read_preset(path):
    """A customization file (:data:`PRESET_DIR`'s, or one the owner made): ``{"game", "characters"}``, the characters
    in :func:`load_characters`' shape. Raises :class:`CoopError` when it cannot be read."""
    import json
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        raise CoopError("The co-op characters file could not be read: %s" % e) from e
    if not isinstance(raw, dict) or not isinstance(raw.get("characters"), list):
        raise CoopError("The file is not a co-op characters file (it has no characters list).")
    return {"game": str(raw.get("game") or ""),
            "characters": _characters({"pick": True, "list": raw["characters"], "theme": raw.get("theme")})}


def project_abilities(project):
    """``(why, abilities)`` for the Modes tab: :func:`abilities` read off the project's card's game program, cached per
    card; ``why`` says why there are none ("" when there are)."""
    why, got = _project_catalog(project)
    return why, got.get("abilities", [])


def project_powers(project):
    """Round 6: ``(why, powers)`` for the Characters dialog: :func:`powers` read off the project's card's game program
    (cached with the abilities)."""
    why, got = _project_catalog(project)
    return why, got.get("powers", [])


def _project_catalog(project):
    """``(why, {"abilities", "powers"})`` read off the project's card, cached per card and catalog version."""
    import hashlib
    import json
    import os
    from . import mode_project as MP
    from . import title_reader as TR
    got = MP.project_card(project) if project else None
    card = getattr(got, "image", "") if got is not None else ""
    if not card or not os.path.isfile(card):
        return NO_CARD_CHARS, {}
    prof = project_title(project)
    key = "%s|%d|%d|%s" % (card, os.path.getsize(card), int(os.path.getmtime(card)), ",".join(port_sites(prof)))
    cache = os.path.join(TR.cache_dir("coop_abilities"), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")
    try:
        with open(cache, encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("key") == key and raw.get("v") == _abilities_v() and "powers" in raw:
            return "", {"abilities": raw["abilities"], "powers": raw["powers"]}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    prof = project_title(project)
    try:
        elf = TR.game_program(card)[2]
        label = prof.label if prof is not None else "This game"
        out = {"abilities": abilities(elf, label, port_sites(prof), port_values(prof)),
               "powers": powers(elf, label, port_sites(prof), port_values(prof))}
    except Exception as e:                              # noqa: BLE001 - an unreadable card: say so
        return "The game program could not be read from the card: %s" % e, {}
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(dict(out, v=_abilities_v(), key=key), f)
    except OSError:
        pass
    return "", out


def _abilities_v():
    """The abilities cache's version: the catalog itself (round 6: the powers too), so a changed word reads the card
    again."""
    import hashlib
    return hashlib.sha1((repr(ABILITIES) + repr(POWERS)).encode("utf-8")).hexdigest()[:12]


def port_values(prof):
    """The ``value`` lines of *prof*'s port (``{}`` when it has none)."""
    from . import mode_project as MP
    if prof is None:
        return {}
    try:
        return dict(MP.read_port(MP.port_path(prof)).get("value", {}))
    except (OSError, MP.ModeProjectError):
        return {}


def port_sites(prof):
    """The site and data names of *prof*'s port (empty when it has none)."""
    from . import mode_project as MP
    if prof is None:
        return []
    try:
        port = MP.read_port(MP.port_path(prof))
        return sorted(set(port.get("site", {})) | set(port.get("data", {})))
    except (OSError, MP.ModeProjectError):
        return []


#: why the Modes tab cannot list a project's abilities
NO_CARD_CHARS = ("The app reads the abilities a game can have off its card, and this project's card image is not on "
                 "this computer.")


def preset_for(prof):
    """The shipped customization file for *prof*'s title (by its key's stem: ``godzilla``), or ``""``."""
    if prof is None:
        return ""
    key = _SMo.title_key(prof)
    for stem, path in presets().items():
        if key.startswith(stem):
            return path
    return ""


# ---- PAD-1031: the pick's screens ----------------------------------------------------------------------------------
# The game's top line is small (Godzilla: a long name ran into CREDITS), so the pick has screens of its own: one per
# character and one for RANDOM, each a picture (the owner's, or a generated panel with the name) and its words,
# added to the HUD scene as a mode's own screen is (scene_write.add_screens), authored visible and hidden by the
# runtime until the pick is on it. coop.cfg's ``screens <scene>`` names the scene they are in.

#: the folder in the project the characters' pictures are copied into
PICTURE_DIR = "coop"
#: a screen's node: ``PadCoop_<n>`` (1-based) and ``PadCoop_Random``
SCREEN_NODE = "PadCoop_%s"
#: PAD-1065: a character's Classic patch over its card
CLASSIC_NODE = "PadCoopClassic_%d"
#: the generated panel's colours when a character has no picture of its own
PANEL_COLOR, TITLE_COLOR = "#3a0a0a", "#ffb400"


def picture_path(project, character):
    """The absolute path of *character*'s picture in *project* (``""`` when it has none, or it is gone)."""
    import os
    rel = str((character or {}).get("picture") or "")
    if not rel or not project:
        return ""
    path = os.path.join(project, *rel.replace("\\", "/").split("/"))
    return path if os.path.isfile(path) else ""


def words_for(project=None):
    """``{power key: the words the pick shows for it}`` - round 6: every power's, or with *project* only the powers
    its card has (a power the game cannot have is not on the card)."""
    if project is None:
        return {p[0]: p[2] for p in POWERS}
    _why, got = project_powers(project)
    return {p["key"]: p["words"] for p in got if p["cfg"]}


def wants_screens(project, prof):
    """Whether *project*'s card gets the pick's screens: co-op on, characters with a pick, a title with screens."""
    if not load(project) or prof is None or not prof.can("screen"):
        return False
    chars = load_characters(project)
    return bool(chars["pick"] and chars["list"])


def pick_screens(project, characters=None, words_for=None, classic=None, videos=None):
    """The pick's screens for :func:`.scene_write.add_screens`: one per character (``PadCoop_1`` ...) and
    ``PadCoop_Random``; ``[]`` when the project's characters have no pick. *words_for* (key -> words) names what
    each ability does, as the top line says it. PAD-1065: with *classic* (None: when CO-OP PLAY is in the service menu,
    the only way to play Classic) each character with an ability also gets its :func:`classic_patch`
    (``PadCoopClassic_1`` ...), after the cards so it draws over its own. PAD-1079: with *videos* (None: when the
    project's title can play them, :func:`can_video`) a character with a video gets a see-through window in its card's
    portrait frame, where its clip plays behind."""
    from . import mode_assets as MA
    chars = _characters(characters if characters is not None else load_characters(project))
    if videos is None:
        videos = bool(clip_entries(project, chars)) and can_video(project_title(project))
    if not chars["pick"] or not chars["list"]:
        return []
    del MA
    out = []
    n = len(chars["list"])
    for i in range(n + 1):                    # every word is on the card but the runtime's: the seconds left, PICKED
        out.append(dict(name=SCREEN_NODE % ("Random" if i == n else i + 1),
                        art_rgba=pick_card(project, chars, i, words_for, chars.get("theme"), window=videos),
                        words=" ", words_name=(SCREEN_NODE % ("Random" if i == n else i + 1)) + "_Words",
                        x=float(CARD_AT[0]), y=float(CARD_AT[1]), words_at=TIMER_WORDS_AT,
                        words_scale=TIMER_WORDS_SCALE))
    if classic is None:
        classic = menu_asked(project)
    for i in range(n if classic else 0):
        got = classic_patch(project, chars, i, words_for, chars.get("theme"), window=videos)
        if got is not None:
            (x, y), art = got
            out.append(dict(name=CLASSIC_NODE % (i + 1), art_rgba=art, words=" ", x=float(CARD_AT[0] + x),
                            y=float(CARD_AT[1] + y)))
    return out


def classic_patch(project, characters, index, words_for=None, theme=None, window=False):
    """PAD-1065: the part of character *index*'s pick card that Classic (CO-OP PLAY 4-6) draws differently: the
    card as a character without an ability draws it (NO SPECIAL ABILITY, "Plays as the game always does."), cut to
    the box where it differs from the card with its ability, out to multiples of 4. ``((x, y) in the card, RGBA)``,
    or None when the character has no ability (its card says so already)."""
    import numpy as np
    chars = _characters(characters)
    if not chars["list"][index]["powers"]:                  # round 6: a list of powers (none: the card says so)
        return None
    full = pick_card(project, chars, index, words_for, theme, window=window)
    plain = pick_card(project, dict(chars, list=[dict(c, powers=[], header="") if k == index else c
                                                 for k, c in enumerate(chars["list"])]), index, words_for, theme,
                      window=window)
    ys, xs = np.nonzero(np.any(full != plain, axis=2))
    if not len(xs):
        return None
    h, w = plain.shape[:2]
    x0, y0 = int(xs.min()) // 4 * 4, int(ys.min()) // 4 * 4
    x1, y1 = min(w, -(-(int(xs.max()) + 1) // 4) * 4), min(h, -(-(int(ys.max()) + 1) // 4) * 4)
    return (x0, y0), np.ascontiguousarray(plain[y0:y1, x0:x1])


def picture_file_name(name):
    """The file name a character's picture has in a folder of them: ``godzilla_1954`` for GODZILLA 1954."""
    return "_".join("".join(ch for ch in str(name).lower() if ch.isalnum() or ch == " ").split())


def pictures_from_folder(project, folder):
    """Every picture in *folder* named after one of the project's characters (:func:`picture_file_name`, any
    picture extension) copied in as its picture; returns ``(found, [names without one])``."""
    import os
    chars = load_characters(project)
    files = {}
    try:
        for f in os.listdir(folder):
            stem, ext = os.path.splitext(f)
            if ext.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                files[stem.lower()] = os.path.join(folder, f)
    except OSError as e:
        raise CoopError("The folder could not be read: %s" % e) from None
    found, missing = 0, []
    for i, c in enumerate(chars["list"]):
        src = files.get(picture_file_name(c["name"]))
        if src:
            save_picture(project, i, src)
            found += 1
        else:
            missing.append(c["name"])
    return found, missing


# ---- PAD-1079: a video per character -------------------------------------------------------------------------------
# DoomWalrus666: "add videos". A character's video plays in its pick card's portrait frame: the card has a see-through
# window there, and the runtime loops the character's clip behind the HUD (the backdrop, in the city's place) while
# its card is on the glass. The clip is the owner's video placed where the window is on the glass, on black, at the
# size the bank's own clips are (:func:`window_clip`); a title whose port has no backdrop keeps the picture.

#: the video files a character's Video... takes
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv", ".mpg", ".mpeg")
#: a character's clip in the video bank (1-based)
CLIP_NAME = "PadCoopClip%d"
#: the portrait frame in the card (card pixels: x, y, w, h), where a video shows
PORTRAIT = (40, 84, 380, 306)
#: the glass the backdrop fills (the clip is stretched over it)
GLASS = (1360, 768)


def video_path(project, character):
    """The absolute path of *character*'s video in *project* (``""`` when it has none, or it is gone)."""
    return picture_path(project, {"picture": (character or {}).get("video") or ""})


def save_video(project, index, source=None):
    """Copy *source* (a video file) into the project as character *index*'s video, or with None forget it; returns
    the characters as stored. Raises :class:`CoopError` when the file is not a video the app takes."""
    import os
    import shutil
    chars = load_characters(project)
    if not 0 <= int(index) < len(chars["list"]):
        raise CoopError("There is no character %d." % (int(index) + 1))
    c = chars["list"][int(index)]
    if source is None:
        c["video"] = ""
        return save_characters(project, chars)
    ext = os.path.splitext(source)[1].lower()
    if ext not in VIDEO_EXTS or not os.path.isfile(source):
        raise CoopError("That is not a video the app can take (%s)." % ", ".join(VIDEO_EXTS))
    folder = os.path.join(project, PICTURE_DIR)
    os.makedirs(folder, exist_ok=True)
    stem = "character_%d_video" % (int(index) + 1)
    for f in os.listdir(folder):                        # one video a character: another extension's goes
        if os.path.splitext(f)[0] == stem and f != stem + ext:
            os.remove(os.path.join(folder, f))
    shutil.copyfile(source, os.path.join(folder, stem + ext))
    c["video"] = "%s/%s%s" % (PICTURE_DIR, stem, ext)
    return save_characters(project, chars)


def can_video(prof):
    """Whether *prof*'s port has the backdrop a character's video plays in (its ``backdrop_draw``)."""
    from . import mode_project as MP
    if prof is None or not getattr(prof, "port", None):
        return False
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return False
    return "backdrop_draw" in port["site"] and bool(port["data"].get("backdrop_city_vtable"))


def window_box(w, h):
    """The portrait window on a clip of w x h: ``(x, y, width, height)``, even numbers (the clip is stretched over
    the :data:`GLASS`)."""
    x, y, pw, ph = CARD_AT[0] + PORTRAIT[0], CARD_AT[1] + PORTRAIT[1], PORTRAIT[2], PORTRAIT[3]
    sx, sy = w / GLASS[0], h / GLASS[1]
    ev = lambda v: int(round(v / 2.0)) * 2                                    # noqa: E731
    return ev(x * sx), ev(y * sy), max(2, ev(pw * sx)), max(2, ev(ph * sy))


def window_clip(src, out, w, h, ffmpeg, max_seconds=None):
    """*src* made into a character's clip at *out*: w x h, black but for the portrait window, where the video covers
    it (cropped, never stretched), 30 fps, silent, no longer than a mode's clip."""
    import os
    from . import mode_assets as MA
    x, y, bw, bh = window_box(w, h)
    head, tail = MA._encode_args(ffmpeg, out)
    vf = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,pad=%d:%d:%d:%d:black,fps=%d"
          % (bw, bh, bw, bh, w, h, x, y, MA.FPS))
    cmd = head + ["-i", src, "-t", str(max_seconds or MA.MODE_CLIP_MAX_SECONDS), "-vf", vf] + tail
    r = _ffmpeg_run(cmd, "the clip of %s" % os.path.basename(src))
    if r.returncode != 0:
        raise CoopError("ffmpeg could not make the clip of %s: %s" % (src, (r.stderr or "").strip()[-300:]))
    return out


def clip_entries(project, characters=None):
    """``[(index, bank name, video path)]`` of the characters with a video (in order)."""
    chars = _characters(characters if characters is not None else load_characters(project))
    out = []
    for i, c in enumerate(chars["list"]):
        path = video_path(project, c)
        if path:
            out.append((i, CLIP_NAME % (i + 1), path))
    return out


# ---- PAD-1114: the co-op and team games' intro video ---------------------------------------------------------------
# DoomWalrus666 (Godzilla): "For co-op and team modes, I would like to have a custom intro video with its own sound.
# This video would be skippable by pressing both flippers. Once the video finishes, or both flipper buttons are pressed,
# the ball is put into the shooter Lane, and then language options, and then character select screen". The project
# keeps one video (``coop/intro_video.<ext>``, the characters record's ``intro``); a Write makes it into a clip of the
# video bank's size (:data:`INTRO_CLIP`, fitted whole, black round it) and its sound into a sound of the card's own
# (sound_modes "the co-op intro"), and coop.cfg names both (pad_mode_runtime.c "PAD-1114").
#: the intro's clip in the video bank
INTRO_CLIP = "PadCoopIntro"
#: the project's file (its extension the source's)
INTRO_FILE = "intro_video"
#: the longest intro a card takes (a mode's clip's longest)
INTRO_MAX_SECONDS = 300


def intro_path(project, characters=None):
    """The absolute path of the project's co-op intro video (``""`` when it has none, or it is gone)."""
    chars = _characters(characters) if characters is not None else load_characters(project)
    return picture_path(project, {"picture": chars.get("intro") or ""})


def save_intro(project, source=None):
    """Copy *source* (a video file) into the project as the co-op and team games' intro, or with None forget it;
    returns the characters as stored. Raises :class:`CoopError` when the file is not a video the app takes."""
    return _save_game_video(project, source, "intro", INTRO_FILE)


def _save_game_video(project, source, key, stem):
    """:func:`save_intro` / :func:`save_ceremony`: *source* copied into the pictures folder as *stem* and named in the
    characters' *key*, or with None forgotten."""
    import os
    import shutil
    chars = load_characters(project)
    if source is None:
        chars.pop(key, None)
        return save_characters(project, chars)
    ext = os.path.splitext(source)[1].lower()
    if ext not in VIDEO_EXTS or not os.path.isfile(source):
        raise CoopError("That is not a video the app can take (%s)." % ", ".join(VIDEO_EXTS))
    folder = os.path.join(project, PICTURE_DIR)
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):                        # one of each: another extension's goes
        if os.path.splitext(f)[0] == stem and f != stem + ext:
            os.remove(os.path.join(folder, f))
    shutil.copyfile(source, os.path.join(folder, stem + ext))
    chars[key] = "%s/%s%s" % (PICTURE_DIR, stem, ext)
    return save_characters(project, chars)


# ---- PAD-1219: the awards ceremony's background video --------------------------------------------------------------
# DoomWalrus666: "Please add an option in the Modes tab Character settings to add a custom awards ceremony background
# video". At a co-op game's end the award cards show over a clip that fills the glass, the game's HUD (score panel,
# power-up meter, credits line) off it (pad_mode_runtime.c "PAD-1219"): the game's own End of Ball Bonus loop, or this
# video of the owner's, made into a silent clip of the video bank's size (as the intro, :func:`intro_clip`) that loops
# for as long as the cards show. coop.cfg names it (``ceremony <clip> <crop>``).
#: the ceremony's clip in the video bank
CEREMONY_CLIP = "PadCoopCeremony"
#: the project's file (its extension the source's)
CEREMONY_FILE = "ceremony_video"


def ceremony_path(project, characters=None):
    """The absolute path of the project's awards ceremony video (``""`` when it has none, or it is gone)."""
    chars = _characters(characters) if characters is not None else load_characters(project)
    return picture_path(project, {"picture": chars.get("ceremony") or ""})


def save_ceremony(project, source=None):
    """Copy *source* (a video file) into the project as the co-op awards ceremony's background, or with None forget
    it (the game's own End of Ball Bonus loop goes behind the cards); returns the characters as stored."""
    return _save_game_video(project, source, "ceremony", CEREMONY_FILE)


#: PAD-1192: the longest any one co-op clip's or sound's ffmpeg run may take. Each is at most INTRO_MAX_SECONDS of
#: video made in seconds; a run past this is stuck (a looped input it cannot decode never ends) and a Write's Cancel
#: cannot reach into it, so it is stopped and the build says which file
FFMPEG_TIMEOUT = 600


def _ffmpeg_run(cmd, what):
    """*cmd* run with :data:`FFMPEG_TIMEOUT`; a run that does not end is killed and :class:`CoopError` names *what*."""
    import subprocess
    from . import mode_assets as MA
    try:
        return subprocess.run(cmd, capture_output=True, text=True, creationflags=MA._NO_WINDOW,
                              stdin=subprocess.DEVNULL, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise CoopError("ffmpeg was still making %s after %d minutes and was stopped - the file it reads may be "
                        "damaged: open it in an editor and save it again, or pick another"
                        % (what, FFMPEG_TIMEOUT // 60)) from None


def intro_clip(src, out, w, h, ffmpeg, max_seconds=None):
    """*src* made into the intro's clip at *out*: w x h, the whole picture fitted in (never cropped), black round it,
    30 fps, silent (its sound is :func:`intro_audio`'s), no longer than :data:`INTRO_MAX_SECONDS`."""
    import os
    from . import mode_assets as MA
    head, tail = MA._encode_args(ffmpeg, out)
    vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2,"
          "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black,fps=%d" % (w, h, w, h, MA.FPS))
    cmd = head + ["-i", src, "-t", str(max_seconds or INTRO_MAX_SECONDS), "-vf", vf] + tail
    r = _ffmpeg_run(cmd, "the intro's clip of %s" % os.path.basename(src))
    if r.returncode != 0:
        raise CoopError("ffmpeg could not make the intro's clip of %s: %s" % (src, (r.stderr or "").strip()[-300:]))
    return out


def intro_audio(src, out, ffmpeg, max_seconds=None):
    """The intro video *src*'s own sound as a 44.1 kHz 16-bit stereo WAV at *out* (the length its clip plays), or
    ``""`` when the video has no sound. Raises :class:`CoopError` when ffmpeg cannot read it."""
    import os
    probe = _ffmpeg_run([ffmpeg, "-v", "error", "-i", src, "-map", "0:a:0", "-t", "0.1", "-f", "null", "-"],
                        "the sound of %s" % os.path.basename(src))
    if probe.returncode != 0:
        return ""                                       # no sound stream in it
    cmd = [ffmpeg, "-v", "error", "-y", "-i", src, "-map", "0:a:0", "-t", str(max_seconds or INTRO_MAX_SECONDS),
           "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out]
    r = _ffmpeg_run(cmd, "the sound of %s" % os.path.basename(src))
    if r.returncode != 0:
        raise CoopError("ffmpeg could not take the sound out of %s: %s" % (src, (r.stderr or "").strip()[-300:]))
    return out


# ---- PAD-1123: a clip and a sound once a character is picked; the character on its teammate's End of Ball Bonus ------
# DoomWalrus666 (Godzilla): "After a player selects a character in co-op/teams play, I would like be able to select the
# following for each character: Play a sound of my choice (example: Godzilla roar from that specific era); Show a brief
# couple second video (like the characters original movie poster)" and "At the end of a players ball, I would like to be
# able to display that players selected Character's image or video in a window on the End of Ball screen, maybe to the
# right of the scores/username". A character keeps a clip (a video, or a picture the build shows for
# :data:`PICKED_STILL_SECONDS`) and a sound (any audio file, or a video's sound); a Write makes the clip full-screen in the
# video bank (:data:`PICKED_CLIP`, fitted whole like the intro) and the sound a sound of the card's own on the intro's
# carrier, and the runtime plays both when the character is picked (pad_mode_runtime.c "PAD-1123"). With ``bonus`` on,
# the build makes the game's own End of Ball Bonus loop again per character with its picture (or video) in a window to the
# right of the bonus's words (:data:`BONUS_CLIP`), and the runtime plays the copy of the teammate up's character when the
# game asks for its loop.
#: a character's picked clip in the video bank (1-based)
PICKED_CLIP = "PadCoopPicked%d"
#: the project's files (their extension the source's)
PICKED_FILE = "character_%d_picked"
PICKED_SOUND_FILE = "character_%d_picked_sound"
#: the longest picked clip and sound a card takes ("a brief couple second video")
PICKED_MAX_SECONDS = 10
#: a picture as the picked clip shows this long (or as long as its sound, up to PICKED_MAX_SECONDS)
PICKED_STILL_SECONDS = 3
#: the sound files a character's Sound... takes (a video's own sound too)
SOUND_EXTS = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus")
#: a character's copy of the bonus loop in the video bank (1-based)
BONUS_CLIP = "PadCoopBonus%d"
#: the window on the glass (x, y, w, h), the portrait frame's shape: right of the bonus's summary (Godzilla LE 1.16,
#: emulator census, a frame every 0.75 s: PLAYER 1 - the Insider name there when logged in -, TOTAL BONUS and TOTAL
#: SCORE run x 425-940, y 140-665). The count's widest lines (GODZILLA POWERUP EARNED, x 135-1230) are drawn over the
#: window's left part, outlined as always: no window this size clears them
BONUS_WINDOW = (964, 236, 360, 290)
#: its frame, glass pixels
BONUS_BORDER = 5


def picked_clip_path(project, character):
    """The absolute path of *character*'s picked clip (a video or a picture) in *project* (``""``: none, or gone)."""
    return picture_path(project, {"picture": (character or {}).get("picked_clip") or ""})


def picked_sound_path(project, character):
    """The absolute path of *character*'s picked sound file in *project* (``""``: none, or gone)."""
    return picture_path(project, {"picture": (character or {}).get("picked_sound") or ""})


def MA_check_picture(src):                              # noqa: N802 - mode_assets.check_picture, imported late
    """*src* decodes whole, or an exception says why (PAD-1192: ``verify()`` let a PNG with damaged data in)."""
    from . import mode_assets as MA
    MA.check_picture(src)


def is_still(path):
    """Whether *path* is a picture (a still picked clip), by its extension."""
    import os
    return os.path.splitext(str(path))[1].lower() in _PICTURE_EXTS


def _save_char_file(project, index, source, field, stem, exts, what):
    import os
    import shutil
    chars = load_characters(project)
    if not 0 <= int(index) < len(chars["list"]):
        raise CoopError("There is no character %d." % (int(index) + 1))
    c = chars["list"][int(index)]
    folder = os.path.join(project, PICTURE_DIR)
    stem = stem % (int(index) + 1)
    if source is not None:
        ext = os.path.splitext(source)[1].lower()
        if ext not in exts or not os.path.isfile(source):
            raise CoopError("That is not %s the app can take (%s)." % (what, ", ".join(exts)))
    if os.path.isdir(folder):
        for f in os.listdir(folder):                    # one a character: another extension's goes
            if os.path.splitext(f)[0] == stem and (source is None or f != stem + os.path.splitext(source)[1].lower()):
                os.remove(os.path.join(folder, f))
    if source is None:
        c[field] = ""
        return save_characters(project, chars)
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(source)[1].lower()
    shutil.copyfile(source, os.path.join(folder, stem + ext))
    c[field] = "%s/%s%s" % (PICTURE_DIR, stem, ext)
    return save_characters(project, chars)


def save_picked_clip(project, index, source=None):
    """Copy *source* (a video, or a picture) into the project as what plays full screen once character *index* is
    picked, or with None forget it; returns the characters as stored. Raises :class:`CoopError` on another file."""
    if source is not None and is_still(source):
        try:
            MA_check_picture(source)
        except Exception as e:                          # noqa: BLE001 - say what the file is not
            raise CoopError("That file is not a picture the app can read (%s)." % e) from None
    return _save_char_file(project, index, source, "picked_clip", PICKED_FILE, VIDEO_EXTS + _PICTURE_EXTS,
                           "a video or picture")


def save_picked_sound(project, index, source=None):
    """Copy *source* (a sound file, or a video whose sound is taken) into the project as the sound character *index*
    plays once picked, or with None forget it; returns the characters as stored."""
    return _save_char_file(project, index, source, "picked_sound", PICKED_SOUND_FILE, SOUND_EXTS + VIDEO_EXTS,
                           "a sound file")


def save_bonus(project, on):
    """Whether each teammate's character shows on their End of Ball Bonus; returns the characters as stored."""
    chars = load_characters(project)
    if on:
        chars["bonus"] = True
    else:
        chars.pop("bonus", None)
    return save_characters(project, chars)


def picked_sound_source(project, character):
    """The file *character*'s picked sound comes from: its sound file, else its picked clip when that is a video (the
    video's own sound; the build finds whether it has one), else ``""``."""
    snd = picked_sound_path(project, character)
    if snd:
        return snd
    clip = picked_clip_path(project, character)
    return clip if clip and not is_still(clip) else ""


def picked_entries(project, characters=None):
    """``[(index, bank name, clip source)]`` of the characters with a picked clip (in order)."""
    chars = _characters(characters if characters is not None else load_characters(project))
    out = []
    for i, c in enumerate(chars["list"]):
        path = picked_clip_path(project, c)
        if path:
            out.append((i, PICKED_CLIP % (i + 1), path))
    return out


def media_seconds(path, ffmpeg):
    """The length of the sound or video at *path* in seconds (0.0 when ffmpeg cannot tell)."""
    import re
    import subprocess
    from . import mode_assets as MA
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True,
                           creationflags=MA._NO_WINDOW, stdin=subprocess.DEVNULL, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def _clean_still(picture, out):
    """PAD-1192: *picture* as a plain PNG beside *out* for ffmpeg's looped still input (mode_assets.clean_still:
    a picture ffmpeg cannot decode looped forever and hung the build); :class:`CoopError` when it does not read."""
    from . import mode_assets as MA
    try:
        return MA.clean_still(picture, out + ".still.png")
    except ValueError as e:
        raise CoopError(str(e)) from None


def _drop(path):
    import os
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def picked_clip(src, out, w, h, ffmpeg, seconds=None):
    """*src* made into a character's picked clip at *out*: w x h, the whole picture fitted in, black round it, 30 fps,
    silent (its sound is the build's), no longer than :data:`PICKED_MAX_SECONDS`. A picture shows *seconds*
    (:data:`PICKED_STILL_SECONDS` when None), a still that reads as video to the bank."""
    import os
    from . import mode_assets as MA
    head, tail = MA._encode_args(ffmpeg, out)
    vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2,"
          "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black,fps=%d,format=yuv420p" % (w, h, w, h, MA.FPS))
    still = ""
    if is_still(src):
        t = min(float(seconds or PICKED_STILL_SECONDS), PICKED_MAX_SECONDS)
        still = _clean_still(src, out)
        cmd = head + ["-loop", "1", "-framerate", str(MA.FPS), "-i", still, "-t", "%.3f" % t, "-vf", vf] + tail
    else:
        cmd = head + ["-i", src, "-t", str(PICKED_MAX_SECONDS), "-vf", vf] + tail
    try:
        r = _ffmpeg_run(cmd, "the picked clip of %s" % os.path.basename(src))
    finally:
        _drop(still)
    if r.returncode != 0:
        raise CoopError("ffmpeg could not make the picked clip of %s: %s" % (src, (r.stderr or "").strip()[-300:]))
    return out


def picked_audio(src, out, ffmpeg):
    """*src*'s sound (a sound file, or a video's own) as a 44.1 kHz 16-bit stereo WAV at *out*, no longer than
    :data:`PICKED_MAX_SECONDS`; ``""`` when it has none. Raises :class:`CoopError` when ffmpeg cannot read it."""
    return intro_audio(src, out, ffmpeg, max_seconds=PICKED_MAX_SECONDS)


def bonus_loop(bank_data, bank=None):
    """``(the game's End of Ball Bonus loop's name, the crop the game plays it at)`` in the video bank *bank_data*, or
    None when the bank has none. Found by its name (Godzilla 1.15/1.16: EndOfBallBonus_BackgroundLoop, at SquareCrop -
    emulator, the backdrop's record of the game's own loop)."""
    from . import video_bank as VB
    bank = bank or VB.parse(bank_data)
    names = [c.name for c in bank.library.entries]
    got = [n for n in names if n.lower().replace("_", "").startswith("endofballbonus") and "loop" in n.lower()]
    if not got:
        return None
    labels = dict(bank.labels)
    return got[0], "SquareCrop" if "SquareCrop" in labels else "Normal"


def bonus_box(transform, w, h):
    """:data:`BONUS_WINDOW` (on the glass) in the loop's own pixels on a clip of w x h, through the crop's
    *transform* (:func:`.video_bank.crop_transform`'s 16 floats; None: Normal): ``(x, y, width, height)``, even. The
    clip is stretched over the :data:`GLASS`, then the crop scales and moves it."""
    sx, sy, tx, ty = (transform[0], transform[5], transform[12], transform[13]) if transform else (1.0, 1.0, 0.0, 0.0)
    ev = lambda v: int(round(v / 2.0)) * 2                                    # noqa: E731
    gx, gy, gw, gh = BONUS_WINDOW
    kx, ky = w / GLASS[0], h / GLASS[1]
    return (ev((gx - tx) / sx * kx), ev((gy - ty) / sy * ky), max(2, ev(gw / sx * kx)), max(2, ev(gh / sy * ky)))


def bonus_clip(loop_src, out, box, ffmpeg, picture="", video="", colour="#ffb400", seconds=None, size=(1360, 768)):
    """The game's bonus loop *loop_src* (at *size*, the bank's clip frame: an owner's replacement of another size is
    scaled to it first) made again at *out* with a character's *video* (looped) or *picture* in a window at *box* (the
    loop's pixels, :func:`bonus_box`), framed in *colour*, as long as the loop (or *seconds*), 30 fps, silent."""
    import os
    from . import mode_assets as MA
    x, y, bw, bh = box
    b = max(2, int(round(BONUS_BORDER * bw / BONUS_WINDOW[2])))
    head, tail = MA._encode_args(ffmpeg, out)
    if video:
        src = ["-stream_loop", "-1", "-i", video]
    elif picture:
        still = _clean_still(picture, out)
        src = ["-loop", "1", "-framerate", str(MA.FPS), "-i", still]
    else:
        raise CoopError("a bonus window needs the character's picture or video")
    col = "0x" + clean_colour(colour).lstrip("#") if clean_colour(colour) else "0xffb400"
    fc = ("[1:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,fps=%d[w];"
          "[0:v]scale=%d:%d,setsar=1,fps=%d,drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=fill[b];"
          "[b][w]overlay=%d:%d:shortest=0:eof_action=repeat,format=yuv420p[v]"
          % (bw, bh, bw, bh, MA.FPS, size[0], size[1], MA.FPS, x - b, y - b, bw + 2 * b, bh + 2 * b, col, x, y))
    t = seconds or media_seconds(loop_src, ffmpeg) or 8.0
    cmd = head + ["-i", loop_src] + src + ["-filter_complex", fc, "-map", "[v]", "-t", "%.3f" % t] + tail
    try:
        r = _ffmpeg_run(cmd, "the bonus window's clip of %s" % os.path.basename(video or picture))
    finally:
        _drop(src[-1] if picture and not video else "")
    if r.returncode != 0:
        raise CoopError("ffmpeg could not make the bonus window's clip: %s" % (r.stderr or "").strip()[-300:])
    return out


def bonus_entries(project, characters=None):
    """``[(index, bank name, picture path, video path)]`` of the characters whose End of Ball Bonus shows them (with
    ``bonus`` on): each with a picture or a video (the video wins)."""
    chars = _characters(characters if characters is not None else load_characters(project))
    if not chars.get("bonus"):
        return []
    out = []
    for i, c in enumerate(chars["list"]):
        pic, vid = picture_path(project, c), video_path(project, c)
        if pic or vid:
            out.append((i, BONUS_CLIP % (i + 1), pic, vid))
    return out


def video_still(project, character, ffmpeg=None):
    """The first frame of *character*'s video (half a second in) as an RGBA PIL image - the dialog's preview - or
    None."""
    import os
    import subprocess
    import tempfile
    from PIL import Image
    path = video_path(project, character)
    if not path:
        return None
    if ffmpeg is None:
        from ...core.audio import find_ffmpeg
        ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    from . import mode_assets as MA
    fd, png = tempfile.mkstemp(suffix=".png", prefix="spike2_coopvid_")
    os.close(fd)
    try:
        for args in (["-ss", "0.5", "-i", path], ["-i", path]):            # a clip under half a second: its first
            r = subprocess.run([ffmpeg, "-v", "error", "-y"] + args + ["-frames:v", "1", png],
                               capture_output=True, creationflags=MA._NO_WINDOW)
            if r.returncode == 0 and os.path.getsize(png):
                with Image.open(png) as im:
                    return im.convert("RGBA")
        return None
    except OSError:
        return None
    finally:
        try:
            os.remove(png)
        except OSError:
            pass


def save_picture(project, index, source):
    """Copy *source* (a picture file) into the project for character *index* and name it there; returns the
    characters as stored. Raises :class:`CoopError` when the file is not a picture."""
    import os
    import shutil
    try:
        MA_check_picture(source)
    except Exception as e:                              # noqa: BLE001 - say what the file is not
        raise CoopError("That file is not a picture the app can read (%s)." % e) from None
    chars = load_characters(project)
    if not 0 <= int(index) < len(chars["list"]):
        raise CoopError("There is no character %d." % (int(index) + 1))
    folder = os.path.join(project, PICTURE_DIR)
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(source)[1].lower() or ".png"
    name = "character_%d%s" % (int(index) + 1, ext)
    shutil.copyfile(source, os.path.join(folder, name))
    chars["list"][int(index)]["picture"] = "%s/%s" % (PICTURE_DIR, name)
    return save_characters(project, chars)


def save_look(project, key, value):
    """PAD-1079: one part of the pick's look (a :data:`THEME` key but ``backdrop``: :func:`save_backdrop`) set to
    *value* (``""`` or None: the default again); returns the characters as stored. Raises :class:`CoopError` on a
    colour that is not ``#rrggbb`` or a key that is not one."""
    if key not in THEME or key == "backdrop":
        raise CoopError("The pick's look has no %s." % key)
    chars = load_characters(project)
    theme = dict(chars.get("theme") or {})
    if value is None or value == "":
        theme.pop(key, None)
    elif key == "title":
        theme[key] = clean_title(value)
    elif key == "dim":
        if str(value) not in {str(d) for d in DIMS}:
            raise CoopError("The background can be darkened by %s percent." % ", ".join(str(d) for d in DIMS))
        theme[key] = int(value)
    elif clean_colour(value):
        theme[key] = clean_colour(value)
    else:
        raise CoopError("%r is not a colour (#rrggbb)." % value)
    chars["theme"] = {k: v for k, v in theme.items() if v not in (None, "")}
    return save_characters(project, chars)


def save_look_default(project):
    """PAD-1079: the pick's look as the game's set (or the app's) has it: the owner's colours, title and background
    forgotten; returns the characters as stored."""
    chars = load_characters(project)
    prof = project_title(project)
    path = preset_for(prof)
    chars["theme"] = dict(read_preset(path)["characters"].get("theme") or {}) if path else {}
    return save_characters(project, chars)


def save_backdrop(project, source=None):
    """PAD-1079: copy *source* (a picture file) into the project as the pick's background picture (its cards and
    the award cards), or with None forget it; returns the characters as stored. Raises :class:`CoopError` when the
    file is not a picture."""
    import os
    import shutil
    chars = load_characters(project)
    theme = dict(chars.get("theme") or {})
    if source is None:
        theme.pop("backdrop", None)
    else:
        try:
            MA_check_picture(source)
        except Exception as e:                          # noqa: BLE001 - say what the file is not
            raise CoopError("That file is not a picture the app can read (%s)." % e) from None
        folder = os.path.join(project, PICTURE_DIR)
        os.makedirs(folder, exist_ok=True)
        name = BACKDROP_FILE + (os.path.splitext(source)[1].lower() or ".png")
        for f in os.listdir(folder):                    # one background: another extension's goes
            if os.path.splitext(f)[0] == BACKDROP_FILE and f != name:
                os.remove(os.path.join(folder, f))
        shutil.copyfile(source, os.path.join(folder, name))
        theme["backdrop"] = "%s/%s" % (PICTURE_DIR, name)
    chars["theme"] = theme
    return save_characters(project, chars)


def preview(project, characters=None, words_for=None, index=0, videos=None):
    """A still of what the machine shows while the pick is on character *index* (RANDOM after the last): its
    screen on a dark glass of the HUD's size, as PNG bytes - the Characters dialog's preview. PAD-1079: a character
    with a video shows its first frame in the window (*videos*: as :func:`pick_screens`)."""
    import io

    import numpy as np
    from PIL import Image
    from . import mode_assets as MA
    chars = _characters(characters if characters is not None else load_characters(project))
    if not chars["list"]:
        return b""
    index = max(0, min(int(index), len(chars["list"])))           # only the one card: a click redraws in a moment
    c = chars["list"][index] if index < len(chars["list"]) else None
    if videos is None:
        videos = bool(c and video_path(project, c)) and can_video(project_title(project))
    s = {"art_rgba": pick_card(project, chars, index, words_for, chars.get("theme"), window=videos),
         "x": CARD_AT[0], "y": CARD_AT[1]}
    glass = Image.new("RGBA", (1360, 768), (40, 34, 58, 255))
    from PIL import ImageDraw
    d = ImageDraw.Draw(glass)
    d.rounded_rectangle((470, -20, 890, 76), radius=18, fill=(30, 30, 36, 255))     # the game's top bar
    secs = chars["time"]
    d.text((680, 30), "PLAYER 1 PICK  %d" % secs if secs else "PLAYER 1 PICK", fill=(255, 255, 255, 255),
           anchor="mm", font=MA._font(26))
    for k in range(4):                                                            # its score panels
        d.rounded_rectangle((30 + k * 330, 612, 330 + k * 330, 760), radius=14, fill=(26, 26, 30, 255))
    still = video_still(project, c) if videos and c else None
    if still is not None:                       # PAD-1079: the clip behind the card, where its window is
        x, y, bw, bh = window_box(*GLASS)
        glass.paste(_cover(still, bw, bh).convert("RGBA"), (x, y))
    art = Image.fromarray(np.asarray(s["art_rgba"], dtype=np.uint8), "RGBA")
    # the card is premultiplied (the game blends so): over the glass as the game draws it
    under = np.asarray(glass, dtype=np.uint16)
    a = np.asarray(art, dtype=np.uint16)
    x0, y0 = int(s["x"]), int(s["y"])
    region = under[y0:y0 + a.shape[0], x0:x0 + a.shape[1], :3]
    region[...] = a[..., :3] + region * (255 - a[..., 3:4]) // 255
    glass = Image.fromarray(under.astype(np.uint8), "RGBA")
    if secs:                                    # PAD-1044: the runtime's countdown, where its words line puts it
        d = ImageDraw.Draw(glass)
        d.text((int(s["x"]) + TIMER_TEXT_X, int(s["y"]) + TIMER_WORDS_AT[1]), str(secs), fill=(255, 255, 255, 255),
               anchor="mm", font=MA._font(30))
    del MA
    buf = io.BytesIO()
    glass.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


# ---- PAD-1031: the pick's card design ---------------------------------------------------------------------------------
# David: "a much better stylized design ... production quality". Each pick screen is one finished card the size of the
# glass between the game's top bar and its score panels: a themed header, the character's portrait in a lit frame,
# its name in a heavy display face, its ability as a badge with what it does, the whole roster as a strip with this
# one lit, and how to choose. Drawn at 2x and scaled down (smooth edges); the picture is the owner's, never the app's.

#: where the card sits on the 1360x768 glass: under the top bar, above the score panels
CARD_AT = (40, 86)
CARD_SIZE = (1280, 516)
#: PAD-1044: the box in the card's header (card pixels) the runtime's words line counts down in, then says PICKED; a
#: clock at its left. The game centres the line on its words box (scene_write.screen: (0, -40) .. (card width, 48),
#: scaled about words_at) with its middle at words_at's y, and draws a short line at about 32 px capitals per unit of
#: scale (emulator, Godzilla LE 1.16: "16" 52 px tall and PICKED 345 px wide at 1.6): at 0.8 the seconds are about
#: 26 px tall and PICKED about 172 px wide, inside the box beside the clock
TIMER_BOX = (880, 20, 1120, 68)
TIMER_TEXT_X = 1025
TIMER_WORDS_SCALE = 0.8
TIMER_WORDS_AT = (round(TIMER_TEXT_X - CARD_SIZE[0] / 2 * TIMER_WORDS_SCALE, 1),
                  float((TIMER_BOX[1] + TIMER_BOX[3]) // 2))
#: the default look; a preset may give its own ("theme": {"title", "accent", "accent2"}). PAD-1079 (DoomWalrus666: "change
#: the colors of certain text ... other alterations"): the owner's Look in the Characters dialog, a colour for each
#: text and the panel ("" for sub/badge/count: the frame's colour, for panel: the stock wash), a background picture
#: (``backdrop``, the project's file) darkened by ``dim`` percent so the words stay readable
THEME = {"title": "CHOOSE YOUR CHARACTER", "accent": "#ffb400", "accent2": "#ff5a1f", "heading": "#ffffff",
         "name": "#ffffff", "sub": "", "badge": "", "badge_text": "#0c0c12", "does": "#dee4f0", "help": "#ffffff",
         "count": "", "panel": "", "backdrop": "", "dim": 40}
#: PAD-1079: the Look's colours, in the dialog's order: (theme key, what it colours)
COLOUR_ROLES = (("accent", "Frame and lights"), ("accent2", "Corners and arrows"), ("heading", "Title"),
                ("count", "Count (01 / 11)"), ("name", "Name"), ("sub", "Sub header"), ("badge", "Ability badge"),
                ("badge_text", "Badge words"), ("does", "What it does"), ("help", "How to choose"),
                ("panel", "Panel"))
#: the stock panel's colour as the Look shows it (the wash runs either side of it)
PANEL_STOCK = "#141420"
#: the background picture's darkening choices, percent
DIMS = (0, 20, 40, 60, 80)
#: the background picture's file in the project's PICTURE_DIR (its extension the source's)
BACKDROP_FILE = "backdrop"
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
_DISPLAY_FONTS = (r"C:\Windows\Fonts\impact.ttf", "/System/Library/Fonts/Supplemental/Impact.ttf",
                  r"C:\Windows\Fonts\ariblk.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
_TEXT_FONTS = (r"C:\Windows\Fonts\arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
               "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _face(paths, size):
    import os
    from PIL import ImageFont
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _fit(draw, text, paths, max_w, start, least=14):
    size = start
    while size > least:
        f = _face(paths, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _face(paths, least)


def _hex(c, a=255):
    c = str(c).lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a)


def clean_title(title):
    """The pick's title as its cards show it: capitals, one space between words, at most 40."""
    return " ".join(str(title or "").upper().split())[:40]


def clean_colour(colour):
    """``#rrggbb`` in lower case, or ``""`` when *colour* is not one."""
    c = str(colour or "").strip()
    return c.lower() if _COLOUR.match(c) else ""


def theme_of(theme=None):
    """The card's look: :data:`THEME` with a preset's (or the owner's, PAD-1079) own over it; a colour that is not
    ``#rrggbb`` and a darkening not in :data:`DIMS` are left at the default."""
    t = dict(THEME)
    for k, v in (theme or {}).items():
        if k not in THEME or v is None or v == "":
            continue
        if k == "title":
            t[k] = clean_title(v) or THEME[k]
        elif k == "backdrop":
            t[k] = str(v)
        elif k == "dim":
            try:
                t[k] = int(v) if int(v) in DIMS else THEME[k]
            except (TypeError, ValueError):
                pass
        elif clean_colour(v):
            t[k] = clean_colour(v)
    return t


def backdrop_path(project, theme=None):
    """PAD-1079: the absolute path of the pick's background picture in *project* (``""`` when it has none)."""
    return picture_path(project, {"picture": theme_of(theme)["backdrop"]})


def _body(project, th, W, H, S):
    """The card's opaque body, W x H: the owner's background picture (covering it, darkened by ``dim``), else a wash
    in the panel's colour (the stock one: cold to warm) with a fine grid a shade off it."""
    from PIL import Image, ImageDraw
    path = backdrop_path(project, th)
    if path:
        with Image.open(path) as im:
            pic = _cover(im.convert("RGBA"), W, H)
        body = Image.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 255)), pic)
        if th["dim"]:
            body = Image.alpha_composite(body, Image.new("RGBA", (W, H), (0, 0, 0, round(255 * th["dim"] / 100))))
        return body
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    p = _hex(th["panel"]) if th["panel"] else None
    for y in range(H):
        t = y / H
        bd.line([(0, y), (W, y)], fill=(int(10 + 16 * t), int(12 + 6 * t), int(20 + 10 * (1 - t)), 255) if p is None
                else tuple(int(v * (0.7 + 0.3 * t)) for v in p[:3]) + (255,))
    grid = (30, 34, 48, 255) if p is None else tuple(min(255, v + 18) for v in p[:3]) + (255,)
    for x in range(0, W, 28 * S):                                # the grid: drawn opaque, a shade off the body
        bd.line([(x, 0), (x, H)], fill=grid, width=S)
    for y in range(0, H, 28 * S):
        bd.line([(0, y), (W, y)], fill=grid, width=S)
    return body


_TAG_SKIP = {"VS", "VS.", "AND", "THE", "OF", "&"}


def tag_of(name, roster=()):
    """A short tag for a monogram or a roster tile: the words that set *name* apart from the rest of the *roster*
    (GODZILLA GMK -> GMK, GODZILLA VS MECHAGODZILLA -> MECHA, DESTROY ALL MONSTERS -> DAM)."""
    names = [str(n).upper().split() for n in roster] or [[]]
    common = {w for w in set(sum(names, [])) if sum(w in n for n in names) * 2 > len(names)}
    words = [w for w in str(name).upper().split() if w not in common and w not in _TAG_SKIP] or \
        [w for w in str(name).upper().split() if w not in _TAG_SKIP] or ["?"]
    if len(words) == 1:
        w = words[0]
        return w if len(w) <= 5 else (w[:5] if w.startswith("MECHA") else w[:4])
    return "".join(w[:1] for w in words[:3])


def _cover(img, w, h):
    """*img* scaled to cover w x h, centred, cropped."""
    from PIL import Image
    s = max(w / img.width, h / img.height)
    im = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    x, y = (im.width - w) // 2, int((im.height - h) * 0.12)   # keep heads: nearly all the crop off the foot
    return im.crop((x, y, x + w, y + h))


def _glow(img, box, radius, color, blur, width):
    """*img* with a soft coloured outline round *box* (a lit frame), blurred in its own patch only."""
    from PIL import Image, ImageDraw, ImageFilter
    m = int(blur * 3 + width)
    x0, y0 = max(0, int(box[0]) - m), max(0, int(box[1]) - m)
    x1, y1 = min(img.width, int(box[2]) + m), min(img.height, int(box[3]) + m)
    layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0), radius=radius,
                                            outline=color, width=width)
    patch = img.crop((x0, y0, x1, y1))
    img.paste(Image.alpha_composite(patch, layer.filter(ImageFilter.GaussianBlur(blur))), (x0, y0))
    return img


def _wrap(draw, text, font, width, lines):
    out, cur = [], ""
    for word in str(text).split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            if cur:
                out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        while out[-1] and draw.textlength(out[-1] + "...", font=font) > width:
            out[-1] = out[-1].rsplit(" ", 1)[0] if " " in out[-1] else out[-1][:-1]
        out[-1] += "..."
    return out


def _portrait(project, character, w, h, accent, accent2):
    """The character's portrait: the owner's picture, covering the frame; without one a monogram plate."""
    from PIL import Image, ImageDraw, ImageFilter
    path = picture_path(project, character) if character else ""
    if path:
        with Image.open(path) as im:
            src = im.convert("RGBA")
        pic = _cover(src, w, h)                                  # fills the frame; a tall still keeps its head
        shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for i in range(h // 3):                                  # a dark fade at the foot, as a poster's
            a = int(170 * (1 - i / (h / 3)) ** 1.6)
            sd.line([(0, h - 1 - i), (w, h - 1 - i)], fill=(0, 0, 0, a))
        return Image.alpha_composite(pic, shade)
    plate = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    pd = ImageDraw.Draw(plate)
    a1, a2 = _hex(accent), _hex(accent2)
    for y in range(h):                                           # a deep diagonal wash in the theme's colours
        t = y / h
        pd.line([(0, y), (w, y)], fill=(int(8 + a2[0] * 0.18 * t), int(10 + a2[1] * 0.10 * t), int(16 + a1[2] * 0.22 * (1 - t)), 255))
    for x in range(-h, w, 18):                                   # fine hatching
        pd.line([(x, h), (x + h, 0)], fill=(255, 255, 255, 10), width=2)
    ring = min(w, h) * 0.36
    cx, cy = w / 2, h * 0.46
    pd.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=a1[:3] + (200,), width=max(4, w // 90))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=a1[:3] + (160,), width=w // 40)
    plate = Image.alpha_composite(plate, glow.filter(ImageFilter.GaussianBlur(w // 50)))
    pd = ImageDraw.Draw(plate)
    mono = "?" if character is None else (character.get("tag") or tag_of(character["name"]))
    f = _fit(pd, mono, _DISPLAY_FONTS, ring * 1.5, int(ring * 1.25))
    pd.text((cx, cy), mono, font=f, fill=(255, 255, 255, 235), anchor="mm")
    return plate


def _card_lines(draw, text, width, S):
    """PAD-1075: the pick card's words for what a character does: ``(font, lines, line step)``, two lines at 27 (or
    24) px, else three at 21 px (DoomWalrus666's lines run to three sentences), the third cut with ... past that."""
    for size, lines in ((27, 2), (24, 2), (21, 3)):
        f = _face(_TEXT_FONTS, size * S)
        got = _wrap(draw, text, f, width, lines)
        if not got or not got[-1].endswith("...") or size == 21:
            return f, got, int(size * 1.4) * S


def pick_card(project, characters, index, words_for=None, theme=None, scale=2, window=False):
    """The pick's card for character *index* (``len(list)`` = RANDOM) as an RGBA array of :data:`CARD_SIZE`. PAD-1079:
    with *window*, a character with a video has its portrait frame see-through inside its lit edge (its clip plays
    behind the HUD there)."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    timed = bool(_characters(characters)["time"])
    chars = [dict(c) for c in _characters(characters)["list"]]
    for c_ in chars:
        c_["tag"] = tag_of(c_["name"], [x["name"] for x in chars])
    th = theme_of(theme)
    S = scale
    W, H = CARD_SIZE[0] * S, CARD_SIZE[1] * S
    n = len(chars)
    rnd = index >= n
    c = None if rnd else chars[index]
    acc, acc2 = (c or {}).get("colour") or th["accent"], th["accent2"]     # PAD-1079: a character's own frame colour
    A, A2 = _hex(acc), _hex(acc2)
    ink = {k: _hex(th[k] or acc) for k in ("heading", "count", "name", "sub", "badge", "badge_text", "does")}
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # the panel: a near-black body with a cold-to-warm wash, a fine grid (or the owner's background picture), a lit
    # border and corner brackets
    body = _body(project, th, W, H, S)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=26 * S, fill=255)
    img.paste(body, (0, 0), mask)
    img = _glow(img, (4 * S, 4 * S, W - 5 * S, H - 5 * S), 24 * S, A[:3] + (200,), 6 * S, 4 * S)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((3 * S, 3 * S, W - 4 * S, H - 4 * S), radius=25 * S, outline=A[:3] + (255,), width=3 * S)
    d.rounded_rectangle((12 * S, 12 * S, W - 13 * S, H - 13 * S), radius=18 * S, outline=(255, 255, 255, 40), width=S)
    L = 46 * S
    for (x, y, dx, dy) in ((14, 14, 1, 1), (W // S - 15, 14, -1, 1), (14, H // S - 15, 1, -1), (W // S - 15, H // S - 15, -1, -1)):
        x, y = x * S, y * S
        d.line([(x, y), (x + dx * L, y)], fill=A2[:3] + (255,), width=5 * S)
        d.line([(x, y), (x, y + dy * L)], fill=A2[:3] + (255,), width=5 * S)
    # the header: the title, a rule, and where in the roster this one is
    hf = _fit(d, th["title"], _DISPLAY_FONTS, W * 0.62, 46 * S)
    d.text((40 * S, 44 * S), th["title"], font=hf, fill=ink["heading"], anchor="lm")
    tw = d.textlength(th["title"], font=hf)
    rule_end = (TIMER_BOX[0] - 18) * S if timed else W - 190 * S
    if rule_end > 40 * S + tw + 18 * S:
        d.line([(40 * S + tw + 18 * S, 44 * S), (rule_end, 44 * S)], fill=A[:3] + (150,), width=2 * S)
    if timed:                       # PAD-1044: the box the runtime counts the seconds down in, a clock at its left
        x0, y0, x1, y1 = (v * S for v in TIMER_BOX)
        d.rounded_rectangle((x0, y0, x1, y1), radius=(y1 - y0) // 2, fill=(6, 8, 14, 255), outline=A2[:3] + (255,),
                            width=3 * S)
        cx, cy, r = x0 + 30 * S, (y0 + y1) // 2, 13 * S
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 230), width=3 * S)
        d.line([(cx, cy), (cx, cy - 8 * S)], fill=(255, 255, 255, 230), width=3 * S)
        d.line([(cx, cy), (cx + 6 * S, cy + 3 * S)], fill=(255, 255, 255, 230), width=3 * S)
    count = "?? / %02d" % n if rnd else "%02d / %02d" % (index + 1, n)
    cf = _face(_DISPLAY_FONTS, 34 * S)
    d.text((W - 40 * S, 44 * S), count, font=cf, fill=ink["count"], anchor="rm")
    # the portrait, in a lit frame
    px, py, pw, ph = 40 * S, 84 * S, 380 * S, 306 * S
    img = _glow(img, (px - 4 * S, py - 4 * S, px + pw + 4 * S, py + ph + 4 * S), 16 * S, A[:3] + (230,), 10 * S, 6 * S)
    por = _portrait(project, c, pw, ph, acc, acc2)
    pm = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(pm).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=14 * S, fill=255)
    img.paste(por, (px, py), pm)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((px, py, px + pw - 1, py + ph - 1), radius=14 * S, outline=A[:3] + (255,), width=3 * S)
    # the name, the ability badge, what it does
    ix, iw = px + pw + 44 * S, W - (px + pw + 44 * S) - 44 * S
    mark = "?" if rnd else c["tag"]                              # the tag, huge and faint, behind the words
    wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wf = _fit(ImageDraw.Draw(wm), mark, _DISPLAY_FONTS, iw * 0.9, 300 * S, 60 * S)
    ImageDraw.Draw(wm).text((W - 50 * S, 250 * S), mark, font=wf, fill=A[:3] + (15,), anchor="rm")
    img = Image.alpha_composite(img, wm)
    d = ImageDraw.Draw(img)
    name = "RANDOM" if rnd else c["name"]
    sub = "" if rnd else c.get("sub", "")
    ny = (150 if sub else 166) * S                  # PAD-1056: a sub header under the name lifts the name a little
    nf = _fit(d, name, _DISPLAY_FONTS, iw, (80 if sub else 92) * S, 30 * S)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((ix + 4 * S, ny + 5 * S), name, font=nf, fill=(0, 0, 0, 220), anchor="ls")
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(4 * S)))
    d = ImageDraw.Draw(img)
    d.text((ix, ny), name, font=nf, fill=ink["name"], anchor="ls",
           stroke_width=max(1, S), stroke_fill=(0, 0, 0, 255))
    nw = min(iw - 40 * S, d.textlength(name, font=nf))
    d.rectangle((ix, ny + 14 * S, ix + nw, ny + 20 * S), fill=A[:3] + (255,))
    d.rectangle((ix + nw + 8 * S, ny + 14 * S, ix + nw + 40 * S, ny + 20 * S), fill=A2[:3] + (255,))
    if sub:
        d.text((ix, ny + 54 * S), sub, font=_fit(d, sub, _TEXT_FONTS, iw, 28 * S, 18 * S), fill=ink["sub"],
               anchor="ls")
    if rnd:
        label, does = "A SURPRISE", "The machine picks one of the characters nobody has taken yet."
    else:
        label = character_words(c, words_for) or "NO SPECIAL ABILITY"      # round 6: its powers' words, or its own
        does = character_line(c, words_for) if label != "NO SPECIAL ABILITY" else "Plays as the game always does."
        label = badge_label(d, c, label, words_for, iw - 40 * S, S)[0]    # PAD-1083: never past the card's edge
    bf = _fit(d, label, _TEXT_FONTS, iw - 40 * S, 24 * S, BADGE_LEAST * S)  # PAD-1075: a long badge shrinks to the card
    bw = d.textlength(label, font=bf) + 40 * S
    by = (222 if sub else 208) * S
    d.rounded_rectangle((ix, by, ix + bw, by + 46 * S), radius=23 * S, fill=ink["badge"])
    d.text((ix + bw / 2, by + 23 * S), label, font=bf, fill=ink["badge_text"], anchor="mm")
    tf, lines, step = _card_lines(d, does, iw, S)
    for k, line in enumerate(lines):                    # with a sub header: closer, clear of how to choose
        d.text((ix, by + ((76 if sub else 88) - (27 * S - tf.size) // S) * S + k * step), line, font=tf,
               fill=ink["does"], anchor="ls")
    # how to choose
    hy = 372 * S
    hf2 = _face(_TEXT_FONTS, 20 * S)
    x = ix
    for kind, words in (("lr", "FLIPPERS TO CHOOSE"), ("dot", "ACTION BUTTON TO SELECT")):
        if kind == "lr":
            d.polygon([(x, hy), (x + 16 * S, hy - 11 * S), (x + 16 * S, hy + 11 * S)], fill=A2[:3] + (255,))
            d.polygon([(x + 40 * S, hy), (x + 24 * S, hy - 11 * S), (x + 24 * S, hy + 11 * S)], fill=A2[:3] + (255,))
            x += 52 * S
        else:
            d.ellipse((x, hy - 11 * S, x + 22 * S, hy + 11 * S), fill=A2[:3] + (255,))
            x += 34 * S
        d.text((x, hy), words, font=hf2, fill=_hex(th["help"], 220), anchor="lm")
        x += d.textlength(words, font=hf2) + 36 * S
    # the roster strip: every character and RANDOM, this one lit
    tiles = chars + [None]
    gap = 10 * S
    sy, sh = 414 * S, 80 * S
    tw_ = min(96 * S, (W - 80 * S - gap * (len(tiles) - 1)) // max(1, len(tiles)))
    sx = (W - (tw_ * len(tiles) + gap * (len(tiles) - 1))) // 2
    for k, t in enumerate(tiles):
        x0 = sx + k * (tw_ + gap)
        on = k == index or (rnd and t is None)
        tile = _portrait(project, t, tw_, sh, acc, acc2) if (t is None or picture_path(project, t)) else None
        if tile is None:
            tile = Image.new("RGBA", (tw_, sh), (22, 26, 38, 255))
            td = ImageDraw.Draw(tile)
            td.text((tw_ / 2, sh / 2), t["tag"], font=_fit(td, t["tag"], _DISPLAY_FONTS, tw_ - 14 * S, 30 * S),
                    fill=(235, 238, 245, 255), anchor="mm")
        if not on:
            tile = Image.blend(tile, Image.new("RGBA", tile.size, (8, 10, 16, 255)), 0.55)
        tm = Image.new("L", (tw_, sh), 0)
        ImageDraw.Draw(tm).rounded_rectangle((0, 0, tw_ - 1, sh - 1), radius=10 * S, fill=255)
        img.paste(tile, (x0, sy), tm)
        d = ImageDraw.Draw(img)
        if on:
            img = _glow(img, (x0 - 3 * S, sy - 3 * S, x0 + tw_ + 3 * S, sy + sh + 3 * S), 12 * S, A[:3] + (255,), 6 * S,
                        5 * S)
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((x0 - 2 * S, sy - 2 * S, x0 + tw_ + 2 * S, sy + sh + 2 * S), radius=11 * S,
                                outline=A[:3] + (255,), width=3 * S)
        else:
            d.rounded_rectangle((x0, sy, x0 + tw_ - 1, sy + sh - 1), radius=10 * S, outline=(255, 255, 255, 50),
                                width=S)
    # ImageDraw REPLACES an RGBA image's pixels (a line at alpha 10 punched a hole, not a tint): everything inside the
    # frame goes over the opaque body, so only the glow outside it is see-through
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    base.paste(Image.new("RGBA", (W, H), (12, 14, 22, 255)), (0, 0), mask)
    img = Image.alpha_composite(base, img)
    if window and c is not None and video_path(project, c):     # PAD-1079: the video's window, inside the frame line
        hole = Image.new("L", (pw - 6 * S, ph - 6 * S), 0)
        ImageDraw.Draw(hole).rounded_rectangle((0, 0, pw - 6 * S - 1, ph - 6 * S - 1), radius=11 * S, fill=255)
        img.paste((0, 0, 0, 0), (px + 3 * S, py + 3 * S), hole)
    out = np.asarray(img.resize(CARD_SIZE, Image.LANCZOS), dtype=np.uint8).copy()
    # the game blends its pictures PREMULTIPLIED (emulator: a white line at alpha 7 came out bright white, a body at
    # alpha 240 let the city through): the colour goes in already scaled by its alpha, so the glow and the rounded
    # corners fade as drawn
    a = out[..., 3:4].astype(np.uint16)
    out[..., :3] = (out[..., :3].astype(np.uint16) * a // 255).astype(np.uint8)
    return out


# ---- PAD-1028 round 2: the awards on the winners' character cards ---------------------------------------------------
# DoomWalrus666: "I want the players selected Godzilla character portrait to be shown next to their awards at the end
# of the game". A card with characters gets an award card per character beside the pick's screens: the pick card's
# look, its portrait in the lit frame and its name, and a words line the runtime fills at the game's end with the award,
# the teammate and the count (pad_mode_runtime.c "the awards on the winners' character cards"). coop.cfg: award_cards.

#: an award card's node: ``PadCoopAward_<n>`` (1-based, the character's place)
AWARD_NODE = "PadCoopAward_%d"
#: where an award card sits on the 1360x768 glass, and its size: the middle, above the score panels
AWARD_AT = (240, 110)
AWARD_SIZE = (880, 460)
#: the band at the card's foot the runtime's words line goes in (its top, from the card's top). The game's text fits
#: itself to its box and centres in it (Godzilla's FlashyText), and its middle sits at the box's y: the box is the
#: card's width less a margin (words_scale), centred, its y the band's middle (emulator, Godzilla LE 1.16)
AWARD_WORDS_Y = 404
AWARD_WORDS_SCALE = 0.93
AWARD_WORDS_X = round(AWARD_SIZE[0] * (1 - AWARD_WORDS_SCALE) / 2, 1)
AWARD_TITLE = "CO-OP AWARD"


def award_card(project, characters, index, theme=None, scale=2):
    """Character *index*'s award card as an RGBA array of :data:`AWARD_SIZE`: the header, its portrait in a lit
    frame, its name, and an empty band at the foot for the runtime's words."""
    import math
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    chars = [dict(c) for c in _characters(characters)["list"]]
    for c_ in chars:
        c_["tag"] = tag_of(c_["name"], [x["name"] for x in chars])
    c = chars[index]
    th = theme_of(theme)
    acc = c.get("colour") or th["accent"]                       # PAD-1079: the pick card's look, its colours too
    A, A2 = _hex(acc), _hex(th["accent2"])
    S = scale
    W, H = AWARD_SIZE[0] * S, AWARD_SIZE[1] * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    body = _body(project, th, W, H, S)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=26 * S, fill=255)
    img.paste(body, (0, 0), mask)
    img = _glow(img, (4 * S, 4 * S, W - 5 * S, H - 5 * S), 24 * S, A[:3] + (200,), 6 * S, 4 * S)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((3 * S, 3 * S, W - 4 * S, H - 4 * S), radius=25 * S, outline=A[:3] + (255,), width=3 * S)
    # the header: CO-OP AWARD, a rule, a star
    hf = _fit(d, AWARD_TITLE, _DISPLAY_FONTS, W * 0.6, 44 * S)
    d.text((40 * S, 42 * S), AWARD_TITLE, font=hf, fill=_hex(th["heading"]), anchor="lm")
    tw = d.textlength(AWARD_TITLE, font=hf)
    d.line([(40 * S + tw + 18 * S, 42 * S), (W - 90 * S, 42 * S)], fill=A[:3] + (150,), width=2 * S)
    cx, cy, r1, r2 = W - 58 * S, 42 * S, 22 * S, 9 * S
    d.polygon([(cx + (r1 if k % 2 == 0 else r2) * math.sin(k * math.pi / 5),
                cy - (r1 if k % 2 == 0 else r2) * math.cos(k * math.pi / 5)) for k in range(10)], fill=A[:3] + (255,))
    # the portrait, in a lit frame
    px, py, pw, ph = 40 * S, 80 * S, 340 * S, 300 * S
    img = _glow(img, (px - 4 * S, py - 4 * S, px + pw + 4 * S, py + ph + 4 * S), 16 * S, A[:3] + (230,), 10 * S, 6 * S)
    por = _portrait(project, c, pw, ph, acc, th["accent2"])
    pm = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(pm).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=14 * S, fill=255)
    img.paste(por, (px, py), pm)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((px, py, px + pw - 1, py + ph - 1), radius=14 * S, outline=A[:3] + (255,), width=3 * S)
    # the name, big, with its tag faint behind it
    ix, iw = px + pw + 40 * S, W - (px + pw + 40 * S) - 40 * S
    wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wf = _fit(ImageDraw.Draw(wm), c["tag"], _DISPLAY_FONTS, iw * 0.9, 240 * S, 60 * S)
    ImageDraw.Draw(wm).text((W - 50 * S, 240 * S), c["tag"], font=wf, fill=A[:3] + (18,), anchor="rm")
    img = Image.alpha_composite(img, wm)
    d = ImageDraw.Draw(img)
    nf = _fit(d, c["name"], _DISPLAY_FONTS, iw, 84 * S, 28 * S)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((ix + 4 * S, 200 * S + 5 * S), c["name"], font=nf, fill=(0, 0, 0, 220), anchor="ls")
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(4 * S)))
    d = ImageDraw.Draw(img)
    d.text((ix, 200 * S), c["name"], font=nf, fill=_hex(th["name"]), anchor="ls", stroke_width=max(1, S),
           stroke_fill=(0, 0, 0, 255))
    nw = min(iw - 40 * S, d.textlength(c["name"], font=nf))
    d.rectangle((ix, 214 * S, ix + nw, 220 * S), fill=A[:3] + (255,))
    d.rectangle((ix + nw + 8 * S, 214 * S, ix + nw + 40 * S, 220 * S), fill=A2[:3] + (255,))
    if c.get("sub"):                                             # PAD-1056: its sub header under the rule
        d.text((ix, 262 * S), c["sub"], font=_fit(d, c["sub"], _TEXT_FONTS, iw, 30 * S, 18 * S),
               fill=_hex(th["sub"] or acc), anchor="ls")
    # the band the runtime's words go in
    by = AWARD_WORDS_Y * S
    d.rounded_rectangle((24 * S, by - 6 * S, W - 25 * S, H - 18 * S), radius=14 * S, fill=(6, 8, 14, 255),
                        outline=A2[:3] + (200,), width=2 * S)
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    base.paste(Image.new("RGBA", (W, H), (12, 14, 22, 255)), (0, 0), mask)
    img = Image.alpha_composite(base, img)
    out = np.asarray(img.resize(AWARD_SIZE, Image.LANCZOS), dtype=np.uint8).copy()
    a = out[..., 3:4].astype(np.uint16)                          # premultiplied, as the pick card (the game blends so)
    out[..., :3] = (out[..., :3].astype(np.uint16) * a // 255).astype(np.uint8)
    return out


def award_screens(project, characters=None):
    """The award cards for :func:`.scene_write.add_screens`, one per character (``PadCoopAward_1`` ...); ``[]`` when
    the project's characters have no pick. Their words line starts empty: the runtime writes it."""
    chars = _characters(characters if characters is not None else load_characters(project))
    if not chars["pick"] or not chars["list"]:
        return []
    out = []
    for i in range(len(chars["list"])):
        name = AWARD_NODE % (i + 1)
        out.append(dict(name=name, art_rgba=award_card(project, chars, i, chars.get("theme")), words=" ",
                        words_name=name + "_Words", x=float(AWARD_AT[0]), y=float(AWARD_AT[1]),
                        words_at=(AWARD_WORDS_X, float(AWARD_WORDS_Y + 16)), words_scale=AWARD_WORDS_SCALE))
    out.append(dict(name=FINAL_NODE, art_rgba=final_band(chars.get("theme")), words=" ",
                    words_name=FINAL_NODE + "_Words",
                    x=float(FINAL_AT[0]), y=float(FINAL_AT[1]),
                    words_at=(round(FINAL_SIZE[0] * (1 - FINAL_WORDS_SCALE) / 2, 1), float(FINAL_WORDS_Y)),
                    words_scale=FINAL_WORDS_SCALE))
    return out


# ---- PAD-1219: the final score under the award cards ---------------------------------------------------------------
# DoomWalrus666: "During the awards ceremony, please remove the scoreboard, power up bar, and credits/player/ball count
# thing. Just display the awards box, and the final score along the bottom in large font." The runtime keeps the
# game's HUD off the glass while the cards show; this band across the glass's foot carries the team's final score
# (its words the runtime's: "FINAL SCORE  240,960").
FINAL_NODE = "PadCoopFinal"
FINAL_AT = (0, 596)
FINAL_SIZE = (1360, 160)
FINAL_WORDS_Y = 92
FINAL_WORDS_SCALE = 1.4          # (emulator: x2.1 cut "FINAL SCORE  2,160,640" at both ends; x1.4 fits 28)


def final_band(theme=None):
    """The final score's band as a premultiplied RGBA array of :data:`FINAL_SIZE`: dark glass fading in from the top,
    an accent rule along its top edge."""
    import numpy as np
    th = theme_of(theme)
    A, A2 = _hex(th["accent"]), _hex(th["accent2"])
    w, h = FINAL_SIZE
    out = np.zeros((h, w, 4), dtype=np.float32)
    ramp = np.clip(np.arange(h, dtype=np.float32) / 40.0, 0.0, 1.0) * 0.82
    out[..., 3] = ramp[:, None]
    out[..., 0], out[..., 1], out[..., 2] = 6 / 255.0, 8 / 255.0, 14 / 255.0
    edge = np.abs(np.arange(w, dtype=np.float32) - w / 2) / (w / 2)
    fade = np.clip(1.0 - edge, 0.0, 1.0) ** 0.6
    for y0, y1, col in ((10, 14, A), (14, 16, A2)):            # the rule: the accent, a thin second colour under it
        for k in range(3):
            out[y0:y1, :, k] = col[k] / 255.0
        out[y0:y1, :, 3] = fade[None, :]
    out[..., :3] *= out[..., 3:4]                              # premultiplied, as the cards (the game blends so)
    return (out * 255 + 0.5).astype(np.uint8)


# ---- PAD-1053: the co-op settings file -----------------------------------------------------------------------------
# DoomWalrus666: a file that keeps every co-op setting of a project (co-op on, the service menu switch, the awards,
# the characters with their abilities, the pick's time and look, and each character's picture) to load into another
# project or keep. A zip: :data:`FILE_MANIFEST` and the pictures under ``pictures/``; a .json is the manifest alone
# (no pictures). Load also takes a characters file the owner made in :data:`PRESET_DIR`'s shape.

#: the zip's manifest, and its kind
FILE_MANIFEST = "pad_coop.json"
FILE_KIND = "pad-coop"
FILE_VERSION = 1
#: the folder in the zip the pictures are in
FILE_PICTURES = "pictures"
_PICTURE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def _sidecar(project):
    from ...core import staged_changes
    raw = staged_changes.load(project).get(STAGED_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def settings_saved(project):
    """Whether *project* has any co-op settings to save."""
    try:
        return bool(project) and bool(_sidecar(project))
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return False


def export_settings(project, path):
    """Write *project*'s co-op settings to *path* (a .zip with the pictures, or a .json without them); returns
    ``{"characters", "pictures", "awards", "left_out"}`` (``left_out``: pictures a .json cannot carry). Raises
    :class:`CoopError` when the project has none."""
    import json
    import os
    import zipfile
    raw = _sidecar(project)
    if not raw:
        raise CoopError("This project has no co-op settings to save. Tick Co-op play first.")
    chars = _characters(raw.get("characters"))
    awards = ({k: v for k, v in raw["awards"].items() if isinstance(v, dict)}
              if isinstance(raw.get("awards"), dict) else {})
    prof = project_title(project)
    head = {"kind": FILE_KIND, "version": FILE_VERSION,
            "from": {"label": prof.label if prof is not None else ""},
            "on": bool(raw.get("on")), "menu": bool(raw.get("menu")), "awards": awards, "characters": chars}
    as_zip = not path.lower().endswith(".json")
    pictures, left_out = [], 0
    for i, c in enumerate(chars["list"]):
        src = picture_path(project, c)
        c["picture"] = ""
        if not src:
            continue
        if not as_zip:
            left_out += 1
            continue
        rel = "%s/%d_%s%s" % (FILE_PICTURES, i + 1, picture_file_name(c["name"]) or "character",
                              os.path.splitext(src)[1].lower() or ".png")
        c["picture"] = rel
        pictures.append((src, rel))
    for i, c in enumerate(chars["list"]):                       # PAD-1079: each character's video
        src = video_path(project, c)
        c["video"] = ""
        if not src:
            continue
        if not as_zip:
            left_out += 1
            continue
        c["video"] = "%s/%d_%s_video%s" % (FILE_PICTURES, i + 1, picture_file_name(c["name"]) or "character",
                                           os.path.splitext(src)[1].lower())
        pictures.append((src, c["video"]))
    for i, c in enumerate(chars["list"]):                       # PAD-1123: each character's clip and sound once picked
        for field, path_of, tag in (("picked_clip", picked_clip_path, "picked"),
                                    ("picked_sound", picked_sound_path, "picked_sound")):
            src = path_of(project, c)
            c[field] = ""
            if not src:
                continue
            if not as_zip:
                left_out += 1
                continue
            c[field] = "%s/%d_%s_%s%s" % (FILE_PICTURES, i + 1, picture_file_name(c["name"]) or "character", tag,
                                          os.path.splitext(src)[1].lower())
            pictures.append((src, c[field]))
    for key, stem, path_of in (("intro", INTRO_FILE, intro_path),          # PAD-1114: the co-op games' intro video
                               ("ceremony", CEREMONY_FILE, ceremony_path)):   # PAD-1219: the awards' background
        got = path_of(project, chars)
        chars.pop(key, None)
        if got:
            if as_zip:
                chars[key] = "%s/%s%s" % (FILE_PICTURES, stem, os.path.splitext(got)[1].lower())
                pictures.append((got, chars[key]))
            else:
                left_out += 1
    back = backdrop_path(project, chars.get("theme"))          # PAD-1079: the pick's background picture
    if back:
        if as_zip:
            rel = "%s/%s%s" % (FILE_PICTURES, BACKDROP_FILE, os.path.splitext(back)[1].lower() or ".png")
            chars["theme"]["backdrop"] = rel
            pictures.append((back, rel))
        else:
            chars["theme"].pop("backdrop", None)
            left_out += 1
    elif "backdrop" in chars.get("theme", {}):
        chars["theme"].pop("backdrop")
    text = json.dumps(head, indent=2)
    tmp = path + ".part"
    try:
        if as_zip:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(FILE_MANIFEST, text)
                for src, rel in pictures:
                    zf.write(src, rel)
        else:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise CoopError("The co-op settings could not be saved: %s" % e) from None
    return {"characters": len(chars["list"]), "pictures": len(pictures),
            "awards": sum(1 for a in awards.values() if a.get("on")), "left_out": left_out}


def _read_file(path):
    """``(head, read)`` of a co-op settings file: its manifest and ``read(rel)`` giving a picture in it as bytes
    (None for a .json). A characters file in :data:`PRESET_DIR`'s shape comes back as one with ``"preset": True``.
    Raises :class:`CoopError` when it is neither."""
    import json
    import zipfile
    read = None
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                if FILE_MANIFEST not in names:
                    raise CoopError("This zip is not a co-op settings file (it has no %s)." % FILE_MANIFEST)
                head = json.loads(zf.read(FILE_MANIFEST).decode("utf-8"))
                blobs = {n: zf.read(n) for n in names if n.startswith(FILE_PICTURES + "/") and not n.endswith("/")}
        except (OSError, zipfile.BadZipFile, ValueError, UnicodeDecodeError) as e:
            raise CoopError("The co-op settings file could not be read: %s" % e) from None
        read = blobs.get
    else:
        try:
            with open(path, encoding="utf-8") as f:
                head = json.load(f)
        except (OSError, ValueError) as e:
            raise CoopError("The co-op settings file could not be read: %s" % e) from None
    if not isinstance(head, dict):
        raise CoopError("The file is not a co-op settings file.")
    if head.get("kind") != FILE_KIND:
        if isinstance(head.get("characters"), list):    # a characters file in PRESET_DIR's shape
            return {"kind": FILE_KIND, "preset": True, "from": {"label": str(head.get("game") or "")},
                    "characters": {"pick": True, "list": head["characters"], "theme": head.get("theme")}}, None
        raise CoopError("The file is not a co-op settings file.")
    return head, read


def file_about(path):
    """``{"made_for", "characters", "pictures", "awards"}`` of a co-op settings file, or None when *path* is not
    one (the Mod Pack tab and the Modes tab's Load from a file... tell it from theirs)."""
    try:
        head, read = _read_file(path)
    except CoopError:
        return None
    if head.get("preset"):
        return None
    chars = _characters(head.get("characters"))
    awards = head.get("awards") if isinstance(head.get("awards"), dict) else {}
    return {"made_for": str((head.get("from") or {}).get("label") or ""), "characters": len(chars["list"]),
            "pictures": sum(1 for c in chars["list"] if c["picture"] and read and read(c["picture"])),
            "awards": sum(1 for a in awards.values() if isinstance(a, dict) and a.get("on"))}


def file_words(about):
    """One sentence naming what :func:`file_about` (or :func:`import_settings`) found."""
    parts = ["%d character%s" % (about["characters"], "" if about["characters"] == 1 else "s")]
    if about["pictures"]:
        parts.append("%d picture%s" % (about["pictures"], "" if about["pictures"] == 1 else "s"))
    parts.append("the awards")
    return "It holds co-op settings (%s)%s." % (", ".join(parts), ", made for %s" % about["made_for"]
                                                if about.get("made_for") else "")


def import_settings(project, path):
    """Load a co-op settings file (:func:`export_settings`', or a characters file) into *project* in place of its
    co-op settings: co-op on or off, the menu switch, the awards and the characters with their pictures (copied into
    the project's :data:`PICTURE_DIR`). A characters file replaces the characters only. Returns ``{"made_for",
    "characters", "pictures", "awards", "preset"}``. Raises :class:`CoopError` when it is not one."""
    import io
    import os
    from ...core import staged_changes
    head, read = _read_file(path)
    chars = _characters(head.get("characters"))
    folder = os.path.join(project, PICTURE_DIR)
    pictures = 0
    for i, c in enumerate(chars["list"]):
        rel, c["picture"] = c["picture"], ""
        blob = read(rel) if read and rel else None
        ext = os.path.splitext(rel)[1].lower()
        if not blob or ext not in _PICTURE_EXTS:
            continue
        try:
            MA_check_picture(io.BytesIO(blob))
        except Exception:                               # noqa: BLE001 - not a picture: the panel with its name
            continue
        os.makedirs(folder, exist_ok=True)
        name = "character_%d%s" % (i + 1, ext)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(blob)
        c["picture"] = "%s/%s" % (PICTURE_DIR, name)
        pictures += 1
    for i, c in enumerate(chars["list"]):                       # PAD-1079: each character's video
        rel, c["video"] = c.get("video") or "", ""
        blob = read(rel) if read and rel else None
        ext = os.path.splitext(rel)[1].lower()
        if not blob or ext not in VIDEO_EXTS:
            continue
        os.makedirs(folder, exist_ok=True)
        name = "character_%d_video%s" % (i + 1, ext)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(blob)
        c["video"] = "%s/%s" % (PICTURE_DIR, name)
        pictures += 1
    for i, c in enumerate(chars["list"]):                       # PAD-1123: each character's clip and sound once picked
        for field, stem, exts in (("picked_clip", PICKED_FILE, VIDEO_EXTS + _PICTURE_EXTS),
                                  ("picked_sound", PICKED_SOUND_FILE, SOUND_EXTS + VIDEO_EXTS)):
            rel, c[field] = c.get(field) or "", ""
            blob = read(rel) if read and rel else None
            ext = os.path.splitext(rel)[1].lower()
            if not blob or ext not in exts:
                continue
            os.makedirs(folder, exist_ok=True)
            name = (stem % (i + 1)) + ext
            with open(os.path.join(folder, name), "wb") as f:
                f.write(blob)
            c[field] = "%s/%s" % (PICTURE_DIR, name)
            pictures += 1
    for key, stem in (("intro", INTRO_FILE), ("ceremony", CEREMONY_FILE)):   # PAD-1114 / PAD-1219: the videos
        rel = chars.pop(key, "") or ""
        blob = read(rel) if read and rel else None
        ext = os.path.splitext(rel)[1].lower()
        if blob and ext in VIDEO_EXTS:
            os.makedirs(folder, exist_ok=True)
            for f in os.listdir(folder):
                if os.path.splitext(f)[0] == stem:
                    os.remove(os.path.join(folder, f))
            with open(os.path.join(folder, stem + ext), "wb") as f:
                f.write(blob)
            chars[key] = "%s/%s%s" % (PICTURE_DIR, stem, ext)
            pictures += 1
    theme = chars.get("theme") or {}                            # PAD-1079: the pick's background picture
    rel = theme.pop("backdrop", "")
    blob = read(rel) if read and rel else None
    ext = os.path.splitext(rel)[1].lower()
    if blob and ext in _PICTURE_EXTS:
        try:
            MA_check_picture(io.BytesIO(blob))
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, BACKDROP_FILE + ext), "wb") as f:
                f.write(blob)
            theme["backdrop"] = "%s/%s%s" % (PICTURE_DIR, BACKDROP_FILE, ext)
            pictures += 1
        except Exception:                               # noqa: BLE001 - not a picture: the stock panel
            pass
    data = staged_changes.load(project)
    raw = dict(data.get(STAGED_KEY)) if isinstance(data.get(STAGED_KEY), dict) else {"on": False}
    awards = {}
    if not head.get("preset"):
        raw = {"on": bool(head.get("on"))}
        if head.get("on") and head.get("menu"):
            raw["menu"] = True
        got = head.get("awards") if isinstance(head.get("awards"), dict) else {}
        for k, v in got.items():
            if isinstance(v, dict):
                a = {}
                if "on" in v:
                    a["on"] = bool(v["on"])
                if v.get("words"):
                    a["words"] = clean_words(v["words"])
                awards[str(k)] = a
        if awards:
            raw["awards"] = awards
    if chars["list"] or chars["pick"] or chars.get("intro") or chars.get("ceremony") or chars.get("bonus"):
        raw["characters"] = chars
    else:
        raw.pop("characters", None)
    if raw.get("on") or len(raw) > 1:
        data[STAGED_KEY] = raw
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return {"made_for": str((head.get("from") or {}).get("label") or ""), "characters": len(chars["list"]),
            "pictures": pictures, "awards": sum(1 for a in awards.values() if a.get("on")),
            "preset": bool(head.get("preset"))}
