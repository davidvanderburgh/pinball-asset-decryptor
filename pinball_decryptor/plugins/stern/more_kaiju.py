"""PAD-707: MORE KAIJU - new monsters on Godzilla's own BATTLE SELECTION screen.

The game's screen has seven places compiled into its program (MODE_SDK.md, "A monster in the roster"), so a place
can be taken but not added to the GAME. A new monster is added to the SCREEN instead: every mode whose When is "the
player picks it on the battle selection screen, in X's place" gets a tile of its own there, beside the game's seven
(:mod:`.battle_select` lays the card's own screen out again for them), and the runtime's ``pm_roster_more`` walks
the cursor over it; picked, it plays as place X's battle.

This module says which modes are on the screen, in its order, and builds the card's selection scene with them.

A monster's picture is ``monster.png`` in its mode's folder (the blocks editor's Picture… on the battle hat puts it
there), else its own screen's picture, else its HUD badge's ``badge.png``, else a tile lettered with its name.
Pictures the person gives are theirs; nothing of a manufacturer's is drawn here."""
import os

from . import battle_select as BS
from . import mode_project as MP

#: the picture a monster's mode folder holds for its tile and portrait
PICTURE_FILE = "monster.png"
BADGE_FILE = "badge.png"
#: the most new monsters on the screen (two columns of six)
MAX_MONSTERS = BS.MAX_NEW
#: what the choice is called (the hat, the form, the runtime's log)
TITLE = "MORE KAIJU"


class MoreKaijuError(ValueError):
    """New monsters that cannot go on the screen as asked."""


def page_names(slug):
    """The stem of a monster's nodes on the selection screen (``PadSel_<slug>``; the runtime adds each part's
    suffix), and "" (its words: none - the game letters the screen)."""
    return BS.page_of(slug), ""


def picture_of(folder, picture="", screen_art=""):
    """The picture file a monster is drawn with: the one named (in its folder), else ``monster.png``, else its own
    screen's picture, else its badge's ``badge.png``; "" when it has none (it is lettered)."""
    for name in (picture, PICTURE_FILE, screen_art, BADGE_FILE):
        if name and os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return ""


def monsters(project, code, forms=()):
    """The new monsters (form modes, then code modes): ``[{"slug", "name", "slot", "picture"}]`` from its form modes
    that start on a battle with ``roster_more``, and its code modes (blocks modes are code modes) whose assets say
    ``more`` (``{"slot": n, "picture": file}``). ``slot`` is the place each stands in."""
    out = []
    for slug, spec in forms or ():
        if not (MP.starts_on_battle(spec) and getattr(spec, "roster_more", False)):
            continue
        slot = MP._int_or_none(spec.roster_slot)
        if slot is None or slot < 0:
            continue
        folder = MP.mode_folder(project, slug) if project else ""
        out.append({"slug": slug, "name": (spec.name or slug).upper()[:40], "slot": slot,
                    "picture": picture_of(folder, "", getattr(spec, "screen_art", "") or "") if folder else ""})
    for slug, spec in code or ():
        more = getattr(spec, "more", None) or {}
        if not isinstance(more, dict) or more.get("slot") is None:
            continue
        folder = MP.mode_folder(project, slug) if project else ""
        out.append({"slug": slug, "name": (spec.name or slug).upper()[:40], "slot": int(more["slot"]),
                    "picture": picture_of(folder, str(more.get("picture") or ""),
                                          getattr(spec, "screen_art", "") or "") if folder else ""})
    return out


def list_order(found):
    """``found`` in the screen's order: the monsters' names, then their node stems - the runtime's (pm_roster_more
    keeps its list so, whatever order the modes join in), so the tiles the build lays out are the cursor's."""
    return BS.order(found)


def problems(found):
    """Why the monsters cannot go on the screen (sentences; empty = fine)."""
    return BS.check(found)


def wanted(project, code=None):
    """1 when the project has a new monster for the selection screen (the Write then reads the card's screen)."""
    if not project:
        return False
    try:
        forms, _broken = MP.list_modes(project)
    except Exception:
        forms = []
    if code is None:
        from . import code_modes as CM
        try:
            code = CM.list_code(project)
        except Exception:
            code = []
    return bool(monsters(project, code, forms))


def scene(project, code, prof, forms=(), stock=b""):
    """The card's selection scene with the project's new monsters on it (bytes), or None when there are none or the
    title has no such screen. ``stock``: the scene as the card holds it (a Heisei card's is Heisei's)."""
    found = list_order(monsters(project, code, forms))
    if not found or not prof.can("roster"):
        return None
    why = problems(found)
    if why:
        raise MoreKaijuError(" ".join(why))
    if not stock:
        raise MoreKaijuError("The card's battle selection screen was not read, so its new monsters cannot be put on it.")
    try:
        return BS.build(stock, found)
    except BS.BattleSelectError as e:
        raise MoreKaijuError("The battle selection screen: %s" % e) from None
