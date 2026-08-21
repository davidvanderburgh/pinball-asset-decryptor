"""The game window remembering which monitor it was on.

THE PROBLEM.  The game runs inside a nested Xephyr server (``display.sh``) and
Xephyr's own window is an ordinary window on the Windows desktop.  Nothing
persists where that window was: Xephyr cannot position its own host window (its
``-screen +X+Y`` and ``-origin`` place a screen inside the *virtual X screen*,
not on the desktop), the game has no say, and WSLg does not remember.  So every
launch dropped the game wherever the compositor chose - on a multi-monitor
desktop, usually the wrong monitor.

These are static checks on the wiring, because the behaviour itself needs a live
WSLg desktop and cannot be exercised on a build agent.  What they protect is
what WAS got wrong by hand: reaching around the compositor with a Win32 call,
restoring a size that killed the X server, saving after the window is already
dead, matching a title WSLg has renamed, and letting a convenience abort a
teardown.
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


def test_the_move_goes_through_x_not_win32():
    """THE mechanism, and it is not a preference.

    The first version used SetWindowPos and could not work: measured, a Win32
    move changed what WINDOWS reported (508,4 -> 628,94 -> 508,4) while X went
    on reporting +800+65 throughout.  Windows and Weston then disagree about
    where the surface is, which is what left a window that could no longer be
    dragged by its title bar - and the version that also restored the SIZE
    killed the nested X server outright and took the game with it.

    An X move propagates BOTH ways (X +800+65 -> +306+147, Windows 508,4 ->
    179,59), so the compositor stays in step.
    """
    assert os.path.isfile(os.path.join(RIG, "winpos.sh"))
    assert not os.path.isfile(os.path.join(RIG, "winpos.ps1")), (
        "the Win32 half must not come back - it cannot keep WSLg in step")
    src = code("winpos.sh")
    assert "xdotool windowmove" in src
    assert "SetWindowPos" not in src and "powershell" not in src.lower()


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
    assert "jjp_title" in src, "the pattern must be built from the mounted title"
    # xdotool --name is a REGEX and WSLg appends " (Ubuntu)", so the pattern
    # must not be anchored at the end or it matches nothing.
    pat = re.search(r"printf\s+'([^']*)'\s+\"\$\(jjp_title\)\"", src)
    assert pat and not pat.group(1).endswith("$")
    assert "wonka" not in src.lower()


def test_restore_moves_the_window_but_never_resizes_it():
    """Restoring a SIZE killed the nested X server and took the game with it:

        X connection to :1 broken (explicit kill or server shutdown)
        XIO: fatal IO error 2 on X server ":1"

    Before it died it went black, because the host window ended up 957x577
    while its X screen was still 1360x768 and WSLg painted the mismatch black -
    while the X content underneath was perfectly healthy (98.8% non-black in a
    grab.sh capture, showing GnR's attract).  So only a position is ever stored
    or applied.
    """
    src = code("winpos.sh")
    assert "windowsize" not in src, "never resize the Xephyr window"
    # The saved state is a position and nothing else.
    assert '"x":%s,"y":%s' in src
    for k in ('"w":', '"h":'):
        assert k not in src, "size must not be recorded; it invites restoring it"


def test_the_frame_offset_is_measured_not_assumed():
    """windowmove takes a FRAME coordinate while getwindowgeometry reports the
    window's, so asking for the remembered number lands close but not on it.
    Hard-coding a decoration size is a number every WM disagrees about; moving,
    measuring and correcting by the error needs to know nothing."""
    src = code("winpos.sh")
    body = src[src.index("restore)"):]
    assert body.count("xdotool windowmove") >= 2, (
        "restore must correct itself after measuring")


def test_a_minimised_window_does_not_overwrite_a_good_position():
    """Windows reports a minimised window at -32000, and restoring that would
    put the game off-screen - which reads as a launch that did nothing."""
    src = read("winpos.sh")
    assert "-20000" in src
    assert "minimised" in src.lower()


def test_a_key_failure_on_a_reused_jail_heals_itself_once():
    """H0007 with the key sitting right there is usually the JAIL, not the key.

    hasplmd keeps state under /var/hasplm inside the overlay and the overlay
    outlives stop.sh, so a jail that has already hosted a run can come back with
    a licence daemon that will not see the key however often it is
    re-registered.  Measured 2026-08-20: three launches H0007'd on a key whose
    USB descriptors read back perfectly, BOTH titles failing identically - and a
    single unjail plus relaunch worked first time.  Telling the user to find a
    different dongle would have been wrong every time.
    """
    src = code("watch.sh")
    assert 'rc" = "7"' in src, "the heal must trigger on the key exit code"
    heal = src[src.index('rc" = "7"'):]
    assert "unjail.sh" in heal and "jail.sh" in heal
    # Only worth retrying when the key IS there - if it is genuinely absent, a
    # rebuild cannot conjure one and the printed message is already correct.
    assert "key_visible" in heal
    # Bounded to ONE retry.
    assert "JJP_JAIL_HEAL=0" in heal


def test_key_visible_has_exactly_one_definition():
    """watch.sh and run_game.sh must not disagree about whether the key is
    there - they take opposite actions on the answer."""
    shared = code("padpath.sh")
    assert "key_visible()" in shared
    for script in ("run_game.sh", "watch.sh"):
        body = code(script)
        assert "key_visible" in body, "%s should use the shared check" % script
        assert "key_visible()" not in body, \
            "%s defines its own copy of key_visible" % script


def test_only_a_rect_that_parses_is_written():
    """A failed read must never clobber a remembered position."""
    src = read("winpos.sh")
    body = src[src.index("save)"):src.index("restore)")]
    assert 'if [ -z "${X:-}" ] || [ -z "${Y:-}" ]' in body
    assert body.index('if [ -z "${X:-}" ]') < body.index('> "$JJP_WIN_FILE"')




def test_both_windows_are_handled_by_one_mechanism():
    """The matrix needs this as much as the game does, for its own reason.

    It is a Tk window that tries to place ITSELF and cannot: under WSLg Tk reads
    its own position as -32768, so jjpsw.py wrote "1450x1754+-32768+-32768" and
    its own restore regex then refused to match it - throwing the geometry away
    on every launch.  That looked like the feature working, because the window
    always reopened at the default, which happened to be the size it was.
    """
    src = code("winpos.sh")
    assert "TARGET=${2:-game}" in src, "the window to act on must be selectable"
    assert "switch matrix" in src
    # Separate state, or one window's position overwrites the other's.
    assert "jjp_window.json" in src and "jjp_matrix_window.json" in src

    launch = code("jjpsw_launch.sh")
    assert 'winpos.sh" restore matrix' in launch
    stop = code("stop.sh")
    assert 'winpos.sh" save game' in stop and 'winpos.sh" save matrix' in stop


def test_the_matrix_persists_its_size_but_not_its_position():
    """Tk gets the size right and the position wrong, so it keeps exactly the
    half it can do.  Persisting the position it reports is what produced a
    geometry string nothing could read back."""
    path = os.path.join(RIG, "jjpsw.py")
    if not os.path.exists(path):
        pytest.skip("jjpsw.py not present")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    i = src.index("def save_geometry")
    body = src[i:i + 900]
    # The saved string is trimmed to WxH before it is written.
    assert r"(\d+x\d+)" in body
    assert "-32768" in src, "the reason must be recorded where it bit"
