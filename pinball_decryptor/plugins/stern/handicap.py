"""A handicap for each player on a Spike 2 card (PAD-1033; sdk/MODE_SDK.md "Handicaps";
docs/plans/pad1033_handicaps.md).

DoomWalrus666 (Godzilla): "select a handicap level on single player or multiplayer. 0 = standard settings, 1 =
qualify battle is easy, ballsave slightly longer, 2 = same as 1 plus easier to qualify heat ray ... -1 = harder
settings ... -3 = hardest settings. This should be able to be selected by player", without disconnecting from Insider
Connected ("You can change this difficulty settings in the service menu"), and "PAD can estimate what settings make
the most sense for each difficulty handicap setting".

So a level is a set of the game's own adjustments read easier or harder while that player is up (pad_mode_runtime.c
"a handicap for each player": the adjustment getter answers them; NVRAM never changes). Each player picks theirs with
the flippers at their first ball. Like the operator's own settings, a handicap leaves the card on Insider Connected.

The levels are worked out of the card's own program (:func:`levels`): the ball save time, and every adjustment the game
names ``..._DIFFICULTY`` (the lowest value the easiest, as every Spike 2 game's menu has them: "EASY allows ...",
"Easy = carryover ..."), a step a level; Godzilla's follow the reporter's list (:data:`GODZILLA`). The Modes tab's tick
(the sidecar's ``handicap: {"on": true}``) puts ``handicap.cfg`` beside the runtime, and the service menu gets a
HANDICAP row (Off/On, :mod:`.menu_settings`) when a spare setting is left for it."""
import struct

from . import sound_modes as _SMo

#: the project sidecar's key: ``{"on": true}``
STAGED_KEY = "handicap"
#: the runtime's file beside it on the card
CFG_NAME = "handicap.cfg"
#: the port lines the runtime needs: the adjustment getter and the player bytes (portcoop.py's)
PORT_SITES = ("adjustment",)
PORT_DATA = ("coop_player", "cur_player")
#: the levels, hardest to easiest; 0 is the operator's own settings
LEVELS = (-3, -2, -1, 1, 2, 3)
#: the runtime's most changes a level (HAND_CHANGES)
MAX_CHANGES = 24
#: the most steps a difficulty adjustment may have to be one of the game's levels, not a count
MAX_STEPS = 10

BALL_SAVE = "AD_BALL_SAVE_TIME"
#: seconds of ball save a level's step
BALL_SAVE_STEP = 2

LABEL = "Handicap per player"
NO_TITLE = "The app cannot tell which game this project is for, so it cannot give it handicaps."
NO_PORT = "The app does not know where %s keeps its players and settings yet, so it cannot give it handicaps."
NO_BUTTON = "The game program names no flipper buttons, so a player could not pick a handicap."
NOTHING = "%s has no ball save or difficulty setting a handicap could change."
#: the service menu's row (menu_settings.HANDICAP): Off/On, On to start with
MENU_VALUES = 2
MENU_HELP = "On: each player picks -3 to +3 at their first ball (flippers)"
#: how a player picks, for the tab and the log
HOW = ("at each player's first ball the top of the screen shows P1 HANDICAP 0: the left flipper button makes it "
       "harder, the right easier (-3 to +3), and the ball's first score takes it")

#: the Modes tab's line under the tick
NOTE = ("On the card: each player picks -3 to +3 at their first ball with the flippers. HANDICAP in the service menu "
        "switches it, On to start with.")

#: Godzilla (Pro, Premium/LE): the reporter's levels - battles first, then the heat ray and Building Multiball, then
#: tanks, the bridge, the powerline and the jets; harder the same way round. ``(adjustment, (level -> change))`` where a
#: change is ``("+"/"-", n)`` steps from the operator's own value or ``("x", pct)``. AD_LIGHT_BATTLE_DIFFICULTY and
#: AD_BUILDING_DIFFICULTY are copied into each player's record at the game's start: the port's coop_cache lines.
GODZILLA = (
    (BALL_SAVE, {-3: ("-", 15), -2: ("-", 2), -1: ("-", 1), 1: ("+", 2), 2: ("+", 4), 3: ("+", 6)}),
    ("AD_LIGHT_BATTLE_DIFFICULTY", {-3: ("+", 2), -2: ("+", 1), -1: ("+", 1), 1: ("-", 1), 2: ("-", 2), 3: ("-", 2)}),
    ("AD_HEAT_RAY_SPINS_PER_LEVEL", {-3: ("x", 150), -2: ("x", 125), 2: ("x", 60), 3: ("x", 40)}),
    ("AD_BUILDING_DIFFICULTY", {-3: ("+", 2), -2: ("+", 1), 2: ("-", 1), 3: ("-", 2)}),
    ("AD_TANK_ATTACK_QUALIFY_DIFFICULTY", {-3: ("+", 2), 3: ("-", 2)}),
    ("AD_BRIDGE_ATTACK_DIFFICULTY", {-3: ("+", 2), 3: ("-", 2)}),
    ("AD_BRIDGE_ATTACK_MULTIBALL_DIFFICULTY", {-3: ("+", 2), 3: ("-", 2)}),
    ("AD_POWERLINE_ATTACK_QUALIFY_DIFFICULTY", {-3: ("+", 1), 3: ("-", 1)}),
    ("AD_JET_FIGHTER_ATTACK_DIFFICULTY", {-3: ("+", 1), 3: ("-", 1)}),
    ("AD_MECHAGODZILLA_SPINS_DIFFICULTY", {-3: ("+", 1), 3: ("-", 1)}),
    ("AD_MECHAGODZILLA_SHIELD_DIFFICULTY", {-3: ("+", 1), 3: ("-", 1)}),
)
#: a title's own levels in place of the worked-out ones, by its title key's stem
PRESETS = {"godzilla_": GODZILLA}


class HandicapError(ValueError):
    """The card's game program cannot take handicaps; the message says why."""


def load(project):
    """Whether the project's sidecar asks for handicaps."""
    if not project:
        return False
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: no
        return False
    return bool(isinstance(raw, dict) and raw.get("on"))


def save(project, on):
    """Ask (or stop asking) for handicaps; returns what it was before."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    was = bool(isinstance(data.get(STAGED_KEY), dict) and data[STAGED_KEY].get("on"))
    if on:
        data[STAGED_KEY] = {"on": True}
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return was


def title_refusal(prof):
    """Why ``prof``'s title cannot have handicaps, or ``""``."""
    if prof is None:
        return NO_TITLE
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


def _ranges(game_elf):
    """``{name: (id, lo, hi)}`` of the game's adjustments."""
    from .adjustments import OFF_MAX, OFF_MIN, AdjustmentTable
    t = AdjustmentTable(bytes(game_elf))
    out = {}
    for name, i in t.by_name.items():
        desc = t._off(t.table_va + i * t.elem)
        if desc is None:
            continue
        lo, hi = (struct.unpack_from("<i", t.data, desc + o)[0] for o in (OFF_MIN, OFF_MAX))
        out[name] = (i, lo, hi)
    return out


def _worked_out(ranges):
    """The levels of a game with no preset, the reporter's way: ball save 2 s a level (down to none at -3), and the
    game's ``..._DIFFICULTY`` adjustments in by thirds - level 1 the first third of them a step toward its lowest
    (easiest) value, level 2 two thirds two steps, level 3 every one three steps (each held to its own range); the
    harder levels the same way toward the highest."""
    rows = []
    if BALL_SAVE in ranges:
        rows.append((BALL_SAVE, {-3: ("-", 15), -2: ("-", 2), -1: ("-", 1), 1: ("+", 2), 2: ("+", 4), 3: ("+", 6)}))
    hard = [name for name in sorted(ranges, key=lambda n: ranges[n][0])
            if name.endswith("_DIFFICULTY") and 0 <= ranges[name][1] < ranges[name][2]
            and ranges[name][2] - ranges[name][1] <= MAX_STEPS]
    for k, name in enumerate(hard):
        first = 1 + 3 * k // len(hard)                  # the first level that has it: 1, 2 or 3
        rows.append((name, {lv: ("-" if lv > 0 else "+", abs(lv)) for lv in LEVELS if abs(lv) >= first}))
    return tuple(rows)


def levels(game_elf, title_key=""):
    """``{level: [(adjustment name, id, op, n, lo, hi), ...]}`` for the levels -3..3 but 0: what each level reads, from
    the title's preset (:data:`PRESETS`) or worked out of the program; only adjustments this program has, each held to
    its own range. Raises :class:`HandicapError` when there is nothing to change."""
    ranges = _ranges(game_elf)
    rows = next((p for stem, p in PRESETS.items() if title_key.startswith(stem)), None) or _worked_out(ranges)
    out = {lv: [] for lv in LEVELS}
    for name, per in rows:
        if name not in ranges:
            continue
        i, lo, hi = ranges[name]
        if lo < 0 or hi <= lo:
            continue
        for lv, (op, n) in per.items():
            if len(out[lv]) < MAX_CHANGES:
                out[lv].append((name, i, op, int(n), lo, hi))
    if not any(out.values()):
        raise HandicapError(NOTHING % (title_key or "This game"))
    return out


def level_line(lv, changes):
    """The ``level`` line of handicap.cfg for one level (the runtime's adj: changes)."""
    return "level %+d %s" % (lv, ",".join("adj:%d%s%d:%d:%d" % (i, op, n, lo, hi)
                                          for _name, i, op, n, lo, hi in changes))


#: the runtime's most records (HAND_CACHES)
MAX_RECORDS = 16


def cfg_text(game_elf, title_key="", setting=0, only=False, port=None):
    """``handicap.cfg`` for the card whose game program is *game_elf* (bytes): the flipper buttons, *setting* (the
    service menu's HANDICAP row's live value, 0 none: always on), *only* when the card carries no modes, a ``record``
    line for each of the levels' adjustments the game keeps in a player's own record (:func:`records`, with *port*'s
    getter and player byte) and a line for each level."""
    buttons = _SMo.flipper_buttons(game_elf)
    if len(buttons) != 2:
        raise HandicapError(NO_BUTTON)
    lv = levels(game_elf, title_key)
    recs = {}
    site, data = (port or {}).get("site", {}).get("adjustment"), (port or {}).get("data", {}).get("coop_player")
    if site and data:
        from . import portgen as G
        ids = sorted({c[1] for k in LEVELS for c in lv[k]})
        try:
            recs = records(game_elf, site[0], data, ids)
        except (G.PortgenError, ValueError, IndexError):
            recs = {}                                   # the getter's answer is what plays
    return ("# PAD-1033: a handicap for each player\nhandicap on\nleft %d\nright %d\n" % tuple(buttons)
            + ("setting 0x%08x\n" % setting if setting else "") + ("only\n" if only else "")
            + "".join("record %d 0x%08x 0x%08x 0x%08x 0x%x\n" % ((i,) + recs[i])
                      for i in sorted(recs)[:MAX_RECORDS])
            + "".join(level_line(k, lv[k]) + "\n" for k in LEVELS if lv[k]))


def _words(name):
    w = name[3:] if name.startswith("AD_") else name
    return " ".join(w.split("_")).title()


def describe(game_elf, title_key=""):
    """``[(level, [words, ...]), ...]``: what each level does, for the Modes tab (hardest first)."""
    out = []
    for lv, changes in sorted(levels(game_elf, title_key).items()):
        said = []
        for name, _i, op, n, _lo, _hi in changes:
            if name == BALL_SAVE:
                said.append("ball save %s" % ("off" if op == "-" and n >= 15 else "%s%d s" % (op, n)))
            elif op == "x":
                said.append("%s x%s" % (_words(name), ("%.2f" % (n / 100.0)).rstrip("0").rstrip(".")))
            else:
                said.append("%s %s" % (_words(name), "easier" if op == "-" else "harder")
                            + (" by %d" % n if n > 1 else ""))
        out.append((lv, said))
    return out


#: why the Modes tab cannot list a project's levels
NO_CARD = ("The app works the levels out of the game program on the card, and this project's card image is not on "
           "this computer. Write works them out of the card it writes.")


def project_levels(project):
    """``(why, [(level, [words, ...]), ...])`` for the Modes tab: :func:`describe` of the project's card's game program,
    cached per card; ``why`` says why there are none ("" when there are)."""
    import hashlib
    import json
    import os
    from . import mode_project as MP
    from . import title_reader as TR
    got = MP.project_card(project) if project else None
    card = getattr(got, "image", "") if got is not None else ""
    if not card or not os.path.isfile(card):
        return NO_CARD, []
    prof = project_title(project)
    title = _SMo.title_key(prof)
    key = "%s|%d|%d|%s" % (card, os.path.getsize(card), int(os.path.getmtime(card)), title)
    cache = os.path.join(TR.cache_dir("handicap_levels"), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")
    try:
        with open(cache, encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("key") == key and raw.get("v") == 1:
            return "", [(lv, list(words)) for lv, words in raw["levels"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        said = describe(TR.game_program(card)[2], title)
    except HandicapError as e:
        return str(e), []
    except Exception as e:                              # noqa: BLE001 - an unreadable card: say so
        return "The game program could not be read from the card: %s" % e, []
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "key": key, "levels": said}, f)
    except OSError:
        pass
    return "", said


# ---- the records a game copies an adjustment into, one a player ------------------------------------------------------
# Godzilla reads LIGHT BATTLE DIFFICULTY once, at a player's first ball, in a method of the battle rule that keeps it in
# the player's own record (LE 1.16 0x12406c):
#     push {r3-r7, lr} ; mov r4, r0 ; mov r0, #0xad ; ... ; bl adjustment ; ... ; mov r7, r0 ; bl player ;
#     add r0, r4, r0, lsl #2 ; str r7, [r0, #0x10]
# (player: movw r3 / movt r3 = the player byte ; ldrb r0, [r3] ; bx lr). Its tanks, bridge, powerline, jets and
# Mechagodzilla difficulties are kept the same way, so the getter's answer never reaches them after that read. The
# runtime hooks each such method to learn the rule's object and writes the player's record at their pick
# (`record <id> <method> <w0> <w1> <at>`: the record is this + player x 4 + at, the player 1-based).

def _bl_target(va, w):
    off = (w & 0x00FFFFFF) << 2
    if off & 0x02000000:
        off -= 0x04000000
    return (va + 8 + off) & 0xFFFFFFFF


def _mov_r0_imm(w):
    """The value of ``mov r0, #imm`` / ``movw r0, #imm``, or None."""
    if (w & 0xFFFFF000) == 0xE3A00000:
        rot, v = ((w >> 8) & 0xF) * 2, w & 0xFF
        return ((v >> rot) | (v << (32 - rot))) & 0xFFFFFFFF if rot else v
    if (w & 0xFFF0F000) == 0xE3000000:
        return ((w >> 4) & 0xF000) | (w & 0xFFF)
    return None


def _player_getters(elf, player_va):
    """The functions that only answer the player byte: ``movw r3 / movt r3 = player ; ldrb r0, [r3] ; bx lr``."""
    lo, hi = player_va & 0xFFFF, player_va >> 16
    movw = 0xE3003000 | ((lo & 0xF000) << 4) | (lo & 0xFFF)
    movt = 0xE3403000 | ((hi & 0xF000) << 4) | (hi & 0xFFF)
    words = elf.words
    out = set()
    for i in range(len(words) - 3):
        if words[i] == movw and words[i + 1] == movt and words[i + 2] == 0xE5D30000 and words[i + 3] == 0xE12FFF1E:
            out.add(elf.tva + 4 * i)
    return out


def records(game_elf, getter_va, player_va, ids):
    """``{id: (method va, word 0, word 1, at)}``: for each adjustment of *ids* (the levels'), the one method that reads
    it (``mov r0, #id`` and a call to the getter at *getter_va*) and keeps it in the player's own record (a call to a
    function answering the byte at *player_va*, ``add r0, <this>, r0, lsl #2``, ``str <it>, [r0, #off]``; a ``sub r0,
    r0, #1`` between makes the index 0-based: at = off - 4), its ``this`` the method's r0. An id read so in more than
    one method, or in none, is left out (the getter's answer is what plays)."""
    from . import portgen as G
    elf = G.Elf(bytes(game_elf))
    words, tva = elf.words, elf.tva
    players = _player_getters(elf, player_va)
    want = set(ids)
    found = {}
    for i, w in enumerate(words):
        if (w & 0xFF000000) != 0xEB000000 or _bl_target(tva + 4 * i, w) != getter_va:
            continue
        ident = next((_mov_r0_imm(words[k]) for k in (i - 1, i - 2, i - 3) if k >= 0
                      and _mov_r0_imm(words[k]) is not None), None)
        if ident not in want:
            continue
        hit = _record_after(words, tva, i, players)
        if hit is None:
            continue
        at, this = hit
        start = _method_start(words, i)
        if start is None or not _moves_r0_to(words, start, i, this):
            continue
        found.setdefault(ident, set()).add((tva + 4 * start, words[start], words[start + 1], at))
    return {k: next(iter(v)) for k, v in found.items() if len(v) == 1}


def _record_after(words, tva, i, players):
    """``(at, this register)`` of the record store after the getter call at word *i*, or None: the answer kept in a
    register (``mov rV, r0``), a call to the player function, ``add rD, rT, r0, lsl #2`` (a ``sub r0, r0, #1`` before
    it: 0-based) and ``str rV, [rD, #off]`` at most two words on (Godzilla LE 1.16: 0x12406c, 0x15c7a8, 0x1685a4)."""
    held = 0                                    # the getter's answer is in r0 until a `mov rV, r0`
    for k in range(i + 1, min(len(words), i + 8)):
        w = words[k]
        if (w & 0xFFFF0FFF) == 0xE1A00000 and held == 0:        # mov rV, r0
            held = (w >> 12) & 0xF
            continue
        if not held and (w & 0x0C00F000) == 0 and (w & 0x0E000000) in (0x00000000, 0x02000000):
            return None                                         # r0 written before it was kept
        if (w & 0xFF000000) == 0xEB000000 and _bl_target(tva + 4 * k, w) in players and held:
            j, base = k + 1, 0
            if words[j] == 0xE2400001:                          # sub r0, r0, #1: 0-based
                j, base = j + 1, -4
            a = words[j]
            if (a & 0xFFF00FFF) != 0xE0800100:                  # add rD, rT, r0, lsl #2
                return None
            dest, this = (a >> 12) & 0xF, (a >> 16) & 0xF
            for q in (j + 1, j + 2):
                st = words[q]
                if (st & 0xFFFFF000) == 0xE5800000 | (dest << 16) | (held << 12):   # str rV, [rD, #off]
                    return (st & 0xFFF) + base, this
                if ((st >> 12) & 0xF) in (dest, held):          # either written first: not this shape
                    return None
            return None
    return None


def _method_start(words, i):
    """The word of the ``push {.., lr}`` that opens the method holding word *i* (within 64 words), or None."""
    for k in range(i - 1, max(-1, i - 64), -1):
        w = words[k]
        if (w & 0xFFFF4000) == 0xE92D4000:
            return k
        if w == 0xE12FFF1E or (w & 0xFFFF8000) == 0xE8BD8000:  # bx lr / pop {.., pc}: another function's end
            return None
    return None


def _moves_r0_to(words, start, i, reg):
    """The method keeps its r0 (``this``) in *reg* before word *i*, and nothing between writes *reg* again."""
    for k in range(start + 1, i):
        w = words[k]
        if w == 0xE1A00000 | (reg << 12):                       # mov reg, r0
            return all(((words[j] >> 12) & 0xF) != reg or (words[j] & 0x0C000000) == 0x04000000
                       and not (words[j] & 0x00100000) for j in range(k + 1, i))
    return False
