"""The crash reporter's Godzilla addresses belong to ONE title, and the gate
that decides when to use them has now been too wide twice.

Everything hwshim.c's SEGV handler prints below the registers - the loader
gate, the event table, the whole mixer and queue-pool dump - is read from
addresses reverse-engineered out of godzilla_pro 1.15.0 and hard-coded.  Used
on any other binary they are somebody else's data, and the failure is not a
crash, it is a REPORT THAT INVENTS FINDINGS: james_bond_le got
``event 93 handler[0] = 0x20474f4c`` (the ASCII "LOG ") stated as fact, then
the handler followed one of its own invented pointers and faulted a second
time, which killed the process before the title-agnostic half of the report
had printed anything.

TWO PASSES TRIED TO FIX THAT WITH A TITLE TEST, AND BOTH WERE WRONG.  The
first compared the first EIGHT characters of ``PAD_GAME``, so ``godzilla_le``
passed a test meant for ``godzilla_pro``; a user's Godzilla Premium 1.16 Heisei
card (PAD-102) then produced the Bond failure again - ``loader_gate=0``,
``event 93 has NO handlers``, an ``[audio] pool`` decoding to ASCII "date", and
a run ending ``qemu: uncaught target signal 11`` mid-line instead of the
handler's own ``_exit(99)``.  The obvious repair, matching the WHOLE name, is
wrong too, just one firmware version later: these addresses came out of
godzilla_pro **1.15.0**, and the day Stern ships godzilla_pro 1.16 the name
matches, the addresses do not, and nothing in the log says so.  A name is not a
build, and there is no fingerprint that survives a rebuild either.

So the gate names no title at all: ``PAD_GZ_ADDRS=1`` - an operator asserting
the addresses fit what they are running - and nothing else.  This pins that.
It compiles the REAL ``gz_addrs_ok()`` out of hwshim.c (the text is extracted
from the source, never copied here, the same way
tests/test_spike2_led_wide_twins.py does), checks that no title opens it -
including the one the addresses came from - and greps the function so a third
title test cannot quietly arrive.  Skipped where there is no C compiler, which
is most Windows checkouts; it runs in WSL and in CI, which is where the shim is
built anyway.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
SHIM = os.path.join(RIG, "hwshim.c")

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present"),
    pytest.mark.skipif(not CC, reason="no C compiler on this host"),
]


def _extract(name):
    """The source text of one static function, straight out of hwshim.c."""
    src = open(SHIM, encoding="utf-8", errors="replace").read()
    m = re.search(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M)
    assert m, "%s not found in hwshim.c - did it get renamed?" % name
    i = src.index("{", m.start())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>

/* The mapping half of the gate, stubbed: in the shim this returns the switch
 * struct's address when 0x7a958c is mapped and 0 when it is not, and the gate
 * ANDs it in so an address that is right for the title but unmapped is still
 * refused.  PAD_TEST_SW_STRUCT=0 plays "not mapped". */
static unsigned a_sw_struct(void)
{
    const char *e = getenv("PAD_TEST_SW_STRUCT");
    return (e && e[0] == '0') ? 0u : 0x7a958cu;
}

%s

int main(void)
{
    printf("%%d\n", gz_addrs_ok());
    return 0;
}
"""


@pytest.fixture(scope="module")
def gate(tmp_path_factory):
    d = tmp_path_factory.mktemp("gzgate")
    src = d / "gate.c"
    src.write_text(HARNESS % _extract("gz_addrs_ok"), encoding="utf-8")
    exe = d / ("gate.exe" if os.name == "nt" else "gate")
    r = subprocess.run([CC, "-O1", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's own gate did not compile:\n" + r.stderr
    return str(exe)


def _ask(gate, **env):
    e = dict(os.environ)
    for k in ("PAD_GAME", "PAD_GZ_ADDRS", "PAD_TEST_SW_STRUCT"):
        e.pop(k, None)
    for k, v in env.items():
        if v is not None:
            e[k] = v
    r = subprocess.run([gate], capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip() == "1"


@pytest.mark.parametrize("game", [
    "godzilla_pro",         # the very title the addresses were read out of
    "godzilla_le",          # PAD-102: a different generation of the binary
    "godzilla",
    "godzilla_pro_test",
    "james_bond_le",
    "led_zeppelin_le",
])
def test_no_title_name_opens_the_gate(gate, game):
    """THE RULE: no hard-coded logic for a specific game and version. Not even
    godzilla_pro opens this on its name - see the header for why matching the
    whole name is still wrong, just one firmware version later."""
    assert not _ask(gate, PAD_GAME=game)


def test_no_title_at_all_is_refused(gate):
    assert not _ask(gate)


def test_only_an_operator_opens_it(gate):
    # PAD_GZ_ADDRS=1 is an operator saying "I have checked these fit what I am
    # running". It is the only thing that does, on any title.
    assert _ask(gate, PAD_GZ_ADDRS="1")
    assert _ask(gate, PAD_GAME="anything_at_all", PAD_GZ_ADDRS="1")
    assert not _ask(gate, PAD_GAME="godzilla_pro", PAD_GZ_ADDRS="0")


def test_the_mapping_test_is_still_and_ed_in(gate):
    # Asserted by the operator, addresses not mapped: still refused. An address
    # that is right for the build and unmapped is unusable either way.
    assert not _ask(gate, PAD_GZ_ADDRS="1", PAD_TEST_SW_STRUCT="0")


def test_the_gate_names_no_title_in_its_source(gate):
    """Belt and braces on the source itself. Two passes put a title test in
    here - an eight-character prefix, then the whole name - and both were
    wrong. A grep is the only thing that keeps a third from arriving."""
    src = open(SHIM, encoding="utf-8", errors="replace").read()
    body = _extract("gz_addrs_ok")
    assert "godzilla" not in body, "a title name is back in the gate"
    assert "PAD_GAME" not in body, "the gate is reading the title again"
    assert "PAD_GZ_ADDRS" in body, "the operator's escape hatch went missing"
    assert src.count("gz_addrs_ok(") >= 4, "a caller stopped going through the gate"


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
