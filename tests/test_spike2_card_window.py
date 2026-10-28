"""The card window is backed in one piece, not paged in 4 KiB at a time (fast).

Paging the card 4 KiB at a time makes every later guest memory access search an
ever-growing pile of tiny unicorn regions, so per-record derive cost is linear
in the number of mapped pages and the whole derive is QUADRATIC in catalog
size.  Measured on Deadpool Pro 1.16 (8175 sounds, 1.5 GiB image): 11.2
ms/record at record 100 rising to 54.5 by record 3000, 18.8 min for the full
derive -- against a flat 11.0 ms/record and ~1.5 min with the window mapped in
one piece, peak RSS 81 MB, and bit-identical derived params.

These run without unicorn or a card: they pin the guard conditions that decide
whether the one-piece mapping is safe to take, and the paging fallback that has
to stay correct when it isn't.
"""
import mmap

import pytest
from unicorn import UC_PROT_WRITE

from pinball_decryptor.plugins.stern.spike2 import emulator as E


class _FakeMu:
    def __init__(self, fail=False):
        self.maps = []
        self.unmaps = []
        self.fail = fail

    # PAD-777: the emulator maps the card through WindowUc (spike2.window)
    def map_window(self, lo, size, fileobj, perms, copy=False):
        if self.fail:
            raise RuntimeError("mem_map_ptr unsupported")
        assert not fileobj.closed, "the window needs the open card file"
        self.maps.append((lo, size, perms))
        self.copy = copy

    def unmap_window(self, lo):
        self.unmaps.append(lo)

    def mem_map(self, addr, size):
        raise AssertionError("paged %#x inside the card window" % addr)


class _Emu:
    """A Spike2Emu with only what _map_card_window / _ensure_page / close touch."""

    _map_card_window = E.Spike2Emu._map_card_window
    close = E.Spike2Emu.close

    def __init__(self, path, imgsize, fail=False, card_copy=False):
        self._imgf = open(path, "rb")
        self.mm = mmap.mmap(self._imgf.fileno(), 0, access=mmap.ACCESS_READ)
        self.imgsize = imgsize
        self.mu = _FakeMu(fail)
        self.log = []
        self.mapped_pages = set()
        self._cardf = self._cardbuf = None
        self._card_copy = card_copy
        self._card_lo = self._card_hi = 0


@pytest.fixture
def card(tmp_path):
    p = tmp_path / "image.bin"
    p.write_bytes(bytes(range(256)) * (E.PAGE * 4 // 256))     # 4 whole pages
    return str(p), p.stat().st_size


def test_whole_image_becomes_one_region(card):
    path, size = card
    emu = _Emu(path, size)
    emu._map_card_window()
    try:
        assert len(emu.mu.maps) == 1, "the point is ONE region, not many"
        addr, span, _perms = emu.mu.maps[0]
        assert addr == E.DESC_BASE
        assert span == size and span % E.PAGE == 0
    finally:
        emu.close()


def test_partial_tail_page_is_left_to_the_pager(tmp_path):
    """Only whole pages can be mapped; the ragged tail keeps the paging path,
    so it must not be included in the one-piece span."""
    p = tmp_path / "image.bin"
    p.write_bytes(b"\xab" * (E.PAGE * 3 + 17))
    emu = _Emu(str(p), p.stat().st_size)
    emu._map_card_window()
    try:
        _addr, span, _perms = emu.mu.maps[0]
        assert span == E.PAGE * 3
        assert emu._card_hi == E.DESC_BASE + E.PAGE * 3
    finally:
        emu.close()


@pytest.mark.parametrize("card_copy", [False, True])
def test_window_is_read_only_unless_the_emulator_writes_the_card(card, card_copy):
    """PAD-777: a read-only view commits nothing; only an emulator that will write
    the card (the Write's integrity check) asks for a copy-on-write one.  That a
    write never reaches image.bin either way is test_pad777_emulator_commit's."""
    path, size = card
    emu = _Emu(path, size, card_copy=card_copy)
    emu._map_card_window()
    try:
        _addr, _span, perms = emu.mu.maps[0]
        assert not perms & UC_PROT_WRITE
        assert emu.mu.copy is card_copy
    finally:
        emu.close()


def test_ensure_page_short_circuits_inside_the_window(card):
    path, size = card
    emu = _Emu(path, size)
    emu._map_card_window()
    try:
        inside = E.DESC_BASE + E.PAGE
        assert E.Spike2Emu._ensure_page(emu, inside) is True
        assert not emu.mapped_pages, "must not re-page what is already backed"
    finally:
        emu.close()


def test_oversized_image_keeps_the_paging_path(card, monkeypatch):
    """A card whose window would run past the 32-bit guest space must fall back
    rather than map something that cannot fit."""
    path, _size = card
    emu = _Emu(path, 0x1_0000_0000 - E.DESC_BASE + E.PAGE)
    emu._map_card_window()
    try:
        assert emu.mu.maps == []
        assert emu._card_hi == emu._card_lo == 0
    finally:
        emu.close()


def test_failure_falls_back_cleanly_and_releases_the_view(card):
    """An older unicorn (or any platform where this doesn't take) must land on
    the paging path with no half-open mmap left behind."""
    path, size = card
    emu = _Emu(path, size, fail=True)
    emu._map_card_window()
    try:
        assert emu._card_lo == emu._card_hi == 0
        assert emu._cardf is None and emu._cardbuf is None
        assert any(k == "card_map_ptr" for k, _v in emu.log)
        # the fallback must still be reachable
        assert emu._card_lo == 0
    finally:
        emu.close()


def test_close_unmaps_before_dropping_the_buffer(card):
    """Ordering matters twice over: unicorn is pointing straight at the view, and
    the exported pointer makes the view's close raise until it is dropped
    (WindowUc.unmap_window does both, in that order).  A wrong order here is a
    hard crash or a leak."""
    path, size = card
    emu = _Emu(path, size)
    emu._map_card_window()
    assert emu.mu.maps
    emu.close()
    assert emu.mu.unmaps == [E.DESC_BASE]
    assert emu._cardbuf is None and emu._cardf is None
    assert emu._card_lo == emu._card_hi == 0


def test_close_is_safe_when_the_window_was_never_mapped(card):
    path, size = card
    emu = _Emu(path, size, fail=True)
    emu._map_card_window()
    emu.close()
    assert emu.mu.unmaps == []
