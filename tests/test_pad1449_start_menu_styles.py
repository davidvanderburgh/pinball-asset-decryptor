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
#define STY_MENU_IDLE_MS 60000ul
#define STY_MENU_GONE_MS 3000ul
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
    /* round 2: the game start's wait on the menu - on; Start; a minute alone; the menu gone 3 s */
    printf("%d%d%d%d%d|", sty_menu_wait(0, 0, 0), sty_menu_wait(1, 70000, 9000), sty_menu_wait(0, 60000, 0),
           sty_menu_wait(0, 59999, 3000), sty_menu_wait(0, 59999, 2999));
    for (k = 0; k < 6; k++) {   /* the menu's line: the game and the style, then what it is */
        sty_menu_words(k < 2 ? STY_STANDARD : k < 4 ? 1u : 4u, k < 2 ? 2 : k < 4 ? 1 : 0, k & 1,
                       "YOUR GODZILLA TEAM", w, sizeof w);
        printf("%s/", w);
    }
    printf("|");
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
       "static int coop_insider_free_in(int standard, int choosing, unsigned style)",
       "static int sty_menu_wait(int pressed, unsigned long idle, unsigned long unseen)",
       "static void sty_menu_words(unsigned kind, int at, int phase, const char *team, char *out, unsigned cap)")


def test_the_chooser_follows_the_right_entries_and_says_its_styles(tmp_path):
    src = _src()
    code = MAIN.replace("@ARR@", _array(src, "STY_NAMES") + "\n" + _array(src, "STY_DOES")) \
        .replace("@FNS@", "\n".join(R._lift(src, s) for s in FNS))
    out = R._host_run(tmp_path, code, flags=("-no-pie",)).strip()
    menu_list, menu_index, words, show, press, line, insider = out.split("|")
    assert line.split("/")[:-1] == ["STANDARD ENHANCED", "POWERS UP YOUR GODZILLA TEAM", "CO-OP CHARACTERS",
                                    "NO SPECIAL ABILITIES", "2 VS 2 NORMAL", "THE GAME AS IT IS"]
    assert press == "01230"
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
    assert "sty_begin(own);" in disp and "if (kind == 1u && sty_wanted()) sty_begin(kind);" in disp
    assert "sty_open(" not in disp                                  # round 2: the menu's style first, else the card
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


def test_round2_the_menu_asks_before_the_game_starts():
    """PAD-1449 round 2: the game start begun from the menu waits while the menu asks; the flippers walk the style off
    the menu's buttons; the next Start lets the game start go on with it, and ball 1 shows no card"""
    src = _src()
    wrap = R._lift(src, "static unsigned coop_start_game_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3, "
                        "unsigned s0)")
    assert wrap.index("sty_menu_ask();") < wrap.index("lb_start_game(")
    ask = R._lift(src, "static void sty_menu_ask(void)\n{")
    assert "!sty_menu_live()" in ask and "proc_sleep" in ask and "smn.preset = smn.at + 1;" in ask
    assert "sty_menu_edge(id, (level & 1u) == closed);" in R._lift(
        src, "static void coop_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity)\n{")
    frame = R._lift(src, "static void team_menu_frame(pm_reg *r)\n{")
    assert frame.index("sty_menu_walk(&r[breg], 4u, 2u);") < frame.index("c = comp_frame_cursor(")
    tick = R._lift(src, "static void sty_tick(void)\n{")
    assert tick.index('sty_close("taken on the start menu");') < tick.index('"styles: the chooser is up')
    begin = R._lift(src, "static void sty_begin(unsigned kind)\n{")
    assert "sty.preset = sty_menu_preset(kind);" in begin
    # the Competition and MODE CHALLENGE entries leave the flippers to the step
    assert "sty_menu_up() ? 0u : r[breg] & 4u" in R._lift(src, "static void comp_menu_frame(pm_reg *r)\n{")
    assert "if (on && !sty_menu_up())" in R._lift(src, "static void challenge_menu_frame(pm_reg *r)\n{")


def test_round2_challenge_names_in_the_index_menu_ports():
    for port in ("godzilla_le-1.16.port", "godzilla_pro-1.16.port"):
        text = (PORTS / port).read_text(encoding="utf-8")
        got = re.findall(r"^value comp_menu_challenge_msg_(\d+) +(\d+)", text, re.M)
        assert got == [("0", "3275"), ("1", "3276")], port            # KING OF THE MONSTERS, TIME ATTACK
    for port in PORTS.glob("*.port"):
        text = port.read_text(encoding="utf-8")
        assert "comp_menu_take" not in text, port.name
        if "comp_menu_challenge_msg_" in text:
            assert "comp_menu_challenge_0" in text, port.name
