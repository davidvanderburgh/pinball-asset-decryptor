"""Prerequisite-probe robustness (no real binaries, no subprocess).

The host probe must not cry "missing" when the tool is actually installed:
A tester saw ffmpeg flagged missing DURING a big extract (disk + CPU churn),
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


# ---------------------------------------------------------------------------
# WSL probe vs a cold / freshly-installed VM (PAD-12).
#
# A distro's very first boot — seconds after `wsl --install` — answers slower
# than PROBE_TIMEOUT, and the timed-out probe is itself what starts the boot.
# The probe used to report "missing", so a tester's Re-check right after
# installing WSL brought the you-don't-have-WSL banner back; restarting the
# app minutes later (VM up by then) said OK.  Now a timeout with a REGISTERED
# distro waits the boot out instead of crying missing.
# ---------------------------------------------------------------------------

def _wsl_env(monkeypatch):
    """Pretend we're on Windows with wsl.exe on PATH, latch reset."""
    monkeypatch.setattr(prereqs.sys, "platform", "win32")
    monkeypatch.setattr(prereqs.shutil, "which",
                        lambda name: r"C:\Windows\System32\wsl.exe")
    monkeypatch.setattr(prereqs, "_wsl_boot_wait_failed", False)


def _scripted_run(monkeypatch, *, registered, probe_outcomes, calls):
    """Fake subprocess.run for wsl invocations only.

    ``wsl -l -q`` exits 0 iff *registered*.  Each in-VM probe consumes the
    next entry of *probe_outcomes*: "timeout" raises, an int returns that
    exit code (stdout "ok").  Every call is appended to *calls* as
    (kind, timeout)."""
    outcomes = list(probe_outcomes)

    def _run(cmd, *a, **kw):
        assert cmd[0] == "wsl"
        if "-l" in cmd:
            calls.append(("list", kw.get("timeout")))
            return subprocess.CompletedProcess(
                cmd, 0 if registered else 1)
        calls.append(("probe", kw.get("timeout")))
        outcome = outcomes.pop(0)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd=cmd,
                                            timeout=kw.get("timeout"))
        return subprocess.CompletedProcess(cmd, outcome,
                                           stdout="ok\n", stderr="")

    monkeypatch.setattr(prereqs.subprocess, "run", _run)


def test_wsl_cold_boot_timeout_retries_and_succeeds(monkeypatch):
    """Timeout + registered distro == a booting VM: wait it out and pass."""
    _wsl_env(monkeypatch)
    calls = []
    _scripted_run(monkeypatch, registered=True,
                  probe_outcomes=["timeout", 0], calls=calls)
    ok, msg = prereqs._probe_wsl("echo ok")
    assert ok is True
    assert calls == [("probe", prereqs.PROBE_TIMEOUT),
                     ("list", prereqs.PROBE_TIMEOUT),
                     ("probe", prereqs.WSL_BOOT_TIMEOUT)]


def test_wsl_timeout_without_distro_still_reports_missing(monkeypatch):
    """No registered distro: the timeout is a genuine missing — no 90 s
    wait burned on a machine that plainly doesn't have WSL set up."""
    _wsl_env(monkeypatch)
    calls = []
    _scripted_run(monkeypatch, registered=False,
                  probe_outcomes=["timeout"], calls=calls)
    ok, msg = prereqs._probe_wsl("echo ok")
    assert ok is False
    assert "timed out" in msg
    assert ("probe", prereqs.WSL_BOOT_TIMEOUT) not in calls


def test_wsl_hung_vm_says_installed_and_latches(monkeypatch):
    """Retry also times out (reboot pending): the message must say WSL IS
    installed — not the misleading not-installed reason — and the latch
    keeps the NEXT probe from burning another boot wait."""
    _wsl_env(monkeypatch)
    calls = []
    _scripted_run(monkeypatch, registered=True,
                  probe_outcomes=["timeout", "timeout", "timeout"],
                  calls=calls)
    ok, msg = prereqs._probe_wsl("echo ok")
    assert ok is False
    assert "WSL is installed" in msg and "reboot" in msg
    assert prereqs._wsl_boot_wait_failed is True

    ok2, msg2 = prereqs._probe_wsl("echo ok")   # e.g. next prereq in the row
    assert ok2 is False
    # Fast fail: one more short probe, no second registration check and no
    # second boot wait.
    assert calls == [("probe", prereqs.PROBE_TIMEOUT),
                     ("list", prereqs.PROBE_TIMEOUT),
                     ("probe", prereqs.WSL_BOOT_TIMEOUT),
                     ("probe", prereqs.PROBE_TIMEOUT)]


def test_wsl_success_clears_boot_latch(monkeypatch):
    """Once the VM finally answers (say the user rebooted), the latch resets
    so a later cold start gets the boot-wait treatment again."""
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_wsl_boot_wait_failed", True)
    calls = []
    _scripted_run(monkeypatch, registered=True,
                  probe_outcomes=[0], calls=calls)
    ok, msg = prereqs._probe_wsl("echo ok")
    assert ok is True
    assert prereqs._wsl_boot_wait_failed is False
