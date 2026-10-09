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
true on Linux and wrong on macOS.  These pin both halves.  The debugfs path now
looks every path up in one session and plans before it writes, so whether a file
is there (and whether its directory is) comes from that look-up.
"""

import os

import pytest

from pinball_decryptor.core import ext4_grow
from tests._debugfs_fake import FakeDebugfs


def _fake_tools():
    return {"debugfs": "/x/debugfs", "e2fsck": "/x/e2fsck"}


def _env(monkeypatch, fake, calls):
    def fake_run_tool(argv, timeout, what):
        calls.append(argv)
        if "stats -h" in argv:
            return 0, "Block size: 4096\nFree blocks: 999999\n"
        assert os.path.basename(argv[0]) == "e2fsck", argv
        return 0, "clean"
    monkeypatch.setattr(ext4_grow, "_find_e2fsprogs", _fake_tools)
    monkeypatch.setattr(ext4_grow, "_run_tool", fake_run_tool)
    monkeypatch.setattr(ext4_grow, "_debugfs_session", fake)


def _writes(fake):
    return [c for w, cmds, _d in fake.sessions if w for c in cmds]


def test_debugfs_creates_a_file_the_card_never_had(monkeypatch, tmp_path):
    """No kill_file, no rm - just write - and the inode appears."""
    src = tmp_path / "ours.radium"
    src.write_bytes(b"x" * 5000)
    fake, logs = FakeDebugfs({}, {"/gz", "/gz/assets", "/gz/assets/lcd",
                                  "/gz/assets/lcd/ours"}), []
    _env(monkeypatch, fake, [])

    grown = ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0,
        [("gz/assets/lcd/ours/scene.radium", str(src))],
        lambda m, lvl="info": logs.append(m), lambda: False, 600)

    assert grown == 1
    assert fake.files == {"/gz/assets/lcd/ours/scene.radium": 5000}
    writes = _writes(fake)
    assert not any(c.startswith("kill_file") for c in writes), \
        "kill_file on a file that does not exist yet"
    assert not any(c.startswith("rm ") for c in writes), \
        "rm on a file that does not exist yet"
    assert any(c.startswith("write ") for c in writes)
    assert "  creating gz/assets/lcd/ours/scene.radium (new file)" in logs


def test_debugfs_still_frees_the_old_blocks_when_replacing(monkeypatch, tmp_path):
    """The existing-file path is unchanged: kill_file + rm + write, in order."""
    src = tmp_path / "big.mp4"
    src.write_bytes(b"x" * 5000)
    fake = FakeDebugfs({"/video/a.mov": 100}, {"/video"})
    _env(monkeypatch, fake, [])

    grown = ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0, [("video/a.mov", str(src))],
        lambda *a, **k: None, lambda: False, 600)

    assert grown == 1
    seq = _writes(fake)
    assert seq[0].startswith("kill_file") and seq[1].startswith("rm ") \
        and seq[2].startswith("write ")


def test_debugfs_refuses_when_the_parent_directory_is_missing(monkeypatch, tmp_path):
    """Match the Linux path's PAD_GROW_NODIR guard, and name the directory - before
    anything is written, the files ahead of it included."""
    ok = tmp_path / "ok.bin"
    ok.write_bytes(b"x" * 10)
    src = tmp_path / "ours.bin"
    src.write_bytes(b"x" * 10)
    fake, calls = FakeDebugfs({"/gz/ok.bin": 5}, {"/gz"}), []
    _env(monkeypatch, fake, calls)

    with pytest.raises(ext4_grow.Ext4GrowError) as e:
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0,
            [("gz/ok.bin", str(ok)), ("gz/nope/ours.bin", str(src))],
            lambda *a, **k: None, lambda: False, 600)
    assert "/gz/nope does not exist" in str(e.value) and e.value.grown == 0
    assert _writes(fake) == [] and fake.files == {"/gz/ok.bin": 5}
    assert not any("e2fsck" in c[0] for c in calls)        # nothing was touched


def test_debugfs_makes_a_scene_assets_directory_only_under_its_scene(monkeypatch, tmp_path):
    """item 164: a clip grafted into a scene with no asset files lands in a
    ``scene.assets`` the card never had - made once, under a scene directory that is
    there.  Without the scene directory, the job is refused by name."""
    clips = []
    for n in range(2):
        p = tmp_path / ("c%d" % n)
        p.write_bytes(b"x" * 100)
        clips.append(("gz/hud/scene.assets/%d.asset" % n, str(p)))
    fake = FakeDebugfs({}, {"/gz", "/gz/hud"})
    _env(monkeypatch, fake, [])
    assert ext4_grow._grow_files_debugfs(
        str(tmp_path / "card.raw"), 0, clips, lambda *a, **k: None, lambda: False, 600) == 2
    assert [c for c in _writes(fake) if c.startswith("mkdir")] == [
        'mkdir "/gz/hud/scene.assets"']

    fake = FakeDebugfs({}, {"/gz"})
    _env(monkeypatch, fake, [])
    with pytest.raises(ext4_grow.Ext4GrowError, match="/gz/hud/scene.assets does not exist"):
        ext4_grow._grow_files_debugfs(
            str(tmp_path / "card.raw"), 0, clips, lambda *a, **k: None, lambda: False, 600)
    assert _writes(fake) == []


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
