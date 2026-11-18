"""A setting of the app's own in a Spike 2 game's operator menu (PAD-494: MUSIC MODE).

A tester building two editions of one retheme (an orchestral score and a standard one) asked for
one card and "a service menu setting [that] allows the user to select a MUSIC MODE". A game's
adjustments cannot be added to: each one's value lives in the board's NVRAM mirror (``.nonvol``,
eight bytes an id), and a new id would move that layout. So the setting TAKES OVER one the game
carries and never reads - a DEPRECATED adjustment, the firmware's own word for it:

  * Godzilla Premium/LE and Pro 1.16 carry ``AD_GI_MAX_BRIGHTNESS`` ("DEPRECATED GI LED MAX
    BRIGHTNESS", id 31) and two siblings (33, 35). Measured at the desk on both programs: no call to
    the adjustment getter names id 31 (LE 0x2b3614, Pro 0x286e00; every other id 30-36 has one or
    two), its value's address is in the program once - in its own descriptor - and no menu lists it.

WHAT THE MENU SHOWS, read in the emulator on Godzilla Premium/LE 1.16 (System 4.35, 2026-10-09).
The operator's Adjustments are pages of a category each (Machine Settings > LCD/Lamp, Audio
Content, ...; the category names are a 37-line text table, "Audio Content" is category 13). A
page lists:

  * the game's own (feature) adjustments, ids 160-384, whose descriptor names that category
    (``u16 @ +0x26``) - Audio Content is Theme Music (160), 163, 201, 202 and 245;
  * and the SYSTEM ones a table says: 107 records ``{u32 category, u32 kind, u32 id}`` (kind 3 =
    an adjustment row) in ``.rodata`` that the menu manager copies into a vector of its own at
    start - ``operator new(1284)`` and ``memcpy`` from a literal, the size loaded twice by
    ``movw`` and the vector's end made as ``add r5, r0, #0x500; add r5, r5, #4`` (LE 0x1fb02c,
    Pro 0x260680). An id in neither is on no page: giving id 31 category 13 alone did not show it.

So the setting goes on a page by a 108th record ``{13, 3, 31}``: the table, one record longer, in
the game program's extension segment, the literal pointed at it and the three constants made
1296. Each row's caption is NOT the descriptor's: it is line ``count - 1 - id`` of a text table of
its own (five language pointers and a zero a line, "GI LED Max Brightness" for id 31). Its help -
the right-hand panel - IS the descriptor's ``+0x20`` string ("Sets the overall brightness of
..."). So the row's caption ("Music Mode"), the descriptor's caption ("MUSIC MODE", which the
machine keys a stored setting by: the SHA1 of the caption, tools/spike2_emu/codeselect/nvm.h) and
the help (the modes' names: "1 = Standard, 2 = Orchestral") are each rewritten IN PLACE, every
string being its own; the descriptor's default/min/max/step become 1, 1, n, 1. The modes' names
live in the help only, so renaming a mode never loses the operator's pick.

Everything but the table is the same size as what it replaces; :func:`plan` returns those writes
and the table to place, :func:`table_writes` the code writes once its address is known. Anything
that does not read the way it was measured is refused with the reason, rather than guessed at:
this edits the game program, and a menu that lists a wrong id is not something an operator would
notice until the machine was in front of them.

The value is read on the machine by the mode runtime (pad_mode_runtime.c "music modes"), from the
setting's own eight bytes, whose address :func:`plan` returns.

PAD-537: BRIGHTNESS, CONTRAST and SATURATION (:mod:`.picture_settings`) take no adjustment of their
own: each takes whichever DEPRECATED one the card's other settings of ours leave (``SETTINGS``
names None for them), so a card with neither MUSIC MODE nor EDITION has all three, one with both
has BRIGHTNESS only. Their range is 1..9 with 5 (normal) the default, and their help is a line of
their own rather than a list of names.

PAD-1321: a Spike 3 game program (64-bit ARM, ``AdjustmentTable(raw, wide_ok=True)``) is read the
same way: the same DEPRECATED settings (ids 31/33/35 on Star Wars ELG 1.10), a 64-byte descriptor
whose fields the table names (``table.fields``), its row caption a five-pointer line the descriptor
points at (``+0x28``), and the menu's category records (111 on ELG, the same ``{category, kind, id}``)
found through the ``adrp``/``add`` that address them. :func:`plan` gives the same-size writes; the
category table cannot be grown on a 64-bit program yet (:class:`WideCategoryTable` refuses, with the
reason), so :func:`offered` says no for one whose menu does not already list the setting.
"""
from __future__ import annotations

import dataclasses
import struct
from dataclasses import dataclass

from .adjustments import (OFF_DEFAULT, OFF_MAX, OFF_MENU_HELP, OFF_MENU_LABEL, OFF_MIN, OFF_STEP,
                          menu_label)

MUSIC_MODE = "music_mode"
#: PAD-495: which of a multi-boot card's editions of the game boots at the next power-up
#: (tools/spike2_emu/codeselect reads it off the NVM mirror before the game starts)
EDITION = "edition"
#: PAD-537: the picture settings (:mod:`.picture_settings`)
BRIGHTNESS = "brightness"
CONTRAST = "contrast"
SATURATION = "saturation"
#: PAD-1017 round 2: co-op play switched in the service menu (:mod:`.coop_play`): Off/On (stored 0, 1)
COOP_PLAY = "coop_play"
#: PAD-1033: a handicap for each player (:mod:`.handicap`), switched in the service menu: Off/On (stored 0, 1)
HANDICAP = "handicap"
#: PAD-1390: which of the project's image sets (:mod:`.scene_variants`, scene variants) the screens show: 1..n by name
IMAGE_SET = "image_set"
#: PAD-1402: SAVED PROGRESS (:mod:`.saved_progress`): 1 Keep, 2 Clear - Clear the default, so a factory reset clears the
#: modes' saved progress with the game's settings; the mode runtime clears it and puts the row back to Keep
SAVED_PROGRESS = "saved_progress"
#: each setting of ours: the adjustment it takes over, its descriptor caption, its row caption and
#: the menu category whose page lists it. EDITION sits on Attract Mode (16), beside the game's own
#: BOOT SCREEN and 70TH BOOT SCREEN, which is where an operator already picks how the game looks.
#: The picture settings take no adjustment of their own (None: a spare one, :func:`plan_many`) and
#: sit on LCD/Lamp (11), beside the game's own LCD BRIGHTNESS.
SETTINGS = {
    MUSIC_MODE: ("AD_GI_MAX_BRIGHTNESS", "MUSIC MODE", "Music Mode", 13),
    EDITION: ("AD_LED_MAX_BRIGHTNESS", "EDITION", "Edition", 16),
    BRIGHTNESS: (None, "BRIGHTNESS", "Brightness", 11),
    CONTRAST: (None, "CONTRAST", "Contrast", 11),
    SATURATION: (None, "SATURATION", "Saturation", 11),
    COOP_PLAY: (None, "CO-OP PLAY", "Co-op Play", 16),
    HANDICAP: (None, "HANDICAP", "Handicap", 16),
    IMAGE_SET: (None, "IMAGE SET", "Image Set", 16),
    SAVED_PROGRESS: (None, "SAVED PROGRESS", "Saved Progress", 16),
}
#: PAD-1382: when a card wants more settings of ours than the game has spare rows, they all SHARE two: MORE SETTINGS
#: picks one (its help names them) and the row under it is that one's value. The mode runtime keeps every value in a
#: file on the card (pad_mode_runtime.c "more settings": /dump/pad_settings.state; it writes the picked setting's
#: caption, help, range and value over the second row, and an accepted change there is that setting's), and each
#: setting's reader is handed the runtime's word for it (SHARED_BASE + 4 x its number, in the setting's cfg line) in
#: place of a row's address. On Attract Mode, beside where CO-OP PLAY and HANDICAP sit with rows of their own.
MORE_SELECT = "more_select"
MORE_VALUE = "more_value"
SETTINGS[MORE_SELECT] = (None, "MORE SETTINGS", "More Settings", 16)
SETTINGS[MORE_VALUE] = (None, "SETTING VALUE", "Setting Value", 16)
#: never shared: EDITION is read off the board's store before the game (and the runtime) starts (codeselect)
NOT_SHARED = frozenset({EDITION, MORE_SELECT, MORE_VALUE})
#: a shared setting's address in its cfg line: SHARED_BASE + 4 x its number on MORE SETTINGS (above the user space of
#: a 32-bit process, so never a .nonvol address)
SHARED_BASE = 0xFADE0000
#: the runtime's table of the shared rows, beside the mode runtime
SHARED_CFG = "settings.cfg"
#: the start of the reason a setting gets when every spare row is taken
NO_SPARE = "the game has no spare setting left for"
#: PAD-1382 round 5 (David: "it's really weird to shove in these settings into the 'attract mode' tab. can't we add our
#: own 'custom code' tab with our own settings there?"): every row of ours goes on a Machine Settings page of its own. The
#: menu lists the categories 8-17 that have rows, and on every one of the 38 newest builds with category pages, category
#: 15 (Wireless Audio Devices) has none - so the page is never shown. Our rows take it, and its name is rewritten in place.
OWN_CATEGORY = 15
OWN_PAGE = "Custom Code"
#: and the Machine Settings list's help line for it
OWN_HELP = "Settings added by this card's custom code."
#: Simon and David (2026-11-18): "When we know an item will require a reboot we should put an asterisk on it" - the
#: settings a change of shows only from the next power-up: IMAGE SET (the auto_loaded scenes are read at boot, before
#: the game reads its settings) and EDITION (read off the board's store before the game starts, NOT_SHARED). Their
#: row caption gets " *" where it has room, and the page's help line says what the asterisk means (Simon's words)
POWER_UP = frozenset({IMAGE_SET, EDITION})
POWER_UP_MARK = " *"
OWN_HELP_POWER_UP = ("Settings added by custom code. Items with * take effect on next power up.",
                     "Items with * take effect on next power up.")


def shown_caption(key, room=None):
    """Setting *key*'s row caption as the menu shows it: a :data:`POWER_UP` one marked "Image Set *" when *room*
    (characters, None: any) holds the mark, else its plain caption."""
    plain = SETTINGS[key][2]
    if key in POWER_UP and (room is None or len(plain) + len(POWER_UP_MARK) <= room):
        return plain + POWER_UP_MARK
    return plain if room is None else plain[:room]
#: the firmware's own word for an adjustment nothing reads any more
DEPRECATED = "DEPRECATED"
#: how many values a setting of ours may offer (the picture settings' 9 are their own)
MAX_VALUES = 8
#: the most any setting of ours offers
VALUES_CEILING = 9
#: a category table record: {category, kind, id}; kind 3 is an adjustment row
REC = 12
KIND_ADJUSTMENT = 3
_MOVW = 0x03000000
_ADD_IMM = 0x02800000


def _new_rows(table, settings):
    """``[(category, id)]`` of *settings* the menu *table* does not list yet, each once, in order (PAD-1382: the
    settings sharing MORE SETTINGS all name the row under it, which the menu must list once - a Standard Adjustments
    list listed it once per shared setting, five times on Aerosmith LE 1.16 in the emulator)."""
    out = []
    for st in settings:
        row = (st.category, st.id)
        if row not in out and not table.has(st.category, st.id):
            out.append(row)
    return out


def _records_without(records, rows):
    """PAD-1394: *records* (``(category, kind, id)``) less the adjustment ones *rows* (``{(category, id)}``) names."""
    rows = set(rows)
    return tuple(r for r in records if not (r[1] == KIND_ADJUSTMENT and (r[0], r[2]) in rows))


def _shrunk_in_place(table, va, records, keep):
    """PAD-1394: ``{file offset: bytes}`` writing the records *keep* over *records* at *va*, the rest zeroed."""
    new = b"".join(struct.pack("<3I", *r) for r in keep)
    return {table._off(va): new + b"\x00" * (len(records) * REC - len(new))}


def listed_rows(cat):
    """PAD-1394: the ``(category, id)`` of each adjustment row the menu *cat* lists (a Standard Adjustments list's
    category is None: it has no pages)."""
    if isinstance(cat, StandardList):
        return [(None, i) for i in cat.ids]
    return [(c, i) for c, k, i in cat.records if k == KIND_ADJUSTMENT]


def stale_rows(table, cat, settings=()):
    """PAD-1394: the rows of ours the menu *cat* lists that *settings* (this Write's :class:`MenuSetting` s) no longer
    want: each row whose adjustment an earlier Write captioned for a setting of ours (no game's own menu row carries one
    of those captions: the 60 Spike 2 cards of the library, read), unless one of *settings* is on that row - on that
    page, where the menu has pages (a setting moved to another page leaves its old record behind too).
    ``[(category, id)]``."""
    ours = {v[1] for v in SETTINGS.values()}
    keep_ids = {s.id for s in settings}
    keep = {(s.category, s.id) for s in settings}
    out = []
    for c, i in listed_rows(cat):
        if (c, i) in out or not (i in keep_ids or menu_label(table, i) in ours):
            continue
        if (i not in keep_ids) if c is None else ((c, i) not in keep):
            out.append((c, i))
    return out


def retire(table, settings=()):
    """PAD-1394: ``({file offset: bytes}, [caption])``: the same-size writes that take the rows of ours *settings* no
    longer want off the program's menu (:func:`stale_rows`), and those rows' captions; ``({}, [])`` when there are
    none. A Write that wants no setting of ours at all calls it with none."""
    cat = menu_table(table)
    if cat is None:
        return {}, []
    rows = stale_rows(table, cat, settings)
    if not rows:
        return {}, []
    return cat.shrink_writes(table, rows), [menu_label(table, i) for _c, i in rows]


class MenuSettingError(ValueError):
    """The program cannot take the setting; the message says why, in the user's words."""


@dataclass(frozen=True)
class MenuSetting:
    key: str
    id: int                 # the adjustment id taken over
    caption: str            # the row's caption
    help: str               # its help line, as written
    values: int             # 1..values
    live: int               # the address of its value in the running game (.nonvol)
    category: int           # the page that lists it
    default: int = 1        # the value a fresh store starts at
    where: str = ""         # PAD-724: where the operator finds it ("Adjustments > ...")
    low: int = 1            # PAD-1017: the lowest value stored (0 for an Off/On one: 0 Off, 1 On)
    kind: int = 0           # PAD-1017: the display kind written (an Off/On one's), 0 when left as it was
    #: PAD-1382: a setting on the shared rows: (its number on MORE SETTINGS,). MORE_VALUE's own: where the runtime
    #: rewrites it - (descriptor, help string, help room, row caption string, caption room, default/min/max/kind
    #: offsets in the descriptor, kind's -1 when it has none)
    shared: tuple = ()


@dataclass(frozen=True)
class CategoryTable:
    """The menu manager's category records and the code that copies them (one build's)."""
    va: int                 # where the records are
    records: tuple          # ((category, kind, id), ...)
    literal_off: int        # file offset of the word holding ``va``
    size_offs: tuple        # file offsets of the two ``movw rd, #size``
    end_off: int            # file offset of ``add rd, rd, #lo`` (the vector's end: hi + lo = size)
    end_hi: int             # the ``add rd, r0, #hi`` before it

    def has(self, category, ident):
        return any(c == category and k == KIND_ADJUSTMENT and i == ident for c, k, i in self.records)

    def lists(self, ident):
        return any(k == KIND_ADJUSTMENT and i == ident for c, k, i in self.records)

    def where(self, category):
        return "Adjustments > Machine Settings > %s" % CATEGORY_NAMES.get(category, "?")

    def blob(self, *settings):
        recs = list(self.records) + [(c, KIND_ADJUSTMENT, i) for c, i in _new_rows(self, settings)]
        return b"".join(struct.pack("<3I", *r) for r in recs)

    def records_with(self, *settings):
        return len(self.records) + len(_new_rows(self, settings))

    def without(self, rows):
        """PAD-1394: this table less the adjustment records *rows* (``{(category, id)}``)."""
        return dataclasses.replace(self, records=_records_without(self.records, rows))

    def shrink_writes(self, table, rows):
        """PAD-1394: ``{file offset: bytes}`` that take *rows* off the menu in place: the shorter table over the old one
        (its tail zeroed) and the copy's sizes made the shorter one's."""
        keep = _records_without(self.records, rows)
        out = _shrunk_in_place(table, self.va, self.records, keep)
        out.update(self.writes_for(table, self.va, len(keep)))
        return out

    def writes(self, table, new_va, *settings):
        return self.writes_for(table, new_va, self.records_with(*settings))

    def writes_for(self, table, new_va, n_records):
        size = n_records * REC
        lo = size - self.end_hi
        if not 0 <= lo <= 0xFF or size > 0xFFFF:
            raise MenuSettingError("the menu's category table cannot grow to %d records" % n_records)
        data = table.data
        out = {self.literal_off: struct.pack("<I", new_va)}
        for o in self.size_offs:
            w = struct.unpack_from("<I", data, o)[0]
            out[o] = struct.pack("<I", (w & ~0x000F0FFF) | ((size & 0xF000) << 4) | (size & 0xFFF))
        w = struct.unpack_from("<I", data, self.end_off)[0]
        out[self.end_off] = struct.pack("<I", (w & ~0xFFF) | lo)
        return out


@dataclass(frozen=True)
class StandardList:
    """PAD-724: the menu of the games without a category table (Aerosmith, Elvira 3, Foo
    Fighters, Guardians, Led Zeppelin, Mandalorian, Munsters, Rush, Sword of Rage, TMNT, Venom:
    22 of the 53 newest builds). Their Adjustments are two pages, Standard Adjustments and
    Feature Adjustments (:mod:`.menu_visibility`); Standard Adjustments is a NUL-ended ``u16`` id
    list in ``.rodata`` its page reaches through a getter of its own (``movw r0 / movt r0 /
    bx lr``). A setting goes on that page by a list one id longer, in the extension segment, the
    getter's two immediates pointed at it. The page lists its ids in order, so ours come last,
    after the game's SERVICE MENU B.BOX BRIGHTNESS."""
    va: int                 # where the list is
    ids: tuple              # the game's ids, in page order
    getter_off: int         # file offset of the getter's ``movw r0``

    def has(self, category, ident):
        return ident in self.ids

    def lists(self, ident):
        return ident in self.ids

    def where(self, category):
        return "Adjustments > Standard Adjustments, at the end"

    def blob(self, *settings):
        ids = list(self.ids) + [i for _c, i in _new_rows(self, settings)]
        out = struct.pack("<%dH" % (len(ids) + 1), *(ids + [0]))
        return out + b"\x00" * (-len(out) % 4)

    def without(self, rows):
        """PAD-1394: this list less the ids of *rows* (``{(category, id)}``; the list has no pages)."""
        drop = {i for _c, i in rows}
        return dataclasses.replace(self, ids=tuple(i for i in self.ids if i not in drop))

    def shrink_writes(self, table, rows):
        """PAD-1394: the shorter list over the old one, NUL-ended, its tail zeroed (the page reads to the NUL)."""
        keep = self.without(rows).ids
        old = 2 * (len(self.ids) + 1)
        new = struct.pack("<%dH" % (len(keep) + 1), *(list(keep) + [0]))
        return {table._off(self.va): new + b"\x00" * (old - len(new))}

    def writes(self, table, new_va, *settings):
        data = table.data
        w0, w1 = struct.unpack_from("<2I", data, self.getter_off)
        lo, hi = new_va & 0xFFFF, new_va >> 16
        return {self.getter_off: struct.pack("<2I", (w0 & ~0x000F0FFF) | ((lo & 0xF000) << 4) | (lo & 0xFFF),
                                             (w1 & ~0x000F0FFF) | ((hi & 0xF000) << 4) | (hi & 0xFFF))}


@dataclass(frozen=True)
class WideCategoryTable:
    """PAD-1321: the category records of a 64-bit (Spike 3) program. The menu manager copies them at
    start as Spike 2's does (``adrp``/``add x1`` names them, ``mov x2, #size`` the copy), so a row is
    added by giving the table one more record in an appended read-only segment and re-pointing the
    copy (:func:`grow_wide_program`) - there is no same-size ``writes`` as there is for Spike 2
    (the append and the re-point are one step, they need the new segment's address), so
    :meth:`writes` is not used for this kind."""
    va: int
    records: tuple
    #: PAD-1394: how many records the program's copy says (its size constants) once :meth:`without` made *records*
    #: fewer; 0 = ``len(records)``
    code_records: int = 0

    def has(self, category, ident):
        return any(c == category and k == KIND_ADJUSTMENT and i == ident for c, k, i in self.records)

    def lists(self, ident):
        return any(k == KIND_ADJUSTMENT and i == ident for c, k, i in self.records)

    def where(self, category):
        return "Adjustments"

    def without(self, rows):
        """PAD-1394: this table less the adjustment records *rows*; the copy's size constants still read the old count."""
        return dataclasses.replace(self, records=_records_without(self.records, rows),
                                   code_records=self.code_records or len(self.records))

    def shrink_writes(self, table, rows):
        """PAD-1394: the shorter table over the old one, its tail zeroed, and the copy's sizes made the shorter one's
        (the stack buffer it copies into stays as large as it was)."""
        keep = _records_without(self.records, rows)
        sites = wide_copy_sites(table, self)
        out = _shrunk_in_place(table, self.va, self.records, keep)
        size = len(keep) * REC
        for kind, o in sites["size_offs"]:
            w = struct.unpack_from("<I", table.data, o)[0]
            out[o] = struct.pack("<I", _w_set_movz(w, size) if kind == "movz" else _w_set_imm12(w, size))
        return out

    def blob(self, *settings):
        recs = list(self.records) + [(c, KIND_ADJUSTMENT, i) for c, i in _new_rows(self, settings)]
        return b"".join(struct.pack("<3I", *r) for r in recs)

    def records_with(self, *settings):
        return len(self.records) + len(_new_rows(self, settings))

    def writes(self, table, new_va, *settings):
        # a 64-bit program's menu is grown by :func:`grow_wide_program`, not a same-size write
        raise MenuSettingError("use grow_wide_program for a Spike 3 menu")


#: the default reason a 64-bit program's menu cannot take a new row (a build whose menu-copy does
#: not match the compiler's pattern :func:`wide_copy_sites` reads; the finder gives a specific one)
WIDE_GROW_REFUSAL = "this Spike 3 game's operator-menu copy could not be read to add a row"


#: the category names (the menu's 37-line text table) of the pages our settings go on
CATEGORY_NAMES = {11: "LCD/Lamp", 13: "Audio Content", 15: OWN_PAGE, 16: "Attract Mode"}

#: PAD-724: ``<game>-<version>`` of the builds where MUSIC MODE and EDITION were SEEN working: the
#: latest build of every Stern Spike 2 game in the image library, each swept in the emulator (a set
#: built by Write's own code with both settings; the slot's sound fired in attract, both rows found
#: in the operator menu and set to 2 there, the sound fired again: mode 1's file before, mode 2's
#: after, and both values in the machine's NVM mirror; docs/plans/pad-724-editions-music-modes-
#: every-title.md). Not here: the three whose program cannot grow (:data:`NO_ROOM`) and every build
#: older than its game's latest.
PROVEN = frozenset({
    "aerosmith-1.16", "aerosmith_le-1.16", "avengers_infinity_le-1.10", "avengers_infinity_pro-1.10",
    "batman-1.14", "beatles-1.29", "deadpool_le-1.16", "deadpool_pro-1.16",
    "dungeons_and_dragons_le-1.10", "dungeons_and_dragons_pro-1.10", "elvira3-1.13",
    "foo_fighters_le-1.04", "foo_fighters_pro-1.04", "godzilla_le-1.16", "godzilla_pro-1.16",
    "guardians-1.15", "guardians_le-1.15", "iron_maiden_le-1.18", "iron_maiden_pro-1.18",
    "james_bond_pro-1.06", "jaws_le-1.02", "jaws_pro-1.02", "john_wick_le-1.02", "john_wick_pro-1.02",
    "jurassic_park_le-1.16", "jurassic_park_pro-1.16", "jurassic_park_the_pin-1.05",
    "king_kong_le-0.97", "king_kong_pro-0.97", "led_zeppelin_le-1.22", "led_zeppelin_pro-1.22",
    "mando_le-1.45", "mando_pro-1.45", "metallica_spike-1.04", "munsters_le-1.28", "munsters_pro-1.28",
    "rush_le-1.19", "rush_pro-1.19", "star_wars_elg-1.10", "star_wars_pro-1.31",
    "stranger_things-1.13", "stranger_things_le-1.13", "sword_of_rage_le-1.19",
    "sword_of_rage_pro-1.19", "turtles_le-1.59", "turtles_pro-1.59", "uncanny_xmen_le-0.98",
    "uncanny_xmen_pro-0.98", "venom_le-1.07", "venom_pro-1.07",
})
#: PAD-724: the latest builds whose game program has no address space free between its code and
#: its data (the engine's program-text growth never maps above its .bss), so no menu table of ours
#: can be placed: every other growth of their program text is refused the same way
NO_ROOM = frozenset({"james_bond_le-1.06", "james_bond_60th_le-1.11", "star_wars_le-1.31"})
#: PAD-724: the games whose Adjustments are Standard Adjustments and Feature Adjustments (no
#: category table, :class:`StandardList`): our rows are the last of Standard Adjustments
STANDARD_MENU = frozenset({
    "aerosmith", "aerosmith_le", "elvira3", "foo_fighters_le", "foo_fighters_pro", "guardians",
    "guardians_le", "led_zeppelin_le", "led_zeppelin_pro", "mando_le", "mando_pro", "munsters_le",
    "munsters_pro", "rush_le", "rush_pro", "sword_of_rage_le", "sword_of_rage_pro", "turtles_le",
    "turtles_pro", "venom_le", "venom_pro",
})


def menu_path(game_dir, key):
    """Where the operator finds setting *key* on game *game_dir*'s menu (``"Adjustments > ..."``)."""
    if game_dir in STANDARD_MENU:
        return "Adjustments > Standard Adjustments, at the end"
    return "Adjustments > Machine Settings > %s" % CATEGORY_NAMES[SETTINGS[key][3]]


#: the same, for a text that names no game
ANY_MENU_PATH = {
    MUSIC_MODE: "Adjustments > Machine Settings > Audio Content, or at the end of Standard "
                "Adjustments on a game whose Adjustments have that page",
    EDITION: "Adjustments > Machine Settings > Attract Mode, or at the end of Standard "
             "Adjustments on a game whose Adjustments have that page",
    COOP_PLAY: "Adjustments > Machine Settings > Attract Mode, or at the end of Standard "
               "Adjustments on a game whose Adjustments have that page",
    HANDICAP: "Adjustments > Machine Settings > Attract Mode, or at the end of Standard "
              "Adjustments on a game whose Adjustments have that page",
}


def _refs(data, va, consts=None, wide=False, skip=()):
    """How many times the program names address *va*: as a literal word, and (with *consts*, the
    menu reading's movw/movt map, or a 64-bit program's adrp/add one) as an address it builds.
    *skip* is the file ranges left out: a 64-bit PIE's relocation tables, which repeat every
    pointer they relocate as an addend (:func:`rela_spans`)."""
    pat = struct.pack("<Q" if wide else "<I", va)
    n = data.count(pat) - sum(data.count(pat, a, b) for a, b in skip)
    if consts is not None:
        n += len(consts.get(va, ()))
    return n


def _room(table, va, consts):
    """How many characters fit at *va* in place: the string there and the NULs after it that
    nothing names, less the one NUL that ends it."""
    o = table._off(va)
    if o is None:
        return 0
    end = table.data.find(b"\x00", o)
    if end < 0:
        return 0
    k = end + 1
    wide = getattr(table, "wide", False)
    skip = rela_spans(table) if wide else ()
    while k < len(table.data) and table.data[k] == 0 and not _refs(table.data, table._va(k), consts, wide, skip):
        k += 1
    return k - o - 1


def _imm12(w):
    rot = ((w >> 8) & 0xF) * 2
    v = w & 0xFF
    return ((v >> rot) | (v << (32 - rot))) & 0xFFFFFFFF if rot else v


def rela_spans(table):
    """PAD-1321: the file ranges of a 64-bit program's relocation tables (``DT_RELA``/``DT_RELASZ``
    and ``DT_JMPREL``/``DT_PLTRELSZ`` of its ``PT_DYNAMIC``). Every pointer the loader relocates is
    stored in place AND as the addend of its relocation, so counting who names an address leaves
    these out."""
    spans = getattr(table, "_rela_spans", None)
    if spans is not None:
        return spans
    data = table.data
    e_phoff = struct.unpack_from("<Q", data, 0x20)[0]
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x36)
    dyn = None
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        if struct.unpack_from("<I", data, o)[0] == 2:                       # PT_DYNAMIC
            dyn = struct.unpack_from("<Q", data, o + 8)[0], struct.unpack_from("<Q", data, o + 0x20)[0]
    tags = {}
    if dyn:
        for k in range(dyn[1] // 16):
            tag, val = struct.unpack_from("<2Q", data, dyn[0] + 16 * k)
            if tag == 0:
                break
            tags[tag] = val
    spans = []
    for at, size in ((7, 8), (23, 2)):                    # DT_RELA/DT_RELASZ, DT_JMPREL/DT_PLTRELSZ
        if at in tags and size in tags and table._off(tags[at]) is not None:
            a = table._off(tags[at])
            spans.append((a, a + tags[size]))
    table._rela_spans = tuple(spans)
    return table._rela_spans


#: PAD-1324: a 64-bit program's menu page record: {name line, 0, help, flags}, each 8 bytes
_W_PAGE_REC = 32
#: R_AARCH64_RELATIVE: the loader stores the load address plus the addend
_R_AARCH64_RELATIVE = 0x403


def _relative_addends(table):
    """PAD-1324: ``{pointer's file-va: addend}`` of every R_AARCH64_RELATIVE relocation of a 64-bit
    program (its ``DT_RELA`` table): where a PIE's pointer tables really point."""
    got = getattr(table, "_rel_addends", None)
    if got is not None:
        return got
    out = {}
    for a, b in rela_spans(table):
        for r_off, info, addend in struct.iter_unpack("<QQq", table.data[a:a + (b - a) // 24 * 24]):
            if info == _R_AARCH64_RELATIVE:
                out[r_off] = addend
    table._rel_addends = out
    return out


def _page_score(names):
    """How like the menu's page table a run of names is: the pages of ours it names, then its length
    (other tables start with INVALID too: ELG's wire colours are 187 records)."""
    want = {v.lower() for v in CATEGORY_NAMES.values()}
    return sum(1 for n in names.values() if n.strip().lower() in want), len(names)


def wide_category_names(table):
    """PAD-1324: ``{category number: name}`` of a 64-bit (Spike 3) program's operator-menu pages.

    The menu names each page by a record of :data:`_W_PAGE_REC` bytes, numbered from 0
    (``INVALID``) in category order: its first word points at the page's five-language name line
    (``char*[5]``, English first), so record 13 is "Audio Content" on every Spike 3 build that has
    the page (Star Wars ELG 1.10, Fallout LE 0.82, Transformers LE 0.96), and a title's own pages
    follow the system's (Fallout's 24.. are its features). In a PIE those pointers are relocations,
    so they are read off their addends. ``{}`` when the table is not found."""
    got = getattr(table, "_wide_cat_names", None)
    if got is not None:
        return got
    rel = _relative_addends(table)
    by_target = {}
    for at, a in rel.items():
        by_target.setdefault(a, []).append(at)

    def name(rec):
        line = rel.get(rec)
        return table._cstr(rel[line], 80) if line in rel else None

    out = {}
    o = table.data.find(b"\x00INVALID\x00")
    while o >= 0 and not out:
        va = table._va(o + 1)
        for line in (by_target.get(va) or ()):
            for rec in by_target.get(line) or ():
                k, names = 0, {}
                while True:
                    n = name(rec + k * _W_PAGE_REC)
                    if not n:
                        break
                    names[k] = n
                    k += 1
                if _page_score(names) > _page_score(out):
                    out = names
        o = table.data.find(b"\x00INVALID\x00", o + 1)
    if not _page_score(out)[0]:           # a table that names none of our pages is another one
        out = {}
    table._wide_cat_names = out
    return out


def wide_category(table, key):
    """PAD-1324: the category number a 64-bit program's menu calls the page setting *key* goes on
    (Spike 2's name for it, :data:`CATEGORY_NAMES`), found by the page's NAME: a Spike 3 build
    numbers its pages its own way. The first page of that name (Fallout LE 0.82 has two "Attract
    Mode" pages, the system's and its own). Raises :class:`MenuSettingError` when it has none."""
    want = CATEGORY_NAMES[SETTINGS[key][3]]
    names = wide_category_names(table)
    if not names:
        raise MenuSettingError("the game's operator menu page names could not be read")
    for num in sorted(names):
        if names[num].strip().lower() == want.lower():
            return num
    raise MenuSettingError("the game's operator menu has no %s page" % want)


def wide_consts(table):
    """PAD-1321: ``{va: [file offsets]}`` of every address a 64-bit program's code builds as
    ``adrp xd`` then ``add xd, xd, #lo12`` within the next eight instructions (how it names a
    string or a table), over its executable segments."""
    cached = getattr(table, "_wide_consts", None)
    if cached is not None:
        return cached
    import numpy as np
    data = table.data
    out = {}
    for po, pv, fsz in table._loads:
        base = (po + 3) & ~3
        n = (po + fsz - base) // 4
        if n <= 0:
            continue
        w = np.frombuffer(data, dtype="<u4", count=n, offset=base)
        adrp = np.flatnonzero((w & 0x9F000000) == 0x90000000)
        if not len(adrp):
            continue
        rd = w[adrp] & 0x1F
        imm = (((w[adrp] >> 29) & 3) | (((w[adrp] >> 5) & 0x7FFFF) << 2)).astype(np.int64)
        imm[imm >= (1 << 20)] -= 1 << 21
        pc = pv + (base - po) + 4 * adrp.astype(np.int64)
        page = (pc & ~0xFFF) + (imm << 12)
        for step in range(1, 9):
            k = adrp + step
            ok = k < n
            kk, rr, pp = k[ok], rd[ok], page[ok]
            a = w[kk]
            hit = ((a & 0xFFC00000) == 0x91000000) & ((a & 0x1F) == rr) & (((a >> 5) & 0x1F) == rr)
            for o, va in zip((base + 4 * kk[hit]).tolist(), (pp[hit] + ((a[hit] >> 10) & 0xFFF)).tolist()):
                out.setdefault(int(va), []).append(int(o))
    table._wide_consts = out
    return out


def wide_category_table(table, consts=None):
    """The :class:`WideCategoryTable` of a 64-bit program, or ``None``: an address its code builds
    into ``x1`` whose ``mov x2, #size`` follows within four instructions, *size* / 12 records
    ``{category < 64, kind 1..8, id < count}`` there (50 to 500 of them), exactly one such."""
    consts = wide_consts(table) if consts is None else consts
    data = table.data
    found = {}
    for va, offs in consts.items():
        o = table._off(va)
        if o is None:
            continue
        for off in offs:
            if data[off] & 0x1F != 1:
                continue
            for q in range(1, 5):
                if off + 4 * q + 4 > len(data):
                    break
                m = struct.unpack_from("<I", data, off + 4 * q)[0]
                if (m & 0xFFE0001F) != 0xD2800002:            # movz x2, #imm16
                    continue
                size = (m >> 5) & 0xFFFF
                if size % REC or not 50 * REC <= size <= 500 * REC or o + size > len(data):
                    continue
                recs = tuple(struct.unpack_from("<3I", data, o + REC * r) for r in range(size // REC))
                if all(c < 64 and 1 <= kd <= 8 and i < table.count for c, kd, i in recs):
                    found[va] = recs
    if len(found) != 1:
        return None
    va, recs = next(iter(found.items()))
    return WideCategoryTable(va, recs)


# ---------------------------------------------------------------------------
# PAD-1321: grow a 64-bit (Spike 3) program's menu by one or more records.
#
# The menu manager copies the category table (a literal run of {category, kind, id}) into a
# std::vector at start-up: ``adrp``/``add`` forms the table address, ``movz x2, #size`` and
# ``movz x0, #size`` give the ``memcpy`` and the ``operator new`` sizes, ``add x21, x0, #size`` the
# vector's end, and the table is staged through a stack buffer (``sub sp, sp, #F``) before the heap.
# The three Spike 3 row-taking builds (Star Wars ELG, Fallout, Transformers) share this exact
# codegen. To add a record: append the grown table as a read-only segment, re-point the ``adrp``/
# ``add`` at it, and raise the three size constants.
#
# The one hazard is the stack buffer: the compiler puts the function's STACK CANARY in the eight
# bytes at the top of that buffer (``[sp, #F-8]``), written at the prologue and re-checked on EVERY
# exit path (the normal return AND the exception landing pad). A longer copy would overwrite it, so
# the frame is grown by ``D`` (16-aligned) and the canary - every one of its accesses - moves up
# with it. A build whose menu-copy does not match this pattern, or that keeps some other local in
# the bytes the longer copy would cover, is refused rather than mis-patched.
# ---------------------------------------------------------------------------
_W_PAGE = 0x1000


def _w_adrp(rd, pc, tgt):
    d = ((tgt & ~0xFFF) - (pc & ~0xFFF)) >> 12
    return 0x90000000 | ((d & 3) << 29) | (((d >> 2) & 0x7FFFF) << 5) | rd


def _w_adrp_target(w, pc):
    d = (((w >> 5) & 0x7FFFF) << 2) | ((w >> 29) & 3)
    if d >= (1 << 20):
        d -= 1 << 21
    return (pc & ~0xFFF) + (d << 12)


def _w_is_addimm(w):
    return (w & 0xFFC00000) == 0x91000000


def _w_addimm_fields(w):
    return (w >> 10) & 0xFFF, (w >> 5) & 0x1F, w & 0x1F


def _w_is_movz(w):
    return (w & 0xFFE00000) == 0xD2800000


def _w_is_ldst_sp(w):
    return (w & 0xFFC003E0) in (0xF90003E0, 0xF94003E0)       # str/ldr x, [sp, #imm*8]


def _w_ldst_off(w):
    return ((w >> 10) & 0xFFF) * 8


def _w_set_imm12(w, imm):                                     # add/sub #imm12, or scaled ld/st off
    return (w & ~(0xFFF << 10)) | ((imm & 0xFFF) << 10)


def _w_set_movz(w, imm16):
    return (w & ~(0xFFFF << 5)) | ((imm16 & 0xFFFF) << 5)


def wide_copy_sites(table, cat):
    """Everything :func:`grow_wide_program` must patch to give *cat* one more record, read from the
    ELF, or raise :class:`MenuSettingError` when the build does not match the compiler's menu-copy
    pattern (so it is left alone rather than mis-patched). PAD-1321."""
    import numpy as np
    data = table.data
    va, size = cat.va, (getattr(cat, "code_records", 0) or len(cat.records)) * REC
    # the single adrp/add pair that forms the table address, and the segment it is in
    pairs, seg_of = [], {}
    for po, pv, fsz in table._loads:
        b = (po + 3) & ~3
        nn = (po + fsz - b) // 4
        if nn <= 0:
            continue
        ww = np.frombuffer(data, dtype="<u4", count=nn, offset=b)
        for k in np.flatnonzero((ww & 0x9F000000) == 0x90000000).tolist():
            pc = pv + (b - po) + 4 * k
            page, rd = _w_adrp_target(int(ww[k]), pc), int(ww[k]) & 0x1F
            for j in range(k + 1, min(nn, k + 9)):
                if _w_is_addimm(int(ww[j])):
                    imm, rn, rdj = _w_addimm_fields(int(ww[j]))
                    if rn == rd and rdj == rd and page + imm == va:
                        pairs.append((b + 4 * k, b + 4 * j))
                        seg_of[b + 4 * j] = (po, b, nn, ww)
                        break
    if len(pairs) != 1:
        raise MenuSettingError("the menu table's address is formed %d times, not once" % len(pairs))
    adrp_off, add_off = pairs[0]
    _po, base, n, w = seg_of[add_off]
    ai = (add_off - base) // 4
    # the memcpy/alloc sizes and the vector-end add, in the window after the address is formed
    size_offs = []
    for j in range(ai + 1, min(n, ai + 24)):
        wj = int(w[j])
        if _w_is_movz(wj) and ((wj >> 5) & 0xFFFF) == size:
            size_offs.append(("movz", base + 4 * j))
        elif _w_is_addimm(wj) and _w_addimm_fields(wj)[0] == size:
            size_offs.append(("add", base + 4 * j))
    kinds = [k for k, _ in size_offs]
    if kinds.count("movz") < 2 or kinds.count("add") < 1:
        raise MenuSettingError("the menu copy's size constants do not match the known pattern")
    # the stack buffer frame and its canary (the slot at F-8, checked on every exit path)
    sub_i = next((j for j in range(ai, max(0, ai - 400), -1) if (int(w[j]) & 0xFFC003FF) == 0xD10003FF), None)
    if sub_i is None:
        raise MenuSettingError("the menu copy's stack buffer could not be found")
    F = ((int(w[sub_i]) >> 10) & 0xFFF)
    add_sp_i = next((j for j in range(ai, min(n, ai + 400))
                     if (int(w[j]) & 0xFFC003FF) == 0x910003FF and ((int(w[j]) >> 10) & 0xFFF) == F), None)
    if add_sp_i is None:
        raise MenuSettingError("the menu copy's stack frame restore could not be found")
    canary_off = F - 8
    end = add_sp_i
    for j in range(add_sp_i + 1, min(n, ai + 600)):
        if (int(w[j]) & 0xFFE003E0) == 0xA98003E0:            # the next function's prologue
            break
        end = j
    saved, intruder = [], []
    for j in range(sub_i + 1, end + 1):
        wj = int(w[j])
        if _w_is_ldst_sp(wj):
            o = _w_ldst_off(wj)
            if o == canary_off:
                saved.append(base + 4 * j)
            elif size <= o < F:
                intruder.append(o)
    if intruder:
        raise MenuSettingError("the menu copy keeps a local where the longer table would go")
    if not saved:
        raise MenuSettingError("the menu copy's stack canary could not be found")
    return {"adrp": adrp_off, "add": add_off, "size_offs": size_offs,
            "F": F, "canary_off": canary_off, "sub": base + 4 * sub_i,
            "add_sp": base + 4 * add_sp_i, "saved": saved}


def _wide_append_segment(buf, blob):
    """Append *blob* (page-padded) to *buf* and map it read-only at an unclaimed vaddr above every
    PT_LOAD (so the load order stays ascending), repurposing PT_GNU_STACK, else PT_NOTE. Returns the
    virtual address. Raises :class:`MenuSettingError` when there is no advisory header to reuse."""
    e_phoff = struct.unpack_from("<Q", buf, 0x20)[0]
    phes, phn = struct.unpack_from("<HH", buf, 0x36)
    slot = hi = None
    for want in (0x6474E551, 4):                               # PT_GNU_STACK, then PT_NOTE
        for i in range(phn):
            o = e_phoff + i * phes
            if struct.unpack_from("<I", buf, o)[0] == want:
                slot = o
                break
        if slot is not None:
            break
    if slot is None:
        raise MenuSettingError("the program has no advisory header to map the grown menu table")
    hi = 0
    for i in range(phn):
        o = e_phoff + i * phes
        if struct.unpack_from("<I", buf, o)[0] == 1:
            hi = max(hi, struct.unpack_from("<Q", buf, o + 16)[0] + struct.unpack_from("<Q", buf, o + 40)[0])
    new_va = (hi + _W_PAGE - 1) & ~(_W_PAGE - 1)
    off = (len(buf) + _W_PAGE - 1) & ~(_W_PAGE - 1)
    want_sz = (len(blob) + _W_PAGE - 1) & ~(_W_PAGE - 1)
    buf.extend(b"\0" * (off - len(buf)))
    buf.extend(bytearray(blob) + b"\0" * (want_sz - len(blob)))
    struct.pack_into("<II", buf, slot, 1, 4)                   # p_type=PT_LOAD, p_flags=R
    struct.pack_into("<QQQQQ", buf, slot + 8, off, new_va, new_va, want_sz, want_sz)
    struct.pack_into("<Q", buf, slot + 48, _W_PAGE)
    return new_va


def grow_wide_program(table, cat, *settings):
    """Return a copy of the 64-bit program *table* whose operator menu lists *settings*' rows: the
    grown category table in an appended read-only segment, the start-up copy re-pointed at it, its
    size constants raised and its stack frame grown so the longer copy clears the canary. Raises
    :class:`MenuSettingError` when the build cannot be grown (:func:`wide_copy_sites`). PAD-1321."""
    add = [s for s in settings if not cat.has(s.category, s.id)]
    if not add:
        return bytes(table.data)
    sites = wide_copy_sites(table, cat)
    buf = bytearray(table.data)
    blob = cat.blob(*settings)
    new_size = len(cat.records) * REC + len(add) * REC
    new_va = _wide_append_segment(buf, blob)
    # re-point the copy at the grown table
    struct.pack_into("<I", buf, sites["adrp"], _w_adrp(1, sites["adrp"], new_va))
    aw = struct.unpack_from("<I", buf, sites["add"])[0]
    struct.pack_into("<I", buf, sites["add"], _w_set_imm12(aw, new_va & 0xFFF))
    for kind, o in sites["size_offs"]:
        wv = struct.unpack_from("<I", buf, o)[0]
        struct.pack_into("<I", buf, o, _w_set_movz(wv, new_size) if kind == "movz" else _w_set_imm12(wv, new_size))
    # grow the frame so the longer copy does not reach the canary, moving every canary access up
    F, canary = sites["F"], sites["canary_off"]
    D = (((new_size - canary) + 15) & ~15) if new_size > canary else 0
    if D:
        for off in (sites["sub"], sites["add_sp"]):
            struct.pack_into("<I", buf, off, _w_set_imm12(struct.unpack_from("<I", buf, off)[0], F + D))
        for off in sites["saved"]:
            wv = struct.unpack_from("<I", buf, off)[0]
            struct.pack_into("<I", buf, off, _w_set_imm12(wv, (canary + D) // 8))
    return bytes(buf)


def category_table(table):
    """The :class:`CategoryTable` of this program, or ``None``: two ``movw rd, #size`` (r0 for the
    allocation, r2 for the copy) a few words apart, a literal load into r1 between them naming a run
    of ``size / 12`` records ``{category < 64, kind 1..8, id < count}``, and the vector's end made
    as ``add rd, r0, #hi`` + ``add rd, rd, #lo`` with hi + lo = size."""
    data = table.data
    po, pv, fsz = table._loads[0]
    base = (po + 3) & ~3
    n = (po + fsz - base) // 4
    words = memoryview(data)[base:base + n * 4].cast("I")
    found = []
    for k in range(n):
        w = words[k]
        if (w & 0x0FF00000) != _MOVW or (w >> 12) & 0xF != 0:
            continue
        size = ((w >> 4) & 0xF000) | (w & 0xFFF)
        if size % REC or not 50 * REC <= size <= 500 * REC:
            continue
        for j in range(k + 1, min(n, k + 12)):
            wj = words[j]
            if (wj & 0x0FF00000) != _MOVW or (wj >> 12) & 0xF != 2 \
                    or (((wj >> 4) & 0xF000) | (wj & 0xFFF)) != size:
                continue
            lit = hi = lo_at = None
            for q in range(k + 1, min(n, j + 4)):
                wq = words[q]
                if (wq & 0x0F7F0000) == 0x051F0000 and (wq >> 12) & 0xF == 1:
                    imm = wq & 0xFFF
                    lit = table._va(base + 4 * q) + 8 + (imm if wq & 0x00800000 else -imm)
                elif (wq & 0x0FF00000) == _ADD_IMM and (wq >> 16) & 0xF == 0:
                    hi, hi_rd = _imm12(wq), (wq >> 12) & 0xF
                elif hi is not None and (wq & 0x0FF00000) == _ADD_IMM \
                        and (wq >> 16) & 0xF == hi_rd and (wq >> 12) & 0xF == hi_rd \
                        and hi + _imm12(wq) == size and not (wq & 0xF00):
                    lo_at = base + 4 * q
            if lit is None or lo_at is None or table._off(lit) is None:
                continue
            va = struct.unpack_from("<I", data, table._off(lit))[0]
            o = table._off(va)
            if o is None or o + size > len(data):
                continue
            recs = tuple(struct.unpack_from("<3I", data, o + REC * r) for r in range(size // REC))
            if all(c < 64 and 1 <= kd <= 8 and i < table.count for c, kd, i in recs):
                found.append(CategoryTable(va, recs, table._off(lit), (base + 4 * k, base + 4 * j),
                                           lo_at, hi))
    return found[0] if len(found) == 1 else None


def standard_list(table):
    """The :class:`StandardList` of a program without a category table, or ``None``: exactly one
    id-list page, its list reached through a ``movw r0 / movt r0 / bx lr`` getter that no other
    code calls. The game's own list stays where it is, so anything else that names it (Led
    Zeppelin LE 1.22 has a word of that value, in a pool of pc-relative offsets) reads it as
    before."""
    from . import menu_visibility as MV
    reading = MV.MenuVisibility(table)
    lists = [(ids, a) for kind, ids, _c, a in reading._pages_raw() if kind == "list"]
    if len(lists) != 1:
        return None
    ids, args = lists[0]
    r0 = args.get(0)
    if r0 is None or r0.form != "getter":
        return None
    getter = reading._bl_target(r0.off)
    go = table._off(getter) if getter is not None else None
    if go is None or reading._trivial_getter(getter) != r0.value:
        return None
    if len(reading._bls.get(getter, ())) != 1:
        return None
    return StandardList(r0.value, tuple(ids), go)


def menu_table(table, consts=None):
    """The menu this program lists its adjustments by: its :class:`CategoryTable`, else its
    :class:`StandardList` (PAD-724), else ``None``. PAD-1321: a 64-bit program's
    :class:`WideCategoryTable`."""
    if getattr(table, "wide", False):
        return wide_category_table(table, consts)
    return category_table(table) or standard_list(table)


def _row_caption_line(table, i):
    """``(file offset of the string, its text)`` of adjustment *i*'s row caption: line
    ``count - 1 - i`` of the text table of exactly ``count`` lines (five language pointers and a
    zero each), when all five name one string; else ``None``. PAD-1321: a 64-bit descriptor points
    at its line itself (``+0x28``)."""
    data = table.data
    if getattr(table, "wide", False):
        line = table._off(table.word(table.field_off(i, "row")))
        if line is None or line + 48 > len(data):
            return None
        ptrs = struct.unpack_from("<6Q", data, line)
        if ptrs[5] != 0 or len(set(ptrs[:5])) != 1:
            return None
        o = table._off(ptrs[0])
        if o is None:
            return None
        end = data.find(b"\x00", o)
        return o, data[o:end].decode("latin1")
    # PAD-1382: the table is found once a program and remembered (the Service menu tab asks for every row's caption:
    # a scan of the whole program per row was 58 s for Elvira 3's 386 rows)
    found = getattr(table, "_pad_row_lines", False)
    if found is False:
        found = _row_caption_table(table)
        try:
            table._pad_row_lines = found
        except AttributeError:
            pass
    if found is None:
        return None
    ptrs = struct.unpack_from("<5I", data, found + 24 * (table.count - 1 - i))
    if len(set(ptrs)) != 1:
        return None
    o = table._off(ptrs[0])
    if o is None:
        return None
    end = data.find(b"\x00", o)
    return o, data[o:end].decode("latin1")


def _row_caption_table(table):
    """The file offset of the row captions' text table (``count`` lines of five language pointers and a zero), or
    None."""
    data = table.data
    for po, pv, fsz in table._loads:
        base = (po + 3) & ~3
        n = (po + fsz - base) // 4
        words = memoryview(data)[base:base + n * 4].cast("I")
        k = 0
        while k + 6 <= n:
            w = words[k]
            if not (w and words[k + 1] == w and words[k + 4] == w and words[k + 5] == 0
                    and table._off(w) is not None):
                k += 1
                continue
            run = k
            while run + 6 <= n and words[run + 5] == 0 and words[run] and table._off(words[run]) is not None:
                run += 6
            if (run - k) // 6 == table.count:
                return base + 4 * k
            k = run if run > k else k + 1
    return None


def help_line(names, room):
    """The help line that names the modes - "1 = Standard, 2 = Orchestral" - in at most *room*
    characters (shorter forms first, then the names cut: the short ones kept whole, and a word
    several names share cut before the word that tells them apart - "2 Cust A 3 Cust B")."""
    names = [" ".join(str(n or "").split()) or "Mode %d" % (i + 1) for i, n in enumerate(names)]
    for sep, eq in ((", ", " = "), (", ", " "), (" ", " ")):
        s = sep.join("%d%s%s" % (i + 1, eq, n) for i, n in enumerate(names))
        if len(s) <= room:
            return s
    budget = room - sum(len("%d " % (i + 1)) for i in range(len(names))) - (len(names) - 1)
    each = max(1, max(len(n) for n in names))
    while each > 1 and sum(min(len(n), each) for n in names) > budget:
        each -= 1
    words = [n.lower().split() for n in names]
    shared = {w for i, ws in enumerate(words) for w in ws
              if any(w in other for j, other in enumerate(words) if j != i)}
    out = [_shortened(n, each, shared) for n in names]
    return " ".join("%d %s" % (i + 1, n) for i, n in enumerate(out))[:room]


def _shortened(name, n, shared):
    """*name* in at most *n* characters: words in *shared* cut (then left out) first, the
    others after."""
    words = name.split()
    common = [w.lower() in shared for w in words]
    while len(" ".join(words)) > n and len(words) > 1 and any(common):
        k = max((k for k in range(len(words)) if common[k]), key=lambda k: len(words[k]))
        if len(words[k]) > 1:
            words[k] = words[k][:-1]
        else:
            del words[k], common[k]
    return " ".join(words)[:n].rstrip()


def spare(table, taken=()):
    """The adjustments a setting of ours may take (PAD-537): every one the game captions as
    DEPRECATED, and every one a previous Write already gave a caption of ours, by name, highest id
    first, less the ids in *taken*."""
    ours = {v[1] for v in SETTINGS.values()}
    out = []
    for name, i in sorted(table.by_name.items(), key=lambda kv: -kv[1]):
        if i in taken:
            continue
        label = menu_label(table, i)
        if label.upper().startswith(DEPRECATED) or label in ours:
            out.append(name)
    return out


#: PAD-1017: the descriptor word saying how the menu shows a value (2 a number, 9 Yes/No, 1 Off/On - CUSTOM MESSAGE's,
#: values 0 and 1, on every latest build); only the 44-byte descriptors have it
OFF_KIND = 0x24
ONOFF_ROW = "AD_CUSTOM_MESSAGE"


def _kind_elem(table):
    """The descriptor size that carries a display kind: 44 bytes on Spike 2, 64 on Spike 3."""
    return 64 if getattr(table, "wide", False) else 44


def _kind_at(table, i):
    """Descriptor *i*'s display kind: a u32 on Spike 2, the u16 below the category on Spike 3."""
    return struct.unpack_from("<H" if table.wide else "<I", table.data, table.field_off(i, "kind"))[0]


def _kind_bytes(table, kind):
    return struct.pack("<H" if table.wide else "<I", kind)


def onoff_kind(table):
    """The display kind of the game's own Off/On row (CUSTOM MESSAGE), or raise :class:`MenuSettingError`."""
    if table.elem != _kind_elem(table) or ONOFF_ROW not in table.by_name:
        raise MenuSettingError("the game has no Off/On setting to show this one like")
    i = table.by_name[ONOFF_ROW]
    low, high = (struct.unpack_from("<I", table.data, table.field_off(i, f))[0] for f in ("min", "max"))
    kind = _kind_at(table, i)
    if (low, high) != (0, 1) or not 0 < kind < 64:
        raise MenuSettingError("the game's own Off/On setting reads %d..%d, kind %d" % (low, high, kind))
    return kind


#: PAD-1042: a row of numbers from 0 (CO-OP PLAY's 0 Off, 1 Co-op, 2 Team 2v2) shows its value the way the game's own
#: GAME ID does: a plain number (kind 2 on every latest build); the help line names what each number is
NUMBER_ROW = "AD_GAME_ID"


def number_kind(table):
    """The display kind of the game's own plain-number row (GAME ID), or raise :class:`MenuSettingError`."""
    if table.elem != _kind_elem(table) or NUMBER_ROW not in table.by_name:
        raise MenuSettingError("the game has no numbered setting to show this one like")
    kind = _kind_at(table, table.by_name[NUMBER_ROW])
    if not 0 < kind < 64:
        raise MenuSettingError("the game's own numbered setting reads kind %d" % kind)
    return kind


def _help_text(names, values, help_text, room):
    """A setting's help line in *room* characters: its own line, or its values' names."""
    if help_text is not None:
        return " ".join(str(help_text).split())[:room].rstrip()
    return help_line(list(names)[:values] + ["Mode %d" % (k + 1) for k in range(len(names), values)], room)


def plan(table, key, values, names=(), ad=None, default=1, help_text=None, onoff=False, from_zero=False,
         category=None):
    """``(MenuSetting, {file offset: bytes}, CategoryTable or None)``: the same-size writes that
    make setting *key* (values 1..*values*, its help naming *names*), and the category table to
    give one more record (:func:`table_writes`) - ``None`` when a previous Write already did. Raises
    :class:`MenuSettingError` when this program cannot take it (the reason is the message).
    PAD-537: *ad* is the adjustment to take over (a picture setting's, :func:`plan_many` picks
    one), *default* the value a fresh store starts at, *help_text* a help line of the setting's
    own in place of the names. PAD-1017: *onoff* shows the two values as Off and On, the way the game's own CUSTOM
    MESSAGE does (stored 0 and 1; *default* still counts from 1: 1 Off, 2 On). PAD-1042: *from_zero* stores and shows
    the values as plain numbers from 0 (the help line says what each is; *default* still counts from 1), so a row that
    was Off/On (0 and 1) keeps an operator's pick when it grows a value."""
    from . import menu_visibility as MV
    if key not in SETTINGS:
        raise MenuSettingError("no such setting: %s" % key)
    fixed, caption, row_caption, own_category = SETTINGS[key]
    category = own_category if category is None else int(category)     # PAD-1382: the page of our own
    if getattr(table, "wide", False):
        category = wide_category(table, key)        # PAD-1324: the page by its name on Spike 3
    ad = ad or fixed
    if ad is None:
        raise MenuSettingError("the game has no spare setting left for %s" % caption)
    values = int(values)
    ceiling = MAX_VALUES if help_text is None else VALUES_CEILING
    if not 2 <= values <= ceiling:
        raise MenuSettingError("a setting of ours offers 2 to %d values, not %d" % (ceiling, values))
    if not 1 <= int(default) <= values:
        raise MenuSettingError("a default of %s is not one of the values 1 to %d" % (default, values))
    if onoff and values != 2:
        raise MenuSettingError("an Off/On setting has two values, not %d" % values)
    kind = onoff_kind(table) if onoff else number_kind(table) if from_zero else 0
    low = 0 if onoff or from_zero else 1
    if ad not in table.by_name:
        raise MenuSettingError("the game has no %s to take over" % ad)
    i = table.by_name[ad]
    desc = table._off(table.table_va + i * table.elem)
    f = getattr(table, "fields", None) or {"default": OFF_DEFAULT, "min": OFF_MIN, "max": OFF_MAX,
                                            "step": OFF_STEP, "label": OFF_MENU_LABEL,
                                            "help": OFF_MENU_HELP, "kind": OFF_KIND}
    wide = getattr(table, "wide", False)
    label = menu_label(table, i)
    # a previous Write's caption of ours (PAD-537: a spare one may have held another of ours)
    ours = label in {v[1] for v in SETTINGS.values()}
    if not ours and not label.upper().startswith(DEPRECATED):
        raise MenuSettingError("the game's %s is \"%s\", not a setting it says it no longer uses"
                               % (ad, label))
    skip = ()
    if wide:
        consts = wide_consts(table)
        skip = rela_spans(table)
    else:
        reading = MV.MenuVisibility(table)
        reading._scan()
        consts = reading._consts
    data = table.data
    live = table.word(desc) if wide else struct.unpack_from("<I", data, desc)[0]
    if _refs(data, live, consts, wide, skip) != 1:
        raise MenuSettingError("the game's program reads %s's value directly" % ad)
    cat = menu_table(table, consts) if wide else menu_table(table)
    if cat is None:
        raise MenuSettingError("the game's operator menu pages could not be read")
    if not ours and cat.lists(i):
        raise MenuSettingError("the game's menu already lists %s" % ad)
    row = _row_caption_line(table, i)
    if row is None:
        raise MenuSettingError("the game's menu captions could not be read")
    if wide:
        cap_va, help_va = table.word(desc + f["label"]), table.word(desc + f["help"])
    else:
        cap_va = struct.unpack_from("<I", data, desc + OFF_MENU_LABEL)[0]
        help_va = struct.unpack_from("<I", data, desc + OFF_MENU_HELP)[0]
    for what, va in (("caption", cap_va), ("help line", help_va)):
        if table._off(va) is None or _refs(data, va, consts, wide, skip) != 1:
            raise MenuSettingError("%s's %s is shared with other settings" % (ad, what))
    row_va = table._va(row[0])
    if _refs(data, row_va, consts, wide, skip) != 5:
        raise MenuSettingError("%s's row caption is shared with other text" % ad)
    cap_room, help_room = _room(table, cap_va, consts), _room(table, help_va, consts)
    row_room = _room(table, row_va, consts)
    if row_room >= len(row_caption):
        row_caption = shown_caption(key, row_room)  # "Image Set *": a change shows from the next power-up
    if cap_room < len(caption) or row_room < len(row_caption):
        raise MenuSettingError("%s's caption has no room for \"%s\"" % (ad, row_caption))
    if help_room < 12:
        raise MenuSettingError("%s's help line has no room to name the modes" % ad)
    text = _help_text(names, values, help_text, help_room)
    writes = {
        table._off(cap_va): caption.encode("ascii") + b"\x00" * (cap_room + 1 - len(caption)),
        row[0]: row_caption.encode("ascii") + b"\x00" * (row_room + 1 - len(row_caption)),
        table._off(help_va): text.encode("ascii", "replace") + b"\x00" * (help_room + 1 - len(text)),
    }
    for off, v in ((f["default"], int(default) - 1 + low), (f["min"], low), (f["max"], values - 1 + low),
                   (f["step"], 1)):
        writes[desc + off] = struct.pack("<i", v)
    if kind:
        writes[desc + f["kind"]] = _kind_bytes(table, kind) if wide else struct.pack("<i", kind)
    where = cat.where(category)
    if wide:            # PAD-1324: the page by its own name (Spike 3 lists it under Machine Settings)
        where = "Adjustments > Machine Settings > %s" % wide_category_names(table).get(category, "?")
    setting = MenuSetting(key, i, row_caption, text, values, live, category, int(default) - 1 + low,
                          where, low, kind)
    return setting, writes, (None if cat.has(category, i) else cat)


def category_name_line(table, category):
    """PAD-1382: the file offset of *category*'s line in the game's table of page names (five language pointers and a
    zero; category c c lines above the line that names INVALID, category 0), or None (Spike 2's 44-byte programs)."""
    raw = table.data
    if getattr(table, "wide", False) or table.elem != 44:
        return None
    found = getattr(table, "_pad_invalid_line", False)
    if found is False:
        found = None
        k = raw.find(b"INVALID\x00")              # the linker shares tails: it may end a longer string
        while k >= 0 and found is None:
            va = table._va(k)
            r = raw.find(struct.pack("<I", va)) if va else -1
            while r >= 0:
                if r % 4 == 0 and r + 24 <= len(raw):
                    w = struct.unpack_from("<6I", raw, r)
                    if w[5] == 0 and all(table._off(x) is not None for x in w[:5]):
                        found = r
                        break
                r = raw.find(struct.pack("<I", va), r + 1)
            k = raw.find(b"INVALID\x00", k + 1)
        try:
            table._pad_invalid_line = found
        except AttributeError:
            pass
    if found is None or found - category * 24 < 0:
        return None
    return found - category * 24


def _category_rows(table, cat, category):
    """The ids the menu lists on *category*'s page: its records, and the feature rows whose descriptor names it."""
    ids = [i for c, k, i in cat.records if c == category and k == KIND_ADJUSTMENT]
    listed = {i for _c, k, i in cat.records if k == KIND_ADJUSTMENT}
    if table.elem == 44:
        for i in range(160, table.count):
            if i not in listed and struct.unpack_from("<H", table.data, table._off(table.table_va + i * table.elem)
                                                     + 0x26)[0] == category:
                ids.append(i)
    return ids


def own_page(table, starred=False):
    """PAD-1382: ``{file offset: bytes}`` that name :data:`OWN_CATEGORY`'s page :data:`OWN_PAGE` in the game's own table
    of page names, or raise :class:`MenuSettingError` when this program cannot have a page of our own (its rows go on the
    pages each setting names, as before): a category table (not the older Standard Adjustments list, nor a 64-bit
    program), nothing but ours on that page, and each of its name strings the line's alone, with room."""
    if getattr(table, "wide", False):
        raise MenuSettingError("a 64-bit game's menu pages are not renamed yet")
    cat = menu_table(table)
    if not isinstance(cat, CategoryTable):
        raise MenuSettingError("the game's menu has no pages of categories")
    ours = {v[1] for v in SETTINGS.values()}
    for i in _category_rows(table, cat, OWN_CATEGORY):
        if menu_label(table, i) not in ours:
            raise MenuSettingError("the game lists its own %s on that page" % menu_label(table, i))
    line = category_name_line(table, OWN_CATEGORY)
    if line is None:
        raise MenuSettingError("the game's table of page names could not be read")
    ptrs = struct.unpack_from("<5I", table.data, line)
    writes = {}
    for va in set(ptrs):
        o = table._off(va)
        if o is None:
            raise MenuSettingError("the page's name is not in the program")
        end = table.data.find(b"\x00", o)
        old = table.data[o:end]
        refs = table.data.count(struct.pack("<I", va))
        if refs != ptrs.count(va):
            raise MenuSettingError("the page's name \"%s\" is used elsewhere too" % old.decode("latin1"))
        if len(old) < len(OWN_PAGE):
            raise MenuSettingError("the page's name has no room for \"%s\"" % OWN_PAGE)
        writes[o] = OWN_PAGE.encode("ascii") + b"\x00" * (len(old) - len(OWN_PAGE))
    # the Machine Settings list's help for the page ("Wireless audio devices, such as headphones, can be connected to
    # this game." on Godzilla LE 1.16 in the emulator): the menu entry that names the page's name line has it two
    # words after, a string of its own - rewritten in place when it is the entry's alone and has room
    line_va = table._va(line)
    r = table.data.find(struct.pack("<I", line_va)) if line_va else -1
    while 0 <= r <= len(table.data) - 12:
        help_va = struct.unpack_from("<I", table.data, r + 8)[0]
        o = table._off(help_va) if r % 4 == 0 else None
        if o is not None and table.data.count(struct.pack("<I", help_va)) == 1:
            end = table.data.find(b"\x00", o)
            # its room: the string and the zeros after it but the last (a card an earlier Write gave the shorter
            # help keeps the stock line's room in those zeros)
            pad = end
            while pad + 1 < len(table.data) and table.data[pad + 1] == 0:
                pad += 1
            room = pad - o
            # a power-up setting on the page: the help says what its asterisk means, in the longest form with room
            text = next((t for t in (OWN_HELP_POWER_UP if starred else ()) + (OWN_HELP,) if len(t) <= room), None)
            if text is not None:
                writes[o] = text.encode("ascii") + b"\x00" * (room - len(text))
            break
        r = table.data.find(struct.pack("<I", line_va), r + 1)
    return writes


def plan_many(table, wanted, share=True):
    """:func:`_plan_many`, and PAD-1394: the rows an earlier Write gave settings of ours that this one no longer wants
    (:func:`stale_rows`: EDITION or HANDICAP turned off, settings moved onto the shared rows or onto another page) are
    taken off the menu - left out of the table to grow when one grows, else by same-size writes in *writes*. The same
    ``(settings, writes, cat, refused)``."""
    settings, writes, cat, refused = _plan_many(table, wanted, share)
    if not settings:
        return settings, writes, cat, refused
    try:
        current = menu_table(table)
        rows = stale_rows(table, current, settings) if current is not None else []
        if rows and cat is not None:
            cat = cat.without(rows)
        elif rows:
            writes = {**writes, **current.shrink_writes(table, rows)}
    except MenuSettingError:                # a copy that cannot be re-sized keeps its rows, as before
        pass
    return settings, writes, cat, refused


def _plan_many(table, wanted, share=True):
    """Several settings of ours at once, each on a row of its own (:func:`_plan_rows`) - or, PAD-1382, when the game
    has too few spare rows for them, all but EDITION on the two shared rows (:func:`plan_shared`), when it can give
    those. *share* False never shares. The same ``(settings, writes, cat, refused)``.

    PAD-1382 round 5: when the program can have a page of our own (:func:`own_page`), every row goes on it, the page's
    name written with the rows."""
    page = {}
    if wanted:
        try:
            page = own_page(table, starred=any(w[0] in POWER_UP for w in wanted))
        except MenuSettingError:
            page = {}
    if page:
        wanted = [(w[0], w[1], w[2], dict(w[3] if len(w) > 3 else {}, category=OWN_CATEGORY)) for w in wanted]
    settings, writes, cat, refused = _plan_rows(table, wanted)
    if page and settings:
        writes = {**writes, **page}
    if not share or getattr(table, "wide", False):
        return settings, writes, cat, refused
    rows = [tuple(w) + ({},) if len(w) == 3 else tuple(w) for w in wanted]
    # a shareable setting refused a row of its own - no spare left, or the spare it last tried cannot be used (Iron
    # Maiden Pro 1.18's first shares its row caption: the library sweep, round 4) - is tried on the shared rows
    if (not any(k not in NOT_SHARED for k in refused)
            or len([r for r in rows if r[0] not in NOT_SHARED]) < 2):
        return settings, writes, cat, refused
    try:
        settings, writes, cat, refused = plan_shared(table, rows)
        if page and settings:
            writes = {**writes, **page}
        return settings, writes, cat, refused
    except MenuSettingError as e:
        for key in refused:
            refused[key] = "%s; nor can the settings share two rows: %s" % (str(refused[key]).rstrip("."), e)
        return settings, writes, cat, refused


def _plan_rows(table, wanted):
    """Several settings of ours at once (PAD-495: MUSIC MODE and EDITION on one card).

    *wanted* is ``[(key, values, names), ...]``, or ``(key, values, names, options)`` with
    *options* :func:`plan`'s ``default``/``help_text``. Returns ``(settings, writes, cat,
    refused)``: the :class:`MenuSetting` of each that this program can take, their same-size
    writes merged, the category table to grow (``None`` when every one of them is already
    listed) and ``{key: reason}`` for the ones it cannot. One setting refused never stops another.

    PAD-537: the settings with an adjustment of their own go first; then each picture setting
    takes the first spare one (:func:`spare`) none of them took, its own from a previous Write
    first, in the order *wanted* names them."""
    settings, writes, refused, cat = [], {}, {}, None
    taken = set()
    rows = [tuple(w) + ({},) if len(w) == 3 else tuple(w) for w in wanted]
    fixed = [r for r in rows if SETTINGS.get(r[0], (None,))[0] is not None or r[0] not in SETTINGS]
    pooled = [r for r in rows if r not in fixed]
    for key in [r[0] for r in fixed] + [r[0] for r in pooled]:
        row = next(r for r in rows if r[0] == key)
        _k, values, names, opts = row
        ad = None
        if row in pooled:
            caption = SETTINGS[key][1]
            free = spare(table, taken)
            mine = [n for n in free if menu_label(table, table.by_name[n]) == caption]
            # PAD-1393: a spare an earlier Write captioned for another setting of ours is held back only while that
            # setting is wanted on this card too; one this Write no longer wants is free (a card the app wrote with
            # MUSIC MODE, EDITION and HANDICAP had no spare left for IMAGE SET once HANDICAP and EDITION were off).
            # Tried after the DEPRECATED ones, so the old caption is kept while there is room.
            ours = {v[1] for v in SETTINGS.values()}
            others = {SETTINGS[r[0]][1] for r in rows if r[0] != key and r[0] in SETTINGS}
            labels = {n: menu_label(table, table.by_name[n]) for n in free}
            free = (mine + [n for n in free if labels[n] not in ours]
                    + [n for n in free if labels[n] in ours and labels[n] not in others and n not in mine])
            if not free:
                refused[key] = ("%s %s (the card's other menu settings of ours use them)"
                                % (NO_SPARE, caption))
                continue
        # PAD-1017: a spare one this program cannot give (Iron Maiden Pro 1.18's first shares its row caption) is passed
        # over for the next
        tries = free if row in pooled else [None]
        setting = None
        for ad in tries:
            try:
                setting, w, c = plan(table, key, values, names, ad=ad, **opts)
                break
            except MenuSettingError as e:
                refused[key] = str(e)
        if setting is None:
            continue
        refused.pop(key, None)
        taken.add(setting.id)
        settings.append(setting)
        writes.update(w)
        if c is not None:
            cat = c
    order = [r[0] for r in rows]
    settings.sort(key=lambda st: order.index(st.key))
    return settings, writes, cat, refused


def _row_places(table, i):
    """Where the runtime rewrites row *i* (a Spike 2 program's): ``(descriptor, help string, its room, row caption
    string, its room)`` as addresses in the running game."""
    from . import menu_visibility as MV
    reading = MV.MenuVisibility(table)
    reading._scan()
    consts = reading._consts
    desc = table.table_va + i * table.elem
    help_va = struct.unpack_from("<I", table.data, table._off(desc) + OFF_MENU_HELP)[0]
    row = _row_caption_line(table, i)
    if row is None:
        raise MenuSettingError("the game's menu captions could not be read")
    row_va = table._va(row[0])
    return desc, help_va, _room(table, help_va, consts), row_va, _room(table, row_va, consts)


def plan_shared(table, rows):
    """PAD-1382: the settings of *rows* (``(key, values, names, options)``) on the two shared rows, EDITION on a row of
    its own: ``(settings, writes, cat, refused)`` as :func:`plan_many`. *settings* holds MORE SETTINGS and the row
    under it, then each shared setting with ``live`` its runtime word (``SHARED_BASE + 4k``) and ``shared`` ``(k,)``;
    :func:`shared_cfg_text` writes the runtime's table of them. Raises :class:`MenuSettingError` when the program
    cannot give the two rows; a setting that cannot be shown on them is refused on its own."""
    if getattr(table, "wide", False):
        raise MenuSettingError("a 64-bit game's settings cannot share rows yet")
    own = [r for r in rows if r[0] in NOT_SHARED]
    share, refused = [], {}
    for key, values, names, opts in [r for r in rows if r[0] not in NOT_SHARED]:
        values, default = int(values), int(opts.get("default", 1))
        ceiling = MAX_VALUES if opts.get("help_text") is None else VALUES_CEILING
        try:
            if key not in SETTINGS:
                raise MenuSettingError("no such setting: %s" % key)
            if not 2 <= values <= ceiling:
                raise MenuSettingError("a setting of ours offers 2 to %d values, not %d" % (ceiling, values))
            if not 1 <= default <= values:
                raise MenuSettingError("a default of %s is not one of the values 1 to %d" % (default, values))
            if opts.get("onoff") and values != 2:
                raise MenuSettingError("an Off/On setting has two values, not %d" % values)
            # the row shows each one as its own row would: Off/On, or a plain number
            kind = (onoff_kind(table) if opts.get("onoff") else number_kind(table)
                    if table.elem == _kind_elem(table) else 0)
        except MenuSettingError as e:
            refused[key] = str(e)
            continue
        share.append((key, values, names, opts, kind))
    if len(share) < 2:
        raise MenuSettingError("fewer than two of them can be shown there")
    if len(share) > MAX_VALUES:
        raise MenuSettingError("more than %d settings of ours cannot share them" % MAX_VALUES)
    first = share[0]
    picks = [SETTINGS[k][2] for k, *_ in share]
    on = {"category": first[3]["category"]} if "category" in first[3] else {}      # the page of our own
    settings, writes, cat, own_refused = _plan_rows(
        table, own + [(MORE_SELECT, len(share), picks, on), (MORE_VALUE, first[1], first[2], dict(first[3]))])
    refused.update({k: v for k, v in own_refused.items() if k not in (MORE_SELECT, MORE_VALUE)})
    by_key = {st.key: st for st in settings}
    pick, value = by_key.get(MORE_SELECT), by_key.get(MORE_VALUE)
    if pick is None or value is None:
        raise MenuSettingError(own_refused.get(MORE_SELECT) or own_refused.get(MORE_VALUE) or "unknown")
    desc, help_va, help_room, row_va, row_room = _row_places(table, value.id)
    kind_off = OFF_KIND if table.elem == _kind_elem(table) else -1
    value = dataclasses.replace(value, shared=(desc, help_va, help_room, row_va, row_room, OFF_DEFAULT, OFF_MIN,
                                               OFF_MAX, kind_off))
    out = [st for st in settings if st.key not in (MORE_SELECT, MORE_VALUE)] + [pick, value]
    for k, (key, values, names, opts, kind) in enumerate(share, 1):
        low = 0 if opts.get("onoff") or opts.get("from_zero") else 1
        out.append(MenuSetting(
            key, value.id, shown_caption(key, row_room), _help_text(names, values, opts.get("help_text"), help_room),
            values, SHARED_BASE + 4 * k, value.category, int(opts.get("default", 1)) - 1 + low,
            "%s, %s %d" % (pick.where, SETTINGS[MORE_SELECT][1], k), low, kind, (k,)))
    return out, writes, cat, refused


def shared_cfg_text(settings):
    """``settings.cfg``, the runtime's table of the shared rows (pad_mode_runtime.c "more settings") for *settings*
    from :func:`plan_many`; ``""`` when none share."""
    by_key = {st.key: st for st in settings}
    pick, value = by_key.get(MORE_SELECT), by_key.get(MORE_VALUE)
    opts = sorted((st for st in settings if is_shared(st)), key=lambda st: st.shared[0])
    if pick is None or value is None or not opts:
        return ""

    def clean(t):
        return " ".join(str(t).replace("\t", " ").split())

    lines = ["# PAD-1382: settings of ours sharing MORE SETTINGS and the row under it"]
    desc, help_va, help_room, row_va, row_room, o_def, o_min, o_max, o_kind = value.shared
    lines += ["select\t0x%08x\t%d" % (pick.live, len(opts)),
              "value\t0x%08x\t0x%08x\t0x%08x\t%d\t0x%08x\t%d" % (value.live, desc, help_va, help_room, row_va,
                                                                  row_room),
              "fields\t%d\t%d\t%d\t%d" % (o_def, o_min, o_max, o_kind)]
    for st in opts:
        lines.append("option\t%d\t%s\t%d\t%d\t%d\t%d\t%s\t%s" % (
            st.shared[0], st.key, st.low, st.values - 1 + st.low, st.default, st.kind,
            clean(st.caption) or "Setting", clean(st.help)))
    return "\n".join(lines) + "\n"


def is_shared(setting):
    """PAD-1382: does *setting* (a :class:`MenuSetting`) live on the shared rows?"""
    return bool(setting is not None and setting.shared and setting.key not in (MORE_SELECT, MORE_VALUE))


def table_blob(cat, *settings):
    """The menu's table (a :class:`CategoryTable` or a :class:`StandardList`) with the settings
    added (those it does not list yet): the bytes to place (4-byte aligned)."""
    return cat.blob(*settings)


def table_writes(table, cat, new_va, *settings):
    """``{file offset: bytes}`` that point the menu at its table grown by *settings*, placed at
    *new_va*: a category table's literal, both sizes and the vector's end; a Standard
    Adjustments list's getter. Raises :class:`MenuSettingError` when the new size cannot be
    encoded the way the old one was."""
    return cat.writes(table, new_va, *settings)


def check(raw, setting):
    """Read the setting back out of a finished program *raw*: ``[]`` when its descriptor, its
    captions, its help and its row on the category page all say what the build wrote, else what
    does not."""
    from .adjustments import AdjustmentTable
    bad = []
    try:
        t = AdjustmentTable(raw, wide_ok=True)
        e = t.entry(setting.id)
        got_help = t._cstr(t.word(t.field_off(setting.id, "help")), 200)
        cat = menu_table(t)
        row = _row_caption_line(t, setting.id)
    except Exception as ex:                                   # noqa: BLE001
        return ["the program does not read back (%s)" % ex]
    if (e["default"], e["min"], e["max"], e["step"]) != (setting.default, setting.low,
                                                          setting.values - 1 + setting.low, 1):
        bad.append("its range reads %d..%d" % (e["min"], e["max"]))
    if setting.kind and _kind_at(t, setting.id) != setting.kind:
        bad.append("it does not show its values as written")
    if menu_label(t, setting.id) != SETTINGS[setting.key][1]:
        bad.append("its caption reads \"%s\"" % menu_label(t, setting.id))
    if row is None or row[1] != setting.caption:
        bad.append("its row caption reads \"%s\"" % (row[1] if row else "?"))
    if got_help != setting.help:
        bad.append("its help reads \"%s\"" % got_help)
    if cat is None or not cat.has(setting.category, setting.id):
        bad.append("no menu page lists it")
    return bad


def offered(elf_bytes, key=MUSIC_MODE):
    """``""`` when this program can take setting *key*, else the reason it cannot."""
    from .adjustments import AdjustmentTable
    try:
        t = AdjustmentTable(elf_bytes, wide_ok=True)
        _s, _w, cat = plan(t, key, 2)
        # PAD-1321: a 64-bit program's menu must be growable too (the row is placed by growing the
        # category table, not a same-size write) - check its menu-copy matches the known pattern
        if isinstance(cat, WideCategoryTable):
            wide_copy_sites(t, cat)
    except MenuSettingError as e:
        return str(e)
    except ValueError as e:
        return "the game's settings could not be read (%s)" % e
    return ""
