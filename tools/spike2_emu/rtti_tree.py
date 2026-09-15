#!/usr/bin/env python3
"""Dump a Spike 2 game ELF's C++ object model from its RTTI: class hierarchy + vtables.

The game ELFs are stripped (no .symtab) but GCC's RTTI survives, so every polymorphic
class still names itself. This walks the mangled typeinfo names, finds their typeinfo
objects (a word pointing at the name, followed by the base-class typeinfo for
__si_class_type_info), and their vtables ([offset-to-top 0][typeinfo][fn ptrs...]).

What it showed on godzilla (2026-09-15): the rules are compiled C++ - `Rule*`
singletons off `HookListener` (the numbered event bus), one `cmode_*` class per mode
(cmode -> cmode_timed / cmode_mball / cmode_hurry_up / cmode_battle -> one leaf per
monster), a `cmode_manager` singleton, `BDL<Mode>Start/BG/Total` display layers off
`SceneLoaderLayeredDisplayElement`, `ctimer_manager` / `cgodzilla_timer`. No script
layer anywhere. That is the starting map for plans/spike2_new_mode_plan.md.

Usage:
    rtti_tree.py <game_elf> [--filter REGEX] [--vtables] [--json OUT]

    --filter   only print classes whose name matches (default: everything)
    --vtables  also print each class's vtable VA and virtual-function count
    --json     write the full model {name: {base, typeinfo, vtable, nvirt}} to OUT

Addresses are ELF virtual addresses (add 0x10000 for a live /proc read under qemu-user,
see reference_spike2_qemu_guest_base). Read-only; never touches the ELF.
"""
import argparse
import json
import re
import struct
import sys


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def load_segments(b):
    e_phoff = _u32(b, 0x1C)
    e_phentsize = struct.unpack_from("<H", b, 0x2A)[0]
    e_phnum = struct.unpack_from("<H", b, 0x2C)[0]
    loads = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        typ, off, va, _pa, fsz, msz, flg, _al = struct.unpack_from("<IIIIIIII", b, o)
        if typ == 1:
            loads.append((off, va, fsz, msz, flg))
    return loads


def make_mappers(loads):
    def va2off(va):
        for off, v, fsz, _msz, _f in loads:
            if v <= va < v + fsz:
                return off + (va - v)
        return None

    def off2va(off):
        for o, v, fsz, _msz, _f in loads:
            if o <= off < o + fsz:
                return v + (off - o)
        return None

    return va2off, off2va


_NAME_RE = re.compile(rb"\0(N?(?:\d+[A-Za-z_][A-Za-z0-9_]*)+E?)\0")


def demangle_simple(s):
    """Good enough for the game's own classes: '12cmode_battle' -> 'cmode_battle',
    'N6Radium5SoundE' -> 'Radium::Sound', '9SingletonI13cmode_managerE' -> 'Singleton<cmode_manager>'."""
    parts = []
    i = 0
    nested = s.startswith("N")
    if nested:
        i = 1
    while i < len(s):
        m = re.match(r"\d+", s[i:])
        if not m:
            break
        n = int(m.group(0))
        i += len(m.group(0))
        parts.append(s[i : i + n])
        i += n
        if i < len(s) and s[i] == "I":  # template args: take the single nested name
            inner = s[i + 1 :]
            m2 = re.match(r"(\d+)", inner)
            if m2:
                k = int(m2.group(1))
                arg = inner[len(m2.group(1)) : len(m2.group(1)) + k]
                parts[-1] = "%s<%s>" % (parts[-1], arg)
            break
    return "::".join(parts) if parts else s


def build_model(b):
    loads = load_segments(b)
    va2off, off2va = make_mappers(loads)
    text = [s for s in loads if s[4] & 1][0]
    tlo, thi = text[1], text[1] + text[2]

    names = {}  # name VA -> mangled
    for m in _NAME_RE.finditer(b):
        s = m.group(1)
        if not re.search(rb"[A-Za-z]{3,}", s):
            continue
        va = off2va(m.start() + 1)
        if va is not None:
            names[va] = s.decode()

    # typeinfo objects. Three GCC layouts share [vptr][name ptr]:
    #   __class_type_info      no base
    #   __si_class_type_info   [base typeinfo]                      (single inheritance)
    #   __vmi_class_type_info  [flags][count][{base typeinfo, offset_flags} x count]
    # The vmi shape is what a class with two bases gets (cmode_battle, RuleAllies,
    # cmode_hurry_up on godzilla), which is why a single-base-only reader shows them rootless.
    ti = {}
    for off in range(0, len(b) - 12, 4):
        nva = _u32(b, off + 4)
        if nva not in names:
            continue
        va = off2va(off)
        if va is None:
            continue
        ti[va] = {"mangled": names[nva], "off": off}
    def _cstr(va):
        o = va2off(va)
        if o is None:
            return None
        e = b.find(b"\0", o, o + 256)
        return b[o:e] if e > o else None

    def _adopt(tva):
        """Accept a base typeinfo the NUL-delimited name scan missed. Names are packed
        straight after typeinfo data, so the byte before one is not always NUL: on
        godzilla Pro 1.15 cmode_battle, cmode_hurry_up and cmode_timed_null all derive
        from one typeinfo at 0x631b3c whose name the scan never saw."""
        if tva in ti:
            return True
        o = va2off(tva)
        if o is None or o + 8 > len(b):
            return False
        s = _cstr(_u32(b, o + 4))
        if not s or not re.fullmatch(rb"N?(?:\d+[A-Za-z_][A-Za-z0-9_]*)+E?", s):
            return False
        ti[tva] = {"mangled": s.decode(), "off": o}
        return True

    def _resolve_bases():
        pending = [x for x in ti if "bases" not in ti[x]]
        while pending:
            rec = ti[pending.pop()]
            if "bases" in rec:
                continue
            off = rec["off"]
            bases = []
            w8 = _u32(b, off + 8) if off + 12 <= len(b) else 0
            if _adopt(w8):
                bases = [w8]
            else:
                count = _u32(b, off + 12) if off + 16 <= len(b) else 0
                if 1 <= count <= 8 and off + 16 + 8 * count <= len(b):
                    cand = [_u32(b, off + 16 + 8 * i) for i in range(count)]
                    if all(_adopt(c) for c in cand):
                        bases = cand
            rec["bases"] = bases
            pending.extend(x for x in bases if "bases" not in ti[x])

    _resolve_bases()

    # vtables: [0][typeinfo va][fn...] with fn in the text segment. A typeinfo the
    # name scan missed is adopted here too, when its own vptr is one the found
    # typeinfos use: on godzilla Pro 1.15 that recovers seven LEAF modes
    # (cmode_super_train, cmode_bridge_attack_multiball, ...) that are only ever
    # reached through a vtable, never as anyone's base.
    tivptrs = {_u32(b, r["off"]) for r in ti.values()}
    vt = {}
    for off in range(0, len(b) - 8, 4):
        if _u32(b, off) != 0:
            continue
        tva = _u32(b, off + 4)
        if tva not in ti:
            o = va2off(tva)
            if o is None or o + 8 > len(b) or _u32(b, o) not in tivptrs or not _adopt(tva):
                continue
        k, o = 0, off + 8
        while o + 4 <= len(b) and tlo <= _u32(b, o) < thi:
            k += 1
            o += 4
        if k:
            vt.setdefault(tva, []).append((off2va(off), k))
    _resolve_bases()

    model = {}
    for va, rec in ti.items():
        name = demangle_simple(rec["mangled"])
        bases = [demangle_simple(ti[bv]["mangled"]) for bv in rec["bases"]]
        vts = sorted(vt.get(va, []), key=lambda x: -x[1])
        model[name] = {
            "mangled": rec["mangled"],
            "typeinfo": va,
            "base": bases[0] if bases else None,
            "bases": bases,
            "vtable": vts[0][0] if vts else None,
            "nvirt": vts[0][1] if vts else None,
        }
    return model


def chain(model, name, seen=None):
    """'A -> B -> C' along the first base; extra bases in braces: 'A -> B {+ IFace}'."""
    seen = seen or set()
    seen.add(name)
    bases = model.get(name, {}).get("bases") or []
    if not bases or bases[0] in seen:
        return name
    extra = "".join(" {+ %s}" % x for x in bases[1:] if x not in seen)
    return name + extra + " -> " + chain(model, bases[0], seen)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("elf")
    ap.add_argument("--filter", default=None)
    ap.add_argument("--vtables", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    with open(a.elf, "rb") as f:
        b = f.read()
    model = build_model(b)
    flt = re.compile(a.filter) if a.filter else None
    print("%d classes with RTTI" % len(model))
    for name in sorted(model):
        if flt and not flt.search(name):
            continue
        rec = model[name]
        line = chain(model, name)
        if a.vtables:
            if rec["vtable"] is not None:
                line += "   [vtable 0x%x, %d virtuals]" % (rec["vtable"], rec["nvirt"])
            else:
                line += "   [no vtable found]"
        print("  " + line)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(model, f, indent=1, sort_keys=True)
        print("wrote", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
