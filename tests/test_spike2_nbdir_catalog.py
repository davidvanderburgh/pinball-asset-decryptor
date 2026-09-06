"""The board-model catalog framing nbdir.py reads a title's part numbers with.

The record starts at the PART NUMBER, not at the type name (nbdir's module
docstring carries the measurement, mando_le 1.44.0, 2026-09-05). Every part
number the rig had ever printed was the NEXT row's, and nothing noticed until
mando_le's holographic topper: the game renders it only when node 12 reports
the part its own catalog gives node 12's type, and the shim answers that from
the `partno=` field nbdir now writes (item 67). These pin the framing and the
field on a synthetic table, so the next reframing cannot pass unseen.
"""
import os
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "spike2_emu"))

RX_VA = 0x8000


@pytest.fixture(scope="module")
def nbdir():
    import nbdir as mod
    return mod


def _table():
    """A two-row catalog the way the game lays it out: strings first, then
    {part_str, part_value, type_name, name_cell, flags} twice, with the
    type-name words where find_catalog() anchors (row start + 8)."""
    # explicit \x00: "\0520" would be the octal escape for "*0"
    strings = b"\x00".join([b"520-5319-XX", b"pinnode", b"520-8530-XX",
                            b"hdmi_ws2812node", b""])
    blob = bytearray(strings)
    blob += b"\0" * (0x100 - len(blob))

    def va(off):
        return RX_VA + off

    rows = [
        (va(0), 520531900, va(12), 0xdead0000, 0x18080400),
        (va(20), 520853000, va(32), 0xdead0014, 0x10600004),
    ]
    for r in rows:
        blob += struct.pack("<5I", *r)
    rx = (0, len(blob), RX_VA)
    return bytes(blob), rx


NAME_ANCHOR = 0x100 + 8         # what find_catalog() returns for this table


def test_part_fields_sit_before_the_name_anchor(nbdir):
    elf, rx = _table()
    assert nbdir.catalog_part(elf, NAME_ANCHOR, 0, rx) == ("520-5319-XX", 520531900)
    assert nbdir.catalog_part(elf, NAME_ANCHOR, 1, rx) == ("520-8530-XX", 520853000)


def test_the_value_is_the_string_times_100(nbdir):
    # the game prints the value "%09d" and splits it "ddd-dddd-dd", so the
    # two must agree or the shim would report a number the string denies
    elf, rx = _table()
    pstr, pval = nbdir.catalog_part(elf, NAME_ANCHOR, 1, rx)
    a, b, _rev = pstr.split("-")
    assert pval // 100 == int(a) * 10000 + int(b)


def test_a_row_before_the_table_reads_as_nothing(nbdir):
    elf, rx = _table()
    assert nbdir.catalog_part(elf, 4, 0, rx) == (None, 0)


def test_emit_writes_partno_beside_the_mcu_part_id(nbdir, tmp_path):
    out = tmp_path / "node_ident.txt"
    rows = [(12, "hdmi_ws2812node", 32, 0x2c40102b, 5, 0x0c,
             0x011300, "1.19.0", "hdmi_ws2812node-LPC1313-1_19_0.hex", False,
             520853000)]
    nbdir.emit(rows, [], "game", str(out))
    lines = [l for l in out.read_text().splitlines() if l.startswith("node=")]
    assert len(lines) == 1
    line = lines[0]
    assert " part=0x2c40102b " in line          # the MCU id keeps its key
    assert " partno=520853000 " in line         # the Stern number, decimal
    assert "variant_guess" not in line
