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


class PrereqMsg:
    """One prereq probe completed (worker thread → GUI)."""
    def __init__(self, mfr_key, result):
        self.mfr_key = mfr_key  # so a stale check from an old mfr is ignored
        self.result = result    # core.prereqs.PrerequisiteResult
