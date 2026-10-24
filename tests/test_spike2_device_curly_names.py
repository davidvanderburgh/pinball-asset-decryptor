"""PAD-703: Stranger Things inserts missing or misplaced on the virtual playfield.

"There are four missing or misplaced inserts on the Stranger Things Premium
playfield" (peanuts, 2026-10-24). Two were dropped by devicexy: Stern names
6:36 `TRAP ‘EM` and 7:48 `WHERE’S BARB?` with UTF-8 curly quotes, and the name
read was ASCII only, so both records were refused. The other two are Stern's
own places, 10-11 px off their inserts (devicexy.MOVED).

Measured over the latest card of every title (60): only stranger_things and
stranger_things_le change, by those four lamps, and no switch row moves.
"""
import os
import struct
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

import devicexy                                    # noqa: E402

STRIDE = devicexy.STRIDE
BIAS = devicexy.VA_BIAS
TABLE = 0x2000


def _blob(recs):
    """A binary holding `recs` - (name bytes, group, index, x, y) LEDs on
    `playfield` - as one run at a true stride. Names go in the PREVIOUS slot
    (devicexy.NAME_OFF)."""
    buf = bytearray(0x4000)
    at = [0x0010]

    def string(raw):
        off = at[0]
        buf[off:off + len(raw) + 1] = raw + b"\x00"
        at[0] += len(raw) + 1
        return off + BIAS

    pf = string(b"playfield")
    for i, (name, grp, idx, x, y) in enumerate(recs):
        rec = TABLE + i * STRIDE
        struct.pack_into("<I", buf, rec + 0x00, pf)
        struct.pack_into("<hh", buf, rec + 0x04, grp, idx)
        struct.pack_into("<hh", buf, rec + 0x08, 3, 2)
        struct.pack_into("<hhhh", buf, rec + 0x10, x, y, 20, 20)
        struct.pack_into("<I", buf, rec + devicexy.NAME_OFF, string(name))
    return bytes(buf)


def _records(tmp_path, recs):
    p = tmp_path / "game.bin"
    p.write_bytes(_blob(recs))
    d, cstr = devicexy.load(str(p))
    return sorted(devicexy.records(d, cstr), key=lambda r: r["va"])


def _st_column():
    """Stranger Things' centre column, as 1.13.0 ships it."""
    return [(b"BUST OUT!", 6, 35, 167, 324),
            ("TRAP ‘EM".encode("utf-8"), 6, 36, 167, 345),
            (b"WHAT'S THAT?", 6, 37, 167, 363),
            (b"RUN WILL!", 6, 38, 167, 383),
            ("WHERE’S BARB?".encode("utf-8"), 7, 48, 91, 395),
            (b"MONSTER HUNTING!", 7, 49, 95, 416)]


def test_curly_quote_names_are_read_as_plain_text(tmp_path):
    """The report's two holes: both records come back, named as typed."""
    recs = _records(tmp_path, _st_column())
    assert [(r["name"], r["group"], r["index"]) for r in recs] == [
        ("BUST OUT!", 6, 35), ("TRAP 'EM", 6, 36), ("WHAT'S THAT?", 6, 37),
        ("RUN WILL!", 6, 38), ("WHERE'S BARB?", 7, 48),
        ("MONSTER HUNTING!", 7, 49)]
    assert all(r["name"].isascii() for r in recs)


def test_a_curly_name_round_trips_through_the_text_table(tmp_path):
    """device_xy.txt is what the playfield window reads, in its own codepage."""
    recs = _records(tmp_path, _st_column())
    txt = devicexy.text("stranger_things_le", recs, None, 321, 710)
    assert txt.isascii()
    p = tmp_path / "device_xy.txt"
    p.write_text(txt)
    back = devicexy.read_table(str(p))
    assert [(r["name"], r["x"], r["y"]) for r in back][1] == ("TRAP 'EM", 167, 345)


def test_other_non_ascii_or_control_names_are_still_refused(tmp_path):
    """Only the typographic marks are mapped; a name the reader cannot spell
    in ASCII still refuses its record, as before."""
    recs = _records(tmp_path, [(b"LAMP 1", 6, 1, 40, 300),
                               (b"LAMP 2", 6, 2, 60, 300),
                               (b"LAMP 3", 6, 3, 80, 300),
                               (b"LAMP 4", 6, 4, 100, 300),
                               ("CAFÉ".encode("utf-8"), 6, 5, 120, 300),
                               (b"BAD\x07", 6, 6, 140, 300),
                               (b"\xff\xfe", 6, 7, 160, 300)])
    assert [r["name"] for r in recs] == ["LAMP 1", "LAMP 2", "LAMP 3", "LAMP 4"]


def test_stern_misplaced_inserts_are_moved_onto_their_inserts(tmp_path):
    recs = _records(tmp_path, [(b"RIGHT RAMP MODE START 3", 6, 48, 229, 339),
                               (b"RIGHT RAMP MODE START 2", 6, 31, 225, 369),
                               (b"RIGHT RAMP MODE START 1", 6, 24, 221, 381),
                               (b"DEMODO(G)", 6, 21, 250, 399)])
    at = {r["name"]: (r["x"], r["y"]) for r in recs}
    assert at == {"RIGHT RAMP MODE START 3": (229, 339),
                  "RIGHT RAMP MODE START 2": (225, 360),
                  "RIGHT RAMP MODE START 1": (221, 381),
                  "DEMODO(G)": (241, 399)}


def test_a_move_needs_the_wrong_place_itself(tmp_path):
    """A build that fixes the place, or another lamp of the same name at
    another address, is left as the binary says."""
    recs = _records(tmp_path, [(b"RIGHT RAMP MODE START 2", 6, 31, 225, 358),
                               (b"DEMODO(G)", 7, 21, 250, 399),
                               (b"LAMP A", 6, 1, 40, 300),
                               (b"LAMP B", 6, 2, 60, 300)])
    at = {r["name"]: (r["x"], r["y"]) for r in recs}
    assert at["RIGHT RAMP MODE START 2"] == (225, 358)
    assert at["DEMODO(G)"] == (250, 399)
