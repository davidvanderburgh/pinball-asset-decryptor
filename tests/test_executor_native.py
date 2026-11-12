"""PAD-314 (Ales, Linux desktop): the native Linux executor asks for root only when it can
have it without a password. ``sudo bash -c`` from a GUI app has no terminal to ask on, so it
failed before the command ran, and every card write on a Linux desktop died at the loop
probe; what needs no root (debugfs on the user's own image, the mode installer, a compile)
now runs as the user."""
import subprocess

import pytest

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


# --------------------------------------------------------------------------
# PAD-1172 (Brombomb, Linux desktop): a card grow attaches the image with
# ``losetup``, which needs root.  :meth:`run` stays the user when sudo would
# ask a password, so the grow failed "Permission denied"; ``run_root`` asks
# for root through pkexec, the desktop's own password dialog.
# --------------------------------------------------------------------------

class _P:
    def __init__(self, argv, rc, out, err, seen):
        seen.append(argv)
        self.returncode = rc
        self._got = (out, err)

    def communicate(self, timeout=None):
        return self._got

    def kill(self):
        pass


def _rooted(monkeypatch, uid=1000, sudo_rc=1, pkexec="/usr/bin/pkexec",
            rc=0, out="done\n", err=""):
    _fresh(monkeypatch, uid, sudo_rc=sudo_rc)
    monkeypatch.setattr(EX.shutil, "which",
                        lambda n: pkexec if n == "pkexec" else None)
    seen = []
    monkeypatch.setattr(EX.subprocess, "Popen",
                        lambda argv, **kw: _P(argv, rc, out, err, seen))
    return seen


def test_root_route_order(monkeypatch):
    _rooted(monkeypatch, uid=0)
    assert EX.NativeExecutor().root_route() == "root"
    _rooted(monkeypatch, sudo_rc=0)
    assert EX.NativeExecutor().root_route() == "sudo"
    _rooted(monkeypatch)
    assert EX.NativeExecutor().root_route() == "pkexec"
    _rooted(monkeypatch, pkexec=None)
    assert EX.NativeExecutor().root_route() is None


def test_run_root_asks_pkexec_when_sudo_wants_a_password(monkeypatch):
    seen = _rooted(monkeypatch)
    ex = EX.NativeExecutor()
    assert ex.run_root("losetup -f --show x", timeout=5) == "done\n"
    assert seen == [["/usr/bin/pkexec", "--disable-internal-agent",
                     "bash", "-c", "losetup -f --show x"]]
    # the plain run is still the user's own shell (PAD-314 unchanged)
    assert ex._prefix() == ["bash", "-c"]


def test_run_root_with_passwordless_sudo_never_prompts(monkeypatch):
    seen = _rooted(monkeypatch, sudo_rc=0)
    ex = EX.NativeExecutor()
    got = []
    monkeypatch.setattr(ex, "run", lambda c, timeout=0: got.append(c) or "ok")
    assert ex.run_root("losetup x") == "ok"
    assert got == ["losetup x"] and seen == []


def test_a_cancelled_prompt_says_so(monkeypatch):
    _rooted(monkeypatch, rc=126, out="", err="")
    with pytest.raises(EX.CommandError, match="password prompt for root was canceled"):
        EX.NativeExecutor().run_root("losetup x")


def test_no_agent_says_what_to_start(monkeypatch):
    _rooted(monkeypatch, rc=127, out="",
            err="Error executing command as another user: No authentication agent found.")
    with pytest.raises(EX.CommandError, match="polkit authentication agent"):
        EX.NativeExecutor().run_root("losetup x")


def test_the_scripts_own_failure_comes_back_as_its_output(monkeypatch):
    _rooted(monkeypatch, rc=1, out="", err="losetup: x: failed")
    with pytest.raises(EX.CommandError, match="losetup: x: failed"):
        EX.NativeExecutor().run_root("losetup x")


def test_no_route_names_pkexec(monkeypatch):
    _rooted(monkeypatch, pkexec=None)
    with pytest.raises(EX.CommandError, match="pkexec"):
        EX.NativeExecutor().run_root("losetup x")


def test_card_grow_runs_its_script_as_root_and_refuses_with_no_route(monkeypatch):
    from pinball_decryptor.plugins.stern import card_size as cs

    class Ex:
        NO_ROOT = EX.NativeExecutor.NO_ROOT

        def __init__(self, route):
            self.route, self.calls = route, []

        def check_available(self):
            return True, "Native Linux"

        def to_exec_path(self, p):
            return p

        def root_route(self):
            return self.route

        def run(self, cmd, timeout=0):
            self.calls.append(("user", cmd))
            return "tools\nok\n"           # the probe as the user passes...

        def run_root(self, cmd, timeout=0):
            self.calls.append(("root", cmd))
            return "PAD_E2 loop 0\n"

    monkeypatch.setattr(cs, "supported", lambda: True)
    import pinball_decryptor.core.executor as exmod
    no = Ex(None)
    monkeypatch.setattr(exmod, "create_executor", lambda: no)
    with pytest.raises(cs.CardSizeError, match="needs root"):
        cs._E2fs()                          # ...but there is no root to be had
    yes = Ex("pkexec")
    monkeypatch.setattr(exmod, "create_executor", lambda: yes)
    e2 = cs._E2fs()
    e2.grow("/home/u/card.raw", 364904448, 14495513600)
    assert [w for w, _ in yes.calls] == ["user", "root"]
