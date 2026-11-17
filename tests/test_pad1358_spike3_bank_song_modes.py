"""PAD-1358: music modes for a Spike 3 card's MUSIC-BANK songs (Fallout LE's 137 ``music_catNN_NNNN``).

A bank song is a record of its own ``image-scNN.bin`` (its params carry the bank's number in their low 12
bits), named by its key in that bank's own descriptor, and a request plays it as sound id ``NN << 16 | n``.
Its mode files are records appended to the same bank, keyed beside the song's, and the runtime swaps the
key at the same record lookup as an idx sound's (docs/plans/spike3_modes.md, "Bank songs").
"""
import struct
import wave

import pytest

from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern import spike3_music as S3MU
from pinball_decryptor.plugins.stern import spike3_write as W


class _Prof:
    def __init__(self, arch):
        self.arch, self.label, self.game_dir, self.version = arch, "Fallout", "fallout_le", "0.82"


# ---- which sounds ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("rel, want", [
    ("audio/music_cat02_0000.wav", (2, 0)),
    ("audio/music_cat41_0003 - Atom Bomb Baby.wav", (41, 3)),
    ("audio/02m21s867 - music_cat10_0001.wav", (10, 1)),
    ("audio/idx0011.wav", None),
    ("audio/notmusic_cat02_0000.wav", None),
])
def test_a_bank_songs_name_says_its_bank_and_record(rel, want):
    assert SMo.bank_slot(rel) == want


def test_a_bank_song_is_no_idx_sound():
    assert SMo.slot_idx("audio/music_cat02_0000.wav") is None


def test_a_bank_song_takes_mode_files_on_spike3_and_spike2():
    # (PAD-1378: on Spike 2 too, through a sound bank of the app's)
    assert SMo.slot_ok("audio/music_cat02_0000.wav", _Prof("a64"))
    assert SMo.slot_ok("audio/music_cat02_0000.wav", _Prof("arm"))
    assert SMo.slot_ok("audio/idx0011.wav", _Prof("arm"))
    assert not SMo.slot_ok("audio/foo.wav", _Prof("a64"))


def test_the_audio_tab_offers_a_bank_song_on_spike3_and_spike2(monkeypatch):
    rels = ["audio/music_cat02_0000.wav", "audio/idx0011.wav", "audio/foo.wav"]
    monkeypatch.setattr(SMo, "title_refusal", lambda prof, turns=False: "")
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: _Prof("a64"))
    why, slots = SMo.offer("p", rels)
    assert why == "" and slots == {rels[0]: "", rels[1]: "", rels[2]: SMo.NOT_SOUND}
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: _Prof("arm"))
    _why, slots = SMo.offer("p", rels)
    assert slots[rels[0]] == "" and slots[rels[1]] == ""


# ---- the key ---------------------------------------------------------------------------------------------------
class _Rec:
    def __init__(self, flags_lo, param, param2=0, channels=2, index=0):
        self.flags_lo, self.param, self.param2, self.channels, self.index = flags_lo, param, param2, channels, index


class _Img:
    def __init__(self, recs):
        self.records, self.count = recs, len(recs)


#: Fallout LE 0.82's banks 02 (one song) and 41 (four records), as read off the card
SC02 = [_Rec(0x20446, 0x82600008)]
SC41 = [_Rec(0x20048, 0x006000a4), _Rec(0x20446, 0x826000a4), _Rec(0x20044, 0xc01000a4), _Rec(0x20044, 0xc20000a4)]


def test_a_one_song_bank_gets_a_key_from_every_banks_bits_keeping_its_number():
    with pytest.raises(RuntimeError):                  # its own record varies no bit
        W.free_key(SC02, 0x20446, 0x82600008)
    flags, param = W.free_key(SC02, 0x20446, 0x82600008, like=SC02 + SC41, keep=S3MU.BANK_KEEP)
    assert flags == 0x20446 and param & 0xFFF == 0x008 and param != 0x82600008
    assert bin(param ^ 0x82600008).count("1") == 1      # the nearest the card's own keys allow


def test_a_bank_key_is_never_one_the_bank_or_the_build_has():
    taken = [(0x20446, 0x82600008 ^ (1 << b)) for b in range(20, 32)]
    flags, param = W.free_key(SC02, 0x20446, 0x82600008, taken=taken, like=SC02 + SC41, keep=S3MU.BANK_KEEP)
    assert (flags, param) not in taken + [(0x20446, 0x82600008)] and param & 0xFFF == 0x008


# ---- the records -----------------------------------------------------------------------------------------------
def _wav(path, secs=0.2, ch=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x01\x00" * ch * int(44100 * secs))
    return str(path)


def test_a_bank_songs_files_are_keyed_beside_it_in_its_bank(tmp_path, monkeypatch):
    a, b = _wav(tmp_path / "a.wav"), _wav(tmp_path / "b.wav")
    monkeypatch.setattr(SMo, "convert", lambda project, rel, m, src, log=None: src)
    modes = SMo.Modes(names=[], slots={"audio/music_cat41_0001 - Song.wav": {2: a, 3: b}})
    mswaps, news, used = S3MU.records(str(tmp_path), modes, _Img(SC41), bank=41, like=SC02 + SC41)
    stock = struct.pack("<II", 0x20446, 0x826000a4)
    assert [(m, s) for m, s, _o in mswaps] == [(2, stock), (3, stock)]
    assert len(news) == 2 and all(n.param & 0xFFF == 0x0a4 and n.flags_lo == 0x20446 for n in news)
    assert [(u["slot"], u["host"], u["bank"], u["bank_idx"]) for u in used] == [(1, 4, 41, 4), (1, 5, 41, 5)]
    # the record lines name the file by its bank and record, so they never read as an idx sound's
    rec = SMo.card_record(SMo.Modes(names=["S", "A", "B"], slots=modes.slots), used)
    assert any(l.split("\t")[3] == "41:4" for l in rec if l.startswith(SMo.REC_FILE + "\t"))


def test_a_song_of_another_bank_is_left_out_with_a_sentence(tmp_path, monkeypatch):
    a = _wav(tmp_path / "a.wav")
    monkeypatch.setattr(SMo, "convert", lambda project, rel, m, src, log=None: src)
    said = []
    modes = SMo.Modes(names=[], slots={"audio/music_cat02_0000.wav": {2: a}})
    mswaps, news, _u = S3MU.records(str(tmp_path), modes, _Img(SC41), bank=41, log=lambda m, k="info": said.append(m))
    assert not mswaps and not news and SMo.NOT_SOUND in said[0]


def _plan(tmp_path, monkeypatch, slots, conts):
    a = _wav(tmp_path / "a.wav")
    monkeypatch.setattr(SMo, "convert", lambda project, rel, m, src, log=None: src)
    monkeypatch.setattr(S3MU, "title_refusal", lambda prof, turns=False: "")
    monkeypatch.setattr(S3MU, "menu_program", lambda raw, modes, extra=(): (type("S", (), {"live": 0x10})(), b"prog"))
    imgs = {"game": _Img([_Rec(0x44000220, 0x02002060 ^ (1 << (20 + i))) for i in range(6)]),
            "sc02": _Img(SC02), "sc41": _Img(SC41)}
    monkeypatch.setattr(W, "project_sound_dirs", lambda reader: conts)
    monkeypatch.setattr(W, "read_container", lambda reader, node: (b"", imgs[node]))
    said = []
    mus = S3MU.plan(str(tmp_path), SMo.Modes(names=[], slots={r: {2: a} for r in slots}), object(), None, b"raw",
                    log=lambda m, k="info": said.append(m))
    return mus, said


CONTS = [("/fallout_le/image.bin", "game", "audio", None),
         ("/fallout_le/image-sc02.bin", "sc02", "audio", "music_cat02"),
         ("/fallout_le/image-sc41.bin", "sc41", "audio", "music_cat41")]


def test_each_bank_song_goes_into_its_own_bank_beside_the_idx_sounds(tmp_path, monkeypatch):
    mus, _said = _plan(tmp_path, monkeypatch, ["audio/idx0002.wav", "audio/music_cat02_0000.wav",
                                               "audio/music_cat41_0003 - X.wav"], CONTS)
    assert sorted(mus.news) == ["/fallout_le/image-sc02.bin", "/fallout_le/image-sc41.bin", "/fallout_le/image.bin"]
    assert mus.news["/fallout_le/image-sc02.bin"][0].param & 0xFFF == 0x008
    assert mus.news["/fallout_le/image-sc41.bin"][0].param & 0xFFF == 0x0a4
    swaps = {l.split("\t")[2] for l in mus.cfg.splitlines() if l.startswith("mswap")}
    assert struct.pack("<II", 0x20446, 0x82600008).hex() in swaps
    assert struct.pack("<II", 0x20044, 0xc20000a4).hex() in swaps


def test_a_song_of_a_bank_the_card_lacks_is_left_out_with_a_sentence(tmp_path, monkeypatch):
    mus, said = _plan(tmp_path, monkeypatch, ["audio/idx0002.wav", "audio/music_cat07_0000.wav"], CONTS)
    assert list(mus.news) == ["/fallout_le/image.bin"]
    assert any("music_cat07_0000.wav" in s and "image-sc07.bin" in s for s in said)


def test_a_card_of_banks_alone_has_no_sound_container(tmp_path, monkeypatch):
    with pytest.raises(S3MU.Spike3MusicError):
        _plan(tmp_path, monkeypatch, ["audio/music_cat02_0000.wav"], CONTS[1:])
