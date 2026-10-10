"""Godzilla's score panel: the colours the GAME PROGRAM paints it (PAD-507, DragonRR).

Every frame the score frame's update (LE 1.16: 0x1ae4ac, next to the constructor that looks
the panel's nodes up by path) fills each score box and then calls its Text's colour setter -
``Radium::Text`` vtable +0x40, a packed ``0xRRGGBBAA`` - with a colour it makes in code::

    the player who is up            gold  0xffdd44   movw rX, #0x44ff / movt rX, #0xffdd
    the other players in the game   grey  0x6c6b6a   movw rX, #0x6aff / movt rX, #0x6c6b
    PRESS START in an empty box     green 0x007f00   mov rA, #0xff ... movt rA, #0x007f
    INSERT COINS (no credits)       red   0x7f0000   mov rB, rA    ... movt rB, #0x7f00

(the green and the red share their low half, so the game makes one from the other: ``mov
rB, rA`` before either ``movt``).  The machine draws a box in its line's scene colour TIMES
that colour (emulator, stock LE 1.16 with these patched: PRESS START picked (32, 64, 255) drew
(19, 38, 153) = 0.6 x it, the InActiveScore line's grey; the player up picked magenta drew
(252, 0, 0) = the score line's yellow x it).  So the score shows the scene's yellow x gold and
the empty boxes 0.6 x green, and a scene edit alone - a Text colour, or a line's colour
profile - only ever scales the game's colour: DragonRR's grey score came up gold and his empty
boxes green.

So a kind of line the project changes takes its WHOLE colour from the program: its lines'
scene colour goes white (:func:`scene_ops`, a ``line_colour`` edit like PAD-438's) and the
program's word becomes the colour the machine is to show (:func:`program_colours`), rewritten
in place at its own size (a pair keeps its registers; ``mov rA, #0xff`` and ``mov rB, rA``
become ``movw``s), so nothing moves and the patch composes with every other edit of the
program.  A kind put back gets the scene's colour and the game's word back.  The colours the
project keeps, and the ones the Scenes window shows, are what the machine shows (:data:`SHOWN`
for the game's own).

Finding the words is structural, never by address: the shapes above, in the ONE function that
holds all four and calls a Text's colour setter.  Anything else - none, or two such
functions, or a word two shapes claim - and :func:`find` returns ``None``: writing a wrong
word into the game program is worse than leaving the colours alone.  Stock Godzilla LE 1.13 /
1.16 and Pro 1.15 / 1.16 all carry it, and the same panel scene (9d578751).  A program an
earlier Write changed holds the colours that Write chose; the project remembers them
(:data:`WRITTEN_KEY`) and :func:`find` is told (*known*), so the next Write finds them again.
A card built by another project's Write is not guessed at: build it from the original card.

The project keeps its colours in its sidecar (:data:`KEY`), only the ones changed; a line of
the panel with the individual files colour profile switched on (PAD-438) puts the profile on
the colours of its kind that were not picked by hand (:func:`wanted`), so a project whose
score lines went grey through the profile gets grey on the machine too.
"""

import struct

#: the sidecar key: ``{role: "#rrggbb"}``, the colours picked, as the machine is to show them
KEY = "score_colors"
#: the sidecar key: ``{role: ["#rrggbb", ...]}``, what this project's Writes put in the program
WRITTEN_KEY = "score_colors_written"

#: ``(role, label, the game's colour in its code)``, in the order the panel lists them
ROLES = (
    ("up", "Player who is up", (0xff, 0xdd, 0x44)),
    ("others", "Other players", (0x6c, 0x6b, 0x6a)),
    ("start", "PRESS START", (0x00, 0x7f, 0x00)),
    ("coins", "INSERT COINS", (0x7f, 0x00, 0x00)),
)
DEFAULTS = {r: rgb for r, _l, rgb in ROLES}
LABELS = {r: label for r, label, _rgb in ROLES}

#: the panel's two kinds of line and the roles each is painted in: a player's active box's
#: ``score``, and an ``InActiveScore_Instance`` (another player's score, or PRESS START /
#: INSERT COINS in an empty box)
GROUPS = {"up": ("up",), "rest": ("others", "start", "coins")}
GROUP_OF = {r: g for g, rs in GROUPS.items() for r in rs}
#: their lines' colour in the panel's scene, on every Godzilla build read (LE 1.13 / 1.16, Pro
#: 1.15 / 1.16): the score yellow, the other boxes 0.6 grey
SCENE_RGB = {"up": (252 / 255.0, 1.0, 0.0), "rest": (0.6, 0.6, 0.6)}
#: what the machine shows of each, as the game ships: the scene colour x the game's
SHOWN = {r: tuple(int(round(c * s)) for c, s in zip(DEFAULTS[r], SCENE_RGB[GROUP_OF[r]]))
         for r in DEFAULTS}

#: how far a pair's ``movt`` may sit after its ``movw`` (the compiler puts a few between)
_PAIR_REACH = 6
#: how far the green/red shape's four instructions may spread
_DUO_REACH = 10

_AL = 0xE0000000                 # condition: always
_MOVW = 0x03000000
_MOVT = 0x03400000
_MOV_FF = 0x03A000FF             # mov rD, #0xff (no S, no rotation)
_MOV_REG = 0x01A00000            # mov rD, rM (no S, no shift)


class Found:
    """Where one build's score colours are made: ``fn`` (the function's VA) and ``sites``,
    each ``{"role" | "roles", "words": {file offset: (kind, register)}}`` - a pair
    (``lo``: the ``movw``, ``hi``: the ``movt``) for one role, or the green/red shape (``a``:
    ``mov rA, #0xff``, ``b``: ``mov rB, rA``, ``ta``/``tb``: their ``movt``s) for ``start``
    and ``coins``."""

    def __init__(self, fn, sites):
        self.fn, self.sites = fn, sites

    def count(self, role):
        return sum(1 for s in self.sites
                   if s.get("role") == role or role in s.get("roles", ()))

    def __repr__(self):
        return "Found(0x%x, %s)" % (self.fn, {r: self.count(r) for r in DEFAULTS})


def _imm16(w):
    return ((w >> 4) & 0xF000) | (w & 0xFFF)


def _with_imm16(w, value):
    return (w & 0xFFF0F000) | ((value & 0xF000) << 4) | (value & 0xFFF)


def _packed(rgb):
    r, g, b = (max(0, min(255, int(c))) for c in tuple(rgb)[:3])
    return (r << 24) | (g << 16) | (b << 8) | 0xFF


def _rgb(v):
    return ((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF)


def _accepted(known):
    """``{role: {packed colour}}``: the game's colour of each role, and those *known*
    (``{role: (r, g, b)}``, or ``{role: [(r, g, b), ...]}`` as :func:`written` gives) says a
    Write put there."""
    out = {r: {_packed(rgb)} for r, rgb in DEFAULTS.items()}
    for r, vals in (known or {}).items():
        if r not in out or vals is None:
            continue
        vals = list(vals)
        for rgb in (vals if vals and isinstance(vals[0], (tuple, list)) else [vals]):
            out[r].add(_packed(rgb))
    return out


def _pairs(w, n, ok):
    """``[(role, i, j)]``: a ``movw rX, #lo`` at word *i* and its ``movt rX, #hi`` at *j*
    making an ``up`` or ``others`` colour of *ok* (another write of rX between ends it)."""
    import numpy as np
    out = []
    want = {}
    for role in ("up", "others"):
        for v in ok[role]:
            want.setdefault(v & 0xFFFF, []).append((v >> 16, role))
    ismovw = ((w >> 28) == 0xE) & ((w & 0x0FF00000) == _MOVW)
    lo16 = ((w >> 4) & 0xF000) | (w & 0xFFF)
    for i in np.nonzero(ismovw & np.isin(lo16, list(want)))[0].tolist():
        x0 = int(w[i])
        rd = (x0 >> 12) & 0xF
        for j in range(i + 1, min(n, i + 1 + _PAIR_REACH)):
            x = int(w[j])
            if (x >> 12) & 0xF != rd:
                continue
            if (x >> 28) == 0xE and (x & 0x0FF00000) == _MOVT:
                for hi, role in want[_imm16(x0)]:
                    if _imm16(x) == hi:
                        out.append((role, i, j))
            break                        # any other write of rX ends it
    return out


def _duos(prog, w, n, ok):
    """``[(i, j, ti, tj)]``: the green/red shape - ``mov rA, #0xff`` or ``movw rA, #lo`` (*i*),
    ``mov rB, rA`` or ``movw rB, #lo`` (*j*), ``movt rA`` (*ti*), ``movt rB`` (*tj*) - making a
    ``start`` and a ``coins`` colour of *ok*, with nothing else between them touching rA or
    rB."""
    import numpy as np
    from . import stock_scan as S
    out = []
    lo_start = {v & 0xFFFF for v in ok["start"]}
    lo_coins = {v & 0xFFFF for v in ok["coins"]}
    al = (w >> 28) == 0xE
    first = (w & 0xFFFF0FFF) == (_AL | _MOV_FF)
    first |= al & ((w & 0x0FF00000) == _MOVW) & np.isin(
        ((w >> 4) & 0xF000) | (w & 0xFFF), sorted(lo_start))
    for i in np.nonzero(first)[0].tolist():
        x0 = int(w[i])
        ra = (x0 >> 12) & 0xF
        lo_a = 0x00FF if (x0 & 0x0FF00000) != _MOVW else _imm16(x0)
        j = ti = tj = rb = lo_b = None
        for k in range(i + 1, min(n, i + 1 + _DUO_REACH)):
            x = int(w[k])
            if (x >> 28) != 0xE:
                continue
            rd = (x >> 12) & 0xF
            if j is None and rd != ra:
                if (x & 0xFFFF0FFF) == (_AL | _MOV_REG | ra) and lo_a == 0x00FF:
                    j, rb, lo_b = k, rd, lo_a
                elif (x & 0x0FF00000) == _MOVW and _imm16(x) in lo_coins and (
                        (x0 & 0x0FF00000) == _MOVW):
                    j, rb, lo_b = k, rd, _imm16(x)
            elif (x & 0x0FF00000) == _MOVT:
                if rd == ra and ti is None:
                    ti = k
                elif rb is not None and rd == rb and tj is None:
                    tj = k
            if j is not None and ti is not None and tj is not None:
                break
        if j is None or ti is None or tj is None or rb == ra:
            continue
        if ((_imm16(int(w[ti])) << 16) | lo_a) not in ok["start"] or (
                (_imm16(int(w[tj])) << 16) | lo_b) not in ok["coins"]:
            continue
        mine = {i, j, ti, tj}
        clean = True
        for k in range(i + 1, max(ti, tj)):
            if k in mine:
                continue
            got = S._regs_at(prog, prog.tlo + 4 * k)
            if got is None or ra in got[0] or ra in got[1] or (
                    k > j and (rb in got[0] or rb in got[1])):
                clean = False
                break
        if clean:
            out.append((i, j, ti, tj))
    return out


def _setter_calls(w, lo, hi):
    """How many ``ldr rX, [rY, #0x40]`` + ``blx rX`` (a virtual call through slot +0x40,
    a Text's colour setter) words *lo*..*hi* hold."""
    n = 0
    for k in range(max(0, lo), min(len(w) - 1, hi)):
        x = int(w[k])
        if (x & 0xFFF00FFF) == 0xE5900040:
            rx = (x >> 12) & 0xF
            for k2 in (k + 1, k + 2):
                if k2 < len(w) and int(w[k2]) == (0xE12FFF30 | rx):
                    n += 1
                    break
    return n


def find(elf, known=None):
    """Where the game program *elf* (bytes) makes its score panel colours, a :class:`Found`,
    or ``None`` when this build doesn't carry the shape (another title, an unfamiliar
    firmware, more than one candidate, or colours an unknown Write put there).  *known*
    (``{role: (r, g, b)}``) are colours this project's Write put in the program."""
    from . import stock_scan as S
    try:
        prog = S.Program(elf)
    except S.ScanError:
        return None
    w = prog.tw
    n = len(w)
    ok = _accepted(known)
    found = {}                   # function VA -> [site]

    def off(i):
        return prog.va2off(prog.tlo + 4 * i)

    def site(i, s):
        found.setdefault(prog.func_start(prog.tlo + 4 * i), []).append(s)

    for i, j, ti, tj in _duos(prog, w, n, ok):
        ra, rb = (int(w[i]) >> 12) & 0xF, (int(w[j]) >> 12) & 0xF
        site(i, {"roles": ("start", "coins"),
                 "words": {off(i): ("a", ra), off(j): ("b", rb),
                           off(ti): ("ta", ra), off(tj): ("tb", rb)}})
    for role, i, j in _pairs(w, n, ok):
        rd = (int(w[i]) >> 12) & 0xF
        site(i, {"role": role, "words": {off(i): ("lo", rd), off(j): ("hi", rd)}})
    hits = []
    for fn, sites in found.items():
        roles = {s.get("role") for s in sites} | {r for s in sites for r in s.get("roles", ())}
        if not set(DEFAULTS) <= roles:
            continue
        claimed = [o for s in sites for o in s["words"]]
        if len(claimed) != len(set(claimed)):
            return None              # one word read two ways: not a guess worth writing
        last = max(prog.off2va(max(s["words"])) for s in sites)
        if _setter_calls(w, (fn - prog.tlo) // 4, (last - prog.tlo) // 4 + 64) < 4:
            continue
        hits.append(Found(fn, sorted(sites, key=lambda s: min(s["words"]))))
    return hits[0] if len(hits) == 1 else None


def overlay(elf, found, colours):
    """``{file offset: 4 bytes}``: the words of *found* (in *elf*) rewritten to make
    *colours* (``{role: (r, g, b)}``; a role not given gets the game's own back).  Only words
    that change are returned, so a program that already makes them yields ``{}``."""
    want = {r: tuple(int(c) for c in tuple(colours.get(r) or DEFAULTS[r])[:3])
            for r in DEFAULTS}
    out = {}

    def word(o):
        return struct.unpack_from("<I", elf, o)[0]

    def put(o, v):
        if v != word(o):
            out[o] = struct.pack("<I", v)

    for s in found.sites:
        words = s["words"]
        if "role" in s:
            v = _packed(want[s["role"]])
            for o, (kind, _rd) in words.items():
                put(o, _with_imm16(word(o), v & 0xFFFF if kind == "lo" else v >> 16))
            continue
        green, red = _packed(want["start"]), _packed(want["coins"])
        stock = want["start"] == DEFAULTS["start"] and want["coins"] == DEFAULTS["coins"]
        ra = next(rd for kind, rd in words.values() if kind == "a")
        for o, (kind, rd) in words.items():
            cond = word(o) & 0xF0000000
            if kind == "a":
                put(o, cond | _MOV_FF | (rd << 12) if stock else
                    cond | _MOVW | (rd << 12) | ((green & 0xF000) << 4) | (green & 0xFFF))
            elif kind == "b":
                put(o, cond | _MOV_REG | (rd << 12) | ra if stock else
                    cond | _MOVW | (rd << 12) | ((red & 0xF000) << 4) | (red & 0xFFF))
            elif kind == "ta":
                put(o, _with_imm16(word(o), green >> 16))
            elif kind == "tb":
                put(o, _with_imm16(word(o), red >> 16))
    return out


def read(elf, found):
    """``{role: (r, g, b)}``: the colours *elf* makes at *found* now, or ``None`` when its
    sites disagree."""
    got = {}
    for s in found.sites:
        vals = {kind: struct.unpack_from("<I", elf, o)[0]
                for o, (kind, _rd) in s["words"].items()}
        if "role" in s:
            pairs = [(s["role"], (_imm16(vals["hi"]) << 16) | _imm16(vals["lo"]))]
        else:
            lo_a = _imm16(vals["a"]) if (vals["a"] & 0x0FF00000) == _MOVW else 0x00FF
            lo_b = _imm16(vals["b"]) if (vals["b"] & 0x0FF00000) == _MOVW else lo_a
            pairs = [("start", (_imm16(vals["ta"]) << 16) | lo_a),
                     ("coins", (_imm16(vals["tb"]) << 16) | lo_b)]
        for role, v in pairs:
            if got.setdefault(role, _rgb(v)) != _rgb(v):
                return None
    return got


# ---------------------------------------------------------------------------------------------
# the panel's lines in the project's scenes
# ---------------------------------------------------------------------------------------------
def _group(n, parents):
    name = n.get("name") or ""
    if name == "score" and any(p.endswith("_ActiveScore_Instance") and "InActive" not in p
                               for p in parents):
        return "up"
    if name == "InActiveScore_Instance" and parents and parents[-1].endswith(
            "_InActiveScore_Instance"):
        return "rest"
    return None


def panel_lines(man):
    """``{node id: "up" | "rest"}``: the score panel's lines in scene manifest *man* (none in
    a scene without the panel)."""
    out, seen = {}, set()

    def run(kids, parents):
        for n in kids:
            for _s, oid in n.get("comps") or ():
                o = man["objects"].get(str(oid)) or {}
                if o.get("kind") == "Text":
                    g = _group(n, parents)
                    if g is not None:
                        out[n["id"]] = g
                elif o.get("kids") is not None and oid not in seen:
                    seen.add(oid)
                    run(o["kids"], parents + [n.get("name") or ""])
    if isinstance(man, dict) and "root" in man:
        run(man["root"]["kids"], [])
    return out


# ---------------------------------------------------------------------------------------------
# the project's colours
# ---------------------------------------------------------------------------------------------
def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in tuple(rgb)[:3])


def _parse(s):
    s = str(s or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def picks(assets_dir, data=None):
    """``{role: (r, g, b)}``: the colours picked by hand in the project."""
    if data is None:
        from ...core import staged_changes
        data = staged_changes.peek(assets_dir) if assets_dir else {}
    m = data.get(KEY) if isinstance(data, dict) else None
    out = {}
    for role, s in (m.items() if isinstance(m, dict) else ()):
        rgb = _parse(s)
        if role in DEFAULTS and rgb is not None:
            out[role] = rgb
    return out


def set_pick(assets_dir, role, rgb):
    """Pick *rgb*, the colour the machine is to show, for *role* (``None``, or what the game
    shows already: no pick)."""
    from ...core import staged_changes
    if role not in DEFAULTS:
        raise ValueError("no score colour %r" % role)
    data = staged_changes.load(assets_dir)
    m = data.get(KEY)
    m = dict(m) if isinstance(m, dict) else {}
    if rgb is None or tuple(rgb)[:3] == SHOWN[role]:
        m.pop(role, None)
    else:
        m[role] = _hex(rgb)
    if m:
        data[KEY] = m
    else:
        data.pop(KEY, None)
    staged_changes.save(assets_dir, data)


def written(assets_dir, data=None):
    """``{role: [(r, g, b)]}``: the colours this project's Writes put in the program, the
    latest last."""
    if data is None:
        from ...core import staged_changes
        data = staged_changes.peek(assets_dir) if assets_dir else {}
    m = data.get(WRITTEN_KEY) if isinstance(data, dict) else None
    out = {}
    for role, vals in (m.items() if isinstance(m, dict) else ()):
        rgbs = [_parse(v) for v in (vals if isinstance(vals, list) else [vals])]
        if role in DEFAULTS:
            out[role] = [v for v in rgbs if v is not None]
    return out


#: how many of a role's earlier colours the project remembers
_HISTORY = 8


def remember_written(assets_dir, colours):
    """Note *colours* (``{role: (r, g, b)}``, every role) as what a Write put in the program."""
    from ...core import staged_changes
    data = staged_changes.load(assets_dir)
    have = written(assets_dir, data)
    m = {}
    for role in DEFAULTS:
        now = tuple(colours[role])
        vals = [v for v in have.get(role, []) if v != now] + [now]
        vals = [v for v in vals if v != DEFAULTS[role]][-_HISTORY:]
        if vals:
            m[role] = [_hex(v) for v in vals]
    if m:
        data[WRITTEN_KEY] = m
    else:
        data.pop(WRITTEN_KEY, None)
    staged_changes.save(assets_dir, data)


def _trees(assets_dir):
    import json
    import os
    try:
        with open(os.path.join(assets_dir, "images", "scene_textures", "scene_tree.json"),
                  encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def profiled(assets_dir, trees=None, data=None):
    """``{role: Profile}``: the individual files profile a line of the panel switched on puts
    on its colours (PAD-438's switch: the line's own profile, else the project's)."""
    from ...core import colour_profile as cp
    if not assets_dir:
        return {}
    if data is None:
        from ...core import staged_changes
        data = staged_changes.peek(assets_dir)
    on = cp.text_lines_on(assets_dir, data)
    if not on:
        return {}
    trees = _trees(assets_dir) if trees is None else trees
    resolve = cp.asset_resolver(assets_dir, data)
    out = {}
    for card, man in sorted((trees or {}).items()):
        for nid, group in sorted(panel_lines(man).items()):
            rel = cp.text_rel(card, nid)
            if rel not in on:
                continue
            prof = resolve("text", rel)
            if prof is None:
                continue
            for role in GROUPS[group]:
                out.setdefault(role, prof)
    return out


def wanted(assets_dir, trees=None, data=None, bake=True):
    """``{role: (r, g, b)}``: every colour the project wants the machine to show the panel in -
    a pick by hand, else what the game shows through the profile of a switched-on line of its
    kind (*bake* False: not), else what the game shows (:data:`SHOWN`)."""
    from . import text_colour
    out = dict(SHOWN)
    if bake:
        for role, prof in profiled(assets_dir, trees, data).items():
            out[role] = tuple(int(round(v * 255.0)) for v in text_colour.corrected(
                prof, [c / 255.0 for c in SHOWN[role]]))
    out.update(picks(assets_dir, data))
    return out


def changed(want):
    """The kinds of line (:data:`GROUPS`) *want* (:func:`wanted`) shows otherwise than the
    game does: their whole colour comes from the program."""
    return {g for g, roles in GROUPS.items() if any(tuple(want[r]) != SHOWN[r] for r in roles)}


def program_colours(want):
    """``{role: (r, g, b)}``: the colours the program is to paint for *want*: the colour to
    show itself for a kind that is changed (its lines white in the scene), the game's own
    for one that is not."""
    kinds = changed(want)
    return {r: tuple(want[r]) if GROUP_OF[r] in kinds else DEFAULTS[r] for r in DEFAULTS}


def pending(assets_dir, data=None):
    """Does a Write have the panel's colours to put in the program (or to put back)?"""
    if not assets_dir:
        return False
    if data is None:
        from ...core import staged_changes
        data = staged_changes.peek(assets_dir)
    if picks(assets_dir, data) or written(assets_dir, data):
        return True
    return bool(profiled(assets_dir, data=data))


def _rgba_of(man, nid):
    for _s, oid in next((n.get("comps") or () for n in _nodes(man) if n.get("id") == nid), ()):
        o = man["objects"].get(str(oid)) or {}
        if o.get("kind") == "Text":
            return [float(v) for v in (o.get("rgba") or (1, 1, 1, 1))[:3]]
    return [1.0, 1.0, 1.0]


def _nodes(man):
    out, seen = [], set()

    def run(kids):
        for n in kids:
            out.append(n)
            for _s, oid in n.get("comps") or ():
                o = man["objects"].get(str(oid)) or {}
                if o.get("kids") is not None and oid not in seen:
                    seen.add(oid)
                    run(o["kids"])
    run(man["root"]["kids"])
    return out


def preview_ops(assets_dir, man, data=None, bake=True):
    """``line_colour`` scene edits that draw the panel's lines of scene *man* (the project's,
    edits applied) as the machine shows them: a kind the project changes in its colour (the
    stand-in score of a box: the player who is up's, or another player's), the others in
    their scene colour times the game's."""
    lines = panel_lines(man)
    if not lines:
        return []
    want = wanted(assets_dir, data=data, bake=bake)
    kinds = changed(want)
    out = []
    for nid, g in sorted(lines.items()):
        role = "up" if g == "up" else "others"
        if g in kinds:
            rgb = [c / 255.0 for c in want[role]]
        else:
            rgb = [s * c / 255.0 for s, c in zip(_rgba_of(man, nid), DEFAULTS[role])]
        out.append({"op": "line_colour", "node": nid, "rgb": [round(v, 4) for v in rgb]})
    return out


def scene_ops(assets_dir, man, data=None):
    """``line_colour`` edits for the Write on scene *man*: the lines of a kind the project
    changes go white, the program's colour is all they show; a kind a Write of this project
    changed before and no longer does gets its scene colour back."""
    lines = panel_lines(man)
    if not lines:
        return []
    want = wanted(assets_dir, data=data)
    kinds = changed(want)
    hist = written(assets_dir, data)
    out = []
    for g, roles in GROUPS.items():
        if g in kinds:
            rgb = [1.0, 1.0, 1.0]
        elif any(hist.get(r) for r in roles):
            rgb = list(SCENE_RGB[g])
        else:
            continue
        out += [{"op": "line_colour", "node": nid, "rgb": rgb}
                for nid, lg in sorted(lines.items()) if lg == g]
    return out


def describe(colours):
    """The colours shown otherwise than the game does, in words, for the Write log."""
    parts = ["%s %s" % (LABELS[r], _hex(colours[r]))
             for r in DEFAULTS if tuple(colours[r]) != SHOWN[r]]
    return ", ".join(parts) if parts else "the game's own colors"


# ---------------------------------------------------------------------------------------------
# the Write
# ---------------------------------------------------------------------------------------------
def compute_writes(reader, fw_node, assets_dir, log, patched_fw=None):
    """``(writes, overlay, n)`` - the panel's colours for the game ELF at *fw_node*: flat
    ``[(disk_offset, bytes)]`` in-place writes and the same words as ``{file_offset: bytes}``
    for whoever refreshes the ELF's ``.sidx`` record last (the validator bypass), as
    :func:`.stock_modes.compute_writes`.  With a staged whole-file firmware (*patched_fw*:
    the blip-free cave's, or a grown program-text ELF) the words go INTO that file and no
    in-place write is returned.  *n* is how many words changed.  Never raises."""
    say = log or (lambda *a, **k: None)
    try:
        if patched_fw is not None:
            with open(patched_fw, "rb") as f:
                elf = bytearray(f.read())
        else:
            if fw_node is None:
                return [], {}, 0
            elf = bytearray(reader.read_file_bytes(fw_node))
        shown = wanted(assets_dir)
        colours = program_colours(shown)
        found = find(bytes(elf), known=written(assets_dir))
        if found is None:
            if changed(shown):
                say("Score colors: this card's game program doesn't make its score panel's "
                    "colors the way Godzilla's does, or a Write from another project changed "
                    "them; they are left as they are. Build from the original card to change "
                    "them.", "warning")
            return [], {}, 0
        ov = overlay(bytes(elf), found, colours)
        remember_written(assets_dir, colours)
        if not ov:
            say("Score colors: the game program already paints the score panel in %s."
                % describe(shown), "info")
            return [], {}, 0
        if patched_fw is not None:
            for off, b in ov.items():
                elf[off:off + len(b)] = b
            with open(patched_fw, "wb") as f:
                f.write(bytes(elf))
            say("Score colors: %s, baked into the rebuilt game program (%d instructions)."
                % (describe(shown), len(ov)), "info")
            return [], {}, len(ov)
        writes = []
        for off, b in sorted(ov.items()):
            payload = b
            for disk, cnt in reader.disk_ranges(fw_node, off, len(b)):
                writes.append((disk, payload[:cnt]))
                payload = payload[cnt:]
        say("Score colors: %s (%d instructions in the game program)."
            % (describe(shown), len(ov)), "info")
        return writes, ov, len(ov)
    except Exception as e:                      # noqa: BLE001 - never fail a Write over this
        say("Score colors: skipped (%s)." % e, "warning")
        return [], {}, 0
