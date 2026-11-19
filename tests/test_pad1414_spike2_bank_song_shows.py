"""PAD-1414: a Spike 2 expression light show tied to a song of the game's own sound banks.

Rush, Foo Fighters, Metallica and four more keep their licensed songs in ``image-scNN.bin`` banks
(``music_catNN_NNNN``, PAD-1378). A show of the Lights page may now pick one, and the Write reads
the sound ids that start it (``NN << 16 | n``) through the game's own bank loader on the emulator,
as the music modes' files do (:func:`.bank_songs.read_banks`), a bank read once per build.

Fast, no card and no firmware: the banks are stand-ins. The end to end proof (an override set of
Rush LE 1.19 on the rig: the bank song's request starting the card's show) is the ticket's.
"""
import os
import types

from pinball_decryptor.plugins.stern import bank_songs as BS
from pinball_decryptor.plugins.stern import cab_shows as CS
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import sound_modes as SMo


def _bank(cat, plays):
    """A BankSongs whose sound ids play *plays* ``{sid: [record, ...]}``."""
    return BS.BankSongs(cat, {r: {"idx": r} for recs in plays.values() for r in recs if r is not None},
                        {sid: (b"\x05", 1, list(recs)) for sid, recs in plays.items()})


def test_a_bank_slot_key_gives_its_bank_and_record_back():
    for bank, rec in ((1, 0), (7, 1), (41, 65535)):
        assert SMo.bank_of_key(SMo.bank_slot_key(bank, rec)) == (bank, rec)
    assert SMo.bank_of_key(412) is None and SMo.bank_of_key(0) is None and SMo.bank_of_key(None) is None
    assert SMo.bank_of_key(True) is None


def test_a_show_of_a_bank_song_starts_with_the_ids_that_play_it_first():
    # Deadpool LE 1.16's bank 07: 0x70001 plays record 1 (the intro) then record 0 looped, 0x70000 record 0 alone
    bk = _bank(7, {0x70000: [0], 0x70001: [1, 0], 0x70002: [None, 0]})
    plays = bk.keyed_plays()
    assert plays[0x70001] == [SMo.bank_slot_key(7, 1), SMo.bank_slot_key(7, 0)]
    assert CS.sids_for_slot(plays, SMo.bank_slot_key(7, 0)) == [0x70000]
    assert CS.sids_for_slot(plays, SMo.bank_slot_key(7, 1)) == [0x70001]


def _write_stubs(monkeypatch, tmp_path, idx_plays, banks, reads):
    monkeypatch.setattr(E, "_params_for", lambda *a, **k: [])
    monkeypatch.setattr(E, "_card_descriptor_sites", lambda *a, **k: [])
    monkeypatch.setattr(E, "_card_sites_key", lambda *a, **k: "k")
    monkeypatch.setattr(E, "_sound_id_plays", lambda *a, **k: dict(idx_plays))
    reader = types.SimpleNamespace(iter_regular_files=lambda min_size=1: [
        ("/games/x/image-sc%02d.bin" % c, 0, {"size": 64}) for c in sorted(banks)],
        read_range=lambda n, off, k: b"\0" * k,
        extract_file=lambda node, dst: open(dst, "wb").close())
    monkeypatch.setattr(E, "_open_readers", lambda disk_f, parts: [(0, reader)])

    def read_banks(gr, img, local, log, cancel=None, who="", left=""):
        reads.append((sorted(local), who))
        return {c: banks[c] for c in local}
    monkeypatch.setattr(BS, "read_banks", read_banks)
    from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
    monkeypatch.setattr(SB, "is_pad_bank_at", lambda rd, size: False)


def test_the_spike2_write_reads_a_bank_songs_starting_ids(monkeypatch, tmp_path):
    reads, lines = [], []
    _write_stubs(monkeypatch, tmp_path, {307: [156]}, {1: _bank(1, {0x10000: [1], 0x10002: [1]}),
                                                         7: _bank(7, {0x70001: [1, 0]})}, reads)
    song, intro = SMo.bank_slot_key(1, 1), SMo.bank_slot_key(7, 0)
    shows = [{"slot": 156}, {"slot": song}, {"slot": intro}]
    E._BANK_SONGS_ONCE[:] = [None, {}]
    try:
        got = E._cab_sids_for_build(None, [], str(tmp_path), lambda m, *a: lines.append(m),
                                    str(tmp_path / "game"), str(tmp_path / "image.bin"), shows)
    finally:
        E._BANK_SONGS_ONCE[:] = [None, {}]
    # an idx song's ids as before; bank 01's song by both its ids; bank 07's record 0 is no id's first play
    assert got == {156: [307], song: [0x10000, 0x10002], intro: []}
    assert reads == [([1, 7], "Expression lights")]
    assert any(m.startswith("Expression lights: read 2 of the game's own sound bank(s)") for m in lines)


def test_a_bank_the_music_modes_read_is_not_read_again(monkeypatch, tmp_path):
    reads = []
    banks = {1: _bank(1, {0x10000: [1]}), 2: _bank(2, {0x20000: [0]})}
    _write_stubs(monkeypatch, tmp_path, {}, banks, reads)
    gr = str(tmp_path / "game")
    E._BANK_SONGS_ONCE[:] = [os.path.abspath(gr), {1: banks[1]}]          # the music modes read bank 01
    try:
        got = E._cab_sids_for_build(None, [], str(tmp_path), lambda *a: None, gr, str(tmp_path / "image.bin"),
                                    [{"slot": SMo.bank_slot_key(1, 1)}, {"slot": SMo.bank_slot_key(2, 0)}])
        assert set(E._bank_songs_read(gr)) == {1, 2}                       # kept for the build's later steps
    finally:
        E._BANK_SONGS_ONCE[:] = [None, {}]
    assert reads == [([2], "Expression lights")]
    assert got == {SMo.bank_slot_key(1, 1): [0x10000], SMo.bank_slot_key(2, 0): [0x20000]}


def test_a_bank_that_cannot_be_read_leaves_its_shows_out_and_says_so(monkeypatch, tmp_path):
    reads, lines = [], []
    _write_stubs(monkeypatch, tmp_path, {}, {}, reads)                    # the card has no image-sc03.bin
    E._BANK_SONGS_ONCE[:] = [None, {}]
    try:
        got = E._cab_sids_for_build(None, [], str(tmp_path), lambda m, *a: lines.append(m),
                                    str(tmp_path / "game"), str(tmp_path / "image.bin"),
                                    [{"slot": SMo.bank_slot_key(3, 0)}])
    finally:
        E._BANK_SONGS_ONCE[:] = [None, {}]
    assert got == {SMo.bank_slot_key(3, 0): []}
    assert ("Expression lights: this card has no sound bank image-sc03.bin; the shows of its songs are left out."
            in lines)
    text, skipped = CS.cfg_text([CS.norm_show({"name": "Tom Sawyer", "slot": SMo.bank_slot_key(3, 0),
                                               "blades": [{"fx": "solid", "ms": 1000}]})], got, only=True)
    assert skipped == ["Tom Sawyer"]


def test_a_write_with_no_bank_song_shows_reads_no_bank(monkeypatch, tmp_path):
    reads = []
    _write_stubs(monkeypatch, tmp_path, {307: [156]}, {1: _bank(1, {0x10000: [1]})}, reads)
    got = E._cab_sids_for_build(None, [], str(tmp_path), lambda *a: None, str(tmp_path / "game"),
                                str(tmp_path / "image.bin"), [{"slot": 156}])
    assert got == {156: [307]} and reads == []


def test_the_lights_tab_lists_a_spike2_cards_bank_songs(tmp_path):
    from pinball_decryptor.webui.tabs import lights as L
    src = open(L.__file__, encoding="utf-8").read()
    assert "banks=True)" in src and "self._spike3" not in src                 # every card's, not Spike 3's alone
    rels = ["audio/idx0412 - music.wav", "audio/music_cat01_0001 - Tom Sawyer.wav"]
    slots = [types.SimpleNamespace(rel_path=r, abs_path=str(tmp_path / os.path.basename(r)), duration=90.0,
                                   info=object()) for r in rels]
    got = L._songs(types.SimpleNamespace(_slots=slots, _assign={}), banks=True)
    assert [s["slot"] for s in got] == [412, SMo.bank_slot_key(1, 1)]


def test_the_writes_show_count_is_said_under_their_own_name():
    src = open(E.__file__, encoding="utf-8").read()
    i = src.index('if _line.startswith("expression lights: "):')
    assert 'log("Expression lights: %s."' in src[i:i + 300]               # not "Random clips: expression lights"
