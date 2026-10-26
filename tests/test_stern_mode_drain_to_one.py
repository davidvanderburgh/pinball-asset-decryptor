"""PAD-733: drain to one ball (pm_drain_to_one) - David, on MINILLA's 2-ball multiball ending with both balls up: "just
kill the flippers and show that the mode is ended, then instead of ending the ball, give a ball back in the plunger
lane". The runtime's section (pad_mode_runtime.c "PAD-733: drain to one ball") lifted verbatim and run on the host
against stubs of the game: the flippers dead (the game's all-flippers off, and nothing else of the game's), the last
ball's save armed only once one is left, the flippers back when that ball comes home (not for a ball still rolling
down the trough after the one before it), after 30 s, and never turned on at a ball's or the game's end (the game's
next ball does that). The Godzilla 1.16 ports' two lines, against the game programs when they are here.
The host part needs an ELF host C compiler (it skips otherwise)."""
import os
import pathlib
import re
import struct

import pytest

from tests.test_spike2_mode_roster import _host_run

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
ELVES = {"godzilla_le-1.16": [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""), r"C:\tmp\PAD-733\game_le116",
                              "/mnt/c/tmp/PAD-733/game_le116"],
         "godzilla_pro-1.16": [os.environ.get("PAD_GODZILLA_PRO_116_GAME", ""), r"C:\tmp\PAD-733\game_pro116",
                               "/mnt/c/tmp/PAD-733/game_pro116"]}
SITES = {"godzilla_le-1.16": ("0x003f1898", "0x003f196c"), "godzilla_pro-1.16": ("0x00479894", "0x00479968")}


def _section(src):
    a = src.index("/* ---- PAD-733: drain to one ball (pm_drain_to_one)")
    return src[a:src.index("/* ---- shots from the switch drain (optional; any build)", a)]


def test_it_kills_the_flippers_alone_and_is_wired_in():
    src = RUNTIME.read_text(encoding="utf-8")
    sec = re.sub(r"/\*.*?\*/", "", _section(src), flags=re.S)                # the code alone
    for call in ("coil_fire", "proc_create", "challenge_end_ball", "0x3f04cc", "devices"):
        assert call not in sec, call                                         # no coil of ours, no devices off
    assert 'fn(on ? "flippers_on" : "flippers_off")' in sec
    assert "    dto_tick();" in src and "    dto_ball_end();" in src
    hdr = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    assert "int pm_drain_to_one(void);" in hdr


HOST = r"""#include <stdio.h>
#include <stdarg.h>
#include <stdint.h>
struct pm_mode { const char *name; };
static const struct pm_mode mini = { "MINILLA" };
static const struct pm_mode *current = &mini;
static const struct pm_mode *running, *block_owner;   /* the block section's (PAD-733: its hold lasts through a drain) */
static unsigned long now;
static int in_game = 1, tilted, balls = 2, save_ok = 1, has_sites = 1;
#define N_SWITCHES 8
static struct { struct { unsigned id; uint64_t mask; } sw[N_SWITCHES]; int n_switch; } port = {
    { { 66, 0x8000000000000000ull }, { 67, 0x8000000000000000ull }, { 73, 0x100000ull } }, 3 };
#define N_SWITCH_IDS 256
static volatile unsigned switch_fired[N_SWITCH_IDS];
static long pm_port_value(const char *n, long fb) { return n[0] == 's' ? 62 : fb; }
static void say(const char *f, ...) { va_list ap; va_start(ap, f); vprintf(f, ap); va_end(ap); putchar('\n'); }
static int pm_snprintf(char *o, unsigned long n, const char *f, ...)
{ va_list ap; int r; va_start(ap, f); r = vsnprintf(o, n, f, ap); va_end(ap); return r; }
static unsigned long pm_ms(void) { return now; }
static int pm_in_game(void) { return in_game; }
static int ball_tilted(void) { return tilted; }
static int multiball_ok(void) { return 1; }
static int pm_balls_in_play(void) { return balls; }
static int pm_ball_save(unsigned s) { printf("SAVE %u\n", s); return save_ok; }
static uint64_t pm_shot(const char *n) { return n[0] == 'T' ? 0x8000000000000000ull : 0; }
static void g_off(void) { printf("FLIPPERS OFF\n"); }
static void g_on(void) { printf("FLIPPERS ON\n"); }
static void g_delay(unsigned s) { printf("SEARCH DELAY %u\n", s); }
#define MAP_R 1u
#define MAP_GAME 4u
static unsigned mb_record[6] = { 600, 0xbb, 0x01020000 };  /* the multiball's save still running: 600 ticks */
static int maps_has(unsigned long a, unsigned long n, unsigned how) { return 1; }
static unsigned data(const char *n) { return n[0] == 'm' ? (unsigned)(unsigned long)mb_record : 0; }
static unsigned fn(const char *n)
{
    if (!has_sites && n[0] == 'f') return 0;
    if (!__builtin_strcmp(n, "flippers_off")) return (unsigned)(unsigned long)g_off;
    if (!__builtin_strcmp(n, "flippers_on")) return (unsigned)(unsigned long)g_on;
    if (!__builtin_strcmp(n, "ball_search_delay")) return (unsigned)(unsigned long)g_delay;
    return 0;
}
"""

MAIN = r"""
static void tick_to(unsigned long t) { while (now < t) { now += 16; dto_tick(); } }
int main(void)
{
    puts("== A");
    printf("R %d\n", pm_drain_to_one());                  /* two up: dead flippers */
    printf("RECORD %u %u %08x\n", mb_record[0], mb_record[1], mb_record[2]);   /* its save over, the rest kept */
    tick_to(5000);                                         /* both still up */
    balls = 1; tick_to(5100);                              /* the first one home: the save armed */
    switch_fired[66]++; tick_to(6000);                     /* still rolling down the trough: not the last */
    tick_to(7000);
    switch_fired[67]++; tick_to(7100);                     /* the last one home */
    tick_to(8000);
    puts("== A2");
    balls = 2; now = 50000; printf("R %d\n", pm_drain_to_one());
    balls = 1; tick_to(50100);                             /* both home together, inside the settle */
    switch_fired[66]++; switch_fired[67]++; tick_to(50600);
    switch_fired[62]++; tick_to(50700);                    /* the served ball in the shooter lane */
    tick_to(51000);
    puts("== B");
    balls = 1; printf("R %d\n", pm_drain_to_one());        /* one ball: nothing to drain */
    puts("== C");
    balls = 3; now = 100000; printf("R %d\n", pm_drain_to_one()); tick_to(131000);   /* never home: 30 s */
    puts("== D");
    balls = 2; now = 200000; printf("R %d\n", pm_drain_to_one()); tick_to(201000); dto_ball_end();
    puts("== E");
    balls = 2; now = 300000; printf("R %d\n", pm_drain_to_one()); tick_to(301000); in_game = 0; tick_to(301100);
    in_game = 1;
    puts("== F");
    has_sites = 0; balls = 2; printf("R %d\n", pm_drain_to_one()); has_sites = 1;
    puts("== G");
    tilted = 1; printf("R %d\n", pm_drain_to_one()); tilted = 0;
    puts("== H");
    save_ok = 0; balls = 2; now = 400000; printf("R %d\n", pm_drain_to_one()); balls = 1; tick_to(400100);
    save_ok = 1;
    puts("== I");                                          /* PAD-733: its hold of the game's modes lasts through it */
    block_owner = running = &mini; balls = 2; now = 500000; pm_drain_to_one();
    running = 0;                                           /* the mode ended (pm_end) */
    printf("LIVE %d\n", block_live());
    balls = 1; tick_to(500100); switch_fired[66]++; tick_to(500600); switch_fired[62]++; tick_to(500700);
    printf("LIVE %d\n", block_live());                     /* the flippers back: the game's modes may start */
    block_owner = 0;
    return 0;
}
"""


def test_the_flippers_die_the_last_ball_is_saved_and_they_come_back(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    out = _host_run(tmp_path, HOST + _section(src) + MAIN, flags=("-no-pie", "-Wno-unused-function"))
    parts = dict(re.findall(r"== (\w+)\n(.*?)(?=\n== |\Z)", out, re.S))
    a = parts["A"]
    assert a.index("FLIPPERS OFF") < a.index("R 1") and "SEARCH DELAY 45" in a
    assert "the flippers are dead with 2 balls in play" in a
    # the multiball's own save ends with it: with dead flippers every drain inside it came back (run dto_insave)
    assert "the multiball's own ball save ends with it (600 ticks of it left, 187 of its grace)" in a
    assert "RECORD 0 0 01020000" in a
    assert a.count("SAVE 20") == 1 and a.index("down to 1 ball(s)") < a.index("SAVE 20")
    assert a.count("FLIPPERS ON") == 1                                        # back once, as the last one is home
    on = a.index("FLIPPERS ON")
    assert "the last ball is home" in a[on:] and a.rindex("FLIPPERS OFF") < on
    a2 = parts["A2"]
    assert a2.count("FLIPPERS ON") == 1 and "the served ball is in the shooter lane" in a2
    assert "R 0" in parts["B"] and "nothing to drain" in parts["B"] and "FLIPPERS" not in parts["B"]
    assert "its 30 s are up" in parts["C"] and "FLIPPERS ON" in parts["C"] and "SAVE" not in parts["C"]
    assert "the ball ended" in parts["D"] and "FLIPPERS ON" not in parts["D"]   # the game's next ball does it
    assert "the game ended" in parts["E"] and "FLIPPERS ON" not in parts["E"]
    assert "R 0" in parts["F"] and "no flippers off/on" in parts["F"] and "FLIPPERS" not in parts["F"]
    assert "R 0" in parts["G"] and "FLIPPERS" not in parts["G"]
    assert "would not arm the save" in parts["H"] and "FLIPPERS ON" in parts["H"]
    # PAD-733 (run mi_dadwin2: the game's BUILDING ATTACK began 13 ms after MINILLA's end, the flippers dead)
    i = parts["I"]
    assert i.index("LIVE 1") < i.index("FLIPPERS ON") < i.index("LIVE 0")


def _elf(key):
    return next((p for p in ELVES[key] if p and os.path.isfile(p)), None)


@pytest.mark.parametrize("key", sorted(SITES))
def test_the_godzilla_116_ports_name_the_flippers_off_and_on(key):
    text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
    lines = {m.group(1): (m.group(2), int(m.group(3), 16), int(m.group(4), 16))
             for m in re.finditer(r"^site (flippers_off|flippers_on)\s+(0x[0-9a-f]{8}) (0x[0-9a-f]{8}) (0x[0-9a-f]{8})$",
                                  text, re.M)}
    assert (lines["flippers_off"][0], lines["flippers_on"][0]) == SITES[key]
    record = {"godzilla_le-1.16": "0x007d3930", "godzilla_pro-1.16": "0x007d74e4"}[key]
    assert re.search(r"^data multiball_record\s+%s\b" % record, text, re.M)
    assert re.search(r"^value shooter_lane_switch\s+62\b", text, re.M)
    elf = _elf(key)
    if not elf:
        pytest.skip("no %s game program here" % key)
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as f:
        e = ELFFile(f)
        segs = [(s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in e.iter_segments() if s["p_type"] == "PT_LOAD"]
        for name, (va, w0, w1) in lines.items():
            va = int(va, 16)
            v, o, _n = next(s for s in segs if s[0] <= va < s[0] + s[2])
            f.seek(o + va - v)
            assert struct.unpack("<2I", f.read(8)) == (w0, w1), name
            # the two are the same code: each flipper record's enable bit (+6, 2) cleared / set, under the list's lock
            f.seek(o + va - v)
            body = struct.unpack("<31I", f.read(124))
            assert (0xe3c33002 in body) == (name == "flippers_off")             # bic r3, r3, #2
            assert (0xe3833006 in body) == (name == "flippers_on")              # orr r3, r3, #6
