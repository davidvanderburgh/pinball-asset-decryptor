"""PAD-634: which of the game's modes plays a clip, read SOURCE FILE by source file - the reading
for the titles :mod:`.clip_modes`' class-by-class one names no mode on: the plain-C titles
(Aerosmith, Batman 66, Beatles, Elvira 3, Guardians, James Bond, Jurassic Park the Pinball,
Metallica, Star Wars ELG, Stranger Things), whose programs carry no class per mode, and Deadpool,
whose clips are played by display-effect code kept in files of their own.

THE FILES. These programs are compiled as C++, and nearly every source file has a static
initialiser (``.init_array``; at the least the one ``<iostream>`` brings), which the linker puts
at the END of its file's code (:func:`.clip_modes._inits`; 473 on Aerosmith 1.16). So the code
between two initialisers is one source file - two at most, when one of them builds no global.
A clip named anywhere in a file - its functions, its initialiser's tables - belongs to that
file, and a file belongs to a mode when the program shows it is that mode's code, and no other
mode's:

* plain C - the mode's own records, which only its code writes, outnumbering the records of
  no mode written there (a feature's file - pop bumpers - also runs a "super" mode): the audits
  counted for it
  (``AUD_TOYS_IN_THE_ATTIC_MULTIBALL_STARTED``, ``..._SUPER_JACKPOT_AWARDS``: the audit witness
  of :mod:`.stock_scan_c`) and its game flags SET or CLEARED (``FG_MODE_SWEET_EMOTION_ACTIVE``:
  Aerosmith's songs have no start audit, only that flag; :func:`flag_writers`). A flag only
  TESTED is no evidence: any code may ask whether a mode runs (Beatles' feature totals ask
  about Main Multiball).
  The modes are the ones those audits and flags name (:func:`c_modes`).
* C++ (Deadpool) - a mode class's own virtuals (:func:`.clip_modes._anchors`), and the display
  effects the mode names for the framework to show: its intro and total effects are virtuals
  that return an effect's id (Deadpool's ``cbattle_juggernaut`` slot 43 returns 68), the id
  indexes the display-effect table (``{function, priority}``, 173 on Deadpool LE 1.16), and the
  effect's function is in the display file (``def_juggernaut``) whose clips the mode then plays.
  Which slots those are is read off the framework itself (:func:`effect_slots`): the slots
  whose result it moves into ``r1`` for one effect function.

A file with evidence of two modes or more names none (a shared multiball file, a select
screen), and so does a file with none (main play, attract, the toy box rule): its clips stay
"other parts of the game". MEASURED on every plain-C card and Deadpool on D: (docs/plans/
played_in_plain_c.md) and proven on the emulator.
"""
from __future__ import annotations

import bisect
import collections
import re
import struct

import numpy as np

#: FG_<name>_ACTIVE flags that are not a mode of the game's (the framework's player modes, test
#: and ball-device state)
NOT_FLAG = re.compile(r"^(PLAYER_|TEST_|MBDEV_|FACTORY_|LOCKOUT|GAME_VALIDATION|FATAL|"
                      r"DIAGNOSTICS|SHOW_PENDING)")
#: a flag function is handed this many different flag ids at least (Aerosmith 1.16's flag set
#: and clear: 47 and 45; the next callee whose ids all fit is the challenge menu's, 21)
FLAG_IDS_MIN = 20
#: how many instructions into a flag function its bit operation is looked for
FLAG_FN_MAX = 28
#: the display-effect table's shortest run of entries, and the most it is looked back for
EFFECTS_MIN = 32


class _Graph:
    """The program's functions: where each starts (a ``push {.., lr}``) and which source file
    (:func:`.clip_modes._inits`) it is in."""

    def __init__(self, prog, inits):
        self.prog = prog
        self.inits = list(inits)

    def file_of(self, va):
        """The static initialiser that ends the file *va* is in (its VA), or None after the
        last one. An initialiser is its own file's."""
        fn = self.prog.func_start(va)
        j = bisect.bisect_left(self.inits, fn)
        return self.inits[j] if j < len(self.inits) else None


# ---- plain C: the modes, and whose code a function is -----------------------------------------
def bit_writer(prog, f):
    """``"set"`` / ``"clear"`` when the function at *f* sets or clears one bit of a bit array
    indexed by its first argument - ``ldrb rX, [rB, r0, asr #3]`` then ``orr`` / ``bic`` of
    ``1 << (r0 & 7)`` - else None (a test reads the bit and writes none; Stranger Things
    0x4296cc, handed flag-sized ids too, stores into a table)."""
    load = op = None
    for k in range(FLAG_FN_MAX):
        w = prog.word(f + 4 * k)
        if w is None:
            break
        if (w & 0x0FF00FF0) == 0x07D001C0:
            load = True
        elif (w & 0x0FE000F0) == 0x01800010:
            op = "set"
        elif (w & 0x0FE000F0) == 0x01C00010:
            op = "clear"
        if k and ((w & 0x0FFF8000) == 0x08BD8000 or w in (0xE12FFF1E, 0xE49DF004)
                  or (k > 3 and (w & 0x0FFF4000) == 0x092D4000)):
            break                               # a return, or the next function's push (a
            #                                     prologue's can come a few words in)
    return op if load else None


def flag_writers(prog, count):
    """The functions that set or clear a game flag: callees handed :data:`FLAG_IDS_MIN`
    different flag ids at least and nothing else (``mov r0, #id``) that set or clear a bit
    (:func:`bit_writer`). One of each on every plain-C card read (Aerosmith 1.16: 0x1a5450 sets,
    0x1a5408 clears)."""
    _s, tgts, vals = prog.call_constants(0)
    ids, other = collections.defaultdict(set), collections.Counter()
    for t, v in zip(tgts.tolist(), vals.tolist()):
        if v < 0:
            continue
        if 0 < v < count:
            ids[t].add(v)
        else:
            other[t] += 1
    return sorted(t for t, vs in ids.items() if len(vs) >= FLAG_IDS_MIN and not other[t]
                  and bit_writer(prog, t))


def c_modes(prog):
    """``(keys, records)`` of a plain-C program: ``keys`` the modes (``SWEET_EMOTION``, as the
    Modes tab keys them: :func:`.stock_scan_c.mode_key`) - every mode a ``..._STARTED`` audit
    counts and every ``FG_<mode>_ACTIVE`` flag; ``records`` ``{function VA: Counter}``, how many
    audits each function counts and game flags it sets or clears, by the mode they are of
    (``""`` for a record of no mode: a pop bumper hit, a dart level)."""
    from . import stock_scan_c as SC
    names, ids, _rec = SC.audit_ids(prog)
    flags = SC.name_array(prog, b"FG_")
    keys = []
    for k, _a in SC.mode_audits(names):
        if k not in keys:
            keys.append(k)
    for x in flags:
        if x and x.endswith("_ACTIVE"):
            k = x[3:-7]
            if NOT_FLAG.match(k):
                continue
            k = k[5:] if k.startswith("MODE_") else k
            if k and k not in keys:
                keys.append(k)
    by_len = sorted(keys, key=len, reverse=True)

    def key_of(name, prefix):
        u = name[len(prefix):]
        if u.startswith("MODE_"):
            u = u[5:]
        for k in by_len:
            if u == k or u.startswith(k + "_"):
                return k
        return None

    recs = collections.defaultdict(collections.Counter)
    audit_add = SC.find_audit_add(prog, ids)
    if audit_add:
        for site in prog.callers(audit_add):
            name = ids.get(prog.const_before(site, 0))
            if name:
                recs[prog.func_start(site)][key_of(name, "AUD_") or ""] += 1
    for f in flag_writers(prog, len(flags)) if flags else ():
        for site in prog.callers(f):
            v = prog.const_before(site, 0)
            if v is None or not 0 < v < len(flags) or not flags[v]:
                continue
            recs[prog.func_start(site)][key_of(flags[v], "FG_") or ""] += 1
    return keys, dict(recs)


def c_label(key):
    """``LOVE_IN_AN_ELEVATOR_MULTIBALL`` -> ``Love in an Elevator Multiball``, as the Modes tab
    names a plain-C title's modes."""
    from . import stock_scan as S
    from . import stock_scan_c as SC
    return S.readable(" ".join(SC._words(key)))


def is_c_key(mode):
    """Whether *mode* is a plain-C mode's key (all capitals), not a C++ class."""
    return bool(mode) and mode == mode.upper() and any(c.isalpha() for c in mode)


# ---- C++: the display effects a mode names ----------------------------------------------------
def effect_table(prog):
    """``(VA of id 0's function word, count)`` of the display-effect table - the longest run of
    ``{function, priority}`` entries in the program's data whose start the code loads - or
    None."""
    best = None
    for off, va, fsz, _msz, flg in prog.loads:
        if flg & 1:
            continue
        base = (off + 3) & ~3
        n = (off + fsz - base) // 4
        if n < 2 * EFFECTS_MIN:
            continue
        w = np.frombuffer(prog.b, dtype="<u4", count=n, offset=base)
        isf = (w >= prog.tlo) & (w < prog.code_end) & (w % 4 == 0)
        for par in (0, 1):
            d = np.diff(np.concatenate(([0], isf[par::2].astype(np.int8), [0])))
            starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
            for a, b in zip(starts.tolist(), ends.tolist()):
                if b - a < EFFECTS_MIN:
                    continue
                first = va + (base - off) + 4 * (par + 2 * a)
                for back in (0, 8):                     # entry 0 is often empty
                    if prog.references(first - back):
                        got = (first - back, b - a + back // 8)
                        if best is None or got[1] > best[1]:
                            best = got
                        break
    return best


def _leaf_const(prog, f):
    """*n* when the function at *f* is ``mov r0, #n ; bx lr``, else None."""
    from . import stock_scan as S
    w0, w1 = prog.word(f), prog.word(f + 4)
    if w0 is None or w1 != 0xE12FFF1E:
        return None
    d = S.decode(w0, f)
    return d[2] if d[0] in ("mov", "movw") and d[1] == 0 and d[-1] == 0xE else None


def effect_slots(prog, steps=16):
    """The virtual slots that answer a display effect's id: the code calls the slot (``ldr rX,
    [vptr, #4k]; blx rX``), moves the answer into ``r1`` and hands it to a function in
    ``.text`` that gets it from two slots or more (Deadpool LE 1.16: slots 42 and 43 to
    0x2cb768, 44 to 0x2cbd28; Godzilla Pro 1.16: 56 to 58)."""
    from . import stock_scan as S
    tw, tlo = prog.tw, prog.tlo
    n = len(tw)
    text = prog.sections.get(".text")
    lo, hi = (text[0], text[0] + text[2]) if text else (prog.tlo, prog.code_end)
    ldr = np.nonzero(((tw & 0x0FF00000) == 0x05900000) & ((tw >> 28) == 0xE)
                     & ((tw & 0x3) == 0) & ((tw & 0xFFF) >= 8) & ((tw & 0xFFF) <= 0x400))[0]
    blx = (tw & 0x0FFFFFF0) == 0x012FFF30
    hits = collections.defaultdict(set)
    for i in ldr.tolist():
        w = int(tw[i])
        rt, slot = (w >> 12) & 0xF, (w & 0xFFF) // 4
        j = next((i + k for k in (1, 2, 3) if i + k < n and blx[i + k]
                  and (int(tw[i + k]) & 0xF) == rt), None)
        if j is None:
            continue
        todo, seen = [(j + 1, False, 0)], set()
        while todo:
            p, held, st = todo.pop()
            if (p, held) in seen or st > steps or not 0 <= p < n:
                continue
            seen.add((p, held))
            x = int(tw[p])
            d = S.decode(x, tlo + 4 * p)
            if d[0] in ("bl", "b"):
                if d[-1] == 0xE and held and lo <= d[1] < hi:
                    hits[d[1]].add(slot)
                if d[0] == "b":
                    todo.append(((d[1] - tlo) // 4, held, st + 1))
                    if d[-1] != 0xE:
                        todo.append((p + 1, held, st + 1))
                continue
            if d[0] in ("bxlr", "poppc", "blx", "bx") or (x & 0x0FFF8000) == 0x08BD8000:
                continue
            if d[0] == "movr" and d[1] == 1 and d[2] == 0:
                todo.append((p + 1, True, st + 1))
                continue
            if d[0] in ("stri", "strd"):
                wr = ()
            elif d[0] == "other":
                wr = tuple(d[1])
            elif len(d) > 2 and isinstance(d[1], int):
                wr = (d[1],)
            else:
                wr = ()
            if held and 1 in wr:
                continue
            todo.append((p + 1, held, st + 1))
    return sorted({s for _f, ss in hits.items() if len(ss) >= 2 for s in ss})


def effect_files(prog, model, modes, graph):
    """``{file: {mode class}}``: the files whose display effects a mode names in its own
    effect slots (:func:`effect_slots`)."""
    from . import stock_scan as S
    table = effect_table(prog)
    if not table:
        return {}
    base, count = table
    slots = effect_slots(prog)
    out = collections.defaultdict(set)
    for cls in modes:
        try:
            own = dict(S.own_slots(prog, model, cls)[1])
        except Exception:                                   # noqa: BLE001 - a class the scan can't read
            continue
        for k in slots:
            f = own.get(k)
            v = _leaf_const(prog, f) if f else None
            if v is None or not 0 < v < count:
                continue
            e = prog.word(base + 8 * v)
            fi = graph.file_of(e) if e and prog.in_text(e) else None
            if fi is not None:
                out[fi].add(cls)
    return dict(out)


# ---- the owners ------------------------------------------------------------------------------
class FileOwners:
    """:class:`.clip_modes._Owners`' questions, answered by source file: ``(mode, "file")``
    for code in a file only one mode's evidence is in, ``(mode, "table")`` for a table only
    such code loads; ``("", "")`` otherwise."""

    def __init__(self, prog, graph, modes_of_file):
        self.prog = prog
        self.graph = graph
        self.mode_of = {fi: next(iter(ms)) for fi, ms in modes_of_file.items() if len(ms) == 1}
        self._table = {}
        self._loaded = None

    def loaded(self):
        """Every value the code makes with a ``movw``/``movt`` pair or loads from a literal pool
        (built once: Batman 66 walks back from 2000 table pointers)."""
        if self._loaded is None:
            prog = self.prog
            got = set()
            for reg in range(13):
                got.update(prog.movwt_values(reg))
            tw = prog.tw
            idx = np.nonzero((tw & 0x0F7F0000) == 0x051F0000)[0]
            imm = (tw[idx] & 0xFFF).astype(np.int64)
            up = (tw[idx] & 0x00800000) != 0
            pool = prog.tlo + 4 * idx.astype(np.int64) + 8 + np.where(up, imm, -imm)
            for va in pool.tolist():
                w = prog.word(va)
                if w is not None:
                    got.add(w)
            self._loaded = got
        return self._loaded

    def of_code(self, va):
        fi = self.graph.file_of(va)
        m = self.mode_of.get(fi) if fi is not None else None
        return (m, "file") if m else ("", "")

    def of_table(self, wva):
        """The mode whose files alone load the address of the table holding the pointer at
        *wva* (walked back to the nearest word the code loads, as :class:`.clip_modes._Owners`
        does)."""
        from .clip_modes import TABLE_BACK
        if wva in self._table:
            return self._table[wva]
        got = ("", "")
        loaded = self.loaded()
        for k in range(TABLE_BACK):
            if wva - 4 * k not in loaded:
                continue
            refs = self.prog.references(wva - 4 * k)
            if not refs:
                continue
            owners = {self.of_code(r)[0] for r in refs}
            if len(owners) == 1 and "" not in owners:
                got = (owners.pop(), "table")
            break
        self._table[wva] = got
        return got


def _files_of(graph, records):
    """``{file: {mode}}``: each file's modes - a file is a mode's when the records written in it
    (*records*, ``{function: Counter}``; a function naming two modes counts for neither) are of
    that mode alone, and outnumber the file's records of no mode. Stranger Things LE 1.13's
    pop bumper file writes 2 of Super Pop Bumpers and 4 of none (pop hits, dart levels: its clips
    show in normal play), Bust Out's 10 and 2."""
    per = collections.defaultdict(collections.Counter)
    for f, c in records.items():
        if len([k for k in c if k]) > 1:
            continue
        fi = graph.file_of(f)
        if fi is not None:
            per[fi].update(c)
    out = {}
    for fi, c in per.items():
        ms = [k for k in c if k]
        if len(ms) == 1:
            out[fi] = set(ms) if c[ms[0]] > c[""] else set()
        elif ms:
            out[fi] = set(ms)
    return out


def owners(S, prog, model=None, modes=None, anchors=None):
    """``(FileOwners, {mode: label})`` for the program, or ``(None, {})`` when it has no files
    (no static initialisers) or no mode evidence. *modes* and *anchors* are the C++ reading's
    (:func:`.clip_modes._mode_classes`, :func:`.clip_modes._anchors`); without them the program
    is read as plain C."""
    from .clip_modes import _inits, mode_label
    inits = _inits(S, prog)
    if not inits:
        return None, {}
    graph = _Graph(prog, inits)
    if modes:
        files = _files_of(graph, {f: collections.Counter({m: 1})
                                  for f, m in (anchors or {}).items()})
        for fi, ms in effect_files(prog, model, modes, graph).items():
            files.setdefault(fi, set()).update(ms)
        labels = {m: mode_label(m) for m in modes}
    else:
        keys, recs = c_modes(prog)
        if not keys:
            return None, {}
        files = _files_of(graph, recs)
        labels = {k: c_label(k) for k in keys}
    if not files:
        return None, {}
    return FileOwners(prog, graph, files), labels
