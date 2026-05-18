"""Helper: drive a manufacturer pipeline synchronously + return result.

Pipelines speak the 4-callback contract (log/phase/progress/done).  For
tests we don't care about progress display — we just want to know when
done_cb fires, with what success flag, and what summary text.

PipelineResult collects every log line + the final summary so
assertions can match against them.
"""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class PipelineResult:
    success: bool = None
    summary: str = ""
    log_lines: List[Tuple[str, str]] = field(default_factory=list)
    phases: List[int] = field(default_factory=list)

    def log_text(self):
        return "\n".join(f"[{lvl}] {msg}" for lvl, msg in self.log_lines)


def run_pipeline_sync(pipeline) -> PipelineResult:
    """Replace the pipeline's callbacks with collectors, run() it, return
    a PipelineResult.  Assumes pipeline.run() is synchronous (it is for
    all of our pipelines — threading is done at the App layer, not by
    the pipelines themselves).
    """
    result = PipelineResult()

    # Pipelines store callbacks under various attribute names depending
    # on which base class they use.  Patch the common ones.
    def _log(text, level="info"):
        result.log_lines.append((level, text))

    def _phase(idx):
        result.phases.append(idx)

    def _progress(cur, tot, desc=""):
        pass

    def _done(success, summary):
        result.success = success
        result.summary = summary

    # Patch every known callback attribute name; harmless if absent.
    for attr in ("_log", "log"):
        if hasattr(pipeline, attr):
            setattr(pipeline, attr, _log)
    for attr in ("_phase_cb", "phase", "on_phase"):
        if hasattr(pipeline, attr):
            setattr(pipeline, attr, _phase)
    for attr in ("_progress", "progress", "on_progress"):
        if hasattr(pipeline, attr):
            setattr(pipeline, attr, _progress)
    for attr in ("_done", "done", "on_done"):
        if hasattr(pipeline, attr):
            setattr(pipeline, attr, _done)

    pipeline.run()
    return result
