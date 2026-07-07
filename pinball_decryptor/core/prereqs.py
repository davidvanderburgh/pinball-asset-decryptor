"""Per-manufacturer runtime-prerequisite checking.

Each plugin declares a list of :class:`Prerequisite` it needs at runtime
(``gpg`` on the Windows host, ``partclone`` inside WSL, etc.).  The GUI
calls :func:`check_prerequisites` on a worker thread when the user picks
that manufacturer and renders an indicator next to each name.

Probes are cheap shell tests (e.g. ``gpg --version``).  They run with a
short timeout and capture nothing — the only thing that matters is the
exit code.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

# Prevent console flashes when launched via pythonw.exe on Windows.
_CREATE_FLAGS = (subprocess.CREATE_NO_WINDOW
                 if sys.platform == "win32" else 0)

PROBE_TIMEOUT = 8


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
    """
    try:
        if prereq.probe.startswith("python:"):
            ok, msg = _probe_python_import(prereq.probe.split(":", 1)[1])
        elif prereq.where == "host":
            ok, msg = _probe_host(prereq.probe)
        elif prereq.where == "wsl":
            ok, msg = _probe_wsl(prereq.probe)
        else:
            ok, msg = False, f"unknown probe location: {prereq.where!r}"
    except Exception as e:
        ok, msg = False, f"{type(e).__name__}: {e}"

    return PrerequisiteResult(
        name=prereq.name, ok=ok, message=msg,
        reason=prereq.reason, install_hint=prereq.install_hint,
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
    # spawn, wrongly flipping a green prereq to red mid-extract — monkeybug saw
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

def _probe_wsl(cmd: str) -> Tuple[bool, str]:
    if sys.platform != "win32":
        return True, "n/a (non-Windows)"

    if shutil.which("wsl") is None:
        return False, "wsl not on PATH"

    try:
        result = subprocess.run(
            ["wsl", "-u", "root", "--", "bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            creationflags=_CREATE_FLAGS,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {PROBE_TIMEOUT}s"

    if result.returncode == 0:
        out = (result.stdout or "").strip().splitlines()
        return True, out[0] if out else "available"
    err = (result.stderr or result.stdout or "").strip().splitlines()
    return False, (err[0] if err else f"exit {result.returncode}")
