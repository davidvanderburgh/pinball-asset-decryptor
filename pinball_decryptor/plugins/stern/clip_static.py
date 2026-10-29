"""PAD-827: what the game program itself says about how a clip is played - read statically, on
every Spike 2 title, beside what the emulator saw (:mod:`.clip_seen`).

Two things are in the program whatever the title, and :func:`analyse` reads both:

* A TABLE OF CLIPS. A mode that has several clips for one moment keeps their names together in
  its data - an array of name pointers (Godzilla's Ebirah battle: ``fight_loop``, ``fight_loop2``,
  ``fight_loop3`` at LE 1.16 0x70e2a0) or an array of records each holding one (stride 8-64
  bytes) - and the game picks one when the moment comes. :func:`tables` finds every run of two or
  more clip-name pointers at one stride; a table's loaders (the code that makes its address, or
  the address of a word just before it, :data:`TABLE_BACK`) are read for HOW it picks: a loader
  that reads a field of an object, uses it as the table's index and writes the same field back
  (Ebirah: ``ldr [r0,#0x7c]`` ... ``str [r4,#0x7c]``, the index stepped mod 3) plays them IN TURN;
  anything else is a pick the program leaves to its state (the shot, a random number, the
  player's progress).
* THE CLIP PLAYER'S LOOP FLAG. Where a title plays a clip through one call that takes the name and
  a loop flag (Godzilla's ``clip_play(name, loop, crop)``, Deadpool's video layer ``(obj, &name,
  loop)``), the call is found by what it is called WITH (:func:`players`): the function most code
  that names a clip calls next with the name in ``r0`` or ``r1``, whose next argument is a constant
  0 or 1 at nearly every such call. At each of those calls a constant 1 means the game loops the
  clip. A 0 says only that this call does not ask for a loop: a game can still ask for the clip
  again as it ends (the emulator saw Ebirah's fight loops re-asked with the flag 0), so only the
  1 is shown. Only a clip named right before the call gets it: a call that plays an entry of a
  table plays whichever one the index says. A clip v2 build sets a clip on a surface and plays it with a separate call, so it
  has no such player and no flag is read there.

What the program does NOT say statically, measured on Godzilla LE 1.16 against the emulator:
which switch starts a clip (a mode's shot handler picks a record by an index it keeps; tying the
two means tracing that title's own logic) and the words drawn over it (the battle's display draws
its numbered text lines, not beside the clip). Those stay the emulator's.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

#: bumped when what :func:`analyse` reads changes
READ_REV = 1
#: the widest record a table of clips is read with (bytes between two names' pointers)
STRIDE_MAX = 64
#: the most clips a table may name and still be one moment's set: past it a table is a catalogue
#: (Elvira's 2246 film clips, Star Wars' 426 scenes), which says nothing about how one plays;
#: Batman's per-episode sets (up to 194) and Elvira's per-film ones are picked from but are too
#: many to name as a set
TABLE_MAX = 64
#: how far back from a table's first name its start may be (words): a record array's other fields
TABLE_BACK = 16
#: how many instructions after a clip name is made its play call is looked for
CALL_NEAR = 12
#: a clip player is called next by code naming this many different clips, at least ...
PLAYER_MIN = 4
#: ... with a constant 0 or 1 as its loop flag at this share of those calls
PLAYER_FLAG = 0.8
#: the most instructions of a loader read for its index (from its start)
LOADER_MAX = 400


@dataclass
class Table:
    """A run of clip-name pointers at one stride in the program's data."""
    at: int                                   # VA of the first name's pointer
    stride: int
    names: list = field(default_factory=list)
    turn: bool = False                        # a loader steps through it in turn
    loaders: list = field(default_factory=list)


@dataclass
class StaticReading:
    tables: list = field(default_factory=list)          # [Table]
    players: list = field(default_factory=list)         # [(VA, flag register)]
    loops: dict = field(default_factory=dict)           # clip name -> True: a play call loops it

    def facts(self):
        """``{clip name: {"group": [names], "turn": bool, "loop": bool}}``: per clip, the other
        clips of its table (itself included, in table order), and whether a play call loops it."""
        out = {}
        for t in self.tables:
            for n in t.names:
                f = out.setdefault(n, {})
                if len(f.get("group", ())) < len(t.names):
                    f["group"], f["turn"] = list(t.names), t.turn
        for n in self.loops:
            out.setdefault(n, {})["loop"] = True
        return out

    def to_json(self):
        return {"rev": READ_REV, "facts": self.facts(),
                "tables": len(self.tables), "players": [[hex(p[0]), p[1]] for p in self.players]}


# ---- tables of clips ---------------------------------------------------------------------------
def tables(words, starts=None):
    """[:class:`Table`] from *words* ``[(VA, clip name)]``: the pointers to clip names in the
    program's data. A table is a run of two or more at one stride, at most :data:`STRIDE_MAX`
    apart, naming two to :data:`TABLE_MAX` different clips (a record table may name one clip in
    several records); a run of one stride is taken whole before a wider one is tried. *starts*
    (``VA -> bool``, the code makes this address) splits a run where a second table begins: the
    linker lays one mode's table right after another's (Godzilla's Ebirah fight loops, then
    Gigan's backgrounds, at one stride)."""
    words = sorted(set(words))
    out, i = [], 0
    starts = starts or (lambda va, stride: False)
    while i < len(words) - 1:
        va, name = words[i]
        stride = words[i + 1][0] - va
        if not 0 < stride <= STRIDE_MAX or stride % 4:
            i += 1
            continue
        j = i + 1
        while j + 1 < len(words) and words[j + 1][0] - words[j][0] == stride \
                and not starts(words[j + 1][0], stride):
            j += 1
        if j == i + 1 and j + 1 < len(words) and starts(words[j][0], stride) \
                and not starts(va, stride):
            i += 1                                     # one name before the next table's start
            continue
        names = list(dict.fromkeys(n for _v, n in words[i:j + 1]))    # once each, in order
        if 2 <= len(names) <= TABLE_MAX:
            out.append(Table(va, stride, names))
        i = j + 1
    return out


def _mem(w):
    """``(load?, base, imm offset, reg offset?, Rt)`` of an ARM word/byte/half load or store
    with an immediate or register offset, else None."""
    if (w >> 28) == 0xF:
        return None
    if (w & 0x0C000000) == 0x04000000:                 # ldr/str (word/byte)
        regoff = bool(w & 0x02000000)
        imm = 0 if regoff else (w & 0xFFF)
    elif (w & 0x0E000090) == 0x00000090 and (w & 0x60):  # ldrh/strh and friends
        regoff = not (w & 0x00400000)
        imm = 0 if regoff else (((w >> 4) & 0xF0) | (w & 0xF))
    else:
        return None
    if not (w & 0x00800000):
        imm = -imm
    return bool(w & 0x00100000), (w >> 16) & 0xF, imm, regoff, (w >> 12) & 0xF


def _wraps(w, n):
    """Whether the instruction *w* is one a turn counter wraps a table of *n* with: a compare
    with *n* or *n* - 1, an ``and`` with *n* - 1 (a power of two), a multiply-high (the
    compiler's division by a constant: Ebirah's ``umull`` by 0xaaaaaaab, mod 3) or a divide."""
    if (w >> 28) == 0xF:
        return False
    if (w & 0x0FE000F0) in (0x00800090, 0x00C00090):   # umull / smull
        return True
    if (w & 0x0FF0F0F0) in (0x0710F010, 0x0730F010):   # sdiv / udiv
        return True
    if (w & 0x0E000000) == 0x02000000:                 # data processing, immediate
        from .stock_scan import rot_imm
        op = (w >> 21) & 0xF
        v = rot_imm(w)
        if op == 0xA and (w & 0x00100000) and v in (n, n - 1):      # cmp rX, #n
            return True
        if op == 0x0 and n & (n - 1) == 0 and v == n - 1:           # and rX, rX, #n-1
            return True
    return False


def steps_in_turn(prog, start, n=0):
    """Whether the function at *start* reads an object's field, indexes with it, wraps it at the
    table's length *n* (:func:`_wraps`) and writes the same field back: ``ldr rI, [rB, #off]``
    ... a register-offset load ... ``str rX, [rB', #off]`` (the table's index kept in the object
    and moved on to the next, round to the first). A field read, used and written back with no
    wrap is a count (Jurassic Park's amber mines: the clip of the mine the player is on, which
    the emulator saw played 2, 1, 1, 4), not a turn."""
    from . import stock_scan as S
    try:
        end, lits = S.function_extent(prog, start, cap=LOADER_MAX)
    except Exception:                                   # noqa: BLE001 - unreadable: no
        return False
    loads, stores, indexed, wraps = {}, set(), False, False
    va = start
    while va < end:
        w = prog.word(va)
        va += 4
        if w is None:
            break
        if va - 4 in lits:
            continue
        wraps = wraps or _wraps(w, n)
        m = _mem(w)
        if m is None:
            continue
        load, base, off, regoff, _rt = m
        if regoff:
            indexed = indexed or load
            continue
        if base in (13, 15) or off <= 0:             # the stack and literals are no object field
            continue
        if load:
            loads.setdefault(off, va)
        elif off in loads and loads[off] < va:
            stores.add(off)
    return indexed and bool(stores) and wraps


def table_loaders(prog, table):
    """The functions whose code makes the table's address (or that of a word up to
    :data:`TABLE_BACK` before it, a record array's start)."""
    for k in range(TABLE_BACK):
        refs = prog.references(table.at - 4 * k)
        if refs:
            return sorted({prog.func_start(r) for r in refs} - {None})
    return []


# ---- the clip player and its loop flag ------------------------------------------------------------
#: the port sites that play a clip, and the register of their loop flag: ``clip_play(name, loop,
#: crop)``, the video layer's ``(obj, &name, loop)``, a clip v2 surface's ``play(surface, loop)``
PLAYER_SITES = {"clip_play": 1, "layer_video": 2, "surface_play": 1}
#: how far before a play call the clip (or the table) it plays is looked for (instructions)
NAME_BACK = 40


def port_players(prog, game, version):
    """``[(VA, flag register)]`` of the build's port's clip-playing sites that are this
    program's (the two words the port records match)."""
    try:
        from . import mode_runtime as MR
        path = MR.port_file(game, version)
    except Exception:                                   # noqa: BLE001 - no port
        path = None
    if not path:
        return []
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                q = line.split()
                if len(q) < 5 or q[0] != "site" or q[1] not in PLAYER_SITES:
                    continue
                try:
                    va, w0, w1 = int(q[2], 0), int(q[3], 0), int(q[4], 0)
                except ValueError:
                    continue
                if prog.in_text(va) and prog.word(va) == w0 and prog.word(va + 4) == w1:
                    out.append((va, PLAYER_SITES[q[1]]))
    except OSError:
        return []
    return out


def _next_call(prog, at, reg):
    """``(call VA, target, argument register)`` of the first ``bl`` within :data:`CALL_NEAR`
    instructions of *at* that is handed *reg* in ``r0`` or ``r1`` (directly, or by one ``mov``);
    None when the register is written over or a branch comes first."""
    holds = {reg}
    for k in range(1, CALL_NEAR + 1):
        va = at + 4 * k
        w = prog.word(va)
        if w is None or (w >> 28) == 0xF:
            return None
        if (w & 0x0F000000) == 0x0B000000:             # bl
            arg = 0 if 0 in holds else 1 if 1 in holds else None
            if arg is None:
                return None
            off = (w & 0xFFFFFF)
            off = (off - (1 << 24)) if off & 0x800000 else off
            return va, va + 8 + 4 * off, arg
        if (w & 0x0E000000) == 0x0A000000 or (w & 0x0FFFFFF0) == 0x012FFF10:
            return None                                # a branch: not this straight line
        if (w & 0x0FEF0FF0) == 0x01A00000 and (w & 0xF) in holds:   # mov rd, rm
            holds.add((w >> 12) & 0xF)
            continue
        rd = (w >> 12) & 0xF
        if (w & 0x0FF00000) == 0x03400000 and rd in holds:   # the movt of the name's pair
            continue
        if rd in holds and ((w & 0x0C000000) == 0x00000000 or (w & 0x0C100000) == 0x04100000):
            holds.discard(rd)                          # written over by an ALU op or a load
            if not holds:
                return None
    return None


def found_players(prog, code_refs):
    """``[(player VA, flag register)]`` found by what it is called with, for a build with no
    port: the function code naming :data:`PLAYER_MIN` different clips calls next with the name
    in ``r0``/``r1``, its next argument a constant 0 or 1 at :data:`PLAYER_FLAG` of the calls."""
    by_target = {}
    for name, at, reg in code_refs:
        got = _next_call(prog, at, reg)
        if got is not None:
            site, tgt, arg = got
            by_target.setdefault((tgt, arg), []).append((name, site))
    out = []
    for (tgt, arg), uses in by_target.items():
        if len({n for n, _s in uses}) < PLAYER_MIN:
            continue
        vals = [prog.const_before(site, arg + 1) for _n, site in uses]
        if sum(1 for v in vals if v in (0, 1)) >= PLAYER_FLAG * len(uses):
            out.append((tgt, arg + 1))
    return out


def _flag(prog, site, reg):
    """The constant in *reg* at the call *site* (the few instructions before it, then the
    function's tracker), or None."""
    from .clip_sounds import _const
    try:
        return _const(prog, site, reg)
    except Exception:                                   # noqa: BLE001 - unknown
        return None


def play_calls(prog, players, marks):
    """``[(call VA, flag, names)]``: every call of each of *players* with a constant 0 or 1
    flag, and what it plays - the clip named last before it in the same function within
    :data:`NAME_BACK` instructions (*marks*: sorted ``[(code VA, [name] or None)]``, None for the
    address of a table, whose clip the call plays is not known: such a call is left out)."""
    keys = [m[0] for m in marks]
    out = []
    for tgt, reg in players:
        for site in prog.callers(tgt):
            v = _flag(prog, site, reg)
            if v not in (0, 1):
                continue
            start = prog.func_start(site) or site
            i = bisect.bisect_left(keys, site) - 1
            if i < 0 or marks[i][0] < max(start, site - 4 * NAME_BACK):
                continue
            out.append((site, v, marks[i][1]))
    return out


# ---- the reading ----------------------------------------------------------------------------------
def analyse(prog, refs, game="", version=""):
    """:class:`StaticReading` of the program *prog* (:class:`.stock_scan.Program`) for the clip
    references *refs* (``{clip name: [Ref]}``, :func:`.clip_modes.clip_refs`); *game* /
    *version* find the build's port, whose clip-playing sites are taken first. Never raises."""
    out = StaticReading()
    try:
        _analyse(prog, refs, out, game, version)
    except Exception:                                   # noqa: BLE001 - best effort, as the modes
        pass
    return out


def _analyse(prog, refs, out, game, version):
    from . import progreloc
    words, code = [], []
    for name, rs in refs.items():
        for r in rs:
            if r.kind == progreloc.KIND_A32:
                w = prog.word(r.at)
                if w is not None:
                    # the pair's movt is the instruction the name is whole after
                    code.append((name, _movt_after(prog, r.at, (w >> 12) & 0xF), (w >> 12) & 0xF))
            elif r.kind == progreloc.KIND_T32:
                continue
            elif not (prog.tlo <= r.at < prog.code_end):
                words.append((r.at, name))
            else:
                for site in prog.literal_loads(r.at):      # a literal-pool word: its load
                    code.append((name, site, (prog.word(site) >> 12) & 0xF))
    made = {}

    def starts(va, stride):
        for k in range(max(1, stride // 4)):
            got = made.get(va - 4 * k)
            if got is None:
                got = made[va - 4 * k] = bool(prog.references(va - 4 * k))
            if got:
                return True
        return False

    marks = [(at, [name]) for name, at, _reg in code]
    for t in tables(words, starts):
        t.loaders = table_loaders(prog, t)
        t.turn = any(steps_in_turn(prog, f, len(t.names)) for f in t.loaders)
        out.tables.append(t)
        for k in range(TABLE_BACK):
            for site in prog.references(t.at - 4 * k):
                marks.append((site, None))         # a table: which of it the call plays is open
    marks.sort(key=lambda m: m[0])
    out.players = port_players(prog, game, version) or found_players(prog, code)
    for _site, v, names in play_calls(prog, out.players, marks):
        if v == 1 and names:
            out.loops[names[0]] = True


def _movt_after(prog, at, reg):
    for k in range(1, 25):
        w = prog.word(at + 4 * k)
        if w is not None and (w & 0x0FF00000) == 0x03400000 and ((w >> 12) & 0xF) == reg:
            return at + 4 * k
    return at


# ---- in words, for the Video tab ------------------------------------------------------------------
GROUP_MAX = 6


def words(name, fact):
    """``(cell, [tooltip lines])`` for one clip's :meth:`StaticReading.facts` entry ("" / [] for
    none)."""
    if not fact:
        return "", []
    cell, lines = [], []
    group = fact.get("group") or []
    if len(group) > 1:
        others = [g for g in group if g != name]
        cell.append(("In turn with %d other" if fact.get("turn") else "1 of %d")
                    % (len(others) if fact.get("turn") else len(group))
                    + ("s" if fact.get("turn") and len(others) > 1 else ""))
        shown = ", ".join(others[:GROUP_MAX]) + (" and %d more" % (len(others) - GROUP_MAX)
                                                 if len(others) > GROUP_MAX else "")
        lines.append(("The game plays it in turn with %s: each time it comes, the next one."
                      if fact.get("turn") else
                      "The game keeps it in a table with %s and picks one of them when the moment "
                      "comes (the shot, the player's progress or chance decides).") % shown)
    if fact.get("loop"):
        cell.append("loops")
        lines.append("The game asks for it as a loop: it plays again each time it ends.")
    return " · ".join(cell), lines
