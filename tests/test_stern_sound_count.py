"""The sound engine's own valid/failed record count, and the NOP that keeps
a grown sound bank from tripping it (valpatch, item 104).

The Tech Alerts line ``GAME VALIDATION ERROR - #4 549:2 UPDATE SD CARD`` on a
Led Zeppelin card with two grown sounds is that count: the boot-time band
build compares each record's window hash with a table in the ELF that has
one word per STOCK record, and counts the appended copies as failed.  The
validator bypass never reached it because the validator only reads the two
counters back.
"""

import struct

import pytest

from pinball_decryptor.plugins.stern import valpatch

NOP = 0xE1A00000
NE, EQ = 0x1, 0x0


def _ldr(cond, rx, ry, off, up):
    return (cond << 28) | 0x05100000 | (0x00800000 if up else 0) | (ry << 16) | (rx << 12) | off


def _str(cond, rx, ry, off, up):
    return (cond << 28) | 0x05000000 | (0x00800000 if up else 0) | (ry << 16) | (rx << 12) | off


def _add1(cond, rx):
    return (cond << 28) | 0x02800001 | (rx << 16) | (rx << 12)


def _cmp(ra, rb):
    return 0xE1500000 | (ra << 16) | rb


def _block(first=NE, rx=1, ry=3, failed=0x978, up=True, cmp_gap=0):
    """The count block as the compilers emit it: cmp, an optional plain load
    of the base between, then ldr/ldr/add/add/str/str with *first* the
    condition of the FAILED half."""
    second = EQ if first == NE else NE
    valid = failed - 4 if up else failed + 4
    words = [_cmp(8, 1)]
    words += [0xE59D317C] * cmp_gap                      # ldr r3, [sp, #0x17c]
    words += [_ldr(first, rx, ry, failed, up), _ldr(second, rx, ry, valid, up),
              _add1(first, rx), _add1(second, rx),
              _str(first, rx, ry, failed, up), _str(second, rx, ry, valid, up)]
    return words


def _elf(blocks):
    """NOP-padded bytes with each block placed at a 4-aligned offset."""
    words = [NOP] * 64
    for at, blk in blocks:
        words[at:at + len(blk)] = blk
    return struct.pack("<%dI" % len(words), *words)


def test_the_failed_store_is_found_in_the_led_zeppelin_shape():
    elf = _elf([(10, _block(first=NE, failed=0x374, up=False))])
    assert valpatch.find_sound_count_failed_store(elf) == (10 + 1 + 4) * 4


def test_the_failed_store_is_found_when_the_conditions_are_swapped():
    elf = _elf([(10, _block(first=EQ, failed=0x978, up=True))])
    # valid half first: the failed store is the LAST word of the block
    assert valpatch.find_sound_count_failed_store(elf) == (10 + 1 + 5) * 4


def test_a_load_of_the_base_may_sit_between_the_cmp_and_the_block():
    """james_bond_le 1.06 reloads the base register between the compare and
    the conditional loads."""
    elf = _elf([(10, _block(cmp_gap=1))])
    assert valpatch.find_sound_count_failed_store(elf) == (10 + 2 + 4) * 4


def test_a_block_without_a_compare_above_it_is_not_the_count():
    """Every firmware carries a second conditional counter pair (offset +0xc)
    with no cmp above it; requiring the cmp is what makes the site unique."""
    blk = _block()[1:]                                   # drop the cmp
    elf = _elf([(10, blk)])
    assert valpatch.find_sound_count_failed_store(elf) is None


def test_two_sites_are_no_answer():
    elf = _elf([(10, _block()), (30, _block(failed=0x9a0))])
    assert valpatch.find_sound_count_failed_store(elf) is None


def test_the_overlay_is_one_nop_and_locating_is_idempotent():
    elf = _elf([(10, _block())])
    ov = valpatch.sound_count_overlay(elf)
    off = (10 + 1 + 4) * 4
    assert ov == {off: valpatch._NOP}
    patched = bytearray(elf)
    patched[off:off + 4] = valpatch._NOP
    assert valpatch.find_sound_count_failed_store(bytes(patched)) == off
    assert valpatch.sound_count_overlay(bytes(patched)) == {off: valpatch._NOP}


def test_an_unlocated_count_is_a_warning_not_a_failure():
    msgs = []
    ov = valpatch.sound_count_overlay(_elf([]), lambda m, lvl="info": msgs.append((lvl, m)))
    assert ov == {}
    assert msgs and msgs[0][0] == "warning" and "#4" in msgs[0][1]


class _Reader:
    def __init__(self, elf, disk=0x100000):
        self.elf, self.disk = elf, disk

    def read_file_bytes(self, node):
        return self.elf

    def disk_ranges(self, node, off, length):
        return [(self.disk + off, length)]


def test_sound_count_writes_lands_on_the_card_and_in_the_overlay():
    elf = _elf([(10, _block())])
    writes, ov = valpatch.sound_count_writes(_Reader(elf), object())
    off = (10 + 1 + 4) * 4
    assert writes == [(0x100000 + off, valpatch._NOP)]
    assert ov == {off: valpatch._NOP}


def test_sound_count_writes_never_raises():
    class _Broken:
        def read_file_bytes(self, node):
            raise OSError("boom")
    msgs = []
    assert valpatch.sound_count_writes(_Broken(), None,
                                       lambda m, lvl="info": msgs.append(m)) == ([], {})
    assert msgs and "boom" in msgs[0]


@pytest.mark.parametrize("failed,up", [(0x978, True), (0x374, False), (0x9a0, True)])
def test_every_measured_offset_shape_is_accepted(failed, up):
    elf = _elf([(12, _block(failed=failed, up=up))])
    assert valpatch.find_sound_count_failed_store(elf) == (12 + 1 + 4) * 4
