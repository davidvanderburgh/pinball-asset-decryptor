"""The GPU encoder and decoder for throwaway preview copies (PAD-1578).

The preview pane, Video Compare and the Audio tab's player all watch a small
H.264 copy of a clip (``webui.video_helpers.browser_proxy``).  Those copies
never go on a machine, so they may be made on the PC's GPU (NVIDIA NVENC,
Intel Quick Sync, AMD AMF, Apple VideoToolbox) when it has one, with libx264
as the fallback.  Anything that goes onto a card keeps its own x264 flags in
``core.video`` and never comes through here, so its bytes do not change.

The encoder list ffmpeg prints is not proof: a full build lists NVENC on a
PC with no NVIDIA card, and QSV on one whose driver is too old.  So each
candidate is tried with a one-frame encode (fed as raw frames on stdin, so
it needs no lavfi) the first time a preview is made, and the first that
works is used for the rest of the run.  A real encode that fails on it falls
back to x264 for that clip (``failed``), and the GPU encoder is dropped for
the run when its one-frame test then fails too.

The source is decoded on the GPU too (``-hwaccel``: D3D11VA on Windows,
VideoToolbox on macOS, CUDA on Linux) when a one-frame decode test with it
works and the preview is short of CPU threads (a small PC, or Video Compare
making four at once): ``worth_gpu_decode``.  On a big CPU the CPU decodes
faster, so it is left there.
ffmpeg decodes a stream the GPU cannot (an odd codec or profile) in
software by itself; a clip that fails outright is redone with neither.

``PAD_PREVIEW_DECODE=cpu`` turns the GPU decode off.
``PAD_PREVIEW_ENCODER`` overrides the pick: ``x264`` (or ``cpu``) always uses
libx264; a candidate name (``nvenc``, ``qsv``, ``amf``, ``videotoolbox``)
tries only that one.
"""

import logging
import os
import subprocess
import sys
import tempfile
import threading

log = logging.getLogger(__name__)

# The flags browser_proxy has always used: the fallback, and what a PC with
# no working GPU encoder keeps getting.
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-profile:v", "main"]

# Each GPU encoder at a quality close to X264's on real Stern clips (NVENC
# cq 30: SSIM 0.968 against x264's 0.964 at about the same size; the bench
# is in docs/plans/gpu-preview-encode.md).  Main profile, 8-bit 4:2:0: what
# every page engine plays.
_GPU = {
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "30",
              "-b:v", "0", "-pix_fmt", "yuv420p", "-profile:v", "main"],
    "qsv": ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "25",
            "-pix_fmt", "nv12", "-profile:v", "main"],
    "amf": ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp",
            "-qp_i", "24", "-qp_p", "26", "-pix_fmt", "nv12", "-profile:v", "main"],
    "videotoolbox": ["-c:v", "h264_videotoolbox", "-b:v", "3M", "-allow_sw", "0",
                     "-pix_fmt", "yuv420p", "-profile:v", "main"],
}


def candidates(platform=None):
    """The GPU encoders worth trying on *platform*, best first.  Linux's
    VAAPI/QSV need a device picked by hand, so only NVENC is tried there."""
    platform = platform or sys.platform
    if platform == "win32":
        return ["nvenc", "qsv", "amf"]
    if platform == "darwin":
        return ["videotoolbox"]
    return ["nvenc"]


def hwaccels(platform=None):
    """The ``-hwaccel`` decoders worth trying on *platform*, best first."""
    platform = platform or sys.platform
    if platform == "win32":
        return ["d3d11va"]
    if platform == "darwin":
        return ["videotoolbox"]
    return ["cuda"]


_lock = threading.Lock()
_picked = {}            # ffmpeg path -> encoder name ("x264" when none works)
_decode = {}            # ffmpeg path -> hwaccel name ("" when none works)
_PROBE_W, _PROBE_H = 256, 144


def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def probe(ffmpeg, name):
    """True when *ffmpeg* makes a one-frame MP4 with encoder *name*'s own
    preview flags.  Never raises."""
    args = X264 if name == "x264" else _GPU.get(name)
    if not args or not ffmpeg:
        return False
    fd, out = tempfile.mkstemp(prefix="pad-encprobe-", suffix=".mp4")
    os.close(fd)
    try:
        frame = bytes([96, 128, 160]) * (_PROBE_W * _PROBE_H)
        r = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", "%dx%d" % (_PROBE_W, _PROBE_H), "-framerate", "30", "-i", "-",
             "-frames:v", "1"] + args + ["-an", "-f", "mp4", out],
            input=frame, capture_output=True, timeout=20,
            creationflags=_no_window())
        return r.returncode == 0 and os.path.getsize(out) > 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


def probe_decode(ffmpeg, hwaccel):
    """True when *ffmpeg* decodes a one-frame H.264 clip with ``-hwaccel
    hwaccel``.  Never raises."""
    if not ffmpeg or not hwaccel:
        return False
    fd, clip = tempfile.mkstemp(prefix="pad-decprobe-", suffix=".mp4")
    os.close(fd)
    try:
        frame = bytes([96, 128, 160]) * (_PROBE_W * _PROBE_H)
        r = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", "%dx%d" % (_PROBE_W, _PROBE_H), "-framerate", "30", "-i", "-",
             "-frames:v", "1"] + X264 + ["-an", "-f", "mp4", clip],
            input=frame, capture_output=True, timeout=20,
            creationflags=_no_window())
        if r.returncode != 0:
            return False
        r = subprocess.run(
            [ffmpeg, "-v", "error", "-hwaccel", hwaccel, "-i", clip,
             "-f", "null", "-"], capture_output=True, timeout=20,
            creationflags=_no_window())
        # A hwaccel that cannot start falls back to software and says so.
        return r.returncode == 0 and not (r.stderr or b"").strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    finally:
        try:
            os.remove(clip)
        except OSError:
            pass


# When the GPU decoder pays (timed on real Stern clips, interleaved; see
# docs/plans/gpu-preview-encode.md).  It frees the CPU but costs a copy of
# every frame back from the GPU and about half a second to start, so it only
# wins when the preview has few CPU threads to itself: with 2 a 9-minute
# 1360x768 clip went 24.6 s -> 17.0 s, with 4 it broke even or won (and four
# Video Compare copies on 16 threads, 4 each, won), with 6 or more it lost
# (16 threads: 6.3 s -> 10.0 s).  A short clip never pays for the start-up:
# clip seconds x megapixels x (4 / threads each) must reach GPU_DECODE_WORK
# (a 26 s 1360x768 clip is 27; a 90 s one is 94).
GPU_DECODE_MAX_THREADS = 4
GPU_DECODE_WORK = 60.0

_active = [0]           # previews being made right now (browser_proxy)


class making:
    """``with making():`` round one preview's encode, so the decode choice
    knows how many share the CPU."""

    def __enter__(self):
        with _lock:
            _active[0] += 1
        return self

    def __exit__(self, *exc):
        with _lock:
            _active[0] = max(0, _active[0] - 1)
        return False


def worth_gpu_decode(info, threads=None, jobs=None):
    """True when decoding the clip *info* describes on the GPU beats the
    CPU: each of the *jobs* previews being made at once (default: those
    inside ``making``) has at most GPU_DECODE_MAX_THREADS of the *threads*
    this process may use, and the clip is big enough to pay the start-up.
    An unknown duration or size decodes on the CPU, as before PAD-1578."""
    try:
        work = (float(info.duration) * info.width * info.height / 1e6)
    except (AttributeError, TypeError, ValueError):
        return False
    count = getattr(os, "process_cpu_count", None) or os.cpu_count
    threads = max(1, threads or count() or 4)
    each = threads / float(max(1, jobs or _active[0]))
    return (each <= GPU_DECODE_MAX_THREADS
            and work * GPU_DECODE_MAX_THREADS / each >= GPU_DECODE_WORK)


def decode_args(ffmpeg, info=None):
    """The ``-hwaccel`` input flags for a preview of the clip *info*
    describes, made by *ffmpeg*: ``[]`` when the clip is too small to pay
    (``worth_gpu_decode``) or no GPU decoder works.  Tested once per run."""
    if not worth_gpu_decode(info):
        return []
    with _lock:
        if ffmpeg not in _decode:
            want = (os.environ.get("PAD_PREVIEW_DECODE") or "").strip().lower()
            order = [] if want in ("cpu", "off", "0", "x264") else hwaccels()
            _decode[ffmpeg] = next((h for h in order if probe_decode(ffmpeg, h)), "")
            log.info("preview decoder: %s", _decode[ffmpeg] or "cpu")
        hw = _decode[ffmpeg]
    return ["-hwaccel", hw] if hw else []


def pick(ffmpeg):
    """The encoder name previews use with *ffmpeg*: the first GPU candidate
    whose one-frame test works, else ``"x264"``.  Tested once per run."""
    with _lock:
        if ffmpeg in _picked:
            return _picked[ffmpeg]
        want = (os.environ.get("PAD_PREVIEW_ENCODER") or "").strip().lower()
        if want in ("x264", "libx264", "cpu", "off", "0"):
            order = []
        elif want in _GPU:
            order = [want]
        else:
            order = candidates()
        name = next((c for c in order if probe(ffmpeg, c)), "x264")
        _picked[ffmpeg] = name
        log.info("preview encoder: %s (tried %s)", name, ", ".join(order) or "none")
        return name


def h264_args(ffmpeg):
    """(name, ffmpeg video flags) for a preview copy made by *ffmpeg*."""
    name = pick(ffmpeg)
    return name, list(X264 if name == "x264" else _GPU[name])


def failed(ffmpeg, name, hwaccel=""):
    """A real preview with encoder *name* (and GPU decoder *hwaccel*) failed;
    the caller redoes it with X264 and no hwaccel.  Drop each for the run
    when its one-frame test now fails too; a passing test means the clip, or
    a busy moment (NVENC's session limit while Compare makes four at once),
    was the trouble, so keep it."""
    if hwaccel and not probe_decode(ffmpeg, hwaccel):
        with _lock:
            if _decode.get(ffmpeg) == hwaccel:
                _decode[ffmpeg] = ""
        log.warning("preview decoder %s stopped working; decoding on the CPU", hwaccel)
    if name == "x264":
        return
    if not probe(ffmpeg, name):
        with _lock:
            if _picked.get(ffmpeg) == name:
                _picked[ffmpeg] = "x264"
        log.warning("preview encoder %s stopped working; using x264", name)


def reset():
    """Forget the picks (tests)."""
    with _lock:
        _picked.clear()
        _decode.clear()
