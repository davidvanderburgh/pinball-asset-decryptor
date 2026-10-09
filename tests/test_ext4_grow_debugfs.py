"""The macOS / native Linux debugfs delivery (``ext4_grow._grow_files_debugfs``) against
real e2fsprogs: a small ext4 at an offset inside an image, as a partition sits in a card.

It writes in a few debugfs sessions - one look-up, then one a batch - instead of one for
every step of every file (a 307-file delivery went from 1,644 debugfs runs to 13).  These
check that what lands is what the jobs asked for, and that a batch debugfs complains about
counts none of its files.  Skipped where e2fsprogs is missing (Windows, the macOS runner);
tests/test_ext4_grow.py covers the same logic there through a fake.
"""
import os
import subprocess

import pytest

from pinball_decryptor.core import ext4_grow
from tests.test_ext4_grow_pinned import OFF, _card, _jobs, needs_e2fs


def _sessions(monkeypatch):
    seen = []
    real = ext4_grow._debugfs_session

    def counting(tools, dev, commands, timeout, writable=False):
        seen.append(writable)
        return real(tools, dev, commands, timeout, writable)
    monkeypatch.setattr(ext4_grow, "_debugfs_session", counting)
    return seen


def _cat(ref, rel):
    return subprocess.run(["debugfs", "-R", 'cat "/%s"' % rel, ref], capture_output=True).stdout


@needs_e2fs
def test_a_delivery_in_batches_lands_every_file(tmp_path, monkeypatch):
    """Replaced files, a file the card never had, a scene.assets made for two clips and
    the game program, two files a batch: every file as its source, the game executable,
    and e2fsck clean."""
    monkeypatch.setattr(ext4_grow, "DEBUGFS_BATCH_FILES", 2)
    card = _card(tmp_path)
    jobs = _jobs(tmp_path)
    for n in range(2):
        p = tmp_path / ("clip%d" % n)
        p.write_bytes(os.urandom(30000 + n))
        jobs.append(("g/bank/scene.assets/%d.asset" % n, str(p)))
    seen = _sessions(monkeypatch)
    logs = []

    grown = ext4_grow._grow_files_debugfs(str(card), OFF, jobs,
                                          lambda m, lvl="info": logs.append(m),
                                          lambda: False, 600)
    assert grown == len(jobs) == 6
    assert seen == [False, True, True, True]            # one look-up, three batches
    ref = "%s?offset=%d" % (card, OFF)
    assert subprocess.run(["e2fsck", "-fn", ref], capture_output=True).returncode == 0
    for rel, src in jobs:
        assert _cat(ref, rel) == open(src, "rb").read(), rel
    game = subprocess.run(["debugfs", "-R", 'stat "/g/game"', ref], capture_output=True,
                          text=True).stdout
    assert "Mode:  0755" in game
    assert [m for m in logs if m.startswith("  grew ")] == ["  grew %s" % r for r, _s in jobs]
    assert sum("creating" in m for m in logs) == 3      # 598.asset and the two clips


@needs_e2fs
def test_a_batch_debugfs_complains_about_counts_none_of_its_files(tmp_path, monkeypatch):
    """A file under the game program (its "directory" is a file, which only debugfs
    finds) fails its batch: the batch before it counts, that batch does not, nothing
    after it runs, and the partition is still reconciled."""
    monkeypatch.setattr(ext4_grow, "DEBUGFS_BATCH_FILES", 2)
    card = _card(tmp_path)
    jobs = _jobs(tmp_path)
    bad = tmp_path / "bad"
    bad.write_bytes(b"x" * 100)
    jobs = jobs[:3] + [("g/game/x.asset", str(bad)), jobs[3]]
    seen = _sessions(monkeypatch)

    with pytest.raises(ext4_grow.Ext4GrowError) as ei:
        ext4_grow._grow_files_debugfs(str(card), OFF, jobs, lambda *a, **k: None,
                                      lambda: False, 600)
    assert ei.value.grown == 2
    assert "g/bank/598.asset to g/game/x.asset" in str(ei.value)
    assert "none of the 2 file(s)" in str(ei.value) and "not a directory" in str(ei.value)
    assert seen == [False, True, True]
    ref = "%s?offset=%d" % (card, OFF)
    assert subprocess.run(["e2fsck", "-fn", ref], capture_output=True).returncode == 0
    for rel, src in jobs[:2]:
        assert _cat(ref, rel) == open(src, "rb").read(), rel


@needs_e2fs
def test_a_source_path_too_long_for_a_command_line_goes_through_a_link(tmp_path, monkeypatch):
    """debugfs reads a command file a BUFSIZ line at a time (1,024 bytes on macOS) and
    splits a longer one; a write whose source path would make it too long goes through
    a short link to the source instead, which is gone afterwards."""
    monkeypatch.setattr(ext4_grow, "DEBUGFS_LINE_MAX", 120)
    card = _card(tmp_path)
    deep = tmp_path / ("d" * 100) / ("e" * 100)
    deep.mkdir(parents=True)
    src = deep / "clip.asset"
    src.write_bytes(os.urandom(40000))
    links = []
    real = ext4_grow._debugfs_session

    def watching(tools, dev, commands, timeout, writable=False):
        links.extend(c.split('"')[1] for c in commands if c.startswith("write "))
        return real(tools, dev, commands, timeout, writable)
    monkeypatch.setattr(ext4_grow, "_debugfs_session", watching)

    assert ext4_grow._grow_files_debugfs(str(card), OFF, [("g/bank/598.asset", str(src))],
                                         lambda *a, **k: None, lambda: False, 600) == 1
    assert len(links) == 1 and len(links[0]) < 120 and "pad_debugfs_" in links[0]
    assert not os.path.exists(os.path.dirname(links[0]))
    ref = "%s?offset=%d" % (card, OFF)
    assert _cat(ref, "g/bank/598.asset") == src.read_bytes()


@needs_e2fs
def test_a_session_keeps_debugfs_complaints_but_not_its_banner(tmp_path):
    """The version banner on stderr is not a complaint; ``debugfs: Unbalanced quotes in
    command line`` (a line split in two) is, though it starts with "debugfs" too."""
    card = _card(tmp_path)
    tools = ext4_grow._find_e2fsprogs()
    rc, out, complaints = ext4_grow._debugfs_session(
        tools, "%s?offset=%d" % (card, OFF), ['stat "/g', 'stat "/g/game"', 'stat "/nope"'], 60)
    assert rc == 0
    assert any("Unbalanced quotes" in c for c in complaints)
    assert any("/nope" in c for c in complaints)
    assert not any(c.startswith("debugfs 1.") for c in complaints)
    found = dict(ext4_grow._stat_results(out))
    assert found["/nope"] is None and found["/g/game"] > 0
