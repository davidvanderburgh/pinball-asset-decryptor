"""PAD-1031: co-op characters - each teammate picks one at their first ball, and its ability holds while they are up.

DoomWalrus666 (Godzilla): "At the start of each player's Ball 1 ... Each player chooses their Godzilla (or selects
Random) ... No player may choose the same godzilla as another player. Each godzilla will have a unique ability";
daveyvandy: a generic entry point, the Godzilla set beside it. The runtime's character code (pad_mode_runtime.c
"co-op characters") is lifted verbatim and played through a model co-op game: coop.cfg's character lines read, the pick
walked with the flippers past the ones taken, RANDOM, and the adjustment getter's answer while each teammate is up.
The app's side (coop_play.py) reads what a game can have off its program and writes the lines."""
import json
import os
import pathlib

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from tests import test_spike2_mode_roster as R

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
#: PAD-1075: the longer-save ability on Godzilla: its ball save, O2 and every multiball's own save, doubled
LONGER_SAVE = ("adj:94x200:0:15,bs:94,adj:193x200:8:40,adj:203x200:10:60,adj:204x200:10:60,adj:206x200:13:40,adj:208x200:15:60,adj:210x200:20:60,adj:211x200:30:120,adj:217x200:28:80,adj:219x200:28:80,adj:221x200:14:50,adj:225x200:28:80,adj:227x200:28:80,adj:200x200:5:20")
GZ_ELF = next((p for p in ("C:/tmp/PAD-1010/elfs/godzilla_le-1_16_0_spike2.elf",
                            "C:/tmp/PAD-1031/elfs/godzilla_le-1_16_0_spike2.elf") if os.path.isfile(p)),
              "C:/tmp/PAD-1010/elfs/godzilla_le-1_16_0_spike2.elf")

MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
static void say(const char *f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); printf("\n"); }
#define pm_snprintf snprintf
static unsigned long now_ms = 1000;
static unsigned long pm_ms(void) { return now_ms; }
static int in_game = 1;                                  /* PAD-1044: 0 is busy (a menu over the game) */
static int pm_in_game(void) { return in_game; }
static unsigned pm_player(void) { return 1; }
static struct { int on; unsigned button, game, n, turn; } coop;
static unsigned coop_teammates(void) { return coop.n; }
static int str_starts(const char *s, const char *p) { return !strncmp(s, p, strlen(p)); }
@NUMBER@
static int coop_ball_msg = 5, coop_ball_held;
static char shown[96];
static int message_borrow(unsigned id, unsigned idx, const char *w) { (void)id; (void)idx; strcpy(shown, w); return 1; }
static void coop_turn_show(void) { sprintf(shown, "PLAYER %u  BALL %%d", coop.turn); }
static unsigned saved_s;
static int refuse;                                      /* PAD-1045: the game does not take a save */
static int pm_ball_save(unsigned s) { if (refuse) return 0; saved_s = s; return 1; }
static unsigned own_adj(unsigned id) { return id == 94 ? 5 : id == 195 ? 20 : 1; }
#define COOP_MSG_ID 0xC0090u
#define MAP_R 1u
static volatile unsigned char *coop_ball_byte;
static int maps_has(unsigned long a, unsigned n, unsigned f) { (void)a; (void)n; (void)f; return 0; }
static void maps_read(void) {}
static int coop_classic(void) { return 0; }                /* PAD-1065: not the Classic (no-ability) pick */
static unsigned fn(const char *name) { (void)name; return 0; }
static int str_eq(const char *a, const char *b) { return !strcmp(a, b); }
static void *pm_node(const char *where, const char *path) { (void)where; (void)path; return 0; }
static void *pm_text(const char *where, const char *path) { (void)where; (void)path; return 0; }
static void pm_set_text(void *t, const char *w) { (void)t; (void)w; }
static void str_copy(char *d, unsigned cap, const char *s, unsigned n) { (void)n; snprintf(d, cap, "%s", s); }
static void pm_show(void *node, int on) { (void)node; (void)on; }
static void coop_cards_find(void) {}                     /* PAD-1028 round 2: the award cards (test_pad1028) */
static int ball_waits = -1;                              /* PAD-1051: the game's plunger flags (-1: the port has none) */
static int coop_ball_waits(void) { return ball_waits; }
static void edge_take_held(unsigned id) { (void)id; }    /* PAD-1078: the drain section's (test_pad1051) */
struct pm_stock_rule;
static struct pm_stock_rule *pm_stock_rule(unsigned id) { (void)id; return 0; }
static int pm_stock_active(struct pm_stock_rule *r) { (void)r; return 0; }
#define PM_STOCK_ANY 0xffu
static int pm_stock_mode_running(unsigned kinds) { (void)kinds; return 0; }
static unsigned added_balls;
static int pm_multiball_add(unsigned n, unsigned s) { (void)s; added_balls += n; return 1; }
static long pm_port_value(const char *n, long f) { (void)n; return f; }
static uint64_t pm_stock_lit(struct pm_stock_rule *r) { (void)r; return 0; }
static unsigned more_state(unsigned slot) { (void)slot; return 0; }
static unsigned long data(const char *name) { (void)name; return 0; }
@DECL@
static unsigned coop_adj_answer(unsigned id, unsigned own);
/* PAD-1033: the runtime's one getter wrap answers a handicap, then the character; here no handicap */
static unsigned adj_chain(unsigned id) { return coop_adj_answer(id, coop_adj_game(id)); }
@FNS@
static void press(unsigned id) { coop_edge(id, 1, 0x800, 0); }
int main(void)
{
    static const char *const cfg[] = {
        "adj:94x200:0:15,bs:94 GODZILLA 1954|LONGER BALL SAVE", "save:10 GODZILLA 2000|ACTION BUTTON BALL SAVE",
        "adj:195x50:4:30,adj:173=0 GODZILLA GMK|EASIER HEAT RAY", "- SHIN GODZILLA|", "adj:oops NO ABILITY|",
        "boost:200,gift:311,gift:319,gift:315,gift:309,gift:320,gift:308,gift:310,keep:perks|=0x100,eb:3 KING KONG|DOUBLE POWER-UPS", 0 };
    int i;
    for (i = 0; cfg[i]; i++) coop_char_line(cfg[i]);
    coop_pick_on = 1; coop.button = 59; coop_left = 60; coop_action = 34; coop_adj_game = own_adj;
    printf("chars %d\n", coop_ch_n);
    for (i = 0; i < coop_ch_n; i++)
        printf("char %d [%s] [%s] adj %u save %u boost %u gift %u\n", i, coop_ch[i].name, coop_ch[i].does,
               coop_ch[i].n_adj, coop_ch[i].save_s, coop_ch[i].boost, coop_ch[i].n_gift ? coop_ch[i].gift[0] : 0u);
    printf("gifts %u:", coop_ch[5].n_gift);                 /* PAD-1075: several, in order, COOP_GIFTS at most */
    for (i = 0; i < (int)coop_ch[5].n_gift; i++) printf(" %u", coop_ch[5].gift[i]);
    printf("\n");
    printf("perks or %u v 0x%x eb %u\n", coop_ch[5].keep_or[0], coop_ch[5].keep_v[0], coop_ch[5].eb);   /* round 6 */
    coop.n = 3; coop.turn = 1;
    coop_chars_begin();
    printf("before a pick: %u\n", coop_adj_answer(94, own_adj(94)));
    coop_pick_open(1);
    printf("open [%s]\n", shown);
    now_ms += 1600; coop_chars_tick(); printf("flip [%s]\n", shown);
    now_ms += 1600; coop_chars_tick(); printf("flip2 [%s]\n", shown);     /* PAD-1078: how to take one */
    now_ms += 1600; coop_chars_tick(); printf("flip3 [%s]\n", shown);
    press(34); coop_chars_tick();
    printf("t1 %d [%s] reads 94: %u 195: %u\n", coop_pick_of[1], shown, coop_adj_answer(94, own_adj(94)), coop_adj_answer(195, own_adj(195)));
    printf("ball out: %u\n", saved_s); saved_s = 0;
    coop.turn = 2; coop_chars_turn();
    printf("open2 [%s]\n", shown);
    press(34); coop_chars_tick();
    printf("t2 %d reads 94: %u\n", coop_pick_of[2], coop_adj_answer(94, own_adj(94)));
    printf("no ball out: %u\n", saved_s);
    now_ms += 5000; press(34); now_ms += 300; press(34); coop_chars_tick();
    printf("save %u\n", saved_s); saved_s = 0;
    now_ms += 200; press(34); now_ms += 300; press(34); coop_chars_tick();
    printf("again %u\n", saved_s);
    coop.turn = 3; coop_chars_turn();
    printf("open3 [%s]\n", shown);
    press(60); coop_chars_tick(); printf("left [%s]\n", shown);
    press(59); coop_chars_tick(); printf("right [%s]\n", shown);
    press(34); coop_chars_tick();
    printf("t3 %d reads 195: %u 173: %u 94: %u\n", coop_pick_of[3], coop_adj_answer(195, own_adj(195)), coop_adj_answer(173, own_adj(173)), coop_adj_answer(94, own_adj(94)));
    coop.turn = 1; coop_chars_turn();
    printf("t1 again: open %d save used %d\n", pk.open, coop_save_used);
    /* a new game: a 4th teammate's RANDOM never takes one a teammate has */
    coop.n = 4; coop_chars_begin();
    coop_pick_of[1] = 0; coop_pick_of[2] = 1; coop_pick_of[3] = 3;
    coop.turn = 4; coop_chars_turn(); press(60); coop_chars_tick(); printf("open4 [%s]\n", shown);
    press(34); coop_chars_tick(); printf("t4 %d\n", coop_pick_of[4]);
    /* the time runs out: the one shown */
    coop_chars_begin(); coop.turn = 1; coop_chars_turn(); press(59); coop_chars_tick();
    now_ms += 20000; coop_chars_tick(); printf("at 20 s: open %d left %u\n", pk.open, coop_pick_secs(pk.left));
    now_ms += 10000; coop_chars_tick(); printf("timed %d open %d [%s]\n", coop_pick_of[1], pk.open, shown);
    now_ms += 2600; coop_chars_tick(); printf("then [%s]\n", shown);
    /* PAD-1044: busy under the pick (a menu over the game): it waits, its clock stopped, and goes on after */
    coop_chars_begin(); coop.turn = 2; coop_chars_turn();
    now_ms += 10000; coop_chars_tick();
    in_game = 0; now_ms += 1000; coop_chars_tick(); now_ms += 60000; coop_chars_tick();
    printf("busy: open %d who %u pick %d\n", pk.open, pk.who, coop_pick_of[2]);
    in_game = 1; now_ms += 1000; coop_chars_tick(); printf("back: open %d [%s]\n", pk.open, shown);
    now_ms += 18500; coop_chars_tick(); printf("back +18.5 s: open %d\n", pk.open);
    now_ms += 1000; coop_chars_tick(); printf("back timed %d\n", coop_pick_of[2]);
    /* no time limit: only Action takes one */
    coop_pick_ms = 0; coop_chars_begin(); coop.turn = 3; coop_chars_turn();
    printf("unlimited [%s]\n", shown);
    now_ms += 600000; coop_chars_tick(); printf("unlimited 10 min: open %d\n", pk.open);
    press(34); coop_chars_tick(); printf("unlimited took %d\n", coop_pick_of[3]);
    return 0;
}
"""

FNS = ("static int coop_pick_step(int n, int at, int dir, unsigned taken)",
       "static unsigned coop_count_get(int i, volatile unsigned *f)",
       "static void coop_count_put(int i, volatile unsigned *f, unsigned v)",
       "static unsigned long coop_pick_left(unsigned long left, unsigned long el)",
       "static unsigned coop_pick_secs(unsigned long left)",
       "static volatile unsigned *coop_cache_field(const struct coop_cache *k)",
       "static unsigned coop_adj_value(unsigned own, unsigned op, unsigned v, unsigned lo, unsigned hi)",
       "static unsigned coop_taken(unsigned except)",
       "static const struct coop_char *coop_char_up(void)",
       "static unsigned coop_adj_answer(unsigned id, unsigned own)",
       "static void coop_cache_hold(void)",
       "static void coop_gift(const struct coop_char *c)",
       "static void coop_counts_give(const struct coop_char *c)",
       "static volatile unsigned *coop_count_field(int i)",
       "static void coop_double_tick(void)",
       "static volatile unsigned *coop_lit_field(int i)",
       "static void coop_lit_tick(void)",
       "static unsigned coop_step_get(int i, volatile unsigned char *b, unsigned j, unsigned p)",
       "static void coop_step_put(int i, volatile unsigned char *b, unsigned j, unsigned p, unsigned v)",
       "static void coop_steps_tick(void)",
       "static void coop_keep_tick(void)",

       "static const char *coop_pick_how(void)",
       "static int coop_pick_steps(void)",
       "static void coop_pick_say(void)",
       "static void coop_pick_open(unsigned t)",
       "static void coop_pick_close(const char *how)",
       "static int coop_launch_press(unsigned long now)",
       "static void coop_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity)",
       "static int coop_rule_running(unsigned rules)",
       "static void coop_rules_watch(void)",
       "static int coop_spot(const struct coop_char *c)",
       "static void coop_screens_tick(void)",
       "static void coop_chars_tick(void)",
       "static void coop_chars_begin(void)",
       "static void coop_chars_turn(void)",
       "static void coop_char_line(const char *s)")


def _decl(src):
    """The character section's declarations, verbatim: from its #defines to the last of its globals."""
    start = src.index("#define COOP_CHARS 16")
    end = src.index("static int coop_dbl_armed;", start)
    return src[start:src.index("\n", end) + 1]


def _run(tmp_path, main=MAIN):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig + "\n{") for sig in FNS)
    number = "\n".join(R._lift(src, sig + "\n{") for sig in ("static int hexval(int c)",   # the runtime's own: it eats
                                                            "static uint64_t number(const char **p, int *ok)"))
    main = main.replace("@NUMBER@", number)                                      # the space after a number
    return R._host_run(tmp_path, main.replace("@DECL@", _decl(src)).replace("@FNS@", fns)).splitlines()


def test_each_teammate_picks_one_nobody_else_has_and_its_ability_holds_while_they_are_up(tmp_path):
    out = _run(tmp_path)
    assert "chars 6" in out
    assert "char 0 [GODZILLA 1954] [LONGER BALL SAVE] adj 1 save 0 boost 0 gift 0" in out
    assert "char 1 [GODZILLA 2000] [ACTION BUTTON BALL SAVE] adj 0 save 10 boost 0 gift 0" in out
    assert "char 2 [GODZILLA GMK] [EASIER HEAT RAY] adj 2 save 0 boost 0 gift 0" in out
    assert "char 3 [SHIN GODZILLA] [] adj 0 save 0 boost 0 gift 0" in out
    assert "char 4 [NO ABILITY] [] adj 0 save 0 boost 0 gift 0" in out
    assert "char 5 [KING KONG] [DOUBLE POWER-UPS] adj 0 save 0 boost 200 gift 311" in out             # an ability it cannot read: none
    assert "gifts 6: 311 319 315 309 320 308" in out                # PAD-1075: several gifts; round 6: six, the seventh past the room
    assert "perks or 1 v 0x100 eb 3" in out                         # round 6: keep:perks|=<mask> sets bits; eb:<ball>
    assert "before a pick: 5" in out                                # no character yet: the game's own value
    assert "open [PLAYER 1 PICK  30: GODZILLA 1954]" in out          # PAD-1044: the seconds left with it
    assert "flip [LONGER BALL SAVE]" in out                         # then what it does, in turn
    assert "flip2 [ACTION TO PICK  27]" in out                      # PAD-1078: then how to take one (no plunger flags)
    assert "flip3 [PLAYER 1 PICK  26: GODZILLA 1954]" in out         # and round again
    # teammate 1's: the save time doubled (5 -> 10, at most 15); the heat ray is not theirs; the top line says whom
    # they took (PAD-1044)
    assert "t1 0 [PLAYER 1 IS GODZILLA 1954] reads 94: 10 195: 20" in out
    assert "open2 [PLAYER 2 PICK  30: GODZILLA 2000]" in out        # 1954 is taken: the first one free
    assert "ball out: 10" in out                                    # the ball served before the pick: its save now
    assert "no ball out: 0" in out                                  # 2000 has no bs: nothing at its pick
    assert "t2 1 reads 94: 5" in out                               # teammate 2 up: the game's own save time
    assert "save 10" in out                                         # Action twice within 0.6 s
    assert "again 0" in out                                         # once a ball
    assert "open3 [PLAYER 3 PICK  30: GODZILLA GMK]" in out
    assert "left [PLAYER 3 PICK  30: RANDOM]" in out                # left past 2000 and 1954 (taken) to RANDOM
    assert "right [PLAYER 3 PICK  30: GODZILLA 1954]" not in out
    assert "right [PLAYER 3 PICK  30: GODZILLA GMK]" in out         # and back, past them again
    assert "t3 2 reads 195: 10 173: 0 94: 5" in out                 # half the spins (20 -> 10), held to 4..30
    assert "t1 again: open 0 save used 0" in out                    # a picked teammate is not asked again
    assert "open4 [PLAYER 4 PICK  30: RANDOM]" in out
    assert "t4 2" in out or "t4 4" in out                           # RANDOM: GMK or NO ABILITY, the free ones
    # PAD-1044: 30 s, counted down; then the one shown, said on the top line a moment, then the ball's line
    assert "at 20 s: open 1 left 10" in out
    assert "timed 1 open 0 [PLAYER 1 IS GODZILLA 2000]" in out
    assert "then [PLAYER 1  BALL %d]" in out
    # busy under the pick: kept open with no character, its clock stopped; 20 s left after, not dropped
    assert "busy: open 1 who 2 pick -1" in out
    assert "back: open 1 [ACTION TO PICK  19]" in out              # PAD-1078: the turn's third step
    assert "back +18.5 s: open 1" in out
    assert "back timed 0" in out
    assert "unlimited [PLAYER 3 PICK: GODZILLA 1954]" in out        # no time limit: no seconds
    assert "unlimited 10 min: open 1" in out
    assert "unlimited took 0" in out



LANE_MAIN = r"""
static void lane(int in) { coop_edge(62, in ? 1 : 0, 0x800, 0); }        /* closed: a ball waits in the lane */
static void twice(const char *what)
{
    saved_s = 0;
    press(34); now_ms += 300; press(34); coop_chars_tick();
    printf("%s %u used %d\n", what, saved_s, coop_save_used);
}
static void launch(const char *what)                 /* Action launches; a second press 0.4 s on, as a player does */
{
    saved_s = 0;
    lane(1); now_ms += 3000; press(34); now_ms += 40; lane(0); now_ms += 360; press(34); coop_chars_tick();
    printf("%s %u used %d\n", what, saved_s, coop_save_used);
}
int main(void)
{
    coop_char_line("save:10 GODZILLA 2000|ACTION BUTTON BALL SAVE");
    coop_char_line("- OTHER|");
    coop_pick_on = 1; coop.button = 59; coop_left = 60; coop_action = 34; coop_lane = 62;
    coop.n = 2; coop.turn = 1;
    lane(1);                                         /* ball 1 is in the lane when the team forms */
    coop_chars_begin(); coop_pick_open(1); press(34); coop_chars_tick();
    printf("t1 %d\n", coop_pick_of[1]);
    now_ms += 1000; press(34); now_ms += 40; lane(0); now_ms += 360; press(34); coop_chars_tick();
    printf("ball 1 launch %u used %d\n", saved_s, coop_save_used);
    now_ms += 5000; twice("ball 1 in play");
    now_ms += 5000; twice("ball 1 again");
    coop.turn = 2; coop_chars_turn(); press(34); coop_chars_tick();
    coop.turn = 1; coop_chars_turn();                /* ball 2: teammate 1 again */
    now_ms += 2000; twice("ball 2 not served");
    now_ms += 2000; launch("ball 2 launch");
    now_ms += 5000; twice("ball 2 in play");
    coop.turn = 2; coop_chars_turn(); coop.turn = 1; coop_chars_turn();
    now_ms += 2000; launch("ball 3 launch");
    refuse = 1; now_ms += 5000; twice("ball 3 refused");
    refuse = 0; now_ms += 5000; twice("ball 3 taken");
    coop_lane = 0; coop.turn = 2; coop_chars_turn(); coop.turn = 1; coop_chars_turn();
    now_ms += 2000; launch("no lane known");
    return 0;
}
"""


def test_a_launch_is_not_the_saves_double_press_on_any_ball(tmp_path):
    """PAD-1045 (DoomWalrus666): "If the player has a 1x per ball ability, it is not able to be used after ball one".
    Godzilla's Action button is also its launch: a quick second press at ball 2's launch was the double press, so the
    save went at the shooter lane (emulator, LE 1.16) and the real one later did nothing; ball 1's pick took those
    presses. With `lane`, the presses count once the turn's ball is out of the lane, and a refused save is not spent."""
    main = MAIN[:MAIN.index("int main(void)")] + LANE_MAIN
    out = _run(tmp_path, main)
    assert "t1 0" in out
    assert "ball 1 launch 0 used 0" in out
    assert "ball 1 in play 10 used 1" in out
    assert "ball 1 again 0 used 1" in out                           # once a ball
    assert "ball 2 not served 0 used 0" in out                      # the turn's ball is not out yet
    assert "ball 2 launch 0 used 0" in out                          # the bug: this spent ball 2's save
    assert "ball 2 in play 10 used 1" in out
    assert "ball 3 launch 0 used 0" in out
    assert "ball 3 refused 0 used 0" in out                         # the game did not take it: still the ball's
    assert "ball 3 taken 10 used 1" in out
    assert "no lane known 10 used 1" in out                         # no lane in coop.cfg: as before, every press
    assert any("at a launch" in line and "not the save's" in line for line in out)


def test_coop_cfg_reads_the_shooter_lane():
    src = RUNTIME.read_text(encoding="utf-8")
    assert '"lane "' in R._lift(src, "static void coop_line(const char *s)")


@pytest.mark.skipif(not os.path.isfile(GZ_ELF), reason="no Godzilla LE 1.16 program here")
def test_coop_cfg_names_the_shooter_lane_beside_the_action_button():
    elf = open(GZ_ELF, "rb").read()
    assert CP.shooter_lane(elf) == 62
    lines = CP.character_lines(elf, {"pick": True, "list": [{"name": "A", "ability": "action_save"}]})
    assert lines[:5] == ["pick on", "pick_time 30", "left 60", "action 34", "lane 62"]

def test_the_pick_step_skips_the_taken_and_wraps_through_random(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static int coop_pick_step(int n, int at, int dir, unsigned taken)")
    main = r"""
#include <stdio.h>
@FN@
int main(void)
{
    printf("[%d %d %d %d %d]", coop_pick_step(3, 3, 1, 0), coop_pick_step(3, 2, 1, 0), coop_pick_step(3, 0, -1, 0),
           coop_pick_step(3, 3, 1, 3), coop_pick_step(3, 2, -1, 3));
    return 0;
}
""".replace("@FN@", fn)
    assert R._host_run(tmp_path, main) == "[0 3 3 2 3]"


def test_the_runtime_asks_for_a_pick_at_each_first_ball_and_reads_the_lines():
    src = RUNTIME.read_text(encoding="utf-8")
    change = R._lift(src, "static unsigned coop_change_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert change.index("coop.turn = next;") < change.index("coop_chars_turn();")
    add = R._lift(src, "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "coop_chars_begin();" in add and "coop_pick_open(1);" in add
    line = R._lift(src, "static void coop_line(const char *s)")
    for w in ('"character "', '"pick on"', '"left "', '"action "'):
        assert w in line
    assert "coop_chars_arm(e);" in R._lift(src, "static void coop_arm(void)")
    assert "coop_chars_tick();" in R._lift(src, "static void coop_tick(void)\n{")
    assert "if (coop_live) coop_edge(id, level, flags, pol);" in R._lift(src, "static void on_switch_edge(unsigned *r)")
    arm = R._lift(src, "static void coop_chars_arm(struct site *e)")
    assert "adj_wrap_arm()" in arm and "adj_coop_on = 1;" in arm      # PAD-1033: the one wrap, answered in turn


def test_character_lines_need_a_pick_and_characters():
    assert CP.character_lines(b"", None) == []
    assert CP.character_lines(b"", {"pick": False, "list": [{"name": "A"}]}) == []
    assert CP.character_lines(b"", {"pick": True, "list": []}) == []


def test_names_are_the_top_lines_words():
    assert CP.clean_name("  godzilla   1954 ") == "GODZILLA 1954"
    assert CP.clean_name("a|b") == "A B"
    assert len(CP.clean_name("x" * 60)) == CP.MAX_NAME


def test_the_project_keeps_its_characters_beside_its_awards(tmp_path):
    project = str(tmp_path)
    CP.save(project, True)
    CP.save_award(project, "score", on=False)
    chars = CP.save_characters(project, {"pick": True, "list": [{"name": "godzilla 1954", "ability": "longer_save"},
                                                                {"name": ""}, "junk"]})
    assert chars == {"pick": True, "time": CP.PICK_TIME,                    # round 6: an old ability is its bundle's powers
                     "list": [{"name": "GODZILLA 1954", "sub": "", "powers": CP.ABILITY_POWERS["longer_save"],
                               "header": "", "ability": "longer_save", "picture": ""}]}
    CP.save(project, False)                                          # unticked: the choices stay
    assert CP.load_characters(project) == chars
    assert CP.load_awards(project) == {"score": {"on": False}}
    CP.save_characters(project, {"pick": False, "list": []})
    assert CP.load_characters(project) == {"pick": False, "time": CP.PICK_TIME, "list": []}


def test_the_godzilla_customization_file_ships_beside_the_module():
    path = CP.presets()["godzilla"]
    got = CP.read_preset(path)
    assert got["game"] == "Godzilla"
    names = [c["name"] for c in got["characters"]["list"]]
    assert len(names) == 11 and len(set(names)) == 11               # the reporter's eleven abilities, one each
    assert all(len(n) <= CP.MAX_NAME for n in names)
    raw = json.load(open(path, encoding="utf-8"))
    assert all(set(c) <= {"name", "sub", "ability", "powers", "header", "picture"} for c in raw["characters"])
    assert all(c["powers"] and set(c["powers"]) <= {p[0] for p in CP.POWERS} for c in raw["characters"])   # round 6


def test_a_file_that_is_not_one_says_so(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(CP.CoopError):
        CP.read_preset(str(bad))
    with pytest.raises(CP.CoopError):
        CP.read_preset(str(tmp_path / "missing.json"))


@pytest.mark.skipif(not os.path.isfile(GZ_ELF), reason="no Godzilla LE 1.16 program here")
def test_godzillas_abilities_and_lines_read_off_its_program():
    elf = open(GZ_ELF, "rb").read()
    got = {a["key"]: a for a in CP.abilities(elf, "Godzilla")}
    assert got["longer_save"]["cfg"] == LONGER_SAVE                 # PAD-1075: the multiballs' saves, not the battles'
    assert got["action_save"]["cfg"] == "save:10"
    assert not got["heat_ray"]["cfg"] and got["heat_ray"]["why"]      # round 4: READY at the pick needs the port's object
    port = __import__("pinball_decryptor.plugins.stern.mode_project", fromlist=["read_port"]).read_port(
        str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))
    full = {a["key"]: a["cfg"] for a in CP.abilities(elf, "Godzilla", port["site"], port["value"])}
    assert full["heat_ray"] == "adj:195x50:4:30,count:heatlevel=3,count:heatspins=9,gift:315"   # PAD-1075: a train
    assert full["powerups"] == "boost:200,double:saucer,double:rampage,keep:djmult>=1"
    assert full["maser"] == "lit:maser=0x8000000,yes:maser,keep:magna=1,steps:powerline,double:saucer,gift:309"
    assert full["building"] == "adj:168=0,steps:building,double:spins,double:shield"
    assert full["ally"] == "gift:311,adj:199x200:40:120,gift:319,adj:200x200:5:20"      # ... Hedorah; round 6: Anguirus's save
    assert full["spot"] == ("spot:0x7f000,adj:212+10:30:80,adj:213+10:30:80,adj:214+10:30:80,adj:215+10:30:80,"
                            "adj:216+10:30:100,adj:218+10:30:100")
    assert CP.action_button(elf) == 34
    lines = CP.character_lines(elf, CP.read_preset(CP.presets()["godzilla"])["characters"])
    assert lines[:6] == ["pick on", "pick_time 30", "left 60", "action 34", "lane 62",
                         "character %s SHODAIGOJI|LONGER BALL SAVE, LONGER TIMERS" % LONGER_SAVE]
    assert all(len(ln.split(" ")[1]) <= CP.MAX_CFG for ln in lines if ln.startswith("character "))   # the runtime's token
    text = CP.cfg_text(elf, None, {"pick": True, "list": [{"name": "A", "ability": "heat_ray"}]},
                       sites=port["site"], values=port["value"])
    assert text.endswith("character adj:195x50:4:30,count:heatlevel=3,count:heatspins=9,gift:315 "
                         "A|HEAT RAY READY, EASIER HEAT RAY, TRAINS ALWAYS LIT\n")


def test_a_held_record_gives_back_the_harder_of_the_teams_and_plays(tmp_path):
    """Godzilla raises LIGHT BATTLE DIFFICULTY's record a notch after each battle: held at 0 for an easy teammate, it
    goes back to the team's own, or to what play made of it when that is harder."""
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static unsigned coop_cache_back(unsigned saved, unsigned wrote, unsigned now)")
    main = r"""
#include <stdio.h>
@FN@
int main(void)
{
    printf("[%u %u %u]", coop_cache_back(1, 0, 0), coop_cache_back(1, 0, 2), coop_cache_back(0, 0, 0));
    return 0;
}
""".replace("@FN@", fn)
    assert R._host_run(tmp_path, main) == "[1 2 0]"


def test_godzillas_own_abilities_need_their_port_sites():
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    from pinball_decryptor.plugins.stern import mode_project as MP
    elf = open(GZ_ELF, "rb").read()
    sites = sorted(MP.read_port(str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))["site"])
    values = MP.read_port(str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))["value"]
    got = {a["key"]: a["cfg"] for a in CP.abilities(elf, "Godzilla", sites, values)}
    assert got["battles"] == "adj:173=0" and got["building"].startswith("adj:168=0,steps:building")
    assert got["powerups"].startswith("boost:200") and got["ally"] == "gift:311,adj:199x200:40:120,gift:319,adj:200x200:5:20"
    bare = {a["key"]: a for a in CP.abilities(elf, "Godzilla")}         # a port without them: not offered, and why
    assert all(not bare[k]["cfg"] and bare[k]["why"] for k in ("battles", "building", "powerups", "ally"))


def test_the_godzilla_ports_name_the_character_sites():
    for key in ("godzilla_le-1.16", "godzilla_pro-1.16"):
        text = (RUNTIME.parent / "ports" / (key + ".port")).read_text(encoding="utf-8")
        for name in ("site coop_adj_changed", "site coop_boost", "site coop_cache_173", "site coop_cache_168",
                     "value coop_cache_173_at", "value coop_cache_168_at"):
            assert name in text, (key, name)


def test_jets_and_tanks_count_where_the_port_names_their_rules():
    """count:<name>+<n> raises a rule's count at the pick: Godzilla's jets through the pointer the game keeps to its
    rule (data coop_count_jets_rule), its tanks through the rule's game-start method (site coop_count_tanks)."""
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    from pinball_decryptor.plugins.stern import mode_project as MP
    elf = open(GZ_ELF, "rb").read()
    port = MP.read_port(str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))
    sites = sorted(set(port["site"]) | set(port["data"]))
    got = {a["key"]: a for a in CP.abilities(elf, "Godzilla", sites)}
    assert got["jets"]["cfg"] == "count:jets+4" and got["tanks"]["cfg"] == "count:tanks+4"
    bare = {a["key"]: a for a in CP.abilities(elf, "Godzilla")}
    assert not bare["jets"]["cfg"] and not bare["tanks"]["cfg"]
    for key in ("godzilla_le-1.16", "godzilla_pro-1.16"):
        text = (RUNTIME.parent / "ports" / (key + ".port")).read_text(encoding="utf-8")
        assert "data  coop_count_jets_rule" in text and "site coop_count_tanks" in text
    src = RUNTIME.read_text(encoding="utf-8")
    assert 'str_starts(p, "count:")' in R._lift(src, "static void coop_char_line(const char *s)")
    assert "coop_counts_give(&coop_ch[c]);" in R._lift(src, "static void coop_pick_close(const char *how)")


def test_the_pick_has_a_screen_for_each_character_and_random(tmp_path):
    project = str(tmp_path)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": [{"name": "GODZILLA 1954", "ability": "longer_save"},
                                                        {"name": "SHIN GODZILLA", "ability": ""}]})
    from PIL import Image
    pic = tmp_path / "mine.png"
    Image.new("RGBA", (300, 200), (10, 120, 10, 255)).save(pic)
    CP.save_picture(project, 1, str(pic))
    assert CP.load_characters(project)["list"][1]["picture"] == "coop/character_2.png"
    screens = CP.pick_screens(project, words_for=CP.words_for())
    assert [s["name"] for s in screens] == ["PadCoop_1", "PadCoop_2", "PadCoop_Random"]
    for sc in screens:                                                 # one finished card each, all words on it
        assert sc["art_rgba"].shape == (CP.CARD_SIZE[1], CP.CARD_SIZE[0], 4) and sc["words"] == " "
        assert (sc["x"], sc["y"]) == CP.CARD_AT
    px, py = 40 + 190, 84 + 150                                        # the portrait's middle on card 2: the picture
    assert tuple(screens[1]["art_rgba"][py, px][:3]) == (10, 120, 10)
    assert tuple(screens[0]["art_rgba"][py, px][:3]) != (10, 120, 10)  # card 1: the monogram plate
    assert CP.preview(project, None, CP.words_for(), 1)[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(CP.CoopError):
        CP.save_picture(project, 0, str(tmp_path / "x.txt")) if (tmp_path / "x.txt").write_text("no") else None
    CP.save_characters(project, {"pick": False, "list": [{"name": "A"}]})
    assert CP.pick_screens(project) == []


def test_co_op_alone_puts_the_pick_screens_in_the_hud_and_names_the_scene(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import scene_write as SW

    class Prof:
        label, game_dir, hud_scene, port = "Godzilla", "godzilla_le", "32e6ae28", ""

        def can(self, part):
            return part == "screen"

        def lcd(self, part):
            return "godzilla_le/assets/lcd/auto_loaded/32e6ae28"
    project = str(tmp_path / "p")
    os.makedirs(project)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": [{"name": "A", "ability": ""}]})
    got = {}
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "")
    monkeypatch.setattr(CP, "cfg_text", lambda *a, **k: "coop on\nbutton 59\n")
    monkeypatch.setattr(SW, "add_screens", lambda hud, screens, **k: (got.setdefault("names", [s["name"] for s in screens])
                                                                      and hud + b"+screens", []))
    result = MW.ModePlan(project=project, profile=Prof(), port="", build=None)
    MW.coop_into(result, b"", str(tmp_path / "scratch"), stock_hud=b"HUD", stock_font=b"")
    assert got["names"] == ["PadCoop_1", "PadCoop_Random", "PadCoopAward_1"]   # PAD-1028: + the award card
    (card, src), = result.replaced
    assert card == "godzilla_le/godzilla_le/assets/lcd/auto_loaded/32e6ae28/scene.radium"
    assert open(src, "rb").read() == b"HUD+screens"
    assert open(result.coop_file).read().endswith("screens 32e6ae28\naward_cards on\n")


def test_the_runtime_shows_the_picks_screen_and_reads_where_they_are():
    src = RUNTIME.read_text(encoding="utf-8")
    assert '"screens "' in R._lift(src, "static void coop_line(const char *s)")
    tick = R._lift(src, "static void coop_screens_tick(void)")
    assert '"PadCoop_%d"' in tick and '"PadCoop_Random"' in tick and "pm_show(coop_scr[want], 1);" in tick
    assert "coop_screens_tick();" in R._lift(src, "static void coop_chars_tick(void)")


def test_godzilla_offers_all_eleven_abilities_from_its_ports():
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    from pinball_decryptor.plugins.stern import mode_project as MP
    elf = open(GZ_ELF, "rb").read()
    for key in ("godzilla_le-1.16", "godzilla_pro-1.16"):
        port = MP.read_port(str(RUNTIME.parent / "ports" / (key + ".port")))
        got = {a["key"]: a["cfg"] for a in CP.abilities(elf, "Godzilla", set(port["site"]) | set(port["data"]),
                                                         port["value"])}
        assert all(got.values()), (key, [k for k, v in got.items() if not v])
        assert got["spot"].startswith("spot:0x7f000,adj:212+10") and got["tier2"] == "unlock:334"
        assert got["addball"] == "addball:1" and got["maser"].startswith("lit:maser=0x8000000,yes:maser")
        assert got["longer_save"] == LONGER_SAVE
        assert got["bridge"] == "adj:176=0,double:tanks,double:jets"
    sets = [tuple(c["powers"]) for c in CP.read_preset(CP.presets()["godzilla"])["characters"]["list"]]
    assert len(set(sets)) == 11 and all(set(s) <= {p[0] for p in CP.POWERS} for s in sets)   # eleven different
    assert {"addball", "maser_lit", "easy_bridge"} <= {k for s in sets for k in s}   # round 2: the three he asked for


def test_godzillas_set_is_doomwalrus666s_list():
    """PAD-1075: his spreadsheet - each character's name, its film under it and its ability, in his order."""
    got = [(c["name"], c["sub"], c["ability"], c["powers"])
           for c in CP.read_preset(CP.presets()["godzilla"])["characters"]["list"]]
    B = CP.ABILITY_POWERS
    assert got == [                        # round 6: each a list of powers; his two asks of 2026-11-08 on SOSHINGEKI and BIOGOJI
        ("SHODAIGOJI", "Godzilla (1954)", "longer_save", B["longer_save"]),
        ("KINGOJI", "Godzilla vs King Kong (1962)", "powerups", B["powerups"]),
        ("SOSHINGEKI", "Destroy All Monsters (1968)", "ally", ["ally_lit", "rodan_x2", "hedorah", "addball_save_x2"]),
        ("MEGAROGOJI", "Godzilla vs Mechagodzilla (1974)", "bridge", B["bridge"]),
        ("84GOJI", "Return of Godzilla (1984)", "addball", ["addball"]),
        ("BIOGOJI", "Godzilla vs Biollante (1989)", "", B["maser"] + ["perk_loop_2x"]),
        ("BATOGOJI", "Godzilla and Mothra: The Battle for Peace (1992)", "building", B["building"]),
        ("DESUGOJI", "Godzilla vs. Destoroyah (1995)", "spot", ["spot", "battle_timers_10"]),
        ("MIREGOJI", "Godzilla 2000: Millennium (1999)", "action_save", ["action_save"]),
        ("SOKOGEKIGOJI", "Godzilla, Mothra and King Ghidorah: Giant Monsters All-Out Attack (2001)", "heat_ray",
         ["heat_ray", "train_lit"]),
        ("FINALGOJI", "Godzilla: Final Wars (2004)", "tier2", ["tier2"])]
    words = {a[0]: a[1] for a in CP.ABILITIES}
    assert words["ally"] == "AN ALLY EVERY BALL, LONGER RODAN, HEDORAH STARTS"
    assert words["maser"] == "MASER, MAGNA GRAB, AND DESTRUCTION JACKPOT LIT, DOUBLE POWERLINES AND POP HITS"
    assert words["building"] == "BUILDING AND MECHA MULTIBALLS"                  # his later message: pops to BioGoji
    assert words["spot"] == "SPOT A BATTLE SHOT, LONGER BATTLE TIMERS"
    assert words["heat_ray"] == "HEAT RAY READY, EASIER HEAT RAY, TRAINS ALWAYS LIT"


def test_no_character_asks_the_runtime_for_more_than_it_keeps():
    """PAD-1075: coop_char_line keeps two of each of count/keep/steps/lit/yes/double, four gifts and COOP_CHAR_ADJ
    adjustments, and drops the rest without a word - BatoGoji's third double: (saucer) was never held. Every ability
    of the shipped set, on both Godzilla builds, fits."""
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    import re
    from pinball_decryptor.plugins.stern import mode_project as MP
    src = RUNTIME.read_text(encoding="utf-8")
    line = R._lift(src, "static void coop_char_line(const char *s)")
    defs = {k: int(n) for k, n in re.findall(r"#define (COOP_CHAR_ADJ|COOP_GIFTS|COOP_CH_N|COOP_CH_DBL) (\d+)", src)}
    names = dict(re.findall(r'str_starts\(p, "(\w+):"\) && c->n_\w+ < (COOP_\w+)', line))   # round 6: by constant
    assert {"count", "keep", "steps", "lit", "yes", "double", "adj"} <= set(names)
    caps = {k: defs[v] for k, v in names.items()}
    caps["gift"] = defs["COOP_GIFTS"]
    assert caps == CP.LIMITS                                          # the app refuses what the runtime would drop
    assert int(re.search(r"char tok\[(\d+)\]", line).group(1)) == CP.MAX_CFG + 1
    elf = open(GZ_ELF, "rb").read()
    for key in ("godzilla_le-1.16", "godzilla_pro-1.16"):
        port = MP.read_port(str(RUNTIME.parent / "ports" / (key + ".port")))
        sites, values = set(port["site"]) | set(port["data"]), port["value"]
        parts = {p["key"]: p for p in CP.powers(elf, "Godzilla", sites, values)}
        cfgs = [(a["key"], a["cfg"]) for a in CP.abilities(elf, "Godzilla", sites, values)]
        for c in CP.read_preset(CP.presets()["godzilla"])["characters"]["list"]:
            got = CP.compose(c["powers"], parts)
            assert got["cfg"] and not got["missing"] and not got["over"], (key, c["name"], got)
            cfgs.append((c["name"], got["cfg"]))
        for name, cfg in cfgs:
            kinds = [part.split(":")[0] for part in cfg.split(",") if part]
            for kind, cap in caps.items():
                assert kinds.count(kind) <= cap, (key, name, kind, cfg)
            assert len(cfg) <= CP.MAX_CFG


def test_a_long_badge_and_line_stay_on_the_card():
    """PAD-1075: the badge shrinks to the card's width, and a three-sentence line takes three smaller lines, not
    two cut with ..."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    f, lines, step = CP._card_lines(d, CP.CARD_LINES["ally"], 760, 1)
    assert lines and not lines[-1].endswith("...") and len(lines) <= 3
    f2, short, _ = CP._card_lines(d, CP.CARD_LINES["tier2"], 760, 1)
    assert len(short) == 1 and f2.size == 27
    png = CP.preview(None, {"pick": True, "list": [{"name": "BIOGOJI", "sub": CP.clean_sub("x" * 90),
                                                     "ability": "maser"}]},
                     {"maser": dict((a[0], a[1]) for a in CP.ABILITIES)["maser"]}, 0)
    assert png[:4] == b"\x89PNG"
    assert len(CP.clean_sub("x" * 90)) == CP.MAX_SUB == 80


def test_spot_and_unlock_read_from_coop_cfg():
    src = RUNTIME.read_text(encoding="utf-8")
    line = R._lift(src, "static void coop_char_line(const char *s)")
    assert 'str_starts(p, "spot:")' in line and 'str_starts(p, "unlock:")' in line
    wrap = R._lift(src, "static unsigned coop_adj_answer(unsigned id, unsigned own)\n{")
    assert "c->unlock_adj == id && pm_in_game() && (!c->unlock_rules || (coop_started[coop.turn] & c->unlock_rules))" in wrap
    turn = R._lift(src, "static void coop_chars_turn(void)")
    assert "coop_gift(&coop_ch[coop_pick_of[coop.turn]]);" in turn            # round 3: an ally at every turn
    spot = R._lift(src, "static int coop_spot(const struct coop_char *c)")
    assert 'fn("shot_dispatch")' in spot and "lit & (~lit + 1)" in spot


def test_tags_name_what_sets_a_character_apart():
    names = ["GODZILLA 1954", "GODZILLA GMK", "DESTROY ALL MONSTERS", "KING KONG VS GODZILLA", "GODZILLA VS MECHAGODZILLA"]
    assert [CP.tag_of(n, names) for n in names] == ["1954", "GMK", "DAM", "KK", "MECHA"]
    assert CP.theme_of({"title": "choose your godzilla", "accent": "#38c8ff", "bogus": 1}) == {
        "title": "CHOOSE YOUR GODZILLA", "accent": "#38c8ff", "accent2": CP.THEME["accent2"]}
    preset = CP.read_preset(CP.presets()["godzilla"])["characters"]
    assert preset["theme"]["title"] == "CHOOSE YOUR GODZILLA"
    assert set(CP.CARD_LINES) == {a[0] for a in CP.ABILITIES}         # every ability has the player's words


def test_a_folder_of_pictures_named_after_the_characters_fills_them_in(tmp_path):
    """The set a game's owners share (the Discord bundle): godzilla_1954.png ... one per character."""
    from PIL import Image
    project = str(tmp_path / "p")
    os.makedirs(project)
    CP.save_characters(project, {"pick": True, "list": [{"name": "GODZILLA 1954", "ability": ""},
                                                        {"name": "KING KONG VS GODZILLA", "ability": ""},
                                                        {"name": "SHIN GODZILLA", "ability": ""}]})
    folder = tmp_path / "pics"
    folder.mkdir()
    Image.new("RGB", (40, 60), (200, 10, 10)).save(folder / "godzilla_1954.png")
    Image.new("RGB", (40, 60), (10, 200, 10)).save(folder / "King_Kong_vs_Godzilla.JPG")
    (folder / "notes.txt").write_text("x")
    assert CP.picture_file_name("KING KONG VS GODZILLA") == "king_kong_vs_godzilla"
    assert CP.pictures_from_folder(project, str(folder)) == (2, ["SHIN GODZILLA"])
    got = CP.load_characters(project)["list"]
    assert got[0]["picture"] == "coop/character_1.png" and got[1]["picture"] == "coop/character_2.jpg"
    assert not got[2]["picture"]
    with pytest.raises(CP.CoopError):
        CP.pictures_from_folder(project, str(tmp_path / "missing"))


def test_round_two_kinds_read_from_coop_cfg(tmp_path):
    """addball:<n>, yes:<name>, double:<name> (DoomWalrus666's second list): parsed, and a doubled count gets one more
    for each rise of one the game makes while its character is up."""
    src = RUNTIME.read_text(encoding="utf-8")
    line = R._lift(src, "static void coop_char_line(const char *s)")
    for w in ('"addball:"', '"yes:"', '"double:"', '"lit:"'):
        assert w in line
    assert "coop_double_tick();" in R._lift(src, "static void coop_chars_tick(void)")
    assert "coop_lit_tick();" in R._lift(src, "static void coop_chars_tick(void)")
    lit = R._lift(src, "static void coop_lit_tick(void)")
    assert "f[0] = (unsigned)(have | m);" in lit and "have &= ~coop_lit[i].mask;" in lit
    assert 'pm_multiball_add(c->addball, 0)' in R._lift(src, "static void coop_chars_tick(void)")
    arm = R._lift(src, "static void coop_chars_arm(struct site *e)")
    assert '"coop_yes_%s"' in arm and "the %s count is doubled" in arm
    tick = R._lift(src, "static void coop_double_tick(void)")
    assert "now > coop_dbl_last[i] && now - coop_dbl_last[i] <= 50u" in tick and "coop_count_put(i, f, now + rise);" in tick
    assert "now < coop_dbl_last[i]" in tick and "coop_count_put(i, f, now);" in tick   # round 4: a count that counts DOWN


# ---- round 6 (David, 2026-11-08): the owner composes a character's powers in the app ------------------------------

def _le_parts():
    from pinball_decryptor.plugins.stern import mode_project as MP
    elf = open(GZ_ELF, "rb").read()
    port = MP.read_port(str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))
    return {p["key"]: p for p in CP.powers(elf, "Godzilla", set(port["site"]) | set(port["data"]), port["value"])}


def test_a_character_is_a_list_of_powers_composed_into_one_ability():
    """DoomWalrus666: Loop Value 2X on BioGoji, Anguirus's longer save on the ally character; David: the end user
    customizes this in the app, nothing hard-coded. Every power is one thing the runtime does; a character's list is
    joined, each token once, the perks folded into one keep:perks|= mask."""
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    parts = _le_parts()
    assert len(parts) == len(CP.POWERS) and all(p["cfg"] for p in parts.values())   # Godzilla LE has every power
    assert {p[1] for p in CP.POWERS} == set(CP.POWER_GROUPS)
    got = CP.compose(["maser_lit", "saucer_x2", "perk_loop_2x", "perk_rodan_15", "saucer_x2", "extra_ball_3"], parts)
    assert got["cfg"] == "lit:maser=0x8000000,yes:maser,double:saucer,eb:3,keep:perks|=0x100100"
    assert got["words"] == "MASER LIT, SAUCER MULTIBALL, LOOP VALUE 2X, RODAN +15 SECONDS, SAUCER MULTIBALL, EXTRA BALL AFTER BALL 3"
    assert got["line"].startswith("Maser lit while you are up. Pop hits count twice")
    assert got["missing"] == [] and got["over"] == [] and got["why"] == ""
    # a power the card cannot have is left out and named; the first one missing is the whole ability missing
    bare = {p["key"]: p for p in CP.powers(open(GZ_ELF, "rb").read(), "Godzilla")}
    got = CP.compose(["action_save", "perk_loop_2x", "ally_lit"], bare)
    assert got["cfg"] == "save:10" and got["missing"] == ["perk_loop_2x", "ally_lit"]
    got = CP.compose(["perk_loop_2x", "action_save"], bare)
    assert got["cfg"] == "" and got["why"] == CP.NO_SITE % "Godzilla"
    assert CP.compose(["no_such"], parts)["why"] == CP.NO_POWER % "no_such"
    # the bundles are the old abilities, token for token
    for key, _w, _d, keys in CP.ABILITIES:
        assert CP.compose(keys, parts)["cfg"] == {a["key"]: a["cfg"] for a in CP.abilities(
            open(GZ_ELF, "rb").read(), "Godzilla", set(parts) and _le_sites(), _le_values())}[key]


def _le_sites():
    from pinball_decryptor.plugins.stern import mode_project as MP
    port = MP.read_port(str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))
    return set(port["site"]) | set(port["data"])


def _le_values():
    from pinball_decryptor.plugins.stern import mode_project as MP
    return MP.read_port(str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))["value"]


def test_too_many_parts_of_a_kind_are_named_as_over_the_runtimes_room():
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    parts = _le_parts()
    got = CP.compose(["ball_save_x2", "multiball_saves_x2", "battle_timers_10", "o2_x2", "rodan_x2", "addball_save_x2",
                      "heat_ray"], parts)
    assert got["over"] == [] and got["cfg"].count("adj:") == 22        # every adj power Godzilla has fits the room (24)
    parts["x"] = {"cfg": ",".join("adj:%d=1" % i for i in range(25)), "words": "X", "line": "x", "why": ""}
    assert CP.compose(["x"], parts)["over"] == ["adj"]                 # one more would be dropped by the runtime
    parts["y"] = {"cfg": ",".join("count:c%d+1" % i for i in range(80)), "words": "Y", "line": "y", "why": ""}
    assert CP.compose(["y"], parts)["over"] == ["count", "length"]
    got = CP.compose(["ally_lit", "hedorah", "train_lit", "dj_lit"], parts)
    assert got["over"] == [] and got["cfg"].count("gift:") == 4


def test_a_saved_character_keeps_its_powers_and_its_own_header(tmp_path):
    project = str(tmp_path)
    chars = CP.save_characters(project, {"pick": True, "list": [
        {"name": "biogoji", "sub": "Godzilla vs Biollante (1989)", "powers": ["maser_lit", "perk_loop_2x", "maser_lit", "nope"],
         "header": "loops and|maser"},
        {"name": "old", "ability": "tier2"}, {"name": "none"}]})
    a, b, c = chars["list"]
    assert a["powers"] == ["maser_lit", "perk_loop_2x"] and a["header"] == "LOOPS AND MASER" and a["ability"] == ""
    assert b["powers"] == ["tier2"] and b["ability"] == "tier2" and b["header"] == ""
    assert c["powers"] == [] and c["ability"] == ""
    assert CP.load_characters(project) == chars
    assert CP.character_words(a) == "LOOPS AND MASER"                 # its own header over its powers' words
    assert CP.character_words(dict(a, header="")) == "MASER LIT, LOOP VALUE 2X"
    assert CP.character_words(dict(a, header=""), {"maser_lit": "MASER LIT"}) == "MASER LIT"   # a power the card lacks: left out
    assert CP.character_line(b) == "Every battle is open to you, tier 2 included."
    assert CP.character_words(c) == "" and CP.character_line(c) == ""


def test_character_lines_carry_the_composed_powers_and_header():
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    elf = open(GZ_ELF, "rb").read()
    lines = CP.character_lines(elf, {"pick": True, "list": [
        {"name": "BIOGOJI", "powers": ["maser_lit", "perk_loop_2x"], "header": "LOOPS AND MASER"},
        {"name": "EB", "powers": ["extra_ball_3", "perk_loop_2x"]},
        {"name": "PLAIN", "powers": []}]}, _le_sites(), _le_values())
    assert lines[5:] == ["character lit:maser=0x8000000,yes:maser,keep:perks|=0x100 BIOGOJI|LOOPS AND MASER",
                         "character eb:3,keep:perks|=0x100 EB|EXTRA BALL AFTER BALL 3, LOOP VALUE 2X",
                         "character - PLAIN|"]
    assert CP.words_for()["perk_loop_2x"] == "LOOP VALUE 2X"


def test_the_godzilla_ports_name_the_perks_word_and_the_extra_ball_award():
    for key in ("godzilla_le-1.16", "godzilla_pro-1.16"):
        text = (RUNTIME.parent / "ports" / (key + ".port")).read_text(encoding="utf-8")
        for name in ("site coop_eb_award", "value coop_keep_perks_obj", "value coop_keep_perks_at      0x44"):
            assert name in text, (key, name)
