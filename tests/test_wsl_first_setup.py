"""A new Windows PC gets from nothing to a working app without a command line
(PAD-1103).

A Pinside helper set PAD up on several PCs and on every one had to install
WSL2 and then Ubuntu-24.04 by hand: the Windows installer left its
prerequisites box unticked, and Install Missing ran a console that insists on
an Ubuntu of one exact release.  The app brings its own Linux now, so the path
is two steps: WSL2 switched on (the installer's ticked "Set up WSL2" task, or
Install Missing's -WslOnly), then the app's own Linux (Install Missing, in the
app).  These tests hold each piece of that.
"""

import os
import queue
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from pinball_decryptor import app as app_module
from pinball_decryptor.core import prereq_launch, prereqs, runtime
from pinball_decryptor.core.messages import LogMsg, UiCallMsg

REPO = Path(__file__).resolve().parent.parent
PS1 = REPO / "installer" / "install_prerequisites.ps1"
ISS = REPO / "installer" / "pinball_decryptor.iss"

R = prereq_launch


# ---------------------------------------------------------------- the route

@pytest.mark.parametrize("rows,wsl_ok,state,pending,want", [
    # WSL off: switch it on, nothing else
    (True, False, "absent", False, R.ROUTE_WSL),
    # ...unless that is already done and only the restart is due
    (True, False, "absent", True, R.ROUTE_SCRIPT),
    # WSL on, no app Linux (or an old one): install the app's own
    (True, True, "absent", False, R.ROUTE_RUNTIME),
    (True, True, "stale", False, R.ROUTE_RUNTIME),
    # the app's Linux is here: a red row is not a missing distro
    (True, True, "ready", False, R.ROUTE_SCRIPT),
    # somebody else's distro of that name, a WSL that does not answer, a
    # build with no image, a Mac: the full installer as before
    (True, True, "foreign", False, R.ROUTE_SCRIPT),
    (True, None, "unknown", False, R.ROUTE_SCRIPT),
    (True, None, "absent", False, R.ROUTE_SCRIPT),
    (True, True, "unpublished", False, R.ROUTE_SCRIPT),
    (True, False, "unsupported", False, R.ROUTE_SCRIPT),
    # only Windows-side tools missing (ffplay): nothing for WSL to do
    (False, False, "absent", False, R.ROUTE_SCRIPT),
])
def test_pick_route(rows, wsl_ok, state, pending, want):
    assert R.pick_route(rows, wsl_ok, state, restart_pending=pending) == want


def test_installer_args_wsl_only():
    args = R.installer_args("s.ps1", "m.txt", wsl_only=True)
    assert args[-1] == "-WslOnly" and "-StartedMarker" in args
    assert "-WslOnly" not in R.installer_args("s.ps1", "m.txt")


def test_questions_name_the_rows_and_never_ask_for_ubuntu():
    wsl = R.wsl_setup_text(["WSL2", "debugfs"])
    assert "WSL2, debugfs run on it" in wsl
    assert "restart" in wsl and "Install Missing again" in wsl
    assert "do not need to install Ubuntu" in wsl
    rt = R.runtime_text(["a", "b", "c", "d", "e"], 434)
    assert "a, b, c and 2 more are missing" in rt
    assert "about 434 MB" in rt and "No:" in rt
    assert "older version" in R.runtime_text(["x"], 434, stale=True)
    assert "x is missing" in R.runtime_text(["x"], 434)


# ------------------------------------------------- Install Missing in the app

def _prereq(name, where):
    return types.SimpleNamespace(name=name, where=where, probe=name)


def _fake_app(missing=("debugfs",), host_missing=()):
    rows = [_prereq(n, "wsl") for n in missing]
    rows += [_prereq(n, "host") for n in host_missing]
    results = {p.name: types.SimpleNamespace(ok=False) for p in rows}
    results["ok-row"] = types.SimpleNamespace(ok=True)
    rows.append(_prereq("ok-row", "wsl"))
    fake = types.SimpleNamespace(
        msg_queue=queue.Queue(), _prereq_results=results,
        _current_mfr=types.SimpleNamespace(prerequisites=tuple(rows)),
        ran=[], runtime_installs=0, rechecks=0)
    fake._run_install_prereqs_win = (
        lambda script, wsl_only=False: fake.ran.append((script, wsl_only)))
    for name in ("_install_route_win", "_offer_install_route_win"):
        setattr(fake, name, types.MethodType(getattr(app_module.App, name),
                                             fake))
    fake._recheck_prereqs = lambda: setattr(fake, "rechecks",
                                            fake.rechecks + 1)
    return fake


def _drain(fake):
    out = []
    while not fake.msg_queue.empty():
        out.append(fake.msg_queue.get_nowait())
    return out


def _machine(monkeypatch, wsl_ok, state, pending=False):
    monkeypatch.setattr(prereqs, "_wsl_status_ok", lambda: wsl_ok)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: pending)
    monkeypatch.setattr(runtime, "status",
                        lambda refresh=False: (state, "said"))


def test_route_counts_only_the_missing_wsl_rows(monkeypatch):
    _machine(monkeypatch, True, "absent")
    fake = _fake_app(missing=("debugfs", "make"), host_missing=("ffplay",))
    route, rows, state = fake._install_route_win()
    assert route == R.ROUTE_RUNTIME and rows == ["debugfs", "make"]
    # nothing WSL-side missing: the full installer, and wsl.exe never asked
    monkeypatch.setattr(runtime, "status", lambda refresh=False: 1 / 0)
    fake = _fake_app(missing=(), host_missing=("ffplay",))
    assert fake._install_route_win()[0] == R.ROUTE_SCRIPT


def test_script_route_runs_the_full_installer_at_once(monkeypatch):
    _machine(monkeypatch, True, "ready")
    fake = _fake_app()
    app_module.App._install_prereqs_win_route(fake, "s.ps1")
    assert fake.ran == [("s.ps1", False)] and _drain(fake) == []


def test_a_failing_route_check_falls_back_to_the_full_installer(monkeypatch):
    fake = _fake_app()
    fake._install_route_win = lambda: 1 / 0
    app_module.App._install_prereqs_win_route(fake, "s.ps1")
    assert fake.ran == [("s.ps1", False)]


class _Threads:
    """threading.Thread that runs its target at start()."""

    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def _offer(monkeypatch, fake, route, state, answer):
    monkeypatch.setattr(app_module.threading, "Thread", _Threads)
    asked = []

    def yes_no(title, message):
        asked.append(message)
        return answer

    monkeypatch.setattr(app_module.messagebox, "askyesno", yes_no)
    monkeypatch.setattr(app_module.messagebox, "askyesnocancel", yes_no)
    fake._install_runtime_from_prereqs = lambda: setattr(
        fake, "runtime_installs", fake.runtime_installs + 1)
    app_module.App._offer_install_route_win(fake, route, ["debugfs"], state,
                                            "s.ps1")
    return asked


def test_wsl_route_runs_the_script_wsl_only(monkeypatch):
    _machine(monkeypatch, False, "absent")
    fake = _fake_app()
    app_module.App._install_prereqs_win_route(fake, "s.ps1")
    [call] = _drain(fake)
    assert isinstance(call, UiCallMsg) and fake.ran == []
    asked = []
    monkeypatch.setattr(app_module.threading, "Thread", _Threads)
    monkeypatch.setattr(app_module.messagebox, "askyesno",
                        lambda t, m: asked.append(m) or True)
    call.fn()
    assert fake.ran == [("s.ps1", True)]
    assert "WSL2 is not set up" in asked[0]


def test_wsl_route_declined_does_nothing(monkeypatch):
    fake = _fake_app()
    _offer(monkeypatch, fake, R.ROUTE_WSL, "absent", False)
    assert fake.ran == [] and fake.runtime_installs == 0


@pytest.mark.parametrize("answer,ran,installs", [
    (True, [], 1),                       # Yes: the app's own Linux
    (False, [("s.ps1", False)], 0),      # No: the full installer instead
    (None, [], 0),                       # Cancel: nothing
])
def test_runtime_route_answers(monkeypatch, answer, ran, installs):
    fake = _fake_app()
    asked = _offer(monkeypatch, fake, R.ROUTE_RUNTIME, "absent", answer)
    assert fake.ran == ran and fake.runtime_installs == installs
    assert "Install the app's own Linux now?" in asked[0]


def test_runtime_install_shows_progress_then_rechecks(monkeypatch):
    from pinball_decryptor.webui import runtime_prompt
    monkeypatch.setattr(app_module.threading, "Thread", _Threads)
    banners = []
    fake = _fake_app()
    fake.window = types.SimpleNamespace(
        set_banner=lambda bid, b: banners.append((bid, b)))

    def ensure(say, progress=None, ask=None, on_blocked=None):
        say("installing")
        for done in (0, 50, 50, 100):
            progress(done, 100)
        return "ready"

    monkeypatch.setattr(runtime_prompt, "ensure", ensure)
    monkeypatch.setattr(runtime, "invalidate", lambda: None)
    app_module.App._install_runtime_from_prereqs(fake)
    msgs = _drain(fake)
    for m in msgs:
        if isinstance(m, UiCallMsg):
            m.fn()
    shown = [b["progress"] if b else None for _bid, b in banners]
    # spinner, 0 %, 50 % once, the import's spinner, then the banner goes
    assert shown == [-1, 0, 50, -1, None]
    logs = [m.text for m in msgs if isinstance(m, LogMsg)]
    assert "[prerequisites] installing" in logs
    assert any("is installed; checking again" in t for t in logs)
    assert fake.rechecks == 1


def test_failed_runtime_install_says_so_and_rechecks(monkeypatch):
    from pinball_decryptor.webui import runtime_prompt
    monkeypatch.setattr(app_module.threading, "Thread", _Threads)
    fake = _fake_app()
    fake.window = types.SimpleNamespace()        # no banners (the Tk app)
    monkeypatch.setattr(runtime_prompt, "ensure",
                        lambda **kw: "absent")
    monkeypatch.setattr(runtime, "invalidate", lambda: None)
    app_module.App._install_runtime_from_prereqs(fake)
    msgs = _drain(fake)
    for m in msgs:
        if isinstance(m, UiCallMsg):
            m.fn()
    assert any("did not install" in m.text for m in msgs
               if isinstance(m, LogMsg))
    assert fake.rechecks == 1


def test_wsl_only_survives_the_old_launch_fallback(monkeypatch):
    fake = types.SimpleNamespace(msg_queue=queue.Queue())
    monkeypatch.setattr(prereq_launch, "ElevatedConsole",
                        lambda args, cwd=None: (_ for _ in ()).throw(
                            OSError("no shell32")))
    popen = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv: popen.append(argv))
    app_module.App._run_install_prereqs_win(
        fake, os.path.join("C:" + os.sep, "PAD", "install_prerequisites.ps1"),
        True)
    assert popen and popen[0][-1].endswith(" -WslOnly'")


# ------------------------------------------------------- the strip's hints

def test_hints_point_at_the_apps_own_linux(monkeypatch):
    monkeypatch.setattr(prereqs.sys, "platform", "win32")
    monkeypatch.setattr(prereqs, "_virtualization_disabled", lambda: False)
    monkeypatch.setattr(prereqs, "_wsl_restart_pending", lambda: False)
    monkeypatch.setattr(runtime, "available", lambda: True)
    monkeypatch.setattr(prereqs, "_wsl_status_ok", lambda: True)
    msg, hint = prereqs._diagnose_wsl_unusable()
    assert "app's own Linux" in hint and "no Ubuntu needed" in hint
    assert "No restart" in hint
    monkeypatch.setattr(prereqs, "_wsl_status_ok", lambda: False)
    msg, hint = prereqs._diagnose_wsl_unusable()
    assert msg == "WSL is not installed on this machine."
    assert "sets up WSL2" in hint and "app's own Linux" in hint
    # a build with no image keeps the Ubuntu route's words
    monkeypatch.setattr(runtime, "available", lambda: False)
    msg, hint = prereqs._diagnose_wsl_unusable()
    assert "installs WSL2 + Ubuntu" in hint


# ------------------------------------------------- the Windows installer

def test_installer_offers_wsl2_ticked_and_only_without_it():
    iss = ISS.read_text(encoding="utf-8")
    [task] = [ln for ln in iss.splitlines() if ln.startswith('Name: "setupwsl"')]
    assert "Check: WslNeedsSetup" in task
    assert "unchecked" not in task, "the WSL2 task must be ticked by default"
    assert "RegKeyExists(HKLM, 'SYSTEM\\CurrentControlSet\\Services\\WslService')" in iss
    assert "LxssManager" in iss
    # the in-app updater installs silently: never a Windows feature then
    assert "not WizardSilent()" in iss
    assert "-WslOnly -Unattended" in iss
    assert "WslRestartDue := ResultCode = 3010" in iss
    assert "function NeedRestart(): Boolean;" in iss
    # Run from the script's own [Files] entry: Inno asks NeedRestart as soon
    # as the files are copied, before ssPostInstall, so a step run there was
    # never offered its restart (measured on a test build)
    [entry] = [ln for ln in iss.splitlines()
               if ln.startswith('Source: "install_prerequisites.ps1"')]
    assert entry.endswith("AfterInstall: SetUpWslIfChosen")
    assert "procedure CurStepChanged" not in iss


def test_wsl_only_runs_before_the_manufacturer_menu():
    ps1 = PS1.read_text(encoding="utf-8")
    assert "[switch]$WslOnly" in ps1 and "[switch]$Unattended" in ps1
    assert ps1.index("if ($WslOnly) {") < ps1.index('$pick = Read-Host')
    # ...and after the admin check, which it needs
    assert ps1.index("IsInRole(") < ps1.index("if ($WslOnly) {")
    body = ps1[ps1.index("function Install-WslPlatform"):
               ps1.index("if ($WslOnly) {")]
    assert "--install --no-distribution" in body
    assert "-d Ubuntu" not in body and "Ubuntu-24.04" not in body


# A harness that runs the REAL Install-WslPlatform, lifted out of the script
# by PowerShell's own parser, against stand-ins for wsl.exe, dism.exe and the
# machine facts it reads.  Nothing here touches this PC's WSL.
HARNESS = r"""
param([string]$Ps1, [string]$Spec, [string]$Marker)
$cfg = @{}
foreach ($kv in ($Spec -split ';')) { $k, $v = $kv -split '=', 2; $cfg[$k] = $v }
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Ps1, [ref]$null, [ref]$null)
$want = @('Install-WslPlatform', 'Write-Step', 'Write-OK', 'Write-Installed',
          'Write-FAIL', 'Write-SKIP', 'Write-VirtualizationBanner')
foreach ($f in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($want -contains $f.Name) { . ([scriptblock]::Create($f.Extent.Text)) }
}
$script:results = @()
$script:RestartMarker = $Marker
$global:calls = @()
$global:statusAsked = 0
function Test-VirtualizationDisabled { return ($cfg['virt'] -eq '1') }
function Test-WslFeatureEnabled { return ($cfg['feature'] -eq '1') }
function Get-BootSessionId { return 'BOOT42' }
function wsl {
    $a = $args -join ' '
    $global:calls += "wsl $a"
    Write-Output "wsl.exe says something about $a"
    if ($a -eq '--status') {
        $global:statusAsked++
        $global:LASTEXITCODE = [int]($(if ($global:statusAsked -eq 1) { $cfg['status'] } else { $cfg['after'] }))
    } elseif ($a -eq '--help') {
        if ($cfg['help'] -eq 'new') { Write-Output '  --install --no-distribution --web-download' }
        else { Write-Output '  --install -d --no-launch' }
        $global:LASTEXITCODE = 0
    } elseif ($a -like '--install*--web-download') {
        $global:LASTEXITCODE = [int]$cfg['web']
    } elseif ($a -like '--install*') {
        $global:LASTEXITCODE = [int]$cfg['install']
    } else { $global:LASTEXITCODE = 0 }
}
function dism.exe {
    $global:calls += "dism $($args -join ' ')"
    Write-Output "dism output"
    $global:LASTEXITCODE = [int]$cfg['dism']
}
$script:WslSetupCode = -1
Install-WslPlatform | Out-Null
"CODE=$script:WslSetupCode"
foreach ($c in $global:calls) { "CALL=$c" }
"MARKER=" + (Test-Path -LiteralPath $Marker)
if (Test-Path -LiteralPath $Marker) { "MARKERTEXT=" + (Get-Content -LiteralPath $Marker | Select-Object -First 1) }
"""


def _powershell():
    return shutil.which("powershell") or shutil.which("pwsh")


def _run_setup(tmp_path, marker_text=None, **cfg):
    base = dict(status="1", after="1", virt="0", feature="0", help="new",
                install="0", web="1", dism="0")
    base.update(cfg)
    harness = tmp_path / "harness.ps1"
    harness.write_text(HARNESS, encoding="utf-8")
    marker = tmp_path / "pending.txt"
    if marker_text is not None:
        marker.write_text(marker_text, encoding="utf-8")
    r = subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(harness), "-Ps1", str(PS1),
         "-Spec", ";".join("%s=%s" % kv for kv in base.items()),
         "-Marker", str(marker)],
        capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    code = [ln for ln in out if ln.startswith("CODE=")]
    assert code, r.stdout + r.stderr
    calls = [ln[5:] for ln in out if ln.startswith("CALL=")]
    has_marker = "MARKER=True" in out
    text = next((ln[11:] for ln in out if ln.startswith("MARKERTEXT=")), None)
    return int(code[0][5:]), calls, has_marker, text


needs_ps = pytest.mark.skipif(_powershell() is None,
                              reason="PowerShell not available")


@needs_ps
def test_setup_wsl_already_on(tmp_path):
    code, calls, marker, _ = _run_setup(tmp_path, marker_text="OLD",
                                        status="0")
    assert code == 0 and calls == ["wsl --status"] and not marker


@needs_ps
def test_setup_wsl_firmware_off_installs_nothing(tmp_path):
    code, calls, marker, _ = _run_setup(tmp_path, virt="1")
    assert code == 2 and calls == ["wsl --status"] and not marker


@needs_ps
def test_setup_wsl_waiting_on_this_boots_restart(tmp_path):
    code, calls, marker, _ = _run_setup(tmp_path, marker_text="BOOT42",
                                        feature="1")
    assert code == 3010 and calls == ["wsl --status"] and marker


@needs_ps
def test_setup_wsl_installs_with_no_distro_and_asks_for_restart(tmp_path):
    code, calls, marker, text = _run_setup(tmp_path)
    assert code == 3010
    assert "wsl --install --no-distribution" in calls
    assert not any("dism" in c for c in calls)
    assert not any("-d " in c for c in calls), "no distro is installed"
    assert marker and text == "BOOT42"


@needs_ps
def test_setup_wsl_ready_without_a_restart(tmp_path):
    code, calls, marker, _ = _run_setup(tmp_path, marker_text="OLD",
                                        after="0")
    assert code == 0 and not marker


@needs_ps
def test_setup_wsl_store_blocked_retries_web_download(tmp_path):
    code, calls, marker, _ = _run_setup(tmp_path, install="1", web="0")
    assert code == 3010
    assert "wsl --install --no-distribution --web-download" in calls
    assert not any("dism" in c for c in calls)


@needs_ps
def test_setup_wsl_old_wsl_exe_switches_the_features_on(tmp_path):
    code, calls, marker, _ = _run_setup(tmp_path, help="old", dism="3010")
    assert code == 3010
    assert not any(c.startswith("wsl --install") for c in calls)
    dism = [c for c in calls if c.startswith("dism")]
    assert len(dism) == 2
    assert "Microsoft-Windows-Subsystem-Linux" in dism[0]
    assert "VirtualMachinePlatform" in dism[1]
    assert "wsl --update" in calls


@needs_ps
def test_setup_wsl_failure_leaves_no_restart_marker(tmp_path):
    code, calls, marker, _ = _run_setup(tmp_path, marker_text="OLD",
                                        install="1", web="1", dism="5")
    assert code == 1 and not marker
