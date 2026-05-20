"""WPC ROM static decoder for Williams pinball DMD assets.

Ported from `permartinson/wpcedit.js`_ (TypeScript port of Garrett Lee's
original WPC Edit, MIT-equivalent ISC license).  WPC Edit reverse-engineered
the layouts that real WPC-era Williams games use to store DMD content in
their game ROMs.  This module is a Python re-implementation of the same
algorithms so we can extract assets directly without needing Node.js.

ROM layout
==========

WPC game ROMs are 256 KB, 512 KB, or 1 MB and divide into 16 KB pages:

  - the top two pages (the last 32 KB) are *non-paged*: they live
    permanently at addresses ``0x8000-0xFFFF`` in the 6809's address
    space.  Reset vectors + the master tables of pointers live here.
  - every other page is *paged*: it gets banked into ``0x4000-0x7FFF``
    by writing its page number to a WPC ASIC register.

DMD assets live in paged pages.  The game code in the non-paged area
holds three master tables (Font, Graphics, Animation), each indexed by
a 6809 instruction sequence that loads the right page + offset.  Our
job is:

  1. Find those master tables by signature-scanning the ROM for the
     known 6809 instruction pattern.
  2. Walk each table to enumerate image indices and ROM offsets.
  3. Decode the compressed image data at each offset (RLE + XOR
     deltas + multi-plane masks) into a 128x32 framebuffer.

This file currently covers stage 1 (table discovery).  Stages 2-3 are
the next milestones.

.. _permartinson/wpcedit.js: https://github.com/permartinson/wpcedit.js
"""

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Constants — direct port of wpcedit.js/src/resources/Constants.ts
# ---------------------------------------------------------------------------

# DMD physical dimensions
DMD_ROWS = 32
DMD_COLS = 128
DMD_PAGE_BYTES = 512  # (DMD_ROWS * DMD_COLS) / 8 — one 1-bit plane

# ROM banking
PAGE_LENGTH = 0x4000               # 16 KB per banked page
BASE_CODE_ADDR_PAGED = 0x4000      # banked pages map here
BASE_CODE_ADDR_NONPAGED = 0x8000   # non-paged area starts here
NONPAGED_LENGTH = 0x8000           # 32 KB non-paged area (last 2 pages)
NONPAGED_BANK_INDICATOR = 0xFF     # "page" byte for non-paged addresses

IMAGE_SHIFT_X_PIXEL = 8
IMAGE_SHIFT_Y_PIXEL = 8

CHECKSUM_OFFSET = 0xFFEE - 0x8000  # offset within non-paged area
DELTA_OFFSET = 0xFFEC - 0x8000

VALID_ENCODINGS = (0x00, 0x01, 0x02, 0x03, 0x04, 0x05,
                   0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF)

# Image encoding type bytes
IMAGE_MONOCHROME = 0x00
IMAGE_FD = 0xFD                    # IJ-specific oddity — treat as mono
IMAGE_BICOLOR_INDIRECT = 0xFE      # one plane inline + pointer to other
IMAGE_BICOLOR_DIRECT = 0xFF        # both planes inline

# Master-table types
DATA_GRAPHICS = 1     # full-frame 128x32 splashes
DATA_FONT = 2         # font glyph tables (variable-sized)
DATA_ANIMATION = 3    # animation sequences (variable-sized)


# ---------------------------------------------------------------------------
# Lightweight ROM wrapper
# ---------------------------------------------------------------------------

class WpcRom:
    """A loaded WPC game ROM with bank metadata.

    Construct with the raw bytes (read from the game-ROM file inside
    a MAME zip).  Methods are deliberately small to mirror the
    wpcedit.js API surface.
    """

    def __init__(self, data: bytes):
        size = len(data)
        if size not in (0x40000, 0x80000, 0x100000):
            raise ValueError(
                f"Not a WPC game ROM (size={size}, expected 256K/512K/1M)")
        self.data = data
        self.size = size
        # Each page is 16 KB; total_pages counts both paged and non-paged
        # (the non-paged area = the last 2 pages).
        self.total_pages = (size + PAGE_LENGTH - 1) // PAGE_LENGTH
        # The first byte of the ROM is the base page index that the
        # game's bank-switching code expects to see when page=basePage.
        self.base_page_index = data[0] & 0xFF

    def byte_at(self, addr: int) -> int:
        if not (0 <= addr < self.size):
            raise IndexError(f"ROM address out of range: 0x{addr:X}")
        return self.data[addr] & 0xFF

    def word_at_be(self, addr: int) -> int:
        """Read a big-endian 16-bit word at *addr*."""
        return (self.byte_at(addr) << 8) | self.byte_at(addr + 1)


# ---------------------------------------------------------------------------
# Address conversion: (WPC address, page) <-> ROM byte offset
# ---------------------------------------------------------------------------

def rom_addr_from_wpc(rom: WpcRom, wpc_addr: int, page: int) -> Optional[int]:
    """Convert a WPC (addr, page) pair to a byte offset into the ROM image.

    Returns None if the pair doesn't decode to a valid ROM location.
    """
    in_nonpaged = (BASE_CODE_ADDR_NONPAGED <= wpc_addr
                   < BASE_CODE_ADDR_NONPAGED + NONPAGED_LENGTH)
    if in_nonpaged:
        # Some opcodes/tables leave the page byte at something other
        # than the non-paged sentinel; the wpcedit.js code force-
        # corrects it here.  We do the same.
        if page != NONPAGED_BANK_INDICATOR:
            page = NONPAGED_BANK_INDICATOR
        rom_off = ((rom.total_pages - 2) * PAGE_LENGTH
                   + (wpc_addr - BASE_CODE_ADDR_NONPAGED))
    elif (rom.base_page_index <= page < rom.base_page_index + rom.total_pages - 2
          and BASE_CODE_ADDR_PAGED <= wpc_addr < BASE_CODE_ADDR_NONPAGED):
        rom_off = ((page - rom.base_page_index) * PAGE_LENGTH
                   + (wpc_addr - BASE_CODE_ADDR_PAGED))
    else:
        return None
    if rom_off >= rom.size:
        return None
    return rom_off


def extract_wpc_addr_page(rom: WpcRom, src: int) -> Optional[tuple]:
    """Read a 3-byte WPC pointer (addr_hi, addr_lo, page) at ROM offset *src*.

    Returns (wpc_addr, page) or None if the pair doesn't validate.
    """
    wpc_addr = rom.word_at_be(src)
    page = rom.byte_at(src + 2)
    in_nonpaged = (BASE_CODE_ADDR_NONPAGED <= wpc_addr
                   < BASE_CODE_ADDR_NONPAGED + NONPAGED_LENGTH)
    if in_nonpaged and page != NONPAGED_BANK_INDICATOR:
        page = NONPAGED_BANK_INDICATOR
    in_paged = (BASE_CODE_ADDR_PAGED <= wpc_addr
                < BASE_CODE_ADDR_PAGED + PAGE_LENGTH)
    if not (in_paged or in_nonpaged):
        return None
    valid_page = (rom.base_page_index <= page
                  < rom.base_page_index + rom.total_pages
                  or page == NONPAGED_BANK_INDICATOR)
    if not valid_page:
        return None
    return wpc_addr, page


# ---------------------------------------------------------------------------
# Table discovery — port of DataParser.initTableAddrs()
# ---------------------------------------------------------------------------

@dataclass
class TableAddresses:
    """ROM offsets of the three master tables.

    Each address points at the *3-byte WPC pointer* in the non-paged
    code area; dereference via :func:`rom_addr_from_wpc` to get the
    actual table data offset.
    """
    font_ptr_rom: Optional[int] = None
    graphics_ptr_rom: Optional[int] = None
    animation_ptr_rom: Optional[int] = None


def find_table_addresses(rom: WpcRom) -> TableAddresses:
    """Locate the Font / Graphics / Animation master-table pointers.

    Strategy mirrors wpcedit.js:

      Scan the ROM byte stream for the 6809 instruction signature
      that loads the Font Table pointer:

        BE xx xx 3A 58 3A D6 yy 34 04 [F6|BD] zz zz [BD|F6] ww ww

      The two bytes ``xx xx`` after ``BE`` (LDX immediate) are the
      WPC address of the Font Table pointer in non-paged ROM.  Once
      we resolve that to a ROM offset, the Graphics and Animation
      pointers are typically the next 3-byte WPC pointers in the same
      area (some ROMs use a 2-byte form when targeting non-paged).

    After locating the pointers, we validate ``rom.base_page_index``
    against the page bytes they hold.  wpcedit.js's "data[0] is the
    basePage" heuristic is right for many WPC games but wrong for
    others (e.g. AFM, where ``data[0] = 0x31`` is a 6809 instruction
    byte, not the true basePage of 0x20).  We brute-force a few
    candidate basePages and pick the one where the most master-
    table pointers resolve.

    Returns a :class:`TableAddresses` — fields are None if the
    signature didn't match (no table found).
    """
    result = TableAddresses()

    end = rom.size - 16
    data = rom.data
    for ptr in range(0, end):
        if data[ptr] != 0xBE:
            continue
        # match the rest of the instruction signature
        if (data[ptr + 3] == 0x3A
                and data[ptr + 4] == 0x58
                and data[ptr + 5] == 0x3A
                and data[ptr + 6] == 0xD6
                and data[ptr + 8] == 0x34
                and data[ptr + 9] == 0x04
                and data[ptr + 10] in (0xF6, 0xBD)
                and data[ptr + 13] in (0xBD, 0xF6)):
            # Bytes ptr+1, ptr+2 hold the WPC address of the Font
            # Table pointer in non-paged ROM.  Convert to a ROM
            # offset.
            wpc_addr = (data[ptr + 1] << 8) | data[ptr + 2]
            font_ptr_rom = rom_addr_from_wpc(
                rom, wpc_addr, NONPAGED_BANK_INDICATOR)
            if font_ptr_rom is None:
                continue
            result.font_ptr_rom = font_ptr_rom

            # Walk forward to find Graphics + Animation pointer offsets.
            graphics_ptr_rom = _next_table_ptr(rom, font_ptr_rom)
            result.graphics_ptr_rom = graphics_ptr_rom
            if graphics_ptr_rom is not None:
                anim_ptr_rom = _next_table_ptr(rom, graphics_ptr_rom)
                result.animation_ptr_rom = anim_ptr_rom

            # Validate basePage by checking how many pointers resolve
            # to valid ROM offsets.  Try a few candidates and pick the
            # winner.  This rescues games (AFM, etc.) whose data[0]
            # heuristic is misleading.
            _correct_base_page(rom, result)
            return result
    return result


def _correct_base_page(rom: WpcRom, tables: "TableAddresses") -> None:
    """Adjust ``rom.base_page_index`` so the table pointers resolve.

    Reads the page byte from each of the three master-table pointers,
    then tries candidate basePages from {data[0], 0, 0x20, 0x40, 0x60,
    and the minimum of the observed page bytes}.  The basePage that
    makes the most pointers resolve wins.  Falls back to the original
    ``data[0]`` value if no candidate is strictly better.
    """
    ptrs = [tables.font_ptr_rom, tables.graphics_ptr_rom,
            tables.animation_ptr_rom]
    ptrs = [p for p in ptrs if p is not None]
    # Read the (addr, page) bytes from each pointer.
    raw = []
    for p in ptrs:
        if p + 2 >= rom.size:
            continue
        addr = rom.word_at_be(p)
        page = rom.byte_at(p + 2)
        raw.append((addr, page))
    if not raw:
        return
    candidates = [rom.base_page_index, 0x00, 0x20, 0x40, 0x60]
    # Also try the smallest observed page byte that's a plausible page
    # number (i.e. < total_pages).
    seen_pages = sorted(set(p for _, p in raw if p < rom.total_pages))
    if seen_pages:
        candidates.append(seen_pages[0])
    best_base = rom.base_page_index
    best_score = -1
    for cand in candidates:
        if cand < 0 or cand > 0xFF:
            continue
        score = 0
        for addr, page in raw:
            # Re-run rom_addr_from_wpc with the candidate basePage.
            in_paged = (BASE_CODE_ADDR_PAGED <= addr
                        < BASE_CODE_ADDR_NONPAGED)
            valid_page = (cand <= page < cand + rom.total_pages - 2)
            if in_paged and valid_page:
                score += 1
        if score > best_score:
            best_score = score
            best_base = cand
    if best_base != rom.base_page_index:
        rom.base_page_index = best_base


def _next_table_ptr(rom: WpcRom, current_ptr_rom: int) -> Optional[int]:
    """Given a ROM offset pointing at a 3-byte WPC table pointer,
    return the ROM offset of the *next* table pointer in the same
    area.  Some ROMs use a 2-byte short form when the targeted address
    is in non-paged ROM; this helper handles both."""
    wpc_addr = rom.word_at_be(current_ptr_rom)
    page = rom.byte_at(current_ptr_rom + 2)
    in_nonpaged = (BASE_CODE_ADDR_NONPAGED <= wpc_addr
                   < BASE_CODE_ADDR_NONPAGED + NONPAGED_LENGTH)
    if in_nonpaged and page != NONPAGED_BANK_INDICATOR:
        # 2-byte short form — page byte is actually the start of the
        # next pointer's address.
        return current_ptr_rom + 2
    return current_ptr_rom + 3


def resolve_table_ptr(rom: WpcRom, ptr_rom: int) -> Optional[int]:
    """Dereference a 3-byte WPC pointer at *ptr_rom* to the actual
    ROM offset where the table data lives.

    Mirrors wpcedit.js ``getROMAddressFromAddrOf3ByteWPCAddrPage``.
    """
    result = extract_wpc_addr_page(rom, ptr_rom)
    if result is None:
        return None
    wpc_addr, page = result
    return rom_addr_from_wpc(rom, wpc_addr, page)


# ---------------------------------------------------------------------------
# FullFrameImage decoding — port of DmdDecoder.decodeImageToPlane +
# decodeFullFrameGraphicImage + decode_00
# ---------------------------------------------------------------------------

# Plane status codes — port of PlaneStatuses
PLANE_VALID = 0
PLANE_INVALID = 1
PLANE_UNKNOWN = 2
PLANE_UNIMPLEMENTED = 3
PLANE_TABLE_ENTRY_OOR = 4
PLANE_BAD_DIMENSION = 5
PLANE_IMAGE_OOR = 6


@dataclass
class DmdPlane:
    """One decoded 1-bit plane (128x32) of an image.

    ``data`` is exactly 512 bytes when ``status == PLANE_VALID``.
    ``encoding`` is the 0x00-0x0F encoding nibble from the image
    header byte (255 = uninitialised, not the same as ImageCodes.* ).
    """
    address: int = 0           # ROM offset where the encoded image starts
    table_address: int = 0     # ROM offset of the table this came from
    status: int = PLANE_VALID
    encoding: int = 255
    data: bytes = b""
    # XOR/mask metadata for the more complex encodings — empty for
    # decode_00.  These are 512-byte buffers when populated.
    skipped: bytes = b""
    xor_flags: bytes = b""
    xor_bits: bytes = b""


def decode_image_to_plane(rom: WpcRom, graphics_table_rom: int,
                          index: int) -> DmdPlane:
    """Decode the plane at ``graphics_table_rom[index]``.

    Each graphics-table entry is a 3-byte WPC pointer; resolving it
    gives the ROM offset of the image's encoded bytes, whose first
    byte is the encoding type.
    """
    plane = DmdPlane(table_address=graphics_table_rom)
    entry_off = graphics_table_rom + index * 3
    if entry_off >= rom.size:
        plane.status = PLANE_TABLE_ENTRY_OOR
        return plane
    image_off = resolve_table_ptr(rom, entry_off)
    if image_off is None or image_off >= rom.size:
        plane.status = PLANE_TABLE_ENTRY_OOR
        return plane
    plane.address = image_off
    return decode_full_frame_image(rom, image_off, plane)


def decode_full_frame_image(rom: WpcRom, source: int,
                            plane: DmdPlane) -> DmdPlane:
    """Decode the bytes at *source* into *plane*.

    The first byte's low nibble is the encoding type (0x00-0x0B).
    Only 0x00 is implemented in this milestone; everything else
    returns ``status=PLANE_UNIMPLEMENTED`` so the iteration loop can
    classify ROM content and we'll know which decoders to add next.
    """
    if source >= rom.size:
        plane.status = PLANE_IMAGE_OOR
        return plane
    enc_byte = rom.byte_at(source)
    plane.encoding = enc_byte & 0x0F
    source += 1
    if source >= rom.size:
        plane.status = PLANE_IMAGE_OOR
        return plane
    enc = plane.encoding
    if enc == 0x00:
        plane.data = _decode_00(rom, source)
        plane.status = PLANE_VALID
    elif enc == 0x01:
        plane.data = _decode_01or02(rom, source, WRITE_COLUMNS)
        plane.status = PLANE_VALID
    elif enc == 0x02:
        plane.data = _decode_01or02(rom, source, WRITE_ROWS)
        plane.status = PLANE_VALID
    elif enc == 0x04:
        plane.data = _decode_04or05(rom, source, WRITE_COLUMNS)
        plane.status = PLANE_VALID
    elif enc == 0x05:
        plane.data = _decode_04or05(rom, source, WRITE_ROWS)
        plane.status = PLANE_VALID
    elif enc == 0x06:
        d, f, b = _decode_06or07(rom, source, WRITE_COLUMNS)
        plane.data, plane.xor_flags, plane.xor_bits = d, f, b
        plane.status = PLANE_VALID
    elif enc == 0x07:
        d, f, b = _decode_06or07(rom, source, WRITE_ROWS)
        plane.data, plane.xor_flags, plane.xor_bits = d, f, b
        plane.status = PLANE_VALID
    elif enc == 0x08:
        d, s = _decode_08or09(rom, source, WRITE_COLUMNS)
        plane.data, plane.skipped = d, s
        plane.status = PLANE_VALID
    elif enc == 0x09:
        d, s = _decode_08or09(rom, source, WRITE_ROWS)
        plane.data, plane.skipped = d, s
        plane.status = PLANE_VALID
    elif enc == 0x0A:
        d, s = _decode_0Aor0B(rom, source, WRITE_COLUMNS)
        plane.data, plane.skipped = d, s
        plane.status = PLANE_VALID
    elif enc == 0x0B:
        d, s = _decode_0Aor0B(rom, source, WRITE_ROWS)
        plane.data, plane.skipped = d, s
        plane.status = PLANE_VALID
    else:
        plane.status = PLANE_UNIMPLEMENTED
    return plane


def _decode_00(rom: WpcRom, source: int) -> bytes:
    """Encoding 0x00 — raw 512-byte plane copy, no compression."""
    end = min(source + DMD_PAGE_BYTES, rom.size)
    out = bytearray(rom.data[source:end])
    if len(out) < DMD_PAGE_BYTES:
        out.extend(b"\x00" * (DMD_PAGE_BYTES - len(out)))
    return bytes(out)


# ---------------------------------------------------------------------------
# Write-direction state machine — shared by all decoders.
# Mirrors DmdDecoder.writeNext8BitValueAnySize.
# ---------------------------------------------------------------------------

WRITE_COLUMNS = 0  # walk down a column, then jump to top of next column
WRITE_ROWS = 1     # plain sequential

# DMD layout: 16 bytes per row, 32 rows.  When we've finished writing
# a column (32 bytes), the next byte should land at the top of the
# adjacent column — that's a step of (16*30 + 15) = 495 backwards
# from the byte we just wrote at the bottom of the previous column.
# Within a column, the next byte is +16 (one row down).
_COLS_BYTES = DMD_COLS // 8                      # 16
_COL_END_RESET = _COLS_BYTES * (DMD_ROWS - 2) + (_COLS_BYTES - 1)   # 495
_COL_INNER_STEP = _COLS_BYTES                    # 16


class _Writer:
    """Tracks write position into a 512-byte DMD plane buffer.

    The encoders all share the same write-counter / write-pointer
    update rules — we centralise them here so the per-encoding
    routines below stay readable.
    """

    __slots__ = ("dest", "ptr", "count")

    def __init__(self):
        self.dest = bytearray(DMD_PAGE_BYTES)
        self.ptr = 0
        self.count = 0

    @property
    def done(self) -> bool:
        return self.count >= DMD_PAGE_BYTES

    def write(self, value: int, mode: int):
        """Write *value* and advance the pointer per *mode*."""
        if self.count >= DMD_PAGE_BYTES:
            return
        self.dest[self.ptr] = value & 0xFF
        self.count += 1
        if self.count >= DMD_PAGE_BYTES:
            return
        if mode == WRITE_ROWS:
            self.ptr += 1
            return
        # WRITE_COLUMNS
        if self.count % DMD_ROWS == 0:
            # finished one column — jump to top of next column
            self.ptr -= _COL_END_RESET
        else:
            self.ptr += _COL_INNER_STEP


# ---------------------------------------------------------------------------
# Bit-stream reader for the header-driven encodings (04/05, 0A/0B).
# Mirrors readNextBit + readNext8BitValue.
# ---------------------------------------------------------------------------

class _BitReader:
    """MSB-first bit reader over ROM bytes with a Huffman-ish escape.

    Each ``read_next_8bit_value()`` call returns either a literal byte
    (one leading 0 bit + 8 data bits) or a header ``RepeatBytes[]``
    entry (one leading 1 + up-to-7 more 1s; the count of consecutive
    1s after the lead indexes into ``RepeatBytes``).
    """

    __slots__ = ("rom", "src", "mask", "repeat_bytes", "special_flag")

    def __init__(self, rom: WpcRom, src: int, special_flag: int,
                 repeat_bytes):
        self.rom = rom
        self.src = src
        self.mask = 0x80
        self.repeat_bytes = list(repeat_bytes)  # length 8
        self.special_flag = special_flag

    def _read_bit(self) -> int:
        if self.src >= self.rom.size:
            return 0
        bit = self.rom.data[self.src] & self.mask
        self.mask >>= 1
        if self.mask == 0:
            self.mask = 0x80
            self.src += 1
        return bit

    def read_byte(self) -> int:
        """Return the next encoded byte (literal or repeat-bytes lookup)."""
        if self.src >= self.rom.size:
            return 0
        first = self._read_bit()
        if first:
            ones = 0
            for _ in range(7):
                if self.src >= self.rom.size:
                    return 0
                b = self._read_bit()
                if b:
                    ones += 1
                else:
                    break
            return self.repeat_bytes[ones]
        # literal: read 8 MSB-first bits
        value = 0
        write_mask = 0x80
        for _ in range(8):
            if self.src >= self.rom.size:
                return 0
            if self._read_bit():
                value |= write_mask
            write_mask >>= 1
        return value


# ---------------------------------------------------------------------------
# Encodings 0x01 / 0x02 — Simple Repeats (columns/rows)
# ---------------------------------------------------------------------------

def _decode_01or02(rom: WpcRom, source: int, mode: int) -> bytes:
    """Simple-repeats: stream of literal bytes with a single escape.

    Format: [SpecialFlagByte] then bytes.  Each byte is written as-is
    unless it equals SpecialFlagByte, in which case the next two
    bytes are ``[count, value]`` and ``value`` is written ``count``
    times.
    """
    if source >= rom.size:
        return bytes(DMD_PAGE_BYTES)
    special = rom.byte_at(source)
    source += 1
    w = _Writer()
    while not w.done and source < rom.size:
        ch = rom.byte_at(source)
        source += 1
        if ch == special:
            if source >= rom.size:
                break
            count = rom.byte_at(source); source += 1
            if source >= rom.size:
                break
            value = rom.byte_at(source); source += 1
            for _ in range(max(1, count)):
                if w.done:
                    break
                w.write(value, mode)
        else:
            w.write(ch, mode)
    return bytes(w.dest)


# ---------------------------------------------------------------------------
# Encodings 0x04 / 0x05 — Complex Repeats (9-byte header, columns/rows)
# ---------------------------------------------------------------------------

def _decode_04or05(rom: WpcRom, source: int, mode: int) -> bytes:
    """Header-based encoding: 1 byte SpecialFlag + 8 RepeatBytes, then
    a bit stream where each ``read_byte`` either produces a literal
    or indexes into RepeatBytes.  When the produced byte matches the
    SpecialFlag, two more bytes are read as ``[count, value]`` and
    ``value`` is written ``count`` times.
    """
    if source + 9 >= rom.size:
        return bytes(DMD_PAGE_BYTES)
    special = rom.byte_at(source); source += 1
    repeat_bytes = [rom.byte_at(source + i) for i in range(8)]
    source += 8
    br = _BitReader(rom, source, special, repeat_bytes)
    w = _Writer()
    while not w.done and br.src < rom.size:
        ch = br.read_byte()
        if br.src >= rom.size:
            break
        if ch == special:
            count = br.read_byte()
            if br.src >= rom.size:
                break
            value = br.read_byte()
            for _ in range(max(1, count)):
                if w.done:
                    break
                w.write(value, mode)
        else:
            w.write(ch, mode)
    return bytes(w.dest)


# ---------------------------------------------------------------------------
# Encodings 0x06 / 0x07 — XOR-Repeat (columns/rows)
# ---------------------------------------------------------------------------

def _decode_06or07(rom: WpcRom, source: int, mode: int):
    """XOR variant of 01/02.  Literal bytes go straight to ``data``;
    matches against SpecialFlag emit zeros into ``data`` plus an XOR
    overlay (count repetitions of value) in ``xor_bits`` with the
    matching positions flagged ``0xFF`` in ``xor_flags``.

    Returns (data, xor_flags, xor_bits) — three 512-byte arrays.
    """
    if source >= rom.size:
        return bytes(DMD_PAGE_BYTES), bytes(DMD_PAGE_BYTES), bytes(DMD_PAGE_BYTES)
    special = rom.byte_at(source); source += 1
    w_data = _Writer()
    w_flags = _Writer()
    w_bits = _Writer()
    while not w_data.done and source < rom.size:
        ch = rom.byte_at(source); source += 1
        if ch == special:
            if source >= rom.size:
                break
            count = rom.byte_at(source); source += 1
            if source >= rom.size:
                break
            value = rom.byte_at(source); source += 1
            for _ in range(max(1, count)):
                if w_data.done:
                    break
                w_data.write(0x00, mode)
                w_flags.write(0xFF, mode)
                w_bits.write(value, mode)
        else:
            w_data.write(ch, mode)
            w_flags.write(0x00, mode)
            w_bits.write(0x00, mode)
    return bytes(w_data.dest), bytes(w_flags.dest), bytes(w_bits.dest)


# ---------------------------------------------------------------------------
# Encodings 0x08 / 0x09 — Bulk Skips and Bulk Repeats (columns/rows)
# ---------------------------------------------------------------------------

def _decode_08or09(rom: WpcRom, source: int, mode: int):
    """Alternates between two phases:

      1. *Pattern phase* — read ``count``; if non-zero, read that
         many literal data bytes and write each (one-shot, NOT
         repeated — the original docs were wrong about this).
      2. *Skip phase* — read ``count``; write ``count`` zeros into
         ``data`` with ``0xFF`` in ``skipped`` (those positions
         shouldn't paint over the underlying display).

    Starts in skip phase if the very first byte is zero.

    Returns (data, skipped).
    """
    if source >= rom.size:
        return bytes(DMD_PAGE_BYTES), bytes(DMD_PAGE_BYTES)
    w_data = _Writer()
    w_skip = _Writer()

    def _skip_phase(src):
        if src >= rom.size:
            return src
        count = rom.byte_at(src); src += 1
        for _ in range(count):
            if w_data.done:
                break
            w_data.write(0x00, mode)
            w_skip.write(0xFF, mode)
        return src

    # First byte tells us whether to start with patterns or skips.
    first = rom.byte_at(source); source += 1
    if first == 0:
        source = _skip_phase(source)
    while not w_data.done and source < rom.size:
        count = rom.byte_at(source); source += 1
        if count:
            for _ in range(count):
                if source >= rom.size or w_data.done:
                    break
                value = rom.byte_at(source); source += 1
                w_data.write(value, mode)
                w_skip.write(0x00, mode)
        if w_data.done:
            break
        source = _skip_phase(source)
    return bytes(w_data.dest), bytes(w_skip.dest)


# ---------------------------------------------------------------------------
# Encodings 0x0A / 0x0B — Write-Data-or-Multiple-Skips (columns/rows)
# Same shape as 08/09 but the literal bytes go through the bit-reader.
# ---------------------------------------------------------------------------

def _decode_0Aor0B(rom: WpcRom, source: int, mode: int):
    if source + 8 >= rom.size:
        return bytes(DMD_PAGE_BYTES), bytes(DMD_PAGE_BYTES)
    repeat_bytes = [rom.byte_at(source + i) for i in range(8)]
    source += 8
    br = _BitReader(rom, source, 0, repeat_bytes)
    w_data = _Writer()
    w_skip = _Writer()

    def _skip_phase():
        count = br.read_byte()
        if br.src >= rom.size:
            return
        for _ in range(count):
            if w_data.done:
                break
            w_data.write(0x00, mode)
            w_skip.write(0xFF, mode)

    first = br.read_byte()
    if br.src >= rom.size:
        return bytes(w_data.dest), bytes(w_skip.dest)
    if first == 0:
        _skip_phase()
    while not w_data.done and br.src < rom.size:
        count = br.read_byte()
        if br.src >= rom.size:
            break
        if count:
            for _ in range(count):
                if w_data.done or br.src >= rom.size:
                    break
                value = br.read_byte()
                w_data.write(value, mode)
                w_skip.write(0x00, mode)
        if w_data.done:
            break
        _skip_phase()
    return bytes(w_data.dest), bytes(w_skip.dest)


# ---------------------------------------------------------------------------
# Variable-sized image / animation tables — port of
# DataParser.getROMAddressOfVariableSizedImageTable +
# getROMAddressOfVariableSizedImageIndex + getVariableSizedImageTableMetadata
# and DmdDecoder.decodeVariableSizedImageIndex_*.
#
# A "variable-sized" master table contains pointers to *sub-tables*; each
# sub-table is one animation (or one font face).  The layout is:
#
#   Master table  := [3-byte WPC pointer]* terminated by an invalid ptr.
#                    Each pointer dereferences to a Sub-table.
#
#   Sub-table     := (ImageIndexMin, ImageIndexMax) pairs* + 0x00
#                    + TableHeight (1 byte)
#                    + TableSpacing (1 byte, usually 0x01)
#                    + [2-byte WPC addr per image]*
#                    The min/max pairs define a sparse image-index range
#                    so e.g. {(0,3), (10,12)} means image indices
#                    0,1,2,3,10,11,12 each have a frame.
#
#   Image         := EITHER  width-byte + bitmap-rows       (no-header)
#                    OR      0x00|0xFD|0xFE|0xFF + Vy + Vx + H + W
#                              + bitmap-rows               (header form)
#                    Bitmap-rows are raw 1-bit pixel data,
#                    ceil(width/8) bytes per row, height rows.
# ---------------------------------------------------------------------------


@dataclass
class VsiSubTable:
    """One sub-table inside a variable-sized master table.

    For the Animation master table, one sub-table == one animation;
    ``frame_indices`` is the ordered list of image indices belonging
    to the animation (filtered through the min/max pairs).
    """
    sub_table_idx: int
    rom_offset: int          # ROM offset where the sub-table starts
    sub_table_page: int      # the WPC page this sub-table lives in
    frame_indices: list      # list[int]
    table_height: int
    table_spacing: int


@dataclass
class VsiFrame:
    """One decoded frame from a variable-sized image table.

    ``data`` is the LOW plane — a packed 1-bit bitmap with
    ``ceil(width/8) * height`` bytes, LSB-first within each byte.

    ``data_high`` is the HIGH plane *if* this frame came from a
    BicolorDirect (0xFF) header — in that case both planes are
    stored inline immediately after the 5-byte header, and the
    pair forms one 4-shade displayable frame (``low + 2*high`` per
    pixel gives brightness levels 0..3).  For Monochrome (0x00)
    frames ``data_high`` is ``None``.

    ``v_off`` and ``h_off`` place the bitmap within the full 128x32
    display when rendering an animation; for no-header frames
    they're 0.
    """
    image_idx: int
    width: int
    height: int
    h_off: int
    v_off: int
    data: bytes
    data_high: bytes = None  # type: ignore[assignment]
    valid: bool = True


def _vsi_sub_table_addr(rom: WpcRom, master_table_rom: int,
                        sub_idx: int):
    """Resolve sub-table *sub_idx* of the master table to (rom_off, page).

    Each master-table entry is a 3-byte WPC pointer.
    """
    entry = master_table_rom + sub_idx * 3
    if entry + 2 >= rom.size:
        return None, None
    wpc_addr = rom.word_at_be(entry)
    page = rom.byte_at(entry + 2)
    # wpcedit.js handles a "double-dereference" case where the
    # pointer points at another in-page pointer — port that fixup.
    rom_off = rom_addr_from_wpc(rom, wpc_addr, page)
    if rom_off is None or rom_off >= rom.size:
        return None, None
    # peek at the dereferenced bytes for the in-page fixup
    if rom_off + 2 < rom.size:
        temp_addr = rom.word_at_be(rom_off)
        if BASE_CODE_ADDR_PAGED <= temp_addr < BASE_CODE_ADDR_PAGED + PAGE_LENGTH:
            wpc_addr = temp_addr
            rom_off = rom_addr_from_wpc(rom, wpc_addr, page)
            if rom_off is None or rom_off >= rom.size:
                return None, None
    return rom_off, page


def _vsi_walk_sub_table(rom: WpcRom, sub_table_rom: int):
    """Walk one sub-table's min/max header.

    Returns (frame_indices, table_height, table_spacing, image_ptrs_off)
    where ``image_ptrs_off`` is the ROM offset of the first 2-byte
    image pointer (right after TableSpacing), and ``frame_indices`` is
    the resolved per-image index list.
    Returns ``(None, None, None, None)`` if the sub-table looks
    malformed.
    """
    ptr = sub_table_rom
    frame_indices = []
    safety = 0
    while ptr < rom.size and rom.byte_at(ptr) != 0x00:
        if safety > 256:
            return None, None, None, None
        safety += 1
        if ptr + 1 >= rom.size:
            return None, None, None, None
        idx_min = rom.byte_at(ptr); ptr += 1
        idx_max = rom.byte_at(ptr); ptr += 1
        if idx_min > idx_max:
            return None, None, None, None
        for i in range(idx_min, idx_max + 1):
            frame_indices.append(i)
    if ptr >= rom.size:
        return None, None, None, None
    ptr += 1  # skip terminating 0x00
    if ptr + 1 >= rom.size:
        return None, None, None, None
    table_height = rom.byte_at(ptr); ptr += 1
    table_spacing = rom.byte_at(ptr); ptr += 1
    return frame_indices, table_height, table_spacing, ptr


def enumerate_sub_tables(rom: WpcRom, master_table_rom: int,
                         max_tables: int = 256):
    """Walk a variable-sized master table and return its sub-tables.

    Stops as soon as a sub-table fails to decode (the usual signal
    we've walked past the end).
    """
    out = []
    for sub_idx in range(max_tables):
        rom_off, page = _vsi_sub_table_addr(rom, master_table_rom, sub_idx)
        if rom_off is None:
            break
        frame_indices, h, s, _ = _vsi_walk_sub_table(rom, rom_off)
        if frame_indices is None or not frame_indices:
            break
        out.append(VsiSubTable(
            sub_table_idx=sub_idx, rom_offset=rom_off,
            sub_table_page=page,
            frame_indices=frame_indices,
            table_height=h, table_spacing=s,
        ))
    return out


def _resolve_vsi_image_addr(rom: WpcRom, sub: VsiSubTable,
                            image_idx: int):
    """Resolve the ROM offset of ``image_idx`` within sub-table *sub*.

    The image-pointer array starts right after TableHeight + TableSpacing;
    each pointer is a 2-byte WPC address (the page comes from the sub-
    table itself).  We have to count how many real images precede this
    one in the min/max-pair listing (image_idx isn't necessarily its
    array position).
    """
    ptr = sub.rom_offset
    image_num = 0
    found = False
    safety = 0
    while ptr < rom.size and rom.byte_at(ptr) != 0x00:
        if safety > 256:
            return None
        safety += 1
        idx_min = rom.byte_at(ptr); ptr += 1
        idx_max = rom.byte_at(ptr); ptr += 1
        if not found:
            cur = idx_min
            while cur <= idx_max:
                if image_idx <= cur:
                    found = True
                    break
                image_num += 1
                cur += 1
    if not found:
        return None
    ptr += 1                  # skip terminating 0x00
    ptr += 2                  # skip TableHeight + TableSpacing
    ptr += image_num * 2      # walk to the right 2-byte pointer
    if ptr + 1 >= rom.size:
        return None
    addr = rom.word_at_be(ptr)
    rom_off = rom_addr_from_wpc(rom, addr, sub.sub_table_page)
    return rom_off


def decode_vsi_frame(rom: WpcRom, sub: VsiSubTable,
                     image_idx: int) -> VsiFrame:
    """Decode one variable-sized frame.

    Returns a :class:`VsiFrame` with ``valid=False`` if anything looks
    off (out-of-range address, bad header byte, truncated bitmap).
    """
    rom_off = _resolve_vsi_image_addr(rom, sub, image_idx)
    if rom_off is None:
        return VsiFrame(image_idx=image_idx, width=0, height=0,
                        h_off=0, v_off=0, data=b"", valid=False)
    if rom_off >= rom.size:
        return VsiFrame(image_idx=image_idx, width=0, height=0,
                        h_off=0, v_off=0, data=b"", valid=False)
    first = rom.byte_at(rom_off)
    # No-header form: first byte is a width in (0, 128].
    # Header form: 0x00, 0xFD, 0xFE, or 0xFF.
    if 1 <= first <= DMD_COLS:
        width = first
        height = sub.table_height
        h_off = 0
        v_off = 0
        data_off = rom_off + 1
    elif first in (0x00, 0xFD, 0xFE, 0xFF):
        if rom_off + 5 >= rom.size:
            return VsiFrame(image_idx=image_idx, width=0, height=0,
                            h_off=0, v_off=0, data=b"", valid=False)
        # Offsets are signed bytes — values 128..255 mean -128..-1.
        # Some sub-tables use 0xFF/0xFE as a "centre" sentinel; we
        # treat that as a negative offset and let the placement code
        # clip — it's the same visual effect for animations that move
        # off-screen at the edges.
        raw_v = rom.byte_at(rom_off + 1)
        raw_h = rom.byte_at(rom_off + 2)
        v_off = raw_v - 256 if raw_v >= 128 else raw_v
        h_off = raw_h - 256 if raw_h >= 128 else raw_h
        height = rom.byte_at(rom_off + 3)
        width = rom.byte_at(rom_off + 4)
        data_off = rom_off + 5
        # BicolorIndirect (0xFE) has a 2-byte address before the
        # bitmap data for the second plane; we don't render the
        # second plane for animations (it's only used for mode
        # transitions), so skip those 2 bytes.
        if first == 0xFE:
            data_off += 2
    else:
        return VsiFrame(image_idx=image_idx, width=0, height=0,
                        h_off=0, v_off=0, data=b"", valid=False)
    if width == 0 or height == 0 or width > 256 or height > 64:
        return VsiFrame(image_idx=image_idx, width=width, height=height,
                        h_off=h_off, v_off=v_off, data=b"", valid=False)
    bytes_per_row = (width + 7) // 8
    total = bytes_per_row * height
    # BicolorDirect (0xFF): both planes stored inline.  We need
    # ``total * 2`` bytes from the data section, not just ``total``.
    bytes_needed = total * 2 if first == 0xFF else total
    if data_off + bytes_needed > rom.size:
        return VsiFrame(image_idx=image_idx, width=width, height=height,
                        h_off=h_off, v_off=v_off, data=b"", valid=False)
    data_low = bytes(rom.data[data_off:data_off + total])
    data_high = None
    if first == 0xFF:
        data_high = bytes(rom.data[data_off + total:data_off + 2 * total])
    return VsiFrame(
        image_idx=image_idx, width=width, height=height,
        h_off=h_off, v_off=v_off,
        data=data_low, data_high=data_high,
        valid=True)


def vsi_frame_to_dmd_buffer(frame: VsiFrame, plane: str = "low") -> bytes:
    """Place one of a VsiFrame's planes into a fresh 128x32 buffer.

    ``plane`` is ``"low"`` (the always-present plane) or ``"high"``
    (the second plane from a BicolorDirect frame).  Asking for the
    high plane of a Monochrome frame returns an all-zero buffer.

    Returns 512 bytes (row-major, 16 bytes/row, LSB-first per byte —
    bit 0 is the leftmost pixel, matching FreeWPC dmd-theory and the
    full-frame plane layout).  Honours signed h_off / v_off offsets.
    """
    out = bytearray(DMD_PAGE_BYTES)
    if not frame.valid or frame.width <= 0 or frame.height <= 0:
        return bytes(out)
    if plane == "high":
        src = frame.data_high
        if src is None:
            return bytes(out)
    else:
        src = frame.data
    src_row_bytes = (frame.width + 7) // 8
    dst_row_bytes = DMD_COLS // 8   # 16
    h_off = frame.h_off
    v_off = frame.v_off
    # Visible source range after clipping
    src_x_start = max(0, -h_off)
    src_y_start = max(0, -v_off)
    src_x_end = min(frame.width, DMD_COLS - h_off)
    src_y_end = min(frame.height, DMD_ROWS - v_off)
    if src_x_start >= src_x_end or src_y_start >= src_y_end:
        return bytes(out)
    for sy in range(src_y_start, src_y_end):
        src_base = sy * src_row_bytes
        dy = sy + v_off
        for sx in range(src_x_start, src_x_end):
            src_byte = src[src_base + (sx // 8)]
            bit = (src_byte >> (sx % 8)) & 1
            if not bit:
                continue
            dx = sx + h_off
            dst_byte_idx = dy * dst_row_bytes + (dx // 8)
            if 0 <= dst_byte_idx < DMD_PAGE_BYTES:
                out[dst_byte_idx] |= 1 << (dx % 8)
    return bytes(out)


def survey_encodings(rom: WpcRom, graphics_table_rom: int,
                     max_index: int = 1000) -> dict:
    """Walk *max_index* image-table entries and tally the encoding byte.

    Returns ``{encoding_nibble: count}``.  Used to size up how much
    decoder work remains before we can render real content.
    """
    counts = {}
    for i in range(max_index):
        plane = decode_image_to_plane(rom, graphics_table_rom, i)
        # PLANE_TABLE_ENTRY_OOR means the table entry didn't decode
        # to a valid ROM offset — that's usually our cue that we've
        # walked past the end of the table.
        if plane.status == PLANE_TABLE_ENTRY_OOR:
            # one bad entry isn't decisive (some games have a few in
            # the middle), but two in a row probably means end-of-table.
            counts.setdefault("oor", 0)
            counts["oor"] += 1
            continue
        key = f"0x{plane.encoding:02X}"
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Small CLI for milestone-1 validation
# ---------------------------------------------------------------------------

def _summarise(rom_path: str) -> str:
    with open(rom_path, "rb") as f:
        data = f.read()
    rom = WpcRom(data)
    tables = find_table_addresses(rom)
    lines = [
        f"ROM: {rom_path}",
        f"  size={rom.size} bytes ({rom.size // 1024} KB), "
        f"pages={rom.total_pages}, basePage=0x{rom.base_page_index:02X}",
    ]
    if tables.font_ptr_rom is None:
        lines.append("  NO Font Table signature found — game not supported, "
                     "or this is the sound ROM rather than the game ROM.")
        return "\n".join(lines)
    lines.append(f"  Font Table pointer @ ROM 0x{tables.font_ptr_rom:06X}")
    if tables.graphics_ptr_rom is not None:
        lines.append("  Graphics Table pointer @ ROM "
                     f"0x{tables.graphics_ptr_rom:06X}")
        graphics_table = resolve_table_ptr(rom, tables.graphics_ptr_rom)
        if graphics_table is not None:
            lines.append(f"  Graphics Table data    @ ROM 0x{graphics_table:06X}")
            counts = survey_encodings(rom, graphics_table, max_index=600)
            lines.append("  Encoding distribution (first 600 indices):")
            for k in sorted(counts):
                lines.append(f"    {k}: {counts[k]}")
        else:
            lines.append("  Graphics Table could not be resolved.")
    if tables.animation_ptr_rom is not None:
        lines.append("  Animation Table pointer @ ROM "
                     f"0x{tables.animation_ptr_rom:06X}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        print(_summarise(arg))
        print()
