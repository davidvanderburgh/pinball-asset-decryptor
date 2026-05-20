"""Render Williams DMD scene bitmaps to PNG + MP4 montage.

A WPC 1-bit plane is 512 bytes (128x32, LSB-first within each byte
— bit 0 is the leftmost pixel, per FreeWPC dmd-theory).  A 4-shade
frame is two stacked planes (1024 bytes) interpreted as
``(low + 2*high) / 3`` brightness.

The Williams scanner emits *groups* — runs of contiguous 1024-byte
chunks that each pass the "looks like a DMD frame" heuristic.  In
practice, most of what passes is the game's static-scene bitmap
region: jackpot splash screens, mode-start announcements, status
panels.  Each 1024-byte chunk is one self-contained scene.

We therefore emit two artefacts per group:

  - ``scene_NNN_NNNN.png`` — one PNG per 1024-byte chunk (the real
    asset a user can identify and re-use)
  - ``montage.mp4`` — a quick MP4 flipping through all chunks at the
    user's chosen FPS (useful for browsing tile sheets, not because
    the chunks form a true motion animation)

Frame timing: WPC DMD hardware runs at ~120 Hz but per-frame hold
counts are controlled by 6809 code we can't statically read.  We
default to 4 fps in the montage so each scene is on screen long
enough to read.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

from ..spooky.p3_video import find_ffmpeg


# Suppress the cmd window Windows pops up for ffmpeg child processes
# when the parent is a GUI app (Tk).  Without this each per-animation
# render flashes a console at the user.
_NO_WINDOW = (subprocess.CREATE_NO_WINDOW
              if sys.platform == "win32" else 0)

DEFAULT_FPS = 4         # slow enough to read each scene
DEFAULT_PIXEL_SIZE = 12  # each DMD dot becomes an 11x11 square in the
                         # PNG — large enough for text to be readable
                         # when the MP4 is played in a typical video
                         # window.  At 6 the dots crowd together and
                         # text in WW/NF cinematics becomes a blob.
DEFAULT_COLOR = (191, 87, 0)  # Dark amber

PLANE_BYTES = 512
ROW_BYTES = 16
ROWS = 32
COLS = 128


def _render_planes(low, high, pixel_size, color):
    """Render a 4-shade frame from two stacked 1-bit planes.

    WPC 4-colour frames combine two bit planes into a brightness value:
    a pixel's intensity is ``(low_bit + 2 * high_bit) / 3``, giving
    {0%, 33%, 66%, 100%}.  *high* may be ``None`` to render mono.
    """
    img = Image.new("RGB", (COLS * pixel_size, ROWS * pixel_size),
                    (0, 0, 0))
    draw = ImageDraw.Draw(img)
    dot = pixel_size - 1
    r_base, g_base, b_base = color
    for r in range(ROWS):
        base = r * ROW_BYTES
        y0 = r * pixel_size
        for c in range(ROW_BYTES):
            lb = low[base + c]
            hb = high[base + c] if high is not None else 0
            if lb == 0 and hb == 0:
                continue
            col0 = c * 8
            # WPC DMD bytes are LSB-first within each byte —
            # bit 0 is the leftmost pixel of the 8-pixel group.
            for k in range(8):
                low_bit = (lb >> k) & 1
                high_bit = (hb >> k) & 1 if high is not None else 0
                if not (low_bit or high_bit):
                    continue
                level = low_bit + 2 * high_bit  # 0..3
                intensity = level / 3.0
                fill = (int(r_base * intensity),
                        int(g_base * intensity),
                        int(b_base * intensity))
                x0 = (col0 + k) * pixel_size
                draw.rectangle(
                    [x0, y0, x0 + dot - 1, y0 + dot - 1], fill=fill)
    return img


def render_scene_png(data, offset, out_path,
                     pixel_size=DEFAULT_PIXEL_SIZE,
                     color=DEFAULT_COLOR,
                     mode="4shade"):
    """Render a single DMD scene from *data* at *offset* to *out_path*.

    For ``mode="4shade"`` the scene is two 512-byte planes starting at
    *offset*; for ``"mono"`` it's a single 512-byte plane.  Returns
    the saved path.
    """
    low = data[offset:offset + PLANE_BYTES]
    if mode == "4shade":
        high = data[offset + PLANE_BYTES:offset + 2 * PLANE_BYTES]
        if len(high) < PLANE_BYTES:
            high = None
    else:
        high = None
    img = _render_planes(low, high, pixel_size, color)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def render_plane_to_png(plane_bytes, out_path,
                        pixel_size=DEFAULT_PIXEL_SIZE,
                        color=DEFAULT_COLOR):
    """Render a 512-byte 1-bit DMD plane to a PNG.

    Convenience wrapper around :func:`_render_planes` for callers
    that already have decoded plane bytes (e.g. animation frames
    that have been placed into a 128x32 canvas).
    """
    img = _render_planes(plane_bytes, None, pixel_size, color)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def render_pngs_to_mp4(png_paths, out_path, fps=DEFAULT_FPS):
    """Assemble an MP4 from a list of already-rendered PNGs.

    Copies each PNG into a temp dir with a sequential filename
    (``frame_NNNNNN.png``) so ffmpeg's image-sequence reader can
    consume them with one ``-i frame_%06d.png`` invocation.  Cheaper
    and safer than re-rendering from ROM data — the PNGs on disk
    are the canonical decoded representation.
    """
    import shutil as _sh
    if not png_paths:
        raise ValueError("No PNGs provided")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found.  Install ffmpeg to assemble the "
            "browse MP4.")
    tmp = tempfile.mkdtemp(prefix="williams_mp4_")
    try:
        for i, src in enumerate(png_paths):
            dst = os.path.join(tmp, f"frame_{i:06d}.png")
            _sh.copy(src, dst)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps),
            "-i", os.path.join(tmp, "frame_%06d.png"),
            "-c:v", "libx264",
            "-crf", "20",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            out_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            creationflags=_NO_WINDOW)
        if result.returncode != 0:
            tail = (result.stderr or "")[-500:]
            raise RuntimeError(
                f"ffmpeg failed (exit {result.returncode}): {tail}")
        return len(png_paths)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render_group_to_mp4(data, offsets, out_path,
                        fps=DEFAULT_FPS,
                        pixel_size=DEFAULT_PIXEL_SIZE,
                        color=DEFAULT_COLOR,
                        mode="4shade"):
    """Render *offsets* (each a frame start in *data*) to an MP4.

    Frame layout is *mode*-dependent:

      - ``"4shade"`` (default): each offset points to a 1024-byte
        4-shade frame — the first 512 bytes are the low plane, the
        next 512 are the high plane.  Brightness is
        ``(low + 2*high)/3``, matching WPC's 4-level DMD.
      - ``"mono"``: each offset is a single 512-byte plane,
        rendered as full-brightness on/off dots.

    Returns the number of frames written.

    Raises:
        RuntimeError: if ffmpeg is missing or fails.
        ValueError: if no offsets are provided.
    """
    if not offsets:
        raise ValueError("No frame offsets provided")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found.  Install ffmpeg to render Williams DMD "
            "animations to MP4.")
    tmp = tempfile.mkdtemp(prefix="williams_dmd_")
    try:
        for i, off in enumerate(offsets):
            low = data[off:off + PLANE_BYTES]
            if mode == "4shade":
                high = data[off + PLANE_BYTES:off + 2 * PLANE_BYTES]
                if len(high) < PLANE_BYTES:
                    high = None
            else:
                high = None
            img = _render_planes(low, high, pixel_size, color)
            img.save(os.path.join(tmp, f"frame_{i:06d}.png"), "PNG")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps),
            "-i", os.path.join(tmp, "frame_%06d.png"),
            "-c:v", "libx264",
            "-crf", "20",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            out_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            creationflags=_NO_WINDOW)
        if result.returncode != 0:
            tail = (result.stderr or "")[-500:]
            raise RuntimeError(
                f"ffmpeg failed (exit {result.returncode}): {tail}")
        return len(offsets)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_group_metadata(meta_path, group, scores=None):
    """Write a small JSON sidecar describing the rendered group."""
    payload = {
        "frame_count": len(group),
        "start_offset_hex": f"0x{group[0]:06X}" if group else None,
        "end_offset_hex": (f"0x{group[-1] + PLANE_BYTES - 1:06X}"
                           if group else None),
        "frames": [
            {"offset_hex": f"0x{off:06X}",
             "score": round(score, 3) if scores else None}
            for off, score in zip(group, scores or [None] * len(group))
        ],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
