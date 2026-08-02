"""Per-manufacturer runtime-prerequisite checking.

Each plugin declares a list of :class:`Prerequisite` it needs at runtime
(``gpg`` on the Windows host, ``partclone`` inside WSL, etc.).  The GUI
calls :func:`check_prerequisites` on a worker thread when the user picks
that manufacturer and renders an indicator next to each name.

Probes are cheap shell tests (e.g. ``gpg --version``).  They run with a
short timeout and capture nothing — the only thing that matters is the
exit code.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

# Prevent console flashes when launched via pythonw.exe on Windows.
_CREATE_FLAGS = (subprocess.CREATE_NO_WINDOW
                 if sys.platform == "win32" else 0)

PROBE_TIMEOUT = 8

# How long to indulge a WSL utility VM that is still booting before calling
# the probe failed.  A distro's very first start — the one that happens
# seconds after `wsl --install` finishes — unpacks the rootfs and registers
# the user before it answers anything, routinely blowing far past
# PROBE_TIMEOUT.  Only ever waited on when a distro is REGISTERED (see
# _probe_wsl), so a machine with no WSL still fails fast.
WSL_BOOT_TIMEOUT = 90

# Latch: True after a boot-wait retry has itself timed out (VM hung — in
# practice a pending post-install reboot).  While set, further probes skip
# the WSL_BOOT_TIMEOUT wait so a 5-probe manufacturer doesn't spend 90 s
# per probe on a VM that isn't coming up; any successful probe clears it.
_wsl_boot_wait_failed = False


@dataclass(frozen=True)
class Prerequisite:
    """A single runtime dependency of a manufacturer plugin.

    Attributes:
        name: Short label shown in the GUI indicator (e.g. ``"gpg"``).
        where: ``"host"`` to probe on the Windows/macOS/Linux host, or
            ``"wsl"`` to probe inside WSL on Windows (a no-op everywhere
            else, since BOF/JJP/Spooky use Docker on macOS instead).
        probe: Shell command string whose exit-zero == "available".
        reason: Human-readable explanation for the tooltip / install hint.
        install_hint: Optional text shown to the user if missing
            (e.g. ``"Run Install Prerequisites from the Start Menu"``).
    """
    name: str
    where: str  # "host" or "wsl"
    probe: str
    reason: str
    install_hint: str = ""


@dataclass(frozen=True)
class PrerequisiteResult:
    name: str
    ok: bool
    message: str
    reason: str = ""
    install_hint: str = ""


def check_prerequisite(prereq: Prerequisite) -> PrerequisiteResult:
    """Run a single probe and return a result.

    Never raises — any unexpected error is reported as ``ok=False`` with
    the exception text in :attr:`PrerequisiteResult.message`.

    Probe formats:
        * ``"python:<module>"`` -- import-checks ``<module>`` in the
          current Python process.  Use this for pip-installed deps
          (e.g. ``"python:faster_whisper"``).  Works regardless of
          whether the app runs from source or a PyInstaller bundle --
          the import always resolves against the running interpreter.
        * any other string -- shell command; exit-zero means OK.
          Runs on the host shell when ``where == "host"`` or inside
          WSL when ``where == "wsl"``.

    A failed WSL probe may swap the prerequisite's static install hint
    for a state-specific one (see :func:`_diagnose_wsl_unusable`) — the
    result's :attr:`install_hint` is what the GUI must show, not the
    :class:`Prerequisite`'s.
    """
    hint_override = ""
    try:
        if prereq.probe.startswith("python:"):
            ok, msg = _probe_python_import(prereq.probe.split(":", 1)[1])
        elif prereq.where == "host":
            ok, msg = _probe_host(prereq.probe)
        elif prereq.where == "wsl":
            ok, msg, hint_override = _probe_wsl(prereq.probe)
        else:
            ok, msg = False, f"unknown probe location: {prereq.where!r}"
    except Exception as e:
        ok, msg = False, f"{type(e).__name__}: {e}"

    return PrerequisiteResult(
        name=prereq.name, ok=ok, message=msg,
        reason=prereq.reason,
        install_hint=hint_override or prereq.install_hint,
    )


def _probe_python_import(module_name: str) -> Tuple[bool, str]:
    """Try to ``import`` *module_name* in the current process.

    No subprocess (and no PATH lookup) -- always uses ``sys.executable``'s
    site-packages, which is exactly what the app will use at runtime.
    """
    import importlib
    try:
        mod = importlib.import_module(module_name)
    except ImportError as e:
        return False, str(e)
    version = getattr(mod, "__version__", "available")
    return True, f"{module_name} {version}"


def check_prerequisites(prereqs) -> List[PrerequisiteResult]:
    """Run every probe in *prereqs* sequentially.  Caller can offload
    to a worker thread; each probe is bounded by :data:`PROBE_TIMEOUT`."""
    return [check_prerequisite(p) for p in prereqs]


# ---------------------------------------------------------------------------
# Host-side probe — uses the OS's default shell.
# ---------------------------------------------------------------------------

# Shell features that make a probe more than a plain "is this binary present?"
# check.  When any appear we must actually run the command — PATH presence of
# the leading token can't stand in for the whole pipeline's exit code.
_SHELL_METACHARS = set("|&;<>()$`\n*?[]{}")


def _probe_presence_exe(cmd: str) -> Optional[str]:
    """The leading executable of *cmd* when it is a simple presence probe
    (``ffmpeg -version``, ``gpg --version``), else None for compound shell
    commands where we can't substitute a PATH lookup for running it."""
    if not cmd or any(c in _SHELL_METACHARS for c in cmd):
        return None
    parts = cmd.split()
    return parts[0] if parts else None


def _probe_host(cmd: str) -> Tuple[bool, str]:
    # Fast, load-proof path for binary-presence probes: shutil.which is a pure
    # PATH scan (no subprocess), so an installed tool resolves instantly even
    # while a big extract + disk churn hammer the machine.  Actually executing
    # `ffmpeg -version` under that load can blow past PROBE_TIMEOUT or fail to
    # spawn, wrongly flipping a green prereq to red mid-extract — a tester saw
    # ffmpeg flagged missing during a Led Zeppelin extract, then a re-check when
    # idle said OK.  Only fall through to running the command when the tool
    # ISN'T on PATH (a genuine "not installed") or the probe is compound.
    exe = _probe_presence_exe(cmd)
    if exe and shutil.which(exe):
        return True, f"{exe} on PATH"
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            creationflags=_CREATE_FLAGS,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {PROBE_TIMEOUT}s"
    except OSError as e:
        return False, str(e)

    if result.returncode == 0:
        # Show the first non-empty line of output as a message hint
        out = (result.stdout or "").strip().splitlines()
        return True, out[0] if out else "available"
    err = (result.stderr or result.stdout or "").strip().splitlines()
    return False, (err[0] if err else f"exit code {result.returncode}")


# ---------------------------------------------------------------------------
# WSL probe — Windows only.  On macOS/Linux returns a friendly skip
# (Docker / native execution is used by those platforms instead).
# ---------------------------------------------------------------------------

def _probe_wsl(cmd: str) -> Tuple[bool, str, str]:
    """Run *cmd* inside WSL.  Returns ``(ok, message, hint_override)``;
    the override is ``""`` whenever the prerequisite's static install
    hint still applies.

    A failing probe hides very different machine states behind the same
    red X, and the static hint (``wsl --install`` + reboot) is only right
    for one of them.  A user who HAD restarted Windows — leaving WSL
    enabled but distro-less, because the distro install is the step that
    runs after the restart — was told to install-and-reboot again, an
    endless loop (PAD-17; the pre-restart half of it was PAD-16).  When
    no registered distro can explain the failure, we diagnose which step
    is actually missing and say that instead.
    """
    global _wsl_boot_wait_failed
    if sys.platform != "win32":
        return True, "n/a (non-Windows)", ""

    if shutil.which("wsl") is None:
        msg, hint = _diagnose_wsl_unusable()
        return False, msg, hint

    try:
        result = _run_in_wsl(cmd, PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        # A cold utility VM — above all a distro's FIRST boot, seconds after
        # `wsl --install` — takes longer than PROBE_TIMEOUT to answer, and
        # the timed-out attempt is itself what kicks the boot off.  Reporting
        # "missing" here handed a tester a you-don't-have-WSL banner on the
        # Re-check right after installing WSL; restarting the app minutes
        # later (VM up by then) said OK.  Distinguish cold from absent via
        # the registration list, then wait the boot out.
        if _wsl_boot_wait_failed:
            return False, f"timed out after {PROBE_TIMEOUT}s", ""
        if not _wsl_distro_registered():
            msg, hint = _diagnose_wsl_unusable()
            return False, msg, hint
        try:
            result = _run_in_wsl(cmd, WSL_BOOT_TIMEOUT)
        except subprocess.TimeoutExpired:
            _wsl_boot_wait_failed = True
            return False, (
                f"WSL is installed but didn't answer within "
                f"{WSL_BOOT_TIMEOUT}s. If it was just installed, reboot "
                f"Windows to finish setup, then hit Re-check."), ""

    if result.returncode == 0:
        _wsl_boot_wait_failed = False
        out = (result.stdout or "").strip().splitlines()
        return True, out[0] if out else "available", ""

    # Non-zero exit with a registered distro: the distro answered and the
    # tool inside it is missing/broken (e.g. the WSL 1 loop-device case) —
    # the static hint is the right advice.  Without one, the "error" is
    # just wsl.exe saying there is nothing to run the command in.
    if not _wsl_distro_registered():
        msg, hint = _diagnose_wsl_unusable()
        return False, msg, hint
    err = (result.stderr or result.stdout or "").strip().splitlines()
    return False, (err[0] if err else f"exit {result.returncode}"), ""


def _run_in_wsl(cmd: str, timeout: float) -> subprocess.CompletedProcess:
    # WSL_UTF8=1: wsl.exe's own diagnostics ("no installed distributions",
    # the 0x80370102 virtualization error, ...) default to UTF-16LE, which
    # text=True renders as NUL-riddled mojibake in the tooltip and log.
    return subprocess.run(
        ["wsl", "-u", "root", "--", "bash", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=dict(os.environ, WSL_UTF8="1"),
        creationflags=_CREATE_FLAGS,
    )


def _wsl_distro_registered() -> bool:
    """True when WSL has at least one registered distro.

    ``wsl -l -q`` is answered by wslservice straight from the registry —
    fast, and no VM boot — and exits non-zero both when the WSL feature is
    absent and when no distro is installed yet.  Output is ignored on
    purpose: wsl.exe prints UTF-16LE (``text=True`` would mangle it) and
    only the exit code matters here."""
    try:
        return subprocess.run(
            ["wsl", "-l", "-q"],
            capture_output=True,
            timeout=PROBE_TIMEOUT,
            creationflags=_CREATE_FLAGS,
        ).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# "Why can't WSL run anything?" diagnosis — feeds the state-specific
# install hints (PAD-17).
# ---------------------------------------------------------------------------

# The prerequisite installer records which boot session ran `wsl --install`
# here, keyed on LastBootUpTime (see installer/install_prerequisites.ps1,
# PAD-16).  While the first line still equals the CURRENT boot session's
# id, the Windows restart that finishes WSL2 setup hasn't happened yet.
_RESTART_MARKER = os.path.join(
    os.environ.get("ProgramData", r"C:\ProgramData"),
    "Pinball Asset Decryptor", "wsl_restart_pending.txt")

# LastBootUpTime can't change while this process lives (a reboot takes the
# app down with it), so one PowerShell spawn per session is enough.
_boot_session_id_cache: Optional[str] = None


def _current_boot_session_id() -> str:
    """This boot session's id, computed exactly like the installer writes
    it (WMI LastBootUpTime as FILETIME) so the strings compare equal.
    Empty string when it can't be determined."""
    global _boot_session_id_cache
    if _boot_session_id_cache is None:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-CimInstance Win32_OperatingSystem)"
                 ".LastBootUpTime.ToFileTime()"],
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT,
                creationflags=_CREATE_FLAGS,
            )
            _boot_session_id_cache = ((result.stdout or "").strip()
                                      if result.returncode == 0 else "")
        except (subprocess.TimeoutExpired, OSError):
            _boot_session_id_cache = ""
    return _boot_session_id_cache


def _wsl_restart_pending() -> bool:
    """True when the installer ran `wsl --install` in THIS boot session,
    i.e. the restart that finishes WSL2 setup hasn't happened yet.  (The
    installer clears the marker once WSL2 answers; a marker from a
    PREVIOUS session just means the user restarted and never re-ran it.)"""
    try:
        with open(_RESTART_MARKER, encoding="utf-8-sig") as f:
            marker = f.readline().strip()
    except OSError:
        return False
    if not marker:
        return False
    boot_id = _current_boot_session_id()
    return bool(boot_id) and marker == boot_id


def _wsl_status_ok() -> bool:
    """True when the WSL framework itself is installed and answering
    (``wsl --status`` exits 0 even with zero distros registered)."""
    try:
        return subprocess.run(
            ["wsl", "--status"],
            capture_output=True,
            timeout=PROBE_TIMEOUT,
            creationflags=_CREATE_FLAGS,
        ).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# Firmware can't change while Windows is running (flipping it takes a trip
# through the BIOS/UEFI setup screen and a reboot), so one PowerShell spawn
# per session is enough — _diagnose_wsl_unusable runs once per failing probe
# and a 5-probe manufacturer would otherwise pay ~1 s each.
_virt_disabled_cache: Optional[bool] = None


def _virtualization_disabled() -> bool:
    """True only when this machine EXPLICITLY reports hardware
    virtualization switched off in its BIOS/UEFI firmware.

    Two WMI facts, checked in order: ``HypervisorPresent`` True means a
    hypervisor is already running, so virtualization is fine — Windows
    reports the firmware flag as False in that state, which is why the
    flag alone can't be trusted.  Only with no hypervisor running AND
    ``VirtualizationFirmwareEnabled`` explicitly False is the firmware
    the problem.  Any query failure means "don't know", never "disabled"
    — a wrong "enable it in your BIOS" on a healthy machine would be
    worse than the generic hint."""
    global _virt_disabled_cache
    if _virt_disabled_cache is None:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-CimInstance Win32_ComputerSystem).HypervisorPresent;"
                 "@(Get-CimInstance Win32_Processor)[0]"
                 ".VirtualizationFirmwareEnabled"],
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT,
                creationflags=_CREATE_FLAGS,
            )
            lines = [ln.strip().lower()
                     for ln in (result.stdout or "").splitlines()
                     if ln.strip()]
            _virt_disabled_cache = (result.returncode == 0
                                    and lines == ["false", "false"])
        except (subprocess.TimeoutExpired, OSError):
            _virt_disabled_cache = False
    return _virt_disabled_cache


def _diagnose_wsl_unusable() -> Tuple[str, str]:
    """(message, install_hint) when WSL can't run our probe at all — no
    registered distro, or no WSL.  Four machine states hide behind that
    one symptom and each has a different next step; naming the wrong one
    (the static install-and-reboot hint) looped a user through pointless
    restarts (PAD-17).

    The firmware check comes first: with virtualization disabled in the
    BIOS/UEFI, no install, restart, or Install Missing click can ever
    succeed — wsl.exe does say so, but its plain-color error scrolled
    past a user unnoticed through three whole support round-trips while
    every other state's hint kept him retrying the install (PAD-21)."""
    if _virtualization_disabled():
        return ("WSL2 cannot start: hardware virtualization is disabled "
                "in this computer's BIOS/UEFI firmware, so installing "
                "WSL/Ubuntu again will not help.",
                "Reboot into the BIOS/UEFI setup screen and enable "
                "virtualization — the option is named Intel VT-x, AMD-V, "
                "SVM Mode, or Virtualization Technology, usually under "
                "Advanced or CPU settings. Then click 'Install Missing' "
                "above the tabs. If the firmware has no such option, this "
                "machine cannot run WSL2.")
    if _wsl_restart_pending():
        return ("WSL2 was installed, but Windows has not been restarted "
                "since — the restart is what finishes WSL2 setup.",
                "Restart Windows (use Restart; with Fast Startup, Shut "
                "down is not a restart), then click 'Install Missing' "
                "above the tabs to finish.")
    if _wsl_status_ok():
        return ("WSL is enabled, but no Linux distro is installed yet — "
                "normal right after the post-install restart; one step "
                "remains.",
                "Click 'Install Missing' above the tabs — it installs "
                "Ubuntu and the Linux-side tools. No restart is needed "
                "this time.")
    return ("WSL is not installed on this machine.",
            "Click 'Install Missing' above the tabs — it installs WSL2 + "
            "Ubuntu and asks for one Windows restart.")
