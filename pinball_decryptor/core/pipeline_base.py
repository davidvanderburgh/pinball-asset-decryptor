"""Pipeline base class — uniform contract for every manufacturer plugin.

A pipeline reports progress through four callbacks:
  log_cb(text, level)              — append to the log pane
  phase_cb(index)                  — light up phase indicator N
  progress_cb(current, total, desc) — drive the progress bar
  done_cb(success, summary)        — terminal message
"""


class PipelineError(Exception):
    def __init__(self, phase, message):
        self.phase = phase
        self.message = message
        super().__init__(message)


class BasePipeline:
    def __init__(self, log_cb, phase_cb, progress_cb, done_cb):
        self._log = log_cb
        self._phase_cb = phase_cb
        self._progress = progress_cb
        self._done = done_cb
        self._cancelled = False
        # Optional in-place keyed-log-line callback (live per-sound decode
        # progress).  None until the App wires it via ``set_log_line_cb``; the
        # ``_log_line`` helper falls back to a plain append when unset.
        self._log_line_cb = None
        # Active progress "band" — a [lo, hi] sub-range of 0..100 that
        # phase-local progress is mapped into, so a multi-phase pipeline
        # drives ONE monotonic 0→100 bar instead of resetting each phase.
        # Default full-range, so plugins that don't set bands are
        # unaffected (``_bp`` then behaves like ``_progress``).
        self._band = (0.0, 100.0)

    def _set_band(self, lo, hi):
        """Set the global progress band subsequent ``_bp`` calls map into."""
        self._band = (float(lo), float(hi))

    def _bp(self, cur, total, desc=""):
        """Banded progress: map a phase-local ``(cur, total)`` into the
        active band and emit a global 0..100 value.  ``total<=0`` reports
        the band floor (a definite value, NOT indeterminate) so the bar
        never flips animation styles or resets mid-run."""
        lo, hi = self._band
        frac = (min(max(cur, 0), total) / total) if total and total > 0 else 0.0
        self._progress(int(round(lo + (hi - lo) * frac)), 100, desc)

    def cancel(self):
        self._cancelled = True

    def _check_cancel(self):
        if self._cancelled:
            raise PipelineError("Cancelled", "Operation cancelled by user.")

    def _set_phase(self, index):
        self._phase_cb(index)

    def set_log_line_cb(self, cb):
        """Wire the in-place keyed-log-line callback (``cb(key, text, level)``)."""
        self._log_line_cb = cb

    def _log_line(self, key, text, level="info"):
        """Create/update a keyed log line in place when a callback is wired,
        else fall back to a plain appended log line."""
        if self._log_line_cb is not None:
            self._log_line_cb(key, text, level)
        else:
            self._log(text, level)

    def run(self):
        try:
            self._run()
        except PipelineError as e:
            self._done(False, e.message)
        except Exception as e:
            # Unexpected (non-PipelineError) failures used to surface only as
            # a one-line modal with no detail — impossible to diagnose from a
            # user's screenshot.  Dump the full traceback to the log pane (the
            # console the user can see + copy) before the terminal modal.
            try:
                import traceback
                self._log(f"Unexpected error: {e}", "error")
                self._log(traceback.format_exc().rstrip(), "error")
            except Exception:
                pass  # logging must never mask the original failure
            self._done(False, f"Unexpected error: {e}")

    def _run(self):
        raise NotImplementedError


class ReadCardPipeline(BasePipeline):
    """Read a whole physical card into a raw image file (the inverse of the
    flash-image pipeline).

    Manufacturer-agnostic on purpose: a card dump is the same sector copy for
    every plugin whose medium is a raw card image, so :class:`Manufacturer`
    hands this out directly rather than each plugin re-implementing it.  The
    GUI collects and confirms the card + destination first; elevation is
    handled inside (only the read is elevated, like the flash).
    """

    PHASES = ("Check card", "Read card", "Save image")

    def __init__(self, device_path, image_path,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.image_path = image_path

    def _run(self):
        import os

        from .elevated_flash import read_device_with_privileges
        from .rawdevice import (FlashCancelled, FlashError, format_size,
                                is_device_path)

        self._set_phase(0)  # Check card
        if not is_device_path(self.device_path):
            raise PipelineError(
                "Check card",
                "Reading a card needs a physical drive (e.g. "
                "\\\\.\\PHYSICALDRIVE2), not a file path (got %r). Pick the "
                "card from the dropdown." % self.device_path)
        if not self.image_path:
            raise PipelineError("Check card",
                                "Pick where the image file should be saved.")
        if os.path.isdir(self.image_path):
            raise PipelineError(
                "Check card",
                "%r is a folder — give the image a file name too."
                % self.image_path)
        self._check_cancel()

        self._set_phase(1)  # Read card
        try:
            read = read_device_with_privileges(
                self.device_path, self.image_path,
                log=self._log, progress=self._progress,
                cancel=lambda: self._cancelled)
        except FlashCancelled:
            # Nothing was written to the card and the partial image was
            # deleted, so there is nothing for the user to clean up.
            self._log("Read cancelled — the partial image was discarded. "
                      "The card itself was not changed.", "info")
            self._check_cancel()   # raises PipelineError("Cancelled", ...)
            return
        except FlashError as e:
            raise PipelineError("Read card", str(e))
        self._check_cancel()

        self._set_phase(2)  # Save image
        self._done(True, "Saved %s from the card to %s."
                   % (format_size(read), self.image_path))
