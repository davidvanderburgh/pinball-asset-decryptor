"""PAD-707: MORE KAIJU - a list of monsters of our own behind one of Godzilla's battle slots.

- The runtime's list and its selection screen (pad_mode_runtime.c, "PAD-707: MORE KAIJU"), lifted verbatim and run on
  the host against stubs of what it calls: joining, the slot's pick opening the menu once the game's screen has
  closed, the flipper buttons and their sounds, the Action button and the timer picking, the monster's on_pick, the
  ball held meanwhile, a lost monster played again by the city pick, a ball or a player change giving the pick back.
- A mode file's ``roster_more`` (mode_file.c on the host): the file joins the list, and its pick starts it.
- Blocks: the hat's "MORE KAIJU, in <battle>'s place", its words, its assets, the C it makes (the desk harness).
- The pages the card build draws (more_kaiju.py), and the Godzilla ports' sound lines.
The C parts need an ELF host C compiler (they skip on Windows and macOS)."""
import json
import os
import pathlib
import re
import subprocess

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import more_kaiju as MK
from pinball_decryptor.plugins.stern import portgen
from tests.test_spike2_mode_roster import HARNESS, _cc, _host_run, weak_stubs

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
ROSTER = list(MP.ROSTER_NAMES["godzilla_le"])
SHOTS = ["Left ramp", "Right ramp", "Building"]


def num(v):
    return {"k": "num", "v": v}


def monster(name="MOTHRA", slot=0, won=True, picture=None):
    hat = {"kind": "battle", "slot": slot, "name": ROSTER[slot], "more": True}
    if picture:
        hat["picture"] = picture
    end = {"op": "end_mode", "won": True} if won else {"op": "end_mode"}
    return {"name": name, "seconds": 30, "game_modes": "stack",
            "scripts": [{"hat": hat, "do": [{"op": "start_mode"}]},
                        {"hat": {"kind": "shot", "shot": "Building", "when": "running"},
                         "do": [{"op": "score", "points": num(1000000)}, end]}]}


# ---- blocks ---------------------------------------------------------------------------------------
def test_a_more_kaiju_hat_builds_and_says_what_it_is():
    assert BM.problems(monster(), shots=SHOTS, roster=ROSTER) == []
    assert BM._hat_words(monster()["scripts"][0]["hat"]) == "when the player picks it on MORE KAIJU, in Ebirah's place"
    # one script per battle place: the list behind a place and the place itself are the same pick
    p = monster()
    p["scripts"].append({"hat": {"kind": "battle", "slot": 0, "name": "Ebirah"}, "do": [{"op": "start_mode"}]})
    assert any("one script per battle" in x for x in BM.problems(p, shots=SHOTS, roster=ROSTER))


def test_its_assets_name_the_slot_and_the_picture():
    assert BM.more_of(monster()) == {"slot": 0}
    assert BM.more_of(monster(slot=3, picture="monster.png")) == {"slot": 3, "picture": "monster.png"}
    plain = monster()
    plain["scripts"][0]["hat"].pop("more")
    assert BM.more_of(plain) == {}


def test_the_c_joins_the_list_instead_of_claiming_the_slot():
    c = BM.to_c(monster(), "mothra")
    assert "static const unsigned BATTLE_MORE[1] = { 1 };" in c
    assert '#define MORE_PAGE "PadMode_mothra_More"' in c
    assert "pm_roster_more(BATTLE_SLOTS[i], MODE_NAME, MORE_PAGE, 0, on_battle)" in c
    assert "pm_roster_more_picked() ? pm_roster_start_after()" in c
    plain = monster()
    plain["scripts"][0]["hat"].pop("more")
    assert "BATTLE_MORE[1] = { 0 };" in BM.to_c(plain, "mothra")


def test_the_c_only_calls_what_the_header_declares():
    declared = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", (SDK / "pad_mode.h").read_text(encoding="utf-8")))
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", BM.to_c(monster(), "mothra")))
    assert used <= declared, used - declared


def test_a_picked_monster_plays_and_gives_the_battle_back(tmp_path):
    from tests.test_stern_block_battle import play
    out = play(tmp_path, monster(), "pickmore", "MOTHRA", "secs", 1, "shot", "Building", "secs", 2, slug="mothra")
    assert "ROSTER MORE 0 MOTHRA page PadMode_mothra_More callout 0" in out
    assert "PICKMORE MOTHRA -> 1" in out
    assert "battle 0 picked - its script runs in 300 ms" in out          # the list's screen has closed already
    assert "[MOTHRA] START (a block)" in out
    assert "ROSTER OVER WON" in out


# ---- a mode file --------------------------------------------------------------------------------------
MORE_STUBS = r"""
static int (*more_fn[16])(unsigned);
static char more_name[16][64];
static int more_k;
static const char *more_who;
int pm_roster_more(unsigned slot, const char *name, const char *page, unsigned callout, int (*f)(unsigned))
{ printf("MORE %u %s page '%s' callout %u\n", slot, name, page, callout); snprintf(more_name[more_k], 64, "%s", name);
  more_fn[more_k] = f; return more_k++; }
void pm_roster_more_leave(const char *name) { printf("LEAVE %s\n", name); }
const char *pm_roster_more_picked(void) { return more_who; }
long pm_roster_start_after(void) { return more_who ? 300 : 0; }
static int pick_more(const char *who)
{ int k; for (k = 0; k < more_k; k++) if (!strcmp(more_name[k], who)) { int r; more_who = more_name[k];
  r = more_fn[k](0); more_who = 0; return r; } return -1; }
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = _cc()
    d = tmp_path_factory.mktemp("more")
    src = HARNESS.replace("int main(int argc, char **argv)\n{", MORE_STUBS + "int main(int argc, char **argv)\n{", 1)
    src = src.replace('        } else if (!strcmp(argv[k], "ball_end")) {',
                      '        } else if (!strcmp(argv[k], "pickmore")) {\n'
                      '            const char *w = argv[++k];\n'
                      '            printf("PICKMORE %s -> %d\\n", w, pick_more(w));\n'
                      '        } else if (!strcmp(argv[k], "ball_end")) {', 1)
    assert "pick_more(w)" in src
    (d / "harness.c").write_text(src)
    stubs, _names = weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    exe = d / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _run(harness, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


MORE_FILE = "name RODAN\nroster_slot 0\nroster_more PadMode_rodan_More\nroster_callout 207\nseconds 30\nshots 0x70300000\n"


def test_a_mode_file_joins_the_list_and_its_pick_starts_it(harness, tmp_path):
    out = _run(harness, tmp_path, MORE_FILE, "pickmore", "RODAN", "tick", "30", "ball_end")
    assert "unknown key" not in out
    assert "MORE 0 RODAN page 'PadMode_rodan_More' callout 207" in out
    assert "CLAIM" not in out                                   # the list holds the slot, not the file
    assert "RODAN joins MORE KAIJU behind roster slot 0" in out
    assert "PICKMORE RODAN -> 1" in out
    assert "RODAN START (roster pick)" in out
    assert "ROSTER_DONE" in out                                 # its end gives the battle back


def test_a_mode_file_without_roster_more_still_claims_the_slot(harness, tmp_path):
    out = _run(harness, tmp_path, MORE_FILE.replace("roster_more PadMode_rodan_More\n", ""), "pick", "0")
    assert "CLAIM 0" in out and "MORE 0" not in out
    assert "PICK 0 -> 1" in out


def test_a_mode_file_leaves_the_list_when_it_goes(harness, tmp_path):
    out = _run(harness, tmp_path, MORE_FILE, "rm", "pickmore", "RODAN")
    assert "LEAVE RODAN" in out


# ---- the runtime's list and its screen ------------------------------------------------------------------
def _section(src):
    """The runtime's MORE KAIJU section, verbatim: from its first #define to the end of more_ball_end."""
    i = src.index("#define N_MORE 16")
    j = src.index("static void more_ball_end(void)\n{", i)
    k = src.index("\n}\n", j) + 3
    return src[i:k]


PRELUDE = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "pad_mode.h"
#define N_ROSTER 16
static const struct pm_mode *current, *running;
static unsigned can = PM_CAN_SCREENS;
static int (*roster_fn[N_ROSTER])(unsigned slot);
static const struct pm_mode *roster_by[N_ROSTER];
static int roster_resuming;
static unsigned long now;
static int in_game = 1;
static unsigned up = 1;
static void say(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); putchar('\n'); }
int pm_roster_slots(void) { return 7; }
static int roster_callout_set(unsigned s, unsigned id, const char *why) { printf("CALLOUT %u %u\n", s, id); return 1; }
static void roster_callout_restore(unsigned s) { printf("CALLOUT %u back\n", s); }
static int nodes[16];
void *pm_node(const char *scene, const char *path) { static int n; return strstr(path, "NOPAGE") ? 0 : &nodes[n++ % 16]; }
void *pm_text(const char *scene, const char *path) { return &nodes[15]; }
void pm_show(void *node, int on) { if (on) printf("SHOW page %ld\n", (long)((int *)node - nodes)); }
void pm_set_text(void *t, const char *w) { printf("WORDS %s\n", w); }
int pm_snprintf(char *o, unsigned long cap, const char *fmt, ...)
{ va_list ap; int n; va_start(ap, fmt); n = vsnprintf(o, cap, fmt, ap); va_end(ap); return n; }
unsigned long pm_ms(void) { return now; }
int pm_in_game(void) { return in_game; }
unsigned pm_player(void) { return up; }
long pm_port_value(const char *n, long fb)
{
    if (!strcmp(n, "roster_start_after_ms")) return 3000;
    if (!strcmp(n, "roster_left_sound")) return 271;
    if (!strcmp(n, "roster_right_sound")) return 272;
    if (!strcmp(n, "roster_pick_sound")) return 236;
    return fb;
}
int pm_sound(unsigned r) { printf("SOUND %u\n", r); return 1; }
uint64_t pm_shot(const char *n)
{
    return !strcmp(n, "Left flipper button") ? 2 : !strcmp(n, "Right flipper button") ? 4 : !strcmp(n, "Action button") ? 1 : 0;
}
int pm_begin(void) { if (running && running != current) { printf("BEGIN refused\n"); return 0; } running = current; return 1; }
void pm_end(void) { if (running == current) running = 0; }
int pm_display_priority(unsigned p) { printf("PRIORITY %u\n", p); return 1; }
void pm_roster_done(void) { printf("GIVEN BACK\n"); }
"""

DRIVER = r"""
static const struct pm_mode A = { "A", 0, 0, 0, 0, 0 }, OTHER = { "OTHER", 0, 0, 0, 0, 0 };
static int nope;
static int pick(unsigned slot)
{
    const char *who = pm_roster_more_picked();
    printf("PICKED %s slot %u after %ld\n", who ? who : "?", slot, pm_roster_start_after());
    if (nope) return 0;
    running = &A;                                   /* its mode begins */
    return 1;
}
int main(int argc, char **argv)
{
    int k, i;
    current = &A;
    for (k = 1; k < argc; k++) {
        const char *c = argv[k];
        if (!strcmp(c, "join")) { current = &A; printf("JOIN %d\n", pm_roster_more(0, argv[++k], strcmp(argv[k], "NOPAGE") ? "PadMode_x_More" : "NOPAGE", 900 + k, pick)); }
        else if (!strcmp(c, "joinslot")) { current = &A; printf("JOIN %d\n", pm_roster_more((unsigned)atoi(argv[k + 1]), argv[k + 2], "P", 0, pick)); k += 2; }
        else if (!strcmp(c, "leave")) { current = &A; pm_roster_more_leave(argv[++k]); }
        else if (!strcmp(c, "pick")) { current = roster_by[0]; printf("TAKEN %d\n", roster_fn[0] ? roster_fn[0](0) : -1); current = 0; }
        else if (!strcmp(c, "resume")) { roster_resuming = 1; current = roster_by[0]; printf("TAKEN %d\n", roster_fn[0](0)); current = 0; roster_resuming = 0; }
        else if (!strcmp(c, "ms")) { int n = atoi(argv[++k]); for (i = 0; i < n / 17 + 1; i++) { now += 17; current = 0; more_tick(); } }
        else if (!strcmp(c, "left") || !strcmp(c, "right") || !strcmp(c, "action")) {
            uint64_t m = c[0] == 'l' ? 2 : c[0] == 'r' ? 4 : 1;
            printf("BUTTON %s taken %d\n", c, more_buttons(m));
        }
        else if (!strcmp(c, "slingshot")) printf("BUTTON slingshot taken %d\n", more_buttons(8));
        else if (!strcmp(c, "holding")) printf("HOLDING %d\n", more_holding());
        else if (!strcmp(c, "ball_end")) more_ball_end();
        else if (!strcmp(c, "lost")) { more_over(up, 0); running = 0; }
        else if (!strcmp(c, "won")) { more_over(up, 1); running = 0; }
        else if (!strcmp(c, "player")) up = (unsigned)atoi(argv[++k]);
        else if (!strcmp(c, "gameover")) in_game = 0;
        else if (!strcmp(c, "other")) running = &OTHER;
        else if (!strcmp(c, "nope")) nope = 1;
        else if (!strcmp(c, "slot")) printf("SLOT0 %s\n", roster_by[0] ? roster_by[0]->name : "-");
    }
    return 0;
}
"""


def menu(tmp_path, *args):
    src = RUNTIME.read_text(encoding="utf-8")
    code = PRELUDE + _section(src) + DRIVER
    return _host_run(tmp_path, code, flags=("-I", str(SDK)), args=[str(a) for a in args])


def test_the_list_holds_the_slot_while_it_has_monsters(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "join", "RODAN", "slot", "leave", "MOTHRA", "slot", "leave", "RODAN",
               "slot", "joinslot", 3, "GIGAN")
    assert "JOIN 0" in out and "JOIN 1" in out
    assert "CALLOUT 0 0" in out                                 # the place is silent: the list speaks
    assert out.count("SLOT0 MORE KAIJU") == 2 and "SLOT0 -" in out
    assert "CALLOUT 0 back" in out
    assert "MORE KAIJU is empty - slot 0 is the game's again" in out
    assert "JOIN 0" in out.split("SLOT0 -")[1]                  # once empty, another place may host it


def test_one_list_per_game(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "joinslot", 3, "GIGAN")
    assert "MORE KAIJU is behind slot 0 already - GIGAN cannot join" in out
    assert "JOIN -1" in out


def test_a_pick_opens_the_menu_once_the_games_screen_has_closed(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "join", "RODAN", "join", "ANGUIRUS", "pick", "holding", "ms", 2900,
               "holding", "ms", 200)
    assert "TAKEN 1" in out                                     # the game's battle does not start
    assert "MORE KAIJU opens in 3000 ms" in out
    assert out.index("HOLDING 1") < out.index("MORE KAIJU open for player 1")   # the ball waits from the pick
    head, menu_on = out.split("MORE KAIJU open for player 1", 1)
    assert "SHOW" not in head                                   # nothing of ours over the game's screen
    assert "PRIORITY 200" in head
    assert "SHOW page 0" in menu_on and "WORDS 13" in menu_on
    assert "MORE KAIJU's cursor is on MOTHRA (1 of 3)" in menu_on
    assert re.search(r"cursor is on MOTHRA \(1 of 3\)\nSOUND 90\d", menu_on)   # its callout as the cursor lands


def test_the_flippers_move_with_the_games_sounds_and_action_picks(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "join", "RODAN", "join", "ANGUIRUS", "pick", "ms", 3100,
               "right", "right", "right", "left", "slingshot", "action", "holding", "ms", 400, "holding")
    moves = re.findall(r"cursor is on (\w+)", out)
    assert moves == ["MOTHRA", "RODAN", "ANGUIRUS", "MOTHRA", "ANGUIRUS"]      # it wraps both ways
    assert out.count("SOUND 272") == 3 and out.count("SOUND 271") == 1
    assert "BUTTON slingshot taken 0" in out                     # anything else goes on to the modes
    assert "ANGUIRUS picked with the Action button" in out
    assert "SOUND 236" in out
    assert "PICKED ANGUIRUS slot 0 after 300" in out             # its mode starts almost at once
    assert "PRIORITY 0" in out
    assert "ANGUIRUS picked by player 1 - its mode has the battle of slot 0" in out
    assert re.search(r"HOLDING 1\s.*the ball goes \(the monster's mode began\).*HOLDING 0", out, re.S)


def test_the_timer_picks_the_monster_under_the_cursor(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "join", "RODAN", "pick", "ms", 3100, "right", "ms", 13100)
    assert "WORDS 1\n" in out
    assert "RODAN picked when the time ran out" in out
    assert "PICKED RODAN" in out


def test_buttons_do_nothing_while_the_menu_is_closed(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "ms", 17, "right", "pick", "action", "ms", 3100)
    assert "BUTTON right taken 0" in out
    assert "BUTTON action taken 1" in out                       # waiting to open: swallowed, not passed on
    assert "MOTHRA picked" not in out.split("open for player 1")[0]


def test_a_lost_monster_comes_back_at_the_city_pick_without_the_menu(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "join", "RODAN", "pick", "ms", 3100, "right", "action", "ms", 100, "lost",
               "resume", "ms", 3100)
    assert "RODAN's battle lost for player 1 - the city pick plays it again" in out
    tail = out.split("RODAN's battle lost")[1]
    assert "restarted by the city pick - RODAN, the monster player 1 lost, plays again" in tail
    assert "open for player" not in tail                         # no menu
    assert "PICKED RODAN" in tail


def test_a_won_monster_does_not_come_back(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "pick", "ms", 3100, "action", "ms", 100, "won", "resume", "ms", 3100)
    assert "MOTHRA's battle won for player 1" in out
    assert "open for player 1" in out.split("battle won")[1]     # a pick after a win opens the list again


def test_the_ball_ending_or_another_player_gives_the_pick_back(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "pick", "ms", 3100, "ball_end", "holding")
    assert "MORE KAIJU closed (the ball ended)" in out and "GIVEN BACK" in out and "HOLDING 0" in out
    out = menu(tmp_path, "join", "MOTHRA", "pick", "ms", 1000, "player", 2, "ms", 50)
    assert "MORE KAIJU closed (another player is up)" in out and "GIVEN BACK" in out


def test_another_mode_running_gives_the_pick_back(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "pick", "other", "ms", 3100)
    assert "BEGIN refused" in out
    assert "another mode of ours runs - the pick is given back" in out and "GIVEN BACK" in out


def test_a_monster_that_will_not_start_gives_the_pick_back(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "nope", "pick", "ms", 3100, "action")
    assert "MOTHRA did not take the pick - given back as a lost battle" in out and "GIVEN BACK" in out


def test_the_game_ending_closes_it_quietly(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "pick", "ms", 3100, "gameover", "ms", 50, "holding")
    assert "MORE KAIJU closed (the game ended)" in out
    assert "GIVEN BACK" not in out and "HOLDING 0" in out


def test_the_pick_outside_a_game_is_the_games(tmp_path):
    out = menu(tmp_path, "join", "MOTHRA", "gameover", "pick")
    assert "TAKEN 0" in out


def test_the_runtime_wires_the_list_in():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "if (more_buttons(mask)) continue;" in src          # the cabinet buttons are the menu's while it is up
    assert re.search(r"e == scoop\.event && pm_in_game\(\) && more_holding\(\)", src)   # the ball waits
    assert "    more_tick();" in src and "    more_ball_end();" in src
    assert "    more_over(p, won);" in src
    assert "    roster_resuming = 1;\n    roster_take(" in src.replace("\r\n", "\n")


# ---- the pages ------------------------------------------------------------------------------------------
def _monsters(n):
    return [{"slug": "m%d" % i, "name": "MONSTER %d" % i, "slot": 0, "picture": ""} for i in range(n)]


def test_a_page_is_the_whole_glass_and_lights_its_own_tile():
    ms = _monsters(3)
    a, b = MK.page_art(ms, 0), MK.page_art(ms, 1)
    assert a.shape == (MK.PAGE_H, MK.PAGE_W, 4) and a.dtype == np.uint8
    assert MK.PAGE_W * MK.PAGE_SCALE == 1360 and MK.PAGE_H * MK.PAGE_SCALE == 768
    assert (a[..., 3] == 255).all()                                      # opaque: the city map never shows through
    assert MK.PAGE_W % 4 == 0 and MK.PAGE_H % 4 == 0                     # BC3
    assert not np.array_equal(a, b)
    s = MK.page_screen(ms, 1)
    assert s["name"] == "PadMode_m1_More" and s["words_name"] == "PadMode_m1_More_Words"
    assert s["scale"] == MK.PAGE_SCALE and (s["x"], s["y"]) == (0.0, 0.0)
    # the timer's words are centred on its box: the text box spans the picture's width at its own scale
    assert s["words_at"][0] + MK.PAGE_W * s["words_scale"] / 2.0 == pytest.approx(MK.TIMER_AT[0])


def test_many_monsters_scroll_the_row(tmp_path):
    ms = _monsters(12)
    assert MK.page_art(ms, 11).shape == (MK.PAGE_H, MK.PAGE_W, 4)
    with pytest.raises(MK.MoreKaijuError):
        MK.page_art(ms, 12)


def test_a_picture_is_the_monster_png_else_the_badge(tmp_path):
    from PIL import Image
    assert MK.picture_of(str(tmp_path)) == ""
    Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(tmp_path / "badge.png")
    assert MK.picture_of(str(tmp_path)).endswith("badge.png")
    Image.new("RGBA", (40, 40), (0, 255, 0, 255)).save(tmp_path / "monster.png")
    assert MK.picture_of(str(tmp_path)).endswith("monster.png")
    ms = [{"slug": "a", "name": "A", "slot": 0, "picture": str(tmp_path / "monster.png")}]
    art = MK.page_art(ms, 0)
    assert (art[150, 100, :3] == (0, 255, 0)).all()                       # the portrait is the picture


class _Spec:
    def __init__(self, name, more):
        self.name, self.more = name, more


class _Prof:
    def can(self, what):
        return True


def test_the_project_has_one_list(tmp_path):
    code = [("a", _Spec("Mothra", {"slot": 0})), ("b", _Spec("RODAN", {})), ("c", _Spec("ANGUIRUS", {"slot": 0}))]
    found = MK.monsters(str(tmp_path), code)
    assert [m["name"] for m in found] == ["MOTHRA", "ANGUIRUS"]
    assert MK.problems(found) == []
    assert [s["name"] for s in MK.screens(str(tmp_path), code, _Prof())] == ["PadMode_a_More", "PadMode_c_More"]
    code.append(("d", _Spec("GIGAN", {"slot": 2})))
    with pytest.raises(MK.MoreKaijuError, match="more than one battle"):
        MK.screens(str(tmp_path), code, _Prof())


def test_the_runtime_finds_the_page_the_build_names():
    node, text = MK.page_names("king-ghidorah 2")
    assert node == "PadMode_king_ghidorah_2_More"
    assert text == node + "." + node + "_Words"
    assert 'pm_snprintf(words, sizeof words, "%s.%s_Words", m->page, m->page);' in RUNTIME.read_text(encoding="utf-8")


# ---- the ports -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("port", ["godzilla_le-1.16", "godzilla_pro-1.16", "godzilla_pro-1.15"])
def test_the_godzilla_ports_carry_the_selection_screens_sounds(port):
    text = (SDK / "ports" / (port + ".port")).read_text(encoding="utf-8")
    for name, value in (("roster_left_sound", 271), ("roster_right_sound", 272), ("roster_pick_sound", 236),
                        ("roster_select_ms", 13000)):
        assert re.search(r"^value %s\s+%d\b" % (name, value), text, re.M), name
    for button in ("Action button", "Left flipper button", "Right flipper button"):
        assert re.search(r"^switch \d+\s+0x[0-9a-f]+ %s$" % button, text, re.M), button
    for name in ("roster_left_sound", "roster_right_sound", "roster_pick_sound", "roster_select_ms"):
        assert name in portgen.TITLE_VALUES


# ---- a form mode ------------------------------------------------------------------------------------------
@pytest.fixture
def le(monkeypatch):
    p = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
    monkeypatch.setitem(MP.PROFILES, p.key, p)
    return p


def _form(p, **kw):
    spec = MP.blank_spec(p)
    spec.name, spec.starts_on, spec.roster_slot, spec.seconds = "RODAN", "battle", 0, 30
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def test_a_form_mode_on_the_list_writes_roster_more_after_its_slot(le):
    lines = [x for x in MP.runtime_cfg(_form(le, roster_more=True), "rodan").splitlines() if x and x[0] != "#"]
    at = lines.index("roster_slot    0")
    assert lines[at + 1] == "roster_more    PadMode_rodan_More"
    assert "roster_more" not in MP.runtime_cfg(_form(le), "rodan")          # the battle's place itself, as before
    spec = MP.ModeSpec.from_json(json.loads(json.dumps(_form(le, roster_more=True).to_json())))
    assert spec.roster_more is True                                          # kept in mode.json


def test_form_modes_come_first_on_the_list(le, tmp_path):
    forms = [("rodan", _form(le, roster_more=True)), ("plain", _form(le, name="PLAIN"))]
    code = [("mothra", _Spec("MOTHRA", {"slot": 0}))]
    found = MK.monsters(str(tmp_path), code, forms)
    assert [(m["slug"], m["slot"]) for m in found] == [("rodan", 0), ("mothra", 0)]
