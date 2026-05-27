"""Render WPC DMD scenes + animations + fonts from raw ROM bytes.

This is the "phase 2-4" core of the Williams extract pipeline, lifted
out so the CGC plugin can reuse it.  CGC's WPC-emulator remakes
(MM/AFM/MB) bundle the same Williams ROM the original DMD ran, so
walking the master tables produces the same scene/animation set --
just at a bigger pixel size to match the colorized LCD backbox.

Callers pass raw ``rom_bytes`` and a target ``output_dir``; the
function writes::

    output_dir/
      dmd_scenes/
        scene_NNNN_encXX_OFFSET.png
        pairs/pair_NNNN.png
        browse.mp4
        scenes.json
      animations/
        anim_scene_NNN_idxNNNN_NNNframes.mp4
        anim_NNNN_NNNframes.mp4
      fonts/
        font_NNNN_NNNglyphs.png

and returns a dict of counts + table addresses.  The CGC pipeline
overrides ``pixel_size`` to a much larger value (~30) since the LCD
display upscales the 128x32 DMD to something close to 1080p.
"""

import json
import os

from . import dmd_render
from . import wpc_decode


# How many image indices to try beyond the last known valid one
# before we conclude we've walked past the end of the table.
MAX_CONSECUTIVE_INVALID = 8

BROWSE_FPS = 2

# Animation playback rate — WPC ran the DMD at ~120 Hz but each
# animation frame is held for several refresh ticks decided by the
# game's 6809 code at runtime.  Bytes alone don't tell us the
# hold count; 8 fps gives a watchable approximation slow enough to
# read mid-frame text without blurring through.
ANIM_FPS = 8

# A frame counts as "blank" for the purposes of leading-blank trim
# if its bitmap area is tiny.  WPC animations often start with a
# 1x1 or 6x1 placeholder/marker frame before the real cinematic
# starts, and that placeholder ends up being the MP4's first frame
# (and therefore Explorer's thumbnail).
BLANK_FRAME_MAX_AREA = 24      # e.g. 1x1, 2x3, 3x7, 6x1 all blank

# After trimming leading blanks, an animation must have at least
# this many real frames to be worth rendering as an MP4.
MIN_ANIM_FRAMES_AFTER_TRIM = 3

# Scene-sequence detection (the TILT/MONSTER FISH/attract-mode
# cinematic finder).  WPC games store consecutive frames of a
# full-screen animation as a run of adjacent FullFrameImage table
# entries: 2 entries per displayable 4-shade frame (low+high planes).
# A "sequence" is a run of consecutive 4-shade frames where each
# differs from its neighbour by less than SCENE_SEQ_MAX_DIFF
# pixels — the threshold is high enough to allow real motion but
# low enough that a hard cut to an unrelated scene breaks the run.
SCENE_SEQ_MIN_FRAMES = 4
SCENE_SEQ_MAX_DIFF_RATIO = 0.30   # at most 30% of pixels may change
SCENE_SEQ_MIN_LIT = 16            # frame must have at least N lit
                                  # pixels to count (filters blanks)

# Safety cap on the FullFrameImage scan.
MAX_IMAGE_INDEX = 4000


class WpcDecodeError(RuntimeError):
    """Raised when a WPC ROM can't be parsed (no font/graphics table)."""


def _noop_log(msg, level="info"):
    pass


def _noop_progress(cur, tot, msg=""):
    pass


def _noop_cancel():
    pass


def extract_dmd_assets(
    rom_bytes,
    output_dir,
    *,
    pixel_size=dmd_render.DEFAULT_PIXEL_SIZE,
    color=dmd_render.DEFAULT_COLOR,
    browse_fps=BROWSE_FPS,
    anim_fps=ANIM_FPS,
    source_label=None,
    log_cb=None,
    progress_cb=None,
    check_cancel=None,
    phase_decode_cb=None,
    phase_animate_cb=None,
):
    """Decode WPC ``rom_bytes`` into PNG scenes + MP4 animations + font sheets.

    Writes ``dmd_scenes/``, ``animations/``, ``fonts/`` subfolders under
    *output_dir*.  Returns a dict of counts and the resolved table
    addresses (for the caller's scan_summary.txt).

    *pixel_size* controls how large each DMD dot is in the rendered
    output.  Williams uses 12 (a comfortable 1536x384 PNG).  CGC's
    WPC remakes use 30 to approximate the 3840x960 LCD-backbox feel.

    *phase_decode_cb* / *phase_animate_cb* are optional callables the
    pipeline can hook to bump its own phase indicator at the right
    moments (just before scene decoding and animation rendering).

    Raises :class:`WpcDecodeError` if the ROM doesn't carry a font
    table the decoder recognises.
    """
    log = log_cb or _noop_log
    progress = progress_cb or _noop_progress
    cancel = check_cancel or _noop_cancel

    scenes_dir = os.path.join(output_dir, "dmd_scenes")
    pairs_dir = os.path.join(scenes_dir, "pairs")
    anim_dir = os.path.join(output_dir, "animations")
    font_dir = os.path.join(output_dir, "fonts")
    os.makedirs(scenes_dir, exist_ok=True)
    os.makedirs(pairs_dir, exist_ok=True)
    os.makedirs(anim_dir, exist_ok=True)
    os.makedirs(font_dir, exist_ok=True)

    # ---- Locate the master tables ----
    log("Locating master tables (signature scan)...", "info")
    try:
        rom = wpc_decode.WpcRom(rom_bytes)
    except ValueError as e:
        raise WpcDecodeError(str(e))
    tables = wpc_decode.find_table_addresses(rom)
    if tables.font_ptr_rom is None:
        raise WpcDecodeError(
            "Could not find the WPC font-table signature in this "
            "ROM.  The game may use a layout this decoder doesn't "
            "recognise.")
    log(f"  font ptr      @ ROM 0x{tables.font_ptr_rom:06X}", "info")
    graphics_table = None
    if tables.graphics_ptr_rom is not None:
        log(f"  graphics ptr  @ ROM 0x{tables.graphics_ptr_rom:06X}", "info")
        graphics_table = wpc_decode.resolve_table_ptr(
            rom, tables.graphics_ptr_rom)
        if graphics_table is not None:
            log(f"  graphics data @ ROM 0x{graphics_table:06X}", "success")
    if tables.animation_ptr_rom is not None:
        log(f"  animation ptr @ ROM 0x{tables.animation_ptr_rom:06X}", "info")
    if graphics_table is None:
        raise WpcDecodeError(
            "Could not resolve the Graphics master table.  The "
            "font table signature matched but the graphics-table "
            "pointer didn't decode.")

    animation_table = None
    if tables.animation_ptr_rom is not None:
        animation_table = wpc_decode.resolve_table_ptr(
            rom, tables.animation_ptr_rom)
        if animation_table is not None:
            log(f"  animation data @ ROM 0x{animation_table:06X}", "success")

    # ---- Decode every image index, render PNGs + pairs ----
    if phase_decode_cb is not None:
        phase_decode_cb()
    log("Decoding every image index...", "info")
    rendered_scenes = []
    plane_cache = {}
    rendered_pairs = []
    encoding_counts = {}
    consecutive_invalid = 0
    idx = 0
    while idx < MAX_IMAGE_INDEX:
        cancel()
        plane = wpc_decode.decode_image_to_plane(rom, graphics_table, idx)
        if plane.status == wpc_decode.PLANE_TABLE_ENTRY_OOR:
            consecutive_invalid += 1
            if consecutive_invalid >= MAX_CONSECUTIVE_INVALID:
                break
            idx += 1
            continue
        consecutive_invalid = 0
        enc_key = f"0x{plane.encoding:02X}"
        if plane.status != wpc_decode.PLANE_VALID:
            encoding_counts[f"unimpl_{enc_key}"] = (
                encoding_counts.get(f"unimpl_{enc_key}", 0) + 1)
            idx += 1
            continue
        encoding_counts[enc_key] = encoding_counts.get(enc_key, 0) + 1
        plane_cache[idx] = plane.data

        png = os.path.join(
            scenes_dir,
            f"scene_{idx:04d}_enc{plane.encoding:02X}_"
            f"{plane.address:06X}.png")
        img = dmd_render._render_planes(plane.data, None, pixel_size, color)
        img.save(png, "PNG")
        rendered_scenes.append({
            "index": idx,
            "encoding": enc_key,
            "rom_offset": f"0x{plane.address:06X}",
            "png": os.path.basename(png),
        })

        if idx > 0 and idx % 2 == 1:
            low = plane_cache.get(idx - 1)
            high = plane.data
            if low is not None:
                pair_png = os.path.join(
                    pairs_dir, f"pair_{(idx - 1) // 2:04d}.png")
                pair_img = dmd_render._render_planes(
                    low, high, pixel_size, color)
                pair_img.save(pair_png, "PNG")
                rendered_pairs.append(os.path.basename(pair_png))

        if idx % 25 == 0:
            progress(len(rendered_scenes), len(rendered_scenes) + 1,
                     f"idx {idx}  enc {enc_key}")
        idx += 1
    total_scenes = len(rendered_scenes)
    progress(total_scenes, total_scenes, "decode complete")
    log(f"  decoded {total_scenes} scene(s)", "success")
    if rendered_pairs:
        log(f"  paired {len(rendered_pairs)} 4-shade composite(s)", "info")
    unimpl_total = sum(v for k, v in encoding_counts.items()
                       if k.startswith("unimpl_"))
    if unimpl_total:
        unimpl_keys = [k for k in encoding_counts if k.startswith("unimpl_")]
        log(f"  unimplemented encodings: "
            f"{unimpl_total} skipped ({', '.join(sorted(unimpl_keys))})",
            "warning")

    if rendered_scenes:
        log("Assembling browse.mp4...", "info")
        browse_path = os.path.join(scenes_dir, "browse.mp4")
        png_paths = [os.path.join(scenes_dir, s["png"])
                     for s in rendered_scenes]
        try:
            dmd_render.render_pngs_to_mp4(
                png_paths, browse_path, fps=browse_fps)
        except (RuntimeError, OSError) as e:
            log(f"  browse.mp4: ffmpeg error: {e}", "warning")

        with open(os.path.join(scenes_dir, "scenes.json"),
                  "w", encoding="utf-8") as f:
            json.dump({
                "source": source_label,
                "pixel_size": pixel_size,
                "encoding_distribution": encoding_counts,
                "scenes": rendered_scenes,
            }, f, indent=2)

    # ---- Animation phase: scene-sequences + sub-tables + fonts ----
    if phase_animate_cb is not None:
        phase_animate_cb()
    anim_count = 0
    font_count = 0

    seq_groups = _detect_scene_sequences(plane_cache)
    log(f"Scene-sequence groups: {len(seq_groups)}", "info")
    for gi, group in enumerate(seq_groups):
        cancel()
        _render_scene_sequence_mp4(
            group, gi, anim_dir, pixel_size, color, anim_fps, log)
        anim_count += 1

    if animation_table is None:
        log("No animation table located — skipping animations.", "warning")
    else:
        subs = wpc_decode.enumerate_sub_tables(
            rom, animation_table, max_tables=300)
        log(f"Found {len(subs)} animation sub-table(s).", "info")
        for i, sub in enumerate(subs):
            cancel()
            decoded = [wpc_decode.decode_vsi_frame(rom, sub, fi)
                       for fi in sub.frame_indices]
            decoded = [f for f in decoded if f.valid]
            if not decoded:
                continue
            # Sub-tables with a non-zero TableHeight use the no-header
            # form (every "image" is a glyph of fixed height) -- these
            # are fonts, not cinematic animations.
            if sub.table_height > 0:
                _render_font_strip(
                    decoded, sub, font_dir, pixel_size, color)
                font_count += 1
            else:
                trimmed = list(decoded)
                while (trimmed
                       and trimmed[0].width * trimmed[0].height
                       <= BLANK_FRAME_MAX_AREA):
                    trimmed.pop(0)
                if len(trimmed) < MIN_ANIM_FRAMES_AFTER_TRIM:
                    continue
                _render_animation_mp4(
                    trimmed, sub, anim_dir, pixel_size, color, anim_fps, log)
                anim_count += 1
            progress(i + 1, len(subs), f"sub-table {i + 1}/{len(subs)}")
        log(f"  animations: {anim_count}  fonts: {font_count}", "success")

    return {
        "scenes": total_scenes,
        "pairs": len(rendered_pairs),
        "animations": anim_count,
        "fonts": font_count,
        "encoding_counts": encoding_counts,
        "font_ptr_rom": tables.font_ptr_rom,
        "graphics_ptr_rom": tables.graphics_ptr_rom,
        "graphics_table": graphics_table,
        "animation_ptr_rom": tables.animation_ptr_rom,
        "animation_table": animation_table,
        "rom_size": rom.size,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_scene_sequences(plane_cache):
    """Group consecutive 4-shade full-frame frames into runs that look
    like one cinematic.

    Walks ``plane_cache`` (keyed by FullFrameImage table index) in
    steps of 2: indices (2N, 2N+1) form one displayable 4-shade
    frame.  Then walks those displayable frames in order, breaking
    the run whenever the next frame's index isn't ``current + 2``,
    the lit-pixel count is too low (blank frame), or the pixel
    difference exceeds ``SCENE_SEQ_MAX_DIFF_RATIO`` (hard cut).
    """
    displayable = []
    ordered_indices = sorted(plane_cache.keys())
    for i in range(0, len(ordered_indices) - 1, 2):
        a = ordered_indices[i]
        b = ordered_indices[i + 1]
        if b != a + 1:
            continue
        displayable.append((a, plane_cache[a], plane_cache[b]))

    groups = []
    current = []
    prev_combined = None
    prev_idx = None
    for disp_idx, low, high in displayable:
        combined = bytes(l | h for l, h in zip(low, high))
        lit = sum(bin(b).count("1") for b in combined)
        if lit < SCENE_SEQ_MIN_LIT:
            if len(current) >= SCENE_SEQ_MIN_FRAMES:
                groups.append(current)
            current = []
            prev_combined = None
            prev_idx = None
            continue
        if (prev_combined is not None
                and prev_idx is not None
                and disp_idx == prev_idx + 2):
            diff = sum(bin(a ^ b).count("1")
                       for a, b in zip(combined, prev_combined))
            max_diff = int(len(combined) * 8 * SCENE_SEQ_MAX_DIFF_RATIO)
            if diff <= max_diff:
                current.append((disp_idx, low, high))
                prev_combined = combined
                prev_idx = disp_idx
                continue
        if len(current) >= SCENE_SEQ_MIN_FRAMES:
            groups.append(current)
        current = [(disp_idx, low, high)]
        prev_combined = combined
        prev_idx = disp_idx
    if len(current) >= SCENE_SEQ_MIN_FRAMES:
        groups.append(current)
    return groups


def _render_scene_sequence_mp4(group, group_idx, anim_dir,
                               pixel_size, color, fps, log):
    """Render a scene-sequence group as a 4-shade MP4.

    The first frame is the highest-lit-count frame in the group
    (poster), then the group plays through in table order.
    """
    import shutil as _sh
    import tempfile
    tmp = tempfile.mkdtemp(prefix="williams_seq_")
    try:
        def lit_count(triple):
            _, low, high = triple
            return sum(bin(l | h).count("1")
                       for l, h in zip(low, high))
        poster = max(group, key=lit_count)
        render_order = [poster] + group
        for i, (_, low, high) in enumerate(render_order):
            png = os.path.join(tmp, f"frame_{i:06d}.png")
            img = dmd_render._render_planes(low, high, pixel_size, color)
            img.save(png, "PNG")
        start_idx = group[0][0]
        mp4 = os.path.join(
            anim_dir,
            f"anim_scene_{group_idx:03d}_"
            f"idx{start_idx:04d}_{len(group):03d}frames.mp4")
        png_paths = [os.path.join(tmp, f"frame_{i:06d}.png")
                     for i in range(len(render_order))]
        try:
            dmd_render.render_pngs_to_mp4(png_paths, mp4, fps=fps)
        except (RuntimeError, OSError) as e:
            log(f"  scene-seq {group_idx}: ffmpeg error: {e}", "warning")
    finally:
        _sh.rmtree(tmp, ignore_errors=True)


def _render_animation_mp4(frames, sub, anim_dir,
                          pixel_size, color, fps, log):
    """Place each VsiFrame in a 128x32 canvas and stitch to MP4.

    WPC animations frequently store two planes per displayable frame
    as consecutive table entries (low plane then high plane), giving
    4-shade brightness via the same ``(low + 2*high) / 3`` formula
    as the full-frame scenes.  We detect pairs by matching consecutive
    frames on (width, height, h_off, v_off) -- when they match, we
    render the pair through :func:`dmd_render._render_planes` as a
    4-shade composite; otherwise we render the frame as mono.

    The frame with the most lit pixels is duplicated at index 0 so
    the MP4's poster frame (used as the Explorer thumbnail) shows
    the animation's high-content moment.
    """
    import shutil as _sh
    import tempfile
    tmp = tempfile.mkdtemp(prefix="williams_anim_")
    try:
        planes = _planes_for_animation(frames)
        if not planes:
            return

        def lit_count(pair):
            low, high = pair
            if high is None:
                return sum(bin(b).count("1") for b in low)
            return sum(bin(low[i] | high[i]).count("1")
                       for i in range(len(low)))
        poster_idx = max(range(len(planes)),
                         key=lambda i: lit_count(planes[i]))
        render_order = [planes[poster_idx]] + planes
        for i, (low, high) in enumerate(render_order):
            png = os.path.join(tmp, f"frame_{i:06d}.png")
            img = dmd_render._render_planes(low, high, pixel_size, color)
            img.save(png, "PNG")
        mp4 = os.path.join(
            anim_dir,
            f"anim_{sub.sub_table_idx:04d}_"
            f"{len(planes):03d}frames.mp4")
        png_paths = [os.path.join(tmp, f"frame_{i:06d}.png")
                     for i in range(len(render_order))]
        try:
            dmd_render.render_pngs_to_mp4(png_paths, mp4, fps=fps)
        except (RuntimeError, OSError) as e:
            log(f"  anim_{sub.sub_table_idx:04d}: ffmpeg error: {e}",
                "warning")
    finally:
        _sh.rmtree(tmp, ignore_errors=True)


def _planes_for_animation(frames):
    """Group ``frames`` into ``(low_plane, high_plane)`` pairs.

    Three cases:

      - BicolorDirect frame (0xFF header) -- already carries both
        low and high planes inline in ``frame.data`` /
        ``frame.data_high``.  Render as one 4-shade frame.
      - Two adjacent Monochrome (0x00) frames with identical shape
        -- treat as low+high planes of one 4-shade frame.
      - Anything else -- render as solo mono (``high=None``).
    """
    out = []
    i = 0
    while i < len(frames):
        f0 = frames[i]
        if f0.data_high is not None:
            low = wpc_decode.vsi_frame_to_dmd_buffer(f0, "low")
            high = wpc_decode.vsi_frame_to_dmd_buffer(f0, "high")
            out.append((low, high))
            i += 1
            continue
        low = wpc_decode.vsi_frame_to_dmd_buffer(f0)
        high = None
        if i + 1 < len(frames):
            f1 = frames[i + 1]
            if (f1.data_high is None
                    and f1.width == f0.width and f1.height == f0.height
                    and f1.h_off == f0.h_off
                    and f1.v_off == f0.v_off):
                high = wpc_decode.vsi_frame_to_dmd_buffer(f1)
                i += 1
        out.append((low, high))
        i += 1
    return out


def _render_font_strip(frames, sub, font_dir, pixel_size, color):
    """Render all glyphs as a grid PNG (one row would be too wide).

    Lays out the proportional-width glyphs in a 16-glyph-per-row
    grid with a 1-pixel gap, each glyph drawn with the same
    DMD-dot rendering used for scenes.
    """
    from PIL import Image, ImageDraw
    r_c, g_c, b_c = color
    cell_h = sub.table_height
    max_w = max(f.width for f in frames)
    cell_w = max_w + 1
    cols = 16
    rows = (len(frames) + cols - 1) // cols
    img = Image.new("RGB",
                    (cols * cell_w * pixel_size,
                     rows * (cell_h + 1) * pixel_size),
                    (0, 0, 0))
    draw = ImageDraw.Draw(img)
    dot = pixel_size - 1
    for i, f in enumerate(frames):
        row = i // cols
        col = i % cols
        base_x = col * cell_w
        base_y = row * (cell_h + 1)
        src_row_bytes = (f.width + 7) // 8
        for r in range(min(f.height, cell_h)):
            for c in range(f.width):
                byte_idx = r * src_row_bytes + (c // 8)
                if byte_idx >= len(f.data):
                    continue
                bit = (f.data[byte_idx] >> (c % 8)) & 1
                if bit:
                    x0 = (base_x + c) * pixel_size
                    y0 = (base_y + r) * pixel_size
                    draw.rectangle(
                        [x0, y0, x0 + dot - 1, y0 + dot - 1],
                        fill=(r_c, g_c, b_c))
    png = os.path.join(
        font_dir,
        f"font_{sub.sub_table_idx:04d}_"
        f"{len(frames):03d}glyphs.png")
    img.save(png, "PNG")
