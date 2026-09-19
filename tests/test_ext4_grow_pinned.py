"""Item 149: ext4_grow's PINNED delivery - the same jobs into the same original give
the same bytes, so a second Write of a project is byte-identical.

The kernel path (loop mount + cp) differs between two identical runs in the journal,
s_last_mounted, the clocks and a new inode's random i_generation (measured: 217 bytes).
The pinned path writes through debugfs with the clock fixed and must differ in none.
The real round trips run the generated script with the local bash against a small ext4
image at an OFFSET (as a partition sits in a card image), and skip where e2fsprogs is
missing (Windows, a CI runner without it).
"""
import os
import shutil
import struct
import subprocess
import sys

import pytest

from pinball_decryptor.core import ext4_grow

EPOCH = 1785242711          # a stock Godzilla Pro 1.15 p3's last write time
OFF = 1 << 20               # the filesystem sits 1 MiB into the image

needs_e2fs = pytest.mark.skipif(
    sys.platform == "win32" or not all(shutil.which(t) for t in ("mke2fs", "debugfs", "e2fsck")),
    reason="needs e2fsprogs (mke2fs, debugfs, e2fsck) and a Linux bash")


def test_partition_epoch_is_the_latest_superblock_clock(tmp_path):
    img = tmp_path / "card.raw"
    sb = bytearray(1024)
    struct.pack_into("<II", sb, 0x2C, 1700000000, 1700000500)   # s_mtime, s_wtime
    struct.pack_into("<I", sb, 0x40, 1700000100)                # s_lastcheck
    sb[0x38:0x3A] = b"\x53\xef"
    with open(img, "wb") as f:
        f.truncate(OFF + 1024)
        f.seek(OFF + 1024)
        f.write(sb)
    assert ext4_grow.partition_epoch(str(img), OFF) == 1700000500
    with pytest.raises(ext4_grow.Ext4GrowError, match="no ext4 superblock"):
        ext4_grow.partition_epoch(str(img), 0)


def test_the_script_pins_both_clocks_and_refuses_a_double_quote():
    s = ext4_grow._pinned_script(OFF, [("g/image.bin", "/src/a")], "/x/card.raw", EPOCH)
    assert "export E2FSPROGS_FAKE_TIME=%d E2FSCK_TIME=%d" % (EPOCH, EPOCH) in s
    assert "card.raw?offset=%d" % OFF in s
    assert "PAD_GROW_OK 0 " in s and "e2fsck -fy" in s
    with pytest.raises(ext4_grow.Ext4GrowError, match="double quote"):
        ext4_grow._pinned_script(OFF, [("g/x", '/src/a"b')], "/x/card.raw", EPOCH)


def test_grow_files_pinned_refuses_a_missing_source_loudly():
    with pytest.raises(ext4_grow.Ext4GrowError, match="could not be found"):
        ext4_grow.grow_files_pinned("/whatever.raw", 0, [("a/b", "/does/not/exist")], EPOCH)


def _debugfs(ref, cmds):
    r = subprocess.run(["debugfs", "-w", "-f", "-", ref], input="\n".join(cmds) + "\n",
                       capture_output=True, text=True,
                       env=dict(os.environ, E2FSPROGS_FAKE_TIME="1700000000"))
    assert r.returncode == 0, r.stderr


def _stat(ref, path):
    return subprocess.run(["debugfs", "-R", "stat \"%s\"" % path, ref],
                          capture_output=True, text=True).stdout


def _card(tmp_path):
    """A 64 MiB ext4 at OFF inside a bigger file, with a game dir, a 'game program'
    at 0775, an asset at 0664 and a manifest at 0666, all root-owned."""
    fs = tmp_path / "fs.img"
    subprocess.run(["mke2fs", "-q", "-t", "ext4", "-b", "4096", "-E",
                    "lazy_itable_init=0,lazy_journal_init=0", str(fs), "16384"], check=True,
                   env=dict(os.environ, E2FSPROGS_FAKE_TIME="1700000000"))
    src = tmp_path / "old"
    src.mkdir()
    (src / "game").write_bytes(b"\x7fELF" + os.urandom(200000))
    (src / "scene").write_bytes(os.urandom(50000))
    (src / "sidx").write_bytes(os.urandom(30000))
    ref = str(fs)
    _debugfs(ref, ["mkdir g", "mkdir g/bank", "mkdir spk",
                   "write %s g/game" % (src / "game"),
                   "write %s g/bank/scene.radium" % (src / "scene"),
                   "write %s spk/a.sidx" % (src / "sidx"),
                   "set_inode_field g/game mode 0100775",
                   "set_inode_field g/bank/scene.radium mode 0100664",
                   "set_inode_field spk/a.sidx mode 0100666"]
             + ["set_inode_field %s %s 0" % (p, k) for p in ("g/game", "g/bank/scene.radium", "spk/a.sidx")
                for k in ("uid", "gid")])
    card = tmp_path / "card.raw"
    with open(card, "wb") as out:
        out.truncate(OFF)
        out.seek(OFF)
        out.write(fs.read_bytes())
        out.truncate(OFF + fs.stat().st_size + (1 << 20))
    return card


def _jobs(tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "game").write_bytes(b"\x7fELF" + os.urandom(300000))      # grown
    (new / "scene").write_bytes(os.urandom(70000))                   # grown
    (new / "clip").write_bytes(os.urandom(900000))                   # a file the card never had
    (new / "sidx").write_bytes(os.urandom(30100))                    # a rewritten manifest
    return [("g/game", str(new / "game")), ("g/bank/scene.radium", str(new / "scene")),
            ("g/bank/598.asset", str(new / "clip")), ("spk/a.sidx", str(new / "sidx"))]


def _run(card, jobs):
    script = ext4_grow._pinned_script(OFF, jobs, str(card), EPOCH)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


@needs_e2fs
def test_two_pinned_deliveries_are_byte_identical(tmp_path):
    base = _card(tmp_path)
    jobs = _jobs(tmp_path)
    a, b = tmp_path / "a.raw", tmp_path / "b.raw"
    shutil.copyfile(base, a)
    shutil.copyfile(base, b)
    out = _run(a, jobs)
    assert out.count("PAD_GROW_OK ") == 4 and "PAD_GROW_DONE" in out
    _run(b, jobs)
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes() != base.read_bytes()


@needs_e2fs
def test_a_pinned_delivery_lands_every_file_with_the_stock_attributes(tmp_path):
    card = _card(tmp_path)
    jobs = _jobs(tmp_path)
    _run(card, jobs)
    ref = "%s?offset=%d" % (card, OFF)
    assert subprocess.run(["e2fsck", "-fn", ref], capture_output=True).returncode == 0
    for rel, src in jobs:
        got = subprocess.run(["debugfs", "-R", "cat \"/%s\"" % rel, ref], capture_output=True).stdout
        assert got == open(src, "rb").read(), rel
    st = _stat(ref, "/g/game")
    assert "Mode:  0775" in st and "User:     0   Group:     0" in st
    assert "Mode:  0664" in _stat(ref, "/g/bank/scene.radium")
    assert "Mode:  0666" in _stat(ref, "/spk/a.sidx")
    new = _stat(ref, "/g/bank/598.asset")
    assert "Type: regular" in new and "Mode:  0664" in new and "User:     0   Group:     0" in new
    assert "mtime: 0x%08x" % EPOCH in new and "crtime: 0x%08x" % EPOCH in new


@needs_e2fs
def test_a_file_whose_directory_is_missing_stops_the_delivery(tmp_path):
    card = _card(tmp_path)
    src = tmp_path / "x"
    src.write_bytes(b"x" * 100)
    script = ext4_grow._pinned_script(OFF, [("nope/x.asset", str(src))], str(card), EPOCH)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 4 and "PAD_GROW_NODIR" in r.stderr
