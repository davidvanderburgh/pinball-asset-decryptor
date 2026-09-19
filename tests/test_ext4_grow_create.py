"""Creating a file the card never had (core.ext4_grow), for item 129.

``.sidx`` can now index a brand-new file, which only helps if delivery can put one
on the card.  Both growth paths were written for REPLACING an existing asset, and
they diverge on a file that is not there yet:

  * the Linux path already creates it - its free-space arithmetic is
    ``cur=$([ -f tgt ] && stat -c%s tgt || echo 0)`` and the write is a plain ``cp``,
    which creates.  It refuses only when the parent DIRECTORY is missing
    (``PAD_GROW_NODIR``);
  * the macOS/debugfs path did NOT.  It issued ``kill_file`` then ``rm``
    unconditionally, and ``_debugfs`` raises when the output says "not found", so a
    new file died on the first command.

So the queue entry's "delivery already exists and has simply never been asked" was
true on Linux and wrong on macOS.  These pin both halves.
"""

import os

import pytest

from pinball_decryptor.core import ext4_grow


def _fake_tools():
    return {"debugfs": "/x/debugfs", "e2fsck": "/x/e2fsck"}


def _stub(calls, *, exists_before, parent_ok=True, size=5000, target=None):
    """A ``_run_tool`` stub where the target may or may not exist yet.

    A ``stat`` is either the probe for the FILE or the probe for its parent
    DIRECTORY, and the two need opposite answers when a file is being created.
    They are told apart by comparing the stat's path against the job's own path
    rather than by guessing at a suffix -- an earlier version keyed on the end of
    the joined argv and silently answered "missing" to the directory probe, which
    made a correct guard look like a bug in the code under test.
    """
    def fake_run_tool(argv, timeout, what):
        calls.append(argv)
        tool = os.path.basename(argv[0])
        if "stats -h" in argv:
            return 0, "Block size: 4096\nFree blocks: 999999\n"
        if tool == "e2fsck":
            return 0, "clean"
        stat_arg = next((a for a in argv if a.startswith("stat ")), None)
        if stat_arg is not None:
            path = stat_arg[len("stat "):].strip().strip('"').lstrip("/")
            if target is not None and path != target:
                # the parent directory probe
                return (0, "Inode: 12   Type: directory") if parent_ok \
                    else (1, "stat: File not found by ext2_lookup")
            wrote = any("write " in " ".join(c) for c in calls[:-1])
            if wrote:
                return 0, "Size: %d" % size
            if exists_before:
                return 0, "Size: 100"
            return 1, "stat: File not found by ext2_lookup while looking up"
        return 0, "debugfs 1.47.0"
    return fake_run_tool


def test_debugfs_creates_a_file_the_card_never_had(monkeypatch, tmp_path):
    """No kill_file, no rm - just write - and the inode appears."""
    src = tmp_path / "ours.radium"
    src.write_bytes(b"x" * 5000)
    calls = []
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", _fake_tools)
    monkeypatch.setattr(
        ext4_grow, "_run_tool",
        _stub(calls, exists_before=False,
              target="gz/assets/lcd/ours/scene.radium"))

    grown = ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0,
        [("gz/assets/lcd/ours/scene.radium", str(src))],
        lambda *a, **k: None, lambda: False, 600)

    assert grown == 1
    flat = [" ".join(c) for c in calls]
    writes = [s for s in flat if "-w" in s]
    assert not any("kill_file" in s for s in writes), \
        "kill_file on a file that does not exist yet"
    assert not any(" rm " in s for s in writes), \
        "rm on a file that does not exist yet"
    assert any("write " in s for s in writes)


def test_debugfs_still_frees_the_old_blocks_when_replacing(monkeypatch, tmp_path):
    """The existing-file path is unchanged: kill_file + rm + write, in order."""
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    calls = []
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", _fake_tools)
    monkeypatch.setattr(
        ext4_grow, "_run_tool",
        _stub(calls, exists_before=True, target="video/a.mov"))

    grown = ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0, [("video/a.mov", str(src))],
        lambda *a, **k: None, lambda: False, 600)

    assert grown == 1
    seq = [" ".join(c) for c in calls if "-w" in " ".join(c)]
    assert "kill_file" in seq[0] and " rm " in seq[1] and "write " in seq[2]


def test_debugfs_refuses_when_the_parent_directory_is_missing(monkeypatch, tmp_path):
    """Match the Linux path's PAD_GROW_NODIR guard, and name the directory."""
    src = tmp_path / "ours.bin"
    src.write_bytes(b"x" * 10)
    calls = []
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", _fake_tools)
    monkeypatch.setattr(
        ext4_grow, "_run_tool",
        _stub(calls, exists_before=False, parent_ok=False,
              target="gz/nope/ours.bin"))

    with pytest.raises(ext4_grow.Ext4GrowError) as e:
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0, [("gz/nope/ours.bin", str(src))],
            lambda *a, **k: None, lambda: False, 600)
    assert "does not exist" in str(e.value)


def test_linux_script_creates_rather_than_requiring_the_file():
    """The generated script must not assume the target exists: its size probe
    degrades to 0 and the copy is a plain cp, which creates."""
    script = ext4_grow._bash_script(
        4096, [("gz/assets/lcd/ours/scene.radium", "/tmp/ours.radium")],
        "/tmp/card.raw")
    assert "|| echo 0" in script, "size probe must tolerate a missing target"
    # shlex only quotes when it has to, so a plain path arrives bare.
    assert "cp /tmp/ours.radium " in script
    # ...but a missing DIRECTORY is still refused, loudly and by name.
    assert "PAD_GROW_NODIR" in script
