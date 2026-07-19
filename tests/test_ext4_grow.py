"""Tests for core.ext4_grow — the ext4 file-growth helper used to keep
oversized replacement videos full-quality instead of crushing them into their
slot.  The mount/copy itself needs a Linux (WSL2) host and the macOS path
needs Homebrew e2fsprogs, so these cover the pure, deterministic pieces: the
generated shell script, the no-jobs / bad input guards, and the debugfs
command sequence (with the tool invocations stubbed).  The real round-trips
are exercised manually against a card image (documented in the module)."""

import os

import pytest

from pinball_decryptor.core import ext4_grow


def test_bash_script_has_the_critical_steps_and_is_quoted():
    jobs = [("turtles_pro/assets/lcd/x/2.asset/341.asset", "/mnt/c/src a.mp4")]
    script = ext4_grow._bash_script(
        364904448, jobs, "/mnt/c/img with space.raw")
    # Loop device at the partition offset, mounted, cleaned up via a trap.
    assert "losetup --find --show -o \"$OFF\"" in script
    assert "OFF=364904448" in script
    assert "trap cleanup EXIT" in script
    assert 'mount "$LOOP" "$MP"' in script
    # Mountpoint is a fresh temp dir — /mnt is not universally writable
    # (read-only on macOS, may not exist elsewhere).
    assert "MP=$(mktemp -d" in script
    # Free-space guard before any copy (fail clearly, not ENOSPC mid-write).
    assert "PAD_GROW_ENOSPC" in script
    # The copy + a per-file OK marker the caller counts.
    assert "PAD_GROW_OK 0" in script
    # Paths with spaces are shell-quoted (single-quoted by shlex).
    assert "'/mnt/c/src a.mp4'" in script
    assert "'/mnt/c/img with space.raw'" in script
    # Final sync so bytes hit the image before we unmount.
    assert script.rstrip().endswith('echo "PAD_GROW_DONE"')


def test_grow_files_no_jobs_is_a_noop():
    # No jobs (or only jobs whose source is missing) -> 0, without touching WSL.
    assert ext4_grow.grow_files("/whatever.raw", 0, []) == 0
    assert ext4_grow.grow_files(
        "/whatever.raw", 0, [("a/b.asset", "/does/not/exist.mp4")]) == 0


def test_available_on_macos_requires_e2fsprogs(monkeypatch):
    monkeypatch.setattr(ext4_grow.sys, "platform", "darwin")
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", lambda: None)
    ok, msg = ext4_grow.available()
    assert not ok
    assert "brew install e2fsprogs" in msg

    monkeypatch.setattr(
        ext4_grow, "_find_e2fsprogs",
        lambda: {"debugfs": "/x/debugfs", "dumpe2fs": "/x/dumpe2fs",
                 "e2fsck": "/x/e2fsck"})
    ok, msg = ext4_grow.available()
    assert ok


def _fake_tools():
    return {"debugfs": "/x/debugfs", "dumpe2fs": "/x/dumpe2fs",
            "e2fsck": "/x/e2fsck"}


def test_debugfs_grow_sequence_and_fsck(monkeypatch, tmp_path):
    """The macOS path issues kill_file + rm + write per job, verifies the
    written size, and always finishes with e2fsck -fy."""
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)

    calls = []

    def fake_run_tool(argv, timeout, what):
        calls.append(argv)
        tool = os.path.basename(argv[0])
        if tool == "dumpe2fs":
            return 0, "Block size:               4096\n" \
                      "Free blocks:              8282\n"
        if tool == "e2fsck":
            return 1, "FILE SYSTEM WAS MODIFIED"       # 1 = fixed, expected
        # debugfs: stat reports the new size once the write happened
        if any(a.startswith("stat ") for a in argv):
            wrote = any("write " in " ".join(c) for c in calls[:-1])
            return 0, "Size: %d" % (5000 if wrote else 100)
        return 0, "debugfs 1.47.0"

    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", _fake_tools)
    monkeypatch.setattr(ext4_grow, "_run_tool", fake_run_tool)

    grown = ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 1048576,
        [("video/a.mov", str(src))], lambda *a, **k: None, lambda: False, 600)
    assert grown == 1

    flat = [" ".join(c) for c in calls]
    # Partition opened at its raw offset via unix_io's ?offset= suffix.
    assert any("?offset=1048576" in s for s in flat)
    seq = [s for s in flat if "/x/debugfs" in s and "-w" in s]
    assert "kill_file" in seq[0] and "rm " in seq[1] and "write " in seq[2]
    # e2fsck -fy always runs after a write (debugfs leaves counts stale).
    assert any("/x/e2fsck" in s and "-fy" in s for s in flat)


def test_debugfs_grow_enospc_fails_before_writing(monkeypatch, tmp_path):
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)

    def fake_run_tool(argv, timeout, what):
        tool = os.path.basename(argv[0])
        if tool == "dumpe2fs":
            return 0, "Block size:               1024\n" \
                      "Free blocks:              1\n"    # 1 KiB free
        if any(a.startswith("stat ") for a in argv):
            return 0, "Size: 100"
        raise AssertionError("must not write when out of space: %s" % argv)

    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", _fake_tools)
    monkeypatch.setattr(ext4_grow, "_run_tool", fake_run_tool)

    with pytest.raises(ext4_grow.Ext4GrowError, match="free space"):
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0,
            [("video/a.mov", str(src))],
            lambda *a, **k: None, lambda: False, 600)


def test_debugfs_grow_partial_failure_reports_grown_count(monkeypatch,
                                                          tmp_path):
    """A mid-run failure still fscks the image and carries how many files
    landed, so the Write summary stays honest."""
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    jobs = [("video/a.mov", str(src)), ("video/b.mov", str(src))]

    state = {"writes": 0, "fsck": 0}

    def fake_run_tool(argv, timeout, what):
        tool = os.path.basename(argv[0])
        joined = " ".join(argv)
        if tool == "dumpe2fs":
            return 0, "Block size: 4096\nFree blocks: 999999\n"
        if tool == "e2fsck":
            state["fsck"] += 1
            return 0, "clean"
        if "write " in joined:
            state["writes"] += 1
            if "b.mov" in joined:
                return 0, "write: Could not allocate block"   # 2nd file fails
            return 0, "Allocated inode: 13"
        if any(a.startswith("stat ") for a in argv):
            return 0, "Size: 5000"
        return 0, "debugfs 1.47.0"

    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", _fake_tools)
    monkeypatch.setattr(ext4_grow, "_run_tool", fake_run_tool)

    with pytest.raises(ext4_grow.Ext4GrowError) as ei:
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0, jobs,
            lambda *a, **k: None, lambda: False, 600)
    assert ei.value.grown == 1        # a.mov landed before b.mov failed
    assert state["fsck"] == 1         # the image was still reconciled
