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
   Machine Settings > Attract Mode, beside the game's own BOOT SCREEN, values 1..n, the editions'
   names in its help line). The project names the editions (``.staged_changes.json``
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
import struct

from . import menu_settings as _MS

#: the project sidecar's key: ``{"names": [name, ...]}``
STAGED_KEY = "editions"
#: how many editions a card may have (the setting's values)
MAX_EDITIONS = _MS.MAX_VALUES
#: the machine keys a stored setting by the SHA1 of its descriptor caption (codeselect nvm.h)
CAPTION = _MS.SETTINGS[_MS.EDITION][1]
NVM_KEY = hashlib.sha1(CAPTION.encode("ascii")).hexdigest()
#: ``<game>-<version>`` of the builds whose menu takes the setting. Premium/LE 1.16 was seen
#: working end to end in the emulator (EDITION set in the menu, the next power-up booting that
#: edition); Pro 1.16 reads the same way, and PAD-494 saw its menu take MUSIC MODE beside it.
PROVEN = frozenset({"godzilla_le-1.16", "godzilla_pro-1.16"})

NO_TITLE = "The app cannot tell which game this project is for, so it cannot give it an EDITION."
NOT_PROVEN = ("Editions have not been tried on %s yet, so they are not offered there. "
              "Godzilla Pro and Premium/LE 1.16 have them.")


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
    from .sound_modes import title_key
    if prof is None:
        return NO_TITLE
    if title_key(prof) not in PROVEN:
        return NOT_PROVEN % prof.label
    return ""


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


# ---- reading a built program back (the Multi-boot side) -----------------------------------------
def in_program(elf_bytes):
    """``{"values": n, "help": str, "id": i}`` when the game program carries our EDITION setting
    on a menu page, else ``None``. Never raises."""
    from .adjustments import AdjustmentTable, OFF_MENU_HELP, menu_label
    ad, caption, _row, category = _MS.SETTINGS[_MS.EDITION]
    try:
        t = AdjustmentTable(bytes(elf_bytes))
        i = t.by_name.get(ad)
        if i is None or menu_label(t, i) != caption:
            return None
        e = t.entry(i)
        desc = t._off(t.table_va + i * t.elem)
        help_text = t._cstr(struct.unpack_from("<I", t.data, desc + OFF_MENU_HELP)[0], 200)
        cat = _MS.category_table(t)
        if cat is None or not cat.has(category, i):
            return None
        if (e["min"], e["step"]) != (1, 1) or not 2 <= e["max"] <= MAX_EDITIONS:
            return None
        return {"values": int(e["max"]), "help": help_text, "id": i}
    except Exception:                                   # noqa: BLE001 - not ours, or not readable
        return None
