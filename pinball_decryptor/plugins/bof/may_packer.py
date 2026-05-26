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


def pack_pck(original_binary, modified_pck_dir, output_binary, log_cb=None):
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

    with open(original_binary, "rb") as f:
        f.seek(pck_start)
        pck = bytearray(f.read(pck_end - pck_start))

    if not is_may_format(pck):
        raise PackerError(
            "Binary doesn't look like BOF May 2026 format — use the "
            "stock pipeline (GDRE Tools --pck-patch) for older PCKs.")

    adjacent, sequential = _read_pck_entries(pck)
    _log(f"Found {len(adjacent)} adjacent + {len(sequential)} sequential entries")

    # Build a path -> (original-data, kind, sidecar_bytes, file_range) lookup
    # for the rebuild step.
    entries = []  # in document order: (file_data_bytes, sidecar_bytes, kind, path)
    # Sort by file_start so we emit in order.
    all_items = []
    for kind, fs, fe, ss, se, p in adjacent:
        all_items.append((fs, fe, ss, se, p, kind))
    for fs, fe, ss, se, p in sequential:
        all_items.append((fs, fe, ss, se, p, "sequential"))
    all_items.sort(key=lambda x: x[0])

    # Track replaced count for log
    n_total = len(all_items)
    n_replaced = 0
    out_pck = bytearray()
    out_pck += bytes(pck[:PCK_HEADER_LEN + PCK_HEADER_PAD])  # header + 8-byte pad

    cursor = PCK_HEADER_LEN + PCK_HEADER_PAD
    for i, (fs, fe, ss, se, p, kind) in enumerate(all_items):
        # Any gap between previous cursor and this file_start — copy verbatim.
        if fs > cursor:
            out_pck += bytes(pck[cursor:fs])

        # Determine new file bytes
        rel = p[len("res://"):] if p.startswith("res://") else p
        local_path = os.path.abspath(
            os.path.join(modified_pck_dir, rel.replace("/", os.sep)))
        if sys.platform == "win32":
            local_path = long_prefix + local_path

        modified_bytes = None
        if os.path.isfile(local_path):
            try:
                with open(local_path, "rb") as fh:
                    modified_bytes = fh.read()
            except OSError:
                modified_bytes = None

        orig_data = bytes(pck[fs:fe])
        if modified_bytes is not None and modified_bytes != orig_data:
            ext = os.path.splitext(p)[1].lower()
            if kind == "adjacent_rscc":
                new_payload = _maybe_strip_rsrc_magic(modified_bytes, ext)
                new_data = _build_rscc_container(new_payload)
            else:
                new_data = modified_bytes
            n_replaced += 1
        else:
            new_data = orig_data

        out_pck += new_data

        # Sidecar (and any zero padding / RSCC separator between file end
        # and sidecar start) — copy verbatim from the original.
        out_pck += bytes(pck[fe:se])
        cursor = se

    # Tail of PCK (after the last sidecar — usually project settings + zero pad)
    if cursor < len(pck):
        out_pck += bytes(pck[cursor:])

    _log(f"Rebuilt PCK: {len(out_pck)} bytes (was {len(pck)}); {n_replaced} files substituted")

    # Now write the output binary: pre-PCK code + new PCK + new trailer
    with open(original_binary, "rb") as f:
        pre = f.read(pck_start)

    new_trailer = struct.pack("<Q", len(out_pck)) + PCK_MAGIC_STOCK

    out_long = long_prefix + os.path.abspath(output_binary) if sys.platform == "win32" else output_binary
    with open(out_long, "wb") as f:
        f.write(pre)
        f.write(out_pck)
        f.write(new_trailer)

    return {
        "files_total": n_total,
        "files_replaced": n_replaced,
        "original_pck_size": len(pck),
        "new_pck_size": len(out_pck),
        "new_binary_size": len(pre) + len(out_pck) + len(new_trailer),
    }
