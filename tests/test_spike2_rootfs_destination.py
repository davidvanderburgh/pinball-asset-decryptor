"""Where the Spike 2 rig is allowed to build its guest filesystem.

THIS FILE EXISTS BECAUSE THE EMULATOR STOPPED STARTING AND NOTHING CAUGHT IT.

rootfs.sh has always refused to extract onto a Windows drive: it drops
symlinks, so ld-linux.so.3 vanishes and nothing in the guest links.  The test
it used for "a Windows drive" was the PATH - anything under /mnt.  That was a
fair shorthand while /mnt/c and its siblings were the only things mounted
there.

Then the app gave the rigs a data disk of their own.  It is ext4, it is
attached to the WSL VM by name so every distro sees it in the same place, and
that place is /mnt/wsl/paddata.  So the app began setting PAD_HOME to exactly
the directory its own rig then refused to build in, and the Spike 2 emulator
did not start at all:

    [rootfs] REFUSING: /mnt/wsl/paddata/spike2/spike2root is a Windows drive

Neither half was wrong on its own, which is why every test passed: the rig's
rule was reasonable, the app's path was reasonable, and nothing anywhere asked
whether the two agreed.  These tests ask.

They run the REAL script rather than a copy of its rule - the bug was in the
script, and a test that re-implemented the rule would have agreed with it.
"""
import os
import pathlib
import re
import subprocess

import pytest

from pinball_decryptor.core import rigdata

REPO = pathlib.Path(__file__).resolve().parent.parent
ROOTFS = REPO / "tools" / "spike2_emu" / "rootfs.sh"


def _bash_runs_scripts():
    """The same guard the installer tests use: a Windows `bash` is git-bash on
    one host and the WSL launcher on the next, and the launcher on a runner
    with no distro answers in UTF-16 and exits 1.  That yanked v0.187.0."""
    try:
        r = subprocess.run(["bash", "-c", 'echo "${BASH_VERSINFO[0]}"'],
                           capture_output=True, timeout=30)
        return int(r.stdout.decode().strip()) >= 4
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        return False


HAS_BASH4 = _bash_runs_scripts()
needs_bash = pytest.mark.skipif(not HAS_BASH4,
                                reason="no bash 4+ to run rootfs.sh with")


def _drive_prefix():
    """How the bash that will run the script spells a Windows drive.

    `bash` on Windows is not one program, and which one it is depends on who
    is asking.  From this pytest process it resolves off the WINDOWS path,
    where it is usually WSL's launcher and drives are /mnt/c; on a GitHub
    windows runner it is git-bash and they are /c.  A path in the wrong
    dialect is "No such file or directory" and exit 127 - a failure that reads
    exactly like the script refusing, which is how these tests first passed
    for the wrong reason.

    ASKED WITHOUT PASSING ARGUMENTS, which is the second trap in the same
    sentence: WSL's bash.exe re-parses its argument line, so `bash -c '...
    "$1"' _ <path>` arrives with $1 EMPTY - `wslpath -u ""` answers "." and
    every path became the current directory.  That is the JJP executor's
    oldest lesson, met again here.  So this probes for a directory instead,
    with nothing to re-parse.
    """
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(
            ["bash", "-c",
             "if [ -d /mnt/c ]; then echo /mnt; elif [ -d /c ]; then echo ''; "
             "else echo none; fi"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    said = r.stdout.strip()
    return None if said == "none" else said


DRIVE_PREFIX = _drive_prefix()


def _bash_path(p):
    """*p* spelled the way that bash understands it."""
    p = str(p)
    if os.name != "nt" or DRIVE_PREFIX is None:
        return p
    p = p.replace(chr(92), "/")
    if len(p) > 1 and p[1] == ":":
        return "%s/%s%s" % (DRIVE_PREFIX, p[0].lower(), p[2:])
    return p


def _run_rootfs(tmp_path, fstype, root):
    """Run the real rootfs.sh with a stubbed ``findmnt`` reporting *fstype*.

    Stubbed rather than mocked away: the script's own decision runs, on the
    answer shape ``findmnt -no FSTYPE -T <path>`` really gives it.  The card is
    an empty file, so a destination that PASSES the check goes on to fail in
    debugfs - which is the evidence that it passed.
    """
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    for tool in ("findmnt", "stat"):
        # `stat -f` is the fallback when findmnt is absent; both answer the
        # same, so a test cannot pass by accident through the other branch.
        f = stub / tool
        f.write_text("#!/bin/sh\necho " + fstype + "\n",
                     encoding="utf-8", newline="\n")
        f.chmod(0o755)

    card = tmp_path / "card.raw"
    card.write_bytes(bytes(1024))

    # RUN THROUGH A WRAPPER, so neither the environment nor the arguments have
    # to cross the Windows/WSL boundary.  Both leak: this process's env does
    # not reach WSL at all without WSLENV - PAD_ROOT simply vanished, the
    # script used the real default, and the test read the DEVELOPER'S OWN
    # rootfs - and WSL's bash.exe re-parses its argument line, so extra
    # positional arguments arrive empty.  A generated script has nothing to
    # cross: every value is already inside it, in that bash's own dialect.
    wrapper = tmp_path / "run.sh"
    wrapper.write_text(
        "#!/bin/sh\n"
        'export PATH="%s:$PATH"\n'
        'export PAD_ROOT="%s"\n'
        'export PAD_HOME="/tmp/pad-rootfs-test"\n'
        'exec bash "%s" "%s"\n'
        % (_bash_path(stub), root, _bash_path(ROOTFS), _bash_path(card)),
        encoding="utf-8", newline="\n")
    return subprocess.run(["bash", _bash_path(wrapper)],
                          capture_output=True, text=True, timeout=120)


@needs_bash
@pytest.mark.parametrize("fstype", ["9p", "drvfs", "v9fs", "cifs"])
def test_a_windows_or_network_destination_is_still_refused(tmp_path, fstype):
    """The rule this was always for, and it has to keep working: an extract
    onto a Windows drive loses its symlinks and the guest cannot link."""
    r = _run_rootfs(tmp_path, fstype, "/somewhere/spike2root")
    said = r.stdout + r.stderr
    assert "REFUSING" in said, said[:500]
    assert r.returncode == 1


@needs_bash
def test_an_ext4_destination_under_mnt_is_allowed(tmp_path):
    """THE REGRESSION.  /mnt/wsl/paddata is ext4 - it only LOOKS like a
    Windows path.  Refusing it stopped the emulator starting on the
    arrangement the app sets up for everybody by default."""
    r = _run_rootfs(tmp_path, "ext4", "/mnt/wsl/paddata/spike2/spike2root")
    said = r.stdout + r.stderr
    assert "REFUSING" not in said, (
        "rootfs.sh refuses the app's own data disk, so the Spike 2 emulator "
        "cannot start:\n" + said[:800])


@needs_bash
def test_the_home_disk_is_still_allowed(tmp_path):
    """Where every machine put it before the data disk existed."""
    r = _run_rootfs(tmp_path, "ext4", "/home/pad/spike2root")
    assert "REFUSING" not in (r.stdout + r.stderr)


@needs_bash
def test_the_script_is_really_running(tmp_path):
    """A guard on the guard.  The two assertions above are about the ABSENCE
    of a word, so a run that died before it ever reached the filesystem check
    - a path this bash cannot open, a renamed variable - satisfies both while
    testing nothing.  That is exactly what happened on the first attempt: exit
    127, "No such file or directory", and two green tests."""
    r = _run_rootfs(tmp_path, "ext4", "/home/pad/spike2root")
    said = r.stdout + r.stderr
    assert r.returncode != 127, said[:400]
    assert "[rootfs]" in said, said[:500]


# ------------------------------------------- and the two halves must agree --

def test_the_rig_accepts_the_directory_the_app_actually_gives_it():
    """The contract that broke, asserted directly and without a shell.

    core/rigdata.py decides where the rigs' work lives; rootfs.sh decides what
    it will build in.  Nothing connected them, so either could change without
    the other noticing - and one did.
    """
    text = ROOTFS.read_text(encoding="utf-8")
    arm = re.search(r'case "\$ROOT_FS" in\s*\n\s*([a-z0-9|]+)\)', text)
    assert arm, "rootfs.sh no longer refuses by filesystem type"
    refused = set(arm.group(1).split("|"))
    assert {"9p", "drvfs"} <= refused, refused

    # ...and it must not have gone back to refusing by PATH, which is the
    # shape of the bug: /mnt/* matches the app's own data disk.
    assert "/mnt/*)" not in text, (
        "rootfs.sh refuses by path again, which rejects %s - where the app "
        "puts every rig's work" % rigdata.MOUNT)
    assert rigdata.MOUNT.startswith("/mnt/"), (
        "the data disk moved; this test's whole point is that it lives "
        "somewhere that LOOKS like a Windows path and is not")
