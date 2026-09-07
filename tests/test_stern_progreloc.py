"""Tests for plugins.stern.progreloc — the reference census and the ARM
movw/movt codecs behind LONGER program text.

The codec vectors are assembler-known encodings (``movw r0, #0x1234`` is
``e3010234`` in A32 and ``f241 2034`` in T32; the movt of ``0x5678`` is
``e3450678`` / ``f2c5 6078``).  The census runs on a tiny synthetic ELF
whose one PT_LOAD is readable+executable so both the data and the code
scans cover it.
"""

import struct

import pytest

from pinball_decryptor.plugins.stern import progreloc as pr

VBASE = 0x10000
BODY_OFF = 0x100


def _elf(body, flags=5, extra=None):
    """Header + one PT_LOAD (flags *flags*) over the file, plus an optional
    second PT_LOAD ``(vaddr, payload)`` appended page-aligned at EOF."""
    total = BODY_OFF + len(body)
    nph = 2 if extra else 1
    hdr = bytearray(52)
    hdr[:4] = b"\x7fELF"
    hdr[4] = 1
    hdr[5] = 1
    struct.pack_into("<H", hdr, 0x12, 40)
    struct.pack_into("<I", hdr, 0x1c, 52)
    struct.pack_into("<H", hdr, 0x2a, 32)
    struct.pack_into("<H", hdr, 0x2c, nph)
    ph = bytearray(32)
    struct.pack_into("<8I", ph, 0, 1, 0, VBASE, VBASE, total, total, flags,
                     0x1000)
    raw = bytearray(hdr + ph)
    if extra:
        raw += b"\x00" * 32
    raw += b"\x00" * (BODY_OFF - len(raw)) + body
    if extra:
        va, payload = extra
        off = (len(raw) + 0xFFF) & ~0xFFF
        size = (len(payload) + 0xFFF) & ~0xFFF
        raw += b"\x00" * (off + size - len(raw))
        raw[off:off + len(payload)] = payload
        struct.pack_into("<8I", raw, 52 + 32, 1, off, va, va, size, size, 4,
                         0x1000)
    return bytes(raw)


# ---------------------------------------------------------------------------
# codecs
# ---------------------------------------------------------------------------

def test_a32_known_encodings_decode():
    assert pr.decode_a32(0xE3010234) == ("movw", 0, 0x1234)
    assert pr.decode_a32(0xE3450678) == ("movt", 0, 0x5678)
    # movw r7, #0xb32c (Godzilla LE 0xd6c70): imm4=b rd=7 imm12=32c
    assert pr.decode_a32(0xE30B732C) == ("movw", 7, 0xB32C)
    # not MOVs: an add, a branch, and the cond=F space
    assert pr.decode_a32(0xE2800001) is None
    assert pr.decode_a32(0xEAFFFFFE) is None
    assert pr.decode_a32(0xF3010234) is None


def test_a32_encode_round_trips_and_keeps_cond_rd():
    for imm in (0, 1, 0x1234, 0xB32C, 0xFFFF, 0x8000, 0x0FFF):
        w = pr.encode_a32(0xE3010234, imm)
        assert pr.decode_a32(w) == ("movw", 0, imm)
        t = pr.encode_a32(0x13450678, imm)          # cond NE, movt r0
        assert pr.decode_a32(t) == ("movt", 0, imm)
        assert t >> 28 == 1
    assert pr.encode_a32(0xE3010234, 0x5678) == 0xE3050678
    assert pr.encode_a32(0xE34B7000, 0xB32C) == 0xE34B732C


def test_t32_known_encodings_decode():
    assert pr.decode_t32(0xF241, 0x2034) == ("movw", 0, 0x1234)
    assert pr.decode_t32(0xF2C5, 0x6078) == ("movt", 0, 0x5678)
    # movw r3, #0x8800 sets the i bit: imm4=8 i=1 imm3=0 imm8=0
    assert pr.decode_t32(0xF648, 0x0300) == ("movw", 3, 0x8800)
    assert pr.decode_t32(0xF241, 0xA034) is None      # hw2 bit 15 set
    assert pr.decode_t32(0xF000, 0xB800) is None      # a branch


def test_t32_encode_round_trips_every_bit_field():
    for imm in (0, 1, 0x1234, 0x8800, 0x0800, 0xF0FF, 0xFFFF, 0x7FF):
        h1, h2 = pr.encode_t32(0xF241, 0x2034, imm)
        assert pr.decode_t32(h1, h2) == ("movw", 0, imm)
        h1, h2 = pr.encode_t32(0xF2C5, 0x6A78, imm)     # movt r10
        assert pr.decode_t32(h1, h2) == ("movt", 10, imm)
    assert pr.encode_t32(0xF241, 0x2034, 0x5678) == (0xF245, 0x6078)


def test_pair_scans_find_a_pair_and_respect_the_window():
    # A32: movw r1 ; nop ; movt r1  -> one pair; a movt to r2 pairs nothing
    code = struct.pack("<6I", 0xE3011234, 0xE1A00000, 0xE3451678,
                       0xE30A2000, 0xE1A00000, 0xE1A00000)
    seg = (VBASE, 0, len(code), len(code), 5)
    assert pr.a32_pairs(code, seg) == [(0, 8, 1, 0x56781234)]
    # a movt 7 instructions after its movw is out of the window
    far = struct.pack("<8I", 0xE3011234, *([0xE1A00000] * 6), 0xE3451678)
    assert pr.a32_pairs(far, (VBASE, 0, len(far), len(far), 5)) == []
    # T32: movw r0 ; movt r0
    t = struct.pack("<4H", 0xF241, 0x2034, 0xF2C5, 0x6078)
    assert pr.t32_pairs(t, (VBASE, 0, len(t), len(t), 5)) == \
        [(0, 4, 0, 0x56781234)]


# ---------------------------------------------------------------------------
# ELF geometry + the extension header
# ---------------------------------------------------------------------------

def test_phdrs_segments_and_hole():
    raw = _elf(b"\x00hello\x00", extra=(0x20000, b"xyz"))
    ph = pr.iter_phdrs(raw)
    assert [p[1] for p in ph] == [1, 1]
    segs = pr.load_segments(raw)
    assert segs[0][0] == VBASE and segs[0][4] == 5
    assert segs[1][0] == 0x20000 and segs[1][4] == 4
    off2va, va2off = pr.seg_maps(segs)
    assert off2va(BODY_OFF + 1) == VBASE + BODY_OFF + 1
    assert va2off(VBASE + BODY_OFF + 1) == BODY_OFF + 1
    assert va2off(0x20000) == segs[1][1]
    assert va2off(0x12345678) is None
    # hole: from the end of segment 1 (page-rounded) to the start of 2
    lo, hi = pr.text_data_hole(raw)
    assert lo == ((VBASE + len(_elf(b"\x00hello\x00")) + 0xFFF) & ~0xFFF)
    assert hi == 0x20000
    assert pr.iter_phdrs(b"not an elf at all" * 10) == []


def test_extension_segment_header_round_trip():
    payload = pr.extension_header(12 + 8) + b"NEW TEXT\x00"
    raw = _elf(b"\x00hello\x00", extra=(0x20000, payload))
    ext = pr.extension_segment(raw)
    assert ext["base_va"] == 0x20000
    assert ext["used"] == 20
    assert ext["capacity"] == 0x1000
    assert raw[ext["seg_off"]:ext["seg_off"] + 8] == pr.EXT_MAGIC
    assert pr.extension_segment(_elf(b"\x00hello\x00")) is None
    # a corrupt "used" is clamped into [header, capacity]
    bad = bytearray(raw)
    struct.pack_into("<I", bad, ext["seg_off"] + 8, 0xFFFFFFFF)
    assert pr.extension_segment(bytes(bad))["used"] == 0x1000
    struct.pack_into("<I", bad, ext["seg_off"] + 8, 0)
    assert pr.extension_segment(bytes(bad))["used"] == pr.EXT_HEADER_LEN


# ---------------------------------------------------------------------------
# the census on a synthetic ELF
# ---------------------------------------------------------------------------

def _build():
    strings = [
        ("plain", "JACKPOT AWARD!"),          # lone + a32 + t32, all delta 0
        ("mega", "GODZILLA VS MEGALON"),      # group d0 + group d12
        ("cap", "BATTLE VS EBIRAH TIMER"),    # lone d0 + group d0 + lone d10
        ("dead", "NO REFS HERE"),             # nothing points at it
        ("ctr", "COUNTER ROW TEXT"),          # group d0; a stride counter at +9
        ("ws", "GAME OVER MAN"),              # lone d4 at a space: dismissed
    ]
    body = bytearray(b"\x00")
    offs = {}
    for key, s in strings:
        offs[key] = BODY_OFF + len(body)
        body += s.encode() + b"\x00"
    while (BODY_OFF + len(body)) % 4:
        body += b"\x00"
    va = lambda k, d=0: VBASE + offs[k] + d

    def word(key, val):
        offs[key] = BODY_OFF + len(body)
        body.extend(struct.pack("<I", val))

    def group(key, val):
        offs[key] = BODY_OFF + len(body)
        body.extend(struct.pack("<5I", *([val] * 5)) + b"\x00" * 4)

    word("plain_lone", va("plain"))
    body.extend(b"\x00" * 8)
    group("mega_g0", va("mega"))
    group("mega_g12", va("mega", 12))
    word("cap_lone", va("cap"))
    body.extend(b"\x00" * 8)
    group("cap_g0", va("cap"))
    word("cap_in10", va("cap", 10))
    body.extend(b"\x00" * 8)
    group("ctr_g0", va("ctr"))
    # a packed counter at stride 8 whose middle member lands 9 bytes in
    for k, d in (("ctr_m1", 8), ("ctr_0", 9), ("ctr_p1", 10)):
        word(k, va("ctr", d))
        body.extend(b"\x00" * 4)
    word("ws_lone", va("ws", 4))              # "GAME OVER MAN"[4] == ' '
    body.extend(b"\x00" * 8)
    # code: A32 movw r1 / nop / movt r1 = plain; T32 movw r2 / movt r2 = plain
    p = va("plain")
    offs["a32_w"] = BODY_OFF + len(body)
    body.extend(struct.pack("<I", pr.encode_a32(0xE3001000, p & 0xFFFF)))
    body.extend(struct.pack("<I", 0xE1A00000))
    offs["a32_t"] = BODY_OFF + len(body)
    body.extend(struct.pack("<I", pr.encode_a32(0xE3401000, p >> 16)))
    body.extend(struct.pack("<I", 0xE1A00000))
    offs["t32_w"] = BODY_OFF + len(body)
    body.extend(struct.pack("<HH", *pr.encode_t32(0xF240, 0x0200, p & 0xFFFF)))
    offs["t32_t"] = BODY_OFF + len(body)
    body.extend(struct.pack("<HH", *pr.encode_t32(0xF2C0, 0x0200, p >> 16)))
    body.extend(b"\x00" * 8)
    return _elf(bytes(body)), offs


@pytest.fixture()
def synth():
    return _build()


def _spans(raw):
    from pinball_decryptor.plugins.stern import progtext
    return progtext._display_spans(raw, progtext._load_ranges(raw))


def test_census_sees_every_reference_kind(synth):
    raw, offs = synth
    c = pr.reference_census(raw, _spans(raw))
    plain = c[offs["plain"]]
    assert [(r["kind"], r["delta"], r["offs"]) for r in plain] == [
        ("lone", 0, [offs["plain_lone"]]),
        ("movw_a32", 0, [offs["a32_w"], offs["a32_t"]]),
        ("movw_t32", 0, [offs["t32_w"], offs["t32_t"]]),
    ]
    assert all(r["va"] == VBASE + offs["plain"] for r in plain)
    mega = c[offs["mega"]]
    assert [(r["kind"], r["delta"], len(r["offs"])) for r in mega] == [
        ("group", 0, 5), ("group", 12, 5)]
    assert mega[1]["offs"] == [offs["mega_g12"] + 4 * i for i in range(5)]
    assert mega[1]["va"] == VBASE + offs["mega"] + 12
    cap = c[offs["cap"]]
    assert [(r["kind"], r["delta"]) for r in cap] == [
        ("lone", 0), ("group", 0), ("lone", 10)]
    assert offs["dead"] not in c


def test_counter_and_whitespace_lookalikes_are_not_references(synth):
    raw, offs = synth
    c = pr.reference_census(raw, _spans(raw))
    assert [(r["kind"], r["delta"]) for r in c[offs["ctr"]]] == [("group", 0)]
    assert pr.is_counter_word(raw, offs["ctr_0"], VBASE + offs["ctr"] + 9)
    assert not pr.is_counter_word(raw, offs["cap_lone"], VBASE + offs["cap"])
    assert offs["ws"] not in c


def test_reference_value_and_retarget_every_kind(synth):
    raw, offs = synth
    c = pr.reference_census(raw, _spans(raw))
    new_va = 0x6EE00C
    buf = bytearray(raw)
    for ref in c[offs["plain"]] + c[offs["mega"]]:
        assert pr.reference_value(raw, ref) == ref["va"]
        for off, b in pr.retarget_writes(raw, ref, new_va + ref["delta"]):
            buf[off:off + len(b)] = b
    buf = bytes(buf)
    for ref in c[offs["plain"]]:
        assert pr.reference_value(buf, ref) == new_va
    for ref in c[offs["mega"]]:
        assert pr.reference_value(buf, ref) == new_va + ref["delta"]
    # the instructions are still the same instructions (cond/opcode/Rd)
    assert pr.decode_a32(struct.unpack_from("<I", buf, offs["a32_w"])[0]) == \
        ("movw", 1, new_va & 0xFFFF)
    assert pr.decode_a32(struct.unpack_from("<I", buf, offs["a32_t"])[0]) == \
        ("movt", 1, new_va >> 16)
    assert pr.decode_t32(*struct.unpack_from("<HH", buf, offs["t32_t"])) == \
        ("movt", 2, new_va >> 16)
    # a group whose words disagree no longer reads as one reference
    torn = bytearray(raw)
    struct.pack_into("<I", torn, offs["mega_g0"], 0)
    assert pr.reference_value(bytes(torn), c[offs["mega"]][0]) is None
    # the original string bytes were never touched
    assert buf[offs["plain"]:offs["plain"] + 14] == b"JACKPOT AWARD!"
