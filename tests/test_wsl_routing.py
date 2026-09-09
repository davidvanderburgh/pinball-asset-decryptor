"""Every path into Linux goes to the SAME Linux.

The app used to have two.  The emulator rigs ran in the runtime it installs
(PAD-Runtime); the extract and write pipelines, the disk tools, the card
builder and the prerequisite strip all ran in whichever distro the machine
happened to have.  That is not a tidiness problem: a card built in one Linux
and a rig run in the other is a difference nobody wanted to reason about, and
the strip reporting on a distro nothing runs in sent people to fix a machine
that was fine.

So these tests are about AGREEMENT, not about any one module being right.
Each covers a place that builds its own ``wsl.exe`` argument list, and what
they assert is that all of them ask :func:`core.runtime.wsl_distro` and get
the same answer - including the answer "there is no runtime here", where every
one of them must behave exactly as it did before any of this existed.
"""
import subprocess
import sys

import pytest

from pinball_decryptor.core import clonezilla, executor, prereqs, runtime
from pinball_decryptor.core import wsl_disk

DISTRO = "PAD-Runtime"


@pytest.fixture
def ours(monkeypatch):
    """This machine has our runtime installed and ready."""
    monkeypatch.setattr(runtime, "wsl_distro", lambda runner=None: DISTRO)
    return DISTRO


@pytest.fixture
def theirs(monkeypatch):
    """This machine has not got it, so everything uses the default distro."""
    monkeypatch.setattr(runtime, "wsl_distro", lambda runner=None: None)


def _record(monkeypatch, module, rc=0, stdout=""):
    """Capture the argv each launcher builds, without running anything."""
    seen = []

    def _run(cmd, *a, **kw):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", _run)
    return seen


# ------------------------------------------------------------- the executor --

def test_the_pipelines_run_in_our_runtime(ours, monkeypatch):
    seen = _record(monkeypatch, executor)
    executor.WslExecutor().run("true")
    assert seen[0][:5] == ["wsl.exe", "-d", DISTRO, "-u", "root"]


def test_the_pipelines_use_the_default_distro_without_one(theirs, monkeypatch):
    seen = _record(monkeypatch, executor)
    executor.WslExecutor().run("true")
    assert "-d" not in seen[0]
    assert seen[0][:3] == ["wsl.exe", "-u", "root"]


def test_all_three_launchers_agree(ours, monkeypatch):
    """run(), stream() and popen_binary() spelled the head out separately
    once, which is three chances for one of them to reach a different Linux -
    and "the extract worked and the write did not" is what that looks like
    from outside."""
    ex = executor.WslExecutor()
    head = ex._head()
    assert head[:5] == ["wsl.exe", "-d", DISTRO, "-u", "root"]
    seen = _record(monkeypatch, executor)
    ex.run("true")
    popens = []
    monkeypatch.setattr(
        executor.subprocess, "Popen",
        lambda cmd, *a, **kw: popens.append(list(cmd)) or _FakePopen())
    ex.popen_binary("true")
    list(ex.stream("true"))
    assert seen[0][:-1] == head
    assert popens[0][:-1] == head
    assert popens[1][:-1] == head


class _FakePopen:
    returncode = 0
    stdout = iter(())

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_a_share_mounted_in_one_linux_is_not_remembered_for_another(monkeypatch):
    """The UNC mount cache lives inside a distro.  Keyed without the distro
    name, a share mounted in the machine's own Ubuntu would be handed back as
    a path that simply does not exist in ours - a pipeline failing on a file
    the user can open in Explorer."""
    executor.WslExecutor._unc_mounts.clear()
    ex = executor.WslExecutor()
    monkeypatch.setattr(ex, "run", lambda *a, **k: "")
    monkeypatch.setattr(runtime, "wsl_distro", lambda runner=None: None)
    first = ex.to_exec_path(r"\\nas\pinball\card.img")
    monkeypatch.setattr(runtime, "wsl_distro", lambda runner=None: DISTRO)
    ex.to_exec_path(r"\\nas\pinball\card.img")
    keys = list(executor.WslExecutor._unc_mounts)
    assert len(keys) == 2, "the same share was reused across two distros"
    assert {k[0] for k in keys} == {"", DISTRO}
    assert first.startswith("/mnt/unc/")
    executor.WslExecutor._unc_mounts.clear()


# ------------------------------------------------------------- the ISO share --

def test_the_iso_share_names_the_distro_the_mount_happened_in(ours, monkeypatch):
    """`\\\\wsl.localhost\\<name>` is how Windows reads what the executor
    mounted.  If the name is a different distro the mount still succeeds, the
    share still resolves, and the caller sees an EMPTY DIRECTORY - the worst
    shape a failure can take."""
    ran = []

    class _Ex:
        def to_exec_path(self, p):
            return "/mnt/c/iso"

        def run(self, cmd, timeout=None):
            ran.append(cmd)
            return ""

    host, exec_mount, _cleanup = clonezilla._mount_via_wsl("C:/iso", _Ex(), None)
    assert host == r"\\wsl.localhost\PAD-Runtime\tmp\pad_iso"
    assert exec_mount == "/tmp/pad_iso"
    assert any("mount -o loop,ro" in c for c in ran)


def test_the_iso_share_still_scans_the_list_without_our_runtime(theirs, monkeypatch):
    monkeypatch.setattr(
        clonezilla.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0,
                                                     stdout="Ubuntu-24.04\n",
                                                     stderr=""))

    class _Ex:
        def to_exec_path(self, p):
            return "/mnt/c/iso"

        def run(self, cmd, timeout=None):
            return ""

    host, _m, _c = clonezilla._mount_via_wsl("C:/iso", _Ex(), None)
    assert host == r"\\wsl.localhost\Ubuntu-24.04\tmp\pad_iso"


# ----------------------------------------------------------- the disk tools --

def test_the_disk_tools_report_on_the_linux_the_app_uses(ours, monkeypatch):
    """This module answers "how much space is WSL using, and can I shrink
    it" - a question about a specific distro.  Asked of the default one while
    the app fills ours, the number is about the wrong disk."""
    seen = _record(monkeypatch, wsl_disk, stdout="ok\n")
    wsl_disk._wsl_bash("true")
    assert seen[0][:5] == ["wsl.exe", "-d", DISTRO, "-u", "root"]


# ---------------------------------------------------- and the one rule above --

def test_the_escape_hatch_puts_everything_back(monkeypatch):
    """PAD_RUNTIME=0 is one switch for a machine where the runtime is
    installed but suspect.  It has to reach every path, not the rigs only -
    otherwise it half-fixes a machine into the two-Linux state this work
    exists to remove."""
    monkeypatch.setenv("PAD_RUNTIME", "0")
    runtime.invalidate()
    assert runtime.wsl_distro() is None
    assert runtime.wsl_head(root=True) == ["wsl.exe", "-u", "root"]
    seen = _record(monkeypatch, executor)
    executor.WslExecutor().run("true")
    assert "-d" not in seen[0]


@pytest.mark.skipif(sys.platform == "win32", reason="the not-Windows answer")
def test_off_windows_there_is_no_distro_to_route_into():
    runtime.invalidate()
    assert runtime.wsl_distro() is None
