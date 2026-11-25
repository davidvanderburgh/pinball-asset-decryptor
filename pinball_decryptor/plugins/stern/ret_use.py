"""PAD-1400's list of the show_start / award_screen callers that use what they get back, read off a build's own
program (PAD-1555: the original scan lived in C:/tmp/PAD-1400 and is gone; a derived port copied `own_ret_scanned 1`
from its references with an EMPTY list, so a whole-game mode would have refused every caller, the ones that crash on
a null among them).

A whole-game mode (pm_own_game) refuses the game's own award screens and light shows by returning 0 from the call; a
caller that then uses the result (TMNT Pro's show_start(178) at 0x147cf0 stores into the show) crashes on the null.
Each port lists those callers (`value own_ret_scanned 1`, `value own_pass_<k> <bl address>`) and the runtime never
refuses them. A caller uses the result when r0 after the call, or a register it was copied to or offset into, is a
load/store base, stored, handed to the next call in r0-r3, or returned - before it is overwritten. Unconditional
branches are followed and conditional ones fallen through; a caller that compares the result with 0 first is safe.
Every doubt lists the caller: a listed caller's show only plays, a missed one crashes the game."""

WINDOW = 24


def _sites(port_text, names):
    out = {}
    for line in port_text.splitlines():
        f = line.split()
        if len(f) >= 3 and f[0] == "site" and f[1] in names:
            out[f[1]] = int(f[2], 16)
    return out


def callers(elf, target):
    """Every BL (any condition) to `target` in the program's text."""
    import numpy as np
    w = elf.arr
    va = elf.tva + 4 * np.arange(len(w), dtype=np.int64)
    is_bl = (w & 0x0F000000) == 0x0B000000
    imm = (w & 0x00FFFFFF).astype(np.int64)
    imm = np.where(imm & 0x800000, imm - 0x1000000, imm)
    dest = va + 8 + imm * 4
    return [int(a) for a in va[is_bl & (dest == target) & ((w >> 28) != 0xF)]]


def _insns(md, elf, at, budget):
    """Straight-line code from `at`, following unconditional branches (the use may sit past a jump)."""
    from capstone import arm as A
    seen = set()
    while budget > 0 and at not in seen:
        seen.add(at)
        try:
            code = elf.b[elf.off(at):elf.off(at) + 4 * budget]
        except Exception:
            return
        jumped = False
        for ins in md.disasm(code, at):
            budget -= 1
            if ins.mnemonic == "b" and ins.operands and ins.operands[0].type == A.ARM_OP_IMM:
                at, jumped = ins.operands[0].imm, True
                break
            yield ins
            if budget <= 0:
                return
        if not jumped:
            return


def uses_result(md, elf, at):
    from capstone import arm as A
    alias = {A.ARM_REG_R0}
    for ins in _insns(md, elf, at + 4, WINDOW):
        ops = ins.operands
        _read, written = ins.regs_access()
        base = ins.mnemonic.split(".")[0]
        if (base in ("cmp", "cmn", "tst") and len(ops) == 2 and ops[0].type == A.ARM_OP_REG and ops[0].reg in alias
                and ops[1].type == A.ARM_OP_IMM and ops[1].imm == 0) or (base == "tst" and ops and ops[0].reg in alias):
            return False                                        # null-checked: a refused 0 is safe here
        if base[:3] == "blx" or (base[:2] == "bl" and base[:3] not in ("ble", "blt", "bls", "blo")):
            if alias & {A.ARM_REG_R0, A.ARM_REG_R1, A.ARM_REG_R2, A.ARM_REG_R3}:
                return True                                     # passed on
            if ins.cc == A.ARM_CC_AL:
                return False                                    # the call's own r0-r3 replace nothing we hold
            continue
        if base == "bx" and ops and ops[0].reg == A.ARM_REG_LR:
            return A.ARM_REG_R0 in alias                        # returned
        if base.startswith(("pop", "ldm")) and any(o.type == A.ARM_OP_REG and o.reg == A.ARM_REG_PC for o in ops):
            return A.ARM_REG_R0 in alias
        if base.startswith(("ldr", "str")):
            mem = [o for o in ops if o.type == A.ARM_OP_MEM]
            if mem and mem[0].mem.base in alias:
                return True                                     # a base
            if base.startswith("str") and ops and ops[0].type == A.ARM_OP_REG and ops[0].reg in alias:
                return True                                     # stored
        if base.startswith(("stm", "push")):
            if any(o.type == A.ARM_OP_REG and o.reg in alias for o in ops[1 if base.startswith("stm") else 0:]):
                return True
        src = [o.reg for o in ops[1:] if o.type == A.ARM_OP_REG]
        if base in ("mov", "add", "sub", "cpy") and ops and ops[0].type == A.ARM_OP_REG and src and src[0] in alias:
            alias.add(ops[0].reg)                               # a copy or an offset carries the result on
            continue
        if ins.cc == A.ARM_CC_AL:                               # a conditional write may not happen: keep it
            for r in written:
                alias.discard(r)
        if not alias:
            return False
    return False


def scan(elf, sites):
    """The calls (bl addresses) that use the result, from a portgen.Elf and {"show_start": va, "award_screen": va}."""
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    md.detail = True
    used = []
    for name in ("award_screen", "show_start"):
        if sites.get(name) is not None:
            used += [a for a in callers(elf, sites[name]) if uses_result(md, elf, a)]
    return sorted(set(used))


def value_lines(addrs):
    return ["value own_ret_scanned      1"] + ["value own_pass_%-11d 0x%08x" % (k, a) for k, a in enumerate(addrs)]


def lines(addrs):
    return ["# PAD-1400: award_screen / show_start callers that use what they get back (a refused 0 would crash them:",
            "# ret_use.py, read off this build); a whole-game mode never refuses these, every other caller of the two it does"
            ] + value_lines(addrs)


def is_own(name):
    """Values a port gets from its own build only (never copied from a reference)."""
    return name == "own_ret_scanned" or name.startswith("own_pass_")
