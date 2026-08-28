"""hwshim.c's led_wide_walk and leddecode.wide_decode must stay twins.

The rig has two implementations of this grammar on purpose - the C one runs
inside the emulated game and is the only one that can see the wire, the Python
one runs at the desk and is the only one anybody can read a capture with - and
padled.h has said "if one changes, change both" about its decoders since
version 1. Nothing has ever CHECKED that, and a decoder that drifts is worse
than one that is missing: the desk tool then explains a picture the rig is not
drawing.

So this compiles the REAL C out of hwshim.c - the function text is extracted
from the source file, never copied into this test - and runs both sides over
the same frames. A change to either one that is not made to the other fails
here with the frame that separates them.

Skipped where there is no C compiler, which is most Windows checkouts; it runs
in WSL and anywhere with cc/gcc, which is where the shim is built anyway.
"""
import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
SHIM = os.path.join(RIG, "hwshim.c")

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present"),
    pytest.mark.skipif(not CC, reason="no C compiler on this host"),
]

sys.path.insert(0, RIG)


def _extract(name):
    """The source text of one static function, straight out of hwshim.c.

    Brace-counted rather than regexed to the closing brace: the function body
    contains braces, and a lazy match would stop at the first one.
    """
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
#include <string.h>

%s

%s

int main(int argc, char **argv)
{
    unsigned char body[512], idx[96], val[96];
    unsigned cmd, blen, n = 0, i;
    int len = 0;
    const char *h;
    cmd = (unsigned)strtoul(argv[1], 0, 16);
    h = argv[2];
    while (h[0] && h[1] && len < 512) {
        char t[3]; t[0] = h[0]; t[1] = h[1]; t[2] = 0;
        body[len++] = (unsigned char)strtoul(t, 0, 16);
        h += 2;
    }
    blen = (unsigned)len;
    if (!led_wide_walk(body, blen, cmd, idx, val, &n)) {
        printf("REFUSED\n");
        return 0;
    }
    for (i = 0; i < n; i++) printf("%%u:%%u ", idx[i], val[i]);
    printf("\n");
    return 0;
}
"""


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    d = tmp_path_factory.mktemp("ledwide")
    src = d / "twin.c"
    src.write_text(HARNESS % (_extract("popcount8"), _extract("led_wide_walk")),
                   encoding="utf-8")
    exe = d / ("twin.exe" if os.name == "nt" else "twin")
    r = subprocess.run([CC, "-O1", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's own decoder did not compile:\n" + r.stderr
    return str(exe)


def _c_side(cbin, cmd, body):
    r = subprocess.run([cbin, "%02x" % cmd, body.hex()],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout.strip()
    if out == "REFUSED":
        return None
    pairs = [p.split(":") for p in out.split()]
    return [int(a) for a, _ in pairs], [int(b) for _, b in pairs]


def _py_side(cmd, body):
    import leddecode
    # wide_decode takes a whole frame; rebuild one around this body so the two
    # sides are fed the same bytes through each one's real entry point.
    frame = bytes([0x80, len(body) + 2, cmd]) + body + bytes([0, 0])
    frame = frame[:-2] + bytes([(-sum(frame[:-2])) & 0xFF, 0])
    return leddecode.wide_decode(frame)


def _frames():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_spike2_led_wide import FRAMES
    return FRAMES


@pytest.mark.parametrize("cmd", sorted(_frames()))
def test_c_and_python_agree_on_real_frames(cbin, cmd):
    body = bytes.fromhex(_frames()[cmd])[3:-2]
    c = _c_side(cbin, cmd, body)
    p = _py_side(cmd, body)
    if p is None:
        assert c is None, "cmd %02x: C decoded a frame Python refused" % cmd
        return
    assert c is not None, "cmd %02x: Python decoded a frame C refused" % cmd
    assert c[0] == p[0], "cmd %02x: the two sides address different lamps" % cmd
    assert c[1] == p[1], "cmd %02x: the two sides give different levels" % cmd


def test_c_and_python_agree_on_mutations(cbin):
    """The interesting frames are the ones the grammar has to REFUSE.

    Every real frame decodes, so agreeing on those only proves the two happy
    paths match. Flipping bytes drives both sides into their refusal branches,
    which is where an off-by-one in one twin and not the other actually lives.
    """
    frames = _frames()
    base = bytes.fromhex(frames[0x8A])[3:-2]
    checked = 0
    for cmd in (0x8A, 0x8E, 0x96, 0x9A, 0x9E, 0xA6, 0xB4):
        body = bytes.fromhex(frames[cmd])[3:-2]
        for pos in range(min(len(body), 8)):
            for bit in (0x01, 0x40, 0x80):
                m = bytearray(body)
                m[pos] ^= bit
                m = bytes(m)
                c, p = _c_side(cbin, cmd, m), _py_side(cmd, m)
                checked += 1
                if p is None:
                    assert c is None, (
                        "cmd %02x body %s: C decoded, Python refused"
                        % (cmd, m.hex()))
                else:
                    assert c is not None, (
                        "cmd %02x body %s: Python decoded, C refused"
                        % (cmd, m.hex()))
                    assert c[0] == p[0] and c[1] == p[1], (
                        "cmd %02x body %s: twins disagree" % (cmd, m.hex()))
    assert checked > 100, "the mutation sweep did not actually run"
    assert base  # keeps the corpus reference honest if 0x8a is ever removed
