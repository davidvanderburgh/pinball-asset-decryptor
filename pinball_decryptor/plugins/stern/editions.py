"""EDITIONS (PAD-495): one card, several editions of the game; the operator's EDITION picks one.

A tester rebuilding Godzilla keeps a "Standard" and a "70th Anniversary" look of the same card
(other colour profiles, other scenes, other pictures and clips) and asked for "a feature that
allows mass change of color profiles, scene settings and small assets ... selected in the service
menu", then "a separate bank of videos/images/scene assets, and when the setting is selected it
pulls from that bank instead".

The bank is a MULTI-BOOT card. Its images are the editions, each a Write of the same game at the
same version (a whole image or a base card plus an edits folder, where only the files an edition
changes take room), in the order the setting numbers them. Two pieces make the setting pick:

1. every edition's Write puts EDITION in the operator menu (:mod:`.menu_settings`: Adjustments >
   Machine Settings > Attract Mode, values 1..n, the editions' names in its help line; PAD-724: on
   the 21 games whose Adjustments are Standard and Feature Adjustments, the last row of Standard
   Adjustments). The project names the editions (``.staged_changes.json``
   ``editions``: ``{"names": [...]}``); every edition's project names the same ones, so every
   image's menu reads the same and the machine's stored settings never see a different table;
2. the card's boot program (tools/spike2_emu/codeselect, ``edition=`` in images.conf) reads the
   setting off the machine's NVM mirror before the game starts, the way it already reads the
   machine's volume, and boots that image with no menu on the glass.

A change in the menu takes effect at the next power-up: the game has its scenes and shaders up by
the time the operator can open the menu.
"""
from __future__ import annotations

import hashlib

from . import menu_settings as _MS

#: the project sidecar's key: ``{"names": [name, ...]}``
STAGED_KEY = "editions"
#: how many editions a card may have (the setting's values)
MAX_EDITIONS = _MS.MAX_VALUES
#: the machine keys a stored setting by the SHA1 of its descriptor caption (codeselect nvm.h)
CAPTION = _MS.SETTINGS[_MS.EDITION][1]
NVM_KEY = hashlib.sha1(CAPTION.encode("ascii")).hexdigest()
#: ``<game>-<version>`` of the builds whose menu takes the setting. Godzilla Premium/LE 1.16 was seen
#: working end to end in the emulator (EDITION set in the menu, the next power-up booting that
#: edition; the boot program reads the setting the same way whatever the game); PAD-724: the latest
#: build of every Spike 2 game, each seen taking it in its menu and storing it (:data:`.menu_settings.PROVEN`)
PROVEN = _MS.PROVEN

NO_TITLE = "The app cannot tell which game this project is for, so it cannot give it an EDITION."
NOT_PROVEN = ("Editions are not offered on %s. They work on the latest version of each Stern "
              "Spike 2 game: update the machine's code to use them.")
#: PAD-724: the latest builds whose program cannot grow (:data:`.menu_settings.NO_ROOM`)
NO_ROOM = ("Editions are not offered on %s: its game program has no room to grow, so its operator "
           "menu cannot take EDITION.")


def clean(raw):
    """The editions' names from a sidecar's value: at most :data:`MAX_EDITIONS`, blanks named
    by their number, trailing blanks dropped."""
    names = raw.get("names") if isinstance(raw, dict) else None
    if not isinstance(names, (list, tuple)):
        return []
    out = [" ".join(n.split()) if isinstance(n, str) else "" for n in names][:MAX_EDITIONS]
    while out and not out[-1]:
        out.pop()
    return [n or "Edition %d" % (i + 1) for i, n in enumerate(out)]


def count(names):
    """How many editions the menu offers: 2 or more names, else 0 (no setting)."""
    return len(names) if len(names) >= 2 else 0


def to_json(names):
    """The sidecar value for *names* (``None`` when there are no editions)."""
    names = clean({"names": list(names or ())})
    return {"names": names} if names else None


def load(project):
    """The project's edition names (``[]`` when it has none)."""
    if not project:
        return []
    from ...core import staged_changes
    try:
        return clean(staged_changes.load(project).get(STAGED_KEY))
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return []


def title_refusal(prof):
    """Why ``prof``'s title cannot have editions, or ``""``."""
    from .sound_modes import modes_any, title_key
    if prof is None:
        return NO_TITLE
    if title_key(prof) in _MS.NO_ROOM:
        return NO_ROOM % prof.label
    if title_key(prof) not in PROVEN and not modes_any():
        return NOT_PROVEN % prof.label
    return ""


def menu_path(prof):
    """Where the operator sets EDITION on ``prof``'s game (any game's, without a profile)."""
    if prof is None:
        return _MS.ANY_MENU_PATH[_MS.EDITION]
    return _MS.menu_path(prof.game_dir, _MS.EDITION)


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


# ---- reading a built program back (the Multi-boot side) -----------------------------------------
def in_program(elf_bytes):
    """``{"values": n, "help": str, "id": i}`` when the game program carries our EDITION setting
    on a menu page, else ``None``. Never raises. PAD-1325: a 64-bit (Spike 3) program too, its
    page the one :func:`.menu_settings.wide_category` names."""
    from .adjustments import AdjustmentTable, menu_label
    ad, caption, _row, category = _MS.SETTINGS[_MS.EDITION]
    try:
        t = AdjustmentTable(bytes(elf_bytes), wide_ok=True)
        i = t.by_name.get(ad)
        if i is None or menu_label(t, i) != caption:
            return None
        e = t.entry(i)
        help_text = t._cstr(t.word(t.field_off(i, "help")), 200)
        cat = _MS.menu_table(t)
        if cat is None:
            return None
        if t.wide:
            category = _MS.wide_category(t, _MS.EDITION)
        if not cat.has(category, i):
            return None
        if (e["min"], e["step"]) != (1, 1) or not 2 <= e["max"] <= MAX_EDITIONS:
            return None
        return {"values": int(e["max"]), "help": help_text, "id": i}
    except Exception:                                   # noqa: BLE001 - not ours, or not readable
        return None


# ---- Spike 3 (PAD-1325) ---------------------------------------------------------------------------
#: ``<game>-<version>`` of the Spike 3 builds whose game program takes EDITION (a setting the game
#: says it no longer uses, and the menu copy :func:`.menu_settings.grow_wide_program` grows), each
#: seen working in the emulator: the row on Attract Mode, the value stored, and a multi-boot card of
#: two editions booting the one it names. The other Spike 3 builds (Pokemon 0.82, both Star Wars
#: 2025, Walking Dead 0.92) still use all three settings EDITION and its siblings could take.
SPIKE3_PROVEN = frozenset({
    "star_wars_elg-1.10",
    "fallout_le-0.81",
    "fallout_le-0.82",
    "transformers_mtmte_le-0.96",
})
SPIKE3_NO_SPARE = ("Editions are not offered on %s: its game program uses every setting EDITION "
                   "could take, so its operator menu cannot take EDITION.")
SPIKE3_NOT_PROVEN = ("Editions are not offered on %s yet: they work on Star Wars ELG 1.10, Fallout "
                     "0.81 and 0.82 and Transformers 0.96 (Spike 3).")
#: the Spike 3 builds read and found to have no setting to spare
SPIKE3_FULL = frozenset({"pokemon_le-0.82", "star_wars_2025_le-0.96", "star_wars_2025_pro-0.84",
                         "walking_dead_remastered_le-0.92"})


def spike3_key(game_dir, version):
    """``<game>-<major>.<minor>`` of a Spike 3 build (``fallout_le``, ``0.82.0`` -> ``fallout_le-0.82``)."""
    parts = str(version or "").split(".")
    while len(parts) > 2 and parts[-1] in ("0", ""):
        parts.pop()
    return "%s-%s" % ((game_dir or "").lower(), ".".join(parts))


def spike3_label(game_dir, version):
    return "%s %s (Spike 3)" % ((game_dir or "?").replace("_", " ").title(), version or "?")


def spike3_refusal(game_dir, version):
    """Why a Spike 3 build cannot have editions, or ``""``."""
    from .sound_modes import modes_any
    if not game_dir:
        return NO_TITLE
    key = spike3_key(game_dir, version)
    if key in SPIKE3_FULL:
        return SPIKE3_NO_SPARE % spike3_label(game_dir, version)
    if key not in SPIKE3_PROVEN and not modes_any():
        return SPIKE3_NOT_PROVEN % spike3_label(game_dir, version)
    return ""


def _spike3_card(project):
    """The project's card when it is a Spike 3 one (its ``game_dir`` / ``version``), else None."""
    from . import mode_project as MP
    try:
        card = MP.project_card(project)
    except (OSError, ValueError):
        return None
    if card is None or not card.image or MP.card_arch(card.image) != "a64":
        return None
    return card


def project_refusal(project):
    """Why ``project``'s game cannot have editions, or ``""``: a Spike 3 card's by its build
    (:func:`spike3_refusal`), a Spike 2 one's by its profile (:func:`title_refusal`)."""
    card = _spike3_card(project)
    if card is not None:
        return spike3_refusal(card.game_dir, card.version)
    return title_refusal(project_title(project))


def project_menu_path(project):
    """Where the operator sets EDITION on ``project``'s game."""
    if _spike3_card(project) is not None:
        return SPIKE3_MENU_PATH
    return menu_path(project_title(project))


#: where a Spike 3 operator finds EDITION (the page :func:`.menu_settings.wide_category` names)
SPIKE3_MENU_PATH = "Adjustments > Machine Settings > Attract Mode"
