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
those numbers with the names in its help line; an Off/On row's 0 and 1 keep their meaning). Set to 2, each Start in the
first ball adds the next player: players 1 and 2 are one team, 3 and 4 the other, each team with its own score and its
own progress (the game plays two players, a team each) and the turns alternating the teams (pad_mode_runtime.c "TEAM
2V2"). The characters' pick works as in co-op: each player picks at their first ball, no two the same."""
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
#: the number; Off/On had 0 and 1 and v1.360.0's row 0-2, so a pick is kept)
MENU_VALUES = 4
MENU_OFF, MENU_COOP, MENU_TEAMS, MENU_TEAMS_2V1 = 0, 1, 2, 3
#: the help names the values and says what they cost (63 characters: the spare help lines' room)
MENU_HELP = "0 Off, 1 Co-op, 2 Team 2v2, 3 Team 2v1. 1-3: Insider mostly off"
#: how a teammate joins, for the tab and the log
HOW = ("hold the right flipper button and press Start to add a teammate (2-4 players share one game); "
       "a plain Start adds a competing player as always")
#: PAD-1042: how a team game is played, for the tab and the log
TEAMS_HOW = ("with CO-OP PLAY at 2 (Team 2v2), each Start in the first ball adds the next player: players 1 and 2 "
             "against players 3 and 4, each team with its own score and progress, the teams taking turns; at 3 "
             "(Team 2v1) the same with three players, players 1 and 2 against player 3, who plays both of team 2's "
             "turns")


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
            + "".join(line + "\n" for line in award_lines(game_elf, awards))
            + "".join(line + "\n" for line in character_lines(game_elf, characters, sites, values)))


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
#: PAD-1044: the seconds a teammate has to pick (the runtime's COOP_PICK_MS when coop.cfg names none), and the
#: choices the Characters dialog offers; 0 is no time limit (the Action button takes one)
PICK_TIME = 30
PICK_TIMES = (15, 20, 30, 45, 60, 90, 0)
#: the presets beside this module: ``coop_presets/<title stem>.json`` (the customization file per game)
PRESET_DIR = "coop_presets"

#: (key, words the pick shows, what it does, how): how is ("adj", adjustment name, "x<pct>" | "min" | "max"),
#: ("cache", adjustment name, "min" | ...): an adjustment the game copies into a player's record at the game's start
#: (the port's ``coop_cache_<id>`` names the copy), ("boost", pct): the port's ``coop_boost`` call adds pct %,
#: ("gift", adjustment name): the game's own one-shot feature at the pick (the port's ``coop_adj_changed``),
#: ("count", name, n): a rule's count for the player raised by n at the pick (the port's ``coop_count_<name>``),
#: ("save", seconds), ("addball", n): Action twice in regular play serves n more balls, ("yes", name): a check of the
#: game's answers yes (the port's ``coop_yes_<name>``), or ("many", [parts]): several of the above at once
ABILITIES = (
    ("longer_save", "LONGER BALL SAVE, LONGER TIMERS",
     "The ball save at each of their balls lasts twice the game's BALL SAVE TIME (at most its top); on Godzilla the "
     "Oxygen Destroyer timer is twice its setting and every battle timer gets 5 seconds more.",
     ("some", [("adj", "AD_BALL_SAVE_TIME", "x200"), ("adj", "AD_O2_DESTROYER_TIMER", "x200"),
               ("adj", "AD_BATTLE_VS_EBIRAH_TIMER", "+5"), ("adj", "AD_BATTLE_VS_TITANOSAURUS_TIMER", "+5"),
               ("adj", "AD_BATTLE_VS_GIGAN_TIMER", "+5"), ("adj", "AD_BATTLE_VS_MEGALON_TIMER", "+5"),
               ("adj", "AD_BATTLE_VS_KING_GHIDORAH_TIMER", "+5"), ("adj", "AD_BATTLE_VS_GHIDORAH_AND_GIGAN_TIMER", "+5")])),
    ("action_save", "ACTION BUTTON BALL SAVE",
     "A 10 second ball save when they press the Action button twice quickly, once a ball.", ("save", 10)),
    ("heat_ray", "HEAT RAY READY, EASIER HEAT RAY", "The heat ray is ready when they pick (HOLD DOWN ACTION BUTTON "
     "from their first ball), and afterwards it charges in half the spinner spins a level (HEAT RAY SPINS PER LEVEL).",
     ("many", [("adj", "AD_HEAT_RAY_SPINS_PER_LEVEL", "x50"), ("set", "heatray", 1)])),
    ("battles", "EASIER BATTLES", "The ramps light a battle as on the game's easiest LIGHT BATTLE DIFFICULTY.",
     ("cache", "AD_LIGHT_BATTLE_DIFFICULTY", "min")),
    ("building", "BUILDING AND MECHA MULTIBALLS", "Every building or ramp shot takes two of the building's six "
     "stability steps (on the game's easiest BUILDING DIFFICULTY), and toward Mechagodzilla Multiball every spin "
     "counts twice and every shield target hit counts twice.",
     ("many", [("cache", "AD_BUILDING_DIFFICULTY", "min"), ("steps", "building"), ("double", "spins"),
               ("double", "shield")])),
    ("powerups", "DOUBLE POWER-UPS", "Every Godzilla power-up the game gives counts twice.", ("boost", 200)),
    ("ally", "AN ALLY EVERY BALL", ("An ally is lit at each of their balls: the next of Mothra, Rodan and Anguirus in "
      "the game's own order (its LIGHT ALLY), at the pick and at every later turn."),
     ("gift", "AD_LIGHT_ALLY")),
    ("jets", "STARTS WITH 4 JETS", "Four jet fighters count as destroyed when they pick (JET FIGHTER CHAMPION and "
     "the bonus count them).", ("count", "jets", 4)),
    ("spot", "SPOT A BATTLE SHOT", "Two quick presses of the Action button during a battle count as its next lit "
     "shot, as often as they like.", ("spot", "coop_battle_rules")),
    ("tier2", "TIER 2 ALWAYS OPEN", "Every battle on the selection screen is open while they are up, tier 2 included "
     "(the game's UNLOCK ALL MONSTER BATTLES reads On for them).",
     ("unlock", "AD_BATTLE_UNLOCK_ALL_MONSTER_BATTLES", None)),
    ("addball", "ADD A BALL", "Two quick presses of the Action button in regular play put a second ball in play, "
     "once a ball.", ("addball", 1)),
    ("maser", "MASER ALWAYS LIT", "The Maser cannon target is lit the whole time they are up: in regular play (the "
     "Maser shot held lit in the game's own rule) and for all of Tank Attack (its Maser phase check says yes).",
     ("many", [("lit", "maser"), ("yes", "maser")])),
    ("bridge", "EASIER BRIDGE, DOUBLE TANKS AND JETS", "The bridge falls as on the game's easiest BRIDGE ATTACK "
     "DIFFICULTY, and every tank or jet destroyed counts as two.",
     ("many", [("cache", "AD_BRIDGE_ATTACK_DIFFICULTY", "min"), ("double", "tanks"), ("double", "jets")])),
    ("tanks", "STARTS WITH 4 TANKS", "Four tanks count as destroyed when they pick: the city map's TANKS n/10 starts "
     "at 4.", ("count", "tanks", 4)),
)
#: what the pick's card says each ability does, in the player's words
CARD_LINES = {
    "longer_save": "Twice the ball save every ball. Longer Oxygen Destroyer and battle timers.",
    "action_save": "Press Action twice for a 10 second ball save, once a ball.",
    "heat_ray": "Heat ray ready from the start. Recharges in half the spins.",
    "battles": "One ramp lights a battle.",
    "building": "Building damage two steps a shot. Mecha spins and shield hits count twice.",
    "powerups": "Every Godzilla power-up counts twice.",
    "ally": "An ally lit at every one of their balls.",
    "jets": "Starts with 4 jet fighters destroyed.",
    "tanks": "Starts with 4 tanks destroyed.",
    "spot": "Press Action twice in a battle to hit its next shot, as often as you like.",
    "tier2": "Every battle is open to you, tier 2 included.",
    "addball": "Press Action twice in regular play to add a ball, once a ball.",
    "maser": "The Maser cannon is lit the whole time you are up.",
    "bridge": "The bridge falls faster. Tanks and jets count two at a time.",
}

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
    out = []
    for key, words, does, how in ABILITIES:
        cfg, why = _ability_part(how, table, action, sites, values, label)
        out.append({"key": key, "words": words, "does": does, "cfg": cfg, "why": why})
    return out


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
                else:
                    cfg = "adj:%d%s:%d:%d" % (idx, how[2], lo, hi)
                if how[1] == "AD_BALL_SAVE_TIME":                  # read when a ball is served: the ball-1 pick's
                    cfg += ",bs:%d" % idx                          # ball gets it at the pick
    return cfg, why


def clean_name(name):
    """A character's name as the top line shows it: capitals, one space between words, no ``|``, at most
    :data:`MAX_NAME`."""
    return " ".join(str(name or "").upper().replace("|", " ").split())[:MAX_NAME]


def load_characters(project):
    """The project's characters: ``{"pick": bool, "time": seconds, "list": [{"name", "ability", "picture"}]}``
    (``ability`` a key of :data:`ABILITIES` or ``""``; ``picture`` the owner's file, for the pick screens that show
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
            out.append({"name": clean_name(c.get("name")), "ability": str(c.get("ability") or ""),
                        "picture": str(c.get("picture") or "")})
    theme = got.get("theme") if isinstance(got.get("theme"), dict) else {}
    out = {"pick": bool(got.get("pick")), "time": pick_time(got.get("time")), "list": out[:MAX_CHARACTERS]}
    if theme:
        out["theme"] = {k: str(v) for k, v in theme.items() if k in ("title", "accent", "accent2") and v}
    return out


def save_characters(project, characters):
    """Store the project's characters (:func:`load_characters`' shape); returns them as stored."""
    from ...core import staged_changes
    chars = _characters(characters)
    data = staged_changes.load(project)
    raw = dict(data.get(STAGED_KEY)) if isinstance(data.get(STAGED_KEY), dict) else {"on": False}
    if chars["list"] or chars["pick"]:
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
    if not chars["pick"] or not chars["list"]:
        return []
    by_key = {a["key"]: a for a in abilities(game_elf, sites=sites, values=values)}
    out = ["pick on", "pick_time %d" % chars["time"]]
    buttons = _SMo.flipper_buttons(game_elf)
    if len(buttons) == 2:
        out.append("left %d" % buttons[0])
    action = action_button(game_elf)
    if action is not None:
        out.append("action %d" % action)
        lane = shooter_lane(game_elf)
        if lane is not None:
            out.append("lane %d" % lane)
    for c in chars["list"]:
        a = by_key.get(c["ability"]) or {}
        out.append("character %s %s|%s" % (a.get("cfg") or "-", c["name"], a["words"] if a.get("cfg") else ""))
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
    import hashlib
    import json
    import os
    from . import mode_project as MP
    from . import title_reader as TR
    got = MP.project_card(project) if project else None
    card = getattr(got, "image", "") if got is not None else ""
    if not card or not os.path.isfile(card):
        return NO_CARD_CHARS, []
    prof = project_title(project)
    key = "%s|%d|%d|%s" % (card, os.path.getsize(card), int(os.path.getmtime(card)), ",".join(port_sites(prof)))
    cache = os.path.join(TR.cache_dir("coop_abilities"), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")
    try:
        with open(cache, encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("key") == key and raw.get("v") == _abilities_v():
            return "", raw["abilities"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    prof = project_title(project)
    try:
        got = abilities(TR.game_program(card)[2], prof.label if prof is not None else "This game", port_sites(prof),
                        port_values(prof))
    except Exception as e:                              # noqa: BLE001 - an unreadable card: say so
        return "The game program could not be read from the card: %s" % e, []
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"v": _abilities_v(), "key": key, "abilities": got}, f)
    except OSError:
        pass
    return "", got


def _abilities_v():
    """The abilities cache's version: the catalog itself, so a changed word reads the card again."""
    import hashlib
    return hashlib.sha1(repr(ABILITIES).encode("utf-8")).hexdigest()[:12]


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


def words_for():
    """``{ability key: the words the pick shows for it}``."""
    return {a[0]: a[1] for a in ABILITIES}


def wants_screens(project, prof):
    """Whether *project*'s card gets the pick's screens: co-op on, characters with a pick, a title with screens."""
    if not load(project) or prof is None or not prof.can("screen"):
        return False
    chars = load_characters(project)
    return bool(chars["pick"] and chars["list"])


def pick_screens(project, characters=None, words_for=None):
    """The pick's screens for :func:`.scene_write.add_screens`: one per character (``PadCoop_1`` ...) and
    ``PadCoop_Random``; ``[]`` when the project's characters have no pick. *words_for* (key -> words) names what
    each ability does, as the top line says it."""
    from . import mode_assets as MA
    chars = _characters(characters if characters is not None else load_characters(project))
    if not chars["pick"] or not chars["list"]:
        return []
    del MA
    out = []
    n = len(chars["list"])
    for i in range(n + 1):                    # every word is on the card but the runtime's: the seconds left, PICKED
        out.append(dict(name=SCREEN_NODE % ("Random" if i == n else i + 1),
                        art_rgba=pick_card(project, chars, i, words_for, chars.get("theme")),
                        words=" ", words_name=(SCREEN_NODE % ("Random" if i == n else i + 1)) + "_Words",
                        x=float(CARD_AT[0]), y=float(CARD_AT[1]), words_at=TIMER_WORDS_AT,
                        words_scale=TIMER_WORDS_SCALE))
    return out


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


def save_picture(project, index, source):
    """Copy *source* (a picture file) into the project for character *index* and name it there; returns the
    characters as stored. Raises :class:`CoopError` when the file is not a picture."""
    import os
    import shutil
    from PIL import Image
    try:
        with Image.open(source) as im:
            im.verify()
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


def preview(project, characters=None, words_for=None, index=0):
    """A still of what the machine shows while the pick is on character *index* (RANDOM after the last): its
    screen on a dark glass of the HUD's size, as PNG bytes - the Characters dialog's preview."""
    import io

    import numpy as np
    from PIL import Image
    from . import mode_assets as MA
    chars = _characters(characters if characters is not None else load_characters(project))
    if not chars["list"]:
        return b""
    index = max(0, min(int(index), len(chars["list"])))           # only the one card: a click redraws in a moment
    s = {"art_rgba": pick_card(project, chars, index, words_for, chars.get("theme")), "x": CARD_AT[0], "y": CARD_AT[1]}
    glass = Image.new("RGBA", (1360, 768), (40, 34, 58, 255))
    from PIL import ImageDraw
    d = ImageDraw.Draw(glass)
    d.rounded_rectangle((470, -20, 890, 76), radius=18, fill=(30, 30, 36, 255))     # the game's top bar
    secs = chars["time"]
    d.text((680, 30), "PLAYER 1 PICK  %d" % secs if secs else "PLAYER 1 PICK", fill=(255, 255, 255, 255),
           anchor="mm", font=MA._font(26))
    for k in range(4):                                                            # its score panels
        d.rounded_rectangle((30 + k * 330, 612, 330 + k * 330, 760), radius=14, fill=(26, 26, 30, 255))
    art = Image.fromarray(np.asarray(s["art_rgba"], dtype=np.uint8), "RGBA")
    glass.alpha_composite(art, (int(s["x"]), int(s["y"])))
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
#: the default look; a preset may give its own ("theme": {"title", "accent", "accent2"})
THEME = {"title": "CHOOSE YOUR CHARACTER", "accent": "#ffb400", "accent2": "#ff5a1f"}
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


def theme_of(theme=None):
    """The card's look: :data:`THEME` with a preset's own over it."""
    t = dict(THEME)
    for k, v in (theme or {}).items():
        if k in THEME and v:
            t[k] = " ".join(str(v).upper().split())[:40] if k == "title" else str(v)
    return t


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


def pick_card(project, characters, index, words_for=None, theme=None, scale=2):
    """The pick's card for character *index* (``len(list)`` = RANDOM) as an RGBA array of :data:`CARD_SIZE`."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    timed = bool(_characters(characters)["time"])
    chars = [dict(c) for c in _characters(characters)["list"]]
    for c_ in chars:
        c_["tag"] = tag_of(c_["name"], [x["name"] for x in chars])
    th = theme_of(theme)
    acc, acc2 = th["accent"], th["accent2"]
    A, A2 = _hex(acc), _hex(acc2)
    S = scale
    W, H = CARD_SIZE[0] * S, CARD_SIZE[1] * S
    n = len(chars)
    rnd = index >= n
    c = None if rnd else chars[index]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # the panel: a near-black body with a cold-to-warm wash, a fine grid, a lit border and corner brackets
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    for y in range(H):
        t = y / H
        bd.line([(0, y), (W, y)], fill=(int(10 + 16 * t), int(12 + 6 * t), int(20 + 10 * (1 - t)), 255))
    for x in range(0, W, 28 * S):                                # the grid: drawn opaque, a shade off the body
        bd.line([(x, 0), (x, H)], fill=(30, 34, 48, 255), width=S)
    for y in range(0, H, 28 * S):
        bd.line([(0, y), (W, y)], fill=(30, 34, 48, 255), width=S)
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
    d.text((40 * S, 44 * S), th["title"], font=hf, fill=(255, 255, 255, 255), anchor="lm")
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
    d.text((W - 40 * S, 44 * S), count, font=cf, fill=A[:3] + (255,), anchor="rm")
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
    nf = _fit(d, name, _DISPLAY_FONTS, iw, 92 * S, 30 * S)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((ix + 4 * S, 166 * S + 5 * S), name, font=nf, fill=(0, 0, 0, 220), anchor="ls")
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(4 * S)))
    d = ImageDraw.Draw(img)
    d.text((ix, 166 * S), name, font=nf, fill=(255, 255, 255, 255), anchor="ls",
           stroke_width=max(1, S), stroke_fill=(0, 0, 0, 255))
    nw = min(iw - 40 * S, d.textlength(name, font=nf))
    d.rectangle((ix, 180 * S, ix + nw, 186 * S), fill=A[:3] + (255,))
    d.rectangle((ix + nw + 8 * S, 180 * S, ix + nw + 40 * S, 186 * S), fill=A2[:3] + (255,))
    if rnd:
        label, does = "A SURPRISE", "The machine picks one of the characters nobody has taken yet."
    else:
        label = (words_for or {}).get(c["ability"], "") if c["ability"] else ""
        label = label or "NO SPECIAL ABILITY"
        does = CARD_LINES.get(c["ability"], "") if label != "NO SPECIAL ABILITY" else "Plays as the game always does."
    bf = _face(_TEXT_FONTS, 24 * S)
    bw = d.textlength(label, font=bf) + 40 * S
    by = 208 * S
    d.rounded_rectangle((ix, by, ix + bw, by + 46 * S), radius=23 * S, fill=A[:3] + (255,))
    d.text((ix + bw / 2, by + 23 * S), label, font=bf, fill=(12, 12, 18, 255), anchor="mm")
    tf = _face(_TEXT_FONTS, 27 * S)
    for k, line in enumerate(_wrap(d, does, tf, iw, 2)):
        d.text((ix, by + 88 * S + k * 38 * S), line, font=tf, fill=(222, 228, 240, 255), anchor="ls")
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
        d.text((x, hy), words, font=hf2, fill=(255, 255, 255, 220), anchor="lm")
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
    A, A2 = _hex(th["accent"]), _hex(th["accent2"])
    S = scale
    W, H = AWARD_SIZE[0] * S, AWARD_SIZE[1] * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    for y in range(H):
        t = y / H
        bd.line([(0, y), (W, y)], fill=(int(10 + 16 * t), int(12 + 6 * t), int(20 + 10 * (1 - t)), 255))
    for x in range(0, W, 28 * S):
        bd.line([(x, 0), (x, H)], fill=(30, 34, 48, 255), width=S)
    for y in range(0, H, 28 * S):
        bd.line([(0, y), (W, y)], fill=(30, 34, 48, 255), width=S)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=26 * S, fill=255)
    img.paste(body, (0, 0), mask)
    img = _glow(img, (4 * S, 4 * S, W - 5 * S, H - 5 * S), 24 * S, A[:3] + (200,), 6 * S, 4 * S)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((3 * S, 3 * S, W - 4 * S, H - 4 * S), radius=25 * S, outline=A[:3] + (255,), width=3 * S)
    # the header: CO-OP AWARD, a rule, a star
    hf = _fit(d, AWARD_TITLE, _DISPLAY_FONTS, W * 0.6, 44 * S)
    d.text((40 * S, 42 * S), AWARD_TITLE, font=hf, fill=(255, 255, 255, 255), anchor="lm")
    tw = d.textlength(AWARD_TITLE, font=hf)
    d.line([(40 * S + tw + 18 * S, 42 * S), (W - 90 * S, 42 * S)], fill=A[:3] + (150,), width=2 * S)
    cx, cy, r1, r2 = W - 58 * S, 42 * S, 22 * S, 9 * S
    d.polygon([(cx + (r1 if k % 2 == 0 else r2) * math.sin(k * math.pi / 5),
                cy - (r1 if k % 2 == 0 else r2) * math.cos(k * math.pi / 5)) for k in range(10)], fill=A[:3] + (255,))
    # the portrait, in a lit frame
    px, py, pw, ph = 40 * S, 80 * S, 340 * S, 300 * S
    img = _glow(img, (px - 4 * S, py - 4 * S, px + pw + 4 * S, py + ph + 4 * S), 16 * S, A[:3] + (230,), 10 * S, 6 * S)
    por = _portrait(project, c, pw, ph, th["accent"], th["accent2"])
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
    d.text((ix, 200 * S), c["name"], font=nf, fill=(255, 255, 255, 255), anchor="ls", stroke_width=max(1, S),
           stroke_fill=(0, 0, 0, 255))
    nw = min(iw - 40 * S, d.textlength(c["name"], font=nf))
    d.rectangle((ix, 214 * S, ix + nw, 220 * S), fill=A[:3] + (255,))
    d.rectangle((ix + nw + 8 * S, 214 * S, ix + nw + 40 * S, 220 * S), fill=A2[:3] + (255,))
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
    return out


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
    from PIL import Image
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
            with Image.open(io.BytesIO(blob)) as im:
                im.verify()
        except Exception:                               # noqa: BLE001 - not a picture: the panel with its name
            continue
        os.makedirs(folder, exist_ok=True)
        name = "character_%d%s" % (i + 1, ext)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(blob)
        c["picture"] = "%s/%s" % (PICTURE_DIR, name)
        pictures += 1
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
    if chars["list"] or chars["pick"]:
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
