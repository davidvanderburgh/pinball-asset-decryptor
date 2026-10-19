"""PAD-634: Played in on the plain-C titles and Deadpool, read source file by source file
(:mod:`.clip_files`): a file is a mode's when only that mode's records are written in it (its
audits counted, its game flags set or cleared) or, on Deadpool, when the mode's display-effect
getters point into it. Checked on synthetic programs, and on the real programs where the cards
are on this machine (skipped elsewhere, as on CI)."""

import os
import struct

import pytest

from pinball_decryptor.plugins.stern import clip_files as CF
from pinball_decryptor.plugins.stern import clip_modes as CM

CARDS = os.environ.get("PAD444_CARDS", r"D:\Pinball\images\Stern\spike2")
AEROSMITH = os.path.join(CARDS, "aerosmith-1_16_0.Release.8G.sdcard.raw")
STRANGER = os.path.join(CARDS, "stranger_things_le-1_13_0.Release.8G.sdcard.raw")
METALLICA = os.path.join(CARDS, "metallica_spike-1_04_0.Release.32G.sdcard.raw")
DEADPOOL = os.path.join(CARDS, "deadpool_le-1_16_0.Release.8G.sdcard.raw")

# Stranger Things LE 1.13's flag clear (0x4836a0), set (0x4836e8) and test (0x483780), and a
# callee handed flag-sized ids that stores into a table (0x4296cc)
CLEAR = (0xe3500000, 0x0a00000d, 0xe3043484, 0xe340305c, 0xe5933000, 0xe1500003, 0x2a000008,
         0xe3042c5c, 0xe2003007, 0xe3402089, 0xe3a0c001, 0xe5921004, 0xe7d121c0, 0xe1c2331c,
         0xe7c131c0, 0xe12fff1e)
SET = CLEAR[:13] + (0xe182331c,) + CLEAR[14:]
TEST = (0xe2502000, 0xe92d4008, 0x0a00000c, 0xe3043484, 0xe340305c, 0xe5933000, 0xe1520003,
        0x2a000007, 0xe3043c5c, 0xe2020007, 0xe3403089, 0xe5933004, 0xe7d331c2, 0xe1a00053,
        0xe2000001, 0xe8bd8008)
STORE = (0xe305cd40, 0xe340c05c, 0xe59cc000, 0xe150000c, 0x2a00000a, 0xe307cf70, 0xe52de004,
         0xe340c07d, 0xe08ce200, 0xe79cc200, 0xe59e0004, 0xe58c1000, 0xe5802000, 0xe59e2008,
         0xe5823000, 0xe49df004)


class _Words:
    def __init__(self, at, words):
        self.at, self.b = at, struct.pack("<%dI" % len(words), *words)

    def word(self, va):
        o = va - self.at
        return struct.unpack_from("<I", self.b, o)[0] if 0 <= o <= len(self.b) - 4 else None


# ---- whose code a function is ----------------------------------------------------------------
@pytest.mark.parametrize("words, kind", [(SET, "set"), (CLEAR, "clear"), (TEST, None),
                                         (STORE, None)])
def test_a_flag_writer_is_told_by_its_bit_operation(words, kind):
    assert CF.bit_writer(_Words(0x1000, words), 0x1000) == kind


def test_the_scan_stops_at_the_function_end_and_does_not_read_the_next_one():
    # a table store right before a flag set: its bytes are not the store's
    prog = _Words(0x1000, STORE + SET)
    assert CF.bit_writer(prog, 0x1000) is None
    assert CF.bit_writer(prog, 0x1000 + 4 * len(STORE)) == "set"


class _Prog:
    """func_start = the VA rounded down to 0x100; ``references`` from a dict."""

    def __init__(self, refs=None):
        self.refs = refs or {}

    def func_start(self, va):
        return va & ~0xFF

    def references(self, va):
        return self.refs.get(va, [])


def test_a_file_is_a_modes_when_only_that_modes_records_are_written_in_it():
    prog = _Prog()
    graph = CF._Graph(prog, [0x2000, 0x4000, 0x6000])
    files = CF._files_of(graph, {0x1100: {"TOYS"}, 0x1300: {"TOYS"},       # file 0x2000: TOYS
                                 0x2100: {"TOYS"}, 0x3100: {"LOVE"},       # file 0x4000: both
                                 0x4100: {"TOYS", "LOVE"}})                # names two: no file
    fo = CF.FileOwners(prog, graph, files)
    assert fo.of_code(0x1880) == ("TOYS", "file")
    assert fo.of_code(0x2000) == ("TOYS", "file")        # the initialiser ends its own file
    assert fo.of_code(0x3880) == ("", "")
    assert fo.of_code(0x5880) == ("", "")
    assert fo.of_code(0x7000) == ("", "")                # past the last initialiser


def test_a_table_is_a_modes_when_only_its_files_load_it(monkeypatch):
    prog = _Prog({0x9000: [0x1180], 0x9100: [0x1180, 0x3180]})
    graph = CF._Graph(prog, [0x2000, 0x4000])
    fo = CF.FileOwners(prog, graph, {0x2000: {"TOYS"}})
    monkeypatch.setattr(fo, "loaded", lambda: {0x9000, 0x9100})
    assert fo.of_table(0x9008) == ("TOYS", "table")      # walked back to 0x9000
    assert fo.of_table(0x9104) == ("", "")               # a file no mode's loads it too


@pytest.mark.parametrize("key, label, slug", [
    ("SWEET_EMOTION", "Sweet Emotion", "sweet_emotion"),
    ("LOVE_IN_AN_ELEVATOR_MULTIBALL", "Love in an Elevator Multiball",
     "love_in_an_elevator_multiball"),
    ("ENTER_SANDMAN_MODE", "Enter Sandman Mode", "enter_sandman_mode"),
])
def test_a_plain_c_mode_is_named_as_the_modes_tab_names_it(key, label, slug):
    assert CF.is_c_key(key)
    assert CM.mode_label(key) == label
    assert CM.mode_slug(key) == slug
    # a copy for it is named and known again like any mode's
    name = CM.own_name("Clip_A", key)
    assert name == "Clip_A_" + slug
    assert CM.copy_of(name, {"Clip_A"}, {key: label}) == ("Clip_A", key)


def test_class_names_are_not_plain_c_keys():
    for cls in ("cmode_battle_vs_gigan", "cberserker_rage", "Mode_Stopping_A_Juggernaut"):
        assert not CF.is_c_key(cls)


# ---- the real programs ---------------------------------------------------------------------------
def _program(card):
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


@pytest.mark.skipif(not os.path.isfile(AEROSMITH), reason="the Aerosmith Pro 1.16 card is not here")
def test_aerosmith_names_its_multiballs_and_leaves_the_toy_box_rule_alone():
    r = CM.analyse(_program(AEROSMITH), {"LoveInAnElevator_LadyEnters_1", "ToysInTheAttic_Intro",
                                         "SupersStart_Lanes", "Kick_Hey1", "Jacky_BallSave"})
    assert r.modes_of("LoveInAnElevator_LadyEnters_1") == ["LOVE_IN_AN_ELEVATOR_MULTIBALL"]
    assert r.label("LOVE_IN_AN_ELEVATOR_MULTIBALL") == "Love in an Elevator Multiball"
    assert r.modes_of("ToysInTheAttic_Intro") == ["TOYS_IN_THE_ATTIC_MULTIBALL"]
    assert r.modes_of("SupersStart_Lanes") == ["SUPER_LANES"]
    # the toy box kicks play in any mode (their file counts no mode's records), and so does a
    # ball save
    assert r.modes_of("Kick_Hey1") == [] and r.elsewhere("Kick_Hey1")
    assert r.modes_of("Jacky_BallSave") == []


@pytest.mark.skipif(not os.path.isfile(STRANGER), reason="the Stranger Things LE 1.13 card is not here")
def test_stranger_things_names_its_modes_by_their_records():
    r = CM.analyse(_program(STRANGER), {"ST_BustOutModeStart_LCD_PRO", "ST_JunkYardModeTotal_LCD_PRO",
                                        "ST_WheresBarbIntro_LCD_PRO", "ST_Match_00"})
    assert [r.label(m) for m in r.modes_of("ST_BustOutModeStart_LCD_PRO")] == ["Bust Out"]
    assert [r.label(m) for m in r.modes_of("ST_JunkYardModeTotal_LCD_PRO")] == ["Junk Yard"]
    assert [r.label(m) for m in r.modes_of("ST_WheresBarbIntro_LCD_PRO")] == ["Wheres Barb"]
    assert r.modes_of("ST_Match_00") == []


@pytest.mark.skipif(not os.path.isfile(METALLICA), reason="the Metallica 1.04 card is not here")
def test_metallica_reads_its_audits_from_the_record_that_maps_them():
    from pinball_decryptor.plugins.stern import stock_scan as S
    from pinball_decryptor.plugins.stern import stock_scan_c as SC
    elf = _program(METALLICA)
    _names, ids, rec = SC.audit_ids(S.Program(elf))
    # an 8-byte record of the same count comes first; the 28-byte one maps the names
    assert rec[2] == 28
    assert ids[284] == "AUD_ENTER_SANDMAN_MODE_STARTED"
    r = CM.analyse(elf, {"EnterSandman_Start", "BatteryMode.Battery_HitAward1",
                         "FadeToBlack_ShotAward1"})
    assert r.modes_of("EnterSandman_Start") == ["ENTER_SANDMAN_MODE"]
    assert r.modes_of("BatteryMode.Battery_HitAward1") == ["BATTERY_MODE"]
    assert r.modes_of("FadeToBlack_ShotAward1") == ["FADE_TO_BLACK_MODE"]


@pytest.mark.skipif(not os.path.isfile(DEADPOOL), reason="the Deadpool LE 1.16 card is not here")
def test_deadpool_names_the_modes_whose_display_effects_play_its_clips():
    from pinball_decryptor.plugins.stern import stock_scan as S
    elf = _program(DEADPOOL)
    prog = S.Program(elf)
    # the framework's intro / total effect slots, read off the framework itself
    assert {42, 43, 44} <= set(CF.effect_slots(prog))
    base, count = CF.effect_table(prog)
    assert count == 173
    r = CM.analyse(elf, {"JuggernautModeTotal", "Deadpool_Juggernaut_Uppercut", "MystiqueModeTotal",
                         "NinjaMBSuperJackpot", "TRexQuest_ModeTotal", "LilDeadpool_BallSaved"})
    assert r.modes_of("JuggernautModeTotal") == ["cbattle_juggernaut"]
    assert r.modes_of("Deadpool_Juggernaut_Uppercut") == ["cbattle_juggernaut"]
    assert r.label("cbattle_juggernaut") == "Battle Juggernaut"
    assert r.modes_of("MystiqueModeTotal") == ["cbattle_mystique"]
    assert r.modes_of("NinjaMBSuperJackpot") == ["cninja_mball"]
    assert r.modes_of("TRexQuest_ModeTotal") == ["cquest_trex"]
    assert r.modes_of("LilDeadpool_BallSaved") == []
