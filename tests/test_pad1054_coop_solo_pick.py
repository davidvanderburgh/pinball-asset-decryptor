"""PAD-1054: a one-player game started with the right flipper held picks a character (pad_mode_runtime.c "co-op play").

DoomWalrus666: "If right flipper is held when start button is pressed, single player should be able to select a
character with an ability as well ... As long as co-op or one of the team modes is active in the service menu". The
runtime makes that game a co-op game of ONE; the wraps are lifted verbatim and run against PAD-1017's model of the
framework's own player change and add player (test_pad1017_coop_turns.py)."""
from tests import test_pad1017_coop_turns as T
from tests import test_spike2_mode_roster as R

RUNTIME = T.RUNTIME

MAIN = T.PRELUDE.replace("@FNS@", "#define COOP_SOLO_MS 1500ul\n@FNS@") + r"""
static void solo(void)                     /* what coop_solo_check sets up once the game plays */
{
    memset(&coop, 0, sizeof coop);
    bytes[0] = 1; bytes[1] = 1; players = 1; extra = 0; game_no++; board = 99;
    coop.game = chg_game_now() + 1; coop.n = 1; coop.turn = 1; coop.round = 1;
}
static void play(const char *head)
{
    unsigned balls = 0;
    printf("%s: n %u teams %u players %u board %u\n", head, coop.n, coop.teams, players, board);
    for (;;) {
        printf("up ball %u turn %u game player %u\n", bytes[1], coop.turn, bytes[0]);
        balls++;
        if (!coop_change_wrap(0, 0, 0, 0)) break;
    }
    printf("over after %u balls, the game's end sees %u player(s)\n", balls, players);
}
int main(void)
{
    /* held at Start: up to 1.5 s before the game's start counts; never held, or long before, does not */
    printf("held %d %d %d %d\n", coop_solo_held(0, 5000), coop_solo_held(4000 | 1, 5000), coop_solo_held(3500, 5000),
           coop_solo_held(3000, 5000));
    /* one player, CO-OP PLAY (or a team mode) on, characters: all three needed */
    printf("takes %d %d %d %d\n", coop_solo_takes(1, 1, 1), coop_solo_takes(2, 1, 1), coop_solo_takes(1, 0, 1),
           coop_solo_takes(1, 1, 0));
    solo();
    play("alone");
    solo();                                 /* a plain Start in ball 1: a teammate, as in a co-op game */
    button = 0; teams_on = 0;
    coop_add_wrap(0, 0, 0, 0);
    play("joined");
    solo();                                 /* CO-OP PLAY at Team 2v2: the Start begins the team game */
    teams_on = 1;
    coop_add_wrap(0, 0, 0, 0);
    printf("teams: n %u teams %u team1 %u team2 %u max %u players %u board %u\n", coop.n, coop.teams, coop.team_n[1],
           coop.team_n[2], coop.team_max, players, board);
    coop_add_wrap(0, 0, 0, 0);
    printf("teams: n %u team1 %u team2 %u players %u\n", coop.n, coop.team_n[1], coop.team_n[2], players);
    return 0;
}
"""

SIGS = ("static int coop_solo_held(unsigned long held, unsigned long start)",
        "static int coop_solo_takes(unsigned players, int switched_on, int chars)")


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in SIGS) + "\n" + T.lifted()
    return R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()


def _game(out, head):
    start = next(i for i, l in enumerate(out) if l.startswith(head + ":"))
    end = next(i for i in range(start, len(out)) if out[i].startswith("over after"))
    return out[start], [l for l in out[start:end] if l.startswith("up ")], out[end]


def test_the_right_flipper_held_at_start_counts_only_just_before_it(tmp_path):
    out = _run(tmp_path)
    assert "held 0 1 1 0" in out
    assert "takes 1 0 0 0" in out


def test_a_team_of_one_plays_the_game_as_one_player_on_its_own_boards(tmp_path):
    head, ups, end = _game(_run(tmp_path), "alone")
    assert head == "alone: n 1 teams 0 players 1 board 99"            # no co-op board: the game's own
    assert ups == ["up ball %d turn 1 game player 1" % b for b in (1, 2, 3)]
    assert end == "over after 3 balls, the game's end sees 1 player(s)"


def test_a_start_in_its_first_ball_still_adds_a_teammate(tmp_path):
    head, ups, end = _game(_run(tmp_path), "joined")
    assert head == "joined: n 2 teams 0 players 2 board 2"             # a 2-player co-op game now, its own board
    assert ups == ["up ball %d turn %d game player 1" % (b, t) for b in (1, 2, 3) for t in (1, 2)]
    assert end == "over after 6 balls, the game's end sees 1 player(s)"


def test_with_a_team_mode_on_the_start_begins_the_team_game(tmp_path):
    out = _run(tmp_path)
    assert "teams: n 2 teams 1 team1 2 team2 0 max 4 players 1 board 0" in out   # player 2 joins team 1
    assert "teams: n 3 team1 2 team2 1 players 2" in out                          # player 3 is team 2
