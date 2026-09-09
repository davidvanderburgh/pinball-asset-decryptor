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


def _drive(tmp_path, hostlog):
    """Ask the real shell functions what this renderer log means."""
    rig = tmp_path / ("rig%d" % len(list(tmp_path.glob("rig*"))))
    rig.mkdir(parents=True)
    shutil.copy(os.path.join(RIG, "padpath.sh"), str(rig / "padpath.sh"))
    for name, text in (("hostlog", hostlog), ("driver.sh", _DRIVER)):
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
