"""PAD-521: the game's own status bar (James Bond LE: the coloured bar under the TV) for a mode of ours.

The Bond owner's own mini-wizards should look like the game's: the mode's name in a coloured bar under the TV, its
clock draining along it. The runtime's pm_status_bar does what the game's own modes do to the score display's bar
(the four flag bytes, the wipe's frame, the words through set_text, the colour through the bar node's two colour
calls). Lifted from the runtime and run over a fake score display.
"""

import re

from tests.test_spike2_mode_roster import RUNTIME, _host_run, _lift

PRELUDE = r"""
#include <stdio.h>
#include <string.h>
#define PM_CAN_STATUS_BAR 0x4000000u
static unsigned can = PM_CAN_STATUS_BAR;
struct pm_mode { const char *name; };
static const struct pm_mode mode_a = { "A" }, mode_b = { "B" };
static const struct pm_mode *current = &mode_a;
static unsigned long now_ms = 1000;
static int in_game = 1;
static unsigned long pm_ms(void) { return now_ms; }
static int pm_in_game(void) { return in_game; }
static unsigned char obj[0x128];
static void *getter(void) { return obj; }
static char shown[64];
static float col[2][4];
static int calls;
static void set_text(void *node, unsigned *str) { strcpy(shown, (const char *)(unsigned long)*str); calls++; }
static void colour_a(void *node, float r, float g, float b, float a) { col[0][0] = r; col[0][1] = g; col[0][2] = b; col[0][3] = a; }
static void colour_b(void *node, float r, float g, float b, float a) { col[1][0] = r; col[1][1] = g; col[1][2] = b; col[1][3] = a; }
static unsigned vtable[32];
static unsigned bar_node[4], text_node[4];
static unsigned fn(const char *n)
{
    if (!strcmp(n, "status_bar")) return (unsigned)(unsigned long)getter;
    if (!strcmp(n, "set_text")) return (unsigned)(unsigned long)set_text;
    return 0;
}
static long pm_port_value(const char *n, long fallback) { return fallback; }
static char strs[8][96];
static int nstr;
static unsigned std_string(const char *s) { char *d = strs[nstr++ % 8]; strcpy(d, s); return (unsigned)(unsigned long)d; }
static void say(const char *f, ...) {}
static int str_eq(const char *a, const char *b)
{
    if (!a || !b) return 0;
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}
static void str_copy(char *dst, unsigned cap, const char *src, unsigned n)
{
    unsigned i;
    for (i = 0; i < n && i + 1 < cap && src[i]; i++) dst[i] = src[i];
    dst[i] = 0;
}
"""

MAIN = r"""
static void bytes(const char *when)
{
    printf("%s %d %d%d%d%d %s %.2f %.2f %.2f %.1f %d\n", when, obj[0x11c], obj[0x11e], obj[0x11f], obj[0x120], obj[0x121],
           shown, col[0][0], col[0][1], col[0][2], col[1][3], calls);
}
int main(void)
{
    vtable[0x4c / 4] = (unsigned)(unsigned long)colour_a;
    vtable[0x44 / 4] = (unsigned)(unsigned long)colour_b;
    bar_node[0] = (unsigned)(unsigned long)vtable;
    *(unsigned *)(obj + 0x114) = (unsigned)(unsigned long)bar_node;
    *(unsigned *)(obj + 0x118) = (unsigned)(unsigned long)text_node;
    obj[0x11e] = 1;                                     /* as found: the empty bar */
    bytes("found");
    pm_status_bar("YOLT WIZARD", 0x00ff00, 100); bytes("taken");
    pm_status_bar("YOLT WIZARD", 0x00ff00, 40); bytes("wipe");        /* the words are not sent again */
    obj[0x11f] = 0; obj[0x121] = 0; sb_tick(); bytes("hidden by the game, held");
    pm_status_bar("DIAMOND DEATH THREAT", 0x0000ff, -1); bytes("blue, no wipe");
    pm_status_bar(0, 0, 0); bytes("given back");
    pm_status_bar("YOLT WIZARD", 0x00ff00, 10);
    obj[0x120] = 0; obj[0x11f] = 7;                     /* the game's own display took it: left to the game */
    pm_status_bar("", 0, 0); bytes("the game's now");
    pm_status_bar("YOLT WIZARD", 0x00ff00, 10);
    current = &mode_b; pm_status_bar("DAF", 0x0000ff, -1);    /* another mode of ours takes it over */
    current = &mode_a; pm_status_bar(0, 0, 0); bytes("not A's to give back");
    current = &mode_b; pm_status_bar("YOLT WIZARD", 0x00ff00, 10);
    in_game = 0; sb_tick(); now_ms += 31000; sb_tick(); bytes("game over");
    return 0;
}
"""


def _sb_struct(src):
    m = re.search(r"static struct \{\n    int held, sent;.*?\} sb;", src, re.S)
    assert m
    return m.group(0)


def test_a_mode_holds_the_games_status_bar_and_gives_it_back(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8").replace("\r\n", "\n")
    parts = [_sb_struct(src)] + [_lift(src, s) for s in (
        "static unsigned char *sb_obj(void)", "static unsigned char *sb_at(unsigned char *o, int k)",
        "static void sb_send(unsigned char *o)", "static void sb_put(unsigned char *o)",
        "static void sb_release(const char *why)", "int pm_status_bar(const char *words, unsigned rgb, int percent)",
        "static void sb_tick(void)")]
    out = _host_run(tmp_path, PRELUDE + "\n".join(parts) + MAIN, flags=("-no-pie", "-fno-pie")).splitlines()
    assert out == [
        "found 0 1000  0.00 0.00 0.00 0.0 0",
        "taken 100 1111 YOLT WIZARD 0.00 1.00 0.00 1.0 1",
        "wipe 40 1111 YOLT WIZARD 0.00 1.00 0.00 1.0 1",
        "hidden by the game, held 40 1111 YOLT WIZARD 0.00 1.00 0.00 1.0 2",
        "blue, no wipe 0 1110 DIAMOND DEATH THREAT 0.00 0.00 1.00 1.0 3",
        "given back 0 1000 DIAMOND DEATH THREAT 0.00 0.00 1.00 1.0 3",
        "the game's now 10 1701 YOLT WIZARD 0.00 1.00 0.00 1.0 4",
        "not A's to give back 0 1110 DAF 0.00 0.00 1.00 1.0 6",
        "game over 10 1701 YOLT WIZARD 0.00 1.00 0.00 1.0 7",          # as it found it, the second time
    ]


def test_the_status_bar_is_armed_from_the_port_and_kept_every_tick():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = _lift(src, "static void status_bar_arm(void)")
    assert 'site("status_bar")' in arm and "can |= PM_CAN_STATUS_BAR;" in arm
    assert "status_bar_arm();" in src and "    sb_tick();" in _lift(src, "static void on_tick(unsigned *r)")
    port = (RUNTIME.parent / "ports" / "james_bond_le-1.06.port").read_text(encoding="utf-8")
    assert re.search(r"^site status_bar\s+0x001862dc 0xe92d4038 0xe30e48f8$", port, re.M)


def test_bond_pro_has_what_bond_le_has():
    """PAD-722: Bond Pro 1.06 gets the LE's status bar, info line, backdrop and film events (LE and Pro of a game get
    the same support). The LE's recipe places each on the Pro strictly; seen in the emulator on the Pro 2026-10-25:
    From Russia With Love's fourth part started a mode on film_frwl, its name in the blue bar and its loop on the TV."""
    port = (RUNTIME.parent / "ports" / "james_bond_pro-1.06.port").read_text(encoding="utf-8")
    assert re.search(r"^site status_bar\s+0x00184aec 0xe92d4038 0xe3004138$", port, re.M)
    assert re.search(r"^text info_line_at 679 510$", port, re.M)
    assert re.search(r"^value backdrop_surface 1$", port, re.M)
    assert re.search(r"^site film_complete\s+0x001d3134 0xe92d4038 0xe1a05000$", port, re.M)
    films = ("dr_no", "frwl", "goldfinger", "thunderball", "yolt", "daf")
    for arg, film in enumerate(films):
        assert re.search(r"^event film_%s\s+site film_complete arg %d$" % (film, arg), port, re.M)
    from pinball_decryptor.plugins.stern import mode_project as MP
    le = MP.profile_from_port(str(RUNTIME.parent / "ports" / "james_bond_le-1.06.port"))
    pro = MP.profile_from_port(str(RUNTIME.parent / "ports" / "james_bond_pro-1.06.port"))
    assert pro.status_bar and le.status_bar and pro.info_at == le.info_at
    assert {e for e in le.events if e.startswith("film_")} == {e for e in pro.events if e.startswith("film_")} \
        == {"film_" + f for f in films}
