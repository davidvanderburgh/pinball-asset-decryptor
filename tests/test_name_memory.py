"""User rename memory (core/name_memory.py): content-hash keyed names that
re-apply on the next extract before Whisper runs (monkeybug's wishlist)."""
import os

from pinball_decryptor.core import name_memory as NM
from pinball_decryptor.core.checksums import CHECKSUMS_FILE, read_baseline_any


def test_split_decode_name_shapes():
    assert NM.split_decode_name("idx0001.wav") == ("idx0001", "", ".wav")
    assert NM.split_decode_name("idx0001 - Hello there.wav") == (
        "idx0001", "Hello there", ".wav")
    assert NM.split_decode_name("01m22s235 - idx0001 - X.wav") == (
        "01m22s235 - idx0001", "X", ".wav")
    assert NM.split_decode_name("music_cat01_0002.wav") == (
        "music_cat01_0002", "", ".wav")
    assert NM.split_decode_name("idx0009.ogg") == ("idx0009", "", ".ogg")
    # Non-decode names are refused: every other plugin's Write maps audio by
    # its full path, so those must never be renamed.
    assert NM.split_decode_name("MUS_MAIN_THEME.wav") is None
    assert NM.split_decode_name("callouts.csv") is None


def test_sanitize_label():
    assert NM.sanitize_label('  a  <b>:"c"  ') == "a _b___c_"
    assert NM.sanitize_label("x" * 200) == "x" * 80   # capped like transcribe
    assert NM.sanitize_label("dots...  ") == "dots"
    assert NM.sanitize_label("") == ""
    assert NM.sanitize_label(None) == ""


def test_remember_load_forget_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(NM, "AUDIO_NAMES_FILE",
                        str(tmp_path / "audio_names.json"))
    md5 = "a" * 32
    NM.remember(md5, "Joust champion!")
    assert NM.load() == {md5: "Joust champion!"}
    NM.remember(md5, "Joust champion!")        # unchanged → no-op
    NM.remember(md5.upper(), "Better name")    # case-insensitive key
    assert NM.load() == {md5: "Better name"}
    NM.remember(md5, "")                       # blank forgets
    assert NM.load() == {}
    NM.remember("not-an-md5", "x")             # foreign keys are dropped
    assert NM.load() == {}


def _write_baseline(assets, entries):
    with open(os.path.join(assets, CHECKSUMS_FILE), "w",
              encoding="utf-8") as f:
        for rel, md5 in entries.items():
            f.write(f"{rel}\t{md5}\n")


def test_apply_saved_names(tmp_path, monkeypatch):
    monkeypatch.setattr(NM, "AUDIO_NAMES_FILE",
                        str(tmp_path / "audio_names.json"))
    assets = tmp_path / "assets"
    audio = assets / "audio"
    audio.mkdir(parents=True)
    # Three sounds: one bare, one Whisper-mis-named, one whose remembered
    # label is already in place.
    (audio / "idx0001.wav").write_bytes(b"one")
    (audio / "idx0002 - wrong transcript.wav").write_bytes(b"two")
    (audio / "idx0003 - Already right.wav").write_bytes(b"three")
    _write_baseline(str(assets), {
        "audio/idx0001.wav": "1" * 32,
        "audio/idx0002 - wrong transcript.wav": "2" * 32,
        "audio/idx0003 - Already right.wav": "3" * 32,
    })
    NM.remember("1" * 32, "Named one")
    NM.remember("2" * 32, "Named two")
    NM.remember("3" * 32, "Already right")

    n = NM.apply_saved_names(str(assets))
    assert n == 2
    names = sorted(os.listdir(audio))
    assert names == ["idx0001 - Named one.wav",
                     "idx0002 - Named two.wav",
                     "idx0003 - Already right.wav"]
    # Baseline followed the renames (bytes unchanged, keys re-pointed).
    base = read_baseline_any(str(assets))
    assert base["audio/idx0001 - Named one.wav"] == "1" * 32
    assert base["audio/idx0002 - Named two.wav"] == "2" * 32
    # Second run is a clean no-op.
    assert NM.apply_saved_names(str(assets)) == 0


def test_apply_saved_names_edge_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(NM, "AUDIO_NAMES_FILE",
                        str(tmp_path / "audio_names.json"))
    assets = tmp_path / "assets"
    assets.mkdir()
    # No baseline → nothing to match against.
    NM.remember("4" * 32, "Ghost")
    assert NM.apply_saved_names(str(assets)) == 0
    # Target collision → skipped, source left alone.
    (assets / "idx0004.wav").write_bytes(b"four")
    (assets / "idx0004 - Taken.wav").write_bytes(b"other")
    _write_baseline(str(assets), {"idx0004.wav": "4" * 32})
    NM.remember("4" * 32, "Taken")
    assert NM.apply_saved_names(str(assets)) == 0
    assert (assets / "idx0004.wav").exists()
    # Non-decode names never rename even when the hash matches.
    (assets / "THEME.wav").write_bytes(b"five")
    _write_baseline(str(assets), {"THEME.wav": "5" * 32})
    NM.remember("5" * 32, "Renamed")
    assert NM.apply_saved_names(str(assets)) == 0
    assert (assets / "THEME.wav").exists()
