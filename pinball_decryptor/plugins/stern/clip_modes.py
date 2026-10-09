"""PAD-444: which of the game's own modes plays each in-game clip, and a mode's OWN copy of a
clip it shares with another mode.

A field report (Godzilla retheme): the battle vs Gigan and the Ghidorah and Gigan tag team play
the same two clips, so whatever footage a retheme puts in them shows in both battles. The ask was
to see the clips of each mode and to point a mode at new footage of its own.

HOW THE GAME PLAYS A CLIP. Every in-game clip is played by NAME (:mod:`.video_bank`): the
in-game video bank maps a name to a clip file, and the code holds the ADDRESS of the name, a C
string in the game program - a ``movw``/``movt`` pair, a literal-pool word, or a pointer in a
table (:func:`.progreloc.reference_census` finds all three). So "which mode plays this clip" is
"whose code holds the address of its name", and a mode's own copy is three things:

* the new name, a C string in the game program's extension segment (where longer program text
  already goes, :func:`.progreloc.extension_segment`), and that mode's references - only
  those - pointed at it (:func:`program_plan`);
* the new name in the bank, a clip the card never had (:func:`.video_bank.add_clip`);
* its file: the project's copy of the shared clip, or whatever replaces it on the Video tab.

Every other mode keeps the shared clip. Nothing is moved: the shared clip, its name and every
other reference stay where they are, so a card built without the copy is the card it was.

WHOSE CODE (a C++ title; a title whose rules are plain C has no mode classes, and this reading
then names no mode at all). A mode is a class ``cmode_<name>``, its screens are display-layer
classes ``BDL<Name>...`` (paired by name, as the SDK's stock-mode reader pairs them), the
functions of one source file lie together, and the file's static initialiser - the function
that builds its global objects, often holding clip names - is at the end of the file. A code
reference belongs to a mode when its function is

* ``own``: one of the mode's or its display layers' own virtual functions;
* ``init``: a static initialiser (``.init_array``) right after a run of the mode's own
  virtuals (the file it ends);
* ``unit``: anything else whose nearest own virtuals before and after it are both the mode's.

A pointer in a table belongs to a mode (``table``) when every function that loads the table's
address is the mode's. Anything else names no mode (main play, attract, the battle select
screen, a table several modes read) and is never offered a copy.

MEASURED on stock Godzilla Pro and Premium/LE 1.16: 481 of the bank's names are in the program,
three of them played by two modes - ``gigan_ghidorah_vs_godzilla13`` (both battles' static
initialisers) and ``gigan_ghidorah_vs_godzilla17`` (the battle vs Gigan's initialiser and the
tag team's background table), and ``PlanetX_Normal_Loop`` (Planet X multiball and O2
destroyer). The global objects each of those initialisers builds are used by its own battle's
functions and no other's, which is what makes ``init`` safe.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import os
import struct
from dataclasses import dataclass, field

#: bumped when what :func:`analyse` reads changes; older cached readings are read again
#: (4: each clip's sounds, :mod:`.clip_sounds`)
READ_REV = 4
#: the most clip-name characters a project file keeps (engine._sanitize_title's cap)
NAME_MAX = 64
#: how far back from a table's pointer the table's start is looked for (words)
TABLE_BACK = 256
#: how many of one mode's own virtuals in a row before a static initialiser make it that
#: mode's file's (a mode's file has dozens; a stray one in another file stands alone)
INIT_RUN = 3
#: how far after a clip name's ``movw`` its ``movt`` is looked for (instructions): the
#: reference census pairs within 6, and the Gigan battle's initialiser loads seven names with
#: their halves 8 apart (LE 1.16 0x91528 / 0x91548, gigan_ghidorah_vs_godzilla60), which the
#: emulator showed it plays
WIDE_PAIR = 24
#: the longest string a clip name is looked for at the end of: the linker keeps one copy of
#: a name that ends a longer string (Godzilla's "tilt" is "Avertisseur de tilt" + 16)
HOST_MAX = 256
#: the most scene directories :func:`read_card` reads for a bank, most clips first (the
#: in-game bank holds most of a title's clips; a title with a clip in every scene is not
#: read scene by scene)
BANKS_MAX = 12


class ClipModesError(ValueError):
    """A copy that can't be made; the message is a sentence."""


@dataclass
class Ref:
    """One place in the game program that names a clip."""
    kind: str               # a progreloc kind: lone, group, movw_a32, movw_t32
    offs: list              # file offsets of the word(s) / instruction(s) to rewrite
    at: int                 # the VA of the first of them
    mode: str = ""          # the cmode class whose code it is, "" for none
    how: str = ""           # own / init / unit / table

    def to_json(self):
        return [self.kind, list(self.offs), self.at, self.mode, self.how]

    @classmethod
    def from_json(cls, v):
        return cls(v[0], list(v[1]), int(v[2]), v[3], v[4])


@dataclass
class Reading:
    """What :func:`analyse` read off one game program."""
    sha1: str = ""
    labels: dict = field(default_factory=dict)    # cmode class -> "Battle vs Gigan"
    refs: dict = field(default_factory=dict)      # clip name -> [Ref]

    def modes_of(self, name):
        """The classes of the modes that play *name*, in label order (none: [])."""
        got = {r.mode for r in self.refs.get(name, ()) if r.mode}
        return sorted(got, key=lambda c: (self.labels.get(c, c).lower(), c))

    def refs_of(self, name, mode):
        return [r for r in self.refs.get(name, ()) if r.mode == mode]

    def elsewhere(self, name):
        """Whether code that is no one mode's (main play, attract, the battle select screen)
        names *name* too."""
        return any(not r.mode for r in self.refs.get(name, ()))

    def label(self, mode):
        return self.labels.get(mode) or mode_label(mode)

    def to_json(self):
        return {"sha1": self.sha1, "labels": dict(self.labels),
                "refs": {n: [r.to_json() for r in rs] for n, rs in self.refs.items()}}

    @classmethod
    def from_json(cls, d):
        return cls(d.get("sha1", ""), dict(d.get("labels") or {}),
                   {n: [Ref.from_json(r) for r in rs] for n, rs in (d.get("refs") or {}).items()})


def mode_label(cls):
    """``cmode_battle_vs_ghidorah_and_gigan`` -> ``Battle vs Ghidorah and Gigan``, as the
    Modes tab names the game's own modes (:class:`.stock_modes.Mode`)."""
    from .stock_modes import Mode
    return Mode(id=0, cls=cls).name


def mode_slug(cls):
    """The part of a mode's class a copy's name ends with: ``battle_vs_gigan``."""
    return cls[6:] if cls.startswith("cmode_") else cls


# ---- reading ---------------------------------------------------------------------------------
def _mode_classes(S, model):
    """The concrete mode classes: ``cmode_*`` that no other mode class derives from, less the
    manager and the ``_null`` stand-ins."""
    allc = [c for c in model if c.startswith("cmode_") and c != "cmode_manager"]
    bases = set()
    for c in allc:
        bases.update(S.chain_of(model, c))
    return [c for c in allc if c not in bases and not c.endswith("_null")]


def _layers(model, modes):
    """``{BDL layer class: mode class}``: a layer goes to the mode with the LONGEST name it
    starts with (the SDK's ``display_layers``: BDLKingOfTheMonstersMultiballStart is the
    multiball's, not king of the monsters')."""
    import re
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())          # noqa: E731
    keys = sorted(((norm(c[6:]), c) for c in modes), key=lambda kc: -len(kc[0]))
    out = {}
    for layer in model:
        if not layer.startswith("BDL"):
            continue
        n = norm(layer[3:])
        for k, c in keys:
            if k and n.startswith(k):
                out[layer] = c
                break
    return out


def _anchors(S, prog, model, modes, layers):
    """``{function VA: mode class}`` for every own virtual of a mode or its display layers that
    exactly one mode has."""
    got = {}
    for cls in list(modes) + list(layers):
        owner = layers.get(cls, cls)
        try:
            _base, own = S.own_slots(prog, model, cls)
        except Exception:                                   # noqa: BLE001 - a class the scan can't read
            continue
        for _k, f in own:
            if f and prog.in_text(f):
                got.setdefault(f, set()).add(owner)
    return {f: next(iter(o)) for f, o in got.items() if len(o) == 1}


def _inits(S, prog):
    """The sorted VAs the static initialisers start at: every ``.init_array`` entry, and the
    function a one-instruction ``b`` stub there branches to."""
    sec = prog.sections.get(".init_array")
    if not sec:
        return []
    addr, off, size = sec
    out = set()
    for i in range(min(size, 1 << 16) // 4):
        if off + 4 * i + 4 > len(prog.b):
            break
        w = struct.unpack_from("<I", prog.b, off + 4 * i)[0]
        if not prog.in_text(w):
            continue
        out.add(w)
        x = prog.word(w)
        if x is not None and (x & 0x0F000000) == 0x0A000000 and (x >> 28) == 0xE:
            out.add(S.branch_target(x, w))
    return sorted(out)


class _Owners:
    def __init__(self, S, prog, anchors, inits):
        self.S, self.prog = S, prog
        self.anchors = anchors
        self.avas = sorted(anchors)
        self.inits = inits
        self._table = {}

    def of_function(self, fn):
        """``(mode class, how)`` of the function starting at *fn*, ``("", "")`` for none."""
        a = self.anchors.get(fn)
        if a:
            return a, "own"
        i = bisect.bisect_right(self.avas, fn) - 1
        prev = self.anchors[self.avas[i]] if i >= 0 else ""
        nxt = self.anchors[self.avas[i + 1]] if i + 1 < len(self.avas) else ""
        # a prologue can start a few instructions before the push (0xa3b9c on LE 1.16)
        j = bisect.bisect_left(self.inits, fn - 16)
        if j < len(self.inits) and self.inits[j] <= fn:
            # the file it ends: the run of one mode's own virtuals right before it, and a
            # run, not a stray one (main play's initialiser follows a tiny virtual of the
            # Mechagodzilla multiball that lives in its file, Pro 1.16 0x475fc)
            run = 0
            while i - run >= 0 and self.anchors[self.avas[i - run]] == prev:
                run += 1
            return (prev, "init") if prev and run >= INIT_RUN else ("", "")
        if prev and prev == nxt:
            return prev, "unit"
        return "", ""

    def of_code(self, va):
        return self.of_function(self.prog.func_start(va))

    def of_table(self, wva):
        """The mode whose functions alone load the address of the table holding the pointer
        at *wva*: walk back to the nearest word whose address the code loads."""
        if wva in self._table:
            return self._table[wva]
        got = ("", "")
        for k in range(TABLE_BACK):
            refs = self.prog.references(wva - 4 * k)
            if not refs:
                continue
            owners = {self.of_code(r)[0] for r in refs}
            if len(owners) == 1 and "" not in owners:
                got = (owners.pop(), "table")
            break
        self._table[wva] = got
        return got


def _spans(raw, names):
    """``([(file offset, text)], {(file offset, delta): name})``: the C strings that hold one
    of *names*, whole or as their tail (the reference census reads each string once), and
    which name each place in them is."""
    hosts, at = {}, {}
    for n in names:
        try:
            key = n.encode("latin1") + b"\0"
        except UnicodeEncodeError:
            continue
        o = raw.find(key)
        while o >= 0:
            z = raw.rfind(b"\0", max(0, o - HOST_MAX), o)
            host = raw[z + 1:o + len(key) - 1] if z >= 0 else b""
            if z >= 0 and host and all(0x20 <= c <= 0x7E for c in host):
                hosts[z + 1] = host.decode("latin1")
                at[(z + 1, o - z - 1)] = n
            o = raw.find(key, o + 1)
    return sorted(hosts.items()), at


def _wide_pairs(S, prog, raw, spans, at_name, census):
    """Add to *census* the ``movw``/``movt`` pairs naming a clip whose halves are further apart
    than the census looks (:data:`WIDE_PAIR`): the same register, nothing between them writing
    it, and no call between them when it is a register a call may change."""
    import numpy as np
    from . import progreloc
    seen = {r["offs"][0] for refs in census.values() for r in refs}
    want = {}                                       # VA -> (host offset, delta)
    for off, _text in spans:
        va = prog.off2va(off)
        if va is None:
            continue
        for (h, d), _n in at_name.items():
            if h == off:
                want[va + d] = (off, d)
    if not want:
        return
    lows = np.array(sorted({v & 0xFFFF for v in want}), dtype=np.uint32)
    for seg in progreloc.load_segments(raw):
        if not seg[4] & progreloc.PF_X:
            continue
        off0, n = seg[1], seg[2] // 4
        a = np.frombuffer(raw[off0:off0 + n * 4], dtype="<u4")
        cond_ok = (a >> 28) != 0xF
        is_w = ((a & 0x0FF00000) == 0x03000000) & cond_ok
        imm = ((a >> 4) & 0xF000) | (a & 0xFFF)
        for i in np.flatnonzero(is_w & np.isin(imm, lows)).tolist():
            if off0 + 4 * i in seen:
                continue
            rd = int((a[i] >> 12) & 0xF)
            for j in range(i + 1, min(i + 1 + WIDE_PAIR, n)):
                w = int(a[j])
                if (w >> 28) != 0xF and (w & 0x0FF00000) == 0x03400000 and (w >> 12) & 0xF == rd:
                    va = int(imm[i]) | (((w >> 4) & 0xF000 | (w & 0xFFF)) << 16)
                    hit = want.get(va)
                    if hit is not None:
                        census.setdefault(hit[0], []).append(
                            {"kind": progreloc.KIND_A32, "delta": hit[1],
                             "offs": [off0 + 4 * i, off0 + 4 * j], "va": va})
                    break
                if (w & 0x0E000000) == 0x0A000000 and (w >> 28) != 0xF and rd in (0, 1, 2, 3, 12, 14):
                    break                           # a call or branch may change it
                regs = S._regs_at(prog, seg[0] + 4 * j)
                if regs is None or rd in regs[1]:
                    break                           # written between: not a pair


def analyse(elf, names, ctx=None):
    """:class:`Reading` of the game program *elf* (bytes) for the clip *names*. Read-only.
    *ctx*, a dict when given, gets the ``prog`` it read, so :mod:`.clip_sounds` reads the same
    program without building it again."""
    from . import stock_scan as S
    elf = bytes(elf)
    out = Reading(sha1=hashlib.sha1(elf).hexdigest())
    try:
        prog = S.Program(elf)
    except S.ScanError:
        return out
    if ctx is not None:
        ctx["prog"] = prog
    model = S.class_model(prog)
    modes = _mode_classes(S, model)
    if not modes:
        return out
    layers = _layers(model, modes)
    owners = _Owners(S, prog, _anchors(S, prog, model, modes, layers), _inits(S, prog))
    out.refs = clip_refs(prog, elf, names, owners)
    for rs in out.refs.values():
        for r in rs:
            if r.mode and r.mode not in out.labels:
                out.labels[r.mode] = mode_label(r.mode)
    return out


def clip_refs(prog, elf, names, owners=None):
    """``{clip name: [Ref]}``: every place in the game program *elf* (its
    :class:`.stock_scan.Program` *prog*) that names one of *names*, in address order, each
    given its mode by *owners* (none without: a title whose rules are plain C)."""
    from . import progreloc
    from . import stock_scan as S
    spans, at_name = _spans(elf, sorted(set(names)))
    census = progreloc.reference_census(elf, spans)
    _wide_pairs(S, prog, elf, spans, at_name, census)
    text_hi = prog.code_end
    out = {}
    for off, refs in census.items():
        for ref in refs:
            name = at_name.get((off, ref["delta"]))
            if name is None:
                continue                 # another part of the string, not a clip's name
            first = ref["offs"][0]
            at = prog.off2va(first)
            if at is None:
                continue
            mode, how = "", ""
            if owners is not None:
                code = ref["kind"] in (progreloc.KIND_A32, progreloc.KIND_T32) or (
                    prog.tlo <= at < text_hi)
                mode, how = owners.of_code(at) if code else owners.of_table(at)
            out.setdefault(name, []).append(Ref(ref["kind"], list(ref["offs"]), at, mode, how))
    for rs in out.values():
        rs.sort(key=lambda r: r.at)
    return out


# ---- a mode's own copy -----------------------------------------------------------------------
def own_name(clip, mode, taken=()):
    """The name a copy of *clip* for *mode* gets: ``<clip>_<mode slug>``, shortened to
    :data:`NAME_MAX` characters, and numbered when *taken* has it already."""
    slug = mode_slug(mode)
    base = "%s_%s" % (clip, slug)
    if len(base) > NAME_MAX:
        room = NAME_MAX - len(clip) - 1
        base = "%s_%s" % (clip, slug[:room]) if room >= 4 else clip[:NAME_MAX - 6] + "_own"
    name, n = base, 2
    taken = set(taken)
    while name in taken:
        tail = "_%d" % n
        name = base[:NAME_MAX - len(tail)] + tail
        n += 1
    return name


def copy_of(name, names, labels):
    """``(clip, mode)`` when *name* is a copy :func:`own_name` made (the name of another clip
    in *names*, ``_`` and a mode's slug in *labels*), else None. How a card built with a copy,
    and extracted again, still knows it is one."""
    for mode in sorted(labels, key=lambda m: -len(mode_slug(m))):
        tail = "_" + mode_slug(mode)
        if name.endswith(tail) and name[:-len(tail)] in names:
            return name[:-len(tail)], mode
    return None


def _cstring_va(raw, prog_maps, text):
    """The VA of a whole C string equal to *text* already in *raw*, or None."""
    off2va = prog_maps
    key = b"\0" + text.encode("latin1") + b"\0"
    o = raw.find(key)
    while o >= 0:
        va = off2va(o + 1)
        if va is not None:
            return va
        o = raw.find(key, o + 1)
    return None


@dataclass
class ProgramPlan:
    writes: list = field(default_factory=list)    # [(file offset, bytes)]
    blob: bytes = b""                              # the new names, for base_va
    lines: list = field(default_factory=list)     # what the log says, one per copy
    done: list = field(default_factory=list)      # the records whose mode now plays the copy
    skipped: list = field(default_factory=list)   # (record, why)
    moves: list = field(default_factory=list)     # (Ref, the VA it now encodes)


def program_plan(elf, records, names, base_va, reading=None):
    """Point each record's mode at its own clip in the game program *elf*.

    *records* are :func:`records` entries (``name``, ``clip``, ``mode``, ``state``); *names*
    every clip name of the card's banks; *base_va* where :attr:`ProgramPlan.blob` will be
    mapped (the first free byte of the extension segment). A record whose mode already
    plays its copy (a card an earlier build made) needs no write, and a copy put back
    (``state == "shared"``) points the mode at the shared clip again."""
    from . import progreloc
    raw = bytes(elf)
    want = set(names)
    for r in records:
        want.update((r["name"], r["clip"]))
    reading = reading or analyse(raw, want)
    segs = progreloc.load_segments(raw)
    off2va, _va2off = progreloc.seg_maps(segs)
    plan = ProgramPlan()
    blob = bytearray()
    placed = {}

    def address(text):
        va = placed.get(text) or _cstring_va(raw, off2va, text)
        if va is None:
            va = base_va + len(blob)
            blob.extend(text.encode("latin1") + b"\0")
            blob.extend(bytes(-len(blob) % 4))
        placed[text] = va
        return va

    for rec in records:
        name, clip, mode = rec["name"], rec["clip"], rec["mode"]
        label = reading.label(mode)
        back = rec.get("state") == "shared"
        src, dst = (name, clip) if back else (clip, name)
        moving = reading.refs_of(src, mode)
        there = reading.refs_of(dst, mode)
        if not moving:
            if there:
                plan.done.append(rec)
                continue
            why = ("the game program has no place where %s plays %s" % (label, src))
            plan.skipped.append((rec, why))
            continue
        va = address(dst)
        for ref in moving:
            plan.writes += progreloc.retarget_writes(
                raw, {"kind": ref.kind, "offs": ref.offs}, va)
            plan.moves.append((ref, va))
        plan.done.append(rec)
        plan.lines.append(
            "%s plays %s again (%d place(s) in the game program)" % (label, clip, len(moving))
            if back else
            "%s plays a clip of its own, %s, instead of sharing %s (%d place(s) in the "
            "game program)"
            % (label, name, clip, len(moving)))
    plan.blob = bytes(blob)
    return plan


def check_program(elf, plan):
    """Raise :class:`ClipModesError` unless *elf* with *plan*'s writes applied encodes, at every
    reference the plan moves, the address it was moved to - and no write lands on another's
    bytes."""
    from . import progreloc
    buf = bytearray(elf)
    seen = set()
    for off, b in plan.writes:
        span = set(range(off, off + len(b)))
        if span & seen:
            raise ClipModesError("two of the copies' writes overlap at file offset 0x%x" % off)
        seen |= span
        buf[off:off + len(b)] = b
    raw = bytes(buf)
    for ref, va in plan.moves:
        got = progreloc.reference_value(raw, {"kind": ref.kind, "offs": ref.offs})
        if got != va:
            raise ClipModesError("the game program does not read back as planned at 0x%x"
                                 % ref.at)
    return True


# ---- the bank --------------------------------------------------------------------------------
def bank_plan(bank, adds):
    """Add each ``(name, size)`` of *adds* the bank *bank* (a scene's bytes) does not hold yet.
    Returns ``(new bytes, [(name, path below scene.assets)])``."""
    from . import video_bank as VB
    have = {c.name for c in VB.parse(bank).library.entries}
    out = []
    for name, size in adds:
        if name in have:
            continue
        bank, info = VB.add_clip(bank, name, size)
        have.add(name)
        out.append((name, info["path"]))
    return bank, out


# ---- one Write -------------------------------------------------------------------------------
class WriteJob:
    """One Write's copies, shared by its two steps: the game program step
    (:meth:`plan_program`, inside the program-text step, since the new names go in the same
    extension segment) and the bank step (:meth:`bank_files`, beside the modes' clips). A
    copy whose program part did not happen gets no bank entry and no file either, so the
    card never names a clip it does not have."""

    def __init__(self, records, rows, banks):
        """*records* the project's (:func:`records`); *rows* its ``video/manifest.txt``
        (:func:`manifest_rows`); *banks* ``{bank dir: scene bytes}`` read off the card."""
        from . import video_bank as VB
        self.records = list(records)
        self.rows = dict(rows)
        self.banks = dict(banks)
        self.names = set()
        self.bank_of = {}                          # clip name -> bank dir
        self.path_of = {}                          # clip name -> its file below scene.assets
        for d, data in self.banks.items():
            for c in VB.parse(data).library.entries:
                self.names.add(c.name)
                self.bank_of.setdefault(c.name, d)
                self.path_of.setdefault(c.name, c.path)
        self.program = None                        # the ProgramPlan, once planned
        self.done = []
        self.why = ""                              # why no copy was made at all
        self.lines = []
        self.skipped = []                          # (record, why)

    def bank_dir(self, rec):
        """The scene directory (card path, leading slash) of the bank holding the shared clip."""
        d = self.bank_of.get(rec["clip"])
        if d:
            return d
        path = self.rows.get(rec.get("of") or "")
        return path.split("/scene.assets/", 1)[0] if path and "/scene.assets/" in path else ""

    def plan_program(self, raw, base_va):
        """The :class:`ProgramPlan` for the game program *raw*, its new names mapped at
        *base_va*; records the outcome."""
        ok = [r for r in self.records if self.bank_dir(r)]
        for r in self.records:
            if r not in ok:
                self.skipped.append((r, "its shared clip %s is in no video bank on this card"
                                     % r["clip"]))
        plan = program_plan(raw, ok, self.names, base_va)
        check_program(raw, plan)
        self.program = plan
        self.done = list(plan.done)
        self.lines += plan.lines
        self.skipped += plan.skipped
        return plan

    def fail(self, why):
        self.program, self.done, self.why = None, [], why

    def bank_files(self, project, scratch, source_of=None, banks=None):
        """``(replaced, new, lines)`` for the bank step: each bank that gains a copy,
        rewritten into *scratch* (``[(card rel, file)]``, no leading slash), and each copy's
        file at the path its bank now names. A copy the card already has (a build on an
        earlier build's card) goes over that card's file instead, unless the project's file
        IS that file (an extract of the card: the Video tab's own slot, written as any other).
        *source_of(rec, staged)* picks the file a copy goes on as (the project's staged file
        by default); *banks* ``{bank dir: bytes}`` overrides a bank the same build already
        rewrote (the modes' clips). Raises :class:`ClipModesError` when a copy's file is
        missing."""
        banks = dict(self.banks, **(banks or {}))
        wanted = {}
        replaced, new, lines = [], [], []
        for rec in self.done:
            if rec.get("state") == "shared":
                continue
            if rec["name"] in self.names and (rec.get("rel") or "") in self.rows:
                continue
            src = os.path.join(project, *(rec.get("rel") or "").split("/"))
            if not rec.get("rel") or not os.path.isfile(src):
                raise ClipModesError("the file of %s's own clip (%s) is not in the project"
                                     % (mode_label(rec["mode"]), rec.get("rel") or rec["name"]))
            if source_of is not None:
                src = source_of(rec, src) or src
            if rec["name"] in self.names:
                card = "%s/scene.assets/%s" % (self.bank_of[rec["name"]].strip("/"),
                                               self.path_of[rec["name"]])
                replaced.append((card, src))
                lines.append("%s's own clip %s is on this card already; the project's file "
                             "goes over it (%s)" % (mode_label(rec["mode"]), rec["name"], card))
                continue
            wanted.setdefault(self.bank_dir(rec), []).append((rec, src))
        for d, items in wanted.items():
            data, added = bank_plan(banks[d], [(r["name"], os.path.getsize(s)) for r, s in items])
            rel = d.strip("/") + "/scene.radium"
            out = os.path.join(scratch, *d.strip("/").split("/"), "scene.radium")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(data)
            replaced.append((rel, out))
            paths = dict(added)
            for rec, src in items:
                card = "%s/scene.assets/%s" % (d.strip("/"), paths[rec["name"]])
                new.append((card, src))
                lines.append("%s's own clip %s is a new clip in the video bank (%s)"
                             % (mode_label(rec["mode"]), rec["name"], card))
        return replaced, new, lines


# ---- the project's record --------------------------------------------------------------------
#: the key in ``.staged_changes.json``: ``[{"name", "clip", "mode", "rel", "of", "state"}]``
#: (``rel`` the copy's file, ``of`` the shared clip's, ``state`` "own" or "shared")
KEY = "own_clips"


def records(project):
    """The project's copies, as recorded (``[]`` for none)."""
    from ...core import staged_changes
    got = staged_changes.load(project).get(KEY) or []
    return [dict(r) for r in got if isinstance(r, dict) and r.get("name") and r.get("clip")
            and r.get("mode")]


def save_records(project, recs):
    from ...core import staged_changes
    data = staged_changes.load(project)
    if recs:
        data[KEY] = [dict(r) for r in recs]
    else:
        data.pop(KEY, None)
    staged_changes.save(project, data)


def pending(project):
    """How many copies the project's next Write has to make or put back."""
    return len(records(project))


def remove_copies(project):
    """Revert all: delete each copy's file the project made (one the card already has is a
    file of the extract, and stays) and forget every copy. Returns how many files went."""
    rows = manifest_rows(project)
    gone = 0
    for rec in records(project):
        rel = rec.get("rel") or ""
        if not rel or rel in rows or rec.get("state") == "shared":
            continue
        try:
            os.remove(os.path.join(project, *rel.split("/")))
            gone += 1
        except OSError:
            pass
    save_records(project, [])
    return gone


# ---- a card's clips, for the Video tab -------------------------------------------------------
@dataclass
class CardClips:
    """A card's clips and the modes that play them, keyed the way the project names them."""
    card: str = ""
    game: str = ""
    version: str = ""
    reading: Reading = field(default_factory=Reading)
    name_of: dict = field(default_factory=dict)    # project rel -> clip name
    bank_of: dict = field(default_factory=dict)    # clip name -> its bank's directory
    note: str = ""                                  # why there is nothing, in words
    #: clips of a bank the game plays by name that nothing in the program names: never shown
    unplayed: list = field(default_factory=list)
    #: the sounds each clip's code asks for (:class:`.clip_sounds.SoundReading`, a dict here
    #: until :attr:`sound_reading` reads it)
    sounds: dict = field(default_factory=dict)

    @property
    def sound_reading(self):
        from .clip_sounds import SoundReading
        return SoundReading.from_json(self.sounds)

    def modes_of_rel(self, rel):
        n = self.name_of.get(rel)
        return self.reading.modes_of(n) if n else []

    def to_json(self):
        return {"rev": READ_REV, "card": self.card, "game": self.game, "version": self.version,
                "reading": self.reading.to_json(), "name_of": dict(self.name_of),
                "bank_of": dict(self.bank_of), "note": self.note,
                "unplayed": list(self.unplayed), "sounds": dict(self.sounds)}

    @classmethod
    def from_json(cls, d):
        return cls(d.get("card", ""), d.get("game", ""), d.get("version", ""),
                   Reading.from_json(d.get("reading") or {}), dict(d.get("name_of") or {}),
                   dict(d.get("bank_of") or {}), d.get("note", ""),
                   list(d.get("unplayed") or ()), dict(d.get("sounds") or {}))


def manifest_rows(project):
    """``{"video/<file>": card path}`` from the project's ``video/manifest.txt``."""
    out = {}
    try:
        with open(os.path.join(project, "video", "manifest.txt"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) >= 2 and cols[0]:
                    out["video/" + cols[0]] = cols[1]
    except OSError:
        pass
    return out


def _bank_dirs(rows):
    """The scene directories the project's clips come from, most clips first (at most
    :data:`BANKS_MAX`)."""
    count = {}
    for path in rows.values():
        if "/scene.assets/" in path:
            d = path.split("/scene.assets/", 1)[0]
            count[d] = count.get(d, 0) + 1
    return sorted(count, key=lambda d: (-count[d], d))[:BANKS_MAX]


def _cache_path(card):
    from .title_reader import cache_dir
    try:
        st = os.stat(card)
    except OSError:
        return None
    from .clip_sounds import READ_REV as SOUNDS_REV
    key = "%s|%d|%d|%d|%d" % (os.path.normcase(os.path.abspath(card)), st.st_size,
                              int(st.st_mtime), READ_REV, SOUNDS_REV)
    return os.path.join(cache_dir("clip_modes"), hashlib.sha1(key.encode()).hexdigest() + ".json")


def read_card(card, rows, cancel=None):
    """:class:`CardClips` for the card image *card* and a project's manifest *rows*
    (:func:`manifest_rows`). Opens the card read-only; cached per card file (path, size,
    time), so the second look is instant. Never raises: a card it can't read is a
    :class:`CardClips` whose ``note`` says why."""
    from . import video_bank as VB
    out = CardClips(card=card)
    if not card or not os.path.isfile(card):
        out.note = "the card the project was extracted from is not on this PC"
        return out
    cache = _cache_path(card)
    if cache and os.path.isfile(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                got = CardClips.from_json(json.load(f))
            got.name_of = _names_of(rows, got.bank_of, got)
            return got
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
    from .explorer import CardImage
    from .mode_tryit import TryItError, card_title
    try:
        game, version, part = card_title(card)
    except TryItError as e:
        out.note = str(e)
        return out
    out.game, out.version = game or "", version or ""
    names, banks = set(), {}
    fragments = None
    try:
        with CardImage(card) as img:
            elf = img.preview(part, "/%s/game" % game, cap=256 << 20) if game else None
            if game:
                from .clip_sounds import card_fragments
                fragments = card_fragments(img, part, game)
            for d in _bank_dirs(rows):
                if cancel is not None and cancel():
                    return out
                try:
                    data = img.preview(part, "%s/scene.radium" % d, cap=64 << 20)
                    bank = VB.parse(data) if data else None
                except (OSError, ValueError, VB.VideoBankError):
                    bank = None
                if bank is None:
                    continue
                for c in bank.library.entries:
                    names.add(c.name)
                    banks.setdefault(c.name, [d, c.path])
    except (OSError, ValueError) as e:
        out.note = "the card could not be read (%s)" % e
        return out
    if not elf or elf[:4] != b"\x7fELF":
        out.note = "the card's game program could not be read"
        return out
    if cancel is not None and cancel():
        return out
    ctx = {}
    out.reading = analyse(elf, names, ctx=ctx)
    out.sounds = _sounds(elf, names, fragments, out, ctx)
    out.bank_of = {n: v for n, v in banks.items()}
    out.unplayed = unplayed(out.reading, banks)
    if not out.reading.labels:
        out.note = "the app can't tell this game's modes apart in its program"
    out.name_of = _names_of(rows, out.bank_of, out)
    if cache:
        try:
            tmp = cache + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out.to_json(), f)
            os.replace(tmp, cache)
        except OSError:
            pass
    return out


def _sounds(elf, names, fragments, clips, ctx):
    """:func:`.clip_sounds.analyse`'s reading as a dict; a failure is its note, never the
    modes' (a prototype rides along, it never breaks the tab)."""
    from . import clip_sounds as CS
    try:
        got = CS.analyse(elf, names, fragments, game=clips.game, version=clips.version,
                         refs=clips.reading.refs or None, ctx=ctx)
    except Exception as e:                                  # noqa: BLE001
        got = CS.SoundReading(note="the sounds could not be read (%s)" % e)
    return got.to_json()


def unplayed(reading, bank_of):
    """The clips nothing in the game program names, in the banks the game plays BY NAME (a
    bank a third of whose clips the program names: Godzilla's in-game bank, 443 of 598).
    Such a bank is only ever asked for a clip by its name, so these never show. A scene's own
    clips (an attract scene's) play with the scene and are never in this list."""
    by_dir = {}
    for name, v in bank_of.items():
        by_dir.setdefault(v[0], []).append(name)
    out = []
    for _d, names in by_dir.items():
        named = [n for n in names if reading.refs.get(n)]
        if names and len(named) * 3 >= len(names):
            out += [n for n in names if not reading.refs.get(n)]
    return sorted(out)


def _names_of(rows, bank_of, clips):
    """``{project rel: clip name}``: each manifest row's card path, matched to the bank clip
    at that path; plus the project's own copies, which no manifest row names yet."""
    by_path = {}
    for name, v in bank_of.items():
        d, path = v[0], v[1]
        by_path["%s/scene.assets/%s" % (d, path)] = name
    out = {}
    for rel, path in rows.items():
        n = by_path.get(path)
        if n:
            out[rel] = n
    return out
