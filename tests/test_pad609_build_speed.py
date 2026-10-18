"""PAD-609: long builds faster still.

A Godzilla build with 11 modes' music spent most of its 9 minutes in the
emulator paying Python for work it did not need: every decode check of an
encoded song ran with the keystream recovery's per-sample capture hooks still
on (86 million calls), every emulator boot ran under the per-instruction
global hook (57 boots a build), each mode's loudness reference was decoded
up front even when the encode it served came from the cache, the mode clip
cache was too small for the clips one build makes and threw them all out
each time, and the final check of the replaced sounds decoded them one after
another.

Fast tests pin each piece on stubs and a real unicorn; the card-gated ones
(``slow``) compare the narrow boot with the global one on real cards and a
decode with the capture hooks on against one without.
"""
import os
import struct

import pytest

pytest.importorskip("unicorn")

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc  # noqa: E402
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0  # noqa: E402

from pinball_decryptor.plugins.stern.spike2 import emulator as EM  # noqa: E402
from tests import test_spike2_narrow_derive as ND  # noqa: E402

NOP = struct.pack("<I", 0xE1A00000)          # mov r0, r0
CODE = ND.CODE


# --------------------------------------------------------------------------
# a PLT thunk the validated build's table also names
# --------------------------------------------------------------------------
def _thunk_emu():
    """An emulator stub whose code at CODE+8 is both one of this build's PLT
    thunks (GOT slot -> CODE+0x40) and an address in the validated build's
    :attr:`PLT` table (a handler that returns to LR, as TMNT 1.58's munmap
    stub does)."""
    emu = ND._stub(32)
    got = CODE + 0x800
    emu.mu.mem_write(got, struct.pack("<I", CODE + 0x40))
    emu._plt_entry = {CODE + 8: got}
    hits = []

    def ret0(eng):
        hits.append("handler")
        eng.mu.reg_write(UC_ARM_REG_R0, 0)
        eng.mu.reg_write(UC_ARM_REG_PC, eng.mu.reg_read(UC_ARM_REG_LR))
    emu.PLT = {CODE + 8: ret0}
    emu.mu.hook_add(UC_HOOK_CODE, emu._plt_branch, begin=CODE + 8, end=CODE + 8)
    return emu, hits


def _where_it_went(emu):
    seen = []
    emu.mu.hook_add(UC_HOOK_CODE, lambda mu, a, s, u: seen.append(a),
                    begin=CODE + 0x3c, end=CODE + 0x44)
    emu.mu.reg_write(UC_ARM_REG_LR, CODE + 0x3c)
    emu.mu.reg_write(UC_ARM_REG_R0, 7)
    emu.mu.emu_start(CODE, CODE + 0x44)
    return seen, emu.mu.reg_read(UC_ARM_REG_R0)


def test_a_thunk_in_the_validated_table_goes_where_the_global_hook_sends_it():
    glob, ghits = _thunk_emu()
    g_seen, g_r0 = _where_it_went(glob)
    narrow, nhits = _thunk_emu()
    narrow._narrow_derive_begin(())
    n_seen, n_r0 = _where_it_went(narrow)
    # the global hook runs the table's handler, then the thunk branch has the
    # last word: the run goes on at the GOT target, never back to LR
    assert ghits == ["handler"] and g_seen == [CODE + 0x40] and g_r0 == 0
    assert (nhits, n_seen, n_r0) == (ghits, g_seen, g_r0)


def test_narrow_boot_is_for_generic_builds_only(monkeypatch):
    emu = ND._stub()
    monkeypatch.delenv(EM.BOOT_HOOKS_ENV, raising=False)
    assert emu.narrow_boot()
    monkeypatch.setenv(EM.BOOT_HOOKS_ENV, "global")
    assert not emu.narrow_boot()
    monkeypatch.delenv(EM.BOOT_HOOKS_ENV)
    emu._generic = False                      # the validated TMNT 1.58 path
    assert not emu.narrow_boot()


def test_a_narrow_boot_puts_the_global_hook_back(monkeypatch):
    emu = ND._stub()
    monkeypatch.delenv(EM.BOOT_HOOKS_ENV, raising=False)
    seen = []

    def fake_boot():
        seen.append((emu._narrow, emu._global_hook))
        return emu
    emu._boot = fake_boot
    assert emu.boot() is emu
    assert seen == [(True, None)]
    assert not emu._narrow and emu._global_hook is not None


# --------------------------------------------------------------------------
# capture hooks off for a whole decode
# --------------------------------------------------------------------------
def test_a_decode_takes_the_recoveries_capture_hooks_off():
    from pinball_decryptor.plugins.stern.spike2 import codec
    emu = ND._stub(16)
    emu._switch_to_narrow_hooks()

    class Rec:
        pass
    rec = Rec()
    rec.emu, rec.mu = emu, emu.mu
    rec._hooked = {CODE + 4}
    hits = []
    rec._handles = [emu.mu.hook_add(UC_HOOK_CODE, lambda *a: hits.append(1),
                                    begin=CODE + 4, end=CODE + 4)]
    codec._own_captures(emu, rec)
    ND._run(emu)
    assert hits == [1]
    codec.drop_captures(emu)
    ND._run(emu)
    assert hits == [1], "the capture hook still fired"
    assert rec._handles == [] and rec._hooked == set()
    codec.drop_captures(emu)                  # nothing left: a no-op


def test_the_recoveries_name_themselves_to_their_emulator():
    from pinball_decryptor.plugins.stern.spike2 import codec
    src = open(codec.__file__, encoding="utf-8").read()
    # both recoveries register (so a decode finds them) and keep their handles
    assert src.count("_own_captures(emu, self)") == 2
    assert src.count("self._handles.append(") >= 4
    em = open(EM.__file__, encoding="utf-8").read()
    i = em.index("def _decode_with_entry")
    assert "drop_captures(self)" in em[i:i + 800]


# --------------------------------------------------------------------------
# loudness references decoded when an encode needs one
# --------------------------------------------------------------------------
def test_a_loudness_reference_is_decoded_only_when_asked_and_once():
    from pinball_decryptor.plugins.stern import engine as E
    calls = []
    refs = E._LazyRefs({5: {"idx": 9}}, lambda idx, q: calls.append((idx, q["idx"])) or "pcm")
    assert 5 in refs and 6 not in refs and calls == []
    base = {"gain_db": 1}
    assert refs.kw(6, base) is base           # no reference: kw as given
    assert refs.kw(5, base) == {"gain_db": 1, "orig": "pcm"}
    assert refs.kw(5, base)["orig"] == "pcm"
    assert calls == [(5, 9)] and base == {"gain_db": 1}


# --------------------------------------------------------------------------
# the mode clip cache holds a whole build's clips
# --------------------------------------------------------------------------
def _clips(folder, sizes):
    os.makedirs(folder, exist_ok=True)
    for i, n in enumerate(sizes):
        p = os.path.join(folder, "c%03d.mp4" % i)
        with open(p, "wb") as f:
            f.write(b"\x00" * n)
        os.utime(p, (1000 + i, 1000 + i))     # c000 the oldest


def test_the_clip_cache_keeps_a_big_builds_clips(tmp_path):
    from pinball_decryptor.plugins.stern import mode_assets as MA
    folder = str(tmp_path / "cache")
    _clips(folder, [10] * 80)                 # Godzilla's 11 modes make 76
    MA._prune_clip_cache(folder)
    assert len(os.listdir(folder)) == 80


def test_the_clip_cache_drops_the_oldest_past_its_budget(tmp_path):
    from pinball_decryptor.plugins.stern import mode_assets as MA
    folder = str(tmp_path / "cache")
    _clips(folder, [40] * 10)
    MA._prune_clip_cache(folder, budget=200)
    assert sorted(os.listdir(folder)) == ["c%03d.mp4" % i for i in range(5, 10)]
    MA._prune_clip_cache(folder, keep=2)
    assert sorted(os.listdir(folder)) == ["c008.mp4", "c009.mp4"]
    _clips(str(tmp_path / "big"), [500])
    MA._prune_clip_cache(str(tmp_path / "big"), budget=100)
    assert os.listdir(str(tmp_path / "big")) == ["c000.mp4"], "the newest always stays"


# --------------------------------------------------------------------------
# the final-bytes check on workers
# --------------------------------------------------------------------------
def test_a_short_final_check_stays_in_one_process(monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2 import parallel
    monkeypatch.setattr(parallel, "block_workers", lambda: 8)
    short = [(0, {"length": 44100}, b"", True)] * 3
    assert E._final_checks_parallel("gr", "img", [], [], short, None, None) is None
    monkeypatch.setattr(parallel, "block_workers", lambda: 0)
    long_ = [(0, {"length": 44100 * 60}, b"", True)] * 3
    assert E._final_checks_parallel("gr", "img", [], [], long_, None, None) is None


def test_a_final_check_whose_workers_fail_says_so_and_hands_back(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2 import parallel
    monkeypatch.setattr(parallel, "block_workers", lambda: 2)
    logs = []
    tasks = [(i, {"length": 44100 * 30, "idx": i}, b"\x00" * 8, True) for i in range(2)]
    got = E._final_checks_parallel(str(tmp_path / "no_game_real"), str(tmp_path / "no_img"),
                                   [], [], tasks, lambda t, l="info": logs.append(t), None)
    assert got is None
    assert any("one process" in t for t in logs)


# --------------------------------------------------------------------------
# card-gated
# --------------------------------------------------------------------------
_no_faulthandler = ND._no_faulthandler


def _booted_state(gr, img, hooks):
    import hashlib
    old = os.environ.get(EM.BOOT_HOOKS_ENV)
    os.environ[EM.BOOT_HOOKS_ENV] = hooks
    try:
        emu = EM.Spike2Emu(gr, img)
        try:
            if not emu.audio_supported:
                pytest.skip("audio decode is not supported for this build")
            emu.boot()
            assert emu.narrow_boot() == (hooks == "")
            regs = [emu.mu.reg_read(r) for r in range(UC_ARM_REG_R0, UC_ARM_REG_R0 + 16)]
            mem = {(lo, hi): hashlib.sha1(bytes(emu.mu.mem_read(lo, hi - lo + 1))).hexdigest()
                   for lo, hi, _p in emu.mu.mem_regions() if hi - lo < (256 << 20)}
            return regs, mem
        finally:
            emu.close()
    finally:
        if old is None:
            os.environ.pop(EM.BOOT_HOOKS_ENV, None)
        else:
            os.environ[EM.BOOT_HOOKS_ENV] = old


@pytest.mark.slow
@pytest.mark.parametrize("title", sorted(ND.CARDS))
def test_a_narrow_boot_leaves_the_machine_the_global_hook_leaves(title):
    gr, img = ND._inputs(title)
    assert _booted_state(gr, img, "") == _booted_state(gr, img, "global")


@pytest.mark.slow
def test_a_decode_with_the_capture_hooks_on_gives_the_same_samples():
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.codec import GenRecover, StereoRecover
    gr_path, img = ND._inputs("godzilla_le_116")
    emu = EM.Spike2Emu(gr_path, img)
    try:
        emu.boot()
        rows = []

        def after(idx, row, redo):
            rows.append(dict(row))
            if len(rows) >= 400:
                raise ND._Enough()
        try:
            emu.derive_params(after_step=after)
        except ND._Enough:
            pass
        emu.warm_slots_for_grown(rows)
        st = max((r for r in rows if r["chan"] == 2), key=lambda r: r["length"])
        mo = max((r for r in rows if r["chan"] == 1), key=lambda r: r["length"])
        plain = [emu.decode(p) for p in (st, mo)]
        sr, gr = StereoRecover(emu), GenRecover(emu)
        a = sr.recover_block(st, 2000, nf=200)
        b = gr.recover_block(mo, 2000, n=200)
        assert sr._handles and gr._handles
        hooked = [emu.decode(p) for p in (st, mo)]
        assert not sr._handles and not gr._handles, "the decode left them on"
        for x, y in zip(plain, hooked):
            assert np.array_equal(x[0], y[0]) and x[2] == y[2]
            if x[2]:
                assert np.array_equal(x[1], y[1])
        # and the recoveries put their hooks back and recover as before
        assert repr(sr.recover_block(st, 2000, nf=200)) == repr(a)
        assert repr(gr.recover_block(mo, 2000, n=200)) == repr(b)
    finally:
        emu.close()
