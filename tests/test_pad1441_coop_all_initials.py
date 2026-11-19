"""PAD-1441 (DoomWalrus666): "In Godzilla co-op, the high score is attributed only to player 1. Could we please allow
all players to have their initials to the high score".

The game's end-of-game high scores walk a category's entry list and, for each entry, file the best player not filed in
it yet who beats it - asking that player for initials first, on the game's own screen (Godzilla LE 1.16 0x300d20). A
co-op board gave the game the one entry, so only player 1 was ever asked. A co-op or team board now gives it one entry
for each player with the top score, each a copy of the board's record, and the initials are joined in the board's
record after. Emulator-proven on Godzilla LE 1.16 (C:/tmp/PAD-1441 job.sh: a 2-player co-op game, both asked).
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"


def _host():
    from tests import test_spike2_mode_roster as R
    return R


JOIN_MAIN = r"""
#include <stdio.h>
@FNS@
static void show(const char *const *names, unsigned n)
{
    char out[16];
    chg_names_join(out, names, n);
    printf("[%s]\n", out);
}
int main(void)
{
    const char *two[] = { "DWL", "DAV" }, *four[] = { "AAA", "BBB", "CCC", "DDD" };
    const char *gap[] = { "AAA", "", "CCC" }, *pad[] = { "AB ", "CD" };
    const char *longer[] = { "DOOMWALRUS", "DAVIDVANDY" }, *four_long[] = { "DOOMWALRUS", "DAVIDVANDY", "ABCDEFGHIJ",
        "WXYZWXYZWX" };
    const char *none[] = { "", "  " };
    show(two, 2); show(four, 4); show(gap, 3); show(pad, 2); show(longer, 2); show(four_long, 4); show(none, 2);
    return 0;
}
"""


def test_the_teams_initials_join_in_one_record(tmp_path):
    R = _host()
    fn = R._lift(RUNTIME.read_text(encoding="utf-8"),
                 "static void chg_names_join(char *out, const char *const *names, unsigned n)")
    out = R._host_run(tmp_path, JOIN_MAIN.replace("@FNS@", fn)).split("\n")
    assert [l for l in out if l] == [
        "[DWL+DAV]",                       # each player's, in turn
        "[AAA+BBB+CCC+DDD]",               # four teammates' 3 letters: 15, the page's width
        "[AAA+CCC]",                       # a blank one (no initials entered) left out
        "[AB+CD]",
        "[DOOMWAL+DAVIDVA]",               # 10-letter names (adjustment): an even share of the page's 15
        "[DOO+DAV+ABC+WXY]",
        "[]"]


def test_a_coop_board_gives_the_game_an_entry_for_each_top_scorer():
    R = _host()
    src = RUNTIME.read_text(encoding="utf-8")
    wrap = R._lift(src, "static unsigned chg_scores_wrap(pm_reg r0, pm_reg r1, pm_reg r2, pm_reg r3)")
    # only a co-op or team board asks; a mode's challenge game keeps its one entry
    assert "if (team) names = coop_hs_names();" in wrap
    assert "list = chg_scores_first_entries(cat, names, &list_was, &names);" in wrap
    assert "list = chg_scores_one_entry(cat, &list_was);" in wrap
    # each extra entry a copy of the board's record (a team that beats it beats them all), titled the board's name
    assert "more[e - 1][k] = chg_rec[k];" in wrap
    assert "ents[e][0] = (pm_addr)(unsigned long)more[e - 1];" in wrap
    assert "ents[e][5] = (pm_addr)(unsigned long)chg_hs.name;" in wrap
    assert "CHG_ENT_AWARD(ents[e]) = 0;" in wrap
    # the gate lets those entries through, and everything is put back after the game's call
    call = wrap.index("ret = chg_scores_game(r0, r1, r2, r3);", wrap.index("if (team) names = coop_hs_names();"))
    assert wrap.index("chg_gate_n = (int)names;") < call
    for back in ("chg_gate_n = 1;", "if (team) coop_hs_back();", "ents[k][0] = mwas[k][0];",
                 "CHG_ENT_AWARD(ents[k]) = mawards[k];"):
        assert wrap.index(back) > call, back
    # the joined initials go in the board's record, its check made again
    join = wrap.index("chg_names_join(joined, who, names);")
    assert join > wrap.index("chg_rec_keep") - 2000 and join < wrap.index("chg_rec_keep(b, n, chg_hs.name, chg_rec);")
    assert "c = chg_rec_check(chg_rec);" in wrap[join:]
    gate = R._lift(src, "static unsigned chg_gate_wrap(pm_reg r0, pm_reg r1, pm_reg r2, pm_reg r3)")
    assert "entry < chg_gate_n" in gate


def test_the_coop_side_counts_the_top_scorers_and_puts_a_team_game_back():
    R = _host()
    src = RUNTIME.read_text(encoding="utf-8")
    mark = R._lift(src, "static void coop_scores_mark(unsigned n)")
    assert "chg_hs.team = 1;" in mark
    picked = R._lift(src, "static void chg_scores_picked(unsigned slot, const char *name, const struct pm_mode *by)\n{")
    assert "chg_hs.team = 0;" in picked
    names = R._lift(src, "static unsigned coop_hs_names(void)\n{")
    assert "coop.standard" in names                          # ENHANCED STANDARD: the game's own boards
    assert "*coop_players_byte = (unsigned char)n;" in names  # a team game's players all counted in for the call
    assert "coop_team_of_in(coop.team_kind, k + 1) - 1" in names
    back = R._lift(src, "static void coop_hs_back(void)\n{")
    assert "*coop_players_byte = coop_hs.players;" in back
    assert "coop_score_put(k, coop_hs.was[k]);" in back
