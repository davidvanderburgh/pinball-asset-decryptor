#!/usr/bin/env python3
"""s3port.py - draft a Spike 3 (64-bit ARM) PORT from a proven Spike 2 (32-bit ARM) port of the
same title (PAD-1271).

    s3port.py <Spike 2 game ELF> <Spike 2 port> <Spike 3 game ELF> -o <draft port> [--report]

A port tells the mode runtime where a game's functions and globals are in one build (MODE_SDK.md,
"Ports"). port_tool.py drafts one from another build of the SAME architecture by instruction
signatures; across architectures no instruction carries over, so this matches FUNCTIONS instead,
the way a binary differ does, and needs no symbols (both programs are stripped):

  anchors   a C++ class's vtable is named by its typeinfo string, and the same source puts the same
            virtual functions in the same slots on both builds: slot n of a class's vtable on Spike 2
            is slot n of that class's vtable on Spike 3 (classes whose vtables differ in length are
            skipped). A string named by exactly one function on each side pairs those two.
  growth    from every pair, the unpaired callees and callers of the two functions are candidates for
            each other, scored on what they share: strings, library calls (by imported name), callees
            and callers already paired, and size. A candidate is taken only when it is the best for
            its function by a margin AND that function is the best for it (mutual), round after round
            until nothing new is found.
  globals   a port `data` address is the global every reference function that loads it maps to: the
            paired Spike 3 functions' globals are counted, and the one at least two of them load, by
            a clear margin, is taken. Spike 3 reaches its globals through the GOT (adrp + ldr of the
            slot), resolved here through the program's RELATIVE relocations.

What differs on Spike 3, measured on Star Wars ELG 1.10 (docs/plans/spike3_modes.md):
  - scores are 64-bit: the reference's 32-bit score_add32 / scores32 is the 64-bit score_add /
    scores on the target when the paired function indexes the table by 8 (`ldr x, [.., lsl #3]`);
  - switch ids are one lower: a switch id is its record's place in the program's own device table
    plus one, so `switch` lines are renumbered BY NAME from that table;
  - structs hold 8-byte pointers: a `value` is a struct offset or a count measured on a 32-bit
    build, so none is carried except those this file names as proven (VALUES_PROVEN); the rest are
    written as comments for a person to measure;
  - a function the reference port names mid-way (a `site` that is not a function's start: ball_end,
    the show and challenge sites) is not placed; ball_end becomes the bus event (value ball_end_event)
    when the reference names `event ball_end`.
Every site placed is written with the two instruction words read from the target, which the runtime
checks before hooking. Exit status 1 when a CORE entry (MODE_SDK.md, the gate) is missing.
"""
import argparse
import bisect
import math
import os
import re
import struct
import sys
from collections import Counter, defaultdict

# Port values that hold on Spike 3 as they are on Spike 2 (each read in the target's own code on Star Wars
# ELG 1.10): the mode mask's busy bits are the immediate score_add tests (`mov w4, #0x210; tst w4, w1`).
VALUES_PROVEN = ("mode_mask_busy",)
# Sites and globals the 64-bit runtime has been run with on Spike 3 (a mode started, scored and ended on Star Wars
# ELG 1.10 in the emulator). Every other site is still PLACED, and written as a comment with its address: the
# runtime features that use one read the game's structs at 32-bit offsets, and the first of them to arm with the
# rest of the draft (after display priority) stopped the game with a segfault. A feature's sites are carried when
# that feature is made 64-bit and proven.
SITES_PROVEN = ("tick", "hook_dispatch", "score_add", "agent_header", "agent_begin")      # + every switch_hit*
DATA_PROVEN = ("cur_player", "scores", "score_mult", "mode_mask")
# the gate's core (pad_mode_runtime.c core_of_port): any one of each group
CORE = (("tick",), ("shot_dispatch", "switch_hit", "switch_edge"), ("ball_end", "hook_dispatch"),
        ("score_add", "score_add32"))
CORE_DATA = (("cur_player",), ("scores", "scores32"))


def sext(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


# ---- the ELF, either width --------------------------------------------------------------------------------
class Elf:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.b = b = f.read()
        if b[:4] != b"\x7fELF":
            raise ValueError("%s is not a program (no ELF header)" % path)
        self.a64 = b[4] == 2
        if self.a64:
            shoff, = struct.unpack_from("<Q", b, 0x28)
            phoff, = struct.unpack_from("<Q", b, 0x20)
            phsz, phn, shsz, shn, shstr = struct.unpack_from("<HHHHH", b, 0x36)
        else:
            phoff, shoff = struct.unpack_from("<II", b, 0x1c)
            phsz, phn, shsz, shn, shstr = struct.unpack_from("<HHHHH", b, 0x2a)
        self.segs = []
        for i in range(phn):
            if self.a64:
                t, fl, off, va, pa, fs, ms, al = struct.unpack_from("<IIQQQQQQ", b, phoff + i * phsz)
            else:
                t, off, va, pa, fs, ms, fl, al = struct.unpack_from("<IIIIIIII", b, phoff + i * phsz)
            if t == 1:
                self.segs.append((va, off, fs, fl))
        raw = []
        for i in range(shn):
            if self.a64:
                nm, t, fl, a, off, sz, ln, inf, al, es = struct.unpack_from("<IIQQQQIIQQ", b, shoff + i * shsz)
            else:
                nm, t, fl, a, off, sz, ln, inf, al, es = struct.unpack_from("<IIIIIIIIII", b, shoff + i * shsz)
            raw.append((nm, t, a, off, sz, ln, es))
        so = raw[shstr][3]
        self.sec = {}
        for nm, t, a, off, sz, ln, es in raw:
            e = b.find(b"\0", so + nm)
            self.sec[b[so + nm:e].decode()] = (a, off, sz, t, ln, es)
        self.tva, self.toff, self.tsz = self.sec[".text"][0], self.sec[".text"][1], self.sec[".text"][2]
        self.words = struct.unpack_from("<%dI" % (self.tsz // 4), b, self.toff)
        self._relocs()
        self._plt()

    def _relocs(self):
        """ptr: an address -> the address stored there (a64: RELATIVE addends; arm: every non-zero data word),
        holes: places a symbol reloc fills at load time (an import's address: a vtable's pure virtual)."""
        self.ptr, self.holes = {}, set()
        if self.a64:
            a, off, sz, t, ln, es = self.sec[".rela.dyn"]
            for k in range(0, sz, 24):
                o, info, add = struct.unpack_from("<QQq", self.b, off + k)
                if info & 0xFFFFFFFF == 1027:          # R_AARCH64_RELATIVE
                    self.ptr[o] = add
                else:
                    self.holes.add(o)
        else:
            for nm in (".data.rel.ro", ".data", ".rodata", ".init_array"):
                if nm not in self.sec or self.sec[nm][3] == 8:      # SHT_NOBITS
                    continue
                a, off, sz = self.sec[nm][:3]
                for k, v in enumerate(struct.unpack_from("<%dI" % (sz // 4), self.b, off)):
                    if v:
                        self.ptr[a + 4 * k] = v
            if ".rel.dyn" in self.sec:
                a, off, sz = self.sec[".rel.dyn"][:3]
                for k in range(0, sz, 8):
                    self.holes.add(struct.unpack_from("<I", self.b, off + k)[0])

    def _plt(self):
        """plt: a PLT stub's address -> the imported name"""
        self.plt = {}
        rel = ".rela.plt" if self.a64 else ".rel.plt"
        if rel not in self.sec or ".plt" not in self.sec:
            return
        dsym = self.sec[".dynsym"]
        dstr = self.sec[".dynstr"][1]
        a, off, sz = self.sec[rel][:3]
        step, first = (16, 32) if self.a64 else (12, 20)
        es = 24 if self.a64 else 8
        for i, k in enumerate(range(0, sz, es)):
            if self.a64:
                o, info, add = struct.unpack_from("<QQq", self.b, off + k)
                si = info >> 32
                nm, = struct.unpack_from("<I", self.b, dsym[1] + si * 24)
            else:
                o, info = struct.unpack_from("<II", self.b, off + k)
                si = info >> 8
                nm, = struct.unpack_from("<I", self.b, dsym[1] + si * 16)
            e = self.b.find(b"\0", dstr + nm)
            self.plt[self.sec[".plt"][0] + first + i * step] = self.b[dstr + nm:e].decode().split("@")[0]

    def off(self, va):
        for s, o, fs, fl in self.segs:
            if s <= va < s + fs:
                return o + va - s
        return None

    def u32(self, va):
        o = self.off(va)
        return None if o is None else struct.unpack_from("<I", self.b, o)[0]

    def cstr(self, va, cap=200):
        o = self.off(va)
        if o is None:
            return None
        e = self.b.find(b"\0", o, o + cap)
        if e - o < 4:
            return None
        s = self.b[o:e]
        return s.decode() if all(32 <= c < 127 or c in (9, 10) for c in s) else None

    def in_sec(self, va, *names):
        for n in names:
            s = self.sec.get(n)
            if s and s[0] <= va < s[0] + s[2]:
                return True
        return False

    def in_text(self, va):
        return self.tva <= va < self.tva + self.tsz

    def is_data(self, va):
        return self.in_sec(va, ".data", ".bss", ".data.rel.ro")


# ---- one pass over the code: calls, the addresses each instruction makes, function starts -----------------
def scan(e):
    w = e.words
    n = len(w)
    calls, refs, starts, btgt = {}, defaultdict(list), set(), set()
    term = []
    if e.a64:
        got = e.sec.get(".got", (0, 0, 0))
        regs = {}
        for i in range(n):
            x = w[i]
            pc = e.tva + 4 * i
            if (x & 0xFC000000) == 0x94000000:                       # bl
                calls[i] = pc + 4 * sext(x & 0x3FFFFFF, 26)
                for k in [k for k in regs if k <= 18]:
                    del regs[k]
                continue
            if (x & 0xFC000000) == 0x14000000:                       # b
                btgt.add(pc + 4 * sext(x & 0x3FFFFFF, 26))
                term.append(i)
                regs = {}
                continue
            if (x & 0xFF000010) == 0x54000000 or (x & 0x7E000000) == 0x34000000:   # b.cond, cbz/cbnz
                btgt.add(pc + 4 * sext((x >> 5) & 0x7FFFF, 19))
                continue
            if (x & 0x7E000000) == 0x36000000:                       # tbz/tbnz
                btgt.add(pc + 4 * sext((x >> 5) & 0x3FFF, 14))
                continue
            if x == 0xD65F03C0 or (x & 0xFFFFFC1F) == 0xD61F0000:    # ret, br
                term.append(i)
                regs = {}
                continue
            if (x & 0x9F000000) == 0x90000000:                       # adrp
                regs[x & 31] = ("p", (pc & ~0xFFF) + (sext((((x >> 5) & 0x7FFFF) << 2) | ((x >> 29) & 3), 21) << 12))
                continue
            if (x & 0xFF800000) == 0x91000000:                       # add xd, xn, #imm
                rn, rd = (x >> 5) & 31, x & 31
                if rn in regs:
                    a = regs[rn][1] + (((x >> 10) & 0xFFF) << (12 if x & 0x400000 else 0))
                    refs[i].append(a)
                    regs[rd] = ("s", a)
                else:
                    regs.pop(rd, None)
                continue
            if (x & 0x3B000000) == 0x39000000:                       # ldr/str, unsigned offset
                rn, rt = (x >> 5) & 31, x & 31
                simd, load = (x >> 26) & 1, (x >> 22) & 1
                size = 4 if simd and (x >> 23) & 1 else x >> 30
                if rn in regs:
                    a = regs[rn][1] + (((x >> 10) & 0xFFF) << size)
                    if regs[rn][0] == "p" and got[0] <= a < got[0] + got[2] and a in e.ptr and load and not simd:
                        regs[rt] = ("s", e.ptr[a])                   # a GOT slot: the global's address
                        refs[i].append(e.ptr[a])
                        continue
                    refs[i].append(a)
                if load and not simd:
                    regs.pop(rt, None)
                continue
            if (x & 0x7F800000) == 0x72800000:                       # movk: a 32-bit constant with its movz
                for j in range(i - 1, max(i - 12, -1), -1):
                    y = w[j]
                    if (y & 0x7F800000) == 0x52800000 and (y & 31) == (x & 31):
                        refs[i].append((((y >> 5) & 0xFFFF) << (16 * ((y >> 21) & 3))) |
                                       (((x >> 5) & 0xFFFF) << (16 * ((x >> 21) & 3))))
                        break
                continue
            if ((x >> 25) & 0xF) in (0x4, 0x5, 0x6, 0x8, 0x9, 0xC, 0xD, 0xE):
                regs.pop(x & 31, None)
        for o, a in e.ptr.items():
            if e.in_text(a):
                starts.add(a)
        pad = lambda x: x in (0xD503201F, 0)
    else:
        for i in range(n):
            x = w[i]
            pc = e.tva + 4 * i
            c = x >> 28
            if (x & 0x0F000000) == 0x0B000000 and c != 0xF:          # bl
                calls[i] = pc + 8 + 4 * sext(x & 0xFFFFFF, 24)
            elif (x & 0x0F000000) == 0x0A000000 and c != 0xF:        # b
                btgt.add(pc + 8 + 4 * sext(x & 0xFFFFFF, 24))
                if c == 0xE:
                    term.append(i)
            elif c == 0xE and (x == 0xE12FFF1E or (x & 0x0FFF8000) == 0x08BD8000):   # bx lr, pop {.., pc}
                term.append(i)
            elif (x & 0x0F7F0000) == 0x051F0000:                     # ldr rX, [pc, #]
                a = pc + 8 + ((x & 0xFFF) if x & 0x800000 else -(x & 0xFFF))
                v = e.u32(a)
                if v is not None:
                    refs[i].append(v)
            elif (x & 0x0FF00000) == 0x03400000:                     # movt: with its movw
                rd = (x >> 12) & 15
                for j in range(i - 1, max(i - 12, -1), -1):
                    y = w[j]
                    if (y & 0x0FF00000) == 0x03000000 and ((y >> 12) & 15) == rd:
                        refs[i].append(((((x >> 4) & 0xF000) | (x & 0xFFF)) << 16) | ((y >> 4) & 0xF000) | (y & 0xFFF))
                        break
            elif (x & 0x0FFF0000) == 0x028F0000:                     # add rX, pc, #
                rot = ((x >> 8) & 15) * 2
                v = x & 0xFF
                refs[i].append(pc + 8 + (((v >> rot) | (v << (32 - rot))) & 0xFFFFFFFF))
        for o, a in e.ptr.items():
            if e.in_text(a) and not a & 3:
                starts.add(a)
        pad = lambda x: x in (0, 0xE320F000, 0xE1A00000)
    starts.update(t for t in calls.values() if e.in_text(t))
    for i in term:                                                  # after a return: the next function
        j = i + 1
        while j < n and pad(w[j]):
            j += 1
        if j < n:
            a = e.tva + 4 * j
            if a not in btgt and (e.a64 or (w[j] >> 28) in (0xE, 0xF)):
                starts.add(a)
    e.calls, e.refs, e.starts = calls, refs, sorted(s for s in starts if e.in_text(s))
    return e


def func_of(e, va):
    i = bisect.bisect_right(e.starts, va) - 1
    return e.starts[i] if i >= 0 else None


def features(e):
    """per function: strs (set), callees (list), imports (Counter), datas (ordered), size (instructions)"""
    F = {s: {"strs": set(), "callees": [], "imports": Counter(), "datas": [], "size": 0} for s in e.starts}
    for k, s in enumerate(e.starts):
        F[s]["size"] = ((e.starts[k + 1] - s) // 4) if k + 1 < len(e.starts) else 100
    for i in sorted(set(e.refs) | set(e.calls)):
        f = func_of(e, e.tva + 4 * i)
        if f is None:
            continue
        d = F[f]
        if i in e.calls:
            c = e.calls[i]
            if c in e.plt:
                d["imports"][e.plt[c]] += 1
            else:
                d["callees"].append(c)
        for v in e.refs.get(i, ()):
            if e.in_sec(v, ".rodata"):
                s = e.cstr(v)
                if s:
                    d["strs"].add(s)
            elif e.is_data(v):
                d["datas"].append(v)
    callers = defaultdict(set)
    for f, d in F.items():
        for c in set(d["callees"]):
            callers[c].add(f)
    for f, d in F.items():
        d["callers"] = callers.get(f, set())
    e.F = F
    return F


def vtables(e):
    """{(class name, n): [slot targets]} - the n-th vtable naming that class's typeinfo"""
    P = 8 if e.a64 else 4
    mang = re.compile(r"^(N|St)?[0-9]+[A-Za-z_][A-Za-z0-9_]*$")
    ti = {}
    for a, v in e.ptr.items():
        if e.in_sec(v, ".rodata") and ((a - P) in e.ptr or (a - P) in e.holes):
            s = e.cstr(v)
            if s and mang.match(s):
                ti[a - P] = s
    out, cnt = {}, Counter()
    for a in sorted(e.ptr):
        v = e.ptr[a]
        if v in ti and (a - P) not in e.ptr:
            slots, q = [], a + P
            while True:
                if q in e.ptr and e.in_text(e.ptr[q]):
                    slots.append(e.ptr[q])
                elif q in e.holes and q not in e.ptr:
                    slots.append(None)
                else:
                    break
                q += P
            if slots:
                out[(ti[v], cnt[ti[v]])] = slots
                cnt[ti[v]] += 1
    return out


# ---- matching ------------------------------------------------------------------------------------------
class Matcher:
    def __init__(self, ref, tgt):
        self.r, self.t = ref, tgt
        self.R, self.T = features(ref), features(tgt)
        self.sidf = Counter(s for d in self.T.values() for s in d["strs"])
        self.m = {}
        self.how = {}

    def score(self, a, b):
        ra, tb = self.R[a], self.T[b]
        m = self.m
        sa, sb = ra["strs"], tb["strs"]
        sc = 0.0
        if sa or sb:
            inter = sa & sb
            if not inter and sa and sb:
                return -9.0
            if bool(sa) != bool(sb):
                if len(sa) + len(sb) >= 2:
                    return -9.0
                sc -= 1
            sc += sum(2.0 / self.sidf[s] for s in inter) - 0.5 * len(sa ^ sb)
        ia, ib = ra["imports"], tb["imports"]
        sc += 0.5 * sum((ia & ib).values()) - 0.3 * (sum((ia - ib).values()) + sum((ib - ia).values()))
        cb = set(tb["callees"])
        for c in set(ra["callees"]):
            if c in m:
                sc += 1.0 if m[c] in cb else -0.7
        sc += sum(1.0 for c in ra["callers"] if c in m and m[c] in tb["callers"])
        q = math.log((tb["size"] + 4) / (ra["size"] + 4))
        sc -= 1.5 * max(0.0, abs(q) - 0.5)
        na, nb = len(ra["callees"]) + sum(ia.values()), len(tb["callees"]) + sum(ib.values())
        sc -= 0.15 * max(0, abs(na - nb) - 1)
        return sc

    def seed(self):
        rv, tv = vtables(self.r), vtables(self.t)
        vv = defaultdict(Counter)
        for k, sl in rv.items():
            if k in tv and len(tv[k]) == len(sl):
                for a, b in zip(sl, tv[k]):
                    if a and b:
                        vv[a][b] += 1
        one = {a: next(iter(c)) for a, c in vv.items() if len(c) == 1}
        tc = Counter(one.values())
        for a, b in one.items():
            if tc[b] == 1 and a in self.R and b in self.T:
                self.m[a] = b
                self.how[a] = "vtable slot"
        rs, ts = defaultdict(set), defaultdict(set)
        for f, d in self.R.items():
            for s in d["strs"]:
                rs[s].add(f)
        for f, d in self.T.items():
            for s in d["strs"]:
                ts[s].add(f)
        cand = defaultdict(set)
        for s, fr in rs.items():
            if len(fr) == 1 and len(ts.get(s, ())) == 1:
                cand[next(iter(fr))].add(next(iter(ts[s])))
        tc = Counter(next(iter(bs)) for bs in cand.values() if len(bs) == 1)
        used = set(self.m.values())
        for a, bs in cand.items():
            if len(bs) == 1:
                b = next(iter(bs))
                if tc[b] == 1 and a not in self.m and b not in used:
                    self.m[a] = b
                    self.how[a] = "a string only it names"
                    used.add(b)
        self.vt = (len(rv), len(tv))

    def grow(self, thr=2.0, margin=1.0, rounds=40):
        for _ in range(rounds):
            rev = set(self.m.values())
            C = defaultdict(set)
            for a, b in self.m.items():
                for ua, ub in ((set(self.R[a]["callees"]), set(self.T[b]["callees"])),
                               (self.R[a]["callers"], self.T[b]["callers"])):
                    ua = [c for c in ua if c not in self.m and c in self.R]
                    ub = [c for c in ub if c not in rev and c in self.T]
                    if ua and ub and len(ua) * len(ub) <= 400:
                        for x in ua:
                            C[x].update(ub)
            best_b = defaultdict(list)
            for a, bs in C.items():
                sc = sorted(((self.score(a, b), b) for b in bs), reverse=True)
                s1, b1 = sc[0]
                s2 = sc[1][0] if len(sc) > 1 else -99
                if s1 >= thr and s1 - s2 >= margin:
                    best_b[b1].append((s1, a))
            new = 0
            for b, lst in best_b.items():
                lst.sort(reverse=True)
                if len(lst) > 1 and lst[0][0] - lst[1][0] < margin:
                    continue
                self.m[lst[0][1]] = b
                self.how[lst[0][1]] = "its calls and callers (score %.1f)" % lst[0][0]
                new += 1
            if not new:
                break
        return self.m

    def data(self, A):
        """(target address, agreeing, of) for the reference global A, or (None, ...)"""
        fr = [f for f, d in self.R.items() if A in d["datas"]]
        fm = [f for f in fr if f in self.m]
        c = Counter()
        for f in fm:
            for x in set(self.T[self.m[f]]["datas"]):
                c[x] += 1
        top = c.most_common(2)
        if top and top[0][1] >= 2 and (len(top) < 2 or top[0][1] >= 1.5 * top[1][1]):
            return top[0][0], top[0][1], len(fm)
        return None, (top[0][1] if top else 0), len(fm)


# ---- what Spike 3 changed ------------------------------------------------------------------------------
def scores_are_64(t, f, table):
    """1 when the function at f loads `table` and indexes something by 8 (ldr x, [xn, xm, lsl #3])"""
    if f is None or table is None:
        return False
    i0 = (f - t.tva) // 4
    n = t.F.get(f, {}).get("size", 0)
    if table not in t.F.get(f, {}).get("datas", []) and not any(table in t.refs.get(i, ()) for i in range(i0, i0 + n)):
        return False
    return any((t.words[i] & 0xFFE00C00) == 0xF8600800 and (t.words[i] >> 12) & 1 for i in range(i0, i0 + n))


def switch_ids(t):
    """{device name (upper case): switch id} from the target's own device table (0x50-byte records, walked out
    from the one named TROUGH 1): id = the record's rank among the table's switches, from 1 - measured on the rig
    (PAD-1271: every switch a press reached the mode with matched it)."""
    def rec(a):
        n = t.ptr.get(a)
        o = t.off(n) if n else None
        if o is None:
            return None
        name = t.b[o:t.b.find(b"\0", o, o + 80)].decode("latin1")     # short names too ("GI", "TILT")
        if not name or len(name) > 40 or not name.isprintable():
            return None
        o = t.off(a + 0x20)
        if o is None:
            return None
        w, = struct.unpack_from("<Q", t.b, o)
        g, idx, cls = w & 0xFFFF, (w >> 16) & 0xFFFF, (w >> 32) & 0xFFFF
        return (name, cls) if 1 <= g <= 64 and idx < 512 and cls in (1, 2, 3, 5) else None
    m = re.search(rb"\0TROUGH 1\0", t.b)
    if not m:
        return {}
    o = m.start() + 1
    sva = next((s + o - so for s, so, fs, fl in t.segs if so <= o < so + fs), None)
    for a, v in t.ptr.items():
        r = rec(a) if v == sva else None
        if r and r[1] == 1:
            # the table runs on through every class (Star Wars ELG 1.10: 16 QR scanner inputs, the coils and lights,
            # then the rest of the switches); a switch's id is its rank among the table's switches
            lo = a
            while rec(lo - 0x50):
                lo -= 0x50
            out, k, n = {}, 0, 0
            while rec(lo + 0x50 * k):
                r = rec(lo + 0x50 * k)
                if r[1] == 1:
                    n += 1
                    out.setdefault(r[0].upper(), n)
                k += 1
            return out
    return {}


# ---- the port ------------------------------------------------------------------------------------------
def read_port(path):
    lines = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            s = raw.rstrip("\n")
            t = s.split()
            lines.append((t[0] if t and not s.lstrip().startswith("#") else "", t, s))
    return lines


def site_ok(t, va):
    """'' when the target's first instruction at va can be hooked, else why not"""
    w = t.u32(va)
    if w is None:
        return "not in the program"
    if (w & 0xFC000000) == 0x94000000:
        return "opens with a bl (the hook layer cannot move one)"
    if (w & 0x3B000000) == 0x18000000:
        return "opens with a literal load (the hook layer cannot move one)"
    return ""


def draft(ref, rport, tgt, game=None, version=None):
    scan(ref)
    scan(tgt)
    M = Matcher(ref, tgt)
    M.seed()
    seeded = len(M.m)
    M.grow()
    lines = read_port(rport)
    g = game or next((t[1] for k, t, s in lines if k == "game"), "?")
    v = version or next((t[1] for k, t, s in lines if k == "version"), "?")
    head = ["# %s %s - Spike 3 (64-bit ARM): drafted by s3port.py (PAD-1271) from the Spike 2 port %s." % (g, v, os.path.basename(rport)),
            "# Functions matched across the two builds: %d of %d reference functions (%d anchored by vtable slots and "
            "strings, the rest grown through calls)." % (len(M.m), len(M.R), seeded),
            "# Written: the core and the globals the 64-bit runtime has run with (SITES_PROVEN, DATA_PROVEN); every other",
            "# entry placed is a comment with its address, for when its runtime feature is made 64-bit.",
            "", "game           %s" % g, "version        %s" % v, ""]
    body, missing, placed, later = [], [], {}, []
    data_lines = {t[1]: int(t[2], 16) for k, t, s in lines if k == "data" and len(t) >= 3}
    tdata = {}
    for name, A in data_lines.items():
        tdata[name] = M.data(A)
    # sites
    body.append("# ---- functions: site <name> <address> <first two instruction words> ----")
    for k, t, s in lines:
        if k != "site" or len(t) < 3:
            continue
        name, a = t[1], int(t[2], 16)
        f = func_of(ref, a)
        if f != a:
            body.append("# site %-16s NOT PLACED: mid-way into a function on Spike 2 (0x%x + 0x%x)" % (name, f or 0, a - (f or 0)))
            missing.append(name)
            continue
        if a in ref.plt or a not in M.m:
            body.append("# site %-16s NOT PLACED: %s" % (name, "a library call" if a in ref.plt else "no counterpart found"))
            missing.append(name)
            continue
        b = M.m[a]
        why = site_ok(tgt, b)
        if why:
            body.append("# site %-16s NOT PLACED: 0x%08x %s" % (name, b, why))
            missing.append(name)
            continue
        out = name
        if name == "score_add32" and scores_are_64(tgt, b, tdata.get("scores32", (None,))[0]):
            out = "score_add"
            body.append("#   score_add: Spike 2's score_add32; the Spike 3 build adds 64-bit points into u64 scores")
        line = "site %-16s 0x%08x 0x%08x 0x%08x" % (out, b, tgt.u32(b), tgt.u32(b + 4))
        if out in SITES_PROVEN or out.startswith("switch_hit"):
            body.append("#   %s: %s" % (out, M.how.get(a, "matched")))
            body.append(line)
            placed[out] = b
        else:
            body.append("# not carried yet (its feature is 32-bit): " + line)
            later.append(out)
    # data
    body += ["", "# ---- globals: data <name> <address> ----"]
    for name, A in data_lines.items():
        b, agree, of = tdata[name]
        out = "scores" if name == "scores32" and "score_add" in placed else name
        if b is None:
            body.append("# data %-22s NOT PLACED: %d of %d paired functions agree" % (name, agree, of))
            continue
        line = "data %-22s 0x%08x   # %d of %d paired functions that load it" % (out, b, agree, of)
        if out in DATA_PROVEN:
            body.append(line)
            placed["data:" + out] = b
        else:
            body.append("# not carried yet: " + line)
    # values, events
    body += ["", "# ---- values: only those proven on Spike 3; a struct offset or a count is a 32-bit build's ----"]
    events = [(t, s) for k, t, s in lines if k == "event"]
    for k, t, s in lines:
        if k == "value":
            body.append(s if t[1] in VALUES_PROVEN else "# not carried (64-bit layout, measure it): " + s.strip())
    if "ball_end" not in placed and any(t[1] == "ball_end" for t, s in events) and "hook_dispatch" in placed:
        eid = next(t[2] for t, s in events if t[1] == "ball_end")
        body.append("value ball_end_event %s    # the end of a ball, from the bus (no ball_end site on Spike 3)" % eid)
        placed["ball_end_event"] = eid
    body += ["", "# ---- events: the framework's bus ids (the dispatch's range is the same on both builds) ----"]
    body += [s for t, s in events]
    # switches
    ids = switch_ids(tgt)
    sw = [(t, s) for k, t, s in lines if k == "switch"]
    if sw:
        body += ["", "# ---- switches: renumbered by name from the Spike 3 program's own device table ----"]
        for t, s in sw:
            m = re.match(r"\s*switch\s+(\d+)\s+(\S+)\s+(.*)$", s)
            nm = m.group(3).strip()
            nid = ids.get(nm.upper())
            if nid is None:
                body.append("# switch NOT PLACED: no device named %r on Spike 3 (%s)" % (nm, s.strip()))
            else:
                body.append("switch %-4d %-18s %s" % (nid, m.group(2), nm))
    tx = [s for k, t, s in lines if k == "text" and len(t) > 1 and t[1].startswith("example_")]
    if tx:
        body += ["", "# ---- text ----"] + tx
    rest = Counter(k for k, t, s in lines if k in ("lamp", "scene", "callout", "shot") or (k == "text" and not t[1].startswith("example_")))
    if rest:
        body += ["", "# not carried (to measure on Spike 3): " + ", ".join("%d %s" % (n, k) for k, n in sorted(rest.items()))]
    core_missing = [grp for grp in CORE if not any(n in placed for n in grp) and not
                    (grp == ("ball_end", "hook_dispatch") and "ball_end_event" in placed)]
    core_missing += [grp for grp in CORE_DATA if not any("data:" + n in placed for n in grp)]
    return "\n".join(head + body) + "\n", M, core_missing, missing + later


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ref_elf")
    ap.add_argument("ref_port")
    ap.add_argument("target_elf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--game")
    ap.add_argument("--version")
    a = ap.parse_args(argv)
    ref, tgt = Elf(a.ref_elf), Elf(a.target_elf)
    if ref.a64 or not tgt.a64:
        print("s3port.py: the reference must be a Spike 2 (32-bit) program and the target a Spike 3 (64-bit) one",
              file=sys.stderr)
        return 2
    text, M, core_missing, missing = draft(ref, a.ref_port, tgt, a.game, a.version)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("%s: %d functions matched; %d port site(s) not written%s" % (a.out, len(M.m), len(missing),
          (": " + ", ".join(missing)) if missing else ""))
    if core_missing:
        print("CORE MISSING: %s" % "; ".join("/".join(g) for g in core_missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
