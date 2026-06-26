"""Tests for core.staged_originals — the .orig snapshot cache that lets a staged
edit be reverted without a full re-extract."""

import os

from pinball_decryptor.core import staged_originals as so
from pinball_decryptor.core.checksums import md5_file
from pinball_decryptor.core.staged_originals import ORIG_DIR


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_snapshot_then_revert_roundtrip(tmp_path):
    assets = str(tmp_path)
    rel = "audio/idx0001.wav"
    target = os.path.join(assets, "audio", "idx0001.wav")
    _write(target, b"ORIGINAL")
    base = md5_file(target)

    # First stage: snapshot the pristine bytes, then "modify" the file.
    assert so.snapshot(assets, rel, base) is True
    assert so.has_snapshot(assets, rel)
    _write(target, b"REPLACEMENT-BYTES")

    # Revert restores the original and drops the snapshot.
    assert so.revert(assets, rel) is True
    with open(target, "rb") as f:
        assert f.read() == b"ORIGINAL"
    assert not so.has_snapshot(assets, rel)


def test_snapshot_is_idempotent_keeps_true_original(tmp_path):
    # A second build must NOT overwrite the snapshot with the already-modified
    # file — the first snapshot is the only copy of the real original.
    assets = str(tmp_path)
    rel = "audio/idx0002.wav"
    target = os.path.join(assets, "audio", "idx0002.wav")
    _write(target, b"ORIGINAL")
    base = md5_file(target)

    assert so.snapshot(assets, rel, base) is True
    _write(target, b"BUILD-1-EDIT")
    # baseline_md5 no longer matches; even without the guard the existing-snapshot
    # check must short-circuit.
    assert so.snapshot(assets, rel, base) is False
    assert so.revert(assets, rel) is True
    with open(target, "rb") as f:
        assert f.read() == b"ORIGINAL"


def test_snapshot_skips_already_diverged_file(tmp_path):
    # A file that no longer matches the baseline and has no snapshot can't be
    # captured (its bytes aren't the original) — revert must fall back.
    assets = str(tmp_path)
    rel = "audio/idx0003.wav"
    target = os.path.join(assets, "audio", "idx0003.wav")
    _write(target, b"ALREADY-MODIFIED")
    stale_baseline = "0" * 32
    assert so.snapshot(assets, rel, stale_baseline) is False
    assert not so.has_snapshot(assets, rel)
    assert so.revert(assets, rel) is False


def test_snapshot_missing_file_is_noop(tmp_path):
    assert so.snapshot(str(tmp_path), "audio/nope.wav", "x" * 32) is False


def test_revert_no_snapshot_returns_false(tmp_path):
    assert so.revert(str(tmp_path), "audio/idx0001.wav") is False


def test_revert_all_restores_and_clears_tree(tmp_path):
    assets = str(tmp_path)
    rels = ["audio/idx0001.wav", "audio/idx0002.wav", "video/intro.mov"]
    for rel in rels:
        target = os.path.join(assets, *rel.split("/"))
        _write(target, b"ORIG-" + rel.encode())
        assert so.snapshot(assets, rel, md5_file(target))
        _write(target, b"EDIT")

    reverted = so.revert_all(assets)
    assert sorted(reverted) == sorted(rels)
    for rel in rels:
        target = os.path.join(assets, *rel.split("/"))
        with open(target, "rb") as f:
            assert f.read() == b"ORIG-" + rel.encode()
    # The whole .orig tree is gone once everything's restored.
    assert not os.path.isdir(os.path.join(assets, ORIG_DIR))


def test_snapshot_rels_lists_everything(tmp_path):
    assets = str(tmp_path)
    rels = {"audio/a.wav", "images/b.png"}
    for rel in rels:
        target = os.path.join(assets, *rel.split("/"))
        _write(target, b"x")
        so.snapshot(assets, rel, None)
    assert so.snapshot_rels(assets) == rels


def test_discard_removes_tree_without_restoring(tmp_path):
    assets = str(tmp_path)
    rel = "audio/idx0001.wav"
    target = os.path.join(assets, "audio", "idx0001.wav")
    _write(target, b"ORIGINAL")
    so.snapshot(assets, rel, md5_file(target))
    _write(target, b"EDIT")

    so.discard(assets)
    assert not os.path.isdir(os.path.join(assets, ORIG_DIR))
    # The on-disk file is left as-is (discard never restores).
    with open(target, "rb") as f:
        assert f.read() == b"EDIT"


def test_snapshot_unconditional_when_baseline_none(tmp_path):
    assets = str(tmp_path)
    rel = "audio/x.wav"
    target = os.path.join(assets, "audio", "x.wav")
    _write(target, b"WHATEVER")
    assert so.snapshot(assets, rel, None) is True
    assert so.has_snapshot(assets, rel)
