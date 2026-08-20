"""The game window remembering which monitor it was on.

THE PROBLEM.  The game runs inside a nested Xephyr server (``display.sh``) and
Xephyr's own window is an ordinary window on the Windows desktop.  Nothing
persists where that window was: Xephyr cannot position its own host window (its
``-screen +X+Y`` and ``-origin`` place a screen inside the *virtual X screen*,
not on the desktop), the game has no say, and WSLg does not remember.  So every
launch dropped the game wherever the compositor chose - on a multi-monitor
desktop, usually the wrong monitor.

These are static checks on the wiring, because the behaviour itself is Win32 and
WSLg and cannot be exercised on a build agent.  What they protect is the part
that WAS got wrong by hand: saving after the window is already dead, matching a
title that WSLg has renamed, and letting a convenience abort a teardown.
"""

import os
import re

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "jjp_emu")


def read(name):
    path = os.path.join(RIG, name)
    if not os.path.exists(path):
        pytest.skip("%s not present" % name)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def code(name):
    """The file with its comment lines removed.

    These scripts explain at length what they deliberately do NOT do - so a
    naive substring search finds the very thing the comment says is avoided, and
    the test passes or fails on prose rather than on behaviour.
    """
    return "\n".join(l for l in read(name).splitlines()
                     if not l.lstrip().startswith("#"))


def test_the_rig_ships_both_halves():
    assert os.path.isfile(os.path.join(RIG, "winpos.sh"))
    assert os.path.isfile(os.path.join(RIG, "winpos.ps1"))


def test_the_position_is_saved_before_anything_kills_the_window():
    """THE ordering bug.  Once Xephyr is gone there is no window left to ask,
    so a save that runs after the kill records nothing - and the first version
    of this looked correct while remembering nothing at all."""
    for script, killer in (("stop.sh", 'bash "$HERE/killgame.sh"'),
                           ("display.sh", 'pkill -TERM -f "Xephyr')):
        src = code(script)
        save = src.index('winpos.sh" save')
        kill = src.index(killer)
        assert save < kill, "%s saves the window position after killing it" % script


def test_restore_runs_after_the_display_is_up():
    """Restoring before the window exists moves nothing."""
    src = read("display.sh")
    up = src.index("Xephyr up on")
    restore = src.index("winpos.sh\" restore")
    assert up < restore


def test_neither_hook_can_abort_the_rig():
    """A window position is a convenience.  Failing a launch - or worse, a
    teardown - over one would be absurd, and stop.sh runs under `set -u` where
    a non-zero return is easy to make fatal."""
    for script in ("stop.sh", "display.sh"):
        src = read(script)
        for line in src.splitlines():
            if "winpos.sh" in line and "usage" not in line:
                assert "|| true" in line, "unguarded winpos call in %s: %s" % (
                    script, line.strip())


def test_the_title_pattern_survives_wslg_renaming_the_window():
    """WSLg appends " (Ubuntu)" to every window title, so an exact match finds
    nothing.  The pattern must also come from the MOUNTED title - the rig is
    title-agnostic and nothing in it may hard-code Wonka."""
    src = read("winpos.sh")
    pat = re.search(r"printf\s+'([^']*)'\s+\"\$\(jjp_title\)\"", src)
    assert pat, "the title pattern must be built from jjp_title"
    assert pat.group(1).endswith("*"), "pattern must be a prefix match"
    assert "wonka" not in src.lower()


def test_a_minimised_window_does_not_overwrite_a_good_position():
    """Windows reports a minimised window at -32000, and restoring that would
    put the game off-screen - which reads as a launch that did nothing."""
    src = read("winpos.sh")
    assert "-30000" in src
    assert "minimised" in src.lower()


def test_only_a_rect_that_parses_is_written():
    """A failed read must never clobber a remembered position."""
    src = read("winpos.sh")
    body = src[src.index("save)"):src.index("restore)")]
    assert 'if [ -z "$X" ] || [ -z "$Y" ]' in body
    assert body.index('if [ -z "$X" ]') < body.index("> \"$JJP_WIN_FILE\"")


def test_windows_side_enumerates_rather_than_asking_for_one_title():
    """WSLg windows are RAIL windows hosted by msrdc, and a process exposes ONE
    MainWindowTitle - so Get-Process finds a single WSLg window whichever of
    them is open.  With the matrix and the game both up that is a coin toss."""
    ps = code("winpos.ps1")
    assert "EnumWindows" in ps
    # Checked against the CODE, not the file: the header explains at length why
    # MainWindowTitle is the wrong tool, and a naive search finds that comment.
    assert "MainWindowTitle" not in ps
    # Moving the window must not raise it over what the user is looking at, nor
    # steal focus: SWP_NOZORDER (0x0004) | SWP_NOACTIVATE (0x0010).
    assert "0x0004 -bor 0x0010" in ps
    # Position-only moves must not resize: SWP_NOSIZE (0x0001).
    assert "0x0001" in ps


def test_it_speaks_key_equals_value_like_the_rest_of_the_rig():
    """A control surface must never have to parse prose - the same rule
    status.sh follows."""
    ps = read("winpos.ps1")
    for key in ("x=", "y=", "w=", "h="):
        assert '"%s{0}"' % key in ps or "'%s{0}'" % key in ps or key in ps
