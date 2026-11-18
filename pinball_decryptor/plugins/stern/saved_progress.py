"""Saved progress: numbers a mode keeps between games (PAD-1402).

A mode's variables last a ball, a mode or a game; a Story mode, New Game Plus or a character unlocked for good needs
what the player did to outlive the game and the power-off. The mode runtime keeps a small store for that
(``pad_mode_runtime.c`` "SAVED PROGRESS": ``/dump/pad_saved_progress`` on the card's data partition, beside the
challenge scores), which a mode reads and writes with ``pm_saved_get`` / ``pm_saved_put`` (``pad_mode.h``). The
blocks' variables reach it through a "saved" reset (:mod:`.block_modes`).

A card carries it only when one of its modes uses it: the Write looks for ``pm_saved_`` in each mode's C (a blocks
mode's is written from its blocks, so the same test covers both kinds) and then puts ``saved.cfg`` beside the runtime
and the service menu's SAVED PROGRESS row on the card: 1 = Keep, 2 = Clear. The row's default is Clear, so a factory
reset (every row back to its default) clears the progress too; the runtime puts the row back to Keep each time it
clears."""
from __future__ import annotations

import glob
import os

#: beside the runtime on the card
CFG_NAME = "saved.cfg"
#: the service menu row's values (menu_settings.SAVED_PROGRESS): 1 Keep, 2 Clear - and Clear is its default
MENU_NAMES = ("Keep", "Clear")
MENU_DEFAULT = 2
#: what a mode's C calls when it keeps progress
USES = "pm_saved_"
#: the build log's line
HOW = ("the modes keep progress between games on the card (/dump/pad_saved_progress): each player's by their Insider "
       "login while they are logged in, else by their player number")


def _sources(project, slug):
    from . import mode_project as MP
    folder = os.path.join(MP.modes_dir(project), slug)
    return sorted(glob.glob(os.path.join(folder, "*.c")) + glob.glob(os.path.join(folder, "*.h")))


def mode_uses(project, slug):
    """Whether mode *slug* of *project* keeps saved progress: its C names ``pm_saved_``. A blocks mode is read from
    its blocks (its C may not be written yet)."""
    from . import block_modes as BM
    try:
        if BM.is_blocks(project, slug):
            return BM.uses_saved(BM.load(project, slug))
    except Exception:                                   # noqa: BLE001 - a broken program is the build's to say
        pass
    for path in _sources(project, slug):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                if USES in f.read():
                    return True
        except OSError:
            continue
    return False


def wanted(project, modes):
    """The names of *modes* (``[(slug, spec)]``: the build's mode list and code mode list, a blocks mode being a code
    mode) that keep saved progress, in order."""
    return [getattr(spec, "name", slug) for slug, spec in modes or () if mode_uses(project, slug)]


def project_wants(project):
    """Whether any of *project*'s modes keeps saved progress (the Service menu tab's SAVED PROGRESS row)."""
    from . import code_modes as CM
    from . import mode_project as MP
    found = []
    try:
        found += MP.list_modes(project)[0]
    except Exception:                                   # noqa: BLE001
        pass
    try:
        found += CM.list_code(project)
    except Exception:                                   # noqa: BLE001 - a broken one is the build's to say
        pass
    return bool(wanted(project, found))


def cfg_text(setting=0, users=None):
    """``saved.cfg``: on; the SAVED PROGRESS row's value *setting* (0: no row - nothing clears it); *users*
    ``(manager, A, B)`` where the game keeps its players' Insider logins (coop_play.insider_users), or None."""
    lines = ["# PAD-1402: saved progress (pad_mode_runtime.c \"SAVED PROGRESS\")", "on"]
    if setting:
        lines.append("clear 0x%x" % int(setting))
    if users:
        mgr, a, _b = users
        lines.append("users 0x%x 0x%x 0x%x" % (int(mgr), int(a), int(_b)))
    return "\n".join(lines) + "\n"
