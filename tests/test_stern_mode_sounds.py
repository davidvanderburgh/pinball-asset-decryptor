"""A mode's own sounds (item 150): carriers per title, their assignment, mode-file lines."""
import os
import struct
from collections import namedtuple

import pytest

from pinball_decryptor.plugins.stern import mode_sounds as MS

Site = namedtuple("Site", "sid payload")


def test_titles_carry_calls_and_music():
    for key in (("godzilla_le", "1.16"), ("godzilla_pro", "1.15")):
        c = MS.carriers(*key)
        assert c is not None
        assert len(c.calls) == len(set(c.calls)) >= 3
        assert len(c.music) == len(set(c.music)) >= 1
        assert not set(c.calls) & set(c.music)
        # item 130's time-up carrier is played by the stock countdown: never a carrier
        assert 1295 not in c.calls and 1295 not in c.music
    assert MS.carriers("godzilla_le", "1.16").key_mask == 0xE0001FFF
    assert MS.carriers("godzilla_pro", "1.15").key_mask == 0xFC0003FF
    assert not MS.carriers("godzilla_le", "1.16").swap
    # item 163: every other latest build swaps its own sounds in; the four builds the engine cannot
    # derive (no resolver, so nothing can grow) have none
    swaps = [k for k, c in MS.TITLES.items() if c.swap]
    assert len(swaps) >= 29 and ("jaws_le", "1.02") in swaps
    for key in swaps:
        c = MS.TITLES[key]
        assert len(c.calls) == len(set(c.calls)) >= 3, key
        assert len(c.music) == len(set(c.music)), key
        assert not set(c.calls) & set(c.music), key
        assert not c.beds, key
    for game, version in (("batman", "1.13"), ("deadpool_le", "1.14"), ("deadpool_pro", "1.16"), ("elvira3", "1.13")):
        assert MS.carriers(game, version) is None


def test_assign_is_distinct_and_stable():
    wants = [MS.SOUND_KEYS, ("sound_start",), (), ("sound_shot", "sound_end")]
    a = MS.assign("godzilla_le", "1.16", wants)
    assert [sorted(x) for x in a] == [sorted(list(MS.SOUND_KEYS) + ["music_sid"]), ["sound_start"], [],
                                      ["sound_end", "sound_shot"]]
    used = [r for x in a for k, r in x.items() if k not in ("music", "music_sid")]
    assert len(used) == len(set(used))
    c = MS.carriers("godzilla_le", "1.16")
    assert a[0]["music"] in c.music and a[0]["sound_shot"] in c.calls and a[0]["music_sid"] in c.beds
    assert MS.assign("godzilla_le", "1.16", wants) == a


def test_assign_runs_out_loudly():
    c = MS.carriers("godzilla_le", "1.16")
    n_calls = len(c.calls) // 3
    MS.assign("godzilla_le", "1.16", [("sound_start", "sound_shot", "sound_end")] * n_calls)
    with pytest.raises(MS.ModeSoundError):
        MS.assign("godzilla_le", "1.16", [("sound_start", "sound_shot", "sound_end")] * (n_calls + 1))
    # item 150 follow-up: every mode has music of its own until the beds run out
    MS.assign("godzilla_le", "1.16", [("music",)] * len(c.beds))
    with pytest.raises(MS.ModeSoundError, match="no music bed left"):
        MS.assign("godzilla_le", "1.16", [("music",)] * (len(c.beds) + 1))
    with pytest.raises(MS.ModeSoundError):
        MS.assign("godzilla_le", "1.16", [("sound_middle",)])
    with pytest.raises(MS.ModeSoundError):
        MS.assign("nobody", "1.0", [("music",)])


def test_cfg_lines():
    a = {"sound_start": 1251, "sound_shot": 1249, "sound_end": 1133, "music": 918}
    assert MS.cfg_lines(a) == ["sound_start    1251", "sound_shot     1249", "sound_end      1133", "music          918"]
    assert MS.cfg_lines(a, shot_every=3)[1] == "sound_shot     1249 3"
    assert MS.cfg_lines({"music": 918}) == ["music          918"]


def _payload(w1, w2):
    return struct.pack("<II", w1, w2)


def test_request_records_uses_the_build_mask():
    mask = 0xE0001FFF
    params = [{"idx": 7, "findkey": _payload(0x1234, 0x00000ABC)},
              {"idx": 8, "findkey": _payload(0x9999, 0x00000001)}]
    # the middle bits of w2 are outside the mask, so they must not matter
    sites = [Site(40, _payload(0x1234, 0x0ABC0ABC)), Site(41, _payload(0x9999, 0x00000001))]
    assert MS.request_records({5: [40], 6: [41]}, sites, params, mask) == {5: 7, 6: 8}
    with pytest.raises(MS.ModeSoundError):
        MS.request_records({5: [40, 41]}, sites, params, mask)            # two sids
    with pytest.raises(MS.ModeSoundError):
        MS.request_records({5: [40]}, sites, params, 0xFFFFFFFF)          # wrong mask: no record


GAME = r"C:\tmp\kaiju_premium\stock\game"
IMAGE = r"C:\tmp\kaiju_premium\stock\image.bin"


@pytest.mark.skipif(not (os.path.exists(GAME) and os.path.exists(IMAGE)),
                    reason="needs the Godzilla Premium 1.16 stock game ELF and image.bin")
def test_request_sids_on_premium_116():
    from pinball_decryptor.plugins.stern.info import container_counts
    with open(IMAGE, "rb") as f:
        fragments, _n = container_counts(f.read(0x100))
    fw = open(GAME, "rb").read()
    c = MS.carriers("godzilla_le", "1.16")
    sids = MS.request_sids(fw, fragments, list(c.calls) + list(c.music))
    assert all(len(s) == 1 for s in sids.values())
    assert len({s[0] for s in sids.values()}) == len(sids)
    assert MS.request_sids(fw, fragments, [1295])[1295] == [2325]    # item 130's measurement


def test_every_key_written_is_one_mode_file_c_reads():
    """The build writes sound_start / sound_shot / sound_end / music; mode_file.c must parse
    each (an unknown key is only logged and skipped, so a typo would fail silently)."""
    src = os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu", "modes", "sdk", "mode_file.c")
    text = open(src, encoding="utf-8").read()
    lines = MS.cfg_lines({"sound_start": 1, "sound_shot": 2, "sound_end": 3, "music": 4}, shot_every=2)
    for line in lines:
        assert 'key_is(line, "%s")' % line.split()[0] in text


def test_own_sound_lines_follow_the_spec():
    from pinball_decryptor.plugins.stern import mode_project as MP
    spec = MP.example("KAIJU RUSH")
    assert MS.wants(spec) == ()
    spec.sound_start, spec.music, spec.end_sound = "a.wav", "m.wav", "e.wav"
    assert MS.wants(spec) == ("sound_start", "sound_end", "music")
    carried = MS.assign_specs(spec.title, [spec])[0]
    assert MS.title_version(spec.title) == ("godzilla_pro", "1.15")
    lines = MP.own_sound_lines(spec, carried)
    assert [l.split()[0] for l in lines] == ["sound_start", "sound_end", "music"]
    assert MS.sound_files(spec, "F", carried) == {carried["sound_start"]: os.path.join("F", "a.wav"),
                                                  carried["sound_end"]: os.path.join("F", "e.wav"),
                                                  carried["music"]: os.path.join("F", "m.wav")}
    assert MP.own_sound_lines(spec, None) == []


def test_music_carriers_are_on_the_music_bus_and_not_played_by_terror_of_mechagodzilla():
    """918 and the TERRORLOOPs left the music list (fix-1): effects buses in RUN 1's dump, and
    Terror of Mechagodzilla plays 863-866 by name. 127 left too: RUN 9 heard the DJ Mixer start
    on it. 1295 stays out of both lists."""
    for key in (("godzilla_le", "1.16"), ("godzilla_pro", "1.15")):
        c = MS.carriers(*key)
        assert c.music == (125,)
        assert not {127, 863, 864, 865, 866, 918} & set(c.music)


def test_cfg_lines_carry_the_calls_own_lengths():
    a = {"sound_start": 1251, "sound_shot": 1249, "sound_end": 1133, "music": 125}
    ms = {"sound_start": 1000, "sound_shot": 850, "sound_end": 1200, "music": 12000}
    assert MS.cfg_lines(a, ms=ms) == ["sound_start    1251 1000", "sound_shot     1249 1 850",
                                      "sound_end      1133 1200", "music          125"]
    assert MS.cfg_lines(a, shot_every=2, ms={"sound_shot": 850})[1] == "sound_shot     1249 2 850"
    assert MS.cfg_lines(a, shot_every=2, ms={"sound_start": 5})[1] == "sound_shot     1249 2"
    assert MS.cfg_lines(a, ms={}) == MS.cfg_lines(a)


def _tone_wav(path, seconds, rate=22050, channels=2, width=2):
    import math
    import wave
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        v = int(8000 * math.sin(2 * math.pi * 440 * i / rate))
        frames += struct.pack("<h", v) * channels if width == 2 else bytes([(v >> 8) + 128]) * channels
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


def test_tile_wav_repeats_the_music_whole_past_the_carrier(tmp_path):
    """build_bank tiles music shorter than its carrier (fix-1): whole repeats, byte for byte,
    at least as long as asked, so the record loops the music with no silence in it."""
    import wave
    src = _tone_wav(str(tmp_path / "loop.wav"), 0.5)                   # 11025 frames at 22.05 kHz
    dst = str(tmp_path / "tiled.wav")
    reps = MS.tile_wav(src, dst, 57330)                                 # 1.3 s at 44.1 kHz
    assert reps == 3
    with wave.open(src, "rb") as a, wave.open(dst, "rb") as b:
        one = a.readframes(a.getnframes())
        assert (b.getnchannels(), b.getsampwidth(), b.getframerate()) == (2, 2, 22050)
        assert b.readframes(b.getnframes()) == one * 3
    assert MS.tile_wav(src, dst, 100) == 1
    assert MS.sound_ms(src) == 500 and MS.sound_ms(dst) == 500
    assert MS.sound_ms(str(tmp_path / "missing.wav")) is None


def test_call_ms_measures_only_the_calls(tmp_path):
    from pinball_decryptor.plugins.stern import mode_project as MP
    spec = MP.example("KAIJU RUSH")
    spec.sound_start = os.path.basename(_tone_wav(str(tmp_path / "s.wav"), 1.0, channels=1))
    spec.end_sound = os.path.basename(_tone_wav(str(tmp_path / "e.wav"), 0.25, channels=1))
    spec.music = os.path.basename(_tone_wav(str(tmp_path / "m.wav"), 0.5))
    assert MS.call_ms(spec, str(tmp_path)) == {"sound_start": 1000, "sound_end": 250}
    carried = {"sound_start": 1251, "sound_end": 1133, "music": 125}
    lines = MP.own_sound_lines(spec, carried, MS.call_ms(spec, str(tmp_path)))
    assert lines == ["sound_start    1251 1000", "sound_end      1133 250", "music          125"]


def test_mode_file_c_stops_a_call_after_its_own_length():
    """mode_file.c reads [ms] after each call's request and stops the carrier once it has played,
    every tick whether or not a mode runs (an end call outlives its mode)."""
    text = open(os.path.join(SDK, "mode_file.c"), encoding="utf-8").read()
    for field in ("S->start_ms = (unsigned)num(&a)", "S->shot_ms = (unsigned)num(&a)",
                  "S->end_ms = (unsigned)num(&a)"):
        assert field in text
    # every call goes through own_call (item 150 follow-up), which arms the stop when it plays
    for call in ("own_call(S->start, own_swap_of(S, S->start), S->start_ms,",
                 "own_call(S->shot, own_swap_of(S, S->shot), S->shot_ms,",
                 "own_call(S->end, own_swap_of(S, S->end), S->end_ms,"):
        assert call in text
    body = text[text.index("static void own_call("):text.index("static void own_calls_tick(")]
    assert "own_sounds_stop_after(request, ms);" in body
    tick = text[text.index("static void on_tick(void)"):]
    assert tick.index("own_sounds_stops_tick();") < tick.index("if (!run.active || !(M = run.slot)) return;")


SDK = os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu", "modes", "sdk")
PORT_ELFS ={"godzilla_le-1.16.port": GAME, "godzilla_pro-1.15.port": r"C:\tmp\godzilla_game.elf"}


def _port_data(port):
    out = {}
    for line in open(os.path.join(SDK, "ports", port), encoding="utf-8"):
        p = line.split()
        if len(p) >= 3 and p[0] == "data":
            out[p[1]] = int(p[2], 16)
    return out


def test_carrier_priorities_have_their_port_words():
    """Bus priority (item 150): mode_file.c sets its carriers through pm_sound_priority, which
    needs the request table and its count in the port - every port with sound sites has both."""
    text = open(os.path.join(SDK, "mode_file.c"), encoding="utf-8").read()
    # item 150 follow-up: the calls keep priorities 4 / 3 / 4 but no longer carry the steal flag
    assert "pm_sound_priority(calls[i], (int)own_prio[i], 0)" in text
    assert "own_prio[3] = { 4, 3, 4 };      /* start, shot, end */" in text
    assert "pm_sound_priority(S->music, -1, 0)" in text
    assert "int pm_sound_priority(unsigned request, int priority, int flags);" in \
        open(os.path.join(SDK, "pad_mode.h"), encoding="utf-8").read()
    for port in PORT_ELFS:
        words = _port_data(port)
        assert words.get("sound_requests") and words.get("sound_request_count"), port


def _elf_u32(elf, va):
    phoff, = struct.unpack_from("<I", elf, 0x1C)
    phnum, = struct.unpack_from("<H", elf, 0x2C)
    for i in range(phnum):
        p_type, p_off, p_va, _pa, p_filesz = struct.unpack_from("<5I", elf, phoff + 32 * i)
        if p_type == 1 and p_va <= va < p_va + p_filesz:
            return struct.unpack_from("<I", elf, p_off + va - p_va)[0]
    raise AssertionError("0x%x is in no loaded segment" % va)


@pytest.mark.skipif(not all(os.path.exists(p) for p in PORT_ELFS.values()),
                    reason="needs the Godzilla Premium 1.16 and Pro 1.15 game ELFs")
def test_request_table_words_read_the_worker_s_records():
    """The port words point where the worker reads: 2030 requests; music carrier 125 at priority
    1 with the steal flag (as the game's own tunes 66 / 67), call carrier 1249 at 2 without."""
    for port, path in PORT_ELFS.items():
        elf = open(path, "rb").read()
        words = _port_data(port)
        assert _elf_u32(elf, words["sound_request_count"]) == 2030, port
        table = words["sound_requests"]
        for req, prio_flags in ((125, 0x101), (66, 0x101), (67, 0x101), (1249, 0x2), (1251, 0x2)):
            word4 = _elf_u32(elf, table + 20 * req + 16)
            assert word4 & 0xFFFF == prio_flags, (port, req, hex(word4))
            assert _elf_u32(elf, table + 20 * req + 8) != 0, (port, req)


def test_assign_never_hands_out_a_carrier_already_taken():
    """Item 149 asks for one sound at a time, with every carrier already chosen in the build
    taken, so no carrier gets two sounds."""
    first = MS.assign("godzilla_le", "1.16", [("sound_start",)])[0]["sound_start"]
    again = MS.assign("godzilla_le", "1.16", [("sound_start",)], taken=[first])[0]["sound_start"]
    assert again != first and again in MS.TITLES[("godzilla_le", "1.16")].calls
    c = MS.TITLES[("godzilla_le", "1.16")]
    # the one music carrier holds no sound of its own (item 150 follow-up): taking it takes
    # nothing; a bed already holding a sound is never handed out again
    a = MS.assign("godzilla_le", "1.16", [("music",)], taken=list(c.music))[0]
    assert a == {"music": c.music[0], "music_sid": c.beds[0]}
    b = MS.assign("godzilla_le", "1.16", [("music",)], taken_beds=[c.beds[0]])[0]
    assert b["music_sid"] == c.beds[1]
    with pytest.raises(MS.ModeSoundError, match="no music bed left"):
        MS.assign("godzilla_le", "1.16", [("music",)], taken_beds=list(c.beds))
    # nothing taken: the assignment it always was
    assert MS.assign("godzilla_pro", "1.15", [("sound_start", "music")], taken=()) == \
        MS.assign("godzilla_pro", "1.15", [("sound_start", "music")])


# ---- item 150 follow-up: blip-free own sounds, a music bed of every mode's own -------------------
def _loop_clicks(path):
    """click-detector hits over two turns of a WAV (mode_sounds.clicks, the capture rule)"""
    import wave

    import numpy as np
    with wave.open(path, "rb") as w:
        ch, n = w.getnchannels(), w.getnframes()
        a = np.frombuffer(w.readframes(n), "<i2").astype(float).reshape(-1, ch) / 32768.0
    two = np.concatenate([a, a])
    return n, [i for c in range(ch) for i in MS.clicks(two[:, c])]


def _chord_wav(path, seconds, rate=44100, channels=2):
    """a chord that changes every 0.7 s: its end does not run into its start"""
    import math
    import wave
    n = int(seconds * rate)
    out = bytearray()
    for i in range(n):
        t = i / rate
        f = (220.0, 277.2, 330.0) if int(t / 0.7) % 2 == 0 else (246.9, 311.1, 370.0)
        v = int(9000 * sum(math.sin(2 * math.pi * x * t) for x in f) / 3)
        out += struct.pack("<h", v) * channels
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(out))
    return path


def test_every_title_with_music_has_beds_distinct_from_its_carriers():
    for key, first in ((("godzilla_le", "1.16"), 618), (("godzilla_pro", "1.15"), 257)):
        c = MS.carriers(*key)
        assert len(c.beds) == len(set(c.beds)) >= 6, key        # one bed for each film mode at least
        assert c.beds[0] == first                                  # the same 4.13 s record on both builds


@pytest.mark.skipif(not (os.path.exists(GAME) and os.path.exists(IMAGE)),
                    reason="needs the Godzilla Premium 1.16 stock game ELF and image.bin")
def test_no_request_names_a_bed_sid_on_premium_116():
    """A bed is a sid NO request of the build plays: the request table is read whole."""
    from pinball_decryptor.plugins.stern.info import container_counts
    from pinball_decryptor.plugins.stern.spike2 import sound_requests as SR
    with open(IMAGE, "rb") as f:
        fragments, _n = container_counts(f.read(0x100))
    fw = open(GAME, "rb").read()
    count, _table = SR.locate_sound_requests(fw, fragments)
    named = set()
    for sids in MS.request_sids(fw, fragments, list(range(1, count))).values():
        named |= set(sids)
    beds = set(MS.carriers("godzilla_le", "1.16").beds)
    assert not beds & named


def test_cfg_lines_name_a_mode_s_own_bed():
    a = {"sound_start": 1251, "music": 125, "music_sid": 618}
    assert MS.cfg_lines(a) == ["sound_start    1251", "music          125 618"]
    assert MS.cfg_lines({"music": 125}) == ["music          125"]


def test_assign_gives_every_mode_its_own_bed():
    a = MS.assign("godzilla_le", "1.16", [("music",), ("sound_start", "music"), ("music",)])
    beds = [x["music_sid"] for x in a]
    assert len(set(beds)) == 3 and all(x["music"] == 125 for x in a)
    assert beds == list(MS.carriers("godzilla_le", "1.16").beds[:3])


def test_loop_wav_makes_a_seamless_loop_on_the_10_ms_grid(tmp_path):
    """A music WAV whose end does not run into its start: the loop is cut where the audio after
    the cut matches the head, crossfaded, a whole number of 441-sample steps, repeated whole -
    and the click detector finds nothing over two turns of the result."""
    src = _chord_wav(str(tmp_path / "chords.wav"), 3.37)
    n_src, raw = _loop_clicks(src)
    assert [h for h in raw if abs(h - n_src) < 50], "the test's source must click at its own seam"
    dst = str(tmp_path / "loop.wav")
    reps, loop = MS.loop_wav(src, dst, 5 * 44100)
    assert loop % MS.LOOP_STEP == 0 and loop <= int(3.37 * 44100)
    assert reps == -(-5 * 44100 // loop)
    n, hits = _loop_clicks(dst)
    assert n == reps * loop
    # every seam (between the repeats, and the loop back to the start) is clean
    seams = [k * loop for k in range(1, 2 * reps + 1)]
    assert [h for h in hits if any(abs(h - s) < 50 for s in seams)] == []


def test_a_beds_record_fades_in_and_out_at_its_edges_and_its_tiles_stay_seamless(tmp_path):
    """The showcase run: a bed ENTERED at its loop head's full level (4 of 7 bed starts clicked in the
    rig). With edge_ms the record fades in at its head and out at its tail; every seam inside is the
    loop's own, and two turns of the record have no click (its own loop point is a dip)."""
    import wave

    import numpy as np
    src = _chord_wav(str(tmp_path / "chords.wav"), 3.37)
    dst = str(tmp_path / "bed.wav")
    reps, loop = MS.loop_wav(src, dst, 8 * 44100, edge_ms=MS.BED_EDGE_MS)
    plain = str(tmp_path / "plain.wav")
    MS.loop_wav(src, plain, 8 * 44100)
    with wave.open(dst, "rb") as a, wave.open(plain, "rb") as b:
        x = np.frombuffer(a.readframes(a.getnframes()), "<i2").astype(float).reshape(-1, a.getnchannels())
        y = np.frombuffer(b.readframes(b.getnframes()), "<i2").astype(float).reshape(-1, b.getnchannels())
    n = int(MS.BED_EDGE_MS * 44.1)
    assert len(x) == len(y) and np.abs(x[0]).max() < 2 and np.abs(x[-1]).max() < 2
    assert np.array_equal(x[n:len(x) - n], y[n:len(y) - n])       # the loop inside untouched
    assert np.abs(x[:n]).max() <= np.abs(y[:n]).max() + 1
    # the fades add no click the loop did not have (the test chord's own chord changes aside)
    _n, hits = _loop_clicks(dst)
    _n, plain_hits = _loop_clicks(plain)
    assert [h for h in hits if h not in plain_hits] == []


def test_loop_wav_keeps_a_seamless_source_as_it_is(tmp_path):
    """A source already on the grid that runs from its end into its start is not touched."""
    import math
    import wave
    n = 441 * 100                                   # 1.000 s, 441 Hz: whole periods
    with wave.open(str(tmp_path / "s.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 441 * i / 44100)))
                               for i in range(n)))
    reps, loop = MS.loop_wav(str(tmp_path / "s.wav"), str(tmp_path / "d.wav"), 2 * n)
    assert (reps, loop) == (2, n)
    with wave.open(str(tmp_path / "s.wav"), "rb") as a, wave.open(str(tmp_path / "d.wav"), "rb") as b:
        assert b.readframes(b.getnframes()) == a.readframes(a.getnframes()) * 2
    with pytest.raises(MS.ModeSoundError, match="too short to loop"):
        MS.loop_wav(_tone_wav(str(tmp_path / "t.wav"), 0.2), str(tmp_path / "x.wav"), 100)


def test_the_runtime_points_a_request_at_one_sid_and_fades():
    """pad_mode.h declares the item 150 follow-up calls and the runtime defines them: a request's
    sid list pointed at a list of ours and put back, a fade stepped from the tick, the channels."""
    h = open(os.path.join(SDK, "pad_mode.h"), encoding="utf-8").read()
    c = open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8").read()
    for decl in ("int pm_sound_sid(unsigned request, unsigned sid);",
                 "int pm_sound_fade(unsigned request, unsigned ms);",
                 "int pm_sound_playing(unsigned *requests, unsigned *buses, int max);"):
        assert decl in h
        assert decl[:-1] + "\n{" in c
    assert "*(unsigned *)(rec + 8) = (unsigned)(unsigned long)sid_slot[i].list;" in c
    assert "*(unsigned *)(rec + 8) = sid_slot[i].orig;" in c
    tick = c[c.index("static void on_tick(unsigned *r)"):]
    assert tick.index("sound_fades_tick();") < tick.index("m->tick();")
    assert "sound_fade_finish(request);" in c[c.index("int pm_sound(unsigned request)"):]


def test_the_godzilla_ports_carry_the_channel_and_voice_offsets():
    for port in PORT_ELFS:
        values = {}
        for line in open(os.path.join(SDK, "ports", port), encoding="utf-8"):
            p = line.split()
            if len(p) >= 3 and p[0] == "value":
                values[p[1]] = int(p[2], 0)
        assert {k: values.get(k) for k in ("sound_channel_count", "sound_channel_size", "sound_channel_request",
                                           "sound_channel_voices", "sound_channel_bus", "sound_channel_voice_ptrs",
                                           "sound_voice_volume")} == {
            "sound_channel_count": 8, "sound_channel_size": 196, "sound_channel_request": 184,
            "sound_channel_voices": 188, "sound_channel_bus": 189, "sound_channel_voice_ptrs": 92,
            "sound_voice_volume": 48}, port


def test_mode_file_c_plays_its_own_bed_and_never_cuts_a_sound():
    """mode_file.c (item 150 follow-up): `music <request> <sid>` points the carrier at the bed while
    the mode runs; the game's music is faded before ours and started again after ours has faded;
    a call waits for the voice bus instead of cutting a sound, and a shot call is skipped while its
    own previous call still sounds."""
    text = open(os.path.join(SDK, "mode_file.c"), encoding="utf-8").read()
    assert "S->music = (unsigned)num(&a); S->music_sid = (unsigned)num(&a);" in text
    assert "pm_sound_sid(S->music, S->music_sid)" in text
    assert "pm_sound_sid(music.after_request, 0);" in text
    end = text[text.index("static void own_sounds_end(struct slot *M)"):]
    assert "pm_sound_fade(S->music, MUSIC_FADE_OUT_MS)" in end and "pm_sound_stop(S->music)" not in end
    start = text[text.index("static void own_sounds_start(struct slot *M)"):]
    assert "pm_sound_fade(music.game, 250);" in start
    assert "pm_sound(music.after_game)" in text
    shot = text[text.index("static void own_sounds_shot(struct slot *M"):]
    assert "skipped - its previous call still sounds" in shot[:shot.index("\n}\n")]
    try_ = text[text.index("static int own_call_try("):text.index("static void own_call(")]
    assert "if (p < 0 || p >= (int)prio) return 0;" in try_ and "pm_sound_fade(reqs[i], 60);" in try_


def test_mode_file_c_fades_a_call_out_at_its_stop():
    """A call whose own sound is over is faded (40 ms) before it is stopped, never cut (item 150
    follow-up: a stop mid-sample is a click)."""
    text = open(os.path.join(SDK, "mode_file.c"), encoding="utf-8").read()
    stops = text[text.index("static void own_sounds_stops_tick(void)"):]
    stops = stops[:stops.index("\n}\n")]
    assert "pm_sound_fade(own_stops[i].request, 40)" in stops
    assert "pm_sound_stop(" not in stops


def test_a_bed_outlasts_its_mode():
    """A bed's record is repeated to the mode's seconds + BED_MARGIN_S, at most BED_MAX_S, never
    shorter than the stock record it grows: the engine's own restart of a record drops ~4 ms."""
    assert MS.bed_min_frames(25) == (25 + MS.BED_MARGIN_S) * 44100
    assert MS.bed_min_frames(0) == MS.BED_MARGIN_S * 44100
    assert MS.bed_min_frames(None, 5 * 44100) == 5 * 44100
    assert MS.bed_min_frames(10, 60 * 44100) == 60 * 44100
    assert MS.bed_min_frames(1000) == MS.BED_MAX_S * 44100


def test_an_appended_record_is_encoded_past_its_end_as_silence():
    """The machine plays the codec's lead-out block past `length - 200`; an appended record is
    encoded _APPENDED_TAIL samples longer (the codec object's length too) so that block is silence,
    not the scaffold's bytes."""
    import inspect
    from pinball_decryptor.plugins.stern import engine as E
    assert E._APPENDED_TAIL >= 200
    ob = bytearray(0x20)
    struct.pack_into("<I", ob, 0x10, 1000)
    p = {"length": 1000, "_rawobj": bytes(ob), "chan": 1}
    q = E._extended_row(p, E._APPENDED_TAIL)
    assert q["length"] == 1000 + E._APPENDED_TAIL
    assert struct.unpack_from("<I", q["_rawobj"], 0x10)[0] == 1000 + E._APPENDED_TAIL
    assert p["length"] == 1000 and struct.unpack_from("<I", p["_rawobj"], 0x10)[0] == 1000
    assert E._extended_row({"length": 7}, 3) == {"length": 10}
    src = inspect.getsource(E._chain_encode_appended)
    assert "_extended_row(p, _APPENDED_TAIL)" in src


def test_a_swapped_sound_writes_a_swap_line_for_its_carrier(tmp_path):
    """Item 163: the mode file names each swapped carrier with its stock key and the appended
    record's (``swap <request> <stock> <ours>``, read by mode_file.c and pad_mode_assets.h), only
    for a sound the mode has."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    spec = MP.example("KAIJU RUSH")
    spec.sound_start, spec.sound_shot, spec.end_sound, spec.music = "s.wav", "", "", ""
    carried = {"sound_start": 901, "music": 70,
               "swaps": [(901, "a20a51102c1c0020", "d1eaa8b4ae100000"), (70, "11" * 8, "22" * 8)]}
    lines = MP.own_sound_lines(spec, carried, {"sound_start": 1200})
    assert lines == ["sound_start    901 1200", "swap           901 a20a51102c1c0020 d1eaa8b4ae100000"]


def test_mode_file_c_and_code_modes_swap_the_carrier_key_right_before_playing():
    """Item 163: a call with a swap arms pm_sound_swap right before pm_sound and is NOT played when
    it cannot be armed; the music keeps its swap armed while the mode runs and lets it lapse after
    the fade. The runtime's lookup hook swaps by KEY (the worker thread looks it up later), and puts
    the carrier's priority back from its own tick."""
    text = open(os.path.join(SDK, "mode_file.c"), encoding="utf-8").read()
    body = text[text.index("static int own_call_try("):text.index("static void own_call(")]
    assert body.index("pm_sound_swap(request, swap, swap + 8,") < body.index("return pm_sound(request);")
    assert 'key_is(line, "swap")' in text
    assert "if (music.swap) pm_sound_swap(S->music, music.swap, music.swap + 8, -1, 0);" in text
    assets = open(os.path.join(SDK, "pad_mode_assets.h"), encoding="utf-8").read()
    assert 'pa_is(key, "swap")' in assets
    call = assets[assets.index("static PA_UNUSED int pa_call("):]
    assert call.index("pm_sound_swap(c->request, swap, swap + 8,") < call.index("pa_try(a, c->request")
    rt = open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8").read()
    hook = rt[rt.index("static void on_sound_lookup(unsigned *r)"):]
    assert hook.index("key_is(k, swaps[i].stock)") < hook.index("if (!sound_armed || !sound_key) return;")
    assert "sound_swaps_tick();" in rt
