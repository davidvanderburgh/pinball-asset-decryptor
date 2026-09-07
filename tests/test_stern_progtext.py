"""Tests for the Spike 2 game-program display strings (plugins.stern.progtext).

Everything runs on a tiny synthetic 32-bit ELF: one PT_LOAD segment mapping
the whole file at VBASE, a NUL-separated string table, and five-identical-dword
"name groups" (the five-UI-language pointer shape) — including one that points
INTO a longer string, the substring trick Godzilla uses for its battle names
("GODZILLA VS EBIRAH" + 12 is the standalone EBIRAH the battle intro shows).

The relocation half (LONGER text than the original) adds lone pointer words
and ARM movw/movt pairs to the fixture, an optional second PT_LOAD standing
in for the extension segment the engine appends, and — when the scratchpad
copy of the stock Godzilla Pro 1.15 ELF is present — a read-only check on
the real thing.
"""

import os
import struct

import pytest

from pinball_decryptor.plugins.stern import progreloc, progtext

VBASE = 0x10000
BODY_OFF = 0x100          # strings/pointers live after the headers

GAME_STOCK = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Temp", "claude",
    "C--Users-david-Documents-development-pinball-asset-decryptor",
    "451ab6eb-65f7-423c-891c-9f5af2819d71", "scratchpad", "longtext",
    "game_stock")


def _elf(body, flags=5, extra=None):
    """A minimal 32-bit LE ELF: header + one PT_LOAD covering the file
    (readable + executable, like a game's text segment), plus — with
    *extra* = ``(vaddr, payload)`` — a read-only PT_LOAD appended
    page-aligned at EOF the way the engine appends an extension segment."""
    total = BODY_OFF + len(body)
    nph = 2 if extra else 1
    hdr = bytearray(52)
    hdr[:4] = b"\x7fELF"
    hdr[4] = 1                                    # ELFCLASS32
    hdr[5] = 1                                    # little-endian
    struct.pack_into("<H", hdr, 0x12, 40)         # e_machine = EM_ARM
    struct.pack_into("<I", hdr, 0x1c, 52)         # e_phoff
    struct.pack_into("<H", hdr, 0x2a, 32)         # e_phentsize
    struct.pack_into("<H", hdr, 0x2c, nph)        # e_phnum
    ph = bytearray(32)
    struct.pack_into("<I", ph, 0, 1)              # PT_LOAD
    struct.pack_into("<I", ph, 4, 0)              # p_offset
    struct.pack_into("<I", ph, 8, VBASE)          # p_vaddr
    struct.pack_into("<I", ph, 16, total)         # p_filesz
    struct.pack_into("<I", ph, 20, total)         # p_memsz
    struct.pack_into("<I", ph, 24, flags)         # p_flags
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


def _build():
    """The fixture ELF: returns (raw, offsets dict)."""
    strings = [
        ("title", "GODZILLA VS EBIRAH"),
        ("mega", "GODZILLA VS MEGALON"),
        ("plain", "JACKPOT AWARD!"),
        ("ident", "AUD_MODE_BATTLE_STARTED"),      # excluded: identifier
        ("sound", "SE GZ VO KAIJUBATTLE 1"),       # excluded: sound event
        ("fmt", "%d MONSTERS LEFT"),
        ("multi", "GODZILLA, MOTHRA\nVS.\nKING GHIDORAH"),
    ]
    body = bytearray(b"\x00")                      # leading NUL: span anchors
    offs = {}
    for key, s in strings:
        offs[key] = BODY_OFF + len(body)
        body += s.encode() + b"\x00"
    # align to 4 for the pointer tables
    while (BODY_OFF + len(body)) % 4:
        body += b"\x00"
    va = lambda k, d=0: VBASE + offs[k] + d
    # 5-language group pointing INTO title (+12 -> "EBIRAH")
    offs["grp_tail"] = BODY_OFF + len(body)
    body += struct.pack("<5I", *([va("title", 12)] * 5)) + b"\x00" * 4
    # 5-language group pointing INTO mega (+12 -> "MEGALON")
    offs["grp_mega"] = BODY_OFF + len(body)
    body += struct.pack("<5I", *([va("mega", 12)] * 5)) + b"\x00" * 4
    # tail of multi: "KING GHIDORAH" at +21
    offs["grp_multi"] = BODY_OFF + len(body)
    body += struct.pack("<5I", *([va("multi", 21)] * 5)) + b"\x00" * 4
    # a LONE word equal to title+12: a sixth reference to the name, which
    # the census sees and the plan repoints like the group
    offs["lone"] = BODY_OFF + len(body)
    body += struct.pack("<I", va("title", 12))
    return _elf(bytes(body)), offs


@pytest.fixture()
def fixture_elf():
    return _build()


def _logs():
    msgs = []
    return msgs, lambda m, lvl="info": msgs.append((lvl, m))


def _warnings(msgs):
    return [m for lvl, m in msgs if lvl == "warning"]


def test_enumerate_rows(fixture_elf):
    raw, offs = fixture_elf
    rows = {r["text"]: r for r in progtext.enumerate_program_strings(raw)}
    assert rows["GODZILLA VS EBIRAH"]["tail_of"] is None
    # referenced (group + lone into it): growable, so the budget is the cap
    assert rows["GODZILLA VS EBIRAH"]["growable"] is True
    assert rows["GODZILLA VS EBIRAH"]["budget"] == progtext.MAX_EDIT_LEN
    assert rows["GODZILLA VS EBIRAH"]["refs"] == 2
    # the substring name is its own row, inheriting the host's growability
    assert rows["EBIRAH"]["tail_of"] == "GODZILLA VS EBIRAH"
    assert rows["EBIRAH"]["budget"] == progtext.MAX_EDIT_LEN
    assert rows["EBIRAH"]["growable"] is True
    assert rows["MEGALON"]["tail_of"] == "GODZILLA VS MEGALON"
    # multiline title round-trips with visible \n escapes
    multi = "GODZILLA, MOTHRA\\nVS.\\nKING GHIDORAH"
    assert multi in rows
    assert rows["KING GHIDORAH"]["tail_of"] == multi
    # nothing points at JACKPOT AWARD!: not growable, budget = its own slot
    assert rows["JACKPOT AWARD!"]["budget"] == 14
    assert rows["JACKPOT AWARD!"]["growable"] is False
    assert rows["JACKPOT AWARD!"]["refs"] == 0
    # exclusions
    assert "AUD_MODE_BATTLE_STARTED" not in rows
    assert "SE GZ VO KAIJUBATTLE 1" not in rows


def test_full_plus_tail_edit_moves_pointers(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {"GODZILLA VS EBIRAH": "GZ VS BIOLLANTE",
              "EBIRAH": "BIOLLANTE"}, log)
    assert n == 2 and blob == b""
    by_off = dict(writes)
    # the string write: NUL-padded to the original 18 bytes
    assert by_off[offs["title"]] == b"GZ VS BIOLLANTE\x00\x00\x00"
    # all five group words AND the lone word move to +6 ("GZ VS " prefix)
    new_ptr = struct.pack("<I", VBASE + offs["title"] + 6)
    for i in range(5):
        assert by_off[offs["grp_tail"] + 4 * i] == new_ptr
    assert by_off[offs["lone"]] == new_ptr
    # applying the writes yields the new strings on a rescan
    buf = bytearray(raw)
    for o, b in writes:
        buf[o:o + len(b)] = b
    rows = {r["text"]: r for r in
            progtext.enumerate_program_strings(bytes(buf))}
    assert rows["BIOLLANTE"]["tail_of"] == "GZ VS BIOLLANTE"


def test_tail_only_edit_that_fits(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(raw, {"EBIRAH": "ORGA"}, log)
    assert n == 1
    by_off = dict(writes)
    assert by_off[offs["title"]] == b"GODZILLA VS ORGA\x00\x00"
    # delta unchanged -> no pointer rewrites
    assert all(o == offs["title"] for o in by_off)


def test_tail_only_edit_too_long_is_skipped(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(raw, {"EBIRAH": "BIOLLANTE"}, log)
    assert writes == [] and n == 0
    assert any("Edit the full line too" in m for _l, m in msgs)


def test_full_edit_that_breaks_the_tail_is_skipped(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(
        raw, {"GODZILLA VS EBIRAH": "GZ VS BIOLLANTE"}, log)
    assert writes == [] and n == 0
    assert any("shown on its own" in m for _l, m in msgs)


def test_multiline_tail_edit(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(
        raw, {"KING GHIDORAH": "MECHAGHIDORA"}, log)
    assert n == 1
    by_off = dict(writes)
    want = "GODZILLA, MOTHRA\nVS.\nMECHAGHIDORA".encode()
    orig_len = len("GODZILLA, MOTHRA\nVS.\nKING GHIDORAH")
    assert by_off[offs["multi"]] == want.ljust(orig_len, b"\x00")


def test_percent_tokens_guarded(fixture_elf):
    raw, offs = fixture_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(
        raw, {"%d MONSTERS LEFT": "NO KAIJU"}, log)
    assert writes == [] and n == 0
    assert any("placeholders" in m for _l, m in msgs)
    # keeping the token is fine
    writes, n, _blob = progtext.plan_writes(
        raw, {"%d MONSTERS LEFT": "%d KAIJU"}, log)
    assert n == 1


def test_unknown_edit_warns(fixture_elf):
    raw, _offs = fixture_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(raw, {"NOT PRESENT": "X"}, log)
    assert writes == [] and n == 0
    assert any("wasn't found" in m for _l, m in msgs)


def test_not_an_elf_yields_nothing():
    assert progtext.enumerate_program_strings(b"garbage" * 100) == []
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(b"garbage" * 100, {"A B": "C"}, log)
    assert writes == [] and n == 0 and blob == b""


# ---------------------------------------------------------------------------
# Longer than the original: relocation into an extension segment.
#
# The fixture adds the reference shapes the census must see beyond the name
# groups: a lone pointer word (an adjustment descriptor, a high-score record),
# an A32 movw/movt pair and a T32 movw/movt pair in code, and a lone word
# pointing INTO a caption (its "EBIRAH TIMER" tail).  The plan is asked for
# with reloc={base_va, capacity, used} exactly as the engine will call it.
# ---------------------------------------------------------------------------

PLAIN = "JACKPOT AWARD!"
MEGA = "GODZILLA VS MEGALON"
CAP = "BATTLE VS EBIRAH TIMER"
DEAD = "NO REFS HERE"
RELOC = {"base_va": 0x6EE000, "capacity": 0x1000, "used": 12}


def _build_reloc():
    strings = [("plain", PLAIN), ("mega", MEGA), ("cap", CAP), ("dead", DEAD)]
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
        body.extend(b"\x00" * 8)

    def group(key, val):
        offs[key] = BODY_OFF + len(body)
        body.extend(struct.pack("<5I", *([val] * 5)) + b"\x00" * 4)

    word("plain_lone", va("plain"))
    group("mega_g0", va("mega"))
    group("mega_g12", va("mega", 12))
    word("cap_lone", va("cap"))
    group("cap_g0", va("cap"))
    word("cap_in10", va("cap", 10))
    p = va("plain")
    offs["a32_w"] = BODY_OFF + len(body)
    body.extend(struct.pack("<I", progreloc.encode_a32(0xE3001000, p & 0xFFFF)))
    body.extend(struct.pack("<I", 0xE1A00000))                     # nop
    offs["a32_t"] = BODY_OFF + len(body)
    body.extend(struct.pack("<I", progreloc.encode_a32(0xE3401000, p >> 16)))
    body.extend(struct.pack("<I", 0xE1A00000))
    offs["t32_w"] = BODY_OFF + len(body)
    body.extend(struct.pack("<HH", *progreloc.encode_t32(0xF240, 0x0200,
                                                          p & 0xFFFF)))
    offs["t32_t"] = BODY_OFF + len(body)
    body.extend(struct.pack("<HH", *progreloc.encode_t32(0xF2C0, 0x0200,
                                                          p >> 16)))
    body.extend(b"\x00" * 8)
    return bytes(body), offs


@pytest.fixture()
def reloc_elf():
    body, offs = _build_reloc()
    return _elf(body), offs


def _apply(raw, writes):
    buf = bytearray(raw)
    for o, b in writes:
        buf[o:o + len(b)] = b
    return bytes(buf)


def _ref_value(buf, kind, offs_):
    return progreloc.reference_value(buf, {"kind": kind, "offs": offs_})


def test_enumerate_marks_growable_rows(reloc_elf):
    raw, offs = reloc_elf
    rows = {r["text"]: r for r in progtext.enumerate_program_strings(raw)}
    assert rows[PLAIN]["growable"] and rows[PLAIN]["budget"] == 96
    assert rows[PLAIN]["refs"] == 3                 # lone + a32 + t32
    assert rows[MEGA]["refs"] == 2                  # two groups
    assert rows["MEGALON"]["tail_of"] == MEGA and rows["MEGALON"]["growable"]
    assert rows[CAP]["refs"] == 3                   # lone + group + interior
    # the interior lone word makes "EBIRAH TIMER" a tail row of its own
    assert rows["EBIRAH TIMER"]["tail_of"] == CAP
    assert rows["EBIRAH TIMER"]["budget"] == 96
    assert rows[DEAD] == {"text": DEAD, "budget": len(DEAD), "tail_of": None,
                          "growable": False, "refs": 0}


def test_too_long_edit_relocates_and_retargets_every_reference(reloc_elf):
    raw, offs = reloc_elf
    msgs, log = _logs()
    new = "SUPER DUPER JACKPOT AWARD!"
    writes, n, blob = progtext.plan_writes(raw, {PLAIN: new}, log, RELOC)
    assert n == 1
    assert blob == new.encode() + b"\x00"
    copy_va = RELOC["base_va"] + RELOC["used"]
    by_off = dict(writes)
    # the original bytes are not written; the lone word, both halves of the
    # A32 pair and both halves of the T32 pair are
    assert offs["plain"] not in by_off
    assert sorted(by_off) == sorted([offs["plain_lone"], offs["a32_w"],
                                     offs["a32_t"], offs["t32_w"],
                                     offs["t32_t"]])
    buf = _apply(raw, writes)
    assert _ref_value(buf, "lone", [offs["plain_lone"]]) == copy_va
    assert _ref_value(buf, "movw_a32", [offs["a32_w"], offs["a32_t"]]) == copy_va
    assert _ref_value(buf, "movw_t32", [offs["t32_w"], offs["t32_t"]]) == copy_va
    assert buf[offs["plain"]:offs["plain"] + len(PLAIN)] == PLAIN.encode()
    assert not _warnings(msgs)
    assert any("placed in new space" in m and "5 reference word(s)" in m
               for _l, m in msgs)


def test_fitting_edit_stays_in_place_even_with_reloc(reloc_elf):
    raw, offs = reloc_elf
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(raw, {PLAIN: "JACKPOT!"}, log, RELOC)
    assert n == 1 and blob == b""
    assert writes == [(offs["plain"], b"JACKPOT!".ljust(len(PLAIN), b"\x00"))]


def test_tail_only_long_edit_relocates_the_host(reloc_elf):
    raw, offs = reloc_elf
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {"MEGALON": "SPACEGODZILLA"}, log, RELOC)
    assert n == 1
    assert blob == b"GODZILLA VS SPACEGODZILLA\x00"
    copy_va = RELOC["base_va"] + RELOC["used"]
    buf = _apply(raw, writes)
    g0 = [offs["mega_g0"] + 4 * i for i in range(5)]
    g12 = [offs["mega_g12"] + 4 * i for i in range(5)]
    assert _ref_value(buf, "group", g0) == copy_va
    assert _ref_value(buf, "group", g12) == copy_va + 12
    assert offs["mega"] not in dict(writes)
    assert len(writes) == 10
    # editing the full line as well gives the identical plan
    writes2, n2, blob2 = progtext.plan_writes(
        raw, {MEGA: "GODZILLA VS SPACEGODZILLA", "MEGALON": "SPACEGODZILLA"},
        log, RELOC)
    assert (sorted(writes2), blob2) == (sorted(writes), blob) and n2 == 2


def test_interior_reference_without_a_tail_mapping_keeps_the_old_rule(reloc_elf):
    raw, offs = reloc_elf
    msgs, log = _logs()
    # the new title no longer ENDS with MEGALON, which the +12 group shows
    writes, n, blob = progtext.plan_writes(
        raw, {MEGA: "GODZILLA VS SPACEGODZILLA"}, log, RELOC)
    assert writes == [] and n == 0 and blob == b""
    assert any("shown on its own" in m and "must END with" in m
               for m in _warnings(msgs))
    # same for the caption's interior LONE word ("EBIRAH TIMER" at +10)
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {CAP: "BATTLE VS BIOLLANTE TIMER"}, log, RELOC)
    assert writes == [] and n == 0 and blob == b""
    assert any("EBIRAH TIMER" in m and "must END with" in m
               for m in _warnings(msgs))


def test_interior_lone_reference_is_retargeted_to_the_new_tail(reloc_elf):
    raw, offs = reloc_elf
    msgs, log = _logs()
    new = "BATTLE VS BIOLLANTE TIMER"              # +10 -> "BIOLLANTE TIMER"
    writes, n, blob = progtext.plan_writes(
        raw, {CAP: new, "EBIRAH TIMER": "BIOLLANTE TIMER"}, log, RELOC)
    assert n == 2 and blob == new.encode() + b"\x00"
    copy_va = RELOC["base_va"] + RELOC["used"]
    buf = _apply(raw, writes)
    assert _ref_value(buf, "lone", [offs["cap_lone"]]) == copy_va
    assert _ref_value(buf, "group", [offs["cap_g0"] + 4 * i
                                     for i in range(5)]) == copy_va
    assert _ref_value(buf, "lone", [offs["cap_in10"]]) == copy_va + 10
    assert not _warnings(msgs)


def test_sizing_pass_at_base_zero_matches_the_real_base(reloc_elf):
    raw, offs = reloc_elf
    edits = {PLAIN: "SUPER DUPER JACKPOT AWARD!", "MEGALON": "SPACEGODZILLA",
             DEAD: "NO REFS HERE BUT LONGER"}
    size = dict(RELOC, base_va=0)
    w0, n0, b0 = progtext.plan_writes(raw, edits, None, size)
    w1, n1, b1 = progtext.plan_writes(raw, edits, None, RELOC)
    assert b0 == b1 and n0 == n1 == 2
    assert [o for o, _b in w0] == [o for o, _b in w1]
    # two strings, each at a 4-aligned offset from the segment start
    assert b0 == b"SUPER DUPER JACKPOT AWARD!\x00\x00GODZILLA VS SPACEGODZILLA\x00"
    assert (RELOC["used"] + b0.index(b"GODZILLA")) % 4 == 0
    # only the pointer VALUES differ, by exactly the base
    for (o, a), (_o, b) in zip(w0, w1):
        if o == offs["plain_lone"] or o >= offs["mega_g0"]:
            if len(a) == 4 and o not in (offs["a32_w"], offs["a32_t"],
                                         offs["t32_w"], offs["t32_t"]):
                assert struct.unpack("<I", b)[0] - struct.unpack("<I", a)[0] \
                    == RELOC["base_va"]


def test_no_reference_span_keeps_the_in_place_rule(reloc_elf):
    raw, offs = reloc_elf
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {DEAD: "NO REFS HERE BUT LONGER"}, log, RELOC)
    assert writes == [] and n == 0 and blob == b""
    assert any("only %d" % len(DEAD) in m for m in _warnings(msgs))


def test_capacity_exhausted_refuses_with_a_named_reason(reloc_elf):
    raw, offs = reloc_elf
    new = "SUPER DUPER JACKPOT AWARD!"
    tight = {"base_va": 0x6EE000, "capacity": 12 + len(new) + 1, "used": 12}
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {PLAIN: new, "MEGALON": "SPACEGODZILLA"}, log, tight)
    # the first long edit fits exactly; the second finds the space used up
    assert n == 1 and blob == new.encode() + b"\x00"
    assert any("the free space for longer text (1 KB) is used up" in m
               for m in _warnings(msgs))
    assert offs["mega_g0"] not in dict(writes)
    # one byte less and even the first is refused; a fitting edit still lands
    tight["capacity"] -= 1
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {PLAIN: new, "MEGALON": "GIGAN"}, log, tight)
    assert n == 1 and blob == b""
    assert dict(writes)[offs["mega"]].startswith(b"GODZILLA VS GIGAN\x00")


def test_over_the_cap_is_refused_even_when_growable(reloc_elf):
    raw, offs = reloc_elf
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {PLAIN: "J" * (progtext.MAX_EDIT_LEN + 1)}, log, RELOC)
    assert writes == [] and n == 0 and blob == b""
    assert any("the longest a line can be is 96" in m for m in _warnings(msgs))
    writes, n, blob = progtext.plan_writes(
        raw, {PLAIN: "J" * progtext.MAX_EDIT_LEN}, log, RELOC)
    assert n == 1 and len(blob) == progtext.MAX_EDIT_LEN + 1


def test_relocated_elf_re_extracts_and_extends_from_used(reloc_elf):
    """A Write leaves the ELF with the extension segment mapped: the copy
    is the live, referenced row; the original is dead (refs 0); the header
    is not a string; and a second plan continues from the header's used."""
    raw, offs = reloc_elf
    new = "SUPER DUPER JACKPOT AWARD!"
    writes, n, blob = progtext.plan_writes(raw, {PLAIN: new}, None, RELOC)
    body, _ = _build_reloc()
    used = RELOC["used"] + len(blob)
    payload = progreloc.extension_header(used) + blob
    grown = _apply(_elf(body, extra=(RELOC["base_va"], payload)), writes)
    ext = progreloc.extension_segment(grown)
    assert ext["base_va"] == RELOC["base_va"] and ext["used"] == used
    rows = {r["text"]: r for r in progtext.enumerate_program_strings(grown)}
    assert rows[new]["growable"] and rows[new]["refs"] == 3
    assert rows[PLAIN] == {"text": PLAIN, "budget": len(PLAIN),
                           "tail_of": None, "growable": False, "refs": 0}
    assert not any(t.startswith("PADTXT") for t in rows)
    # a fitting edit of the live copy patches it in place, inside the segment
    reloc2 = {"base_va": ext["base_va"], "capacity": ext["capacity"],
              "used": ext["used"]}
    w2, n2, b2 = progtext.plan_writes(grown, {new: "JACKPOT AWARD! X"},
                                      None, reloc2)
    assert n2 == 1 and b2 == b""
    assert w2 == [(ext["seg_off"] + 12, b"JACKPOT AWARD! X".ljust(len(new),
                                                                   b"\x00"))]
    # a longer one extends the blob from `used`, not from the header
    w3, n3, b3 = progtext.plan_writes(
        grown, {new: "SUPER DUPER MEGA JACKPOT AWARD!"}, None, reloc2)
    # (used is 39 here, so the copy starts after one alignment pad byte)
    assert n3 == 1 and b3 == b"\x00SUPER DUPER MEGA JACKPOT AWARD!\x00"
    buf = _apply(grown, w3)
    assert _ref_value(buf, "lone", [offs["plain_lone"]]) == \
        ext["base_va"] + ((ext["used"] + 3) & ~3)


# ---------------------------------------------------------------------------
# The settings-caption boot guard.  The firmware hashes every adjustment's
# menu caption at boot; a duplicate is ** FATAL: error 249 (NVMigration:
# ADJUSTMENT hash is NOT UNIQUE) and the machine boot-loops (Godzilla 1.16
# Heisei retheme, 2026-08-26).  These fixtures add the adjustment shapes from
# test_stern_adjustments (AD_ names[], 44-byte descriptors with the caption
# pointer at +0x18, the section record) on top of editable display strings so
# plan_writes can see its edits through the settings table.
# ---------------------------------------------------------------------------

CAP_MEGA = "GZ VS. MEGALON DEFAULT CHAMP SCORE"
CAP_GIGAN = "GZ VS. MEGALON AND GIGAN DEFAULT CHAMP SCORE"
CAP_TIMER = "BATTLE VS EBIRAH TIMER"
CAP_GHIDRA = "BATTLE VS GHIDRA TIMER"
CAP_LONG = "BATTLE VS KING GHIDORAH TIMER"
AWARD_1 = "MEGALON AWARD!"
AWARD_2 = "GIGAN AWARD!"


def _build_settings():
    """(raw, offsets dict): five adjustments whose captions are editable
    display strings, two mergeable plain awards, and a five-language group
    pointing INTO the timer caption (its "EBIRAH TIMER" tail)."""
    ads = ["AD_GODZILLA_VS_MEGALON_CHAMPION",
           "AD_GODZILLA_VS_MEGALON_AND_GIGAN_CHAMPION",
           "AD_BATTLE_VS_EBIRAH_TIMER",
           "AD_BATTLE_VS_GHIDRA_TIMER",
           "AD_BATTLE_VS_KING_GHIDORAH_TIMER"]
    caps = [CAP_MEGA, CAP_GIGAN, CAP_TIMER, CAP_GHIDRA, CAP_LONG]
    body = bytearray(b"\x00")
    offs = {}
    for s in caps + [AWARD_1, AWARD_2] + ads + ["SYS"]:
        offs[s] = BODY_OFF + len(body)
        body += s.encode() + b"\x00"
    while (BODY_OFF + len(body)) % 4:
        body += b"\x00"
    va = lambda k, d=0: VBASE + offs[k] + d
    # five-language group -> the timer caption's "EBIRAH TIMER" tail (+10)
    offs["grp_timer"] = BODY_OFF + len(body)
    body += struct.pack("<5I", *([va(CAP_TIMER, 10)] * 5)) + b"\x00" * 4
    # names[]: the packed char*[] of AD_ strings the decoder hunts for
    body += struct.pack("<%dI" % len(ads), *[va(a) for a in ads])
    # descriptors: 44 bytes, caption pointer at +0x18
    desc_off = BODY_OFF + len(body)
    for cap in caps:
        e = bytearray(44)
        struct.pack_into("<iii", e, 0x04, 0, 0, 10)     # default, min, max
        struct.pack_into("<i", e, 0x10, 1)              # step
        struct.pack_into("<I", e, 0x18, va(cap))
        body += e
    offs["desc"] = desc_off
    # section record {live, table, count, elem, node}
    body += struct.pack("<IIIII", 0, VBASE + desc_off, len(ads), 44,
                        va("SYS"))
    return _elf(bytes(body)), offs


@pytest.fixture()
def settings_elf():
    return _build_settings()


def test_two_edits_to_one_caption_keep_first(settings_elf):
    raw, offs = settings_elf
    msgs, log = _logs()
    new = "GZ VS. SPACE G DEFAULT CHAMP SCORE"
    writes, n, _blob = progtext.plan_writes(raw, {CAP_MEGA: new, CAP_GIGAN: new},
                                            log)
    # the first setting in menu order keeps the name; the second is skipped
    assert n == 1
    by_off = dict(writes)
    assert by_off[offs[CAP_MEGA]] == new.encode().ljust(len(CAP_MEGA), b"\x00")
    assert offs[CAP_GIGAN] not in by_off
    warn = _warnings(msgs)
    assert len(warn) == 1
    assert "REFUSES TO BOOT" in warn[0] and CAP_GIGAN in warn[0]
    assert CAP_MEGA in warn[0]          # names the edit that took the name


def test_caption_rename_onto_existing_setting_skipped(settings_elf):
    raw, offs = settings_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(raw, {CAP_MEGA: CAP_GHIDRA}, log)
    assert writes == [] and n == 0
    warn = _warnings(msgs)
    assert len(warn) == 1
    assert "already named" in warn[0] and "REFUSES TO BOOT" in warn[0]


def test_unique_caption_rename_applies(settings_elf):
    raw, offs = settings_elf
    msgs, log = _logs()
    new = "GZ VS. MEGAGUIRUS DEFAULT CHAMP SCORE"
    writes, n, _blob = progtext.plan_writes(raw, {CAP_GIGAN: new}, log)
    assert n == 1
    assert dict(writes)[offs[CAP_GIGAN]] == new.encode().ljust(
        len(CAP_GIGAN), b"\x00")
    assert not _warnings(msgs)


def test_display_strings_may_still_merge(settings_elf):
    # KAIJU AWARD x3 is a deliberate merge in the very mod that found the
    # fatal — plain display text is none of the caption guard's business.
    raw, offs = settings_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(
        raw, {AWARD_1: "KAIJU AWARD!", AWARD_2: "KAIJU AWARD!"}, log)
    assert n == 2
    assert not _warnings(msgs)


def test_tail_edit_collision_withholds_the_plan(settings_elf):
    # A standalone-name rename rewrites its HOST caption: the edit's key is
    # never a caption text, so only the post-plan backstop can see that
    # "BATTLE VS EBIRAH TIMER" just became "BATTLE VS GHIDRA TIMER" — a name
    # another setting already has.  Nothing may ship.
    raw, offs = settings_elf
    msgs, log = _logs()
    writes, n, _blob = progtext.plan_writes(raw, {"EBIRAH TIMER": "GHIDRA TIMER"},
                                            log)
    assert writes == [] and n == 0
    warn = _warnings(msgs)
    assert any("REFUSES TO BOOT" in m and CAP_GHIDRA in m for m in warn)


def test_relocated_caption_is_read_through_the_blob(settings_elf):
    """A caption longer than its slot relocates: its descriptor word (a lone
    reference) is repointed and the guard reads the new name from the blob —
    so a unique long rename applies, and a tail rename that RELOCATES the
    host onto another setting's name is still caught."""
    raw, offs = settings_elf
    msgs, log = _logs()
    new = "GZ VS. MEGALON THE INSECT KAIJU DEFAULT CHAMP SCORE"
    writes, n, blob = progtext.plan_writes(raw, {CAP_MEGA: new}, log, RELOC)
    assert n == 1 and blob == new.encode() + b"\x00"
    assert not _warnings(msgs)
    desc_word = offs["desc"] + 0x18
    assert dict(writes)[desc_word] == struct.pack(
        "<I", RELOC["base_va"] + RELOC["used"])
    # "EBIRAH TIMER" -> "KING GHIDORAH TIMER" grows the host to CAP_LONG
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {"EBIRAH TIMER": "KING GHIDORAH TIMER"}, log, RELOC)
    assert writes == [] and n == 0 and blob == b""
    assert any("REFUSES TO BOOT" in m and CAP_LONG in m
               for m in _warnings(msgs))


# ---------------------------------------------------------------------------
# The real thing, read-only: the stock Godzilla Pro 1.15 ELF the emulator
# proof was run on (scratchpad copy; skipped when absent).
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.skipif(not os.path.exists(GAME_STOCK),
                    reason="stock Godzilla Pro 1.15 ELF not in the scratchpad")
def test_godzilla_pro_115_relocates_megalon_and_grows_a_caption():
    with open(GAME_STOCK, "rb") as f:
        raw = f.read()
    rows = {r["text"]: r for r in progtext.enumerate_program_strings(raw)}
    assert rows[MEGA]["growable"] and rows[MEGA]["refs"] == 3
    assert rows["MEGALON"]["tail_of"] == MEGA and rows["MEGALON"]["growable"]
    # a settings caption: its descriptor word (lone) plus a five-group
    assert rows[CAP]["growable"] and rows[CAP]["refs"] == 2
    assert rows[CAP]["budget"] == progtext.MAX_EDIT_LEN
    # the designer credits are reached by index, never by pointer
    assert rows["GEORGE GOMEZ"] == {"text": "GEORGE GOMEZ", "budget": 12,
                                    "tail_of": None, "growable": False,
                                    "refs": 0}
    lo, hi = progreloc.text_data_hole(raw)
    assert (lo, hi) == (0x6EE000, 0x6F5000)
    reloc = {"base_va": lo, "capacity": hi - lo, "used": 12}
    msgs, log = _logs()
    writes, n, blob = progtext.plan_writes(
        raw, {MEGA: "GODZILLA VS SPACEGODZILLA", "MEGALON": "SPACEGODZILLA"},
        log, reloc)
    assert n == 2 and blob == b"GODZILLA VS SPACEGODZILLA\x00"
    # the prototype's count: the 5-word title group + two 5-word MEGALON
    # groups, and not one byte of the original string
    assert len(writes) == 15
    assert all(len(b) == 4 for _o, b in writes)
    vals = sorted({struct.unpack("<I", b)[0] for _o, b in writes})
    assert vals == [lo + 12, lo + 12 + 12]
    assert 0x5E7760 not in dict(writes)
    assert not _warnings(msgs)
