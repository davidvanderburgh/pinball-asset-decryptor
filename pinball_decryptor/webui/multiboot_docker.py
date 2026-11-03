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
import shlex
import shutil
import subprocess
import sys
import threading
import time

#: Bumped whenever DOCKERFILE changes.  The tag IS the cache key - ``docker
#: image inspect`` succeeds on a stale image built from an older Dockerfile,
#: so a new package list that kept the old tag would never reach anybody who
#: had already built one.
IMAGE = "pad-multiboot:5"
CONTAINER = "pad-multiboot-worker"

#: Named volume mounted at ``/root`` in the container so the unpacked Stern
#: Spike 2 rootfs (``/root/spike2root``, ~350 MB) and built selector
#: (``/root/emusrc``) survive container restarts and mount updates instead
#: of being re-extracted from the 8 GB card every time a folder is added.
ROOT_VOLUME = "pad-multiboot-root"

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
#:
#: ``gcc-arm-linux-gnueabihf``, ``libc6-dev-armhf-cross`` and
#: ``qemu-user-static`` ARE THE STERN SPIKE 2 MENU AND ITS PREVIEW.
#: ``ensureselect.sh`` cross-compiles the 32-bit ARM ``codeselect`` binary
#: that boots on the machine (``libc6-dev-armhf-cross`` is named beside the
#: cross compiler for the same ``--no-install-recommends`` reason as
#: ``libc6-dev``; see ``tools/spike2_emu/ensurebuild.sh``), and the tab's
#: preview renders its snapshot with ``qemu-arm-static -L ~/spike2root``.
#:
#: ``fonts-dejavu-core`` IS A BUILD TOOL HERE (PAD-194).  A Debian slim image
#: carries no fonts at all, and two separate things then have none:
#: ``make install PLATFORM=jjp`` copies the host's DejaVuSans-Bold.ttf beside
#: the menu program as ``font.ttf`` and simply skips it when the host has
#: none, and ``mkjjpmulti.py build`` then refuses outright ("--selector-dir
#: ... has no font.ttf and /usr/share/fonts/... is not on this host: the
#: selector needs a font").  The preview wants the same file - the conf it
#: writes names ``/var/tmp/jjpselect/jjpe/gen1/padselect/font.ttf`` - so
#: without this package a Mac gets no menu picture either.  --no-install-
#: recommends is what keeps fontconfig and the rest of a desktop out; this
#: is the ~1.5 MB of .ttf on its own.
#:
#: ``ffmpeg`` IS THE MENU'S MEDIA STEP (PAD-203).  ``mkjjpmulti.py media``
#: hands the picked art, music and animations to selectmedia.py, which
#: scales a still with ffmpeg or PIL and needs ffmpeg outright for any music
#: that is not already 44.1 kHz 16-bit, a frame of a video and every GIF.
#: With neither, the first picture refused ("neither ffmpeg nor PIL is
#: available to scale ...") and a Mac could not build a menu with art on it.
#:
#: ``gnupg`` IS A BARRELS OF FUN UPDATE (PAD-342).  A .fun is a GPG-symmetric
#: tarball: ``mkbofmulti.py`` decrypts the two the menu offers and encrypts the
#: one it writes, so without it a Mac's plan stopped at "this needs gpg".
DOCKERFILE = """\
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \\
        partclone e2fsprogs xorriso pigz gzip coreutils util-linux \\
        python3 bash make gcc libc6-dev \\
        gcc-arm-linux-gnueabihf libc6-dev-armhf-cross qemu-user-static \\
        fonts-dejavu-core ffmpeg gnupg \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp
CMD ["bash"]
"""

#: Rigs staged into the cache so the container can run them.  The app bundle
#: itself is NOT bind-mounted: /Applications is not one of the directories
#: Docker Desktop shares by default, and the JJP pipeline already answers
#: this the same way (``_stage_project_file`` copies partclone_to_raw.py
#: into the cache rather than mounting the bundle).
_RIGS = ("jjp_emu", "spike2_emu", "bof_emu", "dp_emu")

#: ...and the package's leaf modules a rig imports from a bare python3 (see
#: plugins/__init__.py): mkbofmulti.py reads both programs' Godot pack
#: directories with plugins.bof.pck_directory to make the delta that keeps a
#: BOF multi-boot update under FAT32's 4 GiB (PAD-342).  The app's own copy
#: is inside the bundle's archive, so the build ships these as files
#: (installer/build_macos.sh) and they are staged from there.  'auto' sound
#: decodes the game's own samples with plugins.bof.source_converter (and its
#: QOA decoder): without them a Mac build's media step failed with an
#: ImportError (COOLTOY, 2026-10-05).  Stern Spike 2's mkmulticard.py and
#: selectmedia.py likewise import plugins.stern's validator bypass, sidx,
#: ext4, adjustments, editions, factory_volume, shader_profile, explorer and
#: engine modules (plus their core leaf dependencies) under the container's
#: bare python3.
_PACKAGE_FILES = ("pinball_decryptor/plugins/bof/pck_directory.py",
                  "pinball_decryptor/plugins/bof/aes_py.py",
                  "pinball_decryptor/plugins/bof/source_converter.py",
                  "pinball_decryptor/plugins/bof/qoa_codec.py",
                  "pinball_decryptor/core/audio.py",
                  "pinball_decryptor/core/checksums.py",
                  "pinball_decryptor/core/colour_profile.py",
                  "pinball_decryptor/core/longpath.py",
                  "pinball_decryptor/core/rawdevice.py",
                  "pinball_decryptor/plugins/stern/adjustments.py",
                  "pinball_decryptor/plugins/stern/editions.py",
                  "pinball_decryptor/plugins/stern/engine.py",
                  "pinball_decryptor/plugins/stern/explorer.py",
                  "pinball_decryptor/plugins/stern/ext4.py",
                  "pinball_decryptor/plugins/stern/factory_volume.py",
                  "pinball_decryptor/plugins/stern/formats.py",
                  "pinball_decryptor/plugins/stern/games.py",
                  "pinball_decryptor/plugins/stern/menu_settings.py",
                  "pinball_decryptor/plugins/stern/progreloc.py",
                  "pinball_decryptor/plugins/stern/shader_profile.py",
                  "pinball_decryptor/plugins/stern/sidx.py",
                  "pinball_decryptor/plugins/stern/valpatch.py")

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
    for rel in _PACKAGE_FILES:
        src = os.path.join(repo_src, *rel.split("/"))
        if os.path.isfile(src):
            dst = os.path.join(dst_root, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
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


#: How long the image build may take before it is given up on.  On Apple
#: silicon every apt-get in it runs emulated, and a slow network makes the
#: 60 MB qemu-user-static alone a minute or more.
BUILD_TIMEOUT = 3600

#: How often a build that is still going says so in the Log.
BUILD_HEARTBEAT = 30

#: The ``docker build`` in flight, so :func:`cancel_build` can stop it.
_BUILD = {"proc": None}


def _docker_build(args, on_line, timeout):
    """Run ``docker`` + *args*, every output line to *on_line*.  Returns
    ``(returncode, the last 2000 characters it printed)``.

    Streamed rather than captured: :func:`_docker` waits for the end in
    silence, and a build is minutes of it.  Killing the client is what
    stops the build (BuildKit cancels a build whose client went away), so
    :data:`_BUILD` holds it for :func:`cancel_build`.
    """
    proc = subprocess.Popen(["docker"] + list(args), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    _BUILD["proc"] = proc
    timer = threading.Timer(timeout, proc.kill)
    timer.daemon = True
    timer.start()
    tail = []
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            tail.append(line)
            if len(tail) > 60:
                del tail[0]
            on_line(line)
        rc = proc.wait()
    finally:
        timer.cancel()
        _BUILD["proc"] = None
    return rc, "\n".join(tail)[-2000:]


def cancel_build():
    """Stop the image build in flight, if there is one.  True when there
    was."""
    proc = _BUILD["proc"]
    if proc is None:
        return False
    try:
        proc.kill()
    except Exception:                                   # noqa: BLE001
        pass
    return True


def _minutes(secs):
    m, s = divmod(int(secs), 60)
    return "%dm %02ds" % (m, s) if m else "%ds" % s


def ensure_image(log=None):
    """Build :data:`IMAGE` if this machine has not got a usable one yet.

    "Usable" is architecture AND tag: an image left over from before
    :data:`PLATFORM` was named is an arm64 Debian under the right tag, and
    inspecting it succeeds.  Building over it re-points the tag, so nothing
    is left behind but dangling layers.

    A WORKER THREAD'S JOB (PAD-911).  It is minutes - on Apple silicon
    every apt-get in it runs emulated - and run on the app's main thread it
    froze the window for all of them: the Log said nothing, macOS called
    the app not responding, and quitting it cancelled the build ("failed
    to solve: Canceled: context canceled"), so the next Build started from
    nothing again.  So it says it is still going every
    :data:`BUILD_HEARTBEAT` seconds, with the step it is on, and
    :func:`cancel_build` stops it.
    """
    if _image_field(".Architecture") == ARCH:
        return
    if log:
        log("building the Linux toolbox image. This is once "
            "per app update that changes it, and takes a few minutes (10 "
            "or more on a Mac with Apple silicon); the app stays usable and "
            "Cancel stops it.")
    ctx = os.path.join(cache_root(), "image")
    os.makedirs(ctx, exist_ok=True)
    with open(os.path.join(ctx, "Dockerfile"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(DOCKERFILE)
    start = time.monotonic()
    state = {"said": start, "last": ""}

    def on_line(line):
        if line.strip():
            state["last"] = line.strip()
        now = time.monotonic()
        if log and now - state["said"] >= BUILD_HEARTBEAT:
            state["said"] = now
            log("still building the Linux toolbox image (%s): "
                "%s" % (_minutes(now - start), state["last"][:120]))
    rc, tail = _docker_build(["build", "--platform", PLATFORM, "-t", IMAGE,
                              ctx], on_line, BUILD_TIMEOUT)
    if rc != 0:
        raise RuntimeError("could not build the Linux toolbox image:\n"
                           + tail.strip())
    if log:
        log("the Linux toolbox image is built (%s)."
            % _minutes(time.monotonic() - start))


def _running_state():
    """``(image id, {host directories})`` of the running container, or None
    when there is no container.

    The IMAGE ID and not the tag: a container started before this app
    version is still up, still named right and still mounted right, and is
    running the wrong-architecture image the tag used to point at.
    """
    r = _docker(["inspect", "-f",
                 "{{.State.Running}}\n{{.Image}}"
                 "{{range .Mounts}}\n{{.Source}}{{end}}",
                 CONTAINER], timeout=20)
    if r.returncode != 0:
        return None
    lines = (r.stdout or "").split("\n")
    # A STOPPED container is no container (PAD-203).  Quitting Docker
    # Desktop or restarting the Mac stops it and leaves it there, still
    # named right, mounted right and on the right image, so the checks
    # below called it "already right" and every step after that died on
    # "Error response from daemon: container ... is not running".
    if len(lines) < 2 or lines[0].strip() != "true" or not lines[1].strip():
        return None
    # Named volumes (such as ROOT_VOLUME at /root) appear in .Mounts under
    # the VM's /var/lib/... storage path; only host bind mounts belong in the
    # set compared against mount_points(paths) | {cache_root()}.
    return (lines[1].strip(),
            set(x.strip() for x in lines[2:]
                if x.strip() and not x.strip().startswith("/var/lib/")))


#: Left in a folder with nothing in it to look for from inside the
#: container (an output folder, usually), and removed straight after.
_PROBE = ".pad-multiboot-share-check"


def _probe_name(d):
    """``(name, made)``: an entry of host directory *d* to look for in the
    container, and whether it was made for the purpose; ``(None, False)``
    when there is nothing to look for and nothing could be made."""
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return None, False
    if names:
        return names[0], False
    try:
        with open(os.path.join(d, _PROBE), "w"):
            pass
    except OSError:
        return None, False
    return _PROBE, True


def unseen_mounts(dirs):
    """The host directories in *dirs* that the container cannot see.

    A BIND MOUNT OF A FOLDER THE ENGINE DOES NOT SHARE DOES NOT FAIL
    (PAD-885).  The engine's Linux VM has a filesystem of its own, and
    docker mounts the VM's folder of that name, which it makes, empty, when
    the VM has none.  colima - what the Emulate tab's "Set up emulator..."
    installs - shares the home folder and nothing else, so a run against
    ISOs on /Volumes/<disk> started fine and every tool then found nothing:
    no input ISOs, and an output written inside the VM where nobody would
    ever find it.  (Docker Desktop refuses such a mount at ``docker run``,
    "Mounts denied", which already stopped the run.)

    So each mounted folder is looked at from inside: an entry the host has
    there must be in the container's copy too.  An empty folder gets a
    marker file for the length of the check.  A folder this cannot look at,
    or a container that cannot be asked, is left to the steps themselves
    rather than called unshared.
    """
    checks, made = [], []
    for d in dirs:
        name, new = _probe_name(d)
        if name is None:
            continue
        checks.append((d, name))
        if new:
            made.append(os.path.join(d, name))
    try:
        if not checks:
            return []
        line = "; ".join(
            "[ -e %s ] || echo %s"
            % (shlex.quote(container_path(d) + "/" + name), shlex.quote(d))
            for d, name in checks)
        try:
            r = _docker(["exec", CONTAINER, "bash", "-c", line], timeout=30)
        except Exception:                               # noqa: BLE001
            return []
        if r.returncode != 0:
            return []
        out = set(x.strip() for x in (r.stdout or "").split("\n"))
        return [d for d, _ in checks if d in out]
    finally:
        for f in made:
            try:
                os.remove(f)
            except OSError:
                pass


def _engine_name():
    """Which engine docker is talking to: "colima" / "colima-<profile>"
    (the docker context colima makes, or its VM's name), "docker-desktop",
    or whatever else ``docker info`` calls the machine; "" when neither
    answers.  Lima, under colima, may name the VM "lima-colima[-<p>]"."""
    names = []
    for args in (["context", "show"], ["info", "-f", "{{.Name}}"]):
        try:
            r = _docker(args, timeout=20)
        except Exception:                               # noqa: BLE001
            continue
        if r.returncode == 0 and (r.stdout or "").strip():
            names.append((r.stdout or "").strip())
    for n in names:
        if n.startswith("lima-colima"):
            n = n[len("lima-"):]
        if n == "colima" or n.startswith("colima-"):
            return n
    return names[-1] if names else ""


def _share_roots(unseen):
    """The folders to share so the container sees *unseen*: /Volumes whole
    for anything on it (so the next disk plugged in is seen too), any other
    folder by name, and nothing for what is under home (always shared)."""
    home = _norm(os.path.expanduser("~"))
    roots = []
    for d in unseen:
        if d == home or d.startswith(home + "/"):
            continue                    # the $HOME mount has it
        r = "/Volumes" if d.startswith("/Volumes/") else d
        if r not in roots:
            roots.append(r)
    return roots


def colima_fix(unseen):
    """The commands that make colima share *unseen*: ``[stop, start]``
    argv, or None when the engine is not colima or the command is not
    there.  The start keeps every folder the profile already shares
    (:func:`emulate_core.colima_start_argv`)."""
    from .emulate_core import colima_start_argv, which_tool
    engine = _engine_name()
    if not (engine == "colima" or engine.startswith("colima-")):
        return None
    colima = which_tool("colima")
    if not colima:
        return None
    profile = engine[len("colima-"):]
    p = ["-p", profile] if profile else []
    return [[colima, "stop"] + p,
            colima_start_argv(colima, profile, _share_roots(unseen))]


class Unshared(RuntimeError):
    """The container cannot see *unseen*; ``str()`` is what to tell the
    user, and ``fix`` the :func:`colima_fix` commands that would share them
    (None when the engine is not colima)."""

    def __init__(self, unseen):
        self.unseen = list(unseen)
        self.fix = colima_fix(self.unseen)
        super().__init__(unshared_reason(self.unseen))


def share_folders(fix, log=None):
    """Run *fix* (:func:`colima_fix`), every line of it into *log*.  True
    when every command succeeded.  Minutes the first time, so a worker
    thread's job."""
    for argv in fix:
        if log:
            log("$ " + " ".join(shlex.quote(a) for a in argv))
        try:
            p = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace")
        except OSError as exc:
            if log:
                log(str(exc))
            return False
        for line in p.stdout:
            if log:
                log(line.rstrip("\n"))
        if p.wait() != 0:
            return False
    return True


def unshared_reason(unseen):
    """What to tell the user when the container cannot see *unseen*.

    For colima, the commands that share them.  ``--mount`` REPLACES
    colima's mount list rather than adding to it, so home is named as well
    or the cache - and the staged rig with it - would vanish next.
    /Volumes is shared whole, so the next disk plugged in is seen too.
    """
    folders = ", ".join(unseen)
    it, that = (("it", "that folder") if len(unseen) == 1
                else ("them", "those folders"))
    engine = _engine_name()
    if engine == "colima" or engine.startswith("colima-"):
        profile = engine[len("colima-"):]
        p = " -p %s" % shlex.quote(profile) if profile else ""
        roots = _share_roots(unseen)
        mounts = "".join(" --mount %s" % shlex.quote(r + ":w")
                         for r in roots)
        return ("The Linux toolbox cannot see %s: Colima shares only your "
                "home folder with its Linux machine, so the tools would find "
                "%s empty. Share %s by restarting Colima from "
                "Terminal:\n\n    colima stop%s\n    colima start%s "
                "--mount \"$HOME:w\"%s\n\nthen build again. Or move the "
                "files into your home folder."
                % (folders, that, it, p, p, mounts))
    if engine == "docker-desktop":
        return ("The Linux toolbox cannot see %s: Docker Desktop does not "
                "share %s. Add %s under Settings > Resources > File sharing, "
                "then build again. Or move the files into your home folder."
                % (folders, it, it))
    return ("The Linux toolbox cannot see %s: your container engine does "
            "not share %s with its Linux machine, so the tools would find "
            "%s empty. Add %s to the engine's shared folders, then "
            "build again. Or move the files into your home folder."
            % (folders, it, that, it))


def ensure_container(paths, repo_src, log=None):
    """Make sure a container is up that can see every path in *paths*.

    Restarted when the mount set changes: a bind mount is fixed at ``docker
    run``, so a second run against an ISO on another volume would otherwise
    find nothing there.  And when the IMAGE changes, which is how a machine
    that already had an arm64 one stops using it (PAD-193).

    And it has to SEE what it mounts (PAD-885, :func:`unseen_mounts`):
    checked on every run, a container kept from an earlier one included,
    since that one was mounted the same way.  One that cannot is removed
    and the run stops here with the way to share the folders.

    Under :data:`_LOCK`: a Build asked for while a preview's worker is in
    :func:`ensure_ready_container` would otherwise ``rm -f`` and ``run`` the
    same container name beside it, and one of the two ``docker run`` calls
    fails on the name.
    """
    with _LOCK:
        _ensure_container(paths, repo_src, log)
        _PREVIEW_REFUSED.clear()
        _BUILD_FAILED.clear()


def _ensure_container(paths, repo_src, log):
    reason = unavailable_reason()
    if reason:
        raise RuntimeError(reason)
    ensure_image(log)
    stage_rig(repo_src)
    _STAGED.add(repo_src)
    want = mount_points(paths)
    have = _running_state()
    if (have is None or have[0] != _image_field(".Id")
            or set(want) | {cache_root()} != have[1]):
        _docker(["rm", "-f", CONTAINER], timeout=30)
        args = ["run", "-d", "--name", CONTAINER, "--privileged",
                "--platform", PLATFORM,
                "-v", "%s:/tmp" % cache_root(),
                "-v", "%s:/root" % ROOT_VOLUME]
        for d in want:
            args += ["-v", "%s:/host%s" % (d, d)]
        args += [IMAGE, "sleep", "infinity"]
        r = _docker(args, timeout=60)
        if r.returncode != 0:
            raise RuntimeError("could not start the Linux toolbox container:\n"
                               + (r.stderr or r.stdout or "").strip()[-2000:])
    unseen = unseen_mounts([cache_root()] + want)
    if unseen:
        _docker(["rm", "-f", CONTAINER], timeout=30)
        raise Unshared(unseen)


def ensure_ready_container(paths, repo_src, log=None):
    """Build :data:`IMAGE` if needed and start or remount the container.
    True when a container that serves *paths* is up afterwards.

    Background warm-up, preview and size-check runs call this on a worker
    thread so the toolbox is ready before the user presses Build.  When the
    container is already up on this image with these folders mounted it
    stops after one ``docker inspect`` and one ``docker image inspect``: no
    ``docker info``, and no copy of the rigs (``tools/spike2_emu`` alone is
    ~50 MB) - :func:`stage_rig` runs once per app session here, and on every
    writing run as before.

    A mount set the engine could not see (:class:`Unshared`) or a failed
    image build is not tried again on the next redraw: that would retry on
    every keystroke.  A writing run (:func:`ensure_container`) clears both.
    """
    want = frozenset(mount_points(paths))
    with _LOCK:
        try:
            have = _running_state()
            if (have is not None and have[0] == _image_field(".Id")
                    and set(want) | {cache_root()} == have[1]):
                if repo_src not in _STAGED:
                    stage_rig(repo_src)
                    _STAGED.add(repo_src)
                return True
            if want in _PREVIEW_REFUSED or IMAGE in _BUILD_FAILED:
                return False
            if unavailable_reason():
                return False
            if not want:
                # Opening the tab with an empty form warms the image and stages
                # the rig in the background without starting a mountless
                # container that the first picked image would have to replace.
                ensure_image(log)
                if repo_src not in _STAGED:
                    stage_rig(repo_src)
                    _STAGED.add(repo_src)
                return True
            if log:
                log("starting the Linux toolbox container"
                    + (" (mounting %s)..." % ", ".join(sorted(want))
                       if want else "..."))
            _ensure_container(paths, repo_src, log)
        except Unshared:
            _PREVIEW_REFUSED.add(want)
            return False
        except Exception:                               # noqa: BLE001
            _BUILD_FAILED.add(IMAGE)
            return False
    return True


#: Held by :func:`ensure_container` and :func:`ensure_ready_container`: the
#: UI thread's writing run and the preview's worker share one container.
_LOCK = threading.RLock()

#: Mount sets a preview found the engine could not see (see above).
_PREVIEW_REFUSED = set()

#: Images whose background build failed in this session (retried on Build).
_BUILD_FAILED = set()

#: Repo sources :func:`stage_rig` has copied in this app session.
_STAGED = set()


def exec_argv(line):
    """The argv that runs one shell line in the container.

    No ``sudo`` anywhere: the container's own user is root, which is what
    made this worth doing rather than teaching a GUI to ask for a password
    it could not have used.  ``argv[-1]`` stays the shell line, because the
    tab's Log echoes it with a ``$`` in front.
    """
    return ["docker", "exec", CONTAINER, "bash", "-lc", line]


# every tool a multi-boot run starts inside the container (see kill_running)
KILL_PATTERN = (r"[m]kjjpmulti|[m]kmulticard|[e]nsurejjpselect|[m]ount\.sh"
                "|[p]artclone|[x]orriso")
KILL_LINE = ("pkill -TERM -f '%s'; sleep 2; pkill -KILL -f '%s'; true"
             % (KILL_PATTERN, KILL_PATTERN))


def kill_running():
    """Stop whatever the container is running.

    ``Popen.kill()`` reaches the ``docker exec`` CLIENT and leaves the
    process inside the container alone - a cancelled build would otherwise
    go on restoring partitions with nothing watching it.

    NOT ``pkill -P 1`` (PAD-218): a ``docker exec`` process's parent is
    outside the container (it reads as 0), and every tool is a grandchild of
    that, so ``-P 1`` matched nothing and Cancel stopped nothing.  The
    cancelled root restore went on, the next run restored into the same
    file beside it, and the first one's rename handed over the second's
    half-written root - which every later build then trusted.  So: match by
    name, whatever the parent, and ``mount.sh`` too (it is what renames a
    finished restore into place).  The ``[x]`` brackets keep the pattern
    from matching this very ``bash -lc`` line, which holds its text.
    """
    try:
        _docker(["exec", CONTAINER, "bash", "-lc", KILL_LINE], timeout=20)
    except Exception:                                   # noqa: BLE001
        pass


def stop():
    """Remove the container (leaves the image and the cache alone)."""
    try:
        _docker(["rm", "-f", CONTAINER], timeout=30)
    except Exception:                                   # noqa: BLE001
        pass
