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
import os
import sys

import pytest

from pinball_decryptor.gui import multiboot_docker as D
from pinball_decryptor.gui import multiboot_tab as mt
from pinball_decryptor.gui.multiboot_tab import ImageRow, MultibootForm

ISO0 = "/Volumes/Mac SSD/Sonichedge/Sonic-v00.930.iso"
ISO1 = "/Volumes/Mac SSD/sonichedgehogcode/build/Sonic-v00.930-modified.iso"


@pytest.fixture
def mac(monkeypatch, tmp_path):
    """Pretend to be macOS, with the cache somewhere harmless."""
    monkeypatch.setattr(mt.sys, "platform", "darwin")
    monkeypatch.setattr(D.sys, "platform", "darwin")
    monkeypatch.setattr(D, "cache_root", lambda: str(tmp_path / "cache"))
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


def test_the_image_tag_is_versioned():
    """`docker image inspect` succeeds on a stale image built from an older
    Dockerfile, so a new package list that kept the old tag would never
    reach anybody who had already built one."""
    assert ":" in D.IMAGE and D.IMAGE.rsplit(":", 1)[1]


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
