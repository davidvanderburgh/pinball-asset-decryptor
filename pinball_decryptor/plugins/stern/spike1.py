"""Stern Spike 1 audio engine — plaintext master directory, raw-PCM bodies.

Spike 1 (2015-2016: WrestleMania, KISS, Whoa Nellie, Game of Thrones,
Spider-Man VE, Ghostbusters) is the DMD generation before Spike 2.  Its card
keeps the game's assets in ``<TITLE>/image.bin`` on an ext2 **logical**
partition, and — unlike Spike 2, whose master directory is consumed through
the firmware's keystream codec — everything here is plaintext:

* A 48-byte header block (``header2``) sits at the offset named by the u64 at
  file offset 0, or at a fixed flash page (0x120000 / 0x120038) on older
  builds whose front page ships erased (0xFF).  Layout::

      u64[0]=0   u64[1]=h2_off-1   u64[2]=build id   u64[3]=table offset
      u64[4]=file size - 5         u64[5]=checksum

* The pointer table is a run of ascending u64 file offsets, five consecutive
  slots per master record (handles 5i..5i+4 share record i).

* Each master record is a small tag stream: a 12-byte ``05`` header whose u32
  at +3 is the sound's duration in 1/7350 s ticks, then a body pointer inline
  at +12 and/or one per ``0a 00`` tag (multi-pointer records are layered
  music — each pointer is an independently playable track).

* A body is ``u32 frames, u16 channels, u16 divisor`` followed by
  ``2*channels*frames`` bytes of interleaved little-endian 16-bit PCM at
  ``44100/divisor`` Hz.  No compression, no cipher.

The model was verified byte-complete on all four available titles: the bodies
referenced this way tile 100.0% of the region between the index and the
master directory on WrestleMania LE 1.35, KISS LE 1.41, GOT LE 1.37 and
Ghostbusters LE 1.17 (a combined ~8.7 hours of audio), with every record's
tick length matching its primary body.

Extract writes one WAV per body — ``audio/idxNNNN.wav`` for a record's first
track, ``audio/idxNNNN-t2.wav`` (…-t3, …) for the extra layers.  Write is the
Spike 2 philosophy on easier terrain: fit the replacement to the slot's exact
frame count, loudness-match it to the original body (soft-limited, never hard
clipped), patch the PCM in place through the ext file→disk map, and refresh
the card's ``/spk/index/*.sidx`` record — the Spike 1 manifests use the same
FINF records and the same global HMAC key as Spike 2 (verified against the
stored digests on all four cards).
"""

import bisect
import os
import re
import struct
import tempfile
import wave

from ...core import checksums, staged_changes
from ...core.longpath import ext as _lp
from . import sidx as sidx_mod
from .ext4 import Ext4Reader

AVAILABLE = True

_TICK_HZ = 7350           # record length field unit: 1/7350 s (44100/6)
_BASE_RATE = 44100
_HDR_CANDIDATES = (0x120000, 0x120038)   # erased-front-page builds (WWE 1.35)

# Extracted WAV stem: "idx0021" (track 1) / "idx0021-t2" (track 2), possibly
# wrapped by a duration prefix and/or an Auto-transcribe rename — search, not
# match, exactly like the Spike 2 engine's idx token.
_IDX_RE = re.compile(r"\bidx0*(\d+)(?:-t(\d+))?", re.IGNORECASE)


class Spike1Error(Exception):
    pass


class Spike1Cancelled(Spike1Error):
    """The user cancelled — distinct from a real failure so pipelines can
    route it to the normal cancel path instead of an error dialog."""


# Master-directory tail sanity cap: the largest real Spike 1 master directory
# (WWE 1.35, 3810 records) is ~150 KB of table + ~250 KB of records.  A first
# table entry pointing anywhere that would make the "tail" bigger than this is
# a corrupt index, and materializing it would read GBs into RAM.
_MAX_MASTER_BYTES = 64 << 20
# A master record is at most a few hundred bytes (biggest observed: 96 + the
# multi-track WWE records at ~180); cap the slice so a corrupt bound can't
# materialize the rest of the file as one record.
_MAX_RECORD_BYTES = 0x10000


# --------------------------------------------------------------------------
# container parsing
# --------------------------------------------------------------------------
# All parsing goes through plain slicing (``m[a:b]``), never
# ``struct.unpack_from(m, off)`` — so the same code runs against an mmap of an
# extracted image.bin (Extract) AND against a lazily-read window view of the
# image still inside a card (Write), which only materializes the small index
# head and master-directory tail.

def _u64(m, off):
    return struct.unpack("<Q", m[off:off + 8])[0]


def _header2_ok(m, off, size):
    blk = m[off:off + 48]
    if len(blk) < 48:
        return False
    h2 = struct.unpack("<6Q", blk)
    return (h2[0] == 0 and h2[1] == off - 1
            and size - 64 <= h2[4] < size and off < h2[3] < size)


def find_header2(m, size=None):
    """Offset of the header2 block, or raise :class:`Spike1Error`."""
    size = len(m) if size is None else size
    if size < 0x200:
        raise Spike1Error("image.bin too small")
    h0 = _u64(m, 0)
    if h0 != 0xFFFFFFFFFFFFFFFF and 0 < h0 < 0x200000 \
            and _header2_ok(m, h0, size):
        return h0
    for cand in _HDR_CANDIDATES:
        if cand + 48 <= size and _header2_ok(m, cand, size):
            return cand
    raise Spike1Error("no Spike 1 header block found in image.bin")


def _body_header(m, off, hi):
    """``(frames, channels, divisor)`` if *off* holds a sane body header."""
    hdr = m[off:off + 8]
    if len(hdr) < 8 or off + 8 > hi:
        return None
    frames, ch, div = struct.unpack("<IHH", hdr)
    if frames > 0 and 1 <= ch <= 2 and div in (1, 2, 4) \
            and off + 8 + 2 * ch * frames <= hi:
        return frames, ch, div
    return None


def parse_master(m, size=None):
    """Parse the master directory of a Spike 1 ``image.bin``.

    Returns ``{"h2_off", "table_off", "md_start", "records"}`` where records
    is ``[{"idx", "off", "ticks", "tracks": [(body_off, frames, ch, div),…]}]``
    for every record that references at least one audio body (control records
    — the handful of tiny mask/dummy entries at the front of the directory —
    carry no body and are omitted).
    """
    size = len(m) if size is None else size
    h2_off = find_header2(m, size)
    table_off = _u64(m, h2_off + 0x18)

    # The table is a strictly-ascending run of u64 offsets into the master-
    # directory tail; it ends where the next structure's values break the
    # ascent.  Read it in one slice — it is at most a few hundred KB.
    first = _u64(m, table_off)
    # Every master record lives AFTER the index header (on real cards, in the
    # file's tail); a first entry at/below the header — notably 0 from a
    # zeroed table — would otherwise pass the ascent filter forever and make
    # the "records" span the whole multi-GB file.
    if not (table_off < first < size) or size - first > _MAX_MASTER_BYTES:
        raise Spike1Error("corrupt master pointer table "
                          "(first record at 0x%x)" % first)
    ptrs = []
    prev = 0
    pos = table_off
    while pos < size:
        chunk = m[pos:min(pos + 0x80000, size)]
        stopped = False
        for i in range(0, len(chunk) - 7, 8):
            v = struct.unpack_from("<Q", chunk, i)[0]
            if v < prev or v < first or v >= size or v % 8:
                stopped = True
                break
            ptrs.append(v)
            prev = v
        if stopped or len(chunk) < 0x80000:
            break
        pos += len(chunk) - (len(chunk) % 8)
    if not ptrs:
        raise Spike1Error("empty master pointer table")
    uniq = sorted(set(ptrs))
    md_start = uniq[0]
    bounds = uniq + [size]

    records = []
    for k, off in enumerate(uniq):
        rec = m[off:min(bounds[k + 1], off + _MAX_RECORD_BYTES)]
        if len(rec) < 7 or rec[0] != 0x05:
            continue
        ticks = struct.unpack_from("<I", rec, 3)[0]
        tracks = []
        # primary pointer inline at +12
        if len(rec) >= 20:
            v = struct.unpack_from("<Q", rec, 12)[0]
            if v % 8 == 0 and h2_off <= v < md_start:
                b = _body_header(m, v, md_start)
                if b:
                    tracks.append((v,) + b)
        # additional tracks behind `0a 00` tags
        j = 12
        while True:
            j = rec.find(b"\x0a\x00", j)
            if j < 0 or j + 10 > len(rec):
                break
            v = struct.unpack_from("<Q", rec, j + 2)[0]
            if v % 8 == 0 and h2_off <= v < md_start:
                b = _body_header(m, v, md_start)
                if b and (v,) + b not in tracks:
                    tracks.append((v,) + b)
            j += 2
        if tracks:
            records.append({"idx": k, "off": off, "ticks": ticks,
                            "tracks": tracks})
    return {"h2_off": h2_off, "table_off": table_off,
            "md_start": md_start, "records": records}


# --------------------------------------------------------------------------
# card access
# --------------------------------------------------------------------------

class _FileMap:
    """One file inside an ext partition, with O(log n) offset lookup.

    ``Ext4Reader.disk_ranges`` rebuilds the whole block map on every call —
    fine for one big mapping, quadratic for the thousands of small reads the
    master-directory parse does.  This builds the (merged) run list once.
    """

    def __init__(self, reader, node):
        self.reader = reader
        self.size = node["size"]
        bs = reader.block_size
        merged = []
        for log, phys, cnt in reader._runs(node):
            if merged and merged[-1][0] + merged[-1][2] == log \
                    and merged[-1][1] + merged[-1][2] == phys:
                merged[-1][2] += cnt
            else:
                merged.append([log, phys, cnt])
        self._runs = [(r[0] * bs, r[1] * bs, r[2] * bs) for r in merged]
        self._starts = [r[0] for r in self._runs]

    def ranges(self, off, length):
        """Absolute disk byte ranges ``[(disk_off, n), ...]`` backing
        ``[off, off+length)``."""
        out = []
        end = min(off + length, self.size)
        pos = off
        while pos < end:
            i = bisect.bisect_right(self._starts, pos) - 1
            if i < 0 or pos >= self._runs[i][0] + self._runs[i][2]:
                raise Spike1Error("offset 0x%x not allocated" % pos)
            lo, po, ln = self._runs[i]
            take = min(lo + ln - pos, end - pos)
            out.append((self.reader.base + po + (pos - lo), take))
            pos += take
        return out

    def read(self, f, off, length):
        out = bytearray()
        for disk, n in self.ranges(off, length):
            f.seek(disk)
            out += f.read(n)
        return bytes(out)


class _CardWindow:
    """Bytes-like view of an image.bin still inside a card.

    Serves the index head and master-directory tail from two eagerly-read
    buffers; anything in between (the body region — only ever probed for
    8-byte body headers) is read through the file map on demand.
    """

    def __init__(self, disk, fmap):
        self.disk = disk
        self.fmap = fmap
        self.size = fmap.size
        head_len = min(0x200000, self.size)
        self._head = fmap.read(disk, 0, head_len)
        # Find the header through the *window*, not the raw head bytes — a
        # header block or table straddling the head boundary is then served
        # by fall-through disk reads.  The tail sentinel makes every
        # past-the-head slice fall through until the real tail is read.
        self._tail_start = self.size
        self._tail = b""
        h2_off = find_header2(self, self.size)
        table_off = _u64(self, h2_off + 0x18)
        first = _u64(self, table_off)
        if not (table_off < first < self.size) \
                or self.size - first > _MAX_MASTER_BYTES:
            raise Spike1Error("corrupt master pointer table "
                              "(first record at 0x%x)" % first)
        self._tail_start = first
        self._tail = fmap.read(disk, first, self.size - first)

    def __len__(self):
        return self.size

    def __getitem__(self, sl):
        if isinstance(sl, int):
            return self[sl:sl + 1][0]
        start = sl.start or 0
        stop = self.size if sl.stop is None else min(sl.stop, self.size)
        if stop <= start:
            return b""
        if stop <= len(self._head):
            return self._head[start:stop]
        if start >= self._tail_start:
            ts = self._tail_start
            return self._tail[start - ts:stop - ts]
        return self.fmap.read(self.disk, start, stop - start)


def locate_assets(f, partitions):
    """Find the game-data directory across *partitions*.

    Returns ``(reader, game_dir, image_node, sidx_path, sidx_node)`` for the
    partition holding the largest ``<dir>/image.bin`` (the rootfs also carries
    a small ``spike_menu/image.bin``, which this skips by size).  *partitions*
    is ``[(byte_offset, byte_size), ...]``.
    """
    best = None
    for off, psize in partitions:
        try:
            reader = Ext4Reader(f, off, psize)
        except Exception:
            continue
        for path, _ino, node in reader.iter_regular_files(max_depth=3,
                                                          min_size=1):
            if path.endswith("/image.bin"):
                if best is None or node["size"] > best[2]["size"]:
                    best = (reader, path.rsplit("/", 2)[-2], node)
    if best is None:
        raise Spike1Error(
            "no <game>/image.bin found on any ext partition — "
            "not a Spike 1 game card?")
    reader, game_dir, node = best
    sidx_path, sidx_node = sidx_mod.find_sidx(reader)
    return reader, game_dir, node, sidx_path, sidx_node


# --------------------------------------------------------------------------
# WAV naming / parsing
# --------------------------------------------------------------------------

def wav_name(idx, track, frames=0, rate=_BASE_RATE, duration_names=False):
    stem = "idx%04d" % idx
    if track > 0:
        stem += "-t%d" % (track + 1)
    if duration_names and rate:
        total_ms = int(round(frames * 1000.0 / rate))
        m, rem = divmod(total_ms, 60000)
        s, ms = divmod(rem, 1000)
        stem = "%02dm%02ds%03d - %s" % (m, s, ms, stem)
    return stem + ".wav"


def parse_wav_stem(stem):
    """``(idx, track)`` from an extracted-WAV stem, or ``None``.

    Track is 0-based (``idx0021`` -> track 0, ``idx0021-t2`` -> track 1).
    Tolerates the duration prefix and Auto-transcribe / Music-ID renames the
    same way the Spike 2 engine does — the idx token can sit anywhere.
    """
    match = _IDX_RE.search(stem)
    if not match:
        return None
    idx = int(match.group(1))
    if match.group(2):
        track_no = int(match.group(2))
        # wav_name only ever emits -t2, -t3, …; a hand-typed -t0/-t1 has no
        # defined slot (t1 would collide with the bare name, t0 would index
        # the record's LAST track via -1), so refuse rather than guess.
        if track_no < 2:
            return None
        return idx, track_no - 1
    return idx, 0


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------

def _write_wav_from(m, path, body_off, frames, ch, div, chunk=1 << 20):
    rate = _BASE_RATE // div
    total = 2 * ch * frames
    with wave.open(_lp(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        pos = body_off + 8
        left = total
        while left > 0:
            n = min(chunk, left)
            w.writeframes(m[pos:pos + n])
            pos += n
            left -= n


def _find_game_elf_node(reader, game_dir):
    """The inode of the game firmware ELF in ``<game_dir>/game``, or None."""
    want = "/" + game_dir + "/game"
    for path, _ino, node in reader.iter_regular_files(max_depth=3,
                                                      min_size=0x10000):
        if path.endswith(want) and reader.is_arm_elf(node):
            return node
    for path, _ino, node in reader.iter_regular_files(max_depth=4,
                                                      min_size=0x10000):
        if path.rsplit("/", 1)[-1] == "game" and reader.is_arm_elf(node):
            return node
    return None


def read_game_elf(image_path, partitions, open_disk=None):
    """The game ELF bytes from a Spike 1 card (for the operator-adjustment
    decoder — see :mod:`.spike1_adjustments`).

    The firmware ELF sits in the same ``<game>/`` directory as ``image.bin``
    (the audio blob), alongside a small top-level ``game`` symlink — so we
    take the ARM-ELF regular file in that directory.  *partitions* is the
    located ``[(byte_offset, byte_size), ...]`` list.
    """
    f = open_disk() if open_disk else open(_lp(image_path), "rb")
    try:
        reader, game_dir, _img, _sp, _sn = locate_assets(f, partitions)
        node = _find_game_elf_node(reader, game_dir)
        if node is None:
            raise Spike1Error("no game ELF found next to %s/image.bin"
                              % game_dir)
        return reader.read_file_bytes(node)
    finally:
        if open_disk is None:
            f.close()


def _refresh_sidx_record(disk, reader, fmap, key, sidx_path, sidx_node, log,
                         progress=None, total=0, check=None):
    """Recompute *key*'s digests in the card's ``.sidx`` from *fmap*'s live
    (patched) bytes.  A generalisation of :func:`_refresh_sidx`, which is the
    ``image.bin`` special case; this one refreshes any indexed file (the game
    ELF, for the settings-default patch)."""
    import hashlib
    import hmac as hmac_mod

    check = check or (lambda: False)
    recs, _crc, fmt = sidx_mod.parse_records(reader.read_file_bytes(sidx_node))
    if not recs or key not in recs:
        log("  ! %s carries no record for %s — sidx left untouched"
            % (os.path.basename(sidx_path or "sidx"), key))
        return False
    h = hmac_mod.new(sidx_mod.SIDX_KEY, digestmod=hashlib.sha1)
    md5 = hashlib.md5()
    pos = 0
    while pos < fmap.size:
        if check():
            raise Spike1Cancelled("cancelled")
        n = min(1 << 23, fmap.size - pos)
        buf = fmap.read(disk, pos, n)
        h.update(buf)
        md5.update(buf)
        pos += n
    field_writes = sidx_mod.record_field_writes(
        recs[key], h.digest(), md5.digest(), fmt)
    smap = _FileMap(reader, sidx_node)
    for rel_off, payload in field_writes:
        for disk_off, n in smap.ranges(rel_off, len(payload)):
            disk.seek(disk_off)
            disk.write(payload[:n])
            payload = payload[n:]
    disk.flush()
    log("Refreshed %s record in %s" % (key, sidx_path))
    return True


def write_game_elf_defaults(card_path, overrides_by_id, log=None, cancel=None):
    """Patch operator-adjustment DEFAULTS into a Spike 1 card's game ELF,
    in place, and refresh the ELF's ``.sidx`` record.

    *overrides_by_id* is ``{adjustment_id: value}`` — each value is clamped to
    the adjustment's own min/max.  Mirrors the Spike 2
    :meth:`explorer.CardImage.write_adjustment_defaults` contract (patch the
    firmware's compiled defaults in place, then refresh the card's validation
    manifest), so the same Build hook can apply staged settings on either era.
    Returns the number of defaults applied.
    """
    from .formats import spike1_linux_partitions
    from .spike1_adjustments import Spike1Adjustments

    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    parts = spike1_linux_partitions(card_path)
    if not parts:
        raise Spike1Error("no ext partitions found in the card image")

    with open(_lp(card_path), "r+b") as disk:
        reader, game_dir, _img, sidx_path, sidx_node = \
            locate_assets(disk, parts)
        node = _find_game_elf_node(reader, game_dir)
        if node is None:
            raise Spike1Error("no game ELF found on the card")
        emap = _FileMap(reader, node)
        elf_bytes = emap.read(disk, 0, emap.size)
        adj = Spike1Adjustments(elf_bytes)

        clean = {}
        for idx, val in overrides_by_id.items():
            e = adj.entry(int(idx))
            clean[int(idx)] = max(e["min"], min(e["max"], int(val)))
        if not clean:
            return 0

        # write only the changed 4-byte default fields at their file offsets
        for idx, val in clean.items():
            payload = struct.pack("<i", val)
            file_off = adj.default_file_offset(idx)
            for disk_off, n in emap.ranges(file_off, 4):
                disk.seek(disk_off)
                disk.write(payload[:n])
                payload = payload[n:]
            log("  adjustment 0x%02X default <- %d" % (idx, val))
        disk.flush()

        if sidx_node is not None:
            _refresh_sidx_record(disk, reader, emap, "%s/game" % game_dir,
                                 sidx_path, sidx_node, log, check=check)
        else:
            log("  ! no /spk/index/*.sidx manifest found — the card's own "
                "validation may reject the modified firmware")
    return len(clean)


def extract_all(image_path, partitions, output_dir, log=None, progress=None,
                cancel=None, phase=None, open_disk=None, duration_names=False):
    """Decode every Spike 1 sound to ``audio/idxNNNN[-tK].wav``.

    Mirrors the Spike 2 engine's contract: *partitions* is the
    ``[(byte_offset, byte_size), ...]`` list the pipeline located, *open_disk*
    optionally supplies the disk file object (the Direct-SD hook), and *phase*
    is called with the pipeline's phase index when decoding starts.
    Returns ``{"sounds": n, "tracks": n, "seconds": float}``.
    """
    import mmap
    import shutil

    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)

    f = open_disk() if open_disk else open(_lp(image_path), "rb")
    tmp_dir = None
    try:
        reader, game_dir, image_node, _sp, _sn = locate_assets(f, partitions)
        log("Game folder: %s (image.bin %.1f MB)"
            % (game_dir, image_node["size"] / 1e6))

        # Stream image.bin out to a flat temp file first: the per-body reads
        # are random-access, and ext2's one-block runs make random access
        # through the reader quadratic.
        tmp_dir = tempfile.mkdtemp(prefix="spike1_")
        flat = os.path.join(tmp_dir, "image.bin")
        log("Reading image.bin out of the card image…")

        def _copy_progress(cur, tot):
            # extract_file has no cancel hook, so the cancel check rides the
            # per-chunk progress callback — otherwise Stop is dead for the
            # whole GB-scale read-out.
            if check():
                raise Spike1Cancelled("cancelled")
            if progress:
                progress(cur, tot * 2, "Reading image.bin")

        try:
            reader.extract_file(image_node, flat, progress=_copy_progress)
        except Spike1Cancelled:
            return {"sounds": 0, "tracks": 0, "seconds": 0.0}
        if check():
            return {"sounds": 0, "tracks": 0, "seconds": 0.0}

        with open(flat, "rb") as ff:
            m = mmap.mmap(ff.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                master = parse_master(m)
                records = master["records"]
                n_tracks = sum(len(r["tracks"]) for r in records)
                log("Master directory: %d sounds, %d tracks"
                    % (len(records), n_tracks))
                if phase:
                    phase(2)

                audio_dir = os.path.join(output_dir, "audio")
                os.makedirs(audio_dir, exist_ok=True)
                done = 0
                seconds = 0.0
                total_size = image_node["size"]
                for rec in records:
                    if check():
                        break
                    for t, (body_off, frames, ch, div) in \
                            enumerate(rec["tracks"]):
                        name = wav_name(rec["idx"], t, frames,
                                        _BASE_RATE // div, duration_names)
                        _write_wav_from(m, os.path.join(audio_dir, name),
                                        body_off, frames, ch, div)
                        seconds += frames / (_BASE_RATE / div)
                        done += 1
                        if progress:
                            progress(
                                total_size
                                + done * total_size // max(n_tracks, 1),
                                total_size * 2,
                                "Decoding audio (%d/%d)" % (done, n_tracks))
                log("Decoded %d WAVs (%.1f minutes of audio)"
                    % (done, seconds / 60.0))
                return {"sounds": len(records), "tracks": done,
                        "seconds": seconds}
            finally:
                m.close()
    finally:
        f.close()
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# write
# --------------------------------------------------------------------------

def _load_wav(path):
    """``(samples float32 [frames, ch], rate)`` from a PCM WAV."""
    import numpy as np
    try:
        with wave.open(_lp(path), "rb") as w:
            ch = w.getnchannels()
            width = w.getsampwidth()
            rate = w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError, struct.error, OSError) as e:
        # e.g. a 32-bit-float editor export ("unknown format: 3") — surface
        # as the engine's own error so the Write can skip just this file.
        raise Spike1Error("not a readable PCM WAV (%s): %s"
                          % (os.path.basename(path), e))
    if ch < 1 or rate <= 0:
        raise Spike1Error("bad WAV header in %s" % os.path.basename(path))
    if width == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    elif width == 1:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
             - 128.0) * 256.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        a = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
             | (b[:, 2].astype(np.int32) << 16))
        a = ((a << 8) >> 16).astype(np.float32)   # sign-extend, 16-bit range
    else:
        raise Spike1Error("unsupported WAV sample width %d in %s"
                          % (width, os.path.basename(path)))
    return a.reshape(-1, ch), rate


def _resample(a, src_rate, dst_rate):
    import numpy as np
    if src_rate == dst_rate or not len(a):
        return a
    n_out = max(1, int(round(len(a) * dst_rate / src_rate)))
    x = np.arange(n_out, dtype=np.float64) * (src_rate / dst_rate)
    i0 = np.minimum(x.astype(np.int64), len(a) - 1)
    i1 = np.minimum(i0 + 1, len(a) - 1)
    frac = (x - i0)[:, None].astype(np.float32)
    return a[i0] * (1.0 - frac) + a[i1] * frac


def _mix_channels(a, ch):
    import numpy as np
    if a.shape[1] == ch:
        return a
    if ch == 1:
        return a.mean(axis=1, keepdims=True)
    return np.repeat(a[:, :1], ch, axis=1)


def _fit_frames(a, frames):
    """Trim/pad to exactly *frames*, with a short edge fade at any cut."""
    import numpy as np
    fade = min(220, frames)      # 5 ms at 44.1 kHz
    if len(a) > frames:
        a = a[:frames].copy()
        if fade:
            a[-fade:] *= np.linspace(1.0, 0.0, fade,
                                     dtype=np.float32)[:, None]
    elif len(a) < frames:
        pad = np.zeros((frames - len(a), a.shape[1]), dtype=np.float32)
        a = np.concatenate([a, pad])
    return a


# Loudness-match tuning, mirroring the Spike 2 engine's semantics (see
# engine.py's _MATCH_* block): the same Advanced-audio-options environment
# levers steer both generations' builds.
_MATCH_MAX_GAIN = 20.0         # absolute bound — never amplify a whisper 20x+
_MATCH_MIN_ORIG_PEAK = 0.02    # orig quieter than 2% of range: not a reference
_MATCH_GAIN_DB_MAX = 12.0      # user offset clamp (build-wide + per-clip)


def _match_loudness_enabled():
    """`PAD_STERN_MATCH_LOUDNESS=0` (Advanced audio options) turns the RMS
    match off — same lever as the Spike 2 build."""
    return os.environ.get("PAD_STERN_MATCH_LOUDNESS") != "0"


def _build_gain_db():
    """Build-wide loudness offset (`PAD_STERN_MATCH_GAIN_DB`), clamped."""
    try:
        ov = float(os.environ.get("PAD_STERN_MATCH_GAIN_DB", ""))
    except ValueError:
        return 0.0
    return max(min(ov, _MATCH_GAIN_DB_MAX), -_MATCH_GAIN_DB_MAX)


def _match_level(rep, orig, extra_db=0.0, match=True):
    """Gain *rep* to *orig*'s RMS (+ *extra_db*), soft-limiting the peaks
    instead of hard-clipping or backing the whole gain off.

    ``match=False`` (the Advanced-options "loudness match off" lever) applies
    only the dB offset.  A near-silent original is no reference — the
    replacement keeps its own level rather than being crushed to silence or
    amplified into its noise floor (mirrors the Spike 2 engine).
    """
    import numpy as np
    limit = 32767.0
    gain = 1.0
    if match:
        r_rms = float(np.sqrt(np.mean(np.square(rep)))) if len(rep) else 0.0
        o_peak = float(np.max(np.abs(orig))) if len(orig) else 0.0
        o_rms = float(np.sqrt(np.mean(np.square(orig)))) if len(orig) else 0.0
        if r_rms > 1.0 and o_rms > 0.0 \
                and o_peak >= _MATCH_MIN_ORIG_PEAK * limit:
            gain = min(o_rms / r_rms, _MATCH_MAX_GAIN)
    gain *= 10.0 ** (extra_db / 20.0)
    out = rep * gain
    knee = 0.89 * limit
    mag = np.abs(out)
    over = mag > knee
    if over.any():
        soft = knee + (limit - knee) * np.tanh((mag[over] - knee)
                                               / (limit - knee))
        out[over] = np.sign(out[over]) * soft
    return np.clip(out, -limit, limit)


def _select_changed_wavs(assets_dir, log):
    """``{(idx, track): abs_path}`` for every audio WAV changed vs baseline.

    Same rules as the Spike 2 engine: a WAV counts when its md5 differs from
    the ``.checksums.md5`` baseline; a WAV missing from the baseline (renamed
    or hand-added after extract) is treated as changed.
    """
    baseline = checksums.read_checksums(assets_dir)
    out = {}
    audio_dir = os.path.join(assets_dir, "audio")
    if not os.path.isdir(audio_dir):
        return out
    for fn in sorted(os.listdir(audio_dir)):
        if not fn.lower().endswith(".wav") or ".stage." in fn:
            continue
        parsed = parse_wav_stem(os.path.splitext(fn)[0])
        if parsed is None:
            continue
        abs_path = os.path.join(audio_dir, fn)
        base_md5 = baseline.get("audio/" + fn)
        changed = (base_md5 is None
                   or checksums.md5_file(abs_path) != base_md5)
        if changed:
            if parsed in out:
                log("  note: %s and %s map to the same sound; using %s"
                    % (os.path.basename(out[parsed]), fn,
                       os.path.basename(out[parsed])))
            else:
                out[parsed] = abs_path
    return out


def _slot_gains(assets_dir):
    """``{(idx, track): dB}`` from the staged-changes per-clip level boxes."""
    data = staged_changes.load(assets_dir)
    out = {}
    for rel, db in (data.get("audio_levels") or {}).items():
        parsed = parse_wav_stem(os.path.splitext(os.path.basename(rel))[0])
        if parsed is None:
            continue
        try:
            out[parsed] = float(db)
        except (TypeError, ValueError):
            pass
    return out


def write_image(original_path, assets_dir, output_path, log=None,
                progress=None, cancel=None, phase=None):
    """Copy *original_path* to *output_path* and patch the changed sounds in.

    Returns ``{"audio": n_patched, "skipped": [names]}``.  Raises
    :class:`Spike1Cancelled` on cancel and :class:`Spike1Error` on a
    card/asset mismatch; either way the partial output file is removed —
    a multi-GB unpatched copy must not be left looking like a build.
    """
    log = log or (lambda *a, **k: None)

    changed = _select_changed_wavs(assets_dir, log)
    gains = _slot_gains(assets_dir)
    log("Changed sounds: %d" % len(changed))
    if not changed:
        log("  ! no changed audio WAVs vs the extract baseline — the build "
            "will be an unmodified copy of the original image", "warning")

    # Everything from the copy on owns the output file: on cancel or error
    # remove it, so no multi-GB partial/unpatched copy is left looking like
    # a finished build.  (Before the copy nothing has been written, so an
    # early failure must NOT delete a pre-existing build at that path.)
    try:
        return _write_image_inner(original_path, output_path, changed, gains,
                                  log, progress, cancel, phase)
    except BaseException:
        try:
            os.remove(_lp(output_path))
        except OSError:
            pass
        raise


def _write_image_inner(original_path, output_path, changed, gains, log,
                       progress, cancel, phase):
    import numpy as np
    from .formats import spike1_linux_partitions

    check = cancel or (lambda: False)

    build_db = _build_gain_db()
    match_on = _match_loudness_enabled()
    if build_db:
        log("Build-wide loudness offset: %+.1f dB" % build_db)
    if not match_on:
        log("Loudness match: off (Advanced audio options)")
    preview_dir = os.environ.get("PAD_STERN_PREVIEW_DIR")

    # ---- copy original -> output --------------------------------------
    total = os.path.getsize(_lp(original_path))
    with open(_lp(original_path), "rb") as src, \
            open(_lp(output_path), "wb") as dst:
        copied = 0
        while True:
            if check():
                raise Spike1Cancelled("cancelled")
            buf = src.read(1 << 23)
            if not buf:
                break
            dst.write(buf)
            copied += len(buf)
            if progress:
                progress(copied, total * 2, "Copying card image")

    parts = spike1_linux_partitions(output_path)
    if not parts:
        raise Spike1Error("no ext partitions found in the card image")

    with open(_lp(output_path), "r+b") as disk:
        reader, game_dir, image_node, sidx_path, sidx_node = \
            locate_assets(disk, parts)
        imap = _FileMap(reader, image_node)
        master = parse_master(_CardWindow(disk, imap), imap.size)
        records = {r["idx"]: r for r in master["records"]}
        if phase:
            phase(2)

        # ---- encode + collect patches ---------------------------------
        writes = []          # [(disk_offset, bytes)]
        body_seen = {}       # body_off -> idx that patched it
        patched = 0
        skipped = []
        items = sorted(changed.items())
        for n, ((idx, track), wav_path) in enumerate(items):
            if check():
                raise Spike1Cancelled("cancelled")
            name = os.path.basename(wav_path)
            rec = records.get(idx)
            if rec is None or track >= len(rec["tracks"]):
                skipped.append(name)
                log("  ! %s: no such sound on this card — skipped" % name)
                continue
            body_off, frames, ch, div = rec["tracks"][track]
            rate = _BASE_RATE // div
            if body_off in body_seen:
                log("  ! %s shares its audio body with idx%04d, which was "
                    "already patched — skipped" % (name, body_seen[body_off]))
                skipped.append(name)
                continue

            try:
                rep, rep_rate = _load_wav(wav_path)
                rep = _mix_channels(_resample(rep, rep_rate, rate), ch)
                rep = _fit_frames(rep, frames)

                orig_raw = imap.read(disk, body_off + 8, 2 * ch * frames)
                orig = np.frombuffer(orig_raw, dtype="<i2") \
                    .astype(np.float32).reshape(-1, ch)
                if match_on and not orig.any():
                    log("  note: %s replaces a silent slot — the original "
                        "gives no level reference, keeping the replacement's "
                        "own level" % name)
                total_db = max(min(build_db + gains.get((idx, track), 0.0),
                                   _MATCH_GAIN_DB_MAX), -_MATCH_GAIN_DB_MAX)
                rep = _match_level(rep, orig, total_db, match=match_on)
            except Spike1Cancelled:
                raise
            except Exception as e:
                # One unreadable replacement must not abort the other
                # patches: skip it, keep its slot stock.
                skipped.append(name)
                log("  ! %s could not be encoded (%s) — skipped, the slot "
                    "keeps its original sound" % (name, e), "warning")
                continue

            body = np.rint(rep).astype("<i2").tobytes()
            _write_preview(preview_dir, idx, track, body, ch, rate, log)
            for disk_off, nbytes in imap.ranges(body_off + 8, len(body)):
                writes.append((disk_off, body[:nbytes]))
                body = body[nbytes:]
            body_seen[body_off] = idx
            patched += 1
            log("  idx%04d%s <- %s (%d frames, %dch, %d Hz)"
                % (idx, "-t%d" % (track + 1) if track else "",
                   name, frames, ch, rate))
            if progress:
                progress(total + (n + 1) * total // (2 * max(len(items), 1)),
                         total * 2, "Encoding audio")

        if phase:
            phase(3)

        # ---- apply ----------------------------------------------------
        for disk_off, buf in writes:
            disk.seek(disk_off)
            disk.write(buf)
        disk.flush()

        # ---- refresh the card's own validation manifest ---------------
        if patched and sidx_node is not None:
            _refresh_sidx(disk, reader, imap, game_dir, sidx_path,
                          sidx_node, log, progress, total, check)
        elif patched:
            log("  ! no /spk/index/*.sidx manifest found — the card's own "
                "validation may reject the modified image")

    return {"audio": patched, "skipped": skipped}


def _write_preview(preview_dir, idx, track, body, ch, rate, log):
    """Machine-render preview (Advanced audio options): the patched PCM *is*
    exactly what the machine will play, so drop it as a WAV.  Best-effort —
    a preview must never fail a Write (same contract as Spike 2)."""
    if not preview_dir:
        return
    try:
        os.makedirs(preview_dir, exist_ok=True)
        stem = "idx%04d" % idx + ("-t%d" % (track + 1) if track else "")
        path = os.path.join(preview_dir, stem + "_machine_render.wav")
        with wave.open(_lp(path), "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(body)
    except Exception:
        pass


def revert_assets(source_path, assets_dir, rels, log=None, progress=None,
                  cancel=None):
    """Re-decode the pristine WAVs for *rels* straight from the source card.

    The no-``.orig``-snapshot Revert fallback: each rel like
    ``audio/idx0398.wav`` (renamed forms included) is decoded from the card
    and written back over the edited copy.  Returns ``(reverted, failed)``
    rel lists.
    """
    from .formats import spike1_linux_partitions

    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    parts = spike1_linux_partitions(source_path)
    if not parts:
        raise Spike1Error("no ext partitions found in the source card image")
    reverted, failed = [], []
    with open(_lp(source_path), "rb") as disk:
        reader, _game_dir, image_node, _sp, _sn = locate_assets(disk, parts)
        imap = _FileMap(reader, image_node)
        window = _CardWindow(disk, imap)
        master = parse_master(window, imap.size)
        records = {r["idx"]: r for r in master["records"]}
        for n, rel in enumerate(rels):
            if check():
                break
            parsed = parse_wav_stem(
                os.path.splitext(os.path.basename(rel))[0])
            rec = records.get(parsed[0]) if parsed else None
            if rec is None or parsed[1] >= len(rec["tracks"]):
                failed.append(rel)
                log("  ! %s: no matching sound on the source card" % rel)
                continue
            body_off, frames, ch, div = rec["tracks"][parsed[1]]
            out = os.path.join(assets_dir, rel.replace("/", os.sep))
            _write_wav_from(window, out, body_off, frames, ch, div)
            reverted.append(rel)
            log("  restored %s" % rel)
            if progress:
                progress(n + 1, len(rels), "Restoring originals")
    return reverted, failed


def _refresh_sidx(disk, reader, imap, game_dir, sidx_path, sidx_node, log,
                  progress, total, check=None):
    """Recompute the patched image.bin's digests in the card's .sidx."""
    import hashlib
    import hmac as hmac_mod

    check = check or (lambda: False)
    sidx_data = reader.read_file_bytes(sidx_node)
    recs, _crc, fmt = sidx_mod.parse_records(sidx_data)
    key = "%s/image.bin" % game_dir
    if not recs or key not in recs:
        log("  ! %s carries no record for %s — sidx left untouched"
            % (os.path.basename(sidx_path or "sidx"), key))
        return
    h = hmac_mod.new(sidx_mod.SIDX_KEY, digestmod=hashlib.sha1)
    md5 = hashlib.md5()
    pos = 0
    while pos < imap.size:
        # This full-image digest is the Write's second-longest stretch, so
        # cancel must stay live here (the caller then removes the output —
        # a patched image with a stale sidx must not survive).
        if check():
            raise Spike1Cancelled("cancelled")
        n = min(1 << 23, imap.size - pos)
        buf = imap.read(disk, pos, n)
        h.update(buf)
        md5.update(buf)
        pos += n
        if progress:
            progress(total + total // 2 + pos * total // (2 * imap.size),
                     total * 2, "Refreshing card validation")
    field_writes = sidx_mod.record_field_writes(
        recs[key], h.digest(), md5.digest(), fmt)
    smap = _FileMap(reader, sidx_node)
    for rel_off, payload in field_writes:
        for disk_off, n in smap.ranges(rel_off, len(payload)):
            disk.seek(disk_off)
            disk.write(payload[:n])
            payload = payload[n:]
    disk.flush()
    log("Refreshed %s record in %s" % (key, sidx_path))
