"""Stern's SD-card validator bypass: finding it, and admitting when we can't.

``valpatch`` writes the four bytes that stop a modded Spike 2 card raising
``GAME VALIDATION ERROR / UPDATE SD CARD``, and it finds the routine to patch by
code signature -- the one function carrying several inlined CRC32-``0xEDB88320``
loops.  That signature describes how the firmware was *compiled*, not what it
does, so it can come up empty on a build that factors its CRC32 out of line:
across the 34 real vendor cards on hand it matches 33, and finds nothing at all
in Jaws LE 1.01.0, whose ``.text`` carries no ``0xEDB88320`` immediate anywhere.

A miss used to be indistinguishable from a title that carries no validator --
both logged "nothing to bypass" and the Write reported success -- so the user
got a card whose validator is fully armed and a machine that answers with the
validation error and reboots instead of starting a game (flippermeister, James
Bond with one replaced sound, 2026-07-31).  These tests pin the two halves:
the signature still finds a normal validator, and a firmware that carries the
validator without matching the signature is reported as a failure, not a no-op.
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


# The validator's own on-LCD messages, as Stern ships them (byte-identical on
# all 34 vendor cards checked, Jaws included).
VALIDATOR_STRINGS = (b"GAME VALIDATION ERROR\x00#6 %d:%d:%d UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#5 %d:%d UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#4 %d:%d UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#3 UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#2 UPDATE SD CARD\x00"
                     b"GAME VALIDATION ERROR\x00#1 UPDATE SD CARD\x00")


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

def test_carries_validator_reads_the_on_lcd_messages_not_the_code_shape():
    # The Jaws shape: the routine is there (its six numbered messages are) but
    # nothing in .text builds the polynomial, so the signature finds nothing.
    jaws_like = _build_elf(inline_crc_loops=0, trailer=VALIDATOR_STRINGS)
    assert valpatch.find_validation_exec(jaws_like) is None
    assert valpatch.carries_validator(jaws_like)


def test_a_firmware_without_the_messages_carries_no_validator():
    assert not valpatch.carries_validator(_build_elf(inline_crc_loops=0))


def test_status_calls_an_unreachable_validator_a_failure_not_a_no_op():
    jaws_like = _build_elf(inline_crc_loops=0, trailer=VALIDATOR_STRINGS)
    overlay, status = valpatch.bypass_overlay(jaws_like)
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
