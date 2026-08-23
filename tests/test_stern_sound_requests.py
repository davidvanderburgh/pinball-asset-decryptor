"""Spike 2 sound-REQUEST tally (plugins.stern.spike2.sound_requests).

The request count is the third sound number in Image Info, and the only one
that is not a plaintext word in the image.bin container header: it comes from
the game ELF's own request table.  A tester (PAD-81/PAD-82) reported the two
figures his machines print -- Venom LE 1.07 = 1869, Deadpool LE 1.15 = 984 --
and Venom is the exact number the card-gated test below re-derives.

The synthetic ELF here carries the same shapes the RE found on real firmware:
a ``{data_va, count, elem_size}`` registry triple pointing at 20-byte records,
each holding a pointer into a block of NUL-terminated u32 sid lists that
follows the array and is indexed from its END.
"""
import os
import struct

import pytest

from pinball_decryptor.plugins.stern.spike2.sound_requests import (
    count_sound_requests, locate_sound_requests)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.environ.get("PAD_SPIKE2_IMG_DIR",
                         os.path.join(REPO, "images", "Stern", "spike2"))

BASE = 0x10000
REC = 20


def make_elf(lists, rec_size=REC, field=2, decoy_lists=None):
    """``lists`` = ``[[sid, ...], ...]`` in REQUEST order -> ELF bytes.

    Laid out the way the firmware does it: the record array first, then the
    sid-list block, with record ``i`` pointing at ``lists[i]`` -- which lands
    the LAST record on the FIRST list, i.e. right where the array ends.

    *decoy_lists* builds a second, smaller table of the same shape ahead of
    the real one, standing in for the look-alikes the same code generator
    emits (menu routing, light shows) that the real scan has to reject."""
    hdr_len = 52 + 32

    def va(off):
        return BASE + off

    def table(off, entries):
        """Serialise ``(records, block)`` for a table starting at *off*."""
        arr_len = len(entries) * rec_size
        block, at = bytearray(), off + arr_len
        starts = []
        for lst in reversed(entries):          # block order = reverse of ids
            starts.append(at + len(block))
            block += b"".join(struct.pack("<I", s) for s in lst)
            block += b"\x00" * 4               # NUL terminator
        starts.reverse()
        recs = bytearray()
        for i, _lst in enumerate(entries):
            r = bytearray(rec_size)
            struct.pack_into("<I", r, field * 4, va(starts[i]))
            recs += r
        return bytes(recs), bytes(block)

    payload = bytearray()
    registry = []                              # (data_off, count) to emit
    for entries in ([decoy_lists] if decoy_lists else []) + [lists]:
        off = hdr_len + len(payload)
        recs, block = table(off, entries)
        payload += recs + block
        registry.append((off, len(entries)))
    reg_off = hdr_len + len(payload)
    for off, n in registry:
        payload += struct.pack("<III", va(off), n, rec_size)
    total = hdr_len + len(payload)

    eh = bytearray(52)
    eh[0:4] = b"\x7fELF"
    eh[4], eh[5], eh[6] = 1, 1, 1              # 32-bit, LE, version 1
    struct.pack_into("<H", eh, 0x10, 2)        # e_type EXEC
    struct.pack_into("<H", eh, 0x12, 40)       # e_machine ARM
    struct.pack_into("<I", eh, 0x14, 1)
    struct.pack_into("<I", eh, 0x1C, 52)       # e_phoff
    struct.pack_into("<H", eh, 0x28, 52)
    struct.pack_into("<H", eh, 0x2A, 32)
    struct.pack_into("<H", eh, 0x2C, 1)
    ph = struct.pack("<IIIIIIII", 1, 0, BASE, BASE, total, total, 5, 0x1000)
    return bytes(eh + ph + payload), reg_off


def _lists(n, frags):
    """*n* request chains whose sids span 0..frags-1 (a real table addresses
    essentially the whole fragment space)."""
    out = [[(i * 7) % frags] for i in range(n - 1)]
    out[0] = [frags - 1, 3, 9]                 # a multi-fragment chain
    out.append([])                             # the trailing empty, id 0
    return out


def test_counts_the_request_table():
    fw, _reg = make_elf(_lists(200, 512))
    assert count_sound_requests(fw, 512) == 200


def test_reports_the_table_offset():
    fw, _reg = make_elf(_lists(120, 300))
    count, off = locate_sound_requests(fw, 300)
    assert count == 120
    # The record array is the first thing after the ELF/program headers.
    assert off == 52 + 32


def test_prefers_the_table_that_addresses_real_fragments():
    """The bigger table wins only if its sids are fragments this card has --
    a decoy twice the size whose ids run past the fragment count is refused
    (that is how the light-show / menu tables are told apart from requests)."""
    decoy = [[40000 + i] for i in range(400)] + [[]]
    fw, _reg = make_elf(_lists(150, 900), decoy_lists=decoy)
    assert count_sound_requests(fw, 900) == 150


def test_refuses_a_table_that_barely_touches_the_fragments():
    """Every sid in range but only the low corner of it used: that is not the
    request table, it is one of the small twins, so no number is reported."""
    stunted = [[i % 20] for i in range(300)] + [[]]
    fw, _reg = make_elf(stunted)
    assert count_sound_requests(fw, 4000) is None


def test_sids_may_carry_a_category_in_the_high_half():
    """Multi-category titles (Rush, Metallica, Deadpool) tag the sid with its
    category above bit 16; the fragment index is the LOW half."""
    tagged = [[(0x0B << 16) | ((i * 5) % 800)] for i in range(160)]
    tagged[0] = [(0x2D << 16) | 799]
    tagged.append([])
    fw, _reg = make_elf(tagged)
    assert count_sound_requests(fw, 800) == 161


@pytest.mark.parametrize("fw,frags", [
    (b"", 512),                                  # no ELF read
    (b"\x7fELF" + b"\x00" * 200, 512),           # unparseable
])
def test_degrades_rather_than_guessing(fw, frags):
    assert count_sound_requests(fw, frags) is None


def test_needs_the_fragment_ceiling():
    """Without the container header's fragment count there is nothing to
    judge the candidates against, so the probe declines."""
    fw, _reg = make_elf(_lists(200, 512))
    assert count_sound_requests(fw, None) is None
    assert count_sound_requests(fw, 0) is None


def test_wrong_pointer_field_is_not_assumed():
    """Builds park the sid-list pointer at a different word inside the
    record; the scan finds it rather than hard-coding field 2."""
    fw, _reg = make_elf(_lists(90, 400), field=4)
    assert count_sound_requests(fw, 400) == 90


# ---------------------------------------------------------------------------
# Card-gated: the tester's own number, off the real Venom card.
# ---------------------------------------------------------------------------

VENOM = os.path.join(IMG_DIR, "venom_le-1_07_0.Release.8G.sdcard.raw")


@pytest.mark.skipif(not os.path.isfile(VENOM),
                    reason="needs the Venom LE 1.07 vendor card image")
def test_venom_le_107_matches_the_machine():
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.info import (_game_elf_bytes,
                                                      _walk_partition,
                                                      container_counts)
    with CardImage(VENOM) as card:
        parts = sorted((p for p in card.partitions() if p.browsable),
                       key=lambda p: p.size, reverse=True)
        reader = found = None
        for p in parts:
            r = card.reader(p.index)
            f = _walk_partition(r)
            if reader is None:
                reader, found = r, f
            if f["sidx_node"] is not None:
                reader, found = r, f
                break
        fragments, _sounds = container_counts(
            reader.peek(found["image_bin"], 0x68))
        fw = _game_elf_bytes(reader, found)
    assert fragments == 4067
    assert count_sound_requests(fw, fragments) == 1869
