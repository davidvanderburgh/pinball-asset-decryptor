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
from ...core.staged_originals import discard as discard_snapshots
from .formats import detect_game, display_for_key, linux_partitions
from ...core.rawdevice import (FlashCancelled, FlashError, RawDeviceFile,
                              flash_image_to_device, format_size,
                              is_device_path)

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


def _category_flags(cats):
    """Map the GUI's ``{category: bool}`` selection to ``extract_all``'s
    ``do_audio`` / ``do_video`` / ``do_images`` / ``do_text`` kwargs.  Missing or
    ``None`` -> everything on (the default extract)."""
    cats = cats or {}
    return dict(
        do_audio=bool(cats.get("audio", True)),
        do_video=bool(cats.get("video", True)),
        do_images=bool(cats.get("images", True)),
        do_text=bool(cats.get("text", True)),
    )


def _extract_summary(n, output_dir, flags, *, source=""):
    """Build the end-of-extract summary line.

    ``extract_all`` only returns the decoded-sound count, but a default run also
    pulls video / images / text -- so a bare "Extracted N sound(s)" misreports a
    full extraction as audio-only.  Name the other categories that were on so the
    summary matches what actually landed on disk.  ``source`` is an optional
    qualifier (e.g. " from the SD card") inserted before the destination."""
    extra = [name for name, on in (("video", flags["do_video"]),
                                   ("images", flags["do_images"]),
                                   ("text", flags["do_text"])) if on]
    if flags["do_audio"]:
        lead = "Extracted %d Spike 2 sound(s)" % n
        if extra:
            if len(extra) == 1:
                lead += " plus %s" % extra[0]
            else:
                lead += " plus " + ", ".join(extra[:-1]) + " and " + extra[-1]
    elif extra:
        lead = "Extracted " + (", ".join(extra[:-1]) + " and " + extra[-1]
                               if len(extra) > 1 else extra[0])
    else:
        lead = "Extraction complete"
    return "%s%s -> %s" % (lead, source, output_dir)


class SternExtractPipeline(BasePipeline):
    """Decode every packed sound in a Spike 2 card image to a per-sound WAV."""

    def __init__(self, input_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 extract_categories=None, duration_names=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.input_path = input_path
        self.output_dir = output_dir
        self.extract_categories = extract_categories
        self.duration_names = duration_names

    def _run(self):
        self._set_phase(0)  # Detect
        self._log("Detecting Stern Spike card...", "info")
        key = detect_game(self.input_path)
        if key is None:
            raise PipelineError(
                "Detect",
                "Not a recognized Stern Spike card image (need a raw .img/.bin "
                "with the Spike partition layout).\n\n"
                "If the file was just copied here, the copy may still have "
                "been in progress — wait for it to finish, then try again.")
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
        flags = _category_flags(self.extract_categories)
        n = engine.extract_all(
            self.input_path, parts, self.output_dir,
            log=self._log, progress=self._progress, cancel=lambda: self._cancelled,
            phase=self._set_phase, log_line=self._log_line,
            label=display_for_key(key, self.input_path),
            duration_names=self.duration_names, **flags)
        # extract_all returns promptly on cancel (it checks between every phase
        # and per decoded sound).  Stop here instead of grinding through the
        # checksum pass and reporting success on a run the user aborted.
        self._check_cancel()

        self._set_phase(5)  # Checksums
        # A fresh decode rewrites every asset pristine, so any .orig snapshots
        # from a prior session now describe stale content — drop them.
        discard_snapshots(self.output_dir)
        # Baseline so Write/Mod Pack can tell which assets the user edited (and
        # so the Write tab accepts this folder as an Extract output).
        self._log("Generating checksums...", "info")
        self._progress(0, 0, "Generating checksums...")
        generate_checksums(self.output_dir, log_cb=self._log,
                           progress_cb=self._progress,
                           cancel=lambda: self._cancelled)
        self._check_cancel()
        self._done(True, _extract_summary(n, self.output_dir, flags))


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
        key = detect_game(self.original_path)
        if key is None:
            raise PipelineError("Detect", "Original is not a Spike card image.")
        self._check_cancel()
        self._set_phase(1)  # Stage
        _require_engine()
        self._set_phase(2)  # Re-encode audio (+ patch, inside the engine)
        n = engine.write_image(
            self.original_path, self.assets_dir, self.output_path,
            log=self._log, progress=self._progress, cancel=lambda: self._cancelled,
            label=display_for_key(key, self.original_path))
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
                 partition_override=None, extract_categories=None,
                 duration_names=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.output_dir = output_dir
        self.partition_override = partition_override
        self.extract_categories = extract_categories
        self.duration_names = duration_names

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
        flags = _category_flags(self.extract_categories)
        n = engine.extract_all(
            self.device_path, parts, self.output_dir,
            log=self._log, progress=self._progress,
            cancel=lambda: self._cancelled, phase=self._set_phase,
            open_disk=lambda: RawDeviceFile(self.device_path, writable=False),
            log_line=self._log_line,
            duration_names=self.duration_names, **flags)
        self._check_cancel()   # don't run checksums on a cancelled extract

        self._set_phase(5)  # Checksums
        # A fresh decode rewrites every asset pristine, so any .orig snapshots
        # from a prior session now describe stale content — drop them.
        discard_snapshots(self.output_dir)
        self._log("Generating checksums...", "info")
        self._progress(0, 0, "Generating checksums...")
        generate_checksums(self.output_dir, log_cb=self._log,
                           progress_cb=self._progress,
                           cancel=lambda: self._cancelled)
        self._check_cancel()
        self._done(True, _extract_summary(n, self.output_dir, flags,
                                          source=" from the SD card"))


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


class SternRevertPipeline(BasePipeline):
    """Re-derive the pristine bytes of specific assets from the source card and
    write them back over the edited copies in the assets folder.

    The fallback for "Revert" when an edit has no ``.orig`` snapshot (changed
    before snapshots existed, or hand-edited).  Audio idx are re-decoded from the
    firmware codec; loose videos/images are re-extracted.  *source* is the
    original image path, or — when ``is_device`` — the physical card device."""

    def __init__(self, source, assets_dir, rels,
                 log_cb, phase_cb, progress_cb, done_cb,
                 is_device=False, partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.source = source
        self.assets_dir = assets_dir
        self.rels = list(rels)
        self.is_device = is_device
        self.partition_override = partition_override

    def _run(self):
        self._set_phase(0)  # Read source
        _require_engine()
        if not self.rels:
            self._done(True, "Nothing to restore from the source card.")
            return
        if self.is_device:
            parts = engine.device_partitions(
                self.source, self.partition_override, log=self._log)
            reverted, failed = engine.revert_assets(
                self.source, self.assets_dir, self.rels,
                log=self._log, progress=self._progress,
                cancel=lambda: self._cancelled,
                open_disk=lambda: RawDeviceFile(self.source, writable=False),
                partitions=parts)
        else:
            key = detect_game(self.source)
            if key is None:
                raise PipelineError(
                    "Read source",
                    "The Original .img isn't a Spike card image, so the "
                    "pre-snapshot edits can't be restored from it. Re-extract "
                    "to reset those files.")
            reverted, failed = engine.revert_assets(
                self.source, self.assets_dir, self.rels,
                log=self._log, progress=self._progress,
                cancel=lambda: self._cancelled,
                label=display_for_key(key, self.source))
        self._set_phase(1)  # Done
        msg = "Restored %d original file(s) from the card." % len(reverted)
        if failed:
            msg += (" %d could not be restored (re-extract to reset those)."
                    % len(failed))
        self._done(True, msg)


class SternFlashImagePipeline(BasePipeline):
    """Flash a pre-built SD-card image (.img/.raw) onto a physical card.

    A dd-style raw block copy — distinct from the asset-modifying Write paths:
    it writes the *whole* image verbatim, so it needs neither the codec engine
    nor a Spike-card check (the image being flashed may be any image the user
    built or backed up).  Refuses an image larger than the target card and
    streams with progress + cancel.  The GUI gates this on Administrator/root
    and confirms the destructive write before reaching here."""

    def __init__(self, image_path, device_path,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.image_path = image_path
        self.device_path = device_path

    def _run(self):
        self._set_phase(0)  # Check card
        if not is_device_path(self.device_path):
            raise PipelineError(
                "Check card",
                "Flashing needs a physical drive (e.g. \\\\.\\PHYSICALDRIVE2), "
                "not a file path (got %r). Pick the card from the dropdown."
                % self.device_path)
        if not self.image_path or not os.path.isfile(self.image_path):
            raise PipelineError(
                "Check card",
                "Image file not found: %r" % self.image_path)
        self._check_cancel()

        self._set_phase(1)  # Write image
        try:
            written = flash_image_to_device(
                self.image_path, self.device_path,
                log=self._log, progress=self._progress,
                cancel=lambda: self._cancelled,
                on_verify_start=lambda: self._set_phase(2))  # Verify card
        except FlashCancelled:
            # The card is now partially written — surface it as a cancel, but
            # make clear the card is no longer usable until re-flashed.
            self._log("Flash cancelled — the card is incomplete and must be "
                      "re-flashed before use.", "error")
            self._check_cancel()   # raises PipelineError("Cancelled", ...)
            return
        except FlashError as e:
            raise PipelineError("Write image", str(e))
        self._check_cancel()

        self._set_phase(3)  # Flush
        self._done(True, "Flashed %s onto the SD card (%s)."
                   % (format_size(written), self.device_path))
