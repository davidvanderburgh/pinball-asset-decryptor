"""Running the Multi-boot tab's steps on macOS, inside a Linux container.

The tab's tools are Linux tools.  Windows runs them in WSL Ubuntu and Linux
runs them natively; macOS has no losetup, no ext4 in the kernel and no
partclone, so ``sudo`` was never the problem there and granting root would
only have moved the failure from "sudo: a password is required" to
"missing tool(s)" (PAD-192).

So macOS gets the same thing the other two have: a Linux with the tools in
it.  The JJP plugin already proves the shape - it runs a ``--privileged``
container on macOS for Direct-SSD extracts - but its image cannot serve this
tab, for one specific reason worth writing down:

    THE MENU PROGRAM IS A GLIBC LINK.  ensurejjpselect.sh compiles jjpselect
    against the card's own libraries with ``-nostdlib -nostartfiles``, the
    host gcc's ``crt1.o``/``crti.o``/``crtbegin.o`` and
    ``$(CC) -print-file-name=libc_nonshared.a``.  ``libc_nonshared.a`` is a
    glibc artefact that musl does not have at all, and musl's crt files are
    the wrong ABI for the card's ``libc.so.6``.  The JJP image is Alpine, so
    ``apk add gcc make`` would NOT fix it - and a writing run hard-fails when
    that compile fails (ensurejjpselect.sh, ``[ "$PREVIEW" = "1" ] || fail``).

This image is therefore Debian, carrying the JJP row of
``installer/install_prerequisites_linux.sh`` - including the ``gcc`` +
``libc6-dev`` pair that file already calls out, because gcc only
*recommends* libc6-dev and the compile needs its headers and crt files.
That makes the container the same kind of Linux the Windows path gets from
WSL Ubuntu, which is the whole idea.

AND IT IS AN X86-64 LINUX, ALWAYS (PAD-193).  A Mac with Apple silicon
builds and runs an image for its OWN architecture unless it is told
otherwise, and an arm64 Debian is the one Linux this tab cannot use:

  * the menu program is a NATIVE x86-64 link (the Makefile's ``PLATFORM=jjp``
    row hardcodes ``CC = gcc``) against the CARD's own
    ``usr/lib/x86_64-linux-gnu``, so an aarch64 gcc fails the link with a
    page of ``ld: skipping incompatible ... libc.so.6``;
  * the preview then RUNS that binary - ``preview_native`` for JJP puts no
    qemu in front of it - so even a cross-compiler would leave the redraw
    with an executable this Linux cannot start.

Hence :data:`PLATFORM` on every ``docker build`` and ``docker run`` here.
On an Apple-silicon Mac that is emulated (Rosetta, or Docker Desktop's
QEMU), which costs time and buys the only architecture that works; on an
Intel Mac it is native and changes nothing.

NOT TESTED ON A MAC.  There is no Mac on the machine this was written on, so
the toolchain reasoning above is read off the Makefile and the package list
rather than observed, and Docker Desktop's own behaviour (its file sharing
for /Volumes, loop devices inside its LinuxKit VM) is not exercised at all.
Everything that can be checked without one - the argv, the path mapping, the
mount list, the Dockerfile's contents - is covered in
tests/test_multiboot_docker.py.  :func:`unavailable_reason` is the guard: if
Docker is not there, the tab says so and runs nothing.
"""

import os
import shutil
import subprocess
import sys

#: Bumped whenever DOCKERFILE changes.  The tag IS the cache key - ``docker
#: image inspect`` succeeds on a stale image built from an older Dockerfile,
#: so a new package list that kept the old tag would never reach anybody who
#: had already built one.
IMAGE = "pad-multiboot:1"
CONTAINER = "pad-multiboot-worker"

#: The architecture the image and the container are built and run for - see
#: the module docstring.  Named on the command line rather than left to the
#: host, because the host is the one thing that must NOT decide it.
PLATFORM = "linux/amd64"

#: ...as ``docker inspect`` spells the same thing back.  A machine that
#: built the image before this was added has an arm64 one under the right
#: tag, which ``docker image inspect`` reports as present and healthy, so
#: the tag alone cannot be the cache key here: the ARCHITECTURE is.
ARCH = "amd64"

#: The JJP row of installer/install_prerequisites_linux.sh, plus what the
#: rig's own scripts shell out to.  ``gcc`` and ``libc6-dev`` are named as a
#: pair on purpose - that file's comment says why ("gcc pulls libc6-dev only
#: as a *recommended* package") and the menu program's link needs the crt
#: files and libc_nonshared.a that come with it.
DOCKERFILE = """\
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \\
        partclone e2fsprogs xorriso pigz gzip coreutils util-linux \\
        python3 bash make gcc libc6-dev \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp
CMD ["bash"]
"""

#: Rigs staged into the cache so the container can run them.  The app bundle
#: itself is NOT bind-mounted: /Applications is not one of the directories
#: Docker Desktop shares by default, and the JJP pipeline already answers
#: this the same way (``_stage_project_file`` copies partclone_to_raw.py
#: into the cache rather than mounting the bundle).
_RIGS = ("jjp_emu", "spike2_emu")

#: Copied without these - build scratch that is large, useless in the
#: container, and in __pycache__'s case actively wrong (host .pyc files).
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "build", "rootfs",
                               "games", ".git")


def enabled():
    """Whether this module is the way the tab runs its steps."""
    return sys.platform == "darwin"


def cache_root():
    """Host directory bind-mounted as ``/tmp`` in the container.

    Under ~/Library/Caches, i.e. inside /Users, which Docker Desktop shares
    out of the box - unlike /Applications, where the app itself lives.
    """
    d = os.path.expanduser("~/Library/Caches/pinball_decryptor/multiboot")
    os.makedirs(d, exist_ok=True)
    return d


def staged_repo():
    """Host path of the staged checkout root: the ``<repo>`` the tab's
    command lines ``cd`` into, so ``tools/jjp_emu/mkjjpmulti.py`` resolves
    under it exactly as it does from a real checkout."""
    return os.path.join(cache_root(), "repo")


def _norm(path):
    """A path in the shape this module compares and emits: forward slashes,
    no trailing one.

    macOS separators ARE forward slashes, so on the only platform this runs
    on the swap is a no-op.  It is here so the mapping can be exercised from
    a machine that is not a Mac - ``os.path.abspath`` on Windows turns
    ``/Volumes/x`` into ``C:\\Volumes\\x``, which would make every test of
    this file a test of Windows instead.
    """
    p = (path or "").replace("\\", "/")
    while len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p


def container_path(path):
    """A host path as the container sees it.

    Two rules, and the cache one has to come first: everything under
    :func:`cache_root` is bind-mounted at ``/tmp``, and everything else at
    ``/host`` + its own absolute path.  Same shape as the JJP executor's
    ``to_exec_path``, which is where it was taken from.
    """
    p = _norm(path)
    cache = _norm(cache_root())
    if p == cache:
        return "/tmp"
    if p.startswith(cache + "/"):
        return "/tmp/" + p[len(cache) + 1:]
    return "/host" + p


def host_from_container(path):
    """The reverse of :func:`container_path`, for a path a card recorded."""
    p = _norm(path)
    if p == "/tmp":
        return _norm(cache_root())
    if p.startswith("/tmp/"):
        return _norm(cache_root()) + "/" + p[5:]
    if p.startswith("/host/"):
        return p[5:]
    return p


def mount_points(paths):
    """The host directories to bind-mount for a run, from the paths it
    touches.

    DIRECTORIES, never the files themselves: an output ISO does not exist
    when the container starts, and a bind mount of a missing file would
    create a directory in its place.  The cache is mounted separately and is
    dropped here, and a path inside another is dropped too so Docker is not
    handed the same tree twice.
    """
    cache = _norm(cache_root())
    dirs = set()
    for p in paths:
        if not p:
            continue
        p = _norm(p)
        if not p.startswith("/"):
            # A "~/spike2root/..." selector dir is a path INSIDE the
            # container - the rig expands it there, against root's own home.
            # Bind-mounting the literal string would make a directory called
            # "~" next to the app and mount nothing useful.
            continue
        d = p if os.path.isdir(p) else p.rsplit("/", 1)[0]
        if not d or d == "" or "/" not in p:
            continue
        if d == cache or d.startswith(cache + "/"):
            continue            # already there as /tmp
        dirs.add(d)
    out = []
    for d in sorted(dirs):
        if any(d != o and d.startswith(o + "/") for o in dirs):
            continue            # a parent is already being mounted
        out.append(d)
    return out


def stage_rig(repo_src):
    """Copy the rigs out of *repo_src* into :func:`staged_repo`.

    Copied on every run rather than cached: the rig is a couple of megabytes,
    and a stale copy would run yesterday's tool against today's app - the
    kind of difference nobody would think to look for.
    """
    dst_root = staged_repo()
    for rig in _RIGS:
        src = os.path.join(repo_src, "tools", rig)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(dst_root, "tools", rig)
        shutil.copytree(src, dst, ignore=_SKIP, dirs_exist_ok=True)
    return dst_root


def _docker(args, timeout=30):
    return subprocess.run(["docker"] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def unavailable_reason():
    """Why the container cannot be used, or "" when it can.

    A sentence the user can act on, because "Docker is not running" and
    "Docker is not installed" want different things from them.
    """
    try:
        r = _docker(["info"], timeout=20)
    except FileNotFoundError:
        return ("Building a multi-boot card on a Mac runs the Linux tools "
                "in a container, and Docker Desktop is not installed. "
                "Install it and try again; the size check needs none of it.")
    except Exception:                                   # noqa: BLE001
        return ("Could not ask Docker whether it is running. Start Docker "
                "Desktop and try again.")
    if r.returncode != 0:
        return ("Building a multi-boot card on a Mac runs the Linux tools "
                "in a container, and Docker Desktop is installed but not "
                "running. Start it and try again.")
    return ""


def _image_field(field):
    """One ``docker image inspect`` field of :data:`IMAGE`, or "" when the
    image is not on this machine."""
    r = _docker(["image", "inspect", "-f", "{{%s}}" % field, IMAGE],
                timeout=20)
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def ensure_image(log=None):
    """Build :data:`IMAGE` if this machine has not got a usable one yet.

    "Usable" is architecture AND tag: an image left over from before
    :data:`PLATFORM` was named is an arm64 Debian under the right tag, and
    inspecting it succeeds.  Building over it re-points the tag, so nothing
    is left behind but dangling layers.
    """
    if _image_field(".Architecture") == ARCH:
        return
    if log:
        log("[multi-boot] building the Linux toolbox image (once, a few "
            "minutes)...")
    ctx = os.path.join(cache_root(), "image")
    os.makedirs(ctx, exist_ok=True)
    with open(os.path.join(ctx, "Dockerfile"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(DOCKERFILE)
    # Long: on Apple silicon every apt-get in here runs emulated.
    r = _docker(["build", "--platform", PLATFORM, "-t", IMAGE, ctx],
                timeout=1800)
    if r.returncode != 0:
        raise RuntimeError("could not build the Linux toolbox image:\n"
                           + (r.stderr or r.stdout or "").strip()[-2000:])


def _running_state():
    """``(image id, {host directories})`` of the running container, or None
    when there is no container.

    The IMAGE ID and not the tag: a container started before this app
    version is still up, still named right and still mounted right, and is
    running the wrong-architecture image the tag used to point at.
    """
    r = _docker(["inspect", "-f",
                 "{{.Image}}{{range .Mounts}}\n{{.Source}}{{end}}",
                 CONTAINER], timeout=20)
    if r.returncode != 0:
        return None
    lines = (r.stdout or "").split("\n")
    if not lines or not lines[0].strip():
        return None
    return lines[0].strip(), set(x for x in lines[1:] if x.strip())


def ensure_container(paths, repo_src, log=None):
    """Make sure a container is up that can see every path in *paths*.

    Restarted when the mount set changes: a bind mount is fixed at ``docker
    run``, so a second run against an ISO on another volume would otherwise
    find nothing there.  And when the IMAGE changes, which is how a machine
    that already had an arm64 one stops using it (PAD-193).
    """
    reason = unavailable_reason()
    if reason:
        raise RuntimeError(reason)
    ensure_image(log)
    stage_rig(repo_src)
    want = mount_points(paths)
    have = _running_state()
    if (have is not None and have[0] == _image_field(".Id")
            and set(want) | {cache_root()} == have[1]):
        return                                          # already right
    _docker(["rm", "-f", CONTAINER], timeout=30)
    args = ["run", "-d", "--name", CONTAINER, "--privileged",
            "--platform", PLATFORM,
            "-v", "%s:/tmp" % cache_root()]
    for d in want:
        args += ["-v", "%s:/host%s" % (d, d)]
    args += [IMAGE, "sleep", "infinity"]
    r = _docker(args, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("could not start the Linux toolbox container:\n"
                           + (r.stderr or r.stdout or "").strip()[-2000:])


def exec_argv(line):
    """The argv that runs one shell line in the container.

    No ``sudo`` anywhere: the container's own user is root, which is what
    made this worth doing rather than teaching a GUI to ask for a password
    it could not have used.  ``argv[-1]`` stays the shell line, because the
    tab's Log echoes it with a ``$`` in front.
    """
    return ["docker", "exec", CONTAINER, "bash", "-lc", line]


def kill_running():
    """Stop whatever the container is running.

    ``Popen.kill()`` reaches the ``docker exec`` CLIENT and leaves the
    process inside the container alone - a cancelled build would otherwise
    go on restoring partitions with nothing watching it.
    """
    try:
        _docker(["exec", CONTAINER, "bash", "-lc",
                 "pkill -TERM -P 1 -f 'mkjjpmulti|mkmulticard|ensurejjpselect"
                 "|partclone|xorriso' || true"], timeout=20)
    except Exception:                                   # noqa: BLE001
        pass


def stop():
    """Remove the container (leaves the image and the cache alone)."""
    try:
        _docker(["rm", "-f", CONTAINER], timeout=30)
    except Exception:                                   # noqa: BLE001
        pass
