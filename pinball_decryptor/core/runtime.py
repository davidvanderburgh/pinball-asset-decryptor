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

SCOPE, AND IT IS DELIBERATE.  The `base` variant runs the Spike 1 rig, whose
runtime needs are small and whose binaries we already ship.  The Spike 2 rig
wants another ~400 MB of toolchain (qemu-user-static, an ARM cross compiler,
ffmpeg, criu) and is the rig in daily use, so moving it onto a new distro is
its own pass with its own proof - not a side effect of introducing one.  Until
then Spike 2 keeps using the default distro, which is why the routing below is
asked PER RIG rather than set globally.
"""

import json
import os
import subprocess
import sys
import time
from typing import Optional, Tuple

from .payloads import (Payload, ensure_cached, is_published,  # noqa: F401
                       verify)

#: The distro name the app registers.  Chosen to be obviously ours in
#: `wsl -l -v`, and never to collide with a name a person would pick.
DISTRO = "PAD-Runtime"

#: What the app expects to find inside an installed runtime
#: (/etc/pad-runtime.json).  A runtime older than this is upgradeable, not
#: broken: the app says so and offers to replace it.
RUNTIME_VERSION = 1

#: The image itself, pinned exactly like a payload binary - same download,
#: same .part-then-verify, same offline "install from file" path.  Filled in
#: by .github/workflows/runtime.yml, which prints these four fields; empty
#: sha256 means NOT YET PUBLISHED and every entry point below reports "not
#: available" rather than trying to fetch a file that does not exist.
IMAGE = Payload(
    key="runtime-base",
    filename="pad-runtime-base.tar.gz",
    release_tag="runtime-1",
    sha256="",
    size=0,
    version="PAD Runtime 1 (base)",
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
        out = run(["wsl.exe", "-l", "-q"], timeout=60)
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
    run = runner or _run
    try:
        out = run(["wsl.exe", "-d", DISTRO, "-e", "cat", "/etc/pad-runtime.json"],
                  timeout=120)
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


def status(runner=None, refresh: bool = False) -> Tuple[str, str]:
    """``(state, one sentence)`` - the whole health answer in one call.

    States: ``unsupported`` (not Windows), ``unpublished`` (no image pinned in
    this app version yet), ``absent``, ``foreign`` (a distro of that name that
    is not ours), ``stale`` (ours, older than this app expects) and ``ready``.
    """
    if runner is None and not refresh:
        cached = _STATUS_CACHE["value"]
        if cached and (time.monotonic() - _STATUS_CACHE["when"]) < STATUS_TTL:
            return cached
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
    info = manifest(runner=runner)
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
            source: Optional[str] = None) -> str:
    """Download (or take a supplied file), verify, and import as a distro.

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
    # refuses a name that exists, and the states this heals - a half-imported
    # runtime, one from an older app version - are exactly the ones where the
    # user pressed a button that says Fix.
    run = runner or _run
    if registered(runner=runner):
        say("Removing the previous runtime…")
        out = run(["wsl.exe", "--unregister", DISTRO], timeout=300)
        invalidate()
        if out.returncode != 0:
            raise RuntimeError("could not remove the previous runtime: %s"
                               % _text(out.stderr).strip())

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
    """Unregister the distro.  Destroys its filesystem, which is why nothing
    the user made lives in it: cards, extractions and captures are the app's,
    on the Windows side."""
    if not registered(runner=runner):
        return False
    run = runner or _run
    out = run(["wsl.exe", "--unregister", DISTRO], timeout=300)
    invalidate()
    return out.returncode == 0


#: WHICH RIGS RUN IN IT.  Per rig, not global: the `base` image runs the
#: Spike 1 rig, and Spike 2 still wants a toolchain the image does not carry,
#: so pretending otherwise would swap a working default distro for one that is
#: missing qemu-user-static.  Adding a rig here is a promise the image can
#: actually run it.
RIGS = {"spike1"}


def distro_for(rig: str, runner=None) -> Optional[str]:
    """The distro name a rig's commands should run in, or None for "the
    machine's default", which is what every rig used before this existed.

    PAD_RUNTIME=0 forces the old behaviour for a machine where the runtime is
    installed but suspect; PAD_RUNTIME=1 does not force it ON, because a
    runtime that is not installed cannot be used by insisting."""
    if os.environ.get("PAD_RUNTIME") == "0":
        return None
    if rig not in RIGS:
        return None
    return DISTRO if usable(runner=runner) else None
