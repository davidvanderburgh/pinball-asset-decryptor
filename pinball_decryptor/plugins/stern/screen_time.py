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
    the order of their vtables. *game_elf*: the program's bytes or a :class:`.portgen.Elf`."""
    from .portgen import Elf
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
        from . import engine as E
        try:
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
