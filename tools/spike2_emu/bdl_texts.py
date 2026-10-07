#!/usr/bin/env python3
"""Which lines of text Godzilla's own code lays out itself (PAD-433).

    bdl_texts.py <game ELF> [<game ELF> ...] [--json OUT] [--check <scene_tree.json>]

Godzilla's screens are run by BDL elements (BDLForeground, BDLBackground and their
subclasses: a battle's intro, its background, an award). Each element is built ONCE, from a
function-local static, with its scene's path and a list of node names:

    BDLForeground(this, "<40 hex>/<40 hex>", const std::vector<const char *> &names, ...)

and when it loads its scene, the base class's v[13] (BDLForeground 0x4152c, BDLBackground
0x401cc on LE 1.16) finds the Text of every name and wraps it in a FlashyText, whose
constructor (0x54ea4) sets the Text's VerticalAlignment to 1 (middle) and ScaleToBounds to 1.
So those lines sit in the middle of their box and shrink to fit it, whatever the card's
bytes say. Emulator-proven on LE 1.16 (PAD-433): the Gigan battle intro's
Lines_Textbox.Line1_Instance in a 220 px box drew at the same rows stored top, middle and
bottom, and where the preview draws it middle.

This reads that list for every element out of the game program, with no disassembler:
  1. RTTI names the two base classes; their vtables' vptrs find the functions that load
     them (the constructors, and the destructors, which nothing builds an element with);
  2. every `bl` to one of those, and one level up (a subclass's own constructor), is a
     place an element is built; the function holding it names the scene (a movw/movt or a
     literal load of a "<40 hex>/<40 hex>" string) and the names: the array of string
     pointers it copies, as many as the `mov r0, #4n ; bl operator new` before the copy;
  3. the class built there (the vptr the function stores) must reach its base's v[13]: its
     own slot 13 IS the base's, or calls it. One that does not is reported and left out.

Prints `scene  class  names...` per element; --json writes {scene: sorted names} (the union
over every ELF given; a scene two builds name differently is an error). --check reads a
project's scene_tree.json and says, per name, whether that scene has a Text there.
Read-only, desk-only (no rig). Godzilla LE/Premium 1.16 and Pro 1.16 are the builds it was
written against."""
import bisect
import collections
import json
import re
import struct
import sys

SCENE_RE = re.compile(r"^[0-9a-f]{40}/[0-9a-f]{40}$")
BASES = ("13BDLForeground", "13BDLBackground")
SLOT_LOAD = 13          # the base's v[13]: find each name's Text and wrap it in a FlashyText


class Elf:
    def __init__(self, path):
        self.path = path
        self.d = d = open(path, "rb").read()
        if d[:4] != b"\x7fELF" or d[4] != 1:
            raise ValueError("%s is not a 32-bit ELF" % path)
        phoff, = struct.unpack_from("<I", d, 0x1C)
        n, = struct.unpack_from("<H", d, 0x2C)
        self.segs = []
        for i in range(n):
            t, off, va, _pa, fs, _ms, fl, _al = struct.unpack_from("<8I", d, phoff + 32 * i)
            if t == 1:
                self.segs.append((off, va, fs, fl))
        self._scan()

    # -- memory --------------------------------------------------------------------------------
    def v2f(self, v):
        for off, va, fs, _fl in self.segs:
            if va <= v < va + fs:
                return v - va + off
        return None

    def f2v(self, o):
        for off, va, fs, _fl in self.segs:
            if off <= o < off + fs:
                return o - off + va
        return None

    def word(self, v):
        o = self.v2f(v)
        if o is None or o + 4 > len(self.d):
            return None
        return struct.unpack_from("<I", self.d, o)[0]

    def cstr(self, v, limit=200):
        o = self.v2f(v) if v else None
        if o is None:
            return None
        e = self.d.find(b"\0", o, o + limit)
        if e <= o:
            return None
        s = self.d[o:e]
        return s.decode() if all(32 <= c < 127 for c in s) else None

    # -- code ----------------------------------------------------------------------------------
    def _scan(self):
        """Every movw/movt pair and pc-relative literal load (site, value), every bl (site,
        target), every `mov r0, #imm` (site, imm) and every `push {..., lr}` (function starts)
        in the executable segment, ARM state."""
        off0, va0, fs0, _ = next(s for s in self.segs if s[3] & 1)
        self.refs, self.calls, self.jumps, self.movr0, self.pushes = [], [], [], {}, []
        last_movw = {}
        d = self.d
        for o in range(0, fs0 - 3, 4):
            w = struct.unpack_from("<I", d, off0 + o)[0]
            va = va0 + o
            cond = w >> 28
            if (w & 0x0FF00000) == 0x03000000:                       # movw rd, #imm16
                last_movw[(w >> 12) & 15] = (va, ((w >> 4) & 0xF000) | (w & 0xFFF))
            elif (w & 0x0FF00000) == 0x03400000:                     # movt rd, #imm16
                rd = (w >> 12) & 15
                if rd in last_movw and va - last_movw[rd][0] <= 64:
                    hi = ((w >> 4) & 0xF000) | (w & 0xFFF)
                    self.refs.append((va, (hi << 16) | last_movw[rd][1]))
            elif (w & 0x0F7F0000) == 0x051F0000:                     # ldr rd, [pc, #+-imm]
                imm = w & 0xFFF
                lit = va + 8 + (imm if (w >> 23) & 1 else -imm)
                v = self.word(lit)
                if v is not None:
                    self.refs.append((va, v))
            elif (w & 0x0E000000) == 0x0A000000 and cond == 0xE:     # bl, and b (a tail call)
                imm = w & 0xFFFFFF
                if imm & 0x800000:
                    imm -= 0x1000000
                (self.calls if w & 0x01000000 else self.jumps).append((va, va + 8 + 4 * imm))
            elif (w & 0x0FFFF000) == 0x03A00000:                     # mov r0, #imm (rotated)
                rot = ((w >> 8) & 15) * 2
                imm = w & 0xFF
                self.movr0[va] = ((imm >> rot) | (imm << (32 - rot))) & 0xFFFFFFFF if rot else imm
            if (w & 0x0FFF4000) == 0x092D4000 and cond == 0xE:       # push {..., lr}
                self.pushes.append(va)
        self.end = va0 + fs0
        self.refs_by_fn = collections.defaultdict(list)
        for site, v in self.refs:
            self.refs_by_fn[self.fn_of(site)].append((site, v))
        self.calls_by_fn = collections.defaultdict(list)
        self.callers = collections.defaultdict(list)
        for site, t in self.calls:
            self.calls_by_fn[self.fn_of(site)].append((site, t))
            self.callers[t].append(site)

    def calls_from(self, fn):
        """Every function *fn* calls or tail-jumps to. A function may load a word or two
        before its push (0x8dec0 on LE 1.16 does): its body runs to the push after that."""
        nxt = bisect.bisect_right(self.pushes, fn)
        start = self.pushes[nxt] if nxt < len(self.pushes) and self.pushes[nxt] - fn <= 32 \
            else fn
        nxt = bisect.bisect_right(self.pushes, start)
        end = self.pushes[nxt] if nxt < len(self.pushes) else self.end
        out = [t for s, t in self.calls if fn <= s < end]
        out += [t for s, t in self.jumps if fn <= s < end and not fn <= t < end]
        return out

    def fn_of(self, va):
        i = bisect.bisect_right(self.pushes, va) - 1
        return self.pushes[i] if i >= 0 else None

    # -- RTTI ----------------------------------------------------------------------------------
    def vptrs_of(self, mangled):
        """The vptr (slot 0's address) of every primary vtable of the class *mangled*
        (``13BDLForeground``)."""
        out = []
        for m in re.finditer(re.escape(mangled.encode() + b"\0"), self.d):
            if m.start() and self.d[m.start() - 1] != 0:
                continue                                  # a longer name ending in this one
            name_va = self.f2v(m.start())
            for t in re.finditer(re.escape(struct.pack("<I", name_va)), self.d):
                ti = self.f2v(t.start()) - 4
                for v in re.finditer(re.escape(struct.pack("<I", ti)), self.d):
                    p = self.f2v(v.start())
                    if self.word(p - 4) == 0:             # offset-to-top 0: a primary vtable
                        out.append(p + 4)
        return out

    def class_of_vptr(self, vptr):
        ti = self.word(vptr - 4)
        name = self.cstr(self.word(ti + 4)) if ti else None
        return name.lstrip("0123456789") if name else None

    def string_array(self, va, n):
        """*n* consecutive pointers to strings at *va*, or None."""
        out = []
        for k in range(n):
            s = self.cstr(self.word(va + 4 * k) or 0)
            if s is None:
                return None
            out.append(s)
        return out


def elements(elf):
    """``[(scene, class, names)]``: every BDL element *elf* builds, and the names whose Texts
    its base class wraps in a FlashyText (middle, scaled to fit)."""
    base_vptr = {}
    for b in BASES:
        for vp in elf.vptrs_of(b):
            base_vptr[vp] = b
    if not base_vptr:
        return []
    base_v13 = {elf.word(vp + 4 * SLOT_LOAD) for vp in base_vptr}
    # the functions that load a base vptr: its constructors (and destructors)
    loaders = {elf.fn_of(site) for site, v in elf.refs if v in base_vptr}
    # a subclass's own constructor calls one; whoever calls THAT builds the element
    builders = set()
    for f in loaders:
        for site in elf.callers.get(f, ()):
            g = elf.fn_of(site)
            builders.add(g)
            for s2 in elf.callers.get(g, ()):
                builders.add(elf.fn_of(s2))
    out = []
    for f in sorted(x for x in builders if x is not None):
        refs = elf.refs_by_fn.get(f, [])
        scenes = sorted({elf.cstr(v) for _s, v in refs if SCENE_RE.match(elf.cstr(v) or "")})
        if len(scenes) != 1:
            continue
        # the names: `mov r0, #4n ; bl operator new` sizes the vector, the array it copies
        # is the next literal that points at n strings
        names, sizes = [], []
        nxt = bisect.bisect_right(elf.pushes, f)
        end = elf.pushes[nxt] if nxt < len(elf.pushes) else elf.end
        calls = sorted(s for s, _t in elf.calls_by_fn.get(f, ()))
        for site in range(f, end, 4):
            if site in elf.movr0 and elf.movr0[site] % 4 == 0 and 4 <= elf.movr0[site] <= 256:
                # operator new a few instructions on (the vector's other words are zeroed
                # in between)
                if any(site < s <= site + 24 for s in calls):
                    sizes.append((site, elf.movr0[site] // 4))
        for site, n in sizes:
            later = sorted((s, v) for s, v in refs if s > site)
            for _s, v in later[:6]:
                arr = elf.string_array(v, n)
                if arr and not any(SCENE_RE.match(a) for a in arr):
                    names += arr
                    break
        # the class built here: a vptr this function stores, whose slot 13 reaches the base's
        cls, reaches = None, False
        for _s, v in refs:
            name = elf.class_of_vptr(v) if elf.word(v - 4) else None
            if not name or not name.startswith("BDL"):
                continue
            ok = _reaches(elf, elf.word(v + 4 * SLOT_LOAD), base_v13)
            if cls is None or ok:
                cls, reaches = name, ok
        if cls is None:
            cls, reaches = "BDLForeground", True          # built as the base class itself
        out.append((scenes[0], cls, sorted(set(names)), reaches))
    return out


def _reaches(elf, fn, targets, depth=3):
    """Whether *fn* is one of *targets* or calls one, through at most *depth* calls (a
    subclass's v[13] calls its parent's, which calls the base's)."""
    seen, todo = set(), [(fn, 0)]
    while todo:
        f, k = todo.pop()
        if f in targets:
            return True
        if f in seen or k >= depth or f is None:
            continue
        seen.add(f)
        todo += [(t, k + 1) for t in elf.calls_from(f)]
    return False


def main(argv):
    out_json = argv[argv.index("--json") + 1] if "--json" in argv else None
    check = argv[argv.index("--check") + 1] if "--check" in argv else None
    elfs = [a for i, a in enumerate(argv) if not a.startswith("--")
            and (i == 0 or argv[i - 1] not in ("--json", "--check"))]
    table, bad = {}, 0
    for path in elfs:
        elf = Elf(path)
        for scene, cls, names, reaches in elements(elf):
            print("%s  %-34s %s %s" % (scene[:8] + "/" + scene[41:49], cls,
                                       "" if reaches else "(DOES NOT REACH v[13]; left out)",
                                       " ".join(names)))
            if not reaches or not names:
                continue
            if scene in table and table[scene] != names:
                print("ERROR: %s names differ between builds: %s / %s"
                      % (scene, table[scene], names))
                bad += 1
            table[scene] = names
    if check:
        trees = json.load(open(check, encoding="utf-8"))
        for scene, names in sorted(table.items()):
            card = next((k for k in trees if scene in k), None)
            if card is None:
                print("check: %s is not in this project" % scene[:8])
                continue
            paths = _text_paths(trees[card])
            for n in names:
                print("check: %s %-50s %s" % (scene[:8], n, "Text" if n in paths else "-"))
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump({k: table[k] for k in sorted(table)}, f, indent=1)
    return 1 if bad else 0


def _text_paths(man):
    """The dotted path (from the scene's root) of every node that draws a Text."""
    out = set()

    def walk(kids, prefix):
        for n in kids:
            path = prefix + [n["name"]]
            for _s, oid in n.get("comps") or ():
                o = man["objects"].get(str(oid)) or {}
                if o.get("kind") == "Text":
                    out.add(".".join(path))
                if o.get("kind") in ("Sprite", "StreamingFlipbook"):
                    walk(o.get("kids") or (), path)
    walk(man["root"]["kids"], [])
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
