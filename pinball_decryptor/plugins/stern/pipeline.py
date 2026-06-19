"""Stern Spike pipelines: Extract (card image -> per-sound WAV) and Write
(edited WAV -> re-encode -> patch image in place).

(Spike 2 stores its code + assets on an SD card; the framework's generic
``direct_ssd`` capability is surfaced here as "Direct SD".)

The decode/replace engine (``engine.py`` over ``spike2/`` + ``ext4.py``) is the
proven standalone Spike 2 codec, validated bit-exact for all 32 scale-variants
(mono + stereo).  These pipelines locate ``image.bin`` + ``game_real`` in the
card's ext partitions (pure-Python ext4), boot the firmware in an emulator to
derive every sound's keystream, then decode/re-encode.
"""

import os

from ...core.pipeline_base import BasePipeline, PipelineError
from .formats import detect_game, linux_partitions
from .games import GAME_DB

try:                                   # engine import is optional during bring-up
    from . import engine
except Exception:                      # pragma: no cover - engine deps may be absent
    engine = None


_DIRECT_PENDING = (
    "Direct SD read/write is not enabled for Spike 2 yet.\n\n"
    "For now, image the card to a raw .img file (e.g. with Win32 Disk Imager "
    "or `dd`) and use the file-based Extract / Write here — those are fully "
    "supported.  Reading/writing the physical card directly is the next step."
)


def _require_engine():
    if engine is None or not getattr(engine, "AVAILABLE", False):
        raise PipelineError(
            "Engine",
            "Spike 2 audio engine unavailable. Install its prerequisites "
            "(pip install unicorn capstone numpy) and try again.")


class SternExtractPipeline(BasePipeline):
    """Decode every packed sound in a Spike 2 card image to a per-sound WAV."""

    def __init__(self, input_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.input_path = input_path
        self.output_dir = output_dir

    def _run(self):
        self._set_phase(0)  # Detect
        self._log("Detecting Stern Spike card...", "info")
        key = detect_game(self.input_path)
        if key is None:
            raise PipelineError(
                "Detect",
                "Not a recognized Stern Spike card image (need a raw .img/.bin "
                "with the Spike partition layout).")
        self._log(f"Detected: {GAME_DB[key]['display']}", "success")
        self._check_cancel()

        self._set_phase(1)  # Locate partitions
        self._log("Reading partition table...", "info")
        parts = linux_partitions(self.input_path)
        if len(parts) < 1:
            raise PipelineError(
                "Locate partitions",
                "No Linux (ext) partition found on the card image.")
        self._log("Found %d ext partition(s)." % len(parts), "info")
        self._check_cancel()

        _require_engine()
        os.makedirs(self.output_dir, exist_ok=True)
        # extract_all drives phases 2 (Extract video) and 3 (Decode audio).
        n = engine.extract_all(
            self.input_path, parts, self.output_dir,
            log=self._log, progress=self._progress, cancel=lambda: self._cancelled,
            phase=self._set_phase)

        self._set_phase(4)  # Checksums
        self._done(True, "Extracted %d Spike 2 sound(s) to %s" % (n, self.output_dir))


class SternWritePipeline(BasePipeline):
    """Re-encode edited WAVs back into a copy of the card image (size-neutral)."""

    def __init__(self, original_path, assets_dir, output_path,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.original_path = original_path
        self.assets_dir = assets_dir
        self.output_path = output_path

    def _run(self):
        self._set_phase(0)  # Detect
        if detect_game(self.original_path) is None:
            raise PipelineError("Detect", "Original is not a Spike card image.")
        self._check_cancel()
        self._set_phase(1)  # Stage
        _require_engine()
        self._set_phase(2)  # Re-encode audio (+ patch, inside the engine)
        n = engine.write_image(
            self.original_path, self.assets_dir, self.output_path,
            log=self._log, progress=self._progress, cancel=lambda: self._cancelled)
        self._set_phase(3)  # Patch image
        self._done(True, "Wrote %d replaced sound(s) to %s" % (n, self.output_path))


class SternDirectSsdExtractPipeline(BasePipeline):
    def __init__(self, device_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.output_dir = output_dir
        self.partition_override = partition_override

    def _run(self):
        self._set_phase(0)
        raise PipelineError("Direct SD", _DIRECT_PENDING)


class SternDirectSsdWritePipeline(BasePipeline):
    def __init__(self, device_path, assets_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.assets_dir = assets_dir
        self.partition_override = partition_override

    def _run(self):
        self._set_phase(0)
        raise PipelineError("Direct SD", _DIRECT_PENDING)
