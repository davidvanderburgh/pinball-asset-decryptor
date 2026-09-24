"""The switch drain and the end of ball of every Spike 2 build's FRAMEWORK: the fallback core of a
port for a build whose rules give no shot dispatch or end of ball that a reference port places.

Every Spike 2 build runs one of two framework generations (:func:`.portgen.generation`, told apart
by the event bus's id bound). Each generation's switch code is the SAME code in every build of it:
measured 2026-09-23 on the 34 latest builds, generation B's switch drain matches The Beatles 1.29's
(= Godzilla Pro 1.15's) 96 words in all 25 B builds under the strict mask, and generation A's matches
TMNT Pro 1.58's 114 words in all 9 A builds. So each function is found by ONE masked signature per
generation (a recipe-style chain: masks and a hash, never the code), and what a port needs is read off
the code that matched:

SHOTS FROM THE SWITCH DRAIN (runtime: ``site switch_edge``). The drain runs once a tick and hands
every switch edge the node boards reported to the game. For each edge it calls one small per-switch
function with r0 = the switch id (B: for every edge, after it stored the edge's new level in the
switch's record; A: for every edge the game acts on, before it stores the level). That function is
hooked; the runtime reads the level and the switch's descriptor through the port's values and counts a
HIT on the edge the game's own handler runs on (a switch whose handler runs on both edges, or that has
none, on the edge to its active level), when the game's mode mask lets the switch through - the test
the drain itself applies before it runs a switch's handler. `switch <id> <mask> <name>` lines name the
playfield switches, with the game's own names (its device table), less the switches that are not shots
(trough, shooter lane, flipper buttons and EOS, cabinet and coin door switches...).

THE END OF BALL FROM THE EVENT BUS (runtime: ``value ball_end_event`` with ``site hook_dispatch``).
The framework ends a ball in ONE function that dispatches, in this order, (a+1, a+2, a, a-13, a-12):
the end of ball is a. Measured: 0x34 on every generation-B build, 0x30 on every generation-A build
(where 0x34 is the tick's exit, dispatched 60 times a second - never carry B's id to A).

THE PLAYER UP (``data cur_player``) where no reference places it: the byte whose value (through one
call) indexes the scores (``scores[f(player) - 1]``): on all eight A builds where a reference placed
cur_player this finds the same byte, and it finds Batman 66's and Stranger Things'.
"""
import re
import struct
from collections import Counter

import numpy as np

from . import portgen as G

# ---- the framework's switch code, per generation ---------------------------------------------------
#: One chain per function: (first masked word, second masked word, masks, words, hash), as
#: portgen's recipes keep them. B from The Beatles 1.29, A from TMNT Pro 1.58.
_CHAINS = {
    "B": {
        "drain": (3912060912, 3808464896, "fwfpwbffbwwfwfwfbffffffbffbfbffbffbfffffbfbffffffffffffbffffffffff"
                                          "ffffffbffffbffffbfbbfbbpffbfbb", 96, 8834338253406932929),
        "leaf": (3808440320, 3812634624, "wwfffwfwfffffff", 15, 7959545421294056730),
        "init": (3912060912, 3818938368, "ffpffffbffffffbfffbfffffbfffbwwwwfffwfwffbffbfbwfwfffbffffffffff", 64,
                 11922411848878501181),
    },
    "A": {
        "drain": (3912060912, 3808464896, "fwwffbfffpbpffbffbffbbffbffbffbfbfffffffbffbfffffbfbffffbfbfffffbff"
                                          "ffbpffbfffbffffffbfbfffffffffbffffffbfbfbfbfffb", 114, 7709488343730236700),
        "leaf": (3912056848, 3785375744, "ffbffwfwffff", 12, 441480613036365167),
        "desc": (3813670912, 3912056840, "ffbwwffbfwwfffffbff", 19, 4701941275102693686),
        "post": (3808477184, 3812671488, "wwfffffffbfbffbfffbffbfbffffffbffffffbfff", 41, 6524515012205943486),
    },
}

#: What each generation's code says, read off the reference (a strict match of the whole function
#: keeps every offset and size here the same in the target; only movw/movt immediates and branch
#: targets may differ, and those are read from the target):
#:   leaf_calls    drain words that are `bl <per-switch function>`
#:   count         (function, movw word, movt word) of the global holding the number of switches
#:   records       ... of the global pointing at the per-switch records (id-indexed)
#:   mode_mask     ... of the u16 mode mask the drain (B) / the handler post (A) tests
#:   desc_table    ... of the global pointing at the STATIC switch descriptors (A: the records)
#:   record_size   one record's bytes; level_at: the level byte (in the record, or, with level_via,
#:                 in the state the record points at from +level_via); level_before: 1 when the byte
#:                 still holds the level from before the edge when the per-switch function runs
#:   desc_via      the record holds a pointer to the switch's descriptor at this offset (None: the
#:                 record is the descriptor); flags_at / polarity_at / device_at / handler_at: the
#:                 descriptor's u16 edge flags (0x400 the level-0 edge, 0x800 the level-1 edge), its
#:                 u16 whose bit 2 says active high, its u16 device index, its u32 handler
SHAPES = {
    "B": dict(leaf_calls=(84,), count=("leaf", 0, 1), records=("leaf", 5, 7), mode_mask=("drain", 10, 14),
              desc_table=("init", 47, 49), record_size=0x20, level_at=0x18, level_via=None, level_before=0,
              desc_via=8, desc_size=0x28, flags_at=0x1a, polarity_at=0x1c, device_at=0x16, handler_at=0),
    "A": dict(leaf_calls=(86, 105), count=("desc", 3, 4), records=("desc", 9, 10), mode_mask=("post", 0, 1),
              desc_table=("desc", 9, 10), record_size=0x2c, level_at=1, level_via=0, level_before=1,
              desc_via=None, desc_size=0x2c, flags_at=0x1e, polarity_at=0x20, device_at=0x1a, handler_at=4),
}

#: a playfield switch whose name has one of these words is not a shot: the ball's way in and out,
#: the player's buttons, the flippers' end-of-stroke, the cabinet, and a mechanism's own position
NOT_SHOTS = re.compile(
    r"\b(TROUGH|SHOOTER|PLUNGER|LAUNCH|FLIPPER|FLIP|EOS|BUTTON|BUTTONS|COIN|DOOR|INTERLOCK|TILT|START|"
    r"SERVICE|DIP|ENCODER|DETECT|SENSE|SENSOR|VOLUME|HEADPHONE|JAM|MOTOR|HOME|AWAY|INDEX|POSITION|POS|"
    r"LOCATION|DIVERTER|GATE|LOCKDOWN|ACTION|OUTHOLE|DRAIN|QR|SCANNER|TICKET|NOTCH|TOURNAMENT|INVALID|"
    r"VIRTUAL|REFLEX|STOPPED|IGNORED|COMMAND|CB|MAG|RESET|TOPPER|UP/DOWN)\b|\b(UP|DOWN|DN)$")

#: the most `switch` lines a derived port gets: the runtime maps up to 64 (pad_mode_runtime.c
#: N_SWITCHES) and the shot masks are one bit each of 64
MAX_SWITCH_SHOTS = 64


def _find(elf, chain):
    """Every index where a chain's masked words (and hash) match."""
    v0, v1, masks, n, h = chain
    a = elf.arr
    m = G._masks_array(masks)
    idx = np.nonzero((a & np.uint32(m[0])) == np.uint32(v0))[0]
    idx = idx[idx + n <= len(a)]
    if len(idx):
        idx = idx[(a[idx + 1] & np.uint32(m[1])) == np.uint32(v1)]
    out = []
    for lo in range(0, len(idx), 4096):
        part = idx[lo:lo + 4096]
        rows = a[part[:, None] + np.arange(n)] & m
        out.extend(part[G._hash_rows(rows) == np.uint64(h)].tolist())
    return out


def _pair(elf, starts, where):
    fn, i, j = where
    return G.value_at(elf, "movw", starts[fn] + i, starts[fn] + j)


def drain(elf):
    """The framework's switch drain in a :class:`.portgen.Elf`: a dict (generation, drain, drain_size,
    leaf, count, records, mode_mask, desc_table and the shape's offsets), or None with no match."""
    cached = getattr(elf, "_switch_drain", False)
    if cached is not False:
        return cached
    out = None
    gen = G.generation(G.bus_bound(elf))
    shape, chains = SHAPES.get(gen), _CHAINS.get(gen)
    if shape and chains:
        starts = {}
        for name, chain in chains.items():
            hits = _find(elf, chain)
            if len(hits) != 1:
                starts = None
                break
            starts[name] = hits[0]
        if starts:
            leaf = elf.va(starts["leaf"])
            calls = [G.bl_dest(elf, starts["drain"] + k) for k in shape["leaf_calls"]]
            vals = {k: _pair(elf, starts, shape[k]) for k in ("count", "records", "mode_mask", "desc_table")}
            if all(c == leaf for c in calls) and None not in vals.values() and G.is_hooked_ok(elf, leaf):
                out = dict(shape, generation=gen, drain=elf.va(starts["drain"]),
                           drain_size=4 * len(chains["drain"][2]), leaf=leaf, **vals)
    elf._switch_drain = out
    return out


def static_count(elf, count_var):
    """The number of switches, as the framework's own initialiser sets it: `ldr rX, [<constant>]; str
    rX, [count_var]`, the constant read from the program. None when no such initialiser is found."""
    W = elf.words
    for kind, i, j in G.refs_to(elf, count_var):
        if kind != "movw":
            continue
        rc = (W[i] >> 12) & 0xF
        for k in range(j + 1, min(j + 4, len(W))):
            w = W[k]
            if (w & 0x0FF00FFF) == 0x05800000 and ((w >> 16) & 0xF) == rc:
                rs = (w >> 12) & 0xF                          # str rs, [rc]
                for m in range(k - 1, max(k - 8, 0), -1):     # ldr rs, [ra] with ra a movw/movt constant
                    u = W[m]
                    if (u & 0x0FF00FFF) == 0x05900000 and ((u >> 12) & 0xF) == rs:
                        ra = (u >> 16) & 0xF
                        lo = hi = None
                        for q in range(m - 1, max(m - 8, 0), -1):
                            x = W[q]
                            if ((x >> 12) & 0xF) != ra:
                                continue
                            if hi is None and (x & 0x0FF00000) == 0x03400000:
                                hi = G.movw_imm(x)
                            elif lo is None and (x & 0x0FF00000) == 0x03000000:
                                lo = G.movw_imm(x)
                        if lo is not None and hi is not None:
                            n = elf.word(hi << 16 | lo)
                            if n and 0 < n <= 512:
                                return n
                        break
    return None


def _device_tables(elf):
    """Candidate device tables (the 48-byte records whose +0x0c is a device's name): the pointer
    every `movw r3,#p; add r0,r0,r0,lsl #1; movt r3,#p; ldr r3,[r3]; add r0,r3,r0,lsl #4` accessor
    loads, read from the program."""
    a = elf.arr
    if len(a) < 8:
        return []
    k = np.nonzero((a[1:-3] == np.uint32(0xE0800080)) & (a[3:-1] == np.uint32(0xE5933000)) &
                   (a[4:] == np.uint32(0xE0830200)))[0]
    out = []
    for i in k.tolist():
        w0, w2 = int(a[i]), int(a[i + 2])
        if (w0 & 0x0FF0F000) == 0x03003000 and (w2 & 0x0FF0F000) == 0x03403000:
            tab = elf.word(G.movw_imm(w2) << 16 | G.movw_imm(w0))
            if tab and tab not in out:
                out.append(tab)
    return out


def _text(elf, va, cap=96):
    s = elf.cstring(va, cap) if va else None
    if not s or not all(32 <= c < 127 for c in s):
        return ""
    return s.decode("latin1")


def _device(elf, tab, dev):
    at = tab + 48 * dev
    name, image, cls = elf.word(at + 0x0C), elf.word(at + 0x18), elf.word(at + 0x20)
    if name is None or image is None or cls is None:
        return None
    return dict(name=_text(elf, name), image=_text(elf, image, 160), cls=cls & 0xFFFF)


def _names_b(elf, recs):
    """Generation B: [device dict or None] per descriptor, from the 48-byte device table (+0x0c the
    name, +0x18 the picture, +0x20 the class, 1 = a switch) that resolves the most of them."""
    best = None
    for tab in _device_tables(elf):
        named = []
        for r in recs:
            d = _device(elf, tab, r["device"]) if r["device"] else None
            named.append(d if d and d["cls"] == 1 and d["name"] else None)
        n = sum(1 for d in named if d)
        if best is None or n > best[0]:
            best = (n, named)
    return best


def _data_words(elf):
    for off, va, fsz, flags in elf.loads:
        if flags & 1:
            continue
        skip = (-va) % 4
        n = (fsz - skip) // 4
        if n > 8:
            yield va + skip, np.frombuffer(elf.b, dtype="<u4", count=n, offset=off + skip)


def _mapped(elf, arr):
    ok = np.zeros(len(arr), dtype=bool)
    for _off, va, fsz, _flags in elf.loads:
        ok |= (arr >= np.uint32(va)) & (arr < np.uint32(va + fsz))
    return ok


def _a_name(elf, rec):
    """A generation-A device record's name: +0x0c points at a cell of five name pointers (one per
    language, English first); +0x14 is the kind, 7 = a switch. "" when it is not a named switch."""
    kind, cell = elf.word(rec + 20), elf.word(rec + 12)
    if kind is None or kind & 0xFFFF != 7 or not cell:
        return ""
    s = elf.word(cell)
    return _text(elf, s) if s else ""


def _names_a(elf, recs):
    """Generation A: [device dict or None] per descriptor. The 24-byte device table has no pointer
    of its own on every build, so its base is VOTED: every record in the program's data that looks
    like a named switch device votes for (its address - 24 x each descriptor's device index); the
    base the most descriptors resolve through wins, and must beat the next by a clear margin (a
    table shifted by one record resolves all but the first or last)."""
    devs = sorted({r["device"] for r in recs if r["device"]})
    if not devs:
        return None
    cands = []
    for base, a in _data_words(elf):
        kind = (a[5:] & np.uint32(0xFFFF)) == np.uint32(7)
        cell = a[3:len(a) - 2]
        for k in np.nonzero(kind & _mapped(elf, cell))[0].tolist():
            if _a_name(elf, base + 4 * k):
                cands.append(base + 4 * k)
    if not cands:
        return None
    c = np.array(cands, dtype=np.int64)
    votes = Counter((c[:, None] - 24 * np.array(devs, dtype=np.int64)[None, :]).ravel().tolist())
    (tab, n), *rest = votes.most_common(2) + [(None, 0)]
    if n < max(8, len(devs) * 9 // 10) or (rest and rest[0][1] >= n):
        return None
    named = []
    for r in recs:
        nm = _a_name(elf, tab + 24 * r["device"]) if r["device"] else ""
        named.append(dict(name=nm, image="", cls=1) if nm else None)
    return sum(1 for d in named if d), named


def switches(elf, info=None):
    """Every switch the framework's static descriptors name: [dict(id, name, handler, flags,
    polarity, device, image)], id-ordered; [] when the tables cannot be read. (image: the picture
    the switch test draws it on - generation B only; "" on A.)"""
    info = info or drain(elf)
    if not info:
        return []
    base = elf.word(info["desc_table"])
    if not base:
        return []
    count = static_count(elf, info["count"]) or 256
    size = info["desc_size"]
    recs = []
    for sid in range(count):
        at = base + sid * size
        raw = [elf.word(at + 4 * k) for k in range(size // 4)]
        if None in raw:
            break
        b = struct.pack("<%dI" % len(raw), *raw)
        recs.append(dict(id=sid, handler=struct.unpack_from("<I", b, info["handler_at"])[0],
                         flags=struct.unpack_from("<H", b, info["flags_at"])[0],
                         polarity=struct.unpack_from("<H", b, info["polarity_at"])[0],
                         device=struct.unpack_from("<H", b, info["device_at"])[0]))
    best = (_names_a if info["generation"] == "A" else _names_b)(elf, recs)
    if best is None or best[0] < max(8, len([r for r in recs if r["device"]]) // 2):
        return []
    out = []
    for r, d in zip(recs, best[1]):
        if d:
            out.append(dict(r, name=d["name"], image=d["image"]))
    return out


def _playfield_image(sws):
    """The picture the playfield switches are drawn on: the commonest image among the switches that
    have a handler of the game's own, else among all, that is not one of the system's pictures."""
    for pool in ([s for s in sws if s["handler"]], sws):
        c = Counter(s["image"] for s in pool if s["image"] and not s["image"].startswith("System/"))
        if c:
            return c.most_common(1)[0][0]
    return None


def shot_switches(sws):
    """[(id, name)] of the playfield switches that are shots: drawn on the playfield picture, and not
    named as the ball's way in or out, a button, a flipper's end of stroke or a mechanism's position."""
    pic = _playfield_image(sws)
    out = []
    for s in sws:
        if s["id"] == 0 or (pic and s["image"] != pic) or NOT_SHOTS.search(" ".join(s["name"].upper().split())):
            continue
        out.append((s["id"], s["name"]))
    return out


def nice(name):
    """``LEFT ORBIT TARGET`` -> ``Left orbit target``, ``(G)ADGET TARGET`` -> ``(G)adget target``: the
    port's shot names are sentence case, the first letter capital."""
    name = " ".join(name.split()).lower()
    m = re.search(r"[a-z]", name)
    return name[:m.start()] + name[m.start()].upper() + name[m.start() + 1:] if m else name


# ---- the event bus: its dispatch and the end of ball ----------------------------------------------
def hook_dispatch(elf):
    """The event bus's dispatch (it starts `cmp r0, #<bound>; push`), or None."""
    bound = G.bus_bound(elf)
    if not bound:
        return None
    a = elf.arr
    hits = np.nonzero((a[:-1] == np.uint32(0xE3500000 | bound)) &
                      ((a[1:] & np.uint32(0xFFFF4000)) == np.uint32(0xE92D4000)))[0].tolist()
    if len(hits) != 1:
        return None
    va = elf.va(hits[0])
    return va if G.is_hooked_ok(elf, va) else None


def ball_end_event(elf):
    """(the end-of-ball bus id, how) from the one framework function that dispatches (a+1, a+2, a,
    a-13, a-12) in that order; (None, why) when no single function does."""
    disp = hook_dispatch(elf)
    if disp is None:
        return None, "the event bus's dispatch was not found"
    seqs = {}
    for k in G.bl_callers(elf, disp):
        f = G.func_start(elf, k)
        if f is not None:
            seqs.setdefault(f, []).append(G._regs_before(elf, k).get(0))
    found = set()
    for f, ids in seqs.items():
        for j in range(len(ids) - 4):
            x = ids[j:j + 5]
            if None in x:
                continue
            a = x[2]
            if x[0] == a + 1 and x[1] == a + 2 and x[3] == a - 13 and x[4] == a - 12:
                found.add((a, f))
    ids = {a for a, _f in found}
    if len(ids) != 1:
        return None, ("no framework function ends a ball the known way" if not ids else
                      "two ball-end sequences disagree (%s)" % ", ".join("0x%x" % a for a in sorted(ids)))
    a, f = sorted(found)[0]
    return a, ("the framework's end of ball at 0x%x dispatches bus 0x%x (its sequence 0x%x, 0x%x, 0x%x, then "
               "the bonus 0x%x, 0x%x) - drain a ball to prove it" % (elf.va(f), a, a + 1, a + 2, a, a - 13, a - 12))


# ---- the player up ---------------------------------------------------------------------------------
def _byte_loads(elf, i, back=8):
    """Globals loaded as a byte into r0 (movw/movt rX; ldrb r0, [rX]) in the `back` words before i."""
    W = elf.words
    out = set()
    for k in range(max(0, i - back), i):
        w = W[k]
        if (w & 0x0FF00000) != 0x03000000:
            continue
        rd = (w >> 12) & 0xF
        for j in range(k + 1, min(i, k + 6)):
            y = W[j]
            if (y & 0x0FF00000) == 0x03400000 and ((y >> 12) & 0xF) == rd:
                for m in range(j + 1, i):
                    if (W[m] & 0x0FFFFFFF) == (0x05D00000 | (rd << 16)):     # ldrb r0, [rd]
                        out.add(G.movw_imm(y) << 16 | G.movw_imm(w))
                break
    return out


def cur_player_via_scores(elf, scores):
    """(the current-player byte, how): the byte global whose value, through one call, indexes the
    scores - `ldrb r0, [P]; bl f; add rS, rS(scores), r0, lsl #2|3` - when exactly one does; else
    (None, why)."""
    if not scores:
        return None, "no scores to line it up with"
    W = elf.words
    found = {}
    for kind, i, j in G.refs_to(elf, scores):
        if kind != "movw":
            continue
        rb = (W[i] >> 12) & 0xF
        scaled = any((W[m] & 0x0FFFFFFF) in (0x00800100 | (rb << 16) | (rb << 12), 0x00800180 | (rb << 16) | (rb << 12))
                     for m in range(j + 1, min(j + 5, len(W))))
        if not scaled:
            continue
        for k in range(i - 1, max(i - 6, 0), -1):
            if (W[k] & 0x0F000000) == 0x0B000000:
                for p in _byte_loads(elf, k):
                    found.setdefault(p, []).append(elf.va(i))
                break
    if len(found) != 1:
        return None, ("no code indexes the scores by a byte" if not found else
                      "the scores are indexed by %d different bytes" % len(found))
    p, where = next(iter(found.items()))
    return p, ("the byte whose value indexes the scores (0x%x, %d place%s, e.g. 0x%x) - prove it with "
               "pm_player() in a game" % (scores, len(where), "" if len(where) == 1 else "s", where[0]))


# ---- the port lines ---------------------------------------------------------------------------------
def site_line(elf, name, va):
    return "site %-16s 0x%08x 0x%08x 0x%08x" % (name, va, elf.word(va), elf.word(va + 4))


def switch_source(elf, first_bit=0):
    """The switch-drain shot source for a port, as parts a port's sections take: dict(sites=[lines],
    data={name: address}, values=[(name, number)], mapped=[(switch id, shot mask, name)], how=words,
    notes=[...]), shot masks from 1 << first_bit; or dict(mapped=[], notes=[why]) when the drain or
    the switch table cannot be read."""
    info = drain(elf)
    if not info:
        return dict(mapped=[], notes=["the framework's switch drain was not found in this build"])
    shots = shot_switches(switches(elf, info))
    if not shots:
        return dict(mapped=[], notes=["the framework's switch table names no playfield switch here"])
    room = MAX_SWITCH_SHOTS - first_bit
    notes = []
    if len(shots) > room:
        notes.append("%d playfield switches; the port maps the first %d" % (len(shots), room))
        shots = shots[:room]
    names = Counter(nice(n) for _i, n in shots)
    mapped = []
    for k, (sid, name) in enumerate(shots):
        nm = nice(name)
        if names[nm] > 1:
            nm = "%s (%d)" % (nm, sid)
        mapped.append((sid, 1 << (first_bit + k), nm[:150]))
    g = info["generation"]
    how = ("the framework's per-switch call in its switch drain (generation %s: r0 = the switch id, called for %s) "
           "- press the switches to prove it" % (g, "every edge after the new level is stored" if not info["level_before"]
                                                 else "every edge the game acts on, before the level is stored"))
    values = [("switch_drain_size", info["drain_size"]), ("switch_record_size", info["record_size"]),
              ("switch_level_at", info["level_at"])]
    if info["level_via"] is not None:
        values.append(("switch_level_via", info["level_via"]))
    if info["level_before"]:
        values.append(("switch_level_before", 1))
    if info["desc_via"] is not None:
        values.append(("switch_desc_via", info["desc_via"]))
    values += [("switch_flags_at", info["flags_at"]), ("switch_polarity_at", info["polarity_at"])]
    return dict(
        sites=["#   switch_edge: %s" % how, site_line(elf, "switch_edge", info["leaf"]),
               "#   switch_drain: the drain itself, never hooked: an edge counts only when switch_edge is called "
               "from it", site_line(elf, "switch_drain", info["drain"])],
        data={"switch_records": info["records"], "switch_count": info["count"], "mode_mask": info["mode_mask"]},
        values=values, mapped=mapped, how=how, notes=notes, generation=g)


def switch_lines(mapped):
    """The `switch <id> <mask> <name>` lines of switch_source()'s mapping."""
    return ["switch %-4d %-18s %s" % (sid, "0x%x" % mask, name) for sid, mask, name in mapped]


def example_start_shot(mapped):
    """A shot a template mode can start on: the first switch named a target, else the first."""
    for _sid, _mask, name in mapped:
        if re.search(r"\b(target|tgt)\b", name, re.I):
            return name
    return mapped[0][2] if mapped else ""
