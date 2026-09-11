"""The renderer losing the GPU must not end the run (PAD-117).

THE FAULT, reported 2026-09-08 against v0.194.0.  A Beatles card, a WSL
session that had been up 1190 hours, and a run that ended one second after it
started::

    [padglhost] window opened 1360x768 on DISPLAY=:0
    libEGL warning: DRI3 error: Could not get DRI3 device
    Inconsistency detected by ld.so: dl-setup_hash.c: 36: _dl_setup_hash:
        Assertion (bitmask_nwords & (bitmask_nwords - 1)) == 0 failed!
    [watch] the renderer died on startup:

``watch.sh`` then ran ``exit 1``, so there was no run at all - no guest, no
sound, no playfield - and the last word the user got was a glibc assertion
about a hash table.

TWO THINGS ARE WRONG THERE AND BOTH ARE TESTED HERE.

* **The verdict.**  padglhost opens its window BEFORE it asks for an EGL
  display, so everything after "window opened" is Mesa loading a driver -
  ``dri/d3d12_dri.so`` and then ``libd3d12core.so`` out of ``/usr/lib/wsl/lib``,
  because this script exports ``GALLIUM_DRIVER=d3d12`` on every run.  That
  directory is an overlay of the GPU libraries WSL injects from Windows, and
  Windows replaces them under a VM that is already running.  So the loader
  abort is a STALE-LIBRARY fault with exactly one cure, a VM restart, and
  ``pad_renderer_verdict`` is where that is decided.  These tests drive the
  real shell function against the real log.

* **The trade.**  The GPU is an optimisation; runbridge.sh has had a software
  mode since it was written.  A renderer that cannot start on d3d12 now gets a
  second attempt on llvmpipe, and only a second death ends the run.  That half
  lives in watch.sh, which needs WSL, a card image and a broken GPU stack to
  run, so it is checked as TEXT - and what is checked is ORDER, which is the
  property that would actually break: diagnose, keep the failed log, switch to
  software, try again, and only then give up.
"""
import os
import re
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def src(name):
    with open(os.path.join(RIG, name), encoding="utf8", errors="replace") as f:
        return f.read()


def line_of(text, needle):
    """1-based line number of the first line containing `needle`."""
    for i, line in enumerate(text.split("\n"), 1):
        if needle in line:
            return i
    raise AssertionError("not found: %r" % needle)


#: The renderer's log as the reporter's machine wrote it, trimmed to the lines
#: watch.sh would have had in front of it.  The assertion text is glibc's own,
#: minus the backticks it wraps the expression in - nothing here reads those,
#: and they are a paste trap in every other file this string travels through.
REPORTED_LOG = """\
[padglhost] no switch list for beatles yet; playfield keys and the trough latch WAIT for it
[padglhost] key binds exported to /home/home/spike2root/dump/padbinds
[padglhost] keyboard -> switches via /home/home/spike2root/dump/padsw
[padglhost] window opened 1360x768 on DISPLAY=:0
libEGL warning: DRI3 error: Could not get DRI3 device
libEGL warning: Ensure your X server supports DRI3 to get accelerated rendering
Inconsistency detected by ld.so: dl-setup_hash.c: 36: _dl_setup_hash: Assertion (bitmask_nwords & (bitmask_nwords - 1)) == 0 failed!
"""

#: EVERYTHING RELATIVE, AND THE SCRIPT ON DISK: the same rule
#: test_spike2_display_guard.py records - on Windows `bash` is as likely to be
#: WSL's launcher as Git's, and that one sees a C:\... path as a name with no
#: directories in it.
_DRIVER = """#!/bin/bash
RIG=$(pwd); export RIG
PAD_HOME=$RIG; export PAD_HOME
. "$RIG/padpath.sh"
echo "VERDICT=$(pad_renderer_verdict "$RIG/hostlog")"
echo "MISSING=$(pad_renderer_verdict "$RIG/no-such-log")"
echo "NOARG=$(pad_renderer_verdict)"
echo "ADVICE<<"
pad_renderer_advice "$(pad_renderer_verdict "$RIG/hostlog")"
echo ">>"
exit 0
"""


def _drive(tmp_path, hostlog, driver=None):
    """Ask the real shell functions what this renderer log means."""
    rig = tmp_path / ("rig%d" % len(list(tmp_path.glob("rig*"))))
    rig.mkdir(parents=True)
    shutil.copy(os.path.join(RIG, "padpath.sh"), str(rig / "padpath.sh"))
    for name, text in (("hostlog", hostlog),
                       ("driver.sh", driver or _DRIVER)):
        with open(str(rig / name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    os.chmod(str(rig / "driver.sh"), 0o755)
    out = subprocess.run([BASH, "driver.sh"], cwd=str(rig),
                         capture_output=True, text=True)
    facts, advice, in_advice = {}, [], False
    for line in (out.stdout + out.stderr).splitlines():
        if line == "ADVICE<<":
            in_advice = True
            continue
        if line == ">>":
            in_advice = False
            continue
        if in_advice:
            advice.append(line)
        elif "=" in line:
            key, _, value = line.partition("=")
            facts[key.strip()] = value.strip()
    facts["advice"] = "\n".join(advice)
    return facts


# --------------------------------------------------------------------------
# THE VERDICT, driven for real.
# --------------------------------------------------------------------------

@pytest.mark.skipif(not BASH, reason="no bash")
def test_the_reported_log_reads_as_a_loader_fault(tmp_path):
    """The ticket's own log, through the real function."""
    assert _drive(tmp_path, REPORTED_LOG)["VERDICT"] == "loader"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_the_loader_verdict_survives_a_reworded_assertion(tmp_path):
    """glibc has respelled this assertion before, and the file:line is a path
    into ITS source tree.  Only the loader's own name is stable, so that is
    what the function may key on."""
    log = ("[padglhost] window opened 1360x768 on DISPLAY=:0\n"
           "Inconsistency detected by ld.so: dl-lookup.c: 111: check_match: "
           "Assertion something entirely different failed!\n")
    assert _drive(tmp_path, log)["VERDICT"] == "loader"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_a_missing_library_is_its_own_verdict(tmp_path):
    """A library that is not INSTALLED is an apt problem, not a stale-overlay
    one, and the two cures have nothing in common."""
    log = ("padglhost: error while loading shared libraries: libEGL.so.1: "
           "cannot open shared object file: No such file or directory\n")
    facts = _drive(tmp_path, log)
    assert facts["VERDICT"] == "nolib"
    assert "Set up emulator" in facts["advice"]
    assert "Restart WSL" not in facts["advice"]


@pytest.mark.skipif(not BASH, reason="no bash")
def test_no_ring_still_points_at_the_rootfs(tmp_path):
    """ensurebuild.sh's own recorded case - four errors, none of them about the
    thing that is missing.  It must not be swept into the graphics answer."""
    log = "open ring: No such file or directory\n"
    facts = _drive(tmp_path, log)
    assert facts["VERDICT"] == "ring"
    assert "card image" in facts["advice"]


@pytest.mark.skipif(not BASH, reason="no bash")
def test_an_unrecognised_death_says_nothing_rather_than_guessing(tmp_path):
    """A verdict with no advice is the honest answer: the renderer's own last
    twenty lines are already on screen above it."""
    facts = _drive(tmp_path, "[padglhost] window opened 1360x768\nsegfault\n")
    assert facts["VERDICT"] == "unknown"
    assert facts["advice"] == ""


@pytest.mark.skipif(not BASH, reason="no bash")
def test_a_log_that_is_not_there_is_unknown_not_an_error(tmp_path):
    """watch.sh asks for the verdict on a path the renderer may never have
    created.  Both spellings of "no log" answer, rather than failing."""
    facts = _drive(tmp_path, REPORTED_LOG)
    assert facts["MISSING"] == "unknown"
    assert facts["NOARG"] == "unknown"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_the_loader_advice_names_the_one_thing_that_fixes_it(tmp_path):
    """A VM restart, in both spellings the user has - the tab's button and the
    Windows command - because nothing inside Linux can re-lay that overlay."""
    advice = _drive(tmp_path, REPORTED_LOG)["advice"]
    assert "Restart WSL" in advice
    assert "wsl --shutdown" in advice
    assert "/usr/lib/wsl/lib" in advice
    # It must not read as an emulator fault, which is what an ld.so assertion
    # reads as to everyone who is not glibc.
    assert re.search(r"not part of Ubuntu", advice)


# --------------------------------------------------------------------------
# THE SECOND ATTEMPT, read out of watch.sh.
# --------------------------------------------------------------------------

def test_the_first_death_no_longer_ends_the_run():
    """The `exit 1` that used to follow "died on startup" immediately is what
    this ticket is about."""
    text = src("watch.sh")
    died = line_of(text, '[watch] the renderer died on startup:')
    retry = line_of(text, "TRYING THE RENDERER AGAIN IN SOFTWARE")
    assert died < retry
    # Nothing may exit between the two: that is the whole bug.
    between = "\n".join(text.split("\n")[died:retry - 1])
    assert "exit 1" not in between


def test_the_order_is_diagnose_keep_switch_retry_give_up():
    """Each step is only useful in this order.  Advice after the retry would
    describe a run that had already moved on; the log copy after the retry
    would copy the retry's own truncated file; a give-up before the retry is
    the fault itself."""
    # From the death onwards, so `pad_gl_software`'s own definition - which is
    # necessarily above all of this - is not what gets found.
    text = src("watch.sh")
    text = text[text.index('echo "[watch] the renderer died on startup:"'):]
    steps = ["the renderer died on startup:",
             "pad_renderer_advice",
             'cp -f "$HOSTLOG" "$HOSTLOG.gpu"',
             "TRYING THE RENDERER AGAIN IN SOFTWARE",
             "        pad_gl_software",
             "if pad_gl_try; then",
             "the software renderer died too"]
    seen = [line_of(text, s) for s in steps]
    assert seen == sorted(seen), dict(zip(steps, seen))


def test_software_means_both_loaders_are_told():
    """LIBGL_ALWAYS_SOFTWARE is what the DRI loader reads, GALLIUM_DRIVER what
    the gallium loader reads.  Naming one leaves the other free to find the
    driver that just died - and this script's own d3d12 export is still in the
    environment at that point."""
    text = src("watch.sh")
    body = text[text.index("pad_gl_software() {"):]
    body = body[:body.index("\n}\n")]
    assert "GALLIUM_DRIVER=llvmpipe" in body
    assert "LIBGL_ALWAYS_SOFTWARE=1" in body
    # The adapter pin is a d3d12 setting and would otherwise stay in the log
    # as a claim about which GPU rendered a run that used none.
    assert "unset MESA_D3D12_DEFAULT_ADAPTER_NAME" in body
    # The cfg block printed d3d12 long before this; a run whose log names a
    # driver it did not use cannot be compared with any other run.
    assert "cfg GALLIUM_DRIVER=llvmpipe" in body


def test_each_attempt_starts_from_no_ring():
    """The startup wait is `[ -s $RING_HOST ] && break`.  Left in place by the
    dead attempt, that file makes the retry's wait return instantly and the
    liveness check land 0.3 s after a launch instead of ~1 s."""
    text = src("watch.sh")
    body = text[text.index("pad_gl_try() {"):]
    body = body[:body.index("\n}\n")]
    assert line_of(body, 'rm -f "$RING_HOST"') < line_of(body, "$PAD_GLHOST_BIN")
    assert line_of(body, "$PAD_GLHOST_BIN") < line_of(body, '[ -s "$RING_HOST" ]')
    # Still the pgid teardown holds: HOSTPG is what the trap kills, and a retry
    # that did not update it would leak the second renderer.
    assert "HOSTPG=$!" in body


def test_software_can_be_asked_for_without_breaking_a_gpu():
    """PAD_GL_SOFTWARE=1 is how the fallback's own path gets exercised on a
    machine whose GPU works, and the answer for one that is known not to."""
    text = src("watch.sh")
    assert '"${PAD_GL_SOFTWARE:-0}" = 1' in text
    assert line_of(text, '"${PAD_GL_SOFTWARE:-0}" = 1') < \
        line_of(text, "if ! pad_gl_try; then")


def test_the_gpu_attempt_is_still_the_default():
    """No machine that works today may quietly drop to software: the retry is
    reached only through a death."""
    text = src("watch.sh")
    assert "export GALLIUM_DRIVER=${GALLIUM_DRIVER:-d3d12}" in text
    assert line_of(text, "PAD_GL_MODE=gpu") < line_of(text, "if ! pad_gl_try; then")
    # A second software death exits rather than looping.
    assert '[ "$PAD_GL_MODE" = gpu ]' in text


# --------------------------------------------------------------------------
# PAD-127: THE RENDERER IS UP AND THERE IS NO WINDOW.
# --------------------------------------------------------------------------
#
# THE FAULT, reported 2026-09-11 with a photograph of the Windows taskbar
# preview of a window that never painted: "whenever I do an update for PAD I
# get no video screen after the update.  I do get the table fine ... a reboot,
# so far, always resolves it."  The table is the virtual playfield, which under
# WSL is a Windows process, so it is the one part of a run that this cannot
# touch - which is exactly why the rest of the run looked healthy.
#
# PAD-117 above gave the GPU path a second chance in software, but only through
# a DEATH: its gate is ``if ! pad_gl_try``.  A renderer that starts, cannot get
# a window surface out of the driver and carries on headless is ALIVE, so it
# walked past that gate, and the run kept its guest, its sound and its playfield
# and lost its picture for the whole session.  Same fault, same cure, and the
# same measurement justifies it.

#: The reporter's failure as the renderer's own log writes it.  The DRI3 line
#: is what comes with it on a WSL whose GPU libraries have gone stale - it is
#: not what is matched on, and it is here so that it cannot be.
_SURFACE_LOG = (
    "[padglhost] keyboard -> switches via /home/home/spike2root/dump/padsw\n"
    "libEGL warning: DRI3 error: Could not get DRI3 device\n"
    "[padglhost] window opened 1360x768 on DISPLAY=:0\n"
    "[padglhost] eglCreateWindowSurface failed 0x3003; falling back to "
    "headless\n"
)

#: The OTHER headless line, and the one no renderer can cure.
_DISPLAY_LOG = (
    "[padglhost] PAD_GL_WINDOW=1 but XOpenDisplay failed (DISPLAY=:0); "
    "staying headless\n"
)

_HL_DRIVER = """#!/bin/bash
RIG=$(pwd); export RIG
PAD_HOME=$RIG; export PAD_HOME
. "$RIG/padpath.sh"
R=$(pad_headless_reason "$RIG/hostlog"); echo "RC=$?"; echo "REASON=$R"
M=$(pad_headless_reason "$RIG/no-such-log"); echo "MISSRC=$?"; echo "MISSING=$M"
N=$(pad_headless_reason); echo "NOARGRC=$?"; echo "NOARG=$N"
exit 0
"""


def _reason(tmp_path, hostlog):
    return _drive(tmp_path, hostlog, _HL_DRIVER)


@pytest.mark.skipif(not BASH, reason="no bash")
def test_a_failed_window_surface_is_the_surface_reason(tmp_path):
    """The reporter's log, through the real function.  This is the case worth
    asking a different driver about: the X window EXISTS and the graphics
    driver would not give a surface for it."""
    facts = _reason(tmp_path, _SURFACE_LOG)
    assert facts["REASON"] == "surface"
    assert facts["RC"] == "0"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_no_x_display_is_a_different_reason_and_not_retried(tmp_path):
    """No renderer of any kind can put a window on a server that is not there,
    so this one must not read as the retryable case - a retry would cost a
    second launch and print a second identical failure."""
    facts = _reason(tmp_path, _DISPLAY_LOG)
    assert facts["REASON"] == "display"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_the_second_displays_surface_failure_is_not_the_main_windows(tmp_path):
    """Item 44's second display prints "eglCreateWindowSurface failed" too, and
    a run that says that still HAS its main window.  Matching the call instead
    of the tail of the line would restart a perfectly good renderer."""
    log = ("[padglhost] window opened 1360x768 on DISPLAY=:0\n"
           "[padglhost] display 2: eglCreateWindowSurface failed 0x3003; its "
           "feed decodes but is not presented\n")
    facts = _reason(tmp_path, log)
    assert facts["REASON"] == ""
    assert facts["RC"] == "1"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_a_healthy_log_and_a_missing_one_both_answer_nothing(tmp_path):
    """The caller asks only after pad_window_line has said the word headless.
    One that asks anyway gets no answer rather than a guess, and a log the
    renderer never created is not an error."""
    facts = _reason(tmp_path, "[padglhost] window opened 1360x768\n")
    assert facts["REASON"] == "" and facts["RC"] == "1"
    assert facts["MISSING"] == "" and facts["MISSRC"] == "1"
    assert facts["NOARG"] == "" and facts["NOARGRC"] == "1"


# --------------------------------------------------------------------------
# The second chance itself, read out of watch.sh.
# --------------------------------------------------------------------------

def _retry_block():
    """The new block, from its own banner to the line that follows it."""
    text = src("watch.sh")
    start = text.index("A RENDERER THAT CAME UP WITH NO WINDOW")
    return text[start:text.index("grep -aE 'window opened", start)]


def test_the_no_window_retry_is_decided_before_the_verdict_is_printed():
    """Order, and it is the whole shape of the fix: the death gate first (a
    renderer that never started cannot be asked about its window), then this,
    then the verdict - which must describe the attempt the user actually got."""
    text = src("watch.sh")
    death = line_of(text, "if ! pad_gl_try; then")
    retry = line_of(text, "the renderer is UP BUT HAS NO WINDOW")
    verdict = line_of(text, 'GLWIN=$(pad_window_line "$HOSTLOG")')
    assert death < retry < verdict


def test_the_retry_fires_only_for_the_surface_reason():
    """pad_headless_reason is the gate.  Retrying the display case would be a
    second launch that fails in exactly the same way."""
    body = _retry_block()
    assert '"$(pad_headless_reason "$HOSTLOG")" = surface' in body


def test_the_retry_fires_only_from_the_gpu_attempt():
    """PAD_GL_SOFTWARE=1 already put this run in software, and a machine whose
    software renderer has no window has nothing left to try."""
    assert '[ "$PAD_GL_MODE" = gpu ]' in _retry_block()


def test_the_live_renderer_is_stopped_before_another_starts():
    """Unlike the death path, this one asks a LIVE padglhost to stand down:
    two of them would fight over one ring path."""
    body = _retry_block()
    assert line_of(body, "pad_gl_stop") < line_of(body, "pad_gl_software")
    assert line_of(body, "pad_gl_software") < line_of(body, "if pad_gl_try")


def test_stopping_the_renderer_is_sigint_first_and_waits():
    """SIGKILL would strand on the desktop exactly the ghost window this retry
    exists to remove: padglhost's shutdown destroys its X windows so WSLg's
    mirror sees them go, and that takes a moment it has to be given."""
    text = src("watch.sh")
    body = text[text.index("pad_gl_stop() {"):]
    body = body[:body.index("\n}\n")]
    assert line_of(body, "kill -INT") < line_of(body, "pgrep -x padglhost")
    assert line_of(body, "pgrep -x padglhost") < line_of(body, "kill -9")
    # And the pgid teardown would have killed is cleared, so a trap firing
    # after this cannot signal a process group that has been replaced.
    assert 'HOSTPG=""' in body


def test_the_failed_gpu_attempts_log_is_kept():
    """pad_gl_try truncates $HOSTLOG, and those lines are the only record of
    what the GPU path did - the same reason the death path keeps them."""
    body = _retry_block()
    assert 'cp -f "$HOSTLOG" "$HOSTLOG.gpu"' in body
    assert line_of(body, 'cp -f "$HOSTLOG" "$HOSTLOG.gpu"') < \
        line_of(body, "pad_gl_software")


def test_a_software_renderer_that_dies_gives_the_gpu_one_back():
    """The opposite trade from the death path's, because what is at stake is
    different: there the GPU renderer was already dead, here it was alive and
    serving a run with a game, sound and a playfield in it.  A run with no
    picture beats no run at all."""
    body = _retry_block()
    assert "did not start either" in body
    assert line_of(body, "did not start either") < line_of(body, "pad_gl_gpu")
    # ...and only then, with neither renderer starting, does the run end.
    assert line_of(body, "pad_gl_gpu") < line_of(body, "exit 1")


def test_going_back_to_the_gpu_names_the_driver_it_restores():
    """The software switch exported two variables; putting one back and
    leaving the other would run d3d12's name over llvmpipe's loader."""
    text = src("watch.sh")
    body = text[text.index("pad_gl_gpu() {"):]
    body = body[:body.index("\n}\n")]
    assert "GALLIUM_DRIVER=d3d12" in body
    assert "unset LIBGL_ALWAYS_SOFTWARE" in body
    assert "PAD_GL_MODE=gpu" in body
    # The log has to say so too, for the reason the software switch does: a run
    # whose log names a driver it did not use cannot be compared with any other.
    assert "cfg GALLIUM_DRIVER=d3d12" in body


def test_the_headless_verdict_names_the_button_as_well_as_the_command():
    """This text is read in the app's log pane far more often than in a
    terminal, and the pane has the cure two buttons away.  pad_renderer_advice
    already names both, in this order."""
    text = src("watch.sh")
    body = text[text.index("THE RENDERER HAS NO WINDOW"):]
    body = body[:body.index("\nesac")]
    assert "'Restart WSL...' on the Emulate tab" in body
    assert line_of(body, "Restart WSL") < line_of(body, "wsl --shutdown")


# --------------------------------------------------------------------------
# The window that could never be painted, read out of padglhost.c.
# --------------------------------------------------------------------------

def test_a_headless_fallback_takes_its_window_back_down():
    """win_open() maps the window BEFORE eglInitialize, so by the time the
    surface fails it is on the desktop and in the taskbar with the game's name
    on it.  Nothing will ever draw into it - every path from here is gated on
    win_on, which just went to 0 - and the reporter of this ticket photographed
    its empty taskbar preview and rebooted the machine.  It also made watch.sh's
    "THE RENDERER HAS NO WINDOW" verdict false on the one screen the user is
    actually looking at."""
    host = src("padglhost.c")
    start = host.index('"falling back to headless')
    body = host[start:host.index("eglCreatePbufferSurface", start)]
    assert "win_on = 0" in body
    assert "XUnmapWindow(xdpy, xwin)" in body
    # UNMAP and not destroy: the id stays valid for every guard that asks "is
    # this our window", and main()'s teardown destroys it with the others while
    # the X connection is still healthy - which is what WSLg's mirror needs.
    assert "XDestroyWindow" not in body
    # XSync and not XFlush: the point is the round trip, so the compositor has
    # seen the unmap before this process spends the next half second in Mesa.
    assert "XSync(xdpy, 0)" in body
    assert "XFlush(" not in body


def test_the_second_display_still_unmaps_its_own():
    """The main window now follows the rule item 44 wrote for display 2, and
    this pins that rule at its source: if display 2 is ever changed to destroy,
    the comment the main window's fix leans on stops being true."""
    host = src("padglhost.c")
    start = host.index('its feed decodes but is not presented')
    body = host[start:start + 900]
    assert "XUnmapWindow(xdpy, xwin2)" in body
