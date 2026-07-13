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


# ---- _descriptor_refs / _select_names: op11 binding rules --------------------

def _desc(pairs, size=0x50):
    """Synthetic descriptor: 0x0b opcode bytes at given offsets, each followed
    (at +4) by a little-endian key."""
    import struct
    d = bytearray(size)
    d[0] = 5
    for off, key in pairs:
        d[off] = 0x0B
        struct.pack_into("<I", d, off + 4, key)
    return bytes(d)


def test_descriptor_refs_kinds():
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    keymap = {0xAAAA: 7, 0xBBBB: 9}
    # op11 anchored at 10 (payload at 14) — the entry's own primary asset,
    # even with another matching key elsewhere in the stream.
    assert sfx_names._descriptor_refs(
        _desc([(10, 0xAAAA), (40, 0xBBBB)]), keymap) == ("anchored", 7)
    # No anchor: every known-key match is returned as a reference set.
    kind, ref = sfx_names._descriptor_refs(_desc([(20, 0xAAAA)]), keymap)
    assert (kind, ref) == ("broad", frozenset({7}))
    kind, ref = sfx_names._descriptor_refs(
        _desc([(20, 0xAAAA), (40, 0xBBBB)]), keymap)
    assert (kind, ref) == ("broad", frozenset({7, 9}))
    # Nothing known -> (None, None).
    assert sfx_names._descriptor_refs(
        _desc([(20, 0xCCCC)]), keymap) == (None, None)


def test_select_names_rules():
    """The Led Zeppelin lesson: anchored names always stick; a broad binding
    names only a short record it alone references."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    secs = {1: 0.2, 2: 0.5, 30: 285.0, 31: 3.0, 40: 1.0}
    entries = [
        # Anchored blip -> named, even though the sequence below also
        # references idx 1.
        (100, "SE FX BLIP", "anchored", 1),
        # Sequence referencing sting + shared music master -> names nothing.
        (99, "SE FX SEQ ZEPPELIN AWARD", "broad", frozenset({1, 30})),
        # Sole unique broad ref to a SHORT record -> named.
        (98, "SE FX TARGET HIT", "broad", frozenset({2})),
        # Unique broad ref to a LONG record (a song master) -> NOT named.
        (97, "SE FX LEFT RAMP EXIT", "broad", frozenset({30})),
        # Unique broad ref, but ANOTHER entry references the same record ->
        # shared, NOT named (no canonical event name exists).
        (96, "SE FX ADD A BALL", "broad", frozenset({31})),
        (95, "SE FX SEQ BALL SAVED", "broad", frozenset({31})),
        # Two anchored entries sharing one reused sample: first in table
        # order wins, second is dropped silently (both names are true).
        (94, "SE FX SLING LEFT", "anchored", 40),
        (93, "SE FX SLING RIGHT", "anchored", 40),
    ]
    out = sfx_names._select_names(entries, secs)
    assert out == {1: "SE FX BLIP", 2: "SE FX TARGET HIT",
                   40: "SE FX SLING LEFT"}


# ---- extract-level naming is disabled pending the binding re-RE -------------

def test_extract_naming_disabled_by_default(tmp_path, monkeypatch):
    """v0.63.1: content validation proved the menu->sound binding wrong
    (speaker prompts inside blip-named files, Kashmir as "COMBO TERMINATE"),
    so the extract pass names nothing until re-verified.  PINBALL_SFX_NAMES=1
    re-enables for RE work."""
    monkeypatch.delenv("PINBALL_SFX_NAMES", raising=False)
    logs = []
    out = engine._load_or_build_sfx_names(
        None, None, None, [], lambda m, lvl: logs.append(m))
    assert out == {}
    assert any("auto-naming is off" in m for m in logs)


# ---- sound_test_names.csv sidecar (rename suggestions) -----------------------

def test_write_sound_test_names_sidecar(tmp_path, monkeypatch):
    """With auto-apply off, the verified menu LIST still ships as a sidecar
    so users can map names themselves (play a number in Sound Test, rename
    the slot that played — David's suggestion)."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    monkeypatch.setattr(
        sfx_names, "locate_menu_names",
        lambda raw: [(87, "SE FX SEQ BALL SAVE LIT"), (12, "SE FX BLIP")])
    gr = tmp_path / "game_real"
    gr.write_bytes(b"elf-ish")
    logs = []
    n = engine._write_sound_test_names(
        str(gr), str(tmp_path), lambda m, lvl: logs.append(m))
    assert n == 2
    import csv
    with open(tmp_path / engine.SOUND_TEST_NAMES_CSV,
              encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["sound_number"], r["name"]) for r in rows] == [
        ("12", "SE FX BLIP"), ("87", "SE FX SEQ BALL SAVE LIT")]
    assert any("Sound Test menu list" in m for m in logs)
    # Menu-less titles: no file, no crash.
    monkeypatch.setattr(sfx_names, "locate_menu_names", lambda raw: [])
    assert engine._write_sound_test_names(str(gr), str(tmp_path / "x")) == 0


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
