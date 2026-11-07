"""PAD-1017: co-op play's teammate turns and teammates joining (pad_mode_runtime.c "co-op play").

The runtime's wraps are lifted verbatim and run against a model of the framework's own player change and add player,
as Godzilla LE 1.16 has them (0x338950 / 0x338790): an extra ball keeps the player and the ball; otherwise the next
player, and past the last one the next ball while it is below the balls per game, else the game's end."""
import pathlib

from tests import test_spike2_mode_roster as R

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"

MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
static unsigned char bytes[2], players = 1, extra;   /* the player up, the ball; the count; extra balls earned */
static unsigned bpg = 3, game_no = 1, button = 0, max_players = 4;
static void say(const char *f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); printf("\n"); }
static unsigned chg_game_now(void) { return game_no; }
static int coop_button_held(void) { return button; }
static struct { int on; unsigned button, game, n, turn; } coop;
static volatile unsigned char *coop_ball_byte = &bytes[1], *coop_players_byte = &players;
static unsigned shown_turn, board;                   /* what the screen and the board were told last */
static void coop_scores_mark(unsigned n) { board = n; }
static void coop_turn_show(void) { shown_turn = coop.turn; }
static void coop_scores_same(unsigned n) { (void)n; }
static void coop_awards_begin(void) {}                /* PAD-1028: the awards (test_pad1028_coop_awards.py) */
static void coop_awards_read(unsigned t) { (void)t; }
static void coop_awards_end(unsigned n) { (void)n; }
static struct { int open; unsigned who; } pk;               /* PAD-1031: the characters' pick (test_pad1031_coop_characters.py) */
static void coop_pick_say(void) {}
static void coop_pick_open(unsigned t) { (void)t; }
static void coop_chars_begin(void) {}
static void coop_chars_turn(void) {}
static void coop_cache_let_go(void) {}
static void coop_cards_show(unsigned n) { (void)n; }    /* PAD-1028 round 2: the awards on the characters' cards */
static int coop_switched_on(void) { return 1; }          /* round 2: CO-OP PLAY says On (test_pad1017_coop_lines.py) */
/* the framework's own, modelled */
static unsigned game_change(unsigned r0, unsigned r1, unsigned r2, unsigned r3)
{
    unsigned next;
    if (extra) { extra--; return 1; }
    next = bytes[0] + 1u;
    if (next <= players) { bytes[0] = (unsigned char)next; return 1; }
    if (bytes[1] >= bpg) return 0;
    bytes[1]++;
    bytes[0] = 1;
    return 1;
}
static unsigned game_add(unsigned r0, unsigned r1, unsigned r2, unsigned r3)
{
    if (players >= max_players) return 0;
    players++;
    return 1;
}
static unsigned (*coop_change_game)(unsigned, unsigned, unsigned, unsigned) = game_change;
static unsigned (*coop_add_game)(unsigned, unsigned, unsigned, unsigned) = game_add;
@FNS@
static void play(unsigned team, int extra_at)
{
    unsigned k, balls = 0;
    memset(&coop, 0, sizeof coop);
    bytes[0] = 1; bytes[1] = 1; players = 1; extra = 0; game_no++;
    button = 1;
    for (k = 1; k < team; k++) coop_add_wrap(0, 0, 0, 0);
    button = 0;
    printf("team %u players %u board %u\n", coop.n, players, board);
    for (;;) {
        printf("up ball %u teammate %u player %u\n", bytes[1], coop.turn ? coop.turn : 1, bytes[0]);
        if (shown_turn != coop.turn) printf("SCREEN SAYS %u\n", shown_turn);
        balls++;
        if ((int)balls == extra_at) extra = 1;
        if (!coop_change_wrap(0, 0, 0, 0)) break;
    }
    printf("over after %u balls, the game's end sees %u player(s)\n", balls, players);
}
int main(void)
{
    play(2, 0);
    play(4, 0);
    play(3, 4);       /* teammate 1 earns an extra ball on its second ball */
    /* a plain Start: a competing player, as stock; then a held button takes no teammate */
    memset(&coop, 0, sizeof coop); players = 1; game_no++;
    button = 0; coop_add_wrap(0, 0, 0, 0);
    button = 1; coop_add_wrap(0, 0, 0, 0);
    printf("competing players %u team %u\n", players, coop.n);
    /* a full team: the fifth Start adds no one */
    memset(&coop, 0, sizeof coop); players = 1; game_no++; button = 1;
    coop_add_wrap(0, 0, 0, 0); coop_add_wrap(0, 0, 0, 0); coop_add_wrap(0, 0, 0, 0);
    printf("full %u\n", coop_add_wrap(0, 0, 0, 0));
    /* the next game forgets the team */
    game_no++;
    printf("next game team %u\n", coop_teammates());
    return 0;
}
"""


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in (
        "static unsigned coop_next_turn(unsigned n, unsigned turn, unsigned before, unsigned after, unsigned down)",
        "static unsigned coop_teammates(void)",
        "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)",
        "static unsigned coop_change_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)"))
    return R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()


def _turns(out, team):
    start = out.index(next(l for l in out if l.startswith("team %d " % team)))
    assert out[start].endswith("board %d" % team)                # the team's own board, by its size
    end = next(i for i in range(start, len(out)) if out[i].startswith("over after"))
    return [l for l in out[start:end] if l.startswith("up ")], out[end]


def test_each_teammate_plays_each_ball_and_the_game_ends_after_the_last(tmp_path):
    out = _run(tmp_path)
    # the game counts the team (a score panel each) but plays one player: player 1 is up every ball (below)
    assert "team 2 players 2 board 2" in out and "team 4 players 4 board 4" in out
    assert not any(l.startswith("SCREEN SAYS") for l in out)   # the screen names the teammate up, every ball
    ups, over = _turns(out, 2)
    assert ups == ["up ball %d teammate %d player 1" % (b, t) for b in (1, 2, 3) for t in (1, 2)]
    assert over == "over after 6 balls, the game's end sees 1 player(s)"
    ups, over = _turns(out, 4)
    assert ups == ["up ball %d teammate %d player 1" % (b, t) for b in (1, 2, 3) for t in (1, 2, 3, 4)]
    assert over == "over after 12 balls, the game's end sees 1 player(s)"


def test_an_extra_ball_stays_with_the_teammate_who_earned_it(tmp_path):
    ups, over = _turns(_run(tmp_path), 3)
    want = ["up ball 1 teammate %d player 1" % t for t in (1, 2, 3)]
    want += ["up ball 2 teammate 1 player 1", "up ball 2 teammate 1 player 1",      # its extra ball
             "up ball 2 teammate 2 player 1", "up ball 2 teammate 3 player 1"]
    want += ["up ball 3 teammate %d player 1" % t for t in (1, 2, 3)]
    assert ups == want and over == "over after 10 balls, the game's end sees 1 player(s)"


def test_plain_start_adds_a_competing_player_and_a_team_tops_out_at_four(tmp_path):
    out = _run(tmp_path)
    assert "competing players 3 team 0" in out             # no teammates in a game of competing players
    assert "full 0" in out
    assert "next game team 0" in out
    assert "co-op: Start - the team is full (4)" in out


def test_the_card_takes_the_whole_gate_and_arms_coop():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "!attract_wanted() && !coop_wanted()" in src
    arm = R._lift(src, "static void coop_arm(void)")
    assert 'hook_wrap(fn("coop_add_player")' in arm and 'fn("coop_player_change"), (void *)coop_change_wrap' in arm
    assert "coop_arm();" in src
