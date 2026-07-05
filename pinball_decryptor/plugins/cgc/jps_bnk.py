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

# --- Per-buffer compressed-length prefix (zlib storage) ---------------------
# Each zlib sound buffer is preceded in the file by a 4-byte LE uint32 that
# the JPS loader reads to learn how many bytes to `fread` + hand to
# `uncompress` as its source length; it then continues sequentially to the
# next prefix.  The value is OBFUSCATED: the loader recovers the true
# compressed byte length as ``prefix ^ JPS_LEN_ENCODE_EXP mod
# JPS_LEN_MODULUS`` (a modular exponentiation, RE'd from `pin`'s bank loader
# @0x77354, decode routine @0x76428).  So a re-compressed buffer whose byte
# length changed MUST have this prefix rewritten -- otherwise the loader reads
# the wrong number of bytes and every following buffer in the bank desyncs
# (edited sound plays stale audio, untouched sounds fall silent, a later
# reference dereferences garbage and crashes).  The write direction uses the
# inverse exponent so ``JPS_LEN_ENCODE(len)`` reproduces the stock prefix
# (verified against all 1007 stock zlib buffers across the 5 PF zlib banks).
JPS_LEN_MODULUS = 0xE8A6B4C3        # 61967 * 62989 (both prime)
JPS_LEN_DECODE_EXP = 0xBC95E7B1     # prefix -> true length (loader's exponent)
JPS_LEN_ENCODE_EXP = 0x35AD47A9     # true length -> prefix (inverse mod lambda(N))
JPS_LEN_PREFIX_SIZE = 4


def _encode_length_prefix(length: int) -> bytes:
    """Return the 4-byte obfuscated compressed-length prefix the JPS loader
    expects in front of a zlib buffer of *length* bytes.

    Raises ValueError if the value doesn't round-trip through the loader's
    decode (only possible for the vanishingly rare length that shares a
    factor with the modulus) -- shipping a prefix the engine would decode to
    the wrong length is exactly the desync bug we're fixing, so we refuse to
    guess.
    """
    prefix_val = pow(length, JPS_LEN_ENCODE_EXP, JPS_LEN_MODULUS)
    if pow(prefix_val, JPS_LEN_DECODE_EXP, JPS_LEN_MODULUS) != length:
        raise ValueError(
            f"can't encode compressed length {length} into a JPS size prefix "
            f"(not invertible under the loader's cipher) -- re-export the clip "
            f"so it compresses to a different length.")
    return struct.pack("<I", prefix_val)


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
            # The outer RIFF size field is UNRELIABLE in these banks: CGC's
            # compiler inflates it so it overshoots into the *next* stream by
            # 62-4372 bytes.  Advancing by 8+riff_size therefore skipped every
            # other stream (pfmusic came out 24 of 49) AND dropped the last
            # stream (whose inflated size runs past EOF, failing the bounds
            # check).  The streams are packed CONTIGUOUSLY (verified: zero
            # inter-stream padding, byte-exact reconstruction to EOF), so the
            # true extent is the data chunk's end -- header + PCM -- which we
            # parse and advance by instead.
            fmt_pos = data.find(b"fmt ", i, i + 256)
            sr, ch, bps = SAMPLE_RATE, CHANNELS, 16
            if fmt_pos > 0:
                fmt_fields = struct.unpack_from("<HHIIHH", data, fmt_pos + 8)
                ch, sr, bps = (fmt_fields[1], fmt_fields[2], fmt_fields[5])
            data_pos = data.find(b"data", i, i + 1024)
            if data_pos > 0:
                pcm_size = struct.unpack_from("<I", data, data_pos + 4)[0]
                pcm_size = min(pcm_size, len(data) - data_pos - 8)
                # Real stream extent: from the stream start through the end of
                # its PCM (data chunk body).  For a canonical 44-byte header
                # this is 44 + pcm_size; computing it from the parsed data
                # offset also handles any non-standard pre-data chunk layout.
                stream_size = (data_pos - i) + 8 + pcm_size
                if i + stream_size <= len(data):
                    frame_bytes = ch * (bps // 8)
                    dur = (pcm_size / frame_bytes / sr
                           if frame_bytes and sr else 0)
                    buffers.append(SoundBuffer(
                        index=len(buffers), bnk_offset=i, storage="riff",
                        compressed_size=stream_size,
                        decompressed_size=stream_size,
                        pcm_size=pcm_size, duration_seconds=dur,
                        sample_rate=sr, channels=ch,
                        sample_width_bytes=bps // 8,
                    ))
                    i += stream_size
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
            # Embedded RIFF/WAV.  Re-emit a CLEAN canonical WAV rather than a
            # verbatim copy: the bank's native RIFF ``size`` field is
            # intentionally inflated (it overshoots into the next stream), so a
            # verbatim copy carries a bogus size field that confuses external
            # editors.  Read the PCM via the data chunk and write a standard
            # 44-byte-header WAV.  (Repack splices using the stock bank header,
            # never this file's header, so this is purely for the user's
            # convenience.)
            payload = data[buf.bnk_offset:buf.bnk_offset + buf.compressed_size]
            off, plen = _riff_data_span(payload)
            pcm = payload[off:off + plen] if off is not None else b""
            with wave.open(wav_path, "wb") as w:
                w.setnchannels(buf.channels)
                w.setsampwidth(buf.sample_width_bytes)
                w.setframerate(buf.sample_rate)
                w.writeframes(pcm)
        buf.wav_path = wav_path

    # Manifest JSON -- format-stable, friendly to a future repack tool
    # that reads it back.
    manifest_path = os.path.join(output_dir, f"{bnk_basename}.manifest.json")
    manifest = {
        # v2: the RIFF scanner now enumerates ALL streams (pfmusic went from
        # 24 to its true 49) with exact per-stream extents.  A v1 decoded
        # subdir has a different (sparser) slot->stream mapping, so the Write
        # pipeline refuses to build from one without a re-extract.
        "format": "jps_bnk_v2",
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
            new_payload, clamp_note = _encode_buffer_payload(
                buf, wav_path, original_payload, data)
            if clamp_note:
                summary.setdefault("clamp_notes", []).append(clamp_note)
            # A zlib re-compress almost never reproduces the stock byte length,
            # and the loader reads each buffer's length from an obfuscated
            # 4-byte prefix that sits immediately before the payload (the last
            # 4 bytes we've appended so far -- part of the file header for
            # buffer 0, otherwise the inter-buffer gap).  Rewrite it to match
            # the new compressed length, else the loader mis-reads this buffer
            # and desyncs every buffer after it.  (RIFF buffers are spliced
            # size-neutrally and carry no such prefix, so they're left alone.)
            if (buf.storage == "zlib"
                    and len(new_payload) != buf.compressed_size
                    and len(new_data) >= JPS_LEN_PREFIX_SIZE):
                new_prefix = _encode_length_prefix(len(new_payload))
                new_data[-JPS_LEN_PREFIX_SIZE:] = new_prefix
                summary.setdefault("prefix_rewrites", []).append(buf.index)
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
        # A leftover Replace-Audio staging temp ("<name>.stage.wav", from an
        # interrupted staging) matches the pattern too and would make a
        # perfectly good rename look ambiguous -- ignore staging scratch.
        matches = [m for m in glob.glob(pattern)
                   if ".stage." not in os.path.basename(m).lower()]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None  # ambiguous -- refuse to guess
    return None


def _riff_data_span(payload: bytes):
    """Locate the PCM ``data`` chunk inside an embedded RIFF/WAVE payload.

    Returns ``(pcm_offset, pcm_len)`` -- the byte offset of the PCM
    samples inside *payload* and the data chunk's declared size (clamped
    to the bytes actually present) -- or ``(None, None)`` if *payload*
    isn't a parseable RIFF/WAVE with a data chunk.

    ``pcm_len`` is exactly the length the game engine validates the
    loaded sample against (the jps loader drops a buffer to silence when
    the WAV's data-chunk length doesn't match the size recorded in the
    bank), so it is the length a replacement must match.
    """
    if payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        return None, None
    pos = 12
    n = len(payload)
    while pos + 8 <= n:
        cid = payload[pos:pos + 4]
        csz = struct.unpack_from("<I", payload, pos + 4)[0]
        body = pos + 8
        if cid == b"data":
            return body, min(csz, max(0, n - body))
        pos = body + csz + (csz & 1)  # RIFF chunks are word-aligned
    return None, None


def _clamp_pcm(pcm: bytes, target_len: int):
    """Fit *pcm* to exactly *target_len* bytes.  Returns
    ``(clamped, note)`` where note is 'truncated'/'padded'/None.

    JPS sound slots are fixed-length: the engine reads each buffer's PCM
    size from an up-front record and seeks to the next buffer by that
    size, so a replacement MUST be the stock byte length or it both
    silences its own slot (the loaded length won't match the record) and
    desyncs every later buffer.  *target_len* is already frame-aligned
    (it's the stock slot length), so a head-truncation stays aligned.
    """
    if len(pcm) == target_len:
        return pcm, None
    if len(pcm) > target_len:
        return pcm[:target_len], "truncated"
    return pcm + b"\x00" * (target_len - len(pcm)), "padded"


def _wav_pcm_differs_from_buffer(wav_path: str, buf: SoundBuffer,
                                 original_payload: bytes) -> bool:
    """Return True if the WAV's PCM bytes differ from what the
    original buffer decodes to (i.e. the user actually edited it).

    Compares only the PCM at the stock slot length -- a re-exported file
    with identical audio but a different container (extra metadata chunk,
    chunk reorder) is NOT treated as an edit, so it's preserved verbatim.
    """
    with wave.open(wav_path, "rb") as w:
        wav_pcm = w.readframes(w.getnframes())
    if buf.storage == "riff":
        off, plen = _riff_data_span(original_payload)
        if off is None:
            # Can't parse the stock payload -- treat as modified so the
            # encode path runs its own validation and aborts loudly.
            return True
        stock_pcm = original_payload[off:off + plen]
        clamped, _ = _clamp_pcm(wav_pcm, plen)
        return clamped != stock_pcm
    # zlib storage: decompress original, strip 44-byte JPS header,
    # compare PCM.
    d = zlib.decompressobj()
    orig_decompressed = d.decompress(original_payload)
    orig_pcm = orig_decompressed[JPS_BUFFER_HEADER_SIZE:]
    clamped, _ = _clamp_pcm(wav_pcm, len(orig_pcm))
    return clamped != orig_pcm


def _encode_buffer_payload(buf: SoundBuffer, wav_path: str,
                           original_payload: bytes,
                           original_data: bytes):
    """Encode a modified WAV into the buffer's storage format.

    Returns ``(payload_bytes, clamp_note)`` where clamp_note is a
    human-readable string when the replacement had to be truncated or
    padded to the stock slot length, else None.

    Both storage forms are edited SIZE-NEUTRALLY -- the re-packed buffer
    is exactly the stock byte length, differing only in its PCM samples.
    The game engine (SDL_mixer + the jps loader in ``pin``) frames every
    buffer as a fixed header + a recorded PCM length, validates the
    loaded length against that record (dropping the sound to silence on
    mismatch), and seeks to the next buffer by that same length -- so a
    longer/shorter splice silences its own slot AND desyncs the rest of
    the bank.  The music bank additionally chains streams the extractor
    doesn't surface, whose headers ride in each buffer's trailing bytes;
    keeping the stock header + trailer verbatim preserves those too.
    """
    with wave.open(wav_path, "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        nf = w.getnframes()
        pcm = w.readframes(nf)

    # Format must match the stock slot for BOTH storage forms (staging
    # normally guarantees this; a hand-dropped file might not).
    if (sr, ch, sw) != (buf.sample_rate, buf.channels,
                        buf.sample_width_bytes):
        raise ValueError(
            f"WAV {os.path.basename(wav_path)} has params "
            f"{sr}Hz/{ch}ch/{sw*8}bit but buffer {buf.index} expects "
            f"{buf.sample_rate}Hz/{buf.channels}ch/"
            f"{buf.sample_width_bytes*8}bit. Re-export your edit at "
            f"the correct format.")

    frame = max(1, ch * sw)

    def _note(kind, target_len):
        user_s = len(pcm) / frame / sr if sr else 0
        slot_s = target_len / frame / sr if sr else 0
        verb = "truncated" if kind == "truncated" else "padded with silence"
        return (f"buffer {buf.index}: your {user_s:.1f}s clip was {verb} "
                f"to the slot's fixed {slot_s:.1f}s -- JPS sound slots "
                f"can't change length")

    if buf.storage == "riff":
        # Keep the stock 44-byte header and everything after the PCM
        # (the next chained stream's header) byte-for-byte; swap only the
        # PCM, clamped to the stock data-chunk length.
        pcm_off, pcm_len = _riff_data_span(original_payload)
        if pcm_off is None:
            raise ValueError(
                f"Buffer {buf.index}: the stock music payload isn't a "
                f"parseable RIFF/WAVE (no data chunk) -- refusing to "
                f"splice, which would corrupt the bank.")
        new_pcm, kind = _clamp_pcm(pcm, pcm_len)
        new_payload = (original_payload[:pcm_off] + new_pcm
                       + original_payload[pcm_off + pcm_len:])
        if len(new_payload) != len(original_payload):
            raise ValueError(
                f"Buffer {buf.index}: size-neutral splice produced "
                f"{len(new_payload)} bytes, expected "
                f"{len(original_payload)} -- refusing to ship a "
                f"size-shifted bank.")
        return bytes(new_payload), (_note(kind, pcm_len) if kind else None)

    # zlib storage: preserve the original 44-byte JPS magic header (its
    # hash1/hash2 fields), clamp PCM to the stock decompressed length so
    # the engine's decompressed-length check still passes, re-compress.
    orig_d = zlib.decompressobj()
    orig_decompressed = orig_d.decompress(original_payload)
    jps_header = orig_decompressed[:JPS_BUFFER_HEADER_SIZE]
    target_len = len(orig_decompressed) - JPS_BUFFER_HEADER_SIZE
    new_pcm, kind = _clamp_pcm(pcm, target_len)
    new_decompressed = jps_header + new_pcm
    # Match the compression level JPS's compiler appears to use (0x78
    # 0x9C header byte in original files).
    return (zlib.compress(new_decompressed, 6),
            _note(kind, target_len) if kind else None)

