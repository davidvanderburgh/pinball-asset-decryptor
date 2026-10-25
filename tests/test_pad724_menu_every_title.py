"""PAD-724: EDITION and MUSIC MODE on the latest build of every Spike 2 game.

Godzilla 1.16 alone had them (PAD-494/495). The 31 newest builds whose operator menu lists its pages
by a category table take the settings as Godzilla does; the other 21 (Aerosmith, Elvira 3, Foo
Fighters, Guardians, Led Zeppelin, Mandalorian, Munsters, Rush, Sword of Rage, TMNT, Venom) have the
older menu, Standard Adjustments and Feature Adjustments, and get them as the last rows of Standard
Adjustments (:class:`menu_settings.StandardList`). Music modes also need each game's sound
resolver: every newest port names it (``site sound_resolve``). All 50 were swept in the emulator
(docs/plans/pad-724-editions-music-modes-every-title.md); these tests pin the reading on the real
programs where the cards are on this machine (skipped elsewhere, as on CI) and the rest at the desk."""

import os
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import editions as Ed
from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, menu_label

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTS = os.path.join(HERE, "tools", "spike2_emu", "modes", "sdk", "ports")
CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
AERO = os.path.join(CARDS, "aerosmith-1_16_0.Release.8G.sdcard.raw")
BOND_LE = os.path.join(CARDS, "james_bond_le-1_06_0.Release.16G.sdcard.raw")
WANT = [(MS.MUSIC_MODE, 3, ["Standard", "Second", "Third"]), (MS.EDITION, 2, ["Standard", "Second"])]


# ---- the older menu's list, at the desk ------------------------------------------------------------
def _movw(rd, v):
    return 0xE3000000 | (rd << 12) | ((v & 0xF000) << 4) | (v & 0xFFF)


def _movt(rd, v):
    return 0xE3400000 | (rd << 12) | ((v & 0xF000) << 4) | (v & 0xFFF)


class _Table:
    def __init__(self, data):
        self.data = data


class _Setting:
    def __init__(self, ident, category):
        self.id, self.category = ident, category


def test_a_standard_list_grows_by_our_ids_and_its_getter_is_pointed_at_the_copy():
    getter = struct.pack("<3I", _movw(0, 0x1234), _movt(0, 0x0065), 0xE12FFF1E)
    sl = MS.StandardList(0x651234, (85, 76, 41), 0)
    blob = sl.blob(_Setting(31, 13), _Setting(33, 16), _Setting(76, 1))
    assert struct.unpack("<6H", blob[:12]) == (85, 76, 41, 31, 33, 0)    # ours last, one NUL
    assert len(blob) % 4 == 0
    w = sl.writes(_Table(getter), 0x7A1238)
    w0, w1 = struct.unpack("<2I", w[0])
    assert (w0, w1) == (_movw(0, 0x1238), _movt(0, 0x007A))
    assert sl.has(13, 41) and sl.lists(41) and not sl.lists(31)
    assert sl.where(13) == "Adjustments > Standard Adjustments, at the end"


def test_where_names_each_menu():
    assert MS.menu_path("aerosmith", MS.EDITION) == "Adjustments > Standard Adjustments, at the end"
    assert MS.menu_path("batman", MS.EDITION) == "Adjustments > Machine Settings > Attract Mode"
    assert MS.menu_path("batman", MS.MUSIC_MODE) == "Adjustments > Machine Settings > Audio Content"


# ---- which titles ----------------------------------------------------------------------------------
class _Prof:
    def __init__(self, key, label):
        self.game_dir, self.version = key.rsplit("-", 1)
        self.label = label


def test_every_proven_title_is_offered_and_the_three_without_room_say_why():
    assert len(MS.PROVEN) == 50 and not MS.PROVEN & MS.NO_ROOM
    assert Ed.PROVEN is MS.PROVEN and SMo.PROVEN is MS.PROVEN
    assert Ed.title_refusal(_Prof("aerosmith-1.16", "Aerosmith 1.16")) == ""
    for key in MS.NO_ROOM:
        why = Ed.title_refusal(_Prof(key, "X"))
        assert "no room to grow" in why
    assert "update the machine's code" in Ed.title_refusal(_Prof("aerosmith-1.15", "Aerosmith 1.15"))
    assert MS.STANDARD_MENU <= {k.rsplit("-", 1)[0] for k in MS.PROVEN}


def test_a_title_without_room_is_never_offered_even_with_the_sweep_switch(monkeypatch):
    monkeypatch.setenv(SMo.MODES_ANY_ENV, "1")
    assert "no room to grow" in Ed.title_refusal(_Prof("star_wars_le-1.31", "Star Wars Premium/LE 1.31"))
    assert "no room to grow" in SMo.title_refusal(_Prof("star_wars_le-1.31", "Star Wars Premium/LE 1.31"))


@pytest.mark.parametrize("key", sorted(MS.PROVEN))
def test_every_proven_port_names_its_games_sound_resolver(key):
    """get_asset_descriptor, found on each card by sfx_names._find_resolver (the candidate that
    hands back a magic-5 descriptor for 399 of the first 400 sound ids), every one beginning
    ``push {r4-r8, lr}; mov r5, r0, lsl #16``."""
    text = open(os.path.join(PORTS, key + ".port"), encoding="utf-8").read()
    m = re.search(r"^site sound_resolve\s+(0x[0-9a-f]+) (0x[0-9a-f]+) (0x[0-9a-f]+)$", text, re.M)
    assert m, key
    assert (m.group(2), m.group(3)) == ("0xe92d41f0", "0xe1a05820")


# ---- the real programs (David's machine) -----------------------------------------------------------
def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


def test_aerosmith_lists_its_adjustments_by_the_standard_list_and_takes_both_settings(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    raw = _program(AERO)
    t = AdjustmentTable(raw)
    assert MS.category_table(t) is None
    cat = MS.menu_table(t)
    assert isinstance(cat, MS.StandardList) and len(cat.ids) == 95
    assert menu_label(t, cat.ids[-1]) == "SERVICE MENU B.BOX BRIGHTNESS"
    settings, writes, cat, refused = MS.plan_many(t, WANT)
    assert refused == {} and [s.key for s in settings] == [MS.MUSIC_MODE, MS.EDITION]
    assert {s.where for s in settings} == {"Adjustments > Standard Adjustments, at the end"}
    reloc, why = E._text_reloc_plan(raw)
    assert reloc, why
    va = reloc["base_va"] + reloc["used"]
    fw = list(writes.items()) + list(MS.table_writes(t, cat, va, *settings).items())
    grown = E._grow_program_text(raw, fw, MS.table_blob(cat, *settings), reloc, None, str(tmp_path), None,
                                 lambda *a, **k: None)
    new = open(grown["path"], "rb").read()
    assert [MS.check(new, s) for s in settings] == [[], []]
    assert Ed.in_program(new) == {"values": 2, "help": "1 = Standard, 2 = Second", "id": 33}
    again = MS.menu_table(AdjustmentTable(new))
    assert again.ids == cat.ids + (31, 33) and again.va == va
    # a second Write of the same project finds both listed and grows nothing
    _s, _w, cat2, refused2 = MS.plan_many(AdjustmentTable(new), WANT)
    assert cat2 is None and refused2 == {}


def test_bond_le_has_no_address_space_to_grow_into():
    from pinball_decryptor.plugins.stern import engine as E
    raw = _program(BOND_LE)
    reloc, why = E._text_reloc_plan(raw)
    assert reloc is None and "no free address space" in why
