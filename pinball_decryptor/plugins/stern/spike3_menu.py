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
    if not Ed.count(names) or Ed.project_refusal(project):
        return []
    return [(MS.EDITION, len(names), names)]


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


def plan(project, reader, work, log=None):
    """The grown game program for the Spike 3 games volume *reader* (an Ext4Reader over it), or
    None when the project asks for no row this card can take (each reason in the log, as a Spike 2
    Write leaves EDITION out: the rest of the project is still written)."""
    from . import spike3_modes
    log = log or (lambda *a, **k: None)
    names = editions_wanted(project, log)
    if not names:
        return None

    def left(why):
        log("Editions: EDITION could not be added to the operator menu (%s), so a Multi-boot "
            "card cannot pick this card by it." % str(why).rstrip("."), "warning")
        return None
    try:
        state, target = spike3_modes.card_state(reader)
    except Exception as e:                              # noqa: BLE001 - an unreadable link
        return left("the card's /games/game could not be read: %s" % e)
    if state == "multiboot":
        return left("this is a multi-boot card; each edition's own card takes it, and the "
                    "Multi-boot tab puts those cards together")
    if state not in ("stock", "modes") or not target:
        return left("the card's /games/game names no game program")
    node = spike3_modes.game_program(reader, target)
    if node is None:
        return left("the game program %s is not on the card" % target)
    raw = bytes(reader.read_file_bytes(node))
    try:
        out, settings, refused = grow(raw, [(MS.EDITION, len(names), names)])
    except (MS.MenuSettingError, ValueError) as e:
        return left(e)
    if not settings:
        return left(refused.get(MS.EDITION) or "unknown")
    rel = target[len("/games/"):] if target.startswith("/games/") else target.lstrip("/")
    os.makedirs(work, exist_ok=True)
    staged = os.path.join(work, "game_program")
    with open(staged, "wb") as f:
        f.write(out)
    s = settings[0]
    log("Editions: EDITION is in the operator menu (%s), values 1 to %d, its help line \"%s\". "
        "Put this card on a Multi-boot card with the other editions, in that order, and the "
        "setting picks the one that boots." % (s.where, s.values, s.help), "info")
    return MenuPlan(rel, staged, settings)
