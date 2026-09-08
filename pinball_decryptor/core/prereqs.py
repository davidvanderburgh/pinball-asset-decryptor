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

from .pkgnames import localize_hint

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

    # SPELLED FOR THIS LINUX.  Every plugin's hint says "apt-get install X
    # (in WSL)", written when Windows was the only desktop: on a Linux desktop
    # the "(in WSL)" is wrong on every distro, and on Arch the name is too -
    # a user on Omarchy translated them by hand (2026-09-06).  Done here, the
    # one place both the tooltip and the log line read from, and a no-op off
    # Linux and for a hint that names no apt package.
    return PrerequisiteResult(
        name=prereq.name, ok=ok, message=msg,
        reason=prereq.reason,
        install_hint=localize_hint(hint_override or prereq.install_hint),
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
    """The executable *cmd* is a presence probe FOR (``ffmpeg -version``,
    ``gpg --version``, ``command -v ffmpeg``), else None for compound shell
    commands where we can't substitute a PATH lookup for running it.

    ``command -v X`` is named here because it is what an in-guest probe is
    spelled as now (PAD-114: ``which`` is a package, and one Debian has been
    shedding).  Without this, the leading word would be "command" - a shell
    builtin, never on PATH - so the fast path would miss and the probe would
    be run through a shell that on Windows is cmd.exe, where it means nothing.
    """
    if not cmd or any(c in _SHELL_METACHARS for c in cmd):
        return None
    parts = cmd.split()
    if len(parts) == 3 and parts[0] == "command" and parts[1] in ("-v", "-V"):
        return parts[2]
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

    The same is true one state further along: a distro that ANSWERS but
    can't hand out a loop device is a working WSL install, and leading
    with ``wsl --install`` there sent a user off to reinstall WSL while
    the prerequisite installer told him it was already there — neither
    half of the app naming the thing that was actually wrong (PAD-73).
    See :func:`_diagnose_wsl_loop_failure`.
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
    # tool inside it is missing/broken — the static hint (an apt install)
    # is the right advice.  Without one, the "error" is just wsl.exe
    # saying there is nothing to run the command in.
    if not _wsl_distro_registered():
        msg, hint = _diagnose_wsl_unusable()
        return False, msg, hint
    lines = (result.stderr or result.stdout or "").strip().splitlines()
    err = lines[0] if lines else f"exit {result.returncode}"
    # ...but "the distro answered" is an ASSUMPTION, and it is wrong for a
    # whole class of machine: a distro that is registered and does not start.
    # wsl.exe fails the same way for every command in that state, so every
    # diagnosis below reads the symptom of the package/loop-device it asked
    # about and describes a fault the machine does not have (PAD-113 was told
    # its distro "answered, but could not hand out a loop device" while
    # nothing at all ran in it).  Ask the one question that separates them.
    if _wsl_distro_runs_commands() is False:
        msg, hint = _diagnose_wsl_dead_distro(err)
        return False, msg, hint
    # ...and the loop-device probe, whose failure is a property of the
    # DISTRO (WSL 1 owns no loop devices), not of a package apt can fix.
    if "losetup" in cmd:
        msg, hint = _diagnose_wsl_loop_failure(err)
        return False, msg, hint
    return False, err, ""


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


def _wsl_default_distro() -> Tuple[str, Optional[int]]:
    """``(name, version)`` of the DEFAULT distro — the one every probe runs
    in — or ``("", None)`` when it can't be read.

    ``wsl -l -v`` marks the default with ``*`` and puts the version last::

          NAME      STATE      VERSION
        * Ubuntu    Running    2

    Nothing here reads the header: it is localized, and on a non-English
    Windows the column titles are translated.  The ``*`` line is split
    from the RIGHT instead (state, then version), so a distro name with
    spaces in it — ``wsl --import`` allows them — survives intact.

    Decoding is deliberately belt-and-braces: ``WSL_UTF8=1`` asks wsl.exe
    for UTF-8, but builds older than 0.64 ignore it and emit UTF-16LE,
    which decodes to NUL-interleaved ASCII.  Stripping NULs reads both
    (the same trick install_prerequisites.ps1 uses on `wsl --help`).
    """
    try:
        result = subprocess.run(
            ["wsl", "-l", "-v"],
            capture_output=True,
            timeout=PROBE_TIMEOUT,
            env=dict(os.environ, WSL_UTF8="1"),
            creationflags=_CREATE_FLAGS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "", None
    if result.returncode != 0:
        return "", None
    out = result.stdout or ""
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    for line in out.replace("\x00", "").splitlines():
        line = line.strip()
        if not line.startswith("*"):
            continue
        parts = line[1:].strip().rsplit(None, 2)
        if len(parts) == 3 and parts[2].isdigit():
            return parts[0].strip(), int(parts[2])
        break
    return "", None


#: Where to send someone who needs a distro that works.  An LTS, and the one
#: the emulator rig is developed against, so it is a recommendation with
#: evidence behind it rather than "try something newer".  Lives here rather
#: than in the Emulate tab (which re-exports it) because the WSL diagnoses on
#: this page hand out the same name, and two spellings of "the distro we know
#: about" is how the app ends up naming different Ubuntus in one session.
KNOWN_GOOD_DISTRO = "Ubuntu-24.04"

#: The oldest Ubuntu this is known to work on, as (major, minor).
#:
#: A FLOOR, NOT A REQUIREMENT, and the difference is the whole design.  PAD
#: runs on whatever apt distro WSL calls the default: 22.04 and 24.04 both
#: work (PAD-114 fixed the four places that had one of them baked in), and
#: whatever comes next has to work on the day it ships rather than on the day
#: this app is next updated.  So nothing here fails a check on a version
#: number - a machine that can do the work is a machine that passes, which is
#: what the probes already ask.  What this floor buys is a NAMED suspicion:
#: below it the release is older than anything the app has been run against,
#: and saying so beats a user chasing a fault that is really their distro's
#: age.  Ubuntu only: Debian, Arch and the rest number their releases their
#: own way, and judging them by this would be a guess dressed as a fact.
OLDEST_TESTED_RELEASE = (22, 4)

#: wsl_release()'s cache: [(id, version, pretty), read].
_WSL_RELEASE: list = [("", "", ""), False]


def wsl_release() -> Tuple[str, str, str]:
    """``(id, version, pretty)`` of the default distro, from its own
    /etc/os-release: ``("ubuntu", "24.04", "Ubuntu 24.04.4 LTS")``.

    ``("", "", "")`` when it cannot be read, which is deliberately the same
    answer for "no WSL", "distro will not start" and "not an os-release
    distro" - every caller here treats it as "say nothing", never as "old".

    NEVER FIRST.  This is a diagnostic, and the first wsl.exe after a Windows
    reboot boots the whole VM; it is asked once, after a prerequisite run has
    already been through that door, so it never adds a cold boot of its own.
    """
    if _WSL_RELEASE[1]:
        return _WSL_RELEASE[0]
    _WSL_RELEASE[1] = True
    if sys.platform != "win32" or shutil.which("wsl") is None:
        return _WSL_RELEASE[0]
    try:
        result = _run_in_wsl("cat /etc/os-release", PROBE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return _WSL_RELEASE[0]
    if result.returncode != 0:
        return _WSL_RELEASE[0]
    fields = {}
    for line in (result.stdout or "").replace("\x00", "").splitlines():
        key, sep, val = line.strip().partition("=")
        if sep:
            fields[key] = val.strip().strip('"')
    _WSL_RELEASE[0] = (fields.get("ID", ""), fields.get("VERSION_ID", ""),
                       fields.get("PRETTY_NAME", ""))
    return _WSL_RELEASE[0]


def _release_tuple(version: str) -> Optional[Tuple[int, int]]:
    """``"24.04"`` -> ``(24, 4)``; None for anything that is not two numbers,
    because a rolling release ("", "n/a", a date) is not a version to compare
    and must not be read as a small one."""
    parts = version.split(".")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1])


def wsl_release_lines() -> List[str]:
    """What a prerequisite run says about the distro it just probed: one line
    naming it, and a second only when it is below :data:`OLDEST_TESTED_RELEASE`.

    THE FIRST LINE IS THE POINT.  Every WSL fault this project has triaged -
    PAD-73, PAD-112, PAD-113, PAD-114 - was reported with a log that said
    which STEP failed and never which Linux it failed on, so the first reply
    was always a request for `wsl -l -v`.  It is one line, it costs a command
    on a VM that is already up, and it turns that round trip into a fact the
    log already carries.
    """
    name, wsl_ver = _wsl_default_distro()
    distro_id, version, pretty = wsl_release()
    if not name and not pretty:
        return []
    said = pretty or version or "release unknown"
    where = "%s (%s%s)" % (name or "the default distro", said,
                           ", WSL %d" % wsl_ver if wsl_ver else "")
    lines = ["WSL: " + where]
    rel = _release_tuple(version)
    if distro_id == "ubuntu" and rel and rel < OLDEST_TESTED_RELEASE:
        lines.append(
            "That release is older than the %d.%02d PAD is tested against. "
            "It is not refused and it may well be fine - but if something "
            "fails here in a way that makes no sense, this is the first "
            "thing to rule out. A newer distro can sit alongside it: "
            "'wsl --install -d %s' then 'wsl --set-default %s'."
            % (OLDEST_TESTED_RELEASE[0], OLDEST_TESTED_RELEASE[1],
               KNOWN_GOOD_DISTRO, KNOWN_GOOD_DISTRO))
    return lines


#: The cheapest thing a Linux can be asked to do.  Run through the same
#: ``wsl -u root -- bash -c`` door as every probe and every pipeline command,
#: because the question is not "is the VM up" but "can WHAT WE DO run here".
WSL_CANARY = "exit 0"


def _wsl_distro_runs_commands() -> Optional[bool]:
    """Can the default distro run anything at all?  ``None`` = don't know.

    A distro that is registered but does not start fails EVERY command with
    the same wsl.exe error, so the failure of any one probe says nothing
    about the package it asked for.  This asks the question that does
    separate them, and it is only ever asked once a probe has already
    failed — a healthy machine never pays for it.

    A timeout or an OSError answers ``None``, never ``False``: a slow VM is
    not a broken one, and "your distro does not start" is far too big an
    accusation to make on a call that merely ran out of patience (the cold-VM
    boot wait above is where slowness is handled).
    """
    try:
        return _run_in_wsl(WSL_CANARY, PROBE_TIMEOUT).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return None


def _diagnose_wsl_dead_distro(err: str) -> Tuple[str, str]:
    """(message, hint) for a REGISTERED distro that runs nothing at all.

    The state PAD-113 arrived in: Ubuntu-22.04 upgraded in place to the next
    LTS, after which it stopped starting.  Everything the app knew still said
    the distro was there — ``wsl -l -q`` lists it, ``wsl -l -v`` reports
    VERSION 2 — so the probe failure was read as the fault of whatever that
    probe had asked for, and the app told him a loop device could not be
    handed out by a distro that "answered".  It had not answered; nothing had.

    Neither an apt package, nor a WSL 1 conversion, nor another
    ``wsl --install`` can touch this, so the hint carries the two things that
    can: restart the WSL service, and (when the distro's own filesystem is
    what broke) a second distro ALONGSIDE the broken one — never a repair of
    it, and never a delete, because the user's files are still in there.
    """
    name, _version = _wsl_default_distro()
    named = name or "the default distro"
    return (f"WSL is installed and {named} is registered, but nothing can "
            f"run inside it — even '{WSL_CANARY}' failed ({err}). This is "
            f"not a missing package and not a missing install: the distro "
            f"itself is not starting.",
            f"Run 'wsl --shutdown' in PowerShell, wait ten seconds, then "
            f"'wsl -d {name or '<name>'} -- echo ok'. If that still fails, "
            f"'wsl --update' (a distro upgraded in place often needs a newer "
            f"WSL). If it fails after that, the distro's own filesystem is "
            f"the problem — install a second one alongside it and make that "
            f"the default, which is the distro PAD uses. Any current Ubuntu "
            f"works; this is the one PAD is tested on:\n"
            f"wsl --install -d {KNOWN_GOOD_DISTRO}\n"
            f"wsl --set-default {KNOWN_GOOD_DISTRO}\n"
            f"The broken one is left where it is; 'wsl --export "
            f"{name or '<name>'} backup.tar' gets its files out.")


def _diagnose_wsl_loop_failure(err: str) -> Tuple[str, str]:
    """(message, hint) for a LOOP-DEVICE probe that failed inside a
    registered, answering distro.

    Every state here has WSL installed, so every one of them is a state
    where "install WSL2 + Ubuntu" is the wrong instruction — and it was
    the first line of the static hint.  A user hit exactly that: the app
    told him WSL2 was missing, the prerequisite installer told him it was
    already installed, and neither said the word that mattered (PAD-73).

    A WSL 1 distro owns no loop devices at all, so no install and no apt
    package can help — only ``wsl --set-version <name> 2``, which we can
    now name with the user's REAL distro name instead of a placeholder.
    A WSL 2 distro that still can't get a loop device is something else
    (usually a VM that wants a restart), so say the error out loud and
    keep the user away from a reinstall either way.  When the version
    can't be read, fall back to the static hint — it carries both routes.

    "Answering" is CHECKED before this is called (:func:`_probe_wsl` asks
    :func:`_wsl_distro_runs_commands` first), so the WSL 2 branch's claim
    that the distro answered is a fact rather than an assumption.  It used
    to be an assumption, and on a distro that had stopped starting it was
    the sentence that sent PAD-113 hunting a loop-device fault.
    """
    name, version = _wsl_default_distro()
    if version == 1:
        return (f"WSL is installed, but its default distro "
                f"({name or 'the default distro'}) is WSL 1, which has no "
                f"loop devices — so the card image cannot be mounted. "
                f"Installing WSL again will not change that: the distro "
                f"has to be converted.",
                f"Convert the distro to WSL 2 in PowerShell, then click "
                f"'Re-check' above the tabs:\n"
                f"wsl --set-version {name or '<name>'} 2\n"
                f"(it runs for a few minutes; close anything using WSL "
                f"first). 'Install Missing' now offers to do this for you.")
    if version == 2:
        return (f"WSL 2 is installed and {name or 'the default distro'} "
                f"answered, but it could not hand out a loop device: {err}",
                "WSL2 itself is installed — do not install it again. Run "
                "'wsl --shutdown' in PowerShell, wait ten seconds, then "
                "click 'Re-check' above the tabs. If it still fails, send "
                "the log: this is not a missing install.")
    return err, ""


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
