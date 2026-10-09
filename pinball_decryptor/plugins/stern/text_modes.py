"""PAD-470: which of the game's own modes shows each line of game-program text, and a line of
its own for a mode that shows the same text as another.

A field report (Godzilla retheme): the award lines of the battles vs Gigan and vs Megalon and
the jackpots of the Megalon and Gigan multiball had all been renamed to the same words, so the
Text tab offered ONE row for them and a new name went to every battle at once. The ask was a
different text in each mode.

HOW THE GAME SHOWS A LINE. A Spike 2 game keeps its display text in a table of numbered lines
(the localised-string table: a word per line, pointing at five ``char*``, one per language,
the name group :mod:`.progtext` already reads), and the code asks for a line by its NUMBER -
``movw r0, #3320`` and a call to the table's reader, or the number stored in an object that
asks for it later. So "which mode shows this line" is "whose code holds its number":

* ``exact``: the number put in ``r0`` right before a call to the table's reader (a function
  whose code loads the table's address) - certain;
* ``near``: any other ``movw``/``mov`` of the number, or a word holding it in a table that one
  mode's code loads, counted only when the same mode asks for a line numbered within
  :data:`NEAR` of it the exact way. A mode's lines are numbered together (Stern lists them per
  mode), so the rule keeps Gigan's award (stored in the effect object that shows it, next to
  Gigan's ramp lines) and the Megalon battle's (13 past its last exact line) and drops a
  number that only happens to equal one (a sound or a lamp number in the same object, beside
  no line of that mode).

Only lines of the table are read this way. A text the code reaches by a plain pointer (a
``movw``/``movt`` pair, a word in a table, :mod:`.progreloc`'s census) names no mode: the
owner rules that serve the clips name the wrong mode for a menu's option words, and a
static initialiser far from any mode's code ("LKRAM" on Pro 1.16) reads as the last mode's.

WHO OWNS THE CODE is :class:`.clip_modes._Owners` (a mode's own virtuals, the file it ends,
the functions between two of its own).

TWO LINES, ONE TEXT. The linker keeps one copy of a text however many lines show it (stock
Godzilla's ``GIGAN`` is line 3250 in the battle vs Gigan and line 3533 in King of the
Monsters), and a card an earlier build renamed can hold the same words twice (the Heisei
retheme's ``KAIJU AWARD`` is two strings, lines 3320 and 3338). Either way a mode's own text
is a matter of pointing that mode's references at a copy of the new text - the copy goes in
the game program's extension segment, as longer text does - or, when every reference to one
string is that mode's, rewriting that string in place (:func:`.progtext.plan_writes`).

MEASURED on stock Godzilla Pro and LE 1.16: 3949 lines. ``GIGAN AWARD`` is the battle vs
Gigan's alone, ``MEGALON AWARD`` the battle vs Megalon's, ``MEGALON JACKPOT!`` and ``GIGAN
JACKPOT!`` the Megalon and Gigan multiball's (a table of its own).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

#: bumped when what :func:`read` finds changes
READ_REV = 1
#: how close (in line numbers) a ``near`` use must be to one of the same mode's ``exact`` ones
NEAR = 16
#: the words of one line of the table: five language pointers and a zero
ENTRY_WORDS = 6
#: how far past a mode's last own virtual a static initialiser may start and still end that
#: mode's file (bytes): the one after the last mode's code on Godzilla Pro 1.16 is 2.5 MB on,
#: in the service menu's code, and asks for its lines
INIT_REACH = 0x10000
def mode_label(cls):
    from .clip_modes import mode_label as _ml
    return _ml(cls)


@dataclass
class Reading:
    """What :func:`read` found in one game program."""
    table_va: int = 0
    count: int = 0
    labels: dict = field(default_factory=dict)       # mode class -> "Battle vs Gigan"
    line_modes: dict = field(default_factory=dict)   # line number -> frozenset of classes
    #: ``{span file offset: [(census ref, mode class or "")]}`` - every reference of every
    #: display span, with the one mode whose it is ("" for several, none or unknown)
    keys: dict = field(default_factory=dict)
    #: ``{span file offset: [mode class]}``: the modes that show the span, by its references
    shown: dict = field(default_factory=dict)

    def label(self, cls):
        return self.labels.get(cls) or mode_label(cls)

    def refs_of(self, off, cls):
        """The references of the span at *off* that are *cls*'s alone (the whole string,
        never a tail)."""
        return [r for r, k in self.keys.get(off, ()) if k == cls and r["delta"] == 0]


def _ref_key(r):
    return (r["kind"], tuple(r["offs"]))


# ---- the table of numbered lines ------------------------------------------------------------
def _entry_ok(prog, va):
    """Is *va* one line of the table: five pointers into the program, then a zero?"""
    ws = [prog.word(va + 4 * k) for k in range(ENTRY_WORDS)]
    if any(w is None for w in ws) or ws[-1] != 0:
        return False
    return all(w and prog.is_address(w) for w in ws[:-1])


def find_table(prog, raw, census):
    """``(table VA, line count)`` of the game's numbered-line table, ``(0, 0)`` for none.

    The census's name groups at a string's start are lines of it; the table is the run of
    words pointing at them (and at the lines no display text is in), and the code loads its
    first word's address."""
    import numpy as np
    from . import progreloc
    entries = set()
    for refs in census.values():
        for r in refs:
            if r["kind"] == progreloc.KIND_GROUP and r["delta"] == 0 and r["offs"]:
                va = prog.off2va(r["offs"][0])
                if va is not None:
                    entries.add(va)
    if len(entries) < 16:
        return 0, 0
    n = len(raw) // 4
    a = np.frombuffer(raw[:n * 4], dtype="<u4")
    hits = np.flatnonzero(np.isin(a, np.array(sorted(entries), dtype=np.uint32)))
    if not len(hits):
        return 0, 0
    # the densest run of them (the table holds every line; a stray pointer elsewhere is one)
    gaps = np.flatnonzero(np.diff(hits) > 64)
    starts = np.concatenate(([0], gaps + 1))
    ends = np.concatenate((gaps, [len(hits) - 1]))
    best = int(np.argmax(ends - starts))
    lo, hi = int(hits[starts[best]]), int(hits[ends[best]])
    if ends[best] - starts[best] < 16:
        return 0, 0
    lo_va, hi_va = prog.off2va(lo * 4), prog.off2va(hi * 4)
    if lo_va is None or hi_va is None:
        return 0, 0
    while _entry_ok(prog, prog.word(lo_va - 4) or 0):
        lo_va -= 4
    while _entry_ok(prog, prog.word(hi_va + 4) or 0):
        hi_va += 4
    if not prog.references(lo_va):
        return 0, 0
    return lo_va, (hi_va - lo_va) // 4 + 1


def _line_of_entry(prog, table_va, count):
    """``{entry VA: line number}``."""
    out = {}
    for i in range(count):
        w = prog.word(table_va + 4 * i)
        if w:
            out.setdefault(w, i)
    return out


# ---- who loads what --------------------------------------------------------------------------
class _Loads:
    """``{value: [code VA]}`` of every address the code makes (``movw``/``movt`` pairs and
    literal-pool loads), built once, and the mode owning a table word by it - what
    :meth:`.clip_modes._Owners.of_table` asks of :meth:`.stock_scan.Program.references`
    one value at a time, too slow for thousands of words."""

    def __init__(self, prog, owners):
        import numpy as np
        self.prog, self.owners = prog, owners
        self.at = {}
        for reg in range(13):
            for v, vas in prog.movwt_values(reg).items():
                self.at.setdefault(v, []).extend(vas)
        w = prog.tw
        ldr = np.flatnonzero((w & 0x0F7F0000) == 0x051F0000)
        imm = (w[ldr] & 0xFFF).astype(np.int64)
        up = (w[ldr] & 0x00800000) != 0
        site = prog.tlo + 4 * ldr.astype(np.int64)
        pool = site + 8 + np.where(up, imm, -imm)
        pi = (pool - prog.tlo) // 4
        ok = (pool % 4 == 0) & (pi >= 0) & (pi < len(w))
        for s, p in zip(site[ok].tolist(), pi[ok].tolist()):
            self.at.setdefault(int(w[p]), []).append(s)
        self._table = {}

    def of_table(self, wva):
        """The one mode whose code loads the table holding the word at *wva* ("" for none
        or several)."""
        from .clip_modes import TABLE_BACK
        got = self._table.get(wva)
        if got is not None:
            return got
        got = ""
        for k in range(TABLE_BACK):
            sites = self.at.get(wva - 4 * k)
            if not sites:
                continue
            owners = {_owner(self.prog, self.owners, s) for s in sites}
            if len(owners) == 1 and "" not in owners:
                got = owners.pop()
            break
        self._table[wva] = got
        return got


# ---- which mode asks for which line ----------------------------------------------------------
def _readers(prog, table_va):
    """The functions whose code loads the table's address: the ones a line number is asked
    of."""
    return {prog.func_start(v) for v in prog.references(table_va)}


def _exact_uses(prog, readers, count):
    """``[(line, call site)]``: a line number put in ``r0`` right before a call to a reader."""
    import numpy as np
    sites, tgts, vals = prog.call_constants(0)
    ok = np.isin(tgts, np.array(sorted(readers), dtype=tgts.dtype)) & (vals >= 0) & (vals < count)
    return [(int(v), prog.tlo + 4 * int(s)) for s, v in zip(sites[ok], vals[ok])]


def _near_uses(prog, count):
    """``[(line, VA)]``: every other ``movw``/``mov`` putting a value below *count* in a
    register that no ``movt`` makes an address of."""
    import numpy as np
    w = prog.tw
    n = len(w)
    cond_ok = (w >> 28) != 0xF
    imm16 = (((w >> 16) & 0xF) << 12) | (w & 0xFFF)
    rd = (w >> 12) & 0xF
    movw = ((w & 0x0FF00000) == 0x03000000) & cond_ok & (imm16 < count)
    out = []
    movt = (w & 0x0FF00000) == 0x03400000
    for i in np.flatnonzero(movw).tolist():
        r = int(rd[i])
        if any(movt[j] and int(rd[j]) == r for j in range(i + 1, min(i + 7, n))):
            continue                               # the low half of an address
        out.append((int(imm16[i]), prog.tlo + 4 * i))
    mov = ((w & 0x0FEF0000) == 0x03A00000) & cond_ok
    rot = ((w >> 8) & 0xF).astype(np.uint64) * 2
    i8 = (w & 0xFF).astype(np.uint64)
    val = np.where(rot == 0, i8, ((i8 >> rot) | (i8 << (np.uint64(32) - rot))) & 0xFFFFFFFF)
    for i in np.flatnonzero(mov & (val < count)).tolist():
        out.append((int(val[i]), prog.tlo + 4 * i))
    return out


def _table_uses(prog, raw, count, lines_wanted):
    """``[(line, VA)]``: a word holding one of *lines_wanted* in the program's data (a table
    of line numbers a mode's code reads, the Megalon and Gigan multiball's jackpots)."""
    import numpy as np
    if not lines_wanted:
        return []
    out = []
    want = np.array(sorted(lines_wanted), dtype=np.uint32)
    for name in (".rodata", ".data", ".data.rel.ro"):
        sec = prog.sections.get(name)
        if not sec:
            continue
        addr, off, size = sec
        a = np.frombuffer(raw[off:off + size // 4 * 4], dtype="<u4")
        for i in np.flatnonzero(np.isin(a, want)).tolist():
            out.append((int(a[i]), addr + 4 * i))
    return out


def _owner(prog, owners, va):
    """The mode whose code *va* is (:meth:`.clip_modes._Owners.of_code`), less a static
    initialiser further than :data:`INIT_REACH` past the mode's code."""
    m, how = owners.of_code(va)
    if m and how == "init":
        fn = prog.func_start(va)
        i = bisect.bisect_right(owners.avas, fn) - 1
        if i < 0 or fn - owners.avas[i] > INIT_REACH:
            return ""
    return m


def line_modes(prog, raw, owners, loads, table_va, count):
    """``{line number: frozenset of mode classes}`` for the lines some mode asks for, by the
    rules in the module docstring ("" in the set: code that is no one mode's asks for it too,
    exactly)."""
    readers = _readers(prog, table_va)
    exact = {}
    for line, site in _exact_uses(prog, readers, count):
        exact.setdefault(line, set()).add(_owner(prog, owners, site))
    by_mode = {}
    for line, ms in exact.items():
        for m in ms:
            if m:
                by_mode.setdefault(m, []).append(line)
    for m in by_mode:
        by_mode[m].sort()

    def near(m, line):
        ls = by_mode.get(m)
        if not ls:
            return False
        i = bisect.bisect_left(ls, line)
        return any(0 <= j < len(ls) and abs(ls[j] - line) <= NEAR for j in (i - 1, i))

    got = {line: set(ms) for line, ms in exact.items()}
    for line, va in _near_uses(prog, count):
        m = _owner(prog, owners, va)
        if m and near(m, line):
            got.setdefault(line, set()).add(m)
    wanted = {line + d for ls in by_mode.values() for line in ls for d in range(-NEAR, NEAR + 1)}
    for line, va in _table_uses(prog, raw, count, {x for x in wanted if 0 <= x < count}):
        m = loads.of_table(va)
        if m and near(m, line):
            got.setdefault(line, set()).add(m)
    return {line: frozenset(ms) for line, ms in got.items()}


# ---- reading ---------------------------------------------------------------------------------
def read(raw, spans=None, census=None):
    """:class:`Reading` of the game program *raw* (bytes); *spans* / *census* are
    :func:`.progtext._display_spans` / :func:`.progtext._census` when the caller has them.
    Never raises: a program it can't read is an empty reading."""
    try:
        return _read(bytes(raw), spans, census)
    except Exception:                                       # noqa: BLE001 - best effort
        return Reading()


def _read(raw, spans, census):
    from . import clip_modes as CM
    from . import progreloc
    from . import progtext
    from . import stock_scan as S
    out = Reading()
    if spans is None:
        ranges = progtext._load_ranges(raw)
        if not ranges:
            return out
        spans = progtext._display_spans(raw, ranges)
    if census is None:
        census = progtext._census(raw, spans)
    try:
        prog = S.Program(raw)
    except S.ScanError:
        return out
    model = S.class_model(prog)
    modes = CM._mode_classes(S, model)
    if not modes:
        return out
    layers = CM._layers(model, modes)
    owners = CM._Owners(S, prog, CM._anchors(S, prog, model, modes, layers), CM._inits(S, prog))
    loads = _Loads(prog, owners)
    table_va, count = find_table(prog, raw, census)
    entry_line = {}
    if count:
        out.table_va, out.count = table_va, count
        out.line_modes = line_modes(prog, raw, owners, loads, table_va, count)
        entry_line = _line_of_entry(prog, table_va, count)
    for off, _text in spans:
        rows = []
        shown = set()
        for r in census.get(off, ()):
            ms = set()
            at = prog.off2va(r["offs"][0]) if r["offs"] else None
            if r["kind"] == progreloc.KIND_GROUP and at in entry_line:
                ms = set(out.line_modes.get(entry_line[at], ()))
            named = {m for m in ms if m}
            shown |= named
            rows.append((r, next(iter(named)) if len(ms) == 1 and named else ""))
        out.keys[off] = rows
        out.shown[off] = sorted(shown)
        for m in shown:
            out.labels.setdefault(m, mode_label(m))
    return out


# ---- a text's lines --------------------------------------------------------------------------
def text_modes(reading, offs):
    """For the spans at *offs* (one text): ``(shown, parts)`` - every mode that shows it, in
    label order, and the modes that get a row of their own (none unless the text's lines
    name two modes, or one mode and lines no one mode shows)."""
    shown, keys, other = set(), set(), False
    for off in offs:
        shown.update(reading.shown.get(off, ()))
        for r, k in reading.keys.get(off, ()):
            if r["delta"]:
                continue
            if k:
                keys.add(k)
            else:
                other = True
    order = lambda c: (reading.label(c).lower(), c)            # noqa: E731
    parts = sorted(keys, key=order) if len(keys) >= 2 or (keys and other) else []
    return sorted(shown, key=order), parts


def whole_span(reading, off, cls):
    """Is every reference of the span at *off* (tails too) *cls*'s alone? Then its own text
    can be written over the string itself."""
    rows = reading.keys.get(off, ())
    return bool(rows) and all(k == cls and r["delta"] == 0 for r, k in rows)
