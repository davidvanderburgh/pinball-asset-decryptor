"""PAD-696: a mode's challenge game of 2-4 players plays the mode for every player (David: "Godzilla challenge mode
multiplayer not working - second through 4th players start full games"). The runtime kept the start menu's pick for
player 1's ball only; the others' balls started plain. The turn rule is lifted from the runtime verbatim and run on the
desk; the wiring at the ball's start is read."""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")
CC = shutil.which("gcc") or shutil.which("cc")
needs_cc = pytest.mark.skipif(not CC or os.name == "nt", reason="needs a C compiler (WSL or Linux)")


def _rt():
    with open(RUNTIME, encoding="utf-8") as f:
        return f.read()


def _lift(src, signature):
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


@needs_cc
def test_each_player_gets_one_turn_at_the_games_pick(tmp_path):
    code = "#include <stdio.h>\n" + _lift(_rt(), "static int chg_turn_due(") + r"""
int main(void)
{
    /* pick, pick_game, game, players (bit p = player p's turn began), player */
    printf("%d", chg_turn_due(16, 5, 5, 1u << 1, 2));             /* player 2's first ball: due */
    printf("%d", chg_turn_due(16, 5, 5, 1u << 1 | 1u << 2, 2));   /* player 2's ball re-served: not again */
    printf("%d", chg_turn_due(16, 5, 5, 1u << 1, 1));             /* player 1 again: no */
    printf("%d", chg_turn_due(16, 5, 5, 1u << 1 | 1u << 2 | 1u << 3, 4));   /* player 4: due */
    printf("%d", chg_turn_due(16, 5, 6, 1u << 1, 2));             /* another game: the pick was the last game's */
    printf("%d", chg_turn_due(-1, 5, 5, 1u << 1, 2));             /* no pick: a plain game */
    printf("%d", chg_turn_due(0, 5, 5, 1u << 1, 2));              /* a claimed challenge (0) counts too */
    printf("%d", chg_turn_due(16, 5, 5, 0, 0));                   /* no player: attract */
    printf("%d\n", chg_turn_due(16, 5, 5, 0, 5));                 /* never past player 4 */
    return 0;
}
"""
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([CC, "-std=gnu17", "-Wall", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True).stdout.strip()
    assert out == "100100100"


def test_the_balls_start_plays_the_pick_again_for_a_later_player():
    src = _rt()
    began = _lift(src, "static void chg_began(void)")
    assert "chg.players |= 1u << pm_player();" in began               # the turn that began is that player's
    assert "if (chg.pick_game != chg.game) chg.players = 0;" in began  # a new game starts with nobody's turn
    turn = _lift(src, "static int chg_next_turn(void)")
    assert "chg.state = 0;" in turn                     # the last turn's "over" no longer refuses this player's mode
    assert "own_pending = chg.pick - CHALLENGE_OWN;" in turn   # MODE CHALLENGE / a menu entry of a mode's own
    start = _lift(src, "static void challenge_ball_start(void)")
    # read before own_pending and the flags are: the pending own pick is what the rest of the ball's start plays
    assert start.index("chg_next_turn()") < start.index("k = own_pending")
    assert "picked = (int)n == again ? 1 : challenge_picked(n);" in start   # a claimed one: its flag was cleared
    picked = _lift(src, "static void chg_picked(")
    assert "chg.pick = pick;" in picked
    assert src.count("chg_picked(") == 5                # the definition and its four callers, each naming its pick
