"""The early Spike 1 alphanumeric display (Transformers The Pin — PAD-101):
decoder + renderer for the 256-byte frames the game streams to /dev/spi0.

The 2012 home models have two 8-digit 16-segment displays instead of a DMD.
The game's display thread (``dmd_update_t``) packs a 512-slot buffer into
**4 bit-planes of 64 bytes** (plane p holds bit p of every slot's 4-bit level,
slots 8 per byte MSB first — the same packing as the 128x32 DMD's 2048-byte
frame, a quarter the size) and writes it through the same begin/commit
ioctls.  The slot buffer is indexed ``x*16 + segment`` (``ALPHANUMERIC_
SegmentSet``), so **every run of 16 slots is one digit**: x = 0..7 the
player-1 display, 8..15 player 2, the rest unused (two 8-digit displays;
32 rows fit the 512 slots).  Verified live: decoding the captured frames with
the game's own font (16 bytes per ASCII code at 0xb3160 in ``gamer``) reads
"PRESS START", "VOLUME: 27%", "PLAYER 1 BALL 1", "PLUNGE BALL".

Which bit is which segment was pinned from that font ('0' lights 8..15, '1'
lights 12..13, '-' 0 and 4, 'T' 2/6 + 14/15, 'X' the four diagonals):

    0 g1  mid-left     8 f   upper-left vertical
    1 k   lower-left   9 e   lower-left vertical
      diagonal        10 d1  bottom-left
    2 l   lower       11 d2  bottom-right
      vertical        12 c   lower-right vertical
    3 m   lower-right 13 b   upper-right vertical
      diagonal        14 a2  top-right
    4 g2  mid-right   15 a1  top-left
    5 j   upper-right diagonal
    6 i   upper vertical
    7 h   upper-left diagonal

Pure Python + optional PIL, like s1dmd.py; loaded by path from the rig dir.
"""

FRAME_BYTES = 256
PLANES = 4
PLANE_BYTES = 64
SLOTS = 512
SEGMENTS = 16
DIGITS = 8              # per display
DISPLAYS = 2

# segment -> line from (x0, y0) to (x1, y1) in a 4-wide x 6-tall glyph cell
# (the outer box is x 0..4, y 0..6; the middle bar is y 3; centre x is 2)
_SEG_LINES = {
    0: ((0, 3), (2, 3)),        # g1
    1: ((2, 3), (0, 6)),        # k
    2: ((2, 3), (2, 6)),        # l
    3: ((2, 3), (4, 6)),        # m
    4: ((2, 3), (4, 3)),        # g2
    5: ((2, 3), (4, 0)),        # j
    6: ((2, 0), (2, 3)),        # i
    7: ((0, 0), (2, 3)),        # h
    8: ((0, 0), (0, 3)),        # f
    9: ((0, 3), (0, 6)),        # e
    10: ((0, 6), (2, 6)),       # d1
    11: ((2, 6), (4, 6)),       # d2
    12: ((4, 3), (4, 6)),       # c
    13: ((4, 0), (4, 3)),       # b
    14: ((2, 0), (4, 0)),       # a2
    15: ((0, 0), (2, 0)),       # a1
}


def decode_frame(frame):
    """One 256-byte frame -> a list of 32 rows, each 16 segment levels 0..15
    (row = digit slot x; rows 0..7 = player 1, 8..15 = player 2)."""
    if len(frame) < FRAME_BYTES:
        raise ValueError("frame is %d bytes, need %d" % (len(frame), FRAME_BYTES))
    levels = []
    for d in range(SLOTS):
        byte_i, bit = d >> 3, 7 - (d & 7)
        v = 0
        for p in range(PLANES):
            v |= ((frame[p * PLANE_BYTES + byte_i] >> bit) & 1) << p
        levels.append(v)
    return [levels[x * SEGMENTS:(x + 1) * SEGMENTS] for x in range(SLOTS // SEGMENTS)]


def frame_is_blank(frame):
    return not any(frame[:FRAME_BYTES])


def display_rows(rows):
    """The two displays' digits: [[row0..row7], [row8..row15]]."""
    return [rows[0:DIGITS], rows[DIGITS:2 * DIGITS]]


def frame_text(frame, font=None):
    """A rough readout of both displays — with *font* ({16-tuple of 0/1:
    char}, from the game's own table) exact, without it a '#' per lit
    digit — for logs and tests."""
    out = []
    for digits in display_rows(decode_frame(frame)):
        chars = []
        for segs in digits:
            pat = tuple(1 if v else 0 for v in segs)
            if not any(pat):
                chars.append(" ")
            elif font and pat in font:
                chars.append(font[pat])
            else:
                chars.append("#")
        out.append("".join(chars))
    return out


def write_font_json(elf_path, out_path, table_vaddr=0xb3160):
    """Write ``{segment-pattern: char}`` as JSON for the app's display window.

    The window decodes segments to CHARACTERS, and the authority for which
    pattern is which character is the game's own font table — but that lives
    in a 1 MB ELF the window would have to read over the UNC path every time.
    So the rig dumps it once at startup (96 entries, ~3 KB) beside the run
    dir's other small state files.  Pattern keys are 16 chars of '0'/'1', bit
    order as decode_frame returns them."""
    import json
    import os
    font = load_font(elf_path, table_vaddr)
    doc = {"".join(str(b) for b in pat): ch for pat, ch in font.items()}
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=0, sort_keys=True)
    os.replace(tmp, out_path)
    return len(doc)


def load_font(elf_path, table_vaddr=0xb3160):
    """{segment-pattern: char} from the game ELF's own 16-byte-per-character
    font (the alphanumeric build's ``ALPHANUMERIC_DisplayText`` table)."""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from s1elf import _Elf
    with open(elf_path, "rb") as f:
        elf = _Elf(f.read())
    font = {}
    for c in range(0x20, 0x80):
        row = elf.read_vaddr(table_vaddr + c * 16, 16)
        font.setdefault(tuple(1 if b else 0 for b in row), chr(c))
    return font


def render_image(rows, scale=6, gap=2):
    """PIL image of both displays: 2 rows of 8 glyphs, amber on black, each
    segment drawn at its level's brightness."""
    from PIL import Image, ImageDraw
    cell_w, cell_h = 4 * scale + 3 * gap, 6 * scale + 3 * gap
    pad = scale
    width = DIGITS * cell_w + (DIGITS + 1) * pad
    height = DISPLAYS * cell_h + (DISPLAYS + 1) * pad * 2
    img = Image.new("RGB", (width, height), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    thick = max(2, scale // 2)
    for di, digits in enumerate(display_rows(rows)):
        oy = pad * 2 + di * (cell_h + pad * 2)
        for k, segs in enumerate(digits):
            ox = pad + k * (cell_w + pad)
            for seg, ((x0, y0), (x1, y1)) in _SEG_LINES.items():
                lvl = segs[seg] if seg < len(segs) else 0
                c = (255 * lvl // 15, 150 * lvl // 15, 0) if lvl else (28, 20, 8)
                dr.line([(ox + x0 * scale + gap, oy + y0 * scale + gap),
                         (ox + x1 * scale + gap, oy + y1 * scale + gap)],
                        fill=c, width=thick)
    return img


def iter_frames(data):
    for i in range(len(data) // FRAME_BYTES):
        yield i, data[i * FRAME_BYTES:(i + 1) * FRAME_BYTES]


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["--font"]:          # --font <game-elf> <out.json>
        print("%d font entries -> %s"
              % (write_font_json(sys.argv[2], sys.argv[3]), sys.argv[3]))
        sys.exit(0)
    data = open(sys.argv[1], "rb").read()
    font = load_font(sys.argv[2]) if len(sys.argv) > 2 else None
    last = None
    for i, fr in iter_frames(data):
        t = frame_text(fr, font)
        if t != last:
            print("%6d  [%s] [%s]" % (i, t[0], t[1]))
            last = t
