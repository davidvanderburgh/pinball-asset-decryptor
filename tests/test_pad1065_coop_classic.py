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
    fns = (R._lift(src, "static unsigned coop_row_mode(unsigned v)")
           + R._lift(src, "static int insider_holding(unsigned while_at, unsigned value)"))
    main = "#include <stdio.h>\n" + fns + r"""
int main(void)
{
    unsigned v;
    for (v = 0; v <= 7; v++) printf("%u", coop_row_mode(v));
    printf(" ");
    for (v = 0; v <= 7; v++) printf("%d", insider_holding(1, v));
    printf(" %d\n", insider_holding(0, 0));
    return 0;
}
"""
    # PAD-1073: 0 Off, 1 Classic, 2 Enhanced; an older row's 3 reads Enhanced, 4-6 Classic; Insider held back for 1-6
    assert R._host_run(tmp_path, main).strip() == "01221110 01111110 1"


CHAR_UP_MAIN = r"""
#include <stdio.h>
struct coop_char { const char *name; };
static struct { unsigned setting, turn, teams_always, style; int onoff; unsigned rowsty; } coop;   /* style: PAD-1449; onoff: Simon */
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
    fns = (R._lift(src, "static unsigned coop_row_mode(unsigned v)") + R._lift(src, "static int coop_row_styles(void)")
           + R._lift(src, "static int coop_classic(void)")
           + R._lift(src, "static const struct coop_char *coop_char_up(void)"))
    out = R._host_run(tmp_path, CHAR_UP_MAIN.replace("@FNS@", fns), flags=("-no-pie",)).strip()
    assert out == ("MECHAGODZILLA - MECHAGODZILLA MECHAGODZILLA - - - MECHAGODZILLA | up")   # PAD-1073: 1 Classic


def test_every_ability_waits_on_classic():
    src = _src()
    close = R._lift(src, "static void coop_pick_close(const char *how)")
    assert "if (c >= 0 && !coop_classic()) coop_gift(&coop_ch[c]);" in close
    assert "if (c >= 0 && !coop_classic()) coop_counts_give(&coop_ch[c]);" in close
    assert "&& coop_adj_game && !coop_classic() && !ci.holding) {" in close   # the pick's late ball save (PAD-1215)
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
    assert names[n + 1:2 * n + 1] == ["PadCoopClassic_%d" % (i + 1) for i in range(n)]      # then drawn over them
    views = names[2 * n + 1:-3]                                       # PAD-1450: the view cards, their Classic
    assert views[:n] == ["PadCoopView_%d" % (i + 1) for i in range(n)] and views[-1] == "PadCoopPeek"
    assert all(v.startswith("PadCoopViewClassic_") for v in views[n:-1])
    assert names[-3:] == ["PadCoopStyle_1", "PadCoopStyle_2", "PadCoopStyle_3"]     # PAD-1449: the style chooser's
    for i in (0, 5, n - 1):
        patch = scr[n + 1 + i]
        h, w = patch["art_rgba"].shape[:2]
        assert w % 4 == 0 and h % 4 == 0 and w * h < CP.CARD_SIZE[0] * CP.CARD_SIZE[1] // 4   # a strip, not a card
        x, y = int(patch["x"]) - CP.CARD_AT[0], int(patch["y"]) - CP.CARD_AT[1]
        laid = CP.pick_card(None, chars, i, words, chars.get("theme")).copy()
        laid[y:y + h, x:x + w] = patch["art_rgba"]
        plain = dict(chars, list=[dict(c, powers=[], header="") if k == i else c for k, c in enumerate(chars["list"])])
        assert np.array_equal(laid, CP.pick_card(None, plain, i, words, chars.get("theme")))   # exactly that card


def test_no_patches_when_not_asked_or_without_an_ability():
    CP, chars = _godzilla()
    assert not [s for s in CP.pick_screens(None, chars, CP.words_for(), classic=False)
                if s["name"].startswith("PadCoopClassic_")]
    # PAD-1449: by default they are there - the start menu's style chooser plays CHARACTERS (Classic) on any card
    assert [s for s in CP.pick_screens(None, chars, CP.words_for()) if s["name"].startswith("PadCoopClassic_")]
    none = dict(chars, list=[dict(c, powers=[], header="") for c in chars["list"]])
    assert CP.classic_patch(None, none, 0) is None                                    # its card says so already


def test_the_menu_and_the_app_name_classic():
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.webui import help_content
    from pinball_decryptor.webui.tabs import modes as M
    # Simon (2026-11-27): the row the app writes is Off / On (an older card's three-value row still reads 1 as Classic)
    assert CP.MENU_VALUES == 2 and CP.MENU_ON == 1
    assert len(CP.MENU_HELP) <= 63
    # PAD-1443: no row is written unless ticked; PAD-1449: a game picked on the
    # start menu asks NORMAL, CHARACTERS (Classic: a character, no ability) or ENHANCED
    assert "**CHARACTERS** (each player picks a character at their first ball, with no special abilities)" in         str(help_content.__dict__)
    assert "CHARACTERS (a character each, no special abilities)" in M.ModesTab.COOP_TIP
