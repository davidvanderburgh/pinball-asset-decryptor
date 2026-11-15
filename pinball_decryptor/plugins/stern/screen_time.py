"""SCREEN TIMES (PAD-1115): a game screen that shows a clip for a fixed time lasts as long as the clip.

DoomWalrus666, Godzilla: "Some videos natively freeze frame at the end. It doesn't matter if the
clip is plenty long, it will freeze frame as normal game behavior. Examples: Secret Combo, Saucer
Attack." The game's award and battle-start screens (Godzilla's layered displays: BDLSecretComboAward,
BDLBigLoopAward, BDLBattleVSGiganStart ...) are objects of one base class, shared by Jaws and King Kong
in a later version. Each names its clip and its crop through two virtuals (``secret_combo`` /
``Normal``) and plays it, and each has a "done" check of its own, the virtual just before the clip's
name. MOST screens are done when their clip is (they ask the video surface whether it still plays), so
any clip plays whole. A few are done on a TIME: at its start the base class reads the screen's length
from a virtual (a float, in seconds: 3.0 unless the class has its own; Secret Combo's is 4.0) and the
check ends the screen when its clock passes it. There a shorter clip sits on its last frame for the
rest (the stock Secret Combo clip is 2.87 s: 1.1 s of a frozen frame), and a longer one is cut off.

THE FLEET (the 53 latest Spike 2 programs, PAD-1115): the screen framework is on Godzilla, Jaws and
King Kong (LE and Pro). The one screen that plays a clip once and ends on its time is Godzilla's Secret
Combo; Jaws times only screens that loop their clip (the time is what ends the loop, no freeze), and
King Kong's all end with their clip. Saucer Attack's videos are played by its mode, not a screen, and
follow their clip too. The reader finds whatever a newer build adds, with no list.

THE FIX. The build reads every such screen off the game program (:func:`screens`) and, for a
replaced clip whose length is not its screen's, writes an ``stime`` line into ``clips.cfg``
(:func:`cfg_lines`); the mode runtime points that screen's time virtual at a function of its own that
answers the clip's length (pad_mode_runtime.c "screen times"). A screen ends when its clip does: no
frozen frame, and a longer clip plays to its end.

WHAT A SCREEN IS, read off the program (no per-title table). Two facts of the base class come from its
code: its "done" check (``vldr s14, [r0, #elapsed]`` / ``vldr s15, [r0, #length]`` / ``vcmpe.f32 s14,
s15``) names the length field, and the start code that stores that field (``vstr s0, [rN, #length]``)
reads it from a vtable slot it first compares with the base's own function (:func:`time_slot`). A
screen is then a vtable whose entry names a clip (a ``movw r0`` / ``movt r0`` / ``bx lr`` string
getter), whose RTTI header sits just above it,
and whose time slot holds a constant float getter (``vldr s0, [pc, #n]`` / ``bx lr``); the clip's slot
is the one those timed vtables most often hold a string getter in, and the crop (the next one) is
read when it is a string too. Two versions of
the framework, both read this way: Godzilla 1.16 (clip slot 15, time slot 20; 26 screens, 3.0 s but
Secret Combo's 4.0 s) and Jaws / King Kong (clip slot 16, time slot 26; slot 23 is the delay before
the screen's sound, not its length).
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass

import numpy as np

#: ``PAD_STERN_SCREEN_TIME=0`` leaves every screen at the game's own time
GATE_ENV = "PAD_STERN_SCREEN_TIME"
#: slots from a screen's clip name to its play-it-looped flag (read off Godzilla's base: name, crop, loop)
LOOP_AFTER_CLIP = 2
#: a clip within this much of its screen's time needs no line (one frame at 30 fps, and a bit)
SAME_S = 0.05
#: the longest a screen may be made to last; a longer clip is cut there, as the game cuts it now
MAX_S = 120.0
#: how far above the clip's entry the vtable's RTTI header may be (Godzilla: 17 words)
MAX_HEAD_WORDS = 64

_MOVW_R0 = 0xE3000000
_MOVT_R0 = 0xE3400000
_BX_LR = 0xE12FFF1E
_VLDR_S0_PC = 0xED9F0A00              # vldr s0, [pc, #imm8*4]
_MASK_RD = 0xFFF0F000


def enabled():
    return os.environ.get(GATE_ENV, "1") != "0"


@dataclass(frozen=True)
class Screen:
    clip: str           # the clip's name, as the game asks for it
    crop: str           # where it plays ("Normal" full screen, "ScoreFrame" in the frame...)
    cls: str            # the class's own name (RTTI), "" when it has none
    vt: int             # the vtable's address point: what an object of the class holds at +0
    slot: int           # the address of its time virtual's entry
    old: int            # the word in that entry: the game's own time function
    seconds: float      # the time that function answers
    loops: bool = False # the screen plays its clip over and over (its time is no freeze, and is left alone)
    timed: bool = True  # its "done" check is its time; False: it ends when its clip does (no freeze, no cut)


def _imm16(w):
    return ((w >> 4) & 0xF000) | (w & 0xFFF)


def _cstr(elf, va, cap=96):
    o = elf.off(va)
    if o is None:
        return None
    end = elf.b.find(b"\0", o, o + cap)
    if end <= o:
        return None
    raw = elf.b[o:end]
    if any(c < 0x20 or c > 0x7E for c in raw):
        return None
    return raw.decode("ascii")


def _getters(elf):
    """``({fn: string}, {fn: float})`` - the text's constant string and float getters."""
    a = elf.arr
    n = len(a)
    if n < 3:
        return {}, {}
    w0, w1, w2 = a[:-2], a[1:-1], a[2:]
    s_idx = np.nonzero(((w0 & _MASK_RD) == _MOVW_R0) & ((w1 & _MASK_RD) == _MOVT_R0) & (w2 == _BX_LR))[0]
    strings = {}
    for i in s_idx.tolist():
        va = (_imm16(int(a[i + 1])) << 16) | _imm16(int(a[i]))
        s = _cstr(elf, va)
        if s:
            strings[elf.tva + 4 * i] = s
    f_idx = np.nonzero(((w0 & 0xFFFFFF00) == _VLDR_S0_PC) & (w1 == _BX_LR))[0]
    floats = {}
    for i in f_idx.tolist():
        lit = elf.tva + 4 * i + 8 + (int(a[i]) & 0xFF) * 4
        w = elf.word(lit)
        if w is not None:
            v = struct.unpack("<f", struct.pack("<I", w))[0]
            if v == v:                                   # not a NaN
                floats[elf.tva + 4 * i] = v
    return strings, floats


def _rtti_head(elf, entry):
    """``(vtable address point, class name)`` for the vtable *entry* is in: the first word above it
    that a ``[0, typeinfo]`` pair precedes, typeinfo's name a mangled one (``19BDLSecretComboAward``)."""
    for k in range(1, MAX_HEAD_WORDS):
        top = entry - 4 * k
        if elf.word(top - 8) != 0:
            continue
        ti = elf.word(top - 4)
        if not ti:
            continue
        name_va = elf.word(ti + 4)
        name = _cstr(elf, name_va) if name_va else None
        if name and name[0].isdigit():
            return top, name.lstrip("0123456789")
    return None, ""


_VLDR_S14_R0 = 0xED907A00           # vldr s14, [r0, #imm8*4]
_VLDR_S15_R0 = 0xEDD07A00           # vldr s15, [r0, #imm8*4]
_VCMPE_S14_S15 = 0xEEB47AE7
_VSTR_S0 = 0xED800A00               # vstr s0, [rN, #imm8*4] (rN at bits 16-19)
_LDR_IMM = 0xE5900000               # ldr rD, [rN, #imm12]
_CMP_REG = 0xE1500000               # cmp rN, rM


def _length_field(elf):
    """The byte offset of a screen's length field: the one most "elapsed > length" checks compare."""
    import collections
    a = elf.arr
    m = np.nonzero(((a[:-2] & 0xFFFFFF00) == _VLDR_S14_R0) & ((a[1:-1] & 0xFFFFFF00) == _VLDR_S15_R0)
                   & (a[2:] == _VCMPE_S14_S15))[0]
    fields = collections.Counter((int(a[i + 1]) & 0xFF) * 4 for i in m.tolist())
    return fields.most_common(1)[0][0] if fields else None


def _reads_field(elf, fn, field, depth=0):
    """Whether the function at *fn* (or one it calls, one level down) loads the float at ``[rN, #field]``
    before it returns: a "done" check that is the screen's time. Godzilla's other screens' checks ask the
    video surface instead (done when the clip stops: ``surface_state(video) != playing``)."""
    for k in range(24):
        w = elf.word(fn + 4 * k)
        if w is None:
            return False
        if (w & 0xFFB00F00) == 0xED900A00 and (w & 0xFF) * 4 == field:      # vldr sX, [rN, #field]
            return True
        if w == _BX_LR or (w & 0xFFFF0000) == 0xE8BD0000:                     # bx lr / pop
            return False
        if (w & 0x0F000000) == 0x0B000000 and depth == 0:                    # bl: one level down
            off = ((w & 0xFFFFFF) ^ 0x800000) - 0x800000
            if _reads_field(elf, fn + 4 * k + 8 + 4 * off, field, 1):
                return True
    return False


def time_slot(elf):
    """The vtable slot a screen's length is read from, worked out of the base class's code, or
    ``None`` when the program has no such screens. The length field is the one the most "elapsed >
    length" checks compare; the slot is the one the code that stores that field loads (and compares
    with the base's own function) just before."""
    import collections
    a = elf.arr
    if len(a) < 16:
        return None
    m = np.nonzero(((a[:-2] & 0xFFFFFF00) == _VLDR_S14_R0) & ((a[1:-1] & 0xFFFFFF00) == _VLDR_S15_R0)
                   & (a[2:] == _VCMPE_S14_S15))[0]
    fields = collections.Counter((int(a[i + 1]) & 0xFF) for i in m.tolist())
    for field, _n in fields.most_common(3):
        stores = np.nonzero(((a & 0xFFF0FF00) == _VSTR_S0) & ((a & 0xFF) == field))[0]
        slots = collections.Counter()
        for i in stores.tolist():
            for k in range(1, 14):
                if i - k < 0:
                    break
                w = int(a[i - k])
                off = w & 0xFFF
                if (w & 0xFFF00000) != _LDR_IMM or not 0x20 <= off <= 0x200 or off & 3:
                    continue
                rd = (w >> 12) & 0xF
                if any((int(a[i - j]) & 0xFFF0F000) == _CMP_REG and ((int(a[i - j]) >> 16) & 0xF) == rd
                       for j in range(0, k)):
                    slots[off // 4] += 1
                    break
        if slots:
            return slots.most_common(1)[0][0]
    return None


def screens(game_elf):
    """Every screen of the game that shows a clip of its own for a fixed time, ``[Screen]``, in
    the order of their vtables. *game_elf*: the program's bytes or a :class:`.portgen.Elf`.
    PAD-1323: a 64-bit program (Spike 3) is read by :func:`screens_a64`."""
    from .portgen import Elf
    if isinstance(game_elf, (bytes, bytearray, memoryview)) and bytes(game_elf[:5]) == b"\x7fELF\x02":
        return screens_a64(bytes(game_elf))
    elf = game_elf if isinstance(game_elf, Elf) else Elf(game_elf)
    strings, floats = _getters(elf)
    tslot = time_slot(elf) if strings and floats else None
    if tslot is None:
        return []
    # every vtable (an RTTI header above it) whose time slot holds a constant float getter
    timed = {}
    want = np.array(sorted(floats), dtype="<u4")
    for off, va, fsz, _flags in elf.loads:
        words = np.frombuffer(elf.b, dtype="<u4", count=fsz // 4, offset=off)
        for i in np.nonzero(np.isin(words, want))[0].tolist():
            slot = va + 4 * i
            vt, cls = _rtti_head(elf, slot)
            if vt is not None and slot == vt + 4 * tslot:
                timed[vt] = (cls, slot, int(words[i]))
    # the clip's slot: where those vtables hold the most DIFFERENT strings (each screen names its own
    # clip; the crop next to it is one of a few: "Normal", "ScoreFrame")
    at = {}
    for vt in timed:
        for k in range(1, tslot):
            fn = elf.word(vt + 4 * k)
            if fn in strings:
                at.setdefault(k, set()).add(strings[fn])
    if not at:
        return []
    cslot = max(at, key=lambda k: (len(at[k]), -k))
    lfield = _length_field(elf)
    out = []
    for vt in sorted(timed):
        cls, slot, old = timed[vt]
        clip_fn = elf.word(vt + 4 * cslot)
        if clip_fn not in strings:
            continue
        # the play-it-looped flag, two slots on: a constant 0 or 1 on every screen of this framework (Godzilla,
        # Jaws, King Kong); anything else is a layout this reader does not know, and the program is left alone
        loops = _bool_getter(elf, elf.word(vt + 4 * (cslot + LOOP_AFTER_CLIP)))
        if loops is None:
            return []
        # its own "done" check, the slot before the clip's name: the time, or (most screens) the clip's end
        done = elf.word(vt + 4 * (cslot - 1))
        on_time = bool(lfield and done and _reads_field(elf, done, lfield))
        crop_fn = elf.word(vt + 4 * cslot + 4)
        out.append(Screen(clip=strings[clip_fn], crop=strings.get(crop_fn, ""), cls=cls, vt=vt,
                          slot=slot, old=old, seconds=floats[old], loops=loops, timed=on_time))
    return out


def _bool_getter(elf, fn):
    """``True`` / ``False`` for a ``mov r0, #1`` / ``mov r0, #0`` / ``bx lr`` function, else ``None``."""
    if not fn:
        return None
    w0, w1 = elf.word(fn), elf.word(fn + 4)
    if w0 in (0xE3A00000, 0xE3A00001) and w1 == _BX_LR:
        return w0 == 0xE3A00001
    return None


# ---- PAD-1323: the 64-bit program (Spike 3) ------------------------------------------------------------
# The same framework, built for AArch64 (Fallout LE 0.82 and Pokemon LE 0.82 carry it; BDLExtraBall,
# BDLModeTotal ...): Fallout's screens name their clip in slot 17 and crop in 18, play-it-looped in 19, their
# "done" check in 16, and the base's start code reads the length from slot 28 (`ldr x1, [x2, #0xe0]`, compared
# with the base's own 3.0 s getter) into the float at +0xe0, which the check compares with the clock beside it
# (`ldp s0, s1, [x0, #0xe0]` / `fcmpe s1, s0`). A PIE: a vtable's words are 0 in the file and its entries are
# R_AARCH64_RELATIVE relocations, read from .rela.dyn; every address here is the program's link-time one (the
# runtime adds the load address, pad_mode_runtime.c "screen times").
_A64_RET = 0xD65F03C0
_A64_RELATIVE = 1027


class _Elf64:
    """The parts of a 64-bit ARM program :func:`screens_a64` reads."""

    def __init__(self, b):
        self.b = b
        phoff, = struct.unpack_from("<Q", b, 0x20)
        shoff, = struct.unpack_from("<Q", b, 0x28)
        phsz, phn, shsz, shn, shstr = struct.unpack_from("<HHHHH", b, 0x36)
        self.loads = []
        for i in range(phn):
            t, fl, off, va, _pa, fs, _ms, _al = struct.unpack_from("<IIQQQQQQ", b, phoff + i * phsz)
            if t == 1:
                self.loads.append((off, va, fs, fl))
        secs = {}
        if shoff and shn and shoff + shn * shsz <= len(b):
            raw = [struct.unpack_from("<IIQQQQIIQQ", b, shoff + i * shsz) for i in range(shn)]
            so = raw[shstr][4] if shstr < len(raw) else 0
            for nm, _t, _fl, a, off, sz, *_rest in raw:
                e = b.find(b"\0", so + nm)
                secs[b[so + nm:e].decode("ascii", "replace")] = (a, off, sz)
        text = secs.get(".text")
        if text is None:
            ex = [l for l in self.loads if l[3] & 1]
            if not ex:
                raise ValueError("no executable code")
            text = (ex[0][1], ex[0][0], ex[0][2])
        self.tva, toff, tsz = text
        self.arr = np.frombuffer(b, dtype="<u4", count=tsz // 4, offset=toff)
        self.ptr = {}
        rel = secs.get(".rela.dyn")
        if rel is not None:
            r = np.frombuffer(b, dtype="<u8", count=rel[2] // 8 // 3 * 3, offset=rel[1]).reshape(-1, 3)
            keep = (r[:, 1] & 0xFFFFFFFF) == _A64_RELATIVE
            self.ptr = dict(zip(r[keep, 0].tolist(), r[keep, 2].tolist()))

    def off(self, va):
        for off, v, fsz, _f in self.loads:
            if v <= va < v + fsz:
                return off + va - v
        return None

    def u32(self, va):
        o = self.off(va)
        return struct.unpack_from("<I", self.b, o)[0] if o is not None and o + 4 <= len(self.b) else None

    def u64(self, va):
        """The pointer at *va* as the loader leaves it (less the load address): its relocation's addend, else
        the file's word."""
        if va in self.ptr:
            return self.ptr[va]
        o = self.off(va)
        return struct.unpack_from("<Q", self.b, o)[0] if o is not None and o + 8 <= len(self.b) else None


def _a64_adrp(va, w):
    imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
    if imm & (1 << 20):
        imm -= 1 << 21
    return (va & ~0xFFF) + (imm << 12)


def _a64_fmov_imm(imm8):
    """The float an ``fmov s0, #imm`` makes (the VFP 8-bit immediate)."""
    b = (imm8 >> 6) & 1                                   # VFPExpandImm: a:NOT(b):bbbbb:cd:efgh:0...
    exp8 = ((b ^ 1) << 7) | ((0x1F if b else 0) << 2) | ((imm8 >> 4) & 3)
    word = ((imm8 >> 7) << 31) | (exp8 << 23) | ((imm8 & 15) << 19)
    return struct.unpack("<f", struct.pack("<I", word))[0]


def _getters_a64(elf):
    """``({fn: string}, {fn: float})``: ``adrp x0 / add x0, x0 / ret`` and ``fmov s0, #imm / ret`` (or a word
    moved in: ``mov wN, #hi, lsl 16 [/ movk] / fmov s0, wN / ret``)."""
    a = elf.arr
    strings, floats = {}, {}
    if len(a) < 4:
        return strings, floats
    w0, w1, w2 = a[:-2], a[1:-1], a[2:]
    s_idx = np.nonzero(((w0 & 0x9F00001F) == 0x90000000) & ((w1 & 0xFFC003FF) == 0x91000000) & (w2 == _A64_RET))[0]
    for i in s_idx.tolist():
        va = elf.tva + 4 * i
        s = _cstr(elf, _a64_adrp(va, int(a[i])) + ((int(a[i + 1]) >> 10) & 0xFFF))
        if s:
            strings[va] = s
    for i in np.nonzero(((w0 & 0xFFE01FFF) == 0x1E201000) & (w1 == _A64_RET))[0].tolist():
        floats[elf.tva + 4 * i] = _a64_fmov_imm((int(a[i]) >> 13) & 0xFF)
    # mov wN, #hi, lsl #16 ; fmov s0, wN ; ret  (and with a movk of the low half between)
    for i in np.nonzero(((w0 & 0xFFE00000) == 0x52A00000) & ((w1 & 0xFFFFFC1F) == 0x1E270000) & (w2 == _A64_RET))[0].tolist():
        if (int(a[i]) & 31) == (int(a[i + 1]) >> 5) & 31:
            v = struct.unpack("<f", struct.pack("<I", ((int(a[i]) >> 5) & 0xFFFF) << 16))[0]
            if v == v:
                floats[elf.tva + 4 * i] = v
    if len(a) > 4:
        x0, x1, x2, x3 = a[:-3], a[1:-2], a[2:-1], a[3:]
        for i in np.nonzero(((x0 & 0xFFE00000) == 0x52800000) & ((x1 & 0xFFE00000) == 0x72A00000)
                            & ((x2 & 0xFFFFFC1F) == 0x1E270000) & (x3 == _A64_RET))[0].tolist():
            rd = int(a[i]) & 31
            if (int(a[i + 1]) & 31) == rd and (int(a[i + 2]) >> 5) & 31 == rd:
                word = (((int(a[i + 1]) >> 5) & 0xFFFF) << 16) | ((int(a[i]) >> 5) & 0xFFFF)
                v = struct.unpack("<f", struct.pack("<I", word))[0]
                if v == v:
                    floats[elf.tva + 4 * i] = v
    return strings, floats


def _length_fields_a64(elf):
    """``Counter({field: n})`` of the "clock > length" checks: ``ldp sA, sB, [xN, #f]`` then ``fcmpe sB, sA`` (the
    length is the compare's second operand), or the two as ``ldr``s."""
    import collections
    a = elf.arr
    out = collections.Counter()
    for i in np.nonzero((a & 0xFFE0FC1F) == 0x1E202010)[0].tolist():        # fcmpe sN, sM
        rn, rm = (int(a[i]) >> 5) & 31, (int(a[i]) >> 16) & 31
        if rn == rm:
            continue
        at = {}
        for j in range(1, 5):
            if i - j < 0:
                break
            w = int(a[i - j])
            if (w & 0xFFC00000) == 0x2D400000:                              # ldp sT, sT2, [xN, #imm7*4]
                imm = (w >> 15) & 0x7F
                imm = (imm - 128 if imm & 64 else imm) * 4
                base = (w >> 5) & 31
                at.setdefault(w & 31, (base, imm))
                at.setdefault((w >> 10) & 31, (base, imm + 4))
            elif (w & 0xFFC00000) == 0xBD400000:                            # ldr sT, [xN, #imm12*4]
                at.setdefault(w & 31, ((w >> 5) & 31, ((w >> 10) & 0xFFF) * 4))
        if rn in at and rm in at and at[rn][0] == at[rm][0] and at[rm][1] > 0:
            out[at[rm][1]] += 1
    return out


def _done_checks_a64(elf):
    """``Counter({field: n})`` of the whole-function "done" checks a timed screen's vtable holds:
    ``ldp s0, s1, [x0, #f]`` / ``fcmpe s1, s0`` / ``cset w0, gt`` / ``ret`` (Fallout +0xe0, Pokemon +0xc8). Other
    float compares in the program (Pokemon has more of them than screens) do not count here."""
    import collections
    a = elf.arr
    out = collections.Counter()
    if len(a) < 5:
        return out
    m = np.nonzero(((a[:-3] & 0xFFC07FFF) == 0x2D400400) & (a[1:-2] == 0x1E202030)
                   & (a[2:-1] == 0x1A9FD7E0) & (a[3:] == _A64_RET))[0]
    for i in m.tolist():
        imm = (int(a[i]) >> 15) & 0x7F
        if not imm & 64:
            out[imm * 4] += 1
    return out


def _time_slot_a64(elf, fields):
    """The vtable slot the code that stores a length field (``str s0, [xN, #field]``) loads and compares with the
    base's own function just before (``ldr xD, [xV, #slot*8]`` ... ``cmp xD, xK``)."""
    import collections
    a = elf.arr
    for field, _n in fields.most_common(3):
        if field % 4 or field // 4 > 0xFFF:
            continue
        stores = np.nonzero((a & 0xFFFFFC1F) == (0xBD000000 | (field // 4) << 10))[0]
        slots = collections.Counter()
        for i in stores.tolist():
            for k in range(1, 16):
                if i - k < 0:
                    break
                w = int(a[i - k])
                if (w & 0xFFC00000) != 0xF9400000:                          # ldr xD, [xN, #imm12*8]
                    continue
                off = ((w >> 10) & 0xFFF) * 8
                if not 0x40 <= off <= 0x400:
                    continue
                rd = w & 31
                if any((int(a[i - j]) & 0xFF20001F) == 0xEB00001F               # cmp xN, xM (subs xzr)
                       and rd in ((int(a[i - j]) >> 5) & 31, (int(a[i - j]) >> 16) & 31) for j in range(0, k)):
                    slots[off // 8] += 1
                    break
        if slots:
            return field, slots.most_common(1)[0][0]
    return None, None


def _rtti_head_a64(elf, entry):
    """``(vtable address point, class name)`` for the vtable *entry* is in: the first pointer above it that a
    ``[0, typeinfo]`` pair precedes, typeinfo's name (at +8) a mangled one."""
    for k in range(1, MAX_HEAD_WORDS):
        top = entry - 8 * k
        if top - 16 in elf.ptr or elf.u64(top - 16) != 0:
            continue
        ti = elf.ptr.get(top - 8)
        if not ti:
            continue
        name_va = elf.u64(ti + 8)
        name = _cstr(elf, name_va) if name_va else None
        if name and name[0].isdigit():
            return top, name.lstrip("0123456789")
    return None, ""


def _reads_field_a64(elf, fn, field, depth=0):
    """:func:`_reads_field` for AArch64: a ``ldr``/``ldp`` of the float at ``[xN, #field]`` before a ``ret``,
    or in a function it ``bl``s, one level down."""
    for k in range(24):
        w = elf.u32(fn + 4 * k)
        if w is None:
            return False
        if (w & 0xFFC00000) == 0xBD400000 and ((w >> 10) & 0xFFF) * 4 == field:
            return True
        if (w & 0xFFC00000) == 0x2D400000:
            imm = (w >> 15) & 0x7F
            imm = (imm - 128 if imm & 64 else imm) * 4
            if field in (imm, imm + 4):
                return True
        if w == _A64_RET:
            return False
        if (w & 0xFC000000) == 0x94000000 and depth == 0:                   # bl
            off = w & 0x3FFFFFF
            off = off - (1 << 26) if off & (1 << 25) else off
            if _reads_field_a64(elf, fn + 4 * k + 4 * off, field, 1):
                return True
    return False


def _bool_getter_a64(elf, fn):
    if not fn:
        return None
    w0, w1 = elf.u32(fn), elf.u32(fn + 4)
    if w0 in (0x52800000, 0x52800020) and w1 == _A64_RET:
        return w0 == 0x52800020
    return None


def screens_a64(b):
    """:func:`screens` for a 64-bit ARM program's bytes *b*: the same screens, read the same way."""
    try:
        elf = _Elf64(b)
    except (struct.error, ValueError, IndexError):
        return []
    strings, floats = _getters_a64(elf)
    if not strings or not floats or not elf.ptr:
        return []
    lfield, tslot = _time_slot_a64(elf, _done_checks_a64(elf))
    if tslot is None:
        lfield, tslot = _time_slot_a64(elf, _length_fields_a64(elf))
    if tslot is None:
        return []
    timed = {}
    for slot, fn in elf.ptr.items():
        if fn in floats:
            vt, cls = _rtti_head_a64(elf, slot)
            if vt is not None and slot == vt + 8 * tslot:
                timed[vt] = (cls, slot, fn)
    at = {}
    for vt in timed:
        for k in range(1, tslot):
            fn = elf.ptr.get(vt + 8 * k)
            if fn in strings:
                at.setdefault(k, set()).add(strings[fn])
    if not at:
        return []
    cslot = max(at, key=lambda k: (len(at[k]), -k))
    out = []
    for vt in sorted(timed):
        cls, slot, old = timed[vt]
        clip_fn = elf.ptr.get(vt + 8 * cslot)
        if clip_fn not in strings:
            continue
        # the play-it-looped flag after the clip's name and its crop (Fallout), or straight after the name on a
        # framework with no crop (Pokemon: an int getter there, not a string's)
        crop_fn = elf.ptr.get(vt + 8 * (cslot + 1))
        loop_at = cslot + LOOP_AFTER_CLIP if crop_fn in strings else cslot + 1
        loops = _bool_getter_a64(elf, elf.ptr.get(vt + 8 * loop_at))
        if loops is None:
            continue                                  # a layout of its own (another family): left alone
        done = elf.ptr.get(vt + 8 * (cslot - 1))
        on_time = bool(done and _reads_field_a64(elf, done, lfield))
        out.append(Screen(clip=strings[clip_fn], crop=strings.get(crop_fn, ""), cls=cls, vt=vt,
                          slot=slot, old=old, seconds=floats[old], loops=loops, timed=on_time))
    return out


def by_clip(found):
    """``{clip name: [Screen]}``."""
    out = {}
    for s in found:
        out.setdefault(s.clip, []).append(s)
    return out


def cfg_lines(found, lengths):
    """``clips.cfg``'s ``stime`` lines: one per screen whose clip has a length in *lengths*
    (``{clip name: seconds}``, the clip as it goes on the card) that is not the screen's own."""
    lines = []
    for s in found:
        sec = lengths.get(s.clip)
        if s.loops or not s.timed or sec is None or sec <= 0 or abs(sec - s.seconds) <= SAME_S:
            continue
        ms = int(round(min(sec, MAX_S) * 1000))
        lines.append("stime\t0x%08x\t0x%08x\t0x%08x\t%d\t%s" % (s.vt, s.slot, s.old, ms, s.clip))
    return lines


# ---- the Video tab's flag ---------------------------------------------------------------------------
_PROJECT_CACHE = {}


def project_screens(project):
    """``{clip name: [Screen]}`` for the card *project* was extracted from (its game program read once per
    card: path, size and time), ``{}`` when the game has none, ``None`` when the card cannot be read. Opens
    the card image: never on the UI thread."""
    from . import mode_project as MP
    try:
        found_card, _prof = MP.project_profile(project, probe=True)
    except (OSError, ValueError):
        return None
    card = getattr(found_card, "image", None) or (found_card if isinstance(found_card, str) else None)
    if not card:
        return None
    try:
        st = os.stat(card)
    except (OSError, TypeError):
        return None
    key = (os.path.abspath(card), st.st_size, int(st.st_mtime))
    if key not in _PROJECT_CACHE:
        from . import engine as E, spike3
        try:
            if spike3.is_spike3_card(card):
                # PAD-1323: a Spike 3 card's 64-bit program, off its encrypted games partition
                from .title_reader import spike3_game_program
                elf = spike3_game_program(card)[2]
            else:
                with open(card, "rb") as f:
                    readers = E._open_readers(f, E._linux_partitions(card))
                    elf = b""
                    if readers:
                        _path, node = E._game_program_path(readers[0][1], lambda: False)
                        if node is not None:
                            elf = bytes(readers[0][1].read_file_bytes(node))
            _PROJECT_CACHE[key] = by_clip(screens(elf)) if elf else {}
        except Exception:                                 # noqa: BLE001 - an unreadable card: unknown
            return None
    return _PROJECT_CACHE[key]


def flag(found, clip_s, replaced):
    """``(tag, cls, head, lines)`` for a Video tab row whose clip *found* (``[Screen]``) shows, or ``None``
    when it needs none (no screen, or one that plays its clip over and over). *clip_s* is the slot's clip
    as it is now (the replacement when *replaced*), 0 when not measured yet. *cls* is ``"warn"`` when the
    clip freezes on its last frame or is cut on the card as it would be built."""
    once = [s for s in found or () if s.timed and not s.loops]
    if not once:
        return None
    sec = once[0].seconds
    tag = "%g s" % sec
    head = "The game shows this clip for %g s" % sec
    lines, cls = [], ""
    if clip_s and replaced:
        if abs(clip_s - sec) > SAME_S:
            lines.append("Your clip is %.2f s. On an image build the screen lasts %.2f s too, its whole length "
                         "(a direct SD write keeps the game's %g s)." % (clip_s, clip_s, sec))
        else:
            lines.append("Your clip is %.2f s, the screen's own time." % clip_s)
    elif clip_s:
        if clip_s < sec - SAME_S:
            cls = "warn"
            lines.append("This clip is %.2f s, so its last frame stays on screen for %.2f s." % (clip_s, sec - clip_s))
        elif clip_s > sec + SAME_S:
            cls = "warn"
            lines.append("This clip is %.2f s, so the game cuts it off after %g s." % (clip_s, sec))
        else:
            lines.append("This clip is %.2f s, the screen's own time." % clip_s)
    lines.append("Replace it with a clip of any length and, on an image build, the screen lasts as long as "
                 "your clip.")
    if len({round(s.seconds, 2) for s in once}) > 1:
        lines.append("More than one screen shows it, for %s." % ", ".join(
            "%g s" % v for v in sorted({s.seconds for s in once})))
    return tag, cls, head, lines
