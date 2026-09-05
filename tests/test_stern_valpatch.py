"""Stern's SD-card validator bypass: finding it, and admitting when we can't.

``valpatch`` writes the four bytes that stop a modded Spike 2 card raising
``GAME VALIDATION ERROR / UPDATE SD CARD``.  It finds the routine to patch two
independent ways: the function carrying several inlined CRC32-``0xEDB88320``
loops, and -- because that describes how a firmware was *compiled* rather than
what it does -- the routine's measured shape.  Profiled over the whole vendor
library, the two select the same single function on all 35 cards that carry the
validator, with no false positive from the shape locator on any of them.

Jaws LE 1.01.0 matches neither, in either of its game binaries, and nothing on
that card explains why: no ``0xEDB88320`` in any ELF's ``.text``, not Thumb, and
its six on-LCD messages present and byte-identical.  It is reported as
uncertain rather than resolved -- inferring "no validator" from our own
signature failing would be an argument from ignorance, and on a newer title the
expensive direction to be wrong in.

A miss used to be indistinguishable from a title that carries no validator --
both logged "nothing to bypass" and the Write reported success -- so the user
got a card whose validator is fully armed and a machine that answers with the
validation error and reboots instead of starting a game (flippermeister, James
Bond with one replaced sound, 2026-07-31).  These tests pin all of it: each
locator finds a normal validator, the shape one refuses a wrong-shaped
function, and a firmware that looks like it carries a validator without
matching either is reported as a failure rather than a no-op.
"""

import struct

from pinball_decryptor.plugins.stern import valpatch


# --- a minimal ARM ELF with a placed "validator" -----------------------------
# Only what _text_section / find_validation_exec read: an ELF header, a section
# header table naming .text, and ARM A32 code.

TEXT_VADDR = 0x11000
TEXT_OFF = 0x1000
NWORDS = 128

FN_A = TEXT_VADDR + 0x40
FN_V = TEXT_VADDR + 0x80       # the "validator"
FN_B = TEXT_VADDR + 0x100

PUSH_LR = 0xE92D4000           # push {lr}
NOP = 0xE1A00000               # mov r0, r0
BX_LR = 0xE12FFF1E


def _bl(at_va, target_va):
    imm = ((target_va - (at_va + 8)) >> 2) & 0xFFFFFF
    return 0xEB000000 | imm


def _movw(rd, imm16):
    return 0xE3000000 | ((imm16 >> 12) << 16) | (rd << 12) | (imm16 & 0xFFF)


def _movt(rd, imm16):
    return 0xE3400000 | ((imm16 >> 12) << 16) | (rd << 12) | (imm16 & 0xFFF)


def _build_elf(inline_crc_loops=5, trailer=b""):
    """A tiny ARM ELF whose ``FN_V`` carries *inline_crc_loops* CRC32 constants.

    ``inline_crc_loops=0`` is the Jaws shape: the same functions, but the
    polynomial never appears as an immediate (it would live behind a call)."""
    words = [NOP] * NWORDS

    def put(va, w):
        words[(va - TEXT_VADDR) // 4] = w

    # A caller that reaches all three functions, so each becomes a known entry.
    for i, target in enumerate((FN_A, FN_V, FN_B)):
        va = TEXT_VADDR + i * 4
        put(va, _bl(va, target))

    put(FN_A, PUSH_LR)
    put(FN_B, PUSH_LR)
    put(FN_V, PUSH_LR)
    va = FN_V + 4
    for _ in range(inline_crc_loops):
        put(va, _movw(3, valpatch._CRC32_POLY & 0xFFFF))
        put(va + 4, _movt(3, valpatch._CRC32_POLY >> 16))
        va += 8
    put(va, BX_LR)

    text = struct.pack("<%dI" % NWORDS, *words)
    shstr = b"\x00.text\x00.shstrtab\x00"
    shstr_off = TEXT_OFF + len(text)
    sh_off = shstr_off + len(shstr)

    def sh(name, addr, off, size):
        return struct.pack("<10I", name, 1, 0, addr, off, size, 0, 0, 4, 0)

    shdrs = (sh(0, 0, 0, 0)
             + sh(1, TEXT_VADDR, TEXT_OFF, len(text))       # ".text"
             + sh(7, 0, shstr_off, len(shstr)))             # ".shstrtab"

    hdr = bytearray(b"\x00" * 0x34)
    hdr[0:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", hdr, 0x12, 40)          # e_machine = EM_ARM
    struct.pack_into("<I", hdr, 0x20, sh_off)      # e_shoff
    struct.pack_into("<H", hdr, 0x2e, 40)          # e_shentsize
    struct.pack_into("<H", hdr, 0x30, 3)           # e_shnum
    struct.pack_into("<H", hdr, 0x32, 2)           # e_shstrndx

    out = bytearray(hdr)
    out.extend(b"\x00" * (TEXT_OFF - len(out)))
    out.extend(text)
    out.extend(shstr)
    out.extend(shdrs)
    out.extend(trailer)
    return bytes(out)


# The validator's own on-LCD messages, as Stern ships them.  Byte-identical on
# all 37 vendor cards -- INCLUDING the two that carry no validator -- and on
# every card they are reached through a data table rather than a direct
# reference.  So they are decoration here, not evidence: a build can ship them
# and still not perform the check.
VALIDATOR_STRINGS = (b"GAME VALIDATION ERROR\x00#6 %d:%d:%d UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#5 %d:%d UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#4 %d:%d UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#3 UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#2 UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#1 UPDATE SD CARD\x00")

# The routine's PRIVATE progress-string pool -- data the compiler has to emit
# for it, so it is present exactly when the routine was linked in (35 of the
# 37 vendor cards, and precisely the 35 where we locate the validator).
POOL_STRINGS = (b"SS: %u:%u\x00GE: PD\x00GE: %5.2f%%\x00CE: PD\x00"
                b"CE: %5.2f%%\x00ZK: PD\x00ZK: %5.2f%%\x00SF: %u:%u:%u\x00")


# --- the signature itself ----------------------------------------------------

def test_finds_the_validator_by_its_inlined_crc32_loops():
    elf = _build_elf(inline_crc_loops=5, trailer=VALIDATOR_STRINGS)
    eoff = valpatch.find_validation_exec(elf)
    assert eoff == FN_V - TEXT_VADDR + TEXT_OFF
    # It must land on the function's push{lr} entry — that word is what gets
    # overwritten with `bx lr`, so being one instruction off corrupts the game.
    assert struct.unpack_from("<I", elf, eoff)[0] == PUSH_LR


def test_one_stray_crc_constant_is_not_enough_to_claim_a_validator():
    # Plenty of code carries a single CRC32 constant; the validator is the one
    # with several inlined loops.  Matching on one would patch a bystander.
    assert valpatch.find_validation_exec(
        _build_elf(inline_crc_loops=1, trailer=VALIDATOR_STRINGS)) is None


def test_bypass_overlay_patches_the_entry_with_bx_lr():
    elf = _build_elf(trailer=VALIDATOR_STRINGS)
    overlay, status = valpatch.bypass_overlay(elf)
    assert status == ("bypassed", "")
    assert list(overlay) == [valpatch.find_validation_exec(elf)]
    assert overlay[valpatch.find_validation_exec(elf)] == valpatch._BX_LR


# --- telling "no validator" apart from "couldn't find the validator" ---------

def test_carries_validator_keys_on_the_private_string_pool():
    # The pool is data the compiler emits for the routine, so it answers "was
    # this linked in?" without depending on how the routine was compiled --
    # which is what lets a build that stops inlining its CRC32 still count.
    pool_only = _build_elf(inline_crc_loops=0, trailer=POOL_STRINGS)
    assert valpatch.find_validation_exec(pool_only) is None
    assert valpatch.carries_validator(pool_only)


def test_carries_validator_also_accepts_the_inlined_crc32_alone():
    # Either marker is enough on its own, so renaming the progress tags does
    # not make a live validator look absent.
    assert valpatch.carries_validator(_build_elf(inline_crc_loops=5))


def test_the_on_lcd_messages_alone_do_not_mean_a_validator_is_present():
    """The Jaws case, and the reason this test exists.

    Jaws LE 1.01.0 ships the six numbered messages but carries no validator:
    the routine's ~1545-instruction body scores zero matching 8-grams against
    every one of the 4,437 files on the card, and its private string pool is
    absent -- while a function the cards share matches Jaws exactly, so the
    binary is the same build lineage and the null result means something.
    Treating the messages as evidence warned on a card that needs no warning.
    """
    jaws_like = _build_elf(inline_crc_loops=0, trailer=VALIDATOR_STRINGS)
    assert valpatch.find_validation_exec(jaws_like) is None
    assert not valpatch.carries_validator(jaws_like)
    assert valpatch.bypass_overlay(jaws_like)[1] == ("absent", "")


def test_a_firmware_with_no_marker_at_all_carries_no_validator():
    assert not valpatch.carries_validator(_build_elf(inline_crc_loops=0))


def test_status_calls_an_unreachable_validator_a_failure_not_a_no_op():
    # A firmware that carries a marker but whose routine neither locator can
    # pin is the dangerous case: it ships a card the machine rejects.
    armed = _build_elf(inline_crc_loops=0, trailer=POOL_STRINGS)
    overlay, status = valpatch.bypass_overlay(armed)
    assert overlay == {}                      # nothing could be patched...
    assert status[0] == "unlocated"           # ...and that is a PROBLEM,
    assert status[1]                          # with a reason for the user.

    # A title that genuinely has no validator is the harmless case, and must
    # not cry wolf — otherwise the warning stops meaning anything.
    plain = _build_elf(inline_crc_loops=0)
    assert valpatch.bypass_overlay(plain)[1] == ("absent", "")


def test_unreachable_validator_is_logged_as_an_error():
    # The log level is the whole point: this used to be an "info" line reading
    # "nothing to bypass", which looked like good news on a card that was about
    # to fail on the machine.
    lines = []
    valpatch.log_status(lambda m, lvl="info": lines.append((m, lvl)),
                        ("unlocated", "no signature match"))
    (msg, lvl), = lines
    assert lvl == "error"
    assert "GAME VALIDATION ERROR" in msg
    assert "no signature match" in msg

    lines.clear()
    valpatch.log_status(lambda m, lvl="info": lines.append((m, lvl)),
                        ("absent", ""))
    assert lines[0][1] == "info"              # nothing to warn about


def test_locating_is_idempotent_on_an_already_bypassed_firmware():
    """Re-running a Write must not "lose" a validator it already patched.

    The bypass overwrites the function's push{lr} prologue, which is the very
    thing the prologue check looks for -- so on a second pass (a build from an
    already-modded image, or a second Direct-SD write onto a modded card) the
    routine went missing and got reported as unreachable, warning about a card
    that is correctly patched.
    """
    elf = bytearray(_build_elf(trailer=VALIDATOR_STRINGS))
    eoff = valpatch.find_validation_exec(bytes(elf))
    elf[eoff:eoff + 4] = valpatch._BX_LR              # apply the bypass
    again = valpatch.find_validation_exec(bytes(elf))
    assert again == eoff
    assert valpatch.bypass_status(bytes(elf), again) == ("bypassed", "")
    # ...and a third pass is still a stable no-op.
    overlay, status = valpatch.bypass_overlay(bytes(elf))
    assert overlay == {eoff: valpatch._BX_LR}
    assert status == ("bypassed", "")


def test_a_bare_bx_lr_without_crc_loops_is_still_not_a_validator():
    # The idempotence allowance must not become a way to match any function
    # that happens to start with `bx lr` -- the CRC32 evidence still rules.
    elf = bytearray(_build_elf(inline_crc_loops=0, trailer=VALIDATOR_STRINGS))
    elf[TEXT_OFF + (FN_V - TEXT_VADDR):TEXT_OFF + (FN_V - TEXT_VADDR) + 4] = \
        valpatch._BX_LR
    assert valpatch.find_validation_exec(bytes(elf)) is None


# --- the second locator: shape, for a build that stops inlining its CRC32 ----
# The CRC-immediate signature describes how a firmware was COMPILED.  A second
# locator keyed on the routine's measured shape (1537-1547 instructions, 22
# callees, 92 backward branches, 269 loads, 198 stores, 156 compares, exactly
# one caller) was profiled over the whole vendor library: on all 35 cards that
# carry the validator the two locators select the SAME single function, and the
# shape one raises no false positive on any of them.

def _build_shape_elf(with_poly=False, ncallees=22, loops=92, loads=269,
                     stores=198, cmps=156, nwords=1500):
    """An ELF whose FN_V has the validator's shape but (by default) no CRC32
    constant anywhere -- the case the first locator cannot see."""
    TV, TO = 0x11000, 0x1000
    total = 0x2000
    words = [NOP] * total
    fn = TV + 0x1000                       # the "validator"
    fi = (fn - TV) // 4

    def put(i, w):
        words[i] = w

    put(0, _bl(TV, fn))                    # exactly one caller
    # callee targets sit immediately AFTER the body, so the next known entry
    # lands exactly at fn+nwords and bounds the function at that size.
    first_callee = fn + nwords * 4
    put(fi, PUSH_LR)
    k = fi + 1
    for c in range(ncallees):
        put(k, _bl(fn + (k - fi) * 4, first_callee + c * 4)); k += 1
    for _ in range(loops):                 # backward B (not BL: no new entry)
        at = fn + (k - fi) * 4
        imm = ((fn - (at + 8)) >> 2) & 0xFFFFFF
        put(k, 0xEA000000 | imm); k += 1
    for _ in range(loads):
        put(k, 0xE5910000); k += 1         # ldr r0,[r1]
    for _ in range(stores):
        put(k, 0xE5810000); k += 1         # str r0,[r1]
    for _ in range(cmps):
        put(k, 0xE3500000); k += 1         # cmp r0,#0
    if with_poly:
        for _ in range(5):
            put(k, _movw(3, valpatch._CRC32_POLY & 0xFFFF)); k += 1
            put(k, _movt(3, valpatch._CRC32_POLY >> 16)); k += 1
    assert k < fi + nwords, (k, fi + nwords)

    text = struct.pack("<%dI" % total, *words)
    shstr = b"\x00.text\x00.shstrtab\x00"
    shstr_off = TO + len(text)
    sh_off = shstr_off + len(shstr)

    def sh(name, addr, off, size):
        return struct.pack("<10I", name, 1, 0, addr, off, size, 0, 0, 4, 0)

    hdr = bytearray(b"\x00" * 0x34)
    hdr[0:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", hdr, 0x12, 40)
    struct.pack_into("<I", hdr, 0x20, sh_off)
    struct.pack_into("<H", hdr, 0x2e, 40)
    struct.pack_into("<H", hdr, 0x30, 3)
    struct.pack_into("<H", hdr, 0x32, 2)
    out = bytearray(hdr)
    out.extend(b"\x00" * (TO - len(out)))
    out.extend(text)
    out.extend(shstr)
    out.extend(sh(0, 0, 0, 0) + sh(1, TV, TO, len(text))
               + sh(7, 0, shstr_off, len(shstr)))
    # A firmware that really carries the routine carries its data too, so the
    # synthetic one models a build that stopped inlining CRC32 but is still
    # recognisably armed.
    out.extend(VALIDATOR_STRINGS)
    out.extend(POOL_STRINGS)
    return bytes(out), TO + (fn - TV)


def test_shape_locator_finds_a_validator_that_inlines_no_crc32():
    elf, want = _build_shape_elf(with_poly=False)
    idx = valpatch._index_text(elf)
    assert valpatch._by_crc32_immediates(elf, idx) is None   # first one is blind
    assert valpatch._by_shape(elf, idx) == want + idx["code_base"]
    assert valpatch.find_validation_exec(elf) == want        # and the fallback runs
    assert valpatch.bypass_status(elf, want) == ("bypassed", "")


def test_both_locators_agree_when_the_crc32_is_inlined():
    elf, want = _build_shape_elf(with_poly=True)
    idx = valpatch._index_text(elf)
    assert valpatch._by_crc32_immediates(elf, idx) == want + idx["code_base"]
    assert valpatch._by_shape(elf, idx) == want + idx["code_base"]


def test_shape_locator_refuses_a_function_of_the_wrong_shape():
    # Every band has to hold; one badly-off feature is a refusal, not a guess.
    for kw in ({"ncallees": 4}, {"loops": 3}, {"loads": 10}, {"cmps": 2}):
        elf, _want = _build_shape_elf(**kw)
        idx = valpatch._index_text(elf)
        assert valpatch._by_shape(elf, idx) is None, kw


# --- composing with other in-place firmware edits ----------------------------
# The bypass is the LAST writer of the game ELF's .sidx record, so any OTHER
# in-place edit this same Write makes to that file (today: the game-program
# display-text patches, plugins.stern.progtext) has to be folded into the
# digest it computes.  Without that the record describes a firmware that never
# reaches the card, and ``spk`` rejects it -- a modded card that fails
# validation for a reason nothing in the log mentions.

class _StubReader:
    """The slice of Ext4Reader compute_writes touches: one firmware file and
    one .sidx manifest, both mapped 1:1 onto a flat 'disk'."""

    FW_DISK = 0x10000
    SIDX_DISK = 0x80000

    def __init__(self, elf, sidx_blob):
        self.elf = elf
        self.sidx_blob = sidx_blob
        self.fw_node = {"i_block": b"\x01" * 60, "size": len(elf)}
        self.sidx_node = {"i_block": b"\x02" * 60, "size": len(sidx_blob)}

    def find_spike_assets(self):
        return 2, 3

    def read_inode(self, ino):
        return self.fw_node if ino == 3 else self.sidx_node

    def read_file_bytes(self, node):
        return (self.elf if node is self.fw_node else self.sidx_blob)

    def disk_ranges(self, node, off, length):
        base = (self.FW_DISK if node is self.fw_node else self.SIDX_DISK)
        return [(base + off, length)]

    def iter_regular_files(self, min_size=1, max_depth=20):
        yield "/gz/game", 3, self.fw_node
        yield "/spk/index/a.sidx", 4, self.sidx_node


def _stub_sidx(paths):
    """A minimal FI64 .sidx carrying a record per path (only the layout
    parse_records + record_field_writes read)."""
    from pinball_decryptor.plugins.stern import sidx as _sidx
    blob = bytearray(b"SIDX" + b"\x00" * 12)
    blob += b"STRS" + struct.pack("<I", sum(len(p) + 1 for p in paths))
    for p in paths:
        blob += p.encode() + b"\x00"
    for _p in paths:
        blob += b"FI64" + struct.pack("<I", 128) + b"\x00" * 128
    return bytes(blob)


def test_compute_writes_folds_other_firmware_edits_into_the_sidx_digest():
    import hashlib
    import hmac

    from pinball_decryptor.plugins.stern import sidx as _sidx

    elf = _build_elf(inline_crc_loops=5, trailer=VALIDATOR_STRINGS)
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    recs, _crc, fmt = _sidx.parse_records(blob)
    if "gz/game" not in recs:
        import pytest
        pytest.skip("stub .sidx doesn't parse on this format revision")

    # a text-style edit elsewhere in the ELF, exactly as progtext emits it:
    # a shorter string NUL-padded into the original's byte budget
    tail = len(elf) - len(VALIDATOR_STRINGS)
    overlay = {tail: b"CARD BAD".ljust(len(b"GAME VALIDATION ERROR"), b"\x00")}
    assert elf[tail:tail + len(overlay[tail])] != overlay[tail]

    rdr = _StubReader(elf, blob)
    msgs = []
    writes, status = valpatch.compute_writes(
        rdr, lambda m, lvl="info": msgs.append(m), fw_overlay=overlay)
    assert status[0] == "bypassed"

    # The digest must be of ELF + overlay + bx lr — the file that ships.
    eoff = valpatch.find_validation_exec(elf)
    shipped = bytearray(elf)
    for o, b in overlay.items():
        shipped[o:o + len(b)] = b
    shipped[eoff:eoff + 4] = valpatch._BX_LR
    want_h = hmac.new(_sidx.SIDX_KEY, bytes(shipped), hashlib.sha1).digest()
    want_m = hashlib.md5(bytes(shipped)).digest()
    by_disk = dict(writes)
    for foff, b in _sidx.record_field_writes(recs["gz/game"], want_h, want_m,
                                             fmt):
        assert by_disk[_StubReader.SIDX_DISK + foff] == b

    # and NOT of the stock ELF + bx lr alone (the bug this pins)
    stock = bytearray(elf)
    stock[eoff:eoff + 4] = valpatch._BX_LR
    bad_h = hmac.new(_sidx.SIDX_KEY, bytes(stock), hashlib.sha1).digest()
    assert want_h != bad_h


# ---- item 98: the grade restore is switched off with the tick ---------------------------
_RESTORE_SEQ = (0xE3A00050, 0xE3A01F85, 0xE1A02004, 0xE3A03080, 0xEB000123, 0xE3500000, 0x1A000004)


def _with_restore(elf, at_words_from_text_end=40):
    """The restore call's five-instruction shape spliced over NOPs near the end of .text."""
    b = bytearray(elf)
    off = TEXT_OFF + (NWORDS - at_words_from_text_end) * 4
    for k, w in enumerate(_RESTORE_SEQ):
        struct.pack_into("<I", b, off + 4 * k, w)
    return bytes(b), off + 16


def test_the_grade_restore_is_found_by_its_shape_and_patched_with_the_tick():
    elf, bl_off = _with_restore(_build_elf())
    assert valpatch.find_grade_restore(elf) == bl_off
    overlay, status = valpatch.bypass_overlay(elf)
    assert status == ("bypassed", "")
    assert overlay == {valpatch.find_validation_exec(elf): valpatch._BX_LR, bl_off: valpatch._MOV_R0_0}
    # idempotent: the patched call still matches, and the overlay is the same
    patched = bytearray(elf)
    for off, b in overlay.items():
        patched[off:off + 4] = b
    assert valpatch.find_grade_restore(bytes(patched)) == bl_off
    assert valpatch.bypass_overlay(bytes(patched))[0] == overlay


def test_without_the_restore_shape_the_tick_alone_is_patched():
    elf = _build_elf()
    assert valpatch.find_grade_restore(elf) is None
    overlay, _status = valpatch.bypass_overlay(elf)
    assert list(overlay) == [valpatch.find_validation_exec(elf)]


def test_two_restore_shapes_are_no_answer():
    elf, _first = _with_restore(_build_elf(), 40)
    elf, _second = _with_restore(elf, 60)
    assert valpatch.find_grade_restore(elf) is None
