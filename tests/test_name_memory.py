"""User rename memory (core/name_memory.py): content-hash keyed names that
re-apply on the next extract before Whisper runs (a tester's wishlist)."""
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
    # PAD-1158: a whole-sentence callout fits (was cut at 80)
    assert NM.sanitize_label("x" * 150) == "x" * 150
    assert NM.sanitize_label("x" * 300) == "x" * NM.MAX_LABEL == "x" * 200
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


def test_remember_with_category(tmp_path, monkeypatch):
    monkeypatch.setattr(NM, "AUDIO_NAMES_FILE",
                        str(tmp_path / "audio_names.json"))
    md5 = "b" * 32
    NM.remember(md5, "Ramp exit swoosh", category="sfx")
    assert NM.load() == {md5: "Ramp exit swoosh"}
    assert NM.load_categories() == {md5: "sfx"}
    # Re-remember without a category drops it (the caller knows best).
    NM.remember(md5, "Ramp exit swoosh 2")
    assert NM.load_categories() == {}
    # Legacy plain-string store entries still load.
    import json
    (tmp_path / "audio_names.json").write_text(
        json.dumps({"c" * 32: "Old style"}), encoding="utf-8")
    assert NM.load() == {"c" * 32: "Old style"}
    assert NM.load_categories() == {}


def test_remember_category_without_a_name(tmp_path, monkeypatch):
    """PAD-1061: the Type given a sound with no name is stored on its own:
    no label, so it renames nothing; a later name replaces it."""
    monkeypatch.setattr(NM, "AUDIO_NAMES_FILE",
                        str(tmp_path / "audio_names.json"))
    md5 = "e" * 32
    NM.remember_category(md5, "sfx")
    assert NM.load() == {}
    assert NM.load_categories() == {md5: "sfx"}
    assets = tmp_path / "assets"
    (assets / "audio").mkdir(parents=True)
    (assets / "audio" / "idx0005.wav").write_bytes(b"five")
    _write_baseline(str(assets), {"audio/idx0005.wav": md5})
    assert NM.apply_saved_names(str(assets)) == 0
    assert os.listdir(assets / "audio") == ["idx0005.wav"]
    NM.remember(md5, "Swoosh", category="music")
    assert NM.load() == {md5: "Swoosh"}
    assert NM.load_categories() == {md5: "music"}
    # a blank name forgets the entry, Type and all
    NM.remember(md5, "")
    assert NM.load_categories() == {}


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


def test_fit_label_keeps_a_name_that_fits():
    """PAD-1158: a 150-character name in a short folder is left whole."""
    name = "y" * 150
    assert NM.fit_label("C:\p\audio", "00m01s000 - idx0001", name, ".wav",
                        windows=True) == name
    assert NM.fit_label("/p/audio", "idx0001", "", ".wav") == ""


def test_fit_label_trims_to_windows_path_limit():
    """PAD-1158: a deep folder plus a long name is trimmed so the whole
    path stays openable by Windows' plain calls; nothing trims elsewhere."""
    folder = "C:\\" + "\\".join(["deepfolder"] * 12)
    name = "word " * 40
    name = name.strip()
    got = NM.fit_label(folder, "00m01s000 - idx0001", name, ".wav",
                       windows=True)
    assert got and name.startswith(got) and len(got) < len(name)
    import ntpath
    full = ntpath.join(folder, "00m01s000 - idx0001 - %s.wav" % got)
    assert len(full) <= 245 and not got.endswith((" ", "."))
    assert NM.fit_label("/" + "/".join(["deepfolder"] * 12), "idx0001",
                        name, ".wav", windows=False) == name


def test_fit_label_counts_bytes_for_the_file_name():
    """ext4 / APFS hold 255 BYTES of name: 200 two-byte characters don't."""
    got = NM.fit_label("/p", "idx0001", "é" * 200, ".wav", windows=False)
    assert len(("idx0001 - %s.wav" % got).encode("utf-8")) <= 255
    assert len(got) > 100


def test_fit_label_nothing_fits():
    folder = "C:\\" + "x" * 240
    assert NM.fit_label(folder, "idx0001", "hello", ".wav", windows=True) == ""


def test_transcribe_rename_keeps_a_long_transcript(tmp_path, monkeypatch):
    """PAD-1158: Auto-name's rename used the same 80 cap.  (The path budget
    is lifted: pytest's own temp folder is deep enough to trim it.)"""
    from pinball_decryptor.core.transcribe import _renamed_rel_path
    monkeypatch.setattr(NM, "_MAX_WIN_PATH", 1000)
    text = "and every unit is to report to the bridge " * 3
    got = _renamed_rel_path("audio/idx0001.wav", text, str(tmp_path))
    assert got == "audio/idx0001 - %s.wav" % text.strip()
    assert len(got) > 120


def test_transcribe_rename_fits_a_deep_folder(tmp_path, monkeypatch):
    """...and is trimmed, never failed, where Windows' path limit bites."""
    from pinball_decryptor.core.transcribe import _renamed_rel_path
    monkeypatch.setattr(NM.sys, "platform", "win32")
    text = "and every unit is to report to the bridge " * 4
    deep = "C:\\" + "\\".join(["deepfolder"] * 10)
    got = _renamed_rel_path("audio/idx0001.wav", text, deep)
    import ntpath
    assert got.startswith("audio/idx0001 - and every unit")
    assert len(ntpath.join(deep, got.replace("/", "\\"))) <= 245
