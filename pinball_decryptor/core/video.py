"""Video processing for replacement assets — probing, frame extraction,
embedded-preview frame streaming, and format-matched transcoding.

The Replace-Video GUI tab lets users swap a game's video files.  A
replacement of (almost) any format / resolution is matched to the slot it
replaces — container / codec, resolution, frame rate, alpha channel, and
optionally duration — then written over the original so the normal Write
pipeline repacks it.  This module is the ffmpeg layer beneath that:

  - Metadata detection via ffprobe (codec / WxH / fps / duration / alpha)
  - Single-frame extraction (poster frame + scrubbing the seek bar)
  - Raw RGB frame streaming for the in-app embedded player
  - Transcoding an arbitrary input into the slot's native format, scaled to
    the slot's resolution, preserving alpha when the slot has it (ProRes)

ffmpeg / ffprobe discovery (and the no-console-window flag) is shared with
:mod:`core.audio`, so installing ffmpeg once lights up both tabs.
"""

import json
import os
import re
import subprocess
import threading
import time

from .audio import (_CREATE_FLAGS, _ffmpeg_banner, find_ffmpeg, find_ffprobe,
                    parse_banner_duration, probe_duration)

# Video containers we treat as replaceable slots.
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".ogv", ".avi", ".mkv")

# Replacement inputs the user may drop in (we transcode the rest via ffmpeg).
REPLACEMENT_EXTS = VIDEO_EXTS + (
    ".mpg", ".mpeg", ".wmv", ".flv", ".ts", ".3gp", ".gif")

# pix_fmt names that carry an alpha channel — used to keep transparency when
# re-encoding (Dutch Pinball's AAIW ships ProRes 4444 .mov with alpha).
_ALPHA_PIX_FMTS = {
    "yuva420p", "yuva422p", "yuva444p", "yuva444p10le", "yuva444p12le",
    "yuva420p10le", "yuva422p10le", "rgba", "bgra", "argb", "abgr",
    "ya8", "ya16le", "pal8",
}


# ---------------------------------------------------------------------------
# Pluggable backends for non-ffmpeg containers
# ---------------------------------------------------------------------------
#
# Most video lives in containers ffmpeg/ffprobe handle directly.  A few games
# use a custom format ffmpeg can't read — Dutch Pinball's The Big Lebowski
# stores its colour-DMD clips as ``.cdmd``.  A plugin registers a backend for
# such an extension so the generic Replace-Video machinery (scan, info,
# embedded preview, staging) works unchanged.
#
# A backend is any object exposing these methods (all may return None to opt
# out of a given capability):
#   info(path)                      -> VideoInfo or None
#   frame_png(path, pos, w, h)      -> PNG bytes or None   (poster / scrub)
#   open_stream(path, w, h, fps, start) -> a Popen-like with .read()/.poll()/
#                                          .terminate() yielding rgb24 frames
#   audio_path(path)                -> a sibling audio file path or None
#   encode(src_path, dst_path, reference_path) -> (ok, detail)

_BACKENDS = {}


def register_backend(ext, backend):
    """Register *backend* to handle files with extension *ext* (e.g. ".cdmd")."""
    _BACKENDS[ext.lower()] = backend


def backend_for(path):
    """Return the registered backend for *path*'s extension, or None."""
    if not path:
        return None
    return _BACKENDS.get(os.path.splitext(path)[1].lower())


def backend_exts():
    """Tuple of all extensions a custom backend handles (e.g. ``(".cdmd",)``)."""
    return tuple(_BACKENDS.keys())


class GeneratorStream:
    """Adapt a Python generator of fixed-size rgb24 frame bytes to the small
    Popen-like surface the embedded player's decode thread expects
    (``.read(n)`` returns one frame, ``.poll()`` / ``.terminate()``)."""

    def __init__(self, gen):
        self._gen = gen
        self._stopped = False
        self.returncode = None
        self.stdout = self  # the worker reads from proc.stdout

    def read(self, _n):
        if self._stopped:
            return b""
        try:
            return next(self._gen)
        except StopIteration:
            self.returncode = 0
            return b""
        except Exception:
            self.returncode = 1
            return b""

    def poll(self):
        return self.returncode

    def terminate(self):
        self._stopped = True
        if self.returncode is None:
            self.returncode = 0


class VideoInfo:
    """Metadata for a video file (from ffprobe, or a custom backend)."""

    def __init__(self, path, vcodec="", width=0, height=0, fps=0.0,
                 duration=0.0, has_audio=False, has_alpha=False,
                 pix_fmt="", container="", nframes=0,
                 audio_rate=0, audio_channels=0, profile="", level=0):
        self.path = path
        self.vcodec = vcodec          # "h264", "vp9", "theora", "prores", …
        self.width = width
        self.height = height
        self.fps = fps                # frames per second (0.0 if unknown)
        self.duration = duration      # seconds
        self.has_audio = has_audio
        self.profile = profile        # "Main" / "High" / "Constrained Baseline"
        self.level = level            # H.264 level_idc x10 (31 == level 3.1)
        self.audio_rate = audio_rate          # Hz (0 = unknown)
        self.audio_channels = audio_channels  # 1 mono / 2 stereo (0 = unknown)
        self.has_alpha = has_alpha    # True for ProRes 4444 / VP9-alpha / …
        self.pix_fmt = pix_fmt
        self.container = container     # extension without the dot ("mp4")
        self.nframes = nframes         # frame count (custom backends; 0=unknown)

    def audio_summary(self):
        """Human audio-track summary — "44.1 kHz Stereo" — or "" for a silent
        clip and a bare "Audio" when the track exists but details didn't
        probe (custom backends, terse banners)."""
        if not self.has_audio:
            return ""
        parts = []
        if self.audio_rate:
            khz = self.audio_rate / 1000.0
            parts.append(("%g kHz" % round(khz, 1)))
        if self.audio_channels == 1:
            parts.append("Mono")
        elif self.audio_channels == 2:
            parts.append("Stereo")
        elif self.audio_channels > 2:
            parts.append("%dch" % self.audio_channels)
        return " ".join(parts) or "Audio"

    def __repr__(self):
        return (f"VideoInfo({self.vcodec}, {self.width}x{self.height}, "
                f"{self.fps:.2f}fps, {self.duration:.2f}s"
                f"{', alpha' if self.has_alpha else ''})")


def _parse_fps(rate):
    """Parse an ffprobe rate field like ``"30000/1001"`` into a float fps."""
    if not rate or rate in ("0/0", "N/A"):
        return 0.0
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den = float(den)
            return float(num) / den if den else 0.0
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return 0.0


def detect_video_info(path):
    """Detect video metadata via ffprobe, or ``None`` if unavailable.

    Returns a :class:`VideoInfo`.  Falls back gracefully (``None``) when
    ffprobe is missing or the file isn't a video ffprobe understands — the
    slot list still shows the file, just without dimensions.  Files handled by
    a registered custom backend (e.g. ``.cdmd``) are delegated to it.
    """
    backend = backend_for(path)
    if backend is not None:
        return backend.info(path)

    if not path or not os.path.isfile(path):
        return None
    ffprobe = find_ffprobe()
    if not ffprobe:
        # ffmpeg-only install (the frozen macOS/Linux apps bundle ffmpeg via
        # imageio-ffmpeg, whose wheel ships no ffprobe) -- parse the metadata
        # banner ``ffmpeg -i`` prints to stderr instead.
        return parse_video_banner(_ffmpeg_banner(path), path)
    try:
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=30,
            creationflags=_CREATE_FLAGS)
        if r.returncode != 0 or not r.stdout:
            return None
        data = json.loads(r.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None

    streams = data.get("streams", []) or []
    vstream = next((s for s in streams
                    if s.get("codec_type") == "video"), None)
    astream = next((s for s in streams
                    if s.get("codec_type") == "audio"), None)
    has_audio = astream is not None
    if vstream is None:
        return None

    pix_fmt = vstream.get("pix_fmt", "") or ""
    has_alpha = pix_fmt in _ALPHA_PIX_FMTS

    fps = _parse_fps(vstream.get("avg_frame_rate")
                     or vstream.get("r_frame_rate"))
    fmt = data.get("format", {}) or {}
    try:
        dur = float(fmt.get("duration") or vstream.get("duration") or 0.0)
    except (ValueError, TypeError):
        dur = 0.0

    try:
        level = int(vstream.get("level", 0) or 0)
    except (TypeError, ValueError):
        level = 0

    return VideoInfo(
        path=path,
        vcodec=vstream.get("codec_name", "") or "",
        width=int(vstream.get("width", 0) or 0),
        height=int(vstream.get("height", 0) or 0),
        fps=fps,
        duration=dur,
        profile=vstream.get("profile", "") or "",
        level=level if level > 0 else 0,
        has_audio=has_audio,
        audio_rate=int((astream or {}).get("sample_rate", 0) or 0),
        audio_channels=int((astream or {}).get("channels", 0) or 0),
        has_alpha=has_alpha,
        pix_fmt=pix_fmt,
        container=os.path.splitext(path)[1].lstrip(".").lower(),
    )


# The video-stream line of an ffmpeg stderr banner, e.g.
#   Stream #0:0[0x1](und): Video: h264 (High) (avc1 / ...), yuv420p(tv,
#       bt709), 1920x1080 [SAR 1:1 DAR 16:9], 4276 kb/s, 29.97 fps, ...
_BANNER_VIDEO_RE = re.compile(r"Stream #[^\n]*?:\s*Video:\s*([^\n]+)")
_BANNER_SIZE_RE = re.compile(r",\s*(\d{2,5})x(\d{2,5})\b")
_BANNER_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s+fps")
_BANNER_TBR_RE = re.compile(r"(\d+(?:\.\d+)?)\s+tbr")


def parse_video_banner(text, path):
    """Build a :class:`VideoInfo` from an ffmpeg stderr banner, or ``None``
    when the banner has no video stream.  Fallback prober for ffmpeg-only
    installs (no ffprobe); the banner carries everything the slot list and
    the transcoder need — codec, pix_fmt, WxH, fps, duration, audio."""
    m = _BANNER_VIDEO_RE.search(text or "")
    if not m:
        return None
    line = m.group(1)
    # First comma-field is the codec chunk ("h264 (High) (avc1 / ...)"),
    # second is the pix_fmt ("yuv420p(tv, bt709, progressive)").
    fields = line.split(",")
    vcodec = fields[0].split()[0].strip() if fields[0].split() else ""
    # "h264 (Constrained Baseline) (avc1 / 0x31637661)" -> the FIRST
    # parenthesised group is the profile; the second is the container fourcc.
    pm = re.match(r"\s*[A-Za-z0-9_]+\s*\(([^)]+)\)", fields[0])
    profile = pm.group(1).strip() if pm else ""
    if profile.lower().startswith("0x") or "/" in profile:
        profile = ""              # that was the fourcc group, not a profile
    pix_fmt = ""
    if len(fields) > 1:
        pm = re.match(r"\s*([A-Za-z0-9]+)", fields[1])
        if pm:
            pix_fmt = pm.group(1)
    sm = _BANNER_SIZE_RE.search(line)
    fm = _BANNER_FPS_RE.search(line) or _BANNER_TBR_RE.search(line)
    return VideoInfo(
        path=path,
        vcodec=vcodec,
        width=int(sm.group(1)) if sm else 0,
        height=int(sm.group(2)) if sm else 0,
        fps=float(fm.group(1)) if fm else 0.0,
        duration=parse_banner_duration(text),
        profile=profile,
        has_audio=": Audio:" in (text or ""),
        audio_rate=_banner_audio_rate(text),
        audio_channels=_banner_audio_channels(text),
        has_alpha=pix_fmt in _ALPHA_PIX_FMTS,
        pix_fmt=pix_fmt,
        container=os.path.splitext(path)[1].lstrip(".").lower(),
    )


_BANNER_AUDIO_RE = re.compile(r"Stream #[^\n]*?:\s*Audio:\s*([^\n]+)")


def _banner_audio_rate(text):
    m = _BANNER_AUDIO_RE.search(text or "")
    if not m:
        return 0
    r = re.search(r"(\d{4,6})\s*Hz", m.group(1))
    return int(r.group(1)) if r else 0


def _banner_audio_channels(text):
    m = _BANNER_AUDIO_RE.search(text or "")
    if not m:
        return 0
    line = m.group(1).lower()
    if "mono" in line:
        return 1
    if "stereo" in line:
        return 2
    r = re.search(r"(\d+)\s+channels", line)
    if r:
        return int(r.group(1))
    if "5.1" in line:
        return 6
    return 0


def isobmff_brand(path):
    """The ISO-BMFF major brand of *path* (``b"isom"``, ``b"qt  "``, …), or
    ``None`` when the file isn't an MP4/QuickTime container at all.

    A 12-byte read, no ffmpeg — so a plugin can tell "this really is the same
    kind of container as the asset it's replacing" even on a machine with no
    ffmpeg installed.  Matches the ``ftyp`` sniff Extract uses to find the
    clips in the first place.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError:
        return None
    if len(head) < 12 or head[4:8] != b"ftyp":
        return None
    return head[8:12]


# ---------------------------------------------------------------------------
# Padding a clip to an exact byte size
#
# Some cards hold every asset at a fixed byte length: Stern patches video into
# the SD-card image in place, and JJP's scheme-3 titles read each asset's
# length out of a dongle-encrypted fl.dat that can be neither read nor
# rewritten.  A replacement therefore has to land on the slot's size to the
# byte, which sounds like it should cost quality — and doesn't, because both
# container formats carry a first-class "ignore these bytes" element for
# exactly this: an EBML ``Void`` for Matroska/WebM (the same one muxers write
# to reserve space for a SeekHead they will fill in later) and a ``free`` box
# for MP4/QuickTime.  Padding with those changes no frame at all.
#
# The EBML primitives are spelled out here rather than shared with
# jjp/crypto_v3.py, which needs its own copy: that module is also deployed
# flat into WSL/Docker as jjp_crypto_v3.py, where this package doesn't exist.
# ---------------------------------------------------------------------------

_EBML_MAGIC = b"\x1a\x45\xdf\xa3"
_EBML_SEGMENT_ID = b"\x18\x53\x80\x67"

_ISOBMFF_FIRST_BOXES = frozenset((b"ftyp", b"styp", b"moov", b"mdat", b"wide",
                                  b"free", b"skip", b"pnot"))


def _read_ebml_size(data, off):
    """``(value, length)`` of the EBML variable-length size at *off*; value is
    None for the "unknown size" encoding or an unreadable one."""
    if off >= len(data):
        return None, -1
    first = data[off]
    if first == 0:
        return None, -1
    n, mask = 1, 0x80
    while not first & mask:
        mask >>= 1
        n += 1
    if n > 8 or off + n > len(data):
        return None, -1
    unknown = (0x80 >> (n - 1)) - 1
    value = first & unknown
    for i in range(1, n):
        value = (value << 8) | data[off + i]
        unknown = (unknown << 8) | 0xFF
    return (None if value == unknown else value), n


def _ebml_vint(value, length):
    """*value* as an EBML variable-length integer of exactly *length* bytes."""
    return ((1 << (7 * length)) | value).to_bytes(length, "big")


def _ebml_void(total):
    """A ``Void`` element occupying exactly *total* bytes, or None when *total*
    can't hold one (0 needs no element; 1 has no legal encoding)."""
    for slen in range(1, 9):
        body = total - 1 - slen
        if body < 0:
            return None
        if body <= (1 << (7 * slen)) - 2:
            return b"\xec" + _ebml_vint(body, slen) + b"\x00" * body
    return None


def pad_matroska_to_size(data, target):
    """Pad a Matroska / WebM clip to exactly *target* bytes, or None.

    The slack goes in a ``Void`` at the end of the Segment.  Appending there
    moves nothing, so every SeekHead / Cues offset stays valid (they are all
    relative to the start of the Segment's data, so even widening the
    Segment's own size field is safe) — and the decoded frames are bit-for-bit
    what they were.
    """
    if not data.startswith(_EBML_MAGIC) or len(data) > target:
        return None
    hdr_size, hdr_len = _read_ebml_size(data, len(_EBML_MAGIC))
    if hdr_size is None:
        return None
    seg_off = len(_EBML_MAGIC) + hdr_len + hdr_size
    if data[seg_off:seg_off + 4] != _EBML_SEGMENT_ID:
        return None
    body_size, size_len = _read_ebml_size(data, seg_off + 4)
    if body_size is None:
        return None
    body_off = seg_off + 4 + size_len
    if body_off + body_size != len(data):
        return None            # something follows the Segment — don't guess
    head, body = data[:seg_off], data[body_off:]
    # Try the width the size field already has, so the payload doesn't move at
    # all; widen to the maximum only if the bigger Segment won't fit in it.
    for slen in (size_len, 8):
        void_len = target - len(head) - 4 - slen - body_size
        if void_len < 0 or void_len == 1:
            continue           # 1 byte can't carry an element header
        if body_size + void_len > (1 << (7 * slen)) - 2:
            continue
        void = b"" if void_len == 0 else _ebml_void(void_len)
        if void_len and void is None:
            continue
        out = (head + _EBML_SEGMENT_ID + _ebml_vint(body_size + void_len, slen)
               + body + void)
        if len(out) == target:
            return out
    return None


def pad_isobmff_to_size(data, target):
    """Pad an MP4 / QuickTime clip to exactly *target* bytes with a trailing
    ``free`` box, which compliant demuxers skip — ``moov`` / ``mdat`` are left
    untouched.  Returns None when *data* already overshoots."""
    pad = target - len(data)
    if pad < 0:
        return None
    if pad == 0:
        return data
    if pad < 8:
        # No room for a box header; a few bytes after the last complete box
        # are where a demuxer stops anyway.
        return data + b"\x00" * pad
    if pad < 0x1_0000_0000:
        return data + pad.to_bytes(4, "big") + b"free" + b"\x00" * (pad - 8)
    # 64-bit box: the size word is 1 and the real size follows the type.
    return (data + (1).to_bytes(4, "big") + b"free"
            + pad.to_bytes(8, "big") + b"\x00" * (pad - 16))


def pad_video_to_size(data, target):
    """Return *data* padded to exactly *target* bytes without changing a frame,
    or None when it isn't a container we can pad (or already overshoots)."""
    if len(data) > target:
        return None
    if data.startswith(_EBML_MAGIC):
        return pad_matroska_to_size(data, target)
    if len(data) >= 8 and data[4:8] in _ISOBMFF_FIRST_BOXES:
        return pad_isobmff_to_size(data, target)
    return None


# 8-bit 4:2:0 — the only pixel format an embedded H.264 decoder is guaranteed
# to handle (yuvj420p is the same layout with full-range flags).
SAFE_PIX_FMTS = {"yuv420p", "yuvj420p", ""}


def same_pix_fmt(a, b):
    """Whether two pixel formats are interchangeable to a hardware decoder.

    The 8-bit 4:2:0 family is one format as far as the machine is concerned
    (``yuv420p`` and ``yuvj420p`` are the same layout with different range
    flags, and ``""`` is "we couldn't read it"); anything else — 10-bit, 4:2:2,
    4:4:4 — has to match the slot's own clip exactly, because that clip is the
    only proof of what the decoder accepts.
    """
    a, b = (a or ""), (b or "")
    if a in SAFE_PIX_FMTS and b in SAFE_PIX_FMTS:
        return True
    return a == b


def probe_video_duration(path):
    """Best-effort total duration in seconds (via ffprobe), else 0.0."""
    return probe_duration(path)


def extract_frame_png(path, pos, width, height):
    """Render the single frame at *pos* seconds of *path* to PNG bytes.

    Scaled to fit *width* x *height* (aspect preserved, the scale filter uses
    ``force_original_aspect_ratio=decrease``).  Returns PNG bytes decodable by
    Pillow, or ``None`` when ffmpeg is unavailable / the render fails.  Used
    for the poster frame and for scrubbing the seek bar while paused.
    """
    backend = backend_for(path)
    if backend is not None:
        return backend.frame_png(path, pos, width, height)

    ffmpeg = find_ffmpeg()
    if not ffmpeg or not path or not os.path.isfile(path):
        return None
    w = max(16, int(width))
    h = max(16, int(height))
    cmd = [ffmpeg, "-v", "error"]
    if pos and pos > 0.05:
        cmd += ["-ss", f"{pos:.3f}"]
    cmd += [
        "-i", path,
        "-frames:v", "1",
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease",
        "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30,
                           creationflags=_CREATE_FLAGS)
        if r.returncode == 0 and r.stdout[:8] == b"\x89PNG\r\n\x1a\n":
            return r.stdout
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def open_raw_stream(path, width, height, fps, start=0.0):
    """Open an ffmpeg process emitting raw ``rgb24`` frames of *width* x
    *height* at *fps*, beginning at *start* seconds.

    Returns the ``subprocess.Popen`` (read ``width*height*3`` bytes per frame
    from ``proc.stdout``) or ``None`` if ffmpeg is unavailable.  The embedded
    player's decode thread consumes this; the caller terminates the process to
    stop playback.  Custom-backend files return a :class:`GeneratorStream`
    wrapping the backend's Python frame generator (same read/poll/terminate
    surface), so the player treats both identically.
    """
    backend = backend_for(path)
    if backend is not None:
        return backend.open_stream(path, width, height, fps, start)

    ffmpeg = find_ffmpeg()
    if not ffmpeg or not path or not os.path.isfile(path):
        return None
    w = max(16, int(width))
    h = max(16, int(height))
    cmd = [ffmpeg, "-v", "error"]
    if start and start > 0.05:
        # -ss before -i: fast input seek, accurate enough for preview.
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path, "-an",
            "-vf", f"scale={w}:{h}",
            "-f", "rawvideo", "-pix_fmt", "rgb24"]
    if fps and fps > 0:
        cmd += ["-r", f"{fps:.4f}"]
    cmd.append("-")
    try:
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE,
            stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_CREATE_FLAGS)
    except OSError:
        return None


def play_video_windowed(path, start=0.0):
    """Play *path* (video + audio) in an ffplay window — the fallback used
    when Pillow is missing so there's no in-app frame canvas.  Returns the
    ``Popen`` handle or ``None`` when ffplay is unavailable."""
    from .audio import find_ffplay
    ffplay = find_ffplay()
    if not ffplay or not path or not os.path.isfile(path):
        return None
    cmd = [ffplay, "-autoexit", "-loglevel", "quiet"]
    if start and start > 0.05:
        cmd += ["-ss", f"{start:.3f}"]
    cmd.append(path)
    try:
        return subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=_CREATE_FLAGS)
    except OSError:
        return None


def audio_source_for(path):
    """Return the file whose audio track should accompany *path* during
    preview.  For ffmpeg-readable video that's the file itself; a custom
    backend may point at a sibling track (``.cdmd`` clips ship a ``.wav``)."""
    backend = backend_for(path)
    if backend is not None:
        ap = backend.audio_path(path)
        return ap if ap and os.path.isfile(ap) else None
    return path


# ---------------------------------------------------------------------------
# Transcoding arbitrary input -> the slot's container / codec / resolution
# ---------------------------------------------------------------------------

def encode_replacement(src_path, dst_path, slot_info, reference_path,
                       match_length=False):
    """Stage *src_path* into *dst_path* for a slot.

    Routes to a custom backend's encoder when the slot's format has one
    (``.cdmd``), else to the ffmpeg :func:`transcode_video_to` path.
    *reference_path* is the original slot file (the backend may read geometry /
    frame count from it).  Returns ``(ok, detail)``.
    """
    backend = backend_for(dst_path) or backend_for(reference_path)
    if backend is not None:
        return backend.encode(src_path, dst_path, reference_path)
    return transcode_video_to(src_path, dst_path, slot_info,
                              match_length=match_length)

# ffmpeg encoder flags per VIDEO CODEC — keyed by the ffprobe codec name of
# the clip already in the slot, because that clip is the only proof of what
# the machine's decoder accepts.  A container says far less than it looks
# like it does: .webm is VP8 *or* VP9, .mov is H.264 or ProRes, .mkv is
# anything at all.  Re-encoding a VP8 slot to VP9 because "webm means VP9"
# hands an embedded player a codec it may not have — and that failure looks
# exactly like the H.264-profile one this module already guards: the demuxer
# still finds the sound (which plays) while the picture stays black.
_ENCODERS = {
    # libvpx-vp9 at its defaults (cpu-used 1, single-threaded rows) encodes
    # long clips at a small fraction of realtime — a full-song 1360x768
    # video can take the better part of an hour.  good/4 with row
    # multithreading is several times faster at near-identical quality for
    # this material.  ``-row-mt`` is a VP9-only private option, so the VP8
    # encoder gets the two flags it does understand and no more.
    "h264":   (["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:a", "aac"]),
    "vp9":    (["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p",
                "-deadline", "good", "-cpu-used", "4", "-row-mt", "1"],
               ["-c:a", "libopus"]),
    "vp8":    (["-c:v", "libvpx", "-pix_fmt", "yuv420p",
                "-deadline", "good", "-cpu-used", "4"],
               ["-c:a", "libvorbis"]),
    "theora": (["-c:v", "libtheora", "-q:v", "7"], ["-c:a", "libvorbis"]),
    "mpeg4":  (["-c:v", "mpeg4", "-qscale:v", "3"], ["-c:a", "libmp3lame"]),
    "prores": (["-c:v", "prores_ks", "-profile:v", "3",
                "-pix_fmt", "yuv422p10le"], ["-c:a", "pcm_s16le"]),
}

# The encoder each codec is produced by — the same table, for callers that
# want the name rather than the flags (the "What this slot needs" recipe).
_ENCODER_NAMES = {c: v[0][1] for c, v in _ENCODERS.items()}

# What each container may legally hold.  A slot's codec is only copied when
# the output container can actually carry it; anything else falls back to the
# container's own default below.
_CONTAINER_CODECS = {
    ".mp4":  ("h264", "mpeg4"),
    ".m4v":  ("h264", "mpeg4"),
    ".mov":  ("h264", "prores", "mpeg4"),
    ".mkv":  ("h264", "vp9", "vp8", "theora", "mpeg4", "prores"),
    ".webm": ("vp9", "vp8"),
    ".ogv":  ("theora",),
    ".avi":  ("mpeg4",),
}

# Used when the slot's own clip was never probed (no ffmpeg/ffprobe on this
# machine, or a file it couldn't read) — the historical extension-picks-codec
# behaviour, which is right for every stock file we have ever seen.
_DEFAULT_CODEC = {
    ".mp4": "h264", ".m4v": "h264", ".mkv": "h264", ".mov": "h264",
    ".webm": "vp9", ".ogv": "theora", ".avi": "mpeg4",
}

# Alpha is carried by exactly one encoder per container, so a transparent
# slot's codec is decided by the container rather than by what it holds.
_ALPHA_CODEC_ARGS = {
    ".mov": (["-c:v", "prores_ks", "-profile:v", "4444",
              "-pix_fmt", "yuva444p10le"], ["-c:a", "pcm_s16le"]),
    ".webm": (["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
               "-deadline", "good", "-cpu-used", "4", "-row-mt", "1"],
              ["-c:a", "libopus"]),
}


def encoder_codec(ext, alpha=False, slot_codec=""):
    """Which codec a re-encode into *ext* should produce, or ``None`` when
    *ext* isn't a container we can write.

    *slot_codec* is the ffprobe codec name of the clip being replaced; it wins
    whenever *ext* can carry it, so a VP8 slot stays VP8 and a ProRes slot
    stays ProRes.  Unknown / unprobed / illegal-for-this-container falls back
    to the container's default.  Alpha slots are decided by the container (see
    :data:`_ALPHA_CODEC_ARGS`), so they report that codec instead.
    """
    default = _DEFAULT_CODEC.get(ext)
    if default is None:
        return None
    if alpha and ext in _ALPHA_CODEC_ARGS:
        return "prores" if ext == ".mov" else "vp9"
    codec = (slot_codec or "").strip().lower()
    if codec in _ENCODERS and codec in _CONTAINER_CODECS.get(ext, ()):
        return codec
    return default


def _video_codec_args(ext, alpha, slot_codec=""):
    """Return ``(video_args, audio_args)`` ffmpeg flags for output *ext*.

    The codec is :func:`encoder_codec`'s answer — the slot's own codec where
    the container can carry it, else the container's default; *alpha* keeps a
    transparency channel where the format supports it (ProRes 4444 for .mov,
    VP9-alpha for .webm).  Returns ``(None, None)`` for an unsupported ext.
    """
    codec = encoder_codec(ext, alpha, slot_codec)
    if codec is None:
        return (None, None)
    if alpha and ext in _ALPHA_CODEC_ARGS:
        vargs, aargs = _ALPHA_CODEC_ARGS[ext]
    else:
        vargs, aargs = _ENCODERS[codec]
    return (list(vargs), list(aargs))


def _is_vpx(vargs):
    """Whether *vargs* drives one of the libvpx encoders (VP8 or VP9), both
    of which need ``-crf`` + ``-b:v 0`` spelled out for constant quality."""
    return "libvpx" in vargs or "libvpx-vp9" in vargs


# ffprobe profile name -> the x264 ``-profile:v`` value that reproduces it.
# Anything not listed (High 10, High 4:2:2, …) has no 8-bit 4:2:0 equivalent,
# so we leave x264 on its own default rather than pinning something wrong.
_X264_PROFILES = {
    "baseline": "baseline",
    "constrained baseline": "baseline",
    "main": "main",
    "high": "high",
}


# The same profiles ordered lowest-first.  A decoder that plays a stream at
# one profile plays everything below it, so the clip already in the slot puts
# a CEILING on what a replacement may use: above it the stream still demuxes
# (the sound plays) and the picture stays black.
_PROFILE_RANK = {"baseline": 0, "constrained baseline": 0, "main": 1,
                 "high": 2}


def profile_rank(info):
    """Where *info*'s H.264 profile sits in :data:`_PROFILE_RANK`, or ``None``
    when it isn't H.264 or isn't a profile we can order (High 10, 4:2:2, …).
    ``None`` means "no opinion" — callers compare only when both sides rank."""
    if info is None or (info.vcodec or "").lower() != "h264":
        return None
    return _PROFILE_RANK.get((info.profile or "").strip().lower())


def _h264_profile_args(info, scaled_to_slot):
    """``-profile:v`` / ``-level`` flags reproducing *info*'s H.264 profile.

    The clip already on the card is proof of what the machine's decoder
    accepts, so an H.264 replacement is encoded to the *same* profile rather
    than to libx264's default (High).  Embedded players — Spike 2's i.MX6
    among them — commonly decode a lower profile only, and a stream above it
    demuxes fine (the sound plays) while the picture stays black.  The level
    is pinned only when the output keeps the slot's exact dimensions, since a
    level is a statement about resolution/bitrate limits.
    """
    if not info or (info.vcodec or "").lower() != "h264":
        return []
    prof = _X264_PROFILES.get((info.profile or "").strip().lower())
    if not prof:
        return []
    args = ["-profile:v", prof]
    if scaled_to_slot and info.level and 9 < info.level < 100:
        args += ["-level", "%.1f" % (info.level / 10.0)]
    return args


# How each container is named on the "What this slot needs" panel.  Every
# extension used to render as "MP4 (<ext>)", so a Spooky .ogv and a JJP .webm
# both read as MP4 — which is exactly the assumption that put an H.264 recipe
# under a WebM slot.
_CONTAINER_NAMES = {
    ".mov": "QuickTime (.mov)",
    ".mp4": "MP4 (.mp4)",
    ".m4v": "MP4 (.m4v)",
    ".mkv": "Matroska (.mkv)",
    ".webm": "WebM (.webm)",
    ".ogv": "Ogg (.ogv)",
    ".avi": "AVI (.avi)",
}


def dropin_spec(info, ext):
    """What a replacement must look like to go onto the card untouched, as an
    ordered ``[(label, value)]`` describing the clip already in the slot.

    The clip on the card is the only authority on what the machine's decoder
    accepts, so every line is read off *info* rather than asserted here.
    ``None`` when there is nothing probed to read.
    """
    if info is None:
        return None
    out = [("Container", _CONTAINER_NAMES.get(ext, "MP4 (%s)" % (ext or ".mp4")))]
    out.append(("Video codec", (info.vcodec or "?").upper()))
    # Profile is only listed for H.264, where it is a decode ceiling worth
    # matching.  ffprobe reports a bare "0" for VP8/VP9, which rendered as a
    # "Profile: 0" row that meant nothing to anyone reading it.
    if info.profile and (info.vcodec or "").lower() == "h264":
        lvl = ("  level %.1f" % (info.level / 10.0)
               if info.level and 9 < info.level < 100 else "")
        out.append(("Profile", "%s%s" % (info.profile, lvl)))
    out.append(("Pixel format", "%s (8-bit 4:2:0)" % info.pix_fmt
                if info.pix_fmt in SAFE_PIX_FMTS and info.pix_fmt
                else (info.pix_fmt or "?")))
    if info.width and info.height:
        out.append(("Frame size", "%d x %d" % (info.width, info.height)))
    if info.fps:
        out.append(("Frame rate", "%.6g fps" % info.fps))
    if info.duration:
        out.append(("Length", "%.2f s" % info.duration))
    # Worth stating outright: most Spike 2 clips carry no audio track, and a
    # replacement that brings one adds sound the game never had, which the
    # machine plays (a tester: "I forgot to drop the audio off some files").
    out.append(("Audio", "none" if not info.has_audio
                else "%d Hz, %d ch" % (info.audio_rate, info.audio_channels)))
    return out


def dropin_ffmpeg_command(info, ext, src="input.mov", dst="output"):
    """An ffmpeg command line that turns *src* into a drop-in for the clip
    *info* describes, or ``None`` when it can't be built.

    For users who would rather encode their own files than let the app do it —
    a tester tunes his own key-frame interval so long clips play smoothly on
    the machine, and without knowing the target he was guessing.  Everything
    that isn't dictated by the slot (bitrate, key-frame interval, preset) is
    deliberately left out, so it can be tuned without fighting the parts that
    have to match.
    """
    if info is None or not info.width or not info.height:
        return None
    codec = (info.vcodec or "").lower()
    # The slot's own codec, not the container's default: a libx264 line under
    # a .webm slot isn't merely suboptimal, ffmpeg refuses to mux it at all.
    enc = _ENCODER_NAMES.get(codec) or _ENCODER_NAMES.get(
        _DEFAULT_CODEC.get(ext or ".mp4", "h264"))
    args = ["ffmpeg", "-i", src, "-c:v", enc]
    if codec == "h264":
        prof = _X264_PROFILES.get((info.profile or "").strip().lower())
        if prof:
            args += ["-profile:v", prof]
            if info.level and 9 < info.level < 100:
                args += ["-level", "%.1f" % (info.level / 10.0)]
    args += ["-pix_fmt", info.pix_fmt or "yuv420p",
             "-vf", "scale=%d:%d" % (info.width, info.height)]
    if info.fps:
        args += ["-r", "%.6g" % info.fps]
    args += ["-an", dst + (ext or ".mov")]
    return " ".join(args)


def _encode_timeout(duration):
    """Wall-clock cap in seconds for one ffmpeg encode of a *duration*-second
    clip.

    The cap exists only to catch a truly hung ffmpeg — it must never kill an
    encode that is merely slow.  A flat 900s did exactly that: VP9 on a slow
    machine can run well below realtime, so a full-song replacement (a
    9-minute GNR webm) legitimately needs more than 15 minutes.  Scale with
    the clip length (20x realtime is far slower than any working encode),
    bounded to [15 minutes, 4 hours]; unknown length gets a flat hour.
    """
    if not duration or duration <= 0:
        return 3600
    return max(900, min(int(duration * 20), 4 * 3600))


def _timeout_error(seconds):
    """Human-readable failure detail for an encode that hit the wall-clock
    cap (str(TimeoutExpired) would dump the whole ffmpeg command line)."""
    return (f"re-encode timed out after {seconds // 60} minutes — ffmpeg was "
            f"found and ran, but converting this clip is too slow on this "
            f"machine.  Try a shorter clip, or supply one already in the "
            f"slot's exact format (container/codec/resolution/fps) so it "
            f"copies through without re-encoding")


# An encoding ffmpeg prints stats to stderr every ~half second, so a long
# silence means it's wedged (source on a dropped network share, cloud file
# that won't download), not slow.  This catches a hung ffmpeg in minutes
# even though the wall-clock cap above is sized for hours-long slow encodes.
_STALL_LIMIT = 300


def _stall_error():
    return (f"ffmpeg produced no output for {_STALL_LIMIT // 60} minutes and "
            f"was stopped — the replacement file may be unreadable (network "
            f"drive dropped?  cloud placeholder not downloaded?).  Check it "
            f"plays in a video player, then try again")


def _run_ffmpeg_watched(cmd, limit, cancel_cb=None):
    """Run an ffmpeg encode under a watchdog instead of one blocking wait.

    Returns ``(returncode, stderr_tail, abort)`` where *abort* is ``None``
    for a normal exit, or ``"cancelled"`` / ``"stall"`` / ``"timeout"`` when
    the process was killed (user cancel, no stderr activity for
    :data:`_STALL_LIMIT` seconds, or *limit* seconds total).  Distinguishing
    stalled from slow is what lets the wall-clock cap be generous: a working
    encode streams stats to stderr continuously, a wedged one goes silent.
    """
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,
                            creationflags=_CREATE_FLAGS)
    tail = bytearray()
    last_activity = [time.monotonic()]

    def _drain():
        try:
            for chunk in iter(lambda: proc.stderr.read1(4096), b""):
                last_activity[0] = time.monotonic()
                tail.extend(chunk)
                if len(tail) > 131072:      # keep only the recent stderr
                    del tail[:-65536]
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    start = time.monotonic()
    abort = None
    while proc.poll() is None:
        now = time.monotonic()
        if cancel_cb is not None and cancel_cb():
            abort = "cancelled"
        elif now - last_activity[0] > _STALL_LIMIT:
            abort = "stall"
        elif now - start > limit:
            abort = "timeout"
        if abort:
            proc.kill()
            proc.wait()
            break
        time.sleep(0.25)
    reader.join(timeout=5)
    return proc.returncode, bytes(tail), abort


def transcode_video_to(src_path, dst_path, original_info,
                       match_length=False, cancel_cb=None):
    """Transcode *src_path* into *dst_path*, whose extension selects the
    output container / codec.

    Resolution, frame rate, and (where the format allows) the alpha channel
    are matched to *original_info* so the result drops into the slot it
    replaces.  When *match_length* is set, the result is trimmed or padded to
    the original's duration.  *cancel_cb* (returns truthy to abort) is polled
    during the encode so a user Cancel stops ffmpeg promptly.  Returns
    ``(ok, actions)`` — *actions* is a short human-readable summary; on
    failure *ok* is False and *actions* is an error.

    The slot's own AUDIO shape is matched too: a slot whose clip has no audio
    track gets a replacement with none either.  Nearly every Spike 2 clip is
    silent and the game plays its own sound, so a replacement that keeps its
    source's audio adds a second soundtrack the machine really does play over
    the top (a tester: "I forgot to drop the audio off some files").  The
    test is per-SLOT, not a blanket rule: a census of 2251 clips across five
    titles found Led Zeppelin, Godzilla, Jaws and John Wick entirely silent
    but Deadpool carrying audio on 7 of its 99, so the clip being replaced is
    the only thing worth matching.

    Requires ffmpeg.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "need ffmpeg to convert video"
    ext = os.path.splitext(dst_path)[1].lower()
    alpha = bool(original_info and original_info.has_alpha)
    slot_codec = ((original_info.vcodec or "") if original_info else "").lower()
    vargs, aargs = _video_codec_args(ext, alpha, slot_codec)
    if vargs is None:
        return False, f"unsupported target format {ext}"

    actions = []
    # Worth one word in the log when the slot's own codec is what we encoded
    # to rather than the container's default — that IS the difference between
    # a clip that plays and one that plays black, and nothing else says it.
    chosen = encoder_codec(ext, alpha, slot_codec)
    if chosen and chosen != _DEFAULT_CODEC.get(ext):
        actions.append("%s (the slot's own codec)" % chosen.upper())
    vf = []
    scaled_to_slot = bool(original_info and original_info.width > 0
                          and original_info.height > 0)
    if original_info and original_info.width > 0 and original_info.height > 0:
        # Scale to the slot's exact dimensions (games expect a fixed canvas);
        # pad after a decrease-fit so odd aspect ratios letterbox instead of
        # stretching.
        vf.append(
            f"scale={original_info.width}:{original_info.height}"
            f":force_original_aspect_ratio=decrease")
        vf.append(
            f"pad={original_info.width}:{original_info.height}"
            f":(ow-iw)/2:(oh-ih)/2"
            + (":color=#00000000" if alpha else ""))
        actions.append(f"→{original_info.width}x{original_info.height}")

    cmd = [ffmpeg, "-y", "-i", src_path]

    # Length matching: trim a longer source, pad a shorter one.  enc_dur is
    # how many seconds of video the encode will actually produce — it drives
    # the wall-clock cap below.
    src_dur = probe_duration(src_path)
    enc_dur = src_dur
    cap_to = None
    if match_length and original_info and original_info.duration > 0:
        target = original_info.duration
        if src_dur > target + 0.05:
            cap_to = target
            enc_dur = target
            actions.append(f"trim {src_dur:.1f}s→{target:.1f}s")
        elif src_dur and src_dur < target - 0.05:
            vf.append(
                f"tpad=stop_mode=clone:stop_duration={target - src_dur:.3f}")
            enc_dur = target
            actions.append(f"pad {src_dur:.1f}s→{target:.1f}s")

    if vf:
        cmd += ["-vf", ",".join(vf)]
    if original_info and original_info.fps > 0:
        cmd += ["-r", f"{original_info.fps:.4f}"]
    cmd += vargs
    if "libx264" in vargs:
        cmd += _h264_profile_args(original_info, scaled_to_slot)
    if _is_vpx(vargs):
        # Pin constant-quality mode: with no explicit rate control the libvpx
        # default varies by ffmpeg build (older ones target 256kbps — visibly
        # blocky at slot resolutions).  This path has no byte budget;
        # shrink_video_to_size sets its own -b:v.
        cmd += ["-crf", "32", "-b:v", "0"]
    # Match the slot's audio shape (see the docstring).  Only when we actually
    # probed the slot: an unprobed original is not evidence that it is silent.
    if original_info is not None and not original_info.has_audio:
        cmd += ["-an"]
        actions.append("no audio (slot has none)")
    else:
        cmd += aargs
    if cap_to is not None:
        cmd += ["-t", f"{cap_to:.3f}"]
    cmd.append(dst_path)

    limit = _encode_timeout(enc_dur)
    try:
        rc, stderr, abort = _run_ffmpeg_watched(cmd, limit, cancel_cb)
    except OSError as e:
        return False, str(e)
    if abort == "cancelled":
        return False, "cancelled"
    if abort == "stall":
        return False, _stall_error()
    if abort == "timeout":
        return False, _timeout_error(limit)
    if rc == 0 and os.path.isfile(dst_path) \
            and os.path.getsize(dst_path) > 0:
        return True, ", ".join(a for a in actions if a)
    err = stderr.decode("utf-8", "replace").strip().splitlines()
    return False, (err[-1] if err else f"ffmpeg failed (code {rc})")


def remux_video_to(src_path, dst_path, original_info, cancel_cb=None):
    """Repackage *src_path* into *dst_path*'s container without re-encoding it.

    For the replacement that already IS the clip the slot needs and is only
    wrapped wrong: a tester encoded his to the slot's codec, resolution and frame
    rate but wrote it as ``.mp4`` where the card's clip is QuickTime, and the
    build then refused it as a drop-in (right — the wrapper really is part of
    what the machine reads).  Re-encoding to fix a container costs a whole
    generation of quality for nothing; a stream copy rewrites only the
    container boxes and leaves every coded frame bit-for-bit identical.

    The slot's AUDIO shape still applies (see :func:`transcode_video_to`): a
    silent slot gets a silent replacement, since the machine really does play
    a soundtrack the clip brought with it.  Returns ``(ok, actions)``.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "need ffmpeg to repackage video"
    ext = os.path.splitext(dst_path)[1].lower()
    cmd = [ffmpeg, "-y", "-i", src_path, "-c", "copy"]
    actions = ["repackaged as %s (no re-encode)" % (ext or "the slot's format")]
    if original_info is not None and not original_info.has_audio:
        cmd += ["-an"]
        actions.append("no audio (slot has none)")
    cmd.append(dst_path)

    limit = _encode_timeout(probe_duration(src_path))
    try:
        rc, stderr, abort = _run_ffmpeg_watched(cmd, limit, cancel_cb)
    except OSError as e:
        return False, str(e)
    if abort == "cancelled":
        return False, "cancelled"
    if abort == "stall":
        return False, _stall_error()
    if abort == "timeout":
        return False, _timeout_error(limit)
    if rc == 0 and os.path.isfile(dst_path) \
            and os.path.getsize(dst_path) > 0:
        return True, ", ".join(actions)
    err = stderr.decode("utf-8", "replace").strip().splitlines()
    return False, (err[-1] if err else f"ffmpeg failed (code {rc})")


def shrink_video_to_size(src_path, dst_path, max_bytes, original_info=None,
                         attempts=3, cancel_cb=None):
    """Re-encode *src_path* into *dst_path* (same container/codec/resolution)
    targeting a muxed file no larger than *max_bytes*.

    Needed for in-place asset patching (e.g. Stern Spike 2), where a
    replacement must fit the original file's exact byte slot — the filesystem
    isn't resized, so the new bytes have to be ``<= max_bytes``.  Derives a
    video bitrate from the clip's duration and the byte budget, hard-caps the
    rate (``-maxrate`` / ``-bufsize``), and retries with a smaller budget if
    the muxed result still overshoots.  Returns ``(ok, detail)`` — on success
    *detail* is the final byte size as a string; on failure it's an error
    message.  The caller pads the (``<= max_bytes``) result up to the exact
    slot size.  Requires ffmpeg.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "need ffmpeg to shrink video"
    if max_bytes <= 0:
        return False, "no byte budget"
    ext = os.path.splitext(dst_path)[1].lower()
    info = original_info or detect_video_info(src_path)
    alpha = bool(info and info.has_alpha)
    vargs, aargs = _video_codec_args(
        ext, alpha, ((info.vcodec or "") if info else "").lower())
    if vargs is None:
        return False, f"unsupported target format {ext}"
    # The byte budget buys bitrate × the length of the clip being ENCODED, so
    # the duration has to come from the source.  *original_info* is a format
    # template — a caller may pass the SLOT's own clip to pin resolution, frame
    # rate and codec — and taking the length from that sets the rate by the
    # wrong clip: a 9-second replacement budgeted as if it were the slot's
    # 3-second original comes out three times over, on every retry.
    dur = probe_duration(src_path)
    if not dur or dur <= 0:
        dur = info.duration if info and info.duration > 0 else 0
    if not dur or dur <= 0:
        return False, "could not determine clip duration"
    # Reserve some bits for an audio track (if any) + container overhead.
    abps = 96_000 if (info is None or info.has_audio) else 0

    vf = []
    if info and info.width > 0 and info.height > 0:
        vf.append(f"scale={info.width}:{info.height}"
                  f":force_original_aspect_ratio=decrease")
        vf.append(f"pad={info.width}:{info.height}:(ow-iw)/2:(oh-ih)/2"
                  + (":color=#00000000" if alpha else ""))

    headrooms = [0.92, 0.80, 0.62][:max(1, attempts)]
    last_err = ""
    for hr in headrooms:
        vbps = int(max_bytes * 8 * hr / dur) - abps
        if vbps < 40_000:
            vbps = 40_000
        cmd = [ffmpeg, "-y", "-i", src_path]
        if vf:
            cmd += ["-vf", ",".join(vf)]
        if info and info.fps > 0:
            cmd += ["-r", f"{info.fps:.4f}"]
        cmd += vargs
        if "libx264" in vargs:
            cmd += _h264_profile_args(info, scaled_to_slot=bool(vf))
        cmd += ["-b:v", str(vbps), "-maxrate", str(vbps),
                "-bufsize", str(vbps * 2)]
        if abps:
            cmd += aargs + ["-b:a", str(abps)]
        else:
            cmd += ["-an"]
        cmd.append(dst_path)
        limit = _encode_timeout(dur)
        try:
            rc, stderr, abort = _run_ffmpeg_watched(cmd, limit, cancel_cb)
        except OSError as e:
            return False, str(e)
        if abort == "cancelled":
            return False, "cancelled"
        if abort == "stall":
            return False, _stall_error()
        if abort == "timeout":
            return False, _timeout_error(limit)
        if rc == 0 and os.path.isfile(dst_path):
            sz = os.path.getsize(dst_path)
            if 0 < sz <= max_bytes:
                return True, str(sz)
            last_err = f"re-encode landed at {sz} > {max_bytes} bytes"
        else:
            err = stderr.decode("utf-8", "replace").strip().splitlines()
            last_err = err[-1] if err else f"ffmpeg failed (code {rc})"
    return False, last_err or "could not shrink to fit"
