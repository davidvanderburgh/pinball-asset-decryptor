#!/usr/bin/env python3
"""Annotated disassembly and cross-references for a stripped Spike 2 game ELF (ARM).

The game ELFs have no .symtab, so a raw objdump range is a wall of hex. This names
what each instruction touches, from what the ELF still carries:
  - C++ classes (rtti_tree.build_model): a vptr load reads `vptr cmode_tesla_strike`,
    a call into a vtable slot function reads `cmode_timed::v[48]`
  - strings in .rodata, through a pc-relative literal or a movw/movt pair
  - PLT imports by name (`_Znwj`, `memcpy`, `__cxa_guard_acquire`) from .rel.plt
  - engine functions this rig already proved (ENGINE below; handoff addresses,
    godzilla Pro 1.15 only - a different build prints them wrong, so they are
    printed with a `?` suffix unless --title godzilla_pro_115 is passed)

Usage:
    armxref.py dis  <elf> <start> <end> [--title godzilla_pro_115]
    armxref.py xref <elf> <va> [<va>...] [--title godzilla_pro_115]
        callers by bl/blx, literal-pool loads, movw/movt pairs; each site with
        the start of the function holding it (nearest preceding push {..lr})

ARM state only (the Spike 2 game ELFs are ARM, the rig's pad_hook assumes it).
Read-only. Item 125, 2026-09-15.
"""
import argparse
import collections
import os
import re
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rtti_tree as rt  # noqa: E402

# Godzilla Pro 1.15. The first block is from plans/spike2_pc_emulation_handoff.md;
# the rest was read out of the disassembly for item 125 (plans/spike2_mode_api.md
# has the evidence for each). A trailing `?` inside a name = role inferred from its
# callers, not yet watched live. The handoff's 0x25feec "get_adjustment" is NOT one
# on this build (it lands mid-function); 0x45df38 is.
ENGINE_PRO115 = {
    0x4BB380: "hook_subscribe(_,id,handler,prio)",
    0x4BB42C: "hook_dispatch(id,arg)",
    0x2553FC: "fiber_yield",
    0x2551DC: "event_post(id,handler,flags)",
    0x4EC828: "tick_body_60hz",
    0x1E7540: "switch_drain",
    0x485918: "message_picker",
    0x7E4D48: "hook_table",
    0x7ABA5A: "global_mode_mask",
    0x45DF38: "get_adjustment(id)",
    0x457E00: "error_log(code)",
    0x460BA0: "current_player()",
    0x460A90: "player_check(p)",
    0x422DE4: "audit_add(id,n)",
    0x2A3108: "sound_request_play(req)",
    0x2A32BC: "sound_request_play_nth(req,n)",
    0x2A387C: "sound_request_active(req)",
    0x2A3C98: "sound_request_variants(req)",
    0x187F44: "callout_play(req)",
    0x18800C: "callout_play_nth(req,n)",
    0x2555DC: "event_post_replacing(id,handler,flags)",
    0x4F34E0: "show_start(id)?",
    0x44C320: "game_event(id,_,v64,a,b64)?",
    0x4B8E5C: "score_add_current(v64)?",
    0x30E48: "caward_get(mgr,id)",
    0x2FACC: "caward_add(aw,_,v64,idx)",
    0x2FB8C: "caward_add_scaled(aw,notify,idx,mult)",
    0x18B47C: "ctimer_get(mgr,idx)",
    0xD1C10: "cmode_manager_get(mgr,id)",
    0xD246C: "cmode_manager_started(mgr,id)",
    0xD24C4: "cmode_manager_stopped(mgr,id,reason)",
    0x7DCD0: "cmode_ctor(this,id,a,award,b)",
    0x11B168: "cmode_timed_ctor(this,id,a,award,b,timer)",
    0x79D954: "cmode_manager",
    0x79AC94: "ctimer_manager",
    0x79D660: "cawards_manager",
    0x7A1698: "mode_table[27]",
    0x7A1708: "mode_null",
    0x708170: "current_player_byte",
    0x7E11BC: "display_dirty",
}

OBJDUMP = "arm-linux-gnueabihf-objdump"


class Elf:
    def __init__(self, path, title=None):
        self.b = open(path, "rb").read()
        b = self.b
        self.loads = rt.load_segments(b)
        self.va2off, self.off2va = rt.make_mappers(self.loads)
        text = [s for s in self.loads if s[4] & 1][0]
        self.toff, self.tva, self.tsz = text[0], text[1], text[2]
        self.engine = ENGINE_PRO115
        self.engine_sure = title == "godzilla_pro_115"
        self._sections()
        self._plt()
        self._classes()

    def u32(self, va):
        o = self.va2off(va)
        if o is None or o + 4 > len(self.b):
            return None
        return struct.unpack_from("<I", self.b, o)[0]

    def _sections(self):
        b = self.b
        shoff = struct.unpack_from("<I", b, 0x20)[0]
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", b, 0x2E)
        self.sec = {}
        if not shoff or not shnum:
            return
        hdrs = [struct.unpack_from("<IIIIIIIIII", b, shoff + i * shentsize) for i in range(shnum)]
        stro = hdrs[shstrndx][4]
        for h in hdrs:
            e = b.find(b"\0", stro + h[0])
            self.sec[b[stro + h[0]:e].decode()] = h  # name, type, flags, addr, off, size, link, info, align, entsize

    def _plt(self):
        self.plt = {}
        if ".rel.plt" not in self.sec or ".plt" not in self.sec or ".dynsym" not in self.sec:
            return
        b = self.b
        rel = self.sec[".rel.plt"]
        dsym = self.sec[".dynsym"]
        dstr = self.sec[".dynstr"]
        got2name = {}
        for i in range(rel[5] // 8):
            r_off, r_info = struct.unpack_from("<II", b, rel[4] + 8 * i)
            si = r_info >> 8
            st_name = struct.unpack_from("<I", b, dsym[4] + 16 * si)[0]
            e = b.find(b"\0", dstr[4] + st_name)
            got2name[r_off] = b[dstr[4] + st_name:e].decode()
        plt = self.sec[".plt"]
        a = plt[3] + 20
        while a + 12 <= plt[3] + plt[5]:
            w0, w1, w2 = self.u32(a), self.u32(a + 4), self.u32(a + 8)
            if (w0 & 0xFFFFF000) == 0xE28FC000 and (w1 & 0xFFFFF000) == 0xE28CC000 and (w2 & 0xFFFFF000) == 0xE5BCF000:
                got = a + 8 + self._rot(w0) + self._rot(w1) + (w2 & 0xFFF)
                if got in got2name:
                    self.plt[a] = got2name[got] + "@plt"
            a += 12

    @staticmethod
    def _rot(w):
        imm, rot = w & 0xFF, ((w >> 8) & 0xF) * 2
        return ((imm >> rot) | (imm << (32 - rot))) & 0xFFFFFFFF if rot else imm

    def _classes(self):
        self.model = rt.build_model(self.b)
        self.vptr, self.tinfo, self.fnames = {}, {}, collections.defaultdict(list)
        for n, r in self.model.items():
            self.tinfo[r["typeinfo"]] = n
            if r["vtable"] is None:
                continue
            self.vptr[r["vtable"] + 8] = n
            for i in range(r["nvirt"]):
                f = self.u32(r["vtable"] + 8 + 4 * i)
                self.fnames[f].append("%s::v[%d]" % (n, i))

    def cstr(self, va):
        o = self.va2off(va)
        if o is None:
            return None
        e = self.b.find(b"\0", o, o + 200)
        if e - o < 3:
            return None
        s = self.b[o:e]
        if all(32 <= c < 127 for c in s):
            return s.decode()
        return None

    def name(self, v):
        """Best description of a 32-bit value, or None."""
        if v in self.plt:
            return self.plt[v]
        if v in self.engine:
            return self.engine[v] + ("" if self.engine_sure else "?")
        if v in self.vptr:
            return "vptr " + self.vptr[v]
        if v in self.tinfo:
            return "typeinfo " + self.tinfo[v]
        if v in self.fnames:
            f = self.fnames[v]
            return f[0] if len(f) == 1 else "%s (+%d vtables)" % (f[0], len(f) - 1)
        s = self.cstr(v) if self.tva <= v < self.tva + self.tsz else None
        if s:
            return '"%s"' % (s if len(s) <= 70 else s[:67] + "...")
        return None

    def fn_start(self, a, limit=4096):
        for k in range(limit):
            w = self.u32(a - 4 * k)
            if w is not None and (w & 0xFFFFC000) == 0xE92D4000:
                return a - 4 * k
        return None


def decode_refs(e, a, w, reg):
    """Values an instruction at `a` loads or branches to. `reg` tracks movw per Rd."""
    out = []
    if (w & 0x0F7F0000) == 0x051F0000:  # ldr Rt, [pc, #+-imm]
        t = a + 8 + ((w & 0xFFF) if w & (1 << 23) else -(w & 0xFFF))
        v = e.u32(t)
        if v is not None:
            out.append(v)
    elif (w & 0x0FFF0000) == 0x028F0000:  # add Rd, pc, #imm (adr)
        out.append(a + 8 + e._rot(w))
    elif (w & 0x0FF00000) == 0x03000000:  # movw
        reg[(w >> 12) & 0xF] = (((w >> 16) & 0xF) << 12) | (w & 0xFFF)
    elif (w & 0x0FF00000) == 0x03400000:  # movt
        rd = (w >> 12) & 0xF
        if rd in reg:
            out.append(((((w >> 16) & 0xF) << 12 | (w & 0xFFF)) << 16) | reg.pop(rd))
    elif (w & 0x0E000000) == 0x0A000000:  # b / bl (and blx imm when cond=0xF)
        off = w & 0xFFFFFF
        if off & 0x800000:
            off -= 0x1000000
        out.append((a + 8 + (off << 2)) & 0xFFFFFFFF)
    return out


def cmd_dis(e, start, end):
    p = subprocess.run([OBJDUMP, "-d", "--start-address=0x%x" % start, "--stop-address=0x%x" % end,
                        e.path], capture_output=True, text=True)
    line_re = re.compile(r"^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(.*)$")
    reg = {}
    for ln in p.stdout.splitlines():
        m = line_re.match(ln)
        if not m:
            continue
        a, w, rest = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
        rest = re.sub(r"\s*;\s*\(?[0-9a-f]+(\s*<[^>]*>)?\)?\s*$", "", rest)
        rest = re.sub(r"\s*<[^>]*>", "", rest)
        if (w & 0xFFFFC000) == 0xE92D4000:
            print("")
            reg = {}
        notes = [n for n in (e.name(v) for v in decode_refs(e, a, w, reg)) if n]
        if not notes and ((w & 0x0F7F0000) == 0x051F0000):
            t = a + 8 + ((w & 0xFFF) if w & (1 << 23) else -(w & 0xFFF))
            v = e.u32(t)
            if v is not None:
                notes.append("=0x%x" % v)
        elif not notes and (w & 0x0FF00000) == 0x03400000:
            pass
        print("%8x: %-44s%s" % (a, rest.replace("\t", " "), ("; " + " | ".join(notes)) if notes else ""))


def cmd_xref(e, targets):
    targets = set(targets)
    pool = collections.defaultdict(list)  # pool slot va -> value, if value in targets
    for o in range(e.toff, e.toff + e.tsz - 4, 4):
        v = struct.unpack_from("<I", e.b, o)[0]
        if v in targets:
            pool[e.off2va(o)].append(v)
    sites = collections.defaultdict(list)
    reg = {}
    for o in range(e.toff, e.toff + e.tsz - 4, 4):
        a = e.off2va(o)
        w = struct.unpack_from("<I", e.b, o)[0]
        if (w & 0xFFFFC000) == 0xE92D4000:
            reg = {}
        if (w & 0x0F7F0000) == 0x051F0000:
            t = a + 8 + ((w & 0xFFF) if w & (1 << 23) else -(w & 0xFFF))
            for v in pool.get(t, ()):
                sites[v].append((a, "ldr"))
            continue
        for v in decode_refs(e, a, w, reg):
            if v in targets:
                kind = "bl" if (w & 0x0F000000) == 0x0B000000 else ("b" if (w & 0x0E000000) == 0x0A000000 else "movw/t")
                sites[v].append((a, kind))
    for v in sorted(targets):
        lst = sites.get(v, [])
        print("0x%x %s: %d site(s)" % (v, e.name(v) or "", len(lst)))
        for a, kind in lst:
            fs = e.fn_start(a)
            fname = e.name(fs) if fs else None
            print("    %-6s at 0x%x   in fn 0x%s%s" % (kind, a, "%x" % fs if fs else "?", "  (%s)" % fname if fname else ""))


def cmd_args(e, fn):
    """Every bl/b to `fn` with the constants r0-r3 held at the call. Walks back from
    the call to the function's push; the nearest write to a register decides it, a
    non-constant write reads `?`, and a call in between clobbers r0-r3."""
    hits = 0
    for o in range(e.toff, e.toff + e.tsz - 4, 4):
        w = struct.unpack_from("<I", e.b, o)[0]
        if (w & 0x0E000000) != 0x0A000000 or (w >> 28) == 0xF:
            continue
        a = e.off2va(o)
        off = w & 0xFFFFFF
        if off & 0x800000:
            off -= 0x1000000
        if (a + 8 + (off << 2)) & 0xFFFFFFFF != fn:
            continue
        vals, hi = {}, {}
        for k in range(1, 24):
            pw = e.u32(a - 4 * k)
            if pw is None or (pw & 0xFFFFC000) == 0xE92D4000:
                break
            if (pw & 0x0F000000) == 0x0B000000:  # an earlier call clobbers r0-r3
                for r in range(4):
                    vals.setdefault(r, None)
                break
            rd = (pw >> 12) & 0xF
            if rd > 3 or (rd in vals and rd not in hi):
                continue
            cond_ok = (pw >> 28) == 0xE
            if (pw & 0x0FEF0000) == 0x03A00000:  # mov rd, #imm
                vals.setdefault(rd, e._rot(pw) if cond_ok else None)
            elif (pw & 0x0FF00000) == 0x03400000:  # movt
                hi[rd] = (((pw >> 16) & 0xF) << 12 | (pw & 0xFFF)) << 16
            elif (pw & 0x0FF00000) == 0x03000000:  # movw
                v = ((pw >> 16) & 0xF) << 12 | (pw & 0xFFF)
                vals[rd] = (v | hi.pop(rd, 0)) if cond_ok else None
            elif (pw >> 26) & 3 == 0 and not (0x11000000 <= (pw & 0x01F00000) <= 0x01700000 and (pw >> 20) & 1):
                if (pw & 0x01900000) != 0x01100000:  # not cmp/cmn/tst/teq
                    vals.setdefault(rd, None)
            elif (pw >> 26) & 3 == 1 and (pw >> 20) & 1:  # ldr into rd
                vals.setdefault(rd, None)
        fs = e.fn_start(a)
        fname = e.name(fs) if fs else None
        reg = " ".join("r%d=%s" % (r, "?" if vals.get(r) is None else "0x%x" % vals[r])
                       for r in range(4) if r in vals)
        print("  %-3s 0x%x  fn 0x%s%s   %s" % ("bl" if (w & 0x0F000000) == 0x0B000000 else "b", a,
              "%x" % fs if fs else "?", " (%s)" % fname if fname else "", reg))
        hits += 1
    print("0x%x %s: %d call site(s)" % (fn, e.name(fn) or "", hits))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["dis", "xref", "args"])
    ap.add_argument("elf")
    ap.add_argument("vals", nargs="+")
    ap.add_argument("--title", default=None)
    a = ap.parse_args(argv)
    e = Elf(a.elf, a.title)
    e.path = a.elf
    vals = [int(x, 16) for x in a.vals if ":" not in x]
    if a.cmd == "dis":
        # start/end pairs, or a lone start with :len (0x2a387c:0x80) - many ranges in
        # one pass, because building the class model is the slow part
        for spec in a.vals:
            if ":" in spec:
                s, n = spec.split(":")
                s = int(s, 16)
                print("\n==== 0x%x %s" % (s, e.name(s) or ""))
                cmd_dis(e, s, s + int(n, 16))
        pairs = [int(x, 16) for x in a.vals if ":" not in x]
        for i in range(0, len(pairs) - 1, 2):
            cmd_dis(e, pairs[i], pairs[i + 1])
    elif a.cmd == "args":
        for v in vals:
            cmd_args(e, v)
    else:
        cmd_xref(e, vals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
