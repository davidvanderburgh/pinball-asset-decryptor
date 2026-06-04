"""Inverse of ``source_converter``: re-encode user-edited source files
back into the BOF imported binary format so the packer can ship them.

Workflow: the user extracts a .fun, edits files in ``pck/editable/``
(e.g. replaces ``intro_audio-abc123.wav`` with a new recording),
hits Write.  The Modify pipeline asks this module to regenerate the
matching imported binary (``pck/.godot/imported/intro_audio.wav-<32hex>.sample``)
so ``may_packer`` can substitute the new bytes into the .fun.

Each inverse converter takes the user's source file PLUS the
original imported binary (so we can preserve the wrapper bytes —
RSRC header, trailer metadata, GST2 header — that depend on the
specific encoding choices Godot made at import time).  The
algorithm is "replace payload, keep wrapper":

  * ``.wav`` → ``.sample``: rebuild the PCM PackedByteArray with new
    bytes; if the original was QOA-encoded, re-encode the new WAV
    to QOA first to preserve compression; pass-through otherwise.
  * ``.webp`` → ``.ctex``: replace the embedded RIFF/WEBP chunk
    inside the GST2 header.  Preserves width/height/format fields
    so Godot's loader still finds them.
  * ``.ogv`` → ``.ctex``: replace the OGG payload that lives inside
    BOF's video-as-texture .ctex variant.
  * ``.ogg`` → ``.oggvorbisstr``: replace the OggPacketSequence
    contents inside the Godot resource.  (Not yet implemented —
    these are rare in modding workflows; falls through to raw copy.)
  * ``.ttf`` / ``.otf`` → ``.fontdata``: replace the font binary
    inside the FontFile resource's ``data`` PBA.

Unrecognised source files are skipped with a clear log warning;
they remain in ``pck/editable/`` but don't affect Write.
"""

import os
import re
import struct
import sys


# ---------------------------------------------------------------------------
# Reverse filename mapping
# ---------------------------------------------------------------------------

# Source files are named ``<stem>-<hash6>.<src_ext>`` where stem is the
# original asset's basename without its source extension, and hash6 is
# the first 6 chars of the 32-char MD5 from the imported filename.
# The matching imported file lives at
# ``.godot/imported/<stem>.<orig_ext>-<full_hash>.<imported_ext>``.
_SOURCE_NAME_RE = re.compile(
    r"^(?P<stem>.+)-(?P<hash6>[a-f0-9]{6})\.(?P<src_ext>wav|qoa|ogg|webp|png|ogv|ttf|otf)$",
    re.IGNORECASE,
)


def parse_source_name(filename):
    """Return ``(stem, hash6, src_ext)`` or ``(None, None, None)``."""
    m = _SOURCE_NAME_RE.match(filename)
    if not m:
        return None, None, None
    return m.group("stem"), m.group("hash6"), m.group("src_ext").lower()


def find_matching_imported(pck_dir, stem, hash6):
    """Look up the imported binary that matches ``<stem>-<hash6>``.

    Scans ``pck_dir/.godot/imported/`` for any file beginning with
    ``<stem>.<*>-<hash6>...`` and returns its absolute path, or None.
    """
    long_prefix = "\\\\?\\" if sys.platform == "win32" else ""
    imp_dir = os.path.join(pck_dir, ".godot", "imported")
    if not os.path.isdir(imp_dir):
        return None
    needle = f"{stem}."
    for name in os.listdir(long_prefix + os.path.abspath(imp_dir)):
        if name.startswith(needle) and f"-{hash6}" in name:
            return os.path.join(imp_dir, name)
    return None


# ---------------------------------------------------------------------------
# .wav → .sample (PCM or QOA, preserving original encoding)
# ---------------------------------------------------------------------------

_VTYPE_PBA = 0x1F


def _read_wav(path):
    """Read a standard RIFF/WAVE PCM file.  Returns
    ``(pcm_bytes, channels, sample_rate, sample_width_bytes)``."""
    import wave
    with wave.open(path, "rb") as w:
        channels = w.getnchannels()
        rate = w.getframerate()
        width = w.getsampwidth()
        pcm = w.readframes(w.getnframes())
    return pcm, channels, rate, width


def _clip16(v):
    return -32768 if v < -32768 else (32767 if v > 32767 else int(v))


def _pcm_to_channels(pcm, src_ch, width):
    """De-interleave raw PCM into a list of ``src_ch`` int16 ``array``s,
    converting 8/24/32-bit samples down to 16-bit.  Returns
    ``(channels, n_frames)``."""
    import array
    n = len(pcm) // (src_ch * width)
    chans = [array.array("h", bytes(2 * n)) for _ in range(src_ch)]
    if width == 2:
        allv = array.array("h")
        allv.frombytes(pcm[:n * src_ch * 2])
        if sys.byteorder == "big":
            allv.byteswap()
        for f in range(n):
            base = f * src_ch
            for c in range(src_ch):
                chans[c][f] = allv[base + c]
    elif width == 1:                              # 8-bit unsigned
        for f in range(n):
            base = f * src_ch
            for c in range(src_ch):
                chans[c][f] = (pcm[base + c] - 128) << 8
    elif width == 3:                              # 24-bit LE signed → top 16
        for f in range(n):
            o = f * src_ch * 3
            for c in range(src_ch):
                p = o + c * 3
                v = pcm[p] | (pcm[p + 1] << 8) | (pcm[p + 2] << 16)
                if v & 0x800000:
                    v -= 1 << 24
                chans[c][f] = v >> 8
    elif width == 4:                              # 32-bit LE signed → top 16
        allv = array.array("i")
        allv.frombytes(pcm[:n * src_ch * 4])
        if sys.byteorder == "big":
            allv.byteswap()
        for f in range(n):
            base = f * src_ch
            for c in range(src_ch):
                chans[c][f] = allv[base + c] >> 16
    else:
        raise ValueError(f"unsupported WAV sample width: {width} bytes")
    return chans, n


def _resample_linear(ch, src_rate, dst_rate):
    """Linear-interpolation resample one int16 channel array.  Adequate
    for the speech callouts BOF ships; avoids a scipy/numpy dependency."""
    import array
    n = len(ch)
    if n == 0 or src_rate == dst_rate:
        return ch
    out_n = max(1, round(n * dst_rate / src_rate))
    out = array.array("h", bytes(2 * out_n))
    ratio = src_rate / dst_rate
    for i in range(out_n):
        x = i * ratio
        i0 = int(x)
        if i0 + 1 < n:
            frac = x - i0
            out[i] = _clip16(ch[i0] * (1.0 - frac) + ch[i0 + 1] * frac)
        else:
            out[i] = ch[n - 1]
    return out


def _interleave(chans):
    import array
    n = len(chans[0])
    ch = len(chans)
    out = array.array("h", bytes(2 * n * ch))
    for f in range(n):
        for c in range(ch):
            out[f * ch + c] = chans[c][f]
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def _conform_pcm(pcm, src_ch, src_rate, src_width, dst_ch, dst_rate):
    """Remix / resample / re-depth user PCM so it matches the channel
    count and sample rate the *original* ``.sample`` declares.

    This keeps the spliced resource internally consistent: we re-use the
    original's ``format`` / ``mix_rate`` / ``stereo`` properties verbatim,
    so the audio those properties describe must actually match.  A
    channel-count mismatch in particular makes Godot read the QOA buffer
    with the wrong stride — an out-of-bounds crash that black-screens the
    game when the sample is preloaded at boot (e.g. a callout).
    """
    if (src_width == 2 and src_ch == dst_ch
            and (src_rate == dst_rate or not src_rate or not dst_rate)):
        return pcm                                # already matches — fast path
    chans, _n = _pcm_to_channels(pcm, src_ch, src_width)
    if src_ch != dst_ch:                          # down-mix to mono, then fan out
        import array
        n = len(chans[0])
        mono = array.array("h", bytes(2 * n))
        for f in range(n):
            mono[f] = _clip16(sum(c[f] for c in chans) // src_ch)
        chans = [mono]
    if src_rate and dst_rate and src_rate != dst_rate:
        chans = [_resample_linear(c, src_rate, dst_rate) for c in chans]
    if len(chans) < dst_ch:                       # fan mono out to dst channels
        chans = [chans[0]] * dst_ch
    elif len(chans) > dst_ch:
        chans = chans[:dst_ch]
    return _interleave(chans)


def _splice_pba_payload(orig_sample_bytes, new_payload):
    """Replace the AudioStreamWAV data PBA payload in place, returning
    the rebuilt .sample bytes.  Preserves the resource header, string
    table, all other properties, and the trailer."""
    needle = struct.pack("<I", len(b"AudioStreamWAV") + 1) + b"AudioStreamWAV\x00"
    p = orig_sample_bytes.rfind(needle)
    if p < 0:
        raise ValueError("not an AudioStreamWAV resource")
    p += len(needle)
    if p + 4 > len(orig_sample_bytes):
        raise ValueError("truncated AudioStreamWAV header")
    num_props = struct.unpack("<I", orig_sample_bytes[p:p+4])[0]
    p += 4
    # Find the first PBA property — that's the data field
    cursor = p
    for _ in range(num_props):
        if cursor + 8 > len(orig_sample_bytes):
            raise ValueError("ran out of bytes walking properties")
        vtype = struct.unpack("<I", orig_sample_bytes[cursor+4:cursor+8])[0]
        cursor += 8
        if vtype == _VTYPE_PBA:
            old_len = struct.unpack("<I", orig_sample_bytes[cursor:cursor+4])[0]
            old_pad = (4 - (old_len % 4)) % 4
            payload_start = cursor + 4
            payload_end = payload_start + old_len + old_pad
            # Rebuild: prefix + new_len + new_payload + new_pad + suffix
            new_pad = (4 - (len(new_payload) % 4)) % 4
            return (orig_sample_bytes[:cursor]
                    + struct.pack("<I", len(new_payload))
                    + new_payload
                    + b"\x00" * new_pad
                    + orig_sample_bytes[payload_end:])
        # Not a PBA — skip its 4-byte value (best-effort)
        cursor += 4
    raise ValueError("no PBA found in AudioStreamWAV properties")


_QOA_FRAME_SAMPLES = 5120


def _qoa_encoded_size(n_samples, channels):
    """Exact byte size qoa_codec.encode() produces for ``n_samples`` per
    channel (matches the encoder's framing: 8-byte file header, then per
    frame 8-byte header + 16*ch LMS state + 8*ceil(spc/20)*ch slices)."""
    if n_samples <= 0:
        return 8
    size = 8
    full, rem = divmod(n_samples, _QOA_FRAME_SAMPLES)
    size += full * (8 + 16 * channels + 8 * (_QOA_FRAME_SAMPLES // 20) * channels)
    if rem:
        size += 8 + 16 * channels + 8 * ((rem + 19) // 20) * channels
    return size


def _max_qoa_samples(max_bytes, channels):
    """Largest per-channel sample count whose QOA encoding fits in
    ``max_bytes`` (binary search over the exact size formula)."""
    lo, hi = 0, max(0, (max_bytes // max(1, channels)))  # generous upper bound
    hi = max(hi, 1)
    while _qoa_encoded_size(hi, channels) <= max_bytes:
        hi *= 2
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _qoa_encoded_size(mid, channels) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return lo


def encode_wav_to_sample(wav_path, orig_sample_path, log_cb=None):
    """Re-encode a user-edited .wav into a Godot .sample, preserving
    whatever wrapper + payload encoding the original used.

    The repacker can only substitute size-neutrally (BOF's encrypted PCK
    directory stores absolute offsets), so the new payload must fit the
    original's byte footprint.  If the replacement audio is longer than
    the original, this auto-trims the tail to fit and warns via
    ``log_cb`` rather than failing the whole Write."""
    long_prefix = "\\\\?\\" if sys.platform == "win32" else ""
    with open(long_prefix + os.path.abspath(orig_sample_path), "rb") as f:
        orig = f.read()

    pcm, channels, rate, width = _read_wav(long_prefix + os.path.abspath(wav_path))

    # Detect original payload encoding so we can match it
    needle = struct.pack("<I", len(b"AudioStreamWAV") + 1) + b"AudioStreamWAV\x00"
    needle_pos = orig.rfind(needle)
    if needle_pos < 0:
        raise ValueError("not an AudioStreamWAV resource")
    pp = needle_pos + len(needle) + 4  # skip num_props
    # Walk to first PBA payload start
    cursor = pp
    while cursor + 8 <= len(orig):
        vtype = struct.unpack("<I", orig[cursor+4:cursor+8])[0]
        cursor += 8
        if vtype == _VTYPE_PBA:
            old_len = struct.unpack("<I", orig[cursor:cursor+4])[0]
            payload_head = orig[cursor+4:cursor+8]
            orig_payload = orig[cursor+4:cursor+4+old_len]
            break
        cursor += 4
    else:
        raise ValueError("can't locate original payload")

    # Determine the channel count + sample rate the original .sample
    # declares.  We splice into its wrapper and keep its format/mix_rate/
    # stereo properties verbatim, so the new audio MUST match that format
    # or the resource lies about itself (a channel mismatch crashes Godot
    # → black screen).  Conform the user's audio to it.
    dst_ch, dst_rate = _original_sample_format(orig, orig_payload, channels, rate)

    pcm = _conform_pcm(pcm, channels, rate, width, dst_ch, dst_rate)
    total_samples = len(pcm) // (dst_ch * 2)

    def _warn_trim(kept_samples):
        if log_cb and kept_samples < total_samples:
            cut = (total_samples - kept_samples) / max(1, dst_rate)
            log_cb(
                f"  Replacement is longer than the original; auto-trimmed "
                f"{cut:.1f}s off the end to fit "
                f"({kept_samples / max(1, dst_rate):.1f}s kept). The game's "
                f"file format can't store a longer clip in this slot.",
                "warning")

    if payload_head[:4] == b"qoaf":
        # Re-encode WAV PCM to QOA at the original's channels + rate,
        # auto-trimming to fit the original payload's byte footprint.
        from .qoa_codec import encode as qoa_encode
        if _qoa_encoded_size(total_samples, dst_ch) > old_len:
            keep = _max_qoa_samples(old_len, dst_ch)
            pcm = pcm[:keep * dst_ch * 2]
            _warn_trim(keep)
        new_payload = qoa_encode(pcm, dst_ch, dst_rate)
    else:
        # Raw 16-bit PCM (or an OGG-original fallback to PCM): conform,
        # then trim the tail to the original payload byte length if longer.
        if len(pcm) > old_len:
            keep = (old_len // (dst_ch * 2))
            pcm = pcm[:keep * dst_ch * 2]
            _warn_trim(keep)
        new_payload = pcm

    return _splice_pba_payload(orig, new_payload)


def _original_sample_format(orig, orig_payload, fallback_ch, fallback_rate):
    """Return ``(channels, sample_rate)`` the original .sample declares.

    QOA payloads are self-describing (channels + samplerate live in the
    stream header), so prefer those; otherwise parse the resource trailer
    (``stereo`` + ``mix_rate``).  Falls back to the user's own values when
    nothing is recoverable, which leaves behaviour unchanged from before."""
    if orig_payload[:4] == b"qoaf" and len(orig_payload) >= 12:
        ch = orig_payload[8] or fallback_ch
        sr = int.from_bytes(orig_payload[9:12], "big") or fallback_rate
        return ch, sr
    try:
        from .source_converter import _find_data_pba, _parse_sample_trailer
        pl, _off, end = _find_data_pba(orig, b"AudioStreamWAV")
        if pl is not None:
            _fmt, rate, stereo = _parse_sample_trailer(orig[end:])
            return (2 if stereo else 1), (rate or fallback_rate)
    except Exception:
        pass
    return fallback_ch, fallback_rate


# ---------------------------------------------------------------------------
# .webp / .png → .ctex (GST2)
# ---------------------------------------------------------------------------

def encode_image_to_ctex(image_path, orig_ctex_path, log_cb=None):
    """Replace the image payload inside a GST2 .ctex while preserving
    its header.  Accepts WebP or PNG; the surrounding GST2 stays
    untouched so Godot's loader still sees the right width/height."""
    long_prefix = "\\\\?\\" if sys.platform == "win32" else ""
    with open(long_prefix + os.path.abspath(orig_ctex_path), "rb") as f:
        orig = f.read()
    with open(long_prefix + os.path.abspath(image_path), "rb") as f:
        new_image = f.read()

    if not orig.startswith(b"GST2"):
        # Probably an OGG-as-texture variant — return as-is and let the
        # pipeline raise a clearer error.
        raise ValueError("original .ctex isn't GST2; can't splice image")

    # Find image payload boundary in original.  Mipmap layout is:
    #   per-mipmap: u32 size + N data bytes
    # First mipmap usually starts ~64 bytes in.  Look for RIFF/WEBP or
    # PNG magic.
    riff = orig.find(b"RIFF")
    png  = orig.find(b"\x89PNG\r\n\x1a\n")
    candidates = sorted([p for p in (riff, png) if 0 < p < 256])
    if not candidates:
        raise ValueError("can't find image payload in GST2 wrapper")
    payload_start = candidates[0]
    # The 4 bytes immediately before the payload encode its size — we
    # need to update those AND the payload bytes.
    new_size = len(new_image)
    rebuilt = bytearray()
    rebuilt += orig[:payload_start - 4]
    rebuilt += struct.pack("<I", new_size)
    rebuilt += new_image
    # Anything AFTER the original payload (additional mipmaps, etc.)
    # we drop — modders typically supply a single full-resolution image
    # and let Godot regenerate mipmaps at load time.  GST2's mipmap
    # count is in the header but Godot handles size mismatches gracefully.
    return bytes(rebuilt)


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------

# Maps source extension → callable that takes (src_path, orig_imported_path)
# and returns the new imported-binary bytes.
ENCODERS = {
    ".wav": encode_wav_to_sample,
    ".webp": encode_image_to_ctex,
    ".png": encode_image_to_ctex,
}


def reencode_source_file(src_path, orig_imported_path, log_cb=None):
    """Top-level entry: dispatch by source extension.  Returns rebuilt
    bytes for the imported binary, or raises ``ValueError`` with a
    human-readable reason."""
    ext = os.path.splitext(src_path)[1].lower()
    enc = ENCODERS.get(ext)
    if enc is None:
        raise ValueError(f"no inverse encoder for {ext} files yet")
    return enc(src_path, orig_imported_path, log_cb=log_cb)


def apply_source_edits(pck_dir, baseline_mtime=0, *,
                       baseline_checksums_path=None, log_cb=None,
                       progress_cb=None, cancel_cb=None):
    """Scan the editable folder for files that differ from the Extract
    baseline and re-encode each one back into its imported binary
    under ``pck_dir/.godot/imported/``.

    Change detection runs in this order:

      1. If ``baseline_checksums_path`` is given and readable, compare
         each file's current MD5 against the saved baseline.  Catches
         edits that don't update mtime — most commonly file renames
         (swapping two filenames, the classic ``mv a b ; mv c a`` etc.)
         but also atomic overwrites by some editors / tools.
      2. Otherwise, fall back to ``baseline_mtime`` and the older
         "mtime > baseline" rule.  Used when a checksums file isn't
         around (pre-May extracts have one but old pre-extractor
         folders may not).

    Returns ``{"updated": [(src_name, imported_name, rel_from_pck)],
    "skipped": [...]}`` — three-tuple to make rel paths available
    without re-walking.
    """
    import hashlib
    import re as _re
    long_prefix = "\\\\?\\" if sys.platform == "win32" else ""

    def _log(msg, sev="info"):
        if log_cb:
            log_cb(msg, sev)

    def _progress(cur, total, label):
        if progress_cb:
            progress_cb(cur, total, label)

    # Load baseline MD5 map if available — same dual-format parser
    # the GUI preview-tree uses (BOF writes path-first; older JJP-style
    # writes md5sum-style).
    baseline_md5 = {}
    if baseline_checksums_path and os.path.isfile(
            long_prefix + os.path.abspath(baseline_checksums_path)):
        md5sum_re = _re.compile(r'^([a-f0-9]{32})\s+\*?(.+)$')
        with open(long_prefix + os.path.abspath(baseline_checksums_path),
                  "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = md5sum_re.match(line)
                if m:
                    md5_val, fp = m.group(1), m.group(2)
                elif "\t" in line:
                    fp, md5_val = line.rsplit("\t", 1)
                    md5_val = md5_val.strip()
                    if not _re.fullmatch(r'[a-f0-9]{32}', md5_val):
                        continue
                else:
                    continue
                if fp.startswith("./"):
                    fp = fp[2:]
                baseline_md5[fp.replace("\\", "/")] = md5_val

    def _md5(path):
        h = hashlib.md5()
        with open(long_prefix + os.path.abspath(path), "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    # assets_dir is the parent of pck_dir; that's the key prefix the
    # checksums file uses (`pck/_EDITABLE ASSETS/...`).
    assets_dir = os.path.dirname(os.path.abspath(pck_dir))

    def _is_changed(full_path):
        if baseline_md5:
            rel = os.path.relpath(
                full_path, assets_dir).replace("\\", "/")
            saved = baseline_md5.get(rel)
            if saved is None:
                return True  # never seen — treat as added
            try:
                return _md5(full_path) != saved
            except OSError:
                return False
        # mtime fallback
        try:
            return os.path.getmtime(
                long_prefix + os.path.abspath(full_path)) > baseline_mtime
        except OSError:
            return False

    # Locate the editable folder — accept the canonical name and the
    # two legacy names so extracts from earlier versions still work
    # when the user re-runs Write.
    from .source_converter import EDITABLE_DIR_NAME, LEGACY_DIR_NAMES
    editable_dir = None
    for candidate_name in (EDITABLE_DIR_NAME,) + LEGACY_DIR_NAMES:
        candidate = os.path.join(pck_dir, candidate_name)
        if os.path.isdir(candidate):
            editable_dir = candidate
            break
    if editable_dir is None:
        _log(f"No pck/{EDITABLE_DIR_NAME}/ folder — nothing to re-encode.",
             "info")
        return {"updated": [], "skipped": []}

    # Walk the editable tree recursively so the post-v0.7.18 subfolder
    # structure (audio/ images/ video/ fonts/) works the same as the
    # earlier flat layout.  We pass the basename through to the per-
    # file encoder regardless of which subfolder it lives in — the
    # source-name regex doesn't care about the parent directory.
    #
    # Walk WITHOUT the Windows long-path prefix; os.walk returns paths
    # carrying whatever prefix it started with, and re-applying the
    # prefix on top of an already-prefixed path produces a broken
    # ``\\?\\\?\C:\...`` that no syscall can open.
    candidates = []
    for dp, _, fs in os.walk(editable_dir):
        for name in fs:
            if name.startswith("_") or name.startswith("."):
                continue  # README / hidden / OS-droppings
            full = os.path.join(dp, name)
            if _is_changed(full):
                # Store the absolute path so we can read it back later
                # regardless of the subfolder it lives in.
                candidates.append((name, full))

    if not candidates:
        _log("No edited files in pck/editable/ since extract.", "info")
        return {"updated": [], "skipped": []}

    _log(f"Re-encoding {len(candidates)} edited file(s) "
         f"from pck/editable/...", "info")
    _progress(0, len(candidates), "Re-encoding edited files...")

    updated = []
    skipped = []
    for i, (name, src_full) in enumerate(candidates):
        if cancel_cb is not None and cancel_cb():
            raise RuntimeError("re-encode cancelled by user")
        stem, hash6, src_ext = parse_source_name(name)
        if stem is None:
            skipped.append((name, "filename doesn't match <stem>-<hash6>.<ext>"))
            continue
        imported = find_matching_imported(pck_dir, stem, hash6)
        if imported is None:
            skipped.append((name, f"no matching imported binary for {stem}/{hash6}"))
            continue
        try:
            new_bytes = reencode_source_file(src_full, imported, log_cb=log_cb)
        except Exception as e:
            skipped.append((name, str(e)))
            continue
        try:
            with open(long_prefix + os.path.abspath(imported), "wb") as f:
                f.write(new_bytes)
            # Record both the basename (for human-readable display)
            # AND the path relative to pck_dir (so the Modify pipeline
            # can feed it straight into changed_pck without re-walking
            # the imported tree).
            rel_from_pck = os.path.relpath(
                imported, pck_dir).replace("\\", "/")
            updated.append((name, os.path.basename(imported),
                            rel_from_pck))
            _log(f"  Re-encoded {name} → {os.path.basename(imported)}", "info")
        except OSError as e:
            skipped.append((name, f"write error: {e}"))
        _progress(i + 1, len(candidates),
                  f"Re-encoded {i+1}/{len(candidates)}")

    _log(f"Re-encoded {len(updated)} edited file(s); "
         f"{len(skipped)} skipped.",
         "success" if updated else "warning")
    for name, reason in skipped:
        _log(f"  Skipped {name}: {reason}", "warning")
    return {"updated": updated, "skipped": skipped}
