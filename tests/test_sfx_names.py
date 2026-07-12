"""Sound-Test-menu SFX auto-naming: the pure-logic pieces (no emulator/card).

The firmware RE (resolver drive, container-key match) is exercised end-to-end
only with a real card, but the filename application, the Whisper skip, and the
graceful-degradation contract are synthetic-testable and are where regressions
would silently mis-name or double-name files.
"""
import os

import pytest

from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.core import transcribe


# ---- _apply_sfx_names: rename bare decode WAVs to their menu names -----------

def _touch(path):
    with open(path, "wb") as f:
        f.write(b"RIFF....WAVE")


def _params(*idxs):
    return [{"idx": i, "length": 44100, "chan": 1} for i in idxs]


def test_apply_names_renames_bare_files(tmp_path):
    ad = tmp_path
    for i in (1, 2, 3):
        _touch(os.path.join(ad, "idx%04d.wav" % i))
    n = engine._apply_sfx_names(
        str(ad), {1: "SE FX ZEPPELIN JACKPOT", 3: "SE FX TOUR ADVANCE"},
        _params(1, 2, 3), duration_names=False)
    assert n == 2
    got = set(os.listdir(ad))
    assert "idx0001 - SE FX ZEPPELIN JACKPOT.wav" in got
    assert "idx0003 - SE FX TOUR ADVANCE.wav" in got
    assert "idx0002.wav" in got                       # unnamed left bare


def test_apply_names_respects_duration_prefix(tmp_path):
    # With length-prefix naming the decode file leads with the duration; the
    # name is appended after the idx, preserving the sort-by-length prefix.
    ad = tmp_path
    base = engine._wav_basename({"idx": 7, "length": 44100, "chan": 1},
                                duration_names=True)
    _touch(os.path.join(ad, base))
    engine._apply_sfx_names(str(ad), {7: "SE FX SONG AWARD"},
                            _params(7), duration_names=True)
    out = os.listdir(ad)
    assert out == [base[:-4] + " - SE FX SONG AWARD.wav"]
    assert out[0].startswith(base[:-4])               # duration prefix intact


def test_apply_names_sanitizes_illegal_chars(tmp_path):
    ad = tmp_path
    _touch(os.path.join(ad, "idx0001.wav"))
    engine._apply_sfx_names(str(ad), {1: 'SE FX A/B:C*?"<>|D'},
                            _params(1), duration_names=False)
    out = os.listdir(ad)[0]
    assert not any(c in out for c in '/\\:*?"<>|')
    assert out == "idx0001 - SE FX ABCD.wav"


def test_apply_names_skips_missing_and_empty(tmp_path):
    ad = tmp_path
    _touch(os.path.join(ad, "idx0001.wav"))
    # idx 2 named but never decoded (no bare file) -> skipped, no crash.
    assert engine._apply_sfx_names(
        str(ad), {1: "SE FX X", 2: "SE FX Y"}, _params(1, 2),
        duration_names=False) == 1
    assert engine._apply_sfx_names(str(ad), {}, _params(1), False) == 0


def test_apply_names_reextract_twin_removal_pattern(tmp_path):
    # A menu-named file must match the renamed-twin regex so a re-extract's
    # cleanup drops it (else duplicates accumulate).
    named = "idx0001 - SE FX ZEPPELIN JACKPOT.wav"
    assert engine._RENAMED_AUDIO_RE.match(named)
    named_dur = "00m01s000 - idx0001 - SE FX SONG AWARD.wav"
    assert engine._RENAMED_AUDIO_RE.match(named_dur)


# ---- Whisper skips already-named decode files -------------------------------

def test_find_wavs_skips_named_decode_files(tmp_path):
    for fn in ("idx0001.wav",                          # bare -> transcribe
               "00m01s000 - idx0002.wav",              # length-prefixed bare
               "idx0003 - SE FX TOUR ADVANCE.wav",     # menu-named -> skip
               "idx0004 - Welcome back!.wav",          # prior transcript -> skip
               "music_cat05_0007.wav",                 # bare bank -> transcribe
               "music_cat05_0008 - Kashmir.wav"):      # named bank -> skip
        _touch(os.path.join(tmp_path, fn))
    got = {os.path.basename(w) for w in transcribe._find_wavs(str(tmp_path))}
    assert got == {"idx0001.wav", "00m01s000 - idx0002.wav",
                   "music_cat05_0007.wav"}


# ---- build_name_map graceful degradation ------------------------------------

def test_locate_menu_names_empty_on_junk():
    # No SE FX menu present -> empty list, never raises.
    assert engine.__dict__  # sanity
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    assert sfx_names.locate_menu_names(b"\x00" * 4096) == []
    assert sfx_names.locate_menu_names(b"not an elf") == []


def test_build_name_map_never_raises_on_bad_emu(tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import sfx_names

    junk = tmp_path / "game_real"
    junk.write_bytes(b"not an elf" * 512)

    class _Bad:
        _gr_path = str(junk)
    # No key0 (empty / key-less params) and un-parsable firmware both yield {}
    # rather than an exception — extract keeps plain idx names.
    assert sfx_names.build_name_map(_Bad(), []) == {}
    assert sfx_names.build_name_map(_Bad(), [{"idx": 0}]) == {}
    assert sfx_names.build_name_map(_Bad(), [{"idx": 0, "key0": 123}]) == {}
