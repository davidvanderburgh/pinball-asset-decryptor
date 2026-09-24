"""The shots of a Spike 2 game build, read out of its program, for a port drafted from another title.

A port's ``shot <mask> <name>`` lines say which bit the game's shot dispatch hands its rules for
each shot (MODE_SDK.md, "Ports"). A port drafted from ANOTHER title cannot copy them: the bits
are the title's own. They are read from the build itself:

* C++ rule titles (a ``cmode_manager`` or ``crule_manager``) keep one ``cshot`` object per shot,
  built at start-up: its vptr, its mask and the lamp the game lights for it. The objects are
  built by running the code that makes them in unicorn (every call it makes is skipped and
  returns fresh memory, so ``new`` works), and read in the layout the build uses:
  ``{vptr, ?, u64 mask @+8, u16 lamp @+0x10}`` or ``{vptr, u32 mask @+4, u16 lamp @+8}``.
  A bit is named after the insert its lamp is (lampmap), else ``Shot 0x..``.
* Plain-C rule titles have no shot objects. Their switch handlers call one function with a
  constant single bit (r0, or r1:r0 for 64 bits); that function, or the dispatcher it hands
  every bit to, is the shot dispatch, and each constant is a shot. A bit is named after the
  switch whose handler passes it (the game's switch table and device names), else ``Shot 0x..``.

Everything here is a DRAFT: the shot census (census_mode.c, MODE_SDK.md) proves the map.
"""
import struct
from collections import Counter, defaultdict

import numpy as np

from . import portgen as G

HEAP = 0x88000000
HEAP_SIZE = 0x800000
STACK = 0x90000000
RET = 0xA0000000


def _single(v):
    return bool(v) and not v & (v - 1)


# ---- C++: the game's cshot objects ------------------------------------------------------------
def _loads_of(elf, value):
    """Indexes of the instructions that load `value` into a register (movt of a movw/movt pair,
    or ldr rd, [pc, #n] of a literal)."""
    out = []
    for kind, i, extra in G.refs_to(elf, value, limit=200):
        out.append(extra if kind == "movw" else i)
    return out


def _ends(w):
    """An unconditional return or jump: bx lr, pop {.., pc}, ldr pc, b."""
    return (w == 0xE12FFF1E or (w & 0xFFFF8000) == 0xE8BD8000 or (w & 0xFFFFF000) == 0xE49DF000
            or (w & 0xFF000000) == 0xEA000000)


def _fstart(elf, k):
    """The start of the function holding index k: its push {.., lr}, or, for a leaf function
    with no push, the first instruction after the previous function's end and its literals."""
    W = elf.words
    j = k
    while j > 0 and k - j < 4000:
        w = W[j]
        if ((w & 0xFFFF0000) == 0xE92D0000 and w & 0x4000) or w == 0xE52DE004:
            return j
        if j < k and _ends(w):
            break
        j -= 1
    else:
        return j
    start = j + 1
    while start < k and _is_literal(elf, start):
        start += 1
    return start


def _is_literal(elf, i):
    """Is the word at index i read by an `ldr rd, [pc, #n]` just before it (a literal pool)?"""
    W = elf.words
    va = elf.va(i)
    for m in range(i - 1, max(i - 1024, -1), -1):
        u = W[m]
        if (u & 0x0F7F0000) == 0x051F0000 and u & 0x00800000 and elf.va(m) + 8 + (u & 0xFFF) == va:
            return True
    return False


class _Machine:
    """The program mapped once in unicorn. :meth:`run` runs one function with every call skipped
    (returning a fresh zeroed block, so ``new`` works) except calls into `keep`, and records
    every word written equal to one of `vptrs`."""

    def __init__(self, elf, keep, vptrs, steps=2000000):
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UcError
        from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R0
        self.UcError = UcError
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for off, va, fsz, _flags in elf.loads:
            lo = va & ~0xFFF
            msz = _memsz(elf, va, fsz)
            try:
                mu.mem_map(lo, ((va + msz + 0xFFF) & ~0xFFF) - lo)
            except UcError:
                pass
            mu.mem_write(va, elf.b[off:off + fsz])
        mu.mem_map(HEAP, HEAP_SIZE)
        mu.mem_map(STACK, 0x100000)
        mu.mem_map(RET, 0x1000)
        self.heap = HEAP + 0x1000
        self.writes = {}
        self.count = 0
        self.limit = steps

        def on_code(uc, addr, _size, _u):
            self.count += 1
            if addr == RET or self.count > self.limit:
                uc.emu_stop()
                return
            ins = struct.unpack("<I", bytes(uc.mem_read(addr, 4)))[0]
            if (ins & 0x0F000000) == 0x0B000000 and ins >> 28 != 0xF:
                o = ins & 0xFFFFFF
                o = o - 0x1000000 if o & 0x800000 else o
                if addr + 8 + 4 * o in keep:
                    return                     # let a constructor run
            elif (ins & 0x0FFFFFF0) != 0x012FFF30:
                return
            if self.heap + 0x400 >= HEAP + HEAP_SIZE:
                uc.emu_stop()
                return
            uc.reg_write(UC_ARM_REG_R0, self.heap)
            self.heap += 0x400
            uc.reg_write(UC_ARM_REG_PC, addr + 4)

        def on_write(uc, _acc, addr, size, value, _u):
            if size == 4 and value in vptrs:
                self.writes[addr] = value

        mu.hook_add(UC_HOOK_CODE, on_code)
        mu.hook_add(UC_HOOK_MEM_WRITE, on_write)

    def run(self, fn, steps=200000):
        from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR
        self.mu.reg_write(UC_ARM_REG_SP, STACK + 0xF0000)
        self.mu.reg_write(UC_ARM_REG_LR, RET)
        self.count, self.limit = 0, steps
        try:
            self.mu.emu_start(fn, RET)
        except self.UcError:
            pass

    def read(self, addr, n):
        try:
            return bytes(self.mu.mem_read(addr, n))
        except self.UcError:
            return None


def _memsz(elf, va, fsz):
    b = elf.b
    phoff, = struct.unpack_from("<I", b, 0x1C)
    phentsize, phnum = struct.unpack_from("<HH", b, 0x2A)
    for i in range(phnum):
        t, _off, v, _pa, f, msz, _fl, _al = struct.unpack_from("<8I", b, phoff + i * phentsize)
        if t == 1 and v == va and f == fsz:
            return max(msz, fsz)
    return fsz


LAYOUTS = (("u64 mask at +8, lamp at +0x10", 8, "<Q", 0x10),
           ("u32 mask at +4, lamp at +8", 4, "<I", 8),
           ("u32 mask at +8, lamp at +0xc", 8, "<I", 0xC))


def cpp_shots(elf):
    """({mask: lamp id}, how) from the game's cshot objects, or ({}, why not)."""
    vptr = G.class_vptr(elf, b"5cshot")
    if vptr is None:
        return {}, "this program has no class cshot"
    import importlib.util
    if importlib.util.find_spec("unicorn") is None:
        return {}, "unicorn is not installed, so the shot objects were not read"
    vtab = vptr - 8
    makers = set()
    for value in (vtab, vptr):
        for k in _loads_of(elf, value):
            makers.add(elf.va(_fstart(elf, k)))
    if not makers:
        return {}, "no code builds the cshot objects"
    callers = set()
    for m in makers:
        for k in G.bl_callers(elf, m):
            callers.add(elf.va(_fstart(elf, k)))
    m = _Machine(elf, makers, {vptr})
    for fn in sorted(callers | makers):
        m.run(fn)
    objects = sorted(m.writes)
    if not objects:
        return {}, "the code that builds the cshot objects ran but built none"
    best = None
    for name, at, fmt, lamp_at in LAYOUTS:
        bits = {}
        for a in objects:
            raw = m.read(a, 0x18)
            if raw is None:
                continue
            mask = struct.unpack_from(fmt, raw, at)[0]
            lamp = struct.unpack_from("<H", raw, lamp_at)[0]
            if _single(mask):
                bits.setdefault(mask, lamp)
        if best is None or len(bits) > len(best[1]):
            best = (name, bits)
    name, bits = best
    if not bits:
        return {}, "%d cshot objects were built, but none holds a single-bit mask" % len(objects)
    return bits, "%d single-bit shots from %d cshot objects (%s)" % (len(bits), len(objects), name)


# ---- plain C: the function every switch handler hands its bit to --------------------------------
def _const_regs_at(elf, k, back=10):
    """(r0, r1) constants at the call at index k, None where unknown (a short backward read)."""
    W = elf.words
    out = {}
    hi = {}
    for m in range(k - 1, max(k - back, 0) - 1, -1):
        w = W[m]
        if (w & 0x0F000000) == 0x0B000000 or (w & 0x0FFFFFF0) == 0x012FFF30:
            break                            # an earlier call: registers unknown before it
        if (w >> 28) != 0xE:
            rd = (w >> 12) & 0xF
            if rd in (0, 1) and rd not in out:
                out[rd] = None               # a conditional write: unknown
            continue
        rd = (w >> 12) & 0xF
        if rd not in (0, 1) or rd in out:
            continue
        if (w & 0x0FEF0000) == 0x03A00000:            # mov rd, #imm
            out[rd] = (hi.get(rd, 0) << 16) | G.rot_imm(w & 0xFFF) if rd in hi else G.rot_imm(w & 0xFFF)
        elif (w & 0x0FF00000) == 0x03400000:          # movt rd (its movw comes before)
            hi[rd] = G.movw_imm(w)
        elif (w & 0x0FF00000) == 0x03000000:          # movw rd
            out[rd] = (hi.get(rd, 0) << 16) | G.movw_imm(w)
        elif (w & 0x0F7F0000) == 0x051F0000:          # ldr rd, [pc, #n]
            imm = w & 0xFFF
            out[rd] = elf.word(elf.va(m) + 8 + (imm if w & 0x00800000 else -imm))
        elif (w & 0x0C000000) in (0x00000000, 0x04000000):
            out[rd] = None
    return out.get(0), out.get(1)


def _bits_into(elf, dest):
    """{bit: [call indexes]} of the constant single bits callers hand `dest` (r0, or r1:r0), and
    whether any caller used r1."""
    bits = defaultdict(list)
    wide = False
    for k in G.bl_callers(elf, dest):
        r0, r1 = _const_regs_at(elf, k)
        if r0 is None:
            continue
        v = r0 if r1 is None else ((r1 << 32) | r0)
        if r1:
            wide = True
        if _single(v):
            bits[v].append(k)
    return bits, wide


def _compares_bits(elf, va, cap=120):
    """How many distinct single bits the function at va compares r0/r1 (or the register it copied
    r0 into) against."""
    i = elf.idx(va)
    regs = {0, 1}
    seen = set()
    for k in range(i, min(i + cap, len(elf.words))):
        w = elf.words[k]
        if (w & 0x0FEF0FF0) == 0x01A00000 and (w & 0xF) in (0, 1):       # mov rd, r0/r1
            regs.add((w >> 12) & 0xF)
        if (w & 0x0FF0F000) == 0x03500000 and ((w >> 16) & 0xF) in regs:  # cmp rn, #imm
            v = G.rot_imm(w & 0xFFF)
            if _single(v):
                seen.add(v)
        if k > i + 2 and (w & 0xFFFF4000) == 0xE92D4000:
            break
    return len(seen)


def _hands_on(elf, va, cap=400):
    """The function that `va` hands its own r0 to (a `mov r0, rK` of the register it saved r0 in,
    then a bl), when it is a dispatcher on single bits too; None otherwise."""
    i = elf.idx(va)
    saved = {0}
    W = elf.words
    for k in range(i, min(i + cap, len(W) - 1)):
        w = W[k]
        if k > i + 2 and (w & 0xFFFF4000) == 0xE92D4000:
            break
        if (w & 0x0FEF0FF0) == 0x01A00000 and (w & 0xF) == 0 and k < i + 6:
            saved.add((w >> 12) & 0xF)
        if (w & 0x0FEF0FF0) == 0x01A00000 and ((w >> 12) & 0xF) == 0 and (w & 0xF) in saved:
            d = G.bl_dest(elf, k + 1)
            if d is not None and _compares_bits(elf, d) >= 6:
                return d
    return None


def c_shots(elf):
    """For a plain-C title: dict(site=shot dispatch address, mask_at=0, bits=32|64,
    shots={bit: [caller indexes]}, how=...), or None when no function takes a single bit from
    enough switch handlers."""
    bl = elf.bl_index()
    best = None
    for dest, callers in bl.items():
        if len(callers) < 6 or not elf.in_text(dest):
            continue
        bits, wide = _bits_into(elf, dest)
        if len(bits) < 8:
            continue
        # a shot hub compares its bit too (a general-purpose call taking flags does not)
        if _compares_bits(elf, dest) < 4:
            continue
        key = (len(bits), len(callers))
        if best is None or key > best[0]:
            best = (key, dest, bits, wide)
    if best is None:
        return None
    _key, hub, bits, wide = best
    site, how = hub, "0x%x: %d callers hand it %d different single bits" % (hub, len(bl[hub]), len(bits))
    sink = _hands_on(elf, hub)
    if sink is not None:
        more, wide2 = _bits_into(elf, sink)
        for b, ks in more.items():
            bits.setdefault(b, []).extend(ks)
        wide = wide or wide2
        site = sink
        how += "; it hands every bit on to 0x%x, which is hooked (so a shot that goes there directly counts too)" % sink
    if max(bits) >> 32 or any((w & 0x0FFFF000) == 0x03510000 for w in elf.words[elf.idx(site):elf.idx(site) + 8]):
        wide = True                          # it compares r1 too: the mask is r1:r0
    return dict(site=site, mask_at=0, bits=64 if wide else 32, shots=dict(bits), how=how)


# ---- names ------------------------------------------------------------------------------------
def c_shot_names(elf, found, dev_tab):
    """{bit: name} for c_shots()' bits: the switch whose handler passes the bit, from the switch
    descriptors that name that handler (u32 +0 handler, u16 +0x16 device)."""
    names = {}
    if not dev_tab:
        return names
    handlers = defaultdict(set)
    for bit, ks in found["shots"].items():
        for k in ks:
            handlers[elf.va(_fstart(elf, k))].add(bit)
    want = set(handlers)
    for off, va, fsz, flags in elf.loads:
        if flags & 1:
            continue
        skip = (-va) % 4
        n = (fsz - skip) // 4
        if n <= 0:
            continue
        a = np.frombuffer(elf.b, dtype="<u4", count=n, offset=off + skip)
        hits = np.nonzero(np.isin(a, np.array(sorted(want), dtype=np.uint32)))[0]
        for h in hits.tolist():
            rec = off + skip + 4 * h
            if rec + 0x18 > len(elf.b):
                continue
            dev = struct.unpack_from("<H", elf.b, rec + 0x16)[0]
            o = elf.off(dev_tab + 48 * dev)
            if not dev or o is None or o + 0x10 > len(elf.b):
                continue
            name = _cstr(elf, struct.unpack_from("<I", elf.b, o + 0x0C)[0])
            if not name:
                continue
            fn = int(a[h])
            for bit in handlers[fn]:
                names.setdefault(bit, []).append(name)
    return {b: " / ".join(dict.fromkeys(_nice(n) for n in ns)) for b, ns in names.items()}


def _cstr(elf, va, cap=64):
    s = elf.cstring(va, cap) if va else None
    if not s or not all(32 <= c < 127 for c in s):
        return None
    return s.decode("latin1")


def _nice(name):
    """``LEFT ORBIT TARGET`` -> ``Left orbit target`` (the port's shot names are sentence case)."""
    name = " ".join(name.split())
    return name[:1].upper() + name[1:].lower()


def shot_lines(pairs):
    """``shot`` lines for [(mask, name)], sorted by mask; a name two bits share gets its bit."""
    count = Counter(name for _m, name in pairs)
    out = []
    for mask, name in sorted(pairs):
        if count[name] > 1:
            name = "%s (0x%x)" % (name, mask)
        out.append("shot %-15s %s" % ("0x%x" % mask, name[:150]))
    return out
