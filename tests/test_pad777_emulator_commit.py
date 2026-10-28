"""PAD-777: the emulator maps card files read-only (no commit charge) until something
writes one, then the whole window becomes a copy-on-write view; the heap is mapped as it
is handed out."""

import struct

import pytest
from unicorn import UC_ARCH_ARM, UC_MODE_ARM, UC_PROT_EXEC, UC_PROT_READ
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3

from pinball_decryptor.plugins.stern.spike2 import emulator as EM
from pinball_decryptor.plugins.stern.spike2.window import PAGE, WindowUc

BASE = 0x70000000
CODE = 0x10000


@pytest.fixture
def card(tmp_path):
    path = tmp_path / "image.bin"
    path.write_bytes(bytes(range(256)) * (16 * PAGE // 256))
    f = open(str(path), "rb")
    mu = WindowUc(UC_ARCH_ARM, UC_MODE_ARM)
    mu.map_window(BASE, 16 * PAGE, f, UC_PROT_READ | UC_PROT_EXEC)
    mu.mem_map(CODE, PAGE)
    yield mu, path
    mu.unmap_window(BASE)
    f.close()


def _run(mu, *words, thumb=False):
    if thumb:
        mu.mem_write(CODE, struct.pack("<%dH" % len(words), *words))
        mu.emu_start(CODE | 1, CODE + 2 * len(words))
    else:
        mu.mem_write(CODE, struct.pack("<%dI" % len(words), *words))
        mu.emu_start(CODE, CODE + 4 * len(words))


def _regions(mu):
    return [(a, b) for a, b, _p in mu.mem_regions() if a >= BASE]


def test_the_guest_reads_the_file_and_nothing_is_copied(card):
    mu, _path = card
    mu.reg_write(UC_ARM_REG_R0, BASE + 5 * PAGE + 8)
    _run(mu, 0xE5902000)                                   # ldr r2, [r0]
    assert mu.reg_read(UC_ARM_REG_R2) == 0x0B0A0908 and mu.copied_windows == 0


def test_a_guest_store_copies_the_window_once_and_runs_once(card):
    mu, path = card
    a = BASE + 5 * PAGE + 8
    mu.reg_write(UC_ARM_REG_R0, a)
    mu.reg_write(UC_ARM_REG_R1, 0xDEADBEEF)
    mu.reg_write(UC_ARM_REG_R3, 7)
    # str r1,[r0] ; ldr r2,[r0,#4] ; add r3,r3,#1
    _run(mu, 0xE5801000, 0xE5902004, 0xE2833001)
    assert struct.unpack("<I", mu.mem_read(a, 4))[0] == 0xDEADBEEF
    assert mu.reg_read(UC_ARM_REG_R2) == 0x0F0E0D0C and mu.reg_read(UC_ARM_REG_R3) == 8
    assert mu.copied_windows == 1
    assert _regions(mu) == [(BASE, BASE + 16 * PAGE - 1)]  # still one piece
    assert path.read_bytes()[5 * PAGE + 8:5 * PAGE + 12] == bytes([8, 9, 10, 11])
    assert bytes(mu.mem_read(BASE + 4 * PAGE + 0xFFC, 8)) == bytes([252, 253, 254, 255, 0, 1, 2, 3])


def test_a_store_multiple_across_two_pages_and_a_thumb_store(card):
    mu, _path = card
    mu.reg_write(UC_ARM_REG_R0, BASE + 6 * PAGE - 4)
    mu.reg_write(UC_ARM_REG_R1, 0x11111111)
    mu.reg_write(UC_ARM_REG_R2, 0x22222222)
    _run(mu, 0xE8A00006)                                   # stmia r0!, {r1, r2}
    assert bytes(mu.mem_read(BASE + 6 * PAGE - 4, 8)) == b"\x11" * 4 + b"\x22" * 4
    assert mu.reg_read(UC_ARM_REG_R0) == BASE + 6 * PAGE + 4 and mu.copied_windows == 1
    mu.reg_write(UC_ARM_REG_R0, BASE + 3 * PAGE + 0x20)
    mu.reg_write(UC_ARM_REG_R1, 0xCAFEF00D)
    mu.reg_write(UC_ARM_REG_R3, 0)
    _run(mu, 0x3301, 0x6001, 0x3301, thumb=True)           # adds r3,#1 ; str r1,[r0] ; adds
    assert struct.unpack("<I", mu.mem_read(BASE + 3 * PAGE + 0x20, 4))[0] == 0xCAFEF00D
    assert mu.reg_read(UC_ARM_REG_R3) == 2 and mu.copied_windows == 1


def test_a_big_host_write_copies_the_window_in_one_piece(card):
    """A bank encode writes a whole sound body (56 MB) into the bank's window at once,
    and the Write's integrity check lays hundreds of bodies over image.bin: the window is
    never split (a split window ran Iron Maiden's derive 2.7x slower)."""
    mu, path = card
    mu.mem_write(BASE + PAGE + 16, b"\x5A" * (12 * PAGE))
    mu.mem_write(BASE + 15 * PAGE, b"\xA5" * 8)
    assert mu.copied_windows == 1 and _regions(mu) == [(BASE, BASE + 16 * PAGE - 1)]
    assert bytes(mu.mem_read(BASE + PAGE, 16)) == bytes(range(16))
    assert bytes(mu.mem_read(BASE + 13 * PAGE + 16, 4)) == bytes([16, 17, 18, 19])
    mu.reg_write(UC_ARM_REG_R0, BASE + 2 * PAGE)
    _run(mu, 0xE1D020B0)                                   # ldrh r2, [r0]
    assert mu.reg_read(UC_ARM_REG_R2) == 0x5A5A
    assert path.read_bytes()[PAGE + 16:PAGE + 20] == bytes([16, 17, 18, 19])


def test_a_window_mapped_to_be_written_is_copy_on_write_from_the_start(tmp_path):
    """The Write's integrity check and a bank's encode write their windows: those are
    mapped copy-on-write at once (a window swapped later ran the derive 2.5x slower)."""
    path = tmp_path / "image.bin"
    path.write_bytes(bytes(range(256)) * (4 * PAGE // 256))
    with open(str(path), "rb") as f:
        mu = WindowUc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.map_window(BASE, 4 * PAGE, f, UC_PROT_READ | UC_PROT_EXEC, copy=True)
        mu.mem_write(BASE + 8, b"\x01\x02")
        assert bytes(mu.mem_read(BASE + 6, 4)) == b"\x06\x07\x01\x02"
        assert mu.copied_windows == 0 and _regions(mu) == [(BASE, BASE + 4 * PAGE - 1)]
        mu.unmap_window(BASE)
    assert path.read_bytes()[8:10] == b"\x08\x09"


class _HeapProbe(object):
    """Spike2Emu's heap with a stand-in engine that records its maps."""
    HEAP, HEAPSZ = EM.Spike2Emu.HEAP, EM.Spike2Emu.HEAPSZ
    alloc = EM.Spike2Emu.alloc
    _map_heap = EM.Spike2Emu._map_heap

    def __init__(self):
        probe = self

        class Mu(object):
            def mem_map(self, addr, size):
                probe.maps.append((addr, size))
        self.maps = []
        self.mu = Mu()
        self._heap_mapped = self.HEAP
        self._map_heap(self.HEAP + 0x100000 + EM.HEAP_STEP)
        self.heap = self.HEAP + 0x100000


def test_the_heap_is_mapped_as_it_is_handed_out_and_never_past_its_window():
    h = _HeapProbe()
    assert h.maps == [(h.HEAP, 2 * EM.HEAP_STEP)]          # 32 MB, not 512
    p = h.alloc(0x1000)
    assert p == h.HEAP + 0x100000 and len(h.maps) == 1
    h.alloc(40 << 20)                                      # past the mapped part
    assert h.maps[-1][0] == h.HEAP + 2 * EM.HEAP_STEP and h._heap_mapped >= h.heap
    h.alloc(800 << 20)                                     # Led Zeppelin 1.21's ask
    assert h._heap_mapped == h.HEAP + h.HEAPSZ
    assert sum(s for _a, s in h.maps) == h.HEAPSZ
