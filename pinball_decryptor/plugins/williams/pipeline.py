"""Williams (WPC-era) extract pipeline.

Input is a MAME-style .zip containing the game ROM(s) and DCS sound
ROM(s).  We extract the game-ROM bytes, locate the Graphics master
table via the 6809 instruction-signature scan in :mod:`.wpc_decode`,
then walk every image index and decode each plane using the actual
WPC compression format (ported from `permartinson/wpcedit.js`_).

For every plane that decodes cleanly we render a PNG.  Consecutive
plane pairs are also paired into 4-shade images (low+high planes
combined as ``(low + 2*high) / 3`` brightness).

Output layout::

    <output_dir>/
      <game_key>/
        dmd_scenes/
          scene_0001_enc01_OFFSET.png       (single plane)
          scene_0002_enc04_OFFSET.png
          ...
          pairs/
            pair_0001_OFFSET.png            (paired 4-shade composite)
            ...
          browse.mp4                        (every scene at 2 fps)
          scenes.json                       (offsets + encoding stats)
        roms/
          fshtl_5.rom
          ft_u18.l1
        scan_summary.txt

This pipeline replaces the heuristic byte-scanner in earlier
versions.  It produces real game content — title cards, jackpot
splashes, mode-start screens, sprite atlases — because it walks
the same data structures the WPC game code uses at runtime.

.. _permartinson/wpcedit.js: https://github.com/permartinson/wpcedit.js
"""

import json
import os
import zipfile

from ...core.checksums import generate_checksums
from ...core.pipeline_base import BasePipeline, PipelineError
from . import dcs_decode
from . import dmd_render
from . import wpc_decode
from .formats import detect_game, list_game_roms
from .games import GAME_DB


PHASES = ("Detect", "Unzip", "Find tables", "Decode scenes",
          "Render animations", "Extract audio", "Cleanup")

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

# A sub-table is treated as a font (rendered as a sprite-sheet PNG
# instead of a video) when it has many frames AND the median frame
# is small.  The median is more robust than max — some font tables
# include a few oversized "joker" glyphs that would otherwise push
# max_dim above the cap and miscategorise the sub-table.
FONT_MIN_FRAMES = 30
FONT_MAX_MEDIAN_DIM = 14

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


class ExtractPipeline(BasePipeline):
    """Real WPC DMD decoder pipeline for Williams ROMs."""

    def __init__(self, zip_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.zip_path = zip_path
        self.output_dir = output_dir

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        key = detect_game(self.zip_path)
        if key is None:
            raise PipelineError(
                "Detect",
                f"Cannot identify game from: "
                f"{os.path.basename(self.zip_path)}\n\n"
                f"Expected a MAME ROM zip containing files like "
                f"`fshtl_5.rom`, `ww_lh6.rom`, or `nofe2_3x.rom`.\n"
                f"Known games: "
                f"{', '.join(info['display'] for info in GAME_DB.values())}.")
        info = GAME_DB[key]
        self._log(f"Game detected: {info['display']} "
                  f"({info['platform']}, {info['year']})", "success")
        self._check_cancel()

        game_dir = os.path.join(self.output_dir, key)
        rom_dir = os.path.join(game_dir, "roms")
        scenes_dir = os.path.join(game_dir, "dmd_scenes")
        pairs_dir = os.path.join(scenes_dir, "pairs")
        os.makedirs(rom_dir, exist_ok=True)
        os.makedirs(scenes_dir, exist_ok=True)
        os.makedirs(pairs_dir, exist_ok=True)

        # ---- Unzip ----
        self._set_phase(1)
        self._log("Extracting ROM files...", "info")
        game_roms, sound_roms = list_game_roms(self.zip_path, key)
        if not game_roms:
            raise PipelineError(
                "Unzip",
                f"No game ROM found inside {os.path.basename(self.zip_path)}.\n"
                f"Expected one of: {', '.join(info['game_roms'])}.")
        self._log(f"  game ROMs:  {', '.join(game_roms)}", "info")
        self._log(f"  sound ROMs: "
                  f"{', '.join(sound_roms) if sound_roms else '(none found)'}",
                  "info")
        with zipfile.ZipFile(self.zip_path, "r") as zf:
            for n in game_roms + sound_roms:
                self._check_cancel()
                zf.extract(n, rom_dir)

        # ---- Locate the master tables ----
        self._set_phase(2)
        self._log("Locating master tables (signature scan)...", "info")
        # WPC ROMs come as a single .rom file; we use the first one
        # in the list as the canonical game ROM (the others, if any,
        # are usually variants or revisions that share the same
        # table layout).
        rom_path = os.path.join(rom_dir, game_roms[0])
        with open(rom_path, "rb") as f:
            rom_bytes = f.read()
        try:
            rom = wpc_decode.WpcRom(rom_bytes)
        except ValueError as e:
            raise PipelineError("Find tables", str(e))
        tables = wpc_decode.find_table_addresses(rom)
        if tables.font_ptr_rom is None:
            raise PipelineError(
                "Find tables",
                "Could not find the WPC font-table signature in this "
                "ROM.  The game may use a layout this decoder doesn't "
                "recognise.")
        self._log(f"  font ptr      @ ROM 0x{tables.font_ptr_rom:06X}",
                  "info")
        graphics_table = None
        if tables.graphics_ptr_rom is not None:
            self._log(f"  graphics ptr  @ ROM 0x{tables.graphics_ptr_rom:06X}",
                      "info")
            graphics_table = wpc_decode.resolve_table_ptr(
                rom, tables.graphics_ptr_rom)
            if graphics_table is not None:
                self._log("  graphics data @ ROM "
                          f"0x{graphics_table:06X}", "success")
        if tables.animation_ptr_rom is not None:
            self._log(f"  animation ptr @ ROM "
                      f"0x{tables.animation_ptr_rom:06X}", "info")
        if graphics_table is None:
            raise PipelineError(
                "Find tables",
                "Could not resolve the Graphics master table.  The "
                "font table signature matched but the graphics-table "
                "pointer didn't decode.")

        # Resolve animation table (used in the next phase)
        animation_table = None
        if tables.animation_ptr_rom is not None:
            animation_table = wpc_decode.resolve_table_ptr(
                rom, tables.animation_ptr_rom)
            if animation_table is not None:
                self._log(f"  animation data @ ROM 0x{animation_table:06X}",
                          "success")

        # ---- Decode every image index, render PNGs + pairs ----
        self._set_phase(3)
        self._log("Decoding every image index...", "info")
        rendered_scenes = []         # one per FullFrameImage index
        # Cache the decoded plane bytes by table index so the
        # sequence-detection pass below doesn't have to re-decode.
        plane_cache = {}             # {idx: bytes(512)}
        rendered_pairs = []
        encoding_counts = {}
        consecutive_invalid = 0
        idx = 0
        max_idx = 4000  # safety cap
        while idx < max_idx:
            self._check_cancel()
            plane = wpc_decode.decode_image_to_plane(
                rom, graphics_table, idx)
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
            img = dmd_render._render_planes(
                plane.data, None,
                dmd_render.DEFAULT_PIXEL_SIZE,
                dmd_render.DEFAULT_COLOR)
            img.save(png, "PNG")
            rendered_scenes.append({
                "index": idx,
                "encoding": enc_key,
                "rom_offset": f"0x{plane.address:06X}",
                "png": os.path.basename(png),
            })

            # 4-shade composite pair (idx, idx+1) — but only at even
            # indices (the natural WPC pairing).  decodeFullFrameGraphic
            # always pairs (2N, 2N+1).
            if idx > 0 and idx % 2 == 1:
                low = plane_cache.get(idx - 1)
                high = plane.data
                if low is not None:
                    pair_png = os.path.join(
                        pairs_dir, f"pair_{(idx - 1) // 2:04d}.png")
                    pair_img = dmd_render._render_planes(
                        low, high,
                        dmd_render.DEFAULT_PIXEL_SIZE,
                        dmd_render.DEFAULT_COLOR)
                    pair_img.save(pair_png, "PNG")
                    rendered_pairs.append(os.path.basename(pair_png))

            if idx % 25 == 0 or idx + 1 == max_idx:
                self._progress(
                    len(rendered_scenes), len(rendered_scenes) + 1,
                    f"idx {idx}  enc {enc_key}")
            idx += 1
        total = len(rendered_scenes)
        self._progress(total, total, "decode complete")
        self._log(f"  decoded {total} scene(s)", "success")
        if rendered_pairs:
            self._log(f"  paired {len(rendered_pairs)} 4-shade composite(s)",
                      "info")
        unimpl_total = sum(v for k, v in encoding_counts.items()
                           if k.startswith("unimpl_"))
        if unimpl_total:
            unimpl_keys = [k for k in encoding_counts if k.startswith("unimpl_")]
            self._log(f"  unimplemented encodings: "
                      f"{unimpl_total} skipped ({', '.join(sorted(unimpl_keys))})",
                      "warning")

        # ---- browse.mp4 + scenes.json ----
        if rendered_scenes:
            self._log("Assembling browse.mp4...", "info")
            browse_path = os.path.join(scenes_dir, "browse.mp4")
            png_paths = [os.path.join(scenes_dir, s["png"])
                         for s in rendered_scenes]
            try:
                dmd_render.render_pngs_to_mp4(
                    png_paths, browse_path, fps=BROWSE_FPS)
            except (RuntimeError, OSError) as e:
                self._log(f"  browse.mp4: ffmpeg error: {e}", "warning")

            with open(os.path.join(scenes_dir, "scenes.json"),
                      "w", encoding="utf-8") as f:
                json.dump({
                    "game": info["display"],
                    "source": os.path.basename(self.zip_path),
                    "encoding_distribution": encoding_counts,
                    "scenes": rendered_scenes,
                }, f, indent=2)

        summary_path = os.path.join(game_dir, "scan_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"Game: {info['display']}\n")
            f.write(f"Source: {os.path.basename(self.zip_path)}\n")
            f.write(f"ROM size: {rom.size:,} bytes\n")
            f.write(f"Font table ptr      @ 0x{tables.font_ptr_rom:06X}\n")
            if tables.graphics_ptr_rom is not None:
                f.write(
                    f"Graphics table ptr  @ 0x{tables.graphics_ptr_rom:06X}\n")
                f.write(f"Graphics table data @ 0x{graphics_table:06X}\n")
            if tables.animation_ptr_rom is not None:
                f.write(
                    f"Animation table ptr @ 0x{tables.animation_ptr_rom:06X}\n")
            f.write(f"\nScenes rendered: {total}\n")
            f.write(f"Pairs rendered:  {len(rendered_pairs)}\n")
            f.write("\nEncoding distribution:\n")
            for k in sorted(encoding_counts):
                f.write(f"  {k}: {encoding_counts[k]}\n")

        # ---- Animation phase: full-frame sequence groups + table-driven anims + fonts ----
        self._set_phase(4)
        anim_dir = os.path.join(game_dir, "animations")
        font_dir = os.path.join(game_dir, "fonts")
        os.makedirs(anim_dir, exist_ok=True)
        os.makedirs(font_dir, exist_ok=True)
        anim_count = 0
        font_count = 0

        # ---- Full-frame scene-sequence detection ----
        # Walk every (idx, idx+1) pair to build 4-shade frames, then
        # group runs of consecutive frames whose pixel-difference
        # stays below the threshold.  Each group is one cinematic.
        seq_groups = self._detect_scene_sequences(plane_cache)
        self._log(f"Scene-sequence groups: {len(seq_groups)}", "info")
        for gi, group in enumerate(seq_groups):
            self._check_cancel()
            self._render_scene_sequence_mp4(group, gi, anim_dir)
            anim_count += 1
        if animation_table is None:
            self._log("No animation table located — skipping animations.",
                      "warning")
        else:
            subs = wpc_decode.enumerate_sub_tables(
                rom, animation_table, max_tables=300)
            self._log(f"Found {len(subs)} animation sub-table(s).", "info")
            for i, sub in enumerate(subs):
                self._check_cancel()
                # Decode every frame in this sub-table first
                decoded = [wpc_decode.decode_vsi_frame(rom, sub, idx)
                           for idx in sub.frame_indices]
                decoded = [f for f in decoded if f.valid]
                if not decoded:
                    continue
                # WPC sub-tables with a non-zero TableHeight use the
                # no-header form: every "image" is a glyph of fixed
                # height (the table's per-row stride).  These are
                # alphabets and digit sets, *not* cinematic animations
                # — so we render them as a sprite-sheet strip.
                # table_h == 0 means the sub-table uses the header
                # form (per-frame width *and* height), which is what
                # real motion animations look like.
                is_font = sub.table_height > 0
                if is_font:
                    self._render_font_strip(decoded, sub, font_dir)
                    font_count += 1
                else:
                    # Trim leading marker frames — the first few are
                    # often 1x1 or 6x1 placeholders that the game's
                    # animation engine uses as a sync marker.  After
                    # trimming, require enough real frames to be a
                    # meaningful animation.
                    trimmed = list(decoded)
                    while (trimmed
                           and trimmed[0].width * trimmed[0].height
                           <= BLANK_FRAME_MAX_AREA):
                        trimmed.pop(0)
                    if len(trimmed) < MIN_ANIM_FRAMES_AFTER_TRIM:
                        continue
                    self._render_animation_mp4(trimmed, sub, anim_dir)
                    anim_count += 1
                self._progress(i + 1, len(subs),
                               f"sub-table {i + 1}/{len(subs)}")
            self._log(f"  animations: {anim_count}  fonts: {font_count}",
                      "success")

        # ---- Extract audio (DCS sound ROMs) — DCS games only ----
        # Pre-DCS games (YM2151 sound board) have no statically
        # decodable audio; they skip this phase and the GUI omits it
        # from the indicator, so the remaining phases renumber.
        dcs_track_count = 0
        cleanup_phase = 5
        if dcs_decode.is_dcs_rom(self.zip_path):
            self._set_phase(5)
            dcs_track_count = self._extract_dcs_audio(game_dir)
            cleanup_phase = 6

        # ---- Cleanup / checksums ----
        self._set_phase(cleanup_phase)
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            game_dir, log_cb=self._log, progress_cb=self._progress)

        dcs_help = ""
        if dcs_track_count:
            dcs_help = ("\n  sounds/track_*.wav — every DCS music cue, "
                        "voice line, and sound effect, one WAV per "
                        "track (indexed in sounds/manifest.json).")

        self._log("Done.", "success")
        self._done(
            True,
            f"{info['display']} extracted.\n\n"
            f"Output:        {game_dir}\n"
            f"Scenes (PNGs): {total}\n"
            f"4-shade pairs: {len(rendered_pairs)}\n"
            f"Animations:    {anim_count}\n"
            f"Fonts:         {font_count}\n"
            f"DCS tracks:    {dcs_track_count}\n"
            f"Files checksummed: {n}\n\n"
            f"What you get:\n"
            f"  dmd_scenes/scene_*.png — every still bitmap in the "
            f"ROM (jackpot splashes, mode-start screens).\n"
            f"  dmd_scenes/pairs/pair_*.png — 4-shade composites "
            f"where consecutive planes pair as low+high.\n"
            f"  animations/anim_*.mp4 — true game animations from "
            f"the WPC animation table, one MP4 per sequence.\n"
            f"  fonts/font_*.png — sprite-sheet strips of the DMD "
            f"glyph atlases (alphabet, numerals, punctuation)."
            + dcs_help)

    # ------------------------------------------------------------------
    # DCS audio extraction
    # ------------------------------------------------------------------

    def _extract_dcs_audio(self, game_dir):
        """Decode the game's DCS sound ROMs into per-track WAVs.

        DCS games (1993-1998) store music, speech, and SFX as
        compressed digital audio; :mod:`.dcs_decode` extracts every
        track via the bundled DCSExplorer decoder.  Pre-DCS games use
        the older YM2151 sound board, which can't be decoded
        statically — those are reported and skipped, no error.

        Returns the number of tracks extracted (0 when not a DCS game
        or the decoder is unavailable).
        """
        self._log("Decoding DCS sound ROMs...", "info")
        sounds_dir = os.path.join(game_dir, "sounds")
        try:
            result = dcs_decode.extract_dcs(
                self.zip_path, sounds_dir, log_cb=self._log)
        except Exception as e:
            self._log(f"  DCS audio extraction error: {e}", "warning")
            return 0
        if not result.is_dcs:
            self._log(f"  {result.message}", "info")
            return 0
        self._log(f"  {result.message} -> sounds/", "success")
        return len(result.tracks)

    # ------------------------------------------------------------------
    # Animation + font sub-table renderers
    # ------------------------------------------------------------------

    def _render_animation_mp4(self, frames, sub, anim_dir):
        """Place each VsiFrame in a 128x32 canvas and stitch to MP4.

        WPC animations frequently store two planes per displayable
        frame as consecutive table entries (low plane then high
        plane), giving 4-shade brightness via the same
        ``(low + 2*high) / 3`` formula as the full-frame scenes.
        We detect pairs by matching consecutive frames on (width,
        height, h_off, v_off) — when they match, we render the pair
        through :func:`dmd_render._render_planes` as a 4-shade
        composite; otherwise we render the frame as mono.

        The frame with the most lit pixels is duplicated at index 0
        so the MP4's poster frame (used as the Explorer thumbnail)
        shows the animation's high-content moment.
        """
        import tempfile
        tmp = tempfile.mkdtemp(prefix="williams_anim_")
        try:
            planes = self._planes_for_animation(frames)
            if not planes:
                return
            # Pick the frame with the most lit pixels (counted from
            # the union of low + high planes) as the poster frame.
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
                img = dmd_render._render_planes(
                    low, high,
                    dmd_render.DEFAULT_PIXEL_SIZE,
                    dmd_render.DEFAULT_COLOR)
                img.save(png, "PNG")
            mp4 = os.path.join(
                anim_dir,
                f"anim_{sub.sub_table_idx:04d}_"
                f"{len(planes):03d}frames.mp4")
            png_paths = [os.path.join(tmp, f"frame_{i:06d}.png")
                         for i in range(len(render_order))]
            try:
                dmd_render.render_pngs_to_mp4(
                    png_paths, mp4, fps=ANIM_FPS)
            except (RuntimeError, OSError) as e:
                self._log(f"  anim_{sub.sub_table_idx:04d}: "
                          f"ffmpeg error: {e}", "warning")
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

    def _detect_scene_sequences(self, plane_cache):
        """Group consecutive 4-shade full-frame frames into runs that
        look like one cinematic.

        Walks ``plane_cache`` (keyed by FullFrameImage table index) in
        steps of 2: indices (2N, 2N+1) form one displayable 4-shade
        frame.  Then walks those displayable frames in order, breaking
        the run whenever:

          - the next frame's index isn't ``current + 2`` (gap in the
            table — game data was reorganised), or
          - the lit-pixel count is too low (a blank frame), or
          - the pixel-difference vs the previous frame exceeds
            ``SCENE_SEQ_MAX_DIFF_RATIO`` (hard cut to an unrelated
            scene).

        Returns a list of groups; each group is a list of
        ``(displayable_idx, low_plane_bytes, high_plane_bytes)``
        triples ready for the renderer.
        """
        # Build the displayable-frame list first.
        displayable = []  # (display_idx, low, high)
        ordered_indices = sorted(plane_cache.keys())
        for i in range(0, len(ordered_indices) - 1, 2):
            a = ordered_indices[i]
            b = ordered_indices[i + 1]
            if b != a + 1:
                continue   # not a consecutive pair — skip
            low = plane_cache[a]
            high = plane_cache[b]
            displayable.append((a, low, high))
        # Group runs.
        groups = []
        current = []
        prev_combined = None
        prev_idx = None
        for disp_idx, low, high in displayable:
            combined = bytes(l | h for l, h in zip(low, high))
            lit = sum(bin(b).count("1") for b in combined)
            if lit < SCENE_SEQ_MIN_LIT:
                # blank frame — end the current group if any.
                if len(current) >= SCENE_SEQ_MIN_FRAMES:
                    groups.append(current)
                current = []
                prev_combined = None
                prev_idx = None
                continue
            if (prev_combined is not None
                    and prev_idx is not None
                    and disp_idx == prev_idx + 2):
                # Same animation candidate — measure pixel diff.
                diff = sum(bin(a ^ b).count("1")
                           for a, b in zip(combined, prev_combined))
                max_diff = int(len(combined) * 8 * SCENE_SEQ_MAX_DIFF_RATIO)
                if diff <= max_diff:
                    current.append((disp_idx, low, high))
                    prev_combined = combined
                    prev_idx = disp_idx
                    continue
            # break — start a new run with this frame
            if len(current) >= SCENE_SEQ_MIN_FRAMES:
                groups.append(current)
            current = [(disp_idx, low, high)]
            prev_combined = combined
            prev_idx = disp_idx
        if len(current) >= SCENE_SEQ_MIN_FRAMES:
            groups.append(current)
        return groups

    def _render_scene_sequence_mp4(self, group, group_idx, anim_dir):
        """Render a scene-sequence group as a 4-shade MP4.

        The first frame is the highest-lit-count frame in the group
        (poster), then the group plays through in table order.
        """
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
                img = dmd_render._render_planes(
                    low, high,
                    dmd_render.DEFAULT_PIXEL_SIZE,
                    dmd_render.DEFAULT_COLOR)
                img.save(png, "PNG")
            start_idx = group[0][0]
            mp4 = os.path.join(
                anim_dir,
                f"anim_scene_{group_idx:03d}_"
                f"idx{start_idx:04d}_{len(group):03d}frames.mp4")
            png_paths = [os.path.join(tmp, f"frame_{i:06d}.png")
                         for i in range(len(render_order))]
            try:
                dmd_render.render_pngs_to_mp4(
                    png_paths, mp4, fps=ANIM_FPS)
            except (RuntimeError, OSError) as e:
                self._log(f"  scene-seq {group_idx}: ffmpeg error: {e}",
                          "warning")
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

    def _planes_for_animation(self, frames):
        """Group ``frames`` into ``(low_plane, high_plane)`` pairs.

        Three cases:

          - BicolorDirect frame (0xFF header) — already carries both
            low and high planes inline in ``frame.data`` /
            ``frame.data_high``.  Render as one 4-shade frame.
          - Two adjacent Monochrome (0x00) frames with identical
            shape — treat as low+high planes of one 4-shade frame.
            (Some games store each plane as a separate table entry
            so the runtime code can flip between them.)
          - Anything else — render as solo mono (``high=None``).
        """
        out = []
        i = 0
        while i < len(frames):
            f0 = frames[i]
            if f0.data_high is not None:
                # Frame has both planes inline already — one
                # displayable frame consumed.
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
                    i += 1   # consume the second plane
            out.append((low, high))
            i += 1
        return out

    def _render_font_strip(self, frames, sub, font_dir):
        """Render all glyphs as a grid PNG (one row would be too wide).

        Lays out the proportional-width glyphs in a 16-glyph-per-row
        grid with a 1-pixel gap, each glyph drawn with the same
        DMD-dot rendering used for scenes.
        """
        from PIL import Image, ImageDraw
        pixel = dmd_render.DEFAULT_PIXEL_SIZE
        r_c, g_c, b_c = dmd_render.DEFAULT_COLOR
        cell_h = sub.table_height
        # Slot each glyph into a fixed-width cell so the grid lines
        # up cleanly even with proportional glyph widths.
        max_w = max(f.width for f in frames)
        cell_w = max_w + 1
        cols = 16
        rows = (len(frames) + cols - 1) // cols
        img = Image.new("RGB",
                        (cols * cell_w * pixel,
                         rows * (cell_h + 1) * pixel),
                        (0, 0, 0))
        draw = ImageDraw.Draw(img)
        dot = pixel - 1
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
                    # LSB-first within each byte (per FreeWPC dmd-theory)
                    bit = (f.data[byte_idx] >> (c % 8)) & 1
                    if bit:
                        x0 = (base_x + c) * pixel
                        y0 = (base_y + r) * pixel
                        draw.rectangle(
                            [x0, y0, x0 + dot - 1, y0 + dot - 1],
                            fill=(r_c, g_c, b_c))
        png = os.path.join(
            font_dir,
            f"font_{sub.sub_table_idx:04d}_"
            f"{len(frames):03d}glyphs.png")
        img.save(png, "PNG")
