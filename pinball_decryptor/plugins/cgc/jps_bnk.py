"""JPS sound-bank extractor for Pulp Fiction `.bnk` files.

CGC's Pulp Fiction uses an in-house audio library called "JPS"
(confirmed via `strings` on the `pin` binary -- error messages all
prefixed with ``jps_``).  Each `.bnk` is a JPS-compiled bank
containing N "sound buffers" (each a zlib-DEFLATE stream wrapping a
fixed 44-byte JPS magic header + raw 48 kHz s16le stereo PCM) plus
metadata structures (filename, version, per-buffer header table,
playlists / events, command chunks).

See ``docs/CGC_BNK_RE.md`` for the full RE journal.

This module currently implements **extract only**:

  >>> from pinball_decryptor.plugins.cgc.jps_bnk import extract_bnk
  >>> sounds = extract_bnk("pfsndui.bnk", "out/")
  >>> for s in sounds:
  ...     print(s.index, s.wav_path, s.duration_seconds)

The output is one ``sound_<NN>.wav`` per zlib stream + a
``manifest.json`` with the per-event -> buffer mapping (so users
modding "the witch laugh" can tell which WAV to swap).

Repack is a future session -- needs hash1/hash2 algorithm + verified
on-machine round-trip.
"""

from __future__ import annotations

import json
import os
import struct
import wave
import zlib
from dataclasses import dataclass, field
from typing import List, Optional


# -----------------------------------------------------------------------------
# Format constants
# -----------------------------------------------------------------------------

# 44-byte per-stream header magic: 11 LE uint32s where 9 are constant
# and 2 (u32[1], u32[10]) vary per-stream.  Values from cross-bank analysis.
JPS_BUFFER_MAGIC = (
    0x0E6F07BB,   # u32[0]  constant
    None,         # u32[1]  per-stream hash (algorithm TBD)
    0x1385CA6D,   # u32[2]  constant
    0xDB8E52BF,   # u32[3]  constant
    0xCBA86BDF,   # u32[4]  constant
    0x3C4B88A6,   # u32[5]  constant
    0x31933080,   # u32[6]  constant
    0x3855CD0A,   # u32[7]  constant
    0x9AC705CB,   # u32[8]  constant
    0xD16487E2,   # u32[9]  constant
    None,         # u32[10] per-stream hash (algorithm TBD)
)
JPS_BUFFER_HEADER_SIZE = 44   # 11 * 4

# Audio params (constant across all known PF banks)
SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH_BYTES = 2

# Per-event command chunk size (uniform across SETV/PLAY/END/DUCK/UNDU/WAIT)
EVENT_CHUNK_SIZE = 96

# The per-PLAY ``buffer_index_byte_offset`` field at chunk offset +0x20
# uses a stride of 68 -- so buffer_index = field_value / 68.
PLAY_BUFFER_INDEX_FIELD_OFFSET = 0x20
PLAY_BUFFER_INDEX_STRIDE = 68


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------

@dataclass
class SoundBuffer:
    """One sound buffer extracted from a JPS bank.

    Banks store buffers in one of two forms:
      * ``"zlib"`` -- a zlib stream wrapping JPS-magic + raw PCM
        (UI, SFX, speech, diagnostic banks).
      * ``"riff"`` -- a standard RIFF/WAVE file embedded inline
        (music bank -- where zlib would only marginally help and the
        streaming-load path benefits from being able to seek + read
        directly without decompression).
    """
    index: int                  # 0-based position in the file's stream order
    bnk_offset: int             # byte offset of the stream in the bnk
    storage: str                # "zlib" or "riff"
    compressed_size: int        # bytes of stream in bnk
    decompressed_size: int      # bytes after decode (zlib: header+PCM; riff: whole WAV)
    pcm_size: int               # bytes of actual PCM payload
    duration_seconds: float
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    sample_width_bytes: int = SAMPLE_WIDTH_BYTES
    # zlib-only fields (None for RIFF buffers)
    hash1: Optional[int] = None  # u32[1] of the 44-byte header
    hash2: Optional[int] = None  # u32[10] of the 44-byte header
    wav_path: Optional[str] = None  # filled in by extract_bnk()


@dataclass
class Event:
    """A sound event (the user-facing 'sound' the game triggers).

    Events reference a SoundBuffer by index; many events may share
    the same buffer (especially in pfsnddiag where 140 events use just
    3 buffers).
    """
    index: int                  # 0-based position in command-chunk order
    buffer_index: int           # -1 if no buffer reference found
    chunk_offset: int           # PLAY chunk byte offset in the bnk


@dataclass
class BnkContents:
    """Everything we know about a parsed JPS bank file."""
    bnk_path: str
    source_name: str            # filename baked into the header (e.g. "pfsndui.txt")
    buffers: List[SoundBuffer] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Parser
# -----------------------------------------------------------------------------

def parse_bnk(bnk_path: str) -> BnkContents:
    """Read a JPS `.bnk` and return its structural contents.

    No files are written -- this is the read-only inspector.  Use
    :func:`extract_bnk` to also dump WAVs + manifest.
    """
    with open(bnk_path, "rb") as f:
        data = f.read()

    # ---- Source name (filename embedded in header) ---------------------
    # First null-terminated string at offset 0, max 32 bytes.
    name_end = data.find(b"\x00", 0, 32)
    source_name = data[:name_end if name_end > 0 else 16].decode(
        "latin-1", errors="replace")

    bnk = BnkContents(bnk_path=bnk_path, source_name=source_name)

    # ---- Sound buffers (zlib-compressed OR embedded RIFF) --------------
    bnk.buffers = _scan_buffers(data)

    # ---- Event commands (PLAY chunks) ----------------------------------
    bnk.events = _scan_events(data)

    return bnk


def _scan_buffers(data: bytes) -> List[SoundBuffer]:
    """Walk *data* finding every sound buffer (zlib or embedded RIFF).

    Returns them in file order with index = 0..N-1.  Music banks store
    buffers as embedded RIFF/WAVE; everything else uses zlib-wrapped
    JPS magic + PCM.
    """
    buffers: List[SoundBuffer] = []
    # A zero-copy view: the zlib probe below slices ``data[i:]`` at (in the
    # worst case) every 0x78 byte in the PCM of a music bank -- a full
    # multi-hundred-MB copy each time, which made parsing a 233 MB pfmusic.bnk
    # take ~140 s.  Slicing the memoryview instead is O(1); the decompress
    # still fails fast on non-zlib data, now without the copy.
    mv = memoryview(data)
    # Next embedded-RIFF marker, advanced lazily so the byte-search below stays
    # O(n) overall instead of re-scanning to a distant 'RIFF' from every byte.
    next_riff = data.find(b"RIFF")
    i = 0
    while i < len(data) - 6:
        # ---- zlib stream (JPS magic inside) ----
        if data[i] == 0x78 and data[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                # 0x78 0x9C etc. is a *valid* zlib header, so a false hit in
                # PCM would otherwise decompress megabytes of garbage before
                # failing.  Probe just the header bytes we need to check the
                # JPS magic (max_length caps the output); only a confirmed
                # match pays for the full decompress.  This is what actually
                # collapses the pfmusic parse from ~65 s to well under 1 s.
                probe = zlib.decompressobj()
                # Bound the INPUT window too: passing the whole (up to 233 MB)
                # tail makes zlib ingest all of it even though max_length caps
                # the output, which was the real 52 s hog.  The 44-byte header
                # decompresses from far less than 64 KiB of compressed input.
                head = probe.decompress(mv[i:i + 65536], JPS_BUFFER_HEADER_SIZE)
                if (len(head) >= JPS_BUFFER_HEADER_SIZE
                        and _matches_jps_magic(
                            struct.unpack("<11I",
                                          head[:JPS_BUFFER_HEADER_SIZE]))):
                    d = zlib.decompressobj()
                    out = d.decompress(mv[i:])
                    consumed = len(data) - i - len(d.unused_data)
                    fields = struct.unpack("<11I",
                                           out[:JPS_BUFFER_HEADER_SIZE])
                    pcm_size = len(out) - JPS_BUFFER_HEADER_SIZE
                    frame_bytes = CHANNELS * SAMPLE_WIDTH_BYTES
                    pcm_size = (pcm_size // frame_bytes) * frame_bytes
                    dur = pcm_size / frame_bytes / SAMPLE_RATE
                    buffers.append(SoundBuffer(
                        index=len(buffers), bnk_offset=i, storage="zlib",
                        compressed_size=consumed,
                        decompressed_size=len(out),
                        hash1=fields[1], hash2=fields[10],
                        pcm_size=pcm_size, duration_seconds=dur,
                    ))
                    i += consumed
                    continue
            except zlib.error:
                pass

        # ---- Embedded RIFF/WAV stream (music banks) ----
        if data[i:i + 4] == b"RIFF" and data[i + 8:i + 12] == b"WAVE":
            riff_size = struct.unpack_from("<I", data, i + 4)[0]
            total = 8 + riff_size  # 'RIFF' + size + (riff_size bytes)
            if i + total <= len(data):
                # Parse fmt chunk for srate/channels/bits
                fmt_pos = data.find(b"fmt ", i, i + 256)
                sr, ch, bps = SAMPLE_RATE, CHANNELS, 16
                if fmt_pos > 0:
                    fmt_fields = struct.unpack_from("<HHIIHH", data,
                                                    fmt_pos + 8)
                    ch, sr, bps = (fmt_fields[1], fmt_fields[2],
                                   fmt_fields[5])
                # Find data chunk size for PCM-size calc
                data_pos = data.find(b"data", i, i + 1024)
                pcm_size = 0
                if data_pos > 0:
                    pcm_size = struct.unpack_from("<I", data,
                                                  data_pos + 4)[0]
                    pcm_size = min(pcm_size, len(data) - data_pos - 8)
                frame_bytes = ch * (bps // 8)
                dur = (pcm_size / frame_bytes / sr) if frame_bytes and sr else 0
                buffers.append(SoundBuffer(
                    index=len(buffers), bnk_offset=i, storage="riff",
                    compressed_size=total, decompressed_size=total,
                    pcm_size=pcm_size, duration_seconds=dur,
                    sample_rate=sr, channels=ch,
                    sample_width_bytes=bps // 8,
                ))
                i += total
                continue
        # No buffer starts at i.  Jump straight to the next position that
        # could -- the nearest of the next 0x78 (zlib header) or the next
        # 'RIFF' -- rather than walking byte-by-byte through hundreds of MB of
        # PCM.  This is what takes the 233 MB pfmusic.bnk parse from ~140 s to
        # well under a second.  ``next_riff`` is only re-searched once we pass
        # it, keeping total scan work linear.
        if next_riff != -1 and next_riff <= i:
            next_riff = data.find(b"RIFF", i + 1)
        j78 = data.find(b"\x78", i + 1)
        cands = [x for x in (j78, next_riff) if x != -1]
        if not cands:
            break
        i = min(cands)
    return buffers


def _matches_jps_magic(fields: tuple) -> bool:
    """Return True if the 11 uint32 fields match the JPS buffer header
    magic pattern (9 constant slots, 2 wildcards).
    """
    return all(fields[k] == JPS_BUFFER_MAGIC[k]
               for k in range(11) if JPS_BUFFER_MAGIC[k] is not None)


def _scan_events(data: bytes) -> List[Event]:
    """Find every PLAY chunk in the bnk and decode its buffer-index ref.

    Per session-2 RE: PLAY chunks live in the "command region" between
    the per-buffer header table and the first zlib stream.  Each chunk
    is uniform 96 bytes; the field at +0x20 is ``buffer_index * 68``.

    We don't enforce structural assumptions about where the command
    region starts -- a linear scan for the 4-char 'PLAY' tag at 96-byte
    boundaries from the first 'PLAY' hit is robust enough and matches
    what the JPS loader does (it walks command chunks sequentially).
    """
    events: List[Event] = []
    # Find first PLAY tag - that anchors the 96-byte stride
    first_play = -1
    for i in range(len(data) - 3):
        if data[i:i + 4] == b"PLAY":
            first_play = i
            break
    if first_play < 0:
        return events

    # Walk forward in 96-byte strides while we still see chunk-shaped data
    # (any 4-char ASCII tag at the start).  Stop at the first non-tag chunk.
    pos = first_play
    while pos + EVENT_CHUNK_SIZE <= len(data):
        tag = data[pos:pos + 4]
        # End of command region: chunk start no longer matches any known tag.
        # The 0x60-aligned bytes will be 0x78 (zlib header) when we cross over.
        if data[pos] == 0x78 and data[pos + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            break
        if tag == b"PLAY":
            field_val = struct.unpack_from(
                "<I", data, pos + PLAY_BUFFER_INDEX_FIELD_OFFSET)[0]
            if field_val % PLAY_BUFFER_INDEX_STRIDE == 0:
                buffer_index = field_val // PLAY_BUFFER_INDEX_STRIDE
            else:
                buffer_index = -1
            events.append(Event(index=len(events),
                                buffer_index=buffer_index,
                                chunk_offset=pos))
        pos += EVENT_CHUNK_SIZE
    return events


# -----------------------------------------------------------------------------
# Extractor
# -----------------------------------------------------------------------------

def extract_bnk(bnk_path: str, output_dir: str) -> BnkContents:
    """Extract every sound buffer in *bnk_path* as a WAV + manifest.

    Writes:
      * ``sound_<NN>.wav`` for each zlib-compressed sound buffer
      * ``manifest.json`` with the bank-level metadata + per-event ->
        buffer-index mapping

    Returns the parsed :class:`BnkContents` (with ``wav_path`` filled
    in on each buffer).
    """
    bnk = parse_bnk(bnk_path)
    os.makedirs(output_dir, exist_ok=True)

    bnk_basename = os.path.splitext(os.path.basename(bnk_path))[0]
    # Re-read so we can decompress directly into the WAV write loop.
    with open(bnk_path, "rb") as f:
        data = f.read()

    for buf in bnk.buffers:
        wav_name = f"{bnk_basename}_sound_{buf.index:03d}.wav"
        wav_path = os.path.join(output_dir, wav_name)
        if buf.storage == "zlib":
            # Decompress + strip 44-byte JPS magic + write PCM payload
            # as a standard WAV.
            d = zlib.decompressobj()
            out = d.decompress(data[buf.bnk_offset:])
            pcm = out[JPS_BUFFER_HEADER_SIZE:
                      JPS_BUFFER_HEADER_SIZE + buf.pcm_size]
            with wave.open(wav_path, "wb") as w:
                w.setnchannels(buf.channels)
                w.setsampwidth(buf.sample_width_bytes)
                w.setframerate(buf.sample_rate)
                w.writeframes(pcm)
        else:
            # Embedded RIFF/WAV -- copy the bytes verbatim.  No transcode.
            with open(wav_path, "wb") as w:
                w.write(data[buf.bnk_offset:
                             buf.bnk_offset + buf.compressed_size])
        buf.wav_path = wav_path

    # Manifest JSON -- format-stable, friendly to a future repack tool
    # that reads it back.
    manifest_path = os.path.join(output_dir, f"{bnk_basename}.manifest.json")
    manifest = {
        "format": "jps_bnk_v1",
        "bnk_basename": bnk_basename,
        "source_name": bnk.source_name,
        "audio_params": {
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
            "sample_width_bytes": SAMPLE_WIDTH_BYTES,
        },
        "buffers": [
            {
                "index": b.index,
                "wav_filename": (os.path.basename(b.wav_path)
                                 if b.wav_path else None),
                "storage": b.storage,
                "sample_rate": b.sample_rate,
                "channels": b.channels,
                "sample_width_bytes": b.sample_width_bytes,
                "duration_seconds": round(b.duration_seconds, 4),
                "pcm_size_bytes": b.pcm_size,
                "compressed_size_bytes": b.compressed_size,
                "bnk_offset_hex": f"0x{b.bnk_offset:X}",
                "hash1_hex": (f"0x{b.hash1:08X}"
                              if b.hash1 is not None else None),
                "hash2_hex": (f"0x{b.hash2:08X}"
                              if b.hash2 is not None else None),
            } for b in bnk.buffers
        ],
        "events": [
            {
                "event_index": e.index,
                "plays_buffer": e.buffer_index,
                "chunk_offset_hex": f"0x{e.chunk_offset:X}",
            } for e in bnk.events
        ],
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return bnk


# -----------------------------------------------------------------------------
# Repack
# -----------------------------------------------------------------------------

def repack_bnk(original_bnk_path: str, modified_wavs_dir: str,
               output_bnk_path: str) -> dict:
    """Rebuild a JPS `.bnk` with modified WAVs spliced in.

    Strategy: preserve every byte of the original bnk except the
    sound-buffer payloads themselves. For each buffer:

      * If a corresponding WAV in *modified_wavs_dir* is identical to
        what we'd extract from the original, copy the original
        compressed bytes verbatim.
      * Otherwise, re-encode the WAV's PCM with zlib, preserving the
        original 44-byte JPS magic header (including the hash1/hash2
        fields, which we don't know how to compute -- copying them
        works fine in practice because JPS appears not to validate
        them on load).
      * For RIFF-storage buffers, the modified WAV bytes are written
        directly (no zlib).

    Any 4-byte "gap" between consecutive buffers in the original is
    preserved bit-for-bit; we don't know its purpose but unchanged is
    the safe bet. Same for the header / ID table / command-chunk
    regions before the first buffer and any trailing data after the
    last buffer.

    Returns a summary dict with per-buffer change details so callers
    (or tests) can verify what got rewritten.
    """
    bnk = parse_bnk(original_bnk_path)
    if not bnk.buffers:
        raise ValueError(
            f"No sound buffers found in {original_bnk_path} -- "
            f"can't repack an empty bank.")

    with open(original_bnk_path, "rb") as f:
        data = f.read()

    bnk_basename = os.path.splitext(os.path.basename(original_bnk_path))[0]
    new_data = bytearray()
    summary = {"buffers": [], "modified_count": 0, "total_count": len(bnk.buffers)}

    # 1) Preserve everything up to the first buffer (header, ID table,
    #    command chunks, per-buffer header table, etc.)
    first_buf_offset = bnk.buffers[0].bnk_offset
    new_data.extend(data[:first_buf_offset])

    # 2) For each buffer in order: preserve the inter-buffer "gap"
    #    bytes (for buffers after the first), then the buffer payload
    #    -- either copied verbatim or rebuilt from the modified WAV.
    prev_buf_end = first_buf_offset
    for buf in bnk.buffers:
        # Bytes between previous buffer's end and this buffer's start
        # (zero-length for the first buffer; usually 4 bytes for the rest).
        if buf.bnk_offset > prev_buf_end:
            new_data.extend(data[prev_buf_end:buf.bnk_offset])
        elif buf.bnk_offset < prev_buf_end:
            raise ValueError(
                f"Buffer {buf.index} overlaps previous buffer "
                f"(@0x{buf.bnk_offset:X} < prev_end @0x{prev_buf_end:X}) "
                f"-- the bnk has an unexpected layout.")

        original_payload = data[buf.bnk_offset:
                                buf.bnk_offset + buf.compressed_size]

        wav_path = _resolve_wav_path(modified_wavs_dir, bnk_basename, buf.index)
        if wav_path and _wav_pcm_differs_from_buffer(
                wav_path, buf, original_payload):
            # User-edited WAV -- re-encode and splice in.
            new_payload = _encode_buffer_payload(buf, wav_path,
                                                 original_payload, data)
            was_modified = True
            summary["modified_count"] += 1
        else:
            # WAV missing OR identical to original -- preserve verbatim.
            # (Preserving original bytes byte-for-byte is important; our
            # re-zlib doesn't produce identical output to JPS's
            # compiler even from identical PCM input, so re-encoding
            # would falsely flip "unchanged" buffers as modified.)
            new_payload = original_payload
            was_modified = False
        summary["buffers"].append({
            "index": buf.index,
            "original_size": len(original_payload),
            "new_size": len(new_payload),
            "size_delta": len(new_payload) - len(original_payload),
            "modified": was_modified,
            # The WAV this buffer resolved to (None if no file matched).
            # Callers use this to verify every user-edited WAV was
            # actually consumed by some buffer -- an edited file the
            # resolver can't match would otherwise vanish silently.
            "wav": wav_path,
        })

        new_data.extend(new_payload)
        prev_buf_end = buf.bnk_offset + buf.compressed_size

    # 3) Preserve any trailing bytes after the last buffer.
    if prev_buf_end < len(data):
        new_data.extend(data[prev_buf_end:])

    summary["original_size"] = len(data)
    summary["new_size"] = len(new_data)

    os.makedirs(os.path.dirname(output_bnk_path) or ".", exist_ok=True)
    with open(output_bnk_path, "wb") as f:
        f.write(new_data)

    return summary


def _resolve_wav_path(wavs_dir: str, bnk_basename: str,
                      buf_index: int) -> Optional[str]:
    """Find the WAV file that corresponds to a given buffer index.

    Tries the canonical name first (``<bnk>_sound_NNN.wav``) then
    falls back to ``sound_NNN.wav`` (older convention).  If neither
    exists, looks for a transcribe-renamed sibling: Extract's
    auto-transcribe step renames WAVs to ``<stem> - <transcript>.wav``
    (strict " - " separator, same convention as the Write pipeline's
    ``_find_renamed_sibling``), and Replace Audio then stages the
    user's track over the *renamed* file -- without this fallback no
    audio mod on a transcribed extract ever reaches the bank.  A
    renamed lookup only counts when it's unique; multiple matches are
    ambiguous, so we return None rather than guess (the pipeline-level
    consumed-check turns that into a loud abort, not a silent
    unmodified build).
    """
    import glob
    stems = [
        f"{bnk_basename}_sound_{buf_index:03d}",
        f"sound_{buf_index:03d}",
    ]
    for stem in stems:
        p = os.path.join(wavs_dir, stem + ".wav")
        if os.path.isfile(p):
            return p
    for stem in stems:
        pattern = os.path.join(glob.escape(wavs_dir),
                               f"{glob.escape(stem)} - *.wav")
        matches = glob.glob(pattern)
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None  # ambiguous -- refuse to guess
    return None


def _wav_pcm_differs_from_buffer(wav_path: str, buf: SoundBuffer,
                                 original_payload: bytes) -> bool:
    """Return True if the WAV's PCM bytes differ from what the
    original buffer decompresses to (i.e. the user actually edited it).
    """
    with wave.open(wav_path, "rb") as w:
        wav_pcm = w.readframes(w.getnframes())
    if buf.storage == "riff":
        # For RIFF buffers, compare the bytes of the embedded WAV
        # directly -- the user's file IS the storage format.
        return open(wav_path, "rb").read() != original_payload
    # zlib storage: decompress original, strip 44-byte JPS header,
    # compare PCM.
    d = zlib.decompressobj()
    orig_decompressed = d.decompress(original_payload)
    orig_pcm = orig_decompressed[
        JPS_BUFFER_HEADER_SIZE:JPS_BUFFER_HEADER_SIZE + buf.pcm_size]
    return wav_pcm != orig_pcm


def _encode_buffer_payload(buf: SoundBuffer, wav_path: str,
                           original_payload: bytes,
                           original_data: bytes) -> bytes:
    """Encode a modified WAV into the buffer's storage format.

    For ``zlib`` buffers: read the WAV's PCM data, glue the original
    44-byte JPS magic header to the front, then zlib-compress.
    For ``riff`` buffers: just return the WAV bytes verbatim (the
    storage format IS a RIFF/WAV file).
    """
    with wave.open(wav_path, "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        nf = w.getnframes()
        pcm = w.readframes(nf)

    if buf.storage == "riff":
        # Need to emit a complete WAV file with the same format as the
        # original.  Easiest: copy the user's WAV bytes verbatim.
        return open(wav_path, "rb").read()

    # zlib storage: preserve the original 44-byte JPS magic header so
    # the hash1/hash2 fields stay the same.
    if (sr, ch, sw) != (buf.sample_rate, buf.channels,
                        buf.sample_width_bytes):
        raise ValueError(
            f"WAV {os.path.basename(wav_path)} has params "
            f"{sr}Hz/{ch}ch/{sw*8}bit but buffer {buf.index} expects "
            f"{buf.sample_rate}Hz/{buf.channels}ch/"
            f"{buf.sample_width_bytes*8}bit. Re-export your edit at "
            f"the correct format.")

    # Decompress original to extract its 44-byte JPS header.
    orig_d = zlib.decompressobj()
    orig_decompressed = orig_d.decompress(original_payload)
    jps_header = orig_decompressed[:JPS_BUFFER_HEADER_SIZE]

    new_decompressed = jps_header + pcm
    # Use the same compression level zlib's default produces; that
    # matches what JPS's compiler output appears to use (0x78 0x9C
    # header byte in original files).
    return zlib.compress(new_decompressed, 6)

