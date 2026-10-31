"""PAD-880: image.bin without the bodies of the game's sounds nothing plays any more.

The layout (image_compact.plan_layout) and the file it writes, on synthetic records; the
fragment slots that name the moved descriptors; which records a build may take out
(engine._dead_keys); the bank plan counting image.bin without them, and the refusal when it
did not come out that small.  Fast, no card and no firmware: the real Iron Maiden LE 1.18
builds and their rig runs are the ticket's proof (docs/plans/extra_sound_banks.md, "image.bin
without the bodies nothing plays").
"""
import os
import random
import struct

import pytest

from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import image_compact as IC
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from tests.test_pad606_game_sounds_in_banks import _Reader, _image, _rec

MB = 1_000_000


def _card(n=12, size=200_000, head=4096, desc=3000):
    """Records 0..n-1, contiguous bodies after a head, the descriptor block after the last
    body, then a 40-byte tail; two windows a record at a quarter and three quarters."""
    records, at = {}, head
    for i in range(n):
        records[i] = (at, size + 2 * i)
        at += size + 2 * i
    desc_at = at
    md_off = at + desc
    windows = {i: [(off // 4 - 1, 37), (3 * off // 4, 41)] for i, (o, off) in records.items()}
    return records, windows, desc_at, md_off, md_off + 40


def test_the_layout_keeps_every_live_byte_and_each_dead_record_s_windows():
    records, windows, desc_at, md_off, size = _card()
    dead = {2, 3, 7}
    lay = IC.plan_layout(size, md_off, 40, records, dead, {r: windows[r] for r in dead},
                         pinned=[desc_at, desc_at + 100])
    assert lay.gone == frozenset(dead)
    assert lay.saved > 400_000      # three bodies, less the region their windows went into
    for i, (off, n) in records.items():
        if i in dead:
            p = lay.offsets[i]
            assert p >= 0 and p + n <= lay.size and (p - off) % IC.ALIGN == 0
            for rel, k in windows[i]:
                assert (p + rel, off + rel, k) in lay.region
        else:
            new = IC.translate(lay, off)
            assert new == lay.offsets[i] and (new - off) % IC.ALIGN == 0
            assert IC.translate(lay, off + n - 1) == new + n - 1
    # the descriptor block moves by a multiple of DESC_ALIGN (its whitening stays right)
    assert (IC.translate(lay, desc_at) - desc_at) % IC.DESC_ALIGN == 0
    # windows never overlap one another
    spans = sorted((d, d + n) for d, _a, n in lay.region)
    assert all(b <= c for (_a, b), (c, _d) in zip(spans, spans[1:]))
    assert lay.md_off + 40 == lay.size


def test_the_written_file_has_the_bytes_where_the_layout_says(tmp_path):
    records, windows, desc_at, md_off, size = _card(n=6, size=50_000)
    rnd = random.Random(880)
    data = bytes(rnd.getrandbits(8) for _ in range(size))
    src, dst = tmp_path / "in.bin", tmp_path / "out.bin"
    src.write_bytes(data)
    dead = {1, 4}
    lay = IC.plan_layout(size, md_off, 40, records, dead, {r: windows[r] for r in dead},
                         pinned=[desc_at])
    IC.write_layout(str(src), str(dst), lay, {lay.md_off: b"TAIL"})
    out = dst.read_bytes()
    assert len(out) == lay.size and out[lay.md_off:lay.md_off + 4] == b"TAIL"
    for i, (off, n) in records.items():
        if i in dead:
            p = lay.offsets[i]
            for rel, k in windows[i]:
                assert out[p + rel:p + rel + k] == data[off + rel:off + rel + k]
        else:
            new = lay.offsets[i]
            assert out[new:new + n] == data[off:off + n]
    new = IC.translate(lay, desc_at)
    assert out[new:new + 3000] == data[desc_at:desc_at + 3000]
    assert out[:4096] == data[:4096]                 # the head (and its tables) stays put


def test_a_dead_record_without_windows_or_too_short_stays_whole():
    records, windows, _d, md_off, size = _card(n=4)
    records[1] = (records[1][0], 600)
    with pytest.raises(IC.CompactError):
        IC.plan_layout(size, md_off, 40, records, {1, 2}, {1: windows[1], 2: []})


def test_windows_of_reads_runs_relative_to_the_body():
    reads = [10, 11, 12, 20, 21, 500]
    assert IC.windows_of(reads, 5, 100) == [(5, 3), (15, 2)]


def test_fragment_slots_are_rewritten_for_the_moved_descriptors():
    vf2 = bytes(random.Random(1).getrandbits(8) for _ in range(SB.VF2_WINDOW + 0x100))
    head = bytearray(0x100)
    struct.pack_into("<I", head, SB.HDR_FRAG_TABLE, 0xf8)
    records, windows, desc_at, md_off, size = _card(n=6, size=50_000)
    lay = IC.plan_layout(size, md_off, 40, records, {2}, {2: windows[2]},
                         pinned=[desc_at, desc_at + 64])
    slots = {0: desc_at, 1: desc_at, 7: desc_at + 64}
    w = IC.slot_writes(bytes(head), slots, vf2, lay)
    for slot, off in slots.items():
        word = struct.unpack("<I", w[0xf8 + slot * 8])[0]
        got = word ^ struct.unpack_from("<I", vf2, SB.slot_vf2_offset(slot))[0]
        assert got == IC.translate(lay, off)
    # a slot naming a descriptor the layout drops is refused, not shipped dangling
    with pytest.raises(IC.CompactError):
        IC.slot_writes(bytes(head), {3: records[2][0] + 1000}, vf2, lay)


def test_rows_differ_allows_only_the_body_offset():
    records, windows, desc_at, md_off, size = _card(n=3, size=50_000)
    lay = IC.plan_layout(size, md_off, 40, records, {1}, {1: windows[1]}, pinned=[desc_at])
    obj = b"\0\0\0\0" + b"\x11" * 12
    before = [{"idx": i, "findkey": b"k%d" % i, "_rawobj": obj, "body_off": records[i][0]}
              for i in range(3)]
    after = [dict(r, body_off=lay.offsets[r["idx"]],
                  _rawobj=struct.pack("<I", lay.offsets[r["idx"]]) + obj[4:]) for r in before]
    assert IC.rows_differ(before, after, lay) == []
    after[2]["findkey"] = b"other"
    assert IC.rows_differ(before, after, lay)[0][:2] == (2, "findkey")


# --------------------------------------------------------------------------
# which records come out
# --------------------------------------------------------------------------
class _Plan(object):
    banked = {600: 0x10000, 601: 0x10001}
    sm_frags = {}
    sm_seqs = {}


def test_dead_keys_are_the_replaced_records_only_unreachable_sids_name(monkeypatch):
    k = {i: struct.pack("<II", 0x100 + i, i) for i in range(1, 6)}
    sites = [E._DescSite(600, 0x10, b"\0" * 8, k[1], 0x14, b"\0" * 4, 4000),   # banked sid
             E._DescSite(601, 0x20, b"\0" * 8, k[2], 0x24, b"\0" * 4, 4000),   # banked sid
             E._DescSite(700, 0x30, b"\0" * 8, k[2], 0x34, b"\0" * 4, 4000),   # another plays 2
             E._DescSite(701, 0x40, b"\0" * 8, k[4], 0x44, b"\0" * 4, 4000)]   # re-pointed 4
    monkeypatch.setattr(E, "_descriptor_sites", lambda gr, im, log=None: sites)
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites: 0xFFFFFFFF)
    monkeypatch.setattr(E, "_play_key", lambda payload, sid, mask: bytes(payload))
    params = [{"idx": 1, "findkey": k[1]}, {"idx": 2, "findkey": k[2]},
              {"idx": 3, "grown": True, "stock_findkey": k[3], "findkey": b"new3"},
              {"idx": 4, "findkey": k[4]}, {"idx": 5, "findkey": k[5]}]
    got = E._dead_keys("g", "i", params, _Plan(), {1, 2, 3, 4, 5}, set(), (set(), set()),
                       lambda *a: None)
    # 1: only a banked sid names it; 3: grown and re-pointed; 5: named by nothing
    # 2: another sid still plays it; 4: a playable sid names it
    assert got == {k[1], k[3], k[5]}
    # a record a mode swaps by, or one left un-pointed for a mode, stays
    assert E._dead_keys("g", "i", params, _Plan(), {1, 3, 5}, {5}, (set(), {k[3]}),
                        lambda *a: None) == {k[1]}
    # a banked sid a music mode's runtime still plays by keeps its record
    assert E._dead_keys("g", "i", params, _Plan(), {1}, set(), ({600}, set()),
                        lambda *a: None) == set()


def test_dead_credit_counts_the_bodies_less_what_stays(monkeypatch):
    byidx = {1: {"idx": 1, "chan": 2, "length": 10 * MB // 4, "body_off": 0},
             2: {"idx": 2, "chan": 2, "length": 20 * MB // 4, "body_off": 10 * MB},
             3: {"idx": 3, "chan": 2, "length": 5 * MB // 4, "body_off": 30 * MB,
                 "shadows": 970}}
    # without a consumed map the longest body is held back for the region
    assert E._dead_credit(byidx, [1, 2, 3]) == 30 * MB - 4 * IC.MARGIN - (
        20 * MB + 2 * (IC.WINDOW_GAP + 4096) + IC.ALIGN)
    # with one, the widest spread of a record's windows
    reads = [100, 101, 9 * MB, 10 * MB + 5, 10 * MB + 15 * MB]
    got = E._dead_credit(byidx, [1, 2], reads)
    assert got == 30 * MB - 4 * IC.MARGIN - ((15 * MB + 1 - 5) + 2 * (IC.WINDOW_GAP + 4096)
                                             + IC.ALIGN)
    monkeypatch.setenv(IC.ENV, "0")
    assert E._dead_credited({1: 0, 2: 0}, {1: 501}, []) == []


def test_memory_check_refuses_a_build_that_did_not_come_out_small(tmp_path, monkeypatch):
    img = tmp_path / "image.bin"
    img.write_bytes(b"\0" * 1000)
    bank = tmp_path / "image-sc01.bin"
    bank.write_bytes(b"\0" * 500)

    class Plan(object):
        files = [(1, str(bank))]
    monkeypatch.setattr(SB, "MAPPED_MAX", 2000)
    E._memory_check(str(img), Plan())
    monkeypatch.setattr(SB, "MAPPED_MAX", 1400)
    with pytest.raises(E.SoundRoomError, match="could not all be taken out"):
        E._memory_check(str(img), Plan())


def _plan(monkeypatch, tmp_path, mapped, compact=True):
    """Ten longer game songs, 19 MB down to 10 MB, into banks beside an image.bin whose
    stock records of them are 30 MB each."""
    monkeypatch.setenv(IC.ENV, "1" if compact else "0")
    img = _image(tmp_path, md_off=400 * MB, count=11)
    sizes = {i: (20 - i) * MB for i in range(1, 11)}
    params = [{"idx": i, "chan": 2, "length": 30 * MB // 4, "findkey": bytes([i]) * 8,
               "body_off": 30 * MB * i} for i in sizes]
    grows = {i: (30 * MB // 4, n // 4 + 30 * MB // 4) for i, n in sizes.items()}
    audio_edits = {i: "idx%04d.wav" % i for i in grows}
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(SB, "BANK_SLICE", 5 * MB)
    monkeypatch.setattr(SB, "MAPPED_MAX", mapped)
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(11)), 11,
                                                    0x9000, 0))
    lines = []
    got = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, dict(grows), [], _Reader(), None, None,
        lambda m, *a: lines.append(m), game_sids={i: 500 + i for i in grows})
    return got, lines


def test_the_bank_plan_counts_image_bin_without_the_records_the_banks_play(
        monkeypatch, tmp_path):
    # image.bin 400 MB beside banks of 49..40 MB: without the 300 MB of their stock records
    # it and the eight biggest fit in 600 MB, with them they do not
    (plan, _e, _g), lines = _plan(monkeypatch, tmp_path, 600 * MB)
    assert plan.dead_credit > 200 * MB and plan.dead_idx == set(range(1, 11))
    assert plan.image_room == SB.MAPPED_MAX - sum(sorted(
        (SB.unit_bytes([SB.BankUnit([e])]) for _c, g in plan.banks for e in g),
        reverse=True)[:SB.SOUND_CHANNELS]) + plan.dead_credit
    assert any("come out of it, which nothing plays any more" in m for m in lines)
    with pytest.raises(E.SoundRoomError):
        _plan(monkeypatch, tmp_path, 600 * MB, compact=False)
