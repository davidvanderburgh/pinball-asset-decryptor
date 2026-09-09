"""Who a root run drops its helpers to, and why the rootfs cannot answer it.

THE FAULT, reported 2026-09-08 (PAD-119).  A tester's game window was black
run after run, with "MESA: error: Failed to attach to x11 shm" repeating and
every other counter healthy - the black-window signature watch.sh already
names.  He was told the cure the rig prints: add an ordinary account and make
it the distro's default.  He did all three commands, restarted WSL, started
again, and got the same black window.

BECAUSE HIS DISTRO WAS ALREADY DOING THAT.  The same log says so twice: the
Emulate tab's setup check reports ``logs in as: home``, and watch.sh reports
``THIS WSL RUNS AS ROOT`` - and the app's launcher only passes
``HOME=/home/home`` at all when the default user is NOT root.  The distro was
never the problem.

WHAT WAS.  The app's Start is ``wsl -u root ... PAD_PIVOT=1`` on purpose (only
a root guest can be checkpointed), and watch.sh drops every helper back to the
desktop user.  It found that user by asking who owns the ROOTFS - which is the
one directory in the rig that a root run builds itself: ensurebuild.sh makes it
and rootfs.sh fills it with ``debugfs rdump``, which as root restores the
card's own ownership.  So on any machine whose first emulator run came from the
app, the rootfs is root-owned, there is nobody to drop to, the renderer runs as
root and the window is black FOREVER - and the warning blames the distro.

THE HOME IS THE RIGHT QUESTION and the rest of the rig already asks it:
cardmount.sh, overrides.sh and buildselect.sh all hand their output back to
``stat -c %U "$HOME"``.  padpath.sh states the rule - "ROOT IS ELEVATION, NOT
OWNERSHIP: the rig belongs to a human's home".

RUN, NOT READ.  The derivation is four lines of shell about ownership, so a
grep for the right words would pass on code that answers the wrong user.  The
block is lifted out of watch.sh verbatim and executed with ``id`` and ``stat``
replaced by shell functions, which is the only way to see which path it
actually asks about.  Functions rather than stub executables on PATH: this
suite runs under WSL bash here and Git Bash on the Windows runner, and the
executable bit means something different on each.
"""
import os
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def _watch():
    with open(os.path.join(RIG, "watch.sh"), encoding="utf-8",
              errors="replace") as fh:
        return fh.read()


def _derivation():
    """watch.sh's PAD_USER block, from its first line to the DROP verdict."""
    src = _watch()
    i = src.index("PAD_USER=${PAD_USER:-${SUDO_USER:-}}")
    end = src.index("as_user()", i)
    block = src[i:end]
    assert "DROP=1" in block, "the DROP verdict is no longer in this block"
    return block


def _run(owners, home="/home/home", root_dir=None, chosen=""):
    """The block, as root, with `stat -c %U` answering `owners` per path.

    A path that is not in `owners` is reported missing, which is what stat
    does and what the block has to survive.
    """
    stub = ["id() { echo 0; }", "stat() { case \"$3\" in"]
    for path, who in owners.items():
        stub.append("  %s) echo %s ;;" % (path, who))
    stub += ["  *) echo 'stat: no such file' >&2; return 1 ;;", "esac; }"]
    script = "\n".join(
        ["unset PAD_USER SUDO_USER"] + ([chosen] if chosen else []) + stub
        + ["PAD_HOME=%s" % home,
           "ROOT=%s" % (root_dir or home + "/spike2root"),
           _derivation(),
           'echo "VERDICT [$PAD_USER] [$DROP]"'])
    out = subprocess.run([BASH, "-c", script], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("VERDICT ")]
    assert line, out.stdout + out.stderr
    user, drop = line[-1].split("[")[1:]
    return user.split("]")[0], drop.split("]")[0]


@pytest.mark.skipif(not BASH, reason="no bash")
def test_a_root_built_rootfs_still_finds_the_desktop_user():
    """PAD-119 itself: the home is the human's, the rootfs is root's.

    This is every machine whose first emulator run was the app's Start, which
    since v0.126.0 is every machine that has only ever used the app.
    """
    assert _run({"/home/home": "home",
                 "/home/home/spike2root": "root"}) == ("home", "1"), \
        "a root-built rootfs still has to drop to the home's owner"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_a_root_default_distro_still_has_nobody_to_drop_to():
    """The case the black-window warning was written for, unchanged.

    A distro that logs in as root has $HOME=/root, root owns it, and there is
    genuinely no desktop session to hand the renderer to.  The warning below
    it in watch.sh is the right answer for this machine and only this one.
    """
    assert _run({"/root": "root", "/root/spike2root": "root"},
                home="/root") == ("", "0")


@pytest.mark.skipif(not BASH, reason="no bash")
def test_the_rootfs_is_still_asked_when_the_home_cannot_be():
    """The old question kept as the fallback, not deleted.

    A rig whose home this shell cannot stat - an unreadable or automounted
    parent - but whose tree is plainly someone's is still theirs to run.
    """
    assert _run({"/home/home/spike2root": "home"}) == ("home", "1")


@pytest.mark.skipif(not BASH, reason="no bash")
def test_an_explicit_user_beats_both():
    """PAD_USER and SUDO_USER are answers, not hints: neither stat runs, so
    a rig on a path this shell cannot see still drops."""
    assert _run({}, chosen="PAD_USER=chosen") == ("chosen", "1")
    assert _run({}, chosen="SUDO_USER=sudoer") == ("sudoer", "1")


def test_the_home_is_asked_before_the_rootfs():
    """Order is the whole fix, and it is invisible in the outcome above once
    both paths answer the same user.  A future edit that puts the rootfs back
    in front would pass every test here on a machine with a user-owned tree
    and reintroduce PAD-119 on every machine without one."""
    # Comments stripped first: the block's own history note quotes the line it
    # replaces, and a text search finds that before the code.
    code = "\n".join(ln for ln in _derivation().splitlines()
                     if not ln.lstrip().startswith("#"))
    assert code.index('stat -c %U "$PAD_HOME"') \
        < code.index('stat -c %U "$ROOT"'), \
        "the rootfs is asked first again - it answers root on a root-built rig"
