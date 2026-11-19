"""PAD-1403: the cabinet buttons as shots on every Spike 2 build - the Action button, the left and right flipper
buttons and the Start button, each as a press, a release and a hold, and the flipper + Action combos (Cyclops'
visor in 20SidedDies' Uncanny X-Men 2.0: "hold a flipper plus the Action button").

Before it only Godzilla had button shots (PAD-228: three `switch` lines in its ports, presses only). Now:

- each title's profile offers :data:`BUTTON_SHOTS` (those its game has: three titles have no Action button,
  :data:`NO_ACTION`) on shot bits nothing of its port uses, highest first (:func:`with_button_shots`), so every
  part of a mode that takes a shot takes a button shot the same way;
- the card's write puts ``buttons.cfg`` beside the mode files (:func:`cfg_text`): one line per button shot,
  ``button <mask> <kind> <switch id> [<second id> | <ms>] <name>``, with the switch ids read off the card's OWN
  game program (``sound_modes.flipper_buttons``, ``coop_play.action_button``, ``handicap.start_button``), so a
  derived or older build gets its own;
- the runtime (pad_mode_runtime.c "PAD-1403") counts each button's press and release edges from the framework's
  switch drain (site switch_edge, which every Spike 2 port names) and, every tick, while a game is played, hands
  the modes: a press at its press edge; a release at its release edge; a hold once, when the button has been held
  that long since its press; a combo at the press that makes both its buttons held (either order).

Census of the newest library builds (C:/tmp/PAD-1403/census.json, 2026-11-18): every one names both flipper
buttons and the Start button; every one but The Beatles, Jurassic Park The Pin and Star Wars ELG names an Action
(LOCKDOWN) button, 34 on all of them.

PAD-1447: Iron Maiden (LE and Pro, every build) names one too, as LOCKDOWN BUTTON (OPTIONAL), but its cabinet has
none (a reporter's machine, as The Beatles'): it is in :data:`NO_ACTION`, and :func:`program_lacks_action` tells its
program apart for the co-op lines that read the button off the program alone. "(OPTIONAL)" is no sign by itself:
TMNT LE names its button so and has one (the Glider).
"""

#: (name, kind, buttons, ms) in the order bits are given: a port with few free bits (King Kong: 9) offers the first
#: ones. Buttons: "action", "left", "right", "start". The names are the shots' names on the Modes tab.
BUTTON_SHOTS = (
    ("Action button", "press", ("action",), 0),
    ("Left flipper button", "press", ("left",), 0),
    ("Right flipper button", "press", ("right",), 0),
    ("Start button", "press", ("start",), 0),
    ("Left flipper + Action button", "combo", ("left", "action"), 0),
    ("Right flipper + Action button", "combo", ("right", "action"), 0),
    ("Action button held 1 s", "hold", ("action",), 1000),
    ("Left flipper button held 1 s", "hold", ("left",), 1000),
    ("Right flipper button held 1 s", "hold", ("right",), 1000),
    ("Action button released", "release", ("action",), 0),
    ("Left flipper button released", "release", ("left",), 0),
    ("Right flipper button released", "release", ("right",), 0),
    ("Both flipper buttons", "combo", ("left", "right"), 0),
    ("Action button held 3 s", "hold", ("action",), 3000),
    ("Left flipper button held 3 s", "hold", ("left",), 3000),
    ("Right flipper button held 3 s", "hold", ("right",), 3000),
    ("Start button held 1 s", "hold", ("start",), 1000),
    ("Start button released", "release", ("start",), 0),
)
NAMES = tuple(n for n, _k, _b, _ms in BUTTON_SHOTS)
_BY_NAME = {n: (k, b, ms) for n, k, b, ms in BUTTON_SHOTS}

#: the titles (game folders) whose cabinets have no Action button: the game programs of the first three name none
#: (the census above); Iron Maiden's names one its cabinet lacks (PAD-1447)
NO_ACTION = frozenset({"beatles", "jurassic_park_the_pin", "star_wars_elg", "iron_maiden_le", "iron_maiden_pro"})

#: PAD-1447: words only the game programs of a :data:`NO_ACTION` title that still names an Action switch carry
_NO_ACTION_MARKS = (b"iron_maiden",)


def program_lacks_action(game_elf):
    """True for a game program (bytes) of a title whose cabinet has no Action button though its switch table names
    one (Iron Maiden: LOCKDOWN BUTTON (OPTIONAL))."""
    data = bytes(game_elf or b"")
    return any(m in data for m in _NO_ACTION_MARKS)

CFG_NAME = "buttons.cfg"

NO_BUTTON = "%s has no %s, so a mode cannot use the shot %s."


def is_button_shot(name):
    return name in _BY_NAME


def buttons_of(name):
    """The buttons shot *name* needs (("action",), ("left", "action"), ...); () for a shot that is not one."""
    return _BY_NAME.get(name, ("", (), 0))[1]


def offered(game):
    """The button shots title *game* (its game folder, ``beatles``) has, in bit order."""
    no_action = str(game or "").strip().lower() in NO_ACTION
    return [s for s in BUTTON_SHOTS if not (no_action and "action" in s[2])]


def with_button_shots(shots, game, arch="arm", reserved=0):
    """``(shots + button shots, button shot names)``: *shots* (``[(name, mask)]``: the port's shots and switch
    shots) with each button shot :func:`offered` for *game* that is not a shot already (Godzilla's ports name the
    Action and flipper buttons' presses as `switch` lines, PAD-228), on the highest bits none of *shots* uses (bit 0
    is the game's "a playfield switch was hit"). A Spike 3 port (*arch* ``a64``) gets none: its edges carry the
    switch shots (PAD-1322), but a button shot was never run there."""
    shots = list(shots)
    if arch == "a64":
        return tuple(shots), ()
    used = 1 | int(reserved)
    for _n, m in shots:
        used |= int(m)
    have = {n for n, _m in shots}
    free = [1 << b for b in range(63, 0, -1) if not used & (1 << b)]
    names = []
    for name, _kind, _btns, _ms in offered(game):
        if name in have:
            continue
        if not free:
            break
        shots.append((name, free.pop(0)))
        names.append(name)
    return tuple(shots), tuple(names)


def switch_ids(game_elf):
    """``{"action": id, "left": id, "right": id, "start": id}`` of the game program *game_elf* (bytes): the ones its
    switch table names (a button it lacks is left out)."""
    from . import coop_play as CP
    from . import handicap as HC
    from . import sound_modes as SMo
    out = {}
    flips = SMo.flipper_buttons(game_elf)
    if len(flips) == 2:
        out["left"], out["right"] = flips
    action = CP.action_button(game_elf)
    if action:
        out["action"] = int(action)
    start = HC.start_button(game_elf)
    if start:
        out["start"] = int(start)
    return out


def cfg_lines(shots, ids):
    """``buttons.cfg``'s ``button`` lines for every button shot in *shots* (``[(name, mask)]``: a profile's) whose
    buttons *ids* (:func:`switch_ids`) has, and the names of those it has not."""
    lines, missing = [], []
    for name, mask in shots:
        if name not in _BY_NAME:
            continue
        kind, btns, ms = _BY_NAME[name]
        if not all(b in ids for b in btns):
            missing.append(name)
            continue
        arg = (" %d" % ids[btns[1]]) if kind == "combo" else (" %d" % ms) if kind == "hold" else ""
        lines.append("button 0x%016x %s %d%s %s" % (int(mask), kind, ids[btns[0]], arg, name))
    return lines, missing


def cfg_text(shots, ids):
    """The whole ``buttons.cfg`` (:func:`cfg_lines`)."""
    lines, _missing = cfg_lines(shots, ids)
    return "# PAD-1403: the cabinet buttons as shots\n" + "".join(line + "\n" for line in lines)


def used_names(text):
    """The button shots named anywhere in *text* (a mode's saved spec, its code), in bit order."""
    return [n for n in NAMES if n in str(text or "")]
