"""Thread-safe message types passed from pipelines to the Tk main loop."""


class LogMsg:
    def __init__(self, text, level="info"):
        self.text = text
        self.level = level


class LinkMsg:
    def __init__(self, text, url):
        self.text = text
        self.url = url


class PhaseMsg:
    def __init__(self, index):
        self.index = index


class ProgressMsg:
    def __init__(self, current, total, desc=""):
        self.current = current
        self.total = total
        self.desc = desc


class DoneMsg:
    def __init__(self, success, summary):
        self.success = success
        self.summary = summary


class LogLineMsg:
    """Create-or-update a single *keyed* log line in place.

    Unlike :class:`LogMsg` (which always appends), a sequence of these sharing a
    ``key`` rewrite the same line — so a long decode animates one progress line
    instead of spamming a new line per tick."""
    def __init__(self, key, text, level="info"):
        self.key = key
        self.text = text
        self.level = level


class PrereqMsg:
    """One prereq probe completed (worker thread → GUI)."""
    def __init__(self, mfr_key, result):
        self.mfr_key = mfr_key  # so a stale check from an old mfr is ignored
        self.result = result    # core.prereqs.PrerequisiteResult


class UiCallMsg:
    """Run *fn* (no args) on the Tk main loop.

    For one-off UI touch-ups a worker thread needs at its end (re-enable a
    button, reset a status) that don't warrant their own message type.  Tk is
    not thread-safe, so workers must never call widget methods directly —
    they enqueue one of these instead."""
    def __init__(self, fn):
        self.fn = fn
