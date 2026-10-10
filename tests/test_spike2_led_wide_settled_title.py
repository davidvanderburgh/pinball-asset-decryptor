"""A title that proved the wide lamp grammar has its godzilla commands read by it too (PAD-311).

The rig's LED view (dump/padled, hwshim.c led_publish) misread short one-light insert
frames on Metallica Remastered 1.04: the title's own vote had said every board speaks the
swelf grammar (200 of 200), but the insert boards' 97/a2..a6/b4/b5 frames were still
handed to the older godzilla shapes first, and those read a swelf body as theirs
whenever the lengths fit. `b5 17 a4 03` (lamps 23 and 36 to 0xff) became "lamps 23..36
fading down"; `a2 2d ae ff 00 03 02` (lamp 45 to 0xff, 46 to 0x00) became a pulse
overlay that never moved the plane. The wire decode was right every time; only the view
was wrong (PAD-306's proof had to rest on the wire for this reason).

The frames here are the real ones from that run (PAD-306 litwire, rig 3). The C side
compiles led_publish and everything under it out of hwshim.c (skipped without a
compiler), so what is tested is the dispatch the shim really runs.
"""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, "tools", "spike2_emu", "hwshim.c")
CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

#: node 8, LIT SOME START: M list [23][36|0x80], A=1 (every lamp 0xff), B=0x14 (one base byte)
B5_TWO_LAMPS_ON = "8805b517a4030000"
#: node 8, LIT SOME END: the same two lamps, A=0 (every lamp 0x00), B=0 (one plane byte each)
A0_TWO_LAMPS_OFF = "8806a017a400021500"
#: node 9, a hold: M list [45][46|0x80], A=2 (ff, 00), B=0 (two plane bytes)
A2_ONE_ON_ONE_OFF = "8908a22daeff000302ee00"
#: node 9, LIT SOME START: a single index, A=1, one base byte
S95_ONE_LAMP_ON = "8904952d03ae00"
#: node 14 of a Premium 1.16 game: a strip-board frame the walk refuses
STRIP = "8e5ca6c80bf8c77ffc9bb66d3e3e3ea2a2a29898981e1e1efdfdfd4848482f2f2ff6f6f694949477777700"


def _extract(name):
    src = open(SHIM, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"^static [^\n;]*\b%s\([^;]*?\)\s*\n?\{" % re.escape(name), src, re.M):
        i, depth = src.index("{", m.start()), 0
        for j in range(i, len(src)):
            depth += {"{": 1, "}": -1}.get(src[j], 0)
            if depth == 0:
                return src[m.start():j + 1]
    raise AssertionError(name)


FUNCS = ("popcount8", "led_insert_node", "led_gz_cmd", "led_show_cmd", "led_dec_log",
         "led_wide_long", "led_wide_walk", "led_wide_strip_bank", "led_wide_dialect",
         "led_wide_settled", "led_strip_levels", "led_wide_publish", "led_node_wide_publish",
         "led_publish")

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void logmsg(const char *s) { fputs(s, stdout); }
static unsigned long pad_ms(void) { static unsigned long t; return t += 10; }
static struct {
    unsigned magic, version, gen, decoded, skipped;
    unsigned char val[16][96];
    unsigned wide_decoded, wide_skipped;
    unsigned fade_head;
    struct { unsigned ms; unsigned char node, start, end, from, to, rise, fall, pad; } fade[96];
    unsigned char seen[16][96];
} shm, *led_shm = &shm;
static unsigned led_shm_len = 8192;
static unsigned char led_known[16][96], led_order[16][96], led_count[16], led_wide_owns[16][96];
static signed char led_node_verdict[16];
static unsigned short led_node_votes[16], led_node_yes[16];
static int led_wide_verdict = -1;
static void led_map(void) {}
static void led_seen(unsigned node, unsigned idx) { shm.seen[node][idx] = 1; }
static void led_val(unsigned node, unsigned idx, unsigned char v) { if (node < 16 && idx < 96) { shm.val[node][idx] = v; led_seen(node, idx); } }
static unsigned char led_level70(unsigned lo, unsigned hi) { (void)hi; return (unsigned char)lo; }
static void led_show_note(unsigned node, unsigned cmd, unsigned weight) { (void)node; (void)cmd; (void)weight; }
/* a banked frame's levels (PAD-500's version-6 plane): not what this test reads */
static void led_hi(unsigned node, int bank, const unsigned char *idx, const unsigned char *val, unsigned cnt)
{ (void)node; (void)bank; (void)idx; (void)val; (void)cnt; }
@FUNCS@
int main(int argc, char **argv)
{
    int k, i;
    for (k = 1; k < argc; k++) {
        if (!strcmp(argv[k], "known")) {                /* known <node> <first> <last> */
            unsigned node = (unsigned)atoi(argv[k + 1]), a = (unsigned)atoi(argv[k + 2]), b = (unsigned)atoi(argv[k + 3]);
            for (i = (int)a; i <= (int)b; i++) { led_known[node][i] = 1; led_order[node][led_count[node]++] = (unsigned char)i; }
            k += 3;
        } else if (!strcmp(argv[k], "send")) {          /* send <node> <times> <frame hex> */
            unsigned char b[512];
            unsigned node = (unsigned)atoi(argv[k + 1]);
            int times = atoi(argv[k + 2]), n = 0;
            const char *h = argv[k + 3];
            while (h[0] && h[1]) { char t[3] = { h[0], h[1], 0 }; b[n++] = (unsigned char)strtoul(t, 0, 16); h += 2; }
            b[0] = (unsigned char)(0x80 | node);
            for (i = 0; i < times; i++) led_publish(b, n);
            k += 3;
        } else if (!strcmp(argv[k], "val")) {           /* val <node> <idx> */
            printf("VAL %u.%u=%d\n", atoi(argv[k + 1]), atoi(argv[k + 2]), shm.val[atoi(argv[k + 1])][atoi(argv[k + 2])]);
            k += 2;
        } else if (!strcmp(argv[k], "fades")) {
            printf("FADES %u", shm.fade_head);
            for (i = 0; i < (int)shm.fade_head && i < 96; i++)
                printf(" [%u:%u..%u %u->%u r%u f%u]", shm.fade[i].node, shm.fade[i].start, shm.fade[i].end,
                       shm.fade[i].from, shm.fade[i].to, shm.fade[i].rise, shm.fade[i].fall);
            printf("\n");
        } else if (!strcmp(argv[k], "counts")) {
            printf("COUNTS decoded=%u skipped=%u wide_decoded=%u wide_skipped=%u\n",
                   shm.decoded, shm.skipped, shm.wide_decoded, shm.wide_skipped);
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
    d = tmp_path_factory.mktemp("ledsettled")
    (d / "h.c").write_text(HARNESS.replace("@FUNCS@", "\n".join(_extract(n) for n in FUNCS)), encoding="utf-8")
    exe = d / ("h.exe" if os.name == "nt" else "h")
    r = subprocess.run([CC, "-O1", "-o", str(exe), str(d / "h.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(exe)


def _run(exe, *args):
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


#: the insert boards' lamps the godzilla shapes would accept these frames for
KNOWN = ("known", "8", "0", "95", "known", "9", "0", "95")
#: a non-insert board speaking the grammar: 200 exact closes settle the title's verdict
SETTLE_YES = ("send", "10", "200", B5_TWO_LAMPS_ON)
#: a strip board refusing it 200 times: the title's verdict is no (godzilla's case)
SETTLE_NO = ("send", "14", "200", STRIP)


def test_a_settled_title_reads_its_two_lamp_list_frames_as_the_builder_sent_them(shim):
    out = _run(shim, *KNOWN, *SETTLE_YES, "send", "8", "1", B5_TWO_LAMPS_ON,
               "val", "8", "23", "val", "8", "30", "val", "8", "36", "fades")
    assert "dialect ACCEPTED" in out
    assert "VAL 8.23=255" in out and "VAL 8.36=255" in out
    assert "VAL 8.30=0" in out                       # not a range: the lamps between are untouched
    assert "FADES 0" in out                          # and no fade-down was invented


def test_a_settled_title_reads_a_six_byte_a2_as_two_levels_not_a_pulse(shim):
    out = _run(shim, *KNOWN, *SETTLE_YES, "send", "9", "1", S95_ONE_LAMP_ON, "val", "9", "45",
               "send", "9", "1", A2_ONE_ON_ONE_OFF, "val", "9", "45", "val", "9", "46", "fades")
    assert re.findall(r"VAL 9\.45=(\d+)", out) == ["255", "255"]
    assert "VAL 9.46=0" in out
    assert "FADES 0" in out


def test_a_settled_title_turns_the_same_lamps_off_again(shim):
    out = _run(shim, *KNOWN, *SETTLE_YES, "send", "8", "1", B5_TWO_LAMPS_ON,
               "send", "8", "1", A0_TWO_LAMPS_OFF, "val", "8", "23", "val", "8", "36", "fades", "counts")
    assert "VAL 8.23=0" in out and "VAL 8.36=0" in out and "FADES 0" in out
    assert "wide_skipped=0" in out                   # every frame closed under the walk


def test_a_title_the_vote_refused_keeps_the_godzilla_shapes(shim):
    # godzilla_pro: b5 blen 3 IS [start][0x80|end][rate] there, and the blen-6 a2 IS a pulse
    out = _run(shim, *KNOWN, *SETTLE_NO, "send", "8", "1", B5_TWO_LAMPS_ON,
               "val", "8", "23", "val", "8", "30", "val", "8", "36",
               "send", "9", "1", A2_ONE_ON_ONE_OFF, "val", "9", "45", "fades")
    assert "dialect REFUSED" in out
    assert "VAL 8.23=0" in out and "VAL 8.30=0" in out and "VAL 8.36=0" in out and "VAL 9.45=0" in out
    assert "FADES 2 [8:23..36 0->0 r0 f3] [9:45..46 255->0 r3 f2]" in out


def test_before_the_vote_is_in_the_shapes_still_own_the_insert_boards(shim):
    # the title has not decided: read exactly as before this change
    out = _run(shim, *KNOWN, "send", "8", "1", B5_TWO_LAMPS_ON, "val", "8", "23", "fades")
    assert "dialect" not in out
    assert "VAL 8.23=0" in out and "FADES 1 [8:23..36 0->0 r0 f3]" in out
