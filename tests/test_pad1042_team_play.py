"""PAD-1042: Team 2v2 - players 1 and 2 against players 3 and 4 (pad_mode_runtime.c "TEAM 2V2").

The runtime's wraps are lifted verbatim and run against PAD-1017's model of the framework's own player change and add
player (test_pad1017_coop_turns.py): the game plays two players, a team each, and the runtime takes each team's
players in turn, alternating the teams."""
import os
import pathlib

from tests import test_pad1017_coop_turns as T
from tests import test_spike2_mode_roster as R

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = T.RUNTIME

MAIN = T.PRELUDE + r"""
static void team_game(unsigned humans, int extra_at, int mode)
{
    unsigned k, balls = 0;
    memset(&coop, 0, sizeof coop);
    bytes[0] = 1; bytes[1] = 1; players = 1; extra = 0; game_no++; board = 99;
    teams_on = mode; button = 0;                         /* CO-OP PLAY at 2 (1 here) or 3: plain Start, no button */
    for (k = 1; k < humans; k++) coop_add_wrap(0, 0, 0, 0);
    printf("teams %u: %u+%u game players %u board %u\n", coop.n, coop.team_n[1], coop.team_n[2], players, board);
    for (;;) {
        printf("up ball %u player %u game player %u\n", bytes[1], coop.turn, bytes[0]);
        if (shown_turn != coop.turn) printf("SCREEN SAYS %u\n", shown_turn);
        balls++;
        if ((int)balls == extra_at) extra = 1;
        if (!coop_change_wrap(0, 0, 0, 0)) break;
    }
    printf("over after %u balls, the game's end sees %u player(s)\n", balls, players);
}
int main(int argc, char **argv)
{
    unsigned humans = (unsigned)(argv[1][0] - '0');
    int extra_at = argc > 2 ? argv[2][0] - '0' : 0;
    int mode = argc > 3 ? argv[3][0] - '0' : 1;          /* 1: Team 2v2, 3: Team 2v1 */
    team_game(humans, extra_at, mode);
    if (mode == 3) printf("fourth %u players %u\n", coop_add_wrap(0, 0, 0, 0), players);   /* 2v1 is full at 3 */
    if (humans == 4) {
        printf("fifth %u\n", coop_add_wrap(0, 0, 0, 0));    /* both teams full */
        /* the next game, CO-OP PLAY back at 1: a co-op game, not a team one */
        memset(&coop.n, 0, sizeof coop.n); game_no++; players = 1; bytes[0] = 1; bytes[1] = 1;
        teams_on = 0; button = 1;
        coop_add_wrap(0, 0, 0, 0);
        printf("co-op after teams: n %u teams %u players %u\n", coop.n, coop.teams, players);
    }
    if (humans == 1) printf("one start: team %u players %u\n", coop_teammates(), players);
    return 0;
}
"""


def _game(tmp_path, humans, extra_at=0, mode=1):
    sub = tmp_path / ("g%d_%d_%d" % (humans, extra_at, mode))
    sub.mkdir()
    args = (str(humans), str(extra_at), str(mode))
    out = R._host_run(sub, MAIN.replace("@FNS@", T.lifted()), args=args).splitlines()
    assert not any(l.startswith("SCREEN SAYS") for l in out)     # the top line names the player up, every ball
    return out


def _head(out):
    return next(l for l in out if l.startswith("teams "))


def _over(out):
    return next(l for l in out if l.startswith("over after "))


def _ups(out):
    return [l[len("up "):] for l in out if l.startswith("up ")]


def _round(ball, order):
    return ["ball %d player %d game player %d" % (ball, p, 1 if p <= 2 else 2) for p in order]


def test_two_against_two_alternate_the_teams_each_ball(tmp_path):
    out = _game(tmp_path, 4)
    # team 1 is the game's player 1, team 2 its player 2: two score panels, two sets of progress; the TEAM PLAY board
    assert _head(out) == "teams 4: 2+2 game players 2 board 0"
    assert _ups(out) == sum((_round(b, (1, 3, 2, 4)) for b in (1, 2, 3)), [])
    assert _over(out) == "over after 12 balls, the game's end sees 2 player(s)"   # both teams' scores at its end
    assert "fifth 0" in out
    assert "co-op after teams: n 2 teams 0 players 2" in out              # the next game is the game's own again


def test_three_players_the_lone_one_plays_both_of_its_teams_turns(tmp_path):
    out = _game(tmp_path, 3)
    assert _head(out) == "teams 3: 2+1 game players 2 board 0"
    assert _ups(out) == sum((_round(b, (1, 3, 2, 3)) for b in (1, 2, 3)), [])
    assert _over(out) == "over after 12 balls, the game's end sees 2 player(s)"


def test_two_players_are_one_team(tmp_path):
    out = _game(tmp_path, 2)
    assert _head(out) == "teams 2: 2+0 game players 1 board 0"
    assert _ups(out) == sum((_round(b, (1, 2)) for b in (1, 2, 3)), [])
    assert _over(out) == "over after 6 balls, the game's end sees 1 player(s)"


def test_team_2v1_is_its_own_choice_full_at_three(tmp_path):
    """daveyvandy: "There should be a designated option for 2V1" - CO-OP PLAY 3."""
    out = _game(tmp_path, 3, mode=3)
    assert _head(out) == "teams 3: 2+1 game players 2 board 1"                # the TEAM 2V1 board
    assert _ups(out) == sum((_round(b, (1, 3, 2, 3)) for b in (1, 2, 3)), [])
    assert _over(out) == "over after 12 balls, the game's end sees 2 player(s)"
    assert "fourth 0 players 2" in out                                     # a fourth Start adds no one
    assert "teams: Start - both teams are full (3 players, Team 2v1)" in out
    out = _game(tmp_path, 2, mode=3)                                       # two players: one team, as in 2v2
    assert _head(out) == "teams 2: 2+0 game players 1 board 1"


def test_the_choice_reads_the_row(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static unsigned coop_teams_size(unsigned always, unsigned setting_value, int has_setting)")
    main = "#include <stdio.h>\n" + fn + r"""
int main(void)
{
    unsigned v;
    for (v = 0; v <= 4; v++) printf("%u", coop_teams_size(0, v, 1));
    printf(" %u %u %u %u\n", coop_teams_size(0, 2, 0), coop_teams_size(4, 0, 1), coop_teams_size(3, 1, 1),
           coop_teams_size(0, 3, 0));
    return 0;
}
"""
    assert R._host_run(tmp_path, main).strip() == "00430 0 4 3 0"                # 2: 2v2 (4), 3: 2v1 (3)


def test_one_start_is_the_games_own_one_player_game(tmp_path):
    out = _game(tmp_path, 1)
    assert _head(out).startswith("teams 0: 0+0 game players 1")
    assert "one start: team 0 players 1" in out


def test_an_extra_ball_stays_with_the_player_who_earned_it(tmp_path):
    for at, who in ((2, 3), (4, 4)):                        # player 3 (team 2, round 1); player 4 (the ball's last)
        out = _game(tmp_path, 4, at)
        ups = _ups(out)
        assert ups[at - 1] == ups[at] and ups[at].startswith("ball 1 player %d " % who)
        rest = ups[:at] + ups[at + 1:]
        assert rest == sum((_round(b, (1, 3, 2, 4)) for b in (1, 2, 3)), [])
        assert _over(out) == "over after 13 balls, the game's end sees 2 player(s)"


def test_the_top_line_board_and_gate_know_team_play():
    src = RUNTIME.read_text(encoding="utf-8")
    show = R._lift(src, "static void coop_turn_show(void)")
    assert '"TEAM %u P%u  BALL %%d", (coop.turn + 1u) / 2u, coop.turn' in show
    board = R._lift(src, "static void coop_board_name(char *out, unsigned n)")
    assert 'pm_snprintf(out, 40, "TEAM PLAY")' in board and 'pm_snprintf(out, 40, "TEAM 2V1")' in board
    assert "for (t = 1; t <= 5 && n < cap; t++)" in R._lift(
        src, "static int coop_page_names(char names[][40], int n, int cap)\n{")
    tick = R._lift(src, "static void coop_tick(void)\n{")
    assert "if (n && !coop.teams && pm_in_game()) coop_scores_same(n);" in tick   # a team's score is the game's own
    line = R._lift(src, "static void coop_line(const char *s)")
    assert '"teams on")) { coop.teams_always = 4;' in line and '"teams 2v1")) { coop.teams_always = 3;' in line
    assert "return !while_at || (value >= 1u && value <= 6u);" in R._lift(
        src, "static int insider_holding(unsigned while_at, unsigned value)")


def test_the_service_menu_row_has_team_2v2_and_the_tab_says_how_to_play_it(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.webui import help_content
    key, values, names, opts = E._CoopMenu(lambda *a: None).wanted()
    assert (values, names, opts) == (7, (), {"default": 1, "help_text": CP.MENU_HELP, "from_zero": True})
    assert (CP.MENU_OFF, CP.MENU_COOP, CP.MENU_TEAMS) == (0, 1, 2)
    assert len(CP.MENU_HELP) <= 63 and "1 Co-op 2 2v2 3 2v1" in CP.MENU_HELP          # PAD-1065: shorter, for 4-6
    text = str(help_content.__dict__)
    assert CP.MENU_TEAMS_2V1 == 3 and "**3 (Team 2v1):** the same team game for three players" in text
    assert "**2 (Team 2v2):** players 1 and 2 play against players 3 and 4" in text
    from pinball_decryptor.webui.tabs import modes as M
    assert "0 Off, 1 Co-op, 2 Team 2v2, 3 Team 2v1" in M.ModesTab.COOP_MENU_TIP


GZ_ELFS = ("C:/tmp/PAD-1010/elfs/godzilla_le-1_16_0_spike2.elf", "C:/tmp/PAD-1033/elfs/godzilla_le-1_16_0.elf")


def test_the_row_is_four_numbers_from_zero_on_godzilla():
    import pytest
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import menu_settings as M
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    elf = next((p for p in GZ_ELFS if os.path.isfile(p)), None)
    if not elf:
        pytest.skip("no Godzilla LE 1.16 program here")
    with open(elf, "rb") as f:
        raw = f.read()
    t = AdjustmentTable(raw)
    settings, writes, _cat, refused = M.plan_many(t, [E._CoopMenu(lambda *a: None).wanted()])
    assert not refused
    s = settings[0]
    assert (s.values, s.low, s.default, s.kind, s.help) == (7, 0, 0, M.number_kind(t), CP.MENU_HELP)
    assert M.number_kind(t) == 2 and t.entry(t.by_name["AD_GAME_ID"])["max"] == 9999
    out = bytearray(raw)
    for off, data in writes.items():
        out[off:off + len(data)] = data
    e = AdjustmentTable(bytes(out)).entry(s.id)
    assert (e["min"], e["max"], e["default"]) == (0, 6, 0)                  # an Off/On row's 0 and 1 mean the same
    assert M.check(bytes(out), s) in ([], ["no menu page lists it"])         # the page record is placed by the Write
