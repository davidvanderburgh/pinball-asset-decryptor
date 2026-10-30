"""Stern S.A.M. DMD animations: decode every frame of a code update's
graphics table, and encode edited frames back in.

Worked out from the game code (PAD-584; TRON 1.74's renderer at
``0x2b194`` and its per-format function table, then checked on every
title).  The art area after the sound table is one *graphics table* of
bank pointers (located, like the font table before it, by the four code
literals ``font count, font table, graphics count, graphics table`` with
``graphics table = font table + 20 * font count``), each to a record:

    u32 id      the renderer's frame cache matches only the low 16 bits
    u32 flags   4 = keep the decoded frame cached (an animation's
                keyframe); 2 or 1 = more delta frames follow
    s16 width, s16 height    (the DMD is 128 x 32; taller ones scroll)
    u8  format, then the data

Pixels are one byte each once decoded, row by row: 0-15 = the DMD's 16
shades, 0xFF = transparent.  The formats (the 2008-2010 engines number
the row-order ones 8 and 10 instead of 7 and 9; the code is the same):

* 0 raw bytes; 12 raw 4-bit, low nibble first.
* 1 / 7 (8) run-length, in column / row order: byte ``c`` (0 ends),
  ``n = c >> 2``; ``c & 3`` = 0 ``n`` literal bytes, 1 ``n`` zeros, 2 ``n``
  x 0x0F, 3 one byte repeated ``n`` times.
* 3 / 9 (10) delta on the previous frame (the cached frame whose id is
  this id - 1), in column / row order: signed byte ``c`` (0 ends),
  negative = skip ``-c`` pixels, positive = ``c`` literal bytes.  The
  game patches the cached frame in place and re-ids it, so a run of
  deltas after a keyframe is an animation.

Which record plays when is in the game code (loops over record numbers),
not in the data, so an animation here is just its frames, numbered by
their place in the graphics table.

The 2006-2008 titles (World Poker Tour, Pirates, Family Guy, Wheel of
Fortune) have only raw pictures with a 5-byte header (w, h, format) and
no animation data; :func:`read_table` refuses them.

Writing keeps every record where it is unless nothing but the table
points at it: an edited frame is re-encoded in the smallest exact form
the record's place allows (:func:`encodings`) and goes into its own
bytes, or the frames of a run of adjacent movable records share the
run's bytes and the table is repointed.  The art area is packed solid,
so a frame that can't fit even then is simplified (fewer shades) until
it does, or keeps its original picture.
"""

import struct
from dataclasses import dataclass, field

import numpy as np

from .sam_sound import bank_pointer, file_offset

TRANSPARENT = 0xFF
HEADER = 13
BANK = 0x800000

# format -> (kind, column order?)
_KINDS = {0: ("raw", False), 12: ("nib", False),
          1: ("rle", True), 7: ("rle", False), 8: ("rle", False),
          3: ("delta", True), 9: ("delta", False), 10: ("delta", False)}
DELTAS = (3, 9, 10)
KEYFRAMES = (0, 1, 7, 8, 12)


class SamAnimError(Exception):
    """The file's graphics table could not be read."""


@dataclass(frozen=True)
class Record:
    number: int      # place in the graphics table
    offset: int      # of the record in the file
    id: int
    flags: int
    width: int
    height: int
    fmt: int
    length: int      # bytes the record's data really uses, header included

    @property
    def key(self):
        return self.id & 0xFFFF

    @property
    def is_delta(self):
        return self.fmt in DELTAS


@dataclass
class ArtTable:
    literals: int            # file offset of the four code literals
    table: int               # file offset of the graphics table
    records: list            # [Record], in table order
    row_rle: int = 7         # this engine's row-order format numbers
    row_delta: int = 9
    has_nibble: bool = True  # format 12 exists
    #: formats the file's records use (only these are written)
    formats: frozenset = frozenset()
    #: number -> True when nothing but the table points at the record
    movable: dict = field(default_factory=dict)
    #: the table's entries: 4-byte bank pointers (SAM) or 8-byte file
    #: offsets (Stern Spike 1, PAD-870)
    entry: int = 4
    #: records start on this boundary
    align: int = 4
    #: a run of records laid out again stays inside one bank this big
    #: (None: the file has no banks)
    bank: int = BANK

    def by_offset(self):
        return sorted(self.records, key=lambda r: r.offset)


def _rec_length(data, off, w, h, fmt):
    n = w * h
    p = off + HEADER
    kind = _KINDS.get(fmt, (None,))[0]
    if kind == "raw":
        return HEADER + n
    if kind == "nib":
        return HEADER + (n + 1) // 2
    end = len(data)
    if kind == "rle":
        while p < end:
            c = data[p]
            p += 1
            if c == 0:
                return p - off
            t = c & 3
            if t == 0:
                p += c >> 2
            elif t == 3:
                p += 1
    elif kind == "delta":
        while p < end:
            c = data[p]
            p += 1
            if c == 0:
                return p - off
            if c < 128:
                p += c
    raise SamAnimError("record at %#x (format %d) runs off the end"
                       % (off, fmt))


def _literal_candidates(data):
    n = min(len(data), 0x200000) // 4
    a = np.frombuffer(data, "<u4", count=n).astype(np.int64)
    fc, fp, gc, gp = a[:-3], a[1:-2], a[2:-1], a[3:]
    hit = np.nonzero((gp == fp + 20 * fc) & (fc > 0) & (fc < 1000)
                     & (gc > 0) & (gc < 100000))[0]
    return [(int(i) * 4, int(gc[i]), int(gp[i])) for i in hit]


def _parse(data, lit, count, ptr):
    table = file_offset(ptr)
    if table + 4 * count > len(data):
        return None
    out = []
    for i, p in enumerate(struct.unpack_from("<%dI" % count, data, table)):
        off = file_offset(p)
        if off + HEADER > len(data):
            return None
        rid, fl, w, h = struct.unpack_from("<IIhh", data, off)
        fmt = data[off + 12]
        if fmt not in _KINDS or fl >= 8 or not (0 < w <= 1024) \
                or not (0 < h <= 1024):
            return None
        out.append(Record(i, off, rid, fl, w, h, fmt,
                          _rec_length(data, off, w, h, fmt)))
    return ArtTable(lit, table, out)


def read_table(data):
    """The :class:`ArtTable` of a SAM image (bytes)."""
    for lit, count, ptr in _literal_candidates(data):
        try:
            art = _parse(data, lit, count, ptr)
        except SamAnimError:
            art = None
        if art is not None:
            break
    else:
        raise SamAnimError("no graphics table with frame records (the "
                           "2006-2008 titles have none)")
    finish(art)
    art.movable = _movable(data, art)
    return art


def finish(art):
    """Fill in *art*'s format facts from its records (which formats the
    engine has, and its row-order numbers)."""
    fmts = {r.fmt for r in art.records}
    art.formats = frozenset(fmts)
    if fmts & {8, 10}:
        art.row_rle, art.row_delta, art.has_nibble = 8, 10, False
    else:
        art.has_nibble = 12 in fmts
        if not fmts & {7, 9, 12}:
            # an engine that shows only 0/1/3: offer no row formats
            art.row_rle = art.row_delta = None
    return art


def _movable(data, art):
    """number -> True when the record's pointer occurs nowhere in the
    file but its table entry (fonts' glyph arrays point at records, and
    anything else might; a chance match only pins a record in place)."""
    n = len(data) // 4
    words = np.frombuffer(data, "<u4", count=n)
    ptrs = np.frombuffer(data, "<u4", count=len(art.records),
                         offset=art.table)
    hits = np.isin(words, ptrs)
    lo = art.table // 4
    hits[lo:lo + len(art.records)] = False
    seen = set(int(v) for v in np.unique(words[hits]))
    return {r.number: int(ptrs[r.number]) not in seen for r in art.records}


def still_numbers(data, art):
    """Records that are plain pictures, not animation frames: the ones the
    Replace Images side writes (:func:`sam_art.read_art`'s bitmaps, PAD-583:
    raw, every pixel a shade or clear, ending before the next record, and
    no delta's base).  Every other record is an animation frame and
    written here, so between them each record has exactly one writer."""
    from . import sam_art
    try:
        stills = set(sam_art.read_art(data).bitmaps)
    except sam_art.SamArtError:
        return set()
    return {n for n in stills if n < len(art.records)}


def animation_numbers(data, art):
    """Every record :func:`still_numbers` leaves: the ones written here."""
    stills = still_numbers(data, art)
    return {r.number for r in art.records if r.number not in stills}


# --------------------------------------------------------------------------
# decode
# --------------------------------------------------------------------------

def _rle_decode(data, p, n):
    out = bytearray()
    while True:
        c = data[p]
        p += 1
        if c == 0:
            break
        k, t = c >> 2, c & 3
        if t == 1:
            out += bytes(k)
        elif t == 2:
            out += b"\x0f" * k
        elif t == 0:
            out += data[p:p + k]
            p += k
        else:
            out += data[p:p + 1] * k
            p += 1
    if len(out) != n:
        raise SamAnimError("run-length data gives %d pixels, not %d"
                           % (len(out), n))
    return out


def _delta_apply(lin, data, p):
    pos = 0
    n = len(lin)
    while True:
        c = data[p]
        p += 1
        if c == 0:
            return
        if c >= 128:
            pos += 256 - c
        else:
            if pos + c > n:
                raise SamAnimError("delta writes past the frame")
            lin[pos:pos + c] = data[p:p + c]
            p += c
            pos += c


def _to_scan(img, col):
    return bytearray((img.T if col else img).tobytes())


def _from_scan(lin, w, h, col):
    a = np.frombuffer(bytes(lin), np.uint8)
    return (a.reshape(w, h).T if col else a.reshape(h, w)).copy()


def decode_record(data, rec, base=None):
    """The frame (``uint8 [h, w]``) of *rec*; a delta needs the frame it
    builds on as *base*."""
    w, h, n = rec.width, rec.height, rec.width * rec.height
    kind, col = _KINDS[rec.fmt]
    p = rec.offset + HEADER
    if kind == "raw":
        return np.frombuffer(data, np.uint8, n, p).reshape(h, w).copy()
    if kind == "nib":
        b = np.frombuffer(data, np.uint8, (n + 1) // 2, p)
        px = np.empty(len(b) * 2, np.uint8)
        px[0::2] = b & 15
        px[1::2] = b >> 4
        return px[:n].reshape(h, w).copy()
    if kind == "rle":
        return _from_scan(_rle_decode(data, p, n), w, h, col)
    if base is None or base.shape != (h, w):
        raise SamAnimError("delta frame %d has no frame to build on"
                           % rec.number)
    lin = _to_scan(base, col)
    _delta_apply(lin, data, p)
    return _from_scan(lin, w, h, col)


def bases(art):
    """number -> number of the record a delta builds on, as the game's
    frame cache finds it (the latest frame decoded with id - 1 that is
    still cached: a keyframe with flag 4, or a delta with flag 2 or 4)."""
    cache = {}
    out = {}
    for r in art.records:
        if r.is_delta:
            src = cache.pop((r.key - 1) & 0xFFFF, None)
            if src is None:
                src = cache.pop(r.key, None)
            out[r.number] = src
            if r.flags & 6:
                cache[r.key] = r.number
        else:
            cache.pop((r.key - 1) & 0xFFFF, None)
            cache.pop(r.key, None)
            if r.flags & 4:
                cache[r.key] = r.number
    return out


def decode_all(data, art, progress=None):
    """number -> frame, for every record (deltas chained as the game
    does)."""
    base_of = bases(art)
    frames = {}
    n = len(art.records)
    for r in art.records:
        b = base_of.get(r.number)
        frames[r.number] = decode_record(
            data, r, frames[b] if b is not None else None)
        if progress and (r.number % 64 == 0 or r.number == n - 1):
            progress(r.number + 1, n)
    return frames


# --------------------------------------------------------------------------
# encode
# --------------------------------------------------------------------------

class _WindowMin:
    """Minimum of ``key(j)`` over a window of indices whose both ends only
    move down (the encoders walk the frame backwards)."""

    def __init__(self, key):
        self.key = key
        self.q = []     # indices, keys increasing from the far end
        self.head = 0

    def push(self, j):
        # j is below every index held; drop the ones it beats
        q, kj = self.q, self.key(j)
        while len(q) > self.head and self.key(q[-1]) >= kj:
            q.pop()
        q.append(j)

    def best(self, hi):
        """argmin over the held indices <= hi (None when empty)."""
        q = self.q
        while self.head < len(q) and q[self.head] > hi:
            self.head += 1
        return q[self.head] if self.head < len(q) else None


def _equal_ahead(a, b=None):
    """out[i] = the length of the run of equal entries starting at i, or,
    given *b*, how many entries from i on equal *b*'s."""
    n = len(a)
    out = [0] * (n + 1)
    if b is None:
        out[n - 1] = 1 if n else 0
        for i in range(n - 2, -1, -1):
            out[i] = out[i + 1] + 1 if a[i] == a[i + 1] else 1
    else:
        for i in range(n - 1, -1, -1):
            out[i] = out[i + 1] + 1 if a[i] == b[i] else 0
    return out


def _shortest(n, reach_a, unit_a, max_lit):
    """Shortest stream over n pixels with two token kinds: an 'a' token
    covering 1..reach_a[i] pixels for unit_a(i) bytes, and a literal of
    1..max_lit pixels for 1 + length bytes; 1 byte ends it.  Returns
    ``[(kind, length)]``.  Exact: both choices are window minimums of the
    cost-to-end, and every window's ends only move down as i does."""
    INF = 1 << 30
    cost = [INF] * (n + 1)
    cost[n] = 1
    choice = [None] * n
    lit = _WindowMin(lambda j: j + cost[j])
    run = _WindowMin(lambda j: cost[j])
    for i in range(n - 1, -1, -1):
        lit.push(i + 1)
        run.push(i + 1)
        r = reach_a[i]
        j = run.best(i + r) if r else None
        ca = unit_a(i) + cost[j] if j is not None else INF
        k = lit.best(i + max_lit)
        cl = 1 + k - i + cost[k]
        if ca <= cl:
            cost[i], choice[i] = ca, ("a", j - i)
        else:
            cost[i], choice[i] = cl, ("l", k - i)
    out = []
    i = 0
    while i < n:
        t, k = choice[i]
        out.append((t, k))
        i += k
    return out


def rle_encode(lin):
    """The shortest run-length stream (terminator included) for the pixel
    bytes *lin*, in the order given."""
    n = len(lin)
    eq = _equal_ahead(lin)
    reach = [min(eq[i], 63) for i in range(n)]
    out = bytearray()
    i = 0
    for t, k in _shortest(n, reach,
                          lambda i: 1 if lin[i] in (0, 15) else 2, 63):
        if t == "l":
            out.append(k << 2)
            out += bytes(lin[i:i + k])
        else:
            v = lin[i]
            if v == 0:
                out.append(k << 2 | 1)
            elif v == 15:
                out.append(k << 2 | 2)
            else:
                out += bytes((k << 2 | 3, v))
        i += k
    out.append(0)
    return bytes(out)


def delta_encode(base, lin):
    """The shortest delta stream turning *base* into *lin* (same order)."""
    last = len(lin)
    while last > 0 and base[last - 1] == lin[last - 1]:
        last -= 1
    same = _equal_ahead(lin[:last], base[:last])
    reach = [min(same[i], 128) for i in range(last)]
    out = bytearray()
    i = 0
    for t, k in _shortest(last, reach, lambda i: 1, 127):
        if t == "a":
            out.append(256 - k)
        else:
            out.append(k)
            out += bytes(lin[i:i + k])
        i += k
    out.append(0)
    return bytes(out)


def _header(rec, fmt):
    return struct.pack("<IIhhB", rec.id, rec.flags, rec.width, rec.height,
                       fmt)


def allowed_formats(art, rec):
    """Formats *rec*'s place can hold with the game's frame cache behaving
    exactly as before.  A raw record stays raw (it always fits).  A
    run-length keyframe may be either run-length order or 4-bit.  A delta
    may be either delta order, or a whole frame when its flags let the
    cache end the same way (keep it: flag 4; drop it: no 2 or 4) --
    formats 1/7/12 first drop the cached id - 1 frame themselves."""
    full = [1]
    if art.row_rle:
        full.append(art.row_rle)
    if art.has_nibble:
        full.append(12)
    if rec.fmt in (0, 12):
        return [rec.fmt]
    if rec.is_delta:
        out = [3]
        if art.row_delta:
            out.append(art.row_delta)
        if rec.flags & 4 or not rec.flags & 6:
            out += full
    else:
        out = full
    # a format the file never uses might be missing from its renderer
    return [f for f in out if f in art.formats or f == rec.fmt]


def encodings(art, rec, frame, base=None):
    """``[(format, record bytes)]`` for *frame* at *rec*'s place, shortest
    first (deltas need the *base* frame the game will patch)."""
    h, w = frame.shape
    if (h, w) != (rec.height, rec.width):
        raise SamAnimError("frame %d is %dx%d, not %dx%d"
                           % (rec.number, w, h, rec.width, rec.height))
    opaque16 = int(frame.max()) <= 15
    out = []
    for fmt in allowed_formats(art, rec):
        kind, col = _KINDS[fmt]
        if kind == "raw":
            body = frame.tobytes()
        elif kind == "nib":
            if not opaque16:
                continue
            px = frame.reshape(-1)
            if len(px) & 1:
                px = np.append(px, 0)
            body = (px[0::2] | (px[1::2] << 4)).astype(np.uint8).tobytes()
        elif kind == "rle":
            body = rle_encode(_to_scan(frame, col))
        else:
            if base is None:
                continue
            body = delta_encode(_to_scan(base, col), _to_scan(frame, col))
        out.append((fmt, _header(rec, fmt) + body))
    out.sort(key=lambda fb: len(fb[1]))
    return out


def simplify(frame, levels, base=None):
    """*frame* with its shades cut to *levels* evenly spaced ones (0 and 15
    and transparency kept); next to a *base* frame, pixels that came out
    within one step of the base's take the base's value (deltas shrink)."""
    out = frame.copy()
    shade = out <= 15
    step = 15.0 / (levels - 1)
    q = np.rint(np.rint(out[shade] / step) * step).astype(np.uint8)
    out[shade] = q
    if base is not None:
        near = shade & (base <= 15) & (np.abs(out.astype(int) - base) <= step)
        out[near] = base[near]
    return out


SIMPLIFY_LEVELS = (8, 4, 2)


def _align(x, a=4):
    return (x + a - 1) & ~(a - 1)


def slots(art):
    """number -> (start, end) bytes the record may use in place: its own,
    plus the alignment padding before the next record."""
    order = art.by_offset()
    out = {}
    for r, nxt in zip(order, order[1:] + [None]):
        end = _align(r.offset + r.length, art.align)
        if nxt is not None:
            end = min(end, nxt.offset)
        out[r.number] = (r.offset, max(end, r.offset + r.length))
    return out


def runs(art, owned):
    """Groups of records (numbers, in file order) that may be laid out
    again together: adjacent owned movable records with only padding
    between them, all in one 8 MB bank (where the file has banks).  Every
    other owned record is a group of its own."""
    sl = slots(art)
    groups = []
    cur = []
    prev_end = None
    for r in art.by_offset():
        ok = r.number in owned and art.movable.get(r.number)
        if ok and cur and prev_end is not None and r.offset == prev_end \
                and (not art.bank or r.offset // art.bank
                     == art.records[cur[0]].offset // art.bank):
            cur.append(r.number)
        else:
            if cur:
                groups.append(cur)
            cur = [r.number] if ok else []
            if r.number in owned and not ok:
                groups.append([r.number])
        prev_end = sl[r.number][1]
    if cur:
        groups.append(cur)
    return groups


@dataclass
class WritePlan:
    #: (file offset, bytes) to put in the image
    patches: list = field(default_factory=list)
    #: graphics-table number -> new file offset (records that moved)
    moved: dict = field(default_factory=dict)
    #: number -> how it was written ("exact", "8 shades", "original")
    how: dict = field(default_factory=dict)
    #: number -> (format, record bytes) written, every re-encoded record
    written: dict = field(default_factory=dict)
    #: frames the game will now show (number -> frame)
    frames: dict = field(default_factory=dict)
    #: records written whole into the *spare* space, out of their run
    away: set = field(default_factory=set)


def plan_write(data, art, frames, edits, owned, spare=None):
    """How to write *edits* (number -> new frame) into the image.

    *frames* are the original decoded frames (:func:`decode_all`); only
    *owned* records are written.  Every delta whose base frame changes is
    re-encoded too, so the frames the game shows are exactly the edited
    ones and the originals everywhere else -- or, for a frame that can't
    fit, a simplified version of it, or its original.

    *spare* (optional) is room the file has free elsewhere, an object whose
    ``take(n)`` returns the file offset of ``n`` bytes it gives up, or
    None: an edited keyframe that doesn't fit its own run goes there whole
    (its table entry repointed) before any picture loses shades."""
    base_of = bases(art)
    recs = art.records
    sl = slots(art)
    plan = WritePlan()
    edits = {k: v for k, v in edits.items() if k in owned}
    if not edits:
        return plan
    followers = {}
    for k, b in base_of.items():
        if b is not None:
            followers.setdefault(b, []).append(k)
    groups = runs(art, owned)
    group_of = {k: gi for gi, g in enumerate(groups) for k in g}

    # every delta after an edited frame is written again, against the
    # frame the game will now have under it
    target = dict(edits)
    touched = set(edits)
    stack = list(edits)
    while stack:
        k = stack.pop()
        for f in followers.get(k, ()):
            if f not in touched:
                touched.add(f)
                stack.append(f)
    for k in touched:
        target.setdefault(k, frames[k])

    shown = {}
    done_groups = set()

    def settle(gi):
        if gi in done_groups:
            return
        done_groups.add(gi)
        g = groups[gi]
        work = sorted(n for n in g if n in touched)
        # bases in other groups first (a delta's base is an earlier record)
        for n in work:
            b = base_of.get(n)
            if b in touched and group_of.get(b) not in (None, gi):
                settle(group_of[b])
        start = sl[g[0]][0]
        end = sl[g[-1]][1]
        ladder = (None,) + SIMPLIFY_LEVELS + ("original",)
        step = {n: 0 for n in work if n in edits}

        def attempt():
            trial, body, fmts = {}, {}, {}
            for n in work:
                b = base_of.get(n)
                base = None
                if b is not None:
                    base = trial[b] if b in trial else shown.get(b, frames[b])
                want = target[n]
                level = ladder[step[n]] if n in step else None
                if level == "original":
                    want = frames[n]
                elif level is not None:
                    want = simplify(want, level, base)
                enc = encodings(art, recs[n], want, base)
                if not enc:
                    raise SamAnimError("frame %d has no encoding" % n)
                trial[n] = want
                fmts[n], body[n] = enc[0]
            size = 0
            for n in g:
                if n in away:
                    continue
                size = _align(size, art.align)
                size += len(body[n]) if n in body else recs[n].length
            return trial, body, fmts, start + size <= end

        # exact first; while it doesn't fit, move the largest edited
        # keyframe out to the spare room (if any takes it), else take the
        # largest edited frame one step down the ladder (fewer shades, then
        # its original), so only as much detail goes as the space needs.
        # Originals always fit: the encoder is never longer than the game's
        # own data.
        away = {}
        trial, body, fmts, fits = attempt()
        while not fits:
            if spare is not None:
                # a keyframe's bytes don't depend on any other frame's, so
                # the room it takes stays right whatever happens after
                cand = sorted((n for n in step if step[n] == 0
                               and n not in away and art.movable.get(n)
                               and base_of.get(n) is None),
                              key=lambda k: (-len(body[k]), k))
                for n in cand:
                    off = spare.take(len(body[n]))
                    if off is not None:
                        away[n] = off
                        break
                else:
                    cand = None
                if cand:
                    trial, body, fmts, fits = attempt()
                    continue
            left = [n for n in step if step[n] < len(ladder) - 1
                    and n not in away]
            if not left:
                raise SamAnimError("frames %s don't fit their place" % work)
            n = max(left, key=lambda k: (len(body[k]), -k))
            step[n] += 1
            trial, body, fmts, fits = attempt()
        shown.update(trial)
        for n in work:
            plan.written[n] = (fmts[n], len(body[n]))
        for n, k in step.items():
            level = ladder[k]
            plan.how[n] = ("exact" if level is None else
                           "original" if level == "original" else
                           "%d shades" % level)
        for n, off in away.items():
            plan.patches.append((off, body[n]))
            plan.moved[n] = off
            plan.away.add(n)
        buf = bytearray()
        for n in g:
            if n in away:
                continue
            buf += bytes(_align(len(buf), art.align) - len(buf))
            off = start + len(buf)
            if off != recs[n].offset:
                plan.moved[n] = off
            r = recs[n]
            buf += body[n] if n in body else data[r.offset:r.offset + r.length]
        # what was there past the last record stays (padding is unread)
        plan.patches.append((start, bytes(buf)))

    for k in sorted(touched):
        if k in group_of:
            settle(group_of[k])
    plan.frames = shown
    return plan


def apply_plan(image, art, plan):
    """Put *plan* into *image* (a bytearray).  Returns ``[(start, end,
    byte-sum delta)]`` for :func:`sam_sound.fix_checksums`."""
    changes = []
    for off, buf in plan.patches:
        old = bytes(image[off:off + len(buf)])
        if old != buf:
            image[off:off + len(buf)] = buf
            changes.append((off, off + len(buf), sum(buf) - sum(old)))
    for n, off in plan.moved.items():
        at = art.table + art.entry * n
        old = bytes(image[at:at + art.entry])
        new = struct.pack("<I", bank_pointer(off)) if art.entry == 4 \
            else struct.pack("<Q", off)
        image[at:at + art.entry] = new
        changes.append((at, at + art.entry, sum(new) - sum(old)))
    return changes
