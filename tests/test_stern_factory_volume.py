"""The built-in master volume a Spike 2 machine starts at
(plugins.stern.factory_volume).

The getter's shape is planted into the synthetic ELF from
test_stern_adjustments, so the locator is covered without a 69 MB game_real:

    mov  r0, #<master volume id>
    bl   <get_adjustment>
    uxtb r4, r0
    cmp  r4, #0x3f
    bls  +8
    movw r3, #lo / movt r3, #hi
    ldrb r4, [r3]          <- the byte this module exists to find

On the 34 vendor cards this was checked against, that shape appears exactly
once per title and the byte holds the volume the machine really comes up at
(30 on Led Zeppelin, 10 on Godzilla, 24 on John Wick).
"""
import struct

import pytest

from pinball_decryptor.plugins.stern import factory_volume
from pinball_decryptor.plugins.stern.adjustments import (AdjustmentTable,
                                                         curated_rows)

from .test_stern_adjustments import SPECS, make_elf

VOL_ID = [s[0] for s in SPECS].index("AD_SOUND_MASTER_VOLUME_SETTING")


def _words(*ws):
    return b"".join(struct.pack("<I", w) for w in ws)


def _movw(rd, imm):
    return 0xE3000000 | ((imm >> 12) & 0xf) << 16 | rd << 12 | (imm & 0xfff)


def _movt(rd, imm):
    return 0xE3400000 | ((imm >> 28) & 0xf) << 16 | rd << 12 \
        | ((imm >> 16) & 0xfff)


def getter(volume=30, vol_id=VOL_ID, copies=1, filler=0):
    """A ``code(code_va) -> bytes`` for :func:`make_elf`: *copies* of the
    volume getter, each reading its own byte.  The bytes sit first so their
    addresses are known before the code that names them is assembled."""
    def build(code_va):
        head = bytes([volume]) * copies
        head += b"\x00" * (-len(head) % 4)
        body = b""
        for i in range(copies):
            addr = code_va + i
            body += _words(
                0xE3A00000 | vol_id,            # mov  r0, #vol_id
                0xEB000000,                     # bl   get_adjustment
                0xE6EF4070,                     # uxtb r4, r0
                0xE354003F,                     # cmp  r4, #0x3f
                0x9A000002,                     # bls  +8
                *([0xE1A00000] * filler),       # nop-ish scheduling filler
                _movw(3, addr & 0xffff),
                _movt(3, addr),
                0xE5D34000,                     # ldrb r4, [r3]
            )
        return head + body
    return build


def table(**kw):
    return AdjustmentTable(make_elf(SPECS, code=getter(**kw)))


def test_finds_the_byte_the_machine_starts_at():
    t = table(volume=30)
    spot = factory_volume.find(t)
    assert spot is not None
    assert spot["value"] == 30
    assert t.data[spot["offset"]] == 30
    # ...and it is NOT the compiled default, which is the whole point.
    assert t.get("AD_SOUND_MASTER_VOLUME_SETTING")["default"] == 64


def test_found_through_scheduled_filler():
    """A build that schedules a couple of unrelated instructions between the
    cmp and the load still matches — the real firmwares differ here."""
    spot = factory_volume.find(table(volume=10, filler=3))
    assert spot is not None and spot["value"] == 10


def test_patch_moves_one_byte_and_is_range_checked():
    t = table(volume=30)
    spot = factory_volume.find(t)
    out = factory_volume.patched_bytes(t.data, spot, 24)
    assert len(out) == len(t.data)
    assert sum(1 for a, b in zip(t.data, out) if a != b) == 1
    assert out[spot["offset"]] == 24
    # 64 is exactly what Stern ships and exactly what the firmware refuses.
    with pytest.raises(ValueError):
        factory_volume.patched_bytes(t.data, spot, 64)
    with pytest.raises(ValueError):
        factory_volume.patched_bytes(t.data, spot, -1)


def test_refuses_an_ambiguous_build():
    """Two matches means we don't know which byte the machine reads, and a
    wrong byte written into the game program is worse than no change."""
    assert factory_volume.find(table(volume=30, copies=2)) is None


def test_refuses_an_implausible_value():
    """A byte the firmware itself would reject isn't the volume — some other
    code just happens to look like the getter."""
    assert factory_volume.find(table(volume=200)) is None


def test_refuses_when_the_title_has_no_master_volume():
    specs = [(("AD_SOUND_SOME_OTHER_SETTING" if
               s[0] == "AD_SOUND_MASTER_VOLUME_SETTING" else s[0]),) + s[1:]
             for s in SPECS]
    assert factory_volume.find(
        AdjustmentTable(make_elf(specs, code=getter()))) is None


def test_curated_row_reports_the_built_in_volume():
    t = table(volume=30)
    spot = factory_volume.find(t)
    row = {r["name"]: r for r in curated_rows(t, master_volume=spot)}[
        "AD_SOUND_MASTER_VOLUME_SETTING"]
    # The card's value is the built-in 30 the operator will see, not the
    # inert compiled 64, and the field stops at the 63 the firmware accepts.
    assert (row["default"], row["min"], row["max"]) == (30, 0, 63)
    # Without the lookup the row falls back to the compiled default.
    plain = {r["name"]: r for r in curated_rows(t)}[
        "AD_SOUND_MASTER_VOLUME_SETTING"]
    assert (plain["default"], plain["max"]) == (64, 64)
