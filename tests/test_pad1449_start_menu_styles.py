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
    /* round 4: Action on the menu - no entry of ours; the style step opens; TEAMS' team step; the team taken; the
     * style taken - then the style Start keeps: the one shown, (TEAMS' team step up) NORMAL, the one taken, none */
    printf("%d%d%d%d%d,%d%d%d%d|", sty_menu_act(0, 0, 0, 0), sty_menu_act(0, 0, 0, 1), sty_menu_act(0, 0, 1, 1),
           sty_menu_act(1, 1, 1, 1), sty_menu_act(1, 0, 0, 1), sty_menu_go_style(1, 0, 2, 0),
           sty_menu_go_style(1, 1, 2, 0), sty_menu_go_style(0, 0, 0, 2), sty_menu_go_style(0, 0, 0, 0));
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
       "static int sty_menu_act(int open, int shaping, int teams, int chooser)",
       "static int sty_menu_go_style(int open, int shaping, int at, int taken)",
       "static void sty_menu_words(unsigned kind, int at, int phase, const char *team, char *out, unsigned cap)")


def test_the_chooser_follows_the_right_entries_and_says_its_styles(tmp_path):
    src = _src()
    code = MAIN.replace("@ARR@", _array(src, "STY_NAMES") + "\n" + _array(src, "STY_DOES")) \
        .replace("@FNS@", "\n".join(R._lift(src, s) for s in FNS))
    out = R._host_run(tmp_path, code, flags=("-no-pie",)).strip()
    menu_list, menu_index, words, show, press, line, insider = out.split("|")
    assert line.split("/")[:-1] == ["STANDARD ENHANCED", "POWERS UP YOUR GODZILLA TEAM", "CO-OP CHARACTERS",
                                    "NO SPECIAL ABILITIES", "2 VS 2 NORMAL", "THE GAME AS IT IS"]
    assert press == "01234,3121"
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
    assert "sty.open ? sty.preset == 1 : coop.plain," in R._lift(
        src, "static void coop_tick(void)\n{")   # no intro while choosing (unless the film just took it), round 5
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


def test_round4_the_menu_asks_on_action_and_the_game_start_never_waits():
    """PAD-1449 round 4 (DoomWalrus666: Action the selector, Start only to start; a menu timing out never starts a
    game and starts over): Action works the step on the menu's own frame, Start only keeps what the entry says, and the
    game start does not wait"""
    src = _src()
    wrap = R._lift(src, "static unsigned coop_start_game_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3, "
                        "unsigned s0)")
    assert wrap.index("sty_menu_begin();") < wrap.index("lb_start_game(")
    begin = R._lift(src, "static void sty_menu_begin(void)\n{")
    assert "proc_sleep" not in begin and "smn.preset = smn.go_style;" in begin and "tm.seen_ms = pm_ms();" in begin
    assert "sty_menu_ask" not in src and "sty_menu_take" not in src and "STY_MENU_IDLE_MS" not in src
    edge = R._lift(src, "static void sty_menu_edge(unsigned id, int press)")
    assert "!sty_menu_live()" in edge and "smn.hold_ms = pm_ms() | 1ul;" in edge and "smn.act = 1;" in edge and "sty_menu_go();" in edge
    assert "sty_menu_edge(id, (level & 1u) == closed);" in R._lift(
        src, "static void coop_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity)\n{")
    frame = R._lift(src, "static void team_menu_frame(pm_reg *r)\n{")
    assert frame.index("sty_menu_walk(&r[breg], 4u, 2u);") < frame.index("c = comp_frame_cursor(") \
        < frame.index("sty_menu_frame(c, ")
    walk = R._lift(src, "static void sty_menu_walk(pm_reg *buttons, unsigned lbit, unsigned rbit)")
    assert "STY_MENU_GONE_MS) {" in walk and 'sty_menu_reset("the menu is up again");' in walk \
        and "smn.go_ms = 0;" in walk                                   # a menu back after a gap starts over
    assert "pm_ms() - smn.frame_ms < STY_MENU_GONE_MS" in R._lift(src, "static int sty_menu_up(void)\n{")
    fr = R._lift(src, "static void sty_menu_frame(unsigned c, int teams, int ours, unsigned std_msg, unsigned index)")
    assert "if ((long)c != smn.entry) {" in fr and "smn.taken = smn.at + 1;" in fr
    tick = R._lift(src, "static void sty_tick(void)\n{")
    assert tick.index('sty_close("taken on the start menu");') < tick.index('"styles: the chooser is up')
    assert "sty.preset = sty_menu_preset(kind);" in R._lift(src, "static void sty_begin(unsigned kind)\n{")
    # the Competition and MODE CHALLENGE entries leave the flippers to the step
    assert "sty_menu_up() ? 0u : r[breg] & 4u" in R._lift(src, "static void comp_menu_frame(pm_reg *r)\n{")
    assert "if (on && !sty_menu_up())" in R._lift(src, "static void challenge_menu_frame(pm_reg *r)\n{")


def test_round4_menu_lines_action_kept_from_the_menu_and_no_intro_in_standard(tmp_path):
    """PAD-1449 round 4: the line with no step up (the style taken, then START TO PLAY; none, ACTION TO CHOOSE); the
    game start the menu's Action began held back on an entry the chooser is for; no co-op intro in Standard"""
    src = _src()
    code = (r"""
#include <stdio.h>
#define pm_snprintf snprintf
#define STY_STANDARD 7u
#define STY_CHALLENGE 8u
""" + _array(src, "STY_NAMES") + "\n" + R._lift(src, "static const char *sty_label(unsigned kind)") + "\n"
            + R._lift(src, "static int sty_menu_rest_words(unsigned kind, int taken, int phase, char *out, unsigned cap)")
            + "\n#define STY_MENU_ACT_MS 600ul\n#define STY_MENU_LIVE_MS 500ul\n"
            + R._lift(src, "static int sty_menu_hold_back(unsigned long since_frame, unsigned long since_act, int go, "
                           "int chooser)") + r"""
int main(void)
{
    char w[40];
    int k, r;
    for (k = 0; k < 4; k++) {
        w[0] = 0;
        r = sty_menu_rest_words(k < 2 ? STY_STANDARD : 4u, k < 2 ? 2 : 0, k & 1, w, sizeof w);
        printf("%d%s/", r, w);
    }
    /* Action just now on the live menu; 700 ms ago; the menu not seen for 600 ms; a Start since (the Home Team
     * screen's own Action); no chooser on the entry */
    printf("|%d%d%d%d%d\n", sty_menu_hold_back(16, 40, 0, 1), sty_menu_hold_back(16, 700, 0, 1),
           sty_menu_hold_back(600, 40, 0, 1), sty_menu_hold_back(16, 40, 1, 1), sty_menu_hold_back(16, 40, 0, 0));
    return 0;
}
""")
    out = R._host_run(tmp_path, code, flags=("-no-pie",)).strip()
    words, want = out.split("|")
    assert words.split("/")[:-1] == ["1STANDARD CHARACTERS", "1START TO PLAY", "0", "1ACTION TO CHOOSE"]
    assert want == "10000"
    wrap = R._lift(src, "static unsigned coop_start_game_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3, "
                        "unsigned s0)")
    assert wrap.index("if (sty_menu_held()) return 0;") < wrap.index("sty_menu_begin();") < wrap.index("lb_start_game(")
    held = R._lift(src, "static int sty_menu_held(void)\n{")
    assert "smn.go_ms != 0" in held and "smn.hold_ms = 0;" in held
    # (the drain's edge opened the step; only round 6's Home Team hand-back opens it here)
    assert "smn.act = 1;" not in held.split("if (smn.home_ms) {")[0]
    # Action on the live menu's chooser entries never reaches the game (the drain hides it), unless a Start came first
    assert "id == coop_action && sty_menu_owns_action()" in R._lift(src, "static int coop_hides(unsigned id)\n{")
    takes = R._lift(src, "static int sty_menu_owns_action(void)\n{")
    assert "sty_menu_live()" in takes and "!smn.go_ms" in takes and "sty_menu_kind() == 0u) return 0;" in takes
    assert "comp_menu_keys" not in src
    # the game's own hint line under the menu, found by its words, says what Action and Start do on our entries
    hint = R._lift(src, "static const char *sty_hint_words(int open, int taken)")
    assert '"USE FLIPPERS TO CHANGE / ACTION TO SELECT"' in hint and '"START TO PLAY / ACTION TO CHANGE"' in hint         and '"USE FLIPPERS TO CHANGE / ACTION TO CHOOSE"' in hint
    find = R._lift(src, "static int sty_hint_find(void)")
    assert 'sf_has(w, "flippers to change") && sf_has(w, "start to select")' in find
    assert "sty_menu_hint(0);" in R._lift(src, "static void sty_menu_begin(void)")         and "sty_menu_hint(0);" in R._lift(src, "static void sty_menu_walk(pm_reg *buttons, unsigned lbit, unsigned rbit)")
    # no co-op intro in the game's own Standard or a challenge
    assert "!coop.standard && !coop.plain && ci.clip[0] && !ci.phase" in R._lift(src, "static void sty_close(const char *how)")
    # co-op or teams at NORMAL: the game's own start - the menu's style while the chooser waits, coop.plain after
    assert "if (sty.open ? sty.preset == 1 : coop.plain) return 0;" in R._lift(src, "static int ci_film_due(void)\n{")
    assert "if (!ci.phase && !coop.standard) coop_intro_begin(" in R._lift(src, "static void coop_pick_open(unsigned t)\n{")
    assert "coop_teammates() && !coop.standard && ci.game" in R._lift(src, "static int ci_film_due(void)\n{")
    assert "prefilm" not in src


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


def test_round3_one_teams_entry_asks_the_team_game_then_the_style(tmp_path):
    """PAD-1449 round 3 (DoomWalrus666: "Standard, Challenge, Co-op, Teams ... when choosing one, the dialog opens"):
    one TEAMS entry whose step says the team game and who plays it, then the style; the caption over ours"""
    src = _src()
    shapes = re.search(r"^static const unsigned TEAM_SHAPES\[3\] = [^;]*;", src, re.M).group(0)
    does = re.search(r"^static const char \*const TEAM_SHAPE_DOES\[3\] = [^;]*;", src, re.M).group(0)
    code = (r"""
#include <stdio.h>
#define pm_snprintf snprintf
#define STY_STANDARD 7u
#define STY_CHALLENGE 8u
""" + shapes + "\n" + does + "\n" + R._lift(src, "static const char *sty_label(unsigned kind)") + "\n"
            + R._lift(src, "static void sty_menu_shape_words(int at, int phase, char *out, unsigned cap)") + r"""
int main(void)
{
    char w[40];
    int k;
    for (k = 0; k < 6; k++) { sty_menu_shape_words(k / 2, k & 1, w, sizeof w); printf("%s/", w); }
    printf("\n");
    return 0;
}
""")
    out = R._host_run(tmp_path, code, flags=("-no-pie",)).strip()
    assert out.split("/")[:-1] == ["TEAMS 2 VS 2", "4 PLAYERS, 2 PER TEAM", "TEAMS 2 VS 1", "3 PLAYERS, 2 AGAINST 1",
                                   "TEAMS 3 VS 1", "4 PLAYERS, 3 AGAINST 1"]
    fr = R._lift(src, "static void sty_menu_frame(unsigned c, int teams, int ours, unsigned std_msg, unsigned index)")
    assert fr.index("case 2:") < fr.index("smn.shaping = 1;") < fr.index("case 3:") \
        < fr.index("smn.team = smn.kind = TEAM_SHAPES[smn.shape_at];") < fr.index("tm.kind = smn.team;") \
        < fr.index("case 4:")                                    # round 4: Action takes the team game, then the style
    assert "kinds[n++] = TEAM_TEAMS;" in R._lift(src, "static unsigned team_menu_kinds(unsigned *kinds)\n{")
    assert "if (kind == TEAM_TEAMS) kind = smn.team ? smn.team : 4u;" in R._lift(
        src, "static void on_team_dispatch(pm_reg *r)\n{")
    assert "tm.kind == TEAM_TEAMS" in R._lift(src, "static unsigned sty_menu_kind(void)")
    assert "if (smn.shaping) {" in R._lift(src, "static void sty_menu_walk(pm_reg *buttons, unsigned lbit, unsigned rbit)")


def test_round3_the_index_menu_ports_name_standards_caption():
    seen = 0
    for port in PORTS.glob("*.port"):
        text = port.read_text(encoding="utf-8")
        if "comp_menu_end_msg" not in text:
            continue
        got = re.findall(r"^value comp_menu_end_caption_msg +(\d+)", text, re.M)
        assert got == ["1914"], port.name                              # STANDARD, beside its NORMAL PLAY (1915)
        seen += 1
    assert seen == 12                                                  # PAD-1477: + Godzilla Pro 1.15
    from pinball_decryptor.plugins.stern import prolonged_comp as P
    assert "standard_caption(e)" in pathlib.Path(P.__file__).read_text(encoding="utf-8")   # frame_lines writes it


def test_round4_the_serve_music_under_standards_intro(tmp_path):
    """PAD-1449 round 4 (DoomWalrus666: "Stock music should play during the standard stock intro video and not wait for
    character selection"): ball 1 held for a Standard or challenge pick asks for the serve's music as the hold begins"""
    src = _src()
    code = (r"""
#include <stdio.h>
#define STY_STANDARD 7u
#define STY_CHALLENGE 8u
""" + R._lift(src, "static int srv_music_wanted(unsigned music, unsigned kind, int preset, int open, unsigned ball)") + r"""
int main(void)
{
    /* Standard CHARACTERS; a challenge ENHANCED; Standard NORMAL; no port value; a co-op game; ball 2; chooser shut */
    printf("%d%d%d%d%d%d%d\n", srv_music_wanted(66, STY_STANDARD, 2, 1, 1), srv_music_wanted(66, STY_CHALLENGE, 3, 1, 1),
           srv_music_wanted(66, STY_STANDARD, 1, 1, 1), srv_music_wanted(0, STY_STANDARD, 2, 1, 1),
           srv_music_wanted(66, 1u, 2, 1, 1), srv_music_wanted(66, STY_STANDARD, 2, 1, 2),
           srv_music_wanted(66, STY_STANDARD, 2, 0, 1));
    return 0;
}
""")
    assert R._host_run(tmp_path, code, flags=("-no-pie",)).strip() == "1100000"
    serve = R._lift(src, "static unsigned ci_serve_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)\n{")
    assert serve.index("srv_music_early();") < serve.index("sty_hold();") < serve.index("ci_serve_game(")
    # round 5 (DoomWalrus666: "Why does the stock music not play on the intro in the Pro code"): request 66 is SE GZ MX
    # MAIN PLAY START on every Godzilla build (the program's own Sound Test names), so every Godzilla port whose ball 1
    # can wait for the pick (`serve_ball`) names it
    held = [f for f in sorted(PORTS.glob("godzilla_*.port"))
            if re.search(r"^site serve_ball ", f.read_text(encoding="utf-8"), re.M)]
    assert [f.name for f in held] == ["godzilla_le-1.16.port", "godzilla_pro-1.16.port"]
    for f in held:
        assert re.search(r"^value serve_music +66$", f.read_text(encoding="utf-8"), re.M), f.name


def test_round5_one_intro_only_for_coop_and_teams_with_characters(tmp_path):
    """PAD-1449 round 5 (DoomWalrus666: "The co-op video should be the default intro video for: Co-op (characters or
    enhanced), Teams (characters or Enhanced) ... never ... Standard (regular, characters, enhanced)"; "ONE INTRO VIDEO
    ON ALL MODES"; "Co-op characters currently plays the co-op/teams intro video with NO MUSIC"; "Challenge should only
    have regular version"; "Only after the ball has been put into the shooter Lane should the handicap settings be able
    to be manipulated"; "Any handicap selections should not carry over to the next game ever")"""
    src = _src()
    code = (r"""
#include <stdio.h>
#define STY_STANDARD 7u
#define STY_CHALLENGE 8u
#define HAND_FILM_MS 30000ul
""" + R._lift(src, "static int ci_tick_begins(unsigned n, int have, int phase, int standard, int plain, int chooser, "
                   "int film_fresh,")
     + "\n" + R._lift(src, "static unsigned sty_chooser_own(unsigned own)")
     + "\n" + R._lift(src, "static int hand_may_open(int film_up, unsigned long since_new, int intro, int chooser, "
                       "int waits, int unserved)") + r"""
int main(void)
{
    /* co-op CHARACTERS, chooser shut; Standard (CHARACTERS / ENHANCED); co-op NORMAL; chooser open, no film swap;
     * chooser open, the film just swapped for the intro; asked already this game; no teammates; under way */
    printf("%d%d%d%d%d%d%d%d|", ci_tick_begins(2, 1, 0, 0, 0, 0, 0, 1, 0), ci_tick_begins(1, 1, 0, 1, 0, 0, 0, 1, 0),
           ci_tick_begins(2, 1, 0, 0, 1, 0, 0, 1, 0), ci_tick_begins(2, 1, 0, 0, 0, 1, 0, 1, 0),
           ci_tick_begins(2, 1, 0, 0, 0, 1, 1, 1, 0), ci_tick_begins(2, 1, 0, 0, 0, 0, 0, 1, 1),
           ci_tick_begins(0, 1, 0, 0, 0, 0, 0, 1, 0), ci_tick_begins(2, 1, 1, 0, 0, 0, 0, 1, 0));
    printf("%u %u %u|", sty_chooser_own(STY_STANDARD), sty_chooser_own(STY_CHALLENGE), sty_chooser_own(0));
    /* the game's film up early; up 40 s in (a stale word); an intro; the chooser; ball 1 still to come; waiting in
     * the lane; launched (served before); a port with no plunger flags */
    printf("%d%d%d%d%d%d%d%d\n", hand_may_open(1, 2000, 0, 0, 1, 0), hand_may_open(1, 40000, 0, 0, 1, 0),
           hand_may_open(0, 2000, 1, 0, 1, 0), hand_may_open(0, 2000, 0, 1, 1, 0), hand_may_open(0, 2000, 0, 0, 0, 1),
           hand_may_open(0, 2000, 0, 0, 1, 0), hand_may_open(0, 2000, 0, 0, 0, 0), hand_may_open(-1, 2000, 0, 0, -1, 1));
    return 0;
}
""")
    begins, chooser, hand = R._host_run(tmp_path, code, flags=("-no-pie",)).strip().split("|")
    assert begins == "10001000"
    assert chooser == "7 0 0"
    assert hand == "01000111"
    own = R._lift(src, "static void sty_menu_own(unsigned own)\n{")
    assert "own = sty_chooser_own(own);" in own
    # one intro a game: none after the game's own start film
    swap = R._lift(src, "static int ci_film_swap(pm_reg *r)\n{")
    assert "ci.own_film_game = chg_game_now() + 1;" in swap
    begin = R._lift(src, "static void coop_intro_begin(const char *why)\n{")
    assert begin.index("ci.own_film_game == g") < begin.index("ci.film_at && pm_ms()")
    # no language window of ours with the ball in the lane: the language is the start film's own bar
    tick = R._lift(src, "static void coop_intro_tick(void)\n{")
    assert "ci.phase = CI_LANG" not in tick and "ci_language_open()" not in tick
    # the handicap: 0 at every new game, and its pick waits for the lane
    check = R._lift(src, "static void hand_game_check(void)\n{")
    assert check.index("for (k = 1; k <= 4; k++) hand.level[k] = 0;") > check.index("if (!fresh) return;")
    assert "hand_may_open(ci_film_up()," in R._lift(src, "static void hand_tick(void)\n{")
    # Regular at the menu is the stock game for every kind: no chooser hold on ball 1, its music under its film
    assert "    if (sty.preset == 1) {" in R._lift(src, "static void sty_begin(unsigned kind)\n{")


def test_round5_the_home_team_screen_keeps_its_action(tmp_path):
    """PAD-1449 round 5 (DoomWalrus666: "If you hold the left flipper to enter the home team screen, however, no user or
    mode could be selected at all with the action button")"""
    src = _src()
    code = (r"""
#include <stdio.h>
#define STY_HOME_MS 1000ul
""" + R._lift(src, "static int sty_home_hold(int left, int right, unsigned long held_for, int in_game)") + r"""
int main(void)
{
    /* the left flipper alone 1.2 s in attract; 0.5 s; both flippers (the start menu's open); in a game; released */
    printf("%d%d%d%d%d\n", sty_home_hold(1, 0, 1200, 0), sty_home_hold(1, 0, 500, 0), sty_home_hold(1, 1, 3000, 0),
           sty_home_hold(1, 0, 3000, 1), sty_home_hold(0, 0, 3000, 0));
    return 0;
}
""")
    assert R._host_run(tmp_path, code, flags=("-no-pie",)).strip() == "10000"
    assert "return !smn.go_ms && (!smn.home_ms || smn.home_walk);" in R._lift(
        src, "static int sty_menu_owns_action(void)\n{")
    # round 6 (DoomWalrus666: the game's reset - the left flipper with Start - brings the Home Team screen with the mode
    # list under it): walking the mode list after the hold gives Action on a mode back to the step
    frame = R._lift(src, "static void sty_menu_frame(unsigned c, int teams, int ours, unsigned std_msg, unsigned index)")
    assert "smn.home_ms && smn.entry >= 0 && !smn.home_walk" in frame and "smn.home_walk = 1;" in frame
    assert "smn.home_walk = 0;" in R._lift(src, "static void sty_home_tick(void)")
    # round 6 (DoomWalrus666: "Selecting a mode no longer brings up the other options"): the hand-back never lets
    # Action begin a game from a mode entry - the start is held back, the hand-back ends and the step opens
    held = R._lift(src, "static int sty_menu_held(void)\n{")
    assert "smn.go_ms != 0," in held and "smn.home_ms != 0," not in held
    assert "smn.home_ms = 0;" in held and "smn.act = 1;" in held
    edge = R._lift(src, "static void sty_menu_edge(unsigned id, int press)")
    assert edge.index("!smn.ov && smn.home_ms && !smn.home_walk && !smn.go_ms && sty_menu_kind() != 0u") < edge.index("sty_menu_owns_action()")
    assert "sty_home_tick();" in R._lift(src, "static void coop_tick(void)\n{")
    # a game begun with the game's own Action (the Home Team screen's) plays NORMAL: no version card at ball 1
    norm = R._lift(src, "static int sty_default_normal(int preset, int menu_steps)")
    code = "#include <stdio.h>\n" + norm + r"""
int main(void) { printf("%d%d%d\n", sty_default_normal(0, 1), sty_default_normal(2, 1), sty_default_normal(0, 0)); return 0; }
"""
    assert R._host_run(tmp_path, code, flags=("-no-pie",)).strip() == "100"
    assert "sty_default_normal(sty.preset, smn.frame_ms != 0)" in R._lift(src, "static void sty_begin(unsigned kind)\n{")


def test_round7_action_follows_the_games_home_team_overlay(tmp_path):
    """PAD-1449 round 7 (DoomWalrus666, on v1.561.1: "other times the action button does nothing on the home team
    screen, and sometimes the version options do not appear"): the game's NetLoginOverlay state, not a guess"""
    src = _src()
    code = r"""#include <stdio.h>
#define STY_OV_PLAIN 1
#define STY_OV_LOGIN 2
#define STY_OV_MODES 3
#define STY_OV_START 4
""" + \
        R._lift(src, "static int sty_overlay_kind(unsigned state, unsigned sub)") + r"""
int main(void)
{
    /* plain menu; Home Team roster (log-in, profile pick, dialog); its game-mode select (6/4, 4/4); a prompt
     * before it (6/3); PRESS ACTION TO START GAME (5/5); attract; Insider boxes; unknown */
    printf("%d %d%d%d %d%d %d %d %d %d %d\n", sty_overlay_kind(1, 4), sty_overlay_kind(5, 0), sty_overlay_kind(5, 1),
           sty_overlay_kind(5, 6), sty_overlay_kind(6, 4), sty_overlay_kind(4, 4), sty_overlay_kind(6, 3),
           sty_overlay_kind(5, 5), sty_overlay_kind(2, 0), sty_overlay_kind(3, 0), sty_overlay_kind(9, 0));
    return 0;
}
"""
    assert R._host_run(tmp_path, code, flags=("-no-pie",)).strip() == "1 222 33 2 4 2 2 0"
    owns = R._lift(src, "static int sty_menu_owns_action(void)\n{")
    assert "if (smn.ov == STY_OV_MODES) return !smn.open || smn.shaping;" in owns
    assert "if (smn.ov) return smn.ov == STY_OV_PLAIN && !smn.go_ms;" in owns
    edge = R._lift(src, "static void sty_menu_edge(unsigned id, int press)")
    assert edge.index("smn.ov == STY_OV_START") < edge.index("sty_menu_owns_action()")
    assert "smn.ov == STY_OV_MODES && smn.open && !smn.shaping" in edge
    assert "if (smn.ov) {" in R._lift(src, "static void sty_home_tick(void)")
    read = R._lift(src, "static void sty_overlay_read(void)")
    assert "smn.open && !smn.act" in read
    hook = R._lift(src, "static void team_menu_frame(pm_reg *r)")
    assert hook.index("sty_overlay_read();") < hook.index("sty_menu_walk(&r[breg]")
