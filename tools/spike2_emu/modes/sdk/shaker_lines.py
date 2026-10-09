#!/usr/bin/env python3
"""shaker_lines.py - the shaker motor's port lines for a Spike 2 game build, read from the game's own shake
routine (PAD-474; MODE_SDK.md "The shaker").

    shaker_lines.py <game ELF> [--port <port>]   prints the lines (only those the port lacks, with --port)

Every Spike 2 framework carries ONE routine that shakes the cabinet, found here by the two things only it names:
the operator adjustment AD_SHAKER_MOTOR (its id = its index in the AD_ name table) and the error "Shaker motor
shake duration out of range" (its id = its index in the error text table). PAD-414 placed it by hand on Godzilla
Premium/LE 1.16 (`site shake` 0x189a54); this finds the same routine on any build (PAD-420's desk reader, its
lines renamed to PAD-414's). It comes in three shapes, each ending in the same framework call:

  ms strength force   (Godzilla, Led Zeppelin, Rush): the operator's setting (0..4) cuts the time to a u32 table,
                      a busy mask on the mode word holds it off unless forced, the strength picks the power from a
                      byte table 0x14 past the time table. `site shake_stop`, the game's OFF, follows it.
  ms force            (TMNT, Mandalorian, Munsters, Venom): the same, at ONE power (51/255): no strength argument.
  kind level          (Aerosmith, Guardians, Elvira, Sword of Rage): shake(kind, min level) - it shakes only when
                      the operator's setting (0..3) is not 0 and at least the call's min level, for the kind's
                      time from a u16 table, at one power; the call cannot take a time, so a mode's shake is sent
                      the way the call sends its own (`text shake_call drive`, `value shake_power`).

  then:  if drive_left(drive) < ms: coil_fire(drive, power, ms, 0, 0, 0) - ONE command that ends by itself.

The lines (pad_mode_runtime.c's "the shaker" reads them):
  site shake / shake_stop / drive_left / adjustment / coil_fire   the routine, the game's OFF (the first shape
                      only), the drive's time left, the adjustment reader, the framework's coil call
  value shake_adj / shake_drive / shake_power                     AD_SHAKER_MOTOR, the drive (7 on every build
                      so far: coil 0 of the cabinet board), the one power (the last two shapes)
  text shake_call         the shape, when it is not the first
  text shake_setting_ms   the longest shake per operator setting, 0 (off) first
  text shake_max_ms       the game's own longest shake at strength 0..3, from the constants its calls pass
                          (0: a strength it never uses); the last two shapes have strength 0 only
  text shake_<name>       the game's own shakes by length (tap, short, medium, long, rumble): the one it calls
                          most in each, as at:ms:strength

Read-only; capstone. Exit 1 when the routine or one of its numbers is not found.
"""
import argparse
import collections
import re
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

ERR_TEXT = b"Shaker motor shake duration out of range"
#: the game's own shakes are named by length: (name, longest ms, the word the app shows)
LENGTHS = (("tap", 150, "tap"), ("short", 300, "short shake"), ("medium", 700, "medium shake"),
           ("long", 1600, "long shake"), ("rumble", 1 << 30, "rumble"))
STRENGTHS = 4


class Elf:
    def __init__(self, path):
        self.d = open(path, "rb").read()
        d = self.d
        phoff, = struct.unpack_from("<I", d, 0x1c)
        phentsize, phnum = struct.unpack_from("<HH", d, 0x2a)
        self.segs = []
        for i in range(phnum):
            t, off, va, _pa, fsz, _msz, fl, _al = struct.unpack_from("<8I", d, phoff + i * phentsize)
            if t == 1:
                self.segs.append((off, va, fsz, fl))
        self._words = None

    def off(self, va):
        for o, v, n, _f in self.segs:
            if v <= va < v + n:
                return o + va - v
        return None

    def va(self, off):
        for o, v, n, _f in self.segs:
            if o <= off < o + n:
                return v + off - o
        return None

    def word(self, va, fmt="<I"):
        return struct.unpack_from(fmt, self.d, self.off(va))[0]

    def cstr(self, va):
        o = self.off(va) if va else None
        if o is None:
            return None
        e = self.d.find(b"\0", o, o + 200)
        s = self.d[o:e] if e >= 0 else b""
        return s.decode() if s and all(32 <= c < 127 for c in s) else None

    def text(self):
        for o, v, n, f in self.segs:
            if f & 1:
                return o, v, n
        raise ValueError("no executable segment")

    def words(self):
        """(va of the first, the executable segment's words)"""
        if self._words is None:
            o, v, n = self.text()
            self._words = (v, struct.unpack_from("<%dI" % (n // 4), self.d, o))
        return self._words

    def str_vas(self, s):
        out = []
        for m in re.finditer(re.escape(s) + b"\0", self.d):
            if m.start() == 0 or self.d[m.start() - 1] == 0:
                out.append(self.va(m.start()))
        return out

    def ptrs_to(self, va):
        pat, out, i = struct.pack("<I", va), [], 0
        while True:
            i = self.d.find(pat, i)
            if i < 0:
                return out
            if i % 4 == 0 and self.va(i):
                out.append(self.va(i))
            i += 1


def table_index(e, ptr, ok):
    """How many string pointers satisfying ok() come before ptr: its index in its table."""
    i = 0
    while True:
        s = e.cstr(e.word(ptr - 4))
        if s is None or not ok(s):
            return i
        ptr -= 4
        i += 1


def ids(e):
    """(AD_SHAKER_MOTOR's adjustment id, the shaker error's id), None where the program has none."""
    adj = err = None
    for sva in e.str_vas(b"AD_SHAKER_MOTOR"):
        for p in e.ptrs_to(sva):
            adj = table_index(e, p, lambda s: s.startswith("AD_"))
    for sva in e.str_vas(ERR_TEXT):
        for p in e.ptrs_to(sva):
            err = table_index(e, p, lambda s: True)
    return adj, err


def _mov_r0(w):
    """The constant an ARM `mov r0, #imm` / `movw r0, #imm` (any condition) puts in r0, else None."""
    if (w & 0x0fef_f000) == 0x03a0_0000:
        rot, imm8 = (w >> 8) & 0xf, w & 0xff
        return ((imm8 >> (2 * rot)) | (imm8 << (32 - 2 * rot))) & 0xffff_ffff if rot else imm8
    if (w & 0x0ff0_f000) == 0x0300_0000:
        return ((w >> 4) & 0xf000) | (w & 0xfff)
    return None


def _branch_target(va, w):
    """Where a `b` / `bl` (any condition) at va goes, else None."""
    if (w & 0x0e00_0000) != 0x0a00_0000 or (w >> 28) == 0xf:
        return None
    imm = w & 0xff_ffff
    if imm & 0x80_0000:
        imm -= 0x100_0000
    return va + 8 + imm * 4


def func_start(e, va):
    for _ in range(4000):
        w = e.word(va)
        if (w & 0xffff_4000) == 0xe92d_4000 or w == 0xe52d_e004:     # push {.., lr} / str lr, [sp, #-4]!
            return va
        va -= 4
    return None


def find_routine(e, adj, err):
    """The one function that loads both the adjustment id and the error id into r0."""
    v0, ws = e.words()
    seen = {}
    for i, w in enumerate(ws):
        imm = _mov_r0(w)
        if imm is not None and imm in (adj, err):
            seen.setdefault(func_start(e, v0 + 4 * i), set()).add(imm)
    both = [f for f, s in seen.items() if s == {adj, err}]
    if len(both) == 1:
        return both[0]
    # Dungeons & Dragons: the callers read the setting and pass it first - the routine loads only the error, and
    # starts with `cmp r0, #4` right before its push
    first = [f - 4 for f, s in seen.items() if s == {err} and e.word(f - 4) == 0xe350_0004]
    return first[0] if len(first) == 1 else None


def setting_wrapper(e, f, adj):
    """(the wrapper, its adjustment read) of a routine that takes the setting first (D&D): the one function that
    reads adjustment <adj> and tail-calls f - shake(ms, force) { f(adjustment(adj), ms, force) } - else None."""
    v0, ws = e.words()
    found = set()
    for i, w in enumerate(ws):
        va = v0 + 4 * i
        if (w & 0x0f00_0000) == 0x0a00_0000 and _branch_target(va, w) == f:       # b f: a tail call
            g = func_start(e, va)
            body = disasm(e, g, va + 4)
            for k, x in enumerate(body[:-1]):
                if x.mnemonic == "mov" and x.op_str == "r0, #%#x" % adj and body[k + 1].mnemonic == "bl":
                    found.add((g, _target(body[k + 1])))
    return found.pop() if len(found) == 1 else None


def disasm(e, start, end):
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    md.skipdata = True
    o = e.off(start)
    return list(md.disasm(e.d[o:o + (end - start)], start))


def _imm(ins):
    m = re.search(r"#(-?0x[0-9a-f]+|-?\d+)$", ins.op_str)
    return int(m.group(1), 0) if m else None


def _target(ins):
    return int(ins.op_str.lstrip("#"), 0) if ins.mnemonic in ("bl", "b") and ins.op_str.startswith("#") else None


def _function(e, start, size):
    ins = disasm(e, start, start + size)
    return ins[:next((k for k, x in enumerate(ins) if k > 2 and (x.mnemonic == "push" or (
        x.mnemonic == "str" and x.op_str == "lr, [sp, #-4]!"))), len(ins))]


def _const(insns, k, reg):
    """The 32-bit constant the movw/movt pair before insns[k] (within 10) built in reg, or None."""
    lo = hi = None
    for ins in insns[max(0, k - 10):k + 1]:
        if ins.op_str.startswith(reg + ","):
            if ins.mnemonic == "movw":
                lo = _imm(ins)
            elif ins.mnemonic == "movt":
                hi = _imm(ins)
    return (hi << 16 | lo) if lo is not None and hi is not None else None


def _device_calls(body):
    """[(bl, the instructions before it, the device)]: the calls in body given a small constant device in r0."""
    out = []
    for k, x in enumerate(body):
        if x.mnemonic != "bl":
            continue
        prev = body[max(0, k - 8):k]
        r0 = [y for y in prev if y.op_str.startswith("r0,") and y.mnemonic not in ("cmp", "tst", "str", "strh")]
        if r0 and r0[-1].mnemonic == "mov" and _imm(r0[-1]) is not None and _imm(r0[-1]) <= 64:
            out.append((x, prev, _imm(r0[-1])))
    return out


def read_routine(e, f):
    """Everything the lines need, from the routine at f and the inner drive it may branch to."""
    r = {"routine": f}
    ins = _function(e, f, 0x120)
    if ins and ins[0].mnemonic == "cmp" and ins[0].op_str == "r0, #4":
        r["setting_first"] = True             # D&D: shake(setting, ms, force)
        r["adjustment"] = None                # not read here: the callers read it
    arg2 = next((x.op_str.split(",")[0] for x in ins[:6] if x.mnemonic == "mov" and x.op_str.endswith(", r1")), None)
    for k, x in enumerate(ins):
        if x.mnemonic == "bl" and "adjustment" not in r and not r.get("setting_first"):
            r["adjustment"] = _target(x)       # the first call: the adjustment read
        if x.mnemonic in ("tst", "ands") and "#" in x.op_str:
            r["busy"] = _imm(x)
        m = re.search(r"\[(\w+), r0, lsl #2\]", x.op_str)
        if x.mnemonic == "ldr" and m:
            r["level_table"] = _const(ins, k, m.group(1))
        m = re.search(r"\[(r\d), (r\d)\]", x.op_str)
        if x.mnemonic == "ldrh" and m and "kinds" in r:
            r["kind_table"] = _const(ins, k, m.group(1))
        if x.mnemonic == "cmp" and x.op_str.startswith("r3, #") and "kinds" not in r and k and \
                ins[k - 1].mnemonic == "sub":
            r["kinds"] = _imm(x) + 1          # sub r3,r5,#1; cmp r3,#N: kinds 1..N+1
        if x.mnemonic.startswith("ldrb") and x.op_str.endswith("#0x14]"):   # ldrbls r1, [r5, #0x14]
            r["power_from_table"] = True
        if x.mnemonic == "cmp" and re.match(r"r[67], #[34]$", x.op_str) and r.get("level_table"):
            r["strengths"] = _imm(x) + 1      # cmp r7, #3: strengths 0..3 index the power table
        if x.mnemonic == "cmp" and arg2 and x.op_str == arg2 + ", #0" and r.get("level_table"):
            r["two_powers"] = True            # Iron Maiden: strength 0 one power, any other the second
        if x.mnemonic == "b" and _target(x) and _target(x) < f:
            r["inner"] = _target(x)
        if x.mnemonic == "mov" and x.op_str == "r0, #0xff" and "inner" not in r:
            r["inner_arg"] = 0xff
        if x.mnemonic == "uxtb" and x.op_str == "r1, r0" and k and ins[k - 1].mnemonic == "bl" and \
                _target(ins[k - 1]) == r.get("adjustment"):
            r["power_adj"] = next((_imm(y) for y in reversed(ins[max(0, k - 4):k - 1])     # Metallica: the
                                   if y.op_str.startswith("r0, #")), None)                   # operator's power
    body = ins
    for _depth in range(3):                   # Elvira, Sword of Rage, Deadpool: the drive is an inner routine
        if "inner" not in r:
            break
        body = _function(e, r["inner"], 0x80)
        if any(x.mnemonic == "umull" for x in body) and any(x.mnemonic == "ubfx" for x in body):
            r["power"] = r.get("inner_arg", 0) // 6          # (arg * 0xaaaaaaab >> 32) >> 2
        tail = [_target(x) for x in body if x.mnemonic == "b" and _target(x) and _target(x) < r["inner"]]
        if len(_device_calls(body)) >= 2 or not tail:
            break
        r["inner"] = tail[0]                  # Deadpool: kind -> (ms, level, delay) -> (ms)
    fires = []
    for x, prev, dev in _device_calls(body):
        if body is ins and _target(x) == r.get("adjustment"):
            continue
        if "coil_left" not in r:
            r["coil_left"], r["dev"] = _target(x), dev
        elif dev == r["dev"] and _target(x) != r["coil_left"] and r.get("coil_fire", _target(x)) == _target(x):
            r["coil_fire"] = _target(x)
            p1 = [_imm(y) for y in prev if y.mnemonic == "mov" and y.op_str.startswith("r1, #")]
            if p1 and p1[-1]:
                fires.append(p1[-1])
                r.setdefault("power", p1[-1])
    if r.get("two_powers") and len(fires) == 2 and not r.get("power_from_table"):
        r["powers"] = fires                   # the fall-through (strength 0) first, the branch's second
    if r.get("power_from_table") and r.get("level_table"):
        n = r.get("strengths", STRENGTHS)
        o = e.off(r["level_table"] + 0x14)
        r["powers"] = list(e.d[o:o + n])
        r["power"] = r["powers"][0]
    if r.get("level_table"):
        r["level_ms"] = [e.word(r["level_table"] + 4 * k) for k in range(5)]
        r["call"] = "ms strength force" if r.get("powers") else "ms force"
    elif r.get("kind_table") and r.get("kinds"):
        r["kind_ms"] = [e.word(r["kind_table"] + 2 * k, "<H") for k in range(1, r["kinds"] + 1)]
        r["call"] = "kind level"
    return r


def find_stop(e, r):
    """The game's own OFF for the drive right after the routine (`str lr, [sp, #-4]!` ... coil_fire(drive, 0, 0,
    0, 0, 0)), else None - only the first shape has one."""
    end = r["routine"] + 0x100
    va = r["routine"] + 8
    while va < end:
        if e.word(va) == 0xe52d_e004:
            body = _function(e, va, 0x40)
            calls = [x for x in body if x.mnemonic == "bl"]
            movs = {x.op_str for x in body if x.mnemonic == "mov"}
            if len(calls) == 1 and _target(calls[0]) == r.get("coil_fire") and "r1, #0" in movs and \
                    "r0, #%d" % r["dev"] in movs and {"r2, r1", "r3, r1"} <= movs:
                return va
        va += 4
    return None


def _regs_before(e, va, regs):
    """The constants a call at va is given in regs, read off the instructions before it (back to a branch)."""
    out = {}
    for x in reversed(disasm(e, va - 48, va)):
        if x.mnemonic.startswith("b") and x.mnemonic not in ("bic", "bics") or x.mnemonic in ("pop", "bx"):
            break
        for reg in regs:
            if reg not in out and x.op_str.startswith(reg + ","):
                out[reg] = _imm(x) if x.mnemonic in ("mov", "movw") else None
    return out


def census(e, r):
    """Counter of (ms, strength) the game's calls of the routine pass as constants (a kind: its time)."""
    v0, ws = e.words()
    f, c = r["routine"], collections.Counter()
    for i, w in enumerate(ws):
        va = v0 + 4 * i
        if _branch_target(va, w) != f:
            continue
        a = _regs_before(e, va, ("r0", "r1"))
        if r["call"] == "kind level":
            kind = a.get("r0")
            if kind and 1 <= kind <= len(r["kind_ms"]):
                c[(r["kind_ms"][kind - 1], 0)] += 1
        elif a.get("r0"):
            strength = a.get("r1") if r["call"] == "ms strength force" else 0
            if r.get("two_powers") and strength:
                strength = 1                  # Iron Maiden: any strength but 0 is the second power
            if strength is not None and 0 <= strength < len(r.get("powers") or [0]):
                c[(a["r0"], strength)] += 1
    return c


def max_ms(r, calls):
    """The game's own longest shake at strength 0..3 (0: a strength it never calls with a constant), never past
    the operator's highest setting's."""
    top = max(r["level_ms"]) if r.get("level_ms") else max(r["kind_ms"])
    out = [0] * STRENGTHS
    for (ms, strength), _n in calls.items():
        out[strength] = max(out[strength], min(ms, top))
    return out


def game_shakes(calls):
    """[(name, word, ms, strength)]: in each length band the game's own shake it calls most, shortest band first."""
    out, lo = [], 0
    for name, hi, word in LENGTHS:
        band = [(n, ms, s) for (ms, s), n in calls.items() if lo < ms <= hi]
        if band:
            _n, ms, s = max(band, key=lambda t: (t[0], -t[1]))
            out.append((name, word, ms, s))
        lo = hi
    return out


def site_line(e, name, va):
    return "site %-18s 0x%08x 0x%08x 0x%08x" % (name, va, e.word(va), e.word(va + 4))


def lines_for(path):
    """(the port lines, what was read) for the ELF at path; SystemExit with the reason when not found."""
    e = Elf(path)
    adj, err = ids(e)
    if adj is None or err is None:
        raise SystemExit("%s: no AD_SHAKER_MOTOR / shaker error text - no shaker routine" % path)
    f = find_routine(e, adj, err)
    if f is None:
        raise SystemExit("%s: no single routine loads adjustment %d and error %d" % (path, adj, err))
    r = read_routine(e, f)
    if r.get("setting_first"):                # D&D: its shake(ms, force) wrapper reads the setting
        w = setting_wrapper(e, f, adj)
        if w is None:
            raise SystemExit("%s: the routine at 0x%x takes the setting, and no one wrapper reads it" % (path, f))
        r["inner_routine"], (r["routine"], r["adjustment"]) = f, w
        f = r["routine"]
    missing = [k for k in ("adjustment", "coil_left", "coil_fire", "dev", "call") if not r.get(k)]
    if not r.get("power") and not r.get("power_adj"):
        missing.append("power")
    if missing:
        raise SystemExit("%s: the routine at 0x%x: not found %s (%r)" % (path, f, missing, r))
    r["adj"] = adj
    r["stop"] = find_stop(e, r) if r["call"] == "ms strength force" else None
    calls = census(e, r)
    r["max_ms"] = max_ms(r, calls)
    r["shakes"] = game_shakes(calls)
    if not r["max_ms"][0]:
        raise SystemExit("%s: the routine at 0x%x: no call of the game's passes a constant at strength 0" % (path, f))
    setting = r["level_ms"] if r.get("level_ms") else [0] + [max(r["kind_ms"])] * 3
    if r["call"] == "ms strength force":
        how = "ms, strength 0..%d (powers %s /255), force" % (len(r["powers"]) - 1, "/".join(map(str, r["powers"])))
    elif r["call"] == "ms force":
        how = "ms, force: one power, %d/255%s" % (r["power"], "; it reads the setting and calls 0x%x(setting, ms, "
                                                  "force)" % r["inner_routine"] if r.get("inner_routine") else "")
    else:
        how = "kind 1..%d (%s ms), min level: one power, %s; a mode's shake is sent as its own are" % (
            len(r["kind_ms"]), "/".join(map(str, r["kind_ms"])), "the operator's (adjustment %d)" % r["power_adj"]
            if r.get("power_adj") else "%d/255" % r["power"])
    out = ["# ---- PAD-474: the shaker motor, read by shaker_lines.py from the game's own shake routine ----------",
           "# shake(%s): adjustment %d (AD_SHAKER_MOTOR), drive %d; %d constant calls" % (
               how, adj, r["dev"], sum(calls.values())),
           site_line(e, "shake", f)]
    if r["stop"]:
        out.append(site_line(e, "shake_stop", r["stop"]))
    out += [site_line(e, "drive_left", r["coil_left"]),
            site_line(e, "adjustment", r["adjustment"]),
            site_line(e, "coil_fire", r["coil_fire"]),
            "value shake_adj            %d" % adj,
            "value shake_drive          %d" % r["dev"]]
    if r["call"] == "kind level":
        out += ["value shake_power_adj      %d" % r["power_adj"] if r.get("power_adj") else
                "value shake_power          %d" % r["power"], "text shake_call            drive"]
    elif r["call"] == "ms force":
        out.append("text shake_call            ms force")
    out += ["text shake_max_ms          %s" % " ".join(map(str, r["max_ms"])),
            "text shake_setting_ms      %s" % " ".join(map(str, setting))]
    out += ["text %-22s 0:%d:%d" % ("shake_" + name, ms, s) for name, _w, ms, s in r["shakes"]]
    return out, r


def _key(line):
    p = line.split()
    return (p[0], p[1]) if len(p) > 1 and p[0] in ("site", "data", "value", "text") else None


def missing_from(lines, port_text):
    """The lines a port lacks; a line the port has with another value is kept, flagged above it."""
    have = {}
    for ln in port_text.splitlines():
        k = _key(ln.strip())
        if k:
            have[k] = ln.strip()
    out = []
    for ln in lines:
        k = _key(ln)
        if k and k in have:
            if have[k].split()[:3] != ln.split()[:3]:
                out += ["# DIFFERS from the port's: " + have[k], ln]
            continue
        out.append(ln)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("elf")
    ap.add_argument("--port", help="print only the lines this port lacks (a differing one is flagged)")
    a = ap.parse_args(argv)
    out, _r = lines_for(a.elf)
    if a.port:
        with open(a.port, encoding="utf-8") as f:
            out = missing_from(out, f.read())
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
