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
    """Pretend we're on Windows with wsl.exe on PATH, latch reset.

    Firmware virtualization defaults to fine — the real probe would spawn
    powershell, which the scripted subprocess fakes (rightly) reject.
    Virtualization-specific tests override this."""
    monkeypatch.setattr(prereqs.sys, "platform", "win32")
    monkeypatch.setattr(prereqs.shutil, "which",
                        lambda name: r"C:\Windows\System32\wsl.exe")
    monkeypatch.setattr(prereqs, "_wsl_boot_wait_failed", False)
    monkeypatch.setattr(prereqs, "_virtualization_disabled", lambda: False)


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
    ok, msg, hint = prereqs._probe_wsl("echo ok")
    assert ok is True
    assert calls == [("probe", prereqs.PROBE_TIMEOUT),
                     ("list", prereqs.PROBE_TIMEOUT),
                     ("probe", prereqs.WSL_BOOT_TIMEOUT)]


def test_wsl_timeout_without_distro_still_reports_missing(monkeypatch):
    """No registered distro: the timeout is a genuine missing — no 90 s
    wait burned on a machine that plainly doesn't have WSL set up."""
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: False)
    monkeypatch.setattr(prereqs, "_wsl_status_ok", lambda: False)
    calls = []
    _scripted_run(monkeypatch, registered=False,
                  probe_outcomes=["timeout"], calls=calls)
    ok, msg, hint = prereqs._probe_wsl("echo ok")
    assert ok is False
    assert "WSL is not installed" in msg
    assert "Install Missing" in hint
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
    ok, msg, hint = prereqs._probe_wsl("echo ok")
    assert ok is False
    assert "WSL is installed" in msg and "reboot" in msg
    assert prereqs._wsl_boot_wait_failed is True

    ok2, _, _ = prereqs._probe_wsl("echo ok")   # e.g. next prereq in the row
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
    ok, msg, hint = prereqs._probe_wsl("echo ok")
    assert ok is True
    assert prereqs._wsl_boot_wait_failed is False


# ---------------------------------------------------------------------------
# State-aware install hints when WSL can't run anything (PAD-17).
#
# `wsl --install`, restart, app still says "WSL2 missing": the restart is
# the step that ENABLES the framework, the distro install only happens on
# the post-restart installer re-run — but the static hint told the user to
# install-and-reboot again, an endless loop.  A failing probe with no
# registered distro now names the step that is actually missing.
# ---------------------------------------------------------------------------

def test_wsl_no_distro_post_restart_says_install_missing_no_reboot(
        monkeypatch):
    """The PAD-17 reporter's state: restart done (wsl --status answers),
    no distro yet.  The hint must send them to Install Missing and must
    NOT ask for another restart."""
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: False)
    monkeypatch.setattr(prereqs, "_wsl_status_ok", lambda: True)
    calls = []
    _scripted_run(monkeypatch, registered=False,
                  probe_outcomes=[1], calls=calls)
    ok, msg, hint = prereqs._probe_wsl("echo ok")
    assert ok is False
    assert "no Linux distro" in msg
    assert "Install Missing" in hint and "No restart" in hint


def test_wsl_restart_pending_says_restart_windows(monkeypatch):
    """Marker matches this boot session: the missing step is the restart
    itself, not another install."""
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: True)
    calls = []
    _scripted_run(monkeypatch, registered=False,
                  probe_outcomes=[1], calls=calls)
    ok, msg, hint = prereqs._probe_wsl("echo ok")
    assert ok is False
    assert "has not been restarted" in msg
    assert "Restart Windows" in hint


def test_wsl_fastfail_with_registered_distro_keeps_static_hint(monkeypatch):
    """A registered distro whose probe fails (e.g. WSL 1's losetup) keeps
    the real error line and the static hint (which carries the WSL 1
    conversion steps)."""
    _wsl_env(monkeypatch)

    def _run(cmd, *a, **kw):
        if "-l" in cmd:
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(
            cmd, 1, stdout="",
            stderr="losetup: cannot find an unused loop device\n")

    monkeypatch.setattr(prereqs.subprocess, "run", _run)
    ok, msg, hint = prereqs._probe_wsl("losetup -f")
    assert ok is False
    assert "losetup" in msg
    assert hint == ""


def test_check_prerequisite_wsl_hint_override_reaches_result(monkeypatch):
    """The dynamic hint must land in PrerequisiteResult.install_hint (the
    GUI's log line and tooltip read the RESULT's hint)."""
    monkeypatch.setattr(prereqs, "_probe_wsl",
                        lambda cmd: (False, "no distro", "dynamic hint"))
    p = Prerequisite(name="WSL2", where="wsl", probe="losetup -f",
                     reason="x", install_hint="static hint")
    res = check_prerequisite(p)
    assert res.install_hint == "dynamic hint"

    monkeypatch.setattr(prereqs, "_probe_wsl",
                        lambda cmd: (False, "tool missing", ""))
    res = check_prerequisite(p)
    assert res.install_hint == "static hint"


# ---------------------------------------------------------------------------
# Virtualization disabled in the BIOS/UEFI firmware (PAD-21).
#
# A laptop with virtualization switched off retried the WSL/Ubuntu install
# across three releases: wsl.exe's own "virtualization is not enabled" text
# scrolled past uncolored, and every diagnosis hint ("Install Missing", one
# more restart) named a step that cannot succeed in that state.  The
# firmware check now runs before the other diagnoses.
# ---------------------------------------------------------------------------

def test_wsl_virtualization_disabled_wins_diagnosis(monkeypatch):
    """Firmware off: say so, and do NOT send the user to Install Missing
    or another restart — neither can ever work.  Wins even over a pending
    restart, which also can't fix firmware."""
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_virtualization_disabled", lambda: True)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: True)
    monkeypatch.setattr(prereqs, "_wsl_status_ok", lambda: True)
    calls = []
    _scripted_run(monkeypatch, registered=False,
                  probe_outcomes=[1], calls=calls)
    ok, msg, hint = prereqs._probe_wsl("echo ok")
    assert ok is False
    assert "virtualization is disabled" in msg
    assert "BIOS" in hint
    assert "Install Missing" not in msg


def _cim_run(monkeypatch, stdout, returncode=0):
    """Fake the one powershell CIM query behind _virtualization_disabled,
    cache cleared so each scenario re-probes."""
    def _run(cmd, *a, **kw):
        assert cmd[0] == "powershell" and "HypervisorPresent" in " ".join(cmd)
        return subprocess.CompletedProcess(cmd, returncode,
                                           stdout=stdout, stderr="")
    monkeypatch.setattr(prereqs.subprocess, "run", _run)
    monkeypatch.setattr(prereqs, "_virt_disabled_cache", None)


def test_virtualization_disabled_needs_explicit_double_false(monkeypatch):
    _cim_run(monkeypatch, "False\nFalse\n")
    assert prereqs._virtualization_disabled() is True
    # Hypervisor already running: Windows reports the firmware flag False
    # in that state, so the flag alone must not read as "disabled".
    _cim_run(monkeypatch, "True\nFalse\n")
    assert prereqs._virtualization_disabled() is False
    _cim_run(monkeypatch, "False\nTrue\n")
    assert prereqs._virtualization_disabled() is False
    # Query failure / no answer: "don't know" is never "disabled" — a
    # wrong go-fix-your-BIOS on a healthy machine beats the user up.
    _cim_run(monkeypatch, "")
    assert prereqs._virtualization_disabled() is False
    _cim_run(monkeypatch, "False\nFalse\n", returncode=1)
    assert prereqs._virtualization_disabled() is False


def test_virtualization_probe_runs_once_per_session(monkeypatch):
    """Firmware can't change without a reboot; a 5-probe manufacturer must
    not pay the ~1 s powershell spawn five times."""
    calls = []

    def _run(cmd, *a, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="False\nFalse\n",
                                           stderr="")

    monkeypatch.setattr(prereqs.subprocess, "run", _run)
    monkeypatch.setattr(prereqs, "_virt_disabled_cache", None)
    assert prereqs._virtualization_disabled() is True
    assert prereqs._virtualization_disabled() is True
    assert len(calls) == 1


def test_restart_pending_marker_compares_boot_session(monkeypatch, tmp_path):
    marker = tmp_path / "wsl_restart_pending.txt"
    monkeypatch.setattr(prereqs, "_RESTART_MARKER", str(marker))
    monkeypatch.setattr(prereqs, "_current_boot_session_id", lambda: "123")

    assert prereqs._wsl_restart_pending() is False   # no marker file
    marker.write_text("123\n", encoding="utf-8")
    assert prereqs._wsl_restart_pending() is True    # same boot session
    marker.write_text("99\n", encoding="utf-8")
    assert prereqs._wsl_restart_pending() is False   # restart happened

    # Boot id unknown: never claim a restart is pending on guesswork.
    monkeypatch.setattr(prereqs, "_current_boot_session_id", lambda: "")
    marker.write_text("123\n", encoding="utf-8")
    assert prereqs._wsl_restart_pending() is False


def test_run_in_wsl_asks_for_utf8_errors(monkeypatch):
    """wsl.exe must be told to emit UTF-8 — its default UTF-16LE turns
    every error line into NUL-riddled mojibake under text=True."""
    seen = {}

    def _run(cmd, *a, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(prereqs.subprocess, "run", _run)
    prereqs._run_in_wsl("echo ok", 5)
    assert seen["env"]["WSL_UTF8"] == "1"
