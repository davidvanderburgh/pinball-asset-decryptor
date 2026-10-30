"""The Docker image (PAD-837) and what Stern Emulate needs to run in it.

A container without privileges cannot see the kernel's binfmt_misc table,
however many handlers the server has registered, so the rig's setup check
said "no handler registered for 32-bit ARM programs" in a container that
ran them fine.  When the table is not there to read, the rig now runs a
96-byte ARM program and believes what happens.
"""

import base64
import pathlib
import re
import struct
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
RIG = REPO / "tools" / "spike2_emu"
DOCKER = REPO / "installer" / "docker"


def _bash_runs_scripts():
    """Same guard as test_pkgnames.py: `bash` here may be git-bash or a WSL
    launcher with no distro."""
    try:
        r = subprocess.run(["bash", "-c", 'echo "${BASH_VERSINFO[0]}"'],
                           capture_output=True, timeout=30)
        return int(r.stdout.decode().strip()) >= 4
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        return False


HAS_BASH4 = _bash_runs_scripts()


def _eb():
    return (RIG / "ensurebuild.sh").read_text(encoding="utf-8")


def _fn(src, name):
    body = src[src.index(name + "() {"):]
    return body[:body.index("\n}") + 2]


# --- the probe program -----------------------------------------------------

def test_the_probe_is_a_32_bit_arm_program_that_exits_0():
    b64 = re.search(r"^PAD_ARM_EXIT0_B64=(\S+)$", _eb(), re.M).group(1)
    elf = base64.b64decode(b64)
    assert elf[:4] == b"\x7fELF"
    assert elf[4:7] == b"\x01\x01\x01"          # 32-bit, little-endian, v1
    e_type, e_machine = struct.unpack_from("<HH", elf, 16)
    assert (e_type, e_machine) == (2, 0x28)     # executable, ARM
    entry, phoff = struct.unpack_from("<II", elf, 24)
    p_type, p_off, p_vaddr, _, p_filesz = struct.unpack_from(
        "<IIIII", elf, phoff)
    assert p_type == 1 and p_off == 0 and p_filesz == len(elf)
    code = elf[entry - p_vaddr:]
    # mov r0,#0 ; mov r7,#1 (exit) ; svc 0
    assert code == bytes.fromhex("0000a0e3" "0170a0e3" "000000ef")
    # ...and it matches the qemu-arm binfmt rule Debian and Ubuntu register
    # (e_ident through e_machine, e_type 2 or 3).
    magic = bytes.fromhex("7f454c4601010100000000000000000002002800")
    mask = bytes.fromhex("ffffffffffffff00fffffffffffffffffeffffff")
    assert all((a & m) == (b & m) for a, b, m in zip(elf, magic, mask))


# --- table first, then the probe --------------------------------------------

def _binfmt_arm(table, probe_rc):
    """_pad_binfmt_arm against a fake binfmt_misc ``table`` ({file: text},
    or None for "not mounted"), with the probe answering ``probe_rc``."""
    harness = 'T=$(mktemp -d)\n'
    if table is not None:
        for name, text in table.items():
            harness += "printf '%%s\\n' '%s' > \"$T/%s\"\n" % (text, name)
    harness += "PAD_BINFMT_DIR=$T\n"
    harness += _fn(_eb(), "_pad_binfmt_arm").replace("\r", "") + "\n"
    harness += "_pad_arm_runs() { return %d; }\n" % probe_rc
    harness += 'out=$(_pad_binfmt_arm); rc=$?; echo "rc=$rc out=${out#$T/}"\n'
    harness += 'rm -rf "$T"\n'
    r = subprocess.run(["bash", "-s"], input=harness.encode("utf-8"),
                       capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", "replace").strip()


@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the probe with")
def test_a_table_that_cannot_be_seen_is_asked_by_running_arm():
    assert _binfmt_arm(None, 0) == "rc=0 out=exec"
    assert _binfmt_arm(None, 1) == "rc=1 out="


@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the probe with")
def test_a_table_that_can_be_seen_is_still_believed():
    """A visible table answers as before, probe or no probe: an empty one
    is "no handler" even if something odd would have run."""
    entry = "enabled\ninterpreter /usr/libexec/qemu-binfmt/arm-binfmt-P"
    assert _binfmt_arm({"status": "enabled", "qemu-arm": entry}, 1) == \
        "rc=0 out=qemu-arm"
    assert _binfmt_arm({"status": "enabled"}, 0) == "rc=1 out="


def test_setupcheck_does_not_read_exec_as_a_table_file():
    sc = (RIG / "setupcheck.sh").read_text(encoding="utf-8")
    body = sc[sc.index("entry=$(_pad_binfmt_arm)"):]
    body = body[:body.index("\nfi\n")]
    assert '"$entry" != exec' in body


# --- the image -------------------------------------------------------------

def test_the_image_installs_every_linux_prerequisite():
    """The prerequisites row is green from the first start: every package
    the Linux prerequisite installer would pick, plus fuse2fs, which the
    emulator otherwise fetches with apt from package lists the image does
    not keep."""
    inst = (REPO / "installer" / "install_prerequisites_linux.sh").read_text(
        encoding="utf-8")
    body = inst.split("MFR_PACKAGES=(", 1)[1].split("\n)", 1)[0]
    wanted = set()
    for pkgs in re.findall(r'^\s*\[\d+\]="([^"]*)"', body, re.M):
        wanted.update(pkgs.split())
    df = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    installed = set()
    for run in re.findall(r"apt-get install -y[^\n]*\\\n((?:.*\\\n)*.*)", df):
        installed.update(w for w in re.split(r"[\s\\]+", run)
                         if re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", w))
    assert wanted - installed == set()
    assert "fuse2fs" in installed


def test_the_image_does_not_ask_for_privileges_it_does_not_need():
    df = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    assert "START_DOCKER=false" in df     # no Docker daemon of its own
    assert "baseimage-selkies" in df      # picture AND sound in the browser
    guide = (REPO / "docs" / "guide" / "docker.md").read_text(encoding="utf-8")
    run = guide[guide.index("docker run -d"):]
    run = run[:run.index("```")]
    assert "--privileged" not in run
    assert "--cap-add SYS_ADMIN --device /dev/fuse" in run


def test_the_arm_helper_registers_what_the_rig_looks_for():
    helper = (DOCKER / "root" / "usr" / "local" / "bin" /
              "pad-register-arm").read_text(encoding="utf-8")
    assert "/usr/lib/binfmt.d/qemu-arm.conf" in helper
    assert "02002800" in helper           # the rig's own ARM match
    for name in ("pad-app", "pad-register-arm"):
        raw = (DOCKER / "root" / "usr" / "local" / "bin" / name).read_bytes()
        assert raw.startswith(b"#!/bin/bash\n") and b"\r" not in raw
