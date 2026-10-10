"""PAD-494 (a tester's request): MUSIC MODE, a setting of the app's own in the operator menu.

menu_settings takes over a DEPRECATED adjustment the game never reads, names the modes in its
help line and adds it to the Audio Content page (one more record in the menu manager's category
table, moved to the game program's extension segment). The emulator showed the result on
Godzilla Premium/LE 1.16 (Music Mode first on Audio Content, editable 1..3, the pick kept in the
NVM mirror under SHA1("MUSIC MODE")); these tests pin the reading and the patch on the real
Godzilla 1.16 programs where the cards are on this machine (skipped elsewhere, as on CI)."""

import os
import struct

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, menu_label

CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
PRO116 = os.path.join(CARDS, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
NAMES = ["Standard", "Orchestral", "Heisei"]


# ---- the help line ---------------------------------------------------------------------------
def test_the_help_line_names_each_mode_by_its_number():
    assert MS.help_line(NAMES, 79) == "1 = Standard, 2 = Orchestral, 3 = Heisei"


def test_a_help_line_with_no_room_drops_the_equals_signs_then_cuts_the_names():
    assert MS.help_line(NAMES, 34) == "1 Standard, 2 Orchestral, 3 Heisei"
    short = MS.help_line(["Standard Edition", "Orchestral Edition"], 20)
    assert len(short) <= 20 and short.startswith("1 ") and " 2 " in short


def test_a_cut_help_line_keeps_what_tells_the_names_apart():
    """Eight modes in the 71 characters Godzilla 1.16's help line has: a word several names share
    is cut first, so "Custom A" and "Custom B" stay told apart; short names stay whole."""
    custom = ["Standard"] + ["Custom %s" % c for c in "ABCDEFG"]
    assert MS.help_line(custom, 71) == \
        "1 Standa 2 Cust A 3 Cust B 4 Cust C 5 Cust D 6 Cust E 7 Cust F 8 Cust G"
    assert MS.help_line(custom[:5], 71) == \
        "1 = Standard, 2 = Custom A, 3 = Custom B, 4 = Custom C, 5 = Custom D"
    eras = ["Standard", "Orchestral", "Heisei", "Showa", "Millennium", "Monsterverse", "Reiwa", "Shin"]
    assert MS.help_line(eras, 71) == \
        "1 Standar 2 Orchest 3 Heisei 4 Showa 5 Millenn 6 Monster 7 Reiwa 8 Shin"
    assert MS.help_line(["Standard Edition", "Orchestral Edition"], 20) == "1 Standar 2 Orchest"


def test_a_mode_without_a_name_is_called_by_its_number():
    assert MS.help_line(["", "  Orchestral  "], 79) == "1 = Mode 1, 2 = Orchestral"


# ---- the real game programs (David's machine) ------------------------------------------------
def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


def _built(raw, tmp, values=3, names=NAMES):
    """*raw* with the setting in it, the way a Write puts it: the same-size writes, the table in
    the extension segment the engine's own growth makes."""
    from pinball_decryptor.plugins.stern import engine as E
    t = AdjustmentTable(raw)
    setting, writes, cat = MS.plan(t, MS.MUSIC_MODE, values, names)
    reloc, why = E._text_reloc_plan(raw)
    assert reloc, why
    va = reloc["base_va"] + reloc["used"]
    fw = list(writes.items()) + list(MS.table_writes(t, cat, va, len(cat.records) + 1).items())
    grown = E._grow_program_text(raw, fw, MS.table_blob(cat, setting), reloc, None, str(tmp), None,
                                 lambda *a, **k: None)
    with open(grown["path"], "rb") as f:
        return f.read(), setting, cat


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_godzilla_116_gives_up_its_deprecated_gi_max_brightness(card):
    raw = _program(card)
    assert MS.offered(raw) == ""
    t = AdjustmentTable(raw)
    setting, writes, cat = MS.plan(t, MS.MUSIC_MODE, 3, NAMES)
    assert setting.id == 31 and setting.category == 13
    assert menu_label(t, 31).startswith("DEPRECATED")
    # its value is read nowhere but through its descriptor
    assert raw.count(struct.pack("<I", setting.live)) == 1
    # the menu manager's table: 107 records, Audio Content holds no system setting yet
    assert len(cat.records) == 107 and not any(c == 13 for c, _k, _i in cat.records)
    assert (11, 3, 30) in cat.records                       # GI LED Brightness, LCD/Lamp
    assert all(len(b) for b in writes.values())


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_the_setting_reads_back_from_the_built_program(card, tmp_path):
    raw = _program(card)
    new, setting, _cat = _built(raw, tmp_path)
    assert MS.check(new, setting) == []
    t = AdjustmentTable(new)
    e = t.entry(31)
    assert (e["default"], e["min"], e["max"], e["step"]) == (1, 1, 3, 1)
    assert menu_label(t, 31) == "MUSIC MODE"
    assert setting.help == "1 = Standard, 2 = Orchestral, 3 = Heisei"
    # every other adjustment as it was
    old = AdjustmentTable(raw)
    for i in range(old.count):
        if i != 31:
            assert t.entry(i) == old.entry(i)


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_a_card_built_before_keeps_its_record_and_takes_new_names(card, tmp_path):
    raw = _program(card)
    new, _setting, _cat = _built(raw, tmp_path)
    setting, writes, cat = MS.plan(AdjustmentTable(new), MS.MUSIC_MODE, 2, ["Standard", "Orchestral"])
    assert cat is None                                      # the page already lists it
    assert setting.help == "1 = Standard, 2 = Orchestral"
    buf = bytearray(new)
    for o, b in writes.items():
        buf[o:o + len(b)] = b
    assert MS.check(bytes(buf), setting) == []


def test_a_setting_the_game_still_uses_is_refused():
    raw = _program(LE116)
    t = AdjustmentTable(raw)
    cap = struct.unpack_from("<I", raw, t._off(t.table_va + 31 * t.elem) + 0x18)[0]
    buf = bytearray(raw)
    o = t._off(cap)
    buf[o:o + 18] = b"GI LED MAX POWER\x00\x00"
    with pytest.raises(MS.MenuSettingError, match="no longer uses"):
        MS.plan(AdjustmentTable(bytes(buf)), MS.MUSIC_MODE, 3, NAMES)


def test_the_table_cannot_grow_past_what_its_end_instruction_holds():
    raw = _program(LE116)
    t = AdjustmentTable(raw)
    _s, _w, cat = MS.plan(t, MS.MUSIC_MODE, 3, NAMES)
    with pytest.raises(MS.MenuSettingError, match="cannot grow"):
        MS.table_writes(t, cat, 0x700000, 200)
    writes = MS.table_writes(t, cat, 0x700000, 108)
    assert struct.unpack_from("<I", writes[cat.literal_off])[0] == 0x700000
    for o in cat.size_offs:
        w = struct.unpack_from("<I", writes[o])[0]
        assert (((w >> 4) & 0xF000) | (w & 0xFFF)) == 108 * 12
