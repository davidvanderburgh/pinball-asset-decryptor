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
    MAX_RECORDS, _accept_masterdir_malloc, _md_record_count)


class _FakeEng:
    """Just enough emulator for _md_record_count: r5 + the last-served alloc."""

    def __init__(self, r5, last_alloc=None):
        self.r5 = r5
        self._last_alloc = last_alloc
        self.mu = self           # _md_record_count reads eng.mu.reg_read(R5)

    def reg_read(self, _reg):
        return self.r5


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


def _align16(n):
    return (n + 15) & ~15


def test_count_from_malloc_size_classic_shape():
    """Deadpool 1.14-style build: r5 holds the raw count at the hook PC and the
    record-array malloc was served by the import stub -- both agree on 2000."""
    eng = _FakeEng(r5=2000, last_alloc=(0x30001000, _align16(2000 * 24)))
    assert _md_record_count(eng, 0x30001000) == 2000


def test_count_from_malloc_size_r5_clobbered():
    """Deadpool 1.16 Pro: the build reuses r5 for the ALIGNED BYTE SIZE it
    passes to malloc (add r5, r7, #0xf ; bic r5, r5, #0xf), so r5 reads ~24x
    high at the hook PC.  The size the import stub served the matching buffer
    for is ground truth: 48000 // 24 == 2000, not 48000."""
    eng = _FakeEng(r5=48000, last_alloc=(0x30001000, 48000))
    assert _md_record_count(eng, 0x30001000) == 2000


def test_count_odd_alignment_pad_is_floored_away():
    """An odd count's *24 size gets a 16-byte-alignment pad (< 24), so the
    floor division still recovers the exact count."""
    n = 2001
    eng = _FakeEng(r5=0xdead, last_alloc=(0x30001000, _align16(n * 24)))
    assert _md_record_count(eng, 0x30001000) == n


def test_count_falls_back_to_r5_when_alloc_unmatched():
    """A buffer the import stub didn't serve (or no alloc seen yet) keeps the
    legacy r5 read -- the validated-build behavior."""
    assert _md_record_count(_FakeEng(r5=2000), 0x30001000) == 2000
    eng = _FakeEng(r5=2000, last_alloc=(0x40000000, 48000))   # different buffer
    assert _md_record_count(eng, 0x30001000) == 2000
    eng = _FakeEng(r5=2000, last_alloc=(0x30001000, 8))       # too small for 1 rec
    assert _md_record_count(eng, 0x30001000) == 2000


def test_dp116_shape_end_to_end_accepted():
    """The 1.16 shape flows through capture: size-derived count 2000 is sane,
    accepted, and the watchdog would be disarmed on the true values."""
    eng = _FakeEng(r5=48000, last_alloc=(0x30001000, 48000))
    cap = _fresh_cap()
    n = _md_record_count(eng, 0x30001000)
    assert _accept_masterdir_malloc(cap, 0x30001000, n) is True
    assert cap["nrec"] == 2000


def test_bound_matches_category_gate():
    """The cat-0 capture and the per-category count gate share one definition of
    a sane record count (the category path always had this gate; the cat-0
    derive hang was the missing twin)."""
    import inspect

    from pinball_decryptor.plugins.stern.spike2 import category
    src = inspect.getsource(category.CatEmu._derive_cat)
    assert "MAX_RECORDS" in src
