"""The game's own modes on a title whose rules are plain C (Beatles, Batman, Metallica, ...).

These builds have no C++ rule classes, so there are no mode objects to read. What every Stern
title carries is enough to list its modes and the numbers an operator can already set:

* the operator settings (``AD_*``, :class:`.adjustments.AdjustmentTable`): on these titles a
  mode's timer, shot count, spin count, ball save and balls in play ARE operator settings
  (``AD_MODE_DRIVE_MY_CAR_TIMER``), whose compiled default is the most universally editable
  number on any title - the word the Defaults tab writes;
* the audits (``AUD_*``): one ``..._STARTED`` audit per mode names it, and the game counts it
  when the mode starts. The audit id the code passes is the HIGH half of the descriptor's
  type word (``+0x12`` in a 28-byte descriptor, ``+0x0a`` in a 16-byte one), not the name's
  place in the name array (only a byte-sized descriptor uses the place);
* ``get_adjustment`` and the audit counter, located structurally: the function that indexes
  the settings table and whose callers most often pass a constant setting id, and the callee
  handed the most distinct audit ids with a count of 1 (``audit_add(id, 1)``).

A mode's award is built in code on these titles (a level times a base, a per-song record), so
a constant its start hands a score function is listed as ``uncertain``: read-only, with the
reason. Only the operator settings are editable.
"""

import collections
import re

import numpy as np

from . import stock_scan as S
from .title_reader import Cancelled
from .stock_scan import Val

# audits whose names end _STARTED but are not modes
_NOT_MODES = ("TOTAL", "CONNECTIVITY", "PLAYER", "MEDIA", "MACHINE", "AU_", "HISTO",
              "OVERCURRENT", "AVERAGE", "REPLAY", "SPECIAL_PERCENT", "HIGH_SCORE", "FREE_GAME",
              "BANK_RESET", "GAMES_STARTED", "BALLS_STARTED", "GAME_STARTED", "JACKPOT")
_EVENT_SUFFIXES = ("_STARTED", "_STARTS", "_COMPLETED", "_COMPLETES", "_LEVEL5", "_JACKPOT",
                   "_SUPER_JACKPOT", "_BALL_ADDED", "_RESTARTS", "_COMPLETE")
# the end of a setting's name -> the row's role (in the order they are tried)
_ROLES = (("_BALL_SAVE_SECONDS", "ball_save"), ("_BALL_SAVE_TIMER", "ball_save"),
          ("_BALL_SAVE", "ball_save"), ("_TIMER", "timer"), ("_TIME", "timer"),
          ("_SECONDS", "timer"), ("_SHOTS", "shots"), ("_SPINS", "spins"), ("_HITS", "hits"),
          ("_BALLS_IN_PLAY", "balls"), ("_BALLS", "balls"), ("_DIFFICULTY", "difficulty"),
          ("_LEVELS", "levels"))


def name_array(prog, prefix):
    """The packed ``char*[]`` of *prefix* names (id-indexed, 0 = the INVALID slot): the
    longest run of consecutive words pointing at such strings, walked from its start so a slot
    that isn't a name keeps the index aligned. ``[]`` when there is none."""
    rx = re.compile(re.escape(prefix) + rb"[A-Z0-9_]{2,80}\x00")
    names = {}
    for lo, hi in prog.scan_ranges():
        for m in rx.finditer(prog.b, lo, hi):
            va = prog.off2va(m.start())
            if va is not None:
                names[va] = prog.b[m.start():m.end() - 1].decode("latin1")
    if not names:
        return []
    keys = np.fromiter(names.keys(), dtype=np.uint32, count=len(names))
    best = (0, None)
    for off, va, fsz, _msz, _flg in prog.loads:
        base = (off + 3) & ~3
        n = (off + fsz - base) // 4
        if n <= 0:
            continue
        words = np.frombuffer(prog.b, dtype="<u4", count=n, offset=base)
        hit = np.isin(words, keys).astype(np.int8)
        if not hit.any():
            continue
        # the longest run of consecutive hits
        d = np.diff(np.concatenate(([0], hit, [0])))
        starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        k = int(np.argmax(ends - starts))
        if ends[k] - starts[k] > best[0]:
            best = (int(ends[k] - starts[k]), va + (base - off) + 4 * int(starts[k]))
    if best[1] is None:
        return []
    out, va = [], best[1]
    pre = prefix.decode()
    while len(out) < 8000:
        w = prog.word(va)
        if w is None:
            break
        if w in names:
            out.append(names[w])
        else:
            s = prog.cstring(w) if w else None
            if out and (not s or not s.startswith(pre)):
                break
            out.append(s or "")
        va += 4
    return out


def descriptor_record(prog, count):
    """``(table VA, count, elem)`` of the ``{live, table, count, elem, ...}`` record whose
    count is *count* and whose table is an address, or None."""
    for off, _va, fsz, _msz, _flg in prog.loads:
        base = (off + 3) & ~3
        n = (off + fsz - base) // 4
        if n < 5:
            continue
        w = np.frombuffer(prog.b, dtype="<u4", count=n, offset=base)
        cand = np.nonzero((w[2:n - 2] == count) & (w[3:n - 1] >= 8) & (w[3:n - 1] <= 96)
                          & (w[3:n - 1] % 4 == 0))[0]
        for i in cand.tolist():
            table, elem = int(w[i + 1]), int(w[i + 3])
            if prog.va2off(table) is not None:
                return table, count, elem
    return None


def audit_ids(prog):
    """``(names, {engine id: AUD name}, record)``: the audit names, and the id the code passes
    for each (the descriptor's type word's high half; the name's place for a byte-sized
    descriptor or when there is no record)."""
    names = name_array(prog, b"AUD_")
    by_index = {i: n for i, n in enumerate(names) if n}
    rec = descriptor_record(prog, len(names)) if names else None
    if rec is None:
        return names, by_index, None
    table, count, elem = rec
    idoff = {28: 0x12, 16: 0x0A}.get(elem)
    by_desc = {}
    if idoff is not None:
        for i in range(min(count, len(names))):
            hid = prog.u16(table + i * elem + idoff)
            if hid and names[i]:
                by_desc.setdefault(hid, names[i])
    return names, (by_desc or by_index), rec


def find_audit_add(prog, ids):
    """The audit counter ``audit_add(id, n)``: the callee handed the most distinct audit ids
    in r0 with a count of 1 in r1 (Beatles 1.29: 119 ids, the next callee 7). None when no
    callee gets at least ten."""
    if not ids:
        return None
    _s, tgts, v0 = prog.call_constants(0)
    _s, _t, v1 = prog.call_constants(1)
    ok = np.isin(v0, np.array(sorted(ids), dtype=np.int64)) & (v1 == 1)
    seen = collections.defaultdict(set)
    for t, v in zip(tgts[ok].tolist(), v0[ok].tolist()):
        seen[t].add(v)
    if not seen:
        return None
    t, vals = max(seen.items(), key=lambda kv: len(kv[1]))
    return t if len(vals) >= 10 else None


def mode_key(aud_name):
    """``AUD_MODE_DRIVE_MY_CAR_STARTED`` -> ``DRIVE_MY_CAR``."""
    s = aud_name
    for p in ("AUD_MODE_", "AUD_"):
        if s.startswith(p):
            s = s[len(p):]
            break
    for suf in _EVENT_SUFFIXES:
        if s.endswith(suf):
            return s[:-len(suf)]
    return s


_MULTIBALL_AUDIT = re.compile(r"^AUD_(.+?_(?:MULTIBALL|MB))S?(?:_MULTIBALL|_PLAYED|_STARTED|_STARTS"
                              r"|_START)?$")
_MODE_AUDIT = re.compile(r"^AUD_MODE_([A-Z0-9_]+?)$")


def mode_audits(names):
    """``[(mode key, audit name)]`` - every mode an audit counts the start of, in the audits'
    order: ``AUD_<MODE>_STARTED`` / ``_STARTS`` / ``_START``, a multiball's own audit
    (``AUD_VILLAIN_MULTIBALLS``, ``AUD_MAIN_MULTIBALL_MULTIBALL``, ``AUD_MISSION_MULTIBALLS_PLAYED``)
    and a bare ``AUD_MODE_<MODE>``."""
    out, seen = [], set()
    for name in names:
        if not name or any(w in name for w in _NOT_MODES):
            continue
        key = None
        if name.endswith(("_STARTED", "_STARTS", "_START")):
            key = mode_key(name[:-len("_START")] + "_STARTED" if name.endswith("_START")
                           else name)
        else:
            m = _MULTIBALL_AUDIT.match(name) or _MODE_AUDIT.match(name)
            if m and not m.group(1).endswith(_EVENT_SUFFIXES):
                key = m.group(1)
        if key and key not in seen:
            seen.add(key)
            out.append((key, name))
    return out


def _words(s):
    """A name's words, with ``MB`` read as ``MULTIBALL``."""
    return ["MULTIBALL" if w == "MB" else w for w in s.split("_") if w]


def settings_for(table, key):
    """``[(role, AD name, id)]``: the operator settings whose name holds the mode's key (or
    its initials, for a key of three words or more: ``AD_AML_...`` for All My Loving) and
    ends in a timer / shots / spins / ball save / balls / difficulty word, in id order."""
    toks = _words(key)
    joined = "_".join(toks)
    initials = "".join(t[0] for t in toks) if len(toks) >= 3 else None
    out = []
    for name, idx in sorted(table.by_name.items(), key=lambda kv: kv[1]):
        u = name[3:] if name.startswith("AD_") else name
        parts = _words(u)
        if joined not in "_".join(parts) and not all(t in parts for t in toks) \
                and not (initials and initials in parts):
            continue
        for suf, role in _ROLES:
            if u.endswith(suf):
                out.append((role, name, idx))
                break
    return out


def _const_site(prog, site, reg, n=8):
    """``Val`` for the constant a mov/movw(+movt)/mvn puts in *reg* before the call at *site*,
    or None (the same rules as :meth:`.stock_scan.Program.const_before`)."""
    hi = None
    for k in range(1, n + 1):
        va = site - 4 * k
        w = prog.word(va)
        if w is None:
            return None
        d = S.decode(w, va)
        if d[0] in ("bl", "blx"):
            return None
        if d[0] == "other":
            if reg in d[1]:
                return None
            continue
        if len(d) > 2 and d[1] == reg and d[0] in ("movw", "movt", "mov", "mvn", "ldrlit", "movr",
                                                    "addi", "subi", "andsi", "ldri"):
            if d[-1] != 0xE:
                return None
            if d[0] == "movt":
                hi = (va, w, d[2])
                continue
            if d[0] == "movw":
                if hi:
                    return Val(hi[2] << 16 | d[2], [(va, w, "movw"), (hi[0], hi[1], "movt")])
                return Val(d[2], [(va, w, "movw")])
            if d[0] in ("mov", "mvn"):
                how = "imm" if d[0] == "mov" else "mvn"
                if hi and d[2] <= 0xFFFF:
                    return Val(hi[2] << 16 | d[2], [(va, w, how), (hi[0], hi[1], "movt")])
                return None if hi else Val(d[2], [(va, w, how)])
            return None
    return None


def read(prog, step=None, cancel=None):
    """:class:`.stock_scan.Reading` of a plain-C title. *step(fraction, text)* reports
    progress; *cancel()* returning True raises :class:`Cancelled`."""
    say = step or (lambda f, t="": None)

    def check():
        if cancel is not None and cancel():
            raise Cancelled()

    reading = S.Reading("c")
    say(0.05, "Reading the operator settings")
    get_adj, table = S.find_get_adjustment(prog)
    if table is None:
        raise S.ScanError("this game program's operator settings can't be read")
    check()
    say(0.2, "Reading the audits")
    names, ids, _rec = audit_ids(prog)
    check()
    audit_add = find_audit_add(prog, ids)
    reading.engine = {"get_adjustment": get_adj, "audit_add": audit_add}
    name_to_id = {n: i for i, n in ids.items()}
    say(0.35, "Finding the modes")
    # where each mode's started audit is counted, and which settings the program reads where
    modes = mode_audits(names)
    started_site = {}
    if audit_add:
        for c in prog.callers(audit_add):
            aid = prog.const_before(c, 0)
            nm = ids.get(aid)
            for key, audit in modes if nm else ():
                if audit == nm:
                    started_site.setdefault(key, c)
    adj_site = {}
    if get_adj:
        for c in prog.callers(get_adj):
            v = _const_site(prog, c, 0)
            if v is not None and 0 < v.v < table.count:
                adj_site.setdefault(v.v, (c, v))
    check()
    if not modes:
        reading.notes.append("no mode audits (..._STARTED) in this game program")
    for i, (key, started) in enumerate(modes, 1):
        check()
        say(0.4 + 0.55 * i / max(1, len(modes)), "Mode %d of %d" % (i, len(modes)))
        m = S.ModeRead(i, key.lower(), S.readable(" ".join(_words(key))))
        m.facts.append("# the mode's own audit: %s (id %s)" % (
            started, name_to_id.get(started, "?")))
        site = started_site.get(key)
        if site:
            m.facts.append("start start: audit %s counted at 0x%x, in the function at 0x%x" % (
                started, site, prog.func_start(site)))
        for role, name, idx in settings_for(table, key):
            e = table.entry(idx)
            at = adj_site.get(idx)
            if at:
                kd, words = S.kind_of(at[1])
                where = "read at 0x%x (the id is %s)" % (at[0], S.fmt_kind(kd))
            else:
                words, where = [], "no constant-id read of it was found"
            m.add("%s.adjustment" % role, e["default"], ("adj", name, idx), words, "adjustment",
                  "the operator setting %s, %s; range %d..%d" % (name, where, e["min"], e["max"]))
        if site:
            _start_awards(prog, m, site, audit_add, get_adj)
        reading.modes.append(m)
    S.settle_shared(reading)
    say(1.0, "")
    return reading


def _start_awards(prog, m, site, audit_add, get_adj):
    """Constants the function that counts the mode's start hands a score-like call (a 64-bit
    r2:r3 with r3 = 0, or r0), each an ``uncertain`` row: on these titles an award is usually
    built in code, so a constant there may be a part of it, or something else."""
    fn = prog.func_start(site)
    t = prog.facts(fn)
    for call in t.calls:
        if call["target"] in (audit_add, get_adj) or call.get("tail"):
            continue
        a = call["args"]
        lo, hi = a.get("r2"), a.get("r3")
        v = None
        if isinstance(lo, Val) and isinstance(hi, Val) and hi.v == 0 and lo.fresh(call["va"]):
            v = lo
        elif isinstance(a.get("r0"), Val) and a["r0"].fresh(call["va"]) and "r1" not in a:
            v = a["r0"]
        if v is None or v.v < 1000 or v.v % 250 or v.v > 1_000_000_000:
            continue
        kd, words = S.kind_of(v)
        if kd[0] == "code":
            continue
        m.add("start.score_add", v.v, kd, words, "uncertain",
              "a constant the function that starts this mode hands 0x%x at 0x%x; on this "
              "title an award is built in code, so it is not certain this is the mode's award"
              % (call["target"], call["va"]))
