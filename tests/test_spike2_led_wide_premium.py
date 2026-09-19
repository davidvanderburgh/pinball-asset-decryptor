"""Godzilla Premium 1.16's insert boards speak the wide lamp grammar (item mode-leds).

The rig's per-title dialect vote refused the grammar for godzilla (its strip boards do
not speak it), so Premium 1.16's playfield inserts were never decoded and the virtual
playfield showed neither the game's in-play inserts nor a mode's. Two things fix it:

- the LONG index-bitmap body (a window of more than 8 groups: M set and a third header
  byte, or no M when every group from 4 on is sent), read off the game's own builder,
  in hwshim.c's led_wide_walk and its twin leddecode.wide_decode;
- a per-BOARD vote (hwshim.c led_node_wide_publish): a board that proves the grammar
  with its own multi-lamp frames is read by it; the others are read as before.

The frames here are real, from a traced Premium 1.16 game (item mode-leds RUN 5). The
C parts compile the shim's own functions out of hwshim.c (skipped without a compiler).
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leddecode  # noqa: E402

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

#: real node-9 frames of a Premium 1.16 game, and what they carry
PREMIUM = {
    # M + bitmap: groups 2..10, header bits 0-1 and third byte 0xfc (groups 6-8) sent, fill 0
    "long_M_ba": ("8914ba832afca00140c001400000ff007b003a030a5d00",
                  [21, 23, 24, 70, 78, 79, 80], [0, 0, 255, 0, 123, 0, 58]),
    "long_M_a2": ("891ca28309ec0128a80340003f1f073f0007073a081004001008001003fa00",
                  [0, 11, 13, 51, 53, 55, 56, 57, 78], [0, 63, 31, 7, 63, 0, 7, 7, 58]),
    # no M, groups 1..10: every group from 4 on sent, so the third byte was dropped
    "long_noM_86": ("8930868f1a430eac1f144090b9755500007f00000000000000000000000000007f007f7f"
                    "000000000000000000000000009900",
                    [8, 9, 14, 17, 18, 19, 26, 27, 29, 31, 32, 33, 34, 35, 36, 42, 44, 54, 60, 63, 64,
                     67, 68, 69, 71, 72, 74, 76, 77, 78, 80, 82, 84, 86],
                    [0, 0, 127, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 127, 0, 127, 127, 0, 0, 0, 0,
                     0, 0, 0, 0, 0, 0, 0, 0, 0]),
    # fill 0xff: window group 1 not sent, so it is all ones
    "long_fill_ff": ("892686cd1a241c8880700e0401807f7f007f7f7f7f00007f7f7f007f00007f0000007f7f007f00a700",
                     [10, 13, 16, 17, 18, 19, 20, 21, 22, 23, 26, 27, 28, 35, 39, 47, 52, 53, 54, 57, 58,
                      59, 66, 72, 87],
                     [127, 127, 0, 127, 127, 127, 127, 0, 0, 127, 127, 127, 0, 127, 0, 0, 127, 0, 0, 0,
                      127, 127, 0, 127, 0]),
    # a mode's BUILDING-B pulse (lamp 78) commanded at 0xd3 with its fade 3: A=3, one fade byte
    "single_97": ("8905974ed303b700", [78], [0xD3]),
    # the same lamp at the pulse's top: A=1 spends no level byte
    "single_95": ("8904954e038d00", [78], [0xFF]),
}


@pytest.mark.parametrize("name", sorted(PREMIUM))
def test_premium_frames_decode_to_what_the_builder_sent(name):
    hexs, idxs, vals = PREMIUM[name]
    got = leddecode.wide_decode(bytes.fromhex(hexs))
    assert got is not None, name
    assert got[0] == idxs and got[1] == vals, name


def test_the_long_form_is_told_apart_by_the_header_alone():
    for name, (hexs, _i, _v) in PREMIUM.items():
        b = bytes.fromhex(hexs)
        assert leddecode.wide_long(b[2], b[3:-2]) == name.startswith("long"), name
    # a short bitmap (a window of 8 groups or fewer, no M) is not the long form
    assert not leddecode.wide_long(0x8A, bytes.fromhex("dc067ff87f"))


def test_a_long_frame_cut_short_or_padded_is_refused():
    hexs = PREMIUM["long_M_ba"][0]
    b = bytes.fromhex(hexs)
    body = b[3:-2]
    for cut in range(1, len(body)):
        maimed = b[:3] + body[:cut] + b[-2:]
        got = leddecode.wide_decode(maimed)
        assert got is None or got[0] != PREMIUM["long_M_ba"][1], cut
    assert leddecode.wide_decode(b[:-2] + b"\x00" + b[-2:]) is None


# ---- the C side: the shim's own walk, and the per-board vote --------------------------------
def _extract(name):
    src = open(SHIM, encoding="utf-8", errors="replace").read()
    m = re.search(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M)
    assert m, name
    i, depth = src.index("{", m.start()), 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
    raise AssertionError(name)


HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void logmsg(const char *s) { fputs(s, stdout); }
static int title_settled, led_wide_verdict = 0;
static int led_wide_settled(void) { return title_settled; }
static unsigned char led_count[16], led_known[16][96], led_wide_owns[16][96];
static struct { unsigned decoded, gen, wide_decoded; unsigned char val[16][96]; } shm, *led_shm = &shm;
static unsigned led_shm_len = 8192;
static void led_map(void) {}
static void led_val(unsigned node, unsigned idx, unsigned char v) { shm.val[node][idx] = v; }
static signed char led_node_verdict[16];
static unsigned short led_node_votes[16], led_node_yes[16];
@FUNCS@
static int frame(unsigned node, const char *h)
{
    unsigned char b[512];
    int n = 0;
    while (h[0] && h[1]) { char t[3] = { h[0], h[1], 0 }; b[n++] = (unsigned char)strtoul(t, 0, 16); h += 2; }
    return led_node_wide_publish(node, b[2], b + 3, (unsigned)n - 5);
}
int main(int argc, char **argv)
{
    int k, i;
    for (k = 1; k < argc; k++) {
        if (!strcmp(argv[k], "walk")) {                 /* walk <cmd hex> <body hex> */
            unsigned char body[512], idx[96], val[96];
            unsigned cnt = 0, blen = 0, cmd = (unsigned)strtoul(argv[k + 1], 0, 16);
            const char *h = argv[k + 2];
            k += 2;
            while (h[0] && h[1]) { char t[3] = { h[0], h[1], 0 }; body[blen++] = (unsigned char)strtoul(t, 0, 16); h += 2; }
            if (!led_wide_walk(body, blen, cmd, idx, val, &cnt)) { printf("REFUSED\n"); continue; }
            for (i = 0; i < (int)cnt; i++) printf("%u:%u ", idx[i], val[i]);
            printf("\n");
        } else if (!strcmp(argv[k], "title")) {         /* title yes|no|undecided */
            k++;
            title_settled = !strcmp(argv[k], "yes");
            led_wide_verdict = !strcmp(argv[k], "undecided") ? -1 : !strcmp(argv[k], "yes");
        } else if (!strcmp(argv[k], "send")) {          /* send <node> <times> <frame hex> */
            unsigned node = (unsigned)atoi(argv[k + 1]); int times = atoi(argv[k + 2]), pub = 0;
            for (i = 0; i < times; i++) pub += frame(node, argv[k + 3]);
            printf("PUBLISHED %d\n", pub);
            k += 3;
        } else if (!strcmp(argv[k], "val")) {           /* val <node> <idx> */
            printf("VAL %d\n", shm.val[atoi(argv[k + 1])][atoi(argv[k + 2])]);
            k += 2;
        }
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def shim(tmp_path_factory):
    if not os.path.isfile(SHIM):
        pytest.skip("rig not present")
    if not CC:
        pytest.skip("no C compiler on this host")
    funcs = "\n".join(_extract(n) for n in ("popcount8", "led_wide_long", "led_wide_walk", "led_node_wide_publish"))
    d = tmp_path_factory.mktemp("ledpremium")
    (d / "h.c").write_text(HARNESS.replace("@FUNCS@", funcs), encoding="utf-8")
    exe = d / ("h.exe" if os.name == "nt" else "h")
    r = subprocess.run([CC, "-O1", "-o", str(exe), str(d / "h.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(exe)


def _run(exe, *args):
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize("name", sorted(PREMIUM))
def test_the_shims_walk_and_the_python_twin_agree_on_premium_frames(shim, name):
    hexs, idxs, vals = PREMIUM[name]
    b = bytes.fromhex(hexs)
    out = _run(shim, "walk", "%02x" % b[2], b[3:-2].hex()).strip()
    assert out == " ".join("%d:%d" % (i, v) for i, v in zip(idxs, vals)), name


MULTI = PREMIUM["long_M_ba"][0]
SINGLE = PREMIUM["single_97"][0]
STRIP = "8e5ca6c80bf8c77ffc9bb66d3e3e3ea2a2a29898981e1e1efdfdfd4848482f2f2ff6f6f694949477777700"  # node 14, refused


def test_a_board_that_proves_the_grammar_is_read_by_it(shim):
    out = _run(shim, "title", "no", "send", "9", "199", MULTI, "val", "9", "78",
               "send", "9", "1", MULTI, "send", "9", "1", MULTI, "val", "9", "78")
    pubs = re.findall(r"PUBLISHED (\d+)", out)
    assert pubs == ["0", "0", "1"]                   # 199 votes, the 200th decides, then it publishes
    assert "node 9 dialect ACCEPTED" in out and "200 of 200" in out
    assert re.findall(r"VAL (\d+)", out) == ["0", "123"]


def test_single_lamp_frames_do_not_vote_and_a_strip_board_is_refused(shim):
    out = _run(shim, "title", "no", "send", "9", "500", SINGLE, "send", "14", "200", STRIP,
               "send", "14", "5", MULTI)
    assert "node 9 dialect" not in out               # 500 one-lamp frames: no verdict
    assert "node 14 dialect REFUSED" in out and "0 of 200" in out
    assert re.findall(r"PUBLISHED (\d+)", out) == ["0", "0", "0"]


def test_a_mostly_refused_board_is_refused_even_with_some_exact_closes(shim):
    out = _run(shim, "title", "no", "send", "12", "30", MULTI, "send", "12", "170", STRIP)
    assert "node 12 dialect REFUSED" in out and "30 of 200" in out


def test_a_title_that_already_speaks_it_or_has_not_decided_is_left_alone(shim):
    out = _run(shim, "title", "yes", "send", "9", "300", MULTI)
    assert "dialect" not in out and "PUBLISHED 0" in out       # batman: the title path handles it
    out = _run(shim, "title", "undecided", "send", "9", "300", MULTI, "val", "9", "78")
    assert "node 9 dialect ACCEPTED" in out and "PUBLISHED 0" in out and "VAL 0" in out
