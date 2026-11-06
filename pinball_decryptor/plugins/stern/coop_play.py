"""Co-op play on a Spike 2 card (PAD-1017; sdk/MODE_SDK.md "Co-op play", docs/plans/pad1017_coop.md).

daveyvandy: co-op on the games that have none, 2-4 players sharing progress, with high score boards of its own. The
game plays one player, whose progress and score are the team's, and the mode runtime takes the teammates in turn, a
ball each (pad_mode_runtime.c "co-op play"; the port lines are portcoop.py's). A teammate joins when Start is pressed
with the right flipper button held; a plain Start adds a competing player as the game always has.

The Write tab's tick (the project sidecar's ``coop_play: {"on": true}``) puts ``coop.cfg`` beside the runtime on the
card: ``coop on`` and the right flipper button's switch id, read off the card's own game program."""
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


def save(project, on):
    """Ask (or stop asking) for co-op play; returns what it was before. PAD-1028: the award choices stay, for when it is
    ticked again; PAD-1031: so do the characters."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    raw = data.get(STAGED_KEY) if isinstance(data.get(STAGED_KEY), dict) else {}
    was = bool(raw.get("on"))
    keep = {k: v for k, v in raw.items() if k in ("awards", "characters")}
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


def cfg_text(game_elf, awards=None, characters=None, sites=(), values=None):
    """``coop.cfg`` for the card whose game program is *game_elf* (bytes): co-op on, the right flipper button,
    (PAD-1028) an ``award`` line for each award ticked (*awards*: the project's choices, :func:`load_awards`) and
    (PAD-1031) the characters' lines (*characters*: :func:`load_characters`; *sites*: the port's site names)."""
    buttons = _SMo.flipper_buttons(game_elf)
    if len(buttons) != 2:
        raise CoopError(NO_BUTTON)
    return ("coop on\nbutton %d\n" % buttons[1] + "".join(line + "\n" for line in award_lines(game_elf, awards))
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
#: the presets beside this module: ``coop_presets/<title stem>.json`` (the customization file per game)
PRESET_DIR = "coop_presets"

#: (key, words the pick shows, what it does, how): how is ("adj", adjustment name, "x<pct>" | "min" | "max"),
#: ("cache", adjustment name, "min" | ...): an adjustment the game copies into a player's record at the game's start
#: (the port's ``coop_cache_<id>`` names the copy), ("boost", pct): the port's ``coop_boost`` call adds pct %,
#: ("gift", adjustment name): the game's own one-shot feature at the pick (the port's ``coop_adj_changed``),
#: ("count", name, n): a rule's count for the player raised by n at the pick (the port's ``coop_count_<name>``), or
#: ("save", seconds)
ABILITIES = (
    ("longer_save", "LONGER BALL SAVE",
     "The ball save at each of their balls lasts twice the game's BALL SAVE TIME (at most its top).",
     ("adj", "AD_BALL_SAVE_TIME", "x200")),
    ("action_save", "ACTION BUTTON BALL SAVE",
     "A 10 second ball save when they press the Action button twice quickly, once a ball.", ("save", 10)),
    ("heat_ray", "EASIER HEAT RAY", "The heat ray needs half the spinner spins a level (HEAT RAY SPINS PER LEVEL).",
     ("adj", "AD_HEAT_RAY_SPINS_PER_LEVEL", "x50")),
    ("battles", "EASIER BATTLES", "The ramps light a battle as on the game's easiest LIGHT BATTLE DIFFICULTY.",
     ("cache", "AD_LIGHT_BATTLE_DIFFICULTY", "min")),
    ("building", "EASIER BUILDING MB", "Building Multiball is as easy to start as on the game's easiest BUILDING "
     "DIFFICULTY.", ("cache", "AD_BUILDING_DIFFICULTY", "min")),
    ("powerups", "DOUBLE POWER-UPS", "Every Godzilla power-up the game gives counts twice.", ("boost", 200)),
    ("ally", "STARTS WITH AN ALLY", ("An ally is lit when they pick: the next of Mothra, Rodan and Anguirus in the game's own order (its LIGHT "
      "ALLY)."),
     ("gift", "AD_LIGHT_ALLY")),
    ("jets", "STARTS WITH 4 JETS", "Four jet fighters count as destroyed when they pick (JET FIGHTER CHAMPION and "
     "the bonus count them).", ("count", "jets", 4)),
    ("spot", "SPOT A BATTLE SHOT", "Two quick presses of the Action button during a battle count as its next lit "
     "shot, once a ball.", ("spot", "coop_battle_rules")),
    ("tier2", "TIER 2 AFTER A BATTLE", "Once a tier-1 battle has started on their turn, every battle on the selection "
     "screen is open while they are up, tier 2 included (the game's UNLOCK ALL MONSTER BATTLES).",
     ("unlock", "AD_BATTLE_UNLOCK_ALL_MONSTER_BATTLES", "coop_tier1_rules")),
    ("tanks", "STARTS WITH 4 TANKS", "Four tanks count as destroyed when they pick: the city map's TANKS n/10 starts "
     "at 4.", ("count", "tanks", 4)),
)
#: why an ability is not offered on a card
NO_ADJ = "%s's game program has no %s setting."
NO_ACTION = "%s has no Action button."
NO_SITE = "The app does not know where %s keeps this yet."

_ACTION = re.compile(r"^(LOCKDOWN|ACTION) BUTTON( \(OPTIONAL\))?$")


def action_button(game_elf):
    """The switch id of the Action button (the lockdown bar's: LOCKDOWN BUTTON, ACTION BUTTON) in the game program
    *game_elf* (bytes), or None."""
    from . import portgen as G
    from . import portswitch as PS
    try:
        sws = PS.switches(G.Elf(bytes(game_elf)))
    except (G.PortgenError, ValueError, struct.error, IndexError):
        return None
    for sw in sws:
        if _ACTION.match(" ".join(str(sw["name"]).upper().split())):
            return int(sw["id"])
    return None


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
        cfg, why = "", ""
        if how[0] == "save":
            cfg, why = ("save:%d" % how[1], "") if action is not None else ("", NO_ACTION % label)
        elif how[0] == "boost":
            cfg, why = ("boost:%d" % how[1], "") if "coop_boost" in sites else ("", NO_SITE % label)
        elif how[0] == "spot":
            rules = values.get(how[1])
            cfg, why = (("spot:0x%x" % rules, "") if rules and action is not None and "shot_dispatch" in sites
                        else ("", NO_ACTION % label if action is None else NO_SITE % label))
        elif how[0] == "count":
            cfg, why = (("count:%s+%d" % (how[1], how[2]), "")
                        if {"coop_count_%s" % how[1], "coop_count_%s_rule" % how[1]} & sites
                        else ("", NO_SITE % label))
        else:
            idx = table.by_name.get(how[1]) if table is not None else None
            if idx is None:
                why = NO_ADJ % (label, how[1][3:].replace("_", " "))
            elif how[0] == "unlock":
                rules = values.get(how[2])
                cfg, why = ("unlock:%d@0x%x" % (idx, rules), "") if rules else ("", NO_SITE % label)
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
        out.append({"key": key, "words": words, "does": does, "cfg": cfg, "why": why})
    return out


def clean_name(name):
    """A character's name as the top line shows it: capitals, one space between words, no ``|``, at most
    :data:`MAX_NAME`."""
    return " ".join(str(name or "").upper().replace("|", " ").split())[:MAX_NAME]


def load_characters(project):
    """The project's characters: ``{"pick": bool, "list": [{"name", "ability", "picture"}]}`` (``ability`` a key of
    :data:`ABILITIES` or ``""``; ``picture`` the owner's file, for the pick screens that show one)."""
    if not project:
        return {"pick": False, "list": []}
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return {"pick": False, "list": []}
    return _characters(raw.get("characters") if isinstance(raw, dict) else None)


def _characters(got):
    if not isinstance(got, dict):
        return {"pick": False, "list": []}
    out = []
    for c in got.get("list") or []:
        if isinstance(c, dict) and clean_name(c.get("name")):
            out.append({"name": clean_name(c.get("name")), "ability": str(c.get("ability") or ""),
                        "picture": str(c.get("picture") or "")})
    return {"pick": bool(got.get("pick")), "list": out[:MAX_CHARACTERS]}


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
    """coop.cfg's character lines: ``pick on``, ``left``/``action`` (the buttons the pick and the save use) and
    ``character <abilities> <name>|<what it does>`` for each character, an ability the card cannot have left out
    (``-``). None when *characters* has no pick or no characters."""
    chars = _characters(characters)
    if not chars["pick"] or not chars["list"]:
        return []
    by_key = {a["key"]: a for a in abilities(game_elf, sites=sites, values=values)}
    out = ["pick on"]
    buttons = _SMo.flipper_buttons(game_elf)
    if len(buttons) == 2:
        out.append("left %d" % buttons[0])
    action = action_button(game_elf)
    if action is not None:
        out.append("action %d" % action)
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
    return {"game": str(raw.get("game") or ""), "characters": _characters({"pick": True, "list": raw["characters"]})}


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
    out = []
    for i, c in enumerate(chars["list"] + [{"name": "RANDOM", "ability": "", "picture": ""}]):
        node = SCREEN_NODE % ("Random" if i == len(chars["list"]) else i + 1)
        path = picture_path(project, c)
        art = MA.load_art(path) if path else MA.panel_art(c["name"], PANEL_COLOR, TITLE_COLOR)
        x, y, words_at = MA.screen_place(art)
        if words_at is not None:
            art = MA.band_art(art)
        does = (words_for or {}).get(c["ability"], "") if c["ability"] else ""
        words = c["name"] if i == len(chars["list"]) else (c["name"] + (" - " + does if does else ""))
        out.append(dict(name=node, art_rgba=art, words=words[:60], words_name=node + "_Words", x=x, y=y,
                        words_at=words_at))
    return out


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
    screens = pick_screens(project, characters, words_for)
    if not screens:
        return b""
    s = screens[max(0, min(int(index), len(screens) - 1))]
    glass = Image.new("RGBA", (1360, 768), (12, 12, 16, 255))
    art = Image.fromarray(np.asarray(s["art_rgba"], dtype=np.uint8), "RGBA")
    glass.alpha_composite(art, (int(s["x"]), int(s["y"])))
    from PIL import ImageDraw
    d = ImageDraw.Draw(glass)
    wx, wy = s["words_at"] if s["words_at"] is not None else (20.0, art.height + 50.0)
    d.text((int(s["x"] + wx), int(s["y"] + wy - 40)), s["words"], fill=(255, 230, 0, 255),
           font=MA._fit_font(d, s["words"], 1300 - int(s["x"] + wx), 34))
    buf = io.BytesIO()
    glass.convert("RGB").save(buf, "PNG")
    return buf.getvalue()
