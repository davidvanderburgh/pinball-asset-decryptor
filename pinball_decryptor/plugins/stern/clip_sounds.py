"""Which SOUNDS the game plays with each in-game clip, read off the game program (a prototype).

A Spike 2 card stores no link between a clip and a sound: Extract names a clip after the scene
element that references it and a sound after its master-directory record (``idxNNNN``). The link
is in the game's code. The code asks for a clip by NAME (:mod:`.clip_modes`) and for a sound by
REQUEST id, a constant argument to one of a handful of sound functions (``sound_request_play``,
``callout`` and their ``_nth`` twins: ``tools/spike2_emu/modes/MODE_API.md``). So the sounds that
go with a clip are the requests that the code naming the clip asks for. This module reads that
join statically:

* the SOUND ENTRIES (:func:`sound_entries`): every function that hands one of its own arguments
  on as the request a sound plays. Seeded from the build's port (``sound_worker``,
  ``sound_play``, ``sound_nth``, ``callout``, ``callout_nth``) when there is one, else from the
  functions that load the request table's address (:func:`table_readers`). Then every function
  that passes one of its arguments on to an entry on some path (:func:`_flow`), close to its
  start (:data:`WRAPPER_MAX`), and whose callers' constants there are request ids
  (:data:`IN_RANGE`);
* every CALL of an entry with a constant request (:func:`sound_calls`);
* each clip's references (:func:`.clip_modes.clip_refs`) beside the calls (:func:`pair`), best
  first: ``next`` - the call is in the function that names the clip, and this clip's name is the
  one nearest the call there, within :data:`NEAR` instructions; ``function`` - the call is in
  that function, nearer another clip's name; ``table`` - the clip is a pointer in a table and the
  call is in code that loads the table; ``mode`` - only the same mode's code makes the call.

A request is named by the Sound Test (the menu's node id IS the request id, MODE_API.md item 150:
:func:`menu_names`) and, once Extract has written :data:`REQUESTS_TSV`, by the ``idx`` records
its sound ids resolve to (:func:`resolve_requests`, driven on the codec emulator the extract
boots anyway).

NOT FOUND, by design: a request the code computes (a table of callouts, a random pick), a sound
played by a function the clip's code calls rather than by that code itself, a request queued for
later (``play_delayed`` stores it; the tick plays it), and a clip's own audio track (7 of
Deadpool's 99 clips carry one). Nothing here is emulator-proven yet: a reading says how it found
the sound functions (:attr:`SoundReading.origin`, :attr:`SoundReading.entries`) so it can be
checked against a port and a sound census (``sdk/sound_census.c``).
"""
from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field

#: bumped when what :func:`analyse` reads changes (a cached :class:`.clip_modes.CardClips` is
#: read again)
READ_REV = 1
#: the port sites that play a sound by request, its id in r0 (MODE_API.md)
SOUND_SITES = ("sound_worker", "sound_play", "sound_nth", "callout", "callout_nth")
#: how many wrappers deep the entries are followed past the seeds: a port names the game's own
#: sound functions, so one or two more (a title's helpers) are left; from the request table it
#: takes the worker -> sound_request_play -> callout chain
DEPTH_PORT = 2
DEPTH_LOCATED = 3
#: a wrapper hands its argument on within this many instructions of its start
WRAPPER_MAX = 200
#: of a wrapper's callers with a constant in the request's register, how many must be a request id
IN_RANGE = 0.9
#: a call this many instructions from a clip's name, nearer it than any other clip's, is ``next``
NEAR = 48
#: passes of the per-function argument flow before it gives up on a fixed point
FLOW_PASSES = 16
#: how far back from a table's pointer the table's start is looked for (words)
TABLE_BACK = 256
HOWS = ("next", "function", "table", "mode")
_RANK = {h: i for i, h in enumerate(HOWS)}
#: Extract's sidecar: every request, the ``idx`` records it plays, its sound ids and Sound Test name
REQUESTS_TSV = "sound_requests.tsv"
_IDX_RE = re.compile(r"\bidx(\d{4,})\b")


# ---- the request table -----------------------------------------------------------------------
def request_table(raw, fragments):
    """``(count, [[sid, ...] per request], table VA, registry VA)`` of the game program *raw*,
    or ``(0, [], None, None)``. *fragments* is ``image.bin``'s fragment count
    (:func:`..info.container_counts`), which :func:`.spike2.sound_requests.locate_sound_requests`
    needs to tell the table from its look-alikes. The registry VA is where the build's
    ``{data_va, count, 20}`` triple for the table sits (None when it is not found)."""
    from .spike2.elf import parse_elf
    from .spike2.sound_requests import locate_sound_requests
    count, table = locate_sound_requests(raw, fragments)
    if not count:
        return 0, [], None, None
    segs, _r = parse_elf(raw)

    def off2va(o):
        for vaddr, foff, fsz, _m in segs:
            if foff <= o < foff + fsz:
                return vaddr + o - foff
        return None

    def va2off(va):
        for vaddr, foff, fsz, _m in segs:
            if vaddr <= va < vaddr + fsz:
                return foff + va - vaddr
        return None

    end = table + count * 20
    lists = []
    for req in range(count):
        sids = []
        # the sid list is the field that points past the record array (sound_requests.py)
        for w in struct.unpack_from("<5I", raw, table + req * 20):
            o = va2off(w) if w else None
            if o is None or o < end:
                continue
            for i in range(256):
                if o + 4 * i + 4 > len(raw):
                    break
                s = struct.unpack_from("<I", raw, o + 4 * i)[0]
                if s == 0:
                    break
                sids.append(s)
            break
        lists.append(sids)
    tva = off2va(table)
    reg = None
    key = struct.pack("<III", tva, count, 20)
    o = raw.find(key)
    while o >= 0:
        if o % 4 == 0:
            reg = off2va(o)
            break
        o = raw.find(key, o + 1)
    return count, lists, tva, reg


def menu_names(raw, lists):
    """``{request: Sound Test name}``: the menu's node id is the request id; a name is kept only
    where the menu's sid list is the request's own, list for list (``sound_map.py``)."""
    from .spike2 import sfx_names as SN
    t = SN._walk_menu_table(raw)
    if t is None:
        return {}
    ml, nl = t["lists"], len(t["lists"])
    out = {}
    for p, name in enumerate(t["names"]):
        if not SN._is_sound_entry(name):
            continue
        nid = t["node_ids"].get(p)
        if nid is None or not 0 <= nid < len(lists):
            continue
        li = (nl - 1) - nid
        if 0 <= li < nl and ml[li] == lists[nid]:
            out[nid] = name.strip()
    return out


# ---- where the sound functions are -----------------------------------------------------------
def port_seeds(prog, game, version):
    """``({VA: name}, port path)``: the build's port's sound sites whose two instruction words
    are this program's (a port made on another build names nothing here)."""
    try:
        from . import mode_runtime as MR
        path = MR.port_file(game, version)
    except Exception:                                       # noqa: BLE001 - no port, no seeds
        path = None
    seeds = {}
    if not path:
        return seeds, ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return seeds, ""
    for line in lines:
        p = line.split()
        if len(p) < 5 or p[0] != "site" or p[1] not in SOUND_SITES:
            continue
        try:
            va, w0, w1 = int(p[2], 0), int(p[3], 0), int(p[4], 0)
        except ValueError:
            continue
        if prog.in_text(va) and prog.word(va) == w0 and prog.word(va + 4) == w1:
            seeds[va] = seeds[va] + "/" + p[1] if va in seeds else p[1]
    return seeds, path


def table_readers(prog, table_va, registry_va=None):
    """``{function VA: "request table"}``: the functions whose code makes the request table's
    address (a field of it, or its registry triple's), the sound worker among them."""
    vals = {table_va + 4 * k for k in range(5)}
    if registry_va is not None:
        vals |= {registry_va + 4 * k for k in range(3)}
    out = {}
    for v in sorted(vals):
        for site in prog.references(v):
            if prog.in_text(site):
                out.setdefault(_start_of(prog, site), "request table")
    return out


def _start_of(prog, va):
    """The start of the function holding *va*: the nearer of the last ``push {..., lr}`` and the
    last ``bl`` target at or before it (a leaf wrapper such as ``sound_request_play`` pushes
    nothing)."""
    import numpy as np
    prog._ensure()
    a = prog.func_start(va)
    k = int(np.searchsorted(prog._bl_tgt, va, "right")) - 1
    b = int(prog._bl_tgt[k]) if k >= 0 else 0
    return b if a < b <= va and prog.in_text(b) else a


class _Calls:
    """Every ``bl`` and leaving ``b`` to a function, indexed once."""

    def __init__(self, prog):
        import numpy as np
        prog._ensure()
        w = prog.tw
        isb = ((w & 0x0F000000) == 0x0A000000) & ((w >> 28) != 0xF)
        sites = np.nonzero(isb)[0]
        tg = prog._tgt[sites]
        order = np.argsort(tg, kind="stable")
        self.prog, self.np = prog, np
        self._b_tgt, self._b_site = tg[order], sites[order]

    def to(self, target):
        """VAs of every call of *target*: its ``bl`` sites, and the ``b`` sites outside it."""
        prog, np = self.prog, self.np
        out = list(prog.callers(target))
        lo = np.searchsorted(self._b_tgt, target, "left")
        hi = np.searchsorted(self._b_tgt, target, "right")
        for i in self._b_site[lo:hi].tolist():
            site = prog.tlo + 4 * i
            if _start_of(prog, site) != target:
                out.append(site)
        return sorted(out)


# ---- which argument a function hands on --------------------------------------------------------
_EMPTY = frozenset()
_EXTEND = {0x6A, 0x6B, 0x6E, 0x6F}          # sxtb sxth uxtb uxth


def _move_of(w, d):
    """``(rd, rm)`` when the instruction copies a register into another (mov, a shift by an
    immediate, an add or sub of 0, a zero or sign extension), else None. A request id is a u16
    (a channel holds it at +184), so the copies a compiler makes of one are these."""
    if d[0] == "movr":
        return d[1], d[2]
    if d[0] in ("addi", "subi") and d[3] == 0 and d[2] != 15:
        return d[1], d[2]
    if d[0] == "other" and w is not None:
        if (w & 0x0FEF0010) == 0x01A00000:                   # mov rd, rm, <shift> #imm
            return (w >> 12) & 0xF, w & 0xF
        if (w >> 20) & 0xFF in _EXTEND and (w >> 16) & 0xF == 0xF and (w & 0xFF0) == 0x070:
            return (w >> 12) & 0xF, w & 0xF
    return None


def _step(st, w, d):
    """The state after one instruction: ``{register or ("sp", offset): the entry arguments it
    may hold}``. A conditional write keeps what was there too (the other path)."""
    kind, cond = d[0], d[-1] != 0xE
    new = dict(st)

    def put(k, v):
        if cond:
            v = v | st.get(k, _EMPTY)
        if v:
            new[k] = v
        else:
            new.pop(k, None)

    mv = _move_of(w, d)
    if mv is not None:
        put(mv[0], st.get(mv[1], _EMPTY))
    elif kind == "stri" and d[2] == 13:
        put(("sp", d[3]), st.get(d[1], _EMPTY))
    elif kind == "ldri" and d[2] == 13:
        put(d[1], st.get(("sp", d[3]), _EMPTY))
    elif kind in ("bl", "blx"):
        if not cond:
            for r in (0, 1, 2, 3, 12, 14):
                new.pop(r, None)
    elif kind in ("movw", "movt", "mov", "mvn", "ldrlit", "andsi", "addi", "subi", "ldri"):
        put(d[1], _EMPTY)
    elif kind == "strd" and d[4]:
        put(d[2], _EMPTY)
    elif kind == "other":
        for r in d[1]:
            put(r, _EMPTY)
    return new


def _join(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, _EMPTY) | v
    return out


def _flow(prog, start, upto=None):
    """``{call VA: {r0..r3: the function's own arguments (0..3) the register may hold there}}``
    for every call (``bl``, ``blx``, a ``b`` that leaves) in the function at *start*, read no
    further than *upto*. A MAY reading: a value one path changes and another does not is still
    the argument, so ``callout``'s swap of an English request for its Japanese sibling, on one
    path, still hands the request on."""
    from . import stock_scan as S
    end, lits = S.function_extent(prog, start)
    stop = end if upto is None else min(end, upto + 4)
    vas = [va for va in range(start, stop, 4) if va not in lits]
    ins, succ, leaves = {}, {}, set()
    for i, va in enumerate(vas):
        w = prog.word(va)
        d = S.decode(w, va)
        ins[va] = (w, d)
        inside = d[0] == "b" and start <= d[1] < end and not (
            d[-1] == 0xE and S.tail_branch(prog, start, va, d[1]))
        nxt = []
        if not S.ends_flow(d) and i + 1 < len(vas):
            nxt.append(vas[i + 1])
        if inside:
            nxt.append(d[1])
        succ[va] = nxt
        if d[0] in ("bl", "blx") or (d[0] == "b" and not inside):
            leaves.add(va)
    state = {start: {r: frozenset((r,)) for r in range(4)}}
    calls = {}
    for _n in range(FLOW_PASSES):
        changed = False
        for va in vas:
            st = state.get(va)
            if st is None:
                continue
            w, d = ins[va]
            if va in leaves:
                calls[va] = {r: st.get(r, _EMPTY) for r in range(4)}
            out = _step(st, w, d)
            for n in succ[va]:
                cur = state.get(n)
                new = out if cur is None else _join(cur, out)
                if new != cur:
                    state[n] = new
                    changed = True
        if not changed:
            break
    return calls


def _const(prog, site, reg):
    """The constant in *reg* at the call *site*, or None: the few instructions before it, then
    the function's own tracker (:func:`.stock_scan.track`) for one made further back."""
    from . import stock_scan as S
    n = min(12, (site - _start_of(prog, site)) // 4)       # never into the function before
    v = prog.const_before(site, reg, n=n) if n > 0 else None
    if v is not None:
        return v
    try:
        facts = prog.facts(prog.func_start(site))
    except Exception:                                       # noqa: BLE001 - unreadable: unknown
        return None
    for c in facts.calls:
        if c["va"] == site:
            a = c["args"].get(S.REG[reg])
            return a.v if isinstance(a, S.Val) else None
    return None


# ---- the sound entries and their calls ---------------------------------------------------------
@dataclass
class Entry:
    """A function that plays the sound request in one of its argument registers."""
    name: str                 # the port's name for it, or how it was found
    reg: int = 0              # the register the request is in
    sites: int = 0            # its calls
    const: int = 0            # ... with a constant in that register
    requests: int = 0         # ... that is a request id

    def plausible(self):
        return not self.const or self.requests >= IN_RANGE * self.const

    def to_json(self):
        return [self.name, self.reg, self.sites, self.const, self.requests]


def _tally(prog, calls, va, entry, count):
    sites = calls.to(va)
    vals = [_const(prog, s, entry.reg) for s in sites]
    vals = [v for v in vals if v is not None]
    entry.sites, entry.const = len(sites), len(vals)
    entry.requests = sum(1 for v in vals if 0 <= v < count)
    return entry


def sound_entries(prog, seeds, count, depth=DEPTH_PORT, trust=True):
    """``{function VA: Entry}``: the *seeds* (``{VA: name}``, each taking its request in r0;
    kept as they are when *trust*, else only when their callers' constants look like requests),
    and every function that hands one of its arguments on to an entry, *depth* wrappers deep."""
    calls = _Calls(prog)
    flows = {}
    entries = {}
    for va, name in seeds.items():
        e = _tally(prog, calls, va, Entry(name, 0), count)
        if trust or e.plausible():
            entries[va] = e
    frontier = list(entries)
    for _d in range(depth):
        cand = {}
        for va in frontier:
            k = entries[va].reg
            for site in calls.to(va):
                f = _start_of(prog, site)
                if f in entries or f in cand or site - f > 4 * WRAPPER_MAX:
                    continue
                n = min(12, (site - f) // 4)
                if n > 0 and prog.const_before(site, k, n=n) is not None:
                    continue                    # game code asking for one sound: no wrapper
                if f not in flows:
                    try:
                        flows[f] = _flow(prog, f, upto=f + 4 * WRAPPER_MAX)
                    except Exception:                       # noqa: BLE001 - unreadable code
                        flows[f] = {}
                args = (flows[f].get(site) or {}).get(k, _EMPTY)
                if len(args) == 1:
                    cand[f] = Entry("0x%x > %s" % (f, entries[va].name.split(" > ")[-1]),
                                    next(iter(args)))
        new = {}
        for f, e in cand.items():
            _tally(prog, calls, f, e, count)
            if e.plausible():
                new[f] = e
        entries.update(new)
        frontier = list(new)
        if not frontier:
            break
    return entries


@dataclass
class Call:
    """One place the game asks for a sound by a constant request."""
    at: int                   # VA of the call
    fn: int                   # the function it is in
    request: int
    entry: str                # the sound function it calls


def sound_calls(prog, entries, count):
    """Every :class:`Call` of an entry with a constant request id, in address order."""
    calls = _Calls(prog)
    out = []
    for va, e in entries.items():
        for site in calls.to(va):
            v = _const(prog, site, e.reg)
            if v is not None and 0 <= v < count:
                out.append(Call(site, _start_of(prog, site), v, e.name))
    out.sort(key=lambda c: (c.at, c.request))
    return out


# ---- a clip's places and its sounds ------------------------------------------------------------
class _Tables:
    """The code that loads the table holding a pointer: walk back from the pointer to the
    nearest word whose address the code makes (``clip_modes._Owners.of_table``'s walk), with
    the program's referenced values gathered once so the walk is set lookups."""

    def __init__(self, prog):
        import numpy as np
        self.prog = prog
        made = set(np.unique(prog.tw).tolist())
        for reg in range(13):
            made.update(prog.movwt_values(reg))
        self.made = made
        self._got = {}

    def loaders(self, wva):
        got = self._got.get(wva)
        if got is not None:
            return got
        got = []
        for k in range(TABLE_BACK):
            v = wva - 4 * k
            if v in self.made:
                got = [r for r in self.prog.references(v) if self.prog.in_text(r)]
                if got:
                    break
        self._got[wva] = got
        return got


def _places(prog, ref, tables):
    """``[(function VA, VA of the instruction naming the clip, or None)]`` for one
    :class:`.clip_modes.Ref`: the ``movw`` of a pair, the ``ldr`` of a literal, or (None) each
    function that loads the table the clip's pointer is in."""
    from . import progreloc
    if ref.kind in (progreloc.KIND_A32, progreloc.KIND_T32):
        return [(_start_of(prog, ref.at), ref.at)]
    if prog.in_text(ref.at):
        loads = prog.literal_loads(ref.at)
        if loads:
            return [(_start_of(prog, v), v) for v in loads]
        return [(_start_of(prog, ref.at), None)]
    return [(_start_of(prog, r), None) for r in tables.loaders(ref.at)]


def _nearest(at, places):
    """The clip of *places* (``[(VA, clip)]``, one function's) a call at *at* goes with: the
    last one named before the call within :data:`NEAR` instructions, else the first one named
    after it within that. Before wins because the code that plays a clip then its sound names
    the NEXT clip right after the sound (``clip("A"); callout(3); clip("B")``: 3 is A's, though
    B's name is the nearer)."""
    before = [p for p in places if at - 4 * NEAR <= p[0] <= at]
    if before:
        return max(before, key=lambda p: (p[0], p[1]))[1]
    after = [p for p in places if at < p[0] <= at + 4 * NEAR]
    if after:
        return min(after, key=lambda p: (p[0], p[1]))[1]
    return None


def pair(prog, refs, calls, owners=None):
    """``{clip name: [[request, how, gap, call VA], ...]}``, best first (:data:`HOWS`; *gap* in
    instructions, -1 where there is none). *refs* is :func:`.clip_modes.clip_refs`' reading,
    *calls* :func:`sound_calls`'; *owners* (a :class:`.clip_modes._Owners`) adds ``mode``."""
    by_fn = {}
    for c in calls:
        by_fn.setdefault(c.fn, []).append(c)
    tables = None
    places, fn_places = {}, {}
    for clip, rs in refs.items():
        pl = []
        for r in rs:
            if tables is None and r.kind not in ("movw_a32", "movw_t32") \
                    and not prog.in_text(r.at):
                tables = _Tables(prog)
            for fn, va in _places(prog, r, tables):
                pl.append((fn, va))
                if va is not None:
                    fn_places.setdefault(fn, []).append((va, clip))
        places[clip] = pl
    nearest = {}
    for fn, cs in by_fn.items():
        ps = fn_places.get(fn)
        if not ps:
            continue
        for c in cs:
            got = _nearest(c.at, ps)
            if got is not None:
                nearest[c.at] = got
    by_mode = {}
    if owners is not None:
        for c in calls:
            m = owners.of_code(c.at)[0]
            if m:
                by_mode.setdefault(m, []).append(c)
    out = {}
    for clip, pl in places.items():
        got = {}

        def keep(c, how, gap):
            cur = got.get(c.request)
            key = (_RANK[how], gap if gap >= 0 else 1 << 30)
            if cur is None or key < (_RANK[cur[1]], cur[2] if cur[2] >= 0 else 1 << 30):
                got[c.request] = [c.request, how, gap, c.at]

        for fn, va in pl:
            for c in by_fn.get(fn, ()):
                if va is None:
                    keep(c, "table", -1)
                else:
                    keep(c, "next" if nearest.get(c.at) == clip else "function",
                         abs(c.at - va) // 4)
        for m in sorted({r.mode for r in refs[clip] if r.mode}):
            for c in by_mode.get(m, ()):
                if c.request not in got:
                    got[c.request] = [c.request, "mode", -1, c.at]
        if got:
            out[clip] = sorted(got.values(), key=lambda p: (
                _RANK[p[1]], p[2] if p[2] >= 0 else 1 << 30, p[0]))
    return out


# ---- the reading -------------------------------------------------------------------------------
@dataclass
class SoundReading:
    """What :func:`analyse` read: each clip's sounds, and how the sound functions were found."""
    origin: str = ""          # "port" (the build's port named them), "located", "" (not found)
    port: str = ""            # the port file, for "port"
    count: int = 0            # the build's sound requests
    entries: dict = field(default_factory=dict)   # function VA -> Entry.to_json()
    calls: int = 0            # calls with a constant request
    pairs: dict = field(default_factory=dict)     # clip -> [[request, how, gap, call VA]]
    names: dict = field(default_factory=dict)     # request -> Sound Test name (paired ones)
    sids: dict = field(default_factory=dict)      # request -> [sid] (paired ones)
    note: str = ""            # why there is nothing, in words

    def sounds_of(self, clip):
        """``[{request, how, gap, at, name, sids}]`` for *clip*, best first."""
        return [{"request": r, "how": how, "gap": gap, "at": at,
                 "name": self.names.get(r, ""), "sids": list(self.sids.get(r, ()))}
                for r, how, gap, at in self.pairs.get(clip, ())]

    def to_json(self):
        return {"rev": READ_REV, "origin": self.origin, "port": self.port, "count": self.count,
                "entries": {"%d" % k: v for k, v in self.entries.items()}, "calls": self.calls,
                "pairs": self.pairs, "names": {"%d" % k: v for k, v in self.names.items()},
                "sids": {"%d" % k: v for k, v in self.sids.items()}, "note": self.note}

    @classmethod
    def from_json(cls, d):
        d = d or {}
        return cls(d.get("origin", ""), d.get("port", ""), int(d.get("count") or 0),
                   {int(k): list(v) for k, v in (d.get("entries") or {}).items()},
                   int(d.get("calls") or 0),
                   {k: [list(p) for p in v] for k, v in (d.get("pairs") or {}).items()},
                   {int(k): v for k, v in (d.get("names") or {}).items()},
                   {int(k): list(v) for k, v in (d.get("sids") or {}).items()},
                   d.get("note", ""))


def analyse(elf, names, fragments, game="", version="", refs=None, ctx=None):
    """:class:`SoundReading` of the game program *elf* (bytes) for the clip *names*.

    *fragments* is ``image.bin``'s fragment count; *game* and *version* find the build's port.
    *refs* (``{clip: [Ref]}``) and *ctx* (``prog`` and ``owners``, :func:`.clip_modes.analyse`'s)
    are reused when given. Read-only; never raises on a program it can't read."""
    from . import clip_modes as CM
    from . import stock_scan as S
    raw = bytes(elf)
    out = SoundReading()
    ctx = ctx or {}
    prog = ctx.get("prog")
    if prog is None:
        try:
            prog = S.Program(raw)
        except S.ScanError as e:
            out.note = "the game program could not be read (%s)" % e
            return out
    owners = ctx.get("owners")
    count, lists, tva, rva = request_table(raw, fragments) if fragments else (0, [], None, None)
    if not count:
        out.note = "the game's table of sound requests was not found"
        return out
    out.count = count
    seeds, port = port_seeds(prog, game, version) if game and version else ({}, "")
    if seeds:
        out.origin, out.port, depth, trust = "port", port, DEPTH_PORT, True
    else:
        seeds = table_readers(prog, tva, rva)
        out.origin, depth, trust = "located", DEPTH_LOCATED, False
    entries = sound_entries(prog, seeds, count, depth=depth, trust=trust) if seeds else {}
    if not entries:
        out.origin = ""
        out.note = "the game's sound functions were not found in its program"
        return out
    out.entries = {va: e.to_json() for va, e in entries.items()}
    calls = sound_calls(prog, entries, count)
    out.calls = len(calls)
    if refs is None:
        refs = CM.clip_refs(prog, raw, names, owners)
    out.pairs = pair(prog, refs, calls, owners)
    paired = sorted({p[0] for ps in out.pairs.values() for p in ps})
    menu = menu_names(raw, lists) if paired else {}
    out.names = {r: menu[r] for r in paired if r in menu}
    out.sids = {r: list(lists[r]) for r in paired}
    if not out.pairs:
        out.note = "no clip's code asks for a sound by a fixed number"
    return out


# ---- a request's sounds ------------------------------------------------------------------------
def resolve_requests(emu, params, lists, fw=None):
    """``{request: [idx, ...]}``: the master-directory records (Extract's ``idxNNNN.wav``) each
    request's sound ids resolve to, through the firmware's own ``get_asset_descriptor`` on the
    booted codec emulator *emu* (the chain :mod:`.spike2.sfx_names` names the Sound Test's
    sounds by). *params* is ``derive_params``' (rows carry ``key0``). A sound id of another
    category's bank (a licensed song) names no cat-0 record and is left out."""
    from .spike2 import sfx_names as SN
    key0 = {p["key0"]: p["idx"] for p in params if p.get("key0") is not None}
    if not key0:
        return {}
    resolver, buf = SN._find_resolver(emu, fw)
    if resolver is None:
        return {}
    by_sid, out = {}, {}
    for req, sids in enumerate(lists):
        got = []
        for sid in sids:
            if sid not in by_sid:
                desc = SN._try_resolve(emu, resolver, buf, sid)
                by_sid[sid] = SN._primary_idx(desc, key0) if desc else None
            i = by_sid[sid]
            if i is not None and i not in got:
                got.append(i)
        if got:
            out[req] = got
    return out


def write_requests(path, lists, idx_of, names):
    """Write :data:`REQUESTS_TSV`: one row per request, ``request idx sids name``."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("# The game's sound requests (what its code asks for by number) and the sounds\n"
                "# each plays: idx = audio/idxNNNN.wav, sids = its sound ids, name = its Sound\n"
                "# Test name. Written by Extract; the Video tab reads it.\n")
        f.write("request\tidx\tsids\tname\n")
        for req, sids in enumerate(lists):
            f.write("%d\t%s\t%s\t%s\n" % (req, ",".join("%d" % i for i in idx_of.get(req, ())),
                                          ",".join("%d" % s for s in sids),
                                          (names.get(req) or "").replace("\t", " ")))
    os.replace(tmp, path)


def read_requests(project):
    """``{request: {"idx": [...], "name": str}}`` from the project's :data:`REQUESTS_TSV`
    (``{}`` when the extract predates it)."""
    out = {}
    try:
        with open(os.path.join(project, REQUESTS_TSV), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or line.startswith("request\t"):
                    continue
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) < 4 or not cols[0].isdigit():
                    continue
                out[int(cols[0])] = {"idx": [int(x) for x in cols[1].split(",") if x.isdigit()],
                                     "name": cols[3]}
    except OSError:
        pass
    return out


def audio_files(project):
    """``{idx: "audio/<file>"}`` for the project's decoded sounds, whatever names the extract
    and the renames gave them (``idx0123.wav``, ``idx0123 - SE FX ROAR.wav``,
    ``00m01s200 - idx0123.wav``)."""
    out = {}
    d = os.path.join(project, "audio")
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not n.lower().endswith(".wav"):
            continue
        m = _IDX_RE.search(n)
        if m:
            out.setdefault(int(m.group(1)), "audio/" + n)
    return out


def card_fragments(img, part, game):
    """``image.bin``'s fragment count read off an open :class:`.explorer.CardImage`, or None."""
    from .info import container_counts
    try:
        reader = img._reader(part)
        res = img._resolve(reader, "/%s/image.bin" % game)
        if res is None:
            return None
        head = reader.read_range(res[1], 0, 0x100)
        return container_counts(bytes(head))[0]
    except Exception:                                       # noqa: BLE001 - unreadable: unknown
        return None
