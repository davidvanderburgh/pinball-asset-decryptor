"""The Multi-boot tab on macOS: the Linux tools run in a container (PAD-192).

It LOOKS like a password problem - the reporter's log is twenty repetitions
of "sudo: a password is required" - and it is not one.  The steps that write
a card restore ext4 partitions, and macOS has no losetup, no ext4 in the
kernel and no partclone, so root would only have moved the failure to
"missing tool(s)".  It gets a Linux instead, the way Windows gets WSL.

Nothing here runs Docker.  What is asserted is the argv each step would run,
the path mapping, the bind mounts a run would ask for, and the contents of
the image - the parts that can be checked without a Mac.  The parts that
cannot (Docker Desktop's file sharing, loop devices in its VM, the menu
program's compile) are called out in multiboot_docker's own docstring.
"""
import hashlib
import os
import re
import shlex
import subprocess
import sys
from dataclasses import replace

import pytest

from pinball_decryptor.webui import multiboot_docker as D
from pinball_decryptor.webui import multiboot_core as mt
from pinball_decryptor.webui.multiboot_core import ImageRow, MultibootForm

ISO0 = "/Volumes/Mac SSD/Sonichedge/Sonic-v00.930.iso"
ISO1 = "/Volumes/Mac SSD/sonichedgehogcode/build/Sonic-v00.930-modified.iso"


@pytest.fixture
def mac(monkeypatch, tmp_path):
    """Pretend to be macOS, with the cache somewhere harmless."""
    monkeypatch.setattr(mt.sys, "platform", "darwin")
    monkeypatch.setattr(D.sys, "platform", "darwin")
    monkeypatch.setattr(D, "cache_root", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(D, "_STAGED", set())
    monkeypatch.setattr(D, "_PREVIEW_REFUSED", set())
    monkeypatch.setattr(D, "_BUILD_FAILED", set())
    # the build streams through its own Popen; route it to whatever _docker
    # fake the test installs, so no test here ever runs a real docker build
    def build(args, on_line, timeout):
        r = D._docker(args, timeout=timeout)
        return r.returncode, (r.stderr or r.stdout or "")
    monkeypatch.setattr(D, "_docker_build", build)
    os.makedirs(str(tmp_path / "cache"), exist_ok=True)
    return tmp_path


# --------------------------------------------------------------------- argv

def test_a_root_step_carries_no_sudo_at_all(mac):
    """The container's own user is root.  That is what makes this worth
    doing rather than teaching a GUI to ask for a password that could not
    have been spent on a losetup which is not there."""
    argv = mt.wsl_shell_root("make -C x")
    assert argv[:3] == ["docker", "exec", D.CONTAINER]
    assert "sudo" not in argv
    # The Log echoes argv[-1] with a "$ " in front, so the line stays last.
    assert argv[-1] == "make -C x"
    assert mt.wsl_shell("make -C x") == argv, \
        "user and root steps are the same argv here"


def test_linux_and_windows_are_untouched(monkeypatch):
    monkeypatch.setattr(mt.sys, "platform", "linux")
    monkeypatch.setattr(D.sys, "platform", "linux")
    assert mt.wsl_shell("x") == ["bash", "-lc", "x"]
    assert mt.wsl_shell_root("x") == ["sudo", "-n", "bash", "-lc", "x"]


# --------------------------------------------------------------------- paths

def test_a_host_path_is_seen_through_the_bind_mount(mac):
    assert mt.wsl(ISO0) == "/host" + ISO0
    assert D.container_path("/Users/x/a.iso") == "/host/Users/x/a.iso"


def test_the_cache_is_the_containers_tmp(mac):
    """It is bind-mounted at /tmp, so a cache path must NOT come back with a
    /host prefix - that directory does not exist in the container."""
    cache = D.cache_root()
    assert D.container_path(cache) == "/tmp"
    assert D.container_path(os.path.join(cache, "repo", "tools")) \
        == "/tmp/repo/tools"
    assert not D.container_path(os.path.join(cache, "x")).startswith("/host")


def test_the_mapping_round_trips(mac):
    for host in (ISO0, os.path.join(D.cache_root(), "repo")):
        assert D.host_from_container(D.container_path(host)) == D._norm(host)


def test_the_tools_are_run_from_the_staged_rig(mac):
    """Docker Desktop does not share /Applications, so the .app bundle is
    never bind-mounted; the rig is copied into the cache and run from
    there, which is what the JJP pipeline already does for its own
    scripts."""
    assert mt.repo_dir() == D.staged_repo()
    assert mt.wsl(mt.repo_dir()) == "/tmp/repo"
    # ...and the REAL checkout is still what the copy is made from.
    assert mt.rig_repo_dir() != D.staged_repo()


def test_the_cache_dir_argument_is_inside_the_container(mac):
    """--cache-dir used the host's temp, which on macOS is a /var/folders
    path Docker Desktop does not share."""
    args = mt.cache_dir_args()
    assert args[0] == "--cache-dir"
    assert args[1].startswith("/tmp/"), args[1]


# -------------------------------------------------------------------- mounts

def test_a_run_mounts_the_directories_its_isos_live_in(mac):
    """DIRECTORIES, not the files: the output ISO does not exist when the
    container starts, and a bind mount of a missing file makes a directory
    where the file should go."""
    mounts = D.mount_points([ISO0, ISO1, None, ""])
    assert "/Volumes/Mac SSD/Sonichedge" in mounts
    assert "/Volumes/Mac SSD/sonichedgehogcode/build" in mounts
    assert not any(m.endswith(".iso") for m in mounts)


def test_the_cache_is_not_mounted_twice(mac):
    """It already goes in as /tmp."""
    inside = os.path.join(D.cache_root(), "repo", "tools")
    assert D.mount_points([inside]) == []


def test_a_directory_inside_another_is_dropped(mac):
    """Docker is not handed the same tree twice."""
    mounts = D.mount_points(["/Volumes/A/one/x.iso",
                             "/Volumes/A/one/deep/y.iso"])
    assert mounts == ["/Volumes/A/one"]


def test_the_panel_offers_every_path_a_run_touches(mac):
    """Over-listing is free; under-listing is a tool that cannot see its
    own ISO."""
    panel = mt.MultibootPanel.__new__(mt.MultibootPanel)
    form = MultibootForm(images=[ImageRow(path=ISO0), ImageRow(path=ISO1)],
                         out="/Volumes/Out/multi.iso", platform="jjp",
                         selector_dir="/Volumes/Sel")
    panel.form = lambda: form
    panel.media_dir = lambda: "/Volumes/Media"
    paths = panel._run_paths()
    for want in (ISO0, ISO1, "/Volumes/Out/multi.iso", "/Volumes/Sel",
                 "/Volumes/Media"):
        assert want in paths, want


def test_the_menus_pictures_and_music_are_mounted_too(mac):
    """PAD-196, cooltoy's Sonic: a picture and a song per image, both on his
    Desktop.  Only the ISOs' folders were mounted, so the prepare inside the
    container said "art 0: /host/Users/.../x.jpg is not a file", no
    media.json was written and the build made a text-only menu."""
    panel = mt.MultibootPanel.__new__(mt.MultibootPanel)
    desk = "/Users/cooltoy/Desktop"
    form = MultibootForm(
        images=[ImageRow(path=ISO0, art=desk + "/logo.jpg",
                         music=desk + "/Fanfare.wav",
                         confirm=desk + "/go.wav"),
                ImageRow(path=ISO1, art="video frame",
                         art_video="/Volumes/Clips/intro.mov",
                         anim=desk + "/loop.gif", music="none")],
        out="/Volumes/Out/multi.iso", platform="jjp",
        sound_move="/Users/cooltoy/Music/move.wav", sound_confirm="synth",
        selector_dir="/Volumes/Sel")
    panel.form = lambda: form
    panel.media_dir = lambda: "/Volumes/Media"
    paths = panel._run_paths()
    for want in (desk + "/logo.jpg", desk + "/Fanfare.wav", desk + "/go.wav",
                 "/Volumes/Clips/intro.mov", desk + "/loop.gif",
                 "/Users/cooltoy/Music/move.wav"):
        assert want in paths, want
    # the words are not files, and must not become mounts
    for word in ("none", "synth", "video frame", "auto"):
        assert word not in paths, word
    mounts = D.mount_points(paths)
    for d in (desk, "/Users/cooltoy/Music", "/Volumes/Clips"):
        assert any(d == m or d.startswith(m + "/") for m in mounts), d


def test_a_form_with_any_picture_or_sound_wants_media():
    """What decides whether a build with no media.json prepares one itself
    (PAD-196) instead of quietly building a text-only menu."""
    none = MultibootForm(images=[ImageRow(path=ISO0, art="none"),
                                 ImageRow(path=ISO1, art="none")],
                         sound_move="none", sound_confirm="none")
    assert not mt.form_wants_media(none)
    art = replace(none, images=[ImageRow(path=ISO0, art="auto"),
                                ImageRow(path=ISO1, art="none")])
    assert mt.form_wants_media(art)
    music = replace(none, images=[ImageRow(path=ISO0, art="none",
                                           music="/x/song.wav"),
                                  ImageRow(path=ISO1, art="none")])
    assert mt.form_wants_media(music)
    assert mt.form_wants_media(replace(none, sound_move="synth"))


def _build_panel(monkeypatch, tmp_path, form):
    """A panel whose Build & verify only records the steps it would run."""
    monkeypatch.setattr(mt, "validate_form", lambda f, **k: [])
    monkeypatch.setattr(mt, "rebuild_blockers", lambda f: [])
    panel = mt.MultibootPanel.__new__(mt.MultibootPanel)
    panel._loaded_card = None
    panel.form = lambda: form
    panel.media_dir = lambda: str(tmp_path / "media")
    panel._update_edit_status = lambda: None
    panel._plan_step = None
    said = []
    panel._ok = said.append
    panel._error = said.append
    ran = {}

    def run(cmds, on_step=None, on_done=None):
        ran["labels"] = [label for label, _ in cmds]
        ran["done"] = on_done
        return True
    panel._run_commands = run
    return panel, ran, said


def test_a_build_with_no_prepared_media_prepares_it(monkeypatch, tmp_path):
    """PAD-196: the preview's prepare had failed, so there was no media.json
    and the build made a text-only menu - "Card built and verified ... (no
    prepared media - text-only menu)" - for a form that named a picture and
    a song for every image.  The build prepares the media itself now."""
    form = MultibootForm(
        images=[ImageRow(path=ISO0, art="/x/logo.jpg", music="/x/a.wav"),
                ImageRow(path=ISO1, art="auto")],
        out=str(tmp_path / "multi.iso"), platform="jjp")
    assert form.media_dir == ""       # what form() says with no media.json
    panel, ran, said = _build_panel(monkeypatch, tmp_path, form)
    panel._build_card()
    assert "prepare" in ran["labels"]
    assert ran["labels"].index("prepare") < ran["labels"].index("build")
    assert form.media_dir == str(tmp_path / "media")
    ran["done"](0, None, {})
    assert not any("text-only" in s for s in said), said


def test_a_text_only_form_still_builds_text_only(monkeypatch, tmp_path):
    """...and one that asked for nothing to look at or hear is not handed a
    prepare it has no use for."""
    form = MultibootForm(
        images=[ImageRow(path=ISO0, art="none"),
                ImageRow(path=ISO1, art="none")],
        sound_move="none", sound_confirm="none",
        out=str(tmp_path / "multi.iso"), platform="jjp")
    panel, ran, said = _build_panel(monkeypatch, tmp_path, form)
    panel._build_card()
    assert "prepare" not in ran["labels"]
    assert form.media_dir == ""


# --------------------------------------------------------------------- image

def test_the_image_is_debian_because_the_menu_program_is_a_glibc_link():
    """THE REASON THIS IS NOT THE JJP PLUGIN'S CONTAINER.  That one is
    Alpine, and ensurejjpselect.sh links jjpselect with -nostdlib plus the
    host gcc's crt files and `-print-file-name=libc_nonshared.a` - a glibc
    artefact musl does not have.  `apk add gcc make` would not have fixed
    it, and a writing run hard-fails when that compile fails."""
    assert "debian" in D.DOCKERFILE.lower()
    assert "alpine" not in D.DOCKERFILE.lower()
    # gcc AND libc6-dev: install_prerequisites_linux.sh names the pair
    # because gcc only *recommends* libc6-dev, and the link needs its crt
    # files and libc_nonshared.a.
    for pkg in ("gcc", "libc6-dev", "make"):
        assert pkg in D.DOCKERFILE, pkg


def test_the_image_carries_what_mkjjpmulti_asks_need_tools_for():
    """build_iso/inject_iso/verify_iso between them want partclone.ext4,
    partclone.restore, gunzip, split, e2fsck, losetup, mount, umount,
    debugfs, xorriso and cp - i.e. these packages."""
    for pkg in ("partclone", "e2fsprogs", "xorriso", "util-linux",
                "coreutils", "gzip", "python3"):
        assert pkg in D.DOCKERFILE, pkg


def test_the_image_carries_a_font_because_a_slim_debian_has_none():
    """PAD-194.  ``make install PLATFORM=jjp`` lays DejaVuSans-Bold.ttf down
    beside the menu program as font.ttf and SKIPS IT SILENTLY when the host
    has not got the font; ``mkjjpmulti.py build`` then refuses outright, and
    the preview's conf names a font.ttf nobody wrote.  debian:bookworm-slim
    ships no fonts at all, so this package is as much a build tool here as
    gcc is - and --no-install-recommends is what keeps the rest of a desktop
    out of the image."""
    assert "fonts-dejavu-core" in D.DOCKERFILE
    assert "--no-install-recommends" in D.DOCKERFILE


def test_the_image_carries_ffmpeg_for_the_menu_media():
    """PAD-203.  The media step scales the picked art with ffmpeg or PIL
    and needs ffmpeg for music, video frames and GIFs; the image had
    neither, so a Mac's build refused at "neither ffmpeg nor PIL is
    available to scale .../Sonic_Pinball_Feature-800x445.jpg"."""
    assert "ffmpeg" in D.DOCKERFILE


def test_the_image_carries_the_arm_toolchain_and_qemu_for_stern_spike2():
    """Stern Spike 2's ensureselect.sh cross-compiles the 32-bit ARM
    codeselect binary with arm-linux-gnueabihf-gcc (needing
    libc6-dev-armhf-cross explicitly because --no-install-recommends skips
    recommended packages), and the preview renders its snapshot with
    qemu-arm-static."""
    assert "gcc-arm-linux-gnueabihf" in D.DOCKERFILE
    assert "libc6-dev-armhf-cross" in D.DOCKERFILE
    assert "qemu-user-static" in D.DOCKERFILE


#: (tag, sha256 of DOCKERFILE) as they were last agreed.  A machine that has
#: already built an image is offered the tag, not the file: ``ensure_image``
#: asks ``docker image inspect`` about IMAGE and returns happily, so a changed
#: package list under an unchanged tag reaches nobody who needs it - which is
#: the mistake PAD-194's fix would have made.  Change one, change both.
_IMAGE_AS_AGREED = (
    "pad-multiboot:5",
    "68307675b7e90eba9c7e3c40e0430119caf79233cb698ff5a86917963164e79e",
)


def test_a_new_package_list_reaches_a_machine_that_already_built_one():
    """The tag is the cache key, so a changed Dockerfile has to change it."""
    digest = hashlib.sha256(D.DOCKERFILE.encode("utf-8")).hexdigest()
    assert (D.IMAGE, digest) == _IMAGE_AS_AGREED, (
        "DOCKERFILE changed: bump IMAGE's tag and put both here (%r, %r)"
        % (D.IMAGE, digest))


def test_the_image_tag_is_versioned():
    """`docker image inspect` succeeds on a stale image built from an older
    Dockerfile, so a new package list that kept the old tag would never
    reach anybody who had already built one."""
    assert ":" in D.IMAGE and D.IMAGE.rsplit(":", 1)[1]


# ------------------------------------------------------------- architecture

class _Fake:
    """A stand-in for :func:`multiboot_docker._docker` that records every
    call and answers ``image inspect`` / ``inspect`` from *state*."""

    def __init__(self, arch="", image_id="sha256:new", container=None,
                 volumes=()):
        self.arch = arch                # "" = no image on this machine
        self.image_id = image_id
        self.container = container      # (image id, {mounts}) or None
        self.volumes = set(volumes)     # named-volume sources, not binds
        self.running = "true"           # .State.Running of that container
        self.calls = []

    def __call__(self, args, timeout=30):
        args = list(args)
        self.calls.append(args)
        out, rc = "", 0
        if args[:2] == ["image", "inspect"]:
            if not self.arch:
                rc = 1
            elif "{{.Architecture}}" in args:
                out = self.arch
            elif "{{.Id}}" in args:
                out = self.image_id
        elif args[0] == "inspect":
            if self.container is None:
                rc = 1
            else:
                mounts = set(self.container[1])
                if 'eq .Type "bind"' not in " ".join(args):
                    mounts |= self.volumes
                out = "\n".join([self.running, self.container[0]]
                                + sorted(mounts))
        elif args[0] == "build":
            self.arch = D.ARCH

        class R:
            returncode = rc
            stdout = out
            stderr = ""
        return R()


def test_the_image_is_built_for_x86_64_on_every_mac(mac, monkeypatch):
    """THE BUG (PAD-193).  An Apple-silicon Mac builds an arm64 Debian
    unless it is told otherwise, and jjpselect is a native x86-64 link
    against the card's own usr/lib/x86_64-linux-gnu: the reporter's log is
    a page of "ld: skipping incompatible ... libc.so.6" and then "make:
    *** [jjpselect] Error 1".  The preview RUNS that binary afterwards, so
    a cross-compiler would not have been enough either."""
    fake = _Fake(arch="")               # nothing built yet
    monkeypatch.setattr(D, "_docker", fake)
    D.ensure_image()
    build = [c for c in fake.calls if c and c[0] == "build"]
    assert build, fake.calls
    assert "--platform" in build[0] and D.PLATFORM in build[0]
    assert D.PLATFORM == "linux/amd64"


def test_an_arm64_image_left_over_is_rebuilt_not_reused(mac, monkeypatch):
    """The tag alone cannot be the cache key here: a machine that wrote a
    card before this fix has an arm64 image under the right name, and
    `docker image inspect` reports it as present and healthy."""
    fake = _Fake(arch="arm64")
    monkeypatch.setattr(D, "_docker", fake)
    D.ensure_image()
    assert any(c[0] == "build" for c in fake.calls), \
        "an arm64 image was accepted as the toolbox"

    fake = _Fake(arch=D.ARCH)           # ...and the right one is kept
    monkeypatch.setattr(D, "_docker", fake)
    D.ensure_image()
    assert not any(c[0] == "build" for c in fake.calls)


def test_the_container_is_run_for_x86_64_too(mac, monkeypatch):
    """--platform on the build settles the image; the container that runs
    it needs it as well, or docker picks the host's again."""
    fake = _Fake(arch=D.ARCH)
    monkeypatch.setattr(D, "_docker", fake)
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    monkeypatch.setattr(D, "stage_rig", lambda src: D.staged_repo())
    D.ensure_container([ISO0], "/repo")
    run = [c for c in fake.calls if c and c[0] == "run"]
    assert run, fake.calls
    assert "--platform" in run[0] and D.PLATFORM in run[0]


def test_a_container_on_the_old_image_is_replaced(mac, monkeypatch):
    """Same mounts, same name, wrong architecture: the mount set alone said
    "already right" and left the arm64 container up."""
    mounts = {D.cache_root(), "/Volumes/Mac SSD/Sonichedge"}
    stale = _Fake(arch=D.ARCH, image_id="sha256:new",
                  container=("sha256:old-arm64", mounts))
    monkeypatch.setattr(D, "_docker", stale)
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    monkeypatch.setattr(D, "stage_rig", lambda src: D.staged_repo())
    D.ensure_container([ISO0], "/repo")
    assert any(c[0] == "run" for c in stale.calls), \
        "the container from the old image was kept"

    # ...and one already on the current image, with the same mounts, is not
    # torn down and rebuilt on every single run.
    good = _Fake(arch=D.ARCH, image_id="sha256:new",
                 container=("sha256:new", mounts))
    monkeypatch.setattr(D, "_docker", good)
    D.ensure_container([ISO0], "/repo")
    assert not any(c[0] == "run" for c in good.calls)


def test_a_stopped_container_is_started_again(mac, monkeypatch):
    """PAD-203.  Quitting Docker Desktop (or restarting the Mac) STOPS the
    container and leaves it there, same name, same mounts, same image, so
    it passed for "already right" and every step died on "Error response
    from daemon: container ... is not running"."""
    mounts = {D.cache_root(), "/Volumes/Mac SSD/Sonichedge"}
    stopped = _Fake(arch=D.ARCH, image_id="sha256:new",
                    container=("sha256:new", mounts))
    stopped.running = "false"
    monkeypatch.setattr(D, "_docker", stopped)
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    monkeypatch.setattr(D, "stage_rig", lambda src: D.staged_repo())
    D.ensure_container([ISO0], "/repo")
    calls = [c[0] for c in stopped.calls]
    assert "run" in calls, "the stopped container was kept"
    assert calls.index("rm") < calls.index("run"), \
        "the stopped one still holds the name"


def test_ensure_ready_container_builds_and_starts_in_background(
        mac, monkeypatch):
    """Background warm-up, preview and size-check runs call
    ensure_ready_container on a worker thread: when the image is not built
    yet it builds it and starts the container; once the image exists it
    starts (or remounts) the container and logs the mounted folders."""
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    monkeypatch.setattr(D, "stage_rig", lambda src: D.staged_repo())

    no_img = _Fake(arch="")
    monkeypatch.setattr(D, "_docker", no_img)
    logs = []
    assert D.ensure_ready_container([ISO0], "/repo", log=logs.append) is True
    assert any(c[0] == "build" for c in no_img.calls)
    run = [c for c in no_img.calls if c[0] == "run"]
    assert run and "%s:/root" % D.ROOT_VOLUME in run[0]
    assert any("building the Linux toolbox image" in m for m in logs)

    ready = _Fake(arch=D.ARCH, image_id="sha256:new")
    monkeypatch.setattr(D, "_docker", ready)
    logs = []
    assert D.ensure_ready_container([ISO0], "/repo", log=logs.append) is True
    assert not any(c[0] == "build" for c in ready.calls)
    assert any(c[0] == "run" for c in ready.calls)
    assert any("starting the Linux toolbox container" in m for m in logs)


def test_ensure_ready_container_with_no_paths_only_builds_image(
        mac, monkeypatch):
    """Opening the tab before any image is picked builds the image and stages
    the rig in the background, waiting to start the container until there are
    folders to mount."""
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    staged = []
    monkeypatch.setattr(D, "stage_rig", lambda src: staged.append(src))
    no_img = _Fake(arch="")
    monkeypatch.setattr(D, "_docker", no_img)
    assert D.ensure_ready_container([], "/repo") is True
    assert any(c[0] == "build" for c in no_img.calls)
    assert not any(c[0] == "run" for c in no_img.calls)
    assert staged == ["/repo"]


def test_a_failed_background_build_is_not_retried_per_keystroke(
        mac, monkeypatch):
    """If a background build fails, ensure_ready_container records
    _BUILD_FAILED so every keystroke does not start another docker build;
    pressing Build (ensure_container) clears it."""
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    tries = []

    def fail(paths, repo_src, log):
        tries.append(paths)
        raise RuntimeError("could not build the Linux toolbox image")
    monkeypatch.setattr(D, "_ensure_container", fail)
    monkeypatch.setattr(D, "_docker", _Fake(arch=""))
    assert D.ensure_ready_container([ISO0], "/repo") is False
    assert D.ensure_ready_container([ISO0], "/repo") is False
    assert len(tries) == 1
    monkeypatch.setattr(D, "_ensure_container", lambda p, r, l: None)
    D.ensure_container([ISO0], "/repo")
    assert not D._BUILD_FAILED


@pytest.mark.parametrize("source", [
    "/var/lib/docker/volumes/%s/_data" % D.ROOT_VOLUME,
    "/var/home/core/.local/share/containers/storage/volumes/%s/_data"
    % D.ROOT_VOLUME,
])
def test_running_state_ignores_named_volume_mount_source(mac, monkeypatch,
                                                         source):
    """ROOT_VOLUME mounted at /root appears in .Mounts with the engine's own
    storage path, which is not under /var/lib on a rootless Podman machine;
    _running_state asks for bind mounts only, so the host bind-mount
    comparison matches and the container is not restarted per redraw."""
    want = set(D.mount_points([ISO0])) | {D.cache_root()}
    fake = _Fake(arch=D.ARCH, image_id="sha256:new",
                 container=("sha256:new", want), volumes=[source])
    monkeypatch.setattr(D, "_docker", fake)
    assert D.ensure_ready_container([ISO0], "/repo") is True
    assert not any(c[0] == "run" for c in fake.calls)


def test_a_preview_finds_the_container_up_with_two_calls(mac, monkeypatch):
    """Every redraw calls ensure_ready_container.  A container already up
    on this image with these folders mounted costs one ``inspect`` and one
    ``image inspect``: no ``docker info``, no ``run``, and the ~50 MB rig
    copy only on the session's first call."""
    staged = []
    monkeypatch.setattr(D, "stage_rig", lambda src: staged.append(src))
    want = set(D.mount_points([ISO0])) | {D.cache_root()}
    fake = _Fake(arch=D.ARCH, image_id="sha256:new",
                 container=("sha256:new", want))
    monkeypatch.setattr(D, "_docker", fake)
    for _ in range(3):
        assert D.ensure_ready_container([ISO0], "/repo") is True
    assert staged == ["/repo"], "staged once per session, not per redraw"
    assert [c[0] for c in fake.calls] == ["inspect", "image"] * 3
    assert not any(c[0] in ("info", "run", "rm") for c in fake.calls)


def test_a_preview_does_not_retry_folders_the_engine_cannot_see(
        mac, monkeypatch):
    """Unshared from a preview is remembered: retrying it on every redraw
    would start and remove a container per keystroke.  A writing run that
    brings a container up clears it."""
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    tries = []

    def unshared(paths, repo_src, log):
        tries.append(paths)
        raise D.Unshared(["/Volumes/Cards"])
    monkeypatch.setattr(D, "_ensure_container", unshared)
    monkeypatch.setattr(D, "_docker", _Fake(arch=D.ARCH))
    assert D.ensure_ready_container([ISO0], "/repo") is False
    assert D.ensure_ready_container([ISO0], "/repo") is False
    assert len(tries) == 1
    monkeypatch.setattr(D, "_ensure_container", lambda p, r, l: None)
    D.ensure_container([ISO0], "/repo")
    assert not D._PREVIEW_REFUSED


def test_a_build_waits_for_the_preview_s_container_start(mac, monkeypatch):
    """The UI thread's Build and the preview's worker share one container
    name: two rm -f / run pairs interleaved fail one run on the name."""
    import threading
    import time
    inside, overlap = [], []

    def slow(paths, repo_src, log):
        if inside:
            overlap.append(True)
        inside.append(True)
        time.sleep(0.05)
        inside.pop()
    monkeypatch.setattr(D, "_ensure_container", slow)
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    monkeypatch.setattr(D, "_docker", _Fake(arch=D.ARCH))
    t = threading.Thread(target=D.ensure_ready_container,
                         args=([ISO0], "/repo"))
    t.start()
    D.ensure_container([ISO0], "/repo")
    t.join()
    assert not overlap


def test_a_stopped_container_gets_the_same_sentence(mac):
    """What the reporter's preview and size check printed, a dozen times."""
    raw = ("Error response from daemon: container 888b1f58e3f1 is not "
           "running")
    assert "not up yet" in mt.container_note(raw)


def test_a_step_before_the_container_is_up_gets_a_sentence(mac):
    """The preview never starts a container - it redraws on every keystroke
    and must not build an image behind the user - so on a Mac every preview
    step before the session's first build fails on Docker's own "No such
    container: pad-multiboot-worker".  Six of those in a row, with nothing
    else said, is what the reporter's log shows."""
    raw = ("Error response from daemon: No such container: %s" % D.CONTAINER)
    note = mt.container_note(raw)
    assert "not up yet" in note and "Build / flash card" in note
    assert D.CONTAINER not in note, "the sentence is for a person"
    # Podman spells the same refusal with a lowercase "no such container".
    podman_raw = ('Error: no container with name or ID "%s" found: '
                  'no such container' % D.CONTAINER)
    assert mt.container_note(podman_raw) == note
    # Anything else a step says is not this.
    assert mt.container_note("partclone.restore failed") == ""
    assert mt.container_note("") == ""


def test_a_step_for_an_unmounted_host_folder_gets_a_sentence(mac):
    """When a container from an earlier build is already running, adding a
    card from a new folder runs the preview/plan before Build / flash card...
    has recreated the container with that folder's /host/... bind mount."""
    for raw in ("mkmulticard.py: REFUSED: /host/Users/me/cards/a.raw: "
                "No such file or directory",
                "selectmedia.py: REFUSED: card image "
                "/host/Users/me/cards/a.raw does not exist",
                "[rootfs] no card image at /host/Users/me/cards/a.raw"):
        note = mt.container_note(raw)
        assert "mounted yet" in note and "Build / flash card" in note


def test_only_a_mac_gets_that_sentence(monkeypatch):
    """Windows and Linux have no container, so the words would be a lie -
    and 'No such container' can only come from somewhere else there."""
    monkeypatch.setattr(mt.sys, "platform", "linux")
    monkeypatch.setattr(D.sys, "platform", "linux")
    assert mt.container_note("No such container: x") == ""
    assert mt.container_note("/host/x: No such file or directory") == ""


# ---------------------------------------------------------------- guard rails

def test_no_docker_is_a_sentence_not_a_traceback(mac, monkeypatch):
    def boom(_args, timeout=30):
        raise FileNotFoundError("docker")
    monkeypatch.setattr(D, "_docker", boom)
    why = D.unavailable_reason()
    assert "not installed" in why and "Docker Desktop" in why

    class Down:
        returncode = 1
        stdout = stderr = ""
    monkeypatch.setattr(D, "_docker", lambda *a, **k: Down())
    assert "not running" in D.unavailable_reason()


def test_a_writing_run_stops_when_docker_is_not_there(mac, monkeypatch):
    """The user is told before anything starts, not part-way through."""
    monkeypatch.setattr(D, "unavailable_reason",
                        lambda: "Docker Desktop is not running.")
    with pytest.raises(RuntimeError, match="not running"):
        D.ensure_container([ISO0], "/repo")


def test_staging_skips_the_host_pycache(mac, tmp_path):
    """Host .pyc files are wrong inside the container, and the build
    scratch is large and useless there."""
    src = tmp_path / "src" / "tools" / "jjp_emu"
    (src / "__pycache__").mkdir(parents=True)
    (src / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (src / "mkjjpmulti.py").write_text("print(1)", encoding="utf-8")
    D.stage_rig(str(tmp_path / "src"))
    staged = os.path.join(D.staged_repo(), "tools", "jjp_emu")
    assert os.path.isfile(os.path.join(staged, "mkjjpmulti.py"))
    assert not os.path.exists(os.path.join(staged, "__pycache__"))


def test_staging_includes_stern_multiboot_leaf_modules(mac):
    """mkmulticard.py and selectmedia.py run on the container's bare python3
    with only the staged tree on sys.path; every Stern and core leaf module
    they import must be staged by stage_rig."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    staged = D.stage_rig(repo_root)
    for rel in D._PACKAGE_FILES:
        assert os.path.isfile(os.path.join(staged, rel)), rel


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX path shapes")
def test_enabled_is_the_only_switch(monkeypatch):
    monkeypatch.setattr(D.sys, "platform", "linux")
    assert D.enabled() is False
    monkeypatch.setattr(D.sys, "platform", "darwin")
    assert D.enabled() is True


def test_a_container_side_path_is_never_mounted(mac):
    """The Stern default selector dir is "~/spike2root/usr/local", which the
    rig expands inside the container against root's own home.  Bind-mounting
    the literal string would make a directory called "~" beside the app and
    mount nothing useful."""
    assert D.mount_points(["~/spike2root/usr/local"]) == []
    # An absolute path beside it still counts, so the filter is on the
    # tilde and not on "there was something odd in the list".
    assert D.mount_points(["~/x/y", ISO0]) == ["/Volumes/Mac SSD/Sonichedge"]


# ------------------------------------------------------------------ cancel

def test_cancel_reaches_the_tools_whatever_their_parent(monkeypatch):
    """PAD-218: ``pkill -P 1`` matched nothing - a ``docker exec`` process's
    parent is outside the container - so Cancel left a root restore running,
    and it later renamed the next run's half-written root into the cache.
    The line matches by name only, covers mount.sh (the rename), and cannot
    match its own ``bash -lc`` command line."""
    seen = []
    monkeypatch.setattr(D, "_docker", lambda args, timeout=30: seen.append(list(args)))
    D.kill_running()
    assert seen and seen[0][:4] == ["exec", D.CONTAINER, "bash", "-lc"]
    line = seen[0][-1]
    assert "-P 1" not in line and "pkill -KILL" in line
    import re
    pat = re.compile(D.KILL_PATTERN)
    for cmd in ("bash tools/jjp_emu/mount.sh --root-only /host/x.iso",
                "bash tools/jjp_emu/ensurejjpselect.sh /host/x.iso /var/tmp/jjpselect",
                "python3 tools/jjp_emu/mkjjpmulti.py build --primary a",
                "partclone.restore -C -f 1 -B -s - -o /var/tmp/jjp_x/sda3.raw.part.12",
                "xorriso -indev a.iso"):
        assert pat.search(cmd), cmd
    assert not pat.search(line)
    assert not pat.search("umount /var/tmp/jjp_x/iso")


# ------------------------------------------------- folders the engine shares

class _R:
    def __init__(self, out, rc=0):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class _Engine(_Fake):
    """A _Fake whose container sees only what *sees(path)* allows, the way
    colima's VM has the home folder and nothing else: a bind mount of any
    other folder is the VM's own empty one (PAD-885).  Answers the probe
    line ``[ -e <in container> ] || echo <host dir>; ...`` from that."""

    def __init__(self, sees, name="colima", context="colima", **kw):
        super().__init__(arch=D.ARCH, **kw)
        self.sees, self.name, self.context = sees, name, context

    def __call__(self, args, timeout=30):
        args = list(args)
        if args[0] == "exec" and args[-2] == "-c":
            self.calls.append(args)
            out = []
            for part in args[-1].split("; "):
                m = re.match(r"\[ -e (.+) \] \|\| echo (.+)$", part)
                assert m, part
                cpath = shlex.split(m.group(1))[0]
                host = shlex.split(m.group(2))[0]
                if not self.sees(cpath):
                    out.append(host)
            return _R("\n".join(out))
        if args[:2] == ["context", "show"]:
            self.calls.append(args)
            return _R(self.context, 0 if self.context else 1)
        if args[0] == "info":
            self.calls.append(args)
            return _R(self.name, 0 if self.name else 1)
        return super().__call__(args, timeout)


def _cache_only(cpath):
    return cpath.startswith("/tmp/")


@pytest.fixture
def unix_paths(mac, monkeypatch, tmp_path):
    """Host folders spelled the way a Mac spells them (``/Volumes/...``),
    backed by real folders under tmp_path so they can be listed.  Returns
    the function that maps one to its real folder."""
    root = str(tmp_path / "fs")

    def back(p):
        if not p.startswith("/") or p.startswith(root):
            return p          # a real path already (os is patched for all)
        return root + p
    real_isdir, real_listdir = os.path.isdir, os.listdir
    real_open, real_remove = open, os.remove
    monkeypatch.setattr(D.os.path, "isdir", lambda p: real_isdir(back(p)))
    monkeypatch.setattr(D.os, "listdir", lambda p: real_listdir(back(p)))
    monkeypatch.setattr(D.os, "remove", lambda p: real_remove(back(p)))
    monkeypatch.setattr(D, "open", lambda p, *a, **k: real_open(back(p), *a, **k),
                        raising=False)
    monkeypatch.setattr(D, "cache_root", lambda: "/Users/me/Library/Caches/pad")
    monkeypatch.setattr(D.os.path, "expanduser",
                        lambda p: p.replace("~", "/Users/me", 1))
    monkeypatch.setattr(D, "unavailable_reason", lambda: "")
    monkeypatch.setattr(D, "stage_rig", lambda src: D.staged_repo())
    os.makedirs(back(D.staged_repo()))
    iso_dir = back("/Volumes/Mac SSD/Sonichedge")
    os.makedirs(iso_dir)
    with real_open(iso_dir + "/Sonic-v00.930.iso", "wb") as fh:
        fh.write(b"\0")
    os.makedirs(back("/Volumes/Mac SSD/out"))
    return back


OUT = "/Volumes/Mac SSD/out/multi.iso"


def test_a_folder_colima_does_not_share_stops_the_run(unix_paths, monkeypatch):
    """The ISOs on /Volumes: docker run succeeds, the mount is colima's
    own empty folder, and every tool after it would have found nothing.
    The run stops before it starts, saying which folders and how."""
    eng = _Engine(_cache_only)
    monkeypatch.setattr(D, "_docker", eng)
    with pytest.raises(RuntimeError) as e:
        D.ensure_container([ISO0, OUT], "/repo")
    why = str(e.value)
    assert "/Volumes/Mac SSD/Sonichedge" in why and "/Volumes/Mac SSD/out" in why
    assert "colima stop\n" in why
    # --mount replaces colima's list: home must be named again, or the
    # cache (and the rig in it) goes next; /Volumes is shared whole.
    assert 'colima start --mount "$HOME:w" --mount /Volumes:w\n' in why
    assert D.cache_root() not in why, "the cache was seen: not named"
    # ...and the container that cannot see them is not left for the next
    # run to call "already right".
    probed = [i for i, c in enumerate(eng.calls) if c[0] == "exec"][-1]
    assert ["rm", "-f", D.CONTAINER] in eng.calls[probed:]


def test_the_empty_output_folder_is_checked_with_a_marker_it_does_not_keep(
        unix_paths, monkeypatch):
    eng = _Engine(_cache_only)
    monkeypatch.setattr(D, "_docker", eng)
    with pytest.raises(RuntimeError):
        D.ensure_container([OUT], "/repo")
    probe = [c for c in eng.calls if c[0] == "exec"][0][-1]
    assert D._PROBE in probe
    assert os.listdir(unix_paths("/Volumes/Mac SSD/out")) == []


def test_folders_it_shares_run_as_before(unix_paths, monkeypatch):
    """OrbStack, Docker Desktop with /Volumes shared, or colima started
    with the mounts the message gives: nothing said, the run goes on."""
    eng = _Engine(lambda p: True)
    monkeypatch.setattr(D, "_docker", eng)
    D.ensure_container([ISO0, OUT], "/repo")
    assert eng.calls[-1] != ["rm", "-f", D.CONTAINER]
    probe = [c for c in eng.calls if c[0] == "exec"][0][-1]
    # the ISO itself is what is looked for, quoted for the space in it
    assert "'/host/Volumes/Mac SSD/Sonichedge/Sonic-v00.930.iso'" in probe
    assert "[ -e /tmp/repo ]" in probe


def test_a_kept_container_is_checked_too(unix_paths, monkeypatch):
    """The one a failed run left would be "already right" next time: same
    mounts, same image.  So the check is on every run, not only a new one."""
    mounts = {D.cache_root(), "/Volumes/Mac SSD/Sonichedge"}
    eng = _Engine(_cache_only, container=("sha256:new", mounts))
    monkeypatch.setattr(D, "_docker", eng)
    with pytest.raises(RuntimeError, match="cannot see"):
        D.ensure_container([ISO0], "/repo")
    assert not any(c[0] == "run" for c in eng.calls)


def test_a_colima_profile_gets_its_own_commands(mac, monkeypatch):
    monkeypatch.setattr(D, "_docker", _Engine(_cache_only, name="",
                                              context="colima-work"))
    why = D.unshared_reason(["/Volumes/Big/isos"])
    assert "colima stop -p work\n" in why
    assert "colima start -p work --mount" in why
    # lima's name for the VM, when the context is not colima's
    monkeypatch.setattr(D, "_docker", _Engine(_cache_only, name="lima-colima",
                                              context="default"))
    why = D.unshared_reason(["/Volumes/Big/isos"])
    assert "colima stop\n" in why and "Big/isos: Colima" in why


def test_a_folder_outside_volumes_is_shared_by_name(mac, monkeypatch):
    monkeypatch.setattr(D, "_docker", _Engine(_cache_only))
    why = D.unshared_reason(["/opt/isos", "/Volumes/A/x", "/Volumes/B/y"])
    assert '--mount "$HOME:w" --mount /opt/isos:w --mount /Volumes:w\n' in why
    assert "Share them" in why and "those folders" in why


def test_docker_desktop_and_others_get_their_own_sentence(mac, monkeypatch):
    monkeypatch.setattr(D, "_docker", _Engine(_cache_only, name="docker-desktop",
                                              context="desktop-linux"))
    why = D.unshared_reason(["/Volumes/A/x"])
    assert "File sharing" in why and "colima" not in why.lower()
    monkeypatch.setattr(D, "_docker", _Engine(_cache_only, name="orbstack",
                                              context="orbstack"))
    why = D.unshared_reason(["/Volumes/A/x"])
    assert "shared folders" in why and "colima" not in why.lower()


def test_a_container_that_cannot_be_asked_is_not_called_unshared(
        unix_paths, monkeypatch):
    """No answer is not "empty": the steps say what is wrong themselves."""
    monkeypatch.setattr(D, "_docker", lambda args, timeout=30: _R("x", 1))
    assert D.unseen_mounts(["/Volumes/Mac SSD/Sonichedge"]) == []
    assert D.unseen_mounts(["/Volumes/not there"]) == []


# ------------------------------------- the app shares them itself (PAD-903)

from pinball_decryptor.webui import emulate_core as E


def _colima_yaml(monkeypatch, tmp_path, text, profile="default"):
    home = tmp_path / "colima"
    (home / profile).mkdir(parents=True)
    (home / profile / "colima.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setenv("COLIMA_HOME", str(home))
    monkeypatch.setattr(E.os.path, "expanduser",
                        lambda p: p.replace("~", "/Users/me", 1))


def test_a_fresh_colima_is_started_sharing_home_and_volumes(monkeypatch,
                                                            tmp_path):
    """Set up emulator's own start: the ISOs on another disk are seen from
    the first run.  Home is named, because --mount replaces colima's list
    and home is in it only while the list is empty."""
    monkeypatch.setenv("COLIMA_HOME", str(tmp_path / "none"))
    monkeypatch.setattr(E.os.path, "expanduser",
                        lambda p: p.replace("~", "/Users/me", 1))
    assert E.colima_start_argv("/opt/homebrew/bin/colima") == [
        "/opt/homebrew/bin/colima", "start",
        "--mount", "/Users/me:w", "--mount", "/Volumes:w"]


def test_the_folders_colima_already_shares_are_kept(monkeypatch, tmp_path):
    _colima_yaml(monkeypatch, tmp_path, (
        "cpu: 2\n"
        "mounts:\n"
        "  - location: ~\n"
        "    writable: true\n"
        "  - location: '/opt/src'   # theirs\n"
        "    writable: false\n"
        "mountType: virtiofs\n"))
    assert E.colima_mounts() == [("/Users/me", True), ("/opt/src", False)]
    assert E.colima_start_argv("colima", share=["/Volumes", "/opt/src/x"]) == [
        "colima", "start", "--mount", "/Users/me:w", "--mount", "/opt/src",
        "--mount", "/Volumes:w"]


def test_an_empty_mount_list_is_colimas_home_default(monkeypatch, tmp_path):
    _colima_yaml(monkeypatch, tmp_path, "mounts: []\nmountType: sshfs\n",
                 profile="work")
    assert E.colima_mounts("work") == []
    assert E.colima_start_argv("colima", "work") == [
        "colima", "start", "-p", "work",
        "--mount", "/Users/me:w", "--mount", "/Volumes:w"]


def test_volumes_already_shared_is_not_named_twice(monkeypatch, tmp_path):
    _colima_yaml(monkeypatch, tmp_path, (
        "mounts:\n- location: /Users/me\n  writable: true\n"
        "- location: /Volumes\n  writable: true\n"))
    assert E.colima_start_argv("colima").count("/Volumes:w") == 1


def test_the_unshared_error_carries_colimas_fix(unix_paths, monkeypatch):
    """stop, then a start sharing /Volumes: what the panel offers to run."""
    monkeypatch.setattr(D, "_docker", _Engine(_cache_only, context="colima-work"))
    monkeypatch.setattr(E, "which_tool", lambda n, *a: "/usr/local/bin/" + n)
    monkeypatch.setattr(E, "colima_mounts", lambda profile="": [])
    monkeypatch.setattr(E.os.path, "expanduser",
                        lambda p: p.replace("~", "/Users/me", 1))
    with pytest.raises(D.Unshared) as e:
        D.ensure_container([ISO0], "/repo")
    assert e.value.unseen == ["/Volumes/Mac SSD/Sonichedge"]
    assert e.value.fix == [
        ["/usr/local/bin/colima", "stop", "-p", "work"],
        ["/usr/local/bin/colima", "start", "-p", "work",
         "--mount", "/Users/me:w", "--mount", "/Volumes:w"]]
    assert "colima stop -p work" in str(e.value)        # the sentence stays


def test_docker_desktop_gets_no_fix_to_run(unix_paths, monkeypatch):
    monkeypatch.setattr(D, "_docker", _Engine(_cache_only, name="docker-desktop",
                                              context="desktop-linux"))
    with pytest.raises(D.Unshared) as e:
        D.ensure_container([ISO0], "/repo")
    assert e.value.fix is None and "File sharing" in str(e.value)


def test_share_folders_runs_each_command_into_the_log():
    lines = []
    py = sys.executable
    ok = D.share_folders([[py, "-c", "print('stopped')"],
                          [py, "-c", "print('started')"]], log=lines.append)
    assert ok and "stopped" in lines and "started" in lines
    assert lines[0].startswith("$ ")
    lines = []
    assert not D.share_folders([[py, "-c", "import sys; sys.exit(3)"],
                                [py, "-c", "print('never')"]],
                               log=lines.append)
    assert "never" not in lines


class _Panel:
    """Just enough of MultibootPanel for _run_commands' container guard."""

    def __init__(self):
        self._busy = self._pv_busy = False
        self._cancelled = self._cancel_pending = False
        self._drain_job = None
        self.asked, self.errors, self.written, self.started = [], [], [], []
        self.busy_log = []

    def _set_busy(self, b):
        self._busy = b
        self.busy_log.append(b)

    def _write(self, line):
        self.written.append(line)

    _append = _write

    def _error(self, msg):
        self.errors.append(msg)

    def _ui(self, fn):
        fn()

    def _drain(self):
        pass

    def _run_paths(self):
        return [ISO0]

    def _start_worker(self, *a):
        self.started.append(a)

    def _phase_cancelled(self):
        self.written.append("cancelled")

    def _phase_fn(self, index, total=None, status=None):
        self.written.append("status: %s" % status)

    def _phase_done(self, rc, failed):
        self.written.append("status: %s failed" % failed)


def _panel_run(monkeypatch, times, answer, shared_ok=True):
    """A build whose first *times* container checks say the ISO folder is
    unseen, the user answering *answer* to the offer."""
    p = _Panel()
    for name in ("_run_commands", "_share_and_retry", "_prepare_container"):
        monkeypatch.setattr(_Panel, name, getattr(mt.MultibootPanel, name),
                            raising=False)
    monkeypatch.setattr(D, "enabled", lambda: True)
    monkeypatch.setattr(D, "colima_fix", lambda unseen: [["colima", "stop"]])
    monkeypatch.setattr(D, "unshared_reason", lambda unseen: "cannot see it")
    calls = {"ensure": 0, "share": 0}

    def ensure(paths, repo, log=None):
        calls["ensure"] += 1
        if calls["ensure"] <= times:
            raise D.Unshared(["/Volumes/Mac SSD/Sonichedge"])
    monkeypatch.setattr(D, "ensure_container", ensure)

    def share(fix, log=None):
        calls["share"] += 1
        return shared_ok
    monkeypatch.setattr(D, "share_folders", share)

    def ask(title, body):
        p.asked.append(body)
        return answer
    monkeypatch.setattr(mt.messagebox, "askyesno", ask)

    class _T:                       # the worker thread, run in place
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(mt.threading, "Thread", _T)
    p._run_commands([("build", ["true"])])
    return p, calls


def test_a_yes_restarts_colima_and_runs_again(monkeypatch):
    p, calls = _panel_run(monkeypatch, times=1, answer=True)
    assert len(p.asked) == 1 and "/Volumes/Mac SSD/Sonichedge" in p.asked[0]
    assert calls == {"ensure": 2, "share": 1}
    assert len(p.started) == 1 and not p.errors
    assert p.busy_log[:2] == [True, False]   # greyed while Colima restarts


def test_a_no_stops_with_the_sentence(monkeypatch):
    p, calls = _panel_run(monkeypatch, times=1, answer=False)
    assert calls["share"] == 0 and not p.started
    assert p.errors == ["cannot see it"]


def test_a_colima_still_blind_is_not_asked_again(monkeypatch):
    p, calls = _panel_run(monkeypatch, times=2, answer=True)
    assert len(p.asked) == 1 and calls["share"] == 1 and not p.started
    assert p.errors == ["cannot see it"]


def test_a_failed_restart_says_so(monkeypatch):
    p, calls = _panel_run(monkeypatch, times=1, answer=True, shared_ok=False)
    assert calls["ensure"] == 1 and not p.started
    assert "did not restart" in p.errors[0]


def test_the_config_is_found_where_colima_keeps_it(monkeypatch, tmp_path):
    """colima's config/files.go: COLIMA_HOME when it exists, ~/.colima,
    then the XDG config folder when ~/.colima is not there."""
    monkeypatch.setenv("COLIMA_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(E.os.path, "expanduser",
                        lambda p: p.replace("~", str(tmp_path / "home"), 1))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert E.colima_profile_dir("work") == os.path.join(
        str(tmp_path / "xdg"), "colima", "work")
    (tmp_path / "home" / ".colima").mkdir(parents=True)
    assert os.path.normpath(E.colima_profile_dir()) == os.path.join(
        str(tmp_path / "home"), ".colima", "default")
    (tmp_path / "ch").mkdir()
    monkeypatch.setenv("COLIMA_HOME", str(tmp_path / "ch"))
    assert E.colima_profile_dir() == os.path.join(str(tmp_path / "ch"),
                                                  "default")


# ------------------------------------------- the build is a worker's (PAD-911)

_real_docker_build = D._docker_build


def _held_panel(monkeypatch, ensure):
    """A Build press whose worker thread is HELD, not run: what the main
    thread has done by the time the button handler returns."""
    p = _Panel()
    for name in ("_run_commands", "_share_and_retry", "_prepare_container"):
        monkeypatch.setattr(_Panel, name, getattr(mt.MultibootPanel, name),
                            raising=False)
    monkeypatch.setattr(D, "enabled", lambda: True)
    monkeypatch.setattr(D, "ensure_container", ensure)
    threads = []

    class _T:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            threads.append(self.target)
    monkeypatch.setattr(mt.threading, "Thread", _T)
    return p, threads


def test_build_press_does_not_build_the_image_on_the_main_thread(monkeypatch):
    """THE BUG (PAD-911).  The reporter's log: three "could not build the
    Linux toolbox image ... CANCELED ... context canceled", each a few
    seconds before the app opened again.  ensure_container ran from the
    button handler, so the minutes of `docker build` froze the window, and
    quitting it cancelled the build.  The press now only greys the tab and
    hands the build to a worker."""
    seen = []
    p, threads = _held_panel(
        monkeypatch, lambda paths, repo, log=None: seen.append(paths))
    assert p._run_commands([("build", ["true"])]) is True
    assert seen == [] and p.started == []          # nothing ran yet
    assert p._busy and len(threads) == 1           # busy: actions greyed
    threads.pop()()                                # the worker
    assert seen == [[ISO0]] and len(p.started) == 1 and not p.errors


def test_a_second_press_while_the_image_builds_is_refused(monkeypatch):
    p, threads = _held_panel(monkeypatch, lambda *a, **k: None)
    p._run_commands([("build", ["true"])])
    assert p._run_commands([("build", ["true"])]) is False
    assert p.errors == ["A run is already in progress."] and len(threads) == 1


def test_a_failed_image_build_says_so_and_frees_the_tab(monkeypatch):
    def ensure(paths, repo, log=None):
        raise RuntimeError("could not build the Linux toolbox image:\nboom")
    p, threads = _held_panel(monkeypatch, ensure)
    p._run_commands([("build", ["true"])])
    threads.pop()()
    assert not p._busy and not p.started
    assert p.errors and "could not build" in p.errors[0]


def test_cancel_during_the_image_build_stops_it_and_runs_nothing(monkeypatch):
    killed = []
    monkeypatch.setattr(D, "cancel_build", lambda: killed.append(1) or True)
    monkeypatch.setattr(D, "kill_running", lambda: None)

    def ensure(paths, repo, log=None):
        raise RuntimeError("could not build the Linux toolbox image:\n"
                           "Canceled: context canceled")
    p, threads = _held_panel(monkeypatch, ensure)
    p._proc = None
    p._proc_preview = False
    p._pending_run = None
    p._ok = p._write
    p._sync_build_button = lambda: None
    p._phase_fn = lambda *a, **k: None
    p._run_commands([("build", ["true"])])
    assert mt.MultibootPanel.cancel_run(p) is True
    assert killed == [1]
    threads.pop()()
    assert not p._busy and not p.started and not p.errors
    assert p.written[-1] == "cancelled"


class _Proc:
    """A `docker build` client: prints *lines*, then exits *rc*."""

    def __init__(self, lines, rc=0):
        self.stdout = iter(line + "\n" for line in lines)
        self.rc, self.killed = rc, False

    def wait(self):
        return self.rc

    def kill(self):
        self.killed = True


def test_the_build_streams_and_says_it_is_still_going(mac, monkeypatch):
    """Minutes of a silent Log read as a hung app.  The build's own lines
    are read as they come, and every BUILD_HEARTBEAT seconds the Log says
    it is still going and the step it is on."""
    monkeypatch.setattr(D, "_image_field", lambda f: "")
    clock = iter([0, 5, 31, 40, 70, 75])
    monkeypatch.setattr(D.time, "monotonic", lambda: next(clock))
    lines = ["#5 1.0 Get:1 http://deb.debian.org/debian bookworm/main gzip",
             "#5 30.9 Get:287 qemu-user-static [62.6 MB]",
             "#5 40.0 Unpacking ffmpeg",
             "#5 69.0 Setting up ffmpeg"]
    proc = _Proc(lines)
    monkeypatch.setattr(D, "_docker_build", _real_docker_build)
    monkeypatch.setattr(D.subprocess, "Popen", lambda *a, **k: proc)
    log = []
    D.ensure_image(log=log.append)
    still = [line for line in log if "still building" in line]
    assert len(still) == 2, log
    assert "qemu-user-static" in still[0] and "(31s)" in still[0]
    assert "Setting up ffmpeg" in still[1] and "1m 10s" in still[1]
    assert "is built (1m 15s)" in log[-1]
    assert D._BUILD["proc"] is None                 # nothing left to cancel


def test_a_failed_build_carries_its_last_lines(mac, monkeypatch):
    monkeypatch.setattr(D, "_image_field", lambda f: "")
    monkeypatch.setattr(D, "_docker_build", _real_docker_build)
    monkeypatch.setattr(D.subprocess, "Popen", lambda *a, **k: _Proc(
        ["#5 CANCELED", "ERROR: failed to build: failed to solve: Canceled"],
        rc=1))
    with pytest.raises(RuntimeError) as e:
        D.ensure_image()
    assert "failed to solve" in str(e.value)


def test_cancel_build_kills_the_client(monkeypatch):
    """Killing the client is what stops a BuildKit build - the reporter's
    "context canceled" is exactly that happening by accident."""
    proc = _Proc([])
    monkeypatch.setitem(D._BUILD, "proc", proc)
    assert D.cancel_build() is True and proc.killed
    monkeypatch.setitem(D._BUILD, "proc", None)
    assert D.cancel_build() is False


def test_warm_container_runs_in_background_without_locking_ui(monkeypatch):
    """Opening the tab or adding an image warms the container in the
    background without setting _busy, then schedules a preview and plan."""
    monkeypatch.setenv("PAD_UI_NO_RIG", "0")
    monkeypatch.setenv("PAD_MULTIBOOT_AUTO", "1")
    monkeypatch.setattr(D, "enabled", lambda: True)
    seen, scheduled, planned = [], [], []
    p = _Panel()
    p._rows = [ImageRow(path=ISO0)]
    p._plan_info = None
    p._pv_src = None
    p._pv_say = lambda msg, **kw: p.written.append("pv: %s" % msg)
    p.schedule_preview = lambda: scheduled.append(1)
    p._maybe_plan = lambda: planned.append(1)
    for name in ("_warm_container", "_warm_log"):
        monkeypatch.setattr(_Panel, name, getattr(mt.MultibootPanel, name),
                            raising=False)

    def ensure_ready(paths, repo, log=None):
        seen.append(paths)
        if log:
            log("starting the Linux toolbox container...")
        return True
    monkeypatch.setattr(D, "ensure_ready_container", ensure_ready)
    threads = []

    class _T:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            threads.append(self.target)
    monkeypatch.setattr(mt.threading, "Thread", _T)
    assert p._warm_container() is True
    assert not p._busy and p._warming_container and len(threads) == 1
    assert p._warm_container() is False             # already warming
    threads.pop()()
    assert not p._warming_container
    assert seen == [[ISO0]] and scheduled == [1] and planned == [1]
    assert any("pv: starting the Linux toolbox" in w for w in p.written)


def test_preview_worker_skips_docker_exec_when_container_not_ready(
        mac, monkeypatch):
    """When ensure_ready_container returns False, _start_worker does not
    spawn a doomed `docker exec` process and instead records the container
    note once."""
    monkeypatch.setattr(D, "ensure_ready_container", lambda *a, **k: False)
    popens = []
    monkeypatch.setattr(mt.subprocess, "Popen",
                        lambda *a, **k: popens.append(a))
    p = _Panel()
    p._pv_cancel = False
    p._pending_run = None
    p._pv_say = lambda *a, **k: None
    for name in ("_start_worker", "_say_once"):
        monkeypatch.setattr(_Panel, name, getattr(mt.MultibootPanel, name),
                            raising=False)

    class _T:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(mt.threading, "Thread", _T)
    done = []
    p._start_worker(
        [("selector", ["docker", "exec", D.CONTAINER, "bash", "-lc", "make"])],
        on_step=None,
        on_done=lambda rc, failed, texts: done.append((rc, failed, texts)),
        quiet=frozenset(),
        preview=True)
    assert not popens
    assert len(done) == 1 and done[0][0] == 1 and done[0][1] == "selector"
    assert any("not up yet" in w for w in p.written)


def test_strip_sha256():
    assert D._strip_sha256("sha256:abcdef0123") == "abcdef0123"
    assert D._strip_sha256("abcdef0123") == "abcdef0123"
    assert D._strip_sha256("") == ""
    assert D._strip_sha256(None) == ""


def test_unavailable_reason_when_podman_cli_used(monkeypatch):
    monkeypatch.setattr(D, "_cli", lambda: "/opt/podman/bin/podman")
    monkeypatch.setattr(D, "_docker", lambda *a, **k: subprocess.CompletedProcess(
        ["podman", "info"], 1, stdout="", stderr="error"))
    reason = D.unavailable_reason()
    assert "Podman is installed but not running" in reason


def test_running_state_ignores_var_lib_volume_mounts(monkeypatch):
    stdout = "true\nsha256:img123\n/tmp\n/host/Volumes/Card\n/var/lib/containers/storage/volumes/pad-vol\n"
    monkeypatch.setattr(D, "_docker", lambda *a, **k: subprocess.CompletedProcess(
        ["podman", "inspect"], 0, stdout=stdout))
    img, mounts = D._running_state()
    assert img == "sha256:img123"
    assert mounts == {"/tmp", "/host/Volumes/Card"}


def test_unshared_reason_podman(monkeypatch):
    monkeypatch.setattr(D, "_engine_name", lambda: "podman")
    msg = D.unshared_reason(["/Volumes/External"])
    assert "Podman" in msg
    assert "Settings > Resources" in msg
