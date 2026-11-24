"""WSL installed, Windows' Virtual Machine Platform switched off (PAD-1564).

A French Windows 10 had WSL from the Store and an Ubuntu-24.04 registered,
but the Virtual Machine Platform feature under WSL 2 was off.  Every check
that asked wsl.exe read that as "WSL2 is set up": the strip said his Ubuntu
itself was broken and sent him to `wsl --shutdown` and a second distro,
Install Missing downloaded a 414 MB runtime that could not import
(HCS_E_SERVICE_NOT_AVAILABLE), and Extract said "Install from Microsoft
Store" over three apt-install lines.  The one step that helps is switching
the feature on (`wsl --install --no-distribution`) and restarting.
"""

import subprocess
from pathlib import Path

import pytest

from pinball_decryptor.core import executor as core_executor
from pinball_decryptor.core import prereq_launch, prereqs, runtime

from tests.test_prereqs import _WSL_LIST_HEADER, _wsl_env

REPO = Path(__file__).resolve().parent.parent

# his canary error, word for word (as the fixed decode reads it): no code
_FR_FEATURE = ("L'opération n'a pas pu être démarrée car une fonctionnalité "
               "requise n'est pas installée. ")
# his first session's, which names the command WSL wants run
_FR_VMP = ("wsl: La plateforme de machine virtuelle n’est pas activée. WSL 2 "
           "risque de ne pas fonctionner correctement. Pour l’activer, "
           "exécutez : wsl.exe --install --no-distribution")


def _dead_distro_run(monkeypatch, err):
    def _run(cmd, *a, **kw):
        if list(cmd[1:3]) == ["-l", "-v"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=_WSL_LIST_HEADER + "* Ubuntu-24.04  Stopped  2\n")
        if "-l" in cmd:
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=err)
    monkeypatch.setattr(prereqs.subprocess, "run", _run)


def _assert_vm_platform_advice(msg, hint):
    assert "Virtual Machine Platform" in msg
    assert "nothing can run inside it" not in msg
    # none of the routes that cannot work here
    assert "wsl --shutdown" not in hint
    assert "--set-default" not in hint
    assert "apt" not in hint
    # ...and the one that does
    assert "Install Missing" in hint
    assert "wsl --install --no-distribution" in hint
    assert "restart" in hint


def test_his_machine_no_error_code_reads_the_missing_service(monkeypatch):
    """His second session: the French text carries no code at all, so the
    language-free fact (no vmcompute service) is what names it."""
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_vm_platform_off", lambda: True)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: False)
    _dead_distro_run(monkeypatch, _FR_FEATURE)
    ok, msg, hint = prereqs._probe_wsl("command -v partclone.ext4")
    assert ok is False
    _assert_vm_platform_advice(msg, hint)


@pytest.mark.parametrize("err", [
    _FR_VMP,
    "Error code: Wsl/Service/CreateInstance/CreateVm/HCS/"
    "HCS_E_SERVICE_NOT_AVAILABLE",
    "WslRegisterDistribution failed with error: 0x80370102",
    "Please enable the Virtual Machine Platform Windows feature and ensure "
    "virtualization is enabled in the BIOS.",
])
def test_wsl_own_words_name_it_even_when_the_service_reads_present(
        monkeypatch, err):
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: False)
    _dead_distro_run(monkeypatch, err)
    ok, msg, hint = prereqs._probe_wsl("command -v xorriso")
    assert ok is False
    _assert_vm_platform_advice(msg, hint)


def test_a_really_dead_distro_keeps_its_own_advice(monkeypatch):
    _wsl_env(monkeypatch)
    _dead_distro_run(monkeypatch, "The Windows Subsystem for Linux instance "
                                  "has terminated.\n")
    ok, msg, hint = prereqs._probe_wsl("command -v xorriso")
    assert "nothing can run inside it" in msg
    assert "wsl --shutdown" in hint


def test_bios_beats_the_feature(monkeypatch):
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_virtualization_disabled", lambda: True)
    _dead_distro_run(monkeypatch, _FR_VMP)
    ok, msg, hint = prereqs._probe_wsl("command -v xorriso")
    assert "BIOS/UEFI" in msg


def test_after_switching_it_on_it_says_restart(monkeypatch):
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_vm_platform_off", lambda: True)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: True)
    _dead_distro_run(monkeypatch, _FR_FEATURE)
    ok, msg, hint = prereqs._probe_wsl("command -v xorriso")
    assert "has not been restarted" in msg
    assert hint.startswith("Restart Windows")


def test_no_distro_and_feature_off_is_not_told_wsl_is_enabled(monkeypatch):
    _wsl_env(monkeypatch)
    monkeypatch.setattr(prereqs, "_vm_platform_off", lambda: True)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: False)
    monkeypatch.setattr(prereqs, "_wsl_status_ok", lambda: True)
    msg, hint = prereqs._diagnose_wsl_unusable()
    assert "Virtual Machine Platform" in msg
    assert "WSL is enabled" not in msg


@pytest.mark.parametrize("rc,want", [(1060, True), (0, False), (1, False)])
def test_vm_platform_off_is_only_a_missing_service(monkeypatch, rc, want):
    calls = []

    def _run(cmd, *a, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, rc)
    monkeypatch.setattr(prereqs.sys, "platform", "win32")
    monkeypatch.setattr(prereqs, "_vm_platform_off_cache", None)
    monkeypatch.setattr(prereqs.subprocess, "run", _run)
    assert prereqs._vm_platform_off() is want
    assert prereqs._vm_platform_off() is want
    assert calls == [["sc", "query", "vmcompute"]]          # asked once


def test_vm_platform_query_failing_is_not_off(monkeypatch):
    def _run(cmd, *a, **kw):
        raise OSError("no sc")
    monkeypatch.setattr(prereqs.sys, "platform", "win32")
    monkeypatch.setattr(prereqs, "_vm_platform_off_cache", None)
    monkeypatch.setattr(prereqs.subprocess, "run", _run)
    assert prereqs._vm_platform_off() is False
    monkeypatch.setattr(prereqs.sys, "platform", "linux")
    monkeypatch.setattr(prereqs, "_vm_platform_off_cache", None)
    assert prereqs._vm_platform_off() is False


def test_probe_output_is_read_as_utf8(monkeypatch):
    """WSL_UTF8=1 asks wsl.exe for UTF-8; text=True alone decoded it with the
    code page and his log read "nâ€™est pas activÃ©e"."""
    seen = {}

    def _run(cmd, *a, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(prereqs.subprocess, "run", _run)
    prereqs._run_in_wsl("exit 0", 1)
    assert seen["encoding"] == "utf-8" and seen["env"]["WSL_UTF8"] == "1"
    assert "est pas activée" == "est pas activée".encode("utf-8").decode(
        seen["encoding"], seen["errors"])


# ------------------------------------------------------------ Install Missing

def test_install_missing_switches_the_feature_on_instead_of_the_runtime():
    R = prereq_launch
    # his PC: wsl --status 0, runtime absent, feature off
    assert R.pick_route(True, True, "absent", vm_off=True) == R.ROUTE_WSL
    assert R.pick_route(True, True, "absent", vm_off=False) == R.ROUTE_RUNTIME
    # already switched on this boot: the restart is what is due
    assert R.pick_route(True, True, "absent", restart_pending=True,
                        vm_off=True) == R.ROUTE_SCRIPT
    text = R.wsl_setup_text(["WSL2", "partclone"], vm_off=True)
    assert text.startswith("WSL is installed on this PC, but Windows' "
                           "Virtual Machine Platform")
    assert "WSL2, partclone run on it" in text
    assert R.wsl_setup_text(["WSL2"]).startswith("WSL2 is not set up")


def test_installer_does_not_call_it_set_up_without_vmcompute():
    ps1 = (REPO / "installer" / "install_prerequisites.ps1").read_text(
        encoding="utf-8-sig")
    assert "function Test-VmPlatformOn" in ps1
    assert "Get-Service -Name vmcompute" in ps1
    body = ps1.split("function Install-WslPlatform", 1)[1].split(
        "\nif ($WslOnly)", 1)[0]
    # both "is WSL ready" checks, before and after the install
    assert body.count("($LASTEXITCODE -eq 0) -and (Test-VmPlatformOn)") == 2
    assert "& wsl --install --no-distribution" in body


def test_runtime_import_names_the_feature(monkeypatch, tmp_path):
    out = subprocess.CompletedProcess(
        [], 1, stdout=b"", stderr=("L'opération n'a pas pu être démarrée car une "
        "fonctionnalité requise n'est pas installée. Code d’erreur : "
        "Wsl/Service/RegisterDistro/CreateVm/HCS/HCS_E_SERVICE_NOT_AVAILABLE"
                           ).encode("utf-8"))
    assert prereqs.vm_platform_error(runtime._why(out))


# --------------------------------------------------------------- Extract gate

def test_extract_gate_names_the_feature_and_asks_no_apt(monkeypatch):
    from pinball_decryptor.plugins.jjp import pipeline as P
    from pinball_decryptor.plugins.jjp.executor import WslExecutor

    monkeypatch.setattr(prereqs, "_virtualization_disabled", lambda: False)
    monkeypatch.setattr(prereqs, "_vm_platform_off", lambda: True)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: False)
    ex = WslExecutor.__new__(WslExecutor)
    ran = []

    def _boom(cmd, *a, **kw):
        ran.append(cmd)
        raise RuntimeError("wsl failed")
    ex.run = _boom
    results = P.check_prerequisites(ex, standalone=True)
    assert [r[0] for r in results] == ["WSL2"]
    name, ok, msg = results[0]
    assert not ok and "Virtual Machine Platform" in msg
    assert "Microsoft Store" not in msg
    assert len(ran) == 1
    # the executors' own check says the same
    assert "Virtual Machine Platform" in ex.check_available()[1]
    assert "Virtual Machine Platform" in core_executor.wsl_unavailable_text()


def test_extract_gate_without_a_known_cause_keeps_the_distro_check(
        monkeypatch):
    monkeypatch.setattr(prereqs, "_virtualization_disabled", lambda: False)
    monkeypatch.setattr(prereqs, "_vm_platform_off", lambda: False)
    monkeypatch.setattr(runtime, "wsl_distro", lambda: None)
    text = core_executor.wsl_unavailable_text()
    assert "wsl -l -v" in text and "Microsoft Store" not in text
