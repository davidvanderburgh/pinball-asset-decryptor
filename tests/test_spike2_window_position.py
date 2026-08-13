"""Can a remembered window position hide the game window, and does anything say so?

REPORTED 2026-08-13 (PAD-67): "With v0.131, Screen Window is gone again" - the
same reporter, and the same words, as PAD-58, which was fixed in v0.127.4.

THE FIRST THING ESTABLISHED WAS THAT v0.131 DID NOT DO IT.  ``git diff
v0.127.4 HEAD -- padglhost.c`` touches no line of ``win_open``, ``win_pump``,
``winpos_*`` or ``win_place``, and watch.sh's ``PAD_GL_W``/``PAD_GL_H`` are
unchanged: the window path is byte for byte the one that worked for him.  So
nothing here claims to be that user's cause - his run has not been seen.  What
IS fixed is the defect found while looking, which produces exactly "the window
is gone" and is sticky across updates, because the coordinates live in
``~/.pad_windows`` and no release touches them.

MEASURED, on real WSLg, with the REAL renderer built by the real production
command, ``~/.pad_windows`` rigged by hand (and put back afterwards):

    game 9000 9000    restore try 1..5, "game at 6,27" every time,
                      aim marched 17994 -> 26988 -> 35982 -> 44976 -> 53970
    game -3000 -2000  restore try 1..6, "game at 6,27", then GAVE UP
    game 86 59        restore converged after 2 check(s)

Two separate faults in that transcript:

  * THE REMEMBERED POSITION IS NEVER CHECKED AGAINST THE SCREEN.  winreset.sh's
    header has said so in as many words since item 37 - "there is no
    DisplayWidth/bounds test in that file ... a window that is fully off every
    monitor cannot be dragged back" - and the only cure was a button the user
    has to know exists.  THIS compositor clamps the move and the window stays
    visible, which is why it has never been the reproduction it looks like; a
    compositor that honors it opens the window where nobody can see it, every
    run, for ever.
  * THE CORRECTIVE NUDGE RUNS AWAY WHEN A MOVE IS REFUSED.  The aim is advanced
    by the WHOLE error on every try, so a window that does not budge is chased
    six times, six seconds and six lines of noise, and a run stopped inside
    that window never reaches the save that would have corrected the file.

PURE TEXT FOR THE C, the rule test_spike2_picture_oracle.py sets out at length:
the shape is the fix, and there is no gcc, X server or WSL in CI.  The awk half
is NOT text - the real filter is lifted out of watch.sh and run over real
lines, because "does this pattern match" is the kind of claim that reads true
and is false.
"""
import os
import re
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
AWK = shutil.which("awk")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _func(src, name):
    """The body of C function `name`, brace-matched from its opening line."""
    m = re.search(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M)
    assert m, "no such function: %s" % name
    i = src.index("{", m.start())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("unbalanced braces in %s" % name)


def _nocomments(src):
    """`src` with C comments removed, for assertions about CODE.

    The comments here necessarily spell the wrong thing while explaining why it
    is wrong ("DisplayWidth() is a MACRO in Xlib.h"), so a bare search over the
    whole file fails on its own documentation.
    """
    return re.sub(r"/\*.*?\*/", " ", src, flags=re.S)


def _event_filter():
    """The real awk program out of watch.sh, so this is not a test of a copy."""
    src = _read("watch.sh")
    lines = src.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.rstrip().endswith("| awk '"))
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].strip() == "' &")
    return "\n".join(lines[start + 1:end])


# --------------------------------------------------------------------------
# The remembered position is checked before it is obeyed
# --------------------------------------------------------------------------

def test_the_remembered_position_is_checked_against_the_screen():
    """win_open asks whether the saved line is reachable at all.

    The whole defect is that it never used to ask: winpos_get's answer went
    straight into XCreateSimpleWindow and into game_want_x/y.
    """
    src = _read("padglhost.c")
    body = _func(src, "win_open")
    assert "winpos_reachable(" in body, "win_open no longer checks the saved position"
    # ...and the check is BETWEEN reading the file and using the answer.
    assert body.index('winpos_get("game"') < body.index("winpos_reachable(")


def test_the_screen_size_uses_the_function_forms_not_the_macros():
    """DisplayWidth()/DisplayHeight() are macros in Xlib.h and this build has no
    headers - the same trap XDefaultScreen and XBlackPixel are declared for.
    Calling the macro spellings compiles to an implicit declaration and the
    production build uses -Werror=implicit-function-declaration."""
    src = _read("padglhost.c")
    assert "extern int XDisplayWidth(XDisplay *, int);" in src
    assert "extern int XDisplayHeight(XDisplay *, int);" in src
    body = _func(src, "winpos_reachable")
    assert "XDisplayWidth(" in body and "XDisplayHeight(" in body
    # The macro spelling must not be CALLED anywhere in the file.
    code = _nocomments(src)
    assert not re.search(r"[^X]\bDisplayWidth\s*\(", code)
    assert not re.search(r"[^X]\bDisplayHeight\s*\(", code)


def test_an_unreachable_position_is_dropped_not_clamped():
    """Dropping it means the compositor's own placement stands.

    Clamping to 0,0 instead would be a second guess about where the user wants
    the window; game_want_pos = 0 is exactly what a first-ever run does, and
    what Reset windows leaves behind.
    """
    src = _read("padglhost.c")
    body = _func(src, "win_open")
    m = re.search(r"if \(game_want_pos && !winpos_reachable\(.*?\n(.*?)\n        \}",
                  body, re.S)
    assert m, "the unreachable branch is not shaped as expected"
    branch = m.group(1)
    assert "game_want_pos = 0;" in branch, "the position is still restored"
    # `game_settled = !game_want_pos` in win_pump is what makes that mean "no
    # XMoveWindow at all", so the two have to keep agreeing.
    assert "game_settled   = !game_want_pos;" in _func(src, "win_pump")


def test_only_a_rectangle_that_is_wholly_off_the_root_is_refused():
    """The weakest test that still catches an unreachable window.

    A tighter rule would be actively wrong on a multi-monitor root, where a
    window legitimately sits at a large or negative coordinate. Overlap by one
    pixel and it is the user's business, not ours.
    """
    src = _read("padglhost.c")
    body = _func(src, "winpos_reachable")
    assert "x < sw && y < sh && x + w > 0 && y + h > 0" in body, \
        "the intersection test changed shape - is a partly-off window still kept?"
    # A screen that cannot be measured must not cause a move.
    assert "if (sw <= 0 || sh <= 0) return 1;" in body


def test_the_remembered_size_is_still_restored():
    """The size is not what hides a window, and it is already bounded. Losing it
    would undo the reason the file has five fields at all (David enlarges the
    window every session)."""
    src = _read("padglhost.c")
    body = _func(src, "win_open")
    assert "gw >= 160 && gh >= 120 && gw <= 7680 && gh <= 4320" in body
    assert "win_w = gw; win_h = gh;" in body


# --------------------------------------------------------------------------
# The restore stops chasing a move that is being refused
# --------------------------------------------------------------------------

def test_a_refused_move_stops_the_restore_instead_of_aiming_again():
    """Two identical readings mean the compositor is refusing, not missing.

    Without this the aim is advanced by the whole error every try and marches
    away from the screen - measured 17994 -> 53970 on a real WSLg while the
    window never left 6,27.
    """
    src = _read("padglhost.c")
    body = _func(src, "win_pump")
    assert "game_seen && ax == game_seen_x && ay == game_seen_y" in body, \
        "the refusal detector is gone; the aim can run away again"
    # It STOPS - it does not issue another move and does not keep the retry
    # budget burning.
    refusal = body[body.index("game_seen && ax == game_seen_x"):]
    refusal = refusal[:refusal.index("} else {")]
    assert "game_settled = 1;" in refusal
    assert "XMoveWindow" not in refusal, "a refused move is issued again"


def test_the_aim_only_advances_on_a_window_that_actually_moved():
    """game_seen is updated in the nudge branch, so the comparison above is
    against the PREVIOUS try rather than against a stale reading."""
    src = _read("padglhost.c")
    body = _func(src, "win_pump")
    nudge = body[body.index("game_seen = 1; game_seen_x = ax;"):]
    nudge = nudge[:nudge.index("XMoveWindow")]
    assert "game_aim_x += game_want_x - ax;" in nudge
    # The legend window gets the same treatment - it is the same loop and the
    # same six-try budget.
    assert "legend_seen && ax == legend_seen_x && ay == legend_seen_y" in body


def test_the_refusal_is_reported_with_the_button_that_cures_it():
    """A give-up the user cannot act on is how PAD-58 became PAD-67."""
    src = _read("padglhost.c")
    body = _func(src, "win_pump")
    assert "Reset windows" in body


# --------------------------------------------------------------------------
# ...and it reaches the user
# --------------------------------------------------------------------------

@pytest.mark.skipif(not AWK, reason="no awk")
def test_the_event_filter_carries_the_window_verdict_to_the_pane():
    """The renderer's own log is the half the app never shows. That gap has now
    cost three tickets (headless lines, then the picture lines, now this)."""
    lines = [
        "[padglhost] window: remembered position 9000,9000 is off every screen "
        "(1920x1080); opening where the compositor puts it instead. "
        "'Reset windows' on the Emulate tab clears it for good.",
        "[padglhost] window: the compositor will not put the game window at "
        "9000,9000 - it stayed at 6,27 after 2 tries. Leaving it there. "
        "('Reset windows' on the Emulate tab forgets the remembered spot.)",
        "[padglhost] window opened 1360x768 on DISPLAY=:0",
        "[padglhost] restore try 1: game at 92,86 want 86,59 -> aim 80,32",
        "just some line",
    ]
    out = subprocess.run([AWK, _event_filter()], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = out.stdout.splitlines()
    for want in lines[:3]:
        assert "[event] " + want in got, "the pane never sees: %s" % want
    # The per-try chatter stays out of the pane: it is a diagnostic for the
    # renderer's own log, and the verdict above already carries the outcome.
    assert not [g for g in got if "restore try 1" in g]
    assert not [g for g in got if "just some line" in g]


def test_the_no_window_advice_offers_the_reversible_cure_first():
    """"Restart WSL" was the only advice, and it is useless against a window
    that opened off-screen: the coordinates come straight back out of
    ~/.pad_windows on the next run."""
    src = _read("watch.sh")
    start = src.index('*"window opened"*)')
    block = src[start:src.index(";;", start)]
    assert "Reset windows" in block, "the off-screen cure is not offered"
    assert "Restart WSL" in block, "the mirror cure was dropped"
    assert block.index("Reset windows") < block.index("Restart WSL"), \
        "the cheap reversible cure should be tried first"
