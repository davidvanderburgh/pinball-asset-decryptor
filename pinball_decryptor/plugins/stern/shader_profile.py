"""The color profile applied to EVERYTHING the Spike 2 game draws (PAD-305).

A colour profile (core/colour_profile.py) corrects for the machine's screen.
Applied to the user's replacement files it reaches only what they replaced;
David's ask was the other one: "a global color profile that just affects
display output", every picture, clip, mode screen and line of text, with
no asset touched.

WHERE THAT IS POSSIBLE.  Spike 2's renderer (Radium) is linked into the game
program, and every pixel it draws comes out of one of a handful of GLSL ES
fragment shaders it hands the GPU as plain text at boot: the textured sprite
(every picture and scene texture), YUV -> RGB (the video clips), the font
and gradient-text shaders, the solid fill, an external-image sprite and a
debug overlay.  Measured on Godzilla LE 1.16: nine ``gl_FragColor`` writers
in ``.rodata``.  Each ends by writing ``gl_FragColor``; this module rewrites
that one statement to pass the colour through ``pad_cp()``, the profile's
maths (the same as Pillow's and ffmpeg's, core/colour_profile.py) spliced
in as a GLSL function with the numbers baked in as literals.

PREMULTIPLIED ALPHA.  The engine's textures are premultiplied (its shaders
add ``colorTransformAdd * fragmentColor.a``; scene textures are stored that
way), so ``pad_cp`` divides the alpha out, corrects, and multiplies it back
in: a soft edge keeps its colour.  A shader that is not of that family (the
debug overlay, the external-image sprite) is corrected as straight alpha.
Opaque pixels, the vast majority, come out the same either way.

WHY THE TEXT MOVES.  The corrected shader is longer than its slot, so the
original bytes are left alone and the new text goes into the game program's
extension segment (the same segment, header and relocation census longer
program text uses: :mod:`.progreloc`, ``engine._grow_program_text``), with
each reference retargeted at the copy.  References come in two shapes: an
absolute address (a pointer word, a movw/movt pair: the progreloc census)
and pc + a stored offset (the video player's sprite shader, on every title:
:func:`pcrel_census`).  Only references that point at the START of a shader
are moved; anything else (a look-alike word pointing into the middle of the
text) keeps the original, so the worst a missed or odd reference can do is
leave that one shader uncorrected.  Measured on all 57 Spike 2 card images
on hand: 10 fragment shaders on each (nine GLSL ES 1.00 that write
gl_FragColor, one GLSL ES 3.00 sprite shader that writes ``out vec4 color``
and draws the boot logo), 9 corrected, the debug fill left alone.

A shader that has no ``precision`` statement (the solid red debug fill) is
left alone: a function needs a default float precision in a fragment
shader, and that one is never on a player's screen.

ADJUSTABLE ON THE MACHINE (PAD-307).  The multi-boot menu's Settings > Color
correction lets an operator change the numbers on the machine itself.  It
cannot rebuild anything there, so ``pad_cp`` is always written in ONE fixed
shape, :data:`TUNABLE_TEMPLATE`: every term present (a saturation of 1 and a
lift of 0 included, a few ALU ops for a slot to write into) and every number
``%.6f`` of a value in [0, 10), eight characters.  The boot hook then copies
the game program and overwrites those 13 eight-character slots in place
(codeselect's ``--apply-color``, colour.c, which carries the same template
and must agree with this one byte for byte).
"""

import dataclasses
import re

from . import progreloc

#: The colour output of a GLSL ES 3.00 fragment shader: ``out [prec] vec4 NAME;``
_OUT_RE = re.compile(r"\bout\s+(?:(?:lowp|mediump|highp)\s+)?vec4\s+(\w+)\s*;")
_FUNC = "pad_cp"


def _colour_output(text):
    """The variable *text* writes its final colour to: ``gl_FragColor`` in
    GLSL ES 1.00, the declared ``out vec4`` in GLSL ES 3.00 (the engine's
    ES3 sprite shader writes ``color``), or ``None`` for a shader that is
    not a fragment shader (a vertex shader writes ``gl_Position``)."""
    if "void main" not in text or "gl_Position" in text:
        return None
    if "gl_FragColor" in text:
        return "gl_FragColor"
    if text.lstrip().startswith("#version 300"):
        m = _OUT_RE.search(text)
        if m:
            return m.group(1)
    return None


def fragment_shaders(raw):
    """``[(file_off, text)]`` of every NUL-terminated GLSL fragment shader in
    the ELF *raw*: a ``void main`` string that writes ``gl_FragColor``
    (GLSL ES 1.00) or a declared ``out vec4`` (GLSL ES 3.00; Godzilla LE
    1.16 has one, the ES3 sprite shader that draws the boot logo)."""
    out = []
    seen = set()
    for m in re.finditer(rb"void main", raw):
        s = raw.rfind(b"\x00", 0, m.start()) + 1
        e = raw.find(b"\x00", m.start())
        if e < 0 or s in seen:
            continue
        seen.add(s)
        try:
            text = raw[s:e].decode("ascii")
        except UnicodeDecodeError:
            continue
        if _colour_output(text):
            out.append((s, text))
    return out


#: Every number in ``pad_cp`` is this wide, so the machine can rewrite one in
#: place (PAD-307): ``%.6f`` of a value in [0, 10) is always ``d.dddddd``.
SLOT = 8
_SLOT_MAX = 9.999999

#: The three statements of ``pad_cp`` that carry its numbers, in the one shape
#: the boot menu's apply step (codeselect/colour.c, ``TUNABLE_TEMPLATE``)
#: knows: each ``#`` run is one eight-character slot.  The slots in order are
#: saturation, gain r g b, gamma r g b, then the lift r g b TWICE (the lift
#: statement names its vector twice).  A test holds colour.c to this text.
TUNABLE_TEMPLATE = (
    "c=mix(vec3(dot(c,vec3(0.299,0.587,0.114))),c,########);"
    "c=pow(clamp(c*vec3(########,########,########),0.0,1.0),"
    "vec3(########,########,########));"
    "c=vec3(########,########,########)+(vec3(1.0)-vec3(########,########,########))*c;")


def _f(v):
    return "%.6f" % min(max(float(v), 0.0), _SLOT_MAX)


def tunable_terms(prof):
    """:data:`TUNABLE_TEMPLATE` with *prof*'s numbers in its slots."""
    prof = prof.folded()      # brightness and contrast ride in gain/gamma
    nums = ((prof.saturation,) + tuple(prof.gain) + tuple(prof.gamma)
            + tuple(prof.lift) + tuple(prof.lift))
    out = TUNABLE_TEMPLATE
    for v in nums:
        out = out.replace("#" * SLOT, _f(v), 1)
    return out


@dataclasses.dataclass(frozen=True)
class Shown:
    """A profile, then the machine's screen (PAD-389): what an Emulate run
    with "Show it through the machine's screen" draws through, so the PC
    shows what the machine will.  *prof* may be ``None`` (no whole screen
    overlay).  Only ever built for an Emulate run, never a Write."""
    prof: object
    screen: object

    def label(self):
        return "%s, through the Machine screen %s" % (
            self.prof.label() if self.prof is not None else "No change",
            self.screen.label())


def correction_glsl(prof, premultiplied, qualified=False):
    """The ``pad_cp`` function for *prof* (a core.colour_profile.Profile, or
    a :class:`Shown`: the profile's terms, then the screen's).

    *qualified* gives every float type an explicit ``highp``: a GLSL ES 3.00
    fragment shader has no default float precision, so an unqualified
    ``vec3`` in it does not compile (ES 1.00 shaders here all declare one).

    EVERY TERM IS WRITTEN, a saturation of 1 and a lift of 0 included, in
    :data:`TUNABLE_TEMPLATE`'s shape: that is what lets the multi-boot menu
    change the numbers on the machine (PAD-307)."""
    q = "highp " if qualified else ""
    screen = None
    if isinstance(prof, Shown):
        from ...core.colour_profile import Profile
        screen = prof.screen
        prof = prof.prof if prof.prof is not None else Profile()
    body = []
    if premultiplied:
        body.append("%sfloat a=f.a;%svec3 c=clamp(f.rgb/max(a,0.0001),0.0,1.0);"
                    % (q, q))
    else:
        body.append("%sfloat a=f.a;%svec3 c=clamp(f.rgb,0.0,1.0);" % (q, q))
    if screen is None:
        body.append(tunable_terms(prof))
        extras = extras_glsl(prof, qualified)
    else:
        # An Emulate run's profile, then the machine's screen (PAD-389): no
        # menu rewrites this program, so only the terms that change something
        # are written, and both profiles' ranges and curves share one
        # function, the screen's sliders between them: the game program has
        # 32 KB (28 KB on some titles) for all nine shaders.
        body.append(plain_terms(prof))
        extras = extras_glsl(prof, qualified, then=screen)
    if extras:
        body.append("c=%s(c);" % _EXTRAS)
    body.append("return vec4(c*a,a);" if premultiplied
                else "return vec4(c,a);")
    return extras + "%svec4 %s(%svec4 f){%s}" % (q, _FUNC, q, "".join(body))


#: The colour ranges' and curves' function (PAD-343), defined before
#: ``pad_cp`` and called after its fixed slots.  Its own function because
#: ``pad_cp``'s body is read back as one brace-free run (:data:`_FUNC_RE`).
_EXTRAS = "pad_cx"
_RANGE = "pad_cr"

#: How far (in levels of 0..255) the straight stretches the curves are drawn
#: with may stray from the 256-entry tables.  The knots are placed where the
#: curves bend, as few as that allows (PAD-389: the game program has 32 KB
#: for its nine corrected shaders, and evenly spaced knots every 8th level
#: filled it with one profile's curves).
_CURVE_TOL = 0.5


def _n(v):
    """*v* as a short GLSL float literal: at most four decimals, at least
    one digit each side of the point (``0.75``, ``8.0``, ``-1.125``)."""
    t = ("%.4f" % float(v)).rstrip("0")
    if t.endswith("."):
        t += "0"
    return "0.0" if t in ("-0.0", "0.0") else t


def plain_terms(prof):
    """*prof*'s saturation, gain/gamma and lift as GLSL statements on ``c``,
    the maths of :data:`TUNABLE_TEMPLATE` without the terms that change
    nothing and without fixed-width slots: for a profile no machine menu
    rewrites (the Machine screen of an Emulate run, PAD-389)."""
    prof = prof.folded()
    out = []
    if prof.saturation != 1.0:
        out.append("c=mix(vec3(dot(c,vec3(0.299,0.587,0.114))),c,%s);"
                   % _n(prof.saturation))
    if prof.gain != (1.0, 1.0, 1.0) or prof.gamma != (1.0, 1.0, 1.0):
        out.append("c=pow(clamp(c*vec3(%s),0.0,1.0),vec3(%s));" % (
            ",".join(_n(v) for v in prof.gain),
            ",".join(_n(v) for v in prof.gamma)))
    elif out:
        out.append("c=clamp(c,0.0,1.0);")
    if prof.lift != (0.0, 0.0, 0.0):
        lift = ",".join(_n(v) for v in prof.lift)
        out.append("c=vec3(%s)+(vec3(1.0)-vec3(%s))*c;" % (lift, lift))
    return "".join(out)


def _curve_floats(prof):
    """``[r, g, b]`` 256 unrounded levels of *prof*'s master curve then each
    channel's own (:meth:`Profile.curve_tables` before its rounding, which
    would otherwise cost a knot at every half-level step), or ``None``."""
    from ...core.colour_profile import CURVE_IDENTITY, curve_values
    cv = {ch: pts for ch, pts in prof.curves if pts != CURVE_IDENTITY}
    if not cv:
        return None

    def through(pts, xs):
        if len(pts) < 2:
            return list(xs)
        return [min(max(y, 0.0), 255.0) for y in curve_values(pts, xs)]
    master = through(cv["rgb"], range(256)) if "rgb" in cv         else [float(v) for v in range(256)]
    return [through(cv[ch], master) if ch in cv else master
            for ch in ("r", "g", "b")]


def _curve_knots(tables, tol=_CURVE_TOL):
    """The levels the curves are drawn straight between: 0, 255, and as few
    in between as keep every channel of *tables* within *tol*."""
    knots, x0 = [0], 0
    while x0 < 255:
        x1 = x0 + 1
        while x1 < 255:
            nxt = x1 + 1
            if any(abs(t[x0] + (t[nxt] - t[x0]) * (x - x0) / (nxt - x0) - t[x])
                   > tol for t in tables for x in range(x0 + 1, nxt)):
                break
            x1 = nxt
        knots.append(x1)
        x0 = x1
    return knots


def _range_glsl(q):
    """``pad_cr``: one colour range on ``c`` (0..1), the maths of
    core/colour_profile.py ``apply_ranges`` with the 0..255 values as
    0..1."""
    f, v = q + "float", q + "vec3"
    # short names and one declaration per type: it is in every shader, and
    # the game program has 32 KB for all nine (PAD-389)
    return (
        "%(v)s %(n)s(%(v)s c,%(f)s u,%(f)s W,%(f)s S,%(f)s T,%(f)s A,"
        "%(f)s B,%(f)s P){"
        "%(f)s m=max(c.r,max(c.g,c.b)),n=m-min(c.r,min(c.g,c.b));"
        "if(n<=0.0)return c;"
        "%(f)s h=60.0*(m==c.r?mod((c.g-c.b)/n,6.0):m==c.g?(c.b-c.r)/n+2.0"
        ":(c.r-c.g)/n+4.0),"
        "d=abs(mod(h-u+180.0,360.0)-180.0),"
        "w=W>=360.0?1.0:S>0.0?smoothstep(0.0,1.0,1.0-(d-W*0.5)/S)"
        ":d<=W*0.5?1.0:0.0;"
        "if(P>0.0)w*=smoothstep(0.0,1.0,n/P);"
        "if(w<=0.0)return c;"
        "h=mod(h+T*w,360.0);"
        "%(f)s s=clamp(n/m*(1.0+(A-1.0)*w),0.0,1.0),"
        "v=clamp(m*(1.0+(B-1.0)*w),0.0,1.0);"
        "%(v)s k=mod(vec3(5.0,3.0,1.0)+h/60.0,6.0);"
        "return v-v*s*clamp(min(k,4.0-k),0.0,1.0);}"
        % {"f": f, "v": v, "n": _RANGE})


def _curve_glsl(tables, decl="vec3 "):
    """Statements taking ``c`` through the ``[r, g, b]`` 256-entry curve
    *tables*: in levels (``d``, 0..255, declared with *decl*), the straight
    stretches between :func:`_curve_knots` as a sum of hinges, each the
    change of slope at its knot times ``max(d - knot, 0)``, then back to
    0..1.  Nothing is drawn past 255, so no hinge needs an upper end."""
    knots = _curve_knots(tables)
    out = ["%sd=c*255.0;c=(vec3(%s)" % (
        decl, ",".join(_n(t[0]) for t in tables))]
    was = (0.0, 0.0, 0.0)
    for x0, x1 in zip(knots, knots[1:]):
        slope = tuple((t[x1] - t[x0]) / float(x1 - x0) for t in tables)
        step = tuple(a - b for a, b in zip(slope, was))
        if any(abs(v) >= 0.00005 for v in step):
            out.append("+vec3(%s)*%s" % (
                ",".join(_n(v) for v in step),
                "max(d-%s,0.0)" % _n(x0) if x0 else "d"))
            was = slope
    return "".join(out) + ")/255.0;"


def _extras_body(prof, q, declared):
    """*prof*'s colour ranges and curve as statements on ``c``; *declared*
    True when ``d`` already is (a second profile in the same function)."""
    from ...core.colour_profile import range_neutral
    body = []
    for hue, width, soft, shift, sat, bright, protect in (
            r for r in prof.ranges if not range_neutral(r)):
        body.append("c=%s(c,%s);" % (_RANGE, ",".join(
            _n(v) for v in (hue, width, soft, shift, sat, bright, protect))))
    tabs = _curve_floats(prof)
    if tabs is not None:
        body.append(_curve_glsl(tabs, "" if declared else q + "vec3 "))
    return body


def extras_glsl(prof, qualified=False, then=None):
    """The GLSL of *prof*'s colour ranges and curves (PAD-343), ``pad_cx``
    (and ``pad_cr`` for the ranges), or ``""`` when it has none that change
    anything, so a profile without them builds exactly the shader it did.
    *then*: a second profile drawn after it in the same function, all of it
    (an Emulate run's Machine screen, PAD-389)."""
    if not prof.has_extras() and then is None:
        return ""
    q = "highp " if qualified else ""
    body = _extras_body(prof, q, False)
    if then is not None:
        terms = plain_terms(then)
        if terms:
            body.append(terms)
        body += _extras_body(then, q, any("d=c*255.0" in b for b in body))
    if not body:
        return ""
    head = _range_glsl(q) if any(_RANGE + "(" in b for b in body) else ""
    body.append("return clamp(c,0.0,1.0);")
    return head + "%svec3 %s(%svec3 c){%s}" % (q, _EXTRAS, q, "".join(body))


def _premultiplied(text):
    """Is *text* one of the engine's premultiplied-alpha shaders?"""
    return ("colorTransformAdd" in text) or ("colorTransformFont" in text) \
        or ("textureYSampler" in text)


def patch_source(text, prof):
    """*text* with the profile applied to its final colour, or ``None`` when
    it is not a shader this patches (an ES 1.00 shader with no ``precision``
    statement - the solid red debug fill -, no colour write, already
    patched)."""
    if _FUNC + "(" in text:
        return None
    var = _colour_output(text)
    if var is None:
        return None
    es3 = var != "gl_FragColor"
    if not es3 and "precision" not in text:
        return None
    main = text.find("void main")
    write_re = re.compile(r"\b%s\s*=\s*([^;]+);" % re.escape(var))
    writes = [w for w in write_re.finditer(text) if w.start() > main]
    if not writes:
        return None
    w = writes[-1]
    expr = w.group(1).strip()
    body = (text[:w.start()] + "%s = %s(%s);" % (var, _FUNC, expr)
            + text[w.end():])
    func = correction_glsl(prof, _premultiplied(text), qualified=es3)
    sep = "\n" if "\n" in text[:main] else ""
    return body[:main] + func + sep + body[main:]


#: How far back from an ``add Rd, pc, Rm`` the ``ldr Rm, =offset`` may sit.
_PCREL_BACK = 16


def pcrel_census(raw, spans):
    """Position-independent references to *spans* (``[(file_off, text)]``):
    an ``ldr Rm, [pc, #imm]`` of a literal OFFSET, then ``add Rd, pc, Rm``
    a few instructions on, so the address is ``pc + offset`` and no word in
    the file holds it.  :func:`progreloc.reference_census` cannot see these;
    the video player's sprite shader is reached only this way on every Spike
    2 title on hand (one A32 site, ``SpiVideoPlayer``), which is why the
    first version left video uncorrected.

    Returns ``{span_off: [{"kind": "pcrel", "delta", "lit", "base"}]}`` where
    the literal at file offset *lit* holds ``target - base``."""
    import numpy as np
    segs = progreloc.load_segments(raw)
    off2va, va2off = progreloc.seg_maps(segs)
    targets = {}
    for off, text in spans:
        va = off2va(off)
        if va is not None:
            for k in range(len(text)):
                targets[va + k] = (off, k)
    out = {}
    if not targets:
        return out
    n = len(raw)
    for seg_va, seg_off, fs, _ms, fl in segs:
        if not fl & 1:
            continue
        lo = seg_off - seg_off % 4
        words = np.frombuffer(raw, dtype="<u4", count=(min(n, seg_off + fs) - lo) // 4,
                              offset=lo)
        # A32: add Rd, pc, Rm  =  cond 0000 100S 1111 dddd 0000 0000 mmmm
        for idx in np.nonzero((words & 0x0FEF0FF0) == 0x008F0000)[0]:
            i = lo + int(idx) * 4
            ins = int(words[idx])
            rm = ins & 0xF
            for back in range(1, _PCREL_BACK + 1):
                j = i - 4 * back
                if j < lo:
                    break
                w = int(words[idx - back])
                if (w & 0x0F7F0000) == 0x051F0000 and ((w >> 12) & 0xF) == rm:
                    imm = w & 0xFFF
                    lit = j + 8 + (imm if (w >> 23) & 1 else -imm)
                    if 0 <= lit <= n - 4:
                        base = off2va(i) + 8
                        lval = int.from_bytes(raw[lit:lit + 4], "little")
                        hit = targets.get((base + lval) & 0xFFFFFFFF)
                        if hit is not None:
                            out.setdefault(hit[0], []).append(
                                {"kind": "pcrel", "delta": hit[1],
                                 "lit": lit, "base": base})
                    break
                if ((w >> 12) & 0xF) == rm and (w & 0x0C000000) == 0:
                    break           # Rm rewritten by a data op: not this site
        # T32: add Rdn, pc (16-bit 0100 0100 D111 1ddd), ldr Rt,[pc,#imm8*4]
        hlo = lo
        halves = np.frombuffer(raw, dtype="<u2", count=(min(n, seg_off + fs) - hlo) // 2,
                               offset=hlo)
        for idx in np.nonzero((halves & 0xFF78) == 0x4478)[0]:
            i = hlo + int(idx) * 2
            h = int(halves[idx])
            rd = (h & 7) | ((h >> 4) & 8)
            for back in range(1, 2 * _PCREL_BACK + 1):
                if idx - back < 0:
                    break
                h2 = int(halves[idx - back])
                if (h2 & 0xF800) == 0x4800 and ((h2 >> 8) & 7) == rd:
                    j = i - 2 * back
                    lit_va = ((off2va(j) + 4) & ~3) + (h2 & 0xFF) * 4
                    lit = va2off(lit_va)
                    if lit is not None and 0 <= lit <= n - 4:
                        base = off2va(i) + 4
                        lval = int.from_bytes(raw[lit:lit + 4], "little")
                        hit = targets.get((base + lval) & 0xFFFFFFFF)
                        if hit is not None:
                            out.setdefault(hit[0], []).append(
                                {"kind": "pcrel", "delta": hit[1],
                                 "lit": lit, "base": base})
                    break
    return out


def _retarget(raw, ref, va):
    if ref["kind"] == "pcrel":
        return [(ref["lit"], ((va - ref["base"]) & 0xFFFFFFFF).to_bytes(
            4, "little"))]
    return progreloc.retarget_writes(raw, ref, va)


def plan(raw, prof, base_va):
    """Where every patched shader goes and what to rewrite.

    *base_va* is the virtual address the blob will start at (the extension
    segment's base + its first free offset).  Returns ``(file_writes, blob,
    report)``: *file_writes* the ``[(file_off, bytes)]`` reference rewrites,
    *blob* the NUL-terminated new shader texts back to back, *report* a list
    of ``(file_off, n_refs_moved, n_refs_left, what)`` per shader, for the
    log.  A shader with no reference at its start is not placed at all.
    References are the absolute ones :func:`progreloc.reference_census`
    finds and the position-independent ones :func:`pcrel_census` finds."""
    shaders = fragment_shaders(raw)
    census = progreloc.reference_census(raw, shaders) if shaders else {}
    pcrel = pcrel_census(raw, shaders) if shaders else {}
    writes, blob, report = [], bytearray(), []
    for off, text in shaders:
        new = patch_source(text, prof)
        if new is None:
            report.append((off, 0, 0, "left alone"))
            continue
        refs = (census.get(off) or []) + (pcrel.get(off) or [])
        head = [r for r in refs if r["delta"] == 0]
        if not head:
            report.append((off, 0, len(refs), "no reference found"))
            continue
        va = base_va + len(blob)
        for r in head:
            writes += _retarget(raw, r, va)
        blob += new.encode("ascii") + b"\x00"
        while len(blob) % 4:
            blob += b"\x00"
        report.append((off, len(head), len(refs) - len(head), "corrected"))
    return writes, bytes(blob), report


_NUM = r"(-?\d+(?:\.\d+)?)"
_V3 = r"vec3\(%s,%s,%s\)" % (_NUM, _NUM, _NUM)
_FUNC_RE = re.compile(rb"vec4 " + _FUNC.encode() + rb"\((?:highp )?vec4 f\)\{([^}]*)\}")
_SAT_RE = re.compile(r"c=mix\(vec3\(dot\(c,vec3\(0\.299,0\.587,0\.114\)\)\),c,%s\);" % _NUM)
_POW_RE = re.compile(r"c=pow\(clamp\(c\*%s,0\.0,1\.0\),%s\);" % (_V3, _V3))
_LIFT_RE = re.compile(r"c=%s\+\(vec3\(1\.0\)-" % _V3)


def profile_in(raw):
    """The color profile the game program *raw* applies to everything it
    draws, read back out of the ``pad_cp`` its patched shaders carry - or
    ``None`` for a game with none (stock, or built with No change).

    What a built card IS is the only record of the profile it was built
    with: the project that made it may be gone, or set to something else
    since.  The Multi-boot menu reads it to show a black-and-white edition's
    logo and attract clip the way that edition's game shows them.  The name
    is a starting point's when the numbers are one's, else empty."""
    from ...core import colour_profile
    m = _FUNC_RE.search(raw)
    if not m:
        return None
    body = m.group(1).decode("ascii", "replace")
    p = _POW_RE.search(body)
    if not p:
        return None
    vals = tuple(float(x) for x in p.groups())
    s = _SAT_RE.search(body)
    lift = _LIFT_RE.search(body)
    prof = colour_profile.Profile(
        gain=vals[:3], gamma=vals[3:],
        lift=tuple(float(x) for x in lift.groups()) if lift else (0.0, 0.0, 0.0),
        saturation=float(s.group(1)) if s else 1.0)
    key = _numbers(prof)
    for _k, preset in colour_profile.PRESETS:
        if _numbers(preset) == key:
            return dataclasses.replace(prof, name=preset.name)
    return prof


_TUNABLE_RE = re.compile(
    re.escape(TUNABLE_TEMPLATE).replace(re.escape("#" * SLOT), r"(\d\.\d{6})").encode())


def tunable_in(raw):
    """``(Profile, functions)`` when every ``pad_cp`` the game program *raw*
    carries is in :data:`TUNABLE_TEMPLATE`'s shape with the SAME numbers -
    the multi-boot menu can then change them on the machine (PAD-307) - else
    ``None``: a stock game, one built with No change, or one built before the
    shape was fixed (v1.60, whose ``pad_cp`` leaves out a term it did not
    need, so there is no slot to write it into)."""
    funcs = _FUNC_RE.findall(raw)
    if not funcs:
        return None
    seen = set()
    for body in funcs:
        m = _TUNABLE_RE.search(body)
        if not m:
            return None
        seen.add(m.groups())
    if len(seen) != 1:
        return None
    nums = [float(x) for x in seen.pop()]
    if nums[7:10] != nums[10:13]:
        return None
    prof = profile_in(raw)
    return prof, len(funcs)


def _numbers(prof):
    """A profile's numbers as the shader text spells them (``%.6f``)."""
    prof = prof.folded()
    return tuple(_f(x) for x in prof.gamma + prof.gain + prof.lift
                 + (prof.saturation,))


def describe(report):
    """One log sentence for :func:`plan`'s report."""
    done = [r for r in report if r[3] == "corrected"]
    left = [r for r in report if r[3] != "corrected"]
    return ("%d of the game's %d drawing shaders carry the color profile"
            % (len(done), len(report))
            + ("; %d left as they are (%s)" % (len(left), ", ".join(
                "0x%x %s" % (r[0], r[3]) for r in left)) if left else ""))
