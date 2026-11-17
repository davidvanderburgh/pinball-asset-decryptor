#!/usr/bin/env python3
"""s3port.py - draft a Spike 3 (64-bit ARM) PORT from a proven Spike 2 (32-bit ARM) port of the
same title (PAD-1271), or from another Spike 3 title's proven port (PAD-1287).

    s3port.py <Spike 2 game ELF> <Spike 2 port> <Spike 3 game ELF> -o <draft port>
    s3port.py <Spike 3 game ELF> <its Spike 3 port> <Spike 3 game ELF> -o <draft port> --game G --version V

From a Spike 3 reference (a title with no Spike 2 build of its own: draft_spike3, below) the functions are paired as
here and then LINED UP instruction by instruction, every site, global, offset and bus id read at the lined-up
instruction; the switch lines come from the target's own device table and the reference game's own content is left
out. Walking Dead Remastered LE 0.92 from Star Wars ELG 1.10: docs/plans/spike3_modes.md, "PAD-1287".

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
SITES_PROVEN = ("tick", "hook_dispatch", "score_add", "agent_header", "agent_begin",      # + every switch_hit*
                # PAD-1282: the game's callouts and sounds (a mode played both on Star Wars ELG 1.10's Spike 3 rig)
                "callout", "callout_nth", "sound_play", "sound_nth", "sound_active", "sound_stop",
                "sound_worker", "sound_resolve", "sound_lookup",
                # PAD-1283: the lamp layer and the game's own light shows (a mode's named inserts held and let go, and
                # the game's shows played as a process of the runtime's and stopped, on Star Wars ELG 1.10's Spike 3 rig)
                "lamp_group", "show_priority", "show_start", "event_post_replacing", "event_cancel",
                "proc_exists", "proc_create")
DATA_PROVEN = ("cur_player", "scores", "score_mult", "mode_mask",
               "sound_channels", "sound_requests", "sound_request_count",
               "event_head", "event_current", "lamp_layers", "light_count")
# PAD-1283: values light_engine() reads but the runtime has no use for (it checks them, the port need not carry them)
LIGHT_VALUES_UNUSED = ("lamp_group_owner", "proc_record_size")
# PAD-1282: the sound engine's 64-bit layout (Star Wars ELG 1.10, read in its sound_active / sound_stop / worker:
# Spike 2's channel with 8-byte pointers - 288 bytes, the request u16 at +272, the voice bits at +276, the bus
# mask at +277, eight voice pointers at +144; a voice's u16 volume step at +56). The engine is the same code on
# every Spike 3 title; sound_engine() checks the request and voice offsets against the program's own code.
SOUND_VALUES = (("sound_channel_count", 8), ("sound_channel_size", 288), ("sound_channel_request", 272),
                ("sound_channel_voices", 276), ("sound_channel_bus", 277), ("sound_channel_voice_ptrs", 144),
                ("sound_voice_volume", 56))
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


def device_records(t):
    """[(name, I/O group, index, class)] of the target's own device table (0x50-byte records, walked out from the one
    named TROUGH 1), in its order: class 1 a switch, 2 a coil, 3 a lamp"""
    def rec(a):
        n = t.ptr.get(a)
        o = t.off(n) if n else None
        if o is None:
            return None
        raw = t.b[o:t.b.find(b"\0", o, o + 80)]                       # short names too ("GI", "TILT")
        try:
            # PAD-1289: the names are UTF-8. Pokemon LE's "POKÉ BALL SPOT" read as Latin-1 has an unprintable \x89,
            # which ended the walk there and lost the 16 QR scanner switches before it: every switch id 16 low
            name = raw.decode("utf-8")
        except UnicodeDecodeError:
            name = raw.decode("latin1")
        if not name or len(name) > 40 or not name.isprintable():
            return None
        o = t.off(a + 0x20)
        if o is None:
            return None
        w, = struct.unpack_from("<Q", t.b, o)
        g, idx, cls = w & 0xFFFF, (w >> 16) & 0xFFFF, (w >> 32) & 0xFFFF
        return (name, g, idx, cls) if 1 <= g <= 64 and idx < 512 and cls in (1, 2, 3, 5) else None
    m = re.search(rb"\0TROUGH 1\0", t.b)
    if not m:
        return []
    o = m.start() + 1
    sva = next((s + o - so for s, so, fs, fl in t.segs if so <= o < so + fs), None)
    for a, v in t.ptr.items():
        r = rec(a) if v == sva else None
        if r and r[3] == 1:
            # the table runs on through every class (Star Wars ELG 1.10: 16 QR scanner inputs, the coils and lights,
            # then the rest of the switches)
            lo = a
            while rec(lo - 0x50):
                lo -= 0x50
            out, k = [], 0
            while rec(lo + 0x50 * k):
                out.append(rec(lo + 0x50 * k))
                k += 1
            return out
    return []


def switch_ids(t):
    """{device name (upper case): switch id} from the target's own device table: id = the record's rank among the
    table's switches, from 1 - measured on the rig (PAD-1271: every switch a press reached the mode with matched it)."""
    out, n = {}, 0
    for name, g, idx, cls in device_records(t):
        if cls == 1:
            n += 1
            out.setdefault(name.upper(), n)
    return out


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


# ---- PAD-1282: the sound engine, read off the 64-bit program from its callout ------------------------------
def _window(t, va, cap=1200):
    """(va, word) from va to the next function start (or cap words)"""
    i = bisect.bisect_right(t.starts, va)
    end = t.starts[i] if i < len(t.starts) else va + 4 * cap
    for a in range(va, min(end, va + 4 * cap), 4):
        w = t.u32(a)
        if w is None:
            return
        yield a, w


def _bl(va, w):
    return va + 4 * sext(w & 0x3FFFFFF, 26) if (w & 0xFC000000) == 0x94000000 else None


def audit_add_a64(e):
    """PAD-1327: ``[(callee, distinct ids)]`` best first - the callees handed `movz w0, #id` with `movz w1, #1` in the
    four instructions before the bl (stock_scan_c.find_audit_add's rule on AArch64). The first is the framework's
    audit add (`site audit_add`: id w0, amount w1): Star Wars ELG 1.10 hands its 132 ids, the next callee 12."""
    from collections import defaultdict
    ids, w = defaultdict(set), e.words

    def movz(x, reg):
        return (x >> 5) & 0xFFFF if (x & 0xFF80001F) == (0x52800000 | reg) else None
    for k in range(4, len(w)):
        if (w[k] & 0xFC000000) != 0x94000000:
            continue
        a0 = a1 = None
        for j in range(k - 1, k - 5, -1):
            a0 = movz(w[j], 0) if a0 is None else a0
            a1 = movz(w[j], 1) if a1 is None else a1
        if a0 is not None and a1 == 1:
            ids[_bl(e.tva + 4 * k, w[k])].add(a0)
    return sorted(((t, len(s)) for t, s in ids.items()), key=lambda kv: -kv[1])


def _adrp(va, w):
    """adrp xd, page -> (d, page), else None"""
    if (w & 0x9F000000) != 0x90000000:
        return None
    imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
    return w & 31, (va & ~0xFFF) + (sext(imm, 21) << 12)


def _add_imm(w):
    """add xd, xn, #imm (no shift) -> (d, n, imm), else None"""
    if (w & 0xFFC00000) != 0x91000000:
        return None
    return w & 31, (w >> 5) & 31, (w >> 10) & 0xFFF


def _addrs(t, va, cap=40):
    """the addresses the first `cap` words at va make with adrp / add #imm, in order (one per add)"""
    reg, out = {}, []
    for a, w in list(_window(t, va))[:cap]:
        p = _adrp(a, w)
        if p:
            reg[p[0]] = p[1]
            continue
        ad = _add_imm(w)
        if ad and ad[1] in reg:
            reg[ad[0]] = reg[ad[1]] + ad[2]
            out.append(reg[ad[0]])
    return out


def _got_loads(t, va, cap=60):
    """the pointers the code at va loads from the GOT (adrp; ldr xd, [xd, #off]), as their RELATIVE targets"""
    reg, out = {}, []
    for a, w in list(_window(t, va))[:cap]:
        p = _adrp(a, w)
        if p:
            reg[p[0]] = p[1]
            continue
        if (w & 0xFFC00000) == 0xF9400000 and ((w >> 5) & 31) in reg:      # ldr xt, [xn, #imm*8]
            slot = reg[(w >> 5) & 31] + ((w >> 10) & 0xFFF) * 8
            if slot in t.ptr:
                out.append(t.ptr[slot])
    return out


def _const_ids(e, target):
    """the constant first argument of every call to `target` (mov r0/w0 #imm within the 4 words before)"""
    out = Counter()
    for i, tg in e.calls.items():
        if tg != target:
            continue
        for j in range(i - 1, max(-1, i - 5), -1):
            x = e.words[j]
            if e.a64:
                if (x & 0xFFE0001F) == 0x52800000:                         # movz w0, #imm16
                    out[(x >> 5) & 0xFFFF] += 1
                    break
            elif (x & 0xFFFFF000) == 0xE3A00000:                            # mov r0, #rot imm8
                r, v = ((x >> 8) & 15) * 2, x & 0xFF
                out[((v >> r) | (v << (32 - r))) & 0xFFFFFFFF] += 1
                break
            elif (x & 0xFFF0F000) == 0xE3000000:                            # movw r0, #imm16
                out[((x >> 4) & 0xF000) | (x & 0xFFF)] += 1
                break
    return out


def request_shift(ref, rcallout, tgt, tcallout):
    """(k, hits, of): Spike 3's request id = Spike 2's + k, read from the constant ids both builds' code passes to
    the callout (Star Wars ELG 1.10: +2 - two requests added early in the Spike 3 build's table). k None when no
    shift explains most of them."""
    a, b = _const_ids(ref, rcallout), _const_ids(tgt, tcallout)
    if len(a) < 10 or len(b) < 10:
        return None, 0, len(a)
    k, hits = max(((k, sum(1 for x in a if x + k in b)) for k in range(-16, 17)), key=lambda kh: kh[1])
    return (k if hits * 2 > len(a) else None), hits, len(a)


def sound_engine(t, placed):
    """sites, data and values of the 64-bit sound engine, from the placed callout / sound_active / sound_stop:
    {'site': {name: va}, 'data': {name: va}, 'why': [what could not be read]}"""
    out, why = {"site": {}, "data": {}, "why": []}, []
    callout = placed.get("callout") or placed.get("sound_play")
    if not callout:
        out["why"].append("no callout placed")
        return out
    worker = next((b for a, w in _window(t, callout) for b in [_bl(a, w)] if b), None)
    if not worker:
        out["why"].append("the callout makes no call")
        return out
    out["site"]["sound_worker"] = worker
    words = list(_window(t, worker, 1000))
    callers = Counter(t.calls.values())
    for k, (a, w) in enumerate(words):             # resolve: the worker's call with x1 = a stack slot (its out)
        b = _bl(a, w)
        if b and callers[b] >= 3 and any((x & 0xFFC003FF) == 0x910003E1 for _, x in words[max(0, k - 5):k]):
            out["site"]["sound_resolve"] = b
            break
    look = Counter()                                # lookup: the find that takes the key the bank bits went into
    for i, tg in t.calls.items():
        if i >= 1 and (t.words[i - 1] & 0xFFE0FFFF) == 0xAA008821:       # orr x1, x1, xN, lsl #34
            look[tg] += 1
    if look and look.most_common(1)[0][1] >= 2:
        out["site"]["sound_lookup"] = look.most_common(1)[0][0]
    # the request count (a u64 the worker checks the request against) and the table after it (32-byte records,
    # Stern's .flash on Star Wars ELG 1.10), both through the GOT
    got = _got_loads(t, worker)
    writable = lambda a: any(va <= a < va + fs and fl & 2 for va, off, fs, fl in t.segs)
    for k, cnt in enumerate(got):
        lo, hi = t.u32(cnt), t.u32(cnt + 4)
        if lo is None or hi != 0 or not 1 <= lo < 0x10000:
            continue
        table = next((a for a in got[k + 1:] if a != cnt and writable(a)), None)
        if table is not None and t.u32(table + 32 * (lo - 1) + 28) is not None:
            out["data"]["sound_request_count"], out["data"]["sound_requests"] = cnt, table
        break
    stop, active = placed.get("sound_stop"), placed.get("sound_active")
    if stop and active:
        st, ac = _addrs(t, stop), _addrs(t, active)
        base = st[1] if len(st) >= 2 else None       # adrp + #lo, then + the first channel's offset
        if base is not None and ac and ac[1:2] == [base + 272]:
            out["data"]["sound_channels"] = base
        else:
            why.append("the channel table's request offset is not +272 in sound_active")
    out["why"] = why
    return out


# ---- PAD-1283: lamps and light shows ---------------------------------------------------------------------------
def _ls(w):
    """an unsigned-offset load / store, or ldp / stp -> (kind, t, n, imm, t2): kind 'ldr' / 'str' / 'ldrb' / 'strb' /
    'ldrh' / 'strh' / 'ldp' / 'stp' (64-bit registers for ldr / str / ldp / stp), imm in bytes; else None"""
    for mask, op, kind, scale in ((0xFFC00000, 0xF9400000, "ldr", 8), (0xFFC00000, 0xF9000000, "str", 8),
                                  (0xFFC00000, 0xB9400000, "ldrw", 4), (0xFFC00000, 0xB9000000, "strw", 4),
                                  (0xFFC00000, 0x39400000, "ldrb", 1), (0xFFC00000, 0x39000000, "strb", 1),
                                  (0xFFC00000, 0x79400000, "ldrh", 2), (0xFFC00000, 0x79000000, "strh", 2)):
        if (w & mask) == op:
            return kind, w & 31, (w >> 5) & 31, ((w >> 10) & 0xFFF) * scale, None
    if (w & 0xFFC00000) in (0xA9400000, 0xA9000000):               # ldp / stp x, signed offset
        return ("ldp" if w & 0x400000 else "stp"), w & 31, (w >> 5) & 31, sext((w >> 15) & 0x7F, 7) * 8, (w >> 10) & 31
    return None


def _tbz_bit(w):
    """tbz / tbnz wt, #bit -> (t, bit), else None"""
    return (w & 31, ((w >> 19) & 31) | ((w >> 26) & 0x20)) if (w & 0x7E000000) == 0x36000000 else None


def _bodies_after(t, va, n=4, cap=600):
    """the n function bodies after the one at va, [(start, [(va, word)])]: a body ends where nop padding (or a
    known function start) begins - the scanner's starts miss a function nothing calls (Star Wars ELG 1.10's
    lamp_free_owner at 0x236d30, reached through a pointer), so the padding between functions is read too"""
    out, cur, a, pad = [], None, va, False
    known = set(t.starts)
    while len(out) <= n and a < va + 4 * cap * (n + 1):
        w = t.u32(a)
        if w is None:
            break
        if w == 0xD503201F:                                             # nop
            pad = True
        else:
            if pad or (a in known and a != va):
                cur = (a, [])
                out.append(cur)
            pad = False
            if cur is not None:
                cur[1].append((a, w))
        a += 4
    return out[:n]


def _regs_walk(t, va, cap=80):
    """(va, word, regs) for the first `cap` words at va, regs: a register's known value ('a', address) for an adrp
    (+ add), ('g', target) for a GOT slot's pointer loaded through it, ('v', target) for the word that pointer
    points at (one more ldr), as each word is reached"""
    reg = {}
    for a, w in list(_window(t, va, cap))[:cap]:
        yield a, w, dict(reg)
        p = _adrp(a, w)
        if p:
            reg[p[0]] = ("a", p[1])
            continue
        ad = _add_imm(w)
        if ad and reg.get(ad[1], ("",))[0] == "a":
            reg[ad[0]] = ("a", reg[ad[1]][1] + ad[2])
            continue
        ls = _ls(w)
        if ls and ls[0] == "ldr":
            src = reg.get(ls[2])
            if src and src[0] == "a" and (src[1] + ls[3]) in t.ptr:
                reg[ls[1]] = ("g", t.ptr[src[1] + ls[3]])
            elif src and src[0] == "g" and ls[3] == 0:
                reg[ls[1]] = ("v", src[1])
            else:
                reg.pop(ls[1], None)
        elif ls and ls[0] in ("ldp", "ldrb", "ldrh", "ldrw"):
            reg.pop(ls[1], None)
            if ls[4] is not None:
                reg.pop(ls[4], None)
        elif _bl(a, w):
            for r in range(19):
                reg.pop(r, None)


def lamp_layer(t, lamp_group):
    """the 64-bit lamp layer, read off the game's allocator (the call `lamp_group` makes): {'data': lamp_layers,
    light_count, event_current; 'value': lamp_group_prio, lamp_group_next, lamp_slot_size, lamp_group_owner;
    'site': lamp_free_owner} - or {'why': ...}. Star Wars ELG 1.10: 0x735e68 (free list, then the active list, one
    pointer each), the group's priority byte +8, its event +24, next +32, slots of 40 bytes, the light count u64."""
    out = {"data": {}, "value": {}, "site": {}, "why": []}
    alloc = next((b for a, w in _window(t, lamp_group, 40) for b in [_bl(a, w)] if b), None)
    if not alloc:
        out["why"].append("lamp_group makes no call")
        return out
    prio_reg = None
    heads = group = None
    for a, w, reg in _regs_walk(t, alloc, 120):
        if (w & 0xFFFFFC00) == 0x12001C00 and ((w >> 5) & 31) == 1:      # and w?, w1, #0xff: the priority
            prio_reg = w & 31
        ls = _ls(w)
        if not ls:
            continue
        kind, rt, rn, imm, rt2 = ls
        src = reg.get(rn)
        if kind == "ldr" and heads is None and src and src[0] == "a" and (src[1] + imm) not in t.ptr:
            heads, group = src[1] + imm, rt                              # the free list's head: the group taken
            continue
        if group is None or rn != group:
            continue
        if kind == "ldr" and "lamp_group_next" not in out["value"]:
            out["value"]["lamp_group_next"] = imm                       # the free list's next, read first
        elif kind == "strb" and rt == prio_reg:
            out["value"]["lamp_group_prio"] = imm
        elif kind == "stp" and reg.get(rt2, ("",))[0] == "v":
            out["data"]["event_current"], out["value"]["lamp_group_owner"] = reg[rt2][1], imm + 8
        elif kind == "str" and reg.get(rt, ("",))[0] == "v":
            out["data"]["event_current"], out["value"]["lamp_group_owner"] = reg[rt][1], imm
    # the slots: memset(group[0], 0, count * 40) - the count a u64 through the GOT, * 5 then << 3
    words = list(_window(t, alloc, 120))
    for k, (a, w) in enumerate(words[:-2]):
        if (w & 0xFFE0FC00) == 0x8B000800 and (w & 31) == ((w >> 5) & 31) == ((w >> 16) & 31):   # add xd, xd, xd, lsl #2
            nxt = words[k + 1][1]
            if (nxt & 0xFFC0FC00) == 0xD340F000 or (nxt & 0xFFFFFC00) == 0xD37DF000:            # lsl #3 (ubfm)
                out["value"]["lamp_slot_size"] = 40
            for b, w2, reg in _regs_walk(t, alloc, k + 1):
                if b == a and reg.get(w & 31, ("",))[0] == "v":
                    out["data"]["light_count"] = reg[w & 31][1]
            break
    if heads is not None:
        out["data"]["lamp_layers"] = heads
    # lamp_free_owner: the next functions after the allocator; the one that walks the active list for a group
    # whose owner (+24) is its argument (the one after it frees one group, the one after that walks the frees)
    own = out["value"].get("lamp_group_owner")
    for f, body in (_bodies_after(t, alloc) if own is not None else []):
        refs_heads = reads_owner = False
        for a, w, reg in _regs_walk(t, f, len(body)):
            ls = _ls(w)
            if not ls:
                continue
            src = reg.get(ls[2], ("",))
            if src[0] == "a" and heads is not None and src[1] + ls[3] in (heads, heads + 8):
                refs_heads = True
            if ls[0] in ("ldr", "ldp") and ls[3] == own and src[0] != "a" and ls[2] != 31:
                reads_owner = True
        if refs_heads and reads_owner:
            out["site"]["lamp_free_owner"] = f
            break
    for need in ("lamp_layers", "light_count", "event_current"):
        if need not in out["data"]:
            out["why"].append("%s not read in the allocator 0x%x" % (need, alloc))
    for need in ("lamp_group_prio", "lamp_group_next", "lamp_slot_size"):
        if need not in out["value"]:
            out["why"].append("%s not read in the allocator 0x%x" % (need, alloc))
    if "lamp_free_owner" not in out["site"]:
        out["why"].append("no function after the allocator walks the groups by owner")
    return out


def processes(t, proc_create):
    """the game's process (event) records, from proc_create: {'data': event_head, event_current; 'value':
    event_next, proc_exit_hooks, proc_exit_slots, proc_record_size} - Star Wars ELG 1.10: the list at 0x7493d8 (the
    current record the pointer after it), the next record at +232, 376-byte records, four {fn, arg} exit hooks of 16
    bytes at +0x138 (the exit at 0x3146d0 calls each as fn(record, arg))."""
    out = {"data": {}, "value": {}, "site": {}, "why": []}
    base = creator = None
    for a, w, reg in _regs_walk(t, proc_create, 40):
        ls = _ls(w)
        if ls and ls[0] == "ldr" and reg.get(ls[2], ("",))[0] == "a" and (reg[ls[2]][1] + ls[3]) not in t.ptr:
            if ls[3] in (8, 16) and base is None:
                base = reg[ls[2]][1]
            if base is not None and reg[ls[2]][1] == base:
                out["data"]["event_head" if ls[3] == 8 else "event_current"] = base + ls[3]
        elif ls and ls[0] == "ldr" and ls[1] == ls[2] and ls[3] > 16:
            out["value"].setdefault("event_next", ls[3])
        if (w & 0xFC000000) == 0x14000000:
            creator = a + 4 * sext(w & 0x3FFFFFF, 26)
    if creator:
        for a, w in _window(t, creator, 40):
            if (w & 0xFFE0001F) == 0xD2800002:                          # mov x2, #size: memset of the record
                out["value"]["proc_record_size"] = (w >> 5) & 0xFFFF
                break
    # the exit: a loop over the record's hooks, `add xh, xr, #first; add xe, xr, #end; ... blr; add xh, xh, #16`
    lo, hi = proc_create - 0x3000, proc_create + 0x3000
    i = bisect.bisect_left(t.starts, lo)
    while i < len(t.starts) and t.starts[i] < hi and "proc_exit_hooks" not in out["value"]:
        f = t.starts[i]
        i += 1
        body = list(_window(t, f, 60))
        made = {}                                                       # register -> (base register, #imm)
        for k, (a, w) in enumerate(body):
            ad = _add_imm(w)
            if ad and ad[0] != ad[1]:
                made[ad[0]] = (ad[1], ad[2])
            if (w & 0xFFFFFC1F) != 0xD63F0000:                          # blr
                continue
            for a2, w2 in body[k + 1:k + 5]:
                ad2 = _add_imm(w2)
                if not (ad2 and ad2[0] == ad2[1] and ad2[0] in made and ad2[2] in (8, 16)):
                    continue
                base, first = made[ad2[0]]
                ends = [v for r, (b, v) in made.items() if b == base and r != ad2[0] and v > first]
                if ends and (min(ends) - first) % ad2[2] == 0 and 1 <= (min(ends) - first) // ad2[2] <= 8:
                    out["value"]["proc_exit_hooks"] = first
                    out["value"]["proc_exit_slots"] = (min(ends) - first) // ad2[2]
                    out["site"]["proc_exit"] = f
                break
            break
    for need in ("event_head", "event_current"):
        if need not in out["data"]:
            out["why"].append("%s not read in proc_create" % need)
    for need in ("event_next", "proc_exit_hooks"):
        if need not in out["value"]:
            out["why"].append("%s not read off the program" % need)
    return out


def show_event(t, show_priority):
    """the show flag and the show id of an event record, read in show_priority: (flags offset, flag, id offset) -
    Star Wars ELG 1.10: +2 bit 0x20, +258 (Spike 2: +150)"""
    flags = flag = sid = None
    for a, w in _window(t, show_priority, 30):
        ls = _ls(w)
        tb = _tbz_bit(w)
        if ls and ls[0] == "ldrh" and flags is None:
            flags = ls[3]
        elif tb and flags is not None and flag is None:
            flag = 1 << tb[1]
        elif ls and ls[0] == "ldrh" and flag is not None and sid is None:
            sid = ls[3]
    return flags, flag, sid


def show_table(e, show_start):
    """(table, count, stride) of the game's show table, read in show_start: Spike 3 through the GOT (16-byte records
    {body, kind, flags}), Spike 2 the movw/movt address its records (12 bytes) start at"""
    if e.a64:
        got = _got_loads(e, show_start, 30)
        cnt = next((g for g in got if e.off(g) is not None and e.u32(g + 4) == 0 and 1 <= (e.u32(g) or 0) < 4096), None)
        n = e.u32(cnt) if cnt else 0
        tab = next((g for g in got if g != cnt and n and sum(1 for k in range(n) if e.in_text(e.ptr.get(g + 16 * k, 0))) * 2 > n), None)
        return tab, n, 16
    i0 = (show_start - e.tva) // 4
    addrs = [a for i in range(i0, i0 + 40) for a in e.refs.get(i, [])]
    cnt = next((a for a in addrs if e.off(a) is not None and 1 <= (e.u32(a) or 0) < 4096), None)
    n = e.u32(cnt) if cnt else 0
    tab = next((a for a in addrs if a != cnt and n and sum(1 for k in range(n) if e.in_text(e.u32(a + 12 * k) or 0)) * 2 > n), None)
    return tab, n, 12


def show_records(e, show_start):
    """[(body, kind, flags)] of the show table"""
    tab, n, stride = show_table(e, show_start)
    if not tab:
        return []
    out = []
    for k in range(n):
        body = e.ptr.get(tab + 16 * k) if e.a64 else e.u32(tab + 12 * k)
        out.append((body, e.u32(tab + stride * k + stride - 8), e.u32(tab + stride * k + stride - 4)))
    return out


def lamp_devices(t):
    """{name (upper case): (I/O group, index)} of the lamps (class 3) in the program's own device table"""
    out = {}
    for name, g, idx, cls in device_records(t):
        if cls == 3:
            out.setdefault(name.upper(), (g, idx))
    return out


def light_lists(t, setter):
    """the light table the per-light setter reads (16-byte records {u16 list, kind}): [sorted light ids] per
    record. Star Wars ELG 1.10: 74 records at 0x6c6638, their count a u64 at 0x5a3808."""
    got = _got_loads(t, setter, 20)
    cnt = next((g for g in got if t.off(g) is not None and t.u32(g + 4) == 0 and 1 <= (t.u32(g) or 0) < 4096), None)
    n = t.u32(cnt) if cnt else 0
    tab = next((g for g in got if g != cnt and n and all((g + 16 * k) in t.ptr or t.u32(g + 16 * k) == 0 for k in range(n))), None)
    if not tab:
        return []
    out = []
    for k in range(n):
        p, ids = t.ptr.get(tab + 16 * k), []
        while p and len(ids) < 16:
            o = t.off(p + 2 * len(ids))
            v = struct.unpack_from("<H", t.b, o)[0] if o is not None else 0
            if not v:
                break
            ids.append(v)
        out.append(sorted(ids))
    return out


def light_engine(ref, rport_lines, tgt, placed):
    """PAD-1283: the lamp layer, the game's processes and its light shows on a Spike 3 program - sites, data and
    values read off its own code (lamp_layer, processes, show_event), the shows the Spike 2 port names carried by
    their place in the show table (the same record: body, kind and flags), the lamp lines by name (a lamp the
    device table names, its light ids one of the light table's records). {'site', 'data', 'value', 'show': [port
    lines], 'lamp': [port lines], 'why': [...]}"""
    out = {"site": {}, "data": {}, "value": {}, "show": [], "lamp": [], "why": []}
    rsite = {t[1]: int(t[2], 16) for k, t, s in rport_lines if k == "site" and len(t) >= 3}
    g = placed.get("lamp_group")
    if g:
        ll = lamp_layer(tgt, g)
        out["data"].update(ll["data"]), out["value"].update(ll["value"]), out["site"].update(ll["site"])
        out["why"] += ll["why"]
        if ll["value"].get("lamp_slot_size") == 40:
            # the slot is the same 40 bytes on both machines (the light id u16 +0, level +2, alpha +3, fade +8, a
            # callback +16, its time +24, its running flag +32, the used byte +36): read in the compositor
            out["value"].update(lamp_slot_level=2, lamp_slot_alpha=3, lamp_slot_fade=8, lamp_slot_used=36)
    pc = placed.get("proc_create")
    if pc:
        pr = processes(tgt, pc)
        for k2, v in pr["data"].items():
            if k2 in out["data"] and out["data"][k2] != v:
                out["why"].append("%s: 0x%x in the allocator, 0x%x in proc_create" % (k2, out["data"][k2], v))
            out["data"][k2] = v
        out["value"].update(pr["value"])
        out["why"] += pr["why"]
    sp = placed.get("show_priority")
    if sp:
        fo, fl, sid = show_event(tgt, sp)
        if None not in (fo, fl, sid):
            out["value"].update(event_flags=fo, event_show_flag=fl, event_show_id=sid)
    # the shows: the Spike 2 port's show_<n>, at the same place of the show table on both builds
    ss, rss = placed.get("show_start"), rsite.get("show_start")
    shows = sorted((int(t[1][5:]), int(t[2], 16), s) for k, t, s in rport_lines
                   if k == "site" and len(t) >= 3 and re.match(r"show_\d+$", t[1]))
    if shows and ss and rss:
        rrec, trec = show_records(ref, rss), show_records(tgt, ss)
        texts = {t[1]: s for k, t, s in rport_lines if k in ("text", "value") and len(t) >= 2}
        n = 0
        for num, a, s in shows:
            k = next((i for i, r in enumerate(rrec) if r[0] == a), None)
            if k is None or k >= len(trec) or trec[k][1:] != rrec[k][1:] or not tgt.in_text(trec[k][0] or 0):
                why = ("not in Spike 2's show table" if k is None else "past the %d shows of Spike 3's table" % len(trec)
                       if k >= len(trec) else "Spike 3's record %d is another show" % k)
                out["show"].append("# show %d of the Spike 2 port (%s) not carried: %s" % (
                    num, (texts.get("show_name_%d" % num) or "").split(None, 2)[-1], why))
                continue
            if "show_call_%d" % num in texts:
                out["show"].append("# show %d of the Spike 2 port not carried: started by a call of the game's "
                                   "(show_call), not proven on Spike 3" % num)
                continue
            n += 1
            b = trec[k][0]
            note = s.split("#", 1)[1].strip() if "#" in s else ""
            out["show"].append("site show_%-12d 0x%08x 0x%08x 0x%08x   # Spike 2's show_%d, record %d of the show table%s"
                               % (n, b, tgt.u32(b), tgt.u32(b + 4), num, k, ("; " + note) if note else ""))
            for key in ("show_name_%d", "show_kind_%d", "show_secs_%d"):
                line = texts.get(key % num)
                if line:
                    out["show"].append(re.sub(r"^(\s*\w+\s+)show_(name|kind|secs)_%d\b" % num,
                                              lambda m: "%sshow_%s_%d" % (m.group(1), m.group(2), n), line))
        sp_id = next((int(t[2], 0) for k, t, s in rport_lines if k == "value" and len(t) >= 3 and t[1] == "show_proc"), None)
        if n and sp_id is not None:
            # an id the game never uses on this build either: no movz of it anywhere in the program
            used = sum(1 for x in tgt.words if (x & 0x7FE00000) == 0x52800000 and (x >> 5) & 0xFFFF == sp_id)
            if used:
                out["why"].append("show_proc %d is an id the Spike 3 program uses (%d places)" % (sp_id, used))
            else:
                out["value"]["show_proc"] = sp_id
    # the lamp lines: the same light ids, by name
    calls = [b for a, w in _window(tgt, g, 40) for b in [_bl(a, w)] if b] if g else []
    setter = calls[1] if len(calls) > 1 else None          # lamp_group: the allocator, then the per-light setter
    lists = light_lists(tgt, setter) if setter else []
    devs = lamp_devices(tgt)
    for k, t, s in rport_lines:
        if k != "lamp":
            continue
        m = re.match(r"\s*lamp\s+(\S+)\s+(\S+)\s+(.*?)\s*(#.*)?$", s)
        if not m:
            continue
        ids, mask, name, note = m.group(1), m.group(2), m.group(3).strip(), (m.group(4) or "")
        want = sorted(int(x) for x in ids.split(","))
        dev = devs.get(name.upper())
        if dev is None or want not in lists:
            out["lamp"].append("# lamp NOT PLACED: %s (%s)" % (
                "no lamp named %r on Spike 3" % name if dev is None else "no record of light ids %s in Spike 3's light table" % ids,
                s.strip()))
            continue
        note = re.sub(r"I/O group \d+ index \d+", "I/O group %d index %d" % dev, note)
        out["lamp"].append(("lamp %-12s %-14s %s  %s" % (ids, mask, name, note)).rstrip())
    if out["lamp"] and not lists:
        out["why"].append("the light table was not read (no per-light call in lamp_group)")
    return out


# ---- PAD-1284: scenes, text and the video surface --------------------------------------------------------------
#: the engine's Sprite class (Radium's own, in every title): its vtable holds the visibility setter pm_show calls
SPRITE_TYPE = b"N6Radium6SpriteE"
#: the sites the screen and clip features call that the matcher places; carried when scene_engine read the rest
SCREEN_SITES = ("find_node", "find_text", "set_text")
CLIP_SITES = ("surface_find", "surface_state", "surface_play", "surface_stop")
#: the scenes a mode's screen (hud) and clip (video_bank) go in, copied when the program names the same ids
SCENES_CARRIED = ("hud", "video_bank")


def _va_of(t, off):
    for s, o, fs, fl in t.segs:
        if o <= off < o + fs:
            return s + off - o
    return None


def _typeinfo(t, name):
    """the typeinfo object whose mangled name is `name` (b'6IScene') in a 64-bit program - the object whose name
    pointer (+8) points at the string - or None"""
    o = t.b.find(b"\0" + name + b"\0")
    while o >= 0:
        va = _va_of(t, o + 1)
        hit = sorted(p - 8 for p, a in t.ptr.items() if a == va) if va is not None else []
        if hit:
            return hit[0]
        o = t.b.find(b"\0" + name + b"\0", o + 1)
    return None


def _ref_typeinfo_name(ref, va):
    """a 32-bit program's typeinfo object at va -> its mangled name (bytes), or None"""
    p = ref.ptr.get(va + 4)
    s = ref.cstr(p) if p else None
    return s.encode() if s else None


def _mov_reg(w):
    """mov xd, xn (orr xd, xzr, xn) -> (d, n), else None"""
    return (w & 31, (w >> 16) & 31) if (w & 0xFFE0FFE0) == 0xAA0003E0 else None


def _walk_mem(t, va, cap=160):
    """(va, word, regs) for the first `cap` words at va: a register's value ('a', address) for an adrp (+ add),
    ('m', address) for the word one ldr loads from such an address, copied by mov; x0-x18 forgotten at a call,
    and any other register an instruction writes"""
    reg = {}
    for a, w in list(_window(t, va, cap))[:cap]:
        yield a, w, dict(reg)
        p, ad, ls, mv = _adrp(a, w), _add_imm(w), _ls(w), _mov_reg(w)
        if p:
            reg[p[0]] = ("a", p[1])
        elif ad and reg.get(ad[1], ("",))[0] == "a":
            reg[ad[0]] = ("a", reg[ad[1]][1] + ad[2])
        elif ls and ls[0] == "ldr" and reg.get(ls[2], ("",))[0] == "a":
            reg[ls[1]] = ("m", reg[ls[2]][1] + ls[3])
        elif mv:
            if mv[1] in reg:
                reg[mv[0]] = reg[mv[1]]
            else:
                reg.pop(mv[0], None)
        elif _bl(a, w):
            for r in range(19):
                reg.pop(r, None)
        elif ls:
            if ls[0].startswith("ld"):
                reg.pop(ls[1], None)
                if ls[4] is not None:
                    reg.pop(ls[4], None)
        else:
            reg.pop(w & 31, None)


def _ready_byte(t, va):
    """the byte a video-surface method tests first (ldrb wN, [x0, #imm] in its first 16 words: the surface's 'set
    up' flag, the same in every method), or None"""
    for a, w in list(_window(t, va, 16))[:16]:
        if (w & 0xFFC003E0) == 0x39400000:
            return (w >> 10) & 0xFFF
    return None


def _calls_before(t, i, n, back):
    """the targets of the last `n` calls (bl to code, not to a PLT stub) in the `back` words before word i, nearest
    first"""
    out = []
    for j in range(i - 1, max(-1, i - back), -1):
        tg = t.calls.get(j)
        if tg is not None and tg not in t.plt:
            out.append(tg)
            if len(out) == n:
                break
    return out


def scene_engine(ref, rlines, tgt, at):
    """what the screen and clip features need, read off the 64-bit program: {'site', 'data', 'value': {name: v},
    'scene': [port lines], 'screens': bool, 'clips': bool, 'why': [what could not be read]}. `at`: the matcher's
    placements of SCREEN_SITES / CLIP_SITES (name -> address)."""
    out = {"site": {}, "data": {}, "value": {}, "scene": [], "screens": False, "clips": False, "why": []}
    why = out["why"]
    rdata = {t[1]: int(t[2], 16) for k, t, s in rlines if k == "data" and len(t) >= 3}
    rval = {t[1]: int(t[2], 0) for k, t, s in rlines if k == "value" and len(t) >= 3}
    cast = next((a for a, n in tgt.plt.items() if n == "__dynamic_cast"), None)
    if cast is None:
        why.append("the program imports no __dynamic_cast")
        return out
    out["site"]["dynamic_cast"] = cast
    tis = {}
    for name in ("typeinfo_resource", "typeinfo_scene_player"):
        nm = _ref_typeinfo_name(ref, rdata[name]) if name in rdata else None
        ti = _typeinfo(tgt, nm) if nm else None
        if ti is None:
            why.append("%s: %s" % (name, "the Spike 2 port names none" if not nm else
                                   "no typeinfo named %s in the program" % nm.decode()))
            return out
        tis[name] = ti
        out["data"][name] = ti
    # the game's own scene lookups: (a wrapper of) resource_get, then __dynamic_cast(res, resource, scene player)
    wrappers, scene_at = Counter(), Counter()
    for i, tg in tgt.calls.items():
        if tg != cast:
            continue
        va = tgt.tva + 4 * i
        regs = next((r for a, w, r in _regs_walk(tgt, va - 48, 13) if a == va), None)
        if not regs or {regs.get(1, ("",))[1:], regs.get(2, ("",))[1:]} != {(tis["typeinfo_resource"],),
                                                                              (tis["typeinfo_scene_player"],)}:
            continue
        if regs[1][1] != tis["typeinfo_resource"]:
            continue
        prev = _calls_before(tgt, i, 1, 24)
        if prev:
            wrappers[prev[0]] += 1
        held, locked = {0}, False                 # after the cast: the scene field read under the player's mutex
        for a, w in list(_window(tgt, va + 4, 20))[:20]:
            mv = _mov_reg(w)
            if mv and mv[1] in held:
                held.add(mv[0])
                continue
            b = _bl(a, w)
            if b is not None:
                if tgt.plt.get(b) == "pthread_mutex_lock":
                    locked = True
                    continue
                if locked:
                    break
                held = {r for r in held if r >= 19}
                continue
            ls = _ls(w)
            if locked and ls and ls[0] == "ldr" and ls[2] in held:
                scene_at[ls[3]] += 1
                break
    if not wrappers:
        why.append("no scene lookup (__dynamic_cast from %s to %s) in the program" % tuple(
            _ref_typeinfo_name(ref, rdata[n]).decode() for n in ("typeinfo_resource", "typeinfo_scene_player")))
        return out
    wrap = wrappers.most_common(1)[0][0]
    got = None
    for a, w, regs in _walk_mem(tgt, wrap):
        b = _bl(a, w)
        if b is not None and b not in tgt.plt:
            if regs.get(0, ("",))[0] == "m":
                got = (b, regs[0][1])
            break
    if got is None:
        why.append("the scene lookup's resource_get (0x%x's first call, on the manager) could not be read" % wrap)
        return out
    rg, mgr = got
    if not any((w & 0xFFFFFC1F) == 0x7100081F and ((w >> 5) & 31) == 2 for a, w in list(_window(tgt, rg, 12))[:12]):
        why.append("0x%x does not switch on its mode argument (cmp w2, #2) as resource_get does" % rg)
        return out
    out["site"]["resource_get"], out["data"]["resource_manager"] = rg, mgr
    if not scene_at:
        why.append("the scene player's scene field could not be read after a lookup")
        return out
    out["value"]["scene_player_scene"] = scene_at.most_common(1)[0][0]
    # the node visibility setter: Spike 2's vtable slot, in the Sprite vtable that holds the setter / getter pair
    slot = rval.get("node_visible_vfn", -1) // 4
    ti = _typeinfo(tgt, SPRITE_TYPE)
    vis = None
    for p in sorted(p for p, a in tgt.ptr.items() if a == ti) if ti is not None and slot >= 0 else ():
        vt = p - 8
        st, gt = tgt.ptr.get(vt + 16 + 8 * slot), tgt.ptr.get(vt + 24 + 8 * slot)
        if st is None or gt is None:
            continue
        ws, wg = tgt.u32(st), tgt.u32(gt)
        if ws is not None and wg is not None and (ws & 0xFFC003FF) == 0x39000001 and tgt.u32(st + 4) == 0xD65F03C0 \
                and (wg & 0xFFC003FF) == 0x39400000 and (wg >> 10) & 0xFFF == (ws >> 10) & 0xFFF:
            vis = 8 * slot
            break
    if vis is None:
        why.append("the Sprite vtable's visibility setter (slot %d: strb w1 / ldrb w0 of one byte) was not found"
                   % slot)
    else:
        out["value"]["node_visible_vfn"] = vis
    ids = {t[1]: t[2] for k, t, s in rlines if k == "scene" and len(t) >= 3}
    for name in SCENES_CARRIED:
        sid = ids.get(name)
        if sid and all(len(x) == 40 and tgt.b.find(x.encode()) >= 0 for x in sid.split("/")):
            out["scene"].append("scene %-20s %s" % (name, sid))
    out["screens"] = vis is not None and all(n in at for n in SCREEN_SITES) and any(
        l.split()[1] == "hud" for l in out["scene"])
    if not out["screens"]:
        why.append("screens: %s" % ("no hud scene the program names" if vis is not None and
                                    all(n in at for n in SCREEN_SITES) else "the node finders or the visibility "
                                    "setter are missing"))
    # the video surface: every method tests the same 'set up' byte first
    if not all(n in at for n in CLIP_SITES):
        why.append("clips: the matcher did not place %s" % ", ".join(n for n in CLIP_SITES if n not in at))
        return out
    ready = _ready_byte(tgt, at["surface_stop"])
    if ready is None:
        why.append("clips: surface_stop tests no 'set up' byte")
        return out
    sv = Counter()
    for i, tg in tgt.calls.items():
        if tg == at["surface_play"]:
            for c in _calls_before(tgt, i, 4, 40):
                if _ready_byte(tgt, c) == ready:
                    sv[c] += 1
                    break
    pair, playing = Counter(), Counter()
    for i, tg in tgt.calls.items():           # the game's progress read: position, duration, then the state
        if tg != at["surface_state"]:
            continue
        prev = _calls_before(tgt, i, 2, 10)
        if len(prev) == 2 and prev[0] != prev[1] and all(_ready_byte(tgt, c) == ready for c in prev):
            pair[(prev[1], prev[0])] += 1
            for j in range(i + 1, i + 4):
                w = tgt.words[j]
                if (w & 0xFFC003FF) == 0x7100001F:                 # cmp w0, #imm
                    playing[(w >> 10) & 0xFFF] += 1
                    break
    if not sv or not pair or not playing:
        why.append("clips: %s could not be read" % ", ".join(n for n, c in (("surface_set_video", sv),
                                                                             ("surface_position/duration", pair),
                                                                             ("surface_playing", playing)) if not c))
        return out
    out["site"]["surface_set_video"] = sv.most_common(1)[0][0]
    pos, dur = pair.most_common(1)[0][0]
    out["site"]["surface_position"], out["site"]["surface_duration"] = pos, dur
    out["value"]["surface_playing"] = playing.most_common(1)[0][0]
    out["clips"] = any(l.split()[1] == "video_bank" for l in out["scene"])
    if not out["clips"]:
        why.append("clips: no video bank scene the program names")
    return out


# ---- PAD-1285: a mode's own multiball, held coils, the game's mode starts (blocks) and its game flags ----------------
# The matcher places balls_in_play / multiball_serve / proc_sleep / adjustment / coil_fire (plain calls with their
# arguments in w0-w5 on both machines: the serve's two stack words are x4/x5). What their features read is laid out
# again by the 64-bit framework, read here off the program: the coil records coil_fire's writer fills (the same 0x68
# bytes, the table's pointer and its u64 count 8 bytes), the device object's take / give (its controlling process
# at +40 where Spike 2 has +32: the vtable pointer is 8 bytes), a held coil's static object by the device
# constructor's call with its device id, and each of the game's mode starts by the game flag it sets.
PLAY_SITES = ("balls_in_play", "multiball_serve", "proc_sleep", "adjustment", "coil_fire")
COIL_REC_SIZE = 0x68


def _movz_w(w):
    """movz wd, #imm (no shift) -> (d, imm), else None"""
    return (w & 31, (w >> 5) & 0xFFFF) if (w & 0xFFE00000) == 0x52800000 else None


def _mov_x0(w):
    """mov xd, x0 (orr xd, xzr, x0) -> d, else None"""
    return w & 31 if (w & 0xFFFFFFE0) == 0xAA0003E0 else None


def _b(va, w):
    return va + 4 * sext(w & 0x3FFFFFF, 26) if (w & 0xFC000000) == 0x14000000 else None


def _arm_mov_r0(w):
    """ARM mov r0, #imm -> imm, else None"""
    if (w & 0xFFFFF000) != 0xE3A00000:
        return None
    rot = 2 * ((w >> 8) & 0xF)
    v = w & 0xFF
    return ((v >> rot) | (v << (32 - rot))) & 0xFFFFFFFF if rot else v


def coil_records(t, coil_fire):
    """the coil records coil_fire's writer fills (coil_fire ends in a branch to it): {'data': {coil_table,
    coil_count}, 'why': [...]} - the table's pointer is the writer's plain load (`ldr x28, [x21, #0x300]`), the count
    its GOT load, each record COIL_REC_SIZE bytes (`mov w3, #0x68`), the request id stored at +0x14 and the link
    word read at +0x10, as the runtime's COIL_REC_* say"""
    out = {"data": {}, "why": []}
    wr = next((_b(a, w) for a, w in list(_window(t, coil_fire, 16))[:16] if _b(a, w)), None)
    if not wr:
        out["why"].append("coil_fire ends in no branch to a record writer")
        return out
    page, tab, cnt, size, rid, link = {}, None, None, False, False, False
    for a, w in list(_window(t, wr, 120))[:120]:
        p = _adrp(a, w)
        if p:
            page[p[0]] = p[1]
            continue
        ls = _ls(w)
        mz = _movz_w(w)
        if mz and mz[1] == COIL_REC_SIZE:
            size = True
        if ls and ls[0] == "ldr" and ls[2] in page:
            at = page[ls[2]] + ls[3]
            if at in t.ptr:
                cnt = cnt or t.ptr[at]
            elif tab is None and t.is_data(at):
                tab = at
        if ls and ls[0] == "strw" and ls[3] == 0x14:
            rid = True
        if ls and ls[0] == "ldrw" and ls[3] == 0x10:
            link = True
    if not (tab and cnt and size and rid and link):
        out["why"].append("the coil record writer at 0x%x is not the known shape (table %s, count %s, 0x68 %s, id +0x14 "
                          "%s, link +0x10 %s)" % (wr, hex(tab or 0), hex(cnt or 0), size, rid, link))
        return out
    out["data"].update(coil_table=tab, coil_count=cnt)
    return out


def coil_control(t, proc_sleep):
    """the device objects' takes (obj, ticks) and gives (obj, flag) - Spike 2's coil_take / coil_give: a take keeps
    the object (`mov xR, x0`), waits a tick at a time (proc_sleep) while +CTL is held, adds an exit hook (`bl hook;
    str w0, [xR, #HOOK]`) and stores the process's id at +CTL; its give opens `mov x19, x0; strh wzr, [x0, #CTL];
    tbnz w1, #0` and calls the object's update through its vtable. Each device family has its own pair (Star Wars
    ELG 1.10: control at +40, +60, +72); the held coil's constructor says which is its own (play_engine).
    [{'site': {coil_take, coil_give}, 'value': {ctl, hook, update_slot}}]"""
    out = []
    takes = []
    for f in t.starts:
        ws = list(_window(t, f, 80))[:80]
        R = next((_mov_x0(w) for a, w in ws[:3] if _mov_x0(w) is not None), None)
        if R is None or not any(_bl(a, w) == proc_sleep for a, w in ws):
            continue
        for i in range(len(ws) - 1):
            x, ls = _bl(*ws[i]), _ls(ws[i + 1][1])
            if not (x and ls and ls[0] == "strw" and ls[1] == 0 and ls[2] == R):
                continue
            st = [_ls(w) for a, w in ws[i + 2:i + 8]]
            c = [s for s in st if s and s[0] == "strh" and s[2] == R]
            if c:
                takes.append((f, x, ls[3], c[0][3]))
                break
    for take, hook, H, C in takes:
        gives = []
        for f in t.starts:
            ws = list(_window(t, f, 40))[:40]
            if len(ws) < 6 or _mov_x0(ws[1][1]) != 19 or _ls(ws[2][1]) != ("strh", 31, 0, C, None)                     or _tbz_bit(ws[3][1]) != (1, 0) or not any(_bl(a, w) == hook for a, w in ws):
                continue
            slots = [s[3] for s in (_ls(w) for a, w in ws) if s and s[0] == "ldr" and s[2] == s[1] and s[3] >= 8]
            gives.append((f, slots[0] if slots else None))
        if len(gives) == 1 and gives[0][1] is not None:
            out.append({"site": {"coil_take": take, "coil_give": gives[0][0]},
                        "value": {"ctl": C, "hook": H, "update_slot": gives[0][1] // 8}})
    return out


def _consts(t, va, cap):
    """(va, word, regs) over cap words, regs a register's address: adrp, add #imm, and `mov xd, xn` kept; x0-x18 lost
    at a call"""
    reg = {}
    for a, w in list(_window(t, va, cap))[:cap]:
        yield a, w, dict(reg)
        p = _adrp(a, w)
        if p:
            reg[p[0]] = p[1]
            continue
        ad = _add_imm(w)
        if ad:
            if ad[1] in reg:
                reg[ad[0]] = reg[ad[1]] + ad[2]
            else:
                reg.pop(ad[0], None)
            continue
        if (w & 0xFFE0FFE0) == 0xAA0003E0:                               # mov xd, xm
            m = (w >> 16) & 31
            if m in reg:
                reg[w & 31] = reg[m]
            else:
                reg.pop(w & 31, None)
            continue
        if _bl(a, w):
            for r in range(19):
                reg.pop(r, None)


def device_object(t, dev, ctl, adjustment):
    """a held coil's static object: built once by the device constructor (`strh w1, [x19, #DEVOFF]` its device,
    `strh wzr, [x19, #CTL]` the controlling process cleared) called with x0 = a static address and w1 = the device
    id, its vtable stored at that address next (`str x3, [x19, #144]`). {'obj', 'devoff', 'vtable', 'off_slot', 'why'}:
    off_slot = the vtable slot that answers "disabled" (it reads an adjustment id off the object and calls the
    adjustment getter)"""
    out = {"why": []}
    ctors = {}
    found = []
    for i0, w0 in enumerate(t.words):
        if _movz_w(w0) != (1, dev):
            continue
        va0 = t.tva + 4 * i0
        f = func_of(t, va0)
        if f is None or va0 - f > 4 * 2000:
            continue
        ws = list(_consts(t, f, (va0 - f) // 4 + 32))
        for i, (a, w, reg) in enumerate(ws):
            if a <= va0 or a > va0 + 24:
                continue
            x = _bl(a, w)
            if not x:
                continue
            if 0 not in reg:
                break
            if x not in ctors:
                cw = list(_window(t, x, 24))[:24]
                R = next((_mov_x0(w2) for a2, w2 in cw[:4] if _mov_x0(w2) is not None), None)
                st = [_ls(w2) for a2, w2 in cw]
                d = next((s[3] for s in st if s and s[0] == "strh" and s[1] == 1 and s[2] == R), None)
                z = any(s and s[0] == "strh" and s[1] == 31 and s[2] == R and s[3] == ctl for s in st)
                ctors[x] = d if (R is not None and z) else None
            if ctors[x] is not None:
                obj = reg[0]
                vt = None
                for a2, w2, r2 in ws[i + 1:i + 13]:
                    s2 = _ls(w2)
                    if s2 and s2[0] == "str" and s2[2] in r2 and r2[s2[2]] + s2[3] == obj and s2[1] in r2:
                        vt = r2[s2[1]]
                        break
                found.append((obj, ctors[x], vt))
            break
    found = sorted(set(found))
    if len(found) != 1 or found[0][2] is None:
        out["why"].append("%d static objects of device %d built by its constructor (one is wanted)" % (len(found), dev))
        return out
    obj, devoff, vt = found[0]
    out.update(obj=obj, devoff=devoff, vtable=vt)
    for slot in range(64):
        f = t.ptr.get(vt + 8 * slot)
        if not f or not t.in_text(f):
            continue
        ws = list(_window(t, f, 10))[:10]
        s0 = _ls(ws[0][1]) if ws else None
        if s0 and s0[0] == "ldrh" and s0[2] == 0 and any(_bl(a, w) == adjustment for a, w in ws):
            out["off_slot"] = slot
            break
    if "off_slot" not in out:
        out["why"].append("no slot of the object's vtable 0x%x answers 'disabled' through the adjustment getter" % vt)
    return out


def _raw(t, va, n):
    """(va, word) for n words at va, function starts or not (a short function's branch targets cut _window)"""
    return [(va + 4 * k, t.u32(va + 4 * k)) for k in range(n) if t.u32(va + 4 * k) is not None]


def flag_set(t, game_flags):
    """the game's flag set: a short function loading the bitmap pointer from game_flags (`ldr x3, [x1, #lo]`) and
    ORing a bit into it (a register-offset strb). -> (address, the count's GOT target) or (None, None)"""
    hits = []
    for f in t.starts:
        ws = _raw(t, f, 24)
        page, loads, cnt = {}, False, None
        for a, w in ws:
            p = _adrp(a, w)
            if p:
                page[p[0]] = p[1]
                continue
            ls = _ls(w)
            if ls and ls[0] == "ldr" and ls[2] in page:
                at = page[ls[2]] + ls[3]
                if at == game_flags:
                    loads = True
                elif at in t.ptr:
                    cnt = cnt or t.ptr[at]
        if loads and any((w & 0xFFE00C00) == 0x38200800 for a, w in ws) and any((w & 0x7F200000) == 0x2A000000
                                                                                   for a, w in ws)                 and not any((w & 0x7F200000) == 0x0A200000 for a, w in ws):          # a bic: the set-to-value
            hits.append((f, cnt))
    return hits[0] if len(hits) == 1 else (None, None)


def flag_names(e):
    """PAD-1286: the program's game flag names by id (`FG_INVALID` first: the pointer table that names it, 8 bytes an
    entry on Spike 3, 4 on Spike 2), or []."""
    i = e.b.find(b"\0FG_INVALID\0")
    va = _va_of(e, i + 1) if i >= 0 else None
    if va is None:
        return []
    step = 8 if e.a64 else 4
    best = []
    for at in [a for a, v in e.ptr.items() if v == va]:
        names = []
        while at + step * len(names) in e.ptr:
            nm = e.cstr(e.ptr[at + step * len(names)])
            if not nm or not nm.startswith("FG_"):
                break
            names.append(nm)
        if len(names) > len(best):
            best = names
    return best if len(best) > 8 else []


#: PAD-1286: the game's books of its modes the Spike 2 port names by flag (mode_framework.plain_books / done_books): a
#: mode in one's place sets its PLAYED / COMPLETED flags, a mode waiting for some completed watches a COMPLETED flag
BOOK_FLAG = re.compile(r"(place_flag_(?:played|completed)_(\d+)|done_flag_(\d+))$")


def mode_books(ref, rval, rtext, t, starts):
    """PAD-1286: the Spike 2 port's flag books on Spike 3, each flag by its NAME in the two programs' flag tables
    (Star Wars ELG's are the same ids on both; another title's need not be): the place_flag_* lines of the block starts
    carried, the done_flag_<n> lines with their done_name_<n>. -> ({name: flag id}, [text lines], [why])"""
    rn, tn = flag_names(ref), flag_names(t)
    if not rn or not tn:
        return {}, [], ["no FG_ flag name table in the %s program" % ("Spike 2" if not rn else "Spike 3")]
    tid = {n: i for i, n in enumerate(tn)}
    vals, text, why = {}, [], []
    for k, v in sorted(rval.items()):
        m = BOOK_FLAG.match(k)
        if not m:
            continue
        if m.group(2) is not None and int(m.group(2)) not in starts:
            why.append("%s: the game's mode %s has no start on Spike 3" % (k, m.group(2)))
            continue
        if m.group(3) is not None and not rtext.get("done_name_%s" % m.group(3), "").strip():
            continue
        fl = int(v, 0)
        nm = rn[fl] if fl < len(rn) else None
        if nm not in tid:
            why.append("%s: flag %d (%s) is not one of the Spike 3 program's" % (k, fl, nm))
            continue
        vals[k] = tid[nm]
        if m.group(3) is not None:
            text.append("text %-20s %s" % ("done_name_" + m.group(3), rtext["done_name_" + m.group(3)].strip()))
    return vals, text, why


def mode_starts(ref, rlines, t, fset):
    """the Spike 2 port's block_start_<id> lines on Spike 3, each by the game flag its start sets: the Spike 2 start's
    `mov r0, #flag` that is one of the port's mode_flag_<n> values, and the one Spike 3 function that opens with a
    call (the same guard shape) and sets that flag through the flag set within its first 24 words. -> {id: (va,
    flag)}, [why]"""
    rsite = {t1[1]: int(t1[2], 16) for k, t1, s in rlines if k == "site" and len(t1) >= 3}
    flags = {int(t1[2], 0) for k, t1, s in rlines if k == "value" and len(t1) >= 3 and re.match(r"mode_flag_\d+$", t1[1])}
    want = {}
    for name, a in rsite.items():
        m = re.match(r"block_start_(\d+)$", name)
        if not m:
            continue
        got = [v for v in (_arm_mov_r0(ref.u32(a + 4 * k) or 0) for k in range(24)) if v is not None and v in flags]
        if len(got) == 1:
            want[int(m.group(1))] = got[0]
    by_flag = defaultdict(list)
    for f in t.starts:
        ws = list(_window(t, f, 24))[:24]
        if len(ws) < 4 or not _bl(*ws[1]):
            continue
        for i, (a, w) in enumerate(ws):
            mz = _movz_w(w)
            if mz and mz[0] == 0 and mz[1] in want.values() and any(_bl(a2, w2) == fset for a2, w2 in ws[i + 1:i + 5]):
                by_flag[mz[1]].append(f)
                break
    out, why = {}, []
    for bid, fl in sorted(want.items()):
        c = by_flag.get(fl, [])
        if len(c) == 1:
            out[bid] = (c[0], fl)
        else:
            why.append("block_start_%d (flag %d): %d Spike 3 starts set it" % (bid, fl, len(c)))
    return out, why


def play_engine(ref, rlines, t, later_at, placed):
    """PAD-1285: what a mode's multiball, its held coils and its blocks need on a Spike 3 program. {'site', 'data',
    'value', 'text', 'carry' (matcher placements now carried), 'why'}"""
    out = {"site": {}, "data": {}, "value": {}, "text": [], "carry": [], "flag_of": {}, "why": [], "books": {}}
    rdata = {t1[1]: int(t1[2], 16) for k, t1, s in rlines if k == "data" and len(t1) >= 3}
    rval = {t1[1]: t1[2] for k, t1, s in rlines if k == "value" and len(t1) >= 3}
    rtext = {t1[1]: s.split(None, 2)[2] if len(s.split(None, 2)) > 2 else "" for k, t1, s in rlines if k == "text"}
    have = {n: later_at[n] for n in PLAY_SITES if n in later_at}
    if "balls_in_play" in have and "multiball_serve" in have:
        out["carry"] += ["balls_in_play", "multiball_serve"]
        arg3 = Counter()
        for i, tg in t.calls.items():
            if tg == have["multiball_serve"]:
                for k in range(1, 9):
                    mz = _movz_w(t.words[i - k]) if i - k >= 0 else None
                    if mz and mz[0] == 3:
                        arg3[mz[1]] += 1
                        break
        if arg3 and 0xBB not in arg3:
            out["value"]["multiball_arg3"] = arg3.most_common(1)[0][0]
    for n in ("proc_sleep", "adjustment", "coil_fire"):
        if n in have:
            out["carry"].append(n)
    # held coils
    if "coil_fire" in have and "proc_sleep" in have:
        cr = coil_records(t, have["coil_fire"])
        out["why"] += cr["why"]
        out["data"].update(cr["data"])
        pairs = coil_control(t, have["proc_sleep"])
        if not pairs:
            out["why"].append("no device take / give pair of the known shape")
        names = rtext.get("held_coils", "").split()
        cc = None
        if cr["data"] and pairs and "magnet_proc" in rval:
            out["value"]["magnet_proc"] = int(rval["magnet_proc"], 0)
            kept = []
            for c in names:
                dev = int(rval.get(c + "_dev", "0"), 0)
                if c + "_drive" not in rtext or not dev:
                    out["why"].append("held coil %s: not by its board address with a device on Spike 2" % c)
                    continue
                if c + "_obj" in rdata or c + "_ctl" in rval:
                    if not ("adjustment" in have and int(rval.get(c + "_ctl", "0"), 0)):
                        out["why"].append("held coil %s: its object needs the adjustment getter and a _ctl" % c)
                        continue
                    o, pair = {"why": ["no device take / give pair's constructor builds it"]}, None
                    for pr in pairs:                     # the family whose constructor builds this coil's object
                        o2 = device_object(t, dev, pr["value"]["ctl"], have["adjustment"])
                        if not o2["why"] or len(o2) > 1:
                            o, pair = o2, pr
                            break
                    if o["why"] or ("%s_off_slot" % c in rval and "off_slot" not in o) or (cc and pair is not cc):
                        out["why"] += ["held coil %s: %s" % (c, w) for w in o["why"] or ["another device family"]]
                        continue
                    cc = pair
                    out["site"].update(cc["site"])
                    out["data"][c + "_obj"] = o["obj"]
                    out["value"][c + "_ctl"] = cc["value"]["ctl"]
                    out["value"][c + "_devoff"] = o["devoff"]
                    if "%s_off_slot" % c in rval:
                        out["value"][c + "_off_slot"] = o["off_slot"]
                out["value"][c + "_dev"] = dev
                for k in ("label", "drive"):
                    if c + "_" + k in rtext:
                        out["text"].append("text %-20s %s" % (c + "_" + k, rtext[c + "_" + k]))
                kept.append(c)
            if kept:
                out["text"].append("text %-20s %s" % ("held_coils", " ".join(kept)))
    # the game's flags and mode starts
    gf = later_at.get("data:game_flags")
    if gf:
        fset, cnt = flag_set(t, gf)
        if fset and cnt:
            out["data"].update(game_flags=gf, game_flag_count=cnt)
            out["value"]["game_flags_at"] = 0
            starts, why = mode_starts(ref, rlines, t, fset)
            out["why"] += why
            for bid, (va, fl) in starts.items():
                out["site"]["block_start_%d" % bid] = va
                out["flag_of"]["block_start_%d" % bid] = fl
                if "block_name_%d" % bid in rtext:
                    out["text"].append("text %-20s %s" % ("block_name_%d" % bid, rtext["block_name_%d" % bid]))
            for k, v in rval.items():
                if re.match(r"mode_flag_\d+$", k) and int(v, 0) in {fl for va, fl in starts.values()}:
                    out["value"][k] = int(v, 0)
            out["books"], btext, bwhy = mode_books(ref, rval, rtext, t, starts)
            out["text"] += btext
            out["why"] += bwhy
        else:
            out["why"].append("no one flag set loads game_flags 0x%x" % gf)
    return out



# ---- PAD-1322: the switch edges --------------------------------------------------------------------------------------
#: the port lines the runtime's 64-bit edge source reads (pad_mode_runtime.c, "the switch edges on Spike 3")
EDGE_VALUES = ("switch_record_reg", "switch_id_at", "switch_level_at", "switch_desc_via", "switch_flags_at",
               "switch_polarity_at")
#: Spike 2's switch_edge lines: a per-switch call and the 32-bit tables it reads - none of them is Spike 3's
_EDGE_NAMES = ("switch_edge", "switch_drain", "switch_records", "switch_count", "switch_drain_size",
               "switch_record_size", "switch_level_via", "switch_level_before") + EDGE_VALUES
_EDGE_LINE = re.compile(r"^(#.*?)?\b(site|data|value)\s+(%s)\b" % "|".join(_EDGE_NAMES))
_EDGE_HOW = re.compile(r"^#\s+(%s):" % "|".join(_EDGE_NAMES))


def switch_edge_point(t):
    """The 64-bit switch drain's per-edge point (PAD-1322). Spike 3's drain makes no per-switch call: it walks the
    list of switch records the node boards' reader queued and, for each, writes the edge's level into the record
    (`strb wL, [xR, #level]`), skips its id table refresh for switch 0 (`cbz wId, X`), and at X loads the
    descriptor (`ldr xD, [xR, #desc]`) and its two u16 flag words, the handler bits tested at bit 11 / 10 and the
    other at bit 1 / 2; the id is the `ldrh wId, [xR, #id]` before. X is the point every edge passes after its level
    is written and before the handler bits are read. Also the mode mask the drain tests, through its GOT slot
    (`ldrh wA, [xM]`, then `tst wFlags, wA`). -> dict, or None when the shape is not there exactly once."""
    W, base, hits = t.words, t.tva, []
    for i in range(24, len(W) - 1):
        w = W[i]
        if (w & 0xFFC00000) != 0x39000000:                          # strb wt, [xn, #imm]
            continue
        c = W[i + 1]
        if (c & 0xFF000000) != 0x34000000:                          # cbz w
            continue
        rn, rid = (w >> 5) & 31, c & 31
        x = base + 4 * (i + 1) + 4 * sext((c >> 5) & 0x7FFFF, 19)
        j = (x - base) // 4
        if not (i < j < len(W) - 20):
            continue
        ld = W[j]
        if (ld & 0xFFC00000) != 0xF9400000 or ((ld >> 5) & 31) != rn:   # ldr xd, [xR, #imm*8]
            continue
        rd = ld & 31
        hs = [(W[j + k] & 31, ((W[j + k] >> 10) & 0xFFF) * 2) for k in (1, 2)
              if (W[j + k] & 0xFFC00000) == 0x79400000 and ((W[j + k] >> 5) & 31) == rd]
        if len(hs) != 2:
            continue
        flags = pol = freg = None
        for k in range(3, 16):
            b = W[j + k]
            if (b & 0x7E000000) != 0x36000000:                      # tbz / tbnz
                continue
            bit = (((b >> 31) & 1) << 5) | ((b >> 19) & 31)
            for r, off in hs:
                if (b & 31) == r and bit in (10, 11):
                    flags, freg = off, r
                elif (b & 31) == r and bit in (1, 2):
                    pol = off
        idat = next((((W[i - k] >> 10) & 0xFFF) * 2 for k in range(1, 24)
                     if (W[i - k] & 0xFFC00000) == 0x79400000 and ((W[i - k] >> 5) & 31) == rn
                     and (W[i - k] & 31) == rid), None)
        if flags is None or pol is None or idat is None or a64_pc_bound(ld):
            continue
        # the mode mask: a GOT load into xM earlier in the drain, `ldrh wA, [xM]` then `tst wFlags, wA`
        got, mask = {}, None
        for k in range(max(0, i - 64), j + 24):
            a, v = base + 4 * k, W[k]
            p = _adrp(a, v)
            if p:
                got[p[0]] = ("page", p[1])
            elif (v & 0xFFC00000) == 0xF9400000 and got.get((v >> 5) & 31, ("",))[0] == "page":
                slot = got[(v >> 5) & 31][1] + ((v >> 10) & 0xFFF) * 8
                if slot in t.ptr:
                    got[v & 31] = ("ptr", t.ptr[slot])
            elif k > j and (v & 0xFFFFFC00) == 0x79400000 and got.get((v >> 5) & 31, ("",))[0] == "ptr":
                nxt = W[k + 1:k + 4]
                if any((n & 0xFF20001F) == 0x6A00001F and ((n >> 5) & 31) in (freg, v & 31)
                       and ((n >> 16) & 31) in (freg, v & 31) for n in nxt):
                    mask = got[(v >> 5) & 31][1]
        hits.append({"site": x, "reg": rn, "id_at": idat, "level_at": (w >> 10) & 0xFFF, "desc_via": ((ld >> 10) & 0xFFF) * 8,
                     "flags_at": flags, "polarity_at": pol, "mode_mask": mask})
    return hits[0] if len(hits) == 1 else None


def a64_pc_bound(w):
    """adrp / adr / a literal load / a branch: an instruction the 64-bit hook cannot move as it is"""
    return ((w & 0x1F000000) == 0x10000000 or (w & 0x3B000000) == 0x18000000 or (w & 0x7C000000) == 0x14000000
            or (w & 0xFE000000) == 0x54000000 or (w & 0x7E000000) in (0x34000000, 0x36000000))


def edge_lines(t, body, placed, notes):
    """PAD-1322: the drain's per-edge point and the record layout, read off this program's own code, in place of
    whatever a draft carried over for switch_edge (Spike 2's per-switch call and its 32-bit tables)."""
    e = switch_edge_point(t)
    keep, cut = [], None
    for l in body:
        if _EDGE_LINE.match(l) or _EDGE_HOW.match(l):
            cut = len(keep) if cut is None else cut
            continue
        keep.append(l)
    for n in _EDGE_NAMES:
        placed.pop(n, None)
        placed.pop("data:" + n, None)
    at = next((k for k, l in enumerate(keep) if l.startswith("# ---- globals")), cut if cut is not None else len(keep))
    while at > 0 and keep[at - 1] == "":
        at -= 1
    if not e:
        block = ["# site %-16s NOT PLACED: the 64-bit drain's per-edge point is not there once (PAD-1322)"
                 % "switch_edge"]
    else:
        block = ["#   switch_edge: the 64-bit drain's per-edge point - every switch edge passes it after its level is "
                 "written, before its handler bits are read (PAD-1322)",
                 "site %-16s 0x%08x 0x%08x 0x%08x" % ("switch_edge", e["site"], t.u32(e["site"]), t.u32(e["site"] + 4))]
        block += ["value %-25s %s    # read off the drain's own code (PAD-1322)"
                  % (n, e["reg"] if n == "switch_record_reg" else "0x%x" % e[n[len("switch_"):]]) for n in EDGE_VALUES]
        placed["switch_edge"] = e["site"]
        mm = placed.get("data:mode_mask")
        if e["mode_mask"] and mm is None:
            block.append("data %-22s 0x%08x   # the drain's own (PAD-1322)" % ("mode_mask", e["mode_mask"]))
            placed["data:mode_mask"] = e["mode_mask"]
        elif e["mode_mask"] and mm != e["mode_mask"]:
            notes.append("data mode_mask: 0x%x written, the switch drain tests 0x%x" % (mm, e["mode_mask"]))
    keep[at:at] = block
    body[:] = keep
    return e


# ---- PAD-1328: the attract sequencer (the 64-bit counterpart of pinball_decryptor/plugins/stern/portattract.py) -----
#: entries the runtime looks at (pad_mode_runtime.c: count <= 256; portattract.MAX_ENTRIES on Spike 2)
ATTRACT_MAX = 256


def _attract_run(t, entry, stride, page_at):
    """how many entries in a row from `entry` hold a page that is code and a test that is 0 or code (each a
    pointer-sized word: a RELATIVE relocation's target, or 0)"""
    k = 0
    while k < ATTRACT_MAX:
        va = entry + stride * k
        if t.off(va + stride - 1) is None or va in t.holes:
            break
        page = t.ptr.get(va + page_at)
        test = t.ptr.get(va)
        raw = t.b[t.off(va):t.off(va) + 8]
        if page is None or not t.in_text(page) or not (test is None and raw == b"\0" * 8 or
                                                       test is not None and t.in_text(test)):
            break
        k += 1
    return k


def attract_sequencer(t, proc_sleep):
    """the attract sequencer's table, read off a 64-bit program: {"entry", "size", "page_at", "count", "create",
    "sleep", "at", "seconds_at"} or None when the program has not exactly one.

    The sequencer starts each page as a child process and stamps the cycle on it, as on Spike 2 (portattract.py):
        ldr x0, [xE, #8] ; mov w1, #0 ; bl <child create> ; cbz x0 ; str wC, [x0, #0x108] ; ... mov w0, #1 ; bl <sleep>
    with xE an entry of a table whose tests it calls through `blr x1` in the same function. Star Wars ELG 1.10: 28
    entries of 16 bytes {test, page} at 0x6a45c0, Walking Dead Remastered and Star Wars 2025 the same shape; Pokemon
    LE 0.82: 24 bytes {test, page, float seconds} (its page process gets seconds x 60 at +0x110). The words are
    RELATIVE relocations (the file holds 0): the runtime reads them moved by the PIE's load address."""
    found = {}
    for i, w in enumerate(t.words):
        if (w & 0xFC000000) != 0x94000000:
            continue
        a = t.tva + 4 * i
        pre = [t.words[j] for j in range(max(0, i - 5), i)]
        page_at = None
        for x in pre:
            ls = _ls(x)
            if ls and ls[0] == "ldr" and ls[1] == 0 and 8 <= ls[3] <= 16:
                page_at = ls[3]
        if page_at is None or not any(x in (0x52800001, 0xD2800001) for x in pre):     # mov w1, #0 / mov x1, #0
            continue
        post = t.words[i + 1:i + 14]
        stamp = None
        for x in post[:6]:
            ls = _ls(x)
            if ls and ls[0] in ("strw", "str") and ls[2] == 0 and ls[3] >= 0x100:
                stamp = ls[3]
                break
            if (x & 0xFFC003E0) == 0xBD000000 and ((x >> 10) & 0xFFF) * 4 >= 0x100:     # str s, [x0, #imm]
                stamp = ((x >> 10) & 0xFFF) * 4
                break
        if stamp is None:
            continue
        if not any(_bl(a + 4 * (k + 1), x) == proc_sleep for k, x in enumerate(post)):
            continue
        f = func_of(t, a)
        if f is None or a - f > 4 * 1200:
            continue
        body = [t.words[j] for j in range((f - t.tva) // 4, i)]

        def tests(ws):                                                  # blr x1: the entry's test
            return any((x & 0xFFFFFC1F) == 0xD63F0000 and ((x >> 5) & 31) == 1 for x in ws)
        if not tests(body):
            # Star Wars ELG 1.10 calls the tests in a helper of its own (0x138080: the next entry shown)
            subs = {_bl(f + 4 * k, x) for k, x in enumerate(body)} - {None}
            if not any(tests([x for _a, x in _window(t, s, 120)]) for s in subs if t.in_text(s)):
                continue
        bases = set()
        for _a, _w, reg in _regs_walk(t, f, (a - f) // 4 + 1):
            for kind, v in reg.values():
                if kind in ("a", "g"):
                    bases.add(v)
        best = None
        for b in sorted(bases):
            if not t.is_data(b):
                continue
            for stride in (16, 24, 32):
                run = _attract_run(t, b, stride, page_at)
                if run >= 4 and (best is None or run > best[2]):
                    best = (b, stride, run)
        if best is None:
            continue
        b, stride, run = best
        # a fixed count: the index's `cmp wI, #imm` (Star Wars 2025 LE: 0xb6), when it fits the run
        cmps = [((x >> 10) & 0xFFF) for x in body if (x & 0xFFC0001F) == 0x7100001F and 8 <= ((x >> 10) & 0xFFF) < 255]
        count = max(cmps) + 1 if cmps and max(cmps) + 1 <= run else run
        if not 2 <= count <= ATTRACT_MAX:
            continue
        secs = None
        if stride >= 24:
            ok = 0
            for k in range(count):
                v = t.u32(b + stride * k + 16)
                fv = struct.unpack("<f", struct.pack("<I", v or 0))[0]
                ok += 0 <= fv < 600
            secs = 16 if ok == count else None
        found[(b, stride, count)] = {"entry": b, "size": stride, "page_at": page_at, "count": count,
                                     "create": a + 4 * sext(w & 0x3FFFFFF, 26), "sleep": proc_sleep, "at": a,
                                     "stamp": stamp, "seconds_at": secs}
    return next(iter(found.values())) if len(found) == 1 else None


def attract_pages(t, s):
    """the page functions of the sequencer's table, in order (0 where an entry has none)"""
    return [t.ptr.get(s["entry"] + s["size"] * k + s["page_at"], 0) for k in range(s["count"])]


def attract_show(t, s):
    """(player_advance, scene_show) the attract pages that play a clip put the scene on the glass with, each frame,
    or None - read off the pages' own frame loop (Star Wars ELG 1.10's VideoSurface pages, 0x138330):
        mov x0, xP ; bl <player_advance(player, float ms)> ; mov w1, #3 ; mov x0, xP ; bl <scene_show(player, 3)>
    the same pair Aerosmith's OilProjectorLoop page calls on Spike 2 (portattract.show_lines)."""
    votes = Counter()
    seen = set()

    def look(f, depth):
        if not f or f in seen or not t.in_text(f):
            return
        seen.add(f)
        ws = list(_window(t, f, 700))
        for k in range(len(ws) - 4):
            (a0, w0), (a1, w1), (a2, w2), (a3, w3), (a4, w4) = ws[k:k + 5]
            mv = _mov_reg(w0)
            if (mv and mv[0] == 0 and _bl(a1, w1) and w2 == 0x52800061 and _mov_reg(w3) == mv and _bl(a4, w4)):
                votes[(_bl(a1, w1), _bl(a4, w4))] += 1
        if depth:
            for a, w in ws:
                b = _bl(a, w) or _b(a, w)
                if b and abs(b - f) < 0x20000:
                    look(b, depth - 1)
    for p in attract_pages(t, s):
        look(p, 1)
    return votes.most_common(1)[0][0] if votes else None


#: the attract lines are always the target's own, read by attract_lines - never carried over from a reference port
_ATTRACT_NAMES = ("attract_table", "attract_entry_size", "attract_page_at", "attract_count", "attract_sleep",
                  "attract_show", "player_advance")
_ATTRACT_LINE = re.compile(r"^(#.*?)?\b(site|data|value)\s+(%s)\b" % "|".join(_ATTRACT_NAMES))
_ATTRACT_HOW = re.compile(r"^#\s+(%s):|^# ---- attract \(PAD-1328\)|^#   the attract pages' own clip loop"
                          % "|".join(_ATTRACT_NAMES))


def drop_carried_attract(body, placed, missing=None):
    """PAD-1328: take out of a draft what the matcher carried over of the reference port's attract lines (the
    reference's table and pages are its own game's); attract_lines reads the target's"""
    body[:] = [l for l in body if not (_ATTRACT_LINE.match(l) or _ATTRACT_HOW.match(l))]
    for n in _ATTRACT_NAMES:
        placed.pop(n, None)
        placed.pop("data:" + n, None)
    if missing is not None:
        missing[:] = [n for n in missing if n not in _ATTRACT_NAMES]


def attract_lines(t, placed):
    """PAD-1328: the port lines for the program's attract table ([] when it has none the runtime can use): the same
    names as Spike 2's (portattract.lines), the table's words pointer-sized; and the scene show an item's page puts
    the video bank's scene on the glass with (portattract.show_lines), when its pages have one"""
    ps = placed.get("proc_sleep")
    s = attract_sequencer(t, ps) if ps else None
    if s is None:
        return []
    placed["data:attract_table"] = s["entry"]
    out = ["# ---- attract (PAD-1328): the attract mode's page table, read off this program's sequencer (its child "
           "create at 0x%x); an owner's attract items play between its pages ----" % s["at"],
           "data  attract_table       0x%08x   # %d entries {test, page%s}, 8-byte pointers (RELATIVE)"
           % (s["entry"], s["count"], ", float seconds" if s["seconds_at"] else ""),
           "value attract_entry_size  %d" % s["size"],
           "value attract_page_at     %d" % s["page_at"],
           "value attract_count       %d" % s["count"],
           "site  attract_sleep       0x%08x 0x%08x 0x%08x" % (s["sleep"], t.u32(s["sleep"]), t.u32(s["sleep"] + 4))]
    sh = attract_show(t, s)
    if sh:
        adv, show = sh
        out += ["#   the attract pages' own clip loop: player_advance(player, ms) ; scene_show(player, 3) each frame",
                "site  attract_show        0x%08x 0x%08x 0x%08x" % (show, t.u32(show), t.u32(show + 4))]
        if "player_advance" not in placed:
            out.append("site  player_advance      0x%08x 0x%08x 0x%08x" % (adv, t.u32(adv), t.u32(adv + 4)))
            placed["player_advance"] = adv
        placed["attract_show"] = show
    return out


# ---- PAD-1328: the cabinet's expression lights on a Spike 3 program --------------------------------------------
def cabinet_a64(t, lamp_group):
    """the cabinet's expression lights of a 64-bit program, as lampmap.cabinet's dicts (placed on the cabinet drawing),
    or []. Each colour channel of a Spike 3 pixel is a lamp of its own in the device table (`SPEAKER L 1-R`, `-G`,
    `-B`), and a light's id is its rank among the table's lamps + 1 (every 3-light record of the light table names
    one fixture's R, G and B that way on all six titles with cabinet lights); a pixel is the light-table record
    holding its three channels."""
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    from pinball_decryptor.plugins.stern import lampmap as LM
    calls = [b for a, w in _window(t, lamp_group, 40) for b in [_bl(a, w)] if b] if lamp_group else []
    lists = light_lists(t, calls[1]) if len(calls) > 1 else []
    devs = [d for d in device_records(t) if d[3] == 3]
    order, out = {"R": 0, "G": 1, "B": 2}, []
    for k, ids in enumerate(lists):
        if len(ids) != 3 or not all(0 < i <= len(devs) for i in ids):
            continue
        names = [devs[i - 1][0].upper() for i in ids]
        m = [re.match(r"^(.*)-([RGB])$", n) for n in names]
        if not all(m) or len({x.group(1) for x in m}) != 1 or sorted(x.group(2) for x in m) != ["B", "G", "R"]:
            continue
        name = m[0].group(1)
        role = LM.cabinet_role(name)
        if not role:
            continue
        rgb = [0, 0, 0]
        for i, x in zip(ids, m):
            rgb[order[x.group(2)]] = i
        g, idx = devs[rgb[0] - 1][1:3]
        out.append(dict(lamp=k, name=name, lights=rgb, role=role[0], side=role[1], n=role[2], group=g, index=idx,
                        x=0, y=0))
    return LM.place_cabinet(out)


def cabinet_lines_a64(t, placed):
    """PAD-1328: the port's `cablamp` lines, read off this program's own device and light tables ([] with no cabinet)"""
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    from pinball_decryptor.plugins.stern import lampmap as LM
    cab = cabinet_a64(t, placed.get("lamp_group"))
    if not cab:
        return []
    lines = LM.cabinet_lines(None, cab=cab)
    lines[0] = lines[0].replace("read by lamp_map.py", "read off the 64-bit device and light tables (PAD-1328)")
    return lines


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
    body, missing, placed, later, later_at = [], [], {}, [], {}
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
        if re.match(r"show_\d+$", name):
            continue
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
            later_at[out] = b
    snd = sound_engine(tgt, placed) if tgt.a64 else {"site": {}, "data": {}, "why": []}
    for name, b in snd["site"].items():
        if name in placed or site_ok(tgt, b):
            continue
        how = {"sound_worker": "the callout's call", "sound_resolve": "the worker's call that takes a stack slot",
               "sound_lookup": "the call after the record key's bank bits"}[name]
        mark = "# site %-16s NOT PLACED" % name
        at = next((k for k, l in enumerate(body) if l.startswith(mark)), len(body))
        body[at:at + 1] = ["#   %s: %s (PAD-1282)" % (name, how),
                           "site %-16s 0x%08x 0x%08x 0x%08x" % (name, b, tgt.u32(b), tgt.u32(b + 4))]
        placed[name] = b
        if name in missing:
            missing.remove(name)
    lit = light_engine(ref, lines, tgt, placed) if tgt.a64 else {"site": {}, "data": {}, "value": {}, "show": [],
                                                                  "lamp": [], "why": []}
    for name, b in lit["site"].items():
        if name == "proc_exit" or name in placed:
            continue
        mark = "# site %-16s NOT PLACED" % name
        at = next((k for k, l in enumerate(body) if l.startswith(mark)), len(body))
        body[at:at + 1] = ["#   %s: read off the lamp layer's code (PAD-1283)" % name,
                           "site %-16s 0x%08x 0x%08x 0x%08x" % (name, b, tgt.u32(b), tgt.u32(b + 4))]
        placed[name] = b
        if name in missing:
            missing.remove(name)
    scn = scene_engine(ref, lines, tgt, later_at) if tgt.a64 else {"site": {}, "data": {}, "value": {},
                                                                     "scene": [], "screens": False, "clips": False,
                                                                     "why": []}
    carry = (SCREEN_SITES if scn["screens"] else ()) + (CLIP_SITES if scn["clips"] else ())
    for name in carry:                        # the matcher's placements, now that their features are 64-bit
        b = later_at[name]
        mark = "# not carried yet (its feature is 32-bit): site %-16s 0x%08x" % (name, b)
        at = next(k for k, l in enumerate(body) if l.startswith(mark))
        body[at:at + 1] = ["#   %s: matched (PAD-1284)" % name, body[at][len("# not carried yet (its feature is 32-bit): "):]]
        placed[name] = b
        later.remove(name)
    how3 = {"dynamic_cast": "the PLT stub of __dynamic_cast",
            "resource_get": "the scene lookup's first call, on the resource manager",
            "surface_set_video": "the surface call before surface_play",
            "surface_position": "the game's progress read: position, duration, then surface_state",
            "surface_duration": "the game's progress read: position, duration, then surface_state"}
    need = {"dynamic_cast": scn["screens"] or scn["clips"], "resource_get": scn["screens"] or scn["clips"],
            "surface_set_video": scn["clips"], "surface_position": scn["clips"], "surface_duration": scn["clips"]}
    for name, b in scn["site"].items():
        if not need[name] or name in placed:
            continue
        mark = "# site %-16s NOT PLACED" % name
        at = next((k for k, l in enumerate(body) if l.startswith(mark)), len(body))
        body[at:at + 1] = ["#   %s: %s (PAD-1284)" % (name, how3[name]),
                           "site %-16s 0x%08x 0x%08x 0x%08x" % (name, b, tgt.u32(b), tgt.u32(b + 4))]
        placed[name] = b
        if name in missing:
            missing.remove(name)
    # PAD-1285: a mode's multiball, held coils and blocks (the matcher's plain calls carried, the rest read off the code)
    gfl = dict(later_at)
    if tdata.get("game_flags", (None,))[0]:
        gfl["data:game_flags"] = tdata["game_flags"][0]
    pe = play_engine(ref, lines, tgt, gfl, placed) if tgt.a64 else {"site": {}, "data": {}, "value": {}, "text": [],
                                                                     "carry": [], "flag_of": {}, "why": []}
    pre = "# not carried yet (its feature is 32-bit): "
    for name in pe["carry"]:
        b = later_at[name]
        at = next(k for k, l in enumerate(body) if l.startswith(pre + "site %-16s 0x%08x" % (name, b)))
        body[at:at + 1] = ["#   %s: matched (PAD-1285)" % name, body[at][len(pre):]]
        placed[name] = b
        later.remove(name)
    how5 = {"coil_take": "the device take (obj, ticks): waits for its control word, adds the exit hook, keeps the "
                         "process's id",
            "coil_give": "the device give (obj, flag): clears the control word, takes the exit hook off, calls the "
                         "object's update"}
    for name, b in pe["site"].items():
        if name in placed and name not in later:
            continue
        at = next((k for k, l in enumerate(body) if l.startswith("# site %-16s NOT PLACED" % name)
                   or l.startswith(pre + "site %-16s " % name)), len(body))
        how = how5.get(name) or "the start that sets the game's flag %d" % pe["flag_of"].get(name, 0)
        body[at:at + 1] = ["#   %s: %s (PAD-1285)" % (name, how),
                           "site %-16s 0x%08x 0x%08x 0x%08x" % (name, b, tgt.u32(b), tgt.u32(b + 4))]
        placed[name] = b
        for lst in (missing, later):
            if name in lst:
                lst.remove(name)
    # PAD-1284: a placed site no feature uses on the Spike 2 port of this build either says why, not "32-bit"
    rsites = {t[1] for k, t, s in lines if k == "site" and len(t) >= 3}
    rdat = {t[1] for k, t, s in lines if k == "data" and len(t) >= 3}
    rvals = {t[1] for k, t, s in lines if k == "value" and len(t) >= 2}
    idle = {}
    if not {"award_message_at", "award_value_at", "award_count_at"} <= rvals:
        idle["award_screen"] = "the award screen needs award_message_at / _value_at / _count_at, which it lacks"
    if "display_effects" not in rdat or not {"display_host", "display_now_at", "display_priority_at"} <= rvals:
        for n in ("display_effect_start", "display_effect_next", "display_priority_now"):
            idle[n] = "display priority needs data display_effects and the display_host / _now_at / _priority_at values"
    if not {"clip_play", "video_player", "video_surface"} <= rsites:
        for n in ("display_draw", "player_advance"):
            idle[n] = "the clip_play clip path it belongs to is not this title's (its clips are the surface's)"
    # PAD-1285 / PAD-1322: the 64-bit switch drain makes no per-switch call (Spike 2's switch_edge); its per-edge point,
    # read off this program's own code, is written by edge_lines (below)
    if (tgt.a64 and "ball_end" not in placed and "hook_dispatch" in placed
            and any(k == "event" and t[1] == "ball_end" for k, t, s in lines)):
        at = next((k for k, l in enumerate(body) if l.startswith("# site %-16s NOT PLACED" % "ball_end")), None)
        if at is not None:
            body[at] = ("# site %-16s NOT NEEDED: the end of a ball is the bus's event (value ball_end_event, through "
                        "hook_dispatch) - the Spike 2 site is that event's handler (PAD-1285)" % "ball_end")
    for k, l in enumerate(body):
        m = re.match(r"# not carried yet \(its feature is 32-bit\): (site (\S+) .*)$", l)
        if m and m.group(2) in idle:
            body[k] = "# not carried - no feature uses it on the Spike 2 port either (%s): %s" % (idle[m.group(2)],
                                                                                              m.group(1))
    for name, why3 in (("string_new", "NOT NEEDED: the 64-bit program's strings are the C++11 ABI and it imports no "
                                      "constructor; the runtime builds them itself (PAD-1284)"),
                       ("surface_seek", "NOT PLACED: the 64-bit video surface has no seek - its clock is set by the "
                                        "player's own decoder thread only (PAD-1284)")):
        if scn["screens"] or scn["clips"]:
            mark = "# site %-16s NOT PLACED" % name
            at = next((k for k, l in enumerate(body) if l.startswith(mark)), None)
            if at is not None:
                body[at] = "# site %-16s %s" % (name, why3)
                if name == "string_new" and name in missing:
                    missing.remove(name)
    if lit["show"]:
        body += ["", "# ---- the game's own light shows (PAD-1283): the Spike 2 port's shows, each at the same record of",
                 "# the show table on both builds (its body, kind and flags), renumbered from 1; played as process show_proc",
                 "# (an id this program never uses either), its lamp groups freed as it ends (lamp_free_owner) ----"]
        body += lit["show"]
    # data
    body += ["", "# ---- globals: data <name> <address> ----"]
    for name, A in data_lines.items():
        b, agree, of = tdata[name]
        out = "scores" if name == "scores32" and "score_add" in placed else name
        if name in snd["data"]:
            body.append("data %-22s 0x%08x   # read in the sound engine's own code (PAD-1282)" % (name, snd["data"][name]))
            placed["data:" + name] = snd["data"][name]
            continue
        if name in lit["data"]:
            body.append("data %-22s 0x%08x   # read in the lamp layer's / processes' own code (PAD-1283)" % (
                name, lit["data"][name]))
            placed["data:" + name] = lit["data"][name]
            continue
        if name in pe["data"]:
            body.append("data %-22s 0x%08x   # read off the program's own code (PAD-1285)" % (name, pe["data"][name]))
            placed["data:" + name] = pe["data"][name]
            continue
        if name in scn["data"] and (scn["screens"] or scn["clips"]):
            body.append("data %-22s 0x%08x   # read in the game's own scene lookups (PAD-1284)" % (
                name, scn["data"][name]))
            placed["data:" + name] = scn["data"][name]
            continue
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
    sound_vals = dict(SOUND_VALUES) if "data:sound_channels" in placed else {}
    for name, b in lit["data"].items():
        if "data:" + name not in placed:
            body.append("data %-22s 0x%08x   # read in the lamp layer's / processes' own code (PAD-1283)" % (name, b))
            placed["data:" + name] = b
    lit_vals = {k: v for k, v in lit["value"].items() if k not in LIGHT_VALUES_UNUSED}
    scn_vals = {k: v for k, v in scn["value"].items()
                if (k == "surface_playing" and scn["clips"]) or (k != "surface_playing" and (scn["screens"] or
                                                                                            scn["clips"]))}
    for k, t, s in lines:
        if k == "value" and t[1] not in sound_vals and not t[1].startswith("countdown_") and t[1] not in lit_vals \
                and t[1] not in scn_vals and t[1] not in pe["value"] and t[1] not in pe.get("books", {}) \
                and not (lit["show"] and re.match(r"show_secs_\d+$", t[1])):
            body.append(s if t[1] in VALUES_PROVEN else "# not carried (64-bit layout, measure it): " + s.strip())
    for name, v in sound_vals.items():
        body.append("value %-25s %d    # the 64-bit sound engine's (PAD-1282)" % (name, v))
    for name, v in lit_vals.items():
        body.append("value %-25s %s    # read off the program's own code (PAD-1283)" % (
            name, ("0x%x" % v) if name == "event_show_flag" else v))
    body += ["# PAD-1283: %s" % w for w in lit["why"]]
    for name, v in scn_vals.items():
        body.append("value %-25s 0x%x    # read off the program's own code (PAD-1284)" % (name, v))
    body += ["# PAD-1284: %s" % w for w in scn["why"]]
    for name, v in pe["value"].items():
        body.append("value %-25s %s    # read off the program's own code (PAD-1285)" % (
            name, ("0x%x" % v) if name == "multiball_arg3" else v))
    for name, v in pe.get("books", {}).items():
        body.append("value %-25s %d    # the game's flag of the same name on Spike 3 (PAD-1286)" % (name, v))
    body += ["# PAD-1285: %s" % w for w in pe["why"]]
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
    co = [(t, s) for k, t, s in lines if k == "callout" and len(t) >= 3]
    shift = None
    if co and "callout" in placed:
        rco = next((int(t[2], 16) for k, t, s in lines if k == "site" and len(t) >= 3 and t[1] == "callout"), None)
        shift, hits, of = request_shift(ref, rco, tgt, placed["callout"]) if rco else (None, 0, 0)
        if shift is not None:
            body += ["", "# ---- callouts: request ids + %d on Spike 3 (%d of the %d constant ids Spike 2's code passes to "
                     "the callout are there at + %d) ----" % (shift, hits, of, shift)]
            body += ["callout %-19s %d" % (t[1], int(t[2], 0) + shift) for t, s in co]
            body += [s for k, t, s in lines if k == "value" and len(t) > 1 and t[1].startswith("countdown_")
                     and not s.lstrip().startswith("#")]
    if lit["lamp"]:
        body += ["", "# ---- lamps (PAD-1283): the Spike 2 port's lamp lines by name - a lamp of Spike 3's device table (its",
                 "# I/O group and index written from it), the same light ids one of the light table's records holds ----"]
        body += lit["lamp"]
    if scn["scene"]:
        body += ["", "# ---- scenes (PAD-1284): a mode's screen goes in hud, its clip on video_bank's surface - the same ids",
                 "# the program names ----"]
        body += scn["scene"]
    if pe["text"]:
        body += ["", "# ---- PAD-1285: a held coil's names and board address, the game's modes a mode keeps from starting;",
                 "# PAD-1286: the game's modes whose books a mode of ours may wait on (done_name) ----"]
        body += pe["text"]
    pe_text = {l.split()[1] for l in pe["text"]}
    tx = [s for k, t, s in lines if k == "text" and len(t) > 1 and t[1].startswith("example_")]
    if tx:
        body += ["", "# ---- text ----"] + tx
    scn_names = {l.split()[1] for l in scn["scene"]}
    rest = Counter(k for k, t, s in lines if (k == "shot" or (k == "scene" and t[1] not in scn_names) or (k == "lamp" and not lit["lamp"])) or
                   (k == "callout" and shift is None) or (k == "text" and not t[1].startswith("example_") and
                                                          t[1] not in pe_text and
                                                          not (lit["show"] and re.match(r"show_(name|kind)_\d+$", t[1]))))
    if rest:
        body += ["", "# not carried (to measure on Spike 3): " + ", ".join("%d %s" % (n, k) for k, n in sorted(rest.items()))]
    edge_notes = []
    if tgt.a64:
        edge_lines(tgt, body, placed, edge_notes)
        body += ["# " + n for n in edge_notes]
        if "switch_edge" in placed:
            missing = [n for n in missing if n not in _EDGE_NAMES]
            later = [n for n in later if n not in _EDGE_NAMES]
    core_missing = [grp for grp in CORE if not any(n in placed for n in grp) and not
                    (grp == ("ball_end", "hook_dispatch") and "ball_end_event" in placed)]
    core_missing += [grp for grp in CORE_DATA if not any("data:" + n in placed for n in grp)]
    return "\n".join(head + body) + "\n", M, core_missing, missing + later


# ---- PAD-1287: a Spike 3 port from another Spike 3 title's proven port ---------------------------------------
# Every Spike 3 program is the same 64-bit framework (sound engine, lamp layer, processes, event bus, switch drain,
# scores, the Insider agent) built with the same compiler around one game's rules, so a framework function's
# instructions on one title are the same instructions on another, give or take its addresses and offsets: the
# reference's port carries over by LINING UP the paired functions' instructions, not just by pairing functions. What
# a port names of the GAME (its shows, lamps tied to shots, callouts, scenes, held coils, the game's modes) is the
# reference's own and is never carried; the switch lines are made from the target's own device table.

#: a reference site that is its game's own content, never another title's
GAME_SITE = re.compile(r"(show_\d+|block_start_\d+)$")
#: reference values that are its game's own (its shows, callouts, held coils, mode flags, and its mode books: a
#: place_flag / done_flag is the flag one of the REFERENCE game's modes sets - PAD-1288: on Fallout the same numbers
#: line up in the framework's flag code but name none of its modes; PAD-1289: Star Wars ELG's 66 / 68 turned up at
#: lined-up instructions on Pokemon LE, but they are the flags of ELG's own modes)
GAME_VALUE = re.compile(r"(show_(secs|name|kind|call)_\d+|show_proc|countdown_\w+|mode_flag_\d+|right_gate_\w+|"
                        r"magnet_proc|game_flags_at|block_\w+|place_flag_\w+|done_flag_\w+|done_audit_\d+|"
                        r"challenge_\w+|comp_menu_\w+)$")   # PAD-1327: a start menu's and the champion framework's numbers are measured per program
#: sites only ever armed together: one placed without the other is written as a comment (PAD-1288: Fallout's
#: coil_give lines up, its coil_take has no counterpart, and the runtime arms held coils on both or neither)
SITE_PAIRS = (("coil_take", "coil_give"),)
GAME_DATA = re.compile(r"right_gate_obj$")
#: the screen and clip features name the title's own hud / video bank scenes (per game): their sites, globals and
#: values are placed and written as comments until a title's scenes are named
SCREEN_CLIP_SITES = SCREEN_SITES + CLIP_SITES + ("dynamic_cast", "resource_get", "surface_set_video",
                                                  "surface_duration", "surface_position", "string_new", "surface_seek")
SCREEN_CLIP_DATA = ("resource_manager", "typeinfo_resource", "typeinfo_scene_player")
SCREEN_CLIP_VALUES = ("scene_player_scene", "node_visible_vfn", "surface_playing")
#: a placed function must be at least this alike its reference (the share of instructions that line up)
SIM_MIN = 0.75


def _loose(w):
    """one 64-bit instruction with its addresses and immediates masked (two titles' builds of one source line up on
    it): pc-relative targets, load/store offsets, add/sub and move immediates, logical masks"""
    if (w & 0x7C000000) == 0x14000000:                   # b, bl
        return w & 0xFC000000
    if (w & 0x1F000000) == 0x10000000:                   # adr, adrp
        return w & 0x9F00001F
    if (w & 0xFF000010) == 0x54000000 or (w & 0x7E000000) == 0x34000000 or (w & 0x3B000000) == 0x18000000:
        return w & 0xFF00001F                            # b.cond, cbz/cbnz, ldr literal
    if (w & 0x7E000000) == 0x36000000:                   # tbz/tbnz: the bit is kept
        return w & 0xFFF8001F
    if (w & 0x3B000000) == 0x39000000:                   # ldr/str, unsigned offset
        return w & ~(0xFFF << 10)
    if (w & 0x3B200C00) == 0x38000000:                   # ldur/stur
        return w & ~(0x1FF << 12)
    if (w & 0x3A000000) == 0x28000000:                   # ldp/stp
        return w & ~(0x7F << 15)
    if (w & 0x1F000000) == 0x11000000:                   # add/sub (and cmp/cmn) immediate
        return w & ~(0x1FFF << 10)
    if (w & 0x1F800000) in (0x12800000, 0x12000000):    # movz/movn/movk (hw kept), logical immediate
        return w & ~(0xFFFF << 5) if (w & 0x1F800000) == 0x12800000 else w & ~(0x1FFF << 10)
    return w


def _bitmask(n, immr, imms, size):
    ln = ((n << 6) | (~imms & 0x3F)).bit_length() - 1
    if ln < 1:
        return None
    es = 1 << ln
    s, r = imms & (es - 1), immr & (es - 1)
    if s == es - 1:
        return None
    el = (1 << (s + 1)) - 1
    el = ((el >> r) | (el << (es - r))) & ((1 << es) - 1)
    return sum(el << (k * es) for k in range(size // es))


def _imm(w):
    """the immediate _loose masks, decoded (a load/store's byte offset, an add's or a move's value, a logical mask),
    or None"""
    if (w & 0x3B000000) == 0x39000000:
        simd = (w >> 26) & 1
        return ((w >> 10) & 0xFFF) << (4 if simd and (w >> 23) & 1 else w >> 30)
    if (w & 0x3B200C00) == 0x38000000:
        return sext((w >> 12) & 0x1FF, 9)
    if (w & 0x3A000000) == 0x28000000:
        return sext((w >> 15) & 0x7F, 7) << ((2 + (w >> 31)) if not (w >> 26) & 1 else 2 + ((w >> 30) & 3))
    if (w & 0x1F000000) == 0x11000000:
        return ((w >> 10) & 0xFFF) << (12 if w & 0x400000 else 0)
    if (w & 0x1F800000) == 0x12800000 and (w >> 29) & 3 in (2, 3):     # movz, movk
        return ((w >> 5) & 0xFFFF) << (16 * ((w >> 21) & 3))
    if (w & 0x1F800000) == 0x12000000:
        return _bitmask((w >> 22) & 1, (w >> 16) & 0x3F, (w >> 10) & 0x3F, 64 if w >> 31 else 32)
    return None


class Aligner:
    """the paired functions' instructions, lined up (difflib on the loose shapes): word index on the reference ->
    word index on the target, and how alike the two are"""

    def __init__(self, ref, tgt):
        self.r, self.t = ref, tgt
        self.lr, self.lt = [_loose(x) for x in ref.words], [_loose(x) for x in tgt.words]
        self.cache = {}

    def _span(self, e, f):
        i0 = (f - e.tva) // 4
        return i0, i0 + e.F[f]["size"]

    def pairs(self, a, b):
        """((ref index, target index) of every lined-up instruction, the share lined up)"""
        k = (a, b)
        if k not in self.cache:
            import difflib
            ra, rb = self._span(self.r, a)
            ta, tb = self._span(self.t, b)
            sm = difflib.SequenceMatcher(None, self.lr[ra:rb], self.lt[ta:tb], autojunk=False)
            out = [(ra + x + k2, ta + y + k2) for x, y, n in sm.get_matching_blocks() for k2 in range(n)]
            self.cache[k] = (out, 2.0 * len(out) / max(1, (rb - ra) + (tb - ta)))
        return self.cache[k]

    def sim(self, a, b):
        return self.pairs(a, b)[1]

    def at(self, a, b, va):
        """the target address of the reference instruction at va inside the pair (a, b), or None"""
        i = (va - self.r.tva) // 4
        return next((self.t.tva + 4 * j for x, j in self.pairs(a, b)[0] if x == i), None)


def shape_seed(M, A, min_size=6):
    """pair the functions whose whole loose shape is the same on both titles and found once on each (framework code
    built from one source: the strongest anchor there is). The number taken."""
    def index(e, L):
        h = defaultdict(list)
        for f, d in e.F.items():
            if d["size"] >= min_size:
                i0 = (f - e.tva) // 4
                h[tuple(L[i0:i0 + d["size"]])].append(f)
        return h
    hr, ht = index(M.r, A.lr), index(M.t, A.lt)
    rev = set(M.m.values())
    n = 0
    for k, fr in hr.items():
        ft = ht.get(k)
        if len(fr) == 1 and ft and len(ft) == 1 and fr[0] not in M.m and ft[0] not in rev:
            M.m[fr[0]] = ft[0]
            M.how[fr[0]] = "the same instructions, found once on each"
            rev.add(ft[0])
            n += 1
    return n


def align_grow(M, A, rounds=20, min_sim=0.6):
    """grow the pairs through the calls that line up: the n-th call of a paired function is to the n-th callee of its
    pair. A callee is taken when every lined-up call to it agrees and the two are alike."""
    total = 0
    for _ in range(rounds):
        rev = {b: a for a, b in M.m.items()}
        votes = defaultdict(Counter)
        for a, b in list(M.m.items()):
            if a not in M.R or b not in M.T:
                continue
            for i, j in A.pairs(a, b)[0]:
                ca, cb = M.r.calls.get(i), M.t.calls.get(j)
                if ca is None or cb is None or ca in M.r.plt or cb in M.t.plt:
                    continue
                if ca in M.m or cb in rev or ca not in M.R or cb not in M.T:
                    continue
                votes[ca][cb] += 1
        claim = defaultdict(list)
        for ca, c in votes.items():
            if len(c) == 1:
                cb, n = next(iter(c.items()))
                claim[cb].append((n, ca))
        new = 0
        for cb, lst in claim.items():
            if len(lst) != 1:
                continue
            n, ca = lst[0]
            if A.sim(ca, cb) >= min_sim:
                M.m[ca] = cb
                M.how[ca] = "the call that lines up in a paired function (%d place%s)" % (n, "" if n == 1 else "s")
                new += 1
        total += new
        M.grow()
        if not new:
            break
    return total


def _place(ref, tgt, M, A, va):
    """(target address, how, alike) of the reference address va: a library call by its imported name, a function by
    its pair, a place inside one by the instruction it lines up with; (None, why, 0) when it cannot be"""
    if va in ref.plt:
        b = next((x for x, n in tgt.plt.items() if n == ref.plt[va]), None)
        return (b, "the PLT stub of %s" % ref.plt[va], 1.0) if b else (None, "the program imports no %s" % ref.plt[va], 0)
    f = func_of(ref, va)
    if f not in M.m:
        return None, "no counterpart found", 0
    b = M.m[f]
    s = A.sim(f, b)
    if s < SIM_MIN:
        return None, "its pair 0x%x is not alike (%.2f of the instructions line up)" % (b, s), s
    if f == va:
        return b, M.how.get(f, "matched"), s
    x = A.at(f, b, va)
    if x is None:
        return None, "0x%x + 0x%x lines up with nothing in its pair 0x%x" % (f, va - f, b), s
    return x, "0x%x + 0x%x lined up in its pair 0x%x" % (f, va - f, b), s


def _data_votes(ref, tgt, M, A, addr):
    """Counter(target global) of every lined-up instruction that makes the reference global addr"""
    if not hasattr(ref, "made"):
        ref.made = defaultdict(set)                     # an address -> the functions whose instructions make it
        for i, vs in ref.refs.items():
            for v in vs:
                ref.made[v].add(func_of(ref, ref.tva + 4 * i))
    c = Counter()
    for f in ref.made.get(addr, ()):
        if f not in M.m or f not in M.R or M.m[f] not in M.T:
            continue
        b = M.m[f]
        if A.sim(f, b) < SIM_MIN:
            continue
        for i, j in A.pairs(f, b)[0]:
            if addr in ref.refs.get(i, ()):
                for v in tgt.refs.get(j, ()):
                    if tgt.is_data(v) or tgt.in_sec(v, ".rodata"):
                        c[v] += 1
    return c


def _imm_votes(ref, tgt, A, pairs, v):
    """Counter(target immediate) of the lined-up instructions in `pairs` whose reference immediate is v"""
    c = Counter()
    for a, b in pairs:
        for i, j in A.pairs(a, b)[0]:
            x = _imm(ref.words[i])
            if x == v:
                c[_imm(tgt.words[j])] += 1
    return c


def _event_votes(ref, tgt, M, A, ids, dispatch):
    """{reference bus id: Counter(target id)}: the constant moved into w0 just before a call of the bus's dispatch, in
    every paired function alike enough, read at the lined-up instruction on the target. (Constants passed to other
    calls are not bus ids: Walking Dead Remastered 0.92's adjustment and sound ids are Star Wars ELG's less one, its
    bus ids the same; Star Wars 2025 Pro 0.84's game over is 0x46 where the others' is 0x47.)"""
    out = {v: Counter() for v in ids}
    posts = {dispatch}
    for a, b in M.m.items():
        if a not in M.R or b not in M.T or A.sim(a, b) < 0.85:
            continue
        for i, j in A.pairs(a, b)[0]:
            w = ref.words[i]
            if (w & 0xFFE0001F) != 0x52800000:                # movz w0, #imm16 (hw 0)
                continue
            v = (w >> 5) & 0xFFFF
            call = next((ref.calls[k] for k in range(i + 1, i + 4) if k in ref.calls), None)
            if v not in out or call not in posts:
                continue
            y = tgt.words[j]
            if (y & 0xFFE0001F) == 0x52800000 and any(tgt.calls.get(k) == M.m.get(dispatch) for k in range(j + 1, j + 4)):
                out[v][(y >> 5) & 0xFFFF] += 1
    return out


def read_switch_ids(path):
    """{device name (upper case): switch id} from a rig census (proofs/s3census.sh, PAD-1290): one `<id> <NAME>` line
    per switch a press reached the modes with; `#` lines are notes."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                sid, name = line.split(None, 1)
                out[" ".join(name.upper().split())] = int(sid, 0)
    return out


def spike3_switches(tgt, ids=None, unseen=None):
    """[(switch id, shot mask, name)] of the target's playfield switches that are shots, from its own device table:
    the switches the Spike 2 rule (portswitch.NOT_SHOTS) keeps, none of the service buttons' I/O group, one shot bit
    each from bit 0 (up to 64). Star Wars ELG 1.10: the 30 its proven port names, every one.

    A switch's id is its rank among the table's switches - true on ELG and Walking Dead Remastered, NOT on every title:
    Star Wars 2025 LE 0.96 numbers its RIGHT TARGET last (87) and every switch after it one lower (PAD-1290, measured
    on the rig; nothing in the table says so), Star Wars 2025 Pro 0.84 its Right target (83, PAD-1291). *ids* (read_switch_ids, a rig census) gives the measured ids instead:
    a switch it does not name never reached the modes on the rig and is left out (its name appended to *unseen*)."""
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    from pinball_decryptor.plugins.stern import portswitch
    recs = [r for r in device_records(tgt) if r[3] == 1]
    svc = {g for name, g, idx, cls in recs if re.match(r"SERVICE\b", name.upper())}
    shots = []
    for sid, (name, g, idx, cls) in enumerate(recs, 1):     # a switch's id: its rank among the table's switches
        key = " ".join(name.upper().split())
        if g in svc or portswitch.NOT_SHOTS.search(key):
            continue
        if ids is not None:
            if key not in ids:
                if unseen is not None:
                    unseen.append(portswitch.nice(name))
                continue
            sid = ids[key]
        shots.append((sid, name))
    shots = shots[:portswitch.MAX_SWITCH_SHOTS]
    names = Counter(portswitch.nice(n) for s, n in shots)
    out = []
    for k, (sid, name) in enumerate(shots):
        nm = portswitch.nice(name)
        out.append((sid, 1 << k, ("%s (%d)" % (nm, sid)) if names[nm] > 1 else nm))
    return out


def draft_spike3(ref, rport, tgt, game, version, switch_ids=None):
    """A Spike 3 port of `tgt` from `rport`, the proven port of the Spike 3 program `ref` (another title). Returns
    (text, matcher, core groups missing, sites not written)."""
    scan(ref)
    scan(tgt)
    M = Matcher(ref, tgt)
    M.seed()
    A = Aligner(ref, tgt)
    shape_seed(M, A)
    seeded = len(M.m)
    M.grow()
    grown = align_grow(M, A)
    lines = read_port(rport)
    rg = next((t[1] for k, t, s in lines if k == "game"), "?")
    rv = next((t[1] for k, t, s in lines if k == "version"), "?")
    alike = sorted(A.sim(a, b) for a, b in M.m.items() if a in M.R and b in M.T)
    head = ["# %s %s - Spike 3 (64-bit ARM): drafted by s3port.py (PAD-1287) from the Spike 3 port %s (%s %s)."
            % (game, version, os.path.basename(rport), rg, rv),
            "# Functions paired across the two titles: %d of %d reference functions (%d anchored by vtable slots and "
            "strings, %d through calls that line up, the rest grown through calls); half of them line up %.0f%% or "
            "better." % (len(M.m), len(M.R), seeded, grown, 100 * alike[len(alike) // 2] if alike else 0),
            "# Written: what the reference port carries that is the FRAMEWORK's (each site's function at least %d%% "
            "alike its" % (100 * SIM_MIN),
            "# reference's, each global and offset read at the lined-up instruction, the engines' layouts re-read off "
            "this program's",
            "# own code); the switch lines from this program's own device table. The reference game's own content "
            "(shows, lamps,",
            "# callouts, scenes, held coils, its modes) is not this title's: written as comments, for its own port.",
            "# NOT RUN: a draft - run a mode with it on this build in the emulator, then write what it proved here.",
            "", "game           %s" % game, "version        %s" % version, ""]
    body, placed, missing, notes = [], {}, [], []
    proven = [(k, t, s) for k, t, s in lines if k and not s.lstrip().startswith("#")]
    # ---- sites
    body.append("# ---- functions: site <name> <address> <first two instruction words> ----")
    for k, t, s in proven:
        if k != "site" or len(t) < 3:
            continue
        name, a = t[1], int(t[2], 16)
        if GAME_SITE.match(name):
            continue
        b, how, sm = _place(ref, tgt, M, A, a)
        why = site_ok(tgt, b) if b else how
        if not b or why:
            body.append("# site %-16s NOT PLACED: %s" % (name, why if b else how))
            missing.append(name)
            continue
        line = "site %-16s 0x%08x 0x%08x 0x%08x" % (name, b, tgt.u32(b), tgt.u32(b + 4))
        if name in SCREEN_CLIP_SITES:
            body.append("# not carried - the screen and clip features name this title's hud / video bank scenes: "
                        + line)
            continue
        body.append("#   %s: %s (%.0f%% alike)" % (name, how, 100 * sm))
        body.append(line)
        placed[name] = b
    # the engines read their layouts off this program's own code; where one finds a site too, it must agree
    snd = sound_engine(tgt, placed)
    content = [(k, t, s) for k, t, s in proven if k not in ("lamp", "scene", "callout", "switch", "text")
               and not (k == "site" and GAME_SITE.match(t[1]))]
    lit = light_engine(ref, content, tgt, placed)
    for eng, tag in ((snd, "the sound engine"), (lit, "the lamp layer / processes")):
        for name, b in eng["site"].items():
            if name in placed and placed[name] != b:
                notes.append("%s: lined up at 0x%x, %s reads 0x%x - the engine's is written" % (name, placed[name], tag, b))
            if name in placed and placed[name] != b or name not in placed and name in [t[1] for k, t, s in proven
                                                                                       if k == "site"]:
                at = next((i for i, l in enumerate(body) if re.match(r"(# )?site %-16s " % re.escape(name), l)), None)
                ln = "site %-16s 0x%08x 0x%08x 0x%08x" % (name, b, tgt.u32(b), tgt.u32(b + 4))
                if at is None:
                    body += ["#   %s: read off %s's code" % (name, tag), ln]
                else:
                    body[at:at + 1] = ["#   %s: read off %s's code" % (name, tag), ln]
                placed[name] = b
                if name in missing:
                    missing.remove(name)
    for pair in SITE_PAIRS:
        half = [n for n in pair if n in placed]
        if half and len(half) < len(pair):
            for name in half:
                at = next((i for i, l in enumerate(body) if re.match(r"site %-16s " % re.escape(name), l)), None)
                if at is not None:
                    body[at] = "# not carried (%s has no counterpart, armed only together): %s" % (
                        "/".join(n for n in pair if n not in placed), body[at])
                del placed[name]
    # ---- globals
    body += ["", "# ---- globals: data <name> <address> ----"]
    for k, t, s in proven:
        if k != "data" or len(t) < 3:
            continue
        name, a = t[1], int(t[2], 16)
        if GAME_DATA.match(name):
            body.append("# data %-22s not carried: the reference game's own (%s)" % (name, s.split("#")[0].strip()))
            continue
        c = _data_votes(ref, tgt, M, A, a)
        top = c.most_common(2)
        eng = snd["data"].get(name, lit["data"].get(name))
        got = top[0][0] if top and (len(top) < 2 or top[0][1] >= 3 * top[1][1]) else None
        if eng is not None and got is not None and eng != got:
            notes.append("data %s: lined up 0x%x, the engine reads 0x%x - the engine's is written" % (name, got, eng))
        b = eng if eng is not None else got
        if b is None:
            body.append("# data %-22s NOT PLACED: %s" % (name, "no lined-up instruction makes it" if not top else
                                                          "the lined-up instructions disagree (%s)" % ", ".join(
                                                              "0x%x x%d" % x for x in top)))
            missing.append("data:" + name)
            continue
        how = ("read off the engine's own code" if eng is not None else
               "%d of %d lined-up instructions" % (top[0][1], sum(c.values())))
        line = "data %-22s 0x%08x   # %s" % (name, b, how)
        if name in SCREEN_CLIP_DATA:
            body.append("# not carried (screens/clips): " + line)
            continue
        body.append(line)
        placed["data:" + name] = b
    # ---- values
    body += ["", "# ---- values: the reference's framework offsets and counts, each read at the lined-up instruction "
             "or off the engine's own code ----"]
    witness = [(func_of(ref, int(t[2], 16)), placed[t[1]]) for k, t, s in proven
               if k == "site" and len(t) >= 3 and t[1] in placed]
    witness = [(a, func_of(tgt, b)) for a, b in witness if a in M.R and func_of(tgt, b) in M.T]
    for a, b in list(witness):                 # and the functions they call (the engines' own helpers)
        for c in set(M.R[a]["callees"]):
            if c in M.m and M.m[c] in M.T and (c, M.m[c]) not in witness and A.sim(c, M.m[c]) >= SIM_MIN:
                witness.append((c, M.m[c]))
    read = set(lit["value"]) - {"lamp_slot_level", "lamp_slot_alpha", "lamp_slot_fade", "lamp_slot_used"}
    engv = dict(SOUND_VALUES) if "data:sound_channels" in placed else {}
    engv.update({k2: v for k2, v in lit["value"].items() if k2 not in LIGHT_VALUES_UNUSED and k2 != "show_proc"})
    events = [(t, s) for k, t, s in proven if k == "event" and len(t) >= 3]
    for k, t, s in proven:
        if k != "value" or len(t) < 3:
            continue
        name = t[1]
        if name == "game_flags_at":
            # PAD-1327: not the reference game's own - the 64-bit flag bitmap's layout (its pointer at +0), the same on
            # every Spike 3 program; dropped with GAME_VALUE, the runtime read Spike 2's +4 at the first game start
            if "data:game_flags" in placed:
                body.append("value %-25s %s    # the 64-bit flag bitmap's layout, as the reference's" % (name, t[2]))
                placed["value:" + name] = int(t[2], 0)
            continue
        if GAME_VALUE.match(name) or name == "ball_end_event":
            continue
        v = int(t[2], 0)
        c = _imm_votes(ref, tgt, A, witness, v)
        top = c.most_common(1)
        fmt = (lambda x: "0x%x" % x) if t[2].startswith("0x") else str
        if name in engv:
            nv = engv[name]
            agree = c.get(nv, 0), sum(c.values())
            if name not in read and top and top[0][0] != nv and top[0][1] > c.get(nv, 0):
                notes.append("value %s: the engines' %s, but %d of %d lined-up instructions hold %s here - that is "
                             "written" % (name, nv, top[0][1], agree[1], fmt(top[0][0])))
                nv, agree = top[0][0], (top[0][1], agree[1])
            elif agree[0] < agree[1]:
                notes.append("value %s: %d of the %d lined-up instructions holding %s on the reference hold %s here" % (
                    name, agree[1] - agree[0], agree[1], fmt(v), ", ".join(fmt(x) for x in c if x != nv)))
            if nv != v:
                notes.append("value %s: %s on the reference, %s here" % (name, fmt(v), fmt(nv)))
            line = "value %-25s %s    # %s%s" % (name, fmt(nv), "read off this program's own code" if name in read else
                                                 "the engine's layout", ", %d of %d lined-up instructions" % agree
                                                 if agree[1] else "")
        else:
            if not top or top[0][1] < 0.75 * sum(c.values()) or top[0][0] is None:
                body.append("# value %-25s NOT PLACED: %s" % (name, "no lined-up instruction of a placed site holds %s"
                                                               % t[2] if not c else "the lined-up instructions disagree"))
                missing.append("value:" + name)
                continue
            nv = top[0][0]
            line = "value %-25s %s    # %d of %d lined-up instructions of the placed sites" % (
                name, ("0x%x" % nv) if t[2].startswith("0x") else nv, top[0][1], sum(c.values()))
        if name in SCREEN_CLIP_VALUES:
            body.append("# not carried (screens/clips): " + line)
            continue
        body.append(line)
        placed["value:" + name] = nv
    body += ["# PAD-1283: %s" % w for w in lit["why"]]
    # ---- events: the framework's bus ids, each checked against the constants this program's code passes
    rdisp = next((int(t[2], 16) for k, t, s in proven if k == "site" and t[1] == "hook_dispatch"), None)
    ev = _event_votes(ref, tgt, M, A, {int(t[2], 0) for t, s in events}, rdisp)
    body += ["", "# ---- events: the framework's bus ids (each one the constant the lined-up code passes here) ----"]
    for t, s in events:
        v = int(t[2], 0)
        c = ev[v]
        top = c.most_common(1)
        if not top or top[0][1] < 0.8 * sum(c.values()):
            body.append("# event %-12s NOT PLACED: %s" % (t[1], "no lined-up code passes it" if not c else
                                                          "the lined-up code passes %s" % dict(c)))
            missing.append("event:" + t[1])
            continue
        nv = top[0][0]
        body.append("event %-12s 0x%x   # %d of %d lined-up places" % (t[1], nv, top[0][1], sum(c.values())))
        placed["event:" + t[1]] = nv
    if "hook_dispatch" in placed and "event:ball_end" in placed:
        body.append("value ball_end_event 0x%x    # the end of a ball, from the bus (no ball_end site on Spike 3)"
                    % placed["event:ball_end"])
        placed["ball_end_event"] = placed["event:ball_end"]
    # ---- switches: this program's own
    unseen = []
    sw = spike3_switches(tgt, switch_ids, unseen)
    if sw:
        body += ["", "# ---- switches: the playfield switches of this program's own device table that are shots "
                 "(switch <id> <shot mask> <name>) ----"]
        if switch_ids is not None:
            body.append("# ids measured on the rig (a census: each switch pressed in a game, the id it reached the "
                        "modes with), not the table's ranks")
            if unseen:
                body.append("# not carried - no id reached the modes when pressed on the rig: %s" % ", ".join(unseen))
        body += ["switch %-4d %-18s %s" % (sid, "0x%x" % mask, nm) for sid, mask, nm in sw]
        ex = next((nm for sid, mask, nm in sw if re.search(r"\b(target|tgt)\b", nm, re.I)), sw[0][2])
        body += ["", "# ---- text ----", "text example_start_shot     %s" % ex]
    # ---- what is the reference game's own
    rest = Counter(k for k, t, s in proven if k in ("lamp", "scene", "callout") or
                   (k == "site" and GAME_SITE.match(t[1])) or (k == "text" and t[1] != "example_start_shot") or
                   (k == "value" and GAME_VALUE.match(t[1])))
    if rest:
        body += ["", "# not carried - the reference game's own content, for this title's own port: " +
                 ", ".join("%d %s" % (n, k) for k, n in sorted(rest.items()))]
    edge_lines(tgt, body, placed, notes)
    if "switch_edge" in placed:
        missing = [n for n in missing if n not in _EDGE_NAMES]
    drop_carried_attract(body, placed, missing)                         # PAD-1328: the target's own, below
    att = attract_lines(tgt, placed)
    if att:
        body += [""] + att
    body[:] = [l for l in body if not l.startswith(("cablamp ", "# cablamp "))]   # the reference's cabinet is its own
    cab = cabinet_lines_a64(tgt, placed)                                # PAD-1328
    if cab:
        body += [""] + cab
    if notes:
        body += ["", "# ---- checks ----"] + ["# " + n for n in notes]
    core_missing = [grp for grp in CORE if not any(n in placed for n in grp) and not
                    (grp == ("ball_end", "hook_dispatch") and "ball_end_event" in placed)]
    if not sw and not any(n in placed for n in ("shot_dispatch", "switch_edge")):
        core_missing.append(("switch lines",))
    core_missing += [grp for grp in CORE_DATA if not any("data:" + n in placed for n in grp)]
    return "\n".join(head + body) + "\n", M, core_missing, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ref_elf")
    ap.add_argument("ref_port")
    ap.add_argument("target_elf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--game")
    ap.add_argument("--version")
    ap.add_argument("--switch-ids", help="a rig census (proofs/s3census.sh or proofs/swcensus.sh): the switch lines' ids as measured")
    a = ap.parse_args(argv)
    ref, tgt = Elf(a.ref_elf), Elf(a.target_elf)
    if not tgt.a64:
        print("s3port.py: the target must be a Spike 3 (64-bit) program", file=sys.stderr)
        return 2
    if ref.a64:
        if not (a.game and a.version):
            print("s3port.py: from a Spike 3 reference, name the target's --game and --version", file=sys.stderr)
            return 2
        text, M, core_missing, missing = draft_spike3(ref, a.ref_port, tgt, a.game, a.version,
                                                             read_switch_ids(a.switch_ids) if a.switch_ids else None)
    else:
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
