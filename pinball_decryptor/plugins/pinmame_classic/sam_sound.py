"""Stern S.A.M. sounds: read every sample out of a code update, and write
replacements back in place.

A SAM ``.bin`` is the whole flash image: ARM code, then a data area that
holds the DMD art and every sound.  The sound side, worked out from the
game code itself (PAD-582; the same on all 24 titles tried, WPT 2006 to
The Walking Dead 2014):

*Pointers* are bank-encoded: ``bank << 24 | offset`` with 8 MB banks, so
file offset = ``(p >> 24) << 23 | (p & 0xFFFFFF)``.

*The sound table* is the long run of pointers at the start of the data
area (one per sound number per language), each to a *script* record:
``05 <voice mask> <voices needed> <u32>`` followed by byte-code.  The
script's PLAY opcode names a voice and a pointer to a *sample*.  Four
generations of the script engine exist; they differ only in which
opcodes they have (:data:`ENGINES`, argument lengths as the game's own
dispatch table measures them), so the one a file uses is the one that
parses all of its scripts and finds samples at their PLAYs.

*A sample* is an 8-byte header -- ``u32 count``, three bytes, ``kind`` --
then its data.  ``kind`` 1/2/3 is IMA ADPCM (4-bit, low nibble first,
predictor and step index starting at 0, the standard tables) played at
24 / 12 / 8 kHz, ``count`` nibbles; kind 0 is 16-bit PCM at 24 kHz (no
title uses it).  Samples tile the sound area end to end, never across an
8 MB bank.

*Checksums*: right before the data area a table of ``(start, end,
~bytesum)`` triplets covers the image in sections; on newer titles
(those whose update code says "VERIFYING IMAGE", 2010 on) the file's
last four bytes are ``~bytesum`` of everything before them, which the
USB update checks.  Some shipped files' section sums don't match their
own bytes, so a write moves every sum by exactly what it changed rather
than recomputing it: whatever held for the file before still holds.

A replacement is re-encoded into the sample's own slot: same rate, same
length, same place, so nothing else in the image moves.
"""

import array
import struct
from dataclasses import dataclass, field

import numpy as np

M32 = 0xFFFFFFFF

#: opcode argument lengths per script-engine generation, and the PLAY
#: opcode (voice byte + sample pointer).
ENGINES = {
    "v18": ((0, 2, 2, 0, 2, 6, 0, 1, 4, 15, 5, 1, 2, 4, 1, 4, 1, 8), 10),
    "v17": ((0, 2, 2, 0, 2, 6, 0, 1, 4, 15, 5, 1, 2, 4, 1, 4, 1), 10),
    "v15": ((0, 2, 2, 0, 2, 6, 1, 15, 5, 1, 2, 4, 1, 4, 1), 8),
    "v14": ((0, 2, 2, 0, 2, 6, 1, 15, 5, 1, 2, 1, 4, 1), 8),
}

#: sample kind -> playback rate (Hz)
RATES = {0: 24000, 1: 24000, 2: 12000, 3: 8000}

SCRIPT_MAGIC = 5
_MAX_SCRIPT_OPS = 4000

_STEPS = (7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34,
          37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
          157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494,
          544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552,
          1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428,
          4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487,
          12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086,
          29794, 32767)
_INDEX = (-1, -1, -1, -1, 2, 4, 6, 8)
# (step index * 16 + nibble) -> signed difference / next (index * 16)
_DIFF = []
_NEXT = []
for _si, _step in enumerate(_STEPS):
    for _nib in range(16):
        _d = _step >> 3
        if _nib & 4:
            _d += _step
        if _nib & 2:
            _d += _step >> 1
        if _nib & 1:
            _d += _step >> 2
        _DIFF.append(-_d if _nib & 8 else _d)
        _NEXT.append(max(0, min(88, _si + _INDEX[_nib & 7])) * 16)
del _si, _step, _nib, _d


class SamSoundError(Exception):
    """The file's sound area could not be read (not SAM, or unknown)."""


def file_offset(ptr):
    """File offset of a bank-encoded SAM flash pointer."""
    return ((ptr >> 24) << 23) | (ptr & 0xFFFFFF)


def bank_pointer(offset):
    return ((offset >> 23) << 24) | (offset & 0x7FFFFF)


@dataclass(frozen=True)
class Sample:
    offset: int          # of the 8-byte header in the file
    count: int           # samples (ADPCM: nibbles)
    kind: int

    @property
    def rate(self):
        return RATES[self.kind]

    @property
    def data_offset(self):
        return self.offset + 8

    @property
    def data_size(self):
        return self.count * 2 if self.kind == 0 else (self.count + 1) // 2

    @property
    def seconds(self):
        return self.count / self.rate


@dataclass
class SoundBank:
    engine: str
    table: int                       # file offset of the sound table
    entries: int                     # pointers in it
    samples: list                    # [Sample], in file order
    #: sample offset -> sound-table indices whose script plays it
    played_by: dict = field(default_factory=dict)

    @property
    def seconds(self):
        return sum(s.seconds for s in self.samples)


def _find_table(data):
    """``(offset, count)`` of the sound table: the longest run of words
    in the first 8 MB that are either 0 or bank pointers to a byte 5."""
    n = min(len(data), 0x800000) // 4
    a = np.frombuffer(data, "<u4", count=n).astype(np.int64)
    off = ((a >> 24) << 23) | (a & 0xFFFFFF)
    ok = ((a >> 24) < 16) & ((a & 0xFFFFFF) < 0x800000) & (off < len(data))
    idx = np.nonzero(ok & (a != 0))[0]
    hit = np.zeros(n, bool)
    hit[idx] = np.frombuffer(data, np.uint8)[off[idx]] == SCRIPT_MAGIC
    good = hit | (a == 0)
    # runs of `good`, scored by their hits
    edges = np.diff(np.concatenate(([0], good.view(np.int8), [0])))
    starts = np.nonzero(edges == 1)[0]
    ends = np.nonzero(edges == -1)[0]
    if not len(starts):
        raise SamSoundError("no sound table")
    csum = np.concatenate(([0], np.cumsum(hit)))
    score = csum[ends] - csum[starts]
    k = int(np.argmax(score))
    if score[k] < 16:
        raise SamSoundError("no sound table")
    s, e = int(starts[k]), int(ends[k])
    while s < e and a[s] == 0:
        s += 1
    while e > s and a[e - 1] == 0:
        e -= 1
    return s * 4, e - s


def _walk(data, rec, engine):
    """Sample pointers a script plays, or None if it doesn't parse."""
    args, play = ENGINES[engine]
    p = rec + 7
    out = []
    for _ in range(_MAX_SCRIPT_OPS):
        if p >= len(data):
            return None
        op = data[p]
        if op >= len(args):
            return None
        if op == play:
            out.append(struct.unpack_from("<I", data, p + 2)[0])
        p += 1 + args[op]
        if op == 0:
            return out
    return None


def _is_sample(data, off):
    if off + 8 > len(data) or data[off + 7] not in RATES:
        return False
    s = Sample(off, struct.unpack_from("<I", data, off)[0], data[off + 7])
    return s.count > 0 and s.data_offset + s.data_size <= len(data)


def read_bank(data):
    """The :class:`SoundBank` of a SAM image (bytes)."""
    table, count = _find_table(data)
    ptrs = struct.unpack_from(f"<{count}I", data, table)
    recs = {}
    for i, p in enumerate(ptrs):
        if p:
            o = file_offset(p)
            if o < len(data) and data[o] == SCRIPT_MAGIC:
                recs.setdefault(o, []).append(i)
    # The engine is the one that parses every script AND finds samples
    # there: an older file's PLAY can read as a newer engine's 4-byte op
    # followed by END, which parses but plays nothing.  Engines that tie
    # (a v17 file reads the same as v18) go to the smaller opcode set.
    best = None
    for name, (args, _play) in ENGINES.items():
        walked = {r: _walk(data, r, name) for r in recs}
        good = sum(1 for v in walked.values() if v is not None)
        found = sum(1 for v in walked.values() if v
                    for p in v if _is_sample(data, file_offset(p)))
        key = (good, found, -len(args))
        if best is None or key > best[0]:
            best = (key, name, walked)
    (good, _found, _n), engine, walked = best
    if good < len(recs):
        raise SamSoundError(
            f"{len(recs) - good} of {len(recs)} sound scripts don't parse")
    played = {}
    for rec, ptrs_ in walked.items():
        for p in ptrs_:
            played.setdefault(file_offset(p), set()).update(recs[rec])
    samples = []
    for off in sorted(played):
        if off + 8 > len(data):
            raise SamSoundError(f"sample at {off:#x} is past the end")
        cnt = struct.unpack_from("<I", data, off)[0]
        kind = data[off + 7]
        if kind not in RATES:
            raise SamSoundError(f"sample at {off:#x} has unknown kind {kind}")
        s = Sample(off, cnt, kind)
        if s.data_offset + s.data_size > len(data):
            raise SamSoundError(f"sample at {off:#x} runs past the end")
        samples.append(s)
    for a, b in zip(samples, samples[1:]):
        if a.data_offset + a.data_size > b.offset:
            raise SamSoundError(f"samples at {a.offset:#x} and "
                                f"{b.offset:#x} overlap")
    return SoundBank(engine, table, count, samples,
                     {k: sorted(v) for k, v in played.items()})


# ---------------------------------------------------------------------------
# Songs stored in pieces (PAD-587)
# ---------------------------------------------------------------------------
# The band titles (AC/DC, Metallica) don't store a song as one sample: it is
# a run of a few hundred bar-length samples (1-2.5 s) that ONE script PLAYs
# back to back, so the game can change section on a bar line.  A song has
# several such scripts -- the whole song, a later start point, one with an
# intro lead-in -- that share pieces; the longest stands for the song.
# Other titles' music is whole samples, and their longest script plays a
# handful, so the threshold finds nothing there.

#: a script that plays at least this many samples is a song in pieces
SONG_MIN_PIECES = 20


@dataclass(frozen=True)
class Song:
    sound: int           # sound-table index of the script that plays it
    pieces: tuple        # indices into bank.samples, in play order

    def frames(self, bank):
        return sum(bank.samples[k].count for k in self.pieces)

    def seconds(self, bank):
        return sum(bank.samples[k].seconds for k in self.pieces)


def songs(data, bank, min_pieces=SONG_MIN_PIECES):
    """The :class:`Song` s of *bank* (in file order of their pieces): every
    group of scripts that PLAY *min_pieces* or more samples and share any of
    them, represented by the group's longest script.  Empty on a title whose
    music is whole samples."""
    idx_of = {s.offset: i for i, s in enumerate(bank.samples)}
    ptrs = struct.unpack_from(f"<{bank.entries}I", data, bank.table)
    seqs = {}                                    # record -> (sound, pieces)
    for sound, p in enumerate(ptrs):
        if not p:
            continue
        rec = file_offset(p)
        if rec in seqs or rec >= len(data) or data[rec] != SCRIPT_MAGIC:
            continue
        played = _walk(data, rec, bank.engine) or []
        pieces = tuple(idx_of[o] for o in map(file_offset, played)
                       if o in idx_of)
        seqs[rec] = (sound, pieces)
    groups = []                                  # [set of pieces, best]
    for sound, pieces in seqs.values():
        if len(pieces) < min_pieces:
            continue
        if len({bank.samples[k].rate for k in pieces}) != 1:
            continue
        mine = set(pieces)
        best = (sound, pieces)
        for g in [g for g in groups if g[0] & mine]:
            groups.remove(g)
            mine |= g[0]
            if (len(g[1][1]), -g[1][0]) > (len(best[1]), -best[0]):
                best = g[1]
        groups.append([mine, best])
    groups.sort(key=lambda g: min(g[0]))
    return [Song(sound, pieces) for _set, (sound, pieces) in groups]


def decode_adpcm(raw, count):
    """``count`` 16-bit samples from IMA ADPCM *raw* -- bit-exact with the
    game's own decoder."""
    out = array.array("h", bytes(2 * count))
    pred = 0
    s = 0
    D, N = _DIFF, _NEXT
    i = 0
    for b in raw:
        if i >= count:
            break
        k = s + (b & 15)
        pred += D[k]
        if pred > 32767:
            pred = 32767
        elif pred < -32768:
            pred = -32768
        s = N[k]
        out[i] = pred
        i += 1
        if i >= count:
            break
        k = s + (b >> 4)
        pred += D[k]
        if pred > 32767:
            pred = 32767
        elif pred < -32768:
            pred = -32768
        s = N[k]
        out[i] = pred
        i += 1
    return out


def encode_adpcm(pcm):
    """IMA ADPCM of the 16-bit samples *pcm* for the game's decoder."""
    out = bytearray((len(pcm) + 1) // 2)
    pred = 0
    si = 0
    D, N, ST = _DIFF, _NEXT, _STEPS
    for i, x in enumerate(pcm):
        step = ST[si]
        diff = x - pred
        nib = 0
        if diff < 0:
            nib = 8
            diff = -diff
        if diff >= step:
            nib |= 4
            diff -= step
        if diff >= step >> 1:
            nib |= 2
            diff -= step >> 1
        if diff >= step >> 2:
            nib |= 1
        k = si * 16 + nib
        pred += D[k]
        if pred > 32767:
            pred = 32767
        elif pred < -32768:
            pred = -32768
        si = N[k] >> 4
        if i & 1:
            out[i >> 1] |= nib << 4
        else:
            out[i >> 1] = nib
    return bytes(out)


def decode(data, sample):
    """The 16-bit mono PCM of *sample* (at ``sample.rate``)."""
    raw = data[sample.data_offset:sample.data_offset + sample.data_size]
    if sample.kind == 0:
        return array.array("h", raw)
    return decode_adpcm(raw, sample.count)


def section_table(data):
    """``[(entry offset, start, end, stored sum)]`` of the image's section
    checksum table, or [] when it has none.  Its first section is always
    the code, ``0 .. table - 1``."""
    n = min(len(data), 0x200000) // 4
    a = np.frombuffer(data, "<u4", count=n)
    cand = np.nonzero((a[:-1] == 0)
                      & (a[1:] == (np.arange(n - 1, dtype=np.int64) * 4 - 1)
                         .astype(np.uint32)))[0]
    for i in cand:
        base = int(i) * 4
        if base == 0:
            continue
        out = []
        for k in range(64):
            s, e, c = struct.unpack_from("<3I", data, base + 12 * k)
            if (s | e | c) == 0:
                break
            S, E = file_offset(s), file_offset(e)
            if S > E or E >= len(data):
                out = []
                break
            out.append((base + 12 * k, S, E, c))
        if out:
            return out
    return []


def has_trailer(data):
    """True when the file ends in ``~bytesum`` of everything before."""
    if len(data) < 8:
        return False
    n = len(data) - 4
    return struct.unpack_from("<I", data, n)[0] == (~_byte_sum(data, n)) & M32


def replace(image, sample, pcm):
    """Write *pcm* (16-bit mono at ``sample.rate``; cut or zero-padded to
    the slot's length) over *sample* in *image* (a bytearray), and return
    the byte-sum change.  Checksums are :func:`fix_checksums`' job."""
    pcm = list(pcm[:sample.count])
    pcm += [0] * (sample.count - len(pcm))
    lo = sample.data_offset
    hi = lo + sample.data_size
    old = bytes(image[lo:hi])
    if sample.kind == 0:
        new = array.array("h", pcm).tobytes()
    else:
        new = encode_adpcm(pcm)
        if sample.count & 1:
            # the last byte's top nibble isn't part of the sample
            new = new[:-1] + bytes([(new[-1] & 0x0F) | (old[-1] & 0xF0)])
    image[lo:hi] = new
    return sum(new) - sum(old)


def _byte_sum(data, end):
    return int(np.frombuffer(data, np.uint8, count=end).sum(dtype=np.uint64))


def fix_checksums(image, changes, trailer):
    """Move the section sums covering *changes* (``[(start, end, byte-sum
    delta)]``, end exclusive) by exactly what changed, then, when
    *trailer*, set the file's own sum -- from the final bytes, since the
    section table it covers has just changed too."""
    secs = section_table(image)
    for lo, hi, delta in changes:
        for at, S, E, _c in secs:
            if S <= lo <= E:
                if hi - 1 > E:
                    raise SamSoundError(
                        f"change at {lo:#x} crosses a checksum section")
                c = struct.unpack_from("<I", image, at + 8)[0]
                struct.pack_into("<I", image, at + 8, (c - delta) & M32)
                break
    if trailer:
        n = len(image) - 4
        struct.pack_into("<I", image, n, (~_byte_sum(image, n)) & M32)
