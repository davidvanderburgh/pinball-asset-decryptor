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
from tests._debugfs_fake import FakeDebugfs


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
    # Genuinely nothing to do -> 0, without touching WSL.
    assert ext4_grow.grow_files("/whatever.raw", 0, []) == 0


def test_grow_files_refuses_to_drop_a_job_whose_source_vanished():
    """A missing source is a bug, and has to be loud.

    This used to return 0 silently, which is exactly how the blip-free build
    shipped broken cards: engine._compute_patches wrote the rebuilt firmware
    into a scratch dir it then deleted in its own ``finally``, so by the time
    the caller ran the grow the file was gone.  The job was dropped without a
    word, the caller read "0 grown" as an ordinary failure, and the card went
    out with its .sidx already rewritten to describe a firmware that had never
    been copied on (and, because the blip-free path skips the in-place
    validator bypass, with the validator still armed) -- a card the machine
    rejects with GAME VALIDATION ERROR.
    """
    lines = []
    with pytest.raises(ext4_grow.Ext4GrowError, match="could be found on disk"):
        ext4_grow.grow_files(
            "/whatever.raw", 0, [("a/b.asset", "/does/not/exist.mp4")],
            log=lambda m, lvl="info": lines.append((m, lvl)))
    assert any(lvl == "error" and "a/b.asset" in m for m, lvl in lines)


class _FakeExecutor:
    """WSL-shaped executor double: reachable as root, but whether the kernel
    hands out loop devices is up to the test."""

    def __init__(self, loop_ok=True):
        self.loop_ok = loop_ok
        self.commands = []

    def check_available(self):
        return True, "WSL2 available"

    def run(self, cmd, timeout=120):
        self.commands.append(cmd)
        if "losetup" in cmd and not self.loop_ok:
            raise RuntimeError(
                "Command failed (exit 32): %s\nlosetup: cannot find an "
                "unused loop device: No such file or directory" % cmd)
        return "ok\n"

    def to_exec_path(self, p):
        return p


def test_available_probes_loop_devices_not_just_wsl_reachability(monkeypatch):
    """PAD-13: a WSL 1 distro answers ``echo ok`` as root but owns zero loop
    devices, so available() said yes, all 489 of a user's replaced videos
    were planned as grow jobs, the blip-free preflight let the .sidx be
    rewritten — and then every job died on losetup.  available() must fail on
    such a host so both graceful fallbacks (fit-in-slot videos, standard
    audio build) actually engage."""
    monkeypatch.setattr(ext4_grow.sys, "platform", "win32")
    ex = _FakeExecutor(loop_ok=False)
    monkeypatch.setattr(ext4_grow, "create_executor", lambda: ex)
    ok, msg = ext4_grow.available()
    assert not ok
    assert "wsl --set-version" in msg      # the actual fix, named
    assert "losetup" in msg                # the probe's own evidence
    assert any("losetup" in c for c in ex.commands)


def test_available_ok_when_loop_probe_passes(monkeypatch):
    monkeypatch.setattr(ext4_grow.sys, "platform", "win32")
    ex = _FakeExecutor(loop_ok=True)
    monkeypatch.setattr(ext4_grow, "create_executor", lambda: ex)
    ok, _msg = ext4_grow.available()
    assert ok
    assert any("losetup" in c for c in ex.commands)


def test_grow_files_raises_unavailable_not_error_on_loopless_host(
        monkeypatch, tmp_path):
    """Runtime double-check: even a caller that skipped available() must get
    the *Unavailable* subclass (warning + honest fallback counts) BEFORE any
    mount attempt — a loop-less host used to reach losetup inside the mount
    script and surface as a raw Ext4GrowError with no hint at the fix."""
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 100)
    monkeypatch.setattr(ext4_grow.sys, "platform", "win32")
    ex = _FakeExecutor(loop_ok=False)
    monkeypatch.setattr(ext4_grow, "create_executor", lambda: ex)
    with pytest.raises(ext4_grow.Ext4GrowUnavailable, match="loop device"):
        ext4_grow.grow_files("/card.raw", 4096, [("video/a.mov", str(src))])
    assert not any("base64" in c for c in ex.commands)  # never got to mount


def test_loop_probe_reason_on_native_linux_names_modprobe(monkeypatch):
    monkeypatch.setattr(ext4_grow.sys, "platform", "linux")
    reason = ext4_grow.loop_unavailable_reason(_FakeExecutor(loop_ok=False))
    assert "modprobe loop" in reason
    assert "losetup" in reason


def test_available_on_macos_requires_e2fsprogs(monkeypatch):
    monkeypatch.setattr(ext4_grow.sys, "platform", "darwin")
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", lambda: None)
    ok, msg = ext4_grow.available()
    assert not ok
    assert "brew install e2fsprogs" in msg

    monkeypatch.setattr(
        ext4_grow, "_find_e2fsprogs",
        lambda: {"debugfs": "/x/debugfs", "e2fsck": "/x/e2fsck"})
    ok, msg = ext4_grow.available()
    assert ok


def _fake_tools():
    return {"debugfs": "/x/debugfs", "e2fsck": "/x/e2fsck"}


def _tools_stub(calls, free_blocks=999999, block_size=4096):
    """``_run_tool`` for the two steps that still run alone: the free-space read
    and the closing e2fsck (exit 1 = "errors corrected", expected)."""
    def fake_run_tool(argv, timeout, what):
        calls.append(argv)
        tool = os.path.basename(argv[0])
        # Free space comes from debugfs stats, NOT dumpe2fs (whose 1.47.x
        # device resolution chokes on the ?offset= suffix).
        assert tool != "dumpe2fs"
        if "stats -h" in argv:
            return 0, "Block size:               %d\n" \
                      "Free blocks:              %d\n" % (block_size, free_blocks)
        if tool == "e2fsck":
            return 1, "FILE SYSTEM WAS MODIFIED"
        raise AssertionError("debugfs runs in sessions now: %s" % argv)
    return fake_run_tool


def _debugfs_env(monkeypatch, fake, calls, **kw):
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", _fake_tools)
    monkeypatch.setattr(ext4_grow, "_run_tool", _tools_stub(calls, **kw))
    monkeypatch.setattr(ext4_grow, "_debugfs_session", fake)


def test_debugfs_grow_sequence_and_fsck(monkeypatch, tmp_path):
    """The debugfs path looks every path up in one read-only session, then writes
    in one session a batch: kill_file + rm + write per replaced file, each read
    back by a stat, and always finishes with e2fsck -fy."""
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    fake, calls = FakeDebugfs({"/video/a.mov": 100}, {"/video"}), []
    _debugfs_env(monkeypatch, fake, calls)

    grown = ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 1048576,
        [("video/a.mov", str(src))], lambda *a, **k: None, lambda: False, 600)
    assert grown == 1 and fake.files["/video/a.mov"] == 5000

    (ro, looked, dev), (rw, wrote, _dev) = fake.sessions
    # Partition opened at its raw offset via unix_io's ?offset= suffix.
    assert dev.endswith("card.raw?offset=1048576")
    assert not ro and looked == ['stat "/video/a.mov"', 'stat "/video"']
    assert rw and wrote == ['kill_file "/video/a.mov"', 'rm "/video/a.mov"',
                            'write "%s" "/video/a.mov"' % src, 'stat "/video/a.mov"']
    # e2fsck -fy always runs after a write (debugfs leaves counts stale).
    flat = [" ".join(c) for c in calls]
    assert any("/x/e2fsck" in s and "-fy" in s for s in flat)


def test_debugfs_grow_makes_a_game_elf_executable(monkeypatch, tmp_path):
    """debugfs ``write`` creates the inode with the host file's mode, so a
    staged game ELF (opened "wb", 0644) would reach the card non-executable
    and game_monitor would loop on RESTARTING GAME.  After the write the ELF's
    inode is set to 0100755; a grown video (stock 0100664) is left alone."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\x00" * 4996)
    vid = tmp_path / "big.mp4"
    vid.write_bytes(b"x" * 5000)
    fake, calls = FakeDebugfs({"/gz/game": 100, "/video/a.mov": 100}, {"/gz", "/video"}), []
    _debugfs_env(monkeypatch, fake, calls)

    grown = ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0,
        [("gz/game", str(elf)), ("video/a.mov", str(vid))],
        lambda *a, **k: None, lambda: False, 600)
    assert grown == 2
    assert fake.fields == {("/gz/game", "mode"): "0100755"}
    wrote = fake.sessions[1][1]
    modes = [c for c in wrote if c.startswith("set_inode_field")]
    assert modes == ['set_inode_field "/gz/game" mode 0100755']
    # ...and only AFTER that file's write landed.
    assert wrote.index('write "%s" "/gz/game"' % elf) < wrote.index(modes[0])


def test_debugfs_grow_enospc_fails_before_writing(monkeypatch, tmp_path):
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    fake, calls = FakeDebugfs({"/video/a.mov": 100}, {"/video"}), []
    _debugfs_env(monkeypatch, fake, calls, block_size=1024, free_blocks=1)   # 1 KiB free

    with pytest.raises(ext4_grow.Ext4GrowError, match="free space"):
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0,
            [("video/a.mov", str(src))],
            lambda *a, **k: None, lambda: False, 600)
    assert not any(w for w, _c, _d in fake.sessions), "must not write when out of space"
    assert not any("e2fsck" in c[0] for c in calls)


def test_debugfs_grow_partial_failure_reports_grown_count(monkeypatch,
                                                          tmp_path):
    """A mid-run failure still fscks the image and carries how many files
    landed, so the Write summary stays honest.  Files land a batch at a time:
    one batch a file here."""
    monkeypatch.setattr(ext4_grow, "DEBUGFS_BATCH_FILES", 1)
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    jobs = [("video/a.mov", str(src)), ("video/b.mov", str(src))]
    fake = FakeDebugfs({"/video/a.mov": 100, "/video/b.mov": 100}, {"/video"},
                       fail={"/video/b.mov": "write: Could not allocate block"})
    calls = []
    _debugfs_env(monkeypatch, fake, calls)

    with pytest.raises(ext4_grow.Ext4GrowError) as ei:
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0, jobs,
            lambda *a, **k: None, lambda: False, 600)
    assert ei.value.grown == 1        # a.mov landed before b.mov failed
    assert "Could not allocate block" in str(ei.value)
    assert sum("e2fsck" in c[0] for c in calls) == 1   # the image was still reconciled


def test_debugfs_grow_counts_none_of_a_batch_debugfs_complains_about(monkeypatch, tmp_path):
    """debugfs does not say which file a complaint is about, so a batch with one
    counts none of its files as grown, even one it did write: a file counted that
    is not on the card would be reported (and recorded) as on it."""
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    jobs = [("video/a.mov", str(src)), ("video/b.mov", str(src))]
    fake = FakeDebugfs({"/video/a.mov": 100, "/video/b.mov": 100}, {"/video"},
                       fail={"/video/b.mov": "write: Could not allocate block"})
    calls = []
    _debugfs_env(monkeypatch, fake, calls)

    with pytest.raises(ext4_grow.Ext4GrowError, match="none of the 2 file") as ei:
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0, jobs,
            lambda *a, **k: None, lambda: False, 600)
    assert ei.value.grown == 0 and fake.files["/video/a.mov"] == 5000
    assert "video/a.mov to video/b.mov" in str(ei.value)
    assert sum("e2fsck" in c[0] for c in calls) == 1


def test_debugfs_grow_writes_in_batches_and_logs_each_file(monkeypatch, tmp_path):
    """A session a batch, not one a step of every file: 70 files are one look-up
    and three writing sessions, and each file is logged once its batch is read
    back, in order."""
    jobs, files = [], {}
    for n in range(70):
        p = tmp_path / ("s%d" % n)
        p.write_bytes(b"x" * (100 + n))
        jobs.append(("v/%d.asset" % n, str(p)))
        files["/v/%d.asset" % n] = 50
    fake, calls, logs = FakeDebugfs(files, {"/v"}), [], []
    _debugfs_env(monkeypatch, fake, calls)

    grown = ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0, jobs,
        lambda m, lvl="info": logs.append(m), lambda: False, 600)
    assert grown == 70
    assert [w for w, _c, _d in fake.sessions] == [False, True, True, True]
    assert [len(c) for w, c, _d in fake.sessions if w] == [32 * 4, 32 * 4, 6 * 4]
    assert [m for m in logs if m.startswith("  grew ")] == [
        "  grew v/%d.asset" % n for n in range(70)]


def test_debugfs_grow_stops_between_batches_when_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(ext4_grow, "DEBUGFS_BATCH_FILES", 1)
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    jobs = [("video/a.mov", str(src)), ("video/b.mov", str(src))]
    fake = FakeDebugfs({"/video/a.mov": 100, "/video/b.mov": 100}, {"/video"})
    calls = []
    _debugfs_env(monkeypatch, fake, calls)
    asked = []

    def cancel():
        asked.append(1)
        return len(asked) > 1               # go on with the first batch only

    assert ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0, jobs, lambda *a, **k: None, cancel, 600) == 1
    assert fake.files == {"/video/a.mov": 5000, "/video/b.mov": 100}
    assert sum("e2fsck" in c[0] for c in calls) == 1


def test_debugfs_grow_names_a_file_that_came_out_short(monkeypatch, tmp_path):
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    fake = FakeDebugfs({"/video/a.mov": 100}, {"/video"}, short={"/video/a.mov": 4096})
    _debugfs_env(monkeypatch, fake, [])
    with pytest.raises(ext4_grow.Ext4GrowError, match="4096 B of 5000 B for video/a.mov") as ei:
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0, [("video/a.mov", str(src))],
            lambda *a, **k: None, lambda: False, 600)
    assert ei.value.grown == 0


def test_debugfs_grow_refuses_a_path_debugfs_cannot_take(monkeypatch, tmp_path):
    """A command a line, its paths in double quotes: a quote or a line break in a
    path is refused before the card is opened."""
    src = tmp_path / 'say "hi".mp4'
    src.write_bytes(b"x" * 10)
    fake = FakeDebugfs({}, {"/video"})
    _debugfs_env(monkeypatch, fake, [])
    with pytest.raises(ext4_grow.Ext4GrowError, match="double quote"):
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0, [("video/a.mov", str(src))],
            lambda *a, **k: None, lambda: False, 600)
    assert fake.sessions == []


# ---- PAD-314 (Ales, Linux desktop): native Linux writes with debugfs, as a Mac does ----------
def test_available_on_linux_takes_the_debugfs_route_without_root(monkeypatch):
    """Every build on a Linux desktop left its new files off the card: the loop mount
    needs root, and a GUI app has no terminal for sudo to ask on, so the probe died
    before it ran. debugfs writes the user's own image as the user."""
    monkeypatch.setattr(ext4_grow.sys, "platform", "linux")
    ex = _FakeExecutor(loop_ok=False)
    monkeypatch.setattr(ext4_grow, "create_executor", lambda: ex)
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs",
                        lambda: {"debugfs": "/sbin/debugfs", "e2fsck": "/sbin/e2fsck"})
    ok, msg = ext4_grow.available()
    assert ok and "debugfs" in msg
    assert ex.commands == []                      # no loop probe, no sudo
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", lambda: None)
    ok, msg = ext4_grow.available()
    assert not ok and "apt install e2fsprogs" in msg and "brew" not in msg


def test_grow_files_on_linux_goes_through_debugfs(monkeypatch, tmp_path):
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 100)
    monkeypatch.setattr(ext4_grow.sys, "platform", "linux")
    seen = []
    monkeypatch.setattr(ext4_grow, "_grow_files_debugfs",
                        lambda *a, **k: (seen.append(a), 1)[1])
    monkeypatch.setattr(ext4_grow, "create_executor",
                        lambda: (_ for _ in ()).throw(AssertionError("no executor on Linux")))
    assert ext4_grow.grow_files("/card.raw", 4096, [("video/a.mov", str(src))]) == 1
    assert seen and seen[0][0] == "/card.raw" and seen[0][1] == 4096


def test_e2fsprogs_is_looked_for_in_sbin_on_linux(monkeypatch, tmp_path):
    """Debian keeps debugfs in /sbin, which a user's PATH leaves out."""
    import shutil
    assert "/sbin" in ext4_grow.E2FSPROGS_DIRS and "/usr/sbin" in ext4_grow.E2FSPROGS_DIRS
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    for name in ("debugfs", "e2fsck"):
        (sbin / name).write_bytes(b"")
    monkeypatch.setattr(ext4_grow, "E2FSPROGS_DIRS", (str(sbin),))
    monkeypatch.setattr(shutil, "which", lambda n: None)
    assert ext4_grow._find_e2fsprogs() == {"debugfs": str(sbin / "debugfs"),
                                           "e2fsck": str(sbin / "e2fsck")}
    monkeypatch.setattr(ext4_grow, "E2FSPROGS_DIRS", (str(tmp_path / "nowhere"),))
    assert ext4_grow._find_e2fsprogs() is None


def test_debugfs_grow_links_a_source_path_too_long_for_a_command_line(monkeypatch, tmp_path):
    """debugfs splits a command line longer than its BUFSIZ buffer (1,024 bytes on
    macOS): such a write goes through a short link to the source, removed afterwards."""
    monkeypatch.setattr(ext4_grow, "DEBUGFS_LINE_MAX", 60)
    deep = tmp_path / ("d" * 80)
    deep.mkdir()
    src = deep / "big.mp4"
    src.write_bytes(b"x" * 5000)
    fake = FakeDebugfs({"/video/a.mov": 100}, {"/video"})
    _debugfs_env(monkeypatch, fake, [])
    assert ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0, [("video/a.mov", str(src))],
        lambda *a, **k: None, lambda: False, 600) == 1
    write = next(c for w, cmds, _d in fake.sessions for c in cmds if c.startswith("write "))
    link = write.split('"')[1]
    assert link != str(src) and "pad_debugfs_" in link
    assert fake.files["/video/a.mov"] == 5000 and not os.path.exists(os.path.dirname(link))
