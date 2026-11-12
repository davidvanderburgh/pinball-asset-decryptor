"""Stern **Spike 3** Write: put a project's replaced sounds, videos, images,
scenes and text onto a copy of the secure SD card (PAD-1186).

A Spike 3 card's games volume (p6, LUKS2 over ext4) carries Spike 2's own
asset tree, so everything but the sounds goes through the Spike 2 write core
(:func:`.engine._compute_patches`) over the decrypted volume
(:class:`.spike3_card.GamesVolume`): the same diff against the Extract
baseline, the same video / image / scene / text / colour work and the same
``.sidx`` validation-record refresh.  Its writes are plaintext offsets in the
volume; the output card's volume takes them and encrypts them back under the
card's own master key, sector by sector, so the rest of the card is the
original's bytes.

Sounds are plain 16-bit PCM in ``image.bin`` (:mod:`.spike3_sound`), one
container per sound set (the game's, and the service menu's under
``spike3/spike_menu``).  A replacement that fits its sound's slot is written
over the body in place, padded with silence (its record unchanged); a longer
one is appended in front of the directory, its record re-pointed, the
directory's CRC (the trailer's first word) and the header's two tail pointers
moved, and the container goes onto the card whole.

A file that has to grow (a longer sound's container, a video larger than its
slot) is copied over the card's own file through the Linux kernel's ext4
driver on the volume opened with dm-crypt (:func:`.ext4_grow.grow_files`,
``luks``), as Spike 2's grown files are without the encryption.
"""

from __future__ import annotations

import os
import struct
import time
import zlib

from ...core.pipeline_base import BasePipeline, PipelineError
from . import spike3_card, spike3_sound

PHASES = ("Detect", "Stage", "Encode", "Write card")

#: the project folder of the game's own sounds (the Spike 2 layout's)
GAME_SOUNDS = "audio"


def _np():
    import numpy as np
    return np


# --------------------------------------------------------------------------
# The sound containers and their project folders
# --------------------------------------------------------------------------

def sound_containers(reader):
    """``[(card_path, node), ...]`` for every ``image.bin`` on the volume,
    the game's own first (the one beside the game's assets)."""
    main_ino, _fw = reader.find_spike_assets()
    out = []
    for path, ino, node in reader.iter_regular_files(min_size=0x80,
                                                     max_depth=12):
        if os.path.basename(path) != "image.bin":
            continue
        out.append((0 if ino == main_ino else 1, path, node))
    out.sort(key=lambda t: (t[0], t[1]))
    return [(p, n) for _k, p, n in out]


def sound_dir(card_path, main):
    """The project folder a container's WAVs live in: ``audio`` for the
    game's own, ``audio_<folder>`` for another (``audio_spike_menu``: the
    service menu's), so the two sets never share a name."""
    if main:
        return GAME_SOUNDS
    parent = os.path.basename(os.path.dirname(card_path.rstrip("/"))) or "other"
    return "audio_" + parent


def project_sound_dirs(reader):
    """``[(card_path, node, project_dir), ...]`` for the volume."""
    conts = sound_containers(reader)
    return [(p, n, sound_dir(p, i == 0)) for i, (p, n) in enumerate(conts)]


# --------------------------------------------------------------------------
# One container's plan
# --------------------------------------------------------------------------

class SoundPlan:
    """The sound edits for one container: in place, or the file whole."""

    def __init__(self, card_path, node, folder):
        self.card_path = card_path
        self.node = node
        self.folder = folder
        self.inplace = []          # [(file_off, bytes)]
        self.staged = None         # path of the whole file, when it grows
        self.n_fit = 0
        self.n_grown = 0
        self.padded = []           # idx shorter than their slot
        self.grown = []            # idx longer than their slot


def _changed_wavs(assets_dir, folder, baseline):
    """``{idx: path}`` of the WAVs in *folder* whose bytes differ from the
    Extract baseline (``idxNNNN.wav``, or a renamed ``idxNNNN - name.wav``)."""
    from . import engine
    base = os.path.join(assets_dir, folder)
    if not os.path.isdir(base):
        return {}
    out = {}
    for fn in sorted(os.listdir(base)):
        if not fn.lower().endswith(".wav"):
            continue
        idx = engine._wav_idx(os.path.splitext(fn)[0])
        if idx is None:
            continue
        path = os.path.join(base, fn)
        rel = os.path.relpath(path, assets_dir).replace(os.sep, "/")
        want = baseline.get(rel)
        if want is not None and engine._scan_md5(assets_dir, path) == want:
            continue
        out[idx] = path
    return out


def _pcm(path, rec, np):
    """The WAV at *path* as the record's 16-bit PCM (its channel count,
    44.1 kHz), as an int16 array of frames x channels."""
    from . import engine
    a = engine._load_wav(path, rec.channels == 2, np)
    a = np.clip(np.asarray(a, np.int64), -32768, 32767).astype(np.int16)
    return a.reshape(-1, rec.channels)


def _fit_frames(a, frames, np):
    """*a* (frames x ch int16) trimmed / silence-padded to *frames*, with the
    engine's fade at the edges of the real audio."""
    from . import engine
    cols = [engine._fit(a[:, c].astype(np.int64), frames, np)
            for c in range(a.shape[1])]
    return np.clip(np.stack(cols, 1), -32768, 32767).astype("<i2")


def read_container(reader, node):
    """``(header bytes, ImageSound view)`` of the container *node*, read off
    the volume (header, directory and trailer only)."""
    hdr = reader.read_range(node, 0, spike3_sound.HEADER_SIZE)
    md_off = struct.unpack_from("<Q", hdr, spike3_sound.MD_OFF_FIELD)[0]
    count = struct.unpack_from("<I", hdr, spike3_sound.COUNT_FIELD)[0]
    d = reader.read_range(node, md_off, spike3_sound.RECORD_SIZE * count)
    img = spike3_sound.ImageSound.from_parts(hdr, d, node["size"])
    return hdr, img


def plan_sounds(reader, assets_dir, baseline, work_dir, log, cancel=None):
    """The :class:`SoundPlan` of every container with an edited sound.

    Every replacement plays at its own length, as on Spike 2: one no longer
    than its sound goes over that body in place with its record's frame
    count cut to it (the directory and its CRC rewritten in place too); a
    longer one is appended and the container goes on whole
    (:func:`_stage_grown`).  A record's other words - the ids the game
    finds a sound by - are never changed."""
    np = _np()
    rs = spike3_sound.RECORD_SIZE
    plans = []
    for card_path, node, folder in project_sound_dirs(reader):
        edits = _changed_wavs(assets_dir, folder, baseline)
        if not edits:
            continue
        hdr, img = read_container(reader, node)
        dir_len = spike3_sound._align16(rs * img.count)
        d = bytearray(reader.read_range(node, img.md_off, dir_len))
        trailer = bytearray(reader.read_range(node, img.md_off + dir_len, 8))
        plan = SoundPlan(card_path, node, folder)
        grows = []
        for idx in sorted(edits):
            if cancel:
                cancel()
            if idx >= img.count:
                log("%s: %s names sound %d, but this card's container has "
                    "only %d; left out." % (folder, os.path.basename(edits[idx]),
                                            idx, img.count), "warning")
                continue
            rec = img.records[idx]
            a = _pcm(edits[idx], rec, np)
            n = max(len(a), 1)
            body = _fit_frames(a, n, np).tobytes()
            if n <= rec.frames:
                plan.inplace.append((rec.offset, body))
                plan.n_fit += 1
                if n < rec.frames:
                    struct.pack_into("<I", d, idx * rs + 0x10, n)
                    plan.padded.append(idx)
            else:
                grows.append((rec, body, n))
        if grows:
            plan.staged = os.path.join(
                work_dir, "%s_image.bin" % folder.replace("/", "_"))
            _stage_grown(reader, node, hdr, img, d, trailer, plan.inplace,
                         grows, plan.staged, cancel)
            plan.n_grown = len(grows)
            plan.grown = [r.index for r, _b, _n in grows]
        elif plan.padded:
            struct.pack_into("<I", trailer, 0, dir_crc(d, img.count))
            plan.inplace.append((img.md_off, bytes(d)))
            plan.inplace.append((img.md_off + dir_len, bytes(trailer[:4])))
        plans.append(plan)
    return plans


def dir_crc(d, count):
    """The CRC32 a container's trailer opens with: of its whole directory,
    ``align16(24 * count)`` bytes with the padding (Pokemon LE 0.82.0's:
    0x199a2999; measured on the game's and the service menu's containers of
    four titles, odd counts among them)."""
    return zlib.crc32(bytes(
        d[:spike3_sound._align16(spike3_sound.RECORD_SIZE * count)]))


def _stage_grown(reader, node, hdr, img, d, trailer, inplace, grows,
                 out_path, cancel):
    """Write the whole container to *out_path* with the longer bodies
    appended after the old body region and the directory moved past them.

    Layout kept: ``[0, md_off)`` as on the card (the bodies that fit
    replaced in place), then the appended bodies, then the directory *d*
    (already carrying the in-place sounds' lengths) with the grown records
    re-pointed, then the 8-byte trailer with its first word the directory's
    CRC32 (as on every card).  The header words that point at the tail (the
    directory at 0x40, the trailer's second word at 0x38) move by the same
    amount."""
    old_md = img.md_off
    count = img.count
    rs = spike3_sound.RECORD_SIZE
    dir_len = spike3_sound._align16(rs * count)
    delta = sum(len(b) for _r, b, _n in grows)
    d = bytearray(d)
    with open(out_path, "wb") as out:
        for off, chunk in reader.read_file_chunks(node):
            if off >= old_md:
                break
            if cancel:
                cancel()
            out.write(chunk[:old_md - off])
        for off, body in inplace:
            out.seek(off)
            out.write(body)
        out.seek(old_md)
        pos = old_md
        moved = {}
        for rec, body, frames in grows:
            out.write(body)
            moved[rec.index] = (pos, frames)
            pos += len(body)
        for idx, (off, frames) in moved.items():
            struct.pack_into("<Q", d, idx * rs, off)
            struct.pack_into("<I", d, idx * rs + 0x10, frames)
        out.write(bytes(d))
        tr = bytearray(trailer)
        struct.pack_into("<I", tr, 0, dir_crc(d, count))
        out.write(bytes(tr))
        h = bytearray(hdr)
        tail_word = old_md + dir_len + 4
        for at in range(0, spike3_sound.HEADER_SIZE - 7, 8):
            v = struct.unpack_from("<Q", h, at)[0]
            if v in (old_md, tail_word) and at != spike3_sound.COUNT_FIELD:
                struct.pack_into("<Q", h, at, v + delta)
        out.seek(0)
        out.write(bytes(h))
    # the result reads back as a container, every body inside the body region
    chk = spike3_sound.ImageSound(out_path)
    chk.validate()
    for idx, (off, frames) in moved.items():
        r = chk.records[idx]
        if r.offset != off or r.frames != frames:
            raise RuntimeError("the grown sound container did not read back "
                               "(sound %d)" % idx)


# --------------------------------------------------------------------------
# The Write
# --------------------------------------------------------------------------

def _sidx_refresh(vol, reader, card_path, node, staged, log):
    """Refresh the ``.sidx`` record of the file *card_path* from what the
    card now holds (*staged*: its new whole content, a file on disk)."""
    from . import sidx
    sidx_path, sidx_node = sidx.find_sidx(reader)
    if sidx_node is None:
        return False
    data = reader.read_file_bytes(sidx_node)
    recs, _crc, fmt = sidx.parse_records(data)
    po = recs.get(card_path.lstrip("/"))
    if po is None:
        log("  .sidx has no record for %s - left stale." % card_path, "warning")
        return False
    if staged:
        hm, md = sidx.digests_file(staged)
        size = os.path.getsize(staged)
    else:
        import hashlib
        import hmac as _hmac
        h = _hmac.new(sidx.SIDX_KEY, digestmod=hashlib.sha1)
        m = hashlib.md5()
        for _off, chunk in reader.read_file_chunks(node):
            h.update(chunk)
            m.update(chunk)
        hm, md, size = h.digest(), m.digest(), None
    for foff, b in sidx.record_field_writes(po, hm, md, fmt, size=size):
        for d, n in reader.disk_ranges(sidx_node, foff, len(b)):
            vol.seek(d)
            vol.write(b[:n])
            b = b[n:]
    return True


def write_card(original_path, assets_dir, output_path, log=None,
               progress=None, cancel=None, phase=None, key_source=None):
    """Build *output_path* from the Spike 3 card *original_path* with the
    project's edits.  Returns ``(n_audio, n_video, n_image, n_text)``."""
    from ...core.checksums import read_checksums
    from ...core import ext4_grow
    from . import engine
    from .ext4 import Ext4Reader

    log = log or (lambda *a, **k: None)
    cancel_fn = cancel or (lambda: False)
    phase = phase or (lambda i: None)

    def check():
        if cancel_fn():
            raise _Cancelled()

    t0 = time.monotonic()
    phase(1)  # Stage
    # the original's key opens the copy too (no key file sits beside it)
    from .spike3_keys import Spike3KeySource
    key_source = key_source or Spike3KeySource.discover(
        image_path=original_path, image_id=spike3_card.image_id(original_path))
    src = spike3_card.open_games(original_path, key_source=key_source)
    work = engine._work_dir(None, base="spike3_write_")
    grow_plan = copier = None
    try:
        reader = Ext4Reader(src, 0, src.size)
        baseline = read_checksums(assets_dir)
        phase(2)  # Encode
        try:
            writes, counts, grow_plan, _am, _vp = engine._compute_patches(
                src, spike3_card.volume_parts(src), assets_dir, log, progress,
                cancel_fn)
        except engine.NothingToWrite:
            writes, counts, grow_plan = [], (0, 0, 0, 0), None
        except FileNotFoundError:
            writes, counts, grow_plan = [], (0, 0, 0, 0), None
        if writes is None:
            raise _Cancelled()
        writes = engine._as_write_list(writes)
        sounds = plan_sounds(reader, assets_dir, baseline, work, log, check)
        n_audio = sum(p.n_fit + p.n_grown for p in sounds)
        for p in sounds:
            if p.padded:
                log("%s: %d replacement(s) shorter than the sound they replace "
                    "play at their own length." % (p.folder, len(p.padded)),
                    "info")
            if p.grown:
                log("%s: %d replacement(s) longer than their sound; the sound "
                    "container goes onto the card whole with them added."
                    % (p.folder, len(p.grown)), "info")
        n_audio_c, n_video, n_image, n_text = tuple(counts)[:4]
        if not writes and not sounds and not (grow_plan or {}).get("jobs"):
            raise engine.NothingToWrite(
                "Nothing to write: no sound, video, image, scene or text in "
                "this project differs from the card it was extracted from.")
        check()
        # the card is copied with the OS's own copy, on a thread of its own
        _write_record(output_path, original_path, complete=False)
        copier = _Copier(original_path, output_path)

        phase(3)  # Write card
        copier.wait(log, progress, check)
        out = spike3_card.open_games(output_path, writable=True,
                                     key_source=key_source)
        try:
            for off, b in writes:
                out.seek(off)
                out.write(b)
            out_reader = Ext4Reader(out, 0, out.size)
            jobs = list((grow_plan or {}).get("jobs") or [])
            for p in sounds:
                if p.staged:
                    jobs.append((p.card_path.lstrip("/"), p.staged))
                else:
                    for off, body in p.inplace:
                        for d, n in out_reader.disk_ranges(p.node, off,
                                                           len(body)):
                            out.seek(d)
                            out.write(body[:n])
                            body = body[n:]
            out.flush()
            # .sidx records: an in-place sound container's from the card; a
            # file that goes on whole (a grown container, and the engine's
            # grown videos and scenes, whose records the Spike 2 core leaves
            # to its validator bypass - which a Spike 3 game program has no
            # counterpart of) from the file it will be, size included
            n_rec = 0
            for p in sounds:
                if not p.staged:
                    n_rec += _sidx_refresh(out, out_reader, p.card_path,
                                           p.node, None, log)
            for rel, whole in jobs:
                n_rec += _sidx_refresh(out, out_reader, "/" + rel.lstrip("/"),
                                       None, whole, log)
            if n_rec:
                log("Refreshed %d more SD-validation manifest record(s) for "
                    "the files written whole or in the sound containers."
                    % n_rec, "info")
            out.flush()
            luks = {"key": out.master_key, "offset": out.segment_offset,
                    "sector_size": out._sector,
                    "cipher": out.header.segment("0")["encryption"]}
            poff, psize = out.part_offset, out.part["sectors"] * 512
        finally:
            out.close()
        if jobs:
            log("Copying %d file(s) whole onto the card through its "
                "encrypted volume..." % len(jobs), "info")
            try:
                grown = ext4_grow.grow_files(output_path, poff, jobs, log=log,
                                             cancel=cancel_fn, luks=luks,
                                             part_size=psize)
            except ext4_grow.Ext4GrowUnavailable as e:
                log(str(e), "error")
                grown = 0
            if grown < len(jobs):
                raise PipelineError(
                    "Write card",
                    "%d of %d file(s) that had to grow could not be copied "
                    "onto the card (see the log), so this card is not "
                    "complete." % (len(jobs) - grown, len(jobs)))
        _write_record(output_path, original_path, complete=True,
                      counts=(n_audio, n_video, n_image, n_text))
        log("Wrote the Spike 3 card in %.0f s: %s (%d sound(s), %d video(s), "
            "%d image(s), %d display string(s))."
            % (time.monotonic() - t0, output_path, n_audio, n_video, n_image,
               n_text), "success")
        return (n_audio, n_video, n_image, n_text)
    except BaseException:
        if copier is not None:
            copier.join()              # never remove a file still being written
        raise
    finally:
        src.close()
        engine._rmtree(work)
        engine._rmtree_grow_plan(grow_plan)


class _Cancelled(Exception):
    pass


def _write_record(output_path, original_path, complete, counts=None):
    """The build record beside the card (engine.BUILD_MANIFEST_SUFFIX).  Its
    fresh ``build_id`` is what tells the Spike 3 card store this card from
    the last build under the same name (tools/spike3_emu/s3store.py
    card_id): the Write changes files in place, past the bytes the store
    fingerprints."""
    import uuid
    from . import engine
    rec = {"spike3": True, "build_id": uuid.uuid4().hex,
           "original": os.path.basename(original_path),
           "complete": bool(complete)}
    if counts is not None:
        rec["counts"] = dict(zip(("audio", "video", "image", "text"), counts))
    try:
        engine._write_build_manifest(output_path, rec)
    except OSError:
        pass


class _Copier:
    """The card image copied to the output on a thread of its own, with the
    OS's own copy (shutil.copyfile: CopyFileEx on Windows), while the edits
    are worked out - :func:`write_card` waits for it before the first write."""

    def __init__(self, src, dst):
        import threading
        self.src, self.dst = src, dst
        self.error = None
        self.total = os.path.getsize(src)
        self.t0 = time.monotonic()
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name="spike3-card-copy")
        self.thread.start()

    def _run(self):
        import shutil
        try:
            shutil.copyfile(self.src, self.dst)
        except BaseException as e:          # noqa: BLE001 - raised by wait()
            self.error = e

    def join(self):
        self.thread.join()

    def wait(self, log, progress, check):
        if self.thread.is_alive():
            log("Waiting for the card image copy to finish (%.1f GB)..."
                % (self.total / 1e9), "info")
        while self.thread.is_alive():
            check()
            if progress:
                try:
                    done = os.path.getsize(self.dst)
                except OSError:
                    done = 0
                progress(min(done, self.total), self.total,
                         "Copying the card %d%%"
                         % (min(done, self.total) * 100 // max(self.total, 1)))
            self.thread.join(1.0)
        if self.error is not None:
            raise OSError("Could not copy the card image to the build's "
                          "destination:\n\n    %s\n\n%s"
                          % (self.dst, self.error)) from self.error
        log("Copied the card image in %.0f s." % (time.monotonic() - self.t0),
            "info")


class Spike3WritePipeline(BasePipeline):
    """The Write tab's job for a Spike 3 card."""

    PHASES = PHASES

    def __init__(self, original_path, assets_dir, output_path,
                 log_cb, phase_cb, progress_cb, done_cb, update=None,
                 key_source=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.original_path = original_path
        self.assets_dir = assets_dir
        self.output_path = output_path
        self.key_source = key_source
        self.card_size_refusal = None

    def _run(self):
        from . import spike3, engine
        from .spike3_keys import Spike3KeyError
        self._set_phase(0)  # Detect
        if not spike3.is_spike3_card(self.original_path):
            raise PipelineError("Detect", "The original is not a Stern Spike 3 "
                                "secure SD-card image.")
        self._check_cancel()
        try:
            counts = write_card(self.original_path, self.assets_dir,
                                self.output_path, log=self._log,
                                progress=self._progress,
                                cancel=lambda: self._cancelled,
                                phase=self._set_phase,
                                key_source=self.key_source)
        except _Cancelled:
            _discard(self.output_path)
            self._check_cancel()
            raise PipelineError("Write card", "Cancelled.")
        except Spike3KeyError as e:
            raise PipelineError("Stage", str(e))
        except engine.NothingToWrite as e:
            raise PipelineError("Stage", str(e))
        except RuntimeError as e:
            _discard(self.output_path)
            raise PipelineError("Encode", str(e))
        n_audio, n_video, n_image, n_text = counts
        bits = []
        for n, word in ((n_audio, "sound"), (n_video, "video"),
                        (n_image, "image"), (n_text, "display string")):
            if n:
                bits.append("%d %s%s" % (n, word, "" if n == 1 else "s"))
        self._done(True, "Wrote %s to %s" % (", ".join(bits) or "the card",
                                             self.output_path))


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass
