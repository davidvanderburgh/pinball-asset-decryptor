"""PAD-1457: the app never wakes WSL to answer a status question.

The installed app launched wsl.exe about once a second on the Home tab (every
Emulate tab polled its rig from app start, for every manufacturer, and each
``wsl.exe -d X`` boots WSL), so ``wsl --shutdown`` was undone within two
seconds.  core/wsl_up.py answers "is it running?" without starting anything,
and every status poll asks it first.
"""
import importlib
import subprocess

import pytest

from pinball_decryptor.core import wsl_up


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("PAD_WSL_UP", raising=False)
    monkeypatch.setattr(wsl_up.sys, "platform", "win32")
    wsl_up.forget()
    yield
    wsl_up.forget()


def _no_wsl(monkeypatch):
    """Fail the test on any wsl.exe launch."""
    def boom(*a, **k):
        raise AssertionError("wsl.exe was launched: %r" % (a,))
    monkeypatch.setattr(wsl_up, "_list_running", boom)


def test_vm_down_answers_without_any_wsl_launch(monkeypatch):
    monkeypatch.setattr(wsl_up, "_process_names",
                        lambda: {"explorer.exe", "wslservice.exe"})
    _no_wsl(monkeypatch)
    assert wsl_up.vm_running() is False
    assert wsl_up.running_distros() == frozenset()
    assert wsl_up.distro_running("PAD-Runtime") is False
    assert wsl_up.distro_running(None) is False


def test_vm_up_lists_the_running_distros_once_for_everyone(monkeypatch):
    monkeypatch.setattr(wsl_up, "_process_names",
                        lambda: {"vmmemwsl", "explorer.exe"})
    n = []

    def listed():
        n.append(1)
        return frozenset({"ubuntu"})
    monkeypatch.setattr(wsl_up, "_list_running", listed)
    monkeypatch.setattr(wsl_up, "default_distro", lambda: "Ubuntu")
    assert wsl_up.distro_running("PAD-Runtime") is False
    assert wsl_up.distro_running("Ubuntu") is True
    assert wsl_up.distro_running(None) is True
    assert len(n) == 1, "one list answers every tab's poll for a while"


def test_old_windows_vmmem_counts_as_maybe_up(monkeypatch):
    monkeypatch.setattr(wsl_up, "_process_names", lambda: {"vmmem"})
    assert wsl_up.vm_running() is True


def test_unreadable_process_list_or_failed_list_behaves_as_before(
        monkeypatch):
    monkeypatch.setattr(wsl_up, "_process_names", lambda: None)
    assert wsl_up.vm_running() is True

    def fail():
        raise subprocess.TimeoutExpired("wsl.exe", 15)
    monkeypatch.setattr(wsl_up, "_list_running", fail)
    assert wsl_up.running_distros() is None
    assert wsl_up.distro_running("PAD-Runtime") is True


def test_off_windows_everything_is_running(monkeypatch):
    monkeypatch.setattr(wsl_up.sys, "platform", "darwin")
    assert wsl_up.vm_running() is True
    assert wsl_up.distro_running("x") is True


def test_the_env_override(monkeypatch):
    monkeypatch.setenv("PAD_WSL_UP", "0")
    _no_wsl(monkeypatch)
    assert not wsl_up.distro_running("PAD-Runtime")
    monkeypatch.setenv("PAD_WSL_UP", "1")
    assert wsl_up.distro_running("PAD-Runtime")


def test_distro_of_reads_the_command():
    assert wsl_up.distro_of(["wsl.exe", "-d", "PAD-Runtime", "-u", "root",
                             "-e", "bash"]) == "PAD-Runtime"
    assert wsl_up.distro_of(["wsl.exe", "-e", "bash", "-d", "x"]) is None
    assert wsl_up.distro_of(["wsl", "--distribution", "U", "--"]) == "U"
    assert wsl_up.distro_of(["docker", "exec"]) is False
    assert wsl_up.distro_of("wsl.exe -d x") is False


def test_cmd_would_boot(monkeypatch):
    monkeypatch.setattr(wsl_up, "_process_names", lambda: set())
    assert wsl_up.cmd_would_boot(["wsl.exe", "-d", "PAD-Runtime", "-e", "x"])
    assert not wsl_up.cmd_would_boot(["ssh", "rig", "status.sh"])


def test_list_running_parses_utf16_and_the_none_message(monkeypatch):
    class P:
        def __init__(self, out):
            self.stdout = out
    monkeypatch.setattr(wsl_up.subprocess, "run", lambda *a, **k: P(
        "Ubuntu\r\nPAD-Runtime\r\n".encode("utf-16-le")))
    assert wsl_up._list_running() == frozenset({"ubuntu", "pad-runtime"})
    monkeypatch.setattr(wsl_up.subprocess, "run", lambda *a, **k: P(
        "There are no running distributions.\r\n".encode("utf-16-le")))
    assert wsl_up._list_running() == frozenset()


def test_the_real_process_list_reads_on_windows():
    if wsl_up.sys.platform != "win32" or importlib.util.find_spec(
            "winreg") is None:
        pytest.skip("Windows only")
    names = wsl_up._process_names()
    assert names and any(n.startswith("python") for n in names)


# ------------------------------------------------ every Emulate tab's text --

@pytest.mark.parametrize("core", ["ap", "bof", "dp", "jjp", "pb", "spike1",
                                  "spooky", None])
def test_every_tab_reads_a_skipped_poll_as_stopped(core):
    mod = importlib.import_module(
        "pinball_decryptor.webui.emulate_%s_core" % core if core
        else "pinball_decryptor.webui.emulate_core")
    assert mod.state_text(wsl_up.asleep_info()) == wsl_up.ASLEEP_STATE


# ------------------------------------------------------ the shared poll gate --

def test_the_shared_poll_never_runs_a_status_call_that_would_boot(
        monkeypatch):
    from pinball_decryptor.webui import emulate_jjp_common as common
    ran = []
    monkeypatch.setattr(common.subprocess, "run",
                        lambda *a, **k: ran.append(a))
    monkeypatch.setattr(wsl_up, "_process_names", lambda: set())
    cls = next(v for v in vars(common).values()
               if isinstance(v, type) and hasattr(v, "_run_status"))
    obj = cls.__new__(cls)
    with pytest.raises(wsl_up.Asleep):
        obj._run_status(["wsl.exe", "-d", "PAD-Runtime", "-e", "bash",
                         "status.sh"])
    assert ran == []


def test_an_idle_hidden_tab_stops_polling_and_a_run_of_ours_does_not(
        monkeypatch):
    from pinball_decryptor.webui import emulate_jjp_common as common
    cls = next(v for v in vars(common).values()
               if isinstance(v, type) and hasattr(v, "_schedule_poll"))
    obj = cls.__new__(cls)
    scheduled = []

    class Loop:
        def after(self, ms, fn):
            scheduled.append(ms)
            return "job"

    class Ctx:
        loop = Loop()
    obj.ctx = Ctx()
    obj._poll_job = None
    obj._polled_once = True
    obj._last_up = False
    obj._busy = False
    obj._started_here = False
    monkeypatch.setattr(cls, "_poll_wanted", lambda self: True)
    monkeypatch.setattr(cls, "_tab_visible", lambda self: False)
    obj._schedule_poll()
    assert scheduled == [] and obj._poll_job is None
    obj._started_here = True
    obj._schedule_poll()
    assert scheduled == [cls.POLL_IDLE_MS]
    obj._poll_job = None
    obj._started_here = False
    monkeypatch.setattr(cls, "_tab_visible", lambda self: True)
    obj._schedule_poll()
    assert scheduled[-1] == cls.POLL_IDLE_MS
