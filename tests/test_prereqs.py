"""Prerequisite-probe robustness (no real binaries, no subprocess).

The host probe must not cry "missing" when the tool is actually installed:
monkeybug saw ffmpeg flagged missing DURING a big extract (disk + CPU churn),
then a re-check when idle said OK.  Root cause: `ffmpeg -version` was executed
with an 8 s timeout, and under load the spawn/exec blew past it.  Fix: for a
simple presence probe, resolve via shutil.which (a pure PATH scan, no
subprocess) first, and only execute when the tool isn't on PATH.
"""
import subprocess

import pytest

from pinball_decryptor.core import prereqs
from pinball_decryptor.core.prereqs import Prerequisite, check_prerequisite


def test_presence_exe_simple_vs_compound():
    assert prereqs._probe_presence_exe("ffmpeg -version") == "ffmpeg"
    assert prereqs._probe_presence_exe("gpg --version") == "gpg"
    # Compound / shell-feature probes: can't shortcut to a PATH lookup.
    assert prereqs._probe_presence_exe("ffmpeg -version | grep foo") is None
    assert prereqs._probe_presence_exe("a && b") is None
    assert prereqs._probe_presence_exe("") is None


def test_host_probe_uses_which_and_never_execs(monkeypatch):
    """An installed tool resolves via which with NO subprocess — the path that
    stays reliable while an extract is thrashing the machine."""
    monkeypatch.setattr(prereqs.shutil, "which",
                        lambda name: r"C:\ffmpeg\ffmpeg.exe")

    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called when the "
                             "binary is already on PATH")
    monkeypatch.setattr(prereqs.subprocess, "run", _boom)

    ok, msg = prereqs._probe_host("ffmpeg -version")
    assert ok is True
    assert "ffmpeg" in msg


def test_host_probe_timeout_under_load_when_not_on_path(monkeypatch):
    """When the tool genuinely isn't on PATH, a slow/timed-out exec still
    reports missing (no false green)."""
    monkeypatch.setattr(prereqs.shutil, "which", lambda name: None)

    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ffmpeg -version",
                                        timeout=prereqs.PROBE_TIMEOUT)
    monkeypatch.setattr(prereqs.subprocess, "run", _timeout)

    ok, msg = prereqs._probe_host("ffmpeg -version")
    assert ok is False
    assert "timed out" in msg


def test_check_prerequisite_ffmpeg_present(monkeypatch):
    monkeypatch.setattr(prereqs.shutil, "which",
                        lambda name: "/usr/bin/ffmpeg")
    p = Prerequisite(name="ffmpeg", where="host", probe="ffmpeg -version",
                     reason="x")
    res = check_prerequisite(p)
    assert res.ok is True
    assert res.name == "ffmpeg"
