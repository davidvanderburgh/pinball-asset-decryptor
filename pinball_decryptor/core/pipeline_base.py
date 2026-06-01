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

    def cancel(self):
        self._cancelled = True

    def _check_cancel(self):
        if self._cancelled:
            raise PipelineError("Cancelled", "Operation cancelled by user.")

    def _set_phase(self, index):
        self._phase_cb(index)

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
