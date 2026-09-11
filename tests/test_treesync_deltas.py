"""treesync's delta half (item 107) - pure python, on MemOps, on Windows.

A store card keeps a song-set variant's image.bin as a DELTA of the base tree's blob:
the record carries which files are deltas, the executor writes the delta blob and links
the base, dedup_costs charges the delta's bytes, gc keeps deltas by name (nothing links
them), the tree carries a tab-line index for the card, and the plan-time discovery
compares two sources once and caches the answer.
"""
import hashlib
import io
import json
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")
sys.path.insert(0, RIG)
import treesync as ts  # noqa: E402


def _tree(files):
    return ts.mem_source_from(files)


def _apply(ops, prefix, old, new, src, **kw):
    return ts.apply_changes(ops, prefix, ts.diff_tree(old, new), new, src, **kw)


def _big(seed, n=(1 << 20) + 5000):
    """A file over DELTA_MIN_SIZE whose bytes depend on the seed."""
    return bytes((i * 7 + seed) & 0xFF for i in range(n))


def _edit(b, off, payload):
    out = bytearray(b)
    out[off:off + len(payload)] = payload
    return bytes(out)


def test_record_carries_deltas_and_writes_format_2_only_when_one_exists():
    a, _ = _tree({"t/image.bin": b"A" * 10})
    key = ts.blob_key(a.files["t/image.bin"])
    im0 = ts.ImageTrees(0, "/dev/mmcblk0p3", "", a)
    b, _ = _tree({"t/image.bin": b"B" * 10})
    dname = ts.delta_name(b.files["t/image.bin"])
    im1 = ts.ImageTrees(1, "/dev/mmcblk0p3:img1", "img1", b,
                        deltas={"t/image.bin": {"base": key, "delta": dname, "size": 10, "bytes": 4, "ranges": 1}})
    assert im1.base_sha("t/image.bin") == a.files["t/image.bin"].sha256
    assert im0.base_sha("t/image.bin") == a.files["t/image.bin"].sha256 and im0.base_sha("nope") is None
    assert im1.delta_names() == {dname} and im0.delta_names() == set()
    plain = ts.CardTrees([im0], layout="store")
    assert json.loads(plain.to_json())["format"] == 1
    rec = ts.CardTrees([im0, im1], layout="store")
    raw = rec.to_json()
    assert json.loads(raw)["format"] == 2 and rec.has_deltas() and rec.delta_names() == {dname}
    back = ts.CardTrees.from_json(raw)
    assert back.image(1).deltas == im1.deltas and back.image(0).deltas is None
    assert back.to_json() == raw
    assert ts.parse_delta_name(dname) == ts.parse_blob_key(ts.blob_key(b.files["t/image.bin"]))
    assert ts.parse_delta_name(key) is None
    with pytest.raises(ts.TreesError):
        ts.CardTrees.from_json(raw.replace(b'"format":2', b'"format":3'))


def test_dedup_costs_charges_a_delta_its_bytes_once_and_the_base_where_it_lives():
    a, _ = _tree({"x/image.bin": b"A" * 100, "x/one": b"1"})
    b, _ = _tree({"x/image.bin": b"B" * 100, "x/two": b"22"})
    c, _ = _tree({"x/image.bin": b"B" * 100, "x/three": b"333"})          # the same variant again
    deltas = [{}, {"x/image.bin": {"bytes": 12}}, {"x/image.bin": {"bytes": 12}}]
    unique, shared = ts.dedup_costs([a, b, c], deltas)
    assert unique == [101, 14, 3]                       # 100 + 1; 12 (the delta) + 2; the delta shared, + 3
    assert shared == (101 + 102 + 103) - sum(unique)
    entry = {"base": "k", "delta": "n", "size": 100, "bytes": 12, "ranges": 1}
    ims = [ts.ImageTrees(0, "d", "", a), ts.ImageTrees(1, "d", "img1", b, deltas={"x/image.bin": entry})]
    assert ts.dedup_costs(ims) == ([101, 14], 203 - 115)


def test_apply_with_a_delta_writes_the_blob_once_links_the_base_and_reruns_clean():
    mz = ts._materialize()
    base = _big(1)
    v1 = _edit(base, 4096 * 10, b"one" * 3000)
    A, srcA = _tree({"t/image.bin": base, "t/small": b"s"})
    B, srcB = _tree({"t/image.bin": v1, "t/small": b"s"})
    key = ts.blob_key(A.files["t/image.bin"])
    ops = ts.MemOps()
    ops.mkdir(".blobs", 0o700, 0, 0)
    ops.mkdir("img1", 0o755, 0, 0)
    _apply(ops, "img1", None, A, srcA, store=True)
    ranges = mz.find_delta(ts.MemSource({"": base}).chunks(""), ts.MemSource({"": v1}).chunks(""), len(base))
    plan = {"t/image.bin": {"base": key, "ranges": ranges}}
    ops.mkdir("img2", 0o755, 0, 0)
    stats = _apply(ops, "img2", None, B, srcB, store=True, deltas=plan)
    dname = ts.delta_name(B.files["t/image.bin"])
    assert stats["deltas"] == 1 and stats["delta_skipped"] == 0 and stats["written"] == 0 and stats["linked"] == 1
    assert stats["delta_bytes"] == sum(n for _o, n in ranges) == stats["delta_files"]["t/image.bin"]["bytes"]
    assert stats["delta_files"] == {"t/image.bin": {"base": key, "delta": dname, "size": len(base),
                                                    "bytes": stats["delta_bytes"], "ranges": len(ranges)}}
    assert ops.ino("img2/t/image.bin") == ops.ino(".blobs/" + key)              # the tree's file IS the base
    assert ops.lstat(".blobs/" + dname)["nlink"] == 1                           # a delta is never linked
    h = mz.read_header(io.BytesIO(ops.read(".blobs/" + dname)))
    assert h["base"] == key and h["ranges"] == ranges and h["sha256"] == B.files["t/image.bin"].sha256
    wf = io.BytesIO(bytearray(base))                                            # the blob rebuilds the variant
    mz.apply_delta(wf, io.BytesIO(ops.read(".blobs/" + dname)), h)
    assert wf.getvalue() == v1
    # a re-run after a crash (the diff is against nothing again) writes nothing and still
    # reports the record entry; a diff that changed nothing visits no file and reports none
    # (carrying the old record's entry forward is the caller's job, as with the bypass)
    again = _apply(ops, "img2", None, B, srcB, store=True, deltas=plan)
    assert again["deltas"] == 0 and again["written"] == 0 and again["delta_files"] == stats["delta_files"]
    assert ops.ino("img2/t/image.bin") == ops.ino(".blobs/" + key)
    assert _apply(ops, "img2", B, B, srcB, store=True, deltas=plan)["delta_files"] == {}
    # a third tree with the SAME variant shares the delta blob: nothing written
    ops.mkdir("img3", 0o755, 0, 0)
    third = _apply(ops, "img3", None, B, srcB, store=True, deltas=plan)
    assert third["deltas"] == 0 and third["delta_files"] == stats["delta_files"]
    assert len([n for n in ops.listdir(".blobs") if n.endswith(".delta")]) == 1
    # no such base in the store: stored whole, and said so
    ops.mkdir("img4", 0o755, 0, 0)
    whole = _apply(ops, "img4", None, B, srcB, store=True,
                   deltas={"t/image.bin": {"base": "0" * 64 + ".0644.0.0", "ranges": ranges}})
    assert whole["delta_skipped"] == 1 and whole["deltas"] == 0 and whole["written"] == 1
    assert ops.ino("img4/t/image.bin") == ops.ino(".blobs/" + ts.blob_key(B.files["t/image.bin"]))
    assert not any(ts.is_tmp(n) for n in ops.listdir(".blobs"))
    # without a deltas argument the stats keep their four old keys exactly
    assert set(_apply(ops, "img2", B, B, srcB, store=True)) == {"written", "bytes", "removed", "linked"}


def test_gc_keeps_deltas_by_name_never_by_link_count():
    ops = ts.MemOps()
    ops.mkdir(".blobs", 0o700, 0, 0)
    ops.write_stream(".blobs/" + "a" * 64 + ".0644.0.0.delta", [b"PADDELTA 1\n"], 0o600, 0, 0, 0)
    ops.write_stream(".blobs/" + "b" * 64 + ".0644.0.0.delta", [b"PADDELTA 1\n"], 0o600, 0, 0, 0)
    ops.write_stream(".blobs/" + "c" * 64 + ".0644.0.0", [b"orphan"], 0o644, 0, 0, 0)
    assert ts.gc_blobs(ops) == (1, 6)                                         # keep None: deltas untouched
    assert ts.gc_blobs(ops, keep_deltas={"b" * 64 + ".0644.0.0.delta"}) == (1, 11)
    assert ops.listdir(".blobs") == ["b" * 64 + ".0644.0.0.delta"]


def test_write_delta_index_writes_the_tab_lines_and_removes_a_stale_one():
    ops = ts.MemOps()
    ops.mkdir("img1", 0o755, 0, 0)
    assert ts.write_delta_index(ops, "img1", {}) is False and not ops.exists("img1/.multiboot")
    files = {"t/image.bin": {"base": "k" * 64 + ".0644.0.0", "delta": "d" * 64 + ".0644.0.0.delta",
                             "size": 7, "bytes": 1, "ranges": 1}}
    assert ts.write_delta_index(ops, "img1", files) is True
    raw = ops.read("img1/.multiboot/deltas")
    assert raw == (b"# PADDELTAS 1\nt/image.bin\t" + b"k" * 64 + b".0644.0.0\t" + b"d" * 64
                   + b".0644.0.0.delta\t7\n")
    assert not any(ts.is_tmp(n) for n in ops.listdir("img1/.multiboot"))
    assert ts._materialize().read_index.__name__ == "read_index"
    assert ts.write_delta_index(ops, "img1", None) is False
    assert not ops.exists("img1/.multiboot/deltas") and not ops.exists("img1/.multiboot")


def test_find_deltas_picks_a_base_per_path_tries_every_full_blob_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv(ts.CACHE_ENV, str(tmp_path / "cache"))
    base = _big(1)
    v1 = _edit(base, 4096 * 3, b"x" * 100)                     # near the base
    far = bytes((b + 1) & 0xFF for b in base)                  # nothing like the base: a full blob
    v_far = _edit(far, 4096 * 50, b"y" * 10)                   # near FAR, nothing like the base
    trees = [_tree({"t/image.bin": base, "t/s": b"a" * 100, "t/other.bin": _big(9)}),
             _tree({"t/image.bin": v1, "t/s": b"b" * 100, "t/other.bin": _big(9)}),
             _tree({"t/image.bin": far}),
             _tree({"t/image.bin": v_far}),
             _tree({"t/image.bin": v1}),                       # the first variant again: shares its delta
             _tree({"t/image.bin": base[:-1]})]                # another size: never a delta
    mans = [m for m, _s in trees]
    srcs = [s for _m, s in trees]
    reads = []

    def chunks_of(i, rel):
        reads.append((i, rel))
        return srcs[i].chunks(rel)
    notes = []
    out = ts.find_deltas(mans, chunks_of, note=notes.append)
    key0 = ts.blob_key(mans[0].files["t/image.bin"])
    key2 = ts.blob_key(mans[2].files["t/image.bin"])
    assert out[0] == {} and out[5] == {}
    assert set(out[1]) == {"t/image.bin"} and out[1]["t/image.bin"]["base"] == key0
    assert out[1]["t/image.bin"]["ranges"] == [(4096 * 3, 4096)] and out[1]["t/image.bin"]["bytes"] == 4096
    assert out[2] == {}                                        # too different: a full blob of its own
    assert out[3]["t/image.bin"]["base"] == key2               # ...and the next variant rides on IT
    assert out[4] == out[1]                                    # the same variant: the same delta, no compare
    assert len(notes) == 4                                     # 1v0, 2v0, 3v0 (fails), 3v2
    assert not any(rel in ("t/s", "t/other.bin") for _i, rel in reads)   # small, and identical: never read
    # a second plan reads nothing at all: every compare, the failed ones too, is cached
    reads.clear()
    notes.clear()
    assert ts.find_deltas(mans, chunks_of) == out and reads == [] and notes == []
    assert len([n for n in os.listdir(tmp_path / "cache") if n.startswith("delta-")]) == 4
    # a cache entry for another size is not believed
    sha0, sha1 = mans[0].files["t/image.bin"].sha256, mans[1].files["t/image.bin"].sha256
    assert ts.load_cached_delta(sha0, sha1, 1) is ts.MISS
    assert ts.load_cached_delta(sha0, sha1, len(base)) == [(4096 * 3, 4096)]
    assert ts.load_cached_delta(sha0, hashlib.sha256(far).hexdigest(), len(base)) is None
