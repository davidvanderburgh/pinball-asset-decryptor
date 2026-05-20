"""Williams PinMAME runtime-capture pipeline.

Drives :mod:`.pinmame_capture` for the user — given a MAME ROM zip,
it spawns PinMAME under libpinmame for a fixed duration, captures
the DMD frames + audio, segments the capture into individual
cinematics by detecting blank-frame gaps + sharp scene cuts, and
emits each cinematic as an MP4 with its corresponding audio slice.

This is a *separate* pipeline from the static
:class:`pinball_decryptor.plugins.williams.pipeline.ExtractPipeline`.
The two are complementary:

  - **Static**: raw asset bitmaps (sprites, font glyphs, splash
    bitmaps) decoded directly from the ROM.  No PinMAME needed.
  - **Capture**: composed display + real audio, as the game plays
    them.  Needs libpinmame.
"""

import json
import os
import subprocess
import sys
import tempfile
import wave
import zipfile

from PIL import Image, ImageDraw

from ...core.checksums import generate_checksums
from ...core.pipeline_base import BasePipeline, PipelineError
from . import dmd_render
from . import pinmame_capture
from .formats import detect_game
from .games import GAME_DB


PHASES = (
    "Detect",
    "Probe libpinmame",
    "Capture",
    "Segment + render",
    "Cleanup",
)

# Combined phases: static extract followed by PinMAME capture.  Used
# by the GUI's phase indicator when the user ticks "Use PinMAME
# runtime capture" (which is additive — capture is on top of, not
# instead of, the static asset extract).
COMBINED_PHASES = (
    "Detect",
    "Static extract",
    "Probe libpinmame",
    "Capture",
    "Segment + render",
    "Cleanup",
)

# How long to let PinMAME run attract mode.  Scripted gameplay tours
# now run ~14 moments at ~10s each (140s) plus ~25s of boot + start
# overhead, so 180s is the new floor — anything shorter risks
# cutting off the last few moments.
DEFAULT_DURATION_SECONDS = 180.0

# How a "new scene" is detected:
#   - Two consecutive frames whose pixel-difference exceeds
#     SCENE_CUT_THRESHOLD pixels = hard cut (start a new clip).
#   - A run of BLANK_GAP_FRAMES mostly-blank frames in a row also
#     ends the current clip (curtains).
SCENE_CUT_THRESHOLD = 0.35    # 35% of pixels differ
BLANK_GAP_FRAMES = 8          # ~250ms at typical 30fps DMD refresh
BLANK_LIT_PIXEL_MAX = 16      # frame is "blank" if <= this many lit
MIN_CLIP_FRAMES = 6           # drop tiny accidental clips
MIN_CLIP_DURATION_MS = 500    # and very brief ones


class CapturePipeline(BasePipeline):
    """Runtime-capture pipeline (DMD + audio) for Williams ROMs."""

    extract_phases = PHASES   # for the GUI's phase indicator

    def __init__(self, zip_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 duration_seconds=DEFAULT_DURATION_SECONDS,
                 simulate_gameplay=True,
                 frame_cb=None,
                 capture_ready_cb=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.zip_path = zip_path
        self.output_dir = output_dir
        self.duration_seconds = duration_seconds
        self.simulate_gameplay = simulate_gameplay
        # Live DMD preview callback — forwarded to PinmameCapture.
        # Signature: fn(data, width, height, depth) called on the
        # libpinmame display thread.
        self.frame_cb = frame_cb
        # Diagnostic switch-matrix hook — fires once with
        # ``(manual_press_fn, active_script)`` so the GUI can let
        # the user click switches by name during the capture.
        self.capture_ready_cb = capture_ready_cb

    # ------------------------------------------------------------------

    def _run(self):
        # ---- Phase 0: detect ----
        self._set_phase(0)
        self._log("Detecting game...", "info")
        key = detect_game(self.zip_path)
        if key is None:
            raise PipelineError(
                "Detect",
                f"Cannot identify game from {os.path.basename(self.zip_path)}.")
        info = GAME_DB[key]
        rom_name = self._guess_rom_name()
        self._log(f"Game: {info['display']} ({rom_name})", "success")
        self._check_cancel()

        # ---- Phase 1: probe libpinmame ----
        self._set_phase(1)
        lib_path = pinmame_capture.find_libpinmame()
        if lib_path is None:
            raise PipelineError(
                "Probe libpinmame",
                "libpinmame not installed.\n\n"
                + pinmame_capture.install_hint())
        self._log(f"libpinmame: {lib_path}", "success")

        game_dir = os.path.join(self.output_dir, key + "_capture")
        os.makedirs(game_dir, exist_ok=True)

        # ---- Phase 2: capture ----
        self._set_phase(2)
        self._log(
            f"Running PinMAME for {self.duration_seconds:.0f}s "
            "(attract-mode capture)...", "info")

        def _on_progress(pct):
            self._progress(int(pct * 1000), 1000,
                           f"capturing... {pct * 100:.1f}%")

        cap = pinmame_capture.PinmameCapture(lib_path)
        try:
            result = cap.run(pinmame_capture.CaptureConfig(
                rom_zip_path=self.zip_path,
                rom_name=rom_name,
                duration_seconds=self.duration_seconds,
                sample_rate=48000,
                capture_audio=True,
                capture_dmd=True,
                simulate_gameplay=self.simulate_gameplay,
                log_callback=self._log,
                progress_callback=_on_progress,
                frame_callback=self.frame_cb,
                capture_ready_callback=self.capture_ready_cb,
            ))
        except RuntimeError as e:
            raise PipelineError("Capture", str(e))
        except FileNotFoundError as e:
            raise PipelineError("Probe libpinmame", str(e))

        if not result.frames:
            raise PipelineError(
                "Capture",
                "PinMAME ran but didn't emit any DMD frames.  "
                "The ROM may not have a DMD display, or attract mode "
                "didn't start within the capture window.")

        self._log(
            f"  captured {len(result.frames)} DMD frames, "
            f"{len(result.audio_pcm)} bytes audio "
            f"({result.audio_sample_rate}Hz x {result.audio_channels}ch)",
            "success")

        # ---- Phase 3: segment + render ----
        self._set_phase(3)
        # Prefer the scripted per-scene clip ranges when the
        # play-through script produced them — each gets a named MP4
        # like "skill_shot.mp4" / "multiball_start.mp4".  Fall back to
        # blank-gap / scene-cut segmentation otherwise.
        if result.script_clips:
            named_clips = self._slice_frames_for_script_clips(
                result.frames, result.script_clips)
            self._log(
                f"Script ran with {len(named_clips)} scene(s); "
                "emitting per-scene MP4s.", "info")
        else:
            grouped = self._segment_into_clips(result.frames)
            named_clips = [
                (f"clip_{i:03d}_{len(c):03d}frames", c)
                for i, c in enumerate(grouped, start=1)]
            self._log(
                f"No script clips; detected {len(named_clips)} "
                "cinematic(s) via scene-boundary segmentation.",
                "info")

        rendered_count = 0
        for i, (name, frames) in enumerate(named_clips, start=1):
            self._check_cancel()
            self._progress(
                i - 1, len(named_clips),
                f"rendering {name} ({i}/{len(named_clips)})")
            try:
                self._render_clip(frames, name, game_dir, result)
                rendered_count += 1
            except (RuntimeError, OSError) as e:
                self._log(f"  {name} render error: {e}", "warning")
        self._progress(
            len(named_clips), len(named_clips), "render complete")

        # Write a full-capture summary
        summary_path = os.path.join(game_dir, "capture_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"Game: {info['display']}\n")
            f.write(f"ROM name: {rom_name}\n")
            f.write(f"Source: {os.path.basename(self.zip_path)}\n")
            f.write(f"Capture duration: {result.elapsed_seconds:.1f}s\n")
            f.write(f"DMD frames captured: {len(result.frames)}\n")
            f.write(f"Audio: {result.audio_sample_rate}Hz "
                    f"x {result.audio_channels}ch, "
                    f"{len(result.audio_pcm)} bytes\n")
            f.write(f"Clips rendered: {rendered_count}/{len(named_clips)}\n")
            f.write("\nClips:\n")
            for name, frames in named_clips:
                if not frames:
                    f.write(f"  {name}: (no frames captured in range)\n")
                    continue
                start_ms = frames[0].timestamp_ms
                end_ms = frames[-1].timestamp_ms
                f.write(f"  {name}.mp4: {len(frames)} frames, "
                        f"{start_ms}ms - {end_ms}ms "
                        f"({(end_ms - start_ms) / 1000:.1f}s)\n")

        # ---- Phase 4: cleanup ----
        self._set_phase(4)
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            game_dir, log_cb=self._log, progress_cb=self._progress)

        self._log("Done.", "success")
        mode_note = (
            "Auto-credited + pressed Start + drove random "
            "playfield switches — clips include attract mode plus "
            "mode-start, scoring, and game-over cinematics."
            if self.simulate_gameplay else
            "Attract-mode capture only (gameplay simulation off).")
        self._done(
            True,
            f"{info['display']} captured.\n\n"
            f"Output:        {game_dir}\n"
            f"Clips:         {rendered_count}\n"
            f"DMD frames:    {len(result.frames)}\n"
            f"Files checksummed: {n}\n\n"
            f"Each clip_*.mp4 has matching DCS audio.\n{mode_note}")

    # ------------------------------------------------------------------
    # ROM-name guessing — PinMAME wants the short name (e.g. "ft_l5")
    # ------------------------------------------------------------------

    def _guess_rom_name(self) -> str:
        """Derive the PinMAME ROM name from the zip filename.

        MAME zips are conventionally named ``<rom_name>.zip``, so we
        strip the directory and extension.  Falls back to the game
        key if anything looks off.
        """
        base = os.path.basename(self.zip_path)
        if base.lower().endswith(".zip"):
            return base[:-4]
        return base

    # ------------------------------------------------------------------
    # Scene segmentation
    # ------------------------------------------------------------------

    def _segment_into_clips(self, frames):
        """Group the captured frames into individual cinematics.

        Returns a list of lists of :class:`CaptureFrame`.
        """
        if not frames:
            return []
        clips = []
        current = []
        blank_run = 0
        prev_frame = None
        for f in frames:
            lit = self._lit_count(f.data)
            is_blank = lit <= BLANK_LIT_PIXEL_MAX
            if prev_frame is not None and not is_blank:
                # Compare to previous to detect a cut
                if (f.width == prev_frame.width
                        and f.height == prev_frame.height
                        and len(f.data) == len(prev_frame.data)):
                    diff = self._diff_fraction(f.data, prev_frame.data)
                    if diff > SCENE_CUT_THRESHOLD:
                        # cut — flush current clip and start fresh
                        if self._clip_is_keepable(current):
                            clips.append(current)
                        current = []
                        blank_run = 0
            if is_blank:
                blank_run += 1
                if blank_run >= BLANK_GAP_FRAMES and current:
                    if self._clip_is_keepable(current):
                        clips.append(current)
                    current = []
                    blank_run = 0
            else:
                blank_run = 0
                current.append(f)
            prev_frame = f
        if self._clip_is_keepable(current):
            clips.append(current)
        return clips

    @staticmethod
    def _lit_count(data: bytes) -> int:
        return sum(1 for b in data if b)

    @staticmethod
    def _diff_fraction(a: bytes, b: bytes) -> float:
        # Counts positions where either side is on and they disagree
        # (ignores depth — treats any non-zero as "on" for cut detection)
        n = min(len(a), len(b))
        if n == 0:
            return 0.0
        differing = sum(1 for i in range(n) if (bool(a[i]) != bool(b[i])))
        return differing / n

    @staticmethod
    def _clip_is_keepable(clip) -> bool:
        if len(clip) < MIN_CLIP_FRAMES:
            return False
        span_ms = clip[-1].timestamp_ms - clip[0].timestamp_ms
        return span_ms >= MIN_CLIP_DURATION_MS

    # ------------------------------------------------------------------
    # Per-clip rendering: frames -> PNGs -> MP4 + audio slice
    # ------------------------------------------------------------------

    def _slice_frames_for_script_clips(self, frames, script_clips):
        """Map each scripted MomentClip(name, start_ms, end_ms) to
        the slice of *frames* whose timestamps fall in that range.

        Returns ``[(clip_name, [CaptureFrame, ...]), ...]``.
        """
        if not frames:
            return [(c.name, []) for c in script_clips]
        out = []
        i = 0
        n = len(frames)
        for clip in script_clips:
            # Advance to first frame inside [start, end].
            while i < n and frames[i].timestamp_ms < clip.start_ms:
                i += 1
            j = i
            while j < n and frames[j].timestamp_ms <= clip.end_ms:
                j += 1
            out.append((clip.name, frames[i:j]))
        return out

    def _render_clip(self, clip, name, game_dir, capture_result):
        if not clip:
            raise RuntimeError(f"{name}: no frames in clip range")
        ffmpeg = dmd_render.find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found")
        tmp = tempfile.mkdtemp(prefix="williams_clip_")
        try:
            # Render each frame as a PNG using the existing renderer.
            # Frames are already brightness-quantized (0..levels-1).
            for j, f in enumerate(clip):
                png = os.path.join(tmp, f"frame_{j:06d}.png")
                img = _render_brightness_frame(f, dmd_render.DEFAULT_PIXEL_SIZE,
                                               dmd_render.DEFAULT_COLOR)
                img.save(png, "PNG")
            # Slice audio matching the clip's time range
            audio_wav = os.path.join(tmp, "clip.wav")
            self._slice_audio_to_wav(capture_result, clip, audio_wav)
            # FPS for the MP4 = inverse of the median inter-frame interval
            fps = _estimate_fps(clip)
            mp4 = os.path.join(game_dir, f"{name}.mp4")
            cmd = [
                ffmpeg, "-y",
                "-framerate", f"{fps:.3f}",
                "-i", os.path.join(tmp, "frame_%06d.png"),
                "-i", audio_wav,
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                mp4,
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode != 0:
                tail = (r.stderr or "")[-400:]
                raise RuntimeError(f"ffmpeg failed: {tail}")
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

    def _slice_audio_to_wav(self, result, clip, wav_path):
        """Write a WAV of the audio between the clip's start and end."""
        start_ms = clip[0].timestamp_ms
        end_ms = clip[-1].timestamp_ms
        sr = result.audio_sample_rate
        ch = max(1, result.audio_channels)
        start_byte = int((start_ms / 1000.0) * sr * ch * 2)
        end_byte = int((end_ms / 1000.0) * sr * ch * 2)
        # Align to sample boundary
        start_byte -= start_byte % (ch * 2)
        end_byte -= end_byte % (ch * 2)
        slice_bytes = result.audio_pcm[start_byte:end_byte]
        if not slice_bytes:
            # No audio captured for this slice — emit a tiny silent WAV
            slice_bytes = b"\x00\x00" * 32
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(slice_bytes)


def _estimate_fps(clip) -> float:
    """Estimate the per-clip FPS from frame timestamps."""
    if len(clip) < 2:
        return 30.0
    intervals = [
        clip[i + 1].timestamp_ms - clip[i].timestamp_ms
        for i in range(len(clip) - 1)
        if clip[i + 1].timestamp_ms > clip[i].timestamp_ms]
    if not intervals:
        return 30.0
    intervals.sort()
    median = intervals[len(intervals) // 2]
    if median <= 0:
        return 30.0
    return min(60.0, max(8.0, 1000.0 / median))


def _render_brightness_frame(frame, pixel_size, color):
    """Render a PinMAME-format DMD frame (one byte per pixel) to a PIL Image.

    Each source byte is a brightness level 0..(2**depth - 1).  We
    scale to 0..1 and render each dot as a square at that intensity
    on top of a black background, with a 1-pixel gap between dots
    (DMD-style).
    """
    levels = max(1, (1 << frame.depth) - 1)
    img = Image.new(
        "RGB",
        (frame.width * pixel_size, frame.height * pixel_size),
        (0, 0, 0))
    draw = ImageDraw.Draw(img)
    dot = pixel_size - 1
    r, g, b = color
    data = frame.data
    width = frame.width
    for y in range(frame.height):
        for x in range(width):
            v = data[y * width + x]
            if v == 0:
                continue
            ratio = v / levels
            fr = int(r * ratio)
            fg = int(g * ratio)
            fb = int(b * ratio)
            x0 = x * pixel_size
            y0 = y * pixel_size
            draw.rectangle(
                [x0, y0, x0 + dot - 1, y0 + dot - 1],
                fill=(fr, fg, fb))
    return img


# ---------------------------------------------------------------------------
# Combined static + capture pipeline
#
# When the user checks "Use PinMAME runtime capture" we run BOTH the
# static asset extractor (raw ROM bitmaps) AND the PinMAME capture
# (composed cinematics + audio).  They produce complementary outputs
# into the same game folder: static gives you the discrete asset
# tiles + animation MP4s decoded straight from the ROM, capture gives
# you the per-scene gameplay MP4s with synced DCS audio.
# ---------------------------------------------------------------------------

class StaticPlusCapturePipeline(BasePipeline):
    """Run the static asset extractor, then the PinMAME capture.

    Phase layout matches :data:`COMBINED_PHASES`.  The static
    pipeline's internal phase callbacks are swallowed; we just hold
    on phase 1 (Static extract) until it finishes.  Capture's
    internal phases map to our 2..5.
    """

    extract_phases = COMBINED_PHASES

    def __init__(self, zip_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 duration_seconds=DEFAULT_DURATION_SECONDS,
                 simulate_gameplay=True,
                 frame_cb=None,
                 capture_ready_cb=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.zip_path = zip_path
        self.output_dir = output_dir
        self.duration_seconds = duration_seconds
        self.simulate_gameplay = simulate_gameplay
        self.frame_cb = frame_cb
        self.capture_ready_cb = capture_ready_cb
        self._inner_static = None
        self._inner_capture = None

    def cancel(self):
        super().cancel()
        # Forward cancel into whichever sub-pipeline is active.
        if self._inner_static is not None:
            self._inner_static.cancel()
        if self._inner_capture is not None:
            self._inner_capture.cancel()

    # NB: we override run() (not _run()) because we delegate the
    # terminal done_cb to the inner CapturePipeline.run() — letting
    # BasePipeline.run() wrap our _run() would risk firing done_cb
    # twice when capture succeeds.
    def run(self):
        try:
            self._do_work()
        except PipelineError as e:
            self._done(False, e.message)
        except Exception as e:
            self._done(False, f"Unexpected error: {e}")

    def _do_work(self):
        # ---- Phase 0: Detect (signal — sub-pipelines re-detect
        # internally, that's cheap) ----
        self._set_phase(0)
        self._check_cancel()

        # ---- Phase 1: Static asset extract ----
        self._set_phase(1)
        self._log("=== Running static asset extract ===", "info")
        from .pipeline import ExtractPipeline
        static = ExtractPipeline(
            self.zip_path, self.output_dir,
            self._log,
            lambda i: None,           # swallow internal phase indicator
            self._progress,
            lambda ok, msg: None,     # we own the final done_cb
        )
        self._inner_static = static
        static_ok = False
        try:
            static._run()
            static_ok = True
            self._log("Static extract complete.", "success")
        except PipelineError as e:
            self._log(
                f"Static extract failed: {e.message}.  Continuing "
                "with PinMAME capture.", "warning")
        self._inner_static = None
        self._check_cancel()

        # ---- Phases 2..5: PinMAME capture ----
        # Remap capture's internal phases (0..4) to our combined 2..5.
        # Capture's phase 0 ("Detect") is already represented by our
        # phase 0 — swallow it to avoid the indicator going backwards.
        def remap_phase(i):
            if i == 0:
                return
            self._set_phase(i + 1)

        # Decorate done_cb so the final summary mentions both halves.
        def combined_done(ok, capture_summary):
            prefix = ("Static extract: complete.\n\n"
                      if static_ok else
                      "Static extract: FAILED (see log above).\n\n")
            self._done(ok, prefix + capture_summary)

        capture = CapturePipeline(
            self.zip_path, self.output_dir,
            self._log, remap_phase, self._progress, combined_done,
            duration_seconds=self.duration_seconds,
            simulate_gameplay=self.simulate_gameplay,
            frame_cb=self.frame_cb,
            capture_ready_cb=self.capture_ready_cb,
        )
        self._inner_capture = capture
        # capture.run() calls combined_done at the end (or on error).
        # We don't need to call self._done ourselves.
        capture.run()
