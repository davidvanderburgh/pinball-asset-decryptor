"""PAD-314 (Ales, Linux desktop): the native Linux executor asks for root only when it can
have it without a password. ``sudo bash -c`` from a GUI app has no terminal to ask on, so it
failed before the command ran, and every card write on a Linux desktop died at the loop
probe; what needs no root (debugfs on the user's own image, the mode installer, a compile)
now runs as the user."""
import subprocess

from pinball_decryptor.core import executor as EX


class _R:
    def __init__(self, rc):
        self.returncode = rc


def _fresh(monkeypatch, uid, sudo_rc=None, raise_=None):
    monkeypatch.setattr(EX.os, "getuid", lambda: uid, raising=False)
    monkeypatch.setattr(EX.NativeExecutor, "_sudo_ok", None)
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if raise_:
            raise raise_
        return _R(sudo_rc)
    monkeypatch.setattr(EX.subprocess, "run", run)
    return calls


def test_root_runs_plain_bash(monkeypatch):
    calls = _fresh(monkeypatch, 0)
    assert EX.NativeExecutor()._prefix() == ["bash", "-c"]
    assert calls == []


def test_passwordless_sudo_keeps_root_and_is_asked_once(monkeypatch):
    calls = _fresh(monkeypatch, 1000, sudo_rc=0)
    ex = EX.NativeExecutor()
    assert ex._prefix() == ["sudo", "bash", "-c"]
    assert ex._prefix() == ["sudo", "bash", "-c"]
    assert calls == [["sudo", "-n", "true"]]


def test_sudo_that_would_prompt_means_the_users_own_shell(monkeypatch):
    calls = _fresh(monkeypatch, 1000, sudo_rc=1)
    assert EX.NativeExecutor()._prefix() == ["bash", "-c"]
    assert calls == [["sudo", "-n", "true"]]


def test_no_sudo_at_all_means_the_users_own_shell(monkeypatch):
    _fresh(monkeypatch, 1000, raise_=FileNotFoundError("sudo"))
    assert EX.NativeExecutor()._prefix() == ["bash", "-c"]
    _fresh(monkeypatch, 1000, raise_=subprocess.TimeoutExpired("sudo", 15))
    assert EX.NativeExecutor()._prefix() == ["bash", "-c"]
