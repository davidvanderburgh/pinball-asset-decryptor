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


# ---- the attract mode's champion page ------------------------------------------------------
PAGES_MAIN = r"""
#include <stdio.h>
static unsigned chg_title_max = 27;
@FNS@
int main(void)
{
    char t[48];
    int first = 1 << 30;
    chg_champion_title(t, sizeof t, "PAD CHALLENGE"); printf("[%s]\n", t);
    chg_champion_title(t, sizeof t, "COMBO CHAMPION"); printf("[%s]\n", t);
    chg_champion_title(t, sizeof t, "A VERY LONG MODE NAME HERE"); printf("[%s]\n", t);
    chg_title_max = 18;                                 /* an 800x480 one-screen cabinet (Star Wars ELG, The Pin) */
    chg_champion_title(t, sizeof t, "PAD CHALLENGE"); printf("[%s]\n", t);
    chg_champion_title(t, sizeof t, "TAKEN"); printf("[%s]\n", t);
    chg_title_max = 27;
    /* a category past the table's (Avengers shows its last scores under 55 of 38): never the cycle's */
    printf("%d", chg_pages_follow(55, 38, &first));
    /* the cycle's first page: category 2 (Iron Maiden's page starts there), then 3 .. - only 2 again follows */
    printf("%d", chg_pages_follow(2, 38, &first));
    printf("%d", chg_pages_follow(3, 38, &first));
    printf("%d", chg_pages_follow(2, 38, &first));
    printf("%d", chg_pages_follow(1, 38, &first));     /* a lower one seen later becomes the first */
    printf("%d", chg_pages_follow(2, 38, &first));
    printf("%d\n", chg_pages_follow(-1, 38, &first));
    return 0;
}
"""


def test_a_modes_page_is_titled_like_the_games_champions_and_follows_the_cycles_first(tmp_path):
    R = _host()
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in (
        "static void chg_champion_title(char *out, unsigned cap, const char *name)",
        "static int chg_pages_follow(int cat, int count, int *first)"))
    out = R._host_run(tmp_path, PAGES_MAIN.replace("@FNS@", fns)).splitlines()
    assert out == ["[PAD CHALLENGE CHAMPION]", "[COMBO CHAMPION]", "[A VERY LONG MODE NAME HERE]",
                   "[PAD CHALLENGE]", "[TAKEN CHAMPION]", "0101100"]


def test_the_page_repeat_follows_only_an_entrys_first_page_in_the_attract_mode():
    R = _host()
    src = RUNTIME.read_text(encoding="utf-8")
    run = R._lift(src, "static unsigned chg_pages_run(int k, unsigned a0, unsigned a1, unsigned a2, unsigned a3,")
    own = run.index("ret = chg_pages_game[k](a0, a1, a2, a3, s0, s1, s2, s3);")
    gate = run.index("pm_in_game() || chg_scores_running || (k != CHG_LIST_PAGE && chg_pages_n != 0)")
    swap = run.index("ent[0] = (unsigned)(unsigned long)chg_pages_rec;")
    again = run.index("chg_pages_game[k](a0, a1, a2, a3, s0, s1, s2, s3);", swap)
    back = run.index("chg_pages_back();", again)
    assert own < gate < swap < again < back
    # a page cut short gives the entry back on the tick; the end-of-game wrap gives it back first
    tick = src[src.index("static void chg_pages_tick(void)\n{"):]
    assert "chg_pages_back();" in tick[:tick.index("\n}\n")]
    wrap = R._lift(src, "static unsigned chg_scores_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert wrap.index("chg_pages_back();") < wrap.index("chg_scores_game(r0, r1, r2, r3)")


def test_the_host_category_is_its_first_entry_alone_for_the_call():
    """HIGHEST SCORES' insert moved the game's HIGH SCORE #1-#4 down one when a mode's record (in the first entry's
    place) was beaten (Avengers LE 1.10, the first rig run)."""
    R = _host()
    src = RUNTIME.read_text(encoding="utf-8")
    one = R._lift(src, "static unsigned *chg_scores_one_entry(long cat, unsigned *was)")
    assert "one[0] = l[0];" in one and "one[1] = 0;" in one and "desc[7] = (unsigned)(unsigned long)one;" in one
    wrap = R._lift(src, "static unsigned chg_scores_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    call = wrap.index("list = chg_scores_one_entry(cat, &list_was);")
    assert call < wrap.index("ret = chg_scores_game(r0, r1, r2, r3);", call) < wrap.index("if (list) *list = list_was;")


@pytest.mark.parametrize("key", ["avengers_infinity_le-1.10", "deadpool_le-1.16", "batman-1.14", "godzilla_le-1.16",
                                 "iron_maiden_pro-1.18", "foo_fighters_le-1.04", "john_wick_le-1.02", "beatles-1.29"])
def test_the_generic_page_ports_name_the_page_the_probe_saw(key):
    """The probe (C:/tmp/PAD-663 probe663.c: every entry read in the attract mode, with its caller) found the attract
    mode's champion page at these addresses; the finder names it (among up to four of that shape)."""
    seen = {"avengers_infinity_le-1.10": 0x214D8, "deadpool_le-1.16": 0x2375C, "batman-1.14": 0x2492C,
            "godzilla_le-1.16": 0x23B70, "iron_maiden_pro-1.18": 0x434C0, "foo_fighters_le-1.04": 0x1CBD8,
            "john_wick_le-1.02": 0x24594, "beatles-1.29": 0x44AC8}
    port = MP.read_port(str(PORTS / ("%s.port" % key)))
    pages = [port["site"]["challenge_pages_%d" % k][0] for k in range(4) if "challenge_pages_%d" % k in port["site"]]
    assert seen[key] in pages


def test_the_per_category_page_route_on_aerosmith_and_guardians():
    for key, cat in (("aerosmith-1.16", 4), ("aerosmith_le-1.16", 4), ("guardians-1.15", 5), ("guardians_le-1.15", 5)):
        port = MP.read_port(str(PORTS / ("%s.port" % key)))
        assert {"challenge_page", "challenge_page_text", "challenge_page_yield"} <= set(port["site"])
        assert int(port["value"]["challenge_page_cat"]) == cat


@pytest.mark.parametrize("before, start", [
    ([0xE12FFF1E, 0xE302CA0C, 0xE340C065, 0xE59CC000], 1),   # Sword of Rage: movw ip ; movt ip ; ldr ip, [ip] ; push
    ([0xE12FFF1E, 0xE307C8C4, 0xE340C075], 1),               # Avengers: movw ip ; movt ip ; push
    ([0xE12FFF1E, 0xE30B3AFC, 0xE30D16F0, 0xE3403069, 0xE3401052, 0xE5933000], 1),   # TMNT's list page: two pairs
    ([0xE12FFF1E, 0xE59CC000], 2),                           # a load alone is not the function's
    ([0xE12FFF1E, 0xE1A00000], 2),
])
def test_a_page_function_starts_before_the_set_up_of_its_push(before, start):
    """Wrapped at its push, Sword of Rage's champion page ran with ip unset and the game crashed in the attract mode."""
    w = before + [0xE92D4FF0, 0xE1A08000]
    assert PC._prologue_start(w, len(before)) == (start if start < len(before) else len(before))


def test_sword_of_rage_pages_are_wrapped_where_they_start():
    for key, va in (("sword_of_rage_le-1.19", 0x219BC), ("sword_of_rage_pro-1.19", 0x21908)):
        assert MP.read_port(str(PORTS / ("%s.port" % key)))["site"]["challenge_pages_0"][0] == va


def test_a_page_is_the_category_it_read_first_of_the_tables():
    """After a game Jaws' page reads category 39 entry 3 and 63 entry 0 after the row it shows, Godzilla 53 entry 1,
    Avengers shows the last scores under 55 (not one of its 38): the first read of one of the table's is the page's."""
    src = RUNTIME.read_text(encoding="utf-8")
    seen = src[src.index("static void chg_lookup_seen(unsigned *r)\n{"):]
    seen = seen[:seen.index("\n}\n")]
    assert "if (chg_pages_cat >= 0 || (int)r[0] <= 0 || (int)r[0] >= chg_pages_count) return;" in seen
    run = _host()._lift(src, "static unsigned chg_pages_run(int k, unsigned a0, unsigned a1, unsigned a2, unsigned a3,")
    assert run.index("chg_pages_count = chg_scores_count();") < run.index("ret = chg_pages_game[k](")


def test_a_games_page_cut_short_does_not_leave_the_pages_passed_through():
    """A game started during the game's own page: the call never returned, chg_pages_tid stayed set and every later
    page went straight to the game (Batman 66 1.14: no mode champion after a game)."""
    src = RUNTIME.read_text(encoding="utf-8")
    tick = src[src.index("static void chg_pages_tick(void)\n{"):]
    tick = tick[:tick.index("\n}\n")]
    clear = tick.index("if (chg_pages_tid && !chg_scores_running && (pm_in_game() || pm_ms() - chg_pages_call_ms > 60000))")
    assert tick.index("chg_pages_tid = 0;", clear) < tick.index("chg_pages_in = 0;", clear + 1)
    run = _host()._lift(src, "static unsigned chg_pages_run(int k, unsigned a0, unsigned a1, unsigned a2, unsigned a3,")
    assert run.index("chg_pages_call_ms = pm_ms();") < run.index("chg_pages_tid = me;")


# ---- the records' layout ------------------------------------------------------------------
# HIGHEST SCORES' compare (category 1's +0x10), word for word: The Beatles 1.29 (0x19d3ac) and Bond LE 1.06 (0x4e804c)
COMPARE_SHORT = [0xE92D40F8, 0xE1A07000, 0xE5914000, 0xE3A01054, 0xE1A06002, 0xE1A00004, 0xE1D455B4, 0xEBFE2805,
                 0xE1E00000, 0xE6FF3070, 0xE1550003, 0x0A000001, 0xE3A00000, 0xE8BD80F8, 0xE5973004, 0xE1A00006,
                 0xE12FFF33, 0xE5943050, 0xE1500003, 0x93A00000, 0x83A00001, 0xE8BD80F8]
COMPARE_BOND = [0xE92D40F8, 0xE1A07000, 0xE5914000, 0xE3A01058, 0xE1A06002, 0xE1A00004, 0xE1D455B8, 0xEBFD3DB6,
                0xE1E00000, 0xE6FF3070, 0xE1550003, 0x0A000001, 0xE3A00000, 0xE8BD80F8, 0xE5973004, 0xE1A00006,
                0xE12FFF33, 0xE1C424D8, 0xE1510003, 0x01500002, 0x83A00001, 0x93A00000, 0xE8BD80F8]


class _Prog:
    """A code segment at 0x10000 (the compare) and the category table at 0x20000, its category 1 pointing at it."""
    def __init__(self, compare):
        self.text_va, self.words = 0x10000, tuple(compare)
        self.data = {0x20000 + 36 + 16: 0x10000}

    def off(self, va):
        return va if va in self.data or self.text_va <= va < self.text_va + 4 * len(self.words) else None

    def word(self, va):
        return self.data[va] if va in self.data else self.words[(va - self.text_va) // 4]


def test_the_finder_names_a_record_layout_only_where_it_is_not_the_default():
    """The Beatles 1.29 / Star Wars ELG 1.10 keep a u32 score at +80 and the check at +84: a mode's record checked at
    +88 failed the game's check, the game reset the category, and no initials were asked (rig, The Beatles)."""
    assert PC.record_lines(_Prog(COMPARE_SHORT), 0x20000)[1:] == [
        "value challenge_record_check_at   84", "value challenge_record_score_at   80",
        "value challenge_record_score_size 4"]
    assert PC.record_lines(_Prog(COMPARE_BOND), 0x20000) == []             # u64 at +72, check at +88: the default
    assert PC.record_lines(_Prog(COMPARE_SHORT[:10]), 0x20000) == []        # not the known shape: nothing said
    for line in PC.record_lines(_Prog(COMPARE_SHORT), 0x20000)[1:]:
        key, rest = line.split(" ", 1)
        assert portgen.generated(key, rest), line


@pytest.mark.parametrize("key", ["beatles-1.29", "star_wars_elg-1.10", "james_bond_le-1.06", "turtles_le-1.59"])
def test_the_short_record_builds_name_their_layout(key):
    port = MP.read_port(str(PORTS / ("%s.port" % key)))
    got = {k: int(port["value"][k]) for k in ("challenge_record_check_at", "challenge_record_score_at",
                                               "challenge_record_score_size") if k in port["value"]}
    short = key in ("beatles-1.29", "star_wars_elg-1.10")
    assert got == ({"challenge_record_check_at": 84, "challenge_record_score_at": 80,
                    "challenge_record_score_size": 4} if short else {})


def test_the_runtime_takes_the_layout_from_the_port_and_refuses_one_that_does_not_fit():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = _host()._lift(src, "static void chg_scores_arm(void)")
    take = arm.index("chg_rec_check_at = (unsigned)check_at;")
    assert arm.index("check_at + 2 > CHG_REC_SIZE") < take < arm.index("scores_wrap_arm()")   # PAD-641: shared wrap
    for v, dflt in (("check_at", 88), ("score_at", 72), ("score_size", 8)):
        assert 'pm_port_value("challenge_record_%s", %d)' % (v, dflt) in arm
    # every read of a record's score goes through the layout (the attract pages' and the end-of-game wrap's)
    assert "+ 72)" not in src[src.index("#define CHG_REC_SIZE 96"):]


# ---- the one-screen cabinets' page title ----------------------------------------------------
def test_the_small_screen_titles_are_the_reported_800x480_panels():
    """A mode's champion title ran off the 800x480 panel of Star Wars Home Edition and The Pin ("PAD CHALLENGE
    CHAMPION" cut at both ends, rig): the panels are the reported ones, the only place that size is known."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("display2", ROOT / "tools" / "spike2_emu" / "display2.py")
    d2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d2)
    small = {t for t, v in d2.REPORTED_PANELS.items() if v.get("screen") == (800, 480)}
    assert set(PC.SMALL_SCREEN_TITLES) == small


def test_a_build_names_its_small_screen_by_its_own_title():
    class _E:
        def __init__(self, d):
            self.d = d
    assert PC.screen_lines(_E(b"x\0star_wars_elg\0y"))[1:] == ["value challenge_page_title_max 18"]
    assert PC.screen_lines(_E(b"x\0star_wars_le\0star_wars_elgx\0")) == []          # whole names only
    key, rest = PC.screen_lines(_E(b"\0jurassic_park_the_pin\0"))[1].split(" ", 1)
    assert portgen.generated(key, rest)


def test_only_the_small_screen_ports_cut_the_title():
    have = sorted(p.stem for p in PORTS.glob("*.port")
                  if "challenge_page_title_max" in MP.read_port(str(p)).get("value", {}))
    assert have == ["jurassic_park_the_pin-1.05", "star_wars_elg-1.10"]
    src = RUNTIME.read_text(encoding="utf-8")
    arm = _host()._lift(src, "static void chg_pages_arm(void)")
    assert 'pm_port_value("challenge_page_title_max", 27)' in arm and "chg_title_max = (unsigned)tmax;" in arm
