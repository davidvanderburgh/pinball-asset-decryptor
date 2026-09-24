"""A port for any Spike 2 game build: the shipped one, one derived earlier, or one derived now.

CONTRACT (title_reader calls this; keep the signature):

    ensure_port(elf, game, version, progress=None, cancel=None) -> PortResult

``progress(fraction, text)`` runs 0..1; ``cancel()`` returning True stops the work with
:class:`.title_reader.Cancelled`. A derived port is written to :func:`user_ports_dir` and
every port lookup (``mode_project.profiles``, ``mode_runtime.port_file``/``ports``,
``mode_write.find_port``) reads that folder after the shipped one.

In order:

1. A SHIPPED port (``tools/spike2_emu/modes/sdk/ports``) for this game whose every site's two
   instruction words are this program's: the build it was made on.
2. A port DERIVED earlier on this machine for this very program: ``<game>-<version>.port`` in
   :func:`user_ports_dir` with a sidecar ``.json`` naming the program's SHA-1, the reference
   ports and recipes it came from and the drafting revision; any of them changed, it is
   derived again.
3. Derived NOW: every shipped port of the same framework generation (the event bus's id bound
   tells the two apart; a port is never carried across them) drafts the build from its recipe
   (:mod:`.portgen`, in up to four processes), and only entries the references agree on are
   kept. Shots come from the build itself (:mod:`.portshots`) when no reference is the same
   title. The result is checked as ``port_words.py`` checks a port, and written with a
   ``NOT RUN`` header: it has never run in the emulator. A draft that lacks a core entry is
   not written as a port (``missing`` says what it lacks); the draft is kept beside the
   sidecar (``.draft``) for a person to finish.
"""

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

#: the most processes a derivation uses
MAX_WORKERS = 4


@dataclass
class PortResult:
    path: str = ""            # "" when there is no port for this build
    origin: str = ""          # "shipped" | "derived" | ""
    proven: bool = False
    missing: tuple = ()       # what could not be placed, as words
    notes: tuple = ()         # sentences for the person


def user_ports_dir():
    """Where ports derived on this machine are kept."""
    from .title_reader import cache_dir
    return cache_dir("ports")


def shipped_ports_dir():
    from .mode_runtime import sdk_dir
    return os.path.join(sdk_dir(), "ports")


def recipes_dir():
    return os.path.join(shipped_ports_dir(), "recipes")


def port_version(version):
    """``1.29.0`` -> ``1.29``, ``1_02_0`` -> ``1.02`` (a nonzero third part is kept), spelled as
    the card spells it, as port file names are (``jaws_le-1.02.port``)."""
    parts = re.findall(r"\d+", str(version or ""))
    while len(parts) > 2 and int(parts[-1]) == 0:
        parts.pop()
    return ".".join(parts)


def _label(game, version=""):
    from .mode_project import title_label
    return title_label(game, version)


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _sha1_file(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def _header_game(text):
    game = version = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("game "):
            game = s.split(None, 1)[1].strip()
        elif s.startswith("version "):
            version = s.split(None, 1)[1].strip()
        if game and version:
            break
    return game, version


def site_mismatches(text, elf):
    """The names of a port's sites whose two words are not the program's (a :class:`.portgen.Elf`).
    Empty = the port was measured on this very program."""
    bad = []
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 5 and f[0] == "site":
            try:
                va, w0, w1 = int(f[2], 0), int(f[3], 0), int(f[4], 0)
            except ValueError:
                bad.append(f[1])
                continue
            if not elf.in_text(va) or (elf.word(va), elf.word(va + 4)) != (w0, w1):
                bad.append(f[1])
    return bad


def _proven(text):
    from .mode_project import UNPROVEN_MARK
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if not s.startswith("#"):
            break
        if UNPROVEN_MARK in s:
            return False
    return True


def _shipped_list():
    out = []
    try:
        names = os.listdir(shipped_ports_dir())
    except OSError:
        return out
    for name in names:
        m = re.match(r"^(.+)-(\d+\.\d+(?:\.\d+)?)\.port$", name)
        if m:
            out.append((m.group(1), m.group(2)))
    return sorted(out)


# ---- is a derived port still current? ----------------------------------------------------------
_HASHES = {}


def _stat_cached(path, fn):
    """fn(path), recomputed only when the file's size or mtime changes; None when it is missing."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_size, st.st_mtime_ns)
    if key not in _HASHES:
        _HASHES[key] = fn(path)
    return _HASHES[key]


def derived_current(port_path):
    """Is a port derived on this machine still what :func:`ensure_port` would derive? Its sidecar
    says it passed, with this drafting revision, from reference ports and recipes that are
    unchanged. Every port lookup skips one that is not (a portgen fix or a corrected shipped
    port then reaches it the next time the card is read). Cheap: a JSON read and file stats."""
    from . import portgen
    side_path = port_path[:-len(".port")] + ".json" if port_path.endswith(".port") else ""
    try:
        with open(side_path, "r", encoding="utf-8") as f:
            side = json.load(f)
    except (OSError, ValueError):
        return False
    key = side.get("key") if isinstance(side, dict) else None
    if not side.get("ok") or not isinstance(key, dict) or key.get("revision") != portgen.REVISION:
        return False
    for name, pair in (key.get("refs") or {}).items():
        try:
            want_entries, want_recipe = pair
        except (TypeError, ValueError):
            return False
        port = os.path.join(shipped_ports_dir(), name + ".port")
        recipe = os.path.join(recipes_dir(), name + ".recipe.gz")
        if _stat_cached(port, lambda p: portgen.entries_sha1(_read(p))) != want_entries:
            return False
        if _stat_cached(recipe, _sha1_file) != want_recipe:
            return False
    return True


# ---- has a derived port run? --------------------------------------------------------------------
#: beside a derived port, ``<game>-<version>.live.json``: the Try it that ran it live on this PC
LIVE_SUFFIX = ".live.json"


def is_derived(port_path):
    """Is ``port_path`` a port derived on this machine (in :func:`user_ports_dir`), not a
    shipped one?"""
    if not port_path:
        return False
    try:
        d = user_ports_dir()
    except OSError:
        return False
    return (os.path.normcase(os.path.dirname(os.path.abspath(port_path)))
            == os.path.normcase(os.path.abspath(d)))


def _live_path(port_path):
    return port_path[:-len(".port")] + LIVE_SUFFIX if port_path.endswith(".port") else ""


def record_live_run(port_path, armed=""):
    """Record that a Try it ran the derived port ``port_path`` live on this PC and the mode
    runtime hooked the game with it (its ``armed:`` line, ``armed``). Kept beside the port and
    tied to the port's exact text: a port derived again with other entries needs a Try it again.
    True when it was recorded."""
    live = _live_path(port_path)
    if not live or not is_derived(port_path):
        return False
    try:
        text_sha1 = _sha1_file(port_path)
    except OSError:
        return False
    _write(live, json.dumps(dict(port_sha1=text_sha1, when=time.strftime("%Y-%m-%d %H:%M:%S"),
                                 armed=str(armed or "")[:400]), indent=1))
    return True


def ran_live(port_path):
    """Has a Try it run this derived port live on this PC, with the port as it is now
    (:func:`record_live_run`)? A shipped port answers False: it has no such record."""
    live = _live_path(port_path)
    try:
        with open(live, "r", encoding="utf-8") as f:
            rec = json.load(f)
        return isinstance(rec, dict) and rec.get("port_sha1") == _sha1_file(port_path)
    except (OSError, ValueError):
        return False


# ---- the references -----------------------------------------------------------------------------
_RECIPES = {}


def _recipe(path):
    """(sha1, recipe) of a recipe file, read once per process while the file is unchanged."""
    from . import portgen
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime_ns)
    hit = _RECIPES.get(key)
    if hit is None:
        hit = _RECIPES[key] = (_sha1_file(path), portgen.load_recipe(path))
    return hit


class Reference:
    """One shipped port with its recipe."""

    def __init__(self, port_path, recipe_path):
        from . import portgen
        self.port_path = port_path
        self.recipe_path = recipe_path
        self.name = os.path.basename(port_path)[:-len(".port")]
        self.text = _read(port_path)
        self.game, self.version = _header_game(self.text)
        self.entries_sha1 = portgen.entries_sha1(self.text)
        self.recipe_sha1, self.recipe = _recipe(recipe_path)
        self.generation = self.recipe.get("generation", "")

    @property
    def label(self):
        return _label(self.game, self.version)

    def current(self):
        return self.recipe.get("entries_sha1") == self.entries_sha1


def references():
    """(every shipped port with a recipe that matches it, sorted by name; notes about the ports
    whose recipe could not be used)."""
    from . import portgen
    out, notes = [], []
    d = shipped_ports_dir()
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".port"))
    except OSError:
        return out, notes
    for n in names:
        rp = os.path.join(recipes_dir(), n[:-len(".port")] + ".recipe.gz")
        if not os.path.isfile(rp):
            continue
        try:
            ref = Reference(os.path.join(d, n), rp)
        except (OSError, ValueError, KeyError, portgen.PortgenError):
            notes.append("%s's recipe could not be read." % n)
            continue
        if not ref.current():
            notes.append("%s changed since its recipe was made, so it is not used to derive ports "
                         "(rebuild the recipe with port_tool.py recipe)." % n)
            continue
        out.append(ref)
    return out, notes


# ---- drafting (one reference; runs in a worker process too) -------------------------------------
#: the target program of a WORKER PROCESS (set by its initializer). The in-process path never
#: uses it: it hands the program to each draft, so two derivations on two threads never share it.
_WORKER = {}


def _worker_init(elf, name):
    from . import portgen
    _WORKER["elf"] = portgen.Elf(elf, name)


def _ref_name(port_path):
    return os.path.basename(port_path)[:-len(".port")]


def _draft_one(port_path, recipe_path, game, version, tgt=None):
    """One reference's draft of `tgt` (a :class:`.portgen.Elf`; in a worker process, the program
    its initializer read) as a plain (picklable) dict. A reference that cannot draft this program
    comes back as ``dict(ref, error)`` instead of raising, so one bad reference never ends the
    derivation of the others."""
    from . import portgen
    t = time.monotonic()
    try:
        if tgt is None:
            tgt = _WORKER["elf"]
        recipe = portgen.load_recipe(recipe_path)
        d = portgen.apply_recipe(recipe, _read(port_path), tgt, game, version,
                                 port_name=os.path.basename(port_path), target_name=tgt.path)
    except Exception as e:                                        # noqa: BLE001 - reported per reference
        return dict(ref=_ref_name(port_path), error="%s: %s" % (type(e).__name__, e),
                    seconds=time.monotonic() - t)
    return dict(ref=_ref_name(port_path), lines=d.lines, placed=d.placed,
                how=d.how, missing=d.missing_core, seconds=time.monotonic() - t)


def _draft_all(refs, elf, tgt, game, version, say, cancel, workers):
    """``(drafts {reference name: draft dict}, how it ran: "pool" | "in-process")``: every
    reference's draft of the program (`elf` bytes, `tgt` the same as a :class:`.portgen.Elf`),
    in up to `workers` processes (in this one when 1, when there is one reference, or for the
    references left when a pool cannot start or breaks). `cancel` is honoured between
    references. A draft that failed is ``dict(ref, error)``."""
    from .title_reader import Cancelled
    jobs = [(r.port_path, r.recipe_path, game, version) for r in refs]
    out = {}
    ran = "in-process"

    def done(d):
        out[d["ref"]] = d
        say(len(out) / len(jobs), "Lined up with %d of %d ports" % (len(out), len(jobs)))

    if workers > 1 and len(jobs) > 1:
        try:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor, as_completed
            with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=mp.get_context("spawn"),
                                     initializer=_worker_init, initargs=(elf, tgt.path)) as ex:
                futs = [ex.submit(_draft_one, *j) for j in jobs]
                try:
                    for f in as_completed(futs):
                        done(f.result())          # raises only when the pool itself broke
                        ran = "pool"
                        if cancel is not None and cancel():
                            raise Cancelled()
                except BaseException:
                    for f in futs:
                        f.cancel()
                    raise
        except Cancelled:
            raise
        except Exception:                 # noqa: BLE001 - a pool that cannot start or broke: draft the rest here
            pass
    for j in jobs:
        if _ref_name(j[0]) in out:
            continue
        if cancel is not None and cancel():
            raise Cancelled()
        done(_draft_one(*j, tgt=tgt))
        ran = "pool, then in-process" if ran.startswith("pool") else "in-process"
    return out, ran


# ---- merging the drafts -------------------------------------------------------------------------
_KEYED = ("site", "data", "scene")
_NOT_PLACED = re.compile(r"^# (site|data|scene)\s+(\S+)\s+NOT PLACED: (.*)$")


def _parse(lines):
    """A draft's lines as (entry order [(kind, name)], not placed {(kind, name): [reason,
    candidate lines...]}, copied lines [(key, rest)])."""
    order, why, copied = [], {}, []
    last = None
    for line in lines:
        m = _NOT_PLACED.match(line)
        if m:
            k = (m.group(1), m.group(2))
            order.append(k)
            why[k] = [m.group(3)]
            last = k
            continue
        if line.startswith("#   candidate:") and last is not None:
            why[last].append(line)
            continue
        if line.startswith("#"):
            continue
        last = None
        f = line.split(None, 1)
        if not f:
            continue
        if f[0] in _KEYED and len(f) > 1:
            order.append((f[0], f[1].split()[0]))
        elif f[0] not in ("game", "version"):
            copied.append((f[0], f[1] if len(f) > 1 else ""))
    return order, why, copied


def _weak(how):
    """Was an entry placed only by a fallback (portgen's via_bus / via_vslot)?"""
    return how.startswith(("the handler of event", "the one virtual of its"))


def _same_title(a, b):
    from .portgen import title_of
    return title_of(a) == title_of(b)


def _in_code(tgt, va):
    """Does the program have both of a site's words at `va`?"""
    return isinstance(va, int) and tgt.word(va) is not None and tgt.word(va + 4) is not None


def _entry_line(kind, name, value, tgt):
    if kind == "site":
        return "site %-16s 0x%08x 0x%08x 0x%08x" % (name, value, tgt.word(value), tgt.word(value + 4))
    if kind == "data":
        return "data %-22s 0x%08x" % (name, value)
    return "scene %-20s %s" % (name, value)


def _fmt(v):
    return v if isinstance(v, str) else "0x%x" % v


def merge(drafts, refs, tgt, game, version, family):
    """(port body lines, provenance {"site tick": {...}}, missing core names, notes) from the
    drafts of every reference.

    Kept: each site, global and scene that every reference which placed it agrees on (a
    disagreement leaves it out, saying so). The references are ranked - the same title first,
    then core-complete ones, then the ones that place the most - and the first one's copied lines
    are the port's (its values; for the same title also its shots, callouts, text and lamps)."""
    from . import portgen
    by_ref = {r.name: r for r in refs}
    ranked = sorted(drafts.values(), key=lambda d: (
        not _same_title(game, by_ref[d["ref"]].game), bool(d["missing"]), -len(d["placed"]), d["ref"]))
    parsed = {d["ref"]: _parse(d["lines"]) for d in ranked}
    votes = {}
    for d in ranked:
        for k, v in d["placed"].items():
            votes.setdefault(k, {}).setdefault(v, []).append(d["ref"])
    # a placement only a fallback made (the end of ball as a bus handler, a manager virtual by
    # its shape) gives way to what a reference's own way of finding it placed
    for k, vals in votes.items():
        if len(vals) > 1:
            strong = {v: [w for w in who if not _weak(drafts[w]["how"].get(k, ""))] for v, who in vals.items()}
            strong = {v: who for v, who in strong.items() if who}
            if strong:
                votes[k] = strong
    order = []
    for d in ranked:
        for k in parsed[d["ref"]][0]:
            if k not in order:
                order.append(k)
    lines = {"site": [], "data": [], "scene": []}
    provenance, placed = {}, {}
    for k in order:
        kind, name = k
        vals = votes.get(k)
        also = ""
        if vals and len(vals) > 1:
            # the same title's references decide a role another title fills differently (Godzilla's
            # callout is its own per-player wrapper, the others' the framework request)
            mine = {v: [w for w in who if _same_title(game, by_ref[w].game)] for v, who in vals.items()}
            mine = {v: who for v, who in mine.items() if who}
            if len(mine) == 1:
                v0 = next(iter(mine))
                also = "; other titles' ports place %s" % ", ".join(
                    "%s (%s)" % (_fmt(v), ", ".join(by_ref[w].label for w in who)) for v, who in vals.items() if v != v0)
                vals = {v0: mine[v0]}
        if vals and len(vals) == 1 and kind == "site" and not _in_code(tgt, next(iter(vals))):
            v = next(iter(vals))
            lines[kind].append("# site %-22s NOT PLACED: 0x%08x is not in the program's code" % (name, v))
        elif vals and len(vals) == 1:
            v, who = next(iter(vals.items()))
            first = next(d for d in ranked if d["ref"] == who[0])
            how = first["how"].get(k, "") + also
            src = ", ".join(by_ref[w].label for w in who)
            lines[kind].append("#   %s%s: %s [%s]" % ("scene " if kind == "scene" else "", name, how, src))
            lines[kind].append(_entry_line(kind, name, v, tgt))
            placed[k] = v
            provenance["%s %s" % k] = dict(value=_fmt(v), how=how, refs=who)
        elif vals:
            txt = ", ".join("%s (%s)" % (_fmt(v), ", ".join(by_ref[w].label for w in who)) for v, who in vals.items())
            lines[kind].append("# %s %-22s NOT PLACED: the references disagree: %s" % (kind, name, txt))
            provenance["%s %s" % k] = dict(value=None, how="the references disagree: %s" % txt, refs=[])
        else:
            first = next((d for d in ranked if k in parsed[d["ref"]][1]), None)
            why = parsed[first["ref"]][1][k] if first else ["no reference names it"]
            lines[kind].append("# %s %-22s NOT PLACED: %s" % (kind, name, why[0]))
            lines[kind].extend(why[1:4])
    # one scoring pair: an unplaced name of the pair the build does not use is dropped
    for kind, idx in (("site", 0), ("data", 1)):
        used = {n for (k, n) in placed if k == kind}
        for pair, other in ((portgen.SCORE_PAIRS[0], portgen.SCORE_PAIRS[1]),
                            (portgen.SCORE_PAIRS[1], portgen.SCORE_PAIRS[0])):
            if other[idx] in used and pair[idx] not in used:
                pat = re.compile(r"^# %s\s+%s\s+NOT PLACED" % (kind, pair[idx]))
                keep, skip = [], False
                for line in lines[kind]:
                    if pat.match(line):
                        skip = True
                        continue
                    if skip and line.startswith("#   candidate:"):
                        continue
                    skip = False
                    keep.append(line)
                lines[kind] = keep
    primary = ranked[0]
    pref = by_ref[primary["ref"]]
    same = _same_title(game, pref.game)
    values, shots, callouts, texts, lamps = [], [], [], [], []
    for key, rest in parsed[primary["ref"]][2]:
        if key == "value":
            values.append((rest.split()[0], rest))
        elif key == "shot":
            shots.append("shot %s" % rest)
        elif key == "callout":
            callouts.append("callout %s" % rest)
        elif key == "text":
            texts.append("text %s" % rest)
        elif key == "lamp":
            lamps.append("lamp %s" % rest)
    # values the primary lacks, from the other references in rank order (framework offsets:
    # one generation keeps them); never another title's rule values or struct offsets
    left_off = set()
    if not same:
        left_off = {n for n, _r in values if not framework_value(n)}
        values = [(n, r) for n, r in values if framework_value(n)]
    have = {n for n, _r in values}
    for d in ranked[1:]:
        mine = _same_title(game, by_ref[d["ref"]].game)
        for key, rest in parsed[d["ref"]][2]:
            n = rest.split()[0] if rest.split() else ""
            if key != "value" or n in have or n.startswith("shot_mask"):
                continue
            if not mine and not framework_value(n):
                left_off.add(n)
                continue
            values.append((n, rest))
            have.add(n)
    # the end of ball's bus id and the switch tables are read off THIS build (framework_core), never copied
    values = [(n, r) for n, r in values if not _read_here(n)]
    left_off -= have
    notes = []
    if not same:
        # another title's message table is left off with its struct offsets: its layout is that title's
        msgs = [n for (k, n) in list(placed) if k == "data" and n.startswith("message_")]
        _drop_placed(lines, placed, provenance, "data", msgs)
        left_off |= set(msgs)
        if left_off:
            notes.append("Left off: %s - another title's layout (%s), not this build's." % (
                ", ".join(sorted({_CAP_OF.get(_cap_key(n), n) for n in left_off})), ", ".join(sorted(left_off))))
    mask_values = []
    sd = placed.get(("site", "shot_dispatch"))
    if sd is not None:
        # the mask is where the reference that placed shot_dispatch keeps it (its own values)
        who = provenance["site shot_dispatch"]["refs"][0]
        mask_values = [(rest.split()[0], rest) for key, rest in parsed[who][2]
                       if key == "value" and rest.startswith("shot_mask")]
    shots_head = "COPIED from %s, the same title; unverified" % pref.label
    if not same or not shots:
        shots, lamps, shots_head, found = _own_shots(tgt, family)
        if found is not None and sd is None and portgen.is_hooked_ok(tgt, found["site"]):
            sd = placed[("site", "shot_dispatch")] = found["site"]
            how = ("the function every switch handler hands its shot bit to (%s) - prove it with the shot "
                   "census" % found["how"])
            pat = re.compile(r"^# site\s+shot_dispatch\s+NOT PLACED")
            keep, skip = [], False
            for line in lines["site"]:
                if pat.match(line):
                    skip = True
                    continue
                if skip and line.startswith("#   candidate:"):
                    continue
                skip = False
                keep.append(line)
            lines["site"] = keep + ["#   shot_dispatch: %s" % how, _entry_line("site", "shot_dispatch", sd, tgt)]
            provenance["site shot_dispatch"] = dict(value=_fmt(sd), how=how, refs=[])
            mask_values = [("shot_mask_at", "shot_mask_at          %d" % found["mask_at"]),
                           ("shot_mask_bits", "shot_mask_bits        %d" % found["bits"])]
    values = [(n, r) for n, r in values if not n.startswith("shot_mask")] + mask_values
    if not same:
        callouts, texts = [], []
    # events: from the first reference (in rank order) that kept any whose site is placed here
    events = []
    for d in ranked:
        ok = []
        for key, rest in parsed[d["ref"]][2]:
            if key != "event":
                continue
            w = rest.split("#", 1)[0].split()
            if len(w) >= 3 and w[1] == "site" and ("site", w[2]) not in placed:
                continue
            ok.append("event %s" % rest)
        if ok:
            events = ok
            break
    # the FRAMEWORK's own core where no reference and none of the build's rule functions placed it:
    # the player byte through the scores, the end of ball from the event bus, shots from the switch drain
    fw = framework_core(tgt, lines, placed, provenance)
    notes += fw["notes"]
    if fw["values"]:
        names = {n for n, _v in fw["values"]}
        values = [(n, r) for n, r in values if n not in names] + [
            (n, "%-21s 0x%x" % (n, v)) for n, v in fw["values"]]
    switch_body = []
    if fw["mapped"]:
        # the build's shot bits (cshot objects) reach no mode without a shot dispatch: the switches' bits
        # replace them, and an insert's tie to one of them is dropped
        if shots:
            switch_body += ["# ---- the build's own shot bits, which no dispatch hands a mode here ----"]
            switch_body += ["# %s" % s for s in shots]
        shots = []
        shots_head = "none from the rules: the switch drain's `switch` lines below are the shots"
        lamps = [_untie_lamp(l) for l in lamps]
        switch_body += ["# ---- shots from the switch drain: switch <id> <shot mask> <name> (the game's own switch names; "
                        "not the trough, shooter lane, flippers or cabinet) - prove them with a census ----"]
        switch_body += fw["switch_lines"]
        # a start shot a template mode finds among these names (a copied one names a rule shot)
        texts = [t for t in texts if t.split()[1:2] != ["example_start_shot"]] + [
            "text example_start_shot     %s" % fw["example"]]
    sites = {n for (k, n) in placed if k == "site"}
    data = {n for (k, n) in placed if k == "data"}
    missing = portgen.core_missing(sites, data, _numbers(values), len(fw["mapped"]))
    if not shots and not fw["mapped"]:
        missing.append("shots")
    body = ["game           %s" % game, "version        %s" % port_version(version), "",
            "# ---- functions: site <name> <address> <first two instruction words> ----"] + lines["site"]
    body += ["", "# ---- globals: data <name> <address> ----"] + lines["data"]
    if lines["scene"]:
        body += ["", "# ---- scenes ----"] + lines["scene"]
    if values:
        body += ["", "# ---- values: COPIED from the references (framework offsets), unverified; the switch_* and "
                     "ball_end_event values read from this build's own framework code ----"]
        body += ["value %s" % r for _n, r in values]
    body += ["", "# ---- shots: %s ----" % shots_head] + shots
    if switch_body:
        body += [""] + switch_body
    if callouts or texts:
        body += ["", "# ---- callouts and text: %s ----" % (
            "COPIED from %s, the same title; unverified" % pref.label if same else "a start shot for a template mode")]
        body += callouts + texts
    if events:
        body += ["", "# ---- events: COPIED, unverified - prove them with event_probe.c (MODE_SDK.md, Events) ----"]
        body += events
    if lamps:
        body += [""] + lamps
    return body, provenance, missing, notes


#: value names that are a title's own rules or struct layout (award screen, display effects, lamp
#: slots, the layered display, Godzilla's lights and city roster): a derived port takes them only
#: from a reference of the SAME title, and the capability they serve is left off otherwise
TITLE_STRUCT_PREFIXES = ("award_", "display_", "lamp_", "layered_", "light_", "roster_", "effect_", "message_")
#: what each left-off value served, for the port's note
_CAP_OF = {"award_": "the award screen", "display_": "clips and display priority", "lamp_": "lights on inserts",
           "layered_": "display priority", "light_": "light shows", "roster_": "the roster",
           "effect_": "display priority", "message_": "messages", "award_screen_type": "the award screen"}


def _cap_key(name):
    return next((p for p in TITLE_STRUCT_PREFIXES if name.startswith(p)), name)


def framework_value(name):
    """1 when a `value` is the FRAMEWORK's (one generation keeps it: the event list, the sound
    channels, the scene graph's virtuals) rather than one title's own (:data:`TITLE_STRUCT_PREFIXES`,
    portgen.TITLE_VALUES)."""
    from . import portgen
    return name not in portgen.TITLE_VALUES and not name.startswith(TITLE_STRUCT_PREFIXES)


def _read_here(name):
    """Values a port gets from its own build only: the end of ball's bus id (0x34 on generation B is
    the tick's exit on A) and the switch tables (portswitch)."""
    return name == "ball_end_event" or name.startswith("switch_")


def _numbers(values):
    """{name: int} of `(name, "name  <number> ...")` value lines (a line that is not a number: left out)."""
    out = {}
    for n, r in values:
        f = r.split()
        try:
            out[n] = int(f[1], 0)
        except (IndexError, ValueError):
            pass
    return out


def _drop_placed(lines, placed, provenance, kind, names):
    """Turn placed `<kind> <name>` entries into `NOT PLACED` comments (left off on purpose)."""
    for name in names:
        pat = re.compile(r"^%s\s+%s\s" % (kind, re.escape(name)))
        keep = []
        for line in lines[kind]:
            if pat.match(line):
                keep.append("# %s %-22s NOT PLACED: left off - another title's layout" % (kind, name))
            elif line.startswith("#   %s:" % name):
                continue
            else:
                keep.append(line)
        lines[kind] = keep
        placed.pop((kind, name), None)
        provenance.pop("%s %s" % (kind, name), None)


def _drop_not_placed(lines, kind, name):
    """Take a `# <kind> <name> NOT PLACED` line (and its candidate lines) out of a section."""
    pat = re.compile(r"^# %s\s+%s\s+NOT PLACED" % (kind, re.escape(name)))
    keep, skip = [], False
    for line in lines[kind]:
        if pat.match(line):
            skip = True
            continue
        if skip and line.startswith("#   candidate:"):
            continue
        skip = False
        keep.append(line)
    lines[kind] = keep


def _untie_lamp(line):
    """A `lamp <lights> <shot mask> <name>` line with its shot tie cleared (0)."""
    m = re.match(r"^(lamp\s+\S+\s+)(\S+)(\s+.*)$", line)
    return "%s0%s" % (m.group(1), m.group(3)) if m else line


def framework_core(tgt, lines, placed, provenance):
    """What the FRAMEWORK every build shares gives a port that no reference placed (:mod:`.portswitch`),
    added to `lines` (the site/data sections) and `placed`/`provenance` in place:

    * ``data cur_player``: the byte that indexes the scores (generation A plain C: Batman 66, Stranger
      Things), when the references placed no cur_player;
    * the end of ball as the framework's bus id (``value ball_end_event`` with ``site hook_dispatch``),
      when no ``site ball_end`` was placed - the id read off the build's own end-of-ball sequence (0x34 on
      generation B, 0x30 on A);
    * shots from the framework's switch drain (``site switch_edge``, its tables and a ``switch`` line per
      playfield switch), when no ``site shot_dispatch`` was placed.

    Returns dict(values=[(name, number)], mapped=[(switch id, mask, name)], switch_lines, example, notes)."""
    from . import portgen, portswitch
    out = dict(values=[], mapped=[], switch_lines=[], example="", notes=[])
    if ("data", "cur_player") not in placed:
        scores = placed.get(("data", "scores")) or placed.get(("data", "scores32"))
        p, how = portswitch.cur_player_via_scores(tgt, scores)
        if p is not None:
            _drop_not_placed(lines, "data", "cur_player")
            lines["data"] += ["#   cur_player: %s" % how, _entry_line("data", "cur_player", p, tgt)]
            placed[("data", "cur_player")] = p
            provenance["data cur_player"] = dict(value=_fmt(p), how=how, refs=[])
        else:
            out["notes"].append("Its current player could not be found through its scores either (%s)." % how)
    if ("site", "ball_end") not in placed:
        ev, how = portswitch.ball_end_event(tgt)
        hd = placed.get(("site", "hook_dispatch")) or portswitch.hook_dispatch(tgt)
        if ev is not None and hd is not None:
            if ("site", "hook_dispatch") not in placed:
                _drop_not_placed(lines, "site", "hook_dispatch")
                hhow = "the event bus's dispatch (cmp r0, #%d; push): the one function of that shape" % portgen.bus_bound(tgt)
                lines["site"] += ["#   hook_dispatch: %s" % hhow, _entry_line("site", "hook_dispatch", hd, tgt)]
                placed[("site", "hook_dispatch")] = hd
                provenance["site hook_dispatch"] = dict(value=_fmt(hd), how=hhow, refs=[])
            lines["site"] += ["#   the end of ball: no ball_end site - %s (value ball_end_event below)" % how]
            out["values"].append(("ball_end_event", ev))
            provenance["value ball_end_event"] = dict(value="0x%x" % ev, how=how, refs=[])
        else:
            out["notes"].append("Its end of ball could not be read from its event bus either (%s)." % how)
    if ("site", "shot_dispatch") not in placed:
        src = portswitch.switch_source(tgt)
        out["notes"] += src["notes"]
        if src["mapped"] and portgen.is_hooked_ok(tgt, int(src["sites"][1].split()[2], 0)):
            lines["site"] += src["sites"]
            for name, va in src["data"].items():
                if ("data", name) not in placed:
                    _drop_not_placed(lines, "data", name)
                    lines["data"].append(_entry_line("data", name, va, tgt))
                    placed[("data", name)] = va
            for name in ("switch_edge", "switch_drain"):
                va = int(next(l for l in src["sites"] if l.startswith("site %s " % name)).split()[2], 0)
                placed[("site", name)] = va
                provenance["site %s" % name] = dict(value=_fmt(va), how=src["how"], refs=[])
            out["values"] += src["values"]
            out["mapped"] = src["mapped"]
            out["switch_lines"] = portswitch.switch_lines(src["mapped"])
            out["example"] = portswitch.example_start_shot(src["mapped"])
    return out


def _own_shots(tgt, family):
    """(shot lines, lamp lines, how, the plain-C finding or None): the build's own shots, named
    after the inserts their lamps are (C++) or the switches that pass them (plain C)."""
    from . import lampmap, portshots
    try:
        ins, _how, tables = lampmap.inserts(lampmap.Elf(tgt.b, tgt.path))
        dev_tab = tables["dev_tab"]
    except SystemExit:
        ins, dev_tab = [], None
    lamp_head = "# ---- lamps: the build's own inserts (lamp_map.py) ----"
    if family in ("cmode", "crule"):
        bits, how = portshots.cpp_shots(tgt)
        names_by_lamp, by_lamp = {}, {}
        for i in ins:
            for l in i["lamps"]:
                names_by_lamp.setdefault(l, i["name"])
        for m, l in bits.items():
            by_lamp[l] = by_lamp.get(l, 0) | m
        pairs = [(m, portshots._nice(names_by_lamp[l]) if l in names_by_lamp else "Shot 0x%x" % m)
                 for m, l in bits.items()]
        lamp_lines = []
        if ins:
            lamp_lines = [lamp_head.replace(") ----", "), shot ties from its cshot objects ----")]
            for i in ins:
                shot = 0
                for l in i["lamps"]:
                    shot |= by_lamp.get(l, 0)
                lamp_lines.append(lampmap.lamp_line(dict(i, shot=shot)))
        head = ("read from the build's own cshot objects (%s), named after their inserts; prove them with "
                "the shot census" % how) if bits else "none: %s" % how
        return portshots.shot_lines(pairs), lamp_lines, head, None
    lamp_lines = [lamp_head] + [lampmap.lamp_line(dict(i, shot=0)) for i in ins] if ins else []
    found = portshots.c_shots(tgt)
    if found is None:
        return [], lamp_lines, "none: no function takes a single shot bit from the switch handlers", None
    names = portshots.c_shot_names(tgt, found, dev_tab)
    pairs = [(m, names.get(m) or "Shot 0x%x" % m) for m in found["shots"]]
    head = ("the constant bits the switch handlers hand 0x%x, named after their switches; prove them with "
            "the shot census" % found["site"])
    return portshots.shot_lines(pairs), lamp_lines, head, found


# ---- the entry point ----------------------------------------------------------------------------
def _paths(game, version):
    base = os.path.join(user_ports_dir(), "%s-%s" % (game, port_version(version)))
    return base + ".port", base + ".json", base + ".draft"


def _write(path, text):
    # a temp name of this process and thread: two reads of the same build never share one
    import threading
    tmp = "%s.%d-%d.tmp" % (path, os.getpid(), threading.get_ident())
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


_WORDS = {"tick": "its tick", "shot_dispatch": "its shot dispatch", "ball_end": "its end of ball",
          "score_add": "its score function", "score_add32": "its score function",
          "cur_player": "its current player", "scores": "its scores", "scores32": "its scores",
          "shots": "its shots"}


def derive(elf, game, version, refs, progress=None, cancel=None, workers=None, tgt=None):
    """Derive the program's port NOW from `refs` (the references of its framework generation),
    writing nothing: dict(ok, text, missing (core names), problems, notes, provenance, drafts).
    `progress(fraction, text)` runs 0.1..0.95 of a whole read."""
    from . import portgen
    from .title_reader import Cancelled, family_of

    def say(frac, text=""):
        if progress is not None:
            progress(frac, text)

    tgt = tgt or portgen.Elf(elf, "%s %s" % (game, version))
    ver = port_version(version)
    label = _label(game, ver)
    n = MAX_WORKERS if workers is None else max(1, min(MAX_WORKERS, int(workers)))
    env = os.environ.get("PAD_PORT_WORKERS", "")
    if env.isdigit():
        n = max(1, min(MAX_WORKERS, int(env)))
    say(0.1, "Lining this build up with %d port%s" % (len(refs), "" if len(refs) == 1 else "s"))
    drafts, ran = _draft_all(refs, elf, tgt, game, version, lambda f, s: say(0.1 + 0.65 * f, s), cancel, n)
    if cancel is not None and cancel():
        raise Cancelled()
    by_name = {r.name: r for r in refs}
    errors = {k: d["error"] for k, d in drafts.items() if "error" in d}
    drafts = {k: d for k, d in drafts.items() if "error" not in d}
    refs = [r for r in refs if r.name in drafts]
    err_notes = ["%s could not be lined up with this build (%s), so it was left out."
                 % (by_name[k].label, e) for k, e in sorted(errors.items())]
    if not drafts:
        return dict(ok=False, text="", missing=[], problems=["no reference could be lined up with this build"],
                    notes=["No port could be derived for %s: none of the %d reference ports could be lined up "
                           "with its program." % (label, len(errors))] + err_notes,
                    provenance={}, drafts={}, errors=errors, ran=ran)
    say(0.78, "Reading the build's shots")
    body, provenance, missing, notes = merge(drafts, refs, tgt, game, version, family_of(elf))
    notes = list(notes) + err_notes
    if cancel is not None and cancel():
        raise Cancelled()
    say(0.9, "Checking the port against the program")
    used = {w for p in provenance.values() for w in p.get("refs", [])}
    names = ", ".join(r.label for r in refs if r.name in used) or "no reference"
    gen = refs[0].generation if refs else ""
    header = ["# %s %s - port DERIVED on this machine from the ports of %s." % (game, ver, names),
              "# NOT RUN: drafted and never run in the emulator. Every entry says how it was placed and from",
              "# which ports; shots come from the build itself when no reference is the same title. Prove it",
              "# before trusting it (MODE_SDK.md, \"Making a port\").",
              "# program sha1 %s, portgen revision %d, %d reference port(s) of framework generation %s."
              % (tgt.sha1, portgen.REVISION, len(refs), gen), ""]
    text = "\n".join(header + body) + "\n"
    problems = portgen.check_port(text, tgt)
    ok = not missing and not problems
    if ok:
        notes = ["The port for %s was derived on this machine from the ports of %s and has not been run "
                 "in the emulator yet." % (label, names)] + notes
    else:
        what = ", ".join(_WORDS.get(m, m) for m in missing) or "a port that passes its check"
        notes = ["No port could be derived for %s: %s could not be found (from %d port%s of its framework "
                 "generation)." % (label, what, len(refs), "" if len(refs) == 1 else "s")] + notes
    return dict(ok=ok, text=text, missing=missing, problems=problems, notes=notes, provenance=provenance,
                drafts={k: dict(seconds=round(d["seconds"], 2), missing=d["missing"], placed=len(d["placed"]))
                        for k, d in sorted(drafts.items())}, errors=errors, ran=ran)


def ensure_port(elf, game, version, progress=None, cancel=None, workers=None):
    """A :class:`PortResult` for the game program `elf` (bytes) of `game` `version`: shipped,
    derived earlier, or derived now (see the module's docstring). `workers` caps the processes a
    derivation uses (default :data:`MAX_WORKERS`; ``PAD_PORT_WORKERS`` overrides it)."""
    from . import portgen
    from .title_reader import Cancelled

    def say(frac, text=""):
        if progress is not None:
            try:
                progress(max(0.0, min(1.0, frac)), text)
            except Exception:
                pass

    def check():
        if cancel is not None and cancel():
            raise Cancelled()

    t0 = time.monotonic()
    ver = port_version(version)
    label = _label(game, ver)
    say(0.0, "Looking for a port shipped for this build")
    try:
        tgt = portgen.Elf(elf, "%s %s" % (game, version))
    except portgen.PortgenError as e:
        say(1.0, "")
        return PortResult(missing=("a game program that can be read",), notes=("%s" % e,))
    # Anything but a cancel that goes wrong from here (an odd program, a reference that cannot be
    # read, a cache folder that cannot be written) is "no port", never a failed card read: the
    # stock table step after this one does not need a port.
    try:
        return _ensure(elf, tgt, game, version, say, check, cancel, workers, t0)
    except Cancelled:
        raise
    except Exception as e:                    # noqa: BLE001 - reported as words, the read goes on
        say(1.0, "")
        return PortResult(missing=("a port that could be derived",),
                          notes=("The port for %s could not be derived: %s: %s" % (label, type(e).__name__, e),))


def _ensure(elf, tgt, game, version, say, check, cancel, workers, t0):
    """ensure_port's three steps, once the program has been read."""
    from . import portgen
    # 1. a shipped port measured on this very program (this version's first)
    from .mode_project import version_key
    cands = [(v, g) for g, v in _shipped_list() if g == game]
    cands.sort(key=lambda gv: version_key(gv[0]) != version_key(version))
    for v, g in cands:
        p = os.path.join(shipped_ports_dir(), "%s-%s.port" % (g, v))
        try:
            text = _read(p)
        except OSError:
            continue
        if not site_mismatches(text, tgt):
            say(1.0, "")
            return PortResult(path=p, origin="shipped", proven=_proven(text))
    check()
    # 2. derived earlier, for this very program and these references
    say(0.05, "Looking for a port derived earlier")
    refs, ref_notes = references()
    gen = portgen.generation(portgen.bus_bound(tgt))
    usable = [r for r in refs if gen and r.generation == gen]
    key = dict(elf_sha1=tgt.sha1, revision=portgen.REVISION,
               refs={r.name: [r.entries_sha1, r.recipe_sha1] for r in usable})
    port_path, side_path, draft_path = _paths(game, version)
    try:
        with open(side_path, "r", encoding="utf-8") as f:
            side = json.load(f)
    except (OSError, ValueError):
        side = None
    if side and side.get("key") == key:
        if side.get("ok") and os.path.isfile(port_path):
            say(1.0, "")
            return PortResult(path=port_path, origin="derived", proven=False, notes=tuple(side.get("notes", ())))
        if not side.get("ok"):
            say(1.0, "")
            return PortResult(missing=tuple(side.get("missing", ())), notes=tuple(side.get("notes", ())))
    check()
    # 3. derived now
    return _derive_now(elf, tgt, game, version, gen, usable, ref_notes, key, say, cancel, workers, t0)


def _derive_now(elf, tgt, game, version, gen, usable, ref_notes, key, say, cancel, workers, t0):
    label = _label(game, port_version(version))
    port_path, side_path, draft_path = _paths(game, version)
    if not usable:
        why = ("its program does not show which framework generation it is" if not gen else
               "no shipped port is of its framework generation")
        miss = ("a reference port (%s)" % why,)
        notes = ["No port could be derived for %s: %s." % (label, why)] + ref_notes
        _write(side_path, json.dumps(dict(key=key, ok=False, missing=miss, notes=notes), indent=1))
        say(1.0, "")
        return PortResult(missing=miss, notes=tuple(notes))
    d = derive(elf, game, version, usable, progress=say, cancel=cancel, workers=workers, tgt=tgt)
    ok, text, missing, problems = d["ok"], d["text"], d["missing"], d["problems"]
    notes = d["notes"] + ref_notes
    say(0.95, "Writing the port")
    miss = tuple(_WORDS.get(m, m) for m in missing) + tuple(problems)
    side = dict(key=key, ok=ok, missing=miss, notes=notes, game=game, version=version, generation=gen,
                seconds=round(time.monotonic() - t0, 2), drafts=d["drafts"], entries=d["provenance"],
                problems=problems, errors=d["errors"], ran=d["ran"])
    if ok:
        _write(port_path, text)
        _remove(draft_path)
    else:
        if text:
            _write(draft_path, text)
        _remove(port_path)
    if ok or not d["errors"]:
        _write(side_path, json.dumps(side, indent=1))
    else:
        # a reference failed on this program: the failure may be that reference's, not the
        # build's, so it is not remembered; the next read tries again
        _remove(side_path)
    say(1.0, "")
    if ok:
        return PortResult(path=port_path, origin="derived", proven=False, notes=tuple(notes))
    return PortResult(missing=miss, notes=tuple(notes))
