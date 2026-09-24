"""Spike 2 audio engine — orchestration over the self-contained codec engine.

Ties together the pure-Python ext4 reader (:mod:`.ext4`) and the unicorn codec
oracle (:mod:`.spike2`):

  * **extract_all** — locate ``game_real`` + ``image.bin`` in the card's ext
    partitions, boot the firmware, derive (and cache) every sound's decode
    params, then decode each sound to a per-sound WAV.
  * **write_image** — re-encode the edited WAVs (size-neutral) and patch the
    sound bodies back into the card image in place (the ext4 file→disk offset
    map lets us overwrite only the changed bytes).

Everything the engine needs derives from ``game_real`` + ``image.bin`` alone —
no bundled per-title blobs.  The per-card params table is derived once (~1-2
min) and cached by a fingerprint of those two files, so re-runs are fast.

Heavy deps (unicorn, capstone, numpy) are imported lazily inside the functions,
so importing this module (which happens at plugin discovery) never requires
them — a missing dep is reported by the manufacturer's prerequisite probe.
"""

import hashlib
import hmac
import os
import pickle
import re
import struct
import sys
import tempfile
import threading
import time
import wave
from collections import namedtuple

# Glyph slices sit 120+ characters below the project folder and the build
# output goes wherever the user pointed it, so both routinely pass Windows'
# 260-character limit — with an error that reads as "file not found" (a tester's
# build failed until he shortened the path).  _lp() opts each call out of it.
from ...core.longpath import ext as _lp

# The engine is wired; a missing unicorn/numpy is surfaced via the plugin's
# prerequisite probe + a lazy import error, not by hiding the tabs.
AVAILABLE = True

# The master-directory index in a decode-WAV stem.  The "idx" token can sit
# anywhere in the name: bare decode output ("idx0001"), an Auto-transcribe /
# Music-ID rename ("idx0001 - Kashmir"), and/or a play-length prefix
# ("01m22s235 - idx0001 - Kashmir", the Length-prefix-names extract option).
# A leading-anchored match would read the length prefix's digits as the index
# (mapping the edit onto the WRONG on-card sound), so search for the literal
# token; a stem that is nothing but digits ("0001.wav") stays accepted for
# hand-named files.
_IDX_TOKEN_RE = re.compile(r"\bidx0*(\d+)", re.IGNORECASE)
_BARE_NUM_RE = re.compile(r"^0*(\d+)$")


def _wav_idx(stem):
    """Master-directory index parsed from a WAV *stem*, or ``None``."""
    m = _IDX_TOKEN_RE.search(stem)
    if m:
        return int(m.group(1))
    m = _BARE_NUM_RE.match(stem)
    return int(m.group(1)) if m else None


# Per-song music-bank WAVs (image-scNN.bin banks). EXTRACT-ONLY: Write re-encodes
# only the cat-0 sounds (idxNNNN.wav) back into image.bin — music_catNN_* live in
# separate image-scNN.bin banks Write doesn't patch.  The prefix survives an
# Auto-transcribe / Music-ID rename ("music_cat01_0001 - Battery.wav"), so it's
# the stable per-song key.
_MUSIC_WAV_RE = re.compile(r"(music_cat\d+_\d+)", re.IGNORECASE)


# --------------------------------------------------------------------------
# params cache (fingerprint of game_real + image.bin master-dir region)
# --------------------------------------------------------------------------
# Bump whenever a fix changes the params DERIVED from unchanged card bytes.  The
# fingerprint covers the card only, so without this a cached pickle from the old
# derive keeps being loaded and silently masks the fix.  It lives in the FILE
# NAME rather than in the fingerprint hash so a superseded cache is identifiable
# and can be deleted (see :func:`clear_stale_params_caches`) instead of just
# ignored -- a poisoned pickle nobody reads still costs the user real disk
# (Deadpool Pro 1.16 alone caches ~66 MB).
#   2: the chain replay no longer writes 24 bytes at a pseudo-random address
#      once per record (spike2.emulator._record_write_addr).  Every catalog big
#      enough to take a hit cached wrong codec params -- Deadpool Pro 1.16 had
#      3461 of 8175 sounds decoding to noise.  rev-1 caches are the unsuffixed
#      files written before this scheme existed.
#   3: that write is now allowed ONLY on the record's own slot.  Bounding it to
#      the record array still let a misaligned dart straddle two records and
#      rewrite them: Beatles 1.29 took one during record 66, at slot 419.25,
#      and every one of the 514 records from 419 to the end of its catalog
#      decoded to noise -- 55% of the card (PAD-108).  A rev-2 cache for any
#      card that took such a hit holds those wrong params.
_DERIVE_REV = 4
_REV_TAG = ".r%d" % _DERIVE_REV
# Everything this module keeps in the cache directory, as (current-rev suffix,
# regex matching that file kind at ANY revision including the unsuffixed rev-1).
_CACHE_KINDS = (
    (_REV_TAG + ".pkl",             re.compile(r"^[0-9a-f]{32}(\.r\d+)?\.pkl$")),
    (_REV_TAG + ".consumed.npy",    re.compile(r"^[0-9a-f]{32}(\.r\d+)?\.consumed\.npy$")),
    (_REV_TAG + ".sfxnames4.json",  re.compile(r"^[0-9a-f]{32}(\.r\d+)?\.sfxnames\d+\.json$")),
)


def _fingerprint(game_real_path, image_path):
    """Identify a card's (firmware, sound bank) pair for the params cache.

    The size and the file's TAIL are in here as well as its head, because a
    grown sound bank differs from its stock self in the record array at the end
    of the file and in one header word — and a cache hit across that difference
    would hand a build the wrong table for its own card."""
    h = hashlib.sha256()
    with open(_lp(game_real_path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    size = os.path.getsize(_lp(image_path))
    h.update(struct.pack("<Q", size))
    with open(_lp(image_path), "rb") as f:
        h.update(f.read(0x20000))   # header + master-directory source region
        if size > 0x40000:
            f.seek(-0x20000, 2)
            h.update(f.read(0x20000))     # the record array lives at the end
    return h.hexdigest()


def _params_cache_dir():
    d = os.path.join(tempfile.gettempdir(), "pinball_spike2_params")
    os.makedirs(d, exist_ok=True)
    return d


def _cache_path(fp):
    return os.path.join(_params_cache_dir(), fp[:32] + _REV_TAG + ".pkl")


def _consumed_cache_path(fp):
    """Sibling of the params cache: the master-directory **consumed** body
    offsets (the bytes the firmware's forward-chain decode reads to set each
    sound's codec params).  These are deterministic for a card, so capturing them
    once at Extract lets a later Write's :func:`_restore_masterdir_consumed` skip
    its own full ~2 min re-derive (the integrity assert still runs)."""
    return os.path.join(_params_cache_dir(),
                        fp[:32] + _REV_TAG + ".consumed.npy")


def _is_stale_cache_file(name):
    """True if *name* is one of our cache files from a SUPERSEDED derive.

    Matches only the file kinds this module writes, so anything else that ends
    up in the directory is left alone."""
    for cur, pat in _CACHE_KINDS:
        if pat.match(name):
            return not name.endswith(cur)
    return False


def clear_stale_params_caches():
    """Delete codec-params caches left by a superseded derive.  Returns
    ``(n_files, bytes_freed)``.

    Runs once per process before the cache is first consulted.  Bumping
    ``_DERIVE_REV`` stops a stale cache being *used*, but on its own it strands
    the old files forever: every user who ever extracted a big Spike 2 card
    would keep carrying tens of MB of pickles holding codec params we now know
    are wrong.  Deleting by revision tag is safe under the extract/write process
    fan-out because no live process ever opens a non-current revision."""
    try:
        d = _params_cache_dir()
        names = os.listdir(d)
    except OSError:
        return 0, 0
    n = freed = 0
    for name in names:
        if not _is_stale_cache_file(name):
            continue
        p = os.path.join(d, name)
        try:
            size = os.path.getsize(p)
            os.remove(p)
        except OSError:
            continue
        n += 1
        freed += size
    return n, freed


_stale_caches_cleared = False


def _clear_stale_params_caches_once(log=None):
    global _stale_caches_cleared
    if _stale_caches_cleared:
        return
    _stale_caches_cleared = True
    try:
        n, freed = clear_stale_params_caches()
    except Exception:
        return
    if n and log:
        log("Removed %d superseded codec-parameter cache file(s) (%.0f MB) "
            "left by an earlier version." % (n, freed / 1e6), "info")


def _install_consumed_hook(emu):
    """Install a read-only whole-body ``MEM_READ`` hook that records every
    master-directory-consumed body offset during a ``derive_params`` pass.
    Returns ``(reads_set, hook_handle)``; the caller must ``mu.hook_del`` the
    handle after the derive so it doesn't slow a later decode.  Read hooks don't
    change emulation and profiling showed ~0 added derive time.  Records each
    byte of a multi-byte read (matching :func:`_restore_masterdir_consumed`)."""
    from unicorn import UC_HOOK_MEM_READ

    from .spike2 import emulator as EM
    base = EM.DESC_BASE
    size = emu.imgsize
    reads = set()

    def on_read(mu, access, addr, sz, value, ud):
        o = addr - base
        for k in range(sz):
            oo = o + k
            if 0 <= oo < size:
                reads.add(oo)
    hh = emu.mu.hook_add(UC_HOOK_MEM_READ, on_read, begin=base, end=base + size)
    return reads, hh


def _save_consumed(fp, reads):
    """Persist the consumed-offset set as a sorted int64 array (np.save)."""
    try:
        import numpy as np
        np.save(_consumed_cache_path(fp),
                np.array(sorted(reads), dtype=np.int64))
    except Exception:
        pass


def _save_grown_consumed(gr_path, staged, reads, log):
    """File the consumed map :func:`_derive_grown` captured under the STAGED
    bank's fingerprint, so :func:`_restore_masterdir_consumed` finds it.

    Best effort like every other cache write here: a cache that cannot be
    written costs the next build a cold derive, never the build itself.
    ``reads`` is ``None`` when the derive could not install its hook, and an
    empty map is not filed either (the cached path treats it as a miss)."""
    if not reads:
        return
    try:
        _save_consumed(_fingerprint(gr_path, staged), reads)
    except Exception as e:                                  # noqa: BLE001
        log("The grown bank's master-directory map could not be kept for "
            "the next build (%s); it will be derived again then." % e, "info")


def _load_consumed(game_real_path, image_path):
    """Sorted consumed-offset array for this card, or ``None`` if not cached."""
    path = _consumed_cache_path(_fingerprint(game_real_path, image_path))
    if not os.path.exists(path):
        return None
    try:
        import numpy as np
        return np.load(path)
    except Exception:
        return None


def _note_cold_consumed(log):
    """Say, once per derive, why a Write is about to spend minutes in the
    emulator.

    The consumed-read map is written at Extract time into ``%TEMP%`` and keyed by
    a fingerprint of the card, NOT by the project folder -- so it goes away when
    the temp dir is cleaned, and it is deleted deliberately when an older
    version's caches are swept (see :func:`clear_stale_params_caches`).  A Write
    that misses it re-derives the whole record chain, which on a big catalog is
    minutes with nothing on screen but a stationary bar.

    A tester worked out empirically that "the version used to decrypt must be the
    version that writes the card", and read the difference as the app freezing
    (a tester, 2026-08-01).  That rule is really "the cache must still be there",
    and the cost is time, not correctness -- but neither of those was sayable
    from the outside, because this path logged nothing at all."""
    if log:
        log("No cached master-directory read map for this card, so it has to be "
            "re-derived from the firmware before the sounds can be written. "
            "This is the slow part of a Write (minutes on a big sound catalog) "
            "and it happens when the card was extracted by a different version "
            "of the app, or the temporary cache has since been cleaned up. "
            "Nothing is wrong; extracting and writing on the same version, in "
            "one sitting, skips it.", "info")


def _load_or_derive_params(emu, game_real_path, image_path, log, progress):
    _clear_stale_params_caches_once(log)
    fp = _fingerprint(game_real_path, image_path)
    cache = _cache_path(fp)
    if os.path.exists(cache):
        try:
            params = pickle.load(open(cache, "rb"))
            # Re-derive a pre-SFX-naming cache (no ``key0``) so the container-key
            # snapshot the name mapping needs is present; harmless for decode.
            if params and "key0" in params[0]:
                log("Loaded cached codec parameters (%d sounds)."
                    % len(params), "info")
                return params
        except Exception:
            pass
    # No fixed time estimate: the derive is a strictly sequential walk of the
    # card's sound catalog, so it scales with catalog size -- seconds for a
    # small title, ~19 min for Deadpool Pro 1.16's 8175 sounds.  The old
    # "~2-5 min" promise was the shape of the field report that opened PAD-2:
    # a user watched an unmoving progress bar past the stated time and
    # reasonably concluded it had hung.  derive_params reports per-record
    # progress below as soon as it knows the count.
    log("Deriving codec parameters from the firmware (one-time per card; "
        "large sound catalogs take several minutes)...", "info")
    if progress:
        progress(0, 0, "Deriving codec parameters...")
    # Capture the master-directory consumed body offsets in the SAME derive
    # (free: a read-only hook, ~0 added time) so a later Write's
    # _restore_masterdir_consumed can skip its own full re-derive.
    reads = hh = None
    try:
        reads, hh = _install_consumed_hook(emu)
    except Exception:
        reads = hh = None
    params = emu.derive_params(progress=progress)
    if hh is not None:
        try:
            emu.mu.hook_del(hh)
        except Exception:
            pass
    # A card whose sound bank was grown carries a retired record beside each
    # appended one.  Report only the sounds the game will play, under the
    # numbers they have always had, so a re-extract names the LIVE body
    # idxN.wav and a later edit of that file encodes into the body that plays.
    from .spike2.emulator import collapse_shadowed
    params = collapse_shadowed(params)
    try:
        pickle.dump(params, open(cache, "wb"))
    except Exception:
        pass
    if reads:
        _save_consumed(fp, reads)
    log("Derived parameters for %d sounds." % len(params), "success")
    return params


def _save_firmware_for_support(gr_path, output_dir, log):
    """Copy the extracted firmware ELF next to the output so a user who hits an
    unmappable build can hand it to the developer for a locator fix (the work
    dir the firmware lives in is deleted when the extract returns).  Returns the
    saved path, or ``None`` if the copy couldn't be made."""
    import shutil
    try:
        dst = os.path.join(output_dir, "firmware_game_real.bin")
        shutil.copyfile(gr_path, dst)
        return dst
    except Exception as e:
        log("Could not save a copy of the firmware for support (%s)." % e,
            "info")
        return None


# --------------------------------------------------------------------------
# locating + extracting the card's game_real / image.bin
# --------------------------------------------------------------------------
def _locate(disk_f, partitions):
    """Find the Spike 2 game directory (the one holding ``image.bin``) and its
    firmware ELF across the card's ext partitions (largest first).  Returns
    ``(reader, firmware_inode, image_inode)``.

    On the card the firmware binary is the ``game`` ELF sitting next to
    ``image.bin`` (with a top-level ``game`` *symlink* the locator skips by
    validating the ELF magic)."""
    from .ext4 import Ext4Reader
    img_only = None
    for off, size in partitions:
        try:
            r = Ext4Reader(disk_f, off, size)
        except Exception:
            continue
        img_ino, fw_ino = r.find_spike_assets()
        if img_ino is not None and fw_ino is not None:
            return r, r.read_inode(fw_ino), r.read_inode(img_ino)
        if img_ino is not None and img_only is None:
            img_only = (r, r.read_inode(img_ino))
    if img_only is not None:
        raise FileNotFoundError(
            "Found image.bin but not the game firmware ELF next to it on the "
            "card.")
    raise FileNotFoundError(
        "Could not find image.bin (with its game firmware) on the card.")


def _extract_inputs(disk_f, partitions, work_dir, log, read_progress=None):
    """Extract the firmware ELF + ``image.bin`` from the (already-open) card to
    ``work_dir``.  Returns ``(game_real_path, image_bin_path, reader, fw_node,
    img_node)``.  The caller owns ``disk_f`` and must keep it open as long as it
    uses ``reader`` (e.g. for video extraction or in-place patching), then close
    it.  ``read_progress`` (if given) is called ``(cur, total)`` while streaming
    image.bin."""
    reader, fw_node, img_node = _locate(disk_f, partitions)
    gr_path = os.path.join(work_dir, "game_real")
    img_path = os.path.join(work_dir, "image.bin")
    log("Extracting firmware (%.1f MB)..." % (fw_node["size"] / 1e6), "info")
    reader.extract_file(fw_node, gr_path)
    log("Extracting image.bin (%.0f MB)..." % (img_node["size"] / 1e6), "info")
    reader.extract_file(img_node, img_path, progress=read_progress)
    return gr_path, img_path, reader, fw_node, img_node


_ASSET_REF = re.compile(rb"\d+\.asset/\d+\.asset")
_IDENT = re.compile(rb"[A-Za-z][A-Za-z0-9_]{2,80}")
_RADIUM_SKIP = {"Video", "video", "in_game_videos"}

# A radium video record is
#   <u64 len><name><u32 id><u64 len><N.asset/M.asset>
# so the name always ends exactly 12 bytes before the reference it names.
_RADIUM_NAME_GAP = 4 + 8
_RADIUM_NAME_MAX = 96


def _radium_name_before(data, end):
    """The length-prefixed scene-element name ending at *end*, or ``None``.

    Strings in a ``scene.radium`` carry a ``u64`` length prefix (the same
    framing :func:`_nearest_element_name` reads for images), so the name is
    recovered by finding the ``ln`` whose prefix sits exactly ``ln + 8`` bytes
    back.  Scanning *forward* from ``ln = 1`` can't match early: a shorter
    candidate would have to read its prefix out of the name's own bytes, and a
    small ``u64`` needs seven zero bytes that printable text never has.
    """
    for ln in range(1, _RADIUM_NAME_MAX + 1):
        p = end - ln - 8
        if p < 0:
            break
        if struct.unpack_from("<Q", data, p)[0] != ln:
            continue
        body = data[end - ln:end]
        if all(32 <= b < 127 for b in body):
            return body.decode("latin1")
    return None


def _parse_radium(data):
    """Map ``asset_ref -> name`` from a ``scene.radium``: each LCD video asset is
    named by the scene element that references it.

    The name is read from its ``u64`` length prefix.  Trusting the nearest
    identifier *text* instead used to append a stray character, because the
    ``u32`` id between the name and the reference is ``0x800000nn`` and its low
    byte is usually ASCII -- ``GodzillaVsMegalon_Award1`` came out as
    ``GodzillaVsMegalon_Award1i``, and a run of clips picked up ``c, d, e, f
    ...`` as the id counted up.  Falls back to the identifier scan for any
    reference that isn't framed this way.
    """
    import bisect
    names = name_offs = None
    out = {}
    for m in _ASSET_REF.finditer(data):
        ref = m.group().decode()
        if ref in out:
            continue
        nm = _radium_name_before(data, m.start() - _RADIUM_NAME_GAP)
        if nm and nm not in _RADIUM_SKIP and ".asset" not in nm:
            out[ref] = nm
            continue
        if names is None:      # unframed record -- pay for the scan once
            names = [(x.start(), x.group().decode("latin1"))
                     for x in _IDENT.finditer(data)]
            name_offs = [p for p, _ in names]
        j = bisect.bisect_left(name_offs, m.start()) - 1
        while j >= 0:
            nm = names[j][1]
            if nm not in _RADIUM_SKIP and ".asset" not in nm:
                out[ref] = nm
                break
            j -= 1
    return out


def _sanitize_title(name, maxlen=64):
    keep = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name).strip("_")
    return keep[:maxlen] or "video"


def _work_dir(label=None, base="spike2_"):
    """Create a uniquely-named scratch dir under the temp dir for a run.

    Mirrors ``tempfile.mkdtemp``'s role (a fresh, unique dir) but folds the
    game title into the name as ``spike2_<title>_<hex8>`` so that if the
    process is hard-killed mid-run (the ``finally`` cleanup never runs) the
    leftover is attributable to a game in the "Manage disk space" view
    (:mod:`core.host_temp`).  The tag is hex (no underscores) so the title
    parses back out cleanly.  ``label`` omitted -> bare ``spike2_<hex8>``.
    """
    import uuid
    safe = ""
    if label:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", label).strip("._-")[:48]
    for _ in range(8):
        tag = uuid.uuid4().hex[:8]
        name = f"{base}{safe}_{tag}" if safe else f"{base}{tag}"
        path = os.path.join(tempfile.gettempdir(), name)
        try:
            os.makedirs(path)
            return path
        except FileExistsError:
            continue
    return tempfile.mkdtemp(prefix=base)  # astronomically unlikely fallback


def _read_video_manifest(vid_dir):
    """``{output filename: card path}`` from a previous extract's
    ``video/manifest.txt``, or ``{}`` when there isn't one."""
    out = {}
    try:
        with open(os.path.join(vid_dir, "manifest.txt"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                cols = line.rstrip("\n").split("\t")
                if len(cols) >= 2 and cols[0]:
                    out[cols[0]] = cols[1]
    except OSError:
        pass
    return out


def _remove_renamed_video_twins(vid_dir, prev, written, log=None):
    """Delete a previous extract's copy of a clip this run wrote under a new
    name.

    Clip names come from the card's scene data, so they move when the title's
    firmware changes -- and once, for every card, when the naming itself is
    corrected.  The re-extract writes the new name and the old file just sits
    there: two files for one clip, no ``manifest.txt`` row for the stale one,
    and the same GUI clutter / Write-mapping hazard
    :func:`_remove_renamed_audio_twins` exists to prevent.

    Only files this tool itself recorded in the old manifest are considered,
    and only when this run wrote the same card path under a different name --
    so anything the user put in the folder is left alone.
    """
    removed = 0
    for old_name, card_path in prev.items():
        new_name = written.get(card_path)
        if not new_name or new_name == old_name:
            continue
        try:
            os.remove(os.path.join(vid_dir, old_name))
            removed += 1
        except OSError:
            pass
    if removed and log:
        log("Removed %d video(s) a previous extract had saved under a "
            "different name." % removed, "info")
    return removed


def find_card_videos(reader, cancel=None):
    """One filesystem pass -> ``([(path, node, brand), ...], {dir: radium node})``.

    Spike 2 stores LCD videos verbatim as ``.asset`` files, so there is no name
    or extension to go on: the sniff is the 12-byte ``ftyp`` magic, which
    catches them whatever they are called.  The ``scene.radium`` inodes come
    back from the same walk because they are what names the clips
    (:func:`video_titler`), and walking the tree twice for them would double
    the cost of every caller.
    """
    cancel = cancel or (lambda: False)
    vids = []
    radiums = {}   # hash-dir path -> scene.radium inode
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            break
        if path.endswith("/scene.radium"):
            radiums[path[:-len("/scene.radium")]] = node
        elif node["size"] >= 0x1000:
            b = reader.peek(node, 12)
            if len(b) >= 12 and b[4:8] == b"ftyp":
                vids.append((path, node, b[8:12]))
    return vids, radiums


def video_titler(reader, radiums):
    """A ``card path -> clip name`` lookup, parsing each ``scene.radium`` at
    most once (they are megabytes and several hundred clips share one)."""
    radium_cache = {}

    def _title_for(path):
        if "/scene.assets/" not in path:
            return None
        hashdir, ref = path.rsplit("/scene.assets/", 1)
        rn = radiums.get(hashdir)
        if rn is None:
            return None
        if hashdir not in radium_cache:
            try:
                radium_cache[hashdir] = (_parse_radium(reader.read_file_bytes(rn))
                                         if rn["size"] <= 0x2000000 else {})
            except Exception:
                radium_cache[hashdir] = {}
        return radium_cache[hashdir].get(ref)

    return _title_for


def extract_videos(reader, output_dir, log=None, progress=None, cancel=None):
    """Extract every directly-stored video (H.264 in an MP4/QuickTime ``ftyp``
    container) from the card's asset tree to ``output_dir/video/``.

    Spike 2 stores LCD videos verbatim as ``.asset`` files; this sniffs the
    ``ftyp`` magic so it catches them regardless of name/extension, and names
    each one from its scene's ``scene.radium`` (e.g. ``Cowabunga_Background``).
    A ``manifest.txt`` records each output name -> original card path."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    log("Scanning for video assets...", "info")
    vids, radiums = find_card_videos(reader, cancel)
    if cancel():
        return 0
    if not vids:
        log("No video assets found.", "info")
        return 0

    _title_for = video_titler(reader, radiums)

    vid_dir = os.path.join(output_dir, "video")
    os.makedirs(vid_dir, exist_ok=True)
    prev = _read_video_manifest(vid_dir)
    log("Extracting %d video(s)..." % len(vids), "info")
    manifest = []
    written = {}       # card path -> output filename this run
    used = {}
    named = 0
    for i, (path, node, brand) in enumerate(vids):
        if cancel():
            break
        if progress:
            progress(i, len(vids), "Extracting video %d/%d" % (i + 1, len(vids)))
        ext = ".mov" if brand == b"qt  " else ".mp4"
        title = _title_for(path)
        base = _sanitize_title(title) if title else ("video_%04d" % (i + 1))
        if title:
            named += 1
        k = used.get(base, 0)
        used[base] = k + 1
        fname = (base if k == 0 else "%s_%d" % (base, k + 1)) + ext
        reader.extract_file(node, os.path.join(vid_dir, fname))
        manifest.append("%s\t%s\t%d" % (fname, path, node["size"]))
        written[path] = fname
    try:
        with open(os.path.join(vid_dir, "manifest.txt"), "w", encoding="utf-8") as f:
            f.write("# output\tcard path\tbytes\n" + "\n".join(manifest) + "\n")
    except Exception:
        pass
    _remove_renamed_video_twins(vid_dir, prev, written, log)
    log("Extracted %d video(s) to %s (%d named from scene data)."
        % (len(manifest), vid_dir, named), "success")
    return len(manifest)


def scan_video_quality(reader, log=None, progress=None, cancel=None):
    """Measure every clip already on the card -> ``[core.video_quality.ClipQuality]``.

    The same discovery and naming as :func:`extract_videos`, but nothing is
    written and no clip is read whole: each one's ``moov`` is picked out of the
    middle of the ``.asset`` through :meth:`ext4.Ext4Reader.read_range`, which
    is why a 658-clip card answers in seconds instead of the minute an extract
    of several GB of video takes.

    This is the after-the-fact form of the Write-time "it will look very
    blocky" warning: it tells a user which clips on a FINISHED card are below
    that bar, long after the log that would have said so has gone.
    """
    from ...core import video_quality

    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    log("Scanning for video assets...", "info")
    vids, radiums = find_card_videos(reader, cancel)
    if cancel() or not vids:
        if not vids:
            log("No video assets found on this card.", "info")
        return []

    _title_for = video_titler(reader, radiums)
    log("Measuring %d clip(s)..." % len(vids), "info")
    used = {}
    clips = []
    for i, (path, node, brand) in enumerate(vids):
        if cancel():
            break
        if progress:
            progress(i, len(vids), "Checking clip %d/%d" % (i + 1, len(vids)))
        # Same naming rule as the extract, so a row in this report and a file
        # in the user's video/ folder are recognisably the same clip.
        ext = ".mov" if brand == b"qt  " else ".mp4"
        title = _title_for(path)
        base = _sanitize_title(title) if title else ("video_%04d" % (i + 1))
        k = used.get(base, 0)
        used[base] = k + 1
        name = (base if k == 0 else "%s_%d" % (base, k + 1)) + ext

        clips.append(video_quality.read_clip_quality(
            lambda off, n, _nd=node: reader.read_range(_nd, off, n),
            node["size"], name=name, card_path=path))

    total, blocky, squeezed, _both, bad = video_quality.summarize(clips)
    log("Checked %d clip(s): %d below the quality bar, %d squeezed into their "
        "slot by a Write%s."
        % (total, blocky, squeezed,
           (", %d unreadable" % bad) if bad else ""),
        "warning" if blocky else "success")
    return clips


def card_video_quality(image_path, log=None, progress=None, cancel=None):
    """:func:`scan_video_quality` for a card image file on disk.

    The games partition is picked by :func:`_locate` — the same
    ``image.bin``-next-to-the-firmware test the Extract uses — so the report
    reads the clips off exactly the partition a Write put them on (on a
    multi-image card, game 1: see the Multi-boot tab's own note).
    """
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    with open(_lp(image_path), "rb") as disk_f:
        reader, _fw_node, _img_node = _locate(disk_f,
                                              _linux_partitions(image_path))
        return scan_video_quality(reader, log, progress, cancel)


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".webp")


def extract_images(reader, output_dir, log=None, progress=None, cancel=None):
    """Extract every loose image file from the card's asset tree to
    ``output_dir/images/``, preserving the card's directory structure (so names
    stay unique and grouped, e.g. ``images/<game>/assets/.../Login/Avatar.png``).

    Spike 2 stores LCD UI images as plain ``.png`` files on the ext4 filesystem
    (not packed inside ``.asset``), so they extract — and later patch back — like
    any loose file.  A ``manifest.txt`` records each output path -> original card
    path so Write can map an edited image back to its inode."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    log("Scanning for image assets...", "info")
    imgs = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.lower().endswith(_IMAGE_EXTS):
            imgs.append((path, node))
    if not imgs:
        log("No image assets found.", "info")
        return 0

    img_dir = os.path.join(output_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    log("Extracting %d image(s)..." % len(imgs), "info")
    manifest = []
    for i, (path, node) in enumerate(imgs):
        if cancel():
            break
        if progress:
            progress(i, len(imgs), "Extracting image %d/%d" % (i + 1, len(imgs)))
        rel = path.lstrip("/")                       # card path without leading /
        out_path = os.path.join(img_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        reader.extract_file(node, out_path)
        manifest.append("%s\t%s\t%d" % (rel, path, node["size"]))
    try:
        with open(os.path.join(img_dir, "manifest.txt"), "w",
                  encoding="utf-8") as f:
            f.write("# output\tcard path\tbytes\n" + "\n".join(manifest) + "\n")
    except Exception:
        pass
    log("Extracted %d image(s) to %s." % (len(manifest), img_dir), "success")
    return len(manifest)


# --------------------------------------------------------------------------
# The boot screen: the picture the machine shows while it starts up.  Every
# other image is on the games partition; this one is on the OS partition
# (sda2), where /etc/init.d/lvds_panel starts /usr/local/bin/boot_display and
# it draws /usr/local/spike/SternLogo.png until the game script kills it.  It
# extracts to images/boot_screen/ with a manifest of its own, so Write knows
# which partition to put it back on (PAD-147).
# --------------------------------------------------------------------------
_BOOT_IMAGE_DIR = "usr/local/spike"
_BOOT_IMAGE_SUBDIR = "boot_screen"


def _boot_screen_dir(disk_f, partitions, games_base=None):
    """``(reader, dir_inode)`` for ``/usr/local/spike`` on the card's OS
    partition, or ``(None, None)`` when no partition has one.

    Every ext partition but the games one (*games_base*, its byte offset) is
    tried in turn; on a Spike 2 card only the rootfs holds that folder."""
    from .ext4 import S_IFDIR, S_IFMT, Ext4Reader
    for off, size in partitions:
        if games_base is not None and off == games_base:
            continue
        try:
            reader = Ext4Reader(disk_f, off, size)
            node = reader.read_inode(2)
            for name in _BOOT_IMAGE_DIR.split("/"):
                child = next((c for n, c, _t in reader._iter_dir(node)
                              if n == name), None)
                if child is None:
                    break
                node = reader.read_inode(child)
                if (node["mode"] & S_IFMT) != S_IFDIR:
                    break
            else:
                return reader, node
        except Exception:
            continue
    return None, None


def _boot_images(reader, dir_node):
    """``[(card_path, inode), ...]`` for the image files directly inside the
    boot screen's folder, sorted by name."""
    from .ext4 import S_IFMT, S_IFREG
    out = []
    for name, child, _t in reader._iter_dir(dir_node):
        if name in (".", "..") or not name.lower().endswith(_IMAGE_EXTS):
            continue
        try:
            node = reader.read_inode(child)
        except Exception:
            continue
        if (node["mode"] & S_IFMT) == S_IFREG and node["size"] > 0:
            out.append(("/%s/%s" % (_BOOT_IMAGE_DIR, name), node))
    out.sort(key=lambda e: e[0].lower())
    return out


def extract_boot_images(disk_f, partitions, output_dir, games_base=None,
                        log=None):
    """Extract the boot screen off the OS partition to
    ``output_dir/images/boot_screen/``, with a ``manifest.txt`` in the loose
    images' shape (output, card path, bytes).  Returns how many; 0 on a card
    whose OS partition has none."""
    log = log or (lambda *a, **k: None)
    reader, dir_node = _boot_screen_dir(disk_f, partitions, games_base)
    imgs = _boot_images(reader, dir_node) if reader is not None else []
    if not imgs:
        log("No boot screen image found on the OS partition.", "info")
        return 0
    out_dir = os.path.join(output_dir, "images", _BOOT_IMAGE_SUBDIR)
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    for card_path, node in imgs:
        name = card_path.rsplit("/", 1)[1]
        reader.extract_file(node, os.path.join(out_dir, name))
        manifest.append("%s/%s\t%s\t%d"
                        % (_BOOT_IMAGE_SUBDIR, name, card_path, node["size"]))
    with open(os.path.join(out_dir, "manifest.txt"), "w",
              encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\n" + "\n".join(manifest) + "\n")
    log("Extracted the boot screen (%s) from the OS partition to %s."
        % (", ".join(c.rsplit("/", 1)[1] for c, _n in imgs), out_dir),
        "success")
    return len(manifest)


# --------------------------------------------------------------------------
# Scene-texture extract: the BC3/DXT5 "DDS" glyph/sprite atlases packed as the
# non-ftyp scene.assets/<N>.asset files (their dims live in the scene.radium).
# --------------------------------------------------------------------------
_TEXTURE_MANIFEST = "manifest.txt"
_TEXTURE_DIR = ("images", "scene_textures")
_DXT5_FORMAT = 5            # the radium texture-descriptor format enum for BC3
_DXT1_FORMAT = 4            # the radium texture-descriptor format enum for BC1


def parse_texture_descriptor(radium, ref):
    """Read ``(width, height, format)`` for a ``<N>.asset`` scene texture from its
    inline descriptor in the co-located ``scene.radium``, or ``None``.

    Each texture reference is serialized as
    ``[handle u32 (top byte 0x80)][width u32][height u32][format u32]
    [next-handle u32][len u64][name ascii]`` — so the 16 bytes before the name's
    8-byte length prefix are ``width, height, format, handle``.  We key off the
    handle's ``0x80`` top byte (the same framing :mod:`.radium` uses for named
    handles) to avoid matching a stray ``N.asset`` substring."""
    key = struct.pack("<Q", len(ref)) + ref.encode("latin1")
    i = radium.find(key)
    while i >= 0:
        if i >= 16 and radium[i - 1] == 0x80:
            w, h, fmt = struct.unpack_from("<III", radium, i - 16)
            if 0 < w <= 8192 and 0 < h <= 8192:
                return w, h, fmt
        i = radium.find(key, i + 1)
    return None


def extract_scene_textures(reader, output_dir, log=None, progress=None,
                           cancel=None):
    """Decode every BC3/DXT5 or BC1/DXT1 scene texture to
    ``output_dir/images/scene_textures/`` as RGBA PNG.

    These are the single (non-nested, non-``ftyp``) ``scene.assets/<N>.asset``
    files — raw BC3 (``format==5``) or BC1 (``format==4``) block data whose
    width/height/format are read from the co-located ``scene.radium``
    (:func:`parse_texture_descriptor`).  A
    ``manifest.txt`` records ``output -> card path, bytes, w, h, format`` so Write
    can re-encode an edited PNG back to the exact original slot."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    from . import dds as _dds
    try:
        from PIL import Image
    except Exception:
        log("Pillow not available; scene-texture extraction skipped.", "warning")
        return 0
    log("Scanning for scene textures...", "info")
    textures = []                  # (card_path, node, ref)
    radiums = {}                   # scene_dir -> scene.radium node
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.endswith("/scene.radium"):
            radiums[path[:-len("/scene.radium")]] = node
        elif "/scene.assets/" in path and path.endswith(".asset"):
            ref = path.rsplit("/scene.assets/", 1)[1]
            if "/" in ref or node["size"] < 16:
                continue           # nested N.asset/M.asset = video, not a texture
            b = reader.peek(node, 8)
            if len(b) >= 8 and b[4:8] == b"ftyp":
                continue
            textures.append((path, node, ref))
    if not textures:
        log("No scene textures found.", "info")
        return 0

    tex_dir = os.path.join(output_dir, *_TEXTURE_DIR)
    os.makedirs(tex_dir, exist_ok=True)
    radium_cache = {}

    def _descriptor(path, ref):
        scene_dir = path.rsplit("/scene.assets/", 1)[0]
        rn = radiums.get(scene_dir)
        if rn is None:
            return None
        if scene_dir not in radium_cache:
            try:
                radium_cache[scene_dir] = (reader.read_file_bytes(rn)
                                           if rn["size"] <= 0x4000000 else b"")
            except Exception:
                radium_cache[scene_dir] = b""
        return parse_texture_descriptor(radium_cache[scene_dir], ref)

    log("Extracting %d scene texture(s)..." % len(textures), "info")
    manifest = []
    used = {}
    n_ok = n_skip = 0
    for i, (path, node, ref) in enumerate(textures):
        if cancel():
            break
        if progress:
            progress(i, len(textures),
                     "Texture %d/%d" % (i + 1, len(textures)))
        desc = _descriptor(path, ref)
        if desc is None:
            n_skip += 1
            continue
        w, h, fmt = desc
        size = node["size"]
        # BC3/DXT5 (16 B/4×4 block) and BC1/DXT1 (8 B/4×4 block) are supported.
        # The block-padded size is the exact, dimension-correct law (a texture
        # whose W/H aren't multiples of 4 still occupies whole 4×4 blocks); it
        # doubles as a guard that the descriptor really belongs to this asset.
        nblk = ((w + 3) // 4) * ((h + 3) // 4)
        if fmt == _DXT5_FORMAT and size == nblk * 16:
            decode = _dds.decode_bc3
        elif fmt == _DXT1_FORMAT and size == nblk * 8:
            decode = _dds.decode_bc1
        else:
            n_skip += 1
            continue
        try:
            rgba = decode(reader.read_file_bytes(node), w, h)
            im = Image.fromarray(rgba, "RGBA")
        except Exception as e:
            log("Texture %s: decode failed (%s); skipped." % (ref, e), "warning")
            n_skip += 1
            continue
        # Name by scene dir (groups a scene's textures together) + the asset
        # ref + W×H.  The dims match the radium-embedded-image convention below
        # so a scene's large "main" texture and its smaller child glyphs are
        # distinguishable at a glance and matchable by resolution in a file
        # browser — the manual workflow a tester was forced into.
        scene8 = path.rsplit("/scene.assets/", 1)[0].rsplit("/", 1)[1][:8]
        base = "%s_%s_%dx%d" % (scene8, os.path.splitext(ref)[0], w, h)
        k = used.get(base, 0)
        used[base] = k + 1
        name = base if k == 0 else "%s_%d" % (base, k + 1)
        out_rel = "scene_textures/%s.png" % name
        im.save(_lp(os.path.join(output_dir, "images",
                                 *out_rel.split("/"))))
        manifest.append("%s\t%s\t%d\t%d\t%d\t%d"
                        % (out_rel, path, size, w, h, fmt))
        n_ok += 1
    try:
        with open(os.path.join(tex_dir, _TEXTURE_MANIFEST), "w",
                  encoding="utf-8") as f:
            f.write("# output\tcard path\tbytes\twidth\theight\tformat\n"
                    + "\n".join(manifest) + "\n")
    except Exception:
        pass
    log("Extracted %d scene texture(s) to %s (%d skipped)."
        % (n_ok, tex_dir, n_skip), "success")
    return n_ok


# --------------------------------------------------------------------------
# Radium-embedded images: the BC3/DXT5 "display-system" bitmaps stored INLINE
# in a scene.radium (the song-title text glyphs like "ROCK AND ROLL" shown
# under a scene) — not a scene.assets file.  Same codec, patched in place.
# --------------------------------------------------------------------------
_RADIUM_IMAGE_MANIFEST = "radium_images.txt"
# Per-glyph slices of the font atlases above: one PNG per character under
# scene_textures/glyphs/<atlas stem>/, plus a manifest mapping each slice back
# to its atlas PNG + pixel rectangle (see radium.parse_glyph_tables).
_GLYPH_MANIFEST = "glyph_images.txt"
_GLYPH_DIR = "glyphs"
# Optional opt-out from the all-occurrences rule: rows of "atlas_rel <TAB>
# radium card path" naming the ONLY scenes an atlas's edits may land in (the
# Fonts window writes it; see fontrender.SCOPE_MANIFEST).  Absent = every
# occurrence, which stays the default.
_GLYPH_SCOPE_MANIFEST = "glyph_scope.txt"
# Static scene layouts (positions/strings/colors per scene.radium) recorded at
# extract so the Scenes window can composite a preview from the CURRENT PNGs.
_SCENE_LAYOUT_MANIFEST = "scene_layout.json"


def _glyph_png_name(char):
    """Filename for a glyph slice: codepoint first (unique even on Windows'
    case-insensitive filesystems where A.png == a.png), readable char after."""
    c = chr(char)
    if c.isascii() and c.isalnum():
        return "U+%04X_%s.png" % (char, c)
    return "U+%04X.png" % char

# Scene-graph element-TYPE keywords — skipped when naming an image after its
# nearest scene element (we want the instance id like "Song_Progress", not the
# generic type tag that precedes it).
_RADIUM_ELEM_TYPES = {"Bitmap", "Sprite", "Animation", "Font", "Pattern",
                      "Group", "Node", "Scene", "Mask", "Particle", "Text",
                      "Video", "VideoSurface", "Material", "Shader"}
_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]+$")


def _padded4(x):
    return ((x + 3) // 4) * 4


def _nearest_element_name(data, before_off, window=512):
    """The nearest scene-element instance id (e.g. ``Song_Progress``,
    ``unnamed_instance_4``) appearing as a length-prefixed string just before
    *before_off*, skipping element-TYPE keywords.  ``""`` when none — used to
    give each radium image an organizing name rather than a bare hash."""
    lo = max(0, before_off - window)
    best = ""
    i = lo
    while i + 8 <= before_off:
        ln = struct.unpack_from("<Q", data, i)[0]
        if 1 <= ln <= 64 and i + 8 + ln <= before_off:
            body = data[i + 8:i + 8 + ln]
            if all(32 <= b < 127 for b in body):
                s = body.decode("latin1")
                if s not in _RADIUM_ELEM_TYPES and _IDENT_RE.match(s):
                    best = s            # keep the last (nearest) match
                i += 8 + ln
                continue
        i += 1
    return best


def parse_radium_images(data):
    """Find every inline BC3/DXT5 or BC1/DXT1 image in a ``scene.radium``.

    Each image is serialized as
    ``[dispW u32][dispH u32][handle u32][texW u32][texH u32][format u32]
    [0 u32][0 u32][length u32][block data]`` where
    ``length == padded4(texW) * padded4(texH)`` for BC3 (``format==5``,
    1 byte/pixel) or half that for BC1 (``format==4``, 1/2 byte/pixel).  We anchor
    on the ``format, 0, 0`` triplet and validate that the length matches the
    block-padded dimensions for that format and that the data fits — a signature
    specific enough to have no false positives.

    Returns ``[{data_off, length, fmt, tex_w, tex_h, pad_w, pad_h, disp_w,
    disp_h}]`` where decoding uses ``pad_w x pad_h`` (the full block grid)."""
    out = []
    n = len(data)
    # fmt enum byte, then "0,0" (the two trailing u32s) -> 12-byte anchor
    sigs = ((_DXT5_FORMAT, b"\x05\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"),
            (_DXT1_FORMAT, b"\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"))
    for fmt, sig in sigs:
        i = data.find(sig)
        while i >= 0:
            m = i
            i = data.find(sig, i + 1)
            if m < 8 or m + 16 > n:
                continue
            tex_w = struct.unpack_from("<I", data, m - 8)[0]
            tex_h = struct.unpack_from("<I", data, m - 4)[0]
            if not (0 < tex_w <= 8192 and 0 < tex_h <= 8192):
                continue
            length = struct.unpack_from("<I", data, m + 12)[0]
            pad_w, pad_h = _padded4(tex_w), _padded4(tex_h)
            want = pad_w * pad_h if fmt == _DXT5_FORMAT else pad_w * pad_h // 2
            if length != want or m + 16 + length > n:
                continue
            disp_w = struct.unpack_from("<I", data, m - 20)[0] if m >= 20 else tex_w
            disp_h = struct.unpack_from("<I", data, m - 16)[0] if m >= 20 else tex_h
            if not (0 < disp_w <= pad_w):
                disp_w = tex_w
            if not (0 < disp_h <= pad_h):
                disp_h = tex_h
            out.append(dict(data_off=m + 16, length=length, fmt=fmt,
                            tex_w=tex_w, tex_h=tex_h, pad_w=pad_w, pad_h=pad_h,
                            disp_w=disp_w, disp_h=disp_h))
    return out


def _scene_layout_entry(lay, off2rel):
    """One ``scene_layout.json`` entry from a parsed layout, or ``None`` when
    nothing drawable survives the translation.

    The parser works in raw image OFFSETS inside the radium; the manifest has
    to name the project folder's PNGs instead, so the preview composites from
    the user's current (possibly replaced) files.  *off2rel* maps this
    radium's image offsets to those rels.  Shared by :func:`extract_radium_images`
    and :func:`rebuild_scene_layouts`, which re-derives layouts on their own —
    a parser change must never mean two translations to keep in step."""
    entry = {"stage": list(lay["stage"]), "partial": lay["partial"],
             "unplaced": lay["unplaced"], "offstage": lay["offstage"],
             "alternates": lay["alternates"],
             # alternative states are KEPT, tagged per element, so the preview
             # can show one at a time instead of drawing the pile
             "states": lay.get("states", 1),
             # the scene's own named screens, in file order
             "groups": list(lay.get("groups") or ()),
             # which corner the coordinates were measured from; kept so
             # a preview can admit when it had to reinterpret them
             "origin": lay["origin"], "scroll": lay.get("scroll", ""),
             "texts": [], "sprites": []}
    for t in lay["texts"]:
        arel = off2rel.get(t["font_atlas_off"])
        entry["texts"].append({
            "name": t["name"], "x": t["x"], "y": t["y"],
            "text": t["text"], "rect": t["rect"], "rgba": t["rgba"],
            "align": t["align"], "slot": t.get("slot"),
            "state": t.get("state", 0), "group": t.get("group"),
            # fontrender's whole-font key = the first atlas's stem
            "font": (os.path.splitext(os.path.basename(arel))[0]
                     if arel else ""),
            # ...and the SIZE that font is drawn at here, because one atlas
            # serves several sizes and the key alone can't say which.
            "font_px": t.get("font_px", 0),
            # an outline under-pass: drawn beneath its fill with the blend
            # that makes black ink visible, and never repainted by a pending
            # text-colour pick (that would delete the border)
            "outline": bool(t.get("outline")),
        })
    for s in lay["sprites"]:
        irel = off2rel.get(s["image_off"])
        if not irel:
            continue
        sp = {"name": s["name"], "x": s["x"], "y": s["y"], "image": irel,
              "slot": s.get("slot"), "state": s.get("state", 0),
              "group": s.get("group")}
        # An animated element carries its frames in play order, so the
        # preview can run them instead of stacking them.
        frames = [off2rel.get(o) for o in s.get("frames") or ()]
        frames = [fr for fr in frames if fr]
        if len(frames) > 1:
            sp["frames"] = frames
        entry["sprites"].append(sp)
    if not entry["texts"] and not entry["sprites"]:
        return None
    return entry


def _write_scene_layouts(tex_dir, layouts, log):
    """Write ``scene_layout.json``.  Returns True on success."""
    import json
    try:
        with open(os.path.join(tex_dir, _SCENE_LAYOUT_MANIFEST), "w",
                  encoding="utf-8") as f:
            json.dump(layouts, f, indent=1, sort_keys=True)
    except OSError as e:
        log("Could not write the scene layouts (%s)." % e, "warning")
        return False
    log("Recorded the layout of %d drawable scene(s) for previews."
        % len(layouts), "info")
    return True


def extract_radium_images(reader, output_dir, log=None, progress=None,
                          cancel=None):
    """Decode every inline DXT5 image from the card's ``scene.radium`` files to
    ``output_dir/images/scene_textures/`` as RGBA PNG (full padded grid, so a
    re-encode is byte-for-byte size-neutral).

    The SAME image is drawn from many scenes/keyframes, so images are
    **deduplicated by content** — one PNG per unique image — while the
    ``radium_images.txt`` manifest records **every** on-card occurrence (a row
    per ``radium card path + data offset``).  Editing one PNG therefore patches
    all of its occurrences at Write, so the change shows everywhere in-game (the
    same all-occurrences rule the display-text replace uses).

    Font atlases are additionally **sliced into per-character PNGs** under
    ``scene_textures/glyphs/<atlas stem>/U+0041_A.png`` (rects from the scene's
    Font glyph tables — see :func:`radium.parse_glyph_tables`), so a user edits
    a single character instead of hand-measuring the atlas.  ``glyph_images.txt``
    maps each slice back to its atlas PNG + pixel rectangle; at Write, changed
    slices are pasted into their atlas before the normal atlas re-encode."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    from . import dds as _dds
    from . import radium as _radium
    from . import scene_layout as _scene_layout
    from ...core.checksums import md5_file  # noqa: F401  (kept for parity)
    import hashlib
    try:
        from PIL import Image
    except Exception:
        log("Pillow not available; radium-image extraction skipped.", "warning")
        return 0
    log("Scanning radium scenes for embedded images...", "info")
    radiums = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.endswith(_RADIUM_EXT) and node["size"] >= 32:
            radiums.append((path, node))
    if not radiums:
        return 0

    tex_dir = os.path.join(output_dir, *_TEXTURE_DIR)
    os.makedirs(tex_dir, exist_ok=True)
    manifest = []                 # one row per occurrence
    by_hash = {}                  # content hash -> output rel path (PNG written once)
    layouts = {}                  # radium card path -> static layout
    glyph_manifest = []           # one row per unique glyph slice
    sliced_atlases = set()        # atlas out_rel already sliced (content-deduped)
    glyph_rows = set()            # (table key, glyph rel) already in the manifest
    n_unique = n_occ = n_glyphs = 0
    for ri, (path, node) in enumerate(radiums):
        if cancel():
            break
        if progress:
            progress(ri, len(radiums),
                     "Radium %d/%d" % (ri + 1, len(radiums)))
        try:
            data = reader.read_file_bytes(node)
        except Exception:
            continue
        imgs = parse_radium_images(data)
        off2rel = {}              # this radium's image offsets -> atlas PNG rel
        for im in imgs:
            raw = data[im["data_off"]:im["data_off"] + im["length"]]
            h = hashlib.md5(raw).hexdigest()
            out_rel = by_hash.get(h)
            if out_rel is None:
                try:
                    decode = (_dds.decode_bc1 if im["fmt"] == _DXT1_FORMAT
                              else _dds.decode_bc3)
                    rgba = decode(raw, im["pad_w"], im["pad_h"])
                    pic = Image.fromarray(rgba, "RGBA")
                except Exception as e:
                    log("Radium image %s: decode failed (%s); skipped."
                        % (h[:8], e), "warning")
                    continue
                # Name by nearest scene-element id + dimensions + a short content
                # hash: the element id (e.g. "Song_Progress") organizes the slot
                # list, the dims separate text banners (462x66) from atlases
                # (512x512), and the hash dedupes identical glyphs.
                elem = _nearest_element_name(data, im["data_off"] - 36)
                bits = ["radimg"]
                if elem:
                    bits.append(_sanitize_title(elem, 40))
                bits.append("%dx%d" % (im["tex_w"], im["tex_h"]))
                bits.append(h[:8])
                out_rel = "scene_textures/%s.png" % "_".join(bits)
                pic.save(_lp(os.path.join(output_dir, "images",
                                          *out_rel.split("/"))))
                by_hash[h] = out_rel
                n_unique += 1
            off2rel[im["data_off"]] = out_rel
            manifest.append("%s\t%s\t%d\t%d\t%d\t%d\t%d"
                            % (out_rel, path, im["data_off"], im["length"],
                               im["pad_w"], im["pad_h"], im["fmt"]))
            n_occ += 1
        # ---- font glyph slices: one PNG per character of each atlas ---------
        # A font's glyph table and its atlas always live in the same radium
        # (the atlas is introduced inline by its first glyph), and identical
        # atlas content ⇒ identical font ⇒ identical rects, so slicing is
        # deduped per atlas PNG just like the atlases themselves.
        tables = _radium.parse_glyph_tables(data, imgs) if imgs else []
        for table in tables:
            if cancel():
                break
            # One glyph table can span SEVERAL atlas pages (TMNT's Vera Mono
            # splits a-z across two 512x512 atlases), so a per-atlas grouping
            # splits a font.  The table column — the stem of the table's
            # first atlas — is the stable whole-font identity the Font
            # Preview / Import window groups on.
            table_key = ""
            for g in table["glyphs"]:
                if g["atlas"] is not None:
                    rel0 = off2rel.get(g["atlas"]["data_off"])
                    if rel0:
                        table_key = os.path.splitext(
                            os.path.basename(rel0))[0]
                        break
            # ...but the atlas is only HALF the identity.  One atlas is
            # routinely drawn at several sizes (JAWS bakes GameFont_Primary at
            # eight sizes over one 512x512 atlas; TMNT does it with
            # Stern_Impact_Outline), and every size is a distinct set of
            # metrics over the SAME art.  Keying the dedupe on the atlas alone
            # kept whichever size was met first and dropped the rest, so every
            # scene on the card drew its text at that one size — JAWS' "MODE
            # TITLE / LINE 0..8" screen wants 45px and was rendering at the
            # 150px another scene had already claimed.
            table_px = _radium.table_size_px(table)
            rgba_cache = {}
            for g in table["glyphs"]:
                px = _radium.glyph_px_rect(g)
                if px is None:
                    continue                     # no bitmap (e.g. space)
                atlas_rel = off2rel.get(g["atlas"]["data_off"])
                if atlas_rel is None:
                    continue
                x, y, w, hh = px
                stem = os.path.splitext(os.path.basename(atlas_rel))[0]
                g_rel = "scene_textures/%s/%s/%s" % (
                    _GLYPH_DIR, stem, _glyph_png_name(g["char"]))
                if (table_key, table_px, g_rel) in glyph_rows:
                    continue        # the same table met again on another card
                                    # path — one row per (font, size, glyph)
                glyph_rows.add((table_key, table_px, g_rel))
                # A page already sliced by an earlier table still belongs to
                # THIS table: skip the decode and the PNG (identical content
                # ⇒ identical slice at an identical path), but keep the
                # manifest row.  Skipping the row split fonts across table
                # keys, one key per atlas page, and a text line only ever
                # draws from ONE key — so every character that happened to
                # live on a later page came out blank.  TMNT's clock screen
                # rendered "CLOCK NOT SET" as "CL CK N  E" (O, S and T are on
                # HelveticaNeueBlack's second page) and an award screen turned
                # "Level 4 Award" into "Le el 4 A ard" (David).
                if atlas_rel not in sliced_atlases:
                    a = g["atlas"]
                    rgba = rgba_cache.get(a["data_off"])
                    if rgba is None:
                        try:
                            decode = (_dds.decode_bc1
                                      if a["fmt"] == _DXT1_FORMAT
                                      else _dds.decode_bc3)
                            rgba = decode(
                                data[a["data_off"]:a["data_off"] + a["length"]],
                                a["pad_w"], a["pad_h"])
                        except Exception:
                            continue
                        rgba_cache[a["data_off"]] = rgba
                    g_abs = os.path.join(output_dir, "images",
                                         *g_rel.split("/"))
                    os.makedirs(_lp(os.path.dirname(g_abs)), exist_ok=True)
                    Image.fromarray(rgba[y:y + hh, x:x + w],
                                    "RGBA").save(_lp(g_abs))
                # Trailing metrics columns (rot + the record's layout floats
                # -- see radium.py's format comment) feed the Font Preview /
                # Import renderer; older readers only parse the first 8.
                # kern: ";"-joined 0xRIGHT:adjust pairs (usually empty).
                gw, gh, bx, by, adv = g["metrics"]
                kern = ";".join("0x%04X:%g" % (c, v)
                                for c, v in sorted(g["kern"].items()))
                glyph_manifest.append(
                    "%s\t%s\t0x%04X\t%d\t%d\t%d\t%d\t%s\t%d\t%g\t%g\t%g\t%g"
                    "\t%g\t%s\t%s\t%d"
                    % (g_rel, atlas_rel, g["char"], x, y, w, hh,
                       table["name"], int(g["rot"]), gw, gh, bx, by, adv,
                       table_key, kern, table_px))
                n_glyphs += 1
            # every glyph of a table shares its per-atlas dedupe fate; mark
            # the table's atlases done only after the whole table is sliced
            sliced_atlases.update(
                off2rel[g["atlas"]["data_off"]] for g in table["glyphs"]
                if g["atlas"] is not None
                and g["atlas"]["data_off"] in off2rel)
        # ---- static scene layout (feeds the Scenes window's Preview) -------
        # Record WHERE things are drawn, not a rendered picture: the GUI then
        # composites from the user's current PNGs / glyph slices, so a preview
        # shows their own replacements and font imports rather than stock art.
        lay = _scene_layout.parse_scene_layout(data, imgs, tables)
        if lay is not None:
            entry = _scene_layout_entry(lay, off2rel)
            if entry is not None:
                layouts[path] = entry
    if layouts:
        _write_scene_layouts(tex_dir, layouts, log)
    if not manifest:
        return 0
    try:
        with open(os.path.join(tex_dir, _RADIUM_IMAGE_MANIFEST), "w",
                  encoding="utf-8") as f:
            f.write("# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
                    + "\n".join(manifest) + "\n")
    except Exception:
        pass
    if glyph_manifest:
        try:
            with open(os.path.join(tex_dir, _GLYPH_MANIFEST), "w",
                      encoding="utf-8") as f:
                f.write("# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont"
                        "\trot\tglyph_w\tglyph_h\tbearing_x\tbearing_y"
                        "\tadvance\ttable\tkern\n"
                        + "\n".join(glyph_manifest) + "\n")
        except Exception:
            pass
    log("Extracted %d unique embedded radium image(s) (%d on-card occurrence(s)) "
        "to %s." % (n_unique, n_occ, tex_dir), "success")
    if n_glyphs:
        log("Sliced %d font glyph(s) from %d atlas(es) to %s."
            % (n_glyphs, len(sliced_atlases), os.path.join(tex_dir, _GLYPH_DIR)),
            "success")
    return n_unique


# --------------------------------------------------------------------------
# Scene previews alone: re-read the card's node graphs and rewrite ONLY
# scene_layout.json.  A full re-extract takes many minutes and, worse,
# OVERWRITES every atlas PNG and glyph slice — which would silently throw away
# an imported font — where re-parsing the layouts is ~12 s and touches one
# file.  So a better parser reaches an existing project folder without costing
# the user their work.
# --------------------------------------------------------------------------
def _radium_image_rels(output_dir):
    """``{radium card path: {data offset: atlas PNG rel}}`` from the extract's
    ``radium_images.txt``.

    This is exactly the ``off2rel`` map :func:`extract_radium_images` builds as
    it decodes, recovered from the manifest instead — which is what lets a
    layout rebuild skip decoding (and therefore rewriting) any image at all."""
    out = {}
    path = os.path.join(output_dir, *_TEXTURE_DIR, _RADIUM_IMAGE_MANIFEST)
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) < 3:
                    continue
                try:
                    off = int(cols[2])
                except ValueError:
                    continue
                out.setdefault(cols[1], {})[off] = cols[0]
    except OSError:
        return {}
    return out


def rebuild_scene_layouts(reader, output_dir, log=None, progress=None,
                          cancel=None):
    """Re-parse every ``scene.radium`` on the card and rewrite
    ``images/scene_textures/scene_layout.json`` — and nothing else.

    Returns the number of drawable scenes recorded, or 0 when the project
    folder has no radium-image manifest to resolve the layouts against (i.e.
    it was never extracted with Images enabled)."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    from . import radium as _radium
    from . import scene_layout as _scene_layout
    rels = _radium_image_rels(output_dir)
    if not rels:
        log("This project folder has no %s, so there is nothing to rebuild "
            "the previews from — run Extract with Images enabled first."
            % _RADIUM_IMAGE_MANIFEST, "warning")
        return 0
    radiums = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.endswith(_RADIUM_EXT) and node["size"] >= 32:
            radiums.append((path, node))
    layouts = {}
    matched = 0
    for ri, (path, node) in enumerate(radiums):
        if cancel():
            return 0
        if progress:
            progress(ri, len(radiums),
                     "Scene %d/%d" % (ri + 1, len(radiums)))
        off2rel = rels.get(path)
        if not off2rel:
            continue              # no images extracted from it -> not drawable
        matched += 1
        try:
            data = reader.read_file_bytes(node)
        except Exception:
            continue
        imgs = parse_radium_images(data)
        tables = _radium.parse_glyph_tables(data, imgs) if imgs else []
        lay = _scene_layout.parse_scene_layout(data, imgs, tables)
        if lay is None:
            continue
        entry = _scene_layout_entry(lay, off2rel)
        if entry is not None:
            layouts[path] = entry
    # A card that isn't the one this project came from mostly fails to match by
    # path and quietly produces a thin, wrong-looking set of previews.  Say so:
    # the counts are the only thing that can tell the two cases apart, since a
    # legitimate rebuild matches nearly every scene.
    if rels and matched < len(rels) * 0.5:
        log("Only %d of this project's %d scene(s) were found on that card — "
            "it looks like a different card (or a different version), so most "
            "previews would be missing. Nothing was changed."
            % (matched, len(rels)), "warning")
        return 0
    if not layouts:
        log("No drawable scene layouts were found on this card.", "warning")
        return 0
    tex_dir = os.path.join(output_dir, *_TEXTURE_DIR)
    os.makedirs(tex_dir, exist_ok=True)
    if not _write_scene_layouts(tex_dir, layouts, log):
        return 0
    return len(layouts)


def rebuild_scene_layouts_from_card(image_path, output_dir, log=None,
                                    progress=None, cancel=None,
                                    open_disk=None, partitions=None):
    """:func:`rebuild_scene_layouts` against a card image on disk.

    Uses the same partition the extract read (the one holding ``image.bin``
    next to the game ELF), so the card paths it writes match the ones already
    in the manifests."""
    log = log or (lambda *a, **k: None)
    if partitions is None:
        partitions = _linux_partitions(image_path)
    disk_f = (open_disk() if open_disk is not None
              else open(_lp(image_path), "rb"))
    try:
        reader, _fw, _img = _locate(disk_f, partitions)
        return rebuild_scene_layouts(reader, output_dir, log=log,
                                     progress=progress, cancel=cancel)
    finally:
        try:
            disk_f.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# display-text extract: editable LCD strings inside the .radium scene files
# --------------------------------------------------------------------------
_RADIUM_EXT = ".radium"
# The editable strings manifest format (text/strings.tsv) lives in the core
# text_manifest module so the Replace Text GUI tab and this engine -- which read
# and write the same file -- can't drift apart.


def extract_radium_text(reader, output_dir, log=None, progress=None, cancel=None):
    """Extract every editable LCD display-text string from the card's
    ``.radium`` scene files into an editable manifest under
    ``output_dir/text/``.

    Spike 2 stores on-screen UI text inside ``*.radium`` scene files on the
    ext4 data partition.  For each radium we enumerate its ``display-text``
    strings (see :mod:`.radium`), dedupe by value (the same string repeats many
    times -- once per keyframe of the parent ``Sprite`` timeline), and write a
    human-editable TSV ``text/strings.tsv`` with columns
    ``radium_card_path``, ``original``, ``replacement`` (replacement left blank;
    the user fills in only the strings to change).  Radiums with no display text are
    skipped.  Write later re-enumerates the unchanged on-card radium to find the
    authoritative offsets, so only the (path, original) key is load-bearing.

    Returns the number of unique (radium, string) rows written."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    from . import radium as _radium

    log("Scanning .radium scene files for display text...", "info")
    rads = []
    fw_cands = {}                # basename -> (card_path, node): the game ELF
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.lower().endswith(_RADIUM_EXT):
            rads.append((path, node))
        else:
            base = path.rsplit("/", 1)[-1]
            if base in ("game_real", "game") and base not in fw_cands:
                try:
                    if reader.is_arm_elf(node):
                        fw_cands[base] = (path, node)
                except Exception:
                    pass
    if not rads:
        log("No .radium scene files found.", "info")
        return 0

    rows = []                    # (card_path, original)
    manifest = []                # (card_path, n_unique, n_occurrences)
    for i, (path, node) in enumerate(rads):
        if cancel():
            break
        if progress:
            progress(i, len(rads), "Scanning radium %d/%d" % (i + 1, len(rads)))
        try:
            data = reader.read_file_bytes(node)
        except Exception as e:
            log("Couldn't read %s (%s); skipped." % (path, e), "warning")
            continue
        dts = _radium.display_texts(data)
        if not dts:
            continue
        seen = set()
        n_occ = 0
        for e in dts:
            n_occ += 1
            text = e["text"]
            if text in seen:
                continue
            seen.add(text)
            rows.append((path, text))
        manifest.append((path, len(seen), n_occ))

    # Game-program strings: display text the game code composes at runtime
    # (mode titles, battle names, award lines) lives in the ELF, not in any
    # radium — the scene's Text node is a placeholder the code overwrites
    # (Godzilla's battle intro was the proving case).  Best-effort: a title
    # whose firmware can't be read/parsed just extracts no program rows.
    prog_rows = []
    fw = fw_cands.get("game_real") or fw_cands.get("game")
    if fw is not None and not cancel():
        from . import progtext
        fw_path, fw_node = fw
        try:
            if progress:
                progress(len(rads), len(rads) + 1,
                         "Scanning the game program for display text")
            entries = progtext.enumerate_program_strings(
                reader.read_file_bytes(fw_node))
            prog_rows = []
            for e in entries:
                row = {"path": fw_path, "original": e["text"],
                       "replacement": "", "budget": e["budget"]}
                # The manifest's 5th-column flags (text_manifest.FLAG_*):
                # a growable row may take longer text (placed in a new
                # area of the game program on Write); a row with no
                # reference found is dead text the game never draws.  The
                # NOT-growable case is written out too ("fixed"), because
                # a row with no flags at all has to keep meaning "this
                # manifest predates the scan" — see FLAG_FIXED.
                if e.get("growable"):
                    row["grow"] = True
                else:
                    row["fixed"] = True
                if e.get("unused") or e.get("refs") == 0:
                    row["unused"] = True
                prog_rows.append(row)
        except Exception as e:
            log("Couldn't scan the game program for display text (%s); "
                "program strings skipped." % e, "warning")
        if prog_rows:
            log("Found %d editable game-program string(s) in %s."
                % (len(prog_rows), fw_path), "info")

    if not rows and not prog_rows:
        log("No editable display text found in %d .radium file(s)."
            % len(rads), "info")
        return 0

    from ...core import text_manifest
    text_dir = os.path.join(output_dir, text_manifest.RELDIR)
    # A RE-EXTRACT KEEPS THE USER'S EDITS.  The manifest is rewritten from the
    # card (budgets, the grows/unused flags and any new rows come from THIS
    # scan), but a replacement already typed for a (scene, original) pair is
    # carried over -- re-extracting used to blank every edit, which is the
    # one thing a user refreshing an old manifest for the new 'grows' budgets
    # cannot afford (David, 2026-09-07: his Godzilla LE project predates the
    # flag).  A row that no longer exists on the card simply drops out.
    kept = {}
    try:
        for r in text_manifest.load(output_dir):
            if r.get("replacement"):
                kept[(r.get("path", ""), r.get("original", ""))] =                     r["replacement"]
    except Exception:
        kept = {}
    try:
        # replacement column left BLANK unless the user had already filled it
        # in -- blank = leave unchanged, so the manifest never looks like every
        # row is already duplicated.
        all_rows = [
            {"path": card_path, "original": original, "replacement": ""}
            for card_path, original in rows] + prog_rows
        n_kept = 0
        for row in all_rows:
            prev = kept.get((row["path"], row["original"]))
            if prev and not row.get("replacement"):
                row["replacement"] = prev
                n_kept += 1
        if n_kept:
            log("Kept %d display-text edit(s) already in text/strings.tsv."
                % n_kept, "info")
        text_manifest.save(output_dir, all_rows)
    except Exception as e:
        log("Couldn't write display-text manifest (%s)." % e, "warning")
        return 0
    try:
        with open(os.path.join(text_dir, "manifest.txt"), "w",
                  encoding="utf-8") as f:
            f.write("# radium card path\tunique strings\toccurrences\n")
            for card_path, nuniq, nocc in manifest:
                f.write("%s\t%d\t%d\n" % (card_path, nuniq, nocc))
            if prog_rows:
                f.write("%s\t%d\t%d\n" % (prog_rows[0]["path"],
                                          len(prog_rows), len(prog_rows)))
    except Exception:
        pass
    log("Extracted %d editable display-text string(s) from %d radium scene(s) "
        "%sto %s." % (len(rows), len(manifest),
                      ("plus %d game-program string(s) " % len(prog_rows))
                      if prog_rows else "", text_dir), "success")
    return len(rows) + len(prog_rows)


def refresh_program_text_flags(assets_dir, log=None, cancel=None):
    """Refresh the game-program rows of an existing ``text/strings.tsv`` from
    the card the project was extracted from, and return how many rows were
    updated (0 when there is nothing to do).

    A project extracted before the growable/fixed flags existed carries the
    ORIGINAL length as every program row's budget, so the Text tab used to
    refuse longer text on strings the Write step can in fact relocate.  The
    tab now treats an unflagged program row as growable (the Write checks
    each one against the card anyway), and this fills in the exact answer:
    the budgets, ``grows`` / ``fixed`` and ``unused`` come from a fresh
    :func:`.progtext.enumerate_program_strings` of the card's own game ELF.

    Only the program rows are touched -- scene rows, the row order and every
    replacement the user has already typed are preserved -- so this is safe to
    run behind a Scan.  Best effort throughout: a project with no source card
    recorded, a card that has moved or changed size, an unreadable ELF or an
    unwritable manifest all return 0 without raising."""
    import json
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    from ...core import text_manifest
    from ...core.extract_source import SIDE_CAR

    try:
        rows = text_manifest.load(assets_dir)
    except Exception:
        return 0
    prog = [r for r in rows
            if not (r.get("path") or "").lower().endswith(_RADIUM_EXT)]
    if not prog or cancel():
        return 0

    # The card this project came out of, and a cheap identity check: a
    # different image at the same path would answer for the wrong build.
    try:
        with open(_lp(os.path.join(assets_dir, SIDE_CAR)),
                  "r", encoding="utf-8") as f:
            src = json.load(f)
        card = src.get("input_path") or ""
        want = src.get("size")
    except Exception:
        return 0
    try:
        ok = bool(card) and os.path.isfile(_lp(card)) and (
            not want or os.path.getsize(_lp(card)) == want)
    except OSError:
        ok = False
    if not ok:
        log("The card image this project was extracted from isn't where it "
            "was (%s), so the game program's exact text limits couldn't be "
            "re-read; longer text is still offered and the Write step "
            "checks each string against the card." % (card or "not recorded"),
            "info")
        return 0

    try:
        parts = _linux_partitions(card)
        with open(_lp(card), "rb") as disk_f:
            reader, fw_node, _img = _locate(disk_f, parts)
            if fw_node is None or cancel():
                return 0
            raw = reader.read_file_bytes(fw_node)
        from . import progtext
        entries = progtext.enumerate_program_strings(raw)
    except Exception as e:
        log("Couldn't re-read the game program's text limits (%s); longer "
            "text is still offered and the Write step checks each string "
            "against the card." % e, "info")
        return 0
    if cancel():
        return 0

    by_text = {e["text"]: e for e in entries}
    n = 0
    for r in prog:
        e = by_text.get(r.get("original"))
        if e is None:
            continue
        r["budget"] = e["budget"]
        r.pop("grow", None)
        r.pop("fixed", None)
        r.pop("unused", None)
        if e.get("growable"):
            r["grow"] = True
        else:
            r["fixed"] = True
        if e.get("unused") or e.get("refs") == 0:
            r["unused"] = True
        n += 1
    if not n:
        return 0
    try:
        text_manifest.save(assets_dir, rows)
    except Exception as e:
        log("Couldn't update the display-text manifest (%s)." % e, "warning")
        return 0
    n_grow = sum(1 for r in prog if r.get("grow"))
    log("Re-read the game program's text limits from the card: %d string(s), "
        "%d of them able to take longer text." % (n, n_grow), "info")
    return n


def _write_wav(path, L, R, stereo):
    import numpy as np
    chans = [L, R] if stereo else [L]
    n = len(chans[0])
    inter = np.empty(n * len(chans), np.int16)
    for i, c in enumerate(chans):
        inter[i::len(chans)] = np.clip(c, -32768, 32767).astype(np.int16)
    w = wave.open(path, "wb")
    w.setnchannels(len(chans)); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(inter.tobytes()); w.close()


# --------------------------------------------------------------------------
# public API (called by the pipelines)
# Auto-transcribe / Music-ID *renamed* decode WAVs — "idx0001 - music.wav",
# "music_cat01_0001 - Battery.wav", either with the optional play-length
# prefix ("01m22s235 - idx0001 - music.wav").  The bare file the decode
# writes is deliberately NOT matched here (it's overwritten in place); only
# the renamed copies a prior extract left behind are.
_RENAMED_AUDIO_RE = re.compile(
    r"^(?:\d+m\d+s\d+ - )?(?:idx\d+|music_cat\d+_\d+) - .*\.wav$",
    re.IGNORECASE)
# The two bare decode-output shapes.  Whichever shape the CURRENT extract is
# NOT writing is a stale leftover from a run with the opposite Length-prefix
# setting (the fresh decode won't overwrite it), so it gets removed too.
_BARE_IDX_RE = re.compile(r"^idx\d+\.wav$", re.IGNORECASE)
_PREFIXED_IDX_RE = re.compile(r"^\d+m\d+s\d+ - idx\d+\.wav$", re.IGNORECASE)


def _wav_basename(p, duration_names):
    """Output filename for a decoded cat-0 sound.

    Default is the classic ``idx0001.wav``.  With *duration_names* (the
    Extract tab's "Length-prefix names" option) the play length leads —
    ``01m22s235 - idx0001.wav`` — zero-padded so a plain name sort orders by
    duration: the stable key for lining the same sounds up across firmware
    versions, where the idx shifts (a tester).  ``:`` is not legal in
    Windows filenames, hence the m/s spelling.

    The prefix is the TRUE decoded play length (header length minus the
    200-sample cursor lead-in, see emitted_length) — the raw header length
    read ~4.5 ms long, so a replacement trimmed to the advertised time got
    its tail cut at encode (a tester's Replace-tab mismatch)."""
    if not duration_names:
        return "idx%04d.wav" % p["idx"]
    from .spike2.emulator import emitted_length
    ms = int(round(emitted_length(p.get("length", 0)) * 1000.0 / 44100.0))
    m, rem = divmod(ms, 60000)
    s, ms = divmod(rem, 1000)
    return "%02dm%02ds%03d - idx%04d.wav" % (m, s, ms, p["idx"])


def _remove_renamed_audio_twins(audio_dir, log=None, duration_names=False):
    """Delete stale decode WAVs in *audio_dir* the fresh decode won't overwrite.

    Two kinds go: (a) a previous run's Auto-transcribe/Music-ID *renamed*
    copies (``idx0001 - music.wav``) — the fresh decode regenerates every
    sound, so those are always stale; (b) bare decode outputs in the OTHER
    Length-prefix style than this run writes (``idx0001.wav`` vs
    ``01m22s235 - idx0001.wav``) — same sound, different name, so it would
    otherwise survive as a duplicate.  Either way a leftover means two files
    per idx: GUI clutter and a hazard for the idx-keyed Write mapping.  The
    same-style bare files are left alone (they're overwritten in place).
    No-op on a first extract into an empty folder.
    """
    if not os.path.isdir(audio_dir):
        return
    stale_bare = _BARE_IDX_RE if duration_names else _PREFIXED_IDX_RE
    removed = 0
    for fn in os.listdir(audio_dir):
        if _RENAMED_AUDIO_RE.match(fn) or stale_bare.match(fn):
            try:
                os.remove(os.path.join(audio_dir, fn))
                removed += 1
            except OSError:
                pass
    if removed and log:
        log("Removed %d stale audio file(s) from a previous extract "
            "(renamed twins and/or the other naming style; re-naming will "
            "run again if enabled)." % removed, "info")


def _sfx_names_cache_path(fp):
    """Sibling of the params cache holding the ``{idx: name}`` SFX-name map.

    The suffix is bumped whenever the menu->sound binding changes so stale
    caches can't re-apply names built by a superseded mapping: ``2`` retired
    the pre-v0.63.1 maps, ``3`` retires everything built before the menu's
    ``{group_ptr, node_id}`` / sound-id-list indirection was read correctly,
    and ``4`` retires the maps built while the menu table was located by the
    literal "SE FX " (which found it on two titles out of fourteen).

    Also carries the derive revision, because a name map is validated against
    the audio the params point at -- params from a superseded derive can only
    have produced a superseded map."""
    return os.path.join(_params_cache_dir(),
                        fp[:32] + _REV_TAG + ".sfxnames4.json")


def _load_or_build_sfx_names(emu, game_real_path, image_path, params, log):
    """``{idx: "SE FX <NAME>"}`` for the sounds the game's Sound Test menu names.

    Mines the menu name table from the firmware, follows the menu's own
    node-id -> sound-id indirection, and drives its asset resolver to map each
    name onto the extraction idx (see :mod:`.spike2.sfx_names`).  The finished
    map only ships if it passes that module's validation, which tests the names
    against the audio they point at, so a build whose layout shifts the mapping
    names nothing rather than mislabelling (the v0.61.x failure mode).  Cached
    per card next to the params.  Best-effort: ``{}`` for older menu-less titles
    or any build whose resolver can't be located — the extract keeps plain idx
    names.  Set ``PINBALL_SFX_NAMES=0`` to turn naming off entirely.  *emu* must
    be booted and *params* must carry ``key0``."""
    if os.environ.get("PINBALL_SFX_NAMES") == "0":
        return {}
    import json
    fp = _fingerprint(game_real_path, image_path)
    cache = _sfx_names_cache_path(fp)
    if os.path.exists(cache):
        try:
            return {int(k): v for k, v in json.load(open(cache)).items()}
        except Exception:
            pass
    try:
        from .spike2 import sfx_names as _sfxn
        name_map = _sfxn.build_name_map(emu, params, log)
    except Exception as e:
        log("Sound-effect auto-naming unavailable (%s)." % e, "info")
        name_map = {}
    try:
        json.dump({str(k): v for k, v in name_map.items()}, open(cache, "w"))
    except Exception:
        pass
    if name_map and log:
        log("Matched %d sound effect(s) to their Sound Test menu name(s)."
            % len(name_map), "success")
    return name_map


SOUND_TEST_NAMES_CSV = "sound_test_names.csv"


def _write_sound_test_names(game_real_path, output_dir, log=None):
    """Write the firmware's Sound-Test menu listing to
    ``sound_test_names.csv`` (columns ``sound_number,name``) at the assets
    root.  Static ELF parse only — no emulator.

    The number is the one the machine prints beside each entry (OCR-verified
    against a real Sound Test), which is a reversed menu position and not the
    internal sound id that :func:`_load_or_build_sfx_names` resolves.  Naming
    is automatic now, so this sidecar is a cross-reference: play a number on
    the machine, and either confirm the name the extract already applied or
    right-click → Rename to set it yourself (the Rename dialog offers these
    names as suggestions).  Best-effort; menu-less titles get no file."""
    try:
        from .spike2.sfx_names import locate_menu_names
        with open(game_real_path, "rb") as f:
            names = locate_menu_names(f.read())
        if not names:
            return 0
        import csv
        out = os.path.join(output_dir, SOUND_TEST_NAMES_CSV)
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["sound_number", "name"])
            for sid, name in sorted(names):
                w.writerow([sid, name])
        if log:
            log("Wrote the game's Sound Test menu list (%d names) to %s — "
                "play a number on the machine's Sound Test menu, then "
                "right-click the matching slot → Rename to apply the name."
                % (len(names), SOUND_TEST_NAMES_CSV), "info")
        return len(names)
    except Exception:
        return 0


_ILLEGAL_FN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _apply_sfx_names(audio_dir, name_map, params, duration_names, log=None):
    """Rename each decoded ``idx####.wav`` to ``idx#### - <STERN NAME>.wav`` for
    the SFX the Sound Test menu names.  Runs after decode; a missing bare file
    (a sound that failed to decode) is skipped.  Returns the count renamed."""
    if not name_map or not os.path.isdir(audio_dir):
        return 0
    by_idx = {p["idx"]: p for p in params}
    renamed = 0
    for idx, name in name_map.items():
        p = by_idx.get(idx)
        if p is None:
            continue
        base = _wav_basename(p, duration_names)
        src = os.path.join(audio_dir, base)
        if not os.path.isfile(src):
            continue
        safe = _ILLEGAL_FN.sub("", name).strip().rstrip(".")[:80] or "sound"
        dst = os.path.join(audio_dir, base[:-4] + " - " + safe + ".wav")
        if os.path.abspath(dst) == os.path.abspath(src):
            continue
        try:
            os.replace(src, dst)
            renamed += 1
        except OSError:
            pass
    if renamed and log:
        log("Named %d sound effect(s) from the Sound Test menu." % renamed,
            "success")
    return renamed


# --------------------------------------------------------------------------
def extract_all(image_path, partitions, output_dir, log=None, progress=None,
                cancel=None, phase=None, open_disk=None, log_line=None,
                music_banks=True, do_audio=True, do_video=True,
                do_images=True, do_text=True, label=None,
                duration_names=False):
    """Decode every cat-0 sound in the card image to ``output_dir`` as WAV
    (under ``audio/``) and extract videos (under ``video/``).

    ``music_banks`` ALSO decodes the per-category ``image-scNN.bin`` banks — the
    licensed songs / extra sound sets the six multi-category titles (Metallica,
    D&D, Rush, Deadpool, Foo Fighters, John Wick) keep outside cat-0.  Each bank
    is derived + decoded on its own fresh emulator across a process pool (one
    task per bank — see :func:`spike2.category.extract_category_audio_parallel`),
    so Metallica's 24 songs finish in ~2 min and titles without banks are a fast
    no-op.  On by default; the few multi-cat builds the loader can't drive skip
    their banks gracefully (cat-0 audio is unaffected).

    ``open_disk`` (a zero-arg callable returning a fresh seekable byte stream)
    overrides how the disk is opened — Direct-SD passes one that returns a
    :class:`.rawdevice.RawDeviceFile` over the physical card; the default opens
    the image file at ``image_path``.  Everything downstream (game_real +
    image.bin are streamed to a temp dir, then decoded) is identical either way.

    ``log_line`` (``cb(key, text, level)``) drives the live per-sound decode
    progress — one in-place-updated line per sound; omitted → no live lines.
    """
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    phase = phase or (lambda i: None)
    from .spike2.emulator import Spike2Emu, audio_decode_supported

    def _read_prog(c, t):
        if progress:
            progress(int(c * 5 / max(t, 1)), 100, "Reading image.bin")

    work = _work_dir(label)
    emu = None
    disk_f = (open_disk() if open_disk is not None
              else open(_lp(image_path), "rb"))
    try:
        os.makedirs(output_dir, exist_ok=True)
        gr_path, img_path, reader, _fw, _img = _extract_inputs(
            disk_f, partitions, work, log, _read_prog)
        if cancel():
            return 0

        # videos + images first (quick file copies) so they appear before the
        # long audio decode
        phase(2)  # Extract video
        if do_video:
            try:
                extract_videos(reader, output_dir, log=log,
                               progress=(lambda c, t, d="": progress(
                                   5 + int(c * 8 / max(t, 1)), 100, d)) if progress else None,
                               cancel=cancel)
            except Exception as e:
                log("Video extraction failed (%s); continuing." % e, "warning")
        if cancel():
            return 0

        phase(3)  # Extract images
        if do_images:
            try:
                extract_images(reader, output_dir, log=log,
                               progress=(lambda c, t, d="": progress(
                                   13 + int(c * 2 / max(t, 1)), 100, d)) if progress else None,
                               cancel=cancel)
            except Exception as e:
                log("Image extraction failed (%s); continuing." % e, "warning")
            if cancel():
                return 0
            # The boot screen, off the OS partition rather than the games one.
            try:
                extract_boot_images(disk_f, partitions, output_dir,
                                    games_base=reader.base, log=log)
            except Exception as e:
                log("Boot screen extraction failed (%s); continuing." % e,
                    "warning")
            # Scene textures (BC3/DXT5 glyph/sprite atlases inside scene.assets)
            # — decoded to editable PNGs; an own try/except so a texture hiccup
            # never blocks the loose-PNG or audio extraction.
            try:
                extract_scene_textures(reader, output_dir, log=log,
                                       progress=(lambda c, t, d="": progress(
                                           15, 100, d)) if progress else None,
                                       cancel=cancel)
            except Exception as e:
                log("Scene-texture extraction failed (%s); continuing." % e,
                    "warning")
            if cancel():
                return 0
            # DXT5 images embedded inline in the radium scenes (the song-title
            # text glyphs like "ROCK AND ROLL") — same codec, patched in place.
            try:
                extract_radium_images(reader, output_dir, log=log,
                                      progress=(lambda c, t, d="": progress(
                                          15, 100, d)) if progress else None,
                                      cancel=cancel)
            except Exception as e:
                log("Radium-image extraction failed (%s); continuing." % e,
                    "warning")
            if cancel():
                return 0
            # Spine skeletons embedded verbatim in scene.radium (the 2D
            # skeletal-animation rigs) -> spine/*.json — own try/except so a
            # skeleton hiccup never blocks the other media or audio.
            try:
                from . import spine as _spine
                _spine.extract_spine(
                    reader, output_dir, log=log,
                    progress=(lambda c, t, d="": progress(
                        15, 100, d)) if progress else None,
                    cancel=cancel)
            except Exception as e:
                log("Spine extraction failed (%s); continuing." % e, "warning")
        if cancel():
            return 0

        # editable LCD display text (.radium scenes) -> text/strings.tsv
        if do_text:
            try:
                extract_radium_text(reader, output_dir, log=log, cancel=cancel)
            except Exception as e:
                log("Display-text extraction failed (%s); continuing." % e,
                    "warning")
            if cancel():
                return 0

        phase(4)  # Decode audio
        if not do_audio:
            log("Audio extraction skipped (unchecked).", "info")
            phase(5)  # Checksums
            return 0
        if not audio_decode_supported(gr_path):
            log("Audio decode isn't supported for this title yet: its game "
                "firmware uses a Spike 2 codec the engine can't locate a "
                "single decode path for (e.g. a dual-path codec), so the "
                "per-sound keystream can't be derived. Video + image "
                "extraction completed normally.", "warning")
            phase(5)  # Checksums
            return 0
        log("Booting firmware codec engine...", "info")
        try:
            emu = Spike2Emu(gr_path, img_path)
            emu.boot()
            params = _load_or_derive_params(emu, gr_path, img_path, log, progress)
        except Exception as e:
            # A newer / unrecognised firmware build the codec locator can't map:
            # skip audio but keep the video / image / text extract that already
            # succeeded (mirrors the audio_decode_supported early-out above), and
            # save the firmware next to the output so the user can send it in for
            # a locator fix -- the work dir it lives in is deleted on return.
            if emu is not None:
                try:
                    emu.close()
                except Exception:
                    pass
                emu = None
            saved = _save_firmware_for_support(gr_path, output_dir, log)
            log("Audio couldn't be extracted from this card: the engine could "
                "not map this firmware build's audio codec (%s). This is "
                "usually a newer game update than this version of the app "
                "recognises -- video, images and text extracted normally.%s"
                % (e, (" The firmware was saved to %s -- send that file to the "
                       "developer to get this build's audio supported in a "
                       "future update." % saved) if saved else ""), "warning")
            phase(5)  # Checksums
            return 0
        # Map the game's Sound Test menu names onto the sounds while the codec
        # emu is still booted (mines the firmware menu + drives its resolver).
        # Best-effort + cached; {} for titles without the menu.
        sfx_name_map = _load_or_build_sfx_names(
            emu, gr_path, img_path, params, log)
        # Even with auto-apply off, the menu NAME LIST itself is verified data
        # (name<->displayed-number matches the machine's menu): ship it as a
        # sidecar so users can play a number in the machine's Sound Test and
        # rename the matching slot themselves (right-click -> Rename offers
        # these as suggestions; David's idea after the binding proved wrong).
        _write_sound_test_names(gr_path, output_dir, log)
        emu.close()
        emu = None   # decode runs in worker processes (or a fresh emu on fallback)

        audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        # Drop a previous extract's auto-named twins so re-extracting doesn't
        # accumulate "idx0001.wav" + "idx0001 - music.wav" duplicates.
        _remove_renamed_audio_twins(audio_dir, log,
                                    duration_names=duration_names)
        total = len(params)
        ok = None
        nworkers = max(1, min((os.cpu_count() or 2) - 2, 8))
        if nworkers > 1 and not cancel():
            try:
                log("Decoding %d sounds across %d processes..." % (total, nworkers), "info")
                ok = _parallel_decode(gr_path, img_path, params, audio_dir,
                                      log, progress, cancel, nworkers,
                                      log_line=log_line,
                                      duration_names=duration_names)
            except Exception as e:
                log("Parallel decode unavailable (%s); using a single process."
                    % e, "warning")
                ok = None
        if ok is None:
            emu = Spike2Emu(gr_path, img_path)
            emu.boot()
            ok = _serial_decode(emu, params, audio_dir, log, progress, cancel,
                                log_line=log_line,
                                duration_names=duration_names)
        if ok == 0 and total > 0:
            # Every sound failed to decode -- a systemic problem (a build whose
            # codec the engine couldn't drive), not a per-sound hiccup.  Surface
            # it loudly instead of a green "Decoded 0/N" that reads like success.
            log("Decoded 0/%d sounds -- audio decode failed for this card. The "
                "firmware build may use a codec path the engine can't drive yet; "
                "video, images and text extracted normally." % total, "error")
        else:
            log("Decoded %d/%d sounds to %s" % (ok, total, audio_dir), "success")
            # Title the decoded SFX with their Sound Test menu names (no-op {}).
            _apply_sfx_names(audio_dir, sfx_name_map, params, duration_names, log)
        if music_banks and not cancel():
            if emu is not None:
                emu.close(); emu = None    # free the cat-0 emu before booting CatEmu
            ok += _extract_category_banks(reader, gr_path, img_path, work,
                                          audio_dir, log, progress, cancel)
        return ok
    finally:
        if emu is not None:
            emu.close()
        disk_f.close()
        _rmtree(work)


def _extract_category_banks(reader, gr_path, img_path, work, audio_dir, log,
                            progress, cancel):
    """Extract the card's ``image-scNN.bin`` banks to ``work`` and decode each to
    WAV under ``audio/`` (named ``music_catNN_idx.wav`` so the existing
    AcoustID auto-naming can title the songs).  Returns the count decoded; 0 (and
    a clean skip) when there are no banks or the build can't be driven."""
    from .spike2.category import extract_category_audio_parallel
    sc_paths = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            break
        base = path.rsplit("/", 1)[-1]
        if base.startswith("image-sc") and base.endswith(".bin"):
            op = os.path.join(work, base)
            reader.extract_file(node, op)
            sc_paths.append(op)
    if not sc_paths:
        return 0
    log("Extracting %d per-category music bank(s) — the licensed songs / extra "
        "sounds outside image.bin." % len(sc_paths), "info")

    def _prog(c, t):
        if progress:
            progress(min(100, int(c * 100 / max(t, 1))), 100,
                     "Decoding music bank %d/%d" % (c, t))
    n = extract_category_audio_parallel(gr_path, img_path, sc_paths, audio_dir,
                                        log=log, progress=_prog, cancel=cancel)
    log("Decoded %d per-category music sound(s)." % n, "success")
    return n


def _serial_progress_cb(p, emit):
    """Throttled per-block callback that emits a ``prog`` event for a long sound
    in the single-process path (mirrors the parallel workers, minus the queue).
    Short sounds never tick (they finish before the threshold)."""
    import time
    t0 = time.monotonic()
    st = {"last": 0.0}
    length = p.get("length", 0); chan = p.get("chan", 1)

    def cb(cur, nmax):
        now = time.monotonic()
        if now - t0 < 2.5 or now - st["last"] < 3.0:
            return
        st["last"] = now
        emit(("prog", p["idx"], cur / max(nmax, 1), length, chan))
    return cb


def _serial_decode(emu, params, audio_dir, log, progress, cancel, log_line=None,
                   duration_names=False):
    total = len(params)
    ok = 0

    def emit(msg):
        _emit_decode(msg, log, log_line)

    for i, p in enumerate(params):
        if cancel():
            log("Cancelled after %d sounds." % ok, "info")
            break
        if progress:
            progress(15 + int(i * 85 / max(total, 1)), 100,
                     "Decoding sound %d/%d" % (i + 1, total))
        length = p.get("length", 0); chan = p.get("chan", 1)
        emit(("start", p["idx"], length, chan))
        try:
            r = emu.decode(p, cancel=cancel,
                           progress=_serial_progress_cb(p, emit))
        except Exception as e:
            log("idx %d: decode failed (%s)" % (p["idx"], e), "warning")
            continue
        if r is None:
            continue
        L, R, stereo = r
        _write_wav(os.path.join(audio_dir, _wav_basename(p, duration_names)),
                   L, R, stereo)
        emit(("done", p["idx"], length, chan))
        ok += 1
    return ok


def _dur_str(length, chan):
    """``(stereo 4:31)`` from a per-channel sample count + channel count."""
    secs = int(length / 44100.0)
    return "(%s %d:%02d)" % ("stereo" if chan == 2 else "mono",
                             secs // 60, secs % 60)


def _bar(frac, width=12):
    n = max(0, min(width, int(round(frac * width))))
    return "[" + "#" * n + "." * (width - n) + "]"


def _decode_line(msg):
    """``(key, text, level)`` for a worker decode event (start/prog/done).

    The key is per-sound (``dec<idx>``) so the GUI rewrites ONE line per sound
    in place — the bar animates from start → done instead of spamming a line per
    tick."""
    kind = msg[0]
    if kind == "start":
        _, idx, length, chan = msg
        return ("dec%d" % idx,
                "    idx%04d %-14s %s   0%%"
                % (idx, _dur_str(length, chan), _bar(0)),
                "info")
    if kind == "prog":
        _, idx, frac, length, chan = msg
        return ("dec%d" % idx,
                "    idx%04d %-14s %s %3d%%"
                % (idx, _dur_str(length, chan), _bar(frac), int(frac * 100)),
                "info")
    # done
    _, idx, length, chan = msg
    return ("dec%d" % idx,
            "    idx%04d %-14s decoded" % (idx, _dur_str(length, chan)),
            "success")


def _emit_decode(msg, log, log_line):
    """Forward a decode event: an in-place keyed line when ``log_line`` is wired
    (the GUI), else a plain appended line for the ``done`` events only (so a
    non-GUI caller's log gets one concise line per finished sound, not a tick
    flood)."""
    if log_line is not None:
        key, text, level = _decode_line(msg)
        log_line(key, text, level)
    elif msg[0] == "done":
        _, text, level = _decode_line(msg)
        log(text, level)


def _parallel_decode(gr_path, img_path, params, audio_dir, log, progress, cancel,
                     nworkers, log_line=None, duration_names=False):
    """Decode across ``nworkers`` spawned emulator processes (each boots once,
    decodes its share, writes WAVs directly).  Raises on any pool failure so the
    caller can fall back to a single process.

    A shared queue carries per-sound start/progress/done events from the
    workers; a daemon thread drains it and forwards each to ``_emit_decode`` so
    the GUI shows one in-place, animating line per sound (the long music tracks
    no longer look stalled)."""
    import multiprocessing as mp
    import threading

    from .spike2.parallel import decode_to_wav, init_worker, probe

    # Decode in natural (master-directory) order so the short sounds finish
    # first and WAVs stream into the output folder right away — the live
    # per-sound progress below surfaces the long music tracks (which would
    # otherwise look stalled) without reordering the queue, so we don't trade
    # away that "files appear as it goes" feedback.
    tasks = [(p, os.path.join(audio_dir, _wav_basename(p, duration_names)))
             for p in params]
    total = len(tasks)
    ctx = mp.get_context("spawn")
    # Manager queue: picklable across spawn (a plain mp.Queue isn't), so it can
    # ride in the pool initargs to every worker.
    mgr = ctx.Manager()
    prog_q = mgr.Queue()
    pool = ctx.Pool(nworkers, initializer=init_worker,
                    initargs=(gr_path, img_path, prog_q))
    stop_forward = threading.Event()

    def _forward():
        while not stop_forward.is_set():
            try:
                msg = prog_q.get(timeout=0.3)
            except Exception:
                continue
            if msg is None:
                break
            try:
                _emit_decode(msg, log, log_line)
            except Exception:
                pass
    fwd = threading.Thread(target=_forward, daemon=True)
    fwd.start()

    ok = 0
    try:
        # Confirm a worker actually booted within a generous window; a stalled
        # pool (e.g. an unguarded entry re-running the GUI) raises here and the
        # caller falls back to a single process.
        pool.apply_async(probe).get(timeout=180)
        i = 0
        for idx, good in pool.imap_unordered(decode_to_wav, tasks, chunksize=4):
            ok += good
            i += 1
            if progress and (i % 4 == 0 or i == total):
                progress(15 + int(i * 85 / max(total, 1)), 100,
                         "Decoding sound %d/%d" % (i, total))
            if cancel():
                log("Cancelled after %d sounds." % ok, "info")
                break
        pool.close()
    finally:
        stop_forward.set()
        try:
            prog_q.put(None)
        except Exception:
            pass
        fwd.join(timeout=1.0)
        pool.terminate()
        pool.join()
        try:
            mgr.shutdown()
        except Exception:
            pass
    return ok


# --------------------------------------------------------------------------
# Replace-Video: size-neutral in-place patch of the loose .asset clips
# --------------------------------------------------------------------------
_VIDEO_MANIFEST = "manifest.txt"


def _pad_isobmff(data, target):
    """Pad an MP4/MOV (ISO-BMFF / QuickTime) byte string up to exactly *target*
    bytes by appending a trailing ``free`` box, which compliant demuxers skip —
    the original ``moov``/``mdat`` are left untouched.  ``len(data)`` must be
    ``<= target``.

    The padding itself lives in :func:`core.video.pad_isobmff_to_size`, which
    JJP's fixed-size slots need too; the truncating guard stays here because
    it is this caller's contract, not the format's.
    """
    if len(data) >= target:
        return data[:target]
    from ...core.video import pad_isobmff_to_size
    return pad_isobmff_to_size(data, target)


# The write-side change scan used to md5 every asset on every Write — minutes
# of re-hashing a big mod even when nothing changed since the last build
# (Godzilla Heisei 1.16: 3 min 12 s of a 9.5-minute write, and a multiple of
# that on a slower rig).  The GUI's change scan and the mod-pack export
# already share a size+mtime sidecar (core.hashcache, ".hashcache.json");
# this routes the engine's scans through the same file, so all three walks
# feed one cache and any of them warms the others.
_HASHCACHES = {}      # assets_dir -> loaded hashcache dict (process lifetime)


def _scan_md5(assets_dir, path):
    """MD5 of *path* through *assets_dir*'s size+mtime hash cache.  ``None``
    on read failure — callers already treat that as "changed", exactly as
    they treated ``md5_file`` raising ``OSError``."""
    from ...core import hashcache
    hc = _HASHCACHES.get(assets_dir)
    if hc is None:
        hc = _HASHCACHES[assets_dir] = hashcache.load(assets_dir)
    rel = os.path.relpath(path, assets_dir).replace(os.sep, "/")
    return hashcache.md5_for(path, rel, hc)


def _save_hashcache(assets_dir):
    """Persist the scan's hash cache (best-effort, like the sidecar itself)."""
    from ...core import hashcache
    hc = _HASHCACHES.get(assets_dir)
    if hc is not None:
        hashcache.save(assets_dir, hc)


def _changed_videos(assets_dir, baseline):
    """Return ``[(fname, card_path, staged_path), ...]`` for the videos under
    ``assets_dir/video`` whose current bytes differ from the Extract baseline
    (``.checksums.md5``).  Empty when there's no ``video/manifest.txt`` (an
    audio-only extract, or Write pointed at a subfolder)."""
    vid_dir = os.path.join(assets_dir, "video")
    manifest = os.path.join(vid_dir, _VIDEO_MANIFEST)
    if not os.path.isfile(manifest):
        return []
    out = []
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            fname, card_path = cols[0], cols[1]
            staged = os.path.join(vid_dir, fname)
            if not os.path.isfile(staged):
                continue
            base = baseline.get("video/" + fname)
            if base is not None and _scan_md5(assets_dir, staged) == base:
                continue               # untouched since extract
            out.append((fname, card_path, staged))
    return out


def _resolve_card_nodes(reader, card_paths, cancel):
    """One filesystem pass: ``{card_path: inode}`` for the wanted card paths.
    Shared by the video + image in-place patch paths."""
    want = set(card_paths)
    found = {}
    if not want:
        return found
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            break
        if path in want:
            found[path] = node
            if len(found) == len(want):
                break
    return found


def _fit_video_payload(staged_path, target, work_dir, log):
    """Return exactly *target* bytes to overwrite the original ``.asset``, or
    ``None`` if the replacement can't be made to fit.  A clip ``<= target``
    pads up with a trailing free box; a larger clip is re-encoded down to the
    byte budget first (and skipped if even that overshoots)."""
    with open(staged_path, "rb") as f:
        data = f.read()
    name = os.path.basename(staged_path)
    if len(data) <= target:
        return _pad_isobmff(data, target)

    from ...core.video import detect_video_info, shrink_video_to_size
    tmp = os.path.join(work_dir, "fit_" + name)
    info = detect_video_info(staged_path)
    ok, detail = shrink_video_to_size(staged_path, tmp, target,
                                      original_info=info)
    if not ok:
        log("Video %s is %d bytes but the original slot is only %d and it "
            "couldn't be shrunk to fit (%s); skipped (left unchanged). Use a "
            "shorter / lower-resolution clip."
            % (name, len(data), target, detail), "warning")
        return None
    try:
        with open(tmp, "rb") as f:
            shrunk = f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if len(shrunk) > target:
        log("Video %s still too large after re-encode; skipped." % name,
            "warning")
        return None
    log("Video %s re-encoded to fit (%d -> %d bytes of %d)."
        % (name, len(data), len(shrunk), target), "info")
    # Warn when the byte slot forces a bitrate so low the result will look
    # blocky/scrambled — the on-card slot is fixed-size, so a big clip in a
    # tiny slot (e.g. a 456 KB attract background) can't keep its quality.
    # Judge by bits-per-pixel-per-second (resolution-aware): H.264 looks poor
    # below ~0.03 bpp regardless of absolute bitrate.  The bar lives in
    # core.video_quality, which re-measures finished cards by the same rule —
    # a report that disagreed with this warning would be worse than none.
    from ...core.video_quality import BLOCKY_BPP
    if info and info.width > 0 and info.height > 0:
        dur = info.duration if info.duration and info.duration > 0 else 0
        if dur > 0:
            bitrate = len(shrunk) * 8 / dur
            fps = info.fps if info.fps and info.fps > 0 else 30.0
            bpp = bitrate / (info.width * info.height * fps)
            if bpp < BLOCKY_BPP:
                slot_str = ("%.1f MB" % (target / 1e6) if target >= 1e6
                            else "%d KB" % (target / 1024))
                log("Video %s: the on-card slot is only %s, so this clip had "
                    "to be squeezed to ~%d kbps (%dx%d, %.0fs) — it will look "
                    "very blocky. This slot is too small for a full-quality "
                    "replacement; use a shorter or lower-resolution clip for "
                    "it."
                    % (name, slot_str, bitrate / 1000,
                       info.width, info.height, dur), "warning")
    return _pad_isobmff(shrunk, target)


def _same_bytes(a, b):
    """Whether two files hold identical bytes.  Sizes first, so the usual
    "these are obviously different" answer costs two stats and no reading."""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                ca, cb = fa.read(1 << 20), fb.read(1 << 20)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def _size(path):
    """File size in bytes, 0 when it can't be read (log text only)."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _intact_copy_source(src, staged, fname, slot_size, log, verdict=None):
    """Pick which file may be copied onto the card verbatim for *fname*, and
    log the one line that says which it was and why.  *verdict* is
    :func:`_intact_verdict`'s answer when the build's pre-flight already
    settled it (:class:`_SpaceCheck`), so the clip is not probed twice.

    The intact path exists to keep a full-quality replacement off the byte-fit
    re-encoder, and it does that by copying the user's *assigned* file — but
    that file is whatever they picked in the file dialog, in whatever format
    their encoder produced.  The machine's decoder is an i.MX6 VPU, not a
    desktop player: hand it a Matroska container, HEVC, a 10-bit / 4:2:2
    stream, or a resolution the scene never sized a surface for, and the
    demuxer still finds the sound (which plays) while the picture stays
    **black**.  That is not a quality trade-off, it's a broken asset, and the
    user doesn't find out until the game is running.

    So a source only goes on the card untouched when it really is a drop-in
    for the clip already there: an ISO-BMFF container (MP4 or QuickTime, the
    machine reads either), H.264, 8-bit 4:2:0, the
    slot's own resolution and frame rate, and an H.264 profile no higher than
    the slot's own (that clip is a decode CEILING — every re-encode is pinned
    to it, so the intact path can't be the one place a higher one gets
    through).  *staged* is the yardstick for the last three — Replace-Video
    already format-matched it to this exact slot, so its geometry *is* the
    slot's (and when the user's file needed no conversion, or they ticked "no
    conversion", *staged* is a byte-copy of *src* and every check passes
    trivially).

    Anything failing a check falls back to *staged*, which still grows to full
    size on the card; the only thing lost is the re-encode the user's own file
    would have avoided (and when Replace-Video only had to repackage it, not
    even that).  Returns the path to copy (``src`` or ``staged``).
    """
    def _accept():
        log("Video %s: replacing the slot with the intact %d B original (slot "
            "was %d B) — full quality, no re-encode."
            % (fname, _size(src), slot_size), "info")
        return src

    def _reject(why):
        # "No conversion" makes *staged* a byte-copy of *src*, so there is no
        # format-matched copy to fall back TO — the rejected clip goes on the
        # card either way.  Saying "writing the format-matched copy instead"
        # there was simply untrue, and it was the only thing standing between
        # a tester and an attract video that played black on the machine with
        # nothing in the log to explain it (batch 23).  Same bytes = say so,
        # as an error, and name what decides it.
        if _same_bytes(src, staged):
            log("Video %s: %s. Nothing converted it — either \"Use my files "
                "as-is\" is ticked on the Video tab or ffmpeg isn't installed "
                "— so your file goes on the card untouched and the machine "
                "will play its sound over a black picture. Untick the box (or "
                "install ffmpeg) and Build again to have it converted."
                % (fname, why), "error")
            return staged
        # Not a failure: the user left conversion on, so the format-matched
        # copy is exactly what they asked for and it goes on at full size.
        # This used to log a black-picture WARNING plus a second line saying
        # the same thing, which read like something had gone wrong when the
        # build was doing the right thing (a tester).
        log("Video %s: %s, so the app's format-matched %d B copy goes on the "
            "card instead of your file (slot was %d B) — full size, no "
            "byte-budget crush." % (fname, why, _size(staged), slot_size),
            "info")
        return staged

    # Container: ISO-BMFF or nothing.  The MP4-vs-QuickTime BRAND inside it is
    # not part of the test, though — the machine reads both.  This gate used to
    # demand the card's own brand (".mov" slots wanted "qt  "), on the
    # reasonable-sounding theory that the wrapper is part of what the VPU's
    # demuxer reads.  It isn't: a tester copied MP4-branded clips straight onto
    # his Beatles card in place of the QuickTime ones and "they all played back
    # without an issue", and PAD's own extract of that working card names 228
    # of them .mp4 — 228 clips a machine has been playing for months.  The
    # brand cost him every one of those: each was rejected here, so the app's
    # own re-encode went on instead, a generation of quality lost (and most of
    # them BIGGER than the clip they replaced) to fix four bytes of ftyp.
    ok, why = verdict if verdict is not None else _intact_verdict(src, staged)
    return _accept() if ok else _reject(why)


def _intact_verdict(src, staged):
    """``(True, None)`` when the user's file *src* may go on the card as it
    is in place of the clip *staged* was converted for, else ``(False, why)``
    (see :func:`_intact_copy_source`).  A 12-byte read and up to two
    ffprobes, and no log: the build's pre-flight asks it for every clip
    before the encode, to know which file goes on (:class:`_SpaceCheck`)."""
    from ...core import video as _video
    brand = _video.isobmff_brand(src)
    if brand is None:
        return False, ("%s isn't an MP4/QuickTime container like the clip it "
                       "replaces" % os.path.basename(src))

    info = _video.detect_video_info(src)
    if info is None:
        return True, None     # no ffprobe/ffmpeg — the container check stands
    codec = (info.vcodec or "").lower()
    if codec and codec != "h264":
        return False, "it's %s and Spike 2 plays H.264" % codec.upper()
    if (info.pix_fmt or "") not in _video.SAFE_PIX_FMTS:
        return False, ("it's %s and the machine's decoder handles only 8-bit "
                       "4:2:0" % info.pix_fmt)

    slot = _video.detect_video_info(staged)
    if slot is None or not slot.width or not slot.height:
        return True, None     # nothing to compare against; the above stands
    if (info.width, info.height) != (slot.width, slot.height):
        return False, ("it's %dx%d and this slot's clip is %dx%d"
                       % (info.width, info.height, slot.width, slot.height))
    if slot.fps > 0 and info.fps > 0 and abs(info.fps - slot.fps) > 0.5:
        return False, ("it runs at %.3g fps and this slot's clip is %.3g fps"
                       % (info.fps, slot.fps))
    # Profile is a decode ceiling, not a preference: Replace-Video pins every
    # re-encode to the slot's own profile for exactly this reason, so the
    # intact path can't be the one place a higher one slips through.
    rank, slot_rank = _video.profile_rank(info), _video.profile_rank(slot)
    if rank is not None and slot_rank is not None and rank > slot_rank:
        return False, ("it's H.264 %s profile and this slot's clip is %s — "
                       "above what the slot proves the machine decodes"
                       % (info.profile, slot.profile))
    return True, None


def _prepare_video_patches(reader, video_edits, work_dir, log, cancel,
                           originals=None, dest_is_device=False,
                           verdicts=None, grow_check=None):
    """Resolve each changed video to its card inode and prepare it for Write.

    Returns ``([(node, payload), ...], n_skipped, grow_jobs)``.  Any video with
    an assignable ORIGINAL is returned as a job ``(card_rel, source_file)`` for
    the caller to copy in INTACT via the ext4 driver (the file's inode grows OR
    shrinks to the source size).  This keeps the user's exact bytes on the card
    — full quality, and the form the game's content validation accepts: *any*
    re-encode is rejected, including the container remux that a clip which
    already "fits" its slot would otherwise get.  Only videos without an
    assignable original (or when the ext4 driver isn't reachable, or a direct-SD
    write) fall back to the old size-fit-in-place patch.

    *originals* maps the extract rel (``video/<name>``) to the user's assigned
    replacement file; the intact copy uses that source, never the transcoded
    staged copy.  *verdicts* (``{fname: _intact_verdict's answer}``) and
    *grow_check* (``ext4_grow.available()``'s) are what the build's
    pre-flight already asked (:class:`_SpaceCheck`), so neither is asked
    twice."""
    originals = originals or {}
    verdicts = verdicts or {}
    nodes = _resolve_card_nodes(reader, [cp for (_f, cp, _s) in video_edits],
                                cancel)

    # Classify: a video with an assigned original is replaced INTACT (via the
    # ext4 driver); one without falls back to the size-fit raw patch.
    intact, fit = [], []      # intact: (fname, card_path, node, src, staged)
    skipped = 0
    for fname, card_path, staged in video_edits:
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Video %s: its original (%s) wasn't found on the card; "
                "skipped." % (fname, card_path), "warning")
            skipped += 1
            continue
        src = originals.get("video/" + fname)
        if src and os.path.isfile(src):
            intact.append((fname, card_path, node, src, staged))
        else:
            fit.append((fname, card_path, node, staged))

    can_grow = False
    if intact and dest_is_device:
        log("%d replaced video(s) will be re-encoded to fit their slots for a "
            "direct-SD write. Build an image file and flash it instead to keep "
            "them full quality (and pass the game's content validation)."
            % len(intact), "warning")
    elif intact:
        from ...core import ext4_grow
        can_grow, why = grow_check or ext4_grow.available()
        if not can_grow:
            log("Can't replace videos intact on this system (%s); they'll be "
                "re-encoded to fit their slots instead (lower quality)." % why,
                "warning")

    patches, grow_jobs = [], []
    for fname, card_path, node, src, staged in intact:
        if can_grow:
            # Logs its own one-line verdict (which file, and why that one).
            source = _intact_copy_source(src, staged, fname, node["size"], log,
                                         verdict=verdicts.get(fname))
            grow_jobs.append((card_path.lstrip("/"), source))
        else:
            fit.append((fname, card_path, node, staged))

    for fname, card_path, node, staged in fit:
        payload = _fit_video_payload(staged, node["size"], work_dir, log)
        if payload is None:
            skipped += 1
            continue
        patches.append((node, payload))
        log("Video %s: ready to patch (%d bytes)." % (fname, node["size"]),
            "info")
    return patches, skipped, grow_jobs


# --------------------------------------------------------------------------
# Replace-Image: size-neutral in-place patch of the loose .png files
# --------------------------------------------------------------------------
_IMAGE_MANIFEST = "manifest.txt"


def _pad_image(data, target):
    """Pad image bytes up to exactly *target* by appending trailing zero bytes,
    which image decoders ignore after the data's end marker (PNG ``IEND`` /
    JPEG ``EOI`` / GIF trailer).  ``len(data)`` must be ``<= target``."""
    pad = target - len(data)
    if pad <= 0:
        return data[:target]
    return data + b"\x00" * pad


def _changed_images(assets_dir, baseline):
    """Return ``[(output, card_path, staged_path), ...]`` for the images under
    ``assets_dir/images`` whose current bytes differ from the Extract baseline
    (``.checksums.md5``).  Empty when there's no ``images/manifest.txt``.
    *output* is the forward-slash path under ``images/`` (mirrors the card)."""
    return _changed_listed_images(assets_dir, baseline, _IMAGE_MANIFEST)


def _changed_boot_images(assets_dir, baseline):
    """:func:`_changed_images` for the boot screen (``images/boot_screen/``,
    with its own manifest because the files are on the OS partition).  Empty
    for an extract made before the boot screen was extracted."""
    return _changed_listed_images(
        assets_dir, baseline, _BOOT_IMAGE_SUBDIR + "/" + _IMAGE_MANIFEST)


def _changed_listed_images(assets_dir, baseline, manifest_rel):
    """The rows of ``images/<manifest_rel>`` whose staged file differs from
    the Extract baseline -> ``[(output, card_path, staged_path), ...]``."""
    img_dir = os.path.join(assets_dir, "images")
    manifest = os.path.join(img_dir, *manifest_rel.split("/"))
    if not os.path.isfile(manifest):
        return []
    out = []
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            output, card_path = cols[0], cols[1]
            staged = os.path.join(img_dir, *output.split("/"))
            if not os.path.isfile(staged):
                continue
            base = baseline.get("images/" + output)
            if base is not None and _scan_md5(assets_dir, staged) == base:
                continue               # untouched since extract
            out.append((output, card_path, staged))
    return out


def _changed_music_banks(assets_dir, baseline):
    """Per-song music-bank WAVs (``music_catNN_*.wav``) whose bytes differ from
    the Extract baseline — i.e. the user edited/replaced a song.  These live in
    the ``image-scNN.bin`` banks, which Write re-encodes in place (size-neutral)
    via :func:`_compute_music_patches`; a song whose re-encode isn't bit-exact is
    skipped there with a warning rather than written blind.  The
    ``music_catNN_MMMM`` prefix survives an Auto-transcribe / Music-ID rename, so
    it's the stable per-song key.  Empty when there's no baseline."""
    base = {}
    for rel in baseline:
        mm = _MUSIC_WAV_RE.match(os.path.splitext(os.path.basename(rel))[0])
        if mm:
            base[mm.group(1).lower()] = baseline[rel]
    if not base:
        return []
    changed = []
    for root, _dirs, files in os.walk(assets_dir):
        for fn in files:
            if not fn.lower().endswith(".wav"):
                continue
            mm = _MUSIC_WAV_RE.match(os.path.splitext(fn)[0])
            if not mm:
                continue
            path = os.path.join(root, fn)
            if _scan_md5(assets_dir, path) != base.get(mm.group(1).lower()):
                changed.append(path)
    return changed


def _select_changed_idx_wavs(assets_dir, baseline):
    """Map ``idx -> path`` for every changed ``idxNNNN.wav`` under *assets_dir*.

    Several files can share one idx: re-extracting into a folder that still
    holds the prior run's Auto-transcribe / Music-ID *renamed* copies leaves
    both ``idx0001.wav`` and ``idx0001 - music.wav`` (identical content, same
    leading index).  Both map to ONE on-card sound at Write, so when the user
    edits one twin we must pick the EDITED file: a plain ``dict[idx] = path``
    keyed by os.walk order silently dropped the edit whenever the *unedited*
    twin was walked last.  Here we group by idx and choose the twin whose bytes
    differ from the ``.checksums.md5`` baseline; an idx with no differing twin
    is unchanged and skipped.
    """
    by_idx = {}  # idx -> [path, ...]
    for root, _dirs, files in os.walk(assets_dir):
        # Never walk the .orig snapshot mirror — it holds pristine copies of
        # edited sounds (== baseline), which would otherwise register as extra
        # twins for their idx (harmless, but wasteful to hash).
        _dirs[:] = [d for d in _dirs if not d.startswith(".")]
        for fn in files:
            if not fn.lower().endswith(".wav"):
                continue
            idx = _wav_idx(os.path.splitext(fn)[0])
            if idx is not None:
                by_idx.setdefault(idx, []).append(os.path.join(root, fn))
    base_by_idx = {}
    for rel in baseline:
        idx = _wav_idx(os.path.splitext(os.path.basename(rel))[0])
        if idx is not None:
            base_by_idx[idx] = baseline[rel]

    edits = {}
    for idx, paths in by_idx.items():
        base = base_by_idx.get(idx)
        if base is None:
            # No baseline for this idx (no .checksums.md5, or a brand-new
            # file) — treat it as an edit; one representative path is enough.
            edits[idx] = paths[-1]
            continue
        for path in paths:
            if _scan_md5(assets_dir, path) != base:
                edits[idx] = path
                break
    return edits


def _fmt_idx_list(idxs, cap=80):
    """``idx0006, idx0021, …`` for a collection of integer sound indices,
    sorted ascending and truncated to *cap* entries (``… and N more``).

    The Write log enumerates exactly which sounds it's about to re-encode so a
    count that's larger than the user expects is never a mystery: a sound that
    was edited/replaced in an *earlier* session is still on disk (differs from
    the Extract baseline), so it's correctly carried into this build — seeing
    its idx in the list makes that obvious instead of an unexplained +N."""
    idxs = sorted(idxs)
    shown = ", ".join("idx%04d" % i for i in idxs[:cap])
    if len(idxs) > cap:
        shown += ", … and %d more" % (len(idxs) - cap)
    return shown


# --------------------------------------------------------------------------
# Replace display text: size-neutral in-place patch of the .radium strings
# --------------------------------------------------------------------------
def _changed_radium_text(assets_dir):
    """Parse ``text/strings.tsv`` and return the user's edits grouped by radium:
    ``{radium_card_path: [(original, replacement), ...]}`` for every row whose
    ``replacement`` differs from ``original``.

    The first two columns (card path, original) are the stable key (the on-card
    radium is unchanged, so its offsets are re-derived at Write time); only rows
    that were actually edited are returned.  Empty when there's no manifest."""
    from ...core import text_manifest
    return text_manifest.changed(assets_dir)


def _mode_family_on():
    """Does this run's Write take the MODE EDITOR FAMILY's paths - the project's modes,
    the game's own modes (item 145), and what they changed in the sound grow (the
    appended records' chain encode, the play-table key mask and declared durations)?
    Only with the preview switch on (Help > Preview features, ``mode_write.preview_on``).
    Off, every one of those places takes the path a build without the family takes, so a
    copy of the app without a code writes what main writes.  Never raises."""
    try:
        from . import mode_write
        return mode_write.preview_on()
    except Exception:                                   # noqa: BLE001
        return False


def _stock_mode_pending(assets_dir):
    """How many of the game's own modes' numbers the project has staged (item
    145; :func:`.stock_modes.pending_count`); 0 with the preview switch off
    (:func:`_mode_family_on`).  Never raises."""
    if not _mode_family_on():
        return 0
    try:
        from . import stock_modes
        return stock_modes.pending_count(assets_dir)
    except Exception:
        return 0


def _stock_mode_managed(assets_dir):
    """True when the project manages the game's own modes (item 145), even
    with every number back at stock; False with the preview switch off.
    Never raises."""
    if not _mode_family_on():
        return False
    try:
        from . import stock_modes
        return stock_modes.manages(assets_dir)
    except Exception:
        return False


def _stock_mode_words_to_restore(disk_f, parts, assets_dir):
    """How many of the game's own modes' numbers the Write puts back to stock
    on the card it builds FROM, for a project that manages them with nothing
    staged: that card holds our words (a card this app built, used as the
    original).  Only asked when nothing else is to be written.  Never
    raises."""
    try:
        if not _stock_mode_managed(assets_dir):
            return 0
        from . import stock_modes
        reader, fw_node, _img = _locate(disk_f, parts)
        return stock_modes.restore_count(reader, fw_node, assets_dir)
    except Exception:
        return 0


def _stock_mode_restore_ok(assets_dir, output_path, prev=None):
    """True when a Write with NOTHING to write should put the build at
    *output_path* back to the original card instead of refusing (item 145).

    A person who stages a stock mode's award, builds, then puts the award
    back to Stock and presses Write expects the card to come back to stock.
    Refusing ("Nothing to write") left our words on the card; on a whole
    build it also deleted the output the copy had already started over.  So
    when the project manages the game's own modes and the record beside the
    output is a finished build of THIS project, the Write goes ahead with no
    edits: an update puts the last build's in-place bytes back to stock, a
    whole build leaves a copy of the original.  *prev* is the record
    :func:`write_image` already read (read here when it has none).  Never
    raises."""
    try:
        if not _stock_mode_managed(assets_dir):
            return False
        if not os.path.isfile(_lp(output_path)):
            return False
        rec = prev or read_build_manifest(output_path)
        if not rec or rec.get("building"):
            return False
        return (os.path.normcase(os.path.abspath(str(rec.get("assets") or "")))
                == os.path.normcase(os.path.abspath(str(assets_dir))))
    except Exception:
        return False


class _WriteCounts(tuple):
    """The Write's ``(audio, video, image, text)`` counts, unchanged as a
    tuple (it unpacks, compares and serialises exactly as before), carrying
    what the four don't name (item 145): ``stock_modes``, how many numbers
    of the game's own modes the Write changed (words and staged timer
    defaults written into the game program, back to stock included),
    and ``restored``, True when a Write with nothing staged put this
    project's build back to the original.  The completion dialog reads both
    (``pipeline._write_summary``), so a Write whose only change was a timer
    or an award no longer reports "no changes"."""

    stock_modes = 0
    restored = False


def _with_stock_modes(counts, n=0, restored=False):
    """*counts* as a :class:`_WriteCounts` carrying *n* and *restored*."""
    out = _WriteCounts(tuple(counts))
    out.stock_modes = int(n or 0)
    out.restored = bool(restored)
    return out


def _compute_patches_or_restore(restore_ok, log, *args, **kwargs):
    """:func:`_compute_patches`, except that its "Nothing to write" becomes an
    empty build when *restore_ok* (:func:`_stock_mode_restore_ok`)."""
    try:
        return _compute_patches(*args, **kwargs)
    except _NothingToWrite:
        if not restore_ok:
            raise
    log("Nothing is staged any more (the game's own modes are all back at "
        "stock), so this Write puts the card back to the original: the last "
        "build's changes come out.", "info")
    return [], _with_stock_modes((0, 0, 0, 0), 0, restored=True), None, None, None


def _program_text_writes(reader, node, card_path, pairs, patched_fw, log,
                         grow=None):
    """Resolve game-program (ELF) display-text edits for one firmware file.

    Three composition modes, mirroring how the firmware itself reaches the
    card:

    * normally the ELF is untouched on disk, so the string/pointer patches are
      emitted as in-place disk writes plus a file-relative overlay for the
      ``.sidx`` digest refresh (same shape as the radium text overlays);
    * when the blip-free audio cave rebuilt the firmware (*patched_fw* — a
      staged whole-file copy that later replaces the on-card ELF), an in-place
      disk write would be undone by that copy, so the edits are applied
      directly INTO the staged file instead; its ``.sidx`` record is computed
      from the file, so the digests cover the text automatically;
    * when an edit is LONGER than its slot and *grow* allows it
      (``{"ok": bool, "why": str, "dir": scratch dir}`` — see
      :func:`_text_grow_gate`), the original bytes stay, the new text goes
      into the ELF's program-text extension segment (appended here, or
      extended when a previous Write left one — including one riding next to
      the cave's) and every reference is repointed; the validator bypass is
      baked into the same bytes when no cave did that already, and the whole
      grown file is staged 0755 under ``grow["dir"]`` for the ext4 grow job,
      exactly the cave's delivery.  A fitting edit still patches in place.

    Returns ``(writes, n_strings, overlays, grown)`` — *grown* is ``None``
    unless the firmware was grown, else ``{"node", "path", "valpatch_mode",
    "new"}`` (*valpatch_mode* only when the bypass was baked here)."""
    from . import progtext

    if patched_fw is not None:
        with open(_lp(patched_fw), "rb") as f:
            raw = f.read()
    else:
        raw = reader.read_file_bytes(node)
    edits = dict(pairs)
    # Only an edit longer than its original can need new space (a longer
    # standalone name grows its host line too, and is itself longer).
    over = [o for o, n in edits.items() if len(n) > len(o)]
    reloc = None
    # Why longer text has nowhere to go, carried into plan_writes so each
    # skipped line names the WRITE's limit instead of blaming itself.
    no_grow_why = ""
    if over and grow is not None:
        if grow.get("ok"):
            reloc, why = _text_reloc_plan(raw)
            if reloc is None:
                no_grow_why = why
                log("Program text: %d edit(s) are longer than the original and "
                    "can't be placed in new space in %s (%s); they are skipped "
                    "— same-length edits still land in place."
                    % (len(over), card_path, why), "warning")
        else:
            no_grow_why = grow.get("why") or "growth unavailable"
            log("Program text: %d edit(s) are longer than the original and "
                "can't be placed in new space for this write (%s); they are "
                "skipped — same-length edits still land in place."
                % (len(over), no_grow_why), "warning")
    file_writes, n, blob = progtext.plan_writes(raw, edits, log, reloc=reloc,
                                                no_grow_why=no_grow_why)
    if blob:
        try:
            grown = _grow_program_text(raw, file_writes, blob, reloc,
                                       patched_fw, grow["dir"], node, log)
            return [], n, {}, grown
        except Exception as e:                  # never fail a Write over this
            log("Program text: couldn't place the longer text in new space "
                "(%s); those edits are skipped and the rest patched in place."
                % e, "warning")
            file_writes, n, blob = progtext.plan_writes(
                raw, edits, log,
                no_grow_why="placing longer text in new space failed (%s)" % e)
    if not file_writes:
        return [], n, {}, None
    if patched_fw is not None:
        buf = bytearray(raw)
        for off, b in file_writes:
            buf[off:off + len(b)] = b
        with open(_lp(patched_fw), "wb") as f:
            f.write(bytes(buf))
        log("Program text: %d string edit(s) baked into the rebuilt firmware."
            % n, "info")
        return [], n, {}, None
    writes = []
    ov = {}
    ib = bytes(node["i_block"])
    for off, b in file_writes:
        payload = b
        for disk, cnt in reader.disk_ranges(node, off, len(b)):
            writes.append((disk, payload[:cnt]))
            payload = payload[cnt:]
        ov.setdefault(ib, (node, {}))[1][off] = b
    return writes, n, ov, None


def _grow_program_text(raw, file_writes, blob, reloc, patched_fw, grow_dir,
                       node, log):
    """Build the grown firmware: *blob* into the extension segment (appended,
    or extended after its used part), *file_writes* applied, the validator
    bypass baked in when no cave has already (the cave's staged file carries
    it), the whole file staged 0755.  Returns the ``grown`` record
    :func:`_program_text_writes` hands back."""
    from . import progreloc
    buf = bytearray(raw)
    stock_len = len(raw)
    seg = _find_extension_segment(buf)
    if seg is None:
        va, off, _gap = _append_extension_segment(
            buf, progreloc.EXT_HEADER_LEN + len(blob), 4, near_fn=None,
            allow_above=False, what="program-text segment",
            slots=(_PT_GNU_STACK, _PT_NOTE))
        used = progreloc.EXT_HEADER_LEN
        if va != reloc["base_va"]:
            raise RuntimeError(
                "the text segment landed at 0x%x, not the planned 0x%x"
                % (va, reloc["base_va"]))
        how = "in a new segment"
    else:
        va, off, _size, used = _extend_extension_segment(buf, len(blob))
        how = "appended to the existing segment"
    buf[off + used:off + used + len(blob)] = blob
    buf[off:off + progreloc.EXT_HEADER_LEN] = progreloc.extension_header(
        used + len(blob))
    for o, b in file_writes:
        buf[o:o + len(b)] = b
    vmode = None
    if patched_fw is None:
        # The whole file is copied onto the card, so the validator bypass has
        # to be in these bytes (the in-place bypass write is skipped by the
        # caller whenever a staged firmware exists).
        from . import valpatch as _vp
        overlay, vmode = _vp.bypass_overlay(bytes(buf))
        for o, b in overlay.items():
            buf[o:o + len(b)] = b
        _vp.log_status(log, vmode)
        staged = os.path.join(grow_dir, "game_text_grown")
    else:
        staged = patched_fw
    with open(_lp(staged), "wb") as f:
        f.write(bytes(buf))
    # The card's game_monitor execs this file: 0644 (open's default) would be
    # EACCES and "RESTARTING GAME" forever on a host whose ext4 path creates
    # the inode with the source's mode (macOS debugfs).
    os.chmod(_lp(staged), 0o755)
    log("Program text: %d byte(s) of longer text placed in the game program's "
        "extension segment at 0x%x (%s, file+0x%x, read-only); the game "
        "program grows %d -> %d bytes and is written whole. No card built "
        "this way has been booted on a machine yet — it is proven in the PC "
        "emulator only."
        % (len(blob), va + used, how, off + used, stock_len, len(buf)),
        "warning")
    return {"node": node, "path": staged, "valpatch_mode": vmode,
            "new": patched_fw is None}


def _text_grow_gate(dest_is_device):
    """``(ok, why)`` — may this write place longer display text in new space
    (a grown game ELF / a re-serialised scene)?  Mirrors
    :func:`_pathA_preflight`: a longer file only reaches the card through the
    Linux ext4 driver, so never on a direct-SD write and never on a host
    without one.  ``PAD_STERN_TEXT_GROW=0`` is the kill switch (on by
    default)."""
    if os.environ.get("PAD_STERN_TEXT_GROW", "1") == "0":
        return False, "PAD_STERN_TEXT_GROW=0"
    if dest_is_device:
        return False, ("a direct-SD write can't grow the game program; build "
                       "an image file")
    ok, why = _ext4_can_grow()
    if not ok:
        return False, ("this system can't grow files inside an ext4 image "
                       "(%s)" % why)
    return True, ""


def _image_grow_gate(dest_is_device):
    """``(ok, why)`` — may this write give a scene's embedded image a new SIZE
    (the scene re-serialised around it, :func:`radium_grow.regrow`)?  The same
    conditions as longer scene text: an image build, and a host that can grow
    a file inside an ext4 image.  ``PAD_STERN_IMAGE_GROW=0`` is the kill
    switch (on by default: nothing resizes unless the user kept a replacement's
    own size)."""
    if os.environ.get("PAD_STERN_IMAGE_GROW", "1") == "0":
        return False, "PAD_STERN_IMAGE_GROW=0"
    if dest_is_device:
        return False, ("a direct-SD write can't change a scene's size; build an "
                       "image file")
    ok, why = _ext4_can_grow()
    if not ok:
        return False, ("this system can't grow files inside an ext4 image "
                       "(%s)" % why)
    return True, ""


def _audio_grow_gate(dest_is_device, gr_path=None):
    """``(ok, why)`` — may this write place a replacement callout LONGER than
    its stock slot in new space at the end of the sound bank?

    Off unless ``PAD_STERN_AUDIO_GROW=1`` asks for it: a grown sound bank is
    confirmed playing on a real machine, but it is opt-in because it changes
    the build (an image build only) rather than something to do on every
    write without asking.  Beyond the flag it needs the
    same things a longer game program needs — an image build, and a host that
    can grow a file inside an ext4 image — plus a firmware whose codec objects
    carry their own length, which is what lets a sound decode past its stock
    range at all.  A closed gate is never an error: the sound is fitted to its
    slot exactly as it is today and the log says why."""
    if os.environ.get("PAD_STERN_AUDIO_GROW") != "1":
        # Name the switch: the default is off, so this is the reason nearly
        # every trim gives, and a user who handed over a whole song has no
        # other way to learn the option exists (PAD-174).
        return False, ("longer replacements are off; to keep them whole, tick "
                       "\"Allow replacements longer than the original\" "
                       "under the Audio tab's Advanced... and build an "
                       "image file")
    if dest_is_device:
        return False, ("a direct-SD write can't grow the sound bank; build an "
                       "image file")
    ok, why = _ext4_can_grow()
    if not ok:
        return False, ("this system can't grow files inside an ext4 image "
                       "(%s)" % why)
    from .spike2.emulator import firmware_build_supported
    if gr_path is not None and firmware_build_supported(gr_path):
        # The validated build's chain replay rebuilds each codec object from
        # the record instead of replaying a raw one, so ``codec.extend_length``
        # returns None there and the encoder cannot drive a sound past its
        # stock range.  Every other title takes the generic path and can.
        return False, ("this game version's audio engine is the one build "
                       "whose sounds can't be driven past their original "
                       "length")
    return True, ""


def _grown_source_gate(params):
    """``(ok, why)`` — may this write grow a sound bank that an EARLIER build
    already grew?  Not yet: *params* are the source card's, and any row with
    ``shadows`` is a sound that build lengthened.

    Growing assumes a stock bank, twice over.  Each appended body starts right
    after the record array, so one more record overlaps the first body an
    earlier build appended.  And that build re-pointed the play tables at its
    appended records' keys, while the grow copies and re-points from the
    STOCK record, a key no table carries any more.  Growing Godzilla Pro
    1.16's main-play music on a card a v0.219.5 build had already grown
    failed with "idx 7: no descriptor in the game's play tables names this
    sound's record" (PAD-176; PAD-175 reproduced it on LE 1.16).

    Closed, nothing is lost that the card has: a sound grown earlier keeps
    its longer slot (the collapsed params give its live length), so a
    replacement up to that length still goes on whole."""
    n = sum(1 for p in params if p.get("shadows") is not None)
    if not n:
        return True, ""
    return False, ("this card's sound bank was already grown by an earlier "
                   "build (%d longer sound(s), which keep their length), and "
                   "a build can't grow it a second time; to lengthen more, "
                   "build onto a card that was never grown, such as the "
                   "stock card" % n)


#: A trim that cuts at least this much (card samples) off a replacement is a
#: warning rather than a note: that is part of a song gone, not the tail of a
#: callout that ran a little long, which is the everyday case the trim is for.
_TRIM_WARN_SAMPLES = 44100


def _trimmed_notice(grows, why):
    """``(message, level)`` for the replacements in *grows* (idx -> ``(room,
    wanted)`` in samples, from :func:`_classify_audio_edits`) that this write
    trims because it can't grow the bank; *why* is the gate's reason.

    Every trimmed sound is named with its length before and after, the
    biggest cut first.  The line used to give only a count, so a user who
    replaced a looping music bed with a whole song found out it had been cut
    to the loop's length by extracting the card (PAD-174)."""
    order = sorted(grows, key=lambda i: (grows[i][0] - grows[i][1], i))
    names = ", ".join("idx %d (%.2f s cut to %.2f s)"
                      % (i, grows[i][1] / 44100.0, grows[i][0] / 44100.0)
                      for i in order)
    worst = max(want - room for room, want in grows.values())
    return ("%d replacement(s) run past their original sound's length and "
            "are trimmed to fit: %s. Trimmed: %s."
            % (len(grows), why, names),
            "warning" if worst >= _TRIM_WARN_SAMPLES else "info")


def _asset_path(assets_dir, wav):
    return wav if os.path.isabs(wav) else os.path.join(assets_dir or "", wav)


def _wav_frames_44k(path):
    """A WAV's length in card samples (44.1 kHz), or ``None`` if it can't be
    read cheaply.

    Resampling happens later, inside the encoder; this only has to be right
    about whether the clip runs past its slot."""
    try:
        w = wave.open(_lp(path), "rb")
        try:
            n, rate = w.getnframes(), w.getframerate()
        finally:
            w.close()
        if not n or not rate:
            return None
        return int(round(n * 44100.0 / rate))
    except Exception:
        return None


def _classify_audio_edits(byidx, audio_edits, assets_dir):
    """Split the user's sound replacements into ``(fits, grows)``.

    ``grows`` maps idx -> ``(room, wanted)`` in samples for every replacement
    whose audio runs past what its slot can emit.  Costs a header read per
    file, and has to run before the encode cache is consulted: a clip that was
    fitted on the last build has a cached body for the STOCK slot, and
    replaying that into a grown build would write the trimmed version."""
    from .spike2.emulator import emitted_length
    fits, grows = {}, {}
    for idx, wav in audio_edits.items():
        p = byidx.get(idx)
        want = _wav_frames_44k(_asset_path(assets_dir, wav)) if p else None
        room = emitted_length(p.get("length", 0)) if p else 0
        if want is None or want <= room:
            fits[idx] = wav
        else:
            grows[idx] = (room, want)
    return fits, grows


def _radium_text_writes(reader, assets_dir, log, cancel, patched_fw=None,
                        grow_dir=None, dest_is_device=False):
    """Resolve the user's display-text edits to a flat list of in-place writes
    ``[(disk_offset, bytes), ...]`` (same form ``_compute_patches`` collects).

    For each changed radium: resolve its inode, read it back, **re-enumerate**
    the unchanged on-card bytes for the authoritative offsets, and for every
    edit ``(original -> replacement)`` patch **all** display-text occurrences
    whose value equals ``original``.  A replacement that fits the original's
    byte budget is space-padded to the exact original length so the file size
    and every other offset stay byte-identical.  One that does NOT fit either
    sends the whole scene to growth — every one of that scene's edits is
    re-serialised at its exact length (:mod:`.radium_grow`), the file grows,
    and it is copied onto the card whole — or, when growth is off for this
    write (:func:`_text_grow_gate`), is skipped with a warning and the radium
    left unchanged.

    Rows whose path resolves to the ARM-ELF game firmware are game-program
    strings, routed to :func:`_program_text_writes` (in-place C-string patch +
    name-group pointer moves; *patched_fw* composes with the blip-free
    firmware rebuild; a longer edit grows the ELF).

    *grow_dir* is the scratch dir a grown file is staged in (``None`` = no
    growth offered); *dest_is_device* says this is a direct-SD write.

    Returns ``(writes, n_strings, overlays, fw_overlay, grown)`` where
    ``n_strings`` is the number of unique (asset, original) strings actually
    patched, ``overlays`` is ``{i_block: (node, {file_offset: bytes})}`` for
    every patched inode (so the caller can recompute its ``.sidx`` digest),
    ``fw_overlay`` is the game ELF's own ``{file_offset: bytes}`` — the
    validator bypass is the LAST writer of that file's ``.sidx`` record, so it
    has to fold these edits into the digest it computes — and ``grown`` is
    ``{"fw": record | None, "radium": {card_path: (node, {original:
    replacement})}}``: the grown firmware (see :func:`_program_text_writes`)
    and the scenes the caller must re-serialise (:func:`_stage_grown_radiums`)
    once every other in-place scene edit is known."""
    from . import radium as _radium

    grown = {"fw": None, "radium": {}}
    edits = _changed_radium_text(assets_dir)
    if not edits:
        return [], 0, {}, {}, grown
    nodes = _resolve_card_nodes(reader, list(edits.keys()), cancel)

    # The growth gate is asked once, and only when some edit is longer than
    # its original (the ext4 probe reaches for WSL; a write of same-length
    # edits never pays for it).
    over_any = any(len(n) > len(o) for prs in edits.values() for o, n in prs)
    if over_any and grow_dir:
        g_ok, g_why = _text_grow_gate(dest_is_device)
    else:
        g_ok, g_why = False, ("no scratch space was offered for a longer copy"
                              if over_any else "")
    grow = {"ok": g_ok, "why": g_why, "dir": grow_dir}

    writes = []
    overlays = {}   # i_block -> (node, {file_off: bytes})
    fw_overlay = {}  # game ELF file_off -> bytes
    n_strings = 0
    for card_path, pairs in edits.items():
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Display text: radium %s wasn't found on the card; %d edit(s) "
                "skipped." % (card_path, len(pairs)), "warning")
            continue
        try:
            is_fw = reader.is_arm_elf(node)
        except Exception:
            is_fw = False
        if is_fw:
            pw, pn, pov, pgrown = _program_text_writes(
                reader, node, card_path, pairs, patched_fw, log, grow=grow)
            writes += pw
            n_strings += pn
            _merge_radium_overlays(overlays, pov)
            for _n, _ov in pov.values():
                fw_overlay.update(_ov)
            if pgrown is not None:
                grown["fw"] = pgrown
                # Later firmware edits in this same write compose into the
                # staged file, exactly as they do with the cave's.
                patched_fw = pgrown["path"]
            continue
        ib = bytes(node["i_block"])
        data = reader.read_file_bytes(node)
        occ_by_text = {}
        for e in _radium.enumerate_strings(data):
            if e["kind"] == "display-text":
                occ_by_text.setdefault(e["text"], []).append(e)
        over = [(o, r) for o, r in pairs
                if len(r.encode("latin1", "replace"))
                > len(o.encode("latin1", "replace"))]
        if over and grow["ok"]:
            # The scene is re-serialised: every edit at its exact length.
            todo = {}
            for original, replacement in pairs:
                if original not in occ_by_text:
                    log("Display text in %s: \"%s\" wasn't found in the "
                        "current radium; skipped." % (card_path, original),
                        "warning")
                    continue
                todo[original] = replacement
            if todo:
                grown["radium"][card_path] = (node, todo)
                n_strings += len(todo)
                for original, replacement in todo.items():
                    log("Display text in %s: \"%s\" -> \"%s\" (%d occurrence(s); "
                        "%s than the original, so the scene is re-serialised "
                        "at the new length and written whole)."
                        % (card_path, original, replacement,
                           len(occ_by_text[original]),
                           "longer" if (original, replacement) in over
                           else "with an edit longer"), "info")
            continue
        if over:
            log("Display text in %s: %d edit(s) are longer than the original "
                "and the scene can't be grown for this write (%s); they are "
                "skipped — same-length edits still land in place."
                % (card_path, len(over), grow["why"] or "growth unavailable"),
                "warning")
        for original, replacement in pairs:
            orig_bytes = original.encode("latin1", "replace")
            new_bytes = replacement.encode("latin1", "replace")
            orig_len = len(orig_bytes)
            if len(new_bytes) > orig_len:
                log("Display text in %s: \"%s\" -> \"%s\" is %d bytes but the "
                    "original is only %d; skipped (left unchanged). Use a "
                    "shorter replacement." % (card_path, original, replacement,
                                              len(new_bytes), orig_len),
                    "warning")
                continue
            occs = occ_by_text.get(original)
            if not occs:
                log("Display text in %s: \"%s\" wasn't found in the current "
                    "radium; skipped." % (card_path, original), "warning")
                continue
            full = new_bytes.ljust(orig_len, b" ")
            for e in occs:
                if e["length"] != orig_len:
                    continue                       # paranoia: length must match
                payload = full
                for disk, n in reader.disk_ranges(node, e["offset"], orig_len):
                    writes.append((disk, payload[:n]))
                    payload = payload[n:]
                overlays.setdefault(ib, (node, {}))[1][e["offset"]] = full
            n_strings += 1
            log("Display text in %s: \"%s\" -> \"%s\" (%d occurrence(s))."
                % (card_path, original, replacement, len(occs)), "info")
    return writes, n_strings, overlays, fw_overlay, grown


def _stage_grown_radiums(reader, grown_radium, radium_overlays, grow_dir, log):
    """Re-serialise every scene in *grown_radium* and stage the result whole
    under *grow_dir*.  An entry is ``{card_path: (node, {original:
    replacement}[, {data_off: (width, height, block bytes)}])}``: the longer
    text from :func:`_radium_text_writes` and the resized images from
    :func:`_radium_image_writes`, either of which may be empty.

    Composition: the scene's OTHER in-place edits this write makes (colours,
    layout, embedded images — all computed at stock-file offsets) are taken
    out of *radium_overlays* and applied to the stock bytes FIRST, then the
    scene is grown, so the staged file carries everything and the ``.sidx``
    digest comes from the file rather than from an overlay.  Returns
    ``(jobs, grown_files)``: the ``(card_rel, staged)`` grow jobs and
    ``{i_block: staged}`` for the manifest refresh."""
    from . import radium_grow
    jobs, grown_files = [], {}
    for i, (card_path, entry) in enumerate(sorted(grown_radium.items())):
        node, edits = entry[0], entry[1]
        images = entry[2] if len(entry) > 2 else {}
        ib = bytes(node["i_block"])
        buf = bytearray(reader.read_file_bytes(node))
        ov = radium_overlays.pop(ib, None)
        if ov:
            for off, b in ov[1].items():
                buf[off:off + len(b)] = b
        try:
            got = radium_grow.regrow(bytes(buf), texts=edits or None,
                                     images=images or None)
        except ValueError as e:
            log("Scene %s couldn't be re-serialised (%s); it is left "
                "unchanged." % (card_path, e), "warning")
            if ov:
                radium_overlays[ib] = ov
            continue
        new, occ = got["data"], got["texts"]
        if not occ and not got["images"]:
            log("Display text in %s: none of the longer lines were found when "
                "re-serialising; the scene is left unchanged." % card_path,
                "warning")
            if ov:
                radium_overlays[ib] = ov
            continue
        staged = os.path.join(grow_dir, "scene_%02d.radium" % i)
        with open(_lp(staged), "wb") as f:
            f.write(new)
        jobs.append((card_path.lstrip("/"), staged))
        grown_files[ib] = staged
        if occ:
            log("Display text in %s: re-serialised %d line(s) at their new "
                "length (%d occurrence(s)); the scene grows %d -> %d bytes and "
                "is written whole. Whether the game loads a longer scene this "
                "way is proven in the PC emulator only." %
                (card_path, len(occ), sum(occ.values()), len(buf), len(new)),
                "warning")
        elif edits:
            log("Display text in %s: none of the longer lines were found when "
                "re-serialising." % card_path, "warning")
        for off, refs in sorted(got["images"].items()):
            w, h = images[off][:2]
            log("Scene image in %s at %#x: now %dx%d, with the %d sprite "
                "reference(s) that draw it resized to match; the scene grows "
                "%d -> %d bytes and is written whole. Whether the game draws a "
                "resized image this way is proven in the PC emulator only."
                % (card_path, off, w, h, refs, len(buf), len(new)), "warning")
    return jobs, grown_files


def _drop_writes_in(writes, reader, node):
    """*writes* (``[(disk_off, bytes)]``) without those landing inside
    *node*'s extents — a file that is written whole must not also be patched
    in place (the copy would undo it, and an override set would list the
    file twice)."""
    try:
        runs = reader.disk_ranges(node, 0, node["size"])
    except Exception:
        return writes
    return [(d, b) for d, b in writes
            if not any(lo <= d < lo + n for lo, n in runs)]


def _changed_radium_text_colors(assets_dir):
    """The user's scene text-colour edits: ``{radium card path: {string:
    (from_rgb, to_rgb)}}``.  Every row in the manifest is an edit."""
    from . import text_colors as _tc
    return _tc.load(assets_dir)


def _radium_color_writes(reader, assets_dir, log, cancel):
    """Resolve the scene text-colour edits to in-place writes, in the same shape
    (and with the same overlay bookkeeping) as :func:`_radium_text_writes`.

    A line's colour is four floats in its keyframe, so this is the most
    size-neutral patch there is: twelve bytes of RGB per keyframe, alpha left
    exactly as it was.  Alpha is what fades a line in, and rewriting it would
    turn a fade into a pop.

    Only keyframes whose colour still matches the edit's ``from`` are touched.
    One string can be drawn twice — a black outline instance under a coloured
    fill — and repainting both is how you lose the border while thinking you
    only changed the colour."""
    import struct as _struct
    from . import radium as _radium
    from . import scene_layout as _scene_layout

    edits = _changed_radium_text_colors(assets_dir)
    if not edits:
        return [], 0, {}
    nodes = _resolve_card_nodes(reader, list(edits.keys()), cancel)

    writes = []
    overlays = {}
    n_lines = 0
    for card_path, per_text in edits.items():
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Text colour: radium %s wasn't found on the card; %d edit(s) "
                "skipped." % (card_path, len(per_text)), "warning")
            continue
        ib = bytes(node["i_block"])
        data = reader.read_file_bytes(node)
        imgs = parse_radium_images(data)
        tables = _radium.parse_glyph_tables(data, imgs) if imgs else []
        found = _scene_layout.text_color_offsets(data, imgs, tables)
        for text, (src, dst) in sorted(per_text.items()):
            hits = found.get(text) or ()
            payload = _struct.pack("<3f", *[c / 255.0 for c in dst])
            n_hit = 0
            for off, rgba in hits:
                # Match on the colour the user picked FROM, at the tolerance a
                # float that came from a byte can be recovered at.
                if any(abs(rgba[i] * 255.0 - src[i]) > 0.6 for i in range(3)):
                    continue
                n_hit += 1
                buf = payload
                for disk, n in reader.disk_ranges(node, off, len(payload)):
                    writes.append((disk, buf[:n]))
                    buf = buf[n:]
                overlays.setdefault(ib, (node, {}))[1][off] = payload
            if not n_hit:
                log("Text colour in %s: \"%s\" is no longer drawn in %s on the "
                    "card, so its colour was left alone."
                    % (card_path, text, _hex_rgb(src)), "warning")
                continue
            n_lines += 1
            log("Text colour in %s: \"%s\" %s -> %s (%d keyframe(s))."
                % (card_path, text, _hex_rgb(src), _hex_rgb(dst), n_hit),
                "info")
    return writes, n_lines, overlays


def _changed_radium_text_layouts(assets_dir):
    """The user's scene text-layout edits: ``{radium card path: {string:
    {"dx", "dy", "align", "size"}}}``.  Every row in the manifest is an edit
    (the manifest never stores a neutral row)."""
    from . import text_layout as _tl
    return _tl.load(assets_dir)


def _radium_layout_writes(reader, assets_dir, log, cancel):
    """Resolve the scene text-layout edits (``text/layout.tsv``) to in-place
    writes, in the same shape (and with the same overlay bookkeeping) as
    :func:`_radium_color_writes`.

    Where a line sits, how it is aligned and how big it is drawn are all bytes
    of the SCENE: its keyframe rect (four floats), its alignment word (a u32)
    and, for the size, the metrics of the glyph table the scene bakes for that
    face.  Every one of those rewrites is byte-count-neutral, so the file never
    changes size and the ``.sidx`` refresh sees an overlay exactly like a
    recolour's.  The byte-level work is :func:`scene_layout.text_layout_patches`;
    this is the card side: find the scene, map file offsets to disk, and say
    in the log what happened to each line (a resize reaches every line drawn
    with that face in that scene, and the user has to be told so)."""
    from . import radium as _radium
    from . import scene_layout as _scene_layout
    from . import text_layout as _tl

    edits = _changed_radium_text_layouts(assets_dir)
    if not edits:
        return [], 0, {}
    nodes = _resolve_card_nodes(reader, list(edits.keys()), cancel)

    writes = []
    overlays = {}
    n_lines = 0
    for card_path, per_text in sorted(edits.items()):
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Text layout: radium %s wasn't found on the card; %d edit(s) "
                "skipped." % (card_path, len(per_text)), "warning")
            continue
        ib = bytes(node["i_block"])
        data = reader.read_file_bytes(node)
        imgs = parse_radium_images(data)
        tables = _radium.parse_glyph_tables(data, imgs) if imgs else []
        found = _scene_layout.text_layout_offsets(data, imgs, tables)
        if not found:
            # text_layout_patches says nothing per string when the scene
            # itself can't be read; this is the one warning the user gets.
            log("Text layout in %s: no text could be read in this scene on the "
                "card, so its %d layout edit(s) were left alone."
                % (card_path, len(per_text)), "warning")
            continue
        patches, n_hit, notes = _scene_layout.text_layout_patches(
            data, imgs, tables, per_text, log=None)
        for note in notes:
            # A resize that reaches other lines is news, not a fault; a string
            # that is gone, an ambiguous face or a size conflict is a warning.
            lvl = ("info" if _scene_layout.COLLATERAL_NOTE_MARK in note
                   else "warning")
            log("Text layout in %s: %s" % (card_path, note), lvl)
        for off, payload in patches:
            buf = payload
            for disk, n in reader.disk_ranges(node, off, len(payload)):
                writes.append((disk, buf[:n]))
                buf = buf[n:]
            overlays.setdefault(ib, (node, {}))[1][off] = payload
        if not n_hit:
            if not notes:
                log("Text layout in %s: the scene on the card already draws "
                    "its %d line(s) the way the edit asks, so nothing was "
                    "written for it." % (card_path, len(per_text)), "info")
            continue
        n_lines += n_hit
        what = "; ".join("\"%s\" %s" % (text, _tl.describe(edit) or "unchanged")
                         for text, edit in sorted(per_text.items()))
        log("Text layout in %s: %d of %d line(s) re-laid-out (%s); %d byte "
            "run(s) rewritten in place." % (card_path, n_hit, len(per_text),
                                            what, len(patches)), "info")
    return writes, n_lines, overlays


def _hex_rgb(rgb):
    return "#%02x%02x%02x" % tuple(int(c) for c in tuple(rgb)[:3])


def _fit_image_payload(staged_path, target, work_dir, log):
    """Return exactly *target* bytes to overwrite the original ``.png``, or
    ``None`` if the replacement can't be made to fit.  An image ``<= target``
    pads up with trailing bytes; a larger one is re-compressed (max deflate,
    then fewer colours) down to the byte budget first."""
    with open(staged_path, "rb") as f:
        data = f.read()
    name = os.path.basename(staged_path)
    if len(data) <= target:
        return _pad_image(data, target)

    from ...core.image import detect_image_info, recompress_image_to_size
    tmp = os.path.join(work_dir, "fitimg_" + name)
    info = detect_image_info(staged_path)
    ok, detail = recompress_image_to_size(staged_path, tmp, target,
                                          original_info=info)
    if not ok:
        log("Image %s is %d bytes but the original slot is only %d and it "
            "couldn't be shrunk to fit (%s); skipped (left unchanged). Use a "
            "simpler image." % (name, len(data), target, detail), "warning")
        return None
    try:
        with open(tmp, "rb") as f:
            shrunk = f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if len(shrunk) > target:
        log("Image %s still too large after re-encode; skipped." % name,
            "warning")
        return None
    log("Image %s re-compressed to fit (%d -> %d bytes of %d)."
        % (name, len(data), len(shrunk), target), "info")
    return _pad_image(shrunk, target)


def _prepare_image_patches(reader, image_edits, work_dir, log, cancel):
    """Resolve each changed image to its card inode and size-fit its bytes.
    Returns ``([(node, payload), ...], n_skipped)`` — each payload is exactly
    the inode's size, ready for an in-place ``disk_ranges`` write."""
    nodes = _resolve_card_nodes(reader, [cp for (_o, cp, _s) in image_edits],
                                cancel)
    patches = []
    skipped = 0
    for output, card_path, staged in image_edits:
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Image %s: its original (%s) wasn't found on the card; "
                "skipped." % (output, card_path), "warning")
            skipped += 1
            continue
        payload = _fit_image_payload(staged, node["size"], work_dir, log)
        if payload is None:
            skipped += 1
            continue
        patches.append((node, payload))
        log("Image %s: ready to patch (%d bytes)." % (output, node["size"]),
            "info")
    return patches, skipped


def _prepare_boot_screen_patches(disk_f, parts, games_base, boot_edits,
                                 work_dir, log, cancel, dest_is_device=False):
    """The boot screen's edits, on the OS partition -> ``(writes, grow, n)``:
    flat ``(disk_offset, bytes)`` *writes*; *grow* ``None`` or
    ``{"offset": <the OS partition>, "jobs": [(card_rel, source), ...]}``;
    *n* how many images the two put on the card.

    A replacement no bigger than the original goes into the file's own
    blocks, padded with trailing zero bytes (boot_display's PNG reader stops
    at IEND, as the game's does).  A bigger one is copied over the file whole
    through the ext4 driver, the way a full-size video is, so it keeps every
    byte; only a direct-SD write or a system without the driver re-compresses
    it to fit, and skips it when even that won't.  Nothing on the OS
    partition is in the game's .sidx manifest, so there is no record to
    refresh."""
    reader, dir_node = _boot_screen_dir(disk_f, parts, games_base)
    if reader is None:
        log("The boot screen was not written: this card has no /%s on its "
            "OS partition." % _BOOT_IMAGE_DIR, "warning")
        return [], None, 0
    nodes = dict(_boot_images(reader, dir_node))
    writes, jobs, n = [], [], 0
    can_grow = None
    for output, card_path, staged in boot_edits:
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Boot screen %s: its original (%s) wasn't found on the card's "
                "OS partition; skipped." % (output, card_path), "warning")
            continue
        size = os.path.getsize(staged)
        if size > node["size"]:
            if can_grow is None:
                if dest_is_device:
                    can_grow, why = False, "a direct-SD write can't grow a file"
                else:
                    from ...core import ext4_grow
                    can_grow, why = ext4_grow.available()
                if not can_grow:
                    log("A boot screen bigger than the original can't be "
                        "copied onto the card whole here (%s); it is "
                        "re-compressed to fit instead." % why, "warning")
            if can_grow:
                jobs.append((card_path.lstrip("/"), staged))
                n += 1
                log("Boot screen %s: %d bytes where the original has %d, so "
                    "it is copied onto the card whole."
                    % (output, size, node["size"]), "info")
                continue
        payload = _fit_image_payload(staged, node["size"], work_dir, log)
        if payload is None:
            continue
        off = 0
        for disk, cnt in reader.disk_ranges(node, 0, len(payload)):
            writes.append((disk, payload[off:off + cnt]))
            off += cnt
        n += 1
        log("Boot screen %s: ready to patch (%d bytes)."
            % (output, node["size"]), "info")
    grow = {"offset": reader.base, "jobs": jobs} if jobs else None
    return writes, grow, n


# --------------------------------------------------------------------------
# Replace scene textures: re-encode an edited PNG back to BC3 and patch the
# original scene.assets/<N>.asset in place (size-neutral by construction).
# --------------------------------------------------------------------------
def _changed_scene_textures(assets_dir, baseline):
    """Return ``[(output, card_path, staged_png, w, h, fmt), ...]`` for the scene
    textures under ``images/scene_textures`` whose PNG bytes differ from the
    Extract baseline.  Empty when there's no texture manifest."""
    tex_dir = os.path.join(assets_dir, *_TEXTURE_DIR)
    manifest = os.path.join(tex_dir, _TEXTURE_MANIFEST)
    if not os.path.isfile(manifest):
        return []
    out = []
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 6:
                continue
            output, card_path = cols[0], cols[1]
            try:
                w, h, fmt = int(cols[3]), int(cols[4]), int(cols[5])
            except ValueError:
                continue
            staged = os.path.join(assets_dir, "images", *output.split("/"))
            if not os.path.isfile(staged):
                continue
            base = baseline.get("images/" + output)
            if base is not None and _scan_md5(assets_dir, staged) == base:
                continue                       # untouched since extract
            out.append((output, card_path, staged, w, h, fmt))
    return out


def _prepare_texture_patches(reader, texture_edits, log, cancel):
    """Re-encode each edited PNG to BC3 at its original dimensions and resolve it
    to its card inode.  Returns ``([(node, payload), ...], n_skipped)`` — each
    payload is exactly the inode's size (same W×H + DXT5 ⇒ identical byte
    length), ready for an in-place ``disk_ranges`` write."""
    from . import dds as _dds
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:
        if texture_edits:
            log("Pillow/numpy unavailable (%s); scene-texture edits skipped." % e,
                "warning")
        return [], len(texture_edits)
    nodes = _resolve_card_nodes(
        reader, [cp for (_o, cp, _s, _w, _h, _f) in texture_edits], cancel)
    patches = []
    skipped = 0
    for output, card_path, staged, w, h, fmt in texture_edits:
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Texture %s: its original (%s) wasn't found on the card; "
                "skipped." % (output, card_path), "warning")
            skipped += 1
            continue
        try:
            im = Image.open(_lp(staged)).convert("RGBA")
        except Exception as e:
            log("Texture %s: can't read PNG (%s); skipped." % (output, e),
                "warning")
            skipped += 1
            continue
        if im.size != (w, h):
            log("Texture %s is %dx%d but the original is %dx%d; skipped "
                "(scene textures must keep their exact dimensions). Resize your "
                "image to %dx%d." % (output, im.size[0], im.size[1], w, h, w, h),
                "warning")
            skipped += 1
            continue
        arr = np.asarray(im, dtype=np.uint8)
        pw, ph = ((w + 3) // 4) * 4, ((h + 3) // 4) * 4
        try:
            stock = (_dds.decode_bc1 if fmt == _DXT1_FORMAT
                     else _dds.decode_bc3)(reader.read_file_bytes(node), pw, ph)
        except Exception:
            stock = None
        arr, premult = _premultiply_like_stock(arr, stock)
        if premult:
            log("Texture %s: colours premultiplied by alpha, the way the game "
                "blends scene textures." % output, "info")
        payload = (_dds.encode_bc1(arr) if fmt == _DXT1_FORMAT
                   else _dds.encode_bc3(arr))
        if len(payload) != node["size"]:
            log("Texture %s: re-encoded to %d bytes but the slot is %d; skipped."
                % (output, len(payload), node["size"]), "warning")
            skipped += 1
            continue
        patches.append((node, payload))
        log("Texture %s: ready to patch (%dx%d, %d bytes)."
            % (output, w, h, node["size"]), "info")
    return patches, skipped


def _changed_glyph_images(assets_dir, baseline):
    """Return ``{atlas_output: [(glyph_output, staged, x, y, w, h), ...]}`` for
    the font-glyph slice PNGs whose bytes differ from the Extract baseline,
    grouped by the atlas PNG they belong to.  Empty when there's no
    ``glyph_images.txt`` manifest (see :func:`extract_radium_images`)."""
    tex_dir = os.path.join(assets_dir, *_TEXTURE_DIR)
    manifest = os.path.join(tex_dir, _GLYPH_MANIFEST)
    if not os.path.isfile(manifest):
        return {}
    out = {}
    seen = set()
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 7:
                continue
            g_rel, atlas_rel = cols[0], cols[1]
            try:
                x, y, w, h = (int(c) for c in cols[3:7])
            except ValueError:
                continue
            # One slice can appear on several rows: a typeface baked at more
            # than one size shares both the atlas and its rectangles, so the
            # sizes differ only in metrics.  Pasting it once per row is
            # idempotent but re-hashes the file each time and would report
            # "8 edited glyphs" for one edited character.
            if (g_rel, x, y, w, h) in seen:
                continue
            seen.add((g_rel, x, y, w, h))
            staged = os.path.join(assets_dir, "images", *g_rel.split("/"))
            if not os.path.isfile(staged):
                continue
            base = baseline.get("images/" + g_rel)
            if base is not None and _scan_md5(assets_dir, staged) == base:
                continue                       # untouched since extract
            out.setdefault(atlas_rel, []).append((g_rel, staged, x, y, w, h))
    return out


def _glyph_atlas_overrides(assets_dir, baseline, log):
    """Composite each changed font-glyph slice into its atlas: returns
    ``{atlas_output: PIL.Image}`` — the staged atlas PNG with the edited
    glyphs pasted over their rectangles (a slice whose size differs from its
    rectangle is auto-scaled to fit).  These atlases must be treated as edited
    by the radium-image write even when the atlas PNG itself is untouched."""
    per_atlas = _changed_glyph_images(assets_dir, baseline)
    if not per_atlas:
        return {}
    try:
        from PIL import Image
    except Exception as e:
        log("Pillow unavailable (%s); font-glyph edits skipped." % e, "warning")
        return {}
    overrides = {}
    for atlas_rel, glyphs in per_atlas.items():
        staged_atlas = os.path.join(assets_dir, "images", *atlas_rel.split("/"))
        try:
            atlas = Image.open(_lp(staged_atlas)).convert("RGBA")
        except Exception as e:
            log("Glyph atlas %s: can't read PNG (%s); its %d glyph edit(s) "
                "skipped." % (atlas_rel, e, len(glyphs)), "warning")
            continue
        n = 0
        for g_rel, staged, x, y, w, h in glyphs:
            try:
                tile = Image.open(_lp(staged)).convert("RGBA")
            except Exception as e:
                log("Glyph %s: can't read PNG (%s); skipped." % (g_rel, e),
                    "warning")
                continue
            if tile.size != (w, h):
                log("Glyph %s is %dx%d; scaling to its %dx%d atlas slot."
                    % (g_rel, tile.size[0], tile.size[1], w, h), "info")
                tile = tile.resize((w, h), Image.LANCZOS)
            atlas.paste(tile, (x, y))          # replaces pixels incl. alpha
            n += 1
        if n:
            overrides[atlas_rel] = atlas
            log("Font atlas %s: %d edited glyph(s) pasted in." % (atlas_rel, n),
                "info")
    return overrides


def _atlas_png_changed(assets_dir, staged, baseline, output):
    """True when the atlas PNG itself differs from the Extract baseline (as
    opposed to only its glyph slices) -- decides whole re-encode vs the
    surgical block splice in :func:`_radium_image_writes`."""
    base = baseline.get("images/" + output)
    if base is None:
        return True
    return _scan_md5(assets_dir, staged) != base


#: Slack when testing premultiplied data's RGB <= A: a BC block's four colours
#: are shared, so a stock texel decodes up to a few dozen levels past its
#: alpha (Godzilla's language-screen date: up to 28 on transparent texels,
#: 2.2% of its pixels past a slack of 12).  Straight art misses by far more:
#: a white edge sits ~150 above its alpha, a white "transparent" pixel 255.
_PREMULT_TOL = 48


def _straight_alpha_share(arr):
    """Share of *arr*'s pixels (uint8 RGBA) whose colour is brighter than their
    alpha -- which premultiplied data never is, a transparent pixel included."""
    import numpy as np
    a = arr[..., 3].astype(np.int16)
    return float((arr[..., :3].max(axis=2).astype(np.int16)
                  > a + _PREMULT_TOL).mean())


def _premultiply_like_stock(arr, stock):
    """``(pixels, changed)``: *arr* (uint8 RGBA) with its colour multiplied by
    its alpha when the slot's *stock* pixels are premultiplied and *arr* is
    not.

    Stern's compressed pictures are premultiplied (PAD-154 census of Godzilla
    LE 1.16 at this slack: all 180 sampled scene pictures, every font atlas
    and all 250 sampled scene textures keep RGB <= A; 70 of the 77 plain PNG
    files with soft edges do not), and the game blends them that way.  A picture saved by an image editor keeps its colour
    unmultiplied, so on the machine its soft edges draw too bright and a
    transparent pixel that isn't black draws as a solid box (a white
    "transparent" background became a white bar in the emulator).  An
    extracted picture edited in place is premultiplied already and is left
    alone, as is a slot whose own stock pixels are not premultiplied."""
    import numpy as np
    if stock is not None and _straight_alpha_share(stock) > 0.005:
        return arr, False
    if _straight_alpha_share(arr) <= 0.005:
        return arr, False
    out = np.array(arr, dtype=np.uint8, copy=True)
    a = arr[..., 3:4].astype(np.uint16)
    out[..., :3] = ((arr[..., :3].astype(np.uint16) * a + 127) // 255).astype(
        np.uint8)
    return out, True


def _splice_changed_blocks(raw, target, pad_w, pad_h, fmt):
    """Re-encode ONLY the 4x4 BC blocks whose pixels differ between the stock
    atlas bytes *raw* and the composited RGBA *target* (uint8 ``(pad_h, pad_w,
    4)``), splicing them into a copy of *raw*.  BC blocks are independent, so
    every untouched character stays bit-identical to stock -- a whole-atlas
    re-encode would subtly reflow every block, changing characters the user
    never edited.  Returns the patched bytes (``raw`` itself when nothing
    differs)."""
    from . import dds as _dds
    import numpy as np
    decode = _dds.decode_bc1 if fmt == _DXT1_FORMAT else _dds.decode_bc3
    encode = _dds.encode_bc1 if fmt == _DXT1_FORMAT else _dds.encode_bc3
    bs = 8 if fmt == _DXT1_FORMAT else 16
    stock = decode(raw, pad_w, pad_h)
    diff = np.any(stock != target, axis=2)
    if not diff.any():
        return raw
    nbx = pad_w // 4
    blocks = diff.reshape(pad_h // 4, 4, nbx, 4).any(axis=(1, 3))
    bys, bxs = np.nonzero(blocks)
    by0, by1 = int(bys.min()), int(bys.max())
    bx0, bx1 = int(bxs.min()), int(bxs.max())
    # One encode of the changed blocks' bounding rect (vectorised), then copy
    # only the truly-changed blocks' bytes -- block outputs depend on nothing
    # but their own 4x4 pixels, so this equals a per-block encode.
    sub = np.ascontiguousarray(
        target[by0 * 4:(by1 + 1) * 4, bx0 * 4:(bx1 + 1) * 4])
    enc = encode(sub)
    out = bytearray(raw)
    nbx_sub = bx1 - bx0 + 1
    for bj, bi in zip(bys, bxs):
        src = ((int(bj) - by0) * nbx_sub + (int(bi) - bx0)) * bs
        dst = (int(bj) * nbx + int(bi)) * bs
        out[dst:dst + bs] = enc[src:src + bs]
    return bytes(out)


def _load_glyph_scopes(assets_dir):
    """``{atlas_output: set(radium card paths)}`` from the optional font-scope
    file (see :data:`_GLYPH_SCOPE_MANIFEST`) — the atlases the user narrowed to
    specific scenes in the Fonts window.  Empty dict = every edit applies to
    every occurrence, the default."""
    path = os.path.join(assets_dir, *_TEXTURE_DIR, _GLYPH_SCOPE_MANIFEST)
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) >= 2 and cols[0] and cols[1]:
                    out.setdefault(cols[0], set()).add(cols[1])
    except OSError:
        return {}
    return out


def _changed_radium_images(assets_dir, baseline, extra_changed=(), scope=None):
    """Return ``[(output, radium_card_path, staged, data_off, length, pad_w,
    pad_h, fmt), ...]`` for the radium-embedded images whose PNG differs from the
    Extract baseline.  Empty when there's no ``radium_images.txt`` manifest.
    ``fmt`` defaults to BC3/DXT5 for manifests written before the BC1 column.
    Outputs in *extra_changed* are included even when their own PNG is
    untouched (an atlas whose glyph slices were edited).

    *scope* (``{output: set(card paths)}``, from :func:`_load_glyph_scopes`)
    drops the occurrences of a narrowed atlas that live outside its chosen
    scenes — those scenes keep their stock bytes because every occurrence
    starts out identical, so simply not patching them IS leaving them stock.
    An output absent from *scope* keeps the all-occurrences default.

    A scope narrows GLYPH edits only.  Replacing the atlas PNG itself on the
    Images tab is the ordinary all-occurrences image replace, and it has to
    stay that way even when the Fonts window happens to have narrowed the same
    atlas earlier: the scope file is written as a SIDE EFFECT of an import
    removing an outline companion, so a user who never opened the scope control
    can own one without knowing.  A tester hit exactly that — he replaced 13
    outline atlases with an empty 512x512 PNG, and 900 of their 913 on-card
    occurrences were silently dropped by scopes an earlier import had left
    behind, so his machine kept the old outlines on every screen but one."""
    tex_dir = os.path.join(assets_dir, *_TEXTURE_DIR)
    manifest = os.path.join(tex_dir, _RADIUM_IMAGE_MANIFEST)
    if not os.path.isfile(manifest):
        return []
    out = []
    png_edited = {}          # output -> the PNG itself differs from stock
    #                          (memoised: one atlas has 200+ rows here)
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 6:
                continue
            output, radium_path = cols[0], cols[1]
            try:
                data_off, length = int(cols[2]), int(cols[3])
                pad_w, pad_h = int(cols[4]), int(cols[5])
                fmt = int(cols[6]) if len(cols) > 6 else _DXT5_FORMAT
            except ValueError:
                continue
            staged = os.path.join(assets_dir, "images", *output.split("/"))
            if not os.path.isfile(staged):
                continue
            allowed = (scope or {}).get(output)
            if allowed is not None and radium_path not in allowed:
                if output not in png_edited:
                    png_edited[output] = _atlas_png_changed(
                        assets_dir, staged, baseline, output)
                if not png_edited[output]:
                    continue                   # narrowed to other scenes
            if output not in extra_changed:
                base = baseline.get("images/" + output)
                if base is not None and _scan_md5(assets_dir, staged) == base:
                    continue                   # untouched since extract
            out.append((output, radium_path, staged, data_off, length,
                        pad_w, pad_h, fmt))
    return out


def _file_range_bytes(reader, node, off, n):
    """*n* bytes of the card file *node* from file offset *off*.

    Whole filesystem blocks through the extent map where the reader has one, so
    a raw SD device is only ever asked for block-aligned reads, and the whole
    file otherwise (the one door a test double has)."""
    bs = getattr(reader, "block_size", 0)
    read = getattr(reader, "_read", None)
    if bs and read is not None and hasattr(reader, "base"):
        lo = (off // bs) * bs
        hi = min(-(-(off + n) // bs) * bs, -(-node["size"] // bs) * bs)
        buf = bytearray()
        for disk, cnt in reader.disk_ranges(node, lo, hi - lo):
            buf += read(disk - reader.base, cnt)
        return bytes(buf[off - lo:off - lo + n])
    return reader.read_file_bytes(node)[off:off + n]


def _radium_record_at(reader, node, data_off, length, pad_w, pad_h, fmt):
    """Whether the card's scene *node* holds a picture record exactly where a
    ``radium_images.txt`` row says: the header before *data_off* names the
    row's format and block length, and its texture size rounds up to the row's
    block grid (:func:`parse_radium_images`' own signature).

    The row's offsets were measured on the card the project was EXTRACTED
    from.  A card whose scene is laid out differently - one already built with
    a picture kept at its own size or with longer text, which moves every
    record after it - puts other bytes there, and writing picture blocks over
    them breaks the scene: the game stops with ``cereal::Exception`` when it
    loads it (PAD-159)."""
    if data_off < 36 or data_off + length > node.get("size", 0):
        return False
    try:
        hdr = _file_range_bytes(reader, node, data_off - 36, 36)
    except Exception:
        return False
    if len(hdr) != 36:
        return False
    (_dw, _dh, _handle, tex_w, tex_h, f, z0, z1,
     n) = struct.unpack("<9I", hdr)
    return (f == fmt and z0 == 0 and z1 == 0 and n == length
            and _padded4(tex_w) == pad_w and _padded4(tex_h) == pad_h)


def _radium_image_writes(reader, assets_dir, baseline, log, cancel,
                         grow_dir=None, dest_is_device=False, grown=None):
    """Re-encode each edited radium-embedded image to its format (BC3/DXT5 or
    BC1/DXT1) and resolve it to a flat ``[(disk_offset, bytes), ...]`` list
    patching the bytes in place inside the ``scene.radium`` inode (same form
    ``_compute_patches`` collects, like the display-text writes).  Returns
    ``(writes, n_images)``.

    Size-neutral when the PNG is the stock padded block grid, so re-encoding
    yields exactly ``length`` bytes at ``data_offset``.  A PNG whose own size
    rounds up to that grid is padded out with transparency and patched the
    same way.

    A PNG of any OTHER size (PAD-154: a replacement the user kept at its own
    size, because a longer name squeezed into the stock banner was unreadable)
    is not patched in place.  When the caller offers *grow_dir* and a *grown*
    dict and :func:`_image_grow_gate` passes, its encoded block data is
    recorded as ``grown[card_path] = (node, {data_off: (width, height,
    bytes)})`` for :func:`_stage_grown_radiums` to re-serialise the scene
    around.  A font atlas never changes size (its glyph rectangles are
    measured in its pixels), and neither does an image no sprite in its scene
    draws by size.

    A picture that cannot keep its own size is FITTED to its slot, exactly as
    the Images tab scales a replacement with Keep size off, and the log says
    why (PAD-179).  It used to be skipped, so ticking Keep size on one of
    those - the tab offers it on every scene picture that is not a font atlas,
    and 26 of the 339 on Godzilla LE 1.16 are drawn by nothing that has a size
    - took the user's picture off the card and out of the emulator entirely.
    A font atlas is fitted the same way, to the pixel grid its letters are
    measured in.  Only an atlas rebuilt from edited glyph slices is still
    skipped at the wrong size: the slices were cut to its stock grid, so
    there is nothing sound to fit.

    Returns ``(writes, n_images, overlays)`` where ``overlays`` is
    ``{i_block: (node, {file_offset: bytes})}`` for every patched ``scene.radium``
    inode, so the caller can recompute its ``.sidx`` digest.

    Edited font-glyph slices (``scene_textures/glyphs/``) are composited into
    their atlas first (:func:`_glyph_atlas_overrides`), which makes the atlas
    count as edited and re-encode from the pasted-over pixels."""
    glyph_atlases = _glyph_atlas_overrides(assets_dir, baseline, log)
    scope = _load_glyph_scopes(assets_dir)
    edits = _changed_radium_images(assets_dir, baseline,
                                   extra_changed=set(glyph_atlases),
                                   scope=scope)
    if scope:
        per_output = {}
        for (o, *_r) in edits:
            per_output[o] = per_output.get(o, 0) + 1
        kept = set(per_output)
        for output, cards in sorted(scope.items()):
            if output in kept and per_output[output] > len(cards):
                # The atlas PNG itself was replaced, so the scope does not
                # apply — say so, because a user who DID mean to narrow this
                # font would otherwise find the border gone everywhere.
                log("Font atlas %s was replaced outright, so all %d of its "
                    "scene(s) take it — the %d-scene limit set in the Fonts "
                    "window applies to glyph edits only."
                    % (output, per_output[output], len(cards)), "info")
            elif output in kept:
                log("Font atlas %s is limited to %d scene(s); its other "
                    "scenes keep the stock font." % (output, len(cards)),
                    "info")
            elif output in glyph_atlases:
                # Narrowed to scenes that no longer exist (a scope carried to
                # another game's extract) — silence here would look like the
                # edit simply didn't take.
                log("Font atlas %s has edited glyphs but is limited to "
                    "scene(s) that aren't in this project (%s); nothing was "
                    "written for it."
                    % (output, ", ".join(sorted(cards)[:3])), "warning")
    if not edits:
        return [], 0, {}
    from . import dds as _dds
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:
        log("Pillow/numpy unavailable (%s); radium-image edits skipped." % e,
            "warning")
        return [], 0, {}
    nodes = _resolve_card_nodes(
        reader, list({rp for (_o, rp, *_r) in edits}), cancel)
    writes = []
    overlays = {}                  # i_block -> (node, {file_off: bytes})
    encoded = {}                   # staged PNG path -> block bytes (one PNG, many occurrences)
    resized = {}                   # (staged, fmt) -> (w, h, block bytes) at the PNG's own size
    fitted = {}                    # staged PNG path -> block bytes, scaled to the slot
    gate = []                      # _image_grow_gate, asked once and only if needed
    scenes = {}                    # card path -> (atlas offsets, {data_off: refs})
    scene_bytes = {}               # card path -> the stock scene.radium
    patched_outputs = set()

    def _scene(radium_path, node):
        if radium_path not in scene_bytes:
            scene_bytes[radium_path] = reader.read_file_bytes(node)
        return scene_bytes[radium_path]

    def _premultiplied(arr, output, radium_path, node, data_off, length,
                       pad_w, pad_h, fmt):
        """*arr* premultiplied when its slot's stock pixels are (see
        :func:`_premultiply_like_stock`)."""
        try:
            raw = _scene(radium_path, node)[data_off:data_off + length]
            stock = (_dds.decode_bc1 if fmt == _DXT1_FORMAT
                     else _dds.decode_bc3)(raw, pad_w, pad_h)
        except Exception:
            stock = None
        arr, changed = _premultiply_like_stock(arr, stock)
        if changed:
            log("Radium image %s: colours premultiplied by alpha, the way the "
                "game blends scene pictures." % output, "info")
        return arr

    def _resize_refusal(radium_path, node, data_off):
        """Why the image at *data_off* can't take a new size, or ``""``."""
        if radium_path not in scenes:
            from . import radium as _radium, radium_grow as _rg
            try:
                data = _scene(radium_path, node)
                imgs = parse_radium_images(data)
                atlas = {g["atlas"]["data_off"]
                         for t in _radium.parse_glyph_tables(data, imgs)
                         for g in t["glyphs"] if g.get("atlas") is not None}
                refs = {im["data_off"]: len(_rg.image_refs(
                            data, im["data_off"], imgs)) for im in imgs}
                scenes[radium_path] = (atlas, refs)
            except Exception:
                scenes[radium_path] = None
        facts = scenes[radium_path]
        if facts is None:
            return "its scene couldn't be read"
        atlas, refs = facts
        if data_off in atlas:
            return ("it is a font atlas, and its letters are measured in its "
                    "pixels")
        if not refs.get(data_off):
            return ("nothing in its scene draws it by size, so a new size "
                    "would not be followed")
        return ""

    moved = {}                     # card path -> outputs whose record isn't there
    for output, radium_path, staged, data_off, length, pad_w, pad_h, fmt in edits:
        if cancel():
            break
        node = nodes.get(radium_path)
        if node is None:
            log("Radium image %s: its scene (%s) wasn't found on the card; "
                "skipped." % (output, radium_path), "warning")
            continue
        if not _radium_record_at(reader, node, data_off, length, pad_w, pad_h,
                                 fmt):
            moved.setdefault(radium_path, []).append(output)
            continue
        payload = encoded.get(staged)
        fit = False                # scaled to the slot: cached apart, because
        #                            another occurrence may still grow it
        if payload is None:
            override = glyph_atlases.get(output)
            try:
                im = override if override is not None else (
                    Image.open(_lp(staged)).convert("RGBA"))
            except Exception as e:
                log("Radium image %s: can't read PNG (%s); skipped."
                    % (output, e), "warning")
                continue
            w, h = im.size
            if (im.size != (pad_w, pad_h)
                    and (_padded4(w), _padded4(h)) == (pad_w, pad_h)):
                # The texture's own size rather than its padded grid: the
                # same blocks, so pad with transparency and patch in place.
                grid = Image.new("RGBA", (pad_w, pad_h), (0, 0, 0, 0))
                grid.paste(im, (0, 0))
                im = grid
            if im.size != (pad_w, pad_h):
                why = "don't resize — edit in place"
                if override is None and grown is not None and grow_dir:
                    if not gate:
                        gate.append(_image_grow_gate(dest_is_device))
                    ok, why = gate[0]
                    if ok:
                        why = _resize_refusal(radium_path, node, data_off)
                        ok = not why
                    if ok:
                        got = resized.get((staged, fmt))
                        if got is None:
                            grid = Image.new("RGBA", (_padded4(w), _padded4(h)),
                                             (0, 0, 0, 0))
                            grid.paste(im, (0, 0))
                            arr = _premultiplied(
                                np.asarray(grid, dtype=np.uint8), output,
                                radium_path, node, data_off, length, pad_w,
                                pad_h, fmt)
                            got = resized[(staged, fmt)] = (
                                w, h, _dds.encode_bc1(arr) if fmt == _DXT1_FORMAT
                                else _dds.encode_bc3(arr))
                        grown.setdefault(radium_path, (node, {}))[1][data_off] = got
                        patched_outputs.add(output)
                        log("Radium image %s is %dx%d, not the original %dx%d: "
                            "the scene (%s) is re-serialised around its new "
                            "size." % (output, w, h, pad_w, pad_h, radium_path),
                            "info")
                        continue
                if override is not None:
                    log("Radium image %s is %dx%d but must stay %dx%d; skipped "
                        "(%s)." % (output, w, h, pad_w, pad_h, why), "warning")
                    continue
                fit = True
                payload = fitted.get(staged)
                if payload is None:
                    log("Radium image %s is %dx%d, and this picture can't take "
                        "a new size (%s), so it is fitted to the original "
                        "%dx%d instead - the same as leaving Keep size off on "
                        "the Images tab." % (output, w, h, why, pad_w, pad_h),
                        "warning")
                    im = im.resize((pad_w, pad_h), Image.LANCZOS)
        if payload is None:
            arr = np.asarray(im, dtype=np.uint8)
            if override is None:
                arr = _premultiplied(arr, output, radium_path, node, data_off,
                                     length, pad_w, pad_h, fmt)
            if (override is not None
                    and not _atlas_png_changed(assets_dir, staged, baseline,
                                               output)):
                # Glyph-only edit: splice just the changed BC blocks into the
                # stock atlas bytes so every character the user didn't touch
                # stays bit-identical (occurrences share one content, so the
                # first occurrence's bytes serve them all).
                try:
                    raw = reader.read_file_bytes(node)[data_off:data_off
                                                       + length]
                except Exception:
                    raw = b""
                if len(raw) == length:
                    payload = _splice_changed_blocks(raw, arr, pad_w, pad_h,
                                                     fmt)
            if payload is None:
                payload = (_dds.encode_bc1(arr) if fmt == _DXT1_FORMAT
                           else _dds.encode_bc3(arr))
            (fitted if fit else encoded)[staged] = payload
        if len(payload) != length:
            log("Radium image %s: re-encoded to %d bytes but the slot is %d; "
                "skipped." % (output, len(payload), length), "warning")
            continue
        rest = payload
        for disk, cnt in reader.disk_ranges(node, data_off, length):
            writes.append((disk, rest[:cnt]))
            rest = rest[cnt:]
        overlays.setdefault(bytes(node["i_block"]), (node, {}))[1][data_off] = payload
        patched_outputs.add(output)
    for radium_path, outs in sorted(moved.items()):
        # Once per scene: an atlas can have hundreds of occurrences.
        names = sorted(set(outs))
        log("Scene %s on this card doesn't have its pictures where this "
            "project's extract found them, so %d edited picture(s) in it were "
            "not written (%s%s): writing them there would break the scene, "
            "and the game stops when it loads a broken scene. This card is "
            "laid out differently from the one the project was extracted "
            "from - a card already built with a picture kept at its own size "
            "or with longer text, or another version of the game. Use the "
            "card the project was extracted from."
            % (radium_path, len(names), ", ".join(names[:3]),
               ", ..." if len(names) > 3 else ""), "warning")
    n = len(patched_outputs)
    if n:
        log("Patching %d edited radium image(s) across %d on-card occurrence(s)."
            % (n, len({(o, ro, do) for (o, ro, _s, do, *_r) in edits})), "info")
    return writes, n, overlays


def _overlay_digests(reader, disk, node, overlays):
    """Stream *node*'s bytes (from *disk* via the ext4 map), applying *overlays*
    (``{file_offset: bytes}``) in place, and return ``(HMAC-SHA1(K), MD5)`` of the
    resulting patched file — the exact digests its ``.sidx`` record should carry,
    computed without re-reading the patched output."""
    from . import sidx
    h = hmac.new(sidx.SIDX_KEY, digestmod=hashlib.sha1)
    m = hashlib.md5()
    ov = sorted(overlays.items())
    pos = 0
    for d, n in reader.disk_ranges(node, 0, node["size"]):
        disk.seek(d)
        rem = n
        while rem:
            take = min(rem, 1 << 20)
            chunk = bytearray(disk.read(take))
            for off, b in ov:
                if off + len(b) <= pos or off >= pos + take:
                    continue
                lo = max(off, pos)
                hi = min(off + len(b), pos + take)
                chunk[lo - pos:hi - pos] = b[lo - off:hi - off]
            h.update(chunk)
            m.update(chunk)
            pos += take
            rem -= take
    return h.digest(), m.digest()


def _merge_radium_overlays(dst, src):
    """Merge ``{i_block: (node, {file_off: bytes})}`` *src* into *dst* in place.

    A single ``scene.radium`` may receive both display-text and embedded-image
    edits; combining their file-relative overlays under one inode key lets the
    ``.sidx`` refresh recompute that radium's digest from the fully-patched
    content in one pass."""
    for ib, (node, ov) in src.items():
        slot = dst.setdefault(ib, (node, {}))
        slot[1].update(ov)


def _compute_sidx_writes(reader, disk_f, img_node, audio_patches, music_patches,
                         full_repl, radium_overlays, log,
                         fw_node=None, fw_patched_path=None, grown_files=None):
    """Produce the on-disk writes that refresh the ``.sidx`` manifest records for
    every file this Write changed, so the card passes Stern SD validation.

    Covers ``image.bin`` (cat-0 audio), the per-song ``image-scNN.bin`` banks,
    full-replacement assets (video / image / texture), in-place ``scene.radium``
    edits (display text + embedded images) via their file-relative
    ``radium_overlays`` (``{i_block: (node, {file_off: bytes})}``), the
    rebuilt firmware (*fw_node* / *fw_patched_path*) and any other file this
    write replaces WHOLE at a new length (*grown_files*, ``{i_block: staged
    path}`` — a re-serialised scene); the last two get their stored size
    rewritten alongside the digests."""
    from . import sidx
    sidx_path, sidx_node = sidx.find_sidx(reader)
    if sidx_node is None:
        log("No /spk/index/*.sidx manifest on the card — skipping SD-validation "
            "refresh (card may report a validation error).", "warning")
        return []
    sdata = reader.read_file_bytes(sidx_node)
    recs, _hdr_crc, sidx_fmt = sidx.parse_records(sdata)
    if not recs:
        log("Unrecognised .sidx manifest format — skipping SD-validation refresh.",
            "warning")
        return []

    # Map each file's unique extent block (i_block) -> manifest path so we can
    # resolve modified inodes to their records.
    ipath = {bytes(node["i_block"]): path.lstrip("/")
             for path, _ino, node in reader.iter_regular_files(
                 min_size=1, max_depth=20)}

    modified = {}   # manifest path -> (hmac, md5) of the patched file
    resized = {}    # manifest path -> new byte length (non-size-neutral writes)
    if audio_patches and img_node is not None:
        p = ipath.get(bytes(img_node["i_block"]))
        if p:
            modified[p] = _overlay_digests(reader, disk_f, img_node, audio_patches)
    # Path A: the rebuilt game_real (blip-free cave + validator bypass) needs its
    # .sidx record refreshed or the card fails SD validation on the modified
    # firmware.  Unlike every other patched file it is LONGER than the original,
    # so the record's stored size has to move too -- digests alone would leave
    # the manifest describing a file that no longer exists.
    if fw_patched_path and fw_node is not None:
        p = ipath.get(bytes(fw_node["i_block"]))
        if p:
            with open(_lp(fw_patched_path), "rb") as f:
                blob = f.read()
            modified[p] = sidx.digests(blob)
            resized[p] = len(blob)
    for ib, staged in (grown_files or {}).items():
        p = ipath.get(ib)
        if p:
            modified[p] = sidx.digests_file(_lp(staged))
            resized[p] = os.path.getsize(_lp(staged))
    if music_patches:
        banks = {}
        for sc_node, body_off, body in music_patches:
            ib = bytes(sc_node["i_block"])
            banks.setdefault(ib, [sc_node, {}])[1][body_off] = body
        for ib, (sc_node, ov) in banks.items():
            p = ipath.get(ib)
            if p:
                modified[p] = _overlay_digests(reader, disk_f, sc_node, ov)
    for node, payload in full_repl:
        p = ipath.get(bytes(node["i_block"]))
        if p:
            modified[p] = sidx.digests(bytes(payload))
    # In-place scene.radium edits (display text + embedded images): recompute the
    # digest by streaming each patched inode with its file-relative overlays.
    for ib, (node, ov) in (radium_overlays or {}).items():
        p = ipath.get(ib)
        if p:
            modified[p] = _overlay_digests(reader, disk_f, node, ov)

    out = []
    n_ok = 0
    for path, (hm, md) in modified.items():
        po = recs.get(path)
        if po is None:
            log("  .sidx has no record for %s — left stale." % path, "warning")
            continue
        for foff, b in sidx.record_field_writes(po, hm, md, sidx_fmt,
                                                size=resized.get(path)):
            for d, n in reader.disk_ranges(sidx_node, foff, len(b)):
                out.append((d, b[:n]))
                b = b[n:]
        n_ok += 1
    if n_ok:
        log("Refreshed %d %s SD-validation manifest record(s) (HMAC-SHA1 + MD5)."
            % (n_ok, sidx_fmt), "success")
        # NOTE: the manifest header word @0x34 (live on FINF cards, 0xffffffff on
        # FI64) is deliberately left as-is.  Firmware RE (2026-06-25) disassembled
        # both on-card .sidx parsers (/usr/local/bin/spk and spike_menu/game) and
        # the firmware ELF: none of them read offset 0x34, and a hardware test that
        # forced @0x34 -> 0xffffffff still failed — so @0x34 is not an enforced
        # integrity word.  The per-file HMAC-SHA1+MD5 records refreshed above are
        # the actual validated digests.
    return out


def _fmt_dur(secs):
    """``4 min 32 s`` / ``52 s`` for the write-timing log lines."""
    secs = int(round(secs))
    return ("%d min %d s" % divmod(secs, 60)) if secs >= 60 else "%d s" % secs


def _stage_done(log, name, t0):
    """Log how long a Write stage took.  Quiet under 5 s so a small write
    stays a small log.

    "Where did my write go?" has to be answerable from the build log alone:
    a modder reporting a slow write can't rerun it under a profiler, and the
    stage mix varies wildly with the mod (Godzilla Heisei 1.16, 2026-08-26:
    ~110 minutes per image on the modder's rig, unattributable from afar)."""
    dt = time.monotonic() - t0
    if dt >= 5.0:
        log("Write timing: %s took %s." % (name, _fmt_dur(dt)), "info")


def _grow_stage_name(grow_plan):
    """The timing line's name for the ext4 copy stage, by what it copies (item 149): a
    build that carries modes copies their files, not just grown videos; one without names
    the videos, the grown sound bank and the rebuilt game files it has."""
    plan = grow_plan or {}
    modes = plan.get("modes")
    if not modes:
        n_jobs = len(plan.get("jobs") or ())
        n_video = int(plan.get("n_video", n_jobs) or 0)
        bank = plan.get("audio_job") is not None
        what = (["the full-size videos"] if n_video else []) + (
            ["the grown sound bank"] if bank else []) + (
            ["the rebuilt game files"] if n_jobs - n_video - bank > 0 else [])
        if not what:
            return "copying the files that outgrew their slots into the card"
        return "copying %s into the card" % (
            what[0] if len(what) == 1
            else ", ".join(what[:-1]) + " and " + what[-1])
    what = "the modes' files (%d added, %d rewritten)" % (
        len(modes.get("added") or ()), len(modes.get("rewritten") or ()))
    if modes.get("end_sound") or modes.get("own_sounds"):
        what += ", the grown sound bank"
    return "copying onto the card %s and any other file that outgrew its slot" % what


class NothingToWrite(FileNotFoundError):
    """:func:`_compute_patches` found no edit at all in the project.

    A ``FileNotFoundError`` so every caller that caught the old one still does,
    and a type of its own so nothing takes a MISSING FILE (a replacement sound
    gone from disk, the pinned mode runtime absent) for an empty project - item
    149's "every mode taken out" branch writes the original card on this and on
    nothing else."""


#: Item 145's name for the same refusal: items 145 and 149 each gave "Nothing to
#: write" a class of its own, so :func:`write_image` can tell it from a file that
#: is really missing.  Merged they are ONE class, so item 145's put-back-to-stock
#: (:func:`_compute_patches_or_restore`) and item 149's every-mode-taken-out
#: branch answer the same raise.
_NothingToWrite = NothingToWrite


# --------------------------------------------------------------------------
# PAD-176: does what a build copies on whole fit the card's games partition?
# --------------------------------------------------------------------------
# A build whose full-size videos, grown sound bank and rebuilt files overran
# the games partition used to find out only at the copy, after a twenty-minute
# encode, leaving a card whose validation records described files that never
# landed.  Every number the comparison needs is known before the encode: the
# partition's free blocks (card_size.p3_space, grown to the build's SD card
# size by card_size.grown), the file each replacement video goes on as
# (_intact_verdict, settled here instead of after the encode, and handed on
# to _prepare_video_patches), the grown bank's exact length
# (_grown_bank_bytes), and upper bounds for the modes' own clips and screens
# and the pictures kept at their own size (_unsized_bytes).

#: What the pre-flight adds for the small whole-file copies it can't size
#: before the encode: the game program grown for longer text or the
#: blip-free cave, a scene re-serialised around longer text, a mode's own
#: runtime files and the manifest that indexes them.  On a stock card each is
#: kilobytes to a few MB.  The big ones made after the encode are sized
#: before it (:func:`_unsized_bytes`).  The copy-time check
#: (core/ext4_grow.py) still stops a build that outgrows this.
_SPACE_MARGIN = 8 << 20

#: Blocks one whole-file copy may take beyond its data: the leaf of its extent
#: tree when the free space it lands in is scattered (an 8 GB card's is).
_SPACE_SLACK_BLOCKS = 1

#: EXT4_HUGE_FILE_FL: the inode counts its i_blocks in filesystem blocks
#: instead of 512-byte sectors.
_HUGE_FILE_FL = 0x40000

#: A mode's own clip, sized before it is encoded: mode_assets encodes every
#: one at an average of 2500 kbit/s (``-b:v 2500k``), at most 30 s long (a
#: title card's own limit, and convert_clip's ``-t 30``).  An average is not
#: a cap, so the allowance leaves the encoder a quarter over it, and the
#: container its own room.
_MODE_CLIP_BYTES_PER_S = 2500 * 1000 // 8
_MODE_CLIP_MAX_S = 30.0
_MODE_CLIP_OVERSHOOT = 1.25
_MODE_CLIP_CONTAINER = 64 << 10
#: A mode's own screen: its picture, at most 1360x768 (mode_assets.load_art)
#: at a byte a pixel (BC3), added to the HUD scene the build re-serialises.
_MODE_SCREEN_BYTES = 1360 * 768

#: Past this many clips to settle, the log says why the build is probing
#: videos before it encodes anything.
_SETTLE_SAY = 8
#: The probes run this many at a time (each is an ffprobe process).
_SETTLE_WORKERS = 8


class _SpaceBudget:
    """What :func:`write_image` measures a build against (handed to its
    :func:`_compute_patches` by :class:`_SpaceScope`), and what the measure
    found.

    *original* is the card the build is made from and *grow_to* the class a
    whole build grows it to (card_size.preflight's answer, or None).  With
    *updating* the build updates the one already at *output*, and is
    measured there first: the files the last build copied on whole still
    take their room on it, and one this build puts back to stock gives its
    room back only after this build's own copies.  So an update can be short
    of room that the same build made from the original has; the measure then
    sets *whole* (the reason, a phrase) and :func:`write_image` builds from
    the original instead, as it does for every other update it can't make.
    *sizes* are the classes the Write tab offers for the original
    (card_size.offered); *fixed* says this build can't take a size at all
    (card_size.size_fixed: a port's).

    *on_clear*, when given, is called once, when the build has been measured
    and fits, or can't be measured: write_image starts copying the original
    over the output then and not before, so a build that is refused leaves
    the file already at the output, and its record, as they were.

    *grow_check* is ``ext4_grow.available()``'s answer once this build has
    asked it (:func:`_ext4_can_grow`): each ask starts WSL, and the
    pre-flight and the grow gates all want the same answer."""

    def __init__(self, original, output=None, updating=False, grow_to=None,
                 sizes=(), fixed=False, on_clear=None):
        self.original = original
        self.output = output
        self.updating = bool(updating)
        self.grow_to = grow_to
        self.sizes = list(sizes or ())
        self.fixed = bool(fixed)
        self.on_clear = on_clear
        self.whole = None
        self.cleared = False
        self.grow_check = None
        self.early = False         # space_floor's: before anything is staged

    def clear(self):
        """The build may go on to write (see *on_clear*)."""
        if self.cleared:
            return
        self.cleared = True
        if self.on_clear is not None:
            self.on_clear()


#: The room :func:`_grows_within_bank_limit` may give the grown sound bank on
#: the games partition: *limit* the largest ``image.bin`` it can take beside
#: everything else the build copies whole (*others* bytes of the partition's
#: *free*), *suggest(bank_bytes)* the smallest SD card size with room for a
#: bank that long, or None, and *fixed* whether this build can take a size at
#: all (card_size.bigger_card).
_BankRoom = namedtuple("_BankRoom", "limit free others suggest fixed",
                       defaults=(False,))

#: The budget of the build running on THIS thread, set by :func:`write_image`
#: around its :func:`_compute_patches` call (:class:`_SpaceScope`).  Handed
#: over this way rather than as an argument because _compute_patches'
#: signature is pinned (tests/test_stern_write_compute_patches.py) and a dozen
#: stand-ins for it take exactly that signature; a headless caller that wants
#: the check opens the scope itself.  :func:`write_device` and the emulator's
#: override sets set none and are never measured: a direct write copies
#: nothing whole, and the rig binds its files with no partition to fill.
_BUILD_SPACE = threading.local()


def _ext4_can_grow():
    """``ext4_grow.available()``, asked once a build: the answer is kept on
    the budget of the build running on this thread (:attr:`_SpaceBudget.
    grow_check`), so the grow gates and the pre-flight share one WSL round
    trip.  Outside a build it is asked every time, as before."""
    budget = getattr(_BUILD_SPACE, "budget", None)
    got = getattr(budget, "grow_check", None)
    if got is None:
        from ...core import ext4_grow
        got = ext4_grow.available()
        if budget is not None:
            budget.grow_check = got
    return got


class _SpaceScope:
    """``with _SpaceScope(budget):`` - *budget* is the build's for the
    :func:`_compute_patches` run inside it, on this thread."""

    def __init__(self, budget):
        self.budget = budget
        self.prev = None

    def __enter__(self):
        self.prev = getattr(_BUILD_SPACE, "budget", None)
        _BUILD_SPACE.budget = self.budget
        return self

    def __exit__(self, *exc):
        _BUILD_SPACE.budget = self.prev
        return False


def _grown_bank_size(img_path, byidx, grows):
    """The exact length ``image.bin`` comes to once :func:`_stage_grown_image`
    has appended every sound in *grows*, read off the bank's header before
    anything is staged."""
    from .spike2 import masterdir as MD
    with open(_lp(img_path), "rb") as f:
        md_off, count = MD.header_geometry(f.read(0x100))
    return _grown_bank_bytes(md_off, count,
                             [_grown_body_bytes(byidx[i], grows[i][1])
                              for i in sorted(grows)])


def _clip_seconds(path, cap):
    """How long the video at *path* runs, at most *cap* (and *cap* when that
    can't be told)."""
    from ...core import video as _video
    try:
        info = _video.detect_video_info(path)
    except Exception:  # noqa: BLE001 - unknown: the longest it can be
        info = None
    dur = float(getattr(info, "duration", 0) or 0)
    return min(cap, dur) if dur > 0 else cap


def _kept_size_growth(row, sizes):
    """Bytes the scene of one ``_changed_radium_images`` *row* grows by when
    its picture keeps its own size (PAD-154): the picture's blocks at that
    size less the ones it replaces.  0 for a picture of the stock grid, which
    is patched in place.  *sizes* memoises each PNG's size (an atlas has
    hundreds of rows)."""
    staged, length, pad_w, pad_h, fmt = row[2], row[4], row[5], row[6], row[7]
    if staged not in sizes:
        try:
            from PIL import Image
            with Image.open(_lp(staged)) as im:
                sizes[staged] = im.size
        except Exception:  # noqa: BLE001 - unreadable: its own step says so
            sizes[staged] = None
    wh = sizes[staged]
    if wh is None:
        return 0
    w, h = _padded4(wh[0]), _padded4(wh[1])
    if (w, h) == (int(pad_w), int(pad_h)):
        return 0
    n = w * h                          # BC3: a byte a pixel
    if fmt == _DXT1_FORMAT:
        n //= 2                        # BC1: half that
    return max(0, n - int(length))


def _unsized_bytes(assets_dir, mode_list, code_list, radimg_edits):
    """What the pre-flight counts for the big whole-file copies that are only
    made after the encode, from what is on disk before it: each mode's own
    clip (:data:`_MODE_CLIP_BYTES_PER_S` for as long as it can run), its own
    screen (:data:`_MODE_SCREEN_BYTES`), and each picture kept at its own
    size (:func:`_kept_size_growth`).  Each is an upper bound, so a build
    that passes has room for them."""
    total = 0
    if mode_list or code_list:
        from . import mode_project as _MP

        def clip(kind, seconds, name, folder):
            if kind == "title":
                s = min(max(float(seconds or 0), 0.0), _MODE_CLIP_MAX_S)
            elif kind == "file" and name:
                s = _clip_seconds(os.path.join(folder, name), _MODE_CLIP_MAX_S)
            else:
                return 0
            return (int(s * _MODE_CLIP_BYTES_PER_S * _MODE_CLIP_OVERSHOOT)
                    + _MODE_CLIP_CONTAINER)
        for slug, spec in mode_list or ():
            folder = _MP.mode_folder(assets_dir, slug)
            kind = getattr(spec, "clip", "none") or "none"
            if kind != "none":
                total += clip(kind, getattr(spec, "clip_seconds", 0),
                              getattr(spec, "clip_file", ""), folder)
                both = getattr(spec, "clip_both", None)
                if isinstance(both, dict) and both.get("clip") in ("title",
                                                                  "file"):
                    total += clip(both["clip"], both.get("seconds", 4.0),
                                  both.get("file", ""), folder)
            if getattr(spec, "screen", False):
                total += _MODE_SCREEN_BYTES
        for slug, spec in code_list or ():
            folder = _MP.mode_folder(assets_dir, slug)
            if getattr(spec, "clip", ""):
                total += clip("file", 0, spec.clip, folder)
            if getattr(spec, "screen", False):
                total += _MODE_SCREEN_BYTES
    return total + sum(_kept_size_scenes(radimg_edits).values())


def _kept_size_scenes(radimg_edits):
    """``{scene card_rel: bytes}``: how much each scene grows by around the
    pictures in it kept at their own size (:func:`_kept_size_growth`, an
    upper bound), for the scenes that grow at all."""
    sizes, scenes = {}, {}
    for row in radimg_edits or ():
        n = _kept_size_growth(row, sizes)
        if n:
            rel = str(row[1]).lstrip("/")
            scenes[rel] = scenes.get(rel, 0) + n
    return scenes


class _SpaceCard:
    """One card image a build's whole-file copies may land on, as the
    pre-flight measures it: the files on its games partition (read by
    *reader*) and the blocks free there, with the partition grown to
    *grow_to* first when the build grows the card.  *room* is the usable
    bytes at the card's own class and each of *sizes*."""

    def __init__(self, cs, reader, path, grow_to, sizes, route):
        self.space = cs.p3_space(reader)
        self.bs = self.space.block_size
        self.files, self.by_block = {}, {}
        for p, _ino, node in reader.iter_regular_files(min_size=0,
                                                       max_depth=20):
            rel = p.lstrip("/")
            self.files[rel] = node
            self.by_block[bytes(node["i_block"])] = rel
        try:
            with open(_lp(path), "rb") as f:
                layout = cs.read_layout(f)
        except (cs.CardSizeError, OSError):
            layout = None            # not Stern-shaped: measured as it is
        self.at = grow_to if layout is not None else None
        nb = (cs.p3_blocks_at(layout, grow_to, self.bs)
              if layout is not None else None)
        self.avail = cs.usable_blocks(self.space, nb, route)
        self.room, self.current = {}, None
        if layout is not None:
            own = cs.class_of(layout.laid_out)
            self.current = grow_to or own
            self.room = cs.room_by_class(layout, self.space,
                                         [own] + list(sizes or ()), route)

    def held(self, node):
        """Blocks *node* holds on the partition now (its extent tree too)."""
        if node is None:
            return 0
        blocks = node.get("blocks_lo")
        if blocks is None:
            return -(-int(node.get("size") or 0) // self.bs)
        if int(node.get("flags") or 0) & _HUGE_FILE_FL:
            return int(blocks)
        return int(blocks) * 512 // self.bs

    def growth(self, rel, new_bytes):
        """Blocks the file at *rel* takes on beyond what it holds now when a
        copy makes it *new_bytes* long (a file the card lacks holds none)."""
        return max(0, -(-int(new_bytes) // self.bs)
                   - self.held(self.files.get(rel)))


class _SpaceCheck:
    """PAD-176's pre-flight: whether the files this build copies onto the card
    whole fit its games partition, answered before the sounds are encoded
    and before the build writes a byte to its output (the Build has
    already converted the replacements it had to).  A build that doesn't fit
    is refused with :class:`.card_size.WontFit`, which names the smallest SD
    card size it fits.

    Everything is counted in filesystem blocks, as the copies will change
    them: a file that grows adds ``ceil(new / block) - blocks it holds now``,
    one that shrinks adds nothing (the copy-time check counts the same way).
    The partition's free space is the ORIGINAL's, grown to the build's SD
    card size first when the build grows it (:attr:`whole`).  An update is
    measured against the build already at the output (:attr:`update`),
    whose files are counted as they are there now; when it doesn't fit there
    but fits made from the original, it is made from the original
    (:attr:`_SpaceBudget.whole`).  A refusal is always worded for a build
    from the original: the Write tab's SD card size note quotes those
    figures, and a bigger size is always a whole build.  *route*
    (card_size.ROUTE_MOUNT / ROUTE_PINNED) is how the copies reach the card,
    which decides whether the kernel's reserve comes off.

    A replacement video goes on as the user's own file or as the app's
    converted copy (:func:`_intact_verdict`), which this settles for every
    clip up front, a 12-byte read and an ffprobe or two each, and hands to
    the video step (:attr:`verdicts`, with :attr:`grow_check`) so nothing is
    probed twice.  So each clip counts at the one size that goes on, and the
    need, the refusal and the room the sound bank is given all come from one
    count.  A clip fitted into its slot in place (no assigned file, or a
    computer that can't copy whole files) adds nothing.  *unsized* bytes are
    the sized allowance for the big copies made after the encode
    (:func:`_unsized_bytes`, counted as growth), *margin* the flat one for
    the small ones.  *scenes* (:func:`_kept_size_scenes`) are the part of
    the allowance that is the scenes grown around pictures kept at their own
    size, by scene: the last build grew them on the build already at the
    output, so an update counts each only past what it holds there
    (:meth:`_allowance`)."""

    def __init__(self, budget, disk_f, parts, route, unsized, margin, log,
                 cancel=None, scenes=None):
        from . import card_size as _cs
        from .ext4 import Ext4Reader
        self.cs = _cs
        self.budget = budget
        self.log = log
        self.cancel = cancel or (lambda: False)
        self.done = False
        self.cancelled = False
        self.clips = []            # (fname, card_rel, bytes of the file that goes on)
        self.verdicts = {}         # fname -> _intact_verdict's answer
        self.grow_check = None     # ext4_grow.available()'s answer, once asked
        orig, _fw, img_node = _locate(disk_f, parts)
        self.whole = _SpaceCard(_cs, orig, budget.original, budget.grow_to,
                                budget.sizes, route)
        self.bs = self.whole.bs
        self.img_rel = (self.whole.by_block.get(bytes(img_node["i_block"]))
                        if img_node is not None else None)
        self.update = None
        if budget.updating:
            with open(_lp(budget.output), "rb") as f:
                f.seek(0, os.SEEK_END)
                self.update = _SpaceCard(
                    _cs, Ext4Reader(f, orig.base, f.tell() - orig.base),
                    budget.output, None, (), route)
        self.card = self.update or self.whole
        self.scenes = dict(scenes or {})
        # on the original: the whole allowance, the scenes' growth in it
        self.unsized = -(-(int(unsized or 0) + sum(self.scenes.values()))
                         // self.bs)
        self.unsized_rest = -(-int(unsized or 0) // self.bs)
        self.margin = -(-int(margin or 0) // self.bs)
        self.uncounted = 0         # clips space_floor couldn't size yet

    def _copies_whole(self):
        """Whether this computer copies files onto the card whole at all.
        Without the ext4 driver every video is fitted into its slot and
        nothing grows, so there is nothing to measure.  Asked once a build
        (it starts WSL): a grow gate's answer is taken from the budget
        (:func:`_ext4_can_grow`), this one is left there for the gates, and
        it goes on to the video step.  Asked on the probes' pool too, where
        the build's scope isn't open, so the budget is read directly."""
        if self.grow_check is None:
            got = getattr(self.budget, "grow_check", None)
            if got is None:
                from ...core import ext4_grow
                try:
                    got = ext4_grow.available()
                except Exception as e:  # noqa: BLE001 - unknown: the copy decides
                    got = (False, str(e))
                self.budget.grow_check = got
            self.grow_check = (bool(got[0]), got[1])
        return self.grow_check[0]

    def add_videos(self, video_edits, originals):
        """Count each changed video that goes on whole: the ones with an
        assigned replacement (*originals*, the staged_changes "video" map)
        whose file is still there, exactly as _prepare_video_patches picks
        them, each as the file :func:`_intact_verdict` puts on the card.  The
        probes run side by side, beside the question whether this computer
        copies whole files at all."""
        todo = []
        for fname, card_path, staged in video_edits:
            src = (originals or {}).get("video/" + fname)
            if not (src and os.path.isfile(src)):
                continue                # fitted into its slot in place
            rel = card_path.lstrip("/")
            if rel not in self.whole.files:
                continue                # not on the card: the build skips it
            todo.append((fname, rel, src, staged))
        if not todo:
            return
        if self.cancel():
            self.cancelled = True
            return
        if len(todo) > _SETTLE_SAY:
            self.log("Checking which file each of the %d replaced videos goes "
                     "on the card as (your own file or the app's converted "
                     "copy), so the room they need is known before the card "
                     "image is written..." % len(todo), "info")
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(
                max_workers=min(_SETTLE_WORKERS, len(todo)) + 1) as pool:
            asked = pool.submit(self._copies_whole)
            probes = [(t, pool.submit(_intact_verdict, t[2], t[3]))
                      for t in todo]
            asked.result()
            for (fname, rel, src, staged), fut in probes:
                try:
                    verdict = fut.result()
                except Exception:  # noqa: BLE001 - the video step says why
                    # unsettled: the bigger file, so the count never falls short
                    self.clips.append((fname, rel,
                                       max(_size(src), _size(staged))))
                    continue
                self.verdicts[fname] = verdict
                self.clips.append((fname, rel,
                                   _size(src) if verdict[0] else _size(staged)))
        if self.cancel():
            self.cancelled = True
        if not self._copies_whole():
            self.clips = []             # every clip is fitted in place

    def _allowance(self, card):
        """Blocks the sized allowance takes on *card*.  All of it on the
        original.  On the build already at the output a scene the last build
        grew around a kept-size picture holds those blocks there already, and
        an unchanged one is not copied again, so each scene counts only what
        it grows past what it holds, as a clip does."""
        if card is not self.update or not self.scenes:
            return self.unsized
        n = self.unsized_rest
        for rel, grow in self.scenes.items():
            node = self.whole.files.get(rel)
            if node is None:
                n += -(-grow // self.bs)
            else:
                n += card.growth(rel, int(node.get("size") or 0) + grow)
        return n

    def _others(self, card, bank_job=False):
        """Blocks on *card* for everything but the sound bank's data: the
        clips' growth, the sized allowance, each copy's slack (the bank's too
        with *bank_job*) and the margin."""
        grow = sum(card.growth(rel, n) for _f, rel, n in self.clips)
        jobs = len(self.clips) + (1 if bank_job else 0)
        return (grow + self._allowance(card) + jobs * _SPACE_SLACK_BLOCKS
                + self.margin)

    def _need(self, card, bank_bytes):
        """``(grow, need)`` in blocks on *card*: what the files grow by (the
        sized allowance included), and that with the slack and the margin."""
        bank = (bank_bytes is not None and self.img_rel is not None
                and self.img_rel in card.files)
        grow = (sum(card.growth(rel, n) for _f, rel, n in self.clips)
                + self._allowance(card)
                + (card.growth(self.img_rel, bank_bytes) if bank else 0))
        jobs = len(self.clips) + (1 if bank else 0)
        return grow, grow + jobs * _SPACE_SLACK_BLOCKS + self.margin

    def _go_whole(self, why):
        """This update doesn't fit the build already at the output (*why*);
        the same build from the original is measured from here on, and made."""
        self.card = self.whole
        self.budget.whole = why

    def _refuse(self, need, bank_bytes):
        """Raise the refusal, worded for a build from the original."""
        cs, bs, card = self.cs, self.bs, self.whole
        items = [(card.growth(rel, n) * bs, fname)
                 for fname, rel, n in self.clips]
        if (bank_bytes is not None and self.img_rel is not None
                and self.img_rel in card.files):
            items.append((card.growth(self.img_rel, bank_bytes) * bs,
                          "the sound bank with the longer sounds"))
        fits = cs.smallest_fit(need * bs, card.room, above=card.current)
        bigger = [c for c in card.room if card.current is None
                  or cs.CARD_SIZES[c] > cs.CARD_SIZES.get(card.current, 0)]
        largest = bigger[-1] if bigger and not fits else None
        self.done = True
        raise cs.WontFit(
            need * bs, card.avail * bs, items, fits=fits,
            fits_room=card.room.get(fits) if fits else None,
            largest=largest,
            largest_room=card.room.get(largest) if largest else None,
            at=card.at, fixed=self.budget.fixed,
            early=getattr(self.budget, "early", False),
            uncounted=self.uncounted, current=card.current)

    def _bank_room(self, card):
        node = card.files.get(self.img_rel) if self.img_rel else None
        if node is None:
            return None
        others = self._others(card, bank_job=True)
        limit = max(0, card.held(node) + card.avail - others) * self.bs
        whole = self.whole
        w_others = self._others(whole, bank_job=True)

        def suggest(bank_bytes):
            # a bigger size is always a build from the original
            return self.cs.smallest_fit(
                (w_others + whole.growth(self.img_rel, bank_bytes)) * self.bs,
                whole.room, above=whole.current)
        return _BankRoom(limit=limit, free=card.avail * self.bs,
                         others=min(others, card.avail) * self.bs,
                         suggest=suggest, fixed=self.budget.fixed)

    def bank_room(self, want=None, kept_at=None):
        """The :data:`_BankRoom` a grown bank has beside everything else this
        build copies whole (counted exactly as :meth:`check` counts it), or
        None when the bank isn't on the card.  *want* is the length the
        bank's longer sounds would take it to, and *kept_at(limit)* the
        sounds the bank's budget keeps whole in a bank of at most *limit*
        bytes (the game's own limit applied too).  When an update's room
        can't hold *want* and a build from the original keeps more of them,
        the build is made from the original, so an update never trims a song
        a whole build keeps, and never copies the whole card again to trim
        the same ones."""
        from .spike2.emulator import MAX_IMAGE_BYTES
        room = self._bank_room(self.card)
        if (room is not None and self.card is self.update
                and want is not None
                and room.limit < min(want, MAX_IMAGE_BYTES)):
            wroom = self._bank_room(self.whole)
            if (wroom is not None and wroom.limit > room.limit
                    and (kept_at is None
                         or kept_at(wroom.limit) != kept_at(room.limit))):
                self._go_whole(
                    "the longer sounds don't all fit on the games partition "
                    "of the build already there (%s free), and built from "
                    "the original there is more room for them"
                    % self.cs.size_words(room.free))
                return wroom
        return room

    def check_grown(self, img_path, byidx, grows):
        """:meth:`check` with the sound bank at the length the grows in
        *grows* (idx -> ``(room, wanted)``) give it, or none grown."""
        bank = None
        if grows:
            try:
                bank = _grown_bank_size(img_path, byidx, grows)
            except Exception as e:  # noqa: BLE001 - the stage says it better
                self.log("The grown sound bank's length could not be worked "
                         "out ahead (%s); the copy at the end still checks "
                         "the room for it." % e, "info")
        self.check(bank_bytes=bank)

    def check(self, bank_bytes=None, final=True):
        """Refuse the build (:class:`.card_size.WontFit`) when what it copies
        on whole can't fit, counting the grown bank at *bank_bytes* when it
        grows one.  An update that doesn't fit the build already there but
        fits made from the original is made from the original instead.  With
        *final* the budget is logged, the check is done and the build may
        start writing (:meth:`_SpaceBudget.clear`); without, only the refusal
        can happen (the videos, before the audio is read)."""
        if self.done or self.cancelled:
            return
        cs, bs = self.cs, self.bs
        card = self.card
        grow, need = self._need(card, bank_bytes)
        if grow and need > card.avail and self._copies_whole():
            if card is self.update:
                w_grow, w_need = self._need(self.whole, bank_bytes)
                if w_need > self.whole.avail:
                    self._refuse(w_need, bank_bytes)
                self._go_whole(
                    "the build already there has %s free on its games "
                    "partition and this build needs %s of it, while built "
                    "from the original it needs %s of %s"
                    % (cs.size_words(card.avail * bs), cs.size_words(need * bs),
                       cs.size_words(w_need * bs),
                       cs.size_words(self.whole.avail * bs)))
                card, grow, need = self.whole, w_grow, w_need
            else:
                self._refuse(need, bank_bytes)
        if not final:
            return
        self.done = True
        at = " on a %s SD card" % cs.words(card.at) if card.at else ""
        where = ("The games partition of the build being updated"
                 if card is self.update else "The games partition")
        if not grow:
            self.log("%s has %s free%s." % (where,
                                            cs.size_words(card.avail * bs),
                                            at), "info")
        elif self._copies_whole():
            # (without the ext4 driver nothing goes on whole: no figure)
            self.log("%s has %s free%s and this build needs about %s of it."
                     % (where, cs.size_words(card.avail * bs), at,
                        cs.size_words(need * bs)), "info")
        self.budget.clear()


def _space_check(space, disk_f, parts, assets_dir, video_edits, log,
                 mode_list=(), code_list=(), radimg_edits=(), margin=0,
                 cancel=None):
    """The build's :class:`_SpaceCheck`, with its videos counted and settled,
    or None when the build isn't measured (*space* is None) or can't be: a
    card the reader can't size is left to the copy-time check, and the log
    says so.

    The copies are measured as the kernel's ext4 driver makes them (a loop
    mount, card_size.ROUTE_MOUNT), which keeps a reserve back, everywhere but
    macOS, where every copy goes through debugfs, which doesn't.  A build
    whose copies go through debugfs elsewhere (one carrying modes) is so
    measured with that reserve (16 MB at most) to spare: the Write tab's note
    quotes the mount route's figures, and the refusal quotes the same."""
    if space is None:
        return None
    from . import card_size as _cs
    route = _cs.ROUTE_PINNED if sys.platform == "darwin" else _cs.ROUTE_MOUNT
    try:
        unsized = _unsized_bytes(assets_dir, mode_list, code_list, ())
        chk = _SpaceCheck(space, disk_f, parts, route, unsized, margin, log,
                          cancel=cancel, scenes=_kept_size_scenes(radimg_edits))
        if video_edits:
            from ...core import staged_changes as _sc
            chk.add_videos(video_edits,
                           _sc.load(assets_dir).get("video") or {})
    except Exception as e:  # noqa: BLE001 - never fail a build on a measure
        log("The games partition's free space could not be measured before "
            "the build (%s); the copy at the end still checks it." % e, "info")
        return None
    return chk


def space_floor(original_path, grow_to=None, output_path=None,
                updating=False):
    """PAD-176 for a Build's first step (Stern write_preflight), before the
    Replace tabs stage anything: ``refuse(clips)``, which raises
    :class:`.card_size.WontFit` when *clips* (``(fname, card_rel, bytes)``,
    videos sure to go on whole at no fewer bytes) can't fit, counted exactly
    as :class:`_SpaceCheck` counts a build (with *updating*, the build at
    *output_path* first).  Nothing else is counted, and the caller has
    settled that this computer copies whole files, so a build refused here
    is one the pre-flight refuses too.  A clip that doesn't grow its file is
    left out: it may be the stock file, which no build copies.  The refusal
    says its need is a floor (WontFit *early*), and with *uncounted* (the
    clips counted short of the file that may go on) names no size as
    enough."""
    from . import card_size as _cs
    route = _cs.ROUTE_PINNED if sys.platform == "darwin" else _cs.ROUTE_MOUNT
    try:
        sizes = _cs.offered(original_path)
    except Exception:  # noqa: BLE001 - a hint is never worth a refusal
        sizes = []
    budget = _SpaceBudget(original_path, output=output_path,
                          updating=updating, grow_to=grow_to, sizes=sizes)
    budget.early = True
    with open(_lp(original_path), "rb") as disk_f:
        chk = _SpaceCheck(budget, disk_f, _linux_partitions(original_path),
                          route, 0, 0, lambda *a, **k: None)
    chk.grow_check = (True, None)

    def refuse(clips, uncounted=0):
        chk.card, chk.done = chk.update or chk.whole, False
        chk.clips = [c for c in clips if c[1] in chk.whole.files
                     and chk.whole.growth(c[1], c[2]) > 0]
        chk.uncounted = int(uncounted or 0)
        chk.check(final=False)
    return refuse


def _compute_patches(disk_f, parts, assets_dir, log, progress, cancel,
                     phase=None, label=None, dest_is_device=False,
                     boot_screen=True, sound_ok=None):
    """Diff *assets_dir* against the Extract baseline, re-encode / size-fit the
    edits, and resolve them to a flat list of absolute on-disk writes
    ``[(disk_offset, bytes), ...]`` (offsets relative to the start of
    ``disk_f`` — i.e. of the whole card image / device).

    ``disk_f`` is an already-open seekable byte stream over the card image OR
    the physical card; the caller owns it (it must stay open for the duration of
    this call) and closes it afterwards.  This is the shared core of both the
    file Write (:func:`write_image`) and the Direct-SD Write
    (:func:`write_device`), so the exact same patch set is produced whether the
    destination is an image copy or the card itself.  ``boot_screen=False``
    leaves a replaced boot screen out (an override set: the emulator starts
    the game without it).  ``sound_ok=False`` closes the modes' own-sound
    gate for this build alone (they are left out with the reason); ``None``
    consults the environment gate exactly as before.  Inside a
    :class:`_SpaceScope` (which :func:`write_image` opens around this call)
    what the build copies on whole is measured against the games partition
    before anything is encoded, and :class:`.card_size.WontFit` is raised when
    it can't fit (:class:`_SpaceCheck`); outside one nothing is measured.

    Returns ``(writes, counts, grow_plan, audio_mode, valpatch_mode)`` where
    ``counts`` is
    ``(n_audio, n_video, n_image, n_text)`` and ``audio_mode`` says how the
    re-encoded cat-0 sounds were built: ``None`` (no cat-0 audio in this
    write), ``("blip-free", "")`` (the firmware cave applied), or
    ``("standard", why)`` (the fallback build -- the original-sound scrap
    remains at the two master-directory windows).  ``valpatch_mode`` says
    whether Stern's SD-card validator was actually neutralised on this card
    (see :func:`.valpatch.bypass_status`).  Every element is ``None``
    if cancelled.  Raises
    ``FileNotFoundError`` when there's nothing to write and ``RuntimeError``
    when nothing could be re-encoded / fit."""
    phase = phase or (lambda i: None)

    import numpy as np

    from ...core.checksums import read_checksums
    from .spike2.emulator import audio_decode_supported

    # Only re-encode/patch what the user actually changed.  The folder is
    # normally the whole Extract output (thousands of idxNNNN.wav + the LCD
    # videos); diff each asset against the Extract baseline (.checksums.md5) so
    # an untouched (or merely Auto-transcribe-renamed) sound/clip is skipped.
    # The leading index survives a rename ("idx0651 - text.wav"); the walk is
    # recursive so Write works from the extract root or its audio/ subdir.
    t_scan = time.monotonic()
    baseline = read_checksums(assets_dir)
    audio_edits = _select_changed_idx_wavs(assets_dir, baseline)

    video_edits = _changed_videos(assets_dir, baseline)
    image_edits = _changed_images(assets_dir, baseline)
    # The boot screen is on the OS partition (PAD-147).  The emulator starts
    # the game without it, so an override set leaves it out.
    boot_edits = _changed_boot_images(assets_dir, baseline)
    if boot_edits and not boot_screen:
        log("The boot screen isn't shown by the emulator, so the replaced one "
            "is left out of this run; build the card to see it.", "info")
        boot_edits = []
    texture_edits = _changed_scene_textures(assets_dir, baseline)
    # Edited font-glyph slices make their atlas count as an edited radium image
    # (the composite happens inside _radium_image_writes).
    glyph_edits = _changed_glyph_images(assets_dir, baseline)
    radimg_edits = _changed_radium_images(assets_dir, baseline,
                                          extra_changed=set(glyph_edits))
    # Per-song music banks (music_catNN_*.wav) edited by the user — re-encoded
    # back into their image-scNN.bin banks (see _compute_music_patches).
    music_edits = _changed_music_banks(assets_dir, baseline)
    # Edited LCD display strings (text/strings.tsv rows where replacement !=
    # original) — patched size-neutral, in place, into their .radium scenes.
    text_edits = _changed_radium_text(assets_dir)
    # Recoloured display text (text/colors.tsv) — the colour lives in the scene,
    # not in the font, so this is a radium patch too.
    color_edits = _changed_radium_text_colors(assets_dir)
    # Re-laid-out display text (text/layout.tsv): a line's position, alignment
    # and size are scene bytes too (the rect, the align word, the scene's own
    # glyph table), so this is a third size-neutral radium patch.
    layout_edits = _changed_radium_text_layouts(assets_dir)
    # The game's own modes (item 145): staged timers / awards of the modes the
    # game shipped with - word patches in the game ELF, and the table's
    # operator-setting defaults (a battle timer) in the same ELF.
    stock_mode_edits = _stock_mode_pending(assets_dir)
    if (not stock_mode_edits and not audio_edits and not music_edits
            and not video_edits and not image_edits and not texture_edits
            and not radimg_edits and not text_edits and not color_edits
            and not layout_edits and not boot_edits):
        # nothing staged, but the card this is built from may hold our words
        stock_mode_edits = _stock_mode_words_to_restore(disk_f, parts,
                                                        assets_dir)
    _save_hashcache(assets_dir)
    _stage_done(log, "scanning the assets for changes (checksumming every "
                "sound and video against the Extract baseline)", t_scan)

    # Item 149: the project's MODES (<project>/modes/<slug>/mode.json) are one
    # more change a build applies.  A mode that does not load stops the Write
    # (never dropped quietly); a closed gate leaves them all out with a reason.
    # THE PREVIEW SWITCH OFF: the modes are not even read (a broken one cannot
    # stop the Write), one sentence says they are left out, and the build goes
    # on exactly as one without the family would.
    from . import mode_write as _MW
    _family = _mode_family_on()
    # The own-sound gate, decided ONCE for this build.  A caller that closes
    # it (Try it's fast run) passes sound_ok=False, so a quick set can be
    # built beside a full Write without either touching the environment the
    # other one reads (the env gate is process-wide).
    _sound_gate = ((False, "left out of this run") if sound_ok is False
                   else _MW.sound_gate())
    mode_list, code_list = [], []
    mode_sound = None
    mode_own = []              # the start / shot sounds and music on carriers (item 150)
    _modes_left_out = None     # (names, why) when a closed gate took the modes out
    if not _family:
        _off = _MW.preview_left_out(assets_dir)
        if _off:
            log(_off, "warning")
            if _MW.held_modes(assets_dir):
                # neutral words for "Nothing to write" (_modes_left_out_clause)
                _modes_left_out = ("preview", _MW.preview_held(assets_dir))
    else:
        try:
            mode_list = _MW.project_modes(assets_dir)
        except _MW.ModeWriteError as e:
            raise RuntimeError("Modes: %s. Fix or delete it in the Modes tab, then "
                               "Write again." % e) from None
    if mode_list:
        _mok, _mwhy = _MW.gate(dest_is_device)
        if not _mok:
            log("Modes: the project's %d mode(s) are left out of this build: %s."
                % (len(mode_list), _mwhy), "warning")
            _modes_left_out = ([s.name for _g, s in mode_list], _mwhy)
            mode_list = []
        else:
            log("Found %d mode(s) to write: %s."
                % (len(mode_list), ", ".join(s.name for _g, s in mode_list)),
                "info")
            # item 148: the modes as the project's CARD runs them (its port,
            # masks and scenes), exactly as mode_assets.build makes them
            try:
                mode_list = _MW.card_modes(assets_dir, mode_list)
            except _MW.ModeWriteError as e:
                raise RuntimeError("Modes: %s Nothing was written." % e) from None
            mode_sound = _MW.choose_end_sound(assets_dir, mode_list,
                                              _sound_gate, log)
            mode_own = _MW.choose_own_sounds(assets_dir, mode_list,
                                             _sound_gate, end_sound=mode_sound,
                                             log=log)
    # The CODE modes (modes/<slug>/<slug>.c) travel too, with their own clip,
    # screen, music and calls (modes/<slug>/assets.json): compiled into the
    # card's object, their sounds on carriers from the same allocator.
    if _family:
        try:
            code_list = _MW.code_mode_list(assets_dir)
        except _MW.ModeWriteError as e:
            raise RuntimeError("Modes: %s. Fix or delete it in the Modes tab, then "
                               "Write again." % e) from None
    if code_list:
        _cok, _cwhy = _MW.gate(dest_is_device)
        if not _cok:
            log("Modes: the project's %d code mode(s) are left out of this build: %s."
                % (len(code_list), _cwhy), "warning")
            _modes_left_out = ((_modes_left_out or ([], _cwhy))[0]
                               + [c.name for _g, c in code_list], _cwhy)
            code_list = []
        else:
            log("Found %d code mode(s) to write: %s."
                % (len(code_list), ", ".join(c.name for _g, c in code_list)), "info")
            from . import code_modes as _CM
            _cprof = (_MW.MP.profile(mode_list[0][1].title) if mode_list
                      else _CM.profile_for(assets_dir, code_list))
            _req, _beds = _MW.own_sounds_taken(mode_own)
            if mode_sound and mode_sound.get("request"):
                _req.append(int(mode_sound["request"]))
            mode_own = list(mode_own) + _MW.choose_code_sounds(
                assets_dir, code_list, _sound_gate, _cprof, taken=_req,
                taken_beds=_beds, log=log)
    # Item 160: the counts-as table (modes/stock.json -> stock.cfg) rides with the modes'
    # runtime, which goes on the card only with a mode; with none, say so rather than
    # dropping the rows without a word.
    if _family and not mode_list and not code_list:
        for _line in _MW.stock_lines(assets_dir, carried=False):
            log("Modes: %s." % _line, "warning")

    if (not audio_edits and not music_edits and not video_edits
            and not image_edits and not texture_edits and not radimg_edits
            and not text_edits and not color_edits and not layout_edits
            and not boot_edits and not mode_list and not code_list
            and not stock_mode_edits):
        raise NothingToWrite(
            "Nothing to write: " + _modes_left_out_clause(_modes_left_out)
            + "every sound (idxNNNN.wav / music_catNN_*.wav) "
            "still matches the Extract baseline (.checksums.md5) and no replaced "
            "videos or images and no edited display text (text/strings.tsv, "
            "text/colors.tsv, text/layout.tsv) were found under %s. Edit a "
            "sound, change a display string, or assign a Replace Video / "
            "Replace Image asset first, then Write." % assets_dir)
    if audio_edits:
        listing = _fmt_idx_list(audio_edits)
        if baseline:
            log("Found %d edited sound(s) to write: %s."
                % (len(audio_edits), listing), "info")
        else:
            log("No .checksums.md5 baseline found; re-encoding all %d sound(s): "
                "%s." % (len(audio_edits), listing), "warning")
        # Raw encode (replacements written as provided) is THE behavior now —
        # the GUI retired the match-to-callouts shaper (feedback batch 20) and
        # pins PAD_STERN_AUDIO_RAW=1 at startup.  Only the unusual case gets a
        # log line: shaping still fingerprints a card built with the env var
        # cleared by hand (a phone recording of the machine can't settle which
        # mode built a card after the fact — a tester's 2026-07 click A/B).
        if os.environ.get("PAD_STERN_AUDIO_RAW") != "1":
            log("Audio shaping ON (PAD_STERN_AUDIO_RAW unset): replacements "
                "get the stock-callout edge fade, level cap, and 5 kHz "
                "roll-off instead of being written as provided.", "warning")
        # Advanced audio options leave fingerprints in the log for the same
        # reason the shaping mode does: a card built during an experiment must
        # be identifiable as such after the fact.
        adv = [(lbl, os.environ.get(var))
               for var, lbl in (("PAD_STERN_FADE_MS", "edge fade ms"),
                                ("PAD_STERN_HEADROOM", "level cap"),
                                ("PAD_STERN_LOWPASS_HZ", "treble roll-off Hz"),
                                ("PAD_STERN_HEAD_MODE", "head block"),
                                ("PAD_STERN_LEADOUT", "tail block"),
                                ("PAD_STERN_MATCH_LOUDNESS", "loudness match"),
                                ("PAD_STERN_MATCH_GAIN_DB", "loudness offset dB"),
                                ("PAD_STERN_SLOT_SEED_DB", "anti-pop seed dBFS"))]
        adv = ["%s=%s" % (lbl, v) for lbl, v in adv if v]
        if adv:
            log("Advanced audio overrides active for this build: %s."
                % "; ".join(adv), "warning")
        # Always say how replacements were levelled.  Matching is scale-
        # invariant, so a user who remixes a track louder and rebuilds gets a
        # byte-identical result and no clue why (a tester, Godzilla music
        # imports).  The one place he will look is this log.
        log("Replacement loudness: %s." % _loudness_log_phrase(), "info")
        if not _pathA_enabled():
            log("Blip-free callouts OFF for this build (the default): a "
                "re-encoded sound keeps a ~6 ms scrap of the original at the "
                "two master-directory windows, and no code is added to the game "
                "firmware (only the long-standing 4-byte validator bypass).",
                "info")
        else:
            # Warning, not info: this is an opt-in firmware patch that has
            # boot-looped the only machine it has ever reached, so the build log
            # has to say so where somebody diagnosing a dead machine will see it.
            log("Blip-free callouts ON for this build -- this is the "
                "experimental setting, and it is not known to boot. Patching "
                "game_real so the boot-derive reads stock master-directory "
                "windows means re-encoded callouts play your audio for their "
                "whole length with no ~6 ms original scrap. Every card built "
                "this way that has reached a machine has looped through the "
                "startup screen, most recently on v0.102.6 after two faults in "
                "the patch were fixed, and none has been confirmed to boot. If "
                "yours does that, clear the box in Advanced Audio Options and "
                "rebuild from your original image. Needs the Linux filesystem "
                "driver because it grows the game binary; falls back to the "
                "standard build for any firmware or host it can't safely "
                "handle.", "warning")
        if _slot_seed_dbfs() is not None:
            log("Anti-pop seed ON (%.0f dBFS): mixing an inaudible low tone into "
                "replacements so a callout is never digitally silent -- aimed at "
                "the start-pop the machine's audio output adds on silent/quiet "
                "callouts (the codec itself is clean). Experimental; HW-"
                "unverified; per-slot idx gate applies." % _slot_seed_dbfs(),
                "info")
    if music_edits:
        log("Found %d edited music-bank song(s) to re-encode." % len(music_edits),
            "info")
    # Per-clip loudness offsets (Replace Audio tab -> Level).  Logged next to
    # the build-wide "Replacement loudness" line and for the same reason: a
    # level the user set weeks ago is invisible in the audio itself, so the log
    # has to be able to answer "why is this one song louder than the rest?".
    slot_gains, music_gains = _slot_gain_maps(assets_dir)
    if slot_gains or music_gains:
        both = dict(slot_gains)
        both.update(music_gains)
        log("Per-clip loudness set on %d sound(s) (build-wide offset already "
            "included): %s." % (len(both), _fmt_gain_map(both)), "info")
    if video_edits:
        log("Found %d replaced video(s) to write." % len(video_edits), "info")
    if image_edits:
        log("Found %d replaced image(s) to write." % len(image_edits), "info")
    if boot_edits:
        log("Found %d replaced boot screen image(s) to write."
            % len(boot_edits), "info")
    if texture_edits:
        log("Found %d edited scene texture(s) to write." % len(texture_edits),
            "info")
    if glyph_edits:
        log("Found %d edited font glyph(s) across %d atlas(es) to write."
            % (sum(len(v) for v in glyph_edits.values()), len(glyph_edits)),
            "info")
    if radimg_edits:
        log("Found %d edited radium image(s) to write." % len(radimg_edits),
            "info")
    if text_edits:
        log("Found edited display text in %d radium scene(s) to write."
            % len(text_edits), "info")
    if color_edits:
        log("Found %d recoloured text line(s) across %d radium scene(s) to "
            "write." % (sum(len(v) for v in color_edits.values()),
                        len(color_edits)), "info")
    if layout_edits:
        log("Found %d re-laid-out text line(s) (moved / re-aligned / resized) "
            "across %d radium scene(s) to write."
            % (sum(len(v) for v in layout_edits.values()),
               len(layout_edits)), "info")

    # PAD-176: what this build copies on whole, against the room on the games
    # partition, before the firmware and the sound bank are read out of the
    # card or anything is encoded.  The videos are settled and counted now,
    # and a build whose videos alone can't fit stops here; the grown sound
    # bank is counted once its exact length is known (after the play-table
    # filter and the bank's budget), still before it is staged.  write_image
    # starts copying the original over the output only once the build has
    # passed (_SpaceBudget.clear), so a refusal leaves the output as it was.
    space = getattr(_BUILD_SPACE, "budget", None)
    space_chk = None
    if space is not None and not dest_is_device:
        _modes_on = bool(mode_list or code_list)
        space_chk = _space_check(
            space, disk_f, parts, assets_dir, video_edits, log,
            # the big files made after the encode, sized from their sources
            mode_list=mode_list, code_list=code_list,
            radimg_edits=radimg_edits,
            # and the small ones (_SPACE_MARGIN)
            margin=(_SPACE_MARGIN if (text_edits or radimg_edits or _modes_on
                                      or (audio_edits and _pathA_enabled()))
                    else 0),
            cancel=cancel)
        if space_chk is not None:
            space_chk.check(final=False)
            if space_chk.cancelled:
                return None, None, None, None, None
    if space is not None and space_chk is None:
        space.clear()               # not measured: the output may be written

    def _read_prog(c, t):
        if progress:
            progress(int(c * 10 / max(t, 1)), 100, "Reading image.bin")

    work = _work_dir(label)
    # The rebuilt blip-free firmware can NOT live in `work`: `work` is deleted
    # by this function's own `finally`, but the firmware is copied onto the card
    # by the CALLER, after we return (it grows the file, so it goes through the
    # ext4 driver rather than the flat write list).  Putting it in `work` left
    # the grow job pointing at a file that no longer existed -- and a job whose
    # source is missing was silently dropped, so the card shipped with its .sidx
    # record already rewritten to describe a firmware that never landed AND
    # without the validator bypass (which the blip-free path skips because the
    # bypass is supposed to ride inside that firmware).  That is a card the
    # machine rejects with GAME VALIDATION ERROR (a tester, James Bond,
    # 2026-07-31).  So it gets its own directory, handed to the caller in the
    # grow plan and removed by the caller once the copy has happened.
    grow_work = None
    grow_work_handed_off = False
    try:
        audio_patches = {}     # body_off -> bytes (inside image.bin)
        music_patches = []     # (sc_node, body_off, bytes) inside image-scNN.bin
        # How this write's cat-0 audio was built, surfaced all the way to the
        # completion dialog.  A fallback build sounds different on the machine
        # -- each replaced sound keeps a ~6 ms scrap of the original at the two
        # master-directory windows, audible as a quick double click on quiet
        # replacements -- but until now only a mid-build log warning said so,
        # and a tester burned two hardware tests on a card he believed was
        # blip-free (Elvira spinner, 2026-07-30).
        audio_mode = None      # None | ("blip-free", "") | ("standard", why)
        # Whether Stern's SD-card validator actually got neutralised on this
        # card (see valpatch.bypass_status).  Carried out to the completion
        # dialog because a firmware whose validator we can't reach still builds
        # a perfectly normal-looking card -- one the machine then refuses with
        # GAME VALIDATION ERROR.
        valpatch_mode = None   # None | ("bypassed"|"absent"|"unlocated", why)
        img_node = None
        fw_node = None
        # Path A: the rebuilt game_real (cave + validator bypass).  It is LONGER
        # than the stock file, so it can't be patched in place like everything
        # else -- it goes on the card as a whole-file copy through the ext4
        # driver, and its .sidx record carries the new size as well as digests.
        patched_gr = None
        # A sound bank grown to hold a replacement longer than its slot.  Like
        # the rebuilt firmware it is longer than the file it replaces, so it
        # goes on the card whole through the ext4 driver and its in-place
        # writes are never emitted.
        grow_places = None
        reader = None
        gr_path = img_path = None
        # Which request a mode's own end sound rode in on, once it has.
        mode_sound_used = None
        mode_own_used = []
        if audio_edits or music_edits or mode_sound or mode_own:
            phase(1)  # Re-encode audio (Direct-SD phase index; no-op for file Write)
            t0 = time.monotonic()
            gr_path, img_path, reader, fw_node, img_node = _extract_inputs(
                disk_f, parts, work, log, _read_prog)
            _stage_done(log, "reading the firmware and audio image out of "
                        "the card", t0)
            if cancel():
                return None, None, None, None, None
            if not audio_decode_supported(gr_path):
                # This title's audio codec can't be re-encoded.  If the user
                # only edited video/images, carry on and write those; otherwise
                # it's a hard error.
                msg = (
                    "Audio re-encode isn't supported for this title yet: its "
                    "game firmware uses a Spike 2 codec the engine can't locate "
                    "a single decode path for (e.g. a dual-path codec), so the "
                    "per-sound keystream can't be derived.")
                if (not video_edits and not image_edits and not boot_edits
                        and not mode_list and not code_list):
                    raise RuntimeError(msg)
                log(msg + "  Writing only the replaced video(s) / image(s).",
                    "warning")
                if mode_sound:
                    log("Modes: %s ends with the game's own time-up call on "
                        "this card (its sounds can't be re-encoded)."
                        % mode_sound["name"], "warning")
                if mode_own:
                    log("Modes: the start sounds, shot sounds and music of the "
                        "modes are not put on this card (its sounds can't be "
                        "re-encoded).", "warning")
                audio_edits = {}
                music_edits = []
                mode_sound = None
                mode_own = []
            else:
                if audio_edits or mode_sound or mode_own:
                    # Re-encode every edited cat-0 sound to its body bytes — fans
                    # across worker processes (each boots its own emulator), with
                    # a single-process fallback.  Params come from the
                    # Extract-time cache; only a cold cache boots an emulator here.
                    params = _params_for(gr_path, img_path, log, progress)
                    # The encode cache is keyed on the STOCK bank even when this
                    # build grows it, so one longer callout doesn't re-encode
                    # every other sound in the mod.  Captured before the grow
                    # stages its copy over the extracted file.
                    stock_ident = _image_identity(img_path)
                    # A replacement longer than its slot is trimmed to fit
                    # unless this write may grow the bank.  Deciding it HERE,
                    # before the cache is consulted, is what stops a clip that
                    # was trimmed on the last build replaying its trimmed body
                    # into a build that could have kept it whole.
                    grows = {}
                    grow_places = None
                    _greads = None      # the staged bank's consumed map, once derived
                    _fits, _grows = _classify_audio_edits(
                        {p["idx"]: p for p in params}, audio_edits, assets_dir)
                    if _grows:
                        _gok, _gwhy = _audio_grow_gate(dest_is_device, gr_path)
                        if _gok:
                            _gok, _gwhy = _grown_source_gate(params)
                        if _gok:
                            grows = _grows
                        else:
                            log(*_trimmed_notice(_grows, _gwhy))
                    desc_sites = []
                    if grows:
                        # A longer copy is only worth appending if a play
                        # table names the sound: the copy registers under a
                        # key of its own, and the table is re-pointed at it
                        # once the staged bank has been derived.
                        t0 = time.monotonic()
                        if progress:
                            progress(10, 100, "Reading the game's play tables...")
                        desc_sites = _descriptor_sites(gr_path, img_path, log)
                        grows = _grows_named_by_a_descriptor(
                            grows, {p["idx"]: p for p in params}, desc_sites,
                            log)
                        _stage_done(log, "reading the game's play tables", t0)
                    # the user's longer sounds; the modes' own are FORCED
                    # grows added below, which the bank's budget can't trim
                    _user_grows = dict(grows)
                    if mode_sound:
                        # Item 149: a mode's own end sound is a FORCED grow of
                        # the record its time-up request plays, so the re-point,
                        # the count patch and the bypass follow as for any
                        # grown bank.
                        if not desc_sites:
                            t0 = time.monotonic()
                            if progress:
                                progress(10, 100,
                                         "Reading the game's play tables...")
                            desc_sites = _descriptor_sites(gr_path, img_path,
                                                           log)
                            _stage_done(log, "reading the game's play tables",
                                        t0)
                        audio_edits, grows, mode_sound_used = _mode_sound_grow(
                            gr_path, img_path, params, desc_sites, audio_edits,
                            grows, mode_sound, log)
                    if mode_own:
                        # Item 149 with item 150: the modes' start sounds, shot
                        # sounds and music, each a forced grow of its carrier's
                        # record, beside the end sound.
                        if not desc_sites:
                            t0 = time.monotonic()
                            if progress:
                                progress(10, 100,
                                         "Reading the game's play tables...")
                            desc_sites = _descriptor_sites(gr_path, img_path,
                                                           log)
                            _stage_done(log, "reading the game's play tables",
                                        t0)
                        grow_work = grow_work or _work_dir(
                            label, base="spike2_grow_")
                        audio_edits, grows, mode_own_used = _mode_own_sounds_grow(
                            gr_path, img_path, params, desc_sites, audio_edits,
                            grows, mode_own, os.path.join(grow_work, "own_sounds"),
                            log)
                    if _user_grows:
                        # The bank's budget: the game's 2 GB, and the room on
                        # the games partition beside the full-size videos,
                        # with the modes' forced sounds (which can't be
                        # trimmed) placed first.  The keep-whole order then
                        # trims the least wanted songs rather than the build
                        # being refused or the copy failing after the encode.
                        _byidx = {p["idx"]: p for p in params}
                        _forced = {i: g for i, g in grows.items()
                                   if i not in _user_grows}
                        _room = None
                        _prio = _grow_priority_idxs(assets_dir)
                        if space_chk is not None:
                            try:
                                _want = _grown_bank_size(img_path, _byidx,
                                                         grows)
                            except Exception:  # noqa: BLE001 - trim sizes it
                                _want = None
                            # an update goes whole only when the original's
                            # room keeps a song the update's trims
                            _room = space_chk.bank_room(
                                want=_want,
                                kept_at=lambda limit: set(_grows_kept_at(
                                    _user_grows, _byidx, img_path, limit,
                                    priority=_prio, reserved=_forced)))
                        grows = dict(_grows_within_bank_limit(
                            _user_grows, _byidx, img_path, log,
                            priority=_prio, room=_room, reserved=_forced))
                        grows.update(_forced)
                    # PAD-176: every grow is settled (the modes' own sounds
                    # included), so the bank's exact length is known: the
                    # whole budget is checked HERE, before the bank is staged,
                    # derived or anything is encoded.
                    if space_chk is not None:
                        space_chk.check_grown(
                            img_path, {p["idx"]: p for p in params}, grows)
                    # The records that loop (the modes' music beds): the
                    # chain encode's loops, and part of the grown bank's key.
                    _loop_idx = {int(u["idx"]) for u in (mode_own_used or ())
                                 if u.get("music") and u.get("idx") is not None}
                    # A grown bank the last build derived, encoded and
                    # verified from these same sounds is replayed
                    # (_GrownBankCache).  Its key is taken HERE, before the
                    # stage moves the stock bank out from under its
                    # fingerprint.  Try it's fast run (sound_ok=False) keeps
                    # out of it, and so does a build whose bodies would not
                    # be the restored ones kept (the blip-free cave, or the
                    # restore skipped by hand).  BEHIND THE PREVIEW SWITCH
                    # (_family) for now: its replay is proven on the synthetic
                    # mode card only, and a copy of the app without a code
                    # must write what main writes until a real-card Write has
                    # taken the hit path and booted.
                    grown_cache = grown_key = grown_hit = None
                    if (grows and assets_dir and sound_ok is not False
                            and _family
                            and not _pathA_enabled()
                            and os.environ.get(
                                "PAD_STERN_SKIP_MASTERDIR_FIX") != "1"
                            and os.environ.get(
                                "PAD_STERN_AUDIO_CACHE") != "0"):
                        try:
                            grown_cache = _GrownBankCache(
                                assets_dir, gr_path, img_path, stock_ident)
                            grown_key = grown_cache.key_for(
                                _family, _grown_cache_sounds(
                                    assets_dir, audio_edits, grows,
                                    slot_gains, _loop_idx,
                                    list(mode_own_used or ())
                                    + ([mode_sound_used] if mode_sound_used
                                       else [])))
                        except Exception as e:
                            log("Grown-bank cache unavailable (%s); deriving "
                                "the grown bank again." % e, "info")
                            grown_cache = grown_key = None
                    if grows:
                        t0 = time.monotonic()
                        grow_work = grow_work or _work_dir(
                            label, base="spike2_grow_")
                        img_path, grow_places = _stage_grown_image(
                            gr_path, img_path, grow_work,
                            {p["idx"]: p for p in params}, grows, log)
                        for idx in sorted(grows):
                            room, want = grows[idx]
                            log("idx %d: the replacement runs %.2f s where the "
                                "original ran %.2f s; the sound bank grows to "
                                "keep it whole." % (idx, want / 44100.0,
                                                    room / 44100.0), "info")
                        # Each of the next two steps boots the emulator; a
                        # Cancel is answered between them rather than after
                        # the stage, the way the encode below answers one.
                        if cancel():
                            return None, None, None, None, None
                        if grown_cache is not None:
                            try:
                                grown_hit = grown_cache.load(grown_key)
                            except Exception as e:                # noqa: BLE001
                                log("Grown-bank cache: the kept result could "
                                    "not be read (%s); deriving the grown bank "
                                    "again." % e, "info")
                                grown_hit = None
                            if grown_hit is not None:
                                _why = _grown_cache_mismatch(grown_hit,
                                                             grow_places)
                                if _why:
                                    # Never ship a table for another bank: the
                                    # cold derive is the only honest answer.
                                    log("Grown-bank cache: the kept result is "
                                        "not this staged bank's (%s); deriving "
                                        "it again." % _why, "warning")
                                    grown_hit = None
                        if grown_hit is not None:
                            # The derive and the chain encode are skipped:
                            # the kept table is the one the finished bank
                            # derives, with every appended record's chain
                            # key.  The play tables are still re-pointed from
                            # it (they are the staged bank's bytes), and the
                            # integrity check below still boots the result.
                            params = grown_hit["params"]
                            _greads = grown_hit["reads"]
                            if progress:
                                progress(12, 100, "Reusing the last grown "
                                         "sound bank...")
                            log("Grown bank: these %d longer sound(s) are "
                                "exactly the set the last build derived, "
                                "encoded and verified, so its derived table "
                                "and restored bodies are reused and the "
                                "derive, the chain encode and the "
                                "master-directory restore are skipped; the "
                                "play tables are re-pointed from that table "
                                "and the firmware integrity check still runs "
                                "(PAD_STERN_AUDIO_CACHE=0 runs everything "
                                "again)." % len(grows), "info")
                            if progress:
                                progress(14, 100, "Re-pointing the game's "
                                         "play tables at the longer sounds...")
                            _repoint_descriptors(
                                gr_path, img_path, params, desc_sites, log,
                                templates=_mode_bed_templates(
                                    gr_path, img_path, mode_own_used, log))
                            if cancel():
                                return None, None, None, None, None
                            _save_grown_consumed(gr_path, img_path, _greads,
                                                 log)
                            _stage_done(log, "staging a sound bank with %d "
                                        "longer sound(s) from the kept derive"
                                        % len(grows), t0)
                        else:
                            if progress:
                                progress(12, 100,
                                         "Deriving the grown sound bank...")
                            params, _greads = _derive_grown(
                                gr_path, img_path, params, log, progress)
                            if cancel():
                                return None, None, None, None, None
                            if progress:
                                progress(14, 100, "Re-pointing the game's "
                                         "play tables at the longer sounds...")
                            _repoint_descriptors(gr_path, img_path, params,
                                                 desc_sites, log)
                            if cancel():
                                return None, None, None, None, None
                            # The derive above walked the firmware's whole
                            # decode chain over the STAGED bank, which is
                            # exactly the pass _restore_masterdir_consumed
                            # re-runs cold when it has no consumed map for
                            # the bank it is handed.  Keeping the map (it
                            # used to be discarded here) is what lets a mixed
                            # build - an own sound beside a replaced stock
                            # sound - take that function's cached path
                            # instead of a second multi-minute boot.  Saved
                            # after the re-point, because the fingerprint
                            # covers the head of the bank and that is the
                            # bank the restore will be looking at.
                            _save_grown_consumed(gr_path, img_path, _greads,
                                                 log)
                            _stage_done(log, "staging a sound bank with %d "
                                        "longer sound(s)" % len(grows), t0)
                    t0 = time.monotonic()
                    # Item 150 follow-up: the APPENDED records (grown sounds, the
                    # modes' own sounds) are encoded along the firmware's chain,
                    # so none of their windows is put back to the scaffold (the
                    # blip at 1/4 and 3/4 of each); the replaced stock sounds go
                    # through the ordinary encode below.  The PREVIEW SWITCH
                    # OFF keeps the encode a build without the family does:
                    # every sound through the ordinary encode, and only the
                    # LAST appended body left unrestored (_family below).
                    _grown_idx = ({p["idx"] for p in params if p.get("grown")}
                                  if _family else set())
                    _chain_edits = {i: w for i, w in audio_edits.items()
                                    if i in _grown_idx}
                    if grown_hit is not None:
                        # The kept bodies are the whole verified set, the
                        # replaced stock sounds' included (every one of them
                        # is in the key), already restored.
                        audio_patches = dict(grown_hit["patches"])
                        _chain_edits = {}
                    else:
                        audio_patches, _askip = _encode_cat0_sounds(
                            gr_path, img_path, params,
                            {i: w for i, w in audio_edits.items()
                             if i not in _chain_edits}, np, log,
                            progress, cancel, assets_dir=assets_dir,
                            gains=slot_gains, cache_img_ident=stock_ident)
                    if audio_patches is None:
                        return None, None, None, None, None
                    if _chain_edits:
                        _cp, params = _chain_encode_appended(
                            gr_path, img_path, params, _chain_edits, np, log,
                            loops=_loop_idx, gains=slot_gains,
                            level_refs=_mode_music_level_refs(
                                gr_path, img_path, params, desc_sites,
                                _loop_idx, log),
                            progress=progress, cancel=cancel)
                        audio_patches.update(_cp)
                        # an appended record's container key comes out of the chain,
                        # so the play tables are re-pointed again at the keys the
                        # finished bank registers (descriptors are no record's window)
                        _repoint_descriptors(
                            gr_path, img_path, params, desc_sites, log,
                            templates=_mode_bed_templates(gr_path, img_path,
                                                          mode_own_used, log))
                        # The re-point may move a key inside the region the
                        # fingerprint covers: file the map under the bank as
                        # it now stands too, so the restore below still hits.
                        _save_grown_consumed(gr_path, img_path, _greads, log)
                    _stage_done(log, "re-encoding %d replaced sound(s)"
                                % len(audio_edits), t0)
                    # Keep the firmware's master-directory forward-chain intact.
                    # Blip-free (default): patch game_real so the boot-derive reads
                    # STOCK window bytes for the replaced sounds -- fully-stock
                    # codec params on a card whose bodies are entirely our audio,
                    # so no ~6 ms original "blip".  Fallback (kill switch, or a
                    # firmware/set the cave can't handle): revert the bytes the
                    # decode consumes back to stock (the blip), then verify every
                    # sound still derives valid params.  Either way the safety net
                    # is a boot of the FINAL firmware+image that asserts stock codec
                    # params for every sound before shipping.
                    pathA_applied = False
                    pathA_why = None
                    if audio_patches and _pathA_enabled():
                        try:
                            _pathA_preflight(dest_is_device)
                            # The cave grows game_real, so the whole firmware is
                            # copied onto the card in one piece -- the validator
                            # bypass has to be baked into that same image or the
                            # copy would undo it.
                            from . import valpatch as _vp
                            with open(_lp(gr_path), "rb") as _f:
                                _fwb = _f.read()
                            _vbypass, _vmode = _vp.bypass_overlay(_fwb)
                            if grow_places is not None:
                                # A grown bank has records the sound engine's
                                # own count has no expected word for; keep
                                # its failed count at zero (see valpatch).
                                _vbypass.update(
                                    _vp.sound_count_overlay(_fwb, log))
                            del _fwb
                            grow_work = grow_work or _work_dir(
                                label, base="spike2_grow_")
                            # Every appended body was encoded along the chain
                            # (_chain_encode_appended), so its windows already
                            # hold what the derive must read: none needs a
                            # redirect, which keeps the cave's limited address
                            # space for the replaced stock sounds.  With the
                            # preview switch off nothing was chain-encoded, so
                            # only the LAST appended body (nothing after it
                            # reads it) is left out, as before the family.
                            _cave_patches = {
                                o: b for o, b in audio_patches.items()
                                if o not in _appended_body_offsets(
                                    audio_patches, grow_places,
                                    last_only=not _family)}
                            patched_gr, _fw_size = _build_derive_redirect_cave(
                                gr_path, img_path, _cave_patches, np, log,
                                grow_work, progress, extra_fw_writes=_vbypass)
                            # Safety net: boot the PATCHED firmware on the patched
                            # image (our whole bodies) and confirm every sound
                            # still derives stock codec params, else abort.
                            if progress:
                                progress(77, 100,
                                         "Verifying blip-free firmware patch...")
                            _assert_param_integrity(patched_gr, img_path,
                                                    audio_patches, params, np,
                                                    log, work, progress)
                            pathA_applied = True
                            # The bypass rode along inside the rebuilt firmware,
                            # so this build's validator status is that overlay's.
                            valpatch_mode = _vmode
                            _vp.log_status(log, _vmode)
                        except Exception as e:
                            # Any failure (unsupported firmware, no free address
                            # space, a host that can't grow ext4 files, or a
                            # failed integrity assert) degrades to the standard
                            # build -- a working card with the brief original
                            # scrap -- never a hard build failure.  The fallback
                            # path re-asserts integrity.
                            patched_gr = None
                            pathA_why = str(e)
                            log("Blip-free callouts not applied (%s); building the "
                                "standard way instead (the brief original-callout "
                                "scrap remains)." % e, "warning")
                    elif audio_patches:
                        pathA_why = _BLIP_FREE_OFF_REASON
                    # The restore, the integrity derive and the final decode
                    # below run over the WHOLE replaced set, changed or not,
                    # and on a big mod they are the build's slowest stretch.
                    # Their result depends only on the card and the exact
                    # encoded set going in, so a set the last build already
                    # restored and verified is replayed (_FinalAudioCache).
                    final_cache = final_key = replayed = None
                    if (audio_patches and not pathA_applied
                            and os.environ.get(
                                "PAD_STERN_SKIP_MASTERDIR_FIX") != "1"):
                        if (assets_dir and grow_places is None
                                and os.environ.get(
                                    "PAD_STERN_AUDIO_CACHE") != "0"):
                            try:
                                final_cache = _FinalAudioCache(
                                    assets_dir, gr_path, stock_ident)
                                final_key = final_cache.key_for(audio_patches)
                                replayed = final_cache.load(final_key)
                            except Exception as e:
                                log("Audio verification cache unavailable "
                                    "(%s); checking everything again." % e,
                                    "info")
                                final_cache = final_key = replayed = None
                        if replayed is not None:
                            audio_patches = replayed
                            log("Audio checks: these %d re-encoded sound(s) "
                                "are exactly the set the last build restored "
                                "and verified, so that result is reused and "
                                "the master-directory restore, the firmware "
                                "integrity check and the final decode are "
                                "skipped (PAD_STERN_AUDIO_CACHE=0 runs them "
                                "again)." % len(replayed), "info")
                        elif grown_hit is not None:
                            # The kept bodies were restored by the build that
                            # kept them; the integrity check is the one stage
                            # a hit never skips, because it is what proves
                            # the bank on the card boots with every sound's
                            # codec parameters intact.
                            t0 = time.monotonic()
                            if cancel():
                                return None, None, None, None, None
                            _assert_param_integrity(gr_path, img_path,
                                                    audio_patches, params, np,
                                                    log, work, progress)
                            _stage_done(log, "the firmware integrity check "
                                        "of the reused grown bank", t0)
                        else:
                            t0 = time.monotonic()
                            # The two slowest emulator passes of a build come
                            # next; a Cancel pressed while the encode was
                            # finishing is honoured HERE, not minutes later.
                            if cancel():
                                return None, None, None, None, None
                            audio_patches = _restore_masterdir_consumed(
                                gr_path, img_path, audio_patches, log,
                                progress, cancel,
                                skip_offsets=_appended_body_offsets(
                                    audio_patches, grow_places,
                                    last_only=not _family))
                            if audio_patches is None or cancel():
                                return None, None, None, None, None
                            _assert_param_integrity(gr_path, img_path,
                                                    audio_patches, params, np,
                                                    log, work, progress)
                            _stage_done(log, "the master-directory restore "
                                        "and firmware integrity check", t0)
                            if final_cache is not None and not cancel():
                                final_cache.store(final_key, audio_patches)
                            # A grown bank that got this far derived,
                            # encoded, restored and verified cleanly: keep
                            # the lot for the next build of the same sounds.
                            if grown_cache is not None and not cancel():
                                grown_cache.store(grown_key, params,
                                                  grow_places, audio_patches,
                                                  _greads)
                    if audio_patches:
                        why = pathA_why or "see the build log"
                        if os.environ.get(
                                "PAD_STERN_SKIP_MASTERDIR_FIX") == "1":
                            why += ("; master-directory restore skipped "
                                    "(experimental)")
                        audio_mode = (("blip-free", "") if pathA_applied
                                      else ("standard", why))
                        _audit_audio_patches(params, audio_patches, log)
                        # Honest end-of-pipeline check: decode the FINAL card
                        # bytes (post master-directory restore) and report /
                        # preview what each sound really plays.  Skippable for
                        # a huge re-encode where the extra decodes aren't worth
                        # it; on by default because it's the only check that
                        # sees the restore's effect (the silent-replacement
                        # scrap).
                        if (replayed is None and os.environ.get(
                                "PAD_STERN_SKIP_FINAL_VERIFY") != "1"):
                            t0 = time.monotonic()
                            try:
                                _verify_final_patches(
                                    gr_path, img_path, audio_patches, params,
                                    np, log, cancel, no_restore=pathA_applied,
                                    no_scrap_offsets=_appended_body_offsets(
                                        audio_patches, grow_places,
                                        last_only=not _family))
                            except Exception as e:
                                log("Final-bytes check skipped (%s)." % e,
                                    "info")
                            _stage_done(log, "the final decode check of every "
                                        "replaced sound "
                                        "(PAD_STERN_SKIP_FINAL_VERIFY=1 skips "
                                        "it)", t0)

                # Per-song music banks (image-scNN.bin) — re-encode each edited
                # song back into its bank (own fresh CatEmu per bank).
                if music_edits:
                    # a build with no cat-0 sounds is measured before this
                    # encode (in place, but it takes minutes)
                    if space_chk is not None:
                        space_chk.check()
                    if progress:
                        progress(80, 100, "Re-encoding music bank(s)...")
                    t0 = time.monotonic()
                    music_patches = _compute_music_patches(
                        reader, gr_path, img_path, music_edits, work, log,
                        progress, cancel, np, gains=music_gains)
                    if cancel():
                        return None, None, None, None, None
                    _stage_done(log, "re-encoding %d music-bank song(s)"
                                % len(music_edits), t0)

        # A build with no sound to encode is measured here, before its videos
        # and text are prepared (a no-op when the audio step measured it).
        if space_chk is not None:
            space_chk.check()

        # A video / image / text-only write (or one whose audio turned out
        # unsupported) still needs a reader to resolve the loose-file inodes.
        if reader is None:
            # The firmware inode is kept: a longer program-text edit grows
            # the game ELF on a text-only write too.
            reader, fw_node, _img_node = _locate(disk_f, parts)

        # Radium edits patch the scene.radium inode in place; collect per-inode
        # file-relative overlays alongside the flat disk writes so the .sidx
        # refresh below can recompute each patched radium's digest.
        radium_overlays = {}   # i_block -> (node, {file_off: bytes})

        # Edited LCD display text -> already-flat (disk_offset, bytes) writes.
        text_writes = []
        n_text = 0
        # Game-program text edits patch the game ELF in place; the validator
        # bypass below is the last writer of that file's .sidx record, so it
        # needs them to compute a digest of the firmware that actually ships.
        fw_text_overlay = {}
        # Longer text than the original: the grown game ELF and the scenes to
        # re-serialise (see _radium_text_writes).  Either is staged whole in
        # the grow scratch dir and copied onto the card by the grow job, like
        # the cave's firmware.
        grown_text = None
        if text_edits:
            if progress:
                progress(95, 100, "Preparing display text...")
            grow_work = grow_work or _work_dir(label, base="spike2_grow_")
            (text_writes, n_text, _t_ov, fw_text_overlay,
             grown_text) = _radium_text_writes(
                reader, assets_dir, log, cancel, patched_fw=patched_gr,
                grow_dir=grow_work, dest_is_device=dest_is_device)
            _merge_radium_overlays(radium_overlays, _t_ov)
            if cancel():
                return None, None, None, None, None
            gfw = grown_text.get("fw")
            if gfw is not None:
                patched_gr = gfw["path"]
                if fw_node is None:
                    fw_node = gfw["node"]
                if gfw.get("valpatch_mode") is not None:
                    valpatch_mode = gfw["valpatch_mode"]

        # The game's own modes (item 145): staged word edits in the game ELF,
        # after the display text so a grown text ELF (or the cave's) takes
        # them INTO its staged file.  In place otherwise: their overlay joins
        # fw_text_overlay (the validator bypass refreshes the ELF's .sidx
        # record last, over all of them) and the radium overlays (a title
        # without the validator still gets its record refreshed).
        stock_mode_writes, n_stock_modes, n_stock_mode_numbers = [], 0, 0
        # A managed project with nothing staged still runs this: a card built
        # from one that holds our words gets the stock words back.
        if stock_mode_edits or _stock_mode_managed(assets_dir):
            from . import stock_modes as _stock_modes
            _sm_stats = {}
            stock_mode_writes, _sm_ov, n_stock_modes = \
                _stock_modes.compute_writes(reader, fw_node, assets_dir, log,
                                            patched_fw=patched_gr,
                                            stats=_sm_stats)
            if _sm_ov and fw_node is not None:
                fw_text_overlay = dict(fw_text_overlay)
                fw_text_overlay.update(_sm_ov)
                _merge_radium_overlays(
                    radium_overlays,
                    {bytes(fw_node["i_block"]): (fw_node, dict(_sm_ov))})
            # The staged timers (operator-setting defaults) are IN that
            # overlay now, so this count is what lands on every path: the
            # image Write, Direct SD and the emulator's override set.  (They
            # used to be counted here and written only by the app's
            # post-build settings step, which only an image Write runs.)
            if n_stock_modes:
                stock_mode_edits = max(stock_mode_edits, n_stock_modes)
            elif _sm_stats.get("held"):
                # every staged number is on this card already (a second
                # Direct SD Write): nothing to change, and nothing refused
                log("The game's own modes: this card already holds the %d "
                    "staged number(s); none needed writing."
                    % _sm_stats["held"], "info")
            else:
                stock_mode_edits = 0
            n_stock_mode_numbers = n_stock_modes

        # Recoloured display text -> the same kind of in-place radium patch,
        # on different bytes of the same scenes, so the two compose.
        color_writes = []
        n_color = 0
        if color_edits:
            if progress:
                progress(95, 100, "Preparing text colours...")
            color_writes, n_color, _c_ov = _radium_color_writes(
                reader, assets_dir, log, cancel)
            _merge_radium_overlays(radium_overlays, _c_ov)
            if cancel():
                return None, None, None, None, None

        # Re-laid-out display text (moved / re-aligned / resized) -> the third
        # in-place radium patch, on the keyframe rect + align word and the
        # scene's glyph metrics; disjoint from the letters and the colours,
        # so all three compose on one scene.
        layout_writes = []
        n_layout = 0
        if layout_edits:
            if progress:
                progress(95, 100, "Preparing text layout...")
            layout_writes, n_layout, _l_ov = _radium_layout_writes(
                reader, assets_dir, log, cancel)
            _merge_radium_overlays(radium_overlays, _l_ov)
            if cancel():
                return None, None, None, None, None

        # Edited radium-embedded DXT5 images -> also already-flat (disk_offset,
        # bytes) writes (patched in place inside the scene.radium inode).
        radimg_writes = []
        n_radimg = 0
        # Images kept at a size of their own (PAD-154): {card path: (node,
        # {data_off: (w, h, block bytes)})}, re-serialised below with the
        # scenes whose text grew.
        grown_images = {}
        if radimg_edits:
            if progress:
                progress(96, 100, "Preparing radium images...")
            grow_work = grow_work or _work_dir(label, base="spike2_grow_")
            radimg_writes, n_radimg, _i_ov = _radium_image_writes(
                reader, assets_dir, baseline, log, cancel,
                grow_dir=grow_work, dest_is_device=dest_is_device,
                grown=grown_images)
            _merge_radium_overlays(radium_overlays, _i_ov)
            if cancel():
                return None, None, None, None, None

        # Scenes whose text outgrew its slot, or whose image changed size,
        # are re-serialised now, AFTER the colour / layout / image writers,
        # so their in-place edits (all at stock offsets) fold into the grown
        # bytes; the grown scene is then written whole and its in-place
        # writes are dropped.
        radium_grow_jobs, grown_files = [], {}
        grown_radium = {cp: (node, texts, {}) for cp, (node, texts)
                        in ((grown_text or {}).get("radium") or {}).items()}
        for cp, (node, imgs) in grown_images.items():
            grown_radium.setdefault(cp, (node, {}, {}))[2].update(imgs)
        if grown_radium:
            radium_grow_jobs, grown_files = _stage_grown_radiums(
                reader, grown_radium, radium_overlays, grow_work, log)
            for _gnode, *_gedits in grown_radium.values():
                if bytes(_gnode["i_block"]) not in grown_files:
                    continue
                text_writes = _drop_writes_in(text_writes, reader, _gnode)
                color_writes = _drop_writes_in(color_writes, reader, _gnode)
                layout_writes = _drop_writes_in(layout_writes, reader, _gnode)
                radimg_writes = _drop_writes_in(radimg_writes, reader, _gnode)
        # A grown sound bank rides the same mechanism: a whole-file copy with
        # its manifest record's size rewritten alongside its digests.
        image_grow_job = None
        if grow_places is not None and img_node is not None:
            img_rel = _card_rel_path(reader, img_node)
            if img_rel:
                image_grow_job = (img_rel, img_path)
                grown_files[bytes(img_node["i_block"])] = img_path
            else:
                raise RuntimeError(
                    "Couldn't resolve the sound bank's path on the card, so "
                    "the grown bank could not be written; aborting rather "
                    "than shipping a card whose sounds don't match its "
                    "manifest.")

        # Item 149: the modes' screens and clips, built from this card's STOCK
        # HUD and bank scenes (never on top of an earlier build), plus the
        # files the system partition gets.  The rewritten scenes and the new
        # clips are whole-file copies; the manifest is composed to match once
        # every other edit's record refresh is known (below).
        mode_plan = mode_payload = None
        if mode_list or code_list:
            t0 = time.monotonic()
            if progress:
                progress(95, 100, "Building the project's modes...")
            grow_work = grow_work or _work_dir(label, base="spike2_grow_")
            try:
                if mode_list:
                    _mprof = _MW.MP.profile(mode_list[0][1].title)
                else:
                    from . import code_modes as _CM
                    _mprof = _CM.profile_for(assets_dir, code_list)
                _mnodes = {"": None}
                for _rel in _MW.scene_rels(_mprof):
                    if not _rel:
                        continue        # a part this title cannot do (item 148)
                    _mnodes[_rel] = _MW.lookup(reader, _rel)
                    if _mnodes[_rel] is None:
                        raise _MW.ModeWriteError(
                            "this card has no %s, so it is not the game the "
                            "modes were made for (%s)" % (_rel, _mprof.label))
                if fw_node is None:
                    raise _MW.ModeWriteError("the card's game program was not "
                                             "found")
                _hud_rel, _bank_rel = _MW.scene_rels(_mprof)
                mode_plan = _MW.plan(
                    assets_dir,
                    reader.read_file_bytes(_mnodes[_hud_rel]) if _hud_rel else b"",
                    reader.read_file_bytes(_mnodes[_bank_rel]) if _bank_rel else b"",
                    bytes(reader.read_file_bytes(fw_node)),
                    os.path.join(grow_work, "modes"), log=log,
                    end_sound=mode_sound_used, own_sounds=mode_own_used)
                _ipath = {bytes(n["i_block"]): p.lstrip("/")
                          for p, _i, n in reader.iter_regular_files(
                              min_size=1, max_depth=20)}
                _touched = [_ipath.get(ib) for ib in radium_overlays]
                _touched += [r for r, _s in radium_grow_jobs]
                _bad = _MW.conflicts(mode_plan, [t for t in _touched if t])
                if _bad:
                    raise _MW.ModeWriteError("; ".join(_bad))
                for _rel, _src in mode_plan.replaced:
                    _node = _mnodes.get(_rel) or _MW.lookup(reader, _rel)
                    if _node is None:
                        raise _MW.ModeWriteError("%s is not on the card" % _rel)
                    grown_files[bytes(_node["i_block"])] = _src
                mode_payload = _MW.p2_payload(
                    mode_plan, os.path.join(grow_work, "modes", "p2"))
            except _MW.ModeWriteError as e:
                raise RuntimeError("Modes: %s. Nothing was written." % e) \
                    from None
            for _line in mode_plan.lines:
                log("Modes: %s." % _line, "info")
            _stage_done(log, "building %d mode(s)" % (len(mode_list) + len(code_list)), t0)

        video_patches = []     # (inode, payload bytes == inode size)
        video_grow_jobs = []   # (card_rel, source_file) — grown via ext4 driver
        if video_edits:
            if progress:
                progress(86, 100, "Preparing video...")
            # The user's assigned replacements (extract rel -> source file);
            # oversized ones grow their slot instead of being crushed to fit.
            from ...core import staged_changes as _sc
            _saved = _sc.load(assets_dir)
            t0 = time.monotonic()
            video_patches, _vskip, video_grow_jobs = _prepare_video_patches(
                reader, video_edits, work, log, cancel,
                originals=_saved.get("video") or {},
                dest_is_device=dest_is_device,
                verdicts=(space_chk.verdicts if space_chk is not None
                          else None),
                grow_check=(space_chk.grow_check if space_chk is not None
                            else None))
            if cancel():
                return None, None, None, None, None
            _stage_done(log, "preparing %d replaced video(s)"
                        % len(video_edits), t0)

        image_patches = []     # (inode, payload bytes == inode size)
        if image_edits:
            if progress:
                progress(92, 100, "Preparing images...")
            t0 = time.monotonic()
            image_patches, _iskip = _prepare_image_patches(
                reader, image_edits, work, log, cancel)
            if cancel():
                return None, None, None, None, None
            _stage_done(log, "preparing %d replaced image(s)"
                        % len(image_edits), t0)

        boot_writes, boot_grow, n_boot = [], None, 0
        if boot_edits:
            if progress:
                progress(93, 100, "Preparing the boot screen...")
            boot_writes, boot_grow, n_boot = _prepare_boot_screen_patches(
                disk_f, parts, reader.base, boot_edits, work, log, cancel,
                dest_is_device=dest_is_device)
            if cancel():
                return None, None, None, None, None

        texture_patches = []   # (inode, payload bytes == inode size)
        if texture_edits:
            if progress:
                progress(94, 100, "Preparing scene textures...")
            texture_patches, _tskip = _prepare_texture_patches(
                reader, texture_edits, log, cancel)
            if cancel():
                return None, None, None, None, None

        if (not audio_patches and not music_patches and not video_patches
                and not video_grow_jobs and not image_patches
                and not texture_patches and not radimg_writes
                and not text_writes and not color_writes
                and not layout_writes and not radium_grow_jobs
                and not boot_writes and boot_grow is None
                and patched_gr is None and mode_plan is None
                and not stock_mode_edits):
            raise RuntimeError(
                "Nothing could be written: no sound re-encoded, no replaced "
                "video or image could be fit to its original slot, and no "
                "display-text edit fit its original string (the card image was "
                "not modified).")

        # Flatten every patch to absolute (disk_offset, bytes) writes via the
        # ext4 file->disk map.  The offsets are relative to the start of the
        # card image / device, so the same list applies whether we patch an
        # image copy (write_image) or the card itself (write_device).
        # Display-text writes are already (disk_offset, bytes) (the radium-text
        # helper resolved them through disk_ranges itself).
        writes = (list(text_writes) + list(color_writes) + list(layout_writes)
                  + list(radimg_writes))
        writes += stock_mode_writes          # the game's own modes (item 145)
        # A grown sound bank is longer than the file on the card, so it can't be
        # patched in place: every re-encoded body is composed into the staged
        # file and the whole thing is copied on by the ext4 driver.  Emitting
        # the in-place writes as well would be wasted work on an image build
        # and actively wrong on an override set, which patches the file and
        # then copies over it.
        audio_inplace = audio_patches
        if grow_places is not None:
            with open(_lp(img_path), "r+b") as f:
                for body_off, body in audio_patches.items():
                    f.seek(body_off)
                    f.write(body)
            log("Sound bank: %d re-encoded sound(s) composed into the grown "
                "file (%.1f MB), which is written whole."
                % (len(audio_patches),
                   os.path.getsize(_lp(img_path)) / 1e6), "info")
            audio_inplace = {}
        for body_off, body in audio_inplace.items():
            for disk, n in reader.disk_ranges(img_node, body_off, len(body)):
                writes.append((disk, body[:n]))
                body = body[n:]
        # Music songs patch their OWN bank inode (image-scNN.bin), not image.bin.
        for sc_node, body_off, body in music_patches:
            for disk, n in reader.disk_ranges(sc_node, body_off, len(body)):
                writes.append((disk, body[:n]))
                body = body[n:]
        for node, payload in video_patches + image_patches + texture_patches:
            off = 0
            for disk, n in reader.disk_ranges(node, 0, len(payload)):
                writes.append((disk, payload[off:off + n]))
                off += n
        # The boot screen's writes are flat already, and on the OS partition,
        # so the games tree's .sidx refresh below has no record of them.
        writes += boot_writes
        # Regenerate the .sidx manifest records for the changed files so the
        # card passes Stern's SD validation (recompute HMAC-SHA1 + MD5 with the
        # manifest's global validation key).  Best-effort: a missing /
        # unrecognised manifest never fails the Write — it just leaves the card
        # needing re-validation, exactly as before this step existed.
        full_repl = list(video_patches) + list(image_patches) + list(texture_patches)
        t0 = time.monotonic()
        try:
            writes += _compute_sidx_writes(
                reader, disk_f, img_node, audio_inplace, music_patches,
                full_repl, radium_overlays, log,
                fw_node=fw_node, fw_patched_path=patched_gr,
                grown_files=grown_files)
        except Exception as e:
            log("SD-validation manifest update failed (%s); the card may report "
                "a validation error until re-validated." % e, "warning")
        _stage_done(log, "refreshing the SD-validation manifest", t0)

        # Auto-disable Stern's game self/asset validator (validation_exec) so the
        # modded card boots without the "#N UPDATE SD CARD" tamper errors.  The
        # game validates itself, so a single bx-lr at that routine's entry stops
        # the asset checks, the self-check and the tamper flags (see valpatch).
        # Best-effort: a title without the validator, or any failure, is a no-op.
        # Skipped when the blip-free cave rebuilt the firmware: the bypass is
        # already baked into that image (and its .sidx record refreshed above),
        # and an in-place write here would be undone by the whole-file copy.
        if patched_gr is None:
            try:
                from . import valpatch
                if grow_places is not None and fw_node is not None:
                    # A grown bank has records the sound engine's own count
                    # has no expected word for; keep its failed count at
                    # zero, in place, and let the bypass below fold the edit
                    # into the firmware's .sidx digest (see valpatch).
                    _sw, _sov = valpatch.sound_count_writes(reader, fw_node,
                                                            log)
                    writes += _sw
                    fw_text_overlay = dict(fw_text_overlay)
                    fw_text_overlay.update(_sov)
                _vwrites, valpatch_mode = valpatch.compute_writes(
                    reader, log, fw_overlay=fw_text_overlay)
                writes += _vwrites
            except Exception as e:
                log("Validation bypass skipped (%s)." % e, "warning")

        # Item 149: a mode adds files, so the manifest gains records and grows:
        # it can no longer be patched in place.  Every in-place record refresh
        # above (the grown bank, the firmware's bypass, the rewritten scenes)
        # is folded into one manifest composed here, dropped from the in-place
        # writes, and the whole manifest is copied on after the files it names.
        manifest_job = None
        mode_info = None
        if mode_plan is not None:
            from . import sidx as _sidx
            try:
                _man_path, _man_node = _sidx.find_sidx(reader)
                if _man_node is None:
                    raise _MW.ModeWriteError(
                        "the card has no /spk/index/*.sidx manifest, so the "
                        "modes' new files could not be indexed")
                _folded, writes = _MW.fold_writes(
                    writes, reader.disk_ranges(_man_node, 0,
                                               _man_node["size"]))
                _new_man = _MW.compose_manifest(
                    bytes(reader.read_file_bytes(_man_node)), inplace=_folded,
                    refreshed=mode_plan.replaced, new=mode_plan.new)
                _man_src = os.path.join(grow_work, "modes",
                                        os.path.basename(_man_path))
                with open(_lp(_man_src), "wb") as f:
                    f.write(_new_man)
                manifest_job = (_man_path.lstrip("/"), _man_src)
                _p3_epoch = _MW.epoch_at(disk_f, reader.base)
                _p2_off = _MW.p2_offset(disk_f)
                _p2_epoch = _MW.epoch_at(disk_f, _p2_off)
            except _MW.ModeWriteError as e:
                raise RuntimeError("Modes: %s. Nothing was written." % e) \
                    from None
            log("Modes: the SD-validation manifest gains %d record(s) (%s) "
                "and %d in-place record refresh(es) are folded into it; it is "
                "copied onto the card whole."
                % (len(mode_plan.new), ", ".join(r for r, _s in mode_plan.new)
                   or "none", len(_folded)), "info")
            mode_info = {
                "names": ([s.name for _g, s in mode_list]
                          + [c.name for _g, c in code_list]),
                "lines": list(mode_plan.lines),
                "added": [r for r, _s in mode_plan.new],
                "rewritten": ([r for r, _s in mode_plan.replaced]
                              + [manifest_job[0]]),
                "port": os.path.basename(mode_plan.port),
                "p2": ([os.path.basename(mode_payload["so"])]
                       + [os.path.basename(c) for c in mode_payload["cfgs"]]
                       + [os.path.basename(a) for a in mode_payload.get("assets") or ()]
                       + [os.path.basename(e) for e in mode_payload.get("extras") or ()]
                       + [os.path.basename(mode_payload["port"])]),
                "code_object": bool(getattr(mode_plan, "object", "")),
                "payload": mode_payload,
                "end_sound": ({k: mode_sound_used[k]
                               for k in ("name", "request", "idx")}
                              if mode_sound_used else None),
                "own_sounds": [dict({k: u.get(k) for k in ("slug", "name", "key",
                                                           "request", "idx", "ms")},
                                    **({"sid": u["sid"]} if u.get("sid") else {}))
                               for u in mode_own_used],
                "p2_offset": _p2_off,
                "p2_epoch": _p2_epoch,
            }

        # Grown videos aren't flat disk writes — they're copied in by the ext4
        # driver after the in-place writes land.  Re-serialised scenes and the
        # rebuilt firmware ride the same mechanism, because they too are
        # longer than the file they replace.  The firmware goes LAST: jobs
        # fail from the end, so anything short of the full count means the
        # firmware didn't land (write_image reads it that way).
        grow_jobs = list(video_grow_jobs) + list(radium_grow_jobs)
        if image_grow_job is not None:
            grow_jobs.append(image_grow_job)
        if mode_plan is not None:
            # the files before the manifest that names them; the firmware, if
            # any, still goes last
            grow_jobs += mode_plan.jobs
            grow_jobs.append(manifest_job)
        if patched_gr is not None and fw_node is not None:
            from .valpatch import _game_manifest_path
            fw_rel = _game_manifest_path(reader, fw_node)
            if fw_rel:
                grow_jobs.append((fw_rel, patched_gr))
            else:
                log("Couldn't resolve the game firmware's path on the card; the "
                    "blip-free firmware won't be written.", "error")
        # ``cleanup`` is the scratch dir holding the rebuilt firmware; it has to
        # survive until the caller has copied it onto the card, so the caller
        # removes it (see the note where grow_work is created).
        uses_work = (bool(radium_grow_jobs) or patched_gr is not None
                     or image_grow_job is not None or mode_plan is not None)
        grow_plan = ({"offset": reader.base, "jobs": grow_jobs,
                      "n_video": len(video_grow_jobs),
                      # Where the grown sound bank sits in the queue, so a
                      # partial run can say whether the sounds landed (jobs
                      # fail from the end).  None when nothing was grown.
                      "audio_job": (grow_jobs.index(image_grow_job)
                                    if image_grow_job is not None else None),
                      "cleanup": grow_work if uses_work else None,
                      # A boot screen that outgrew its file: another
                      # partition, so another mount (_grow_boot_screen).
                      "boot": boot_grow,
                      # Item 149: what the modes add (the log, the build
                      # record, the p2 install, Try it's payload), and the
                      # fixed clock a mode build delivers with so a second
                      # Write is byte-identical (ext4_grow.grow_files_pinned).
                      "modes": mode_info,
                      "epoch": (_p3_epoch if mode_plan is not None else None)}
                     if grow_jobs or boot_grow else None)
        # Only a plan that actually carries a staged file (the firmware, a
        # re-serialised scene) owns that dir; a video-only plan doesn't, and
        # neither does a build whose cave was dropped after being written.
        grow_work_handed_off = bool(grow_plan and grow_work and uses_work)

        # Scene textures + radium-embedded images fold into the image count
        # (they ARE images) so the (audio, video, image, text) summary tuple
        # stays the same shape.
        # Recoloured and re-laid-out lines fold into the text count: they ARE
        # display-text edits, just of the colour / position / size rather
        # than the letters.
        counts = (len(audio_patches) + len(music_patches),
                  len(video_patches) + len(video_grow_jobs),
                  len(image_patches) + len(texture_patches) + n_radimg
                  + n_boot,
                  n_text + n_color + n_layout)
        # the game's own modes ride along without changing the tuple's shape
        counts = _with_stock_modes(counts, n_stock_mode_numbers)
        return writes, counts, grow_plan, audio_mode, valpatch_mode
    finally:
        _rmtree(work)
        # Cancelled, raised, or the cave never made it into a grow job: nobody
        # downstream is going to use (or clean up) the firmware scratch dir.
        if grow_work and not grow_work_handed_off:
            _rmtree(grow_work)


def _apply_writes(out, writes):
    """Apply ``[(disk_offset, bytes), ...]`` to an open seekable destination
    (an image copy opened ``r+b``, or a writable :class:`.rawdevice.RawDeviceFile`
    over the card)."""
    for disk, b in writes:
        out.seek(disk)
        out.write(b)


# --------------------------------------------------------------------------
# The build record, and updating the last build in place
# --------------------------------------------------------------------------
#: Beside every card image a Build writes: what that build put on the card,
#: so the next Build of the same project onto the same file can write only
#: what changed since instead of starting over from the stock card
#: (:func:`write_image`).  A build with no usable record beside it is built
#: whole, as every build was before the record existed.
BUILD_MANIFEST_SUFFIX = ".pad-build.json"
#: Bumped when the record's shape changes; an older record is not trusted.
BUILD_MANIFEST_VERSION = 1


class _CannotUpdate(Exception):
    """The build at the output can't be updated in place safely; build whole.
    The message is the reason, in a form the log can print."""


def build_manifest_path(output_path):
    """Where :func:`write_image` keeps its record of the build at
    *output_path*."""
    return str(output_path) + BUILD_MANIFEST_SUFFIX


def read_build_manifest(output_path):
    """The record of the build at *output_path*, or ``{}`` — a missing,
    half-written or unreadable record means "there is no build here to
    update", which every caller treats as "build whole", never as an error."""
    import json
    try:
        with open(_lp(build_manifest_path(output_path)),
                  encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_build_manifest(output_path, data):
    import json
    path = build_manifest_path(output_path)
    tmp = path + ".tmp"
    with open(_lp(tmp), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(_lp(tmp), _lp(path))


def _mark_building(output_path):
    """Lay the stub record down before the first byte is written, so a build
    that dies half way leaves a record that refuses to be updated over.
    ``False`` when it couldn't be written — any old record is removed too, so
    nothing stale can vouch for the file about to be modified."""
    try:
        _write_build_manifest(output_path,
                              {"version": BUILD_MANIFEST_VERSION,
                               "building": True})
        return True
    except OSError:
        _safe_remove(build_manifest_path(output_path))
        return False


def _discard_output(output_path):
    """Remove a half-prepared output and its record together."""
    _safe_remove(output_path)
    _safe_remove(build_manifest_path(output_path))


def _file_stamp(path):
    """A file's identity for the record: path, size and mtime.  Size+mtime is
    the identity every other cache in this app keys on (the emulator's card
    cache, the override set's card stamp)."""
    st = os.stat(_lp(path))
    return {"path": os.path.abspath(str(path)), "size": st.st_size,
            "mtime_ns": st.st_mtime_ns}


def _stamp_matches(stamp, path):
    try:
        cur = _file_stamp(path)
    except OSError:
        return False
    stamp = stamp or {}
    return (stamp.get("size") == cur["size"]
            and int(stamp.get("mtime_ns") or -1) == cur["mtime_ns"])


def build_update_reason(prev, original_path, output_path, assets_dir):
    """``None`` when the build recorded by *prev* (the record beside
    *output_path*, see :func:`read_build_manifest`) may be UPDATED in place
    with this project's current edits; otherwise one sentence saying why it
    has to be built whole instead.

    All-or-nothing on purpose, like the override set's reuse test: a build is
    only worth patching because nothing has touched it since it was written,
    and the moment anything disagrees — the original, the project, the file,
    the app version that wrote the record, a copy that never landed — the
    honest answer is to start from the stock card again.
    """
    from ... import __version__
    if not prev:
        return "there is no record of a build here"
    if prev.get("building"):
        return "the last build here did not finish"
    if (int(prev.get("version") or 0) != BUILD_MANIFEST_VERSION
            or prev.get("app") != __version__):
        return ("it was built by a different version of this app (%s)"
                % (prev.get("app") or "unknown"))
    if not prev.get("complete"):
        return "the last build did not land every file"
    stock = prev.get("stock") or {}
    if (os.path.normcase(str(stock.get("path") or ""))
            != os.path.normcase(os.path.abspath(str(original_path)))
            or not _stamp_matches(stock, original_path)):
        return ("it was built from a different original, or the original "
                "has changed since")
    if (os.path.normcase(os.path.abspath(str(prev.get("assets") or "")))
            != os.path.normcase(os.path.abspath(str(assets_dir)))):
        return "it was built from a different project folder"
    if not _stamp_matches(prev.get("output") or {}, output_path):
        return "the file has changed since it was built"
    try:
        from .multiimage import images_for_path
        if len(images_for_path(original_path)) > 1:
            return "a multi-boot card is built whole"
    except Exception:
        pass
    # Item 149: modes change the system partition and the manifest's shape,
    # which an in-place update cannot put back; a build with modes, or the
    # first build after one, starts from the original - so taking every mode
    # out of a project gives a card without them.
    if prev.get("modes"):
        return ("the last build here carried modes" if _mode_family_on()
                else "the last build here carried preview content")
    # The SD card size the build is for (card_size.py): a build grown to 16 GB
    # is not the one a build for 32 GB (or the original's size) would update.
    try:
        from . import card_size as _cs
        want = _cs.target_for(original_path)
    except Exception as e:  # noqa: BLE001 - CardSizeError or an unreadable file
        return str(e).rstrip(".")
    if (prev.get("card_size") or None) != want:
        def _for(cls):
            return ("a %s SD card" % _cs.words(cls) if cls
                    else "the original's card size")
        return ("it was built for %s, and this build is for %s"
                % (_for(prev.get("card_size")), _for(want)))
    try:
        from . import mode_write as _MW
        if _mode_family_on() and _MW.enabled() and (
                _MW.project_modes(assets_dir) or _MW.code_mode_list(assets_dir)):
            return "a build that carries modes is built whole"
    except Exception:
        return "the project's modes could not be read"
    return None


def _source_digest(assets_dir, path, scratch=None):
    """MD5 of a file a build copies onto the card whole.  Through the
    project's size+mtime hash cache for a file that will still be there next
    time (a staged replacement, the user's own clip on another drive); a
    plain hash for one in this build's *scratch* space, which is gone before
    the next build and would only litter the cache.  ``None`` when
    unreadable."""
    from ...core import hashcache
    from ...core.checksums import md5_file
    abs_path = os.path.abspath(str(path))
    if scratch:
        root = os.path.normcase(os.path.abspath(str(scratch))).rstrip(os.sep)
        if os.path.normcase(abs_path).startswith(root + os.sep):
            try:
                return md5_file(_lp(abs_path))
            except OSError:
                return None
    hc = _HASHCACHES.get(assets_dir)
    if hc is None:
        hc = _HASHCACHES[assets_dir] = hashcache.load(assets_dir)
    try:
        rel = os.path.relpath(abs_path, assets_dir).replace(os.sep, "/")
    except ValueError:                        # another drive
        rel = None
    if rel is None or rel == ".." or rel.startswith("../"):
        rel = "abs:" + os.path.normcase(abs_path).replace(os.sep, "/")
    return hashcache.md5_for(abs_path, rel, hc)


def _open_readers(disk_f, parts):
    """``[(part_off, Ext4Reader), ...]`` for every ext partition in *parts*
    that can be read, in *parts*' order (largest first, so the games
    partition leads).  A partition the reader can't open is simply not there
    to map."""
    from .ext4 import Ext4Reader
    out = []
    for off, size in parts:
        try:
            out.append((int(off), Ext4Reader(disk_f, off, size)))
        except Exception:
            continue
    return out


def _file_key(part_off, path):
    """How the record names a card file: ``"<partition offset>:/<path>"``.
    The partition is part of the name because the boot screen lives on the
    OS partition and the game on the games partition, at paths that could
    coincide."""
    return "%d:/%s" % (int(part_off), str(path).lstrip("/"))


def _key_path(key):
    return key.split(":", 1)[1] if ":" in key else key


def _file_extents(reader, node):
    """The disk ranges holding a file, ``[]`` for an empty one, ``None`` when
    they can't be mapped (a hole, an inode the reader can't follow)."""
    size = int(node.get("size") or 0)
    if not size:
        return []
    try:
        return [(int(d), int(n)) for d, n in reader.disk_ranges(node, 0, size)]
    except Exception:
        return None


class _CardIndex:
    """The regular files of a card, by :func:`_file_key`, walked one
    partition at a time and only when asked: the games partition holds a few
    hundred files and every write but a boot-screen edit; the OS partition
    holds thousands and is walked only when something lands on it."""

    def __init__(self, disk_f, parts):
        self.parts = [(int(o), int(s)) for o, s in parts]
        self._readers = dict(_open_readers(disk_f, self.parts))
        self._files = {}                   # part_off -> {key: (reader, node)}

    def part_files(self, part_off):
        part_off = int(part_off)
        if part_off not in self._files:
            r = self._readers.get(part_off)
            files = {}
            if r is not None:
                for path, _ino, node in r.iter_regular_files(min_size=1):
                    files[_file_key(part_off, path)] = (r, node)
            self._files[part_off] = files
        return self._files[part_off]

    def lookup(self, key):
        """``(reader, node)`` for *key*, or ``None``."""
        try:
            part_off = int(key.split(":", 1)[0])
        except (ValueError, AttributeError):
            return None
        return self.part_files(part_off).get(key)

    def map_writes(self, writes):
        """Group absolute-disk *writes* by the card file each lands in:
        ``({key: (reader, node, [(file_off, bytes), ...])}, unmapped)`` —
        *unmapped* the writes no file's extents cover.  The whole-card twin
        of :func:`_writes_by_file`, which does one partition."""
        by_file, unmapped = {}, list(writes)
        for part_off, _size in self.parts:
            if not unmapped:
                break
            found, unmapped = _map_writes(self.part_files(part_off), unmapped)
            by_file.update(found)
        return by_file, unmapped


def _map_writes(files, writes):
    import bisect
    index = []
    for key, (reader, node) in files.items():
        runs = _file_extents(reader, node)
        if not runs:
            continue
        f_off = 0
        for disk, n in runs:
            index.append((disk, disk + n, key, reader, node, f_off))
            f_off += n
    index.sort(key=lambda e: (e[0], e[1]))
    starts = [e[0] for e in index]
    by_file, unmapped = {}, []
    for disk, buf in writes:
        pos = 0
        while pos < len(buf):
            here = disk + pos
            i = bisect.bisect_right(starts, here) - 1
            if i < 0 or not (index[i][0] <= here < index[i][1]):
                unmapped.append((disk, buf))
                break
            d_start, d_end, key, reader, node, f_off = index[i]
            take = min(d_end - here, len(buf) - pos)
            ent = by_file.setdefault(key, (reader, node, []))
            ent[2].append((f_off + (here - d_start), buf[pos:pos + take]))
            pos += take
    return by_file, unmapped


def _as_write_list(writes):
    """The write list as ``[(disk_offset, bytes), ...]`` (a dict is accepted
    for the stubbed tests that hand one in)."""
    if isinstance(writes, dict):
        return sorted(writes.items())
    return list(writes)


def _inplace_record(by_file):
    """The record's in-place half: ``{key: [[file_off, n], ...]}``, ranges
    merged, for every file this build patched in place."""
    return {key: [[int(o), int(n)] for o, n in _merge_ranges(
                [(off, len(buf)) for off, buf in fw])]
            for key, (_r, _n, fw) in by_file.items()}


def _whole_jobs(grow_plan):
    """Every file a build copies onto the card whole, as
    ``[(key, part_off, card_rel, source, kind), ...]`` in the order the build
    copies them — *kind* ``"video"``, ``"bank"`` (the grown sound bank) or
    ``"other"`` (a rebuilt game program, a re-serialised scene) on the games
    partition, ``"boot"`` on the OS partition."""
    out = []
    if not grow_plan:
        return out
    off = grow_plan.get("offset")
    jobs = grow_plan.get("jobs") or []
    n_video = grow_plan.get("n_video", len(jobs))
    audio_job = grow_plan.get("audio_job")
    for i, (rel, src) in enumerate(jobs):
        kind = ("video" if i < n_video
                else "bank" if i == audio_job else "other")
        out.append((_file_key(off, rel), int(off), rel.lstrip("/"), src,
                    kind))
    boot = grow_plan.get("boot") or {}
    for rel, src in boot.get("jobs") or []:
        out.append((_file_key(boot["offset"], rel), int(boot["offset"]),
                    rel.lstrip("/"), src, "boot"))
    return out


def _whole_digests(whole, assets_dir, scratch):
    """``{key: (digest, size)}`` for :func:`_whole_jobs`' sources — taken
    BEFORE the copies run, since a scratch source is gone afterwards.  An
    unreadable source maps to ``None``."""
    out = {}
    for key, _off, _rel, src, _kind in whole:
        d = _source_digest(assets_dir, src, scratch)
        try:
            size = os.path.getsize(_lp(src))
        except OSError:
            size = None
        out[key] = (d, size) if d is not None and size is not None else None
    return out


def _build_record(original_path, output_path, assets_dir, parts, by_file,
                  whole_record, complete, modes=None, card_size=None):
    """The record :func:`write_image` leaves beside its output.  Taken LAST,
    after every byte is on the card, because the output's stamp is what the
    next build checks before trusting any of it.  *modes* (item 149) is what
    the build's modes put on the card, recorded so the next build knows to
    start from the original."""
    from ... import __version__
    rec = {
        "version": BUILD_MANIFEST_VERSION,
        "app": __version__,
        "building": False,
        "complete": bool(complete),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stock": _file_stamp(original_path),
        "assets": os.path.abspath(str(assets_dir)),
        "partitions": [[int(o), int(s)] for o, s in parts],
        "inplace": _inplace_record(by_file),
        "whole": dict(whole_record),
        "output": _file_stamp(output_path),
    }
    if modes:
        rec["modes"] = modes
    if card_size:
        # the class the output was grown to (card_size.py); *partitions*
        # stays the ORIGINAL's, which every in-place range was resolved in
        rec["card_size"] = card_size
    return rec


def _update_plan(index, parts, output_path, prev, writes, whole, digests,
                 out_parts=None):
    """How the build at *output_path* (recorded in *prev*) becomes this one.

    Returns ``{"by_file", "restore", "copy", "keep", "back"}``: this build's
    in-place writes by file; the last build's in-place ranges that get the
    stock bytes back first; the whole-file copies whose source changed (or
    is new); the ones already on the card as they are; and the files the
    last build replaced whole that this build does not, which get the stock
    file back.  Raises :class:`_CannotUpdate` with the reason whenever the
    record can't vouch for the result — the caller builds whole.

    THE ONE RULE THAT MAKES IT SAFE: every in-place patch was resolved
    through the STOCK card's extent maps, so a file patched in place — by the
    last build or by this one — must still sit in exactly the blocks it had
    on the stock card.  A file the last build copied whole was reallocated by
    the filesystem driver; patching "its" stock blocks now would write into
    whatever lives there today.
    """
    # *out_parts*: the partitions the output should have - the original's,
    # or the original's grown to a bigger card class (card_size.py), whose
    # games partition starts where the original's does, so every key and
    # every in-place range below means the same thing on both.
    expect = [(int(o), int(s)) for o, s in (out_parts or parts)]
    prev_parts = [(int(o), int(s)) for o, s in _linux_partitions(output_path)]
    if prev_parts != expect:
        raise _CannotUpdate("its partition table differs from the original's")
    by_file, unmapped = index.map_writes(writes)
    if unmapped:
        raise _CannotUpdate(
            "%d of this build's patches could not be traced to a file on the "
            "card" % len(unmapped))
    now_whole = {}
    for key, off, rel, src, kind in whole:
        ent = digests.get(key)
        if ent is None:
            raise _CannotUpdate(
                "%s could not be read to compare with the last build" % rel)
        now_whole[key] = (off, rel, src, kind) + tuple(ent)
    prev_whole = prev.get("whole") or {}
    prev_inplace = prev.get("inplace") or {}
    for key in by_file:
        if key in prev_whole:
            raise _CannotUpdate(
                "%s was rewritten whole by the last build and is patched in "
                "place by this one" % _key_path(key))
    check = set(by_file) | {k for k in prev_inplace if k not in now_whole}
    with open(_lp(output_path), "rb") as prev_f:
        prev_index = _CardIndex(prev_f, expect)
        for key in sorted(check):
            stock = index.lookup(key)
            if stock is None:
                raise _CannotUpdate("%s is not on the original card"
                                    % _key_path(key))
            built = prev_index.lookup(key)
            if built is None:
                raise _CannotUpdate("%s is missing from the last build"
                                    % _key_path(key))
            s_ext = _file_extents(*stock)
            b_ext = _file_extents(*built)
            if (s_ext is None or b_ext is None or s_ext != b_ext
                    or stock[1].get("size") != built[1].get("size")):
                raise _CannotUpdate(
                    "%s no longer sits in the blocks it had on the original "
                    "card (the last build rewrote it whole)" % _key_path(key))
    restore = []
    for key, ranges in prev_inplace.items():
        if key in now_whole:
            continue                   # copied whole below; nothing to put back
        restore.append((key, [(int(o), int(n)) for o, n in ranges]))
    copy, keep = [], {}
    for key, (off, rel, src, kind, digest, size) in now_whole.items():
        rec = prev_whole.get(key) or {}
        if rec.get("digest") == digest and rec.get("size") == size:
            keep[key] = {"digest": digest, "size": size}
        else:
            copy.append((key, off, rel, src, kind, digest, size))
    back = []
    for key in sorted(prev_whole):
        if key in now_whole:
            continue
        if index.lookup(key) is None:
            raise _CannotUpdate("%s is not on the original card, so its stock "
                                "content can't be put back" % _key_path(key))
        back.append(key)
    return {"by_file": by_file, "restore": restore, "copy": copy,
            "keep": keep, "back": back}


def _apply_update(disk_f, index, output_path, plan, writes, log, label=None):
    """Turn the last build into this one: the last build's in-place edits
    come out (stock bytes back over every range it patched), this build's go
    in, then the whole-file copies whose source changed, and the stock file
    back for anything the last build replaced whole that this one doesn't.

    Returns ``(whole_record, failed)`` — the record's whole-file half as it
    stands after the copies, and ``[(key, card_rel, kind), ...]`` for copies
    that did not land (the caller adjusts its counts and marks the record
    incomplete, so the next build starts from the original)."""
    t0 = time.monotonic()
    n_back = 0
    with open(_lp(output_path), "r+b") as out:
        for key, ranges in plan["restore"]:
            reader, node = index.lookup(key)
            for off, n in ranges:
                for disk, m in reader.disk_ranges(node, off, n):
                    disk_f.seek(disk)
                    buf = disk_f.read(m)
                    if len(buf) != m:
                        raise OSError("the card image ended early at 0x%x"
                                      % disk)
                    out.seek(disk)
                    out.write(buf)
                    n_back += m
        _apply_writes(out, writes)
        out.flush()
        os.fsync(out.fileno())
    _stage_done(log, "writing the patched bytes into the build", t0)
    log("Patched %.1f MB in place (%.1f MB of the last build's edits were "
        "put back to stock first)."
        % (sum(len(b) for _d, b in _as_write_list(writes)) / 1e6,
           n_back / 1e6), "info")

    record = dict(plan["keep"])
    failed = []
    if plan["keep"]:
        log("%d file(s) copied whole by the last build are unchanged since "
            "and stay as they are." % len(plan["keep"]), "info")
    groups = {}            # part_off -> [(key, rel, src, kind, digest, size)]
    for key, off, rel, src, kind, digest, size in plan["copy"]:
        groups.setdefault(off, []).append((key, rel, src, kind, digest, size))
    scratch = None
    try:
        if plan["back"]:
            scratch = _work_dir(label, base="spike2_update_")
            for i, key in enumerate(plan["back"]):
                reader, node = index.lookup(key)
                rel = _key_path(key).lstrip("/")
                dest = os.path.join(scratch,
                                    "%03d_%s" % (i, os.path.basename(rel)))
                reader.extract_file(node, _lp(dest))
                groups.setdefault(int(key.split(":", 1)[0]), []).append(
                    (key, rel, dest, "stock", None, int(node.get("size") or 0)))
            log("%d file(s) the last build replaced whole are no longer "
                "replaced; the stock file goes back." % len(plan["back"]),
                "info")
        for off in sorted(groups):
            jobs = groups[off]
            t0 = time.monotonic()
            n_ok = _grow_whole(output_path, off,
                               [(rel, src) for _k, rel, src, *_ in jobs], log,
                               hint_sizes=plan.get("hint_sizes"), report=plan)
            _stage_done(log, "copying %d file(s) whole onto the card"
                        % len(jobs), t0)
            for i, (key, rel, src, kind, digest, size) in enumerate(jobs):
                if i < n_ok:
                    if kind == "stock":
                        record.pop(key, None)
                    else:
                        record[key] = {"digest": digest, "size": size}
                else:
                    failed.append((key, rel, kind))
    finally:
        if scratch:
            _rmtree(scratch)
    return record, failed


def _no_modes_why(assets_dir):
    """Item 149: why a Write with nothing to write carries no modes, in the log's
    words - the project has none, or its modes were left out by a closed gate
    (the warning above says which)."""
    from . import mode_write as _MW
    if not _mode_family_on():
        # not parsed (the switch is off), and said in neutral words: a copy without a
        # code names no preview feature
        have = _MW.preview_held(assets_dir)
        if have:
            return ("this project's %s are left out of this build (%s) with nothing "
                    "else to write" % (have, _MW.PREVIEW_REFUSAL))
        return "this project has nothing else to write"
    try:
        have = _MW.project_modes(assets_dir)
    except _MW.ModeWriteError:
        have = []
    if have:
        return ("this project's %d mode(s) are left out of this build (see above) "
                "with nothing else to write" % len(have))
    return "this project has none and nothing else to write"


def _modes_left_out_clause(left_out):
    """Item 149: the start of "Nothing to write" when the project HAS modes and a closed
    gate left them out (a direct-SD write, ``PAD_STERN_MODES=0``, no ext4 driver), so a
    modes-only project never reads as if it had no edits at all. ``""`` otherwise.
    *left_out* is ``(names, why)`` or None."""
    if not left_out:
        return ""
    names, why = left_out
    if names == "preview":
        # the preview switch is off: *why* is the neutral list (mode_write.preview_held),
        # and no feature is named
        from . import mode_write as _MW
        return ("this project's %s are left out of this write (%s), and "
                % (why, _MW.PREVIEW_REFUSAL))
    return ("the project's %d mode(s) (%s) are left out of this write (%s), and "
            % (len(names), ", ".join(names), why))


#: Beside a card image, the system partition's md5 that mode_install.py (through
#: mkmulticard) records after it writes p2.
P2_SIDECAR_SUFFIX = ".p2.md5"


def _drop_stale_p2_sidecar(output_path, log=None):
    """Item 149: a whole build copies the ORIGINAL system partition over the
    output, so a ``<out>.p2.md5`` left by an earlier mode build no longer
    describes it (mkmulticard's verify would call the card's p2 wrong).  Removed
    before the copy; a mode build's p2 install writes a fresh one."""
    side = str(output_path) + P2_SIDECAR_SUFFIX
    if os.path.isfile(_lp(side)):
        try:
            os.remove(_lp(side))
        except OSError as e:
            if log:
                log("The old system-partition checksum %s could not be removed "
                    "(%s); it describes the last build, not this one." % (side, e),
                    "warning")


def _install_modes(output_path, modes, landed, planned, log):
    """Item 149: put the modes' runtime on the built card's system partition
    and say, file by file, what the modes added.  Only once every whole-file
    copy has landed: a runtime armed over scenes or a manifest that did not
    make it would be a card that looks modded and is not.  Returns
    ``(record, ok)`` - *record* is what the build record keeps."""
    from . import mode_write as _MW
    if landed < planned:
        log("Modes: not every file reached the card, so the mode runtime was "
            "NOT put on the system partition and no mode will run on this "
            "card. Some of the modes' files may already be on it (the "
            "rewritten HUD and bank scenes can name a clip that did not "
            "land), so do not use this card: fix the issue above and Write "
            "again.", "error")
        return None, False
    try:
        _MW.install_p2(output_path, modes["payload"], modes["p2_epoch"],
                       log=log)
    except Exception as e:                   # the executor's CommandError too
        log("Modes: the mode runtime could not be put on the card's system "
            "partition, so this card carries no modes: %s" % e, "error")
        return None, False
    for rel in modes.get("added") or ():
        log("Modes: added %s." % rel, "info")
    for rel in modes.get("rewritten") or ():
        log("Modes: rewrote %s." % rel, "info")
    for name in modes.get("p2") or ():
        log("Modes: added %s/%s on the system partition." % (_MW.P2_DIR, name),
            "info")
    log("Modes: /etc/init.d/game_monitor now loads the mode runtime (port %s)."
        % modes.get("port"), "info")
    snd = modes.get("end_sound")
    if snd:
        log("Modes: request %d (sound idx %d) plays %s's own end sound."
            % (snd["request"], snd["idx"], snd["name"]), "info")
    for own in modes.get("own_sounds") or ():
        log("Modes: request %d (sound idx %d) plays %s's own %s."
            % (own["request"], own["idx"], own["name"],
               _MW.sound_words(own["key"])), "info")
    log("Modes: %d mode(s) on the card: %s."
        % (len(modes.get("names") or ()), ", ".join(modes.get("names") or ())),
        "success")
    rec = {k: modes.get(k) for k in ("names", "added", "rewritten", "port",
                                     "p2", "end_sound")}
    if modes.get("own_sounds"):
        rec["own_sounds"] = modes.get("own_sounds")
    return rec, True


def _rebuilt_not_written(no_space=False, rels=(), switches=True):
    """The error after a rebuilt game file (the game program, a scene, the
    grown sound bank) did not land, naming *rels* when given.  When the games
    partition ran out of room (*no_space*) it points at making room - the
    no-space line above it names the SD card size that fits - rather than
    at the environment switches that build the card without the longer sounds
    and text, which a user can't set from the app and which throw away what
    the build was for.  Otherwise it says to re-run the Write, and with
    *switches* names those switches as the size-neutral way out."""
    msg = ("A rebuilt game file (the game program with longer text or the "
           "blip-free cave, a re-serialised scene, or a sound bank grown to "
           "hold a longer callout) could NOT be written to the card%s%s. Its "
           "SD-validation record was already updated to match, so this card "
           "will fail validation"
           % (" because its games partition ran out of room" if no_space
              else "", ": " + ", ".join(rels) if rels else ""))
    if no_space:
        from . import card_size as _cs
        if not _cs.supported():
            # macOS: no SD card size control to point at
            return msg + ". Make room and Write again: take something out."
        if _cs.size_fixed():
            return msg + (". Make room and Write again: build this card on its "
                          "own from the Write tab for a bigger SD card when "
                          "the line above says one fits, or take something "
                          "out.")
        return msg + (". Make room and Write again: build for a bigger SD card "
                      "(SD card size on the Write tab) when the line above "
                      "says one fits, or take something out.")
    if not switches:
        return msg + " — re-run the Write."
    return msg + (" — re-run the Write, or build with PAD_STERN_TEXT_GROW=0 "
                  "(and PAD_STERN_SKIP_KEYPATCH=1 for the cave, "
                  "PAD_STERN_AUDIO_GROW=0 for the bank) for a standard "
                  "(size-neutral) build.")


def _report_failed_copies(failed, counts, audio_mode, log, no_space=False):
    """Say which whole-file copies of an update did not land, and take them
    out of the completion counts so the summary never claims a file the card
    doesn't have — the full build's accounting, per kind.  *no_space*: the
    copies stopped because the games partition ran out of room."""
    n_audio, n_video, n_image, n_text = counts
    vids = [rel for _k, rel, kind in failed if kind == "video"]
    boots = [rel for _k, rel, kind in failed if kind == "boot"]
    stocks = [rel for _k, rel, kind in failed if kind == "stock"]
    others = [(rel, kind) for _k, rel, kind in failed
              if kind in ("bank", "other")]
    if vids:
        n_video -= len(vids)
        log("%d replaced video(s) could NOT be written — those slots still "
            "hold what the last build put there. Fix the issue above and run "
            "the Write again: %s" % (len(vids), ", ".join(vids)), "error")
    if boots:
        n_image -= len(boots)
        log("The replaced boot screen could NOT be copied onto the card, so "
            "it still shows what the last build put there. Fix the issue "
            "above and run the Write again.", "error")
    if others:
        log(_rebuilt_not_written(no_space, [rel for rel, _k in others],
                                 switches=False), "error")
        if any(kind == "bank" for _r, kind in others):
            log("The grown sound bank was one of them, so NONE of the "
                "re-encoded sounds are on this card.", "error")
            n_audio = 0
        if audio_mode and audio_mode[0] == "blip-free":
            audio_mode = ("standard", "the rebuilt blip-free firmware could "
                          "not be copied onto the card (see the build log; "
                          "this image will fail SD validation until rebuilt)")
    if stocks:
        log("%d file(s) could NOT be put back to stock and still hold what "
            "the last build put there: %s" % (len(stocks), ", ".join(stocks)),
            "error")
    log("Because a copy failed, this build's record is marked incomplete and "
        "the next build starts from the original.", "warning")
    return (n_audio, n_video, n_image, n_text), audio_mode


def write_image(original_path, assets_dir, output_path, log=None, progress=None,
                cancel=None, label=None, update=None):
    """Patch a copy of the card image at ``output_path`` with the user's edits
    (size-neutral, in place): re-encoded cat-0 audio bodies inside ``image.bin``,
    re-encoded per-song music bodies inside their ``image-scNN.bin`` banks,
    replaced LCD videos written over their original ``.asset`` files, and
    replaced UI images written over their original ``.png`` files.  Any kind of
    edit may be absent — a video/image-only write skips the firmware emulator
    entirely.

    OR UPDATE THE BUILD ALREADY THERE.  Every build leaves a record beside
    its output (:func:`build_manifest_path`) of what it put on the card.
    When the file at ``output_path`` is that build, untouched since, from
    this same original and project (:func:`build_update_reason`), the card
    image is not copied again and only what changed since goes in: the last
    build's in-place edits are put back to the stock bytes and this build's
    go in over them, a file copied whole last time is copied again only when
    its source changed, and one no longer replaced gets the stock file back.
    A modder iterating on a retheme with hundreds of replaced videos used to
    pay for every one of them on every build (Godzilla Heisei: about two and
    a half hours per build on the modder's machine for a few changed clips);
    an update costs the changed clips.

    ``update``: ``None`` updates when it can and builds whole otherwise (a
    log line says which); ``True`` is the user's explicit choice to update
    (it still falls back, loudly, when the record disagrees); ``False``
    always builds whole.  Anything the record can't vouch for — a file the
    last build rewrote whole that this build patches in place, a copy that
    did not land, a partition table that moved — makes the build start over
    from the original rather than guess (:func:`_update_plan`).
    """
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    t_write = time.monotonic()
    import shutil
    import threading

    from ...core import build_output

    # The destination folder before anything else.  The copy below is the first
    # thing that touches it, on a background thread whose failure only surfaces
    # at the join — so a Build Location that wasn't on disk yet used to fail a
    # minute and a half in, with an [Errno 2] naming the build FILE rather than
    # the missing folder (see core.build_output).
    dest_err = build_output.ensure_dir_for(output_path)
    if dest_err:
        raise OSError(dest_err)

    # A BIGGER CARD (card_size.py): the games partition grown to Stern's 16 GB
    # or 32 GB class so the files this build copies on whole have room.
    # Settled before anything is copied or encoded, so an original that can't
    # grow, or a computer without resize2fs, is refused in seconds rather
    # than after the encode.
    from . import card_size as _cs
    grow_to = _cs.preflight(original_path, _cs.requested(), tools=False)
    if grow_to:
        log("This build is for a %s SD card: the games partition is grown to "
            "fill it, so it needs an SD card of at least %s."
            % (_cs.words(grow_to), _cs.words(grow_to)), "info")
    elif _cs.requested():
        # a card is never made smaller: say so rather than hand back a bigger
        # image than the one the user thinks they asked for
        log("SD card size %s: the original is already a card that size or "
            "bigger, so this build keeps the original's size."
            % _cs.words(_cs.requested()), "info")

    # UPDATE THE LAST BUILD, OR BUILD WHOLE?  Settled before the copy starts,
    # because the copy is the first thing an update saves.
    prev, updating = {}, False
    if update is not False:
        prev = read_build_manifest(output_path)
        why = build_update_reason(prev, original_path, output_path, assets_dir)
        if why is None:
            updating = True
        elif update or prev:
            log("Building from the original rather than updating the build "
                "already at %s: %s." % (output_path, why),
                "warning" if update else "info")
    # Growing takes the Linux side's loop devices and e2fsprogs; an update of
    # a build that is already that size grows nothing, so only a whole build
    # asks (still before any copy or encode).
    if grow_to and not updating:
        _cs.check_tools(grow_to)
    # What a no-space failure may suggest: the sizes the Write tab would offer
    # for this original, not whatever is bigger than the output.
    try:
        hint_sizes = _cs.offered(original_path)
    except Exception:  # noqa: BLE001 - a hint is never worth failing a build
        hint_sizes = []
    # Item 149: did the build already at the output carry modes?  Read before
    # the copy lays its stub record over it.
    prev_modes = (prev or read_build_manifest(output_path)).get("modes")
    # Item 145: with nothing staged any more, a project that manages the
    # game's own modes puts ITS build at the output back to the original
    # rather than refusing.  Asked now, before the copy lays its stub record
    # over the one that says whose build this is.
    restore_ok = _stock_mode_restore_ok(assets_dir, output_path, prev)

    # Copy the (unpatched) card image to the output in a BACKGROUND THREAD while
    # we compute the patches.  Computing them is CPU-bound -- the parallel cat-0
    # re-encode and the in-process master-directory integrity assert -- and both
    # yield the GIL often enough (the assert's emulator fires a per-instruction
    # Python hook; the re-encode blocks on its worker pool) that the copy's I/O
    # runs concurrently and disappears under it (measured: a 7.9 GB card copy
    # hides fully under the ~120 s assert).  The copy only writes output_path and
    # only reads original_path (which _compute_patches reads through a separate
    # handle), so they're independent; join()ing before any patch byte is written
    # keeps it purely opportunistic -- it shaves the copy off the wall-clock but
    # never reorders or corrupts the write.
    #
    # PAD-176: the copy starts once the build has been measured against the
    # games partition and fits (_SpaceBudget.clear, from _compute_patches'
    # pre-flight, before anything is encoded), not before: a build that is
    # refused leaves the file at the output and its record as they were, and
    # is refused in a second rather than after the whole card was copied.
    copy_err = []

    def _bg_copy():
        try:
            shutil.copyfile(_lp(original_path), _lp(output_path))
        except BaseException as e:          # surfaced to the caller after join
            copy_err.append(e)

    def _start_copy():
        # The stub record goes down first: from here on the file at the
        # output is being rewritten, and nothing may take it for a build.
        _mark_building(output_path)
        _drop_stale_p2_sidecar(output_path, log)
        t = threading.Thread(target=_bg_copy, name="spike2-image-copy",
                             daemon=True)
        t.start()
        return t

    copier = None
    if updating:
        log("Updating the build already at %s: the card image is not copied "
            "again, and only what changed since it was built is written."
            % output_path, "info")

    def _clear():
        # The build was measured and fits, or can't be measured: the output
        # may be written from here.  An update that only fits made from the
        # original is made from the original, as for any update that can't be,
        # and like theirs its copy starts only once the edits are computed:
        # the last build is the user's until then, so a failed or cancelled
        # encode leaves it as it was.
        nonlocal copier, updating
        if updating and budget.whole:
            log("This build can't update the last one in place (%s); building "
                "from the original instead." % budget.whole, "warning")
            updating = False
            if grow_to:
                _cs.check_tools(grow_to)    # a whole build grows it now
            return
        if not updating and copier is None:
            log("Copying card image to output (in parallel with computing "
                "edits)...", "info")
            copier = _start_copy()

    parts = _linux_partitions(original_path)
    disk_f = open(_lp(original_path), "rb")
    grow_plan = None
    # PAD-176: what the whole-file copies are measured against before the
    # encode (_SpaceCheck): the original grown to this build's SD card size,
    # and for an update first the build already at the output.
    budget = _SpaceBudget(original_path, output=output_path,
                          updating=updating, grow_to=grow_to,
                          sizes=hint_sizes, fixed=_cs.size_fixed(),
                          on_clear=_clear)
    try:
        try:
            with _SpaceScope(budget):
                writes, counts, grow_plan, audio_mode, valpatch_mode = \
                    _compute_patches_or_restore(restore_ok, log,
                                                disk_f, parts, assets_dir,
                                                log, progress, cancel,
                                                label=label)
        except NothingToWrite:
            # Item 149: every mode taken out of a project with nothing else to
            # write.  The card at the output still carries the last build's
            # modes, and the Write the user asked for is the card without
            # them - which is the original, copied now.  ONLY on
            # NothingToWrite: any other missing file is a failed build.
            if prev_modes and not updating:
                if copier is None:
                    copier = _start_copy()
                copier.join()
                if not copy_err:
                    # the original, at the SD card size this build is for
                    if grow_to and not _expand_card(
                            original_path, output_path, parts, grow_to, log,
                            cancel):
                        return (0, 0, 0, 0), None, None
                    try:
                        os.utime(_lp(output_path), None)
                    except OSError:
                        pass
                    _write_build_manifest(
                        output_path,
                        _build_record(original_path, output_path, assets_dir,
                                      parts, {}, {}, True,
                                      card_size=grow_to))
                    if _mode_family_on():
                        log("The build at %s carried modes (%s) and %s, so it is "
                            "written as the original card: no modes, stock files."
                            % (output_path, ", ".join(prev_modes.get("names") or ()),
                               _no_modes_why(assets_dir)),
                            "success")
                    else:
                        # neutral words: a copy without a code names no preview feature
                        log("The build at %s carried preview content (%s) and %s, so "
                            "it is written as the original card: stock files."
                            % (output_path, ", ".join(prev_modes.get("names") or ()),
                               _no_modes_why(assets_dir)),
                            "success")
                    return (0, 0, 0, 0), None, None
            if copier is not None:
                copier.join()               # let the copy finish before unlinking
                _discard_output(output_path)
            raise
        except BaseException:
            if copier is not None:
                copier.join()               # let the copy finish before unlinking
                _discard_output(output_path)
            raise
        if writes is None:                  # cancelled mid-compute
            if copier is not None:
                copier.join()
                _discard_output(output_path)
            return (0, 0, 0, 0), None, None
        # a build the pre-flight didn't measure starts its copy here
        budget.clear()
        if not updating and copier is None:
            # the update the pre-flight made a whole build (_clear)
            log("Copying card image to output...", "info")
            copier = _start_copy()
        # the game's own modes (item 145): kept aside, since the counts below
        # are rebuilt as plain tuples when a copy fails
        n_stock_mode_numbers = getattr(counts, "stock_modes", 0)
        restored_to_original = getattr(counts, "restored", False)
        wlist = _as_write_list(writes)

        # What this build puts on the card whole, digested BEFORE any copy
        # runs (a scratch source is gone afterwards) and before the plan
        # below compares it with the last build's.
        index = _CardIndex(disk_f, parts)
        whole = _whole_jobs(grow_plan)
        digests = _whole_digests(whole, assets_dir,
                                 (grow_plan or {}).get("cleanup"))
        if grow_plan is not None:
            grow_plan["hint_sizes"] = hint_sizes
        _save_hashcache(assets_dir)

        plan = None
        if updating:
            try:
                plan = _update_plan(index, parts, output_path, prev, wlist,
                                    whole, digests,
                                    out_parts=_cs.output_parts(
                                        original_path, parts, grow_to))
                if not _mark_building(output_path):
                    raise _CannotUpdate("the build record beside the output "
                                        "can't be written")
                plan["hint_sizes"] = hint_sizes
            except _CannotUpdate as e:
                log("This build can't update the last one in place (%s); "
                    "building from the original instead." % e, "warning")
                updating = False
                if grow_to:
                    _cs.check_tools(grow_to)    # a whole build grows it now
                t0 = time.monotonic()
                log("Copying card image to output...", "info")
                copier = _start_copy()
                copier.join()
                _stage_done(log, "copying the card image to the output", t0)
        if copier is not None:
            t0 = time.monotonic()
            copier.join()
            _stage_done(log, "waiting for the card-image copy to finish (the "
                        "copy outlived the edit computation - a faster build "
                        "drive would shorten this)", t0)
            if copy_err:                    # the background copy itself failed
                _discard_output(output_path)
                # Say what was being done and where — the raw error is an errno
                # and a path, which read as the app losing the user's card image.
                raise OSError("Could not copy the card image to the build's "
                              "destination:\n\n    %s\n\n%s"
                              % (output_path, copy_err[0])) from copy_err[0]

        whole_record, complete = {}, True
        mode_rec = None
        if updating:
            whole_record, failed = _apply_update(disk_f, index, output_path,
                                                 plan, writes, log, label=label)
            by_file = plan["by_file"]
            if failed:
                complete = False
                counts, audio_mode = _report_failed_copies(
                    failed, counts, audio_mode, log,
                    no_space=bool(plan.get("no_space")))
            n_audio, n_video, n_image, n_text = counts
        else:
            # the copy is already on disk; patch the changed bytes in place
            t0 = time.monotonic()
            with open(_lp(output_path), "r+b") as out:
                _apply_writes(out, writes)
                out.flush()
                os.fsync(out.fileno())
            _stage_done(log, "writing the patched bytes into the image", t0)
            if grow_to and not _expand_card(original_path, output_path,
                                            parts, grow_to, log, cancel):
                return (0, 0, 0, 0), None, None     # cancelled
            # Grow the files that outgrew their slots (oversized videos kept at
            # full quality, and the rebuilt firmware when a blip-free build is
            # on) by copying them in through the ext4 driver — done AFTER the
            # in-place writes so the filesystem it mounts is already consistent.
            t0 = time.monotonic()
            n_grown = _grow_video_slots(output_path, grow_plan, log)
            _stage_done(log, _grow_stage_name(grow_plan), t0)
            n_boot_grown = _grow_boot_screen(output_path, grow_plan, log)
            n_audio, n_video, n_image, n_text = counts
            n_boot_jobs = len(((grow_plan or {}).get("boot") or {}).get("jobs") or ())
            if n_boot_grown < n_boot_jobs:
                n_image -= n_boot_jobs - n_boot_grown
                counts = (n_audio, n_video, n_image, n_text)
                log("The replaced boot screen could NOT be copied onto the card, so "
                    "it still shows Stern's own. Fix the issue above and run the "
                    "Write again.", "error")
            n_planned = len(grow_plan["jobs"]) if grow_plan else 0
            # The firmware job is queued last, so jobs fail from the end: anything short
            # of the full count means the firmware didn't land, and only the remainder
            # comes out of the video tally.
            n_vid_jobs = grow_plan.get("n_video", n_planned) if grow_plan else 0
            if n_grown < n_planned:
                if n_planned > n_vid_jobs:
                    # Serious: the .sidx record already describes the rebuilt firmware
                    # (or re-serialised scene), so the card now claims a file it
                    # doesn't have.
                    log(_rebuilt_not_written(grow_plan.get("no_space")), "error")
                    aj = grow_plan.get("audio_job")
                    if aj is not None and n_grown <= aj:
                        log("The grown sound bank was one of them, so NONE of the "
                            "re-encoded sounds are on this card.", "error")
                        n_audio = 0
                        counts = (n_audio, n_video, n_image, n_text)
                    # The completion dialog must not claim a blip-free card either.
                    if audio_mode and audio_mode[0] == "blip-free":
                        audio_mode = ("standard", "the rebuilt blip-free firmware "
                                      "could not be copied onto the card (see the "
                                      "build log; this image will fail SD validation "
                                      "until rebuilt)")
                n_vid_failed = max(0, n_vid_jobs - n_grown)
                if n_vid_failed:
                    # The summary must not claim videos that never landed: every grow
                    # job that failed left its slot with the STOCK content.
                    n_video -= n_vid_failed
                    counts = (n_audio, n_video, n_image, n_text)
                    log("%d of %d replaced video(s) could NOT be written — those slots "
                        "still hold the game's stock videos. Fix the issue above and "
                        "run the Write again." % (n_vid_failed, n_vid_jobs), "error")
            # Item 149: the modes' system-partition half - the pinned runtime,
            # the mode files and the port - once every games-partition file
            # they depend on has landed.
            if (grow_plan or {}).get("modes"):
                mode_rec, _mok = _install_modes(output_path,
                                                grow_plan["modes"], n_grown,
                                                n_planned, log)
                if not _mok:
                    complete = False
            # The record of what this build put on the card, for the next one
            # to update: every in-place write traced back to its file, every
            # whole-file copy that landed (they land in order) with its
            # source's digest.  A write no file covers, or a copy that did not
            # land, leaves the record incomplete, and the next build is whole.
            by_file, unmapped = index.map_writes(wlist)
            games = [w for w in whole if w[4] != "boot"]
            boots = [w for w in whole if w[4] == "boot"]
            for key in ([w[0] for w in games[:n_grown]]
                        + [w[0] for w in boots[:n_boot_grown]]):
                ent = digests.get(key)
                if ent is None:
                    complete = False
                else:
                    whole_record[key] = {"digest": ent[0], "size": ent[1]}
            complete = (complete and not unmapped
                        and n_grown >= len(games)
                        and n_boot_grown >= len(boots))
        # Every write to the output is done; the driver's copies went through
        # WSL and the timestamp they leave is theirs, so stamp the file from
        # this side (a handle closed here guarantees the time it records)
        # and only then take the record's stamp of it.
        try:
            os.utime(_lp(output_path), None)
        except OSError:
            pass
        try:
            _write_build_manifest(
                output_path,
                _build_record(original_path, output_path, assets_dir, parts,
                              by_file, whole_record, complete,
                              modes=mode_rec, card_size=grow_to))
        except OSError as e:
            log("The build's record could not be written beside it (%s), so "
                "the next build starts from the original." % e, "info")
        if updating:
            log("Updated the build in %s: %s (%d sound(s), %d video(s), "
                "%d image(s), %d display string(s)); %d file(s) copied whole, "
                "%d unchanged since the last build, %d put back to stock."
                % (_fmt_dur(time.monotonic() - t_write), output_path,
                   n_audio, n_video, n_image, n_text, len(plan["copy"]),
                   len(plan["keep"]), len(plan["back"])), "success")
        else:
            log("Wrote patched image in %s: %s (%d sound(s), %d video(s), "
                "%d image(s), %d display string(s))."
                % (_fmt_dur(time.monotonic() - t_write), output_path,
                   n_audio, n_video, n_image, n_text), "success")
        # Return the per-type breakdown (not just the total) so the completion
        # dialog can name what actually changed instead of always saying
        # "sound(s)", plus the audio build mode so it can say whether the card
        # is blip-free or keeps the original-sound scrap (a fallback was
        # invisible outside the log), and the validator status so it can say
        # when the card will fail Stern's SD-card validation on the machine.
        # The game's own modes ride on the counts (item 145, _WriteCounts).
        counts = _with_stock_modes(counts, n_stock_mode_numbers,
                                   restored_to_original)
        return counts, audio_mode, valpatch_mode
    finally:
        disk_f.close()
        # The rebuilt firmware has been copied onto the card (or has failed to
        # be); either way its scratch dir is ours to remove now.
        _rmtree_grow_plan(grow_plan)


#: The file that makes a folder an override set rather than somebody's
#: documents.  Written last (so a half-built set has no manifest and is
#: therefore never bound over a card), and the only thing that lets
#: :func:`write_overrides` clear a folder it is about to rewrite.
OVERRIDE_MANIFEST = "overrides.json"
# Beside it, and read by the rig rather than by this app: the shopping list
# for staging one build's changes onto a stage that holds the one before it.
OVERRIDE_DELTA = "overrides.delta"
# Bumped when either file's shape changes: a set written by an older PAD is
# rebuilt from scratch rather than half-understood.
OVERRIDE_VERSION = 2


def _writes_by_file(reader, writes):
    """Group absolute-disk *writes* by the CARD FILE each one lands in.

    Returns ``({card_path: (node, [(file_off, bytes), ...])}, unmapped)`` —
    *unmapped* being the writes no file's extents cover.

    THE WHOLE POINT IS THAT THE WRITE LIST IS ALREADY THE ANSWER.  Every patch
    :func:`_compute_patches` produces was resolved from a file offset through
    ``disk_ranges`` on the way out, so mapping it back is exact rather than a
    second guess at what the edit meant: the override set is the same bytes the
    built card would carry, in the file the built card would carry them in.

    Cost is a directory walk plus one extent map per regular file — 619 files
    and 657 runs on a jurassic_park_le 1.16.0 card, measured at well under a
    tenth of a second, because these cards store their assets in a handful of
    large extents.
    """
    index = []                       # (disk_start, disk_end, path, node, f_off)
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        f_off = 0
        try:
            runs = reader.disk_ranges(node, 0, node["size"])
        except Exception:            # a hole, or an inode we can't map
            continue
        for disk, n in runs:
            index.append((disk, disk + n, path, node, f_off))
            f_off += n
    index.sort()
    starts = [r[0] for r in index]

    import bisect
    by_file, unmapped = {}, []
    for disk, buf in writes:
        pos = 0
        while pos < len(buf):
            here = disk + pos
            i = bisect.bisect_right(starts, here) - 1
            if i < 0:
                unmapped.append(here)
                break
            d_start, d_end, path, node, f_off = index[i]
            if not (d_start <= here < d_end):
                unmapped.append(here)
                break
            # A single write CAN straddle two extents of the same file (the
            # producers split on the extent map, but nothing promises that
            # every one of them did), so take what this run holds and go round
            # again for the rest.
            take = min(d_end - here, len(buf) - pos)
            ent = by_file.setdefault(path, (node, []))
            ent[1].append((f_off + (here - d_start), buf[pos:pos + take]))
            pos += take
    return by_file, unmapped


def card_title_index(path):
    """The ``.sidx`` names in ``/spk/index`` on the games partition
    :func:`write_overrides` would edit on the card image at *path*, sorted —
    which title, edition and version the card is
    (``("godzilla_le-1_16_0.sidx",)``) — or ``()`` when it can't be read.

    Only directory blocks are read, so it costs milliseconds on a multi-GB
    image.  PAD-161 asks it of two cards to decide whether an override set may
    be prepared from one and run over the other: a card PAD built keeps its
    title's index name, another version of the game does not.
    """
    from .ext4 import S_IFDIR, S_IFMT
    try:
        with open(_lp(str(path)), "rb") as f:
            reader, _fw, _img = _locate(f, _linux_partitions(path))
            node = reader.read_inode(2)
            for name in ("spk", "index"):
                ino = next((c for n, c, _t in reader._iter_dir(node)
                            if n == name), None)
                if ino is None:
                    return ()
                node = reader.read_inode(ino)
                if node["mode"] & S_IFMT != S_IFDIR:
                    return ()
            return tuple(sorted(n for n, _c, _t in reader._iter_dir(node)
                                if n.lower().endswith(".sidx")))
    except Exception:
        return ()


def write_overrides(original_path, assets_dir, out_dir, log=None, progress=None,
                    cancel=None, label=None, run_card=None, sound_ok=None):
    """Build an OVERRIDE SET: the card files the user's edits touch, patched,
    and nothing else — so the emulator can run those edits without a rebuild.

    Same edits, same bytes, same code path as :func:`write_image`: this calls
    ``_compute_patches`` and then, instead of copying the whole card image and
    patching it, writes each TOUCHED FILE out on its own.  The emulator binds
    those files over the read-only card mount at run time (``PAD_OVERRIDE_DIR``
    in ``tools/spike2_emu/run_game.sh``), which is the same trick the rig
    already uses to mask a title's ``boot_display_cmd``.

    WHY IT EXISTS (PAD-103, DragonRR: "rather than rebuild a raw image using
    new assets and then emulate … can you make it so that any added assets will
    override raw image files?").  Trying a replaced callout on the PC costs two
    full-size copies today — the build's copy of the card, then the emulator's
    own copy of that new card onto the WSL disk, because its cache is keyed on
    size+mtime and a fresh build invalidates it.  On a 7.3 GB card with one
    edited sound the override set is ``image.bin`` plus the ``.sidx`` record:
    the same bytes, a fraction of the I/O, and the stock card's cache stays
    valid because the stock card was never touched.

    A SECOND BUILD PATCHES THE FIRST rather than laying it down again, when
    the card is the same one and every file the manifest names is still there
    as it was left: the card's own bytes go back over what the last build
    wrote, this build's writes go on top, and a file the edits no longer touch
    is deleted.  Rebuilding whole would mean re-extracting a 1.4 GB
    ``image.bin`` because one callout changed, and then handing the rig 1.4 GB
    to copy over 9p, on every Start.  :data:`OVERRIDE_DELTA` is written beside
    the manifest so the staging script can be just as narrow
    (``tools/spike2_emu/overrides.sh``).

    *run_card* is the card the set will be bound over, when that is not
    *original_path* (a card PAD built from this project: PAD-161 prepares the
    set from the original, and PAD-172 is what that cost).  The set's game
    program then keeps what that card's own build changed in it and these
    edits do not - see :func:`_carry_run_card_program`.  Recorded in the
    manifest, because a set carrying one card's program is not the set for
    another.

    *sound_ok* is the modes' own-sound gate for THIS build: ``None`` reads
    the environment gate as :func:`write_image` does, ``False`` leaves the
    own sounds out with a reason in the log.  A parameter rather than the
    environment because a Try it can run beside a Write in the same process.

    *out_dir* is emptied first when it cannot be patched, and only if it is
    empty or already an override set (it carries :data:`OVERRIDE_MANIFEST`)
    — a stale file left behind would still be bound over the card, so "what is
    in the folder" has to mean "what the current edits say", and a folder that
    is somebody's documents is not ours to clear.

    Returns ``(counts, audio_mode, valpatch_mode, files)`` — the first three
    exactly as :func:`write_image` returns them, *files* being
    ``[(card_path, size), ...]`` for what was written.  Everything is ``None``
    when the caller cancelled.
    """
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    t_all = time.monotonic()
    import shutil

    out_dir = os.path.abspath(str(out_dir))
    if os.path.isdir(_lp(out_dir)) and os.listdir(_lp(out_dir)) \
            and not os.path.isfile(_lp(os.path.join(out_dir,
                                                    OVERRIDE_MANIFEST))):
        raise OSError(
            "The override folder\n\n    %s\n\nalready holds files that were "
            "not put there by this app, and building the set would delete "
            "them. Point it at an empty folder." % out_dir)

    # WHAT IS ALREADY THERE, and may it be patched instead of rebuilt?  Asked
    # before anything is written, because the question is whether the folder
    # on disk is still exactly the set this manifest describes.
    previous = read_override_manifest(out_dir)
    have = _override_reuse(out_dir, previous, original_path)

    parts = _linux_partitions(original_path)
    disk_f = open(_lp(original_path), "rb")
    try:
        writes, counts, grow_plan, audio_mode, valpatch_mode = _compute_patches(
            disk_f, parts, assets_dir, log, progress, cancel, label=label,
            boot_screen=False,
            # Only when the caller decided the gate: the default call stays
            # exactly the call it was (the tests' stand-ins for
            # _compute_patches pin its signature).
            **({} if sound_ok is None else {"sound_ok": sound_ok}))
        if writes is None:                  # cancelled mid-compute
            _rmtree_grow_plan(grow_plan)
            return None, None, None, None
        try:
            # A second locate rather than a value threaded out of
            # _compute_patches: it is a directory scan on an already-open
            # handle, and one function owning "which partition is the game on"
            # is worth more here than the milliseconds.
            reader, _fw_node, _img_node = _locate(disk_f, parts)
            t0 = time.monotonic()
            by_file, unmapped = _writes_by_file(reader, writes)
            if unmapped:
                # Never write a PARTIAL override set: the run would look like
                # it was testing the edits while silently dropping some of
                # them, which is the failure the build path cannot have.
                raise RuntimeError(
                    "%d of this build's patches could not be traced back to a "
                    "file on the card (first at disk offset 0x%x), so an "
                    "override set would be missing them. Build the card image "
                    "instead." % (len(unmapped), unmapped[0]))
            _stage_done(log, "tracing the edits back to the card files they "
                        "live in", t0)
            if run_card is not None:
                _carry_run_card_program(reader, _fw_node, by_file, grow_plan,
                                        original_path, run_card, log)

            # UPDATE WHAT IS THERE, or lay a new set down.  Building whole
            # means re-extracting a 1.4 GB image.bin because one callout
            # changed, and then handing the rig 1.4 GB to copy over 9p, on
            # every Start; neither has anything to do with what the user
            # changed since the last run.
            fresh = have is None
            parent = "" if fresh else str(previous.get("generation") or "")
            if fresh:
                _rmtree(out_dir)
                if os.path.isdir(_lp(out_dir)) and os.listdir(_lp(out_dir)):
                    # Silent-by-design rmtree: say so rather than building a
                    # set ON TOP of a previous one, where the leftovers would
                    # be bound over the card alongside the current edits.
                    raise OSError(
                        "The override folder\n\n    %s\n\ncould not be "
                        "emptied — something else has a file in it open."
                        % out_dir)
                os.makedirs(_lp(out_dir), exist_ok=True)
                have = {}
            # A STUB MANIFEST BEFORE ANY BYTES, so a build that dies half way
            # (the app killed, the disk full) leaves a folder that is still
            # recognisably OURS.  Without it the guard at the top of this
            # function — which refuses to clear a folder with no manifest in
            # it, because it might be somebody's documents — would refuse this
            # folder from then on.  A stub never satisfies the "may I reuse
            # this?" test either: it names no card, so the next Start rebuilds.
            # It is also what makes patching in place safe: a half-patched set
            # is one no manifest vouches for, so nothing will bind it.
            _write_override_manifest(out_dir, {"version": OVERRIDE_VERSION,
                                               "building": True})
            written, records, delta = [], [], []
            t0 = time.monotonic()
            total = len(by_file) + len((grow_plan or {}).get("jobs", ()))
            try:
                for i, (card_path, (node, file_writes)) in enumerate(
                        sorted(by_file.items())):
                    if cancel():
                        if fresh:
                            _rmtree(out_dir)   # the plan is cleaned by finally
                        return None, None, None, None
                    if progress:
                        progress(i, max(total, 1),
                                 "Writing %s" % os.path.basename(card_path))
                    dest = _override_path(out_dir, card_path)
                    ranges = _merge_ranges(
                        [(off, len(buf)) for off, buf in file_writes])
                    rec = have.get(card_path)
                    if rec is not None and rec.get("size") != node["size"]:
                        # Under this path in the old set, but not the card's
                        # own file (a video that outgrew its slot last time),
                        # so these offsets do not mean anything in it.
                        rec = None
                    if rec is None:
                        os.makedirs(_lp(os.path.dirname(dest)), exist_ok=True)
                        log("Override: %s (%.1f MB)"
                            % (card_path, node["size"] / 1e6), "info")
                        reader.extract_file(node, _lp(dest))
                        touched = None                  # all of it is new
                    else:
                        # PATCHED IN PLACE.  The card's own bytes go back over
                        # what the last build wrote, so an edit taken back
                        # since then is really gone, and then this build's
                        # writes go on top.  Both are bounded by the size of
                        # the edits and never by the size of the file.
                        was = [(int(o), int(n))
                               for o, n in (rec.get("ranges") or [])]
                        _restore_stock(disk_f, reader, node, dest, was)
                        touched = _merge_ranges(was + ranges)
                        log("Override: %s (%.1f MB of it, in place)"
                            % (card_path,
                               sum(n for _o, n in touched) / 1e6), "info")
                    with open(_lp(dest), "r+b") as f:
                        for f_off, buf in file_writes:
                            f.seek(f_off)
                            f.write(buf)
                    written.append((card_path, node["size"]))
                    records.append(_override_record(dest, card_path, ranges))
                    delta.append(
                        (card_path, _delta_ranges(touched, node["size"])))

                # The grown files (an oversized replacement video kept at full
                # quality, and the rebuilt blip-free firmware) are the easy
                # half here: on a card they need the ext4 driver because they
                # no longer fit their slot, and in a set a file is just a file.
                # AFTER the in-place writes, exactly as write_image orders
                # them, so a file that is both ends up the same either way.
                # Written whole when they are written: they are built into a
                # scratch dir on every run, so there is no earlier version to
                # patch and no mtime worth believing.  EXCEPT that a build
                # whose grown file came out byte-for-byte what the last one
                # put here (the ordinary second Try it: the same own sound on
                # the same card) leaves that file as it is and out of the
                # delta.  The rig's stage keeps a file the delta does not
                # name and only checks its size (tools/spike2_emu/
                # overrides.sh), so a 1.65 GB grown bank is neither rewritten
                # here nor copied over 9p again.
                for j, (card_rel, source) in enumerate(
                        (grow_plan or {}).get("jobs", ())):
                    card_path = "/" + card_rel.lstrip("/")
                    dest = _override_path(out_dir, card_path)
                    if card_path in have and _same_file_bytes(source, dest):
                        size = _size(_lp(dest))
                        log("Override: %s (%.1f MB, full size — left as it "
                            "was: this build's copy is byte-identical to "
                            "the one already in the set)"
                            % (card_path, size / 1e6), "info")
                        written.append((card_path, size))
                        records.append(_override_record(dest, card_path, []))
                        if progress:
                            progress(len(by_file) + j, max(total, 1),
                                     "Keeping %s" % os.path.basename(card_path))
                        continue
                    os.makedirs(_lp(os.path.dirname(dest)), exist_ok=True)
                    shutil.copyfile(_lp(source), _lp(dest))
                    try:
                        # A grown game ELF is staged 0755; the emulator on a
                        # non-Windows host execs the override copy.
                        shutil.copymode(_lp(source), _lp(dest))
                    except OSError:
                        pass
                    size = _size(_lp(dest))
                    log("Override: %s (%.1f MB, full size — %s)"
                        % (card_path, size / 1e6,
                           _override_whole_why(card_rel, grow_plan)), "info")
                    written.append((card_path, size))
                    records.append(_override_record(dest, card_path, []))
                    delta.append((card_path, None))
                    if progress:
                        progress(len(by_file) + j, max(total, 1),
                                 "Writing %s" % os.path.basename(card_path))

                # Item 149: the modes' system-partition files (the pinned
                # runtime, the mode files, the port) are not games-partition
                # files, and the rig binds the set whole over the games tree -
                # so they go BESIDE the set, in "<set>-modes", for Try it to
                # hand the rig through PAD_MODE_SO and /dump.
                modes_out = _write_override_modes(
                    out_dir, (grow_plan or {}).get("modes"), log)

                # AND WHAT THE LAST BUILD LEFT THAT THIS ONE DOES NOT WANT: a
                # file the user has reverted is absent from the new set, and a
                # copy of it left behind would go on being bound over the card.
                # The run would look like it was testing the current edits
                # while playing an old one.
                current = {p for p, _n in written}
                removed = sorted(p for p in have if p not in current)
                for card_path in removed:
                    dead = _override_path(out_dir, card_path)
                    _safe_remove(dead)
                    _prune_empty_dirs(out_dir, os.path.dirname(dead))
            except BaseException:
                # Half a set is not a set.  A fresh one goes entirely, because
                # leaving it would cost the user their next Start too (the
                # folder would refuse to be cleared).  An updated one keeps its
                # files — they are still most of a set, and the next build
                # lays the stock bytes back over them — but the stub manifest
                # above stays, so nothing reuses or binds it until one works.
                if fresh:
                    _rmtree(out_dir)
                raise
            _stage_done(log, "writing the override files", t0)
        finally:
            _rmtree_grow_plan(grow_plan)
    finally:
        disk_f.close()

    st = os.stat(_lp(original_path))
    generation = os.urandom(6).hex()
    manifest = {
        "version": OVERRIDE_VERSION,
        # WHICH BUILD THIS IS, and which one it was patched out of, so the rig
        # can be as narrow as this function was: overrides.sh stages the set on
        # the Linux disk, and a set whose parent it already holds costs it the
        # bytes in OVERRIDE_DELTA rather than a copy of the whole thing.
        "generation": generation,
        "parent": parent,
        # The card these bytes were patched OUT OF.  A set built from one card
        # and bound over another is a corrupt title, so whoever launches has to
        # be able to tell — size+mtime is the same identity cardmount.sh's own
        # cache uses (item 34: David keeps byte-identical cards at two paths).
        "card": {"path": os.path.abspath(str(original_path)),
                 "size": st.st_size, "mtime": int(st.st_mtime)},
        # ...and the card they are bound OVER, whose game program the set's
        # carries (PAD-172).  The same card when no other one was named.
        "run_card": _card_identity(run_card or original_path),
        "assets": os.path.abspath(str(assets_dir)),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "counts": {"audio": counts[0], "video": counts[1],
                   "image": counts[2], "text": counts[3]},
        "audio_mode": audio_mode[0] if audio_mode else "",
        "valpatch": valpatch_mode[0] if valpatch_mode else "",
        "files": records,
        "removed": removed,
    }
    if modes_out:
        manifest["modes"] = modes_out
    # A project that HOLDS modes: which way the preview switch stood, so the
    # Emulate tab rebuilds this set when it changes (emulate_tab.
    # preview_modes_reason).  Nothing for a project without modes.
    try:
        from . import mode_write as _MW
        if _MW.held_modes(assets_dir):
            manifest["modes_preview"] = _mode_family_on()
    except Exception:                                   # noqa: BLE001
        pass
    _write_override_manifest(out_dir, manifest)
    # Item 149: the set's list of NEW files travels with the delta like a file of
    # the set (whole when this build has one, removed when the last one did), so a
    # stage brought forward by overrides.sh never keeps a stale list.
    new_delta, new_removed = [], []
    if (modes_out or {}).get("added"):
        new_delta.append(("/" + OVERRIDE_NEW, None))
    elif parent and ((previous or {}).get("modes") or {}).get("added"):
        new_removed.append("/" + OVERRIDE_NEW)
    _write_override_delta(out_dir, generation, parent, delta + new_delta,
                          removed + new_removed)
    patched = sum(n for _p, rs in delta if rs is not None for _o, n in rs)
    # By path, not by position: a grown file left as it was is in `written`
    # (it is part of the set) but has no line in the delta.
    _sizes = dict(written)
    copied = sum(_sizes.get(p, 0) for p, rs in delta if rs is None)
    log("%s the emulator override set in %s: %d file(s), %.0f MB written "
        "(%d sound(s), %d video(s), %d image(s), %d display string(s))."
        % ("Updated" if parent else "Built",
           _fmt_dur(time.monotonic() - t_all), len(written),
           (copied + patched) / 1e6,
           counts[0], counts[1], counts[2], counts[3]), "success")
    return counts, audio_mode, valpatch_mode, written


#: Beside an override set, the folder its modes' system-partition files go in.
OVERRIDE_MODES_SUFFIX = "-modes"
#: The runtime object's name in that folder: the name item 127's rig stage takes
#: (``tools/spike2_emu/modes/tryit.sh install <folder>``), so the folder installs
#: as it is. On the card the same bytes are ``mode.so``.
OVERRIDE_MODES_OBJECT = "pad_mode.so"


def _write_override_modes(out_dir, modes, log):
    """Item 149: lay the modes' p2 payload down in ``<out_dir>-modes`` (emptied
    first, removed when this build carries no modes) and return what
    ``overrides.json`` says about it, or ``None``.  The same payload a card
    build installs on the system partition, built by the same code."""
    import shutil
    dest = str(out_dir).rstrip("\\/") + OVERRIDE_MODES_SUFFIX
    _rmtree(dest)
    _write_override_new_list(out_dir, (modes or {}).get("added"))
    if not modes:
        return None
    os.makedirs(_lp(dest), exist_ok=True)
    pay = modes["payload"]
    files = []
    for src, name in ([(pay["so"], OVERRIDE_MODES_OBJECT)]
                      + [(c, os.path.basename(c)) for c in pay["cfgs"]]
                      + [(a, os.path.basename(a)) for a in pay.get("assets") or ()]
                      + [(a, os.path.basename(a)) for a in pay.get("extras") or ()]   # item 160: stock.cfg
                      + [(pay["port"], os.path.basename(pay["port"]))]):
        shutil.copyfile(_lp(src), _lp(os.path.join(dest, name)))
        files.append(name)
    log("Override: the modes' runtime, mode files and port in %s (%s)."
        % (dest, ", ".join(files)), "info")
    return {"dir": dest, "files": files, "names": list(modes.get("names") or ()),
            "added": list(modes.get("added") or ()),
            "end_sound": modes.get("end_sound"),
            "own_sounds": list(modes.get("own_sounds") or ()),
            "code_object": bool(modes.get("code_object"))}


def _override_whole_why(card_rel, grow_plan):
    """Why an override file is written whole, in the log's words. Item 149: a
    mode's new clip has no slot to outgrow, and the scenes and manifest the modes
    rewrite are rebuilt rather than grown."""
    modes = (grow_plan or {}).get("modes") or {}
    rel = str(card_rel).strip("/")
    if rel in [str(r).strip("/") for r in modes.get("added") or ()]:
        return "a new file the modes add"
    if rel in [str(r).strip("/") for r in modes.get("rewritten") or ()]:
        return "rebuilt whole for the modes"
    return "it outgrew its slot on the card"


#: In an override set, the list of files a stock card does not have (a mode's own
#: clip): the name and format item 127's Try it set uses and ``run_game.sh`` reads -
#: one games-partition path per line, ``#`` comments, LF - so the rig overlays their
#: directories instead of refusing a file it has nothing to bind over.
OVERRIDE_NEW = "overrides.new"


def _write_override_new_list(out_dir, added):
    """Item 149: write :data:`OVERRIDE_NEW` in the set for the modes' new files, or
    remove it when this build adds none (a stale list would overlay a directory for a
    file the set no longer holds)."""
    path = os.path.join(str(out_dir), OVERRIDE_NEW)
    rels = [str(r).strip("/") for r in (added or ()) if str(r).strip("/")]
    if not rels:
        _safe_remove(path)
        return []
    with open(_lp(path), "w", encoding="utf-8", newline="\n") as f:
        f.write("# files a stock card does not have: run_game.sh overlays their "
                "directories\n")
        for rel in rels:
            f.write(rel + "\n")
    return rels


def _override_path(out_dir, card_path):
    """Where a card file lands inside an override set.

    The set MIRRORS THE GAMES PARTITION, not the title directory: the ``.sidx``
    manifest an edit also rewrites lives at ``/spk/index/<title>.sidx``, beside
    the title rather than inside it, and a layout that could not express that
    would quietly drop the one file Stern's validator reads.
    """
    rel = card_path.strip("/").split("/")
    return os.path.join(out_dir, *rel)


def _card_identity(path):
    """``{path, size, mtime}`` - the identity an override manifest keeps for a
    card, the same size+mtime the rig's own card cache keys on."""
    st = os.stat(_lp(str(path)))
    return {"path": os.path.abspath(str(path)), "size": st.st_size,
            "mtime": int(st.st_mtime)}


#: More differing bytes than this between the picked card's game program and
#: the original's is not a build of the same program with PAD's in-place edits
#: in it (the validator bypass is 8 bytes, the sound count 4, a program text a
#: few hundred), so none of it is carried.
_CARRY_LIMIT = 256 * 1024


def _program_diff_runs(a, b, block=4096):
    """``[(offset, length), ...]`` where the equal-length *a* and *b* differ.
    Compared a block at a time first: two copies of one game program differ in
    a few words out of 8 MB, and a byte loop over all of it costs seconds."""
    runs = []
    for base in range(0, len(a), block):
        if a[base:base + block] == b[base:base + block]:
            continue
        i, end = base, min(base + block, len(a))
        while i < end:
            if a[i] == b[i]:
                i += 1
                continue
            j = i
            while j < end and a[j] != b[j]:
                j += 1
            runs.append((i, j - i))
            i = j
    return _merge_ranges(runs)


def _minus_ranges(runs, cover):
    """*runs* with every byte that *cover* spans taken out."""
    cover = _merge_ranges(cover)
    out = []
    for off, n in runs:
        pos, end = off, off + n
        for c_off, c_n in cover:
            if c_off + c_n <= pos or c_off >= end:
                continue
            if c_off > pos:
                out.append((pos, c_off - pos))
            pos = max(pos, c_off + c_n)
            if pos >= end:
                break
        if pos < end:
            out.append((pos, end - pos))
    return out


def _carry_run_card_program(reader, fw_node, by_file, grow_plan,
                            original_path, run_card, log):
    """Keep the game-program bytes the card the set RUNS ON was built with.

    Returns how many bytes were carried into the set's copy of the program.

    PAD-172 (a field report, v0.219.1): "if I uncheck the assets box it works, and
    if I recheck it, it fails again" - the game put up GAME VALIDATION ERROR,
    UPDATE SD CARD over attract, on a card PAD had built, but only with his
    edits applied on top.  Every override set carries the game program,
    because the validator bypass is written on every build, and since PAD-161
    that program is prepared from the card the project was EXTRACTED from:
    the stock program plus the bypass.  Bound over a built card, it replaced
    that card's own program, and with it everything the card's build had
    changed there for the rest of the card.  A card built with longer sounds
    is the case that shows: its grown sound bank counts every appended
    record as failed unless the program's count store is patched out
    (``valpatch.sound_count_overlay``), and nothing else in the program can
    stop that count raising the banner - the bypassed validator only reads
    it back.  Measured on the emulator, Godzilla LE 1.16, looking at Ball 1
    of a started game (attract never shows it): stock plus a set of ten
    pictures and a video is clean; that card built with two longer callouts
    is clean on its own; the set over the built card shows the banner; the
    set with this carry over the built card is clean again.

    So when *run_card* is another card than the original and its program is
    the same size (every in-place edit PAD makes to a program keeps its
    size), each byte it has that differs from the original's, and that none
    of this set's own program writes touch, is laid into the set's copy
    first.  The set's writes still go on top, so where both changed a byte,
    these edits win - the same rule as every other file on that card: what
    the edits change is theirs, what they leave alone is the card's.  The
    carried bytes join the file's write list, so the manifest's ranges hold
    them, the next build lays the original's bytes back over them before it
    decides again (the picked card may be another one by then), and the rig
    stages them with everything else.

    A program rebuilt whole - by that card's build (blip-free sounds, longer
    program text) or by these edits - has no offsets the other side shares,
    so nothing is carried and the log says what that can cost.  The set's
    ``.sidx`` record for the program is left as prepared: a card run never
    binds the ``.sidx`` (it sits beside the title), and only the bypassed
    validator ever reads it.
    """
    if fw_node is None or not run_card:
        return 0
    if (os.path.normcase(os.path.abspath(str(run_card)))
            == os.path.normcase(os.path.abspath(str(original_path)))):
        return 0
    fw_ib = bytes(fw_node["i_block"])
    key = next((p for p, (n, _w) in by_file.items()
                if bytes(n["i_block"]) == fw_ib), None)
    fw_rel = key.lstrip("/") if key else _card_rel_path(reader, fw_node)
    rebuilt = bool(fw_rel) and any(
        rel.lstrip("/") == fw_rel
        for rel, _src in (grow_plan or {}).get("jobs", ()))
    if key is None and not rebuilt:
        return 0            # no program in the set: the card's own one runs
    name = os.path.basename(str(run_card))
    try:
        with open(_lp(str(run_card)), "rb") as f:
            run_reader, run_fw, _img = _locate(f, _linux_partitions(run_card))
            picked = bytes(run_reader.read_file_bytes(run_fw))
    except Exception as e:                              # noqa: BLE001
        log("The game program on %s could not be read (%s), so this run uses "
            "the one prepared from %s. If that card was built with changes of "
            "its own to the program, they are not in this run."
            % (name, e, os.path.basename(str(original_path))), "warning")
        return 0
    stock = bytes(reader.read_file_bytes(fw_node))
    if picked == stock:
        return 0
    if rebuilt or len(picked) != len(stock):
        log("%s carries a game program its own build changed, and %s, so "
            "this run uses the one your edits bring. Anything that card's "
            "build needed in its program (longer sounds, blip-free sounds, "
            "longer program text) is not in it: if the game shows GAME "
            "VALIDATION ERROR or those come out wrong, build the card image "
            "to test the two together."
            % (name, "your edits rebuild the program" if rebuilt
               else "the two are different sizes"), "warning")
        return 0
    node, writes = by_file[key]
    runs = _minus_ranges(_program_diff_runs(picked, stock),
                         [(o, len(b)) for o, b in writes])
    total = sum(n for _o, n in runs)
    if not total:
        return 0
    if total > _CARRY_LIMIT:
        log("%s carries a game program that differs from the original's in "
            "%d bytes, which is not a build of the same program, so this run "
            "uses the one prepared from %s." % (
                name, total, os.path.basename(str(original_path))), "warning")
        return 0
    by_file[key] = (node, [(o, picked[o:o + n]) for o, n in runs]
                    + list(writes))
    from . import valpatch
    count = valpatch.sound_count_patched(picked) \
        and not valpatch.sound_count_patched(stock)
    log("Kept %d byte(s) of the game program, in %d place(s), that %s was "
        "built with and your edits do not change: the rest of that card was "
        "built to run with them%s."
        % (total, len(runs), name,
           " (among them the sound-count patch its longer sounds need; "
           "without it the game shows GAME VALIDATION ERROR)" if count
           else ""), "info")
    return total


def _write_override_manifest(out_dir, data):
    """Write *data* as the override set's manifest, replacing what is there.

    One writer for all three of them — the stub the build lays down before any
    bytes, the real manifest at the end, and the app's own stamp on top — so
    "what makes this folder an override set" is one line of code rather than
    three that can drift apart.
    """
    import json
    with open(_lp(os.path.join(str(out_dir), OVERRIDE_MANIFEST)), "w",
              encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def _override_reuse(out_dir, manifest, original_path):
    """The files of the set in *out_dir* that may be PATCHED, or ``None``.

    ``{card_path: record}`` when the set was built from this same card image
    and every file it names is still on disk exactly as the manifest left it
    (size and mtime); ``None`` when anything at all is off, which sends the
    caller back to building the set from scratch.

    All-or-nothing on purpose.  A set is only worth patching because nobody
    has touched it since it was written; the moment one file disagrees, "what
    is in this folder" is a question this manifest cannot answer, and guessing
    is how a run ends up playing a sound the user took back.
    """
    if not manifest or manifest.get("building"):
        return None
    if int(manifest.get("version") or 0) < OVERRIDE_VERSION \
            or not manifest.get("generation"):
        return None
    card = manifest.get("card") or {}
    try:
        st = os.stat(_lp(str(original_path)))
    except OSError:
        return None
    if os.path.normcase(str(card.get("path") or "")) \
            != os.path.normcase(os.path.abspath(str(original_path))) \
            or card.get("size") != st.st_size \
            or int(card.get("mtime") or 0) != int(st.st_mtime):
        return None
    have = {}
    for rec in manifest.get("files") or []:
        path = rec.get("path")
        if not path:
            return None
        try:
            fst = os.stat(_lp(_override_path(out_dir, path)))
        except OSError:
            return None
        if fst.st_size != rec.get("size") \
                or int(fst.st_mtime) != int(rec.get("mtime") or 0):
            return None
        have[path] = rec
    return have


def _same_file_bytes(a, b):
    """True when *a* and *b* are both files of the same size and the same
    bytes.  The size test first, because the common miss is a different
    length; the byte compare is chunked, never a whole-file read."""
    try:
        if not (os.path.isfile(_lp(a)) and os.path.isfile(_lp(b))):
            return False
        if os.path.getsize(_lp(a)) != os.path.getsize(_lp(b)):
            return False
        with open(_lp(a), "rb") as fa, open(_lp(b), "rb") as fb:
            while True:
                x = fa.read(1 << 20)
                y = fb.read(1 << 20)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


def _override_record(dest, card_path, ranges):
    """One file's line in the manifest: what it is, and what was put in it.

    The size and mtime are read back AFTER the writes because they are what
    the next build checks the file against, and *ranges* is what that build
    has to lay the card's own bytes back over before it applies its own.
    """
    st = os.stat(_lp(dest))
    return {"path": card_path, "size": st.st_size, "mtime": int(st.st_mtime),
            "ranges": [[o, n] for o, n in ranges]}


def _merge_ranges(ranges, slack=0):
    """Sorted, non-overlapping ``[(offset, length), ...]``.

    *slack* also joins ranges that are merely CLOSE, which is worth doing for
    the staging list: every range there costs a ``dd`` of its own, and copying
    the untouched megabyte between two edited sounds is cheaper than the
    process that would have avoided it.
    """
    out = []
    for off, n in sorted((int(o), int(x)) for o, x in ranges if int(x) > 0):
        if out and off <= out[-1][0] + out[-1][1] + slack:
            end = max(out[-1][0] + out[-1][1], off + n)
            out[-1] = (out[-1][0], end - out[-1][0])
        else:
            out.append((off, n))
    return out


_DELTA_SLACK = 1 << 20                  # "not worth a second dd"


def _delta_ranges(touched, size):
    """What the rig must copy for one file: ranges, or ``None`` for all of it.

    ``None`` when the file is new to the set, and also when so much of it
    changed that copying it whole is the cheaper instruction — a set rebuilt
    from a different extract should not be staged as ten thousand seeks.
    """
    if touched is None:
        return None
    wide = _merge_ranges(touched, slack=_DELTA_SLACK)
    if sum(n for _o, n in wide) * 2 >= size:
        return None
    return wide


def _prune_empty_dirs(root, path):
    """Remove *path* and any parents it leaves empty, stopping at *root*.

    A set that loses its last ``/spk/index`` file should lose the folder too:
    the rig walks the staged tree, and an empty directory in it is a question
    the next reader of this code should not have to answer.
    """
    root, path = os.path.abspath(str(root)), os.path.abspath(str(path))
    while path.startswith(root) and path != root:
        try:
            os.rmdir(_lp(path))
        except OSError:
            return
        path = os.path.dirname(path)


def _restore_stock(disk_f, reader, node, dest, ranges):
    """Put the card's own bytes back over *ranges* of a staged override file.

    The undo half of patching a set in place: whatever the last build wrote
    into this file is overwritten with what the card holds there, so an edit
    the user has since taken back leaves nothing of itself behind.  Read
    through the same extent map the writes were resolved through, which is
    what makes it exact rather than a guess.
    """
    if not ranges:
        return
    with open(_lp(dest), "r+b") as f:
        for off, length in ranges:
            pos = off
            for disk, n in reader.disk_ranges(node, off, length):
                disk_f.seek(disk)
                buf = disk_f.read(n)
                if len(buf) != n:
                    raise OSError("the card image ended early at 0x%x" % disk)
                f.seek(pos)
                f.write(buf)
                pos += n


def _write_override_delta(out_dir, generation, parent, delta, removed):
    """Write :data:`OVERRIDE_DELTA`: what changed since the parent generation.

    Plain lines rather than JSON because the reader is a shell script
    (``tools/spike2_emu/overrides.sh``), and the path goes LAST on every line
    so a card path with a space in it still parses there::

        generation <id>
        parent <id, or - when this set was built from scratch>
        remove <path>
        whole <path>
        range <offset> <length> <path>

    Paths are relative to the set, which mirrors the games partition, so the
    script joins them to either side with nothing to translate.
    """
    lines = ["# PAD override set: what changed since the parent generation.",
             "# tools/spike2_emu/overrides.sh stages only this much of it.",
             "generation %s" % generation,
             "parent %s" % (parent or "-")]
    for card_path in removed:
        lines.append("remove %s" % card_path.strip("/"))
    for card_path, ranges in delta:
        rel = card_path.strip("/")
        if ranges is None:
            lines.append("whole %s" % rel)
        else:
            for off, n in ranges:
                lines.append("range %d %d %s" % (off, n, rel))
    # LF, always: a shell inside WSL reads this, and a CR at the end of a line
    # there is part of the path.
    with open(_lp(os.path.join(str(out_dir), OVERRIDE_DELTA)), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return lines


def stamp_override_manifest(out_dir, **fields):
    """Merge *fields* into an existing override manifest.

    For the facts only the CALLER can know, and only once the set is built:
    the app stamps its "have the edits moved since?" fingerprint here, and it
    has to be taken AFTER the build, because building writes the hash cache
    back into the assets folder it fingerprints.  Silent no-op when there is
    no manifest — a set that failed to build has nothing to stamp.
    """
    data = read_override_manifest(out_dir)
    if not data:
        return {}
    data.update(fields)
    return _write_override_manifest(out_dir, data)


def read_override_manifest(out_dir):
    """The manifest of the override set in *out_dir*, or ``{}``.

    Best-effort by design: a missing, half-written or unreadable manifest means
    "there is no usable set here", which every caller treats as "build one",
    never as an error.
    """
    import json
    try:
        with open(_lp(os.path.join(str(out_dir), OVERRIDE_MANIFEST)),
                  encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _rmtree_grow_plan(grow_plan):
    """Remove the scratch dir a grow plan carries (the rebuilt firmware), if any.

    ``_compute_patches`` hands its lifetime to whoever consumes the plan, so
    every path out of that consumer has to come through here.
    """
    d = (grow_plan or {}).get("cleanup")
    if d:
        _rmtree(d)


def _expand_card(original_path, output_path, parts, target, log, cancel):
    """Grow the build at *output_path* to the *target* card class
    (card_size.py) once the in-place patches are in and before any file is
    copied on whole, then prove the resize moved nothing the build or its
    next update relies on.  Returns True when it grew, False when the user
    cancelled (the output is discarded).  Any failure discards the output
    too: a card the user asked to be bigger is never handed back at the
    original's size.

    The filesystem tools run with the clock pinned to the original's own
    games partition (the clock item 149's pinned deliveries use), so the
    same project grows to the same bytes on every build."""
    from ...core import ext4_grow
    from . import card_size as _cs
    t0 = time.monotonic()
    try:
        epoch = ext4_grow.partition_epoch(original_path,
                                          _cs.P3_START * _cs.SECTOR)
    except Exception:  # noqa: BLE001 - an unpinned grow is still a valid one
        epoch = None
    try:
        _cs.expand_image(output_path, target, log=log, cancel=cancel,
                         epoch=epoch)
        moved = _cs.check_blocks_unmoved(original_path, output_path, parts,
                                         log=log)
        if moved:
            raise _cs.CardSizeError(
                "growing the games partition moved %s, and the build's "
                "patches were placed by where it was" % moved)
    except _cs.Cancelled:
        _discard_output(output_path)
        log("Cancelled while making the card a %s card; nothing was built."
            % _cs.words(target), "warning")
        return False
    except BaseException as e:
        _discard_output(output_path)
        if isinstance(e, _cs.CardSizeError):
            raise _cs.CardSizeError(
                "The card could not be made a %s card, so nothing was built: "
                "%s" % (_cs.words(target), e)) from e
        if isinstance(e, OSError):
            # a full or non-sparse destination drive lands here
            raise _cs.CardSizeError(
                "The card could not be made a %s card, so nothing was built: "
                "writing the bigger image failed (%s). A %s image needs room "
                "on the drive it is built on."
                % (_cs.words(target), e, _cs.words(target))) from e
        raise
    _stage_done(log, "making the card a %s card" % _cs.words(target), t0)
    return True


def _grow_video_slots(image_or_device, grow_plan, log):
    """Copy every file this write replaces WHOLE onto the card through the ext4
    driver — full-size videos, a re-serialised scene, the rebuilt game program,
    a grown sound bank.  A growth failure is surfaced loudly but does NOT
    discard the rest of the write: the in-place edits already landed, and the
    files that didn't land keep their stock content until the user retries.
    Returns how many actually landed so the caller can report honest counts."""
    if not grow_plan or not grow_plan.get("jobs"):
        return 0
    return _grow_whole(image_or_device, grow_plan["offset"],
                       grow_plan["jobs"], log, epoch=grow_plan.get("epoch"),
                       hint_sizes=grow_plan.get("hint_sizes"),
                       report=grow_plan)


def _grow_whole(image_or_device, part_offset, jobs, log, epoch=None,
                hint_sizes=None, report=None):
    """Copy ``[(card_rel, source), ...]`` whole onto the partition at
    *part_offset* through the ext4 driver and return how many landed (they
    land in order, so it is the first N).  Failures are logged, never
    raised — the caller reports honest counts.

    With *epoch* (a build carrying modes, item 149) the copies go through
    :func:`.ext4_grow.grow_files_pinned` with the clock fixed, so the same
    project and original give a byte-identical card.  *report*, a dict,
    gets ``no_space`` set when the copies stopped because the partition ran
    out of room, so what the caller says next points at making room."""
    from ...core import ext4_grow
    # The default 1800 s is generous for a handful of videos and thin for a
    # 1-2 GB sound bank on a slow disk (macOS writes it through debugfs).
    # Scale by the bytes actually being copied, and never go below the default.
    total = 0
    for _rel, src in jobs:
        try:
            total += os.path.getsize(_lp(src))
        except OSError:
            pass
    timeout = max(1800, int(total / (2 << 20)) + 600)   # ~2 MB/s plus slack
    try:
        if epoch is not None:
            return ext4_grow.grow_files_pinned(image_or_device, part_offset,
                                               jobs, epoch, log=log,
                                               timeout=timeout)
        return ext4_grow.grow_files(image_or_device, part_offset, jobs,
                                    log=log, timeout=timeout)
    except ext4_grow.Ext4GrowUnavailable as e:
        log("Could not write the full-size file(s): %s" % e, "warning")
        return 0
    except ext4_grow.Ext4GrowError as e:
        if report is not None and isinstance(e, ext4_grow.Ext4GrowNoSpace):
            report["no_space"] = True
        log("Writing the full-size file(s) failed: %s%s"
            % (e, _bigger_card_hint(e, image_or_device, part_offset,
                                    hint_sizes)),
            "error")
        return getattr(e, "grown", 0)


def _bigger_card_hint(err, image, part_offset, sizes=None):
    """The other way out of a full games partition (card_size.py): when the
    SD card in the machine is bigger than the image, build for it.  Said only
    when that could help: the failure was for space, on the games partition
    (the system partition never grows), of an image file laid out like
    Stern's that is smaller than the biggest class, on a computer that can
    grow one.  *sizes*, when the build knows them, are the classes the Write
    tab offers for its ORIGINAL (card_size.offered): an original it refuses
    (a pending journal, a multi-boot card) is never pointed at the option.

    When the failure carries its numbers (``need`` / ``avail``), the ONE
    smallest size whose room holds the build is named, or the biggest is
    said to be too small too; without them every bigger size is listed.  A
    port's build (card_size.size_fixed) can't take a size, so it is told to
    build the card on its own for it."""
    from ...core import ext4_grow
    from . import card_size as _cs
    if not isinstance(err, ext4_grow.Ext4GrowNoSpace) or not _cs.supported():
        return ""
    fixed = _cs.size_fixed()
    if int(part_offset) != _cs.P3_START * _cs.SECTOR:
        return ""
    try:
        with open(_lp(image), "rb") as f:
            cls = _cs.class_of(_cs.read_layout(f).laid_out)
    except Exception:  # noqa: BLE001 - a device, a multi-boot card, unreadable
        return ""
    bigger = [c for c in (_cs.CARD_SIZES if sizes is None else sizes)
              if _cs.CARD_SIZES[c] > _cs.CARD_SIZES.get(cls, 1 << 62)]
    if not bigger:
        return ""
    bigger.sort(key=_cs.CARD_SIZES.get)
    need = getattr(err, "need", None)
    avail = getattr(err, "avail", None)
    if need is not None and avail is not None:
        # the room each size adds to what the copy measured, on this card
        try:
            room = [(c, int(avail) + _cs.room_gained(image, c)) for c in bigger]
        except Exception:  # noqa: BLE001 - unreadable: list them instead
            room = None
        if room:
            for c, have in room:
                if int(need) <= have and fixed:
                    return ("  Or, if the SD card in that machine is %s or "
                            "bigger, %s." % (_cs.words(c), _cs.bigger_card(
                                c, have, fixed=True)))
                if int(need) <= have:
                    return ("  Or, if the SD card in the machine is %s or "
                            "bigger, build it for a %s SD card: SD card size "
                            "on the Write tab grows the games partition, which "
                            "then has %s free."
                            % (_cs.words(c), _cs.words(c),
                               _cs.size_words(have)))
            c, have = room[-1]
            return ("  Even built for a %s SD card%s the games partition would "
                    "have only %s free, so something has to come out."
                    % (_cs.words(c), "" if fixed
                       else " (SD card size on the Write tab)",
                       _cs.size_words(have)))
    if fixed:
        return ("  Or, if the SD card in that machine is bigger than this "
                "image, %s." % _cs.bigger_card(bigger[0], fixed=True))
    return ("  Or, if the SD card in the machine is bigger than this image, "
            "build for a bigger card: SD card size on the Write tab (%s) "
            "grows the games partition to fill it."
            % " or ".join(_cs.words(c) for c in bigger))


def _grow_boot_screen(image_or_device, grow_plan, log):
    """Copy a boot screen that outgrew its file onto the OS partition through
    the ext4 driver: :func:`_grow_video_slots`' route, on the partition the
    plan's ``boot`` entry names.  Returns how many landed."""
    boot = (grow_plan or {}).get("boot")
    if not boot or not boot.get("jobs"):
        return 0
    from ...core import ext4_grow
    try:
        return ext4_grow.grow_files(image_or_device, boot["offset"],
                                    boot["jobs"], log=log)
    except ext4_grow.Ext4GrowUnavailable as e:
        log("Could not write the boot screen: %s" % e, "warning")
        return 0
    except ext4_grow.Ext4GrowError as e:
        log("Writing the boot screen failed: %s" % e, "error")
        return getattr(e, "grown", 0)


def revert_assets(source_path, assets_dir, rels, log=None, progress=None,
                  cancel=None, open_disk=None, partitions=None, label=None):
    """Re-derive the pristine bytes of *rels* from the source card and write them
    over the matching files in *assets_dir*.

    The fallback for "Revert" when a file has no ``.orig`` snapshot (edited
    before snapshots existed, or hand-edited so it never matched the baseline).
    *rels* are ``/``-separated asset paths.  Audio (``audio/idxNNNN.wav`` and its
    auto-named twins) is re-decoded from the firmware codec; loose videos /
    images are re-extracted.  Anything else (e.g. per-category music banks) is
    reported as un-revertable so the caller can tell the user to re-extract.

    ``open_disk`` (zero-arg → seekable stream) and ``partitions`` override how the
    card is opened / where its ext partitions are — Direct-SD passes a
    ``RawDeviceFile`` + ``device_partitions``; the default reads ``source_path``.

    Returns ``(reverted, failed)`` — two lists of rel paths.
    """
    import shutil
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)

    # Bucket the requested rels by how each is recovered.
    audio_idx = {}            # idx -> rel (target to overwrite)
    media_rels = []           # video/* + images/* loose files
    failed = []
    for rel in rels:
        top = rel.split("/", 1)[0]
        base = os.path.splitext(os.path.basename(rel))[0]
        if top == "audio":
            if _MUSIC_WAV_RE.search(base):
                failed.append(rel)           # music-bank revert not supported here
                continue
            idx = _wav_idx(base)
            if idx is not None:
                audio_idx[idx] = rel
            else:
                failed.append(rel)
        elif top in ("video", "images"):
            media_rels.append(rel)
        else:
            failed.append(rel)

    if not audio_idx and not media_rels:
        return [], failed

    reverted = []
    work = _work_dir(label, base="spike2_revert_")
    emu = None
    disk_f = (open_disk() if open_disk is not None
              else open(_lp(source_path), "rb"))
    try:
        parts = partitions if partitions is not None else _linux_partitions(
            source_path)
        gr_path, img_path, reader, _fw, _img = _extract_inputs(
            disk_f, parts, work, log)
        if cancel():
            return reverted, failed

        if audio_idx:
            from .spike2.emulator import Spike2Emu, audio_decode_supported
            if not audio_decode_supported(gr_path):
                log("This title's audio can't be re-decoded for revert; "
                    "re-extract to reset those sounds.", "warning")
                failed.extend(audio_idx.values())
            else:
                log("Re-decoding %d original sound(s) from the card..."
                    % len(audio_idx), "info")
                emu = Spike2Emu(gr_path, img_path)
                emu.boot()
                params = _load_or_derive_params(
                    emu, gr_path, img_path, log, progress)
                want = set(audio_idx)
                selected = [p for p in params if p["idx"] in want]
                total = len(selected)
                for i, p in enumerate(selected):
                    if cancel():
                        break
                    if progress:
                        progress(i, total, "Reverting sound %d/%d" % (i + 1, total))
                    rel = audio_idx[p["idx"]]
                    try:
                        r = emu.decode(p, cancel=cancel)
                    except Exception as e:
                        log("idx %d: revert decode failed (%s)" % (p["idx"], e),
                            "warning")
                        failed.append(rel)
                        continue
                    if r is None:
                        failed.append(rel)
                        continue
                    L, R, stereo = r
                    _write_wav(os.path.join(assets_dir, *rel.split("/")),
                               L, R, stereo)
                    reverted.append(rel)
                # idx the firmware didn't list at all can't be recovered here.
                got = {audio_idx[p["idx"]] for p in selected}
                failed.extend(r for r in audio_idx.values()
                              if r not in got and r not in failed)
                emu.close(); emu = None

        if media_rels and not cancel():
            log("Re-extracting %d original media file(s) from the card..."
                % len(media_rels), "info")
            want_video = any(r.startswith("video/") for r in media_rels)
            want_images = any(r.startswith("images/") for r in media_rels)
            try:
                if want_video:
                    extract_videos(reader, work, log=log, cancel=cancel)
                if want_images:
                    extract_images(reader, work, log=log, cancel=cancel)
                if any(r.startswith("images/%s/" % _BOOT_IMAGE_SUBDIR)
                       for r in media_rels):
                    extract_boot_images(disk_f, parts, work,
                                        games_base=reader.base, log=log)
            except Exception as e:
                log("Media re-extract failed (%s)." % e, "warning")
            for rel in media_rels:
                src = os.path.join(work, *rel.split("/"))
                dst = os.path.join(assets_dir, *rel.split("/"))
                if os.path.isfile(src):
                    try:
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        reverted.append(rel)
                    except OSError:
                        failed.append(rel)
                else:
                    failed.append(rel)
        return reverted, failed
    finally:
        if emu is not None:
            emu.close()
        disk_f.close()
        _rmtree(work)


def device_partitions(device_path, partition_override=None, log=None):
    """Confirm a raw device is a Spike 2 card and return its ext partitions
    ``[(byte_offset, byte_size), ...]`` (largest first) for ``_locate`` to
    search — the Direct-SD twin of :func:`formats.linux_partitions`.

    Reads only the device's MBR (sector-aligned).  Honors an optional 1-based
    MBR partition override.  Raises ``RuntimeError`` if the device can't be read
    (e.g. without Administrator) or doesn't carry the Spike 2 signature, so we
    never extract/write the wrong drive."""
    log = log or (lambda *a, **k: None)
    from .formats import (is_spike_card_parts, linux_partitions_from_parts,
                          parse_mbr_partitions_bytes)
    from ...core.rawdevice import read_mbr

    mbr = read_mbr(device_path)
    if not mbr:
        raise RuntimeError(
            "Couldn't read the selected drive (%s). On Windows, Direct SD needs "
            "Administrator — re-launch as administrator and try again."
            % device_path)
    parts_raw = parse_mbr_partitions_bytes(mbr)
    if not is_spike_card_parts(parts_raw):
        raise RuntimeError(
            "The selected drive isn't a Stern Spike 2 SD card — its partition "
            "table doesn't match the Spike 2 signature. Double-check the drive "
            "selection (and that the card was removed from the machine and "
            "connected to this PC).")
    if partition_override is not None:
        match = [(lba * 512, sectors * 512)
                 for (idx, _t, lba, sectors) in parts_raw
                 if idx == partition_override - 1]
        if match:
            log("Using forced partition #%d." % partition_override, "info")
            return match
        log("Forced partition #%d not found on the card; auto-discovering "
            "instead." % partition_override, "warning")
    return linux_partitions_from_parts(parts_raw)


def write_device(device_path, assets_dir, log=None, progress=None, cancel=None,
                 phase=None, partition_override=None):
    """Direct-SD twin of :func:`write_image`: patch the user's edits straight
    onto the physical card (size-neutral, in place) — no intermediate image.

    Verifies the device carries the Spike 2 partition signature first (so we
    never write to the wrong drive), computes the identical patch set via
    :func:`_compute_patches`, then writes those exact byte ranges back to the
    card with a sector-aligned :class:`.rawdevice.RawDeviceFile`.  Needs the
    Administrator/root handle the GUI already gates the Direct-SD button on."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    phase = phase or (lambda i: None)
    from ...core.rawdevice import RawDeviceFile

    phase(0)  # Scan
    from . import card_size as _cs
    if _cs.requested():
        log("SD card size applies to building an image; writing straight to "
            "the card keeps the card's own partitions.", "info")
    parts = device_partitions(device_path, partition_override, log=log)

    with RawDeviceFile(device_path, writable=False) as disk_f:
        writes, counts, _grow_plan, audio_mode, valpatch_mode = _compute_patches(
            disk_f, parts, assets_dir, log, progress, cancel, phase=phase,
            dest_is_device=True)
    # Direct-SD can't grow files, so a plan here carries nothing to copy — but
    # it still owns a scratch dir if one was made, and nothing else will free it.
    _rmtree_grow_plan(_grow_plan)
    if writes is None:                          # cancelled mid-compute
        return (0, 0, 0, 0), None, None

    phase(2)  # Write to SD card
    log("Writing changes directly to the SD card (in place)...", "info")
    if progress:
        progress(0, 0, "Writing to SD card...")
    with RawDeviceFile(device_path, writable=True) as out:
        _apply_writes(out, writes)
        out.flush()
    n_audio, n_video, n_image, n_text = counts
    n_stock = getattr(counts, "stock_modes", 0)
    log("Wrote to SD card: %d sound(s), %d video(s), %d image(s), "
        "%d display string(s)%s."
        % (n_audio, n_video, n_image, n_text,
           ", %d number(s) of the game's own modes" % n_stock
           if n_stock else ""), "success")
    # Return the per-type breakdown (see write_image) so the completion dialog
    # names what changed rather than a bare total, plus the audio build mode --
    # Direct-SD can never grow game_real, so a card with re-encoded sounds is
    # always a standard (scrap-remains) build and the dialog should say so --
    # and the validator status, which applies to a card write just the same.
    return counts, audio_mode, valpatch_mode


# --------------------------------------------------------------------------
# encode helpers
# --------------------------------------------------------------------------
def _read_wav_any(path, np):
    """Decode *path* to ``(samples, channels, rate)`` with samples an int64
    array of interleaved frames scaled to the 16-bit range — whatever the
    file's own bit depth.

    Replacement WAVs come straight from the user's editor, and editors default
    to all sorts of PCM: a tester's callouts exported at their DAW's default
    bit depth played as pure STATIC, because this loader used to interpret
    every file as 16-bit (24-bit words read as garbage int16 pairs — while the
    one file they happened to export as 16-bit worked, which pointed everyone
    at the sample rate instead).  Sample rate was never the problem (any rate
    resamples fine); bit depth was.  Handles 8/16/24/32-bit integer PCM via
    the wave module and 32/64-bit IEEE float (which the wave module rejects)
    via a minimal RIFF parse."""
    try:
        w = wave.open(path, "rb")
        n = w.getnframes(); ch = w.getnchannels(); sw = w.getsampwidth()
        sr = w.getframerate()
        raw = w.readframes(n)
        w.close()
        if sw == 2:
            a = np.frombuffer(raw, "<i2").astype(np.int64)
        elif sw == 1:                       # unsigned 8-bit
            a = (np.frombuffer(raw, np.uint8).astype(np.int64) - 128) << 8
        elif sw == 3:                       # packed 24-bit: keep the top 16
            b = np.frombuffer(raw, np.uint8)
            b = b[: len(b) // 3 * 3].reshape(-1, 3)
            a = (b[:, 1].astype(np.int64)
                 | (b[:, 2].astype(np.int64) << 8))
            a = np.where(a & 0x8000, a - 0x10000, a)
        elif sw == 4:                       # 32-bit int: keep the top 16
            a = np.frombuffer(raw, "<i4").astype(np.int64) >> 16
        else:
            raise ValueError("unsupported WAV sample width: %d" % sw)
        return a, ch, sr
    except wave.Error:
        pass
    # IEEE-float WAV (format 3 / EXTENSIBLE float): minimal RIFF walk.
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file: %s" % path)
    fmt = None
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        ln = struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + ln]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data" and fmt is not None:
            tag, ch, sr, _br, _ba, bits = struct.unpack_from("<HHIIHH", fmt, 0)
            if tag == 0xFFFE and len(fmt) >= 26:
                tag = struct.unpack_from("<H", fmt, 24)[0]
            if tag == 3 and bits in (32, 64):
                a = np.frombuffer(body, "<f4" if bits == 32 else "<f8")
                a = np.clip(a.astype(np.float64), -1.0, 1.0)
                return (np.round(a * 32767.0).astype(np.int64), ch, sr)
            raise ValueError(
                "unsupported WAV format tag %d (%d-bit)" % (tag, bits))
        pos += 8 + ln + (ln & 1)
    raise ValueError("no data chunk found in %s" % path)


def _load_wav(path, want_stereo, np):
    a, ch, sr = _read_wav_any(path, np)
    a = a[: len(a) // ch * ch].reshape(-1, ch)
    if ch > 2:                              # downmix surround to stereo L/R
        a = a[:, :2]
        ch = 2
    if sr != 44100 and len(a):
        idx = np.clip((np.arange(int(len(a) * 44100 / sr)) * sr / 44100).astype(int),
                      0, len(a) - 1)
        a = a[idx]
    if want_stereo:
        return a if ch == 2 else np.repeat(a, 2, axis=1)
    return a.mean(1).astype(np.int64) if ch == 2 else a[:, 0]


def _fit(a, length, np, fade_ms=5.0):
    """Truncate / zero-pad *a* to exactly *length* samples, with a short
    raised-cosine fade from zero at the head and to zero at the tail of the
    actual audio (the truncation point, or the last real sample before the
    zero padding).

    Every caller feeds user replacement audio, and audio whose edge is
    non-zero — cut mid-waveform, or carrying DC offset — is a step the
    machine renders as an audible click at that edge of the callout
    (a tester, real-HW, both ends; stock sounds start and end at silence so
    stock never clicked).  The symmetric fade also lands looping music at
    zero on both sides of the loop point.  Landing the edge at zero isn't
    enough on real HW — a 5 ms slam from zero to a hot sample still pops,
    where stock eases in over 40-77 ms — so the callers pass a stock-length
    *fade_ms* by default (see :func:`_declick_params`); ~5 ms is the legacy
    minimum, used only when the user unticks auto-fade."""
    a = np.asarray(a, np.int64)
    if len(a) > length:
        a = a[:length]
    # Halve on short clips so head + tail fades can't overlap.
    n = min(len(a) // 2, int(round(fade_ms * 44.1)))
    if n > 1:
        ramp = 0.5 + 0.5 * np.cos(np.linspace(0.0, np.pi, n))
        a = np.concatenate(
            [np.round(a[:n] * ramp[::-1]).astype(np.int64),
             a[n:len(a) - n],
             np.round(a[len(a) - n:] * ramp).astype(np.int64)])
    if len(a) < length:
        a = np.concatenate([a, np.zeros(length - len(a), np.int64)])
    return a


def _amplitude_fit(samples, rng, np, headroom=0.97):
    pk = int(np.abs(samples).max()) if len(samples) else 0
    if pk <= 0:
        return samples
    return (samples.astype(np.float64) * (rng * headroom / pk)).astype(np.int64)


# ---- match the replacement's loudness to the sound it replaces -----------
#
# Peak-normalizing lands every replacement at one fixed PEAK, but a peak says
# nothing about loudness: stock callouts are broadcast-compressed voice (high
# RMS for their peak — Godzilla's mono callouts measure a crest factor of
# ~2.6), while a home-recorded voiceover normalized to the very same peak
# carries far less energy, and a single stray transient (a lip smack, a desk
# knock) is enough to hold the whole recording down.  A tester's custom
# callouts came out clearly quieter than the stock sounds around them ("I
# will have to crank up the volume"), which is that gap.
#
# The honest reference is the sound being replaced: decode the stock slot,
# measure its active-speech RMS, and gain the replacement to the same figure.
# The subtlety — and the reason the first cut of this was a measured no-op —
# is that a gain capped at the peak ceiling IS the peak-normalize gain
# whenever the peak is a transient, i.e. in exactly the case worth fixing.
# Reaching stock's energy therefore means letting the transient past the
# ceiling and limiting it, which is what stock itself did upstream.  So:
# match the RMS, then soft-knee limit (smooth, monotonic, asymptotic to the
# ceiling) so nothing hard-clips.  Matching runs both ways — a hot music clip
# dropped on a quiet callout slot is brought DOWN to its neighbours' level —
# and the gain is bounded absolutely (_MATCH_MAX_GAIN) so a near-dead track
# is never amplified into its own noise floor.  Measured on a real Godzilla
# card: +5 dB on a transient-peaked recording, +9.5 dB on a quiet one with
# several transients, -1.5 dB on a hot compressed source, and no change at
# all on material already at stock level.  PAD_STERN_MATCH_LOUDNESS=0
# restores the plain peak cap (rides the environment into the encode workers
# like the other audio levers).
_MATCH_CEILING = 0.97          # peak ceiling (stock reaches 1.0 of the range)
_MATCH_MIN_ORIG_PEAK = 0.02    # orig quieter than 2% of range: not a reference
_MATCH_KNEE = 0.70             # limiting starts at 70% of the ceiling
# Absolute bound on the gain, NOT a bound relative to peak-normalizing: a
# relative cap binds hardest exactly when the peak is a transient, which is
# the one case worth fixing (measured: it held a +5 dB correction down to
# +0 dB).  20x keeps a whisper or a near-dead track from being amplified into
# its own noise floor while leaving every real recording room to reach stock.
_MATCH_MAX_GAIN = 20.0

# How far the user may push a replacement off the level the mode picked
# ("Replacement loudness" in Advanced audio options).  Matching is scale-
# INVARIANT by construction — the gain is orms/arms, so the output lands on
# stock's energy no matter how the source was mixed — which means remixing a
# track hotter changes the encoded result by literally nothing (a tester,
# Godzilla music imports: "I mixed them loud but the edit didn't seem to make a
# big change").  That is correct for a callout dropped into a bank of callouts
# and wrong for somebody who wants his music to sit ABOVE the stock bed, so the
# offset is the one lever that survives the match.  +/-12 dB: beyond that the
# soft limiter is doing all the work and the result is distortion, not level.
_MATCH_GAIN_DB_MAX = 12.0


def _match_loudness_enabled():
    return os.environ.get("PAD_STERN_MATCH_LOUDNESS") != "0"


def _match_gain_db():
    """User loudness offset in dB (``PAD_STERN_MATCH_GAIN_DB``; GUI: Advanced
    audio options -> "Replacement loudness"), clamped to
    ±:data:`_MATCH_GAIN_DB_MAX`.  0.0 = the mode's own level, i.e. the shipped
    behavior."""
    ov = _env_float("PAD_STERN_MATCH_GAIN_DB")
    if ov is None:
        return 0.0
    return max(min(ov, _MATCH_GAIN_DB_MAX), -_MATCH_GAIN_DB_MAX)


def _slot_gain_db(offset_db):
    """Total dB for one slot: the build-wide offset plus that slot's own
    per-clip offset, clamped to the same ±:data:`_MATCH_GAIN_DB_MAX` ceiling.

    The build-wide number is the everyday setting and moves every replacement
    together, which is the whole complaint the per-clip column answers ("will
    the sound boost affect every single clip? it looks like if I change the
    setting on one, it changed it on another one too" — a tester, Godzilla).
    Per-clip is a nudge RELATIVE to it, so a project set to +3 overall with one
    song at +4 lands that song at +7 and everything else stays where it was."""
    return max(min(_match_gain_db() + float(offset_db), _MATCH_GAIN_DB_MAX),
               -_MATCH_GAIN_DB_MAX)


def _slot_gain_maps(assets_dir):
    """Per-clip loudness offsets for *assets_dir*, as ``({idx: total_db},
    {(cid, idx): total_db})`` — cat-0 sounds and music-bank songs.

    Read from the folder's ``.staged_changes.json`` (``"audio_levels"``: ``{rel
    path -> dB}``, written by the Replace Audio tab's Level column) rather than
    threaded through the write call, exactly like the video tab's originals
    map.  Keyed off the ``idxNNNN`` / ``music_catNN_MMMM`` stem so an
    Auto-transcribe rename between setting the level and building keeps it.

    Only slots that actually asked for something appear: an empty map means
    every sound takes the untouched :func:`_match_gain_db` path and the build
    is byte-identical to one from a folder that never saw this feature."""
    from ...core import staged_changes as _sc
    levels = (_sc.load(assets_dir) or {}).get("audio_levels") or {}
    by_idx, by_music = {}, {}
    for rel, db in levels.items():
        try:
            db = float(db)
        except (TypeError, ValueError):
            continue
        if not db:
            continue
        stem = os.path.splitext(os.path.basename(str(rel)))[0]
        m = _MUSIC_NAME_RE.search(stem)
        if m:
            by_music[(int(m.group(1)), int(m.group(2)))] = _slot_gain_db(db)
            continue
        idx = _wav_idx(stem)
        if idx is not None:
            by_idx[idx] = _slot_gain_db(db)
    return by_idx, by_music


def _grow_priority_idxs(assets_dir):
    """Ordered cat-0 idxs the user chose to keep whole when the sound bank
    can't hold every longer song (item PAD-181).

    Read from ``.staged_changes.json`` (``"grow_keep_whole"``: a list of rel
    paths, written by the Replace Audio tab's right-click "Keep this song
    whole..." toggle) the same way :func:`_slot_gain_maps` reads the Level
    column, so it is not threaded through the write call and survives an
    Auto-transcribe rename (matched by the ``idxNNNN`` stem).  The list's order
    is the user's priority.  An empty list restores the old slot-order pick, so
    a folder that never used the feature builds byte-identically."""
    from ...core import staged_changes as _sc
    rels = (_sc.load(assets_dir) or {}).get("grow_keep_whole") or []
    out, seen = [], set()
    for rel in rels:
        stem = os.path.splitext(os.path.basename(str(rel)))[0]
        idx = _wav_idx(stem)
        if idx is not None and idx not in seen:
            out.append(idx)
            seen.add(idx)
    return out


def _fmt_gain_map(gains, cap=12):
    """``idx 6 +3 dB, idx 21 -2 dB, … and N more`` for the build log."""
    items = sorted(gains.items(), key=lambda kv: str(kv[0]))
    out = ", ".join("%s %+.0f dB" % ("idx %s" % (k,) if not isinstance(k, tuple)
                                     else "music_cat%02d_%04d" % k, v)
                    for k, v in items[:cap])
    if len(items) > cap:
        out += ", and %d more" % (len(items) - cap)
    return out


def _loudness_log_phrase():
    """One sentence for the build log describing how replacements are levelled,
    including the "your own mix level is not what comes out" part that a
    scale-invariant match makes invisible."""
    db = _match_gain_db()
    off = ("" if not db else
           ", then %+.1f dB" % db)
    if _match_loudness_enabled():
        return ("matched to the level of each sound being replaced%s (the "
                "level you mixed your file at is not carried over; change "
                "\"Replacement loudness\" in Advanced Audio Options to sit "
                "louder or quieter than stock)" % off)
    return ("each replacement normalized to full scale%s, ignoring the level "
            "of the sound it replaces" % off)


def _active_rms(a, np):
    """RMS over the audible part of *a* (samples above 2% of its own peak) —
    comparing whole-slot RMS would let trailing silence in either sound skew
    the gain."""
    x = np.abs(np.asarray(a, np.float64)).ravel()
    if not len(x):
        return 0.0
    pk = x.max()
    if pk <= 0:
        return 0.0
    act = x[x > 0.02 * pk]
    return float(np.sqrt((act ** 2).mean())) if len(act) else 0.0


def _soft_limit(x, ceiling, np):
    """Smoothly fold everything above ``_MATCH_KNEE * ceiling`` into the range
    below *ceiling*: identity under the knee, ``tanh``-shaped above it, so the
    waveform stays continuous and monotonic and no sample can reach the
    ceiling.  Used only after a loudness match has deliberately pushed peaks
    up; the body of the speech is under the knee and passes through
    untouched."""
    t = _MATCH_KNEE * ceiling
    room = ceiling - t
    if room <= 0:
        return np.clip(x, -ceiling, ceiling)
    ax = np.abs(x)
    over = ax > t
    if not over.any():
        return x
    y = np.array(x, np.float64, copy=True)
    y[over] = np.sign(x[over]) * (t + room * np.tanh((ax[over] - t) / room))
    return y


def _stock_render(emu, p, np, stereo):
    """Decoded stock audio for slot *p* (the loudness reference), or ``None``
    (matching off / no emulator / decode failed — callers then keep the fixed
    peak cap)."""
    if emu is None or not _match_loudness_enabled():
        return None
    try:
        out = emu.decode(p)
    except Exception:
        return None
    if out is None:
        return None
    if stereo and len(out) > 2 and out[2] and out[1] is not None:
        return np.stack([np.asarray(out[0], np.int64),
                         np.asarray(out[1], np.int64)], axis=1)
    return np.asarray(out[0], np.int64)


def _fit_level(a, orig, rng, np, headroom, gain_db=None):
    """Level the replacement *a* (int64, mono 1-D or stereo ``(n, 2)``): match
    the ORIGINAL sound's active RMS when a usable reference decoded, else fall
    back to the fixed peak cap.  See the block comment above for why matching
    limits rather than simply capping the gain.

    Whichever mode ran, the user's :func:`_match_gain_db` offset is applied on
    top and the result soft-limited, so "louder than the sound I replaced" is
    reachable without turning matching off.  *gain_db* replaces that global
    offset for this one sound (already totalled by :func:`_slot_gain_db`) —
    the per-clip Level column on the Replace Audio tab."""
    pk = int(np.abs(a).max()) if a.size else 0
    if pk <= 0:
        return a
    # Applied AFTER the _MATCH_MAX_GAIN cap, not folded into it: that cap is an
    # anti-noise-floor guard on the automatic part, and an explicit request for
    # +N dB should not be silently swallowed by it.
    off = 10.0 ** ((_match_gain_db() if gain_db is None else gain_db) / 20.0)
    if orig is not None and orig.size:
        opk = float(np.abs(orig).max())
        orms = _active_rms(orig, np)
        arms = _active_rms(a, np)
        if opk >= rng * _MATCH_MIN_ORIG_PEAK and orms > 0 and arms > 0:
            ov = _env_float("PAD_STERN_HEADROOM")
            ceil_frac = ov if (ov is not None and 0.05 <= ov <= 1.0) \
                else _MATCH_CEILING
            ceiling = rng * ceil_frac
            gain = min(orms / arms, _MATCH_MAX_GAIN) * off
            y = a.astype(np.float64) * gain
            # Limit ONLY when the gain actually pushed peaks past the ceiling.
            # Running the limiter unconditionally would shave the loudest 30%
            # of audio that needed nothing, making it quieter than doing
            # nothing at all — the opposite of matching (measured: -0.3 dB on
            # material already at stock level).
            if pk * gain > ceiling:
                y = _soft_limit(y, ceiling, np)
            return np.round(y).astype(np.int64)
    y = _amplitude_fit(a, rng, np, headroom=headroom)
    if off != 1.0 and y.size:
        # Peak-normalizing already parked the peak on the cap, so a boost here
        # can only come from the limiter folding the top down — which is what
        # makes it louder rather than just clipped.  Cut is a plain scaling.
        ceiling = rng * headroom
        y = y.astype(np.float64) * off
        if float(np.abs(y).max()) > ceiling:
            y = _soft_limit(y, ceiling, np)
        y = np.round(y).astype(np.int64)
    return y


_MONO_RANGE = 11147
_STEREO_RANGE = 21452

# "Auto-fade + cap audio replacements" (Write/Audio tab toggle, on by default).
# A user replacement cut mid-waveform slams from silence to a hot sample in a
# few ms; stock callouts ease in over 40-77 ms, so ours pop at that edge on real
# hardware (a tester, Led Zeppelin LE: clicks at BOTH edges, click volume
# tracks the cabinet's master knob, and a deliberately silent clip never clicks
# -- i.e. the step is in the signal we ship, not a Stern anti-tamper "watermark"
# that couldn't be removed).  ON lands a stock-length raised-cosine fade on both
# edges and normalizes to a lower ceiling so replacements sit nearer stock
# loudness (his sources were hotter than stock, and a louder edge = a louder
# click).  OFF (PAD_STERN_AUDIO_RAW=1, set by the GUI when the box is unticked)
# restores the prior minimal 5 ms fade + 0.97 ceiling.  The env var rides the
# spawn boundary into the encode workers, so serial and parallel writes agree
# without threading a flag through every signature.
_DECLICK_FADE_MS = 40.0
_DECLICK_HEADROOM = 0.80

# Band-limit to the stock callout's bandwidth (2026-07-09 firmware RE + spectral
# measurement).  The edge-fade + cap shipped in v0.49 did NOT fix a tester's HW
# clicks -- and reverse-engineering the firmware's symboled audio path (cabal's
# Ghidra DBs) plus measuring the audio explained why.  The callouts are mixed by
# Stern's own FIQ sound-script engine (sys_dac_c_handler_pdi: sums the cat-0
# tracks, *saturates* the sum, runs a DSP filter, then amp_write -- NOT the
# SoLoud path that carries music, which ramps/fades every gain).  Stock callouts
# are band-limited SPEECH (spectral centroid ~620 Hz, essentially nothing above
# 4 kHz); a tester's music-excerpt replacements measured ~2000 Hz centroid with
# 10x the energy above 8 kHz (Immigrant Song: 6400 Hz centroid, 28% in 8-12 kHz).
# That HF content -- cymbals / sibilance a speech-tuned cabinet speaker never
# reproduces, driven into the saturating FIQ mix -- is the click, and a fade + a
# peak cap can't touch bandwidth (which is why v0.49 didn't help).  A ~5 kHz
# low-pass pulls the profile back onto stock's (centroid ~820 Hz, zero energy
# above 8 kHz).  Rides the same toggle as the fade/cap; RAW mode skips it.
_DECLICK_LOWPASS_HZ = 5000.0


def _env_float(name):
    """``float(os.environ[name])`` or None (unset / not a number).  The audio
    experiment overrides ride the environment for the same reason
    ``PAD_STERN_AUDIO_RAW`` does: spawned encode workers inherit it, so serial
    and parallel writes agree without threading knobs through every
    signature."""
    v = os.environ.get(name)
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _declick_params():
    """``(fade_ms, headroom)`` for an audio replacement's edge fade + level cap.
    Auto-fade + cap is on unless the GUI unticked it (``PAD_STERN_AUDIO_RAW=1``),
    which restores the pre-v0.49 behavior.  ``PAD_STERN_FADE_MS`` /
    ``PAD_STERN_HEADROOM`` (GUI: Advanced audio options) override either base
    so the click hunt can vary one lever at a time."""
    if os.environ.get("PAD_STERN_AUDIO_RAW") == "1":
        fade, headroom = 5.0, 0.97
    else:
        fade, headroom = _DECLICK_FADE_MS, _DECLICK_HEADROOM
    ov = _env_float("PAD_STERN_FADE_MS")
    if ov is not None and 0.0 <= ov <= 500.0:
        fade = ov
    ov = _env_float("PAD_STERN_HEADROOM")
    if ov is not None and 0.05 <= ov <= 1.0:
        headroom = ov
    return fade, headroom


def _declick_lowpass_hz():
    """Low-pass cutoff (Hz) for band-limiting a replacement to stock callout
    bandwidth, or ``None`` in RAW mode (same toggle as :func:`_declick_params`).
    ``PAD_STERN_LOWPASS_HZ`` overrides in either mode; 0 disables the filter."""
    ov = _env_float("PAD_STERN_LOWPASS_HZ")
    if ov is not None:
        return None if ov <= 0 else min(max(ov, 500.0), 20000.0)
    if os.environ.get("PAD_STERN_AUDIO_RAW") == "1":
        return None
    return _DECLICK_LOWPASS_HZ


# Anti-pop "keep the output engaged" seed (2026-07-23 LZ RE).
# WHAT IT ADDRESSES: on real hardware a SILENT (or near-silent) callout
# replacement clicks/pops at its start, while stock callouts and audible
# replacements do not (a tester, Led Zeppelin 1.22).  We proved the whole
# codec + encode pipeline is clean -- our silent body decodes to true silence
# with the same codec the machine uses (clickdiag/encode_slot_match.py) -- so
# the pop is added by the machine's audio OUTPUT/mixer stage and is
# content-dependent: something there reacts to a dead-silent voice (a
# noise-gate / un-mute / underrun-restart in the SoLoud+ALSA output) that an
# audible voice keeps from firing.  The exact output mechanism is not yet
# pinned and this is HARDWARE-UNVERIFIED.
# THE SEED: mix an essentially-inaudible low-frequency tone into the target so
# the sound is never *digitally* silent -- keeping the output stage engaged so
# the silence-triggered pop never fires -- while staying below hearing
# (-65 dBFS default = ~18 counts).  A tone (not dither) is used so it also reads
# as real audio to anything that inspects the signal.  Off by default; opt-in
# via the GUI / PAD_STERN_SLOT_SEED_DB, and gated per-slot so one card can carry
# treated + control slots for a single-flash A/B (see _slot_seed_for).
_SLOT_SEED_HZ = 150.0


def _slot_seed_dbfs():
    """Seed-tone level in dBFS (negative), or None when the anti-pop codec seed
    is off.  ``PAD_STERN_SLOT_SEED_DB`` (GUI: Advanced audio options) sets it;
    clamped to a sane inaudible-but-effective range."""
    ov = _env_float("PAD_STERN_SLOT_SEED_DB")
    if ov is None or ov >= 0:
        return None
    return max(min(ov, -40.0), -90.0)


def _slot_seed_for(p):
    """Seed level for sound *p*, honouring the per-slot experiment idx gate so
    one card can carry seeded (treated) AND unseeded (control) slots for a
    single-flash A/B on the real machine (``PAD_STERN_EXPERIMENT_IDXS``)."""
    db = _slot_seed_dbfs()
    if db is None:
        return None
    from .spike2.codec import experiment_covers
    return db if experiment_covers(p) else None


def _pathA_seed_peak():
    """Sample peak of the Path A anti-degenerate seed tone.  A replacement whose
    fitted target peaks below this is (near-)silent -- and Path A skips the
    master-directory restore, so a silent body stays silent everywhere and the
    codec can't round-trip pure silence (it decodes to loud garbage).  Such
    replacements are seeded to :data:`_PATHA_SEED_DBFS` to stay decodable.
    (:func:`_amplitude_fit` normalises any real content up to near full scale, so
    only genuinely silent targets fall below this -- voice is never touched.)"""
    return int(round((10.0 ** (_PATHA_SEED_DBFS / 20.0)) * 32768.0))


def _encode_seed_for(p, peak):
    """Seed level for sound *p* whose fitted target peaks at *peak* counts
    (the loudest sample across every channel), or ``None`` for no seed.

    TWO independent levers ask for a seed here and they are not interchangeable:

    * the explicit anti-pop seed (``PAD_STERN_SLOT_SEED_DB`` / the GUI's
      "Anti-pop codec seed") is a PREFERENCE — an inaudible tone at a level the
      user picks, gated per-slot so one card can carry treated slots and
      untouched controls;
    * the Path A seed (:data:`_PATHA_SEED_DBFS`) is a REQUIREMENT — blip-free
      skips the master-directory restore, so a near-silent body stays silent
      everywhere, and below :func:`_pathA_seed_peak` the codec can no longer
      round-trip it (it decodes to loud garbage).

    So they combine as "whichever is stronger", never "whichever was asked for
    first".  The old ``seed is None`` gate let the weaker preference cancel the
    requirement outright: ticking the anti-pop seed at its -65 dBFS default
    (~18 counts) while blip-free was also on took a silent slot from the ~184
    counts Path A needs down to 18 — turning one click mitigation ON silently
    disabled a stronger one, on the exact settings pair the GUI hands out by
    default (a tester, Led Zeppelin LE 1.22, clicks back on song-name callouts
    after three builds of settings changes, 2026-08-08).

    The per-slot experiment gate deliberately does NOT narrow the requirement
    half: a control slot is still a slot that has to decode."""
    seed = _slot_seed_for(p)
    if (_pathA_enabled() and peak < _pathA_seed_peak()
            and (seed is None or seed < _PATHA_SEED_DBFS)):
        return _PATHA_SEED_DBFS
    return seed


def _apply_slot_seed(samples, np, rng, dbfs):
    """Mix an inaudible edge-faded ~150 Hz tone into *samples* so the correct
    codec slot decodes to spectrally-peaked ("audio") content and the firmware's
    slot resolver never falls back to the noise codec (the start pop).  The tone
    is faded to zero at both edges (like :func:`_fit`) so it adds no edge step,
    and the sum is clipped to the codec range.  See the module comment above."""
    if dbfs is None:
        return samples
    n = len(samples)
    if n < 8:
        return samples
    amp = (10.0 ** (dbfs / 20.0)) * 32768.0
    t = np.arange(n) / 44100.0
    tone = amp * np.sin(2.0 * np.pi * _SLOT_SEED_HZ * t)
    m = min(n // 2, int(round(40.0 * 44.1)))   # match the declick edge fade
    if m > 1:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, m))
        tone[:m] *= ramp
        tone[n - m:] *= ramp[::-1]
    out = np.asarray(samples, np.int64) + np.round(tone).astype(np.int64)
    return np.clip(out, -rng, rng)


def _lowpass(samples, cutoff_hz, np, fs=44100.0):
    """Zero-phase 2nd-order Butterworth low-pass (applied forward + reverse, so
    4th-order effective with no phase shift and, being IIR, no pre-echo that an
    FFT brick-wall would smear backward into a transient).  Dependency-free
    (numpy only -- the plugin never pulls scipy).  Returns int64 samples.

    Used to band-limit an audio replacement to the stock callout's spectral
    envelope; see :data:`_DECLICK_LOWPASS_HZ` for why."""
    x = np.asarray(samples, np.float64)
    if cutoff_hz is None or len(x) < 12 or cutoff_hz >= fs * 0.5:
        return np.asarray(samples, np.int64)
    import math
    w0 = 2.0 * math.pi * cutoff_hz / fs
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / math.sqrt(2.0)              # Butterworth Q = 1/sqrt(2)
    a0 = 1.0 + alpha
    b0 = (1.0 - cw) / 2.0 / a0
    b1 = (1.0 - cw) / a0
    b2 = b0
    a1 = (-2.0 * cw) / a0
    a2 = (1.0 - alpha) / a0

    def _iir(sig):
        y = np.empty_like(sig)
        x1 = x2 = y1 = y2 = 0.0
        for i in range(len(sig)):
            xi = sig[i]
            yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1 = x1, xi
            y2, y1 = y1, yi
            y[i] = yi
        return y

    y = _iir(x)                              # forward
    y = _iir(y[::-1])[::-1]                   # reverse -> zero phase
    return np.round(y).astype(np.int64)


# ---- stock-vs-replacement audio profiling (Audio tab: "Profile vs stock") --
#
# The stock callouts have a house style — 40-77 ms ease-ins, band-limited
# speech (centroid ~620 Hz, nothing above 8 kHz), moderate levels — and every
# hardware click hunt so far has come back to a replacement deviating from it
# (hot onsets, 10x the HF energy, near-full-scale peaks).  This report puts
# numbers on that per sound: every idxNNNN.wav gets characterized, and each
# REPLACED sound is compared against its pristine .orig snapshot (or, without
# one, the stock population median) with plain-language flags.

def _wav_profile(path, np):
    """Waveform metrics for one WAV: duration, levels, edges, spectrum."""
    import math
    s = _load_wav(path, False, np)
    n = len(s)
    if n == 0:
        return None
    x = s.astype(np.float64)
    peak = float(np.abs(x).max())
    rms = float(np.sqrt((x ** 2).mean()))
    dbfs = lambda v: -120.0 if v <= 0 else 20.0 * math.log10(v / 32768.0)

    def first_above(frac):
        i = np.flatnonzero(np.abs(x) >= frac * peak)
        return (i[0] / 44.1) if len(i) else -1.0          # ms

    def last_above(frac):
        i = np.flatnonzero(np.abs(x) >= frac * peak)
        return ((n - 1 - i[-1]) / 44.1) if len(i) else -1.0

    # Whole-file spectrum (these are short callouts; decimate very long files
    # to keep the FFT cheap).
    xs = x if n <= 2 ** 21 else x[:: (n // 2 ** 20)]
    S = np.abs(np.fft.rfft(xs * np.hanning(len(xs)))) ** 2
    f = np.fft.rfftfreq(len(xs), 1 / 44100.0)
    tot = max(float(S.sum()), 1e-9)
    return {
        "dur_s": round(n / 44100.0, 4),
        "peak_dbfs": round(dbfs(peak), 1),
        "rms_dbfs": round(dbfs(rms), 1),
        "dc_counts": int(round(float(x.mean()))),
        "lead5_ms": round(first_above(0.05), 1),
        "lead50_ms": round(first_above(0.50), 1),
        "tail5_ms": round(last_above(0.05), 1),
        "centroid_hz": int((S * f).sum() / tot),
        "pct_gt4k": round(float(S[f > 4000].sum()) / tot * 100.0, 1),
        "pct_gt8k": round(float(S[f > 8000].sum()) / tot * 100.0, 1),
    }


_PROFILE_FIELDS = ["dur_s", "peak_dbfs", "rms_dbfs", "dc_counts", "lead5_ms",
                   "lead50_ms", "tail5_ms", "centroid_hz", "pct_gt4k",
                   "pct_gt8k"]


def _profile_flags(rep, ref):
    """Plain-language deviations of a replacement profile vs its reference."""
    flags = []
    if ref["lead5_ms"] >= 0 and rep["lead5_ms"] >= 0:
        if rep["lead5_ms"] < 10.0 and ref["lead5_ms"] - rep["lead5_ms"] > 10.0:
            flags.append("starts much hotter than stock (lead-in %.0fms vs "
                         "%.0fms)" % (rep["lead5_ms"], ref["lead5_ms"]))
    if rep["centroid_hz"] > max(2 * ref["centroid_hz"], 1500):
        flags.append("much brighter than stock (centroid %dHz vs %dHz)"
                     % (rep["centroid_hz"], ref["centroid_hz"]))
    if rep["pct_gt8k"] > ref["pct_gt8k"] + 5.0:
        flags.append("treble-heavy vs stock (%.1f%% vs %.1f%% above 8kHz)"
                     % (rep["pct_gt8k"], ref["pct_gt8k"]))
    if rep["peak_dbfs"] > ref["peak_dbfs"] + 6.0:
        flags.append("much hotter peak than stock (%.1f vs %.1f dBFS)"
                     % (rep["peak_dbfs"], ref["peak_dbfs"]))
    if abs(rep["dc_counts"]) > 100:
        flags.append("carries a DC offset (%+d counts)" % rep["dc_counts"])
    return flags


def audio_profile_report(assets_dir, log, progress=None):
    """Characterize every ``idxNNNN.wav`` under *assets_dir* and write
    ``audio_profile.csv`` beside the extract baseline.

    Returns ``(csv_path, n_sounds, n_replaced, n_flagged)``.  Replaced sounds
    (bytes differ from ``.checksums.md5``) are compared against their pristine
    ``.orig`` snapshot when one exists, else against the median profile of the
    unchanged (stock) population."""
    import csv
    import statistics

    import numpy as np

    from ...core import staged_originals
    from ...core.checksums import read_checksums

    baseline = read_checksums(assets_dir)
    base_by_idx = {}
    rel_by_idx = {}
    for rel in baseline:
        idx = _wav_idx(os.path.splitext(os.path.basename(rel))[0])
        if idx is not None:
            base_by_idx[idx] = baseline[rel]
            rel_by_idx[idx] = rel

    files = []
    for root, _dirs, fns in os.walk(assets_dir):
        _dirs[:] = [d for d in _dirs if not d.startswith(".")]
        for fn in fns:
            if fn.lower().endswith(".wav"):
                idx = _wav_idx(os.path.splitext(fn)[0])
                if idx is not None:
                    files.append((idx, os.path.join(root, fn)))
    # One row per idx (renamed twins share content; prefer the changed twin).
    by_idx = {}
    for idx, path in sorted(files):
        base = base_by_idx.get(idx)
        changed = True
        if base is not None:
            changed = _scan_md5(assets_dir, path) != base
        prev = by_idx.get(idx)
        if prev is None or (changed and not prev[1]):
            by_idx[idx] = (path, changed)

    rows = []
    stock_profiles = []
    n_rep = 0
    items = sorted(by_idx.items())
    for i, (idx, (path, changed)) in enumerate(items):
        if progress:
            progress(i, len(items), os.path.basename(path))
        try:
            prof = _wav_profile(path, np)
        except Exception as e:
            log("idx%04d: could not profile (%s)" % (idx, e), "warning")
            continue
        if prof is None:
            continue
        ref = None
        if changed:
            n_rep += 1
            rel = rel_by_idx.get(idx)
            snap = staged_originals.snapshot_path(assets_dir, rel) if rel else None
            if snap:
                try:
                    ref = _wav_profile(snap, np)
                except Exception:
                    ref = None
        else:
            stock_profiles.append(prof)
        rows.append({"idx": idx, "file": os.path.basename(path),
                     "status": "replaced" if changed else "stock",
                     "prof": prof, "ref": ref})

    # Population median as the fallback reference for snapshot-less edits.
    pop_ref = None
    if stock_profiles:
        pop_ref = {k: statistics.median(p[k] for p in stock_profiles)
                   for k in _PROFILE_FIELDS}

    csv_path = os.path.join(assets_dir, "audio_profile.csv")
    n_flagged = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["idx", "file", "status"] + _PROFILE_FIELDS
                   + ["stock_" + k for k in _PROFILE_FIELDS] + ["flags"])
        for r in rows:
            ref = r["ref"] or (pop_ref if r["status"] == "replaced" else None)
            flags = _profile_flags(r["prof"], ref) if ref else []
            if flags:
                n_flagged += 1
                log("idx%04d %s: %s" % (r["idx"], r["file"],
                                        "; ".join(flags)), "warning")
            w.writerow(["idx%04d" % r["idx"], r["file"], r["status"]]
                       + [r["prof"][k] for k in _PROFILE_FIELDS]
                       + [(r["ref"] or {}).get(k, "") for k in _PROFILE_FIELDS]
                       + ["; ".join(flags)])
    log("Audio profile written: %s (%d sounds, %d replaced, %d flagged)."
        % (csv_path, len(rows), n_rep, n_flagged),
        "success" if not n_flagged else "warning")
    return csv_path, len(rows), n_rep, n_flagged


class _BodyOverlay:
    """Read-through overlay on the image.bin mmap: returns patched bytes for one
    body offset so a freshly re-encoded body can be decoded back *without*
    copying the whole multi-GB image.  Used by :func:`_recovery_valid` to verify
    a sound's re-encode round-trips before Write trusts it."""

    def __init__(self, mm):
        self._mm = mm
        self.patch = None      # (file_off, bytes) or None

    def __getitem__(self, sl):
        data = bytearray(self._mm[sl])
        if self.patch is not None and isinstance(sl, slice):
            off, b = self.patch
            start = sl.start or 0
            lo = max(off, start)
            hi = min(off + len(b), start + len(data))
            if lo < hi:
                data[lo - start:hi - start] = b[lo - off:hi - off]
        return bytes(data)

    def size(self):
        return self._mm.size()

    def close(self):
        self._mm.close()


def _recovery_valid(emu, gr, sr, p, np, nblk=4):
    """True iff re-encoding the sound's *own* decoded audio reproduces it
    bit-exact over the first ``nblk`` blocks.

    The analytic re-encode recovers a per-sample keystream by driving the codec;
    that recovery is exact for the codecs validated so far but does not yet model
    every variant (e.g. multi-band sounds, where the companding fires several
    times per output sample and the captured keystream interleaves).  This
    self-test catches such sounds so Write can skip them rather than patch a body
    that would decode to noise -- protecting both the newly-located titles and
    any multi-band sound in an already-supported title.  Any failure to drive the
    recovery (e.g. no companding site located) is treated as 'not valid' so the
    sound is skipped, never written blind."""
    secs = (nblk * 200 + 200) / 44100.0
    try:
        out0 = emu.decode(p, max_secs=secs)
        if out0 is None:
            return False
        L0 = np.asarray(out0[0], np.int64); R0 = np.asarray(out0[1], np.int64)
        stereo = out0[2]
        nb = min(nblk, (len(L0) + 199) // 200)
        if nb == 0:
            return False
        # Re-encode only the first ``nb`` blocks (truncate the target so
        # encode_sound stops there) and compare over that range; encode_sound
        # applies the build's body-word offset so the self-test sees the same
        # bytes a full Write would lay down.
        cmp_n = nb * 200
        if stereo:
            off, body = sr.encode_sound(p, L0[:cmp_n], R0[:cmp_n])
        else:
            off, body = gr.encode_sound(p, L0[:cmp_n])
        if not isinstance(emu.mm, _BodyOverlay):
            emu.mm = _BodyOverlay(emu.mm)
        emu.mm.patch = (off, bytes(body))
        try:
            out1 = emu.decode(p, max_secs=secs)
        finally:
            emu.mm.patch = None
        if out1 is None:
            return False
        L1 = np.asarray(out1[0], np.int64); R1 = np.asarray(out1[1], np.int64)
        m = min(len(L0), len(L1), cmp_n)
        if int(np.count_nonzero(L0[:m] != L1[:m])):
            return False
        if stereo:
            mr = min(len(R0), len(R1), cmp_n)
            if int(np.count_nonzero(R0[:mr] != R1[:mr])):
                return False
        return True
    except Exception:
        return False


class _EncodeVerifyError(Exception):
    """The body we were about to write does not decode back to the target.

    Raised by :func:`_verify_encoded`; callers treat it exactly like a
    ``_recovery_valid`` failure — skip the sound, leave it unchanged, say so."""


def _verify_encoded(emu, p, start, body, tgtL, tgtR, np, log=None,
                    exempt_head=False):
    """Check the ACTUAL bytes we're about to write decode back to the target,
    over the WHOLE emitted range.

    ``_recovery_valid`` is only a pre-flight: it re-encodes the sound's own
    audio over the first few blocks (4 blocks = ~4% of a 425 ms sound), so a
    keystream recovery that holds at the head but degrades later would ship
    unnoticed and decode to noise on the machine.  This is the honest check —
    it costs one extra decode (not a second encode) and covers every sample we
    actually lay down.

    The first ``BLOCK`` frames are exempt on delta<0 keys: there the head word
    is physically shared with the layout predecessor, so it is deliberately a
    compromise between the two keystreams and any residual is absorbed by a
    short decay ramp — that head legitimately differs from the fitted target
    (see :func:`_resolve_shared_boundary`).  On delta=0 keys nothing is exempt
    unless *exempt_head* says block 0 was deliberately restored to the stock
    card's words (:func:`_apply_stock_head` — those decode to the STOCK head,
    within its silence gate, not to the fitted target).

    On success, drops a machine-render preview WAV when the GUI asked for one
    (:func:`_write_machine_render`).

    Raises :class:`_EncodeVerifyError` on mismatch."""
    from .spike2.emulator import emitted_length, BLOCK
    # Verification needs a booted emulator and a real slot; without either
    # there is nothing to check against (only unit tests exercising the
    # target-fitting half of the encoders get here).  Both always exist on the
    # Write path.
    if emu is None or "body_off" not in p:
        return
    n = emitted_length(p["length"])
    if n <= 0:
        return
    stereo = p["chan"] == 2
    step = 4 if stereo else 2
    delta = (start - p["body_off"]) // step
    lo = BLOCK if (delta < 0 or exempt_head) else 0
    if lo >= n:
        return
    if not isinstance(emu.mm, _BodyOverlay):
        emu.mm = _BodyOverlay(emu.mm)
    saved = emu.mm.patch
    emu.mm.patch = (start, bytes(body))
    try:
        out = emu.decode(p)
    finally:
        emu.mm.patch = saved
    if out is None:
        raise _EncodeVerifyError("idx %d: re-decode of the encoded body failed"
                                 % p["idx"])
    got = [np.asarray(out[0], np.int64)]
    want = [np.asarray(tgtL, np.int64)]
    if stereo and out[2] and out[1] is not None and tgtR is not None:
        got.append(np.asarray(out[1], np.int64))
        want.append(np.asarray(tgtR, np.int64))
    for ch, (g, w) in enumerate(zip(got, want)):
        m = min(len(g), len(w), n)
        if m <= lo:
            continue
        d = np.abs(g[lo:m] - w[lo:m])
        if not d.size:
            continue
        worst = int(np.argmax(d))
        err = int(d[worst])
        if err:
            at = lo + worst
            raise _EncodeVerifyError(
                "idx %d: encoded body does not decode to the requested audio "
                "(%s channel differs by %d counts at sample %d of %d, %.0f ms in)"
                % (p["idx"], "LR"[ch] if stereo else "mono", err, at, n,
                   at / 44.1))
    _write_machine_render(p, got, stereo, np)


def _audit_audio_patches(params, patches, log):
    """Byte-range audit of the assembled cat-0 patch set — the paranoid check
    that OUR writes land exactly where the model says they do.

    Every hardware click hunt eventually asks "did the pipeline scribble on a
    neighbor?", so answer it on every build: each patch must be owned by
    exactly one sound (its window at ``body_off`` or the documented delta<0
    shift of 1-2 words below), be size-neutral for that window, and overlap
    another patch by at most the deliberate shared-boundary word(s).  Log-only
    — an anomaly warns loudly but never blocks a build (the verify pass is
    the hard gate).  Returns the number of anomalies."""
    own = {}
    for p in params:
        s = 4 if p.get("chan") == 2 else 2
        for d in (0, 1, 2):                 # delta 0 / -1 / -2 window starts
            own.setdefault(p["body_off"] - s * d, []).append((p, s, d))
    issues = shared = 0
    items = sorted(patches.items())
    prev_end = prev_owner = None
    for off, body in items:
        owner = None
        for p, s, d in own.get(off, ()):
            # an APPENDED record's encode also covers its silent lead-out (_APPENDED_TAIL,
            # item 150 follow-up): its window is that much longer than its length
            if len(body) == s * p["length"] or (p.get("grown") and not d and len(body) == s * (
                    p["length"] + _APPENDED_TAIL)):
                owner = (p, s, d)
                break
        if owner is None:
            log("Patch audit: patch at 0x%x (%d bytes) matches no sound's "
                "write window — please report this build log." % (off, len(body)),
                "warning")
            issues += 1
        elif owner[2]:
            shared += 1                      # shifted window: head word shared
        if prev_end is not None and off < prev_end:
            ov = prev_end - off
            if owner is not None and ov <= 2 * owner[1]:
                shared += 1                  # adjacent replacement, shared word
            else:
                log("Patch audit: patches overlap by %d bytes at 0x%x "
                    "(owners idx%s/idx%s) — please report this build log."
                    % (ov, off,
                       getattr(prev_owner, "get", lambda *_: "?")("idx", "?")
                       if prev_owner else "?",
                       owner[0]["idx"] if owner else "?"), "warning")
                issues += 1
        prev_end = off + len(body)
        prev_owner = owner[0] if owner else None
    if issues:
        log("Patch audit: %d anomalies across %d audio patches." %
            (issues, len(items)), "warning")
    else:
        log("Patch audit: %d audio patches, every byte inside its own "
            "sound's window%s." %
            (len(items), (" (%d shared-boundary words, expected)" % shared)
             if shared else ""), "info")
    return issues


def _slot_end_map(params):
    """``{slot_end_byte_offset: p}`` — who ends exactly where.  Cat-0 sounds
    are packed back-to-back, so the sound ending at another's ``body_off`` is
    the layout predecessor whose tail word(s) a delta<0 encode window
    overlaps (see :func:`_resolve_shared_boundary`)."""
    out = {}
    for q in params:
        bps = 4 if q.get("chan") == 2 else 2
        out[q["body_off"] + bps * q["length"]] = q
    return out


def _extended_params(p, extra=400):
    """*p* with its length grown by *extra* samples — including inside
    ``_rawobj`` (generic builds replay that obj verbatim, and the firmware's
    emission gate reads the length stored at +0x10) — so a keystream-recovery
    drive can reach the tail block real hardware renders past the emulated
    emitted range.  ``None`` if the raw obj layout isn't the known one."""
    p2 = dict(p, length=p["length"] + extra)
    raw = p.get("_rawobj")
    if raw:
        raw = bytearray(raw)
        if struct.unpack_from("<I", raw, 0x10)[0] != p["length"]:
            return None
        struct.pack_into("<I", raw, 0x10, p2["length"])
        p2["_rawobj"] = bytes(raw)
    return p2


# The decay ramp absorbing our forced sample 0 is only the right tool for
# SMALL residuals.  The two keystream maps can conflict by thousands of counts,
# and stock cards ship exactly that: on EHOH idx5103 the stock frame-0 words
# render (+2925, -6274) under the sound's own keystream — a naked one-frame
# impulse Stern accepted, and real hardware provably does not click on it.  A
# 4 ms ramp seeded from a residual that size carries ~60x the impulse's energy
# spread across fully audible samples (the thump the tester still heard after
# v0.64.2), so past this threshold we keep the stock geometry instead: sample 0
# lands where it lands, samples 1+ are the caller's untouched (faded) content.
_RAMP_MAX_EXCESS = 512


def _ramp_excess(excess):
    return excess if abs(excess) <= _RAMP_MAX_EXCESS else 0


def _resolve_shared_boundary(emu, p, pred, start, body, tgtL, tgtR, np,
                             gr=None, sr=None, log=None):
    """Re-pick the head word(s) of a delta<0 encode window — storage the
    hardware reads TWICE, with two different keystreams.

    On delta<0 keys the window's first word (mono) / frame (stereo) sits below
    ``body_off``: physically the LAST word(s) of the layout-predecessor's
    slot.  The machine renders a sound until its body is exhausted — one
    sample past the lead-out block on delta=-1 builds — so it decodes that
    storage once as OUR sample 0 (our keystream) and once as the
    predecessor's final rendered sample(s) (its keystream).  encode_sound
    writes ``enc[0]`` there: correct for us, but under the predecessor's
    keystream it decodes as a random up-to-full-scale sample — a pop at the
    end of every complete predecessor playback, surviving even a silent
    replacement (Elvira HoH spinner pair idx4447/idx4448: stock -6 became
    +7383 at idx4447's final sample).  Leaving the stock word (pre-v0.59.0)
    is the mirror image: clean predecessor, pop at our trigger.

    Neither single-context choice is right, but the sides aren't symmetric
    either.  The predecessor's contested sample sits at the end of its
    faded-out tail — any residual there is a naked pop, and none of its other
    samples are ours to shape.  Our contested sample is sample 0, and every
    sample AFTER it is ours.  So: pick the word whose decode is essentially
    exact for the predecessor (target = the STOCK word's decode there — its
    lead-out stays stock-seeded whether or not it is itself replaced — via
    :func:`~.spike2.codec.pick_shared_word`), then absorb whatever our
    sample 0 lands on by re-encoding the head of block 0 as a short decay
    ramp from that value into the replacement's own (faded) content — a
    click becomes a ~4 ms inaudible slope.  Large residuals are left as a
    naked one-frame impulse instead, matching stock cards (see
    ``_RAMP_MAX_EXCESS``).  Any failure returns *body* unchanged (the
    v0.59.0 behavior).  *tgtL*/*tgtR* are the encode's target sample arrays
    (R ``None`` for mono)."""
    if pred is None or start >= p["body_off"]:
        return body
    try:
        from .spike2.codec import (GenRecover, StereoRecover, _rorv,
                                   decode_word, pick_shared_word)

        def rec_for(chan):
            nonlocal gr, sr
            if chan == 2:
                if sr is None:
                    sr = getattr(emu, "_boundary_sr", None) or StereoRecover(emu)
                    emu._boundary_sr = sr
                return sr
            if gr is None:
                gr = getattr(emu, "_boundary_gr", None) or GenRecover(emu)
                emu._boundary_gr = gr
            return gr

        def stock_word(abs_off):
            return struct.unpack("<H", bytes(emu.mm[abs_off:abs_off + 2]))[0]

        pred_ext = _extended_params(pred)
        if pred_ext is None:
            return body
        prec = rec_for(pred["chan"])
        if pred["chan"] == 2:
            d_p = min(prec._calibrate(pred), 0)
        else:
            d_p = min(prec._calibrate(pred)[2], 0)

        def pred_ctx(abs_off, u0_word, u0_stock=None):
            """Predecessor-side ``(r, x, qmul, target)`` for its word at
            *abs_off* (target = what the STOCK CARD rendered there).  *u0_word*
            = the u0 that will actually sit on the card after our write, for
            the stereo u1 coupling of candidate words; *u0_stock* = the u0 in
            effect on the stock card, for the target.  They differ only when
            the caller rewrites the L word of the same frame (stereo self):
            folding the new u0 into the target too would aim at the stock
            word's decode under a coupling that never played — a value up to
            full-scale off the true stock render, i.e. a pop at the
            predecessor's natural end that pick_shared_word then faithfully
            reproduces while reporting near-zero error (EHOH spinner
            idx5102/idx5103: stock R 7 shipped as 3357)."""
            w = (abs_off - pred["body_off"]) // 2
            if pred["chan"] == 2:
                f, sub = w // 2, w % 2
                i = f - d_p
                C = 200 * (i // 200) + 200
                j = i - (C - 200)
                rec = prec.recover_block(pred_ext, C, nf=j + 1)
                if rec["m"] <= j:
                    return None
                if sub == 0:
                    r, x = int(rec["rbL"][j]), int(rec["KL"][j])
                    tx = x
                else:
                    r = int(rec["bR"][j])
                    kr, ar = int(rec["KR"][j]), int(rec["aR"][j])
                    x = kr ^ _rorv(int(u0_word) & 0xffff, ar)
                    u0s = u0_word if u0_stock is None else u0_stock
                    tx = kr ^ _rorv(int(u0s) & 0xffff, ar)
                q = prec.qmul
            else:
                i = w - d_p
                C = 200 * (i // 200) + 200
                j = i - (C - 200)
                K, rb = prec.recover_block(pred_ext, C, n=j + 1)
                if len(K) <= j:
                    return None
                r, x, q = int(rb[j]), int(K[j]), prec.qmul
                tx = x
            return (r, x, int(q), decode_word(stock_word(abs_off), r, tx, q))

        def ramp(tgt, excess, m, rng, ramp_n=176):
            """Block-0 target with *excess* decayed linearly from sample 1 —
            continues our (fixed) sample-0 value smoothly into the
            replacement's own content instead of stepping off a spike."""
            new_t = np.asarray(tgt[:m], np.int64).copy()
            n = min(int(ramp_n), m - 1)
            if n > 0 and excess:
                i = np.arange(1, n + 1)
                new_t[1:n + 1] += (int(excess) * (n + 1 - i)) // (n + 1)
                np.clip(new_t, -rng, rng, out=new_t)
            return new_t

        out = bytearray(body)
        srec = rec_for(p["chan"])
        if p["chan"] == 2:
            rec0 = srec.recover_block(p, 200, nf=200)
            m = min(rec0["m"], len(tgtL), len(tgtR))
            if m < 1:
                return body
            pcA = pred_ctx(start, 0)
            if pcA is None:
                return body
            q2 = int(srec.qmul)
            u0, epA, svL = pick_shared_word(
                pcA, (int(rec0["rbL"][0]), int(rec0["KL"][0]), q2,
                      int(tgtL[0])))
            pcB = pred_ctx(start + 2, u0, u0_stock=stock_word(start))
            if pcB is None:
                return body
            u1, epB, svR = pick_shared_word(
                pcB, (int(rec0["bR"][0]),
                      int(rec0["KR"][0]) ^ _rorv(u0, int(rec0["aR"][0])),
                      q2, int(tgtR[0])))
            struct.pack_into("<HH", out, 0, u0, u1)
            exL = _ramp_excess(svL - int(tgtL[0]))
            exR = _ramp_excess(svR - int(tgtR[0]))
            if (abs(exL) > 48 or abs(exR) > 48) and m > 1:
                rec_m = {k: (v[:m] if k in ("KL", "rbL", "KR", "aR", "bR")
                             else m if k == "m" else v)
                         for k, v in rec0.items()}
                frame, _ = srec.encode_block(
                    ramp(tgtL, exL, m, _STEREO_RANGE),
                    ramp(tgtR, exR, m, _STEREO_RANGE), rec_m)
                out[4:4 * m] = np.ascontiguousarray(
                    frame[2:2 * m], dtype="<u2").tobytes()
            err = max(epA, epB)
        else:
            K, rb = srec.recover_block(p, 200, n=200)
            m = min(len(K), len(tgtL))
            if m < 1:
                return body
            pc = pred_ctx(start, stock_word(start - 2))
            if pc is None:
                return body
            W, err, sval = pick_shared_word(
                pc, (int(rb[0]), int(K[0]), int(srec.qmul), int(tgtL[0])))
            struct.pack_into("<H", out, 0, W)
            excess = _ramp_excess(sval - int(tgtL[0]))
            if abs(excess) > 48 and m > 1:
                enc, _ = srec.encode_block(
                    ramp(tgtL, excess, m, _MONO_RANGE), K[:m], rb[:m])
                out[2:2 * m] = np.ascontiguousarray(
                    enc[1:m], dtype="<u2").tobytes()
        if log is not None and err > 8:
            log("idx %d: boundary word shared with idx %d settles at error %d "
                "counts on the neighbor." % (p["idx"], pred["idx"], err),
                "info")
        return bytes(out)
    except Exception:
        return body


# Experimental head mode for the 2026-07 a tester trigger-pop hunt
# (``PAD_STERN_HEAD_MODE=stock``, GUI: Advanced audio options).  Theory under
# test: real playback seeds per-sound codec state at voice start in a way the
# emulated decode path doesn't model, so ANY re-encoded head block can burp a
# few-ms burst at trigger even when its words provably decode to the fitted
# (silent-headed) target — the write-side mirror of the extract-side
# quiet-intro slot trap.  Keeping the stock words for block 0 makes the first
# 4.5 ms byte-identical to stock — immune to any unmodeled read path — and the
# gates guarantee it never audibly changes the sound: delta=0 windows only,
# fitted head essentially silent (always true with shaping on: the fade starts
# at zero), and the stock head itself decodes essentially silent (so a
# replacement never opens with the replaced sound's own attack).
_STOCK_HEAD_TGT_MAX = 16      # counts: fitted head counts as silent
_STOCK_HEAD_STOCK_MAX = 64    # counts: stock head counts as silent (-53 dBFS)


def _apply_stock_head(emu, p, start, body, tgt, rec, np, log=None):
    """``(body, applied)`` — *body* with block 0 restored to the stock card's
    words when every stock-head gate passes (see above), unchanged otherwise."""
    from .spike2.codec import decode_word, experiment_covers
    from .spike2.emulator import BLOCK

    def skip(why):
        if log is not None:
            log("idx %d: stock-head mode not applied (%s)." % (p["idx"], why),
                "info")
        return body, False

    if os.environ.get("PAD_STERN_HEAD_MODE") != "stock":
        return body, False
    if not experiment_covers(p):
        return body, False               # not in the experiment idx list
    try:
        if p.get("chan") == 2:
            return skip("stereo slot; mono only for now")
        if start != p["body_off"]:
            return skip("shifted delta<0 window, head word is shared")
        head = np.abs(np.asarray(tgt[:BLOCK], np.int64))
        if head.size == 0 or len(body) < 2 * BLOCK:
            return skip("sound shorter than one block")
        if int(head.max()) > _STOCK_HEAD_TGT_MAX:
            return skip("replacement head is not silent (max %d counts)"
                        % int(head.max()))
        K, rb = rec.recover_block(p, 200, n=BLOCK)
        m = min(len(K), BLOCK)
        if m < BLOCK:
            return skip("head keystream recovery came up short")
        stock = np.frombuffer(bytes(emu.mm[start:start + 2 * BLOCK]),
                              dtype="<u2")
        worst = max(abs(decode_word(int(stock[i]), int(rb[i]), int(K[i]),
                                    rec.qmul)) for i in range(BLOCK))
        if worst > _STOCK_HEAD_STOCK_MAX:
            return skip("stock head is not silent (max %d counts)" % worst)
        out = bytearray(body)
        out[:2 * BLOCK] = stock.tobytes()
        if log is not None:
            log("idx %d: head block kept byte-identical to stock "
                "(experimental stock-head mode; stock head decodes within "
                "%d counts)." % (p["idx"], worst), "info")
        return bytes(out), True
    except Exception:
        return skip("gate check failed")


def _write_machine_render(p, got, stereo, np):
    """Drop the verified machine-render of a re-encoded sound as a WAV into
    ``PAD_STERN_PREVIEW_DIR`` (set by the GUI's 'export machine-render
    previews' option).  Best-effort: a preview must never fail a Write."""
    out_dir = os.environ.get("PAD_STERN_PREVIEW_DIR")
    if not out_dir:
        return
    try:
        import wave
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "idx%04d_machine_render.wav" % p["idx"])
        if stereo and len(got) > 1:
            a = np.stack([got[0], got[1]], axis=1).ravel()
            nch = 2
        else:
            a = np.asarray(got[0])
            nch = 1
        pcm = np.clip(a, -32768, 32767).astype("<i2").tobytes()
        with wave.open(path, "wb") as w:
            w.setnchannels(nch)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(pcm)
    except Exception:
        pass


def _lowpass_loop(samples, cutoff_hz, np, pad=4096):
    """:func:`_lowpass` for a sound that LOOPS: filtered as one turn of a circle
    (wrapped padding on both sides), so the filter's start-up and tail do not
    make a step at the loop point.  Item 150 follow-up (a mode's music bed)."""
    x = np.asarray(samples, np.int64)
    if cutoff_hz is None or len(x) < 12:
        return x
    k = min(pad, len(x))
    y = _lowpass(np.concatenate([x[-k:], x, x[:k]]), cutoff_hz, np)
    return np.asarray(y[k:k + len(x)], np.int64)


_LEVEL_REF_UNSET = object()


def _encode_mono(emu, gr, p, wav_path, np, pred=None, log=None, gain_db=None,
                 loop=False, orig=_LEVEL_REF_UNSET):
    # Returns encode_sound's ``(start_off, body)`` — the write offset can sit
    # one word below body_off on delta=-1 codec keys (the start-click fix).
    # Fit to the codec's TRUE emitted sample count (length - BLOCK), not the raw
    # header length: encode_sound only writes that many samples, so fitting to
    # the full length would silently drop the user's last ~200 samples (a click
    # at the loop point of looping music).
    # *loop* (item 150 follow-up): the record LOOPS (a mode's music bed), so its
    # end runs straight into its start - no edge fades, a circular low-pass.
    # *orig* is the loudness reference to match (default: the slot's own stock
    # render); a mode's music bed passes the game's own music.
    from .spike2.emulator import emitted_length
    n = emitted_length(p["length"])
    fade_ms, headroom = _declick_params()
    if loop:
        fade_ms = 0.0
    s = _load_wav(wav_path, False, np)
    # Band-limit to stock callout bandwidth BEFORE the level fit so the gain
    # targets the audible (post-filter) signal, not HF we're about to remove.
    s = (_lowpass_loop if loop else _lowpass)(s, _declick_lowpass_hz(), np)
    s = _fit_level(np.asarray(s, np.int64),
                   _stock_render(emu, p, np, stereo=False)
                   if orig is _LEVEL_REF_UNSET else orig,
                   _MONO_RANGE, np, headroom, gain_db=gain_db)
    tgt = _fit(np.clip(s, -_MONO_RANGE, _MONO_RANGE), n, np, fade_ms=fade_ms)
    seed = _encode_seed_for(p, int(np.abs(tgt).max()))
    tgt = _apply_slot_seed(tgt, np, _MONO_RANGE, seed)
    start, body = gr.encode_sound(p, tgt)
    body = _resolve_shared_boundary(emu, p, pred, start, body, tgt, None, np,
                                    gr=gr, log=log)
    body, head_stock = _apply_stock_head(emu, p, start, body, tgt, gr, np,
                                         log=log)
    _verify_encoded(emu, p, start, body, tgt, None, np, log=log,
                    exempt_head=head_stock)
    return start, body


def _encode_stereo(emu, sr, p, wav_path, np, pred=None, log=None,
                   gain_db=None, loop=False, orig=_LEVEL_REF_UNSET):
    from .spike2.emulator import emitted_length
    n = emitted_length(p["length"])
    fade_ms, headroom = _declick_params()
    if loop:
        fade_ms = 0.0                 # see _encode_mono: a looping record
    lp = _declick_lowpass_hz()
    lpf = _lowpass_loop if loop else _lowpass
    a = _load_wav(wav_path, True, np)
    # Band-limit each channel before the level fit (see _encode_mono).
    a = np.stack([lpf(a[:, 0], lp, np), lpf(a[:, 1], lp, np)], axis=1)
    a = _fit_level(a, _stock_render(emu, p, np, stereo=True)
                   if orig is _LEVEL_REF_UNSET else orig,
                   _STEREO_RANGE, np, headroom, gain_db=gain_db)
    L = _fit(np.clip(a[:, 0], -_STEREO_RANGE, _STEREO_RANGE), n, np,
             fade_ms=fade_ms)
    R = _fit(np.clip(a[:, 1], -_STEREO_RANGE, _STEREO_RANGE), n, np,
             fade_ms=fade_ms)
    _seed = _encode_seed_for(
        p, max(int(np.abs(L).max()), int(np.abs(R).max())))
    L = _apply_slot_seed(L, np, _STEREO_RANGE, _seed)
    R = _apply_slot_seed(R, np, _STEREO_RANGE, _seed)
    start, body = sr.encode_sound(p, L, R)
    body = _resolve_shared_boundary(emu, p, pred, start, body, L, R, np,
                                    sr=sr, log=log)
    body, head_stock = _apply_stock_head(emu, p, start, body, L, sr, np,
                                         log=log)
    _verify_encoded(emu, p, start, body, L, R, np, log=log,
                    exempt_head=head_stock)
    return start, body


# --------------------------------------------------------------------------
# Parallel re-encode (Write) — the cat-0 audio re-encode is the dominant cost of
# building an update when many sounds changed.  It's a pure-CPU emulation loop,
# so it fans across processes exactly like the decode path (_parallel_decode):
# each worker boots one emulator and re-encodes its share.  Per-sound encode is
# independent of order, so a parallel Write is byte-identical to a serial one;
# any pool failure falls back to a single in-process emulator.  Set
# PAD_STERN_SERIAL_ENCODE=1 to force the serial path (A/B verification).
# --------------------------------------------------------------------------
_FORCE_SERIAL_ENCODE = os.environ.get("PAD_STERN_SERIAL_ENCODE") == "1"


def _params_for(gr_path, img_path, log, progress):
    """Codec params for the card — from the Extract-time cache, or derived on a
    throwaway emulator if the cache is cold (rare for Write, which follows an
    Extract that already cached them).  Avoids booting an emulator on the common
    cache-hit path (the workers boot their own)."""
    _clear_stale_params_caches_once(log)   # a Write-only session never Extracts
    fp = _fingerprint(gr_path, img_path)
    cache = _cache_path(fp)
    if os.path.exists(cache):
        try:
            params = pickle.load(open(cache, "rb"))
            log("Loaded cached codec parameters (%d sounds)." % len(params),
                "info")
            return params
        except Exception:
            pass
    _note_cold_consumed(log)
    from .spike2.emulator import Spike2Emu
    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        return _load_or_derive_params(emu, gr_path, img_path, log, progress)
    finally:
        emu.close()


def _image_identity(img_path):
    """A cheap identity for a sound bank: its size and the md5 of its first and
    last 4 MB.  Taken as bytes rather than a path so a caller can capture the
    STOCK bank's identity before staging a grown copy over it."""
    h = hashlib.md5()
    sz = os.path.getsize(_lp(img_path))
    h.update(b"%d" % sz)
    with open(_lp(img_path), "rb") as f:
        h.update(f.read(4 << 20))
        if sz > (8 << 20):
            f.seek(-(4 << 20), 2)
            h.update(f.read(4 << 20))
    return h.digest()


def _audio_cache_base_key(gr_path, img_ident):
    """What every cached audio result depends on besides the sound itself:
    the card's identity (md5 of ``game_real`` plus the sound bank's
    :func:`_image_identity`), every ``PAD_STERN_*`` env var that shapes an
    encode (toggles that only pick a path through the write are excluded,
    see :attr:`_AudioBodyCache._PATH_ONLY`), and the app version.  Shared by
    the per-sound body cache and the verified-set cache so the two can never
    disagree about what "the same build" means."""
    from ... import __version__
    h = hashlib.md5()
    with open(_lp(gr_path), "rb") as f:
        h.update(f.read())
    h.update(img_ident)
    env = sorted((k, v) for k, v in os.environ.items()
                 if k.startswith("PAD_STERN_")
                 and k not in _AudioBodyCache._PATH_ONLY)
    h.update(repr(env).encode())
    h.update(__version__.encode())
    return h.hexdigest()


class _AudioBodyCache:
    """Persistent per-sound encode-result cache under
    ``<assets>/.write_cache/audio``.

    A Write re-encodes every replaced sound on every build even though almost
    none of them changed since the LAST build, and on a big mod that stage is
    minutes of emulator time per iteration (Godzilla Heisei 1.16: 123 sounds,
    2 min 21 s on a 16-core box, a multiple of that on the modder's rig).

    An entry replays only when EVERYTHING the encode depends on is unchanged;
    the key is an md5 over:

      * the card's identity — md5 of ``game_real`` plus ``image.bin``'s size
        and the md5 of its first and last 4 MB (the emulator the encode runs
        on boots from exactly these two files);
      * the sound's own param record AND its layout-predecessor's (the
        shared-boundary word settles against the predecessor's stock tail);
      * the replacement WAV's content (via the change scan's size+mtime hash
        cache, so it usually costs a stat);
      * every ``PAD_STERN_*`` env var that shapes the encode — toggles that
        only pick a path through the write (verify passes, blip-free
        composition, serial-vs-parallel) are excluded so flipping them does
        not dump the cache;
      * that sound's own per-clip loudness offset, so re-levelling ONE clip
        re-encodes that clip and replays every other one;
      * the app version (an encoder change must never replay old bodies).

    The value is the encode's ``(write_off, body)`` — or the skip verdict for
    a codec that can't re-encode bit-exact, which otherwise costs a full
    failed encode attempt every single build.  One entry per idx: storing a
    new key removes the idx's old file, so the cache never outgrows one body
    per replaced sound.  ``PAD_STERN_AUDIO_CACHE=0`` disables it entirely.
    """

    _PATH_ONLY = frozenset((
        "PAD_STERN_AUDIO_CACHE", "PAD_STERN_BLIP_FREE",
        "PAD_STERN_SERIAL_ENCODE", "PAD_STERN_SKIP_FINAL_VERIFY",
        "PAD_STERN_SKIP_KEYPATCH", "PAD_STERN_SKIP_MASTERDIR_FIX"))

    _MAGIC_BODY = b"PADAC1\n"
    _MAGIC_SKIP = b"PADAC0\n"

    def __init__(self, assets_dir, gr_path, img_path, byidx, ends, gains=None,
                 img_ident=None):
        self.assets_dir = assets_dir
        self.dir = os.path.join(assets_dir, ".write_cache", "audio")
        os.makedirs(self.dir, exist_ok=True)
        self.byidx = byidx
        self.ends = ends
        self.gains = gains or {}
        self.base_key = _audio_cache_base_key(
            gr_path, img_ident if img_ident is not None
            else _image_identity(img_path))

    @staticmethod
    def _fp_param(p):
        if p is None:
            return b"-"
        return pickle.dumps(sorted(p.items(), key=lambda kv: str(kv[0])), 4)

    def _key(self, idx, wav_path):
        wav_md5 = _scan_md5(self.assets_dir, wav_path)
        if wav_md5 is None:
            return None
        p = self.byidx.get(idx)
        if p is None:
            return None
        h = hashlib.md5()
        h.update(self.base_key.encode())
        h.update(self._fp_param(p))
        h.update(self._fp_param(self.ends.get(p["body_off"])))
        h.update(wav_md5.encode())
        h.update(b"g%.3f" % self.gains.get(idx, 0.0))
        return h.hexdigest()

    def _path(self, idx, key):
        return os.path.join(self.dir, "idx%05d-%s.bin" % (idx, key[:16]))

    def lookup(self, idx, wav_path):
        """``("body", off, bytes)`` | ``("skip",)`` | ``None`` (no entry)."""
        key = self._key(idx, wav_path)
        if key is None:
            return None
        try:
            with open(self._path(idx, key), "rb") as f:
                magic = f.read(len(self._MAGIC_BODY))
                if magic == self._MAGIC_SKIP:
                    return ("skip",)
                if magic != self._MAGIC_BODY:
                    return None
                off = struct.unpack("<Q", f.read(8))[0]
                body = f.read()
            return ("body", off, body) if body else None
        except OSError:
            return None

    def store(self, idx, wav_path, off, body):
        """Record *idx*'s fresh encode result (*body* None = skip verdict)."""
        key = self._key(idx, wav_path)
        if key is None:
            return
        target = self._path(idx, key)
        prefix = "idx%05d-" % idx
        try:
            for fn in os.listdir(self.dir):
                if fn.startswith(prefix) and fn != os.path.basename(target):
                    try:
                        os.remove(os.path.join(self.dir, fn))
                    except OSError:
                        pass
            tmp = target + ".tmp"
            with open(tmp, "wb") as f:
                if body is None:
                    f.write(self._MAGIC_SKIP)
                else:
                    f.write(self._MAGIC_BODY)
                    f.write(struct.pack("<Q", off))
                    f.write(body)
            os.replace(tmp, target)
        except OSError:
            pass                       # advisory, like the hash cache


class _FinalAudioCache:
    """The last VERIFIED set of re-encoded bodies, under
    ``<assets>/.write_cache/audio_final.bin``.

    The per-sound cache above spares a build the encodes, but three stages
    still ran on every build over the WHOLE replaced set, changed or not:
    the master-directory restore, the firmware integrity derive (a
    multi-minute emulator pass even on a fast machine) and the final decode
    of every replaced sound.  Their result depends on nothing but the card,
    the encode environment and the exact set of encoded bodies going in — so
    when this build's encoded set is byte-for-byte the set the last build
    restored and verified, the restored bodies are replayed and the three
    stages are skipped.  One entry, keyed by :func:`_audio_cache_base_key`
    plus a digest over every ``(offset, body)``; a build that grows the sound
    bank or applies the blip-free cave never uses it (their restore rules
    differ).  ``PAD_STERN_AUDIO_CACHE=0`` disables it with the body cache.
    """

    _MAGIC = b"PADAF1\n"

    def __init__(self, assets_dir, gr_path, img_ident):
        self.dir = os.path.join(assets_dir, ".write_cache")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "audio_final.bin")
        self.base_key = _audio_cache_base_key(gr_path, img_ident)

    def key_for(self, patches):
        """The digest of an encoded set ``{body_off: body}``."""
        h = hashlib.md5()
        h.update(self.base_key.encode())
        for off in sorted(patches):
            body = patches[off]
            h.update(b"%d:%d:" % (off, len(body)))
            h.update(hashlib.md5(body).digest())
        return h.hexdigest()

    def load(self, key):
        """The verified ``{body_off: body}`` stored under *key*, else None."""
        try:
            with open(self.path, "rb") as f:
                if f.read(len(self._MAGIC)) != self._MAGIC:
                    return None
                if f.readline().strip() != key.encode():
                    return None
                data = pickle.load(f)
        except (OSError, EOFError, ValueError, pickle.UnpicklingError):
            return None
        if not isinstance(data, dict) or not data:
            return None
        return {int(k): bytes(v) for k, v in data.items()}

    def store(self, key, patches):
        """Record *patches* as the verified set for *key* (advisory)."""
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(self._MAGIC)
                f.write(key.encode() + b"\n")
                pickle.dump(dict(patches), f, 4)
            os.replace(tmp, self.path)
        except OSError:
            pass


#: Bump whenever the grow, the chain encode, the re-point or the restore
#: changes what it writes for the same inputs: a kept grown-bank result from
#: before the change would otherwise replay bytes the new code never makes.
_GROWN_CACHE_REV = 1


def _grown_cache_sounds(assets_dir, audio_edits, grows, gains, loop_idx, own_used):
    """One tuple per sound the grow stage is handed, the part of the
    :class:`_GrownBankCache` key that names the sounds themselves.

    *audio_edits* is the ``{idx: wav}`` map as it enters the grow (the user's
    replacements after :func:`_classify_audio_edits`, plus the modes' own
    sounds :func:`_mode_sound_grow` and :func:`_mode_own_sounds_grow` put on
    their carriers, a music bed already tiled into its loop file), *grows*
    ``{idx: (room, wanted)}``, *gains* the per-clip loudness map, *loop_idx*
    the records that loop and *own_used* the modes' sounds with their carrier
    ``idx`` and ``request`` / ``sid``.  Every replacement is in here, not only
    the ones that grow: the kept result is the whole verified set, and a
    replaced stock sound that fits its slot changes those bytes too.  The WAV
    is named by a digest of its bytes, so a re-export of the same file with
    one sample different is a different sound."""
    names = {}
    for u in own_used or ():
        if u.get("idx") is None:
            continue
        names[int(u["idx"])] = (("sid", int(u["sid"])) if u.get("sid")
                                else ("request", int(u["request"])))
    out = []
    for idx, wav in audio_edits.items():
        h = hashlib.sha256()
        with open(_lp(_asset_path(assets_dir, wav)), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _room, want = grows.get(idx, (None, None))
        out.append((int(idx), names.get(int(idx)), h.hexdigest(),
                    round(float((gains or {}).get(idx, 0.0)), 3),
                    idx in (loop_idx or ()),
                    None if want is None else int(want)))
    return tuple(sorted(out))


class _GrownBankCache:
    """The last DERIVED AND VERIFIED grown sound bank, under
    ``<assets>/.write_cache/audio_grown.bin``.

    A build that grows the bank (a longer callout, or the modes' own sounds,
    which are always appended records) never took :class:`_FinalAudioCache`,
    so every press spent three emulator passes over a bank nothing had
    changed: the derive of the staged bank, the chain encode of the appended
    records and the master-directory restore -- 3 min 35 s of a 4 min Try it
    for ONE unchanged six-second end sound (the Modes tab audit, 2026-09-22).
    Their result depends on nothing but the stock card, the engine, the
    family switch and the exact sounds going in, so when those are what the
    last build derived from, its derived table, the verified bodies and the
    consumed map are replayed: the staged bank is still built (cheap), the
    play tables are still re-pointed from the kept table, and
    :func:`_assert_param_integrity` still boots the finished bank -- it is the
    always-on safety net, and a hit must not weaken it.

    One entry, keyed by :func:`_audio_cache_base_key` (the card, the encode
    environment, the app version), the stock card's :func:`_fingerprint`
    (taken BEFORE the grow moves the bank), the derive revision and
    :data:`_GROWN_CACHE_REV`, the family switch and
    :func:`_grown_cache_sounds`.  ``PAD_STERN_AUDIO_CACHE=0`` disables it
    with the other two.  A build with the blip-free cave on, or with the
    restore skipped, never uses it: the kept bodies are restored ones."""

    _MAGIC = b"PADAG1\n"

    def __init__(self, assets_dir, gr_path, stock_img_path, stock_ident):
        self.dir = os.path.join(assets_dir, ".write_cache")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "audio_grown.bin")
        self.base_key = _audio_cache_base_key(gr_path, stock_ident)
        self.stock_fp = _fingerprint(gr_path, stock_img_path)

    def key_for(self, family, sounds):
        """The digest of one grow: *family* is the mode editor family switch
        and *sounds* what :func:`_grown_cache_sounds` returned."""
        h = hashlib.md5()
        h.update(self.base_key.encode())
        h.update(self.stock_fp.encode())
        h.update(b"derive%d grown%d " % (_DERIVE_REV, _GROWN_CACHE_REV))
        h.update(b"family1" if family else b"family0")
        for entry in sounds:
            h.update(repr(entry).encode())
        return h.hexdigest()

    def load(self, key):
        """The kept result under *key* as ``{"params", "places", "patches",
        "reads"}``, or ``None`` when there is none (no file, another key, an
        older format).  Raises ``ValueError`` when the entry for THIS key
        cannot be read whole, so the caller can say so and derive again."""
        try:
            with open(self.path, "rb") as f:
                if f.read(len(self._MAGIC)) != self._MAGIC:
                    return None
                if f.readline().strip() != key.encode():
                    return None
                try:
                    data = pickle.load(f)
                except Exception as e:                        # noqa: BLE001
                    raise ValueError("the entry is damaged (%s)" % e) from None
        except OSError:
            return None
        try:
            params = [dict(p) for p in data["params"]]
            places = [tuple(pl) for pl in data["places"]]
            patches = {int(k): bytes(v) for k, v in data["patches"].items()}
            reads = data.get("reads")
        except (TypeError, KeyError, ValueError, AttributeError) as e:
            raise ValueError("the entry has the wrong shape (%s)" % e) from None
        if not params or not places or not patches:
            raise ValueError("the entry is empty")
        return {"params": params, "places": places, "patches": patches,
                "reads": set(int(r) for r in reads) if reads else None}

    def store(self, key, params, places, patches, reads):
        """Record this build's derived *params*, the staged *places*, the
        verified *patches* and the derive's consumed *reads* under *key*
        (advisory, like every cache write here)."""
        if not params or not places or not patches:
            return
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(self._MAGIC)
                f.write(key.encode() + b"\n")
                pickle.dump({"params": [dict(p) for p in params],
                             "places": [tuple(pl) for pl in places],
                             "patches": dict(patches),
                             "reads": sorted(int(r) for r in reads)
                             if reads else None}, f, 4)
            os.replace(tmp, self.path)
        except OSError:
            pass


def _grown_cache_mismatch(kept, places):
    """Why a kept grown-bank result does not describe the bank just staged,
    or ``""`` when it does.  The staged geometry (one placement per grown
    sound: its record, body offset and length) must be the one the kept
    table was derived from, and each grown row of that table must sit where
    the placement puts it; anything else is a table for another bank, and
    the cold derive is the only honest answer."""
    fresh = [tuple(pl) for pl in places or ()]
    if fresh != list(kept["places"]):
        return "the staged bank's layout differs from the kept one"
    by_idx = {pl[0]: pl for pl in fresh}
    for p in kept["params"]:
        if not p.get("grown"):
            continue
        pl = by_idx.get(p["idx"])
        if pl is None:
            return "idx %d is grown in the kept table but not staged" % p["idx"]
        if int(p["body_off"]) != int(pl[2]) or int(p["length"]) != int(pl[3]):
            return ("idx %d sits at %#x (%d samples) in the kept table but at "
                    "%#x (%d) in the staged bank"
                    % (p["idx"], p["body_off"], p["length"], pl[2], pl[3]))
    grown = {p["idx"] for p in kept["params"] if p.get("grown")}
    missing = sorted(set(by_idx) - grown)
    if missing:
        return "idx %d is staged but not grown in the kept table" % missing[0]
    return ""


def _encode_cat0_serial(gr_path, img_path, byidx, edits, np, log, progress,
                        cancel, gains=None):
    """Single-process cat-0 re-encode (the fallback + correctness reference).
    Returns ``(patches, skipped, results)`` — *results* maps each freshly
    encoded idx to its ``(off, body)`` so the caller can cache it.  *gains*
    maps idx -> that clip's total loudness dB (see :func:`_slot_gain_maps`);
    an idx it doesn't mention takes the build-wide offset."""
    gains = gains or {}
    from .spike2.codec import GenRecover, StereoRecover
    from .spike2.emulator import Spike2Emu
    log("Booting firmware codec engine...", "info")
    emu = Spike2Emu(gr_path, img_path)
    emu.boot()
    emu.warm_slots_for_grown(list(byidx.values()))
    patches, skipped, results = {}, [], {}
    gr = sr = None
    ends = _slot_end_map(byidx.values())
    try:
        for n, (idx, wav) in enumerate(edits):
            if cancel():
                return None, None, None
            p = byidx[idx]
            pred = ends.get(p["body_off"])
            if progress:
                progress(10 + int(n * 65 / max(len(edits), 1)), 100,
                         "Re-encoding idx %d" % idx)
            if p["chan"] == 2:
                sr = sr or StereoRecover(emu)
            else:
                gr = gr or GenRecover(emu)
            if not _recovery_valid(emu, gr, sr, p, np):
                skipped.append(idx)
                log("idx %d: re-encode isn't bit-exact for this sound's codec "
                    "(skipped -- left unchanged in the output)." % idx, "warning")
                continue
            try:
                gdb = gains.get(idx)
                off, body = (_encode_stereo(emu, sr, p, wav, np, pred=pred,
                                            log=log, gain_db=gdb)
                             if p["chan"] == 2
                             else _encode_mono(emu, gr, p, wav, np, pred=pred,
                                               log=log, gain_db=gdb))
            except _EncodeVerifyError as e:
                skipped.append(idx)
                log("%s -- skipped, left unchanged in the output." % e,
                    "warning")
                continue
            patches[off] = body
            results[idx] = (off, bytes(body))
            log("Re-encoded idx %d (%s, %d samples)."
                % (idx, "stereo" if p["chan"] == 2 else "mono", p["length"]),
                "info")
    finally:
        emu.close()
    return patches, sorted(skipped), results


def _encode_cat0_parallel(gr_path, img_path, params, edits, nworkers, np,
                          log, progress, cancel, gains=None):
    """Re-encode across ``nworkers`` spawned emulator processes (each boots once).

    Returns ``(patches, skipped, remaining, results)``: ``remaining`` is the
    list of edits that did NOT complete (empty on full success), *results*
    maps each freshly encoded idx to its ``(off, body)`` so the caller can
    cache it.  A pool that never boots a worker raises (so the caller does a
    full single-process pass).  But a pool that dies *part way* (e.g. a worker
    is killed) does NOT raise -- it returns what already finished plus the
    leftover edits, so the caller can finish just those in a single process
    instead of throwing away all the parallel work and re-encoding everything
    serially (the failure that turned a ~minutes job into hours).  Returns
    ``(None, None, None, None)`` if cancelled."""
    import multiprocessing as mp

    from .spike2.parallel import encode_one, encode_probe, init_encode_worker
    # Say what this step IS, not just that it is running.  A tester whose
    # replacements came off a working modded card asked why the app was
    # re-encoding sounds it had itself extracted, and guessed "a safety check".
    # It isn't: the extract hands you decoded WAV, and the card holds the
    # game's own compressed format, so every replaced sound has to be encoded
    # back into that slot's codec whatever it came from.
    log("Encoding %d replacement sound(s) into the card's own format across "
        "%d process(es) (the extract is decoded audio, so every replacement "
        "is encoded back)..." % (len(edits), nworkers), "info")
    ctx = mp.get_context("spawn")
    # Per-clip loudness rides in the worker's INITARGS rather than in each
    # task: the task tuple is the cache's edit list too, and one dict per
    # worker keeps both shapes unchanged.
    pool = ctx.Pool(nworkers, initializer=init_encode_worker,
                    initargs=(gr_path, img_path, params, gains or {}))
    patches, skipped, done_idx, results = {}, [], set(), {}
    try:
        # Confirm a worker actually booted (a stalled/unguarded pool raises here
        # and the caller falls back to the serial path).
        pool.apply_async(encode_probe).get(timeout=300)
        done = 0
        # chunksize=1: tasks vary by >1000x in cost (sub-second SFX to 8-minute
        # songs), so hand them out one at a time -- batching would strand several
        # long songs on one worker while others idle.  edits arrive longest-first
        # (see _encode_cat0_sounds), so the big tracks start immediately.
        it = pool.imap_unordered(encode_one, edits, chunksize=1)
        while True:
            try:
                idx, body_off, body, valid = next(it)
            except StopIteration:
                break
            except Exception as e:
                # A worker died mid-run.  Keep everything finished so far and let
                # the caller re-encode only the leftovers in a single process.
                remaining = [(i, w) for (i, w) in edits if i not in done_idx]
                log("Parallel re-encode interrupted (%s); %d of %d sound(s) "
                    "already done, finishing the remaining %d in a single "
                    "process." % (e, len(done_idx), len(edits), len(remaining)),
                    "warning")
                pool.terminate()
                return patches, sorted(skipped), remaining, results
            done += 1
            done_idx.add(idx)
            if valid and body is not None:
                patches[body_off] = body
                results[idx] = (body_off, body)
                log("Re-encoded idx %d." % idx, "info")
            elif body_off is not None:
                skipped.append(idx)
                log("idx %d: re-encode isn't bit-exact for this sound's codec "
                    "(skipped -- left unchanged)." % idx, "warning")
            if progress and (done % 4 == 0 or done == len(edits)):
                progress(10 + int(done * 65 / max(len(edits), 1)), 100,
                         "Re-encoding %d/%d" % (done, len(edits)))
            if cancel():
                pool.terminate()
                return None, None, None, None
        pool.close()
    finally:
        pool.join()
    return patches, sorted(skipped), [], results


# --------------------------------------------------------------------------
# Blip-free callouts — derive-read redirect firmware cave (the callout "blip"
# COMPLETE fix).  OPT-IN since v0.104.0 (PAD_STERN_BLIP_FREE=1 / the GUI's
# Advanced Audio Options checkbox); PAD_STERN_SKIP_KEYPATCH=1 also forces it
# off — see _pathA_enabled, and the field record at the end of this comment.
#
# The firmware's boot-derive reads two ~512 B "windows" out of each sound's body
# to set up that sound's (and, via a forward chain, every later sound's) codec
# params.  A re-encoded callout changes those bytes, so a plain write desyncs the
# chain and the machine reboots on audio.  The standard escape hatch
# (_restore_masterdir_consumed) reverts just those window bytes to stock -- but
# the windows sit inside the audible body, so the callout plays a ~6 ms scrap of
# the ORIGINAL at each window: the "blip".
#
# This removes the blip at the source: instead of reverting card bytes, it patches
# game_real with a small code cave that redirects the derive's window reads (for
# the replaced sounds only) to a STOCK copy stashed inside the firmware.  The
# derive then builds fully-stock params from a card whose bodies are ENTIRELY our
# audio -> our audio plays for the whole callout; no blip, no hole.  HW-confirmed
# on Led Zeppelin LE 1.22 (a tester, 2026-07-25).
#
# GENERIC across Spike 2 titles: the window-read function is the same compiled
# routine on every firmware seen (LZ LE/non-LE, TMNT) -- only its address moves --
# so it's located by its unique 3-instruction prologue signature and confirmed
# dynamically (it must actually perform the image window read).
#
# WHERE the cave lives was the hard part, and got it badly wrong once.  Until
# v0.94.0 it went in the first reloc-free zero run of the RW data segment, on the
# reasoning that a zero run with no relocations pointing into it must be spare.
# It isn't: a zero-initialised global lives in .data and needs no relocations
# either, so live storage and dead padding are indistinguishable to that rule.
# On Elvira's House of Horrors 1.13.0 the run it picked (0x7FEEC0) is element 0
# of the NODE BUS board table -- 5 elements of stride 0x798, node ids 0/1/7/8/9,
# registered by the init loop at 0x1f0de8 into the table at 0x88B2A0 -- so the
# build wrote executable code into node board 0's state buffer.  Reported from
# the field as a machine that boots very slowly, runs slowly, throws node board
# errors and cannot start a game (a tester, 2026-07-28).  Section headers tile the RW
# segment exactly on all 17 firmwares on hand, so there was never any genuinely
# unclaimed space to find there; LZ only worked because the object it happened to
# land on goes unused, and even that shifts with the number of replaced sounds.
#
# So the cave no longer looks for space -- it MAKES it.  _append_cave_segment
# appends the cave to game_real and maps it with a PT_LOAD of its own, over
# address space no segment claims.  Nothing can own those bytes because they did
# not exist until we wrote them.  The cost is that game_real stops being
# size-neutral: the write path has to grow the file through the ext4 driver and
# refresh its .sidx size fields as well as its digests.
#
# Anything the locator can't pin down, a firmware with no free address space in
# branch reach, a host that can't grow ext4 files, or a firmware that fails the
# post-build integrity assert falls back to the standard
# _restore_masterdir_consumed build.  PAD_STERN_BLIP_FREE=1 opts IN;
# PAD_STERN_SKIP_KEYPATCH=1 forces the fallback everywhere and wins.
#
# WHY THIS CAVE HAD NEVER ACTUALLY BOOTED, and what was wrong with it.  Every
# claim of hardware confirmation above belongs to the OLD, unsafe data-segment
# placement (Led Zeppelin LE 1.22, 2026-07-25, pre-v0.94.0).  What v0.94.0
# proved about the own-segment placement it proved OFFLINE, in the emulator --
# and Spike2Emu maps each PT_LOAD's full p_memsz itself (spike2/emulator.py, the
# mem_map over `_algn(vaddr + memsz)`), so it cannot see how a real ARM Linux
# loader treats an appended segment.  Worse, from v0.94.0 through v0.102.2 the
# rebuilt firmware was deleted before it could be copied onto the card on every
# host that has the ext4 driver (see PAD-6 / grow_plan["cleanup"]), so no user
# ever booted this cave either: driver hosts got a card the machine rejected,
# and every card that DID work was a non-driver host silently falling back to
# the standard build.
#
# v0.102.3 fixed the delivery, which made it the first release ever to put this
# cave in front of a machine.  The first report back was a James Bond Premium
# 1.06.0 that reboots partway through "Initializing" and loops there (a tester,
# 2026-08-01) -- the same tester whose pre-v0.94.0 card froze at the game logo
# on the old placement.
#
# The ELF geometry was audited across all 37 vendor firmwares and came back
# clean (see _append_cave_segment, which records the result so it isn't
# re-derived).  Both faults found are in the cave's RUNTIME behaviour, and both
# end the same way -- a window that should have been redirected wasn't, so the
# boot-derive read the re-encoded bytes the cave exists to hide from it, which
# desyncs the codec forward chain, and a desynced chain is a reboot:
#
#   1. It latched the image's mapped base from the first call with r2 == 0x200,
#      i.e. it took "a 512-byte read" to mean "the master directory's first
#      window read".  Nothing established that; the routine has four call sites
#      and _capture_first_window_off has always had to reject calls whose r1
#      lands outside the image.  A foreign call arriving first poisons the base
#      for the life of the process and NOTHING is redirected after that.
#   2. It only redirected reads with r2 == 0x200 exactly.  But 0x200 is not a
#      constant the firmware believes in: the stream reader computes
#      `bic r2, r5, #0x3f` -- the run length rounded down to 64 -- so a window
#      run that isn't a full 512 bytes arrives as some other multiple of 64 and
#      was passed straight through.  The consumed map the table is built from
#      has no size filter, so the table always described those runs; only the
#      cave's own gate discarded them.
#
# _asm_derive_redirect_cave now identifies the calibrating read by the card's
# own content instead of by call order, and decides redirects on the file offset
# alone.  Both fixes are reasoned out in full there.  Measured on Bond 1.06
# during the cat-0 derive: 4 static call sites (3 hard-coding r2=0x40, one
# variable), 200/200 of the r2==0x200 calls in-image, the 0x40 scratch calls all
# out-of-image -- so (1) is an unguarded assumption that happens to hold for
# that pass, while (2) bites whenever a run isn't a full window.
#
# Both fixes are verified at instruction level (tests drive the emitted cave
# under unicorn through exactly the call order that broke it, and through a
# window read that isn't 512 bytes) and end to end against the real Bond card:
# _assert_param_integrity passes on the rebuilt firmware with all 2351 sounds
# keeping valid parameters, while the same patches against STOCK firmware shift
# 2348 of them -- so the check is sensitive and the cave is what makes it pass.
# A trace over that derive shows 9404 entries into the cave, exactly one
# satisfying the new signature condition, latching the true mapping base.
#
# That evidence was judged good enough to keep the cave ON BY DEFAULT in
# v0.102.5 (David's call, 2026-08-01).  THE FIELD SAYS NO (PAD-18, same tester,
# same James Bond Premium 1.06.0, v0.102.6): with the checkbox ticked the
# machine loops through Initializing exactly as before, and with it cleared the
# card loads and the replaced sound plays correctly.  So neither v0.102.5 fix
# was the cause, and the running score for this feature's own-segment placement
# is three deliveries, one machine, three boot loops, zero confirmed boots.
#
# It is now OPT-IN (default off) and no longer describes itself as the standard
# build.  Read that as a statement about what is KNOWN, not a verdict on the
# design: every argument for it is still an offline one, and offline agreement
# is precisely what was believed the three times it shipped broken.  The two
# v0.102.5 fixes are kept -- they are real defects with tests pinning them, and
# whoever picks this up next should not have to rediscover them -- but they are
# no longer evidence of anything about hardware.
#
# AND NEITHER OF THEM WAS EVER GOING TO FIX BOND.  Measured on the real card
# (PAD-18) over the full cat-0 derive, which is the same trace the paragraph
# above quotes 9404 from:
#
#   * of those 9404 entries at fn=0x2ef45c, 4702 carry r2 == 0x200 and ALL 4702
#     have r1 inside the image; the other 4702 are the r2 == 0x40 scratch calls,
#     all pointing at ctx+0x158, out of image.  There is no out-of-image 0x200
#     call anywhere in the pass -- so fault (1), a foreign call arriving first
#     and poisoning the base, has nothing to bite on here;
#   * every window read is exactly 0x200, and every consumed run inside a body
#     is exactly 512 contiguous bytes.  Fault (2)'s premise -- a run that isn't
#     a full window arriving as some other multiple of 64 -- never occurs.
#
# Those numbers were already in this comment.  What was missing was the
# conclusion: the v0.102.6 retest could not have come back any other way, and
# reporting the fixes to the tester as the answer was a mistake made from data
# already in hand.  The fixes are still right in general; they were never
# Bond's fault.
#
# WORSE, THE SYMPTOM DOES NOT MATCH A DESYNC AT ALL.  The model this whole cave
# is reasoned about says a desynced forward chain reboots the machine WHEN
# AUDIO PLAYS, and the same tester's pre-v0.94.0 desync did exactly that: it
# got through the initialization screen and froze at the game logo.  What the
# caved card does is reboot mid-init, deterministically, always after the
# second of the four progress periods, before the logo.  Both v0.102.5 faults
# only change WHETHER A WINDOW GETS REDIRECTED, i.e. they only move the card
# between "desync" and "no desync" -- neither can produce a hard stop at a
# fixed, earlier point.  Three releases of work have been aimed at the wrong
# failure.  A likelier shape is that the process dies on or near its FIRST
# ENTRY into the cave, or that something rejects the grown binary before the
# codec matters at all.
#
# Nothing offline can currently see that, which is the third thing to know:
# Spike2Emu.boot() enters fn ZERO times, stock or caved.  Every offline result
# about this cave comes from derive_params(), so the phase of a real boot where
# the machine actually dies has no coverage here at all.
#
# What the same report also establishes is how little is being given up: the
# tester replaced a sound with the cave off, listened for artefacts, and could
# not hear the blip the cave exists to remove ("I did not hear any other
# artifacts besides the song"). A ~6 ms scrap at two points inside a callout is
# apparently at or below the audible floor on a real cabinet, which makes an
# unbooted firmware patch a bad trade for it by default.
#
# WHERE TO LOOK NEXT, for whoever has a machine.  Ranked by what the symptom
# above actually points at, NOT by what is easiest to change here:
#
#   1. The process dies at/near its first entry into the cave, for a reason
#      unicorn cannot show -- the RWX file mapping refused or not actually
#      writable, `str r8,[r4]` into BASEVAR faulting, an exec-permission policy.
#      This fits "always after two periods" and is present in v0.102.3 and
#      v0.102.6 alike.  Settled cheaply: build a cave that never WRITES memory
#      (no BASEVAR -- e.g. a second, R/W-only PT_LOAD, or no caching at all).
#      Getting past two periods convicts the write; a serial console or dmesg
#      off the machine names it outright and is worth more than any of this.
#   2. Something outside the game rejects the grown / re-laid-out binary before
#      the codec matters.  Settled by a build with p_flags=5 and no BASEVAR, or
#      one placed without growing the file.
#   3. The SIG compare does UNALIGNED word loads (four `ldr r6,[r1,#n]` below).
#      On Bond FIRST_OFF=0x58df6 is 2 mod 4 and 2344 of the 4702 window
#      pointers are 2 mod 4 -- and the stock transform assembles its own
#      message block with 64 `ldrb`s precisely because that pointer is
#      unaligned.  It cannot fault (r2 >= 0x200 guarantees the bytes are
#      there), but on a core or kernel that doesn't give correct unaligned LDR
#      the signature never matches, the base never latches and nothing is
#      redirected.  A byte-wise compare removes the hazard for free.  Note it
#      predicts the WRONG symptom (a late, audio-time failure) and postdates
#      v0.102.3, so it is not the boot loop -- fix it while you are in here,
#      not as the answer.
#   4. The redirect has no caller discriminator.  fn is the SHA-1 block
#      transform; its wrapper at 0x2f0314 has 9 call sites across at least 3
#      functions, one of them (0x25e914) the very routine valpatch stubs out.
#      Since v0.102.5 the redirect keys on the file offset alone, so any caller
#      whose data pointer lands in a table window silently gets stock bytes.
#      Not shown to fire; structurally unguarded.
#
# The placement lead in _append_cave_segment (Bond is one of 4 titles with no
# text/data gap, so its cave lands exactly on the stock mm->start_brk) has been
# re-derived across 36 vendor firmwares and comes back clean AGAIN, including
# Bond concretely: in-loop set_brk maps [0x814000,0x8ba000) and clears 0xa1c
# bytes at 0x8135e4, the cave maps [0x8ba000,0x8bb000) exactly adjacent with no
# overlap, and the post-loop set_brk is a no-op that walks start_brk to
# 0x8bb000.  Bond's phdr table is also SORTED by p_vaddr, so the unsorted-table
# caveat belongs to the 33 gap-placed titles and not to the one that fails.
# Keep the lead, but note the trap in reading it as "the difference between
# Bond and the cards that work": there are no cards that work.  The own-segment
# cave has only ever reached one machine, so the 33/4 split explains nothing on
# its own.  A Led Zeppelin test is still worth doing -- a boot loop there
# refutes the placement theory outright -- but it ranks below 1 and 2.
#
# Deliberately NOT changed here, and the reason matters: the next hardware test
# needs to be against the SAME cave the three existing data points describe.
# Shipping 3 and 4 now would buy a little correctness and cost the only clean
# A/B available, which is the mistake v0.102.5 made -- plausible fixes to a
# fault nobody had localised, reported as the answer.
#
# THE LED ZEPPELIN TEST COULD NOT HAPPEN, and until PAD-56 nobody knew why.  The
# cave carries a stock copy of every window it redirects -- ~1 KB per replaced
# sound -- and it had to land within a single ARM branch of the window-read
# function.  On Led Zeppelin LE 1.22 the only free region in reach is the 28 KB
# text/data gap, i.e. a ceiling of about 27 sounds; the other free region starts
# 64 MB up.  So every real build silently placed nothing and fell back: a tester
# replacing 201 sounds got the box saying NOT applied, a 210876-byte cave and no
# room, and heard the scrap on 179 of them (PAD-56, v0.119.7, reproduced offline
# against his own firmware).  The ceiling, not the checkbox, is why this feature
# has one machine's worth of evidence.
#
# The hops are now long where they have to be (an `ldr pc,[pc,#-4]` veneer in,
# an `ldr pc,=ret` back out) and placement still PREFERS an in-reach region, so
# a build that placed before places at the same VA behind the same branch and
# the A/B above survives intact.  What is new is that a full-size Led Zeppelin
# build now lands on the synthetic region above the top PT_LOAD -- the same
# top-of-heap placement as Bond, and 52 pages of it rather than one.  That is
# the placement lead below, so if the first LZ report is a boot loop, read it as
# evidence about the placement and not about the title.
# --------------------------------------------------------------------------
# The window-read function's 3-instruction prologue -- push {r4-r8,sb,sl,fp,lr} /
# sub sp,sp,#0x16c / add sb,r1,#0x40 -- uniquely identifies it on every Spike 2
# firmware examined, each at a different address.  The cave replicates these three
# (all position-independent) and resumes at fn+12.
_CAVE_SIG = (0xE92D4FF0, 0xE24DDF5B, 0xE2819040)
_CAVE_SIG_BYTES = struct.pack("<III", *_CAVE_SIG)
_PATHA_SEED_DBFS = -45.0    # anti-degenerate seed level for a near-silent replacement
_CAVE_MAX_BRANCH = 1 << 25  # ARM b reach (+/-32 MB); the fn<->cave hop must fit
_PT_GNU_STACK = 0x6474E551  # advisory phdr the cave's PT_LOAD is carved from


_BLIP_FREE_OFF_REASON = ("not switched on for this build; it is off by default "
                         "(Advanced Audio Options)")


def _pathA_enabled():
    """True when the blip-free firmware cave should be built for this write.

    **Opt-in since v0.104.0**, surfaced as the "Blip-free callouts" checkbox in
    the GUI's Advanced Audio Options.  It requires an explicit
    ``PAD_STERN_BLIP_FREE=1``; ``PAD_STERN_SKIP_KEYPATCH=1`` forces it off and
    wins, so anything that already sets the historical kill switch keeps
    working.  Either way the build falls back to
    :func:`_restore_masterdir_consumed`, which touches no game code at all --
    and so does any firmware or host the cave can't safely handle.

    Unset means OFF, and the polarity is the point.  Headless callers and the
    spawned encode workers inherit ``os.environ`` without ever passing through
    the GUI's env mirroring, so whatever "unset" means is what they build; it
    now means the build that changes no game code.  Requiring "1" rather than
    accepting "not 0" is the same argument: a stale or misspelled value fails
    towards the standard build instead of towards a firmware patch that has
    boot-looped a real machine on every release it has been delivered by.
    """
    if os.environ.get("PAD_STERN_SKIP_KEYPATCH") == "1":
        return False
    return os.environ.get("PAD_STERN_BLIP_FREE") == "1"


def _cave_va2off(segs, va):
    """File offset of virtual address *va* in the firmware ELF (its file-backed
    PT_LOAD)."""
    for v, o, fz, _mz in segs:
        if v <= va < v + fz:
            return o + (va - v)
    raise ValueError("VA 0x%x is not in any file-backed segment" % va)


def _iter_phdrs(raw):
    """Yield ``(ph_off, p_vaddr, p_offset, p_filesz, p_memsz, p_flags)`` for each
    PT_LOAD program header."""
    e_phoff = struct.unpack_from("<I", raw, 0x1c)[0]
    e_phentsize = struct.unpack_from("<H", raw, 0x2a)[0]
    e_phnum = struct.unpack_from("<H", raw, 0x2c)[0]
    for i in range(e_phnum):
        ph = e_phoff + i * e_phentsize
        if struct.unpack_from("<I", raw, ph + 0)[0] != 1:  # PT_LOAD
            continue
        yield (ph, struct.unpack_from("<I", raw, ph + 8)[0],
               struct.unpack_from("<I", raw, ph + 4)[0],
               struct.unpack_from("<I", raw, ph + 16)[0],
               struct.unpack_from("<I", raw, ph + 20)[0],
               struct.unpack_from("<I", raw, ph + 24)[0])


def _exec_seg(raw):
    """``(vaddr, offset, filesz)`` of the firmware's executable (R-X) PT_LOAD."""
    for _ph, va, off, fz, _mz, fl in _iter_phdrs(raw):
        if fl & 1:                 # PF_X
            return va, off, fz
    raise ValueError("no executable PT_LOAD segment")


def _locate_window_read_fn(raw):
    """VA of the masterdir window-read function: the unique occurrence of the
    3-word prologue signature inside the executable segment.  Returns the VA, or
    ``None`` if the signature is absent or (defensively) appears more than once
    -- either case falls the build back to the standard restore path."""
    va, off, fz = _exec_seg(raw)
    hits = []
    i = raw.find(_CAVE_SIG_BYTES, off, off + fz)
    while i != -1:
        hits.append(va + (i - off))
        i = raw.find(_CAVE_SIG_BYTES, i + 4, off + fz)
    return hits[0] if len(hits) == 1 else None


_CAVE_SIG_WORDS = 4              # 16 bytes of card content that identify FIRST_OFF
_CAVE_NCODE = 55                 # code + literals + BASEVAR + signature, in words


def _asm_derive_redirect_cave(raw, va2off, fn, ret, cave_va, table_va,
                              first_off, basevar_va, sig_va):
    """Assemble the self-calibrating derive-read redirect cave (ARM, little-
    endian) for the window-read function at *fn*, resuming at *ret* (= fn+12).

    The cave turns a live source pointer into a FILE OFFSET so the redirect
    table can be card-position-independent, which needs the address the image is
    mapped at.  That is only knowable at runtime, so the cave recovers it as
    ``base = r1 - FIRST_OFF`` on the master directory's first window read and
    caches it in a writable word (BASEVAR).  Thereafter ``fileoff = r1 - base``
    is matched against the table; a hit redirects ``r1`` into that window's stock
    copy, a miss passes through untouched.

    IDENTIFYING that first read is the delicate part, and getting it wrong is
    silent.  The original cave took "the first call with ``r2 == 0x200``" as the
    first window read.  That is not sound: this routine is a shared helper, and
    ``_capture_first_window_off`` -- the build-time code that measures FIRST_OFF
    in the first place -- has always had to reject calls whose ``r1`` points
    outside the image, which is precisely an admission that ``r2 == 0x200`` on
    its own does not mean "master directory window".  One such call arriving
    ahead of the real one poisons BASEVAR for the life of the process: every
    fileoff is then wrong, nothing matches the table, no window is redirected,
    and the boot-derive reads the re-encoded bytes it was supposed to be
    shielded from.  That desyncs the codec forward chain, which is the failure
    the whole cave exists to prevent and which the machine answers by rebooting.
    Nothing catches it in the emulator, because ``_assert_param_integrity``
    calls ``derive_params()`` directly, so the first ``r2 == 0x200`` call it ever
    sees IS the right one -- the ordering that makes this fail only exists on a
    real boot, where the whole init runs first (a tester's James Bond Premium
    1.06.0, rebooting partway through "Initializing", 2026-08-01).

    So the base is no longer latched on position.  It is latched on EVIDENCE: 16
    bytes of the card's own content at FIRST_OFF are baked into the cave (SIG),
    and the base is taken only from a call whose ``r1`` actually points at those
    bytes.  Anything else passes through without touching BASEVAR.  The check
    runs on every call rather than only while BASEVAR is zero, so a second
    derive pass, or the image being mapped somewhere else, re-latches instead of
    silently going stale.  Until a match has been seen there is no base and
    nothing is redirected, which is the safe direction: an un-redirected read
    is the old standard build's behaviour, not a corrupt one.

    ``r2 == 0x200`` now gates ONLY the calibration, not the redirect, and that
    is a second fix rather than a tidy-up.  0x200 is not a constant the firmware
    believes in: of the four call sites this routine has (identical layout on
    all 37 vendor builds), three hard-code ``mov r2,#0x40`` and the fourth --
    the master-directory stream reader, the only one that can ever present a
    window -- computes ``bic r2, r5, #0x3f``, i.e. the run length rounded down
    to 64.  It is 0x200 for a full window and something else for any run that
    isn't, and the old cave answered a non-0x200 window read by passing it
    straight through.  That leaves that window un-redirected while the card
    carries re-encoded bytes underneath it, which is the same desync-the-chain
    reboot as a poisoned base, just for one sound instead of all of them.  The
    consumed map the table is built from comes from a memory-read hook with no
    size filter, so the table always described those runs correctly; only the
    cave's own gate threw them away.  Redirecting is now decided purely by
    whether the file offset falls in a table window.  The ``r2 == 0x200`` test
    survives in front of the signature check because that check dereferences
    ``r1``, and a 512-byte read is the case we know carries a readable image
    pointer; the scratch calls fall through to the table scan, where their
    out-of-image pointer matches nothing and passes through untouched.

    The cave replicates the function's 3-word prologue (push / sub sp / add sb
    -- all position-independent) and returns to *ret*.  ``game_real`` is ET_EXEC,
    so the absolute VAs baked as literals are HW-valid.

    The hop BACK to *ret* is a plain ARM ``b`` while the cave is within +/-32 MB
    of it, and an absolute ``ldr pc,=ret`` when it isn't.  ``br`` masks its
    offset to 24 bits, so a cave placed further out would otherwise return to a
    wrapped address rather than fail -- and a cave that far out is now normal
    (see :func:`_append_cave_segment`)."""
    def w(x):
        return struct.pack("<I", x & 0xffffffff)

    def br(cond, frm, to):
        return w((cond << 28) | (0xA << 24) | (((to - (frm + 8)) >> 2) & 0xFFFFFF))
    W_push = struct.unpack_from("<I", raw, va2off(fn))[0]
    W_subsp = struct.unpack_from("<I", raw, va2off(fn + 4))[0]
    W_addsb = struct.unpack_from("<I", raw, va2off(fn + 8))[0]

    def iva(i):
        return cave_va + i * 4
    LIT_BASE, LIT_SIG, LIT_FIRST, LIT_TABLE = (iva(45), iva(46), iva(47),
                                               iva(48))
    LIT_RET = iva(54)

    def ldrpc(rt, frm, lit):
        return w(0xE59F0000 | (rt << 12) | (lit - (frm + 8)))
    DONE, NOLATCH, HAVE_BASE, SCAN = iva(43), iva(26), iva(30), iva(32)
    # Return hop: relative while it reaches, absolute (via LIT_RET) when the
    # cave is out of branch range of the function it came from.
    goback = (br(0xE, iva(44), ret)
              if abs(ret - (iva(44) + 8)) < _CAVE_MAX_BRANCH
              else ldrpc(15, iva(44), LIT_RET))
    words = [
        w(W_push), w(W_subsp),                  # 0,1  replicated prologue
        w(0xE3520C02),                          # 2  cmp r2,#0x200 (calibration candidate?)
        br(0x1, iva(3), NOLATCH),               # 3  bne nolatch -> still eligible to redirect
        # --- is r1 really pointing at the card bytes that live at FIRST_OFF? ---
        ldrpc(5, iva(4), LIT_SIG),              # 4  ldr r5,=&SIG
        w(0xE5916000), w(0xE5957000),           # 5,6   ldr r6,[r1]    ; ldr r7,[r5]
        w(0xE1560007), br(0x1, iva(8), NOLATCH),  # 7 cmp r6,r7 ; 8 bne nolatch
        w(0xE5916004), w(0xE5957004),           # 9,10  ldr r6,[r1,#4] ; ldr r7,[r5,#4]
        w(0xE1560007), br(0x1, iva(12), NOLATCH),  # 11 cmp ; 12 bne nolatch
        w(0xE5916008), w(0xE5957008),           # 13,14 ldr r6,[r1,#8] ; ldr r7,[r5,#8]
        w(0xE1560007), br(0x1, iva(16), NOLATCH),  # 15 cmp ; 16 bne nolatch
        w(0xE591600C), w(0xE595700C),           # 17,18 ldr r6,[r1,#12]; ldr r7,[r5,#12]
        w(0xE1560007), br(0x1, iva(20), NOLATCH),  # 19 cmp ; 20 bne nolatch
        # --- matched: (re)latch base = r1 - FIRST_OFF ---
        ldrpc(4, iva(21), LIT_BASE),            # 21 ldr r4,=&BASEVAR
        ldrpc(5, iva(22), LIT_FIRST),           # 22 ldr r5,=FIRST_OFF
        w(0xE0418005),                          # 23 sub r8,r1,r5
        w(0xE5848000),                          # 24 str r8,[r4]
        br(0xE, iva(25), HAVE_BASE),            # 25 b have_base   (r8 = base)
        ldrpc(4, iva(26), LIT_BASE),            # 26 nolatch: ldr r4,=&BASEVAR
        w(0xE5948000),                          # 27 ldr r8,[r4]
        w(0xE3580000),                          # 28 cmp r8,#0
        br(0x0, iva(29), DONE),                 # 29 beq done   (no base yet)
        w(0xE0418008),                          # 30 have_base: sub r8,r1,r8  (fileoff)
        ldrpc(4, iva(31), LIT_TABLE),           # 31 ldr r4,=&TABLE
        w(0xE4945004),                          # 32 scan: ldr r5,[r4],#4   (lo)
        w(0xE3550000),                          # 33 cmp r5,#0
        br(0x0, iva(34), DONE),                 # 34 beq done  (zero sentinel)
        w(0xE4946004), w(0xE4947004),           # 35,36 ldr r6/r7,[r4],#4 (hi, stockbuf)
        w(0xE1580005), br(0x3, iva(38), SCAN),  # 37 cmp r8,r5 ; 38 blo scan
        w(0xE1580006), br(0x2, iva(40), SCAN),  # 39 cmp r8,r6 ; 40 bhs scan
        w(0xE0488005), w(0xE0871008),           # 41 sub r8,r8,r5 ; 42 add r1,r7,r8
        w(W_addsb),                             # 43 done: add sb,r1,#0x40
        goback,                                 # 44 b ret / ldr pc,=ret (fn+12)
        w(basevar_va), w(sig_va), w(first_off), w(table_va),  # 45-48 literals
        w(0),                                   # 49 BASEVAR (writable, init 0)
        w(0), w(0), w(0), w(0),                 # 50-53 SIG (filled by the caller)
        w(ret),                                 # 54 RET literal (long return)
    ]
    assert len(words) == _CAVE_NCODE, len(words)
    return b"".join(words)


def _card_bytes_at(img_path, patches, off, n):
    """The *n* bytes that will be at image file offset *off* ON THE CARD, i.e.
    the stock image with *patches* (``{body_off: body}``) overlaid.

    The cave's calibration signature has to be read from this, not from the
    stock image: by the time the machine performs that read, the replaced bodies
    are already on the card, so a signature taken from stock would simply never
    match if the first window happens to land inside one."""
    with open(img_path, "rb") as f:
        f.seek(off)
        buf = bytearray(f.read(n))
    for boff, body in patches.items():
        lo, hi = max(off, boff), min(off + n, boff + len(body))
        if lo < hi:
            buf[lo - off:hi - off] = body[lo - boff:hi - boff]
    return bytes(buf)


def _capture_first_window_off(gr_path, img_path, fn):
    """File offset of the FIRST masterdir window read (``r2 == 0x200``, source
    pointing into the image) the boot-derive performs at *fn* -- the FIRST_OFF the
    self-cal cave subtracts from the live source pointer to recover the image mmap
    base.  Doubles as the dynamic confirmation that *fn* really is the window
    reader: returns ``None`` if no in-image window read is ever observed there
    (wrong function, or unsupported firmware).  Boots and derives only until that
    read, then stops."""
    from unicorn.arm_const import UC_ARM_REG_R1, UC_ARM_REG_R2

    from .spike2 import emulator as EM
    from .spike2.emulator import Spike2Emu
    img_size = os.path.getsize(img_path)
    emu = Spike2Emu(gr_path, img_path)
    got = {}

    def at_fn(eng):
        m = eng.mu
        if m.reg_read(UC_ARM_REG_R2) == 0x200 and "off" not in got:
            off = m.reg_read(UC_ARM_REG_R1) - EM.DESC_BASE
            if 0 <= off < img_size:        # a real image window read
                got["off"] = off
                m.emu_stop()
    emu.boot()
    emu.extra[fn] = at_fn
    try:
        emu.derive_params()
    except Exception:
        pass
    finally:
        emu.extra.pop(fn, None)
        emu.close()
    return got.get("off")


def _replaced_consumed_offsets(gr_path, img_path, patches, np, log=None,
                               progress=None):
    """For each replaced body in *patches* (``{off: body}``), the sorted image
    file offsets the boot-derive CONSUMES within it (the two window runs).

    Uses the Extract-time consumed cache when present; otherwise runs one
    master-directory derive with a read hook over just the replaced extents -- so
    a legacy cache that stored params but not the consumed map still yields a
    blip-free build instead of silently falling back to the standard one.

    That fallback derive is the expensive one (minutes on a big catalog), so it
    reports progress and says why it is running: without both, a Write whose
    cache had gone reads as a frozen app -- see :func:`_note_cold_consumed`."""
    out = {}
    cached = _load_consumed(gr_path, img_path)
    if cached is not None and len(cached):
        cached = np.asarray(cached, np.int64)
        for off, body in patches.items():
            lo = int(np.searchsorted(cached, off, "left"))
            hi = int(np.searchsorted(cached, off + len(body), "left"))
            out[off] = cached[lo:hi]
        return out
    from unicorn import UC_HOOK_MEM_READ

    from .spike2 import emulator as EM
    from .spike2.emulator import Spike2Emu
    reads = {off: set() for off in patches}

    def _mk(b0, e0, acc):
        def on_read(mu, access, addr, size, value, ud):
            o = addr - EM.DESC_BASE
            for k in range(size):
                if b0 <= o + k < e0:
                    acc.add(o + k)
        return on_read
    _note_cold_consumed(log)
    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        for off, body in patches.items():
            end = off + len(body)
            emu.mu.hook_add(UC_HOOK_MEM_READ, _mk(off, end, reads[off]),
                            begin=(EM.DESC_BASE + off) & ~0xfff,
                            end=((EM.DESC_BASE + end) + 0xfff) & ~0xfff)
        emu.derive_params(progress=progress)
    finally:
        emu.close()
    for off in patches:
        out[off] = np.array(sorted(reads[off]), np.int64)
    return out


def _pathA_preflight(dest_is_device):
    """Raise (so the caller falls back to the standard build) when this host or
    destination can't take a blip-free build.

    The cave makes ``game_real`` longer, and a longer file can only get onto the
    card through the Linux filesystem driver -- the same requirement full-size
    video replacement already has.  Checked BEFORE the cave is built so a host
    that can't do it spends no time on the emulator work, and, more importantly,
    so the ``.sidx`` record never gets rewritten to describe a firmware the write
    then fails to deliver.
    """
    if dest_is_device:
        raise RuntimeError(
            "a direct-SD write can't grow files on the card; build an image "
            "file and flash it for a blip-free build")
    from ...core import ext4_grow
    ok, why = ext4_grow.available()
    if not ok:
        raise RuntimeError(
            "this system can't grow files inside an ext4 image (%s), which the "
            "blip-free firmware patch needs" % why)


def _append_cave_segment(raw, need, fn):
    """Append *need* bytes to the ELF *raw* and map them with a PT_LOAD of the
    cave's own, at a virtual address no existing segment claims.

    This is what makes the cave safe: rather than hunting the data segment for
    zeros and hoping nothing owns them (which put the cave on Elvira's node bus
    board table -- see the section comment), the bytes are created here, so
    nothing can own them.

    The header comes from ``PT_GNU_STACK``, which every Spike 2 firmware seen
    ships as a pure advisory entry (offset / vaddr / sizes all zero) with
    ``flags=7``.  There is no room to append a 9th program header -- ``.interp``
    starts immediately after the table -- so the advisory entry is repurposed.
    Dropping it is benign here: it already requested an executable stack, and
    its absence leaves the loader on that same default.

    Returns ``(cave_va, append_off, gap_bytes)``.  Placement prefers free space
    within ARM branch reach of *fn* and settles for anything that fits when the
    near regions are too small -- the caller reads ``cave_va`` back and emits a
    long hop for that case.  Raises ``RuntimeError`` (so the caller falls back
    to the standard build) if there's no repurposable header, or no free address
    space large enough anywhere.

    AUDITED against all 37 vendor firmwares while chasing the James Bond boot
    loop (PAD-11), and the ELF geometry this produces came back clean, so don't
    re-litigate it: p_offset/p_vaddr stay page-congruent, p_filesz never runs
    past EOF, the new segment overlaps no existing one, and the game's .bss is
    still mapped and zeroed exactly as stock.  That last one is worth spelling
    out because it looks broken and isn't.  The cave does become the new maximum
    for both ``elf_bss`` and ``elf_brk``, which does make binfmt_elf's
    *post-loop* ``set_brk`` a no-op -- but PT_GNU_STACK is program header index
    7, after both PT_LOADs, on every one of the 37.  So the cave is a LATER
    PT_LOAD than the RW one, the in-loop ``if (elf_brk > elf_bss)`` fires on the
    cave's own iteration, and it performs the identical ``vm_brk`` +
    partial-page clear the stock load would have.  Rewriting this to sort the
    headers, or to place the cave before the data segment, would break that.

    Two things the audit did turn up, neither of them the Bond fault:

    * **The placement splits the library 33/4, and Bond is in the minority.**
      Where a title has a text/data gap big enough, the cave goes there (33
      titles, Led Zeppelin among them).  Where it doesn't -- Bond LE 1.06,
      Deadpool LE 1.14, Elvira 1.11, TMNT Pro 1.58 -- the only candidate left is
      the synthetic "32 MB above the highest PT_LOAD", and ``cave_va`` is then
      *precisely* the stock ``mm->start_brk``: the cave claims the bottom of the
      heap arena and is safe only because ``set_brk`` afterwards pushes
      ``start_brk`` past it.  Nothing here knows that, and nothing tests it.
      This is the one structural axis on which the card that boot-loops differs
      from every card anyone has booted, so it is where to look next.
    * **The resulting PT_LOAD table is no longer sorted by p_vaddr** on the 33
      gap-placed titles, because the cave keeps index 7 while sitting below the
      data segment.  The gABI requires ascending order; Linux and glibc tolerate
      it for ET_EXEC, which is why those titles work at all.  Left alone
      deliberately: the fix is a header reshuffle, it would move the cave out of
      last position and undo the .bss property above, and none of it can be
      confirmed without a machine.
    """
    return _append_extension_segment(raw, need, 7, near_fn=fn, allow_above=True,
                                     what="cave")


# --------------------------------------------------------------------------
# The appended "extension" segment: a repurposed advisory program header
# mapping bytes appended after the section headers and the 20-byte trailer.
# Two consumers, each with a segment of its own:
#
# * the blip-free cave (flags 7, placed within branch reach of the window-
#   read function, anywhere unclaimed -- above .bss included), which takes
#   PT_GNU_STACK exactly as it always has;
# * the longer program strings (flags 4, the text/data hole ONLY, never
#   above .bss: above-bss is the Bond shape, the one structural axis the
#   boot-looping cards differ on, and a passive read-only page has no reason
#   to go there).  PT_GNU_STACK when it is still there; PT_NOTE when the cave
#   already took it (nothing on the card reads PT_NOTE -- kernel 3.14 and
#   glibc 2.21 walk PT_LOAD / PT_INTERP / PT_GNU_STACK / PT_DYNAMIC / PT_TLS).
#
# Sharing the cave's segment was the alternative and was rejected: the text
# segment's identity IS its header (``PADTXT01`` + u32 first-free offset at
# the segment's FIRST byte, :func:`progreloc.extension_segment` /
# :func:`progtext.enumerate_program_strings` read it there so a re-Extract
# of a relocated card lists the live strings, and a second Write appends
# after them instead of opening another slot), and the cave's code occupies
# a shared segment's first byte.  A second header costs one more mapped
# read-only page, which is the mapping the text segment is anyway.
# --------------------------------------------------------------------------
_PT_NOTE = 4
_EXT_PAGE = 0x1000
_EXT_ABOVE = 32 << 20              # synthetic region above the highest PT_LOAD


def _free_regions(raw, allow_above=True):
    """``[(lo, hi)]`` page-aligned virtual ranges no PT_LOAD covers: the gaps
    between consecutive segments and, when *allow_above*, 32 MB above the
    highest one.  Raises when the ELF maps nothing."""
    PAGE = _EXT_PAGE
    loads = [(va, mz) for _ph, va, _o, _fz, mz, _fl in _iter_phdrs(raw)]
    if not loads:
        raise RuntimeError("no PT_LOAD segments in the firmware ELF.")
    loads.sort()
    frees = []
    for i, (va, mz) in enumerate(loads):
        lo = (va + mz + PAGE - 1) & ~(PAGE - 1)
        if i + 1 < len(loads):
            hi = loads[i + 1][0] & ~(PAGE - 1)
        elif allow_above:
            hi = lo + _EXT_ABOVE
        else:
            continue
        if hi > lo:
            frees.append((lo, hi))
    return frees


def _pick_region(frees, want, near_fn=None):
    """The free region a *want*-byte extent goes in: the first within ARM
    branch reach of *near_fn* (the cave's preference, so a build that placed
    before still places identically), else the lowest that fits, else
    ``None``."""
    fits = [(lo, hi) for lo, hi in frees if hi - lo >= want]  # padded extent
    near = ([f for f in fits if abs(f[0] - (near_fn + 8)) < _CAVE_MAX_BRANCH]
            if near_fn is not None else [])
    return near[0] if near else (fits[0] if fits else None)


def _spare_phdr_slot(raw, types=(_PT_GNU_STACK,)):
    """File offset of the first program header whose type is in *types*
    (in *types* order), or ``None``."""
    e_phoff = struct.unpack_from("<I", raw, 0x1c)[0]
    e_phentsize = struct.unpack_from("<H", raw, 0x2a)[0]
    e_phnum = struct.unpack_from("<H", raw, 0x2c)[0]
    for t in types:
        for i in range(e_phnum):
            o = e_phoff + i * e_phentsize
            if struct.unpack_from("<I", raw, o)[0] == t:
                return o
    return None


def _append_extension_segment(raw, need, flags, near_fn=None, allow_above=True,
                              what="segment", slots=(_PT_GNU_STACK,)):
    """Append *need* bytes to the ELF *raw* and map them with a PT_LOAD of
    their own (``p_flags`` = *flags*) at a virtual address no existing segment
    claims, repurposing the first advisory header in *slots*.

    The generalisation of :func:`_append_cave_segment` (which calls this with
    ``flags=7, near_fn=fn, allow_above=True`` and is byte-identical to what it
    produced before).  The program-text segment calls it with ``flags=4,
    near_fn=None, allow_above=False, slots=(PT_GNU_STACK, PT_NOTE)``:
    read-only, the lowest gap that fits, never the synthetic region above
    .bss, and PT_NOTE when the cave has already spent PT_GNU_STACK.

    Returns ``(seg_va, append_off, gap_bytes)`` -- *gap_bytes* being the size
    of the free region the segment went in, which is how much it could still
    grow by (:func:`_extend_extension_segment`).  Raises ``RuntimeError`` when
    there is no repurposable header or no free region large enough."""
    PAGE = _EXT_PAGE
    frees = _free_regions(raw, allow_above)
    want = (need + PAGE - 1) & ~(PAGE - 1)
    pick = _pick_region(frees, want, near_fn)
    if pick is None:
        raise RuntimeError(
            "no unclaimed address space fits a %d-byte %s -- using the "
            "standard build." % (need, what))
    seg_va, gap_hi = pick
    gap = gap_hi - seg_va

    slot = _spare_phdr_slot(raw, slots)
    if slot is None:
        raise RuntimeError(
            "firmware has no PT_GNU_STACK header to repurpose for the %s."
            % what)

    # Page-align the appended data so p_offset == p_vaddr (mod PAGE), which the
    # loader requires, and pad the file out to the whole declared extent -- a
    # p_filesz running past EOF makes the loader read off the end of the file.
    append_off = (len(raw) + PAGE - 1) & ~(PAGE - 1)
    raw.extend(b"\0" * (append_off + want - len(raw)))
    struct.pack_into("<8I", raw, slot,
                     1,              # p_type = PT_LOAD
                     append_off,     # p_offset
                     seg_va,         # p_vaddr
                     seg_va,         # p_paddr
                     want,           # p_filesz
                     want,           # p_memsz
                     flags,          # p_flags
                     PAGE)           # p_align
    return seg_va, append_off, gap


def _find_extension_segment(raw):
    """The program-text extension segment a previous Write left in *raw*, as
    ``(va, off, size, used)``, or ``None`` on an ELF without one (stock, or
    cave-only).

    It is the PT_LOAD whose first bytes are the ``PADTXT01`` header
    (:data:`progreloc.EXT_MAGIC`) -- the same test
    :func:`progreloc.extension_segment` applies, so the engine, the program-
    text planner and a re-Extract all agree on which segment it is.  *used*
    is the header's u32: the first free offset from the segment's start, the
    12 header bytes included.  New strings go at ``off + used``."""
    from . import progreloc
    ext = progreloc.extension_segment(raw)
    if ext is None:
        return None
    return ext["base_va"], ext["seg_off"], ext["capacity"], ext["used"]


def _extension_room(raw, va):
    """How many bytes of virtual address space the segment at *va* could
    occupy before the next PT_LOAD above it (page-aligned start); 32 MB when
    nothing sits above it."""
    above = [v & ~(_EXT_PAGE - 1)
             for _ph, v, _o, _fz, _mz, _fl in _iter_phdrs(raw) if v > va]
    return (min(above) - va) if above else _EXT_ABOVE


def _extend_extension_segment(raw, need):
    """Grow the program-text extension segment so *need* more bytes fit
    after its used part; returns the new ``(va, off, size, used)``.

    The segment has to be the last thing in the file (it always is: it was
    appended at EOF, and the only other appended segment -- the cave -- is
    built from the STOCK firmware, so it can never land after a text segment),
    and it stays there: the file is padded to the page-rounded extent and
    the PT_LOAD's ``p_filesz``/``p_memsz`` follow.  Raises ``RuntimeError``
    when there is no segment, it is not at EOF, or the next segment's
    address space is in the way."""
    seg = _find_extension_segment(raw)
    if seg is None:
        raise RuntimeError("the firmware has no extension segment to extend.")
    va, off, size, used = seg
    if off + size != len(raw):
        raise RuntimeError(
            "the firmware's extension segment is not at the end of the file, "
            "so it can't be extended.")
    PAGE = _EXT_PAGE
    want = (used + need + PAGE - 1) & ~(PAGE - 1)
    if want <= size:
        return seg
    if want > _extension_room(raw, va):
        raise RuntimeError(
            "the firmware's extension segment can't grow to %d bytes: the "
            "next segment's address space is in the way." % want)
    raw.extend(b"\0" * (off + want - len(raw)))
    for ph, v, _o, _fz, _mz, _fl in _iter_phdrs(raw):
        if v == va:
            struct.pack_into("<I", raw, ph + 16, want)   # p_filesz
            struct.pack_into("<I", raw, ph + 20, want)   # p_memsz
            break
    return va, off, want, used


def _text_reloc_plan(raw):
    """Where longer program text would go in *raw*: ``(reloc, why)`` with
    *reloc* the ``{"base_va", "capacity", "used"}`` dict
    :func:`progtext.plan_writes` takes (``None`` when the ELF can't take a
    text segment, *why* saying so).

    An existing text segment is reused (``used`` = its first free offset,
    ``capacity`` = the address space it can grow into); otherwise the
    placement is the one :func:`_append_extension_segment` will make -- the
    lowest page-aligned gap between the PT_LOADs, never above .bss -- so the
    plan's pointer values are final before a byte of the file changes."""
    from . import progreloc
    seg = _find_extension_segment(raw)
    if seg is not None:
        va, off, size, used = seg
        if off + size != len(raw):
            return None, ("its extension segment is not at the end of the "
                          "file, so it can't be extended")
        return {"base_va": va, "capacity": _extension_room(raw, va),
                "used": used}, ""
    if _spare_phdr_slot(raw, (_PT_GNU_STACK, _PT_NOTE)) is None:
        return None, ("the game program has no spare program header to map "
                      "new space with")
    try:
        frees = _free_regions(raw, allow_above=False)
    except RuntimeError as e:
        return None, str(e)
    pick = _pick_region(frees, _EXT_PAGE)
    if pick is None:
        return None, ("the game program has no free address space between "
                      "its text and data segments")
    lo, hi = pick
    return {"base_va": lo, "capacity": hi - lo,
            "used": progreloc.EXT_HEADER_LEN}, ""


def _cave_entry_patch(fn, cave_va):
    """The instruction bytes that send the window-read function at *fn* into the
    cave at *cave_va*: 4 bytes (a plain ARM branch) while the cave is within
    +/-32 MB, 8 bytes (the ET_EXEC veneer ``ldr pc,[pc,#-4]`` plus the absolute
    target) when it isn't.

    The veneer costs the word at fn+4, which is free to spend: the cave
    replicates all three prologue words and resumes at fn+12, so nothing
    executes fn+4 again.  ``cave_va`` is page-aligned, so the loaded address has
    bit 0 clear and the core stays in ARM state."""
    if abs(cave_va - (fn + 8)) < _CAVE_MAX_BRANCH:
        return struct.pack("<I", (0xE << 28) | (0xA << 24)
                           | (((cave_va - (fn + 8)) >> 2) & 0xFFFFFF))
    return struct.pack("<II", 0xE51FF004, cave_va)


# --------------------------------------------------------------------------
# Rebuilding the cave on a card an earlier blip-free Write already caved.
#
# A modder who extracts his OWN built card and writes the next version from it
# hands the Write a firmware whose window-read function starts with our branch
# instead of its prologue, so the signature locator found nothing and every
# such build fell back to the standard one, reporting "this firmware isn't
# supported" about a firmware it had caved itself (PAD-160, Godzilla Pro 1.16
# V1.8 -> V1.81; the same modder's V1.6 Premium card carries the cave).
#
# Reading the caved firmware straight is right for everything the build
# MEASURES: with the old cave in place the derive reads stock bytes for every
# window it redirects, so the params, the consumed map (which then leaves those
# windows out, bar the 4-16 bytes the signature check reads before redirecting)
# and FIRST_OFF all come out as they would on stock.  Only the bytes the new
# cave is BUILT into have to lose the old one: the prologue goes back, the
# program header goes back to PT_GNU_STACK and the cave's pages come out of the
# file.  Its table is carried into the new cave -- the bodies it covers are
# still the old build's audio on this card, and the stock bytes for their
# windows now exist nowhere else.
# --------------------------------------------------------------------------
_CAVE_CMP_R2 = 0xE3520C02        # cave word 2: cmp r2,#0x200


def _cut_file_extent(raw, off, size):
    """Remove *size* bytes at file offset *off* from the ELF *raw* and pull
    every PT_LOAD stored after them down by as much.  Whole pages past the
    section headers only (an appended segment), so every ``p_offset`` stays
    congruent with its ``p_vaddr``; raises ``RuntimeError`` otherwise."""
    shoff = struct.unpack_from("<I", raw, 0x20)[0]
    shend = shoff + (struct.unpack_from("<H", raw, 0x2e)[0]
                     * struct.unpack_from("<H", raw, 0x30)[0])
    if (off % _EXT_PAGE or size % _EXT_PAGE or off < shend
            or off + size > len(raw)):
        raise RuntimeError("the firmware's appended segment at file+0x%x "
                           "(%d bytes) can't be taken back out." % (off, size))
    del raw[off:off + size]
    for ph, _va, p_off, _fz, _mz, _fl in _iter_phdrs(raw):
        if p_off >= off + size:
            struct.pack_into("<I", raw, ph + 4, p_off - size)


def _cave_table(raw, va, off, size):
    """``[(lo, hi, stock_bytes)]`` from the redirect table of the cave mapped
    at *va* (file offset *off*, *size* bytes), or ``None`` when an entry does
    not describe a window whose copy lies inside the cave."""
    out = []
    t = off + _CAVE_NCODE * 4
    while t + 12 <= off + size:
        lo, hi, sb = struct.unpack_from("<III", raw, t)
        if lo == 0:                                    # the zero sentinel
            return out
        if not (lo < hi and va <= sb and sb + (hi - lo) <= va + size):
            return None
        out.append((lo, hi, bytes(raw[off + sb - va:off + sb - va + hi - lo])))
        t += 12
    return None


def _find_pad_cave(raw):
    """The blip-free cave an earlier Write left in *raw*, or ``None``:
    ``{"fn", "va", "off", "size", "phdr", "windows"}``, *windows* being the
    carried ``[(lo, hi, stock_bytes)]``.

    Recognised by the layout :func:`_asm_derive_redirect_cave` emits (a
    PF_RWX PT_LOAD opening with the replicated prologue and the ``cmp r2``,
    literals naming its own BASEVAR / SIG / table, the RET literal) and by the
    function it returns to really branching into it.  A cave from before the
    long-hop layout (PAD-56) has no RET literal and is not recognised."""
    xva, xoff, xfz = _exec_seg(raw)
    for ph, va, off, fz, _mz, fl in _iter_phdrs(raw):
        if fl != 7 or fz < _CAVE_NCODE * 4 or off + fz > len(raw):
            continue
        w = struct.unpack_from("<%dI" % _CAVE_NCODE, raw, off)
        if ((w[0], w[1], w[43]) != _CAVE_SIG or w[2] != _CAVE_CMP_R2
                or w[45] != va + 49 * 4 or w[46] != va + 50 * 4
                or w[48] != va + _CAVE_NCODE * 4):
            continue
        fn = w[54] - 12
        if not xva <= fn <= xva + xfz - 12:
            continue
        fo = xoff + (fn - xva)
        entry = _cave_entry_patch(fn, va)
        if (bytes(raw[fo:fo + len(entry)]) != entry
                or struct.unpack_from("<I", raw, fo + 8)[0] != _CAVE_SIG[2]):
            continue
        windows = _cave_table(raw, va, off, fz)
        if windows is None:
            continue
        return {"fn": fn, "va": va, "off": off, "size": fz, "phdr": ph,
                "windows": windows}
    return None


def _strip_pad_cave(raw):
    """Take an earlier Write's cave back out of the ELF *raw* in place --
    prologue restored, its program header back to the stock advisory
    PT_GNU_STACK, its pages cut from the file -- and return what
    :func:`_find_pad_cave` found (``None``, *raw* untouched, when there is
    none)."""
    cave = _find_pad_cave(raw)
    if cave is None:
        return None
    xva, xoff, _xfz = _exec_seg(raw)
    struct.pack_into("<III", raw, xoff + cave["fn"] - xva, *_CAVE_SIG)
    struct.pack_into("<8I", raw, cave["phdr"],
                     _PT_GNU_STACK, 0, 0, 0, 0, 0, 7, 0x10)
    _cut_file_extent(raw, cave["off"], cave["size"])
    return cave


def _text_segment_to_eof(raw):
    """Move the program-text extension segment back to the end of *raw* when
    something was appended after it, so a longer string can still extend it
    (:func:`_extend_extension_segment` only grows a segment at EOF).  A cave
    built from a firmware that already carried longer text lands after it."""
    from . import progreloc
    seg = progreloc.extension_segment(raw)
    if seg is None or seg["seg_off"] + seg["capacity"] == len(raw):
        return
    off, size = seg["seg_off"], seg["capacity"]
    data = bytes(raw[off:off + size])
    _cut_file_extent(raw, off, size)
    new_off = (len(raw) + _EXT_PAGE - 1) & ~(_EXT_PAGE - 1)
    raw.extend(b"\0" * (new_off - len(raw)))
    raw.extend(data)
    struct.pack_into("<I", raw, seg["hdr_off"] + 4, new_off)


def _build_derive_redirect_cave(gr_path, img_path, patches, np, log,
                                out_dir, progress=None, extra_fw_writes=None):
    """Build the blip-free firmware cave for the replaced sounds in *patches*
    (``{body_off: body}``), generically for any Stern Spike 2 firmware.

    Locates the window-read function by signature, then rebuilds ``game_real``
    so the boot-derive reads STOCK window bytes for every replaced sound: cave
    code + redirect table + stock window copies go into a segment of the cave's
    own (:func:`_append_cave_segment`), and the function is branched into it.
    Anything in *extra_fw_writes* (``{file_off: bytes}`` -- in practice the
    validator bypass) is baked into the same image, because the whole file is
    copied onto the card in one piece.

    Returns ``(patched_gr_path, new_size)``.  The result is LONGER than the stock
    firmware, so the caller must write it through the ext4 grow path and refresh
    the file's ``.sidx`` size as well as its digests.

    A firmware an earlier blip-free Write already caved is rebuilt rather than
    refused: the old cave comes out and its windows are carried into the new
    one alongside this build's (see the section comment above
    :func:`_find_pad_cave`).

    Raises ``RuntimeError`` (caught by the caller, which then falls back to the
    standard restore build) if the window-read function can't be located, the
    consumed-window map is missing, no unclaimed address space is large enough
    for the cave, the firmware has no repurposable program header, or the located
    function turns out not to be the window reader."""
    from .spike2.elf import parse_elf
    raw = bytearray(open(gr_path, "rb").read())

    # Locate the window-read function by its unique prologue signature (address
    # differs per firmware; the routine itself is identical).
    fn = _locate_window_read_fn(raw)
    carried = []   # (lo, hi, stock bytes) an earlier Write's cave redirected
    if fn is None:
        prev = _strip_pad_cave(raw)
        if prev is not None:
            fn, carried = prev["fn"], sorted(prev["windows"],
                                             key=lambda w: w[0])
            log("Blip-free cave: this card's game program already carries one "
                "from an earlier build (%d window(s)); rebuilding it with "
                "this build's sounds added." % len(carried), "info")
        elif any(fl == 7 for *_x, fl in _iter_phdrs(raw)):
            raise RuntimeError(
                "this card's game program already carries a blip-free patch "
                "from an older version of PAD, which this version can't "
                "rebuild -- write from the stock card image for a blip-free "
                "card")
    if fn is None:
        raise RuntimeError(
            "window-read function not located (prologue signature absent or "
            "ambiguous) -- this firmware isn't supported by the blip-free cave.")
    segs, _relocs = parse_elf(bytes(raw))   # relocs no longer used: the cave has its own segment

    def va2off(va):
        return _cave_va2off(segs, va)

    ret = fn + 12
    log("Blip-free cave: window-read function located at 0x%x." % fn, "info")

    # The exact bytes the boot-derive consumes for each replaced sound == the
    # window ranges to redirect (from the Extract cache, or a fresh derive).
    # Read off the firmware as it is on the card: a carried window is served
    # from the old cave, so only the signature check's first bytes of it show
    # up here, and those are dropped in favour of the carried entry.
    per_body = _replaced_consumed_offsets(gr_path, img_path, patches, np, log,
                                          progress)
    c_lo = np.array([w[0] for w in carried], np.int64)
    c_hi = np.array([w[1] for w in carried], np.int64)
    entries = list(carried)
    with open(img_path, "rb") as f:
        for off in sorted(patches):
            wcon = per_body.get(off)
            if wcon is None or not len(wcon):
                continue
            if len(c_lo):
                i = np.searchsorted(c_lo, wcon, "right") - 1
                wcon = wcon[~((i >= 0) & (wcon < c_hi[np.maximum(i, 0)]))]
                if not len(wcon):
                    continue
            brk = np.where(np.diff(wcon) != 1)[0]
            starts = np.concatenate(([0], brk + 1))
            ends = np.concatenate((brk, [len(wcon) - 1]))
            for s, e in zip(starts, ends):
                a0, b0 = int(wcon[s]), int(wcon[e]) + 1
                f.seek(a0)
                entries.append((a0, b0, f.read(b0 - a0)))
    entries.sort(key=lambda w: w[0])
    windows = [(a0, b0) for a0, b0, _s in entries]   # (lo, hi) image file-offset ranges (2 per mono sound)
    stock_chunks = [s for _a, _b, s in entries]
    if not windows:
        raise RuntimeError("no master-directory windows found for the replaced "
                           "sound(s) -- nothing to redirect.")

    # Layout, all contiguous inside the cave's own segment: the cave itself
    # (code + 4 literals + BASEVAR + the 4-word signature), the redirect table
    # (12 bytes/window + a zero sentinel), then the stock window copies.
    ncode = _CAVE_NCODE
    table_bytes = (len(windows) + 1) * 12
    total_stock = sum(b - a for a, b in windows)
    needed = ncode * 4 + table_bytes + total_stock

    if progress:
        progress(74, 100, "Verifying firmware audio path...")
    first_off = _capture_first_window_off(gr_path, img_path, fn)
    if first_off is None:
        raise RuntimeError(
            "the located function did not perform an image window read -- "
            "unsupported firmware layout; using the standard build.")

    # The content the cave identifies that first read BY (see
    # _asm_derive_redirect_cave).  It has to be what the CARD will hold there,
    # not what the stock image holds, because the read happens after our patches
    # are on the card -- so overlay any replaced body covering those bytes.
    sig = _card_bytes_at(img_path, patches, first_off, _CAVE_SIG_WORDS * 4)
    if len(set(sig)) < 2:
        # A run of identical bytes is not an identification; some other 512-byte
        # buffer of the same filler would latch the base off the wrong pointer,
        # which is the exact failure this signature exists to stop.
        raise RuntimeError(
            "the first master-directory window is %d identical bytes (0x%02x), "
            "which can't identify the read the cave has to calibrate on -- "
            "using the standard build." % (len(sig), sig[0] if sig else 0))

    # Give the cave a segment of its own rather than squatting on the game's
    # data (see the section comment): appended bytes at a virtual address no
    # PT_LOAD claims can't collide with anything the game owns.
    cave_va, append_off, gap = _append_cave_segment(raw, needed, fn)
    table_va = cave_va + ncode * 4
    basevar_va = cave_va + 49 * 4
    sig_va = cave_va + 50 * 4
    stock_va = table_va + table_bytes
    placements = []
    c = stock_va
    for (a0, b0) in windows:
        placements.append(c)
        c += (b0 - a0)

    cave = bytearray(_asm_derive_redirect_cave(
        raw, va2off, fn, ret, cave_va, table_va, first_off, basevar_va, sig_va))
    cave[50 * 4:50 * 4 + len(sig)] = sig
    table = b"".join(struct.pack("<III", a0, b0, sb)
                     for (a0, b0), sb in zip(windows, placements))
    table += struct.pack("<III", 0, 0, 0)     # zero sentinel
    blob = bytes(cave) + table + b"".join(stock_chunks)
    assert len(blob) == needed, (len(blob), needed)
    raw[append_off:append_off + len(blob)] = blob

    # Jump the window-read function into the cave (after the prologue words were
    # read out of it, above).
    entry = _cave_entry_patch(fn, cave_va)
    raw[va2off(fn):va2off(fn) + len(entry)] = entry

    # Anything else this Write would have patched into the firmware has to go
    # into the SAME image: the whole file is copied onto the card in one go, so
    # a separate in-place write against the old inode would just be overwritten.
    for fo, b in (extra_fw_writes or {}).items():
        raw[fo:fo + len(b)] = b
    _text_segment_to_eof(raw)
    append_off = next(o for _ph, v, o, _fz, _mz, _fl in _iter_phdrs(raw)
                      if v == cave_va)

    patched_gr = os.path.join(out_dir, "game_real_pathA")
    with open(patched_gr, "wb") as f:
        f.write(bytes(raw))

    log("Blip-free cave built: %d window(s) across %d replaced sound(s) "
        "redirected to stock%s; fn=0x%x FIRST_OFF=0x%x; cave@0x%x in its own "
        "%d-byte segment (file+0x%x), placed in %d bytes of unclaimed address "
        "space %s; game_real %d -> %d bytes."
        % (len(windows), len(patches),
           (" (%d of them carried from the earlier build's cave)"
            % len(carried) if carried else ""),
           fn, first_off, cave_va, len(blob),
           append_off, gap,
           "in branch reach" if len(entry) == 4 else
           "reached by an absolute jump",
           os.path.getsize(gr_path), len(raw)), "success")
    return patched_gr, len(raw)


def _restore_masterdir_consumed(gr_path, img_path, patches, log, progress=None,
                                cancel=None, skip_offsets=()):
    """Keep each re-encoded body byte-identical to stock in the bytes the
    firmware's master-directory decode CONSUMES.

    ``MASTERDIR_DECODE`` is one continuous, forward-chained pass over every cat-0
    sound: it reads ~1 KB out of each sound's body into a running accumulator that
    sets the codec scale / predictor of that **and every later** sound.  The codec
    is many-to-one, so a re-encode that decodes bit-exact still produces *different*
    body bytes; those changed bytes desync the chain, so every later sound is then
    decoded with the wrong codec and plays as garbage — the machine reboots the
    instant any audio plays.  (Reverse-engineered + proven offline: restoring the
    consumed bytes drops downstream codec-param shifts from ~all sounds to zero.)

    Fix: after encoding, capture the exact body offsets the decode pass reads (via
    a memory-read hook over each modded sound's extent) and overwrite them with the
    original bytes, so the chain reads identical input.  The consumed bytes overlap
    real audio, so that scattered sub-window of the replaced sound reverts toward
    the original — acceptable for a call-out swap.  Mutates and returns *patches*
    (``{body_off: body}``); returns ``None`` if cancelled.

    *skip_offsets* names bodies appended past the old end of the bank (a sound
    grown past its slot).  Those run LAST in the chain, so nothing downstream
    reads them and restoring their windows would only push a scrap of the
    scaffold body into the user's audio for no gain — measured on Led Zeppelin
    LE 1.22 and Godzilla Pro 1.15, where an appended sound's own parameters did
    not move when its body was replaced wholesale.
    """
    if not patches:
        return patches
    skip_offsets = set(skip_offsets or ())
    if cancel and cancel():
        return None
    if progress:
        progress(76, 100, "Preserving master-directory integrity...")
    log("Preserving master-directory forward-chain integrity "
        "(re-encode keeps the firmware's per-sound decode params valid)...",
        "info")

    # Fast path: the consumed offsets are deterministic for a card and were
    # captured (free) during the Extract derive.  Restore each modded body's
    # consumed bytes to stock WITHOUT a full ~2 min re-derive — identical result
    # to the derive path below (both read the same un-patched stock image), and
    # the _assert_param_integrity that follows still re-derives the patched image,
    # so a stale/incomplete cache can only abort the Write, never ship a bad card.
    cached = _load_consumed(gr_path, img_path)
    if cached is not None and len(cached):
        import numpy as np
        with open(img_path, "rb") as f:
            for off, body in patches.items():
                if off in skip_offsets:
                    continue
                lo = int(np.searchsorted(cached, off, "left"))
                hi = int(np.searchsorted(cached, off + len(body), "left"))
                if lo >= hi:
                    continue
                f.seek(off)
                stock = f.read(len(body))
                b = bytearray(body)
                n = 0
                for fo in cached[lo:hi]:
                    rel = int(fo) - off
                    if 0 <= rel < len(b):
                        b[rel] = stock[rel]
                        n += 1
                patches[off] = bytes(b)
                log("  idx@0x%x: preserved %d master-directory byte(s) (cached)."
                    % (off, n), "info")
        return patches

    # body_off -> consumed file offsets
    reads = {off: set() for off in patches if off not in skip_offsets}
    if not reads:
        # The ordinary own-sound build: every patch is an appended body, and
        # the docstring above says why none of those is restored.  Before this
        # return the emulator was still booted and the whole record chain
        # re-derived to restore NOTHING - 1 min 41 s of a 4-minute Try it
        # for one unchanged 6-second end sound (owner session, 2026-09-22).
        log("Master-directory restore: every patch is an appended body, so "
            "there is nothing of the master directory to restore.", "info")
        return patches

    _note_cold_consumed(log)
    from unicorn import UC_HOOK_MEM_READ

    from .spike2 import emulator as EM
    from .spike2.emulator import Spike2Emu

    def _mk(b0, e0, acc):
        def on_read(mu, access, addr, size, value, ud):
            o = addr - EM.DESC_BASE
            for k in range(size):
                if b0 <= o + k < e0:
                    acc.add(o + k)
        return on_read

    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        for off, body in patches.items():
            if off in skip_offsets:
                continue
            end = off + len(body)
            emu.mu.hook_add(UC_HOOK_MEM_READ, _mk(off, end, reads[off]),
                            begin=(EM.DESC_BASE + off) & ~0xfff,
                            end=((EM.DESC_BASE + end) + 0xfff) & ~0xfff)
        # Progress, because this is the multi-minute stretch a cold cache adds
        # to a Write and a stationary bar here is what reads as a hang.
        emu.derive_params(progress=progress)    # the real MASTERDIR_DECODE pass
        for off, body in patches.items():
            if off in skip_offsets:
                continue
            stock = bytes(emu.mm[off:off + len(body)])
            b = bytearray(body)
            for fo in reads[off]:
                rel = fo - off
                if 0 <= rel < len(b):
                    b[rel] = stock[rel]
            patches[off] = bytes(b)
            log("  idx@0x%x: preserved %d master-directory byte(s)."
                % (off, len(reads[off])), "info")
    finally:
        emu.close()
    return patches


def _verify_final_patches(gr_path, img_path, patches, params, np, log,
                          cancel=None, no_restore=False, no_scrap_offsets=()):
    """Decode the ACTUAL card bytes — after ``_restore_masterdir_consumed`` —
    and report what each replaced sound really plays.  ``no_restore=True`` (the
    blip-free firmware-cave build) means the whole body is our audio with no
    original scrap, so the scrap heuristic is skipped.

    The per-sound ``_verify_encoded`` runs INSIDE the encoder, before the
    master-directory restore reverts ~1 KB of scattered body words back to
    stock to keep the firmware's forward-chain intact.  Those reverted words
    are inside the audible range and decode to a scrap of the ORIGINAL callout
    (up to ~-12 dBFS on a silent replacement), so the pre-restore preview and
    verify both understate what ships.  This is the honest, end-of-pipeline
    check: it decodes the final bytes and, when previews are enabled, writes
    the real card render (overwriting the encoder's pre-restore preview).

    Log-only.  Returns ``[(idx, peak_dbfs, head_dbfs, reverted_dbfs)]``."""
    import math

    from .spike2.emulator import BLOCK, Spike2Emu, emitted_length

    if not patches:
        return []
    # {start_off: param} for every plausible window start (delta 0 / -1 / -2).
    owners = {}
    for p in params:
        s = 4 if p.get("chan") == 2 else 2
        for d in (0, 1, 2):
            owners.setdefault(p["body_off"] - s * d, p)

    def dbfs(v):
        return -120.0 if v <= 0 else 20.0 * math.log10(v / 32768.0)

    out = []
    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        emu.warm_slots_for_grown(params)
        if not isinstance(emu.mm, _BodyOverlay):
            emu.mm = _BodyOverlay(emu.mm)
        for off in sorted(patches):
            if cancel and cancel():
                break
            p = owners.get(off)
            if p is None:
                continue
            body = patches[off]
            n = emitted_length(p["length"])
            step = 4 if p.get("chan") == 2 else 2
            stock = bytes(emu.mm.base[off:off + len(body)]
                          if hasattr(emu.mm, "base")
                          else emu.mm[off:off + len(body)])
            # The blip-free cave keeps the whole body as our audio (no master-
            # directory restore), so there is no original-scrap to flag; the body
            # differs from stock nearly everywhere and the scrap heuristic below
            # would false-positive.  Skip it.
            # An appended body (a sound grown past its slot) has no original
            # underneath it at all — what it starts as is a scaffold this write
            # laid down — so comparing against it would report a scrap of a
            # sound that was never there.
            reverted = (
                np.empty(0, int) if (no_restore or off in no_scrap_offsets)
                else np.flatnonzero(
                    np.frombuffer(body, "<u2") != np.frombuffer(stock, "<u2")))
            saved = emu.mm.patch
            emu.mm.patch = (off, body)
            try:
                got = emu.decode(p)
            finally:
                emu.mm.patch = saved
            if got is None or got[0] is None:
                continue
            s = np.asarray(got[0], np.int64)[:n]
            if not len(s):
                continue
            # This render OVERWRITES the encoder's preview file, so it must
            # carry the R channel too — dropping it here shipped mono preview
            # WAVs for stereo slots while the card itself plays stereo.
            chans = [s]
            if got[2] and got[1] is not None:
                chans.append(np.asarray(got[1], np.int64)[:n])
            peak = int(np.abs(s).max())
            head = int(np.abs(s[:BLOCK]).max()) if len(s) else 0
            # Peak within the master-directory-reverted words specifically:
            # those map ~1:1 to output samples (delta near 0), so index by
            # word position clipped into range.
            rev_pk = 0
            if len(reverted):
                ri = reverted[reverted < step * n] // step
                ri = ri[ri < len(s)]
                if len(ri):
                    rev_pk = int(np.abs(s[ri]).max())
            out.append((p["idx"], dbfs(peak), dbfs(head), dbfs(rev_pk)))
            if peak or any(int(np.abs(c).max()) for c in chans[1:]):
                _write_machine_render(p, chans, len(chans) == 2, np)
            # A sound whose head is quiet but whose body carries a loud scrap
            # is the master-directory tradeoff surfacing — name it so a "why is
            # my quiet replacement not quiet?" is answered from the log.
            if rev_pk > 512 and rev_pk >= peak - 6:
                log("idx %d: the card plays a %.0f dBFS scrap of the original "
                    "sound mid-body (bytes the firmware's decode chain forces "
                    "back to stock — unavoidable without rebooting audio); "
                    "the start is clean (%.0f dBFS)."
                    % (p["idx"], dbfs(rev_pk), dbfs(head)), "warning")
    finally:
        emu.close()
    if out:
        worst = max(out, key=lambda r: r[1])
        log("Final-bytes check: %d replaced sound(s) decoded from the card "
            "image; loudest start %.0f dBFS (idx %d)."
            % (len(out), max(r[2] for r in out),
               max(out, key=lambda r: r[2])[0]), "info")
    return out


def _card_rel_path(reader, node):
    """A file's path on the card, matched by extent block — the form the grow
    jobs and the ``.sidx`` manifest both name files by."""
    want = bytes(node["i_block"])
    for path, _ino, n in reader.iter_regular_files(min_size=1, max_depth=20):
        if bytes(n["i_block"]) == want:
            return path.lstrip("/")
    return None


def _appended_body_offsets(patches, places, last_only=False):
    """The patch offsets that land in a body appended past the old end of the
    bank.  The encoder writes from a word or two BELOW a sound's body offset,
    so match by range rather than by equality.

    ``last_only`` narrows it to the body of the LAST appended record, and that
    distinction is load-bearing.  The firmware's decode is one forward chain
    over the record array, so a record's own bytes set the parameters of every
    record AFTER it.  Only the final appended record has nothing after it; the
    others are as ordinary as any stock sound and their consumed windows have
    to be restored like any other.  Growing two sounds in one build without
    that shifted the second one's codec parameters and the integrity check
    stopped the write — which is exactly what it is for."""
    if not places:
        return set()
    want = places[-1:] if last_only else places
    out = set()
    for off in patches:
        for pl in want:
            if pl.body_off - 64 <= off < pl.body_off + pl.body_bytes:
                out.add(off)
                break
    return out


def _grown_body_bytes(p, want):
    """Bytes the appended body of sound *p* takes for a replacement *want*
    card samples long: room for the encoder's whole window, which writes from
    a word or two BELOW the body offset (the shared-boundary word) up to the
    last frame of the new length."""
    from .spike2.emulator import BLOCK
    step = 4 if p.get("chan") == 2 else 2
    return step * (int(want) + BLOCK) + 4096


def _grown_bank_bytes(md_off, count, bodies):
    """What ``image.bin`` measures once :func:`_stage_grown_image` has appended
    one record per entry of *bodies* (appended body sizes in bytes): the record
    array at *md_off* gains that many records and each body follows it behind
    its zero pad, as :func:`~.spike2.masterdir.plan_grow_records` lays them
    out."""
    from .spike2 import masterdir as MD
    return (md_off + MD.tail_len(count + len(bodies))
            + sum(MD.BODY_PAD + b for b in bodies))


#: Bytes one minute of lengthened stereo sound costs in the bank (4 bytes a
#: card sample at 44.1 kHz).  Mono costs half.  Used for the budget readout and
#: the trim reason so both speak in minutes, the unit a user thinks in.
_STEREO_BYTES_PER_MIN = 4 * 44100 * 60


def _grow_budget_minutes(md_off, count, bodies, limit=None):
    """Stereo minutes of lengthened sound the bank can still hold once the
    appended *bodies* (byte sizes) are placed, against *limit* (default
    :data:`~.spike2.emulator.MAX_IMAGE_BYTES`).  Conservative: it leaves room
    for one more body's own header overhead, so a clip of that length really
    fits."""
    from .spike2.emulator import MAX_IMAGE_BYTES
    spare = max(0, (MAX_IMAGE_BYTES if limit is None else limit)
                - _grown_bank_bytes(md_off, count,
                                    list(bodies) + [_grown_body_bytes({}, 0)]))
    return spare / float(_STEREO_BYTES_PER_MIN)


def _fit_grows(order, grows, byidx, md_off, count, limit, start=()):
    """``(kept, cut, bodies)``: the grows of *order* whose bodies fit a bank
    of at most *limit* bytes, fitted in that order after the bodies *start*
    (placed first, whatever their size).  A sound that doesn't fit is skipped
    rather than ending the pass, so a shorter one after it can still use what
    is left."""
    kept, cut, bodies = {}, {}, list(start)
    for idx in order:
        b = _grown_body_bytes(byidx[idx], grows[idx][1])
        if _grown_bank_bytes(md_off, count, bodies + [b]) <= limit:
            kept[idx] = grows[idx]
            bodies.append(b)
        else:
            cut[idx] = grows[idx]
    return kept, cut, bodies


def _grow_order(grows, priority=None):
    """The order the bank's budget fits *grows* in: the idxs the user chose
    to keep whole first (*priority*, order preserved, dupes and unknowns
    dropped), then every remaining grow in slot order."""
    order, seen = [], set()
    for idx in (priority or []):
        if idx in grows and idx not in seen:
            order.append(idx)
            seen.add(idx)
    return order + [idx for idx in sorted(grows) if idx not in seen]


def _grows_kept_at(grows, byidx, img_path, limit, priority=None,
                   reserved=None):
    """The grows :func:`_grows_within_bank_limit` keeps whole when the card
    gives the bank *limit* bytes (the game's own limit applies too), without
    its log: what a room keeps, to compare two rooms by."""
    if not grows:
        return {}
    from .spike2 import masterdir as MD
    from .spike2.emulator import MAX_IMAGE_BYTES
    with open(_lp(img_path), "rb") as f:
        md_off, count = MD.header_geometry(f.read(0x100))
    reserved = reserved or {}
    start = [_grown_body_bytes(byidx[i], reserved[i][1])
             for i in sorted(reserved)]
    return _fit_grows(_grow_order(grows, priority), grows, byidx, md_off,
                      count, min(int(limit), MAX_IMAGE_BYTES), start)[0]


def _grows_within_bank_limit(grows, byidx, img_path, log, priority=None,
                             room=None, reserved=None):
    """*grows* less every sound whose longer copy would take the sound bank
    past :data:`~.spike2.emulator.MAX_IMAGE_BYTES`, the largest file the game
    can open; those are trimmed to fit and named in one log line.  A budget
    readout is always logged, so a user sees how much room is left even when
    nothing was trimmed.

    Every appended body holds the WHOLE new sound and the stock body it
    retires stays where it is, so full-length songs over looping music beds
    add up: stock Godzilla 1.16 has ~498 MB to spare, about 47 minutes of
    stereo sound across everything one build lengthens.  A build past it
    failed outright, with the derive blaming an unrecognised game update
    (PAD-175, PAD-176).

    The bank's growth also has to fit on the card's games partition, beside
    the full-size videos.  On a stock 8 GB Godzilla that partition has 352 MB
    for all of it, less than the 2 GB limit leaves, so it binds first.  With
    *room* (a :data:`_BankRoom`, from the build's :class:`_SpaceCheck`) the
    bank is also held to what the partition can take, so the order below
    trims the least wanted songs instead of the whole build failing at the
    copy, and the trim names the SD card size that keeps them.

    *priority* is an optional sequence of idxs the user chose to keep whole
    (item PAD-181): they are fitted FIRST, in the given order, so when the
    bank can't hold everything the songs the user cares about win rather than
    whichever happen to have the lowest slot numbers.  Everything else follows
    in slot order.

    *reserved* are grows that can't be trimmed (the modes' own sounds, item
    149): their bodies are placed first, and the room left is what the
    longer sounds share."""
    if not grows:
        return grows
    from . import card_size as _cs
    from .spike2 import masterdir as MD
    from .spike2.emulator import MAX_IMAGE_BYTES
    with open(_lp(img_path), "rb") as f:
        md_off, count = MD.header_geometry(f.read(0x100))
    order = _grow_order(grows, priority)
    reserved = reserved or {}
    start = [_grown_body_bytes(byidx[i], reserved[i][1])
             for i in sorted(reserved)]
    limit = MAX_IMAGE_BYTES
    card_binds = room is not None and room.limit < MAX_IMAGE_BYTES
    if card_binds:
        limit = room.limit
    kept, cut, bodies = _fit_grows(order, grows, byidx, md_off, count, limit,
                                   start)
    now = _grown_bank_bytes(md_off, count, bodies)
    left_min = _grow_budget_minutes(md_off, count, bodies, limit)
    # The 2 GB limit is the game's (its 32-bit open of the bank), not the
    # card's, so a bigger SD card doesn't lift it; the card's room does.
    card_mb = max(limit, _grown_bank_bytes(md_off, count, [])) // 10**6
    there = ""
    if room is not None:
        there = "%s free there" % _cs.size_words(room.free)
        if room.others >= 10**6:
            there += (", about %s of it for the other files this build copies "
                      "whole" % _cs.size_words(room.others))
    msg = ("Longer sounds: %d kept whole%s, the sound bank comes to %d MB of "
           "the %d MB the game can open (the game's own limit, which a bigger "
           "SD card doesn't raise)"
           % (len(kept), " beside %d other sound(s) this build adds whole"
              % len(reserved) if reserved else "", now // 10**6,
              MAX_IMAGE_BYTES // 10**6))
    if card_binds:
        msg += (", but the card's games partition has room for it to come to "
                "only %d MB (%s), which leaves room for about %.1f more "
                "minute(s) of stereo sound (or twice that in mono)."
                % (card_mb, there, left_min))
    else:
        msg += (", room for about %.1f more minute(s) of stereo sound (or "
                "twice that in mono). Its growth also takes room on the card's "
                "games partition, which it shares with full-size replacement "
                "videos%s." % (left_min, " (%s)" % there if there else ""))
    log(msg, "info")
    if cut:
        if card_binds:
            # what the bank would come to at the game's limit alone: the
            # size a bigger card has to have room for
            _k, _c, whole = _fit_grows(order, grows, byidx, md_off, count,
                                       MAX_IMAGE_BYTES, start)
            bigger = room.suggest(_grown_bank_bytes(md_off, count, whole))
            why = ("the card's games partition has room for the sound bank to "
                   "come to only %d MB (%s)%s, which leaves room for about "
                   "%.1f more minute(s) of stereo sound or twice that in "
                   "mono%s"
                   % (card_mb, there,
                      ", and the bank comes to %d MB with the %d other longer "
                      "sound(s) kept whole" % (now // 10**6, len(kept))
                      if kept else "", left_min,
                      "; if the SD card in the machine is %s or bigger, %s to "
                      "keep them whole"
                      % (_cs.words(bigger),
                         _cs.bigger_card(bigger, fixed=room.fixed))
                      if bigger else ""))
        else:
            why = ("the game can't open a sound bank bigger than %d MB, and "
                   "keeping them whole as well would pass that (the bank comes "
                   "to %d MB%s, which leaves room for about %.1f more "
                   "minute(s) of stereo sound or twice that in mono)"
                   % (MAX_IMAGE_BYTES // 10**6, now // 10**6,
                      " with the %d other longer sound(s) kept whole"
                      % len(kept) if kept else "", left_min))
        log(*_trimmed_notice(cut, why))
    return kept


def _stage_grown_image(gr_path, img_path, grow_work, byidx, grows, log):
    """Build the sound bank a longer replacement needs, and return
    ``(staged_path, placements)``.

    The bank keeps everything it already had: every stock record and every
    stock body stays exactly where it is.  What changes is that the record
    array gains one entry per grown sound — a copy of that sound's record with
    only its body offset and its length replaced — and the file gains one body
    per entry, appended past where it used to end.  The copy registers with the
    game's sound container under a key of its own (the key moves with a
    record's geometry), so on its own it would sit there unplayed; the play
    tables are re-pointed at it afterwards (:func:`_repoint_descriptors`).

    The appended body starts as the stock sound's own bytes, repeated to fill
    the new length.  It is a scaffold the encoder overwrites, but it has to be
    real card audio rather than zeros: the codec is driven over these bytes to
    recover the keystream, and a degenerate body gives a degenerate one.

    The extracted image is MOVED rather than copied — both directories are in
    the same temp filesystem, so it costs nothing — and the caller owns the
    staged file until it has been copied onto the card."""
    from .spike2 import masterdir as MD
    from .spike2.emulator import BLOCK, Spike2Emu

    staged = os.path.join(grow_work, "image.bin")
    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        d = MD.read_directory(img_path, emu)
        edits = []
        for idx in sorted(grows):
            _room, want = grows[idx]
            p = byidx[idx]
            edits.append(MD.GrowEdit(idx, int(p["length"]), int(want) + BLOCK,
                                     _grown_body_bytes(p, want)))
        grown, places = MD.plan_grow_records(d, edits)
        writes = MD.write_directory(grown, emu)
    finally:
        emu.close()

    os.replace(_lp(img_path), _lp(staged))
    with open(_lp(staged), "r+b") as f:
        stock_bodies = {}
        for pl in places:
            p = byidx[pl.idx]
            step = 4 if p.get("chan") == 2 else 2
            f.seek(p["body_off"])
            stock_bodies[pl.idx] = f.read(step * int(p["length"])) or b"\x00"
        for off, data in writes.items():
            f.seek(off)
            f.write(data)
        end = 0
        for pl in places:
            src = stock_bodies[pl.idx]
            reps = -(-pl.body_bytes // len(src))
            f.seek(pl.body_off - MD.BODY_PAD)
            f.write(b"\x00" * MD.BODY_PAD)
            f.write((src * reps)[:pl.body_bytes])
            end = max(end, pl.body_off + pl.body_bytes)
        f.truncate(end)
    return staged, places


def _derive_grown(gr_path, staged, params_stock, log, progress=None):
    """Derive the codec parameters of the staged bank (pass A) and return the
    table the rest of the write uses.

    The appended records are only decodable by running the firmware's own chain
    over the new array, so this is a full derive of the staged file.  Its
    result is collapsed (:func:`~.spike2.emulator.collapse_shadowed`), which
    retires each grown sound's stock record in favour of its appended one under
    the same index, so every later stage — the encoder, the integrity check,
    the final decode — sees one row per sound with the NEW geometry and needs
    no special case of its own.

    Raises if any sound that was not grown moved: records before an appended
    one are byte-identical, so their parameters must be too, and anything else
    means the bank was not staged the way this function believes."""
    from .spike2.emulator import Spike2Emu, collapse_shadowed
    emu = Spike2Emu(gr_path, staged)
    reads = hh = None
    try:
        emu.boot()
        try:
            reads, hh = _install_consumed_hook(emu)
        except Exception:
            reads = hh = None
        rows = emu.derive_params(progress=progress)
        if hh is not None:
            try:
                emu.mu.hook_del(hh)
            except Exception:
                pass
    finally:
        emu.close()
    params = collapse_shadowed(rows)
    grown_idx = {p["idx"] for p in params if p.get("shadows") is not None}
    raw_by_idx = {r.get("idx"): r for r in rows}
    for p in params:
        p["grown"] = p["idx"] in grown_idx
        if p["grown"]:
            # The key the STOCK record registered under, from the row the
            # collapse retired.  The play tables name the sound by it, and
            # the re-point matches on it exactly (all eight bytes).
            p["stock_findkey"] = (raw_by_idx.get(p["idx"]) or {}).get("findkey")
            # and its length, which is what the descriptor's declared
            # duration was written from.
            p["stock_length"] = (raw_by_idx.get(p["idx"]) or {}).get("length")
    stock = {p["idx"]: (p["scale"], p["pred16"], p["body_off"], p["length"])
             for p in params_stock}
    moved = [p["idx"] for p in params
             if not p["grown"] and p["idx"] in stock
             and stock[p["idx"]] != (p["scale"], p["pred16"], p["body_off"],
                                     p["length"])]
    if moved:
        raise RuntimeError(
            "Staging the longer sound(s) moved %d sound(s) that should not "
            "have changed (first: idx %d); aborting rather than building a "
            "card whose other callouts would play as noise."
            % (len(moved), moved[0]))
    log("Sound bank staged with %d longer sound(s); the other %d are "
        "byte-identical." % (len(grown_idx), len(params) - len(grown_idx)),
        "info")
    return params, reads


# --------------------------------------------------------------------------
# Appended records encoded ALONG the firmware's chain (item 150 follow-up)
# --------------------------------------------------------------------------
# The boot derive reads two 512-byte windows out of every record body (a
# quarter and three quarters of the way in) and those bytes set the codec
# parameters of EVERY record after it, never its own (measured on Godzilla
# Premium 1.16: rewriting appended record 2534's windows left its own
# parameters as they were and moved all nineteen after it).  The standard
# build therefore puts the scaffold's bytes back in each window of every
# appended record but the last, and the card plays ~6 ms of the copied stock
# sound there: a blip at 1/4 and 3/4 of each call, and in a call's silent tail.
#
# There is no need for that with appended records, because nothing after them
# is stock.  Encoding them IN CHAIN ORDER - derive up to the first appended
# record, encode it with the parameters the chain gives it, put its bytes in,
# carry the chain on from them, encode the next - leaves every window holding
# the sound's own audio and every later record's parameters consistent with it.
# No firmware patch; the final derive of the finished bank is the proof.

#: Samples encoded past an appended record's emitted end (item 150 follow-up). The machine plays the
#: codec's LEAD-OUT block past ``length - BLOCK`` (codec.GenRecover.encode_sound, "TAIL"), and an
#: appended record's bytes there were the scaffold: decoded with the record's own parameters they are
#: an 11000-21000 count burst (measured at the desk with the codec object's length raised by 400, and
#: in the rig at every record end and at a bed's loop seam). The appended body's allocation has 4 KB of
#: room past the header length, so the encode simply covers two more blocks, as silence.
_APPENDED_TAIL = 400


def _extended_row(p, extra):
    """*p* with its length (and the codec object's, on a generic build) *extra* samples longer, so an
    encode covers the lead-out block too."""
    q = dict(p, length=int(p["length"]) + extra)
    ob = q.get("_rawobj")
    if ob:
        ob = bytearray(ob)
        struct.pack_into("<I", ob, 0x10, struct.unpack_from("<I", ob, 0x10)[0] + extra)
        q["_rawobj"] = bytes(ob)
    return q


def _chain_encode_appended(gr_path, staged, params, edits, np, log, loops=(),
                           level_refs=None, gains=None, progress=None,
                           cancel=None):
    """Encode the APPENDED records named by *edits* (``{idx: wav}``, idx being
    the collapsed index of a grown sound) along the firmware's own chain, so no
    window of theirs has to be restored.  *loops* are the idx whose records
    loop (music beds: no edge fades, circular low-pass); *level_refs*
    ``{idx: ref_idx}`` gives a sound the stock record whose loudness it
    matches (default: its own slot's).  Returns ``(patches, params)``: the
    ``{write_off: body}`` to lay on the staged bank and the parameter table the
    finished bank derives (every stock record unchanged, every appended record
    with the parameters it was encoded with).  Raises on anything the chain
    cannot carry: a sound not grown, a codec that cannot re-encode bit-exact,
    a record whose own parameters moved."""
    from .spike2 import emulator as EM
    from .spike2.codec import GenRecover, StereoRecover
    from .spike2.emulator import Spike2Emu, collapse_shadowed
    level_refs = dict(level_refs or {})
    gains = gains or {}
    loops = set(loops or ())
    byidx = {p["idx"]: p for p in params}
    want = {}
    for idx, wav in edits.items():
        p = byidx.get(idx)
        if p is None or not p.get("grown") or p.get("shadows") is None:
            raise RuntimeError("idx %d is not an appended record of this bank"
                               % idx)
        want[int(p["shadows"])] = (idx, wav)
    if not want:
        return {}, params
    stock_rows = [p for p in params if not p.get("grown")]
    emu_e = Spike2Emu(gr_path, staged)
    emu_d = Spike2Emu(gr_path, staged)
    patches, done, state = {}, [], {"gr": None, "sr": None}
    try:
        emu_e.boot()
        emu_e.warm_slots_for_grown(params)
        refs = {}
        for idx, ref in level_refs.items():
            q = byidx.get(ref)
            if q is not None:
                refs[idx] = _stock_render(emu_e, q, np,
                                          stereo=byidx[idx].get("chan") == 2)
        emu_d.boot()
        order = sorted(want)

        def after(raw_idx, row, redo):
            got = want.get(raw_idx)
            if got is None:
                return None
            if cancel is not None and cancel():
                raise RuntimeError("cancelled")
            idx, wav = got
            base = byidx[idx]
            p = dict(row, idx=idx, shadows=raw_idx, grown=True)
            for k in ("stock_findkey", "stock_length"):
                if base.get(k) is not None:
                    p[k] = base[k]
            emu_e.warm_slots_for_grown(stock_rows + [p])
            if p["chan"] == 2:
                state["sr"] = state["sr"] or StereoRecover(emu_e)
            else:
                state["gr"] = state["gr"] or GenRecover(emu_e)
            if not _recovery_valid(emu_e, state["gr"], state["sr"], p, np):
                raise RuntimeError(
                    "idx %d: this sound's codec cannot re-encode bit-exact on "
                    "the chain's parameters (scale %s)" % (idx, p["scale"]))
            kw = dict(pred=None, log=log, gain_db=gains.get(idx),
                      loop=idx in loops)
            if idx in refs:
                kw["orig"] = refs[idx]
            # the lead-out block too, as silence (_APPENDED_TAIL); the target is zero-padded to it
            pe = _extended_row(p, _APPENDED_TAIL)
            off, body = (_encode_stereo(emu_e, state["sr"], pe, wav, np, **kw)
                         if p["chan"] == 2 else
                         _encode_mono(emu_e, state["gr"], pe, wav, np, **kw))
            emu_d._ensure_range(EM.DESC_BASE + off, len(body))
            emu_d.mu.mem_write(EM.DESC_BASE + off, bytes(body))
            patches[off] = bytes(body)
            done.append(idx)
            if progress:
                progress(40 + int(len(done) * 35 / max(len(want), 1)), 100,
                         "Encoding the new sounds along the firmware's chain "
                         "(%d of %d)..." % (len(done), len(want)))
            log("idx %d (record %d): encoded on the chain's parameters (scale "
                "%s), %s; its windows hold its own audio."
                % (idx, raw_idx, p["scale"],
                   "a loop" if idx in loops else "%.2f s" % (
                       (p["length"] - EM.BLOCK) / 44100.0)), "info")
            return redo()

        rows = emu_d.derive_params(after_step=after)
    finally:
        emu_e.close()
        emu_d.close()
    missing = sorted(set(i for i, _w in want.values()) - set(done))
    if missing:
        raise RuntimeError("the chain never reached appended sound(s) %s"
                           % missing)
    out = collapse_shadowed(rows)
    for p in out:
        base = byidx.get(p["idx"])
        p["grown"] = p.get("shadows") is not None
        if p["grown"] and base is not None:
            for k in ("stock_findkey", "stock_length"):
                if base.get(k) is not None:
                    p[k] = base[k]
    moved = [p["idx"] for p in out if not p["grown"] and p["idx"] in byidx
             and (p["scale"], p["pred16"]) != (byidx[p["idx"]]["scale"],
                                               byidx[p["idx"]]["pred16"])]
    if moved:
        raise RuntimeError("the chain encode moved %d stock sound(s) (first idx "
                           "%d)" % (len(moved), moved[0]))
    log("%d appended sound(s) encoded along the firmware's chain: no window of "
        "theirs is restored, so none plays a scrap of another sound."
        % len(done), "success")
    return patches, out


# --------------------------------------------------------------------------
# Re-pointing the play tables at an appended record
# --------------------------------------------------------------------------
# The game does not find a sound by its record's identity bytes.  The boot-time
# band build registers every record with the sound container under a key of
# its own, and that key moves with the record's geometry: the appended copy of
# a sound registers under a DIFFERENT key from the stock record it copies, so
# both entries exist and the descriptor that names the sound keeps naming the
# stock one.  Measured on a built Led Zeppelin 1.22 card: idx 44's stock key
# 0xf3e13d92, its appended copy's 0xb0c13c9e, and the Sound Test played the
# original.  So the descriptor is re-pointed: its op11 payload is rewritten to
# the appended record's key.
#
# What the firmware makes of that payload, read off both callers of the
# container find on Led Zeppelin 1.22 (0x209858 and 0x2090f8):
#
#     key.w1 = payload.w1
#     key.w2 = (payload.w2 & 0xe0001fff) | ((sid >> 16) << 13)
#
# and the find itself compares all 64 bits (ldrd / cmp / cmpeq at 0x16fe80).
# The sixteen bits in the middle of the second word are something else the
# descriptor carries; they are kept as they are.
#
# A descriptor also DECLARES its sound's duration: the little-endian word at
# bytes 3..6 (three bytes on every descriptor seen, the fourth always zero) in
# 1/4000 s, i.e. ceil(length * 4000 / 44100) of the record it names on 421 of
# Led Zeppelin's 560 plain descriptors, the rest being multi-part entries
# whose figure covers the whole sequence.  The voice setup (0x170548..0x1705f8)
# assembles it and keeps it on the voice, so a grown sound that still declared
# its old 0.32 s would be cut, or worse, at 0.32 s.  It is moved by the
# difference between the new and the stock length, which keeps whatever base
# a multi-part entry had.
_DESC_KEY2_MASK = 0xE0001FFF
_DESC_OP11 = b"\x0b\x00\x00\x00"
_DESC_DUR_OFF = 3
_DESC_DUR_RATE = 4000

#: One op11 payload in one descriptor, as the card carries it.  ``off`` is
#: where the eight payload bytes sit in ``image.bin`` and ``keystream`` the
#: eight bytes whitening them there; ``dur_off`` / ``dur_keystream`` are the
#: same for the four-byte declared duration, ``duration`` its plain value.
_DescSite = namedtuple(
    "_DescSite", "sid off keystream payload dur_off dur_keystream duration")


def _duration_units(samples):
    """A length in card samples as the descriptor declares it."""
    return -(-int(samples) * _DESC_DUR_RATE // 44100)


def _duration_units_emitted(length):
    """The declared duration that ends where a record of header *length* stops
    emitting audio (``length - BLOCK`` samples), rounded DOWN so the voice never
    plays past the decoder's own output.  A record whose emitted length is a
    multiple of 441 samples (10 ms) gets it exactly, which is what a looping
    record needs for a seamless loop (:func:`.mode_sounds.loop_wav`)."""
    from .spike2.emulator import emitted_length
    return int(emitted_length(length)) * _DESC_DUR_RATE // 44100


def _play_key(payload8, sid, mask=_DESC_KEY2_MASK):
    """The 8-byte container key the game derives from an op11 payload.
    ``mask`` is the build's second-word key mask (:func:`_desc_key_mask`)."""
    w1, w2 = struct.unpack("<II", payload8)
    w2 = (w2 & mask) | (((sid >> 16) << 13) & 0xFFFFFFFF)
    return struct.pack("<II", w1, w2)


#: The second-word key masks measured so far (item 149).  The mask is PER BUILD:
#: Led Zeppelin 1.22 keeps ``0xE0001FFF`` (read off its container find) and so does
#: Godzilla Premium 1.16's time-up record; Godzilla Pro 1.15 keeps ``0xFC0003FF``
#: (item 130: 2557 of the runtime tree's sids exact, 0 wrong; with Led Zeppelin's
#: mask only 44 of 2535 records looked named and the re-point refused).
_DESC_KEY2_MASKS = (0xE0001FFF, 0xFC0003FF)


def _desc_key_mask(params, sites, log=None):
    """The key mask this build's play tables use: the candidate under which the
    descriptors name the most STOCK records (a grown row counts by its stock key).

    A right mask names nearly every record and a wrong one a coincidental few, so the
    winner must name at least twice as many as the runner-up; anything closer is not
    a measurement and is refused rather than re-pointing against a coincidence.  When
    no candidate names anything there is no evidence either way and Led Zeppelin's
    mask is kept, so the plan refuses per sound with its own reason."""
    stock = set()
    for p in params:
        k = p.get("stock_findkey") if p.get("grown") else p.get("findkey")
        if k:
            stock.add(bytes(k))
    counts = []
    for m in _DESC_KEY2_MASKS:
        named = {_play_key(s.payload, s.sid, m) for s in sites} & stock
        counts.append((len(named), m))
    counts.sort(key=lambda c: -c[0])
    (best, mask), (second, _m2) = counts[0], counts[1]
    if best == 0:
        return _DESC_KEY2_MASK
    if best < 2 * second:
        raise RuntimeError(
            "The game's play tables do not match one known key layout clearly "
            "(%s), so no descriptor is re-pointed on this build."
            % ", ".join("0x%08X names %d record(s)" % (m, n) for n, m in counts))
    if log:
        log("Play-table key layout 0x%08X: the descriptors name %d of %d sound "
            "record(s) (the other layout %d)." % (mask, best, len(stock), second),
            "info")
    return mask


def _op11_payloads(desc):
    """``[(offset, payload8)]`` for every op11 marker in a descriptor, from
    the first position a primary asset can sit at (see sfx_names)."""
    out = []
    p = 9
    while True:
        p = desc.find(_DESC_OP11, p)
        if p < 0 or p + 12 > len(desc):
            return out
        out.append((p + 4, desc[p + 4:p + 12]))
        p += 4


def _descriptor_sites(gr_path, img_path, log=None):
    """Every op11 payload the card's play tables carry, as a list of
    :class:`_DescSite`.  Empty when the resolver can't be located, which a
    caller treats as "no descriptor names anything"."""
    from .spike2 import sfx_names as SN
    from .spike2.emulator import Spike2Emu
    out = []
    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        resolver, buf = SN._find_resolver(emu)
        if resolver is None:
            if log:
                log("The game's descriptor resolver could not be located, so "
                    "no play table can be re-pointed on this build.", "info")
            return out
        for sid in range(SN.sid_ceiling(img_path) + 1):
            r = SN.resolve_descriptor(emu, resolver, buf, sid)
            if r is None:
                continue
            dec0, ks, desc = r
            d0 = _DESC_DUR_OFF
            dur = struct.unpack_from("<I", desc, d0)[0]
            for p, payload in _op11_payloads(desc):
                out.append(_DescSite(sid, dec0 + p, ks[p:p + 8], payload,
                                     dec0 + d0, ks[d0:d0 + 4], dur))
    finally:
        emu.close()
    return out


def _grows_named_by_a_descriptor(grows, byidx, sites, log):
    """*grows* less every sound no play table names, each dropped with a
    reason in the log: a longer copy nothing points at would never be played,
    so that replacement trims to fit exactly as it did before.

    Matches on the key's first word here, which is all the cached params
    carry; the exact eight-byte match happens once the staged bank has been
    derived (:func:`_plan_descriptor_repoint`)."""
    named = set()
    for s in sites:
        named.add(struct.unpack_from("<I", s.payload)[0])
    kept = {}
    for idx, spec in grows.items():
        k0 = (byidx.get(idx) or {}).get("key0")
        if k0 is None:
            log("idx %d: this firmware's decode reports no container key for "
                "the sound, so its play tables can't be re-pointed at a "
                "longer copy; the replacement is trimmed to fit." % idx,
                "info")
        elif k0 not in named:
            log("idx %d: nothing in the game's play tables names this sound, "
                "so a longer copy would never be played; the replacement is "
                "trimmed to fit." % idx, "info")
        else:
            kept[idx] = spec
    return kept


def _mode_sound_grow(gr_path, img_path, params, sites, audio_edits, grows,
                     mode_sound, log):
    """Item 149: put a mode's own END SOUND into this build as a forced grow.

    The mode signs off with its title's time-up request; that request's record
    (request -> sid chain -> descriptor key under this build's mask -> record)
    is grown to hold the mode's WAV - never shorter than the stock sound - and
    the WAV joins the build's sound edits, so the staged bank, the re-point,
    the encode, the count patch and the validator bypass all happen exactly as
    for a user's longer callout.  Returns ``(audio_edits, grows, used)`` where
    *used* is *mode_sound* with ``idx`` filled in, or ``None`` when the sound
    falls back to the game's own call (logged).  Raises when another edit in
    the project replaces that same sound: the two cannot both be on the card."""
    from . import mode_write as _MW
    from .spike2.emulator import emitted_length, firmware_build_supported
    name = mode_sound["name"]
    if firmware_build_supported(gr_path):
        # _audio_grow_gate's firmware check, for the same reason: the validated
        # build rebuilds each codec object from its record, so no sound on it
        # can run past its stock length and the grow could never be heard.
        log("Modes: %s ends with the game's own time-up call on this card: this "
            "game version's audio engine is the one build whose sounds can't be "
            "driven past their original length." % name, "warning")
        return audio_edits, grows, None
    try:
        mask = _desc_key_mask(params, sites)
        with open(_lp(gr_path), "rb") as f:
            elf = f.read()
        with open(_lp(img_path), "rb") as f:
            head = f.read(1 << 16)
        idx = _MW.request_record(elf, head, params, sites,
                                 mode_sound["request"], mask)
    except (RuntimeError, OSError, ValueError, IndexError, struct.error) as e:
        # An unexpected program or an out-of-range request in a profile is a
        # sound that cannot be located, never a failed Write.
        log("Modes: %s ends with the game's own time-up call on this card: its "
            "time-up sound could not be located (%s)." % (name, e), "warning")
        return audio_edits, grows, None
    if idx in audio_edits:
        raise RuntimeError(
            "Modes: %s's own end sound goes in place of sound idx %d (the "
            "game's time-up call, request %d), and this project also replaces "
            "that sound. Take one of them out, then Write again."
            % (name, idx, mode_sound["request"]))
    p = {q["idx"]: q for q in params}.get(idx)
    want = _wav_frames_44k(mode_sound["wav"])
    if p is None or want is None:
        log("Modes: %s ends with the game's own time-up call on this card: %s."
            % (name, "its sound record is unknown" if p is None else
               "its end sound %s is not a WAV this app can read"
               % os.path.basename(mode_sound["wav"])), "warning")
        return audio_edits, grows, None
    room = emitted_length(p.get("length", 0))
    audio_edits = dict(audio_edits)
    audio_edits[idx] = mode_sound["wav"]
    grows = dict(grows)
    grows[idx] = (room, max(int(want), int(p.get("length", 0))))
    used = dict(mode_sound, idx=idx)
    log("Modes: %s's own end sound (%s, %.2f s) goes on the card as a new "
        "record for request %d (sound idx %d, %.2f s on the stock card), and "
        "the game's play tables are re-pointed at it - so the game's own "
        "time-up call plays it too." % (name, os.path.basename(mode_sound["wav"]),
                                         want / 44100.0, mode_sound["request"],
                                         idx, p.get("length", 0) / 44100.0),
        "info")
    return audio_edits, grows, used


def _mode_bed_templates(gr_path, img_path, used, log):
    """``{bed sid: music carrier's sid}`` for the modes' music beds in this build (item 150
    follow-up): each bed's descriptor is rewritten as a copy of its carrier's looping-music one
    (:func:`_music_template_writes`), so the bed plays on the music bus and loops."""
    beds = [u for u in (used or ()) if u.get("music") and u.get("sid")]
    if not beds:
        return {}
    from . import mode_write as _MW
    with open(_lp(gr_path), "rb") as f:
        elf = f.read()
    with open(_lp(img_path), "rb") as f:
        head = f.read(1 << 16)
    out = {}
    for u in beds:
        sids = _MW.request_sids(elf, head, int(u["request"]))
        if len(sids) != 1:
            raise RuntimeError("Modes: the music carrier, request %d, plays %d sound ids; a "
                               "music bed needs one to copy" % (int(u["request"]), len(sids)))
        out[int(u["sid"])] = sids[0]
    return out


def _mode_music_level_refs(gr_path, img_path, params, sites, loop_idx, log):
    """``{idx: ref_idx}``: the stock record whose loudness a mode's music bed matches - the
    title's music carrier's own (a stock tune at the game's music level), not the bed sid's
    stock record, which is a short effect (item 150 follow-up). ``{}`` when it cannot be found,
    and each bed then matches its own slot as before."""
    if not loop_idx:
        return {}
    from . import mode_sounds as _MS
    from . import mode_write as _MW
    try:
        with open(_lp(gr_path), "rb") as f:
            elf = f.read()
        with open(_lp(img_path), "rb") as f:
            head = f.read(1 << 16)
        mask = _desc_key_mask(params, sites)
        carriers = [c for c in _MS.TITLES.values() if c.key_mask == mask and c.music]
        if not carriers:
            return {}
        ref = _MW.request_record(elf, head, params, sites, carriers[0].music[0], mask)
    except Exception as e:  # noqa: BLE001 - a missing reference only changes a level
        log("Modes: the music beds match their own slots' level (the game's music record "
            "was not found: %s)." % e, "info")
        return {}
    return {int(i): int(ref) for i in loop_idx}


def _mode_own_sounds_grow(gr_path, img_path, params, sites, audio_edits, grows,
                          own, work_dir, log):
    """Item 149 with item 150: put the modes' START SOUNDS, SHOT SOUNDS and MUSIC into
    this build, each a forced grow of its CARRIER's record (a stock request the game
    never plays: :data:`.mode_sounds.TITLES`), exactly as :func:`_mode_sound_grow` does
    the end sound: the staged bank, the re-point, the encode, the count patch and the
    validator bypass follow as for any grown bank. A music WAV shorter than its carrier's
    record is tiled in whole repeats past it (:func:`.mode_sounds.tile_wav`), so the
    record loops it with no silence; a shorter call is followed by silence, which the mode
    file's length (``ms``) stops. Returns ``(audio_edits, grows, used)``: *used* is the
    sounds that went in, each with ``idx`` and ``ms``; one that cannot be located is left
    out and logged. Raises when another edit in the project replaces a carrier's sound."""
    from . import mode_sounds as _MS
    from . import mode_write as _MW
    from .spike2.emulator import emitted_length, firmware_build_supported
    if not own:
        return audio_edits, grows, []
    if firmware_build_supported(gr_path):
        log("Modes: the start sounds, shot sounds and music of the modes are not put on "
            "this card: this game version's audio engine is the one build whose sounds "
            "can't be driven past their original length.", "warning")
        return audio_edits, grows, []
    try:
        mask = _desc_key_mask(params, sites)
        with open(_lp(gr_path), "rb") as f:
            elf = f.read()
        with open(_lp(img_path), "rb") as f:
            head = f.read(1 << 16)
    except (RuntimeError, OSError, ValueError, IndexError, struct.error) as e:
        log("Modes: the start sounds, shot sounds and music of the modes are not put on "
            "this card: the game's play tables could not be read (%s)." % e, "warning")
        return audio_edits, grows, []
    byidx = {q["idx"]: q for q in params}
    audio_edits, grows = dict(audio_edits), dict(grows)
    mine, used = set(), []
    for s in own:
        what = "%s's own %s" % (s["name"], _MW.sound_words(s["key"]))
        try:
            if s.get("sid"):
                # item 150 follow-up: a music BED is its own sid's record (no request names
                # it); the mode points the music carrier at that sid while it runs
                idx = _MW.sid_record(params, sites, s["sid"], mask)
            else:
                idx = _MW.request_record(elf, head, params, sites, s["request"], mask)
        except (RuntimeError, OSError, ValueError, IndexError, struct.error) as e:
            log("Modes: %s is not put on this card: its carrier, request %d%s, could not be "
                "located (%s)." % (what, s["request"],
                                   " (bed sid %d)" % s["sid"] if s.get("sid") else "", e), "warning")
            continue
        if idx in mine:
            log("Modes: %s is not put on this card: its carrier, request %d, plays the same "
                "sound record (idx %d) as another of the modes' sounds."
                % (what, s["request"], idx), "warning")
            continue
        if idx in audio_edits:
            raise RuntimeError(
                "Modes: %s goes in place of sound idx %d (request %d, a stock call the "
                "game does not play), and this project also replaces that sound. Take one "
                "of them out, then Write again." % (what, idx, s["request"]))
        p = byidx.get(idx)
        wav = s["wav"]
        want = _wav_frames_44k(wav)
        if p is None or want is None:
            log("Modes: %s is not put on this card: %s." % (
                what, "its carrier's sound record is unknown" if p is None else
                "%s is not a WAV this app can read" % os.path.basename(wav)), "warning")
            continue
        length = int(p.get("length", 0))
        if s.get("music"):
            # item 150 follow-up: always a seamless loop, a whole number of 10 ms steps (so the
            # record's declared duration ends exactly on it), repeated past the stock record
            os.makedirs(_lp(work_dir), exist_ok=True)
            tiled = os.path.join(work_dir, "music_%d_loop.wav" % idx)
            try:
                reps, loop = _MS.loop_wav(_lp(wav), _lp(tiled),
                                          _MS.bed_min_frames(s.get("seconds"), length),
                                          edge_ms=_MS.BED_EDGE_MS)
            except _MS.ModeSoundError as e:
                log("Modes: %s is not put on this card: %s." % (what, e), "warning")
                continue
            log("Modes: %s (%s, %.2f s) is made a seamless %.3f s loop and repeated %d time(s) "
                "to fill its record." % (what, os.path.basename(wav), want / 44100.0,
                                         loop / 44100.0, reps), "info")
            wav, want = tiled, _wav_frames_44k(tiled)
        audio_edits[idx] = wav
        grows[idx] = (emitted_length(length), max(int(want), length))
        mine.add(idx)
        ms = None if s.get("music") else _MS.sound_ms(_lp(s["wav"]))
        used.append(dict(s, idx=idx, ms=ms))
        log("Modes: %s (%s, %.2f s) goes on the card as a new record for request %d "
            "(sound idx %d, %.2f s on the stock card, a call the game does not play), "
            "and the mode's file names that request." % (
                what, os.path.basename(s["wav"]), _wav_frames_44k(s["wav"]) / 44100.0,
                s["request"], idx, length / 44100.0), "info")
    return audio_edits, grows, used


def _plan_descriptor_repoint(params, sites, mask=None, family=None):
    """``({off: bytes}, {sid: ({key8}, duration)})`` -- the writes that
    re-point every descriptor naming a grown sound's stock record at its
    appended record and move its declared duration by the growth, and what
    each touched sid must then resolve to.

    ``mask`` is the build's key mask; ``None`` measures it from *params* and
    *sites* (:func:`_desc_key_mask`).  *family* (default: the preview switch,
    :func:`_mode_family_on`) False keeps what a build without the mode editor
    family does: the one key mask it knew and the declared duration rounded
    UP from the header length.

    Raises when a grown sound's appended key has bits no descriptor can
    carry, or when no descriptor names its stock record: either would ship
    a card that plays the original, the very thing this exists to prevent."""
    if family is None:
        family = _mode_family_on()
    if mask is None:
        mask = _desc_key_mask(params, sites) if family else _DESC_KEY2_MASK
    writes, expect = {}, {}
    for p in params:
        if not p.get("grown"):
            continue
        old, new = p.get("stock_findkey"), p.get("findkey")
        if not old or not new:
            raise RuntimeError(
                "idx %d: the staged bank's decode reported no container key "
                "for the sound, so its play tables can't be re-pointed."
                % p["idx"])
        grew = 0
        if p.get("stock_length") is not None:
            # The declared duration is what the voice PLAYS, and the codec emits
            # only length - BLOCK samples: a duration rounded up past that makes
            # the voice read ~10 samples beyond the decoder's own output, a
            # burst the machine plays at the very end of every appended record
            # and at every loop of a looping one (item 150 follow-up, measured
            # in a rig capture: 6 of 6 record ends, and the music's loop seam
            # at the declared 39.965 s, not the emitted 39.960 s).  So the new
            # duration ends where the audio ends (rounded DOWN), keeping any
            # base a multi-part entry had over its stock record.  (The preview
            # switch off keeps the old rounding: _mode_family_on.)
            grew = ((_duration_units_emitted(p["length"]) if family
                     else _duration_units(p["length"]))
                    - _duration_units(p["stock_length"]))
        hits = 0
        for s in sites:
            if _play_key(s.payload, s.sid, mask) != old:
                continue
            if _play_key(new, s.sid, mask) != new:
                raise RuntimeError(
                    "idx %d: the appended record's container key (%s) has "
                    "bits no descriptor can carry, so the game could never "
                    "look it up." % (p["idx"], new.hex()))
            w1, w2 = struct.unpack("<II", new)
            _o1, o2 = struct.unpack("<II", s.payload)
            plain = struct.pack(
                "<II", w1,
                (o2 & ~mask & 0xFFFFFFFF) | (w2 & mask))
            writes[s.off] = bytes(a ^ b for a, b in zip(plain, s.keystream))
            keys, dur = expect.get(s.sid, (set(), s.duration))
            keys.add(new)
            # One descriptor can name two grown sounds; each moves the
            # declared duration by its own growth.
            dur = (dur + grew) & 0xFFFFFFFF
            expect[s.sid] = (keys, dur)
            writes[s.dur_off] = bytes(
                a ^ b for a, b in zip(struct.pack("<I", dur), s.dur_keystream))
            hits += 1
        if not hits:
            raise RuntimeError(
                "idx %d: no descriptor in the game's play tables names this "
                "sound's record, so the longer copy could never be played."
                % p["idx"])
    return writes, expect


#: What a looping MUSIC descriptor has right after its op11 payload on Godzilla (request 125's
#: sid and the game's looping tunes 73 / 83 / 84): the script that plays the record and goes
#: back to its loop mark. A tune that plays once (66, the DJ Mixer's tracks) has 11 01 00.
_MUSIC_LOOP_TAIL = b"\x11\x01\x03\x00"


def _music_template_writes(gr_path, staged, templates, expect, mask, log):
    """``({file_off: bytes}, {sid: (category byte, tail)})``: each BED sid's descriptor
    rewritten as a copy of its music carrier's (item 150 follow-up, a mode's own music bed).

    The bus a sound plays on and whether it loops are the DESCRIPTOR's, not the request's:
    measured in the rig (2026-09-18, X1), request 125 pointed at a free stereo effect sid
    played that sid's record on effects bus 0x04, once. A descriptor starts ``05 <bus mask>
    01 <duration u32> ...`` (0x01 music, 0x02 voice, 0x1c effects), and a looping tune's
    script ends ``0b 00 00 00 <key> 11 01 03 00``. So the head of the bed's descriptor, up to
    and including that loop, is replaced by the carrier's own, with the bed's appended key and
    duration in it. It must fit inside what the bed's descriptor already used (its own op11
    payload ends further in: 38 bytes for Godzilla's stereo effects against the carrier's 31),
    so nothing past it moves. *templates* maps bed sid -> the carrier's sid; *expect* is
    :func:`_plan_descriptor_repoint`'s ``{sid: ({key}, duration)}``. Raises when a template is
    not a looping music descriptor or does not fit."""
    from .spike2 import sfx_names as SN
    from .spike2.emulator import Spike2Emu
    out, want = {}, {}
    emu = Spike2Emu(gr_path, staged)
    try:
        emu.boot()
        resolver, buf = SN._find_resolver(emu)
        if resolver is None:
            raise RuntimeError("the game's descriptor resolver could not be located, so a "
                               "music bed's descriptor cannot be written")
        for bed, tsid in sorted(templates.items()):
            rt = SN.resolve_descriptor(emu, resolver, buf, tsid)
            rb = SN.resolve_descriptor(emu, resolver, buf, bed)
            if rt is None or rb is None:
                raise RuntimeError("sid %d or its template sid %d has no descriptor" % (bed, tsid))
            tdesc = rt[2]
            tops = _op11_payloads(tdesc)
            if not tops or tdesc[tops[0][0] + 8:tops[0][0] + 12] != _MUSIC_LOOP_TAIL:
                raise RuntimeError("sid %d (the music carrier's) is not a looping music "
                                   "descriptor: %s" % (tsid, tdesc[:40].hex()))
            tp, tpay = tops[0]
            n = tp + 8 + len(_MUSIC_LOOP_TAIL)
            bdec0, bks, bdesc = rb
            bops = _op11_payloads(bdesc)
            if not bops or bops[0][0] + 8 < n or len(bks) < n:
                raise RuntimeError("sid %d's descriptor is too short for a music descriptor "
                                   "(%s)" % (bed, bdesc[:40].hex()))
            keys, dur = expect.get(bed, (set(), None))
            if len(keys) != 1 or dur is None:
                raise RuntimeError("sid %d is not re-pointed at exactly one appended record" % bed)
            w1, w2 = struct.unpack("<II", next(iter(keys)))
            _t1, t2 = struct.unpack("<II", tpay)
            plain = bytearray(tdesc[:n])
            plain[tp:tp + 8] = struct.pack("<II", w1, (t2 & ~mask & 0xFFFFFFFF) | (w2 & mask))
            plain[_DESC_DUR_OFF:_DESC_DUR_OFF + 4] = struct.pack("<I", dur)
            out[bdec0] = bytes(a ^ b for a, b in zip(plain, bks[:n]))
            want[bed] = (tdesc[1], tp)
            log("Modes: sound id %d becomes a music bed: its descriptor now plays on the music "
                "bus (0x%02x, was 0x%02x) and loops, as the carrier's sid %d does."
                % (bed, tdesc[1], bdesc[1], tsid), "info")
    finally:
        emu.close()
    return out, want


def _repoint_descriptors(gr_path, staged, params, sites, log, templates=None):
    """Rewrite the play tables in the staged bank so every descriptor that
    named a grown sound's stock record names its appended record instead,
    then prove it through the game's own resolver on the file as written.
    *templates* ``{bed sid: carrier sid}`` also makes each of those a looping music
    descriptor (:func:`_music_template_writes`). Returns the ``{off: bytes}`` written."""
    from .spike2 import sfx_names as SN
    from .spike2.emulator import Spike2Emu
    # the key mask measured per build, and durations that end where the audio
    # does, are the mode editor family's: the preview switch off keeps the
    # one mask and the rounding a build without it uses (_mode_family_on)
    family = _mode_family_on()
    mask = _desc_key_mask(params, sites, log) if family else _DESC_KEY2_MASK
    writes, expect = _plan_descriptor_repoint(params, sites, mask, family=family)
    t_writes, t_want = ({}, {})
    if templates:
        t_writes, t_want = _music_template_writes(gr_path, staged, templates, expect, mask, log)
    with open(_lp(staged), "r+b") as f:
        for off, data in writes.items():
            f.seek(off)
            f.write(data)
        # the bed heads last: they cover the duration word and the first payload byte the
        # ordinary re-point wrote at the effect layout's offsets
        for off, data in t_writes.items():
            f.seek(off)
            f.write(data)
    writes = {**writes, **t_writes}
    emu = Spike2Emu(gr_path, staged)
    try:
        emu.boot()
        resolver, buf = SN._find_resolver(emu)
        if resolver is None:
            raise RuntimeError(
                "The game's descriptor resolver could not be located on the "
                "staged bank, so the re-point could not be verified.")
        for sid, (keys, dur) in sorted(expect.items()):
            r = SN.resolve_descriptor(emu, resolver, buf, sid)
            got, got_dur = set(), None
            if r is not None:
                for _p, payload in _op11_payloads(r[2]):
                    got.add(_play_key(payload, sid, mask))
                got_dur = struct.unpack_from("<I", r[2], _DESC_DUR_OFF)[0]
            missing = keys - got
            if missing:
                raise RuntimeError(
                    "sid %d: after the re-point the game's resolver does not "
                    "hand back the appended record's key (%s); aborting "
                    "rather than shipping a card that plays the original."
                    % (sid, ", ".join(k.hex() for k in sorted(missing))))
            if got_dur != dur:
                raise RuntimeError(
                    "sid %d: after the re-point the descriptor declares a "
                    "duration of %s where %d was written; aborting rather "
                    "than shipping a card whose sound would be cut short."
                    % (sid, got_dur, dur))
            if sid in t_want:
                bus, tp = t_want[sid]
                if r[2][1] != bus or r[2][tp + 8:tp + 8 + len(_MUSIC_LOOP_TAIL)] != _MUSIC_LOOP_TAIL:
                    raise RuntimeError(
                        "sid %d: after the rewrite its descriptor is not a looping music "
                        "descriptor (%s); aborting" % (sid, r[2][:40].hex()))
    finally:
        emu.close()
    n_grown = sum(1 for p in params if p.get("grown"))
    log("Play tables re-pointed: %d descriptor(s) now name the longer copy "
        "of %d sound(s) and declare the new length, confirmed through the "
        "game's own resolver." % (len(expect), n_grown), "info")
    return writes


def _assert_param_integrity(gr_path, img_path, patches, params, np, log,
                            work_dir, progress=None):
    """Write-time safety net: apply *patches* to a temp ``image.bin`` and confirm
    the firmware's master-directory decode derives the **same** codec scale /
    predictor for every sound as the stock card.  A non-empty shift list means the
    forward chain is still broken (a card that would reboot on audio), so we raise
    rather than ship it.  Set ``PAD_STERN_SKIP_MASTERDIR_VERIFY=1`` to skip.

    This one derives on EVERY audio Write, cache or no cache, so it reports
    progress too -- it is the last multi-minute stretch before the card is
    written and used to be the one with nothing on screen at all."""
    if not patches or os.environ.get("PAD_STERN_SKIP_MASTERDIR_VERIFY") == "1":
        return
    import shutil

    from .spike2.emulator import Spike2Emu, collapse_shadowed
    tmp = os.path.join(work_dir, "image_verify.bin")
    shutil.copyfile(img_path, tmp)
    try:
        with open(tmp, "r+b") as f:
            for off, body in patches.items():
                f.seek(off)
                f.write(body)
        emu = Spike2Emu(gr_path, tmp)
        try:
            emu.boot()
            rows = emu.derive_params(progress=progress)
        finally:
            emu.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    # On a grown bank the array holds two records per grown sound; the collapse
    # keeps the one the game will actually play, under the index the rest of
    # the write knows it by (:func:`~.spike2.emulator.collapse_shadowed`).  On
    # a stock bank it is a no-op.
    rows = collapse_shadowed(rows)
    stock = {p["idx"]: (p["scale"], p["pred16"]) for p in params}
    cur = {r["idx"]: (r["scale"], r["pred16"]) for r in rows}
    shifted = [i for i in stock if i in cur and stock[i] != cur[i]]
    if shifted:
        # Name them.  Which sounds moved is the whole diagnosis: a run of
        # consecutive indexes means the chain desynced at the first of them,
        # and a lone index means that one sound's own bytes are the cause.
        raise RuntimeError(
            "Master-directory integrity check FAILED: %d of %d sounds would "
            "decode with the wrong codec parameters (the card would reboot on "
            "audio). The re-encode could not preserve the firmware's "
            "forward-chain; aborting the write rather than producing a broken "
            "card. First shifted: %s%s."
            % (len(shifted), len(stock),
               ", ".join("idx %d (%s -> %s)" % (i, stock[i], cur[i])
                         for i in sorted(shifted)[:5]),
               " and %d more" % (len(shifted) - 5) if len(shifted) > 5 else ""))
    log("Master-directory integrity verified: all %d sounds keep valid decode "
        "parameters." % len(stock), "success")


def _encode_cat0_sounds(gr_path, img_path, params, audio_edits, np, log,
                        progress, cancel, assets_dir=None, gains=None,
                        cache_img_ident=None):
    """Re-encode every edited cat-0 sound to its body bytes — parallel across
    processes with a single-process fallback.  Returns ``({body_off: body},
    [skipped_idx])`` or ``(None, None)`` if cancelled.

    With *assets_dir*, sounds unchanged since their last encode replay from
    that folder's :class:`_AudioBodyCache` instead of re-encoding.  *gains*
    maps idx -> that clip's total loudness dB (:func:`_slot_gain_maps`).

    *cache_img_ident* is the identity the CACHE should be keyed on.  When this
    build grew the bank, the encode runs against the staged file but the cache
    is keyed on the stock one, so a mod with a hundred replaced sounds does not
    re-encode all of them because one of them got longer.  A grown sound misses
    the cache anyway: its own param record is part of its key and it now says a
    different body offset and length."""
    gains = gains or {}
    byidx = {p["idx"]: p for p in params}
    for idx in sorted(set(audio_edits) - set(byidx)):
        log("idx %d not a known sound; skipping." % idx, "warning")
    # Longest sound first: re-encode time is ~linear in length and the songs
    # range from a fraction of a second to >8 minutes, so a long track is an
    # irreducible tail on a single worker.  Scheduling it first (with chunksize=1
    # below) keeps every worker busy and makes the wall-clock ≈ the longest
    # single song rather than worst-case load imbalance.  Tie-break on idx for a
    # deterministic order.
    edits = sorted(((idx, wav) for idx, wav in audio_edits.items()
                    if idx in byidx),
                   key=lambda iw: (-byidx[iw[0]].get("length", 0), iw[0]))
    if not edits:
        return {}, []

    cache = None
    if assets_dir and os.environ.get("PAD_STERN_AUDIO_CACHE") != "0":
        try:
            cache = _AudioBodyCache(assets_dir, gr_path, img_path, byidx,
                                    _slot_end_map(params), gains=gains,
                                    img_ident=cache_img_ident)
        except Exception as e:
            log("Audio encode cache unavailable (%s); encoding everything "
                "fresh." % e, "info")
    patches, skipped = {}, []
    todo = edits
    if cache is not None:
        todo, hits, skip_hits = [], 0, 0
        for idx, wav in edits:
            ent = cache.lookup(idx, wav)
            if ent is None:
                todo.append((idx, wav))
            elif ent[0] == "skip":
                skipped.append(idx)
                skip_hits += 1
            else:
                patches[ent[1]] = ent[2]
                hits += 1
        if hits or skip_hits:
            log("Audio cache: %d of %d sound(s) unchanged since their last "
                "encode — reused their encoded bodies%s. "
                "(PAD_STERN_AUDIO_CACHE=0 rebuilds everything.)"
                % (hits + skip_hits, len(edits),
                   "; %d known-unencodable stay skipped" % skip_hits
                   if skip_hits else ""), "info")
    if not todo:
        skipped = sorted(set(skipped))
        if skipped:
            log("%d sound(s) skipped (re-encode unsupported for their codec): "
                "%s" % (len(skipped), ", ".join(map(str, skipped))), "warning")
        return patches, skipped

    nworkers = max(1, min((os.cpu_count() or 2) - 2, 8))
    nworkers = max(1, min(nworkers, len(todo)))
    fresh, remaining, results = {}, todo, {}
    if not _FORCE_SERIAL_ENCODE and nworkers > 1 and not cancel():
        try:
            # Full params, not just the edited sounds': the workers also need
            # each edit's layout-predecessor for the shared-boundary word.
            fresh, psk, remaining, results = _encode_cat0_parallel(
                gr_path, img_path, params, todo, nworkers, np, log, progress,
                cancel, gains=gains)
            if fresh is None:
                return None, None
            skipped.extend(psk)
        except Exception as e:
            # The pool never started -- fall back to a full single-process pass.
            log("Parallel re-encode unavailable (%s); using a single process."
                % e, "warning")
            fresh, remaining, results = {}, todo, {}
    # Finish any edits the parallel path didn't complete (all of them if it was
    # skipped/unavailable; just the leftovers if a worker died mid-run).  Keeping
    # the parallel results avoids re-encoding everything serially on a partial
    # failure -- the slow path that made a quick job take hours.
    if remaining:
        sp, sk, sres = _encode_cat0_serial(
            gr_path, img_path, byidx, remaining, np, log, progress, cancel,
            gains=gains)
        if sp is None:
            return None, None
        fresh.update(sp)
        skipped.extend(sk)
        results.update(sres)
    patches.update(fresh)
    skipped = sorted(set(skipped))
    if cache is not None:
        # Remember this build's fresh outcomes — bodies and skip verdicts both
        # (a skip otherwise costs a full failed encode attempt every build).
        wav_by_idx = dict(todo)
        for idx, (off, body) in results.items():
            cache.store(idx, wav_by_idx[idx], off, body)
        for idx in skipped:
            if idx in wav_by_idx:
                cache.store(idx, wav_by_idx[idx], None, None)
    if skipped:
        log("%d sound(s) skipped (re-encode unsupported for their codec): %s"
            % (len(skipped), ", ".join(map(str, skipped))), "warning")
    return patches, skipped


_MUSIC_NAME_RE = re.compile(r"music_cat(\d+)_(\d+)", re.IGNORECASE)


def _derive_encode_bank(gr_path, img_path, rev, cid, sc_path, edits, np,
                        gains=None):
    """Re-encode one bank's edited songs on a FRESH CatEmu (deriving several
    banks on one emu grinds the loader — see ``spike2/category.py``).  *edits* =
    ``[(idx, wav_path), ...]`` for this bank, *gains* ``{idx: total dB}`` for
    the songs the user levelled by hand.  Returns ``(patches, skipped)``
    where ``patches`` = ``[(cid, idx, body_off, body), ...]`` (the parent maps
    cid back to its ext4 inode) and ``skipped`` = ``[(cid, idx), ...]``.
    Bit-identical to the serial inner loop, just per-bank so it parallelises."""
    from .spike2.category import CatEmu
    from .spike2.codec import GenRecover, StereoRecover
    gains = gains or {}
    patches, skipped = [], []
    emu = CatEmu(gr_path, img_path)
    rows = []
    try:
        emu.boot()
        emu.set_category_file(sc_path)
        rows = emu._derive_cat(cid, rev) or []
        byidx = {r["idx"]: r for r in rows}
        emu.mm = emu._mm_cat          # body source = this bank
        gr = sr = None
        # Songs are packed back-to-back in the bank just like cat-0 sounds in
        # image.bin, so a delta<0 song's head frame is the previous song's
        # final frame — same shared-boundary word, same fix (a miss in this
        # map, e.g. an aligned/gapped bank, just keeps the enc[0] behavior).
        ends = _slot_end_map(rows)
        for idx, wav in sorted(edits):
            p = byidx.get(idx)
            if p is None:                 # not a sound in that bank
                skipped.append((cid, idx))
                continue
            if p["chan"] == 2:
                sr = sr or StereoRecover(emu)
            else:
                gr = gr or GenRecover(emu)
            if not _recovery_valid(emu, gr, sr, p, np):
                skipped.append((cid, idx))
                continue
            pred = ends.get(p["body_off"])
            gdb = gains.get(idx)
            off, body = (_encode_stereo(emu, sr, p, wav, np, pred=pred,
                                        gain_db=gdb)
                         if p["chan"] == 2
                         else _encode_mono(emu, gr, p, wav, np, pred=pred,
                                           gain_db=gdb))
            patches.append((cid, idx, off, bytes(body)))
    finally:
        emu.close()
    # The bank's MASTERDIR_DECODE is the same forward-chained pass as cat-0
    # (just over the bank file), so a re-encoded song desyncs the codec params
    # of later songs IN THAT BANK.  Restore the masterdir-consumed bytes and
    # verify the chain stays intact (else the music would reboot the machine).
    if patches and os.environ.get("PAD_STERN_SKIP_MASTERDIR_FIX") != "1":
        patches = _restore_bank_consumed(gr_path, img_path, rev, cid, sc_path,
                                         patches)
        _assert_bank_integrity(gr_path, img_path, rev, cid, sc_path, patches,
                               rows)
    return patches, skipped


def _restore_bank_consumed(gr_path, img_path, rev, cid, sc_path, patches):
    """Bank twin of :func:`_restore_masterdir_consumed`: keep each re-encoded
    song's masterdir-consumed bytes identical to stock so the bank's forward
    chain reads the same input.  *patches* = ``[(cid, idx, body_off, body), ...]``;
    returns the same with each body's consumed bytes restored."""
    from unicorn import UC_HOOK_MEM_READ

    from .spike2.category import DESC2, CatEmu
    reads = {bo: set() for (_c, _i, bo, _b) in patches}

    def _mk(b0, e0, acc):
        def on_read(mu, access, addr, size, value, ud):
            o = addr - DESC2
            for k in range(size):
                if b0 <= o + k < e0:
                    acc.add(o + k)
        return on_read

    emu = CatEmu(gr_path, img_path)
    try:
        emu.boot()
        emu.set_category_file(sc_path)
        for (_c, _i, bo, body) in patches:
            emu.mu.hook_add(UC_HOOK_MEM_READ, _mk(bo, bo + len(body), reads[bo]),
                            begin=(DESC2 + bo) & ~0xfff,
                            end=((DESC2 + bo + len(body)) + 0xfff) & ~0xfff)
        emu._derive_cat(cid, rev)
        out = []
        for (c, idx, bo, body) in patches:
            stock = bytes(emu._mm_cat[bo:bo + len(body)])
            b = bytearray(body)
            for fo in reads[bo]:
                rel = fo - bo
                if 0 <= rel < len(b):
                    b[rel] = stock[rel]
            out.append((c, idx, bo, bytes(b)))
        return out
    finally:
        emu.close()


def _assert_bank_integrity(gr_path, img_path, rev, cid, sc_path, patches,
                           stock_rows):
    """Bank twin of :func:`_assert_param_integrity`: apply *patches* to a temp
    copy of the bank and confirm every song still derives the same codec params,
    else raise (a card that would reboot on that bank's music).  Skipped by
    ``PAD_STERN_SKIP_MASTERDIR_VERIFY=1``."""
    if not patches or os.environ.get("PAD_STERN_SKIP_MASTERDIR_VERIFY") == "1":
        return
    import shutil

    from .spike2.category import CatEmu
    fd, tmp = tempfile.mkstemp(suffix=".scbin")
    os.close(fd)
    try:
        shutil.copyfile(sc_path, tmp)
        with open(tmp, "r+b") as f:
            for (_c, _i, bo, body) in patches:
                f.seek(bo)
                f.write(body)
        emu = CatEmu(gr_path, img_path)
        try:
            emu.boot()
            emu.set_category_file(tmp)
            rows = emu._derive_cat(cid, rev) or []
        finally:
            emu.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    def _key(r):
        return (r["scale"], bytes(r["_rawobj"][0x14:0x1e]))
    stock = {r["idx"]: _key(r) for r in stock_rows}
    cur = {r["idx"]: _key(r) for r in rows}
    shifted = [i for i in stock if i in cur and stock[i] != cur[i]]
    if shifted:
        raise RuntimeError(
            "Music bank %d integrity check FAILED: %d of %d songs would decode "
            "with the wrong codec parameters (the card would reboot on that "
            "bank's music); aborting the write." % (cid, len(shifted), len(stock)))


def _bank_encode_worker(args):
    """One task = re-encode a single bank's edited songs on a fresh emu.
    Top-level so it pickles across the spawn boundary."""
    gr_path, img_path, rev, cid, sc_path, edits, gains = args
    import numpy as np
    try:
        return _derive_encode_bank(gr_path, img_path, rev, cid, sc_path, edits,
                                   np, gains=gains)
    except Exception:
        return ([], [(cid, idx) for idx, _ in edits])


def _run_bank_encode(tasks, log, progress, cancel):
    """Run the per-bank encode *tasks* — one process per bank (fresh emu each)
    with a single-process fallback.  Returns ``[(patches, skipped), ...]`` per
    bank, or ``None`` if cancelled."""
    nworkers = max(1, min((os.cpu_count() or 2) - 2, 8))
    nworkers = max(1, min(nworkers, len(tasks)))
    if (not _FORCE_SERIAL_ENCODE and nworkers > 1 and len(tasks) > 1
            and not cancel()):
        try:
            import multiprocessing as mp
            log("Re-encoding %d music bank(s) across %d process(es)..."
                % (len(tasks), nworkers), "info")
            ctx = mp.get_context("spawn")
            out, done = [], 0
            # maxtasksperchild=1: a fresh process per bank reclaims the large
            # unicorn mappings and never inherits another bank's state.
            with ctx.Pool(nworkers, maxtasksperchild=1) as pool:
                for res in pool.imap_unordered(_bank_encode_worker, tasks):
                    out.append(res)
                    done += 1
                    if progress:
                        progress(80 + int(done * 15 / max(len(tasks), 1)), 100,
                                 "Re-encoding music bank %d/%d"
                                 % (done, len(tasks)))
                    if cancel():
                        pool.terminate()
                        return None
            return out
        except Exception as e:
            log("Parallel music re-encode unavailable (%s); using a single "
                "process." % e, "warning")
    import numpy as np
    out = []
    for n, t in enumerate(tasks):
        if cancel():
            return None
        if progress:
            progress(80 + int(n * 15 / max(len(tasks), 1)), 100,
                     "Re-encoding music bank %d/%d" % (n + 1, len(tasks)))
        gr_path, img_path, rev, cid, sc_path, edits, gains = t
        try:
            out.append(_derive_encode_bank(gr_path, img_path, rev, cid, sc_path,
                                           edits, np, gains=gains))
        except Exception as e:
            log("music_cat%02d: re-encode failed (%s); skipped." % (cid, e),
                "warning")
            out.append(([], [(cid, idx) for idx, _ in edits]))
    return out


def _compute_music_patches(reader, gr_path, img_path, music_edits, work, log,
                           progress, cancel, np, gains=None):
    """Re-encode each edited per-song music bank back into its ``image-scNN.bin``
    (size-neutral) and return ``[(sc_node, body_off, body_bytes), ...]`` for the
    songs that re-encode bit-exact.

    Each song's body lives in a SEPARATE bank file (so every patch carries its
    own ext4 inode, not ``image.bin``'s), and each bank is derived on its own
    fresh :class:`CatEmu` (deriving several banks on one emu accumulates state
    that grinds the loader).  Because a fresh emu per bank is required anyway,
    the banks fan across processes — one task per bank — for a big speedup when
    many songs changed (Metallica = 24 banks).  A song whose re-encode isn't
    bit-exact (``_recovery_valid``) is skipped, never written blind."""
    from .spike2.category import _find_revalidate, read_category_id

    # group edits by category id; idx = the sound's index within that bank
    by_cat = {}
    for wav in music_edits:
        m = _MUSIC_NAME_RE.match(os.path.basename(wav))
        if not m:
            continue
        by_cat.setdefault(int(m.group(1)), []).append((int(m.group(2)), wav))
    if not by_cat:
        return []

    # resolve + extract each needed image-scNN.bin (the body source AND the
    # inode we patch).
    sc = {}     # catid -> (sc_node, local_path)
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return []
        rid = read_category_id(path.rsplit("/", 1)[-1])
        if rid in by_cat and rid not in sc:
            local = os.path.join(work, os.path.basename(path))
            reader.extract_file(node, local)
            sc[rid] = (node, local)
    for cid in sorted(set(by_cat) - set(sc)):
        log("music_cat%02d: bank not on the card; %d edit(s) skipped."
            % (cid, len(by_cat[cid])), "warning")
    if not sc:
        log("None of the edited songs' banks (image-scNN.bin) were found on the "
            "card; left unchanged.", "warning")
        return []

    rev = _find_revalidate(
        gr_path, img_path,
        sorted((cid, local) for cid, (_n, local) in sc.items()), log)
    if rev is None:
        log("Couldn't drive the category loader to re-encode the music bank(s); "
            "the edited song(s) were left unchanged.", "warning")
        return []

    # one task per bank; biggest banks first so a long song isn't pure tail
    # latency (bank file size ≈ decoded length).
    cids = sorted(
        (c for c in by_cat if c in sc),
        key=lambda c: (os.path.getsize(sc[c][1])
                       if os.path.exists(sc[c][1]) else 0),
        reverse=True)
    # Each bank task carries only its OWN songs' loudness offsets (keyed by the
    # index within the bank, which is what _derive_encode_bank looks up).
    gains = gains or {}
    tasks = [(gr_path, img_path, rev, c, sc[c][1], by_cat[c],
              {i: db for (gc, i), db in gains.items() if gc == c})
             for c in cids]
    results = _run_bank_encode(tasks, log, progress, cancel)
    if results is None:
        return []

    patches, skipped = [], []
    for bank_patches, bank_skipped in results:
        for (cid, idx, body_off, body) in bank_patches:
            patches.append((sc[cid][0], body_off, body))
            log("Re-encoded music_cat%02d_%04d." % (cid, idx), "info")
        skipped.extend(bank_skipped)
    if skipped:
        log("%d music song(s) skipped (re-encode not bit-exact or not in the "
            "bank)." % len(skipped), "warning")
    return patches


# --------------------------------------------------------------------------
def _linux_partitions(path):
    from .formats import linux_partitions
    return linux_partitions(path)


def _rmtree(path):
    import shutil
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _safe_remove(path):
    """Best-effort unlink (used to discard a half-prepared output on a
    cancelled / failed write).  Long-path aware: the output is user-chosen, and
    failing to clean up leaves a multi-GB half-written image behind."""
    try:
        os.remove(_lp(path))
    except OSError:
        pass
