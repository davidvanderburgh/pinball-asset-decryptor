"""PAD-1449 (DoomWalrus666: "whenever a mode is selected from the start menu ... a dialog box ... would pop up and ask
if player wants to continue in Normal, Normal with Character Selection, or Enhanced"): the start menu carries one entry
per game of ours, and a game begun from it - on one of ours, the game's STANDARD or one of its challenges - holds ball 1
for a NORMAL / CHARACTERS / ENHANCED chooser (pad_mode_runtime.c "PAD-1449: the play styles")."""
import pathlib
import re

import numpy as np

from tests import test_spike2_mode_roster as R

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
PORTS = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "ports"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _array(src, name):
    return re.search(r"^static const char \*const %s\[3\] = [^;]*;" % name, src, re.M).group(0)


MAIN = r"""
#include <stdio.h>
#include <string.h>
#define pm_snprintf snprintf
#define TEAM_KIND 0x300u
#define STY_STANDARD 7u
#define STY_CHALLENGE 8u
enum { CI_OFF, CI_START, CI_FILM, CI_PLAY, CI_BALL, CI_LANG };
@ARR@
@FNS@
int main(void)
{
    static const unsigned ch[2] = { 4, 5 };
    char w[40];
    int k;
    /* the entry lists: kind 0 Standard, the port's challenge kind a challenge, Competition (1) and others none */
    printf("%u %u %u %u %u|", sty_own_of_kind(0, 3), sty_own_of_kind(3, 3), sty_own_of_kind(1, 3), sty_own_of_kind(4, 3),
           sty_own_of_kind(3, 0));
    /* Godzilla's index menu: 1 STANDARD, 3 COMPETITION, 4/5 the KOTM challenges, DJ MIXER (8) none */
    printf("%u %u %u %u %u %u|", sty_own_of_index(1, 1, ch, 2), sty_own_of_index(3, 1, ch, 2),
           sty_own_of_index(4, 1, ch, 2), sty_own_of_index(5, 1, ch, 2), sty_own_of_index(8, 1, ch, 2),
           sty_own_of_index(0, 1, ch, 2));
    for (k = 0; k < 3; k++) { sty_words(STY_STANDARD, 2, k, 1, w, sizeof w); printf("%s/", w); }
    sty_words(4u, 1, 0, 1, w, sizeof w); printf("%s/", w);
    sty_words(STY_CHALLENGE, 1, 0, 0, w, sizeof w); printf("%s/", w);
    sty_words(1u, 0, 2, 0, w, sizeof w); printf("%s|", w);
    /* up: the film, the intro before its ball; down 0.5 s; none seen: 2 s, or at once where the port cannot tell */
    printf("%d%d%d%d%d%d%d%d|", sty_may_show(1, 1, CI_OFF, 9999, 9999), sty_may_show(0, 1, CI_OFF, 100, 9999),
           sty_may_show(0, 1, CI_OFF, 600, 9999), sty_may_show(0, 0, CI_OFF, 0, 500), sty_may_show(0, 0, CI_OFF, 0, 2500),
           sty_may_show(-1, 0, CI_OFF, 0, 0), sty_may_show(0, 0, CI_PLAY, 0, 9999), sty_may_show(0, 0, CI_BALL, 0, 9999));
    /* Insider: Standard / a challenge while choosing or at CHARACTERS stays the game's own; ENHANCED and co-op not */
    printf("%d%d%d%d%d\n", coop_insider_free_in(1, 1, 0), coop_insider_free_in(1, 0, 2), coop_insider_free_in(1, 0, 3),
           coop_insider_free_in(0, 0, 2), coop_insider_free_in(0, 1, 0));
    return 0;
}
"""

FNS = ("static unsigned sty_own_of_kind(unsigned kind, unsigned challenge_kind)",
       "static unsigned sty_own_of_index(unsigned index, unsigned standard, const unsigned *challenges, unsigned n)",
       "static const char *sty_label(unsigned kind)",
       "static void sty_words(unsigned kind, int at, int phase, int action, char *out, unsigned cap)",
       "static int sty_may_show(int film_up, int film_seen, int intro_phase, unsigned long since_down, "
       "unsigned long since_open)",
       "static int coop_insider_free_in(int standard, int choosing, unsigned style)")


def test_the_chooser_follows_the_right_entries_and_says_its_styles(tmp_path):
    src = _src()
    code = MAIN.replace("@ARR@", _array(src, "STY_NAMES") + "\n" + _array(src, "STY_DOES")) \
        .replace("@FNS@", "\n".join(R._lift(src, s) for s in FNS))
    out = R._host_run(tmp_path, code, flags=("-no-pie",)).strip()
    menu_list, menu_index, words, show, insider = out.split("|")
    assert menu_list == "7 8 0 0 0"
    assert menu_index == "7 0 8 8 0 0"
    # 20 characters at most each: Godzilla LE's top line
    assert words.split("/") == ["STANDARD ENHANCED", "POWERS UP YOUR TEAM", "ACTION PICKS", "2 VS 2 CHARACTERS",
                                "CHALLENGE CHARACTERS", "FLIPPERS CHANGE"]
    assert all(len(w) <= 20 for w in words.split("/"))
    assert show == "00101101"
    assert insider == "11000"


def test_the_menu_and_the_game_wait_for_the_chooser():
    src = _src()
    kinds = R._lift(src, "static unsigned team_menu_kinds(unsigned *kinds)\n{")
    assert "6u" not in kinds                                       # ENHANCED CO-OP is off the menu
    serve = R._lift(src, "static unsigned ci_serve_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert serve.index("sty_hold();") < serve.index("ci_ball_hold(")   # the style before the intro and the pick
    assert "if (sty.open) return;" in R._lift(src, "static void coop_pick_open(unsigned t)\n{")
    assert "sty.open && sty.ready && id" in R._lift(src, "static int coop_hides(unsigned id)\n{")
    assert "!coop_insider_free()" in R._lift(src, "static int insider_holding_now(void)")
    assert "if (!coop.setting) return coop.style == 2u;" in R._lift(src, "static int coop_classic(void)")
    disp = R._lift(src, "static void on_team_dispatch(pm_reg *r)\n{")
    assert "sty_open(own);" in disp and "if (kind == 1u && sty_wanted()) sty_open(kind);" in disp
    assert "!sty.open && pm_in_game()" in R._lift(src, "static void coop_tick(void)\n{")   # no intro while choosing
    due = R._lift(src, "static int ci_film_due(void)\n{")
    assert "sty.kind == STY_STANDARD || sty.kind == STY_CHALLENGE" in due   # NORMAL is the game's own film


def test_the_app_draws_the_three_cards_with_the_pick():
    from pinball_decryptor.plugins.stern import coop_play as CP
    chars = CP.read_preset(CP.presets()["godzilla"])["characters"]
    scr = CP.pick_screens("", chars, CP.words_for())
    names = [s["name"] for s in scr]
    assert names[-3:] == ["PadCoopStyle_1", "PadCoopStyle_2", "PadCoopStyle_3"]
    assert any(n.startswith("PadCoopClassic_") for n in names)           # CHARACTERS plays Classic
    for s in scr[-3:]:
        assert s["art_rgba"].shape == (CP.CARD_SIZE[1], CP.CARD_SIZE[0], 4) and (s["x"], s["y"]) == CP.CARD_AT
    a = CP.style_card("", chars, 2, chars.get("theme"), team="your Godzilla team")
    b = CP.style_card("", chars, 2, chars.get("theme"))
    assert not np.array_equal(a, b)                                       # the words name the title's team
    assert CP.STYLES[2][2].format(team="your Godzilla team").startswith("Enhanced powers up your Godzilla team")
    assert [s[0] for s in CP.STYLES] == ["NORMAL", "CHARACTERS", "ENHANCED"]


def test_godzillas_challenges_are_named_in_its_ports():
    for port in ("godzilla_le-1.16.port", "godzilla_pro-1.16.port"):
        text = (PORTS / port).read_text(encoding="utf-8")
        got = re.findall(r"^value comp_menu_challenge_(\d+) +(\d+)", text, re.M)
        assert got == [("0", "4"), ("1", "5")], port                  # KING OF THE MONSTERS and its TIME ATTACK
    for port in PORTS.glob("*.port"):                                 # only where the index menu is known
        text = port.read_text(encoding="utf-8")
        if "comp_menu_challenge_" in text:
            assert "comp_menu_end_index" in text, port.name
