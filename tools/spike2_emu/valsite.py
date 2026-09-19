#!/usr/bin/env python3
r"""valsite.py <card-game-elf> [<run-game-elf>] - where this title keeps its
GAME VALIDATION ERROR state, and whether the program a run uses can raise one.

    valsite.py /home/me/card/godzilla_le-1_16_0/game
    -> 0x7d6c1c 0x7f86a0 live

    valsite.py <card game> <override set's game>
    -> 0x7d6c1c 0x7f86a0 off

One line: the validation module's base, the address of the sound bank's FAILED
count, and what the validator does in the RUN program (the second ELF when
given, else the first): `off` when its tick is PAD's `bx lr`, `live` when it
runs, `unknown` when the tick was not found. Nothing at all when either address
cannot be derived, and the shim then stays quiet exactly as before.

WHY (PAD-178). "Game validation error, Update SD card" is one red banner for SIX
different checks, and nothing in a run's log said which one was up. PAD-172 was
closed on a deduction ("#4 is the only one left, so his card must have longer
sounds") and the same user came back with the same banner on the STOCK card,
where that deduction cannot hold, and a log that could not settle it either
way. The game's alert provider decides the banner from six fields, and the shim
can read all six if it knows where they are - hwshim's PAD_VAL_MOD/PAD_VAL_AUD,
which were Godzilla Pro 1.15 constants. This derives them from any title's own
code, so the run can name the check (hwshim val_watch).

THE SIX CHECKS, read off the provider on Godzilla Pro 1.15 (0x24a018) and LE
1.16 (0x3fe898), instruction for instruction the same. V = [MOD+0xc0]:

    #1  V[+42] (GE) is 2 or 3        #4  the sound bank's failed count != 0
    #2  V[+43] (CE) is 2 or 3        #5  V[+24] != 0, or V[+41] == 1
    #3  V[+44] (ZK) is 2 or 3        #6  V[+12] or V[+16] != 0

Only the validator's tick writes V's counters and grades, so with PAD's bypass
(tick = `bx lr`, grade restore = "failed", so every boot re-initialises to
passing) #4 is the one check left alive: the sound engine's band build counts it
on its own (valpatch's note on the sound count).

HOW, and why two ways. MOD comes from the module's start function, the one
that restores the grades from NVRAM (`mov r0,#0x50; mov r1,#0x214; mov r2,rN;
mov r3,#0x80; bl`), whose rN is built by a movw/movt just above. The provider
names MOD too, and the #4 getter it calls (`movw/movt; ldr [#valid]; ldr
[#failed]; str [r0]; str [r1]; bx lr`) names the count. The two MODs must
agree or nothing is printed: a wrong address here makes the shim report a
check the game is not raising.

Measured: godzilla_pro 1.15.0 -> 0x7b7b70 0x7b9308 (hwshim's hand-found
constants), godzilla_le 1.16.0 -> 0x7d6c1c 0x7f86a0.
"""
import re
import struct
import sys

BX_LR = 0xE12FFF1E
MOV_R0_0 = 0xE3A00000


def _text(d):
    """``(file_off, vaddr, size)`` of the first executable PT_LOAD."""
    if d[:4] != b"\x7fELF" or d[4] != 1:
        raise ValueError("not a 32-bit ELF")
    phoff = struct.unpack_from("<I", d, 0x1C)[0]
    phent, phnum = struct.unpack_from("<HH", d, 0x2A)
    for i in range(phnum):
        p_type, p_off, p_va, _pa, p_fsz, _msz, p_flags = \
            struct.unpack_from("<7I", d, phoff + i * phent)
        if p_type == 1 and p_flags & 1:
            return p_off, p_va, p_fsz
    raise ValueError("no executable segment")


def _word(d, off):
    return struct.unpack_from("<I", d, off)[0]


def _movw_movt(d, off, reg, back=8):
    """The constant a movw/movt pair builds in *reg* within *back* words
    above *off*, or None."""
    lo = hi = None
    for k in range(1, back + 1):
        p = off - 4 * k
        if p < 0:
            break
        w = _word(d, p)
        if (w >> 12) & 0xF != reg or w >> 28 != 0xE:
            continue
        imm = ((w >> 4) & 0xF000) | (w & 0xFFF)
        if (w >> 20) & 0xFF == 0x34 and hi is None:
            hi = imm
        elif (w >> 20) & 0xFF == 0x30 and lo is None:
            lo = imm
        if lo is not None and hi is not None:
            return (hi << 16) | lo
    return None


def _aligned(pattern, d, lo, hi):
    """File offsets of word-aligned regex matches inside [lo, hi)."""
    return [m.start() for m in pattern.finditer(d, lo, hi)
            if m.start() % 4 == 0]


def mod_from_restore(d, t_off, t_sz):
    """MOD from the grade-restore call (see the header), or None."""
    pat = re.compile(re.escape(struct.pack("<II", 0xE3A00050, 0xE3A01F85)))
    out = set()
    for off in _aligned(pat, d, t_off, t_off + t_sz):
        w = struct.unpack_from("<5I", d, off)
        if (w[2] & 0xFFFFFFF0) != 0xE1A02000 or w[3] != 0xE3A03080:
            continue
        if (w[4] >> 24) != 0xEB and w[4] != MOV_R0_0:
            continue
        m = _movw_movt(d, off, w[2] & 0xF)
        if m is not None:
            out.add(m)
    return out.pop() if len(out) == 1 else None


def _ldr_imm(w):
    """``(rt, rn, signed offset)`` of an unconditional ``ldr rt, [rn, #imm]``."""
    if w >> 28 != 0xE or (w & 0x0F700000) != 0x05100000:
        return None
    off = w & 0xFFF
    return (w >> 12) & 0xF, (w >> 16) & 0xF, off if w & 0x00800000 else -off


def provider(d, t_off, t_va, t_sz):
    """``(mod, failed_addr)`` read off the alert provider and its #4 getter,
    or None unless exactly one provider matches."""
    # ldrb rX, [rY, #0x2c] - ZK, the last of the three grade loads
    pat = re.compile(b"\x2c[\x00\x10\x20\x30\x40\x50\x60\x70\x80\x90\xa0\xb0"
                     b"\xc0][\xd0-\xdc]\xe5")
    found = set()
    for off in _aligned(pat, d, t_off, t_off + t_sz):
        ry = (_word(d, off) >> 16) & 0xF
        seen = set()
        for k in range(1, 16):
            w = _word(d, off - 4 * k)
            if (w & 0xFFFF0FFF) in (0xE5D0002A | (ry << 16),
                                    0xE5D0002B | (ry << 16)):
                seen.add(w & 0xFF)
        if seen != {0x2A, 0x2B}:
            continue
        # the V load feeding them: ldr rY, [rM, #0xc0], and MOD built in rM
        mod = None
        for k in range(1, 24):
            p = off - 4 * k
            li = _ldr_imm(_word(d, p))
            if li and li[0] == ry and li[2] == 0xC0:
                mod = _movw_movt(d, p, li[1], back=12)
                break
        # the #4 getter: the first bl after the ZK load
        getter = None
        for k in range(1, 10):
            w = _word(d, off + 4 * k)
            if w >> 24 == 0xEB:
                rel = w & 0xFFFFFF
                if rel & 0x800000:
                    rel -= 0x1000000
                getter = (off + 4 * k - t_off + t_va) + 8 + rel * 4
                break
        if mod is None or getter is None:
            continue
        g = getter - t_va + t_off
        if not t_off <= g < t_off + t_sz - 28:
            continue
        w = struct.unpack_from("<7I", d, g)
        if (w[4], w[5], w[6]) != (0xE5802000, 0xE5813000, BX_LR):
            continue
        base = _movw_movt(d, g + 8, 3, back=2)
        valid, failed = _ldr_imm(w[2]), _ldr_imm(w[3])
        if base is None or not valid or not failed:
            continue
        if (valid[0], valid[1], failed[0], failed[1]) != (2, 3, 3, 3):
            continue
        if failed[2] - valid[2] != 4:
            continue
        found.add((mod, base + failed[2]))
    return found.pop() if len(found) == 1 else None


def tick_state(d):
    """``off`` / ``live`` / ``unknown``: is the validator's tick PAD's
    ``bx lr``? The tick opens by testing the state byte at MOD+0xc5 against
    its terminal state (``ldrb rX,[rY,#197]; cmp rX,#8`` - see valtick.py),
    and its first instruction decides."""
    try:
        t_off, _t_va, t_sz = _text(d)
    except ValueError:
        return "unknown"
    pat = re.compile(b"\xc5[\x00\x10\x20\x30\x40\x50\x60\x70\x80\x90\xa0\xb0"
                     b"\xc0][\xd0-\xdc]\xe5")
    verdicts = set()
    for off in _aligned(pat, d, t_off, t_off + t_sz):
        rx = (_word(d, off) >> 12) & 0xF
        if _word(d, off + 4) != (0xE3500008 | (rx << 16)):
            continue
        for k in range(1, 65):
            w = _word(d, off - 4 * k)
            if w == BX_LR:
                verdicts.add("off")
                break
            if (w & 0xFFFF4000) == 0xE92D4000:
                verdicts.add("live")
                break
    return verdicts.pop() if len(verdicts) == 1 else "unknown"


def sites(d):
    """``(mod, failed_addr)`` when both derivations agree, else None."""
    t_off, t_va, t_sz = _text(d)
    a = mod_from_restore(d, t_off, t_sz)
    b = provider(d, t_off, t_va, t_sz)
    if a is None or b is None or b[0] != a:
        return None
    return b


def read_code(path):
    """The ELF from its start to the end of its code segment - everything
    this reads - and not the rest: rush_le's program is 190 MB, almost all of
    it data, and a run's copy of it can sit across 9p."""
    with open(path, "rb") as f:
        head = f.read(0x10000)
        try:
            t_off, _va, t_sz = _text(head)
        except (ValueError, struct.error):
            return head + f.read()
        end = t_off + t_sz
        return (head + f.read(max(0, end - len(head))))[:end]


def main(argv):
    if not 1 <= len(argv) <= 2:
        raise SystemExit("usage: valsite.py <card-game-elf> [<run-game-elf>]")
    card = read_code(argv[0])
    got = sites(card)
    if got is None:
        return 1
    run = card
    if len(argv) == 2:
        try:
            run = read_code(argv[1])
        except OSError:
            run = None
    print("0x%06x 0x%06x %s" % (got[0], got[1],
                                tick_state(run) if run else "unknown"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
