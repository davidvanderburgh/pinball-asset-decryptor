"""PAD-1064: How it works on the page of each of the game's own modes - what starts it, its clips, the sounds its
own code asks for - read off the game program, read-only."""
import json
import os

import pytest

from pinball_decryptor.plugins.stern import clip_modes as CM
from pinball_decryptor.plugins.stern import clip_sounds as CS
from pinball_decryptor.plugins.stern import stock_modes as SM
from pinball_decryptor.webui import modes_how as MH

TABLE = """
build godzilla_pro 1.16 sha1 0000000000000000000000000000000000000000
mode 1 cmode_godzilla_multiball obj 0x7a18a8 vtable 0x629b98 title_msg 3235
start 1 start: cmode_manager_get(1) at 0x12ee2c then v[8], in RuleBuildingLocks::v[25]
mode 3 cmode_bridge_attack_multiball obj 0x7a1a08 vtable 0x6295d8 title_msg 3239
start 3 start: cmode_manager_get(3) at 0x130cb4 then v[8], in fn 0x130c30
mode 11 cmode_monster_island_madness obj 0x7a1a28 vtable 0x6295e8 title_msg 3240
start 11 start: the mode getter(11) at 0xc55ac then v[8], in cmode_king_of_the_monsters_multiball::v[42]
start 11 stop: cmode_manager_get(11) at 0xc5000 then v[11], in RuleOther::v[3]
mode 10 cmode_king_of_the_monsters_multiball obj 0x7a1a48 vtable 0x6295f8 title_msg 3241
mode 6 cmode_battle_vs_king_ghidorah obj 0x7a1a68 vtable 0x629608 title_msg 3242
start 6 select: slot 5 of the 7-entry selector table 0x64272c {slot, mode id, 0} (12 13 14 15 16 6 17)
start 6 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730)
"""


def _build():
    return SM.parse(TABLE)[0]


def test_what_starts_a_mode_is_said_in_words():
    b = _build()
    assert MH.start_words(b, b.modes[1]) == [
        "Started by the game's Building Locks rule (the code that counts its shots)."]
    # a start in a plain function names nothing a person can use
    assert MH.start_words(b, b.modes[3]) == []
    # another mode starts it (the table's own name for that mode); a stop line is not a start
    assert MH.start_words(b, b.modes[11]) == [
        "Started by the game's own King of the Monsters Multiball mode, while it runs."]
    # a select line and its screen are one sentence
    assert MH.start_words(b, b.modes[6]) == [
        "Picked by the player on one of the game's selection screens."]


def test_each_sound_call_goes_to_the_mode_whose_code_it_is_in():
    class Owners:
        def of_code(self, va):
            return ("cmode_a", "own") if va < 0x100 else ("cmode_b", "unit") if va < 0x200 else ("", "")
    calls = [CS.Call(0x10, 0x0, 7, "callout"), CS.Call(0x20, 0x0, 3, "sound_play"),
             CS.Call(0x30, 0x0, 7, "callout"), CS.Call(0x150, 0x100, 9, "sound_play"),
             CS.Call(0x250, 0x200, 4, "sound_play")]                 # main play's: no mode's
    assert CS.mode_calls(calls, Owners()) == {"cmode_a": [[7, 0x10, 2], [3, 0x20, 1]],
                                               "cmode_b": [[9, 0x150, 1]]}


def test_a_reading_keeps_each_modes_sounds_in_its_cache():
    sr = CS.SoundReading(origin="port", count=3, modes={"cmode_a": [[7, 16, 2]]}, names={7: "SE VO GO"})
    clips = CM.CardClips(card="c", sounds=sr.to_json())
    back = CM.CardClips.from_json(json.loads(json.dumps(clips.to_json())))
    assert back.sound_reading.modes == {"cmode_a": [[7, 16, 2]]}
    # a reading cached before PAD-1064 has none, and is read again (its revision)
    assert CS.SoundReading.from_json({"pairs": {}}).modes == {}
    assert CS.READ_REV >= 6


class _Tab(MH.HowItWorksMixin):
    def __init__(self, project, clips):
        self._init_how()
        self._project = project
        self._how = clips
        self._how_key = ("p", "card", 1, 1)

    def project(self):
        return self._project


def test_the_page_lists_the_modes_clips_and_its_sounds_with_their_files(tmp_path):
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "idx0042 - SE GZ VO TANK START.wav").write_bytes(b"")
    CS.write_requests(str(tmp_path / CS.REQUESTS_TSV), [[], [5], [6]], {1: [42]}, {1: "SE GZ VO TANK START"})
    reading = CM.Reading(labels={"cmode_godzilla_multiball": "Godzilla Multiball"},
                         refs={"gz_mb_start": [CM.Ref("lone", [0], 0x100, "cmode_godzilla_multiball", "own")],
                               "attract": [CM.Ref("lone", [0], 0x200, "", "")]})
    sr = CS.SoundReading(origin="port", count=3, names={2: "SE GZ FX ROAR"},
                         modes={"cmode_godzilla_multiball": [[1, 0x110, 2], [2, 0x120, 1]]})
    clips = CM.CardClips(card="card", reading=reading, name_of={"video/gz_mb_start.mp4": "gz_mb_start"},
                         sounds=sr.to_json())
    tab = _Tab(str(tmp_path), clips)
    b = _build()
    how = tab._how_for(b, 1)
    assert how["starts"] == ["Started by the game's Building Locks rule (the code that counts its shots)."]
    assert [c["text"] for c in how["clips"]] == ["gz_mb_start"]
    assert how["clips"][0]["tip"]["lines"] == ["video/gz_mb_start.mp4"]
    first, second = how["sounds"]
    # the extract's file, played from the page; the Sound Test name and how often the code asks in its tooltip
    assert first["text"] == "idx0042 - SE GZ VO TANK START"
    assert first["path"] == os.path.join(str(tmp_path), "audio", "idx0042 - SE GZ VO TANK START.wav")
    assert first["tip"]["lines"] == ["Sound request 1", "Sound Test: SE GZ VO TANK START",
                                     "idx0042 - SE GZ VO TANK START.wav", "Asked for in 2 places of its code"]
    # no file for it in the project: its Sound Test name, nothing to play
    assert second["text"] == "SE GZ FX ROAR" and second["path"] == ""
    assert how["unread"] == "" and how["note"] == MH.HOW_NOTE
    # a mode the reading does not know: its start still, and why there is no list
    other = tab._how_for(b, 3)
    assert other["clips"] == [] and other["sounds"] == [] and "can't tell this mode's code apart" in other["unread"]


def test_while_the_card_is_read_the_page_says_so_and_without_a_card_says_why():
    tab = _Tab("p", None)
    b = _build()
    assert tab._how_for(b, 1)["unread"] == "Reading the card's clips and sounds..."
    tab._how_key = ("p", "", 0, 0)
    assert "not on this PC" in tab._how_for(b, 1)["unread"]
    assert tab._how_for(b, 1)["starts"]


def test_the_page_draws_how_it_works():
    js = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js",
                           "tabs", "modes.js"), encoding="utf-8").read()
    for bit in ("function HowSec", "<${HowSec} h=${g.how} />", "Sounds and callouts it plays", "What starts it",
                "Clips it plays", "<${PlayButton} path=${x.path} />"):
        assert bit in js, bit
    py = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "tabs",
                           "modes.py"), encoding="utf-8").read()
    assert '"how": self._how_for(build, mid)' in py and "self._how_kick()" in py


# ---- the real cards (David's machine) ----------------------------------------------------------
CARDS = os.environ.get("PAD444_CARDS", r"D:\Pinball\images\Stern\spike2")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")


def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern import video_bank as VB
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, version, part = card_title(card)
    with CardImage(card) as img:
        elf = img.preview(part, "/%s/game" % game, cap=256 << 20)
        bank = img.preview(part, "/%s/assets/lcd/auto_loaded/%s/scene.radium"
                           % (game, VB.GODZILLA_PRO_BANK), cap=64 << 20)
        fragments = CS.card_fragments(img, part, game)
    return elf, [c.name for c in VB.parse(bank).library.entries], fragments, game, version


@pytest.mark.slow
def test_a_real_godzilla_modes_sounds_are_the_ones_the_emulator_heard_it_play():
    """EMULATOR-PROVEN: PAD-455's census (artifacts/PAD-455/emulator, sound_play and callout hooked, every rule
    forced in turn) heard each of these from the listed call site with the listed request while that mode ran:
    40 of the 40 listed calls it heard played their request, 39 in their own mode (Planet X Hurry Up's in the
    Planet X Multiball that starts it)."""
    elf, names, fragments, game, version = _program(LE116)
    ctx = {}
    reading = CM.analyse(elf, names, ctx=ctx)
    sr = CS.analyse(elf, names, fragments, game=game, version=version, refs=reading.refs, ctx=ctx)
    got = {m: {r[0] for r in rows} for m, rows in sr.modes.items()}
    heard = {"cmode_tank_attack_multiball": {1057, 1064}, "cmode_bridge_attack_multiball": {791, 1105},
             "cmode_monster_zero": {871, 1034, 1035, 1036, 1043}, "cmode_o2_destroyer": {670, 1351},
             "cmode_godzilla_multiball": {264, 348, 429}, "cmode_saucer_attack_multiball": {512, 513, 800},
             "cmode_battle_vs_king_ghidorah": {1304}, "cmode_tesla_strike": {574}}
    for mode, reqs in heard.items():
        assert reqs <= got.get(mode, set()), (mode, sorted(reqs - got.get(mode, set())))
    assert len(sr.modes) >= 20
    assert sr.names[1057] == "SE GZ VO GAME TANK ATTACK START"


@pytest.mark.slow
def test_a_generated_table_names_the_rule_that_starts_a_mode_as_the_hand_table_does():
    """The C++ reader's start line now names the class whose virtual starts the mode; on Godzilla LE 1.16 its
    words are the hand table's (RuleBuildingLocks, RuleMechagodzillaShield, RuleSaucerAttack - past the
    function that starts every mode - RuleKingOfTheMonsters)."""
    elf = _program(LE116)[0]
    from pinball_decryptor.plugins.stern import stock_scan as S
    from pinball_decryptor.plugins.stern import stock_scan_cpp as C
    r = C.read(S.Program(elf))
    starts = {m.id: f for m in r.modes for f in m.facts if f.startswith("start start:")}
    assert starts[1].endswith(", in RuleBuildingLocks::v[25]")
    assert starts[2].endswith(", in RuleMechagodzillaShield::v[25]")
    assert starts[5].endswith(", in RuleSaucerAttack::v[25]")
    assert starts[9].endswith(", in RuleKingOfTheMonsters::v[25]")
    assert starts[12].endswith(", in cmode_king_of_the_monsters::v[8]")
