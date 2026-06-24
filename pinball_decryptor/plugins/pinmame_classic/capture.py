"""libpinmame DMD-frame capture for the PinMAME classic-DMD plugins.

Data East / Sega DMD *animations* are stored compressed in the DMD ROM
(see ``docs/DE_DMD_RE.md``) and only render when the emulated DMD-CPU
firmware decompresses them at runtime — which is exactly how the DMD-
colourisation community extracts them (VPinMAME's frame dumper).  This
reuses the libpinmame driver the Williams plugin already ships: we run
the game in **attract mode** (no WPC gameplay scripting) and capture the
decoded 4-shade DMD frames + audio into per-animation MP4s.

The pipeline subclasses the Williams capture pipeline purely to inherit
its generic scene-segmentation + brightness-frame/audio MP4 rendering;
the Williams plugin itself is left untouched.
"""

import os

from ...core.checksums import generate_checksums
from ...core.pipeline_base import PipelineError
from ..williams import pinmame_capture as pc
from ..williams.capture_pipeline import CapturePipeline as _WilliamsCapture
from .formats import detect_game

PHASES = (
    "Detect", "Probe libpinmame", "Capture (attract mode)",
    "Segment + render", "Cleanup",
)

DEFAULT_DURATION_SECONDS = 180.0


class CapturePipeline(_WilliamsCapture):
    """Attract-mode libpinmame DMD+audio capture for DE/Sega DMD games."""

    extract_phases = PHASES

    def __init__(self, input_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 game_db=None, duration_seconds=DEFAULT_DURATION_SECONDS,
                 frame_cb=None, capture_ready_cb=None, **_ignored):
        # Force attract-mode: these games have no PinMAME switch maps, so
        # WPC-style gameplay simulation can't drive them.
        super().__init__(
            input_path, output_dir, log_cb, phase_cb, progress_cb, done_cb,
            duration_seconds=duration_seconds, simulate_gameplay=False,
            frame_cb=frame_cb, capture_ready_cb=capture_ready_cb)
        self.game_db = game_db or {}
        self._cap = None     # the live PinmameCapture, for cancel()

    def cancel(self):
        # Stop the blocking libpinmame run early when the user hits Cancel
        # (the base flag is only polled between phases, not during capture).
        super().cancel()
        cap = self._cap
        if cap is not None:
            cap.request_stop()

    def _run(self):
        ph = iter(range(len(PHASES)))

        # ---- Detect ----
        self._set_phase(next(ph))
        self._log("Detecting game...", "info")
        key = detect_game(self.zip_path, self.game_db)
        if key is None:
            raise PipelineError(
                "Detect",
                f"Cannot identify a supported game from "
                f"{os.path.basename(self.zip_path)}.")
        info = self.game_db[key]
        rom_name = self._guess_rom_name()
        self._log(f"Game: {info['display']} ({info['manufacturer']}, "
                  f"{info['year']}, {info['dmd']} DMD) — rom {rom_name}",
                  "success")
        game_dir = os.path.join(self.output_dir, key)
        os.makedirs(game_dir, exist_ok=True)

        # ---- Probe libpinmame ----
        self._set_phase(next(ph))
        lib = pc.find_libpinmame()
        if lib is None:
            raise PipelineError(
                "Probe libpinmame",
                "libpinmame not installed.\n\n" + pc.install_hint())
        self._log(f"libpinmame: {lib}", "success")

        # ---- Capture (attract mode) ----
        self._set_phase(next(ph))
        self._log(f"Running PinMAME for {self.duration_seconds:.0f}s "
                  "(attract-mode capture)...", "info")

        def _on_progress(pct):
            self._progress(int(pct * 1000), 1000,
                           f"capturing... {pct * 100:.1f}%")

        self._check_cancel()
        cap = pc.PinmameCapture(lib)
        self._cap = cap
        try:
            result = cap.run(pc.CaptureConfig(
                rom_zip_path=self.zip_path, rom_name=rom_name,
                duration_seconds=self.duration_seconds, sample_rate=48000,
                capture_audio=True, capture_dmd=True,
                simulate_gameplay=False,
                log_callback=self._log, progress_callback=_on_progress,
                frame_callback=self.frame_cb,
                capture_ready_callback=self.capture_ready_cb))
        except RuntimeError as e:
            raise PipelineError("Capture", str(e))
        except FileNotFoundError as e:
            raise PipelineError("Probe libpinmame", str(e))

        # If Cancel was pressed, the run stopped early — abort without
        # rendering a partial capture.
        self._check_cancel()
        if not result.frames:
            raise PipelineError(
                "Capture",
                "PinMAME ran but emitted no DMD frames — the ROM may not "
                "have a DMD, or attract mode didn't start in time.")
        self._log(f"  captured {len(result.frames)} DMD frames, "
                  f"{len(result.audio_pcm)} bytes audio", "success")

        # ---- Segment + render (inherited generic helpers) ----
        self._set_phase(next(ph))
        cap_dir = os.path.join(game_dir, "captured")
        os.makedirs(cap_dir, exist_ok=True)
        clips = self._segment_into_clips(result.frames)
        self._log(f"Detected {len(clips)} animation(s) via scene "
                  "segmentation.", "info")
        rendered = 0
        for i, frames in enumerate(clips, start=1):
            self._check_cancel()
            self._progress(i - 1, len(clips),
                           f"rendering clip {i}/{len(clips)}")
            name = f"anim_{i:03d}_{len(frames):03d}frames"
            try:
                self._render_clip(frames, name, cap_dir, result)
                rendered += 1
            except (RuntimeError, OSError) as e:
                self._log(f"  {name} render error: {e}", "warning")
        self._progress(len(clips), len(clips), "render complete")

        # ---- Cleanup ----
        self._set_phase(next(ph))
        n = generate_checksums(
            game_dir, log_cb=self._log, progress_cb=self._progress)
        self._done(
            True,
            f"{info['display']} captured.\n\n"
            f"Output:        {game_dir}\n"
            f"Animations:    {rendered} (in captured/)\n"
            f"DMD frames:    {len(result.frames)}\n"
            f"Files checksummed: {n}\n\n"
            "Attract-mode capture: each anim_*.mp4 is a decoded DMD "
            "animation with synced audio.  Tick Auto-transcribe to name "
            "the audio by spoken text.")
