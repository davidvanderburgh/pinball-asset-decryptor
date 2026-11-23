"""PAD-1521 (luvthatapex, Bond LE): a drain in one of his own modes holds the game's end of ball for the mode's
TOTAL (PAD-622's pm_ball_end_hold), and the flippers stayed live all through it - the hold runs in the game's
end-of-ball dispatch before the game itself switches them off. Now the hold switches them off through the game's
own all-flippers off (PAD-1406's pair), answers the game's flipper policy "off" while it lasts and never turns them
back on: the game's next ball does, as after any ball.

The runtime's two sections (the hold, PAD-622; the flippers, PAD-1406) lifted verbatim and run on the host against
stubs of the game."""
import pathlib
import re

from tests.test_spike2_mode_roster import _host_run
from tests.test_pad1406_flippers import _section as _fl_section

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"


def _hold_section(src):
    a = src.index("/* ---- the end of a ball held for a mode's total (PAD-622)")
    return src[a:src.index("static void ball_end_hold_arm(void)", a)]


HOST = r"""#include <stdio.h>
#include <stdarg.h>
#define PM_CAN_BALL_END_HOLD 0x0800u
struct pm_mode { const char *name; };
static const struct pm_mode game = { "CRAB KEY" };
static const struct pm_mode *current = &game;
static struct { const struct pm_mode *owner; int tilted; } og;
static struct { int state; } dto;
static unsigned can = PM_CAN_BALL_END_HOLD;
static unsigned long now = 1000;
static int in_game = 1, has_sites = 1, tilt_events, sleeps, offs, tilt_at = -1;
static void say(const char *f, ...) { va_list ap; va_start(ap, f); vprintf(f, ap); va_end(ap); putchar('\n'); }
static int pm_snprintf(char *o, unsigned long n, const char *f, ...)
{ va_list ap; int r; va_start(ap, f); r = vsnprintf(o, n, f, ap); va_end(ap); return r; }
static unsigned long pm_ms(void) { return now; }
static int pm_in_game(void) { return in_game; }
static int pm_event(const char *n) { return 7; }
static unsigned event_count(int id) { return tilt_events; }
static void g_off(void) { offs++; }
static void g_on(void) { printf("FLIPPERS ON\n"); }
static unsigned long (*wrapped)(unsigned long, unsigned long, unsigned long, unsigned long);
static unsigned long q_game(unsigned long id, unsigned long args, unsigned long a2, unsigned long a3)
{ ((unsigned *)args)[1] = 2; return 1; }                     /* a listener of the game's: on */
static unsigned hook_call(unsigned a, void *w)
{ wrapped = (unsigned long (*)(unsigned long, unsigned long, unsigned long, unsigned long))w;
  return (unsigned)(unsigned long)q_game; }
static unsigned args[2];
static unsigned policy(void) { args[0] = 0; args[1] = 1; wrapped(0x40, (unsigned long)args, 0, 0); return args[1]; }
static void g_sleep(unsigned t)
{
    if (++sleeps == 3) printf("POLICY IN HOLD %u\n", policy());
    if (sleeps == tilt_at) tilt_events++;
    now += 10;
}
static unsigned long fn(const char *n)
{
    if (!__builtin_strcmp(n, "proc_sleep")) return (unsigned long)g_sleep;
    if (!has_sites) return 0;
    if (!__builtin_strcmp(n, "flippers_off")) return (unsigned long)g_off;
    if (!__builtin_strcmp(n, "flippers_on")) return (unsigned long)g_on;
    if (!__builtin_strcmp(n, "flipper_query_call")) return 0x3ca39cul;
    return 0;
}
"""

MAIN = r"""
static void ball_end(unsigned ms)
{
    beh.ms = 0; beh.release = 0; beh.asking = 1;
    printf("ASK %d\n", pm_ball_end_hold(ms));
    beh.asking = 0;
    sleeps = 0; offs = 0;
    ball_end_hold_run();
    beh.holding = 0;
    beh.tilts = tilt_events;
    printf("SLEEPS %d OFFS %d AFTER %d\n", sleeps, offs, beh.flippers_off);
}
int main(void)
{
    puts("== A"); ball_end(100);                          /* a mode's total: off for the whole hold */
    printf("POLICY AFTER %u\n", policy());                /* the game's own answer again */
    puts("== B"); ball_end(0);                            /* no mode asked: nothing touched */
    puts("== C"); has_sites = 0; ball_end(100); has_sites = 1;   /* no flipper sites: the hold as before */
    puts("== D"); tilt_at = 2; ball_end(100); tilt_at = -1;      /* a tilt mid-hold: the hold ends */
    return 0;
}
"""


def test_flippers_off_through_the_hold(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    out = _host_run(tmp_path, HOST + _hold_section(src) + _fl_section(src) + MAIN,
                    flags=("-no-pie", "-Wno-unused-function"))
    p = dict(re.findall(r"== (\w+)\n(.*?)(?=\n== |\Z)", out, re.S))
    a = p["A"]
    assert "ASK 1" in a and "the flippers are off for the hold" in a
    assert "POLICY IN HOLD 1" in a                         # the game's policy answered off meanwhile
    assert "SLEEPS 10 OFFS 11 AFTER 0" in a                # off at the start, then again after every tick
    assert "FLIPPERS ON" not in out                        # never back on: the game's next ball does that
    assert "POLICY AFTER 2" in a                           # the game's own listener answers once it is over
    b = p["B"]
    assert "ASK 0" in b and "SLEEPS 0 OFFS 0" in b and "flippers" not in b
    c = p["C"]
    assert "ASK 1" in c and "SLEEPS 10 OFFS 0" in c and "flippers are off" not in c
    d = p["D"]
    assert "the ball tilted" in d and "SLEEPS 2 OFFS 3 AFTER 0" in d


def test_wired_in_the_hold():
    src = RUNTIME.read_text(encoding="utf-8")
    sec = _hold_section(src)
    assert 'fl_hold(1)' in sec and 'fl_hold(0)' in sec and 'fn("flippers_on")' not in sec
    assert "(fl.off || fl.held)" in src and "static int fl_hold(int off)" in src
