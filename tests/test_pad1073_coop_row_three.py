"""PAD-1073 (DoomWalrus666: "I would like for the service menu options to simply be Co-op/Team: Off, Classic,
Enhanced"): CO-OP PLAY is 0 Off, 1 Classic, 2 Enhanced, and at 1 or 2 the start menu has CO-OP PLAY, TEAM PLAY 2 VS 2
and TEAM PLAY 2 VS 1 all three; the entry picked says which game it is (pad_mode_runtime.c "PAD-1073")."""
import pathlib

from tests import test_spike2_mode_roster as R

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _fns(src, *sigs):
    return "\n".join(R._lift(src, s) for s in sigs)


ROW_FNS = ("static unsigned coop_row_mode(unsigned v)", "static int coop_switched_on(void)",
           "static int coop_classic(void)", "static unsigned team_menu_kinds(unsigned *kinds)\n{")

PRELUDE = r"""
#include <stdio.h>
#include <string.h>
static struct { unsigned teams_always, setting; } coop;
static unsigned row;
static char team_name_2v2[] = "TEAM PLAY 2 VS 2", team_name_2v1[] = "TEAM PLAY 2 VS 1", team_name_coop[] = "CO-OP PLAY";
"""

ROW_MAIN = PRELUDE + r"""
@FNS@
static void kinds(const char *tag)
{
    unsigned k[3], n = team_menu_kinds(k), i;
    printf(" %s:", tag);
    for (i = 0; i < n; i++) printf("%u", k[i]);
}
int main(void)
{
    unsigned v;
    char tag[8];
    for (v = 0; v <= 7; v++) printf("%u", coop_row_mode(v));
    coop.setting = (unsigned)(unsigned long)&row;
    for (v = 0; v <= 4; v++) {
        row = v;
        snprintf(tag, sizeof tag, "%u", v);
        kinds(tag);
        printf(",%d%d", coop_switched_on(), coop_classic());
    }
    coop.setting = 0;                                   /* no row: co-op always on, CO-OP PLAY alone */
    kinds("none");
    coop.teams_always = 3;                              /* coop.cfg `teams 2v1`: its one team game */
    kinds("teams");
    printf("\n");
    return 0;
}
"""


def test_off_classic_enhanced_and_what_the_menu_offers(tmp_path):
    out = R._host_run(tmp_path, ROW_MAIN.replace("@FNS@", _fns(_src(), *ROW_FNS)), flags=("-no-pie",)).strip()
    # an older row's store: 3 reads Enhanced, 4-6 Classic, past that Off; at 1 or 2 all three games, CO-OP PLAY first
    assert out == "01221110 0:,00 1:143,11 2:143,10 3:143,10 4:143,11 none:1 teams:3"


MENU_PRELUDE = PRELUDE + r"""
#define TEAM_KIND 0x300u
#define MENU_KIND_AT 0u
#define MENU_CAPTION_AT 4u
#define MENU_NAME_AT 8u
static struct { volatile int pending; volatile unsigned long seen_ms; volatile unsigned kind; } tm;
static unsigned long pm_ms(void) { return 7; }
static void say(const char *f, ...) { (void)f; }
static const char *lettered = "-";
static int pm_message_set(unsigned id, const char *w) { lettered = w; return 1; }
static void pm_message_restore(unsigned id) { lettered = "-"; }
static long pm_port_value(const char *n, long d)
{
    static const struct { const char *n; long v; } t[] = {
        { "challenge_menu_count_reg", 4 }, { "challenge_menu_cap", 8 }, { "challenge_menu_entry", 12 },
        { "challenge_menu_list_at", 16 }, { "challenge_menu_pick_back", 0 },
        { "comp_menu_frame_list_at", 16 }, { "comp_menu_frame_count_at", 8 }, { "comp_menu_frame_count_last", 0 },
        { "comp_menu_frame_cap", 8 }, { "comp_menu_frame_cursor_reg", 5 }, { "comp_menu_frame_buttons_reg", 6 },
        { "comp_menu_end_index", 1 }, { "comp_menu_end_msg", 0x77 } };
    unsigned i;
    for (i = 0; i < sizeof t / sizeof t[0]; i++) if (!strcmp(t[i].n, n)) return t[i].v;
    return d;
}
"""

MENU_FNS = ROW_FNS + ("static const char *team_kind_name(unsigned k)\n{",
                      "static unsigned team_entry_at(const unsigned char *ent, unsigned kat, unsigned nat)",
                      "static void team_menu_built(unsigned *r)", "static void team_menu_picked(unsigned *r)")

LIST_MAIN = MENU_PRELUDE + r"""
@FNS@
static unsigned r[64];
int main(void)
{
    unsigned *list = (unsigned *)((unsigned char *)(r + 14) + 16), i;
    coop.setting = (unsigned)(unsigned long)&row;
    row = 1;
    list[0] = 0; list[1] = 0xC1; list[2] = 0x1111;        /* Standard: kind 0, its caption, its name */
    list[3] = 5; list[4] = 0xC2; list[5] = 0x2222;        /* another of the game's */
    r[4] = 2;
    team_menu_built(r);
    team_menu_built(r);                                   /* an every-frame site: once */
    printf("%u", r[4]);
    for (i = 2; i < r[4]; i++)
        printf(" %x/%x/%s", list[3 * i], list[3 * i + 1], team_kind_name(team_entry_at((unsigned char *)(list + 3 * i), 0, 8)));
    for (i = 0x301; i <= 0x305; i++) {                    /* the pick hands over the kind: it says which */
        r[3] = i;
        team_menu_picked(r);
        printf(" %d%u%x", tm.pending, tm.kind, r[3]);
    }
    row = 0;                                              /* Off: no entry */
    r[4] = 2;
    team_menu_built(r);
    printf(" off %u\n", r[4]);
    return 0;
}
"""


def test_the_entry_lists_get_all_three_and_the_pick_says_which(tmp_path):
    out = R._host_run(tmp_path, LIST_MAIN.replace("@FNS@", _fns(_src(), *MENU_FNS)), flags=("-no-pie",)).strip()
    assert out == ("5 301/c1/CO-OP PLAY 304/c1/TEAM PLAY 2 VS 2 303/c1/TEAM PLAY 2 VS 1"   # Standard's caption each
                   " 110 01302 130 140 04305 off 2")   # 0x302, 0x305: none of ours, left as they are


FRAME_FNS = ROW_FNS + ("static const char *team_kind_name(unsigned k)\n{",
                       "static unsigned comp_frame_cursor(unsigned cursor, unsigned n, unsigned left, unsigned right)",
                       "static void team_frame_restore(void)\n{", "static void team_menu_frame(unsigned *r)")

FRAME_MAIN = MENU_PRELUDE + r"""
static unsigned long team_frame_sp;
static unsigned team_frame_at, team_frame_msg;
static unsigned team_frame_n, team_frame_kinds[3];
@FNS@
static unsigned r[64];
int main(void)
{
    unsigned char *sp = (unsigned char *)(r + 14);
    unsigned *list = (unsigned *)(sp + 16), *count = (unsigned *)(sp + 8), c, i;
    coop.setting = (unsigned)(unsigned long)&row;
    row = 2;
    list[0] = 1; list[1] = 2; list[2] = 3;                /* the game's own game-mode indices, Standard's 1 first */
    *count = 3;
    r[5] = 0;
    team_menu_frame(r);
    printf("%u", *count);
    for (i = 3; i < *count; i++) printf(" %u", list[i]);
    for (c = 0; c <= 5; c++) {                            /* the cursor over every entry */
        r[5] = c;
        team_menu_frame(r);
        printf(" %u:%d%u:%s", c, tm.pending, tm.pending ? tm.kind : 0, lettered);
    }
    printf(" %u\n", *count);                              /* the same menu: nothing added again */
    return 0;
}
"""


def test_the_index_menus_get_all_three_and_the_cursor_says_which(tmp_path):
    out = R._host_run(tmp_path, FRAME_MAIN.replace("@FNS@", _fns(_src(), *FRAME_FNS)), flags=("-no-pie",)).strip()
    assert out == ("6 1 1 1 0:00:- 1:00:- 2:00:- 3:11:CO-OP PLAY 4:14:TEAM PLAY 2 VS 2 5:13:TEAM PLAY 2 VS 1 6")


def test_the_pick_not_the_row_sizes_the_team_game():
    src = _src()
    disp = R._lift(src, "static void on_team_dispatch(unsigned *r)\n{")
    assert "kind = tm.kind;" in disp and "if (kind == 1u) {" in disp
    assert "tm.size = kind;" in disp and "added = coop_team_fill(0, 0, 0, 0);\n    tm.size = 0;" in disp
    assert "return coop.teams_always ? coop.teams_always : tm.size;" in R._lift(
        src, "static unsigned coop_teams_switched_on(void)")
    assert "return !while_at || coop_row_mode(value) != 0u;" in R._lift(
        src, "static int insider_holding(unsigned while_at, unsigned value)")


def test_the_app_says_off_classic_enhanced():
    from pinball_decryptor.plugins.stern import coop_play as CP
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.webui import help_content
    from pinball_decryptor.webui.tabs import modes as M
    key, values, names, opts = E._CoopMenu(lambda *a: None).wanted()
    assert (values, names, opts) == (3, (), {"default": 1, "help_text": CP.MENU_HELP, "from_zero": True})
    assert (CP.MENU_OFF, CP.MENU_CLASSIC, CP.MENU_ENHANCED) == (0, 1, 2)
    assert len(CP.MENU_HELP) <= 63 and CP.MENU_HELP.startswith("0 Off. 1 Classic. 2 Enhanced.")
    text = str(help_content.__dict__)
    assert "- **1 (Classic):**" in text and "- **2 (Enhanced):**" in text
    for entry in ("CO-OP PLAY", "TEAM PLAY 2 VS 2", "TEAM PLAY 2 VS 1"):
        assert "- **%s:**" % entry in text and entry in M.ModesTab.COOP_MENU_TIP
    assert "0 Off, 1 Classic (characters picked, no special abilities), 2 Enhanced" in M.ModesTab.COOP_MENU_TIP
    assert "Team 2v2" not in M.ModesTab.COOP_MENU_TIP and "1 to 6" not in M.ModesTab.COOP_MENU_TIP
