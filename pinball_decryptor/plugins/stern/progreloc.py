"""Reference census and relocation helpers for LONGER program text.

:mod:`.progtext` patches a game-program string in place, so a replacement
has to fit the original's byte slot.  The way past that limit (proven under
qemu on Godzilla Pro 1.15, ``plans/spike2_longer_program_text.md``) is to
leave the original bytes alone, copy the new NUL-terminated text into a NEW
read-only ``PT_LOAD`` segment the caller appends to the ELF (page-aligned
payload at EOF, mapped into the unused text/data hole through the repurposed
``PT_GNU_STACK`` header, exactly as ``engine._append_cave_segment`` does for
the audio cave), and retarget every reference to the string at the copy.

Retargeting is only safe when every reference can be seen, so this module is
first a CENSUS.  For each display span (:func:`progtext._display_spans`) it
finds:

* ``group`` — words inside a run of >= 5 identical dwords (the five-language
  ``char*`` name-group shape :mod:`.progtext` already patches);
* ``lone`` — any other 4-byte-aligned word inside a ``PT_LOAD`` file range
  equal to the string's address or an address INSIDE it (adjustment
  descriptors, high-score default records, per-monster structs, literal
  pools in code all reference strings this way).  A random data word equal
  to one specific ``.rodata`` address is a ~1e-4 event over a whole 8 MB
  binary; accepted, with two evidence-based exceptions below;
* ``movw_a32`` / ``movw_t32`` — ARM ``movw``/``movt`` immediate pairs (same
  ``Rd``, the ``movt`` within a few instructions of the ``movw``) in the
  executable segments whose combined 32-bit immediate is such an address.
  Both immediates are rewritten on retarget.

Three shapes are deliberately NOT references:

* misaligned dwords — A32 code and C data are word-aligned; the thousands
  of misaligned hits on a real ELF are byte soup, and the one class that
  looked real (inside the text segment) cannot be a pointer at all;
* "counter" words — a lone word whose neighbour at some fixed stride holds
  the value +-1 is a packed sequence, not a pointer.  The proving case is
  Godzilla LE 1.16's ``BATTLE VS SPACE G SHOT TIMER``: a 24-byte-stride
  table of ``0x5a0817, 0x5b0818, ... 0x60081d ...`` lands one member 9
  bytes into the caption.  Likewise a lone word pointing INTO a string at a
  whitespace character is dismissed (a linker tail-merge never starts on a
  space; a coincidence there would force every edit of the caption to keep
  a tail nobody displays);
* the LAST BYTES OF A C STRING — the ELF's own symbol tables are full of
  C++ mangled names ending ``...EUlPvPKvE_\0`` or ``...S0_PS_\0``, and the
  three printable characters in front of that terminator read as a
  little-endian ``0x005f____``, which is squarely inside these games'
  ``.rodata``.  Every span address on a Spike 2 ELF starts with a zero
  byte, so the shape is systematic rather than rare: 32 hits on stock
  Godzilla Pro 1.16, 43 on LE 1.16, and EVERY one of them lands INSIDE a
  display string, i.e. becomes a phantom "the machine also shows this tail"
  rule.  PAD-130 is the proving case: ``"PS_\0"`` at file offset ``0x857c``
  of Godzilla Pro 1.16 reads as ``MEGALON AWARD`` + 4, so renaming that
  award to ``KAIJU AWARD`` was skipped for not ending in ``LON AWARD``
  while every other award line on the same card renamed cleanly.
  Retargeting one would have been worse still: the write lands in the
  middle of a mangled symbol name.  See :func:`is_string_tail_word`.

A reference is ``{"kind", "delta", "offs", "va"}``: ``delta`` is how far
into the string it points (0 = the whole string; > 0 = a TAIL such as
``"GODZILLA VS MEGALON" + 12`` = ``MEGALON``), ``offs`` the file offsets of
the words / instructions to rewrite (a group lists its whole run), ``va``
the address they encode.

**Extension segment header.**  So a relocated game can be extended again
(a re-Extract of a relocated card, or a second Write), the caller stores
``b"PADTXT01" + u32 used_bytes`` (little-endian) at the very start of the
segment's payload; :func:`extension_segment` finds it, and
:func:`progtext.plan_writes` honours ``reloc["used"]`` as the first free
offset — the header's 12 bytes are counted in ``used``.  Nothing in this
module allocates or appends the segment: it sizes the blob, and the caller
(the engine) owns the ELF surgery.
"""

import struct

PAGE = 0x1000
PT_LOAD = 1
PT_GNU_STACK = 0x6474e551
PF_X = 1

EXT_MAGIC = b"PADTXT01"
EXT_HEADER_LEN = 12                      # magic + u32 used

KIND_GROUP = "group"
KIND_LONE = "lone"
KIND_A32 = "movw_a32"
KIND_T32 = "movw_t32"

# How far a movt may trail its movw and still form one address.
A32_PAIR_WINDOW = 6                      # instructions
T32_PAIR_WINDOW = 12                     # halfwords
# Strides (bytes) probed by the packed-counter test.
COUNTER_STRIDES = range(4, 68, 4)
# Printable bytes that must run up to a candidate word before it is judged
# the tail of a C string rather than a pointer, and how far back that run is
# followed before it counts as text whatever precedes it.  Eight printable
# bytes ending at a NUL is already a ~1e-6 accident in code or in a pointer
# table; the mangled names that produce this shape run to hundreds.
STRING_TAIL_LEAD = 8
STRING_TAIL_SCAN = 512


# ---------------------------------------------------------------------------
# ELF geometry
# ---------------------------------------------------------------------------

def iter_phdrs(raw):
    """``[(hdr_off, p_type, p_offset, p_vaddr, p_filesz, p_memsz, p_flags,
    p_align)]`` for a 32-bit little-endian ELF; ``[]`` for anything else."""
    if len(raw) < 0x34 or raw[:4] != b"\x7fELF" or raw[4] != 1 or raw[5] != 1:
        return []
    e_phoff = struct.unpack_from("<I", raw, 0x1c)[0]
    e_phentsize = struct.unpack_from("<H", raw, 0x2a)[0]
    e_phnum = struct.unpack_from("<H", raw, 0x2c)[0]
    out = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        if o + 32 > len(raw):
            break
        t, off, va, _pa, fs, ms, fl, al = struct.unpack_from("<8I", raw, o)
        out.append((o, t, off, va, fs, ms, fl, al))
    return out


def load_segments(raw):
    """``[(vaddr, file_off, filesz, memsz, flags)]`` of the PT_LOADs."""
    return [(va, off, fs, ms, fl)
            for (_o, t, off, va, fs, ms, fl, _al) in iter_phdrs(raw)
            if t == PT_LOAD]


def seg_maps(segs):
    """``(off2va, va2off)`` over *segs* from :func:`load_segments`."""
    def off2va(off):
        for va, o, fs, _ms, _fl in segs:
            if o <= off < o + fs:
                return va + (off - o)
        return None

    def va2off(va):
        for v, o, fs, _ms, _fl in segs:
            if v <= va < v + fs:
                return o + (va - v)
        return None
    return off2va, va2off


def text_data_hole(raw):
    """``(lo_va, hi_va)`` of the page-aligned gap between the two lowest
    PT_LOADs (text's last page to data's first) — the address space a text
    extension segment goes in — or ``None`` when there is no gap."""
    loads = sorted((va, ms) for (va, _o, _fs, ms, _fl) in load_segments(raw))
    if len(loads) < 2:
        return None
    lo = (loads[0][0] + loads[0][1] + PAGE - 1) & ~(PAGE - 1)
    hi = loads[1][0] & ~(PAGE - 1)
    return (lo, hi) if hi > lo else None


def extension_segment(raw):
    """The text extension segment a previous Write left in *raw*, or
    ``None``: ``{"hdr_off", "seg_off", "base_va", "capacity", "used"}``
    where *capacity* is the segment's mapped size and *used* the first free
    offset from its header (never less than the header itself)."""
    for (o, t, off, va, fs, _ms, _fl, _al) in iter_phdrs(raw):
        if t != PT_LOAD or fs < EXT_HEADER_LEN:
            continue
        if raw[off:off + 8] != EXT_MAGIC:
            continue
        used = struct.unpack_from("<I", raw, off + 8)[0]
        used = min(max(used, EXT_HEADER_LEN), fs)
        return {"hdr_off": o, "seg_off": off, "base_va": va,
                "capacity": fs, "used": used}
    return None


def extension_header(used):
    """The 12 header bytes for a segment whose first free offset is *used*."""
    return EXT_MAGIC + struct.pack("<I", used)


# ---------------------------------------------------------------------------
# movw / movt codecs (ARM ARM A8.8.102 / A8.8.106; T32 encodings T3 / T1)
# ---------------------------------------------------------------------------

def decode_a32(word):
    """``("movw" | "movt", rd, imm16)`` for an A32 MOVW/MOVT, else ``None``.
    The ``cond == 0xF`` space is not a MOV (it is unconditional SIMD/other)."""
    if (word >> 28) == 0xF:
        return None
    top = word & 0x0FF00000
    if top == 0x03000000:
        kind = "movw"
    elif top == 0x03400000:
        kind = "movt"
    else:
        return None
    rd = (word >> 12) & 0xF
    imm = ((word >> 4) & 0xF000) | (word & 0xFFF)
    return kind, rd, imm


def encode_a32(word, imm16):
    """*word* (an A32 MOVW/MOVT) with its immediate replaced by *imm16*;
    condition, opcode and Rd are kept."""
    imm16 &= 0xFFFF
    return (word & 0xFFF0F000) | ((imm16 & 0xF000) << 4) | (imm16 & 0xFFF)


def decode_t32(hw1, hw2):
    """``("movw" | "movt", rd, imm16)`` for a T32 MOVW (T3) / MOVT (T1)
    halfword pair (*hw1* at the lower address), else ``None``."""
    if hw2 & 0x8000:
        return None
    if (hw1 & 0xFBF0) == 0xF240:
        kind = "movw"
    elif (hw1 & 0xFBF0) == 0xF2C0:
        kind = "movt"
    else:
        return None
    imm = ((hw1 & 0xF) << 12) | (((hw1 >> 10) & 1) << 11) \
        | (((hw2 >> 12) & 7) << 8) | (hw2 & 0xFF)
    rd = (hw2 >> 8) & 0xF
    return kind, rd, imm


def encode_t32(hw1, hw2, imm16):
    """``(hw1, hw2)`` of the T32 MOVW/MOVT *hw1*/*hw2* with the immediate
    replaced by *imm16*."""
    imm16 &= 0xFFFF
    hw1 = (hw1 & 0xFBF0) | (((imm16 >> 11) & 1) << 10) | ((imm16 >> 12) & 0xF)
    hw2 = (hw2 & 0x8F00) | (((imm16 >> 8) & 7) << 12) | (imm16 & 0xFF)
    return hw1, hw2


def a32_pairs(raw, seg):
    """``[(off_movw, off_movt, rd, imm32)]`` over one executable segment
    ``(vaddr, off, filesz, memsz, flags)``: each MOVW paired with the first
    later MOVT to the same Rd within :data:`A32_PAIR_WINDOW` instructions."""
    import numpy as np
    off0, fs = seg[1], seg[2]
    n = fs // 4
    if n < 2:
        return []
    a = np.frombuffer(raw[off0: off0 + n * 4], dtype="<u4")
    cond_ok = (a >> 28) != 0xF
    top = a & 0x0FF00000
    is_w = (top == 0x03000000) & cond_ok
    is_t = (top == 0x03400000) & cond_ok
    rd = (a >> 12) & 0xF
    imm = ((a >> 4) & 0xF000) | (a & 0xFFF)
    out = []
    for i in np.flatnonzero(is_w):
        i = int(i)
        for j in range(i + 1, min(i + 1 + A32_PAIR_WINDOW, n)):
            if is_t[j] and rd[j] == rd[i]:
                out.append((off0 + i * 4, off0 + j * 4, int(rd[i]),
                            int(imm[i]) | (int(imm[j]) << 16)))
                break
    return out


def t32_pairs(raw, seg):
    """``[(off_movw, off_movt, rd, imm32)]`` of Thumb-2 MOVW/MOVT pairs over
    one executable segment (halfword-granular scan; a MOVT to the same Rd
    within :data:`T32_PAIR_WINDOW` halfwords after the MOVW's second half)."""
    import numpy as np
    off0, fs = seg[1], seg[2]
    n = fs // 2
    if n < 4:
        return []
    h = np.frombuffer(raw[off0: off0 + n * 2], dtype="<u2").astype(np.uint32)
    hw1 = h[:-1]
    hw2 = h[1:]
    lo_ok = (hw2 & 0x8000) == 0
    is_w = ((hw1 & 0xFBF0) == 0xF240) & lo_ok
    is_t = ((hw1 & 0xFBF0) == 0xF2C0) & lo_ok
    imm = ((hw1 & 0xF) << 12) | (((hw1 >> 10) & 1) << 11) \
        | (((hw2 >> 12) & 7) << 8) | (hw2 & 0xFF)
    rd = (hw2 >> 8) & 0xF
    m = len(hw1)
    out = []
    for i in np.flatnonzero(is_w):
        i = int(i)
        for j in range(i + 2, min(i + 2 + T32_PAIR_WINDOW, m)):
            if is_t[j] and rd[j] == rd[i]:
                out.append((off0 + i * 2, off0 + j * 2, int(rd[i]),
                            int(imm[i]) | (int(imm[j]) << 16)))
                break
    return out


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------

def group_runs(raw):
    """``[(word_off, n_words, value)]`` for every run of >= 5 identical
    non-zero dwords (word-aligned), file order."""
    import numpy as np
    n = len(raw) // 4
    if n < 5:
        return []
    a = np.frombuffer(raw[: n * 4], dtype="<u4")
    same = np.concatenate(([False], a[1:] == a[:-1]))
    run_id = np.cumsum(~same)
    counts = np.bincount(run_id)
    starts = np.flatnonzero(~same)
    out = []
    for s in starts:
        c = int(counts[run_id[s]])
        if c >= 5 and a[s] != 0:
            out.append((int(s) * 4, c, int(a[s])))
    return out


def _u32(raw, off):
    return struct.unpack_from("<I", raw, off)[0]


def is_counter_word(raw, off, val):
    """True when the word at *off* (value *val*) sits in a packed +-1
    sequence at some fixed stride — a counter table, not a pointer."""
    n = len(raw)
    for s in COUNTER_STRIDES:
        if off - s >= 0 and _u32(raw, off - s) == val - 1:
            return True
        if off + s + 4 <= n and _u32(raw, off + s) == val + 1:
            return True
    return False


def is_string_tail_word(raw, off):
    """True when the aligned word at *off* is the last bytes of a
    NUL-terminated ASCII string — a C++ mangled name in one of the ELF's
    string tables — rather than a pointer that happens to encode them.

    Both halves have to hold: the word itself ENDS a string (printable
    bytes then the terminating NUL, inside the word), and it is reached by
    a printable run of at least :data:`STRING_TAIL_LEAD` bytes that starts
    at a NUL (or runs past :data:`STRING_TAIL_SCAN`, at which point it is
    text whatever precedes it).  A genuine pointer fails the second half:
    whatever sits before it in a table, a literal pool or a struct ends in
    the zero high byte of an address, or in padding."""
    if off < 1 or off + 4 > len(raw):
        return False
    k = 0
    while k < 4 and 0x20 <= raw[off + k] <= 0x7e:
        k += 1
    if k == 4 or raw[off + k] != 0:
        return False
    i = off - 1
    n = 0
    while i >= 0 and n < STRING_TAIL_SCAN and 0x20 <= raw[i] <= 0x7e:
        i -= 1
        n += 1
    if n < STRING_TAIL_LEAD:
        return False
    return n >= STRING_TAIL_SCAN or (i >= 0 and raw[i] == 0)


def reference_census(raw, spans, segs=None):
    """Every reference to every display span: ``{span_off: [ref, ...]}``
    (spans with no reference are absent).  *spans* is
    :func:`progtext._display_spans`'s ``[(file_off, text)]``; *segs* the
    :func:`load_segments` list (computed when omitted).

    ``ref = {"kind": "group" | "lone" | "movw_a32" | "movw_t32",
    "delta": int, "offs": [file offsets], "va": int}`` — see the module
    docstring for what each kind is and which look-alikes are dismissed."""
    import numpy as np
    if segs is None:
        segs = load_segments(raw)
    if not segs or not spans:
        return {}
    off2va, _va2off = seg_maps(segs)
    ordered = []
    for off, text in spans:
        va = off2va(off)
        if va is not None:
            ordered.append((va, off, len(text), text))
    if not ordered:
        return {}
    ordered.sort()
    vas = np.array([o[0] for o in ordered], dtype=np.uint64)
    lens = np.array([o[2] for o in ordered], dtype=np.int64)

    def resolve(vals):
        """(hit mask, span index, delta) for an array of candidate VAs."""
        v = vals.astype(np.uint64)
        idx = np.searchsorted(vas, v, side="right") - 1
        ok = idx >= 0
        idx2 = np.where(ok, idx, 0)
        delta = v.astype(np.int64) - vas[idx2].astype(np.int64)
        hit = ok & (delta >= 0) & (delta < lens[idx2])
        return hit, idx2, delta

    refs = {}

    def add(si, kind, delta, offs, va):
        refs.setdefault(ordered[si][1], []).append(
            {"kind": kind, "delta": int(delta), "offs": list(offs),
             "va": int(va)})

    # group runs: one reference per run
    group_words = set()
    runs = group_runs(raw)
    if runs:
        vals = np.array([r[2] for r in runs], dtype=np.uint32)
        hit, idx, delta = resolve(vals)
        for k in np.flatnonzero(hit):
            woff, cnt, val = runs[int(k)]
            add(int(idx[k]), KIND_GROUP, delta[k],
                [woff + 4 * i for i in range(cnt)], val)
    for woff, cnt, _val in runs:
        group_words.update(woff + 4 * i for i in range(cnt))

    # lone aligned words in every PT_LOAD file range
    for (_va, off0, fs, _ms, _fl) in segs:
        start = (off0 + 3) & ~3
        n = (off0 + fs - start) // 4
        if n <= 0:
            continue
        a = np.frombuffer(raw[start: start + n * 4], dtype="<u4")
        hit, idx, delta = resolve(a)
        for k in np.flatnonzero(hit):
            fo = start + int(k) * 4
            if fo in group_words:
                continue
            si = int(idx[k])
            d = int(delta[k])
            val = int(a[k])
            if is_counter_word(raw, fo, val):
                continue
            if is_string_tail_word(raw, fo):
                continue
            if d > 0 and ordered[si][3][d].isspace():
                continue
            add(si, KIND_LONE, d, [fo], val)

    # movw/movt pairs over the executable segments
    for seg in segs:
        if not (seg[4] & PF_X):
            continue
        for kind, pairs in ((KIND_A32, a32_pairs(raw, seg)),
                            (KIND_T32, t32_pairs(raw, seg))):
            if not pairs:
                continue
            vals = np.array([p[3] for p in pairs], dtype=np.uint32)
            hit, idx, delta = resolve(vals)
            for k in np.flatnonzero(hit):
                ow, ot, _rd, imm = pairs[int(k)]
                add(int(idx[k]), kind, delta[k], [ow, ot], imm)

    for lst in refs.values():
        lst.sort(key=lambda r: (r["delta"], r["offs"][0]))
    return refs


# ---------------------------------------------------------------------------
# Rewriting references
# ---------------------------------------------------------------------------

def reference_value(raw, ref):
    """The address *ref* currently encodes in *raw*, or ``None`` when the
    bytes no longer decode as that reference (a group whose words disagree,
    a rewritten instruction)."""
    kind, offs = ref["kind"], ref["offs"]
    try:
        if kind in (KIND_GROUP, KIND_LONE):
            vals = {_u32(raw, o) for o in offs}
            return vals.pop() if len(vals) == 1 else None
        if kind == KIND_A32:
            w = decode_a32(_u32(raw, offs[0]))
            t = decode_a32(_u32(raw, offs[1]))
            if not w or not t or w[0] != "movw" or t[0] != "movt" \
                    or w[1] != t[1]:
                return None
            return w[2] | (t[2] << 16)
        if kind == KIND_T32:
            w = decode_t32(*struct.unpack_from("<HH", raw, offs[0]))
            t = decode_t32(*struct.unpack_from("<HH", raw, offs[1]))
            if not w or not t or w[0] != "movw" or t[0] != "movt" \
                    or w[1] != t[1]:
                return None
            return w[2] | (t[2] << 16)
    except struct.error:
        return None
    return None


def retarget_writes(raw, ref, new_va):
    """``[(file_off, bytes)]`` that make *ref* encode *new_va* — every word
    of a group, or both halves of a movw/movt pair."""
    kind, offs = ref["kind"], ref["offs"]
    new_va &= 0xFFFFFFFF
    if kind in (KIND_GROUP, KIND_LONE):
        b = struct.pack("<I", new_va)
        return [(o, b) for o in offs]
    lo, hi = new_va & 0xFFFF, new_va >> 16
    if kind == KIND_A32:
        return [(offs[0], struct.pack("<I", encode_a32(_u32(raw, offs[0]), lo))),
                (offs[1], struct.pack("<I", encode_a32(_u32(raw, offs[1]), hi)))]
    if kind == KIND_T32:
        out = []
        for o, imm in ((offs[0], lo), (offs[1], hi)):
            h1, h2 = struct.unpack_from("<HH", raw, o)
            out.append((o, struct.pack("<HH", *encode_t32(h1, h2, imm))))
        return out
    raise ValueError("unknown reference kind %r" % (kind,))
