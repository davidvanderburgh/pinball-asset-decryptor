"""Delivering a file the card never had (plugins/stern/sidx_deliver), item 129.

The appender makes the manifest; delivery has to put BOTH halves on the card, and
that is the part no existing caller does.  Every write today is size-neutral for the
manifest itself - ``explorer._resize_file`` relies on ".sidx itself keeps its length,
so its own record fields are still patchable at raw disk offsets".  Appending makes it
longer, so it becomes a copy job of its own and both files' extents move.

The ``grow`` callable is injected, so these run anywhere: no loop device, no WSL, no
e2fsprogs.  What they pin is the ORDER OF EVENTS - refuse before the copy, ship both
files in one pass, re-read through a fresh reader afterwards - because the failure
this is written to avoid is a card carrying a manifest that indexes a file which never
landed.
"""

import struct

import pytest

from pinball_decryptor.plugins.stern import sidx, sidx_append, sidx_deliver

_PAYLOAD = {"FI64": 80, "FINF": 60}


def _build(paths_and_sizes, fmt="FI64", pkg="game_pro"):
    """A .sidx in the shape real cards of *fmt* use (see test_stern_sidx_append)."""
    tag = fmt.encode()
    plen = _PAYLOAD[fmt]
    strs = b"".join(p.encode() + b"\x00" for p, _ in paths_and_sizes)
    total = sum(s for _p, s in paths_and_sizes)
    hdr = bytearray(0x38)
    hdr[0:4] = b"SIDX"
    hdr[8:8 + len(pkg)] = pkg.encode()
    struct.pack_into("<I", hdr, 0x30, len(paths_and_sizes))
    body = b""
    if fmt == "FI64":
        struct.pack_into("<I", hdr, 0x34, 0xFFFFFFFF)
        body += b"SZ64" + struct.pack("<I", 8) + struct.pack("<Q", total)
    else:
        struct.pack_into("<I", hdr, 0x34, total)
    body += b"STRS" + struct.pack("<I", len(strs)) + strs
    pack, *size_offs = sidx._SIZE_FIELDS[fmt]
    for _p, size in paths_and_sizes:
        payload = bytearray(plen)
        for off in size_offs:
            struct.pack_into(pack, payload, off, size)
        body += tag + struct.pack("<I", plen) + bytes(payload)
    out = bytearray(bytes(hdr) + body + sidx_append.FEND)
    struct.pack_into("<I", out, 0x04, len(out) - 8)
    return bytes(out)


class _FakeReader:
    """Just enough of Ext4Reader for find_sidx + read_file_bytes."""

    def __init__(self, manifest, path="/spk/index/game_pro-1_00_0.sidx"):
        self._manifest = manifest
        self._path = path

    def iter_regular_files(self, min_size=1, max_depth=20):
        yield self._path, 12, {"i_block": b"\x00" * 60, "size": len(self._manifest)}

    def read_file_bytes(self, node):
        return self._manifest


def _factory(state):
    """A reader_factory that hands back whatever the 'card' currently holds."""
    def make():
        return _FakeReader(state["manifest"])
    return make


def _grow_ok(state, jobs_seen):
    """A grow_files stand-in that 'writes' the manifest into the fake card."""
    def grow(image_path, part_offset, jobs, log=None, **kw):
        jobs_seen.append(list(jobs))
        for rel, src in jobs:
            if rel.endswith(".sidx"):
                with open(src, "rb") as f:
                    state["manifest"] = f.read()
        return len(jobs)
    return grow


def test_plan_new_file_indexes_the_source(tmp_path):
    src = tmp_path / "ours.radium"
    src.write_bytes(b"our own scene" * 40)
    data = _build([("game/a.bin", 10)])
    out, size = sidx_deliver.plan_new_file(data, "game/ours.radium", str(src))
    assert size == src.stat().st_size
    assert sidx_append.verify(out, expect_paths=["game/ours.radium"]) == []
    recs, _c, fmt = sidx.parse_records(out)
    po = recs["game/ours.radium"]
    hm, md = sidx.digests(src.read_bytes())
    h_off, m_off = sidx._FORMATS[fmt]
    assert out[po + h_off:po + h_off + 20] == hm
    assert out[po + m_off:po + m_off + 16] == md


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_add_file_ships_both_halves_in_one_pass(tmp_path, fmt):
    src = tmp_path / "ours.bin"
    src.write_bytes(b"x" * 1234)
    state = {"manifest": _build([("game/a.bin", 10)], fmt=fmt)}
    jobs_seen = []

    size, mpath = sidx_deliver.add_file(
        str(tmp_path / "card.raw"), 4096, _factory(state),
        "game/ours.bin", str(src), grow=_grow_ok(state, jobs_seen))

    assert size == 1234
    assert mpath.endswith(".sidx")
    # ONE pass carrying BOTH files: a manifest indexing a file that never landed
    # is the failure this ordering exists to prevent.
    assert len(jobs_seen) == 1
    rels = [rel for rel, _src in jobs_seen[0]]
    assert "game/ours.bin" in rels
    assert any(r.endswith(".sidx") for r in rels)
    # and the card's manifest now indexes it
    recs, _c, _f = sidx.parse_records(state["manifest"])
    assert "game/ours.bin" in recs


def test_add_file_refuses_a_duplicate_without_touching_the_card(tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"x" * 10)
    state = {"manifest": _build([("game/a.bin", 10)])}
    before = state["manifest"]
    jobs_seen = []
    with pytest.raises(sidx_deliver.SidxDeliverError):
        sidx_deliver.add_file(
            str(tmp_path / "card.raw"), 0, _factory(state),
            "game/a.bin", str(src), grow=_grow_ok(state, jobs_seen))
    assert jobs_seen == [], "the card was touched despite a refusable request"
    assert state["manifest"] == before


def test_add_file_refuses_when_there_is_no_manifest(tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"x")

    class _NoSidx:
        def iter_regular_files(self, **kw):
            return iter(())

    with pytest.raises(sidx_deliver.SidxDeliverError) as e:
        sidx_deliver.add_file(str(tmp_path / "card.raw"), 0,
                              lambda: _NoSidx(), "game/x", str(src),
                              grow=lambda *a, **k: 0)
    assert "manifest" in str(e.value)


def test_add_file_reports_a_partial_delivery(tmp_path):
    src = tmp_path / "ours.bin"
    src.write_bytes(b"x" * 10)
    state = {"manifest": _build([("game/a.bin", 10)])}

    def grow_half(image_path, part_offset, jobs, log=None, **kw):
        return 1                      # the asset landed, the manifest did not

    with pytest.raises(sidx_deliver.SidxDeliverError) as e:
        sidx_deliver.add_file(str(tmp_path / "card.raw"), 0, _factory(state),
                              "game/ours.bin", str(src), grow=grow_half)
    assert "1 of 2" in str(e.value)


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_remove_is_the_exact_inverse_of_append(fmt):
    stock = _build([("game/a.bin", 10), ("game/b.bin", 20)], fmt=fmt)
    hm, md = sidx.digests(b"payload")
    grown = sidx_append.append_record(stock, "game/ours.bin", 4096, hm, md)
    back = sidx_deliver.remove_file_record(grown, "game/ours.bin")
    assert back == stock, "removing the record must restore the stock manifest"


def test_remove_refuses_from_the_middle():
    # record i belongs to path i, so removing anything but the last would
    # silently re-point every record after it.
    data = _build([("game/a.bin", 10), ("game/b.bin", 20)])
    with pytest.raises(sidx_append.SidxAppendError):
        sidx_deliver.remove_file_record(data, "game/a.bin")
