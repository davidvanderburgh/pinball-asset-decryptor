"""PAD-1026: James Bond's gadget countdowns count nothing while a mode of ours holds the game's modes off, as under the
game's own mini-wizards (the Bond LE owner: "the (4) other mini wizard modes suppress progress of DB5 (right scoop) and
powerpack (left scoop) during their mini wizard modes. I'd like the option to do this in new modes").

Bond is plain C. Each gadget's countdown asks ONE check before it counts, plays its clip or lights its inserts (LE 1.06:
DB5 0x651ec, Powerpack 0x156424, Attache Case 0xc6410: the game's multiballs 0x9f460, its mini-wizards 0x110b20, ...).
The ports name each check as a rule of the game's (`site block_rule_<n>` + `value block_rule_gate_<n> 1`) that the
runtime refuses with 0 while a mode of ours blocks, unless the mode keeps it counting (keep_rules: the Modes tab's
"keep counting" ticks)."""
import os
import re
from pathlib import Path

import pytest

from pinball_decryptor.plugins.stern import game_mode_blocks as G
from tests import test_spike2_mode_roster as R

SDK = Path(__file__).resolve().parent.parent / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
#: the checks, read off each program (2026-11-06): (gadget, countdown, check)
CHECKS = {"james_bond_le-1.06": [(1, 0x000c6608, 0x000c6410), (2, 0x0006533c, 0x000651ec), (3, 0x00156568, 0x00156424)],
          "james_bond_pro-1.06": [(1, 0x000c63f0, 0x000c61f8), (2, 0x00065344, 0x000651f4), (3, 0x00155548, 0x00155404)]}
NAMES = ["Attache Case Countdown", "DB5 Countdown", "Powerpack Countdown"]
ELF_DIRS = [os.environ.get("PAD_GAME_ELF_DIR", ""), r"C:\tmp\PAD-400\elf", "/mnt/c/tmp/PAD-400/elf"]


def _elf(key):
    for d in ELF_DIRS:
        p = os.path.join(d, key + ".elf") if d else ""
        if p and os.path.isfile(p):
            return open(p, "rb").read()
    pytest.skip("game program not present: %s" % key)


def _port_rules(key):
    text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
    sites = re.findall(r"^site block_rule_(\d+)\s+(0x[0-9a-f]+) (0x[0-9a-f]+) (0x[0-9a-f]+)", text, re.M)
    gates = set(re.findall(r"^value block_rule_gate_(\d+)\s+1\b", text, re.M))
    names = dict(re.findall(r"^text block_rule_name_(\d+)\s+(.+?)\s*$", text, re.M))
    return text, sites, gates, names


@pytest.mark.parametrize("key", sorted(CHECKS))
def test_each_bond_port_names_its_three_countdown_checks_as_gate_rules(key):
    text, sites, gates, names = _port_rules(key)
    assert [(int(n), int(a, 16)) for n, a, *_ in sites] == [(i, c[2]) for i, c in enumerate(CHECKS[key])]
    assert gates == {"0", "1", "2"}
    assert [names[str(i)] for i in range(3)] == NAMES
    for _n, _a, w0, w1 in sites:
        assert int(w0, 16) == 0xE92D4008 and int(w1, 16) >> 24 == 0xEB        # push {r3, lr}; bl: hook_veto_bl's
        assert G.movable((int(w0, 16), int(w1, 16)))


def test_the_60th_anniversary_names_none():
    """Its rules are its own (Bond multiball awards films): no countdown of this shape, so no rule lines."""
    _text, sites, gates, _names = _port_rules("james_bond_60th_le-1.11")
    assert not sites and not gates


@pytest.mark.parametrize("key", sorted(CHECKS))
def test_the_ports_gate_lines_are_the_programs(key):
    """What read_gate_rules reads from each program is what its port says, line for line."""
    gates = G.read_gate_rules(_elf(key))
    assert [(g.gadget, g.rule, g.gate) for g in gates] == CHECKS[key]
    assert [g.name for g in gates] == NAMES
    text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
    assert [ln for ln in G.gate_rule_lines(gates) if not ln.startswith("#")] == \
        re.findall(r"^(?:site block_rule_|value block_rule_gate_|text block_rule_name_).*$", text, re.M)


def test_the_60th_anniversary_program_has_no_countdown_checks():
    assert G.read_gate_rules(_elf("james_bond_60th_le-1.11")) == []


def test_a_draft_port_of_a_plain_c_build_reads_its_own_checks():
    """A Bond build drafted from a reference gets the lines read from ITS program (never carried)."""
    from pinball_decryptor.plugins.stern import portgen as P
    assert P._GENERATED.match("value block_rule_gate_1 1") and P._GENERATED.match("site block_rule_1 0x1 0x2 0x3")
    src = Path(P.__file__).read_text(encoding="utf-8")
    assert "out += own_gate_rules(tgt)" in src


def test_the_app_lists_them_as_the_game_rules_a_mode_may_keep_counting():
    from pinball_decryptor.plugins.stern import mode_project as MP
    profiles = MP.profiles()
    for key in ("james_bond_le_1_06", "james_bond_pro_1_06"):
        assert [n for _i, n in profiles[key].game_rules] == NAMES


GATE_MAIN = r"""
#include <stdio.h>
#include <stdarg.h>
#define BLOCK_RULES 32
static int live, in_game;
static unsigned block_rules_keep;
static int block_rules_said;
static char block_who[40] = "YOLT WIZARD";
static int said;
static int block_live(void) { return live; }
static int pm_in_game(void) { return in_game; }
static const char *pm_port_text(const char *k) { return "DB5 Countdown"; }
static int pm_snprintf(char *b, unsigned long n, const char *f, ...)
{ va_list a; int r; va_start(a, f); r = vsnprintf(b, n, f, a); va_end(a); return r; }
static void say(const char *f, ...) { said++; }
@FN@
int main(void)
{
    unsigned r[6] = {0};
    int b0, b1, b2;
    printf("idle %d\n", on_rule_gate(r, 1));                         /* nothing of ours blocks */
    live = 1;
    printf("attract %d\n", on_rule_gate(r, 1));                      /* not in a game */
    in_game = 1;
    /* called before the printf: gcc reads its arguments right to left, so `said` would be read first */
    b0 = on_rule_gate(r, 0); b1 = on_rule_gate(r, 1); b2 = on_rule_gate(r, 2);
    printf("blocks %d %d %d said %d\n", b0, b1, b2, said);
    block_rules_keep = 1u << 1;                                       /* the mode keeps the DB5 countdown counting */
    printf("kept %d %d\n", on_rule_gate(r, 1), on_rule_gate(r, 2));
    printf("range %d\n", on_rule_gate(r, 40));
    live = 0;
    printf("after %d\n", on_rule_gate(r, 2));
    return 0;
}
"""


def test_the_runtime_refuses_a_check_only_while_a_mode_of_ours_blocks_in_a_game(tmp_path):
    fn = R._lift(RUNTIME.read_text(encoding="utf-8"), "static int on_rule_gate(unsigned *r, unsigned n)")
    out = R._host_run(tmp_path, GATE_MAIN.replace("@FN@", fn)).splitlines()
    assert out == ["idle 0", "attract 0", "blocks 1 1 1 said 1", "kept 0 1", "range 0", "after 0"]


def test_the_runtime_hooks_a_gate_rule_as_a_veto_answering_0():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = src[src.index("static void block_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    assert 'pm_snprintf(lo, sizeof lo, "block_rule_gate_%d", i);' in arm
    assert "hook_veto_n(fn(name), on_rule_gate, (unsigned)i, 0)" in arm               # refused: r0 = 0, "not now"
    assert arm.index("on_rule_gate") < arm.index("hook_n(fn(name), on_rule_shots, (unsigned)i)")
