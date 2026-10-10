"""PAD-511 (a tester): "Idx SE GZ MX TUNE 16 still played the stock audio even though I have the
game set to Music Mode 4, and there is an alternate file for Music Mode 4".

Godzilla 1.16 plays TUNE 16 in two parts: idx 2241 (the 9.6 s the Sound Test names "SE GZ MX TUNE
16"), then idx 799 (38.4 s, a music record the Sound Test leaves unnamed), looped. The mode's
descriptor swapped idx 2241 alone, so the game played the tester's file for 9.6 s and then its own
song. A file for the opening part of a song in parts now plays in place of the whole song, once
where the song played once and looped where its body looped. Every descriptor below is the game's
own window, read through its resolver off the Godzilla LE 1.16 card."""

import struct

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK

MASK = 0xE0001FFF                     # Godzilla LE 1.16's key mask
TUNE16 = "audio/idx2241 - SE GZ MX TUNE 16.wav"

#: request 94, TUNE 16: idx 2241, then idx 799 looped ("0b 11 07 0b 11 03"); its own 45 bytes, then
#: the next descriptor's
D2541 = bytes.fromhex("050101c1ed020001000002000e0b0000003e300bdab7a2ecfa110107000b00000071f07b2ea590744011"
                      "0103007b6af819d48a3e77f6abe62d06646cfbabd44bb942a51b5b95163fd111e2054ae44c70")
#: request 152: idx 2241, then idx 799, once ("0b 11 0b 11 00"); 42 bytes
D2587 = bytes.fromhex("050101c1ed02000100000200100b0000003e300bdab70220fa11010b00000071f07b2ea530d6581101"
                      "00191ba98cee17a89490dd77eb2a62439f24d394dca176f1a3cf34370b8d9d32c76cb33bfbbf57")
#: three music records, once (56 bytes) and all three looped (59 bytes)
D2489 = bytes.fromhex("050101f59806000100000200060b000000ea92e3be3772fbfd11010b000000c7b232d163d4651d1101"
                      "0b00000051d8eab805966b191101006b41af03d2bd95006640704b6fccd0767fe66a27e16367a6")
D2545 = bytes.fromhex("050101f598060001000002000107000b000000ea92e3be371272ef11010b000000c7b232d16394b107"
                      "11010b00000051d8eab805d6c20f11010300ebe876542b41c7d6d9b8c08893af22e53fddf43790")
#: idx 877, then idx 66 looped, with the 06 and 08 set-ups around them (56 bytes)
D2532 = bytes.fromhex("050101d02b0f000100000200010608010000000b0000002db27ae7b75814451101080200000007000b000000"
                      "b6f2c84c0766e81f1101030066400023f4221ab23b8c03f34095588850ab547d7e2e605b")
#: a sound effect whose script has an op the rewrite does not know (0x09)
D68 = bytes.fromhex("051c01493d00000200080900a0000000050000000500010000000b0000006051910df75450c210293a00"
                    "0009004001000005000000fbffffff00001101003bd82d2ffea0458268fa0652b9eb07c33e61")

K2241 = bytes.fromhex("3e300bdab70200e0")          # the records' keys on the card
K799 = bytes.fromhex("71f07b2ea5100040")
HOST = E._play_key(bytes.fromhex("6f31228f15c03a10"), 2547, MASK)


def _dur(d):
    return struct.unpack_from("<I", d, E._DESC_DUR_OFF)[0]


def _script(desc, sid, extent=None):
    """The descriptor's script as words: the record each play names, the other ops by number."""
    names = {K2241: "2241", K799: "799", HOST: "HOST"}
    out = []
    for b in E._desc_ops(desc, extent):
        out.append("play %s" % names.get(E._play_key(b[4:12], sid, MASK), "?")
                   if b[0] == 0x0b else "%02x" % b[0])
    return " ".join(out)


# ---- the game's scripts -------------------------------------------------------------------------
def test_a_script_reads_op_by_op_to_where_the_next_descriptor_starts():
    assert _script(D2541, 2541, 45) == "01 02 play 2241 11 07 play 799 11 03"
    assert _script(D2587, 2587, 42) == "01 02 play 2241 11 play 799 11 00"
    assert [b[0] for b in E._desc_ops(D2532, 56)] == [1, 2, 6, 0x0b, 0x11, 8, 7, 0x0b, 0x11, 3]
    # a script that does not end exactly there is not one the table reads right
    assert E._desc_ops(D2541, 44) is None and E._desc_ops(D2541, 46) is None
    assert E._desc_ops(D68, 62) is None                               # op 0x09: not known
    assert E._desc_ops(D2541) is not None                              # no extent: within the window


# ---- which sounds are songs in parts ------------------------------------------------------------
def _row(idx, seconds, key=None):
    return {"idx": idx, "length": int(seconds * 44100) + BLOCK, "chan": 2,
            "findkey": key or bytes([idx % 256, idx // 256]) * 4}


def test_a_song_opens_with_the_slot_and_goes_on_into_other_music():
    byidx = {i: _row(i, s) for i, s in ((2241, 9.6), (799, 38.4), (5, 3.0), (6, 30.0))}
    plays = {2541: [2241, 799], 2587: [2241, 799], 10: [2241], 11: [799, 2241], 12: [2241, 5],
             13: [2241, None], 14: [2241, 799, 6]}
    assert E._sound_mode_song(2241, plays, byidx) == {2541: [799], 2587: [799], 14: [799, 6]}
    # a part with a file of its own in that mode plays its own file
    assert E._sound_mode_song(2241, plays, byidx, own={799}) == {}
    # the body is no song's opening part
    assert E._sound_mode_song(799, plays, byidx) == {}


def test_the_records_a_sound_id_plays_are_read_off_the_play_tables():
    by = [_row(2241, 9.6, K2241), _row(799, 38.4, K799), _row(974, 86.7, b"\x9e\xf9\x4b\x2c\x17\x04\x00\x40")]
    sites = []
    for sid, start, desc in ((2541, 1000, D2541), (2587, 1045, D2587)):
        for p, pl in E._op11_payloads(desc):
            sites.append(E._DescSite(sid, start + p, b"\0" * 8, pl, start + 3, b"\0" * 4, _dur(desc)))
    plays = E._sound_id_plays(by, sites, MASK)
    # 2541's window runs into 2587's (45 bytes on): those payloads are 2587's
    assert plays == {2541: [2241, 799], 2587: [2241, 799]}


# ---- the descriptor the runtime hands the game ---------------------------------------------------
def test_tune_16_looped_plays_the_file_and_then_loops_it():
    mu, su, pu = 240000, 38000, 153000                # the file 60 s, the intro, the body
    got = E._mode_song_descriptor(D2541, 2541, MASK, K2241, HOST, mu, su, [pu], extent=45)
    assert _script(got, 2541) == "01 02 play HOST 11 07 play HOST 11 03"
    assert _dur(got) == _dur(D2541) + mu - su + mu - pu
    assert got[45:] == D2541[45:] and len(got) == len(D2541)    # the next descriptor's bytes kept
    # each payload keeps its bits outside the key mask
    for (o, new), (_o, old) in zip(E._op11_payloads(got[:45]), E._op11_payloads(D2541[:45])):
        w2n, w2o = struct.unpack_from("<I", new, 4)[0], struct.unpack_from("<I", old, 4)[0]
        assert w2n & ~MASK & 0xFFFFFFFF == w2o & ~MASK & 0xFFFFFFFF


def test_tune_16_once_plays_the_file_once():
    mu, su, pu = 240000, 38000, 153000
    got = E._mode_song_descriptor(D2587, 2587, MASK, K2241, HOST, mu, su, [pu], extent=42)
    assert _script(got, 2587) == "01 02 play HOST 11 00"
    assert got[27:42] == bytes(15)                    # the dropped play and its wait, after the end
    assert got[42:] == D2587[42:]
    assert _dur(got) == _dur(D2587) + mu - su - pu


def test_a_song_in_three_parts_plays_the_file_once_or_loops_it():
    once = E._mode_song_descriptor(D2489, 2489, MASK, _rk(D2489, 2489, 0), HOST, 9000, 100,
                                   [200, 300], extent=56)
    assert [b[0] for b in E._desc_ops(once)] == [1, 2, 0x0b, 0x11, 0]
    assert _dur(once) == _dur(D2489) + 9000 - 100 - 200 - 300
    looped = E._mode_song_descriptor(D2545, 2545, MASK, _rk(D2545, 2545, 0), HOST, 9000, 100,
                                     [200, 300], extent=59)
    assert _script(looped, 2545) == "01 02 07 play HOST 11 03"


def test_a_song_with_set_ups_around_its_parts_keeps_them():
    got = E._mode_song_descriptor(D2532, 2532, MASK, _rk(D2532, 2532, 0), HOST, 9000, 100, [200],
                                  extent=56)
    assert [b[0] for b in E._desc_ops(got, 56)] == [1, 2, 6, 0x0b, 0x11, 8, 7, 0x0b, 0x11, 3]
    assert _script(got, 2532).count("play HOST") == 2


def test_a_script_this_cannot_rewrite_is_left_to_the_plain_swap():
    assert E._mode_song_descriptor(D68, 68, MASK, _rk(D68, 68, 0), HOST, 1, 1, [], extent=62) is None
    # the opening play must be the slot's, and the parts the song's
    assert E._mode_song_descriptor(D2541, 2541, MASK, K799, HOST, 1, 1, [1], extent=45) is None
    assert E._mode_song_descriptor(D2541, 2541, MASK, K2241, HOST, 1, 1, [1, 1], extent=45) is None


def _rk(desc, sid, n):
    return E._play_key(E._op11_payloads(desc)[n][1], sid, MASK)


# ---- one line per mode and sound id ------------------------------------------------------------------
def _table(used, found, rows, logs):
    return E._mode_descriptor_table(found, rows, MASK, used,
                                    lambda t, lvl="info": logs.append((lvl, t)))


def _rows():
    host = _row(4, 60.0, HOST)
    host2 = _row(5, 50.0, E._play_key(bytes.fromhex("1122334455667788"), 0, MASK))
    return [_row(2241, 9.6, K2241), _row(799, 38.4, K799), dict(host, grown=True),
            dict(host2, grown=True)]


def _used(slot, host, song=None, mode=4):
    u = {"rel": "audio/idx%04d.wav" % slot, "slot": slot, "mode": mode, "host": host,
         "frames": 44100 * 60, "name": "Custom C", "level_ref": slot, "db": 0}
    if song:
        u["song"] = song
    return u


FOUND = [(2541, 1000, D2541), (2587, 1045, D2587)]


def test_a_file_for_the_tune_plays_in_place_of_the_whole_song_through_both_sound_ids():
    logs = []
    out = _table([_used(2241, 4, song={2541: [799], 2587: [799]})], FOUND, _rows(), logs)
    assert [(m, s) for m, s, _d in out] == [(4, 2541), (4, 2587)]
    by = {s: d for _m, s, d in out}
    assert _script(by[2541], 2541) == "01 02 play HOST 11 07 play HOST 11 03"
    assert _script(by[2587], 2587) == "01 02 play HOST 11 00"
    assert any("2541, 2587 play it in place of the whole song" in t for _l, t in logs)


def test_without_the_song_the_tune_swaps_its_opening_part_alone():
    """What v1.172.0 built for the tester: his file, then the game's own idx 799."""
    out = _table([_used(2241, 4)], FOUND, _rows(), [])
    assert _script(out[0][2], 2541) == "01 02 play HOST 11 07 play 799 11 03"


def test_two_slots_of_one_mode_in_one_sound_id_are_one_line():
    """Before PAD-511 each was a line of its own and the runtime played the first it found."""
    host2 = E._play_key(bytes.fromhex("1122334455667788"), 0, MASK)
    out = _table([_used(2241, 4), _used(799, 5)], FOUND, _rows(), [])
    assert [(m, s) for m, s, _d in out] == [(4, 2541), (4, 2587)]
    names = {K2241: "2241", K799: "799", HOST: "HOST", host2: "HOST2"}
    plays = [names[E._play_key(b[4:12], 2541, MASK)] for b in E._desc_ops(out[0][2]) if b[0] == 0x0b]
    assert plays == ["HOST", "HOST2"]
    # its own modes stay apart
    out = _table([_used(2241, 4, mode=2), _used(799, 5, mode=3)], FOUND, _rows(), [])
    assert [(m, s) for m, s, _d in out] == [(2, 2541), (2, 2587), (3, 2541), (3, 2587)]


def test_a_song_whose_parts_moved_since_the_grow_plays_the_plain_swap():
    logs = []
    out = _table([_used(2241, 4, song={2541: [799, 799]})], FOUND, _rows(), logs)
    assert _script(dict((s, d) for _m, s, d in out)[2541], 2541).count("play 799") == 1
    assert any(lvl == "warning" and "rest of the game's own song" in t for lvl, t in logs)


# ---- the file's length and loudness ---------------------------------------------------------------
def _wav(path, seconds, rate=44100, chans=2):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(chans)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * chans * int(seconds * rate))
    return str(path)


def _grow(tmp_path, monkeypatch, longer_ok, slots=None):
    made = {"a.wav": _wav(tmp_path / "conv_a.wav", 120.0), "b.wav": _wav(tmp_path / "conv_b.wav", 5.0)}
    monkeypatch.setattr(SMo, "convert", lambda project, rel, mode, src, log=None: made[src])
    rows = [_row(2241, 9.6, K2241), _row(799, 38.4, K799), _row(4, 100.0), _row(7, 4.0),
            _row(8, 50.0), _row(9, 3.0)]
    sites = []
    for sid, start, desc in ((2541, 1000, D2541), (2587, 1045, D2587)):
        for p, pl in E._op11_payloads(desc):
            sites.append(E._DescSite(sid, start + p, b"\0" * 8, pl, start + 3, b"\0" * 4, _dur(desc)))
    m = SMo.clean({"slots": slots or {TUNE16: {"4": "a.wav"}}})
    logs = []
    edits, grows, used = E._sound_modes_grow(str(tmp_path), rows, {}, {}, m,
                                             lambda t, lvl="info": logs.append(t),
                                             longer_ok=longer_ok, longer_why="off in Settings",
                                             sites=sites)
    return edits, grows, used, logs


def test_the_file_for_a_songs_opening_part_is_cut_to_the_song_not_the_part(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length
    edits, grows, used, logs = _grow(tmp_path, monkeypatch, longer_ok=False)
    song = emitted_length(_row(2241, 9.6)["length"]) + emitted_length(_row(799, 38.4)["length"])
    assert [u["frames"] for u in used] == [song]
    assert used[0]["song"] == {2541: [799], 2587: [799]}
    assert used[0]["level_ref"] == 799                 # the song's longest part
    assert E._sm_level_refs(used) == {used[0]["host"]: 799}
    assert any("in place of the whole song" in t for t in logs)
    assert any("cut to its song's" in t for t in logs)


def test_the_file_for_a_songs_opening_part_plays_whole_when_longer_files_may(tmp_path, monkeypatch):
    edits, grows, used, logs = _grow(tmp_path, monkeypatch, longer_ok=True)
    assert [u["frames"] for u in used] == [120 * 44100]


def test_a_tune_whose_body_has_its_own_file_in_that_mode_keeps_both(tmp_path, monkeypatch):
    edits, grows, used, logs = _grow(tmp_path, monkeypatch, longer_ok=True, slots={
        TUNE16: {"4": "a.wav"}, "audio/idx0799 - music.wav": {"4": "b.wav", "2": "a.wav"}})
    by = {(u["slot"], u["mode"]): u for u in used}
    assert "song" not in by[(2241, 4)] and "song" not in by[(799, 4)]
    assert by[(2241, 4)]["level_ref"] == 2241
