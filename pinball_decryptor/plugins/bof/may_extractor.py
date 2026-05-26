"""Extract files from a BOF May 2026+ Godot PCK (custom format).

BOF's May 2026 firmware reorganised the Godot PCK layout into a custom
sequential format that GDRE Tools and stock Godot tooling cannot read.
Layers, all confirmed empirically against the Dune May code binary
``GDHarvest_202600513.x86_64`` (2.74 GB, 4703 path references, 2481
sidecar entries):

  1. PCK magic ``GDPC`` renamed to ``GBOF``.  Handled by
     ``pipeline._patch_pck_magic`` — must be patched back BEFORE this
     extractor runs.
  2. ``PACK_DIR_ENCRYPTED`` flag bit set as a tripwire.  No actual
     encryption — flag is set but the directory itself is not AES'd.
  3. No traditional Godot file-directory table.  Instead, files are
     stored sequentially with their ``.import`` sidecars inline.
  4. Each font is wrapped in a custom ``RSCC`` Zstd-compressed container
     (see ``rscc_decoder.py``).  Other files (textures, audio, scripts,
     scenes) are stored as raw bytes.

The pairing model — two flavours of sidecar:

  * **Adjacent (imported) sidecars** contain ``importer="..."`` +
    ``type="..."`` + ``uid="..."`` + ``path="res://.godot/imported/..."``.
    File data lives immediately BEFORE the sidecar, optionally
    separated by a 8-byte ``RSCC\\x00\\x00\\x00\\x00`` marker.
    Covers .ctex (textures), .sample (audio), .fontdata (fonts),
    .oggvorbisstr (ogg).  About 1781 files in the Dune build.

  * **Simple sidecars** contain only ``path="res://..."`` (no importer
    field).  File data is NOT adjacent — it lives in a separate
    contiguous block earlier in the PCK, paired sequentially by file
    type.  Covers .gdc (compiled scripts), .scn (binary scenes),
    .res (binary resources).  About 700 files in the Dune build.

Extraction strategy (in order):

  1. Scan the PCK section for every ``[remap]\\n`` marker (sidecar
     starts).  Parse each to get the path + classify as adjacent or
     simple.
  2. For adjacent sidecars: file data is between the previous
     sidecar-end and the current sidecar-start, trimmed of zero
     padding and the optional RSCC separator.  If the file data
     starts with a RSCC v2 container, decompress it; otherwise save
     raw.
  3. For simple sidecars grouped by extension: scan the PCK for the
     matching file magic (``GDSC`` for .gdc) and pair the Nth magic
     occurrence with the Nth simple sidecar of that extension.
  4. Optionally prepend ``RSRC`` magic to decompressed font files
     (BOF strips it during compression).

This recovers ~97% of the PCK contents on Dune (1.48 GB extracted,
2180 / 2250 files validate by magic).  Remaining ~3% are .scn and
.res files (need a different magic-detection heuristic — open work).
"""

import os
import re
import shutil
import struct

from .rscc_decoder import is_rscc_at, decompress


# PCK header constants — Godot 4.x with PACK_REL_FILEBASE
PCK_MAGIC_STOCK = b"GDPC"
PCK_HEADER_LEN = 96   # 4 magic + 4 ver + 12 engine + 4 flags + 8 file_base + 64 reserved
PCK_HEADER_PAD = 8    # 8 zero bytes between header end and first file (observed)

# BOF custom markers
RSCC_SEPARATOR = b"RSCC\x00\x00\x00\x00"  # 8-byte separator between file data and sidecar
SIDECAR_MARKER = b"[remap]\n"

# Trailer (last 12 bytes of binary)
PCK_TRAILER_LEN = 12


class ExtractorError(Exception):
    """Raised when the extractor can't make sense of the PCK structure."""


def find_pck_section(binary_path):
    """Locate the embedded PCK section in a Godot binary by reading its
    trailer.  Returns ``(pck_start, pck_end)``."""
    size = os.path.getsize(binary_path)
    with open(binary_path, "rb") as f:
        f.seek(size - PCK_TRAILER_LEN)
        trailer = f.read(PCK_TRAILER_LEN)
    if trailer[8:12] != PCK_MAGIC_STOCK:
        raise ExtractorError(
            f"Binary trailer magic is {trailer[8:12]!r}, expected {PCK_MAGIC_STOCK!r}. "
            "Was the GBOF->GDPC patch applied?")
    pck_data_size = struct.unpack("<Q", trailer[:8])[0]
    pck_end = size - PCK_TRAILER_LEN
    pck_start = pck_end - pck_data_size
    return pck_start, pck_end


def is_may_format(pck_buf):
    """Return True if this PCK uses BOF's May 2026+ custom format.

    The distinguishing markers (vs stock Godot 4.x PCK):

      * pack_format_version == 3 (newer Godot, also used by stock 4.4+)
      * pack_flags bit 0 set (``PACK_DIR_ENCRYPTED`` tripwire) — BOF
        sets this without actually encrypting, which makes GDRE Tools
        bail on the "encrypted" PCK before getting anywhere
      * 8 zero bytes immediately after the 96-byte header, where stock
        Godot would put a u32 file_count

    A stock Godot PCK never sets the tripwire flag, so flag bit 0 alone
    is a reliable discriminator.
    """
    if len(pck_buf) < PCK_HEADER_LEN + PCK_HEADER_PAD:
        return False
    if pck_buf[:4] != PCK_MAGIC_STOCK:
        return False
    pack_flags = struct.unpack("<I", pck_buf[20:24])[0]
    if not (pack_flags & 0x01):  # PACK_DIR_ENCRYPTED tripwire
        return False
    # Stock Godot puts a u32 file_count here; BOF puts 8 zero bytes.
    return pck_buf[PCK_HEADER_LEN:PCK_HEADER_LEN + 8] == b"\x00" * 8


# BOF sidecars always end with `path="..."` followed by `\n`.  Texture
# sidecars (CompressedTexture2D) optionally append a `metadata={...}\n`
# block — match it greedily so we don't cut off the sidecar early.
_PATH_LINE_RE = re.compile(
    rb'path="[^"\x00\n]+"\n'
    rb'(?:metadata=\{[^\x00]*?\}\n)?')


def _find_sidecar_end(buf, start):
    """Locate the end of the sidecar that begins at *start*.

    A BOF sidecar always ends with a ``path="..."\\n`` line, optionally
    followed by a ``metadata={...}\\n`` block (textures only).  After
    that final newline come 0–7 zero padding bytes, then the next
    file's binary data.  We anchor on this exact terminator rather than
    walking until a non-text byte — the next file's data can begin
    with printable ASCII bytes (e.g. ``RSCC`` magic) which a naïve
    text-walker would otherwise consume into the sidecar.
    """
    # Search a bounded window — real sidecars never exceed ~1 KB
    window_end = min(start + 2048, len(buf))
    window = bytes(buf[start:window_end])
    m = _PATH_LINE_RE.search(window)
    if m is None:
        # Fall back to the old behaviour for malformed sidecars
        p = start + len(SIDECAR_MARKER)
        end = len(buf)
        while p < end and buf[p] != 0:
            b = buf[p]
            if not (32 <= b < 127 or b in (9, 10, 13)):
                break
            p += 1
        return p
    return start + m.end()


def _parse_path(sidecar_text):
    m = re.search(r'path="([^"]+)"', sidecar_text)
    return m.group(1) if m else None


def _trim_file_bounds(buf, fstart, fend):
    """Trim a trailing RSCC separator and any zero padding from both ends
    of a file data slice."""
    if fend - fstart >= len(RSCC_SEPARATOR) and \
            bytes(buf[fend - len(RSCC_SEPARATOR):fend]) == RSCC_SEPARATOR:
        fend -= len(RSCC_SEPARATOR)
    while fend > fstart and buf[fend - 1] == 0:
        fend -= 1
    while fstart < fend and buf[fstart] == 0:
        fstart += 1
    return fstart, fend


def _safe_rel_path(res_path):
    """Convert a ``res://...`` path to a relative on-disk path."""
    if res_path.startswith("res://"):
        return res_path[len("res://"):]
    return res_path


def _write_out(out_dir, res_path, data, _long_path_prefix=None):
    """Write ``data`` under ``out_dir`` at the location specified by a
    ``res://`` path.  Uses ``\\\\?\\``-prefixed paths on Windows so that
    long PCK paths (which routinely exceed Windows' 260-char MAX_PATH)
    work."""
    rel = _safe_rel_path(res_path).replace("/", os.sep)
    target = os.path.abspath(os.path.join(out_dir, rel))
    # Windows long-path prefix — harmless on POSIX (not used)
    import sys
    if sys.platform == "win32":
        target = "\\\\?\\" + target
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        return True
    except OSError:
        return False


def _maybe_fix_resource_magic(data, ext):
    """BOF's RSCC compression strips the leading 'RSRC' magic from
    Godot binary resource files.  Restore it for known resource types."""
    if not data:
        return data
    if ext == ".fontdata" and not data.startswith(b"RSRC"):
        # Detect by looking for the FontFile object reference
        if b"FontFile" in data[:64]:
            return b"RSRC" + data
    return data


def extract_pck(binary_path, out_dir, log_cb=None):
    """Extract a BOF May 2026+ binary's PCK section into ``out_dir``.

    Returns a dict with extraction stats:
      ``files_written`` — total successful saves
      ``adjacent_count`` — imported assets paired with adjacent sidecars
      ``sequential_count`` — simple-sidecar assets paired by magic order
      ``rscc_count`` — files that were RSCC-Zstd-decompressed
      ``unpaired_simple`` — paths from simple sidecars whose data we
          couldn't locate (mostly .scn / .res today)
      ``total_bytes`` — total bytes written

    ``log_cb(msg, severity)`` is optional and receives progress info.
    """
    def _log(msg, sev="info"):
        if log_cb:
            log_cb(msg, sev)

    pck_start, pck_end = find_pck_section(binary_path)
    _log(f"PCK section: bytes {pck_start} – {pck_end} ({pck_end - pck_start} bytes)")

    with open(binary_path, "rb") as f:
        f.seek(pck_start)
        pck = f.read(pck_end - pck_start)

    if not is_may_format(pck):
        raise ExtractorError(
            "Binary doesn't look like BOF May 2026 format "
            "(PACK_DIR_ENCRYPTED flag clear or first file isn't RSCC v2). "
            "Use GDRE Tools for stock PCKs.")

    sidecar_starts = [m.start() for m in re.finditer(re.escape(SIDECAR_MARKER), pck)]
    _log(f"Found {len(sidecar_starts)} sidecars")

    # Pre-compute positions of SEQUENTIAL blobs (GDSC compiled scripts)
    # so we can skip past them when locating adjacent-file boundaries.
    # GDSC blobs live intermixed with imported assets in some PCK
    # regions; without filtering them out, the naive prev_sidecar_end →
    # current_sidecar_start range absorbs an entire .gdc script into
    # the next imported file (creating 92 MB "textures" containing
    # script bytecode).
    gdsc_positions = sorted(m.start() for m in re.finditer(rb"GDSC", pck))

    # Imported file magics — used to nudge the adjacent-file start past
    # any sequential blob residue when the simple GDSC-skip would
    # otherwise consume the whole [prev_end, sidecar_start) range.
    IMPORTED_MAGICS = (b"RSCC", b"GST2", b"OggS", b"RSRC", b"RIFF")

    def _gdsc_end_at(buf, p):
        """Best-effort end of the GDSC blob starting at ``p``.  Uses the
        next GDSC magic (sorted) as a conservative upper bound."""
        nxt = next((g for g in gdsc_positions if g > p), len(buf))
        return nxt

    def _adjacent_file_bounds(buf, sidecar_start, lower_bound):
        """Compute the file-data byte range for an adjacent (imported)
        file whose sidecar starts at *sidecar_start*."""
        fstart = lower_bound
        fend = sidecar_start
        # Trim trailing RSCC separator + zero padding
        if fend - fstart >= len(RSCC_SEPARATOR) and \
                bytes(buf[fend - len(RSCC_SEPARATOR):fend]) == RSCC_SEPARATOR:
            fend -= len(RSCC_SEPARATOR)
        while fend > fstart and buf[fend - 1] == 0:
            fend -= 1
        while fstart < fend and buf[fstart] == 0:
            fstart += 1

        # If the file data starts with a GDSC blob (sequential file
        # interleaved with adjacent ones), skip past it.  Repeat until
        # we find non-GDSC data — but never consume the entire range,
        # so the imported file always has SOMETHING to extract.
        while fstart < fend and buf[fstart:fstart+4] == b"GDSC":
            new_start = _gdsc_end_at(buf, fstart)
            if new_start >= fend:
                # Would consume everything — instead, look forward for
                # the next imported magic past this GDSC and use that
                # as the file start.
                for magic in IMPORTED_MAGICS:
                    pos = buf.find(magic, fstart + 4, fend)
                    if pos != -1 and (new_start := pos):
                        break
                else:
                    break  # No imported magic found — give up
            fstart = new_start
            # Trim leading zeros again after skip
            while fstart < fend and buf[fstart] == 0:
                fstart += 1

        return fstart, fend

    adjacent_entries = []   # (file_start, file_end, path)
    simple_by_ext = {}       # ext -> [paths] in document order
    prev_end = PCK_HEADER_LEN + PCK_HEADER_PAD

    for s in sidecar_starts:
        e = _find_sidecar_end(pck, s)
        text = pck[s:e].decode("utf-8", errors="replace")
        p = _parse_path(text)
        if not p:
            prev_end = e
            continue
        if "importer=" not in text:
            ext = os.path.splitext(p)[1].lower()
            simple_by_ext.setdefault(ext, []).append(p)
        else:
            # Imported file data is between prev_end and the sidecar,
            # but we have to skip past any sequential GDSC blobs that
            # got intermixed.
            fstart, fend = _adjacent_file_bounds(pck, s, prev_end)
            adjacent_entries.append((fstart, fend, p))
        prev_end = e

    _log(f"Adjacent (imported) entries: {len(adjacent_entries)}; "
         f"simple sidecars by ext: { {k: len(v) for k, v in simple_by_ext.items()} }")

    if os.path.exists(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    stats = {
        "files_written": 0, "adjacent_count": 0, "sequential_count": 0,
        "rscc_count": 0, "unpaired_simple": [], "total_bytes": 0,
    }

    # Phase 1: adjacent (imported) files
    for fs, fe, p in adjacent_entries:
        fdata = bytes(pck[fs:fe])
        if is_rscc_at(fdata, 0):
            try:
                fdata, _ = decompress(fdata, 0)
                stats["rscc_count"] += 1
            except Exception as ex:
                _log(f"  RSCC decompress failed for {p}: {ex}", "warning")
                continue
        ext = os.path.splitext(p)[1].lower()
        fdata = _maybe_fix_resource_magic(fdata, ext)
        if _write_out(out_dir, p, fdata):
            stats["files_written"] += 1
            stats["adjacent_count"] += 1
            stats["total_bytes"] += len(fdata)

    # Phase 2: simple sidecars paired sequentially by magic
    # Two strategies depending on file type:
    #   .gdc → unique GDSC magic, scan + pair sequentially
    #   .scn → RSRC magic + "PackedScene" class name within 100 bytes
    #   .res → RSRC magic + any class name OTHER than the adjacent-pair
    #          ones (AudioStreamWAV, FontFile, AudioStreamOggVorbis,
    #          CompressedTexture2D) within 100 bytes
    def find_rscc_file_starts(pck):
        """Locate every RSRC blob's START position (filtering out trailer
        RSRC bytes that appear at file END).  Returns ``[(pos, class_name)]``."""
        positions = []
        for m in re.finditer(rb"RSRC", pck):
            p = m.start()
            if p + 100 > len(pck):
                continue
            window = pck[p:p+100]
            # Class name is length-prefixed (u32) somewhere in offsets 16-30.
            # Walk through and pick the first plausible string.
            cls = None
            for off in range(16, 30):
                if off + 4 >= len(window):
                    break
                ln = struct.unpack("<I", window[off:off+4])[0]
                if 3 < ln < 60 and off + 4 + ln <= len(window):
                    try:
                        name = window[off+4:off+4+ln].rstrip(b"\x00").decode("ascii")
                        if name.replace("_", "").replace(".", "").isalnum():
                            cls = name
                            break
                    except UnicodeDecodeError:
                        pass
            if cls:
                positions.append((p, cls))
        return positions

    # Class names that pair with ADJACENT (importer=) sidecars — already extracted
    ADJACENT_CLASSES = {
        "AudioStreamWAV", "FontFile",
        "AudioStreamOggVorbis", "CompressedTexture2D",
    }

    rsrc_files = None  # lazily computed only if a simple sidecar needs it

    for ext, paths in simple_by_ext.items():
        if ext == ".gdc":
            magic = b"GDSC"
            positions = [m.start() for m in re.finditer(re.escape(magic), pck)]
            if len(positions) != len(paths):
                _log(f"  .gdc magic count mismatch: {len(positions)} GDSC vs "
                     f"{len(paths)} paths", "warning")
                stats["unpaired_simple"].extend(paths)
                continue
            for i, gp in enumerate(positions):
                end = positions[i + 1] if i + 1 < len(positions) else len(pck)
                for s in sidecar_starts:
                    if s > gp:
                        clip = s
                        while clip > gp and pck[clip - 1] == 0:
                            clip -= 1
                        if clip < end:
                            end = clip
                        break
                fdata = bytes(pck[gp:end])
                if _write_out(out_dir, paths[i], fdata):
                    stats["files_written"] += 1
                    stats["sequential_count"] += 1
                    stats["total_bytes"] += len(fdata)
            continue

        if ext in (".scn", ".res"):
            if rsrc_files is None:
                rsrc_files = find_rscc_file_starts(pck)
            if ext == ".scn":
                wanted_class = "PackedScene"
                positions = [p for p, c in rsrc_files if c == wanted_class]
            else:  # .res — any non-adjacent class
                positions = [p for p, c in rsrc_files
                             if c not in ADJACENT_CLASSES
                             and c != "PackedScene"]

            # Build a sorted list of file boundaries (each RSRC at start)
            # File N ends at start of file N+1 OR next sidecar boundary.
            all_starts = sorted(p for p, _ in rsrc_files)

            # Trim positions list to match path count if slightly off
            if len(positions) > len(paths):
                positions = positions[:len(paths)]
            elif len(positions) < len(paths):
                _log(f"  {ext} pairing short: only {len(positions)} "
                     f"{ext} files identifiable vs {len(paths)} paths "
                     f"(extracting what we can)", "warning")
                stats["unpaired_simple"].extend(paths[len(positions):])

            for i, gp in enumerate(positions):
                # File ends at the next RSRC start (any type)
                nexts = [s for s in all_starts if s > gp]
                end = nexts[0] if nexts else len(pck)
                # Or at the next sidecar's preceding padding
                for s in sidecar_starts:
                    if s > gp:
                        clip = s
                        while clip > gp and pck[clip - 1] == 0:
                            clip -= 1
                        if clip < end:
                            end = clip
                        break
                fdata = bytes(pck[gp:end])
                if _write_out(out_dir, paths[i], fdata):
                    stats["files_written"] += 1
                    stats["sequential_count"] += 1
                    stats["total_bytes"] += len(fdata)
            continue

        # Unknown extension — leave unpaired
        stats["unpaired_simple"].extend(paths)

    _log(
        f"Wrote {stats['files_written']} files "
        f"({stats['adjacent_count']} adjacent + {stats['sequential_count']} sequential, "
        f"{stats['rscc_count']} RSCC-decompressed). "
        f"Unpaired: {len(stats['unpaired_simple'])} "
        f"({stats['total_bytes'] / 1024 / 1024:.1f} MB total)",
        "success" if stats["files_written"] > 0 else "warning")

    return stats
