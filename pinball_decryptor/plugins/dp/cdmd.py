"""Decoder for The Big Lebowski ``.cdmd`` color-display video files.

TBL's LCD plays full-color clips and animations stored in a custom,
**unencrypted** container.  Reverse-engineered byte layout (all integers
little-endian uint32):

    File header (16 bytes):
      [0:4]   magic = 01 02 15 20
      [4:8]   nframes
      [8:12]  canvasW   (observed 272)
      [12:16] canvasH   (observed 102)

    Then, per frame:
      x, y, w, h   (4 x uint32 = 16 bytes) — the changed sub-rectangle
      pixel data   = w * h * 4 bytes in ARGB order (byte0=Alpha, R, G, B)

Frames are **dirty rectangles**: each frame only carries the region that
changed since the previous frame, composited onto a persistent canvas.
Single-frame files (icons, text strips) are one full or partial rect;
animations and video clips ("character_videos_*") store many frames.

Video sequences ship a sibling ``<name>.wav`` audio track; when present we
sync the MP4 frame rate to the audio duration and mux the two together.

Requirements: Pillow (already a dependency) and ffmpeg in PATH (for MP4).
Single-frame stills are written as PNG and need only Pillow.
"""

import glob as _glob
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

from PIL import Image, ImageChops, ImageDraw, ImageFilter

CDMD_MAGIC = b"\x01\x02\x15\x20"

# Frame rate used when a clip has no paired audio to sync against.
DEFAULT_FPS = 30

# Dot-matrix (DMD) rendering — each source pixel becomes a round LED "dot"
# on black, mimicking the machine's colour dot-matrix display.
DMD_CELL = 8           # output pixels per source pixel (LED pitch)
DMD_DOT_RATIO = 0.82   # dot diameter as a fraction of the cell
DMD_BORDER = 8         # black bezel margin (output px) around the panel

# Cached ffmpeg path (None = not searched yet, False = searched, not found).
_ffmpeg_path = None

# Suppress the flashing console window ffmpeg would otherwise pop on Windows
# (we spawn it once per clip — hundreds of times across a full extract).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# ffmpeg discovery (mirrors the other plugins' resilient PATH + winget search)
# ---------------------------------------------------------------------------

def find_ffmpeg():
    """Return the ffmpeg executable path, or None if unavailable."""
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path or None

    path = shutil.which("ffmpeg")
    if path:
        _ffmpeg_path = path
        return path

    if sys.platform == "win32":
        search_dirs = []
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            search_dirs.extend(_glob.glob(os.path.join(
                local_app, "Microsoft", "WinGet", "Packages",
                "*ffmpeg*", "*", "bin")))
            search_dirs.append(os.path.join(
                local_app, "Microsoft", "WinGet", "Links"))
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            search_dirs.append(os.path.join(userprofile, "scoop", "shims"))
        choco = os.environ.get("ChocolateyInstall", r"C:\ProgramData\chocolatey")
        search_dirs.append(os.path.join(choco, "bin"))
        search_dirs.extend([
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
        ])
        for d in search_dirs:
            for exe in ("ffmpeg.exe", "ffmpeg"):
                candidate = os.path.join(d, exe)
                if os.path.isfile(candidate):
                    _ffmpeg_path = candidate
                    return candidate

    _ffmpeg_path = False
    return None


def check_ffmpeg():
    return find_ffmpeg() is not None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def is_cdmd(data):
    """True if *data* (bytes or an open path) begins with the cdmd magic."""
    if isinstance(data, (bytes, bytearray)):
        return data[:4] == CDMD_MAGIC
    try:
        with open(data, "rb") as f:
            return f.read(4) == CDMD_MAGIC
    except OSError:
        return False


def parse_header(data):
    """Return ``(nframes, canvasW, canvasH)`` from a cdmd byte string.

    Raises ValueError if the magic or geometry is invalid.
    """
    if len(data) < 16 or data[:4] != CDMD_MAGIC:
        raise ValueError("Not a cdmd file (bad magic)")
    nframes, canvas_w, canvas_h = struct.unpack_from("<3I", data, 4)
    if canvas_w == 0 or canvas_h == 0 or canvas_w > 8192 or canvas_h > 8192:
        raise ValueError(f"Invalid cdmd canvas {canvas_w}x{canvas_h}")
    return nframes, canvas_w, canvas_h


def _argb_to_rgba(raw):
    """Reorder a packed ARGB byte string into RGBA for Pillow."""
    out = bytearray(len(raw))
    out[0::4] = raw[1::4]   # R
    out[1::4] = raw[2::4]   # G
    out[2::4] = raw[3::4]   # B
    out[3::4] = raw[0::4]   # A
    return bytes(out)


def iter_frames(data):
    """Yield each fully-composited frame as an RGBA ``PIL.Image``.

    The canvas persists across frames so dirty-rectangle updates accumulate,
    exactly as the machine renders them.
    """
    nframes, canvas_w, canvas_h = parse_header(data)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    off = 16
    n = len(data)
    for _ in range(nframes):
        if off + 16 > n:
            break
        x, y, w, h = struct.unpack_from("<4I", data, off)
        off += 16
        size = w * h * 4
        if w and h and off + size <= n:
            sub = Image.frombytes("RGBA", (w, h), _argb_to_rgba(data[off:off + size]))
            canvas.alpha_composite(sub, (x, y))
        off += size
        yield canvas.copy()


def frame_count(data):
    return parse_header(data)[0]


# ---------------------------------------------------------------------------
# Encoding  (Replace-Video: write a replacement clip back into .cdmd)
# ---------------------------------------------------------------------------
#
# The decoder above is fully reversible, so we can round-trip: a replacement
# video is decoded to RGB frames, scaled to the original's canvas, resampled
# to the original's frame count (so the sibling .wav stays in sync), and
# written back as a .cdmd.  Each frame is emitted as a single full-canvas
# dirty rectangle (x=y=0, w=canvasW, h=canvasH) — always valid, and the size
# cost is negligible for these small DMD panels.

def _rgb24_to_argb(rgb):
    """Pack an opaque rgb24 byte string into the cdmd ARGB byte order."""
    px = len(rgb) // 3
    out = bytearray(px * 4)
    out[0::4] = b"\xff" * px   # A (opaque)
    out[1::4] = rgb[0::3]      # R
    out[2::4] = rgb[1::3]      # G
    out[3::4] = rgb[2::3]      # B
    return bytes(out)


def write_cdmd(dst_path, frames_rgb, nframes, canvas_w, canvas_h):
    """Write *frames_rgb* (an iterable of rgb24 byte strings, each exactly
    ``canvas_w*canvas_h*3`` bytes) to *dst_path* as a cdmd of *nframes*
    full-canvas frames.  Frames beyond *nframes* are ignored; if the iterable
    is short the last frame is repeated so the header count stays honest."""
    frame_bytes = canvas_w * canvas_h * 3
    rect = struct.pack("<4I", 0, 0, canvas_w, canvas_h)
    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    with open(dst_path, "wb") as f:
        f.write(CDMD_MAGIC)
        f.write(struct.pack("<3I", nframes, canvas_w, canvas_h))
        it = iter(frames_rgb)
        last = b"\x00" * frame_bytes
        for _ in range(nframes):
            try:
                rgb = next(it)
                if len(rgb) == frame_bytes:
                    last = rgb
            except StopIteration:
                rgb = last  # ran out early: hold the final frame
            f.write(rect)
            f.write(_rgb24_to_argb(last if len(rgb) != frame_bytes else rgb))


def cdmd_video_info(path):
    """Return ``(canvas_w, canvas_h, nframes, fps, duration, wav)`` for a
    multi-frame *video* cdmd, or ``None`` for anything that isn't one.

    Returns None for non-video .cdmd (font/glyph data with a different magic),
    unreadable files, and single-frame stills (icons / text strips) — only
    real clips are offered as Replace-Video slots.  The frame rate is derived
    from the paired .wav when present so the reported length matches playback.
    """
    if not is_cdmd(path):
        return None
    try:
        with open(path, "rb") as f:
            head = f.read(16)
        nframes, cw, ch = parse_header(head)
    except (OSError, ValueError):
        return None
    if nframes <= 1:
        return None
    wav = _sibling_wav(path)
    dur = _wav_duration(wav) if wav else None
    if dur and dur > 0:
        fps = max(1.0, min(nframes / dur, 60.0))
        duration = dur
    else:
        fps = float(DEFAULT_FPS)
        duration = nframes / float(DEFAULT_FPS)
    return (cw, ch, nframes, fps, duration, wav)


def iter_preview_rgb(path, target_w, target_h, start_index=0):
    """Yield composited frames of *path* as rgb24 bytes scaled to
    *target_w* x *target_h* (flattened on black — the raw clip content, no
    dot-matrix shader).  Skips the first *start_index* frames (for seeking).

    The canvas must be composited from frame 0, so skipped frames are still
    decoded; they're just not yielded.
    """
    with open(path, "rb") as f:
        data = f.read()
    for i, img in enumerate(iter_frames(data)):
        if i < start_index:
            continue
        flat = Image.new("RGB", img.size, (0, 0, 0))
        flat.paste(img, (0, 0), img)
        if flat.size != (target_w, target_h):
            flat = flat.resize((target_w, target_h), Image.BILINEAR)
        yield flat.tobytes()


def preview_frame_png(path, pos, target_w, target_h):
    """Return PNG bytes of the frame at *pos* seconds, scaled to fit
    *target_w* x *target_h* — used for the poster frame + seek scrubbing."""
    info = cdmd_video_info(path)
    if info is None:
        return None
    _cw, _ch, nframes, fps, _dur, _wav = info
    idx = max(0, min(nframes - 1, int(round(pos * fps))))
    with open(path, "rb") as f:
        data = f.read()
    last = None
    for i, img in enumerate(iter_frames(data)):
        last = img
        if i >= idx:
            break
    if last is None:
        return None
    flat = Image.new("RGB", last.size, (0, 0, 0))
    flat.paste(last, (0, 0), last)
    flat.thumbnail((target_w, target_h), Image.BILINEAR)
    import io
    buf = io.BytesIO()
    flat.save(buf, "PNG")
    return buf.getvalue()


def video_to_cdmd(src_video, dst_path, canvas_w, canvas_h, nframes):
    """Re-encode an arbitrary *src_video* into *dst_path* as a cdmd of exactly
    *nframes* frames at *canvas_w* x *canvas_h*.

    The source is decoded + scaled by ffmpeg at a frame rate chosen so its full
    duration maps onto *nframes* (keeping the clip in sync with the original's
    untouched sibling .wav).  Returns ``(ok, detail)``.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "need ffmpeg to convert video to .cdmd"
    if nframes <= 0:
        return False, "original cdmd has no frames to match"

    from ...core.video import (_encode_timeout, _timeout_error,
                               probe_video_duration)
    dur = probe_video_duration(src_video)
    fps_out = (nframes / dur) if (dur and dur > 0) else float(DEFAULT_FPS)
    fps_out = max(0.1, fps_out)

    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", src_video,
           "-vf", f"scale={canvas_w}:{canvas_h},fps={fps_out:.6f}",
           "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    limit = _encode_timeout(dur)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=limit,
                           creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, _timeout_error(limit)
    except OSError as e:
        return False, str(e)
    if r.returncode != 0 or not r.stdout:
        err = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return False, (err[-1] if err else "ffmpeg decode failed")

    frame_bytes = canvas_w * canvas_h * 3
    raw = r.stdout
    frames = [raw[i:i + frame_bytes]
              for i in range(0, len(raw) - frame_bytes + 1, frame_bytes)]
    if not frames:
        return False, "no frames decoded from replacement"
    try:
        write_cdmd(dst_path, frames, nframes, canvas_w, canvas_h)
    except OSError as e:
        return False, str(e)
    return True, f"→.cdmd {canvas_w}x{canvas_h}, {nframes}f"


# ---------------------------------------------------------------------------
# Audio sync helpers
# ---------------------------------------------------------------------------

def _wav_duration(wav_path):
    """Duration of a WAV file in seconds, or None if unreadable."""
    if not wav_path:
        return None
    try:
        with wave.open(wav_path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate:
                return frames / float(rate)
    except (wave.Error, OSError, EOFError):
        return None
    return None


def _sibling_wav(cdmd_path):
    """Return a paired ``<name>.wav`` next to *cdmd_path*, if it exists."""
    cand = os.path.splitext(cdmd_path)[0] + ".wav"
    return cand if os.path.isfile(cand) else None


# ---------------------------------------------------------------------------
# Dot-matrix (DMD) rendering
# ---------------------------------------------------------------------------

# Cache the tiled dot mask per (cols, rows, cell, dot_ratio) — every frame of
# a clip (and every clip of the same size) reuses it.
_mask_cache = {}


def _dot_mask_rgb(cols, rows, cell, dot_ratio):
    """Full-size RGB mask: white circular dot per cell, black gaps between."""
    key = (cols, rows, cell, round(dot_ratio, 3))
    cached = _mask_cache.get(key)
    if cached is not None:
        return cached

    # One anti-aliased cell (supersampled then downscaled), tiled across.
    ss = 4
    big = Image.new("L", (cell * ss, cell * ss), 0)
    dia = cell * ss * dot_ratio
    off = (cell * ss - dia) / 2.0
    ImageDraw.Draw(big).ellipse([off, off, off + dia, off + dia], fill=255)
    cell_mask = big.resize((cell, cell), Image.LANCZOS)

    row = Image.new("L", (cols * cell, cell), 0)
    for x in range(cols):
        row.paste(cell_mask, (x * cell, 0))
    full = Image.new("L", (cols * cell, rows * cell), 0)
    for y in range(rows):
        full.paste(row, (0, y * cell))

    full_rgb = full.convert("RGB")
    _mask_cache[key] = full_rgb
    return full_rgb


def render_dmd(img, cell=DMD_CELL, dot_ratio=DMD_DOT_RATIO,
               glow=True, border=DMD_BORDER):
    """Render an RGBA frame as a colour dot-matrix panel (RGB image).

    Each source pixel becomes a round LED dot of its colour on black; lit
    dots get a soft bloom and the panel is framed by a black bezel.
    """
    cols, rows = img.size
    big = img.convert("RGB").resize((cols * cell, rows * cell), Image.NEAREST)
    out = ImageChops.multiply(big, _dot_mask_rgb(cols, rows, cell, dot_ratio))

    if glow:
        # Soft additive bloom so bright LEDs halo into their neighbours.
        halo = out.filter(ImageFilter.GaussianBlur(max(1.0, cell * 0.45)))
        halo = halo.point(lambda v: (v * 45) // 100)
        out = ImageChops.add(out, halo)

    if border:
        framed = Image.new("RGB", (out.width + 2 * border,
                                   out.height + 2 * border), (0, 0, 0))
        framed.paste(out, (border, border))
        out = framed
    return out


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def _frame_to_rgb(img, dmd, cell):
    """Turn one composited RGBA frame into an RGB image for output.

    With *dmd* on it goes through the colour dot-matrix shader; otherwise it
    is just flattened onto black (padded to even dims for H.264).
    """
    if dmd:
        return render_dmd(img, cell=cell)
    ew, eh = img.width + (img.width & 1), img.height + (img.height & 1)
    flat = Image.new("RGB", (ew, eh), (0, 0, 0))
    flat.paste(img, (0, 0), img)
    return flat


def cdmd_to_png(cdmd_path, output_path, dmd=True, cell=DMD_CELL):
    """Render a (typically single-frame) cdmd to a last-frame PNG.

    With *dmd* on the still is rendered as a dot-matrix panel.  Returns the
    number of frames in the source file.
    """
    with open(cdmd_path, "rb") as f:
        data = f.read()
    last = None
    count = 0
    for img in iter_frames(data):
        last = img
        count += 1
    if last is None:
        raise ValueError(f"cdmd has no frames: {cdmd_path}")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    _frame_to_rgb(last, dmd, cell).save(output_path, "PNG")
    return count


def cdmd_to_mp4(cdmd_path, output_path, fps=None, dmd=True, cell=DMD_CELL):
    """Convert a multi-frame cdmd to MP4, muxing a sibling ``.wav`` if present.

    The frame rate is derived from the paired audio duration when available
    (so video and sound stay in sync); otherwise ``DEFAULT_FPS`` is used.
    With *dmd* on each frame is rendered as a colour dot-matrix panel.

    Returns the number of frames written.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found — needed to build MP4 from cdmd.")

    with open(cdmd_path, "rb") as f:
        data = f.read()
    nframes = parse_header(data)[0]
    wav = _sibling_wav(cdmd_path)

    if fps is None:
        dur = _wav_duration(wav) if wav else None
        fps = (nframes / dur) if (dur and dur > 0 and nframes > 0) else DEFAULT_FPS
        # Clamp to a sane range; some control sequences are very short.
        fps = max(1.0, min(fps, 60.0))

    # Render frames and pipe them straight into ffmpeg as raw RGB — avoids
    # writing/reading hundreds of large PNGs per clip (the real bottleneck).
    frames = iter_frames(data)
    try:
        first = _frame_to_rgb(next(frames), dmd, cell)
    except StopIteration:
        raise ValueError(f"cdmd has no frames: {cdmd_path}")
    w, h = first.size

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-nostats",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-framerate", f"{fps:.6f}", "-i", "-"]
    if wav:
        cmd += ["-i", wav, "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-pix_fmt", "yuv420p", output_path]

    def _err_tail():
        err.seek(0)
        return err.read()[-500:].decode("utf-8", "replace")

    err = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=err,
                            creationflags=_NO_WINDOW)
    written = 0
    try:
        proc.stdin.write(first.tobytes())
        written = 1
        for img in frames:
            proc.stdin.write(_frame_to_rgb(img, dmd, cell).tobytes())
            written += 1
        proc.stdin.close()
        proc.wait(timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (exit {proc.returncode}): {_err_tail()}")
        return written
    except (BrokenPipeError, subprocess.TimeoutExpired) as e:
        proc.kill()
        raise RuntimeError(f"ffmpeg failed: {e}\n{_err_tail()}")
    finally:
        err.close()


def decode_cdmd_file(cdmd_path, out_dir, rel_base=None, dmd=True, cell=DMD_CELL):
    """Decode one cdmd into *out_dir*, mirroring its relative path.

    Single-frame files become ``.png``; multi-frame files become ``.mp4``
    (falling back to a last-frame ``.png`` if ffmpeg is unavailable).  With
    *dmd* on, output is rendered as a colour dot-matrix panel.

    Returns ``(output_path, kind)`` where kind is ``"png"`` or ``"mp4"``.
    """
    rel = (os.path.relpath(cdmd_path, rel_base) if rel_base
           else os.path.basename(cdmd_path))
    stem = os.path.splitext(rel)[0]

    with open(cdmd_path, "rb") as f:
        head = f.read(16)
    nframes = parse_header(head)[0]

    if nframes <= 1:
        out = os.path.join(out_dir, stem + ".png")
        cdmd_to_png(cdmd_path, out, dmd=dmd, cell=cell)
        return out, "png"

    if check_ffmpeg():
        out = os.path.join(out_dir, stem + ".mp4")
        cdmd_to_mp4(cdmd_path, out, dmd=dmd, cell=cell)
        return out, "mp4"

    # No ffmpeg: still give the user a viewable still of the final frame.
    out = os.path.join(out_dir, stem + ".png")
    cdmd_to_png(cdmd_path, out, dmd=dmd, cell=cell)
    return out, "png"


# ---------------------------------------------------------------------------
# Replace-Video backend  (registered with core.video so the generic tab can
# scan / preview / stage .cdmd clips like any other video format)
# ---------------------------------------------------------------------------

class _CdmdBackend:
    """Adapts the cdmd codec to core.video's pluggable-backend interface."""

    def info(self, path):
        from ...core.video import VideoInfo
        res = cdmd_video_info(path)
        if res is None:
            return None
        cw, ch, nframes, fps, dur, wav = res
        return VideoInfo(
            path, vcodec="cdmd", width=cw, height=ch, fps=fps, duration=dur,
            has_audio=bool(wav), has_alpha=False, pix_fmt="argb",
            container="cdmd", nframes=nframes)

    def frame_png(self, path, pos, w, h):
        try:
            return preview_frame_png(path, pos, w, h)
        except Exception:
            return None

    def open_stream(self, path, w, h, fps, start=0.0):
        from ...core.video import GeneratorStream
        idx = int(round(start * fps)) if (fps and start) else 0
        try:
            return GeneratorStream(iter_preview_rgb(path, w, h, start_index=idx))
        except Exception:
            return None

    def audio_path(self, path):
        return _sibling_wav(path)

    def encode(self, src_path, dst_path, reference_path):
        """Re-encode *src_path* into *dst_path* as a cdmd matching the geometry
        and frame count of the original *reference_path* (so its sibling .wav
        stays in sync)."""
        if not os.path.isfile(src_path):
            return False, "replacement file not found"
        try:
            with open(reference_path, "rb") as f:
                head = f.read(16)
            nframes, cw, ch = parse_header(head)
        except (OSError, ValueError) as e:
            return False, f"can't read original .cdmd: {e}"
        return video_to_cdmd(src_path, dst_path, cw, ch, nframes)


def convert_all_cdmd(input_dir, output_dir, progress_cb=None, log_cb=None,
                     cancel_cb=None, dmd=True, cell=DMD_CELL):
    """Walk *input_dir* for ``.cdmd`` files and decode each into *output_dir*.

    Output preserves the source's relative directory structure.  Returns
    ``(converted, failed)`` counts.
    """
    def log(text, level="info"):
        if log_cb:
            log_cb(text, level)

    cdmd_files = []
    skipped_nonvideo = 0
    for root, _dirs, files in os.walk(input_dir):
        for fn in files:
            if not fn.lower().endswith(".cdmd"):
                continue
            path = os.path.join(root, fn)
            # Some assets (notably bitmap fonts under fonts/) reuse the .cdmd
            # extension with a different "dmd\0" magic — those aren't video.
            if is_cdmd(path):
                cdmd_files.append(path)
            else:
                skipped_nonvideo += 1
    cdmd_files.sort()

    if skipped_nonvideo:
        log(f"Skipping {skipped_nonvideo} non-video .cdmd file(s) "
            f"(font/glyph data).")
    if not cdmd_files:
        log("No video .cdmd files found to decode.")
        return 0, 0

    if not check_ffmpeg():
        log("ffmpeg not found — multi-frame clips will be saved as a "
            "last-frame PNG instead of MP4. Install ffmpeg for full video.",
            "warning")

    total = len(cdmd_files)
    log(f"Decoding {total} cdmd file(s)...")
    converted = failed = 0
    for i, path in enumerate(cdmd_files):
        if cancel_cb and cancel_cb():
            log("cdmd decode cancelled.", "warning")
            break
        name = os.path.basename(path)
        if progress_cb:
            progress_cb(i, total, name)
        try:
            decode_cdmd_file(path, output_dir, rel_base=input_dir,
                             dmd=dmd, cell=cell)
            converted += 1
        except Exception as e:  # one bad file shouldn't sink the batch
            failed += 1
            log(f"  Failed to decode {name}: {e}", "warning")
    if progress_cb:
        progress_cb(total, total, "Done")
    log(f"Decoded {converted}/{total} cdmd file(s)"
        + (f", {failed} failed." if failed else "."),
        "success" if converted else "warning")
    return converted, failed


# Make .cdmd a first-class Replace-Video format (scan / preview / stage).
try:
    from ...core.video import register_backend as _register_backend
    _register_backend(".cdmd", _CdmdBackend())
except Exception:  # core.video import shouldn't ever fail, but never block load
    pass
