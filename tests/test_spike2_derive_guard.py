"""Fail-fast guards around the Spike 2 params derivation (fast; no boot, no card).

A field report: a Deadpool Pro 1.15 card sat on "Deriving codec parameters"
for 24+ minutes with no error, twice.  On a firmware build newer than the
locator knows, the master-directory malloc hook can fire on a mis-located PC
where r5 is NOT the record count; accepting the garbage value disarmed the
fail-fast watchdog and sent the derive into ``_ensure_range``/``mem_read`` over
``n * 24`` bytes -- gigabytes of page churn with no bound and no error.  The
capture (``_accept_masterdir_malloc``) now rejects an insane count so the
watchdog stays armed and the derive bails within ~1-2 min with the
unmapped-build error, naming the bogus count.
"""
import pytest

from pinball_decryptor.plugins.stern.spike2.emulator import (
    MAX_RECORDS, _accept_masterdir_malloc)


def _fresh_cap():
    return {"mddst": None, "nrec": None, "state": None, "badrec": None}


@pytest.mark.parametrize("n", [1, 131, 2000, 10500, MAX_RECORDS])
def test_sane_counts_accepted(n):
    """Every real catalog size (biggest shipped: D&D ~10.5k) is accepted and
    disarms the watchdog (accept -> True)."""
    cap = _fresh_cap()
    assert _accept_masterdir_malloc(cap, 0x30001000, n) is True
    assert cap["mddst"] == 0x30001000
    assert cap["nrec"] == n
    assert cap["badrec"] is None


@pytest.mark.parametrize("n", [
    0,                    # empty / uninitialised register
    MAX_RECORDS + 1,      # just past the ceiling
    0x30001234,           # a heap pointer where the count should be
    0xffffffff,           # -1 in a register
])
def test_insane_counts_rejected_and_named(n):
    """A wild r5 (mis-located hook on an unmapped build) must NOT be captured --
    capturing it is what turned the Deadpool 1.15 derive into an unbounded
    page-map churn.  The bogus value lands in cap["badrec"] so the
    unmapped-build error (which reprs cap) names it."""
    cap = _fresh_cap()
    assert _accept_masterdir_malloc(cap, 0x30001000, n) is False
    assert cap["mddst"] is None      # watchdog stays armed on this
    assert cap["nrec"] is None
    assert cap["badrec"] == n


def test_first_sane_hit_wins():
    """The capture is first-sane-hit-wins: once accepted, later hits are ignored
    (the malloc PC can re-fire; the first execution is the cat-0 decode)."""
    cap = _fresh_cap()
    assert _accept_masterdir_malloc(cap, 0x30001000, 2000) is True
    assert _accept_masterdir_malloc(cap, 0x40000000, 5000) is False
    assert cap["mddst"] == 0x30001000
    assert cap["nrec"] == 2000


def test_bad_hit_then_sane_hit_recovers():
    """A rejected hit must not poison the capture: if a later hit at the same PC
    carries a sane count, it is accepted (strictly more forgiving than stopping
    the emulation on the first bad value)."""
    cap = _fresh_cap()
    assert _accept_masterdir_malloc(cap, 0x30001000, 0x30001234) is False
    assert _accept_masterdir_malloc(cap, 0x30002000, 2000) is True
    assert cap["mddst"] == 0x30002000
    assert cap["nrec"] == 2000
    assert cap["badrec"] == 0x30001234   # the anomaly stays visible for the log


def test_bound_matches_category_gate():
    """The cat-0 capture and the per-category count gate share one definition of
    a sane record count (the category path always had this gate; the cat-0
    derive hang was the missing twin)."""
    import inspect

    from pinball_decryptor.plugins.stern.spike2 import category
    src = inspect.getsource(category.CatEmu._derive_cat)
    assert "MAX_RECORDS" in src
