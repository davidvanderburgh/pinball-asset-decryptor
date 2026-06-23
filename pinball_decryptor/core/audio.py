"""Audio processing for replacement assets — format detection, conversion, trim/pad.

When users replace audio files (WAV, OGG) in extracted game assets, the
replacements may differ from the originals in duration, sample rate, channel
count, or bit depth.  This module provides:

  - Audio metadata detection (WAV and OGG Vorbis)
  - Pure-Python WAV duration matching (trim / silence-pad)
  - Pure-Python WAV format conversion (bit depth, channels)
  - ffmpeg-based OGG duration matching and format conversion
  - ffmpeg-based WAV resampling (when sample rate differs)

The modify pipeline calls ``process_modified_audio()`` for each changed audio
file to auto-convert it so the game accepts it without issues.
"""

import os
import struct
import shutil
import subprocess
import sys

# Prevent console windows from flashing on Windows
_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe discovery (shared with p3_video)
# ---------------------------------------------------------------------------

_ffmpeg_path = None
_ffprobe_path = None
_ffmpeg_shimmed = False


def _imageio_ffmpeg_exe():
    """Path to the ffmpeg binary bundled by the imageio-ffmpeg wheel, or
    None if that package isn't installed or has no usable binary.

    This is how the frozen macOS / Linux apps ship a working ffmpeg without a
    system install: imageio-ffmpeg is pip-installed and collected into the
    bundle, and exposes its binary's path here."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    return exe if exe and os.path.isfile(exe) else None


def _ffmpeg_candidates(name):
    """Common install locations for an ffmpeg-family binary (*name* is
    ``"ffmpeg"`` or ``"ffprobe"``), searched after PATH and before the
    bundled-imageio fallback.

    Merged from the per-plugin finders so this stays the single source of
    truth.  A Finder-launched macOS .app inherits no shell PATH, so the
    explicit brew paths matter; Windows users install via winget / scoop /
    choco / manual unzip, so we probe all of those."""
    import glob as _glob
    if sys.platform == "win32":
        exe = f"{name}.exe"
        cands = []
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            for d in _glob.glob(os.path.join(
                    local_app, "Microsoft", "WinGet", "Packages",
                    "*ffmpeg*", "*", "bin")):
                cands.append(os.path.join(d, exe))
            cands.append(os.path.join(
                local_app, "Microsoft", "WinGet", "Links", exe))
            cands.append(os.path.join(local_app, "ffmpeg", "bin", exe))
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            cands.append(os.path.join(userprofile, "scoop", "shims", exe))
        choco = os.environ.get("ChocolateyInstall",
                               r"C:\ProgramData\chocolatey")
        cands.append(os.path.join(choco, "bin", exe))
        for base in (os.environ.get("ProgramFiles", ""),
                     os.environ.get("ProgramFiles(x86)", "")):
            if base:
                cands.append(os.path.join(base, "ffmpeg", "bin", exe))
        cands.append(rf"C:\ffmpeg\bin\{exe}")
        return cands
    if sys.platform == "darwin":
        return [f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"]
    return [f"/usr/bin/{name}", f"/usr/local/bin/{name}"]


def find_ffmpeg():
    """Find the ffmpeg executable -- the single source of truth for the whole
    app (every plugin's finder delegates here).  Checks PATH, the OS's common
    install locations, then the ffmpeg bundled via imageio-ffmpeg (shipped in
    the frozen macOS/Linux apps so ffmpeg features work with no system
    install)."""
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path if _ffmpeg_path else None

    path = shutil.which("ffmpeg")
    if path:
        _ffmpeg_path = path
        return path

    for c in _ffmpeg_candidates("ffmpeg"):
        if os.path.isfile(c):
            _ffmpeg_path = c
            return c

    # Last resort: the ffmpeg bundled via imageio-ffmpeg (shipped inside the
    # frozen macOS/Linux apps so the audio tab works without a system ffmpeg).
    # A pure fallback -- a real ffmpeg on PATH or in the brew/Program Files
    # locations above always wins, so this never shadows a fuller system build.
    bundled = _imageio_ffmpeg_exe()
    if bundled:
        _ffmpeg_path = bundled
        return bundled

    _ffmpeg_path = ""
    return None


def find_ffprobe():
    """Find the ffprobe executable."""
    global _ffprobe_path
    if _ffprobe_path is not None:
        return _ffprobe_path if _ffprobe_path else None

    path = shutil.which("ffprobe")
    if path:
        _ffprobe_path = path
        return path

    for c in _ffmpeg_candidates("ffprobe"):
        if os.path.isfile(c):
            _ffprobe_path = c
            return c

    # Try same directory as ffmpeg
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        d = os.path.dirname(ffmpeg)
        ext = ".exe" if sys.platform == "win32" else ""
        probe = os.path.join(d, f"ffprobe{ext}")
        if os.path.isfile(probe):
            _ffprobe_path = probe
            return probe

    _ffprobe_path = ""
    return None


def ensure_bundled_ffmpeg_on_path():
    """Expose the ffmpeg :func:`find_ffmpeg` resolves under the plain name
    ``ffmpeg`` on PATH, so EVERY ffmpeg consumer can find it -- not just this
    module.

    Two consumers can't use :func:`find_ffmpeg`'s smart lookup and only see
    PATH: the per-manufacturer prerequisite checks shell out to bare
    ``ffmpeg -version``, and several plugins ship their own verbatim-upstream
    ffmpeg finders we must not edit.  Those would report "ffmpeg missing" even
    when :func:`find_ffmpeg` locates one -- e.g. the macOS/Linux apps bundle
    ffmpeg via imageio-ffmpeg under a version-stamped name
    (``ffmpeg-osx-arm64-v7.0``), and on Windows ffmpeg often lives in a
    winget / scoop / Program Files directory that isn't on the running app's
    PATH.  So resolve it once with the full finder and put it on PATH for
    everyone: prepend its real directory when it's a normally-named binary, or
    symlink/copy a version-stamped one into a temp dir as ``ffmpeg``.

    Idempotent; call once at startup.  A real ffmpeg already on PATH always
    wins (early return), and when nothing is found this is a no-op."""
    global _ffmpeg_shimmed
    if _ffmpeg_shimmed:
        return
    _ffmpeg_shimmed = True
    if shutil.which("ffmpeg"):
        return  # a real ffmpeg is already discoverable
    # Resolve the same way find_ffmpeg() does -- the OS install locations
    # (winget/scoop/Program Files on Windows, brew on macOS) then the bundled
    # imageio binary -- but WITHOUT find_ffmpeg()'s module-level cache, which an
    # earlier no-ffmpeg lookup can have already pinned to "not found" before we
    # run at startup.
    exe = None
    for c in _ffmpeg_candidates("ffmpeg"):
        if os.path.isfile(c):
            exe = c
            break
    if exe is None:
        exe = _imageio_ffmpeg_exe()
    if not exe:
        return
    plain = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    # A normally-named binary in a real directory (a winget/scoop/Program Files
    # install, or a system ffmpeg): just put that directory on PATH -- bare
    # ``ffmpeg`` probes resolve it and ffprobe sits alongside it.
    if os.path.basename(exe).lower() == plain:
        os.environ["PATH"] = (os.path.dirname(exe) + os.pathsep
                              + os.environ.get("PATH", ""))
        return
    # A version-stamped imageio binary: symlink (or copy) it to a temp dir as
    # ``ffmpeg`` and prepend that dir, so the plain name resolves.
    import tempfile
    link_dir = tempfile.mkdtemp(prefix="pad-ffmpeg-")
    link = os.path.join(link_dir, plain)
    try:
        os.symlink(exe, link)
    except (OSError, NotImplementedError, AttributeError):
        # Symlinks may be unavailable (Windows without privilege); copy.
        try:
            shutil.copy2(exe, link)
        except OSError:
            return
    os.environ["PATH"] = link_dir + os.pathsep + os.environ.get("PATH", "")


# ---------------------------------------------------------------------------
# Audio metadata detection
# ---------------------------------------------------------------------------

class AudioInfo:
    """Metadata for an audio file."""

    def __init__(self, path, codec="unknown", channels=0, sample_rate=0,
                 bit_depth=0, duration=0.0, bitrate=0, compressed=False):
        self.path = path
        self.codec = codec          # "pcm", "adpcm", "ogg_vorbis", etc.
        self.channels = channels
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth  # 0 for compressed formats
        self.duration = duration    # seconds
        self.bitrate = bitrate      # bits/sec (for OGG)
        self.compressed = compressed  # True for non-PCM WAV

    def __repr__(self):
        return (f"AudioInfo({self.codec}, {self.channels}ch, "
                f"{self.sample_rate}Hz, {self.bit_depth}bit, "
                f"{self.duration:.2f}s)")


def detect_audio_info(path):
    """Detect audio format metadata from a WAV or OGG file.

    Returns AudioInfo, or None if the file format is unrecognized.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".wav":
        return _parse_wav_info(path)
    elif ext == ".ogg":
        return _parse_ogg_info(path)

    return None


def _parse_wav_info(path):
    """Parse WAV header to extract format metadata."""
    try:
        with open(path, "rb") as f:
            riff = f.read(12)
            if len(riff) < 12 or riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
                return None

            # Walk chunks to find fmt and data
            fmt_data = None
            data_size = 0
            while True:
                chunk_hdr = f.read(8)
                if len(chunk_hdr) < 8:
                    break
                chunk_id = chunk_hdr[:4]
                chunk_size = struct.unpack("<I", chunk_hdr[4:8])[0]

                if chunk_id == b"fmt ":
                    fmt_data = f.read(chunk_size)
                    if chunk_size % 2:
                        f.read(1)  # padding byte
                elif chunk_id == b"data":
                    data_size = chunk_size
                    break  # don't need to read the actual data
                else:
                    f.seek(chunk_size + (chunk_size % 2), 1)

            if fmt_data is None or len(fmt_data) < 16:
                return None

            audio_fmt = struct.unpack("<H", fmt_data[0:2])[0]
            channels = struct.unpack("<H", fmt_data[2:4])[0]
            sample_rate = struct.unpack("<I", fmt_data[4:8])[0]
            # byte_rate = struct.unpack("<I", fmt_data[8:12])[0]
            # block_align = struct.unpack("<H", fmt_data[12:14])[0]
            bit_depth = struct.unpack("<H", fmt_data[14:16])[0]

            # PCM = 1, IEEE float = 3, ADPCM = 2, etc.
            compressed = audio_fmt not in (1, 3)
            codec = "pcm"
            if audio_fmt == 3:
                codec = "ieee_float"
            elif audio_fmt == 2:
                codec = "adpcm"
            elif audio_fmt == 0x55:
                codec = "mp3"
            elif compressed:
                codec = f"wav_fmt_{audio_fmt}"

            # Calculate duration
            if channels > 0 and sample_rate > 0 and bit_depth > 0:
                bytes_per_sample = bit_depth // 8
                if bytes_per_sample > 0 and channels > 0:
                    total_frames = data_size // (bytes_per_sample * channels)
                    duration = total_frames / sample_rate
                else:
                    duration = 0.0
            else:
                duration = 0.0

            return AudioInfo(
                path=path, codec=codec, channels=channels,
                sample_rate=sample_rate, bit_depth=bit_depth,
                duration=duration, compressed=compressed)

    except (OSError, struct.error):
        return None


def _parse_ogg_info(path):
    """Parse OGG Vorbis identification header for metadata."""
    try:
        with open(path, "rb") as f:
            # Read first OGG page
            magic = f.read(4)
            if magic != b"OggS":
                return None

            f.seek(0)
            page_data = f.read(8192)

            # Find Vorbis identification header (starts with \x01vorbis)
            idx = page_data.find(b"\x01vorbis")
            if idx == -1:
                return None

            hdr = page_data[idx:]
            if len(hdr) < 30:
                return None

            # Parse identification header
            # \x01 + "vorbis" + version(4) + channels(1) + sample_rate(4)
            # + bitrate_max(4) + bitrate_nominal(4) + bitrate_min(4) + ...
            channels = hdr[11]
            sample_rate = struct.unpack("<I", hdr[12:16])[0]
            # bitrate_max = struct.unpack("<i", hdr[16:20])[0]
            bitrate_nominal = struct.unpack("<i", hdr[20:24])[0]
            # bitrate_min = struct.unpack("<i", hdr[24:28])[0]

            # Get duration via ffprobe if available, otherwise estimate from file size
            duration = _get_ogg_duration(path, sample_rate)

            return AudioInfo(
                path=path, codec="ogg_vorbis", channels=channels,
                sample_rate=sample_rate, bit_depth=0,
                duration=duration, bitrate=bitrate_nominal)

    except (OSError, struct.error):
        return None


def _get_ogg_duration(path, sample_rate):
    """Get OGG duration by reading the last granule position."""
    try:
        file_size = os.path.getsize(path)
        with open(path, "rb") as f:
            # Read last 64KB to find the final OGG page
            seek_back = min(65536, file_size)
            f.seek(file_size - seek_back)
            tail = f.read()

            # Find last OggS sync
            last_page = tail.rfind(b"OggS")
            if last_page == -1:
                return 0.0

            page = tail[last_page:]
            if len(page) < 14:
                return 0.0

            # Granule position at offset 6 (8 bytes, little-endian)
            granule = struct.unpack("<q", page[6:14])[0]
            if granule > 0 and sample_rate > 0:
                return granule / sample_rate

    except (OSError, struct.error):
        pass
    return 0.0


# ---------------------------------------------------------------------------
# WAV processing (pure Python)
# ---------------------------------------------------------------------------

def trim_wav(path, target_duration):
    """Trim a WAV file to target_duration seconds (in-place).

    Only works on PCM WAV files. Returns True if trimmed.
    """
    info = _parse_wav_info(path)
    if info is None or info.compressed:
        return False

    if info.duration <= target_duration + 0.01:
        return False  # Already short enough

    bytes_per_sample = info.bit_depth // 8
    block_align = bytes_per_sample * info.channels
    target_frames = int(target_duration * info.sample_rate)
    target_data_size = target_frames * block_align

    # Re-read and rewrite the file
    with open(path, "rb") as f:
        riff = f.read(12)
        chunks_before_data = bytearray()
        data_start = None

        while True:
            chunk_hdr = f.read(8)
            if len(chunk_hdr) < 8:
                break
            chunk_id = chunk_hdr[:4]
            chunk_size = struct.unpack("<I", chunk_hdr[4:8])[0]

            if chunk_id == b"data":
                data_content = f.read(min(target_data_size, chunk_size))
                break
            else:
                chunk_content = f.read(chunk_size)
                if chunk_size % 2:
                    f.read(1)
                chunks_before_data.extend(chunk_hdr)
                chunks_before_data.extend(chunk_content)

    # Write truncated file
    new_riff_size = 4 + len(chunks_before_data) + 8 + target_data_size
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", new_riff_size))
        f.write(b"WAVE")
        f.write(chunks_before_data)
        f.write(b"data")
        f.write(struct.pack("<I", target_data_size))
        f.write(data_content)
        # Pad with silence if we didn't have enough data
        remaining = target_data_size - len(data_content)
        if remaining > 0:
            f.write(b"\x00" * remaining)

    return True


def pad_wav(path, target_duration):
    """Pad a WAV file with silence to reach target_duration seconds (in-place).

    Only works on PCM WAV files. Returns True if padded.
    """
    info = _parse_wav_info(path)
    if info is None or info.compressed:
        return False

    if info.duration >= target_duration - 0.01:
        return False  # Already long enough

    bytes_per_sample = info.bit_depth // 8
    block_align = bytes_per_sample * info.channels
    target_frames = int(target_duration * info.sample_rate)
    current_frames = int(info.duration * info.sample_rate)
    pad_frames = target_frames - current_frames

    if pad_frames <= 0:
        return False

    pad_bytes = pad_frames * block_align

    # Silence value depends on bit depth
    if info.bit_depth == 8:
        silence = b"\x80" * pad_bytes  # 8-bit WAV is unsigned
    else:
        silence = b"\x00" * pad_bytes  # 16/24/32-bit is signed

    # Read entire file, append silence to data chunk, rewrite
    with open(path, "rb") as f:
        content = f.read()

    # Find data chunk
    idx = content.find(b"data")
    if idx == -1:
        return False

    data_size_offset = idx + 4
    old_data_size = struct.unpack("<I", content[data_size_offset:data_size_offset + 4])[0]
    new_data_size = old_data_size + pad_bytes

    # Update data chunk size
    new_content = bytearray(content)
    new_content[data_size_offset:data_size_offset + 4] = struct.pack("<I", new_data_size)

    # Update RIFF size
    new_riff_size = len(new_content) - 8 + pad_bytes
    new_content[4:8] = struct.pack("<I", new_riff_size)

    with open(path, "wb") as f:
        f.write(new_content)
        f.write(silence)

    return True


def convert_wav_channels(path, target_channels):
    """Convert WAV between mono and stereo (in-place, pure Python).

    Returns True if converted.
    """
    info = _parse_wav_info(path)
    if info is None or info.compressed:
        return False
    if info.channels == target_channels:
        return False

    bytes_per_sample = info.bit_depth // 8

    with open(path, "rb") as f:
        content = f.read()

    # Find data chunk
    data_idx = content.find(b"data")
    if data_idx == -1:
        return False

    data_offset = data_idx + 8
    data_size = struct.unpack("<I", content[data_idx + 4:data_idx + 8])[0]
    raw_data = content[data_offset:data_offset + data_size]

    if info.channels == 1 and target_channels == 2:
        # Mono to stereo: duplicate each sample
        new_data = bytearray()
        for i in range(0, len(raw_data), bytes_per_sample):
            sample = raw_data[i:i + bytes_per_sample]
            new_data.extend(sample)
            new_data.extend(sample)
    elif info.channels == 2 and target_channels == 1:
        # Stereo to mono: average left and right
        new_data = bytearray()
        frame_size = bytes_per_sample * 2
        for i in range(0, len(raw_data), frame_size):
            if info.bit_depth == 8:
                # Unsigned 8-bit
                l = raw_data[i]
                r = raw_data[i + 1] if i + 1 < len(raw_data) else 128
                new_data.append((l + r) // 2)
            elif info.bit_depth == 16:
                l = struct.unpack("<h", raw_data[i:i + 2])[0]
                r = struct.unpack("<h", raw_data[i + 2:i + 4])[0]
                new_data.extend(struct.pack("<h", (l + r) // 2))
            elif info.bit_depth == 24:
                l = int.from_bytes(raw_data[i:i + 3], "little", signed=True)
                r = int.from_bytes(raw_data[i + 3:i + 6], "little", signed=True)
                avg = (l + r) // 2
                new_data.extend(avg.to_bytes(3, "little", signed=True))
            elif info.bit_depth == 32:
                l = struct.unpack("<i", raw_data[i:i + 4])[0]
                r = struct.unpack("<i", raw_data[i + 4:i + 8])[0]
                new_data.extend(struct.pack("<i", (l + r) // 2))
    elif info.channels > 2 and target_channels <= 2:
        # Multi-channel downmix to mono/stereo via ffmpeg
        return _ffmpeg_convert_wav(path, info, target_channels=target_channels)
    else:
        return False

    new_data_size = len(new_data)
    block_align = bytes_per_sample * target_channels
    byte_rate = info.sample_rate * block_align

    # Rebuild the file: update fmt chunk and data chunk
    result = bytearray()
    result.extend(b"RIFF")
    result.extend(b"\x00\x00\x00\x00")  # placeholder
    result.extend(b"WAVE")

    # fmt chunk
    result.extend(b"fmt ")
    result.extend(struct.pack("<I", 16))
    result.extend(struct.pack("<H", 1))  # PCM
    result.extend(struct.pack("<H", target_channels))
    result.extend(struct.pack("<I", info.sample_rate))
    result.extend(struct.pack("<I", byte_rate))
    result.extend(struct.pack("<H", block_align))
    result.extend(struct.pack("<H", info.bit_depth))

    # data chunk
    result.extend(b"data")
    result.extend(struct.pack("<I", new_data_size))
    result.extend(new_data)

    # Update RIFF size
    struct.pack_into("<I", result, 4, len(result) - 8)

    with open(path, "wb") as f:
        f.write(result)

    return True


def convert_wav_bit_depth(path, target_bit_depth):
    """Convert WAV bit depth (8/16/24/32) in-place, pure Python.

    Returns True if converted.
    """
    info = _parse_wav_info(path)
    if info is None or info.compressed:
        return False
    if info.bit_depth == target_bit_depth:
        return False

    src_bps = info.bit_depth // 8
    dst_bps = target_bit_depth // 8

    with open(path, "rb") as f:
        content = f.read()

    data_idx = content.find(b"data")
    if data_idx == -1:
        return False

    data_offset = data_idx + 8
    data_size = struct.unpack("<I", content[data_idx + 4:data_idx + 8])[0]
    raw_data = content[data_offset:data_offset + data_size]

    new_data = bytearray()
    for i in range(0, len(raw_data), src_bps):
        sample_bytes = raw_data[i:i + src_bps]
        if len(sample_bytes) < src_bps:
            break

        # Read sample as normalized float (-1.0 to 1.0)
        if info.bit_depth == 8:
            val = (sample_bytes[0] - 128) / 128.0
        elif info.bit_depth == 16:
            val = struct.unpack("<h", sample_bytes)[0] / 32768.0
        elif info.bit_depth == 24:
            ival = int.from_bytes(sample_bytes, "little", signed=True)
            val = ival / 8388608.0
        elif info.bit_depth == 32:
            val = struct.unpack("<i", sample_bytes)[0] / 2147483648.0
        else:
            return False

        # Clamp
        val = max(-1.0, min(1.0, val))

        # Write to target depth
        if target_bit_depth == 8:
            new_data.append(int(val * 127 + 128) & 0xFF)
        elif target_bit_depth == 16:
            new_data.extend(struct.pack("<h", int(val * 32767)))
        elif target_bit_depth == 24:
            ival = int(val * 8388607)
            new_data.extend(ival.to_bytes(3, "little", signed=True))
        elif target_bit_depth == 32:
            new_data.extend(struct.pack("<i", int(val * 2147483647)))

    new_data_size = len(new_data)
    block_align = dst_bps * info.channels
    byte_rate = info.sample_rate * block_align

    # Rebuild file
    result = bytearray()
    result.extend(b"RIFF")
    result.extend(b"\x00\x00\x00\x00")
    result.extend(b"WAVE")

    result.extend(b"fmt ")
    result.extend(struct.pack("<I", 16))
    result.extend(struct.pack("<H", 1))  # PCM
    result.extend(struct.pack("<H", info.channels))
    result.extend(struct.pack("<I", info.sample_rate))
    result.extend(struct.pack("<I", byte_rate))
    result.extend(struct.pack("<H", block_align))
    result.extend(struct.pack("<H", target_bit_depth))

    result.extend(b"data")
    result.extend(struct.pack("<I", new_data_size))
    result.extend(new_data)

    struct.pack_into("<I", result, 4, len(result) - 8)

    with open(path, "wb") as f:
        f.write(result)

    return True


# ---------------------------------------------------------------------------
# ffmpeg-based processing
# ---------------------------------------------------------------------------

def _ffmpeg_convert_wav(path, info, target_channels=None, target_sample_rate=None,
                        target_bit_depth=None):
    """Convert a WAV file using ffmpeg (for compressed WAV or resampling)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False

    tmp = path + ".tmp.wav"
    cmd = [ffmpeg, "-y", "-i", path]

    if target_channels:
        cmd.extend(["-ac", str(target_channels)])
    if target_sample_rate:
        cmd.extend(["-ar", str(target_sample_rate)])
    if target_bit_depth:
        codec_map = {8: "pcm_u8", 16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}
        cmd.extend(["-acodec", codec_map.get(target_bit_depth, "pcm_s16le")])
    else:
        # Default to PCM output
        bps = info.bit_depth if info.bit_depth in (8, 16, 24, 32) else 16
        codec_map = {8: "pcm_u8", 16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}
        cmd.extend(["-acodec", codec_map.get(bps, "pcm_s16le")])

    cmd.append(tmp)

    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=120,
            creationflags=_CREATE_FLAGS)
        if result.returncode == 0 and os.path.isfile(tmp):
            os.replace(tmp, path)
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return False


def _ffmpeg_get_duration(path):
    """Get audio duration via ffprobe."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return 0.0

    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries",
             "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
            creationflags=_CREATE_FLAGS)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return 0.0


def trim_ogg(path, target_duration):
    """Trim an OGG file to target_duration using ffmpeg. Returns True if trimmed."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False

    info = _parse_ogg_info(path)
    if info is None:
        return False

    if info.duration <= target_duration + 0.05:
        return False

    tmp = path + ".tmp.ogg"
    cmd = [ffmpeg, "-y", "-i", path, "-t", f"{target_duration:.3f}",
           "-acodec", "libvorbis"]

    if info.bitrate > 0:
        cmd.extend(["-b:a", str(info.bitrate)])
    cmd.extend(["-ac", str(info.channels), "-ar", str(info.sample_rate)])
    cmd.append(tmp)

    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=120,
            creationflags=_CREATE_FLAGS)
        if result.returncode == 0 and os.path.isfile(tmp):
            os.replace(tmp, path)
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return False


def pad_ogg(path, target_duration):
    """Pad an OGG file with silence to reach target_duration using ffmpeg."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False

    info = _parse_ogg_info(path)
    if info is None:
        return False

    if info.duration >= target_duration - 0.05:
        return False

    pad_seconds = target_duration - info.duration
    tmp = path + ".tmp.ogg"

    # Use anullsrc filter to generate silence and concatenate
    cmd = [
        ffmpeg, "-y",
        "-i", path,
        "-f", "lavfi", "-t", f"{pad_seconds:.3f}",
        "-i", f"anullsrc=r={info.sample_rate}:cl={'stereo' if info.channels >= 2 else 'mono'}",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
        "-acodec", "libvorbis",
    ]
    if info.bitrate > 0:
        cmd.extend(["-b:a", str(info.bitrate)])
    cmd.append(tmp)

    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=120,
            creationflags=_CREATE_FLAGS)
        if result.returncode == 0 and os.path.isfile(tmp):
            os.replace(tmp, path)
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return False


def convert_ogg(path, target_channels=None, target_sample_rate=None,
                target_bitrate=None):
    """Re-encode an OGG file to match target format parameters."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False

    tmp = path + ".tmp.ogg"
    cmd = [ffmpeg, "-y", "-i", path, "-acodec", "libvorbis"]

    if target_channels:
        cmd.extend(["-ac", str(target_channels)])
    if target_sample_rate:
        cmd.extend(["-ar", str(target_sample_rate)])
    if target_bitrate:
        cmd.extend(["-b:a", str(target_bitrate)])

    cmd.append(tmp)

    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=120,
            creationflags=_CREATE_FLAGS)
        if result.returncode == 0 and os.path.isfile(tmp):
            os.replace(tmp, path)
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return False


# ---------------------------------------------------------------------------
# High-level: process a replacement audio file
# ---------------------------------------------------------------------------

def process_modified_audio(replacement_path, original_info, keep_original_length=False):
    """Process a modified audio file to match the original's format.

    Performs (as needed):
      1. Compressed WAV → PCM WAV conversion (via ffmpeg)
      2. Channel count conversion
      3. Sample rate conversion (via ffmpeg)
      4. Bit depth conversion
      5. Duration matching (trim or pad) — unless keep_original_length is True

    Args:
        replacement_path: Path to the replacement file (modified in-place).
        original_info: AudioInfo of the original file.
        keep_original_length: If True, skip duration matching.

    Returns:
        List of action strings describing what was done (empty if nothing).
    """
    if original_info is None:
        return []

    ext = os.path.splitext(replacement_path)[1].lower()
    actions = []

    if ext == ".wav":
        actions.extend(_process_wav(replacement_path, original_info, keep_original_length))
    elif ext == ".ogg":
        actions.extend(_process_ogg(replacement_path, original_info, keep_original_length))

    return actions


def _process_wav(path, original, keep_length):
    """Process a replacement WAV file."""
    actions = []
    info = _parse_wav_info(path)
    if info is None:
        return actions

    # 1. Compressed WAV → PCM
    if info.compressed:
        if _ffmpeg_convert_wav(path, info):
            actions.append(f"converted {info.codec} to PCM")
            info = _parse_wav_info(path)
            if info is None:
                return actions

    # 2. Channel conversion
    if info.channels != original.channels and original.channels > 0:
        if convert_wav_channels(path, original.channels):
            actions.append(f"{info.channels}ch → {original.channels}ch")
            info = _parse_wav_info(path)
            if info is None:
                return actions

    # 3. Sample rate conversion (requires ffmpeg)
    if info.sample_rate != original.sample_rate and original.sample_rate > 0:
        if _ffmpeg_convert_wav(path, info, target_sample_rate=original.sample_rate):
            actions.append(f"{info.sample_rate}Hz → {original.sample_rate}Hz")
            info = _parse_wav_info(path)
            if info is None:
                return actions

    # 4. Bit depth conversion
    if info.bit_depth != original.bit_depth and original.bit_depth > 0:
        if convert_wav_bit_depth(path, original.bit_depth):
            actions.append(f"{info.bit_depth}bit → {original.bit_depth}bit")

    # 5. Duration matching
    if not keep_length and original.duration > 0:
        info = _parse_wav_info(path)
        if info and info.duration > original.duration + 0.01:
            if trim_wav(path, original.duration):
                actions.append(f"trimmed {info.duration:.1f}s → {original.duration:.1f}s")
        elif info and info.duration < original.duration - 0.01:
            if pad_wav(path, original.duration):
                actions.append(f"padded {info.duration:.1f}s → {original.duration:.1f}s")

    return actions


def _process_ogg(path, original, keep_length):
    """Process a replacement OGG file."""
    actions = []
    info = _parse_ogg_info(path)
    if info is None:
        return actions

    needs_convert = False
    kwargs = {}

    # Check format differences
    if info.channels != original.channels and original.channels > 0:
        kwargs["target_channels"] = original.channels
        needs_convert = True

    if info.sample_rate != original.sample_rate and original.sample_rate > 0:
        kwargs["target_sample_rate"] = original.sample_rate
        needs_convert = True

    if original.bitrate > 0 and info.bitrate > 0:
        # Only re-encode for bitrate if significantly different (>50%)
        ratio = info.bitrate / original.bitrate if original.bitrate else 1
        if ratio < 0.5 or ratio > 2.0:
            kwargs["target_bitrate"] = original.bitrate
            needs_convert = True

    if needs_convert:
        if convert_ogg(path, **kwargs):
            parts = []
            if "target_channels" in kwargs:
                parts.append(f"{info.channels}ch → {kwargs['target_channels']}ch")
            if "target_sample_rate" in kwargs:
                parts.append(f"{info.sample_rate}Hz → {kwargs['target_sample_rate']}Hz")
            if "target_bitrate" in kwargs:
                parts.append(f"bitrate adjusted")
            actions.append(", ".join(parts))

    # Duration matching
    if not keep_length and original.duration > 0:
        info = _parse_ogg_info(path)
        if info and info.duration > original.duration + 0.05:
            if trim_ogg(path, original.duration):
                actions.append(f"trimmed {info.duration:.1f}s → {original.duration:.1f}s")
        elif info and info.duration < original.duration - 0.05:
            if pad_ogg(path, original.duration):
                actions.append(f"padded {info.duration:.1f}s → {original.duration:.1f}s")

    return actions


# ---------------------------------------------------------------------------
# Transcoding arbitrary input -> the original's container/codec
# ---------------------------------------------------------------------------

def transcode_to(src_path, dst_path, original_info):
    """Transcode *src_path* (any audio format ffmpeg understands) into
    *dst_path*, whose extension (.wav / .ogg) selects the output codec.

    Channels / sample rate (and OGG bitrate) are matched to
    *original_info* up front so the result already resembles the slot
    it's replacing; :func:`process_modified_audio` then fine-tunes bit
    depth and duration.  Returns True on success.

    Requires ffmpeg.  The replace-audio flow uses this so users can drop
    in an .mp3 / .flac / .m4a and still get a file in the game's native
    format — they no longer have to pre-convert by hand.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False

    ext = os.path.splitext(dst_path)[1].lower()
    cmd = [ffmpeg, "-y", "-i", src_path]

    if original_info is not None and original_info.channels > 0:
        cmd.extend(["-ac", str(original_info.channels)])
    if original_info is not None and original_info.sample_rate > 0:
        cmd.extend(["-ar", str(original_info.sample_rate)])

    if ext == ".ogg":
        cmd.extend(["-acodec", "libvorbis"])
        if original_info is not None and original_info.bitrate > 0:
            cmd.extend(["-b:a", str(original_info.bitrate)])
    elif ext == ".wav":
        depth = (original_info.bit_depth
                 if original_info is not None
                 and original_info.bit_depth in (8, 16, 24, 32) else 16)
        codec_map = {8: "pcm_u8", 16: "pcm_s16le",
                     24: "pcm_s24le", 32: "pcm_s32le"}
        cmd.extend(["-acodec", codec_map[depth]])
    else:
        return False

    cmd.append(dst_path)

    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=300,
            creationflags=_CREATE_FLAGS)
        return result.returncode == 0 and os.path.isfile(dst_path)
    except (subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Playback (preview) — ffplay
# ---------------------------------------------------------------------------

_ffplay_path = None


def find_ffplay():
    """Find the ffplay executable (ships alongside ffmpeg)."""
    global _ffplay_path
    if _ffplay_path is not None:
        return _ffplay_path if _ffplay_path else None

    path = shutil.which("ffplay")
    if path:
        _ffplay_path = path
        return path

    # Try the same directory as ffmpeg (the usual case for bundled builds).
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        d = os.path.dirname(ffmpeg)
        ext = ".exe" if sys.platform == "win32" else ""
        cand = os.path.join(d, f"ffplay{ext}")
        if os.path.isfile(cand):
            _ffplay_path = cand
            return cand

    _ffplay_path = ""
    return None


def play_audio_file(path, start=0.0):
    """Start playing *path* in the background, no window.

    Prefers ffplay, which honors the *start* seek offset (seconds) used by
    the Replace-Audio preview's seek bar.  When ffplay isn't available -- the
    frozen macOS/Linux apps bundle ffmpeg but not ffplay -- falls back to the
    OS-native player (afplay / aplay / paplay), which plays from the start and
    ignores *start* (no seek).  Returns the ``subprocess.Popen`` handle (so
    the caller can stop it) or ``None`` if nothing can play the file.  The
    caller terminates a previous handle before starting a new one.
    """
    if not path or not os.path.isfile(path):
        return None
    ffplay = find_ffplay()
    if ffplay:
        cmd = [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet"]
        if start and start > 0.05:
            # -ss before -i: fast input seek, accurate enough for audio preview.
            cmd += ["-ss", f"{start:.3f}"]
        cmd.append(path)
        try:
            return subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_FLAGS)
        except OSError:
            pass
    # No ffplay (the frozen macOS/Linux apps bundle ffmpeg but not ffplay --
    # static ffplay builds are unreliable) -> fall back to the OS-native
    # player.  These don't seek, so playback starts from the beginning; the
    # *start* offset is ignored.
    native = _native_audio_player(path)
    if native:
        try:
            return subprocess.Popen(
                native,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_FLAGS)
        except OSError:
            return None
    return None


def _native_audio_player(path):
    """Command list for the OS built-in audio player, or None.

    The preview fallback when ffplay isn't available.  macOS always ships
    ``afplay``; most Linux desktops have ``paplay`` or ``aplay``.  None of
    these seek, so playback always starts from the beginning."""
    if sys.platform == "darwin":
        for cand in (shutil.which("afplay"), "/usr/bin/afplay"):
            if cand and os.path.isfile(cand):
                return [cand, path]
    elif sys.platform.startswith("linux"):
        for name in ("paplay", "aplay"):
            exe = shutil.which(name)
            if exe:
                return [exe, path]
    return None


def probe_duration(path):
    """Best-effort total duration in seconds (via ffprobe), else 0.0."""
    if not path or not os.path.isfile(path):
        return 0.0
    return _ffmpeg_get_duration(path)


def render_spectrogram_png(path, width=700, height=90):
    """Render a full-track spectrogram of *path* to PNG bytes via ffmpeg.

    Returns the PNG bytes (decodable by Pillow) or ``None`` if ffmpeg is
    unavailable or the render fails.  Used as the seekable preview strip in
    the Replace-Audio tab — the whole track at a glance, no new dependency.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not path or not os.path.isfile(path):
        return None
    w = max(100, int(width))
    h = max(40, int(height))
    cmd = [
        ffmpeg, "-v", "error", "-i", path,
        "-lavfi",
        f"showspectrumpic=s={w}x{h}:legend=0:gain=3:color=intensity",
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60,
                           creationflags=_CREATE_FLAGS)
        if r.returncode == 0 and r.stdout[:8] == b"\x89PNG\r\n\x1a\n":
            return r.stdout
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def stop_audio(proc):
    """Terminate a playback handle from :func:`play_audio_file` (safe on None)."""
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
    except OSError:
        pass
