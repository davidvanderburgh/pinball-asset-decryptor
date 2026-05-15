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
