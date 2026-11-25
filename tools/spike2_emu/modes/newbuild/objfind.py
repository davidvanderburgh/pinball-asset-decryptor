"""objfind.py <program> <class> [...] - a C++ class's typeinfo and its static objects in a Spike 2 program (PAD-1555).

For the `data wizard_obj_<n>` (a mini-wizard's mode object) and `data typeinfo_*` lines a new build's port lacks:
  name      the class's mangled name, "<len><name>\\0", in the program's read-only data
  typeinfo  the record whose second word points at the name (its first is a type_info vtable)
  vtable    the address point after a word holding the typeinfo (vtable[-1] = typeinfo, vtable[-2] = 0 for the
            primary one)
  objects   every movw/movt pair (or literal) in the code that makes the vtable's address is a constructor storing it;
            each `bl <constructor>` whose r0 was just made by movw/movt (or a literal) is a static object built
            there - the address the port names.
Prints `<class> typeinfo 0x.. vtable 0x.. objects 0x.. 0x..`."""
import os
import struct
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def words_equal(elf, value, writable=None):
    pat, out = struct.pack("<I", value), []
    for off, va, fsz, flags in elf.loads:
        if writable is not None and bool(flags & 2) != writable:
            continue
        i = elf.b.find(pat, off, off + fsz)
        while i >= 0:
            if (i - off) % 4 == 0:
                out.append(va + i - off)
            i = elf.b.find(pat, i + 1, off + fsz)
    return out


def name_va(elf, cls):
    pat = b"%d%s\x00" % (len(cls), cls.encode())
    for off, va, fsz, flags in elf.loads:
        i = elf.b.find(pat, off, off + fsz)
        while i >= 0:
            if i == off or elf.b[i - 1] < 0x20 or not chr(elf.b[i - 1]).isalnum():
                return va + i - off
            i = elf.b.find(pat, i + 1, off + fsz)
    return None


def movw_movt(w0, w1):
    """(rd, value) when w0 = movw rd, #lo and w1 = movt rd, #hi (cond AL), else None."""
    if (w0 & 0x0FF00000) != 0x03000000 or (w1 & 0x0FF00000) != 0x03400000 or (w0 >> 28) != 0xE:
        return None
    rd0, rd1 = (w0 >> 12) & 15, (w1 >> 12) & 15
    if rd0 != rd1:
        return None
    lo = ((w0 >> 4) & 0xF000) | (w0 & 0xFFF)
    hi = ((w1 >> 4) & 0xF000) | (w1 & 0xFFF)
    return rd0, (hi << 16) | lo


def made_at(elf, value):
    """Indexes of the code that makes `value` in a register (a movw/movt pair, possibly a word apart)."""
    out = []
    for i in elf.movw_by_lo().get(value & 0xFFFF, []):
        for k in (1, 2, 3):
            r = movw_movt(elf.words[i], elf.words[i + k]) if i + k < len(elf.words) else None
            if r and r[1] == value:
                out.append(i)
                break
    for va in words_equal(elf, value):                                 # a literal pool word in the code
        if elf.in_text(va):
            out.append(elf.idx(va))
    return out


def func_start(elf, i):
    while i > 0:
        w = elf.words[i]
        if (w & 0xFFFF0000) == 0xE92D0000 and w & 0x4000:     # push {..., lr}
            return i
        i -= 1
    return 0


def reg_value(elf, i, reg, stop):
    """The value the nearest movw/movt or ldr <reg>, [pc, #] before index i (back to `stop`) put in reg."""
    for j in range(i - 1, stop - 1, -1):
        w = elf.words[j]
        if (w & 0x0FF00000) == 0x03400000 and ((w >> 12) & 15) == reg:
            for k in (1, 2, 3):
                r = movw_movt(elf.words[j - k], w) if j - k >= 0 else None
                if r and r[0] == reg:
                    return r[1]
        if (w & 0xFFFF0000) == 0xE59F0000 and ((w >> 12) & 15) == reg:
            return elf.word(elf.va(j) + 8 + (w & 0xFFF))
    return None


def r0_held(elf, i):
    """r0 at the call at index i: made just before, or copied from a register (`mov r0, rX`) that a load earlier in the
    same function made - a function-local static's object, built behind its __cxa_guard (King Kong, D&D)."""
    v = r0_before(elf, i)
    if v is not None:
        return v
    stop = func_start(elf, i)
    for j in range(i - 1, max(stop, i - 16) - 1, -1):
        w = elf.words[j]
        if (w & 0xFFFFFFF0) == 0xE1A00000:                            # mov r0, rX
            return reg_value(elf, j, w & 15, stop)
    return None


def r0_before(elf, i, back=8):
    """The value movw/movt (or ldr r0, [pc, #]) put in r0 in the few words before index i."""
    for j in range(i - 1, max(0, i - back), -1):
        w = elf.words[j]
        if (w & 0x0FF0F000) == 0x03400000 and j > 0:                  # movt r0, #hi
            for k in (1, 2, 3):
                r = movw_movt(elf.words[j - k], w) if j - k >= 0 else None
                if r and r[0] == 0:
                    return r[1]
        if (w & 0xFFFFF000) == 0xE59F0000:                            # ldr r0, [pc, #imm]
            return elf.word(elf.va(j) + 8 + (w & 0xFFF))
    return None


def find(elf, cls):
    nva = name_va(elf, cls)
    if nva is None:
        return None, None, []
    tis = [x - 4 for x in words_equal(elf, nva)]
    tis = [t for t in tis if elf.word(t) and not elf.in_text(elf.word(t))]
    ti = tis[0] if len(tis) == 1 else None
    if ti is None:
        return None, None, []
    vts = [x + 4 for x in words_equal(elf, ti) if elf.word(x - 4) == 0]
    objs = []
    for vt in vts:
        for i in made_at(elf, vt):
            ctor = elf.va(func_start(elf, i))
            for b in elf.bl_index().get(ctor, []):
                o = r0_held(elf, b)
                if o is not None and not elf.in_text(o):
                    objs.append(o)
    return ti, (vts[0] if vts else None), sorted(set(objs))


def main():
    sys.path.insert(0, REPO)
    from pinball_decryptor.plugins.stern import portgen
    elf = portgen.Elf(sys.argv[1])
    for cls in sys.argv[2:]:
        ti, vt, objs = find(elf, cls)
        print("%s typeinfo %s vtable %s objects %s" % (cls, "0x%08x" % ti if ti else "-", "0x%08x" % vt if vt else "-",
                                                        " ".join("0x%08x" % o for o in objs) or "-"))


if __name__ == "__main__":
    main()
