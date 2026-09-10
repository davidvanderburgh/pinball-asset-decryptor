"""Re-pointing the game's play tables at an appended (grown) sound record.

The appended copy of a sound registers with the sound container under a key
of its own, so a descriptor that names the sound keeps naming the stock
record until it is rewritten.  These tests cover the pure parts of that
rewrite -- the key the firmware derives from a descriptor, the plan of
writes, and the reasons a sound is left un-grown -- and the write flow's
ordering around it.  The emulator steps themselves are stubbed.
"""

import struct

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import engine                 # noqa: E402
from tests.test_stern_audio_grow import (                           # noqa: E402
    BLOCK, _capture, _edits, _grow_card, _grow_on, _params, _run, _said)

__all__ = ["_grow_on"]      # the fixture is used here by name

MASK = engine._DESC_KEY2_MASK


def _key(w1, w2):
    return struct.pack("<II", w1, w2)


# --------------------------------------------------------------------------
# the key the game derives from a descriptor
# --------------------------------------------------------------------------
def test_play_key_keeps_the_first_word_and_masks_the_second():
    """Read off the firmware: w1 whole, w2 & 0xe0001fff.  The stock Led
    Zeppelin descriptor for idx 39 carries 0x1eef6d81 and the record's key
    is 0x00000d81."""
    assert engine._play_key(_key(0xd2694790, 0x1eef6d81), 180) == \
        _key(0xd2694790, 0x00000d81)


def test_play_key_folds_the_high_half_of_the_sid_in_above_bit_12():
    assert engine._play_key(_key(1, 0), 0x30000) == _key(1, 3 << 13)
    assert engine._play_key(_key(1, 0xffffffff), 0) == _key(1, MASK)


def test_op11_payloads_starts_after_the_header_and_finds_every_marker():
    desc = (b"\x05" + b"\x00" * 8 + b"\x0b\x00\x00\x00" + b"A" * 8
            + b"\x00" * 4 + b"\x0b\x00\x00\x00" + b"B" * 8 + b"\x00" * 8)
    assert engine._op11_payloads(desc) == [(13, b"A" * 8), (29, b"B" * 8)]
    # a marker inside the header is not a payload, and a truncated one is
    # not reported
    assert engine._op11_payloads(b"\x0b\x00\x00\x00" + b"\x00" * 5) == []
    assert engine._op11_payloads(b"\x00" * 9 + b"\x0b\x00\x00\x00" + b"x") == []


# --------------------------------------------------------------------------
# which grows survive, and what is written
# --------------------------------------------------------------------------
def _site(sid, off, payload, ks=b"\x00" * 8):
    return (sid, off, ks, payload)


def test_a_sound_no_play_table_names_is_not_grown_and_says_why():
    byidx = {0: {"idx": 0, "key0": 0x11}, 1: {"idx": 1, "key0": 0x22},
             2: {"idx": 2, "key0": None}}
    grows = {0: (10, 20), 1: (10, 20), 2: (10, 20)}
    sites = [_site(7, 0x100, _key(0x11, 0x1eef0000))]
    msgs, log = _capture()
    kept = engine._grows_named_by_a_descriptor(grows, byidx, sites, log)
    assert kept == {0: (10, 20)}
    assert _said(msgs, "idx 1: nothing in the game's play tables names")
    assert _said(msgs, "idx 2: this firmware's decode reports no container key")
    assert all("trimmed to fit" in m for _l, m in msgs)


def test_the_plan_rewrites_only_the_key_bits_under_the_same_whitening():
    """The middle sixteen bits of the second word are not the key and are
    kept; the whitening the descriptor already has is re-applied."""
    stock, new = _key(0xd2694790, 0x00000d81), _key(0xd7094794, 0x80000b86)
    ks = bytes(range(8))
    payload = _key(0xd2694790, 0x1eef6d81)
    sites = [_site(180, 0x2af2bdf2, payload, ks),
             _site(181, 0x2af2c000, _key(0x55, 0x66), ks)]   # someone else's
    params = [{"idx": 39, "grown": True, "stock_findkey": stock,
               "findkey": new},
              {"idx": 40, "grown": False}]
    writes, expect = engine._plan_descriptor_repoint(params, sites)
    want_plain = _key(0xd7094794, (0x1eef6d81 & ~MASK) | 0x80000b86)
    assert writes == {0x2af2bdf2: bytes(a ^ b for a, b in zip(want_plain, ks))}
    assert expect == {180: {new}}
    # what the game would derive from the rewritten payload IS the new key
    assert engine._play_key(want_plain, 180) == new


def test_the_plan_matches_on_all_eight_bytes_not_just_the_first_word():
    """Two records can share a first word; only the exact key is re-pointed."""
    stock = _key(0x11, 0x0d81)
    sites = [_site(1, 0x100, _key(0x11, 0x0d81)),
             _site(2, 0x200, _key(0x11, 0x0d82))]
    params = [{"idx": 0, "grown": True, "stock_findkey": stock,
               "findkey": _key(0x99, 0x0b86)}]
    writes, expect = engine._plan_descriptor_repoint(params, sites)
    assert list(writes) == [0x100]
    assert expect == {1: {_key(0x99, 0x0b86)}}


def test_the_plan_refuses_a_key_no_descriptor_can_carry():
    """Bits 13..28 of the second word are not the descriptor's to give, so a
    key with any of them set could never be looked up."""
    sites = [_site(1, 0x100, _key(0x11, 0x0d81))]
    params = [{"idx": 0, "grown": True, "stock_findkey": _key(0x11, 0x0d81),
               "findkey": _key(0x99, 0x00004000)}]
    with pytest.raises(RuntimeError, match="bits no descriptor can carry"):
        engine._plan_descriptor_repoint(params, sites)


def test_the_plan_refuses_a_grown_sound_nothing_names_or_without_a_key():
    sites = [_site(1, 0x100, _key(0x11, 0x0d81))]
    params = [{"idx": 5, "grown": True, "stock_findkey": _key(0x12, 0x0d81),
               "findkey": _key(0x99, 0x0b86)}]
    with pytest.raises(RuntimeError, match="idx 5: no descriptor"):
        engine._plan_descriptor_repoint(params, sites)
    params = [{"idx": 5, "grown": True, "stock_findkey": None,
               "findkey": _key(0x99, 0x0b86)}]
    with pytest.raises(RuntimeError, match="no container key"):
        engine._plan_descriptor_repoint(params, sites)


def test_two_grown_sounds_in_one_descriptor_are_both_expected():
    a, b = _key(0x11, 0x0d81), _key(0x22, 0x0d82)
    sites = [_site(1, 0x100, a), _site(1, 0x120, b)]
    params = [{"idx": 0, "grown": True, "stock_findkey": a,
               "findkey": _key(0x91, 1)},
              {"idx": 1, "grown": True, "stock_findkey": b,
               "findkey": _key(0x92, 2)}]
    writes, expect = engine._plan_descriptor_repoint(params, sites)
    assert set(writes) == {0x100, 0x120}
    assert expect == {1: {_key(0x91, 1), _key(0x92, 2)}}


# --------------------------------------------------------------------------
# the write flow
# --------------------------------------------------------------------------
def test_the_staged_bank_is_repointed_after_it_is_derived(monkeypatch,
                                                           tmp_path, _grow_on):
    params = _params(4)
    grown = [dict(p) for p in params]
    grown[0].update(body_off=0x40000, length=2 * 44100 + BLOCK, grown=True,
                    shadows=4)
    _reader, staged = _grow_card(monkeypatch, tmp_path, params,
                                 grown_rows=grown)
    assets, _wavp = _edits(tmp_path, 2.0)
    msgs, log = _capture()

    _writes, counts, plan, _mode, _vp = _run(
        monkeypatch, assets, params, 0x40000, log)

    rp = staged["repointed"]
    assert rp["path"] == staged["path"], "re-pointed a file other than the staged bank"
    assert rp["params"] is not None and rp["params"][0].get("grown")
    assert [s[0] for s in rp["sites"]] == [100, 101, 102, 103]
    assert counts[0] == 1
    assert _said(msgs, "the sound bank grows to keep it whole")


def test_a_sound_no_play_table_names_trims_instead_of_growing(monkeypatch,
                                                              tmp_path,
                                                              _grow_on):
    params = _params(4)
    _reader, staged = _grow_card(monkeypatch, tmp_path, params)
    # nothing names idx 0
    monkeypatch.setattr(engine, "_descriptor_sites",
                        lambda gr, img, log=None: [
                            (101, 0x308, b"\x00" * 8, struct.pack("<II", 1, 0))])
    assets, _wavp = _edits(tmp_path, 2.0)
    msgs, log = _capture()

    writes, counts, plan, _mode, _vp = _run(
        monkeypatch, assets, params, params[0]["body_off"], log)

    assert "path" not in staged, "the bank was staged for a sound nothing plays"
    assert "path" not in staged["repointed"]
    assert _said(msgs, "idx 0: nothing in the game's play tables names")
    assert not _said(msgs, "the sound bank grows to keep it whole")
    assert plan is None or not plan.get("jobs")
