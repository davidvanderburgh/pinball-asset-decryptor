#!/usr/bin/env python3
"""port_tool.py - draft the PORT for a game build from a port that already works (item 135).

    port_tool.py <reference game ELF> <reference port> <target game ELF> -o <draft port>
                 [--game NAME] [--version TEXT]

A port tells the mode runtime where a game's functions and globals are in ONE build
(MODE_SDK.md, "Ports"). This drafts one for a new build from a proven one, and says,
entry by entry, how sure it is:

  site   located by a masked signature of the reference function's first instructions,
         strict (only branch and literal offsets masked) or loose (small immediates too);
         a PLT stub (a library call such as __dynamic_cast) by its imported symbol name.
         Its two instruction words are read from the target, as port_words.py does.
  data   derived: every place the reference code loads the address is found, the
         function around it is located in the target, the instructions from its start to
         that place must line up, and the address the TARGET loads there is taken. At
         least two agreeing places are needed (one for a global in ONE_PLACE_DATA, which
         says why one is enough); disagreement is reported, not voted away.
  scene  a 40-hex id the reference code loads as a string is derived the same way, and
         the target's string read back.
  value / shot / callout / text / a scene no code names
         COPIED from the reference and marked unverified: struct offsets, shot bits and
         sound ids are not in any instruction this can line up. The emulator decides
         (the shot census, and a mode that runs). A scene id is copied only if the
         target program names it too.
  ANOTHER TITLE (--game jaws_le from godzilla_pro; _le/_pro are one title)
         shot, callout and text lines are LEFT OUT as comments: they are the reference
         title's, and so are the values in TITLE_VALUES (a rule's light owner and light
         set, an award screen type). Other values are still copied: framework offsets.

Nothing is guessed silently: an entry it cannot place is written as a comment saying why,
and the runtime then treats that capability as absent. Under it, CANDIDATES where there
are any - the framework calls the reference function makes that the target has (a title's
own wrapper usually ends in one), or for a scene the first id after the same neighbouring
strings - for a person to prove (MODE_SDK.md, "Making a port"). Exit status 1 if a CORE
site (tick, shot_dispatch, ball_end, score_add) or core global is missing.
"""
import argparse
import re
import struct
import sys
from collections import Counter

import numpy as np

CORE_SITES = ("tick", "shot_dispatch", "ball_end", "score_add")
CORE_DATA = ("cur_player", "scores")
HOOKED = ("tick", "shot_dispatch", "ball_end", "sound_lookup")
HOOKED = HOOKED + ("hook_dispatch",)          # item 147: the event bus's dispatch
# values that are one title's rules, not the framework's: Godzilla's are Tesla Strike's
# light owner and light set, and its powerline-tower award screen
TITLE_VALUES = ("light_owner", "light_lts", "award_screen_type")
MIN_N, MAX_N = 8, 48
# globals ONE lined-up place may place (the rule is two), each with the reason one is enough; the
# draft's line says so. Item 154 display's two: without this the reference's own port was not
# reproduced (layered_displays) and Premium 1.16's draft left both out.
ONE_PLACE_DATA = {
    "layered_displays": "the program loads it in ONE place only (its getter), so two can never agree",
    "display_effects": "the runtime uses it only when the manager it points at holds award_screen_arg's "
                       "table (disp_manager), so a wrong one holds nothing",
    "ebirah_stage_awards": "the rule's constructor copies the rodata table in ONE place; the runtime "
                           "reads it only through a rule whose vtable words matched",
    "ebirah_lamp_table": "the rule's lamp fiber loads the rodata table from ONE literal; the runtime "
                         "reads it only through a rule whose vtable words matched",
    "tank_path": "the tank rule's constructor loads the rodata path from ONE literal; the runtime reads it "
                 "only through a rule whose vtable words matched",
    "tank_spot_list": "the tank rule's spot getter loads the rodata list from ONE literal; the runtime "
                      "reads it only through a rule whose vtable words matched",
}


# ---- the ELF ----------------------------------------------------------------------------
class Elf:
    def __init__(self, path):
        self.path = path
        self.b = open(path, "rb").read()
        b = self.b
        if b[:4] != b"\x7fELF" or b[4] != 1:
            raise SystemExit("%s: not a 32-bit ELF" % path)
        phoff, = struct.unpack_from("<I", b, 0x1C)
        phentsize, phnum = struct.unpack_from("<HH", b, 0x2A)
        self.loads = []
        for i in range(phnum):
            t, off, va, _pa, fsz, _msz, flags, _al = struct.unpack_from("<8I", b, phoff + i * phentsize)
            if t == 1:
                self.loads.append((off, va, fsz, flags))
        text = [l for l in self.loads if l[3] & 1][0]
        self.toff, self.tva, self.tsz = text[0], text[1], text[2]
        self.words = struct.unpack_from("<%dI" % (self.tsz // 4), b, self.toff)
        # the same words as an array: a whole-text scan is one vector compare, not a loop
        self.arr = np.frombuffer(b, dtype="<u4", count=self.tsz // 4, offset=self.toff)
        self.sections = self._sections()
        self.plt_by_name, self.name_by_plt = self._plt()

    def off(self, va):
        for off, v, fsz, _f in self.loads:
            if v <= va < v + fsz:
                return off + va - v
        return None

    def word(self, va):
        o = self.off(va)
        return struct.unpack_from("<I", self.b, o)[0] if o is not None and o + 4 <= len(self.b) else None

    def cstring(self, va, cap=64):
        o = self.off(va)
        if o is None:
            return None
        end = self.b.find(b"\0", o, o + cap)
        return self.b[o:end] if end > o else None

    def idx(self, va):
        return (va - self.tva) // 4

    def va(self, i):
        return self.tva + 4 * i

    def in_text(self, va):
        return self.tva <= va < self.tva + self.tsz

    def _sections(self):
        b = self.b
        shoff, = struct.unpack_from("<I", b, 0x20)
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", b, 0x2E)
        if not shoff or not shnum:
            return {}
        raw = [struct.unpack_from("<10I", b, shoff + i * shentsize) for i in range(shnum)]
        stroff = raw[shstrndx][4]
        out = {}
        for s in raw:
            end = b.find(b"\0", stroff + s[0])
            out[b[stroff + s[0]:end].decode("latin1")] = s   # name, type, flags, addr, off, size ...
        return out

    def _plt(self):
        """{symbol: PLT stub address} from .rel.plt, .dynsym, .dynstr and the stubs."""
        s = self.sections
        if not all(k in s for k in (".rel.plt", ".dynsym", ".dynstr", ".plt")):
            return {}, {}
        b = self.b
        dynsym, dynstr, relplt, plt = s[".dynsym"], s[".dynstr"], s[".rel.plt"], s[".plt"]
        slot_name = {}
        for i in range(relplt[5] // 8):
            got, info = struct.unpack_from("<II", b, relplt[4] + 8 * i)
            sym = info >> 8
            name_off, = struct.unpack_from("<I", b, dynsym[4] + 16 * sym)
            end = b.find(b"\0", dynstr[4] + name_off)
            slot_name[got] = b[dynstr[4] + name_off:end].decode("latin1")
        by_name, by_plt = {}, {}
        va, end = plt[3], plt[3] + plt[5]
        while va + 12 <= end:
            w0, w1, w2 = (self.word(va + 4 * k) for k in range(3))
            if (w0 & 0xFFFFF000) == 0xE28FC000 and (w1 & 0xFFFFF000) == 0xE28CC000 and (w2 & 0xFFFFF000) == 0xE5BCF000:
                got = va + 8 + rot_imm(w0) + rot_imm(w1) + (w2 & 0xFFF)
                if got in slot_name:
                    by_name[slot_name[got]] = va
                    by_plt[va] = slot_name[got]
                va += 12
            else:
                va += 4
        return by_name, by_plt


def rot_imm(w):
    rot, imm = (w >> 8) & 0xF, w & 0xFF
    return ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF if rot else imm


# ---- signatures (patloc.py's masks) ---------------------------------------------------------
def mask_of(w, loose=False):
    if (w & 0x0E000000) == 0x0A000000:
        return 0xFF000000
    if (w & 0x0F7F0000) == 0x051F0000:
        return 0xFFFFF000
    if (w & 0x0FB00000) == 0x03000000:
        return 0xFFF0F000
    if (w & 0x0FEF0000) == 0x028F0000:
        return 0xFFFFF000
    if loose:
        if (w & 0x0E000000) == 0x02000000:
            return 0xFFFFF000
        if (w & 0x0E000000) == 0x04000000:
            return 0xFFFFF000
    return 0xFFFFFFFF


def sig(elf, i, n, loose):
    return [(w & mask_of(w, loose), mask_of(w, loose)) for w in elf.words[i:i + n]]


def matches_at(elf, i, s):
    if i < 0 or i + len(s) > len(elf.words):
        return False
    return all((elf.words[i + k] & m) == v for k, (v, m) in enumerate(s))


class Finder:
    """Candidate indexes by first masked word, cached - locating hundreds of functions
    in a 2M-word text must not rescan it each time."""
    def __init__(self, elf):
        self.elf = elf
        self.cache = {}

    def cands(self, v, m):
        key = (v, m)
        if key not in self.cache:
            self.cache[key] = np.nonzero((self.elf.arr & np.uint32(m)) == np.uint32(v))[0].tolist()
        return self.cache[key]

    def find(self, s):
        return [i for i in self.cands(*s[0]) if matches_at(self.elf, i, s)]


def locate(ref, rf, tgt, tf, i, need=0):
    """The target index of the reference function starting at index i, or (None, why).
    `need` = the signature must cover at least this many words (so offsets line up)."""
    for loose in (False, True):
        n = max(MIN_N, need)
        while n <= max(MAX_N, need):
            s = sig(ref, i, n, loose)
            rh = rf.find(s)
            if len(rh) == 1:
                th = tf.find(s)
                if len(th) == 1:
                    return th[0], "loose" if loose else "strict"
                if not th and loose:
                    return None, "absent in the target (the function changed)"
                if not th:
                    break                   # try loose
                if n >= max(MAX_N, need):
                    return None, "ambiguous in the target (%d matches)" % len(th)
            elif not rh:
                return None, "no signature"
            n += 4
    return None, "not unique in the reference"


def func_start(elf, i):
    for k in range(i, max(-1, i - 6000), -1):
        w = elf.words[k]
        if (w & 0xFFFF4000) == 0xE92D4000:
            return k
    return None


# ---- how code loads an address --------------------------------------------------------------
def movw_imm(w):
    return ((w >> 16) & 0xF) << 12 | (w & 0xFFF)


def refs_to(elf, target, limit=400):
    """[(kind, index, extra)] where the text loads `target`: ('movw', i_movw, i_movt) or
    ('lit', i_ldr, pool_va)."""
    out = []
    lo, hi = target & 0xFFFF, (target >> 16) & 0xFFFF
    W = elf.words
    a = elf.arr
    movw = ((a & np.uint32(0x0FF00000)) == np.uint32(0x03000000)) & \
           ((((a >> np.uint32(16)) & np.uint32(0xF)) << np.uint32(12) | (a & np.uint32(0xFFF))) == np.uint32(lo))
    hits = sorted(np.nonzero(movw)[0].tolist() + np.nonzero(a == np.uint32(target))[0].tolist())
    for i in hits:
        w = W[i]
        if (w & 0x0FF00000) == 0x03000000 and movw_imm(w) == lo:
            rd = (w >> 12) & 0xF
            for j in range(1, 16):
                if i + j >= len(W):
                    break
                y = W[i + j]
                if (y & 0x0FF00000) == 0x03400000 and ((y >> 12) & 0xF) == rd:
                    if movw_imm(y) == hi:
                        out.append(("movw", i, i + j))
                    break
        if w == target:
            pool = elf.va(i)
            for k in range(1, 1024):
                u = W[i - k] if i - k >= 0 else 0
                if (u & 0x0F7F0000) == 0x051F0000:
                    imm = u & 0xFFF
                    if elf.va(i - k) + 8 + (imm if u & 0x00800000 else -imm) == pool:
                        out.append(("lit", i - k, pool))
        if len(out) >= limit:
            break
    return out


def value_at(elf, kind, i, j):
    W = elf.words
    if kind == "movw":
        w, y = W[i], W[j]
        if (w & 0x0FF00000) != 0x03000000 or (y & 0x0FF00000) != 0x03400000:
            return None
        if ((w >> 12) & 0xF) != ((y >> 12) & 0xF):
            return None
        return movw_imm(y) << 16 | movw_imm(w)
    u = W[i]
    if (u & 0x0F7F0000) != 0x051F0000:
        return None
    imm = u & 0xFFF
    return elf.word(elf.va(i) + 8 + (imm if u & 0x00800000 else -imm))


def bl_dest(elf, i):
    w = elf.words[i]
    if (w & 0x0F000000) != 0x0B000000:
        return None
    off = w & 0xFFFFFF
    if off & 0x800000:
        off -= 0x1000000
    return elf.va(i) + 8 + off * 4


def via_callers(ref, rf, tgt, tf, address, want=2, tries=80):
    """Place a function no signature makes unique (a twin, a typed wrapper) through the
    functions that CALL it: line each caller up in the target and read its bl."""
    seen = Counter()
    via = {}
    tried = 0
    idx = np.arange(len(ref.arr), dtype=np.int64)
    off = (ref.arr & np.uint32(0xFFFFFF)).astype(np.int64)
    off = np.where(off & 0x800000, off - 0x1000000, off)
    is_bl = (ref.arr & np.uint32(0x0F000000)) == np.uint32(0x0B000000)
    callers = np.nonzero(is_bl & (ref.tva + 4 * idx + 8 + off * 4 == address))[0].tolist()
    for i in callers:
        start = func_start(ref, i)
        if start is None or i - start > 400:
            continue
        tried += 1
        if tried > tries:
            break
        need = i - start + 1
        t_start, _how = locate(ref, rf, tgt, tf, start, need)
        if t_start is None or not matches_at(tgt, t_start, sig(ref, start, need, True)):
            continue
        d = bl_dest(tgt, t_start + (i - start))
        if d is None:
            continue
        seen[d] += 1
        via.setdefault(d, "0x%x" % ref.va(i))
        if seen[d] >= 3 and len(seen) == 1:
            break
    if not seen:
        return None, "no caller could be lined up"
    if len(seen) > 1:
        return None, "callers disagree: %s" % ", ".join("0x%x x%d" % kv for kv in seen.most_common(4))
    d, n = seen.most_common(1)[0]
    if n < want:
        return None, "only %d caller lined up" % n
    return d, "placed through %d callers, e.g. the bl at %s" % (n, via[d])


def _bl_callers(elf, address):
    idx = np.arange(len(elf.arr), dtype=np.int64)
    off = (elf.arr & np.uint32(0xFFFFFF)).astype(np.int64)
    off = np.where(off & 0x800000, off - 0x1000000, off)
    is_bl = (elf.arr & np.uint32(0x0F000000)) == np.uint32(0x0B000000)
    return np.nonzero(is_bl & (elf.tva + 4 * idx + 8 + off * 4 == address))[0].tolist()


def _hook_id_before(elf, k):
    """The n of the `mov r1, #n` just before index k, or None."""
    for m in range(k - 1, max(k - 9, 0), -1):
        w = elf.words[m]
        if (w & 0x0FFFF000) == 0x03A01000:
            return rot_imm(w)
    return None


def via_hook(ref, rf, tgt, tf, address):
    """Place a function the game reaches through its numbered event bus: the reference calls
    it from a handler registered (registrar(slot, n, handler, priority)) for hook n; the
    target's handler for the same hook, of the same shape, makes the call at the same place.
    Jaws LE's and Deadpool's end of ball are found this way."""
    found = Counter()
    for i in _bl_callers(ref, address):
        push = func_start(ref, i)
        if push is None or i - push > 40:
            continue
        for h in range(push, max(push - 4, -1), -1):          # a handler may load before its push
            for kind, j, jt in refs_to(ref, ref.va(h), limit=8):
                if kind != "movw":
                    continue
                call = next((k for k in range(max(j, jt), min(jt + 9, len(ref.words))) if bl_dest(ref, k) is not None), None)
                if call is None:
                    continue
                hook = _hook_id_before(ref, call)
                ri, _how = locate(ref, rf, tgt, tf, ref.idx(bl_dest(ref, call)))
                if hook is None or ri is None:
                    continue
                shape = sig(ref, h, i - h, True)
                for c in _bl_callers(tgt, tgt.va(ri)):
                    if _hook_id_before(tgt, c) != hook:
                        continue
                    lo = hi = None
                    for m in range(c - 1, max(c - 9, 0), -1):
                        w = tgt.words[m]
                        if lo is None and (w & 0x0FF0F000) == 0x03002000:
                            lo = movw_imm(w)
                        if hi is None and (w & 0x0FF0F000) == 0x03402000:
                            hi = movw_imm(w)
                    if lo is None or hi is None or not tgt.in_text(hi << 16 | lo):
                        continue
                    th = tgt.idx(hi << 16 | lo)
                    if th + (i - h) >= len(tgt.words) or not matches_at(tgt, th, shape):
                        continue
                    d = bl_dest(tgt, th + (i - h))
                    if d is not None:
                        found[(d, hook)] += 1
    if not found:
        return None, "no hook handler lined up", []
    if len(set(d for d, _h in found)) > 1:
        # the reference sends several hooks to this one function and the target does not:
        # which hook it is has to be measured (MODE_SDK.md, "Making a port")
        return None, "its hooks' handlers call different functions here: %s" % ", ".join(
            "0x%x (hook 0x%x)" % k for k in sorted(found)), sorted(d for d, _h in found)
    (d, hook), _n = found.most_common(1)[0]
    return d, "through the handler of hook 0x%x, as in the reference" % hook, [d]


def callee_hints(ref, rf, tgt, tf, address, cap=96):
    """For a function that could not be placed: what it calls that CAN be found in the
    target. A title's own wrapper (Godzilla's callout remaps a sound id per player) often
    ends in a framework call every title has - a candidate, never a placement."""
    i = ref.idx(address)
    out = []
    for k in range(cap):
        if i + k >= len(ref.words):
            break
        w = ref.words[i + k]
        d = bl_dest(ref, i + k) if (w & 0xF0000000) != 0xF0000000 else None
        if d is None and (w >> 28) == 0xE and (w & 0x0F000000) == 0x0A000000:
            d = ref.va(i + k) + 8 + (((w & 0xFFFFFF) ^ 0x800000) - 0x800000) * 4   # a tail call
        if d is not None and ref.in_text(d) and d != address and d not in (r for r, _t in out):
            ti, _how = locate(ref, rf, tgt, tf, ref.idx(d))
            if ti is not None:
                out.append((d, tgt.va(ti)))
        if w == 0xE12FFF1E or (w & 0xFFFF8000) == 0xE8BD8000:     # bx lr, pop {..., pc}
            break
    return out


def title_of(game):
    """godzilla_pro and godzilla_le are one title: they share shot bits and sound ids."""
    return re.sub(r"_(le|pro|premium|prem|ce|se)$", "", game or "")


def scene_by_neighbours(ref, tgt, at):
    """A scene id the target never names: look for the strings printed just before the
    reference id (a class's own strings, such as "NetScoreFrameOverlay") in the target,
    and the first 40-hex id after them. (candidate, anchor) or (None, None)."""
    window = ref.b[max(0, at - 256):at]
    anchors = [m.group(1) for m in re.finditer(rb"(?<=\0)([ -~]{6,})\0", b"\0" + window)][::-1]
    for a in anchors[:4]:
        if re.fullmatch(rb"[0-9a-f]{40}", a):
            continue
        k = tgt.b.find(b"\0" + a + b"\0")
        if k < 0:
            continue
        m = re.search(rb"(?<=\0)[0-9a-f]{40}(?=\0)", tgt.b[k:k + 2048])
        if m:
            return m.group(0).decode(), a.decode()
    return None, None


def derive(ref, rf, tgt, tf, address, want=2, tries=60):
    """Map a reference address to the target through code that loads it - directly, or
    as a base the code loads plus the field offset its next instruction reads."""
    v, how = derive_direct(ref, rf, tgt, tf, address, want, tries)
    if v is not None:
        return v, how
    for off in range(4, 0x200, 4):
        base = address - off
        bv, bhow = derive_direct(ref, rf, tgt, tf, base, want, tries, field=off)
        if bv is not None:
            return bv + off, "a base 0x%x + field 0x%x; the base %s" % (base, off, bhow)
    return None, how


def loads_field(elf, j, off):
    """Does an instruction just after j read [rd, #off], rd being what j loaded into?"""
    rd = (elf.words[j] >> 12) & 0xF
    for k in range(1, 4):
        if j + k >= len(elf.words):
            return False
        u = elf.words[j + k]
        if (u & 0x0F700000) == 0x05100000 and ((u >> 16) & 0xF) == rd and (u & 0x00800000) and (u & 0xFFF) == off:
            return True
    return False


def derive_direct(ref, rf, tgt, tf, address, want=2, tries=60, field=None):
    """Map a reference address to the target through code that loads it."""
    seen = Counter()
    via = {}
    tried = 0
    funcs_done = set()
    for kind, i, extra in refs_to(ref, address):
        if field is not None and not loads_field(ref, extra if kind == "movw" else i, field):
            continue
        start = func_start(ref, i)
        if start is None or (start, i) in funcs_done:
            continue
        funcs_done.add((start, i))
        tried += 1
        if tried > tries:
            break
        j = extra if kind == "movw" else i
        need = max(i, j) - start + 1
        if need > 400:
            continue
        t_start, how = locate(ref, rf, tgt, tf, start, need)
        if t_start is None:
            continue
        # the whole stretch must line up under the loose mask, so offsets are the same
        if not matches_at(tgt, t_start, sig(ref, start, need, True)):
            continue
        ti = t_start + (i - start)
        tj = t_start + (j - start) if kind == "movw" else ti
        v = value_at(tgt, kind, ti, tj)
        if v is None:
            continue
        if field is not None and not loads_field(tgt, tj, field):
            continue
        seen[v] += 1
        via.setdefault(v, "0x%x+0x%x" % (ref.va(start), 4 * (i - start)))
        if seen[v] >= want and len(seen) == 1:
            break
    if not seen:
        return None, "no code that loads it could be lined up"
    if len(seen) > 1:
        return None, "disagreement: %s" % ", ".join("0x%x x%d" % kv for kv in seen.most_common(4))
    v, n = seen.most_common(1)[0]
    if n < want:
        return None, "only %d place lined up (0x%x via %s); %d needed" % (n, v, via[v], want)
    return v, "derived from %d places, e.g. %s" % (n, via[v])


# ---- the port ----------------------------------------------------------------------------------
LINE = re.compile(r"^(\s*)(\w+)\s+(.*)$")


def parse_port(path):
    entries = []
    for raw in open(path, encoding="utf-8").read().splitlines():
        m = LINE.match(raw)
        if not m or raw.lstrip().startswith("#"):
            entries.append(("#", raw))
            continue
        entries.append((m.group(2), m.group(3)))
    return entries


def is_hooked_ok(tgt, va):
    w0, w1 = tgt.word(va), tgt.word(va + 4)

    def pcdep(w):
        if (w & 0x0E000000) == 0x0A000000:
            return True
        if (w >> 26) & 3 == 1 and ((w >> 16) & 0xF) == 15:
            return True
        if (w >> 26) & 3 == 0 and (((w >> 16) & 0xF) == 15 or ((w >> 12) & 0xF) == 15):
            return (w & 0x0FB00000) != 0x03000000
        return (w & 0x0E108000) == 0x08108000

    def literal_load(w):          # ldr rd, [pc, #n]: the runtime relocates it (item 137)
        return (w & 0xFF7F0000) == 0xE51F0000 and ((w >> 12) & 0xF) != 15

    def return_(w):               # bx lr moves anywhere; only a one-instruction function is out
        return (w & 0x0FFFFFFF) == 0x012FFF1E
    if w0 == 0xE12FFF1E:
        return False
    return not any(pcdep(w) and not literal_load(w) and not return_(w) for w in (w0, w1))


_LAMPS = {}


def lamp_draft(rest, target_elf, other_title, report):
    """One `lamp` line for the target (item mode-leds), placed by the insert's name in the target's own
    tables (lamp_map.py), with the target's own shot tie where its shot table was read; or a comment."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import lamp_map
    ref = lamp_map.parse_lamp(rest)
    if ref is None:
        report["lamp unreadable"] += 1
        return "# lamp %s   <- not a lamp line the runtime can read" % rest
    if other_title:
        report["lamp left out"] += 1
        return "# lamp %s   <- another title's insert" % rest
    if target_elf not in _LAMPS:
        try:
            ins, how, _t = lamp_map.inserts(lamp_map.Elf(target_elf))
            _LAMPS[target_elf] = ({i["name"]: i for i in ins}, how)
        except SystemExit as e:
            _LAMPS[target_elf] = ({}, str(e))
    by_name, how = _LAMPS[target_elf]
    ins = by_name.get(ref[3])
    if ins is None:
        report["lamp missing"] += 1
        return "# lamp %-40s left out: the target names no insert %s (%s)" % (rest.split("#")[0].strip(), ref[3], how)
    if not ins["shot"] and ref[2]:
        ins = dict(ins, shot=ref[2])            # the target's shot table was not read: keep the reference's tie
    report["lamp placed"] += 1
    return lamp_map.lamp_line(ins)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ref_elf")
    ap.add_argument("ref_port")
    ap.add_argument("target_elf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--game")
    ap.add_argument("--version")
    args = ap.parse_args(argv)
    ref, tgt = Elf(args.ref_elf), Elf(args.target_elf)
    rf, tf = Finder(ref), Finder(tgt)
    entries = parse_port(args.ref_port)
    out = ["# DRAFTED by port_tool.py from %s" % args.ref_port.replace("\\", "/").split("/")[-1],
           "# target ELF: %s" % args.target_elf.replace("\\", "/").split("/")[-1],
           "# Every entry says how it was placed. COPIED entries are unverified: prove them in the",
           "# emulator (MODE_SDK.md). Re-run port_words.py on the result before shipping it."]
    report = Counter()
    missing_core = []
    started = False
    ref_game = target_game = args.game
    for key, rest in entries:
        if key == "#":
            # the reference's comments describe the reference build (its header, how each of
            # its entries was placed, at its addresses): keep only the section headings
            if started and (rest.startswith("# ----") or not rest.strip()):
                out.append(rest)
            continue
        started = True
        if key == "game":
            ref_game, target_game = rest, args.game or rest
            out.append("game           %s" % target_game)
            continue
        if key == "version":
            out.append("version        %s" % (args.version or rest))
            continue
        parts = rest.split()
        if key == "site":
            name, va = parts[0], int(parts[1], 0)
            hook_cands = []
            if va in ref.name_by_plt:
                sym = ref.name_by_plt[va]
                tva = tgt.plt_by_name.get(sym)
                how = "PLT stub for %s" % sym if tva else "no PLT stub for %s in the target" % sym
            elif ref.in_text(va):
                ti, how = locate(ref, rf, tgt, tf, ref.idx(va))
                tva = tgt.va(ti) if ti is not None else None
                how = "located (%s)" % how if tva else how
                if tva is None or how == "located (loose)":
                    # a loose signature can match a sibling of the same shape (Jaws's end of
                    # ball did); the hook a handler is registered for cannot
                    hva, hhow, hook_cands = via_hook(ref, rf, tgt, tf, va)
                    if hva is not None:
                        if tva is not None and tva != hva:
                            hhow += "; a loose signature pointed at 0x%x instead" % tva
                        tva, how = hva, hhow
                    elif hook_cands and tva is not None and tva not in hook_cands:
                        tva, how = None, "a loose signature matched 0x%x, which no handler of its hooks calls; %s" % (tva, hhow)
                    elif hook_cands and tva is None:
                        how = "%s; %s" % (how, hhow)
                if tva is None and not hook_cands:
                    tva, how2 = via_callers(ref, rf, tgt, tf, va)
                    how = how2 if tva else "%s; %s" % (how, how2)
            else:
                tva, how = None, "not in the reference text"
            if tva is None:
                out.append("# site %-16s NOT PLACED: %s" % (name, how))
                for hc in hook_cands:
                    out.append("#   candidate: 0x%x, called by a handler of one of its hooks - drain a ball "
                               "with each hooked and keep the one that fires" % hc)
                if ref.in_text(va):
                    for rd, td in callee_hints(ref, rf, tgt, tf, va)[:3]:
                        out.append("#   candidate: the reference %s calls 0x%x, which is 0x%x in the target "
                                   "- prove what it does before using it" % (name, rd, td))
                report["site missing"] += 1
                if name in CORE_SITES:
                    missing_core.append(name)
                continue
            if name in HOOKED and not is_hooked_ok(tgt, tva):
                out.append("# site %-16s NOT PLACED: 0x%08x starts pc-relative, cannot be hooked" % (name, tva))
                report["site missing"] += 1
                if name in CORE_SITES:
                    missing_core.append(name)
                continue
            out.append("#   %s: %s" % (name, how))
            out.append("site %-16s 0x%08x 0x%08x 0x%08x" % (name, tva, tgt.word(tva), tgt.word(tva + 4)))
            report["site placed"] += 1
        elif key == "data":
            name, va = parts[0], int(parts[1], 0)
            v, how = derive(ref, rf, tgt, tf, va)
            if v is None and name in ONE_PLACE_DATA and how.startswith("only 1 place"):
                v1, how1 = derive(ref, rf, tgt, tf, va, want=1)
                if v1 is not None:
                    v, how = v1, "%s; ONE place is enough here: %s" % (how1, ONE_PLACE_DATA[name])
            if v is None:
                out.append("# data %-22s NOT PLACED: %s" % (name, how))
                report["data missing"] += 1
                if name in CORE_DATA:
                    missing_core.append(name)
                continue
            out.append("#   %s: %s" % (name, how))
            out.append("data %-22s 0x%08x" % (name, v))
            report["data placed"] += 1
        elif key == "scene":
            role, sid = parts[0], parts[1] if len(parts) > 1 else ""
            at = ref.b.find(sid.encode() + b"\0")
            sva = None
            if at >= 0:
                for off, v, fsz, _f in ref.loads:
                    if off <= at < off + fsz:
                        sva = v + at - off
            tid = None
            if sva is not None:
                tv, how = derive(ref, rf, tgt, tf, sva, want=1)
                s = tgt.cstring(tv) if tv is not None else None
                if s and re.fullmatch(rb"[0-9a-f]{40}", s):
                    tid = s.decode()
                    how = "derived: the target code loads it (%s)" % how
                elif tv is not None:
                    how = "derived an address, but it holds no 40-hex id"
            else:
                how = "the reference code names no such id"
            if tid:
                out.append("#   scene %s: %s" % (role, how))
                out.append("scene %-20s %s" % (role, tid))
                report["scene derived"] += 1
            elif tgt.b.find(sid.encode() + b"\0") >= 0:
                out.append("#   scene %s: COPIED, unverified (%s; the target program names the same id)" % (role, how))
                out.append("scene %-20s %s" % (role, sid))
                report["scene copied"] += 1
            else:
                out.append("# scene %-20s NOT PLACED: the target program never names %s (%s)" % (role, sid[:8], how))
                cand, anchor = scene_by_neighbours(ref, tgt, at) if at >= 0 else (None, None)
                if cand:
                    out.append("#   candidate: %s, the first id after \"%s\" in the target, as in the "
                               "reference - prove it holds this role" % (cand, anchor))
                report["scene missing"] += 1
        elif key == "event":
            # item 147: bus ids are dispatched by shared framework code, but what each id MEANS
            # is measured per build (event_probe.c); a copy is a lead until a mark proves it
            out.append("#   event %s: COPIED, unverified - prove it with event_probe.c (MODE_SDK.md, Events)"
                       % (parts[0] if parts else "?"))
            out.append("event %s" % rest)
            report["event copied"] += 1
        elif key == "lamp":
            # item mode-leds: an insert's light ids move from build to build; its NAME is the game's own,
            # so the target's inserts are re-read (lamp_map.py) and the line placed by name
            out.append(lamp_draft(rest, args.target_elf, title_of(target_game) != title_of(ref_game), report))
        elif (key in ("shot", "callout", "text") or (key == "value" and parts and parts[0] in TITLE_VALUES)) \
                and title_of(target_game) != title_of(ref_game):
            # shot bits, sound ids, rule ids and example names belong to the reference TITLE
            out.append("# %s %s   <- %s's, not this title's" % (key, rest, ref_game))
            report["%s left out" % key] += 1
        elif key in ("value", "shot", "callout", "text"):
            out.append("%s %s" % (key, rest))
            report["%s copied" % key] += 1
        else:
            out.append("%s %s" % (key, rest))
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print("wrote %s" % args.out)
    for k in sorted(report):
        print("  %-16s %d" % (k, report[k]))
    print("  (value, shot, callout and text lines are COPIED from the reference, unverified)")
    if missing_core:
        print("CORE MISSING: %s - the runtime would hook nothing with this port" % ", ".join(missing_core))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
