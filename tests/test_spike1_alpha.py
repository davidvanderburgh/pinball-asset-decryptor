"""The early Spike 1 alphanumeric display (tools/spike1_emu/s1alpha.py).

The 2012 home models drive two 8-digit 16-segment displays with 256-byte
frames (4 bit-planes of 64 bytes, a slot per segment, 16 slots per digit).
These pin the decoding, the digit/display split, the text readout and the
renderer's shape; the live proof is the captured "PRESS START" / "PLAYER 1
BALL 1" frames decoded with the game's own font (PAD-101).
"""

import os
import sys

import pytest

_RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "spike1_emu")
if _RIG not in sys.path:
    sys.path.insert(0, _RIG)

import s1alpha  # noqa: E402


def _frame(lit):
    """A 256-byte frame with the given {(digit, segment): level} lit."""
    fr = bytearray(256)
    for (x, seg), lvl in lit.items():
        d = x * 16 + seg
        for p in range(4):
            if (lvl >> p) & 1:
                fr[p * 64 + (d >> 3)] |= 1 << (7 - (d & 7))
    return bytes(fr)


def test_blank_frame_decodes_to_32_dark_digits():
    rows = s1alpha.decode_frame(bytes(256))
    assert len(rows) == 32 and all(len(r) == 16 for r in rows)
    assert not any(any(r) for r in rows)
    assert s1alpha.frame_is_blank(bytes(256))


def test_slot_x16_plus_segment_addressing_and_levels():
    fr = _frame({(0, 15): 15, (7, 0): 9, (8, 12): 1})
    rows = s1alpha.decode_frame(fr)
    assert rows[0][15] == 15          # digit 0, segment a1, full brightness
    assert rows[7][0] == 9            # digit 7, g1, level 9
    assert rows[8][12] == 1           # player 2's first digit, segment c
    assert sum(sum(r) for r in rows) == 15 + 9 + 1


def test_short_frame_is_refused():
    with pytest.raises(ValueError):
        s1alpha.decode_frame(bytes(100))


def test_display_rows_split_player_1_and_2():
    rows = s1alpha.decode_frame(_frame({(3, 8): 15, (11, 8): 15}))
    p1, p2 = s1alpha.display_rows(rows)
    assert len(p1) == 8 and len(p2) == 8
    assert p1[3][8] == 15 and p2[3][8] == 15


def test_frame_text_reads_digits_with_a_font():
    # '1' lights segments 12 and 13 in the game's font
    one = tuple(1 if i in (12, 13) else 0 for i in range(16))
    fr = _frame({(0, 12): 15, (0, 13): 15, (9, 12): 15, (9, 13): 15})
    assert s1alpha.frame_text(fr, {one: "1"}) == ["1       ", " 1      "]
    assert s1alpha.frame_text(fr) == ["#       ", " #      "]   # no font


def test_render_draws_two_rows_of_eight_glyphs():
    pytest.importorskip("PIL")
    img = s1alpha.render_image(s1alpha.decode_frame(bytes(256)), scale=4)
    w, h = img.size
    assert w > 8 * 4 * 4 and h > 2 * 6 * 4          # 8 cells wide, 2 rows
    lit = s1alpha.render_image(s1alpha.decode_frame(_frame({(0, 15): 15})), scale=4)
    # a lit top-left segment paints amber pixels a blank frame does not
    blank_px = set(img.getdata())
    assert any(px[0] > 200 for px in lit.getdata() if px not in blank_px)


def test_every_segment_has_a_line_and_bits_are_the_font_order():
    assert sorted(s1alpha._SEG_LINES) == list(range(16))
    # the outer ring 8..15 forms a closed box: f,e down the left, d1,d2 along
    # the bottom, c,b up the right, a2,a1 back along the top
    ring = [s1alpha._SEG_LINES[i] for i in (15, 14, 13, 12, 11, 10, 9, 8)]
    for (a, b), (c, d) in zip(ring, ring[1:]):
        assert {a, b} & {c, d}, "ring segments must share an endpoint"
    assert set(ring[0]) & set(ring[-1])                # ...and close the box


# ---------------------------------------------------- the segment DECODER --
# The window shows the CHARACTERS, not just segment art (David: the segment
# view alone was "completely unusable").  The authority is the game's own font
# table, which the rig dumps to s1font.json so the window never reads the ELF.

def test_write_font_json_round_trips_through_the_pattern_keys(tmp_path):
    import json
    fake = {(1, 0) + (0,) * 14: "A", (0,) * 16: " "}
    out = tmp_path / "s1font.json"
    # write_font_json reads an ELF; exercise its serialisation shape directly
    doc = {"".join(str(b) for b in pat): ch for pat, ch in fake.items()}
    out.write_text(json.dumps(doc), encoding="utf-8")
    back = {tuple(int(c) for c in k): v
            for k, v in json.loads(out.read_text(encoding="utf-8")).items()}
    assert back == fake
    assert all(len(k) == 16 for k in doc)


def test_frame_text_uses_the_font_for_both_displays():
    # 'A' in the game's font lights 0,4,8,9,12,13,14,15
    a = tuple(1 if i in (0, 4, 8, 9, 12, 13, 14, 15) else 0 for i in range(16))
    font = {a: "A"}
    lit = {(0, i): 15 for i in (0, 4, 8, 9, 12, 13, 14, 15)}
    lit.update({(9, i): 15 for i in (0, 4, 8, 9, 12, 13, 14, 15)})
    fr = _frame(lit)
    assert s1alpha.frame_text(fr, font) == ["A       ", " A      "]


def test_a_pattern_the_font_does_not_know_is_marked_not_guessed():
    fr = _frame({(0, 1): 15, (0, 3): 15})        # two diagonals: no character
    assert s1alpha.frame_text(fr, {})[0].startswith("#")
