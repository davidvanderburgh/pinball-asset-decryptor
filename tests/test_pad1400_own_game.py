"""PAD-1400: a mode that is the whole game - Stern's own rules switched off underneath it.

- mode_file.c's `game_modes own_game`: it starts with each game (no trigger, no clock), runs through every drain and
  every player's turn (each player's count and total kept), and ends with the game; it asks pm_own_game(1) and holds
  the game's modes off as `block` does.
- pad_mode_runtime.c's pm_own_game: which of the game's calls it refuses (og_refuses, lifted and compiled), and the
  sites it holds back.
- The app: the mode file's lines, validation, the blocks mode's C (GAME_MODES 3) and where the choice is offered.
The emulator proof (Uncanny X-Men LE 0.98) is in docs/plans/pad1400_own_game.md.
"""
import os
import pathlib
import re
import subprocess

import pytest

from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"

HARNESS = R.HARNESS.replace(
    '''        } else if (!strcmp(argv[k], "player")) {''',
    '''        } else if (!strcmp(argv[k], "game_on")) {   /* PAD-1400: a new game */
            in_game = 1;
        } else if (!strcmp(argv[k], "player")) {''').replace(
    '''int main(int argc, char **argv)''',
    '''int pm_own_game(int on) { printf("OWN_GAME %d\\n", on); return 1; }
int pm_block_game_modes(int on) { printf("BLOCK %d\\n", on); return 1; }
int pm_block_list(const unsigned char *ids, int n) { return 1; }
int pm_block_rules_keep(const unsigned char *ns, int n) { return 1; }
int main(int argc, char **argv)''')


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = R._cc()
    d = tmp_path_factory.mktemp("own_game")
    (d / "harness.c").write_text(HARNESS)
    stubs, _names = R.weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    exe = d / "harness"
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


OWN = "name UNCANNY\ngame_modes own_game\nshots 0x6\naward 1000\naward_ladder fixed\n"


def test_it_starts_with_the_game_and_needs_no_trigger_or_clock(harness, tmp_path):
    out = R._run(harness, tmp_path, OWN, "tick", "3")
    assert "NOT VALID" not in out
    assert "UNCANNY START (the game's start)" in out
    assert "OWN_GAME 1" in out and "BLOCK 1" in out


def test_it_runs_through_drains_and_each_player_keeps_their_own_count(harness, tmp_path):
    out = R._run(harness, tmp_path, OWN, "tick", "3", "shot", "0x2", "shot", "0x4", "ball_end", "tick", "3",
                 "player", "2", "tick", "3", "shot", "0x2", "ball_end", "player", "1", "tick", "3")
    assert "the whole game's mode runs on (player 1: 2 hits, awarded 2000" in out
    assert "player 2's turn - their first ball (0 hits, 0)" in out
    assert "the whole game's mode runs on (player 2: 1 hits, awarded 1000" in out
    assert "player 1's turn - resumed (2 hits, 2000)" in out
    assert "END (" not in out and out.count("START (") == 1


def test_it_ends_with_the_game_and_starts_again_with_the_next(harness, tmp_path):
    out = R._run(harness, tmp_path, OWN, "tick", "3", "shot", "0x2", "game_over", "tick", "3", "game_on", "tick", "3")
    assert "UNCANNY END (the game is over)" in out
    assert out.count("UNCANNY START (the game's start)") == 2
    second = out.split("UNCANNY END (the game is over)")[1]
    assert "OWN_GAME 1" in second


def test_an_ordinary_mode_still_ends_with_its_ball(harness, tmp_path):
    cfg = "name RAMPS\ntrigger 0x2 1\nseconds 30\nshots 0x4\naward 1000\n"
    out = R._run(harness, tmp_path, cfg, "tick", "3", "shot", "0x2", "ball_end", "tick", "3")
    assert "OWN_GAME" not in out
    assert "RAMPS END (ball ended)" in out


# ---- the runtime's decision ------------------------------------------------------------------------------------
def _c_function(name):
    text = RUNTIME.read_text(encoding="utf-8")
    m = re.search(r"^static int %s\(.*?\n\}\n" % name, text, re.S | re.M)
    assert m, name
    return m.group(0)


def test_og_refuses_only_the_games_own_calls_while_a_ball_is_in_play(tmp_path):
    cc = R._cc()
    src = "#define OG_COUNT 0x80u\n" + _c_function("og_refuses") + r'''
#include <stdio.h>
int main(void)
{
    /* owner, in_game, fresh, tilted, now, pass_until, ours, self, how */
    printf("%d", og_refuses(1, 1, 0, 0, 100, 0, 0, 0, 0));        /* the game's call, a ball in play: refused */
    printf("%d", og_refuses(0, 1, 0, 0, 100, 0, 0, 0, 0));        /* no whole-game mode */
    printf("%d", og_refuses(1, 0, 0, 0, 100, 0, 0, 0, 0));        /* no game */
    printf("%d", og_refuses(1, 1, 1, 0, 100, 0, 0, 0, 0));        /* the ball's start, before its first switch */
    printf("%d", og_refuses(1, 1, 0, 1, 100, 0, 0, 0, 0));        /* a tilted ball */
    printf("%d", og_refuses(1, 1, 0, 0, 100, 200, 0, 0, 0));      /* the tilt warning's 3 s */
    printf("%d", og_refuses(1, 1, 0, 0, 100, 0, 1, 0, 0));        /* our own call */
    printf("%d", og_refuses(1, 1, 0, 0, 100, 0, 0, 1, 0));        /* inside one of our own calls */
    printf("%d", og_refuses(1, 1, 0, 0, 100, 0, 0, 0, OG_COUNT)); /* a counted site is never refused */
    printf("\n");
    return 0;
}
'''
    (tmp_path / "og.c").write_text(src)
    exe = tmp_path / "og"
    r = subprocess.run([cc, "-o", str(exe), str(tmp_path / "og.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert subprocess.run([str(exe)], capture_output=True, text=True).stdout.strip() == "100000000"


def test_the_sites_held_back_and_the_ones_only_counted():
    text = RUNTIME.read_text(encoding="utf-8")
    table = text[text.index("og_sites[OG_N] = {"):text.index("};", text.index("og_sites[OG_N] = {"))]
    refused = re.findall(r'\{ "(\w+)", "[^"]+", (?:0|OG_ZERO) \}', table)
    counted = re.findall(r'\{ "(\w+)", "[^"]+", OG_COUNT \}', table)
    assert refused == ["shot_dispatch", "score_add", "score_add32", "callout", "callout_nth", "multiball_serve",
                       "award_screen", "show_start", "rule_dispatch", "switch_spawn",
                       "drain_rule_call"]
    # the score display's own effects run through display_effect_start; sound_play carries the music beds
    assert set(counted) == {"display_effect_start", "sound_play"}
    assert 'og_sites[OG_SHOW]' not in text and '#define OG_SHOW   7' in text and refused[7] == "show_start"
    # a show of ours (its process is the game's code) still plays
    assert "(n == OG_SHOW && show_now.n)" in text
    assert "#define OG_N      %d" % (len(refused) + len(counted)) in text
    # the shot the game's rules do not hear still reaches our modes
    assert "if (n == OG_SHOT) on_shot(r);" in text
    # pm_end gives the game its rules back
    assert "og_mode_ended(current);" in text[text.index("void pm_end(void)"):]


def test_a_site_a_logger_hooked_already_still_takes_a_veto():
    text = RUNTIME.read_text(encoding="utf-8")
    body = text[text.index("static int hook_veto(unsigned addr, veto_fn logger)"):]
    assert "!(og_chaining && p[0] == 0xe51ff004u)" in body[:1400]
    # only og_arm's own vetoes go on top of a logger's hook: every other veto is refused there, as before
    arm = text[text.index("static int og_arm(void)"):]
    assert "og_chaining = 1;" in arm[:2500] and "og_chaining = 0;" in arm[:2500]


# ---- the app ---------------------------------------------------------------------------------------------------
def _xmen():
    from pinball_decryptor.plugins.stern import mode_project as MP
    return MP, MP.profile("uncanny_xmen_le_0_98")


def test_the_mode_file_says_own_game_with_its_block_lines():
    MP, p = _xmen()
    assert p.own_game
    s = MP.blank_spec(p, "UNCANNY")
    s.game_modes = "own_game"
    assert MP.game_modes_lines(s, p) == ["game_modes     own_game"]
    s.block_modes = [3, 4]
    assert MP.game_modes_lines(s, p) == ["game_modes     own_game", "block_modes    3 4"]
    assert MP.validate_game_modes(s, p) == []
    assert MP.held_off(s, p) == (3, 4)
    assert "game_modes     own_game" in MP.runtime_cfg(s, "uncanny").splitlines()


def test_a_title_whose_port_cannot_is_refused():
    MP, p = _xmen()
    import dataclasses
    q = dataclasses.replace(p, own_game=False)
    s = MP.blank_spec(p, "UNCANNY")
    s.game_modes = "own_game"
    assert "Being the whole game is not on" in MP.validate_game_modes(s, q)[0]


def test_own_game_sites_needs_a_score_and_a_callout_site():
    from pinball_decryptor.plugins.stern import mode_project as MP
    assert MP.own_game_sites({"score_add", "callout"})
    assert MP.own_game_sites({"score_add32", "callout"})
    assert not MP.own_game_sites({"score_add"})
    assert not MP.own_game_sites({"callout", "sound_play"})


def test_a_blocks_mode_as_the_whole_game():
    from pinball_decryptor.plugins.stern import block_modes as BM
    assert "own_game" in BM.GAME_MODES
    prog = BM.normalize({"name": "SENTINEL WAR", "game_modes": "own_game", "ends_on_drain": True})
    assert prog["game_modes"] == "own_game"
    c = BM.to_c(prog, "sentinel_war")
    assert "#define GAME_MODES       3" in c
    assert "#define ENDS_ON_DRAIN    0" in c                      # the whole game runs through every drain
    assert re.search(r"#define RUN_SECONDS +0 ", c)              # ... and has no clock (emulator: 30 s ended it)
    assert "pm_own_game(1)" in c
    assert 'start("the game\'s start", 0);' in c
    assert 'end_now("the game is over");' in c


def test_the_shield_and_building_accept_the_whole_game():
    MP, p = _xmen()
    s = MP.blank_spec(p, "UNCANNY")
    s.game_modes = "own_game"
    assert MP.holds_game_modes(s)
    s.game_modes = "stack"
    assert not MP.holds_game_modes(s)


def test_the_games_points_run_with_zero_rather_than_being_refused():
    """Star Wars LE serves a drained ball back while nothing has scored: the game's score call still runs, at 0."""
    text = RUNTIME.read_text(encoding="utf-8")
    assert '{ "score_add", "scores", OG_ZERO }' in text and '{ "score_add32", "scores", OG_ZERO }' in text
    veto = text[text.index("static int og_veto(pm_reg *r, unsigned n)"):]
    veto = veto[:veto.index("\n}\n")]
    assert "r[2] = r[3] = 0;" in veto and "if (n == 2) r[1] = 0;" in veto


def test_switch_spawn_refuses_only_rule_handlers():
    """Rush, Batman...: a switch's handler with none of the low 10 flag bits is a rule's (it runs in play only)."""
    text = RUNTIME.read_text(encoding="utf-8")
    read = text[text.index("static int og_rule_handlers_read(void)"):]
    read = read[:read.index("\n}\n")]
    assert "if (fl & 0x3ffu) { dev++; continue; }" in read
    wrap = text[text.index("static unsigned og_spawn_wrap("):]
    wrap = wrap[:wrap.index("\n}\n")]
    assert "og_rule_handler(handler)" in wrap and "return og_spawn_target(group, handler, arg, r3);" in wrap
    ports = sorted(p.stem for p in (SDK / "ports").glob("*.port") if "\nsite switch_spawn " in p.read_text(encoding="utf-8"))
    assert {"rush_le-1.19", "batman-1.14", "star_wars_le-1.31"} <= set(ports) and len(ports) == 19


def test_the_drain_question_is_answered_no_on_every_newest_build():
    """The trough asks the game's callback (event 10) whether to serve a drained ball back; the whole game answers 0
    (Star Wars LE served every one back). One framework site per build: `mov rN, #10; blx rM`."""
    text = RUNTIME.read_text(encoding="utf-8")
    patch = text[text.index("static int og_drain_patch(pm_addr at)\n{"):]
    patch = patch[:patch.index("\n}\n")]
    assert "(p[0] & 0xFFFF0FFFu) != 0xE3A0000Au" in patch and "s[5] = 0x13a00000u;" in patch
    assert "og_drain_hold = og.owner && !og.tilted;" in text
    ports = [p for p in (SDK / "ports").glob("*.port")]
    have = [p.stem for p in ports if "\nsite drain_rule_call " in p.read_text(encoding="utf-8")]
    assert len(have) == 53
    for p in ports:
        m = re.search(r"^site drain_rule_call\s+\S+\s+(0x\w+)\s+(0x\w+)", p.read_text(encoding="utf-8"), re.M)
        if m:
            assert int(m.group(1), 16) & 0xFFFF0FFF == 0xE3A0000A and int(m.group(2), 16) & 0xFFFFFFF0 == 0xE12FFF30


def test_award_screens_and_shows_pass_at_callers_that_use_the_result():
    """TMNT Pro's show_start(178) at 0x147cf0 stores into the show it gets back: a refused 0 crashed the game. Those
    callers are listed per port and never refused; a port whose callers were not scanned only counts the two."""
    text = RUNTIME.read_text(encoding="utf-8")
    veto = text[text.index("static int og_veto(pm_reg *r, unsigned n)\n{"):]
    veto = veto[:veto.index("\n}\n")]
    assert "og_pass_caller(n, (unsigned)r[PM_REG_LR])" in veto
    caller = text[text.index("static int og_pass_caller(unsigned n, unsigned lr)\n{"):]
    assert "if (!og_ret_scanned) return 1;" in caller[:600] and "lr -= 4u;" in caller[:600]
    tp = (SDK / "ports" / "turtles_pro-1.59.port").read_text(encoding="utf-8")
    assert "value own_ret_scanned      1" in tp
    assert re.search(r"^value own_pass_\d+\s+0x00147cf0$", tp, re.M)
    scanned = [p for p in (SDK / "ports").glob("*.port") if "\nvalue own_ret_scanned " in p.read_text(encoding="utf-8")]
    assert len(scanned) == 53
