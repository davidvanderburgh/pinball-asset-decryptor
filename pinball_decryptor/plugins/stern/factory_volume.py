"""The volume a Spike 2 machine actually comes up at — which is NOT the
``AD_SOUND_MASTER_VOLUME_SETTING`` compiled default.

A tester reported three times that staging Master Volume = 24 still left his
machine's first-boot Guided Setup showing 30.  The firmware says why.  Its
master-volume getter is::

    mov  r0, #17                 ; AD_SOUND_MASTER_VOLUME_SETTING
    bl   get_adjustment          ; stored value, or the compiled default
    uxtb r4, r0
    cmp  r4, #0x3f               ; 63
    bls  done                    ; <= 63 -> use it
    movw r3, #...  / movt r3, #...
    ldrb r4, [r3]                ; else: the title's built-in volume
    bl   set_master_volume       ; ...and store THAT

and the operator menu's "reset the volumes" step reads the same byte and writes
it straight into the master volume.  Two consequences:

* Stern ships the compiled default as **64 on every one of the 34 vendor cards
  checked**, and 64 is one past the 63 the getter accepts — so the shipped
  default never survives, and a fresh machine always lands on the built-in
  byte instead (30 on Led Zeppelin, 10 on Godzilla and Jaws, 24 on John Wick,
  13 on Deadpool...).  That 30 is the number the tester kept seeing.
* Patching only the compiled default therefore fixes the first boot but not a
  later factory reset, which re-reads the byte.

So a "default master volume" that means anything has to move both, which is
what :func:`patched_bytes` does (the compiled default is
:mod:`.adjustments`' job).

Finding the byte is generic — no per-title addresses.  The adjustment id comes
from the title's own name table, the ``cmp #63`` and the ``ldrb`` off a
``movw``/``movt`` pair are the getter's shape, and the hunt **refuses to guess**
(:func:`find` returns ``None`` unless exactly one candidate matches and its
current value is a plausible volume), on the same reasoning as
:mod:`.menu_visibility`: writing a wrong byte into the game program is worse
than leaving the volume alone.
"""
import re
import struct

# The adjustment whose compiled default this byte overrules.
ADJUSTMENT = "AD_SOUND_MASTER_VOLUME_SETTING"
# The getter clamps to 0..63; the setter does the same on the way in, so this
# is the whole usable range of a Spike 2 master volume.
MAX_VOLUME = 0x3f

_MOV_R0_IMM = 0xE3A00000        # mov r0, #imm8
_CMP_IMM_MASK = 0xFFF00FFF      # cmp rN, #imm8, any rN
_CMP_63 = 0xE350003F            # cmp rN, #0x3f
_MOVW = 0x03000000
_MOVT = 0x03400000
_LDRB_MASK = 0x0FF00000
_LDRB = 0x05D00000              # ldrb rD, [rN, #imm12]

# How far past the `mov r0, #id` / `cmp` the rest of the shape may sit.  The
# compiler schedules a couple of unrelated instructions in between on some
# builds, but never more than a handful.
_CMP_WINDOW = 8
_LOAD_WINDOW = 10


def _u32s(data, off, count):
    return memoryview(data)[off:off + count * 4].cast("I")


def find(table):
    """Locate the title's built-in master volume.

    Returns ``{"va", "offset", "value"}`` — the address in the game ELF, its
    file offset, and the volume the machine will come up at — or ``None`` when
    this build doesn't match the known shape (an unfamiliar firmware, or more
    than one candidate).  *table* is an
    :class:`~.adjustments.AdjustmentTable`; its ``data`` is the ELF searched.
    """
    vol_id = table.by_name.get(ADJUSTMENT)
    if vol_id is None or vol_id > 0xff:
        # >255 can't be a bare `mov r0, #imm8`, so the shape below can't be
        # matched -- no title has needed it, and guessing at the alternative
        # encodings would be guessing.
        return None
    data = table.data
    po, _pv, fsz = table._loads[0]
    end = po + (fsz & ~3)
    pattern = struct.pack("<I", _MOV_R0_IMM | vol_id)
    hits = []
    for m in re.finditer(re.escape(pattern), data[po:end]):
        off = po + m.start()
        if off % 4:
            continue                       # inside some other instruction
        spot = _match(table, data, off, end)
        if spot is not None and spot not in hits:
            hits.append(spot)
    if len(hits) != 1:                     # nothing, or ambiguous: refuse
        return None
    return hits[0]


def _match(table, data, off, end):
    """The ``cmp #63`` + ``ldrb`` tail of the getter starting at *off*, as a
    ``{"va", "offset", "value"}`` spot, or ``None``."""
    words = _u32s(data, off, min(_CMP_WINDOW + _LOAD_WINDOW + 1,
                                 (end - off) // 4))
    for i in range(1, min(_CMP_WINDOW + 1, len(words))):
        if (words[i] & _CMP_IMM_MASK) != _CMP_63:
            continue
        pend = {}
        for j in range(i + 1, min(i + 1 + _LOAD_WINDOW, len(words))):
            w = words[j]
            op = w & 0x0FF00000
            rd = (w >> 12) & 0xf
            if op == _MOVW:
                pend[rd] = ((w >> 4) & 0xf000) | (w & 0xfff)
            elif op == _MOVT and rd in pend:
                pend[rd] = ((((w >> 4) & 0xf000) | (w & 0xfff)) << 16) \
                    | pend[rd]
            elif op == _LDRB and (w & 0xfff) == 0:
                addr = pend.get((w >> 16) & 0xf)
                if addr is not None:
                    return _spot(table, addr)
        return None                        # right cmp, wrong tail
    return None


def _spot(table, addr):
    """Validate *addr* as the built-in volume byte and describe it."""
    off = table._off(addr)
    if off is None:
        return None
    loads = table._loads
    if len(loads) > 1:
        po, _pv, fsz = loads[0]
        if po <= off < po + fsz:
            return None                    # in the code segment: not data
    value = table.data[off]
    if value > MAX_VOLUME:
        return None                        # not a volume this firmware accepts
    return {"va": addr, "offset": off, "value": value}


def patched_bytes(elf_bytes, spot, value):
    """*elf_bytes* with the built-in volume at *spot* set to *value*.

    One byte, so the card's ``.sidx`` refresh and every other patch are
    unaffected.  Raises ``ValueError`` outside 0..63 — the firmware would
    reject anything else and fall back to what it shipped with.
    """
    value = int(value)
    if not 0 <= value <= MAX_VOLUME:
        raise ValueError("master volume %d out of range [0, %d]"
                         % (value, MAX_VOLUME))
    buf = bytearray(elf_bytes)
    buf[spot["offset"]] = value
    return bytes(buf)
