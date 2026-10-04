"""PAD-363: what a plain-C (or hand-rolled C++) Spike 2 game program does around its modes' starts - the facts
find_c_starts.py decides on. Read-only, static. Built on the app's stock_scan reader so the logic can move into
game_mode_blocks.py.

A *start* is a function entry the runtime may veto (game_mode_blocks.movable on its first two words). Facts read
per candidate function:

* its TRUE entry: the compiler often schedules a movw/mov before the push, so the nearest push is not always the
  entry; the entry is the earliest address within six words before the push that something refers to (a bl, a b, a
  movw/movt pair, a literal, a data word);
* who reaches it: bl sites, tail branches, code references (a function pointer handed on), data words (tables);
* what it does: the audits it counts (audit_add(id, n), with the tracker's constants), the game flags it sets /
  clears, the processes it creates (create(gid, body, ...)), the live-record ranges it asks about, and every call
  into the framework's ball serving within three calls (multiball_serve: serve until N are in play; a relative
  wrapper that adds N to the balls in play) with its ball count - a multiball serves 2+ / adds 1+;
* whether a caller uses the result (the veto returns r0 = 1).
"""

import collections
import os
import re
import sys

WT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
if WT not in sys.path:
    sys.path.insert(0, WT)

from pinball_decryptor.plugins.stern import stock_scan as S          # noqa: E402
from pinball_decryptor.plugins.stern import stock_scan_c as SC       # noqa: E402
from pinball_decryptor.plugins.stern.game_mode_blocks import movable  # noqa: E402

import numpy as np  # noqa: E402

#: the folder of game programs, one per port: <port key>.elf (title_reader.game_program writes them from a card)
ELVES = os.environ.get("PAD_GAME_PROGRAMS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "elves"))
PORTS = os.path.join(WT, "tools", "spike2_emu", "modes", "sdk", "ports")


# ---- the port ------------------------------------------------------------------------------------------------
def read_port(key):
    """{(kind, name): [fields]} and the raw lines of a port."""
    path = os.path.join(PORTS, key + ".port")
    out, lines = {}, []
    if not os.path.isfile(path):
        return out, lines
    for ln in open(path, encoding="utf-8", errors="replace"):
        lines.append(ln.rstrip("\n"))
        body = ln.split("#", 1)[0].strip()
        if not body:
            continue
        f = body.split()
        if len(f) >= 3 and f[0] in ("site", "data", "value", "text"):
            out[(f[0], f[1])] = f[2:] if f[0] != "text" else [body.split(None, 2)[2]]
    return out, lines


def port_int(port, kind, name):
    v = port.get((kind, name))
    if not v:
        return None
    try:
        return int(v[0], 0)
    except ValueError:
        return None


# ---- the audits -------------------------------------------------------------------------------------------
def audit_ids(p):
    """(names, {engine id: AUD name}) like stock_scan_c.audit_ids, but over EVERY descriptor record whose count is the
    name count, keeping the one that maps the most names (Guardians 1.14 has a second {table, 271, 16} record ahead
    of the real one, whose +0x0a halfwords are not ids)."""
    names = SC.name_array(p, b"AUD_")
    by_index = {i: n for i, n in enumerate(names) if n}
    if not names:
        return names, by_index
    best = {}
    cnt = len(names)
    for off, _va, fsz, _msz, _flg in p.loads:
        base = (off + 3) & ~3
        n = (off + fsz - base) // 4
        if n < 5:
            continue
        w = np.frombuffer(p.b, dtype="<u4", count=n, offset=base)
        for i in np.nonzero((w[2:n - 2] == cnt) & np.isin(w[3:n - 1], (16, 28)))[0].tolist():
            table, elem = int(w[i + 1]), int(w[i + 3])
            if p.va2off(table) is None:
                continue
            idoff = {28: 0x12, 16: 0x0A}[elem]
            got = {}
            for k in range(cnt):
                hid = p.u16(table + k * elem + idoff)
                if hid and names[k]:
                    got.setdefault(hid, names[k])
            if len(got) > len(best):
                best = got
    return names, (best if len(best) >= cnt // 3 else by_index)


# ---- the program -------------------------------------------------------------------------------------------
class Title:
    def __init__(self, key):
        self.key = key
        self.p = S.Program(open(os.path.join(ELVES, key + ".elf"), "rb").read())
        self.port, self.port_lines = read_port(key)
        p = self.p
        p._ensure()
        self._isb = (((p.tw >> 24) & 0xF) == 0xA) & ((p.tw >> 28) != 0xF)
        self._dw = None
        self.names, self.ids = audit_ids(p)
        self.audit_add = SC.find_audit_add(p, self.ids)
        self.aud_id = {n: i for i, n in self.ids.items()}
        self.mb_serve = port_int(self.port, "site", "multiball_serve")
        self.live_records = port_int(self.port, "site", "live_records")
        self.flag_set, self.flag_clear = self._flag_functions()
        self.create = self._process_create()
        self._facts = {}

    # -- data words (tables of function pointers) --
    def data_words(self):
        if self._dw is None:
            p = self.p
            out = []
            blob = p.asset_blob()
            for off, va, fsz, _msz, flg in p.loads:
                base = (off + 3) & ~3
                n = (off + fsz - base) // 4
                if n <= 0:
                    continue
                arr = np.frombuffer(p.b, dtype="<u4", count=n, offset=base)
                vb = va + (base - off)
                if blob and off <= blob[0] < off + fsz:
                    k0, k1 = (blob[0] - base) // 4, (blob[1] - base) // 4
                    out.append((vb, arr[:k0]))
                    if k1 < n:
                        out.append((vb + 4 * k1, arr[k1:]))
                else:
                    out.append((vb, arr))
            self._dw = out
        return self._dw

    def data_refs(self, value):
        """Words equal to *value* outside the code proper (tables, vtables; literal pools inside .text are
        found as code references instead)."""
        out = []
        for vb, arr in self.data_words():
            for i in np.nonzero(arr == value)[0].tolist():
                va = vb + 4 * i
                if self.p.tlo <= va < self.p.code_end:
                    # a word inside .text: a literal pool word is a code reference, found by literal_loads
                    continue
                out.append(va)
        return out

    def tail_branches(self, target):
        p = self.p
        sites = np.nonzero(self._isb & (p._tgt == target))[0]
        return [p.tlo + 4 * int(i) for i in sites]

    def refs(self, f):
        """{"bl": [...], "b": [...], "code": [...], "data": [...]} - every way the program reaches *f*."""
        p = self.p
        return {"bl": p.callers(f), "b": self.tail_branches(f), "code": p.references(f), "data": self.data_refs(f)}

    def nrefs(self, f):
        r = self.refs(f)
        return sum(len(v) for v in r.values())

    def entry(self, va):
        """The true entry of the function holding *va*: the nearest push at or before it, or an earlier word (within
        six) that something refers to while every word in between flows on."""
        p = self.p
        f = p.func_start(va)
        if f != va and va - f > 24 and (p.callers(va) or self.data_refs(va)) and not self.nrefs(f):
            return va                       # referenced itself, its push a few words in (ldr r3, [r0]; push ...)
        best = f
        for k in range(1, 7):
            e = f - 4 * k
            w = p.word(e)
            if w is None:
                break
            d = S.decode(w, e)
            if S.ends_flow(d) or d[0] in ("poppc", "bxlr") or (w & 0x0E000000) == 0x0A000000 and d[-1] == 0xE:
                break
            if p.literal_loads(e):          # a literal pool word, not code
                break
            if self.nrefs(e):
                best = e
        return best

    # -- engine functions --
    def _flag_functions(self):
        """(set, clear) of the framework's game flags: the functions that index the bitmap whose holder the port names
        (`data game_flags`, the bitmap pointer at holder + game_flags_at): of the functions referring to the holder
        and called with constant flag ids, the one that ORs a bit in is set, the one that BICs is clear."""
        holder = port_int(self.port, "data", "game_flags")
        if holder is None:
            return None, None
        p = self.p
        fs = set()
        for x in p.references(holder):
            # a leaf function has no push: the nearest bl target at or before the reference starts it
            k = int(np.searchsorted(p._bl_tgt, x, "right")) - 1
            tgt = int(p._bl_tgt[k]) if k >= 0 else None
            fs.add(tgt if tgt is not None and x - tgt < 96 else p.func_start(x))
        fs = sorted(fs)
        sets, clears = [], []
        for f in fs:
            n, tot = S.constant_callers(p, f, 0, lambda v: v < 4096)
            if n < 5:
                continue
            end, lits = S.function_extent(p, f)
            body = [p.word(v) for v in range(f, min(end, f + 160), 4) if v not in lits]
            orr = any((w & 0x0FE00000) == 0x01800000 for w in body if w is not None)    # orr reg
            bic = any((w & 0x0FE00000) == 0x01C00000 for w in body if w is not None)    # bic reg
            if orr and not bic:
                sets.append((n, f))
            elif bic and not orr:
                clears.append((n, f))
        return (max(sets)[1] if sets else None), (max(clears)[1] if clears else None)

    def _process_create(self):
        """The framework's create-a-process(gid, body, ...): the callee most often handed a small constant gid in r0 and
        a code address (the body) in r1."""
        p = self.p
        _s, tgts, v0 = p.call_constants(0)
        sites, _t, _v = p.call_constants(1)
        cnt = collections.Counter()
        w = p.tw
        for k, (site, tgt) in enumerate(zip(sites.tolist(), tgts.tolist())):
            if not (0 <= v0[k] < 1024):
                continue
            # r1 made by movw/movt within 6 before the call
            va = p.tlo + 4 * site
            v = p.const_before(va, 1)
            if v is not None and p.in_text(v):
                cnt[tgt] += 1
        if not cnt:
            return None
        return cnt.most_common(1)[0][0]

    # -- facts of one function --
    def facts(self, f):
        got = self._facts.get(f)
        if got is not None:
            return got
        p = self.p
        t = track_entry(p, f)
        fx = {"entry": f, "words": (p.word(f), p.word(f + 4)), "end": t.end}
        fx["movable"] = movable(fx["words"])
        fx["refs"] = self.refs(f)
        aud, fset, fclr, made, live, calls = [], [], [], [], [], []
        for c in t.calls:
            a = c["args"]
            tgt = c["target"]
            v0, v1, v2 = (a.get(k).v if isinstance(a.get(k), S.Val) else None for k in ("r0", "r1", "r2"))
            calls.append(tgt)
            if tgt == self.audit_add:
                aud.append((c["va"], v0, self.ids.get(v0) if v0 is not None else None))
            elif self.flag_set and tgt == self.flag_set:
                fset.append((c["va"], v0))
            elif self.flag_clear and tgt == self.flag_clear:
                fclr.append((c["va"], v0))
            elif self.create and tgt == self.create:
                made.append((c["va"], v0, v1))
            elif self.live_records and tgt == self.live_records:
                live.append((c["va"], v0, v1))
        fx.update(audits=aud, flags_set=fset, flags_clear=fclr, creates=made, live=live, calls=calls)
        fx["balls"] = ball_evidence(self, f)
        fx["mb"] = serves_balls(fx["balls"])
        self._facts[f] = fx
        return fx

    def callees(self, f):
        p = self.p
        out = set()
        for c in track_entry(p, f).calls:
            out.add(c["target"])
            if self.create and c["target"] == self.create:      # a process body it creates runs as its callee
                v = c["args"].get("r1")
                if isinstance(v, S.Val) and p.in_text(v.v) and v.v != f:
                    out.add(v.v)
        return out

    def reaches(self, f, targets, depth=3, _seen=None):
        """A call path [f, ..., target] to one of *targets* within *depth* calls (process bodies handed to a call
        count as calls), or None."""
        _seen = set() if _seen is None else _seen
        if f in targets:
            return [f]
        if depth == 0 or f in _seen:
            return None
        _seen.add(f)
        for c in sorted(self.callees(f)):
            got = self.reaches(c, targets, depth - 1, _seen)
            if got:
                return [f] + got
        return None

    # -- the mode audits --
    def mode_audits(self):
        return SC.mode_audits(self.names)

    def count_sites(self):
        """{audit id: [call VA]} of every audit_add with a constant id."""
        out = collections.defaultdict(list)
        if not self.audit_add:
            return out
        for c in self.p.callers(self.audit_add):
            v = self.p.const_before(c, 0)
            if v is not None:
                out[v].append(c)
        return out


def hx(v):
    return "0x%x" % v


def fmt_refs(t, r, cap=4):
    out = []
    p = t.p
    for k in ("bl", "b", "code", "data"):
        for x in r[k][:cap]:
            out.append("%s 0x%x%s" % (k, x, "" if k == "data" else " (fn 0x%x)" % t.entry(x)))
        if len(r[k]) > cap:
            out.append("+%d more %s" % (len(r[k]) - cap, k))
    return "; ".join(out) if out else "none"


def is_multiball_name(name):
    u = name.upper().replace(" ", "_")
    return bool(re.search(r"MULTIBALL|(^|_)MB(_|$)|MBALL|(^|_)TRIBALL", u))


def return_used(p, site, n=6):
    """Whether the code after the call at *site* reads r0 (the callee's result) before writing it: a cmp/tst, a move,
    a store or an argument of a tail call. A tail branch (b) is a tail call: its caller's caller sees the result."""
    w = p.word(site)
    d = S.decode(w, site)
    if d[0] == "b":
        return "tail"
    for k in range(1, n + 1):
        va = site + 4 * k
        rw = S._regs_at(p, va)
        if rw is None:
            return None
        reads, writes = rw
        dd = S.decode(p.word(va), va)
        if 0 in reads:
            return "0x%x" % va
        if dd[0] in ("bl", "blx"):
            return False
        if dd[0] in ("poppc", "bxlr"):
            return "returned"      # the caller returns the result on to its own caller
        if 0 in writes:
            return False
        if S.ends_flow(dd):
            return None
    return False


_TRACKED = {}


def extent(p, entry):
    """(end, literal pools) of the function entered at *entry*: when its push comes a few words in (the compiler put
    a movw or a vptr load first), the push's extent - stock_scan.function_extent stops AT a push after the start."""
    for k in range(0, 7):
        w = p.word(entry + 4 * k)
        if w is None:
            break
        d = S.decode(w, entry + 4 * k)
        if d[0] == "pushlr":
            if k == 0:
                return S.function_extent(p, entry)
            return S.function_extent(p, entry + 4 * k)
        if S.ends_flow(d):
            break
    return S.function_extent(p, entry)


def track_entry(p, entry):
    """stock_scan.track over the function entered at *entry*, with :func:`extent`'s end (cached per program)."""
    cache = p.__dict__.setdefault("_pad363_tracked", {})     # per program: id() of a freed program is reused
    got = cache.get(entry)
    if got is not None:
        return got
    end, lits = extent(p, entry)
    orig = S.function_extent

    def fe(prog, start, cap=6000):
        return (end, lits) if start == entry and prog is p else orig(prog, start, cap)
    S.function_extent = fe
    try:
        got = S.track(p, entry)
    finally:
        S.function_extent = orig
    cache[entry] = got
    return got


def audit_functions(t):
    """{audit id: [function entry]} over every caller of audit_add, with the tracker's constants (a movw made
    far ahead of the call counts too, unlike Program.const_before)."""
    if getattr(t, "_afun", None) is not None:
        return t._afun
    out = collections.defaultdict(list)
    seen = set()
    for c in t.p.callers(t.audit_add) if t.audit_add else ():
        f = t.entry(c)
        if f in seen:
            continue
        seen.add(f)
        for _va, v0, _nm in t.facts(f)["audits"]:
            if v0 is not None and f not in out[v0]:
                out[v0].append(f)
    t._afun = out
    return out


def relative_wrappers(t):
    """Functions that serve balls RELATIVE to the balls in play: they call balls_in_play and then the framework's
    multiball_serve (Metallica 1.03 0x36ad44: serve(r0 + in play)), so r0 = the number of balls ADDED."""
    if getattr(t, "_relw", None) is not None:
        return t._relw
    out = set()
    bip = port_int(t.port, "site", "balls_in_play")
    if t.mb_serve and bip:
        for site in t.p.callers(bip):
            g = t.entry(site)
            for c in track_entry(t.p, g).calls:
                if c["target"] == t.mb_serve and not isinstance(c["args"].get("r0"), S.Val)                         and any(c2["target"] == bip and c2["va"] < c["va"] for c2 in track_entry(t.p, g).calls):
                    out.add(g)
    t._relw = out
    return out


def ball_evidence(t, f, depth=3):
    """[(path, kind, balls)] - every call into the framework's ball serving within *depth* calls of *f* (process
    bodies handed on count): kind "serve" (multiball_serve: serve until *balls* are in play) or "add" (a relative
    wrapper: add *balls*); balls None when not a constant."""
    if not t.mb_serve:
        return []
    rel = relative_wrappers(t)
    out, seen = [], set()

    def walk(g, path, d):
        if g in seen or d < 0:
            return
        seen.add(g)
        for c in track_entry(t.p, g).calls:
            tgt = c["target"]
            if tgt == t.mb_serve or tgt in rel:
                v = c["args"].get("r0")
                out.append((path + [g, tgt], "serve" if tgt == t.mb_serve else "add",
                            v.v if isinstance(v, S.Val) else None))
        if d == 0:
            return
        for nxt in sorted(t.callees(g)):
            if nxt != t.mb_serve and nxt not in rel:
                walk(nxt, path + [g], d - 1)
    walk(f, [], depth)
    return out


def serves_balls(ev):
    """Whether ball evidence means a multiball: an absolute serve of 2+ (or unknown), or an add of 1+ (or unknown)."""
    for _path, kind, n in ev:
        if n is None or (kind == "serve" and n >= 2) or (kind == "add" and n >= 1):
            return True
    return False


def immediate_sites(t, value):
    """VAs of every mov/movw rX, #value (an id built as an immediate anywhere in the code)."""
    p = t.p
    w = p.tw
    movw = np.nonzero(((w & 0x0FF00000) == 0x03000000) & ((((w >> 4) & 0xF000) | (w & 0xFFF)) == value))[0]
    out = [p.tlo + 4 * int(i) for i in movw]
    if value < 256:
        mov = np.nonzero(((w & 0x0FEF0F00) == 0x03A00000) & ((w & 0xFF) == value))[0]
        out += [p.tlo + 4 * int(i) for i in mov]
    return sorted(out)
