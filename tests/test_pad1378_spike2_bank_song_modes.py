"""PAD-1378: music modes for the songs in a Spike 2 game's own sound banks.

Seven Spike 2 titles keep their licensed songs in ``image-scNN.bin`` banks (an extract decodes
them as ``music_catNN_NNNN.wav``), which the Audio tab refused mode files for. The game plays such a
song by a sound id of the bank's own, ``NN << 16 | n``, its request lists naming those as they name
any other, so a mode file for it goes into a sound bank of this app's (PAD-608's road): a fragment
for each of the game's bank sound ids that plays the song, each with the game's own descriptor for
that id rewritten so the file plays in place of the whole sound, and a ``bsid`` line per fragment.

Fast, no card and no firmware: the descriptors are Deadpool LE 1.16's own, read off its banks
through the game's resolver (bank 01's sound id 0x10000 plays record 1 looped; bank 07's 0x70001
plays record 1, then record 0 looped). The end to end proof (an override set of the stock card on
the rig, the files heard in the game's own capture) is the ticket's.
"""
import struct
from types import SimpleNamespace

from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import bank_songs as BS
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import media_share as MS
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB

#: Deadpool LE 1.16, bank 01, sound id 0x10000 (31 bytes its own): record 1, looped
DP_SONG = bytes.fromhex("050101c7d50b0001000002000b07000b000000d4eb405f8ae66cf711010300")
#: bank 07, sound id 0x70001 (45 bytes): record 1 (26.1 s) once, then record 0 (151.8 s) looped
DP_INTRO = bytes.fromhex("05010115dc0a000100000200000b000000a4f5431ec9460584110107000b000000"
                         "55d2c84383313d1611010300")
#: the next descriptor's bytes, which a read window runs on into
NEXT = bytes.fromhex("0501019945080001000002000107000b000000a4f5431ec986bf82110103")
KEY = bytes.fromhex("1122334455667788")
SONG = "audio/music_cat01_0001 - Deadpool Theme.wav"
INTRO = "audio/music_cat07_0000.wav"


def _plays(desc):
    return [b[4:12] for b in E._desc_ops(desc) if b[0] == 0x0b]


# --------------------------------------------------------------------------
# the Audio tab offers a bank song on Spike 2
# --------------------------------------------------------------------------
def test_a_spike2_bank_song_can_have_files_for_other_modes(monkeypatch):
    arm = SimpleNamespace(arch="arm", game_dir="deadpool_le", version="1.16", label="Deadpool LE 1.16")
    assert SMo.slot_ok(SONG, arm) and SMo.slot_ok("audio/idx0011.wav", arm)
    assert not SMo.slot_ok("audio/foo.wav", arm)
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=True: arm)
    monkeypatch.setattr(SMo, "title_refusal", lambda prof, turns=False: "")
    assert SMo.offer("proj", [SONG, "audio/foo.wav"]) == ("", {SONG: "", "audio/foo.wav": SMo.NOT_SOUND})


def test_a_bank_song_s_slot_number_is_never_an_idx():
    assert SMo.bank_slot_key(1, 1) == -65538 and SMo.bank_slot_key(0x37, 0) == -(0x370000 + 1)
    assert SMo.slot_key(SONG) == SMo.bank_slot_key(1, 1)
    assert SMo.slot_key("audio/idx2095 - Godzilla.wav") == 2095 and SMo.slot_key("audio/x.wav") is None


def test_the_card_record_brings_a_bank_song_s_files_back(tmp_path):
    proj = tmp_path / "proj"
    (proj / "audio").mkdir(parents=True)
    (proj / "audio" / "music_cat01_0001 - Deadpool Theme.wav").write_bytes(b"RIFF")
    (proj / "audio" / "idx0011.wav").write_bytes(b"RIFF")
    m = SMo.clean({"names": ["", "Custom A"], "slots": {SONG: {"2": "C:/x/Mine.wav"}}})
    used = [{"rel": SONG, "slot": SMo.bank_slot_key(1, 1), "mode": 2, "host": 900, "db": 0,
             "lines": 1, "bank": 60, "bank_idx": 0, "vbank": [1, 1]}]
    rec = SMo.read_card_record(SMo.cfg_text(0, 2, [], False, record=SMo.card_record(m, used)))
    assert rec["files"][0]["slot"] == SMo.bank_slot_key(1, 1) and rec["files"][0]["bank"] == 60
    assert MS._card_idx(str(proj)) == {11: "audio/idx0011.wav",
                                      SMo.bank_slot_key(1, 1): "audio/music_cat01_0001 - Deadpool Theme.wav"}


# --------------------------------------------------------------------------
# what each of the game's bank sound ids plays
# --------------------------------------------------------------------------
def test_a_play_names_its_record_by_the_first_four_bytes_of_its_key():
    # (the rest carries bits the game fills from the sound id's bank: bank 55's record 0 has the
    # same first word, read under another bank's id)
    assert BS.play_records(DP_SONG + NEXT, len(DP_SONG), {0x5f40ebd4: 1, 0x1e43f5a4: 0}) == [1]
    assert BS.play_records(DP_INTRO + NEXT, len(DP_INTRO), {0x1e43f5a4: 1, 0x43c8d255: 0}) == [1, 0]
    # a payload past the descriptor's own bytes is the next one's
    assert BS.play_records(DP_SONG + NEXT, None, {0x5f40ebd4: 1, 0x1e43f5a4: 0}) == [1, 0]


def test_a_bank_names_the_sound_ids_that_play_a_song():
    bk = BS.BankSongs(7, {0: {}, 1: {}, 2: {}}, {0x70000: (b"", 0, [2]), 0x70001: (b"", 0, [1, 0]),
                                                 0x70002: (b"", 0, [2])})
    assert bk.sids_of(0) == [0x70001] and bk.sids_of(2) == [0x70000, 0x70002] and bk.sids_of(5) == []


# --------------------------------------------------------------------------
# the file in place of the whole sound
# --------------------------------------------------------------------------
def test_a_looped_song_s_descriptor_loops_the_file():
    d = BS.mode_descriptor(DP_SONG + NEXT, len(DP_SONG), KEY, 4000 * 20)
    assert len(d) == SB.DESC_SLOT and d[len(DP_SONG):] == bytes(SB.DESC_SLOT - len(DP_SONG))
    assert _plays(d) == [KEY]
    assert struct.unpack_from("<I", d, 3)[0] == 4000 * 20
    # everything but the play's key and the length is the game's own script
    assert d[7:19] == DP_SONG[7:19] and d[27:31] == DP_SONG[27:31] == b"\x11\x01\x03\x00"


def test_an_intro_and_its_looped_song_both_play_the_file():
    # the song after the intro is in a loop of its own (after the 07 mark): the file plays once,
    # then loops, as the song did after its intro
    d = BS.mode_descriptor(DP_INTRO + NEXT, len(DP_INTRO), KEY, 4000 * 20)
    assert _plays(d) == [KEY, KEY]
    assert struct.unpack_from("<I", d, 3)[0] == 2 * 4000 * 20
    assert d[len(DP_INTRO):] == bytes(SB.DESC_SLOT - len(DP_INTRO))


def test_a_part_played_straight_after_the_first_is_dropped_with_its_wait():
    a, b = bytes(range(8)), bytes(range(8, 16))
    desc = (b"\x05\x01\x01" + struct.pack("<I", 4000 * 9) + b"\x01\x00\x00"
            + b"\x0b\x00\x00\x00" + a + b"\x11\x01" + b"\x0b\x00\x00\x00" + b + b"\x11\x01" + b"\x00")
    d = BS.mode_descriptor(desc, len(desc), KEY, 4000 * 5)
    assert _plays(d) == [KEY] and b not in d and a not in d
    assert d[7:] .startswith(b"\x01\x00\x00\x0b\x00\x00\x00" + KEY + b"\x11\x01\x00")
    assert struct.unpack_from("<I", d, 3)[0] == 4000 * 5
    # an op the engine does not know: none
    assert BS.mode_descriptor(desc[:7] + b"\x99" + desc[8:], len(desc), KEY, 1) is None


# --------------------------------------------------------------------------
# into a bank of ours, played by the game's bank sound ids
# --------------------------------------------------------------------------
def _banks():
    return {1: BS.BankSongs(1, {0: {"length": 44100 * 135}, 1: {"length": 44100 * 193}},
                            {0x10000: (DP_SONG, 31, [1]), 0x10001: (b"", 0, [0]),
                             0x10002: (DP_SONG, 31, [1])}),
            7: BS.BankSongs(7, {0: {"length": 44100 * 151}, 1: {"length": 44100 * 26},
                                2: {"length": 44100 * 181}},
                            {0x70000: (b"", 0, [2]), 0x70001: (DP_INTRO, 45, [1, 0])})}


def test_a_bank_song_s_file_takes_every_bank_sound_id_a_request_names(monkeypatch, tmp_path):
    (tmp_path / "game").write_bytes(b"\0" * 64)
    (tmp_path / "image.bin").write_bytes(b"\0" * 64)
    E._BANK_SONGS_ONCE[:] = [str(tmp_path / "game"), _banks()]
    import os
    E._BANK_SONGS_ONCE[0] = os.path.abspath(str(tmp_path / "game"))
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a, **k: 0xE0001FFF)
    # 0x10002 is in no request; 0x70001 in one
    monkeypatch.setattr(BB, "request_list_slots", lambda elf, head: {0x10000: [8], 0x70001: [12],
                                                                      0x10001: [16]})
    used = [{"rel": SONG, "slot": SMo.bank_slot_key(1, 1), "mode": 2, "host": 40, "vbank": [1, 1]},
            {"rel": INTRO, "slot": SMo.bank_slot_key(7, 0), "mode": 3, "host": 41, "vbank": [7, 0]},
            # bank 07's intro in the same mode: 0x70001 plays it and the longer song
            {"rel": "audio/music_cat07_0001.wav", "slot": SMo.bank_slot_key(7, 1), "mode": 3,
             "host": 42, "vbank": [7, 1]},
            # in another mode the intro has 0x70001 to itself
            {"rel": "audio/music_cat07_0001.wav", "slot": SMo.bank_slot_key(7, 1), "mode": 2,
             "host": 43, "vbank": [7, 1]},
            # record 2 of bank 07: 0x70000, in no request
            {"rel": "audio/music_cat07_0002.wav", "slot": SMo.bank_slot_key(7, 2), "mode": 2,
             "host": 44, "vbank": [7, 2]}]
    lines = []
    try:
        frags, stay, seqs = E._sound_modes_for_banks(
            str(tmp_path / "game"), str(tmp_path / "image.bin"), [], [], used, [], {},
            lambda m, *a: lines.append(m))
    finally:
        E._BANK_SONGS_ONCE[:] = [None, {}]
    assert {h: [(u["mode"], s) for u, s in f] for h, f in frags.items()} == {
        40: [(2, 0x10000)], 41: [(3, 0x70001)], 43: [(2, 0x70001)]}
    assert seqs == [] and {0x70000, 0x70001} <= stay
    text = "\n".join(lines)
    assert ("music_cat07_0001.wav's file for mode 3 (Custom B) is not put on this card: every sound id of "
            "the game's that plays it plays a longer song that has a file in this mode too") in text
    assert ("is not put on this card: no sound request of the game's plays song 2 of the game's "
            "sound bank image-sc07.bin") in text
    assert "stays in image.bin" not in text


def test_a_bank_song_s_file_that_is_in_no_bank_is_left_out_of_the_runtime_table(tmp_path):
    params = [{"idx": 40, "findkey": b"H" * 8, "grown": True}]
    m = SMo.clean({"names": ["", "Custom A"], "slots": {SONG: {"2": "C:/x/a.wav"}}})
    used = [{"rel": SONG, "slot": SMo.bank_slot_key(1, 1), "mode": 2, "host": 40, "vbank": [1, 1]}]
    logs = []
    E._sound_modes_cfg("gr", {}, params, {}, used, m, True, str(tmp_path),
                       lambda t, lvl="info": logs.append(t))
    assert used[0]["lines"] == 0
    assert any("could not go into a sound bank" in t for t in logs)


def test_the_bank_line_names_the_game_s_bank_sound_id():
    used = [{"rel": SONG, "slot": SMo.bank_slot_key(1, 1), "mode": 2, "bank": 60, "vbank": [1, 1],
             "bank_sids": {0x10000: 0x3C0000}}]
    bsids, tsids = E._bank_sid_lines([], used, {}, lambda *a: None)
    assert bsids == [(2, 0x10000, 0x3C0000)] and tsids == [] and used[0]["lines"] == 1
    assert "bsid\t2\t65536\t3932160" in SMo.cfg_text(0x7A4E78, 2, [], False, bsids=bsids)


def test_the_runtime_swaps_a_whole_32_bit_bank_sound_id():
    import os
    rt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "spike2_emu",
                      "modes", "sdk", "pad_mode_runtime.c")
    with open(rt, encoding="utf-8") as f:
        c = f.read()
    assert "unsigned id, bank;" in c                      # struct bsid: whole ids
    assert "hit = bsid[j].id == own[len];" in c           # the request's list, word for word


# --------------------------------------------------------------------------
# the file's loudness: the song's own, off the project's copy
# --------------------------------------------------------------------------
def test_a_bank_song_s_file_is_levelled_against_the_song_s_own_wav(monkeypatch):
    ref = E._LEVEL_WAV + r"C:\proj\audio\music_cat01_0001.wav"
    assert E._sm_level_refs([{"host": 40, "slot": -65538, "level_ref": ref},
                             {"host": 41, "slot": 7, "level_ref": 9}]) == {40: ref, 41: 9}
    assert E._wav_ref(ref) == r"C:\proj\audio\music_cat01_0001.wav" and E._wav_ref(9) is None
    seen = []
    monkeypatch.setattr(E, "_self_level_render", lambda path, p, np: seen.append(path) or "pcm")
    assert E._level_ref_render(None, {}, {"chan": 2}, ref, None) == "pcm"
    assert seen == [r"C:\proj\audio\music_cat01_0001.wav"]


def test_a_title_with_no_room_beside_its_own_banks_refuses_its_songs_up_front(monkeypatch):
    # Dungeons & Dragons 1.10: image.bin and its biggest music bank fill the machine's memory, so a
    # bank song's file would have no bank to play from (the Write leaves one out as well)
    dnd = SimpleNamespace(arch="arm", game_dir="dungeons_and_dragons_le", version="1.10",
                          label="Dungeons & Dragons LE 1.10")
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=True: dnd)
    monkeypatch.setattr(SMo, "title_refusal", lambda prof, turns=False: "")
    why, slots = SMo.offer("proj", [SONG, "audio/idx0011.wav"])
    assert why == "" and slots["audio/idx0011.wav"] == ""
    assert slots[SONG] == SMo.NO_BANK_ROOM % "Dungeons & Dragons LE 1.10"
    assert "dungeons_and_dragons_pro-1.10" in SMo.BANK_SONG_NO_ROOM
    rush = SimpleNamespace(arch="arm", game_dir="rush_le", version="1.19", label="Rush LE 1.19")
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=True: rush)
    assert SMo.offer("proj", [SONG])[1] == {SONG: ""}
