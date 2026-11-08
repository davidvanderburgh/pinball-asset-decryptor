"""PAD-1065: Co-op, Team 2v2 and Team 2v1 Classic - CO-OP PLAY 4, 5 and 6 play 1, 2 and 3's games with the characters
picked but no special abilities (pad_mode_runtime.c "PAD-1065", coop_play.classic_patch)."""
import pathlib

import numpy as np

from tests import test_spike2_mode_roster as R

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def test_4_to_6_play_1_to_3s_games(tmp_path):
    src = _src()
    fns = (R._lift(src, "static unsigned coop_menu_game(unsigned v)")
           + R._lift(src, "static unsigned coop_teams_size(unsigned always, unsigned setting_value, int has_setting)")
           + R._lift(src, "static int insider_holding(unsigned while_at, unsigned value)"))
    main = "#include <stdio.h>\n" + fns + r"""
int main(void)
{
    unsigned v;
    for (v = 0; v <= 7; v++) printf("%u", coop_menu_game(v));
    printf(" ");
    for (v = 0; v <= 7; v++) printf("%u", coop_teams_size(0, v, 1));
    printf(" ");
    for (v = 0; v <= 7; v++) printf("%d", insider_holding(1, v));
    printf(" %d\n", insider_holding(0, 0));
    return 0;
}
"""
    # 4 Co-op Classic is co-op (no team game), 5 is 2v2 (4 players), 6 is 2v1 (3); Insider held back for 1-6
    assert R._host_run(tmp_path, main).strip() == "01231237 04300430 01111110 1"


CHAR_UP_MAIN = r"""
#include <stdio.h>
struct coop_char { const char *name; };
static struct { unsigned setting, turn, teams_always; } coop;
static unsigned row;
static int coop_pick_of[5];
static struct coop_char coop_ch[2] = { { "GODZILLA 1954" }, { "MECHAGODZILLA" } };
static int coop_ch_n = 2;
static unsigned coop_teammates(void) { return 2; }
@FNS@
int main(void)
{
    unsigned v;
    coop.setting = (unsigned)(unsigned long)&row;
    coop.turn = 2;
    coop_pick_of[2] = 1;
    for (v = 0; v <= 7; v++) {
        row = v;
        printf("%s%s", v ? " " : "", coop_char_up() ? coop_char_up()->name : "-");
    }
    coop.setting = 0;                                   /* no row: co-op always on, Enhanced */
    printf(" | %s\n", coop_char_up() ? "up" : "-");
    return 0;
}
"""


def test_classic_has_no_character_up(tmp_path):
    src = _src()
    fns = R._lift(src, "static int coop_classic(void)") + R._lift(src, "static const struct coop_char *coop_char_up(void)")
    out = R._host_run(tmp_path, CHAR_UP_MAIN.replace("@FNS@", fns), flags=("-no-pie",)).strip()
    assert out == ("MECHAGODZILLA MECHAGODZILLA MECHAGODZILLA MECHAGODZILLA - - - MECHAGODZILLA | up")


def test_every_ability_waits_on_classic():
    src = _src()
    close = R._lift(src, "static void coop_pick_close(const char *how)")
    assert "if (c >= 0 && !coop_classic()) coop_gift(&coop_ch[c]);" in close
    assert "if (c >= 0 && !coop_classic()) coop_counts_give(&coop_ch[c]);" in close
    assert "&& coop_adj_game && !coop_classic()) {" in close                  # the pick's late ball save
    turn = R._lift(src, "static void coop_chars_turn(void)")
    assert "&& !coop_classic())\n        coop_gift(" in turn                  # a gift at every turn
    say = R._lift(src, "static void coop_pick_say(void)")
    assert "|| coop_classic()) pm_snprintf" in say                           # the top line never says what one does
    # the rest (adjustments, record holds, counts, lit shots, yes/double, unlocks, the Action button) ask coop_char_up
    for sig in ("static unsigned coop_adj_answer(unsigned id, unsigned own)\n{", "static void coop_cache_hold(void)",
                "static void coop_lit_tick(void)", "static void coop_double_tick(void)",
                "static void coop_rules_watch(void)"):
        assert "coop_char_up()" in R._lift(src, sig), sig
    tick = R._lift(src, "static void coop_screens_tick(void)")
    assert '"PadCoopClassic_%d"' in tick and "coop_classic() ? want : -1" in tick


def _godzilla():
    from pinball_decryptor.plugins.stern import coop_play as CP
    pre = CP.read_preset(CP.presets()["godzilla"])
    return CP, CP._characters(pre.get("characters") or pre)


def test_each_classic_patch_turns_its_card_into_no_special_ability():
    CP, chars = _godzilla()
    words = CP.words_for()
    scr = CP.pick_screens(None, chars, words, classic=True)
    n = len(chars["list"])
    names = [s["name"] for s in scr]
    assert names[:n + 1] == ["PadCoop_%d" % (i + 1) for i in range(n)] + ["PadCoop_Random"]   # the cards first
    assert names[n + 1:] == ["PadCoopClassic_%d" % (i + 1) for i in range(n)]               # then drawn over them
    for i in (0, 5, n - 1):
        patch = scr[n + 1 + i]
        h, w = patch["art_rgba"].shape[:2]
        assert w % 4 == 0 and h % 4 == 0 and w * h < CP.CARD_SIZE[0] * CP.CARD_SIZE[1] // 4   # a strip, not a card
        x, y = int(patch["x"]) - CP.CARD_AT[0], int(patch["y"]) - CP.CARD_AT[1]
        laid = CP.pick_card(None, chars, i, words, chars.get("theme")).copy()
        laid[y:y + h, x:x + w] = patch["art_rgba"]
        plain = dict(chars, list=[dict(c, ability="") if k == i else c for k, c in enumerate(chars["list"])])
        assert np.array_equal(laid, CP.pick_card(None, plain, i, words, chars.get("theme")))   # exactly that card


def test_no_patches_without_the_service_menu_row_or_an_ability():
    CP, chars = _godzilla()
    assert not [s for s in CP.pick_screens(None, chars, CP.words_for(), classic=False)
                if s["name"].startswith("PadCoopClassic_")]
    assert not [s for s in CP.pick_screens(None, chars, CP.words_for())                # no project: no menu row
                if s["name"].startswith("PadCoopClassic_")]
    none = dict(chars, list=[dict(c, ability="") for c in chars["list"]])
    assert CP.classic_patch(None, none, 0) is None                                    # its card says so already


def test_the_menu_and_the_app_name_classic():
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.webui import help_content
    from pinball_decryptor.webui.tabs import modes as M
    assert CP.MENU_VALUES == 7 and (CP.MENU_COOP_CLASSIC, CP.MENU_TEAMS_CLASSIC, CP.MENU_TEAMS_2V1_CLASSIC) == (4, 5, 6)
    assert len(CP.MENU_HELP) <= 63 and "Enhanced 1 Co-op 2 2v2 3 2v1. 4-6 Classic" in CP.MENU_HELP
    assert "**4, 5 and 6 (Classic):** Co-op, Team 2v2 and Team 2v1" in str(help_content.__dict__)
    assert "4, 5 and 6 the same three Classic (characters picked, no special abilities)" in M.ModesTab.COOP_MENU_TIP
