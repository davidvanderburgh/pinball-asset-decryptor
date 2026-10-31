"""PAD-889: James Bond's Bond Women multiplier (2X-7X) for blocks modes.

A Bond LE owner wanted the game's Bond Women multiplier in their own modes' scoring. Read off the game program
(LE 1.06): each Bond Woman collected sets a bit of the player's mask, the multiplier is the bits counted plus one held
to 2-7, and while its timed process (0x1ab) runs the game counts it into the playfield multiplier that score_add
multiplies every award by - a mode's Score blocks go through score_add, so they are multiplied already. What blocks
lacked was the multiplier itself, to show it or decide on it: the value "the Bond Women multiplier" reads the game's
own getter (`site bond_women_mult`), 1 when none runs.
"""

import re

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import blocks_sim as BS
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_script as MS
from tests.test_spike2_mode_roster import RUNTIME, _host_run, _lift
from tests.test_stern_block_modes import SHOTS, play, prog, scores

WOMEN = {"k": "women_mult"}


def test_the_ports_name_the_getter_on_bond_le_and_pro_only():
    ports = RUNTIME.parent / "ports"
    for name, at in (("james_bond_le-1.06", "0x0008c9e4"), ("james_bond_pro-1.06", "0x0008c89c")):
        text = (ports / (name + ".port")).read_text(encoding="utf-8")
        assert re.search(r"^site bond_women_mult\s+%s 0xe92d4008 0xe3a01f6b$" % at, text, re.M), name
    assert "bond_women_mult" not in (ports / "james_bond_60th_le-1.11.port").read_text(encoding="utf-8")
    assert MP.profile("james_bond_le_1_06").bond_women is True
    assert MP.profile("james_bond_pro_1_06").bond_women is True
    assert MP.profile("james_bond_60th_le_1_11").bond_women is False      # no Bond Women on the 60th Anniversary
    assert MP.profile("godzilla_le_1_16").bond_women is False


PRELUDE = r"""
#include <stdio.h>
#include <string.h>
static unsigned now, has;
static unsigned getter(void) { return now; }
static unsigned fn(const char *n) { return has && !strcmp(n, "bond_women_mult") ? (unsigned)(unsigned long)getter : 0; }
"""

MAIN = r"""
int main(void)
{
    printf("%u", pm_bond_women_mult());                  /* no getter in the port */
    has = 1;
    now = 1; printf(" %u", pm_bond_women_mult());        /* none runs */
    now = 4; printf(" %u", pm_bond_women_mult());
    now = 7; printf(" %u", pm_bond_women_mult());
    now = 0; printf(" %u", pm_bond_women_mult());        /* never 0: a multiplier */
    now = 0x305; printf(" %u\n", pm_bond_women_mult());  /* the getter's answer is a byte */
    return 0;
}
"""


def test_the_runtime_asks_the_games_own_getter(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8").replace("\r\n", "\n")
    body = _lift(src, "unsigned pm_bond_women_mult(void)")
    out = _host_run(tmp_path, PRELUDE + body + MAIN, flags=("-no-pie", "-fno-pie")).strip()
    assert out == "1 1 4 7 1 5"
    assert "bond_women_arm();" in src
    assert "unsigned pm_bond_women_mult(void);" in (RUNTIME.parent / "pad_mode.h").read_text(encoding="utf-8")


def test_a_blocks_mode_shows_the_multiplier_and_its_points_are_multiplied_by_it(tmp_path):
    """The game multiplies the mode's points (the desk harness's scoring, as Bond's, multiplies by it); the value
    is what it is now: 1 before, 4 while 4X runs, 1 again after."""
    p = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [{"op": "start_mode"}]},
              {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"},
               "do": [{"op": "score", "points": {"k": "num", "v": 1000}},
                      {"op": "words", "text": "BOND WOMEN", "value": WOMEN}]}], seconds=30)
    assert BM.problems(p, SHOTS, MP.GODZILLA_PRO_1_15.events) == []
    assert "(long long)pm_bond_women_mult()" in BM.to_c(p, "blk")
    out = play(tmp_path, p, "shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "women", 4,
               "shot", "Right ramp", "secs", 1, "women", 1, "shot", "Right ramp", "secs", 40)
    assert scores(out) == [1000, 4000, 1000]
    words = re.findall(r"WORDS \S+: (BOND WOMEN.*)", out)
    assert [w.split()[-1] for w in words if w.split()[-1].isdigit()][:3] == ["1", "4", "1"], words
    assert re.search(r"END \(time ran out\): 3 scores, total 6000", out), out[-400:]


def test_the_value_round_trips_and_simulates():
    p = prog([{"hat": {"kind": "mode_start"}, "do": [{"op": "set", "var": "x", "value": WOMEN}]}],
             vars=[{"name": "x", "reset": "mode"}])
    text = MS.to_script(p)
    assert "women_mult()" in text
    assert MS.from_script(text)["scripts"][0]["do"][0]["value"] == WOMEN
    sim = BS.Sim(p)
    assert sim.val(WOMEN) == 1
    sim.women_mult = 3
    assert sim.val(WOMEN) == 3
