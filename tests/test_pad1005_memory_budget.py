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
    assert any(l.startswith("Room left: about 111 MB") for l in lines)


def test_7_minute_songs_are_over_as_the_build_refused():
    est = MB.estimate(STOCK, [("s%d" % i, MB.pcm_bytes(420, 2)) for i in range(21)])
    assert est["total"] > SB.MAPPED_MAX and round(est["total"] / 1e6) == 2240
    text, kind, _h, lines = MB.words(est)
    assert kind == "err" and "2,240 of 2,182" in text
    assert any(l.startswith("Over by about 58 MB") for l in lines)


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
