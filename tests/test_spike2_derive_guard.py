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


def _asm(words):
    """Assemble a tiny ARM blob from raw u32 words (little-endian)."""
    import struct
    return b"".join(struct.pack("<I", w) for w in words)


def test_locator_reads_count_register_from_mul3():
    """locate._find_internal_pcs must report WHERE the count is live
    (MASTERDIR_COUNT) and WHICH register holds it (COUNTREG), read off the *24
    computation's `add rD, rN, rN, lsl #1`.  This is what makes the capture
    independent of whether the build later reuses rN for the malloc size."""
    from pinball_decryptor.plugins.stern.spike2 import locate as L

    # add lr, r5, r5, lsl #1 ; lsl r7, lr, #3 ; add r5, r7, #0xf ;
    # bic r5, r5, #0xf ; mov r4, r0 ; mov r0, r5 ; bl <malloc> ; subs r3, r0, #0
    # (the Deadpool 1.16 / TMNT 1.59 shape: r5 REUSED for the size)
    words = [0xe085e085, 0xe1a0718e, 0xe287500f, 0xe3c5500f,
             0xe1a04000, 0xe1a00005, 0xeb000000, 0xe2503000]
    ins = list(L._cs.disasm(_asm(words), 0x1000))
    assert [i.mnemonic for i in ins][:4] == ["add", "lsl", "add", "bic"], (
        "fixture did not assemble to the expected shape: %s"
        % [(i.mnemonic, i.op_str) for i in ins])
    # the *3 add carries the count register in operands 1 and 2
    p = [q.strip() for q in ins[0].op_str.split(",")]
    assert p[1] == p[2] == "r5"
    assert L._reg_index(p[1]) == 5


@pytest.mark.parametrize("name,idx", [
    ("r0", 0), ("r5", 5), ("r12", 12), ("sb", 9), ("sl", 10), ("fp", 11),
    ("ip", 12), (" r7 ", 7),
])
def test_reg_index_names(name, idx):
    """Capstone spells r9-r12 as sb/sl/fp/ip; the count register must resolve
    through either spelling (a build keeping the count in r9 would otherwise
    silently fall back to the r5 read)."""
    from pinball_decryptor.plugins.stern.spike2 import locate as L
    assert L._reg_index(name) == idx


def test_reg_index_rejects_non_gp():
    from pinball_decryptor.plugins.stern.spike2 import locate as L
    assert L._reg_index("sp") is None
    assert L._reg_index("lr") is None
    assert L._reg_index("r13") is None


def test_count_addrs_are_optional_not_required():
    """MASTERDIR_COUNT/COUNTREG must stay OUT of _REQUIRED: a build whose *24
    computation doesn't parse should still locate (and fall back to the
    malloc-return capture), not lose audio entirely."""
    from pinball_decryptor.plugins.stern.spike2 import locate as L
    assert "MASTERDIR_COUNT" not in L._REQUIRED
    assert "COUNTREG" not in L._REQUIRED


def test_emulator_defaults_count_addrs_to_none():
    """The validated (TMNT 1.58) hardcoded path has no located count site -- it
    doesn't need one (that build's size math uses a spare register, so r5 still
    holds the count at the malloc return).  The attributes must exist and be
    None so derive_params takes the fallback cleanly."""
    from pinball_decryptor.plugins.stern.spike2.emulator import Spike2Emu

    emu = Spike2Emu.__new__(Spike2Emu)
    Spike2Emu._set_addrs(emu, None)
    assert emu.MASTERDIR_COUNT is None
    assert emu.COUNTREG is None


def test_located_count_addrs_are_bound():
    """When the locator supplies them, _set_addrs must bind both (a missed
    binding silently reverts every generic build to the buggy r5 read)."""
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM

    addrs = {k: 0x1000 for k in (
        "BOOT_LO", "BOOT_HI", "VF2_VA", "REG_BASE", "PROV", "DISPATCH",
        "QMUL_TABLE", "CAT0_REGISTER", "RBTREE_HDR", "RBTREE_ACC",
        "MASTERDIR_DECODE", "MASTERDIR_MALLOC", "BANDLOOP", "BANDOBJ",
        "FIND_BL")}
    addrs.update(OBJREG=7, MASTERDIR_COUNT=0x2dad48, COUNTREG=5)
    emu = EM.Spike2Emu.__new__(EM.Spike2Emu)
    EM.Spike2Emu._set_addrs(emu, addrs)
    assert emu.MASTERDIR_COUNT == 0x2dad48
    assert emu.COUNTREG == 5


def test_bound_matches_category_gate():
    """The cat-0 capture and the per-category count gate share one definition of
    a sane record count (the category path always had this gate; the cat-0
    derive hang was the missing twin)."""
    import inspect

    from pinball_decryptor.plugins.stern.spike2 import category
    src = inspect.getsource(category.CatEmu._derive_cat)
    assert "MAX_RECORDS" in src
