"""P3 VID to MP4 converter for Multimorphic DMD animation files.

P3/Multimorphic games (AMH, Rob Zombie, Domino's, Jetsons) use a custom
binary .VID format for dot-matrix display animations:

    [512 bytes]  Header
      byte 0: display width (128)
      byte 1: display height (32)
      byte 2: sub-frame width (64 or 128)
      byte 3: sub-frame height (32)
      byte 4: bits-per-pixel hint (4 or 8)
      byte 5: frame count hint (0 if >255)
      byte 6: max brightness (15)
      bytes 7-511: padding

Two frame formats exist, auto-detected via the frame count hint:

    4bpp (AMH):
      Each frame is width*height/2 bytes (2048 for 128x32).
      Each byte packs two 4-bit pixels (high nibble=left, low=right).
      Each pixel is a 4-bit monochrome brightness value (0-15).

    8bpp (Domino's, Rob Zombie, Jetsons):
      Each frame is width*height bytes (4096 for 128x32).
      Each byte is an RGB332 pixel:
        bits 7-5 (3 bits): red   (0-7)
        bits 4-2 (3 bits): green (0-7)
        bits 1-0 (2 bits): blue  (0-3)
      Confirmed by the chromaColor FPGA Verilog source (benheck/chromaColor)
      which decodes each byte as: r=data[7:5], g=data[4:2], b={data[1:0],0}.

Some 8bpp games (Jetsons, some Domino's files) store interleaved halves:
the raw frame count is 2x the display frame count (hint*2 == raw_frames).
Even-indexed raw frames contain the top half of the display; odd-indexed
frames contain the bottom half. The converter stacks both halves to
reconstruct the full-height display frame (e.g. 128x64 from two 128x32).

Requirements:
    - Pillow (already a dependency via UnityPy)
    - ffmpeg in PATH
"""

import glob as _glob
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw


# Default DMD rendering parameters (matching rundmd-to-video style)
DEFAULT_FPS = 30
DEFAULT_PIXEL_SIZE = 10
DEFAULT_COLOR = (191, 87, 0)  # Dark amber (4bpp monochrome games)
DEFAULT_GAMMA = 2.2

# Cached ffmpeg path (None = not searched yet, False = not found)
_ffmpeg_path = None


def find_ffmpeg():
    """Find the ffmpeg executable, searching PATH and common install locations.

    Returns:
        Path to ffmpeg executable, or None if not found.
    """
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path if _ffmpeg_path else None

    # First try PATH
    path = shutil.which("ffmpeg")
    if path:
        _ffmpeg_path = path
        return path

    # On Windows, search common install locations
    if sys.platform == "win32":
        search_dirs = []

        # WinGet packages
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            search_dirs.extend(
                _glob.glob(os.path.join(local_app,
                    "Microsoft", "WinGet", "Packages", "*ffmpeg*", "*", "bin")))

        # Scoop
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            search_dirs.append(os.path.join(userprofile, "scoop", "shims"))

        # Chocolatey
        choco = os.environ.get("ChocolateyInstall",
                               r"C:\ProgramData\chocolatey")
        search_dirs.append(os.path.join(choco, "bin"))

        # Common manual install locations
        search_dirs.extend([
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
        ])

        for d in search_dirs:
            candidate = os.path.join(d, "ffmpeg.exe")
            if os.path.isfile(candidate):
                _ffmpeg_path = candidate
                return candidate

    _ffmpeg_path = False
    return None


def check_ffmpeg():
    """Check if ffmpeg is available."""
    return find_ffmpeg() is not None


def parse_vid_header(data, data_size=None, frame_data=None):
    """Parse a 512-byte VID header.

    The actual bits-per-pixel (4 or 8) is auto-detected by comparing the
    frame-count hint against the data size at both 4bpp and 8bpp frame
    sizes.  When the hint is ambiguous, a sample of the frame data is
    checked: if many bytes exceed 15, the file is 8bpp (since 4bpp packs
    two 0-15 values per byte, most bytes would be <= 15 only when both
    pixels are dark).

    Args:
        data: At least 512 bytes of header data.
        data_size: Total size of frame data (file size minus 512).
            Used for auto-detecting bpp.  If None, uses the header's
            bpp field directly.
        frame_data: Raw frame bytes (or at least the first 4096 bytes).
            Used as fallback when hint-based detection is ambiguous.

    Returns:
        dict with keys: width, height, bpp, max_brightness, header_size,
        subframes (1 or 2 — number of raw frames per display frame)
    """
    if len(data) < 512:
        raise ValueError(f"VID header too short: {len(data)} bytes (need 512)")

    width = data[0]
    height = data[1]
    bpp_field = data[4]
    frame_hint = data[5]
    max_brightness = data[6]

    if width == 0 or height == 0:
        raise ValueError(f"Invalid VID dimensions: {width}x{height}")
    if bpp_field == 0:
        raise ValueError("Invalid VID: 0 bits per pixel")

    # Auto-detect actual bpp from frame hint vs data size.
    # Some games (AMH) use 4bpp, others (Domino's, Rob Zombie, Jetsons)
    # use 8bpp, but both may report bpp=4 in the header field.
    bpp = bpp_field
    detected = False
    subframes = 1  # raw frames per display frame (2 = sub-frame pairs)

    if data_size is not None and data_size > 0:
        frame_size_4 = (width * height) // 2   # 4bpp: 2 pixels per byte
        frame_size_8 = width * height           # 8bpp: 1 pixel per byte

        frames_4 = data_size // frame_size_4 if frame_size_4 > 0 else 0
        frames_8 = data_size // frame_size_8 if frame_size_8 > 0 else 0

        if frame_hint > 0:
            # Hint matches count (exact or mod 256 for large files)
            match_4 = (frame_hint == frames_4 or
                       (frames_4 > 255 and frame_hint == frames_4 % 256))
            match_8 = (frame_hint == frames_8 or
                       (frames_8 > 255 and frame_hint == frames_8 % 256))

            # Hint matches half the 8bpp count (sub-frame pairs)
            hint_half_8 = (frame_hint * 2 == frames_8 or
                           (frames_8 > 255 and
                            (frame_hint * 2) % 256 == frames_8 % 256))

            if match_8 and not match_4:
                bpp = 8
                detected = True
            elif match_4 and not match_8 and not hint_half_8:
                bpp = 4
                detected = True
            elif hint_half_8 and not match_4:
                # hint is half the 8bpp frame count — sub-frame pairs
                bpp = 8
                subframes = 2
                detected = True

        if bpp_field == 8:
            bpp = 8
            detected = True

    # Fallback: compare high-nibble and low-nibble distributions.
    # In 4bpp each byte packs two independent pixel values, so the high
    # and low nibble histograms are nearly identical (cosine similarity
    # > 0.98 in practice).  In 8bpp each byte is one pixel, so the two
    # nibble histograms diverge (similarity typically < 0.7).
    if not detected and frame_data is not None and len(frame_data) >= 1024:
        sample = frame_data[:min(4096, len(frame_data))]
        high_hist = [0] * 16
        low_hist = [0] * 16
        for byte in sample:
            high_hist[(byte >> 4) & 0x0F] += 1
            low_hist[byte & 0x0F] += 1
        total = len(sample)
        h_n = [h / total for h in high_hist]
        l_n = [lo / total for lo in low_hist]
        dot = sum(a * b for a, b in zip(h_n, l_n))
        mag_h = sum(a * a for a in h_n) ** 0.5
        mag_l = sum(b * b for b in l_n) ** 0.5
        similarity = dot / (mag_h * mag_l) if mag_h > 0 and mag_l > 0 else 1.0
        if similarity < 0.95:
            bpp = 8

    return {
        "width": width,
        "height": height,
        "bpp": bpp,
        "max_brightness": max_brightness if max_brightness > 0 else 15,
        "header_size": 512,
        "subframes": subframes,
    }


def render_frame(frame_data, width, height, bpp=4,
                 pixel_size=DEFAULT_PIXEL_SIZE,
                 color=DEFAULT_COLOR, gamma=DEFAULT_GAMMA,
                 max_brightness=15):
    """Render a single VID frame as a PIL Image with DMD dot effect.

    For 4bpp: each byte contains two 4-bit pixels
        (high nibble = left pixel, low nibble = right pixel).
        Rendered as monochrome amber dots.
    For 8bpp: each byte is an RGB332 pixel — red (3 bits), green (3 bits),
        blue (2 bits).  Decoded directly to full RGB color.

    Pixels are drawn as (pixel_size-1) x (pixel_size-1) squares with a
    1px gap, giving the characteristic DMD dot-matrix look.

    Args:
        frame_data: Raw bytes for one frame.
        width: Frame width in pixels.
        height: Frame height in pixels.
        bpp: Bits per pixel (4 or 8).
        pixel_size: Scale factor (each DMD pixel becomes pixel_size x pixel_size).
        color: Base RGB color tuple for the dots (used for 4bpp only).
        gamma: Gamma correction exponent (used for 4bpp only).
        max_brightness: Maximum brightness value (used for 4bpp only).

    Returns:
        PIL Image (RGB).
    """
    img_w = width * pixel_size
    img_h = height * pixel_size
    img = Image.new("RGB", (img_w, img_h), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    dot_size = pixel_size - 1  # 1px gap between dots

    if bpp == 8:
        # 8bpp RGB332: bits 7-5 = red (0-7), bits 4-2 = green (0-7),
        # bits 1-0 = blue (0-3).  Matches the chromaColor FPGA decoding:
        #   r = dataOut[7:5], g = dataOut[4:2], b = {dataOut[1:0], 1'b0}
        for y in range(height):
            for x in range(width):
                idx = y * width + x
                if idx >= len(frame_data):
                    break
                val = frame_data[idx]
                if val == 0:
                    continue
                dr = ((val >> 5) & 7) * 255 // 7
                dg = ((val >> 2) & 7) * 255 // 7
                db = (val & 3) * 255 // 3
                x0 = x * pixel_size
                y0 = y * pixel_size
                draw.rectangle(
                    [x0, y0, x0 + dot_size - 1, y0 + dot_size - 1],
                    fill=(dr, dg, db))
    else:
        # 4bpp: two pixels per byte (high nibble = left, low = right)
        # Monochrome amber rendering
        r, g, b = color
        inv_gamma = 1.0 / gamma
        byte_idx = 0
        for y in range(height):
            for x in range(0, width, 2):
                if byte_idx >= len(frame_data):
                    break

                byte = frame_data[byte_idx]
                byte_idx += 1

                left_val = (byte >> 4) & 0x0F
                right_val = byte & 0x0F

                for dx, val in ((0, left_val), (1, right_val)):
                    px = x + dx
                    if val > 0:
                        intensity = (val / max_brightness) ** inv_gamma
                        dr = int(r * intensity)
                        dg = int(g * intensity)
                        db = int(b * intensity)

                        x0 = px * pixel_size
                        y0 = y * pixel_size
                        draw.rectangle(
                            [x0, y0, x0 + dot_size - 1, y0 + dot_size - 1],
                            fill=(dr, dg, db))

    return img


def convert_vid_to_mp4(vid_path, output_path, fps=DEFAULT_FPS,
                       pixel_size=DEFAULT_PIXEL_SIZE, color=DEFAULT_COLOR,
                       gamma=DEFAULT_GAMMA):
    """Convert a single .VID file to MP4 video.

    Args:
        vid_path: Path to input .VID file.
        output_path: Path for output .mp4 file.
        fps: Frames per second (default 30).
        pixel_size: Scale factor for DMD dots.
        color: RGB tuple for dot color.
        gamma: Gamma correction exponent.

    Returns:
        Number of frames converted.

    Raises:
        FileNotFoundError: If vid_path doesn't exist.
        ValueError: If VID format is invalid.
        RuntimeError: If ffmpeg is not available or fails.
    """
    if not os.path.isfile(vid_path):
        raise FileNotFoundError(f"VID file not found: {vid_path}")

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg to convert VID files to MP4.")

    with open(vid_path, "rb") as f:
        header_data = f.read(512)
        body = f.read()
        header = parse_vid_header(header_data, data_size=len(body),
                                  frame_data=body)

    width = header["width"]
    height = header["height"]
    bpp = header["bpp"]
    max_bright = header["max_brightness"]
    subframes = header["subframes"]

    if bpp == 8:
        frame_size = width * height          # 8bpp: 1 byte per pixel
    else:
        frame_size = (width * height) // 2   # 4bpp: 2 pixels per byte

    raw_count = len(body) // frame_size

    if raw_count == 0:
        raise ValueError(f"VID file has no frames: {vid_path}")

    # When interleaved halves are detected (hint*2 == raw frames), the file
    # stores a taller display (e.g. 128x64) as alternating top/bottom halves:
    # even-indexed raw frames = top half, odd-indexed = bottom half.
    # Stack them vertically to reconstruct the full display frame.
    if subframes == 2:
        frame_count = raw_count // 2
        render_height = height * 2  # full display is double the header height
    else:
        frame_count = raw_count
        render_height = height

    if frame_count == 0:
        raise ValueError(f"VID file has no frames: {vid_path}")

    # Render frames to temp PNGs
    temp_dir = tempfile.mkdtemp(prefix="spooky_vid_")
    try:
        for i in range(frame_count):
            if subframes == 2:
                # Stack top half (even) + bottom half (odd) into full frame
                off_top = (i * 2) * frame_size
                off_bot = (i * 2 + 1) * frame_size
                top_data = body[off_top:off_top + frame_size]
                bot_data = body[off_bot:off_bot + frame_size]

                top_img = render_frame(top_data, width, height, bpp=bpp,
                                       pixel_size=pixel_size, color=color,
                                       gamma=gamma, max_brightness=max_bright)
                bot_img = render_frame(bot_data, width, height, bpp=bpp,
                                       pixel_size=pixel_size, color=color,
                                       gamma=gamma, max_brightness=max_bright)

                img = Image.new("RGB",
                                (width * pixel_size, render_height * pixel_size),
                                (0, 0, 0))
                img.paste(top_img, (0, 0))
                img.paste(bot_img, (0, height * pixel_size))
            else:
                offset = i * frame_size
                frame_data = body[offset:offset + frame_size]

                img = render_frame(frame_data, width, height, bpp=bpp,
                                   pixel_size=pixel_size, color=color,
                                   gamma=gamma, max_brightness=max_bright)

            png_path = os.path.join(temp_dir, f"frame_{i:06d}.png")
            img.save(png_path, "PNG")

        # Assemble MP4 with ffmpeg
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps),
            "-i", os.path.join(temp_dir, "frame_%06d.png"),
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "slow",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (exit {result.returncode}): {result.stderr[-500:]}")

        return frame_count

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def convert_all_vids(input_dir, output_dir, fps=DEFAULT_FPS,
                     pixel_size=DEFAULT_PIXEL_SIZE, color=DEFAULT_COLOR,
                     gamma=DEFAULT_GAMMA, progress_cb=None, log_cb=None,
                     cancel_event=None):
    """Convert all .VID files in a directory tree to MP4.

    Args:
        input_dir: Root directory to search for .VID files.
        output_dir: Root directory for output MP4 files (preserves structure).
        fps: Frames per second.
        pixel_size: Scale factor for DMD dots.
        color: RGB tuple for dot color.
        gamma: Gamma correction exponent.
        progress_cb: Optional callback(files_done, total_files, current_name).
        log_cb: Optional callback(text, level) for logging.
        cancel_event: Optional threading.Event checked between files.

    Returns:
        List of output MP4 paths (relative to output_dir).
    """
    def log(text, level="info"):
        if log_cb:
            log_cb(text, level)

    # Find all .VID files (skip the extracted assets folder itself)
    vid_files = []
    for root, dirs, files in os.walk(input_dir):
        if "_extracted_assets" in root.split(os.sep):
            continue
        for f in files:
            if f.upper().endswith(".VID"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, input_dir)
                vid_files.append(rel)

    if not vid_files:
        log("No .VID files found")
        return []

    log(f"Found {len(vid_files)} VID files to convert")

    if not find_ffmpeg():
        log("ffmpeg not found - skipping VID to MP4 conversion", "warning")
        log("Install ffmpeg to enable automatic VID conversion", "warning")
        return []

    os.makedirs(output_dir, exist_ok=True)
    converted = []

    for i, rel_path in enumerate(vid_files):
        if cancel_event and cancel_event.is_set():
            log("VID conversion cancelled", "warning")
            break

        vid_path = os.path.join(input_dir, rel_path)
        # Change extension to .mp4
        mp4_rel = os.path.splitext(rel_path)[0] + ".mp4"
        mp4_path = os.path.join(output_dir, mp4_rel)

        name = os.path.basename(rel_path)
        if progress_cb:
            progress_cb(i, len(vid_files), name)

        try:
            frames = convert_vid_to_mp4(
                vid_path, mp4_path, fps=fps,
                pixel_size=pixel_size, color=color, gamma=gamma)
            converted.append(mp4_rel)
        except Exception as e:
            log(f"  Error converting {name}: {e}", "warning")

    if progress_cb:
        progress_cb(len(vid_files), len(vid_files), "Done")

    log(f"Converted {len(converted)}/{len(vid_files)} VID files to MP4", "success")
    return converted
