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

from unicorn import UC_HOOK_CODE  # noqa: E402
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0  # noqa: E402

from pinball_decryptor.plugins.stern.spike2 import emulator as EM  # noqa: E402
from tests import test_spike2_narrow_derive as ND  # noqa: E402

NOP = struct.pack("<I", 0xE1A00000)          # mov r0, r0
CODE = ND.CODE


from pinball_decryptor.plugins.stern.spike2 import parallel as _PAR  # noqa: E402

_REAL_COMMIT_ROOM = _PAR.commit_room


@pytest.fixture(autouse=True)
def _commit_room_unknown(monkeypatch):
    """Worker counts here are the cores'; a test of the commit budget sets its own room."""
    monkeypatch.setattr(_PAR, "commit_room", lambda: None)


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


# --------------------------------------------------------------------------
# the banks of a Write side by side
# --------------------------------------------------------------------------
class _ThreadPool:
    """ProcessPoolExecutor's stand-in: the same calls on threads, so a stubbed
    encode is what the workers run."""

    def __init__(self, n, mp_context=None, **kw):
        from concurrent.futures import ThreadPoolExecutor
        self._p = ThreadPoolExecutor(n)

    def submit(self, fn, *a):
        return self._p.submit(fn, *a)

    def shutdown(self, wait=True, cancel_futures=False):
        self._p.shutdown(wait=wait, cancel_futures=cancel_futures)


def _bank_stub(monkeypatch, delays=None, fail=None):
    import concurrent.futures as CF
    import time
    from pinball_decryptor.plugins.stern import bank_build as BB
    monkeypatch.setattr(CF, "ProcessPoolExecutor", _ThreadPool)
    seen = []

    def fake(gr, img, job, params, np, log, loops=(), gains=None, level_refs=None,
             progress=None, cancel=None, revalidate=None, body_cache=None):
        time.sleep((delays or {}).get(job.cat, 0))
        seen.append((job.cat, revalidate))
        log("bank %d encoded" % job.cat)
        if fail == job.cat:
            raise RuntimeError("bank %d's chain never reached sound(s) [7]" % job.cat)
        if body_cache is not None:
            body_cache.used.add("k%d" % job.cat)
            body_cache.hits += 1
        return [{"idx": 0, "host": job.cat}], "rev-of-%d" % (revalidate is None and job.cat or 1)
    monkeypatch.setattr(BB, "encode_and_verify", fake)
    jobs = [BB.BankJob(c, "sc%02d" % c, [], {}) for c in range(1, 6)]
    return BB, jobs, seen


def test_banks_come_back_in_order_with_their_lines_in_order(monkeypatch):
    BB, jobs, seen = _bank_stub(monkeypatch, delays={2: 0.3, 3: 0.0, 4: 0.1})
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "4")
    logs = []

    class Cache:
        used, hits = set(), 0
    cache = Cache()
    out = BB.encode_banks("gr", "img", jobs, [], None,
                          lambda m, lv="info": logs.append(m), body_cache=cache)
    assert [r[0][0]["host"] for r in out] == [1, 2, 3, 4, 5]
    lines = [m for m in logs if m.startswith("bank ")]
    assert lines == ["bank %d encoded" % c for c in range(1, 6)]
    # the first bank settles the stub; every later one is handed it
    assert seen[0] == (1, None) and {r for c, r in seen[1:]} == {"rev-of-1"}
    assert cache.used == {"k1", "k2", "k3", "k4", "k5"} and cache.hits == 5
    assert any("at a time" in m for m in logs)


def test_a_failing_bank_stops_the_write_with_its_own_words(monkeypatch):
    BB, jobs, _seen = _bank_stub(monkeypatch, fail=3)
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "4")
    logs = []
    with pytest.raises(RuntimeError) as e:
        BB.encode_banks("gr", "img", jobs, [], None, lambda m, lv="info": logs.append(m))
    assert str(e.value) == "bank 3's chain never reached sound(s) [7]"
    assert "bank 3 encoded" in logs and "bank 4 encoded" not in logs[:logs.index("bank 3 encoded")]


def test_one_bank_worker_is_the_old_one_after_another(monkeypatch):
    BB, jobs, seen = _bank_stub(monkeypatch)
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "1")
    import concurrent.futures as CF

    def no_pool(*a, **k):
        raise AssertionError("a pool was started")
    monkeypatch.setattr(CF, "ProcessPoolExecutor", no_pool)
    out = BB.encode_banks("gr", "img", jobs, [], None, lambda *a: None)
    assert [c for c, _r in seen] == [1, 2, 3, 4, 5] and len(out) == 5


def test_the_bank_worker_count(monkeypatch):
    from pinball_decryptor.plugins.stern import bank_build as BB
    monkeypatch.delenv(BB.BANK_WORKERS_ENV, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert BB.bank_workers(11) == 4
    assert BB.bank_workers(3) == 2          # the banks after the first
    assert BB.bank_workers(1) == 1
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    assert BB.bank_workers(11) == 1
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "3")
    assert BB.bank_workers(11) == 3


def test_the_bank_worker_count_is_no_part_of_an_audio_cache_key(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    gr = tmp_path / "game_real"
    gr.write_bytes(b"fw")
    monkeypatch.delenv("PAD_STERN_BANK_WORKERS", raising=False)
    a = E._audio_cache_base_key(str(gr), b"id")
    monkeypatch.setenv("PAD_STERN_BANK_WORKERS", "1")
    assert E._audio_cache_base_key(str(gr), b"id") == a


# --------------------------------------------------------------------------
# a picture's stock pixels decoded only when they decide something
# --------------------------------------------------------------------------
def test_a_premultiplied_picture_never_decodes_its_stock_one():
    np = pytest.importorskip("numpy")
    from pinball_decryptor.plugins.stern import engine as E
    calls = []
    arr = np.zeros((8, 8, 4), np.uint8)
    arr[..., 3] = 200
    arr[..., :3] = 100                              # colour <= alpha: premultiplied
    out, changed = E._premultiply_like_stock(arr, lambda: calls.append(1))
    assert out is arr and not changed and calls == []


def test_a_lazy_stock_picture_gives_what_the_decoded_one_gave():
    np = pytest.importorskip("numpy")
    from pinball_decryptor.plugins.stern import engine as E
    rng = np.random.default_rng(3)
    straight = rng.integers(0, 256, (8, 8, 4), dtype=np.uint8)
    straight[..., 3] = 40                           # colour brighter than alpha
    premult = np.zeros((8, 8, 4), np.uint8)
    for stock in (premult, straight, None):
        want = E._premultiply_like_stock(straight, stock)
        got = E._premultiply_like_stock(straight, lambda s=stock: s)
        assert got[1] == want[1] and np.array_equal(got[0], want[0])

    def broken():
        raise ValueError("no stock bytes")
    want = E._premultiply_like_stock(straight, None)
    got = E._premultiply_like_stock(straight, broken)
    assert got[1] == want[1] and np.array_equal(got[0], want[0])


# --------------------------------------------------------------------------
# a long song's blocks across processes beside the cat-0 pool
# --------------------------------------------------------------------------
def _rows(*lengths):
    return [{"idx": i, "chan": 2, "length": n, "body_off": 0x10000 * (i + 1)}
            for i, n in enumerate(lengths)]


def _split(monkeypatch, lengths, cpus=16, blocks=8):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2 import parallel
    monkeypatch.setattr(E.os, "cpu_count", lambda: cpus)
    monkeypatch.setattr(parallel, "block_workers", lambda: blocks)
    rows = _rows(*lengths)
    byidx = {r["idx"]: r for r in rows}
    todo = sorted(((r["idx"], "w%d" % r["idx"]) for r in rows),
                  key=lambda e: -byidx[e[0]]["length"])
    return E._cat0_long_split(todo, byidx, min(cpus - 2, 8))


def test_a_song_longer_than_an_even_share_is_split_off(monkeypatch):
    # the Godzilla project: one 205 s song among 79 shorter sounds
    long_, short, n = _split(monkeypatch, [9036650, 4108718, 3806279] + [400000] * 77)
    assert [i for i, _w in long_] == [0]
    assert len(short) == 79 and n == 6, "the pool's 8 workers leave 6 of 14 cores"


def test_one_long_song_alone_gets_every_block_worker(monkeypatch):
    long_, short, n = _split(monkeypatch, [9036650])
    assert [i for i, _w in long_] == [0] and short == [] and n == 8


def test_nothing_is_split_without_a_long_song_or_the_cores(monkeypatch):
    long_, short, n = _split(monkeypatch, [400000] * 20)
    assert long_ == [] and len(short) == 20 and n == 0
    # a "long" sound too short for block workers stays in the pool
    long_, short, n = _split(monkeypatch, [40000, 100, 100])
    assert long_ == [] and n == 0
    # 8 cores: the pool takes the 6 a computer spares, no room for blocks
    long_, short, n = _split(monkeypatch, [9036650] + [400000] * 20, cpus=8, blocks=6)
    assert long_ == [] and len(short) == 21 and n == 0


def _dispatch(monkeypatch, lengths, long_ok=True):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2 import parallel
    monkeypatch.setattr(E, "_FORCE_SERIAL_ENCODE", False)
    monkeypatch.setattr(E.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(parallel, "block_workers", lambda: 8)
    rows = _rows(*lengths)
    seen = {"serial": []}

    def body(edits):
        return ({r: b"%d" % i for i, _w in edits for r in [rows[i]["body_off"]]}, [],
                {i: (rows[i]["body_off"], b"%d" % i) for i, _w in edits})

    def fake_parallel(gr, img, params, edits, nworkers, np, log, progress, cancel,
                      gains=None, edited=None, **_k):
        seen["pool"] = ([i for i, _w in edits], sorted(edited), nworkers)
        done, _sk, res = body(edits)
        return done, [], [], res

    def fake_serial(gr, img, byidx, edits, np, log, progress, cancel, gains=None,
                    blocks=None, edited=None, **_k):
        seen["serial"].append(([i for i, _w in edits], sorted(edited), blocks is not None))
        if blocks is not None and not long_ok:
            raise RuntimeError("block workers fell over")
        return body(edits)
    monkeypatch.setattr(E, "_encode_cat0_parallel", fake_parallel)
    monkeypatch.setattr(E, "_encode_cat0_serial", fake_serial)
    logs = []
    edits = {r["idx"]: "w%d" % r["idx"] for r in rows}
    patches, skipped = E._encode_cat0_sounds(
        "g", "i", rows, edits, None, lambda t, l="info": logs.append((l, t)), None,
        lambda: False)
    return rows, seen, patches, logs


def test_the_long_song_and_the_pool_encode_side_by_side_warmed_alike(monkeypatch):
    rows, seen, patches, logs = _dispatch(monkeypatch, [9036650] + [400000] * 9)
    every = list(range(10))
    assert seen["pool"] == (list(range(1, 10)), every, 8)
    assert seen["serial"] == [([0], every, True)], \
        "the long song: one emulator with block workers, warmed as the pool's"
    assert patches == {r["body_off"]: b"%d" % r["idx"] for r in rows}
    assert any("idx 0 (204 s) encoded with its blocks across 6" in t for _l, t in logs)


def test_a_long_song_whose_workers_fail_is_encoded_again_in_one_process(monkeypatch):
    rows, seen, patches, logs = _dispatch(monkeypatch, [9036650] + [400000] * 9,
                                          long_ok=False)
    assert seen["serial"] == [([0], list(range(10)), True), ([0], list(range(10)), False)]
    assert patches == {r["body_off"]: b"%d" % r["idx"] for r in rows}
    assert any(l == "warning" and "again in one process" in t for l, t in logs)


def test_block_workers_warm_with_the_writes_edited_sounds(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2 import parallel
    got = {}

    class Pool:
        def __init__(self, kind, gr, img, rows, n, **kw):
            got.update(kw, n=n)
    monkeypatch.setattr(parallel, "BlockPool", Pool)
    monkeypatch.setattr(parallel, "block_workers", lambda: 8)
    parallel.start_block_pool("image", "g", "i", [], first_warm=[], first_edited=[3, 5],
                              longest=10 ** 6, workers=6)
    assert got["first_edited"] == [3, 5] and got["n"] == 6
    assert parallel.start_block_pool("image", "g", "i", [], longest=10 ** 6,
                                     workers=1) is None


@pytest.mark.slow
def test_a_long_song_with_block_workers_is_the_pools_own_bytes(tmp_path):
    """The cat-0 encode of a long song in the app with block workers gives the
    bytes an encode worker gives it alone (the build-wide proof: Godzilla LE
    1.16, 80 replaced sounds and one 205 s song, every card file identical)."""
    import wave
    np = pytest.importorskip("numpy")
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    gr, img = ND._inputs("godzilla_le_116")
    params = E._params_for(gr, img, lambda *a, **k: None, None)
    p = min((q for q in params if q["chan"] == 2 and q["length"] >= 200 * 600),
            key=lambda q: q["length"])
    wav = str(tmp_path / "song.wav")
    t = np.arange(p["length"]) / 44100.0
    s = (8000 * np.sin(2 * np.pi * 330 * t)).astype(np.int16)
    with wave.open(wav, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(np.stack([s, s[::-1]], 1).tobytes())
    edited = [p["idx"]]
    P.init_encode_worker(gr, img, params, {}, edited, {})
    _i, off, body, ok = P.encode_one((p["idx"], wav))
    assert ok
    byidx = {q["idx"]: q for q in params}

    def blocks(_emu):
        return P.start_block_pool("image", gr, img, params, first_warm=params,
                                  first_edited=edited, longest=p["length"], workers=4)
    patches, skipped, _r = E._encode_cat0_serial(
        gr, img, byidx, [(p["idx"], wav)], np, lambda *a, **k: None, None,
        lambda: False, blocks=blocks, edited=edited)
    assert skipped == [] and patches == {off: body}


# --------------------------------------------------------------------------
# every bank to the workers at once when the stub is known up front
# --------------------------------------------------------------------------
def test_a_known_stub_sends_every_bank_to_the_workers(monkeypatch):
    BB, jobs, seen = _bank_stub(monkeypatch)
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "4")
    monkeypatch.setattr(BB, "known_revalidate", lambda gr, img: 0x3b57d8)
    logs, prog = [], []
    out = BB.encode_banks("gr", "img", jobs, [], None, lambda m, lv="info": logs.append(m),
                          progress=lambda a, b, t="": prog.append(t))
    assert [r[0][0]["host"] for r in out] == [1, 2, 3, 4, 5]
    assert sorted(seen) == [(c, 0x3b57d8) for c in range(1, 6)], "none encoded in the app"
    assert [m for m in logs if m.startswith("bank ")] == ["bank %d encoded" % c
                                                         for c in range(1, 6)]
    assert any("image-sc01.bin, image-sc02.bin" in m and "4 at a time" in m for m in logs)
    assert prog and prog[0].endswith("(1 of 5)...") and prog[-1].endswith("(5 of 5)...")


def test_the_stub_is_known_only_when_the_program_has_one_candidate(monkeypatch):
    from pinball_decryptor.plugins.stern import bank_build as BB
    from pinball_decryptor.plugins.stern.spike2 import category as CAT
    locs = {}

    class Emu:
        def __init__(self, gr, img):
            if locs.get("boom"):
                raise RuntimeError("no game program")
            self._cat_locs = locs.get("locs")

        def close(self):
            pass
    monkeypatch.setattr(CAT, "CatEmu", Emu)
    locs["locs"] = {"REVALIDATE_CANDIDATES": [0x3b57d8]}
    assert BB.known_revalidate("gr", "img") == 0x3b57d8
    locs["locs"] = {"REVALIDATE_CANDIDATES": [0x1000, 0x2000]}
    assert BB.known_revalidate("gr", "img") is None, "the first bank's derive picks one"
    locs["locs"] = None
    assert BB.known_revalidate("gr", "img") is None
    locs["boom"] = True
    assert BB.known_revalidate("gr", "img") is None


def test_the_bank_worker_count_with_the_first_bank_too(monkeypatch):
    from pinball_decryptor.plugins.stern import bank_build as BB
    monkeypatch.delenv(BB.BANK_WORKERS_ENV, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert BB.bank_workers(3, first_too=True) == 3
    assert BB.bank_workers(2, first_too=True) == 2 and BB.bank_workers(2) == 1
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "9")
    assert BB.bank_workers(5, first_too=True) == 5


def test_the_biggest_banks_go_to_the_workers_first(monkeypatch, tmp_path):
    BB, _jobs, _seen = _bank_stub(monkeypatch)
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "2")
    monkeypatch.setattr(BB, "known_revalidate", lambda gr, img: 7)
    jobs = []
    for c, size in ((1, 10), (2, 5000), (3, 300), (4, 90000)):
        wav = tmp_path / ("b%d.wav" % c)
        wav.write_bytes(b"\0" * size)
        jobs.append(BB.BankJob(c, "sc%02d" % c, [], {c: str(wav)}))
    order = []
    submit = _ThreadPool.submit

    def spy(self, fn, task):
        order.append(task[2].cat)
        return submit(self, fn, task)
    monkeypatch.setattr(_ThreadPool, "submit", spy)
    out = BB.encode_banks("gr", "img", jobs, [], None, lambda *a, **k: None)
    assert order == [4, 2, 3, 1]
    assert [r[0][0]["host"] for r in out] == [1, 2, 3, 4], "results stay in bank order"


# --------------------------------------------------------------------------
# no more emulators than the computer can commit the memory of
# --------------------------------------------------------------------------
def test_an_emulator_commits_its_files_and_a_margin(tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    img = tmp_path / "image.bin"
    img.write_bytes(b"\0" * 1000)
    assert P.emulator_commit(str(img)) == P.EMU_COMMIT_EXTRA + 1000
    assert P.emulator_commit(str(img), None, str(tmp_path / "gone")) == P.EMU_COMMIT_EXTRA + 1000


def test_the_emulators_that_fit(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    gb = 1 << 30
    monkeypatch.setattr(P, "commit_room", lambda: None)
    assert P.emulators_that_fit(3 * gb, 16) == 16, "Linux and macOS: as many as asked"
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + 10 * gb)
    assert P.emulators_that_fit(3 * gb, 16) == 3
    assert P.emulators_that_fit(3 * gb, 2) == 2
    monkeypatch.setattr(P, "commit_room", lambda: gb)
    assert P.emulators_that_fit(3 * gb, 16) == 1, "the encode always gets its one"


@pytest.mark.skipif(os.name != "nt", reason="Windows' commit limit")
def test_windows_says_how_much_it_can_commit():
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    room = _REAL_COMMIT_ROOM()
    assert room is not None and room > 0


def test_a_short_commit_holds_the_block_workers_back(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    monkeypatch.setattr(P, "block_workers", lambda: 8)
    made = []

    class Pool:
        def __init__(self, kind, gr, img, rows, n, **kw):
            made.append(n)
    monkeypatch.setattr(P, "BlockPool", Pool)
    per = P.emulator_commit(None)
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + 3 * per)
    P.start_block_pool("image", "g", None, [], longest=10 ** 6)
    assert made == [3]
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + per)
    assert P.start_block_pool("image", "g", None, [], longest=10 ** 6) is None


def test_a_short_commit_shrinks_the_pool_and_keeps_the_long_song_whole(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    per = P.emulator_commit("i")
    # room for 9 emulators: the pool's 8 and the long song's own one, no blocks
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + 9 * per)
    rows, seen, patches, logs = _dispatch(monkeypatch, [9036650] + [400000] * 9)
    assert seen["pool"][0] == list(range(10)) and seen["pool"][2] == 8
    assert seen["serial"] == []
    # room for 4: a pool of 4, said in the log
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + 4 * per)
    rows, seen, patches, logs = _dispatch(monkeypatch, [9036650] + [400000] * 9)
    assert seen["pool"][2] == 4
    assert any("on 4 process(es), not 8" in t for _l, t in logs)
    assert patches == {r["body_off"]: b"%d" % r["idx"] for r in rows}
    # room for one: the one-process encode
    monkeypatch.setattr(P, "commit_room", lambda: 0)
    rows, seen, patches, logs = _dispatch(monkeypatch, [9036650] + [400000] * 9)
    assert "pool" not in seen and [s[0] for s in seen["serial"]] == [list(range(10))]


def test_a_short_commit_holds_the_bank_workers_back(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    BB, jobs, seen = _bank_stub(monkeypatch)
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "4")
    monkeypatch.setattr(BB, "known_revalidate", lambda gr, img: 7)
    monkeypatch.setattr(P, "block_workers", lambda: 8)
    per = P.emulator_commit(None)
    # room for 5 emulators: two banks at a time (two emulators each), no blocks
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + 5 * per)
    import os as _os
    blocks_seen = []
    real = BB._bank_worker

    def spy(task):
        blocks_seen.append(task[-1])
        return real(task)
    monkeypatch.setattr(BB, "_bank_worker", spy)
    logs = []
    out = BB.encode_banks("gr", "img", jobs, [], None, lambda m, lv="info": logs.append(m))
    assert len(out) == 5 and set(blocks_seen) == {0}
    assert any("2 at a time, not 4" in m for m in logs)
    _os.environ.pop("PAD_STERN_BLOCK_WORKERS", None)
    # room for 3: one at a time, in the app, as on a small computer before
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + 3 * per)
    seen.clear()
    out = BB.encode_banks("gr", "img", jobs, [], None, lambda *a, **k: None)
    assert len(out) == 5 and [c for c, _r in seen] == [1, 2, 3, 4, 5]


def test_a_page_file_counts_what_it_can_still_grow_by():
    from collections import namedtuple
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    gb = 1 << 30
    Du = namedtuple("Du", "total used free")

    def disk(free, total=2000 * gb):
        return lambda d: Du(total, total - free, free)
    ram = 64 * gb
    # system-managed: up to three times the RAM, as the drive's free space allows
    assert P._page_file_growth(ram, 19 * gb, [("C:", None)], disk(500 * gb)) == 192 * gb - 19 * gb
    assert P._page_file_growth(ram, 19 * gb, [("C:", None)], disk(29 * gb)) == 27 * gb
    assert P._page_file_growth(ram, 19 * gb, [("C:", None)], disk(1 * gb)) == 0
    # ... and at most an eighth of the drive
    assert P._page_file_growth(ram, 0, [("C:", None)], disk(500 * gb, total=800 * gb)) == 100 * gb
    # a page file of a fixed size, or none, does not grow
    assert P._page_file_growth(ram, 16 * gb, [("C:", 16 * gb)], disk(500 * gb)) == 0
    assert P._page_file_growth(ram, 0, [], disk(500 * gb)) == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows' page files")
def test_windows_names_its_page_files():
    from pinball_decryptor.plugins.stern.spike2 import parallel as P
    for drive, mx in P._page_file_entries():
        assert len(drive) == 2 and drive[1] == ":" and (mx is None or mx >= 0)


def test_a_bank_whose_worker_runs_out_of_memory_is_encoded_again_on_its_own(monkeypatch):
    """PAD-777: three Iron Maiden bank workers, each holding a 2.1 GB image.bin, ran a
    user's PC out of memory (UC_ERR_NOMEM) and the Write failed.  Such a bank is encoded
    again in the Write's own process once the workers have gone; the others stand."""
    import threading
    BB, jobs, seen = _bank_stub(monkeypatch)
    real = BB.encode_and_verify

    def short(gr, img, job, *a, **k):
        if job.cat == 3 and threading.current_thread() is not threading.main_thread():
            raise RuntimeError("No memory available or memory not present (UC_ERR_NOMEM)")
        return real(gr, img, job, *a, **k)
    monkeypatch.setattr(BB, "encode_and_verify", short)
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "4")
    logs = []
    out = BB.encode_banks("gr", "img", jobs, [], None, lambda m, lv="info": logs.append(m))
    assert [r[0][0]["host"] for r in out] == [1, 2, 3, 4, 5]
    assert [c for c, _r in seen].count(3) == 1                  # once, on its own
    assert any("its worker ran out of memory" in m for m in logs)
    assert any("encoded again on its own" in m for m in logs)


def test_a_bank_that_runs_out_of_memory_alone_too_says_so_in_words(monkeypatch):
    BB, jobs, _seen = _bank_stub(monkeypatch)

    def short(gr, img, job, *a, **k):
        raise RuntimeError("No memory available or memory not present (UC_ERR_NOMEM)")
    monkeypatch.setattr(BB, "encode_and_verify", short)
    monkeypatch.setenv(BB.BANK_WORKERS_ENV, "1")
    with pytest.raises(RuntimeError, match=r"ran out of memory encoding the sound banks, "
                                           r"even one at a time: .*C: drive"):
        BB.encode_banks("gr", "img", jobs, [], None, lambda *a, **k: None)
