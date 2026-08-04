#!/usr/bin/env python3
"""Recover the packet bytes at every `bl 59ebac` (node-bus send wrapper) site.

Strategy: for each call site, walk forward from the enclosing function start
(largest bl-target <= site), doing a tiny constant-propagation emulation of
  mov rN,#imm / movw/movt / add rN,sp,#imm / mov rN,sp
and recording strb/strh/str of a KNOWN constant into a KNOWN sp-relative slot.
At the bl, r0 must be a known sp+K; packet = mem[K], mem[K+1], ...
Layout (from 0x59d824): [0]=node|0x80, [1]=len, [2..2+len-1]=payload,
[2+len]=reply-length field.
"""
import re, sys, collections

DIS = "/home/david/game.dis"
TARGETS = "/home/david/bltargets.txt"

line_re = re.compile(r"^\s*([0-9a-f]+):\t([0-9a-f ]+)\t(\S+)\s*(.*)$")

print("loading...", file=sys.stderr)
insns = {}
order = []
with open(DIS, "r", errors="replace") as f:
    for ln in f:
        m = line_re.match(ln)
        if not m:
            continue
        a = int(m.group(1), 16)
        insns[a] = (m.group(3), m.group(4).split("@")[0].strip())
        order.append(a)
order.sort()
print("insns %d" % len(insns), file=sys.stderr)

fnstarts = sorted(int(x, 16) for x in open(TARGETS))
import bisect
def fnstart(a):
    i = bisect.bisect_right(fnstarts, a) - 1
    return fnstarts[i] if i >= 0 else a

REGS = ["r%d" % i for i in range(13)] + ["sp", "lr", "pc", "fp", "ip", "sl"]
ALIAS = {"fp": "r11", "ip": "r12", "sl": "r10"}
def norm(r):
    r = r.strip().rstrip(",").rstrip("!")
    return ALIAS.get(r, r)

imm_re = re.compile(r"^#(-?(?:0x)?[0-9a-fA-F]+)$")
def parseimm(t):
    t = t.strip()
    m = imm_re.match(t)
    if not m:
        return None
    s = m.group(1)
    try:
        return int(s, 16) if s.startswith("0x") or s.startswith("-0x") else int(s, 10)
    except ValueError:
        return None

memop_re = re.compile(r"^(\w+),\s*\[(\w+)(?:,\s*#(-?\d+|-?0x[0-9a-f]+))?\]")

def emulate(fs, site):
    reg = {}          # regname -> ('c', value) or ('sp', off)
    mem = {}          # sp offset -> byte value (int) ; None = unknown
    a = fs
    guard = 0
    while a <= site and guard < 4000:
        guard += 1
        ins = insns.get(a)
        if ins is None:
            a += 4
            continue
        mn, ops = ins
        if a == site:
            return reg, mem
        base = mn.rstrip("s")
        # skip conditional suffix handling: treat all as unconditional (approx)
        if base.startswith("mov") and not base.startswith("movt"):
            p = [x.strip() for x in ops.split(",", 1)]
            if len(p) == 2:
                d = norm(p[0]); src = p[1].strip()
                v = parseimm(src)
                if v is not None:
                    reg[d] = ("c", v & 0xFFFFFFFF)
                elif norm(src) == "sp":
                    reg[d] = ("sp", 0)
                elif norm(src) in reg:
                    reg[d] = reg[norm(src)]
                else:
                    reg.pop(d, None)
        elif base.startswith("movt"):
            p = [x.strip() for x in ops.split(",", 1)]
            if len(p) == 2:
                d = norm(p[0]); v = parseimm(p[1])
                cur = reg.get(d)
                if v is not None and cur and cur[0] == "c":
                    reg[d] = ("c", (cur[1] & 0xFFFF) | (v << 16))
                else:
                    reg.pop(d, None)
        elif base in ("add", "sub"):
            p = [x.strip() for x in ops.split(",")]
            if len(p) == 3:
                d = norm(p[0]); s1 = norm(p[1]); v = parseimm(p[2])
                if v is not None:
                    sv = reg.get(s1)
                    if s1 == "sp":
                        sv = ("sp", 0)
                    if sv:
                        k = sv[1] + (v if base == "add" else -v)
                        reg[d] = (sv[0], k if sv[0] == "sp" else (k & 0xFFFFFFFF))
                    else:
                        reg.pop(d, None)
                else:
                    reg.pop(d, None)
            else:
                if ops:
                    reg.pop(norm(ops.split(",")[0]), None)
        elif base.startswith("strb") or base.startswith("strh") or (base.startswith("str") and "[" in ops):
            m = memop_re.match(ops)
            if m:
                src = norm(m.group(1)); bs = norm(m.group(2))
                off = m.group(3)
                off = int(off, 16) if off and off.startswith("0x") else (int(off) if off else 0)
                bv = ("sp", 0) if bs == "sp" else reg.get(bs)
                if bv and bv[0] == "sp":
                    slot = bv[1] + off
                    sv = reg.get(src)
                    n = 1 if base.startswith("strb") else (2 if base.startswith("strh") else 4)
                    for i in range(n):
                        if sv and sv[0] == "c":
                            mem[slot + i] = (sv[1] >> (8 * i)) & 0xFF
                        else:
                            mem[slot + i] = None
        elif base.startswith("ldr") or base.startswith("ldm"):
            m = re.match(r"^(\w+)", ops)
            if m:
                reg.pop(norm(m.group(1)), None)
        elif base in ("bl", "blx"):
            for r in ("r0", "r1", "r2", "r3", "r12"):
                reg.pop(r, None)
        elif base in ("mul", "mla", "eor", "orr", "and", "bic", "lsl", "lsr",
                      "asr", "ror", "rsb", "uxtb", "uxth", "sxtb", "sxth",
                      "mvn", "clz", "ubfx", "sbfx", "bfi", "bfc", "adc", "sbc"):
            m = re.match(r"^(\w+)", ops)
            if m:
                reg.pop(norm(m.group(1)), None)
        a += 4
    return reg, mem

sites = []
for a in order:
    ins = insns[a]
    if ins[0] in ("bl", "blx") and ins[1].startswith("59ebac "):
        sites.append(a)
print("sites %d" % len(sites), file=sys.stderr)

rows = []
for s in sites:
    fs = fnstart(s)
    reg, mem = emulate(fs, s)
    r0 = reg.get("r0")
    if not r0 or r0[0] != "sp":
        rows.append((s, fs, None, None, None, "r0 unknown %r" % (r0,)))
        continue
    k = r0[1]
    b = [mem.get(k + i, "?") for i in range(80)]
    node = b[0]
    ln = b[1]
    if isinstance(ln, int) and 0 <= ln < 70:
        payload = b[2:2 + ln]
        rl = b[2 + ln]
    else:
        payload = None
        rl = None
    rows.append((s, fs, node, ln, payload, rl))

for s, fs, node, ln, payload, rl in rows:
    print("site=0x%x fn=0x%x node=%s len=%s payload=%s replylen=%s" %
          (s, fs, node, ln,
           payload if payload is None else "[" + ",".join(
               ("0x%02x" % x) if isinstance(x, int) else str(x) for x in payload) + "]",
           rl))
