"""Tests for :mod:`pinball_decryptor.plugins.stern.film_cut` - the movie cutter (item 142).

Everything runs on a SYNTHETIC 10 s film made with ``ffmpeg -f lavfi``, laid out like the
real ones (never a real film in the repo): a 2.4:1 picture with SAR 1:1 at 23.976 fps whose
border is RED for the first five seconds and BLUE after, a 5.1 AC3 track whose tone steps
up 100 Hz every second (quiet for five seconds, hot after), a cover PNG as a second video
stream (an attached picture) and a subtitle stream. So a cut can be checked for WHERE it
started (the colour, the pitch), for its crop (bars or none) and for picking the right
streams. Skipped cleanly without the app's ffmpeg, or when that ffmpeg cannot make it.
"""

import json
import os
import subprocess
import wave

import numpy as np
import pytest

from pinball_decryptor.core import audio
from pinball_decryptor.plugins.stern import film_cut as FC
from pinball_decryptor.plugins.stern import mode_assets as MA

W, H = 720, 300          # 2.4:1, like most of the films
FPS = "24000/1001"
RED, BLUE = (255, 0, 0), (0, 0, 255)
BORDER = 40              # px of coloured border around the test pattern
QUIET, HOT = 0.05, 0.9   # the tone's amplitude before and after 5 s


def tone_hz(t):
    """The synthetic film's tone at ``t`` seconds."""
    return 300 + 100 * int(t)


def make_film(folder, ffmpeg):
    """Write the synthetic film into ``folder`` and return its path (or None if this
    ffmpeg cannot make it: no lavfi, no libx264)."""
    os.makedirs(folder, exist_ok=True)
    film = os.path.join(folder, "synthetic_film.mp4")
    if os.path.isfile(film):
        return film
    srt = os.path.join(folder, "subs.srt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:04,000\nA SUBTITLE\n\n")
    video = ("testsrc2=s=%dx%d:r=%s:d=10,"
             "drawbox=x=0:y=0:w=iw:h=ih:t=%d:color=red:enable='lt(t,5)',"
             "drawbox=x=0:y=0:w=iw:h=ih:t=%d:color=blue:enable='gte(t,5)'"
             % (W, H, FPS, BORDER, BORDER))
    expr = "if(lt(t,5),%g,%g)*sin(2*PI*(300+100*floor(t))*t)" % (QUIET, HOT)
    sound = "aevalsrc=exprs='%s':s=48000:d=10:c=5.1" % "|".join([expr] * 6)
    plain = os.path.join(folder, "plain.mp4")
    cover = os.path.join(folder, "cover.png")
    base = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", video, "-f", "lavfi", "-i", sound]
    tail = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "ac3", "-t", "10"]

    def ok(cmd, out):
        r = subprocess.run(cmd, capture_output=True)
        good = r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0
        if not good and os.path.exists(out):
            os.remove(out)
        return good

    if not (ok(base + ["-i", srt, "-map", "0:v", "-map", "1:a", "-map", "2:s"] + tail
               + ["-c:s", "mov_text", plain], plain)
            or ok(base + ["-map", "0:v", "-map", "1:a"] + tail + [plain], plain)):
        return None
    # the cover goes in by a remux: encoding it in the same run as the picture makes
    # ffmpeg's mp4 muxer drop the H.264 stream (measured, ffmpeg 8.1.2)
    if (ok([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=64x64:d=1",
            "-frames:v", "1", "-update", "1", cover], cover)
            and ok([ffmpeg, "-v", "error", "-y", "-i", plain, "-i", cover, "-map", "0", "-map", "1",
                    "-c", "copy", "-disposition:v:1", "attached_pic", film], film)):
        return film
    os.replace(plain, film)
    return film


@pytest.fixture(scope="module")
def ff():
    p = audio.find_ffmpeg()
    if not p:
        pytest.skip("no ffmpeg")
    return p


@pytest.fixture(scope="module")
def film(ff, tmp_path_factory):
    path = make_film(str(tmp_path_factory.mktemp("film")), ff)
    if not path:
        pytest.skip("this ffmpeg cannot make the synthetic film (lavfi / libx264)")
    return path


def _streams(path):
    probe = audio.find_ffprobe()
    if not probe:
        pytest.skip("no ffprobe")
    r = subprocess.run([probe, "-v", "error", "-show_streams", "-count_frames", "-of", "json", path],
                       capture_output=True)
    return json.loads(r.stdout.decode("utf-8", "replace"))["streams"]


def _frame(ff, path, index=0):
    """Frame ``index`` of a clip as an (h, w, 3) array."""
    r = subprocess.run([ff, "-v", "error", "-i", path, "-vf", "select=eq(n\\,%d)" % index,
                        "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                       capture_output=True, check=True)
    info = [s for s in _streams(path) if s["codec_type"] == "video"][0]
    return np.frombuffer(r.stdout, np.uint8).reshape(info["height"], info["width"], 3)


def _near(px, rgb, tol=60):
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(px, rgb))


def _is_black(px, tol=24):
    return all(int(c) <= tol for c in px)


def _dominant_hz(samples, rate=44100):
    x = np.asarray(samples, np.float64)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1.0 / rate)[int(spec.argmax())])


# ---- times and spans (no ffmpeg) ------------------------------------------------------
@pytest.mark.parametrize("text,secs", [("95", 95.0), ("1:35", 95.0), ("01:35.5", 95.5),
                                        ("1:01:35", 3695.0), ("0:00", 0.0), (" 2:03 ", 123.0),
                                        ("7.25", 7.25)])
def test_parse_time_reads_mm_ss_and_h_mm_ss(text, secs):
    assert FC.parse_time(text) == pytest.approx(secs)


@pytest.mark.parametrize("text", ["", "abc", "1:75", "1:60:00", "-3", "1::2", "1:2:3:4", "1:-5"])
def test_parse_time_refuses_with_a_sentence(text):
    with pytest.raises(FC.FilmCutError) as e:
        FC.parse_time(text)
    assert str(e.value).endswith(".")


def test_format_time_round_trips():
    for secs in (0, 5, 59.5, 95, 3695, 7387.136):
        assert FC.parse_time(FC.format_time(secs)) == pytest.approx(secs, abs=0.001)
    assert FC.format_time(95) == "1:35" and FC.format_time(3695) == "1:01:35"
    assert FC.format_time(5.9996) == "0:06"


def test_span_problems():
    assert FC.span_problems(10, 6) == []
    assert FC.span_problems(10, 30, duration=100) == []
    assert "at most 30 seconds" in " ".join(FC.span_problems(0, 30.5))
    assert "more than zero" in " ".join(FC.span_problems(0, 0))
    assert "0:00 or later" in " ".join(FC.span_problems(-1, 5))
    assert "only 1:40 long" in " ".join(FC.span_problems(100, 5, duration=100))
    assert "past the end" in " ".join(FC.span_problems(97, 6, duration=100))


def test_level_raises_quiet_lowers_hot_and_limits_only_past_the_ceiling():
    rng = 32767.0
    t = np.arange(44100) / 44100.0
    quiet = (0.05 * rng * np.sin(2 * np.pi * 440 * t))[:, None]
    y, gain, limited = FC.level(quiet, rng)
    assert gain > 1 and not limited
    from pinball_decryptor.plugins.stern import engine as E
    assert E._active_rms(y, np) == pytest.approx(rng / FC.STOCK_CREST, rel=0.01)

    hot = (0.95 * rng * np.sign(np.sin(2 * np.pi * 440 * t)))[:, None]      # a square: crest 1
    y, gain, limited = FC.level(hot, rng)
    assert gain < 1 and not limited

    dead = (0.001 * rng * np.sin(2 * np.pi * 440 * t))[:, None]
    _y, gain, _l = FC.level(dead, rng)
    assert gain == pytest.approx(20.0)                                        # the absolute bound

    spiky = (0.02 * rng * np.sin(2 * np.pi * 440 * t))[:, None]
    spiky[1000] = 0.9 * rng                                                    # one transient
    y, gain, limited = FC.level(spiky, rng)
    assert limited and np.abs(y).max() < rng * FC.CEILING


def test_edge_fade_lands_both_edges_on_zero():
    a = np.full((44100, 2), 1000.0)
    y = FC.edge_fade(a)
    assert (y[0] == 0).all() and (y[-1] == 0).all()
    n = int(FC.EDGE_FADE_MS * 44.1)
    assert (y[n + 5:-n - 5] == 1000).all() and 0 < y[n // 2, 0] < 1000


# ---- the film --------------------------------------------------------------------------
def test_probe_reads_the_film_and_skips_its_cover(film):
    kinds = [(s["codec_type"], (s.get("disposition") or {}).get("attached_pic", 0))
             for s in _streams(film)]
    assert ("video", 1) in kinds and ("video", 0) in kinds and ("audio", 0) in kinds
    info = FC.probe(film)
    assert (info.width, info.height) == (W, H)                # not the 64x64 cover picture
    assert info.duration == pytest.approx(10.0, abs=0.1)
    assert info.fps == pytest.approx(23.976, abs=0.01)
    assert info.has_audio and info.audio_channels == 6
    assert "720x300" in info.summary() and "sound 6 ch" in info.summary()


def test_probe_without_ffprobe_reads_the_banner(film, monkeypatch):
    """The frozen macOS/Linux app bundles ffmpeg with no ffprobe: the probe falls back to
    the banner ``ffmpeg -i`` prints, and reads the film the same (not its cover)."""
    from pinball_decryptor.core import video
    monkeypatch.setattr(audio, "find_ffprobe", lambda *a, **k: None)
    monkeypatch.setattr(video, "find_ffprobe", lambda *a, **k: None)
    info = FC.probe(film)
    assert (info.width, info.height) == (W, H)
    assert info.duration == pytest.approx(10.0, abs=0.1)
    assert info.fps == pytest.approx(23.976, abs=0.01)
    assert info.has_audio and (info.audio_channels, info.audio_rate) == (6, 48000)


def test_probe_refuses_what_is_not_a_film(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("not a film")
    with pytest.raises(FC.FilmCutError):
        FC.probe(str(p))
    with pytest.raises(FC.FilmCutError):
        FC.probe(str(tmp_path / "missing.mp4"))


# ---- the clip ---------------------------------------------------------------------------
def test_cut_clip_is_the_bank_format_and_starts_where_asked(film, ff, tmp_path):
    out = str(tmp_path / "clip.mp4")
    FC.cut_clip(film, 2.0, 6.0, out, ff, crop="letterbox")
    streams = _streams(out)
    assert [s["codec_type"] for s in streams] == ["video"]                 # silent, no cover, no subs
    (v,) = streams
    assert v["codec_name"] == "h264" and v["profile"] == "Constrained Baseline"
    assert (v["width"], v["height"], v["pix_fmt"]) == (1360, 768, "yuv420p")
    assert v["r_frame_rate"] == "30/1" and int(v["nb_read_frames"]) == 180
    first = _frame(ff, out)
    assert _is_black(first[5, 680]) and _is_black(first[762, 680])        # the letterbox bars
    assert _near(first[384, 20], RED)                                       # the film's border, at 2 s
    assert not os.path.exists(out + ".part")


def test_cut_clip_fill_has_no_bars_and_a_late_start_is_blue(film, ff, tmp_path):
    out = str(tmp_path / "clip.mp4")
    FC.cut_clip(film, 6.0, 2.0, out, ff, crop="fill")
    (v,) = _streams(out)
    assert (v["width"], v["height"]) == (1360, 768) and int(v["nb_read_frames"]) == 60
    first = _frame(ff, out)
    assert _near(first[5, 680], BLUE) and _near(first[762, 680], BLUE)    # the border, not bars


def test_cut_clip_refuses_the_film_itself_and_long_spans(film, ff, tmp_path):
    before = os.path.getsize(film)
    with pytest.raises(FC.FilmCutError, match="overwrite the film"):
        FC.cut_clip(film, 0, 5, film, ff)
    with pytest.raises(FC.FilmCutError, match="at most 30"):
        FC.cut_clip(film, 0, 31, str(tmp_path / "c.mp4"), ff)
    with pytest.raises(FC.FilmCutError, match="letterbox or fill"):
        FC.cut_clip(film, 0, 2, str(tmp_path / "c.mp4"), ff, crop="stretch")
    assert os.path.getsize(film) == before


# ---- the sound --------------------------------------------------------------------------
def test_cut_sound_is_the_record_shape_levelled_and_faded(film, ff, tmp_path):
    out = str(tmp_path / "end.wav")
    res = FC.cut_sound(film, 3.0, 1.5, out, ff, channels=1)             # all in the quiet half
    with wave.open(out, "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 44100)
        pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.int64)
    assert abs(len(pcm) - int(1.5 * 44100)) <= 64 and res.frames == len(pcm)
    assert res.gain_db > 0                                                    # quiet, raised
    rng = FC.PEAK_RANGE[1]
    assert np.abs(pcm).max() < rng * FC.CEILING
    assert pcm[0] == 0 and pcm[-1] == 0
    head = pcm[int(0.05 * 44100):int(0.45 * 44100)]
    assert _dominant_hz(head) == pytest.approx(tone_hz(3.0), abs=5)          # starts where asked
    from pinball_decryptor.plugins.stern import engine as E
    a, ch, sr = E._read_wav_any(out, np)
    assert (ch, sr) == (1, 44100) and len(a) == len(pcm)
    assert len(E._load_wav(out, False, np)) == len(pcm)


def test_cut_sound_hot_span_is_lowered_and_stereo_works(film, ff, tmp_path):
    out = str(tmp_path / "end.wav")
    res = FC.cut_sound(film, 6.0, 2.0, out, ff, channels=2)
    assert res.gain_db < 0 and res.channels == 2
    with wave.open(out, "rb") as w:
        assert (w.getnchannels(), w.getframerate()) == (2, 44100)
        pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2)
    assert (pcm[0] == 0).all() and (pcm[-1] == 0).all()
    assert _dominant_hz(pcm[int(0.05 * 44100):int(0.45 * 44100), 0]) == pytest.approx(tone_hz(6.0), abs=5)


def test_cut_sound_refuses(film, ff, tmp_path):
    with pytest.raises(FC.FilmCutError, match="mono or stereo"):
        FC.cut_sound(film, 0, 2, str(tmp_path / "e.wav"), ff, channels=6)
    with pytest.raises(FC.FilmCutError, match="overwrite the film"):
        FC.cut_sound(film, 0, 2, film, ff)


# ---- a still and a preview --------------------------------------------------------------
def test_grab_still_is_screen_art_of_the_right_moment(film, ff, tmp_path):
    out = str(tmp_path / "art.png")
    w, h = FC.grab_still(film, 7.0, out, ff)
    assert w == 640 and h % 4 == 0 and abs(h - 640 * H / W) <= 4
    art = MA.load_art(out)
    assert art.shape == (h, w, 4)                                             # load_art keeps the size
    assert _near(art[h // 2, 10, :3], BLUE)
    w2, h2 = FC.grab_still(film, 1.0, out, ff, crop="fill")
    assert w2 == 640 and h2 % 4 == 0 and abs(h2 - 640 * 768 / 1360) <= 4
    assert _near(MA.load_art(out)[4, 320, :3], RED)


def test_grab_still_joins_the_stock_hud(film, ff, tmp_path):
    from pinball_decryptor.plugins.stern import scene_write as SW
    from tests.test_stern_mode_assets import HUD
    if not os.path.exists(HUD):
        pytest.skip("stock HUD scene not present")
    out = str(tmp_path / "art.png")
    FC.grab_still(film, 2.0, out, ff)
    new, infos = SW.add_screens(open(HUD, "rb").read(),
                                [dict(name="PadMode_film_Screen", art_rgba=MA.load_art(out),
                                      words="1,000,000 A SHOT")])
    assert b"PadMode_film_Screen" in new and len(infos) == 1


def test_preview_frame_shows_the_crop_at_the_start(film, ff):
    img = FC.preview_frame(film, 2.0, ff, box=(480, 270), crop="letterbox")
    assert img.size == FC.preview_size((480, 270)) and img.mode == "RGB"
    px = np.asarray(img)
    assert _is_black(px[1, img.width // 2]) and _near(px[img.height // 2, 3], RED)
    fill = np.asarray(FC.preview_frame(film, 6.0, ff, box=(480, 270), crop="fill"))
    assert _near(fill[1, fill.shape[1] // 2], BLUE)


def test_peak_range_is_the_sound_codecs_own():
    """A cut is levelled into the codec's range: the sound path takes a WAV's samples as
    they are, and a full-scale cut decoded clipped (item 142, measured)."""
    from pinball_decryptor.plugins.stern import engine as E
    assert FC.PEAK_RANGE == {1: E._MONO_RANGE, 2: E._STEREO_RANGE}


# ---- black bars burned into a film --------------------------------------------------------
def make_barred_film(folder, ffmpeg):
    """A 4 s film whose 720x300 picture sits inside black bars burned into a 720x404 frame,
    like the 1920x1080 Showa transfers. None if this ffmpeg cannot make it."""
    os.makedirs(folder, exist_ok=True)
    film = os.path.join(folder, "barred_film.mp4")
    if os.path.isfile(film):
        return film
    video = ("testsrc2=s=%dx%d:r=%s:d=4,drawbox=x=0:y=0:w=iw:h=ih:t=%d:color=red,"
             "pad=%d:404:0:52:black" % (W, H, FPS, BORDER, W))
    r = subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", video, "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", film], capture_output=True)
    return film if r.returncode == 0 and os.path.isfile(film) else None


@pytest.fixture(scope="module")
def barred(ff, tmp_path_factory):
    path = make_barred_film(str(tmp_path_factory.mktemp("barred")), ff)
    if not path:
        pytest.skip("this ffmpeg cannot make the barred film")
    return path


def test_detect_picture_finds_burned_in_bars_and_fill_leaves_them_out(barred, film, ff, tmp_path):
    pic = FC.detect_picture(barred, ff)
    assert pic is not None
    w, h, x, y = pic
    assert abs(w - W) <= 2 and abs(h - H) <= 4 and x <= 2 and abs(y - 52) <= 4
    assert FC.detect_picture(film, ff) is None                              # no bars, no crop
    out = str(tmp_path / "clip.mp4")
    FC.cut_clip(barred, 1.0, 1.0, out, ff, crop="fill", picture=pic)
    first = _frame(ff, out)
    assert _near(first[3, 680], RED) and _near(first[764, 680], RED)       # the border, not the bars
    FC.cut_clip(barred, 1.0, 1.0, out, ff, crop="fill")                     # without it: the bars
    assert _is_black(_frame(ff, out)[3, 680])
    png = str(tmp_path / "art.png")
    sw, sh = FC.grab_still(barred, 1.0, png, ff, picture=pic)
    assert sw == 640 and abs(sh - 640 * H / W) <= 4
    assert _near(MA.load_art(png)[2, 320, :3], RED)


def test_detect_picture_unites_samples_and_refuses_what_is_not_bars(monkeypatch, tmp_path):
    """A dark scene makes ONE sample's box smaller; the union of every sample is the
    picture. No bars, or a box too small to be bars, is None."""
    fake = tmp_path / "f.mp4"
    fake.write_bytes(b"x")
    monkeypatch.setattr(FC, "probe", lambda p: FC.FilmInfo(path=p, duration=6000, width=1920, height=1080))

    def run_with(crops):
        it = iter(crops)

        class R:
            def __init__(self):
                self.stderr = b"[Parsed_cropdetect_0] x1:0 crop=%s\n" % next(it).encode()
        monkeypatch.setattr(FC.subprocess, "run", lambda *a, **k: R())
        return FC.detect_picture(str(fake), "ffmpeg")

    assert run_with(["1920:800:0:140", "1920:800:0:140", "1200:400:360:340",
                     "1920:800:0:140", "1920:800:0:140"]) == (1920, 800, 0, 140)
    assert run_with(["1920:1080:0:0"] * 5) is None
    assert run_with(["1920:1076:0:2"] * 5) is None
    assert run_with(["400:300:760:390"] * 5) is None


# ---- the command line -------------------------------------------------------------------
def test_cli_cuts_into_its_folder_only_and_never_beside_the_film(film, ff, tmp_path, capsys):
    out = str(tmp_path / "cuts")
    assert FC.main([film, "--out-dir", out, "--from", "0:02", "--length", "3", "--crop", "fill",
                    "--clip", "--sound", "--still", "0:07"]) == 0
    assert sorted(os.listdir(out)) == ["art.png", "clip.mp4", "end.wav"]
    text = capsys.readouterr().out
    assert "clip.mp4: 0:02 for 3 s, fill" in text and "art.png: the frame at 0:07, 640x" in text
    (v,) = _streams(os.path.join(out, "clip.mp4"))
    assert int(v["nb_read_frames"]) == 90
    assert FC.main([film, "--out-dir", out, "--clip"]) == 2                      # no silent overwrite
    assert "use --force" in capsys.readouterr().out
    assert FC.main([film, "--out-dir", out, "--clip", "--force"]) == 0
    before = sorted(os.listdir(os.path.dirname(film)))
    assert FC.main([film, "--out-dir", os.path.dirname(film), "--clip"]) == 2
    assert "film's own folder" in capsys.readouterr().out
    assert sorted(os.listdir(os.path.dirname(film))) == before
    assert FC.main([film, "--out-dir", out]) == 2
    assert FC.main([film, "--out-dir", out, "--from", "0:08", "--clip", "--force"]) == 2
