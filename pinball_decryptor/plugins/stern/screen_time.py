"""SCREEN TIMES (PAD-1115): a game screen that shows a clip for a fixed time lasts as long as the clip.

DoomWalrus666, Godzilla: "Some videos natively freeze frame at the end. It doesn't matter if the
clip is plenty long, it will freeze frame as normal game behavior. Examples: Secret Combo, Saucer
Attack." The game's award and battle-start screens (Godzilla's layered displays: BDLSecretComboAward,
BDLBigLoopAward, BDLBattleVSGiganStart ...) are objects of one base class. Each names its clip and its
crop through two virtuals (``secret_combo`` / ``Normal``), plays the clip ONCE, and stays up for a time
of its own: at its start the base class reads the screen's length from a third virtual (a float, in
seconds: 3.0 unless the class has its own; Secret Combo's is 4.0) and ends the screen when its clock
passes it. So a clip shorter than that sits on its last frame for the rest of the time (the stock
Secret Combo clip is 2.87 s: 1.1 s of a frozen frame), and a longer one is cut off.

THE FIX. The build reads every such screen off the game program (:func:`screens`) and, for a
replaced clip whose length is not its screen's, writes an ``stime`` line into ``clips.cfg``
(:func:`cfg_lines`); the mode runtime points that screen's time virtual at a function of its own that
answers the clip's length (pad_mode_runtime.c "screen times"). A screen ends when its clip does: no
frozen frame, and a longer clip plays to its end.

WHAT A SCREEN IS, read off the program (no per-title table): a vtable entry that points at a
getter returning a string (``movw r0`` / ``movt r0`` / ``bx lr``) - the clip's name - whose next
entry is another string getter (the crop) and whose entry :data:`TIME_AFTER_CLIP` slots on is a
float getter returning a constant (``vldr s0, [pc, #n]`` / ``bx lr``) - the time. The vtable's own
address (what an object of the class holds) is found from its RTTI header just above it. Read on
Godzilla LE / Pro 1.16: 34 screens with a clip of their own, all 3.0 s but Secret Combo's 4.0 s.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass

import numpy as np

#: ``PAD_STERN_SCREEN_TIME=0`` leaves every screen at the game's own time
GATE_ENV = "PAD_STERN_SCREEN_TIME"
#: entries from a screen's clip-name virtual to its time virtual (Godzilla 1.16: slots 15 and 20)
TIME_AFTER_CLIP = 5
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


def screens(game_elf):
    """Every screen of the game that shows a clip of its own for a fixed time, ``[Screen]``, in
    the order of their vtables. *game_elf*: the program's bytes or a :class:`.portgen.Elf`."""
    from .portgen import Elf
    elf = game_elf if isinstance(game_elf, Elf) else Elf(game_elf)
    strings, floats = _getters(elf)
    if not strings or not floats:
        return []
    want = np.array(sorted(strings), dtype="<u4")
    out = []
    for off, va, fsz, _flags in elf.loads:
        words = np.frombuffer(elf.b, dtype="<u4", count=fsz // 4, offset=off)
        for i in np.nonzero(np.isin(words, want))[0].tolist():
            entry = va + 4 * i
            crop_fn = elf.word(entry + 4)
            slot = entry + 4 * TIME_AFTER_CLIP
            old = elf.word(slot)
            if crop_fn not in strings or old not in floats:
                continue
            vt, cls = _rtti_head(elf, entry)
            if vt is None:
                continue
            out.append(Screen(clip=strings[int(words[i])], crop=strings[crop_fn], cls=cls, vt=vt,
                              slot=slot, old=old, seconds=floats[old]))
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
        if sec is None or sec <= 0 or abs(sec - s.seconds) <= SAME_S:
            continue
        ms = int(round(min(sec, MAX_S) * 1000))
        lines.append("stime\t0x%08x\t0x%08x\t0x%08x\t%d\t%s" % (s.vt, s.slot, s.old, ms, s.clip))
    return lines
