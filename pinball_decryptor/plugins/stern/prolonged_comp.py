"""Prolonged Competition on a Spike 2 card's start menu (PAD-1041; sdk/MODE_SDK.md "Prolonged Competition",
pad_mode_runtime.c "Prolonged Competition on the start menu").

Joe_Blasi (Pinside): "can the prolonged comp (in player menu) be added to all games?" Venom and Dungeons & Dragons
offer it on CHOOSE YOUR MODE OF PLAY (both flipper buttons in attract): COMPETITION GAME PLAY UNTIL POWERED OFF. Picked
once, every game after it plays as Competition until the machine is switched off; picked again, it ends. Every other
Spike 2 game has only the one-game COMPETITION entry, which sets one flag, FG_PLAYER_COMPETITION_MODE_ACTIVE, and
nothing else (the menu's kind jump, read on all 53 latest builds). The mode runtime adds a PROLONGED entry to that menu
and keeps the flag set at every game's start while it is on.

The Modes tab's tick (the project sidecar's ``prolonged_comp: {"on": true}``) puts ``comp.cfg`` beside the runtime: the
flag's id and the menu's COMPETITION and STANDARD captions, read off the card's own game program (:func:`cfg_text`).
Like the game's own Competition, it keeps the card on Insider Connected."""
import re

#: the project sidecar's key: ``{"on": true}``
STAGED_KEY = "prolonged_comp"
#: the runtime's file beside it on the card
CFG_NAME = "comp.cfg"
#: the port lines the runtime needs: the start menu's (portchallenge.py's) and the event bus
PORT_SITES = ("challenge_menu", "challenge_menu_pick", "hook_dispatch")
PORT_VALUES = ("challenge_menu_list_at", "challenge_menu_cap")
PORT_EVENTS = ("game_start", "ball_start")
#: the titles with a Prolonged Competition of their own: they keep theirs, by their title keys' stems
OWN = ("venom_", "dungeons_and_dragons_")
FLAG = "FG_PLAYER_COMPETITION_MODE_ACTIVE"

LABEL = "Prolonged Competition"
NO_TITLE = "The app cannot tell which game this project is for, so it cannot give it Prolonged Competition."
OWN_ONE = "%s has Prolonged Competition on its start menu already."
NO_PORT = ("The app does not know %s's start menu yet, so it cannot add Prolonged Competition to it.")
NO_FLAG = "The game program names no %s flag, so there is no Competition game to prolong." % FLAG
NO_CAPTION = "The game program's start menu has no COMPETITION and STANDARD captions to show the entry with."
#: how a player uses it, for the tab and the log
HOW = ("hold both flipper buttons in attract to open the start menu: COMPETITION / UNTIL POWERED OFF makes every game "
       "a Competition game until the machine is switched off, and STANDARD / ENDS PROLONGED COMPETITION ends it")
#: the Modes tab's line under the tick
NOTE = "On the card: COMPETITION / UNTIL POWERED OFF on the start menu. Picked again, it ends."


class CompError(ValueError):
    """The card's game program cannot take Prolonged Competition; the message says why."""


def load(project):
    """Whether the project's sidecar asks for it."""
    if not project:
        return False
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: no
        return False
    return bool(isinstance(raw, dict) and raw.get("on"))


def save(project, on):
    """Ask (or stop asking) for it; returns what it was before."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    was = bool(isinstance(data.get(STAGED_KEY), dict) and data[STAGED_KEY].get("on"))
    if on:
        data[STAGED_KEY] = {"on": True}
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return was


def port_ready(port):
    """1 when a parsed port names the start menu and the events the runtime keeps the flag set at."""
    if not port:
        return False
    sites, values = port.get("site", {}), port.get("value", {})
    events = {e[0] for e in port.get("event", ()) if len(e) > 1 and e[1] == "bus"}   # on the bus, as the runtime's
    menu = (all(s in sites for s in PORT_SITES) and all(v in values for v in PORT_VALUES)
            and ("challenge_menu_count_at" in values or "challenge_menu_count_reg" in values))
    frame = (FRAME_SITE in sites and all(v in values for v in FRAME_VALUES)     # round 2: a menu of indices,
             and all(d in port.get("data", {}) for d in ("message_count", "message_remap", "message_table")))   # lettered
    obj = all(s in sites for s in OBJ_SITES) and all(v in values for v in OBJ_VALUES)   # Bond 60th's menu object
    return ((menu or frame or obj) and "hook_dispatch" in sites and "game_flags" in port.get("data", {})
            and all(e in events for e in PORT_EVENTS))


def title_refusal(prof):
    """Why ``prof``'s game cannot have it (or has its own), or ``""``."""
    if prof is None:
        return NO_TITLE
    if prof.key.startswith(OWN):
        return OWN_ONE % prof.label
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_PORT % prof.label
    return "" if port_ready(port) else NO_PORT % prof.label


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def card_lines(game_elf):
    """``(flag, caption, caption_end)`` read off the card's game program: the Competition flag's id (the FG_ name
    table's index) and the start menu's COMPETITION and STANDARD caption message ids (the first of each after CHOOSE
    YOUR MODE OF PLAY's). Raises :class:`CompError`."""
    from . import portchallenge as PC
    try:
        e = PC.Elf(game_elf)
    except Exception as ex:                             # noqa: BLE001 - not an ELF the reader knows
        raise CompError("the card's game program could not be read (%s)" % ex) from None
    names = PC.flag_names(e)
    if FLAG not in names:
        raise CompError(NO_FLAG)
    table, n = PC.message_table(e)
    head = None
    if table:
        head = next((i for i in range(n) if PC.message_text(e, table, i) == "CHOOSE YOUR MODE OF PLAY"), None)
    if head is None:
        raise CompError(NO_CAPTION)

    def caption(words):
        return next((i for i in range(head, min(n, head + 40)) if PC.message_text(e, table, i) == words), None)
    comp, std = caption("COMPETITION"), caption("STANDARD")
    if comp is None or std is None:
        raise CompError(NO_CAPTION)
    return names.index(FLAG), comp, std


def cfg_text(game_elf, only):
    """``comp.cfg`` for the card's game program; *only* when the card carries no modes (the runtime then arms this
    and nothing else). Raises :class:`CompError`."""
    flag, comp, std = card_lines(game_elf)
    return ("# PAD-1041: Prolonged Competition on the start menu\ncomp on\nflag %d\ncaption %d\ncaption_end %d\n%s"
            % (flag, comp, std, "only\n" if only else ""))


def cfg_values(text):
    """The numbers a ``comp.cfg`` names, by key (for the tests and the build's log)."""
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"(?m)^(flag|caption|caption_end) (\d+)$", text or "")}


# ---- round 2: the menus of game-mode table indices ---------------------------------------------------------------
# Godzilla, Jaws, John Wick, King Kong, Metallica and X-Men build their start menu as a list of GAME-MODE TABLE INDICES
# on the menu function's stack (PAD-619/686), not entries of their own. Every frame the loop reads the buttons, moves
# the cursor, applies the index under it live and draws that index's caption and name messages. The frame point is
# one shape on all of them:
#   add r3, sp, #T ; [vmov] ; add r3, r3, rC, lsl #2 ; ldr r3, [r3, #-back] ; cmp r3, #1 ; ...
#   tst rB, #4 (left: the cursor back, wrapping) ... tst rB, #2 (right) ; ldr rX, [sp, #count] ; [sub rX, rX, #1] ; cmp
# Metallica keeps the LAST index in its count slot (no sub). The list holds as many as the game-mode table has entries.
# Each index's table entry names its caption and name messages; Competition's is the entry of the Competition flag
# alone (COMPETITION / ALL RANDOMNESS REMOVED), Standard's the plain one (STANDARD / NORMAL PLAY).
FRAME_SITE = "comp_menu_frame"
#: Bond 60th LE 1.11's start menu is an object filled by an add function (pad_mode_runtime.c "Bond 60th's start menu")
OBJ_SITES = ("comp_menu_obj_built", "comp_menu_obj_pick", "comp_menu_obj_add_fn")
OBJ_VALUES = ("comp_menu_obj_reg", "comp_menu_obj_pick_reg", "comp_menu_obj_vec", "comp_menu_obj_index",
              "comp_menu_obj_kind", "comp_menu_obj_end_kind")
FRAME_VALUES = ("comp_menu_frame_list_at", "comp_menu_frame_count_at", "comp_menu_frame_cap",
                "comp_menu_frame_cursor_reg", "comp_menu_index", "comp_menu_index_msg", "comp_menu_end_index",
                "comp_menu_end_msg")


def _frame_points(e):
    from . import portchallenge as PC
    w, base, out = e.words, e.text_va, []
    for k in range(2, len(w) - 40):
        if not ((w[k] & 0xFFFFFFF0) == 0xE0833100 and (w[k + 1] & 0xFFFF0000) == 0xE5130000):
            continue
        top = [x for x in (w[k - 1], w[k - 2]) if (x & 0xFFFFF000) == 0xE28D3000]
        if not top:
            continue
        tsts = [j for j in range(k + 2, k + 30) if (w[j] & 0xFFF0FF00) == 0xE3100000 and (w[j] & 0xFF) in (2, 4)]
        if len(tsts) < 2 or (w[tsts[0]] & 0xFF, w[tsts[1]] & 0xFF) != (4, 2):
            continue
        count_at = last = None
        for q in range(tsts[1], tsts[1] + 8):
            if (w[q] & 0xFFFF0000) == 0xE59D0000:                   # ldr rX, [sp, #count]
                count_at = w[q] & 0xFFF
                last = not any((x & 0xFFF00FFF) == 0xE2400001 for x in w[q + 1:q + 3])
                break
        if count_at is None:
            continue
        out.append(dict(site=base + 4 * k, w0=w[k], w1=w[k + 1],
                        list_at=PC.rot_imm(top[0] & 0xFFF) - (w[k + 1] & 0xFFF), cursor=w[k] & 0xF,
                        buttons=(w[tsts[0]] >> 16) & 0xF, count_at=count_at, last=last))
    return out


def _index_entries(e):
    """(n, {index: (flag, name message)}) of the build's game-mode table: Godzilla's own 32-byte table, or the
    GamePlayModes adapter's (index, flag, caption, name); (0, {}) when neither is there."""
    from . import portchallenge as PC
    w = e.words
    tables = set()
    for k in range(len(w) - 4):
        x = w[k]
        if x & 0xFFFFFF00 == 0xE3510000 and w[k + 1] & 0xFFF0F000 == 0x93003000 and w[k + 2] & 0xFFF0F000 \
                == 0x93403000 and w[k + 3] == 0x90833281 and w[k + 4] == 0x91D300B4:
            lo = ((w[k + 1] >> 16) & 0xF) << 12 | (w[k + 1] & 0xFFF)
            hi = ((w[k + 2] >> 16) & 0xF) << 12 | (w[k + 2] & 0xFFF)
            tables.add(((hi << 16) | lo, (x & 0xFF) + 1))
    if len(tables) == 1:
        (tbl, n), = tables
        ents = PC._table_entries(e, tbl, n)
        return n, {i: (f, m) for i, (f, f2, m) in enumerate(ents) if not f2}
    tbl, n = PC._gpm_table(e)
    if not tbl:
        return 0, {}
    ents = PC._gpm_entries(e, tbl, n)
    return n, {v["index"]: (v["flag"] or 0, v["msgs"][1] or 0) for v in ents.values() if v["index"] is not None}


def frame_lines(game_elf):
    """The port lines of a game-mode index menu's frame (see above), or [] when the program has none of that shape."""
    from . import portchallenge as PC
    e = PC.Elf(game_elf)
    names = PC.flag_names(e)
    if FLAG not in names:
        return []
    points = _frame_points(e)
    n, ents = _index_entries(e)
    comp = [(i, m) for i, (f, m) in sorted(ents.items()) if f == names.index(FLAG) and m]
    std = [(i, m) for i, (f, m) in sorted(ents.items()) if i and not f and m]
    if len(points) != 1 or not n or not comp or not std:
        return []
    p = points[0]
    return ["# PAD-1041: the start menu of game-mode table indices - Prolonged Competition's entry is Competition's "
            "index again",
            "site  %s %s 0x%08x 0x%08x 0x%08x" % (FRAME_SITE, " " * 6, p["site"], p["w0"], p["w1"]),
            "value comp_menu_frame_list_at    %d" % p["list_at"],
            "value comp_menu_frame_count_at   %d" % p["count_at"],
            "value comp_menu_frame_count_last %d%s" % (1 if p["last"] else 0,
                                                      "   # the count slot holds the last index" if p["last"] else ""),
            "value comp_menu_frame_cap        %d   # the game-mode table's entries" % n,
            "value comp_menu_frame_cursor_reg %d" % p["cursor"],
            "value comp_menu_frame_buttons_reg %d" % p["buttons"],
            "value comp_menu_index            %d   # COMPETITION" % comp[0][0],
            "value comp_menu_index_msg        %d" % comp[0][1],
            "value comp_menu_end_index        %d   # STANDARD" % std[0][0],
            "value comp_menu_end_msg          %d" % std[0][1]]
