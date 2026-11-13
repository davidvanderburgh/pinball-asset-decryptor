"""PAD-1221: every co-op teammate's ball waits in the trough while their character pick is open
(pad_mode_runtime.c coop_pick_hold, ci_serve_wrap).

DoomWalrus666 (Godzilla, co-op with characters and handicaps): on player 1's turn Action took the character, then the
handicap could be chosen and Action or the plunger launched the ball. On players 2-4 the Action press that took the
character also launched the ball, so no handicap could be chosen. Only teammate 1's ball-1 serve waited for the pick
(behind the intro); a later teammate's ball was in the lane under their pick, and the game launches on an Action press
even when the runtime hides it. The ball start's serve now waits for any open pick."""
from tests import test_spike2_mode_roster as R
from tests import test_pad1017_coop_turns as T

RUNTIME = T.RUNTIME

MAIN = r"""
#include <stdio.h>
#include <string.h>
static struct { int open; unsigned who; } pk;
static struct { char clip[8]; int holding; } ci;
static unsigned long now_ms, pick_ms_cfg = 30000;
#define coop_pick_ms pick_ms_cfg
static unsigned teammates = 2, player = 1, sleeps, served, close_after, held_seen;
static volatile unsigned char *coop_ball_byte;
static unsigned long pm_ms(void) { return now_ms; }
static unsigned pm_player(void) { return player; }
static unsigned coop_teammates(void) { return teammates; }
static void say(const char *f, ...) { (void)f; }
static void ci_ball_hold(unsigned ball) { (void)ball; }
static void game_sleep(unsigned t)
{
    sleeps++;
    now_ms += 100;
    if (ci.holding) held_seen++;
    if (close_after && sleeps >= close_after) pk.open = 0;
}
static unsigned fn(const char *name) { return !strcmp(name, "proc_sleep") ? (unsigned)(unsigned long)game_sleep : 0; }
static unsigned game_serve(unsigned a, unsigned b, unsigned c, unsigned d) { served++; return 0; }
static unsigned (*ci_serve_game)(unsigned, unsigned, unsigned, unsigned) = game_serve;
@FNS@
static void run(const char *what, int open, unsigned close, unsigned long pick_ms, unsigned mates)
{
    pk.open = open; pk.who = 2; close_after = close; pick_ms_cfg = pick_ms; teammates = mates;
    sleeps = served = held_seen = 0; now_ms = 0; ci.holding = 0;
    ci_serve_wrap(0, 0, 0, 0);
    printf("%s: slept %u, served %u, held %u, holding after %d\n", what, sleeps, served, held_seen, ci.holding);
}
int main(void)
{
    run("pick open", 1, 25, 30000, 2);
    run("no pick", 0, 0, 30000, 2);
    run("not co-op", 1, 25, 30000, 0);
    run("pick never taken", 1, 0, 2000, 2);
    return 0;
}
"""

SIGS = ("static unsigned long coop_pick_hold_most(unsigned long pick_ms)",
        "static void coop_pick_hold(void)",
        "static unsigned ci_serve_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "#define COOP_PICK_HOLD_MS 300000ul\n" + "\n".join(R._lift(src, sig) for sig in SIGS)
    # the runtime calls pointers through (unsigned long) casts of 32-bit target addresses; on the host keep them whole
    fns = fns.replace("((void (*)(unsigned))(unsigned long)fn(\"proc_sleep\"))(1)", "game_sleep(1)")
    lines = R._host_run(tmp_path, MAIN.replace("@FNS@", fns), flags=("-Wno-pointer-to-int-cast",)).splitlines()
    return {l.split(":")[0]: l.split(": ", 1)[1] for l in lines}


def test_a_later_teammates_serve_waits_for_their_pick_with_the_buttons_theirs(tmp_path):
    out = _run(tmp_path)
    assert out["pick open"] == "slept 25, served 1, held 25, holding after 0"


def test_no_open_pick_serves_at_once(tmp_path):
    out = _run(tmp_path)
    assert out["no pick"] == "slept 0, served 1, held 0, holding after 0"
    assert out["not co-op"] == "slept 0, served 1, held 0, holding after 0"


def test_a_pick_never_taken_lets_the_ball_go_after_its_time(tmp_path):
    out = _run(tmp_path)
    assert out["pick never taken"] == "slept 70, served 1, held 70, holding after 0"   # 2 s + 5 s at 100 ms a sleep


def test_the_serve_is_hooked_for_picks_without_an_intro():
    src = RUNTIME.read_text(encoding="utf-8")
    assert '(ci.clip[0] || coop_pick_on) && fn("serve_ball") && !ci_serve_game' in src
    assert "coop_pick_hold();" in R._lift(src, SIGS[2])
