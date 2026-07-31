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
does, so on its own it can miss: a build that factored its CRC32 out of line
would carry no ``0xEDB88320`` immediate in ``.text`` at all.  So there is a
second, independent locator (:func:`_by_shape`) keyed on the routine's measured
*shape* -- 1537-1547 instructions, exactly 22 callees, 92 backward branches,
269 loads, one caller.  That profile is stable across every build generation on
hand and, required in full, selects the validator and nothing else on all 35
vendor cards that carry it.  Two locators that agree 35/35 make a miss much
less likely than one; if both come up empty on a firmware that *does* carry
CRC32 machinery, the Write says so loudly rather than shipping a card whose
validator is still live.

**Jaws LE 1.01.0 remains unexplained, and is treated as unsafe rather than
solved.**  Neither locator finds anything in either of its game binaries
(``/jaws_le/game`` and ``spike_menu/game``); no ELF anywhere on that card holds
more than one ``0xEDB88320``; it is not Thumb (same ``e_flags`` and ARM entry
as every other card); and its six ``#N ... UPDATE SD CARD`` messages are
present and byte-identical.  Tracing back from those messages doesn't help
either -- on the cards where the validator *is* known, nothing referencing them
calls it or is called by it, so they are reached through data tables.

It is tempting to read all that as "Jaws has no validator", and to stay quiet
about it.  That is an argument from ignorance: it infers absence from our own
signature failing, on a *newer* title, where a vendor is far likelier to have
strengthened the check than dropped it.  Whatever that build does is simply
unknown, so :func:`carries_validator` keeps trusting the messages and the Write
warns.  A warning on a card that may not need one is cheap; silence on a card
that does need one is a hardware test that fails for reasons the user cannot
see.

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
# byte-identical in every Spike 2 firmware checked (all 36 cards in the vendor
# library, Jaws included).  They are the validator's user-visible output, so a
# build carrying them is assumed to still perform the check -- see
# :func:`carries_validator` for why that assumption is the safe one.
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

    Two independent locators, tried in order.  :func:`_by_crc32_immediates`
    picks the function holding the most inlined ``0xEDB88320`` constants (the
    validator has several such loops; nothing else has more than one).  If that
    finds nothing -- which is what a build that stopped inlining its CRC32
    would look like -- :func:`_by_shape` matches the routine's measured shape
    instead.  Either way the entry must be a ``push {..., lr}`` prologue, or the
    ``bx lr`` this module already put there, else we refuse (wrong match /
    non-ARM image).

    The two were checked against each other over the whole vendor library: on
    all 35 cards that carry the validator they select the same single function,
    and the shape locator raises no false positive on any of them.

    Accepting our own patch is what makes this idempotent.  Only the 4-byte
    prologue is overwritten, so a already-bypassed firmware still carries the
    CRC32 loops and still resolves to the same function; without that case the
    routine "disappeared" the moment it was patched, and re-running a Write
    against an already-modded image (or a second Direct-SD write onto a card
    that is already modded) would report the validator as unreachable and warn
    about a card that is in fact correctly patched."""
    idx = _index_text(elf)
    if idx is None:
        return None
    entry = _by_crc32_immediates(elf, idx)
    if entry is None:
        # A build that factors its CRC32 out of line carries no 0xEDB88320
        # immediate at all.  The shape of the routine is unchanged, though, so
        # fall back to that (see :func:`_by_shape`).
        entry = _by_shape(elf, idx)
    if entry is None:
        return None
    eoff = entry - idx["code_base"]
    if not _entry_ok(elf, eoff):
        return None
    return eoff


def _entry_ok(elf, eoff):
    """The word at *eoff* must be a ``push {..., lr}`` prologue, or the
    ``bx lr`` this module already wrote there (which is what makes locating
    idempotent -- see :func:`find_validation_exec`)."""
    if bytes(elf[eoff:eoff + 4]) == _BX_LR:
        return True
    w = struct.unpack_from("<I", elf, eoff)[0]
    # ``push {..., lr}`` == STMDB sp!, reglist: bits[27:20]=0x92, Rn=sp(13), bit14(lr)
    return (((w >> 20) & 0xFF) == 0x92 and ((w >> 16) & 0xF) == 13
            and bool(w & 0x4000))


def _index_text(elf):
    """One pass over ``.text``: function entries (BL targets), how many times
    each is called, and every ``0xEDB88320`` immediate site.

    Both locators share this, so a Write pays for it once."""
    if elf[:4] != b"\x7fELF" or elf[4] != 1:
        return None
    ts = _text_section(elf)
    if ts is None:
        return None
    tva, toff, tsz = ts
    code_base = tva - toff                    # vaddr = file_off + code_base
    ncalls = {}
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
            t = va + 8 + (imm << 2)
            ncalls[t] = ncalls.get(t, 0) + 1
        top = (w >> 20) & 0xFF
        rd = (w >> 12) & 0xF
        if top == 0x30:                       # movw rd, #imm16
            movw[rd] = (((w >> 16) & 0xF) << 12) | (w & 0xFFF)
        elif top == 0x34 and rd in movw:      # movt rd, #imm16
            full = (((((w >> 16) & 0xF) << 12) | (w & 0xFFF)) << 16) | movw[rd]
            if full == _CRC32_POLY:
                crc_sites.append(va)
    ents = sorted(e for e in ncalls if tva <= e < tva + tsz)
    return dict(tva=tva, toff=toff, tsz=tsz, code_base=code_base, ents=ents,
                ncalls=ncalls, crc_sites=crc_sites)


def _by_crc32_immediates(elf, idx):
    """The function containing the most inlined ``0xEDB88320`` constants."""
    import bisect
    from collections import Counter
    if not idx["crc_sites"]:
        return None
    ents = idx["ents"]

    def enclosing(a):
        j = bisect.bisect_right(ents, a) - 1
        return ents[j] if j >= 0 else None

    entry, n = Counter(enclosing(s)
                       for s in idx["crc_sites"]).most_common(1)[0]
    return None if (entry is None or n < 3) else entry


# The validator's shape, measured on every one of the 35 vendor cards that
# carry it.  It is one function, essentially unchanged across every build
# generation on hand (Led Zeppelin 1.20-1.22, TMNT 1.58-1.59, Elvira
# 1.11-1.13, King Kong 0.96, X-Men 0.97, ...): 1537-1547 instructions, exactly
# 22 callees, 92 backward branches, 269 loads.  The bands below are those
# measurements with headroom.  Requiring all six, plus a single caller and a
# ``push {..., lr}`` prologue, picked the right function and ONLY the right
# function on 35 of 35 cards -- and nothing at all on Jaws.
_SHAPE = {"words": (1400, 1700), "ncallees": (20, 24), "loops": (80, 105),
          "loads": (240, 300), "stores": (180, 215), "cmp": (140, 170)}
_SHAPE_CAP = 0x4000                            # ~4x the routine; bounds a scan


def _shape_of(elf, idx, fn):
    """Count the shape features of the function entered at *fn* (a vaddr)."""
    import bisect
    ents, cb = idx["ents"], idx["code_base"]
    j = bisect.bisect_right(ents, fn)
    hi = min(ents[j] if j < len(ents) else fn + _SHAPE_CAP, fn + _SHAPE_CAP,
             idx["tva"] + idx["tsz"],          # never past .text...
             len(elf) + cb)                    # ...nor past the file itself
    hi = max(hi, fn)
    callees = set()
    loops = loads = stores = cmps = 0
    for a in range(fn, hi, 4):
        w = struct.unpack_from("<I", elf, a - cb)[0]
        if ((w >> 25) & 0x7) == 0b101:                    # B / BL
            imm = w & 0xFFFFFF
            if imm & 0x800000:
                imm -= 0x1000000
            t = a + 8 + (imm << 2)
            if (w >> 24) & 1:
                callees.add(t)
            elif t < a:
                loops += 1                                # backward = loop
        if ((w >> 26) & 0x3) == 0b01:                     # load/store
            if (w >> 20) & 1:
                loads += 1
            else:
                stores += 1
        if (((w >> 26) & 0x3) == 0b00 and ((w >> 28) & 0xF) != 0xF
                and ((w >> 21) & 0xF) == 0xA):            # CMP
            cmps += 1
    return {"words": (hi - fn) // 4, "ncallees": len(callees), "loops": loops,
            "loads": loads, "stores": stores, "cmp": cmps}


def _by_shape(elf, idx):
    """The one function matching the validator's measured shape, or ``None``.

    Independent of how the CRC32 is emitted, so it still finds the routine on a
    build that stopped inlining the polynomial.  Deliberately all-or-nothing:
    it returns a function only when exactly one candidate matches every band,
    because patching four bytes into the wrong function is how the pre-v0.94.0
    cave landed on Elvira's node board table."""
    hits = []
    for fn in idx["ents"]:
        if idx["ncalls"].get(fn) != 1:        # the validator has one caller
            continue
        if not _entry_ok(elf, fn - idx["code_base"]):
            continue
        s = _shape_of(elf, idx, fn)
        if all(lo <= s[k] <= hi for k, (lo, hi) in _SHAPE.items()):
            hits.append(fn)
            if len(hits) > 1:                 # ambiguous -> refuse
                return None
    return hits[0] if hits else None


def carries_validator(elf):
    """True when *elf* should be assumed to carry Stern's self/asset validator.

    Keyed on the validator's six on-LCD ``#N ... UPDATE SD CARD`` messages
    rather than on any code shape, so it stays true for a firmware neither
    locator can match.  That distinction is the whole point: without it, "this
    title has no validator" (harmless) and "this title's validator is still
    armed and we couldn't reach it" (ships a card that errors on the machine)
    look identical to the Write.

    It is deliberately the *cautious* test, and the caution is load-bearing.
    Jaws LE 1.01.0 ships these messages while neither locator finds anything in
    either of its game binaries, its ``.text`` holds no ``0xEDB88320`` at all,
    and it is not Thumb -- so what that build actually does is unknown.  It
    would be easy to read "our signature found nothing" as "there is nothing
    there" and stay quiet; that is an argument from ignorance, and getting it
    wrong means silently shipping a card the machine rejects.  Reporting the
    uncertainty costs a warning on a card that may not need one.  Staying quiet
    costs a bricked test run, so this errs toward the warning.
    """
    return len(_ERR_MSG_RE.findall(elf)) >= 4


def bypass_status(elf, eoff):
    """``(kind, why)`` describing what the bypass achieved on *elf*, where
    *eoff* is :func:`find_validation_exec`'s answer.

    ``("bypassed", "")`` the validator was found and neutered; ``("absent", "")``
    this firmware shows no sign of a validator, so there was nothing to do; and
    ``("unlocated", why)`` the firmware looks like it carries one but neither
    locator could pin the routine -- the case a card must never ship on
    silently.  ``unlocated`` states uncertainty, not a diagnosis: it is what
    Jaws LE 1.01.0 reports, and what that build actually does is unknown (see
    the module docstring)."""
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
