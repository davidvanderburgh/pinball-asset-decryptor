"""The game's own modes on a title whose rules are C++ classes, read off the build itself.

Two rule systems share one shape (MODE_SDK.md, "The game's own modes"):

* ``cmode_manager`` titles (Godzilla, Jaws, Deadpool, King Kong, ...): ``cmode`` <-
  ``cmode_timed`` / ``cmode_mball`` / ``cmode_hurry_up`` <- one leaf class per mode;
* ``crule_manager`` titles (TMNT, Mandalorian, Munsters, Rush, Venom, ...): ``crule`` <-
  ``cmode`` <- ... with leaf classes named freely (``cepisode_one``, ``cberserker_rage``).

A MODE is an object of a class that derives from ``cmode``, whatever the class is called. The
objects are found where they are built: a static initialiser calls each class's constructor
on a constant address (a constructor being a function that stores a class's vtable pointer
into its first argument), ``ctor(obj, id, a, award, b[, timer])``, and registers the
destructor with ``__aeabi_atexit`` right after.

Every engine function the numbers flow through is located on THIS build, by what it does:

``get_adjustment``  the function that indexes the operator settings table (the Defaults tab's
                    table), ranked by callers passing a constant id;
award add           the callee the modes' own code hands a fresh 64-bit constant (r2:r3, high
                    word 0) most often, that adds with carry near its start;
mode getter         ``get_rule(id)`` / ``cmode_manager_get(mgr, id)``: the callee nearly all of
                    whose callers pass a constant mode id, whose result's virtual is then called
                    (the slot most such calls use, that the modes override and that adds an
                    award, is START).

Slot numbers never carry across titles (the base classes differ), so every role is found from
statistics on the build: the title-message slot is the one most classes override with a
distinct constant return; a timed mode's durations are the slots ``cmode_timed`` adds that
return a constant and whose value ``cmode_timed`` hands on (``cmode_manager`` titles), or
fields a mode's constructor stores and a setup virtual hands to its timer object
(``crule_manager`` titles).

WHAT MAY BE EDITED. An operator setting a mode reads is always editable: its compiled default
is what the Defaults tab writes. A word is editable only when the pattern that found it is
structural: an award-add's value argument built by ``mov``/``movw``/``movt`` right before the
call, a constant a mode's virtual returns in a timer slot, a constructor-stored field the
timer setup hands to the timer's duration virtuals (and nothing else stores into). A number
whose meaning is not certain - a value on one path only (a conditional instruction: a clamp
reads like an award), a constant stored into the award record by a field this reader has not
decoded - is listed as ``uncertain``: read-only, with the reason.
"""

import collections

import numpy as np

from . import stock_scan as S
from .title_reader import Cancelled
from .stock_scan import THIS, Sym, Val

FRAMEWORK = {"cmode", "cmode_timed", "cmode_mball", "cmode_hurry_up", "cmode_battle", "crule"}


def family(model):
    """``("crule", "crule_manager")``, ``("cmode", "cmode_manager")`` or None."""
    if "crule_manager" in model and S.derives(model, "cmode", "crule"):
        return "crule", "crule_manager"
    if "cmode_manager" in model and "cmode" in model:
        return "cmode", "cmode_manager"
    return None


# ---- the mode objects -------------------------------------------------------------------------
def vptr_sites(prog, vptrs):
    """``{code VA: vptr}`` for every movw/movt pair or literal load of one of *vptrs*."""
    out = {}
    for reg in range(13):
        for v, sites in prog.movwt_values(reg).items():
            if v in vptrs:
                for s_ in sites:
                    out[s_] = v
    arr = np.array(sorted(vptrs), dtype=np.uint32)
    for pi in np.nonzero(np.isin(prog.tw, arr))[0].tolist():
        pool = prog.tlo + 4 * pi
        for va in prog.literal_loads(pool):
            out[va] = int(prog.tw[pi])
    return out


def init_objects(prog, model, root):
    """Every static object of a class deriving from *root*: ``[{id, a, award, b, timer,
    class, obj, ctor, ctor_call, init}]``. A constructor is a function that stores a class's
    vptr into its first argument; the static initialisers are the functions that call
    constructors (or pair a constructor call with a destructor's registration) on constant
    object addresses."""
    classes = [c for c in model if S.derives(model, c, root) and (model[c] or {}).get("vtable")]
    by_vptr = {model[c]["vtable"] + 8: c for c in classes}
    sites = vptr_sites(prog, set(by_vptr))
    ctor_class = {}
    for f in sorted({prog.func_start(s_) for s_ in sites}):
        st = prog.facts(f).stores.get(0)
        if isinstance(st, Val) and st.v in by_vptr:
            ctor_class[f] = by_vptr[st.v]
    funcs = collections.Counter()
    for f in ctor_class:
        for va in prog.callers(f):
            funcs[prog.func_start(va)] += 1
    # the atexit way too: a destructor in one of the first vtable slots, loaded into r1 and
    # handed over with the object the call before made
    dtor = {}
    for c in classes:
        for f in S.vslots(prog, model, c)[:6]:
            dtor.setdefault(f, set()).add(c)
    dtor = {f: sorted(cs)[0] for f, cs in dtor.items() if len(cs) == 1}
    for v, sites_ in prog.movwt_values(1).items():
        if v in dtor:
            for s_ in sites_:
                funcs[prog.func_start(s_)] += 1
    out, seen = [], set()
    for f, n in funcs.most_common():
        if n < 3 or f in ctor_class:
            continue
        calls = prog.facts(f).calls
        for i, c in enumerate(calls):
            d1, obj = c["args"].get("r1"), c["args"].get("r0")
            if c.get("tail") or not isinstance(d1, Val) or d1.v not in dtor \
                    or not isinstance(obj, Val):
                continue
            for k in range(1, 4):
                if i - k < 0:
                    break
                pc_ = calls[i - k]
                if isinstance(pc_["args"].get("r0"), Val) and pc_["args"]["r0"].v == obj.v:
                    ctor_class.setdefault(pc_["target"], dtor[d1.v])
                    break
        for c in calls:
            cls = ctor_class.get(c["target"])
            obj = c["args"].get("r0")
            if cls is None or c.get("tail") or not isinstance(obj, Val) \
                    or not prog.is_address(obj.v) or obj.v in seen:
                continue
            seen.add(obj.v)
            a = c["args"]
            if not isinstance(a.get("r1"), Val):
                # a constructor with no arguments: the ids are the constants it hands its
                # base constructor (Jurassic Park LE hands a descriptor filled at run time)
                inner = [x for x in prog.facts(c["target"]).calls
                         if x["args"].get("r0") == THIS and isinstance(x["args"].get("r1"), Val)]
                if inner:
                    a = inner[0]["args"]

            def val(k, a=a):
                return a[k].v if isinstance(a.get(k), Val) else None
            rid = val("r1")
            if rid is not None and rid > 0xFFFF and prog.is_address(rid):
                rid = None               # a pointer to a descriptor filled at run time
            out.append({"id": rid, "a": val("r2"), "award": val("r3"), "b": val("sp0"),
                        "timer": val("sp4"), "class": cls, "obj": obj.v,
                        "ctor": c["target"], "ctor_call": c["va"], "init": f})
    return out


# ---- engine functions ---------------------------------------------------------------------------
def _is_stub(prog, f):
    return ((prog.word(f) or 0) & 0xFFFFF000) == 0xE28FC000          # add ip, pc, ... (PLT)


def find_mode_getter(prog, ids):
    """``(function, id register)``: the callee most of whose callers pass a constant mode or
    rule id (in r0 or r1) and that calls something in its first instructions (the
    manager's getter). ``(None, None)`` when nothing does."""
    ids_arr = np.array(sorted(i for i in ids if i is not None), dtype=np.int64)
    if not len(ids_arr):
        return None, None
    best = (0, None, None)
    for reg in (0, 1):
        _sites, tgts, vals = prog.call_constants(reg)
        good = np.isin(vals, ids_arr)
        cnt = collections.Counter(tgts[good].tolist())
        for f, n in cnt.most_common(40):
            if n < 10 or _is_stub(prog, f):
                continue
            tot = len(prog.callers(f))
            if n < 0.5 * tot:
                continue
            if not any(S.decode(prog.word(f + 4 * j), f + 4 * j)[0] == "bl" for j in range(12)):
                continue
            if n > best[0]:
                best = (n, f, reg)
    return best[1], best[2]


def starter_slots(prog, getter, reg):
    """``{(id, slot): [call VA]}``: ``getter(id)`` followed by a virtual call on the result."""
    out = collections.defaultdict(list)
    for va in prog.callers(getter):
        rid = prog.const_before(va, reg)
        if rid is None:
            continue
        slot = None
        for k in range(1, 13):
            d = S.decode(prog.word(va + 4 * k), va + 4 * k)
            if d[0] == "ldri" and d[3] > 0 and d[3] % 4 == 0 and d[1] == d[2]:
                slot = d[3] // 4
            if d[0] == "blx" and slot is not None:
                break
            if d[0] == "bl":
                slot = None
                break
        if slot is not None:
            out[(rid, slot)].append(va)
    return out


def adds_with_carry(prog, f, n=40):
    """The callee adds with carry near its start: a 64-bit sum (an award ADD)."""
    return any(((prog.word(f + 4 * i) or 0) & 0x0DE00000) == 0x00A00000 for i in range(n))


def find_award_add(prog, own_facts):
    """The award add: of the callees the modes' own virtuals hand a fresh 64-bit constant
    (r2 at least 1,000, r3 = 0), the most frequent that adds with carry."""
    cnt = collections.Counter()
    for _cls, _k, _f, t in own_facts:
        for call in t.calls:
            lo, hi = call["args"].get("r2"), call["args"].get("r3")
            if isinstance(lo, Val) and isinstance(hi, Val) and hi.v == 0 and lo.v >= 1000 \
                    and lo.fresh(call["va"]) and hi.fresh(call["va"]):
                cnt[call["target"]] += 1
    for t, _n in cnt.most_common(8):
        if adds_with_carry(prog, t):
            return t
    return None


def award_field(prog, model, objs, modes, null):
    """The field a rule keeps its award record in: in the chain of base constructors, the one
    that calls a function with its entry r3 (the award id) and stores the result into a field
    of this (TMNT +0x30). None when there is no such store."""
    firsts = collections.Counter()
    for o in modes[:40]:
        t = prog.facts(o["ctor"])
        f1 = next((c["target"] for c in t.calls if c["args"].get("r0") == THIS), None)
        if f1:
            firsts[f1] += 1
    start = next((o["ctor"] for o in objs if o["class"] == null), None)
    todo = [f for f in [start] + [f for f, _n in firsts.most_common(3)] if f]
    seen = []
    while todo and len(seen) < 12:
        fn = todo.pop(0)
        if fn in seen:
            continue
        seen.append(fn)
        t = prog.facts(fn, entry_args=True)
        for c in t.calls:
            if c["args"].get("r0") != Sym("arg", 3):
                continue
            for va in range(c["va"] + 4, min(t.end, c["va"] + 40), 4):
                d = S.decode(prog.word(va), va)
                if d[0] == "stri" and d[1] == 0 and d[2] != 13 and d[3] > 0:
                    return d[3]
                if d[0] in ("bl", "blx") or (d[0] in ("mov", "movw", "movr", "ldri", "ldrlit")
                                              and d[1] == 0):
                    break
        nxt = next((c["target"] for c in t.calls if c["args"].get("r0") == THIS), None)
        if nxt:
            todo.insert(0, nxt)
    return None


# ---- the reader ---------------------------------------------------------------------------------
def kind_words(k):
    if k is None:
        return "?"
    names = [(4, "multiball"), (8, "timed"), (16, "hurry-up"), (2, "mode"), (1, "rule"),
             (32, "exclusive")]
    return "+".join(n for b, n in names if k & b) or "mode"


def _cond_reason(v):
    return ("it is set on one path only (a conditional instruction), so it may be a limit "
            "rather than the number itself")


def read(prog, model=None, step=None, cancel=None):
    """:class:`.stock_scan.Reading` of a C++ rule title. *step(fraction, text)* reports
    progress; *cancel()* returning True raises :class:`Cancelled`. Raises
    :class:`.stock_scan.ScanError` when the program has no C++ rule manager."""
    say = step or (lambda f, t="": None)

    def check():
        if cancel is not None and cancel():
            raise Cancelled()

    say(0.02, "Reading the program's classes")
    if model is None:
        model = S.class_model(prog)
    check()
    fam = family(model)
    if fam is None:
        raise S.ScanError("no C++ rule manager in this game program")
    root = fam[0]
    reading = S.Reading(fam[0])
    say(0.25, "Finding the modes")
    objs = init_objects(prog, model, root)
    check()
    fw = set(FRAMEWORK) | {c for c in model if c.endswith("_null")}
    modes = [o for o in objs if S.derives(model, o["class"], "cmode") and o["class"] not in fw]
    null = "crule_null" if root == "crule" else "cmode_null"
    say(0.35, "Finding the engine")
    get_adj, adjt = S.find_get_adjustment(prog)
    adj = {}
    if adjt is not None:
        adj = {i: adjt.entry(i) for i in range(adjt.count)}
    ids = {o["id"] for o in objs if o["id"] is not None}
    getter, getter_reg = find_mode_getter(prog, ids)
    starts = starter_slots(prog, getter, getter_reg) if getter else {}
    check()
    mode_classes = sorted({o["class"] for o in modes})
    held = collections.defaultdict(set)
    facts = {}
    own_facts = []
    for c in mode_classes:
        base, own = S.own_slots(prog, model, c)
        facts[c] = (base, [(k, f, prog.facts(f), S.const_return(prog, f)) for k, f in own])
        for k, f, t, _cr in facts[c][1]:
            own_facts.append((c, k, f, t))
        for f in S.vslots(prog, model, c):
            held[f].add(c)
    check()
    award_add = find_award_add(prog, own_facts)
    award_off = award_field(prog, model, objs, modes, null) if root == "crule" else None
    say(0.45, "Finding the modes' roles")

    # title: the slot most classes override with a distinct constant return
    cnt = collections.defaultdict(list)
    for c, (_b, fs) in facts.items():
        for k, _f, _t, cr in fs:
            if cr:
                cnt[k].append(cr[0])
    title_slot = max(cnt, key=lambda k: (len(set(cnt[k])), len(cnt[k]))) if cnt else None
    if title_slot is not None and len(set(cnt[title_slot])) < max(3, len(mode_classes) // 3):
        title_slot = None

    # start: the slot getter(mode id)->v[k] calls that most modes override and that adds an award
    mode_ids = {o["id"] for o in modes}
    votes = collections.Counter(s for (rid, s) in starts if rid in mode_ids)
    overridden = collections.Counter(k for c in facts for k, _f, _t, _c in facts[c][1])
    start_slot = None
    for s_, _n in votes.most_common():
        if overridden[s_] >= 0.5 * len(mode_classes) and award_add and any(
                call["target"] == award_add for c in facts for k, _f, t, _cr in facts[c][1]
                if k == s_ for call in t.calls):
            start_slot = s_
            break

    # reset (crule): the slot whose overrides store the most award-like constants (strd)
    reset_slot = None
    if award_off is not None:
        rv = collections.Counter()
        for c, (_b, fs) in facts.items():
            for k, _f, t, _cr in fs:
                rv[k] += sum(1 for _va, lo, hi, _bs, _o in t.strd64
                             if hi.v == 0 and lo.v >= 1000 and lo.v % 10 == 0)
        rv.pop(start_slot, None)
        if rv and rv.most_common(1)[0][1]:
            reset_slot = rv.most_common(1)[0][0]

    timer_slots = _timer_slots(prog, model)
    tmodel = _timer_object_model(prog, model, facts)

    reading.engine = {"get_adjustment": get_adj, "award_add": award_add, "mode_getter": getter,
                      "start_slot": start_slot, "title_slot": title_slot}
    if award_off is not None:
        reading.engine["award_field"] = award_off
    if not modes:
        reading.notes.append("no mode objects were found in this game program")
    roles = {start_slot: "start", reset_slot: "reset"}
    roles.pop(None, None)
    for k, name in timer_slots.items():
        roles.setdefault(k, name)

    by_id = collections.Counter(o["id"] for o in modes)
    next_free = 1000
    ordered = sorted(modes, key=lambda o: (o["id"] is None, o["id"] or 0, o["ctor_call"]))
    for n_done, o in enumerate(ordered):
        check()
        say(0.5 + 0.45 * n_done / max(1, len(ordered)),
            "Mode %d of %d" % (n_done + 1, len(ordered)))
        c = o["class"]
        mid = o["id"]
        if mid is None or by_id[mid] > 1:
            while next_free in by_id:
                next_free += 1
            mid, next_free = next_free, next_free + 1
        base, fs = facts[c]
        title = None
        for k, _f, _t, cr in fs:
            if k == title_slot and cr:
                title = cr
        m = S.ModeRead(mid, c, S.class_words(c), o["obj"], model[c]["vtable"],
                       title[0] if title else None)
        m.facts.append("ctor a %s award %s b %s timer %s   # kind %s (%s), ctor 0x%x called at "
                       "0x%x; %s%s" % (
                           o["a"], o["award"], o["b"], "-" if o["timer"] is None else o["timer"],
                           o["a"], kind_words(o["a"]) if root == "crule" else "?", o["ctor"],
                           o["ctor_call"], " <- ".join([c] + S.chain_of(model, c)),
                           "" if mid == o["id"] else
                           "; the id is not a constant of the constructor, so this table "
                           "numbers it"))
        if title:
            m.add("title_msg", title[0], title[1], title[2], "word", "v[%d] returns it" % title_slot)
        for (rid, slot), vas in sorted(starts.items()):
            if rid == o["id"] and mid == o["id"] and slot == start_slot:
                m.facts.append("start start: the mode getter(%d) at %s then v[%d]" % (
                    rid, ",".join("0x%x" % v for v in vas[:4]), slot))
        _mode_rows(prog, model, m, o, c, fs, roles, get_adj, adj, award_add, award_off,
                   timer_slots, tmodel, held, set(mode_classes))
        m.facts.append("# overrides: %s" % " ".join("v[%d]=0x%x" % (k, f) for k, f, _t, _c in fs))
        reading.modes.append(m)
    S.settle_shared(reading)
    rules = [o for o in objs if o not in modes and o["class"] not in fw]
    if rules:
        reading.notes.append("rules that are not modes: %s" % " ".join(
            "%s=%s" % (o["id"], o["class"]) for o in rules))
    say(1.0, "")
    return reading


def _timer_slots(prog, model):
    """``{slot: key}`` of a ``cmode_manager`` title's timer slots: the slots ``cmode_timed``
    adds to ``cmode`` that return a constant there and whose base function ``cmode_timed``'s
    own code checks for (the compiler inlines the base's constant behind a compare of the
    mode's slot with the base function's address, so that address shows in the code). The
    one checked by the most functions (then the biggest default, then the lowest slot) is the
    duration, ``timer.seconds``."""
    base = S.vslots(prog, model, "cmode")
    tim = S.vslots(prog, model, "cmode_timed")
    if not base or len(tim) <= len(base):
        return {}
    own = {f for k, f in enumerate(tim) if not (k < len(base) and base[k] == f)}
    checked = {}
    for k in range(len(base), len(tim)):
        cr = S.const_return(prog, tim[k])
        if not cr or cr[0] <= 0:
            continue
        users = {prog.func_start(r) for r in prog.references(tim[k])} & own
        if users:
            checked[k] = (len(users), cr[0])
    if not checked:
        return {}
    seconds = max(checked, key=lambda k: (checked[k][0], checked[k][1], -k))
    return {k: "timer.seconds" if k == seconds else "timer.v%d" % k for k in sorted(checked)}


def _timer_object_model(prog, model, facts):
    """A ``crule_manager`` title's timer: ``{"field", "feed", "pair"}`` - the field of a timed
    mode holding its timer object, the timer virtuals ``cmode_timed`` feeds a number
    (``{slot: default}``) and the two timer slots fed the duration. None without one."""
    if "cmode_timed" not in model or not S.derives(model, "cmode", "crule"):
        return None
    _cb, cown = S.own_slots(prog, model, "cmode_timed")
    objc = collections.Counter()
    best = (0, None)
    for _k, f in cown:
        t = prog.facts(f)
        for vc in t.vcalls:
            if isinstance(vc["obj"], Sym) and vc["obj"].t[0] == "field":
                objc[vc["obj"].t[1]] += 1
        nconst = sum(1 for vc in t.vcalls if isinstance(vc["obj"], Sym)
                     and vc["obj"].t[0] == "field" and isinstance(vc["args"].get("r1"), Val)
                     and vc["args"]["r1"].v < 100000)
        if nconst > best[0]:
            best = (nconst, t)
    if not objc or best[1] is None:
        return None
    field = objc.most_common(1)[0][0]
    feed = {}
    for vc in best[1].vcalls:
        if vc["obj"] == Sym("field", field) and isinstance(vc["args"].get("r1"), Val) \
                and vc["args"]["r1"].v < 100000:
            feed[vc["slot"]] = vc["args"]["r1"].v
    if not feed:
        return None
    # the duration: the two timer slots mode classes most often feed from ONE of their fields
    pairs = collections.Counter()
    for _c, (_b, fs) in facts.items():
        for _k, _f, t, _cr in fs:
            grp = collections.defaultdict(set)
            for vc in t.vcalls:
                a1 = vc["args"].get("r1")
                if vc["obj"] == Sym("field", field) and isinstance(a1, Sym) \
                        and a1.t[0] == "field":
                    grp[a1.t[1]].add(vc["slot"])
            for sls in grp.values():
                if len(sls) == 2:
                    pairs[tuple(sorted(sls))] += 1
    pair = list(pairs.most_common(1)[0][0]) if pairs else None
    if pair is None:
        # no class feeds two slots from one field (Munsters: the leaf passes immediates):
        # the two slots every class feeds with EQUAL values are the duration
        vals = collections.defaultdict(dict)
        for c, (_b, fs) in facts.items():
            for _k, _f, t, _cr in fs:
                for vc in t.vcalls:
                    if vc["obj"] == Sym("field", field) and isinstance(vc["args"].get("r1"), Val):
                        vals[c][vc["slot"]] = vc["args"]["r1"].v
        agree = collections.Counter()
        for c, d in vals.items():
            sl = sorted(d)
            for i in range(len(sl)):
                for j in range(i + 1, len(sl)):
                    agree[(sl[i], sl[j])] += 1 if d[sl[i]] == d[sl[j]] else -100
        good = [(n, pr) for pr, n in agree.items() if n >= 2]
        if good:
            pair = list(max(good)[1])
    return {"field": field, "feed": feed, "pair": pair}


def _other_stores(fs, field, ctor_site):
    """Constant stores into *field* by the class's own virtuals: ``[_Stored]``."""
    out = []
    for _k, _f, t, _cr in fs:
        v = t.stores.get(field)
        if isinstance(v, Val) and tuple(v.sites) != ctor_site:
            out.append(_Stored(v, t, t.store_at.get(field)))
    return out


class _Stored:
    """A constant stored into a field: the value, the function (facts) and the store."""
    __slots__ = ("v", "facts", "at")

    def __init__(self, v, facts, at):
        self.v, self.facts, self.at = v, facts, at


_UNDECODED_TIMER = ("which of the timer's settings this is (its length, a warning, a grace "
                    "period) isn't decoded")


def _undecoded_timer(key):
    """A timer number the reader couldn't name: ``timer.v<slot>``, not ``timer.seconds``."""
    return key.split("@")[0].startswith("timer.v")


def _also_read(prog, v, facts, consumer):
    """Why tracked constant *v* isn't only the number read at *consumer* (a store or a call
    in *facts*' function): the register its instruction sets is read somewhere else too, so
    editing the instruction would change that as well. "" when it is read there alone."""
    if consumer is None or consumer == [] or consumer == [None]:
        return "where the value is used isn't known"
    if S.kind_of(v)[0][0] == "code":
        return ""
    extra = S.other_uses(prog, v, facts, consumer)
    if not extra:
        return ""
    return ("the same instruction also feeds %s%s, so changing it would change more than this "
            "number" % (", ".join("0x%x" % x for x in extra[:3]),
                        " and more" if len(extra) > 3 else ""))


#: how far before the call a constant handed to it may be made (the single-read check in
#: :func:`_also_read` is what makes it the call's own; this keeps the instruction nearby)
NEAR = 128


def _handed_only(prog, v, facts, calls):
    """Why constant *v* handed to *calls* isn't only their number: made far from them, or its
    register read elsewhere too (:func:`_also_read`). "" when it is theirs alone."""
    if not all(v.fresh(c, NEAR) for c in calls):
        return "the value is made well before the call, where other code may use it too"
    return _also_read(prog, v, facts, calls)


def _word_row(m, key, v, comment, shared=0, why_unsure=""):
    """A row for tracked constant *v*: ``word`` when its kind is one the app writes and nothing
    makes it uncertain, ``uncertain`` with the reason otherwise, ``code`` when it is built by
    instructions (not one word)."""
    kind, words = S.kind_of(v)
    if kind[0] == "code":
        return m.add(key, v.v, kind, [], "code", "%s; the value is built by instructions, not "
                     "held in one word" % comment, shared)
    if v.cond and not why_unsure:
        why_unsure = _cond_reason(v)
    if _undecoded_timer(key) and not why_unsure:
        why_unsure = _UNDECODED_TIMER
    if why_unsure:
        return m.add(key, v.v, kind, words, "uncertain", "%s; %s" % (why_unsure, comment), shared)
    return m.add(key, v.v, kind, words, "word", comment, shared)


def _mode_rows(prog, model, m, o, c, fs, roles, get_adj, adj, award_add, award_off, timer_slots,
               tmodel, held, mode_classes):
    ctor_t = prog.facts(o["ctor"])
    fields = ctor_t.stores
    slots = S.vslots(prog, model, c)
    tim = S.vslots(prog, model, "cmode_timed")

    def shared_of(fn):
        n = len(held.get(fn, set()) & mode_classes)
        return n if n > 1 else 0

    def role(k):
        return roles.get(k, "v%d" % k)

    # a cmode_manager title's timer slots: the constant this mode returns, the base's
    # default, or (below) an operator setting read there
    if timer_slots and S.derives(model, c, "cmode_timed"):
        for k, key in sorted(timer_slots.items()):
            if k >= len(slots):
                continue
            fn = slots[k]
            r = S.const_return(prog, fn)
            if k < len(tim) and fn == tim[k] and r:
                users = len(held.get(fn, set()) & mode_classes)
                m.add(key, r[0], ("code", fn), [], "code",
                      "the default every timed mode without its own shares: v[%d] 0x%x "
                      "returns %d for %d mode(s); change it with a hook" % (k, fn, r[0], users),
                      users)
            elif r:
                m.add(key, r[0], r[1], r[2], "uncertain" if _undecoded_timer(key) else "word",
                      "%sv[%d] returns it" % (_UNDECODED_TIMER + "; " if _undecoded_timer(key)
                                              else "", k), shared_of(fn))
            elif not any(call["target"] == get_adj for call in prog.facts(fn).calls):
                d0 = S.decode(prog.word(fn), fn)
                if d0[0] == "ldri" and d0[1] == 0 and d0[2] == 0:
                    m.add(key, None, ("code", fn), [], "code",
                          "v[%d] reads the object's field +0x%x; set elsewhere, not measured"
                          % (k, d0[3]))
                else:
                    m.add(key, None, ("code", fn), [], "code", "v[%d] computes it" % k)

    for k, f, t, _cr in fs:
        r = role(k)
        sh = shared_of(f)
        # award values a crule reset stores into the award record (strd of a constant pair)
        if award_off is not None:
            on_award = any(call["args"].get("r0") == Sym("field", award_off) for call in t.calls)
            seen_sites = collections.OrderedDict()
            for va, lo, hi, _bs, _off in t.strd64:
                if not on_award or hi.v != 0 or lo.v < 1000 or lo.v % 10 \
                        or not all(va - 64 <= x[0] < va for x in lo.sites):
                    continue
                seen_sites.setdefault(tuple(lo.sites), []).append(va)
            for sites, uses in seen_sites.items():
                lo = next(x for va, x, _h, _b, _o in t.strd64 if tuple(x.sites) == sites)
                _word_row(m, "%s.award_value" % r, lo,
                          "v[%d] stores it into the award record (strd at %s)%s" % (
                              k, ",".join("0x%x" % u for u in uses),
                              "; one word, stored %d times" % len(uses) if len(uses) > 1 else ""),
                          sh, why_unsure="which part of the award record this is (a score, a "
                                         "step, a limit) isn't decoded")
        # a crule title's timer: its timer object's virtuals fed from a field or a constant
        if tmodel is not None:
            _timer_feed_rows(prog, m, o, k, t, ctor_t, fs, tmodel, sh)
        for call in t.calls:
            a = call["args"]
            if award_add and call["target"] == award_add:
                lo, hi = a.get("r2"), a.get("r3")
                key = "%s.caward_add" % r
                where = "v[%d] call 0x%x" % (k, call["va"])
                if call.get("cond"):
                    m.add(key, lo.v if isinstance(lo, Val) else None, ("code", call["va"]), [],
                          "code", "%s: the call itself is conditional" % where, sh)
                elif isinstance(lo, Val) and isinstance(hi, Val) and hi.v == 0:
                    _word_row(m, key, lo, where, sh,
                              why_unsure=_handed_only(prog, lo, t, [call["va"]]))
                elif isinstance(lo, Sym) and lo.t[0] == "field" and lo.t[1] in fields:
                    fv = fields[lo.t[1]]
                    others = _other_stores(fs, lo.t[1], tuple(fv.sites))
                    _word_row(m, key, fv, "%s adds field +0x%x, which the constructor 0x%x "
                              "stores" % (where, lo.t[1], o["ctor"]), sh,
                              why_unsure="other code of this mode also sets the field"
                              if others else _also_read(prog, fv, ctor_t,
                                                        ctor_t.store_at.get(lo.t[1])))
                else:
                    m.add(key, None, ("code", call["va"]), [], "code",
                          "%s: the value is computed before the call" % where, sh)
            elif get_adj and call["target"] == get_adj:
                v = a.get("r0")
                if not isinstance(v, Val):
                    continue
                e = adj.get(v.v)
                if e is None:
                    continue
                kd, words = S.kind_of(v)
                key = r if r.startswith("timer.") else "%s.adjustment" % r
                m.add(key, e["default"], ("adj", e["name"], v.v), words, "adjustment",
                      "v[%d] call 0x%x; the id is %s, range %s..%s" % (
                          k, call["va"], S.fmt_kind(kd), e["min"], e["max"]), sh)


def _timer_feed_rows(prog, m, o, k, t, ctor_t, fs, tm, sh):
    fields = ctor_t.stores
    fed = collections.OrderedDict()           # source -> [(timer slot, VA of the call)]
    for vc in t.vcalls:
        if vc["obj"] != Sym("field", tm["field"]):
            continue
        v = vc["args"].get("r1")
        if isinstance(v, Sym) and v.t[0] == "field":
            src = ("f", v.t[1])
        elif isinstance(v, Val):
            src = ("c", v)
        else:
            continue
        fed.setdefault(src, []).append((vc["slot"], vc["va"]))
    # only the timer virtuals cmode_timed itself feeds a number (a duration), not its flags
    fed = collections.OrderedDict((s_, sl) for s_, sl in fed.items()
                                  if any(tm["feed"].get(x, 0) >= 2 for x, _va in sl))
    pair = tm["pair"] or []

    def key_for(sls):
        if pair and (sorted(sls) == pair or (len(sls) == 1 and sls[0] in pair)):
            return "timer.seconds"
        return "timer.v%s" % "_".join(str(x) for x in sorted(sls))

    # one number the game keeps at several sites (Munsters: the duration is two mov words,
    # one per timer virtual) is ONE row: group constant sources by (key, value, kind)
    groups = collections.OrderedDict()
    for src, fed_at in fed.items():
        sls = [x for x, _va in fed_at]
        if src[0] == "c":
            v = src[1]
            gk = (key_for(sls), v.v, S.kind_of(v)[0][0], v.cond)
            groups.setdefault(gk, []).append((v, sls, [va for _x, va in fed_at]))
        else:
            groups.setdefault(("f", src[1], tuple(sls)), []).append((src, sls, None))
    for gk, members in groups.items():
        if gk[0] == "f":
            fo = gk[1]
            sls = members[0][1]
            key = key_for(sls)
            fv = fields.get(fo)
            if fv is None:
                m.add(key, None, ("code", t.start), [], "code",
                      "v[%d] hands field +0x%x to timer v%s; the constructor doesn't store a "
                      "constant there" % (k, fo, sls), sh)
                continue
            others = _other_stores(fs, fo, tuple(fv.sites))
            same = [x for x in others if x.v.v == fv.v]
            differ = [x for x in others if x.v.v != fv.v]
            comment = "the constructor 0x%x stores it in +0x%x; v[%d] hands it to timer v%s" % (
                o["ctor"], fo, k, sls)
            mine = _Stored(fv, ctor_t, ctor_t.store_at.get(fo))
            if same and not differ and all(S.kind_of(x.v)[0][0] == S.kind_of(fv)[0][0]
                                           for x in same):
                _multi_row(prog, m, key, [(x.v, x.facts, [x.at]) for x in [mine] + same],
                           comment + "; also stored by %d other function(s)" % len(same), sh)
            else:
                _word_row(m, key, fv, comment, sh,
                          why_unsure="other code of this mode stores another value there"
                          if differ else _also_read(prog, fv, ctor_t, mine.at))
        else:
            sls = sorted({x for _v, s_, _c in members for x in s_})
            key = gk[0]
            comment = "v[%d] hands it to timer v%s" % (k, sls)
            if len(members) > 1:
                _multi_row(prog, m, key, [(v, t, c) for v, _s, c in members],
                           comment + "; one number at %d sites, changed together"
                           % len(members), sh)
            else:
                v, _s, calls = members[0]
                _word_row(m, key, v, comment, sh, why_unsure=_handed_only(prog, v, t, calls))


def _multi_row(prog, m, key, sources, comment, sh):
    """One row for one number held at several sites of one kind: *sources* =
    ``[(Val, facts of its function, [VAs that read it as this number])]``."""
    vals = [v for v, _t, _c in sources]
    kinds = [S.kind_of(v) for v in vals]
    k0 = kinds[0][0][0]
    if k0 not in ("imm", "movw", "movwt") or any(k[0][0] != k0 for k in kinds) \
            or any(v.cond for v in vals) or len({v.v for v in vals}) != 1:
        return _word_row(m, key, vals[0], comment, sh,
                         why_unsure="the same number is also held elsewhere in another form")
    seen, sites, words = set(), [], []
    for (kd, w) in kinds:
        if kd[1:] in seen:
            continue
        seen.add(kd[1:])
        sites.extend(kd[1:])
        words.extend(w)
    why = next((r for r in (_also_read(prog, v, t, c) for v, t, c in sources) if r), "")
    if not why and _undecoded_timer(key):
        why = _UNDECODED_TIMER
    if why:
        return m.add(key, vals[0].v, (k0,) + tuple(sites), words, "uncertain",
                     "%s; %s" % (why, comment), sh)
    return m.add(key, vals[0].v, (k0,) + tuple(sites), words, "word", comment, sh)
