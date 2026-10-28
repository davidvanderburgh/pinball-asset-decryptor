"""A final wizard that does not end the game (PAD-786).

A Pinside user asked for a way to turn off "the wizard modes that END THE GAME": on Godzilla (King of the
Monsters), James Bond (Her Majesty's Secret Service), Jaws (Super Celebration Multiball), John Wick (Special
Assignment), Jurassic Park (When Dinosaurs Ruled the Earth) and Elvira (Wild Market Value) - the wizards as
pinballrulesheets.com names them; the flags below confirm Bond's, John Wick's and Elvira's - the final wizard, once
played, ends the player's game: every ball they have left is ended the moment it starts.  No adjustment controls it.

HOW THE GAME DOES IT (emulator, Godzilla LE 1.16).  The framework's ball start has two handlers on it:

* a REFUSAL (bus 0x25, Godzilla LE 0x5612c): when the player's final wizard is over it puts up a screen and answers
  0, which skips the ball's start (its ball save, skill shot, serve);
* an ENDER (bus 0x26, 0x56228): when it is over it starts a process whose body is a single ``b <end of ball>``
  (0x55660 -> 0x2a7cc8), so the ball ends at once; the next ball goes the same way, then GAME OVER.

Both read the same condition, which comes in three shapes:

* ``WORD`` (Godzilla, Jurassic Park): a per-player word of a rule singleton, ``ldr rX, [r0, #0x34]`` after
  ``add r0, base, player, lsl #2``.  King of the Monsters writes it.
* ``FLAG`` (James Bond, Elvira, John Wick): a game flag, ``mov r0, #id; bl get_flag``, whose name ends in
  ``_PLAYED`` (FG_WIZARD_MODE_MULTIBALL_PLAYED, FG_WILD_MARKET_VALUE_PLAYED, FG_SPECIAL_ASSIGNMENT_MODE_PLAYED).
  John Wick's ender also ends a challenge game's ball by the game-play mode; that test is left alone.
* ``STATE`` (Jaws): a shared condition function that switches on the game-play mode; the Standard game's case reads
  a mode's per-player state (``ldr r0, [r0, #N]; sub r0, r0, #K; clz``) and the challenges have cases of their own.

The patch makes the final wizard's part of the condition read "not over": the WORD load and the STATE load become
``mov rX, #0``, the FLAG call ``mov r0, #0``.  Size-neutral, every site checked against its expected word.  On WORD
titles the word is also what a challenge game of that wizard ends by (Godzilla's King of the Monsters challenges),
so with the option on such a challenge game plays on after the wizard as an ordinary game would.

Found generically: the ball advance (``mov r0, #0x90`` ... ``mov r0, #0x91``), the end of ball that calls it, the
one-word stub that branches to it, and the handler that starts the stub; nothing per address.  A build whose ender
matches none of the shapes is offered nothing.
"""
import struct

from .coin_door import _Elf

WORD, FLAG, STATE = "word", "flag", "state"

_NOP_MOV0 = 0xE3A00000          # mov rX, #0 (rX at bits 12-15)
_RET = (0xE12FFF1E,)            # bx lr


def _bl_target(va, w):
    if (w & 0x0E000000) == 0x0A000000 and (w >> 28) == 0xE:
        o = w & 0xFFFFFF
        if o & 0x800000:
            o -= 1 << 24
        return va + 8 + o * 4
    return None


def _is_bl(w):
    return (w & 0x0F000000) == 0x0B000000 and (w >> 28) == 0xE


def _mov_imm(w, rd=None):
    """``mov rd, #imm`` (cond AL) -> imm, else None."""
    if (w & 0xFFF00000) != 0xE3A00000 or (rd is not None and (w >> 12) & 0xF != rd):
        return None
    rot = ((w >> 8) & 0xF) * 2
    imm = w & 0xFF
    return ((imm >> rot) | (imm << (32 - rot))) & 0xFFFFFFFF


def _movw(w):
    if (w & 0xFFF00000) == 0xE3000000:
        return (w >> 12) & 0xF, ((w >> 4) & 0xF000) | (w & 0xFFF)
    return None


def _movt(w):
    if (w & 0xFFF00000) == 0xE3400000:
        return (w >> 12) & 0xF, ((w >> 4) & 0xF000) | (w & 0xFFF)
    return None


class _Text:
    def __init__(self, elf):
        o, v, f = elf.text
        self.elf, self.base, self.n = elf, v, f // 4
        self.w = struct.unpack_from("<%dI" % self.n, elf.b, o)

    def at(self, va):
        i = (va - self.base) // 4
        return self.w[i] if 0 <= i < self.n else None

    def items(self):
        return ((self.base + 4 * i, w) for i, w in enumerate(self.w))

    def func_start(self, va):
        """The ``push {..., lr}`` at or before *va*, stepping over a hoisted movw/movt (+ ldr) pair."""
        i = (va - self.base) // 4
        while i >= 0:
            if (self.w[i] & 0xFFFF4000) == 0xE92D4000:
                j = i
                while j > 0 and (_movw(self.w[j - 1]) or _movt(self.w[j - 1])
                                 or (self.w[j - 1] & 0x0FF00000) == 0x05900000 and (self.w[j - 1] >> 28) == 0xE
                                 and j >= i - 3):
                    j -= 1
                return self.base + 4 * j
            i -= 1
        return None


def _enders(t):
    """``[(stub va, end-of-ball va, the ender's use va)]``: every handler that starts a one-word stub of the end of
    ball, found from the ball advance."""
    advs = set()
    for va, w in t.items():
        if w == 0xE3A00090:
            for k in range(1, 12):
                if t.at(va + 4 * k) == 0xE3A00091:
                    s = t.func_start(va)
                    if s is not None:
                        advs.add(s)
                    break
    if not advs:
        return []
    ends = set()
    for va, w in t.items():
        if _is_bl(w) and _bl_target(va, w) in advs:
            s = t.func_start(va)
            if s is not None:
                ends.add(s)
    stubs = []
    for va, w in t.items():
        tgt = _bl_target(va, w)
        if tgt in ends and not (w & 0x01000000):
            prev = t.at(va - 4)
            if prev in _RET or (prev is not None and ((prev & 0xFFFF8000) == 0xE8BD8000
                                                      or (prev & 0x0E000000) == 0x0A000000)):
                stubs.append((va, tgt))
    out = []
    for sva, eva in stubs:
        lo, hi = sva & 0xFFFF, sva >> 16
        for va, w in t.items():
            mw = _movw(w)
            if not mw or mw[1] != lo:
                continue
            for k in range(1, 6):
                mt = _movt(t.at(va + 4 * k) or 0)
                if mt and mt[0] == mw[0] and mt[1] == hi:
                    out.append((sva, eva, va))
                    break
    return out


def _flag_names(elf):
    """``index -> name`` reader of the plain-C titles' FG_ name table, or None."""
    i = elf.b.find(b"FG_INVALID\0")
    if i < 0:
        return None
    nva = elf.va(i)
    p = struct.pack("<I", nva)
    j = elf.b.find(p)
    while j >= 0:
        if j % 4 == 0:
            nxt = struct.unpack_from("<I", elf.b, j + 4)[0]
            s = elf.cstr(nxt)
            if s and s.startswith("FG_"):
                base = j

                def name(k):
                    o = base + 4 * k
                    if o + 4 > len(elf.b):
                        return None
                    return elf.cstr(struct.unpack_from("<I", elf.b, o)[0])
                return name
        j = elf.b.find(p, j + 1)
    return None


def _ld_offset(w):
    """``ldr rt, [rn, #+imm]`` (cond AL, word) -> (rt, rn, imm), else None."""
    if (w & 0xFFF00000) == 0xE5900000:
        return (w >> 12) & 0xF, (w >> 16) & 0xF, w & 0xFFF
    return None


def _cond_target(va, w):
    """The target of a conditional ``b`` at *va*."""
    return _bl_target(va, (w & 0x0FFFFFFF) | 0xE0000000) if (w & 0x0E000000) == 0x0A000000 else None


def _add_scaled(w):
    """``add r0, rB, r0, lsl #2`` -> rB, else None."""
    if (w & 0xFFF0FFFF) == 0xE0800100:
        return (w >> 16) & 0xF
    return None


def _returns_one(t, va):
    """The refusal's "not over" answer right after its test at *va*: ``moveq r0, #1``, or ``beq`` to ``mov r0, #1``."""
    w = t.at(va) or 0
    if w == 0x03A00001:
        return True
    if (w & 0xFF000000) == 0x0A000000:
        return t.at(_cond_target(va, w)) == 0xE3A00001
    return False


def _word_sites(t, ender, use):
    """WORD: the ender's ``add r0, rB, r0, lsl #2; ldr rX, [r0, #off]; cmp rX, #0; bne <use>`` and the refusal that
    reads the same base and offset and answers 1 when it is clear."""
    site = None
    for va in range(ender, use, 4):
        ld = _ld_offset(t.at(va) or 0)
        if not ld or ld[1] != 0:
            continue
        rt, _rn, off = ld
        rb = _add_scaled(t.at(va - 4) or 0)
        br = t.at(va + 8) or 0
        if rb is None or t.at(va + 4) != (0xE3500000 | rt << 16) or (br & 0xFF000000) != 0x1A000000                 or _cond_target(va + 8, br) != use:
            continue
        base = _base_before(t, va - 4, rb)
        if base is not None:
            site = (va, rt, off, base)
            break
    if site is None:
        return None
    va, rt, off, base = site
    sites = [(va, t.at(va), _NOP_MOV0 | rt << 12)]
    for v, w in t.items():
        ld = _ld_offset(w)
        if v == va or not ld or ld[1] != 0 or ld[2] != off:
            continue
        rt2 = ld[0]
        rb = _add_scaled(t.at(v - 4) or 0)
        if rb is None or t.at(v + 4) != (0xE3500000 | rt2 << 16) or not _returns_one(t, v + 8):
            continue
        if _base_before(t, v - 4, rb) == base:
            sites.append((v, w, _NOP_MOV0 | rt2 << 12))
    return _with_nearest(sites)


#: how far from the ender its refusal may be: the two are registered side by side (they sat 0xf8 - 0x830 apart on
#: every build that has them)
NEAR = 0x2000


def _with_nearest(sites):
    """The ender's site and the one refusal nearest it (within :data:`NEAR`), or None."""
    first, rest = sites[0], [x for x in sites[1:] if abs(x[0] - sites[0][0]) <= NEAR]
    if not rest:
        return None
    return [first, min(rest, key=lambda x: abs(x[0] - first[0]))]


def _base_before(t, va, reg):
    """The 32-bit constant a movw/movt pair put in *reg* in the few words before *va*."""
    lo = hi = None
    for k in range(1, 10):
        w = t.at(va - 4 * k) or 0
        mw, mt = _movw(w), _movt(w)
        if mt and mt[0] == reg and hi is None:
            hi = mt[1]
        if mw and mw[0] == reg and lo is None:
            lo = mw[1]
        if lo is not None and hi is not None:
            return hi << 16 | lo
    return None


def _flag_sites(t, elf, ender, use):
    """FLAG: the ender's ``mov r0, #id; bl get`` of a ``..._PLAYED`` flag and the refusal's same read followed by
    ``cmp r0, #0; moveq r0, #1``."""
    names = _flag_names(elf)
    if names is None:
        return None
    hit = None
    for va in range(ender, use, 4):
        imm = _mov_imm(t.at(va) or 0, 0)
        nxt = t.at(va + 4) or 0
        if imm is None or not _is_bl(nxt):
            continue
        n = names(imm)
        if n and n.endswith("_PLAYED"):
            hit = (imm, _bl_target(va + 4, nxt), va + 4, n)
            break
    if hit is None:
        return None
    flag, get, ender_bl, name = hit
    sites = [(ender_bl, t.at(ender_bl), _NOP_MOV0)]
    for v, w in t.items():
        if v == ender_bl or not _is_bl(w) or _bl_target(v, w) != get:
            continue
        if not any(_mov_imm(t.at(v - 4 * k) or 0, 0) == flag for k in (1, 2, 3)):
            continue
        if t.at(v + 4) == 0xE3500000 and _returns_one(t, v + 8):
            sites.append((v, w, _NOP_MOV0))
    sites = _with_nearest(sites)
    return (sites, name) if sites else None


def _state_sites(t, ender, use):
    """STATE: the ender opens with ``bl C; subs r4, r0, #0; bne <use>``; C switches on the game-play mode with a
    jump table, and the Standard game's case (index 1) reads ``ldr r0, [r0, #N]; sub r0, r0, #K; clz r0, r0``."""
    first = t.at(ender + 4) or 0
    if not _is_bl(first):
        return None
    cond = _bl_target(ender + 4, first)
    if ((t.at(ender + 8) or 0) & 0xFFFF0FFF) != 0xE2500000 or ((t.at(ender + 12) or 0) & 0xFF000000) != 0x1A000000:
        return None
    jt = None
    for k in range(0, 24):
        w = t.at(cond + 4 * k) or 0
        if (w & 0xFFFFF000) == 0x979FF000:          # ldrls pc, [pc, rX, lsl #2]
            jt = cond + 4 * k + 8
            break
    if jt is None:
        return None
    case = t.at(jt)                                   # the table is indexed by mode - 1: [0] = Standard (1)
    if case is None or not (t.base <= case < t.base + 4 * t.n):
        return None
    for k in range(0, 24):
        va = case + 4 * k
        ld = _ld_offset(t.at(va) or 0)
        if ld and ld[0] == 0 and ld[1] == 0 and ((t.at(va + 4) or 0) & 0xFFFFF000) == 0xE2400000 \
                and t.at(va + 8) == 0xE16F0F10:
            return [(va, t.at(va), _NOP_MOV0)]
    return None


def plan(elf_bytes):
    """``{"shape", "sites": [(va, old word, new word)], "flag"?}`` for a build whose final wizard ends the game in a
    shape this module knows, else None (nothing is offered)."""
    try:
        elf = _Elf(elf_bytes)
    except (ValueError, struct.error):
        return None
    t = _Text(elf)
    found = _enders(t)
    if len(found) != 1:
        return None
    _stub, _end, use = found[0]
    ender = t.func_start(use)
    if ender is None:
        return None
    sites = _word_sites(t, ender, use)
    if sites:
        return {"shape": WORD, "sites": sites}
    fs = _flag_sites(t, elf, ender, use)
    if fs:
        return {"shape": FLAG, "sites": fs[0], "flag": fs[1]}
    sites = _state_sites(t, ender, use)
    if sites:
        return {"shape": STATE, "sites": sites}
    return None


def patched_bytes(elf_bytes, p=None):
    """*elf_bytes* with the final wizard's part of the condition reading "not over" (see the module doc).  Same
    size; every site must hold its expected word."""
    p = p or plan(elf_bytes)
    if not p:
        raise ValueError("this build's final wizard is not one this app can stop from ending the game")
    elf = _Elf(elf_bytes)
    out = bytearray(elf_bytes)
    for va, old, new in p["sites"]:
        o = elf.off(va)
        if o is None or struct.unpack_from("<I", out, o)[0] != old:
            raise ValueError("the final wizard patch site at 0x%x is not what was planned" % va)
        struct.pack_into("<I", out, o, new)
    return bytes(out)
