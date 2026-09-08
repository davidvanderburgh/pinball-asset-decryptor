"""Binaries the app SHIPS, pinned by hash, instead of building on a user's machine.

WHY THIS EXISTS.  Every emulator rig used to compile itself on first Start, out
of whatever compiler, glibc, python and build tools the user's distro shipped
that year.  That is a build we have never run, on a machine we cannot see, and
it broke in the field twice in eight days for reasons that had nothing to do
with the app: a glibc 2.41 header collision in qemu 8.2.2 (Joe, 2026-08-31,
v0.175.2) and a Python 3.14 distro that packages ``ensurepip`` separately, so
qemu's configure could not build the venv it installs its own meson into
(eyeamred2u, 2026-09-08).  Both users saw the rig fail at a step that is not
theirs to fix.

So the rule is now: WE build it, ONCE, in CI, and ship the result.  A payload is
identified by its SHA-256, which is written down here - not fetched, not
"latest", not resolved through an API.  A machine either has the exact bytes we
tested or it has nothing, and "nothing" is a download away rather than a
toolchain away.

WHAT MAKES THIS POSSIBLE.  The two Spike 1 binaries have no runtime dependency
on the distro at all: ``qemu-arm`` is built ``--static`` (a static-pie ELF), and
``s1hwshim`` links libfuse3 statically (CUSE talks to /dev/fuse directly - it
never needs the fusermount3 helper).  So one build runs everywhere, which is the
whole reason this can be a download rather than a per-distro package.

WHERE THEY LAND.  Exactly where each rig already looks for a binary it built
itself - ``~/qemubuild/qemu-arm``, ``~/s1emu/s1hwshim``.  Nothing downstream has
to learn a new path, and a developer who wants the from-source build still gets
it: ``build_qemu.sh`` is unchanged and ``S1_QEMU`` still points wherever it is
told.  The stamp beside each payload records WHICH source it was built from, so
a rig can tell "this is the binary for the sources I have" from "this is older
than the .c file next to it" without guessing from timestamps.

NETWORK SHAPE, and every part of it is a decision:

* The asset URL is built from the release TAG, never from ``api.github.com``.
  The API is rate limited to 60 requests an hour per IP unauthenticated, which
  a shared corporate address exhausts without the user doing anything (this app
  has already met that 403 once), and a direct asset URL cannot 403.
* Downloads land in a ``.part`` file and are renamed only after the hash
  matches, so an antivirus that eats a file mid-write, a proxy that returns an
  HTML error page, and a half-finished download all fail the same loud way
  instead of installing something that is not what we built.
* Nothing is packed or compressed with anything exotic.  UPX and friends are
  what actually trip antivirus heuristics; a plain ELF from a GitHub release
  does not.
* HTTPS goes through :mod:`core.net`, which prefers certifi, and falls back to
  the OS trust store when that rejects - the shape of a corporate TLS-
  intercepting proxy, whose CA is in the Windows store and not in certifi.
* And when the network is simply not allowed: :func:`install_from_file` takes a
  payload downloaded on some other machine and checks the same hash before
  installing it.  That is the air-gapped path, and it is a file picker, not a
  terminal.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import net
from .config import GITHUB_REPO

#: Where a downloaded payload is kept on the HOST, so a repair, a second WSL
#: distro or a reinstall does not download it again.
_CACHE_NAMESPACE = "pinball_decryptor"

#: Read in 1 MiB blocks: big enough that hashing a 20 MB binary is one tick of
#: the progress bar, small enough to stay off the large-object heap.
_CHUNK = 1024 * 1024

DOWNLOAD_TIMEOUT = 60


@dataclass(frozen=True)
class Payload:
    """One binary we build, pin and ship.

    Attributes:
        key: stable id used by the UI and the tests (``"spike1-qemu"``).
        filename: the release asset's name, and the name it is cached under.
        release_tag: the git tag whose release carries it.  Payload releases
            are cut SEPARATELY from app releases and never re-uploaded, so a
            tag plus a filename is an immutable address.
        sha256: what we built.  The only definition of "correct" here.
        size: expected byte count - checked first, because it costs nothing
            and it is what tells a truncated download from a wrong one.
        version: human wording for the UI ("qemu 8.2.2 + PAD patches").
        what: one line saying what it is for, shown beside the version.
        dest: absolute path INSIDE the Linux side (WSL, or the machine itself
            on a Linux desktop) - the path the rig already looks in.
        mode: unix permission bits for the installed file.
        source_of: repo-relative sources this was built from, if any.
        source_sha256: the hash of that source AT BUILD TIME, written into a
            stamp beside the installed file.

    THE STAMP IS THERE TO KILL A TIMESTAMP RULE.  ``start.sh`` decided whether
    to recompile the device model by asking whether ``s1hwshim.c`` was NEWER
    than the binary - which is true of every machine that has just installed an
    app update, because unpacking rewrites the .c with today's date.  That
    turned "the user updated the app" into "the user now needs gcc and
    libfuse3-dev", which is the exact failure this module exists to end.  The
    stamp says which SOURCE the shipped binary was built from, so the question
    becomes "is this binary for these sources", which a reinstall does not
    change and an actual edit does.
    """
    key: str
    filename: str
    release_tag: str
    sha256: str
    size: int
    version: str
    what: str
    dest: str
    mode: int = 0o755
    source_of: Tuple[str, ...] = field(default_factory=tuple)
    source_sha256: str = ""


#: THE PINNED SET.  A new entry is added by the payload workflow
#: (.github/workflows/payloads.yml), which prints exactly these fields after it
#: builds and uploads.  Never edit a hash by hand to make something pass: the
#: hash IS the verification.
#:
#: The two Spike 1 binaries come first because they are the ones a user's first
#: Start used to compile - twenty minutes of qemu build on a good machine, and
#: an apt install of seven packages before it.
PAYLOADS: Dict[str, Payload] = {}


def register(payload: Payload) -> Payload:
    PAYLOADS[payload.key] = payload
    return payload


# Built and published by .github/workflows/payloads.yml on 2026-09-08 (run
# 34262051787, tag payloads-1), which printed every field below.  A payload
# whose sha256 is empty is treated as NOT YET PUBLISHED - the app then falls
# back to the from-source build rather than trying to download a file that does
# not exist - which is what these two were between the mechanism landing and
# the release being cut.  See tests/test_payloads.py.
register(Payload(
    key="spike1-qemu",
    filename="qemu-arm",
    release_tag="payloads-1",
    sha256="af669cbaf5536e431315685a8c37bdd511b9496536aed553552cd450afc572bf",
    size=4981904,
    version="qemu 8.2.2, patched (static)",
    what="the ARM emulator the Spike 1 game runs under",
    dest="~/qemubuild/qemu-arm",
    source_of=("tools/spike1_emu/patch_qemu.py",),
    source_sha256="968c137774290af7481db53cb75de1e0dfe89a066f9b70e41ed200fb5589c779",
))

register(Payload(
    key="spike1-hwshim",
    filename="s1hwshim",
    release_tag="payloads-1",
    sha256="27dbf3864d4ec2d7afe107c8fa834788be5fc7439b432277eebdee3529c0c4ba",
    size=1276008,
    version="s1hwshim (static libfuse3)",
    what="the CUSE device model the game's board set talks to",
    dest="~/s1emu/s1hwshim",
    source_of=("tools/spike1_emu/s1hwshim.c",),
    source_sha256="3fd77ece34cfde552330b838650a00678e2b0ed9202d12af734b50dd4a8eea28",
))


def is_published(payload: Payload) -> bool:
    """False while a payload has no pinned hash yet - the app then builds from
    source as it always did.  This is what lets the mechanism ship before the
    first payload release is cut, rather than in the same breath."""
    return bool(payload.sha256) and payload.size > 0


def asset_url(payload: Payload, repo: str = GITHUB_REPO) -> str:
    """The direct release-asset URL.  No API call - see the module docstring."""
    return "https://github.com/%s/releases/download/%s/%s" % (
        repo, payload.release_tag, payload.filename)


def cache_root() -> str:
    """Where downloads are kept on the host."""
    override = os.environ.get("PAD_PAYLOAD_DIR")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME",
                              os.path.expanduser("~/.cache"))
    return os.path.join(base, _CACHE_NAMESPACE, "payloads")


def cache_path(payload: Payload) -> str:
    """The cached file for this EXACT payload.

    Named with the hash prefix, so a payload that is re-cut lands beside the
    old one instead of on top of it: a stale file can then never masquerade as
    the new one, and rolling back is deleting a file rather than re-downloading
    the previous build."""
    stamp = payload.sha256[:12] if payload.sha256 else "unpinned"
    return os.path.join(cache_root(), "%s-%s" % (stamp, payload.filename))


def file_sha256(path: str, progress: Optional[Callable[[int], None]] = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(_CHUNK)
            if not block:
                break
            h.update(block)
            if progress:
                progress(len(block))
    return h.hexdigest()


def verify(path: str, payload: Payload) -> Tuple[bool, str]:
    """``(ok, why not)`` for a file on disk.

    Size first: a truncated download, an antivirus that replaced the file with
    a stub, and a proxy's HTML error page are all wrong SIZES, and saying so
    costs no hashing at all.  Then the hash, which is the actual promise."""
    if not os.path.exists(path):
        return False, "not downloaded yet"
    actual_size = os.path.getsize(path)
    if actual_size != payload.size:
        return False, ("wrong size: %d bytes, expected %d (a blocked download "
                       "often lands as an error page)"
                       % (actual_size, payload.size))
    got = file_sha256(path)
    if got != payload.sha256:
        return False, ("checksum does not match what we built (%s..., expected "
                       "%s...)" % (got[:12], payload.sha256[:12]))
    return True, ""


def download(payload: Payload, dest: Optional[str] = None,
             log: Optional[Callable[[str], None]] = None,
             progress: Optional[Callable[[int, int], None]] = None,
             opener: Optional[Callable] = None,
             repo: str = GITHUB_REPO) -> str:
    """Fetch one payload into the host cache and return its path.

    Writes ``<dest>.part`` and renames only after :func:`verify` passes, so a
    failed or tampered download leaves NOTHING that a later run could mistake
    for the real thing.  Raises ``RuntimeError`` with a sentence a user can act
    on - which is the whole point of this function having its own error text
    rather than letting a urllib exception reach the log."""
    dest = dest or cache_path(payload)
    url = asset_url(payload, repo)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if log:
        log("Downloading %s (%s)…" % (payload.filename, payload.version))
    part = dest + ".part"
    do_open = opener or net.urlopen
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pad-payloads"})
        with do_open(req, timeout=DOWNLOAD_TIMEOUT) as resp, \
                open(part, "wb") as out:
            done = 0
            while True:
                block = resp.read(_CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress:
                    progress(done, payload.size)
    except Exception as exc:                                   # noqa: BLE001
        _unlink(part)
        raise RuntimeError(
            "could not download %s: %s\n"
            "If this machine is behind a firewall, %s and "
            "objects.githubusercontent.com need to be reachable on 443 — or "
            "download the file on another machine and use \"Install from "
            "file\"." % (payload.filename, exc, "github.com")) from exc

    ok, why = verify(part, payload)
    if not ok:
        _unlink(part)
        raise RuntimeError(
            "%s downloaded but %s. Antivirus or a proxy may have altered it; "
            "try again, or download it on another machine and use \"Install "
            "from file\"." % (payload.filename, why))
    os.replace(part, dest)
    if log:
        log("%s verified (%s)." % (payload.filename, _human(payload.size)))
    return dest


def ensure_cached(payload: Payload, log=None, progress=None, opener=None,
                  repo: str = GITHUB_REPO) -> str:
    """The cached payload, downloading it only if what is cached is not it.

    A cached file that fails verification is re-downloaded rather than trusted
    or reported: that is the self-healing half - a half-written cache from a
    machine that slept mid-download costs one retry, not a support thread."""
    path = cache_path(payload)
    ok, _why = verify(path, payload)
    if ok:
        return path
    if os.path.exists(path):
        if log:
            log("Cached %s is not what we built — fetching it again."
                % payload.filename)
        _unlink(path)
    return download(payload, path, log=log, progress=progress, opener=opener,
                    repo=repo)


def install_from_file(payload: Payload, path: str, installer=None, log=None) -> str:
    """Install a payload the user supplied themselves.

    The offline path, and it verifies EXACTLY what the download path verifies -
    a file handed over by a person is not more trusted than one off the wire,
    it is just differently delivered."""
    ok, why = verify(path, payload)
    if not ok:
        raise RuntimeError("%s is not the file we built: %s"
                           % (os.path.basename(path), why))
    # Into the cache first, so a file handed over once is not asked for again
    # after a reinstall - and so install() below has exactly one source of
    # bytes to verify, whichever way they arrived.
    cached = cache_path(payload)
    os.makedirs(os.path.dirname(cached) or ".", exist_ok=True)
    shutil.copyfile(path, cached)
    return install(payload, installer=installer, log=log)


def install(payload: Payload, installer=None, log=None,
            distro: Optional[str] = None) -> str:
    """Put the cached payload where the rig looks for it.

    ``installer`` is the one thing that differs between a Windows host talking
    to WSL and a Linux desktop that IS the machine, so it is injected rather
    than decided here - which is also what lets the tests exercise every line
    above without a WSL on the runner."""
    src = cache_path(payload)
    ok, why = verify(src, payload)
    if not ok:
        raise RuntimeError("refusing to install %s: %s" % (payload.filename, why))
    place = installer or default_installer(distro)
    place(payload, src)
    if log:
        log("Installed %s -> %s" % (payload.filename, payload.dest))
    return payload.dest


def default_installer(distro: Optional[str] = None):
    # macOS IS NOT A PLACE FOR THESE.  Every payload is a Linux binary bound
    # for a Linux path; on a Mac the "local" installer would write ELF into
    # ~/qemubuild and report success for a rig that cannot run there at all.
    if sys.platform == "darwin":
        raise RuntimeError(
            "the emulator binaries are Linux programs; this Mac has nowhere "
            "to put them (the Spike 1 rig runs on Windows through WSL)")
    """Copy into the Linux side: through ``wsl.exe`` as root on Windows, and
    straight onto the filesystem on a Linux desktop.

    The bytes go in on STDIN rather than by path.  A /mnt/c copy would work on
    Windows and read at drvfs speed, but it also means the file has to BE on a
    Windows filesystem, which is the one place a Windows antivirus can hold it
    open or quarantine it between our write and the rig's read."""
    if sys.platform == "win32":
        return lambda p, src: _install_through_wsl(p, src, distro)
    return _install_locally


#: What the stamp beside an installed payload is called, and what a rig reads
#: out of it.  One line, `name=value`, because the readers are shell.
STAMP_SUFFIX = ".pad-payload"


def stamp_text(payload: Payload) -> str:
    return ("key=%s\nsha256=%s\nsource_sha256=%s\nversion=%s\n"
            % (payload.key, payload.sha256, payload.source_sha256,
               payload.version))


def _install_locally(payload: Payload, src: str) -> None:
    dest = os.path.expanduser(payload.dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".new"
    shutil.copyfile(src, tmp)
    os.chmod(tmp, payload.mode)
    os.replace(tmp, dest)
    with open(dest + STAMP_SUFFIX, "w", encoding="utf-8") as f:
        f.write(stamp_text(payload))


def _install_through_wsl(payload: Payload, src: str,
                         distro: Optional[str] = None) -> None:
    # install -D makes the directory, sets the mode and writes the file in one
    # step; /dev/stdin is the payload arriving on the pipe.  As root, because
    # the rig's own work dirs are made by a root start.sh - and then chown'd to
    # the desktop user, or the next ordinary-user run cannot read its own rig.
    # `install -D` makes the directory, sets the mode and writes the file in
    # one step, with /dev/stdin as the payload arriving on the pipe.
    #
    # THE PARENT DIRECTORY IS CHOWNED ONLY IF WE MADE IT.  Everything here runs
    # as root (the rig's own start.sh does too), so a directory we create is
    # root's and the rig, which runs as the desktop user for everything it can,
    # then cannot write beside its own binary.  Chowning a directory that was
    # already there is the other error: ~/s1emu holds root-owned extraction
    # output on purpose, and taking that over would be a much bigger act than
    # installing a file.
    script = (
        'set -e; '
        # A DISTRO WITH NO uid 1000 IS NOT ONE WE CAN INSTALL INTO.  Without
        # this, `h` is empty, `~/qemubuild/qemu-arm` resolves to
        # /qemubuild/qemu-arm, and the app installs the emulator at the ROOT of
        # someone's distro as root - which then reads back as installed,
        # because the probe expands the same empty `~` the same wrong way.
        'u="$(getent passwd 1000 | cut -d: -f1)"; '
        'h="$(getent passwd 1000 | cut -d: -f6)"; '
        'if [ -z "$h" ]; then echo "this WSL distro has no ordinary user '
        '(uid 1000), and the emulator installs into that user home" >&2; '
        'exit 3; fi; '
        # AND THE BYTES MUST BE FOR THIS CPU.  Everything we pin is built
        # x86-64; an ARM64 Windows PC runs an aarch64 distro, where these would
        # install cleanly and then fail to exec.
        'm="$(uname -m)"; if [ "$m" != x86_64 ]; then echo "this WSL distro is '
        '$m; the emulator we ship is built for x86_64" >&2; exit 4; fi; '
        'd="%s"; case "$d" in "~"*) d="$h${d#\\~}";; esac; '
        'p="$(dirname "$d")"; made=0; [ -d "$p" ] || made=1; '
        'install -D -m %o /dev/stdin "$d"; '
        'printf %%b "%s" > "$d%s"; '
        'chown "$u": "$d" "$d%s" 2>/dev/null || true; '
        'if [ "$made" = 1 ]; then chown "$u": "$p" 2>/dev/null || true; fi; '
        'echo "$d"' % (payload.dest, payload.mode,
                       stamp_text(payload).replace("\n", "\\n"),
                       STAMP_SUFFIX, STAMP_SUFFIX))
    head = ["wsl.exe"] + (["-d", distro] if distro else []) + ["-u", "root"]
    # A TIMEOUT, because a wedged WSL is a state this rig documents and hits:
    # zombie mounts pin a distro and wsl.exe never returns.  Without one the
    # worker thread waits forever, "Fix setup" stays greyed and Start sits at
    # "Starting…" with no way back but killing the app.  Ten minutes is far
    # longer than piping 20 MB and far shorter than never.
    with open(src, "rb") as f:
        proc = subprocess.run(
            head + ["-e", "bash", "-c", script], timeout=600,
            stdin=f, capture_output=True,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0))
    if proc.returncode != 0:
        raise RuntimeError("could not install %s into WSL: %s"
                           % (payload.filename,
                              proc.stderr.decode("utf-8", "replace").strip()
                              or "exit %d" % proc.returncode))


def missing(keys: Optional[List[str]] = None, prober=None,
            distro: Optional[str] = None) -> List[Payload]:
    """Those of ``keys`` that are published but not installed on this machine.

    ``prober`` answers "is this path an executable file on the Linux side?" and
    is injected for the same reason the installer is."""
    ask = prober or default_prober(distro)
    out = []
    for key in (keys if keys is not None else list(PAYLOADS)):
        p = PAYLOADS[key]
        if is_published(p) and not ask(p):
            out.append(p)
    return out


def default_prober(distro: Optional[str] = None):
    if sys.platform == "win32":
        return lambda p: _probe_through_wsl(p, distro)
    return _probe_locally


def _probe_locally(payload: Payload) -> bool:
    return os.access(os.path.expanduser(payload.dest), os.X_OK)


def _probe_through_wsl(payload: Payload,
                       distro: Optional[str] = None) -> bool:
    # NOT "IS SOMETHING THERE" - "IS THIS ONE THERE".  The stamp beside the
    # binary names the payload it came from, so a RE-CUT payload (a new hash
    # under the same filename) actually reaches a machine that already has the
    # old one.  Existence alone would mean the first payload a machine ever
    # installed is the last one it would ever get, while the app went on
    # believing its users were running the bytes it had pinned.
    script = ('h="$(getent passwd 1000 | cut -d: -f6)"; d="%s"; '
              'case "$d" in "~"*) d="$h${d#\\~}";; esac; '
              '[ -x "$d" ] || exit 1; '
              'grep -qx "sha256=%s" "$d%s" 2>/dev/null'
              % (payload.dest, payload.sha256, STAMP_SUFFIX))
    try:
        head = ["wsl.exe"] + (["-d", distro] if distro else [])
        proc = subprocess.run(
            head + ["-e", "bash", "-c", script], capture_output=True,
            timeout=30, creationflags=(subprocess.CREATE_NO_WINDOW
                                       if sys.platform == "win32" else 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def ensure(keys: Optional[List[str]] = None, log=None, progress=None,
           installer=None, prober=None, opener=None,
           repo: str = GITHUB_REPO, distro: Optional[str] = None) -> List[str]:
    """Make sure every published payload in ``keys`` is installed.

    Returns the keys it actually had to install, so a caller can say "nothing
    to do" honestly.  Never raises for a payload that has no pinned hash yet -
    that one is simply not ours to supply until the release is cut."""
    installed = []
    for p in missing(keys, prober=prober, distro=distro):
        ensure_cached(p, log=log, progress=progress, opener=opener, repo=repo)
        install(p, installer=installer, log=log, distro=distro)
        installed.append(p.key)
    return installed


def _unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _human(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit != "bytes" else "%d bytes" % n
        n /= 1024.0
    return str(n)
