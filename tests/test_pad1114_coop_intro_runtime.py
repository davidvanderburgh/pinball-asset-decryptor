"""PAD-1114: the co-op and team games' intro - when the runtime plays it, the both-flipper skip (lifted verbatim from
pad_mode_runtime.c), what coop.cfg and sounds.cfg say for it, and its sound's pseudo mode."""
from tests import test_spike2_mode_roster as R
from tests import test_pad1017_coop_turns as T

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import sound_modes as SM

MAIN = r"""
#include <stdio.h>
@FNS@
int main(void)
{
    int freed = 0, a, b, c, d;
    /* an intro on the card, not yet in this game, ball 1 not out (unserved, or waiting in the lane) */
    printf("wanted %d %d %d %d %d %d\n", ci_wanted(1, 0, 5, 1, 1, 0), ci_wanted(1, 0, 5, 1, 0, 1),
           ci_wanted(1, 0, 5, 1, 0, 0), ci_wanted(1, 5, 5, 1, 1, 0), ci_wanted(0, 0, 5, 1, 1, 0),
           ci_wanted(1, 0, 5, 2, 1, 1));
    /* the right flipper held through a solo Start, then the left pressed: no skip until the right is let go once */
    a = ci_skip(0, 1, &freed);
    b = ci_skip(1, 1, &freed);
    c = ci_skip(0, 0, &freed);
    d = ci_skip(1, 1, &freed);
    printf("skip %d %d %d %d freed %d\n", a, b, c, d, freed);
    return 0;
}
"""

SIGS = ("static int ci_wanted(int have, unsigned played_game, unsigned game, unsigned ball, int unserved, int waits)",
        "static int ci_skip(int left, int right, int *freed)")


def _run(tmp_path):
    src = T.RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in SIGS)
    return R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()


def test_the_intro_plays_once_a_game_before_its_first_ball_is_out(tmp_path):
    assert "wanted 1 1 0 0 0 0" in _run(tmp_path)


def test_both_flippers_skip_it_once_each_was_let_go(tmp_path):
    assert "skip 0 0 0 1 freed 3" in _run(tmp_path)


def _elf():
    import os
    path = r"C:/tmp/PAD-1108/elfs/godzilla_le-1_16_0_spike2.elf"
    if not os.path.isfile(path):
        import pytest
        pytest.skip("the Godzilla LE 1.16 game program is not on this machine")
    with open(path, "rb") as f:
        return f.read()


def test_an_intro_alone_writes_the_buttons_and_no_pick():
    lines = CP.character_lines(_elf(), {"pick": False, "list": [], "intro": "coop/intro_video.mp4"})
    assert lines == ["left 60", "action 34", "lane 62", "intro_hold 96"]   # TIMED PLUNGER held off


def test_the_timed_plunger_is_read_off_the_program():
    assert CP.timed_plunger(_elf()) == 96
    assert CP.timed_plunger(b"not a program") is None


def test_no_intro_and_no_pick_writes_nothing():
    assert CP.character_lines(_elf(), {"pick": False, "list": []}) == []


def test_sounds_cfg_names_the_intro_sound():
    text = SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": bytes(range(8)), "host": bytes(range(8, 16)),
                                              "ms": 12005})
    assert "cintro\t979\t0001020304050607\t08090a0b0c0d0e0f\t12005" in text.splitlines()


def test_the_intro_sound_is_a_file_built_whole_and_kept_out_of_the_record():
    assert SM.is_intro(SM.INTRO_MODE) and SM.is_turn(SM.INTRO_MODE)
    assert not SM.is_shot(SM.INTRO_MODE) and not SM.is_juke(SM.INTRO_MODE) and not SM.is_mode_turn(SM.INTRO_MODE)
    assert SM.is_shot(SM.shot_mode(SM.SHOT_MAX)) and not SM.is_shot(SM.shot_mode(SM.SHOT_MAX + 1))
    m = SM.Modes(intro="x.wav", intro_rel="audio/idx1725.wav")
    assert m.any and m.files() == [("audio/idx1725.wav", SM.INTRO_MODE, "x.wav")]
    assert m.level("audio/idx1725.wav", SM.INTRO_MODE) == 0
    rec = SM.card_record(m, [{"mode": SM.INTRO_MODE, "lines": 1, "rel": "audio/idx1725.wav", "slot": 1725,
                              "host": 369}])
    assert len(rec) == 1                                   # the heading only: the intro is co-op's to keep
