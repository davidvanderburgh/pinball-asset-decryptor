"""PAD-1042: Team 2v2 - two teams of two (pad_mode_runtime.c "TEAM 2V2"); PAD-1052: players 1 and 3 against players
2 and 4, all added by one Start once TEAM PLAY 2 VS 2 is picked on the start menu, as on stock Stern (a plain Start
is still the game's own one-player game). The model runs the fill through the second Start, the route of a build whose
start menu the port does not know; the same coop_team_fill fills the menu's pick from the tick.

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
static void team_game(unsigned humans, int extra_at, int mode, int later)
{
    unsigned k, balls = 0;
    char words[40];
    memset(&coop, 0, sizeof coop);
    bytes[0] = 1; bytes[1] = 1; players = 1; extra = 0; game_no++; board = 99; join_shown = 0;
    teams_on = mode; button = 0;                         /* CO-OP PLAY at 2 (1 here) or 3: plain Start, no button */
    credits = humans - 1;                                /* PAD-1052: the credits for as many more as `humans` */
    if (humans > 1) {                                    /* PAD-1052: the second Start adds them all */
        printf("second start %u\n", coop_add_wrap(0, 0, 0, 0));
        for (k = 0; coop_join_words(coop.join_n, k, words, sizeof words); k++) printf("SAYS %s\n", words);
        printf("shown %u\n", join_shown);
    }
    if (later) {                                         /* ... a credit more, and another Start: the next player */
        credits = (unsigned)later;
        k = coop_add_wrap(0, 0, 0, 0);
        printf("later start %u n %u join %u\n", k, coop.n, coop.join_n);
    }
    credits = 99;
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
    int later = argc > 4 ? argv[4][0] - '0' : 0;         /* PAD-1052: credits for a later Start */
    team_game(humans, extra_at, mode, later);
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


def _game(tmp_path, humans, extra_at=0, mode=1, later=0):
    sub = tmp_path / ("g%d_%d_%d_%d" % (humans, extra_at, mode, later))
    sub.mkdir()
    args = (str(humans), str(extra_at), str(mode), str(later))
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
    return ["ball %d player %d game player %d" % (ball, p, 1 if p % 2 else 2) for p in order]


def _says(out):
    return [l[len("SAYS "):] for l in out if l.startswith("SAYS ")]


def test_two_against_two_alternate_the_teams_each_ball(tmp_path):
    out = _game(tmp_path, 4)
    # team 1 (players 1, 3) is the game's player 1, team 2 (players 2, 4) its player 2: two score panels, two sets of
    # progress; the TEAM PLAY board. PAD-1052: so the turns go in the players' order
    assert _head(out) == "teams 4: 2+2 game players 2 board 0"
    assert _ups(out) == sum((_round(b, (1, 2, 3, 4)) for b in (1, 2, 3)), [])
    assert _over(out) == "over after 12 balls, the game's end sees 2 player(s)"   # both teams' scores at its end
    assert "fifth 0" in out
    assert "co-op after teams: n 2 teams 0 players 2" in out              # the next game is the game's own again


def test_three_players_the_lone_one_plays_both_of_its_teams_turns(tmp_path):
    out = _game(tmp_path, 3)                                # credits for two more: the second Start adds both
    assert _head(out) == "teams 3: 2+1 game players 2 board 0"
    assert _ups(out) == sum((_round(b, (1, 2, 3, 2)) for b in (1, 2, 3)), [])
    assert _over(out) == "over after 12 balls, the game's end sees 2 player(s)"


def test_two_players_are_a_team_each(tmp_path):
    out = _game(tmp_path, 2)
    assert _head(out) == "teams 2: 1+1 game players 2 board 0"
    assert _ups(out) == sum((_round(b, (1, 2)) for b in (1, 2, 3)), [])
    assert _over(out) == "over after 6 balls, the game's end sees 2 player(s)"


def test_team_2v1_is_its_own_choice_full_at_three(tmp_path):
    """daveyvandy: "There should be a designated option for 2V1" - CO-OP PLAY 3."""
    out = _game(tmp_path, 3, mode=3)
    assert _head(out) == "teams 3: 2+1 game players 2 board 1"                # the TEAM 2V1 board
    assert _ups(out) == sum((_round(b, (1, 2, 3, 2)) for b in (1, 2, 3)), [])
    assert _over(out) == "over after 12 balls, the game's end sees 2 player(s)"
    assert "fourth 0 players 2" in out                                     # a third Start adds no one
    assert "teams: Start - both teams are full (3 players, Team 2v1)" in out
    out = _game(tmp_path, 2, mode=3)                                       # two players: a team each, as in 2v2
    assert _head(out) == "teams 2: 1+1 game players 2 board 1"


def test_the_choice_reads_the_row(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    # PAD-1073: the start menu's pick sizes the team game (test_pad1073_coop_row_three.py), coop.cfg `teams` its own
    body = R._lift(src, "static unsigned coop_teams_switched_on(void)")
    assert "return coop.teams_always ? coop.teams_always : tm.size;" in body


def test_one_start_is_the_games_own_one_player_game(tmp_path):
    out = _game(tmp_path, 1)
    assert _head(out).startswith("teams 0: 0+0 game players 1")
    assert "one start: team 0 players 1" in out


def test_an_extra_ball_stays_with_the_player_who_earned_it(tmp_path):
    for at, who in ((2, 2), (4, 4)):                        # player 2 (team 2, round 1); player 4 (the ball's last)
        out = _game(tmp_path, 4, at)
        ups = _ups(out)
        assert ups[at - 1] == ups[at] and ups[at].startswith("ball 1 player %d " % who)
        rest = ups[:at] + ups[at + 1:]
        assert rest == sum((_round(b, (1, 2, 3, 4)) for b in (1, 2, 3)), [])
        assert _over(out) == "over after 13 balls, the game's end sees 2 player(s)"


def test_the_top_line_board_and_gate_know_team_play():
    src = RUNTIME.read_text(encoding="utf-8")
    show = R._lift(src, "static void coop_turn_show(void)")
    assert '"TEAM %u P%u  BALL %%d", coop_team_of(coop.turn), coop.turn' in show
    board = R._lift(src, "static void coop_board_name(char *out, unsigned n)")
    assert 'pm_snprintf(out, 40, "TEAM PLAY")' in board and 'pm_snprintf(out, 40, "TEAM 2V1")' in board
    assert "for (t = 1; t <= 5 && n < cap; t++)" in R._lift(
        src, "static int coop_page_names(char names[][40], int n, int cap)\n{")
    tick = R._lift(src, "static void coop_tick(void)\n{")
    assert "if (n && !coop.teams && pm_in_game()) coop_scores_same(n);" in tick   # a team's score is the game's own
    line = R._lift(src, "static void coop_line(const char *s)")
    assert '"teams on")) { coop.teams_always = 4;' in line and '"teams 2v1")) { coop.teams_always = 3;' in line
    assert "return !while_at || coop_row_mode(value) != 0u;" in R._lift(
        src, "static int insider_holding(unsigned while_at, unsigned value)")


def test_the_service_menu_row_has_team_2v2_and_the_tab_says_how_to_play_it(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.webui import help_content
    key, values, names, opts = E._CoopMenu(lambda *a: None).wanted()
    assert (values, names, opts) == (3, (), {"default": 1, "help_text": CP.MENU_HELP, "from_zero": True})   # PAD-1073
    assert (CP.MENU_OFF, CP.MENU_CLASSIC, CP.MENU_ENHANCED) == (0, 1, 2)
    assert len(CP.MENU_HELP) <= 63 and "Games on start menu" in CP.MENU_HELP
    text = str(help_content.__dict__)
    assert "- **TEAM PLAY 2 VS 1:** the same team game for three players" in text
    assert "- **TEAM PLAY 2 VS 2:** players 1 and 3 play against players 2 and 4" in text
    assert "step to it and press **Start** once. The game starts with all four players" in text
    from pinball_decryptor.webui.tabs import modes as M
    assert "TEAM PLAY 2 VS 2: players 1 and 3 play as a team against players 2 and 4" in M.ModesTab.COOP_MENU_TIP


def test_the_second_start_adds_all_four_and_says_the_teams(tmp_path):
    """DoomWalrus666: "you must press the start button 4 times ... it said 4 players added: Team 1: Player 1 and
    Player 3, Team 2: Player 2 and Player 4"; then "you still want to be able to play 1 player" - so one Start is the
    game's own one-player game (test_one_start_is_the_games_own_one_player_game) and the second adds the rest."""
    out = _game(tmp_path, 4)
    assert "second start 1" in out
    assert "teams: Start - 4 players added at once (team 1: 2, team 2: 2)" in out
    assert _says(out) == ["4 PLAYERS ADDED", "TEAM 1: P1 AND P3", "TEAM 2: P2 AND P4"]
    assert "shown 1" in out                                               # the first line now; the tick shows the rest
    assert sum(l.startswith("teams: player ") for l in out) == 3          # the game's own add, once a player


def test_the_second_start_in_2v1_adds_two(tmp_path):
    """DoomWalrus666: "3 players added: Team 1: Player 1 and Player 3, Team 2: Player 2"."""
    out = _game(tmp_path, 4, mode=3)                                       # credits for four: 2v1 stops at 3
    assert "teams: Start - 3 players added at once (team 1: 2, team 2: 1)" in out
    assert _says(out) == ["3 PLAYERS ADDED", "TEAM 1: P1 AND P3", "TEAM 2: P2"]
    assert _head(out) == "teams 3: 2+1 game players 2 board 1"
    assert _ups(out) == sum((_round(b, (1, 2, 3, 2)) for b in (1, 2, 3)), [])


def test_short_of_credits_the_second_start_adds_what_they_buy_and_a_later_one_the_next(tmp_path):
    out = _game(tmp_path, 2)                                               # one credit: one more player
    assert "teams: Start - 2 players added at once (team 1: 1, team 2: 1)" in out
    assert _says(out) == ["2 PLAYERS ADDED", "TEAM 1: P1", "TEAM 2: P2"]
    out = _game(tmp_path, 3, later=1)                                       # two, then a credit and Start: player 4
    assert "later start 1 n 4 join 0" in out                               # its own turn line and pick, as before
    assert "teams: player 4 joins team 2 (team 1: 2, team 2: 2; the game plays 2 player(s), a team each)" in out
    assert _head(out) == "teams 4: 2+2 game players 2 board 0"
    assert _ups(out) == sum((_round(b, (1, 2, 3, 4)) for b in (1, 2, 3)), [])


def test_the_fill_says_its_lines_from_the_tick():
    src = RUNTIME.read_text(encoding="utf-8")
    tick = R._lift(src, "static void coop_join_tick(void)\n{")
    assert "else if (pm_ms() - coop.join_at >= COOP_JOIN_MS) {" in tick
    assert "coop_pick_open(1);" in tick                                    # player 1's pick once the lines are said
    assert "coop_join_tick();" in R._lift(src, "static void coop_tick(void)\n{")
    add = R._lift(src, "static unsigned coop_team_add(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "if (coop.filling) return ret;" in add
    wrap = R._lift(src, "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "if (!n && *coop_players_byte == 1 && coop_teams_switched_on() && !tm.armed)" in wrap   # no menu: 2nd Start


def test_team_play_is_a_start_menu_pick_as_on_stock_stern(tmp_path):
    """daveyvandy: "Make it work like stock Stern co-op 2v2 games work" - TMNT's TEAM PLAY 2 VS 2 is an entry of its
    start menu, and one Start then makes the whole team game. The entry goes on at Prolonged Competition's sites,
    played as Standard; a game starting while (or just after) the menu showed it is filled from the tick."""
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static int team_pick_live(int pending, unsigned long seen, unsigned long now)")
    main = "#include <stdio.h>\n#define TEAM_PICK_MS 20000ul\n" + fn + r"""
int main(void)
{
    printf("%d %d %d %d\n", team_pick_live(1, 1000, 1200), team_pick_live(1, 1000, 20999), team_pick_live(1, 1000, 21000),
           team_pick_live(0, 1000, 1200));
    return 0;
}
"""
    assert R._host_run(tmp_path, main).strip() == "1 1 0 0"      # shown just before the game; a menu left long ago
    disp = R._lift(src, "static void on_team_dispatch(unsigned *r)\n{")   # the game's thread, not the tick's
    assert "want = team_pick_live(tm.pending, tm.seen_ms, pm_ms()) && kind && team_menu_kinds(kinds);" in disp
    assert "if (!tm.armed || r[0] != tm.ball_id || !tm.seen_ms) return;" in disp and "coop_team_fill(0, 0, 0, 0)" in disp
    # through the runtime's own bus hook: a second hook of the bus never ran on Godzilla LE 1.16 (emulator)
    assert "on_team_dispatch(r);" in R._lift(src, "static void on_event_dispatch(unsigned *r)\n{")
    assert "COOP_JOIN_ROUNDS" in R._lift(src, "static void coop_join_tick(void)\n{")   # said twice: a film hid one
    assert "coop_team_fill" not in R._lift(src, "static void coop_tick(void)\n{")
    built = R._lift(src, "static void team_menu_built(unsigned *r)")
    assert "*(unsigned *)(list + es * i + kat) = TEAM_KIND + kinds[j];" in built and "if (!nk) return;" in built
    picked = R._lift(src, "static void team_menu_picked(unsigned *r)")
    assert "else r[3] = 0;" in picked                                  # the game plays it as Standard
    frame = R._lift(src, "static void team_menu_frame(unsigned *r)")
    assert 'pm_port_value("comp_menu_end_index", 0)' in frame and "pm_message_set(msg, team_kind_name(tm.kind));" in frame
    arm = R._lift(src, "static void team_menu_arm(void)\n{")
    assert 'hook_full(fn("comp_menu_frame"), team_menu_frame)' in arm
    assert 'hook(fn("challenge_menu_pick"), team_menu_picked)' in arm
    assert "team_menu_arm();" in R._lift(src, "static void coop_arm(void)")      # every co-op card: CO-OP PLAY too


def test_co_op_is_a_start_menu_pick_too(tmp_path):
    """DoomWalrus666: "Can we please make Co-op mode work the same way?" - CO-OP PLAY 1 (or Classic 4, or a card of
    co-op with no row) puts CO-OP PLAY on the start menu: picked, ball 1 makes a co-op game of one, each Start in ball
    1 adds a teammate with no button held, and the top line says so."""
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static int coop_join_words(unsigned n, unsigned step, char *out, unsigned cap)")
    main = "#include <stdio.h>\n#define pm_snprintf snprintf\n" + fn + r"""
int main(void)
{
    char w[40];
    unsigned k;
    for (k = 0; coop_join_words(1, k, w, sizeof w); k++) printf("%s|", w);
    printf("\n");
    return 0;
}
"""
    assert R._host_run(tmp_path, main).strip() == "CO-OP PLAY|START ADDS PLAYERS|UP TO 4 PLAYERS|"   # 19 fit
    kind = R._lift(src, "static unsigned team_menu_kinds(unsigned *kinds)\n{")
    assert "kinds[0] = 1u;\n    if (!coop.setting) return 1;" in kind             # PAD-1073: CO-OP PLAY first
    disp = R._lift(src, "static void on_team_dispatch(unsigned *r)\n{")
    assert "if (kind == 1u) {" in disp and "coop.n = 1;" in disp and "coop.teams = 0;" in disp
    assert "coop.join_n = 1;" in disp
    wrap = R._lift(src, "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "coop.join_n = 0;" in wrap                                  # a teammate's join ends the menu's lines


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
    assert (s.values, s.low, s.default, s.kind, s.help) == (3, 0, 0, M.number_kind(t), CP.MENU_HELP)
    assert M.number_kind(t) == 2 and t.entry(t.by_name["AD_GAME_ID"])["max"] == 9999
    out = bytearray(raw)
    for off, data in writes.items():
        out[off:off + len(data)] = data
    e = AdjustmentTable(bytes(out)).entry(s.id)
    assert (e["min"], e["max"], e["default"]) == (0, 2, 0)                  # PAD-1073: Off, Classic, Enhanced
    assert M.check(bytes(out), s) in ([], ["no menu page lists it"])         # the page record is placed by the Write
