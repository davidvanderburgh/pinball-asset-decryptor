"""PAD-1224 (DoomWalrus666): ENHANCED STANDARD - "standard play but with the ability for players to choose a character
with special abilities. They would each have their own scores and gameplay progress as normal, nothing shared" - and
"Also please add a 3v1 mode" (pad_mode_runtime.c "PAD-1224", "TEAM 3V1").

The runtime's wraps are lifted verbatim and run against PAD-1017's model of the framework's own player change and add
player (test_pad1017_coop_turns.py), as test_pad1042_team_play.py runs the team games."""
from tests import test_pad1017_coop_turns as T
from tests import test_pad1042_team_play as TP
from tests import test_spike2_mode_roster as R

RUNTIME = T.RUNTIME


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _round_3v1(ball, order):
    # team 1 (players 1, 3, 4) is the game's player 1, team 2 (player 2) its player 2
    return ["ball %d player %d game player %d" % (ball, p, 2 if p == 2 else 1) for p in order]


def test_three_against_one_the_lone_player_plays_every_round(tmp_path):
    out = TP._game(tmp_path, 4, mode=5)                     # CO-OP PLAY's TEAM PLAY 3 VS 1: one Start adds all four
    assert TP._head(out) == "teams 4: 3+1 game players 2 board 5"           # the TEAM 3V1 board
    assert TP._ups(out) == sum((_round_3v1(b, (1, 2, 3, 2, 4, 2)) for b in (1, 2, 3)), [])
    assert TP._over(out) == "over after 18 balls, the game's end sees 2 player(s)"   # both teams' scores at its end
    assert "fifth 0" in out
    assert "teams: Start - both teams are full (4 players, Team 3v1)" in out


def test_three_against_one_with_fewer_players(tmp_path):
    out = TP._game(tmp_path, 3, mode=5)                     # three: players 1 and 3 against player 2
    assert TP._head(out) == "teams 3: 2+1 game players 2 board 5"
    assert TP._ups(out) == sum((_round_3v1(b, (1, 2, 3, 2)) for b in (1, 2, 3)), [])
    out = TP._game(tmp_path, 2, mode=5)                     # two: a team each
    assert TP._head(out) == "teams 2: 1+1 game players 2 board 5"


def test_an_extra_ball_in_three_against_one_stays_with_its_player(tmp_path):
    out = TP._game(tmp_path, 4, extra_at=5, mode=5)         # player 4's turn (the ball's third round) earns one
    ups = TP._ups(out)
    assert ups[4] == ups[5] == "ball 1 player 4 game player 1"
    assert ups[6] == "ball 1 player 2 game player 2"


def test_the_layout_names_and_board(tmp_path):
    src = _src()
    fns = "\n".join(R._lift(src, s) for s in (
        "static unsigned coop_team_player(unsigned team, unsigned size, unsigned round)",
        "static unsigned coop_team_of(unsigned p)",
        "static unsigned coop_team_player_in(unsigned kind, unsigned team, unsigned size, unsigned round)",
        "static unsigned coop_team_of_in(unsigned kind, unsigned p)",
        "static unsigned team_kind_most(unsigned kind)",
        "static int coop_join_words(unsigned n, unsigned step, char *out, unsigned cap)\n{",
        "static int coop_join_words_in(unsigned kind, int standard, unsigned n, unsigned step, char *out, unsigned cap)",
        "static void coop_board_name(char *out, unsigned n)"))
    main = "#include <stdio.h>\n#define pm_snprintf snprintf\n" + fns + r"""
static void says(unsigned kind, int standard, unsigned n)
{
    char w[40];
    unsigned k;
    for (k = 0; coop_join_words_in(kind, standard, n, k, w, sizeof w); k++) printf("%s|", w);
    printf("\n");
}
int main(void)
{
    char w[40];
    unsigned r, p;
    for (r = 1; r <= 4; r++) printf("%u", coop_team_player_in(5, 1, 3, r));
    printf(" ");
    for (r = 1; r <= 2; r++) printf("%u", coop_team_player_in(5, 2, 1, r));
    printf(" ");
    for (r = 1; r <= 4; r++) printf("%u", coop_team_player_in(4, 1, 2, r));   /* 2v2 as it was */
    printf(" ");
    for (p = 1; p <= 4; p++) printf("%u", coop_team_of_in(5, p));
    printf(" ");
    for (p = 1; p <= 4; p++) printf("%u", coop_team_of_in(4, p));
    printf(" ");
    for (p = 0; p <= 6; p++) printf("%u", team_kind_most(p));
    coop_board_name(w, 5);
    printf(" %s\n", w);
    says(5, 0, 4);
    says(5, 0, 3);
    says(4, 0, 4);
    says(0, 1, 1);
    return 0;
}
"""
    out = R._host_run(tmp_path, main).splitlines()
    assert out[0] == "1341 22 1313 1211 1212 0003440 TEAM 3V1"
    assert out[1] == "4 PLAYERS ADDED|TEAM 1: P1, P3, P4|TEAM 2: P2|"          # 19 fit
    assert out[2] == "3 PLAYERS ADDED|TEAM 1: P1, P3|TEAM 2: P2|"
    assert out[3] == "4 PLAYERS ADDED|TEAM 1: P1 AND P3|TEAM 2: P2 AND P4|"       # 2v2 as it was
    assert out[4] == "ENHANCED STANDARD|START ADDS PLAYERS|EACH PICKS A HERO|"
    assert all(len(w) <= 19 for l in out[1:] for w in l.split("|"))


STD_MAIN = T.PRELUDE + r"""
static void std_game(unsigned humans, int extra_at)
{
    unsigned k, balls = 0;
    memset(&coop, 0, sizeof coop);
    bytes[0] = 1; bytes[1] = 1; players = 1; extra = 0; game_no++; board = 99; button = 0; teams_on = 0;
    credits = 99;
    /* the start menu's ENHANCED STANDARD (on_team_dispatch's kind 2) */
    coop.game = chg_game_now() + 1; coop.standard = 1; coop.n = players; coop.turn = 1; coop.round = 1;
    for (k = 1; k < humans; k++) printf("start %u\n", coop_add_wrap(0, 0, 0, 0));
    printf("game players %u players %u board %u\n", players, coop.n, board);
    for (;;) {
        printf("up ball %u player %u game player %u\n", bytes[1], coop.turn, bytes[0]);
        if (shown_turn != coop.turn && balls) printf("SCREEN SAYS %u\n", shown_turn);
        balls++;
        if ((int)balls == extra_at) extra = 1;
        if (!coop_change_wrap(0, 0, 0, 0)) break;
    }
    printf("over after %u balls, the game's end sees %u player(s)\n", balls, players);
    printf("fifth %u\n", coop_add_wrap(0, 0, 0, 0));
}
int main(int argc, char **argv)
{
    std_game((unsigned)(argv[1][0] - '0'), argc > 2 ? argv[2][0] - '0' : 0);
    return 0;
}
"""


def _std(tmp_path, humans, extra_at=0):
    sub = tmp_path / ("s%d_%d" % (humans, extra_at))
    sub.mkdir()
    out = R._host_run(sub, STD_MAIN.replace("@FNS@", T.lifted()), args=(str(humans), str(extra_at))).splitlines()
    assert not any(l.startswith("SCREEN SAYS") for l in out)
    return out


def test_enhanced_standard_is_the_games_own_competing_game(tmp_path):
    out = _std(tmp_path, 4)
    # each Start is the game's own add (a competing player: the game counts them all), no co-op board
    assert "game players 4 players 4 board 99" in out
    assert [l for l in out if l.startswith("enhanced standard: player")][:3] == [
        "enhanced standard: player %d joins (their own game; a character at their first ball)" % p for p in (2, 3, 4)]
    # the game's own turns, each its own player, and the one up is the game's player up
    ups = [l[len("up "):] for l in out if l.startswith("up ")]
    assert ups == ["ball %d player %d game player %d" % (b, p, p) for b in (1, 2, 3) for p in (1, 2, 3, 4)]
    assert "over after 12 balls, the game's end sees 4 player(s)" in out    # four players at its end, not one
    assert "fifth 0" in out


def test_enhanced_standard_extra_ball_and_two_players(tmp_path):
    out = _std(tmp_path, 2, extra_at=2)                     # player 2 earns an extra ball on ball 1
    ups = [l[len("up "):] for l in out if l.startswith("up ")]
    assert ups[:4] == ["ball 1 player 1 game player 1", "ball 1 player 2 game player 2",
                       "ball 1 player 2 game player 2", "ball 2 player 1 game player 1"]
    assert "enhanced standard: ball 1, player 2 done - an extra ball: player 2, ball 1" in out


def test_enhanced_standard_leaves_the_game_its_own():
    src = _src()
    kinds = R._lift(src, "static unsigned team_menu_kinds(unsigned *kinds)\n{")
    assert "if (!coop_classic()) kinds[n++] = 2u;" in kinds                  # Enhanced only
    disp = R._lift(src, "static void on_team_dispatch(unsigned *r)\n{")
    assert "if (kind == 2u) {" in disp and "coop.standard = 1;" in disp and "coop.n = *coop_players_byte;" in disp
    assert "coop_awards_begin" not in disp.split("if (kind == 2u) {")[1].split("return;\n    }")[1]
    tick = R._lift(src, "static void coop_tick(void)\n{")
    assert "!coop.standard && pm_in_game()) coop_scores_same(n);" in tick    # no scores mirrored
    first = R._lift(src, "static unsigned coop_first_ball_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "coop.standard ? ball" in first                                   # each player's own first-ball setup
    show = R._lift(src, "static void coop_turn_show(void)")
    assert "(coop.n == 1 && !coop.teams) || coop.standard" in show           # the game's own top line
    panel = R._lift(src, "static unsigned coop_panel_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "!coop.teams && !coop.standard" in panel
    hand = R._lift(src, "static void hand_records(unsigned p, int lv)")
    assert "coop_teammates() >= 2 && !coop.standard) return;" in hand        # each player's own handicap records
    up = R._lift(src, "static const struct coop_char *coop_char_up(void)")
    assert "c = coop_pick_of[coop.turn];" in up                              # the player up's character
    line = R._lift(src, "static void coop_line(const char *s)")
    assert '"teams 3v1")) { coop.teams_always = 5;' in line
