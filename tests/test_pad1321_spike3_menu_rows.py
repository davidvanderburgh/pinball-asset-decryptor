"""PAD-1321: a Spike 3 (64-bit ARM) game program's operator-menu rows.

The menu-settings reader (:mod:`.adjustments`, :mod:`.menu_settings`) was built for Spike 2's
32-bit game program and refused a 64-bit one, so no operator-menu row (MUSIC MODE, EDITION,
CO-OP PLAY, HANDICAP) could be planned on a Spike 3 card. ``AdjustmentTable(raw, wide_ok=True)``
now reads the 64-bit table (8-byte pointers, a 64-byte descriptor, the menu's category records
found through the program's ``adrp``/``add`` pairs), and :func:`menu_settings.plan` returns the
same-size writes for a row. Growing the menu's page list (so a new row actually shows) is a
separate 64-bit program-growth ticket; until it lands :func:`menu_settings.offered` says so, and a
planned row reads back right in every field but "no menu page lists it".

The real proof is the Spike 3 library cards: their game programs, read off the card and planned
against. The tests that need a card skip when the library is not on this machine.
"""
import os

import pytest

from pinball_decryptor.plugins.stern import menu_settings as M
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, is_wide, menu_label

#: the Spike 3 cards in the image library, newest build of each (docs/plans/spike3_modes.md)
LIBRARY = r"D:\Pinball\images\Stern\spike3"
CARDS = {
    "fallout_le": "fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw",
    "pokemon_le": "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw",
    "star_wars_2025_le": "star_wars_2025_le-0_96_0.Release.64G.sdcard-secure.raw",
    "star_wars_2025_pro": "star_wars_2025_pro-0_84_0.Release.64G.sdcard-secure.raw",
    "star_wars_elg": "star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw",
    "transformers_mtmte_le": "transformers_mtmte_le-0_96_0_spike3.Release.64G.sdcard-secure.raw",
    "walking_dead_remastered_le": "walking_dead_remastered_le-0_92_0.Release.64G.sdcard-secure.raw",
}
_CACHE = {}


def program(key):
    """The game program of library card *key*, read off its games partition, or a skip."""
    if key in _CACHE:
        return _CACHE[key]
    path = os.path.join(LIBRARY, CARDS[key])
    if not os.path.isfile(path):
        pytest.skip("no Spike 3 library card for %s (%s)" % (key, path))
    from pinball_decryptor.plugins.stern import title_reader as TR
    game, version, elf = TR.game_program(path)
    _CACHE[key] = (game, version, elf)
    return _CACHE[key]


# --- the card whose family census is the plan's: Star Wars ELG 1.10 ---

def test_elg_program_is_a_64bit_pie_the_old_reader_refuses():
    _g, _v, elf = program("star_wars_elg")
    assert is_wide(elf)
    with pytest.raises(ValueError):
        AdjustmentTable(elf)                      # a Spike 2 caller never accepts it


def test_elg_settings_table_reads_wide():
    _g, _v, elf = program("star_wars_elg")
    t = AdjustmentTable(elf, wide_ok=True)
    assert t.wide and t.ptr == 8 and t.elem == 64 and t.count == 195
    cm = t.get("AD_CUSTOM_MESSAGE")
    assert (cm["min"], cm["max"]) == (0, 1)       # the Off/On row the whole library carries
    assert t.sane()
    dep = sorted(i for n, i in t.by_name.items()
                 if menu_label(t, i).upper().startswith("DEPRECATED"))
    assert dep == [31, 33, 35]                    # GI / INSERT / FLASHER LED MAX BRIGHTNESS


def test_elg_takes_music_mode_edition_and_coop_rows():
    _g, _v, elf = program("star_wars_elg")
    t = AdjustmentTable(elf, wide_ok=True)
    wanted = [(M.MUSIC_MODE, 2, ["Standard", "Orchestral"]),
              (M.EDITION, 3, ["A", "B", "C"]),
              (M.COOP_PLAY, 2, [], {"onoff": True, "help_text": "Two players share a game"})]
    settings, writes, cat, refused = M.plan_many(t, wanted)
    assert refused == {}
    assert {s.key: s.id for s in settings} == {"music_mode": 31, "edition": 33, "coop_play": 35}
    # every descriptor/caption/help write is the same size as the bytes it replaces
    assert all(0 <= o < len(elf) for o in writes)
    buf = bytearray(elf)
    for o, b in writes.items():
        buf[o:o + len(b)] = b
    assert len(buf) == len(elf)
    co = next(s for s in settings if s.key == "coop_play")
    assert co.low == 0 and co.help == "Two players share a game"


def test_elg_grows_the_menu_so_the_row_is_listed():
    _g, _v, elf = program("star_wars_elg")
    assert M.offered(elf, M.MUSIC_MODE) == ""      # growable, so no longer refused
    t = AdjustmentTable(elf, wide_ok=True)
    s, writes, _c = M.plan(t, M.MUSIC_MODE, 2, names=["Standard", "Orchestral"])
    buf = bytearray(elf)
    for o, b in writes.items():
        buf[o:o + len(b)] = b
    t2 = AdjustmentTable(bytes(buf), wide_ok=True)
    cat = M.menu_table(t2)
    assert cat.lists(s.id) is False                 # id 31 is on no page as shipped
    grown = M.grow_wide_program(t2, cat, s)
    assert len(grown) > len(elf)                     # a read-only segment was appended
    t3 = AdjustmentTable(grown, wide_ok=True)
    cat3 = M.menu_table(t3)
    assert cat3.lists(s.id) and len(cat3.records) == len(cat.records) + 1
    assert M.check(grown, s) == []                   # descriptor, captions, help AND the page listing


def test_a_menu_copy_that_cannot_be_read_is_refused_not_mangled():
    # a table address the program never forms must raise, never silently mis-patch
    _g, _v, elf = program("star_wars_elg")
    t = AdjustmentTable(elf, wide_ok=True)
    real = M.menu_table(t)
    bogus = M.WideCategoryTable(real.va + 0x4000, real.records)   # a va no adrp/add forms
    with pytest.raises(M.MenuSettingError):
        M.wide_copy_sites(t, bogus)


# --- the same reader + grow over every Spike 3 library card ---

@pytest.mark.parametrize("key", sorted(CARDS))
def test_every_spike3_program_reads_and_either_takes_rows_or_says_why(key):
    _g, _v, elf = program(key)
    t = AdjustmentTable(elf, wide_ok=True)
    assert t.wide and t.elem == 64 and t.sane()
    cat = M.menu_table(t)
    assert isinstance(cat, M.WideCategoryTable) and 50 <= len(cat.records) <= 500
    # MUSIC MODE is taken and the menu grown when the program has a spare DEPRECATED setting whose
    # value nothing else reads AND a menu-copy we can read; else refused with a sentence; no crash
    settings, writes, _c, refused = M.plan_many(t, [(M.MUSIC_MODE, 2, ["A", "B"])])
    assert settings or refused
    if settings:
        s = settings[0]
        buf = bytearray(elf)
        for o, b in writes.items():
            buf[o:o + len(b)] = b
        assert len(buf) == len(elf)
        t2 = AdjustmentTable(bytes(buf), wide_ok=True)
        grown = M.grow_wide_program(t2, M.menu_table(t2), s)
        assert M.check(grown, s) == []
