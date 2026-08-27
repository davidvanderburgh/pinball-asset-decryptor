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
import tempfile
import time
import wave

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
_DERIVE_REV = 2
_REV_TAG = ".r%d" % _DERIVE_REV
# Everything this module keeps in the cache directory, as (current-rev suffix,
# regex matching that file kind at ANY revision including the unsuffixed rev-1).
_CACHE_KINDS = (
    (_REV_TAG + ".pkl",             re.compile(r"^[0-9a-f]{32}(\.r\d+)?\.pkl$")),
    (_REV_TAG + ".consumed.npy",    re.compile(r"^[0-9a-f]{32}(\.r\d+)?\.consumed\.npy$")),
    (_REV_TAG + ".sfxnames4.json",  re.compile(r"^[0-9a-f]{32}(\.r\d+)?\.sfxnames\d+\.json$")),
)


def _fingerprint(game_real_path, image_path):
    h = hashlib.sha256()
    with open(_lp(game_real_path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    with open(_lp(image_path), "rb") as f:
        h.update(f.read(0x20000))   # header + master-directory source region
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
    vids = []
    radiums = {}   # hash-dir path -> scene.radium inode
    for path, ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.endswith("/scene.radium"):
            radiums[path[:-len("/scene.radium")]] = node
        elif node["size"] >= 0x1000:
            b = reader.peek(node, 12)
            if len(b) >= 12 and b[4:8] == b"ftyp":
                vids.append((path, node, b[8:12]))
    if not vids:
        log("No video assets found.", "info")
        return 0

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
            prog_rows = [
                {"path": fw_path, "original": e["text"], "replacement": "",
                 "budget": e["budget"]}
                for e in entries]
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
    try:
        # replacement column left BLANK -- the user fills in only the strings
        # they want to change (blank = leave unchanged), so the manifest never
        # looks like every row is already duplicated.
        text_manifest.save(output_dir, [
            {"path": card_path, "original": original, "replacement": ""}
            for card_path, original in rows] + prog_rows)
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
    # below ~0.03 bpp regardless of absolute bitrate.
    if info and info.width > 0 and info.height > 0:
        dur = info.duration if info.duration and info.duration > 0 else 0
        if dur > 0:
            bitrate = len(shrunk) * 8 / dur
            fps = info.fps if info.fps and info.fps > 0 else 30.0
            bpp = bitrate / (info.width * info.height * fps)
            if bpp < 0.03:
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


def _intact_copy_source(src, staged, fname, slot_size, log):
    """Pick which file may be copied onto the card verbatim for *fname*, and
    log the one line that says which it was and why.

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
    for the clip already there: same container family, H.264, 8-bit 4:2:0, the
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
    from ...core import video as _video

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

    # Container: the extract extension records the brand the card itself used
    # (".mov" for QuickTime-branded clips, ".mp4" for the rest).
    brand = _video.isobmff_brand(src)
    if brand is None:
        return _reject("%s isn't an MP4/QuickTime container like the clip it "
                       "replaces" % os.path.basename(src))
    want_qt = os.path.splitext(fname)[1].lower() == ".mov"
    if (brand == b"qt  ") != want_qt:
        return _reject("%s is a %s file but this slot holds %s"
                       % (os.path.basename(src),
                          "QuickTime" if brand == b"qt  " else "MP4",
                          "QuickTime" if want_qt else "MP4"))

    info = _video.detect_video_info(src)
    if info is None:
        return _accept()      # no ffprobe/ffmpeg — the container check stands
    codec = (info.vcodec or "").lower()
    if codec and codec != "h264":
        return _reject("it's %s and Spike 2 plays H.264" % codec.upper())
    if (info.pix_fmt or "") not in _video.SAFE_PIX_FMTS:
        return _reject("it's %s and the machine's decoder handles only 8-bit "
                       "4:2:0" % info.pix_fmt)

    slot = _video.detect_video_info(staged)
    if slot is None or not slot.width or not slot.height:
        return _accept()      # nothing to compare against; the above stands
    if (info.width, info.height) != (slot.width, slot.height):
        return _reject("it's %dx%d and this slot's clip is %dx%d"
                       % (info.width, info.height, slot.width, slot.height))
    if slot.fps > 0 and info.fps > 0 and abs(info.fps - slot.fps) > 0.5:
        return _reject("it runs at %.3g fps and this slot's clip is %.3g fps"
                       % (info.fps, slot.fps))
    # Profile is a decode ceiling, not a preference: Replace-Video pins every
    # re-encode to the slot's own profile for exactly this reason, so the
    # intact path can't be the one place a higher one slips through.
    rank, slot_rank = _video.profile_rank(info), _video.profile_rank(slot)
    if rank is not None and slot_rank is not None and rank > slot_rank:
        return _reject("it's H.264 %s profile and this slot's clip is %s — "
                       "above what the slot proves the machine decodes"
                       % (info.profile, slot.profile))
    return _accept()


def _prepare_video_patches(reader, video_edits, work_dir, log, cancel,
                           originals=None, dest_is_device=False):
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
    staged copy."""
    originals = originals or {}
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
        can_grow, why = ext4_grow.available()
        if not can_grow:
            log("Can't replace videos intact on this system (%s); they'll be "
                "re-encoded to fit their slots instead (lower quality)." % why,
                "warning")

    patches, grow_jobs = [], []
    for fname, card_path, node, src, staged in intact:
        if can_grow:
            # Logs its own one-line verdict (which file, and why that one).
            source = _intact_copy_source(src, staged, fname, node["size"], log)
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
    img_dir = os.path.join(assets_dir, "images")
    manifest = os.path.join(img_dir, _IMAGE_MANIFEST)
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


def _program_text_writes(reader, node, card_path, pairs, patched_fw, log):
    """Resolve game-program (ELF) display-text edits for one firmware file.

    Two composition modes, mirroring how the firmware itself reaches the card:

    * normally the ELF is untouched on disk, so the string/pointer patches are
      emitted as in-place disk writes plus a file-relative overlay for the
      ``.sidx`` digest refresh (same shape as the radium text overlays);
    * when the blip-free audio cave rebuilt the firmware (*patched_fw* — a
      staged whole-file copy that later replaces the on-card ELF), an in-place
      disk write would be undone by that copy, so the edits are applied
      directly INTO the staged file instead; its ``.sidx`` record is computed
      from the file, so the digests cover the text automatically.

    Returns ``(writes, n_strings, overlays)`` like the radium helper."""
    from . import progtext

    if patched_fw is not None:
        with open(_lp(patched_fw), "rb") as f:
            raw = f.read()
    else:
        raw = reader.read_file_bytes(node)
    file_writes, n = progtext.plan_writes(raw, dict(pairs), log)
    if not file_writes:
        return [], n, {}
    if patched_fw is not None:
        buf = bytearray(raw)
        for off, b in file_writes:
            buf[off:off + len(b)] = b
        with open(_lp(patched_fw), "wb") as f:
            f.write(bytes(buf))
        log("Program text: %d string edit(s) baked into the rebuilt firmware."
            % n, "info")
        return [], n, {}
    writes = []
    ov = {}
    ib = bytes(node["i_block"])
    for off, b in file_writes:
        payload = b
        for disk, cnt in reader.disk_ranges(node, off, len(b)):
            writes.append((disk, payload[:cnt]))
            payload = payload[cnt:]
        ov.setdefault(ib, (node, {}))[1][off] = b
    return writes, n, ov


def _radium_text_writes(reader, assets_dir, log, cancel, patched_fw=None):
    """Resolve the user's display-text edits to a flat list of in-place writes
    ``[(disk_offset, bytes), ...]`` (same form ``_compute_patches`` collects).

    For each changed radium: resolve its inode, read it back, **re-enumerate**
    the unchanged on-card bytes for the authoritative offsets, and for every
    edit ``(original -> replacement)`` patch **all** display-text occurrences
    whose value equals ``original``.  A replacement is rejected (skipped with a
    warning, the radium left unchanged) unless it fits the original's byte
    budget; it is space-padded to the exact original length so the file size and
    every other offset stay byte-identical.

    Rows whose path resolves to the ARM-ELF game firmware are game-program
    strings, routed to :func:`_program_text_writes` (in-place C-string patch +
    name-group pointer moves; *patched_fw* composes with the blip-free
    firmware rebuild).

    Returns ``(writes, n_strings, overlays, fw_overlay)`` where ``n_strings``
    is the number of unique (asset, original) strings actually patched,
    ``overlays`` is ``{i_block: (node, {file_offset: bytes})}`` for every
    patched inode (so the caller can recompute its ``.sidx`` digest), and
    ``fw_overlay`` is the game ELF's own ``{file_offset: bytes}`` — the
    validator bypass is the LAST writer of that file's ``.sidx`` record, so it
    has to fold these edits into the digest it computes."""
    from . import radium as _radium

    edits = _changed_radium_text(assets_dir)
    if not edits:
        return [], 0, {}, {}
    nodes = _resolve_card_nodes(reader, list(edits.keys()), cancel)

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
            pw, pn, pov = _program_text_writes(
                reader, node, card_path, pairs, patched_fw, log)
            writes += pw
            n_strings += pn
            _merge_radium_overlays(overlays, pov)
            for _n, _ov in pov.values():
                fw_overlay.update(_ov)
            continue
        ib = bytes(node["i_block"])
        data = reader.read_file_bytes(node)
        occ_by_text = {}
        for e in _radium.enumerate_strings(data):
            if e["kind"] == "display-text":
                occ_by_text.setdefault(e["text"], []).append(e)
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
    return writes, n_strings, overlays, fw_overlay


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


def _radium_image_writes(reader, assets_dir, baseline, log, cancel):
    """Re-encode each edited radium-embedded image to its format (BC3/DXT5 or
    BC1/DXT1) and resolve it to a flat ``[(disk_offset, bytes), ...]`` list
    patching the bytes in place inside the ``scene.radium`` inode (same form
    ``_compute_patches`` collects, like the display-text writes).  Returns
    ``(writes, n_images)``.

    Size-neutral by construction: the PNG is the full padded block grid, so
    re-encoding yields exactly ``length`` bytes at ``data_offset``.

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
    patched_outputs = set()
    for output, radium_path, staged, data_off, length, pad_w, pad_h, fmt in edits:
        if cancel():
            break
        node = nodes.get(radium_path)
        if node is None:
            log("Radium image %s: its scene (%s) wasn't found on the card; "
                "skipped." % (output, radium_path), "warning")
            continue
        payload = encoded.get(staged)
        if payload is None:
            override = glyph_atlases.get(output)
            try:
                im = override if override is not None else (
                    Image.open(_lp(staged)).convert("RGBA"))
            except Exception as e:
                log("Radium image %s: can't read PNG (%s); skipped."
                    % (output, e), "warning")
                continue
            if im.size != (pad_w, pad_h):
                log("Radium image %s is %dx%d but must stay %dx%d; skipped "
                    "(don't resize — edit in place)."
                    % (output, im.size[0], im.size[1], pad_w, pad_h), "warning")
                continue
            arr = np.asarray(im, dtype=np.uint8)
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
            encoded[staged] = payload
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
                         fw_node=None, fw_patched_path=None):
    """Produce the on-disk writes that refresh the ``.sidx`` manifest records for
    every file this Write changed, so the card passes Stern SD validation.

    Covers ``image.bin`` (cat-0 audio), the per-song ``image-scNN.bin`` banks,
    full-replacement assets (video / image / texture), and in-place ``scene.radium``
    edits (display text + embedded images) via their file-relative
    ``radium_overlays`` (``{i_block: (node, {file_off: bytes})}``)."""
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


def _compute_patches(disk_f, parts, assets_dir, log, progress, cancel,
                     phase=None, label=None, dest_is_device=False):
    """Diff *assets_dir* against the Extract baseline, re-encode / size-fit the
    edits, and resolve them to a flat list of absolute on-disk writes
    ``[(disk_offset, bytes), ...]`` (offsets relative to the start of
    ``disk_f`` — i.e. of the whole card image / device).

    ``disk_f`` is an already-open seekable byte stream over the card image OR
    the physical card; the caller owns it (it must stay open for the duration of
    this call) and closes it afterwards.  This is the shared core of both the
    file Write (:func:`write_image`) and the Direct-SD Write
    (:func:`write_device`), so the exact same patch set is produced whether the
    destination is an image copy or the card itself.

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
    _save_hashcache(assets_dir)
    _stage_done(log, "scanning the assets for changes (checksumming every "
                "sound and video against the Extract baseline)", t_scan)

    if (not audio_edits and not music_edits and not video_edits
            and not image_edits and not texture_edits and not radimg_edits
            and not text_edits and not color_edits):
        raise FileNotFoundError(
            "Nothing to write: every sound (idxNNNN.wav / music_catNN_*.wav) "
            "still matches the Extract baseline (.checksums.md5) and no replaced "
            "videos or images and no edited display text (text/strings.tsv) were "
            "found under %s. Edit a sound, change a display string, or assign a "
            "Replace Video / Replace Image asset first, then Write." % assets_dir)
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
                                ("PAD_STERN_SLOT_SEED_DB", "anti-pop seed dBFS"))]
        adv = ["%s=%s" % (lbl, v) for lbl, v in adv if v]
        if adv:
            log("Advanced audio overrides active for this build: %s."
                % "; ".join(adv), "warning")
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
    if video_edits:
        log("Found %d replaced video(s) to write." % len(video_edits), "info")
    if image_edits:
        log("Found %d replaced image(s) to write." % len(image_edits), "info")
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
        reader = None
        gr_path = img_path = None
        if audio_edits or music_edits:
            phase(1)  # Re-encode audio (Direct-SD phase index; no-op for file Write)
            t0 = time.monotonic()
            gr_path, img_path, reader, fw_node, img_node = _extract_inputs(
                disk_f, parts, work, log, _read_prog)
            _stage_done(log, "reading the firmware and audio image out of "
                        "the card", t0)
            if cancel():
                return None, None, None, None
            if not audio_decode_supported(gr_path):
                # This title's audio codec can't be re-encoded.  If the user
                # only edited video/images, carry on and write those; otherwise
                # it's a hard error.
                msg = (
                    "Audio re-encode isn't supported for this title yet: its "
                    "game firmware uses a Spike 2 codec the engine can't locate "
                    "a single decode path for (e.g. a dual-path codec), so the "
                    "per-sound keystream can't be derived.")
                if not video_edits and not image_edits:
                    raise RuntimeError(msg)
                log(msg + "  Writing only the replaced video(s) / image(s).",
                    "warning")
                audio_edits = {}
                music_edits = []
            else:
                if audio_edits:
                    # Re-encode every edited cat-0 sound to its body bytes — fans
                    # across worker processes (each boots its own emulator), with
                    # a single-process fallback.  Params come from the
                    # Extract-time cache; only a cold cache boots an emulator here.
                    params = _params_for(gr_path, img_path, log, progress)
                    t0 = time.monotonic()
                    audio_patches, _askip = _encode_cat0_sounds(
                        gr_path, img_path, params, audio_edits, np, log,
                        progress, cancel, assets_dir=assets_dir)
                    if audio_patches is None:
                        return None, None, None, None
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
                                _vbypass, _vmode = _vp.bypass_overlay(_f.read())
                            grow_work = grow_work or _work_dir(
                                label, base="spike2_grow_")
                            patched_gr, _fw_size = _build_derive_redirect_cave(
                                gr_path, img_path, audio_patches, np, log,
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
                    if (audio_patches and not pathA_applied
                            and os.environ.get(
                                "PAD_STERN_SKIP_MASTERDIR_FIX") != "1"):
                        t0 = time.monotonic()
                        audio_patches = _restore_masterdir_consumed(
                            gr_path, img_path, audio_patches, log, progress,
                            cancel)
                        if audio_patches is None:
                            return None, None, None, None
                        _assert_param_integrity(gr_path, img_path, audio_patches,
                                                params, np, log, work, progress)
                        _stage_done(log, "the master-directory restore and "
                                    "firmware integrity check", t0)
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
                        if os.environ.get(
                                "PAD_STERN_SKIP_FINAL_VERIFY") != "1":
                            t0 = time.monotonic()
                            try:
                                _verify_final_patches(
                                    gr_path, img_path, audio_patches, params,
                                    np, log, cancel, no_restore=pathA_applied)
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
                    if progress:
                        progress(80, 100, "Re-encoding music bank(s)...")
                    t0 = time.monotonic()
                    music_patches = _compute_music_patches(
                        reader, gr_path, img_path, music_edits, work, log,
                        progress, cancel, np)
                    if cancel():
                        return None, None, None, None
                    _stage_done(log, "re-encoding %d music-bank song(s)"
                                % len(music_edits), t0)

        # A video / image / text-only write (or one whose audio turned out
        # unsupported) still needs a reader to resolve the loose-file inodes.
        if reader is None:
            reader, _fw_node, _img_node = _locate(disk_f, parts)

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
        if text_edits:
            if progress:
                progress(95, 100, "Preparing display text...")
            text_writes, n_text, _t_ov, fw_text_overlay = _radium_text_writes(
                reader, assets_dir, log, cancel, patched_fw=patched_gr)
            _merge_radium_overlays(radium_overlays, _t_ov)
            if cancel():
                return None, None, None, None

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
                return None, None, None, None

        # Edited radium-embedded DXT5 images -> also already-flat (disk_offset,
        # bytes) writes (patched in place inside the scene.radium inode).
        radimg_writes = []
        n_radimg = 0
        if radimg_edits:
            if progress:
                progress(96, 100, "Preparing radium images...")
            radimg_writes, n_radimg, _i_ov = _radium_image_writes(
                reader, assets_dir, baseline, log, cancel)
            _merge_radium_overlays(radium_overlays, _i_ov)
            if cancel():
                return None, None, None, None

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
                dest_is_device=dest_is_device)
            if cancel():
                return None, None, None, None
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
                return None, None, None, None
            _stage_done(log, "preparing %d replaced image(s)"
                        % len(image_edits), t0)

        texture_patches = []   # (inode, payload bytes == inode size)
        if texture_edits:
            if progress:
                progress(94, 100, "Preparing scene textures...")
            texture_patches, _tskip = _prepare_texture_patches(
                reader, texture_edits, log, cancel)
            if cancel():
                return None, None, None, None

        if (not audio_patches and not music_patches and not video_patches
                and not video_grow_jobs and not image_patches
                and not texture_patches and not radimg_writes
                and not text_writes and not color_writes):
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
        writes = list(text_writes) + list(color_writes) + list(radimg_writes)
        for body_off, body in audio_patches.items():
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
        # Regenerate the .sidx manifest records for the changed files so the
        # card passes Stern's SD validation (recompute HMAC-SHA1 + MD5 with the
        # manifest's global validation key).  Best-effort: a missing /
        # unrecognised manifest never fails the Write — it just leaves the card
        # needing re-validation, exactly as before this step existed.
        full_repl = list(video_patches) + list(image_patches) + list(texture_patches)
        t0 = time.monotonic()
        try:
            writes += _compute_sidx_writes(
                reader, disk_f, img_node, audio_patches, music_patches,
                full_repl, radium_overlays, log,
                fw_node=fw_node, fw_patched_path=patched_gr)
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
                _vwrites, valpatch_mode = valpatch.compute_writes(
                    reader, log, fw_overlay=fw_text_overlay)
                writes += _vwrites
            except Exception as e:
                log("Validation bypass skipped (%s)." % e, "warning")

        # Grown videos aren't flat disk writes — they're copied in by the ext4
        # driver after the in-place writes land.  The rebuilt firmware rides the
        # same mechanism, because it too is longer than the file it replaces.
        grow_jobs = list(video_grow_jobs)
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
        grow_plan = ({"offset": reader.base, "jobs": grow_jobs,
                      "n_video": len(video_grow_jobs),
                      "cleanup": grow_work}
                     if grow_jobs else None)
        # Only a plan that actually carries the firmware job owns that dir; a
        # video-only plan doesn't, and neither does a build whose cave was
        # dropped after being written.
        grow_work_handed_off = bool(grow_plan and grow_work
                                    and patched_gr is not None)

        # Scene textures + radium-embedded images fold into the image count
        # (they ARE images) so the (audio, video, image, text) summary tuple
        # stays the same shape.
        # Recoloured lines fold into the text count: they ARE display-text
        # edits, just of the colour rather than the letters.
        counts = (len(audio_patches) + len(music_patches),
                  len(video_patches) + len(video_grow_jobs),
                  len(image_patches) + len(texture_patches) + n_radimg,
                  n_text + n_color)
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


def write_image(original_path, assets_dir, output_path, log=None, progress=None,
                cancel=None, label=None):
    """Patch a copy of the card image at ``output_path`` with the user's edits
    (size-neutral, in place): re-encoded cat-0 audio bodies inside ``image.bin``,
    re-encoded per-song music bodies inside their ``image-scNN.bin`` banks,
    replaced LCD videos written over their original ``.asset`` files, and
    replaced UI images written over their original ``.png`` files.  Any kind of
    edit may be absent — a video/image-only write skips the firmware emulator
    entirely."""
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
    copy_err = []

    def _bg_copy():
        try:
            shutil.copyfile(_lp(original_path), _lp(output_path))
        except BaseException as e:          # surfaced to the caller after join
            copy_err.append(e)

    log("Copying card image to output (in parallel with computing edits)...",
        "info")
    copier = threading.Thread(target=_bg_copy, name="spike2-image-copy",
                              daemon=True)
    copier.start()

    parts = _linux_partitions(original_path)
    disk_f = open(_lp(original_path), "rb")
    try:
        writes, counts, grow_plan, audio_mode, valpatch_mode = _compute_patches(
            disk_f, parts, assets_dir, log, progress, cancel, label=label)
    except BaseException:
        copier.join()                       # let the copy finish before unlinking
        _safe_remove(output_path)
        raise
    finally:
        disk_f.close()

    t0 = time.monotonic()
    copier.join()
    _stage_done(log, "waiting for the card-image copy to finish (the copy "
                "outlived the edit computation - a faster build drive would "
                "shorten this)", t0)
    if copy_err:                            # the background copy itself failed
        _safe_remove(output_path)
        # Say what was being done and where — the raw error is an errno and a
        # path, which read as the app losing the user's card image.
        raise OSError("Could not copy the card image to the build's "
                      "destination:\n\n    %s\n\n%s"
                      % (output_path, copy_err[0])) from copy_err[0]
    if writes is None:                      # cancelled mid-compute
        _safe_remove(output_path)
        _rmtree_grow_plan(grow_plan)
        return (0, 0, 0, 0), None, None

    try:
        # the copy is already on disk; patch the changed bytes in place
        t0 = time.monotonic()
        with open(_lp(output_path), "r+b") as out:
            _apply_writes(out, writes)
            out.flush()
            os.fsync(out.fileno())
        _stage_done(log, "writing the patched bytes into the image", t0)
        # Grow the files that outgrew their slots (oversized videos kept at full
        # quality, and the rebuilt firmware when a blip-free build is on) by
        # copying them in through the ext4 driver — done AFTER the in-place
        # writes so the filesystem it mounts is already consistent.
        t0 = time.monotonic()
        n_grown = _grow_video_slots(output_path, grow_plan, log)
        _stage_done(log, "copying the full-size (grown) videos into the card",
                    t0)
    finally:
        # The rebuilt firmware has been copied onto the card (or has failed to
        # be); either way its scratch dir is ours to remove now.
        _rmtree_grow_plan(grow_plan)
    n_audio, n_video, n_image, n_text = counts
    n_planned = len(grow_plan["jobs"]) if grow_plan else 0
    # The firmware job is queued last, so jobs fail from the end: anything short
    # of the full count means the firmware didn't land, and only the remainder
    # comes out of the video tally.
    n_vid_jobs = grow_plan.get("n_video", n_planned) if grow_plan else 0
    if n_grown < n_planned:
        if n_planned > n_vid_jobs:
            # Serious: the .sidx record already describes the rebuilt firmware,
            # so the card now claims a game binary it doesn't have.
            log("The blip-free game firmware could NOT be written to the card. "
                "Its SD-validation record was already updated to match, so this "
                "card will fail validation — re-run the Write, or build with "
                "PAD_STERN_SKIP_KEYPATCH=1 for a standard (firmware-untouched) "
                "build.", "error")
            # The completion dialog must not claim a blip-free card either.
            audio_mode = ("standard", "the rebuilt blip-free firmware could "
                          "not be copied onto the card (see the build log; "
                          "this image will fail SD validation until rebuilt)")
        n_vid_failed = max(0, n_vid_jobs - n_grown)
        if n_vid_failed:
            # The summary must not claim videos that never landed: every grow
            # job that failed left its slot with the STOCK content.
            n_video -= n_vid_failed
            counts = (n_audio, n_video, n_image, n_text)
            log("%d of %d replaced video(s) could NOT be written — those slots "
                "still hold the game's stock videos. Fix the issue above and "
                "run the Write again." % (n_vid_failed, n_vid_jobs), "error")
    log("Wrote patched image in %s: %s (%d sound(s), %d video(s), "
        "%d image(s), %d display string(s))."
        % (_fmt_dur(time.monotonic() - t_write), output_path,
           n_audio, n_video, n_image, n_text), "success")
    # Return the per-type breakdown (not just the total) so the completion
    # dialog can name what actually changed instead of always saying "sound(s)",
    # plus the audio build mode so it can say whether the card is blip-free or
    # keeps the original-sound scrap (a fallback was invisible outside the log),
    # and the validator status so it can say when the card will fail Stern's
    # SD-card validation on the machine.
    return counts, audio_mode, valpatch_mode


def _rmtree_grow_plan(grow_plan):
    """Remove the scratch dir a grow plan carries (the rebuilt firmware), if any.

    ``_compute_patches`` hands its lifetime to whoever consumes the plan, so
    every path out of that consumer has to come through here.
    """
    d = (grow_plan or {}).get("cleanup")
    if d:
        _rmtree(d)


def _grow_video_slots(image_or_device, grow_plan, log):
    """Copy oversized replacement videos into their (grown) slots via the ext4
    driver.  A growth failure is surfaced loudly but does NOT discard the rest
    of the write — the in-place edits already landed, and the un-grown videos
    simply keep their stock content until the user retries.  Returns the
    number of videos actually grown so the caller can report honest counts."""
    if not grow_plan or not grow_plan.get("jobs"):
        return 0
    from ...core import ext4_grow
    try:
        return ext4_grow.grow_files(image_or_device, grow_plan["offset"],
                                    grow_plan["jobs"], log=log)
    except ext4_grow.Ext4GrowUnavailable as e:
        log("Could not grow the full-size videos: %s" % e, "warning")
        return 0
    except ext4_grow.Ext4GrowError as e:
        log("Video growth failed: %s" % e, "error")
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
    log("Wrote to SD card: %d sound(s), %d video(s), %d image(s), "
        "%d display string(s)."
        % (n_audio, n_video, n_image, n_text), "success")
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


def _match_loudness_enabled():
    return os.environ.get("PAD_STERN_MATCH_LOUDNESS") != "0"


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


def _fit_level(a, orig, rng, np, headroom):
    """Level the replacement *a* (int64, mono 1-D or stereo ``(n, 2)``): match
    the ORIGINAL sound's active RMS when a usable reference decoded, else fall
    back to the fixed peak cap.  See the block comment above for why matching
    limits rather than simply capping the gain."""
    pk = int(np.abs(a).max()) if a.size else 0
    if pk <= 0:
        return a
    if orig is not None and orig.size:
        opk = float(np.abs(orig).max())
        orms = _active_rms(orig, np)
        arms = _active_rms(a, np)
        if opk >= rng * _MATCH_MIN_ORIG_PEAK and orms > 0 and arms > 0:
            ov = _env_float("PAD_STERN_HEADROOM")
            ceil_frac = ov if (ov is not None and 0.05 <= ov <= 1.0) \
                else _MATCH_CEILING
            ceiling = rng * ceil_frac
            gain = min(orms / arms, _MATCH_MAX_GAIN)
            y = a.astype(np.float64) * gain
            # Limit ONLY when the gain actually pushed peaks past the ceiling.
            # Running the limiter unconditionally would shave the loudest 30%
            # of audio that needed nothing, making it quieter than doing
            # nothing at all — the opposite of matching (measured: -0.3 dB on
            # material already at stock level).
            if pk * gain > ceiling:
                y = _soft_limit(y, ceiling, np)
            return np.round(y).astype(np.int64)
    return _amplitude_fit(a, rng, np, headroom=headroom)


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
            if len(body) == s * p["length"]:
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


def _encode_mono(emu, gr, p, wav_path, np, pred=None, log=None):
    # Returns encode_sound's ``(start_off, body)`` — the write offset can sit
    # one word below body_off on delta=-1 codec keys (the start-click fix).
    # Fit to the codec's TRUE emitted sample count (length - BLOCK), not the raw
    # header length: encode_sound only writes that many samples, so fitting to
    # the full length would silently drop the user's last ~200 samples (a click
    # at the loop point of looping music).
    from .spike2.emulator import emitted_length
    n = emitted_length(p["length"])
    fade_ms, headroom = _declick_params()
    s = _load_wav(wav_path, False, np)
    # Band-limit to stock callout bandwidth BEFORE the level fit so the gain
    # targets the audible (post-filter) signal, not HF we're about to remove.
    s = _lowpass(s, _declick_lowpass_hz(), np)
    s = _fit_level(np.asarray(s, np.int64),
                   _stock_render(emu, p, np, stereo=False),
                   _MONO_RANGE, np, headroom)
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


def _encode_stereo(emu, sr, p, wav_path, np, pred=None, log=None):
    from .spike2.emulator import emitted_length
    n = emitted_length(p["length"])
    fade_ms, headroom = _declick_params()
    lp = _declick_lowpass_hz()
    a = _load_wav(wav_path, True, np)
    # Band-limit each channel before the level fit (see _encode_mono).
    a = np.stack([_lowpass(a[:, 0], lp, np), _lowpass(a[:, 1], lp, np)], axis=1)
    a = _fit_level(a, _stock_render(emu, p, np, stereo=True),
                   _STEREO_RANGE, np, headroom)
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

    def __init__(self, assets_dir, gr_path, img_path, byidx, ends):
        from ... import __version__
        self.assets_dir = assets_dir
        self.dir = os.path.join(assets_dir, ".write_cache", "audio")
        os.makedirs(self.dir, exist_ok=True)
        self.byidx = byidx
        self.ends = ends
        h = hashlib.md5()
        with open(_lp(gr_path), "rb") as f:
            h.update(f.read())
        sz = os.path.getsize(_lp(img_path))
        h.update(b"%d" % sz)
        with open(_lp(img_path), "rb") as f:
            h.update(f.read(4 << 20))
            if sz > (8 << 20):
                f.seek(-(4 << 20), 2)
                h.update(f.read(4 << 20))
        env = sorted((k, v) for k, v in os.environ.items()
                     if k.startswith("PAD_STERN_")
                     and k not in self._PATH_ONLY)
        h.update(repr(env).encode())
        h.update(__version__.encode())
        self.base_key = h.hexdigest()

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


def _encode_cat0_serial(gr_path, img_path, byidx, edits, np, log, progress,
                        cancel):
    """Single-process cat-0 re-encode (the fallback + correctness reference).
    Returns ``(patches, skipped, results)`` — *results* maps each freshly
    encoded idx to its ``(off, body)`` so the caller can cache it."""
    from .spike2.codec import GenRecover, StereoRecover
    from .spike2.emulator import Spike2Emu
    log("Booting firmware codec engine...", "info")
    emu = Spike2Emu(gr_path, img_path)
    emu.boot()
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
                off, body = (_encode_stereo(emu, sr, p, wav, np, pred=pred,
                                            log=log)
                             if p["chan"] == 2
                             else _encode_mono(emu, gr, p, wav, np, pred=pred,
                                               log=log))
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
                          log, progress, cancel):
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
    log("Re-encoding %d sound(s) across %d process(es)..."
        % (len(edits), nworkers), "info")
    ctx = mp.get_context("spawn")
    pool = ctx.Pool(nworkers, initializer=init_encode_worker,
                    initargs=(gr_path, img_path, params))
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
    PAGE = 0x1000
    loads = [(va, mz) for _ph, va, _o, _fz, mz, _fl in _iter_phdrs(raw)]
    if not loads:
        raise RuntimeError("no PT_LOAD segments in the firmware ELF.")
    loads.sort()

    # Address space no PT_LOAD covers: the gaps between consecutive segments,
    # then everything above the highest one.
    frees = []
    for i, (va, mz) in enumerate(loads):
        lo = (va + mz + PAGE - 1) & ~(PAGE - 1)
        hi = (loads[i + 1][0] & ~(PAGE - 1)) if i + 1 < len(loads) else lo + (32 << 20)
        if hi > lo:
            frees.append((lo, hi))

    # Prefer a region within a single ARM branch (+/-32 MB) of the window-read
    # function, which is the only kind of region caves were placed in before --
    # a build that placed then still places identically, same VA, same entry
    # instruction.  Falling back to a region out of branch reach costs only the
    # two long hops (see _asm_derive_redirect_cave and the caller's entry
    # patch), and it is what makes a real-sized build possible at all: the cave
    # carries a stock copy of every redirected window, ~1 KB per replaced sound,
    # so Led Zeppelin LE 1.22's 28 KB text/data gap holds about 27 sounds and
    # its only other free region is 64 MB up.  PAD-56 replaced 201 sounds, blip-
    # free silently fell back to the standard build, and every one of those
    # sounds kept the scrap the option exists to remove.
    want = (need + PAGE - 1) & ~(PAGE - 1)
    fits = [(lo, hi) for lo, hi in frees if hi - lo >= want]  # padded extent
    near = [f for f in fits if abs(f[0] - (fn + 8)) < _CAVE_MAX_BRANCH]
    pick = near[0] if near else (fits[0] if fits else None)
    if pick is None:
        raise RuntimeError(
            "no unclaimed address space fits a %d-byte cave -- using the "
            "standard build." % need)
    cave_va, gap_hi = pick
    gap = gap_hi - cave_va

    slot = None
    e_phoff = struct.unpack_from("<I", raw, 0x1c)[0]
    e_phentsize = struct.unpack_from("<H", raw, 0x2a)[0]
    e_phnum = struct.unpack_from("<H", raw, 0x2c)[0]
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        if struct.unpack_from("<I", raw, o)[0] == _PT_GNU_STACK:
            slot = o
            break
    if slot is None:
        raise RuntimeError(
            "firmware has no PT_GNU_STACK header to repurpose for the cave.")

    # Page-align the appended data so p_offset == p_vaddr (mod PAGE), which the
    # loader requires, and pad the file out to the whole declared extent -- a
    # p_filesz running past EOF makes the loader read off the end of the file.
    append_off = (len(raw) + PAGE - 1) & ~(PAGE - 1)
    raw.extend(b"\0" * (append_off + want - len(raw)))
    struct.pack_into("<8I", raw, slot,
                     1,              # p_type = PT_LOAD
                     append_off,     # p_offset
                     cave_va,        # p_vaddr
                     cave_va,        # p_paddr
                     want,           # p_filesz
                     want,           # p_memsz
                     7,              # p_flags = R|W|X (BASEVAR is written)
                     PAGE)           # p_align
    return cave_va, append_off, gap


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

    Raises ``RuntimeError`` (caught by the caller, which then falls back to the
    standard restore build) if the window-read function can't be located, the
    consumed-window map is missing, no unclaimed address space is large enough
    for the cave, the firmware has no repurposable program header, or the located
    function turns out not to be the window reader."""
    from .spike2.elf import parse_elf
    raw = bytearray(open(gr_path, "rb").read())
    segs, _relocs = parse_elf(bytes(raw))   # relocs no longer used: the cave has its own segment

    def va2off(va):
        return _cave_va2off(segs, va)

    # Locate the window-read function by its unique prologue signature (address
    # differs per firmware; the routine itself is identical).
    fn = _locate_window_read_fn(raw)
    if fn is None:
        raise RuntimeError(
            "window-read function not located (prologue signature absent or "
            "ambiguous) -- this firmware isn't supported by the blip-free cave.")
    ret = fn + 12
    log("Blip-free cave: window-read function located at 0x%x." % fn, "info")

    # The exact bytes the boot-derive consumes for each replaced sound == the
    # window ranges to redirect (from the Extract cache, or a fresh derive).
    per_body = _replaced_consumed_offsets(gr_path, img_path, patches, np, log,
                                          progress)
    windows = []   # (lo, hi) image file-offset ranges (2 per mono sound)
    with open(img_path, "rb") as f:
        stock_chunks = []
        for off in sorted(patches):
            wcon = per_body.get(off)
            if wcon is None or not len(wcon):
                continue
            brk = np.where(np.diff(wcon) != 1)[0]
            starts = np.concatenate(([0], brk + 1))
            ends = np.concatenate((brk, [len(wcon) - 1]))
            for s, e in zip(starts, ends):
                a0, b0 = int(wcon[s]), int(wcon[e]) + 1
                windows.append((a0, b0))
                f.seek(a0)
                stock_chunks.append(f.read(b0 - a0))
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

    patched_gr = os.path.join(out_dir, "game_real_pathA")
    with open(patched_gr, "wb") as f:
        f.write(bytes(raw))

    log("Blip-free cave built: %d window(s) across %d replaced sound(s) "
        "redirected to stock; fn=0x%x FIRST_OFF=0x%x; cave@0x%x in its own "
        "%d-byte segment (file+0x%x), placed in %d bytes of unclaimed address "
        "space %s; game_real %d -> %d bytes."
        % (len(windows), len(patches), fn, first_off, cave_va, len(blob),
           append_off, gap,
           "in branch reach" if len(entry) == 4 else
           "reached by an absolute jump",
           os.path.getsize(gr_path), len(raw)), "success")
    return patched_gr, len(raw)


def _restore_masterdir_consumed(gr_path, img_path, patches, log, progress=None,
                                cancel=None):
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
    """
    if not patches:
        return patches
    from unicorn import UC_HOOK_MEM_READ

    from .spike2 import emulator as EM
    from .spike2.emulator import Spike2Emu
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

    _note_cold_consumed(log)
    reads = {off: set() for off in patches}     # body_off -> consumed file offsets

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
            end = off + len(body)
            emu.mu.hook_add(UC_HOOK_MEM_READ, _mk(off, end, reads[off]),
                            begin=(EM.DESC_BASE + off) & ~0xfff,
                            end=((EM.DESC_BASE + end) + 0xfff) & ~0xfff)
        # Progress, because this is the multi-minute stretch a cold cache adds
        # to a Write and a stationary bar here is what reads as a hang.
        emu.derive_params(progress=progress)    # the real MASTERDIR_DECODE pass
        for off, body in patches.items():
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
                          cancel=None, no_restore=False):
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
            reverted = (
                np.empty(0, int) if no_restore
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

    from .spike2.emulator import Spike2Emu
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
    stock = {p["idx"]: (p["scale"], p["pred16"]) for p in params}
    cur = {r["idx"]: (r["scale"], r["pred16"]) for r in rows}
    shifted = [i for i in stock if i in cur and stock[i] != cur[i]]
    if shifted:
        raise RuntimeError(
            "Master-directory integrity check FAILED: %d of %d sounds would "
            "decode with the wrong codec parameters (the card would reboot on "
            "audio). The re-encode could not preserve the firmware's "
            "forward-chain; aborting the write rather than producing a broken "
            "card." % (len(shifted), len(stock)))
    log("Master-directory integrity verified: all %d sounds keep valid decode "
        "parameters." % len(stock), "success")


def _encode_cat0_sounds(gr_path, img_path, params, audio_edits, np, log,
                        progress, cancel, assets_dir=None):
    """Re-encode every edited cat-0 sound to its body bytes — parallel across
    processes with a single-process fallback.  Returns ``({body_off: body},
    [skipped_idx])`` or ``(None, None)`` if cancelled.

    With *assets_dir*, sounds unchanged since their last encode replay from
    that folder's :class:`_AudioBodyCache` instead of re-encoding."""
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
                                    _slot_end_map(params))
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
                cancel)
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
            gr_path, img_path, byidx, remaining, np, log, progress, cancel)
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


def _derive_encode_bank(gr_path, img_path, rev, cid, sc_path, edits, np):
    """Re-encode one bank's edited songs on a FRESH CatEmu (deriving several
    banks on one emu grinds the loader — see ``spike2/category.py``).  *edits* =
    ``[(idx, wav_path), ...]`` for this bank.  Returns ``(patches, skipped)``
    where ``patches`` = ``[(cid, idx, body_off, body), ...]`` (the parent maps
    cid back to its ext4 inode) and ``skipped`` = ``[(cid, idx), ...]``.
    Bit-identical to the serial inner loop, just per-bank so it parallelises."""
    from .spike2.category import CatEmu
    from .spike2.codec import GenRecover, StereoRecover
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
            off, body = (_encode_stereo(emu, sr, p, wav, np, pred=pred)
                         if p["chan"] == 2
                         else _encode_mono(emu, gr, p, wav, np, pred=pred))
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
    gr_path, img_path, rev, cid, sc_path, edits = args
    import numpy as np
    try:
        return _derive_encode_bank(gr_path, img_path, rev, cid, sc_path, edits,
                                   np)
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
        gr_path, img_path, rev, cid, sc_path, edits = t
        try:
            out.append(_derive_encode_bank(gr_path, img_path, rev, cid, sc_path,
                                           edits, np))
        except Exception as e:
            log("music_cat%02d: re-encode failed (%s); skipped." % (cid, e),
                "warning")
            out.append(([], [(cid, idx) for idx, _ in edits]))
    return out


def _compute_music_patches(reader, gr_path, img_path, music_edits, work, log,
                           progress, cancel, np):
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
    tasks = [(gr_path, img_path, rev, c, sc[c][1], by_cat[c]) for c in cids]
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
