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

from ...core.checksums import generate_checksums
from ...core.pipeline_base import BasePipeline, PipelineError
from .formats import detect_game, display_for_key, linux_partitions
from .rawdevice import RawDeviceFile, is_device_path

try:                                   # engine import is optional during bring-up
    from . import engine
except Exception:                      # pragma: no cover - engine deps may be absent
    engine = None


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
        self._log(f"Detected: {display_for_key(key, self.input_path)}", "success")
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
            phase=self._set_phase, log_line=self._log_line)
        # extract_all returns promptly on cancel (it checks between every phase
        # and per decoded sound).  Stop here instead of grinding through the
        # checksum pass and reporting success on a run the user aborted.
        self._check_cancel()

        self._set_phase(5)  # Checksums
        # Baseline so Write/Mod Pack can tell which assets the user edited (and
        # so the Write tab accepts this folder as an Extract output).
        self._log("Generating checksums...", "info")
        self._progress(0, 0, "Generating checksums...")
        generate_checksums(self.output_dir, log_cb=self._log,
                           progress_cb=self._progress,
                           cancel=lambda: self._cancelled)
        self._check_cancel()
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
    """Extract straight from the physical SD card (no .img intermediate).

    Identical decode path to :class:`SternExtractPipeline` — the only
    difference is the disk source: the pure-Python ``Ext4Reader`` is pointed at
    the raw device (``\\\\.\\PHYSICALDRIVEn`` / ``/dev/sdX``) via a
    sector-aligned :class:`~.rawdevice.RawDeviceFile` instead of a file path.
    The GUI gates this on Administrator/root before we're reached."""

    def __init__(self, device_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.output_dir = output_dir
        self.partition_override = partition_override

    def _run(self):
        self._set_phase(0)  # Read SD card
        self._log("Reading the SD card...", "info")
        if not is_device_path(self.device_path):
            raise PipelineError(
                "Read SD card",
                "Direct SD needs a physical drive (e.g. \\\\.\\PHYSICALDRIVE2), "
                "not a file path (got %r). Pick the card from the Game SD "
                "dropdown." % self.device_path)
        _require_engine()
        # Confirm the device is a Spike 2 card and resolve its ext partitions
        # (raises a clear error on a non-Spike card or when it can't be read,
        # e.g. without Administrator).
        parts = engine.device_partitions(
            self.device_path, self.partition_override, log=self._log)
        self._log("Spike 2 SD card detected (%d ext partition(s))."
                  % len(parts), "success")
        self._check_cancel()

        self._set_phase(1)  # Locate partitions
        os.makedirs(self.output_dir, exist_ok=True)
        # extract_all drives phases 2-5 (video / images / audio / checksums);
        # open_disk points the reader at the raw card.
        n = engine.extract_all(
            self.device_path, parts, self.output_dir,
            log=self._log, progress=self._progress,
            cancel=lambda: self._cancelled, phase=self._set_phase,
            open_disk=lambda: RawDeviceFile(self.device_path, writable=False),
            log_line=self._log_line)
        self._check_cancel()   # don't run checksums on a cancelled extract

        self._set_phase(5)  # Checksums
        self._log("Generating checksums...", "info")
        self._progress(0, 0, "Generating checksums...")
        generate_checksums(self.output_dir, log_cb=self._log,
                           progress_cb=self._progress,
                           cancel=lambda: self._cancelled)
        self._check_cancel()
        self._done(True, "Extracted %d Spike 2 sound(s) from the SD card to %s"
                   % (n, self.output_dir))


class SternDirectSsdWritePipeline(BasePipeline):
    """Write edited assets straight back onto the physical SD card (in place).

    The Direct-SD twin of :class:`SternWritePipeline`: same size-neutral patch
    set, applied to the card device instead of an image copy."""

    def __init__(self, device_path, assets_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.assets_dir = assets_dir
        self.partition_override = partition_override

    def _run(self):
        self._set_phase(0)  # Scan
        if not is_device_path(self.device_path):
            raise PipelineError(
                "Scan",
                "Direct SD needs a physical drive (e.g. \\\\.\\PHYSICALDRIVE2), "
                "not a file path (got %r). Pick the card from the Game SD "
                "dropdown." % self.device_path)
        _require_engine()
        n = engine.write_device(
            self.device_path, self.assets_dir,
            log=self._log, progress=self._progress,
            cancel=lambda: self._cancelled, phase=self._set_phase,
            partition_override=self.partition_override)
        self._done(True, "Wrote %d change(s) directly to the SD card." % n)
