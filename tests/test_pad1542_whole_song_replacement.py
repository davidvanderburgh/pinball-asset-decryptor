"""PAD-1542: a replaced song's music plays in place of the whole song.

Iron Maiden LE 1.18, read off the card: the song select's "MUSIC: ICARUS" (sound id 977) plays
idx 471's 0.6 s once and then loops idx 950's 219 s; 968 plays 471, 950 and idx 941's 10.5 s
ending once.  A tester's own song on idx 950 started with the first second of Flight of Icarus.
The game's other pieces of the song now drop out of its descriptors, whatever their length."""
import os
import struct

from pinball_decryptor.plugins.stern import engine as E

S = 44100
MASK = 3153854467
D977 = bytes.fromhex("050101f0660d000100000200030608010000000b000000993b5d4060dd113b1101080200000007"
                     "000b0000006a177584d5745cba11010300")
D968 = bytes.fromhex("050101340b0e000100000200030608010000000b000000993b5d40f0c8103b110108020000000b"
                     "0000006a1775847da65cba110108030000000b000000361eed1cac9256b9110100")
RECS = {471: ("993b5d400000103b", 24979), 950: ("6a17758401005cba", 9658490),
        941: ("361eed1c000054b9", 463617)}
TROOPER = {307: ("bee35d160300e822", 402280), 492: ("64b77d100100bc80", 10440666)}


def _params():
    return [{"idx": i, "findkey": bytes.fromhex(k), "length": n, "chan": 2}
            for i, (k, n) in RECS.items()]


def _byidx(lengths):
    return {i: {"idx": i, "length": int(sec * S), "chan": 2} for i, sec in lengths.items()}


IM = _byidx({471: 0.6, 950: 219.0, 941: 10.5, 307: 9.1, 492: 236.7, 212: 4.6,
             222: 7.5, 150: 63.1, 618: 138.3, 426: 273.0, 895: 157.2, 786: 176.4,
             281: 158.4, 12: 1.0})
WIDE = {977: (b"", [471, 950]), 968: (b"", [471, 950, 941]),
        947: (b"", [307, 492]), 935: (b"", [307, 492, 212]),
        976: (b"", [222, 150, 618]), 974: (b"", [222, 150, 618]), 960: (b"", [150, 618]),
        962: (b"", [426, 895]), 978: (b"", [786, 895]), 979: (b"", [426, 281]),
        5: (b"", [12])}


def _plays(desc, sid):
    return [E._play_key(pl, sid, MASK) for _o, pl in E._own_payloads(desc)]


def test_icarus_plays_its_replacement_alone():
    plans, kept = E._whole_song_plans(IM, WIDE, {950: "idx0950.wav"})
    assert plans == {977: (950, [471, 950]), 968: (950, [471, 950, 941])} and kept == {}


def test_long_pieces_drop_out_too():
    # Run to the Hills: its 7.5 s opening and its 63 s first half are pieces of the song
    plans, _k = E._whole_song_plans(IM, WIDE, {618: "x.wav"})
    assert set(plans) == {974, 976, 960}


def test_piece_the_game_plays_elsewhere_stays():
    # Hallowed: 895 is also another song's (978), so 962 plays it after the replacement
    plans, kept = E._whole_song_plans(IM, WIDE, {426: "x.wav"})
    assert kept == {962: (426, [895])} and plans == {979: (426, [426, 281])}
    # ... but 978 is a sound id the game never plays (no request names it): 895 drops out too
    plans, kept = E._whole_song_plans(IM, WIDE, {426: "x.wav"}, idle={978})
    assert kept == {} and set(plans) == {962, 979}
    wide = {**WIDE, 999: (b"", [307])}
    assert 947 in E._whole_song_plans(IM, WIDE, {492: "x"})[0]
    assert E._whole_song_plans(IM, wide, {492: "x"})[0] == {}


def test_users_own_pieces_and_short_records_left_alone():
    assert E._whole_song_plans(IM, WIDE, {471: "x.wav"}) == ({}, {})
    assert E._whole_song_plans(IM, WIDE, {950: "a.wav", 471: "b.wav"}) == ({}, {})
    # two replaced pieces of music in one sound id: they play as the user made them
    assert E._whole_song_plans(IM, WIDE, {150: "a", 618: "b"})[0] == {}


def test_real_descriptors_rewritten():
    k = {i: bytes.fromhex(v[0]) for i, v in RECS.items()}
    u = {i: E._duration_units_emitted(v[1]) for i, v in RECS.items()}
    # 977: 471 once, then 950 looped -> 950, then 950 looped
    d = E._mode_song_descriptor(D977, 977, MASK, k[471], k[950], u[950], u[471], [u[950]],
                                extent=len(D977))
    assert len(d) == len(D977) and _plays(d, 977) == [k[950], k[950]]
    assert struct.unpack_from("<I", d, 3)[0] & 0xFFFFFF == 2 * u[950] + (
        struct.unpack_from("<I", D977, 3)[0] & 0xFFFFFF) - u[471] - u[950]
    # 968: 471, 950, 941 once -> 950 alone, declared as long as 950 (plus the stock base)
    d = E._mode_song_descriptor(D968, 968, MASK, k[471], k[950], u[950], u[471],
                                [u[950], u[941]], extent=len(D968))
    assert len(d) == len(D968) and _plays(d, 968) == [k[950]]
    base = (struct.unpack_from("<I", D968, 3)[0] & 0xFFFFFF) - u[471] - u[950] - u[941]
    assert struct.unpack_from("<I", d, 3)[0] & 0xFFFFFF == u[950] + base


class _Site:
    def __init__(self, sid, dur_off):
        self.sid, self.dur_off = sid, dur_off


def test_whitened_writes_round_trip(tmp_path):
    ks = bytes((37 * i + 11) & 0xFF for i in range(len(D977) + len(D968) + 64))
    at = {977: 16, 968: 16 + len(D977) + 8}
    img = bytearray(ks)
    for sid, d in ((977, D977), (968, D968)):
        for i, b in enumerate(d):
            img[at[sid] + i] = b ^ ks[at[sid] + i]
    p = tmp_path / "image.bin"
    p.write_bytes(bytes(img))
    wide = {977: (D977, [471, 950]), 968: (D968, [471, 950, 941])}
    plans = {977: (950, [471, 950]), 968: (950, [471, 950, 941])}
    sites = [_Site(s, at[s] + 3) for s in at]
    writes, why = E._whole_song_writes(str(p), _params(), sites, wide, plans, MASK)
    assert why == {} and writes
    for off, b in writes.items():
        img[off:off + len(b)] = b
    k950 = bytes.fromhex(RECS[950][0])
    for sid, d in ((977, D977), (968, D968)):
        plain = bytes(img[at[sid] + i] ^ ks[at[sid] + i] for i in range(len(d)))
        assert set(_plays(plain, sid)) == {k950}
    # nothing outside the two descriptors moved
    assert all(at[977] <= off < at[968] + len(D968) for off in writes)


def test_whole_songs_rolls_back_when_it_does_not_read_back(tmp_path, monkeypatch):
    p = tmp_path / "image.bin"
    p.write_bytes(bytes(256))
    wide = {977: (D977, [471, 950])}
    seq = [wide, {977: (D977, [471, 950])}]         # read back unchanged: not as planned
    monkeypatch.setattr(E, "_wide_descriptors_once", lambda *a: seq.pop(0))
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a, **k: MASK)
    monkeypatch.setattr(E, "_whole_song_writes",
                        lambda *a: ({10: b"\x01\x02"}, {}))
    lines = []
    got = E._whole_songs("g", str(p), _params(), [object()], {950: "x.wav"},
                         lambda t, l="info": lines.append((l, t)))
    assert got == {} and p.read_bytes() == bytes(256)
    assert any(l == "warning" and "did not read back" in t for l, t in lines)


# ------------------------------------------------------------ the Sounds tab's note
def _project(tmp_path):
    from pinball_decryptor.plugins.stern import clip_sounds as CS
    # requests 564 / 567: the song select's ICARUS and its version with the ending; 600 plays
    # Hallowed (426 then 895) and 601 another song with 895; 602 the 0.4 s sting alone
    lists = [[0]] * 603
    idx_of = {564: [471], 567: [471], 600: [426], 601: [786], 602: [12]}
    also = {564: [950], 567: [950, 941], 600: [895], 601: [895]}
    CS.write_requests(str(tmp_path / CS.REQUESTS_TSV), lists, idx_of, {564: "MUSIC: ICARUS"},
                      also=also)
    return str(tmp_path)


SECS = {471: 0.6, 950: 219.0, 941: 10.5, 426: 273.0, 895: 157.2, 786: 176.4, 12: 0.4}


def test_song_pieces_off_the_request_map(tmp_path):
    from pinball_decryptor.plugins.stern import clip_sounds as CS
    got = CS.song_pieces(_project(tmp_path), SECS)
    assert got[950] == {"pieces": [471, 941], "kept": [], "music": []}
    assert got[471]["music"] == [950] and got[941]["music"] == [950]
    # Hallowed's 895 is music too, and another song's (601 plays it after 786): kept beside 426
    assert got[426]["pieces"] == [895] and got[426]["kept"] == [895]
    assert 12 not in got


def test_song_cells_words(tmp_path):
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    from pinball_decryptor.webui.tabs import audio as A
    import wave
    proj = _project(tmp_path)
    os.makedirs(os.path.join(proj, "audio"))
    rels = []
    for i, sec in SECS.items():           # 1 kHz mono files of the records' real lengths
        rels.append("audio/idx%04d.wav" % i)
        with wave.open(os.path.join(proj, rels[-1]), "wb") as w:
            w.setnchannels(1); w.setsampwidth(1); w.setframerate(1000)
            w.writeframes(bytes(int(sec * 1000)))
    parts = SternManufacturer().sound_song_parts(proj, rels)
    music = A._song_cells("audio/idx0950.wav", parts)
    assert music["sp"] == "Song in 3 parts" and music["spn"] == 3
    assert "idx0471 (0.6 s), idx0941 (10.5 s)" in music["sp_tip"][0], music
    assert "plays in place of the whole song" in music["sp_tip"][1]
    piece = A._song_cells("audio/idx0471.wav", parts)
    assert piece["sp"] == "Piece of a song" and "drops out" in piece["sp_tip"][1]
    hall = A._song_cells("audio/idx0426.wav", parts)
    assert any("Kept in it" in t for t in hall["sp_tip"])
    assert A._song_cells("audio/idx0012.wav", parts) == {}


def test_trooper_loop_with_its_waits_and_0e_step():
    """Sound id 950, The Trooper looped: 307 once, then 492 in a loop that waits 20.7 s, runs a
    ``0e 01 00 00 00`` step and waits 25 s - unread (so never rewritten) until 0x0e and 0x10
    were in the op table."""
    d950 = bytes.fromhex("050101c0010f000100000200030b000000bee35d164fd3e822110107000b00000064b77d10"
                         "1577bf8010374401000e0100000010a086010011010300")
    ops = E._desc_ops(d950, len(d950))
    assert ops is not None and [o[0] for o in ops].count(0x10) == 2 and ops[-1][0] == 0x03
    k307, k492 = bytes.fromhex(TROOPER[307][0]), bytes.fromhex(TROOPER[492][0])
    u = {i: E._duration_units_emitted(v[1]) for i, v in TROOPER.items()}
    d = E._mode_song_descriptor(d950, 950, MASK, k307, k492, u[492], u[307], [u[492]],
                                extent=len(d950))
    assert d is not None and _plays(d, 950) == [k492, k492]
    assert E._desc_ops(d, len(d)) is not None and d.count(bytes.fromhex("0e01000000")) == 1


def test_a_dropped_plays_own_wait_goes_with_it():
    # intro (waited for), then the music with a fixed 0x10 wait of its own, once: the later
    # play and its wait go, and the replacement keeps the opening play's wait for it to finish
    k471, k950 = bytes.fromhex(RECS[471][0]), bytes.fromhex(RECS[950][0])
    head = bytes.fromhex("050101") + struct.pack("<I", 1000)[:4]
    body = (b"\x01\x00\x00\x02\x00\x03"              # every real script opens so
            + b"\x0b\x00\x00\x00" + k471 + b"\x11\x01"
            + b"\x0b\x00\x00\x00" + k950 + b"\x10" + struct.pack("<I", 2240) + b"\x00")
    desc = head + body
    d = E._mode_song_descriptor(desc, 5, MASK, k471, k950, 900, 100, [900], extent=len(desc))
    ops = E._desc_ops(d, None)
    assert [o[0] for o in ops] == [0x01, 0x02, 0x0b, 0x11, 0x00] and _plays(d, 5) == [k950]
