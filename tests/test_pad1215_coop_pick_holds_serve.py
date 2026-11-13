"""PAD-1215: a player's first-ball character pick holds their ball's serve back, so neither the pick's Action press (the
launch on Godzilla) nor the game's TIMED PLUNGER launches it - coop_pick_due lifted verbatim from pad_mode_runtime.c,
and the serve hook armed for a pick with no intro."""
import re

from tests import test_spike2_mode_roster as R
from tests import test_pad1017_coop_turns as T
from tests import test_pad1114_coop_intro_runtime as I

from pinball_decryptor.plugins.stern import coop_play as CP

MAIN = r"""
#include <stdio.h>
@FNS@
int main(void)
{
    /* on, 11 characters, turn 2 of a team game, not picked, 4 players, no intro running: hold */
    printf("due %d\n", coop_pick_due(1, 11, 2, -1, 4, 0));
    /* already picked; no pick on the card; no characters; no co-op game; an intro's phase has the ball; no turn */
    printf("not %d %d %d %d %d %d %d\n", coop_pick_due(1, 11, 2, 3, 4, 0), coop_pick_due(0, 11, 2, -1, 4, 0),
           coop_pick_due(1, 0, 2, -1, 4, 0), coop_pick_due(1, 11, 2, -1, 0, 0), coop_pick_due(1, 11, 2, -1, 4, 1),
           coop_pick_due(1, 11, 0, -1, 4, 0), coop_pick_due(1, 11, 5, -1, 4, 0));
    /* every turn's first ball, players 1-4 alike */
    printf("turns %d %d %d %d\n", coop_pick_due(1, 2, 1, -1, 2, 0), coop_pick_due(1, 2, 2, -1, 2, 0),
           coop_pick_due(1, 2, 3, -1, 4, 0), coop_pick_due(1, 2, 4, -1, 4, 0));
    return 0;
}
"""

SIG = "static int coop_pick_due(int on, int n_chars, unsigned turn, int picked, unsigned teammates, int intro_phase)"


def test_the_serve_waits_for_any_players_unmade_pick(tmp_path):
    src = T.RUNTIME.read_text(encoding="utf-8")
    out = R._host_run(tmp_path, MAIN.replace("@FNS@", R._lift(src, SIG))).splitlines()
    assert out == ["due 1", "not 0 0 0 0 0 0 0", "turns 1 1 1 1"]


def test_the_serve_wrap_holds_for_the_pick_and_is_armed_without_an_intro():
    src = T.RUNTIME.read_text(encoding="utf-8")
    wrap = R._lift(src, "static unsigned ci_serve_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert wrap.index("ci_ball_hold(") < wrap.index("coop_pick_hold();") < wrap.index("ci_serve_game(")
    assert re.search(r"if \(\(ci\.clip\[0\] \|\| \(coop_pick_on && coop_ch_n\)\) && fn\(\"serve_ball\"\)", src)
    hold = R._lift(src, "static void coop_pick_hold(void)")
    assert "ci.holding = 1;" in hold and "ci_start_poll(1);" in hold      # the pick's words say ACTION PICKS; joins
    assert "proc_sleep" in hold


def test_a_pick_without_an_intro_still_names_the_start_button():
    lines = CP.character_lines(I._elf(), {"pick": True, "list": [{"name": "A", "ability": "save"}]})
    assert "intro_start 36" in lines and not any(ln.startswith("intro_hold") for ln in lines)
