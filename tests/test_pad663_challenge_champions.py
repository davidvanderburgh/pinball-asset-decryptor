"""PAD-663: a mode's challenge champion on every Spike 2 game.

PAD-640 kept a mode's challenge high score only where the build has one "<x> CHALLENGE CHAMPION" category per
challenge (Bond 1.06, Stranger Things). Every Spike 2 build keeps its champions in the same framework, and its
end-of-game function asks the bus (`mov r0, #0x5b ; add r1, sp, #X ; bl <dispatch> ; cmp r0, #0`, {player, category
+2, entry +4} at sp + X) before it files a player under a category's entry. The port names that call; in a mode's
challenge game the runtime answers yes only for the one entry pointed at the mode's record (HIGHEST SCORES' first,
where the build has no category of the challenge's own) - the game's own champions are not touched by that game.
"""
import os
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import portchallenge as PC
from pinball_decryptor.plugins.stern import portgen

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"


def _host():
    from tests import test_spike2_mode_roster as R
    return R


# ---- the finder ---------------------------------------------------------------------------
class _Mem:
    def __init__(self, words, base):
        self.words, self.text_va = tuple(words), base


def _gate_code(ident=0x5B, at=0x48, cmp=True, stores=True):
    """The end-of-game function's question, as every build has it: the stores of {player, category, entry} at sp + at,
    a call before the question, the question, the call, its test."""
    push = 0xE92D4FF0
    strb = 0xE5CD5000 | at                                   # strb r5, [sp, #at]
    strh = 0xE1CDA0B0 | ((at + 2) >> 4) << 8 | ((at + 2) & 0xF)   # strh sl, [sp, #at + 2]
    st = 0xE58D6000 | (at + 4)                               # str r6, [sp, #at + 4]
    words = [push, 0xE24DD0BC] + [0] * 8 + ([strb, 0, strh, st] if stores else [0, 0, 0, 0]) + [0] * 6
    words += [0xEB000100,                                    # bl (the uuid copy before it)
              0xE3A00000 | ident, 0xE28D1000 | at, 0xE3A02000, 0xE3A03000,
              0xEB000200, 0xE3500000 if cmp else 0xE1A00000, 0x0A000010]
    return words


def test_the_gate_is_the_one_bus_call_whose_answer_is_tested():
    e = _Mem(_gate_code(), 0x10000)
    lines = [l for l in PC.gate_lines(e, 0) if not l.startswith("#")]
    call = 0x10000 + 4 * (len(_gate_code()) - 3)
    assert lines == ["site  challenge_scores_gate  0x%08x 0xeb000200 0xe3500000" % call,
                     "value challenge_scores_gate_id       91",
                     "value challenge_scores_gate_cat_at   2",
                     "value challenge_scores_gate_entry_at 4"]


def test_no_gate_without_the_test_or_the_fields():
    assert PC.gate_lines(_Mem(_gate_code(cmp=False), 0x10000), 0) == []      # its answer not tested: not the one
    assert PC.gate_lines(_Mem(_gate_code(stores=False), 0x10000), 0) == []   # no {player, category, entry} there


#: the newest build of every title with a challenge a mode can take (the library's; PAD-619's list less King Kong,
#: X-Men, Dungeons & Dragons and Bond 60th, which have none)
NEWEST = ["aerosmith-1.16", "aerosmith_le-1.16", "avengers_infinity_le-1.10", "avengers_infinity_pro-1.10",
          "batman-1.14", "beatles-1.29", "deadpool_le-1.16", "deadpool_pro-1.16", "elvira3-1.13",
          "foo_fighters_le-1.04", "foo_fighters_pro-1.04", "godzilla_le-1.16", "godzilla_pro-1.16", "guardians-1.15",
          "guardians_le-1.15", "iron_maiden_le-1.18", "iron_maiden_pro-1.18", "james_bond_le-1.06",
          "james_bond_pro-1.06", "jaws_le-1.02", "jaws_pro-1.02", "john_wick_le-1.02", "john_wick_pro-1.02",
          "jurassic_park_le-1.16", "jurassic_park_pro-1.16", "jurassic_park_the_pin-1.05", "led_zeppelin_le-1.22",
          "led_zeppelin_pro-1.22", "mando_le-1.45", "mando_pro-1.45", "metallica_spike-1.04", "munsters_le-1.28",
          "munsters_pro-1.28", "rush_le-1.19", "rush_pro-1.19", "star_wars_elg-1.10", "star_wars_le-1.31",
          "star_wars_pro-1.31", "stranger_things-1.13", "stranger_things_le-1.13", "sword_of_rage_le-1.19",
          "sword_of_rage_pro-1.19", "turtles_le-1.59", "turtles_pro-1.59", "venom_le-1.07", "venom_pro-1.07"]


@pytest.mark.parametrize("key", NEWEST)
def test_every_newest_challenge_port_keeps_a_modes_champion(key):
    port = MP.read_port(str(PORTS / ("%s.port" % key)))
    assert {"challenge_scores", "challenge_score_entry", "challenge_scores_gate"} <= set(port["site"])
    assert int(port["value"]["challenge_scores_gate_id"]) == 91
    assert (int(port["value"]["challenge_scores_gate_cat_at"]), int(port["value"]["challenge_scores_gate_entry_at"])) \
        == (2, 4)
    assert int(port["value"]["challenge_scores_cat"]) == 1
    # the gate is a call inside the end-of-game function, a few hundred words in
    assert 0 < port["site"]["challenge_scores_gate"][0] - port["site"]["challenge_scores"][0] < 0x400


FW = [os.environ.get("PAD_FW_GAMES", ""), r"C:\tmp\PAD-663\fw", "/mnt/c/tmp/PAD-663/fw"]
FW_DIR = next((d for d in FW if d and os.path.isdir(d)), None)


@pytest.mark.parametrize("key", ["avengers_infinity_le-1.10", "mando_le-1.45", "james_bond_le-1.06"])
def test_the_finder_reads_the_gate_off_each_builds_own_program(key):
    game = next((os.path.join(FW_DIR, f) for f in sorted(os.listdir(FW_DIR))
                 if f.startswith(key.split("-")[0] + "-" + key.split("-")[1].replace(".", "_"))), None) if FW_DIR else None
    if not game:
        pytest.skip("the game program is not on this machine")
    lines = [l for l in PC.scores_lines(PC.Elf(game), 5 if key.startswith("james_bond") else 0) if not l.startswith("#")]
    port = MP.read_port(str(PORTS / ("%s.port" % key)))
    got = {l.split()[1]: l.split()[2] for l in lines}
    assert int(got["challenge_scores_gate"], 16) == port["site"]["challenge_scores_gate"][0]
    assert got["challenge_scores_cat"] == "1"


def test_the_lines_are_each_builds_own_never_a_references():
    for line in ("site challenge_scores_gate 0x004e8a48 0xebfafb75 0xe3500000", "value challenge_scores_gate_id 91",
                 "value challenge_scores_gate_cat_at 2", "value challenge_scores_gate_entry_at 4",
                 "value challenge_scores_cat 1"):
        key, rest = line.split(" ", 1)
        assert portgen.generated(key, rest), line


# ---- the runtime -------------------------------------------------------------------------
GATE_MAIN = r"""
#include <stdio.h>
@FNS@
int main(void)
{
    printf("%d %d %d %d %d\n", chg_gate_lets(1, 1, 0), chg_gate_lets(1, 1, 1), chg_gate_lets(2, 1, 0),
           chg_gate_lets(34, 1, 2), chg_gate_lets(1, -1, 0));
    return 0;
}
"""


def test_the_gate_lets_only_the_entry_pointed_at_the_modes_record(tmp_path):
    R = _host()
    fn = R._lift(RUNTIME.read_text(encoding="utf-8"), "static int chg_gate_lets(int cat, int host, int entry)")
    # HIGHEST SCORES' first entry yes; its HIGH SCORE #1, another category, a challenge's scores, no host: no
    assert R._host_run(tmp_path, GATE_MAIN.replace("@FNS@", fn)).split() == ["1", "0", "0", "0", "0"]


def test_the_wrap_shuts_the_games_records_only_around_its_end_of_game_call():
    R = _host()
    src = RUNTIME.read_text(encoding="utf-8")
    body = R._lift(src, "static unsigned chg_scores_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    shut = body.index("chg_gate_cat = (int)cat;")
    call = body.index("ret = chg_scores_game(r0, r1, r2, r3);", shut)
    open_ = body.index("chg_gate_cat = -1;")
    assert shut < call < open_
    assert body.index("*(unsigned short *)(ent + 8) = 0;") < call < body.index("*(unsigned short *)(ent + 8) = award;")
    gate = R._lift(src, "static unsigned chg_gate_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "return 0;" in gate and "return 1;" in gate and "return chg_gate_game(r0, r1, r2, r3);" in gate
    arm = R._lift(src, "static void chg_scores_arm(void)")
    assert 'hook_call(\n                     fn("challenge_scores_gate")' in arm or 'hook_call(fn("challenge_scores_gate")' in arm
    # a menu of the modes' own challenges (no challenge of the game's a mode may take) keeps their champions too
    assert re.search(r"if \(challenges_n \|\| site\(\"challenge_menu\"\)\) chg_scores_arm\(\);", src)


def test_the_score_belongs_to_the_game_its_mode_began_in():
    """Avengers LE 1.10 starts the ball (where a menu pick is taken) before it counts the game's start: the pick's
    stamp was the last game's, and the end of this one filed the score under the game's own challenge scores."""
    R = _host()
    src = RUNTIME.read_text(encoding="utf-8")
    began = src[src.index("static void chg_began(void)\n{"):]
    began = began[:began.index("\n}\n")]
    assert "chg_scores_began();" in began
    restamp = src[src.index("static void chg_scores_began(void)\n{"):]
    assert "chg_hs.game = chg_game_now();" in restamp[:restamp.index("\n}\n")]


def test_hook_call_moves_only_a_call_and_a_plain_word():
    R = _host()
    body = R._lift(RUNTIME.read_text(encoding="utf-8"), "static unsigned hook_call(unsigned addr, void *wrapper)")
    for word in ("0xe59fc00cu", "0xe12fff3cu", "0xe51ff004u"):
        assert word in body
    assert "(p[0] & 0xFF000000u) != 0xEB000000u" in body           # an unconditional bl, nothing else
    assert "(w1 & 0x0E000000u) == 0x0A000000u" in body              # the second word is no branch


def test_the_docs_say_how():
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "challenge_scores_gate" in sdk and "PAD-663" in sdk
