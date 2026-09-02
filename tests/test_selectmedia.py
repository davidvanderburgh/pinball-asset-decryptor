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
    ok = {"w": 512, "h": 288, "frames": 30, "bytes": sm.GIF_MAX_BYTES, "delays_ms": [], "duration_ms": 0}
    assert sm.gif_fits(ok) is None
    assert "frames" in sm.gif_fits(dict(ok, frames=31))
    assert ">" in sm.gif_fits(dict(ok, bytes=sm.GIF_MAX_BYTES + 1))
    assert "x" in sm.gif_fits(dict(ok, w=640, h=360))


# ============================================================================ GIF planner
def test_gif_first_plan_clamps_size_and_frames(sm):
    p = sm.gif_first_plan((512, 288), 3, 10)
    assert (p.w, p.h, p.seconds, p.fps, p.frames) == (512, 288, 3.0, 10, 30)
    big = sm.gif_first_plan((1360, 768), 3, 10)
    assert big.w <= sm.GIF_MAX_W and big.h <= sm.GIF_MAX_H and big.w % 2 == 0
    assert abs(big.w / float(big.h) - 1360 / 768.0) < 0.02
    long = sm.gif_first_plan((512, 288), 5, 10)       # 50 frames asked
    assert long.frames <= sm.GIF_MAX_FRAMES and long.seconds == 5.0 and long.fps == 6
    very = sm.gif_first_plan((512, 288), 60, 10)      # even 1 fps is too many frames
    assert very.frames <= sm.GIF_MAX_FRAMES
    with pytest.raises(sm.Refused):
        sm.gif_first_plan((512, 288), 0, 10)


@pytest.mark.parametrize("size", [(512, 288), (384, 216), (256, 144), (500, 200)])
def test_gif_ladder_is_monotonic_bounded_and_finite(sm, size):
    """Every step strictly lowers cost, never exceeds the caps, ends at the floor."""
    lad = sm.gif_ladder(sm.gif_first_plan(size, 3, 10))
    assert lad[0] == sm.gif_first_plan(size, 3, 10)
    costs = [p.cost() for p in lad]
    assert all(a > b for a, b in zip(costs, costs[1:])), costs
    for p in lad:
        assert p.frames <= sm.GIF_MAX_FRAMES
        assert p.w <= sm.GIF_MAX_W and p.h <= sm.GIF_MAX_H
        assert p.w >= sm.GIF_MIN_W or p.w == lad[0].w
        assert p.fps >= sm.GIF_MIN_FPS and p.seconds >= sm.GIF_MIN_SECONDS
        assert p.w % 2 == 0 and p.h % 2 == 0
    assert sm.gif_shrink(lad[-1]) is None
    assert 1 <= len(lad) <= 20


def test_gif_ladder_order_rate_then_size_then_length(sm):
    lad = sm.gif_ladder(sm.gif_first_plan((512, 288), 3, 10))
    assert (lad[1].fps, lad[1].w) == (8, 512), "the first move is 10 -> 8 fps"
    assert lad[2].w < 512 and lad[2].fps == 8, "then the picture shrinks"
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
    assert sm.panel_size_for(2) == (512, 288)
    assert sm.panel_size_for(3) == (384, 216)
    assert sm.panel_size_for(4) == (256, 144)
    assert sm.panel_size_for(7) == (256, 144)
    assert sm.panel_size_for(1) == (512, 288)


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
    assert m == {"images": [{"art": "art0.png", "anim": None, "music": None},
                            {"art": "art1.png", "anim": "anim1.gif", "music": "music1.wav"}],
                 "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 50}
    assert sm.validate_manifest(json.loads(json.dumps(m))) == m
    assert sm.manifest_files(m) == ["art0.png", "art1.png", "anim1.gif", "music1.wav", "move.wav", "confirm.wav"]
    none = sm.build_manifest([(None, None, None)], None, None, 0)
    assert none["sound_move"] is None and none["images"][0]["art"] is None
    assert sm.manifest_files(none) == []


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
        f.write(tiny_gif(frames=31))               # one frame too many
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
    assert m == {"images": [{"art": None, "anim": None, "music": None}] * 2,
                 "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 35}
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
