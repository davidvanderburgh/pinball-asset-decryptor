"""Drafting a game build's PORT from a port that already works, without the reference program.

A port tells the mode runtime where one game build keeps the functions and globals it hooks
(``tools/spike2_emu/modes/sdk/MODE_SDK.md``, "Ports"). A new build's port is drafted from a
proven one by lining the reference's code up with the new build's. That takes two programs:
the REFERENCE (whose port is proven) and the TARGET (the card in hand). A person's PC only
ever has the target, so the drafting is split in two:

* :func:`compile_recipe` runs once per shipped port, at the desk, with the reference program.
  It works out everything the reference side of a draft needs - for each entry, which
  masked instruction sequences are unique in the reference, which functions load a global
  and where, which handlers call a function through the event bus - and keeps it as a
  RECIPE: hashes of masked instruction words, masks, offsets and a few strings, never the
  reference's code. Recipes ship beside the ports (``ports/recipes/<port>.recipe.gz``).
* :func:`apply_recipe` runs on the person's PC with the target program alone and writes the
  draft, entry by entry, saying how sure it is (the rules are ``port_tool.py``'s: see its
  docstring and MODE_SDK.md, "Making a port").

``draft()`` does both, which is what the command line ``port_tool.py`` does; its drafts are
byte-identical to the tool's before the split.

Speed: the target's code is indexed once (movw immediates, first-word candidates, every
``bl``), and a masked sequence is found by hashing candidate windows in one numpy pass.
"""
import gzip
import hashlib
import json
import re
import struct
from collections import Counter, defaultdict

import numpy as np

#: bump when a change here changes what a draft says (cached derived ports are re-derived); 2: the
#: framework core (portswitch: shots from the switch drain, the end of ball from the bus, cur_player
#: through the scores) fills what no reference places
#: 3: four one-place rodata tables (Godzilla's Ebirah stage awards and lamp table, the tank path and
#: spot list) are carried like layered_displays
#: 4: the Insider Connected score gate (agent_header + agent_begin), which every port must carry
REVISION = 4
RECIPE_FORMAT = 1

CORE_SITES = ("tick", "shot_dispatch", "ball_end", "score_add")
CORE_DATA = ("cur_player", "scores")
#: the two ways a build adds a score: 64-bit (score_add(player, u64 points in r2:r3) into u64
#: scores) or 32-bit (score_add32(player, u32 points in r1) into u32 scores32, The Beatles and
#: Star Wars ELG). A port names ONE pair; the runtime refuses a port with neither.
SCORE_PAIRS = (("score_add", "scores"), ("score_add32", "scores32"))
HOOKED = ("tick", "shot_dispatch", "ball_end", "sound_lookup", "hook_dispatch", "switch_edge",
          "agent_header", "agent_begin")     # item 166: the Insider Connected score gate
# values that are one title's rules, not the framework's: Godzilla's are Tesla Strike's
# light owner and light set, and its powerline-tower award screen
TITLE_VALUES = ("light_owner", "light_lts", "award_screen_type")
MIN_N, MAX_N = 8, 48
# globals ONE lined-up place may place (the rule is two), each with the reason one is enough
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
DERIVE_TRIES = 60
MORE_TRIES = 140
CALLER_TRIES = 80
VSLOTS = 48          # a rule manager's vtable is read this far
VSLOT_N = 4          # a virtual is known by its first four (loose) instructions among them


class PortgenError(ValueError):
    """A program or a recipe that cannot be used, with the reason in words."""


# ---- the ELF ----------------------------------------------------------------------------
def rot_imm(w):
    rot, imm = (w >> 8) & 0xF, w & 0xFF
    return ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF if rot else imm


class Elf:
    """A 32-bit ARM game program: its loads, its text as words, its PLT stubs by name."""

    def __init__(self, path_or_bytes, name=None):
        if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
            self.b = bytes(path_or_bytes)
            self.path = name or "the game program"
        else:
            self.path = path_or_bytes
            with open(path_or_bytes, "rb") as f:
                self.b = f.read()
        b = self.b
        if len(b) < 0x34 or b[:4] != b"\x7fELF" or b[4] != 1:
            raise PortgenError("%s: not a 32-bit ELF" % self.path)
        try:
            self._parse(b)
        except PortgenError:
            raise
        except (struct.error, ValueError, IndexError, UnicodeDecodeError) as e:
            # a cut-off or odd program is refused in words, never with a struct or numpy error
            raise PortgenError("%s: the program cannot be read (%s)" % (self.path, e)) from None
        self._sha1 = None
        self._movw_by_lo = None
        self._refs = {}
        self._bl = None

    def _parse(self, b):
        phoff, = struct.unpack_from("<I", b, 0x1C)
        phentsize, phnum = struct.unpack_from("<HH", b, 0x2A)
        if phnum and (phentsize < 32 or phoff + phnum * phentsize > len(b)):
            raise PortgenError("%s: its program headers run past its end" % self.path)
        self.loads = []
        for i in range(phnum):
            t, off, va, _pa, fsz, _msz, flags, _al = struct.unpack_from("<8I", b, phoff + i * phentsize)
            if t == 1:
                self.loads.append((off, va, fsz, flags))
        texts = [l for l in self.loads if l[3] & 1]
        if not texts:
            raise PortgenError("%s: no executable code" % self.path)
        self.toff, self.tva, self.tsz = texts[0][0], texts[0][1], texts[0][2]
        if self.tsz < 4 or self.toff + self.tsz > len(b):
            raise PortgenError("%s: its code runs past the end of the file (cut off?)" % self.path)
        # the same words as an array: a whole-text scan is one vector compare, not a loop
        self.arr = np.frombuffer(b, dtype="<u4", count=self.tsz // 4, offset=self.toff)
        self.words = self.arr.tolist()
        self.sections = self._sections()
        self.plt_by_name, self.name_by_plt = self._plt()

    @property
    def sha1(self):
        if self._sha1 is None:
            self._sha1 = hashlib.sha1(self.b).hexdigest()
        return self._sha1

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
        if not shoff or not shnum or shoff + shnum * shentsize > len(b):
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
            if None not in (w0, w1, w2) and (w0 & 0xFFFFF000) == 0xE28FC000 and \
                    (w1 & 0xFFFFF000) == 0xE28CC000 and (w2 & 0xFFFFF000) == 0xE5BCF000:
                got = va + 8 + rot_imm(w0) + rot_imm(w1) + (w2 & 0xFFF)
                if got in slot_name:
                    by_name[slot_name[got]] = va
                    by_plt[va] = slot_name[got]
                va += 12
            else:
                va += 4
        return by_name, by_plt

    # ---- indexes built once per program -----------------------------------------------------
    def movw_by_lo(self):
        """{16-bit immediate: [indexes of movw rd, #imm]}."""
        if self._movw_by_lo is None:
            a = self.arr
            movw = np.nonzero((a & np.uint32(0x0FF00000)) == np.uint32(0x03000000))[0]
            imm = (((a[movw] >> np.uint32(16)) & np.uint32(0xF)) << np.uint32(12)) | (a[movw] & np.uint32(0xFFF))
            by = defaultdict(list)
            for i, v in zip(movw.tolist(), imm.tolist()):
                by[v].append(i)
            self._movw_by_lo = by
        return self._movw_by_lo

    def bl_index(self):
        """{destination address: sorted [indexes of every bl to it]}."""
        if self._bl is None:
            a = self.arr
            is_bl = np.nonzero((a & np.uint32(0x0F000000)) == np.uint32(0x0B000000))[0]
            off = (a[is_bl] & np.uint32(0xFFFFFF)).astype(np.int64)
            off = np.where(off & 0x800000, off - 0x1000000, off)
            dest = self.tva + 4 * is_bl.astype(np.int64) + 8 + off * 4
            by = defaultdict(list)
            for i, d in zip(is_bl.tolist(), dest.tolist()):
                by[d].append(i)
            self._bl = by
        return self._bl


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


_MASK_CHAR = {0xFFFFFFFF: "f", 0xFF000000: "b", 0xFFFFF000: "p", 0xFFF0F000: "w"}
_CHAR_MASK = {v: k for k, v in _MASK_CHAR.items()}


def sig(elf, i, n, loose):
    return [(w & mask_of(w, loose), mask_of(w, loose)) for w in elf.words[i:i + n]]


def matches_at(elf, i, s):
    if i < 0 or i + len(s) > len(elf.words):
        return False
    return all((elf.words[i + k] & m) == v for k, (v, m) in enumerate(s))


class Finder:
    """Every place a masked sequence matches in one program: candidates by the first masked
    word (cached), then filtered a word at a time in numpy."""

    def __init__(self, elf):
        self.elf = elf
        self.cache = {}

    def cands(self, v, m):
        key = (v, m)
        if key not in self.cache:
            self.cache[key] = np.nonzero((self.elf.arr & np.uint32(m)) == np.uint32(v))[0]
        return self.cache[key]

    def find(self, s):
        idx = self.cands(*s[0])
        if not len(idx):
            return []
        a = self.elf.arr
        idx = idx[idx + len(s) <= len(a)]
        for k, (v, m) in enumerate(s[1:], 1):
            if not len(idx):
                break
            idx = idx[(a[idx + k] & np.uint32(m)) == np.uint32(v)]
        return idx.tolist()


def locate(ref, rf, tgt, tf, i, need=0):
    """The target index of the reference function starting at index i, or (None, why), with
    both programs in hand. `need` = the signature must cover at least this many words."""
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
        if (elf.words[k] & 0xFFFF4000) == 0xE92D4000:
            return k
    return None


# ---- how code loads an address --------------------------------------------------------------
def movw_imm(w):
    return ((w >> 16) & 0xF) << 12 | (w & 0xFFF)


def refs_to(elf, target, limit=400):
    """[(kind, index, extra)] where the text loads `target`: ('movw', i_movw, i_movt) or
    ('lit', i_ldr, pool_va). Memoised per program."""
    key = (target, limit)
    hit = elf._refs.get(key)
    if hit is not None:
        return hit
    out = []
    lo, hi = target & 0xFFFF, (target >> 16) & 0xFFFF
    W = elf.words
    hits = sorted(elf.movw_by_lo().get(lo, []) + np.nonzero(elf.arr == np.uint32(target))[0].tolist())
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
    elf._refs[key] = out
    return out


def value_at(elf, kind, i, j):
    W = elf.words
    if not (0 <= i < len(W) and 0 <= j < len(W)):
        return None
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
    if not 0 <= i < len(elf.words):
        return None
    w = elf.words[i]
    if (w & 0x0F000000) != 0x0B000000:
        return None
    off = w & 0xFFFFFF
    if off & 0x800000:
        off -= 0x1000000
    return elf.va(i) + 8 + off * 4


def bl_callers(elf, address):
    return elf.bl_index().get(address, [])


def hook_id_before(elf, k):
    """The n of the `mov r1, #n` just before index k, or None."""
    for m in range(k - 1, max(k - 9, 0), -1):
        w = elf.words[m]
        if (w & 0x0FFFF000) == 0x03A01000:
            return rot_imm(w)
    return None


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


def is_hooked_ok(tgt, va):
    """Can the runtime move a hooked function's first two instructions into a trampoline?"""
    w0, w1 = tgt.word(va), tgt.word(va + 4)
    if w0 is None or w1 is None:
        return False

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


#: ids below this are the game's event bus ids (pad_mode_runtime.c N_BUS_IDS)
BUS_IDS = 208


def core_names(sites, values=None, switches=0):
    """(sites, data) of the core one port uses, as pad_mode_runtime.c core_of_port picks them:
    ``sites``/`values` hold the port's site names and ``{value name: number}``, `switches` its number
    of `switch` lines. A switch_edge (the framework's switch drain) or switch_hit site with switch
    lines stands in for the shot dispatch, value ball_end_event (a bus id) with site hook_dispatch
    for the end of ball, and site score_add32 picks the 32-bit scoring pair. mode_project's
    ``_core_names`` is this rule on a read port."""
    values = values or {}
    s32 = SCORE_PAIRS[1][0] in sites
    no_sd = "shot_dispatch" not in sites
    shots = ("switch_edge" if no_sd and "switch_edge" in sites and switches
             else "switch_hit" if no_sd and "switch_hit" in sites and switches else "shot_dispatch")
    event = values.get("ball_end_event", -1)
    event = event if isinstance(event, int) else -1
    ball_end = "hook_dispatch" if "ball_end" not in sites and 0 <= event < BUS_IDS else "ball_end"
    pair = SCORE_PAIRS[1] if s32 else SCORE_PAIRS[0]
    return ("tick", shots, ball_end, pair[0]), ("cur_player", pair[1])


def core_missing(sites, data, values=None, switches=0):
    """The core entries a port lacks, in the order a port lists them: tick, the shot source, the end
    of ball, a scoring site, cur_player and its scores - [] exactly when the runtime would hook the
    port (:func:`core_names`: `values` is ``{name: number}``, `switches` the number of `switch`
    lines). When the port names neither scoring site, the scores it names say which pair is missing."""
    want_sites, want_data = core_names(sites, values, switches)
    if not any(p[0] in sites for p in SCORE_PAIRS) and SCORE_PAIRS[1][1] in data:
        want_sites = want_sites[:3] + (SCORE_PAIRS[1][0],)
        want_data = ("cur_player", SCORE_PAIRS[1][1])
    return [n for n in want_sites if n not in sites] + [n for n in want_data if n not in data]


def score_width(elf, va):
    """64 when the score function at va multiplies into a 64-bit value (umull/umlal: u64 scores),
    32 when it multiplies with mul/mla only (u32 scores), 0 when it cannot tell."""
    i = elf.idx(va)
    long_mul = short_mul = False
    for k in range(i, min(i + 300, len(elf.words))):
        w = elf.words[k]
        if k > i + 8 and (w & 0xFFFF4000) == 0xE92D4000:      # the next function's push {.., lr}
            break
        op = w & 0x0FE000F0
        if op in (0x00800090, 0x00A00090, 0x00C00090, 0x00E00090):
            long_mul = True
        elif op in (0x00000090, 0x00200090):
            short_mul = True
    return 64 if long_mul else 32 if short_mul else 0


def class_vptr(elf, mangled):
    """The address a C++ object of class `mangled` (its typeinfo name, "13crule_manager") keeps as
    its vptr: the typeinfo whose name it is, then the vtable whose word -1 is that typeinfo and
    word -2 is 0. None when the program has no such class."""
    at = elf.b.find(b"\0" + mangled + b"\0")
    if at < 0:
        return None
    at += 1
    name_va = None
    for off, v, fsz, _f in elf.loads:
        if off <= at < off + fsz:
            name_va = v + at - off
    if name_va is None:
        return None

    def words_equal(value):
        for off, v, fsz, _f in elf.loads:
            skip = (-v) % 4
            n = (fsz - skip) // 4
            if n <= 0:
                continue
            a = np.frombuffer(elf.b, dtype="<u4", count=n, offset=off + skip)
            for k in np.nonzero(a == np.uint32(value))[0].tolist():
                yield v + skip + 4 * k
    for ti_name in words_equal(name_va):
        ti = ti_name - 4
        for at_ti in words_equal(ti):
            if elf.word(at_ti - 4) == 0:
                return at_ti + 4
    return None


MANAGERS = (b"13cmode_manager", b"13crule_manager")


def title_of(game):
    """godzilla_pro and godzilla_le are one title: they share shot bits and sound ids."""
    return re.sub(r"_(le|pro|premium|prem|ce|se)$", "", game or "")


# ---- hashing masked sequences -----------------------------------------------------------------
_M64 = (1 << 64) - 1
_COEF = np.zeros(0, dtype=np.uint64)


def _coeffs(n):
    """The first n multipliers of the sequence hash: splitmix64 from a fixed seed, odd."""
    global _COEF
    if len(_COEF) < n:
        out, x = [], 0x5EED0F90
        for _ in range(max(n, 2 * len(_COEF), 512)):
            x = (x + 0x9E3779B97F4A7C15) & _M64
            z = x
            z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
            z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
            out.append((z ^ (z >> 31)) | 1)
        _COEF = np.array(out, dtype=np.uint64)
    return _COEF[:n]


def _hash_rows(masked):
    """One 64-bit hash per row of masked words (a 2-D uint32 array); rows of equal words and
    equal length hash equal."""
    x = masked.astype(np.uint64)
    x = x * np.uint64(0x9E3779B97F4A7C15)
    x ^= x >> np.uint64(29)
    return (x * _coeffs(masked.shape[1])).sum(axis=1, dtype=np.uint64)


def _masks_array(masks):
    return np.array([_CHAR_MASK[c] for c in masks], dtype=np.uint32)


# ---- the recipe: the reference side of every draft, computed once ------------------------------
class _Compiler:
    """Builds a recipe from the reference program and its port."""

    def __init__(self, ref):
        self.ref = ref
        self.rf = Finder(ref)
        self.chains = []            # [v0, v1, masks, {n: hash}]
        self.chain_at = {}          # (start, loose) -> id
        self.ladders = []           # [top, [[loose, n, chain id or -1], ...]]
        self.ladder_at = {}

    def chain(self, start, loose, n):
        """The id of the masked sequence from `start`, with its hash at length n recorded."""
        ref = self.ref
        n = max(0, min(n, len(ref.words) - start))
        key = (start, bool(loose))
        cid = self.chain_at.get(key)
        if cid is None:
            cid = self.chain_at[key] = len(self.chains)
            self.chains.append([0, 0, "", {}])
        c = self.chains[cid]
        if len(c[2]) < n:
            ms = [mask_of(w, loose) for w in ref.words[start:start + n]]
            c[2] = "".join(_MASK_CHAR[m] for m in ms)
            c[0] = ref.words[start] & ms[0] if n else 0
            c[1] = ref.words[start + 1] & ms[1] if n > 1 else 0
        if n not in c[3]:
            if n:
                row = ref.arr[start:start + n] & _masks_array(c[2][:n])
                c[3][n] = int(_hash_rows(row[None, :])[0])
            else:
                c[3][n] = 0
        return cid

    def ladder(self, i, need=0):
        """locate()'s steps for the reference function at index i: each signature that is
        unique in the reference, in the order locate() tries them."""
        key = (i, need)
        lid = self.ladder_at.get(key)
        if lid is not None:
            return lid
        top = max(MAX_N, need)
        steps = []
        for loose in (False, True):
            n = max(MIN_N, need)
            while n <= top:
                s = sig(self.ref, i, n, loose)
                rh = self.rf.find(s) if s else []
                if len(rh) == 1:
                    steps.append([int(loose), n, self.chain(i, loose, n)])
                elif not rh:
                    steps.append([int(loose), n, -1])
                    break
                n += 4
            if steps and steps[-1][2] == -1:
                break
        lid = self.ladder_at[key] = len(self.ladders)
        self.ladders.append([top, steps])
        return lid

    # -- data: code that loads an address ------------------------------------------------------
    def load_items(self, address, field=None, tries=DERIVE_TRIES):
        """The functions that load `address`, as derive() lines them up: the first `tries` in address
        order, then, for a global loaded from more places than that (a current-player byte has
        hundreds), up to MORE_TRIES more, the SHORTEST first: the first ones may all have changed."""
        ref = self.ref
        found = []
        done = set()
        for kind, i, extra in refs_to(ref, address):
            if field is not None and not loads_field(ref, extra if kind == "movw" else i, field):
                continue
            start = func_start(ref, i)
            if start is None or (start, i) in done:
                continue
            done.add((start, i))
            j = extra if kind == "movw" else i
            found.append((kind, i, j, start, max(i, j) - start + 1))
        if len(found) > tries:
            rest = sorted((f for f in found[tries:] if f[4] <= 400), key=lambda f: (f[4], f[1]))
            found = found[:tries] + rest[:MORE_TRIES]
        out = []
        for kind, i, j, start, need in found:
            if need > 400:
                continue
            out.append(["m" if kind == "movw" else "l", self.ladder(start, need), self.chain(start, True, need),
                        need, i - start, j - start, "0x%x+0x%x" % (ref.va(start), 4 * (i - start))])
        return out

    def derive(self, address):
        fields = []
        for off in range(4, 0x200, 4):
            items = self.load_items(address - off, field=off)
            if items:
                fields.append([off, items])
        return {"direct": self.load_items(address), "fields": fields}

    # -- sites ---------------------------------------------------------------------------------
    def hook_items(self, address):
        ref = self.ref
        out = []
        for i in bl_callers(ref, address):
            push = func_start(ref, i)
            if push is None or i - push > 40:
                continue
            for h in range(push, max(push - 4, -1), -1):
                for kind, j, jt in refs_to(ref, ref.va(h), limit=8):
                    if kind != "movw":
                        continue
                    call = next((k for k in range(max(j, jt), min(jt + 9, len(ref.words)))
                                 if bl_dest(ref, k) is not None), None)
                    if call is None:
                        continue
                    hook = hook_id_before(ref, call)
                    if hook is None:
                        continue
                    reg = ref.idx(bl_dest(ref, call))
                    if not 0 <= reg < len(ref.words):
                        continue
                    out.append([hook, self.ladder(reg), self.chain(h, True, i - h), i - h])
        return out

    def caller_items(self, address, tries=CALLER_TRIES):
        ref = self.ref
        out = []
        tried = 0
        for i in bl_callers(ref, address):
            start = func_start(ref, i)
            if start is None or i - start > 400:
                continue
            tried += 1
            if tried > tries:
                break
            need = i - start + 1
            out.append([self.ladder(start, need), self.chain(start, True, need), need, i - start,
                        "0x%x" % ref.va(i)])
        return out

    def hints(self, address, cap=96):
        ref = self.ref
        i = ref.idx(address)
        out, seen = [], set()
        for k in range(cap):
            if i + k >= len(ref.words):
                break
            w = ref.words[i + k]
            d = bl_dest(ref, i + k) if (w & 0xF0000000) != 0xF0000000 else None
            if d is None and (w >> 28) == 0xE and (w & 0x0F000000) == 0x0A000000:
                d = ref.va(i + k) + 8 + (((w & 0xFFFFFF) ^ 0x800000) - 0x800000) * 4   # a tail call
            if d is not None and ref.in_text(d) and d != address and d not in seen:
                seen.add(d)
                out.append([d, self.ladder(ref.idx(d))])
            if w == 0xE12FFF1E or (w & 0xFFFF8000) == 0xE8BD8000:     # bx lr, pop {..., pc}
                break
        return out

    def site(self, va):
        ref = self.ref
        if va in ref.name_by_plt:
            return {"plt": ref.name_by_plt[va]}
        if not ref.in_text(va):
            return {}
        out = {"lid": self.ladder(ref.idx(va)), "hook": self.hook_items(va),
               "callers": self.caller_items(va), "hints": self.hints(va)}
        slot = self.vslot(va)
        if slot is not None:
            out["vslot"] = [slot[0], slot[1], self.chain(ref.idx(va), True, VSLOT_N), VSLOT_N]
        return out

    def vslot(self, va):
        """(manager class, slot) when va is a virtual of the game's C++ rule manager."""
        if not hasattr(self, "_vslots"):
            self._vslots = {}
            for name in MANAGERS:
                vp = class_vptr(self.ref, name)
                if vp is None:
                    continue
                for k in range(VSLOTS):
                    f = self.ref.word(vp + 4 * k)
                    if f is not None and self.ref.in_text(f):
                        self._vslots.setdefault(f, (name.decode(), k))
        return self._vslots.get(va)

    def scene(self, sid):
        ref = self.ref
        at = ref.b.find(sid.encode() + b"\0")
        sva = None
        if at >= 0:
            for off, v, fsz, _f in ref.loads:
                if off <= at < off + fsz:
                    sva = v + at - off
        out = {"derive": self.derive(sva) if sva is not None else None, "sva": sva, "anchors": None}
        if at >= 0:
            window = ref.b[max(0, at - 256):at]
            anchors = [m.group(1) for m in re.finditer(rb"(?<=\0)([ -~]{6,})\0", b"\0" + window)][::-1]
            out["anchors"] = [a.decode("latin1") for a in anchors[:4]]
        return out


LINE = re.compile(r"^(\s*)(\w+)\s+(.*)$")


def parse_port(text):
    """A port's lines as [(key, rest)]; a comment or a blank line is ("#", the line)."""
    entries = []
    for raw in text.splitlines():
        m = LINE.match(raw)
        if not m or raw.lstrip().startswith("#"):
            entries.append(("#", raw))
            continue
        entries.append((m.group(2), m.group(3)))
    return entries


def entries_sha1(text):
    """A port's entries (every line but comments and blanks, spaces normalised), hashed: what a
    recipe and a derived port depend on. A comment edit does not change it."""
    h = hashlib.sha1()
    for key, rest in parse_port(text):
        if key != "#":
            h.update((" ".join([key] + rest.split("#", 1)[0].split()) + "\n").encode("utf-8"))
    return h.hexdigest()


def _entry_key(key, parts):
    return "%s %s %s" % (key, parts[0], parts[1] if len(parts) > 1 else "")


def bus_bound(elf):
    """The event bus's highest id (its dispatch starts `cmp r0, #N; push`), or 0. Builds of one
    framework generation share it; the two generations number their events differently."""
    a = elf.arr
    cmp0 = (a[:-1] & np.uint32(0xFFFFFF00)) == np.uint32(0xE3500000)
    push = (a[1:] & np.uint32(0xFFFF4000)) == np.uint32(0xE92D4000)
    ids = [int(a[i]) & 0xFF for i in np.nonzero(cmp0 & push)[0].tolist()]
    sub = (a[:-1] & np.uint32(0xFFFFFF00)) == np.uint32(0xE3510000)
    subs = {int(a[i]) & 0xFF for i in np.nonzero(sub & push)[0].tolist()}
    both = sorted({n for n in ids if n >= 150 and n in subs})
    return both[-1] if both else 0


def _regs_before(elf, k, back=12):
    """{register: constant} for r0-r3 at the call at index k: mov/movw/movt/literal loads in the
    instructions before it (back to the previous call); None where a register was written with
    something else."""
    W = elf.words
    out, hi = {}, {}
    for m in range(k - 1, max(k - back, 0) - 1, -1):
        w = W[m]
        if (w & 0x0F000000) == 0x0B000000 or (w & 0x0FFFFFF0) == 0x012FFF30:
            break
        rd = (w >> 12) & 0xF
        if rd > 3 or rd in out:
            continue
        if (w >> 28) != 0xE:
            out[rd] = None
        elif (w & 0x0FEF0000) == 0x03A00000:                  # mov rd, #imm
            out[rd] = rot_imm(w & 0xFFF)
        elif (w & 0x0FF00000) == 0x03400000:                  # movt rd (its movw is earlier)
            hi[rd] = movw_imm(w)
        elif (w & 0x0FF00000) == 0x03000000:                  # movw rd
            out[rd] = (hi.get(rd, 0) << 16) | movw_imm(w)
        elif (w & 0x0F7F0000) == 0x051F0000:                  # ldr rd, [pc, #n]
            imm = w & 0xFFF
            out[rd] = elf.word(elf.va(m) + 8 + (imm if w & 0x00800000 else -imm))
        elif (w & 0x0C000000) in (0x00000000, 0x04000000):
            out[rd] = None
    return out


def subscriptions(elf):
    """{bus id: [handler addresses]} from every call of the event bus's subscribe (it starts
    `cmp r1, #N; push`): subscribe(?, r1 id, r2 handler, r3 priority). Cached per program."""
    hit = getattr(elf, "_subs", None)
    if hit is not None:
        return hit
    a = elf.arr
    sub = (a[:-1] & np.uint32(0xFFFFFF00)) == np.uint32(0xE3510000)
    push = (a[1:] & np.uint32(0xFFFF4000)) == np.uint32(0xE92D4000)
    out = defaultdict(list)
    for i in np.nonzero(sub & push)[0].tolist():
        if (int(a[i]) & 0xFF) < 150:
            continue
        for k in bl_callers(elf, elf.va(i)):
            r = _regs_before(elf, k)
            ident, h = r.get(1), r.get(2)
            if ident is not None and h and elf.in_text(h) and h not in out[ident]:
                out[ident].append(h)
    elf._subs = dict(out)
    return elf._subs


def generation(bound):
    """"A" (the older framework, bus bound under 200) or "B"; "" when unknown."""
    if not bound:
        return ""
    return "A" if bound < 200 else "B"


def compile_recipe(ref_elf, port_text, port_name, progress=None):
    """The recipe for one proven port, from its own program (an :class:`Elf`, a path or bytes)."""
    ref = ref_elf if isinstance(ref_elf, Elf) else Elf(ref_elf)
    c = _Compiler(ref)
    sites, data, scenes = {}, {}, {}
    entries = parse_port(port_text)
    body = [(k, r) for k, r in entries if k in ("site", "data", "scene")]
    for n, (key, rest) in enumerate(body):
        if progress is not None:
            progress(n / max(1, len(body)), "%s %s" % (key, rest.split()[0] if rest.split() else ""))
        parts = rest.split()
        if len(parts) < 2:
            continue
        k = _entry_key(key, parts)
        if key == "site":
            sites[k] = c.site(int(parts[1], 0))
        elif key == "data":
            data[k] = c.derive(int(parts[1], 0))
        elif key == "scene":
            scenes[k] = c.scene(parts[1])
    bound = bus_bound(ref)
    bus = {}
    for key, rest in entries:
        w = rest.split("#", 1)[0].split() if key == "event" else []
        if len(w) >= 2 and w[0] == "ball_end" and w[1] != "site":
            ident = int(w[1], 0)
            hs = [h for h in subscriptions(ref).get(ident, []) if is_hooked_ok(ref, h)]
            bus["ball_end"] = [ident, [[h, c.ladder(ref.idx(h))] for h in hs]]
    return {"format": RECIPE_FORMAT, "revision": REVISION, "port": port_name, "bus": bus,
            "entries_sha1": entries_sha1(port_text), "elf_sha1": ref.sha1,
            "bus_bound": bound, "generation": generation(bound),
            "chains": c.chains, "ladders": c.ladders, "sites": sites, "data": data, "scenes": scenes}


def save_recipe(recipe, path):
    raw = json.dumps(recipe, separators=(",", ":"), sort_keys=True).encode("utf-8")
    with open(path, "wb") as f:
        # mtime 0: the same recipe is the same file, byte for byte
        with gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0, compresslevel=9) as g:
            g.write(raw)


def load_recipe(path):
    with gzip.open(path, "rb") as f:
        r = json.loads(f.read().decode("utf-8"))
    if r.get("format") != RECIPE_FORMAT:
        raise PortgenError("%s is a recipe of another format" % path)
    for c in r["chains"]:
        c[3] = {int(k): v for k, v in c[3].items()}
    return r


# ---- the target side ---------------------------------------------------------------------------
class Target:
    """The target program with what a recipe asks of it cached."""

    def __init__(self, elf, recipe):
        self.elf = elf
        self.r = recipe
        self._cands = {}
        self._masks = {}
        self._ladder = {}

    def _chain_masks(self, cid, n):
        key = (cid, n)
        m = self._masks.get(key)
        if m is None:
            m = self._masks[key] = _masks_array(self.r["chains"][cid][2][:n])
        return m

    def find(self, cid, n):
        """Every index where chain `cid`'s first n masked words match."""
        c = self.r["chains"][cid]
        masks = c[2]
        if n == 0:
            return list(range(len(self.elf.words)))
        m0 = _CHAR_MASK[masks[0]]
        key = (c[0], m0, c[1] if n > 1 else None, _CHAR_MASK[masks[1]] if n > 1 else None)
        idx = self._cands.get(key)
        a = self.elf.arr
        if idx is None:
            idx = np.nonzero((a & np.uint32(m0)) == np.uint32(c[0]))[0]
            if n > 1:
                idx = idx[idx + 1 < len(a)]
                idx = idx[(a[idx + 1] & np.uint32(key[3])) == np.uint32(c[1])]
            self._cands[key] = idx
        idx = idx[idx + n <= len(a)]
        if not len(idx) or n <= 2:
            return idx.tolist()
        want = c[3][n]
        ms = self._chain_masks(cid, n)
        out = []
        for lo in range(0, len(idx), 4096):
            part = idx[lo:lo + 4096]
            rows = a[part[:, None] + np.arange(n)] & ms
            out.extend(part[_hash_rows(rows) == np.uint64(want)].tolist())
        return out

    def match_at(self, cid, n, i):
        a = self.elf.arr
        if i < 0 or i + n > len(a):
            return False
        if n == 0:
            return True
        c = self.r["chains"][cid]
        ms = self._chain_masks(cid, n)
        row = a[i:i + n] & ms
        if int(row[0]) != c[0] or (n > 1 and int(row[1]) != c[1]):
            return False
        return n <= 2 or int(_hash_rows(row[None, :])[0]) == c[3][n]

    def locate(self, lid):
        hit = self._ladder.get(lid)
        if hit is not None:
            return hit
        top, steps = self.r["ladders"][lid]
        res = None
        for loose in (0, 1):
            for lo, n, cid in steps:
                if lo != loose:
                    continue
                if cid == -1:
                    res = (None, "no signature")
                    break
                th = self.find(cid, n)
                if len(th) == 1:
                    res = (th[0], "loose" if loose else "strict")
                    break
                if not th and loose:
                    res = (None, "absent in the target (the function changed)")
                    break
                if not th:
                    break                   # try loose
                if n >= top:
                    res = (None, "ambiguous in the target (%d matches)" % len(th))
                    break
            if res is not None:
                break
        if res is None:
            res = (None, "not unique in the reference")
        self._ladder[lid] = res
        return res

    # -- data --------------------------------------------------------------------------------
    def derive_direct(self, items, want=2, field=None):
        tgt = self.elf
        seen = Counter()
        via = {}
        for kind, lid, cid, need, di, dj, via_s in items:
            t_start, _how = self.locate(lid)
            if t_start is None:
                continue
            # the whole stretch must line up under the loose mask, so offsets are the same
            if not self.match_at(cid, need, t_start):
                continue
            ti = t_start + di
            tj = t_start + dj if kind == "m" else ti
            v = value_at(tgt, "movw" if kind == "m" else "lit", ti, tj)
            if v is None:
                continue
            if field is not None and not loads_field(tgt, tj, field):
                continue
            seen[v] += 1
            via.setdefault(v, via_s)
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

    def derive(self, rec, address, want=2):
        v, how = self.derive_direct(rec["direct"], want)
        if v is not None:
            return v, how
        for off, items in rec["fields"]:
            bv, bhow = self.derive_direct(items, want, field=off)
            if bv is not None:
                return bv + off, "a base 0x%x + field 0x%x; the base %s" % (address - off, off, bhow)
        return None, how

    # -- sites -------------------------------------------------------------------------------
    def via_hook(self, items):
        tgt = self.elf
        found = Counter()
        for hook, reg_lid, cid, off in items:
            ri, _how = self.locate(reg_lid)
            if ri is None:
                continue
            for c in bl_callers(tgt, tgt.va(ri)):
                if hook_id_before(tgt, c) != hook:
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
                if th + off >= len(tgt.words) or not self.match_at(cid, off, th):
                    continue
                d = bl_dest(tgt, th + off)
                if d is not None:
                    found[(d, hook)] += 1
        if not found:
            return None, "no hook handler lined up", []
        if len(set(d for d, _h in found)) > 1:
            return None, "its hooks' handlers call different functions here: %s" % ", ".join(
                "0x%x (hook 0x%x)" % k for k in sorted(found)), sorted(d for d, _h in found)
        (d, hook), _n = found.most_common(1)[0]
        return d, "through the handler of hook 0x%x, as in the reference" % hook, [d]

    def via_callers(self, items, want=2):
        tgt = self.elf
        seen = Counter()
        via = {}
        for lid, cid, need, off, via_s in items:
            t_start, _how = self.locate(lid)
            if t_start is None or not self.match_at(cid, need, t_start):
                continue
            d = bl_dest(tgt, t_start + off)
            if d is None:
                continue
            seen[d] += 1
            via.setdefault(d, via_s)
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

    def via_bus(self, rec, rbound):
        """The end of ball as an event-bus handler: one of the reference's handlers of its
        end-of-ball event, located here and subscribed to the same event here. Only where the
        bus numbers its events as the reference's does."""
        ident, handlers = rec
        tgt = self.elf
        tb = bus_bound(tgt)
        if not tb or tb != rbound:
            return None, "this build's event bus numbers its events differently"
        mine = set(subscriptions(tgt).get(ident, []))
        found = {}
        for h, lid in handlers:
            ti, how = self.locate(lid)
            if ti is not None and tgt.va(ti) in mine and is_hooked_ok(tgt, tgt.va(ti)):
                found.setdefault(tgt.va(ti), (h, how))
        if len(found) != 1:
            return None, ("%d of the reference's handlers of event 0x%x line up with one here"
                          % (len(found), ident))
        va, (h, how) = next(iter(found.items()))
        return va, ("the handler of event 0x%x (the end of ball) that is the reference's 0x%x (located, %s) "
                    "- drain a ball to prove it" % (ident, h, how))

    def via_vslot(self, rec):
        """A manager virtual the reference's signature no longer finds: the one virtual of the
        target's manager of the same class that starts as the reference's does."""
        cls, slot, cid, n = rec
        tgt = self.elf
        vp = class_vptr(tgt, cls.encode())
        if vp is None:
            return None, "this build has no %s" % cls[2:]
        hits = {}
        for k in range(VSLOTS):
            f = tgt.word(vp + 4 * k)
            if f is not None and tgt.in_text(f) and self.match_at(cid, n, tgt.idx(f)):
                hits.setdefault(f, k)
        if len(hits) != 1:
            return None, "%d of its %s's virtuals start as the reference's does" % (len(hits), cls[2:])
        f, k = next(iter(hits.items()))
        return f, ("the one virtual of its %s that starts as the reference's does (slot %d; the "
                   "reference's is slot %d) - prove it with call_probe.c" % (cls[2:], k, slot))

    def hints(self, items):
        out = []
        for rd, lid in items:
            ti, _how = self.locate(lid)
            if ti is not None:
                out.append((rd, self.elf.va(ti)))
        return out

    def scene_by_neighbours(self, anchors):
        tgt = self.elf
        for a in anchors or []:
            a = a.encode("latin1")
            if re.fullmatch(rb"[0-9a-f]{40}", a):
                continue
            k = tgt.b.find(b"\0" + a + b"\0")
            if k < 0:
                continue
            m = re.search(rb"(?<=\0)[0-9a-f]{40}(?=\0)", tgt.b[k:k + 2048])
            if m:
                return m.group(0).decode(), a.decode("latin1")
        return None, None


# ---- lamps -------------------------------------------------------------------------------------
def lamp_draft(rest, target, other_title, report, cache):
    """One `lamp` line for the target (item mode-leds), placed by the insert's name in the target's own
    tables (lampmap), with the target's own shot tie where its shot table was read; or a comment."""
    from . import lampmap
    ref = lampmap.parse_lamp(rest)
    if ref is None:
        report["lamp unreadable"] += 1
        return "# lamp %s   <- not a lamp line the runtime can read" % rest
    if other_title:
        report["lamp left out"] += 1
        return "# lamp %s   <- another title's insert" % rest
    if "inserts" not in cache:
        try:
            ins, how, _t = lampmap.inserts(lampmap.Elf(target.b, target.path))
            cache["inserts"] = ({i["name"]: i for i in ins}, how)
        except SystemExit as e:
            cache["inserts"] = ({}, str(e))
    by_name, how = cache["inserts"]
    ins = by_name.get(ref[3])
    if ins is None:
        report["lamp missing"] += 1
        return "# lamp %-40s left out: the target names no insert %s (%s)" % (rest.split("#")[0].strip(), ref[3], how)
    if not ins["shot"] and ref[2]:
        ins = dict(ins, shot=ref[2])            # the target's shot table was not read: keep the reference's tie
    report["lamp placed"] += 1
    return lampmap.lamp_line(ins)


# ---- a draft -----------------------------------------------------------------------------------
class Draft:
    """One reference's draft for the target: its port text, what it placed, what it could not."""

    def __init__(self, lines, report, missing_core, placed, how=None):
        self.lines = lines
        self.report = report
        self.missing_core = missing_core
        self.placed = placed          # {("site"|"data"|"scene", name): value}
        self.how = how or {}          # {("site"|"data"|"scene", name): how it was placed}

    @property
    def text(self):
        return "\n".join(self.lines) + "\n"


def apply_recipe(recipe, port_text, target, game=None, version=None, port_name=None, target_name=None,
                 progress=None, cancel=None):
    """The draft of the target's port from one reference's recipe and port text. `target` is an
    :class:`Elf`. `cancel()` returning True stops between entries (raising KeyboardInterrupt's
    cousin, :class:`Stopped`)."""
    tgt = target
    T = Target(tgt, recipe)
    entries = parse_port(port_text)
    port_name = port_name or recipe.get("port", "the reference port")
    out = ["# DRAFTED by port_tool.py from %s" % port_name.replace("\\", "/").split("/")[-1],
           "# target ELF: %s" % (target_name or tgt.path).replace("\\", "/").split("/")[-1],
           "# Every entry says how it was placed. COPIED entries are unverified: prove them in the",
           "# emulator (MODE_SDK.md). Re-run port_words.py on the result before shipping it."]
    report = Counter()
    placed = {}
    hows = {}
    tbound = None
    started = False
    ref_game = target_game = game
    lamp_cache = tgt.__dict__.setdefault("_lamp_cache", {})
    total = max(1, sum(1 for k, _r in entries if k != "#"))
    done = 0
    for key, rest in entries:
        if key == "#":
            # the reference's comments describe the reference build: keep only the section headings
            if started and (rest.startswith("# ----") or not rest.strip()):
                out.append(rest)
            continue
        done += 1
        if cancel is not None and cancel():
            raise Stopped()
        if progress is not None and done % 8 == 0:
            progress(done / total, "")
        started = True
        if key == "game":
            ref_game, target_game = rest, game or rest
            out.append("game           %s" % target_game)
            continue
        if key == "version":
            out.append("version        %s" % (version or rest))
            continue
        parts = rest.split()
        if key == "site":
            name, va = parts[0], int(parts[1], 0)
            rec = recipe["sites"].get(_entry_key(key, parts))
            hook_cands = []
            if rec is None:
                tva, how = None, "the reference's recipe does not cover this line (rebuild the recipe)"
            elif "plt" in rec:
                sym = rec["plt"]
                tva = tgt.plt_by_name.get(sym)
                how = "PLT stub for %s" % sym if tva else "no PLT stub for %s in the target" % sym
            elif "lid" in rec:
                ti, how = T.locate(rec["lid"])
                tva = tgt.va(ti) if ti is not None else None
                how = "located (%s)" % how if tva else how
                if tva is None or how == "located (loose)":
                    # a loose signature can match a sibling of the same shape (Jaws's end of
                    # ball did); the hook a handler is registered for cannot
                    hva, hhow, hook_cands = T.via_hook(rec["hook"])
                    if hva is not None:
                        if tva is not None and tva != hva:
                            hhow += "; a loose signature pointed at 0x%x instead" % tva
                        tva, how = hva, hhow
                    elif hook_cands and tva is not None and tva not in hook_cands:
                        tva, how = None, "a loose signature matched 0x%x, which no handler of its hooks calls; %s" % (tva, hhow)
                    elif hook_cands and tva is None:
                        how = "%s; %s" % (how, hhow)
                if tva is None and not hook_cands:
                    tva, how2 = T.via_callers(rec["callers"])
                    how = how2 if tva else "%s; %s" % (how, how2)
                if tva is None and not hook_cands and "vslot" in rec:
                    tva, how3 = T.via_vslot(rec["vslot"])
                    how = how3 if tva else "%s; %s" % (how, how3)
                if tva is None and not hook_cands and name == "ball_end" and "ball_end" in recipe.get("bus", {}):
                    tva, how4 = T.via_bus(recipe["bus"]["ball_end"], recipe.get("bus_bound", 0))
                    how = how4 if tva else "%s; %s" % (how, how4)
            else:
                tva, how = None, "not in the reference text"
            if tva is None:
                out.append("# site %-16s NOT PLACED: %s" % (name, how))
                for hc in hook_cands:
                    out.append("#   candidate: 0x%x, called by a handler of one of its hooks - drain a ball "
                               "with each hooked and keep the one that fires" % hc)
                if rec and "lid" in rec:
                    for rd, td in T.hints(rec["hints"])[:3]:
                        out.append("#   candidate: the reference %s calls 0x%x, which is 0x%x in the target "
                                   "- prove what it does before using it" % (name, rd, td))
                report["site missing"] += 1
                continue
            if not tgt.in_text(tva) or tgt.word(tva) is None or tgt.word(tva + 4) is None:
                # a caller's branch or a bl can point past the code of an odd program
                out.append("# site %-16s NOT PLACED: 0x%08x is not in the program's code" % (name, tva))
                report["site missing"] += 1
                continue
            if is_hooked_site(name) and not is_hooked_ok(tgt, tva):
                out.append("# site %-16s NOT PLACED: 0x%08x starts pc-relative, cannot be hooked" % (name, tva))
                report["site missing"] += 1
                continue
            out.append("#   %s: %s" % (name, how))
            out.append("site %-16s 0x%08x 0x%08x 0x%08x" % (name, tva, tgt.word(tva), tgt.word(tva + 4)))
            placed[("site", name)] = tva
            hows[("site", name)] = how
            report["site placed"] += 1
        elif key == "data":
            name, va = parts[0], int(parts[1], 0)
            rec = recipe["data"].get(_entry_key(key, parts))
            if rec is None:
                v, how = None, "the reference's recipe does not cover this line (rebuild the recipe)"
            else:
                v, how = T.derive(rec, va)
                if v is None and name in ONE_PLACE_DATA and how.startswith("only 1 place"):
                    v1, how1 = T.derive(rec, va, want=1)
                    if v1 is not None:
                        v, how = v1, "%s; ONE place is enough here: %s" % (how1, ONE_PLACE_DATA[name])
            if v is None:
                out.append("# data %-22s NOT PLACED: %s" % (name, how))
                report["data missing"] += 1
                continue
            out.append("#   %s: %s" % (name, how))
            out.append("data %-22s 0x%08x" % (name, v))
            placed[("data", name)] = v
            hows[("data", name)] = how
            report["data placed"] += 1
        elif key == "scene":
            role, sid = parts[0], parts[1] if len(parts) > 1 else ""
            rec = recipe["scenes"].get(_entry_key(key, parts)) or {"derive": None, "anchors": None}
            tid = None
            if rec["derive"] is not None:
                tv, how = T.derive(rec["derive"], rec.get("sva"), want=1)
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
                placed[("scene", role)] = tid
                hows[("scene", role)] = how
                report["scene derived"] += 1
            elif tgt.b.find(sid.encode() + b"\0") >= 0:
                out.append("#   scene %s: COPIED, unverified (%s; the target program names the same id)" % (role, how))
                out.append("scene %-20s %s" % (role, sid))
                placed[("scene", role)] = sid
                hows[("scene", role)] = "COPIED, unverified (%s; the target program names the same id)" % how
                report["scene copied"] += 1
            else:
                out.append("# scene %-20s NOT PLACED: the target program never names %s (%s)" % (role, sid[:8], how))
                cand, anchor = T.scene_by_neighbours(rec["anchors"]) if rec["anchors"] is not None else (None, None)
                if cand:
                    out.append("#   candidate: %s, the first id after \"%s\" in the target, as in the "
                               "reference - prove it holds this role" % (cand, anchor))
                report["scene missing"] += 1
        elif key == "event":
            # item 147: bus ids are dispatched by shared framework code, but what each id MEANS
            # is measured per build (event_probe.c); a copy is a lead until a mark proves it
            words = rest.split("#", 1)[0].split()
            why = None
            if len(words) >= 3 and words[1] == "site":
                if ("site", words[2]) not in placed:
                    why = "its site %s was not placed" % words[2]
            elif len(words) >= 2:
                if tbound is None:
                    tbound = bus_bound(tgt)
                rbound = recipe.get("bus_bound", 0)
                try:
                    ident = int(words[1], 0)
                except ValueError:
                    ident = -1
                if not tbound or tbound != rbound:
                    why = ("this build's event bus numbers its events differently (its ids end at %d, "
                           "the reference's at %d)" % (tbound, rbound))
                elif not 0 <= ident <= tbound:
                    why = "the id is outside this build's event bus (0..%d)" % tbound
            if why:
                out.append("# event %s   <- left out: %s" % (rest, why))
                report["event left out"] += 1
                continue
            out.append("#   event %s: COPIED, unverified - prove it with event_probe.c (MODE_SDK.md, Events)"
                       % (parts[0] if parts else "?"))
            out.append("event %s" % rest)
            report["event copied"] += 1
        elif key == "lamp":
            out.append(lamp_draft(rest, tgt, title_of(target_game) != title_of(ref_game), report, lamp_cache))
        elif (key in ("shot", "callout", "text", "switch") or (key == "value" and parts and parts[0] in TITLE_VALUES)) \
                and title_of(target_game) != title_of(ref_game):
            # shot bits, switch ids, sound ids, rule ids and example names belong to the reference TITLE
            out.append("# %s %s   <- %s's, not this title's" % (key, rest, ref_game))
            report["%s left out" % key] += 1
        elif key == "value" and _address_value(parts) and tgt.sha1 != recipe.get("elf_sha1"):
            # a value that is an address (a call's return the runtime compares) is the reference
            # build's own: another build, even of the same title, has it elsewhere
            out.append("# %s %s   <- an address in the reference's program, not this one's" % (key, rest))
            report["value left out"] += 1
        elif key in ("value", "shot", "callout", "text"):
            out.append("%s %s" % (key, rest))
            report["%s copied" % key] += 1
        else:
            out.append("%s %s" % (key, rest))
    _score_pair(out, placed, tgt, hows)
    sites = {n for k, n in placed if k == "site"}
    data = {n for k, n in placed if k == "data"}
    return Draft(out, report, core_missing(sites, data), placed, hows)


def _score_pair(out, placed, tgt, hows):
    """Name the scoring pair after the TARGET's score function: a 64-bit reference's score_add
    placed on a build that adds 32-bit scores is its score_add32 (and scores its scores32), and
    the other way round. The runtime calls the two with different arguments."""
    for (site, data), (osite, odata) in ((SCORE_PAIRS[0], SCORE_PAIRS[1]), (SCORE_PAIRS[1], SCORE_PAIRS[0])):
        va = placed.get(("site", site))
        if va is None:
            continue
        width = score_width(tgt, va)
        if width == (32 if site == "score_add32" else 64) or not width:
            return
        for k, line in enumerate(out):
            if line.startswith("site %s " % site):
                out[k] = "site %-16s%s" % (osite, line[len("site ") + 16:])
                out.insert(k, "#   %s: this build's score function multiplies %s, so it adds %d-bit scores: "
                              "the port names it %s" % (osite, "with mul" if width == 32 else "into 64 bits",
                                                        width, osite))
                break
        for k, line in enumerate(out):
            if line.startswith("data %s " % data):
                out[k] = "data %-22s%s" % (odata, line[len("data ") + 22:])
                break
        placed[("site", osite)] = placed.pop(("site", site))
        hows[("site", osite)] = hows.pop(("site", site), "")
        if ("data", data) in placed:
            placed[("data", odata)] = placed.pop(("data", data))
            hows[("data", odata)] = hows.pop(("data", data), "")
        return


def _address_value(parts):
    """Is a `value` line's number an address (a struct offset or a count is small)?"""
    try:
        return len(parts) > 1 and int(parts[1], 0) >= 0x10000
    except ValueError:
        return False


class Stopped(Exception):
    """A draft was asked to stop."""


def draft(ref_elf, port_text, target, game=None, version=None, port_name=None, target_name=None):
    """compile_recipe then apply_recipe: a draft with both programs in hand (port_tool.py)."""
    recipe = compile_recipe(ref_elf, port_text, port_name or "the reference port")
    tgt = target if isinstance(target, Elf) else Elf(target)
    return apply_recipe(recipe, port_text, tgt, game, version, port_name, target_name)


# ---- checking a port against its program (port_words.py) ----------------------------------------
#: sites the runtime hooks (it moves their first two instructions into a trampoline)
HOOKED_SITES = frozenset(HOOKED) | {"roster_start", "clip_play", "display_effect_start", "display_priority_now",
                                     "layered_priority", "layered_waiter"}


def is_hooked_site(name):
    """1 when the runtime hooks a site of this name (:data:`HOOKED_SITES`, and every switch_hit* site:
    switches_arm hooks each one when the port has `switch` lines)."""
    return name in HOOKED_SITES or name.startswith("switch_hit")


def event_problems(n, parts, sites=()):
    """item 147: `event <name> <id>` - a name the runtime keeps (39 characters) and a bus id
    (0..207) - or `event <name> site <site name>`, a site the port names. Returns the problem
    lines."""
    out = []
    if len(parts) < 3:
        return ["line %d: an event needs a name and an id" % n]
    name, rest = parts[1], parts[2].split()
    if len(name) > 39:
        out.append("line %d: the event name %r is over 39 characters" % (n, name))
    if rest and rest[0] == "site":
        if len(rest) < 2 or rest[1].startswith("#"):
            return out + ["line %d: the event %r names no site" % (n, name)]
        if rest[1] not in sites:
            out.append("line %d: the event %r names site %r, which the port has no line for" % (n, name, rest[1]))
        return out
    try:
        ident = int(rest[0], 0)
    except (ValueError, IndexError):
        return out + ["line %d: the event %r has no numeric id" % (n, name)]
    if not 0 <= ident <= 207:
        out.append("line %d: the event %r id %d is outside 0..207" % (n, name, ident))
    return out


def pc_dependent(w):
    if (w & 0x0E000000) == 0x0A000000:                 # b / bl / blx imm
        return True
    if (w >> 26) & 3 == 1 and ((w >> 16) & 0xF) == 15:  # ldr/str based on pc
        return True
    if (w >> 26) & 3 == 0 and (((w >> 16) & 0xF) == 15 or ((w >> 12) & 0xF) == 15):
        return (w & 0x0FB00000) != 0x03000000          # movw/movt carry imm4 there
    if (w & 0x0E108000) == 0x08108000:                 # ldm ... pc
        return True
    return False


def literal_load(w):
    """`ldr rd, [pc, #+-n]` with rd not pc: pad_mode_runtime.c relocates it."""
    return (w & 0xFF7F0000) == 0xE51F0000 and ((w >> 12) & 0xF) != 15


def movable(w0, w1):
    """Can the trampoline run these two words somewhere else? A return (bx lr) can, unless it
    is the function's first and only instruction."""
    if w0 == 0xE12FFF1E:
        return False
    return not any(pc_dependent(w) and not literal_load(w) and (w & 0x0FFFFFFF) != 0x012FFF1E
                   for w in (w0, w1))


def check_port(text, elf):
    """port_words.py's check of a port against its program (an :class:`Elf`): every site's two
    words as the program has them, a hooked site movable, names and values within the runtime's
    buffers, every event readable. The problem lines; empty = good."""
    out = []
    lines = text.splitlines()
    sites = {l.split()[1] for l in lines if l.split()[:1] == ["site"] and len(l.split()) > 1}
    event_sites = {l.split()[3] for l in lines if l.split()[:1] == ["event"] and len(l.split()) > 3
                   and l.split()[2] == "site"}
    for n, line in enumerate(lines, 1):
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        key = parts[0]
        if key in ("site", "data", "value", "callout", "scene", "text") and len(parts[1]) > 39:
            out.append("line %d: the name %r is over 39 characters" % (n, parts[1]))
        if key in ("text", "scene", "shot") and len(parts) == 3 and len(parts[2].strip()) > 159:
            out.append("line %d: the value is over 159 characters" % n)
        if key == "event":
            out.extend(event_problems(n, parts, sites))
        if key == "site":
            f = line.split()
            try:
                va = int(f[2], 0)
                have = [int(x, 0) for x in f[3:5]]
            except (IndexError, ValueError):
                out.append("line %d: a site needs an address and two words" % n)
                continue
            w0, w1 = elf.word(va), elf.word(va + 4)
            if w0 is None or w1 is None or not elf.in_text(va):
                out.append("%s 0x%x is not in the program's code" % (f[1], va))
                continue
            if (is_hooked_site(f[1]) or f[1] in event_sites) and not movable(w0, w1):
                out.append("%s 0x%08x starts %08x %08x - cannot be hooked (pc-relative)" % (f[1], va, w0, w1))
            if have != [w0, w1]:
                out.append("%s 0x%08x: the port says %s, the program has %08x %08x"
                           % (f[1], va, " ".join(f[3:5]) or "(nothing)", w0, w1))
    return out
