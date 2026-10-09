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
    s = ext4_grow._pinned_script(OFF, [("g/image.bin", "/src/a")], "/x/card.raw", EPOCH,
                                 sizes=[5])
    assert "export E2FSPROGS_FAKE_TIME=%d E2FSCK_TIME=%d" % (EPOCH, EPOCH) in s
    assert "card.raw?offset=%d" % OFF in s
    assert "REL=(/g/image.bin)" in s and "SZ=(5)" in s and "CUT=(1)" in s
    assert 'echo "PAD_GROW_OK $i' in s and "e2fsck -fy" in s
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


@needs_e2fs
def test_a_scene_assets_directory_is_made_and_no_other(tmp_path):
    """item 164: a clip grafted into a scene with no asset files (The Munsters' HUD) lands in a
    ``scene.assets`` the card never had - made with its scene directory's mode and owner, the
    same bytes both times. Any other missing directory still stops the delivery."""
    base = _card(tmp_path)
    src = tmp_path / "clip"
    src.write_bytes(os.urandom(40000))
    jobs = [("g/bank/scene.assets/1.asset", str(src))]
    a, b = tmp_path / "a.raw", tmp_path / "b.raw"
    shutil.copyfile(base, a)
    shutil.copyfile(base, b)
    assert "PAD_GROW_MKDIR" in _run(a, jobs)
    _run(b, jobs)
    assert a.read_bytes() == b.read_bytes()
    ref = tmp_path / "ref.img"
    with open(a, "rb") as f:
        f.seek(OFF)
        ref.write_bytes(f.read(16384 * 4096))
    d, up = _stat(str(ref), "/g/bank/scene.assets"), _stat(str(ref), "/g/bank")
    assert "Type: directory" in d
    mode = lambda st: st.split("Mode:", 1)[1].split()[0]
    assert mode(d) == mode(up)
    got = subprocess.run(["debugfs", "-R", "cat /g/bank/scene.assets/1.asset", str(ref)],
                         capture_output=True).stdout
    assert got == src.read_bytes()
    for rel in ("g/nope/scene.assets/1.asset", "g/bank/other/1.asset"):
        script = ext4_grow._pinned_script(OFF, [(rel, str(src))], str(base), EPOCH)
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert r.returncode == 4 and "PAD_GROW_NODIR" in r.stderr, rel


def test_a_delivery_is_cut_into_batches_by_files_and_bytes(monkeypatch):
    """A few debugfs sessions instead of four per file: a batch ends at PINNED_BATCH_FILES
    files or PINNED_BATCH_BYTES bytes, a bigger file a batch of its own. The cut depends on
    the sizes alone, so the same project batches (and so writes) the same every build."""
    monkeypatch.setattr(ext4_grow, "PINNED_BATCH_FILES", 3)
    monkeypatch.setattr(ext4_grow, "PINNED_BATCH_BYTES", 100)
    assert ext4_grow._pinned_batches([]) == []
    assert ext4_grow._pinned_batches([1] * 7) == [3, 6, 7]
    assert ext4_grow._pinned_batches([60, 30, 20, 500, 1]) == [2, 3, 4, 5]
    assert ext4_grow._pinned_batches([500]) == [1]


@needs_e2fs
def test_a_delivery_in_many_batches_lands_every_file_the_same_both_times(tmp_path, monkeypatch):
    """One file a batch: every session sees what the ones before it wrote, a scene.assets
    made in one batch is the next one's directory, and the same target twice is a new file
    and then a replaced one - all decided before anything is written."""
    monkeypatch.setattr(ext4_grow, "PINNED_BATCH_FILES", 1)
    base = _card(tmp_path)
    jobs = _jobs(tmp_path)
    for n in range(3):
        p = tmp_path / ("c%d" % n)
        p.write_bytes(os.urandom(20000 + n))
        jobs.append(("g/bank/scene.assets/%d.asset" % n, str(p)))
    again = tmp_path / "again"
    again.write_bytes(os.urandom(12345))
    jobs.append(("g/bank/598.asset", str(again)))
    a, b = tmp_path / "a.raw", tmp_path / "b.raw"
    shutil.copyfile(base, a)
    shutil.copyfile(base, b)
    out = _run(a, jobs)
    assert out.count("PAD_GROW_OK ") == len(jobs) and out.count("PAD_GROW_MKDIR ") == 1
    assert [ln.split()[1] for ln in out.splitlines() if ln.startswith("PAD_GROW_OK ")] == [
        str(i) for i in range(len(jobs))]
    _run(b, jobs)
    assert a.read_bytes() == b.read_bytes()
    ref = "%s?offset=%d" % (a, OFF)
    assert subprocess.run(["e2fsck", "-fn", ref], capture_output=True).returncode == 0
    for rel, src in dict(jobs).items():             # the last job for a path is what it holds
        got = subprocess.run(["debugfs", "-R", "cat \"/%s\"" % rel, ref], capture_output=True).stdout
        assert got == open(src, "rb").read(), rel


@needs_e2fs
def test_a_batch_debugfs_complains_about_counts_none_of_its_files(tmp_path, monkeypatch):
    """debugfs does not say which file a complaint is about, so a batch with one counts
    none of its files as written (a file counted that is not there would go into the build
    record as on the card); the batches before it count, and nothing after it runs."""
    monkeypatch.setattr(ext4_grow, "PINNED_BATCH_FILES", 2)
    card = _card(tmp_path)
    jobs = _jobs(tmp_path)
    bad = tmp_path / "bad"
    bad.write_bytes(b"x" * 100)
    # a file under the game program: its "directory" is a file, which only debugfs finds
    jobs = jobs[:3] + [("g/game/x.asset", str(bad)), jobs[3]]
    script = ext4_grow._pinned_script(OFF, jobs, str(card), EPOCH)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 6, r.stderr
    assert "PAD_GROW_DEBUGFS g/bank/598.asset to g/game/x.asset" in r.stderr
    assert "not a directory" in r.stderr
    assert [ln.split()[2] for ln in r.stdout.splitlines() if ln.startswith("PAD_GROW_OK ")] == [
        "g/game", "g/bank/scene.radium"]
    assert "PAD_GROW_CHECKING" not in r.stdout


class _StreamExecutor:
    """An executor whose stream() is the test's: *lines*, then *fail* (an exception) or,
    with *hang*, nothing until kill() is called."""

    def __init__(self, lines, fail=None, hang=False):
        import threading
        self.lines, self.fail, self.hang = lines, fail, hang
        self.events = []
        self.killed = threading.Event()

    def check_available(self):
        return True, "Native Linux"

    def to_exec_path(self, p):
        return p

    def kill(self):
        self.killed.set()

    def stream(self, cmd, timeout=600):
        assert cmd.startswith("base64 -d < ")
        for line in self.lines:
            self.events.append(("line", line))
            yield line
        if self.hang:
            assert self.killed.wait(10), "the delivery was never stopped"
            raise RuntimeError("Command failed (exit -15)")
        if self.fail is not None:
            raise self.fail


def _src_jobs(tmp_path, n):
    jobs = []
    for i in range(n):
        p = tmp_path / ("s%d" % i)
        p.write_bytes(b"x" * (10 + i))
        jobs.append(("g/%d.asset" % i, str(p)))
    return jobs


def test_the_log_names_each_file_as_it_lands(tmp_path, monkeypatch):
    """The 'Writing N file(s) with a fixed clock' step used to say nothing until every file
    and the final check were done: each written file is logged as its line arrives now."""
    ex = _StreamExecutor(["PAD_GROW_SPACE need=1 avail=2", "PAD_GROW_OK 0 g/0.asset",
                          "PAD_GROW_OK 1 g/1.asset", "PAD_GROW_CHECKING", "PAD_GROW_DONE fsck=1"])
    monkeypatch.setattr(ext4_grow, "create_executor", lambda: ex)
    log = lambda m, lvl="info": ex.events.append(("log", m))
    assert ext4_grow.grow_files_pinned("/c.raw", OFF, _src_jobs(tmp_path, 2), EPOCH, log=log) == 2
    seq = [(k, v) for k, v in ex.events if k == "log" or v.startswith("PAD_GROW_OK")
           or v == "PAD_GROW_CHECKING"]
    assert seq[1:] == [
        ("line", "PAD_GROW_OK 0 g/0.asset"), ("log", "  wrote g/0.asset (1 of 2)"),
        ("line", "PAD_GROW_OK 1 g/1.asset"), ("log", "  wrote g/1.asset (2 of 2)"),
        ("line", "PAD_GROW_CHECKING"),
        ("log", "Checking the card's games partition after the copies (e2fsck)..."),
        ("log", "Wrote 2 file(s) with the clock fixed at %d (filesystem checked)." % EPOCH)]


def test_a_failed_delivery_counts_what_landed_and_says_why(tmp_path, monkeypatch):
    from pinball_decryptor.core.executor import CommandError
    ex = _StreamExecutor(["PAD_GROW_ITEM 5 g/0.asset", "PAD_GROW_OK 0 g/0.asset",
                          "PAD_GROW_DEBUGFS g/1.asset to g/1.asset (exit 0): write: boom"],
                         fail=CommandError("base64", 6, "..."))
    monkeypatch.setattr(ext4_grow, "create_executor", lambda: ex)
    with pytest.raises(ext4_grow.Ext4GrowError) as ei:
        ext4_grow.grow_files_pinned("/c.raw", OFF, _src_jobs(tmp_path, 2), EPOCH)
    assert ei.value.grown == 1
    assert "(exit 6)" in str(ei.value) and "write: boom" in str(ei.value)
    assert "PAD_GROW_OK" not in str(ei.value) and "PAD_GROW_ITEM" not in str(ei.value)


def test_a_delivery_that_does_not_fit_still_says_by_how_much(tmp_path, monkeypatch):
    from pinball_decryptor.core.executor import CommandError
    ex = _StreamExecutor(["PAD_GROW_ITEM 700 g/0.asset", "PAD_GROW_ITEM 400 g/1.asset",
                          "PAD_GROW_ENOSPC need=1100 avail=1000"],
                         fail=CommandError("base64", 3, "..."))
    monkeypatch.setattr(ext4_grow, "create_executor", lambda: ex)
    with pytest.raises(ext4_grow.Ext4GrowNoSpace) as ei:
        ext4_grow.grow_files_pinned("/c.raw", OFF, _src_jobs(tmp_path, 2), EPOCH)
    assert (ei.value.need, ei.value.avail, ei.value.grown) == (1100, 1000, 0)
    assert ei.value.items == [(700, "g/0.asset"), (400, "g/1.asset")]


def test_a_delivery_past_its_timeout_is_stopped(tmp_path, monkeypatch):
    """stream() sets no deadline while lines flow, so grow_files_pinned stops the run itself
    at its timeout, as run() did."""
    ex = _StreamExecutor(["PAD_GROW_OK 0 g/0.asset"], hang=True)
    monkeypatch.setattr(ext4_grow, "create_executor", lambda: ex)
    with pytest.raises(ext4_grow.Ext4GrowError, match="stopped after 0 s with 1 of 2") as ei:
        ext4_grow.grow_files_pinned("/c.raw", OFF, _src_jobs(tmp_path, 2), EPOCH, timeout=0.2)
    assert ex.killed.is_set() and ei.value.grown == 1


def test_only_a_scene_assets_directory_may_be_made():
    assert ext4_grow._makes_dir("g/assets/lcd/auto_loaded/9d57/scene.assets/1.asset") == (
        "g/assets/lcd/auto_loaded/9d57/scene.assets", "g/assets/lcd/auto_loaded/9d57")
    assert ext4_grow._makes_dir("g/bank/598.asset") is None
    assert ext4_grow._makes_dir("scene.assets/1.asset") is None
    s = ext4_grow._bash_script(OFF, [("g/b/scene.assets/1.asset", "/s")], "/c.raw")
    assert 'mkdir "$MP"/g/b/scene.assets' in s and "PAD_GROW_NODIR" in s
