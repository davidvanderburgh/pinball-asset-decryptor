"""Spike 2 factory high-score board decoder/patcher (stern.high_scores).

Builds on the synthetic ELF from test_stern_adjustments: the same fake game
carries an adjustment table plus a record array shaped like the real one
({char* initials, char* name, shared handler, 0, char* slot label}), so the
locator, the per-slot capacity maths and the in-place patch are all covered
without a 69 MB game_real.
"""
import struct

import pytest

from pinball_decryptor.plugins.stern.adjustments import (AdjustmentTable,
                                                         OFF_MENU_LABEL)
from pinball_decryptor.plugins.stern.high_scores import HighScoreDefaults

BASE = 0x20000
ELEM = 44
STRIDE = 36
HANDLER = 0x00311078


# (adjustment name, menu caption) — the caption is what a high-score record
# points at, and how a record finds the adjustment holding its score.
ADJ = [
    ("AD_INVALID", "INVALID"),
    ("AD_FREE_PLAY", "FREE PLAY"),
    ("AD_GRAND_CHAMPION_SCORE", "GRAND CHAMPION SCORE"),
    ("AD_HIGH_SCORE_1_SCORE", "HIGH SCORE #1"),
    ("AD_HIGH_SCORE_2_SCORE", "HIGH SCORE #2"),
]
# (initials, player name, slot label) — the label ties back to a caption
# above, EXCEPT the Grand Champion, whose record says "GRAND CHAMPION" while
# its adjustment caption is "GRAND CHAMPION SCORE" (real firmware does this).
HSTD = [
    ("SSR", "THE KING", "GRAND CHAMPION"),
    ("TSX", "TIM S", "HIGH SCORE #1"),
    ("JMR", "ROTHARMEL", "HIGH SCORE #2"),
    ("OJ", "OLIVE", "SPINNER CHAMPION"),      # no adjustment for this one
    ("G S", "GARY STERN", "RECORD CHAMPION"),
    (" R ", "RAPHAEL", "RAPHAEL CHAMPION"),
]


def make_elf():
    """A little-endian 32-bit ARM ELF with both tables in one PT_LOAD."""
    hdr_len = 52 + 32
    pool = bytearray()
    va_of = {}

    def intern(text):
        """Add a NUL-terminated string, 4-byte aligned like the real pool (so
        the padding gives each string its writable slack)."""
        if text in va_of:
            return va_of[text]
        off = hdr_len + len(pool)
        pool.extend(text.encode() + b"\x00")
        while len(pool) % 4:
            pool.append(0)
        va_of[text] = BASE + off
        return va_of[text]

    adj_name_va = [intern(n) for n, _c in ADJ]
    cap_va = [intern(c) for _n, c in ADJ]
    hs_va = [(intern(i), intern(n), intern(lbl)) for i, n, lbl in HSTD]

    body = bytearray(pool)

    # names[] — the packed char*[] the adjustment decoder keys off.
    names_off = hdr_len + len(body)
    body.extend(b"".join(struct.pack("<I", v) for v in adj_name_va))

    # descriptor array: default@+4, min@+8, max@+12, step@+16, caption@+0x18
    desc_off = hdr_len + len(body)
    for i, (_n, _c) in enumerate(ADJ):
        e = bytearray(ELEM)
        struct.pack_into("<iiii", e, 0x04, 10 * (i + 1), 0, 1_000_000_000, 1)
        struct.pack_into("<I", e, OFF_MENU_LABEL, cap_va[i])
        body.extend(e)

    # the high-score record array
    hstd_off = hdr_len + len(body)
    for ini_va, name_va, lbl_va in hs_va:
        r = bytearray(STRIDE)
        struct.pack_into("<IIII", r, 0, ini_va, name_va, HANDLER, 0)
        struct.pack_into("<I", r, 0x10, lbl_va)
        body.extend(r)

    # section record {live, table, count, elem, node}
    node_va = intern("SYS")
    rec_off = hdr_len + len(body)
    body.extend(struct.pack("<IIIII", 0, BASE + desc_off, len(ADJ), ELEM,
                            node_va))
    assert names_off and rec_off                       # silence linters

    total = hdr_len + len(body)
    eh = bytearray(52)
    eh[0:4] = b"\x7fELF"
    eh[4], eh[5], eh[6] = 1, 1, 1
    struct.pack_into("<H", eh, 0x10, 2)
    struct.pack_into("<H", eh, 0x12, 40)
    struct.pack_into("<I", eh, 0x14, 1)
    struct.pack_into("<I", eh, 0x1c, 52)
    struct.pack_into("<H", eh, 0x28, 52)
    struct.pack_into("<H", eh, 0x2a, 32)
    struct.pack_into("<H", eh, 0x2c, 1)
    ph = struct.pack("<IIIIIIII", 1, 0, BASE, BASE, total, total, 5, 0x1000)
    return bytes(eh + ph + body), hstd_off


def load():
    elf, hstd_off = make_elf()
    table = AdjustmentTable(elf)
    return elf, HighScoreDefaults(elf, table), hstd_off


def test_locates_the_record_array_by_shape():
    elf, hs, hstd_off = load()
    assert hs.offset == hstd_off and hs.stride == STRIDE
    assert [r["initials"] for r in hs.rows] == [h[0] for h in HSTD]
    assert [r["name"] for r in hs.rows] == [h[1] for h in HSTD]
    assert [r["label"] for r in hs.rows] == [h[2] for h in HSTD]


def test_ties_each_slot_to_the_adjustment_holding_its_score():
    _elf, hs, _o = load()
    by_label = hs.by_label()
    assert by_label["HIGH SCORE #1"]["adjustment"] == "AD_HIGH_SCORE_1_SCORE"
    assert by_label["HIGH SCORE #2"]["adjustment"] == "AD_HIGH_SCORE_2_SCORE"
    # The Grand Champion needs the "<label> SCORE" fallback.
    assert by_label["GRAND CHAMPION"]["adjustment"] == \
        "AD_GRAND_CHAMPION_SCORE"
    # A slot the firmware exposes no score adjustment for still lists.
    assert by_label["SPINNER CHAMPION"]["adjustment"] is None


def test_capacity_is_the_strings_own_allocation():
    _elf, hs, _o = load()
    by_label = hs.by_label()
    # 3 chars + NUL fills a 4-byte slot exactly: initials are always 3.
    assert by_label["GRAND CHAMPION"]["initials_max"] == 3
    # "OJ" is 2 chars + NUL + 1 pad byte -> room for 3.
    assert by_label["SPINNER CHAMPION"]["initials_max"] == 3
    # "THE KING" is 8 chars + NUL + 3 pad -> room for 11.
    assert by_label["GRAND CHAMPION"]["name_max"] == 11
    # "TIM S" is 5 + NUL + 2 pad -> room for 7.
    assert by_label["HIGH SCORE #1"]["name_max"] == 7


def test_patch_is_size_neutral_and_reads_back():
    elf, hs, _o = load()
    out = hs.patched_bytes({"GRAND CHAMPION": {"initials": "PAD",
                                               "name": "MONKEYBUG"},
                            "HIGH SCORE #1": {"initials": "DAV"}})
    assert len(out) == len(elf)
    again = HighScoreDefaults(out, AdjustmentTable(out)).by_label()
    assert again["GRAND CHAMPION"]["initials"] == "PAD"
    assert again["GRAND CHAMPION"]["name"] == "MONKEYBUG"
    assert again["HIGH SCORE #1"]["initials"] == "DAV"
    # Untouched slots are untouched.
    assert again["HIGH SCORE #2"]["initials"] == "JMR"
    assert again["HIGH SCORE #2"]["name"] == "ROTHARMEL"


def test_shorter_replacement_leaves_no_tail_of_the_old_string():
    _elf, hs, _o = load()
    out = hs.patched_bytes({"GRAND CHAMPION": {"name": "OJ"}})
    again = HighScoreDefaults(out, AdjustmentTable(out)).by_label()
    assert again["GRAND CHAMPION"]["name"] == "OJ"


def test_patch_rejects_overlong_and_unknown():
    _elf, hs, _o = load()
    with pytest.raises(ValueError, match="room for 3"):
        hs.patched_bytes({"GRAND CHAMPION": {"initials": "TOOLONG"}})
    with pytest.raises(ValueError, match="room for 7"):
        hs.patched_bytes({"HIGH SCORE #1": {"name": "ROTHARMEL!!"}})
    with pytest.raises(ValueError, match="unknown high-score slot"):
        hs.patched_bytes({"NOT A SLOT": {"initials": "ABC"}})


def test_no_table_raises():
    from tests.test_stern_adjustments import SPECS, make_elf as plain_elf
    elf = plain_elf(SPECS)
    with pytest.raises(ValueError, match="no default high-score table"):
        HighScoreDefaults(elf, AdjustmentTable(elf))


def test_one_adjustment_is_never_claimed_by_two_slots():
    """Co-op / team boards repeat a caption at several menu indents, and all
    of them normalise onto the same score adjustment — only the first (the
    un-indented one) gets it, or the editor would build two spinboxes bound to
    one setting."""
    elf, hstd_off = make_elf()
    # Append an indented duplicate of HIGH SCORE #1 to the record array.
    buf = bytearray(elf)
    dup = bytearray(buf[hstd_off + STRIDE:hstd_off + 2 * STRIDE])
    lbl_va = struct.unpack_from("<I", dup, 0x10)[0]
    # Re-point it at a padded copy of the same caption appended to the file.
    pad_va = BASE + len(buf)
    buf.extend(b" HIGH SCORE #1 \x00\x00")
    struct.pack_into("<I", dup, 0x10, pad_va)
    buf[hstd_off + len(HSTD) * STRIDE:
        hstd_off + len(HSTD) * STRIDE] = dup
    assert lbl_va != pad_va
    # The PT_LOAD has to cover the bytes we appended.
    struct.pack_into("<II", buf, 52 + 16, len(buf), len(buf))
    hs = HighScoreDefaults(bytes(buf), AdjustmentTable(bytes(buf)))
    owners = [r["adjustment"] for r in hs.rows if r["adjustment"]]
    assert len(owners) == len(set(owners))
    assert owners.count("AD_HIGH_SCORE_1_SCORE") == 1


def _append_str(buf, text):
    """Append a NUL-terminated string, return its VA (PT_LOAD grown later)."""
    while len(buf) % 4:
        buf.append(0)
    va = BASE + len(buf)
    buf.extend(text.encode("latin1") + b"\x00")
    return va


def _grow_load(buf):
    struct.pack_into("<II", buf, 52 + 16, len(buf), len(buf))


def test_a_longer_unlabeled_run_does_not_win():
    """A connector/pin wiring table ("CN7", pin "2", shared word) is shaped
    exactly like the board and can be LONGER (Venom: 87 lamps vs 47 slots),
    but none of its records has a caption — the board must still win."""
    elf, hstd_off = make_elf()
    buf = bytearray(elf)
    ini = _append_str(buf, "CN7")
    pin = _append_str(buf, "2")
    shared = _append_str(buf, "1")
    while len(buf) % 4:
        buf.append(0)
    for i in range(3 * len(HSTD)):
        buf.extend(struct.pack("<IIIIII", ini, pin, shared,
                               0x175010F + i, 0, 0))
    _grow_load(buf)
    hs = HighScoreDefaults(bytes(buf), AdjustmentTable(bytes(buf)))
    assert hs.offset == hstd_off and hs.stride == STRIDE
    assert len(hs.rows) == len(HSTD)


def test_two_line_captions_decode():
    """Jaws-era captions hold both display lines in one string ("JAWS
    MULTIBALL 1\\nCHAMPION"); the raw label keeps the newline (it is the
    stable key), the display copy collapses it."""
    elf, hstd_off = make_elf()
    buf = bytearray(elf)
    ins = hstd_off + len(HSTD) * STRIDE
    buf[ins:ins] = buf[hstd_off:hstd_off + STRIDE]
    lbl = _append_str(buf, "ENCORE\nCHAMPION")
    struct.pack_into("<I", buf, ins + 0x10, lbl)
    _grow_load(buf)
    hs = HighScoreDefaults(bytes(buf), AdjustmentTable(bytes(buf)))
    assert len(hs.rows) == len(HSTD) + 1
    row = hs.by_label()["ENCORE\nCHAMPION"]
    assert row["display"] == "ENCORE CHAMPION"


def test_language_bundle_labels_resolve():
    """Older builds point +0x10 at a per-language bundle {char* EN, DE, …, 0}
    instead of at the caption itself — the English entry is the label."""
    elf, hstd_off = make_elf()
    buf = bytearray(elf)
    ins = hstd_off + len(HSTD) * STRIDE
    buf[ins:ins] = buf[hstd_off:hstd_off + STRIDE]
    en = _append_str(buf, "BUNDLE CHAMPION")
    de = _append_str(buf, "BUENDEL CHAMPION")
    while len(buf) % 4:
        buf.append(0)
    bundle = BASE + len(buf)
    buf.extend(struct.pack("<III", en, de, 0))
    struct.pack_into("<I", buf, ins + 0x10, bundle)
    _grow_load(buf)
    hs = HighScoreDefaults(bytes(buf), AdjustmentTable(bytes(buf)))
    assert "BUNDLE CHAMPION" in hs.by_label()


def test_caption_normalisation_bridges_sterns_spellings():
    n = HighScoreDefaults._norm_caption
    # Grand Champion: record vs adjustment.
    assert n("GRAND CHAMPION") == n("GRAND CHAMPION SCORE")
    # Led Zeppelin abbreviates CHAMPION to CHAMP in the adjustment caption.
    assert n("KASHMIR CHAMPION") == n("KASHMIR CHAMP SCORE")
    # TMNT pads co-op captions to indent them in the operator menu.
    assert n(" COOP HIGH SCORE #3 ") == n("COOP HIGH SCORE #3")
    # An award is not a score and must never fold onto one.
    assert n("KASHMIR CHAMP AWARD") != n("KASHMIR CHAMP SCORE")
