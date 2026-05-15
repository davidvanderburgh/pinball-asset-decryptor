"""Audio format detection and conversion for JJP game assets.

JJP games use different WAV formats across files (mono/stereo, 44.1k/48k, etc.)
and OGG Vorbis for song-select previews.  This module detects mismatches between
replacement files and originals, and converts where possible using pure Python
(wave + struct + array) for WAV or flags the need for ffmpeg (OGG/sample-rate).
"""

import array
import io
import struct
import wave


def detect_wav_format(data):
    """Parse WAV header from raw bytes.

    Returns dict with nchannels, sampwidth, framerate, or None if not a
    valid uncompressed WAV that Python's wave module can read.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return {
                "nchannels": w.getnchannels(),
                "sampwidth": w.getsampwidth(),
                "framerate": w.getframerate(),
                "nframes": w.getnframes(),
            }
    except Exception:
        return None


def is_compressed_wav(data):
    """Return True if data looks like a WAV but uses a compressed codec."""
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE" and detect_wav_format(data) is None


def wav_formats_match(src, tgt):
    """Return True if src and tgt dicts have the same audio parameters."""
    return (
        src["nchannels"] == tgt["nchannels"]
        and src["sampwidth"] == tgt["sampwidth"]
        and src["framerate"] == tgt["framerate"]
    )


def format_description(fmt):
    """Human-readable format string, e.g. '2ch/16bit/44100Hz'."""
    return f"{fmt['nchannels']}ch/{fmt['sampwidth'] * 8}bit/{fmt['framerate']}Hz"


def format_diff(src, tgt):
    """Describe how src differs from tgt, e.g. '1ch->2ch, 48000Hz->44100Hz'."""
    diffs = []
    if src["nchannels"] != tgt["nchannels"]:
        diffs.append(f"{src['nchannels']}ch->{tgt['nchannels']}ch")
    if src["sampwidth"] != tgt["sampwidth"]:
        diffs.append(f"{src['sampwidth']*8}bit->{tgt['sampwidth']*8}bit")
    if src["framerate"] != tgt["framerate"]:
        diffs.append(f"{src['framerate']}Hz->{tgt['framerate']}Hz")
    return ", ".join(diffs) if diffs else "match"


def needs_ffmpeg(src_fmt, tgt_fmt):
    """Return True if conversion requires ffmpeg (sample rate change)."""
    return src_fmt["framerate"] != tgt_fmt["framerate"]


def convert_wav_python(data, src_fmt, tgt_fmt):
    """Convert WAV data in-memory using pure Python.

    Handles bit-depth (8/24/32 -> target) and channel (mono<->stereo) changes.
    Returns converted WAV bytes, or None if sample rate differs (needs ffmpeg).
    """
    if src_fmt["framerate"] != tgt_fmt["framerate"]:
        return None  # resampling requires ffmpeg

    # Read raw PCM frames
    with wave.open(io.BytesIO(data), "rb") as w:
        raw = w.readframes(w.getnframes())

    nframes = src_fmt["nframes"]
    src_sw = src_fmt["sampwidth"]
    src_ch = src_fmt["nchannels"]
    tgt_sw = tgt_fmt["sampwidth"]
    tgt_ch = tgt_fmt["nchannels"]

    # --- Step 1: Normalize to array of 16-bit signed samples ---
    # (intermediate representation — we'll convert to target bit-depth after)
    if src_sw == 1:
        # 8-bit unsigned -> 16-bit signed
        samples = array.array("h", ((b - 128) << 8 for b in raw))
    elif src_sw == 2:
        samples = array.array("h")
        samples.frombytes(raw)
    elif src_sw == 3:
        # 24-bit signed LE -> 16-bit signed
        samples = array.array("h")
        for i in range(0, len(raw), 3):
            val = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
            if val >= 0x800000:
                val -= 0x1000000
            samples.append(max(-32768, min(32767, val >> 8)))
    elif src_sw == 4:
        # 32-bit signed int -> 16-bit signed
        src_arr = array.array("i")
        src_arr.frombytes(raw)
        samples = array.array("h", (max(-32768, min(32767, s >> 16)) for s in src_arr))
    else:
        return None

    # --- Step 2: Channel conversion ---
    if src_ch == 1 and tgt_ch == 2:
        # Mono -> Stereo: duplicate each sample
        stereo = array.array("h")
        for s in samples:
            stereo.append(s)
            stereo.append(s)
        samples = stereo
    elif src_ch == 2 and tgt_ch == 1:
        # Stereo -> Mono: average L+R
        mono = array.array("h")
        for i in range(0, len(samples), 2):
            mono.append((samples[i] + samples[i + 1]) // 2)
        samples = mono
    elif src_ch > 2 and tgt_ch == 2:
        # Multi-channel -> Stereo: take first two channels
        stereo = array.array("h")
        for i in range(0, len(samples), src_ch):
            stereo.append(samples[i])
            stereo.append(samples[i + 1])
        samples = stereo
    elif src_ch > 2 and tgt_ch == 1:
        # Multi-channel -> Mono: average first two channels
        mono = array.array("h")
        for i in range(0, len(samples), src_ch):
            mono.append((samples[i] + samples[i + 1]) // 2)
        samples = mono

    # --- Step 3: Convert from 16-bit intermediate to target bit-depth ---
    if tgt_sw == 1:
        # 16-bit -> 8-bit unsigned
        out_raw = bytes((max(0, min(255, (s >> 8) + 128)) for s in samples))
    elif tgt_sw == 2:
        out_raw = samples.tobytes()
    elif tgt_sw == 3:
        # 16-bit -> 24-bit (zero-pad low byte)
        parts = []
        for s in samples:
            val = s << 8
            if val < 0:
                val += 0x1000000
            parts.append(bytes([val & 0xFF, (val >> 8) & 0xFF, (val >> 16) & 0xFF]))
        out_raw = b"".join(parts)
    elif tgt_sw == 4:
        # 16-bit -> 32-bit (shift up)
        out_arr = array.array("i", (s << 16 for s in samples))
        out_raw = out_arr.tobytes()
    else:
        return None

    # --- Step 4: Write output WAV ---
    out_buf = io.BytesIO()
    with wave.open(out_buf, "wb") as w:
        w.setnchannels(tgt_ch)
        w.setsampwidth(tgt_sw)
        w.setframerate(tgt_fmt["framerate"])
        w.writeframes(out_raw)
    return out_buf.getvalue()


# ------------------------------------------------------------------
# OGG Vorbis helpers
# ------------------------------------------------------------------

def detect_ogg_format(data):
    """Parse OGG Vorbis identification header from raw bytes.

    Returns dict with nchannels, sample_rate, nominal_bitrate,
    or None if not a valid OGG Vorbis file.
    """
    if len(data) < 4 or data[:4] != b"OggS":
        return None
    # Find Vorbis identification header: 0x01 + "vorbis"
    marker = b"\x01vorbis"
    idx = data.find(marker)
    if idx < 0 or idx + 7 + 21 > len(data):
        return None
    hdr = idx + 7  # skip marker
    try:
        version = struct.unpack_from("<I", data, hdr)[0]
        if version != 0:
            return None
        channels = data[hdr + 4]
        sample_rate = struct.unpack_from("<I", data, hdr + 5)[0]
        # max / nominal / min bitrate (signed 32-bit)
        _max_br = struct.unpack_from("<i", data, hdr + 9)[0]
        nom_br = struct.unpack_from("<i", data, hdr + 13)[0]
        _min_br = struct.unpack_from("<i", data, hdr + 17)[0]
        return {
            "nchannels": channels,
            "sample_rate": sample_rate,
            "nominal_bitrate": nom_br,
        }
    except (struct.error, IndexError):
        return None


def ogg_formats_match(src, tgt):
    """Return True if src and tgt OGG dicts have the same channel count
    and sample rate (bitrate differences are OK)."""
    return (
        src["nchannels"] == tgt["nchannels"]
        and src["sample_rate"] == tgt["sample_rate"]
    )


def ogg_format_description(fmt):
    """Human-readable OGG format string, e.g. '2ch/44100Hz/112kbps'."""
    br = fmt["nominal_bitrate"]
    br_str = f"{br // 1000}kbps" if br > 0 else "VBR"
    return f"{fmt['nchannels']}ch/{fmt['sample_rate']}Hz/{br_str}"


def ogg_format_diff(src, tgt):
    """Describe how src OGG differs from tgt."""
    diffs = []
    if src["nchannels"] != tgt["nchannels"]:
        diffs.append(f"{src['nchannels']}ch->{tgt['nchannels']}ch")
    if src["sample_rate"] != tgt["sample_rate"]:
        diffs.append(f"{src['sample_rate']}Hz->{tgt['sample_rate']}Hz")
    if src["nominal_bitrate"] != tgt["nominal_bitrate"]:
        src_br = src["nominal_bitrate"] // 1000
        tgt_br = tgt["nominal_bitrate"] // 1000
        diffs.append(f"{src_br}kbps->{tgt_br}kbps")
    return ", ".join(diffs) if diffs else "match"
