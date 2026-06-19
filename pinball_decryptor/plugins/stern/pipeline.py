"""Stern Spike pipelines: Extract (image.bin -> per-sound WAV) and Write /
Direct-SD (edited WAV -> re-encode -> patch image.bin).

(Spike 2 stores its code + assets on an SD card; the framework's generic
``direct_ssd`` capability is surfaced here as "Direct SD".)

The decode/replace engine (``engine.py``) is the proven standalone Spike 2
codec, validated bit-exact for all 32 scale-variants (mono + stereo).  Wiring
it through these pipelines — reading ``image.bin`` + ``game_real`` from the
card's ext partitions (pure-Python ext4) and letting the emulator derive
everything else (vf2 + rt tables are boot-built; params via the chain) — is
being finished with GUI verification; until then the pipelines detect the input
and report a clear status instead of failing opaquely.
"""

import os

from ...core.pipeline_base import BasePipeline, PipelineError
from .formats import detect_game, linux_partitions
from .games import GAME_DB

try:                                   # engine import is optional during bring-up
    from . import engine
except Exception:                      # pragma: no cover - engine deps may be absent
    engine = None


_PENDING = (
    "Stern Spike 2 support is in active bring-up.\n\n"
    "The audio codec is fully reverse-engineered and validated — every sound "
    "decodes to WAV and re-encodes back bit-exact (mono + stereo, all 32 "
    "codec variants), entirely from the card (game_real + image.bin; no extra "
    "data needed). GUI wiring (pure-Python ext4 read of the card partitions + "
    "running the engine) is being finished with testing.\n\n"
    "Standalone tools are available now: spike2_extract.py / spike2_replace.py."
)


def _require_engine():
    if engine is None or not getattr(engine, "AVAILABLE", False):
        raise PipelineError("Engine", _PENDING)


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
        if len(parts) < 2:
            raise PipelineError(
                "Locate partitions",
                "Expected at least two Linux (ext) partitions on a Spike card "
                "(rootfs + data); found %d." % len(parts))
        self._log("Found %d ext partition(s)." % len(parts), "info")
        self._check_cancel()

        self._set_phase(2)  # Decode audio
        _require_engine()
        os.makedirs(self.output_dir, exist_ok=True)
        engine.extract_all(
            self.input_path, parts, self.output_dir,
            log=self._log, progress=self._bp, cancel=lambda: self._cancelled)

        self._set_phase(3)  # Checksums
        self._done(True, f"Extracted Spike 2 audio to {self.output_dir}")


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
        self._set_phase(2)  # Re-encode audio
        _require_engine()
        engine.write_image(
            self.original_path, self.assets_dir, self.output_path,
            log=self._log, progress=self._bp, cancel=lambda: self._cancelled)
        self._set_phase(3)
        self._done(True, f"Wrote patched image to {self.output_path}")


class SternDirectSsdExtractPipeline(BasePipeline):
    def __init__(self, device_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.output_dir = output_dir
        self.partition_override = partition_override

    def _run(self):
        self._set_phase(1)
        _require_engine()
        raise PipelineError("Direct SD", _PENDING)


class SternDirectSsdWritePipeline(BasePipeline):
    def __init__(self, device_path, assets_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.assets_dir = assets_dir
        self.partition_override = partition_override

    def _run(self):
        self._set_phase(1)
        _require_engine()
        raise PipelineError("Direct SD", _PENDING)
