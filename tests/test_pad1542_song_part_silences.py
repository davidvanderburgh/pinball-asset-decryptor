"""PAD-1542: a replaced song's music plays without the game's own short opening and ending.

Shapes are Iron Maiden LE 1.18's, read off the card: "MUSIC: ICARUS" (sound id 977) is idx
471's 0.6 s then idx 950's 219 s; 968 goes on into idx 941's 10.5 s ending.  A tester's own song
on idx 950 started with the first second of Flight of Icarus on the song select."""
import os
import wave

from pinball_decryptor.plugins.stern import engine as E

S = 44100


def _byidx(lengths):
    return {i: {"idx": i, "length": int(sec * S), "chan": 2} for i, sec in lengths.items()}


IM = _byidx({471: 0.6, 950: 219.0, 941: 10.5, 307: 9.1, 492: 236.7, 212: 4.6,
             222: 7.5, 150: 63.1, 618: 138.3, 426: 273.0, 895: 157.2, 786: 176.4,
             281: 158.4, 12: 1.0})
WIDE = {977: (b"", [471, 950]), 968: (b"", [471, 950, 941]),
        947: (b"", [307, 492]), 935: (b"", [307, 492, 212]),
        976: (b"", [222, 150, 618]), 960: (b"", [150, 618]),
        962: (b"", [426, 895]), 978: (b"", [786, 895]), 979: (b"", [426, 281]),
        5: (b"", [12])}


def test_icarus_opening_and_ending_silenced_with_its_music():
    got = E._song_part_silences(IM, WIDE, {950: "idx0950.wav"}, "")
    assert got == {471: (950, [968, 977]), 941: (950, [968])}


def test_long_parts_keep_their_music():
    # Run to the Hills: 7.5 s opening silenced, its 63 s first half is music and stays
    got = E._song_part_silences(IM, WIDE, {618: "x.wav"}, "")
    assert set(got) == {222}


def test_part_played_without_the_replaced_music_keeps_its_sound():
    # the 307 opening: every sid playing it plays 492 too -> silenced; if one plays it alone
    wide = {**WIDE, 999: (b"", [307])}
    assert 307 in E._song_part_silences(IM, WIDE, {492: "x.wav"}, "")
    assert 307 not in E._song_part_silences(IM, wide, {492: "x.wav"}, "")


def test_short_replacement_or_replaced_part_left_alone():
    # replacing the 0.6 s opening itself is not replacing the song's music
    assert E._song_part_silences(IM, WIDE, {471: "x.wav"}, "") == {}
    # a part the user replaced keeps their file
    got = E._song_part_silences(IM, WIDE, {950: "a.wav", 471: "b.wav"}, "")
    assert set(got) == {941}
    # a record nothing plays in a sequence: nothing to silence
    assert E._song_part_silences(IM, WIDE, {426: "x.wav"}, "") == {}


def test_silence_file_and_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_wide_descriptors_once", lambda *a: WIDE)
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a, **k: 0)
    lines = []
    params = list(IM.values())
    got = E._silence_song_parts("g", "i", params, [object()], {950: "idx0950.wav"},
                                str(tmp_path), str(tmp_path / "work"),
                                lambda t, l="info": lines.append(t))
    assert got[950] == "idx0950.wav" and set(got) == {950, 471, 941}
    with wave.open(got[471], "rb") as w:
        assert (w.getnframes(), w.getframerate(), w.getnchannels()) == (E._SONG_EDGE_SILENCE, 44100, 2)
        assert set(w.readframes(w.getnframes())) == {0}
    assert E._wav_frames_44k(got[941]) == E._SONG_EDGE_SILENCE
    assert any("idx 471" in t and "977" in t for t in lines)
    # no sites -> unchanged
    assert E._silence_song_parts("g", "i", params, [], {950: "a"}, "", "", print) == {950: "a"}
