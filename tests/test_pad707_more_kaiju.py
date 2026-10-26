"""PAD-707: new monsters on Godzilla's own battle selection screen (MORE KAIJU).

- The runtime's part (pad_mode_runtime.c, "PAD-707: new monsters on the battle selection screen"), lifted verbatim and
  run on the host against stubs of the game's screen: joining in a place, the cursor walked over the new tiles by
  the screen's own flipper handler (vetoed), the game's cursor parked on the monster's place, its nodes shown and the
  place's portrait hidden, locked places skipped, the game's pick of the place taken by the monster under the
  cursor (and the place's own battle when the cursor was on the place), a lost monster played again by the city pick.
- A mode file's ``roster_more`` (mode_file.c on the host): the file joins, and its pick starts it.
- Blocks: the hat's "a new monster in <battle>'s place", its words, its assets, the C it makes (the desk harness).
- The scene the card build makes (battle_select.py) on a small selection screen of the same shape, and the
  Godzilla ports' lines.
The C parts need an ELF host C compiler (they skip on Windows and macOS)."""
import json
import os
import pathlib
import re
import subprocess

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import battle_select as BS
from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import more_kaiju as MK
from pinball_decryptor.plugins.stern import portgen
from pinball_decryptor.plugins.stern import scene_tree as T
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
def test_a_new_monster_hat_builds_and_says_what_it_is():
    assert BM.problems(monster(), shots=SHOTS, roster=ROSTER) == []
    assert BM._hat_words(monster()["scripts"][0]["hat"]) == \
        "when the player picks it on the battle selection screen, a new monster in Ebirah's place"
    # one script per battle place: a new monster in a place and the place itself are the same pick
    p = monster()
    p["scripts"].append({"hat": {"kind": "battle", "slot": 0, "name": "Ebirah"}, "do": [{"op": "start_mode"}]})
    assert any("one script per battle" in x for x in BM.problems(p, shots=SHOTS, roster=ROSTER))


def test_its_assets_name_the_slot_and_the_picture():
    assert BM.more_of(monster()) == {"slot": 0}
    assert BM.more_of(monster(slot=3, picture="monster.png")) == {"slot": 3, "picture": "monster.png"}
    plain = monster()
    plain["scripts"][0]["hat"].pop("more")
    assert BM.more_of(plain) == {}


def test_the_c_joins_the_screen_instead_of_claiming_the_slot():
    c = BM.to_c(monster(), "mothra")
    assert "static const unsigned BATTLE_MORE[1] = { 1 };" in c
    assert '#define MORE_PAGE "PadSel_mothra"' in c
    assert "pm_roster_more(BATTLE_SLOTS[i], MODE_NAME, MORE_PAGE, 0, on_battle)" in c
    plain = monster()
    plain["scripts"][0]["hat"].pop("more")
    assert "BATTLE_MORE[1] = { 0 };" in BM.to_c(plain, "mothra")


def test_the_c_only_calls_what_the_header_declares():
    declared = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", (SDK / "pad_mode.h").read_text(encoding="utf-8")))
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", BM.to_c(monster(), "mothra")))
    assert used <= declared, used - declared


def test_a_picked_monster_plays_and_gives_the_battle_back(tmp_path):
    from tests.test_stern_block_battle import play
    out = play(tmp_path, monster(), "pickmore", "MOTHRA", "secs", 4, "shot", "Building", "secs", 2, slug="mothra")
    assert "ROSTER MORE 0 MOTHRA page PadSel_mothra callout 0" in out
    assert "PICKMORE MOTHRA -> 1" in out
    assert "[MOTHRA] START (a block)" in out
    assert "ROSTER OVER WON" in out


def test_a_blocks_monster_with_nothing_else_is_built(tmp_path):
    """A blocks mode whose only asset is its tile on the screen still goes through the build (Try it found 'no
    modes' for three such monsters before has_assets counted it)."""
    from pinball_decryptor.plugins.stern import code_modes as CM
    c = CM.CodeAssets(screen=False)
    assert not c.has_assets()
    c.more = {"slot": 0}
    assert c.has_assets()


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
long pm_roster_start_after(void) { return 3000; }
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


MORE_FILE = "name RODAN\nroster_slot 0\nroster_more PadSel_rodan\nroster_callout 207\nseconds 30\nshots 0x70300000\n"


def test_a_mode_file_joins_the_screen_and_its_pick_starts_it(harness, tmp_path):
    out = _run(harness, tmp_path, MORE_FILE, "pickmore", "RODAN", "tick", "200", "ball_end")
    assert "unknown key" not in out
    assert "MORE 0 RODAN page 'PadSel_rodan' callout 207" in out
    assert "CLAIM" not in out                                   # the screen holds the place, not the file
    assert "PICKMORE RODAN -> 1" in out
    assert "RODAN START (roster pick)" in out
    assert "ROSTER_DONE" in out                                 # its end gives the battle back


def test_a_mode_file_without_roster_more_still_claims_the_slot(harness, tmp_path):
    out = _run(harness, tmp_path, MORE_FILE.replace("roster_more PadSel_rodan\n", ""), "pick", "0")
    assert "CLAIM 0" in out and "MORE 0" not in out
    assert "PICK 0 -> 1" in out


def test_a_mode_file_leaves_the_screen_when_it_goes(harness, tmp_path):
    out = _run(harness, tmp_path, MORE_FILE, "rm", "pickmore", "RODAN")
    assert "LEAVE RODAN" in out


# ---- the runtime's part ---------------------------------------------------------------------------------
def _section(src):
    """The runtime's PAD-707 section, verbatim: from its first #define to the end of more_ball_end."""
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
static const struct pm_mode *current;
static unsigned can = PM_CAN_SCREENS | PM_CAN_MESSAGES;
static int (*roster_fn[N_ROSTER])(unsigned slot);
static const struct pm_mode *roster_by[N_ROSTER];
static int roster_resuming;
static int in_game = 1, timer_on = 1, held, no_callouts;
static unsigned up = 1, states[7];
static unsigned screen_obj[8];                       /* the game's screen: its cursor at +16 */
static void say(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); putchar('\n'); }
int pm_roster_slots(void) { return 7; }
static int roster_callout_set(unsigned s, unsigned id, const char *why)
{ if (no_callouts) return 0; printf("CALLOUT %u %u\n", s, id); return 1; }
static void roster_callout_restore(unsigned s) { printf("CALLOUT %u back\n", s); }
static char node_names[64][120];
static int n_nodes;
void *pm_node(const char *scene, const char *path)
{ int i; if (strstr(path, "NOPAGE")) return 0;
  for (i = 0; i < n_nodes; i++) if (!strcmp(node_names[i], path)) return node_names[i];
  snprintf(node_names[n_nodes], 120, "%s", path); return node_names[n_nodes++]; }
void pm_show(void *node, int on) { const char *p = strrchr((const char *)node, '.'); printf("%s %s\n", on ? "SHOW" : "HIDE", p ? p + 1 : (const char *)node); }
int pm_snprintf(char *o, unsigned long cap, const char *fmt, ...)
{ va_list ap; int n; va_start(ap, fmt); n = vsnprintf(o, cap, fmt, ap); va_end(ap); return n; }
static unsigned long now_ms;
/* PAD-733: the city screen's rematch line - the battle rule's seven slot records (12 bytes, the battle's id at +4: 12 +
 * the slot), the city each player is in and the battle it holds for them, the table's line count */
static long rematch_line = -1;
static unsigned slot_recs[21] = { 0, 12, 0, 0, 13, 0, 0, 14, 0, 0, 15, 0, 0, 16, 0, 0, 6, 0, 0, 17, 0 };
static unsigned battle_rule[4], held_ids[4], city_now, line_count = 3949;
static unsigned rw(unsigned a) { return *(const unsigned *)(unsigned long)a; }
static unsigned roster_city_of(unsigned p) { return city_now; }
static unsigned roster_city_rec(unsigned idx, long vec_at, unsigned rec)
{ return vec_at == 56 ? (unsigned)(unsigned long)held_ids : 0; }
static int message_borrow(unsigned id, unsigned idx, const char *words)
{ printf("BORROW %u '%s'\n", idx, words); return 1; }
void pm_message_restore(unsigned id) { printf("RESTORE %u\n", id & 0x7fffffffu); }
unsigned long pm_ms(void) { return now_ms; }
int pm_in_game(void) { return in_game; }
unsigned pm_player(void) { return up; }
long pm_port_value(const char *n, long fb)
{
    if (!strcmp(n, "roster_start_after_ms")) return 3000;
    if (!strcmp(n, "roster_left_sound")) return 271;
    if (!strcmp(n, "roster_right_sound")) return 272;
    if (!strcmp(n, "roster_cursor_at")) return 16;
    if (!strcmp(n, "roster_rematch_line")) return rematch_line;
    if (!strcmp(n, "roster_city_battle_vec_at")) return 56;
    if (!strcmp(n, "roster_vec_at")) return 8;
    if (!strcmp(n, "roster_record_size")) return 12;
    if (!strcmp(n, "roster_id_at")) return 4;
    return fb;
}
const char *pm_port_text(const char *n)
{
    static const char *tiles[7] = { "Ebirah", "Titan", "Gigan", "Megalon", "Ghidorah", "MegalonGigan", "GhidorahGigan" };
    if (!strcmp(n, "roster_screen_scene")) return "cac32730";
    if (!strcmp(n, "roster_screen_path")) return "SelectOverlay_Textbox.CharacterSelect_Instance.";
    static const char *boxes[7] = { "T1_1_Artbox", "T1_2_Artbox", "T1_3_Artbox", "T1_4_Artbox", "T2_1_Artbox",
                                    "T2_2_Artbox", "T2_3_Artbox" };
    if (!strncmp(n, "roster_tile_", 12)) return tiles[atoi(n + 12)];
    if (!strcmp(n, "roster_box_path")) return "SelectOverlay_Textbox.";
    if (!strncmp(n, "roster_box_", 11)) return boxes[atoi(n + 11)];
    return 0;
}
int pm_sound(unsigned r) { printf("SOUND %u\n", r); return 1; }
/* the game's functions the section calls */
static void g_bump(unsigned s, unsigned by) { printf("BUMP %u\n", by); }
static void g_land(unsigned s) { printf("LAND slot %u\n", screen_obj[4]); }
static unsigned g_state(unsigned rule, unsigned slot) { return states[slot]; }
static unsigned g_timer(unsigned id) { return id == 83 ? timer_on : 0; }
static unsigned g_held(unsigned sw) { return held; }
static unsigned fn(const char *n)
{
    if (!strcmp(n, "roster_screen_bump")) return (unsigned)(unsigned long)g_bump;
    if (!strcmp(n, "roster_cursor")) return (unsigned)(unsigned long)g_land;
    if (!strcmp(n, "roster_slot_state")) return (unsigned)(unsigned long)g_state;
    if (!strcmp(n, "roster_timer_on")) return (unsigned)(unsigned long)g_timer;
    if (!strcmp(n, "roster_switch_held")) return (unsigned)(unsigned long)g_held;
    return 0;
}
static unsigned data(const char *n)
{
    if (!strcmp(n, "message_count")) return (unsigned)(unsigned long)&line_count;
    if (!strcmp(n, "rule_battle")) { battle_rule[2] = (unsigned)(unsigned long)slot_recs; return (unsigned)(unsigned long)battle_rule; }
    return 0x1000;
}
"""

DRIVER = r"""
static const struct pm_mode A = { "A", 0, 0, 0, 0, 0 };
static int nope;
static int pick(unsigned slot)
{
    printf("PICKED %s slot %u after %ld\n", pm_roster_more_picked() ? pm_roster_more_picked() : "?", slot,
           pm_roster_start_after());
    return !nope;
}
int main(int argc, char **argv)
{
    int k;
    unsigned regs[4];
    current = &A;
    for (k = 1; k < argc; k++) {
        const char *c = argv[k];
        regs[0] = (unsigned)(unsigned long)screen_obj;
        if (!strcmp(c, "join")) { int s = atoi(argv[++k]); const char *n = argv[++k]; char page[64];
            snprintf(page, sizeof page, "PadSel_%s", n); current = &A;
            printf("JOIN %d\n", pm_roster_more((unsigned)s, n, page, 900 + s, pick)); }
        else if (!strcmp(c, "leave")) { current = &A; pm_roster_more_leave(argv[++k]); }
        else if (!strcmp(c, "open")) { screen_obj[4] = (unsigned)atoi(argv[++k]); on_roster_open(regs); }
        else if (!strcmp(c, "right") || !strcmp(c, "left") || !strcmp(c, "action")) {
            regs[1] = c[0] == 'r' ? 139 : c[0] == 'l' ? 137 : 34;
            int vetoed = on_roster_keys(regs);
            printf("KEY %s vetoed %d cursor %u\n", c, vetoed, screen_obj[4]);
        }
        else if (!strcmp(c, "gamepick")) {               /* the game's own pick: its pick fn, then the battle's start */
            unsigned s = screen_obj[4];
            on_roster_pick(regs);
            if (roster_fn[s]) { current = roster_by[s]; printf("TAKEN %d (slot %u)\n", roster_fn[s](s), s); current = 0; }
            else printf("GAME BATTLE %u\n", s);
        }
        else if (!strcmp(c, "resume")) { int s = atoi(argv[++k]); roster_resuming = 1; current = roster_by[s];
            printf("RESUME %d\n", roster_fn[s] ? roster_fn[s]((unsigned)s) : -1); current = 0; roster_resuming = 0; }
        else if (!strcmp(c, "tick")) more_tick();
        else if (!strcmp(c, "ms")) now_ms = strtoul(argv[++k], 0, 10);
        else if (!strcmp(c, "MARK")) puts("MARK");
        else if (!strcmp(c, "lost")) more_over(up, 0);
        else if (!strcmp(c, "won")) more_over(up, 1);
        else if (!strcmp(c, "state")) { int s = atoi(argv[++k]); states[s] = (unsigned)atoi(argv[++k]); }
        else if (!strcmp(c, "timeroff")) timer_on = 0;
        else if (!strcmp(c, "held")) held = 1;
        else if (!strcmp(c, "nocallouts")) no_callouts = 1;
        else if (!strcmp(c, "nope")) nope = 1;
        else if (!strcmp(c, "gameover")) in_game = 0;
        else if (!strcmp(c, "rematch")) rematch_line = atol(argv[++k]);
        else if (!strcmp(c, "city")) city_now = (unsigned)atoi(argv[++k]);
        else if (!strcmp(c, "holds")) held_ids[up - 1] = (unsigned)atoi(argv[++k]);
        else if (!strcmp(c, "ball_end")) more_ball_end();
        else if (!strcmp(c, "slots")) { int s; for (s = 0; s < 7; s++) printf("SLOT%d %s\n", s, roster_by[s] ? roster_by[s]->name : "-"); }
    }
    return 0;
}
"""


def menu(tmp_path, *args):
    src = RUNTIME.read_text(encoding="utf-8").replace("\r\n", "\n")
    code = PRELUDE + _section(src) + DRIVER
    return _host_run(tmp_path, code, flags=("-I", str(SDK), "-no-pie", "-Wno-unused-function"),
                     args=[str(a) for a in args])


THREE = ("join", 0, "KUMONGA", "join", 1, "KAMACURAS", "join", 2, "KIRYU")


def test_each_monster_stands_in_its_own_place(tmp_path):
    out = menu(tmp_path, *THREE, "slots", "leave", "KAMACURAS", "slots")
    assert out.split("SLOT0")[1].startswith(" MORE KAIJU")
    first = out.split("leave")[0] if "leave" in out else out
    assert re.findall(r"SLOT(\d) MORE KAIJU", out)[:3] == ["0", "1", "2"]
    tail = out.split("KAMACURAS leaves the selection screen")[1]
    assert "SLOT1 -" in tail and "SLOT0 MORE KAIJU" in tail and "SLOT2 MORE KAIJU" in tail
    assert "CALLOUT" not in first                                # the places keep their own callouts


def test_the_cursor_walks_each_place_then_the_monsters_booked_against_it(tmp_path):
    """David: "pick A | B, C | D, E, F" - each game place, then the new monsters that book the same battle (in their
    names' order), place by place (battle_select.walk, the build's)."""
    out = menu(tmp_path, *THREE, "open", 0, *(["right"] * 10))
    landed = re.findall(r"KEY right vetoed 1 cursor (\d)", out)
    assert landed == ["0", "1", "1", "2", "2", "3", "4", "5", "6", "0"]
    news = re.findall(r"the cursor is on (\w+) \(new monster (\d), in slot (\d)'s place\)", out)
    assert news == [("KUMONGA", "3", "0"), ("KAMACURAS", "1", "1"), ("KIRYU", "2", "2")]
    assert out.count("SOUND 272") == 10 and out.count("BUMP 3") == 10
    assert BS.walk([0, 1, 2]) == [0, ("new", 0), 1, ("new", 1), 2, ("new", 2), 3, 4, 5, 6]
    assert BS.walk([1, 1, 0]) == [0, ("new", 2), 1, ("new", 0), ("new", 1), 2, 3, 4, 5, 6]


def test_left_goes_back_and_wraps(tmp_path):
    out = menu(tmp_path, *THREE, "open", 0, "left", "left")
    assert re.findall(r"KEY left vetoed 1 cursor (\d)", out) == ["6", "5"]   # round to the right column's last
    assert "SOUND 271" in out


def test_a_monster_lands_with_its_own_callout_through_the_games(tmp_path):
    out = menu(tmp_path, *THREE, "open", 0, "right")
    seg = out.split("KEY right")[0].split("selection screen opens")[1]
    assert "CALLOUT 0 900" in seg and "LAND slot 0" in seg and "CALLOUT 0 back" in seg
    out = menu(tmp_path, *THREE, "nocallouts", "open", 0, "right")
    assert "SOUND 900" in out                                     # no table to swap: played straight


def test_locked_places_and_their_monsters_are_skipped(tmp_path):
    out = menu(tmp_path, *THREE, "join", 4, "MOTHRA", "state", 4, 1, "state", 5, 1, "state", 6, 1,
               "open", 0, *(["right"] * 7))
    # the walk: 0 KUMONGA 1 KAMACURAS 2 KIRYU 3 4 5 6 MOTHRA -> locked 4-6 and MOTHRA (booked against 4) skipped
    names = re.findall(r"the cursor is on (\w+) \(new", out)
    assert "MOTHRA" not in names
    assert re.findall(r"KEY right vetoed 1 cursor (\d)", out) == ["0", "1", "1", "2", "2", "3", "0"]


def test_the_games_guards_and_chords_stay_the_games(tmp_path):
    out = menu(tmp_path, *THREE, "open", 0, "timeroff", "right")
    assert "KEY right vetoed 0" in out
    out = menu(tmp_path, *THREE, "open", 0, "held", "right")
    assert "KEY right vetoed 0" in out                             # both flippers: the game's pick
    out = menu(tmp_path, *THREE, "open", 0, "action")
    assert "KEY action vetoed 0" in out
    out = menu(tmp_path, "open", 0, "right")
    assert "KEY right vetoed 0" in out                             # no new monsters: the game's own walk


def test_its_nodes_show_and_the_places_portrait_hides(tmp_path):
    out = menu(tmp_path, *THREE, "tick", "open", 0, *(["right"] * 3), "tick", "left", "tick")
    found = out.split("open")[0] if "open" in out else out
    assert "HIDE PadSel_KAMACURAS_Lit" in found and "HIDE PadSel_KAMACURAS_Portrait" in found
    on = out.split("KEY right vetoed 1 cursor 1")[-1].split("KEY left")[0]
    assert "SHOW PadSel_KAMACURAS_Lit" in on and "SHOW PadSel_KAMACURAS_Portrait" in on
    assert "SHOW PadSel_Cover1" in on and "HIDE TitanFullBody_instance" in on
    back = out.split("KEY left")[1]
    assert "HIDE PadSel_KAMACURAS_Lit" in back and "SHOW TitanFullBody_instance" in back and "HIDE PadSel_Cover1" in back


def test_a_won_place_shows_the_claw_a_locked_one_the_lock(tmp_path):
    """David (v21): "the footprint icons over the beaten modes are off" - the claw goes on the tile that won alone: a
    place KUMONGA won shows KUMONGA's claw and hides the place's own state box (the game's claw for a battle it never
    played); a place the game's own battle won keeps its box and puts no claw on the new tile booked against it."""
    out = menu(tmp_path, *THREE, "open", 0, "right", "gamepick", "won", "state", 0, 2, "state", 2, 2, "state", 1, 1,
               "tick", "open", 3, "tick")
    shown = out.split("selection screen opens")[2]
    assert "SHOW PadSel_KUMONGA_Done" in shown and "SHOW PadSel_KAMACURAS_Lock" in shown
    assert "HIDE PadSel_KIRYU_Done" in shown and "SHOW PadSel_KIRYU_Done" not in shown
    assert "SHOW PadSel_KIRYU_Lock" not in shown
    assert "HIDE T1_1_Artbox" in shown
    assert "Artbox" not in shown.replace("HIDE T1_1_Artbox", "")   # the game's boxes are the game's to show (run22:
    #                                                                shown, an open place's box drew its footprint)
    out = menu(tmp_path, *THREE, "state", 0, 2, "tick", "open", 3, "tick")      # the game's own win of place 0
    shown = out.split("selection screen opens")[1]
    assert "HIDE PadSel_KUMONGA_Done" in shown and "Artbox" not in shown
    out = menu(tmp_path, *THREE, "open", 0, "right", "gamepick", "won", "state", 0, 2, "tick", "open", 3, "tick",
               "gameover", "tick", "tick")                              # the game over: our hide undone, once
    assert out.split("selection screen opens")[2].count("SHOW T1_1_Artbox") == 1


def test_a_picked_monster_stays_on_the_screen_through_its_close(tmp_path):
    """PAD-730 (David: "When selecting a bonus monster, the wrong monster is briefly shown before the screen
    transition"): the game's screen fades out after its pick, so the picked monster's tile and portrait stay on and the
    place's own portrait hidden until it has closed (roster_start_after_ms) - before, the place's own showed at once."""
    out = menu(tmp_path, *THREE, "open", 0, *(["right"] * 3), "tick", "ms", 100, "gamepick", "tick",
               "ms", 3099, "tick", "MARK", "ms", 3100, "tick")
    fade = out.split("TAKEN 1 (slot 1)")[1].split("MARK")[0]
    assert "PadSel_KAMACURAS" not in fade and "TitanFullBody" not in fade and "PadSel_Cover1" not in fade
    closed = out.split("TAKEN 1 (slot 1)")[1]
    assert "HIDE PadSel_KAMACURAS_Portrait" in closed and "SHOW TitanFullBody_instance" in closed
    assert "HIDE PadSel_Cover1" in closed
    for end in (("ball_end",), ("open", 1)):                      # the ball's end or the next opening: put back at once
        out = menu(tmp_path, *THREE, "open", 0, *(["right"] * 3), "tick", "gamepick", "tick", *end, "tick")
        assert "SHOW TitanFullBody_instance" in out.split("TAKEN 1 (slot 1)")[1]
    out = menu(tmp_path, *THREE, "open", 0, "right", "right", "tick", "gamepick", "tick")   # the place's own battle
    assert "TAKEN 0 (slot 1)" in out and "SHOW PadSel_" not in out.split("TAKEN 0")[1]


def test_the_city_screens_rematch_names_the_monster_lost_there(tmp_path):
    """PAD-733 (David: "if a mode is failed and you come back to start it again it still says fight biolante again
    when it's supposed to be kumunga"): the city screen's TO REMATCH %s line (3750) names the new monster while the
    player's city holds the battle it lost - and is the game's own again when it does not, or at the game's end."""
    lost = ("rematch", 3750, *THREE, "open", 0, "right", "tick", "gamepick", "tick", "lost", "holds", 12)
    out = menu(tmp_path, *lost, "tick", "MARK", "tick")
    assert "TAKEN 1 (slot 0)" in out
    assert out.count("BORROW 3750 'TO REMATCH KUMONGA'") == 1 and "RESTORE" not in out      # once, and held
    out = menu(tmp_path, *lost, "tick", "MARK", "city", 1, "tick")      # travelled: that city's battle is the game's
    assert "RESTORE 3750" in out.split("MARK")[1]
    out = menu(tmp_path, *lost, "tick", "MARK", "holds", 13, "tick")    # the city holds another battle now
    assert "RESTORE 3750" in out.split("MARK")[1]
    out = menu(tmp_path, *lost, "tick", "MARK", "gameover", "tick")
    assert "RESTORE 3750" in out.split("MARK")[1]
    out = menu(tmp_path, "rematch", 3750, *THREE, "open", 0, "right", "tick", "gamepick", "tick", "won", "holds", 12,
               "tick")                                                  # won: nothing to rematch
    assert "BORROW" not in out
    out = menu(tmp_path, *THREE, "open", 0, "right", "tick", "gamepick", "tick", "lost", "holds", 12, "tick")
    assert "BORROW" not in out                                          # a port without the line: the game's


def test_a_lost_monster_comes_back_only_in_the_city_that_holds_it(tmp_path):
    """PAD-733: the city pick replays the lost monster in the city it was lost in; another city's replay of the same
    place's battle is the game's own."""
    base = (*THREE, "open", 0, "right", "tick", "gamepick", "tick", "lost")
    assert "RESUME 1" in menu(tmp_path, *base, "resume", 0)
    assert "RESUME 0" in menu(tmp_path, *base, "city", 2, "resume", 0)


def test_the_games_pick_under_a_monster_is_the_monsters(tmp_path):
    out = menu(tmp_path, *THREE, "open", 0, *(["right"] * 3), "gamepick")
    assert "the selection screen picks KAMACURAS (in slot 1's place)" in out
    assert "PICKED KAMACURAS slot 1 after 3000" in out              # it starts once the game's screen has closed
    assert "TAKEN 1 (slot 1)" in out
    assert "KAMACURAS picked for player 1 - its mode has slot 1's battle" in out


def test_the_places_own_tile_picks_the_places_own_battle(tmp_path):
    out = menu(tmp_path, *THREE, "open", 0, "right", "right", "gamepick")
    assert "TAKEN 0 (slot 1)" in out and "PICKED" not in out        # Destoroyah's own battle runs
    out = menu(tmp_path, *THREE, "open", 3, "gamepick")
    assert "GAME BATTLE 3" in out                                    # a place no monster stands in: untouched


def test_a_monster_that_will_not_start_lets_the_places_battle_run(tmp_path):
    out = menu(tmp_path, *THREE, "nope", "open", 0, *(["right"] * 3), "gamepick")
    assert "KAMACURAS did not take the pick - the place's own battle runs" in out and "TAKEN 0" in out


def test_a_lost_monster_comes_back_at_the_city_pick(tmp_path):
    out = menu(tmp_path, *THREE, "open", 0, *(["right"] * 3), "gamepick", "lost", "resume", 1, "resume", 0)
    assert "KAMACURAS's battle lost for player 1 - the city pick plays it again" in out
    tail = out.split("battle lost")[1]
    assert "KAMACURAS plays again (the city pick: the battle player lost)" in tail
    assert "RESUME 1" in tail and "RESUME 0" in tail                # in Biollante's place: Biollante's own replays


def test_a_won_monster_does_not_come_back(tmp_path):
    out = menu(tmp_path, *THREE, "open", 0, *(["right"] * 3), "gamepick", "won", "resume", 1)
    assert "KAMACURAS's battle won for player 1" in out
    assert "RESUME 0" in out.split("battle won")[1]


def test_outside_a_game_the_pick_is_the_games(tmp_path):
    out = menu(tmp_path, *THREE, "open", 0, *(["right"] * 3), "gameover", "gamepick")
    assert "TAKEN 0" in out


def test_the_runtime_wires_the_screen_in():
    src = RUNTIME.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert 'hook_veto(fn("roster_screen_keys"), on_roster_keys)' in src
    assert 'hook(fn("roster_screen_open"), on_roster_open)' in src and 'hook(fn("roster_screen_pick"), on_roster_pick)' in src
    assert "    more_tick();" in src and "    more_ball_end();" in src and "    more_over(p, won);" in src
    assert "more_holding" not in src and "more_buttons" not in src     # the old screen of its own is gone
    assert "    roster_resuming = 1;\n    roster_take(" in src


# ---- the scene the card build makes ------------------------------------------------------------------------
def _scene_bytes():
    """A small selection screen of the measured shape: the map, the overlay with the title, the grey sheet, seven
    places' portraits and lit tiles, their state boxes and words - built with the tree's own writer."""
    sc = T.Scene()
    sc.classes = {1: "Bitmap", 3: "Text", 4: "Sprite", 5: "Shape"}
    ids = [10]

    def nid():
        ids[0] += 1
        return ids[0]

    def tex(w, h, rgba):
        px = np.zeros(((h + 3) // 4 * 4, (w + 3) // 4 * 4, 4), np.uint8)
        px[:h, :w] = rgba
        t = nid()
        from pinball_decryptor.plugins.stern import dds
        sc.textures[t] = dict(w=w, h=h, fmt=5, name="", blob=dds.encode_bc3(px), data_off=None)
        return t

    def bitmap(name, w, h, rgba, x, y, s=1.0, shear=0.0):
        o = T.Obj(nid(), "Bitmap", dict(sym=16, name="", w=w, h=h, tex=tex(w, h, rgba)))
        sc.objects[o.id] = o
        return T.Node(nid(), name, 1, [(1, 1)], [], [(1, [s, shear, 0, 0, 0, s, 0, 0, 0, 0, 1, 0, x, y, 0, 1])],
                      [T.Component(1, 1, o)])

    def group(name, kids, x, y, s=1.0, kf=None):
        o = T.Obj(nid(), "Sprite", dict(sym=19, name="", frames=1, kids=kids, labels=[]))
        sc.objects[o.id] = o
        return T.Node(nid(), name, 1, kf or [(1, 1)], [], [(1, [s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1, 0, x, y, 0, 1])],
                      [T.Component(1, 4, o)])

    def tile(c):
        a = np.zeros((40, 48, 4), np.uint8)
        a[2:38, 2:46] = (200, 200, 200, 255)
        a[6:34, 6:42] = c + (255,)
        return a
    cs_kids = [bitmap("unnamed_sheet", 160, 260, np.full((260, 160, 4), 120, np.uint8), 0, 0)]
    for s, n in enumerate(BS.SLOT_NODES):
        frame = np.zeros((90, 70, 4), np.uint8)
        frame[:, :] = (220, 220, 220, 255)
        name = np.zeros((40, 100, 4), np.uint8)
        name[10:30, 10:90] = (255, 140, 0, 255)
        cs_kids.append(group(n + "FullBody_instance", [bitmap("frame", 70, 90, frame, 0, 0),
                                                       bitmap("PAD_%d4a" % s, 100, 40, name, 40, -50)],
                             200, 40, kf=[(1, 1 if s == 0 else 0)]))
    for s, n in enumerate(BS.SLOT_NODES):
        col, row = (0, s) if s < 4 else (1, s - 4 + 0.5)
        cs_kids.append(group(n + "_Selected_instance", [bitmap("t", 48, 40, tile((30 * s, 90, 200)), 0, 0)],
                             10 + col * 70, 10 + row * 60))
    chars = group(BS.CHARS, cs_kids, -300, -300)
    ov_kids = [chars]
    for s, a in enumerate(BS.ARTBOX):
        lock = np.zeros((10, 8, 4), np.uint8)
        lock[...] = (250, 250, 250, 255)
        ov_kids.append(group(a + "_Artbox", [bitmap("lock", 8, 10, lock, 0, 0), bitmap("claw", 8, 10, lock, 0, 0)],
                             -280 + (s >= 4) * 70, -280 + (s % 4) * 60))
    overlay = group(BS.OVERLAY, ov_kids, 400, 400)
    shape = T.Obj(nid(), "Shape", dict(sym=20, name="", rect=[0.0, 0.0, 800.0, 480.0], fill=1,
                                         bitmap=T.Obj(nid(), "Bitmap", dict(sym=16, name="", w=4, h=4,
                                                                           tex=tex(4, 4, (20, 40, 80, 255))))))
    sc.objects[shape.id] = shape
    sc.objects[shape.body["bitmap"].id] = shape.body["bitmap"]
    bg = group("map", [T.Node(nid(), "shape", 1, [(1, 1)], [], [(1, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])],
                              [T.Component(1, 5, shape)])], 0, 0)
    sc.stage = (800, 480, 30.0, [0.2, 0.2, 0.2, 1.0])
    sc.root = dict(sym=19, name="", frames=1, kids=[bg, overlay], labels=[])
    return T.serialize(sc)


@pytest.fixture(scope="module")
def stock():
    try:
        return _scene_bytes()
    except Exception as e:      # the tree writer's grammar for a hand-made scene
        pytest.skip("a hand-made scene does not serialize here: %s" % e)


def _mons(n):
    return [{"slug": "m%d" % i, "name": "MONSTER %d" % i, "slot": i % 3, "picture": ""} for i in range(n)]


def test_the_build_adds_each_monsters_nodes_and_keeps_the_games(stock):
    out = BS.build(stock, _mons(3))
    sc = T.parse(out)
    names = [n.name for n, _p, _d in sc.walk()]
    for i in range(3):
        for part in ("Gray", "Lit", "Lock", "Done", "Portrait"):
            assert "PadSel_m%d_%s" % (i, part) in names
    assert [n for n in names if re.fullmatch(r"PadSel_Cover[0-9]", n)] == ["PadSel_Cover0", "PadSel_Cover1", "PadSel_Cover2"]
    assert sum(n.startswith("PadSel_Gray") for n in names) == 7       # each place's grey cut out of the sheet
    for n in BS.SLOT_NODES:                                            # the game finds its own nodes by name still
        assert n + "_Selected_instance" in names and n + "FullBody_instance" in names
    for i in range(3):                     # what the runtime shows and hides is a Sprite: the game's lookup finds no other
        for part in ("Lit", "Lock", "Done", "Portrait"):
            node = next(n for n, _p, _d in sc.walk() if n.name == "PadSel_m%d_%s" % (i, part))
            assert BS.sprite_of(node) is not None, part
    assert BS.sprite_of(next(n for n, _p, _d in sc.walk() if n.name == "PadSel_Cover0")) is not None
    sheet = next(n for n, _p, _d in sc.walk() if n.name == "unnamed_sheet")
    assert all(v == 0 for _f, v in sheet.keyframes)                    # the sheet itself hidden
    order = [n for n in names if n.startswith("PadSel_") or n.endswith("_Selected_instance")]
    assert order.index("PadSel_Cover0") > order.index("GhidorahGigan_Selected_instance")   # over the lit tiles


def test_the_layout_fits_the_new_tiles_and_moves_the_state_boxes(stock):
    out = BS.build(stock, _mons(3))
    tree = T.parse(out)
    nodes = {n.name: n for n, _p, _d in tree.walk()}
    before = {n.name: n for n, _p, _d in T.parse(stock).walk()}
    moved = [s for s in BS.SLOT_NODES if BS.rest(nodes[s + "_Selected_instance"]) != BS.rest(before[s + "_Selected_instance"])]
    assert moved                                                       # the places laid out again
    assert BS.rest(nodes["T1_2_Artbox"]) != BS.rest(before["T1_2_Artbox"])   # its state box with it
    # the groups split between the columns where the taller is shortest, never inside a group
    assert BS.columns([0, 1, 2]) == ([[0, ("new", 0)], [1, ("new", 1)], [2, ("new", 2)]], [[3], [4], [5], [6]])
    assert BS.columns([4]) == ([[0], [1], [2], [3]], [[4, ("new", 0)], [5], [6]])
    assert BS.columns([]) == ([[0], [1], [2], [3]], [[4], [5], [6]])             # the game's own four and three


def test_a_new_tiles_claw_sits_on_it_as_the_games_on_its_own(stock):
    """David (v21): "one was way too low" - the claw of a new tile sat a tile lower, read off place 4's state box after
    the box had moved and against its tile before it had. On its own tile, as the game's claw is on place 4's."""
    out = BS.build(stock, _mons(3))
    real, BS.PREFIX = BS.PREFIX, "ZZZ_"                         # read the built screen as the game's
    try:
        sc = BS.Screen(T.parse(out))
    finally:
        BS.PREFIX = real
    box = sc.art[4]
    claw = BS.sprite_of(box).body["kids"][1]
    game = BS.apply(BS.mul(BS.inv(sc.glass), BS.mul(sc.os, BS.mul(BS.rest(box), BS.rest(claw)))), 0, 0)
    tile4 = BS.apply(sc.tile_at[4], 0, 0)
    want = (game[0] - tile4[0], game[1] - tile4[1])            # the game's claw from its tile's corner, in CS space
    nodes = {n.name: n for n in sc.kids}
    for i in range(3):
        lit, done = nodes["PadSel_m%d_Lit" % i], nodes["PadSel_m%d_Done" % i]
        corner = BS.apply(BS.mul(BS.rest(lit), BS.rest(BS.sprite_of(lit).body["kids"][0])), 0, 0)
        at = BS.apply(BS.mul(BS.rest(done), BS.rest(BS.sprite_of(done).body["kids"][0])), 0, 0)
        k = BS.rest(lit)[0] / BS.rest(sc.selected[4])[0] if BS.rest(sc.selected[4])[0] else 1.0
        assert abs(at[0] - corner[0] - want[0] * k) < 1.5 and abs(at[1] - corner[1] - want[1] * k) < 1.5, i


def test_no_new_monsters_leaves_the_scene_as_it_was(stock):
    assert BS.build(stock, []) == stock


def test_too_many_or_a_place_out_of_range_is_refused(stock):
    with pytest.raises(BS.BattleSelectError, match="at most 5"):
        BS.build(stock, _mons(6))
    with pytest.raises(BS.BattleSelectError, match="no battle's place"):
        BS.build(stock, [{"slug": "x", "name": "X", "slot": 9, "picture": ""}])
    with pytest.raises(BS.BattleSelectError, match="already carries"):
        BS.build(BS.build(stock, _mons(1)), _mons(1))


def test_a_monsters_picture_is_framed_in_the_places_tile(stock, tmp_path):
    from PIL import Image
    Image.new("RGB", (64, 64), (0, 255, 0)).save(tmp_path / "monster.png")
    out = BS.build(stock, [{"slug": "g", "name": "GREEN", "slot": 0, "picture": str(tmp_path / "monster.png")}])
    tree = T.parse(out)
    lit = next(n for n, _p, _d in tree.walk() if n.name == "PadSel_g_Lit_Art")   # the picture, in its group
    px = BS.texture_rgba(tree, BS.bitmap_of(lit).body["tex"])
    assert (px[20, 24, :3] == (0, 255, 0)).all()                      # the inside is the picture
    assert np.abs(px[3, 3, :3].astype(int) - 200).max() < 16          # the frame is the card's (BC3 again)


def test_the_order_is_the_runtimes():
    found = [{"slug": s, "name": n, "slot": 0, "picture": ""} for s, n in (("r", "rodan"), ("m", "MOTHRA"), ("a", "ANGUIRUS"))]
    assert [m["name"] for m in MK.list_order(found)] == ["ANGUIRUS", "MOTHRA", "rodan"]
    assert BS.page_of("king-ghidorah 2") == "PadSel_king_ghidorah_2"
    assert MP.more_page("king-ghidorah 2") == "PadSel_king_ghidorah_2"
    assert MK.page_names("x")[0] == "PadSel_x"


def test_a_picture_is_the_monster_png_else_the_badge(tmp_path):
    from PIL import Image
    assert MK.picture_of(str(tmp_path)) == ""
    Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(tmp_path / "badge.png")
    assert MK.picture_of(str(tmp_path)).endswith("badge.png")
    Image.new("RGBA", (40, 40), (0, 255, 0, 255)).save(tmp_path / "monster.png")
    assert MK.picture_of(str(tmp_path)).endswith("monster.png")


def test_names_get_their_katakana_and_are_lettered():
    assert BS.katakana("King Caesar") == "キングシーサー" and BS.katakana("NOBODY") == ""
    art = BS.name_art("KUMONGA", BS.katakana("KUMONGA"), 512, 171)
    assert art.shape == (171, 512, 4) and art[..., 3].max() == 255


class _Spec:
    def __init__(self, name, more):
        self.name, self.more = name, more


class _Prof:
    def can(self, what):
        return True


def test_the_project_puts_each_on_the_screen_in_its_own_place(tmp_path, stock):
    code = [("a", _Spec("Mothra", {"slot": 0})), ("b", _Spec("RODAN", {})), ("c", _Spec("ANGUIRUS", {"slot": 2}))]
    found = MK.monsters(str(tmp_path), code)
    assert [(m["name"], m["slot"]) for m in found] == [("MOTHRA", 0), ("ANGUIRUS", 2)]
    assert MK.problems(found) == []
    out = MK.scene(str(tmp_path), code, _Prof(), stock=stock)
    names = [n.name for n, _p, _d in T.parse(out).walk()]
    assert "PadSel_a_Lit" in names and "PadSel_c_Lit" in names
    assert MK.scene(str(tmp_path), [("b", _Spec("RODAN", {}))], _Prof(), stock=stock) is None
    with pytest.raises(MK.MoreKaijuError, match="not read"):
        MK.scene(str(tmp_path), code, _Prof(), stock=b"")


# ---- the ports -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("port", ["godzilla_le-1.16", "godzilla_pro-1.16", "godzilla_pro-1.15"])
def test_the_godzilla_ports_carry_the_selection_screen(port):
    text = (SDK / "ports" / (port + ".port")).read_text(encoding="utf-8")
    for name, value in (("roster_left_sound", 271), ("roster_right_sound", 272), ("roster_pick_sound", 236),
                        ("roster_select_ms", 13000), ("roster_screen_left", 137), ("roster_screen_right", 139),
                        ("roster_screen_timer", 83), ("roster_screen_busy", 23), ("roster_screen_bump_by", 3)):
        assert re.search(r"^value %s\s+%d\b" % (name, value), text, re.M), name
    for site in ("roster_screen_keys", "roster_screen_open", "roster_screen_pick", "roster_screen_bump",
                 "roster_slot_state", "roster_timer_on", "roster_switch_held", "roster_cursor"):
        assert re.search(r"^site %s\s+0x[0-9a-f]{8} 0x[0-9a-f]{8} 0x[0-9a-f]{8}$" % site, text, re.M), site
    assert re.search(r"^text roster_screen_scene\s+%s$" % BS.SCENE_ID, text, re.M)
    assert re.search(r"^text roster_screen_path\s+%s$" % re.escape(BS.PATH), text, re.M)
    for s, n in enumerate(BS.SLOT_NODES):
        assert re.search(r"^text roster_tile_%d\s+%s$" % (s, n), text, re.M)
    for name in ("roster_left_sound", "roster_right_sound", "roster_pick_sound", "roster_select_ms",
                 "roster_screen_left", "roster_screen_right", "roster_screen_timer", "roster_screen_busy"):
        assert name in portgen.TITLE_VALUES
    # a won pick counts as beaten in its city (the battles' last hit), and each place's state box by name
    assert re.search(r"^site battle_beaten\s+0x[0-9a-f]{8} 0xe92d47f0 0xe1a06000$", text, re.M)
    for d in ("battle_beaten_rule", "battle_beaten_guard"):
        assert re.search(r"^data %s\s+0x[0-9a-f]{8}$" % d, text, re.M), d
    assert re.search(r"^value roster_city_beaten_vec_at 68$", text, re.M)
    assert re.search(r"^value battle_beaten_slots\s+0x0f$", text, re.M)
    assert re.search(r"^text roster_box_path\s+SelectOverlay_Textbox\.$", text, re.M)
    for s, b in enumerate(BS.ARTBOX):
        assert re.search(r"^text roster_box_%d\s+%s_Artbox$" % (s, b), text, re.M)
    assert "roster_city_beaten_vec_at" in portgen.TITLE_VALUES and "battle_beaten_slots" in portgen.TITLE_VALUES
    # PAD-733: the city screen's TO REMATCH %s is line 3750 of every Godzilla build's text table (read off each
    # program); a pick waits for the screen's close at most 2.5 s (the runtime starts it at the close itself)
    assert re.search(r"^value roster_rematch_line\s+3750$", text, re.M) and "roster_rematch_line" in portgen.TITLE_VALUES
    assert re.search(r"^value roster_start_after_ms 2500$", text, re.M)


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


def test_a_form_mode_on_the_screen_writes_roster_more_after_its_slot(le):
    lines = [x for x in MP.runtime_cfg(_form(le, roster_more=True), "rodan").splitlines() if x and x[0] != "#"]
    at = lines.index("roster_slot    0")
    assert lines[at + 1] == "roster_more    PadSel_rodan"
    assert "roster_more" not in MP.runtime_cfg(_form(le), "rodan")          # the battle's place itself, as before
    spec = MP.ModeSpec.from_json(json.loads(json.dumps(_form(le, roster_more=True).to_json())))
    assert spec.roster_more is True                                          # kept in mode.json


def test_form_modes_come_first(le, tmp_path):
    forms = [("rodan", _form(le, roster_more=True)), ("plain", _form(le, name="PLAIN"))]
    code = [("mothra", _Spec("MOTHRA", {"slot": 0}))]
    found = MK.monsters(str(tmp_path), code, forms)
    assert [(m["slug"], m["slot"]) for m in found] == [("rodan", 0), ("mothra", 0)]


# ---- David's v22 notes (2026-10-25): what progresses a mode flashes, the rest is dark ---------------------------
def test_a_chase_over_one_insert_blinks():
    """"the shots for the mode should be flashing, not solid": most of Godzilla's shots have one insert (Powerline
    center: lamp 362), and a chase over one was lit at every step"""
    src = RUNTIME.read_text(encoding="utf-8")
    level = src[src.index("static int lamp_level("):]
    level = level[:level.index("\n}\n")]
    chase = level[level.index("case PM_LAMP_CHASE:"):level.index("default:")]
    assert "if (h->chase_n <= 1) return (el / p) % 2 == 0 ? 255 : 0;" in chase


def test_a_mode_that_holds_the_games_modes_off_darkens_the_shots_it_does_not_light():
    """"other targets should not be flashing": while a mode that keeps the game's modes off runs, every shot it does
    not light is held dark (a block lighting one paints over it; putting one out puts it back to dark, not the
    game's); a mode beside the game's modes leaves them be"""
    p = monster()
    p["game_modes"] = "block"
    p["scripts"][1]["do"].insert(0, {"op": "light_shot", "shot": "Left ramp", "color": "#ffffff", "pattern": "blink",
                                     "rate": num(200)})
    p["scripts"][1]["do"].insert(1, {"op": "lights_off", "shot": "Left ramp"})
    c = BM.to_c(p, "mothra")
    assert "#define QUIET_SHOTS (GAME_MODES != 0)" in c
    assert re.search(r"quiet_shots\(\);\s+/\* PAD-707[^\n]*\n\s+on_mode_start\(\);", c)    # dark, then its own lights
    assert "pm_lamp_shot(named, 0, PM_LAMP_SOLID, 0)" in c
    unlight = c[c.index("UNUSED static void unlight(int i)"):]
    unlight = unlight[:unlight.index("\n}\n")]
    assert "pm_lamp_shot(S[i], 0, PM_LAMP_SOLID, 0)" in unlight and "pm_lamp_release_shot(S[i])" in unlight
    relight = c[c.index("UNUSED static void relight_all(void)"):]
    assert relight.index("quiet_shots();") < relight.index("lamp_send(i)")       # after a show: dark first
    assert re.search(r"#define GAME_MODES\s+2\b", c)
    assert re.search(r"#define GAME_MODES\s+0\b", BM.to_c(monster(), "mothra"))   # "stack": QUIET_SHOTS is 0
