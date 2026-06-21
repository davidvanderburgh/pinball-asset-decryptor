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
import struct
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
        "~1-2 min)...", "info")
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
                cancel=None, phase=None):
    """Decode every cat-0 sound in the card image to ``output_dir`` as WAV
    (under ``audio/``) and extract videos (under ``video/``)."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    phase = phase or (lambda i: None)
    from .spike2.emulator import Spike2Emu, audio_decode_supported

    def _read_prog(c, t):
        if progress:
            progress(int(c * 5 / max(t, 1)), 100, "Reading image.bin")

    work = tempfile.mkdtemp(prefix="spike2_")
    emu = None
    disk_f = open(image_path, "rb")
    try:
        os.makedirs(output_dir, exist_ok=True)
        gr_path, img_path, reader, _fw, _img = _extract_inputs(
            disk_f, partitions, work, log, _read_prog)
        if cancel():
            return 0

        # videos first (quick file copies) so they appear before the long decode
        phase(2)  # Extract video
        try:
            extract_videos(reader, output_dir, log=log,
                           progress=(lambda c, t, d="": progress(
                               5 + int(c * 10 / max(t, 1)), 100, d)) if progress else None,
                           cancel=cancel)
        except Exception as e:
            log("Video extraction failed (%s); continuing with audio." % e, "warning")
        if cancel():
            return 0

        phase(3)  # Decode audio
        if not audio_decode_supported(gr_path):
            log("Audio decode isn't supported for this title yet: its game "
                "firmware uses a Spike 2 codec the engine can't locate a "
                "single decode path for (e.g. a dual-path codec), so the "
                "per-sound keystream can't be derived. Video extraction "
                "completed normally.", "warning")
            phase(4)  # Checksums
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
                                      log, progress, cancel, nworkers)
            except Exception as e:
                log("Parallel decode unavailable (%s); using a single process."
                    % e, "warning")
                ok = None
        if ok is None:
            emu = Spike2Emu(gr_path, img_path)
            emu.boot()
            ok = _serial_decode(emu, params, audio_dir, log, progress, cancel)
        log("Decoded %d/%d sounds to %s" % (ok, total, audio_dir), "success")
        return ok
    finally:
        if emu is not None:
            emu.close()
        disk_f.close()
        _rmtree(work)


def _serial_decode(emu, params, audio_dir, log, progress, cancel):
    total = len(params)
    ok = 0
    for i, p in enumerate(params):
        if cancel():
            log("Cancelled after %d sounds." % ok, "info")
            break
        if progress:
            progress(15 + int(i * 85 / max(total, 1)), 100,
                     "Decoding sound %d/%d" % (i + 1, total))
        try:
            r = emu.decode(p, cancel=cancel)
        except Exception as e:
            log("idx %d: decode failed (%s)" % (p["idx"], e), "warning")
            continue
        if r is None:
            continue
        L, R, stereo = r
        _write_wav(os.path.join(audio_dir, "idx%04d.wav" % p["idx"]), L, R, stereo)
        ok += 1
    return ok


def _parallel_decode(gr_path, img_path, params, audio_dir, log, progress, cancel,
                     nworkers):
    """Decode across ``nworkers`` spawned emulator processes (each boots once,
    decodes its share, writes WAVs directly).  Raises on any pool failure so the
    caller can fall back to a single process."""
    import multiprocessing as mp

    from .spike2.parallel import decode_to_wav, init_worker, probe

    tasks = [(p, os.path.join(audio_dir, "idx%04d.wav" % p["idx"])) for p in params]
    total = len(tasks)
    ctx = mp.get_context("spawn")
    pool = ctx.Pool(nworkers, initializer=init_worker, initargs=(gr_path, img_path))
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
        pool.terminate()
        pool.join()
    return ok


def write_image(original_path, assets_dir, output_path, log=None, progress=None,
                cancel=None):
    """Re-encode edited WAVs under ``assets_dir`` and patch them into a copy of
    the card image at ``output_path`` (size-neutral, in place)."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    import shutil

    import numpy as np

    from .spike2.codec import GenRecover, StereoRecover
    from .spike2.emulator import Spike2Emu, audio_decode_supported

    # which idx slots did the user edit?  Scan recursively so the user can
    # point Write at the extract root or its audio/ subdir; the leading index
    # in the filename survives an Auto-transcribe rename (idx0651 - text.wav).
    edits = {}
    for root, _dirs, files in os.walk(assets_dir):
        for fn in files:
            if not fn.lower().endswith(".wav"):
                continue
            m = _WAV_RE.match(os.path.splitext(fn)[0])
            if m:
                edits[int(m.group(1))] = os.path.join(root, fn)
    if not edits:
        raise FileNotFoundError("No idxNNNN.wav files found in %s" % assets_dir)
    log("Found %d edited sound(s) to write." % len(edits), "info")

    def _read_prog(c, t):
        if progress:
            progress(int(c * 10 / max(t, 1)), 100, "Reading image.bin")

    parts = _linux_partitions(original_path)
    work = tempfile.mkdtemp(prefix="spike2_")
    emu = None
    disk_f = open(original_path, "rb")
    try:
        gr_path, img_path, img_reader, _fw_node, img_node = _extract_inputs(
            disk_f, parts, work, log, _read_prog)
        if cancel():
            return 0
        if not audio_decode_supported(gr_path):
            raise RuntimeError(
                "Audio re-encode isn't supported for this title yet: its game "
                "firmware uses a Spike 2 codec the engine can't locate a single "
                "decode path for (e.g. a dual-path codec), so the per-sound "
                "keystream can't be derived.")
        log("Booting firmware codec engine...", "info")
        emu = Spike2Emu(gr_path, img_path)
        emu.boot()
        params = _load_or_derive_params(emu, gr_path, img_path, log, progress)
        byidx = {p["idx"]: p for p in params}

        # re-encode each edited sound into its body bytes
        patches = {}   # body_off -> bytes
        skipped = []
        gr = sr = None
        for n, (idx, wav_path) in enumerate(sorted(edits.items())):
            if cancel():
                return 0
            if idx not in byidx:
                log("idx %d not a known sound; skipping." % idx, "warning")
                continue
            p = byidx[idx]
            if progress:
                progress(10 + int(n * 80 / max(len(edits), 1)), 100,
                         "Re-encoding idx %d" % idx)
            if p["chan"] == 2:
                sr = sr or StereoRecover(emu)
            else:
                gr = gr or GenRecover(emu)
            # Verify the keystream recovery actually round-trips for THIS sound
            # before trusting its re-encode -- skip (never patch) sounds whose
            # codec variant the analytic encode can't yet reproduce bit-exact, so
            # Write can't silently corrupt them (see _recovery_valid).
            if not _recovery_valid(emu, gr, sr, p, np):
                skipped.append(idx)
                log("idx %d: re-encode isn't bit-exact for this sound's codec "
                    "(skipped -- left unchanged in the output)." % idx, "warning")
                continue
            if p["chan"] == 2:
                body = _encode_stereo(emu, sr, p, wav_path, np)
            else:
                body = _encode_mono(emu, gr, p, wav_path, np)
            patches[p["body_off"]] = body
            log("Re-encoded idx %d (%s, %d samples)."
                % (idx, "stereo" if p["chan"] == 2 else "mono", p["length"]), "info")
        if skipped:
            log("%d sound(s) skipped (re-encode unsupported for their codec): %s"
                % (len(skipped), ", ".join(map(str, skipped))), "warning")
        if not patches:
            raise RuntimeError(
                "None of the edited sounds could be re-encoded bit-exact for this "
                "title's codec yet, so nothing was written (the card image was not "
                "modified).")

        # copy the card image, then patch the changed bodies in place
        log("Copying card image to output...", "info")
        if progress:
            progress(0, 0, "Copying image...")
        shutil.copyfile(original_path, output_path)

        with open(output_path, "r+b") as out:
            for body_off, body in patches.items():
                for disk, n in img_reader.disk_ranges(img_node, body_off, len(body)):
                    out.seek(disk)
                    out.write(body[:n])
                    body = body[n:]
            out.flush()
            os.fsync(out.fileno())
        log("Wrote patched image: %s" % output_path, "success")
        return len(patches)
    finally:
        if disk_f is not None:
            disk_f.close()
        if emu is not None:
            emu.close()
        _rmtree(work)


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
        if stereo:
            body = bytearray(4 * p["length"])
            for k in range(nb):
                g0 = 200 * k
                seg = L0[g0:g0 + 200]
                if len(seg) == 0:
                    break
                rec = sr.recover_block(p, 200 + 200 * k, nf=len(seg)); m = rec["m"]
                frame, _ = sr.encode_block(L0[g0:g0 + m], R0[g0:g0 + m], rec)
                struct.pack_into("<%dH" % (2 * m), body, 4 * g0, *frame.tolist())
        else:
            body = bytearray(2 * p["length"])
            for k in range(nb):
                g0 = 200 * k
                seg = L0[g0:g0 + 200]
                if len(seg) == 0:
                    break
                K, rb = gr.recover_block(p, 200 + 200 * k, n=len(seg)); m = len(K)
                enc, _ = gr.encode_block(L0[g0:g0 + m], K, rb)
                struct.pack_into("<%dH" % m, body, 2 * g0, *enc.tolist())
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
        cmp_n = nb * 200
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
    body = bytearray(2 * length)
    for k in range((length + 199) // 200):
        g0 = 200 * k
        seg = tgt[g0:g0 + 200]
        if len(seg) == 0:
            break
        K, rb = gr.recover_block(p, 200 + 200 * k, n=len(seg))
        m = len(K)
        enc, _ = gr.encode_block(seg[:m], K, rb)
        struct.pack_into("<%dH" % m, body, 2 * g0, *enc.tolist())
    return bytes(body)


def _encode_stereo(emu, sr, p, wav_path, np):
    length = p["length"]
    a = _load_wav(wav_path, True, np)
    a = _amplitude_fit(a, _STEREO_RANGE, np)
    L = _fit(np.clip(a[:, 0], -_STEREO_RANGE, _STEREO_RANGE), length, np)
    R = _fit(np.clip(a[:, 1], -_STEREO_RANGE, _STEREO_RANGE), length, np)
    body = bytearray(4 * length)
    for k in range((length + 199) // 200):
        g0 = 200 * k
        segL = L[g0:g0 + 200]
        if len(segL) == 0:
            break
        rec = sr.recover_block(p, 200 + 200 * k, nf=len(segL))
        m = rec["m"]
        frame, _ = sr.encode_block(L[g0:g0 + m], R[g0:g0 + m], rec)
        struct.pack_into("<%dH" % (2 * m), body, 4 * g0, *frame.tolist())
    return bytes(body)


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
