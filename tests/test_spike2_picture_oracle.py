"""Can the rig say whether there is a picture, when the window is black?

THE FAULT, reported 2026-08-12 (PAD-63): a black game window, and a log in
which every instrument the rig owns read healthy.  The card mounted, the guest
booted, the node bus went quiet, auto-advance reached attract mode, ffmpeg
decoded the clips, the guest was handed 30.0 frames/s, and ``padglhost``
reported 40.9 fps over 4210 frames with 28.4 video uploads/s and a 15.36 ms/f
swap - which is to say ``win_present()`` ran, the blit ran and
``eglSwapBuffers`` was called for every frame.  Nothing in any of that can tell
the two possible faults apart:

  * the picture is BLACK WHERE IT IS DRAWN, and the window is innocent;
  * the picture is fine here and is lost between the swap and the Windows
    desktop - WSLg's RAIL mirror, REMAINING item 38 - and a restart cures it.

They want opposite work and the log offered no way to choose, so the answer was
"restart WSL and see", which is a whole session spent on a coin toss.

The measurement itself was never the missing part: ``present()`` has read the
non-black percentage of the screen FBO since item 27.  It was gated on
``PADGL_DEBUG``, which nobody sets, capped at frame 400 - about ten seconds in,
while a boot is legitimately still black - and printed into ``padglhost.log``,
which the app never showed.  So the tests here are about the three things that
made it useless rather than about the readback: it runs unasked, it says
something only when the answer CHANGES, and what it says reaches the log pane.

PURE TEXT FOR THE C, for the reason ``test_spike2_emu_video_threads.py`` gives
at length: the shape is the fix.  The awk half is NOT text - the real filter is
lifted out of watch.sh and run over real lines, because "does this pattern
match" is exactly the kind of claim that reads true and is false.
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


# --------------------------------------------------------------------------
# The oracle itself
# --------------------------------------------------------------------------

def test_the_picture_check_runs_without_being_asked():
    """Not behind PADGL_DEBUG, and not capped at an early frame number.

    Both of those are why the reading existed for two months and answered
    nobody: the debug block below it is `dbg && frames_done <= 400 && ...`, and
    a boot is still black at frame 400.
    """
    src = _read("padglhost.c")
    body = _func(src, "pic_check")
    assert "dbg" not in body, "the oracle is gated on the debug flag again"
    assert "frames_done <=" not in body, "the oracle stops after N frames again"
    # And it is actually called, from the one place that sees every frame.
    assert "pic_check();" in _func(src, "present")


def test_the_picture_check_has_an_off_switch():
    src = _read("padglhost.c")
    assert 'getenv("PAD_GL_PICCHECK")' in src
    assert "pic_every <= 0.0" in _func(src, "pic_check")


def test_a_dark_scene_is_not_reported_as_a_black_screen():
    """The decision is on the PIXEL COUNT, never on a rounded percentage.

    A percentage is the obvious return value and it is wrong: a dark scene with
    a small logo in it rounds to 0%, and reporting that as a black screen is
    the single mistake this oracle exists not to make.
    """
    src = _read("padglhost.c")
    assert "screen_nonblack_px" in src, "renamed away from the pixel count?"
    assert "if (lit > 0)" in _func(src, "pic_check")
    assert "lit * 100" not in _func(src, "pic_check")


def test_the_readback_puts_the_framebuffer_binding_back():
    """It runs mid-stream, so the guest's own binding has to survive it - the
    same rule jgl_poll's on-demand shot follows.

    Item 44 moved the readback into fbo_nonblack_px so the d2 oracle shares
    it; screen_nonblack_px is a wrapper now, and the guard follows the code
    that actually binds."""
    src = _read("padglhost.c")
    body = _func(src, "fbo_nonblack_px")
    assert "0x8CA6" in body, "the previous binding is never read"
    assert body.index("p_glBindFramebuffer(0x8D40, fbo)") \
        < body.index("(unsigned)prev"), \
        "it binds the target FBO and never puts the old one back"
    assert "fbo_nonblack_px(fbo_screen, fb_w, fb_h)" in \
        _func(src, "screen_nonblack_px"), \
        "the d0 wrapper no longer reads the d0 screen"


def test_it_speaks_on_a_change_and_not_on_a_timer():
    """Four lines at most in a run, all of them a state change.

    A number every five seconds is noise, and noise in this pane is what buried
    the last two faults of this shape.
    """
    body = _func(_read("padglhost.c"), "pic_check")
    assert body.count("fprintf(") == 4, "the oracle grew a fifth thing to say"
    for phrase in ("picture: FIRST", "picture: back", "picture: GONE BLACK",
                   "picture: STILL BLACK"):
        assert phrase in body, "lost the %r line" % phrase


def test_the_black_screen_verdict_needs_no_timeout():
    """"Still black after N seconds" needs a number that is right for every
    title's boot, and there is no such number - this user's own run reached its
    first clip 74 s in.  Video frames arriving into an empty screen is a
    contradiction whatever the clock says, so that is what it waits for."""
    body = _func(_read("padglhost.c"), "pic_check")
    assert "vid_distinct > 0" in body
    assert "pic_every" in body        # the only clock in here is the sampler


# --------------------------------------------------------------------------
# ...and it has to reach the app's log pane
# --------------------------------------------------------------------------

def _event_filter():
    """The real awk program out of watch.sh, so these are not tests of a copy."""
    src = _read("watch.sh")
    lines = src.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.rstrip().endswith("| awk '"))
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].strip() == "' &")
    return "\n".join(lines[start + 1:end])


@pytest.mark.skipif(not AWK, reason="no awk")
def test_the_event_filter_carries_the_picture_lines_to_the_pane():
    """The lines that explain a black window must not be in the half of the log
    the app never shows - which is exactly where the headless explanations sat
    until the run that needed them."""
    lines = [
        "[padglhost] picture: FIRST at frame 240 (812345 of 1044480 pixels are not black)",
        "[padglhost] picture: GONE BLACK at frame 900 - the renderer is still drawing",
        "[padglhost] picture: back at frame 1100 (700000 of 1044480 pixels)",
        "[padglhost] picture: STILL BLACK after 240 video frames - the game is drawing",
        "[padglhost] window opened 1360x768 on DISPLAY=:0",
        "[padglhost] 40.9 fps (4048 frames total)  vid 28.4 uploads/s 28.4 NEW/s",
        "just some line",
    ]
    out = subprocess.run([AWK, _event_filter()], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = out.stdout.splitlines()
    for want in lines[:4]:
        assert "[event] " + want in got, "the pane never sees: %s" % want
    # Unchanged: the window line still gets through, the two-second stats line
    # still does not (it is 30 lines a minute and means nothing on its own).
    assert "[event] " + lines[4] in got
    assert not [g for g in got if "fps (4048" in g]
    assert not [g for g in got if "just some line" in g]


# --------------------------------------------------------------------------
# ...and the configuration that actually produces a black window
# --------------------------------------------------------------------------

def test_root_with_nobody_to_drop_to_is_told_its_window_will_be_black():
    """The one configuration that makes the window black on purpose.

    watch.sh's own header records the measurement: as root the renderer cannot
    attach to the WSLg X server's shared memory and THE WINDOW IS BLACK.  The
    drop dance exists to prevent it and is skipped in exactly one case - root
    with no user to drop to, which is a WSL whose DEFAULT USER IS ROOT.  That
    case used to run the renderer as root in silence; PAD-63 is what it costs.
    """
    src = _read("watch.sh")
    i = src.index("THIS WSL RUNS AS ROOT")
    guard = src[max(0, i - 2200):i]
    assert '[ "$(id -u)" = 0 ] && [ "$DROP" = 0 ]' in guard, \
        "the warning is not gated on root-with-no-drop-target"
    block = src[i:i + 1800]
    assert "BLACK" in block
    assert "default=<name>" in block, "it does not name the cure"
    assert "exit" not in block.split("fi", 1)[0], \
        "this became fatal; the rest of the run is real (see the ffmpeg guard)"


@pytest.mark.skipif(not shutil.which("bash"), reason="no bash")
def test_the_cure_survives_shell_quoting():
    """The middle line of the cure carries nested quotes and a \\n, which is
    exactly the kind of thing that reaches a user mangled.  Run the block."""
    src = _read("watch.sh")
    i = src.index('echo "[watch] THIS WSL RUNS AS ROOT')
    end = src.index("\nfi\n", i)
    out = subprocess.run([shutil.which("bash"), "-c", src[i:end]],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    text = out.stderr
    assert 'printf "[user]\\ndefault=<name>\\n" >> /etc/wsl.conf' in text, text
    assert "adduser <name>" in text


@pytest.mark.skipif(not AWK, reason="no awk")
def test_mesas_own_explanation_reaches_the_pane():
    """Mesa names this fault and the app never showed the line.  It also
    repeats without limit, so it is collapsed like the Radium storm."""
    line = "MESA: error: Failed to attach to x11 shm"
    out = subprocess.run([AWK, _event_filter()], input=(line + "\n") * 3,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = out.stdout.splitlines()
    assert got == ["[event] %s (x1)" % line], \
        "shown once per sighting, or not shown at all: %r" % got


def test_the_window_hint_says_which_half_a_black_window_is():
    """The old hint sent every "no picture" to `Restart WSL...`, which is right
    for a lost mirror and useless for a picture that is black where it is
    drawn.  It now points at the line that knows."""
    src = _read("watch.sh")
    i = src.index("no game window on the desktop?")
    hint = src[i:i + 1400]
    assert "stays BLACK" in hint
    assert "picture:" in hint, "the hint does not name the line that decides"


# --------------------------------------------------------------------------
# ...and the run must stop claiming to know why the renderer went
# --------------------------------------------------------------------------

def test_a_dead_renderer_is_not_reported_as_the_user_closing_the_window():
    """`renderer exited (window closed).` was printed on nothing but "the
    process is gone", so a renderer that DIED read as a human closing a window.
    PAD-63's black-window report arrived with that sentence on the end of it,
    and it was the first thing that had to be established and could not be."""
    src = _read("watch.sh")
    i = src.index("renderer exited (window closed).")
    before = src[max(0, i - 1200):i]
    assert "window \\(closed\\|destroyed\\); stopping" in before, \
        "the claim is not checked against what padglhost actually said"
    after = src[i:i + 900]
    assert "THE RENDERER STOPPED ON ITS OWN" in after
    assert "$HOSTLOG" in after, "and it does not show its last words"
