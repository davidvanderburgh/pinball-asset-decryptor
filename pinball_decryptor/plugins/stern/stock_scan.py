"""What a Spike 2 game program is made of, read off its code: the parts every rule reader shares.

A game program is a stripped 32-bit ARM ELF. The readers in :mod:`.stock_scan_cpp` (titles
whose rules are C++ classes) and :mod:`.stock_scan_c` (titles whose rules are plain C) find a
build's own modes and the numbers they use STRUCTURALLY, on the build itself, with no
reference build and no address list. This module holds what they share:

* :class:`Program` - the ELF's loads, VA <-> file offset, and numpy views of its code
  (branch targets, function starts, ``movw``/``movt`` pairs) built once, so a question such as
  "who calls this function" is a sorted-array lookup, not a walk of the file;
* :func:`decode` / :class:`Val` / :func:`track` - a linear constant tracker over one function:
  every call it makes with the constants in its argument registers (and the instruction words
  each constant came from), the constants it stores into its object's fields, and the virtual
  calls it makes on an object held in a field;
* :func:`class_model` - the C++ class model from RTTI (every class, its bases and its vtable);
* :func:`find_get_adjustment` - the function that reads an operator setting, located by the
  settings table it indexes;
* :func:`kind_of` - where a tracked constant lives, in the table grammar's words (``imm``,
  ``movw``, ``movwt``, ``lit``, ``data`` or ``code``).

Everything is read-only.
"""

import bisect
import collections
import hashlib
import re
import struct

import numpy as np

REG = ("r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12",
       "sp", "lr", "pc")
TERMINATORS = ("poppc", "bxlr")


class ScanError(ValueError):
    """The program can't be read as a Spike 2 game program, with the reason in words."""


# ---- the program ------------------------------------------------------------------------------
class Program:
    """A 32-bit little-endian ARM ELF held in memory, with its code indexed once."""

    def __init__(self, data):
        self.b = bytes(data)
        b = self.b
        if len(b) < 0x34 or b[:4] != b"\x7fELF" or b[4] != 1 or b[5] != 1:
            raise ScanError("not a 32-bit little-endian ELF")
        phoff = struct.unpack_from("<I", b, 0x1C)[0]
        phent, phnum = struct.unpack_from("<HH", b, 0x2A)
        loads = []
        for i in range(phnum):
            o = phoff + i * phent
            if o + 32 > len(b):
                break
            typ, off, va, _pa, fsz, msz, flg, _al = struct.unpack_from("<8I", b, o)
            if typ == 1:
                loads.append((off, va, fsz, msz, flg))
        if not loads:
            raise ScanError("the ELF has no loadable segments")
        self.loads = sorted(loads, key=lambda s: s[1])
        self._va_starts = [s[1] for s in self.loads]
        self._off_sorted = sorted(self.loads, key=lambda s: s[0])
        self._off_starts = [s[0] for s in self._off_sorted]
        text = [s for s in self.loads if s[4] & 1]
        if not text:
            raise ScanError("the ELF has no code segment")
        toff, tva, tfsz = text[0][0], text[0][1], text[0][2]
        if toff + tfsz > len(b):
            raise ScanError("the file is shorter than its code segment (a cut-off copy?)")
        self.tlo, self.thi = tva, tva + tfsz
        self.sha1 = hashlib.sha1(b).hexdigest()
        self.sections = self._sections()
        sec = self.sections.get(".text")
        self.code_end = sec[0] + sec[2] if sec else self.thi
        n = tfsz // 4
        self.tw = np.frombuffer(b, dtype="<u4", count=n, offset=toff)
        self._index = None
        self._movwt = {}
        self._facts = {}
        self._vslots = {}
        self._callconst = {}
        self._regs = {}

    def _sections(self):
        out = {}
        b = self.b
        try:
            shoff = struct.unpack_from("<I", b, 0x20)[0]
            shent, shnum, shstr = struct.unpack_from("<HHH", b, 0x2E)
            if not shoff or not shnum or shoff + shnum * shent > len(b):
                return out
            raw = [struct.unpack_from("<10I", b, shoff + i * shent) for i in range(shnum)]
            stroff = raw[shstr][4]
            for s in raw:
                e = b.find(b"\0", stroff + s[0])
                out[b[stroff + s[0]:e].decode("latin1")] = (s[3], s[4], s[5])
        except (struct.error, IndexError):
            pass
        return out

    # -- addresses --
    def va2off(self, va):
        i = bisect.bisect_right(self._va_starts, va) - 1
        if i < 0:
            return None
        off, v, fsz, _msz, _flg = self.loads[i]
        return off + (va - v) if va < v + fsz else None

    def off2va(self, off):
        i = bisect.bisect_right(self._off_starts, off) - 1
        if i < 0:
            return None
        o, v, fsz, _msz, _flg = self._off_sorted[i]
        return v + (off - o) if off < o + fsz else None

    def word(self, va):
        if va is None:
            return None
        o = self.va2off(va)
        if o is None or o + 4 > len(self.b):
            return None
        return struct.unpack_from("<I", self.b, o)[0]

    def u16(self, va):
        o = self.va2off(va)
        if o is None or o + 2 > len(self.b):
            return None
        return struct.unpack_from("<H", self.b, o)[0]

    def in_text(self, va):
        return self.tlo <= va < self.code_end

    def is_address(self, v):
        i = bisect.bisect_right(self._va_starts, v) - 1
        return i >= 0 and v < self.loads[i][1] + self.loads[i][3]

    def writable_file(self, va):
        i = bisect.bisect_right(self._va_starts, va) - 1
        if i < 0:
            return False
        _off, v, fsz, _msz, flg = self.loads[i]
        return va < v + fsz and bool(flg & 2)

    def cstring(self, va, cap=120):
        o = self.va2off(va) if va else None
        if o is None:
            return None
        end = self.b.find(b"\0", o, o + cap)
        if end <= o:
            return None
        s = self.b[o:end]
        if len(s) < 2 or any(c < 0x20 or c > 0x7E for c in s):
            return None
        return s.decode("latin1")

    # -- where to look for class data --
    def asset_blob(self):
        """``(file offset, end)`` of a ``.data`` section of more than 16 MB (Rush and
        Metallica carry their assets there, 185 and 110 MB), which no class data is in; the
        class scans skip it. None when there is none."""
        sec = self.sections.get(".data")
        if sec and sec[2] > 16 << 20 and sec[1] + sec[2] <= len(self.b):
            return sec[1], sec[1] + sec[2]
        return None

    def scan_ranges(self):
        """The file ranges the class scans read: the whole file less :meth:`asset_blob`."""
        blob = self.asset_blob()
        return [(0, len(self.b))] if not blob else [(0, blob[0]), (blob[1], len(self.b))]

    # -- the code index (built on first use) --
    def _build_index(self):
        w = self.tw
        n = len(w)
        idx = np.arange(n, dtype=np.int64)
        vas = self.tlo + 4 * idx
        op = (w >> 24) & 0xF
        off = (w & 0xFFFFFF).astype(np.int64)
        off = np.where(off & 0x800000, off - 0x1000000, off)
        tgt = (vas + 8 + off * 4) & 0xFFFFFFFF
        cond = w >> 28
        isbl = (op == 0xB) & (cond != 0xF)
        bl_sites = np.nonzero(isbl)[0]
        bl_tgt = tgt[bl_sites]
        order = np.argsort(bl_tgt, kind="stable")
        self._bl_tgt = bl_tgt[order]
        self._bl_site = bl_sites[order]
        self._isbl = isbl
        self._push = np.nonzero((w & 0x0FFF4000) == 0x092D4000)[0]
        self._imm16 = ((((w >> 16) & 0xF) << 12) | (w & 0xFFF)).astype(np.uint32)
        self._rd = ((w >> 12) & 0xF).astype(np.uint8)
        self._ismovw = (w & 0x0FF00000) == 0x03000000
        self._ismovt = (w & 0x0FF00000) == 0x03400000
        self._tgt = tgt
        self._index = True

    def _ensure(self):
        if self._index is None:
            self._build_index()

    def callers(self, target):
        """VAs of every ``bl target``."""
        self._ensure()
        lo = np.searchsorted(self._bl_tgt, target, "left")
        hi = np.searchsorted(self._bl_tgt, target, "right")
        return sorted((self.tlo + 4 * self._bl_site[lo:hi]).tolist())

    def bl_targets(self):
        """``(sites, targets)`` numpy arrays of every ``bl`` (site as a word index)."""
        self._ensure()
        s = np.nonzero(self._isbl)[0]
        return s, self._tgt[s]

    def func_start(self, va):
        """The nearest ``push {..., lr}`` at or before *va* (a function's first instruction)."""
        self._ensure()
        i = (va - self.tlo) // 4
        k = np.searchsorted(self._push, i, "right") - 1
        return self.tlo + 4 * int(self._push[k]) if k >= 0 else self.tlo

    def starts_between(self, lo, hi):
        """Whether a function starts in ``(lo, hi]``: a ``push {..., lr}`` or the target of a
        ``bl`` there. An unconditional branch over one leaves its function (a tail call)."""
        self._ensure()
        i, j = (lo - self.tlo) // 4, (hi - self.tlo) // 4
        if np.searchsorted(self._push, j, "right") > np.searchsorted(self._push, i, "right"):
            return True
        return bool(np.searchsorted(self._bl_tgt, hi, "right")
                    > np.searchsorted(self._bl_tgt, lo, "right"))

    def movwt_values(self, reg):
        """``{value: [VA of the movw]}`` for every ``movw rREG`` followed within six
        instructions by ``movt rREG`` (built once per register)."""
        if reg in self._movwt:
            return self._movwt[reg]
        self._ensure()
        idx = np.nonzero(self._ismovw & (self._rd == reg))[0]
        n = len(self.tw)
        out = {}
        done = np.zeros(len(idx), dtype=bool)
        for j in range(1, 7):
            k = idx + j
            ok = (k < n) & ~done
            k2 = np.where(ok, k, 0)
            hit = ok & self._ismovt[k2] & (self._rd[k2] == reg)
            # a second movw on the register in between ends the pair
            stop = ok & self._ismovw[k2] & (self._rd[k2] == reg)
            for a, bb in zip(idx[hit].tolist(), k2[hit].tolist()):
                v = int(self._imm16[bb]) << 16 | int(self._imm16[a])
                out.setdefault(v, []).append(self.tlo + 4 * a)
            done |= hit | stop
        self._movwt[reg] = out
        return out

    def movwt_sites(self, value):
        """VAs of a ``movw rX, #lo`` followed within six by ``movt rX, #hi`` making *value*."""
        out = []
        for reg in range(13):
            out.extend(self.movwt_values(reg).get(value, ()))
        return sorted(out)

    def literal_loads(self, pool_va):
        """VAs of every ``ldr rX, [pc, #off]`` that loads the word at *pool_va*."""
        pi = (pool_va - self.tlo) // 4
        if not 0 <= pi < len(self.tw):
            return []
        lo = max(0, pi - 1025)
        seg = self.tw[lo:pi + 1024]
        cand = np.nonzero((seg & 0x0F7F0000) == 0x051F0000)[0]
        out = []
        for j in cand.tolist():
            x = int(seg[j])
            va = self.tlo + 4 * (lo + j)
            imm = x & 0xFFF
            if va + 8 + (imm if x & 0x00800000 else -imm) == pool_va:
                out.append(va)
        return out

    def references(self, value):
        """VAs in the code that make *value*: ``movw``/``movt`` pairs and literal loads."""
        out = set(self.movwt_sites(value))
        for pi in np.nonzero(self.tw == value)[0].tolist():
            out.update(self.literal_loads(self.tlo + 4 * pi))
        return sorted(out)

    def call_constants(self, reg):
        """``(sites, targets, values)`` numpy arrays over every ``bl``: the constant a ``mov``
        (an unrotated byte) or ``movw`` puts in *reg* within four instructions before the call
        (-1 when none, or when another call comes first). Built once per register; a quick
        statistic over the whole program, not a tracker."""
        got = self._callconst.get(reg)
        if got is not None:
            return got
        sites, tgts = self.bl_targets()
        w = self.tw
        vals = np.full(len(sites), -1, dtype=np.int64)
        done = np.zeros(len(sites), dtype=bool)
        for k in range(1, 5):
            j = sites - k
            ok = j >= 0
            x = np.where(ok, w[np.where(ok, j, 0)], 0).astype(np.int64)
            call = (x & 0x0F000000) == 0x0B000000
            mov = ((x & 0x0FEF0F00) == 0x03A00000) & (((x >> 12) & 0xF) == reg)
            movw = ((x & 0x0FF00000) == 0x03000000) & (((x >> 12) & 0xF) == reg)
            v = np.where(mov, x & 0xFF, ((x >> 4) & 0xF000) | (x & 0xFFF))
            hit = ~done & ok & (mov | movw)
            vals = np.where(hit, v, vals)
            done |= hit | call
        got = self._callconst[reg] = (sites, tgts, vals)
        return got

    def const_before(self, site, reg, n=8):
        """The constant a ``mov``/``movw``(+``movt``)/``mvn`` puts in *reg* within *n*
        instructions before the call at *site*, or None (a call or any other write to the
        register in between means unknown)."""
        i = (site - self.tlo) // 4
        hi = None
        for k in range(1, n + 1):
            if i - k < 0:
                return None
            w = int(self.tw[i - k])
            if (w & 0x0F000000) == 0x0B000000 or (w & 0x0FFFFFF0) == 0x012FFF30:
                return None
            d = decode(w, site - 4 * k)
            if d[0] == "other":
                if reg in d[1]:
                    return None
                continue
            if d[0] in ("movw", "movt", "mov", "mvn", "ldrlit", "movr", "addi", "subi", "andsi",
                        "ldri") and d[1] == reg:
                if d[-1] != 0xE:
                    return None
                if d[0] == "movt":
                    hi = d[2]
                    continue
                if d[0] == "movw":
                    return (hi << 16 if hi is not None else 0) | d[2]
                if d[0] in ("mov", "mvn"):
                    return ((hi << 16) | (d[2] & 0xFFFF)) if hi is not None else d[2]
                return None
        return None

    # -- one function --
    def facts(self, start, entry_args=False):
        """:func:`track` of the function at *start*, cached."""
        key = (start, entry_args)
        f = self._facts.get(key)
        if f is None:
            f = self._facts[key] = track(self, start, entry_args)
        return f


# ---- instruction words ------------------------------------------------------------------------
def rot_imm(w):
    rot, imm = (w >> 8) & 0xF, w & 0xFF
    return ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF if rot else imm


def imm16(w):
    return ((w >> 16) & 0xF) << 12 | (w & 0xFFF)


def branch_target(w, va):
    off = w & 0xFFFFFF
    if off & 0x800000:
        off -= 0x1000000
    return (va + 8 + off * 4) & 0xFFFFFFFF


def decode(w, va):
    """The instruction shapes the tracker models, as a tuple ending in the condition;
    ``("other", registers it may write, cond)`` for anything else. ARM state only."""
    if w is None:
        return ("other", tuple(range(4)), 0xE)
    cond = w >> 28
    if cond == 0xF:
        return ("other", tuple(range(4)), cond)
    rd = (w >> 12) & 0xF
    rn = (w >> 16) & 0xF
    if (w & 0x0FF00000) == 0x03000000:
        return ("movw", rd, imm16(w), cond)
    if (w & 0x0FF00000) == 0x03400000:
        return ("movt", rd, imm16(w), cond)
    if (w & 0x0FEF0000) == 0x03A00000:
        return ("mov", rd, rot_imm(w), cond)
    if (w & 0x0FEF0000) == 0x03E00000:
        return ("mvn", rd, (~rot_imm(w)) & 0xFFFFFFFF, cond)
    if (w & 0x0F7F0000) == 0x051F0000:
        imm = w & 0xFFF
        return ("ldrlit", rd, (va + 8 + (imm if w & 0x00800000 else -imm)) & 0xFFFFFFFF, cond)
    if (w & 0x0F000000) == 0x0B000000:
        return ("bl", branch_target(w, va), cond)
    if (w & 0x0F000000) == 0x0A000000:
        return ("b", branch_target(w, va), cond)
    if (w & 0x0FFFFFFF) == 0x012FFF1E:
        return ("bxlr", cond)
    if (w & 0x0FFFFFF0) == 0x012FFF30:
        return ("blx", w & 0xF, cond)
    if (w & 0x0FFFFFF0) == 0x012FFF10:
        return ("bx", w & 0xF, cond)
    if (w & 0x0FFF8000) == 0x08BD8000:
        return ("poppc", cond)
    if (w & 0x0FFF4000) == 0x092D4000:
        return ("pushlr", cond)
    if (w & 0x0FEF0FF0) == 0x01A00000:
        return ("movr", rd, w & 0xF, cond)
    if (w & 0x0FE00000) == 0x02800000:
        return ("addi", rd, rn, rot_imm(w), cond)
    if (w & 0x0FE00000) == 0x02400000:
        return ("subi", rd, rn, rot_imm(w), cond)
    if (w & 0x0FF00000) == 0x02100000:
        return ("andsi", rd, rn, rot_imm(w), cond)
    if (w & 0x0F700000) == 0x05100000:                       # ldr rt, [rn, #+-imm]
        imm = w & 0xFFF
        return ("ldri", rd, rn, imm if w & 0x00800000 else -imm, cond)
    if (w & 0x0F700000) == 0x05000000:                       # str rt, [rn, #+-imm]
        imm = w & 0xFFF
        return ("stri", rd, rn, imm if w & 0x00800000 else -imm, cond)
    if (w & 0x0E5000F0) == 0x004000F0 and (w & 0x01000000):  # strd rt, [rn, #+-imm]
        imm = ((w >> 4) & 0xF0) | (w & 0xF)
        return ("strd", rd, rn, imm if w & 0x00800000 else -imm, bool(w & 0x00200000), cond)
    return ("other", written(w), cond)


def written(w):
    """Registers an instruction outside :func:`decode`'s shapes may write (conservative)."""
    op = (w >> 25) & 7
    rd = (w >> 12) & 0xF
    rn = (w >> 16) & 0xF
    if op in (0, 1):
        if (w & 0x0F0000F0) == 0x00000090:                    # multiply family
            return (rn, rd)
        if (w & 0x0FB00FF0) == 0x01000090:                    # swp
            return (rd,)
        if (w & 0x0E000090) == 0x00000090 and (w & 0x60):     # ldrh / ldrsb / ldrd / strd
            out = []
            if w & 0x00100000:
                out.append(rd)
            if (w & 0x00100000) == 0 and (w & 0xF0) == 0xD0:  # ldrd: rt and rt+1
                out += [rd, (rd + 1) & 0xF]
            if not (w & 0x01000000) or (w & 0x00200000):
                out.append(rn)
            return tuple(out)
        opcode = (w >> 21) & 0xF
        if 8 <= opcode <= 11 and (w & 0x00100000):             # tst teq cmp cmn
            return ()
        if (w & 0x0FBF0FFF) == 0x010F0000:                     # mrs
            return (rd,)
        if (w & 0x0FF000F0) == 0x01200010:                     # bx / blx
            return ()
        return (rd,)
    if op in (2, 3):                                          # ldr / str
        out = [rd] if w & 0x00100000 else []
        if not (w & 0x01000000) or (w & 0x00200000):
            out.append(rn)
        return tuple(out)
    if op == 4:                                               # ldm / stm
        out = [r for r in range(16) if (w >> r) & 1] if w & 0x00100000 else []
        if w & 0x00200000:
            out.append(rn)
        return tuple(out)
    if op == 5:
        return (14,) if (w >> 24) & 1 else ()
    return tuple(range(4)) + (rd,)                            # coprocessor / VFP: conservative


# ---- a tracked value ----------------------------------------------------------------------------
class Val:
    """A constant and the instruction(s) that made it: ``sites`` = ``((va, word, how), ...)``
    with how in imm/mvn/movw/movt/lit/data/add/sub/code; ``cond`` = made by a conditional
    instruction (one path only); ``lit`` = the VA of the literal or data word it was loaded
    from."""
    __slots__ = ("v", "sites", "cond", "lit")

    def __init__(self, v, sites, cond=False, lit=None):
        self.v, self.sites, self.cond, self.lit = v & 0xFFFFFFFF, tuple(sites), cond, lit

    def __eq__(self, o):
        return isinstance(o, Val) and o.v == self.v and o.sites == self.sites

    def __hash__(self):
        return hash((self.v, self.sites))

    def fresh(self, va, near=48):
        """Made just before *va* (not a register left over from long ago)."""
        return all(va - near <= s[0] < va for s in self.sites)


class Sym:
    """A symbolic value: ``("this",)``, ``("arg", k)``, ``("field", off)`` (a field of this),
    ``("vptr", obj)`` (the vtable pointer of obj), ``("vfn", obj, slot)``, ``("ret", callee)``
    (what a direct call returned) or ``("vret", obj, slot)`` (what a virtual call returned)."""
    __slots__ = ("t",)

    def __init__(self, *t):
        self.t = t

    def __eq__(self, o):
        return isinstance(o, Sym) and o.t == self.t

    def __hash__(self):
        return hash(self.t)

    def __repr__(self):
        return "Sym%r" % (self.t,)


THIS = Sym("this")


def kind_of(val):
    """``(kind tuple, [word hex])`` for a tracked value, in the table grammar: ``("imm", va)``,
    ``("movw", va)``, ``("movwt", va, va)``, ``("lit", pool va)``, ``("data", va)`` or
    ``("code", va)``. The words are the instruction words (the literal word itself for
    lit/data)."""
    hows = [s[2] for s in val.sites]
    if hows in (["imm"], ["mvn"]):
        return ("imm", val.sites[0][0]), ["%08x" % val.sites[0][1]]
    if hows == ["movw"]:
        return ("movw", val.sites[0][0]), ["%08x" % val.sites[0][1]]
    if hows == ["movw", "movt"]:
        return ("movwt", val.sites[0][0], val.sites[1][0]), ["%08x" % s[1] for s in val.sites]
    if hows == ["imm", "movt"] and rot_imm(val.sites[0][1]) <= 0xFFFF:
        # a plain mov holds the low half and a movt the high: the app writes it as movwt
        return ("movwt", val.sites[0][0], val.sites[1][0]), ["%08x" % s[1] for s in val.sites]
    if hows == ["lit"]:
        return ("lit", val.lit), ["%08x" % val.v]
    if hows and hows[-1] == "data":
        return ("data", val.lit), ["%08x" % val.v]
    return ("code", val.sites[-1][0] if val.sites else 0), ["%08x" % s[1] for s in val.sites]


# ---- one function -------------------------------------------------------------------------------
def tail_branch(prog, start, va, target):
    """An unconditional ``b`` at *va* of the function at *start* leaves the function: it is
    the function's first instruction (a thunk), or a function starts between it and its
    target (the target is another function, placed after this one)."""
    return target > va and (va == start or prog.starts_between(va, target))


def ends_flow(d):
    """An unconditional instruction control never falls through: a return, a ``b`` or a
    ``bx`` through a register."""
    return d[-1] == 0xE and (d[0] in TERMINATORS or d[0] in ("b", "bx"))


def function_extent(prog, start, cap=6000):
    """``(end VA, set of literal-pool VAs)``: forward from *start* to a return or an
    unconditional branch at or past every forward branch target seen, skipping pools. A tail
    call (:func:`tail_branch`) is not a branch inside the function: walking on to its target
    would read the functions after this one as its code."""
    lits, far, va = set(), start, start
    for _n in range(cap):
        if va in lits:
            va += 4
            continue
        w = prog.word(va)
        if w is None:
            break
        d = decode(w, va)
        if d[0] == "ldrlit":
            lits.add(d[2])
        elif d[0] == "b" and start <= d[1] < start + cap * 4 \
                and not (d[-1] == 0xE and tail_branch(prog, start, va, d[1])):
            far = max(far, d[1])
        if ends_flow(d) and va >= far:
            return va + 4, lits
        if d[0] == "pushlr" and va > start and va > far:
            return va, lits
        va += 4
    return va, lits


class Facts:
    """What one function does, as :func:`track` read it."""
    __slots__ = ("start", "end", "calls", "vcalls", "stores", "store_at", "strd64", "lits",
                 "vloads")

    def __init__(self, start):
        self.start, self.end = start, start
        self.calls = []          # {"va", "target", "args": {r0..r3, sp<off>: Val|Sym}, "tail"}
        self.vcalls = []         # {"va", "obj": Sym|None, "slot", "args": {r1..r3: Val|Sym}}
        self.stores = {}         # this-field offset -> Val (unconditional constant stores)
        self.store_at = {}       # this-field offset -> VA of that store
        self.strd64 = []         # (va, lo Val, hi Val, base Sym|None, offset)
        self.lits = set()
        self.vloads = set()      # slots of this's own vtable the function loads


def track(prog, start, entry_args=False):
    """Walk one function linearly with r0 = ``this`` at entry (and r1..r3 = its arguments
    when *entry_args*). A branch target's state is what every path into it agrees on; a
    backward branch (a loop) forgets everything; code after a return or an unconditional
    branch that no branch reaches starts from nothing. Returns :class:`Facts`."""
    end, lits = function_extent(prog, start)
    out = Facts(start)
    out.end, out.lits = end, lits
    sources = {}
    for va in range(start, end, 4):
        if va in lits:
            continue
        d = decode(prog.word(va), va)
        if d[0] == "b" and start <= d[1] < end \
                and not (d[-1] == 0xE and tail_branch(prog, start, va, d[1])):
            sources.setdefault(d[1], []).append(va)
    state = {0: THIS}
    if entry_args:
        state.update({k: Sym("arg", k) for k in (1, 2, 3)})
    stack, saved = {}, {}
    prev = None
    va = start
    while va < end:
        if va in lits:
            va += 4
            continue
        w = prog.word(va)
        d = decode(w, va)
        falls = not (prev is not None and ends_flow(prev))
        if va in sources and va != start:
            srcs = sources[va]
            if any(s > va for s in srcs):
                state, stack = {}, {}
            else:
                preds = [saved.get(s, ({}, {})) for s in srcs] + ([(state, stack)] if falls else [])
                st0, sk0 = preds[0]
                state = {r: v for r, v in st0.items() if all(p[0].get(r) == v for p in preds[1:])}
                stack = {o: v for o, v in sk0.items() if all(p[1].get(o) == v for p in preds[1:])}
        elif not falls:
            state, stack = {}, {}            # nothing reaches this but the walk: no state
        kind = d[0]
        cond = d[-1] != 0xE
        if kind == "movw":
            state[d[1]] = Val(d[2], [(va, w, "movw")], cond)
        elif kind == "movt":
            lo = state.get(d[1])
            if isinstance(lo, Val) and [s[2] for s in lo.sites] in (["movw"], ["imm"]) \
                    and lo.v <= 0xFFFF:
                state[d[1]] = Val(d[2] << 16 | (lo.v & 0xFFFF), list(lo.sites) + [(va, w, "movt")],
                                  cond or lo.cond)
            else:
                state.pop(d[1], None)
        elif kind in ("mov", "mvn"):
            state[d[1]] = Val(d[2], [(va, w, "imm" if kind == "mov" else "mvn")], cond)
        elif kind == "ldrlit":
            lw = prog.word(d[2])
            if lw is None:
                state.pop(d[1], None)
            else:
                state[d[1]] = Val(lw, [(va, w, "lit")], cond, lit=d[2])
        elif kind == "movr":
            src = state.get(d[2])
            if src is None or cond:
                state.pop(d[1], None)
            elif isinstance(src, Val):
                state[d[1]] = Val(src.v, src.sites, src.cond, src.lit)
            else:
                state[d[1]] = src
        elif kind in ("addi", "subi"):
            src = state.get(d[2])
            if isinstance(src, Val) and d[2] != 15:
                nv = src.v + d[3] if kind == "addi" else src.v - d[3]
                state[d[1]] = Val(nv, list(src.sites) + [(va, w, "add" if kind == "addi" else "sub")],
                                  src.cond or cond, src.lit)
            else:
                state.pop(d[1], None)
        elif kind == "andsi":
            state.pop(d[1], None)
        elif kind == "stri":
            rt_, rn, imm = d[1], d[2], d[3]
            if rn == 13:
                if rt_ in state and not cond:
                    stack[imm] = state[rt_]
                else:
                    stack.pop(imm, None)
            elif state.get(rn) == THIS and isinstance(state.get(rt_), Val) and not cond \
                    and imm >= 0:
                out.stores[imm] = state[rt_]
                out.store_at[imm] = va
        elif kind == "strd":
            rt_, rn, imm = d[1], d[2], d[3]
            lo_, hi_ = state.get(rt_), state.get(rt_ + 1)
            if isinstance(lo_, Val) and isinstance(hi_, Val) and not cond:
                base = state.get(rn)
                out.strd64.append((va, lo_, hi_, base if isinstance(base, Sym) else None, imm))
            if rn == 13:
                stack.pop(imm, None)
                stack.pop(imm + 4, None)
            if d[4]:
                state.pop(rn, None)
        elif kind == "ldri":
            base = state.get(d[2])
            state.pop(d[1], None)
            if d[2] == 13 and d[3] >= 0:
                if d[3] in stack:
                    state[d[1]] = stack[d[3]]
            elif base == THIS and d[3] > 0:
                state[d[1]] = Sym("field", d[3])
            elif isinstance(base, Sym) and d[3] == 0 \
                    and base.t[0] in ("field", "this", "arg", "ret", "vret"):
                state[d[1]] = Sym("vptr", base)
            elif d[3] == 0 and base is None and d[1] == d[2]:
                state[d[1]] = Sym("vptr", None)
            elif isinstance(base, Sym) and base.t[0] == "vptr" and d[3] >= 0 and d[3] % 4 == 0:
                state[d[1]] = Sym("vfn", base.t[1], d[3] // 4)
                if base.t[1] == THIS:
                    out.vloads.add(d[3] // 4)
            elif isinstance(base, Val) and prog.writable_file(base.v + d[3]):
                dv = prog.word(base.v + d[3])
                if dv is not None:
                    state[d[1]] = Val(dv, list(base.sites) + [(va, w, "data")], cond,
                                      lit=base.v + d[3])
        elif kind == "bl":
            args = {REG[r]: state[r] for r in range(4) if r in state}
            for o, v in stack.items():
                args["sp%d" % o] = v
            out.calls.append({"va": va, "target": d[1], "args": args, "cond": cond})
            for r in (0, 1, 2, 3, 12, 14):
                state.pop(r, None)
            if not cond:
                state[0] = Sym("ret", d[1])                        # what the callee returned
            stack = {o: v for o, v in stack.items() if o >= 8}     # spills survive a call
        elif kind in ("blx", "bx"):
            fn = state.get(d[1])
            vf = isinstance(fn, Sym) and fn.t[0] == "vfn"
            if vf and (kind == "blx" or d[1] != 14):
                out.vcalls.append({"va": va, "obj": fn.t[1], "slot": fn.t[2],
                                   "args": {REG[r]: state[r] for r in range(0, 4) if r in state}})
            for r in (0, 1, 2, 3, 12, 14):
                state.pop(r, None)
            if vf and kind == "blx" and not cond:
                state[0] = Sym("vret", fn.t[1], fn.t[2])           # what the virtual returned
            stack = {o: v for o, v in stack.items() if o >= 8}
        elif kind == "b":
            st = dict(state)
            if d[-1] == 0x0 and prev is not None and prev[0] == "andsi":   # beq after ands: 0
                st[prev[1]] = Val(0, [(va - 4, prog.word(va - 4), "code")], False)
            saved[va] = (st, dict(stack))
            if d[-1] == 0xE and (not (start <= d[1] < end) or tail_branch(prog, start, va, d[1])):
                out.calls.append({"va": va, "target": d[1], "tail": True, "cond": False,
                                  "args": {REG[r]: state[r] for r in range(4) if r in state}})
        elif kind == "other":
            for r in d[1]:
                state.pop(r, None)
        prev = d
        va += 4
    return out


# ---- who else reads a constant -------------------------------------------------------------------
_REG_INDEX = {n: i for i, n in enumerate(REG)}
_REG_INDEX.update({"sb": 9, "sl": 10, "fp": 11, "ip": 12})
_CS = []


def _disassembler():
    if not _CS:
        import capstone
        cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
        cs.detail = True
        _CS.append(cs)
    return _CS[0]


def _regs_at(prog, va):
    """``(registers read, registers written)`` (as numbers) of the instruction at *va*, None
    for a word that isn't one. Disassembled once per program."""
    cache = prog._regs
    if va in cache:
        return cache[va]
    o = prog.va2off(va)
    cs = _disassembler()
    if o is not None:
        for i in cs.disasm(prog.b[o:o + 256], va):
            r, w = i.regs_access()
            cache[i.address] = (frozenset(_REG_INDEX[cs.reg_name(x)] for x in r
                                          if cs.reg_name(x) in _REG_INDEX),
                                frozenset(_REG_INDEX[cs.reg_name(x)] for x in w
                                          if cs.reg_name(x) in _REG_INDEX))
    return cache.setdefault(va, None)


def other_uses(prog, val, facts, consumer):
    """Where else the value the instruction(s) of *val* put in a register is read, besides
    the read(s) at *consumer* (a VA or several: a ``str`` into a field, or a call handed it):
    ``[VA]``, empty when those are the only ones. Editing the instruction changes every read,
    so a number is only its own when the list is empty.

    The register is followed through the function of *facts* (every path: a forward branch
    carries it to its target) until each path writes it again, a call clobbers it (r0-r3,
    r12 - a call it's live into may take it as an argument: a read), or the function returns
    (r0: the return value, a read). A backward branch while it is live (a loop), or an
    instruction that can't be read, counts as a read at that VA: unknown is not "only one"."""
    if not val.sites:
        return []
    va0 = val.sites[-1][0]
    try:
        got = _regs_at(prog, va0)
    except ImportError:
        return [va0]
    if not got or len(got[1]) != 1:
        return [va0]
    reg = next(iter(got[1]))
    mine = {consumer} if isinstance(consumer, int) else set(consumer)
    start, end, lits = facts.start, facts.end, facts.lits
    uses, pending, live = [], set(), True
    va = va0 + 4
    while va < end:
        if va in pending:
            pending.discard(va)
            live = True
        if not live:
            nxt = [t for t in pending if t > va]
            if not nxt:
                break
            va = min(nxt)
            continue
        if va in lits:
            va += 4
            continue
        w = prog.word(va)
        d = decode(w, va)
        rw = _regs_at(prog, va)
        if rw is None:
            uses.append(va)
            va += 4
            continue
        reads, writes = rw
        cond = d[-1] != 0xE
        if reg in reads and va not in mine:
            uses.append(va)
        if d[0] in ("bl", "blx"):
            if reg <= 3 and va not in mine:
                uses.append(va)                       # it may be an argument
            if (reg <= 3 or reg == 12) and not cond:
                live = False                          # the callee may overwrite it
        elif d[0] == "b":
            tgt = d[1]
            inside = start <= tgt < end and not (not cond and tail_branch(prog, start, va, tgt))
            if not inside:
                if reg <= 3 and va not in mine:
                    uses.append(va)                   # a tail call may take it
            elif tgt <= va:
                uses.append(va)                       # a loop: it comes round again
            else:
                pending.add(tgt)
            if not cond:
                live = False
        elif d[0] in TERMINATORS or d[0] == "bx":
            if reg == 0 or (d[0] == "bx" and reg <= 3):
                if va not in mine:
                    uses.append(va)
            if not cond:
                live = False
        elif reg in writes and not cond:
            live = False                              # replaced (a read was counted above)
        va += 4
    if val.lit is not None and val.sites[-1][2] == "lit":
        uses += [x for x in prog.literal_loads(val.lit) if x != va0]    # the word is shared
    return sorted(set(uses))


def const_return(prog, fn):
    """A function that only returns a constant: ``(value, kind tuple, [word hex])``, or None.
    ``mov r0, #v; bx lr``, ``movw r0, #v; bx lr`` or a literal load then ``bx lr``."""
    w0, w1 = prog.word(fn), prog.word(fn + 4)
    if w0 is None or w1 is None:
        return None
    d0, d1 = decode(w0, fn), decode(w1, fn + 4)
    if d1[0] == "bxlr" and d1[-1] == 0xE and d0[-1] == 0xE and d0[0] in ("mov", "movw") \
            and d0[1] == 0:
        return d0[2], ("imm" if d0[0] == "mov" else "movw", fn), ["%08x" % w0]
    if d1[0] == "bxlr" and d1[-1] == 0xE and d0[0] == "ldrlit" and d0[1] == 0 and d0[-1] == 0xE:
        lw = prog.word(d0[2])
        if lw is not None:
            return lw, ("lit", d0[2]), ["%08x" % lw]
    return None


# ---- the C++ class model ----------------------------------------------------------------------
_NAME_RE = re.compile(rb"\0(N?(?:\d+[A-Za-z_][A-Za-z0-9_]*)+E?)\0")
_MANGLED_RE = re.compile(rb"N?(?:\d+[A-Za-z_][A-Za-z0-9_]*)+E?")


def demangle_simple(s):
    """Good enough for the game's own classes: ``12cmode_battle`` -> ``cmode_battle``,
    ``N6Radium5SoundE`` -> ``Radium::Sound``, ``9SingletonI13cmode_managerE`` ->
    ``Singleton<cmode_manager>``."""
    parts = []
    i = 1 if s.startswith("N") else 0
    while i < len(s):
        m = re.match(r"\d+", s[i:])
        if not m:
            break
        n = int(m.group(0))
        i += len(m.group(0))
        parts.append(s[i:i + n])
        i += n
        if i < len(s) and s[i] == "I":
            inner = s[i + 1:]
            m2 = re.match(r"(\d+)", inner)
            if m2:
                k = int(m2.group(1))
                parts[-1] = "%s<%s>" % (parts[-1], inner[len(m2.group(1)):len(m2.group(1)) + k])
            break
    return "::".join(parts) if parts else s


def class_model(prog):
    """``{class name: {"mangled", "typeinfo", "base", "bases", "vtable", "nvirt"}}`` from the
    program's RTTI (a stripped program keeps it): every typeinfo object (a word pointing at a
    mangled name, then its base typeinfo(s)) and every vtable (``[0][typeinfo][functions]``).
    The candidate words are found with numpy; the rules are GCC's typeinfo layouts."""
    b = prog.b
    u32 = lambda o: struct.unpack_from("<I", b, o)[0]  # noqa: E731
    names = {}
    for lo, hi in prog.scan_ranges():
        for m in _NAME_RE.finditer(b, lo, hi):
            s = m.group(1)
            if not re.search(rb"[A-Za-z]{3,}", s):
                continue
            va = prog.off2va(m.start() + 1)
            if va is not None:
                names[va] = s.decode()
    n4 = len(b) // 4
    arr = np.frombuffer(b, dtype="<u4", count=n4)
    keep = np.ones(n4, dtype=bool)
    skip = prog.asset_blob()
    if skip:
        keep[skip[0] // 4:skip[1] // 4] = False
    name_vas = np.fromiter(names.keys(), dtype=np.uint32, count=len(names))
    lim = min((len(b) - 12 + 3) // 4, n4 - 1)
    ti = {}
    for i in np.nonzero(np.isin(arr[1:lim + 1], name_vas) & keep[:lim])[0].tolist():
        off = 4 * i
        va = prog.off2va(off)
        if va is not None:
            ti[va] = {"mangled": names[int(arr[i + 1])], "off": off}

    def cstr(va):
        o = prog.va2off(va)
        if o is None:
            return None
        e = b.find(b"\0", o, o + 256)
        return b[o:e] if e > o else None

    def adopt(tva):
        # a base typeinfo the name scan missed (names are packed straight after typeinfo
        # data, so the byte before one is not always NUL)
        if tva in ti:
            return True
        o = prog.va2off(tva)
        if o is None or o + 8 > len(b):
            return False
        s = cstr(u32(o + 4))
        if not s or not _MANGLED_RE.fullmatch(s):
            return False
        ti[tva] = {"mangled": s.decode(), "off": o}
        return True

    def resolve_bases():
        pending = [x for x in ti if "bases" not in ti[x]]
        while pending:
            rec = ti[pending.pop()]
            if "bases" in rec:
                continue
            off = rec["off"]
            bases = []
            w8 = u32(off + 8) if off + 12 <= len(b) else 0
            if adopt(w8):
                bases = [w8]
            else:
                count = u32(off + 12) if off + 16 <= len(b) else 0
                if 1 <= count <= 8 and off + 16 + 8 * count <= len(b):
                    cand = [u32(off + 16 + 8 * i) for i in range(count)]
                    if all(adopt(c) for c in cand):
                        bases = cand
            rec["bases"] = bases
            pending.extend(x for x in bases if "bases" not in ti[x])

    resolve_bases()
    tivptrs = {u32(r["off"]) for r in ti.values()}
    tlo, thi = prog.tlo, prog.thi
    lim = min((len(b) - 8 + 3) // 4, n4 - 2)
    a0, a1, a2 = arr[:lim], arr[1:lim + 1], arr[2:lim + 2]
    cand = np.nonzero((a0 == 0) & (a2 >= tlo) & (a2 < thi) & (a1 != 0) & keep[:lim])[0]
    in_text = (arr >= tlo) & (arr < thi)
    vt = {}
    for i in cand.tolist():
        tva = int(arr[i + 1])
        if tva not in ti:
            o = prog.va2off(tva)
            if o is None or o + 8 > len(b) or u32(o) not in tivptrs or not adopt(tva):
                continue
        j = i + 2
        stop = np.argmin(in_text[j:j + 4096]) if j < n4 else 0
        k = int(stop) if stop or not in_text[j] else min(4096, n4 - j)
        if k:
            vt.setdefault(tva, []).append((prog.off2va(4 * i), k))
    resolve_bases()
    model = {}
    for va, rec in ti.items():
        name = demangle_simple(rec["mangled"])
        bases = [demangle_simple(ti[bv]["mangled"]) for bv in rec["bases"]]
        vts = sorted(vt.get(va, []), key=lambda x: -x[1])
        model[name] = {"mangled": rec["mangled"], "typeinfo": va,
                       "base": bases[0] if bases else None, "bases": bases,
                       "vtable": vts[0][0] if vts else None, "nvirt": vts[0][1] if vts else None}
    return model


def derives(model, cls, base):
    c = cls
    seen = set()
    while c and c not in seen:
        if c == base:
            return True
        seen.add(c)
        c = (model.get(c) or {}).get("base")
    return False


def chain_of(model, cls):
    out, seen = [], {cls}
    c = (model.get(cls) or {}).get("base")
    while c and c not in seen:
        out.append(c)
        seen.add(c)
        c = (model.get(c) or {}).get("base")
    return out


def plausible_function(prog, fn):
    """A vtable entry is a function only if it starts where a function can: a push, or right
    after a return, an unconditional branch or a literal-pool word. The RTTI walk counts slots
    until the words stop pointing into the code, so a vtable's tail can hold data words."""
    if fn is None or not prog.in_text(fn) or fn & 3:
        return False
    d = decode(prog.word(fn), fn)
    if d[0] == "pushlr":
        return True
    pw = prog.word(fn - 4)
    if pw is None:
        return True
    p = decode(pw, fn - 4)
    flowing = p[0] in ("movw", "movt", "mov", "mvn", "addi", "subi", "andsi", "ldri", "stri",
                       "movr", "ldrlit") or (
        p[0] == "other" and (pw >> 26) & 3 in (0, 1) and (pw & 0x0FFFFFF0) != 0x012FFF10)
    if not flowing or p[-1] != 0xE or pw in (0xE320F000, 0xE1A00000):
        return True
    return bool(prog.literal_loads(fn - 4))


def vslots(prog, model, cls):
    """The class's virtual functions, cut at the first entry that is not a function."""
    m = model.get(cls)
    if not m or not m.get("vtable"):
        return []
    got = prog._vslots.get(cls)
    if got is None:
        got = []
        for k in range(m["nvirt"]):
            f = prog.word(m["vtable"] + 8 + 4 * k)
            if not plausible_function(prog, f):
                break
            got.append(f)
        prog._vslots[cls] = got
    return got


def ancestor_with_vtable(model, cls):
    """The class *cls*'s slots are compared against: the nearest base with a vtable of its
    own, and for an abstract base with none its concrete ``<base>_null`` twin."""
    b = (model.get(cls) or {}).get("base")
    seen = set()
    while b and b not in seen and not (model.get(b) or {}).get("vtable"):
        seen.add(b)
        null = b + "_null"
        if (model.get(null) or {}).get("vtable") and null != cls:
            return null
        b = (model.get(b) or {}).get("base")
    return b


def own_slots(prog, model, cls):
    """``(base, [(slot, function)])``: the virtuals *cls* overrides against its base."""
    mine = vslots(prog, model, cls)
    base = ancestor_with_vtable(model, cls)
    theirs = vslots(prog, model, base) if base else []
    return base, [(k, f) for k, f in enumerate(mine)
                  if not (k < len(theirs) and theirs[k] == f)]


# ---- engine functions every title has ---------------------------------------------------------
def constant_callers(prog, fn, reg=0, accept=None):
    """``(how many callers of fn pass a constant in reg, how many callers)``; *accept*, when
    given, filters the constant."""
    sites = prog.callers(fn)
    n = 0
    for s in sites:
        v = prog.const_before(s, reg)
        if v is not None and (accept is None or accept(v)):
            n += 1
    return n, len(sites)


def find_indexer(prog, table_va, count, extra_refs=()):
    """The function that indexes a descriptor table: of the functions that make the table's
    VA (or one of *extra_refs*), the one whose callers most often pass a constant id below
    *count* in r0. None when nothing does."""
    refs = set(prog.references(table_va))
    for r in extra_refs:
        refs.update(prog.references(r))
    best = (0, None)
    for f in sorted({prog.func_start(s) for s in refs}):
        n, _tot = constant_callers(prog, f, 0, lambda v: 0 < v < count)
        if n > best[0]:
            best = (n, f)
    return best[1]


def settings_table(prog):
    """The program's :class:`.adjustments.AdjustmentTable`, found with numpy (the same rules;
    a Python walk of every word costs seconds on the biggest programs). Raises ValueError as
    the class does."""
    from .adjustments import _AD_RE, AdjustmentTable

    class _Fast(AdjustmentTable):
        def _find_names(self):
            ad_va = {}
            for m in _AD_RE.finditer(self.data):
                va = prog.off2va(m.start())
                if va is not None:
                    ad_va[va] = self.data[m.start():m.end() - 1].decode("latin1")
            if not ad_va:
                raise ValueError("no AD_ name array found")
            keys = np.fromiter(ad_va.keys(), dtype=np.uint32, count=len(ad_va))
            best = (0, None)
            for po, pv, fsz in self._loads:
                base = (po + 3) & ~3
                n = (po + fsz - base) // 4
                if n <= 0:
                    continue
                hit = np.isin(np.frombuffer(self.data, dtype="<u4", count=n, offset=base),
                              keys).astype(np.int8)
                if not hit.any():
                    continue
                d = np.diff(np.concatenate(([0], hit, [0])))
                starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
                k = int(np.argmax(ends - starts))
                if ends[k] - starts[k] > best[0]:
                    best = (int(ends[k] - starts[k]), pv + (base + 4 * int(starts[k]) - po))
            if best[1] is None:
                raise ValueError("no AD_ name array found")
            names, va = [], best[1]
            while True:
                w = struct.unpack_from("<I", self.data, self._off(va))[0]
                if w in ad_va:
                    names.append(ad_va[w])
                else:
                    s = self._cstr(w) if w else None
                    if names and (not s or not s.startswith("AD_")):
                        break
                    names.append(s or "")
                va += 4
                if len(names) > 6000:
                    break
            return names

        def _find_section(self):
            target = len(self.names)
            for po, _pv, fsz in self._loads:
                if po % 4:
                    return AdjustmentTable._find_section(self)
                n = fsz // 4
                if n < 5:
                    continue
                w = np.frombuffer(self.data, dtype="<u4", count=n, offset=po)
                el = w[3:n - 1]
                cand = np.nonzero((w[2:n - 2] == target) & (el >= 24) & (el <= 96)
                                  & (el % 4 == 0))[0]
                for j in cand.tolist():
                    i = po + 4 * j
                    if i + 20 > po + fsz:
                        break
                    table, _c, elem, node = struct.unpack_from("<IIII", self.data, i + 4)
                    node_s = self._cstr(node, 16)
                    if self._off(table) is not None and node_s:
                        return table, target, elem, node_s, self._va(i)
            raise ValueError("adjustment section record not found")

    return _Fast(prog.b)


def find_get_adjustment(prog):
    """``(get_adjustment VA or None, AdjustmentTable or None)``: the function that indexes
    the operator settings table (``AdjustmentTable``'s VA, or the record that holds it)."""
    try:
        at = settings_table(prog)
    except ValueError:
        return None, None
    extra = (at.record_va, at.record_va + 4) if getattr(at, "record_va", None) else ()
    return find_indexer(prog, at.table_va, at.count, extra), at


# ---- words for a person ---------------------------------------------------------------------------
_SMALL = ("vs", "and", "of", "the", "a", "an", "to", "in", "on", "at", "for", "mb")


def readable(words):
    """``DRIVE_MY_CAR`` / ``drive_my_car`` -> ``Drive My Car``; ``mb`` -> ``Multiball``."""
    out = []
    for w in re.split(r"[_\s]+", words.strip()):
        if not w:
            continue
        lw = w.lower()
        if lw == "mb":
            out.append("Multiball")
        elif lw in _SMALL and out:
            out.append(lw)
        elif re.fullmatch(r"[ivx]+", lw) and out:
            out.append(lw.upper())
        else:
            out.append(lw.capitalize())
    return " ".join(out)


def class_words(cls):
    """A C++ mode class's name in words: ``cmode_battle_vs_ebirah`` -> ``Battle vs Ebirah``,
    ``cepisode_one`` -> ``Episode One``, ``choth_i`` -> ``Hoth I``."""
    s = cls.split("::")[-1]
    if s.startswith("cmode_"):
        s = s[6:]
    elif re.match(r"^c[a-z]", s):
        s = s[1:]
    return readable(s)


# ---- what a reader found, and the table text -----------------------------------------------------
class Row:
    """One number of one mode, in the table grammar: ``key`` (unique within the mode),
    ``value`` (None = not measured), ``kind`` (a :func:`kind_of` tuple, or ``("adj", name,
    id)``), ``words`` (hex strings), ``klass`` (``word``, ``adjustment``, ``code`` or
    ``uncertain``) and a comment saying where it was read. A word kind may carry several
    sites (``("imm", va1, va2)``): one number the game keeps in several places, edited
    together."""
    __slots__ = ("key", "value", "kind", "words", "klass", "comment", "shared")

    def __init__(self, key, value, kind, words, klass, comment="", shared=0):
        self.key, self.value, self.kind, self.words = key, value, tuple(kind), list(words)
        self.klass, self.comment, self.shared = klass, comment, shared

    @property
    def vas(self):
        return tuple(self.kind[1:]) if self.kind and self.kind[0] != "adj" else ()


class ModeRead:
    """One mode a reader found."""

    def __init__(self, mid, cls, name, obj=0, vtable=0, title_msg=None):
        self.id, self.cls, self.name = mid, cls, name
        self.obj, self.vtable, self.title_msg = obj, vtable, title_msg
        self.facts = []          # extra fact lines ("ctor ...", "start ..."), without the id
        self.rows = []
        self._keys = collections.Counter()

    def key(self, k):
        """*k*, or ``k@2``, ``k@3``... for a repeat within this mode."""
        self._keys[k] += 1
        return k if self._keys[k] == 1 else "%s@%d" % (k, self._keys[k])

    def add(self, key, value, kind, words, klass, comment="", shared=0):
        row = Row(self.key(key), value, kind, words, klass, comment, shared)
        self.rows.append(row)
        return row


def settle_shared(reading):
    """Make a reading's word rows honest about the instruction words they share.

    * Within one mode, rows at the same words (one instruction read as two numbers, say a
      timer and one of its settings) become ONE row: the named key is kept, the others are
      listed in its comment, and it is read-only when any of them was.
    * Across modes, every word row whose words another mode's row also holds carries
      ``shared N`` = the number of modes holding them (objects, not classes: two objects of
      one class are two modes), so the tab says that changing it changes them all."""
    for m in reading.modes:
        kept, first = [], {}
        for r in m.rows:
            vas = tuple(sorted(r.vas)) if r.klass in ("word", "uncertain") else ()
            if not vas:
                kept.append(r)
                continue
            if vas not in first:
                first[vas] = r
                kept.append(r)
                continue
            a = first[vas]
            if a.key.split("@")[0].startswith("timer.v") and r.key.startswith("timer.seconds"):
                a.key, r.key = r.key, a.key         # keep the decoded name
            a.comment = "%s; the same word(s) as %s (%s)" % (a.comment, r.key, r.comment)
            if r.klass == "uncertain" and a.klass == "word":
                a.klass = "uncertain"
                a.comment = "it is also read as %s, so its meaning isn't one number; %s" % (
                    r.key, a.comment)
            a.shared = max(a.shared, r.shared)
        m.rows = kept
    modes_at = collections.defaultdict(set)
    for m in reading.modes:
        for r in m.rows:
            if r.klass in ("word", "uncertain"):
                for va in r.vas:
                    modes_at[va].add(m.id)
    for m in reading.modes:
        for r in m.rows:
            if r.klass in ("word", "uncertain") and r.vas:
                n = len(set().union(*(modes_at[va] for va in r.vas)))
                if n > 1:
                    r.shared = max(r.shared, n)


class Reading:
    """What a reader found on one game program: the modes, the engine functions it located
    (name -> VA or None) and notes for a person."""

    def __init__(self, family):
        self.family = family
        self.modes = []
        self.engine = {}
        self.notes = []
        self.seconds = 0.0


def fmt_kind(kind):
    if kind[0] == "adj":
        return "adj %s %d" % (kind[1], kind[2])
    return " ".join([kind[0]] + ["0x%x" % x for x in kind[1:]])


def _flat(text):
    return " ".join(str(text).split())


def table_text(game, version, sha1, reading, header=()):
    """The table grammar (MODE_SDK.md, "The game's own modes", format 1) for *reading*, the
    text :func:`.stock_modes.parse` reads."""
    out = ["build %s %s sha1 %s" % (game, version, sha1)]
    for h in header:
        out.append("# " + _flat(h))
    eng = " ".join("%s %s" % (k, "0x%x" % v if isinstance(v, int) else (v if v else "?"))
                   for k, v in sorted(reading.engine.items()))
    if eng:
        out.append("# engine on this build: " + eng)
    for n in reading.notes:
        out.append("# " + _flat(n))
    for m in reading.modes:
        out.append("")
        out.append("mode %d %s obj 0x%x vtable 0x%x title_msg %s name %s" % (
            m.id, m.cls, m.obj or 0, m.vtable or 0,
            "?" if m.title_msg is None else m.title_msg,
            re.sub(r"\s+", "_", m.name.strip()) or "?"))
        for f in m.facts:
            if f.startswith("#"):
                out.append(_flat(f))
                continue
            what, _sp, rest = f.partition(" ")
            out.append("%s %d %s" % (what, m.id, _flat(rest)))
        for r in m.rows:
            if r.kind[0] == "adj":
                out.append("number %d %s %s adj %s %d %s adjustment%s  # %s" % (
                    m.id, r.key, "?" if r.value is None else r.value, r.kind[1], r.kind[2],
                    ",".join(r.words) if r.words else "-",
                    " shared %d" % r.shared if r.shared > 1 else "", _flat(r.comment)))
            else:
                out.append("number %d %s %s %s %s %s%s  # %s" % (
                    m.id, r.key, "?" if r.value is None else r.value, fmt_kind(r.kind),
                    ",".join(r.words) if r.words else "-", r.klass,
                    " shared %d" % r.shared if r.shared > 1 else "", _flat(r.comment)))
    return "\n".join(out) + "\n"
