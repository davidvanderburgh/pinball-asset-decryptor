"""Auto-neutralise Stern Spike 2's game self/asset validator on every write.

The ``game`` ELF **validates itself**: a master routine (``validation_exec``) runs
a state machine that CRC32s (polynomial ``0xEDB88320``) the protected game assets
*and the binary's own bytes*, sets persistent tamper flags, and raises the on-LCD
``#N %d:%d UPDATE SD CARD`` errors — the two counters are ``valid:failed``, so any
modified asset makes ``failed`` climb and trips it.  A modded card therefore shows
validation errors / tech alerts even though every edit is otherwise sound.

Because the self-check runs *inside* ``validation_exec``, overwriting that
function's entry with ``bx lr`` (return immediately) disables the asset checks,
the self-integrity check, and the tamper-flag writes in a single 4-byte,
size-neutral change — the check can no longer even detect its own patch.  The
game ELF's ``.sidx`` record is then refreshed so the *separate* ``spk`` integrity
layer still validates it.

``validation_exec`` is found by **signature** (the only function carrying several
inlined CRC32-``0xEDB88320`` loops), not a hardcoded address, so this works across
titles / editions / versions.

That signature is a property of how the firmware was *compiled*, not of what it
does, so it can miss: a build that factors its CRC32 out of line instead of
inlining it carries no ``0xEDB88320`` immediate in ``.text`` at all.  Jaws LE
1.01.0 is a shipped title exactly like that (33 of the 34 cards in the vendor
library match the signature; Jaws matches nothing).  A miss used to be
indistinguishable from a title that simply carries no validator, and both were
reported as a mild "nothing to bypass" note -- so the Write quietly shipped a
card whose validator is fully live, and the machine put up GAME VALIDATION ERROR
/ UPDATE SD CARD on a mod the user was told had built fine.
:func:`carries_validator` answers "is the validator in here at all?" from the
validator's own on-LCD strings, independently of the code shape, so the two
cases can be told apart and a miss is reported as the problem it is.

NOTE: the tamper *state* is stored on the machine's board i2c/nvram, NOT on the
SD card, so a machine that already booted an **unpatched** modded card can keep a
saved tamper flag until a settings/factory reset.  This patch prevents all *new*
tamper detection; it can't un-set a flag another card already wrote.
"""

import hashlib
import hmac
import re
import struct

_CRC32_POLY = 0xEDB88320
_BX_LR = bytes.fromhex("1eff2fe1")          # ARM A32 ``bx lr``

# The six numbered messages the validator puts on the LCD.  Stern ships them
# byte-identical in every Spike 2 firmware checked (34/34 cards in the vendor
# library, Jaws included), which makes them a code-shape-free answer to "does
# this title carry the validator?" -- see the module docstring.
_ERR_MSG_RE = re.compile(rb"#[1-6](?: %d:%d(?::%d)?)? UPDATE SD CARD\x00")


def _text_section(elf):
    """``(vaddr, file_offset, size)`` of the ELF ``.text`` section."""
    e_shoff = struct.unpack_from("<I", elf, 0x20)[0]
    e_shnum = struct.unpack_from("<H", elf, 0x30)[0]
    e_shstrndx = struct.unpack_from("<H", elf, 0x32)[0]
    e_shent = struct.unpack_from("<H", elf, 0x2e)[0]
    secs = [struct.unpack_from("<10I", elf, e_shoff + i * e_shent)
            for i in range(e_shnum)]
    shstr = secs[e_shstrndx][4]
    for s in secs:
        end = elf.index(b"\x00", shstr + s[0])
        if elf[shstr + s[0]:end] == b".text":
            return s[3], s[4], s[5]
    return None


def find_validation_exec(elf):
    """Return the ELF *file offset* of ``validation_exec``'s entry, or ``None``.

    Located structurally: collect BL (call) targets as function entries, find
    every ``0xEDB88320`` CRC32 immediate (built via ``movw``/``movt``), and pick
    the function that contains the most of them (the validator has several
    inlined CRC32 loops; nothing else has more than one).  The entry must be a
    ``push {..., lr}`` prologue, else we refuse (wrong match / non-ARM image)."""
    if elf[:4] != b"\x7fELF" or elf[4] != 1:
        return None
    ts = _text_section(elf)
    if ts is None:
        return None
    tva, toff, tsz = ts
    code_base = tva - toff                    # vaddr = file_off + code_base
    entries = set()
    crc_sites = []
    movw = {}
    for i in range(toff, toff + tsz, 4):
        w = struct.unpack_from("<I", elf, i)[0]
        va = i + code_base
        cond = (w >> 28) & 0xF
        if ((w >> 25) & 0x7) == 0b101 and ((w >> 24) & 1) == 1 and cond != 0xF:
            imm = w & 0xFFFFFF                 # BL -> function entry
            if imm & 0x800000:
                imm -= 0x1000000
            entries.add(va + 8 + (imm << 2))
        top = (w >> 20) & 0xFF
        rd = (w >> 12) & 0xF
        if top == 0x30:                       # movw rd, #imm16
            movw[rd] = (((w >> 16) & 0xF) << 12) | (w & 0xFFF)
        elif top == 0x34 and rd in movw:      # movt rd, #imm16
            full = (((((w >> 16) & 0xF) << 12) | (w & 0xFFF)) << 16) | movw[rd]
            if full == _CRC32_POLY:
                crc_sites.append(va)
    if not crc_sites:
        return None
    import bisect
    from collections import Counter
    ents = sorted(e for e in entries if tva <= e < tva + tsz)

    def enclosing(a):
        j = bisect.bisect_right(ents, a) - 1
        return ents[j] if j >= 0 else None

    entry, n = Counter(enclosing(s) for s in crc_sites).most_common(1)[0]
    if entry is None or n < 3:
        return None
    eoff = entry - code_base
    w = struct.unpack_from("<I", elf, eoff)[0]
    # ``push {..., lr}`` == STMDB sp!, reglist: bits[27:20]=0x92, Rn=sp(13), bit14(lr)
    if not (((w >> 20) & 0xFF) == 0x92 and ((w >> 16) & 0xF) == 13 and (w & 0x4000)):
        return None
    return eoff


def carries_validator(elf):
    """True when *elf* carries Stern's self/asset validator at all.

    Keyed on the validator's own ``#N ... UPDATE SD CARD`` messages rather than
    on any code shape, so it stays true for a firmware
    :func:`find_validation_exec` can't match.  That distinction is the whole
    point: without it, "this title has no validator" (harmless) and "this
    title's validator is still armed and we couldn't reach it" (ships a card
    that errors on the machine) look identical to the Write."""
    return len(_ERR_MSG_RE.findall(elf)) >= 4


def bypass_status(elf, eoff):
    """``(kind, why)`` describing what the bypass achieved on *elf*, where
    *eoff* is :func:`find_validation_exec`'s answer.

    ``("bypassed", "")`` the validator was found and neutered; ``("absent", "")``
    this firmware carries no validator, so there was nothing to do; and
    ``("unlocated", why)`` the firmware *does* carry one but its routine didn't
    match the signature -- the case a card must never ship on silently."""
    if eoff is not None:
        return ("bypassed", "")
    if carries_validator(elf):
        return ("unlocated",
                "this firmware's validator doesn't match the routine signature "
                "the bypass looks for")
    return ("absent", "")


def log_status(log, mode):
    """Report *mode* on the build log at a level that matches how bad it is."""
    kind, why = mode
    if kind == "bypassed":
        log("Applied Stern validation bypass: patched the game firmware so this "
            "modified card boots without the \"GAME VALIDATION ERROR / UPDATE SD "
            "CARD\" message or technician tamper alerts. (Disabled the game's "
            "self/asset validator and refreshed its SD-validation record to "
            "match.)", "success")
    elif kind == "absent":
        log("This game firmware carries no SD-card validator; nothing to "
            "bypass.", "info")
    else:
        log("COULD NOT disable this game's SD-card validator (%s). The card "
            "will still be built, but the game checks its own assets on boot, "
            "so the machine is likely to show \"GAME VALIDATION ERROR / UPDATE "
            "SD CARD\" and may reboot instead of starting a game. Please report "
            "the title and firmware version so the bypass can be taught this "
            "build." % why, "error")


def _game_manifest_path(reader, fw_node):
    """The ``.sidx`` manifest path for the game ELF (match by extent block)."""
    want = bytes(fw_node["i_block"])
    for path, _ino, node in reader.iter_regular_files(min_size=0x10000, max_depth=20):
        if bytes(node["i_block"]) == want:
            return path.lstrip("/")
    return None


def bypass_overlay(elf_bytes):
    """``({file_off: bytes}, status)`` neutering ``validation_exec`` inside
    *elf_bytes*, expressed against the game ELF's own file offsets rather than
    the card's.

    Used when the whole firmware file is being rebuilt and copied onto the card
    in one piece (the blip-free cave grows ``game_real``, so it can't be patched
    in place): the bypass has to be baked into that image, because a separate
    in-place write against the old inode would just be overwritten by the copy.
    The overlay is empty when no validator routine was matched; *status* (see
    :func:`bypass_status`) says whether that means there is none to match."""
    eoff = find_validation_exec(elf_bytes)
    overlay = {} if eoff is None else {eoff: _BX_LR}
    return overlay, bypass_status(elf_bytes, eoff)


def compute_writes(reader, log):
    """``([(disk_offset, bytes), ...], status)`` that neuter ``validation_exec``
    on the card behind *reader* and refresh the game ELF's ``.sidx`` record.

    Best-effort and non-fatal: returns no writes (and logs) if the game ELF or
    the validator can't be found, so it never breaks a Write for a title that
    doesn't carry the validator.  *status* (see :func:`bypass_status`) is what
    tells that harmless case apart from a firmware whose validator is still
    armed; ``None`` when the firmware itself couldn't be read.  Offsets are
    absolute (relative to the start of the card image / device), matching the
    rest of the Write's flat write list."""
    from . import sidx as _sidx
    try:
        _img_ino, fw_ino = reader.find_spike_assets()
        if not fw_ino:
            return [], None
        fw_node = reader.read_inode(fw_ino)
        elf = bytearray(reader.read_file_bytes(fw_node))
        eoff = find_validation_exec(bytes(elf))
        status = bypass_status(bytes(elf), eoff)
        if eoff is None:
            log_status(log, status)
            return [], status

        writes = []
        elf[eoff:eoff + 4] = _BX_LR            # patched bytes -> new sidx digest
        b = _BX_LR
        for disk, n in reader.disk_ranges(fw_node, eoff, 4):
            writes.append((disk, b[:n]))
            b = b[n:]

        # refresh the game ELF's .sidx record so ``spk`` still validates it
        sidx_path, sidx_node = _sidx.find_sidx(reader)
        if sidx_node is not None:
            sdata = reader.read_file_bytes(sidx_node)
            recs, _crc, fmt = _sidx.parse_records(sdata)
            game_path = _game_manifest_path(reader, fw_node)
            po = recs.get(game_path) if game_path else None
            if po is not None:
                hm, md = _sidx.digests(bytes(elf))
                for foff, rb in _sidx.record_field_writes(po, hm, md, fmt):
                    for disk, n in reader.disk_ranges(sidx_node, foff, len(rb)):
                        writes.append((disk, rb[:n]))
                        rb = rb[n:]
            else:
                log("Game ELF has no .sidx record; validation bypass applied but "
                    "the card may report an invalid-SD banner.", "warning")

        log_status(log, status)
        return writes, status
    except Exception as e:                     # never fail a Write over this
        log("Validation bypass skipped (%s)." % e, "warning")
        return [], None
