"""Emulate tab — run the Stern Spike 2 game on this PC and watch its health.

The emulator is a rig of shell scripts, an ``LD_PRELOAD`` hardware shim and a
native GL host, in ``tools/spike2_emu``.  It SHIPS WITH THE APP (this used to
say it lived outside the repo, in ``c:\\tmp\\spike2_emu``, which stopped being
true twice over).  ``PAD_EMU_DIR`` moves it.  This panel is a *control surface*
for that rig: start it, stop it, and say truthfully what it is doing.  It
deliberately does not reimplement any of it.

WHERE IT RUNS.  The rig is a Linux program: the chroot, qemu-user, the node bus
and the GL host have nothing Windows-specific in them.  On a Linux desktop it is
simply run; from Windows it is reached through WSL, and everything that looks
Windows-flavoured in it - the playfield window as a Windows process, the audio
bridge - is a WORKAROUND for what WSL lacks, not a design choice.  ``rig_cmd()``
is the one place that knows which of the two applies.

Three things about it are worth knowing before changing anything here:

* **It runs a card image, and only a card image.**  The image is mounted READ
  ONLY and run in place: nothing is extracted, and nothing can write to it.  The
  user picks the file; whether that is a stock card or their own build is their
  business, and this tab does not guess.

  Two other sources were offered briefly and both were wrong.  An "extracted
  folder" cannot work: PAD extracts ASSETS, and the rig needs a title directory
  (a ``game`` binary with ``assets/`` and the node ``.hex`` files beside it),
  which is a different shape — pointing it at an extract folder could only fail.
  A "rig's own copy" option exposed whatever happened to be unpacked inside the
  rig on this machine, which is internal state no user can create or reason
  about.

* **The LAUNCH is root on Windows now, and that is item 13's doing.**  This
  module's original rule was "normal WSL user, never root - root breaks WSLg
  and the audio path", and that stopped being true when ``watch.sh`` learned
  the drop dance: a ``PAD_PIVOT=1`` root launch boots the GUEST as root (the
  only shape criu can checkpoint, so the only shape the playfield's
  Save/Load state buttons work in) and drops every helper back to the desktop
  user, whose WSLg and audio session they need.  ``watch_cmd()`` owns the
  launch, ``kill_cmd()`` the teardown (a root guest needs a root kill), and
  ``wsl_home()`` the one fact both need beyond ``rig_cmd()``.  Helpers,
  status polls and everything else still run as the normal user, which is
  still why this module calls ``wsl.exe`` directly instead of reusing the
  executor.

* **Stopping must be verified, never assumed.**  An orphaned guest spins at
  ~140% CPU forever and ignores polite signals, so Stop runs the rig's own
  ``killgame.sh`` (SIGKILL for all five processes) and then re-reads the status
  until it reports zero.  The panel shows the process count for exactly this
  reason.
"""

import json
import ntpath
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from ..core import config
from . import _rig
from .widgets import _Tooltip

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

#: The rig ships in the repo, next to this package, rather than in the temp
#: directory it was developed in - so it survives a reboot and there is exactly
#: one copy of it.  Resolved from this file so a checkout anywhere works.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "spike2_emu"
)

#: Item 56: master PC-side volume + Mute for the emulator's OWN sound - "our
#: level, not the game's" (David).  One small JSON plays two roles at once,
#: deliberately: it is BOTH the remembered setting (read once, at panel
#: construction, so the slider already shows what a fresh run will play) AND
#: the LIVE control channel a running padplay.py polls every ~250 ms (see its
#: poll_gain()) - so dragging the slider or hitting Mute reaches the speakers
#: with no restart, which is the whole of what this item asked for beyond a
#: plain preference. One shared file alongside settings.json, same idiom as
#: AUDIO_NAMES_FILE / CARD_EDITS_FILE / LIBRARY_FILE.
#: Shape: {"gain": 0.0-1.0, "muted": bool}.
AUDIO_CTL_FILE = os.path.join(os.path.dirname(config.SETTINGS_FILE),
                              "audio_ctl.json")


def _load_audio_ctl():
    """The remembered volume/mute, defaulting to unity/unmuted — today's
    behaviour, unchanged, for a machine that has never touched the knob."""
    try:
        with open(AUDIO_CTL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        gain = float(data.get("gain", 1.0))
        muted = bool(data.get("muted", False))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 1.0, False
    return max(0.0, min(1.0, gain)), muted


def _write_audio_ctl(gain, muted):
    """Persist AND live-publish.  Atomic (temp + ``os.replace``) so padplay.py's
    poll never catches a half-written file — the file is small and this is
    called on every slider tick, but a torn read would only ever cost one
    250 ms poll's worth of stale gain, never a corrupt one."""
    try:
        os.makedirs(os.path.dirname(AUDIO_CTL_FILE), exist_ok=True)
        tmp = AUDIO_CTL_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"gain": gain, "muted": muted}, f)
        os.replace(tmp, AUDIO_CTL_FILE)
    except OSError:
        pass

#: How the rig's ``state=`` word is shown to a human.  ``techalerts`` is not a
#: fault: the game boots to its Tech Alerts screen and waits there for an
#: operator, exactly as the real machine does.  Reading that as "stuck" cost a
#: whole pass of this project, so the wording here is deliberate.
_STATE_TEXT = {
    "off": ("Not running", ""),
    "booting": ("Starting…", "Loading scenes and bringing up the node bus."),
    "techalerts": ("Waiting at Tech Alerts",
                   "Press a switch in the game window to carry on — this is "
                   "what the real machine does, not a fault."),
    "attract": ("In attract mode", "Playing its attract loop, or in the "
                                   "operator menu."),
    # Kept: what status.sh emitted before it learned to say `attract`, so an
    # older rig against a newer app still reads as something rather than as a
    # bare word.  The rename happened because the old word was reached by a
    # test that had quietly stopped working - see gamestate.sh.
    "running": ("Running", "Attract mode or the operator menu."),
}

#: Replaces the Tech Alerts hint while the rig's own auto-advance helper is
#: still working.  The default hint tells the user to press something; saying
#: that while something else is already pressing invites two operators fighting
#: over the same screen.
_ADVANCING_HINT = ("Skipping to attract mode on its own — it waits for the "
                   "node bus to finish bringing up, then presses Service Back "
                   "once. Untick “Skip to attract mode” to do it by hand.")

#: Shown when the auto-advance helper ran out of presses and stopped.  It names
#: the service menu because that is the failure this cannot see: the menu opens
#: no video clip, so from the outside it reads exactly like Tech Alerts.
_GAVEUP_HINT = ("Auto-advance pressed Service Back several times and the "
                "screen did not change. If an earlier press DID take, the game "
                "is probably on the SERVICE MENU, which looks the same from "
                "out here. Click the game window and press Esc: from the menu "
                "it leaves toward attract, from Tech Alerts it clears them.")

#: The token killgame.sh prints (WSL only) when leftovers survived everything
#: it can do from inside the VM - the measured case is a dead guest held as a
#: zombie by a WSL interop relay, which ignores SIGKILL from inside.  Stop
#: watches for it and offers the Windows-side cure, because without that the
#: wedge is a locked room: the leftovers keep ``procs`` nonzero, which keeps
#: the button on Stop (which kills nothing) and greys out "Restart WSL…"
#: (which reads nonzero procs as a live run it must not interrupt).  A user
#: met exactly that on 2026-08-09, with the answer sitting in the log pane.
_NEEDS_WSL_RESTART = "PAD_STOP_NEEDS_WSL_RESTART"

#: The token watch.sh prints when it cannot open the virtual playfield window
#: itself, with everything needed to open it from here.
#:
#: THE MACHINE THAT NEEDS IT.  The playfield is a WINDOWS process — this WSL
#: has no Tk of any kind — so watch.sh launches it through interop, and a user
#: reported on 2026-08-11 that his never appeared.  His ``/etc/wsl.conf`` has
#: ``[interop] enabled=false``, so his Linux cannot execute a Windows binary
#: at all: the window could not open itself, and the rig's only answer was to
#: print a command for him to type before every run.
#:
#: AND THE ASYMMETRY THAT FIXES IT.  Interop is LINUX → WINDOWS.  Windows →
#: Linux (``wsl.exe``) is untouched by that switch, so everything the window
#: does once it is up — reading ``dump/padled``, running ``swpoke.py``, asking
#: ``wslpath`` — keeps working.  Only the LAUNCH cannot cross.  PAD is already
#: standing on the far side: it is a Windows process running a Python with
#: tkinter (it is drawing its own window with it), so it opens the playfield
#: and watch.sh gets on with the run.
_PLAYFIELD_LAUNCH = "PAD_PLAYFIELD_WINDOWS_LAUNCH"


def playfield_launch(line):
    """Parse a ``_PLAYFIELD_LAUNCH`` line into its fields, or None.

    ``key=value`` pairs, split on the KEYS rather than on whitespace: two of
    the values are paths (``\\\\wsl.localhost\\…``), and a path is entitled to
    contain a space even though this rig's own never has.

    Pure, and separate from the launching, so the format can be tested without
    a WSL, a Tk root or a game.
    """
    if not line or _PLAYFIELD_LAUNCH not in line:
        return None
    rest = line.split(_PLAYFIELD_LAUNCH, 1)[1].strip()
    out = {}
    for part in re.split(r"\s+(?=[a-z_]+=)", rest):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out if out.get("game") else None


def windows_python():
    """The interpreter to run ``playfield.py`` with, on Windows.

    ``sys.executable`` IS THE ANSWER AND IS ALSO A TRAP, so it is not used
    bare.  The Windows app runs on the Python bundled beside it
    (``{app}\\python\\pythonw.exe`` — launcher.vbs starts it that way), and
    that interpreter has tkinter and Pillow, which is exactly what the
    playfield needs.  But in a FROZEN build ``sys.executable`` is the app's own
    .exe, and handing it a script path would start a second copy of PAD.

    So: prefer the windowed twin of whatever is running us (no console window
    beside the playfield), accept the running interpreter itself, and only
    then look for a Python on PATH.  None when there is nothing to run it
    with, and the caller says so rather than launching something wrong.
    """
    # ntpath, NOT os.path, for the path arithmetic: this function reasons
    # about WINDOWS paths by contract (its one caller returns early off
    # Windows), and os.path is posixpath on the Linux and macOS CI runners,
    # where dirname(r"C:\Py\python.exe") is "" because a backslash is not a
    # separator there.  On Windows ntpath IS os.path, so this changes nothing
    # where the code runs and unbreaks the test everywhere it is tested.
    cands = []
    exe = sys.executable or ""
    if exe and not getattr(sys, "frozen", False):
        base = ntpath.dirname(exe)
        cands += [ntpath.join(base, "pythonw.exe"), exe]
    elif exe:
        # Frozen: the bundled interpreter sits in `python\` beside the app.
        cands.append(ntpath.join(ntpath.dirname(exe), "python",
                                 "pythonw.exe"))
    for name in ("pythonw.exe", "python.exe"):
        found = shutil.which(name)
        if found:
            cands.append(found)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def rig_dir():
    """Where the emulator rig lives.  Overridable so this is not welded to one
    machine's scratch directory."""
    return os.environ.get("PAD_EMU_DIR", DEFAULT_RIG_DIR)


def rig_available():
    """Whether the rig is present.  The tab stays visible when it is not and
    explains what is missing, rather than disappearing without a word."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, f))
               for f in ("watch.sh", "killgame.sh", "status.sh"))


#: Where Docker Desktop comes from when there is no Homebrew to ask.
DOCKER_URL = "https://www.docker.com/products/docker-desktop/"

#: How long to give the Docker CLI.  ``docker info`` with no daemon behind it
#: answers in about a second; the timeout is only so a wedged socket cannot
#: hang a background probe forever.
_DOCKER_PROBE_S = 12

#: Where a `docker` command lives on a Mac when this app's own PATH cannot see
#: it.  A GUI app launched from Finder inherits launchd's PATH -
#: /usr/bin:/bin:/usr/sbin:/sbin - and NOT ONE of these is on it, so a bare
#: ``["docker", "info"]`` is a PATH lookup that fails on machines where docker
#: is installed and working.  The same fact is already encoded elsewhere in
#: this codebase (MacExecutor._EXTRA_PATH, homebrew() below, the gpg candidate
#: list in plugins/bof/pipeline.py); the Docker probe was the one place that
#: still assumed a login shell's PATH.
DOCKER_DIRS = (
    "/usr/local/bin",                                  # Docker Desktop's own
                                                       # symlink; Intel Homebrew
    "/opt/homebrew/bin",                               # Apple Silicon Homebrew
    "/opt/local/bin",                                  # MacPorts
    "~/.docker/bin",                                   # Docker Desktop when it
                                                       # is told to keep out of
                                                       # /usr/local/bin
    "~/.rd/bin",                                       # Rancher Desktop
    "~/.orbstack/bin",                                 # OrbStack
    "/Applications/Docker.app/Contents/Resources/bin",  # Desktop's own copy,
                                                        # there even when the
                                                        # symlink was declined
)

#: The Mac apps that ship a Linux VM for the `docker` command to talk to.
#: Directories, not files: these are .app bundles.
DOCKER_ENGINE_APPS = (
    ("Docker Desktop", "/Applications/Docker.app"),
    ("OrbStack", "/Applications/OrbStack.app"),
    ("Rancher Desktop", "/Applications/Rancher Desktop.app"),
)


def which_tool(name, dirs=DOCKER_DIRS):
    """*name* as an absolute path, looking where a Mac actually keeps it.

    PATH FIRST, ALWAYS: someone who launched the app from a terminal, or who
    set PATH deliberately, has already answered this question and their answer
    wins.  ``dirs`` is only consulted when the inherited PATH has no answer at
    all, which for a Finder-launched .app is the normal case rather than the
    exception.

    ``isfile`` and not ``os.access(X_OK)``, matching :func:`homebrew` and the
    rest of this codebase's tool lookups: a file sitting in one of these
    directories under this name is the tool, and a permission problem is
    better reported by running it than by pretending it is not installed.
    """
    found = shutil.which(name)
    if found:
        return found
    for d in dirs:
        p = os.path.join(os.path.expanduser(d), name)
        if os.path.isfile(p):
            return p
    return None


def docker_cli():
    """The `docker` command on this machine, or None.

    ``PAD_DOCKER`` overrides, for the Mac that keeps it somewhere none of
    :data:`DOCKER_DIRS` names - and a wrong override answers None rather than
    silently falling back, because a support instruction that is quietly
    ignored is worse than one that fails.
    """
    override = (os.environ.get("PAD_DOCKER") or "").strip()
    if override:
        return override if os.path.isfile(override) else None
    return which_tool("docker")


def docker_engine():
    """What on THIS Mac can provide the daemon, as ``(label, kind, path)``,
    or None.

    macOS cannot run a Linux container itself.  ``docker`` is a client; the
    daemon lives in a Linux VM, and something has to ship that VM - Docker
    Desktop does, and so do OrbStack, Rancher Desktop and Colima.  A client
    with no engine behind it is therefore NOT "Docker is stopped", and it is
    the case a Mac reaches by installing a package manager's `docker`: MacPorts
    says of its own port that it "contains command line utilities for
    interacting with Docker, but not the core daemon".

    ``kind`` is how it starts: ``"app"`` is ``open -a``, ``"cli"`` is a command
    that has to be run and watched.
    """
    for label, app in DOCKER_ENGINE_APPS:
        if os.path.isdir(app):
            return (label, "app", app)
    colima = which_tool("colima")
    if colima:
        return ("Colima", "cli", colima)
    return None


def docker_state():
    """``ok`` / ``stopped`` / ``engineless`` / ``absent`` - macOS's answer to
    "can we emulate?".

    THE EMULATOR NEEDS LINUX, and macOS reaches it through a container (see
    ``rig_cmd``), so Docker is as much a prerequisite there as WSL is on
    Windows.  It was not treated like one: nothing on this tab checked for it,
    the manufacturer's prerequisite list does not carry it, and the only place
    it was ever named was the "rig not found" hint - which a Mac user never
    sees, because the rig SHIPS WITH THE APP and is therefore always found.  So
    the whole of "you need Docker" arrived as one line of padbox.sh's stderr,
    part way down the log pane, after Start appeared to work.

    Four answers rather than two, because the remedies are four different
    things: nothing installed is a download, installed-but-down is one click,
    and a CLIENT WITH NO ENGINE - the answer this app used to be unable to give
    - is a second install that is not Docker Desktop at all.  A Mac in that
    state was told "Docker Desktop is required" while `docker` sat on its disk,
    and clicking Start Docker on it opens an app that is not there.

    ``engineless`` is macOS-only by construction: everywhere else the daemon is
    local and "installed but not running" is the whole of the question.
    """
    cli = docker_cli()
    if not cli:
        return "absent"
    try:
        out = subprocess.run([cli, "info"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             timeout=_DOCKER_PROBE_S,
                             creationflags=_CREATE_FLAGS)
        if out.returncode == 0:
            return "ok"
    except FileNotFoundError:
        return "absent"
    except Exception:                                   # noqa: BLE001
        # A timeout is Docker Desktop still waking up, not an absent one - and
        # something has to be there to be slow, so it is not engineless either.
        return "stopped"
    if sys.platform != "darwin":
        return "stopped"
    return "stopped" if docker_engine() else "engineless"


def homebrew():
    """The `brew` binary, or None.  Homebrew installs itself in two places and
    is famously not on a GUI app's inherited PATH, so both are named."""
    for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.isfile(p):
            return p
    return None


def engine_setup_plan(cli=None):
    """What “Set up emulator…” will DO on this Mac, or None when it cannot.

    NOBODY IS SENT TO A TERMINAL.  The Windows half of this tab installs what
    the emulator needs at the press of a button, and a Mac that was handed a
    command to type instead was being asked to do the app's job - David,
    2026-08-19, on the first version of this fix.  So this returns the work
    itself, not advice: argv to run, and the sentences that describe it.

    Like :func:`setup_fix_steps`, the consent list and the work are ONE object,
    so what the dialog promises and what the button runs cannot drift apart.

    CHOSEN BY WHERE THE CLIENT CAME FROM, because that is the package manager
    already working on this Mac: a `docker` in /opt/local/bin came from
    MacPorts, whose own docker port points at colima for exactly this ("this
    port contains command line utilities for interacting with Docker, but not
    the core daemon"), and driving Homebrew on that machine would be a second
    package manager for a problem the first one already solves.

    Colima rather than Docker Desktop, and not as a preference: it installs
    without a browser, without a drag-to-Applications, and it still works on
    the macOS versions Docker Desktop has stopped supporting - which is the
    machine that reported this.  Docker Desktop stays one click away for
    anyone who wants the GUI (see ``_docker_download``).

    ``cli`` is the client this Mac already has; without one the plan installs
    that too, because colima ships the Linux machine and not the `docker`
    command.
    """
    port = which_tool("port", ("/opt/local/bin",))
    brew = homebrew()
    if cli and cli.startswith("/opt/local/") and port:
        mgr, tool, admin = "MacPorts", port, True
    elif brew:
        mgr, tool, admin = "Homebrew", brew, False
    elif port:
        mgr, tool, admin = "MacPorts", port, True
    else:
        return None
    packages = ["colima"] if cli else ["docker", "colima"]
    # THE PACKAGE NAMES ARE ARGV, NOT PROSE.  "install docker colima" is what
    # the machine needs; a person reads "the docker command" and "Colima", and
    # this is the one place the two spellings are tied to each other.
    label = " and ".join({"docker": "the docker command",
                          "colima": "Colima"}.get(p, p) for p in packages)
    # -N for MacPorts: no question this app cannot see gets asked half way
    # through an install it is driving.  Homebrew is NEVER run as root - it
    # refuses outright - which is also why `admin` is per-plan and not a
    # constant.
    install = ([tool, "-N", "install"] + packages if admin
               else [tool, "install"] + packages)
    steps = ["Install %s with %s. Nothing already on this Mac is changed or "
             "removed." % (label, mgr),
             "Start Colima, the Linux machine the docker command talks to. It "
             "runs in the background and takes a couple of minutes the first "
             "time, while it downloads its disk image."]
    if admin:
        steps.append("macOS will ask for your password once, in its own "
                     "dialog, because %s installs system-wide." % mgr)
    return {"manager": mgr, "packages": packages, "label": label,
            "admin": admin, "install": install, "steps": steps}


def parse_status(text):
    """Parse ``status.sh``'s ``key=value`` output into a dict.

    Split out of the panel so it can be tested without a Tk root — the state
    wording is the part most likely to be got wrong, and it is the part a user
    reads first.  The parsing itself now lives in :mod:`.._rig`, shared with
    the JJP panel; both rigs speak key=value for the same reason.
    """
    return _rig.parse_status(text)


def state_text(info):
    """(label, hint) for the rig's ``state=`` word.

    ``auto=`` is the number of auto-advance helpers still running, so a
    non-zero value at Tech Alerts means the rig is already dealing with it and
    the user should be told to wait rather than to press something.

    ``auto_result=gaveup`` is the case this used to hide.  The helper presses a
    fixed number of times and then exits either way; with only ``auto=`` to go
    on, "finished the job" and "gave up" both showed as the same unchanging
    "Waiting at Tech Alerts", and the two want opposite things from the human.
    """
    label, hint = _STATE_TEXT.get(info.get("state", "off"),
                                  (info.get("state", ""), ""))
    if info.get("state") == "techalerts":
        if info.get("auto", "0") != "0":
            return label, _ADVANCING_HINT
        if info.get("auto_result") == "gaveup":
            return "Stuck at Tech Alerts", _GAVEUP_HINT
    return label, hint


def _wsl_path(win_path):
    """``c:\\repo\\tools\\spike2_emu`` -> ``/mnt/c/repo/tools/spike2_emu``.

    Delegates to :func:`.._rig.wsl_path`, which the JJP panel uses too.  Kept
    as a name here because three test files and several call sites import it,
    but there is now exactly ONE definition of how a Windows path is spelled
    for WSL - two panels each with their own copy is how ``alive.sh`` and
    ``killgame.sh`` came to disagree about what a running rig is.
    """
    return _rig.wsl_path(win_path)


def rig_cmd(script, *args, env=()):
    """The command that runs one of the rig's scripts, on THIS platform.

    ONE PLACE THAT KNOWS, because there are six call sites and they were six
    copies of ``["wsl.exe", "-e", "bash", ...]``.  The rig is a Linux program,
    and the three platforms differ only in how Linux is reached:

    ============  ======================================================
    Linux         run it.  Nothing in between.
    Windows       through WSL, which is Linux.
    macOS         in a container, because ``qemu-user`` translates LINUX
                  syscalls and the chroot needs Linux namespaces - so
                  this is not a port that could be written, it is Linux
                  that has to be running somewhere.  ``docker/padbox.sh``
                  owns every detail of that and this only calls it.
    ============  ======================================================

    `env` is a list of ``NAME=value`` strings, applied with ``env`` so the
    values survive the hop without a shell re-parsing them - `wsl.exe` re-parses
    its arguments, and `$var` expands to nothing on that second pass.
    """
    if sys.platform == "darwin":
        # padbox.sh forwards the interesting variables into the container
        # itself, so they are set for IT rather than wrapped around it: `docker
        # run` takes its environment through -e, and an `env` prefix out here
        # would set them on the docker client and nowhere useful.
        box = os.path.join(rig_dir(), "docker", "padbox.sh")
        return ["/usr/bin/env"] + list(env) + ["bash", box, script] + \
               [str(a) for a in args]
    if sys.platform == "win32":
        head = ["wsl.exe", "-e"]
        path = "%s/%s" % (_wsl_path(rig_dir()), script)
    else:
        head = []
        path = os.path.join(rig_dir(), script)
    if env:
        head = head + ["env"] + list(env)
    return head + ["bash", path] + [str(a) for a in args]


def rig_cmd_root(script, *args):
    """The same script, as root.  WINDOWS ONLY, and that is not a limitation
    that was settled for - it is the only platform where it is honest.

    ``wsl -u root`` is uid 0 with NO PASSWORD, because the Windows side is what
    launches the distro; ``install_prerequisites.ps1`` has installed the WSL
    packages that way for several releases.  On a Linux desktop the equivalent
    is sudo, which wants a password that a GUI app has nowhere to ask for
    without becoming an invisible hang - so there the rig keeps printing the
    command instead, which is what ``ensurebuild.sh`` has always done.

    NOT ``rig_cmd(..., env=...)`` with a root flag bolted on: the normal path
    deliberately runs as the ordinary user (WSLg and the audio session belong
    to them), and the two must not be one call that a wrong argument could
    flip.
    """
    if sys.platform != "win32":
        raise RuntimeError("rig_cmd_root is WSL-only")
    return ["wsl.exe", "-u", "root", "-e", "bash",
            "%s/%s" % (_wsl_path(rig_dir()), script)] + [str(a) for a in args]


#: wsl_home()'s cache: [value, probed].  One probe per app run is plenty - the
#: answer changes when the user reinstalls their distro, not between clicks.
_WSL_HOME = [None, False]


def wsl_home():
    """The default WSL user's home ('/home/david'), asked of WSL itself.

    The checkpointable launch below runs ``wsl -u root``, whose own HOME is
    /root - the wrong rootfs, the wrong logs, the wrong everything - so the
    desktop user's home is passed in explicitly, and this is where it comes
    from.  NO shell variables anywhere in the probe: ``wsl.exe`` re-parses its
    argument line and ``$HOME`` expands to empty on that second pass (the JJP
    executor learned that the hard way), so it is ``whoami`` + ``getent``,
    which carry no ``$`` at all.  None when anything fails, and the callers
    fall back to the ordinary user launch.

    NEVER ON THE UI THREAD.  The first wsl.exe after a Windows reboot boots
    the whole WSL VM, so this probe's real worst case is not its 30 s
    timeouts, it is that boot - call it (and watch_cmd/kill_cmd, which call
    it) from a worker.  shutdown_sync is the one deliberate exception: app
    quit blocks by design, and it only runs while a run is up - so WSL is
    warm and the probe answers fast even when it is not already cached.
    """
    if _WSL_HOME[1]:
        return _WSL_HOME[0]
    _WSL_HOME[1] = True
    try:
        u = subprocess.run(["wsl.exe", "-e", "whoami"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=30, creationflags=_CREATE_FLAGS)
        user = u.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
        if user and user != "root":
            p = subprocess.run(["wsl.exe", "-e", "getent", "passwd", user],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,
                               timeout=30, creationflags=_CREATE_FLAGS)
            row = p.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
            parts = row.split(":")
            if len(parts) >= 6 and parts[5].startswith("/"):
                _WSL_HOME[0] = parts[5]
    except Exception:                                   # noqa: BLE001
        _WSL_HOME[0] = None
    return _WSL_HOME[0]


def watch_cmd(minutes, env, savestates=True):
    """The Start Emulator launch - and on Windows, when save states are
    enabled, it is the CHECKPOINTABLE one (item 13): ``wsl -u root`` with
    ``PAD_PIVOT=1`` and the desktop user's HOME.

    ``savestates=False`` is the tab's opt-out (the default in the UI): the
    plain user launch, the shape this tab always had before item 13.  It
    cannot be checkpointed, and watch.sh therefore starts the playfield
    without its Save/Load state controls - a run with no save states shows
    no buttons that could only ever refuse.

    This module's old rule was "never root - it breaks WSLg and audio", and
    that stopped being true when watch.sh learned the drop dance: a root
    launch boots the GUEST as root (which is what lets criu checkpoint it -
    an unprivileged userns forces setgroups off and restore dies there) and
    drops every helper back to the desktop user, whose WSLg and audio
    session they need.  Verified live across save -> load -> repeat load.
    Without the pivot boot, the playfield's Save state button can only ever
    answer "this run is not checkpointable", which is exactly what David's
    first real press got.

    Falls back to the ordinary user launch when the home probe fails, so a
    broken probe degrades to what this tab always did - no save states,
    everything else identical - rather than to a root run pointed at
    /root/spike2root.
    """
    if savestates and sys.platform == "win32":
        home = wsl_home()
        if home:
            return (["wsl.exe", "-u", "root", "-e", "env",
                     "HOME=" + home, "PAD_PIVOT=1"] + list(env)
                    + ["bash", "%s/watch.sh" % _wsl_path(rig_dir()),
                       str(minutes)])
    return rig_cmd("watch.sh", minutes, env=env)


def kill_cmd():
    """killgame.sh, as ROOT on Windows, because the guest may be root's.

    A PAD_PIVOT guest is a root process; the ordinary user's pkill reports
    success and kills nothing (the same lie the restored-guest teardown told
    once already), while root's kill reaches both kinds.  The desktop HOME
    rides along so padpath resolves the right rootfs.  Everywhere else, and
    when the home probe fails, the ordinary call - which is right for the
    runs it can see.
    """
    if sys.platform == "win32":
        home = wsl_home()
        if home:
            return ["wsl.exe", "-u", "root", "-e", "env", "HOME=" + home,
                    "bash", "%s/killgame.sh" % _wsl_path(rig_dir())]
    return rig_cmd("killgame.sh")


def load_cmd(slot):
    """loadgame.sh as ROOT with the desktop HOME — the same shape as
    kill_cmd, for the same reasons: a save-state load is a criu restore of
    a root guest, and padpath must resolve the desktop user's rootfs.
    PAD_RESTORE_KILL clears whatever guest is running (the restored one
    takes its place)."""
    if sys.platform == "win32":
        home = wsl_home()
        if home:
            return ["wsl.exe", "-u", "root", "-e", "env", "HOME=" + home,
                    "PAD_RESTORE_KILL=1", "bash",
                    "%s/loadgame.sh" % _wsl_path(rig_dir()), str(slot)]
    return rig_cmd("loadgame.sh", slot, env=("PAD_RESTORE_KILL=1",))


#: What the emulator needs BEYOND the rig itself, in the order a run meets
#: them: probe key (from setupcheck.sh) -> package, and what it is for.
#:
#: The tool is what is probed, because that is the fact; the package name is
#: only how Debian spells it.  Same six as the Stern section of
#: install_prerequisites.ps1 - that installer is where a user who never opens
#: this tab still gets them.
#:
#: THE NATIVE COMPILER WAS MISSING FROM THIS LIST FOR FIVE RELEASES, and a
#: machine can pass every other line here without it: the rig builds TWO
#: things, the hardware shim (ARM, cross compiled) and the renderer (native),
#: and only the cross compiler was ever asked about.  A user on 2026-08-08 had
#: the ARM one, watched the shim build, and then met
#:
#:     [build] the GL renderer is not built, and there is no gcc here
#:
#: half a minute into a run that this tab had said nothing about.  It is two
#: apt names for one capability because gcc only RECOMMENDS its headers.
#:
#: AND THEN THE DECODER, which is the same omission with a worse symptom.  Every
#: other line here builds or mounts something, so missing one ENDS the run and
#: says why; missing ffmpeg lets the run succeed completely - guest up, window
#: open, renderer at 59 fps - and simply shows black, because the picture and
#: the sound are both decoded by it out here (the game's gstreamer-0.10 has no
#: software H.264 element).  A user on 2026-08-08 sat in front of that window
#: with a log repeating `No such file or directory: 'ffmpeg'` a hundred times a
#: second while this tab said nothing and the prerequisite strip said OK - that
#: strip's ffmpeg is the WINDOWS one, which the app bundles, and this is Linux's.
_SETUP_TOOLS = (
    ("qemu", "qemu-user-static",
     "runs the machine's own 32-bit ARM game binary"),
    ("armgcc", "gcc-arm-linux-gnueabihf",
     "builds the hardware shim the game runs against"),
    ("nativecc", "gcc libc6-dev",
     "builds the renderer that draws the game's picture on this PC"),
    ("debugfs", "e2fsprogs",
     "builds the guest filesystem out of a card image, without root"),
    ("fuse", "fuse3",
     "mounts a card read only, so a title runs without extracting 6 GB"),
    ("ffmpeg", "ffmpeg",
     "decodes the game's video and sound, which it cannot decode itself"),
)

#: WHAT A FEATURE NEEDS, WHICH IS NOT WHAT THE EMULATOR NEEDS.  Same shape as
#: _SETUP_TOOLS and probed by the same setupcheck.sh loop, but kept apart
#: because missing one of these does not stop a run - and a notice that says
#: "this PC cannot run the emulator" over a machine that runs it perfectly is
#: the same wrong-accusation fault this file guards against everywhere else.
#:
#: THE FAULT THAT PUT IT HERE.  v0.126.0 made every Start a checkpointable
#: (PAD_PIVOT) boot so the save-state controls could simply be on.  That boot
#: needs a native static busybox, no machine has one by default, it was on no
#: prerequisite list at all - and run_game.sh's answer to a pivot it cannot do
#: was to stop.  So the release that added save states took the WHOLE emulator
#: away from anyone without busybox-static, which is how a user reported it on
#: 2026-08-11: two titles that had run before, no window, and
#:
#:     [run] PAD_PIVOT needs a STATIC busybox at /bin/busybox
#:     [watch] the game never started.
#:
#: watch.sh now withdraws the request and runs the ordinary boot instead, so
#: the cost is the feature.  This list is how the user gets told that BEFORE
#: the save slots turn out to do nothing, and how “Set up emulator…” is given
#: something to install.
#: THE FOURTH FIELD IS HOW IT IS GOT, and it exists because the second of
#: these cannot be got the way the first is.  ``apt`` means what it says;
#: ``build`` means no Ubuntu publishes the thing at all and getcriu.sh
#: compiles it from source.  Without the distinction the consent dialog says
#: "Install in WSL: criu", which is a promise apt cannot keep: ``apt-cache
#: policy criu`` on 24.04 prints an EMPTY version table, and naming it on an
#: install line would fail the packages beside it too.
#:
#: THE FAULT THAT PUT CRIU HERE is the busybox one, one layer down. PAD-53
#: made a missing busybox-static cost only the feature - but a machine that
#: then installed busybox-static STILL had no save states, because criu was a
#: hard-coded ``/var/tmp/criubuild/criu/criu/criu`` in eight rig scripts: one
#: developer's hand-built binary, on one machine. Everyone else got the
#: checkpointable boot, the Save and Load buttons, and a failure naming a
#: directory they had never heard of. Both halves are probed now, and both
#: are obtainable.
_SETUP_OPTIONAL = (
    ("busybox", "busybox-static",
     "save states: the guest is booted in the one shape that can be frozen "
     "and reloaded, and that shape needs a static busybox", "apt"),
    ("criu", "criu",
     "save states: this is the program that freezes the running game and "
     "thaws it again, and no Ubuntu publishes it — PAD builds it", "build"),
)

#: How long to give the setup probe.  It is five `command -v`s, one small
#: compile and a read of /proc, so it answers in well under a second on a warm
#: WSL - the timeout is entirely for a COLD one, where `wsl.exe` has to boot
#: the distro first.
_SETUP_PROBE_S = 90

#: How many drain passes (250 ms each) the setup probe gets before the tab
#: says WSL itself is booting.  A warm WSL answers inside one pass, so the
#: message never flashes on an ordinary start; a cold one - the first wsl.exe
#: after a Windows reboot boots the whole VM - takes tens of seconds, and a
#: tab that says nothing for that long reads as a broken app.  David read it
#: exactly that way on 2026-08-09.
_WSL_BOOT_TICKS = 4

#: What the tab says while that boot runs.  It names the wait AND its bound,
#: because "Starting WSL…" alone invites force-quitting at the 30 s mark.
_WSL_BOOT_TEXT = ("Starting WSL — the first start after a Windows reboot can "
                  "take a minute. The app stays usable, and this finishes on "
                  "its own.")


def setup_state():
    """What this machine still needs before it can emulate, as setupcheck.sh's
    facts - or None when the question could not be asked at all.

    None IS NOT "everything is fine", and no caller may read it that way: a
    machine with no WSL installed answers that way too, and so does one where
    the probe timed out.  Claiming a fault on no evidence is how a prerequisite
    notice ends up in front of someone whose machine is perfect.

    macOS is excluded because it emulates in a container that already carries
    every one of these (docker/Dockerfile installs them at build time); there
    the prerequisite is Docker itself, which ``docker_state`` owns.
    """
    if sys.platform == "darwin" or not rig_available():
        return None
    try:
        out = subprocess.run(rig_cmd("setupcheck.sh"), stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL,
                             timeout=_SETUP_PROBE_S,
                             creationflags=_CREATE_FLAGS)
    except Exception:                                       # noqa: BLE001
        return None                 # no WSL, no bash, or it never came back
    if out.returncode != 0:
        return None
    # parse_status, not a second parser: setupcheck.sh emits the same key=value
    # shape as status.sh, and that function already survives the warnings
    # wsl.exe is entitled to prepend to stdout.
    facts = parse_status(out.stdout.decode("utf-8", "replace"))
    return facts or None


def setup_summary(facts):
    """``(missing, binfmt)`` - the two things the notice is built from.

    Pure, so the wording tests do not need a WSL or a Tk root.
    """
    if not facts:
        return [], "1"
    missing = [(pkg, why) for key, pkg, why in _SETUP_TOOLS
               if facts.get(key) == "0"]
    return missing, facts.get("binfmt", "1")


def setup_extras(facts):
    """The missing packages that cost a FEATURE rather than the emulator.

    Absent facts accuse nobody, the same as everywhere else here: an older rig
    emits no ``busybox`` line, and silence is not a missing package.

    ASKED ONLY WHERE THE FEATURE IS.  ``watch_cmd`` requests the checkpointable
    boot on Windows and nowhere else, so a Linux desktop's Start never wants a
    static busybox at all - and a notice about a package that machine's runs
    would never use is the same wrong accusation as any other.  Decided from
    the rig's own ``iswsl`` fact rather than from sys.platform, so the answer
    is about the machine the run happens on.
    """
    if not facts or facts.get("iswsl") == "0":
        return []
    return [(pkg, why) for key, pkg, why, _how in _SETUP_OPTIONAL
            if facts.get(key) == "0"]


def setup_built(facts):
    """Of those, the ones apt cannot supply at all — PAD compiles them.

    Split out because the two are different acts and the consent dialog has to
    say which is which: ``apt-get install busybox-static`` is seconds and a
    package, ``getcriu.sh`` is a source download and a three-minute build.
    Folding the second into "Install in WSL: …" would make that dialog a
    consent to something it did not describe — and would name a package
    ``apt-get install`` cannot resolve, which fails the packages beside it.
    """
    if not facts or facts.get("iswsl") == "0":
        return []
    return [(pkg, why) for key, pkg, why, how in _SETUP_OPTIONAL
            if how == "build" and facts.get(key) == "0"]


def setup_unavailable(facts):
    """The missing packages apt cannot install on this machine at all.

    ``setupcheck.sh``'s ``nocand``, which is a fact about the machine's
    package SOURCES rather than about the machine's tools.  Older rigs do not
    emit it, and an absent key means "nothing known against them" - never
    "all of them", which would put a wrong accusation on a working PC.
    """
    return (facts or {}).get("nocand", "").split()


#: Where to send someone whose own WSL distro cannot supply a package.  An
#: LTS, and the one the rig is developed against, so it is a recommendation
#: with evidence behind it rather than "try something newer" - which is what
#: the old wording amounted to, in front of a tester already on the newest.
#: setupfix.sh names the same one in the log; a test holds the two together.
KNOWN_GOOD_DISTRO = "Ubuntu-24.04"

#: The same release, as a user reads it.  One constant, two spellings, so the
#: sentence and the command can never name different Ubuntus.
FALLBACK_RELEASE = KNOWN_GOOD_DISTRO.split("-", 1)[1]


def setup_fetchable(facts):
    """The unavailable packages the rig will go and GET rather than give up on.

    ``setupcheck.sh``'s ``xrel``: a package this release does not publish, but
    which depends on nothing and so installs cleanly out of another Ubuntu's
    archive.  Exactly one qualifies today (qemu-user-static, a static-pie
    interpreter with an empty Depends), and setupfix.sh re-reads the
    downloaded file's control before it installs it — this is what the tab is
    allowed to PROMISE, not what the rig is allowed to do.

    Absent on an older rig, and absent means "none", which is the safe way for
    a promise to be wrong.
    """
    return (facts or {}).get("xrel", "").split()


def setup_fixable(facts):
    """Can “Set up emulator…” actually change anything on this machine?

    A BUTTON THAT CANNOT IS WORSE THAN NO BUTTON.  A tester pressed this one
    twice against a package apt had no version of, and both times the tab had
    promised, underneath the sentence saying the package could not be
    installed, that pressing it would install the package.

    Unknown is yes, like everywhere else here: an older rig that never emitted
    ``nocand`` must not have its silence read as "nothing works".
    """
    if not facts:
        return True
    # NOTHING TO DO IS NOT SOMETHING TO PRESS, and this became reachable with
    # setup_env_faults: the notice now appears for machines whose packages are
    # all present (a root login spoils the picture on a fully installed PC),
    # and without this the button would appear under it offering to install
    # nothing.  Single-sourced against the consent list rather than re-deciding
    # it here - if setupfix.sh has no step to take, there is no button.
    if not setup_fix_steps(facts):
        return False
    if facts.get("universe") == "0":
        return True             # turning universe on IS the repair
    unavailable = set(setup_unavailable(facts)) - set(setup_fetchable(facts))
    if not unavailable:
        return True             # nothing left that cannot be got somehow
    missing, binfmt = setup_summary(facts)
    # Extras count here: the button installs them too, so a machine whose only
    # installable package is a save-state one still has something to press.
    if any(pkg not in unavailable
           for pkg, _ in missing + setup_extras(facts)):
        return True             # some of them still install
    # Nothing installable left.  Switching a handler that is merely off back
    # on is the one repair that needs no package.
    return binfmt == "disabled"


def setup_ok(facts):
    """Can this machine emulate?  Unknown counts as yes - see setup_state."""
    missing, binfmt = setup_summary(facts)
    return not missing and binfmt == "1"


def setup_env_faults(facts):
    """What this WSL will SPOIL, even though the emulator can start on it.

    A different class from everything above, and the class that cost PAD-63.
    The package facts answer "can a 32-bit ARM binary execute here"; a machine
    can pass every one of them and still show a black window, no window, or
    play through the damaged audio hop.  Nothing asked, so the tab said nothing
    and the user found out by running it and reading a log.

    Returns ``[(what is wrong, what to do), ...]`` - pure, so the wording is
    testable without a WSL or a Tk root, like every other notice part here.

    NONE OF IT IS FIXABLE BY THE BUTTON, which is why it is a separate list:
    three of the four are WSL settings that belong to the user.  The notice
    carries the route out instead, the same shape ``setup_fixable`` already
    uses for a package apt cannot supply.

    ABSENT KEYS ACCUSE NOBODY, as everywhere else here: an older rig emits none
    of these lines, and silence is not a fault.
    """
    facts = facts or {}
    out = []
    if facts.get("user") == "root":
        out.append((
            "This WSL logs in as root, so the game window will open and stay "
            "BLACK. Everything else works — sound, switches, the playfield.",
            "Give the distro an ordinary user account, make it the default, "
            "and restart WSL."))
    if facts.get("display") in ("none", "nosocket"):
        out.append((
            "WSLg is not reachable from this distro, so there will be no game "
            "window at all.",
            "Restart WSL. If it comes back, GUI apps are switched off for this "
            "PC in %USERPROFILE%\\.wslconfig."))
    if facts.get("interop") == "0":
        out.append((
            "This WSL cannot start Windows programs, so the playfield window "
            "has to be opened from here and the sound takes its poorer route.",
            "Usually systemd dropping the interop registration at boot; "
            "`wsl --update` in a Windows terminal is the cure."))
    elif facts.get("winaudio") == "0":
        # ONLY WHEN INTEROP WORKS.  Every candidate interpreter is a Windows
        # .exe, so a distro that cannot start Windows programs answers "no
        # Windows Python" however many are installed - and telling that user to
        # install one more is advice addressed to the wrong fault.  It was in a
        # reply draft on 2026-08-12 before this branch existed.
        out.append((
            "No Windows Python with sounddevice, so the sound goes through "
            "WSLg's audio, which is measurably damaged.",
            "`py -m pip install sounddevice` in a Windows terminal, once."))
    return out


def setup_report(facts):
    """The Check button's answer, one line per fact, for the log pane.

    THE POINT IS THAT IT ALWAYS SAYS SOMETHING.  The notice speaks only when
    something is wrong, which makes silence ambiguous between "checked, fine"
    and "never asked" - and leaves a user with a black window nothing to press
    and nothing to send.  This is the thing to ask someone for instead of a
    log: every fact the rig has about their machine, in one paste.
    """
    if not facts:
        return ["setup check: no answer from WSL — it may not be installed, "
                "or the probe timed out."]
    missing, binfmt = setup_summary(facts)
    yes_no = lambda k, y, n: y if facts.get(k) == "1" else (      # noqa: E731
        n if facts.get(k) == "0" else "unknown")
    lines = ["setup check:"]
    lines.append("  packages: " + (", ".join(p for p, _ in missing) + " MISSING"
                                   if missing else "all present"))
    extras = setup_extras(facts)
    if extras:
        lines.append("  save states: %s MISSING"
                     % ", ".join(p for p, _ in extras))
    lines.append("  32-bit ARM handler: "
                 + {"1": "registered", "0": "NOT REGISTERED",
                    "disabled": "registered but SWITCHED OFF"}.get(binfmt,
                                                                   binfmt))
    if facts.get("iswsl") == "1":
        lines.append("  survives a WSL restart: "
                     + yes_no("wslconf", "yes", "NO — systemd is off"))
        lines.append("  logs in as: %s%s"
                     % (facts.get("user", "unknown"),
                        "  <- the picture will be black"
                        if facts.get("user") == "root" else ""))
        lines.append("  can start Windows programs: "
                     + yes_no("interop", "yes", "NO"))
        lines.append("  Windows sound player: "
                     + yes_no("winaudio", "found", "not found"))
    lines.append("  display: %s" % facts.get("display", "unknown"))
    if facts.get("distro"):
        lines.append("  distro: %s" % facts["distro"])
    lines.append("this PC can run the emulator."
                 if setup_ok(facts) else
                 "this PC cannot run the emulator yet.")
    return lines


def setup_report_darwin(docker, cli=None, engine=None):
    """The Check button's answer on a Mac, where the question is a different
    one.

    ``setup_state`` answers None on macOS BY DESIGN - the container carries
    every package the emulator needs (docker/Dockerfile installs them at build
    time), so Docker itself is the whole prerequisite and ``docker_state``
    owns it.  Asking WSL's question on a machine that has no WSL would report
    "no answer from WSL - it may not be installed" to a user whose Mac is
    perfect, which is the same class of lie the None-is-not-fine rule on
    ``setup_state`` exists to prevent.

    Pure, like ``setup_report``, so the wording is testable without a Tk root
    or a Docker.  ``cli`` and ``engine`` are what the probe found (see
    :func:`docker_cli` and :func:`docker_engine`) and both are optional: this
    is the paste a user is asked for when a Mac disagrees with the tab, and
    "which docker, found where" is the fact that settles it.
    """
    lines = ["setup check:",
             "  this Mac emulates in a container, so there are no packages "
             "to install here."]
    lines.append("  Docker: " + {
        "ok": "running",
        "stopped": "installed, but NOT running",
        "engineless": "the command is installed, but nothing here runs "
                      "containers",
        "absent": "NOT installed",
    }.get(docker, "unknown — the probe gave no answer"))
    # NAMED, not just counted.  The bug that added this state was a docker in
    # /opt/local/bin that the app could not see, and no line of any report said
    # where it had looked.
    lines.append("  docker command: " + (cli or "not found on PATH or in "
                                         + ", ".join(DOCKER_DIRS)))
    lines.append("  container engine: "
                 + ("%s (%s)" % (engine[0], engine[2]) if engine else
                    "none installed — Docker Desktop, OrbStack, Rancher "
                    "Desktop and Colima each provide one"))
    lines.append("this Mac can run the emulator." if docker == "ok" else
                 "this Mac cannot run the emulator yet.")
    return lines


def setup_settled(facts):
    """Is there NOTHING left to say about this machine?

    Different from setup_ok, and the difference is the whole of _SETUP_OPTIONAL:
    a PC can run the emulator (setup_ok) and still be missing what its save
    states need.  The tab shows its notice on this, so that "runs, but the save
    slots will not" is a thing it can say - and stays silent on the machine
    that has everything, which is what it did before.

    ...AND "runs, but the picture will be black" IS THE SAME KIND OF THING,
    which the tab was silent about until PAD-63.  See setup_env_faults.
    """
    return (setup_ok(facts) and not setup_extras(facts)
            and not setup_env_faults(facts))


def setup_fix_steps(facts):
    """Everything “Set up emulator…” is about to change, one line each.

    THIS LIST IS THE CONSENT.  setupfix.sh installs packages and writes to
    /etc/wsl.conf inside the user's distro, and the dialog built from this is
    the only place any of that is agreed to - so it is a pure function with
    tests on it rather than a list assembled inside a callback where nothing
    can see it.
    """
    facts = facts or {}
    missing, binfmt = setup_summary(facts)
    # THE BUTTON INSTALLS THE EXTRAS TOO, so the consent list has to name them:
    # setupfix.sh installs whatever setupcheck.sh reports as `need`, which is
    # every probe that came back 0 - this list is what the user agreed to, and
    # it may not be shorter than what is about to happen.
    missing = missing + setup_extras(facts)
    unavailable = setup_unavailable(facts)
    fetch = [p for p in unavailable if p in setup_fetchable(facts)]
    steps = []
    # Named FIRST because it happens first, and because it is the one step
    # here that changes how WSL finds packages at all rather than which
    # packages are on it.
    if facts.get("universe") == "0":
        steps.append(
            "Turn on Ubuntu's “universe” component in WSL — it is "
            "switched off, and it is where %s is published."
            % ", ".join(unavailable))
    # The ordinary install covers everything EXCEPT what has to be fetched:
    # naming a package on both lines reads as installing it twice, and one of
    # the two descriptions of how would be wrong.
    built = [pkg for pkg, _ in setup_built(facts)]
    ordinary = [pkg for pkg, _ in missing
                if pkg not in fetch and pkg not in built]
    if ordinary:
        steps.append("Install in WSL:  " + "  ".join(ordinary))
    # ...AND THE ONE APT HAS NEVER HEARD OF.  No Ubuntu publishes criu, so
    # this step is a source download and a compile, not an install — a
    # different act, a different length (minutes, not seconds), and a
    # different thing to agree to.  It is named with everything it touches
    # for the same reason the rest of this list is.
    if built:
        steps.append(
            "Build %s from source in WSL — no Ubuntu publishes it. This "
            "installs the build tools, downloads the source from GitHub, "
            "compiles it (a few minutes) and puts the result in "
            "/usr/local/bin. Save states need it; nothing else does."
            % ", ".join(built))
    # NAMED SEPARATELY because it is a different act from `apt install`: the
    # package comes out of ANOTHER Ubuntu's archive.  Folding that into the
    # line above would make this dialog a consent to something it did not say.
    if fetch:
        steps.append(
            "%s is not published for your Ubuntu at all, so fetch that one "
            "from Ubuntu %s's archive and install it (it depends on nothing, "
            "so nothing else comes with it). Your package sources are not "
            "changed." % (", ".join(fetch), FALLBACK_RELEASE))
    if binfmt == "0":
        steps.append("Register the kernel's handler for 32-bit ARM programs.")
    elif binfmt == "disabled":
        steps.append("Switch the 32-bit ARM handler back on.")
    if facts.get("iswsl") == "1" and facts.get("wslconf") == "0":
        steps.append("Add [boot] systemd=true to /etc/wsl.conf, so the "
                     "registration is still there after WSL restarts.")
    return steps


def setup_notice(facts, can_fix):
    """What the tab says about a machine that cannot emulate yet.

    THE ARM HANDLER LEADS, when it is what is wrong, because it is the fault
    that produced this: a tester's first run stopped at

        chroot: failed to run command '/bin/sh': Exec format error

    which names the shell and not the missing thing, arrives after Start has
    said "Starting…", and is the one of the rig's four guest-exec faults that
    it cannot repair by itself (the other three it fixes without asking).

    AND IT HAS A SECOND, QUIETER JOB: a machine can run the emulator and still
    be missing what SAVE STATES need (_SETUP_OPTIONAL).  That gets its own
    headline, because telling someone whose emulator works that his PC cannot
    run it is how a correct notice becomes a false one.
    """
    if setup_settled(facts):
        return ""
    missing, binfmt = setup_summary(facts)
    extras = setup_extras(facts)
    env = setup_env_faults(facts)
    if setup_ok(facts):
        # Everything the RUN needs is here; what is missing costs a feature.
        # Lead with the good news, because the alternative wording has just
        # told a working machine that it is broken.  Three headlines rather
        # than two now: a fully installed PC can still be one whose picture
        # will be black, and "Save states do not yet" would be a false
        # description of that machine.
        if extras:
            parts = ["The emulator runs on this PC. Save states do not yet."]
        else:
            parts = ["The emulator runs on this PC, but this WSL will spoil "
                     "it."]
    else:
        parts = ["This PC cannot run the emulator yet."]
    if binfmt == "0":
        parts.append(
            "This machine has no handler registered for 32-bit ARM programs, "
            "and the game is one — so a run would stop the moment it started.")
    elif binfmt == "disabled":
        parts.append(
            "The handler for 32-bit ARM programs is registered but switched "
            "off, and the game is a 32-bit ARM program.")
    if missing:
        parts.append("Missing:\n" + "\n".join(
            "     •  %s — %s" % (pkg, why) for pkg, why in missing))
    # LISTED APART FROM THE ONES ABOVE, and it has to be: those stop a run and
    # this one does not.  A run started without it boots normally and simply
    # cannot be frozen (watch.sh says the same thing in the log), so the line
    # says what it costs rather than filing it under "missing".
    if extras:
        parts.append("Save states need:\n" + "\n".join(
            "     •  %s — %s" % (pkg, why) for pkg, why in extras))
    # NOT INSTALLABLE IS NOT THE SAME AS MISSING, and saying only the first is
    # what sent a tester to press a button that could never work: the tab
    # named qemu-user-static, he pressed “Set up emulator…”, and apt answered
    # "has no installation candidate" because Ubuntu's `universe` component -
    # which is where that package lives - was switched off in his WSL.
    unavailable = setup_unavailable(facts)
    if unavailable:
        named = ", ".join(unavailable)
        if facts.get("universe") == "0":
            parts.append(
                "WSL cannot install %s as it stands: Ubuntu publishes it in "
                "the “universe” component, and this distro has that switched "
                "off." % named)
        else:
            # SAY WHAT WE KNOW, NOT WHAT IT MIGHT BE.  The line that stood
            # here ("the package sources this Linux is set up with do not
            # offer it") is true but shapeless, and the log underneath it went
            # on to blame an out-of-support distro and trimmed sources —
            # neither of which had been checked, and neither of which was true
            # of the machine that met it.  The release and its components are
            # facts setupcheck.sh now reports, so they are what gets said.
            where = facts.get("distro", "").strip()
            comps = facts.get("components", "").split()
            said = "WSL cannot install %s from its own sources." % named
            if where:
                said += "  This is %s" % where
                if "universe" in comps:
                    said += ", with “universe” switched on"
                said += ", and that release does not publish it."
            else:
                said += ("  The package sources this Linux is set up with do "
                         "not offer it.")
            parts.append(said)
    fetch = [p for p in setup_unavailable(facts) if p in setup_fetchable(facts)]
    # `unavailable and` IS NEW AND IS LOAD-BEARING.  setup_fixable now also
    # answers False for a machine with simply nothing to install - which became
    # reachable the moment setup_env_faults let the notice appear on a fully
    # installed PC - and without this gate a root-login machine with every
    # package present would be told that “Set up emulator…” cannot get `that`
    # from this distro, which is a sentence about a fault it does not have.
    if can_fix and unavailable and not setup_fixable(facts):
        # The button is hidden in this state (see _setup_apply), so this is
        # the whole of what the user has to go on.
        if setup_ok(facts):
            # ...and when the emulator itself is fine, "replace your Linux" is
            # a wildly out-of-proportion answer to a feature that is off.  Say
            # what is lost, and leave the working machine alone.
            parts.append(
                "“Set up emulator…” cannot get %s from this distro, so save "
                "states stay off. Everything else about the emulator is "
                "unaffected — titles start and run exactly as they do now."
                % (", ".join(unavailable) or "that"))
        else:
            parts.append(
                "“Set up emulator…” cannot get past this — there is nothing "
                "left for it to install. PAD uses whichever distro WSL calls "
                "the default, so a distro that does carry %s, made the "
                "default, is the way through. In a Windows terminal:\n"
                "     wsl --install -d %s\n"
                "     wsl --set-default %s"
                % (", ".join(unavailable) or "the packages",
                   KNOWN_GOOD_DISTRO, KNOWN_GOOD_DISTRO))
    elif can_fix and setup_fix_steps(facts):
        # ...and the same gate on this side: with no step to take there is no
        # button and nothing to describe, and `does[0]` on an empty list is an
        # IndexError rather than a wrong sentence.
        # ONLY THE PARTS IT IS ACTUALLY GOING TO DO.  Every earlier
        # prerequisite failed on machines whose handler was unregistered too,
        # so "installs those and registers the handler" was always true; the
        # decoder is the first that turns up on its own, on a machine whose
        # handler is fine, and promising to register it there is a promise
        # about something that is not going to happen.  setup_fix_steps is the
        # consent and is already exact - this sentence is its summary and has
        # to be exact the same way.
        does = []
        built = setup_built(facts)
        if facts.get("universe") == "0":
            does.append("turns universe back on")
        # NOT EVERYTHING LISTED ABOVE IS AN INSTALL.  criu is a source build,
        # and "installs those" over a list whose only entry is criu describes
        # something that is not going to happen - apt has no such package.
        if missing or [e for e in extras if e not in built]:
            does.append("installs those in WSL")
        if built:
            does.append("builds %s from source (a few minutes)"
                        % ", ".join(p for p, _ in built))
        if binfmt == "0":
            does.append("registers the handler for 32-bit ARM programs")
        elif binfmt == "disabled":
            # A different act from registering one, and setup_fix_steps has
            # said so since it was written.
            does.append("switches the 32-bit ARM handler back on")
        parts.append(
            "“Set up emulator…” %s. It lists exactly what it will change "
            "first, and needs no password."
            % (", ".join(does[:-1]) + " and " + does[-1]
               if len(does) > 1 else does[0]))
        if fetch:
            # The user is about to be told the button works after being told
            # the package cannot be installed, so it has to say HOW — and say
            # the thing that makes it safe, which is the empty Depends.
            parts.append(
                "%s comes from Ubuntu %s's archive instead, which does "
                "publish it. It depends on nothing, so nothing else comes "
                "with it and the rest of this Linux is left alone."
                % (", ".join(fetch), FALLBACK_RELEASE))
    else:
        cmds = []
        if facts.get("universe") == "0":
            cmds.append("sudo add-apt-repository universe")
        # A package apt has no version of must not be printed INTO the command
        # unless the line above is about to make it installable: `apt install
        # a b` is all or nothing, so one such name in the list is an apt
        # command that installs none of the others.  That is the fault PAD-41
        # fixed in the rig, and it was still here in the advice the rig prints.
        # ...and neither must a package that DOES NOT EXIST.  criu is on no
        # Ubuntu at all, so `apt install criu` cannot work anywhere; it gets
        # the command that does work, on its own line.
        built_names = [p for p, _ in setup_built(facts)]
        askable = [p for p, _ in missing + extras
                   if p not in built_names
                   and (facts.get("universe") == "0" or p not in unavailable)]
        if askable:
            cmds.append("sudo apt install " + " ".join(askable))
        if built_names:
            cmds.append("sudo bash %s" % os.path.join(rig_dir(), "getcriu.sh"))
        if binfmt != "1":
            cmds.append(facts.get("advice", "sudo apt install qemu-user-static"))
        if cmds:
            parts.append("Run this, then start again:\n" + "\n".join(
                "     %s" % c for c in cmds))
    # LAST, AND SEPARATELY, because none of it is anything the button can do.
    # Each line says what the machine will do wrong and what to change; the
    # button above stays hidden or stays about packages, and neither sentence
    # is allowed to claim these.
    for what, cure in env:
        parts.append("%s\n     %s" % (what, cure))
    return "\n\n".join(parts)


class EmulatePanel:
    """The Emulate tab's widgets and its background poller."""

    #: Wall-clock cap handed to ``watch.sh``.  A forgotten window must not be
    #: able to burn a core all night; the rig enforces it, this only chooses it.
    BACKSTOP_MIN = 120

    #: Status poll period.  Each poll is one ``wsl.exe`` round trip, so this is
    #: slow enough to cost nothing and fast enough to feel live.
    POLL_MS = 2000

    #: Poll period when the rig is IDLE.  A run in progress is worth a
    #: two-second heartbeat; a machine with no emulator on it is not worth a
    #: `wsl.exe` spawn every two seconds for as long as the app is open — that
    #: is 1,800 WSL round trips an hour to be told "off" each time, and after
    #: a Windows reboot the first of them boots the whole WSL VM.  A run this
    #: app starts flips to POLL_MS immediately (the status says so), so the
    #: only thing this delays is noticing a run somebody started in a
    #: terminal, by a few seconds.
    POLL_IDLE_MS = 10000

    def __init__(self, parent, log=None, card_var=None, savestates_var=None,
                 theme_fn=None, badge_fn=None, resize_fn=None):
        self._parent = parent
        self._log_sink = log or (lambda msg: None)
        #: "This tab is taller than it was" - MainWindow._resize_notebook_to_
        #: current_tab, injected the same way the log and the theme are.
        #:
        #: WHY THE PANEL HAS TO ASK.  ttk.Notebook is pinned to the selected
        #: tab's requested height, measured when the tab is selected, and the
        #: setup notice is the one thing here that appears LATER: the probe
        #: that arms it now runs after a WSL restart, with the user already
        #: sitting on this tab.  Packed into a pane that was measured without
        #: it, the label gets no room and pack leaves it unmapped - so the
        #: "Set up emulator…" button appeared beside a sentence nobody could
        #: read.  Found in the before/after shots for PAD-62, not in a test.
        self._resize_fn = resize_fn or (lambda: None)
        # The card path lives in a variable the WINDOW owns (when given one):
        # the app persists it into the project anchor and restores it when a
        # project loads, exactly like the Extract/Write path fields. The
        # fallback keeps the panel testable on its own.
        self._card_var = card_var
        # Same window-owned pattern for the save-states opt-in (item 13):
        # default OFF, persisted with the project. The fallback var keeps the
        # panel testable on its own, same as the card path's.
        self._states_var = savestates_var
        self._theme_fn = theme_fn or (lambda: "dark")
        #: The window's round ⓘ badge factory (``MainWindow._make_round_icon``),
        #: passed in rather than reached for: this panel is built standalone in
        #: tests, and scene_browser's ``_info`` sets the precedent of degrading
        #: to a plain label when the app is not there.
        self._badge_fn = badge_fn
        #: status.sh's saves_mtime the last time the slot list was read.
        #: The list refreshes itself whenever the token moves.
        self._saves_token = None
        #: A slot waiting to be loaded once the boot the Launch button
        #: started comes up — _apply fires it when running=1.  And whether
        #: a load is in flight right now (one at a time, like the poll).
        self._launch_slot = None
        self._loading = False
        self._proc = None            # the watch.sh child, while we own one
        #: The virtual playfield window, ON THE MACHINES WHERE PAD HAS TO OPEN
        #: IT ITSELF (see _open_playfield).  Normally watch.sh launches it
        #: through WSL interop and this stays None; when interop is off it
        #: cannot, and then PAD owns the process — which means PAD closes it,
        #: because the rig's forced close is a powershell.exe call and that is
        #: interop too.
        self._pf_proc = None
        #: Whether the last status poll saw anything running. Read by
        #: shutdown_sync() on app quit: a terminal-started run shows up here
        #: too, and quitting PAD must take the emulator down either way.
        self._last_up = False
        # TWO flags, not one.  A single "_busy" covering both was a real bug:
        # the thread that drains watch.sh's output lives for as long as the
        # emulator does, so a shared flag stayed set the whole session and Stop
        # returned immediately without doing anything.  _starting is only true
        # across the launch itself.
        self._starting = False
        self._stopping = False
        self._resetting = False
        #: A "Reset windows" run is in flight.  Its own flag rather than
        #: _resetting: that one greys the WSL restart and is cleared by a
        #: worker that can take two minutes, and the two must not unstick
        #: each other's button.
        self._winresetting = False
        self._poll_job = None
        self._stopped = False
        # NO game-log path is chosen here, on purpose. The GUI runs on the
        # HOST and the rig runs wherever Linux is (WSL, a container), so a
        # path picked on this side is wrong exactly when the two differ: a
        # hardcoded LOG=/home/david/gzpad.log was handed into the macOS
        # container, the game start's `> "$LOG"` redirect failed, and the
        # game never ran at all while everything around it looked normal.
        # watch.sh, status.sh and every helper script already default to the
        # same $HOME/gzwatch.log resolved on the LINUX side; saying nothing
        # is what keeps them agreeing.
        #: macOS only: whether Screen Sharing has been opened for the current
        #: run. The picture lives on a VNC display inside the container -
        #: there is no native window coming, and a user left to wait for one
        #: waits forever.
        self._vnc_opened = False
        #: True only for a run THIS panel started. Attaching to a run that
        #: was started from a terminal must not pop a viewer nobody asked
        #: for - the terminal already said where the picture is.
        self._started_here = False
        #: Last answer from docker_state(), macOS only.  None until the first
        #: probe comes back, which is why nothing is claimed before then.
        self._docker = None
        self._docker_busy = False
        self._docker_ticks = 0
        self._docker_result = None
        #: What that probe found alongside the state word: the `docker` command
        #: it used, and the engine that could run a container for it.  Both are
        #: needed to say anything useful about a Mac that has one and not the
        #: other, and both are asked on the SAME worker thread as the state -
        #: they are filesystem lookups, and the main loop does not do those on
        #: behalf of a probe it has already moved off itself.
        self._docker_cli = None
        self._docker_engine = None
        #: Last answer from setup_state(), Windows/Linux only.  None means the
        #: question has not been answered yet OR could not be asked, and both
        #: read the same way on purpose: nothing is claimed without evidence.
        self._setup = None
        self._setup_busy = False
        self._setup_result = None
        self._setup_fixing = False
        #: The probe now out was armed by a `wsl --shutdown` this panel did,
        #: so its answer is worth a line in the log as well as the notice.
        #: See _setup_after_restart and _setup_apply.
        self._setup_restart_check = False
        #: The macOS half of the same flag: there the Check button asks Docker,
        #: because that is the whole of what a Mac needs.  See
        #: _setup_recheck_now and _docker_report_if_asked.
        self._docker_report_next = False
        #: The probe now out was asked for by “Check setup…”, so its answer is
        #: reported IN FULL to the log pane - including a machine with nothing
        #: wrong, which no other path here ever says out loud.  See
        #: _setup_report_if_asked.
        self._setup_report_next = False
        #: A status poll's wsl.exe is in flight — see _poll.  Written only on
        #: the main thread, so it cannot be raced by the worker it gates.
        self._poll_busy = False
        #: Whether ANY status poll has come back yet.  Until one has, the
        #: poll retries on a short timer instead of the 10 s idle cadence —
        #: the first answer is what fills the save-state list, and a user
        #: looks at that list the moment the app opens.  See _schedule_poll.
        self._polled_once = False
        #: Drain passes the current setup probe has been out for, and whether
        #: the "Starting WSL" line went up because of it (so only the writer
        #: takes it down - the hint label has other owners).
        self._setup_ticks = 0
        self._setup_said_boot = False
        #: Item 56: master PC-side volume + Mute, loaded once here so the
        #: widgets built in build() already show what padplay.py will
        #: actually play.  LIVE controls, unlike Sound/Auto-attract above -
        #: see build()'s comment on why they are never greyed out.
        vol0, mute0 = _load_audio_ctl()
        self._volume_var = tk.DoubleVar(value=vol0 * 100)
        self._mute_var = tk.BooleanVar(value=mute0)

    def _timer(self):
        """The widget every ``after`` job on this panel is hung off.

        NOT the tab frame, which is the obvious choice and is wrong.  An
        ``after`` job registers a Tcl command owned by the widget it was
        scheduled on, and the tab frame is destroyed in the middle of the
        ``root.destroy()`` cascade - cancelling a job on a widget that is
        itself being torn down raises ``can't delete Tcl command``, which
        showed up as four errors in the GUI smoke test and is not visible in
        normal use because the app is normally alive when a poll fires.  The
        toplevel outlives every tab, so a cancel from the frame's ``<Destroy>``
        handler always lands on a live widget.
        """
        return self._parent.winfo_toplevel()

    def _log(self, msg):
        """Log from ANY thread.  ``append_log`` writes into a Tk Text widget and
        Tk is not thread safe, so the two places this is called from - the
        watch.sh output drain and the stop worker - must hand it back to the
        main loop.  Calling it directly is the bug that froze the Partition
        Explorer's extract."""
        try:
            self._timer().after(0, lambda: self._log_sink(msg))
        except (tk.TclError, RuntimeError):
            pass    # main loop gone; nothing to log into

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def build(self, frame):
        pad = {"padx": 10, "pady": 4}

        intro = ttk.Label(
            frame, justify=tk.LEFT, wraplength=820,
            text=("Runs a real Stern Spike 2 game binary on this PC under "
                  "emulation, in its own window, with sound.\n"
                  "Pick a card image and it runs straight off it — nothing is "
                  "extracted and the image is opened read only."))
        intro.pack(anchor=tk.W, **pad)

        self._build_source(frame, pad)

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, **pad)
        # ONE button, not two.  Start and Stop are never both available - the
        # emulator is either up or it is not - so a pair of buttons meant one of
        # them was always greyed out, and the greyed one still had to be aimed
        # at.  A single button that says what it will do next is the whole
        # control.  _run_label() owns the text and the state; nothing else sets
        # them, so the button cannot drift out of step with the rig.
        self._run_btn = ttk.Button(btns, text="Start emulator",
                                   command=self._toggle, width=16)
        self._run_btn.pack(side=tk.LEFT)

        # The remedy for the faults that are NOT ours and cannot be fixed from
        # inside WSL.  It used to be called "Fix crackly sound", after the only
        # one known at the time; it now covers two, and the one it is reached
        # for most is the second:
        #   * a STRANDED EMULATOR WINDOW.  When WSLg's RAIL side keeps painting
        #     a window whose X client has gone, clicking its X does nothing -
        #     there is no client left to receive the close - and msrdc is a
        #     protected process, so it cannot be killed either.  `wsl
        #     --shutdown` is the only cure found.
        #   * crackly sound on the WSLg fallback path.  Measured 2026-08-05: a
        #     pure sine came back mathematically perfect off the sink's own
        #     monitor while it was audibly breaking up in the room, so nothing
        #     inside WSL can see it.  (The default sink no longer goes through
        #     WSLg at all, so this half is now the fallback's problem only.)
        # It is here because the alternative is remembering a command that has
        # nothing to do with pinball, at the moment you are least inclined to
        # go looking for one.
        #
        # WINDOWS ONLY, because there is no WSL to restart anywhere else and a
        # button that cannot do its one job is worse than no button.  The two
        # faults it cures are both WSL's: a WSLg window still being painted
        # after its X client has gone, and the WSLg-to-Windows audio hop
        # degrading over a long session.  Neither exists on a Linux desktop.
        self._fixaud_btn = ttk.Button(btns, text="Restart WSL…",
                                      command=self._audio_reset, width=17)
        if sys.platform == "win32":
            self._fixaud_btn.pack(side=tk.LEFT, padx=(6, 0))

        # The escape hatch for a window that cannot be dragged back (item 37).
        # EVERY platform, unlike the two buttons around it: the remembered
        # geometry is restored with no on-screen check wherever the rig runs,
        # and a second monitor that goes away is not a Windows-only event.
        self._winreset_btn = ttk.Button(btns, text="Reset windows",
                                        command=self._window_reset, width=15)
        self._winreset_btn.pack(side=tk.LEFT, padx=(6, 0))

        # MACOS ONLY, for exactly the reason "Restart WSL…" is Windows only:
        # Docker is that platform's WSL.  The emulator is a Linux program, macOS
        # has no Linux, and a container is how it gets one - so a Mac without
        # Docker cannot emulate at all, and the app had nowhere on this tab that
        # said so or offered to help.  It packs and unpacks itself from
        # _docker_apply(): a ready machine should not carry a button about a
        # dependency it already satisfies.
        self._docker_btn = ttk.Button(btns, text="Install Docker…",
                                      command=self._docker_fix, width=17)

        # WINDOWS ONLY, and for the same reason the Docker button is macOS
        # only: it can only do its job where the app can actually get root.
        # See rig_cmd_root - on WSL that is free, on a Linux desktop it is a
        # password prompt with nowhere to appear.  Packs itself from
        # _setup_apply(), so a machine that is already set up never sees it.
        self._setup_btn = ttk.Button(btns, text="Set up emulator…",
                                     command=self._setup_fix, width=18)

        # ★ AND THE ONE THAT IS ALWAYS THERE, because LOOKING is not something
        # a user should have to consent to - setupcheck.sh's own header has
        # said that since it was written, and the UI never offered the looking
        # half.  The pair is deliberate and the split is the point: this one
        # changes NOTHING and is always available, “Set up emulator…” changes
        # the machine and appears only when it has something to change.
        #
        # WHY IT HAD TO EXIST (PAD-63).  Silence from this tab meant two
        # different things - "asked, nothing wrong" and "never asked" - and a
        # user whose game window was black had nothing to press and nothing to
        # send.  The answer goes into the LOG PANE, not just the notice, so
        # that "press Check setup and paste what it says" is a thing that can
        # be asked of someone, and so it is one paste rather than a run.
        #
        # NOT MADE A PERMANENT “Set up emulator…” INSTEAD: that button is
        # allowed to install packages and write /etc/wsl.conf, and one that is
        # always pressable with nothing to do is what _setup_apply already
        # records a tester meeting twice, minutes apart.
        # EVERY PLATFORM, unlike the button above it: the probe is read-only,
        # and a Linux desktop or a Mac has just as much right to be told what
        # its machine is missing as a Windows one - it simply gets commands to
        # run instead of a button to press (setup_notice's `can_fix` split).
        self._check_btn = ttk.Button(btns, text="Check setup…",
                                     command=self._setup_recheck_now, width=14)
        self._check_btn.pack(side=tk.LEFT, padx=(6, 0))

        # BOTH tickboxes are read ONCE, when Start builds the environment for
        # watch.sh, so they are start-time options and not live controls.  They
        # are therefore disabled while the emulator is up: leaving them
        # clickable invites unticking one mid-run and concluding the option is
        # broken when nothing happens, which is exactly what a tester reported.
        self._audio_var = tk.BooleanVar(value=True)
        self._audio_chk = ttk.Checkbutton(btns, text="Sound",
                                          variable=self._audio_var)
        self._audio_chk.pack(side=tk.LEFT, padx=(16, 0))

        # On by default: the game boots to Tech Alerts and waits for an
        # operator, which means sitting through ~15 s of bring-up and then
        # pressing Escape twice, every single start.  There is no state to save
        # instead — see autoattract.sh for why NVRAM is not the lever.
        self._auto_var = tk.BooleanVar(value=True)
        self._auto_chk = ttk.Checkbutton(btns, text="Skip to attract mode",
                                         variable=self._auto_var)
        self._auto_chk.pack(side=tk.LEFT, padx=(12, 0))

        # ITS OWN ROW, not crowded into btns above: btns already re-packs
        # _docker_btn/_setup_btn at the end of ITS OWN pack order whenever
        # docker/setup state changes (pack_forget() then a bare pack() with
        # no before=/after= always appends), and Tk's packer UNMAPS a slave
        # it cannot fit rather than shrinking it - so a wider btns row was
        # putting those two buttons at real risk of losing their mapping on
        # a narrower/CI-sized window. Confirmed live: adding these three
        # widgets to btns itself made test_a_ready_docker_leaves_no_notice_
        # behind and test_a_wsl_restart_re_probes_what_it_left_behind fail
        # winfo_ismapped() twice running on macOS CI, on a commit that
        # changed nothing else about either button.
        audio_row = ttk.Frame(frame)
        audio_row.pack(fill=tk.X, **pad)
        # Item 56: the emulator's OWN volume to the PC speakers, not the
        # game's in-game adjustment (that stays on the coin door, per title,
        # untouched by this).  Deliberately LIVE, unlike Sound/Auto-attract
        # above: those are read once when Start builds watch.sh's
        # environment, so David asked for a knob that moves the sound
        # WITHOUT a restart, which is the opposite of that shape — so these
        # two are never added to the up/busy disable block in _apply.
        ttk.Label(audio_row, text="Volume:").pack(side=tk.LEFT)
        self._vol_scale = ttk.Scale(audio_row, from_=0, to=100, length=110,
                                    orient=tk.HORIZONTAL,
                                    variable=self._volume_var,
                                    command=self._on_volume_change)
        self._vol_scale.pack(side=tk.LEFT, padx=(4, 0))
        self._mute_chk = ttk.Checkbutton(audio_row, text="Mute",
                                         variable=self._mute_var,
                                         command=self._on_volume_change)
        self._mute_chk.pack(side=tk.LEFT, padx=(6, 0))
        # Seed the control file NOW, from whatever was just loaded (or the
        # unity/unmuted default) — so it exists before the first Start even
        # on a machine that has never touched the knob, rather than relying
        # on padplay.py's own separate default to happen to agree.
        self._on_volume_change()

        self._build_states(frame, pad)

        grid = ttk.LabelFrame(frame, text="Status")
        grid.pack(fill=tk.X, **pad)
        self._vals = {}
        rows = [
            ("state", "State:"),
            ("procs", "Processes:"),
            ("cpu", "Game CPU / memory:"),
            ("host", "Renderer:"),
            ("audio", "Audio:"),
        ]
        for r, (key, label) in enumerate(rows):
            ttk.Label(grid, text=label, width=22, anchor=tk.W).grid(
                row=r, column=0, sticky=tk.W, padx=8, pady=2)
            v = ttk.Label(grid, text="—", anchor=tk.W)
            v.grid(row=r, column=1, sticky=tk.W, padx=4, pady=2)
            self._vals[key] = v
        grid.columnconfigure(1, weight=1)

        self._hint = ttk.Label(frame, justify=tk.LEFT, wraplength=820,
                               foreground="#888", text="")
        self._hint.pack(anchor=tk.W, **pad)

        # ITS OWN LABEL, not _hint.  _hint belongs to the status poll and is
        # rewritten every two seconds from the rig's own state word, so a
        # prerequisite message put there would blink out again immediately.
        self._docker_msg = ttk.Label(frame, justify=tk.LEFT, wraplength=820,
                                     foreground="#c07000", text="")
        self._docker_pad = pad

        # Same reasoning, same colour: this is a prerequisite notice, not the
        # rig's state, so it must not share a label with the status poll.
        self._setup_msg = ttk.Label(frame, justify=tk.LEFT, wraplength=820,
                                    foreground="#c07000", text="")
        self._setup_pad = pad

        # The key list that used to be here is gone. The virtual playfield's
        # key panel lists every binding (item 39; before that, the Controls
        # window), and it is generated from the bindings themselves rather
        # than typed out - so a copy on this tab was a second source of truth
        # that could only ever drift out of date.

        if not rig_available():
            self._run_btn.configure(state=tk.DISABLED)
            self._fixaud_btn.configure(state=tk.DISABLED)
            self._winreset_btn.configure(state=tk.DISABLED)
            # SAY WHERE IT ACTUALLY IS. This used to read "it is not part of
            # this repository", which was wrong and sent people looking for a
            # separate download: the rig IS in the repository, at
            # tools/spike2_emu, and it is the INSTALLERS that deliberately do
            # not carry it. A user who installed to Program Files and read that
            # sentence had no way to work out what to do next.
            if sys.platform == "darwin":
                self._hint.configure(
                    text=("The emulator rig was not found in %s.\n\n"
                          "It ships with the app. On macOS it runs in a "
                          "container — the emulator needs Linux — and shows "
                          "its picture over VNC, which Screen Sharing opens "
                          "with nothing to install.\n\n"
                          "Docker Desktop is required. Set PAD_EMU_DIR if the "
                          "rig is somewhere else." % rig_dir()))
            elif sys.platform != "win32":
                self._hint.configure(
                    text=("The emulator rig was not found in %s.\n\n"
                          "It ships with the app, in tools/spike2_emu. Re-run "
                          "the installer, or set PAD_EMU_DIR to point at that "
                          "folder.\n\n"
                          "There is no setup step once it is found: the "
                          "first run builds the guest filesystem out of the "
                          "card you pick, and compiles the shim and the "
                          "renderer." % rig_dir()))
            else:
                self._hint.configure(
                    text=("The emulator rig was not found in %s.\n\n"
                          "It ships with the app, so this usually means an "
                          "upgrade over a copy that predates it, or a checkout "
                          "without tools/spike2_emu. Re-run the installer, or "
                          "set PAD_EMU_DIR to point at that folder.\n\n"
                          "There is no setup step once it is found: the "
                          "first run builds the guest filesystem out of the "
                          "card you pick, and compiles the shim and the "
                          "renderer." % rig_dir()))
        # The poll re-arms itself forever, so it MUST be cancelled when the tab
        # goes away.  A pending `after` job outliving its widgets is what makes
        # Tk raise "can't delete Tcl command" during teardown - it showed up
        # immediately as an error in the GUI smoke test.
        frame.bind("<Destroy>", self._on_destroy, add="+")
        if sys.platform == "darwin":
            self._docker_check()
        else:
            # ASKED ONCE, HERE, rather than left for the run to discover. The
            # rig finds each missing tool one at a time by failing on it, which
            # is three separate runs and three separate walls of log text for
            # someone who has none of them.
            self._setup_check()
        self._schedule_poll()

    # ------------------------------------------------------------------
    # Docker, which on macOS is what WSL is on Windows
    # ------------------------------------------------------------------

    def _docker_check(self):
        """Probe Docker off the main loop and show the answer.

        Never blocking: ``docker info`` against a daemon that is starting can
        take seconds, and one of the callers is tab BUILD time.

        THE WORKER TOUCHES NO WIDGET AND SCHEDULES NOTHING, which is a stronger
        rule than the one the status poll follows and it is build time that
        forces it: ``after`` from another thread needs a running mainloop, and
        at build time there is not one yet, so the answer would have been
        dropped in silence and the notice would not appear until the first
        re-check ten seconds later.  The worker leaves its answer in a field
        and _docker_drain(), which is main-loop code from the first call,
        collects it.
        """
        if self._docker_busy or sys.platform != "darwin":
            return
        self._docker_busy = True

        def run():
            try:
                self._docker_result = self._docker_probe()
            finally:
                self._docker_busy = False

        threading.Thread(target=run, daemon=True).start()
        self._docker_drain()

    def _docker_probe(self):
        """The three questions, asked together, off the main loop.

        ONE PLACE, because Start asks them again on every press - the user may
        have installed or started something since build time - and a second
        copy would be free to drift, which is how a state word and the paths
        printed beside it end up describing different machines.

        The two lookups come FIRST: the state is the conclusion drawn from
        them, so they must not be the older pair.
        """
        self._docker_cli = docker_cli()
        self._docker_engine = docker_engine()
        return docker_state()

    def _docker_drain(self):
        """Main-loop side of _docker_check: show the answer once it lands."""
        if self._stopped:
            return
        if self._docker_busy:
            try:
                self._timer().after(250, self._docker_drain)
            except tk.TclError:
                self._stopped = True
            return
        if self._docker_result is not None:
            self._docker_apply(self._docker_result)
            self._docker_result = None
        else:
            # NO ANSWER IS STILL AN ANSWER TO A BUTTON PRESS - the same rule
            # _setup_drain follows, and for the same reason: _docker_apply is
            # deliberately not called with None.  No-op unless Check asked.
            self._docker_report_if_asked(None)

    def _docker_report_if_asked(self, state):
        """“Check setup…”'s answer on a Mac.  See _setup_report_if_asked, whose
        shape and whose reasons this mirrors exactly - a Check that left the
        button reading "Checking…" for the rest of the session is the fault
        that button exists to fix, and on macOS that is what it did."""
        if not getattr(self, "_docker_report_next", False):
            return
        self._docker_report_next = False
        for line in setup_report_darwin(state, self._docker_cli,
                                        self._docker_engine):
            self._log("[emulate] " + line)
        try:
            self._check_btn.configure(state=tk.NORMAL, text="Check setup…")
        except (tk.TclError, AttributeError):
            pass

    def _docker_apply(self, state):
        """Put the Docker answer on the tab, or take it away when it is fine.

        TWO BUTTONS, ONE JOB EACH, and the split is the same one Windows makes:
        “Set up emulator…” CHANGES the machine (it installs the engine and
        starts it, here as much as there), and the Docker button only starts
        something already installed - or, when this Mac has no package manager
        to install with, opens the download page.  Nothing tells anyone to type
        a command: that was the first version of this fix, and it was wrong.
        """
        self._docker = state
        self._docker_report_if_asked(state)
        try:
            if state == "ok":
                self._docker_btn.pack_forget()
                self._setup_btn.pack_forget()
                self._docker_msg.pack_forget()
                self._refit()
                return
            plan = (engine_setup_plan(self._docker_cli)
                    if state in ("engineless", "absent") else None)
            if state == "stopped":
                # NAME THE ENGINE THAT IS ACTUALLY HERE.  "Open Docker Desktop"
                # is not advice on a Mac running Colima or OrbStack, and the
                # button below used to `open -a Docker` on every one of them.
                eng = self._docker_engine
                label = eng[0] if eng else "Docker Desktop"
                self._docker_btn.configure(text="Start Docker")
                self._docker_msg.configure(
                    text=("Docker is installed but not running, and the "
                          "emulator runs inside it. Click “Start Docker”, or "
                          "start %s yourself and give it a moment to come up."
                          % label))
            elif state == "engineless":
                # ★ THE CASE THAT USED TO READ AS "NOT INSTALLED".  The client
                # is right there; what is missing is the Linux VM behind it,
                # which is a different install and on some Macs cannot be
                # Docker Desktop at all.
                self._docker_msg.configure(
                    text=("The docker command is installed here (%s), but "
                          "nothing on this Mac can run a container: on macOS "
                          "docker is only the client, and the containers "
                          "themselves need a Linux machine behind it."
                          % (self._docker_cli or "found on PATH")
                          + (self._plan_sentence(plan) if plan else
                             " Docker Desktop, OrbStack and Colima each "
                             "provide one; the button below opens the Docker "
                             "Desktop download page.")))
            else:
                self._docker_msg.configure(
                    text=("Docker is required to emulate on macOS: the game is "
                          "a Linux program and a container is how this Mac "
                          "runs one. It is a one-time install."
                          + (self._plan_sentence(plan) if plan else
                             "\nThe button below opens the download page.")))
            # The install button is “Set up emulator…”, the same one Windows
            # presses for the same reason; the Docker button stays for the
            # cases that install nothing.
            if plan:
                self._docker_btn.pack_forget()
                self._setup_btn.pack(side=tk.LEFT, padx=(6, 0))
            else:
                self._setup_btn.pack_forget()
                self._docker_btn.configure(
                    text="Start Docker" if state == "stopped" else "Get Docker…")
                self._docker_btn.pack(side=tk.LEFT, padx=(6, 0))
            self._docker_msg.pack(anchor=tk.W,
                                  **getattr(self, "_docker_pad", {}))
            self._refit()
        except (tk.TclError, AttributeError):
            pass            # the tab was never built, or is being torn down

    @staticmethod
    def _plan_sentence(plan):
        """What “Set up emulator…” will do, in one sentence for the notice.

        Built from the plan and not typed out beside it, so the words under the
        button cannot promise something other than what the button runs.
        """
        return ("\nPress “Set up emulator…” and this app will install %s with "
                "%s and start it%s. Colima is the Linux machine that runs the "
                "container, and it works on the macOS versions Docker Desktop "
                "no longer supports."
                % (plan["label"], plan["manager"],
                   ", asking for your password once" if plan["admin"] else ""))

    def _docker_fix(self):
        """Start the engine this Mac has, or go and get one.

        INSTALLING IS NOT THIS BUTTON'S JOB ANY MORE - “Set up emulator…” owns
        that, on macOS exactly as on Windows (see _setup_fix_darwin).  What is
        left here is starting something already installed, and the one case
        this app cannot do for the user: a Mac with no package manager, which
        gets the Docker Desktop download page rather than a command to type.

        AND IT STARTS WHAT IS ACTUALLY INSTALLED.  ``open -a Docker`` was the
        only thing this button could do, on a platform where the engine is as
        likely to be Colima or OrbStack; on a Mac without Docker Desktop it
        opened nothing and said it had started something.
        """
        if self._setup_fixing:
            return              # a start or an install is already running
        if self._docker == "stopped":
            self._docker_start_engine()
            return
        self._docker_download()

    def _docker_download(self):
        """The last resort: send them to the download page.

        A page and an installer to double-click, which is a thing a Mac user
        does; the alternative here was never a Terminal command.
        """
        import webbrowser
        webbrowser.open(DOCKER_URL)
        self._log("[emulate] opened %s - install it, then click Start "
                  "emulator again" % DOCKER_URL)

    def _docker_start_engine(self):
        """Start whatever engine this Mac has, by the means that engine wants.

        An .app is ``open -a``.  Colima is a command, and it is run HERE with
        its output drained into the log pane - not handed to Terminal, which
        would be this app asking the user to watch it work.
        """
        eng = self._docker_engine
        if eng and eng[1] == "cli":
            self._log("[emulate] starting %s; the first start takes a couple "
                      "of minutes" % eng[0])
            self._run_engine_setup([("starting %s" % eng[0],
                                     [eng[2], "start"], False)])
            return
        target = eng[2] if eng else "Docker"
        label = eng[0] if eng else "Docker Desktop"
        try:
            subprocess.Popen(["open", "-a", target])
            self._log("[emulate] starting %s; it takes a moment to come up"
                      % label)
        except Exception as exc:                        # noqa: BLE001
            self._log("[emulate] could not start %s: %s" % (label, exc))
        self._timer().after(4000, self._docker_check)

    # ------------------------------------------------------------------
    # ...and doing something about it, without sending anyone to Terminal
    # ------------------------------------------------------------------

    def _run_engine_setup(self, phases):
        """Run *phases* off the main loop, into the log pane, then re-probe.

        ``phases`` is ``(label, argv, admin)``, in order; the first failure
        stops the rest, because "install failed" followed by "start failed"
        is one fault reported twice and the second line is the less useful of
        the two.

        SHAPED LIKE _setup_fix's Windows worker on purpose: disable the button,
        stream every line as it arrives, say what happened in words, then ask
        the machine again rather than assuming the press worked.
        """
        self._setup_fixing = True
        # BOTH buttons, because either one can be the visible one here: “Set up
        # emulator…” starts this, and so does “Start Docker” when the engine is
        # Colima.  Leaving the other pressable is a second `colima start` on
        # top of the one already running.
        try:
            self._setup_btn.configure(state=tk.DISABLED, text="Setting up…")
            self._docker_btn.configure(state=tk.DISABLED)
        except (tk.TclError, AttributeError):
            pass

        def run():
            ok = True
            try:
                for label, argv, admin in phases:
                    # Resolved HERE when it is a callable: a step's command can
                    # depend on what the step before it installed.
                    argv = argv() if callable(argv) else argv
                    if not argv:
                        ok = False
                        self._log("[emulate] %s: the command it needs is not "
                                  "on this Mac, even after the install above."
                                  % label)
                        break
                    ok = self._run_step(label, argv, admin)
                    if not ok:
                        break
            except Exception as exc:                    # noqa: BLE001
                ok = False
                self._log("[emulate] setup failed: %s" % exc)
            if ok:
                self._log("[emulate] the container engine is installed and "
                          "running; this Mac can emulate now.")
            self._setup_fixing = False
            try:
                self._timer().after(0, self._setup_recheck)
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=run, daemon=True).start()

    def _run_step(self, label, argv, admin):
        """One phase of the setup: run it, log every line, say if it worked.

        ADMIN IS macOS's OWN DIALOG, not a password box this app invents and
        not a Terminal window: ``do shell script … with administrator
        privileges`` is what a Mac installer uses, and the user answers it with
        Touch ID or the password they already know.

        ``do shell script`` hands back its output only when it FINISHES, and a
        package install runs for minutes - so the privileged command writes to
        a log file that this side tails while it runs.  A silent five minutes
        is indistinguishable from a hang, which is the whole reason the WSL
        boot notice exists on the other half of this tab.
        """
        import shlex
        import tempfile
        self._log("[emulate] %s: %s" % (label, " ".join(argv)))
        if not admin:
            try:
                proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        creationflags=_CREATE_FLAGS)
            except Exception as exc:                    # noqa: BLE001
                self._log("[emulate] could not start %s: %s" % (argv[0], exc))
                return False
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self._log("[emulate] " + line)
            rc = proc.wait()
            if rc:
                self._log("[emulate] %s did not finish (exit %s)."
                          % (label, rc))
            return rc == 0

        # mkdtemp, not a name in /tmp: it is created 0700 and owned by this
        # user, so nothing can swap the script out from under the root shell
        # between writing it and running it.
        work = tempfile.mkdtemp(prefix="pad_engine_")
        script = os.path.join(work, "setup.sh")
        out = os.path.join(work, "setup.log")
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n" + " ".join(shlex.quote(a) for a in argv)
                    + "\n")
        shell = "/bin/sh %s > %s 2>&1" % (shlex.quote(script),
                                          shlex.quote(out))
        osa = ('do shell script "%s" with administrator privileges'
               % shell.replace("\\", "\\\\").replace('"', '\\"'))
        try:
            proc = subprocess.Popen(["osascript", "-e", osa],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        except Exception as exc:                        # noqa: BLE001
            self._log("[emulate] could not ask macOS for permission: %s" % exc)
            return False
        seen = 0
        while proc.poll() is None:
            seen = self._tail(out, seen)
            time.sleep(0.5)
        self._tail(out, seen)
        err = (proc.stderr.read() or b"").decode("utf-8", "replace")
        try:
            shutil.rmtree(work, ignore_errors=True)
        except Exception:                               # noqa: BLE001
            pass
        if proc.returncode == 0:
            return True
        # A cancelled password dialog is not a failure to explain, it is a
        # decision to respect - and the machine is exactly as it was.
        if "-128" in err or "cancel" in err.lower():
            self._log("[emulate] setup cancelled; nothing was changed.")
        else:
            self._log("[emulate] %s did not finish. %s"
                      % (label, err.strip() or "See the lines above."))
        return False

    def _tail(self, path, seen):
        """Log whatever is new in *path*, and say how far this got.

        Bytes rather than lines: the install is still writing, so the tail of
        the file is routinely half a line, and it must not be logged twice
        once the rest of it lands.
        """
        try:
            with open(path, "rb") as f:
                f.seek(seen)
                data = f.read()
        except OSError:
            return seen
        if not data:
            return seen
        text = data.decode("utf-8", "replace")
        keep = text.rsplit("\n", 1)
        done = keep[0] if len(keep) > 1 else ""
        for line in done.splitlines():
            if line.strip():
                self._log("[emulate] " + line.rstrip())
        return seen + len(done.encode("utf-8")) + (1 if len(keep) > 1 else 0)

    # ------------------------------------------------------------------
    # the setup check, which is what WSL needs and Docker is on a Mac
    # ------------------------------------------------------------------

    def _setup_check(self):
        """Probe the machine off the main loop and show the answer.

        Same shape as _docker_check, and for the same reason: one of the
        callers is tab BUILD time, where there is no mainloop yet, so the
        worker touches no widget and schedules nothing.  It leaves its answer
        in a field for _setup_drain to collect.
        """
        if self._setup_busy or sys.platform == "darwin":
            return
        self._setup_busy = True
        self._setup_ticks = 0

        def run():
            try:
                self._setup_result = setup_state()
            finally:
                self._setup_busy = False

        threading.Thread(target=run, daemon=True).start()
        self._setup_drain()

    def _setup_drain(self):
        """Main-loop side of _setup_check.

        ALSO THE HONEST MOUTH FOR A COLD WSL.  The probe is one wsl.exe call,
        and the first wsl.exe after a Windows reboot boots the whole WSL VM -
        tens of seconds, sometimes minutes, during which this tab used to show
        a dash and say nothing.  David restarted Windows on 2026-08-09, opened
        PAD, and read that silence as a broken app.  A probe still out after
        _WSL_BOOT_TICKS passes can only mean that boot (a warm WSL answers
        inside one), so that is when the tab says so - and the sayer takes its
        own line down again, because the status poll is gated behind this very
        probe (see _poll) and will not overwrite it.
        """
        if self._stopped:
            return
        if self._setup_busy:
            self._setup_ticks += 1
            if (self._setup_ticks == _WSL_BOOT_TICKS
                    and sys.platform == "win32"):
                self._setup_said_boot = True
                self._set("state", "Starting WSL…")
                try:
                    self._hint.configure(text=_WSL_BOOT_TEXT)
                except (tk.TclError, AttributeError):
                    pass
                self._log("[emulate] starting WSL — the first start after a "
                          "Windows reboot can take a minute")
            try:
                self._timer().after(250, self._setup_drain)
            except tk.TclError:
                self._stopped = True
            return
        if self._setup_said_boot:
            # Back to the built state, not to "Not running": nothing has
            # looked at the rig yet, and the first real poll is 2 s away.
            self._setup_said_boot = False
            self._set("state", "—")
            try:
                self._hint.configure(text="")
            except (tk.TclError, AttributeError):
                pass
        if self._setup_result is not None:
            self._setup_apply(self._setup_result)
            self._setup_result = None
        else:
            # NO ANSWER IS STILL AN ANSWER TO A BUTTON PRESS.  _setup_apply is
            # deliberately not called with None - that would overwrite what the
            # tab already knows with "unknown" on one flaky probe - so the
            # report is done from here instead.  No-op unless Check asked.
            self._setup_report_if_asked(None)

    def _setup_recheck_now(self):
        """“Check setup…”: ask again, and SAY the answer either way.

        The same probe the tab runs at build time and after a WSL restart - not
        a second one, because two ways of asking one question is how this rig
        gets two answers.  What is different is that this one reports: a
        machine with nothing wrong gets a line saying so, which is the whole
        point of a button whose job is to end the ambiguity of silence.

        NOTHING IS CHANGED BY IT.  setupcheck.sh is read-only by design (its
        own header), which is why this button needs no confirmation dialog and
        no root, and why it is safe to leave it there permanently.

        EACH PLATFORM IS ASKED ITS OWN QUESTION.  The button is on every
        platform, but "what does this machine still need" is not one question:
        macOS has no WSL and no packages to install, and ``setup_state``
        answers None there BY DESIGN, so _setup_check returns without starting
        a probe at all - which left this button DISABLED and reading
        "Checking…" for the rest of the session on every Mac, the exact fault
        _setup_report_if_asked exists to prevent.  The Mac gets the probe it
        can answer instead (see _docker_report_if_asked).
        """
        if self._setup_busy:
            return
        try:
            self._check_btn.configure(state=tk.DISABLED, text="Checking…")
        except (tk.TclError, AttributeError):
            pass
        self._log("[emulate] checking what this PC needs…")
        if sys.platform == "darwin":
            self._docker_report_next = True
            # A probe already in flight has a _docker_drain pending, and that
            # drain reports for us - starting a second one would not.
            self._docker_check()
            if not self._docker_busy and self._docker_result is None:
                # It neither started nor had an answer waiting: report what the
                # tab already knows rather than leaving the button stranded.
                self._docker_report_if_asked(self._docker)
            return
        self._setup_report_next = True
        self._setup_check()

    def _setup_report_if_asked(self, facts):
        """★ THE BUTTON ASKED, SO THE BUTTON IS ANSWERED - in the log pane, in
        full, whatever the answer is.

        This is the only path on this panel that reports a HEALTHY machine.
        Every other probe here is a background fact the notice speaks for, and
        the notice says nothing when there is nothing wrong - which is what
        made silence ambiguous and left a black-window user with nothing to
        send.

        ONE PLACE, TWO CALLERS, because ``None`` is an answer too: a probe that
        could not reach WSL never reaches _setup_apply (see _setup_drain), and
        a Check that silently left the button reading "Checking…" for the rest
        of the session would be the same fault this button exists to fix.  The
        flag is cleared first either way, so a failed probe cannot leave it
        armed for the next background poll to spend on a report nobody asked
        for.
        """
        if not getattr(self, "_setup_report_next", False):
            return
        self._setup_report_next = False
        for line in setup_report(facts):
            self._log("[emulate] " + line)
        try:
            self._check_btn.configure(state=tk.NORMAL, text="Check setup…")
        except (tk.TclError, AttributeError):
            pass

    def _setup_apply(self, facts):
        """Put the answer on the tab, or take it away when there is nothing to
        say.  A machine that is ready carries no notice and no button.

        Ready is setup_settled, not setup_ok: a PC that runs the emulator and
        cannot save it still has something to be told, and hiding the notice
        there is how the save-state package would have stayed invisible - the
        button that installs it lives under exactly this notice."""
        self._setup = facts
        self._setup_report_if_asked(facts)
        # THE ONE ANSWER THAT ALSO BELONGS IN THE LOG.  Every other probe on
        # this panel is a background fact the notice speaks for; this one
        # answers a question the user just asked by pressing a button, and the
        # log pane is where they are looking while it runs.  Said once, by the
        # probe the restart armed, and only when the machine really did come
        # back unable to run the emulator - _setup_apply is called on every
        # probe and a line per poll would be noise.
        if getattr(self, "_setup_restart_check", False):
            self._setup_restart_check = False
            if facts and not setup_ok(facts):
                self._log("[emulate] the restart took the 32-bit ARM handler "
                          "with it, so the emulator cannot start until it is "
                          "registered again — press “Set up emulator…” above, "
                          "which does that and makes it survive the next "
                          "restart.")
        try:
            if setup_settled(facts):
                self._setup_btn.pack_forget()
                self._setup_msg.pack_forget()
                self._refit()
                return
            self._setup_msg.configure(
                text=setup_notice(facts, can_fix=sys.platform == "win32"))
            # THE BUTTON GOES AWAY WHEN IT CANNOT HELP.  Leaving it there under
            # a notice that says the package cannot be installed is an
            # invitation to press it, and a tester took it twice - two runs,
            # the same dead end, minutes apart.  The notice carries the route
            # out instead (setup_notice, same condition).
            if sys.platform == "win32" and setup_fixable(facts):
                self._setup_btn.pack(side=tk.LEFT, padx=(6, 0))
            else:
                self._setup_btn.pack_forget()
            self._setup_msg.pack(anchor=tk.W,
                                 **getattr(self, "_setup_pad", {}))
            self._refit()
        except (tk.TclError, AttributeError):
            pass            # the tab was never built, or is being torn down

    def _refit(self):
        """Tell the window this tab is a different height now.

        See _resize_fn.  Best effort by design: the panel is built standalone
        in tests and by anything that is not MainWindow, and a notice that
        appears is worth more than an exception about the frame around it.
        """
        try:
            self._resize_fn()
        except Exception:                                   # noqa: BLE001
            pass

    def _setup_fix(self):
        """Install what is missing and register the ARM handler.

        PROMPTED ONCE, THEN DONE.  This installs Debian packages and writes to
        /etc/wsl.conf inside the user's distro, which is a bigger thing than
        anything else on this tab does - so it names every package and every
        file before it touches one, and a No leaves the machine exactly as it
        was.  It does not ask again per step: a dialog per package is how a
        user stops reading them.

        The work itself is setupfix.sh's.  This panel is a control surface for
        the rig and does not reimplement it - which is also what keeps the
        Windows path and a future Linux one from drifting apart.

        ONE BUTTON, TWO MACHINES.  On a Mac the same press installs the
        container engine, because what "set up the emulator" MEANS there is
        Docker with a Linux machine behind it - see _setup_fix_darwin.
        """
        if self._setup_fixing:
            return
        if sys.platform == "darwin":
            self._setup_fix_darwin()
            return
        if sys.platform != "win32":
            return
        facts = self._setup or {}
        steps = setup_fix_steps(facts)
        if not steps:
            return
        if not messagebox.askyesno(
                "Set up the emulator",
                "This will change your WSL installation:\n\n"
                + "\n\n".join("  •  " + s for s in steps)
                + "\n\nIt runs as root inside WSL, which needs no password. "
                  "Nothing on the Windows side is touched, and nothing is "
                  "removed.\n\nGo ahead?"):
            return

        self._setup_fixing = True
        try:
            self._setup_btn.configure(state=tk.DISABLED, text="Setting up…")
        except tk.TclError:
            pass
        cmd = rig_cmd_root("setupfix.sh")
        self._log("[emulate] %s" % " ".join(cmd))

        def run():
            result = ""
            restart = False
            # The save-state build reports SEPARATELY from the setup's own
            # verdict, because it is a feature and the rest is the emulator:
            # setupfix.sh returns result=ok for a machine that emulates
            # perfectly and could not build criu, and that machine must not be
            # told its setup failed - nor be left thinking its Save buttons
            # will now work.  One line each way.
            criu = ""
            try:
                # Popen and drain, not run(): apt on a cold index takes long
                # enough that a silent minute reads as a hang, and the log pane
                # is where the user is already looking.
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        creationflags=_CREATE_FLAGS)
                for raw in proc.stdout:
                    line = raw.decode("utf-8", "replace").rstrip()
                    if line.startswith("result="):
                        result = line.split("=", 1)[1]
                    elif line.startswith("extras_criu="):
                        criu = line.split("=", 1)[1]
                    elif line == "needs_restart=1":
                        restart = True
                    if line:
                        self._log("[emulate] " + line)
                proc.wait(timeout=60)
            except Exception as exc:                        # noqa: BLE001
                self._log("[emulate] setup failed: %s" % exc)
            if result == "ok":
                self._log("[emulate] this PC can run the emulator now.")
                if restart:
                    self._log("[emulate] systemd was turned on for WSL so the "
                              "ARM handler survives a restart; it takes effect "
                              "the next time WSL starts, and nothing needs "
                              "restarting now.")
            elif result == "nocandidate":
                # A DEAD END, and it has to read like one: retrying this
                # button cannot help, because nothing is failing - the Linux
                # in WSL simply has nowhere to fetch the package from.
                self._log("[emulate] setup cannot finish on this WSL "
                          "installation: the package it needs is not offered "
                          "by any of that Linux's package sources, so trying "
                          "again will say the same thing.")
            else:
                self._log("[emulate] setup did not finish — the emulator will "
                          "probably still fail to start.")
            if criu == "ok":
                self._log("[emulate] criu was built and installed, so save "
                          "states work from the next title you start.")
            elif criu == "failed":
                self._log("[emulate] criu could not be built — see above. "
                          "Everything else is set up: titles start and run, "
                          "and only the Save/Load state buttons stay off.")
            self._setup_fixing = False
            # Re-probe rather than assume it worked: the notice must reflect
            # the machine, not the fact that a button was pressed.
            try:
                self._timer().after(0, self._setup_recheck)
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=run, daemon=True).start()

    def _setup_fix_darwin(self):
        """“Set up emulator…” on a Mac: install the container engine and start
        it, here, without anyone opening Terminal.

        THE MAC HALF OF THE SAME BUTTON.  Windows presses this and gets its
        missing WSL packages installed; a Mac pressed nothing, because the
        engine was a paragraph of instructions instead - and this app is
        perfectly able to run a package manager itself.  macOS's own
        authentication dialog is how the privileged half is agreed to, which is
        the Mac's UAC and exactly what the Windows path leans on.

        PROMPTED ONCE, THEN DONE, like its Windows twin: every step is named
        before anything is touched, and a No leaves the machine as it was.
        """
        plan = engine_setup_plan(self._docker_cli)
        if not plan:
            # Nothing to drive: no package manager, so the honest offer is the
            # Docker Desktop download and not a command to copy.
            self._docker_download()
            return
        if not messagebox.askyesno(
                "Set up the emulator",
                "This Mac needs a container engine before it can emulate. "
                "This will:\n\n"
                + "\n\n".join("  •  " + s for s in plan["steps"])
                + "\n\nIt runs here, in this window, and you can watch it in "
                  "the log below. Nothing is removed.\n\nGo ahead?"):
            return
        self._log("[emulate] setting up a container engine with %s"
                  % plan["manager"])
        self._run_engine_setup([
            ("installing " + plan["label"], plan["install"], plan["admin"]),
            # A CALLABLE, because colima does not exist yet: its path is
            # whatever the step above just put on this disk, and resolving it
            # when the plan was built would resolve it to None.
            ("starting Colima", self._colima_argv, False),
        ])

    def _colima_argv(self):
        """``colima start``, resolved AFTER the install that provided it."""
        colima = which_tool("colima")
        return [colima, "start"] if colima else None

    def _setup_recheck(self):
        try:
            self._setup_btn.configure(state=tk.NORMAL, text="Set up emulator…")
            self._docker_btn.configure(state=tk.NORMAL)
        except (tk.TclError, AttributeError):
            pass
        # Each platform re-asks its OWN question.  _setup_check is a no-op on
        # macOS by design (setup_state answers None there), so without this the
        # Mac's notice would sit there describing the machine as it was before
        # the button it just finished running.
        if sys.platform == "darwin":
            self._docker_check()
        else:
            self._setup_check()

    #: The cost, spelled out beside the section it belongs to.
    #:
    #: IT WAS A CHECKBOX UNTIL 2026-08-10, and David removed it: "remove the
    #: checkbox for 'enable save state' and just keep the tooltip, but put it
    #: on the save states title with a blue (i) button to the right of it like
    #: we normally do."  So the feature is simply ON, and this text stopped
    #: being a warning attached to a choice and became a description of what
    #: the section does — the cost is still stated, because a save really does
    #: freeze the game for a few seconds and every slot really is disk.
    _STATES_TIP = (
        "Save states snapshot the WHOLE running game so you can jump back "
        "to that exact moment later - including in a future session, or "
        "after replacing assets, to compare how a mode looks.\n\n"
        "The cost:\n"
        "• each slot stores roughly 50-150 MB on the WSL disk "
        "(snapshots compress ~20x; a save briefly needs ~1.5 GB free "
        "while it packs)\n"
        "• saving freezes the game and its sound for a few seconds "
        "while the snapshot is written\n"
        "• slots stay on disk until deleted below\n\n"
        "The virtual playfield window carries the Save/Load state controls "
        "for these 10 slots, and Launch above starts the emulator straight "
        "into one.")

    #: The Launch button's honest timeline — from cold, the boot comes
    #: first and the save takes over only once the game is up.
    _LAUNCH_TIP = (
        "Starts the emulator straight into the selected slot.\n\n"
        "From cold, the emulator has to boot first: the game comes up on "
        "screen and runs for a little while (roughly half a minute with "
        "everything warm) before the save state takes over. If the "
        "emulator is already running, the slot loads into it right away — "
        "a load takes about 10–15 seconds either way.")

    def _states_badge(self, parent):
        """The app's round blue ⓘ badge, or a plain marker without the app.

        Same shape as scene_browser's ``_info``: the badge is the window's
        (``_make_round_icon``), and a panel built on its own - every test in
        tests/test_emulate_tab.py - degrades to a label that still carries the
        tooltip. Clicking shows the tip too, because on a short hover or a
        touch screen a badge that does nothing reads as broken.
        """
        if self._badge_fn is None:
            lbl = ttk.Label(parent, text="(i)", foreground="#2f80ed")
            _Tooltip(lbl, self._STATES_TIP, self._theme_fn, place="side")
            return lbl
        badge = self._badge_fn(parent, "i", "#2f80ed", "#5296f2",
                               self._STATES_TIP, lambda: None, size=18,
                               font=("Georgia", 10, "bold italic"),
                               tooltip_place="side")
        badge.bind("<Button-1>", lambda _e: badge.icon_tip.show(), add="+")
        return badge

    def _build_states(self, frame, pad):
        """The save-states section: the slot manager, and what it costs.

        NO ENABLE CHECKBOX, since 2026-08-10 (David: "remove the checkbox for
        'enable save state' and just keep the tooltip, but put it on the save
        states title with a blue (i) button to the right of it").  Save states
        are simply on: every Start uses the checkpointable (root, PAD_PIVOT)
        launch shape, which is the only shape criu can dump, and the cost the
        checkbox used to guard is now stated on the ⓘ beside the title.

        The title is a `labelwidget` rather than `text=` for exactly that
        reason - a LabelFrame's own title is drawn text with nowhere to put a
        button, so the title becomes a small frame holding the words and the
        badge."""
        head = ttk.Frame(frame)
        ttk.Label(head, text="Save states").pack(side=tk.LEFT)
        self._states_badge(head).pack(side=tk.LEFT, padx=(6, 0))
        box = ttk.LabelFrame(frame, labelwidget=head)
        box.pack(fill=tk.X, **pad)

        # The var stays - the window persists it with the project - and is
        # simply held true now, so anything that reads it (or restores an old
        # project that saved it false) agrees with what the launch does.
        if self._states_var is None:
            self._states_var = tk.BooleanVar(value=True)
        try:
            self._states_var.set(True)
        except tk.TclError:
            pass

        wrap = ttk.Frame(box)
        wrap.pack(fill=tk.X, padx=8, pady=(2, 2))
        cols = ("slot", "name", "game", "size", "saved")
        self._slots_tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                        height=4, selectmode="browse")
        for col, head, width, anchor in (
                ("slot", "Slot", 90, tk.W), ("name", "Name", 220, tk.W),
                ("game", "Game", 150, tk.W), ("size", "Size", 80, tk.E),
                ("saved", "Saved", 120, tk.W)):
            self._slots_tree.heading(col, text=head)
            self._slots_tree.column(col, width=width, anchor=anchor,
                                    stretch=(col == "name"))
        self._slots_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        side = ttk.Frame(wrap)
        side.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 0))
        self._slots_btns = []
        for text, cmd in (("Launch", self._slot_launch),
                          ("Refresh", self._slots_refresh),
                          ("Rename…", self._slot_rename),
                          ("Delete", self._slot_delete)):
            b = ttk.Button(side, text=text, width=10, command=cmd)
            b.pack(fill=tk.X, pady=1)
            self._slots_btns.append(b)
        # Side placement, same rule as the toggle's tip: a tip UNDER a
        # control you are about to click covers what you are aiming at.
        _Tooltip(self._slots_btns[0], self._LAUNCH_TIP, self._theme_fn,
                 place="side")

        # NO refresh at build, deliberately: listing the slots is a root
        # wsl.exe spawn, and the first wsl.exe after a Windows reboot boots
        # the whole VM - the exact freeze class the status poller's idle
        # rules exist to avoid. The list populates itself from the first
        # status poll instead (the saves_mtime token in _apply), and after
        # that refreshes whenever a save/pack/delete moves the token.
        self._slots_sum = ttk.Label(box, foreground="#888",
                                    text="The slots appear with the next "
                                         "status poll.")
        self._slots_sum.pack(anchor=tk.W, padx=8, pady=(0, 6))

        if sys.platform != "win32":
            # slots.sh needs root, which only WSL gives for free; on other
            # platforms the manager would be buttons that can only fail.
            for b in self._slots_btns:
                b.configure(state=tk.DISABLED)
            self._slots_sum.configure(
                text="Slot management is available on Windows (WSL).")

    @staticmethod
    def _human(n):
        try:
            n = int(n)
        except (TypeError, ValueError):
            return "?"
        if n >= 1 << 30:
            return "%.1f GB" % (n / float(1 << 30))
        if n >= 1 << 20:
            return "%d MB" % (n // (1 << 20))
        return "%d KB" % max(1, n // (1 << 10))

    def _card_game(self):
        """The title the picked card image runs, or None without a pick.

        Derived from the filename the same way the rig names its card cache:
        everything up to the first `-<digit>` of the basename
        (``star_wars_le-1_30_0.Release.8G.sdcard.raw`` → ``star_wars_le``).
        Titles never contain a dash-digit; versions always start with one.
        A filename that fits no such shape scopes nothing rather than
        guessing wrong."""
        try:
            path = self._src_path.get().strip().strip('"')
        except (AttributeError, tk.TclError):
            return None
        if not path:
            return None
        # Both separators by hand: the path may have been written into the
        # project settings on the other OS, and POSIX basename() does not
        # split on backslashes (CI caught exactly that).
        base = path.replace("\\", "/").rsplit("/", 1)[-1]
        m = re.match(r"([a-z0-9_]+?)-\d", base.lower())
        return m.group(1) if m else None

    def _slots_refresh(self):
        """Re-read the slots as root, off the Tk thread, and repaint."""
        if sys.platform != "win32":
            return
        cmd = rig_cmd_root("slots.sh", "list")

        def run():
            rows, total, free = [], None, None
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=30,
                                   creationflags=_CREATE_FLAGS)
                for ln in (r.stdout or b"").decode("utf8",
                                                   "replace").splitlines():
                    p = ln.split("|")
                    if p[0] == "slot" and len(p) >= 6:
                        rows.append(p[1:6])
                    elif p[0] == "total" and len(p) > 1:
                        total = int(p[1] or 0)
                    elif p[0] == "free" and len(p) > 1:
                        free = int(p[1] or 0)
            except Exception:                               # noqa: BLE001
                pass

            def apply():
                self._slots_rows = rows
                self._slots_total = total
                self._slots_free = free
                self._slots_paint()
            try:
                self._slots_tree.after(0, apply)
            except (tk.TclError, RuntimeError):
                pass          # tab (or the whole interp) is gone

        threading.Thread(target=run, daemon=True).start()

    def _slots_paint(self):
        """Repaint the slot list from the cached rows, SCOPED TO THE PICKED
        CARD'S TITLE.

        David, 2026-08-10: "when switching games, the save state manager
        should change to be per game (you can't load a venom save state for
        john wick)" — a state is a memory image of one title's game binary,
        so a slot for another title is never loadable from here.  With no
        card picked there is nothing to scope to and every slot shows; the
        footer keeps the ALL-slots total either way, because the disk cost
        (item 33's reason to exist) does not care which card is picked.
        Pure repaint from the cache: switching cards never spawns wsl.exe."""
        rows = getattr(self, "_slots_rows", None)
        if rows is None:
            return                      # nothing listed yet; first poll will
        game_now = self._card_game()
        try:
            tree = self._slots_tree
            tree.delete(*tree.get_children())
            shown = hidden = 0
            for name, size, game, label, mtime in rows:
                if game_now and game and game != game_now:
                    hidden += 1
                    continue
                shown += 1
                try:
                    when = time.strftime(
                        "%b %d %H:%M", time.localtime(int(mtime)))
                except (ValueError, OverflowError):
                    when = "?"
                # The iid stays the FULL reference (game/slotN - what
                # slots.sh and loadgame.sh take, item 39's per-game layout);
                # the Slot column shows the bare name, because the Game
                # column already says whose it is.
                tree.insert("", tk.END, iid=name, values=(
                    name.rsplit("/", 1)[-1], label or "", game,
                    self._human(size), when))
            if self._slots_total is None:
                self._slots_sum.configure(
                    text="Could not read the slots - is WSL up?")
            else:
                bits = []
                if game_now:
                    bits.append("%d slot%s for %s" % (
                        shown, "" if shown == 1 else "s", game_now))
                    if hidden:
                        bits.append("%d for other game%s hidden" % (
                            hidden, "" if hidden == 1 else "s"))
                else:
                    bits.append("%d slot%s" % (
                        shown, "" if shown == 1 else "s"))
                bits.append("all slots %s" % self._human(self._slots_total))
                bits.append("free on the WSL disk: %s"
                            % self._human(self._slots_free))
                self._slots_sum.configure(text=" · ".join(bits))
        except tk.TclError:
            pass              # tab torn down while the list was loading

    def _slot_launch(self):
        """Start the emulator INTO the selected slot — or, with a run
        already up, load the slot into it.  The button the tester asked
        for: "it would be great to be able to launch from a savestate
        from here"."""
        slot = self._slot_selected()
        if not slot:
            self._slots_sum.configure(text="Pick a slot to launch first.")
            return
        # A state is a memory image of ONE title's game binary; loading it
        # under another title's card hands the guest a foreign image. The
        # list is already scoped to the picked card, so this guard only
        # fires when no card is picked (the list shows everything) or the
        # slot predates the game column - and then it must speak, not guess.
        try:
            slot_game = str(self._slots_tree.item(slot)["values"][2] or "")
        except (tk.TclError, LookupError, TypeError):
            slot_game = ""
        game_now = self._card_game()
        if slot_game and game_now and slot_game != game_now:
            self._slots_sum.configure(
                text="That save is for %s - pick that title's card first."
                     % slot_game)
            return
        if self._loading or self._starting or self._stopping:
            return
        if self._last_up:
            self._slot_load(slot)
            return
        # Not running: boot the checkpointable shape and let the status
        # poll fire the load once the guest is up (_apply watches
        # _launch_slot).  Launching FROM a save opts this run into save
        # states by definition, whatever the toggle says.
        self._launch_slot = slot
        self._log("[emulate] will load slot '%s' once the game is up" % slot)
        self.start()
        if not self._starting:       # start refused (bad card path, busy)
            self._launch_slot = None

    def _slot_load(self, slot):
        """Run loadgame.sh off the Tk thread and put its story in the log."""
        if self._stopping:
            return
        self._loading = True
        self._set("state", "Loading save…")
        self._log("[emulate] loading slot '%s'" % slot)
        cmd = load_cmd(slot)

        def run():
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=240,
                                   creationflags=_CREATE_FLAGS)
                lines = [ln.strip() for ln in
                         (r.stdout or b"").decode("utf8",
                                                  "replace").splitlines()
                         + (r.stderr or b"").decode("utf8",
                                                    "replace").splitlines()
                         if ln.strip()]
            except Exception:                               # noqa: BLE001
                lines = ["loadgame.sh did not run"]
            for ln in lines[-12:]:
                self._log("[emulate] " + ln)

            def done():
                self._loading = False
            try:
                self._timer().after(0, done)
            except (tk.TclError, RuntimeError):
                self._loading = False

        threading.Thread(target=run, daemon=True).start()

    def _slot_selected(self):
        try:
            sel = self._slots_tree.selection()
        except tk.TclError:
            return None
        return sel[0] if sel else None

    def _slot_rename(self):
        slot = self._slot_selected()
        if not slot:
            self._slots_sum.configure(text="Pick a slot to rename first.")
            return
        top = self._slots_tree.winfo_toplevel()
        dlg = tk.Toplevel(top)
        dlg.title("Rename slot")
        dlg.transient(top)
        dlg.resizable(False, False)
        ttk.Label(dlg, text="Name for '%s':" % slot).pack(
            fill=tk.X, padx=10, pady=(10, 2))
        cur = ""
        try:
            cur = self._slots_tree.item(slot, "values")[1]
        except (tk.TclError, IndexError):
            pass
        var = tk.StringVar(value=cur)
        ent = ttk.Entry(dlg, textvariable=var, width=34)
        ent.pack(padx=10, pady=2)
        rowf = ttk.Frame(dlg)
        rowf.pack(pady=(6, 10))

        def go(_e=None):
            # The label crosses wsl.exe's re-parse into bash argv, and
            # wsl.exe expands $ and backticks even in -e argv (the executor
            # lesson) - so those characters simply never leave the dialog.
            ok = ("abcdefghijklmnopqrstuvwxyz"
                  "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _.()!-")
            label = "".join(ch for ch in var.get() if ch in ok).strip()[:40]
            dlg.destroy()
            self._slot_cmd(["label", slot] + ([label] if label else []))

        ttk.Button(rowf, text="Rename", width=10, command=go).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(rowf, text="Cancel", width=10, command=dlg.destroy).pack(
            side=tk.LEFT, padx=4)
        ent.bind("<Return>", go)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        ent.focus_set()
        dlg.update_idletasks()
        dlg.geometry("+%d+%d" % (
            top.winfo_rootx() + 240, top.winfo_rooty() + 240))
        dlg.grab_set()

    def _slot_delete(self):
        slot = self._slot_selected()
        if not slot:
            self._slots_sum.configure(text="Pick a slot to delete first.")
            return
        size = ""
        try:
            size = " (%s)" % self._slots_tree.item(slot, "values")[3]
        except (tk.TclError, IndexError):
            pass
        if not messagebox.askyesno(
                "Delete save state",
                "Delete slot '%s'%s?\n\nThe saved game in it is gone for "
                "good." % (slot, size),
                parent=self._slots_tree.winfo_toplevel()):
            return
        self._slot_cmd(["delete", slot])

    def _slot_cmd(self, args):
        """Run one slots.sh action off the Tk thread, then refresh."""
        cmd = rig_cmd_root("slots.sh", *args)
        for b in self._slots_btns:
            b.configure(state=tk.DISABLED)

        def run():
            out = ""
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=60,
                                   creationflags=_CREATE_FLAGS)
                out = (r.stdout or b"").decode("utf8", "replace").strip()
            except Exception:                               # noqa: BLE001
                out = "slots.sh did not run"
            if out:
                self._log("[emulate] %s" % out.splitlines()[-1])

            def apply():
                try:
                    for b in self._slots_btns:
                        b.configure(state=tk.NORMAL)
                except tk.TclError:
                    return
                self._slots_refresh()
            try:
                self._slots_tree.after(0, apply)
            except (tk.TclError, RuntimeError):
                pass          # tab (or the whole interp) is gone

        threading.Thread(target=run, daemon=True).start()

    def _build_source(self, frame, pad):
        """The card image to run.  One box and a Browse button.

        A CARD IMAGE IS THE ONLY SOURCE, and why the other two went is worth
        keeping: an "extracted folder" cannot work, because PAD extracts ASSETS
        and the rig needs a title directory - a ``game`` binary with ``assets/``
        and the node ``.hex`` files beside it - which is a different shape, so
        it could only ever fail.  A "rig's own copy" option exposed whatever
        happened to be unpacked inside the rig on this machine, which is
        internal state no user can create or reason about.

        There are no "use the project's image" buttons either.  The user picks
        the image; stock or modded is their business, and a pair of buttons
        guessing at it was a second way to set one field for no gain.  The
        picked path IS remembered with the project (the app stores it in the
        anchor and restores it on project load) — remembering a choice is not
        the same as guessing one.
        """
        box = ttk.LabelFrame(frame, text="Card image to run")
        box.pack(fill=tk.X, **pad)
        self._src_path = self._card_var if self._card_var is not None \
            else tk.StringVar()
        # Switching cards re-scopes the save-state list to the new title
        # (client-side repaint from the cache — no wsl.exe involved). The
        # guard: the states box may build after this one, or the trace may
        # fire during teardown.
        try:
            self._src_path.trace_add(
                "write", lambda *_a: self._slots_paint()
                if hasattr(self, "_slots_tree") else None)
        except (AttributeError, tk.TclError):
            pass
        row = ttk.Frame(box)
        row.pack(fill=tk.X, padx=8, pady=6)
        self._src_entry = ttk.Entry(row, textvariable=self._src_path)
        self._src_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse…", width=10,
                   command=self._browse).pack(side=tk.LEFT, padx=(6, 0))

    def _browse(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Pick a Spike 2 card image",
            filetypes=[("Card images", "*.raw *.img"), ("All files", "*.*")])
        if path:
            self._src_path.set(path)

    def _source_env(self):
        """The environment for watch.sh, or None with a reason already shown.

        Validated HERE rather than in the rig: a bad path should be a sentence
        on the tab, not a shell script exiting into the log pane.
        """
        path = self._src_path.get().strip().strip('"')
        if not path:
            self._hint.configure(
                text="Pick a card image first — the one on the Extract tab, the "
                     "one Write builds, or any other Spike 2 card.")
            return None
        if not os.path.isfile(path):
            self._hint.configure(text="No such image: %s" % path)
            return None
        return ["PAD_CARD=%s" % _wsl_path(path)]

    def _on_destroy(self, event=None):
        # <Destroy> fires for every descendant too; only the frame itself means
        # the tab is really going.  Compared by widget path rather than by
        # identity so this still holds if tkinter ever hands the callback a bare
        # Tcl name instead of a resolved widget.
        if event is not None and str(event.widget) != str(self._parent):
            return
        self._stopped = True
        if self._poll_job is not None:
            try:
                self._timer().after_cancel(self._poll_job)
            except (tk.TclError, ValueError):
                pass
            self._poll_job = None

    def _on_volume_change(self, *_args):
        """Volume/Mute changed (item 56) - write the live control file.

        No debounce: a Scale drag fires this on every tick and the write is a
        few bytes, atomic, so the speakers are meant to track the handle the
        way any other app's volume slider does, not settle after a pause.
        Called with no run up too (build() seeds it once, at construction) -
        harmless either way, since it is only ever read by a padplay.py that
        may or may not currently exist.

        ``*_args`` because ``ttk.Scale``'s ``command`` calls back with the new
        value as a string; the Checkbutton's ``command`` calls back with
        nothing.  Both are ignored — the vars themselves are already current
        by the time either fires."""
        gain = max(0.0, min(1.0, self._volume_var.get() / 100.0))
        _write_audio_ctl(gain, bool(self._mute_var.get()))

    # ------------------------------------------------------------------
    # start / stop
    # ------------------------------------------------------------------

    def _toggle(self):
        """The one button.  Dispatches on what is actually running rather than
        on what the label says: the label is refreshed by a 1 s poll, so a run
        that died a moment ago could still read "Stop".  Both branches are
        already no-ops when they do not apply, so the worst case is nothing."""
        if self._starting or self._stopping:
            return
        if self._last_up:
            self.stop()
        else:
            self.start()

    def _run_label(self, up, busy):
        """Sole owner of the run button's text and state."""
        try:
            if busy:
                self._run_btn.configure(
                    state=tk.DISABLED,
                    text="Stopping…" if self._stopping else "Starting…")
            elif up:
                self._run_btn.configure(state=tk.NORMAL, text="Stop emulator")
            else:
                self._run_btn.configure(
                    state=tk.NORMAL if rig_available() else tk.DISABLED,
                    text="Start emulator")
        except tk.TclError:
            pass

    def start(self):
        if self._starting or self._stopping or not rig_available():
            return
        self._starting = True
        self._run_label(False, True)
        self._set("state", "Starting…")
        # Validate the source BEFORE anything is launched, and put the reason
        # on the tab.  A bad path reaching the rig becomes a shell error in the
        # log pane, which is the wrong place to read it.
        src = self._source_env()
        if src is None:
            self._starting = False
            self._run_label(False, False)
            self._set("state", "Not running")
            return
        # Item 56: padplay.py polls this file live (see its poll_gain()), so
        # naming it here is what lets the volume/mute knob reach a run this
        # tab starts - build() already wrote the file itself, this only
        # tells the rig where it is.  Unconditional, unlike Sound/Auto-attract
        # below: a muted or half-volume run is still worth having the file
        # for, in case Mute gets unticked mid-run.
        env = ["PAD_AUDIO_DUMP=30", "PAD_AUDIO_CTL=" + AUDIO_CTL_FILE] + src
        if not self._audio_var.get():
            env.append("PAD_AUDIO=0")
        if not self._auto_var.get():
            env.append("PAD_AUTO_ATTRACT=0")
        # ALWAYS THE CHECKPOINTABLE SHAPE (root, PAD_PIVOT) since the enable
        # checkbox was removed on 2026-08-10. It used to be the toggle's
        # answer, with a pending launch-from-slot forcing it anyway because
        # loading a save NEEDS this shape; with no toggle there is nothing
        # left to ask.
        states = True

        def run():
            # DOCKER IS CHECKED HERE, in the worker, so a slow probe cannot
            # freeze the tab - and it is checked on every Start rather than
            # trusted from build time, because the user may have installed or
            # started it in the meantime.  Without this the whole of "you need
            # Docker" was one line of padbox.sh's stderr in the log pane, after
            # the button had already said "Starting…".
            if sys.platform == "darwin":
                state = self._docker_probe()
                if state != "ok":
                    self._log("[emulate] Docker is %s. The emulator runs in a "
                              "container on macOS, so it cannot start without "
                              "it." % {
                                  "absent": "not installed",
                                  "engineless": "installed, but nothing on "
                                                "this Mac can run a container",
                              }.get(state, "not running"))
                    # QUEUED BEFORE the flag is cleared, so anything waiting on
                    # "no longer starting" can be sure the tab has already been
                    # told why.
                    try:
                        self._timer().after(
                            0, lambda: (self._docker_apply(state),
                                        self._set("state", "Not running"),
                                        self._run_label(False, False)))
                    except (tk.TclError, RuntimeError):
                        pass
                    finally:
                        self._starting = False
                    return
            # THE COMMAND IS BUILT IN HERE, not before the thread.  On
            # Windows watch_cmd() asks WSL for the desktop user's home
            # (wsl_home: two wsl.exe probes, 30 s timeout each), and the
            # first wsl.exe after a Windows reboot boots the whole WSL VM.
            # Built on the main thread, that was the window frozen solid for
            # the boot - David hit it on 2026-08-09 and read it as a crash.
            cmd = watch_cmd(self.BACKSTOP_MIN, env, savestates=states)
            self._log("[emulate] %s" % " ".join(cmd))
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=_CREATE_FLAGS)
            except Exception as exc:                    # noqa: BLE001
                self._log("[emulate] failed to start: %s" % exc)
                self._proc = None
                self._starting = False
                return
            # Launched.  Clear _starting HERE, not when the process ends: this
            # thread now lives for the whole session draining output, and
            # holding a flag across it is what stopped Stop from working.
            self._starting = False
            self._started_here = True
            try:
                # Drain so the pipe cannot fill and block the rig; the rig keeps
                # its own log, this is only for PAD's log pane.
                for raw in self._proc.stdout:
                    line = raw.decode("utf-8", "replace").rstrip()
                    self._log("[emulate] " + line)
                    # ...and one line in it is addressed to US: the run cannot
                    # start a Windows program on this machine and is asking
                    # PAD to open the playfield window.  Done on THIS thread,
                    # which is the drain thread and not the UI one — it is a
                    # Popen, and the interpreter it starts may take a moment
                    # to appear.
                    fields = playfield_launch(line)
                    if fields:
                        self._open_playfield(fields)
            except Exception:                           # noqa: BLE001
                pass                                    # pipe closed under us
            finally:
                self._proc = None

        threading.Thread(target=run, daemon=True).start()

    def _open_playfield(self, fields):
        """Open the virtual playfield window, because the run cannot.

        See ``_PLAYFIELD_LAUNCH`` for why a machine ends up here: WSL interop
        switched off (or no ``pythonw.exe`` on the distro's PATH), which stops
        Linux starting a Windows program and stops nothing else.

        THE PATHS COME FROM THE RUN, ALREADY TRANSLATED.  ``playfield.py`` can
        work them out for itself — padpath.py asks ``wslpath`` — but watch.sh
        knows them for certain, including a rootfs the user moved with
        PAD_ROOT, and it costs two ~200 ms round trips not to be told.  This is
        the same pair WSLENV's ``/p`` would have carried across the interop
        exec that is not happening.

        Failures are logged, never raised: this runs on the thread draining
        watch.sh's output, and a run whose playfield could not open is a run
        with a game window, sound and everything else — it is not a reason to
        stop reading the log.
        """
        if sys.platform != "win32":
            return
        # ALIVE, not merely remembered.  A run that ended on its own (the game
        # window closed) leaves the handle behind while the window itself has
        # already gone — playfield.py closes when the LED block disappears —
        # and reading that stale handle as "one is already open" is a second
        # Start with no playfield at all.
        if self._pf_proc is not None and self._pf_proc.poll() is None:
            return
        py = windows_python()
        if not py:
            self._log("[emulate] the run asked PAD to open the playfield "
                      "window, and there is no Python here to open it with. "
                      "The game itself is unaffected.")
            return
        script = os.path.join(rig_dir(), "playfield.py")
        cmd = [py, script, fields["game"]]
        if fields.get("savestates") == "1":
            cmd.append("--savestates")
        env = dict(os.environ)
        for key, name in (("root", "PAD_ROOT"), ("tables", "PAD_TABLES")):
            if fields.get(key):
                env[name] = fields[key]
        try:
            self._pf_proc = subprocess.Popen(cmd, env=env,
                                             creationflags=_CREATE_FLAGS)
            self._log("[emulate] opened the virtual playfield window here — "
                      "this WSL cannot start Windows programs itself.")
        except Exception as exc:                            # noqa: BLE001
            self._pf_proc = None
            self._log("[emulate] could not open the playfield window: %s" % exc)

    def _close_playfield(self, grace=8):
        """Close a playfield window PAD opened, once the run is down.

        ONLY ONE PAD OPENED.  The ordinary window is watch.sh's child through
        interop and watch.sh tears it down; this is the other case, where the
        rig's forced close (a ``powershell.exe`` call) is itself interop and
        therefore the one thing that machine cannot do.  Whoever owns the
        launch owns the teardown.

        THE POLITE EXIT GETS ITS CHANCE FIRST, and it is worth having: the
        window saves its position on the way out, and it goes by itself as
        soon as the run's LED block disappears (playfield.py's ``emu_gone``,
        ~2 s).  Killing it at once would lose that on every single stop.
        ``grace`` is shorter on app quit, where this blocks the main thread
        and the LED block has already gone.
        """
        proc, self._pf_proc = self._pf_proc, None
        if proc is None:
            return
        try:
            proc.wait(timeout=grace)
        except Exception:                                   # noqa: BLE001
            try:
                proc.kill()
                self._log("[emulate] the playfield window did not close "
                          "itself; closed it here.")
            except Exception:                               # noqa: BLE001
                pass

    def stop(self):
        """Kill everything and VERIFY.  Never assume: the rig's own killgame.sh
        SIGKILLs all five processes and reports what survived."""
        if self._stopping:
            return
        self._stopping = True
        # A manual stop cancels any launch-from-slot still waiting for the
        # boot — the load must not fire into the NEXT run the user starts.
        self._launch_slot = None
        self._run_label(True, True)
        self._set("state", "Stopping…")

        def run():
            needs_restart = False
            try:
                out = subprocess.run(
                    kill_cmd(),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=60, creationflags=_CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    self._log("[emulate] " + line)
                    if _NEEDS_WSL_RESTART in line:
                        needs_restart = True
            except Exception as exc:                    # noqa: BLE001
                self._log("[emulate] stop failed: %s" % exc)
            # watch.sh is still sitting in its own poll loop; it notices the
            # renderer has gone and runs its teardown (which also removes the
            # audio fifo). Wait briefly for that rather than racing it.
            proc = self._proc
            if proc is not None:
                try:
                    proc.wait(timeout=20)
                except Exception:                       # noqa: BLE001
                    try:
                        proc.kill()
                    except Exception:                   # noqa: BLE001
                        pass
            # AFTER the rig's own teardown, never before: removing the LED
            # block is what tells the window to close itself, and that exit is
            # the one that saves its position.  Only ever a window PAD opened.
            self._close_playfield()
            self._stopping = False
            # killgame.sh says the survivors are beyond anything inside WSL.
            # Offer the Windows-side cure ON THE MAIN THREAD - this is a
            # dialog, and Tk is not thread safe (see _log).
            if needs_restart and sys.platform == "win32":
                try:
                    self._timer().after(0, self._offer_wsl_restart)
                except (tk.TclError, RuntimeError):
                    pass

        threading.Thread(target=run, daemon=True).start()

    def _offer_wsl_restart(self):
        """Stop ran killgame.sh and leftovers survived that nothing inside WSL
        can clear - killgame.sh said so with its restart token.  Offer the one
        cure, because a user cannot be expected to read `wsl --shutdown` out
        of a log pane: measured 2026-08-09, the wedge held Start AND Stop dead
        (zombie guests kept the process count nonzero, so the button stayed on
        Stop and Stop killed nothing) with "Restart WSL…" greyed out for the
        same reason.  This dialog is that button's confirmation, minus the
        parts the wedge has already answered: there is no run to protect (the
        rig is already torn down to unkillable remains) and no second killgame
        to run (it just ran; its verdict is why we are here)."""
        if self._resetting or self._stopped:
            return
        if not messagebox.askyesno(
                "Stop emulator",
                "The emulator did not stop cleanly.\n\n"
                "Some of its processes are stuck in a way that cannot be "
                "fixed from inside WSL - Windows is holding on to processes "
                "that are already dead.  They will keep the emulator looking "
                "half-running and may block the next start.\n\n"
                "Restarting WSL clears them.  This closes EVERYTHING running "
                "in WSL, not just the emulator.  Nothing on disk is lost, "
                "and WSL starts again by itself the next time it is used.\n\n"
                "Restart WSL now?"):
            self._log("[emulate] leftovers kept; press Stop again for this "
                      "offer, or run `wsl --shutdown` yourself when ready")
            return
        self._restart_wsl("clearing stuck emulator processes")

    def _audio_reset(self):
        """Restart WSL: the cure for a stranded window, and for the old crackle.

        NOT A FIX FOR ANYTHING IN THE RIG, and the dialog says so, because
        reaching for this when the emulator really is at fault would only hide
        the problem for a while.  The two faults it does address both live
        outside WSL's reach:

        * a window WSLg keeps painting after its X client has gone.  Clicking
          its X does nothing (nothing is left to receive the close) and msrdc
          refuses Stop-Process, so a restart of WSL is the only way out.
        * crackle on the WSLg audio fallback.  Measured 2026-08-05: a pure sine
          came back mathematically perfect off the sink's own monitor (0 of
          280490 samples off a sine) while it was audibly breaking up in the
          room, so nothing inside WSL can see it and no self-test could catch
          it.  A restart rebuilds the PulseAudio server and that channel.

        Terminates EVERY WSL distro, so it asks first and refuses while a run
        is up (the poll greys the button, and this re-checks).
        """
        if self._resetting or self._starting or self._stopping:
            return
        if not rig_available():
            return
        if self._last_up:
            messagebox.showinfo(
                "Restart WSL",
                "Stop the emulator first.\n\n"
                "This restarts WSL, which would kill the running game without "
                "letting it shut down cleanly.")
            return
        if not messagebox.askyesno(
                "Restart WSL",
                "Restart WSL?\n\n"
                "This is the cure for two things the emulator cannot fix "
                "itself:\n\n"
                "  • an emulator window left on screen that will not close. "
                "Its X button does nothing because nothing is behind it any "
                "more.\n"
                "  • crackly or stuttery sound, which is usually WSL's audio "
                "link to Windows going bad after a long session.\n\n"
                "This closes EVERYTHING running in WSL, not just the "
                "emulator. Nothing on disk is lost, and WSL starts again by "
                "itself the next time it is used.\n\n"
                "Restart WSL now?"):
            return

        # Tear the rig down first even though the button is only enabled when
        # nothing is up: a terminal-started run the poll has not seen yet
        # would otherwise be killed by the shutdown with no teardown at all.
        self._restart_wsl("rebuilding the audio path and window link",
                          pre_kill=True)

    #: playfield.py's own state file, by the same rule playfield.py builds it
    #: (``~/.pad_playfield.json``).  Named here rather than imported because
    #: that module is a rig script the app never loads - it runs as its own
    #: process, on the other side of an interop hop.
    PF_STATE = os.path.join(os.path.expanduser("~"), ".pad_playfield.json")

    @classmethod
    def _forget_playfield_pos(cls):
        """Drop ``playfield_pos`` from the WINDOWS-side playfield state.

        THE HALF winreset.sh CANNOT REACH, and the split is a property of the
        machine rather than a choice.  Under WSL there is no Tk inside the
        distro at all, so watch.sh launches playfield.py as a *Windows*
        process through interop - its ``~`` is the Windows profile, a home no
        script running inside WSL can see.  On a Linux desktop and in the
        macOS container the playfield is a local Tk process instead, its state
        file sits in the rig's own home, and winreset.sh clears it there; this
        then finds a file that does not exist and does nothing.  So exactly
        one side acts on each platform, and neither has to know which.

        Only that one key: the file holds other playfield state, and taking it
        all would be a second reset nobody asked for.  Returns a line for the
        log, or None when there was nothing to forget.
        """
        try:
            with open(cls.PF_STATE) as f:
                st = json.load(f)
        except Exception:                                   # noqa: BLE001
            return None      # absent, unreadable, or not JSON: leave it alone
        if not isinstance(st, dict):
            return None
        pos = st.pop("playfield_pos", None)
        if pos is None:
            return None
        try:
            with open(cls.PF_STATE, "w") as f:
                json.dump(st, f, indent=1)
        except Exception as exc:                            # noqa: BLE001
            return "could not rewrite %s: %s" % (cls.PF_STATE, exc)
        return "forgot the playfield window position %s" % (pos,)

    def _window_reset(self):
        """Put the emulator windows back where a first-ever run would open them.

        THE FAULT IT EXISTS FOR: the remembered geometry is restored with no
        on-screen check anywhere.  padglhost XMoveWindows the game and legend
        windows to whatever ``~/.pad_windows`` says and CREATES the game window
        at the saved size, and playfield.py's own guard measures against the
        PRIMARY monitor, so a legitimate second-screen position is thrown away
        while a genuinely off-every-monitor one is not.  Either way a window
        that lands outside the desktop cannot be dragged back, and before this
        button the only cure was knowing ``~/.pad_windows`` existed and editing
        it inside WSL.

        REFUSES WHILE A RUN IS UP, and that is not timidity - it is the only
        honest answer.  padglhost re-saves the geometry as the windows move and
        again when it closes, so a reset now is written straight back at the
        end of this run; the button would report success and the next start
        would come up in the same wrong place.  Moving a LIVE run's windows is
        a different job that this cannot do at all: it can only be done from
        inside X, per the standing non-negotiable, and padglhost has no channel
        to ask it through.  winreset.sh carries the same gate off its own
        reading of ``alive.sh --procs``, so a command-line caller is refused
        too and the rule lives in one place; this one is early UX, not the
        authority.
        """
        if self._winresetting or self._starting or self._stopping:
            return
        if not rig_available():
            return
        if self._last_up:
            messagebox.showinfo(
                "Reset windows",
                "Stop the emulator first.\n\n"
                "The emulator saves where its windows are as you move them, "
                "and again when it closes — so resetting now would be undone "
                "at the end of this run.")
            return
        if not messagebox.askyesno(
                "Reset windows",
                "Forget where the emulator windows were?\n\n"
                "The next time you start the emulator, the game window and "
                "the virtual playfield open at their default position and "
                "size.\n\n"
                "Use this when a window has ended up off the screen — after "
                "unplugging a second monitor, for example — and cannot be "
                "dragged back.\n\n"
                "Nothing else is affected: no save state, no setting, and no "
                "running game.\n\n"
                "Reset the window positions now?"):
            return

        self._winresetting = True
        self._winreset_btn.configure(state=tk.DISABLED)

        def run():
            try:
                out = subprocess.run(rig_cmd("winreset.sh"),
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT,
                                     timeout=120, creationflags=_CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    if line.strip():
                        self._log("[emulate] " + line.strip())
                # The Windows-side half, after the rig-side one: if the script
                # refused (a run came up between the poll and the click) this
                # would otherwise clear the playfield's position on its own and
                # leave the two files disagreeing about what was reset.
                if out.returncode == 0:
                    msg = self._forget_playfield_pos()
                    if msg:
                        self._log("[emulate] " + msg)
            except Exception as exc:                        # noqa: BLE001
                self._log("[emulate] reset windows failed: %s" % exc)
            finally:
                self._winresetting = False

        threading.Thread(target=run, daemon=True).start()

    def _restart_wsl(self, why, pre_kill=False):
        """The one `wsl --shutdown` worker, shared by the two doors that reach
        it: the "Restart WSL…" button (pre_kill=True - a terminal-started run
        deserves a teardown before the VM dies under it) and Stop's
        stuck-process offer (pre_kill=False - killgame.sh just ran, and its
        failure to finish is the reason we are here).

        ...AND IT RE-PROBES AFTERWARDS, because this button is one of the two
        ways a machine that could emulate a minute ago stops being one.  The
        kernel's 32-bit ARM registration lives in the RUNNING kernel; systemd
        puts it back at boot, and a WSL distro started without systemd loses it
        on every restart.  So the app would shut WSL down, say "start the
        emulator again when ready", and leave a tab still showing the machine
        it probed at launch - notice hidden, "Set up emulator…" hidden - while
        the next Start died at

            chroot: failed to run command '/bin/sh': Exec format error

        A tester walked exactly that path on 2026-08-12: a display fault, this
        button as the cure, and then a wall of guest log text about binfmt and
        /etc/wsl.conf that he was left to act on by hand - past a button that
        does the whole of it.  The probe costs one wsl.exe, which the status
        poll spends every 10 s anyway.
        """
        self._resetting = True
        self._fixaud_btn.configure(state=tk.DISABLED)
        self._set("state", "Restarting WSL…")

        def run():
            try:
                if pre_kill:
                    subprocess.run(kill_cmd(),
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   timeout=60, creationflags=_CREATE_FLAGS)
                self._log("[emulate] restarting WSL: %s" % why)
                out = subprocess.run(["wsl.exe", "--shutdown"],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT,
                                     timeout=120, creationflags=_CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    if line.strip():
                        self._log("[emulate] " + line)
                self._log("[emulate] WSL is down; it restarts by itself on "
                          "next use. Start the emulator again when ready.")
            except Exception as exc:                    # noqa: BLE001
                self._log("[emulate] WSL restart failed: %s" % exc)
            finally:
                self._resetting = False
                # ASK THE MACHINE WHAT THE RESTART LEFT, rather than assume it
                # left everything.  See this method's docstring: on a distro
                # without systemd the ARM handler has just gone, and the whole
                # point is that the tab says so HERE - with the button that
                # puts it back - instead of the next Start saying it in guest
                # log text.  Back on the main thread: _setup_check's drain
                # touches widgets.
                try:
                    self._timer().after(0, self._setup_after_restart)
                except (tk.TclError, RuntimeError):
                    pass

        threading.Thread(target=run, daemon=True).start()

    def _setup_after_restart(self):
        """Re-probe once WSL has been shut down, and SAY that is why.

        The line goes up before the probe rather than after it because the
        probe is what boots WSL back up: on a cold VM that is tens of seconds
        of "Starting WSL…" which would otherwise look like the restart itself
        hanging.  A machine that came back intact gets this one line and
        nothing else - _setup_apply keeps its notice hidden.
        """
        if self._stopped:
            return
        self._log("[emulate] checking what the restart left behind: the "
                  "kernel's 32-bit ARM handler only survives one on a distro "
                  "that boots systemd.")
        self._setup_restart_check = True
        self._setup_check()

    def shutdown_sync(self):
        """Take the whole emulator down because PAD is quitting.  BLOCKING, on
        the main thread, bounded by the subprocess timeout — quitting the app
        must close the game window and the virtual playfield, not leave them
        orphaned behind a vanished control surface.

        Runs whenever this panel started a run OR the last status poll saw one
        (so a terminal-started run is taken down too — the user asked for
        "quitting PAD shuts down all the emulator windows", not "the ones PAD
        started").  killgame.sh SIGKILLs all five processes and removes the
        LED block, which is the playfield window's signal to close itself;
        the game window dies with padglhost.

        ...EXCEPT ON THE ONE MACHINE WHERE THAT SIGNAL IS ALL THERE IS.  When
        PAD opened the playfield itself (interop off — see _open_playfield),
        the rig's forced close cannot run, so this closes it here.  Quitting
        PAD leaving a playfield window on the desktop is exactly the orphan
        this method exists to prevent.
        """
        if not (self._proc is not None or self._last_up):
            self._close_playfield(grace=3)
            return
        if not rig_available():
            self._close_playfield(grace=3)
            return
        self._stopped = True             # no more polls into a dying Tk
        try:
            subprocess.run(
                kill_cmd(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=25, creationflags=_CREATE_FLAGS)
        except Exception:                               # noqa: BLE001
            pass                     # quitting anyway; best effort by design
        self._close_playfield(grace=3)

    # ------------------------------------------------------------------
    # status polling
    # ------------------------------------------------------------------

    def _schedule_poll(self, ms=None):
        if self._stopped:
            return
        if ms is None:
            if not self._polled_once:
                # The FIRST answer is what fills the save-state list (the
                # saves_mtime token), and a user looks at that list the
                # moment the app opens — "when i load the app, the save
                # states are empty until i refresh" (tester, 2026-08-10).
                # The 10 s idle cadence made that true for ~11 s per
                # launch.  Until one poll has come back, retry on a short
                # TIMER — the deferral branches in _poll spawn nothing, so
                # this costs Tk ticks, not wsl.exe processes, and the one
                # real spawn happens right behind the setup probe.
                ms = 700
            else:
                # A run in progress is worth watching closely; an idle rig
                # is not worth a wsl.exe every two seconds for the whole
                # time the app is open.  See POLL_IDLE_MS.
                ms = self.POLL_MS if self._last_up else self.POLL_IDLE_MS
        try:
            self._poll_job = self._timer().after(ms, self._poll)
        except tk.TclError:
            self._stopped = True

    def _poll(self):
        self._poll_job = None
        if self._stopped:
            return
        # RE-ASKED ONLY WHILE THE ANSWER IS BAD, every ~10 s.  A user who
        # installs Docker Desktop with this tab open should see the notice go
        # away, and a machine that already has it should not pay for a `docker
        # info` every two seconds to be told what it was told at build time.
        if sys.platform == "darwin" and self._docker != "ok":
            self._docker_ticks += 1
            if self._docker_ticks % 5 == 1:
                self._docker_check()
            # AND DO NOT POLL THROUGH IT.  status.sh reaches the rig via
            # padbox.sh, so on macOS every poll is a `docker` invocation - and
            # with no Docker to invoke that is a process spawned every two
            # seconds to fail in exactly the same way.  `None` is "the first
            # probe has not answered yet", which is not the same as "no", so it
            # still polls.
            if self._docker is not None:
                # macOS with no Docker: nothing will answer, so settle to
                # the idle cadence rather than fast-retrying forever.
                self._polled_once = True
                self._schedule_poll()
                return
        # AND NOT THROUGH A BOOTING WSL EITHER.  While the setup probe is
        # still out, wsl.exe may be booting the whole VM (the first call
        # after a Windows reboot does exactly that).  Each poll through it
        # would stack another 20 s worker behind the boot, and the first one
        # back would time out empty and write "Not running" over the
        # "Starting WSL" line - a claim about a machine nobody has seen yet.
        if self._setup_busy:
            self._schedule_poll()
            return
        if not rig_available():
            # No rig on this machine: there is nothing a fast first poll
            # could fetch, so settle to the idle cadence.
            self._polled_once = True
            self._schedule_poll()
            return
        # ★ ONE STATUS POLL AT A TIME, AND NONE WHILE THE SETUP PROBE IS OUT.
        #
        # This loop used to start a worker and reschedule itself in the same
        # breath, so the NEXT poll fired 2 s later whether or not the last one
        # had answered.  Each worker is a `wsl.exe` spawn with a 20 s timeout,
        # and the first wsl.exe after a Windows reboot boots the whole WSL VM
        # — so a cold start stacked up to ten concurrent WSL spawns, each one
        # contending with the boot the others were waiting on.  Measured
        # 2026-08-09 on a warm machine: 21 wsl.exe spawns in the first 45 s of
        # app life, from a tab nobody had opened.  Cold, that is what left the
        # window "Not Responding" for tens of seconds after a reboot, and it
        # was blamed on three other things (a GUI release, an OneDrive stat,
        # the log pane) before anyone counted the spawns.
        #
        # Skipping rather than queueing is right: a status poll is a snapshot,
        # and the answer a stacked poll would have given is the one the
        # in-flight poll is already fetching.
        if self._poll_busy or self._setup_busy:
            self._schedule_poll()
            return
        self._poll_busy = True

        def run():
            try:
                out = subprocess.run(
                    rig_cmd("status.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=20, creationflags=_CREATE_FLAGS)
                text = out.stdout.decode("utf-8", "replace")
            except Exception:                            # noqa: BLE001
                text = ""
            info = parse_status(text)
            # Tk is not thread safe — every widget touch goes back to the main
            # loop.  Doing it from the worker is the exact bug that froze the
            # Partition Explorer's extract.  The busy flag is cleared THERE
            # too, so it is only ever written on the main thread and a slow
            # poll cannot be lapped by the timer that scheduled it.
            if self._stopped:
                self._poll_busy = False
                return

            def apply_and_release():
                self._poll_busy = False
                # One poll has answered (even emptily): the fast first-poll
                # retry has done its job, drop to the normal cadence.
                self._polled_once = True
                self._apply(info)

            try:
                self._timer().after(0, apply_and_release)
            except (tk.TclError, RuntimeError):
                self._poll_busy = False

        threading.Thread(target=run, daemon=True).start()
        self._schedule_poll()

    def _apply(self, info):
        try:
            label, hint = state_text(info)
            self._set("state", label)
            self._hint.configure(text=hint)

            procs = info.get("procs", "0")
            self._set("procs", "%s running%s" % (
                procs, "  (all stopped)" if procs == "0" else ""))

            if info.get("running") == "1":
                self._set("cpu", "%s%% of one core, %s MB"
                          % (info.get("cpu", "?"), info.get("rss", "?")))
                self._set("host", "%s%% CPU, %s fps"
                          % (info.get("host_cpu", "?"), info.get("fps", "—")))
                pcm = info.get("pcm")
                if pcm is None:
                    self._set("audio", "not sampled")
                else:
                    drop = info.get("drop", "0")
                    self._set("audio", "%s frames played, %s dropped%s" % (
                        pcm, drop,
                        "" if drop == "0" else "   <-- dropping"))
            else:
                for k in ("cpu", "host", "audio"):
                    self._set(k, "—")

            # Event-based slot list (tester: "i shouldn't have to press
            # Refresh... it should be event based"): status.sh publishes
            # when the saves last changed, and the list re-reads itself
            # whenever the token moves - a playfield save, a CLI pack or
            # delete - and on the FIRST sighting, which is what populates
            # the list at startup without a spawn of its own (the status
            # poll that carried the token already paid for one).
            tok = info.get("saves_mtime")
            if tok is not None and tok != self._saves_token:
                self._saves_token = tok
                self._slots_refresh()

            # A pending launch-from-slot: Launch was pressed with the
            # emulator down, and the boot it started is now up — fire the
            # load ONCE, after a short settle so the freshly-started
            # helpers (node bus, video host, card mount) finish coming up.
            # Killing a guest that is milliseconds old would race
            # run_game's own bring-up.
            if (self._launch_slot and not self._loading
                    and info.get("running") == "1"):
                slot, self._launch_slot = self._launch_slot, None
                self._timer().after(4000, lambda: self._slot_load(slot))

            busy = self._starting or self._stopping
            up = info.get("running") == "1" or procs != "0"
            if self._last_up and not up:
                # The run went away; the next one gets its own viewer.
                self._vnc_opened = False
                self._started_here = False
            if (sys.platform == "darwin" and up and self._started_here
                    and not self._vnc_opened):
                # The picture is a VNC display inside the container, so the
                # "own window" this tab promises is macOS Screen Sharing.
                # Opened from the poll, not from Start, so it cannot race the
                # container's VNC server: by the first up=1 answer x11vnc is
                # already listening (entrypoint.sh starts it before watch.sh).
                self._vnc_opened = True
                # The password rides in the URL because Screen Sharing will
                # ask for one either way: it refuses a VNC server with no
                # authentication, so padbox.sh always sets one (its default,
                # "pinball", and this URL must agree). It exists to satisfy
                # the client, not to protect anything - the port is loopback
                # only.
                try:
                    subprocess.Popen(["open", "vnc://:pinball@localhost:5900"])
                    self._log("[emulate] opening the picture in Screen "
                              "Sharing (VNC password: pinball)")
                except Exception:                       # noqa: BLE001
                    pass
            self._last_up = up
            self._run_label(up, busy)
            # Resetting WSL audio kills every distro, so never offer it while a
            # run is up or mid-transition: the honest order is stop, then reset.
            self._fixaud_btn.configure(
                state=tk.DISABLED if (up or busy or self._resetting
                                      or not rig_available()) else tk.NORMAL)
            # Same gate, same reason stated a different way: the emulator
            # writes its window geometry back as it runs, so a reset while it
            # is up is a lie rather than a no-op.  _window_reset re-checks on
            # the click and winreset.sh checks again inside the rig, because a
            # run can come up in the two seconds between polls.
            self._winreset_btn.configure(
                state=tk.DISABLED if (up or busy or self._winresetting
                                      or not rig_available()) else tk.NORMAL)
            # Start-time options: they follow the Start button, because that is
            # the only moment they are read.
            opts = tk.DISABLED if (up or busy) else tk.NORMAL
            self._audio_chk.configure(state=opts)
            self._auto_chk.configure(state=opts)
        except tk.TclError:
            pass        # the tab went away between the poll and its result

    def _set(self, key, text):
        try:
            self._vals[key].configure(text=text)
        except (KeyError, tk.TclError):
            pass
