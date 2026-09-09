"""The PAD Runtime: a Linux we build, pin and import, so the user's own is not
part of the story.

WHY THIS EXISTS, and why it is a second thing after core/payloads.py.  Payloads
stopped the app COMPILING on a user's machine.  This stops it DEPENDING on that
machine's Linux.  Every rig has so far run inside whichever distro happened to
be the WSL default - some Ubuntu, some Debian, one tester on an Arch spin - and
each brings its own glibc, python, package names and set of installed tools.
Every field break has come out of that gap, and none was reproducible on the
machine that could fix it.

So the app brings its own: a rootfs we build in CI (tools/runtime/Dockerfile,
.github/workflows/runtime.yml), pinned by SHA-256 here, imported as a PRIVATE
WSL distro.  Three things follow, and the third is the one nobody asked for but
everybody wanted:

  * the user's distro is not touched, not read and not required;
  * "which Linux is this?" has one answer, the same on every machine, so a bug
    report describes a system we can stand up ourselves;
  * a Windows PC with WSL enabled and NO distro installed at all can run the
    emulator.  That used to be a trip to the Microsoft Store before the app was
    any use.

WHAT THIS IS NOT.  It is not a replacement for WSL itself: importing a distro
needs the WSL feature present (that install wants an administrator and usually
a reboot, which the app cannot do for anyone).  What it removes is everything
AFTER that.

ONE IMAGE, BOTH RIGS.  The first cut (`base`, runtime 1) carried what Spike 1
needs; `full` adds Spike 2's - the ARM cross compiler and qemu-user-static its
guest runs under, ffmpeg for a picture and a sound the game does not decode
itself, e2fsprogs and fuse3 for the card, a static busybox for the
checkpointable boot, and criu, which no Ubuntu has ever packaged and which the
rig therefore COMPILES on the user's machine today.  The image builds it, so
that stops too.

AND EVERYTHING GOES THROUGH IT, not only the rigs.  The first cut routed the
two emulators and left the extract and write pipelines in the user's own
distro, which gave the app two Linuxes and a prerequisite strip reporting on
the wrong one.  The image carries the pipelines' tools now, so `wsl_distro`
answers once for the whole app - and a machine without our runtime still uses
its own default, exactly as before.
"""

import json
import os
import subprocess
import sys
import threading
import time
from typing import Optional, Tuple

from .payloads import (Payload, ensure_cached, is_published,  # noqa: F401
                       verify)

class RuntimeNeedsReplacing(RuntimeError):
    """Raised instead of destroying a runtime that is already installed.

    Carries no data: the caller knows which distro it asked about, and what
    matters is that the decision goes to a person."""


#: The distro name the app registers.  Chosen to be obviously ours in
#: `wsl -l -v`, and never to collide with a name a person would pick.
DISTRO = "PAD-Runtime"

#: What the app expects to find inside an installed runtime
#: (/etc/pad-runtime.json).  A runtime older than this is upgradeable, not
#: broken: the app says so and offers to replace it.
RUNTIME_VERSION = 6

#: The image itself, pinned exactly like a payload binary - same download,
#: same .part-then-verify, same offline "install from file" path.  Filled in
#: by .github/workflows/runtime.yml, which prints these four fields (run
#: 34304691929, 2026-09-09).  An empty sha256 means NOT YET PUBLISHED and every
#: entry point below reports "not available" rather than trying to fetch a file
#: that does not exist - which is how the mechanism shipped before the image
#: existed.  413 MB compressed, most of it the ARM cross compiler, ffmpeg,
#: qemu-user-static and GDRE Tools: one download, once, against a toolchain a
#: user would otherwise be told to assemble themselves.
IMAGE = Payload(
    key="runtime-full",
    filename="pad-runtime-full.tar.gz",
    release_tag="runtime-6",
    sha256="cb056136596f6f9a56265308c5e1578e59f5992687e4b8ff4660d781c972a750",
    size=434090457,
    version="PAD Runtime 5 (full)",
    what="the Linux the emulator runs on, built and pinned by us",
    dest="",              # not a path inside Linux: this one becomes a distro
)

_CREATE_FLAGS = (subprocess.CREATE_NO_WINDOW
                 if sys.platform == "win32" else 0)

#: wsl.exe speaks UTF-16LE by default, which turns "Ubuntu" into
#: "U\0b\0u\0n\0t\0u\0" and breaks every comparison downstream.  WSL_UTF8=1
#: makes it speak UTF-8; the decoder below still strips NULs, because an older
#: wsl.exe ignores the variable and answering that with mojibake would be a
#: silent wrong answer rather than a loud one.
def _wsl_env():
    env = dict(os.environ)
    env["WSL_UTF8"] = "1"
    return env


def _run(args, timeout=120, stdin=None):
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          env=_wsl_env(), stdin=stdin,
                          creationflags=_CREATE_FLAGS)


def _why(out) -> str:
    """What wsl.exe actually said, wherever it said it.

    IT WRITES ITS ERRORS TO STDOUT, in UTF-16, and returns 4294967295 - so a
    message built from stderr and the return code alone says "exit 4294967295"
    for a full disk, a WSL 1 machine, virtualization switched off in the BIOS
    and a distro that will not start, which are four different problems with
    four different answers."""
    for stream in (getattr(out, "stderr", b""), getattr(out, "stdout", b"")):
        said = " ".join(_text(stream or b"").split())
        if said:
            return said
    rc = getattr(out, "returncode", "?")
    return "exit %s (WSL said nothing)" % rc


def _text(raw):
    if b"\x00" in raw:
        try:
            return raw.decode("utf-16-le", "replace")
        except Exception:                                   # noqa: BLE001
            return raw.replace(b"\x00", b"").decode("utf-8", "replace")
    return raw.decode("utf-8", "replace")


def install_dir() -> str:
    """Where the imported distro's virtual disk lives.

    Under LOCALAPPDATA, not APPDATA: it is machine-local state that must never
    follow a roaming profile onto another PC, and it is measured in hundreds of
    megabytes."""
    override = os.environ.get("PAD_RUNTIME_DIR")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    return os.path.join(base, "pinball_decryptor", "runtime")


def available() -> bool:
    """Is a runtime image published for this app version at all?"""
    return is_published(IMAGE)


def registered(runner=None) -> bool:
    """Is our distro registered with WSL?

    Asked of `wsl -l -q` rather than by looking for the install directory: a
    user can delete the folder, and a distro can be unregistered while the
    folder survives.  WSL's own list is the only thing that decides."""
    if sys.platform != "win32":
        return False
    run = runner or _run
    try:
        out = run(["wsl.exe", "-l", "-q"], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    names = [n.strip() for n in _text(out.stdout).splitlines()]
    return DISTRO in [n for n in names if n]


def manifest(runner=None) -> Optional[dict]:
    """What the installed runtime says it is, read from inside it.

    None when it is not installed, or when it is installed but has no manifest
    - which means something else registered a distro under our name, and the
    app must not treat that as its own."""
    if not registered(runner=runner):
        return None
    return _read_manifest(runner)


def _read_manifest(runner=None) -> Optional[dict]:
    """The read itself, WITHOUT re-asking whether the distro is registered.

    Split out because the caller that matters has just asked: `_status` was
    paying for THREE wsl.exe launches per refresh - list, list again, then the
    read - and the second list told it nothing the first had not."""
    run = runner or _run
    try:
        out = run(["wsl.exe", "-d", DISTRO, "-e", "cat", "/etc/pad-runtime.json"],
                  timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(_text(out.stdout))
    except ValueError:
        return None


#: The health answer is CACHED, because it is asked on a timer.  Every rig
#: command has to know which distro to run in, the status poll fires every
#: couple of seconds, and answering honestly costs two `wsl.exe` launches
#: (~200 ms each, each one a console process).  Sixty seconds is far longer
#: than a poll and far shorter than a user's patience with a stale answer, and
#: anything that CHANGES the state - install, uninstall - clears it outright.
_STATUS_CACHE = {"when": 0.0, "value": None}
STATUS_TTL = 60.0


def invalidate() -> None:
    _STATUS_CACHE.update(when=0.0, value=None)


def known_state() -> Optional[str]:
    """The last answer, WITHOUT asking anyone.  None when nobody has asked yet.

    For the things that must never cost a subprocess: a cosmetic log line, a
    label, anything on a hot path.  Routing uses :func:`status`, which is
    allowed to go and look; a sentence in the log is not worth starting a
    distro for."""
    value = _STATUS_CACHE["value"]
    return value[0] if value else None




def status(runner=None, refresh: bool = False) -> Tuple[str, str]:
    """``(state, one sentence)`` - the whole health answer in one call.

    States: ``unsupported`` (not Windows), ``unpublished`` (no image pinned in
    this app version yet), ``absent``, ``foreign`` (a distro of that name that
    is not ours), ``stale`` (ours, older than this app expects), ``ready``, and
    ``unknown`` - which means only "nobody has asked yet on a thread allowed to
    wait", never "something is wrong".
    """
    if runner is None:
        # The two answers that cost NOTHING are always exact, cache or no
        # cache: a Mac is not going to grow a WSL distro, and an app version
        # with no pinned image has nothing to look for.
        if sys.platform != "win32":
            return ("unsupported",
                    "The runtime is a WSL distro, so it is Windows-only.")
        if not available():
            return ("unpublished",
                    "This app version has no pinned runtime image yet.")
        if not refresh:
            cached = _STATUS_CACHE["value"]
            if cached and (time.monotonic() - _STATUS_CACHE["when"]) < STATUS_TTL:
                return cached
            # A COLD CACHE MUST NEVER BLOCK THE INTERFACE.  Answering honestly
            # costs two wsl.exe launches, and every rig command asks this to
            # decide which distro to run in - so a command built on the Tk
            # thread would freeze the window for as long as WSL takes, which on
            # a machine with no distro at all is seconds.  On that thread the
            # answer is "not known yet" and the routing falls back to the
            # machine's default, which is what every rig did before this
            # existed.  Nothing is spawned to fix that: both tabs already build
            # their commands on worker threads, so the ordinary status poll
            # fills this cache within a tick - and a background thread started
            # from here would race with anything that patches subprocess.
            if threading.current_thread() is threading.main_thread():
                return cached or (
                    "unknown",
                    "The runtime has not been looked at on this machine yet.")
    answer = _status(runner)
    if runner is None:
        _STATUS_CACHE.update(when=time.monotonic(), value=answer)
    return answer


def _status(runner=None) -> Tuple[str, str]:
    if sys.platform != "win32":
        return "unsupported", "The runtime is a WSL distro, so it is Windows-only."
    if not available():
        return ("unpublished",
                "This app version has no pinned runtime image yet.")
    if not registered(runner=runner):
        return "absent", "The runtime is not installed on this machine yet."
    info = _read_manifest(runner)
    if info is None:
        return ("foreign",
                "A WSL distro called %s exists but is not ours - the app will "
                "not touch it." % DISTRO)
    have = info.get("runtime_version")
    if have != RUNTIME_VERSION:
        return ("stale",
                "The installed runtime is version %s; this app expects %s."
                % (have, RUNTIME_VERSION))
    return ("ready",
            "Runtime %s (%s), built %s."
            % (info.get("runtime_version"), info.get("variant", "?"),
               info.get("built", "?")))


def usable(runner=None) -> bool:
    return status(runner=runner)[0] == "ready"


def install(log=None, progress=None, runner=None, opener=None,
            source: Optional[str] = None, replace: bool = False) -> str:
    """Download (or take a supplied file), verify, and import as a distro.

    ``replace`` IS A CONSENT FLAG, and it is False by default on purpose.
    Importing over a registered runtime means `wsl --unregister` first, and
    that DELETES THAT DISTRO'S ENTIRE FILESYSTEM - which is not empty: the rigs
    keep their extracted games, their card caches and their SAVE-STATE SLOTS
    inside it ($S1_WORK/saves, $PAD_HOME/cardcache).  A save state is something
    a person made and cannot get back.  So a caller that has not asked a human
    gets :class:`RuntimeNeedsReplacing` instead of a silent wipe, and the one
    place that may pass ``replace=True`` is a dialog that named what is inside.

    Returns the state afterwards.  Raises with a sentence for the log if the
    import itself fails - which on a machine without the WSL feature is the
    error that matters, and is not something the app can fix for the user."""
    if sys.platform != "win32":
        raise RuntimeError("the runtime is a WSL distro, so it is Windows-only")
    if not available():
        raise RuntimeError("this app version has no pinned runtime image yet")
    say = log or (lambda _m: None)

    if source:
        ok, why = verify(source, IMAGE)
        if not ok:
            raise RuntimeError("%s is not the runtime we built: %s"
                               % (os.path.basename(source), why))
        tarball = source
    else:
        tarball = ensure_cached(IMAGE, log=log, progress=progress,
                                opener=opener)

    # A REGISTERED DISTRO IS REPLACED, NOT INSTALLED OVER.  `wsl --import`
    # refuses a name that exists - but replacing one is destroying one, so it
    # happens only when a human has been told what is in it.
    run = runner or _run
    if registered(runner=runner) and not replace:
        raise RuntimeNeedsReplacing(
            "A runtime called %s is already installed, and replacing it "
            "deletes everything inside it - extracted games, card caches and "
            "save-state slots." % DISTRO)
    if registered(runner=runner):
        say("Removing the previous runtime…")
        out = run(["wsl.exe", "--unregister", DISTRO], timeout=300)
        invalidate()
        if out.returncode != 0:
            raise RuntimeError("could not remove the previous runtime: %s"
                               % _why(out))

    target = install_dir()
    os.makedirs(target, exist_ok=True)
    say("Installing the runtime (this takes a moment, once)…")
    out = run(["wsl.exe", "--import", DISTRO, target, tarball, "--version", "2"],
              timeout=900)
    if out.returncode != 0:
        raise RuntimeError(
            "could not import the runtime: %s\nWSL 2 itself has to be "
            "installed first - `wsl --install --no-distribution` in an "
            "administrator terminal, then restart."
            % (_text(out.stderr).strip() or "exit %d" % out.returncode))

    invalidate()
    state, detail = status(runner=runner, refresh=True)
    if state != "ready":
        raise RuntimeError("the runtime imported but does not answer as ours: "
                           "%s" % detail)
    say(detail)
    return state


def uninstall(runner=None) -> bool:
    """Unregister the distro, DESTROYING ITS FILESYSTEM.

    And that filesystem is not empty, whatever an earlier version of this
    docstring claimed: the rigs keep extracted games, card caches and
    save-state slots inside the distro they run in ($S1_WORK/saves,
    $PAD_HOME/cardcache).  Cards and captures are the app's, on the Windows
    side; slots are not.  Callers must have said so to a human first."""
    if not registered(runner=runner):
        return False
    run = runner or _run
    out = run(["wsl.exe", "--unregister", DISTRO], timeout=300)
    invalidate()
    return out.returncode == 0


def wsl_distro(runner=None) -> Optional[str]:
    """The distro EVERY Linux command from this app runs in, or None meaning
    "the machine's default" - which is what everything did before this existed
    and what a machine without our runtime still does.

    IT USED TO BE PER RIG, and the reason it no longer is worth writing down.
    The first cut routed only the Spike 1 and Spike 2 emulators here, because
    the image carried only what they need; the extract and write pipelines
    stayed in the user's own distro, installing packages onto his machine.
    That left the app with two Linuxes and a prerequisite strip that reported
    on the wrong one - a user whose emulator ran perfectly could be shown a
    column of red, because the strip was asking a thin default distro about
    tools that live in ours.  The image carries the pipelines' tools now
    (tools/runtime/Dockerfile, and tests/test_runtime_packages.py holds it to
    the installer's own lists), so there is one answer to "which Linux?" and
    this is it.

    Everything still degrades to the old behaviour rather than failing: on a
    machine with no runtime installed this is None and every caller uses the
    default distro exactly as it always has.

    PAD_RUNTIME=0 forces that old behaviour on a machine where the runtime is
    installed but suspect.  PAD_RUNTIME=1 does not force it ON, because a
    runtime that is not installed cannot be used by insisting.
    """
    if os.environ.get("PAD_RUNTIME") == "0":
        return None
    return DISTRO if usable(runner=runner) else None


def wsl_head(root: bool = False, runner=None) -> list:
    """``wsl.exe`` plus the distro selector, and ``-u root`` when asked.

    Every command this app sends into Linux starts with these words.  Handing
    out the list rather than the name is deliberate: the ``-d`` has to come
    before ``-u``, which has to come before ``--``, and six modules spelling
    that out separately is six chances to put our distro on one code path and
    not its neighbour."""
    head = ["wsl.exe"]
    distro = wsl_distro(runner=runner)
    if distro:
        head += ["-d", distro]
    if root:
        head += ["-u", "root"]
    return head


def distro_for(rig: str, runner=None) -> Optional[str]:
    """Kept for the rig callers, which name the rig they are.  The answer no
    longer depends on which one - see :func:`wsl_distro`."""
    return wsl_distro(runner=runner)
