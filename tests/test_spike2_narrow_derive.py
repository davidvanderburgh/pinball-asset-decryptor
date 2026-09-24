"""The params derive under NARROW hooks gives the rows the global hook gave.

The derive used to run under one global per-instruction Python code hook: about
101 million callbacks on a Godzilla derive, 119 of its 155 s under a profiler.
A generic build now runs it under address-filtered hooks (the import sentinels,
the PLT table, the derive's own handler addresses), the way the decode already
ran.  Extract and Write use this derive for every Stern Spike 2 card, so the
rows (every key: geometry, codec fields, the raw codec object, the container
key) and the consumed-read map must not move by a byte.

Fast tests pin the hook bookkeeping on a real unicorn with a few instructions;
the card-gated ones (``slow``) compare the two derives on real cards and skip
when the card images are not on this machine.
"""
import os
import struct
import tempfile

import pytest

pytest.importorskip("unicorn")

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc  # noqa: E402
from unicorn.arm_const import UC_ARM_REG_R0  # noqa: E402

from pinball_decryptor.plugins.stern.spike2 import emulator as EM  # noqa: E402

NOP = struct.pack("<I", 0xE1A00000)          # mov r0, r0
CODE = 0x1000


# --------------------------------------------------------------------------
# fast: hook bookkeeping on a real unicorn
# --------------------------------------------------------------------------
def _stub(n=16):
    """A Spike2Emu with only what the hook bookkeeping touches, over ``n`` NOPs at
    :data:`CODE`, on the global hook as ``__init__`` leaves a real one."""
    emu = EM.Spike2Emu.__new__(EM.Spike2Emu)
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    mu.mem_map(CODE, 0x1000)
    mu.mem_write(CODE, NOP * n)
    emu.mu = mu
    emu.imports = {}
    emu.PLT = {}
    emu._atomic_pcs = set()
    emu.extra = EM._ExtraHooks()
    emu._extra_handles = {}
    emu._watchdog = None
    emu._generic = True
    emu._global_hook = mu.hook_add(UC_HOOK_CODE, emu._global_code)
    emu._narrow = False
    return emu


def _run(emu, n=16):
    emu.mu.emu_start(CODE, CODE + 4 * n)


def _counter(hits, name):
    def fn(_eng):
        hits.append(name)
    return fn


def test_extra_hooks_watch_only_while_set():
    seen = []
    d = EM._ExtraHooks()
    d[1] = "a"
    d.watch = seen.append
    d[2] = "b"
    d.watch = None
    d[3] = "c"
    assert seen == [2] and dict(d) == {1: "a", 2: "b", 3: "c"}


def test_narrow_derive_is_for_generic_builds_only(monkeypatch):
    emu = _stub()
    monkeypatch.delenv(EM.DERIVE_HOOKS_ENV, raising=False)
    assert emu.narrow_derive()
    monkeypatch.setenv(EM.DERIVE_HOOKS_ENV, "global")
    assert not emu.narrow_derive()
    monkeypatch.delenv(EM.DERIVE_HOOKS_ENV)
    emu._generic = False                      # the validated TMNT 1.58 path
    assert not emu.narrow_derive()


def test_narrow_hooks_fire_every_handler_once_and_are_put_back():
    emu = _stub()
    hits = []
    emu.extra[CODE + 8] = _counter(hits, "before")      # set before the derive
    state = emu._narrow_derive_begin([CODE + 12, None])
    assert emu._global_hook is None and emu._narrow
    emu.extra[CODE + 12] = _counter(hits, "own")         # a derive address
    emu.extra[CODE + 16] = _counter(hits, "assigned")    # plain assignment mid-derive
    _run(emu)
    assert hits == ["before", "own", "assigned"]
    emu.extra.pop(CODE + 12)
    emu.extra.pop(CODE + 16)
    emu._narrow_derive_end(state)
    assert emu._global_hook is not None and not emu._narrow
    assert emu.extra.watch is None
    hits.clear()
    _run(emu)
    # the global hook is back (it serves "before"), nothing fires twice, and the
    # popped handlers' narrow hooks went with the derive
    assert hits == ["before"]


def test_a_narrow_emulator_stays_narrow_and_keeps_its_handlers():
    emu = _stub()
    emu._switch_to_narrow_hooks()              # a decode was set up first
    hits = []
    state = emu._narrow_derive_begin([])
    emu.extra[CODE + 4] = _counter(hits, "kept")
    emu._narrow_derive_end(state)
    assert emu._narrow and emu._global_hook is None
    _run(emu)
    assert hits == ["kept"]                    # still hooked, as add_hook would


def test_watchdog_block_hook_counts_and_takes_itself_out():
    emu = _stub(64)
    emu._narrow_derive_begin([])
    counted = []

    def wd(n=1):
        counted.append(n)
    emu._watchdog = wd
    box = emu._watchdog_block_hook()
    _run(emu, 64)
    assert sum(counted) >= 1 and box.get("hh") is not None
    emu._watchdog = None
    _run(emu, 64)                              # the first block sees None and leaves
    assert "hh" not in box
    n = len(counted)
    _run(emu, 64)
    assert len(counted) == n


def _failing(exc, imgsize=100):
    """A narrow-derive emulator whose derive raises *exc*; the hook swap is
    stubbed (the bookkeeping itself is pinned above)."""
    emu = EM.Spike2Emu.__new__(EM.Spike2Emu)
    emu._generic = True
    emu.imgsize = imgsize
    emu.MASTERDIR_MALLOC = emu.BANDLOOP = emu.BANDOBJ = emu.FIND_BL = 0
    emu.COUNTREG = None
    emu.CHAIN_STUBS = ()
    ended = []
    emu._narrow_derive_begin = lambda addrs: "state"
    emu._narrow_derive_end = ended.append

    def derive(progress, after_step):
        raise exc
    emu._derive_params = derive
    return emu, ended


def test_a_failed_narrow_derive_names_the_way_back(monkeypatch):
    monkeypatch.delenv(EM.DERIVE_HOOKS_ENV, raising=False)
    emu, ended = _failing(RuntimeError("Spike 2 params: no band-build"))
    with pytest.raises(RuntimeError) as got:
        emu.derive_params()
    assert "no band-build" in str(got.value) and EM.DERIVE_HOOKS_ENV + "=global" in str(got.value)
    assert ended == ["state"], "the hooks are put back on the way out"


def test_a_callers_own_error_and_a_too_big_bank_pass_unchanged(monkeypatch):
    monkeypatch.delenv(EM.DERIVE_HOOKS_ENV, raising=False)

    class Own(RuntimeError):
        pass
    for exc, size in ((Own("mine"), 100), (RuntimeError("too big"), EM.MAX_IMAGE_BYTES + 1)):
        emu, ended = _failing(exc, size)
        with pytest.raises(RuntimeError) as got:
            emu.derive_params()
        assert got.value is exc and ended == ["state"]


def test_static_analysis_cache_is_safe_across_threads(monkeypatch):
    """Emulators for different programs made at the same moment (an Extract
    beside a build) never trip over each other's cache eviction."""
    import threading
    monkeypatch.setattr(EM, "_STATIC", {})
    monkeypatch.setattr(EM, "_build_supported_raw", lambda raw: True)
    errors = []
    start = threading.Barrier(8)

    def make(i):
        try:
            start.wait()
            for j in range(40):
                EM._static_analysis(bytes([i, j]) * 8, [])
        except Exception as e:                   # noqa: BLE001 - reported below
            errors.append(e)
    threads = [threading.Thread(target=make, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(EM._STATIC) <= EM._STATIC_KEEP


def _reads_stub():
    emu = EM.Spike2Emu.__new__(EM.Spike2Emu)
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    mu.mem_map(CODE, 0x1000)
    mu.mem_map(EM.DESC_BASE, 0x1000)
    # ldr r1,[r0] ; ldrb r2,[r0,#9] ; ldrh r3,[r0,#20] ; ldr r4,[r0,#0xffc]
    mu.mem_write(CODE, struct.pack("<4I", 0xE5901000, 0xE5D02009, 0xE1D031B4, 0xE5904FFC))
    mu.reg_write(UC_ARM_REG_R0, EM.DESC_BASE)
    emu.mu = mu
    emu.imgsize = 0xffe                         # the last read runs 2 bytes past the end
    return emu


@pytest.mark.parametrize("raw", [True, False])
def test_consumed_hook_records_every_byte_read(raw, monkeypatch):
    from pinball_decryptor.plugins.stern import engine
    emu = _reads_stub()
    if not raw:
        def refuse(*a, **k):
            raise AttributeError("no private API here")
        monkeypatch.setattr(EM, "_raw_read_hook", refuse)
    reads, hh = engine._install_consumed_hook(emu)
    emu.mu.emu_start(CODE, CODE + 16)
    assert reads == {0, 1, 2, 3, 9, 20, 21, 0xffc, 0xffd}
    emu.mu.hook_del(hh)                        # the handle is one hook_del takes
    reads.clear()
    emu.mu.emu_start(CODE, CODE + 16)
    assert reads == set()


def test_patch_card_is_seen_by_the_guest_and_never_written(tmp_path):
    img = tmp_path / "image.bin"
    body = bytes(range(256)) * (EM.PAGE * 2 // 256) + b"\x77" * 100   # a partial tail page
    img.write_bytes(body)
    emu = EM.Spike2Emu.__new__(EM.Spike2Emu)
    emu.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    emu._imgf = open(str(img), "rb")
    import mmap
    emu.mm = mmap.mmap(emu._imgf.fileno(), 0, access=mmap.ACCESS_READ)
    emu.imgsize = emu.mm.size()
    emu.log = []
    emu.mapped_pages = set()
    emu._cardf = emu._cardbuf = None
    emu._card_lo = emu._card_hi = 0
    emu._map_card_window()
    try:
        emu.patch_card(10, b"\xaa\xbb")
        emu.patch_card(len(body) - 3, b"\x01\x02\x03")      # in the paged tail
        assert bytes(emu.mu.mem_read(EM.DESC_BASE + 8, 6)) == bytes([8, 9, 0xaa, 0xbb, 12, 13])
        assert bytes(emu.mu.mem_read(EM.DESC_BASE + len(body) - 4, 4)) == b"\x77\x01\x02\x03"
        with pytest.raises(ValueError):
            emu.patch_card(len(body) - 1, b"\x00\x00")       # would grow the file
    finally:
        emu.close()
    assert img.read_bytes() == body


# --------------------------------------------------------------------------
# card-gated: the two derives on real cards
# --------------------------------------------------------------------------
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_IMG_DIRS = [d for d in (os.environ.get("PAD_SPIKE2_IMG_DIR"),
                         os.path.join(REPO, "images", "Stern", "spike2"),
                         r"D:\Pinball\images\Stern\spike2",
                         "/mnt/d/Pinball/images/Stern/spike2") if d]
#: Three rule systems and three catalog sizes: 2534, 933 and 8175 sounds; a
#: crule_manager build (TMNT LE 1.59) and the build whose boot memcpy goes
#: through a PLT thunk (Led Zeppelin LE 1.22).
CARDS = {
    "godzilla_le_116": "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw",
    "beatles_129": "beatles-1_29_0.Release.8G.sdcard.raw",
    "deadpool_pro_116": "deadpool_pro-1_16_0.Release.8G.sdcard.raw",
    "turtles_le_159": "turtles_le-1_59_0.Release.8G.sdcard.raw",
    "led_zeppelin_le_122": "led_zeppelin_le-1_22_0.Release.8G.sdcard.raw",
}
#: Records compared under the old (slow) hook; the new derive runs them all.
FIRST = 300


def _card_path(title):
    for d in _IMG_DIRS:
        p = os.path.join(d, CARDS[title])
        if os.path.isfile(p):
            return p
    return None


def _inputs(title):
    """The card's game_real + image.bin, extracted once into the temp dir (the
    same cache tests/test_spike2_masterdir.py and test_stern_audio_tail.py use)."""
    from pinball_decryptor.plugins.stern import engine as E
    card = _card_path(title)
    if card is None:
        pytest.skip("card image %s is not on this machine" % CARDS[title])
    work = os.path.join(tempfile.gettempdir(), "pad_stern_tail_" + title)
    gr = os.path.join(work, "game_real")
    img = os.path.join(work, "image.bin")
    if not (os.path.exists(gr) and os.path.exists(img) and os.path.getsize(img) > 0):
        os.makedirs(work, exist_ok=True)
        parts = E._linux_partitions(card)
        with open(card, "rb") as disk_f:
            E._extract_inputs(disk_f, parts, work, lambda *a, **k: None)
    return gr, img


@pytest.fixture(autouse=True)
def _no_faulthandler():
    """unicorn services guest memory through the host's fault machinery, which
    pytest's faulthandler traps first on Windows (see test_spike2_masterdir)."""
    import faulthandler
    was = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        yield
    finally:
        if was:
            faulthandler.enable()


class _Enough(Exception):
    pass


def _derive(gr, img, hooks, first=None, consumed=False):
    """``(rows, record count, consumed offsets or None)`` of one derive under
    *hooks* ("narrow" or "global"), stopped after *first* records if given."""
    from pinball_decryptor.plugins.stern import engine as E
    old = os.environ.get(EM.DERIVE_HOOKS_ENV)
    if hooks == "global":
        os.environ[EM.DERIVE_HOOKS_ENV] = "global"
    else:
        os.environ.pop(EM.DERIVE_HOOKS_ENV, None)
    emu = EM.Spike2Emu(gr, img)
    try:
        if not emu.audio_supported:
            pytest.skip("audio decode is not supported for this build")
        assert emu.narrow_derive() == (hooks == "narrow")
        emu.boot()
        reads, hh = E._install_consumed_hook(emu) if consumed else (None, None)
        rows, total = [], []

        def after(idx, row, redo):
            rows.append(dict(row))
            if first is not None and len(rows) >= first:
                raise _Enough()

        try:
            emu.derive_params(progress=lambda d, t, m: total.append(t), after_step=after)
        except _Enough:
            pass
        if hh is not None:
            emu.mu.hook_del(hh)
        assert emu._narrow is False and emu._global_hook is not None
        return rows, max(total), reads
    finally:
        emu.close()
        if old is None:
            os.environ.pop(EM.DERIVE_HOOKS_ENV, None)
        else:
            os.environ[EM.DERIVE_HOOKS_ENV] = old


@pytest.mark.slow
@pytest.mark.parametrize("title", sorted(CARDS))
def test_narrow_derive_rows_match_the_global_hook(title):
    gr, img = _inputs(title)
    new, n_new, _ = _derive(gr, img, "narrow")
    old, n_old, _ = _derive(gr, img, "global", first=FIRST)
    assert n_new == n_old and len(new) == n_new, "the chain walked another catalog"
    assert len(old) == FIRST
    for a, b in zip(new, old):
        assert a == b, "%s: record %d differs in %s" % (
            title, a.get("idx"), sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k)))


@pytest.mark.slow
def test_narrow_derive_consumed_map_matches_the_global_hook():
    title = "godzilla_le_116"
    gr, img = _inputs(title)
    _r1, _n1, new = _derive(gr, img, "narrow", first=FIRST, consumed=True)
    _r2, _n2, old = _derive(gr, img, "global", first=FIRST, consumed=True)
    assert new and new == old


@pytest.mark.slow
def test_integrity_check_in_the_emulators_view_matches_a_patched_copy(tmp_path, monkeypatch):
    """The integrity derive laid over the emulator's copy-on-write view reads
    what it read off a patched copy of image.bin, and the file is untouched."""
    from pinball_decryptor.plugins.stern import engine as E
    gr, img = _inputs("beatles_129")
    stock, _n, _ = _derive(gr, img, "narrow")
    # two whole bodies mid-bank: their windows feed every later record's params
    patches = {}
    for p in stock[len(stock) // 2:len(stock) // 2 + 2]:
        n = min(2 * int(p["length"]), 1 << 20)
        patches[p["body_off"]] = bytes((i * 37 + 11) & 0xff for i in range(n))
    before = os.path.getmtime(img), os.path.getsize(img)
    monkeypatch.delenv(E.VERIFY_COPY_ENV, raising=False)
    in_view = E._integrity_rows(gr, img, patches, str(tmp_path))
    monkeypatch.setenv(E.VERIFY_COPY_ENV, "1")
    copied = E._integrity_rows(gr, img, patches, str(tmp_path))
    assert in_view == copied
    assert (os.path.getmtime(img), os.path.getsize(img)) == before
    assert not os.listdir(str(tmp_path)), "the copy is removed"
    assert in_view != stock, "the patches were not seen by the firmware at all"
