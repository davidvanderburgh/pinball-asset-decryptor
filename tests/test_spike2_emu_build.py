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

PURE TEXT, NO SHELL.  There is no bash on every machine this suite runs on, and
a test that needs a compiler is not a test anybody runs.  The behaviour itself -
missing builds, stale rebuilds, a live run blocking both - is proven by driving
``ensurebuild.sh`` against a synthetic rig, which needs a real filesystem with
real exec bits and so lives outside this file.
"""
import os
import re

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
