"""The rig builds what it runs, and builds it from the sources it says.

WHAT THIS IS GUARDING.  Three binaries are compiled by the rig - the ARM
hardware shim and the GL bridge's two halves - and each of them has now failed
in the same way, twice in two releases:

* the shim was PRESENT BUT OLD.  An app update delivered new ``hwshim.c`` while
  the ``.so`` that ran stayed whatever was built months ago.
* the renderer was ABSENT ENTIRELY, and the user saw
  ``env: './padglhost': No such file or directory`` ten seconds after Start
  said "Starting...".

``ensurebuild.sh`` answers both, from source lists in ``padpath.sh``.  The
failure mode THAT has is the one ``build.sh`` already records in its own
comment: ``alsastub.c`` was on the compile line and missing from the copy list,
so an edit was silently never built AND THE BUILD STILL SAID "built ok".  These
tests are the coupling - a source on a list but not on a compile line, or the
reverse, is caught here and not one full run later.

PURE TEXT, NO SHELL, WITH ONE EXCEPTION AT THE BOTTOM.  There is no bash on
every machine this suite runs on, and a test that needs a compiler is not a test
anybody runs.  The behaviour itself - missing builds, stale rebuilds, a live run
blocking both - is proven by driving ``ensurebuild.sh`` against a synthetic rig,
which needs a real filesystem with real exec bits and so lives outside this file.

The exception is how a FAILED build is reported, which is a text-shaping
question and needs no compiler at all - a script that prints an error and exits
non-zero is enough, and the assertion is worth far more run against the real
function than pattern-matched against its source.  It skips where bash is not.
"""
import os
import re
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as fh:
        return fh.read()


def _srcs(var):
    """One of padpath.sh's source lists, as the shell would split it."""
    m = re.search(r'^%s="([^"]*)"' % var, _read("padpath.sh"), re.M)
    assert m, "%s is not defined in padpath.sh" % var
    return m.group(1).split()


LISTS = ["PAD_SHIM_SRCS", "PAD_GLHOST_SRCS", "PAD_GLGUEST_SRCS"]


@pytest.mark.parametrize("var", LISTS)
def test_every_named_source_exists(var):
    """A list naming a file that is not there fails the build, and the build
    is now something a user's first start runs."""
    for src in _srcs(var):
        assert os.path.isfile(os.path.join(RIG, src)), "%s: %s" % (var, src)


@pytest.mark.parametrize("var,script", [
    ("PAD_SHIM_SRCS", "build.sh"),
    ("PAD_GLHOST_SRCS", "buildbridge.sh"),
    ("PAD_GLGUEST_SRCS", "buildbridge.sh"),
])
def test_every_named_c_file_is_compiled(var, script):
    """The alsastub.c lesson, as a test.  Headers are pulled in by the
    compiler; a ``.c`` has to reach a command line or it is not built.

    TWO WAYS TO SATISFY THIS, and both are honest.  ``build.sh`` expands the
    list itself and so cannot drift by construction; ``buildbridge.sh`` names
    its sources, because the two halves go to different compilers.  What is not
    allowed is a source on the list that neither builder ever sees.
    """
    text = _read(script)
    if "$" + var in text:
        return
    for src in _srcs(var):
        if src.endswith(".c"):
            assert src in text, "%s names %s and %s never compiles it" % (
                var, src, script)


def test_the_protocol_header_is_on_both_bridge_lists():
    """padgl.h IS the wire between padglhost and the guest encoder, so a change
    to it has to make both halves stale.  On one list only, the two would be
    allowed to drift into reading the same ring different ways."""
    assert "padgl.h" in _srcs("PAD_GLHOST_SRCS")
    assert "padgl.h" in _srcs("PAD_GLGUEST_SRCS")


def test_each_half_of_the_bridge_can_be_built_alone():
    """A box with a native gcc and no cross compiler must still get its
    renderer.  Building both under ``set -e``, ARM first, is what left
    ``padglhost`` unbuilt on a machine perfectly able to build it."""
    text = _read("buildbridge.sh")
    assert "--host" in text and "--guest" in text


def test_a_successful_build_records_what_it_compiled():
    """The stamp is the whole input to the rebuild decision.  No stamp means
    timestamps, which answer differently depending on which copy of the rig you
    installed last."""
    assert "pad_shim_hash" in _read("build.sh")
    bridge = _read("buildbridge.sh")
    assert "pad_glhost_hash" in bridge
    assert "pad_glguest_hash" in bridge


@pytest.mark.parametrize("script", ["watch.sh", "runbridge.sh"])
def test_the_run_scripts_check_before_they_start_anything(script):
    """Both entry points, not just the one the app happens to call."""
    text = _read(script)
    assert "ensurebuild.sh" in text
    assert "pad_ensure_shim" in text
    assert "pad_ensure_bridge" in text


@pytest.mark.parametrize("script", ["watch.sh", "runbridge.sh"])
def test_the_renderer_is_launched_by_its_resolved_path(script):
    """``./padglhost`` with a ``cd $HOME`` above it is what turned "not built"
    into a bare ``env:`` message naming a relative path the user could not
    place.

    CODE ONLY.  Both scripts quote that exact error in a comment, because the
    comment is why they check at all - and a lint that cannot tell prose from a
    command line would make the explanation illegal to write down.
    """
    body = "\n".join(ln for ln in _read(script).splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "./padglhost" not in body
    assert "$PAD_GLHOST_BIN" in body


# --------------------------------------------------------------------------
# ...and when the build DOES fail, what the user is shown has to be the reason
#
# Reported 2026-08-07, Star Wars LE on a fresh WSL install: "build FAILED, and
# the game has no hardware without it", above it eight lines of
# -Wformat-truncation notes about gstvid.c:476.  Every one of those lines is a
# warning about code that compiles perfectly, and all eight are byte for byte
# the tail of a SUCCESSFUL build on this machine.
#
# The cause was three `implicit declaration of function` errors in hwshim.c,
# which GCC 13 warns about and GCC 14 REJECTS - so the shim did not build on any
# distro newer than the one the rig is developed on, and could not be made to
# fail on the machine that could fix it.  Neither half of that was visible: the
# report showed the tail, and gcc compiles every translation unit before giving
# up, so the tail belongs to whichever source came last and never to the one
# that broke.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("script", ["build.sh", "buildbridge.sh"])
def test_an_old_compiler_is_asked_for_a_new_compiler_s_answer(script):
    """The flag is the whole fix for the class.  Without it these sources
    compile here and fail on a user's machine, which is the one shape of build
    fault that cannot be reproduced where it can be repaired."""
    text = _read(script)
    assert "-Werror=implicit-function-declaration" in text, script


def test_the_bridge_pins_it_for_both_halves():
    """Guest and host are different compilers on the user's machine, and both
    of them are theirs, not ours."""
    text = _read("buildbridge.sh")
    # Once in the shared ARM CFLAGS, once on the native padglhost line.
    assert text.count("-Werror=implicit-function-declaration") >= 2


def test_a_failed_build_is_reported_by_its_errors_not_by_its_last_lines():
    """``tail -8`` is what showed a user eight lines of harmless warning notes
    and hid the three errors that stopped the build."""
    eb = _read("ensurebuild.sh")
    body = eb[eb.index("_pad_build() {"):]
    body = body[:body.index("\n}")]
    assert "error:" in body, "the errors have to be selected FOR"
    assert "undefined reference" in body, "ld's own failures do not say error:"
    # The tail survives only as the fallback for a failure none of the words
    # match; it must not be the only thing that is ever printed.
    assert "tail -8" in body
    assert body.index("grep -E") < body.index("tail -8")


def test_a_failed_build_keeps_its_full_output_somewhere_nameable():
    """Whatever the next fault is, this pattern will not know its words - and a
    user who can send the file is a user whose problem can be read."""
    eb = _read("ensurebuild.sh")
    body = eb[eb.index("_pad_build() {"):]
    body = body[:body.index("\n}")]
    assert "TMPDIR" in body, "somewhere writable on every platform"
    assert "full build output" in body, "and NAMED, or it may as well not exist"


# ---- the one shell-driven test in this file (see the module docstring) -----

BASH = shutil.which("bash")

_FAKE_BUILD = """#!/bin/bash
echo "hwshim.c:5276:10: error: implicit declaration of function 'open'"
echo "hwshim.c:5279:5: error: implicit declaration of function 'close'"
for i in $(seq 1 20); do
    echo "gstvid.c:476:22: warning: noise $i [-Wformat-truncation=]"
done
exit 1
"""

_FAKE_ODD = """#!/bin/bash
for i in $(seq 1 20); do echo "something nobody predicted $i"; done
exit 1
"""


#: EVERYTHING RELATIVE, AND THE SCRIPT ON DISK RATHER THAN ON THE COMMAND LINE.
#: On Windows ``bash`` is as likely to be WSL's launcher as Git's - and that one
#: takes the ``-c`` string, drops the positional arguments after it, and sees a
#: ``C:\...`` path as a name with no directories in it.  A driver file run from
#: its own directory says the same thing to both, and to a Linux CI runner.
_DRIVER = """#!/bin/bash
RIG=$(pwd); export RIG
TMPDIR=$RIG; export TMPDIR
. "$RIG/ensurebuild.sh"
_pad_build fake.sh
"""


def _drive(tmp_path, script_body):
    """Run _pad_build against a synthetic build script and return what a user
    would have seen.  ensurebuild.sh is SOURCED, exactly as watch.sh sources
    it, so this is the real function and not a copy of it."""
    rig = tmp_path / "rig"
    rig.mkdir()
    shutil.copy(os.path.join(RIG, "ensurebuild.sh"), str(rig / "ensurebuild.sh"))
    for name, body in (("fake.sh", script_body), ("driver.sh", _DRIVER)):
        with open(str(rig / name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    out = subprocess.run([BASH, "driver.sh"], cwd=str(rig),
                         capture_output=True, text=True)
    assert out.returncode != 0, "a failed build must stay failed: %r" % (
        out.stdout + out.stderr)
    return out.stdout + out.stderr


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_the_error_survives_twenty_lines_of_warnings_after_it(tmp_path):
    """The reported shape exactly: errors first, noise after, and the noise
    longer than anything a tail can see past."""
    seen = _drive(tmp_path, _FAKE_BUILD)
    assert "implicit declaration of function 'open'" in seen
    assert "implicit declaration of function 'close'" in seen
    assert "noise 20" not in seen, "the tail is not what is worth showing"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_failure_with_no_recognisable_words_still_says_something(tmp_path):
    """The fallback matters more than the pattern does: an unmatched failure
    must not report NOTHING, which is strictly worse than the tail was."""
    seen = _drive(tmp_path, _FAKE_ODD)
    assert "something nobody predicted 20" in seen


# --------------------------------------------------------------------------
# ...and BEFORE any of that, whether this machine can compile at all.
#
# Reported 2026-08-08: the ARM cross compiler was there, the shim built and
# said "built ok: 154684 bytes", and the very next line was
#
#     [build] the GL renderer is not built, and there is no gcc here to build
#     [build] it. It is a NATIVE binary - install gcc ...
#
# Two compilers, and having one says nothing about having the other.  The
# guard was `command -v gcc`, which is also wrong in the other direction: gcc
# only RECOMMENDS libc6-dev, so a slim WSL has the compiler on PATH with no
# headers to give it, and padglhost.c opens with #include <stdio.h>.
#
# NEEDS NO COMPILER TO TEST, which is the point of doing it here: a `gcc` on
# PATH that exits non-zero is exactly the machine that a PATH lookup clears
# and a compile does not.
# --------------------------------------------------------------------------

#: ``$RIG/bin`` FIRST, so the stand-in gcc is the one that answers.  The empty
#: case replaces PATH outright rather than prepending: this suite runs on
#: Linux CI too, where a real gcc is sitting on the inherited PATH and would
#: quietly turn "no compiler here" into a test of the machine instead of of the
#: probe.  Nothing external is needed to reach the verdict in that case - the
#: `command -v` guard returns before mktemp is ever called.
_CC_DRIVER = """#!/bin/bash
RIG=$(pwd); export RIG
PATH=%s; export PATH
TMPDIR=$RIG/tmp; export TMPDIR
. "$RIG/ensurebuild.sh"
_pad_cc_works && echo VERDICT=yes || echo VERDICT=no
"""


def _cc_verdict(tmp_path, gcc_body):
    """Run the real _pad_cc_works with a stand-in gcc first on PATH.

    ``gcc_body=None`` means a machine with no compiler at all."""
    rig = tmp_path / "rig"
    (rig / "bin").mkdir(parents=True)
    (rig / "tmp").mkdir()
    shutil.copy(os.path.join(RIG, "ensurebuild.sh"), str(rig / "ensurebuild.sh"))
    path = "$RIG/bin:$PATH" if gcc_body is not None else "$RIG/bin"
    files = [(rig / "driver.sh", _CC_DRIVER % path)]
    if gcc_body is not None:
        files.append((rig / "bin" / "gcc", gcc_body))
    for path_, body in files:
        with open(str(path_), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        os.chmod(str(path_), 0o755)
    out = subprocess.run([BASH, "driver.sh"], cwd=str(rig),
                         capture_output=True, text=True)
    return out.stdout + out.stderr


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_compiler_that_cannot_compile_is_not_a_compiler(tmp_path):
    """On PATH and unusable - the gcc-without-libc6-dev machine.  A PATH lookup
    says yes to this one and the build then fails on the first #include."""
    seen = _cc_verdict(tmp_path, "#!/bin/sh\n"
                                 "echo 'stdio.h: No such file' >&2\nexit 1\n")
    assert "VERDICT=no" in seen, seen


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_a_compiler_that_compiles_is_believed(tmp_path):
    """...and the probe must not be so strict that it condemns a good box: a
    gcc that does its job is a yes, with no real toolchain needed to show it."""
    seen = _cc_verdict(tmp_path, "#!/bin/sh\nexit 0\n")
    assert "VERDICT=yes" in seen, seen


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_the_probe_actually_hands_gcc_a_source_file(tmp_path):
    """The one thing a stub cannot fake for us: it must be a COMPILE.  A probe
    that ran `gcc --version` would pass both tests above and still clear a
    machine with no headers, so the arguments are what is checked.

    Written to a FILE, not printed: the probe sends the compiler's own output
    to /dev/null, which is right - a build error belongs in the build's report,
    not in a yes/no answer - and means stdout cannot be read from here."""
    seen = _cc_verdict(tmp_path, '#!/bin/sh\nprintf "%s" "$*" > "$RIG/args"\n'
                                 'exit 0\n')
    assert "VERDICT=yes" in seen, seen
    args = (tmp_path / "rig" / "args").read_text(encoding="utf-8")
    assert args.rstrip().endswith(".c"), (
        "the probe must compile a source file, not interrogate the binary: %r"
        % args)
    src = tmp_path / "rig" / "tmp"
    assert not any(src.iterdir()), "and clean up after itself"


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_no_compiler_at_all_is_a_no(tmp_path):
    """The fault as it was actually reported: no gcc on the machine."""
    seen = _cc_verdict(tmp_path, None)
    assert "VERDICT=no" in seen, seen


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_the_probe_leaves_nothing_behind(tmp_path):
    """It runs on every setupcheck, which is every time the tab opens - so a
    probe that littered would leave a directory per visit in /tmp."""
    seen = _cc_verdict(tmp_path, "#!/bin/sh\nexit 0\n")
    assert "VERDICT=yes" in seen, seen
    assert os.listdir(str(tmp_path / "rig" / "tmp")) == []


@pytest.mark.skipif(BASH is None, reason="no bash on this machine")
def test_the_whole_output_is_written_where_it_says_it_is(tmp_path):
    """Named in the log, and actually there - including the twenty lines the
    report deliberately left out."""
    seen = _drive(tmp_path, _FAKE_BUILD)
    m = re.search(r"full build output: (\S+)", seen)
    assert m, seen
    # The name is read back from the report, but opened from this side of the
    # fence: _drive puts TMPDIR in the rig, so whatever shell wrote it, the
    # basename lands where Python can find it.
    with open(str(tmp_path / "rig" / os.path.basename(m.group(1))),
              encoding="utf-8") as fh:
        full = fh.read()
    assert "implicit declaration of function 'open'" in full
    assert "noise 20" in full
