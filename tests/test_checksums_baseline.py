"""Tests for the robust baseline parser + change-diff helpers in core.checksums
(read_baseline_any / changed_rels), shared by the Write preview and the Replace
tabs so they agree on what counts as 'changed'."""

import os

from pinball_decryptor.core import checksums
from pinball_decryptor.core.checksums import CHECKSUMS_FILE


def _w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_read_baseline_any_tab_format(tmp_path):
    lines = ["audio/idx0001.wav\t" + "a" * 32,
             "video/intro.mov\t" + "b" * 32]
    (tmp_path / CHECKSUMS_FILE).write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")
    base = checksums.read_baseline_any(str(tmp_path))
    assert base == {"audio/idx0001.wav": "a" * 32, "video/intro.mov": "b" * 32}


def test_read_baseline_any_md5sum_format(tmp_path):
    lines = ["a" * 32 + "  ./audio/idx0001.wav",
             "b" * 32 + " *video/intro.mov"]
    (tmp_path / CHECKSUMS_FILE).write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")
    base = checksums.read_baseline_any(str(tmp_path))
    assert base == {"audio/idx0001.wav": "a" * 32, "video/intro.mov": "b" * 32}


def test_changed_rels_detects_edits_and_unknowns(tmp_path):
    assets = str(tmp_path)
    _w(os.path.join(assets, "audio", "idx0001.wav"), b"ORIGINAL")
    _w(os.path.join(assets, "audio", "idx0002.wav"), b"UNCHANGED")
    _w(os.path.join(assets, "audio", "idx0003.wav"), b"NEW-FILE")
    checksums.generate_checksums(assets)            # baseline of 0001 + 0002
    # 0003 was written AFTER the baseline — drop it from the baseline so it reads
    # as an un-baselined (new) file.
    base = checksums.read_baseline_any(assets)
    base.pop("audio/idx0003.wav", None)

    _w(os.path.join(assets, "audio", "idx0001.wav"), b"EDITED")   # changed
    rels = ["audio/idx0001.wav", "audio/idx0002.wav", "audio/idx0003.wav"]
    changed = checksums.changed_rels(assets, rels, baseline=base)
    assert changed == {"audio/idx0001.wav", "audio/idx0003.wav"}


def test_changed_rels_missing_file_is_changed(tmp_path):
    assets = str(tmp_path)
    base = {"audio/gone.wav": "a" * 32}
    assert checksums.changed_rels(assets, ["audio/gone.wav"], baseline=base) == {
        "audio/gone.wav"}


def test_all_changed_diffs_whole_baseline(tmp_path):
    assets = str(tmp_path)
    _w(os.path.join(assets, "audio", "idx0001.wav"), b"A")
    _w(os.path.join(assets, "audio", "idx0002.wav"), b"B")
    _w(os.path.join(assets, "video", "intro.mov"), b"V")
    checksums.generate_checksums(assets)
    _w(os.path.join(assets, "audio", "idx0001.wav"), b"A-EDIT")
    _w(os.path.join(assets, "video", "intro.mov"), b"V-EDIT")
    assert checksums.all_changed(assets) == {"audio/idx0001.wav",
                                             "video/intro.mov"}


def test_all_changed_excludes_orig_mirror(tmp_path):
    # A baseline that somehow carries a stale ".orig/" entry must never be
    # diffed (the snapshot mirror isn't a card asset).
    assets = str(tmp_path)
    base = {".orig/audio/idx0001.wav": "a" * 32, "audio/idx0001.wav": "b" * 32}
    _w(os.path.join(assets, "audio", "idx0001.wav"), b"changed")
    assert checksums.all_changed(assets, baseline=base) == {"audio/idx0001.wav"}


def test_all_changed_progress_and_cancel(tmp_path):
    assets = str(tmp_path)
    for i in range(4):
        _w(os.path.join(assets, "audio", "idx%04d.wav" % i), bytes([i]))
    checksums.generate_checksums(assets)
    seen = []
    checksums.all_changed(assets, progress=lambda c, t: seen.append((c, t)))
    assert seen and seen[-1][0] == seen[-1][1]      # finishes at total/total
    # Cancel short-circuits.
    out = checksums.all_changed(assets, cancel=lambda: True)
    assert out == set()


def test_all_changed_quick_skips_by_mtime(tmp_path):
    """quick=True skips files whose mtime is <= the baseline file's mtime
    (pristine by construction — checksums is written last), and still catches
    files modified after extract."""
    assets = str(tmp_path)
    _w(os.path.join(assets, "audio", "old.wav"), b"A")
    _w(os.path.join(assets, "audio", "new.wav"), b"B")
    checksums.generate_checksums(assets)
    base_m = os.path.getmtime(os.path.join(assets, CHECKSUMS_FILE))
    # Change BOTH files' content, but control their mtimes.
    _w(os.path.join(assets, "audio", "old.wav"), b"A-CHANGED")
    _w(os.path.join(assets, "audio", "new.wav"), b"B-CHANGED")
    os.utime(os.path.join(assets, "audio", "old.wav"),
             (base_m - 10, base_m - 10))   # looks untouched since extract
    os.utime(os.path.join(assets, "audio", "new.wav"),
             (base_m + 10, base_m + 10))   # touched after extract

    # quick skips old.wav (old mtime) despite its bytes differing; catches new.wav.
    assert checksums.all_changed(assets, quick=True) == {"audio/new.wav"}
    # The full byte scan catches both — quick is a deliberate revert-only opt-in.
    assert checksums.all_changed(assets, quick=False) == {
        "audio/old.wav", "audio/new.wav"}


def test_rename_in_baseline_moves_key(tmp_path):
    assets = str(tmp_path)
    _w(os.path.join(assets, "audio", "idx0001.wav"), b"DATA")
    checksums.generate_checksums(assets)
    md5 = checksums.read_baseline_any(assets)["audio/idx0001.wav"]
    moved = checksums.rename_in_baseline(
        assets, {"audio/idx0001.wav": "audio/idx0001 - Cowabunga.wav"})
    assert moved == 1
    base = checksums.read_baseline_any(assets)
    assert "audio/idx0001.wav" not in base
    assert base["audio/idx0001 - Cowabunga.wav"] == md5   # md5 carried over


def test_rename_in_baseline_noops(tmp_path):
    assets = str(tmp_path)
    # No baseline file → 0.
    assert checksums.rename_in_baseline(assets, {"a": "b"}) == 0
    _w(os.path.join(assets, "audio", "idx0001.wav"), b"DATA")
    checksums.generate_checksums(assets)
    # Empty renames, unknown key, and identity rename all → 0 (no file rewrite).
    assert checksums.rename_in_baseline(assets, {}) == 0
    assert checksums.rename_in_baseline(assets, {"audio/nope.wav": "x.wav"}) == 0
    assert checksums.rename_in_baseline(
        assets, {"audio/idx0001.wav": "audio/idx0001.wav"}) == 0


def test_autoname_rename_then_baseline_repoint_is_clean(tmp_path):
    """The bug monkeybug hit: Auto-name MOVES the WAV after the baseline was
    written, so without re-pointing the renamed file reads as "changed on disk".
    With rename_in_baseline applied, the renamed-but-unedited file is clean."""
    assets = str(tmp_path)
    _w(os.path.join(assets, "audio", "idx0001.wav"), b"SPEECH")
    _w(os.path.join(assets, "audio", "music_cat01_0001.wav"), b"SONG")
    _w(os.path.join(assets, "audio", "idx0002.wav"), b"UNTOUCHED")
    checksums.generate_checksums(assets)

    # Simulate the transcribe / music-ID rename (os.replace == move).
    renames = {"audio/idx0001.wav": "audio/idx0001 - Cowabunga.wav",
               "audio/music_cat01_0001.wav":
                   "audio/music_cat01_0001 - Kashmir.wav"}
    for old_rel, new_rel in renames.items():
        os.replace(os.path.join(assets, *old_rel.split("/")),
                   os.path.join(assets, *new_rel.split("/")))

    new_names = list(renames.values()) + ["audio/idx0002.wav"]

    # BEFORE the fix: every renamed file reads as changed (absent from baseline).
    pre = checksums.changed_rels(assets, new_names)
    assert pre == set(renames.values())

    # AFTER re-pointing: nothing reads as changed (nothing was actually edited).
    checksums.rename_in_baseline(assets, renames)
    assert checksums.changed_rels(assets, new_names) == set()
