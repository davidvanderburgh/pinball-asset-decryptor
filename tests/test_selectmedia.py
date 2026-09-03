"""selectmedia.py - the boot selector's media preparation tool (item 90 v2), pure-python parts.

Everything a card or ffmpeg is NOT needed for: the PNG trim, the GIF parser and
budget planner, the WAV contract, the synthetic sounds, the manifest shape, the
size defaults, the name and output refusals, and a `prepare` run fed with loose
files only (synthetic sounds, PIL art) that must produce a valid media.json.
The ffmpeg-backed encoders get one real run each where ffmpeg exists.
"""
import json
import os
import shutil
import struct
import sys
import wave
import zlib

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(RIG, "selectmedia.py")),
                                reason="selectmedia.py not present")

HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture()
def sm():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import selectmedia
    return selectmedia


def _no_src(m):
    """A manifest copy without the sound-SOURCE keys (sound_move_source /
    sound_confirm_source top-level, music_source per image), so a test can
    assert the media SHAPE against the pre-source expected dict and check
    the sources separately (item 90's changed-sound staleness)."""
    m = dict(m)
    m.pop("sound_move_source", None)
    m.pop("sound_confirm_source", None)
    m["images"] = [{k: v for k, v in im.items() if k != "music_source"}
                   for im in m["images"]]
    return m


# ---- helpers that build tiny media by hand ---------------------------------------------------
def _chunk(ctype, body):
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def tiny_png(w=4, h=3, rgba=(200, 40, 60, 255)):
    """A valid RGBA PNG of one colour, written by hand (no PIL)."""
    row = b"\x00" + bytes(rgba) * w
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(row * h)) + _chunk(b"IEND", b""))


def tiny_gif(frames=2, delay_cs=10, w=1, h=1, gce=True):
    """A minimal animated GIF: 1x1 frames, one global colour table, LZW bodies borrowed
    from the canonical smallest GIF."""
    out = bytearray(b"GIF89a" + struct.pack("<HHBBB", w, h, 0x80, 0, 0) + b"\x00\x00\x00\xff\xff\xff")
    for _ in range(frames):
        if gce:
            out += b"\x21\xf9\x04\x00" + struct.pack("<H", delay_cs) + b"\x00\x00"
        out += b"\x2c" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00" + b"\x02\x02\x44\x01\x00"
    out += b"\x3b"
    return bytes(out)


def write_wav(path, rate=44100, channels=2, seconds=0.05, sampwidth=2, amp=8000):
    n = int(rate * seconds)
    frames = bytearray()
    for i in range(n):
        v = amp if (i // 50) % 2 == 0 else -amp
        for _ in range(channels):
            frames += struct.pack("<h", v) if sampwidth == 2 else bytes([(v >> 8) & 0xFF])
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


# ============================================================================ PNG trim
def test_trim_png_cuts_the_slot_replace_padding(sm):
    """The 1987 card's logo is a 71,925-byte PNG zero-padded to the stock 379,645 bytes:
    everything after IEND+8 goes, a clean PNG comes back byte-identical."""
    png = tiny_png()
    padded = png + b"\x00" * 1000
    assert sm.trim_png(padded) == png
    assert sm.trim_png(png) == png
    assert sm.png_size(png) == (4, 3)


def test_trim_png_refuses_non_png_and_truncated(sm):
    with pytest.raises(sm.Refused):
        sm.trim_png(b"GIF89a" + b"\x00" * 40)
    png = tiny_png()
    with pytest.raises(sm.Refused):
        sm.trim_png(png[:-4])            # IEND chunk cut short


# ============================================================================ GIF parser
def test_gif_info_counts_frames_and_delays(sm):
    gi = sm.gif_info(tiny_gif(frames=3, delay_cs=10))
    assert (gi["w"], gi["h"], gi["frames"]) == (1, 1, 3)
    assert gi["delays_ms"] == [100, 100, 100]
    assert gi["duration_ms"] == 300


def test_gif_info_zero_delay_reads_as_the_selectors_100ms(sm):
    gi = sm.gif_info(tiny_gif(frames=2, delay_cs=0))
    assert gi["delays_ms"] == [sm.GIF_DEFAULT_DELAY_MS] * 2
    gi = sm.gif_info(tiny_gif(frames=2, gce=False))
    assert gi["delays_ms"] == [sm.GIF_DEFAULT_DELAY_MS] * 2


def test_gif_fits_reports_every_cap(sm):
    ok = {"w": 512, "h": 288, "frames": sm.GIF_MAX_FRAMES, "bytes": sm.GIF_MAX_BYTES,
          "delays_ms": [], "duration_ms": 0}
    assert sm.gif_fits(ok) is None
    assert "frames" in sm.gif_fits(dict(ok, frames=sm.GIF_MAX_FRAMES + 1))
    assert ">" in sm.gif_fits(dict(ok, bytes=sm.GIF_MAX_BYTES + 1))
    assert "x" in sm.gif_fits(dict(ok, w=640, h=360))


# ============================================================================ GIF planner
def test_the_contract_is_five_seconds_at_thirty(sm):
    """David, 2026-09-03: 'run at original fps (minimum 30fps would be
    ideal). we can limit them to 5 second clips' - the frame cap is the
    product of the two, and the byte cap clears a busy 5 s clip at 512x288
    (measured 7.65 MB)."""
    assert sm.GIF_MAX_SECONDS == 5.0 and sm.GIF_MAX_NATIVE_FPS == 30
    assert sm.GIF_MAX_FRAMES == 150
    assert sm.GIF_MAX_BYTES >= 8 << 20
    assert sm.GIF_MAX_FPS >= sm.GIF_MAX_NATIVE_FPS


def test_gif_first_plan_keeps_the_rate_and_cuts_the_length(sm):
    """An EXPLICIT ask past the caps loses LENGTH, never rate: 13 s at 30 fps
    is 5 s at 30 fps (the old rate-first clamp made it 13 s at 2 fps, which
    is what David saw)."""
    p = sm.gif_first_plan((512, 288), 3, 10)
    assert (p.w, p.h, p.seconds, p.fps, p.frames) == (512, 288, 3.0, 10, 30)
    big = sm.gif_first_plan((1360, 768), 3, 10)
    assert big.w <= sm.GIF_MAX_W and big.h <= sm.GIF_MAX_H and big.w % 2 == 0
    assert abs(big.w / float(big.h) - 1360 / 768.0) < 0.02
    davids = sm.gif_first_plan((384, 216), 13, 30)     # 390 frames asked
    assert (davids.fps, davids.seconds, davids.frames) == (30, 5.0, 150)
    long = sm.gif_first_plan((512, 288), 5, 10)        # 50 frames: fits whole now
    assert (long.seconds, long.fps, long.frames) == (5.0, 10, 50)
    fast = sm.gif_first_plan((512, 288), 5, 50)        # 250 frames asked: 3 s at 50
    assert fast.fps == 50 and fast.frames == sm.GIF_MAX_FRAMES and abs(fast.seconds - 3.0) < 1e-6
    assert sm.gif_first_plan((512, 288), 5, 120).fps == sm.GIF_MAX_FPS
    very = sm.gif_first_plan((512, 288), 60, 10)       # 60 s asked: the 5 s cap
    assert very.frames <= sm.GIF_MAX_FRAMES and very.seconds == 5.0 and very.fps == 10
    with pytest.raises(sm.Refused):
        sm.gif_first_plan((512, 288), 0, 10)


def test_gif_native_plan_keeps_the_rate_and_cuts_the_length(sm):
    """David: '10fps sucks... make it the original fps', then 'minimum 30fps
    would be ideal... 5 second clips'.  The native plan keeps the source's
    rate (up to 30) and gives the loop the whole 5 s."""
    # a 30 fps source: the rate is kept, the loop is the whole 5 s
    p = sm.gif_native_plan((384, 216), 30)
    assert (p.fps, p.frames) == (30, 150) and abs(p.seconds - 5.0) < 1e-6
    # ...or the source's own length when that is shorter (David's 3.7 s clip)
    short = sm.gif_native_plan((384, 216), 30, 3.7)
    assert short.fps == 30 and abs(short.seconds - 3.7) < 1e-6 and short.frames == 111
    # 24 fps -> 5 s at 24 fps, 120 frames (not throttled, not cut)
    q = sm.gif_native_plan((384, 216), 24)
    assert (q.fps, q.frames) == (24, 120)
    # a slow source keeps its slow rate and the whole 5 s
    slow = sm.gif_native_plan((384, 216), 8)
    assert slow.fps == 8 and abs(slow.seconds - 5.0) < 1e-6
    # a 60 fps source halves cleanly to 30; absurd rates clamp, never below the floor
    assert sm.gif_native_plan((384, 216), 60).fps == 30
    assert sm.gif_native_plan((384, 216), 240).fps == sm.GIF_MAX_NATIVE_FPS
    assert sm.gif_native_plan((384, 216), 1).fps == sm.GIF_MIN_FPS
    # a longer ask than the cap is the cap
    assert sm.gif_native_plan((384, 216), 30, 13.0).seconds == 5.0
    # size is clamped like the other planner
    big = sm.gif_native_plan((1360, 768), 30)
    assert big.w <= sm.GIF_MAX_W and big.h <= sm.GIF_MAX_H


@pytest.mark.skipif(not HAS_FFMPEG, reason="no ffmpeg")
def test_probe_fps_reads_the_sources_rate(sm, tmp_path):
    """probe_fps reads the real frame rate; a non-video returns the default."""
    import subprocess
    ff = shutil.which("ffmpeg")
    clip = str(tmp_path / "c.mp4")
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x64:rate=24:duration=1", clip],
                   check=True)
    assert abs(sm.probe_fps(clip, default=0) - 24) < 0.5
    assert sm.probe_fps(str(tmp_path / "nope.mp4"), default=7) == 7


@pytest.mark.parametrize("size", [(512, 288), (384, 216), (256, 144), (500, 200), (300, 170)])
@pytest.mark.parametrize("seconds,fps", [(5, 30), (3, 10), (1.7, 5), (5, 50), (2.5, 24)])
def test_gif_ladder_is_monotonic_bounded_and_finite(sm, size, seconds, fps):
    """Every step strictly lowers cost, never exceeds the caps, ends at the
    floor - including the 1.7 s / 5 fps corner where cutting to 1.5 s is the
    same 8 frames (that step is skipped, not re-encoded)."""
    lad = sm.gif_ladder(sm.gif_first_plan(size, seconds, fps))
    assert lad[0] == sm.gif_first_plan(size, seconds, fps)
    costs = [p.cost() for p in lad]
    assert all(a > b for a, b in zip(costs, costs[1:])), costs
    for p in lad:
        assert p.frames <= sm.GIF_MAX_FRAMES
        assert p.w <= sm.GIF_MAX_W and p.h <= sm.GIF_MAX_H
        assert p.w >= sm.GIF_MIN_W or p.w == lad[0].w
        assert p.fps >= sm.GIF_MIN_FPS
        assert p.seconds >= min(sm.GIF_MIN_SECONDS, lad[0].seconds)
        assert p.w % 2 == 0 and p.h % 2 == 0
    assert sm.gif_shrink(lad[-1]) is None
    assert 1 <= len(lad) <= 24


def test_gif_ladder_order_length_then_size_then_rate_last(sm):
    """THE RATE IS THE LAST THING TO GIVE (David: 'minimum 30fps would be
    ideal'): a 5 s / 30 fps clip that is over the byte cap loses a second
    first, then picture, and only then frame rate."""
    lad = sm.gif_ladder(sm.gif_first_plan((512, 288), 5, 30))
    assert [(p.seconds, p.w, p.fps) for p in lad[:4]] == \
        [(5.0, 512, 30), (4.0, 512, 30), (3.0, 512, 30), (2.0, 512, 30)]
    assert lad[4].w < 512 and lad[4].fps == 30, "then the picture shrinks"
    first_slower = next(i for i, p in enumerate(lad) if p.fps < 30)
    assert lad[first_slower - 1].w == 320 and lad[first_slower].fps == 24
    assert lad[-1] == sm.GifPlan(256, 144, 1.5, 5)


# ============================================================================ WAV contract + synth
def test_wav_contract(sm, tmp_path):
    good = write_wav(str(tmp_path / "g.wav"))
    assert sm.wav_contract_error(sm.wav_info(good)) is None
    mono = write_wav(str(tmp_path / "m.wav"), channels=1)
    assert sm.wav_contract_error(sm.wav_info(mono)) is None
    bad_rate = write_wav(str(tmp_path / "r.wav"), rate=48000)
    assert "48000" in sm.wav_contract_error(sm.wav_info(bad_rate))
    bad_width = write_wav(str(tmp_path / "w.wav"), sampwidth=1)
    assert "16-bit" in sm.wav_contract_error(sm.wav_info(bad_width))


def test_synth_click_and_chime_meet_the_contract(sm, tmp_path):
    for kind, secs in (("click", 0.040), ("chime", 0.400)):
        p = sm.synth_wav(kind, str(tmp_path / (kind + ".wav")))
        info = sm.wav_info(p)
        assert sm.wav_contract_error(info) is None
        assert info["channels"] == 2
        assert abs(info["seconds"] - secs) < 0.002
        peak, rms = sm.wav_stats(p)
        assert -8 < peak < -5, "the tones sit at about half scale"
        assert rms < peak
    with pytest.raises(sm.Refused):
        sm.synth_samples("buzz")


def test_apply_fade_ends_at_silence(sm):
    s = [10000] * 4410
    f = sm.apply_fade(s, 50)
    assert f[-1] == 0 and f[0] == 10000 and f[len(f) - 2205 + 1] < 10000


# ============================================================================ names, sizes, manifest
def test_panel_size_defaults(sm):
    # the selector's own card at 1360x768 (layout_compute mirrored): the
    # widest 16:9 the card allows, capped by the text block under it
    assert sm.panel_geometry(2) == (554, 294)
    assert sm.panel_geometry(3) == (341, 191)
    assert sm.panel_geometry(4) == (235, 132)
    assert sm.panel_size_for(2) == (522, 294)
    assert sm.panel_size_for(3) == (338, 190)
    assert sm.panel_size_for(4) == (234, 132)
    assert sm.panel_size_for(7) == (338, 190)
    assert sm.panel_size_for(1) == (522, 294)
    assert sm.panel_size_for(5) == (338, 190)
    for n in (1, 2, 3, 4, 5, 9):
        w, h = sm.panel_size_for(n)
        inner, art_h = sm.panel_geometry(n)
        assert w <= inner and h <= art_h and w % 2 == 0 and h % 2 == 0
        assert abs(w / float(h) - 16 / 9.0) < 0.03


def test_parse_size(sm):
    assert sm.parse_size("512x288") == (512, 288)
    assert sm.parse_size(" 384X216 ") == (384, 216)
    for bad in ("512", "512x", "axb", "4x4"):
        with pytest.raises(sm.Refused):
            sm.parse_size(bad)


@pytest.mark.parametrize("name", ["art0.png", "anim-1.gif", "My_Music.2.wav", "a"])
def test_media_names_accepted(sm, name):
    assert sm.check_media_name(name) == name


@pytest.mark.parametrize("name", ["", "sub/art.png", "sp ace.png", "..\\x", "ümlaut.png", "a;b"])
def test_media_names_refused(sm, name):
    with pytest.raises(sm.Refused):
        sm.check_media_name(name)


def test_manifest_shape_round_trips(sm):
    m = sm.build_manifest([("art0.png", None, None), ("art1.png", "anim1.gif", "music1.wav")],
                          "move.wav", "confirm.wav", 50)
    assert _no_src(m) == {
        "images": [{"art": "art0.png", "anim": None, "music": None, "confirm": None},
                   {"art": "art1.png", "anim": "anim1.gif", "music": "music1.wav", "confirm": None}],
        "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 50}
    # no sources were given, so the SOURCE keys are all null
    assert m["sound_move_source"] is None and m["sound_confirm_source"] is None
    assert sm.validate_manifest(json.loads(json.dumps(m))) == m
    assert sm.manifest_files(m) == ["art0.png", "art1.png", "anim1.gif", "music1.wav", "move.wav", "confirm.wav"]
    none = sm.build_manifest([(None, None, None)], None, None, 0)
    assert none["sound_move"] is None and none["images"][0]["art"] is None
    assert sm.manifest_files(none) == []


def test_manifest_carries_a_per_image_confirm(sm):
    """The image row's fourth field is that image's OWN confirm sound; a 3-field row
    (every older caller) still means 'falls back to the menu-wide one'.  The per-image
    file is a media name like any other: check_media_dir and the budget see it."""
    m = sm.build_manifest([("art0.png", None, None, "confirm0.wav"), ("art1.png", None, None)],
                          "move.wav", "confirm.wav", 50,
                          sources=[("auto", "none", "auto@350"), ("auto", "none")])
    got = {k: v for k, v in m["images"][0].items() if k != "music_source"}
    assert got == {
        "art": "art0.png", "anim": None, "music": None, "confirm": "confirm0.wav",
        "art_source": "auto", "anim_source": "none", "confirm_source": "auto@350"}
    assert m["images"][0]["music_source"] is None    # a 3-field source row
    assert m["images"][1]["confirm"] is None and m["images"][1]["confirm_source"] is None
    assert sm.validate_manifest(json.loads(json.dumps(m))) == m
    assert sm.manifest_files(m) == ["art0.png", "confirm0.wav", "art1.png", "move.wav", "confirm.wav"]
    with pytest.raises(sm.Refused):
        sm.build_manifest([("art0.png", None, None, "con firm0.wav")])
    for bad in ({"images": [{"art": None, "anim": None, "music": None, "confirm": "a/b.wav"}]},
                {"images": [{"art": None, "anim": None, "music": None, "confirm": 3}]},
                {"images": [{"art": None, "anim": None, "music": None, "confirm_source": 3}]},
                {"images": [{"art": None, "anim": None, "music": None, "confirm_wav": "x.wav"}]}):
        with pytest.raises(sm.Refused):
            sm.validate_manifest(bad)


@pytest.mark.parametrize("bad", [
    {"images": []},
    {"images": [{"art": "a/b.png", "anim": None, "music": None}]},
    {"images": [{"art": None, "anim": None, "music": None, "extra": 1}]},
    {"images": [{"art": None, "anim": None, "music": None}], "volume": 101},
    {"images": [{"art": None, "anim": None, "music": None}], "volume": "50"},
    {"images": [{"art": None, "anim": None, "music": None}], "sound_move": 3},
    {"images": "art0.png"},
])
def test_manifest_shape_refusals(sm, bad):
    with pytest.raises(sm.Refused):
        sm.validate_manifest(bad)


def test_build_manifest_refuses_bad_volume_and_names(sm):
    with pytest.raises(sm.Refused):
        sm.build_manifest([("art0.png", None, None)], volume=120)
    with pytest.raises(sm.Refused):
        sm.build_manifest([("art 0.png", None, None)])


def test_budget(sm):
    assert sm.check_budget({"a": 10, "b": 20}) == 30
    with pytest.raises(sm.Refused):
        sm.check_budget({"a": sm.MEDIA_BUDGET, "b": 1})


def test_parse_index_spec(sm):
    assert sm.parse_index_spec([], 3, "auto") == ["auto"] * 3
    assert sm.parse_index_spec(["1=x.gif"], 3, "none") == ["none", "x.gif", "none"]
    assert sm.parse_index_spec(["none", "2=auto"], 3, "auto") == ["none", "none", "auto"]
    for bad in (["3=auto"], ["-1=auto"], ["a=auto"]):
        with pytest.raises(sm.Refused):
            sm.parse_index_spec(bad, 3, "auto")


def test_split_source(sm, tmp_path):
    f = tmp_path / "card.raw"
    f.write_bytes(b"x")
    assert sm.split_source(str(f)) == (str(f), None)
    assert sm.split_source(str(f) + ":attract") == (str(f), "attract")
    with pytest.raises(sm.Refused):
        sm.split_source(str(tmp_path / "missing.raw") + ":attract")
    with pytest.raises(sm.Refused):
        sm.split_source(str(tmp_path / "missing.mov"))


def test_model_from_title(sm):
    assert sm.model_from_title("turtles_pro") == "pro"
    assert sm.model_from_title("king_kong_le") == "le"
    assert sm.model_from_title("godzilla_prem") == "prem"
    assert sm.model_from_title("jurassic_park_the_pin") == ""


# ============================================================================ output refusals
@pytest.mark.parametrize("out", ["/mnt/d/Pinball/images/x", "D:/Pinball/images/Stern/set",
                                 "D:\\Pinball\\images\\set"])
def test_refuses_output_under_the_card_library(sm, out):
    with pytest.raises(sm.Refused):
        sm.check_output_dir(out)


def test_accepts_other_outputs(sm, tmp_path):
    assert sm.check_output_dir(str(tmp_path / "set")) == str(tmp_path / "set")


# ============================================================================ check_media_dir
def _valid_set(sm, d):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "art0.png"), "wb") as f:
        f.write(tiny_png())
    with open(os.path.join(d, "anim0.gif"), "wb") as f:
        f.write(tiny_gif(frames=3))
    sm.synth_wav("click", os.path.join(d, "move.wav"))
    m = sm.build_manifest([("art0.png", "anim0.gif", None)], "move.wav", None, 40)
    with open(os.path.join(d, "media.json"), "w") as f:
        json.dump(m, f)
    return m


def test_check_media_dir_passes_a_valid_set(sm, tmp_path):
    d = str(tmp_path / "set")
    m = _valid_set(sm, d)
    lines = []
    assert sm.check_media_dir(d, log=lines.append) == m
    assert any("media.json OK" in l for l in lines)
    assert any("art0.png" in l and "PNG 4x3" in l for l in lines)
    assert any("anim0.gif" in l and "3 frames" in l for l in lines)


def test_check_media_dir_refusals(sm, tmp_path):
    d = str(tmp_path / "set")
    _valid_set(sm, d)
    with open(os.path.join(d, "art0.png"), "ab") as f:
        f.write(b"\x00" * 8)                       # bytes after IEND
    with pytest.raises(sm.Refused):
        sm.check_media_dir(d, log=lambda s: None)
    _valid_set(sm, d)
    os.remove(os.path.join(d, "move.wav"))         # named but missing
    with pytest.raises(sm.Refused):
        sm.check_media_dir(d, log=lambda s: None)
    _valid_set(sm, d)
    with open(os.path.join(d, "anim0.gif"), "wb") as f:
        f.write(tiny_gif(frames=sm.GIF_MAX_FRAMES + 1))     # one frame too many
    with pytest.raises(sm.Refused):
        sm.check_media_dir(d, log=lambda s: None)
    _valid_set(sm, d)
    write_wav(os.path.join(d, "move.wav"), rate=48000)
    with pytest.raises(sm.Refused):
        sm.check_media_dir(d, log=lambda s: None)
    shutil.rmtree(d)
    with pytest.raises(sm.Refused):
        sm.check_media_dir(d, log=lambda s: None)


# ============================================================================ the CLI
def test_cli_synth_and_info_and_check(sm, tmp_path, capsys):
    out = str(tmp_path / "c.wav")
    assert sm.main(["synth", "click", out]) == 0
    assert sm.main(["info", out]) == 0
    assert "44100 Hz 2ch" in capsys.readouterr().out
    d = str(tmp_path / "set")
    _valid_set(sm, d)
    assert sm.main(["check", d]) == 0
    assert sm.main(["check", str(tmp_path / "nowhere")]) == 2
    assert "refused" in capsys.readouterr().out


def test_cli_sound_refuses_without_a_card(sm, tmp_path, capsys):
    assert sm.main(["sound", str(tmp_path / "no.raw"), "1717", str(tmp_path / "x.wav")]) == 2
    assert "refused" in capsys.readouterr().out


def test_prepare_refuses_the_card_library(sm, tmp_path, capsys):
    rc = sm.main(["prepare", "--primary", str(tmp_path / "a.raw"), "--out", "D:/Pinball/images/set",
                  "--art", "none", "--sound-move", "none", "--sound-confirm", "none"])
    assert rc == 2
    assert "card library" in capsys.readouterr().out


def test_prepare_from_loose_files_without_a_card(sm, tmp_path, capsys):
    """Nothing 'auto' -> no card is ever opened: synthetic sounds, no art, the manifest
    still comes out in shape, the stale-file sweep and the check run."""
    out = str(tmp_path / "set")
    os.makedirs(out)
    with open(os.path.join(out, "art5.png"), "wb") as f:
        f.write(tiny_png())                        # a leftover from a bigger set
    rc = sm.main(["prepare", "--primary", "a.raw", "--extra", "b.raw", "--out", out,
                  "--art", "none", "--sound-move", "synth", "--sound-confirm", "synth", "--volume", "35"])
    text = capsys.readouterr().out
    assert rc == 0, text
    with open(os.path.join(out, "media.json")) as f:
        m = json.load(f)
    assert _no_src(m) == {
        "images": [{"art": None, "anim": None, "music": None, "confirm": None,
                    "art_source": "none", "anim_source": "none",
                    "confirm_source": None}] * 2,
        "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 35}
    # the menu sounds were rendered from 'synth', recorded so a change is seen
    assert m["sound_move_source"] == "synth" and m["sound_confirm_source"] == "synth"
    assert all(im["music_source"] == "none" for im in m["images"])
    assert sm.wav_contract_error(sm.wav_info(os.path.join(out, "move.wav"))) is None
    assert not os.path.exists(os.path.join(out, "art5.png")), "stale media swept"
    assert "removed stale art5.png" in text
    assert "media.json OK" in text


def test_prepare_music_from_a_wav_needs_no_ffmpeg_when_already_conformant(sm, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sm, "find_ffmpeg", lambda name="ffmpeg": None)
    out = str(tmp_path / "set")
    music = write_wav(str(tmp_path / "m.wav"), channels=1, seconds=0.2)
    rc = sm.main(["prepare", "--primary", "a.raw", "--out", out, "--art", "none",
                  "--music", "0=" + music, "--sound-move", "none", "--sound-confirm", "none"])
    assert rc == 0, capsys.readouterr().out
    info = sm.wav_info(os.path.join(out, "music0.wav"))
    assert info["channels"] == 2 and abs(info["seconds"] - 0.2) < 0.001
    bad = write_wav(str(tmp_path / "bad.wav"), rate=48000)
    rc = sm.main(["prepare", "--primary", "a.raw", "--out", out, "--art", "none",
                  "--music", "0=" + bad, "--sound-move", "none", "--sound-confirm", "none"])
    assert rc == 2 and "48000" in capsys.readouterr().out


# ============================================================================ ffmpeg-backed (real runs)
@pytest.mark.skipif(not HAS_FFMPEG, reason="no ffmpeg")
def test_scale_png_letterboxes_to_the_panel(sm, tmp_path):
    src = str(tmp_path / "src.png")
    with open(src, "wb") as f:
        f.write(tiny_png(40, 40))                  # square into a 16:9 panel
    out = str(tmp_path / "art.png")
    sm.scale_png(src, out, (64, 36))
    with open(out, "rb") as f:
        data = f.read()
    assert sm.png_size(data) == (64, 36)
    assert sm.trim_png(data) == data


@pytest.mark.skipif(not HAS_FFMPEG, reason="no ffmpeg")
def test_gif_fit_encodes_within_the_contract(sm, tmp_path):
    """A synthetic 2 s clip through the real two-pass recipe: frames = seconds*fps,
    the size is the plan's, the delay is 1/fps, and the file is a GIF the parser reads."""
    src = str(tmp_path / "src.mp4")
    ff = shutil.which("ffmpeg")
    import subprocess
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=128x72:rate=25",
                    "-pix_fmt", "yuv420p", src], check=True)
    out = str(tmp_path / "anim.gif")
    plan = sm.gif_first_plan((96, 54), 2, 10)
    info, used, tries = sm.gif_fit(src, out, plan, log=lambda s: None)
    assert tries == 1 and used == plan
    assert (info["w"], info["h"], info["frames"]) == (96, 54, 20)
    assert info["delays_ms"] == [100] * 20
    assert sm.gif_fits(info) is None


@pytest.mark.skipif(not HAS_FFMPEG, reason="no ffmpeg")
def test_normalise_wav_resamples_cuts_and_fades(sm, tmp_path):
    src = write_wav(str(tmp_path / "in.wav"), rate=48000, channels=1, seconds=1.0)
    out = str(tmp_path / "out.wav")
    sm.normalise_wav(src, out, max_seconds=0.5, fade_ms=100)
    info = sm.wav_info(out)
    assert sm.wav_contract_error(info) is None
    assert info["channels"] == 2 and abs(info["seconds"] - 0.5) < 0.01
    with wave.open(out, "rb") as w:
        w.setpos(w.getnframes() - 1)
        last = struct.unpack("<hh", w.readframes(1))
    assert max(abs(v) for v in last) < 200, "faded to silence"


# ============================================================================ v3: per-image specs
def test_anim_specs_parse_start_length_and_fps(sm):
    """'N=auto@START[:SECONDS[:FPS]]' and 'N=PATH@...' per image; the run's --start/
    --seconds/--fps fill what the spec leaves out; a bare value applies to every image."""
    vals = sm.parse_index_spec(["1=auto@12:2.5:8", "0=/x/clip.mp4@3"], 3, "none")
    a = [sm.parse_anim_spec(v, start=0.0, seconds=3.0, fps=10) for v in vals]
    # only start was pinned, so seconds/fps are free to follow the source
    assert a[0] == {"kind": "file", "source": "/x/clip.mp4", "start": 3.0, "seconds": 3.0, "fps": 10,
                    "seconds_explicit": False, "fps_explicit": False, "spec": "/x/clip.mp4@3"}
    # all three pinned
    assert a[1] == {"kind": "auto", "source": None, "start": 12.0, "seconds": 2.5, "fps": 8,
                    "seconds_explicit": True, "fps_explicit": True, "spec": "auto@12:2.5:8"}
    assert a[2] == {"kind": "none", "spec": "none"}
    bare = [sm.parse_anim_spec(v) for v in sm.parse_index_spec(["auto@1"], 2, "none")]
    assert [b["start"] for b in bare] == [1.0, 1.0] and [b["kind"] for b in bare] == ["auto", "auto"]
    assert all(not b["fps_explicit"] and not b["seconds_explicit"] for b in bare)
    # a bare 'auto' pins nothing: the defaults fill in, and both are free
    assert sm.parse_anim_spec("auto", 4, 2, 6) == {"kind": "auto", "source": None, "start": 4.0,
                                                   "seconds": 2.0, "fps": 6, "seconds_explicit": False,
                                                   "fps_explicit": False, "spec": "auto"}
    card = sm.parse_anim_spec("/d/card.raw:attract@20:2:8")
    assert card["kind"] == "file" and card["source"] == "/d/card.raw:attract"
    assert (card["start"], card["seconds"], card["fps"]) == (20.0, 2.0, 8)
    win = sm.parse_anim_spec("C:\\clips\\a.mp4@1.5")
    assert win["source"] == "C:\\clips\\a.mp4" and win["start"] == 1.5
    lit = sm.parse_anim_spec("/x/clip@home.mp4")           # a literal '@' in a name stays a path
    assert lit["source"] == "/x/clip@home.mp4" and lit["start"] == 0.0


@pytest.mark.parametrize("bad", ["auto@", "auto@x", "auto@-1", "auto@1:0", "auto@1:2:0", "none@3", "", "@3",
                                 "/x/clip.mp4@1:2:3:4"])
def test_anim_spec_refusals(sm, bad):
    with pytest.raises(sm.Refused):
        sm.parse_anim_spec(bad)


def test_art_specs_parse_stills_videos_and_frames(sm):
    vals = sm.parse_index_spec(["0=/x/clip.mp4@3", "2=/y/still.png"], 3, "auto")
    a = [sm.parse_art_spec(v) for v in vals]
    assert a[0] == {"kind": "video", "source": "/x/clip.mp4", "at": 3.0, "spec": "/x/clip.mp4@3"}
    assert a[1] == {"kind": "auto", "spec": "auto"}
    assert a[2] == {"kind": "file", "source": "/y/still.png", "spec": "/y/still.png"}
    assert sm.parse_art_spec("none") == {"kind": "none", "spec": "none"}
    assert sm.parse_art_spec("/x/Clip.MOV")["at"] == 0.0, "a bare video is its first frame"
    assert sm.parse_art_spec("/x/clip.mkv@0.5")["at"] == 0.5
    assert sm.parse_art_spec("/x/logo@2x.png") == {"kind": "file", "source": "/x/logo@2x.png", "spec": "/x/logo@2x.png"}
    for bad in ("/y/still.png@3", "/x/clip.mp4@", "/x/clip.mp4@1:2", "", "@3"):
        with pytest.raises(sm.Refused):
            sm.parse_art_spec(bad)


def test_still_kind_by_signature(sm, tmp_path):
    cases = {"p.png": tiny_png(), "j.jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 20, "g.gif": tiny_gif(),
             "b.bmp": b"BM" + b"\x00" * 20, "t.tif": b"II*\x00" + b"\x00" * 20,
             "w.webp": b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8}
    want = {"p.png": "PNG", "j.jpg": "JPEG", "g.gif": "GIF", "b.bmp": "BMP", "t.tif": "TIFF", "w.webp": "WebP"}
    for fn, data in cases.items():
        p = tmp_path / fn
        p.write_bytes(data)
        assert sm.still_kind(str(p)) == want[fn]
    raw = tmp_path / "card.raw"
    raw.write_bytes(b"\x00" * 4096)                  # a disk image's MBR area
    assert sm.still_kind(str(raw)) is None
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16)
    assert sm.still_kind(str(mp4)) is None


def test_prepare_refuses_a_non_image_as_art(sm, tmp_path, capsys):
    """A card handed in as art (or any non-image) is refused by signature before any
    decoder touches it - no ffmpeg, no PIL, no card open."""
    raw = tmp_path / "turtles.raw"
    raw.write_bytes(b"\x00" * 4096)
    out = str(tmp_path / "set")
    rc = sm.main(["prepare", "--visual-only", "--primary", "a.raw", "--out", out,
                  "--art", "0=" + str(raw), "--anim", "none"])
    text = capsys.readouterr().out
    assert rc == 2 and "refused" in text and "not a still image" in text and "VIDEO@T" in text
    assert not os.path.exists(os.path.join(out, "media.json"))
    rc = sm.main(["prepare", "--visual-only", "--primary", "a.raw", "--out", out,
                  "--art", "0=" + str(tmp_path / "missing.png"), "--anim", "none"])
    assert rc == 2 and "is not a file" in capsys.readouterr().out


# ============================================================================ v3: the sidecar cache
def test_cache_matches_on_source_mtime_size_and_params(sm, tmp_path):
    src = tmp_path / "src.png"
    src.write_bytes(tiny_png())
    stamp = sm.source_stamp(str(src))
    assert stamp["source"] == os.path.abspath(str(src)) and stamp["size"] == len(tiny_png())
    params = {"kind": "file", "size": (64, 36)}
    target = str(tmp_path / "art0.png")
    assert not sm.is_cached(target, stamp, params), "no target, no sidecar"
    with open(target, "wb") as f:
        f.write(tiny_png())
    assert not sm.is_cached(target, stamp, params), "a target without a sidecar is never trusted"
    sm.write_sidecar(target, stamp, params)
    assert os.path.isfile(target + sm.SIDECAR_SUFFIX)
    assert sm.is_cached(target, stamp, params)
    side = sm.read_sidecar(target)
    assert side["params"] == {"kind": "file", "size": [64, 36]}
    assert sm.cache_matches(side, stamp, {"kind": "file", "size": [64, 36]}), "tuple vs list is no difference"
    assert not sm.cache_matches(side, dict(stamp, mtime=stamp["mtime"] + 1), params), "mtime"
    assert not sm.cache_matches(side, dict(stamp, size=stamp["size"] + 1), params), "size"
    assert not sm.cache_matches(side, dict(stamp, source=stamp["source"] + ".x"), params), "path"
    assert not sm.cache_matches(side, stamp, {"kind": "file", "size": [32, 18]}), "params"
    assert not sm.cache_matches(side, stamp, {"kind": "video", "size": [64, 36], "at": 1.0}), "params"
    assert not sm.cache_matches(None, stamp, params) and not sm.cache_matches("junk", stamp, params)
    # the source rewritten (a new mtime, same size) -> a fresh stamp misses
    os.utime(str(src), (1000000000, 1000000000))
    assert not sm.is_cached(target, sm.source_stamp(str(src)), params)
    with open(target + sm.SIDECAR_SUFFIX, "w") as f:
        f.write("{not json")
    assert sm.read_sidecar(target) is None and not sm.is_cached(target, stamp, params)
    os.remove(target)
    sm.write_sidecar(target, stamp, params)
    assert not sm.is_cached(target, stamp, params), "a sidecar without its file"
    sm.drop_sidecar(target)
    sm.drop_sidecar(target)                          # twice is fine
    assert sm.read_sidecar(target) is None


def _fake_encoders(sm, monkeypatch, counts):
    """scale_png / gif_fit stand-ins that write tiny valid media and count their calls."""
    def fake_scale(src, out, size, seek=None):
        counts["art"] += 1
        with open(out, "wb") as f:
            f.write(tiny_png(*size))
        return out

    def fake_gif(src, out, plan, start=0.0, workdir=None, log=None):
        counts["anim"] += 1
        counts["last_plan"] = (plan, start)
        with open(out, "wb") as f:
            f.write(tiny_gif(frames=plan.frames))
        return sm.gif_info(open(out, "rb").read()), plan, 1

    monkeypatch.setattr(sm, "scale_png", fake_scale)
    monkeypatch.setattr(sm, "gif_fit", fake_gif)


def test_prepare_caches_art_and_anim_by_sidecar(sm, tmp_path, capsys, monkeypatch):
    """Run 1 generates and writes sidecars; run 2 (same sources, same specs) says 'cached'
    and calls no encoder; a touched source or a changed parameter regenerates just that
    file; media.json round-trips the spec strings."""
    counts = {"art": 0, "anim": 0}
    _fake_encoders(sm, monkeypatch, counts)
    still = tmp_path / "still.png"
    still.write_bytes(tiny_png())
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64)
    out = str(tmp_path / "set")
    anim_spec = "1=%s@12:2.5:8" % clip
    base = ["prepare", "--visual-only", "--primary", "a.raw", "--extra", "b.raw", "--out", out,
            "--art", "none", "--art", "0=" + str(still), "--anim", anim_spec, "--size", "64x36"]
    assert sm.main(base) == 0
    text = capsys.readouterr().out
    assert counts == {"art": 1, "anim": 1, "last_plan": counts["last_plan"]}
    plan, start = counts["last_plan"]
    assert (plan.w, plan.h, plan.seconds, plan.fps, start) == (64, 36, 2.5, 8, 12.0)
    assert "cached" not in text
    for fn in ("art0.png", "art0.png.src.json", "anim1.gif", "anim1.gif.src.json", "media.json"):
        assert os.path.isfile(os.path.join(out, fn)), fn
    with open(os.path.join(out, "anim1.gif.src.json")) as f:
        side = json.load(f)
    assert side["source"] == os.path.abspath(str(clip)) and side["size"] == clip.stat().st_size
    assert side["params"] == {"kind": "file", "clip": None, "size": [64, 36], "start": 12.0, "seconds": 2.5, "fps": 8}
    with open(os.path.join(out, "media.json")) as f:
        m = json.load(f)
    got = {k: v for k, v in m["images"][0].items() if k != "music_source"}
    assert got == {
        "art": "art0.png", "anim": None, "music": None, "confirm": None,
        "art_source": str(still), "anim_source": "none", "confirm_source": None}
    got = {k: v for k, v in m["images"][1].items() if k != "music_source"}
    assert got == {
        "art": None, "anim": "anim1.gif", "music": None, "confirm": None,
        "art_source": "none", "anim_source": "%s@12:2.5:8" % clip,
        "confirm_source": None}
    assert m["sound_move"] is None and m["sound_confirm"] is None
    assert sm.validate_manifest(m) == m
    # run 2: everything cached, no encoder called
    assert sm.main(base) == 0
    text = capsys.readouterr().out
    assert counts["art"] == 1 and counts["anim"] == 1
    assert "art0.png: cached" in text and "anim1.gif: cached" in text
    # the still rewritten -> only the art regenerates
    os.utime(str(still), (1000000000, 1000000000))
    assert sm.main(base) == 0
    text = capsys.readouterr().out
    assert counts["art"] == 2 and counts["anim"] == 1
    assert "art0.png: cached" not in text and "anim1.gif: cached" in text
    # a parameter change (fps) -> only the anim regenerates
    assert sm.main(base[:-4] + ["--anim", "1=%s@12:2.5:6" % clip, "--size", "64x36"]) == 0
    text = capsys.readouterr().out
    assert counts["art"] == 2 and counts["anim"] == 2
    assert "art0.png: cached" in text and "anim1.gif: cached" not in text
    # a panel size change -> both regenerate
    assert sm.main(base[:-1] + ["96x54"]) == 0
    assert counts["art"] == 3 and counts["anim"] == 3
    assert "cached" not in capsys.readouterr().out


def test_prepare_visual_only_skips_sounds_but_keeps_music(sm, tmp_path, capsys):
    out = str(tmp_path / "set")
    music = write_wav(str(tmp_path / "m.wav"), seconds=0.1)
    rc = sm.main(["prepare", "--visual-only", "--primary", "a.raw", "--extra", "b.raw", "--out", out,
                  "--art", "none", "--music", "1=" + music, "--sound-move", "synth", "--sound-confirm", "synth"])
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "sounds: skipped (--visual-only)" in text and "(visual only)" in text
    with open(os.path.join(out, "media.json")) as f:
        m = json.load(f)
    assert _no_src(m) == {
        "images": [{"art": None, "anim": None, "music": None, "confirm": None,
                    "art_source": "none", "anim_source": "none", "confirm_source": None},
                   {"art": None, "anim": None, "music": "music1.wav", "confirm": None,
                    "art_source": "none", "anim_source": "none", "confirm_source": None}],
        "sound_move": None, "sound_confirm": None, "volume": 50}
    # a --visual-only run renders no menu sound, so their sources are null too;
    # image 1's music DID render, so its source is recorded
    assert m["sound_move_source"] is None and m["sound_confirm_source"] is None
    assert m["images"][0]["music_source"] == "none"
    assert m["images"][1]["music_source"] not in (None, "none")
    assert not os.path.exists(os.path.join(out, "move.wav"))
    assert not os.path.exists(os.path.join(out, "confirm.wav"))
    assert sm.wav_contract_error(sm.wav_info(os.path.join(out, "music1.wav"))) is None


def test_manifest_accepts_sources_and_refuses_bad_ones(sm):
    m = sm.build_manifest([("art0.png", None, None)], sources=[("auto", "none")])
    got = {k: v for k, v in m["images"][0].items() if k != "music_source"}
    assert got == {
        "art": "art0.png", "anim": None, "music": None, "confirm": None,
        "art_source": "auto", "anim_source": "none", "confirm_source": None}
    assert m["images"][0]["music_source"] is None
    assert sm.validate_manifest(m) == m
    assert sm.manifest_files(m) == ["art0.png"]
    with pytest.raises(sm.Refused):
        sm.build_manifest([("art0.png", None, None)], sources=[])
    with pytest.raises(sm.Refused):
        sm.validate_manifest({"images": [{"art": None, "anim": None, "music": None, "art_source": 3}]})


# ============================================================================ v3: the sweep
def test_sweep_never_removes_what_the_manifest_names(sm, tmp_path):
    d = str(tmp_path / "set")
    os.makedirs(d)
    present = ["art0.png", "art1.png", "art5.png", "anim1.gif", "anim7.gif", "music1.wav", "music3.wav",
               "move.wav", "confirm.wav", "art0.png.src.json", "art5.png.src.json", "anim1.gif.src.json",
               "anim7.gif.src.json", "notes.txt", "media.json"]
    for fn in present:
        with open(os.path.join(d, fn), "wb") as f:
            f.write(b"x")
    m = sm.build_manifest([("art0.png", None, None), ("art1.png", "anim1.gif", "music1.wav")], "move.wav", "confirm.wav")
    removed = sm.sweep_stale(d, m, log=lambda s: None)
    assert sorted(removed) == ["anim7.gif", "anim7.gif.src.json", "art5.png", "art5.png.src.json", "music3.wav"]
    assert not set(removed) & set(sm.manifest_files(m))
    left = sorted(os.listdir(d))
    assert left == sorted(set(present) - set(removed))
    assert "art0.png.src.json" in left and "anim1.gif.src.json" in left, "a kept file keeps its sidecar"
    # a visual-only run says nothing about sounds: move/confirm/music stay, only art/anim leftovers go
    m2 = sm.build_manifest([("art0.png", None, None), (None, None, None)], None, None)
    removed = sm.sweep_stale(d, m2, visual_only=True, log=lambda s: None)
    assert sorted(removed) == ["anim1.gif", "anim1.gif.src.json", "art1.png"]
    for fn in ("move.wav", "confirm.wav", "music1.wav", "art0.png", "art0.png.src.json", "notes.txt", "media.json"):
        assert os.path.exists(os.path.join(d, fn)), fn


def test_check_ignores_sidecars(sm, tmp_path):
    d = str(tmp_path / "set")
    m = _valid_set(sm, d)
    for fn in ("art0.png.src.json", "anim0.gif.src.json", "art9.png.src.json"):
        with open(os.path.join(d, fn), "w") as f:
            f.write("{\"source\": \"/x\", \"mtime\": 1, \"size\": 1, \"params\": {}}")
    lines = []
    assert sm.check_media_dir(d, log=lines.append) == m
    assert not any("src.json" in l for l in lines)
    assert any(l.startswith("3 files,") for l in lines)


# ============================================================================ v4: per-image confirm
def test_sound_specs_mix_a_menu_wide_value_with_per_image_ones(sm):
    """--sound-confirm's two forms in one list: a BARE value is the menu-wide sound every
    image falls back to, 'N=' is image N's own.  This is where the sound flags differ from
    --art/--anim/--music, whose bare value applies to every image."""
    assert sm.parse_sound_specs([], 2, "auto") == ("auto", [None, None])
    assert sm.parse_sound_specs(["synth"], 2, "auto") == ("synth", [None, None])
    assert sm.parse_sound_specs(["1=/x/a.wav"], 2, "auto") == ("auto", [None, "/x/a.wav"])
    assert sm.parse_sound_specs(["none", "0=auto@350", "1=synth"], 2, "auto") == ("none", ["auto@350", "synth"])
    assert sm.parse_sound_specs(["0=a.wav", "synth", "0=b.wav", "none"], 1, "auto") == ("none", ["b.wav"])
    for bad in (["2=synth"], ["-1=synth"], ["x=synth"]):
        with pytest.raises(sm.Refused):
            sm.parse_sound_specs(bad, 2, "auto")
    # the older flags keep their meaning exactly
    assert sm.parse_index_spec(["none", "1=x.png"], 2, "auto") == ["none", "x.png"]
    assert sm.split_index_spec("1= auto ", 2) == (1, "auto")
    assert sm.split_index_spec("auto", 2) == (None, "auto")


def test_sound_spec_grammar(sm):
    """none | synth | auto | auto@IDX | PATH, with the same '@' rule --art uses: only
    digits after the '@' are parameters, so a path holding one stays a path."""
    assert sm.parse_sound_spec("none") == {"kind": "none", "source": None, "idx": None, "spec": "none"}
    assert sm.parse_sound_spec("synth") == {"kind": "synth", "source": None, "idx": None, "spec": "synth"}
    assert sm.parse_sound_spec("auto", 350) == {"kind": "auto", "source": None, "idx": 350, "spec": "auto"}
    assert sm.parse_sound_spec(" auto@1717 ", 350) == {"kind": "auto", "source": None, "idx": 1717,
                                                       "spec": "auto@1717"}
    assert sm.parse_sound_spec("/x/a.wav") == {"kind": "file", "source": "/x/a.wav", "idx": None,
                                               "spec": "/x/a.wav"}
    assert sm.parse_sound_spec("C:\\sfx\\hit@home.wav")["kind"] == "file"
    for bad in ("", "auto@", "auto@x", "auto@1.5", "auto@1:2", "synth@3", "none@3", "/x/a@12"):
        with pytest.raises(sm.Refused):
            sm.parse_sound_spec(bad)


def test_prepare_gives_one_image_its_own_confirm_and_falls_back_for_the_rest(sm, tmp_path, capsys, monkeypatch):
    """'--sound-confirm synth --sound-confirm 1=FILE': confirm.wav is the menu-wide
    fallback, confirm1.wav is image 1's own, media.json names both, and `check` (which
    prepare runs) validates the new file and counts it in the budget."""
    monkeypatch.setattr(sm, "find_ffmpeg", lambda name="ffmpeg": None)
    out = str(tmp_path / "set")
    own = write_wav(str(tmp_path / "own.wav"), seconds=0.3)
    base = ["prepare", "--primary", "a.raw", "--extra", "b.raw", "--out", out, "--art", "none",
            "--sound-move", "none"]
    rc = sm.main(base + ["--sound-confirm", "synth", "--sound-confirm", "1=" + own])
    text = capsys.readouterr().out
    assert rc == 0, text
    with open(os.path.join(out, "media.json")) as f:
        m = json.load(f)
    assert m["sound_confirm"] == "confirm.wav"
    assert m["images"][0]["confirm"] is None and m["images"][0]["confirm_source"] is None
    assert m["images"][1]["confirm"] == "confirm1.wav" and m["images"][1]["confirm_source"] == own
    assert sm.validate_manifest(m) == m
    assert sm.wav_contract_error(sm.wav_info(os.path.join(out, "confirm1.wav"))) is None
    assert os.path.isfile(os.path.join(out, "confirm1.wav.src.json"))
    assert "confirm1.wav: %s" % own in text
    assert "confirm=y +1 own" in text, "check's summary counts the per-image confirms"
    # 'N=none' means "no sound of its own": the image falls back, and the file it used to
    # have is swept because the manifest no longer names it
    rc = sm.main(base + ["--sound-confirm", "synth", "--sound-confirm", "1=none"])
    text = capsys.readouterr().out
    assert rc == 0, text
    with open(os.path.join(out, "media.json")) as f:
        m = json.load(f)
    got = {k: v for k, v in m["images"][1].items() if k != "music_source"}
    assert got == {
        "art": None, "anim": None, "music": None, "confirm": None,
        "art_source": "none", "anim_source": "none", "confirm_source": "none"}
    assert "removed stale confirm1.wav" in text and "removed stale confirm1.wav.src.json" in text
    assert not os.path.exists(os.path.join(out, "confirm1.wav"))
    assert os.path.isfile(os.path.join(out, "confirm.wav")), "the menu-wide one is untouched"


def test_prepare_caches_a_per_image_confirm_from_a_file(sm, tmp_path, capsys, monkeypatch):
    """Run 2 with the same source and parameters says 'cached' and re-encodes nothing;
    a touched source or a different file regenerates just that confirm."""
    monkeypatch.setattr(sm, "find_ffmpeg", lambda name="ffmpeg": None)
    real = sm.normalise_wav
    done = []

    def counting(src, out, max_seconds=None, fade_ms=0):
        done.append(src)
        return real(src, out, max_seconds, fade_ms)

    monkeypatch.setattr(sm, "normalise_wav", counting)
    out = str(tmp_path / "set")
    own = write_wav(str(tmp_path / "own.wav"), seconds=0.2)
    other = write_wav(str(tmp_path / "other.wav"), seconds=0.25)
    base = ["prepare", "--primary", "a.raw", "--out", out, "--art", "none", "--sound-move", "none",
            "--sound-confirm", "none"]
    assert sm.main(base + ["--sound-confirm", "0=" + own]) == 0, capsys.readouterr().out
    assert done == [own] and "cached" not in capsys.readouterr().out
    assert sm.main(base + ["--sound-confirm", "0=" + own]) == 0
    assert done == [own], "run 2 re-encodes nothing"
    assert "confirm0.wav: cached (%s)" % own in capsys.readouterr().out
    os.utime(own, (1000000000, 1000000000))
    assert sm.main(base + ["--sound-confirm", "0=" + own]) == 0
    assert done == [own, own], "a touched source regenerates"
    assert "cached" not in capsys.readouterr().out
    assert sm.main(base + ["--sound-confirm", "0=" + other]) == 0
    assert done == [own, own, other], "a different file regenerates"
    with open(os.path.join(out, "media.json")) as f:
        m = json.load(f)
    assert m["images"][0]["confirm_source"] == other and m["images"][0]["confirm"] == "confirm0.wav"
    assert abs(sm.wav_info(os.path.join(out, "confirm0.wav"))["seconds"] - 0.25) < 0.01
    capsys.readouterr()


def _fake_sound_sources(sm, monkeypatch, warm, opened, rendered):
    """SoundSource / render_sound stand-ins: no card, no emulator, but the same calls."""
    class FakeSource(object):
        def __init__(self, card, workdir=None, params_cache=None, log=None):
            if not os.path.isfile(card):
                raise sm.Refused("card image %s does not exist" % card)
            opened.append(os.path.basename(card))
            self.card = card
            self.warm = warm.get(os.path.basename(card), True)

        def close(self):
            pass

    def fake_render(src, idx, out, max_seconds=None, fade_ms=0):
        rendered.append((os.path.basename(src.card), idx, max_seconds, fade_ms))
        sm.synth_wav("click", out)
        return sm.wav_info(out)

    monkeypatch.setattr(sm, "SoundSource", FakeSource)
    monkeypatch.setattr(sm, "render_sound", fake_render)


def test_per_image_confirm_auto_pulls_that_images_own_card_and_caches_the_boot(sm, tmp_path, capsys, monkeypatch):
    """'1=auto' is image 1's OWN card, not the primary's (that is the whole point of a
    per-entry sound), 'auto@IDX' names another index of that card's catalog, and the
    sidecar keeps it so a second prepare never re-boots the emulator."""
    warm, opened, rendered = {}, [], []
    _fake_sound_sources(sm, monkeypatch, warm, opened, rendered)
    primary = str(tmp_path / "p.raw")
    extra = str(tmp_path / "e.raw")
    for p in (primary, extra):
        with open(p, "wb") as f:
            f.write(b"\x00" * 64)
    out = str(tmp_path / "set")
    base = ["prepare", "--primary", primary, "--extra", extra, "--out", out, "--art", "none",
            "--sound-move", "none", "--sound-confirm", "auto", "--sound-confirm", "1=auto@777"]
    assert sm.main(base) == 0, capsys.readouterr().out
    text = capsys.readouterr().out
    assert rendered == [("p.raw", sm.CONFIRM_IDX, sm.CONFIRM_SECONDS, sm.CONFIRM_FADE_MS),
                        ("e.raw", 777, sm.CONFIRM_SECONDS, sm.CONFIRM_FADE_MS)]
    assert "confirm1.wav: idx0777 of e.raw" in text
    with open(os.path.join(out, "confirm1.wav.src.json")) as f:
        side = json.load(f)
    assert side["source"] == os.path.abspath(extra)
    assert side["params"] == {"kind": "auto", "idx": 777, "seconds": sm.CONFIRM_SECONDS,
                              "fade_ms": sm.CONFIRM_FADE_MS}
    with open(os.path.join(out, "media.json")) as f:
        m = json.load(f)
    assert m["images"][1]["confirm"] == "confirm1.wav" and m["images"][1]["confirm_source"] == "auto@777"
    assert m["sound_confirm"] == "confirm.wav"
    # run 2: the per-image confirm is cached (no boot); the menu-wide one is not cached
    assert sm.main(base) == 0
    text = capsys.readouterr().out
    assert "confirm1.wav: cached (idx0777 of e.raw)" in text
    assert rendered[2:] == [("p.raw", sm.CONFIRM_IDX, sm.CONFIRM_SECONDS, sm.CONFIRM_FADE_MS)]
    assert opened == ["p.raw", "e.raw", "p.raw"], "a cached per-image confirm never opens the card"
    # a cold params cache falls back to the chime and leaves NO sidecar, so the run after
    # an Extract warms it picks the card's own sound up
    warm["e.raw"] = False
    os.utime(extra, (1000000000, 1000000000))
    assert sm.main(base) == 0
    text = capsys.readouterr().out
    assert "params cache is cold for e.raw; synthetic chime instead" in text
    assert not os.path.exists(os.path.join(out, "confirm1.wav.src.json"))
    assert sm.wav_contract_error(sm.wav_info(os.path.join(out, "confirm1.wav"))) is None
    with open(os.path.join(out, "media.json")) as f:
        assert json.load(f)["images"][1]["confirm"] == "confirm1.wav"


def test_per_image_confirm_refusals(sm, tmp_path, capsys):
    out = str(tmp_path / "set")
    base = ["prepare", "--primary", "a.raw", "--extra", "b.raw", "--out", out, "--art", "none",
            "--sound-move", "none"]
    rc = sm.main(base + ["--sound-confirm", "1=" + str(tmp_path / "missing.wav")])
    assert rc == 2 and "is not a file" in capsys.readouterr().out
    for bad, why in (("5=synth", "must be 0..1"), ("1=auto@", "catalog index"),
                     ("1=synth@3", "needs 'auto'"), ("1=", "empty")):
        rc = sm.main(base + ["--sound-confirm", bad])
        text = capsys.readouterr().out
        assert rc == 2 and why in text, (bad, text)
        assert not os.path.exists(os.path.join(out, "media.json")), bad


def test_sweep_keeps_a_per_image_confirm_the_manifest_names(sm, tmp_path):
    d = str(tmp_path / "set")
    os.makedirs(d)
    present = ["art0.png", "move.wav", "confirm.wav", "confirm1.wav", "confirm1.wav.src.json",
               "confirm3.wav", "confirm3.wav.src.json", "media.json"]
    for fn in present:
        with open(os.path.join(d, fn), "wb") as f:
            f.write(b"x")
    m = sm.build_manifest([("art0.png", None, None), (None, None, None, "confirm1.wav")],
                          "move.wav", "confirm.wav")
    removed = sm.sweep_stale(d, m, log=lambda s: None)
    assert sorted(removed) == ["confirm3.wav", "confirm3.wav.src.json"]
    assert not set(removed) & set(sm.manifest_files(m))
    for fn in ("confirm.wav", "confirm1.wav", "confirm1.wav.src.json"):
        assert os.path.exists(os.path.join(d, fn)), fn
    # a visual-only run says nothing about the sounds: every confirm stays
    m2 = sm.build_manifest([("art0.png", None, None), (None, None, None)], None, None)
    assert sm.sweep_stale(d, m2, visual_only=True, log=lambda s: None) == []
    assert os.path.exists(os.path.join(d, "confirm1.wav"))


def test_check_validates_a_per_image_confirm(sm, tmp_path):
    d = str(tmp_path / "set")
    _valid_set(sm, d)
    sm.synth_wav("chime", os.path.join(d, "confirm1.wav"))
    m = sm.build_manifest([("art0.png", "anim0.gif", None, "confirm1.wav")], "move.wav", None, 40)
    with open(os.path.join(d, "media.json"), "w") as f:
        json.dump(m, f)
    lines = []
    assert sm.check_media_dir(d, log=lines.append) == m
    assert any("confirm1.wav" in l and "44100 Hz 2ch" in l for l in lines)
    assert any("confirm=n +1 own" in l for l in lines)
    write_wav(os.path.join(d, "confirm1.wav"), rate=48000)
    with pytest.raises(sm.Refused):
        sm.check_media_dir(d, log=lambda s: None)
    os.remove(os.path.join(d, "confirm1.wav"))
    with pytest.raises(sm.Refused):
        sm.check_media_dir(d, log=lambda s: None)


# ============================================================================ v3: ffmpeg-backed
@pytest.mark.skipif(not HAS_FFMPEG, reason="no ffmpeg")
def test_art_from_a_video_frame(sm, tmp_path):
    """'VIDEO@T' -> the frame T seconds in, letterboxed to the panel; past the end refuses."""
    import subprocess
    src = str(tmp_path / "src.mp4")
    subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=duration=2:size=128x72:rate=25", "-pix_fmt", "yuv420p", src], check=True)
    out = str(tmp_path / "art.png")
    sm.scale_png(src, out, (64, 36), seek=1.0)
    with open(out, "rb") as f:
        data = f.read()
    assert sm.png_size(data) == (64, 36) and sm.trim_png(data) == data
    with pytest.raises(sm.Refused):
        sm.scale_png(src, str(tmp_path / "late.png"), (64, 36), seek=10.0)
    assert not os.path.exists(str(tmp_path / "late.png"))


def test_a_music_bed_is_a_loop_not_a_whole_track(sm, tmp_path):
    """A game's music track is minutes long and 176 KB a second, so ONE of
    them is over the whole media budget with nothing left for the pictures.
    David picked two off a card and the set came to 46.38 MB; the tool
    refused it and the preview simply stopped drawing, which is the wrong
    way round - the length is what should give, not the feature."""
    assert sm.MUSIC_MAX_SECONDS <= 30, "a menu bed is a phrase, not a song"
    # 176400 bytes a second, so the default cap has to leave room for the
    # pictures of a full 16-image card inside MEDIA_BUDGET
    per_bed = sm.MUSIC_MAX_SECONDS * sm.WAV_RATE * 2 * 2
    assert per_bed * 4 < sm.MEDIA_BUDGET


def test_the_music_spec_takes_an_optional_length(sm, tmp_path):
    """``PATH`` is the default cap and ``PATH@SECONDS`` asks for another -
    and a path that really does contain an '@' still names itself."""
    track = tmp_path / "track.wav"
    track.write_bytes(b"RIFF")
    assert sm.split_music_spec(str(track)) == (str(track),
                                               sm.MUSIC_MAX_SECONDS)
    assert sm.split_music_spec(str(track) + "@30") == (str(track), 30.0)
    odd = tmp_path / "gz@home - music.wav"
    odd.write_bytes(b"RIFF")
    assert sm.split_music_spec(str(odd)) == (str(odd), sm.MUSIC_MAX_SECONDS)
    # ...and nonsense after the '@' is part of the name, not a length
    assert sm.split_music_spec(str(track) + "@later")[1] ==         sm.MUSIC_MAX_SECONDS


def test_a_long_bed_is_cut_and_faded(sm, tmp_path, monkeypatch):
    """The cut is what keeps the set inside the budget, and the fade is what
    keeps the loop from clicking at the seam."""
    seen = {}

    def fake(src, out, max_seconds=None, fade_ms=0):
        seen["args"] = (src, max_seconds, fade_ms)
        with open(out, "wb") as f:
            f.write(b"RIFF")
        return out
    monkeypatch.setattr(sm, "normalise_wav", fake)
    monkeypatch.setattr(sm, "_duration_of", lambda p: 204.9)
    track = tmp_path / "long.wav"
    track.write_bytes(b"RIFF")
    out = tmp_path / "out"
    out.mkdir()
    sm.normalise_wav(str(track), str(out / "music0.wav"),
                     sm.MUSIC_MAX_SECONDS, sm.MUSIC_FADE_MS)
    src, secs, fade = seen["args"]
    assert src == str(track)
    assert secs == sm.MUSIC_MAX_SECONDS and fade == sm.MUSIC_FADE_MS
