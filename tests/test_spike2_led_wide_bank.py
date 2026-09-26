"""The swelf lamp grammar's BANK form (item 165): hwshim.c's led_wide_strip_bank and leddecode.wide_bank.

A board with more than 96 lamps takes them in banks of 96. Stranger Things LE 1.12's topper (node
12, 72 RGB pixels, 216 channels) spoke eight commands in a traced game and the shim refused every
one: their B field reads 0x10, which the builder's path B (batman 0x518b78, Stranger Things
0x4ece40) uses as a marker, moving the real B into a prefix byte with the bank above it. Every
frame here is real - the shim's `[nbcmd] <cmd> first frame <hex>` lines of that run - and every one
closes exactly once the prefix is read as bank << 5 | B.

The C side compiles the shim's own functions out of hwshim.c (skipped without a compiler).
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
sys.path.insert(0, RIG)
import leddecode  # noqa: E402

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

#: Stranger Things LE 1.12, node 12, 2026-09-26: (bank, lamps, levels)
FRAMES = {
    "91_one_on": ("8c04912400bb00", 1, [0], [0xFF]),
    "90_one_off": ("8c04902400bc00", 1, [0], [0x00]),
    # the long index-bitmap body with no group sent: every lamp of the bank is the fill, all off
    "b0_bank_off": ("8c06b024c00b00cf00", 1, list(range(96)), [0x00] * 96),
    # one level byte per lamp (A == 2), then the channel-B base byte the prefix's B (0x14) carries
    "b2_bank_levels": ("8c67b234c00b00" + "0000ff" * 32 + "3c4000", 1, list(range(96)), [0x00, 0x00, 0xFF] * 32),
    "92_three_groups": ("8c209254c002ffff" + "00ff00" * 8 + "3c7a00", 2, list(range(24)), [0x00, 0xFF, 0x00] * 8),
    # the short index list, all on (A == 1 spends no level byte)
    "b1_list_on": ("8c07b14402080e94cc00", 2, [2, 8, 14, 20], [0xFF] * 4),
    # one level shared by the whole bank (A == 3)
    "b3_bank_dim": ("8c08b334c00b000a8c2400", 1, list(range(96)), [0x0A] * 96),
    "93_groups_dim": ("8c099354c002ffff0a8c2e00", 2, list(range(24)), [0x0A] * 24),
}


@pytest.mark.parametrize("name", sorted(FRAMES))
def test_the_python_twin_reads_the_bank_form(name):
    h, bank, idxs, vals = FRAMES[name]
    b = bytes.fromhex(h)
    assert leddecode.wide_decode(b) is None, "the plain walk must still refuse the marker"
    assert leddecode.wide_decode_any(b) == (bank, idxs, vals)


def test_a_frame_without_the_marker_is_bank_zero_and_unchanged():
    b = bytes.fromhex("8905b527ac02e800")            # batman's b5: lamps 39 and 44 on
    assert leddecode.wide_bank(b) == (0, b)
    assert leddecode.wide_decode_any(b) == (0, [39, 44], [0xFF, 0xFF])


def test_a_malformed_prefix_is_refused():
    assert leddecode.wide_bank(bytes.fromhex("8c04912500bb00")) is None      # low bits set
    assert leddecode.wide_bank(bytes.fromhex("8c039100bb00")) is None        # nothing after the prefix


def _extract(name):
    src = open(SHIM, encoding="utf-8", errors="replace").read()
    m = re.search(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M)
    assert m, "%s not found in hwshim.c" % name
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
@FUNCS@
int main(int argc, char **argv)
{
    unsigned char raw[512], idx[96], val[96];
    const unsigned char *body;
    unsigned cmd, blen, cnt = 0, i;
    int n = 0, bank;
    const char *h = argv[1];
    while (h[0] && h[1] && n < 512) { char t[3] = { h[0], h[1], 0 }; raw[n++] = (unsigned char)strtoul(t, 0, 16); h += 2; }
    cmd = raw[2]; body = raw + 3; blen = (unsigned)n - 5;
    bank = led_wide_strip_bank(&cmd, &body, &blen);
    if (bank < 0 || !led_wide_walk(body, blen, cmd, idx, val, &cnt)) { printf("REFUSED\n"); return 0; }
    printf("%d", bank);
    for (i = 0; i < cnt; i++) printf(" %u:%u", idx[i], val[i]);
    printf("\n");
    return 0;
}
"""


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    if not os.path.isfile(SHIM):
        pytest.skip("rig not present")
    if not CC:
        pytest.skip("no C compiler on this host")
    funcs = "\n".join(_extract(n) for n in ("popcount8", "led_wide_long", "led_wide_walk", "led_wide_strip_bank"))
    d = tmp_path_factory.mktemp("ledbank")
    (d / "h.c").write_text(HARNESS.replace("@FUNCS@", funcs), encoding="utf-8")
    exe = d / ("h.exe" if os.name == "nt" else "h")
    r = subprocess.run([CC, "-O1", "-o", str(exe), str(d / "h.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(exe)


@pytest.mark.parametrize("name", sorted(FRAMES))
def test_the_shim_strips_the_prefix_and_walks_the_rest_like_the_twin(cbin, name):
    h, bank, idxs, vals = FRAMES[name]
    r = subprocess.run([cbin, h], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = r.stdout.split()
    assert out and out[0] != "REFUSED", "the shim refused %s" % name
    assert int(out[0]) == bank
    pairs = [p.split(":") for p in out[1:]]
    assert [int(a) for a, _ in pairs] == idxs
    assert [int(b) for _, b in pairs] == vals
