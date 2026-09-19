#!/usr/bin/env python3
"""stock_modes.py - what a Spike 2 game's OWN modes are made of, read from its game ELF (item 144).

    stock_modes.py <game ELF> [--ref <Godzilla Pro 1.15 game ELF>] [--json OUT] [--table]

A stock mode is compiled C++: one `cmode_*` class per mode, a static object per mode that
`cmode_manager`'s constructor builds, and virtual functions that call the engine (awards,
callouts, shows, timers, adjustments). Every NUMBER such a mode uses sits in one of a few
places, and where it sits decides how it can be changed:

  imm    `mov rd, #imm` - an 8-bit value rotated; a new value must fit the same encoding
  movw   `movw rd, #imm16` - any value below 65536
  movwt  `movw` + `movt` on one register - any 32-bit value, two words
  lit    `ldr rd, [pc, #off]` - a literal-pool word, any 32-bit value; other code may load it too
  data   a word in .data read through a loaded address - shared by every reader
  adj    `get_adjustment(id)` - the operator's setting; the ELF holds only its default
  code   computed by the instructions (shifts, a level times a constant) - not one word

This reads, for every mode:
  - the manager constructor's call per mode: id, class, object, constructor arguments
    (a, award id, b, and a timer index for timed modes), and the destructor that names it;
  - every virtual the class overrides against its base, and in each: the engine calls it
    makes with the constants in r0-r3 and on the stack at the call, the VA and the words
    of the instruction(s) each constant came from, and its KIND (above);
  - virtual calls (`ldr r3,[r0]; ldr r3,[r3,#4n]; blx r3`) with their r1-r3 constants,
    which is how a timer is given a duration;
  - strings the function loads: a 40-hex scene id, a clip or text name;
  - who starts the mode: every `cmode_manager_get(mgr, id)` whose result's slot 8 (START)
    is called, with the function (and class) holding the call;
  - the lit-shot mask its v[44] returns (what cmode's START lights), when that is a constant:
    `shots` plus `initial_mask.lo`/`.hi` numbers (a mode's own start may write another);
  - selector tables: runs of 12-byte `{slot, mode id, 0}` entries a screen starts modes from
    (Godzilla's battle select screen), one `select.slot<n>.mode_id` data word per slot.

It is a linear constant tracker, not an emulator. A value a call builds, a loop, or a
register merged from two paths reads as unknown, never as a guess. The engine addresses
are Godzilla Pro 1.15's (MODE_API.md); for another build, --ref locates them there with
port_tool.py's masked signatures, and a function it cannot place is left out.

Output: one line per fact, in the grammar MODE_SDK.md ("The game's own modes") sets out.
Read-only; never touches the ELF.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import rtti_tree as rt  # noqa: E402

PRO115_SHA1 = "08d502998706d327bfbb6ea5f92ac0cee76be63b"

# Godzilla Pro 1.15 (MODE_API.md). name -> (VA, argument roles). Roles name what each of
# r0..r3 / the stack holds; "v64" is a 64-bit value in two registers.
ENGINE_PRO115 = {
    "get_adjustment": (0x45DF38, ("id",)),
    "caward_add": (0x2FACC, ("aw", "_", "v64lo", "v64hi", "sp0:idx")),
    "caward_add_scaled": (0x2FB8C, ("aw", "notify", "idx", "mult")),
    "caward_build": (0x2F784, ("aw", "value")),
    "caward_get": (0x30E48, ("mgr", "id")),
    "score_add": (0x4B8CF4, ("p", "_", "v64lo", "v64hi")),
    "score_add_current": (0x4B8E5C, ("v64lo", "v64hi")),
    "callout_play": (0x187F44, ("req",)),
    "callout_play_nth": (0x18800C, ("req", "n")),
    "sound_request_play": (0x2A3108, ("req",)),
    "sound_request_play_nth": (0x2A32BC, ("req", "n")),
    "show_start": (0x4F34E0, ("id",)),
    "show_kill": (0x255DD4, ("id",)),
    "event_post": (0x2551DC, ("id", "handler", "flags")),
    "event_post_replacing": (0x2555DC, ("id", "handler", "flags")),
    "game_event": (0x44C320, ("id",)),
    "ctimer_get": (0x18B47C, ("mgr", "idx")),
    "award_screen": (0x3BA540, ("type", "a", "b", "obj")),
    "fx": (0x185E9C, ("n", "a", "b")),
    "clip_play": (0x528A4, ("name", "loop", "crop")),
    "cmode_manager_get": (0xD1C10, ("mgr", "id")),
    "cmode_manager_started": (0xD246C, ("mgr", "id")),
    "cmode_manager_stopped": (0xD24C4, ("mgr", "id", "reason")),
    "audit_add": (0x422DE4, ("id", "n")),
    "light_run": (0x1C3454, ("owner", "group", "command")),
    "lamp_group": (0x4BF294, ("set", "prio")),
    "msg_lookup": (0x34A764, ("id",)),
    "playfield_multiplier": (0x4B8E7C, ("n",)),
    "error_log": (0x457E00, ("code",)),
}
# the calls whose constants are a mode's NUMBERS (the rest are reported as facts)
NUMBER_CALLS = ("get_adjustment", "caward_add", "caward_add_scaled", "caward_build", "score_add",
                "score_add_current", "callout_play", "callout_play_nth", "sound_request_play",
                "sound_request_play_nth", "show_start", "event_post", "event_post_replacing",
                "game_event", "ctimer_get", "award_screen", "fx", "audit_add", "playfield_multiplier")

HEX40 = re.compile(rb"^[0-9a-f]{40}$")
REG = ("r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12", "sp", "lr", "pc")


# ---- instruction words -------------------------------------------------------------------
def rot_imm(w):
    rot, imm = (w >> 8) & 0xF, w & 0xFF
    return ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF if rot else imm


def encodable_imm8(v):
    """True if v fits `mov rd, #imm` (an 8-bit value rotated right by an even amount)."""
    v &= 0xFFFFFFFF
    for r in range(16):
        x = ((v << (2 * r)) | (v >> (32 - 2 * r))) & 0xFFFFFFFF if r else v
        if x <= 0xFF:
            return True
    return False


def imm16(w):
    return ((w >> 16) & 0xF) << 12 | (w & 0xFFF)


def branch_target(w, va):
    off = w & 0xFFFFFF
    if off & 0x800000:
        off -= 0x1000000
    return (va + 8 + off * 4) & 0xFFFFFFFF


def decode(w, va):
    """The few instruction shapes the tracker models, as a tuple; ('other', written regs) for
    anything else. ARM state only."""
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
    if (w & 0x0FFF8000) == 0x08BD8000:
        return ("poppc", cond)
    if (w & 0x0FFF4000) == 0x092D4000:
        return ("pushlr", cond)
    if (w & 0x0FFF0000) == 0x058D0000:
        return ("strsp", rd, w & 0xFFF, cond)
    if (w & 0x0FEF0FF0) == 0x01A00000:
        return ("movr", rd, w & 0xF, cond)
    if (w & 0x0FE00000) == 0x02800000:
        return ("addi", rd, rn, rot_imm(w), cond)
    if (w & 0x0FE00000) == 0x02400000:
        return ("subi", rd, rn, rot_imm(w), cond)
    if (w & 0x0FF00000) == 0x02100000:
        return ("andsi", rd, rn, rot_imm(w), cond)
    if (w & 0x0F700000) == 0x05100000:                       # ldr rt, [rn, #+-imm] (no writeback)
        imm = w & 0xFFF
        return ("ldri", rd, rn, imm if w & 0x00800000 else -imm, cond)
    return ("other", written(w), cond)


def written(w):
    """Registers an instruction outside decode()'s shapes may write (conservative)."""
    op = (w >> 25) & 7
    rd = (w >> 12) & 0xF
    rn = (w >> 16) & 0xF
    if op in (0, 1):
        if (w & 0x0F0000F0) == 0x00000090:                    # multiply family: rd at 19:16
            return (rn, rd)
        if (w & 0x0FB00FF0) == 0x01000090:                    # swp
            return (rd,)
        if (w & 0x0E000090) == 0x00000090 and (w & 0x60):     # extra load/store (ldrh, ldrsb, strd)
            out = []
            if w & 0x00100000:
                out.append(rd)
                if (w & 0xF0) == 0xD0 and not w & 0x00100000:
                    pass
            if (w & 0x00100000) == 0 and (w & 0xF0) == 0xD0:  # ldrd: rt and rt+1
                out += [rd, (rd + 1) & 0xF]
            if not (w & 0x01000000) or (w & 0x00200000):
                out.append(rn)
            return tuple(out)
        opcode = (w >> 21) & 0xF
        if 8 <= opcode <= 11 and (w & 0x00100000):             # tst teq cmp cmn
            return ()
        if (w & 0x0FBF0FFF) == 0x010F0000 or (w & 0x0FF000F0) == 0x01200010:   # mrs, bx
            return (rd,) if (w & 0x0FBF0FFF) == 0x010F0000 else ()
        return (rd,)
    if op in (2, 3):                                          # ldr/str
        out = [rd] if w & 0x00100000 else []
        if not (w & 0x01000000) or (w & 0x00200000):
            out.append(rn)
        return tuple(out)
    if op == 4:                                               # ldm/stm
        out = [r for r in range(16) if (w >> r) & 1] if w & 0x00100000 else []
        if w & 0x00200000:
            out.append(rn)
        return tuple(out)
    if op == 5:
        return (14,) if (w >> 24) & 1 else ()
    return tuple(range(4)) + (rd,)                            # coprocessor / VFP: be conservative


# ---- a tracked value --------------------------------------------------------------------
class Val:
    """A constant and the instruction(s) that made it: sites = ((va, word, how), ...), how in
    imm/movw/movt/lit/data/mvn/add/sub/copy. cond = made by a conditional instruction."""
    __slots__ = ("v", "sites", "cond", "lit")

    def __init__(self, v, sites, cond=False, lit=None):
        self.v, self.sites, self.cond, self.lit = v & 0xFFFFFFFF, tuple(sites), cond, lit

    def __eq__(self, o):
        return isinstance(o, Val) and o.v == self.v and o.sites == self.sites

    def __hash__(self):
        return hash((self.v, self.sites))


def kind_of(val):
    """The kind grammar for a value: ('imm', va) | ('movw', va) | ('movwt', va, va) |
    ('lit', pool va) | ('data', va) | ('code', va). Words are the instruction words (the
    literal word itself for lit/data)."""
    if val is None:
        return None
    hows = [s[2] for s in val.sites]
    if hows == ["imm"] or hows == ["mvn"]:
        return ("imm", val.sites[0][0]), ["%08x" % val.sites[0][1]]
    if hows == ["movw"]:
        return ("movw", val.sites[0][0]), ["%08x" % val.sites[0][1]]
    if hows == ["movw", "movt"]:
        return ("movwt", val.sites[0][0], val.sites[1][0]), ["%08x" % s[1] for s in val.sites]
    if hows == ["lit"]:
        return ("lit", val.lit), ["%08x" % val.v]
    if hows and hows[-1] == "data":
        return ("data", val.lit), ["%08x" % val.v]
    return ("code", val.sites[-1][0] if val.sites else 0), ["%08x" % s[1] for s in val.sites]


def fmt_kind(k):
    return " ".join([k[0]] + ["0x%x" % x for x in k[1:]])


# ---- the ELF ----------------------------------------------------------------------------
class Image:
    def __init__(self, data):
        self.b = bytes(data)
        self.loads = rt.load_segments(self.b)
        self.va2off, self.off2va = rt.make_mappers(self.loads)
        text = [s for s in self.loads if s[4] & 1][0]
        self.tlo, self.thi = text[1], text[1] + text[2]
        self.sha1 = hashlib.sha1(self.b).hexdigest()
        self.code_end = self.thi
        try:
            shoff = struct.unpack_from("<I", self.b, 0x20)[0]
            shentsize, shnum, shstrndx = struct.unpack_from("<HHH", self.b, 0x2E)
            if shoff and shnum:
                raw = [struct.unpack_from("<10I", self.b, shoff + i * shentsize) for i in range(shnum)]
                stroff = raw[shstrndx][4]
                for sh in raw:
                    nm = self.b[stroff + sh[0]:self.b.find(b"\0", stroff + sh[0])]
                    if nm == b".text":
                        self.code_end = sh[3] + sh[5]
        except struct.error:
            pass

    def word(self, va):
        o = self.va2off(va)
        if o is None or o + 4 > len(self.b):
            return None
        return struct.unpack_from("<I", self.b, o)[0]

    def in_text(self, va):
        return self.tlo <= va < self.code_end

    def writable_file(self, va):
        for off, v, fsz, _msz, flg in self.loads:
            if v <= va < v + fsz:
                return bool(flg & 2)
        return False

    def is_address(self, v):
        for _off, va, _fsz, msz, _flg in self.loads:
            if va <= v < va + msz:
                return True
        return False

    def cstring(self, va, cap=120):
        o = self.va2off(va)
        if o is None:
            return None
        end = self.b.find(b"\0", o, o + cap)
        if end <= o:
            return None
        s = self.b[o:end]
        if len(s) < 3 or any(c < 0x20 or c > 0x7E for c in s):
            return None
        return s.decode("latin1")


# ---- one function -------------------------------------------------------------------------
TERMINATORS = ("poppc", "bxlr")


def function_extent(img, start, cap=6000):
    """(end VA, set of literal-pool VAs) - scans forward from start until a return or an
    unconditional branch at or past every forward branch target seen, skipping pools."""
    lits, far, va = set(), start, start
    n = 0
    while n < cap:
        if va in lits:
            va += 4
            n += 1
            continue
        w = img.word(va)
        if w is None:
            break
        d = decode(w, va)
        if d[0] == "ldrlit":
            lits.add(d[2])
        if d[0] in ("b", "bl") and d[0] == "b" and start <= d[1] < start + cap * 4:
            far = max(far, d[1])
        cond = d[-1]
        if cond == 0xE and (d[0] in TERMINATORS or d[0] == "b") and va >= far:
            return va + 4, lits
        if d[0] == "pushlr" and va > start and va > far:
            return va, lits
        va += 4
        n += 1
    return va, lits


def track(img, start, engine_by_va):
    """Walk one function linearly; return (calls, vcalls, strings). A call is
    {va, target, name, args: {r0..r3, sp0, sp4...: Val}}."""
    end, lits = function_extent(img, start)
    # branch sources per target, for the one-predecessor state hand-off
    sources = {}
    va = start
    while va < end:
        if va not in lits:
            w = img.word(va)
            d = decode(w, va)
            if d[0] == "b" and start <= d[1] < end:
                sources.setdefault(d[1], []).append(va)
        va += 4
    state, stack, saved = {}, {}, {}
    calls, vcalls, strings = [], [], []
    prev = None
    va = start
    while va < end:
        if va in lits:
            va += 4
            continue
        w = img.word(va)
        d = decode(w, va)
        if va in sources and va != start:
            srcs = sources[va]
            falls = not (prev is not None and prev[-1] == 0xE and (prev[0] in TERMINATORS or prev[0] == "b"))
            preds = []
            if any(s > va for s in srcs):
                preds = None                              # a loop: nothing is known
            else:
                preds = [saved.get(s, ({}, {})) for s in srcs]
                if falls:
                    preds.append((state, stack))
            if preds is None:
                state, stack = {}, {}
            else:
                st0, sk0 = preds[0]
                state = {r: v for r, v in st0.items() if all(p[0].get(r) == v for p in preds[1:])}
                stack = {o: v for o, v in sk0.items() if all(p[1].get(o) == v for p in preds[1:])}
        kind = d[0]
        cond = d[-1] != 0xE
        if kind == "movw":
            state[d[1]] = Val(d[2], [(va, w, "movw")], cond)
        elif kind == "movt":
            lo = state.get(d[1])
            if lo is not None and [s[2] for s in lo.sites] == ["movw"]:
                state[d[1]] = Val(d[2] << 16 | lo.v, list(lo.sites) + [(va, w, "movt")], cond or lo.cond)
            else:
                state.pop(d[1], None)
        elif kind in ("mov", "mvn"):
            if cond and d[1] in state:
                state[d[1]] = Val(d[2], [(va, w, "imm" if kind == "mov" else "mvn")], True)
            else:
                state[d[1]] = Val(d[2], [(va, w, "imm" if kind == "mov" else "mvn")], cond)
        elif kind == "ldrlit":
            lw = img.word(d[2])
            if lw is None:
                state.pop(d[1], None)
            else:
                state[d[1]] = Val(lw, [(va, w, "lit")], cond, lit=d[2])
                s = img.cstring(lw) if img.is_address(lw) else None
                if s:
                    strings.append((va, s, ("lit", d[2]), ["%08x" % lw]))
        elif kind == "movr":
            if d[2] in state:
                src = state[d[2]]
                state[d[1]] = Val(src.v, src.sites, src.cond or cond, src.lit)
            else:
                state.pop(d[1], None)
        elif kind in ("addi", "subi"):
            src = state.get(d[2])
            if src is not None and d[2] != 15:
                nv = src.v + d[3] if kind == "addi" else src.v - d[3]
                state[d[1]] = Val(nv, list(src.sites) + [(va, w, "add" if kind == "addi" else "sub")],
                                  src.cond or cond, src.lit)
            else:
                state.pop(d[1], None)
        elif kind == "andsi":
            state.pop(d[1], None)
            pass                            # beq after it: see the "b" case (the register is 0 there)
        elif kind == "strsp":
            if d[1] in state:
                stack[d[2]] = state[d[1]]
            else:
                stack.pop(d[2], None)
        elif kind == "ldri":
            base = state.get(d[2])
            state.pop(d[1], None)
            if base is not None and d[2] != d[1] and img.writable_file(base.v + d[3]):
                dv = img.word(base.v + d[3])
                if dv is not None:
                    state[d[1]] = Val(dv, list(base.sites) + [(va, w, "data")], cond, lit=base.v + d[3])
            # a virtual call: ldr rX,[rY]; ldr rX,[rX,#4n]; blx rX
            if d[3] >= 0 and d[3] % 4 == 0 and d[1] == d[2]:
                state[("vslot", d[1])] = d[3] // 4
        elif kind == "bl":
            name = engine_by_va.get(d[1])
            args = {REG[r]: state[r] for r in range(4) if r in state}
            for o, v in stack.items():
                args["sp%d" % o] = v
            calls.append({"va": va, "target": d[1], "name": name, "args": args})
            for r in (0, 1, 2, 3, 12, 14):
                state.pop(r, None)
            state = {k: v for k, v in state.items() if not isinstance(k, tuple)}
            stack = {}
        elif kind == "blx":
            slot = state.get(("vslot", d[1]))
            if slot is not None:
                args = {REG[r]: state[r] for r in range(1, 4) if r in state}
                vcalls.append({"va": va, "slot": slot, "args": args})
            for r in (0, 1, 2, 3, 12, 14):
                state.pop(r, None)
            state = {k: v for k, v in state.items() if not isinstance(k, tuple)}
            stack = {}
        elif kind == "b":
            st, sk = dict(state), dict(stack)
            if d[-1] == 0x0 and prev is not None and prev[0] == "andsi":   # beq after ands rd: rd == 0
                st[prev[1]] = Val(0, [(va - 4, img.word(va - 4), "code")], False)
            saved[va] = (st, sk)
            if not (start <= d[1] < end) and d[-1] == 0xE:
                calls.append({"va": va, "target": d[1], "name": engine_by_va.get(d[1]),
                              "args": {REG[r]: state[r] for r in range(4) if r in state}, "tail": True})
        else:
            for r in (d[1] if kind == "other" else ()):
                state.pop(r, None)
        # movw/movt building a string address
        if kind == "movt" and d[1] in state:
            v = state[d[1]]
            s = img.cstring(v.v) if img.is_address(v.v) else None
            if s:
                k, words = kind_of(v)
                strings.append((va, s, k, words))
        prev = d
        va += 4
    return calls, vcalls, strings, end


# ---- the model ---------------------------------------------------------------------------
def plausible_function(img, fn):
    """A vtable entry is a function only if it starts where a function can: a push, or right
    after a return / an unconditional branch / a literal-pool word. The RTTI walk counts slots
    until the next typeinfo, so a vtable's tail can hold rodata words that point mid-code."""
    if fn is None or not img.in_text(fn) or fn & 3:
        return False
    d = decode(img.word(fn), fn)
    if d[0] == "pushlr":
        return True
    pw = img.word(fn - 4)
    p = decode(pw, fn - 4)
    flowing = p[0] in ("movw", "movt", "mov", "mvn", "addi", "subi", "andsi", "ldri", "strsp", "movr", "ldrlit") or (
        p[0] == "other" and (pw >> 26) & 3 in (0, 1) and (pw & 0x0FFFFFF0) != 0x012FFF10)
    if not flowing or p[-1] != 0xE or pw in (0xE320F000, 0xE1A00000):     # padding nops too
        return True                  # after a return, a tail call, a no-return bl, a pool word
    return literal_readers(img, fn - 4, near=1024) > 0


_VSLOTS = {}


def vslots(img, model, cls):
    """The class's virtual functions, cut at the first entry that is not a function."""
    m = model.get(cls)
    if not m or not m.get("vtable"):
        return []
    key = (id(img), cls)
    if key not in _VSLOTS:
        out = []
        for k in range(m["nvirt"]):
            f = img.word(m["vtable"] + 8 + 4 * k)
            if not plausible_function(img, f):
                break
            out.append(f)
        _VSLOTS[key] = out
    return _VSLOTS[key]


def locate_engine(img_path, ref_path):
    """Engine names -> VA on another build, through port_tool.locate from Pro 1.15."""
    sys.path.insert(0, HERE)
    import port_tool as pt
    ref, tgt = pt.Elf(ref_path), pt.Elf(img_path)
    rf, tf = pt.Finder(ref), pt.Finder(tgt)
    out, missed = {}, {}
    for name, (va, roles) in ENGINE_PRO115.items():
        ti, why = pt.locate(ref, rf, tgt, tf, ref.idx(va))
        if ti is None:
            missed[name] = why
        else:
            out[name] = (tgt.va(ti), roles)
    return out, missed


def manager_ctor(img, model):
    """The cmode_manager constructor VA: the function that stores its vptr and makes the
    most __cxa_guard_acquire calls (one per static mode object)."""
    m = model.get("cmode_manager")
    if not m or not m.get("vtable"):
        return None
    vptr = m["vtable"] + 8
    lo = img.va2off(img.tlo)
    hits = []
    b = img.b
    needle = struct.pack("<I", vptr)
    i = b.find(needle, lo, img.va2off(img.thi - 4))
    while i >= 0:
        va = img.off2va(i)
        # a literal: find the ldr that loads it, then the push before it
        for k in range(4, 4096, 4):
            w = img.word(va - k)
            if w is None:
                break
            d = decode(w, va - k)
            if d[0] == "ldrlit" and d[2] == va:
                s = va - k
                for j in range(0, 64 * 4, 4):
                    dd = decode(img.word(s - j), s - j)
                    if dd[0] == "pushlr":
                        hits.append(s - j)
                        break
                break
        i = b.find(needle, i + 4, img.va2off(img.thi - 4))
    best, most = None, 0
    for f in set(hits):
        end, lits = function_extent(img, f)
        n = 0
        for va in range(f, end, 4):
            if va in lits:
                continue
            d = decode(img.word(va), va)
            if d[0] == "bl":
                n += 1
        if n > most:
            best, most = f, n
    return best


def build(img, model, engine):
    engine_by_va = {va: name for name, (va, _r) in engine.items()}
    classes = {k for k in model if k.startswith("cmode_") and k not in ("cmode_manager",)}
    dtor = {}
    for c in classes:
        s = vslots(img, model, c)
        if s:
            dtor.setdefault(s[0], []).append(c)
    ctor_va = manager_ctor(img, model)
    modes = []
    if ctor_va:
        calls, _v, _s, _e = track(img, ctor_va, engine_by_va)
        for i, c in enumerate(calls):
            if c.get("name") or c.get("tail"):
                continue
            r0, r1 = c["args"].get("r0"), c["args"].get("r1")
            if r0 is None or r1 is None or not img.is_address(r0.v) or r1.v > 64:
                continue
            nxt = calls[i + 1:i + 3]
            cls = None
            for n in nxt:
                d1 = n["args"].get("r1")
                if d1 is not None and d1.v in dtor and len(dtor[d1.v]) == 1:
                    cls = dtor[d1.v][0]
                    break
            if cls is None:
                continue
            args = [c["args"].get(k) for k in ("r2", "r3", "sp0", "sp4")]
            modes.append({"id": r1.v, "class": cls, "object": r0.v, "ctor": c["target"], "ctor_call": c["va"],
                          "args": [a.v if a is not None else None for a in args]})
    modes.sort(key=lambda m: m["id"])
    return ctor_va, modes


def mode_facts(img, model, engine, cls):
    """Per overridden virtual of cls: its calls, vcalls and strings."""
    engine_by_va = {va: name for name, (va, _r) in engine.items()}
    mine = vslots(img, model, cls)
    base = ancestor_with_vtable(model, cls)
    theirs = vslots(img, model, base) if base else []
    out = []
    for k, fn in enumerate(mine):
        if fn is None or not img.in_text(fn):
            continue
        if k < len(theirs) and theirs[k] == fn:
            continue
        calls, vcalls, strings, end = track(img, fn, engine_by_va)
        out.append({"slot": k, "fn": fn, "end": end, "new": k >= len(theirs),
                    "calls": calls, "vcalls": vcalls, "strings": strings})
    return base, out


def const_return(img, fn):
    """A slot that returns a constant: (value, kind, words) or None (v[27]/v[28]/v[29])."""
    w0, w1 = img.word(fn), img.word(fn + 4)
    if w0 is None or w1 is None:
        return None
    d0, d1 = decode(w0, fn), decode(w1, fn + 4)
    if d1[0] == "bxlr" and d0[0] in ("mov", "movw") and d0[1] == 0:
        return d0[2], ("imm" if d0[0] == "mov" else "movw", fn), ["%08x" % w0]
    if d1[0] == "bxlr" and d0[0] == "ldrlit" and d0[1] == 0:
        return img.word(d0[2]), ("lit", d0[2]), ["%08x" % img.word(d0[2])]
    return None


def starters(img, model, engine):
    """[(mode id, slot called, call VA, holder function, holder class::slot)] for every
    cmode_manager_get(mgr, id) whose result has a slot called within 12 instructions."""
    get = engine.get("cmode_manager_get")
    if not get:
        return []
    fn_owner = {}
    for c, m in model.items():
        for k, f in enumerate(vslots(img, model, c)):
            if f is not None:
                fn_owner.setdefault(f, "%s::v[%d]" % (c, k))
    out = []
    lo = img.va2off(img.tlo)
    n = (img.thi - img.tlo) // 4
    words = struct.unpack_from("<%dI" % n, img.b, lo)
    for i, w in enumerate(words):
        if (w & 0x0F000000) != 0x0B000000:
            continue
        va = img.tlo + 4 * i
        if branch_target(w, va) != get[0]:
            continue
        # the id: the last write to r1 in the 8 instructions before
        rid = None
        for k in range(1, 9):
            d = decode(words[i - k], va - 4 * k)
            if d[0] in ("mov", "movw") and d[1] == 1:
                rid = d[2]
                break
            if d[0] in ("bl", "blx") or (d[0] == "other" and 1 in d[1]) or (d[0] in ("movr", "ldri", "ldrlit", "addi", "subi", "movt") and d[1] == 1):
                break
        slot = None
        for k in range(1, 13):
            d = decode(words[i + k], va + 4 * k)
            if d[0] == "ldri" and d[3] >= 0 and d[3] % 4 == 0 and d[1] == d[2] and d[3] > 0:
                slot = d[3] // 4
            if d[0] == "blx" and slot is not None:
                break
            if d[0] == "bl":
                slot = None
                break
        holder = None
        for k in range(0, 6000):
            if i - k < 0:
                break
            if decode(words[i - k], va - 4 * k)[0] == "pushlr":
                holder = va - 4 * k
                break
        out.append((rid, slot, va, holder, fn_owner.get(holder)))
    return out


def ancestor_with_vtable(model, cls):
    """The class whose slots cls is compared against: the nearest base with a vtable of its
    own, and for an abstract base (cmode_mball, cmode_hurry_up have none) its concrete
    `<base>_null` twin, which keeps every slot the base implements."""
    b = model.get(cls, {}).get("base")
    while b and not (model.get(b) or {}).get("vtable"):
        null = b + "_null"
        if (model.get(null) or {}).get("vtable") and null != cls:
            return null
        b = model.get(b, {}).get("base")
    return b


# Pro 1.15's cmode / cmode_timed slot roles (MODE_API.md). The KEY of a number carries the role,
# never the slot: Premium/LE has one more slot at every cmode level.
ROLE_PRO115 = {3: "reset", 4: "ball_end", 5: "ball_reset", 6: "qualify", 7: "can_start", 8: "start",
               9: "resume", 10: "end", 11: "stop", 15: "on_shots", 41: "shot", 42: "start_display",
               43: "total_display", 44: "initial_mask", 48: "add_time", 55: "countdown", 56: "timer",
               57: "timer"}
TIMED_ONLY = (48, 55, 56, 57)
STARTER_ROLES = {6: "qualify", 8: "start", 11: "stop"}
SKIP_ROLES = ("_", "mgr", "aw", "handler", "obj", "group", "notify", "flags", "idx", "a", "b", "loop", "crop")


# Pro 1.15 slot -> this build's slot. Identity on Pro 1.15; slot_map() fills it for another build.
SLOT = {}


def S(k):
    return SLOT.get(k, k)


def pro_slot(j):
    """This build's slot -> Pro 1.15's. A slot past the mapped levels (a subclass's own) takes
    the shift of the nearest mapped slot below it."""
    if not SLOT or j is None:
        return j
    for k, v in SLOT.items():
        if v == j:
            return k
    below = [v for v in SLOT.values() if v < j]
    if not below:
        return j
    v = max(below)
    k = [kk for kk, vv in SLOT.items() if vv == v][0]
    guess = j - (v - k)
    return None if guess in SLOT else guess


def slot_map(ref_path, tgt_path):
    """{Pro 1.15 slot: target slot} for cmode's and cmode_timed's own slots: each Pro base
    function located in the target (port_tool's masked signatures) and found in the target's
    base vtable. A slot whose function is not unique (a shared no-op) takes the shift of the
    nearest located slot below it, if the nearest located slot above agrees; otherwise it is
    left out, and its role reads as v<k>."""
    sys.path.insert(0, HERE)
    import port_tool as pt
    ref, tgt = pt.Elf(ref_path), pt.Elf(tgt_path)
    rf, tf = pt.Finder(ref), pt.Finder(tgt)
    rimg, timg = Image(ref.b), Image(tgt.b)
    rmodel, tmodel = rt.build_model(ref.b), rt.build_model(tgt.b)
    out = {}
    for level, parent in (("cmode", None), ("cmode_timed", "cmode")):
        rs, ts = vslots(rimg, rmodel, level), vslots(timg, tmodel, level)
        lo = len(vslots(rimg, rmodel, parent)) if parent else 0
        tlo = len(vslots(timg, tmodel, parent)) if parent else 0
        found = {}
        for k in range(lo, len(rs)):
            if rs.count(rs[k]) > 1:
                continue
            ti, _why = pt.locate(ref, rf, tgt, tf, ref.idx(rs[k]))
            if ti is None:
                continue
            va = tgt.va(ti)
            js = [j for j in range(tlo, len(ts)) if ts[j] == va]
            if len(js) == 1:
                found[k] = js[0]
        for k in range(lo, len(rs)):
            if k in found:
                out[k] = found[k]
                continue
            below = [b for b in found if b < k]
            above = [a for a in found if a > k]
            if below:
                d = found[max(below)] - max(below)
                if not above or found[min(above)] - min(above) == d:
                    out[k] = k + d
    return out


def role_of(model, cls, slot):
    slot = pro_slot(slot)
    if slot is None:
        return "v?"
    if slot in TIMED_ONLY:
        c = cls
        while c and c != "cmode_timed":
            c = model.get(c, {}).get("base")
        if c != "cmode_timed":
            return "v%d" % slot
    return ROLE_PRO115.get(slot, "v%d" % slot)


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def display_layers(model, mode_classes):
    """{mode class: [BDL display-layer classes]} by name: BDLTeslaStrikeBG belongs to
    cmode_tesla_strike. A layer goes to the mode with the LONGEST name it starts with, so
    BDLKingOfTheMonstersMultiballStart is the multiball's, not king of the monsters'."""
    keys = sorted(((_norm(c[len("cmode_"):]), c) for c in mode_classes), key=lambda kc: -len(kc[0]))
    out = {}
    for layer in sorted(model):
        if not layer.startswith("BDL"):
            continue
        n = _norm(layer[3:])
        for k, c in keys:
            if n.startswith(k):
                out.setdefault(c, []).append(layer)
                break
    return out


def layer_strings(img, model, engine_by_va, layer):
    """[(slot, va, string, kind, words)] loaded by the layer's own virtuals (not its base's)."""
    mine = vslots(img, model, layer)
    base = ancestor_with_vtable(model, layer)
    theirs = vslots(img, model, base) if base else []
    out = []
    for k, fn in enumerate(mine):
        if fn is None or not img.in_text(fn) or (k < len(theirs) and theirs[k] == fn):
            continue
        _c, _v, strings, _e = track(img, fn, engine_by_va)
        for va, st, kind, words in strings:
            out.append((k, va, st, kind, words))
    return out


def holders(img, model):
    """{function VA: set of cmode classes whose vtable holds it}."""
    out = {}
    for c in model:
        if not c.startswith("cmode_") or c == "cmode_manager":
            continue
        for f in vslots(img, model, c):
            if f is not None:
                out.setdefault(f, set()).add(c)
    return out


def literal_readers(img, pool_va, near=4096):
    """How many `ldr rX, [pc, #off]` within +-near bytes load the pool word at pool_va."""
    n = 0
    for va in range(max(img.tlo, pool_va - near), min(img.thi, pool_va + near), 4):
        w = img.word(va)
        if w is not None and (w & 0x0F7F0000) == 0x051F0000:
            imm = w & 0xFFF
            if va + 8 + (imm if w & 0x00800000 else -imm) == pool_va:
                n += 1
    return n


def timer_key(slot):
    return {56: "timer.seconds", 57: "timer.v57"}.get(slot, "timer.v%d" % slot)


def derives(model, cls, base):
    c = cls
    while c:
        if c == base:
            return True
        c = model.get(c, {}).get("base")
    return False


def timer_lines(img, model, engine, m, slots, p, entry, held, mode_classes):
    """cmode_timed's start hands the timer v[56]() (the duration, timer v[16] and v[12]) and
    v[57]() (timer v[18]); when a slot is the base's, the game inlines the base's 30 with a
    conditional mov in cmode_timed's reset and start - so the default is THREE words."""
    if not derives(model, m["class"], "cmode_timed") or len(slots) <= S(57):
        return
    base = vslots(img, model, "cmode_timed")
    users = lambda fn: len(held.get(fn, set()) & mode_classes)  # noqa: E731
    for pk in (56, 57):
        k = S(pk)
        fn = slots[k]
        key = timer_key(pk)
        r = const_return(img, fn)
        if fn == base[k] and r:
            inl = []
            for f in (base[S(3)], base[S(8)]):
                end, lits = function_extent(img, f)
                for va in range(f, end, 4):
                    if va in lits:
                        continue
                    d = decode(img.word(va), va)
                    if d[0] != "mov" or d[-1] != 0x0 or d[2] != r[0]:
                        continue
                    # the devirtualised copy: `ldr rX, [vptr, #4k]; ... cmp; moveq rY, #default`
                    back = [decode(img.word(va - 4 * j), va - 4 * j) for j in range(1, 5)]
                    if any(b[0] == "ldri" and b[3] == 4 * k for b in back):
                        inl.append(va)
            sites = ", ".join("0x%x" % v for v in [fn] + inl)
            p("number %d %s %d code 0x%x - code shared %d  # the base default: mov #%d at %s - all of them, or a hook"
              % (m["id"], key, r[0], fn, users(fn), r[0], sites))
            entry["numbers"].append({"key": key, "value": r[0], "kind": ["code", fn], "words": [], "class": "code",
                                     "shared": users(fn), "sites": [fn] + inl, "slot": k})
        elif r:
            sh = users(fn)
            p("number %d %s %d %s %s word%s  # v[%d] returns it" % (m["id"], key, r[0], fmt_kind(r[1]), ",".join(r[2]),
                                                                   " shared %d" % sh if sh > 1 else "", k))
            entry["numbers"].append({"key": key, "value": r[0], "kind": list(r[1]), "words": r[2], "class": "word",
                                     "shared": sh, "slot": k})
        else:
            w0 = img.word(fn)
            d0 = decode(w0, fn) if w0 is not None else ("other",)
            if d0[0] == "ldri" and d0[2] == 0 and d0[1] == 0:
                p("number %d %s ? code 0x%x - code  # v[%d] reads the object's field +0x%x; set elsewhere, not measured"
                  % (m["id"], key, fn, k, d0[3]))
                entry["numbers"].append({"key": key, "value": None, "kind": ["code", fn], "words": [], "class": "code",
                                         "field": d0[3], "slot": k})
            elif fn != base[k] and not any(c["name"] == "get_adjustment" for c in track(img, fn, {va: n for n, (va, _r) in engine.items()})[0]):
                p("number %d %s ? code 0x%x - code  # v[%d] computes it; not measured" % (m["id"], key, fn, k))
                entry["numbers"].append({"key": key, "value": None, "kind": ["code", fn], "words": [], "class": "code",
                                         "slot": k})


# ---- which shots a mode lights, and selector tables ------------------------------------------
# Godzilla Pro 1.15's switch -> shot bit (MODE_API.md "Switch -> shot bit", one swpoke each). Only
# used to NAME a mask's bits in a comment; the mask itself is read from the code.
SHOT_BITS_GODZILLA = {7: "left spinner", 9: "left spinner", 10: "left spinner", 11: "top spinner",
                      13: "top spinner", 14: "top spinner", 15: "right spinner", 17: "right spinner",
                      18: "right spinner", 33: "right spinner", 19: "godzilla target", 20: "left ramp",
                      21: "right ramp", 22: "building", 27: "maser target", 28: "powerline left",
                      29: "powerline center", 30: "powerline right", 31: "shield left", 32: "shield right",
                      34: "skill shot", 36: "big loop"}


def const_return64(img, fn, cap=8):
    """A slot that returns a 64-bit constant in r0:r1 (v[44], the lit-shot mask a start sets):
    ({0: lo, 1: hi}, {0: sites, 1: sites}, tail target or None) or None. Sites are (va, word, how)
    with how in mov/mvn/movw/movt. Only unconditional mov/mvn/movw/movt on r0/r1, then `bx lr`
    or a tail `b` (which may change the mask: the caller says so)."""
    val, sites = {0: None, 1: None}, {0: [], 1: []}
    for i in range(cap):
        va = fn + 4 * i
        w = img.word(va)
        if w is None:
            return None
        d = decode(w, va)
        if d[-1] != 0xE:
            return None
        if d[0] in ("mov", "mvn", "movw") and d[1] in (0, 1):
            val[d[1]], sites[d[1]] = d[2], [(va, w, d[0])]
        elif d[0] == "movt" and d[1] in (0, 1) and val[d[1]] is not None:
            val[d[1]] = (val[d[1]] & 0xFFFF) | (d[2] << 16)
            sites[d[1]].append((va, w, "movt"))
        elif d[0] in ("bxlr", "b") and val[0] is not None and val[1] is not None:
            return val, sites, (d[1] if d[0] == "b" else None)
        else:
            return None
    return None


def half_kind(s):
    """(kind tuple, words) for one half of a const_return64 value. A `mov` then `movt` on one
    register is written as movwt: two words, low half then high (the low word is a `mov`)."""
    hows = [h for _va, _w, h in s]
    words = ["%08x" % w for _va, w, _h in s]
    if hows in (["mov"], ["mvn"]):
        return ("imm", s[0][0]), words
    if hows == ["movw"]:
        return ("movw", s[0][0]), words
    if len(hows) == 2 and hows[1] == "movt":
        return ("movwt", s[0][0], s[1][0]), words
    return ("code", s[-1][0]), words


def mask_names(mask, names):
    bits = [b for b in range(64) if mask >> b & 1]
    out = []
    for b in bits:
        n = names.get(b, "bit %d" % b)
        if n not in out:
            out.append(n)
    return ", ".join(out) or "none"


def mask_lines(img, model, m, slots, p, entry, held, mode_classes, names=None):
    """shots / number lines for the lit mask a start sets: `mask = v[44]()` (cmode's START)."""
    k = S(44)
    if len(slots) <= k:
        return
    fn = slots[k]
    users = len(held.get(fn, set()) & mode_classes)
    shs = " shared %d" % users if users > 1 else ""
    r = const_return64(img, fn)
    if r:
        val, sites, tail = r
        mask = val[1] << 32 | val[0]
        why = "then tail-calls 0x%x, which may change it" % tail if tail else "returned as a constant"
        base_slots = vslots(img, model, ancestor_with_vtable(model, m["class"]) or "cmode")
        own8 = len(slots) > S(8) and (len(base_slots) <= S(8) or slots[S(8)] != base_slots[S(8)])
        p("shots %d 0x%x v[%d] 0x%x, the lit mask cmode's START takes (%s)%s: %s" % (
            m["id"], mask, k, fn, why, "; this mode has its own start, which can write another mask" if own8 else "",
            mask_names(mask, names or {})))
        entry["shots"] = {"mask": mask, "fn": fn, "slot": k, "tail": tail, "shared": users}
        for half, ri in (("lo", 0), ("hi", 1)):
            kind, words = half_kind(sites[ri])
            cl = "code" if tail or kind[0] == "code" else "word"
            note = " (the low word is a mov)" if kind[0] == "movwt" and sites[ri][0][2] != "movw" else ""
            p("number %d initial_mask.%s %d %s %s %s%s  # v[%d] returns it (0x%x)%s" % (
                m["id"], half, val[ri], fmt_kind(kind), ",".join(words), cl, shs, k, val[ri], note))
            entry["numbers"].append({"key": "initial_mask.%s" % half, "value": val[ri], "kind": list(kind),
                                     "words": words, "class": cl, "shared": users, "slot": k})
        return
    w0 = img.word(fn)
    if w0 is not None and (w0 & 0x0E5000F0) == 0x004000D0 and ((w0 >> 16) & 0xF) == 0 and w0 >> 28 == 0xE:
        off = ((w0 >> 8) & 0xF) << 4 | (w0 & 0xF)
        p("shots %d ? v[%d] 0x%x returns the object's field +0x%x: set by other code, not measured" % (
            m["id"], k, fn, off))
        entry["shots"] = {"mask": None, "fn": fn, "slot": k, "field": off}
        return
    p("shots %d ? v[%d] 0x%x computes the lit mask: code" % (m["id"], k, fn))
    entry["shots"] = {"mask": None, "fn": fn, "slot": k}


def selector_tables(img, mode_ids, minimum=3):
    """[(table va, [mode id per slot])]: runs of 12-byte entries {slot index, mode id, 0} with the
    index counting from 0 and distinct mode ids - a table a selector screen starts modes from
    (Godzilla's battle select screen). Scans every loaded segment."""
    ids = set(mode_ids)
    b = img.b
    found = {}
    for first in sorted(ids):
        needle = struct.pack("<3I", 0, first, 0)
        i = b.find(needle)
        while i >= 0:
            va = img.off2va(i) if i % 4 == 0 else None
            if va is not None and va not in found:
                n, got = 0, []
                while i + 12 * (n + 1) <= len(b):
                    a, mid, z = struct.unpack_from("<3I", b, i + 12 * n)
                    if a != n or z != 0 or mid not in ids or mid in got:
                        break
                    got.append(mid)
                    n += 1
                if n >= minimum:
                    found[va] = got
            i = b.find(needle, i + 1)
    return sorted(found.items())


MANGLED = re.compile(r"^(L?N?\d|N\d|St|_Z)|__")


# ---- the report ----------------------------------------------------------------------------
def adjustment_names(img):
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))
        from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
        t = AdjustmentTable(img.b)
        return {i: t.entry(i) for i in range(t.count)}
    except Exception:
        return {}


def report(img, model, engine, game, version, out=sys.stdout, reader_notes=True):
    adj = adjustment_names(img)
    ctor_va, modes = build(img, model, engine)
    held = holders(img, model)
    mode_classes = {m["class"] for m in modes}
    layers = display_layers(model, mode_classes)
    p = lambda s="": out.write(s + "\n")  # noqa: E731
    p("build %s %s sha1 %s" % (game, version, img.sha1))
    p("# read by stock_modes.py: cmode_manager constructor 0x%x, %d mode objects" % (ctor_va or 0, len(modes)))
    starts = starters(img, model, engine)
    selectors = selector_tables(img, [m["id"] for m in modes])
    shot_names = SHOT_BITS_GODZILLA if game.startswith("godzilla") else {}
    data = {"build": {"game": game, "version": version, "sha1": img.sha1, "ctor": ctor_va}, "modes": []}
    for m in modes:
        cls = m["class"]
        mv = model[cls]
        base, facts = mode_facts(img, model, engine, cls)
        slots = vslots(img, model, cls)
        title = const_return(img, slots[S(27)]) if len(slots) > S(29) else None
        a = ["-" if x is None else str(x) for x in m["args"]]
        p()
        p("mode %d %s obj 0x%x vtable 0x%x title_msg %s" % (m["id"], cls, m["object"], mv["vtable"],
                                                           title[0] if title else "?"))
        p("ctor %d a %s award %s b %s timer %s   # %s, ctor 0x%x called at 0x%x; compared against %s, %d virtuals"
          % (m["id"], a[0], a[1], a[2], a[3], mv.get("base"), m["ctor"], m["ctor_call"], base, mv["nvirt"]))
        entry = {"id": m["id"], "class": cls, "object": m["object"], "vtable": mv["vtable"], "base": mv.get("base"),
                 "compared_with": base, "ctor_args": m["args"], "ctor": m["ctor"], "ctor_call": m["ctor_call"],
                 "numbers": [], "strings": [], "starts": [],
                 "vcalls": []}
        seen_keys = {}
        timer_lines(img, model, engine, m, slots, p, entry, held, mode_classes)
        mask_lines(img, model, m, slots, p, entry, held, mode_classes, shot_names)
        for tva, order in selectors:
            if m["id"] not in order:
                continue
            n = order.index(m["id"])
            wva = tva + 12 * n + 4
            p("start %d select: slot %d of the %d-entry selector table 0x%x {slot, mode id, 0} (%s); the screen that "
              "reads it is not traced by the tool" % (m["id"], n, len(order), tva, " ".join(str(x) for x in order)))
            p("number %d select.slot%d.mode_id %d data 0x%x %08x word  # which mode the selector's slot %d starts" % (
                m["id"], n, m["id"], wva, img.word(wva), n))
            entry["starts"].append({"how": "select", "call": None, "holder": None, "owner": None, "table": tva, "slot": n})
            entry["numbers"].append({"key": "select.slot%d.mode_id" % n, "value": m["id"], "kind": ["data", wva],
                                     "words": ["%08x" % img.word(wva)], "class": "word", "shared": 0})
        # (keys carry the ROLE of a slot; on another build the slot numbers are mapped from Pro 1.15's)

        def key_for(k):
            seen_keys[k] = seen_keys.get(k, 0) + 1
            return k if seen_keys[k] == 1 else "%s@%d" % (k, seen_keys[k])

        def shared_of(fn, kind):
            users = held.get(fn, set()) & mode_classes
            n = len(users)
            if kind and kind[0] == "lit":
                r = literal_readers(img, kind[1])
                n = max(n, r)
            return n

        for k, key in ((S(27), "title_msg"), (S(28), "audit_started"), (S(29), "audit_completed")):
            if len(slots) > k:
                r = const_return(img, slots[k])
                if r:
                    sh = shared_of(slots[k], r[1])
                    p("number %d %s %d %s %s word%s" % (m["id"], key, r[0], fmt_kind(r[1]), ",".join(r[2]),
                                                         " shared %d" % sh if sh > 1 else ""))
                    entry["numbers"].append({"key": key, "value": r[0], "kind": list(r[1]), "words": r[2],
                                             "class": "word", "shared": sh})
        readers = 0
        done = set()
        for rid, slot, va, holder, owner in starts:
            if rid != m["id"]:
                continue
            if pro_slot(slot) in STARTER_ROLES:
                if (slot, holder) in done:
                    continue
                done.add((slot, holder))
                how = STARTER_ROLES[pro_slot(slot)]
                p("start %d %s: cmode_manager_get(%d) at 0x%x then v[%d], in %s" % (
                    m["id"], how, m["id"], va, slot, owner or ("fn 0x%x" % holder if holder else "?")))
                entry["starts"].append({"how": how, "call": va, "holder": holder, "owner": owner})
            else:
                readers += 1
        if readers and reader_notes:
            p("# %d other cmode_manager_get(%d) sites read it (is_running, is_active, or a slot not traced)" % (readers, m["id"]))
        for f in facts:
            role = role_of(model, cls, f["slot"])
            tag = "v[%d]%s" % (f["slot"], " new" if f["new"] else "")
            for c in f["calls"]:
                if c["name"] not in NUMBER_CALLS:
                    continue
                roles = engine[c["name"]][1]
                args = c["args"]
                if c["name"] in ("caward_add", "score_add", "score_add_current"):
                    lo_r = "r2" if c["name"] != "score_add_current" else "r0"
                    hi_r = "r3" if c["name"] != "score_add_current" else "r1"
                    lo, hi = args.get(lo_r), args.get(hi_r)
                    key = key_for("%s.%s" % (role, c["name"]))
                    if lo is not None and hi is not None and hi.v == 0 and not lo.cond:
                        k, words = kind_of(lo)
                        cl = "word" if k[0] != "code" else "code"
                        sh = shared_of(f["fn"], k)
                        p("number %d %s %d %s %s %s%s  # %s call 0x%x" % (
                            m["id"], key, lo.v, fmt_kind(k), ",".join(words), cl, " shared %d" % sh if sh > 1 else "",
                            tag, c["va"]))
                        entry["numbers"].append({"key": key, "value": lo.v, "kind": list(k), "words": words,
                                                 "class": cl, "shared": sh, "slot": f["slot"], "call": c["va"]})
                    else:
                        sh = shared_of(f["fn"], None)
                        p("number %d %s ? code 0x%x - code%s  # %s: the value is computed before the call" % (
                            m["id"], key, c["va"], " shared %d" % sh if sh > 1 else "", tag))
                        entry["numbers"].append({"key": key, "value": None, "kind": ["code", c["va"]], "words": [],
                                                 "class": "code", "shared": sh, "slot": f["slot"], "call": c["va"]})
                    continue
                for ri, arole in enumerate(roles):
                    name = arole.split(":")[-1]
                    if name in SKIP_ROLES:
                        continue
                    rk = arole.split(":")[0] if ":" in arole else REG[ri]
                    v = args.get(rk)
                    if v is None or (img.is_address(v.v) and v.v > 0xFFFF):
                        continue
                    k, words = kind_of(v)
                    sh = shared_of(f["fn"], k)
                    shs = " shared %d" % sh if sh > 1 else ""
                    cq = " (set by a conditional instruction)" if v.cond else ""
                    if c["name"] == "get_adjustment":
                        e = adj.get(v.v)
                        nm = e["name"] if e else "AD_%d" % v.v
                        dflt = e["default"] if e else "?"
                        key = key_for(timer_key(pro_slot(f["slot"])) if role == "timer" else "%s.adjustment" % role)
                        p("number %d %s %s adj %s %d %s adjustment%s  # %s call 0x%x; the id is %s, range %s..%s"
                          % (m["id"], key, dflt, nm, v.v, ",".join(words), shs, tag, c["va"], fmt_kind(k),
                             e["min"] if e else "?", e["max"] if e else "?"))
                        entry["numbers"].append({"key": key, "value": dflt, "kind": ["adj", nm, v.v], "words": words,
                                                 "class": "adjustment", "shared": sh, "slot": f["slot"],
                                                 "call": c["va"], "id_kind": list(k)})
                        continue
                    cl = "word" if k[0] != "code" else "code"
                    if c["name"] in ("callout_play", "callout_play_nth", "sound_request_play", "sound_request_play_nth") \
                            and name == "req":
                        key = key_for("%s.%s" % (role, c["name"]))
                        p("callout %d %d %s %s %s%s  # %s call 0x%x%s" % (m["id"], v.v, key, fmt_kind(k), ",".join(words),
                                                                        shs, tag, c["va"], cq))
                        entry["strings"].append({"type": "callout", "value": v.v, "key": key, "kind": list(k),
                                                 "words": words, "shared": sh, "call": c["va"]})
                        continue
                    key = key_for("%s.%s.%s" % (role, c["name"], name))
                    p("number %d %s %d %s %s %s%s  # %s call 0x%x%s" % (m["id"], key, v.v, fmt_kind(k), ",".join(words),
                                                                      cl, shs, tag, c["va"], cq))
                    entry["numbers"].append({"key": key, "value": v.v, "kind": list(k), "words": words, "class": cl,
                                             "shared": sh, "slot": f["slot"], "call": c["va"], "conditional": v.cond})
            for vc in f["vcalls"]:
                for rk in ("r1", "r2", "r3"):
                    v = vc["args"].get(rk)
                    if v is None or img.is_address(v.v) and v.v > 0xFFFF:
                        continue
                    k, words = kind_of(v)
                    p("# vcall %d %s: [obj]->v[%d](%s=%d) %s %s  call 0x%x" % (m["id"], tag, vc["slot"], rk, v.v,
                                                                           fmt_kind(k), ",".join(words), vc["va"]))
                    entry["vcalls"].append({"slot": f["slot"], "vslot": vc["slot"], "reg": rk, "value": v.v,
                                            "kind": list(k), "words": words, "call": vc["va"]})
            for va, s, k, words in f["strings"]:
                sh = shared_of(f["fn"], k)
                shs = " shared %d" % sh if sh > 1 else ""
                if HEX40.match(s.encode()):
                    p("scene %d %s %s %s%s  # %s at 0x%x" % (m["id"], s, fmt_kind(k), ",".join(words), shs, tag, va))
                    entry["strings"].append({"type": "scene", "value": s, "kind": list(k), "words": words, "shared": sh})
                elif s.startswith("blel"):
                    p("lights %d ? %s  # %s at 0x%x" % (m["id"], s[:140], tag, va))
                    entry["strings"].append({"type": "lights", "value": s, "kind": list(k), "words": words, "shared": sh})
                elif re.match(r"^[A-Za-z][A-Za-z0-9_]{5,}$", s) and "_" in s and not MANGLED.search(s):
                    p("clip %d %s %s %s%s  # %s at 0x%x: a name %s loads" % (m["id"], s, fmt_kind(k), ",".join(words), shs,
                                                                           tag, va, role))
                    entry["strings"].append({"type": "clip", "value": s, "kind": list(k), "words": words, "shared": sh})
        engine_by_va = {va: n for n, (va, _r) in engine.items()}
        for layer in layers.get(cls, []):
            for k, va, st, kind, words in layer_strings(img, model, engine_by_va, layer):
                if HEX40.match(st.encode()):
                    p("scene %d %s %s %s  # %s::v[%d] at 0x%x" % (m["id"], st, fmt_kind(kind), ",".join(words), layer, k, va))
                    entry["strings"].append({"type": "scene", "value": st, "kind": list(kind), "words": words,
                                             "layer": layer})
                elif re.match(r"^[A-Za-z][A-Za-z0-9_]{5,}$", st) and "_" in st and not MANGLED.search(st):
                    p("clip %d %s %s %s  # %s::v[%d] at 0x%x: a name the display layer loads" % (
                        m["id"], st, fmt_kind(kind), ",".join(words), layer, k, va))
                    entry["strings"].append({"type": "clip", "value": st, "kind": list(kind), "words": words,
                                             "layer": layer})
        if layers.get(cls):
            p("# display layers: %s" % " ".join(layers[cls]))
        entry["virtuals"] = [[f["slot"], f["fn"], f["new"]] for f in facts]
        p("# overrides: %s" % " ".join("v[%d]=0x%x%s" % (f["slot"], f["fn"], "+" if f["new"] else "") for f in facts))
        data["modes"].append(entry)
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("elf")
    ap.add_argument("--ref", help="Godzilla Pro 1.15's game ELF, to locate the engine calls on another build")
    ap.add_argument("--game", default="godzilla_pro")
    ap.add_argument("--version", default="1.15")
    ap.add_argument("--json", help="also write the facts as JSON to this path (an OUTPUT; it is overwritten)")
    args = ap.parse_args(argv)
    data = open(args.elf, "rb").read()
    img = Image(data)
    model = rt.build_model(data)
    if img.sha1 == PRO115_SHA1:
        engine = ENGINE_PRO115
    elif args.ref:
        engine, missed = locate_engine(args.elf, args.ref)
        for k, why in sorted(missed.items()):
            print("# engine %s not located: %s" % (k, why))
        SLOT.update(slot_map(args.ref, args.elf))
        print("# slots mapped from Pro 1.15: %s" % " ".join("%d->%d" % kv for kv in sorted(SLOT.items()) if kv[0] != kv[1]))
    else:
        sys.exit("not Godzilla Pro 1.15 (sha1 %s): pass --ref <Pro 1.15 game ELF> to locate the engine calls" % img.sha1)
    out = report(img, model, engine, args.game, args.version)
    if args.json:
        if os.path.abspath(args.json) == os.path.abspath(args.elf):
            sys.exit("--json would overwrite the ELF")
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
