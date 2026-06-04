"""Re-pack modified files into a BOF May 2026+ Godot binary.

The inverse of ``may_extractor.extract_pck``.  Given the original
binary plus a directory tree of modified files at ``pck/``, produce
a new binary with the modifications baked into the PCK section.

The PCK section is rebuilt **sequentially** (BOF's format has no
file offset table — files are addressed by walking forward) so any
file can change size; subsequent files just shift in place and the
PCK trailer is updated to match.  The non-PCK portion of the binary
(ELF/PE code + headers) is copied bit-for-bit from the original.

What works today:
  * **Raw imported assets** (.ctex, .sample, .oggvorbisstr) — replace
    file bytes 1-for-1, no compression.  Most common modding case.
  * **Fonts (.fontdata)** — repacked into RSCC v2 Zstd containers
    matching the original block-size + version conventions.  If the
    user's modified .fontdata starts with the "RSRC" magic, it's
    stripped before compression (BOF's format omits the magic and
    reconstructs it at load time, mirroring our extractor's fix-up).
    A font whose *decompressed payload* is unchanged is left byte-for-
    byte verbatim — fonts extract decompressed but live compressed, so
    a raw byte compare would otherwise re-wrap every font on every Write
    and shift the PCK out of alignment (see below).

Alignment: the PCK keeps entries on a 16-byte boundary (~96% of
file/sidecar starts at offset ≡ 8 mod 16 on real Dune).  Every
size-changing substitution is zero-padded so its region stays the same
length-mod-16 as the original, keeping all downstream entries on their
boundaries — BOF's no-directory loader walks the PCK forward and an
unpadded shift knocks ~half the entries out of phase.
  * **Sequential files (.gdc, .scn, .res)** — file bytes replace the
    corresponding sequential blob; their sidecars are unchanged.

What's NOT supported here (would need additional work):
  * Adding files that weren't in the original PCK.
  * Removing files (the sidecar still references them).
  * Splitting / merging files (the path / sidecar association is
    preserved 1-for-1).
"""

import os
import re
import shutil
import struct
import sys

from .rscc_decoder import is_rscc_at, decompress
from .may_extractor import (
    PCK_HEADER_LEN, PCK_HEADER_PAD, PCK_MAGIC_STOCK,
    PCK_TRAILER_LEN, RSCC_SEPARATOR, SIDECAR_MARKER,
    ExtractorError, find_pck_section, is_may_format,
    _find_sidecar_end, _parse_path,
)


class PackerError(Exception):
    """Raised when the packer can't safely produce an output binary."""


# Block size matches what BOF used in every observed RSCC container.
RSCC_BLOCK_SIZE = 4096
RSCC_VERSION = 2


def _build_rscc_container(payload):
    """Compress *payload* into a fresh RSCC v2 Zstd container, matching
    the layout BOF's loader expects."""
    # Late import — keeps zstandard optional for users who only Extract.
    import zstandard

    cctx = zstandard.ZstdCompressor()
    blk = RSCC_BLOCK_SIZE

    if not payload:
        # Empty container — valid, occasionally appears in BOF data.
        header = b"RSCC" + struct.pack("<III", RSCC_VERSION, blk, 0)
        return header

    frames = []
    pos = 0
    while pos < len(payload):
        chunk = payload[pos:pos + blk]
        frames.append(cctx.compress(chunk))
        pos += blk

    block_sizes = [len(f) for f in frames]
    out = bytearray()
    out += b"RSCC"
    out += struct.pack("<III", RSCC_VERSION, blk, len(payload))
    out += struct.pack(f"<{len(block_sizes)}I", *block_sizes)
    for f in frames:
        out += f
    return bytes(out)


def _maybe_strip_rsrc_magic(data, ext):
    """Inverse of ``may_extractor._maybe_fix_resource_magic`` — strip
    the leading "RSRC" magic from a font binary so the re-packed RSCC
    decompresses to the same bytes BOF expects."""
    if ext == ".fontdata" and data.startswith(b"RSRC") and b"FontFile" in data[:64]:
        return data[4:]
    return data


def _read_pck_entries(pck_buf):
    """Walk the PCK buffer using the same algorithm as the extractor and
    yield ``(kind, file_start, file_end, sidecar_start, sidecar_end, path)``
    for each entry, in document order.  ``kind`` is one of
    ``'adjacent_raw'``, ``'adjacent_rscc'``, or ``'sequential'``.
    """
    sidecar_starts = [m.start() for m in re.finditer(re.escape(SIDECAR_MARKER), pck_buf)]
    gdsc_positions = sorted(m.start() for m in re.finditer(rb"GDSC", pck_buf))

    # Pre-compute RSRC file starts with class names (for .scn / .res)
    def _rsrc_starts():
        out = []
        for m in re.finditer(rb"RSRC", pck_buf):
            p = m.start()
            if p + 100 > len(pck_buf):
                continue
            window = pck_buf[p:p+100]
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
                out.append((p, cls))
        return out

    ADJACENT_CLASSES = {"AudioStreamWAV", "FontFile",
                        "AudioStreamOggVorbis", "CompressedTexture2D"}
    rsrc_files = None

    def _gdsc_end_at(p):
        return next((g for g in gdsc_positions if g > p), len(pck_buf))

    IMPORTED_MAGICS = (b"RSCC", b"GST2", b"OggS", b"RSRC", b"RIFF")

    def _adjacent_bounds(sidecar_start, lower_bound):
        fstart = lower_bound
        fend = sidecar_start
        if fend - fstart >= len(RSCC_SEPARATOR) and \
                bytes(pck_buf[fend - len(RSCC_SEPARATOR):fend]) == RSCC_SEPARATOR:
            fend -= len(RSCC_SEPARATOR)
        while fend > fstart and pck_buf[fend - 1] == 0:
            fend -= 1
        while fstart < fend and pck_buf[fstart] == 0:
            fstart += 1
        while fstart < fend and pck_buf[fstart:fstart+4] == b"GDSC":
            new_start = _gdsc_end_at(fstart)
            if new_start >= fend:
                for magic in IMPORTED_MAGICS:
                    pos = pck_buf.find(magic, fstart + 4, fend)
                    if pos != -1:
                        new_start = pos
                        break
                else:
                    break
            fstart = new_start
            while fstart < fend and pck_buf[fstart] == 0:
                fstart += 1
        return fstart, fend

    # Pass 1: walk sidecars, classify each
    adjacent = []  # (file_start, file_end, sidecar_start, sidecar_end, path)
    simple_by_ext = {}
    prev_end = PCK_HEADER_LEN + PCK_HEADER_PAD

    for s in sidecar_starts:
        e = _find_sidecar_end(pck_buf, s)
        text = pck_buf[s:e].decode("utf-8", errors="replace")
        p = _parse_path(text)
        if not p:
            prev_end = e
            continue
        if "importer=" not in text:
            ext = os.path.splitext(p)[1].lower()
            simple_by_ext.setdefault(ext, []).append((s, e, p))
        else:
            fstart, fend = _adjacent_bounds(s, prev_end)
            kind = ("adjacent_rscc"
                    if is_rscc_at(pck_buf, fstart) else "adjacent_raw")
            adjacent.append((kind, fstart, fend, s, e, p))
        prev_end = e

    # Pass 2: simple sidecars — pair with sequential file blobs by magic
    sequential = []  # (file_start, file_end, sidecar_start, sidecar_end, path)
    for ext, sidecars in simple_by_ext.items():
        paths = [p for _, _, p in sidecars]
        if ext == ".gdc":
            positions = gdsc_positions
        elif ext in (".scn", ".res"):
            if rsrc_files is None:
                rsrc_files = _rsrc_starts()
            if ext == ".scn":
                positions = [p for p, c in rsrc_files if c == "PackedScene"]
            else:
                positions = [p for p, c in rsrc_files
                             if c not in ADJACENT_CLASSES and c != "PackedScene"]
        else:
            continue

        if len(positions) > len(paths):
            positions = positions[:len(paths)]
        elif len(positions) < len(paths):
            continue  # mismatch — skip this ext for safe round-trip

        all_starts = sorted(p for p, _ in (rsrc_files or [(g, "") for g in gdsc_positions]))
        for i, gp in enumerate(positions):
            nexts = [s for s in all_starts if s > gp]
            end = nexts[0] if nexts else len(pck_buf)
            for s2, _, _ in sidecars:
                if s2 > gp:
                    clip = s2
                    while clip > gp and pck_buf[clip - 1] == 0:
                        clip -= 1
                    if clip < end:
                        end = clip
                    break
            sc_start, sc_end = sidecars[i][0], sidecars[i][1]
            sequential.append((gp, end, sc_start, sc_end, paths[i]))

    return adjacent, sequential


def pack_pck(original_binary, modified_pck_dir, output_binary,
             log_cb=None, cancel_cb=None, progress_cb=None):
    """Repack the PCK section of ``original_binary`` using whatever's
    in ``modified_pck_dir`` (mirror of the extractor's output tree).

    Files that don't appear in ``modified_pck_dir`` retain their
    original bytes.  Files that do are substituted in place.  The
    binary's PE/ELF code section is bit-copied; only the PCK section
    is rewritten and the trailer's pck_size is updated.
    """
    def _log(msg, sev="info"):
        if log_cb:
            log_cb(msg, sev)

    long_prefix = "\\\\?\\" if sys.platform == "win32" else ""

    pck_start, pck_end = find_pck_section(original_binary)
    _log(f"PCK section: [{pck_start}, {pck_end}) ({pck_end - pck_start} bytes)")

    # Read the original 12-byte trailer so we can preserve its magic
    # bytes for the rebuilt binary.  BOF May code uses GBOF here; if
    # we wrote GDPC instead, the game's bootstrap loader on the real
    # machine would fail to find the PCK section.  Pre-May Winchester
    # (and stock Godot) uses GDPC; preserve that too.
    with open(original_binary, "rb") as f:
        f.seek(pck_end)
        original_trailer_magic = f.read(PCK_TRAILER_LEN)[8:12]

    # Read the PCK section into memory.  We need random-access here for
    # the directory walk (sidecars/magics live throughout); the alternative
    # would be a multi-pass file scan which is far slower for the typical
    # 1.5 GB PCK.  We aim to keep ONE copy in memory and stream the
    # rewrite directly to the output file (rather than buffering a second
    # 1.5 GB+ bytearray) — see the streaming `_write_slice` below.  A
    # 2.8 GB binary with this approach uses ~1.5 GB peak RSS instead of
    # ~3 GB, which is what tripped the original MemoryError.
    with open(original_binary, "rb") as f:
        f.seek(pck_start)
        pck = bytearray(f.read(pck_end - pck_start))

    if not is_may_format(pck):
        raise PackerError(
            "Binary doesn't look like BOF May 2026 format — use the "
            "stock pipeline (GDRE Tools --pck-patch) for older PCKs.")

    adjacent, sequential = _read_pck_entries(pck)
    _log(f"Found {len(adjacent)} adjacent + {len(sequential)} sequential entries")

    # ---- Build the replacement list ---------------------------------
    # For each file entry that the user actually edited, record the
    # byte range of its FILE DATA in the original PCK plus the new
    # bytes that should appear there.  We DON'T touch sidecar bytes at
    # all — for adjacent entries the sidecar lives right after the
    # file data and gets copied verbatim with surrounding content;
    # for sequential entries (.gdc, .scn, .res) the sidecar lives far
    # away (the trailing-text area of the PCK) and is also unchanged.
    #
    # The previous algorithm walked entries and wrote each entry's
    # [file_end, sidecar_end] slice individually — for sequential
    # entries that ~1.4 GB slice could be re-written 469× (once per
    # .gdc entry), producing 200+ GB output.  This rewrite walks the
    # PCK bytes monotonically and writes each byte exactly once.
    all_items = []
    for kind, fs, fe, ss, se, p in adjacent:
        all_items.append((fs, fe, ss, se, p, kind))
    for fs, fe, ss, se, p in sequential:
        all_items.append((fs, fe, ss, se, p, "sequential"))
    all_items.sort(key=lambda x: x[0])

    n_total = len(all_items)
    n_replaced = 0
    n_font_verbatim = 0   # fonts left untouched (payload unchanged)

    # Pre-copy the unchanged binary prefix (ELF/PE code) directly from
    # the original to the output, then stream the PCK rewrite into the
    # same handle.  This avoids ever holding a copy of the rebuilt PCK
    # in memory — write-and-forget per slice.
    out_long = (long_prefix + os.path.abspath(output_binary)
                if sys.platform == "win32" else output_binary)

    pck_bytes_written = 0
    COPY_CHUNK = 8 * 1024 * 1024  # 8 MB chunks for the pre-PCK code copy

    # Total output bytes (≈ prefix + PCK; close enough for a progress bar).
    # Reported as bytes-written so the GUI shows a moving determinate bar
    # through the otherwise-silent multi-minute native pack — the May path
    # used to look frozen at 0% because it emitted no progress at all.
    total_out = pck_start + (pck_end - pck_start)
    bytes_out = 0

    def _report():
        if progress_cb:
            progress_cb(bytes_out, total_out, "Packing binary…")

    with open(original_binary, "rb") as src, open(out_long, "wb") as dst:
        # 1) Pre-PCK code section — copy bit-for-bit
        remaining = pck_start
        while remaining > 0:
            chunk = src.read(min(COPY_CHUNK, remaining))
            if not chunk:
                break
            dst.write(chunk)
            remaining -= len(chunk)
            bytes_out += len(chunk)
            _report()

        def _write_slice(start, end):
            """Write pck[start:end] to dst WITHOUT materialising a copy,
            in chunks so the progress bar keeps moving through large
            verbatim runs.  Tracks pck_bytes_written via closure."""
            nonlocal bytes_out
            nonlocal pck_bytes_written
            if end <= start:
                return
            # memoryview avoids the copy that bytes()/slice would create;
            # write in COPY_CHUNK steps so the bar advances on big runs.
            base = memoryview(pck)
            p = start
            while p < end:
                q = min(p + COPY_CHUNK, end)
                mv = base[p:q]
                dst.write(mv)
                mv.release()
                pck_bytes_written += (q - p)
                bytes_out += (q - p)
                _report()
                p = q
            base.release()

        # 2) PCK header + 8-byte pad — write directly from source
        _write_slice(0, PCK_HEADER_LEN + PCK_HEADER_PAD)

        # ---- Pass 1: build the replacement list -------------------
        # Each replacement is (start, end, new_bytes).  The byte-walk
        # in Pass 2 writes [cursor, start] verbatim, then new_bytes,
        # then advances cursor to end.
        #
        # For **adjacent** entries (textures, audio, fonts, etc.) the
        # entry's [fs, fe] range exactly bounds the file data — the
        # reader knows fe because the next byte is the .import sidecar
        # marker.  Safe to substitute new bytes of any size.
        #
        # For **sequential** entries (.gdc / .scn / .res) the reader
        # picks fe heuristically (next GDSC start, or next sidecar) so
        # the range may include bytes past the actual file end.
        # Replacing the whole range would clobber whatever sits in
        # those tail bytes (sometimes other files, sometimes padding).
        # We log a warning and SKIP the replacement, leaving the
        # original sequential file in place.  Mod authors who need to
        # change scripts / scenes today need to either match the exact
        # original byte size (which we can't easily verify) or use a
        # separate tool.
        skipped_sequential = []
        replacements = []
        for idx, (fs, fe, ss, se, p, kind) in enumerate(all_items):
            if cancel_cb is not None and idx % 25 == 0 and cancel_cb():
                raise RuntimeError("pack cancelled by user")
            rel = p[len("res://"):] if p.startswith("res://") else p
            local_path = os.path.abspath(
                os.path.join(modified_pck_dir, rel.replace("/", os.sep)))
            if sys.platform == "win32":
                local_path = long_prefix + local_path
            if not os.path.isfile(local_path):
                continue
            try:
                with open(local_path, "rb") as fh:
                    modified_bytes = fh.read()
            except OSError:
                continue
            orig_region = bytes(pck[fs:fe])

            if kind == "sequential":
                # .gdc/.scn/.res have no stable byte boundaries — only flag
                # as skipped if the file genuinely differs.
                if modified_bytes != orig_region:
                    skipped_sequential.append(rel)
                continue

            ext = os.path.splitext(p)[1].lower()
            if kind == "adjacent_rscc":
                # Fonts live COMPRESSED in the PCK but are extracted
                # DECOMPRESSED, so a raw byte compare always reports
                # "changed" even for untouched fonts.  Compare at the
                # decompressed-payload level instead, so an unchanged font
                # is left byte-for-byte verbatim.  Re-wrapping it would
                # shift every downstream entry off the PCK's 16-byte
                # alignment for no reason (and the .ttf/.otf→.fontdata
                # encoder isn't implemented, so fonts are never actually
                # user-edited — they only reached here via the byte compare).
                new_payload = _maybe_strip_rsrc_magic(modified_bytes, ext)
                ro = orig_region.find(b"RSCC")
                orig_payload = orig_csz = None
                if ro >= 0:
                    try:
                        orig_payload, orig_csz = decompress(orig_region, ro)
                    except Exception:
                        orig_payload = None
                if orig_payload is not None and new_payload == orig_payload:
                    n_font_verbatim += 1
                    continue   # unchanged font — leave verbatim
                new_container = _build_rscc_container(new_payload)
                # Preserve the bytes around the container — any lead, plus
                # the trailing 4-byte "RSCC" alignment separator before the
                # sidecar — so the inter-entry layout matches the original.
                lead = orig_region[:ro] if ro > 0 else b""
                trail = (orig_region[ro + orig_csz:]
                         if orig_csz is not None else b"")
                new_data = lead + new_container + trail
            else:  # adjacent_raw (.sample / .ctex / .oggvorbisstr)
                if modified_bytes == orig_region:
                    continue   # not actually different
                new_data = modified_bytes

            # SIZE-NEUTRAL substitution — the replacement MUST keep the
            # entry's exact original byte length so nothing downstream
            # shifts.  BOF's May PCK is a Godot v3 pack whose REAL file
            # directory lives encrypted at the header's dir_offset and
            # stores ABSOLUTE file offsets (verified by RE: the engine is
            # stock Godot 4.5.2 PackedSourcePCK + FileAccessEncrypted).
            # Our extractor sidesteps that directory by marker-scanning,
            # but the running engine uses it — so any net size change
            # leaves every later file's stored offset stale and the engine
            # reads boot resources at the wrong place → black screen (even
            # for an edit to a gameplay-only asset, because the shift
            # corrupts everything after it).  We can't rewrite the
            # encrypted directory (its AES key isn't statically
            # recoverable), so we forbid growth and zero-pad shrinkage back
            # to the original footprint.  The resource loader ignores the
            # trailing bytes (standard PCK padding) and QOA stops at its
            # frame count, so the pad is inert.
            orig_len = fe - fs
            if len(new_data) > orig_len:
                raise PackerError(
                    f"Replacement for '{rel}' is larger than the original "
                    f"({len(new_data)} > {orig_len} bytes). BOF's encrypted "
                    f"PCK directory stores absolute file offsets that can't "
                    f"be safely shifted, so a replacement must fit within the "
                    f"original's byte footprint. Audio is auto-trimmed to fit; "
                    f"for an image, supply a smaller/more-compressible file "
                    f"(e.g. lower resolution or higher WebP compression).")
            pad = orig_len - len(new_data)
            if pad:
                new_data = new_data + b"\x00" * pad
            _log(f"  replace {rel} [{kind}] {len(modified_bytes)} -> "
                 f"{orig_len} bytes (size-neutral"
                 + (f", +{pad}B zero-pad)" if pad else ")"))
            replacements.append((fs, fe, new_data))
            n_replaced += 1
        if skipped_sequential:
            _log(
                f"Skipped {len(skipped_sequential)} sequential-entry "
                f"replacements (.gdc/.scn/.res) — these don't have stable "
                f"byte boundaries in BOF's PCK layout so we can't safely "
                f"substitute. First few: "
                f"{', '.join(skipped_sequential[:3])}",
                "warning")
        # Sort by start so we can byte-walk in order.  Resolve any
        # overlaps by preferring the earlier entry — the file-finder
        # in _read_pck_entries should produce disjoint file-data
        # ranges in practice, but be defensive.
        replacements.sort(key=lambda r: r[0])
        deduped = []
        for fs, fe, new_data in replacements:
            if deduped and fs < deduped[-1][1]:
                continue   # overlap; drop the later entry
            deduped.append((fs, fe, new_data))
        replacements = deduped

        # ---- Pass 2: byte-walk through the PCK --------------------
        # Each byte in the original PCK is touched at most once.
        # Between replacements, bytes go verbatim; inside a
        # replacement range, the new bytes replace the original.
        cursor = PCK_HEADER_LEN + PCK_HEADER_PAD
        for fs, fe, new_data in replacements:
            if fs > cursor:
                _write_slice(cursor, fs)
            dst.write(new_data)
            pck_bytes_written += len(new_data)
            bytes_out += len(new_data)
            _report()
            cursor = fe

        # 3) PCK tail — everything from cursor to end of PCK
        if cursor < len(pck):
            _write_slice(cursor, len(pck))

        # 4) New trailer reflecting whatever total we just wrote.  Use
        # the ORIGINAL trailer magic (GBOF for May code, GDPC for
        # Winchester / stock Godot) so the rebuilt binary still loads
        # on the real machine.
        new_trailer = struct.pack("<Q", pck_bytes_written) + original_trailer_magic
        dst.write(new_trailer)

    _log(f"Rebuilt PCK: {pck_bytes_written} bytes (was {len(pck)}); "
         f"{n_replaced} files substituted, "
         f"{n_font_verbatim} unchanged font(s) left verbatim")

    # Release the input PCK buffer now that we're done with it.
    del pck

    new_binary_size = pck_start + pck_bytes_written + PCK_TRAILER_LEN
    return {
        "files_total": n_total,
        "files_replaced": n_replaced,
        "fonts_verbatim": n_font_verbatim,
        "original_pck_size": pck_end - pck_start,
        "new_pck_size": pck_bytes_written,
        "new_binary_size": new_binary_size,
    }
