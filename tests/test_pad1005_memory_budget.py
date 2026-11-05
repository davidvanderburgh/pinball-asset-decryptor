"""PAD-1005 round 2: the Audio tab shows how much of the machine's memory the card's sounds will
take, before a Write. An owner found out only at Write time that his songs at random did not fit
and asked what the limit was; David: "for limits like this we need to visualize it to the user
somehow. Knowing ahead of time is very meaningful."

Measured against the real build on stock Godzilla Pro 1.16 (``C:\\tmp\\PAD-1005``): 7 tracks x 3
songs of 5 minutes, the build planned 2,073 MB (estimate 2,071); of 7 minutes, the build refused
for 2,241 MB (estimate 2,240). The numbers below are those cards' shapes.
"""
import os
import wave

from pinball_decryptor.core.audio import AudioInfo
from pinball_decryptor.plugins.stern import memory_budget as MB
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from pinball_decryptor.webui.tabs.audio import _memory_estimate

STOCK = 1_647_695_474           # Godzilla Pro 1.16's extracted sounds, PCM bytes (image.bin 1,650 MB)
SONG5 = MB.pcm_bytes(300, 2)    # a 5-minute stereo song: 52,920,000 bytes


def test_a_5_minute_song_is_its_pcm_and_21_of_them_fit_as_the_build_planned():
    assert SONG5 == 52_920_000
    est = MB.estimate(STOCK, [("s%d" % i, SONG5) for i in range(21)])
    assert len(est["banks"]) == 21                  # past a 40 MB slice: a bank each
    assert est["live"] == 8 * SONG5                 # the 8 biggest at once
    assert est["total"] == STOCK + 8 * SONG5 and 0 < est["left"] < 120_000_000
    text, kind, _h, lines = MB.words(est)
    assert text == "Machine memory: about 2,071 of 2,182 MB" and kind == "warn"
    assert lines[0]["bar"][-1] == {"v": est["left"], "label": "Room left", "kind": "free"}
    assert ["In use", "about 2,071 of 2,182 MB"] in lines
    assert {"li": "About 111 MB, about 10.5 minutes of stereo, for the longest songs to share."} in lines


def test_7_minute_songs_are_over_as_the_build_refused():
    est = MB.estimate(STOCK, [("s%d" % i, MB.pcm_bytes(420, 2)) for i in range(21)])
    assert est["total"] > SB.MAPPED_MAX and round(est["total"] / 1e6) == 2240
    text, kind, _h, lines = MB.words(est)
    assert kind == "err" and "2,240 of 2,182" in text
    assert ["In use", "about 2,240 of 2,182 MB (over by 58 MB)"] in lines
    assert {"li": "About 58 MB too much, about 5.5 minutes of stereo."} in lines
    assert lines[0]["of"] == SB.MAPPED_MAX and all(p["kind"] != "free" for p in lines[0]["bar"])


def test_short_sounds_share_slices_and_the_game_s_replaced_recordings_come_out():
    est = MB.estimate(1000_000_000, [("a", 30_000_000), ("b", 15_000_000), ("c", 9_000_000),
                                     ("d", 5_000_000)], credit=20_000_000)
    assert est["image"] == 980_000_000
    assert est["banks"] == [39_000_000, 20_000_000]     # 30+9 and 15+5, a 40 MB slice each
    assert est["live"] == 59_000_000 and est["longest"] == ("a", 30_000_000)
    assert MB.words(MB.estimate(1000_000_000))[1] == ""  # nothing near the room: no warning


def _wav(path, secs, ch=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(8000)                        # (a short header-only length: 8 kHz)
        w.writeframes(b"\0" * int(secs * 8000) * 2 * ch)
    return str(path)


def test_the_audio_tab_counts_mode_files_their_turns_and_longer_replacements(tmp_path):
    a = _wav(tmp_path / "a.wav", 2.0)
    b = _wav(tmp_path / "b.wav", 3.0)               # a file in turn: cut to its mode file's 2 s
    t = _wav(tmp_path / "t.wav", 9.0, ch=1)         # a slot's file in turn: cut to its slot's 1 s
    r = _wav(tmp_path / "r.wav", 4.0, ch=1)         # a longer replacement of a 1 s mono sound
    slots = [("audio/idx0601.wav", "x", AudioInfo("x", "pcm", 2, 44100, 16, 10.0)),
             ("audio/idx0002.wav", "y", AudioInfo("y", "pcm", 1, 44100, 16, 1.0))]
    est = _memory_estimate(str(tmp_path), slots, {"audio/idx0601.wav": {2: a, 3: a}},
                           {"audio/idx0601.wav": {2: [b]}}, {"audio/idx0002.wav": [t]},
                           {"audio/idx0002.wav": r}, [])
    stock = MB.pcm_bytes(10, 2) + MB.pcm_bytes(1, 1)
    assert est["image"] == stock - MB.pcm_bytes(1, 1)   # the replaced recording comes out
    got = sorted(est["banks"], reverse=True)
    # a.wav once (one record for two modes), b cut to 2 s, t cut to 1 s, r whole: one slice
    assert got == [MB.pcm_bytes(2, 2) * 2 + MB.pcm_bytes(1, 1) + MB.pcm_bytes(4, 1)]
    assert est["longest"][0] in ("a.wav", "b.wav")


def test_the_chip_is_in_the_page_head_with_one_tooltip():
    js = os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor", "webui", "static", "js",
                      "tabs", "audio.js")
    with open(js, encoding="utf-8") as f:
        c = f.read()
    assert "title=${{ head: s.mem.head, lines: s.mem.lines }}>${s.mem.text}" in c


# ---- a game with sound banks of its own (Deadpool Pro 1.16: 16, image-sc01..55, up to 80.4 MB) --
DP_IMAGE = 1_612_000_000
DP_BANKS = [58_100_000, 44_200_000, 51_200_000, 63_500_000, 28_200_000, 37_000_000, 61_200_000,
            35_200_000, 45_200_000, 39_000_000, 54_300_000, 56_500_000, 80_400_000, 58_300_000,
            32_300_000, 4_300_000]


def test_the_game_s_biggest_own_bank_takes_one_of_the_8_places():
    game, cap, chans = SB.room_beside(DP_BANKS)
    assert (game, cap, chans) == (80_400_000, SB.MAPPED_MAX - 80_400_000, 7)
    assert SB.room_beside([]) == (0, SB.MAPPED_MAX, 8)
    est = MB.estimate(DP_IMAGE, [("s%d" % i, SONG5) for i in range(21)], vendor=DP_BANKS)
    assert est["chans"] == 7 and est["live"] == 7 * SONG5 and est["game_n"] == 16
    assert est["total"] == DP_IMAGE + 7 * SONG5 + 80_400_000
    _t, _k, _h, lines = MB.words(est)
    assert ["The game's own banks", "80 MB: the biggest of its 16"] in lines
    assert any(p["kind"] == "game" for p in lines[0]["bar"])


def test_the_audio_tab_counts_a_game_s_bank_sounds_as_their_bank_not_image_bin(tmp_path):
    a = _wav(tmp_path / "a.wav", 2.0)
    slots = [("audio/idx0001.wav", "x", AudioInfo("x", "pcm", 2, 44100, 16, 10.0)),
             ("audio/music_cat40_0000.wav", "y", AudioInfo("y", "pcm", 2, 44100, 16, 6.0)),
             ("audio/music_cat40_0001.wav", "z", AudioInfo("z", "pcm", 2, 44100, 16, 4.0)),
             ("audio/music_cat03_0000.wav", "w", AudioInfo("w", "pcm", 2, 44100, 16, 3.0))]
    est = _memory_estimate(str(tmp_path), slots, {"audio/idx0001.wav": {2: a}}, {}, {}, {}, [])
    assert est["image"] == MB.pcm_bytes(10, 2)
    assert est["game"] == MB.pcm_bytes(10, 2) and est["game_n"] == 2 and est["chans"] == 7


def test_the_write_counts_the_game_s_own_bank_beside_its_own(monkeypatch, tmp_path):
    """engine._plan_sound_banks: the same rule. A long song's bank is refused at the room left
    beside image.bin and the game's own biggest bank."""
    import inspect
    from pinball_decryptor.plugins.stern import engine as E
    src = inspect.getsource(E._plan_sound_banks)
    assert "game_bank, cap, chans = SB.room_beside(vendor)" in src
    assert "SB.is_pad_bank_at(" in src
    assert "room = min(cap_alone, max(0, cap - mem_img - sum(others)))" in src
    assert "live = sum(sizes[:chans])" in src
    chk = inspect.getsource(E._memory_check)
    assert 'getattr(plan, "game_bank", 0)' in chk


def test_a_bank_this_app_made_is_not_the_game_s(tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    import struct
    count, md_off = 1, 0x200
    size = md_off + MD.tail_len(count)
    head = bytearray(SB.HDR_LEN)
    struct.pack_into("<I", head, SB.HDR_MD_OFF, md_off)
    struct.pack_into("<I", head, SB.HDR_COUNT, count)
    body = bytearray(size)
    body[:SB.HDR_LEN] = head
    at = md_off + MD.align16(MD.RECORD_SIZE * count) + 4
    try:
        MD.header_geometry(bytes(head))
    except Exception:                                   # noqa: BLE001 - the layout is MD's own
        return
    read = lambda off, n: bytes(body[off:off + n])     # noqa: E731
    assert SB.is_pad_bank_at(read, size) is False
    body[at:at + 4] = SB.PAD_TRAILER
    assert SB.is_pad_bank_at(read, size) is True
    assert SB.is_pad_bank_at(read, size + 1) is False


def test_a_slot_the_game_never_plays_keeps_its_songs_in_image_bin(tmp_path):
    """Deadpool Pro 1.16's idx 2131: no sound request plays it, so the build keeps its music
    mode's files in image.bin (the real Write's image.bin was 159 MB bigger), and none is heard."""
    a = _wav(tmp_path / "a.wav", 2.0)
    b = _wav(tmp_path / "b.wav", 2.0)
    slots = [("audio/idx2131.wav", "x", AudioInfo("x", "pcm", 2, 44100, 16, 10.0)),
             ("audio/idx0001.wav", "y", AudioInfo("y", "pcm", 2, 44100, 16, 10.0))]
    est = _memory_estimate(str(tmp_path), slots, {"audio/idx2131.wav": {2: a}, "audio/idx0001.wav": {2: b}},
                           {"audio/idx2131.wav": {2: [b]}}, {}, {}, [],
                           uses={"audio/idx2131.wav": [], "audio/idx0001.wav": [(76, "TUNE")]})
    assert est["image"] == MB.pcm_bytes(20, 2) + 2 * MB.pcm_bytes(2, 2)
    assert est["banks"] == [MB.pcm_bytes(2, 2)] and est["unplayed"] == [("idx2131.wav", 2)]
    _t, _k, _h, lines = MB.words(est)
    assert {"sec": "Never played by the game"} in lines
    assert any("idx2131.wav: no sound request plays it, so its 2 songs" in str(l) for l in lines)


def test_a_slot_whose_header_the_tab_has_not_read_yet_still_counts(tmp_path):
    """The tab reads a slot's format lazily (a Deadpool card's 8,252 sounds are mostly unread when
    the estimate runs): it reads the header itself, or image.bin came out at 870 MB, not 1,612."""
    x = _wav(tmp_path / "idx0001.wav", 3.0)
    y = _wav(tmp_path / "music_cat40_0000.wav", 2.0)
    a = _wav(tmp_path / "a.wav", 1.0)
    est = _memory_estimate(str(tmp_path), [("audio/idx0001.wav", x, None),
                                           ("audio/music_cat40_0000.wav", y, None)],
                           {"audio/idx0001.wav": {2: a}}, {}, {}, {}, [])
    assert est["image"] == MB.pcm_bytes(3, 2) and est["game"] == MB.pcm_bytes(2, 2)
