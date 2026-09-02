"""Stop must end a run, not start one (item 90).

2026-09-02, live: David pressed Stop in the Emulate tab with the boot
selector's menu on screen. killgame.sh swept the rig ("killed 23; still
running: 2"), then reported STILL NOT CLEAN and
``PAD_STOP_NEEDS_WSL_RESTART``, and the app offered to restart WSL.

THE MECHANISM, measured on the app's own launch shape (root, PAD_PIVOT, a
three-image card)::

    unshare -m -p -f setsid bash -s /home/david/spike2root ...   <- 42141, OUR pid ns
      bash -s /home/david/spike2root ...                         <- 42142, NSpid 42142 1
        codeselect ...                                           <- 42175, NSpid 42175 28

The ``unshare`` wrapper is OUTSIDE the new PID namespace (its ``ns/pid`` is
the caller's), so killing it does not end anything inside.  The bash it forks
IS the namespace's init, and it is the second half of run_game.sh: the INNER
heredoc, still a shell for as long as the menu is up.  That script takes the
selector's EXIT STATUS as the choice - so ``pkill -9 -x codeselect`` read to
it as "the selector exited 137", it printed "[select] fallback: primary" and
fell through to the game's exec.  PID 42142 came back a moment after the
sweep as ``game /.padqemu/game ./game``: a brand new guest, started by the
stop that was meant to end the run.

THE FIX is to kill the namespace's init FIRST.  The kernel SIGKILLs every
member of a PID namespace whose init dies, so nothing in there can outlive
the sweep or start anything after it - whatever the inner script was in the
middle of.  Verified live: the same Stop with the menu up now prints "killed
18; still running: 0", with ``alive.sh --total`` 0 and no card mount left,
in both launch shapes (root PAD_PIVOT and the ordinary ``unshare -r`` user
run), and a run with no menu tears down exactly as it did before.

These tests read the scripts rather than running them: the fault needs WSL,
a 17 GB card and a live menu to see, and it is a fault of ORDER and of one
pattern, both of which are readable.  The one thing that is DRIVEN is the
pattern itself, against the command lines this rig actually measured.
"""
import os
import re

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

#: The guest's namespace init, as ps showed it - both launch shapes, measured
#: 2026-09-02 with the selector's menu up.  argv[0] is ``bash`` in both: a
#: root PAD_PIVOT run's ``setsid`` EXECs the shell rather than forking it.
NSINIT_USER = ("bash -s /home/david/spike2root /dev/pts/4 turtles_pro "
               "/home/david/card/tmnt_multi3/turtles_pro  p3\t...")
NSINIT_PIVOT = ("bash -s /home/david/spike2root /dev/pts/5 turtles_pro "
                "/home/david/card/tmnt_multi3/turtles_pro 1 /usr/sbin/pivot_root")
#: ...and the things that must NOT be mistaken for it.
WRAPPER = ("unshare -m -p -f setsid bash -s /home/david/spike2root /dev/pts/5 "
           "turtles_pro")
RUN_GAME = ("bash /mnt/c/Users/david/Documents/development/pinball-asset-"
            "decryptor/tools/spike2_emu/run_game.sh")
PIVOT_GUEST = "/.padqemu/game ./game"
OTHER_ROOTFS = "bash -s /home/david/spike2root2 /dev/pts/5 turtles_pro"


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8", newline="") as fh:
        return fh.read()


def _code(text):
    """The script with its comment lines removed."""
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))


def _nsinit_pattern(text):
    """The pkill/pgrep pattern the script uses for the namespace init."""
    m = re.search(r'-f "(\^[^"]*bash -s \$ROOT ?)"', text)
    assert m, "no anchored `bash -s $ROOT` pattern in this script"
    return m.group(1)


def test_the_namespace_init_pattern_matches_what_ps_measured():
    """Both launch shapes, and nothing else.

    A pattern is only as good as what it does NOT match: the wrapper carries
    the same words on its own command line one process up, and matching that
    instead would kill the process whose -m namespace is holding the card
    mounts while leaving the init - and the guest - running.
    """
    pat = _nsinit_pattern(_read("killgame.sh")).replace("$ROOT",
                                                        "/home/david/spike2root")
    rx = re.compile(pat)
    assert rx.search(NSINIT_USER), "the ordinary user run's init is not matched"
    assert rx.search(NSINIT_PIVOT), "the root PAD_PIVOT run's init is not matched"
    # A setsid that FORKS rather than execs (not this machine, but the shape
    # exists) leaves the init with setsid's own argv.
    assert rx.search("setsid " + NSINIT_PIVOT)
    assert not rx.search(WRAPPER), "the unshare wrapper is not the init"
    assert not rx.search(RUN_GAME), "run_game.sh's own shell is not the init"
    assert not rx.search(PIVOT_GUEST), "a running guest is counted as the guest"
    assert not rx.search(OTHER_ROOTFS), "$ROOT must pin the pattern to this rootfs"


def test_the_sweep_kills_the_namespace_init_before_anything_inside_it():
    """Order is the whole fix.

    Killed after the leaves, this changes nothing: the inner script has
    already read the selector's death as a choice and exec'd a guest by then.
    """
    kill = _code(_read("killgame.sh"))
    ns = kill.index("bash -s $ROOT")
    assert ns < kill.index("pkill -9 -x game")
    assert ns < kill.index("pkill -9 -x codeselect")
    assert ns < kill.index("pkill -9 -f 'arm-binfmt|qemu-arm'")


def test_the_unshare_wrapper_is_still_killed_and_still_later():
    """It is NOT the namespace init and it is not a substitute for killing it.

    It is killed for its own reason - its -m namespace holds a reference to
    every card mount, and the unmount pass below it cannot work until that
    goes - so it stays where it is, with the other run scripts, after the
    guest is down.
    """
    kill = _code(_read("killgame.sh"))
    wrapper = kill.index("pkill -9 -f '^unshare (-r )?-m -p -f'")
    assert kill.index("bash -s $ROOT") < wrapper
    assert wrapper < kill.index('for m in "$PAD_HOME/card/"*/')


def test_a_run_with_no_menu_tears_down_exactly_as_it_did():
    """The guest's PID is the namespace init on EVERY run - by the time a
    plain run's guest is up, that PID has exec'd the game and the pattern
    above no longer matches it.  So the lines a menu-less stop depends on
    have to be untouched, in their old order.
    """
    kill = _code(_read("killgame.sh"))
    assert kill.index("pkill -9 -x game") \
        < kill.index("pkill -9 -f 'arm-binfmt|qemu-arm'") \
        < kill.index("pkill -9 -x codeselect") \
        < kill.index("pkill -9 -x padglhost")


def test_alive_counts_the_namespace_init_from_the_same_one_pattern():
    """The rig's founding rule: what a run starts is counted, once, in
    alive.sh - and killgame.sh does not keep its own copy of the list.

    This one was invisible for the whole window in which it could restart a
    game: no row here would have shown the process that was about to do it.
    """
    alive = _read("alive.sh")
    assert _nsinit_pattern(alive) == _nsinit_pattern(_read("killgame.sh")), \
        "alive.sh and killgame.sh disagree about what the guest's init is"
    procs = next(ln for ln in alive.splitlines() if ln.startswith("PROCS=$(("))
    assert "NSINIT" in procs, "counted in --procs/--total, not just printed"
    assert "guest ns init" in alive, "no row for it in the report"
    assert "bash -s /" in alive[alive.index("--- what is still up ---"):], \
        "counted but not printable: the row would say 1 and the list nothing"
