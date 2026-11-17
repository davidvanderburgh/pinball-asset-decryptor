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
import re
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
    """``[(card_path, node), ...]`` for every sound container on the volume:
    each ``image.bin`` and its ``image-scNN.bin`` music banks (the same
    format, PAD-1185), the game's own first (the one beside the game's
    assets), a folder's banks after its ``image.bin`` in number order."""
    from .spike3_extract import is_sound_container, _container_order
    main_ino, _fw = reader.find_spike_assets()
    main_dirs = set()
    found = []
    for path, ino, node in reader.iter_regular_files(min_size=0x80,
                                                     max_depth=12):
        if not is_sound_container(os.path.basename(path)):
            continue
        if ino == main_ino:
            main_dirs.add(os.path.dirname(path))
        found.append((path, node))
    out = [(0 if os.path.dirname(p) in main_dirs else 1,
            _container_order(p), p, n) for p, n in found]
    out.sort(key=lambda t: (t[0], t[1]))
    return [(p, n) for _k, _o, p, n in out]


def sound_dir(card_path, main):
    """The project folder a container's WAVs live in: ``audio`` for the
    game's own, ``audio_<folder>`` for another (``audio_spike_menu``: the
    service menu's), so the two sets never share a name.  A music bank's
    folder is its ``image.bin``'s."""
    if main:
        return GAME_SOUNDS
    parent = os.path.basename(os.path.dirname(card_path.rstrip("/"))) or "other"
    return "audio_" + parent


def project_sound_dirs(reader):
    """``[(card_path, node, project_dir, stem), ...]`` for the volume.
    *stem* is ``None`` for an ``image.bin`` (its WAVs are ``idxNNNN``) and
    ``music_catNN`` for bank NN (``music_catNN_NNNN``)."""
    from .spike3_extract import _sound_stem
    conts = sound_containers(reader)
    main_dir = os.path.dirname(conts[0][0]) if conts else None
    return [(p, n, sound_dir(p, i == 0 or os.path.dirname(p) == main_dir),
             _sound_stem(os.path.basename(p)))
            for i, (p, n) in enumerate(conts)]


# --------------------------------------------------------------------------
# One container's plan
# --------------------------------------------------------------------------

class SoundPlan:
    """The sound edits for one container: in place, or the file whole."""

    def __init__(self, card_path, node, folder, stem=None):
        self.card_path = card_path
        self.node = node
        self.folder = folder
        self.stem = stem           # None: image.bin; "music_catNN": a bank
        self.inplace = []          # [(file_off, bytes)]
        self.staged = None         # path of the whole file, when it grows
        self.n_fit = 0
        self.n_grown = 0
        self.padded = []           # idx shorter than their slot
        self.grown = []            # idx longer than their slot
        self.appended = []         # idx of the records added (PAD-1296)


_MUSIC_STEM_RE = re.compile(r"\bmusic_cat0*(\d+)_0*(\d+)", re.IGNORECASE)


def _wav_index(stem, name_stem):
    """The sound number a WAV name *name_stem* gives in the container whose
    WAV stem is *stem* (``None``: ``idxNNNN``; ``music_catNN``: that bank's
    ``music_catNN_NNNN``), or ``None`` when the WAV is another container's."""
    from . import engine
    if stem is None:
        if _MUSIC_STEM_RE.search(name_stem):
            return None
        return engine._wav_idx(name_stem)
    m = _MUSIC_STEM_RE.search(name_stem)
    if not m or "music_cat%02d" % int(m.group(1)) != stem.lower():
        return None
    return int(m.group(2))


def _changed_wavs(assets_dir, folder, baseline, stem=None):
    """``{idx: path}`` of the WAVs in *folder* whose bytes differ from the
    Extract baseline (``idxNNNN.wav``, or a renamed ``idxNNNN - name.wav``;
    with *stem* a music bank's ``music_catNN_NNNN[ - name].wav``)."""
    from . import engine
    base = os.path.join(assets_dir, folder)
    if not os.path.isdir(base):
        return {}
    out = {}
    for fn in sorted(os.listdir(base)):
        if not fn.lower().endswith(".wav"):
            continue
        idx = _wav_index(stem, os.path.splitext(fn)[0])
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


def plan_sounds(reader, assets_dir, baseline, work_dir, log, cancel=None,
                adds=None):
    """The :class:`SoundPlan` of every container with an edited sound, or
    with records to append (*adds*: ``{card_path: [NewRecord, ...]}``, the
    modes' own sounds, PAD-1296).

    Every replacement plays at its own length, as on Spike 2: one no longer
    than its sound goes over that body in place with its record's frame
    count cut to it (the directory and its CRC rewritten in place too); a
    longer one is appended and the container goes on whole
    (:func:`_stage_grown`).  A record's other words - the ids the game
    finds a sound by - are never changed.  An appended record (*adds*) is a
    new one after the last, its body after the old body region: the
    container goes on whole."""
    np = _np()
    rs = spike3_sound.RECORD_SIZE
    plans = []
    for card_path, node, folder, stem in project_sound_dirs(reader):
        edits = _changed_wavs(assets_dir, folder, baseline, stem)
        news = list((adds or {}).get(card_path) or ())
        if not edits and not news:
            continue
        hdr, img = read_container(reader, node)
        dir_len = spike3_sound._align16(rs * img.count)
        d = bytearray(reader.read_range(node, img.md_off, dir_len))
        trailer = bytearray(reader.read_range(node, img.md_off + dir_len, 8))
        plan = SoundPlan(card_path, node, folder, stem)
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
        appended = []
        for nr in news:
            if cancel:
                cancel()
            a = _pcm(nr.wav, nr, np)
            n = max(len(a), 1)
            appended.append((nr, _fit_frames(a, n, np).tobytes(), n))
        if grows or appended:
            plan.staged = os.path.join(
                work_dir, "%s_%s" % (folder.replace("/", "_"),
                                     os.path.basename(card_path)))
            _stage_grown(reader, node, hdr, img, d, trailer, plan.inplace,
                         grows, plan.staged, cancel, adds=appended)
            plan.n_grown = len(grows)
            plan.grown = [r.index for r, _b, _n in grows]
            plan.appended = [img.count + k for k in range(len(appended))]
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
                 out_path, cancel, adds=()):
    """Write the whole container to *out_path* with the longer bodies
    appended after the old body region and the directory moved past them.

    Layout kept: ``[0, md_off)`` as on the card (the bodies that fit
    replaced in place), then the appended bodies, then the directory *d*
    (already carrying the in-place sounds' lengths) with the grown records
    re-pointed, then the 8-byte trailer with its first word the directory's
    CRC32 (as on every card).  The header words that point at the tail (the
    directory at 0x40, the trailer's second word at 0x38) move with it.

    *adds* (PAD-1296): ``[(NewRecord, body, frames)]`` - records of their
    own after the last (a mode's own sounds), their bodies after the grown
    ones; the directory grows by a record each and the header's count with
    it."""
    old_md, count = img.md_off, img.count
    bodies, d, tr, h, moved = _tail(hdr, img, d, trailer, grows, adds)
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
        for body in bodies:
            out.write(body)
        out.write(d)
        out.write(tr)
        out.seek(0)
        out.write(h)
    _check_grown(out_path, count, moved, adds)


def _tail(hdr, img, d, trailer, grows, adds):
    """The grown container's new tail: ``(bodies, directory, trailer, header,
    moved)`` - the bodies in order from the old directory's offset, the
    directory with the grown records re-pointed and the added ones after the
    last, the trailer (its first word the directory's CRC32), the header
    with the tail words and the count moved, and ``{idx: (offset, frames)}``
    of the grown records."""
    old_md = img.md_off
    count = img.count
    rs = spike3_sound.RECORD_SIZE
    dir_len = spike3_sound._align16(rs * count)
    new_count = count + len(adds)
    new_dir_len = spike3_sound._align16(rs * new_count)
    d = bytearray(d[:rs * count]) + bytearray(new_dir_len - rs * count)
    pos = old_md
    moved, bodies = {}, []
    for rec, body, frames in grows:
        bodies.append(body)
        moved[rec.index] = (pos, frames)
        pos += len(body)
    for k, (nr, body, frames) in enumerate(adds):
        bodies.append(body)
        struct.pack_into("<QIIII", d, (count + k) * rs, pos, nr.flags_lo,
                         nr.param, frames, nr.param2)
        pos += len(body)
    for idx, (off, frames) in moved.items():
        struct.pack_into("<Q", d, idx * rs, off)
        struct.pack_into("<I", d, idx * rs + 0x10, frames)
    tr = bytearray(trailer)
    struct.pack_into("<I", tr, 0, dir_crc(d, new_count))
    h = bytearray(hdr)
    tail_word = old_md + dir_len + 4
    new_md = pos
    for at in range(0, spike3_sound.HEADER_SIZE - 7, 8):
        v = struct.unpack_from("<Q", h, at)[0]
        if at == spike3_sound.COUNT_FIELD:
            continue
        if v == old_md:
            struct.pack_into("<Q", h, at, new_md)
        elif v == tail_word:
            struct.pack_into("<Q", h, at, new_md + new_dir_len + 4)
    struct.pack_into("<I", h, spike3_sound.COUNT_FIELD, new_count)
    return bodies, bytes(d), bytes(tr), bytes(h), moved


def stage_tail(reader, node, adds, out_dir, name):
    """PAD-1296: Try it's own sounds on the Spike 3 rig - the container
    *node* with the records *adds* (``[NewRecord]``) appended, as a PATCH of
    the card's own file rather than the whole file: ``(cut, head, tail)``,
    the file is the card's cut at *cut* (its old directory's offset), then
    the bytes of *tail*, with its first 0x80 bytes those of *head*
    (``<name>.head`` / ``<name>.tail`` in *out_dir*). s3run.sh builds it in
    the rig slot's /games overlay from the store's copy (PAD_S3_MODE_FILES's
    ``games.patch``)."""
    np = _np()
    hdr, img = read_container(reader, node)
    dir_len = spike3_sound._align16(spike3_sound.RECORD_SIZE * img.count)
    d = reader.read_range(node, img.md_off, dir_len)
    trailer = reader.read_range(node, img.md_off + dir_len, 8)
    appended = []
    for nr in adds:
        a = _pcm(nr.wav, nr, np)
        n = max(len(a), 1)
        appended.append((nr, _fit_frames(a, n, np).tobytes(), n))
    bodies, d, tr, h, _moved = _tail(hdr, img, d, trailer, [], appended)
    os.makedirs(out_dir, exist_ok=True)
    head, tail = os.path.join(out_dir, name + ".head"), os.path.join(out_dir, name + ".tail")
    with open(tail, "wb") as f:
        for body in bodies:
            f.write(body)
        f.write(d)
        f.write(tr)
    with open(head, "wb") as f:
        f.write(h)
    # the patched header and directory read back as the grown container
    size = img.md_off + os.path.getsize(tail)
    chk = spike3_sound.ImageSound.from_parts(h, d, size)
    for k, (nr, _b, frames) in enumerate(appended):
        r = chk.records[img.count + k]
        if (r.flags_lo, r.param, r.frames) != (nr.flags_lo, nr.param, frames):
            raise RuntimeError("the sound container's patch did not read back "
                               "(added sound %d)" % (img.count + k))
    return img.md_off, head, tail


def _check_grown(out_path, count, moved, adds):
    # the result reads back as a container, every body inside the body region
    chk = spike3_sound.ImageSound(out_path)
    chk.validate()
    for idx, (off, frames) in moved.items():
        r = chk.records[idx]
        if r.offset != off or r.frames != frames:
            raise RuntimeError("the grown sound container did not read back "
                               "(sound %d)" % idx)
    if chk.count != count + len(adds):
        raise RuntimeError("the grown sound container did not read back "
                           "(%d records, not %d)" % (chk.count, count + len(adds)))
    for k, (nr, _body, frames) in enumerate(adds):
        r = chk.records[count + k]
        if (r.flags_lo, r.param, r.frames) != (nr.flags_lo, nr.param, frames):
            raise RuntimeError("the grown sound container did not read back "
                               "(added sound %d)" % (count + k))


# --------------------------------------------------------------------------
# Records of their own (PAD-1296: a mode's own sounds)
# --------------------------------------------------------------------------

class NewRecord:
    """A record appended to a container: *wav* as *channels* (1 or 2), under
    the key ``flags_lo | param << 32`` - the 8 bytes the game's record lookup
    finds it by (a sound id's descriptor names its recordings by them;
    :func:`.spike3_requests.sound_parts`) - and *param2* (an id, unique per
    record on every card)."""

    def __init__(self, wav, channels, flags_lo, param, param2):
        self.wav = wav
        self.channels = int(channels)
        self.flags_lo = int(flags_lo) & 0xFFFFFFFF
        self.param = int(param) & 0xFFFFFFFF
        self.param2 = int(param2) & 0xFFFFFFFF

    @property
    def key(self):
        """The record key as the lookup reads it (its 8 bytes in order)."""
        return struct.pack("<II", self.flags_lo, self.param)


def free_key(records, flags_lo, param, taken=(), like=None, keep=0x3):
    """``(flags_lo, param)`` for a new record shaped like the record keyed
    *flags_lo* / *param* (a carrier's): the same flags word (its channel bit
    and the rest), and the param nearest *param* that no record of the
    container (*records*) nor one already handed out (*taken*, pairs) has
    with it.  Only the param bits some record already varies change, never
    bits 0-1 (Star Wars ELG 1.10: the 0x100000 steps and the top bits), so
    the key reads like the card's own.

    PAD-1358: *like* (records) reads the varying bits off other records than
    *records* (a music bank of one song varies none: every bank's), and
    *keep* the bits never changed (a bank's number is in its params' low 12
    bits, Fallout LE 0.82: ``0x82600008`` in image-sc02.bin)."""
    used = {(r.flags_lo, r.param) for r in records} | {tuple(t) for t in taken}
    var = 0
    for r in (records if like is None else like):
        var |= r.param ^ param
    var &= ~keep
    bits = [b for b in range(32) if var >> b & 1][:16]
    best = None
    for m in range(1, 1 << len(bits)):
        v = param
        for i, b in enumerate(bits):
            if m >> i & 1:
                v ^= 1 << b
        if (flags_lo, v) in used:
            continue
        cand = (bin(v ^ param).count("1"), abs(v - param), v)
        if best is None or cand < best:
            best = cand
    if best is None:
        raise RuntimeError("no free record key beside %08x %08x" % (flags_lo, param))
    return flags_lo, best[2]


def free_param2(records, seed, taken=()):
    """A *param2* no record of the container has (nor *taken*), from the
    bytes *seed*."""
    used = {r.param2 for r in records} | set(taken)
    v = zlib.crc32(seed) & 0xFFFFFFFF
    while v in used or v == 0:
        v = (v * 1103515245 + 12345) & 0xFFFFFFFF
    return v


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


def _sidx_new_files(reader, jobs, work, log):
    """PAD-1284: the files of *jobs* (``[(card rel, source)]``) the card's ``.sidx`` manifest has
    no record of - a mode's clip, a new file on the card - and the manifest with a record of
    each appended (:func:`.mode_write.compose_manifest`, as Spike 2's mode Write does: a file
    the manifest does not list fails Stern's SD validation), staged in *work* as a whole-file
    job. Returns ``(new rels, job or None)``; ``([], None)`` when every file has a record, or
    the card has no manifest this app can read (the existing refresh says so)."""
    from . import mode_write as MW, sidx
    log = log or (lambda *a, **k: None)
    if not jobs:
        return [], None
    sidx_path, sidx_node = sidx.find_sidx(reader)
    if sidx_node is None:
        return [], None
    stock = bytes(reader.read_file_bytes(sidx_node))
    recs, _crc, _fmt = sidx.parse_records(stock)
    if not recs:
        return [], None
    new = [(rel.lstrip("/"), src) for rel, src in jobs if rel.lstrip("/") not in recs]
    if not new:
        return [], None
    try:
        man = MW.compose_manifest(stock, new=new)
    except MW.ModeWriteError as e:
        raise PipelineError("Write card", "the SD-validation manifest could not take the new "
                                          "file(s): %s" % e) from None
    staged = os.path.join(work, "sidx", os.path.basename(sidx_path))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    with open(staged, "wb") as f:
        f.write(man)
    log("Added %d new file(s) to the SD-validation manifest: %s."
        % (len(new), ", ".join(os.path.basename(r) for r, _s in new)), "info")
    return [r for r, _s in new], (sidx_path.lstrip("/"), staged)


def _plan_modes(assets_dir, reader, work, log, coop_setting=0, coop_ok=True, hand_setting=0):
    """PAD-1272: ``(plan, remove)`` - the project's modes for this card, and its score
    feed (:func:`.spike3_modes.plan`, or None), and whether the card carries an
    earlier build's modes that this build, with none, takes off.  A mode that
    cannot be built stops the Write before anything is copied."""
    from . import mode_write as MW, spike3_modes
    try:
        mplan = spike3_modes.plan(assets_dir, reader, os.path.join(work, "modes"),
                                  log, coop_setting=coop_setting, coop_ok=coop_ok,
                                  hand_setting=hand_setting)
    except MW.ModeWriteError as e:
        raise PipelineError("Encode", "Modes: %s. Nothing was written." % e) from None
    if mplan is not None:
        for line in mplan.lines:
            # PAD-1297: the score feed's line names itself (PAD-1323: and the random clips' and screen times')
            if line.startswith("co-op play: "):         # PAD-1326: co-op's lines under its own name
                line = "Co-op play: " + line[len("co-op play: "):]
            elif line.startswith(("handicaps: ", "handicap ")):   # and the handicaps'
                line = "Handicaps: " + line[len("handicaps: "):] if line.startswith("handicaps: ") else "H" + line[1:]
            log(line if line.startswith(("Score feed:", "Random clips:", "Screen times:", "Co-op play:", "Handicap",
                                        "Prolonged Competition:", "Records on the high scores:"))   # PAD-1327
                else "Modes: %s" % line,
                "info")
        return mplan, False
    try:
        state, _target = spike3_modes.card_state(reader)
    except Exception:                                   # noqa: BLE001 - no link read: stock
        state = ""
    return None, state == "modes"


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
        # PAD-1272: the project's modes, onto the games partition (spike3_modes); a card an
        # earlier build put modes on, written with none now, has them taken off. Planned
        # before the sounds: PAD-1296's own sounds are records appended to image.bin.
        # PAD-1325: our operator-menu rows (EDITION; PAD-1326: CO-OP PLAY): the game program grown,
        # put on whole. Planned first: coop.cfg names the CO-OP PLAY row's live value.
        from . import menu_settings as MS, spike3_menu
        menu = spike3_menu.plan(assets_dir, reader, os.path.join(work, "menu"), log)
        coop_setting = menu.live(MS.COOP_PLAY) if menu is not None else 0
        coop_ok = bool(coop_setting) or not spike3_menu.coop_row_asked(assets_dir)
        hand_setting = menu.live(MS.HANDICAP) if menu is not None else 0
        mplan, mremove = _plan_modes(assets_dir, reader, work, log, coop_setting=coop_setting,
                                     coop_ok=coop_ok, hand_setting=hand_setting)
        sounds = plan_sounds(reader, assets_dir, baseline, work, log, check,
                             adds=mplan.sound_adds if mplan is not None else None)
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
            if p.appended:
                log("%s: the modes' %d own sound(s) added to the sound container "
                    "(records %s); it goes onto the card whole."
                    % (p.folder, len(p.appended),
                       ", ".join(str(i) for i in p.appended)), "info")
        n_audio_c, n_video, n_image, n_text = tuple(counts)[:4]
        if not writes and not sounds and not (grow_plan or {}).get("jobs") \
                and mplan is None and not mremove and menu is None:
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
            if mplan is not None:
                jobs += mplan.jobs        # the title's scenes the modes' screens and clips rewrite
            if menu is not None:
                jobs.append(menu.job)     # PAD-1325: the game program, its menu grown
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
            # PAD-1284: a file new on the card (a mode's clip) has no record to
            # refresh: the manifest, with one appended, goes on whole after them
            fresh, man_job = _sidx_new_files(out_reader, jobs, work, None)
            for rel, whole in jobs:
                if rel.lstrip("/") in fresh:
                    continue
                n_rec += _sidx_refresh(out, out_reader, "/" + rel.lstrip("/"),
                                       None, whole, log)
            if man_job is not None:
                out.flush()
                # the in-place refreshes above are in the card's manifest: rebuilt from it
                _fresh, man_job = _sidx_new_files(Ext4Reader(out, 0, out.size), jobs, work, log)
                jobs.append(man_job)
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
        if mplan is not None or mremove:
            from . import mode_write as MW, spike3_modes
            vol = dict(luks, part_offset=poff, part_size=psize)
            try:
                if mplan is not None:
                    spike3_modes.install(output_path, vol, mplan, log)
                else:
                    spike3_modes.remove(output_path, vol, log)
            except MW.ModeWriteError as e:
                raise PipelineError("Write card", "Modes: %s, so this card is not complete."
                                    % e) from None
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
