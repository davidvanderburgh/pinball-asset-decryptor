"""PAD-1630, third round: on a Mac (Apple silicon) the multi-boot build stopped
at "missing tool(s): fuser" and every menu preview at frame 0 with qemu's
"Unable to reserve 0xfffff000 bytes of virtual address space at 0x8000".

* The Mac's Linux toolbox image never had psmisc, the package fuser comes in.
* Its x86-64 container runs under Rosetta there, and an x86-64 qemu-arm
  cannot reserve the 32-bit guest under it.  The preview then runs the menu
  program through the kernel's own ARM handler (the arm64 VM's native one),
  with QEMU_LD_PREFIX for -L.  Proven frame-for-frame against real qemu in WSL:
  docs/validation is not needed for that, the wrapper is what is tested here.
"""
import os
import re
import shutil
import stat
import subprocess
import sys

import pytest

from pinball_decryptor.webui import multiboot_core as core
from pinball_decryptor.webui import multiboot_docker as mbd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Debian bookworm package for each tool the store layout checks for.
_PKG = {"losetup": "mount", "mount": "mount", "umount": "mount",
        "findmnt": "util-linux", "fuser": "psmisc", "e2fsck": "e2fsprogs"}
#: Packages every debian:bookworm-slim image already has (Priority: required).
_BASE = {"mount", "util-linux"}


def test_the_mac_image_carries_every_tool_the_store_layout_asks_for():
    src = open(os.path.join(ROOT, "tools", "spike2_emu", "mkmulticard.py"),
               encoding="utf-8").read()
    m = re.search(r'missing = \[n for n in \(([^)]*)\) if shutil\.which', src)
    assert m, "the store layout's tool check moved"
    tools = re.findall(r'"([^"]+)"', m.group(1))
    assert "fuser" in tools
    run = mbd.DOCKERFILE.split("install -y --no-install-recommends", 1)[1]
    pkgs = set(re.findall(r"[a-z0-9][a-z0-9.+-]+", run.split("&&")[0]))
    for t in tools:
        assert _PKG[t] in pkgs | _BASE, "%s (package %s) is not in the Mac image" % (t, _PKG[t])


def test_the_image_tag_moved_with_the_package_list():
    # the tag is the cache key: a Mac that built :5 would never get psmisc
    assert mbd.IMAGE != "pad-multiboot:5"


def _sh():
    sh = shutil.which("sh")
    if not sh or sys.platform == "win32":
        pytest.skip("needs a POSIX sh with this process's own filesystem")
    return sh


def _exe(path, body):
    with open(path, "w", newline="\n") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path, qemu_body):
    sh = _sh()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _exe(str(bindir / "qemu-arm-static"), qemu_body)
    # stands in for the ARM menu program: the kernel's binfmt handler is what
    # would run the real one; it reports what it was handed
    prog = tmp_path / "codeselect"
    _exe(str(prog), 'echo "ran prefix=$QEMU_LD_PREFIX args=$*"\n')
    argv = [sh if a == "sh" else a for a in core.QEMU_ARM] + [
        "-L", "/root/spike2root", str(prog), "--snapshot", "f.ppm"]
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=30)


ROSETTA = ('echo "qemu-arm-static: Unable to reserve 0xfffff000 bytes of virtual '
           'address space at 0x8000 (Success) for use as guest address space" >&2\n'
           'exit 1\n')


def test_a_qemu_that_cannot_reserve_the_guest_hands_the_menu_to_the_arm_handler(tmp_path):
    r = _run(tmp_path, ROSETTA)
    assert r.returncode == 0, r.stderr
    assert "ran prefix=/root/spike2root args=--snapshot f.ppm" in r.stdout
    assert "Unable to reserve" in r.stderr  # the cause stays in the tool output
    assert "ARM handler" in r.stderr


def test_any_other_qemu_failure_is_passed_through_untouched(tmp_path):
    r = _run(tmp_path, 'echo "qemu: some other trouble" >&2\nexit 3\n')
    assert r.returncode == 3
    assert "ran prefix" not in r.stdout
    assert "some other trouble" in r.stderr and "ARM handler" not in r.stderr


def test_a_working_qemu_runs_once_as_before(tmp_path):
    r = _run(tmp_path, 'echo "qemu ran $*"\n')
    assert r.returncode == 0
    assert r.stdout.strip() == "qemu ran -L /root/spike2root %s --snapshot f.ppm" % (tmp_path / "codeselect")
