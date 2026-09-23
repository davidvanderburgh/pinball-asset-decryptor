"""Tests for the "From a film" dialog's logic, :class:`webui.modes_filmcut.FilmCutForm`
(item 142). The form is driven directly: no window is ever shown. The film is the
synthetic lavfi one from ``tests/test_stern_film_cut.py``; tests needing it skip without
the app's ffmpeg.
"""

import os
import tempfile
import wave

import numpy as np
import pytest

from pinball_decryptor.core import audio
from pinball_decryptor.webui import modes_filmcut as D
from pinball_decryptor.webui.modes_filmcut import PROVENANCE, FilmCutForm, describe
from pinball_decryptor.plugins.stern import film_cut as FC
from pinball_decryptor.plugins.stern import mode_assets as MA
from pinball_decryptor.plugins.stern import mode_project as MP
from tests.test_stern_film_cut import BLUE, RED, _is_black, _near, _streams, make_film


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


# ---- without a film ---------------------------------------------------------------------
def test_problems_name_what_is_missing(tmp_path):
    assert FilmCutForm().problems() == ["Choose a film."]
    f = FilmCutForm(film=str(tmp_path / "missing.mp4"), take_clip=False)
    assert "Tick at least one" in f.problems()[0]
    f = FilmCutForm(film=str(tmp_path / "missing.mp4"), start="1:75", length="x")
    text = " ".join(f.problems())
    assert "Start:" in text and "Length:" in text and "There is no film" in text


def test_spans_follow_the_takes():
    f = FilmCutForm(film="x.mp4", start="1:00", length="6", take_clip=True, take_sound=True,
                    take_still=True)
    assert f.spans() == ([], {"clip": (60.0, 6.0), "sound": (60.0, 6.0), "still": 60.0})
    f.sound_same, f.sound_start, f.sound_length, f.still_at = False, "1:02.5", "4", "1:03"
    assert f.spans() == ([], {"clip": (60.0, 6.0), "sound": (62.5, 4.0), "still": 63.0})
    f.take_clip = False
    assert "clip" not in f.spans()[1]


def test_from_spec_reopens_on_the_last_cut():
    spec = MP.ModeSpec(clip_source="D:/Films/G.mp4", clip_from=5700.0, clip_length=6.0,
                       art_source="D:/Films/G.mp4", art_from=5703.5)
    f = FilmCutForm.from_spec(spec, "clip")
    assert (f.film, f.start, f.length, f.take_clip, f.take_sound, f.take_still) == (
        "D:/Films/G.mp4", "1:35:00", "6", True, False, False)
    f = FilmCutForm.from_spec(spec, "still")
    assert f.take_still and not f.take_clip and f.still_at == "1:35:03.5"
    assert FilmCutForm.from_spec(MP.ModeSpec(), "sound").film == ""


def test_from_spec_opens_on_the_cut_of_the_kind_opened():
    """A mode whose clip and sound came from different spans reopens each on its own span,
    and the crop the cut used comes back."""
    spec = MP.ModeSpec(clip_source="D:/Films/G.mp4", clip_from=5700.0, clip_length=6.0, clip_crop="fill",
                       sound_source="D:/Films/M.mp4", sound_from=600.0, sound_length=4.0,
                       art_source="D:/Films/G.mp4", art_from=5703.5, art_crop="letterbox")
    f = FilmCutForm.from_spec(spec, "sound")
    assert (f.film, f.start, f.length, f.take_sound, f.take_clip) == ("D:/Films/M.mp4", "10:00", "4", True, False)
    f = FilmCutForm.from_spec(spec, "clip")
    assert (f.film, f.start, f.length, f.crop) == ("D:/Films/G.mp4", "1:35:00", "6", "fill")
    f = FilmCutForm.from_spec(spec, "still")
    assert (f.film, f.start, f.still_at, f.crop) == ("D:/Films/G.mp4", "1:35:03.5", "1:35:03.5", "letterbox")
    only_clip = MP.ModeSpec(clip_source="D:/Films/G.mp4", clip_from=60.0, clip_length=5.0, clip_crop="fill")
    f = FilmCutForm.from_spec(only_clip, "sound")                 # never cut: opens on the clip's
    assert (f.film, f.start, f.length, f.crop, f.take_sound) == ("D:/Films/G.mp4", "1:00", "5", "fill", True)
    assert FilmCutForm.from_spec(MP.ModeSpec(clip_source="x.mp4", clip_crop="odd"), "clip").crop == "letterbox"


def test_commit_cut_moves_a_staged_cut_into_the_mode(tmp_path, monkeypatch):
    """The dialog cuts into a staging folder and moves the cut into the mode only when it
    is still wanted; each file lands whole, also across drives."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    stage = D.stage_folder()
    assert os.path.basename(stage).startswith(D.STAGE_PREFIX) and os.listdir(stage) == []
    for name, data in (("clip.mp4", b"new clip"), ("end.wav", b"new sound")):
        with open(os.path.join(stage, name), "wb") as f:
            f.write(data)
    folder = tmp_path / "proj" / "modes" / "rush"
    folder.mkdir(parents=True)
    (folder / "clip.mp4").write_bytes(b"old clip")
    (folder / "mode.json").write_text("{}")
    res = D.commit_cut({"mode_folder": stage, "clip_file": "clip.mp4", "end_sound": "end.wav",
                        "clip_from": 2.0, "summary": "x"}, str(folder))
    assert res["mode_folder"] == str(folder) and res["clip_from"] == 2.0
    assert sorted(os.listdir(folder)) == ["clip.mp4", "end.wav", "mode.json"]
    assert (folder / "clip.mp4").read_bytes() == b"new clip"
    D.discard_stage(stage)
    assert not os.path.exists(stage)

    stage2 = D.stage_folder()
    with open(os.path.join(stage2, "art.png"), "wb") as f:
        f.write(b"art")
    real_replace = os.replace

    def across_drives(src, dst):
        if str(src).startswith(stage2):
            raise OSError(18, "Invalid cross-device link")
        return real_replace(src, dst)
    monkeypatch.setattr(os, "replace", across_drives)
    D.commit_cut({"mode_folder": stage2, "screen_art": "art.png"}, str(folder))
    assert (folder / "art.png").read_bytes() == b"art" and not (folder / "art.png.part").exists()
    D.discard_stage(stage2)
    stage3 = D.stage_folder()
    with open(os.path.join(stage3, "clip.mp4"), "wb") as f:
        f.write(b"orphan")
    gone = tmp_path / "proj" / "modes" / "deleted_meanwhile"
    with pytest.raises(FC.FilmCutError, match="deleted while the cut was made"):
        D.commit_cut({"mode_folder": stage3, "clip_file": "clip.mp4"}, str(gone))
    assert not gone.exists()                                      # no orphan folder made
    D.discard_stage(stage3)
    keep = tmp_path / "not_a_stage"
    keep.mkdir()
    D.discard_stage(str(keep))                                    # only ever a staging folder
    assert keep.is_dir()


def test_describe_says_what_came_from_where():
    spec = MP.ModeSpec()
    assert describe(spec) == ""
    spec.clip, spec.clip_file, spec.screen_art = "file", "clip.mp4", "art.png"
    spec.clip_source, spec.clip_from, spec.clip_length = r"D:\Films\Godzilla.2014.mp4", 5700.0, 6.0
    spec.art_source, spec.art_from = "D:/Films/Godzilla.2014.mp4", 5703.0
    assert describe(spec) == ("Clip: 6 s from 1:35:00. Picture: the frame at 1:35:03. "
                              "Cut from Godzilla.2014.mp4.")
    spec.clip = "title"                                  # the cut is no longer the mode's clip
    assert describe(spec) == "Picture: the frame at 1:35:03. Cut from Godzilla.2014.mp4."
    spec.screen_art = ""                                 # a generated panel instead
    assert describe(spec) == ""


# ---- on the synthetic film -----------------------------------------------------------------
def test_snapshot_keeps_its_fields_and_shares_the_probe(film, monkeypatch):
    """A worker's snapshot does not see later edits, and the film is probed once for both."""
    f = FilmCutForm(film=film, start="0:02")
    calls = []
    real = FC.probe
    monkeypatch.setattr(FC, "probe", lambda p: calls.append(p) or real(p))
    snap = f.snapshot()
    f.start, f.length, f.crop = "0:09", "30", "fill"
    assert (snap.start, snap.length, snap.crop) == ("0:02", "6", "letterbox")
    assert snap.info().width == 720
    assert f.info() is snap.info() and len(calls) == 1


def test_problems_check_the_span_against_the_film(film):
    assert FilmCutForm(film=film, start="0:02", length="6").problems() == []
    text = " ".join(FilmCutForm(film=film, start="0:07", length="6", take_sound=True).problems())
    assert "The clip: That span runs past the end of the film (0:10" in text
    assert "The sound: That span runs past the end" in text
    text = " ".join(FilmCutForm(film=film, start="0:02", length="31").problems())
    assert "at most 30 seconds" in text
    f = FilmCutForm(film=film, take_clip=False, take_still=True, still_at="0:12")
    assert len(f.problems()) == 1 and f.problems()[0].startswith("The picture: the film is only 0:10")


def test_preview_is_the_start_with_the_crop(film, ff):
    img = FilmCutForm(film=film, start="0:02", crop="letterbox").preview(ff)
    px = np.asarray(img)
    assert img.size == FC.preview_size((480, 270))
    assert _is_black(px[1, img.width // 2]) and _near(px[img.height // 2, 3], RED)
    px = np.asarray(FilmCutForm(film=film, start="0:06", crop="fill").preview(ff))
    assert _near(px[1, px.shape[1] // 2], BLUE)
    with pytest.raises(FC.FilmCutError):
        FilmCutForm(film=film, start="nope").preview(ff)


def test_apply_cuts_all_three_into_the_mode_folder(film, ff, tmp_path):
    folder = str(tmp_path / "modes" / "rush")
    f = FilmCutForm(film=film, start="0:02", length="6", crop="fill", take_clip=True,
                    take_sound=True, take_still=True, sound_same=False, sound_start="0:06",
                    sound_length="3", still_at="0:07")
    res = f.apply(folder, ff)
    assert sorted(os.listdir(folder)) == ["art.png", "clip.mp4", "end.wav"]
    assert (res["clip_file"], res["end_sound"], res["screen_art"]) == ("clip.mp4", "end.wav", "art.png")
    assert (res["clip_from"], res["clip_length"], res["sound_from"], res["sound_length"], res["art_from"]) == (
        2.0, 6.0, 6.0, 3.0, 7.0)
    assert all(res[k] == os.path.abspath(film) for k in ("clip_source", "sound_source", "art_source"))
    assert set(PROVENANCE) <= set(res)
    assert (res["clip_crop"], res["art_crop"]) == ("fill", "fill")
    (v,) = _streams(os.path.join(folder, "clip.mp4"))
    assert (v["width"], v["height"], int(v["nb_read_frames"])) == (1360, 768, 180)
    with wave.open(os.path.join(folder, "end.wav"), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getnframes()) == (1, 44100, 3 * 44100)
    art = MA.load_art(os.path.join(folder, "art.png"))
    assert art.shape[1] == 640 and _near(art[4, 320, :3], BLUE)
    assert res["summary"].startswith("Clip: 6 s from 0:02. Sound: 3 s from 0:06. Picture: the frame at 0:07.")


def test_apply_refuses_before_writing_anything(film, ff, tmp_path):
    folder = str(tmp_path / "m")
    with pytest.raises(FC.FilmCutError, match="past the end"):
        FilmCutForm(film=film, start="0:08", length="6").apply(folder, ff)
    assert not os.path.exists(folder)


def test_describe_shortens_a_long_film_name_for_the_tab():
    spec = MP.ModeSpec(clip_source="D:/F/Ghidorah.The.Three.Headed.Monster1964.JAPANESE.1080p.BluRay.H264.AC3.DD2.0.mp4",
                       clip_from=4800.0, clip_length=6.0, clip="file", clip_file="clip.mp4")
    text = describe(spec)
    assert text.startswith("Clip: 6 s from 1:20:00. Cut from Ghidorah.The.Three.Headed.Monster")
    assert text.endswith("\u2026.mp4.") and len(text) < 90
