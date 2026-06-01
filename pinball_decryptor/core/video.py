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
import subprocess

from .audio import (_CREATE_FLAGS, find_ffmpeg, find_ffprobe, probe_duration)

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
                 pix_fmt="", container="", nframes=0):
        self.path = path
        self.vcodec = vcodec          # "h264", "vp9", "theora", "prores", …
        self.width = width
        self.height = height
        self.fps = fps                # frames per second (0.0 if unknown)
        self.duration = duration      # seconds
        self.has_audio = has_audio
        self.has_alpha = has_alpha    # True for ProRes 4444 / VP9-alpha / …
        self.pix_fmt = pix_fmt
        self.container = container     # extension without the dot ("mp4")
        self.nframes = nframes         # frame count (custom backends; 0=unknown)

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

    ffprobe = find_ffprobe()
    if not ffprobe or not path or not os.path.isfile(path):
        return None
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
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
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

    return VideoInfo(
        path=path,
        vcodec=vstream.get("codec_name", "") or "",
        width=int(vstream.get("width", 0) or 0),
        height=int(vstream.get("height", 0) or 0),
        fps=fps,
        duration=dur,
        has_audio=has_audio,
        has_alpha=has_alpha,
        pix_fmt=pix_fmt,
        container=os.path.splitext(path)[1].lstrip(".").lower(),
    )


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

def _video_codec_args(ext, alpha):
    """Return ``(video_args, audio_args)`` ffmpeg flags for output *ext*.

    The container extension selects the codec family; *alpha* keeps a
    transparency channel where the format supports it (ProRes 4444 for .mov,
    VP9-alpha for .webm).  Returns ``(None, None)`` for an unsupported ext.
    """
    if ext in (".mp4", ".m4v", ".mkv"):
        return (["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:a", "aac"])
    if ext == ".mov":
        if alpha:
            return (["-c:v", "prores_ks", "-profile:v", "4444",
                     "-pix_fmt", "yuva444p10le"], ["-c:a", "pcm_s16le"])
        return (["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:a", "aac"])
    if ext == ".webm":
        if alpha:
            return (["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p"],
                    ["-c:a", "libopus"])
        return (["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p"],
                ["-c:a", "libopus"])
    if ext == ".ogv":
        return (["-c:v", "libtheora", "-q:v", "7"], ["-c:a", "libvorbis"])
    if ext == ".avi":
        return (["-c:v", "mpeg4", "-qscale:v", "3"], ["-c:a", "libmp3lame"])
    return (None, None)


def transcode_video_to(src_path, dst_path, original_info,
                       match_length=False):
    """Transcode *src_path* into *dst_path*, whose extension selects the
    output container / codec.

    Resolution, frame rate, and (where the format allows) the alpha channel
    are matched to *original_info* so the result drops into the slot it
    replaces.  When *match_length* is set, the result is trimmed or padded to
    the original's duration.  Returns ``(ok, actions)`` — *actions* is a short
    human-readable summary; on failure *ok* is False and *actions* is an error.

    Requires ffmpeg.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "need ffmpeg to convert video"
    ext = os.path.splitext(dst_path)[1].lower()
    alpha = bool(original_info and original_info.has_alpha)
    vargs, aargs = _video_codec_args(ext, alpha)
    if vargs is None:
        return False, f"unsupported target format {ext}"

    actions = []
    vf = []
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

    # Length matching: trim a longer source, pad a shorter one.
    cap_to = None
    if match_length and original_info and original_info.duration > 0:
        src_dur = probe_duration(src_path)
        target = original_info.duration
        if src_dur > target + 0.05:
            cap_to = target
            actions.append(f"trim {src_dur:.1f}s→{target:.1f}s")
        elif src_dur and src_dur < target - 0.05:
            vf.append(
                f"tpad=stop_mode=clone:stop_duration={target - src_dur:.3f}")
            actions.append(f"pad {src_dur:.1f}s→{target:.1f}s")

    if vf:
        cmd += ["-vf", ",".join(vf)]
    if original_info and original_info.fps > 0:
        cmd += ["-r", f"{original_info.fps:.4f}"]
    cmd += vargs
    cmd += aargs
    if cap_to is not None:
        cmd += ["-t", f"{cap_to:.3f}"]
    cmd.append(dst_path)

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=900,
                           creationflags=_CREATE_FLAGS)
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    if r.returncode == 0 and os.path.isfile(dst_path) \
            and os.path.getsize(dst_path) > 0:
        return True, ", ".join(a for a in actions if a)
    err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return False, (err[-1] if err else f"ffmpeg failed (code {r.returncode})")
