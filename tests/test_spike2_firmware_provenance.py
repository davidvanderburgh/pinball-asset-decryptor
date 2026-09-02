"""A run should say whether the firmware it is running is Stern's or ours.

PAD-102 spent a day pointed at a user's *rethemed* Godzilla card on the
assumption that custom content was involved.  It was not - the stock factory
1.16 image crashed identically, to the register - and the retheme turned out to
patch only assets and strings, not code.  That mistake was cheap.  The reverse
one is not: a log from a card whose firmware PAD itself rewrote, read as though
it were stock, sends the next investigation hunting a bug in Stern's code that
we put there.

So `gameinfo.firmware_provenance()` answers it structurally, with no addresses
to go stale.  The blip-free callout patch (docs/architecture/stern.md) rewrites
the ELF's `PT_GNU_STACK` header into a third `PT_LOAD` so it can append an
executable cave page and branch into it; stock Spike 2 firmware is exactly two
`PT_LOAD`s plus a `PT_GNU_STACK`.

Both verdicts are exercised here.  Testing only the stock shape would be the
easy half and the useless one - "patched" is the answer that has to be right,
so this builds an ELF with the patch's own signature rather than trusting the
reader to be symmetrical.
"""
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

sys.path.insert(0, RIG)

PT_LOAD = 1
PT_GNU_STACK = 0x6474E551


def _elf(segments):
    """A minimal ARM ELF32 carrying exactly `segments` as [(type, vaddr, memsz,
    flags), ...].  Only the program headers are real; nothing else is read."""
    phentsize, phoff = 32, 52
    head = bytearray(52)
    head[0:4] = b"\x7fELF"
    head[4] = 1            # ELFCLASS32
    head[5] = 1            # little endian
    head[6] = 1            # EV_CURRENT
    struct.pack_into("<H", head, 16, 2)          # e_type = ET_EXEC
    struct.pack_into("<H", head, 18, 40)         # e_machine = ARM
    struct.pack_into("<I", head, 24, 0x1B4F0)    # e_entry
    struct.pack_into("<I", head, 28, phoff)      # e_phoff
    struct.pack_into("<H", head, 42, phentsize)  # e_phentsize
    struct.pack_into("<H", head, 44, len(segments))
    body = b"".join(
        struct.pack("<8I", t, 0, vaddr, vaddr, memsz, memsz, flags, 0x8000)
        for (t, vaddr, memsz, flags) in segments)
    return bytes(head) + body


STOCK = [(PT_LOAD, 0x8000, 0x6F6F28, 5),        # RX
         (PT_LOAD, 0x707000, 0x14F26C, 6),      # RW
         (PT_GNU_STACK, 0, 0, 7)]

# What blip-free leaves behind: GNU_STACK is gone, and a third executable LOAD
# (the cave) has taken its place.
PATCHED = [(PT_LOAD, 0x8000, 0x6F6F28, 5),
           (PT_LOAD, 0x707000, 0x14F26C, 6),
           (PT_LOAD, 0x857000, 0x1000, 5)]


def _verdict(tmp_path, segments, name="game"):
    import gameinfo
    p = tmp_path / name
    p.write_bytes(_elf(segments))
    return gameinfo.firmware_provenance(path=str(p))


def test_stock_firmware_reads_as_stock(tmp_path):
    verdict, detail = _verdict(tmp_path, STOCK)
    assert verdict == "stock", detail


def test_blip_free_firmware_reads_as_patched(tmp_path):
    verdict, detail = _verdict(tmp_path, PATCHED)
    assert verdict == "patched", detail
    assert "blip-free" in detail
    assert "0x00857000" in detail, "the cave should be named, not just counted"


def test_a_file_that_is_not_an_elf_is_unknown_not_a_guess(tmp_path):
    p = tmp_path / "game"
    p.write_bytes(b"this is not an ELF, and a guess here would be a lie")
    import gameinfo
    verdict, _ = gameinfo.firmware_provenance(path=str(p))
    assert verdict == "unknown"


def test_a_missing_file_is_unknown(tmp_path):
    import gameinfo
    verdict, _ = gameinfo.firmware_provenance(path=str(tmp_path / "nope"))
    assert verdict == "unknown"


def test_an_unrecognised_shape_is_unknown_rather_than_stock(tmp_path):
    """One PT_LOAD and no GNU_STACK is neither shape. It must not fall through
    to a verdict - saying "stock" about something unrecognised is the failure
    this whole check exists to prevent."""
    verdict, _ = _verdict(tmp_path, [(PT_LOAD, 0x8000, 0x1000, 5)])
    assert verdict == "unknown"


@pytest.mark.skipif(not os.path.isfile(r"C:\tmp\gz116\game"),
                    reason="the extracted 1.16 ELF is not on this machine")
def test_the_real_godzilla_116_elf_is_stock():
    """The PAD-102 evidence itself: the card that crashes is unpatched."""
    import gameinfo
    verdict, detail = gameinfo.firmware_provenance(path=r"C:\tmp\gz116\game")
    assert verdict == "stock", detail
