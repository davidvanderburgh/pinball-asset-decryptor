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

That was fixed by making the gate an identity test - and the identity test
compared the first EIGHT characters, so ``godzilla_le`` passed it.  A user's
Godzilla Premium 1.16 Heisei custom card (PAD-102) then produced exactly the
Bond failure again: ``loader_gate[0x7e1a10]=0``, ``event 93 has NO handlers``,
an ``[audio] pool`` whose words decode to the ASCII "date"/"Obje", and a run
that ended ``qemu: uncaught target signal 11 - core dumped`` mid-line instead
of the handler's own ``_exit(99)``.  godzilla_le is not a variant of
godzilla_pro; item 60's survey calls the pair the clearest example of two
different generations of the binary, and the two card images measure
0x8000..0x683bc0 (le 1.13.0) against 0x8000..0x6ed2c0 (pro 1.15.0) with the
event table at 0x7e4d48 falling off the end of the le image entirely.

So this pins the gate itself.  It compiles the REAL ``gz_addrs_ok()`` out of
hwshim.c - the text is extracted from the source, never copied here, the same
way tests/test_spike2_led_wide_twins.py does - and asks it about the titles
that matter.  Skipped where there is no C compiler, which is most Windows
checkouts; it runs in WSL and in CI, which is where the shim is built anyway.
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


def test_the_title_the_addresses_came_from_is_allowed(gate):
    assert _ask(gate, PAD_GAME="godzilla_pro")


@pytest.mark.parametrize("game", [
    "godzilla_le",          # PAD-102: the whole point - a DIFFERENT generation
    "godzilla",             # the bare family name names no binary
    "godzilla_pro_test",    # a longer name that starts with the right one
    "godzilla_p",           # a shorter one that is a prefix of it
    "james_bond_le",        # the title the gate was introduced for
    "led_zeppelin_le",
])
def test_every_other_title_is_refused(gate, game):
    assert not _ask(gate, PAD_GAME=game)


def test_no_title_at_all_is_refused(gate):
    assert not _ask(gate)


def test_the_operator_override_still_works_both_ways(gate):
    # An operator saying "these addresses are right for this title" is obeyed
    # even on a title the name test refuses, and PAD_GZ_ADDRS=0 is obeyed even
    # on the title it came from.  Both are the escape hatch PAD_SW_STRUCT gives.
    assert _ask(gate, PAD_GAME="godzilla_le", PAD_GZ_ADDRS="1")
    assert not _ask(gate, PAD_GAME="godzilla_pro", PAD_GZ_ADDRS="0")


def test_the_mapping_test_is_still_and_ed_in(gate):
    # Right title, addresses not mapped: still refused.  An address that is
    # right for the title and unmapped is unusable either way.
    assert not _ask(gate, PAD_GAME="godzilla_pro", PAD_TEST_SW_STRUCT="0")


def test_the_gate_reads_the_whole_name(gate):
    """Belt and braces on the source itself: the bug this file exists for was a
    character-by-character compare that stopped after eight of them, which no
    single behavioural case can rule back in on its own."""
    src = open(SHIM, encoding="utf-8", errors="replace").read()
    body = _extract("gz_addrs_ok")
    assert "godzilla_pro" in body, "the gate no longer names the title"
    assert "g[7]" not in body, "the eight-character prefix compare is back"
    assert src.count("gz_addrs_ok(") >= 4, \
        "a caller stopped going through the gate"


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
