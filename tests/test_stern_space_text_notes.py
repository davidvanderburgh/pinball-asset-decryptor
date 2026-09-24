"""PAD-176's texts about the games partition's room: where a build's refusal
is shown, and what the notes and help say a full partition does.

The refusal (card_size.WontFit and the other CardSizeError sentences) used to
reach only the Write Failed dialog, never the log.  The notes sent a macOS
user to an SD card size control macOS doesn't show, the help said a full
partition was never trimmed although longer sounds are, and the Check card
help said a low-bitrate clip was never touched although the report beside it
advises a rebuild (PAD-171)."""

import os

import pytest

from pinball_decryptor.core import video_quality as vq
from pinball_decryptor.core.pipeline_base import PipelineError
from pinball_decryptor.plugins.stern import card_size as cs
from pinball_decryptor.plugins.stern import pipeline as pl
from pinball_decryptor.plugins.stern.manufacturer import (SternManufacturer,
                                                          _bigger_card_words)
from pinball_decryptor.webui.help_content import HELP_CONTENT

CONTROL = "SD card size on the Write tab"


# --------------------------------------------------------------- the refusal
def _pipeline(monkeypatch, exc, cancelled=False):
    def fake_write(*a, **k):
        raise exc
    monkeypatch.setattr(pl, "detect_game", lambda p: "godzilla_pro")
    monkeypatch.setattr(pl, "_require_engine", lambda: None)
    monkeypatch.setattr(pl, "_log_multi_image", lambda p, log: None)
    monkeypatch.setattr(pl.engine, "write_image", fake_write)
    monkeypatch.setattr(pl.engine, "read_build_manifest", lambda p: {})
    logged, done = [], []
    p = pl.SternWritePipeline("a.raw", "assets", "out.raw",
                              lambda text, level="info": logged.append(
                                  (text, level)),
                              lambda *a, **k: None, lambda *a, **k: None,
                              lambda ok, summary: done.append((ok, summary)))
    p._cancelled = cancelled
    return p, logged, done


def test_a_refusal_is_logged_once_as_an_error(monkeypatch):
    """The numbers a refusal quotes belong in the log a user keeps: one error
    line, in the same words as the one dialog, class codes in words."""
    why = ("This build needs 400 MB more on the card's games partition. "
           "Build it for a 16G SD card.")
    p, logged, done = _pipeline(monkeypatch, cs.CardSizeError(why))
    p.run()
    errors = [t for t, lvl in logged if lvl == "error"]
    assert errors == [pl.card_class_words(why)]
    assert "16 GB SD card" in errors[0]
    assert done == [(False, errors[0])]


def test_the_space_refusal_itself_is_logged(monkeypatch):
    p, logged, done = _pipeline(monkeypatch, cs.WontFit(400 << 20, 352 << 20))
    with pytest.raises(PipelineError) as ei:
        p._run()
    errors = [t for t, lvl in logged if lvl == "error"]
    assert errors == [ei.value.message]
    assert "games partition" in errors[0]


@pytest.mark.parametrize("exc,cancelled", [(cs.Cancelled("cancelled"), False),
                                           (cs.CardSizeError("x"), True)])
def test_a_cancel_is_not_logged_as_a_refusal(monkeypatch, exc, cancelled):
    p, logged, _done = _pipeline(monkeypatch, exc, cancelled)
    with pytest.raises(PipelineError):
        p._run()
    assert not [t for t, lvl in logged if lvl == "error"]


# ------------------------------------------------ macOS has no such control
def test_the_notes_name_the_control_where_it_is_shown(monkeypatch):
    mfr = SternManufacturer()
    for plat in ("win32", "linux"):
        monkeypatch.setattr("sys.platform", plat)
        assert CONTROL in mfr.video_length_note()
        assert CONTROL in mfr.audio_length_note()
        assert CONTROL in " ".join(vq.summary_lines(
            [_clip(padded=True)]))


def test_the_notes_on_macos_never_send_the_user_to_the_control(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    mfr = SternManufacturer()
    video, audio = mfr.video_length_note(), mfr.audio_length_note()
    squeezed = " ".join(vq.summary_lines([_clip(padded=True)]))
    small = " ".join(vq.summary_lines([_clip()]))
    for text in (video, audio, squeezed, small):
        assert "SD card size" not in text, text
        assert "Windows and Linux" in text, text
    assert "not raise the 2 GB limit" in audio
    assert audio.count("..") == 0 and ",," not in audio
    # the platform argument wins over this computer's
    monkeypatch.setattr("sys.platform", "win32")
    assert CONTROL not in " ".join(vq.summary_lines([_clip()], "darwin"))
    assert _bigger_card_words("darwin", capital=True).startswith("A build")


def test_the_advanced_audio_text_knows_the_platform():
    import pinball_decryptor.webui as webui_pkg
    js = os.path.join(os.path.dirname(webui_pkg.__file__),
                      "static", "js", "tabs", "audio.js")
    with open(js, encoding="utf-8") as f:
        src = f.read()
    start = src.index('label="Allow replacements longer than the original')
    para = src[start:src.index("</p>", start)]
    assert "${mac ?" in para and "Windows and Linux" in para
    assert "trimmed to fit it" in para
    assert "const mac" in src[:start]


def test_static_help_says_where_the_control_is():
    """The help can't tell the platform, so every pointer at the control says
    it is on Windows and Linux."""
    for tab, section in (("Replace Audio",
                          "Longer replacements (Advanced Audio Options)"),
                         ("Replace Video", "Size limits"),
                         ("Replace Video", "Checking a card you already built")):
        text = dict(HELP_CONTENT[tab])[section]
        assert text.count(CONTROL) == text.count(CONTROL + " (Windows and "
                                                           "Linux)"), section
        assert CONTROL in text, section


# ------------------------------------------------------- what the code does
def test_help_says_longer_sounds_are_trimmed_to_the_room():
    text = dict(HELP_CONTENT["Replace Audio"])[
        "Longer replacements (Advanced Audio Options)"]
    assert "is not trimmed" not in text
    assert "trimmed to fit it" in text
    assert "Keep this song whole if the bank fills up" in text


def test_help_names_every_case_a_clip_is_squeezed():
    """engine._prepare_video_patches squeezes an assigned clip whose own file
    is gone from disk too."""
    size = dict(HELP_CONTENT["Replace Video"])["Size limits"]
    note = SternManufacturer().video_length_note()
    for text in (size, note):
        assert "moved or deleted" in text, text
        assert "direct SD write" in text, text


def test_check_card_help_agrees_with_the_report():
    """PAD-171: a low-bitrate clip may be the app's own old conversion, which
    a rebuild does fix; the report says so and the help must too."""
    text = dict(HELP_CONTENT["Replace Video"])[
        "Checking a card you already built"]
    small = " ".join(vq.summary_lines([_clip()]))
    assert "rebuilding changes nothing" not in text
    assert "never touched" not in text
    for t in (text, small):
        assert "again from your original replacement files" in t
        assert "bitrate of the clip" in t


def test_the_size_tip_does_not_overpromise():
    """Longer sounds are trimmed, videos are refused before the encode, an
    update that won't fit is built whole, and what can't be sized ahead can
    still stop the copy: the tip says each, and not "instead of failing"."""
    tip = dict(HELP_CONTENT["Write"])["SD card size (Stern Spike 2)"]
    assert "instead of failing at the end" not in tip
    assert "Longer sounds are trimmed" in tip
    assert "built from the original instead" in tip
    assert "left as it was" in tip
    assert "can still stop at the copy" in tip


def test_help_never_says_a_refused_build_encoded_nothing():
    """The engine's refusal comes after the Build converted the replacements
    it had to; only the card image is sure to be untouched, and the help
    says a video still to be converted is counted once it is."""
    size = dict(HELP_CONTENT["Replace Video"])["Size limits"]
    tip = dict(HELP_CONTENT["Write"])["SD card size (Stern Spike 2)"]
    for text in (size, tip):
        assert "before anything is encoded" not in text
        assert "efore anything is written to the card image" in text
    assert ("A video that has to be converted is counted once it is, so that "
            "refusal can come after the conversions; the converted videos "
            "are kept in the project.") in tip
    assert "smallest SD card size that could take it" in tip


def _clip(padded=False):
    """A clip far under the quality bar, squeezed into its slot or not."""
    return vq.ClipQuality(name="a.mp4", size=150_000, payload=150_000,
                          width=1360, height=768, fps=30.0, duration=4.0,
                          padded=padded)
