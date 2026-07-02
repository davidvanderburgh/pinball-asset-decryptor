"""Tests for core.mod_transfer — moving a user's pending mods from an old
extract folder onto a new-version extract, reconciling layout changes."""

import os

from pinball_decryptor.core import mod_transfer, staged_changes, text_manifest


def _wav(path, payload):
    """Write a fake WAV-ish file (content signature only cares about bytes)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(payload)


def _mk_extract(root, sounds, images=None, strings=()):
    """sounds: {rel: bytes stock content}; images: {rel: bytes};
    strings: list of (path, original, replacement)."""
    images = images or {}
    for rel, data in sounds.items():
        _wav(os.path.join(root, rel.replace("/", os.sep)), data)
    for rel, data in images.items():
        _wav(os.path.join(root, rel.replace("/", os.sep)), data)
    if strings:
        text_manifest.save(root, [{"path": p, "original": o, "replacement": r}
                                  for p, o, r in strings])


def test_audio_same_index_matches(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0001.wav": b"SOUND-A" * 100})
    _mk_extract(tgt, {"audio/idx0001.wav": b"SOUND-A" * 100})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\a.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["matched"]) == 1
    assert plan["audio"]["matched"][0]["tgt_rel"] == "audio/idx0001.wav"
    assert plan["totals"]["transfer"] == 1

    mod_transfer.apply_transfer(src, tgt, plan)
    saved = staged_changes.load(tgt)
    assert saved["audio"]["audio/idx0001.wav"] == r"C:\r\a.mp3"


def test_audio_shifted_index_is_remapped(tmp_path):
    # The sound the user modded moved from idx0001 to idx0005 in the new build.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0001.wav": b"THE-SONG" * 100})
    _mk_extract(tgt, {"audio/idx0001.wav": b"a-new-intro" * 50,
                      "audio/idx0005.wav": b"THE-SONG" * 100})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\song.mp3"},
                              "audio_loop": {"audio/idx0001.wav": True}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["remapped"]) == 1
    assert plan["audio"]["remapped"][0]["tgt_rel"] == "audio/idx0005.wav"

    mod_transfer.apply_transfer(src, tgt, plan)
    saved = staged_changes.load(tgt)
    assert saved["audio"]["audio/idx0005.wav"] == r"C:\r\song.mp3"
    # The per-slot Loop flag follows the remapped index.
    assert saved["audio_loop"]["audio/idx0005.wav"] is True
    assert "audio/idx0001.wav" not in saved["audio"]


def test_audio_reused_index_is_flagged_not_applied(tmp_path):
    # idx0001 exists in both, but now holds a DIFFERENT sound -> must flag, not
    # silently mis-apply.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0001.wav": b"OLD-SOUND" * 100})
    _mk_extract(tgt, {"audio/idx0001.wav": b"DIFFERENT" * 100})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\a.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["flagged"]) == 1
    assert not plan["audio"]["matched"] and not plan["audio"]["remapped"]

    res = mod_transfer.apply_transfer(src, tgt, plan)
    assert res["audio"] == 0
    assert staged_changes.load(tgt).get("audio") in (None, {})

    # ...unless the user opts in.
    res2 = mod_transfer.apply_transfer(src, tgt, plan, include_flagged=True)
    assert res2["audio"] == 1
    assert staged_changes.load(tgt)["audio"]["audio/idx0001.wav"] == r"C:\r\a.mp3"


def test_audio_missing_sound_is_dropped(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0009.wav": b"GONE" * 100})
    _mk_extract(tgt, {"audio/idx0001.wav": b"stays" * 100})
    staged_changes.save(src, {"audio": {"audio/idx0009.wav": r"C:\r\g.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["dropped"]) == 1
    assert plan["totals"]["transfer"] == 0


def test_image_matches_by_relpath(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, images={"images/logo.png": b"PNGDATA"})
    _mk_extract(tgt, {}, images={"images/logo.png": b"PNGDATA-v2"})
    staged_changes.save(src, {"image": {"images/logo.png": r"C:\r\logo.png"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["image"]["matched"]) == 1
    # Same name, different stock art -> flagged as content_changed (still moves).
    assert plan["image"]["matched"][0]["content_changed"] is True

    mod_transfer.apply_transfer(src, tgt, plan)
    assert staged_changes.load(tgt)["image"]["images/logo.png"] == r"C:\r\logo.png"


def test_image_gone_is_dropped(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, images={"images/old.png": b"X"})
    _mk_extract(tgt, {}, images={"images/other.png": b"Y"})
    staged_changes.save(src, {"image": {"images/old.png": r"C:\r\old.png"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert not plan["image"]["matched"]
    assert len(plan["image"]["dropped"]) == 1


def test_text_transfers_by_original(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, strings=[
        ("a/scene.radium", "HELLO", "GOODBYE"),   # edited
        ("b/scene.radium", "UNCHANGED", ""),      # not edited
        ("c/scene.radium", "REMOVED", "NEW"),     # edited, but original gone in tgt
    ])
    _mk_extract(tgt, {}, strings=[
        ("a/scene.radium", "HELLO", ""),
        ("d/scene.radium", "HELLO", ""),          # same original in a 2nd scene
        ("b/scene.radium", "UNCHANGED", ""),
    ])
    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["text"]["matched"]) == 1
    assert plan["text"]["matched"][0]["targets"] == 2   # applies to both scenes
    assert len(plan["text"]["dropped"]) == 1

    mod_transfer.apply_transfer(src, tgt, plan)
    rows = {(r["path"], r["original"]): r["replacement"]
            for r in text_manifest.load(tgt)}
    assert rows[("a/scene.radium", "HELLO")] == "GOODBYE"
    assert rows[("d/scene.radium", "HELLO")] == "GOODBYE"
    assert rows[("b/scene.radium", "UNCHANGED")] == ""


def test_apply_preserves_existing_target_edits(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0001.wav": b"A" * 300})
    _mk_extract(tgt, {"audio/idx0001.wav": b"A" * 300,
                      "audio/idx0002.wav": b"B" * 300})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\a.mp3"}})
    # target already has an edit on a different slot
    staged_changes.save(tgt, {"audio": {"audio/idx0002.wav": r"C:\r\b.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    mod_transfer.apply_transfer(src, tgt, plan)
    saved = staged_changes.load(tgt)["audio"]
    assert saved["audio/idx0001.wav"] == r"C:\r\a.mp3"
    assert saved["audio/idx0002.wav"] == r"C:\r\b.mp3"
