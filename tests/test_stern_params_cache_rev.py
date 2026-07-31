"""Superseded codec-parameter caches are deleted, not just ignored (fast).

Bumping ``_DERIVE_REV`` stops a stale cache being USED, but on its own it
strands the old files forever: a pickle holding codec params we now know are
wrong keeps costing the user disk (Deadpool Pro 1.16 caches ~66 MB on its own,
and a machine that has extracted a few big cards was carrying ~250 MB).  So the
revision lives in the FILE NAME -- the same way the SFX-name map's ``3`` -> ``4``
suffix already retires superseded maps -- which makes a superseded file
identifiable and therefore deletable.
"""
import os

import pytest

from pinball_decryptor.plugins.stern.engine import (
    _CACHE_KINDS, _DERIVE_REV, _REV_TAG, _cache_path, _consumed_cache_path,
    _is_stale_cache_file, _sfx_names_cache_path, clear_stale_params_caches)

FP = "0123456789abcdef" * 4        # 64 hex chars; only the first 32 are used
STEM = FP[:32]


def test_current_paths_all_carry_the_revision():
    """Every file kind is tagged, so a later bump can identify all of them."""
    for p in (_cache_path(FP), _consumed_cache_path(FP), _sfx_names_cache_path(FP)):
        assert os.path.basename(p).startswith(STEM + _REV_TAG), p


def test_all_current_paths_land_in_one_directory():
    """The prune lists a single directory, so the three kinds must be siblings."""
    dirs = {os.path.dirname(p) for p in
            (_cache_path(FP), _consumed_cache_path(FP), _sfx_names_cache_path(FP))}
    assert len(dirs) == 1


@pytest.mark.parametrize("name", [
    STEM + ".pkl",                       # rev-1: written before tagging existed
    STEM + ".consumed.npy",
    STEM + ".sfxnames3.json",
    STEM + ".sfxnames4.json",
    STEM + ".r1.pkl",
    STEM + ".r1.consumed.npy",
])
def test_superseded_files_are_stale(name):
    assert _is_stale_cache_file(name) is True


@pytest.mark.parametrize("name", [
    STEM + _REV_TAG + ".pkl",
    STEM + _REV_TAG + ".consumed.npy",
    STEM + _REV_TAG + ".sfxnames4.json",
])
def test_current_files_are_not_stale(name):
    """The live cache must survive its own prune."""
    assert _is_stale_cache_file(name) is False


@pytest.mark.parametrize("name", [
    "notes.txt",                         # not ours
    "README",
    STEM + ".pkl.tmp",
    "zzz.pkl",                           # right suffix, not a fingerprint stem
    STEM[:31] + ".pkl",                  # 31 hex chars
    (STEM + "ab") + ".pkl",              # 34 hex chars
])
def test_foreign_files_are_left_alone(name):
    """Only the file kinds this module writes are ever deleted."""
    assert _is_stale_cache_file(name) is False


def test_future_revision_is_also_stale():
    """A cache written by a NEWER build (user downgraded) is not ours to read;
    it is superseded from this build's point of view and gets cleared."""
    assert _is_stale_cache_file(STEM + ".r%d.pkl" % (_DERIVE_REV + 1)) is True


def test_clear_deletes_only_superseded(tmp_path, monkeypatch):
    """End to end: stale files go, the live cache and foreign files stay, and
    the reported byte count matches what was actually freed."""
    d = tmp_path / "pinball_spike2_params"
    d.mkdir()
    monkeypatch.setattr(
        "pinball_decryptor.plugins.stern.engine._params_cache_dir",
        lambda: str(d))

    stale = {STEM + ".pkl": 300,
             STEM + ".consumed.npy": 5000,
             STEM + ".sfxnames4.json": 20,
             STEM + ".r1.pkl": 100}
    keep = {STEM + _REV_TAG + ".pkl": 7,
            STEM + _REV_TAG + ".consumed.npy": 9,
            "notes.txt": 11}
    for name, size in {**stale, **keep}.items():
        (d / name).write_bytes(b"x" * size)

    n, freed = clear_stale_params_caches()
    assert n == len(stale)
    assert freed == sum(stale.values())
    left = set(os.listdir(str(d)))
    assert left == set(keep)


def test_clear_is_idempotent_and_survives_a_missing_dir(tmp_path, monkeypatch):
    """Called once per process, and processes fan out -- a second call (or a
    directory that isn't there yet) must be a quiet no-op, not an error."""
    d = tmp_path / "gone"
    monkeypatch.setattr(
        "pinball_decryptor.plugins.stern.engine._params_cache_dir",
        lambda: str(d))
    assert clear_stale_params_caches() == (0, 0)

    d.mkdir()
    (d / (STEM + ".pkl")).write_bytes(b"x" * 42)
    assert clear_stale_params_caches() == (1, 42)
    assert clear_stale_params_caches() == (0, 0)


def test_every_kind_has_a_pattern_matching_its_own_current_name():
    """Guards the bump ritual: if a new revision's suffix stops matching its own
    kind regex, that kind would be deleted the moment it is written."""
    for cur, pat in _CACHE_KINDS:
        assert pat.match(STEM + cur), cur
