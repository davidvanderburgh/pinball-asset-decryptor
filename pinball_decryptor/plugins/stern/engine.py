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
import os
import pickle
import re
import tempfile
import wave

# The engine is wired; a missing unicorn/numpy is surfaced via the plugin's
# prerequisite probe + a lazy import error, not by hiding the tabs.
AVAILABLE = True

_WAV_RE = re.compile(r"(?:idx)?0*(\d+)", re.IGNORECASE)


# --------------------------------------------------------------------------
# params cache (fingerprint of game_real + image.bin master-dir region)
# --------------------------------------------------------------------------
def _fingerprint(game_real_path, image_path):
    h = hashlib.sha256()
    with open(game_real_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    with open(image_path, "rb") as f:
        h.update(f.read(0x20000))   # header + master-directory source region
    return h.hexdigest()


def _cache_path(fp):
    d = os.path.join(tempfile.gettempdir(), "pinball_spike2_params")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, fp[:32] + ".pkl")


def _load_or_derive_params(emu, game_real_path, image_path, log, progress):
    fp = _fingerprint(game_real_path, image_path)
    cache = _cache_path(fp)
    if os.path.exists(cache):
        try:
            params = pickle.load(open(cache, "rb"))
            log("Loaded cached codec parameters (%d sounds)." % len(params), "info")
            return params
        except Exception:
            pass
    log("Deriving codec parameters from the firmware (one-time per card, "
        "~2-5 min)...", "info")
    if progress:
        progress(0, 0, "Deriving codec parameters...")
    params = emu.derive_params()
    try:
        pickle.dump(params, open(cache, "wb"))
    except Exception:
        pass
    log("Derived parameters for %d sounds." % len(params), "success")
    return params


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


def _parse_radium(data):
    """Map ``asset_ref -> name`` from a ``scene.radium``: each LCD video asset is
    named by the scene-element identifier immediately preceding its
    ``N.asset/M.asset`` reference (verified contiguous on the TMNT card)."""
    import bisect
    names = [(m.start(), m.group().decode("latin1"))
             for m in _IDENT.finditer(data)]
    name_offs = [p for p, _ in names]
    out = {}
    for m in _ASSET_REF.finditer(data):
        ref = m.group().decode()
        if ref in out:
            continue
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
    log("Extracting %d video(s)..." % len(vids), "info")
    manifest = []
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
    try:
        with open(os.path.join(vid_dir, "manifest.txt"), "w", encoding="utf-8") as f:
            f.write("# output\tcard path\tbytes\n" + "\n".join(manifest) + "\n")
    except Exception:
        pass
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
# --------------------------------------------------------------------------
def extract_all(image_path, partitions, output_dir, log=None, progress=None,
                cancel=None, phase=None, open_disk=None, log_line=None,
                music_banks=False):
    """Decode every cat-0 sound in the card image to ``output_dir`` as WAV
    (under ``audio/``) and extract videos (under ``video/``).

    ``music_banks`` ALSO decodes the per-category ``image-scNN.bin`` banks — the
    licensed songs / extra sound sets the six multi-category titles (Metallica,
    D&D, Rush, Deadpool, Foo Fighters, John Wick) keep outside cat-0.  It's
    OFF by default for now because driving the firmware codec per bank is slow
    (~10-15 min for Metallica's 24 songs even parallelized — see
    plans/spike2_multicat_handoff.md "perf"); titles without banks are a fast
    no-op.  The decode is correct; only the speed needs work before it's a safe
    always-on default.

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

    work = tempfile.mkdtemp(prefix="spike2_")
    emu = None
    disk_f = open_disk() if open_disk is not None else open(image_path, "rb")
    try:
        os.makedirs(output_dir, exist_ok=True)
        gr_path, img_path, reader, _fw, _img = _extract_inputs(
            disk_f, partitions, work, log, _read_prog)
        if cancel():
            return 0

        # videos + images first (quick file copies) so they appear before the
        # long audio decode
        phase(2)  # Extract video
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
        try:
            extract_images(reader, output_dir, log=log,
                           progress=(lambda c, t, d="": progress(
                               13 + int(c * 2 / max(t, 1)), 100, d)) if progress else None,
                           cancel=cancel)
        except Exception as e:
            log("Image extraction failed (%s); continuing." % e, "warning")
        if cancel():
            return 0

        phase(4)  # Decode audio
        if not audio_decode_supported(gr_path):
            log("Audio decode isn't supported for this title yet: its game "
                "firmware uses a Spike 2 codec the engine can't locate a "
                "single decode path for (e.g. a dual-path codec), so the "
                "per-sound keystream can't be derived. Video + image "
                "extraction completed normally.", "warning")
            phase(5)  # Checksums
            return 0
        log("Booting firmware codec engine...", "info")
        emu = Spike2Emu(gr_path, img_path)
        emu.boot()
        params = _load_or_derive_params(emu, gr_path, img_path, log, progress)
        emu.close()
        emu = None   # decode runs in worker processes (or a fresh emu on fallback)

        audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        total = len(params)
        ok = None
        nworkers = max(1, min((os.cpu_count() or 2) - 2, 8))
        if nworkers > 1 and not cancel():
            try:
                log("Decoding %d sounds across %d processes..." % (total, nworkers), "info")
                ok = _parallel_decode(gr_path, img_path, params, audio_dir,
                                      log, progress, cancel, nworkers,
                                      log_line=log_line)
            except Exception as e:
                log("Parallel decode unavailable (%s); using a single process."
                    % e, "warning")
                ok = None
        if ok is None:
            emu = Spike2Emu(gr_path, img_path)
            emu.boot()
            ok = _serial_decode(emu, params, audio_dir, log, progress, cancel,
                                log_line=log_line)
        log("Decoded %d/%d sounds to %s" % (ok, total, audio_dir), "success")
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


def _serial_decode(emu, params, audio_dir, log, progress, cancel, log_line=None):
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
        _write_wav(os.path.join(audio_dir, "idx%04d.wav" % p["idx"]), L, R, stereo)
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
                "    idx%04d %s %s   0%%" % (idx, _dur_str(length, chan), _bar(0)),
                "info")
    if kind == "prog":
        _, idx, frac, length, chan = msg
        return ("dec%d" % idx,
                "    idx%04d %s %s %3d%%"
                % (idx, _dur_str(length, chan), _bar(frac), int(frac * 100)),
                "info")
    # done
    _, idx, length, chan = msg
    return ("dec%d" % idx,
            "    idx%04d %s decoded" % (idx, _dur_str(length, chan)), "success")


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
                     nworkers, log_line=None):
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
    tasks = [(p, os.path.join(audio_dir, "idx%04d.wav" % p["idx"])) for p in params]
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
    ``<= target``."""
    pad = target - len(data)
    if pad <= 0:
        return data[:target]
    if pad < 8:
        # Too small for a box header; a few trailing bytes after a complete
        # file are ignored by MP4/MOV demuxers.
        return data + b"\x00" * pad
    if pad < 0x1_0000_0000:
        return data + pad.to_bytes(4, "big") + b"free" + b"\x00" * (pad - 8)
    # 64-bit box: size word = 1, then the real size as an 8-byte largesize.
    return (data + (1).to_bytes(4, "big") + b"free"
            + pad.to_bytes(8, "big") + b"\x00" * (pad - 16))


def _changed_videos(assets_dir, baseline):
    """Return ``[(fname, card_path, staged_path), ...]`` for the videos under
    ``assets_dir/video`` whose current bytes differ from the Extract baseline
    (``.checksums.md5``).  Empty when there's no ``video/manifest.txt`` (an
    audio-only extract, or Write pointed at a subfolder)."""
    from ...core.checksums import md5_file
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
            try:
                if base is not None and md5_file(staged) == base:
                    continue           # untouched since extract
            except OSError:
                pass
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
    return _pad_isobmff(shrunk, target)


def _prepare_video_patches(reader, video_edits, work_dir, log, cancel):
    """Resolve each changed video to its card inode and size-fit its bytes.
    Returns ``([(node, payload), ...], n_skipped)`` where every payload is
    exactly the inode's size, ready for an in-place ``disk_ranges`` write."""
    nodes = _resolve_card_nodes(reader, [cp for (_f, cp, _s) in video_edits],
                                cancel)
    patches = []
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
        payload = _fit_video_payload(staged, node["size"], work_dir, log)
        if payload is None:
            skipped += 1
            continue
        patches.append((node, payload))
        log("Video %s: ready to patch (%d bytes)." % (fname, node["size"]),
            "info")
    return patches, skipped


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
    from ...core.checksums import md5_file
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
            try:
                if base is not None and md5_file(staged) == base:
                    continue           # untouched since extract
            except OSError:
                pass
            out.append((output, card_path, staged))
    return out


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


def _compute_patches(disk_f, parts, assets_dir, log, progress, cancel,
                     phase=None):
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

    Returns ``(writes, counts)`` where ``counts`` is ``(n_audio, n_video,
    n_image)``; returns ``(None, None)`` if cancelled.  Raises
    ``FileNotFoundError`` when there's nothing to write and ``RuntimeError``
    when nothing could be re-encoded / fit."""
    phase = phase or (lambda i: None)

    import numpy as np

    from ...core.checksums import md5_file, read_checksums
    from .spike2.codec import GenRecover, StereoRecover
    from .spike2.emulator import Spike2Emu, audio_decode_supported

    # Every idxNNNN.wav under assets_dir (the leading index survives an
    # Auto-transcribe rename, e.g. "idx0651 - text.wav"); scan recursively so the
    # user can point Write at the extract root or its audio/ subdir.
    all_wavs = {}
    for root, _dirs, files in os.walk(assets_dir):
        for fn in files:
            if not fn.lower().endswith(".wav"):
                continue
            m = _WAV_RE.match(os.path.splitext(fn)[0])
            if m:
                all_wavs[int(m.group(1))] = os.path.join(root, fn)
    # Only re-encode/patch what the user actually changed.  The folder is
    # normally the whole Extract output (thousands of WAVs + the LCD videos);
    # diff each asset against the Extract baseline (.checksums.md5) so an
    # untouched (or merely Auto-transcribe-renamed) sound/clip is skipped.
    baseline = read_checksums(assets_dir)
    base_by_idx = {}
    for rel in baseline:
        mm = _WAV_RE.match(os.path.splitext(os.path.basename(rel))[0])
        if mm:
            base_by_idx[int(mm.group(1))] = baseline[rel]
    audio_edits = {}
    if all_wavs:
        if base_by_idx:
            for idx, path in all_wavs.items():
                try:
                    if md5_file(path) != base_by_idx.get(idx):
                        audio_edits[idx] = path
                except OSError:
                    audio_edits[idx] = path
        else:
            audio_edits = dict(all_wavs)

    video_edits = _changed_videos(assets_dir, baseline)
    image_edits = _changed_images(assets_dir, baseline)

    if not audio_edits and not video_edits and not image_edits:
        raise FileNotFoundError(
            "Nothing to write: every idxNNNN.wav still matches the Extract "
            "baseline (.checksums.md5) and no replaced videos or images were "
            "found under %s. Edit a sound or assign a Replace Video / Replace "
            "Image asset first, then Write." % assets_dir)
    if audio_edits:
        if base_by_idx:
            log("Found %d edited sound(s) of %d to write."
                % (len(audio_edits), len(all_wavs)), "info")
        else:
            log("No .checksums.md5 baseline found; re-encoding all %d sound(s)."
                % len(audio_edits), "warning")
    if video_edits:
        log("Found %d replaced video(s) to write." % len(video_edits), "info")
    if image_edits:
        log("Found %d replaced image(s) to write." % len(image_edits), "info")

    def _read_prog(c, t):
        if progress:
            progress(int(c * 10 / max(t, 1)), 100, "Reading image.bin")

    work = tempfile.mkdtemp(prefix="spike2_")
    emu = None
    try:
        audio_patches = {}     # body_off -> bytes (inside image.bin)
        img_node = None
        reader = None
        if audio_edits:
            phase(1)  # Re-encode audio (Direct-SD phase index; no-op for file Write)
            gr_path, img_path, reader, _fw_node, img_node = _extract_inputs(
                disk_f, parts, work, log, _read_prog)
            if cancel():
                return None, None
            if not audio_decode_supported(gr_path):
                # This title's audio codec can't be re-encoded.  If the user
                # only edited video, carry on and write that; otherwise it's a
                # hard error.
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
            else:
                log("Booting firmware codec engine...", "info")
                emu = Spike2Emu(gr_path, img_path)
                emu.boot()
                params = _load_or_derive_params(emu, gr_path, img_path, log,
                                                progress)
                byidx = {p["idx"]: p for p in params}

                # re-encode each edited sound into its body bytes
                skipped = []
                gr = sr = None
                for n, (idx, wav_path) in enumerate(sorted(audio_edits.items())):
                    if cancel():
                        return None, None
                    if idx not in byidx:
                        log("idx %d not a known sound; skipping." % idx, "warning")
                        continue
                    p = byidx[idx]
                    if progress:
                        progress(10 + int(n * 75 / max(len(audio_edits), 1)), 100,
                                 "Re-encoding idx %d" % idx)
                    if p["chan"] == 2:
                        sr = sr or StereoRecover(emu)
                    else:
                        gr = gr or GenRecover(emu)
                    # Verify the keystream recovery actually round-trips for THIS
                    # sound before trusting its re-encode -- skip (never patch)
                    # sounds whose codec variant the analytic encode can't yet
                    # reproduce bit-exact, so Write can't silently corrupt them
                    # (see _recovery_valid).
                    if not _recovery_valid(emu, gr, sr, p, np):
                        skipped.append(idx)
                        log("idx %d: re-encode isn't bit-exact for this sound's "
                            "codec (skipped -- left unchanged in the output)."
                            % idx, "warning")
                        continue
                    if p["chan"] == 2:
                        body = _encode_stereo(emu, sr, p, wav_path, np)
                    else:
                        body = _encode_mono(emu, gr, p, wav_path, np)
                    audio_patches[p["body_off"]] = body
                    log("Re-encoded idx %d (%s, %d samples)."
                        % (idx, "stereo" if p["chan"] == 2 else "mono",
                           p["length"]), "info")
                if skipped:
                    log("%d sound(s) skipped (re-encode unsupported for their "
                        "codec): %s"
                        % (len(skipped), ", ".join(map(str, skipped))), "warning")
                if (not audio_patches and not video_edits
                        and not image_edits):
                    raise RuntimeError(
                        "None of the edited sounds could be re-encoded bit-exact "
                        "for this title's codec yet, so nothing was written (the "
                        "card image was not modified).")

        # A video-only write (or one whose audio turned out unsupported) still
        # needs a reader to resolve the .asset inodes.
        if reader is None:
            reader, _fw_node, _img_node = _locate(disk_f, parts)

        video_patches = []     # (inode, payload bytes == inode size)
        if video_edits:
            if progress:
                progress(86, 100, "Preparing video...")
            video_patches, _vskip = _prepare_video_patches(
                reader, video_edits, work, log, cancel)
            if cancel():
                return None, None

        image_patches = []     # (inode, payload bytes == inode size)
        if image_edits:
            if progress:
                progress(92, 100, "Preparing images...")
            image_patches, _iskip = _prepare_image_patches(
                reader, image_edits, work, log, cancel)
            if cancel():
                return None, None

        if not audio_patches and not video_patches and not image_patches:
            raise RuntimeError(
                "Nothing could be written: no sound re-encoded and no replaced "
                "video or image could be fit to its original slot (the card "
                "image was not modified).")

        # Flatten every patch to absolute (disk_offset, bytes) writes via the
        # ext4 file->disk map.  The offsets are relative to the start of the
        # card image / device, so the same list applies whether we patch an
        # image copy (write_image) or the card itself (write_device).
        writes = []
        for body_off, body in audio_patches.items():
            for disk, n in reader.disk_ranges(img_node, body_off, len(body)):
                writes.append((disk, body[:n]))
                body = body[n:]
        for node, payload in video_patches + image_patches:
            off = 0
            for disk, n in reader.disk_ranges(node, 0, len(payload)):
                writes.append((disk, payload[off:off + n]))
                off += n
        return writes, (len(audio_patches), len(video_patches),
                        len(image_patches))
    finally:
        if emu is not None:
            emu.close()
        _rmtree(work)


def _apply_writes(out, writes):
    """Apply ``[(disk_offset, bytes), ...]`` to an open seekable destination
    (an image copy opened ``r+b``, or a writable :class:`.rawdevice.RawDeviceFile`
    over the card)."""
    for disk, b in writes:
        out.seek(disk)
        out.write(b)


def write_image(original_path, assets_dir, output_path, log=None, progress=None,
                cancel=None):
    """Patch a copy of the card image at ``output_path`` with the user's edits
    (size-neutral, in place): re-encoded audio bodies inside ``image.bin``,
    replaced LCD videos written over their original ``.asset`` files, and
    replaced UI images written over their original ``.png`` files.  Any kind of
    edit may be absent — a video/image-only write skips the firmware emulator
    entirely."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    import shutil

    parts = _linux_partitions(original_path)
    disk_f = open(original_path, "rb")
    try:
        writes, counts = _compute_patches(
            disk_f, parts, assets_dir, log, progress, cancel)
    finally:
        disk_f.close()
    if writes is None:                          # cancelled mid-compute
        return 0

    # copy the card image, then patch the changed bytes in place
    log("Copying card image to output...", "info")
    if progress:
        progress(0, 0, "Copying image...")
    shutil.copyfile(original_path, output_path)
    with open(output_path, "r+b") as out:
        _apply_writes(out, writes)
        out.flush()
        os.fsync(out.fileno())
    n_audio, n_video, n_image = counts
    log("Wrote patched image: %s (%d sound(s), %d video(s), %d image(s))."
        % (output_path, n_audio, n_video, n_image), "success")
    return n_audio + n_video + n_image


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
    from .rawdevice import read_mbr

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
    from .rawdevice import RawDeviceFile

    phase(0)  # Scan
    parts = device_partitions(device_path, partition_override, log=log)

    with RawDeviceFile(device_path, writable=False) as disk_f:
        writes, counts = _compute_patches(
            disk_f, parts, assets_dir, log, progress, cancel, phase=phase)
    if writes is None:                          # cancelled mid-compute
        return 0

    phase(2)  # Write to SD card
    log("Writing changes directly to the SD card (in place)...", "info")
    if progress:
        progress(0, 0, "Writing to SD card...")
    with RawDeviceFile(device_path, writable=True) as out:
        _apply_writes(out, writes)
        out.flush()
    n_audio, n_video, n_image = counts
    log("Wrote to SD card: %d sound(s), %d video(s), %d image(s)."
        % (n_audio, n_video, n_image), "success")
    return n_audio + n_video + n_image


# --------------------------------------------------------------------------
# encode helpers
# --------------------------------------------------------------------------
def _load_wav(path, want_stereo, np):
    w = wave.open(path, "rb")
    n = w.getnframes(); ch = w.getnchannels(); sr = w.getframerate()
    a = np.frombuffer(w.readframes(n), np.int16).astype(np.int64)
    w.close()
    a = a.reshape(-1, ch)
    if sr != 44100 and len(a):
        idx = np.clip((np.arange(int(len(a) * 44100 / sr)) * sr / 44100).astype(int),
                      0, len(a) - 1)
        a = a[idx]
    if want_stereo:
        return a if ch == 2 else np.repeat(a, 2, axis=1)
    return a.mean(1).astype(np.int64) if ch == 2 else a[:, 0]


def _fit(a, length, np):
    a = np.asarray(a, np.int64)
    if len(a) > length:
        a = a[:length]
    if len(a) < length:
        a = np.concatenate([a, np.zeros(length - len(a), np.int64)])
    return a


def _amplitude_fit(samples, rng, np, headroom=0.97):
    pk = int(np.abs(samples).max()) if len(samples) else 0
    if pk <= 0:
        return samples
    return (samples.astype(np.float64) * (rng * headroom / pk)).astype(np.int64)


_MONO_RANGE = 11147
_STEREO_RANGE = 21452


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
            body = sr.encode_sound(p, L0[:cmp_n], R0[:cmp_n])
        else:
            body = gr.encode_sound(p, L0[:cmp_n])
        if not isinstance(emu.mm, _BodyOverlay):
            emu.mm = _BodyOverlay(emu.mm)
        emu.mm.patch = (p["body_off"], bytes(body))
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


def _encode_mono(emu, gr, p, wav_path, np):
    length = p["length"]
    s = _load_wav(wav_path, False, np)
    s = _amplitude_fit(s, _MONO_RANGE, np)
    tgt = _fit(np.clip(s, -_MONO_RANGE, _MONO_RANGE), length, np)
    return gr.encode_sound(p, tgt)


def _encode_stereo(emu, sr, p, wav_path, np):
    length = p["length"]
    a = _load_wav(wav_path, True, np)
    a = _amplitude_fit(a, _STEREO_RANGE, np)
    L = _fit(np.clip(a[:, 0], -_STEREO_RANGE, _STEREO_RANGE), length, np)
    R = _fit(np.clip(a[:, 1], -_STEREO_RANGE, _STEREO_RANGE), length, np)
    return sr.encode_sound(p, L, R)


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
