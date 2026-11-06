"""PAD-1031: co-op characters - each teammate picks one at their first ball, and its ability holds while they are up.

DoomWalrus666 (Godzilla): "At the start of each player's Ball 1 ... Each player chooses their Godzilla (or selects
Random) ... No player may choose the same godzilla as another player. Each godzilla will have a unique ability";
daveyvandy: a generic entry point, the Godzilla set beside it. The runtime's character code (pad_mode_runtime.c
"co-op characters") is lifted verbatim and played through a model co-op game: coop.cfg's character lines read, the pick
walked with the flippers past the ones taken, RANDOM, and the adjustment getter's answer while each teammate is up.
The app's side (coop_play.py) reads what a game can have off its program and writes the lines."""
import json
import os
import pathlib

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from tests import test_spike2_mode_roster as R

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
GZ_ELF = "C:/tmp/PAD-1010/elfs/godzilla_le-1_16_0_spike2.elf"

MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
static void say(const char *f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); printf("\n"); }
#define pm_snprintf snprintf
static unsigned long now_ms = 1000;
static unsigned long pm_ms(void) { return now_ms; }
static int pm_in_game(void) { return 1; }
static struct { int on; unsigned button, game, n, turn; } coop;
static unsigned coop_teammates(void) { return coop.n; }
static int str_starts(const char *s, const char *p) { return !strncmp(s, p, strlen(p)); }
@NUMBER@
static int coop_ball_msg = 5, coop_ball_held;
static char shown[96];
static int message_borrow(unsigned id, unsigned idx, const char *w) { (void)id; (void)idx; strcpy(shown, w); return 1; }
static void coop_turn_show(void) { sprintf(shown, "PLAYER %u  BALL %%d", coop.turn); }
static unsigned saved_s;
static int pm_ball_save(unsigned s) { saved_s = s; return 1; }
static unsigned own_adj(unsigned id) { return id == 94 ? 5 : id == 195 ? 20 : 1; }
#define COOP_MSG_ID 0xC0090u
#define MAP_R 1u
static volatile unsigned char *coop_ball_byte;
static int maps_has(unsigned long a, unsigned n, unsigned f) { (void)a; (void)n; (void)f; return 0; }
static unsigned fn(const char *name) { (void)name; return 0; }
static int str_eq(const char *a, const char *b) { return !strcmp(a, b); }
static void *pm_node(const char *where, const char *path) { (void)where; (void)path; return 0; }
static void pm_show(void *node, int on) { (void)node; (void)on; }
struct pm_stock_rule;
static struct pm_stock_rule *pm_stock_rule(unsigned id) { (void)id; return 0; }
static int pm_stock_active(struct pm_stock_rule *r) { (void)r; return 0; }
static uint64_t pm_stock_lit(struct pm_stock_rule *r) { (void)r; return 0; }
static unsigned more_state(unsigned slot) { (void)slot; return 0; }
static unsigned long data(const char *name) { (void)name; return 0; }
@DECL@
@FNS@
static void press(unsigned id) { coop_edge(id, 1, 0x800, 0); }
int main(void)
{
    static const char *const cfg[] = {
        "adj:94x200:0:15,bs:94 GODZILLA 1954|LONGER BALL SAVE", "save:10 GODZILLA 2000|ACTION BUTTON BALL SAVE",
        "adj:195x50:4:30,adj:173=0 GODZILLA GMK|EASIER HEAT RAY", "- SHIN GODZILLA|", "adj:oops NO ABILITY|",
        "boost:200,gift:311 KING KONG|DOUBLE POWER-UPS", 0 };
    int i;
    for (i = 0; cfg[i]; i++) coop_char_line(cfg[i]);
    coop_pick_on = 1; coop.button = 59; coop_left = 60; coop_action = 34; coop_adj_game = own_adj;
    printf("chars %d\n", coop_ch_n);
    for (i = 0; i < coop_ch_n; i++)
        printf("char %d [%s] [%s] adj %u save %u boost %u gift %u\n", i, coop_ch[i].name, coop_ch[i].does,
               coop_ch[i].n_adj, coop_ch[i].save_s, coop_ch[i].boost, coop_ch[i].gift);
    coop.n = 3; coop.turn = 1;
    coop_chars_begin();
    printf("before a pick: %u\n", coop_adj_wrap(94));
    coop_pick_open(1);
    printf("open [%s]\n", shown);
    now_ms += 1600; coop_chars_tick(); printf("flip [%s]\n", shown);
    press(34); coop_chars_tick();
    printf("t1 %d [%s] reads 94: %u 195: %u\n", coop_pick_of[1], shown, coop_adj_wrap(94), coop_adj_wrap(195));
    printf("ball out: %u\n", saved_s); saved_s = 0;
    coop.turn = 2; coop_chars_turn();
    printf("open2 [%s]\n", shown);
    press(34); coop_chars_tick();
    printf("t2 %d reads 94: %u\n", coop_pick_of[2], coop_adj_wrap(94));
    printf("no ball out: %u\n", saved_s);
    now_ms += 5000; press(34); now_ms += 300; press(34); coop_chars_tick();
    printf("save %u\n", saved_s); saved_s = 0;
    now_ms += 200; press(34); now_ms += 300; press(34); coop_chars_tick();
    printf("again %u\n", saved_s);
    coop.turn = 3; coop_chars_turn();
    printf("open3 [%s]\n", shown);
    press(60); coop_chars_tick(); printf("left [%s]\n", shown);
    press(59); coop_chars_tick(); printf("right [%s]\n", shown);
    press(34); coop_chars_tick();
    printf("t3 %d reads 195: %u 173: %u 94: %u\n", coop_pick_of[3], coop_adj_wrap(195), coop_adj_wrap(173), coop_adj_wrap(94));
    coop.turn = 1; coop_chars_turn();
    printf("t1 again: open %d save used %d\n", pk.open, coop_save_used);
    /* a new game: a 4th teammate's RANDOM never takes one a teammate has */
    coop.n = 4; coop_chars_begin();
    coop_pick_of[1] = 0; coop_pick_of[2] = 1; coop_pick_of[3] = 3;
    coop.turn = 4; coop_chars_turn(); press(60); coop_chars_tick(); printf("open4 [%s]\n", shown);
    press(34); coop_chars_tick(); printf("t4 %d\n", coop_pick_of[4]);
    /* the time runs out: the one shown */
    coop_chars_begin(); coop.turn = 1; coop_chars_turn(); press(59); coop_chars_tick();
    now_ms += 20000; coop_chars_tick(); printf("timed %d open %d\n", coop_pick_of[1], pk.open);
    return 0;
}
"""

FNS = ("static int coop_pick_step(int n, int at, int dir, unsigned taken)",
       "static volatile unsigned *coop_cache_field(const struct coop_cache *k)",
       "static unsigned coop_adj_value(unsigned own, unsigned op, unsigned v, unsigned lo, unsigned hi)",
       "static unsigned coop_taken(unsigned except)",
       "static const struct coop_char *coop_char_up(void)",
       "static unsigned coop_adj_wrap(unsigned id)",
       "static void coop_cache_hold(void)",
       "static void coop_gift(const struct coop_char *c)",
       "static void coop_counts_give(const struct coop_char *c)",
       "static void coop_pick_say(void)",
       "static void coop_pick_open(unsigned t)",
       "static void coop_pick_close(const char *how)",
       "static void coop_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity)",
       "static int coop_rule_running(unsigned rules)",
       "static void coop_rules_watch(void)",
       "static int coop_spot(const struct coop_char *c)",
       "static void coop_screens_tick(void)",
       "static void coop_chars_tick(void)",
       "static void coop_chars_begin(void)",
       "static void coop_chars_turn(void)",
       "static void coop_char_line(const char *s)")


def _decl(src):
    """The character section's declarations, verbatim: from its #defines to the last of its globals."""
    start = src.index("#define COOP_CHARS 16")
    end = src.index("static unsigned coop_started[5];", start)
    return src[start:src.index("\n", end) + 1]


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig + "\n{") for sig in FNS)
    number = "\n".join(R._lift(src, sig + "\n{") for sig in ("static int hexval(int c)",   # the runtime's own: it eats
                                                            "static uint64_t number(const char **p, int *ok)"))
    main = MAIN.replace("@NUMBER@", number)                                      # the space after a number
    return R._host_run(tmp_path, main.replace("@DECL@", _decl(src)).replace("@FNS@", fns)).splitlines()


def test_each_teammate_picks_one_nobody_else_has_and_its_ability_holds_while_they_are_up(tmp_path):
    out = _run(tmp_path)
    assert "chars 6" in out
    assert "char 0 [GODZILLA 1954] [LONGER BALL SAVE] adj 1 save 0 boost 0 gift 0" in out
    assert "char 1 [GODZILLA 2000] [ACTION BUTTON BALL SAVE] adj 0 save 10 boost 0 gift 0" in out
    assert "char 2 [GODZILLA GMK] [EASIER HEAT RAY] adj 2 save 0 boost 0 gift 0" in out
    assert "char 3 [SHIN GODZILLA] [] adj 0 save 0 boost 0 gift 0" in out
    assert "char 4 [NO ABILITY] [] adj 0 save 0 boost 0 gift 0" in out
    assert "char 5 [KING KONG] [DOUBLE POWER-UPS] adj 0 save 0 boost 200 gift 311" in out             # an ability it cannot read: none
    assert "before a pick: 5" in out                                # no character yet: the game's own value
    assert "open [PLAYER 1 PICK: GODZILLA 1954]" in out
    assert "flip [LONGER BALL SAVE]" in out                         # then what it does, in turn
    # teammate 1's: the save time doubled (5 -> 10, at most 15); the heat ray is not theirs
    assert "t1 0 [PLAYER 1  BALL %d] reads 94: 10 195: 20" in out
    assert "open2 [PLAYER 2 PICK: GODZILLA 2000]" in out            # 1954 is taken: the first one free
    assert "ball out: 10" in out                                    # the ball served before the pick: its save now
    assert "no ball out: 0" in out                                  # 2000 has no bs: nothing at its pick
    assert "t2 1 reads 94: 5" in out                               # teammate 2 up: the game's own save time
    assert "save 10" in out                                         # Action twice within 0.6 s
    assert "again 0" in out                                         # once a ball
    assert "open3 [PLAYER 3 PICK: GODZILLA GMK]" in out
    assert "left [PLAYER 3 PICK: RANDOM]" in out                    # left past 2000 and 1954 (taken) to RANDOM
    assert "right [PLAYER 3 PICK: GODZILLA 1954]" not in out
    assert "right [PLAYER 3 PICK: GODZILLA GMK]" in out             # and back, past them again
    assert "t3 2 reads 195: 10 173: 0 94: 5" in out                 # half the spins (20 -> 10), held to 4..30
    assert "t1 again: open 0 save used 0" in out                    # a picked teammate is not asked again
    assert "open4 [PLAYER 4 PICK: RANDOM]" in out
    assert "t4 2" in out or "t4 4" in out                           # RANDOM: GMK or NO ABILITY, the free ones
    assert "timed 1 open 0" in out                                  # the time ran out on the one shown


def test_the_pick_step_skips_the_taken_and_wraps_through_random(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static int coop_pick_step(int n, int at, int dir, unsigned taken)")
    main = r"""
#include <stdio.h>
@FN@
int main(void)
{
    printf("[%d %d %d %d %d]", coop_pick_step(3, 3, 1, 0), coop_pick_step(3, 2, 1, 0), coop_pick_step(3, 0, -1, 0),
           coop_pick_step(3, 3, 1, 3), coop_pick_step(3, 2, -1, 3));
    return 0;
}
""".replace("@FN@", fn)
    assert R._host_run(tmp_path, main) == "[0 3 3 2 3]"


def test_the_runtime_asks_for_a_pick_at_each_first_ball_and_reads_the_lines():
    src = RUNTIME.read_text(encoding="utf-8")
    change = R._lift(src, "static unsigned coop_change_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert change.index("coop.turn = next;") < change.index("coop_chars_turn();")
    add = R._lift(src, "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "coop_chars_begin();" in add and "coop_pick_open(1);" in add
    line = R._lift(src, "static void coop_line(const char *s)")
    for w in ('"character "', '"pick on"', '"left "', '"action "'):
        assert w in line
    assert "coop_chars_arm(e);" in R._lift(src, "static void coop_arm(void)")
    assert "coop_chars_tick();" in R._lift(src, "static void coop_tick(void)\n{")
    assert "if (coop_live) coop_edge(id, level, flags, pol);" in R._lift(src, "static void on_switch_edge(unsigned *r)")
    arm = R._lift(src, "static void coop_chars_arm(struct site *e)")
    assert 'hook_wrap(fn("adjustment")' in arm


def test_character_lines_need_a_pick_and_characters():
    assert CP.character_lines(b"", None) == []
    assert CP.character_lines(b"", {"pick": False, "list": [{"name": "A"}]}) == []
    assert CP.character_lines(b"", {"pick": True, "list": []}) == []


def test_names_are_the_top_lines_words():
    assert CP.clean_name("  godzilla   1954 ") == "GODZILLA 1954"
    assert CP.clean_name("a|b") == "A B"
    assert len(CP.clean_name("x" * 60)) == CP.MAX_NAME


def test_the_project_keeps_its_characters_beside_its_awards(tmp_path):
    project = str(tmp_path)
    CP.save(project, True)
    CP.save_award(project, "score", on=False)
    chars = CP.save_characters(project, {"pick": True, "list": [{"name": "godzilla 1954", "ability": "longer_save"},
                                                                {"name": ""}, "junk"]})
    assert chars == {"pick": True, "list": [{"name": "GODZILLA 1954", "ability": "longer_save", "picture": ""}]}
    CP.save(project, False)                                          # unticked: the choices stay
    assert CP.load_characters(project) == chars
    assert CP.load_awards(project) == {"score": {"on": False}}
    CP.save_characters(project, {"pick": False, "list": []})
    assert CP.load_characters(project) == {"pick": False, "list": []}


def test_the_godzilla_customization_file_ships_beside_the_module():
    path = CP.presets()["godzilla"]
    got = CP.read_preset(path)
    assert got["game"] == "Godzilla"
    names = [c["name"] for c in got["characters"]["list"]]
    assert len(names) == 11 and len(set(names)) == 11               # the reporter's eleven abilities, one each
    assert all(len(n) <= CP.MAX_NAME for n in names)
    raw = json.load(open(path, encoding="utf-8"))
    assert all(set(c) <= {"name", "ability", "picture"} for c in raw["characters"])


def test_a_file_that_is_not_one_says_so(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(CP.CoopError):
        CP.read_preset(str(bad))
    with pytest.raises(CP.CoopError):
        CP.read_preset(str(tmp_path / "missing.json"))


@pytest.mark.skipif(not os.path.isfile(GZ_ELF), reason="no Godzilla LE 1.16 program here")
def test_godzillas_abilities_and_lines_read_off_its_program():
    elf = open(GZ_ELF, "rb").read()
    got = {a["key"]: a for a in CP.abilities(elf, "Godzilla")}
    assert got["longer_save"]["cfg"] == "adj:94x200:0:15,bs:94"
    assert got["action_save"]["cfg"] == "save:10"
    assert got["heat_ray"]["cfg"] == "adj:195x50:4:30"
    assert CP.action_button(elf) == 34
    lines = CP.character_lines(elf, CP.read_preset(CP.presets()["godzilla"])["characters"])
    assert lines[:4] == ["pick on", "left 60", "action 34", "character adj:94x200:0:15,bs:94 GODZILLA 1954|LONGER BALL SAVE"]
    text = CP.cfg_text(elf, None, {"pick": True, "list": [{"name": "A", "ability": "heat_ray"}]})
    assert text.endswith("character adj:195x50:4:30 A|EASIER HEAT RAY\n")


def test_a_held_record_gives_back_the_harder_of_the_teams_and_plays(tmp_path):
    """Godzilla raises LIGHT BATTLE DIFFICULTY's record a notch after each battle: held at 0 for an easy teammate, it
    goes back to the team's own, or to what play made of it when that is harder."""
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static unsigned coop_cache_back(unsigned saved, unsigned wrote, unsigned now)")
    main = r"""
#include <stdio.h>
@FN@
int main(void)
{
    printf("[%u %u %u]", coop_cache_back(1, 0, 0), coop_cache_back(1, 0, 2), coop_cache_back(0, 0, 0));
    return 0;
}
""".replace("@FN@", fn)
    assert R._host_run(tmp_path, main) == "[1 2 0]"


def test_godzillas_own_abilities_need_their_port_sites():
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    from pinball_decryptor.plugins.stern import mode_project as MP
    elf = open(GZ_ELF, "rb").read()
    sites = sorted(MP.read_port(str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))["site"])
    got = {a["key"]: a["cfg"] for a in CP.abilities(elf, "Godzilla", sites)}
    assert got["battles"] == "adj:173=0" and got["building"] == "adj:168=0"
    assert got["powerups"] == "boost:200" and got["ally"] == "gift:311"
    bare = {a["key"]: a for a in CP.abilities(elf, "Godzilla")}         # a port without them: not offered, and why
    assert all(not bare[k]["cfg"] and bare[k]["why"] for k in ("battles", "building", "powerups", "ally"))


def test_the_godzilla_ports_name_the_character_sites():
    for key in ("godzilla_le-1.16", "godzilla_pro-1.16"):
        text = (RUNTIME.parent / "ports" / (key + ".port")).read_text(encoding="utf-8")
        for name in ("site coop_adj_changed", "site coop_boost", "site coop_cache_173", "site coop_cache_168",
                     "value coop_cache_173_at", "value coop_cache_168_at"):
            assert name in text, (key, name)


def test_jets_and_tanks_count_where_the_port_names_their_rules():
    """count:<name>+<n> raises a rule's count at the pick: Godzilla's jets through the pointer the game keeps to its
    rule (data coop_count_jets_rule), its tanks through the rule's game-start method (site coop_count_tanks)."""
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    from pinball_decryptor.plugins.stern import mode_project as MP
    elf = open(GZ_ELF, "rb").read()
    port = MP.read_port(str(RUNTIME.parent / "ports" / "godzilla_le-1.16.port"))
    sites = sorted(set(port["site"]) | set(port["data"]))
    got = {a["key"]: a for a in CP.abilities(elf, "Godzilla", sites)}
    assert got["jets"]["cfg"] == "count:jets+4" and got["tanks"]["cfg"] == "count:tanks+4"
    bare = {a["key"]: a for a in CP.abilities(elf, "Godzilla")}
    assert not bare["jets"]["cfg"] and not bare["tanks"]["cfg"]
    for key in ("godzilla_le-1.16", "godzilla_pro-1.16"):
        text = (RUNTIME.parent / "ports" / (key + ".port")).read_text(encoding="utf-8")
        assert "data  coop_count_jets_rule" in text and "site coop_count_tanks" in text
    src = RUNTIME.read_text(encoding="utf-8")
    assert 'str_starts(p, "count:")' in R._lift(src, "static void coop_char_line(const char *s)")
    assert "coop_counts_give(&coop_ch[c]);" in R._lift(src, "static void coop_pick_close(const char *how)")


def test_the_pick_has_a_screen_for_each_character_and_random(tmp_path):
    project = str(tmp_path)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": [{"name": "GODZILLA 1954", "ability": "longer_save"},
                                                        {"name": "SHIN GODZILLA", "ability": ""}]})
    from PIL import Image
    pic = tmp_path / "mine.png"
    Image.new("RGBA", (300, 200), (10, 120, 10, 255)).save(pic)
    CP.save_picture(project, 1, str(pic))
    assert CP.load_characters(project)["list"][1]["picture"] == "coop/character_2.png"
    screens = CP.pick_screens(project, words_for=CP.words_for())
    assert [s["name"] for s in screens] == ["PadCoop_1", "PadCoop_2", "PadCoop_Random"]
    assert screens[0]["words"] == "GODZILLA 1954 - LONGER BALL SAVE" and screens[1]["words"] == "SHIN GODZILLA"
    assert screens[1]["art_rgba"].shape[:2] == (200, 300)              # the owner's picture, not the panel
    assert screens[0]["art_rgba"].shape[:2] == (160, 640)              # the generated panel
    assert CP.preview(project, None, CP.words_for(), 1)[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(CP.CoopError):
        CP.save_picture(project, 0, str(tmp_path / "x.txt")) if (tmp_path / "x.txt").write_text("no") else None
    CP.save_characters(project, {"pick": False, "list": [{"name": "A"}]})
    assert CP.pick_screens(project) == []


def test_co_op_alone_puts_the_pick_screens_in_the_hud_and_names_the_scene(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import scene_write as SW

    class Prof:
        label, game_dir, hud_scene, port = "Godzilla", "godzilla_le", "32e6ae28", ""

        def can(self, part):
            return part == "screen"

        def lcd(self, part):
            return "godzilla_le/assets/lcd/auto_loaded/32e6ae28"
    project = str(tmp_path / "p")
    os.makedirs(project)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": [{"name": "A", "ability": ""}]})
    got = {}
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "")
    monkeypatch.setattr(CP, "cfg_text", lambda *a, **k: "coop on\nbutton 59\n")
    monkeypatch.setattr(SW, "add_screens", lambda hud, screens, **k: (got.setdefault("names", [s["name"] for s in screens])
                                                                      and hud + b"+screens", []))
    result = MW.ModePlan(project=project, profile=Prof(), port="", build=None)
    MW.coop_into(result, b"", str(tmp_path / "scratch"), stock_hud=b"HUD", stock_font=b"")
    assert got["names"] == ["PadCoop_1", "PadCoop_Random"]
    (card, src), = result.replaced
    assert card == "godzilla_le/godzilla_le/assets/lcd/auto_loaded/32e6ae28/scene.radium"
    assert open(src, "rb").read() == b"HUD+screens"
    assert open(result.coop_file).read().endswith("screens 32e6ae28\n")


def test_the_runtime_shows_the_picks_screen_and_reads_where_they_are():
    src = RUNTIME.read_text(encoding="utf-8")
    assert '"screens "' in R._lift(src, "static void coop_line(const char *s)")
    tick = R._lift(src, "static void coop_screens_tick(void)")
    assert '"PadCoop_%d"' in tick and '"PadCoop_Random"' in tick and "pm_show(coop_scr[want], 1);" in tick
    assert "coop_screens_tick();" in R._lift(src, "static void coop_chars_tick(void)")


def test_godzilla_offers_all_eleven_abilities_from_its_ports():
    if not os.path.isfile(GZ_ELF):
        pytest.skip("no Godzilla LE 1.16 program here")
    from pinball_decryptor.plugins.stern import mode_project as MP
    elf = open(GZ_ELF, "rb").read()
    for key in ("godzilla_le-1.16", "godzilla_pro-1.16"):
        port = MP.read_port(str(RUNTIME.parent / "ports" / (key + ".port")))
        got = {a["key"]: a["cfg"] for a in CP.abilities(elf, "Godzilla", set(port["site"]) | set(port["data"]),
                                                         port["value"])}
        assert all(got.values()), (key, [k for k, v in got.items() if not v])
        assert got["spot"] == "spot:0x7f000" and got["tier2"] == "unlock:334@0xf000"
    keys = {c["ability"] for c in CP.read_preset(CP.presets()["godzilla"])["characters"]["list"]}
    assert keys == {a[0] for a in CP.ABILITIES}                      # the preset uses every ability once


def test_spot_and_unlock_read_from_coop_cfg():
    src = RUNTIME.read_text(encoding="utf-8")
    line = R._lift(src, "static void coop_char_line(const char *s)")
    assert 'str_starts(p, "spot:")' in line and 'str_starts(p, "unlock:")' in line
    wrap = R._lift(src, "static unsigned coop_adj_wrap(unsigned id)")
    assert "c->unlock_adj == id && (coop_started[coop.turn] & c->unlock_rules)" in wrap
    spot = R._lift(src, "static int coop_spot(const struct coop_char *c)")
    assert 'fn("shot_dispatch")' in spot and "lit & (~lit + 1)" in spot
