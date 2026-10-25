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
"""
from __future__ import annotations

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
}
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
        recs = list(self.records) + [(s.category, KIND_ADJUSTMENT, s.id) for s in settings
                                     if not self.has(s.category, s.id)]
        return b"".join(struct.pack("<3I", *r) for r in recs)

    def records_with(self, *settings):
        return len(self.records) + sum(1 for s in settings if not self.has(s.category, s.id))

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
        ids = list(self.ids) + [s.id for s in settings if s.id not in self.ids]
        out = struct.pack("<%dH" % (len(ids) + 1), *(ids + [0]))
        return out + b"\x00" * (-len(out) % 4)

    def writes(self, table, new_va, *settings):
        data = table.data
        w0, w1 = struct.unpack_from("<2I", data, self.getter_off)
        lo, hi = new_va & 0xFFFF, new_va >> 16
        return {self.getter_off: struct.pack("<2I", (w0 & ~0x000F0FFF) | ((lo & 0xF000) << 4) | (lo & 0xFFF),
                                             (w1 & ~0x000F0FFF) | ((hi & 0xF000) << 4) | (hi & 0xFFF))}


#: the category names (the menu's 37-line text table) of the pages our settings go on
CATEGORY_NAMES = {11: "LCD/Lamp", 13: "Audio Content", 16: "Attract Mode"}

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
}


def _refs(data, va, consts=None):
    """How many times the program names address *va*: as a literal word, and (with *consts*, the
    menu reading's movw/movt map) as an address it builds."""
    n = data.count(struct.pack("<I", va))
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
    while k < len(table.data) and table.data[k] == 0 and not _refs(table.data, table._va(k), consts):
        k += 1
    return k - o - 1


def _imm12(w):
    rot = ((w >> 8) & 0xF) * 2
    v = w & 0xFF
    return ((v >> rot) | (v << (32 - rot))) & 0xFFFFFFFF if rot else v


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


def menu_table(table):
    """The menu this program lists its adjustments by: its :class:`CategoryTable`, else its
    :class:`StandardList` (PAD-724), else ``None``."""
    return category_table(table) or standard_list(table)


def _row_caption_line(table, i):
    """``(file offset of the string, its text)`` of adjustment *i*'s row caption: line
    ``count - 1 - i`` of the text table of exactly ``count`` lines (five language pointers and a
    zero each), when all five name one string; else ``None``."""
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
            lines = (run - k) // 6
            if lines == table.count:
                line = k + 6 * (table.count - 1 - i)
                ptrs = [words[line + m] for m in range(5)]
                if len(set(ptrs)) != 1:
                    return None
                o = table._off(ptrs[0])
                end = data.find(b"\x00", o)
                return o, data[o:end].decode("latin1")
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


def plan(table, key, values, names=(), ad=None, default=1, help_text=None):
    """``(MenuSetting, {file offset: bytes}, CategoryTable or None)``: the same-size writes that
    make setting *key* (values 1..*values*, its help naming *names*), and the category table to
    give one more record (:func:`table_writes`) - ``None`` when a previous Write already did. Raises
    :class:`MenuSettingError` when this program cannot take it (the reason is the message).
    PAD-537: *ad* is the adjustment to take over (a picture setting's, :func:`plan_many` picks
    one), *default* the value a fresh store starts at, *help_text* a help line of the setting's
    own in place of the names."""
    from . import menu_visibility as MV
    if key not in SETTINGS:
        raise MenuSettingError("no such setting: %s" % key)
    fixed, caption, row_caption, category = SETTINGS[key]
    ad = ad or fixed
    if ad is None:
        raise MenuSettingError("the game has no spare setting left for %s" % caption)
    values = int(values)
    ceiling = MAX_VALUES if help_text is None else VALUES_CEILING
    if not 2 <= values <= ceiling:
        raise MenuSettingError("a setting of ours offers 2 to %d values, not %d" % (ceiling, values))
    if not 1 <= int(default) <= values:
        raise MenuSettingError("a default of %s is not one of the values 1 to %d" % (default, values))
    if ad not in table.by_name:
        raise MenuSettingError("the game has no %s to take over" % ad)
    i = table.by_name[ad]
    desc = table._off(table.table_va + i * table.elem)
    label = menu_label(table, i)
    # a previous Write's caption of ours (PAD-537: a spare one may have held another of ours)
    ours = label in {v[1] for v in SETTINGS.values()}
    if not ours and not label.upper().startswith(DEPRECATED):
        raise MenuSettingError("the game's %s is \"%s\", not a setting it says it no longer uses"
                               % (ad, label))
    reading = MV.MenuVisibility(table)
    reading._scan()
    consts = reading._consts
    data = table.data
    live = struct.unpack_from("<I", data, desc)[0]
    if _refs(data, live, consts) != 1:
        raise MenuSettingError("the game's program reads %s's value directly" % ad)
    cat = menu_table(table)
    if cat is None:
        raise MenuSettingError("the game's operator menu pages could not be read")
    if not ours and cat.lists(i):
        raise MenuSettingError("the game's menu already lists %s" % ad)
    row = _row_caption_line(table, i)
    if row is None:
        raise MenuSettingError("the game's menu captions could not be read")
    cap_va = struct.unpack_from("<I", data, desc + OFF_MENU_LABEL)[0]
    help_va = struct.unpack_from("<I", data, desc + OFF_MENU_HELP)[0]
    for what, va in (("caption", cap_va), ("help line", help_va)):
        if table._off(va) is None or _refs(data, va, consts) != 1:
            raise MenuSettingError("%s's %s is shared with other settings" % (ad, what))
    row_va = table._va(row[0])
    if _refs(data, row_va, consts) != 5:
        raise MenuSettingError("%s's row caption is shared with other text" % ad)
    cap_room, help_room = _room(table, cap_va, consts), _room(table, help_va, consts)
    row_room = _room(table, row_va, consts)
    if cap_room < len(caption) or row_room < len(row_caption):
        raise MenuSettingError("%s's caption has no room for \"%s\"" % (ad, row_caption))
    if help_room < 12:
        raise MenuSettingError("%s's help line has no room to name the modes" % ad)
    if help_text is not None:
        text = " ".join(str(help_text).split())[:help_room].rstrip()
    else:
        text = help_line(list(names)[:values] + ["Mode %d" % (k + 1) for k in range(len(names), values)],
                         help_room)
    writes = {
        table._off(cap_va): caption.encode("ascii") + b"\x00" * (cap_room + 1 - len(caption)),
        row[0]: row_caption.encode("ascii") + b"\x00" * (row_room + 1 - len(row_caption)),
        table._off(help_va): text.encode("ascii", "replace") + b"\x00" * (help_room + 1 - len(text)),
    }
    for off, v in ((OFF_DEFAULT, int(default)), (OFF_MIN, 1), (OFF_MAX, values), (OFF_STEP, 1)):
        writes[desc + off] = struct.pack("<i", v)
    setting = MenuSetting(key, i, row_caption, text, values, live, category, int(default), cat.where(category))
    return setting, writes, (None if cat.has(category, i) else cat)


def plan_many(table, wanted):
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
            others = {v[1] for k, v in SETTINGS.items() if k != key}
            free = mine + [n for n in free if menu_label(table, table.by_name[n]) not in others
                           and n not in mine]
            if not free:
                refused[key] = ("the game has no spare setting left for %s (the card's other menu "
                                "settings of ours use them)" % caption)
                continue
            ad = free[0]
        try:
            setting, w, c = plan(table, key, values, names, ad=ad, **opts)
        except MenuSettingError as e:
            refused[key] = str(e)
            continue
        taken.add(setting.id)
        settings.append(setting)
        writes.update(w)
        if c is not None:
            cat = c
    order = [r[0] for r in rows]
    settings.sort(key=lambda st: order.index(st.key))
    return settings, writes, cat, refused


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
        t = AdjustmentTable(raw)
        e = t.entry(setting.id)
        desc = t._off(t.table_va + setting.id * t.elem)
        got_help = t._cstr(struct.unpack_from("<I", raw, desc + OFF_MENU_HELP)[0], 200)
        cat = menu_table(t)
        row = _row_caption_line(t, setting.id)
    except Exception as ex:                                   # noqa: BLE001
        return ["the program does not read back (%s)" % ex]
    if (e["default"], e["min"], e["max"], e["step"]) != (setting.default, 1, setting.values, 1):
        bad.append("its range reads %d..%d" % (e["min"], e["max"]))
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
        plan(AdjustmentTable(elf_bytes), key, 2)
    except MenuSettingError as e:
        return str(e)
    except ValueError as e:
        return "the game's settings could not be read (%s)" % e
    return ""
