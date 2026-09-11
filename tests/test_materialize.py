"""materialize.py - the store card's delta format and the on-card rebuild (item 107).

Pure python, no WSL: the format is bytes in and bytes out, and the machine side is
exercised over a temporary store directory with --no-bind.  The one thing this file
cannot prove is python 2.7 on ARM, which is what the card runs; the subset lint at the
bottom is the desk's stand-in, and the rig runs the script under the card's own
interpreter through qemu (recorded in the queue item).
"""
import hashlib
import io
import os
import re
import sys

import pytest

CODESELECT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tools", "spike2_emu", "codeselect")

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(CODESELECT, "materialize.py")),
                                reason="materialize.py not present")


@pytest.fixture()
def mz():
    if CODESELECT not in sys.path:
        sys.path.insert(0, CODESELECT)
    import materialize
    return materialize


def _chunks(b, n=1000):
    return (b[i:i + n] for i in range(0, len(b), n))


def _variant(base, edits):
    out = bytearray(base)
    for off, payload in edits:
        out[off:off + len(payload)] = payload
    return bytes(out)


# ---- the format ---------------------------------------------------------------------------
def test_find_delta_names_the_changed_blocks_and_merges_within_slack(mz):
    base = bytes(range(256)) * 400                        # 102400 bytes
    new = _variant(base, [(5000, b"X" * 10), (13000, b"Y" * 3), (60000, b"Z" * 5000)])
    ranges = mz.find_delta(_chunks(base, 777), _chunks(new, 4096), len(base), slack=0)
    assert ranges == [(4096, 4096), (12288, 4096), (57344, 8192)]     # 4 KiB blocks, exactly the touched ones
    wide = mz.find_delta(_chunks(base), _chunks(new), len(base), slack=4096)
    assert wide == [(4096, 12288), (57344, 8192)]                      # the two near ones joined
    assert mz.find_delta(_chunks(base), _chunks(base), len(base)) == []
    assert mz.find_delta(_chunks(base), _chunks(new[:-1]), len(base)) is None      # sizes differ
    assert mz.find_delta(_chunks(base), _chunks(new), len(base) + 1) is None
    # more than the limit differs: None, and the compare stops early
    noisy = bytes((b + 1) & 0xFF for b in base)
    assert mz.find_delta(_chunks(base), _chunks(noisy), len(base)) is None
    assert mz.find_delta(_chunks(base), _chunks(noisy), len(base), limit=len(base)) == [(0, len(base))]


def test_write_read_apply_and_hash_round_trip(mz, tmp_path):
    base = bytes(range(256)) * 1000                       # 256000 bytes; the edits are well under a quarter
    new = _variant(base, [(100, b"a" * 50), (40000, b"b" * 9000), (len(base) - 7, b"tail!!!")])
    sha = hashlib.sha256(new).hexdigest()
    key = hashlib.sha256(base).hexdigest() + ".0644.0.0"
    ranges = mz.find_delta(_chunks(base), _chunks(new), len(base))
    blob = tmp_path / "x.delta"
    with open(blob, "wb") as f:
        payload = mz.write_delta(f, key, sha, len(base), ranges, _chunks(new, 3000))
    assert payload == sum(n for _o, n in ranges) and 0 < payload < len(base) // 4
    with open(blob, "rb") as f:
        h = mz.read_header(f)
        assert (h["base"], h["size"], h["sha256"], h["ranges"]) == (key, len(base), sha, ranges)
        assert h["payload"] == f.tell() and os.path.getsize(blob) == h["payload"] + payload
        # hashing base + delta without a work file gives the variant's sha
        assert mz.hash_with_delta(_chunks(base, 5000), f, h) == sha
        # applying it to a copy of the base gives the variant's bytes
        work = tmp_path / "work.bin"
        work.write_bytes(base)
        with open(work, "r+b") as wf:
            mz.apply_delta(wf, f, h)
        assert work.read_bytes() == new
        # and putting the base back over the ranges undoes it
        with open(work, "r+b") as wf, io.BytesIO(base) as bf:
            mz.restore_ranges(wf, bf, h["ranges"])
        assert work.read_bytes() == base


def test_the_header_is_ascii_lines_a_blank_line_then_bytes(mz):
    out = io.BytesIO()
    mz.write_delta(out, "k.0644.0.0", "s" * 64, 10, [(2, 3)], _chunks(b"0123456789", 4))
    raw = out.getvalue()
    assert raw == b"PADDELTA 1\nbase k.0644.0.0\nsize 10\nsha256 " + b"s" * 64 + b"\nranges 1\n2 3\n\n234"
    with pytest.raises(ValueError):
        mz.read_header(io.BytesIO(b"nope"))
    with pytest.raises(ValueError):
        mz.read_header(io.BytesIO(b"PADDELTA 1\nbase k\nsize 10\nranges 2\n0 1\n"))   # short, no blank line
    # an unknown key is ignored, so a later writer may add one
    h = mz.read_header(io.BytesIO(b"PADDELTA 1\nbase k\nsize 4\nnote hi there\nranges 0\n\n"))
    assert h["ranges"] == [] and h["payload"] == len(b"PADDELTA 1\nbase k\nsize 4\nnote hi there\nranges 0\n\n")


def test_write_delta_refuses_a_stream_shorter_than_its_ranges(mz):
    with pytest.raises(ValueError):
        mz.write_delta(io.BytesIO(), "k", "s", 100, [(90, 10)], _chunks(b"x" * 50))


def test_index_round_trips_sorted_and_refuses_a_tab_in_a_path(mz, tmp_path):
    p = tmp_path / "deltas"
    entries = [("t/image.bin", "b" * 64 + ".0644.0.0", "n" * 64 + ".0644.0.0.delta", 12345),
               ("a/other.bin", "c" * 64 + ".0644.0.0", "d" * 64 + ".0644.0.0.delta", 1)]
    mz.write_index(str(p), entries)
    raw = p.read_bytes()
    assert raw.startswith(b"# PADDELTAS 1\n") and raw.count(b"\n") == 3 and b"\t" in raw
    assert mz.read_index(str(p)) == sorted(entries)
    assert mz.read_index(str(tmp_path / "missing")) == []
    with pytest.raises(ValueError):
        mz.index_bytes([("bad\tname", "k", "n", 1)])
    p.write_bytes(b"# PADDELTAS 1\nonly three\tfields\there\n")
    with pytest.raises(ValueError):
        mz.read_index(str(p))


# ---- the machine side ---------------------------------------------------------------------
@pytest.fixture()
def store(mz, tmp_path):
    """A store with a base blob, two deltas of it and a tree whose index names the first."""
    base = bytes(range(256)) * 500                        # 128000 bytes
    v1 = _variant(base, [(1000, b"one" * 100)])
    v2 = _variant(base, [(50000, b"two" * 200), (100000, b"2" * 10)])
    blobs = tmp_path / "store" / ".blobs"
    blobs.mkdir(parents=True)
    key = hashlib.sha256(base).hexdigest() + ".0644.0.0"
    (blobs / key).write_bytes(base)
    names = {}
    for tag, v in (("v1", v1), ("v2", v2)):
        sha = hashlib.sha256(v).hexdigest()
        name = sha + ".0644.0.0.delta"
        ranges = mz.find_delta(_chunks(base), _chunks(v), len(base))
        with open(blobs / name, "wb") as f:
            mz.write_delta(f, key, sha, len(base), ranges, _chunks(v))
        names[tag] = name
    tree = tmp_path / "store" / "img1"
    (tree / ".multiboot").mkdir(parents=True)
    (tree / "beatles").mkdir()
    (tree / "beatles" / "image.bin").write_bytes(base)        # the tree's file IS the base (a hardlink on a card)
    mz.write_index(str(tree / ".multiboot" / "deltas"), [("beatles/image.bin", key, names["v1"], len(base))])
    return {"root": str(tmp_path / "store"), "tree": str(tree), "key": key, "base": base, "v1": v1, "v2": v2,
            "names": names, "work": str(tmp_path / "work")}


def test_materialize_one_copies_then_hits_then_restores_then_redoes(mz, store):
    S = store
    rel, size = "beatles/image.bin", len(S["base"])
    path, how = mz.materialize_one(S["root"], rel, S["key"], S["names"]["v1"], size, S["work"], verify=True)
    assert how == "copied" and open(path, "rb").read() == S["v1"]
    stamp = path + ".stamp"
    assert mz.read_stamp(stamp) == (S["key"], S["names"]["v1"])
    # the same again: nothing to do
    assert mz.materialize_one(S["root"], rel, S["key"], S["names"]["v1"], size, S["work"])[1] == "hit"
    # another delta of the same base: the old ranges are put back, the new written; no whole copy
    path, how = mz.materialize_one(S["root"], rel, S["key"], S["names"]["v2"], size, S["work"], verify=True)
    assert how == "restored" and open(path, "rb").read() == S["v2"]
    assert mz.read_stamp(stamp) == (S["key"], S["names"]["v2"])
    # the old delta's blob gone (an update gc'd it): back to v1 means a whole copy
    os.unlink(os.path.join(S["root"], ".blobs", S["names"]["v2"]))
    path, how = mz.materialize_one(S["root"], rel, S["key"], S["names"]["v1"], size, S["work"], verify=True)
    assert how == "copied" and open(path, "rb").read() == S["v1"]
    # a stamp that names the right delta but a work file of the wrong size: redone
    with open(path, "ab") as f:
        f.write(b"junk")
    path, how = mz.materialize_one(S["root"], rel, S["key"], S["names"]["v1"], size, S["work"], verify=True)
    assert how == "copied" and open(path, "rb").read() == S["v1"]
    # no stamp at all (power went mid-write last time): redone from the base
    os.unlink(stamp)
    path, how = mz.materialize_one(S["root"], rel, S["key"], S["names"]["v1"], size, S["work"], verify=True)
    assert how == "copied" and mz.read_stamp(stamp) == (S["key"], S["names"]["v1"])


def test_materialize_one_refuses_a_wrong_base_or_a_lying_delta(mz, store):
    S = store
    size = len(S["base"])
    with pytest.raises((IOError, OSError)):
        mz.materialize_one(S["root"], "x", "0" * 64 + ".0644.0.0", S["names"]["v1"], size, S["work"])
    with pytest.raises((IOError, OSError, ValueError)):     # the index's size disagrees with the base's
        mz.materialize_one(S["root"], "x", S["key"], S["names"]["v1"], size - 1, S["work"])
    # a delta whose header names another base than the index does: refused before any write
    other = os.path.join(S["root"], ".blobs", "e" * 64 + ".0644.0.0.delta")
    with open(other, "wb") as f:
        mz.write_delta(f, "f" * 64 + ".0644.0.0", "e" * 64, size, [], iter([]))
    with pytest.raises(ValueError):
        mz.materialize_one(S["root"], "x", S["key"], "e" * 64 + ".0644.0.0.delta", size, S["work"])
    # a delta whose payload is short: the work file is left WITHOUT a stamp, so the next boot redoes it
    short = os.path.join(S["root"], ".blobs", S["names"]["v1"])
    raw = open(short, "rb").read()
    with open(short, "wb") as f:
        f.write(raw[:-10])
    with pytest.raises((IOError, OSError)):
        mz.materialize_one(S["root"], "beatles/image.bin", S["key"], S["names"]["v1"], size, S["work"])
    assert not os.path.exists(os.path.join(S["work"], "beatles", "image.bin.stamp"))


def test_main_reads_the_trees_index_and_writes_the_work_files(mz, store, capsys):
    S = store
    rc = mz.main(["--store", S["root"], "--tree", "img1", "--games", S["tree"], "--work", S["work"],
                  "--no-bind", "--verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "names 1 delta file(s)" in out and "copied base" in out and "1 of 1 delta file(s) in place" in out
    assert open(os.path.join(S["work"], "beatles", "image.bin"), "rb").read() == S["v1"]
    # a tree with no index says nothing and does nothing
    os.unlink(os.path.join(S["tree"], ".multiboot", "deltas"))
    assert mz.main(["--store", S["root"], "--tree", "img1", "--games", S["tree"], "--work", S["work"], "--no-bind"]) == 0
    assert capsys.readouterr().out == ""
    # a broken index is a message, not a failure: the game boots on the base's files
    with open(os.path.join(S["tree"], ".multiboot", "deltas"), "wb") as f:
        f.write(b"garbage\n")
    assert mz.main(["--store", S["root"], "--tree", "img1", "--games", S["tree"], "--work", S["work"], "--no-bind"]) == 0
    assert "cannot read" in capsys.readouterr().out
    # usage errors are the only non-zero exit
    assert mz.main(["--store", S["root"]]) == 2
    assert mz.main(["--bogus"]) == 2


def test_a_missing_delta_blob_skips_that_file_and_still_exits_zero(mz, store, capsys):
    S = store
    os.unlink(os.path.join(S["root"], ".blobs", S["names"]["v1"]))
    assert mz.main(["--store", S["root"], "--tree", "img1", "--games", S["tree"], "--work", S["work"], "--no-bind"]) == 0
    out = capsys.readouterr().out
    assert "NOT materialized" in out and "0 of 1 delta file(s) in place" in out


def test_the_log_file_gets_every_line_with_a_timestamp(mz, store, tmp_path, capsys):
    S = store
    logf = tmp_path / "materialize.log"
    mz.main(["--store", S["root"], "--tree", "img1", "--games", S["tree"], "--work", S["work"], "--no-bind",
             "--log", str(logf)])
    lines = logf.read_text().splitlines()
    assert len(lines) == 3 and all(re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d materialize: ", ln) for ln in lines)
    mz._LOG[0] = None


# ---- the python 2.7 subset ----------------------------------------------------------------
def test_materialize_stays_in_the_card_pythons_subset():
    """The card runs python 2.7 with os, sys, hashlib, struct, errno, time, stat, io, re and
    collections and WITHOUT json, subprocess, fcntl, shutil, zlib or tempfile (measured on
    the rootfs under qemu, 2026-09-11).  A crude gate, but a real one: each pattern here is
    something the interpreter on the machine cannot parse or import."""
    src = open(os.path.join(CODESELECT, "materialize.py"), encoding="utf-8").read()
    assert "from __future__ import print_function" in src
    src = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))   # code, not the notes
    for bad in (r'\bf"', r"\bf'", r"\byield from\b", r"\bnonlocal\b", r":=", r"\bmatch\b\s+\w+\s*:",
                r"^\s*def \w+\([^)]*\*\s*,", r"\bos\.replace\b", r"\bos\.makedirs\([^)]*exist_ok"):
        assert not re.search(bad, src, re.M), bad
    for mod in ("json", "subprocess", "fcntl", "shutil", "zlib", "tempfile", "pathlib", "typing"):
        assert not re.search(r"^\s*(import|from)\s+%s\b" % mod, src, re.M), mod
