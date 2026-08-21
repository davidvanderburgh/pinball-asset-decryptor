"""The device table's SEEDS, and the cache that decided it never needed rebuilding.

Queue item 61. `godzilla_le` drew the switch list and said "no playfield artwork
in this title" while its card shipped both the drawing and 593 device records.
Two independent faults had to line up, and each gets a test here because each
one on its own is silent:

  * `devicexy.seeds()` only recorded where a string STARTS. A linker merges a
    string that is a SUFFIX of another into it and points at the tail, and
    godzilla_le keeps exactly one NUL-terminated `playfield` in the binary - at
    the end of `Test/scaled_godzilla_le_playfield`. A record run made up
    entirely of playfield records therefore had NO seed and was never walked.
    `godzilla_pro` hides this completely: it happens to keep a second,
    standalone copy of the string, so the same code found all 575 of its
    records and the fault read as a property of the LE card.

  * `mktables._stale()` judged a cached table by mtime alone, so a zero-record
    table written when no binary was reachable was permanently "newer" than the
    binary it never opened - a card's files carry the IMAGE's mtimes. 17 of 30
    cached titles were carrying one and nothing was ever going to rebuild them.

The synthetic binaries below are the smallest thing `records()` accepts: a run
of five 0x30-byte records at a true stride, with the name of each living at the
PREVIOUS record's +0x24 (devicexy.NAME_OFF is negative, and its header says
why). Nothing here needs a real ELF or a card.
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
import mktables                                    # noqa: E402

STRIDE = devicexy.STRIDE
BIAS = devicexy.VA_BIAS

#: Where the string pool starts, and where the record table starts, as OFFSETS
#: into the fake binary. The table is placed well clear of the pool so the slot
#: BEFORE record 0 - which the run walk-back probes - is zeroes.
POOL = 0x0000
TABLE = 0x0400

NAMES = ["SKILL SHOT", "LEFT SPINNER", "MASER TARGET", "POP BUMPER",
         "RIGHT SCOOP"]


def _blob(image_string, tail_offset):
    """A binary whose five records all name `image_string[tail_offset:]`.

    `tail_offset` is the whole trick: 0 points at the string itself, and any
    other value points INTO it, which is what a suffix merge produces.
    """
    buf = bytearray(0x1000)

    def put(off, raw):
        buf[off:off + len(raw)] = raw

    put(POOL, image_string + b"\x00")
    name_off = {}
    at = POOL + len(image_string) + 1
    for n in NAMES:
        name_off[n] = at
        put(at, n.encode() + b"\x00")
        at += len(n) + 1

    img_va = POOL + BIAS + tail_offset
    for i, name in enumerate(NAMES):
        rec = TABLE + i * STRIDE
        struct.pack_into("<I", buf, rec + 0x00, img_va)
        struct.pack_into("<hh", buf, rec + 0x04, 7, i)            # group, index
        struct.pack_into("<hh", buf, rec + 0x08, 1, 0)            # class 1 = switch
        struct.pack_into("<I", buf, rec + 0x0c, 0x0aa00a71)
        struct.pack_into("<hh", buf, rec + 0x10, 40 + i, 300 + i)  # x, y
        struct.pack_into("<hh", buf, rec + 0x14, 20, 20)          # w, h
        # THE NAME BELONGS TO THE RECORD AFTER IT - devicexy.NAME_OFF.
        struct.pack_into("<I", buf, rec + devicexy.NAME_OFF,
                         name_off[name] + BIAS)
    return bytes(buf)


def _records(tmp_path, blob, stem):
    p = tmp_path / (stem + ".bin")
    p.write_bytes(blob)
    d, cstr = devicexy.load(str(p))
    return devicexy.records(d, cstr), d


def test_a_standalone_image_name_is_found(tmp_path):
    """The control. This case always worked and must keep working."""
    recs, _ = _records(tmp_path, _blob(b"playfield", 0), "standalone")
    assert [r["name"] for r in recs] == NAMES


def test_an_image_name_merged_into_a_longer_string_is_found(tmp_path):
    """The regression: the pointer lands 14 bytes INTO the only string there is.

    This is godzilla_le exactly - one `playfield`, at the tail of
    `Test/scaled_godzilla_le_playfield`, and a run that names nothing else. The
    old seeder recorded only the start of the string, so every record here was
    unreachable and the title fell through to the switch list.
    """
    merged = b"Test/scaled_x_playfield"
    assert merged.endswith(b"playfield")
    tail = len(merged) - len(b"playfield")
    recs, d = _records(tmp_path, _blob(merged, tail), "merged")
    assert [r["name"] for r in recs] == NAMES, "the merged tail was not seeded"
    assert all(r["image"] == "playfield" for r in recs)
    # seeds() returns RECORD addresses - the words that point at an image name -
    # so this is the seeder's own answer, not the walk's.
    assert TABLE + BIAS in set(devicexy.seeds(d))


def test_a_path_suffix_is_seeded_too(tmp_path):
    """A merge can land on any suffix that is still a legal image name.

    `System/TestMode/x` merged into `Extra/System/TestMode/x` points past the
    first component, and the suffix still carries a "/" - which is the other
    half of _one()'s image test.
    """
    merged = b"Extra/System/TestMode/x"
    recs, _d = _records(tmp_path, _blob(merged, len(b"Extra/")), "path")
    assert [r["name"] for r in recs] == NAMES
    assert all(r["image"] == "System/TestMode/x" for r in recs)


def test_a_bare_word_tail_that_is_not_an_image_name_is_not_seeded(tmp_path):
    """The fix must not seed every suffix of every string.

    `scaled_x_backpanel` ends in `backpanel`, which is neither "playfield" nor
    a path, so its tail is not a candidate. That is the same refusal _one()
    would make anyway; it is asserted here so the seed set cannot quietly grow
    into "every offset in the binary".
    """
    recs, d = _records(tmp_path, _blob(b"scaled_x_backpanel", len(b"scaled_x_")),
                       "tail")
    assert TABLE + BIAS not in set(devicexy.seeds(d))
    assert recs == []


def test_binary_id_names_the_file_and_its_size(tmp_path):
    p = tmp_path / "game"
    p.write_bytes(b"x" * 1234)
    assert devicexy.binary_id(str(p)) == "game 1234 bytes"
    assert devicexy.binary_id(str(tmp_path / "nope")) is None
    assert devicexy.binary_id(None) is None


def test_the_written_table_records_the_binary_and_still_parses(tmp_path):
    recs, _ = _records(tmp_path, _blob(b"playfield", 0), "hdr")
    elf = tmp_path / "game"
    elf.write_bytes(b"y" * 99)
    out = tmp_path / "device_xy.txt"
    out.write_text(devicexy.text("t", recs, None, 313, 710, str(elf)),
                   newline="")
    assert "# binary: game 99 bytes" in out.read_text()
    # The extra header line must not disturb the reader, which counts fields
    # from the RIGHT because the name is the multi-word one.
    assert [r["name"] for r in devicexy.read_table(str(out))] == NAMES


def _table(tmp_path, body):
    p = tmp_path / "device_xy.txt"
    p.write_text(body, newline="")
    return str(p)


def test_a_table_that_names_no_binary_is_rebuilt(tmp_path):
    """The 17 poisoned files. An empty table is not evidence of an empty title."""
    elf = tmp_path / "game"
    elf.write_bytes(b"z" * 500)
    dest = _table(tmp_path, "# t device positions, from the game binary.\n"
                            "# 0 records (), 0 on the playfield image.\n")
    assert mktables._recorded_binary(dest) is None
    assert not mktables._built_from(dest, str(elf))


def test_a_table_naming_this_binary_stays_cached(tmp_path):
    """The legitimate empty - a title that really ships no device table - must
    not be re-derived out of an 8 MB binary on every single run."""
    elf = tmp_path / "game"
    elf.write_bytes(b"z" * 500)
    dest = _table(tmp_path, "# t device positions, from the game binary.\n"
                            "# binary: game 500 bytes\n"
                            "# 0 records (), 0 on the playfield image.\n")
    assert mktables._built_from(dest, str(elf))


def test_a_table_naming_a_different_binary_is_rebuilt(tmp_path):
    """A card swap. mtime cannot see this at all: a card's files carry the
    IMAGE's timestamps, so the newer card is routinely the OLDER file."""
    elf = tmp_path / "game"
    elf.write_bytes(b"z" * 777)
    dest = _table(tmp_path, "# t device positions, from the game binary.\n"
                            "# binary: game 500 bytes\n"
                            "# 3 records (switch=3), 3 on the playfield image.\n")
    assert not mktables._built_from(dest, str(elf))
    assert mktables._stale(dest, str(elf)) is False, \
        "mtime alone still says cached - which is the whole point"


def test_no_binary_to_compare_against_keeps_what_is_there(tmp_path):
    """Same contract as _stale(): with nothing to check, do not churn."""
    dest = _table(tmp_path, "# t\n# 0 records (), 0 on the playfield image.\n")
    assert mktables._built_from(dest, None)
    assert mktables._built_from(dest, str(tmp_path / "absent"))
    assert mktables._built_from(str(tmp_path / "absent.txt"), None)


# --- cardaudit.py's pure halves ------------------------------------------
# The card-reading half needs a 8 GB .raw and is exercised by running it; these
# are the two pieces that can be wrong quietly.

def test_cardaudit_reads_records_from_bytes_not_a_path(tmp_path):
    """The card's ELF never exists as a file, so records_of() takes bytes.

    Same table the seeder tests build, through the path cardaudit actually
    uses - if the temp-file dance regresses, every title scores zero and the
    audit reads like a catalogue of empty cards.
    """
    import cardaudit
    recs = cardaudit.records_of(_blob(b"playfield", 0))
    assert [r["name"] for r in recs] == NAMES


def test_cardaudit_reads_a_png_size_from_the_header_alone(tmp_path):
    """33 bytes, never a full read - a card's art can be megabytes."""
    import cardaudit
    head = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
            + struct.pack(">II", 313, 710) + b"\x08\x06\x00\x00\x00")
    assert cardaudit._png_size(head) == (313, 710)
    assert cardaudit._png_size(b"not a png at all, no") is None
