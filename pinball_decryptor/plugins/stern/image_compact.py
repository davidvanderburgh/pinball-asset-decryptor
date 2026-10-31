"""PAD-880: ``image.bin`` without the bodies of the game's sounds nothing plays any more.

A replaced sound longer than its slot plays from a record of its own (appended, the play
tables re-pointed at it) or from a sound bank (the game's request lists name the bank's sound
id): either way the game's own record stays, with its whole body, and ``image.bin`` is mapped
whole beside every bank the game is playing from (:data:`.spike2.soundbank.MAPPED_MAX`).  An
Iron Maiden LE 1.18 card with 23 replaced songs carried 834 MB of their stock bodies in its
1,312 MB ``image.bin``, and its songs did not fit beside it.

What the firmware needs of a record nothing plays, measured on that card:

* every record keeps its place in the master directory, its length word and its identity: a
  record's length shifts the decode parameters of every later one (:mod:`.spike2.masterdir`);
* the sound registration (the boot derive, one forward chain over every record) reads about
  1 KB of each body, in two windows spread over it, into an accumulator that sets every LATER
  record's parameters and container key: those bytes must stay, at the same distance from the
  record's body offset.  Pointing a record at other bytes moved the keys of every record after
  it;
* a body's keystream does not follow its offset: the same bytes decode the same at any
  offset (a stock body shifted by 16 bytes to 1 MB decoded identically), and moving one body
  left every other record's parameters as they were.

So a record nothing plays keeps its directory entry and its windows only: the windows go into
one sparse region, each record's body offset placed so its windows land there, and every
other byte of the file moves down as plain bytes (offsets kept to the same phase of 16).  The
directory is written at the new end.  The result is checked against the input by a full
derive (every record's parameters, its body offset aside) and by decodes, before it is used.
"""

import bisect
import collections
import os

#: Bytes kept at each end of a body that comes out: the codec reads the frame below a body
#: (``Spike2Emu._decode_with_entry`` mirrors 0x80 bytes), and a body that stays may read a
#: little past its end, so the bytes around every body that stays stay too.
MARGIN = 0x100
#: Every move keeps an offset's phase modulo this.
ALIGN = 16
#: Room between one record's windows and another's in the region.
WINDOW_GAP = 64
#: A range holding a play-table descriptor moves by a multiple of this: the resolver whitens a
#: descriptor at a keystream offset taken from its own offset's low bits (``(off ^ xor) &
#: mask``, every mask inside the 0x3F00-byte vf2 window), so the descriptor's bytes stay
#: valid where they land and only the fragment slots naming it change.
DESC_ALIGN = 0x4000
#: ``PAD_STERN_COMPACT=0`` leaves ``image.bin`` as the build made it.
ENV = "PAD_STERN_COMPACT"

Layout = collections.namedtuple(
    "Layout", "moves offsets region region_at region_len md_off size saved gone")
"""A planned compaction.  ``moves`` ``[(src, dst, n)]`` copy the kept bytes in order;
``offsets`` ``{record: new body offset}`` for every record; ``region`` ``[(dst, src, n)]``
the windows of the records that came out (``gone``); ``md_off`` where the directory goes,
``size`` the new file's length with it, ``saved`` how much shorter that is."""


class CompactError(RuntimeError):
    """The compaction could not be planned, or its result is not the same card."""


def enabled():
    return os.environ.get(ENV, "1") != "0"


def windows_of(reads, off, size):
    """The windows ``[(rel, n)]`` of a body at *off*, *size* bytes long, that *reads* (a
    sorted sequence of the file offsets the derive read) holds: contiguous runs."""
    lo = bisect.bisect_left(reads, off)
    hi = bisect.bisect_left(reads, off + size)
    out = []
    for o in reads[lo:hi]:
        o = int(o)
        if out and out[-1][0] + out[-1][1] == o - off:
            out[-1][1] += 1
        else:
            out.append([o - off, 1])
    return [tuple(w) for w in out]


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _up(x, phase):
    """The least offset >= *x* with *phase* modulo :data:`ALIGN`."""
    return x + ((phase - x) % ALIGN)


def plan_layout(file_size, md_off, tail_len, records, dead, windows, pinned=()):
    """The :class:`Layout` that drops the bodies of *dead* records.

    *records* ``{record: (body offset, body bytes)}`` is every record of the directory at
    *md_off* (*tail_len* bytes on disk) of a file *file_size* long; *windows* ``{record:
    [(rel, n)]}`` the bytes the derive reads of each dead one.  A dead record with no window
    or a body too short to gain anything is kept whole.  A kept range holding one of the
    *pinned* offsets (the play tables' descriptors) moves by a multiple of
    :data:`DESC_ALIGN`."""
    pinned = sorted(int(o) for o in pinned)

    def holds(a, b):
        i = bisect.bisect_left(pinned, a)
        return i < len(pinned) and pinned[i] < b

    gone = {}
    for r in sorted(dead):
        off, size = records[r]
        if not windows.get(r) or size <= 4 * MARGIN:
            continue
        gone[r] = (off, size)
    if not gone:
        raise CompactError("no record's body can come out")
    drops = _merge([(off + MARGIN, off + size - MARGIN) for off, size in gone.values()]
                   + [(md_off, md_off + tail_len)])
    keeps, at = [], 0
    for a, b in drops:
        if a > at:
            keeps.append((at, a))
        at = max(at, b)
    if at < file_size:
        keeps.append((at, file_size))
    # each dead record's body offset P: its windows in the region, P >= 0, and its body
    # inside the file (as every record of a stock card is)
    first = {r: min(rel for rel, _n in windows[r]) for r in gone}
    need_at = max(first.values())
    moves, cursor, region_at = [], 0, None
    for a, b in keeps:
        if region_at is None and cursor >= need_at:
            region_at = _up(cursor, 0)
            cursor = region_at          # the region's length is added once it is placed
            break_at = len(moves)
        dst = (cursor + ((a - cursor) % DESC_ALIGN) if holds(a, b)
               else _up(cursor, a % ALIGN))
        moves.append((a, dst, b - a))
        cursor = dst + (b - a)
    if region_at is None:
        region_at = _up(max(cursor, need_at), 0)
        break_at = len(moves)
    # place the windows: the widest record first, each as near the region's start as its
    # phase and the windows already placed allow
    placed, offsets, region = [], {}, []
    starts = []

    def free(a, b):
        i = bisect.bisect_right(starts, a)
        if i and placed[i - 1][1] + WINDOW_GAP > a:
            return False
        return not (i < len(placed) and placed[i][0] < b + WINDOW_GAP)

    for r in sorted(gone, key=lambda r: -(max(rel + n for rel, n in windows[r]) - first[r])):
        off, _size = gone[r]
        p = _up(region_at - first[r], off % ALIGN)
        while not all(free(p + rel, p + rel + n) for rel, n in windows[r]):
            p += ALIGN
        offsets[r] = p
        for rel, n in windows[r]:
            i = bisect.bisect_left(starts, p + rel)
            starts.insert(i, p + rel)
            placed.insert(i, (p + rel, p + rel + n))
            region.append((p + rel, off + rel, n))
    region_len = max(b for _a, b in placed) - region_at
    shift = -(-region_len // DESC_ALIGN) * DESC_ALIGN
    moves = moves[:break_at] + [(a, d + shift, n) for a, d, n in moves[break_at:]]
    data_end = max([d + n for _a, d, n in moves] + [region_at + region_len])

    def new_of(off):
        for a, d, n in moves:
            if a <= off < a + n:
                return d + (off - a)
        return None

    for r, (off, _size) in records.items():
        if r in offsets:
            continue
        o = new_of(off)
        if o is None:
            raise CompactError("record %d's body (offset %d) is in no kept range" % (r, off))
        offsets[r] = o
    body_end = max(offsets[r] + records[r][1] for r in records)
    md = _up(max(data_end, body_end - tail_len), 0)
    size = md + tail_len
    return Layout(moves, offsets, sorted(region), region_at, region_len, md, size,
                  file_size - size, frozenset(gone))


def translate(layout, off):
    """Where a kept byte at *off* of the old file is in the new one (``None``: dropped)."""
    for a, d, n in layout.moves:
        if a <= off < a + n:
            return d + (off - a)
    return None


def write_layout(src_path, dst_path, layout, tail_writes, chunk=8 << 20):
    """Write the compacted file: the kept bytes, the region's windows, the directory
    (*tail_writes* ``{offset: bytes}``, :func:`.spike2.masterdir.write_directory`'s)."""
    with open(src_path, "rb") as fi, open(dst_path, "wb") as fo:
        fo.truncate(layout.size)
        for a, d, n in layout.moves:
            fi.seek(a)
            fo.seek(d)
            left = n
            while left:
                b = fi.read(min(chunk, left))
                if not b:
                    raise CompactError("%s ended at %d, before %d" % (src_path, fi.tell(), a + n))
                fo.write(b)
                left -= len(b)
        for d, a, n in layout.region:
            fi.seek(a)
            fo.seek(d)
            fo.write(fi.read(n))
        for off, data in sorted(tail_writes.items()):
            fo.seek(off)
            fo.write(data)


#: What may differ between a record's derived row before and after: where its body is.
_MOVES = ("body_off", "_rawobj")


def rows_differ(before, after, layout):
    """``[(record, field, before, after)]`` where a derive of the compacted file is not the
    input's: every row's every field, its body offset aside (which must be the layout's)."""
    bad = []
    b = {int(r["idx"]): r for r in before}
    a = {int(r["idx"]): r for r in after}
    if set(a) != set(b):
        return [(None, "records", len(b), len(a))]
    for i, r in sorted(b.items()):
        q = a[i]
        for k in set(r) | set(q):
            if k in _MOVES:
                continue
            if r.get(k) != q.get(k):
                bad.append((i, k, r.get(k), q.get(k)))
        if q.get("body_off") != layout.offsets.get(i):
            bad.append((i, "body_off", layout.offsets.get(i), q.get("body_off")))
        ob, oa = bytes(r.get("_rawobj") or b""), bytes(q.get("_rawobj") or b"")
        if ob[4:] != oa[4:]:
            bad.append((i, "_rawobj", ob.hex(), oa.hex()))
    return bad


def compact(fw_path, src_path, dst_path, dead, log, firmware_for=None, samples=8):
    """Compact *src_path* (a finished ``image.bin``) into *dst_path* without the bodies of
    the *dead* records, and check it.  Returns ``(layout, firmware)``.

    *dead* is a set of record numbers, or of container keys (8 bytes): the records the
    derive registers under them.

    *fw_path* is the program the input is played with (the blip-free cave's, when there is
    one: its derive is the machine's).  *firmware_for(layout)*, when given, returns the
    program the output is played with (a cave rebuilt for the new offsets); the check derives
    the output under it.  Raises :class:`CompactError` when the result is not the same card:
    a record whose parameters moved, or a sound that decodes differently."""
    import numpy as np

    from . import engine as E
    from .spike2 import masterdir as MD
    from .spike2.emulator import Spike2Emu, frame_bytes

    with open(src_path, "rb") as f:
        head = f.read(0x100)
    md_off, count = MD.header_geometry(head)
    file_size = os.path.getsize(src_path)
    keys = Spike2Emu(fw_path, src_path)
    try:
        keys.boot()
        d = MD.read_directory(src_path, keys)
        slots, vf2 = fragment_slots(src_path, head, keys)
        emu = Spike2Emu(fw_path, src_path)
        try:
            emu.boot()
            reads, hh = E._install_consumed_hook(emu)
            rows = emu.derive_params()
            emu.mu.hook_del(hh)
            by = {int(r["idx"]): r for r in rows}
            if len(by) != d.count or set(by) != set(range(d.count)):
                raise CompactError("the derive gave %d rows for %d records" % (len(by), d.count))
            if any(isinstance(k, bytes) for k in dead):
                dead = {i for i, r in by.items() if bytes(r.get("findkey") or b"") in dead}
            reads = np.array(sorted(reads), dtype=np.int64)
            ends = sorted(int(d.body_off(i)) for i in range(d.count)) + [md_off]
            records = {}
            for i in range(d.count):
                off = int(d.body_off(i))
                if off != int(by[i]["body_off"]):
                    raise CompactError("record %d: the directory says %d, the derive %d"
                                       % (i, off, by[i]["body_off"]))
                size = frame_bytes(by[i]) * int(by[i]["length"])
                nxt = ends[bisect.bisect_right(ends, off)] if off < ends[-1] else file_size
                if off < md_off:
                    size = min(size, nxt - off)
                records[i] = (off, size)
            spans = sorted(records.values())
            for (a, n), (b, _m) in zip(spans, spans[1:]):
                if a + n > b and (a, n) != (b, _m):
                    raise CompactError(
                        "two records' bodies overlap (offsets %d and %d): this image.bin "
                        "was laid out by an earlier build" % (a, b))
            # (a body another record shares stays: PAD-880 drops only a body of its own)
            dead = {r for r in dead if r in records and not any(
                j != r and records[j][0] < records[r][0] + records[r][1]
                and records[r][0] < records[j][0] + records[j][1] for j in records)}
            if not dead:
                raise CompactError("every body that could come out shares its bytes")
            windows = {r: windows_of(reads, *records[r]) for r in dead}
            layout = plan_layout(file_size, md_off, MD.tail_len(count), records, dead,
                                 windows, pinned=set(slots.values()))
            # the sounds that stay, decoded before: the shortest few and the first after
            # the first body that comes out
            first_gone = min(records[r][0] for r in dead)
            live = sorted((i for i in records if i not in layout.gone
                           and int(by[i]["length"]) > 4000),
                          key=lambda i: records[i][0])
            pick = [i for i in live if records[i][0] > first_gone][:samples // 2]
            pick += sorted(live, key=lambda i: by[i]["length"])[:samples - len(pick)]
            before = {i: emu.decode(by[i], max_secs=1.0) for i in pick}
        finally:
            emu.close()
        recs = bytearray(d.records)
        for i, off in layout.offsets.items():
            recs[i * MD.RECORD_SIZE:(i + 1) * MD.RECORD_SIZE] = MD.set_geometry(
                d.record(i), body_off=off)
        d2 = d.with_records(bytes(recs), d.count)
        d2.md_off = layout.md_off
        tail = MD.write_directory(d2, keys)
        tail.update(slot_writes(head, slots, vf2, layout))
    finally:
        keys.close()
    write_layout(src_path, dst_path, layout, tail)
    fw_out = firmware_for(layout) if firmware_for is not None else fw_path
    emu = Spike2Emu(fw_out, dst_path)
    try:
        emu.boot()
        rows2 = emu.derive_params()
        bad = rows_differ(rows, rows2, layout)
        if bad:
            raise CompactError(
                "%d record field(s) derive differently from the compacted image.bin "
                "(first: record %s %s %r -> %r)" % ((len(bad),) + tuple(bad[0])))
        by2 = {int(r["idx"]): r for r in rows2}
        for i, got in before.items():
            now = emu.decode(by2[i], max_secs=1.0)
            same = (got is None and now is None) or (
                got is not None and now is not None
                and np.array_equal(got[0], now[0]) and np.array_equal(got[1], now[1]))
            if not same:
                raise CompactError("idx %d decodes differently from the compacted image.bin"
                                   % i)
    finally:
        emu.close()
    n = check_descriptors(fw_path, src_path, fw_out, dst_path, layout)
    log("image.bin without the bodies nothing plays: %d record(s) checked by a full derive, "
        "%d sound(s) decoded the same and %d sound id(s) resolved to the same descriptor."
        % (len(rows2), len(before), n), "info")
    return layout, fw_out


def fragment_slots(path, head, emu):
    """``({slot: descriptor offset}, vf2)``: what every slot of ``image.bin``'s fragment
    table (``hdr[0x28]``, ``hdr[0x5c]`` fragments of :func:`.spike2.soundbank.fragment_stride`
    slots, each an offset whitened with four vf2 bytes at
    :func:`~.spike2.soundbank.slot_vf2_offset`) names, read with *emu*'s keystream.  The
    descriptors sit at the end of the bodies, just before the directory, and the game finds
    them only through these slots: moved without them, no sound id resolves and the game
    plays none of image.bin's sounds (PAD-880's first rig run)."""
    import struct
    from .spike2 import soundbank as SB
    table = struct.unpack_from("<I", head, SB.HDR_FRAG_TABLE)[0]
    nfrag = struct.unpack_from("<I", head, SB.HDR_FRAGMENTS)[0]
    stride = SB.fragment_stride(head)
    vf2 = bytes(emu.mu.mem_read(emu.VF2_VA, SB.VF2_WINDOW + 0x100))
    size = os.path.getsize(path)
    out = {}
    with open(path, "rb") as f:
        f.seek(table)
        raw = f.read(nfrag * stride * SB.FRAG_SLOT)
    for slot in range(len(raw) // SB.FRAG_SLOT):
        word = struct.unpack_from("<I", raw, slot * SB.FRAG_SLOT)[0]
        off = word ^ struct.unpack_from("<I", vf2, SB.slot_vf2_offset(slot))[0]
        if 0 < off < size:
            out[slot] = off
    return out, vf2


def slot_writes(head, slots, vf2, layout):
    """``{file offset: bytes}``: the fragment slots naming a descriptor *layout* moved, each
    naming it where it lands (a move of a multiple of :data:`DESC_ALIGN`, so the descriptor
    stays whitened right)."""
    import struct
    from .spike2 import soundbank as SB
    table = struct.unpack_from("<I", head, SB.HDR_FRAG_TABLE)[0]
    out = {}
    for slot, off in slots.items():
        new = translate(layout, off)
        if new is None:
            raise CompactError("fragment slot %d's descriptor (offset %d) would be dropped"
                               % (slot, off))
        if (new - off) % DESC_ALIGN:
            raise CompactError("fragment slot %d's descriptor moves by %d, not a multiple of "
                               "%#x" % (slot, new - off, DESC_ALIGN))
        if new != off:
            word = new ^ struct.unpack_from("<I", vf2, SB.slot_vf2_offset(slot))[0]
            out[table + slot * SB.FRAG_SLOT] = struct.pack("<I", word & 0xFFFFFFFF)
    return out


def check_descriptors(fw_in, src_path, fw_out, dst_path, layout):
    """Every sound id resolved through the game's own resolver on both files: the same
    descriptor bytes, where *layout* put them.  Returns how many resolved; raises
    :class:`CompactError` on the first that does not match."""
    import struct

    from .spike2 import sfx_names as SN
    from .spike2.emulator import Spike2Emu

    def resolve_all(fw, path):
        emu = Spike2Emu(fw, path)
        try:
            emu.boot()
            res, out = SN._find_resolver(emu)
            if res is None:
                raise CompactError("the game's descriptor resolver could not be located")
            got = {}
            for sid in range(SN.sid_ceiling(path)):
                r = SN.resolve_descriptor(emu, res, out, sid)
                if r is not None:
                    got[sid] = (r[0], bytes(r[2]))
            return got
        finally:
            emu.close()

    a = resolve_all(fw_in, src_path)
    b = resolve_all(fw_out, dst_path)
    if set(a) != set(b):
        raise CompactError("%d sound id(s) resolve on one file and not the other"
                           % len(set(a) ^ set(b)))
    with open(src_path, "rb") as f:
        md_off = struct.unpack_from("<I", f.read(0x48), 0x40)[0]
    for sid, (off, desc) in sorted(a.items()):
        noff, ndesc = b[sid]
        # (the resolver's window runs on past the last descriptor into the directory,
        # which is not the same bytes where it moved)
        n = max(0, min(len(desc), md_off - off))
        if noff != translate(layout, off) or ndesc[:n] != desc[:n]:
            raise CompactError("sound id %d resolves to another descriptor on the compacted "
                               "image.bin (offset %d -> %d)" % (sid, off, noff))
    if not a:
        raise CompactError("no sound id resolved")
    return len(a)

