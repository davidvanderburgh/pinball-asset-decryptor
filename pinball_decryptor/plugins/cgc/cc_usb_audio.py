"""Cactus Canyon ``usb.so`` — CGC's *new* audio bank → WAV.

The Cactus Canyon remake keeps the original 1998 Bally audio in the Williams
DCS sound ROMs (``s2..s7.rom``, decoded elsewhere via DCSExplorer), and CGC's
*added* music / speech / SFX (the "Continued"-style modes — Stampede,
Showdown, High Noon, plus callouts and music loops) in ``ccdata/usb.so``.

Despite the ``.so`` name it is not an ELF — it's an **encrypted DCS sample
bank**.  The game's ``pin`` engine loads it via ``dcs_load_samplefile``
(@0x52174) which calls ``dcs_decrypt`` (@0x52300).  The decryption is a
3-stage, stateless transform over the whole buffer (verified byte-for-byte
against a Unicorn emulation of the real ``pin`` loop — see
``docs/CC_REVISITED_RE.md``):

  1. word-level byte-shuffle exchanging the lower/upper file halves,
  2. XOR every 32-bit word with ``dcsxor13_keys_32[i % 13]``,
  3. a 16-bit running prefix-sum over all halfwords.

The decrypted container is a 16-byte header + ``count`` records of 0x58 bytes
(``filename`` @+0x04, ``data_off`` @+0x44 (absolute), ``decoded_len`` @+0x4C,
``sample_count`` @+0x50), followed by the concatenated payloads.  The payloads
are **raw 48 kHz / mono / 16-bit PCM** (verified: ``decoded_len == 2 *
sample_count`` for every record), so each one is sliced straight out and
wrapped in a WAV header — no audio codec needed.

This module is **extract-only**.  Repack (edited WAV → re-encrypt → usb.so) is
separate, future work.
"""

from __future__ import annotations

import json
import os
import struct
import wave
from typing import Callable, List, Optional

# dcs_decrypt stage-2 key: dcsxor13_keys_32 @ pin VA 0x11a5a8 (13 LE u32).
DCSXOR13 = [
    0x53697CA5, 0x1B2D3A4E, 0xC5B4938D, 0x697CA5D1, 0x2D3A4E53,
    0xB4938D1B, 0x7CA5D1C5, 0x3A4E5369, 0x938D1B2D, 0xA5D1C5B4,
    0x4E53697C, 0x8D1B2D3A, 0xD1C5B493,
]

_REC = 0x58       # bytes per record
_BASE = 0x10      # records start after the 16-byte header
_SAMPLE_RATE = 48000
_CHANNELS = 1
_SAMPLE_WIDTH = 2  # 16-bit


class UsbAudioError(Exception):
    """usb.so wasn't the expected encrypted DCS sample bank."""


def _dcs_decrypt(data: bytes) -> bytes:
    """Decrypt a usb.so buffer.  Requires numpy (185 MB; the pure-Python
    prefix-sum would be far too slow).  Raises ImportError if absent."""
    import numpy as np

    if len(data) % 4:
        data = data + b"\x00" * (4 - len(data) % 4)
    w = np.frombuffer(data, dtype="<u4").copy()
    nwords = w.size
    n_pairs = nwords // 2

    # Stage 1: swap + byte-shuffle the lower/upper halves (word-paired).
    lo = w[:n_pairs].copy()
    hi = w[n_pairs:2 * n_pairs].copy()
    w[:n_pairs] = (hi & 0x00FF00FF) | (lo & 0xFF00FF00)
    w[n_pairs:2 * n_pairs] = (
        ((hi & 0xFF00FF00) >> np.uint32(8))
        | ((lo & 0x00FF00FF) << np.uint32(8))
    )

    # Stage 2: XOR each word with the 13-word repeating key.
    key = np.resize(np.array(DCSXOR13, dtype="<u4"), nwords)
    w ^= key

    # Stage 3: 16-bit running prefix-sum over all halfwords (uint16 wraps).
    h = w.view("<u2").copy()
    np.cumsum(h, dtype="u2", out=h)
    return h.tobytes()


def _dcs_encrypt(plain: bytes) -> bytes:
    """Inverse of :func:`_dcs_decrypt` — turn a decrypted bank back into the
    on-disk usb.so byte stream.  Applies the three stages' inverses in reverse
    order (un-prefix-sum → XOR → un-shuffle).  Requires numpy."""
    import numpy as np

    if len(plain) % 4:
        plain = plain + b"\x00" * (4 - len(plain) % 4)
    # Inverse stage 3: difference over halfwords (uint16 wraps mod 65536).
    s = np.frombuffer(plain, dtype="<u2").copy()
    d = s.copy()
    d[1:] = s[1:] - s[:-1]
    w = d.view("<u4").copy()
    nwords = w.size
    # Inverse stage 2: XOR is its own inverse.
    key = np.resize(np.array(DCSXOR13, dtype="<u4"), nwords)
    w ^= key
    # Inverse stage 1: recover the original lo/hi words from the shuffle.
    n_pairs = nwords // 2
    out_lo = w[:n_pairs].copy()
    out_hi = w[n_pairs:2 * n_pairs].copy()
    w[:n_pairs] = ((out_lo & 0xFF00FF00)
                   | ((out_hi & 0xFF00FF00) >> np.uint32(8)))
    w[n_pairs:2 * n_pairs] = ((out_lo & 0x00FF00FF)
                              | ((out_hi & 0x00FF00FF) << np.uint32(8)))
    return w.tobytes()


def decode_usb_so(usb_so_path: str) -> bytes:
    """Return the decrypted usb.so buffer, validating the integrity word."""
    with open(usb_so_path, "rb") as f:
        raw = f.read()
    dec = _dcs_decrypt(raw)
    if len(dec) < _BASE:
        raise UsbAudioError("usb.so too small to be a DCS sample bank")
    count = struct.unpack_from("<I", dec, 0)[0]
    chk = (struct.unpack_from("<I", dec, 8)[0]
           ^ struct.unpack_from("<I", dec, 0xC)[0])
    # pin's loader checks hdr[8]^hdr[0xc] == original file size.
    if chk != len(raw) or not (0 < count < 1_000_000):
        raise UsbAudioError(
            f"usb.so decrypt failed integrity check "
            f"(count={count}, chk=0x{chk:08x}, size={len(raw)})")
    return dec


def extract_usb_audio(usb_so_path: str, out_dir: str,
                      log_cb: Optional[Callable[[str, str], None]] = None,
                      progress_cb: Optional[Callable[[int, int, str], None]]
                      = None) -> int:
    """Decrypt *usb_so_path* and write every sample to a WAV under *out_dir*.

    Returns the number of WAVs written.  Writes a ``manifest.json`` index.
    Raises :class:`UsbAudioError` if the file isn't the expected bank, or
    ``ImportError`` if numpy is unavailable.
    """
    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    dec = decode_usb_so(usb_so_path)
    count = struct.unpack_from("<I", dec, 0)[0]
    os.makedirs(out_dir, exist_ok=True)

    entries: List[dict] = []
    written = 0
    for i in range(count):
        o = _BASE + i * _REC
        rec = dec[o:o + _REC]
        if len(rec) < _REC:
            break
        name = rec[4:0x44].split(b"\x00")[0].decode("latin1") or f"sound_{i}"
        data_off = struct.unpack_from("<I", rec, 0x44)[0]
        decoded_len = struct.unpack_from("<I", rec, 0x4C)[0]
        sample_count = struct.unpack_from("<I", rec, 0x50)[0]
        pcm = dec[data_off:data_off + decoded_len]
        if not pcm:
            continue
        safe = "".join(c if (c.isalnum() or c in "._-") else "_"
                       for c in name)
        if not safe.lower().endswith(".wav"):
            safe += ".wav"
        fn = f"{i:04d}_{safe}"
        with wave.open(os.path.join(out_dir, fn), "wb") as w:
            w.setnchannels(_CHANNELS)
            w.setsampwidth(_SAMPLE_WIDTH)
            w.setframerate(_SAMPLE_RATE)
            w.writeframes(pcm)
        entries.append({
            "index": i,
            "name": name,
            "wav_filename": fn,
            "duration_seconds": round(sample_count / _SAMPLE_RATE, 4),
            "sample_count": sample_count,
            "pcm_bytes": len(pcm),
        })
        written += 1
        if progress_cb and (i % 32 == 0 or i == count - 1):
            progress_cb(i + 1, count, name)

    manifest = {
        "format": "cgc_usb_audio_v1",
        "source": os.path.basename(usb_so_path),
        "sample_rate": _SAMPLE_RATE,
        "channels": _CHANNELS,
        "bits": _SAMPLE_WIDTH * 8,
        "track_count": written,
        "tracks": entries,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return written


def _read_wav_pcm(path: str):
    """Return raw PCM bytes of a 48 kHz / mono / 16-bit WAV, or raise."""
    with wave.open(path, "rb") as w:
        if (w.getnchannels() != _CHANNELS or w.getsampwidth() != _SAMPLE_WIDTH
                or w.getframerate() != _SAMPLE_RATE):
            raise UsbAudioError(
                f"{os.path.basename(path)} must be "
                f"{_SAMPLE_RATE} Hz / mono / 16-bit")
        return w.readframes(w.getnframes())


def repack_usb(orig_usb_so_path: str, new_audio_dir: str, out_usb_so_path: str,
               log_cb: Optional[Callable[[str, str], None]] = None) -> dict:
    """Rebuild usb.so with edited WAVs from *new_audio_dir* spliced in.

    Each ``new_audio/<NNNN>_*.wav`` whose PCM differs from the original
    record ``NNNN`` is spliced back into the decrypted bank (trimmed/padded to
    the original byte length, so the record table + size-check word stay
    valid), then the whole bank is re-encrypted to *out_usb_so_path*.

    A no-op repack (no WAV changed) reproduces the original bytes exactly.
    Returns ``{"modified_count": n, "total": count}``.
    """
    import glob as _glob

    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    with open(orig_usb_so_path, "rb") as f:
        raw = f.read()
    dec = bytearray(decode_usb_so(orig_usb_so_path))  # validates integrity
    count = struct.unpack_from("<I", dec, 0)[0]

    modified = 0
    for i in range(count):
        o = _BASE + i * _REC
        data_off = struct.unpack_from("<I", dec, o + 0x44)[0]
        decoded_len = struct.unpack_from("<I", dec, o + 0x4C)[0]
        matches = _glob.glob(os.path.join(
            _glob.escape(new_audio_dir), f"{i:04d}_*.wav"))
        if len(matches) != 1:
            continue
        try:
            pcm = _read_wav_pcm(matches[0])
        except UsbAudioError as e:
            log(f"  skip {os.path.basename(matches[0])}: {e}", "warning")
            continue
        if len(pcm) != decoded_len:
            pcm = (pcm + b"\x00" * decoded_len)[:decoded_len]
        if dec[data_off:data_off + decoded_len] == pcm:
            continue  # unchanged
        dec[data_off:data_off + decoded_len] = pcm
        modified += 1

    if modified:
        out = _dcs_encrypt(bytes(dec))
        # Preserve original length exactly (no trailing pad).
        out = out[:len(raw)]
        with open(out_usb_so_path, "wb") as f:
            f.write(out)
    return {"modified_count": modified, "total": count}
