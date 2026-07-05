"""Tests for core.ext4_grow — the ext4 file-growth helper used to keep
oversized replacement videos full-quality instead of crushing them into their
slot.  The mount/copy itself needs a Linux (WSL2) host, so these cover the
pure, deterministic pieces: the generated shell script and the no-jobs / bad
input guards.  The real mount round-trip is exercised manually against a card
image (documented in the module)."""

from pinball_decryptor.core import ext4_grow


def test_bash_script_has_the_critical_steps_and_is_quoted():
    jobs = [("turtles_pro/assets/lcd/x/2.asset/341.asset", "/mnt/c/src a.mp4")]
    script = ext4_grow._bash_script(
        364904448, "/mnt/pad_grow_1", jobs, "/mnt/c/img with space.raw")
    # Loop device at the partition offset, mounted, cleaned up via a trap.
    assert "losetup --find --show -o \"$OFF\"" in script
    assert "OFF=364904448" in script
    assert "trap cleanup EXIT" in script
    assert 'mount "$LOOP" "$MP"' in script
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
