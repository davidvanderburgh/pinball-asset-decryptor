"""PAD-1533: a multi-boot card written onto a Windows drive from WSL is really sparse, and the
log says what it really takes.

A 16G King Kong two-image build onto C: came out 15.49 GB allocated (fsutil: "NOT set as
sparse") while the log said "(sparse)" twice: the Spike 2 builder made its output with a plain
truncate, which on drvfs is a full-size NTFS file.  It now asks Windows for the sparse flag
first (the PAD-1507 Spike 3 fix, now one shared definition), and the JJP builder's work copy
beside its output does the same.  The emulator-side proof is the rebuilt card itself (6.35 GB
allocated, flag set, verify PASS); these pin the decisions.
"""
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
JJP = os.path.join(ROOT, "tools", "jjp_emu")
S3 = os.path.join(ROOT, "tools", "spike3_emu")


@pytest.fixture()
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


def _as_windows_drive(mk, monkeypatch, tmp_path, rc=0):
    """Every path reads as itself (a /mnt/x path stays one on a Windows test host), every open
    lands on one tmp file, and fsutil is recorded and answers `rc`."""
    calls = []
    monkeypatch.setattr(mk.subprocess, "run", lambda a, **k: calls.append(a) or SimpleNamespace(returncode=rc))
    monkeypatch.setattr(mk.os.path, "abspath", lambda p: p)
    real = tmp_path / "card.raw"
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, m="r", *a, **k: real_open(real, m, *a, **k))
    return calls, real


def test_windows_drive_paths(mk, monkeypatch):
    monkeypatch.setattr(mk.os.path, "abspath", lambda p: p)
    assert mk.windows_drive_path("/mnt/c/Users/david/OneDrive/Desktop/kk/multi/kk.multi.raw") == \
        r"C:\Users\david\OneDrive\Desktop\kk\multi\kk.multi.raw"
    assert mk.windows_drive_path("/mnt/d") == "D:\\"
    for linux in ("/mnt/wsl/cards/cardcache/x.raw", "/var/tmp/x.raw", "/home/pad/x.raw", "/mnt/"):
        assert mk.windows_drive_path(linux) is None, linux


def test_off_a_windows_drive_the_output_is_a_plain_truncate(mk, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(mk.subprocess, "run", lambda a, **k: calls.append(a) or SimpleNamespace(returncode=0))
    out = tmp_path / "x.raw"
    out.write_bytes(b"old content")
    assert mk.fresh_sparse_file(str(out), 1 << 20) is True
    assert out.stat().st_size == 1 << 20 and out.read_bytes()[:3] == b"\0\0\0"
    assert calls == [], "no Windows tool for a file Linux holds"


def test_on_a_windows_drive_windows_marks_it_sparse_before_the_first_write(mk, monkeypatch, tmp_path):
    calls, real = _as_windows_drive(mk, monkeypatch, tmp_path)
    assert mk.fresh_sparse_file("/mnt/c/Users/david/kk/kk.multi.raw", 4096) is True
    win = r"C:\Users\david\kk\kk.multi.raw"
    assert calls[0][-3:] == ["sparse", "setflag", win]
    assert calls[1][-5:] == ["sparse", "setrange", win, "0", "4096"]
    assert real.stat().st_size == 4096


def test_a_refused_flag_still_makes_the_file_and_says_it_is_not_sparse(mk, monkeypatch, tmp_path):
    calls, real = _as_windows_drive(mk, monkeypatch, tmp_path, rc=1)
    assert mk.fresh_sparse_file("/mnt/c/x/c.raw", 4096) is False
    assert real.stat().st_size == 4096
    assert len(calls) == 1, "setflag refused: nothing more is asked"


def test_a_missing_windows_tool_is_a_plain_file_not_a_crash(mk, monkeypatch, tmp_path):
    calls, real = _as_windows_drive(mk, monkeypatch, tmp_path)

    def gone(a, **k):
        raise FileNotFoundError(a[0])
    monkeypatch.setattr(mk.subprocess, "run", gone)
    assert mk.fresh_sparse_file("/mnt/c/x/c.raw", 8192) is False
    assert real.stat().st_size == 8192


def test_growing_a_card_on_a_windows_drive_sets_the_flag_first(mk, monkeypatch, tmp_path):
    calls, _ = _as_windows_drive(mk, monkeypatch, tmp_path)
    assert mk.set_windows_sparse("/mnt/d/Pinball/kk.multi.raw") is True
    assert calls[0][-3:] == ["sparse", "setflag", r"D:\Pinball\kk.multi.raw"]
    assert mk.set_windows_sparse("/var/tmp/x.raw") is False


def _plan(src, total):
    return SimpleNamespace(total_bytes=total, logs=[], prims=[], primary=src, multi_part=None,
                           layout="parts", store_src_count=0)


@pytest.mark.parametrize("sparse, word", [(True, "(sparse)"), (False, "(NOT sparse: Windows would not mark it sparse")])
def test_the_build_log_says_sparse_only_when_it_is(mk, monkeypatch, tmp_path, sparse, word):
    src = tmp_path / "src.raw"
    src.write_bytes(os.urandom(mk.PRE_P1 * mk.SECTOR))
    out = tmp_path / "out.raw"
    said = []
    monkeypatch.setattr(mk, "say", said.append)
    monkeypatch.setattr(mk, "write_tables", lambda plan, o: None)

    def fresh(p, size):
        with open(p, "wb") as f:
            f.truncate(size)
        return sparse
    monkeypatch.setattr(mk, "fresh_sparse_file", fresh)
    mk.build_image(_plan(str(src), 1 << 22), str(out))
    head = [s for s in said if "bytes apparent" in s][0]
    assert word in head
    assert out.read_bytes()[:len(src.read_bytes())] == src.read_bytes()


def test_the_allocation_is_reported_as_it_is(mk, monkeypatch, tmp_path):
    f = tmp_path / "card.raw"
    f.write_bytes(b"\0" * 10000)
    monkeypatch.setattr(mk, "allocated_bytes", lambda p: 3000)
    assert mk.allocation_note(str(f)) == ", 0.00 GB allocated (sparse)"
    monkeypatch.setattr(mk, "allocated_bytes", lambda p: 10240)
    assert mk.allocation_note(str(f)).endswith("(not sparse)")
    monkeypatch.setattr(mk, "allocated_bytes", lambda p: None)
    assert mk.allocation_note(str(f)) == ""
    # David's build: 15.49 GB allocated of 15.49 GB apparent was printed "(sparse)"
    assert mk.sparse_word(15494807552, 15494807552) == "not sparse"
    assert mk.sparse_word(6350000000, 15494807552) == "sparse"


def test_copy_progress_says_where_the_time_went(mk, monkeypatch, tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"\0" * mk.CHUNK + b"Q" * mk.CHUNK + b"\0" * mk.CHUNK)
    out = tmp_path / "out.bin"
    with open(out, "wb") as f:
        f.truncate(3 * mk.CHUNK)
    clock = iter(x * 0.75 for x in range(1000))
    monkeypatch.setattr(mk.time, "monotonic", lambda: next(clock))
    lines = []
    mk.copy_range(str(src), 0, str(out), 0, 3 * mk.CHUNK, "p3 kk", progress=lines.append)
    ticks = [ln for ln in lines if "reading" in ln]
    assert ticks and all("writing" in ln and "last " in ln for ln in ticks)
    assert out.read_bytes() == src.read_bytes()


def test_jjp_work_copy_on_a_windows_drive_keeps_its_holes(mk, monkeypatch, tmp_path):
    if JJP not in sys.path:
        sys.path.insert(0, JJP)
    import mkjjpmulti as mj
    src = tmp_path / "sda3.cache.raw"
    src.write_bytes(b"\0" * mk.CHUNK + b"root" * 1000 + b"\0" * mk.CHUNK)
    dst = tmp_path / "sda3.raw"
    asked = []

    def win_sparse(p, size):
        asked.append((p, size))
        with open(p, "wb") as f:
            f.truncate(size)
        return True
    monkeypatch.setattr(mj.mkc, "windows_sparse_file", win_sparse)
    monkeypatch.setattr(mj, "_run", lambda *a, **k: pytest.fail("cp would fill the holes on drvfs"))
    mj.sparse_copy(str(src), str(dst))
    assert asked == [(str(dst), src.stat().st_size)]
    assert dst.read_bytes() == src.read_bytes()


def test_spike3_uses_the_one_definition(mk):
    if S3 not in sys.path:
        sys.path.insert(0, S3)
    import mks3multi
    assert mks3multi._windows_sparse_file is mk.windows_sparse_file


def test_a_starved_source_read_is_named_once(mk, monkeypatch):
    monkeypatch.setattr(mk.os.path, "abspath", lambda p: p)
    # David's crawl: ~50 MB in a 16 s stretch, all of it reading
    note = mk.slow_read_note("/mnt/d/Pinball/images/Stern/spike2/kk.raw", 50 << 20, 15.5, 16.0)
    assert "slowed to 3 MB/s" in note and "drive D:" in note
    assert mk.slow_read_note("/mnt/d/x.raw", 200 << 20, 1.9, 2.0) == "", "100 MB/s is not slow"
    assert mk.slow_read_note("/mnt/d/x.raw", 8 << 20, 0.5, 2.0) == "", "the time went elsewhere"
    assert "its drive is busy" in mk.slow_read_note("/var/tmp/x.raw", 8 << 20, 2.0, 2.0)
