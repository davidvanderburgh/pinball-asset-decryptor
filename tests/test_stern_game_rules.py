"""PAD-400: our modes run alone on the other Spike 2 titles too - the game's rules (its features) are read from
each title's own program, whatever its rule base (`Rule`, `crule`) and whichever virtual is its shot handler."""
import os
import re
from pathlib import Path

import pytest

from pinball_decryptor.plugins.stern import game_mode_blocks as G

SDK = Path(__file__).resolve().parent.parent / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = sorted((SDK / "ports").glob("*.port"))
#: the titles whose ports carry the rule lines, and how many (read_rules on each program, 2026-10-06)
RULED = {"avengers_infinity_le-1.09": 23, "avengers_infinity_le-1.10": 23, "avengers_infinity_pro-1.10": 23,
         "deadpool_le-1.14": 12, "deadpool_le-1.16": 12, "deadpool_pro-1.16": 12,
         "dungeons_and_dragons_le-1.00": 18, "dungeons_and_dragons_le-1.10": 18,
         "dungeons_and_dragons_pro-1.10": 18, "foo_fighters_le-1.04": 17, "foo_fighters_pro-1.04": 17,
         "godzilla_le-1.16": 24, "godzilla_pro-1.15": 24, "godzilla_pro-1.16": 24, "jaws_le-1.02": 22,
         "john_wick_le-1.01": 20, "john_wick_le-1.02": 20, "john_wick_pro-1.02": 21, "king_kong_le-0.97": 21,
         "king_kong_pro-0.97": 21, "mando_le-1.44": 12, "mando_le-1.45": 12, "mando_pro-1.45": 12,
         "sword_of_rage_le-1.18": 14, "sword_of_rage_le-1.19": 14, "sword_of_rage_pro-1.19": 13,
         "venom_le-1.07": 19, "venom_pro-1.07": 19}


@pytest.mark.parametrize("cls, name", [
    ("RuleKingOfTheMonsters", "King of the Monsters"),
    ("RuleDestructionJackpot", "Destruction Jackpot"),
    ("RuleAvengerBlackWidowRamp", "Avenger Black Widow Ramp"),
    ("RuleTeamUpShot", "Team Up Shot"),
    ("cdragon_rule", "Dragon"),
    ("ctinys_dice_game_rule", "Tinys Dice Game"),
    ("cthe_child_rule", "The Child"),
    ("cweb_combos", "Web Combos"),
    ("AtticAttackMultiballRule", "Attic Attack Multiball"),
    ("GargoylesGoneWild_Rule", "Gargoyles Gone Wild"),
    ("rule_drop_targets", "Drop Targets"),
    ("RuleUIBonusScreen", "UI Bonus Screen"),
])
def test_a_rule_reads_as_its_feature(cls, name):
    assert G.rule_name(cls) == name


def test_two_rules_of_one_name_are_told_apart():
    assert G.rule_name("chost_combo_rule", whole=True) == "Host Combo Rule"


def test_a_handler_is_hooked_only_where_the_plain_hook_can_move_its_words():
    assert G.hookable((0xE92D4070, 0xE1A04000))                # push; mov
    assert G.hookable((0xE59F3010, 0xE92D4010))                # ldr r3, [pc, #16]: relocated
    assert not G.hookable((0xE12FFF1E, 0xE1A00000))            # bx lr first: ends at once
    assert not G.hookable((0xE92D4010, 0xEB000123))            # push {.., lr}; bl: the bl would land wrong
    assert not G.hookable((0xEA000010, 0xE1A00000))            # b
    assert not G.hookable((0xE08F3003, 0xE1A00000))            # add r3, pc, r3


def _rules(text):
    sites = re.findall(r"^site block_rule_(\d+)\s+(0x[0-9a-f]+) (0x[0-9a-f]+) (0x[0-9a-f]+)", text, re.M)
    names = dict(re.findall(r"^text block_rule_name_(\d+)\s+(.+?)\s*$", text, re.M))
    return sites, names


@pytest.mark.parametrize("port", PORTS, ids=lambda p: p.stem)
def test_every_ports_rule_lines_are_whole(port):
    text = port.read_text(encoding="utf-8")
    sites, names = _rules(text)
    assert len(sites) == RULED.get(port.stem, 0), port.stem
    cap = int(re.search(r"#define BLOCK_RULES\s+(\d+)", RUNTIME.read_text(encoding="utf-8")).group(1))
    assert len(sites) <= cap
    assert [int(n) for n, *_ in sites] == list(range(len(sites)))
    assert set(names) == {n for n, *_ in sites}
    assert len({v.lower() for v in names.values()}) == len(names), "two features of one name"
    others = {m.group(2) for m in re.finditer(r"^site (\S+)\s+(0x[0-9a-f]+)", text, re.M)
              if not m.group(1).startswith("block_rule_")}
    for _n, addr, w0, w1 in sites:
        assert addr not in others, addr                      # two hooks on one entry are not possible
        assert G.hookable((int(w0, 16), int(w1, 16))), addr


ELF_DIRS = [os.environ.get("PAD_GAME_ELF_DIR", ""), r"C:\tmp\PAD-400\elf", "/mnt/c/tmp/PAD-400/elf"]


def _elf(key):
    for d in ELF_DIRS:
        p = os.path.join(d, key + ".elf") if d else ""
        if p and os.path.isfile(p):
            return p
    pytest.skip("game program not present: %s" % key)


@pytest.mark.parametrize("key, slot", [("godzilla_pro-1.16", 25), ("avengers_infinity_le-1.09", 28),
                                       ("deadpool_le-1.14", 31), ("deadpool_pro-1.16", 32), ("venom_le-1.07", 40),
                                       ("dungeons_and_dragons_le-1.00", 43), ("mando_le-1.44", 31)])
def test_the_ports_rule_lines_are_the_programs(key, slot):
    """What read_rules reads from each program is what its port says, at the title's own shot slot."""
    rules = G.read_rules(open(_elf(key), "rb").read())
    assert rules and {r.slot for r in rules} == {slot}
    text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
    assert [ln for ln in G.rule_lines(rules) if not ln.startswith("#")] == \
        re.findall(r"^(?:site block_rule_|text block_rule_name_).*$", text, re.M)


@pytest.mark.parametrize("key", ["iron_maiden_le-1.16", "jurassic_park_le-1.16", "elvira3-1.13", "turtles_pro-1.58",
                                 "uncanny_xmen_le-0.98"])
def test_a_title_whose_rules_take_no_shot_mask_gets_none(key):
    """Their rules hear shots as switch hooks (or the program has no rule base): no slot is guessed."""
    assert G.read_rules(open(_elf(key), "rb").read()) == []
