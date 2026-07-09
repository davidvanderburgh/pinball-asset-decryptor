"""WSL executors — UNC network paths drvfs-mounted on demand.

WSL never automounts network shares, so ``\\\\plexnas\\Work\\...`` used to be
naively rewritten to ``//plexnas/Work/...`` — a path that doesn't exist inside
WSL, killing loop mount AND the xorriso fallback (monkeybug's GNR extract).
Every WSL executor now translates UNC paths onto an on-demand
``mount -t drvfs`` mount under /mnt/unc/.  These tests drive the translation
and mount bookkeeping with executor.run() recorded, so they run on every
platform and CI.
"""
import pytest

from pinball_decryptor.core import executor as core_executor
from pinball_decryptor.plugins.bof import executor as bof_executor
from pinball_decryptor.plugins.jjp import executor as jjp_executor
from pinball_decryptor.plugins.spooky import executor as spooky_executor

WSL_CLASSES = [
    pytest.param(core_executor.WslExecutor, core_executor.CommandError,
                 id="core"),
    pytest.param(jjp_executor.WslExecutor, jjp_executor.CommandError,
                 id="jjp"),
    pytest.param(bof_executor.WslExecutor, bof_executor.CommandError,
                 id="bof"),
    pytest.param(spooky_executor.WslExecutor, spooky_executor.CommandError,
                 id="spooky"),
]


def make_executor(cls, error_cls, fail=False):
    """Instantiate cls with run() recorded (and optionally failing)."""
    ex = cls()
    type(ex)._unc_mounts = {}   # isolate the class-level mount table per test
    ex.commands = []

    def fake_run(bash_cmd, timeout=120):
        ex.commands.append(bash_cmd)
        if fail:
            raise error_cls(bash_cmd, 32, "mount: cannot mount")
        return ""

    ex.run = fake_run
    return ex


@pytest.mark.parametrize("cls,error_cls", WSL_CLASSES)
def test_drive_letters_unchanged_and_no_wsl_call(cls, error_cls):
    ex = make_executor(cls, error_cls)
    assert (ex.to_exec_path(r"C:\Users\david\file.img")
            == "/mnt/c/Users/david/file.img")
    assert ex.commands == []


@pytest.mark.parametrize("cls,error_cls", WSL_CLASSES)
def test_unc_path_mounts_share_and_translates(cls, error_cls):
    ex = make_executor(cls, error_cls)
    p = ex.to_exec_path(
        r"\\plexnas\Work\Pinball\Guns N Roses\GunsNRoses-v03.03.iso")
    assert p == ("/mnt/unc/plexnas/work/"
                 "Pinball/Guns N Roses/GunsNRoses-v03.03.iso")
    assert len(ex.commands) == 1
    cmd = ex.commands[0]
    # Forward-slash drvfs source: backslashes get eaten by the extra bash
    # parse wsl.exe applies to `wsl -- bash -c` (verified on real WSL).
    assert "mount -t drvfs '//plexnas/Work'" in cmd
    assert "'/mnt/unc/plexnas/work'" in cmd
    assert "findmnt" in cmd   # idempotent across processes / app restarts


@pytest.mark.parametrize("cls,error_cls", WSL_CLASSES)
def test_share_mounted_once_case_insensitively(cls, error_cls):
    ex = make_executor(cls, error_cls)
    ex.to_exec_path(r"\\plexnas\Work\a.iso")
    ex.to_exec_path(r"\\PLEXNAS\WORK\sub\b.iso")
    assert len(ex.commands) == 1   # second path reuses the cached mount
    # A different share on the same server is its own mount.
    ex.to_exec_path(r"\\plexnas\Media\c.iso")
    assert len(ex.commands) == 2


@pytest.mark.parametrize("cls,error_cls", WSL_CLASSES)
def test_share_names_needing_sanitizing(cls, error_cls):
    ex = make_executor(cls, error_cls)
    p = ex.to_exec_path(r"\\my nas\My Share\f.iso")
    # Mount point is sanitized + hash-disambiguated; original UNC is mounted.
    assert p.startswith("/mnt/unc/my_nas-")
    assert p.endswith("/f.iso")
    assert "mount -t drvfs '//my nas/My Share'" in ex.commands[0]
    # "My_Share" must not collide with "My Share".
    p2 = ex.to_exec_path(r"\\my nas\My_Share\f.iso")
    assert p2 != p


@pytest.mark.parametrize("cls,error_cls", WSL_CLASSES)
def test_share_root_and_degenerate_paths(cls, error_cls):
    ex = make_executor(cls, error_cls)
    assert ex.to_exec_path(r"\\plexnas\Work") == "/mnt/unc/plexnas/work"
    # Server with no share: pass through (callers report the bad path).
    assert ex.to_exec_path(r"\\plexnas") == "//plexnas"
    assert len(ex.commands) == 1


@pytest.mark.parametrize("cls,error_cls", WSL_CLASSES)
def test_mount_failure_raises_helpful_error(cls, error_cls):
    ex = make_executor(cls, error_cls, fail=True)
    with pytest.raises(error_cls) as ei:
        ex.to_exec_path(r"\\deadnas\Work\a.iso")
    assert r"network share \\deadnas\Work" in ei.value.output
    # A failed mount must not be cached as mounted.
    assert (r"\\deadnas".lower().lstrip("\\"), "work") not in type(ex)._unc_mounts


@pytest.mark.parametrize("cls,error_cls", WSL_CLASSES)
def test_check_path_accessible_unc(cls, error_cls):
    if not hasattr(cls, "check_path_accessible"):
        pytest.skip("executor has no check_path_accessible")
    ok, msg = make_executor(cls, error_cls).check_path_accessible(
        r"\\plexnas\Work\Pinball")
    assert ok and msg == ""
    ok, msg = make_executor(cls, error_cls, fail=True).check_path_accessible(
        r"\\deadnas\Work\Pinball")
    assert not ok
    assert r"network share \\deadnas\Work" in msg
    assert "File Explorer" in msg
