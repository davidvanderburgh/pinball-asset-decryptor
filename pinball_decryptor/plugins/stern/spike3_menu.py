"""Our operator-menu rows on a Spike 3 card (PAD-1325): the game program grown so its menu lists them.

A Spike 2 Write puts EDITION (and MUSIC MODE, the picture rows, CO-OP PLAY, HANDICAP) in the game's
operator menu with same-size writes and an appended category table in the program it rewrites
(engine's text step). A Spike 3 game program is a 64-bit PIE on the encrypted games partition: the
Spike 3 Write reads it off the card's games volume, takes over the setting the game no longer uses
(:func:`.menu_settings.plan_many`), grows the menu's category table so a page lists the row
(:func:`.menu_settings.grow_wide_program`, PAD-1321), reads the result back
(:func:`.menu_settings.check`) and puts the program on the card whole, as it does the scenes it
rewrites (``ext4_grow`` through the volume's encryption; its SD-validation record refreshed with the
rest).

Today the rows are EDITION (:mod:`.editions`): the number a Spike 3 multi-boot card of the game's
editions (tools/spike3_emu/mks3multi.py ``--editions``) boots by at the next power-up. The plan
takes a list, so the other menu rows join it as their 64-bit runtimes land.
"""
from __future__ import annotations

import os

from . import menu_settings as MS


class MenuPlan:
    """The grown game program for a Spike 3 card: ``rel`` (its path on the games volume),
    ``staged`` (the file to put there whole), ``settings`` (the :class:`.menu_settings.MenuSetting`
    of each row it lists)."""

    def __init__(self, rel, staged, settings):
        self.rel, self.staged, self.settings = rel, staged, list(settings)

    @property
    def job(self):
        return (self.rel, self.staged)

    def live(self, key):
        """PAD-1326: the live value's address (the program's own) of row *key*, or 0 when it is not on."""
        return next((s.live for s in self.settings if s.key == key), 0)


def coop_row_asked(project):
    """PAD-1326: whether this Spike 3 build's co-op play asks for CO-OP PLAY in the operator menu (co-op goes on
    and the project switches it there: coop_play.menu_asked)."""
    from . import coop_play as CP
    from . import spike3_modes
    return CP.menu_asked(project) and spike3_modes.coop_wanted(project) is not None


def hand_row_asked(project):
    """PAD-1326: whether this Spike 3 build's handicaps ask for HANDICAP in the operator menu (always, as on Spike 2:
    with no setting left for it the handicaps are always on)."""
    from . import spike3_modes
    return spike3_modes.hand_wanted(project) is not None


def _hand_row():
    from . import handicap as HC
    return (MS.HANDICAP, HC.MENU_VALUES, (), {"default": 1, "help_text": HC.MENU_HELP, "onoff": True})


def _coop_row():
    from . import coop_play as CP
    return (MS.COOP_PLAY, CP.MENU_VALUES_A64, (), {"default": 1, "help_text": CP.MENU_HELP_A64, "from_zero": True})


def editions_wanted(project, log):
    """The project's edition names when they go on a Spike 3 card, else ``[]`` (said why)."""
    from . import editions as Ed
    names = Ed.load(project)
    if not Ed.count(names):
        return []
    why = Ed.project_refusal(project)
    if why:
        log("Editions: EDITION is not added to this card: %s" % why, "warning")
        return []
    log("Editions: this card is one of %d editions (%s)." % (
        len(names), ", ".join("%d %s" % (i + 1, n) for i, n in enumerate(names))), "info")
    return names


def rows_wanted(project):
    """The project's rows this module puts on a Spike 3 card (``[(key, values, names)]``, for
    :func:`grow`), quietly: :func:`plan` says why one is left out. PAD-1324's music modes grow their
    own copy of the program (``game.pad``, which the modes' hook runs in the card's program's place)
    with these beside MUSIC MODE, so the program the machine runs carries EDITION either way."""
    from . import editions as Ed
    names = Ed.load(project)
    rows = [] if not Ed.count(names) or Ed.project_refusal(project) else [(MS.EDITION, len(names), names)]
    if coop_row_asked(project):                         # PAD-1326: the CO-OP PLAY and HANDICAP rows too
        rows.append(_coop_row())
    if hand_row_asked(project):
        rows.append(_hand_row())
    return rows


def grow(raw, wanted):
    """``(grown program bytes, [MenuSetting], {key: reason})`` for the 64-bit program *raw* with
    *wanted* (``[(key, values, names), ...]``, :func:`.menu_settings.plan_many`'s) in its menu.
    The settings it cannot take are in the reasons; the bytes are *raw* unchanged when none go.
    Every setting placed is read back from the grown bytes (:func:`.menu_settings.check`)."""
    from .adjustments import AdjustmentTable
    t = AdjustmentTable(bytes(raw), wide_ok=True)
    if not t.wide:
        raise MS.MenuSettingError("this is not a Spike 3 (64-bit) game program")
    settings, writes, cat, refused = MS.plan_many(t, wanted)
    if not settings:
        return bytes(raw), [], refused
    buf = bytearray(raw)
    for off, b in writes.items():
        buf[off:off + len(b)] = b
    out = bytes(buf)
    if cat is not None:
        out = MS.grow_wide_program(AdjustmentTable(out, wide_ok=True), cat, *settings)
    for s in settings:
        bad = MS.check(out, s)
        if bad:
            raise MS.MenuSettingError("%s did not read back from the grown program (%s)"
                                      % (MS.SETTINGS[s.key][1], "; ".join(bad)))
    return out, settings, refused


#: PAD-1326: each row's own words when it cannot go on, and once it is on
_LEFT = {
    MS.EDITION: ("Editions: EDITION could not be added to the operator menu (%s), so a Multi-boot "
                 "card cannot pick this card by it."),
    MS.COOP_PLAY: ("Co-op play: CO-OP PLAY could not be added to the operator menu (%s), so co-op play "
                   "is left out of this card."),
    MS.HANDICAP: ("Handicaps: HANDICAP could not be added to the operator menu (%s), so the handicaps are "
                  "always on on this card."),
}
#: PAD-1326: a row whose absence is no warning (the part goes on without it)
_QUIET = (MS.HANDICAP,)


def _placed(s, names, log):
    if s.key == MS.EDITION:
        log("Editions: EDITION is in the operator menu (%s), values 1 to %d, its help line \"%s\". "
            "Put this card on a Multi-boot card with the other editions, in that order, and the "
            "setting picks the one that boots." % (s.where, s.values, s.help), "info")
    elif s.key == MS.COOP_PLAY:
        log("Co-op play: CO-OP PLAY is in the operator menu (%s), 0 (Off) to start with: set it to 1 "
            "(On) and holding the right flipper button while pressing Start adds a teammate. While it "
            "is 1 most Insider Connected features are off; at 0 the card reports as it always has "
            "(with no modes on it)." % s.where, "info")
    elif s.key == MS.HANDICAP:
        log("Handicaps: HANDICAP is in the operator menu (%s), Off to start with: set it to On and each "
            "player picks a handicap at their first ball." % s.where, "info")


def plan(project, reader, work, log=None):
    """The grown game program for the Spike 3 games volume *reader* (an Ext4Reader over it), or
    None when the project asks for no row this card can take (each reason in the log, as a Spike 2
    Write leaves EDITION out: the rest of the project is still written). PAD-1326: CO-OP PLAY too,
    when co-op goes on and the project switches it in the menu (its live value goes in coop.cfg:
    :meth:`MenuPlan.live`)."""
    from . import spike3_modes
    log = log or (lambda *a, **k: None)
    names = editions_wanted(project, log)
    coop = coop_row_asked(project)
    hand = hand_row_asked(project)
    wanted = (([(MS.EDITION, len(names), names)] if names else [])
              + ([_coop_row()] if coop else []) + ([_hand_row()] if hand else []))
    if not wanted:
        return None

    def left(why, keys=None):
        for key in keys or [w[0] for w in wanted]:
            log(_LEFT[key] % str(why).rstrip("."), "info" if key in _QUIET else "warning")
        return None
    try:
        state, target = spike3_modes.card_state(reader)
    except Exception as e:                              # noqa: BLE001 - an unreadable link
        return left("the card's /games/game could not be read: %s" % e)
    if state == "multiboot":
        return left("this is a multi-boot card; each game's own card takes it, and the "
                    "Multi-boot tab puts those cards together")
    if state not in ("stock", "modes") or not target:
        return left("the card's /games/game names no game program")
    node = spike3_modes.game_program(reader, target)
    if node is None:
        return left("the game program %s is not on the card" % target)
    raw = bytes(reader.read_file_bytes(node))
    try:
        out, settings, refused = grow(raw, wanted)
    except (MS.MenuSettingError, ValueError) as e:
        return left(e)
    for key, why in refused.items():
        left(why or "unknown", [key])
    if not settings:
        return None
    rel = target[len("/games/"):] if target.startswith("/games/") else target.lstrip("/")
    os.makedirs(work, exist_ok=True)
    staged = os.path.join(work, "game_program")
    with open(staged, "wb") as f:
        f.write(out)
    for s in settings:
        _placed(s, names, log)
    return MenuPlan(rel, staged, settings)
