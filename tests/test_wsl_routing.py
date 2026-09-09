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
    # CREATE_NO_WINDOW does not exist off Windows, and the scan below swallows
    # every exception - so without this the fallback silently does nothing and
    # the test passes for the wrong reason on a Linux or macOS runner, which
    # is exactly what it did.  Stubbed rather than skipped: the thing under
    # test is a string the app builds, and that is the same everywhere.
    monkeypatch.setattr(clonezilla.subprocess, "CREATE_NO_WINDOW", 0,
                        raising=False)
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


#: The Windows registry is where WSL keeps which distro is which, so the two
#: tests below can only run where there is one.  Everything else in this file
#: checks an argument list or a string, which is the same on every platform -
#: and has to be, because those are what the Linux and macOS runners see.
windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason=r"reads HKCU\...\Lxss, which exists only on Windows")


@windows_only
def test_the_disk_dialog_measures_and_resizes_the_same_distro(ours, monkeypatch):
    """usage() df's the filesystem the pipelines stage into; resize_disk()
    grows the disk named by _default_distro_vhdx().  Those were two different
    Linuxes the moment the pipelines moved into ours - so the dialog would
    report OUR distro filling up and its Resize button would grow the user's
    Ubuntu, which is a wrong answer that looks like a working feature."""
    seen = {}

    def _enum(lxss_key, want):
        seen["asked_for"] = want
        return "{guid-of-ours}"

    monkeypatch.setattr(wsl_disk, "_guid_named", _enum)
    monkeypatch.setattr(wsl_disk, "is_supported", lambda: True)

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import winreg
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: _Key())
    vals = {"DefaultDistribution": ("{guid-of-theirs}", 1),
            "BasePath": (r"C:\wsl\ours", 1),
            "DistributionName": (DISTRO, 1)}
    monkeypatch.setattr(winreg, "QueryValueEx", lambda k, n: vals[n])

    name, vhdx = wsl_disk._default_distro_vhdx()
    assert seen["asked_for"] == DISTRO, (
        "the resize still follows WSL's DefaultDistribution while every "
        "measurement in this module follows the app's own distro")
    assert name == DISTRO
    assert vhdx.endswith("ext4.vhdx")


@windows_only
def test_without_our_runtime_the_disk_dialog_follows_the_default(theirs, monkeypatch):
    asked = []
    monkeypatch.setattr(wsl_disk, "_guid_named",
                        lambda k, w: asked.append(w) or None)
    monkeypatch.setattr(wsl_disk, "is_supported", lambda: True)

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import winreg
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: _Key())
    vals = {"DefaultDistribution": ("{guid-of-theirs}", 1),
            "BasePath": (r"C:\wsl	heirs", 1),
            "DistributionName": ("Ubuntu", 1)}
    monkeypatch.setattr(winreg, "QueryValueEx", lambda k, n: vals[n])
    name, _ = wsl_disk._default_distro_vhdx()
    assert asked == [], "it went looking for a runtime that is not installed"
    assert name == "Ubuntu"


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


# --------------------------------------- EVERY executor, not the one I knew --

def _every_wsl_executor():
    """Every WslExecutor class in the app, found by importing.

    NAMED ONE AT A TIME IS HOW THIS WAS MISSED.  core/executor.py is not the
    only executor: Barrels of Fun, Jersey Jack and Spooky each carry their own,
    lifted from the standalone decryptor each plugin came from.  Routing the
    core one and testing the core one left three manufacturers' extract and
    write pipelines running in the user's distro while the prerequisite strip
    reported on ours - the exact split this work exists to end, still live for
    three of the seven makers, with a green test suite over it.

    So this discovers them instead of listing them, and a fourth executor
    added tomorrow is covered on the day it appears.
    """
    import importlib
    import pkgutil

    import pinball_decryptor.plugins as plugins
    found = {}
    mods = ["pinball_decryptor.core.executor"]
    for m in pkgutil.iter_modules(plugins.__path__):
        mods.append("pinball_decryptor.plugins.%s.executor" % m.name)
    for name in mods:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        cls = getattr(mod, "WslExecutor", None)
        if cls is not None:
            found[name] = cls
    return found


def test_the_app_has_more_than_one_executor_and_the_scan_finds_them():
    """A guard on the guard: if the plugins stop shipping their own, this test
    should be deleted deliberately rather than quietly pass over nothing."""
    found = _every_wsl_executor()
    assert "pinball_decryptor.core.executor" in found
    assert len(found) >= 4, (
        "only %d WslExecutor classes found - the scan is not seeing the "
        "plugins' own: %s" % (len(found), sorted(found)))


def test_every_executor_in_the_app_runs_in_our_runtime(ours):
    wrong = []
    for name, cls in sorted(_every_wsl_executor().items()):
        head = cls()._head()
        if head[:3] != ["wsl.exe", "-d", DISTRO]:
            wrong.append("%s -> %s" % (name, head[:4]))
    assert not wrong, (
        "these executors do not go to the app's own Linux, so the "
        "manufacturers that use them run somewhere the prerequisite strip is "
        "not reporting on: %s" % "; ".join(wrong))


def test_every_executor_falls_back_the_same_way(theirs):
    """And a machine without our runtime must be unchanged for all of them."""
    for name, cls in sorted(_every_wsl_executor().items()):
        head = cls()._head()
        assert "-d" not in head, "%s -> %s" % (name, head)
        assert head[:3] == ["wsl.exe", "-u", "root"], "%s -> %s" % (name, head)


# ------------------------------------- ...including the wrappers around them --
#
# THE HEAD IS NOT THE WHOLE ANSWER, and believing it was cost a working JJP
# extract.  `_install_robust_run_host` SHADOWS `executor.run` on the instance
# with a Popen-based version that could tree-kill a wedged WSL, and that
# replacement spelled the argument list out for itself: ["wsl", "-u", "root",
# "--", "bash", "-c"].  Nothing shadows `executor.stream`.  So `_head()` was
# routed, the test above passed, and the two halves of a single phase ran in two
# different Linuxes - the .iso mounted and listed by run() in the machine's
# default distro, piped into partclone by stream() in ours, which reported the
# parts it had been handed a second earlier as "No such file or directory".
#
# These ask the question at the level the fault lived at: what argv actually
# reaches the operating system.


class _FakeProc:
    """Just enough of Popen for both call paths."""
    returncode = 0

    def __init__(self):
        self.stdout = iter(())

    def communicate(self, timeout=None):
        return (b"", b"")

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _argv_of_each_path(monkeypatch):
    """The argv `run` and `stream` really launch, in that order."""
    from pinball_decryptor.plugins.jjp import executor as jjp_exec
    from pinball_decryptor.plugins.jjp import pipeline as jjp_pipe

    seen = []

    def _popen(cmd, *a, **kw):
        seen.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(jjp_pipe.subprocess, "Popen", _popen)
    monkeypatch.setattr(jjp_exec.subprocess, "Popen", _popen)

    ex = jjp_pipe._install_robust_run_host(jjp_exec.WslExecutor())
    ex.run("true")
    list(ex.stream("true"))
    assert len(seen) == 2, seen
    return seen


def test_the_jjp_pipeline_runs_and_streams_in_ONE_linux(ours, monkeypatch):
    """The two must agree, because one phase uses both over the same files."""
    ran, streamed = _argv_of_each_path(monkeypatch)
    assert ran[:3] == ["wsl.exe", "-d", DISTRO], ran
    assert streamed[:3] == ["wsl.exe", "-d", DISTRO], streamed
    assert ran[:-1] == streamed[:-1], (
        "run() and stream() build different heads, so a phase that mounts with "
        "one and reads with the other looks at two machines: %s vs %s"
        % (ran[:-1], streamed[:-1]))


# ------------------------------------- ...and the way back out of Linux --
#
# ★ A PATH INTO LINUX IS ALSO A PATH BACK.  Three places in the app turn a
# Linux path into a Windows one, `\\wsl.localhost\<distro>\...`, and every one
# of them has to name the distro the work was actually done in.  Chicago
# Gaming's did not: it took the first name `wsl -l -q` printed.  That agreed
# with the executor for exactly as long as the executor also used the machine's
# default distro - so this branch, which moved the executor and not the
# read-back, broke every CGC extract on a machine with our runtime.  The whole
# game was staged into PAD-Runtime by `debugfs rdump` (up to 1800 s) and then
# read back out of Ubuntu, where the directory does not exist.


def _cgc_host_path():
    from pinball_decryptor.plugins.cgc import pipeline as cgc
    p = cgc.ExtractPipeline.__new__(cgc.ExtractPipeline)
    return cgc.ExtractPipeline._exec_to_host(p, "/var/tmp/cgc_stage_x/out")


def test_the_cgc_extract_reads_back_from_the_linux_it_staged_into(
        ours, monkeypatch):
    from pinball_decryptor.plugins.cgc import pipeline as cgc
    monkeypatch.setattr(cgc.sys, "platform", "win32")
    # The old guess, still there as the no-runtime fallback, must not win.
    monkeypatch.setattr(cgc, "_detect_wsl_distro", lambda: "Ubuntu")
    host = _cgc_host_path()
    assert DISTRO in host, (
        "CGC stages into %s and reads back from %s, so the extract dies on a "
        "directory that is not there: %s" % (DISTRO, "somewhere else", host))
    assert "Ubuntu" not in host


def test_without_our_runtime_cgc_reads_back_the_way_it_always_did(
        theirs, monkeypatch):
    """A machine with no runtime keeps the old guess, unchanged."""
    from pinball_decryptor.plugins.cgc import pipeline as cgc
    monkeypatch.setattr(cgc.sys, "platform", "win32")
    monkeypatch.setattr(cgc, "_detect_wsl_distro", lambda: "Ubuntu")
    assert "Ubuntu" in _cgc_host_path()


def test_the_jjp_pipeline_falls_back_in_ONE_linux_too(theirs, monkeypatch):
    """A machine without our runtime: both go to the default, as they always
    did.  The agreement is what is being pinned, not the presence of a -d."""
    ran, streamed = _argv_of_each_path(monkeypatch)
    assert "-d" not in ran and "-d" not in streamed, (ran, streamed)
    assert ran[:-1] == streamed[:-1], (ran[:-1], streamed[:-1])
