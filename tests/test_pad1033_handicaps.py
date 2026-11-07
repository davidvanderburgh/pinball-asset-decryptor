"""PAD-1033: a handicap for each player (pad_mode_runtime.c "a handicap for each player", plugins/stern/handicap.py).

DoomWalrus666 (Godzilla): each player picks a level, -3 (hardest) to +3 (easiest), and the game's own adjustments read
easier or harder for them while they are up, without leaving Insider Connected. The runtime's changes are lifted
verbatim and run on the host; the levels are worked out of the game's own adjustments (Godzilla: the reporter's list);
the card carries handicap.cfg beside the runtime and a HANDICAP row in the service menu."""
import os
import pathlib

import pytest

from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"
#: the Godzilla programs (PAD_GAME_ELVES=<folder>, else the ticket's scratch copies); tests that need one skip without
ELVES = os.environ.get("PAD_GAME_ELVES", "C:/tmp/PAD-1033/elfs")
GZ = {"le": os.path.join(ELVES, "godzilla_le-1_16_0.elf"), "pro": os.path.join(ELVES, "godzilla_pro-1_16_0.elf")}

MAIN = r"""
#include <stdio.h>
#include <stdint.h>
@FNS@
static void show(const char *s)
{
    struct hand_change c;
    if (hand_change_parse(s, &c)) printf("%s -> %u %u %u %u %u\n", s, c.id, c.op, c.v, c.lo, c.hi);
    else printf("%s -> no\n", s);
}
int main(void)
{
    unsigned last = 0, k;
    /* two players, three balls, then attract (the bytes stay 2 / 4), then the next game */
    static const unsigned seq[][2] = { {1, 1}, {1, 1}, {2, 1}, {1, 2}, {2, 2}, {1, 3}, {2, 3}, {2, 4}, {1, 1}, {1, 1},
                                       {2, 1} };
    printf("new");
    for (k = 0; k < sizeof seq / sizeof seq[0]; k++) printf(" %d", hand_new_game(&last, seq[k][0], seq[k][1]));
    printf("\n");
    show("adj:94+2:0:15"); show("adj:173-1:0:2"); show("adj:195x60:4:30"); show("adj:94=7");
    show("adj:94+-2:0:15"); show("adj:94+2:5:1"); show("adj:0+1:0:2"); show("bs:10"); show("adj:94?2");
    printf("v %u %u %u %u %u %u %u\n", hand_value(5, 1, 6, 0, 15), hand_value(12, 1, 6, 0, 15),
           hand_value(5, 2, 15, 0, 15), hand_value(1, 2, 1, 0, 2), hand_value(20, 3, 60, 4, 30),
           hand_value(20, 3, 150, 4, 30), hand_value(3, 0, 9, 0, 1));
    return 0;
}
"""


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _run(tmp_path):
    src = _src()
    fns = "\n".join([
        "struct hand_change { unsigned id, op, v, lo, hi; };",
        R._lift(src, "static int hexval(int c)"),
        R._lift(src, "static uint64_t number(const char **p, int *ok)"),
        R._lift(src, "static int str_starts(const char *s, const char *prefix)\n{"),
        R._lift(src, "static unsigned hand_value(unsigned own, unsigned op, unsigned v, unsigned lo, unsigned hi)"),
        R._lift(src, "static int hand_change_parse(const char *s, struct hand_change *c)"),
        R._lift(src, "static int hand_new_game(unsigned *last_up, unsigned player, unsigned ball)"),
    ])
    return R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()


def test_a_level_change_reads_and_holds_to_its_range(tmp_path):
    out = _run(tmp_path)
    assert out.pop(0) == "new 1 0 0 0 0 0 0 0 1 0 0"                     # player 1's first ball after anything else
    assert out[:9] == [
        "adj:94+2:0:15 -> 94 1 2 0 15", "adj:173-1:0:2 -> 173 2 1 0 2", "adj:195x60:4:30 -> 195 3 60 4 30",
        "adj:94=7 -> 94 0 7 0 4294967295", "adj:94+-2:0:15 -> no", "adj:94+2:5:1 -> no", "adj:0+1:0:2 -> no",
        "bs:10 -> no", "adj:94?2 -> no"]
    # ball save 5 + 6, 12 + 6 held to 15, 5 - 15 held to 0, battles 1 - 1, heat ray 20 x 60% / x 150% held to 30, = 9
    assert out[9] == "v 11 15 0 0 12 30 9"


def test_it_arms_before_the_score_gate_and_alone_keeps_insider_connected():
    src = _src()
    assert src.index("hand_arm();") < src.index("if (!insider_arm()) return;")
    assert ("(clipv_only || sndm_only || pic_only || idle_only || hand_cfg_only()) && !attract_wanted() "
            "&& !coop_wanted()") in src
    assert "if (hand.on && !hook(fn(\"tick\"), on_hand_tick))" in src       # a card of only this has a tick of its own
    assert "    hand_tick();" in R._lift(src, "static void on_tick(unsigned *r)")
    arm = R._lift(src, "static void hand_arm(void)")
    assert "if (!adj_wrap_arm()) {" in arm and "adj_hand_on = 1;" in arm
    # the getter is wrapped once and each of ours answers in turn (PAD-1031's co-op characters wrap it too)
    chain = R._lift(src, "static unsigned adj_chain(unsigned id)")
    assert chain.index("hand_adj_answer(id, v)") < chain.index("coop_adj_answer(id, v)")
    assert src.count('hook_wrap(fn("adjustment")') == 1
    assert 'str_starts(s, "record ")' in R._lift(_src(), "static void hand_line(const char *s)")


def test_a_level_holds_from_the_players_first_ball():
    """The getter answers a player's level from the game's first read in their first ball (the ball save is read as
    the ball is served, before the pick shows), and the operator's own before it: what the game reads for everyone
    before then never carries a level, and a level never reaches another player."""
    up = R._lift(_src(), "static int hand_level_up(void)")
    assert "if (!(hand.picked & (1u << p))) {" in up and "if (hand_ball() != 1u || !pm_in_game()) return 0;" in up
    assert "!hand_switched_on()" in up
    tick = R._lift(_src(), "static void hand_tick(void)\n{")
    assert "hand_game_check();" in tick and "hand_game_check();" in up                  # a new game: afresh
    assert "hand.picked = hand.asked = 0;" in R._lift(_src(), "static void hand_game_check(void)")
    assert "if (ball != 1u || !pm_in_game()) return;" in tick                          # the pick: the first ball
    assert 'hand_close("the ball scored")' in tick
    assert tick.index("if (hand_waits_for_coop()) {") < tick.index("hand.asked |= 1u << p;")   # a character pick first
    rec = R._lift(_src(), "static void hand_records(unsigned p, int lv)")
    assert "own = hand_adj_game(hand_cache[i].id);" in rec                            # from the operator's, never twice
    assert "a = hand_cache[i].obj + p * 4u + hand_cache[i].at;" in rec
    # a level that leaves a record be gives it back the operator's (the game copied it at the level the pick opened at)
    assert "v = k < n ? hand_value(own, c[k].op, c[k].v, c[k].lo, c[k].hi) : own;" in rec
    assert "if (!lv" not in rec                                                        # level 0 too
    arm = R._lift(_src(), "static void hand_arm(void)")
    assert "!words_match(&probe) || !hook(probe.addr, seen[i])" in arm                 # a record's method checked first


def _gz_port(v):
    from pinball_decryptor.plugins.stern import mode_project as MP
    return MP.read_port(str(PORTS / ("godzilla_%s-1.16.port" % v)))


@pytest.mark.skipif(not all(os.path.isfile(p) for p in GZ.values()), reason="no Godzilla 1.16 programs here")
def test_the_records_godzilla_keeps_a_player_are_found_in_its_program():
    """Every difficulty Godzilla reads once at a player's first ball is in a record of theirs: found by the shape of the
    method that keeps it (the battle and building ones are PAD-1031's, found by hand)."""
    from pinball_decryptor.plugins.stern import handicap as HC
    want = {"le": {168: (0x12e168, 4), 169: (0x15c7a8, 0x14), 170: (0x15c7a8, 4), 173: (0x12406c, 0x10),
                   175: (0x158ba0, 4), 176: (0x1349c4, 4), 178: (0x1685a4, 4), 181: (0x180e44, 4)},
            "pro": {168: (0x12b7a4, 4), 169: (0x159084, 0x14), 170: (0x159084, 4), 173: (0x12175c, 0x10),
                    175: (0x155548, 4), 176: (0x1316a0, 4), 178: (0x164bcc, 4), 181: (0x17d46c, 4)}}
    for v, recs in want.items():
        elf, port = open(GZ[v], "rb").read(), _gz_port(v)
        got = HC.records(elf, port["site"]["adjustment"][0], port["data"]["coop_player"],
                         [94, 168, 169, 170, 173, 175, 176, 178, 181, 195, 207])
        assert {k: (x[0], x[3]) for k, x in got.items()} == recs, v
        assert all(x[1] & 0xFFFF4000 == 0xE92D4000 for x in got.values()), v       # each a push {.., lr}
        text = HC.cfg_text(elf, "godzilla_%s-1.16" % v, port=port)
        assert "record 173 0x%08x 0xe92d40f8 0xe1a04000 0x10" % recs[173][0] in text.splitlines(), v


def test_a_game_without_a_preset_gets_its_difficulties_in_by_thirds(monkeypatch):
    from pinball_decryptor.plugins.stern import handicap as HC
    ranges = {"AD_BALL_SAVE_TIME": (94, 0, 60), "AD_A_DIFFICULTY": (180, 0, 2), "AD_B_DIFFICULTY": (181, 0, 1),
              "AD_C_DIFFICULTY": (182, 0, 2), "AD_D_DIFFICULTY_MAX": (183, 0, 9), "AD_E_DIFFICULTY": (184, 0, 500),
              "AD_F_SCORE": (185, 0, 2)}
    monkeypatch.setattr(HC, "_ranges", lambda elf: ranges)
    lv = HC.levels(b"", "mando_le-1.45")
    ids = {k: [c[1] for c in v] for k, v in lv.items()}
    assert ids[1] == ids[-1] == [94, 180]
    assert ids[2] == ids[-2] == [94, 180, 181]
    assert ids[3] == ids[-3] == [94, 180, 181, 182]                 # not a _MAX count, a 500-step one or a score
    assert [c[2:4] for c in lv[3]] == [("+", 6), ("-", 3), ("-", 3), ("-", 3)]
    assert lv[-3][0][2:4] == ("-", 15) and lv[-1][1][2:4] == ("+", 1)
    assert HC.level_line(2, lv[2]) == "level +2 adj:94+4:0:60,adj:180-2:0:2,adj:181-2:0:1"


def test_nothing_to_change_is_refused(monkeypatch):
    from pinball_decryptor.plugins.stern import handicap as HC
    monkeypatch.setattr(HC, "_ranges", lambda elf: {"AD_FREE_PLAY": (2, 0, 1)})
    with pytest.raises(HC.HandicapError):
        HC.levels(b"", "x-1.0")


def test_handicap_cfg(monkeypatch):
    from pinball_decryptor.plugins.stern import handicap as HC
    monkeypatch.setattr(HC, "_ranges", lambda elf: {"AD_BALL_SAVE_TIME": (94, 0, 15)})
    monkeypatch.setattr(HC._SMo, "flipper_buttons", lambda elf: [60, 59])
    text = HC.cfg_text(b"", "x-1.0", setting=0x7d2000, only=True)
    assert text.splitlines()[1:6] == ["handicap on", "left 60", "right 59", "setting 0x007d2000", "only"]
    assert text.splitlines()[6] == "level -3 adj:94-15:0:15" and text.splitlines()[-1] == "level +3 adj:94+6:0:15"
    assert "setting" not in HC.cfg_text(b"", "x-1.0") and "only" not in HC.cfg_text(b"", "x-1.0")
    monkeypatch.setattr(HC._SMo, "flipper_buttons", lambda elf: [])
    with pytest.raises(HC.HandicapError):
        HC.cfg_text(b"", "x-1.0")


@pytest.mark.skipif(not os.path.isfile(GZ["le"]), reason="no Godzilla LE 1.16 program here")
def test_godzillas_levels_follow_the_reporters_list():
    from pinball_decryptor.plugins.stern import handicap as HC
    elf = open(GZ["le"], "rb").read()
    lv = {k: {c[0]: c[2:] for c in v} for k, v in HC.levels(elf, "godzilla_le-1.16").items()}
    assert lv[1] == {"AD_BALL_SAVE_TIME": ("+", 2, 0, 15), "AD_LIGHT_BATTLE_DIFFICULTY": ("-", 1, 0, 2)}
    assert set(lv[2]) == {"AD_BALL_SAVE_TIME", "AD_LIGHT_BATTLE_DIFFICULTY", "AD_HEAT_RAY_SPINS_PER_LEVEL",
                          "AD_BUILDING_DIFFICULTY"}
    assert lv[2]["AD_HEAT_RAY_SPINS_PER_LEVEL"] == ("x", 60, 4, 30)
    assert {"AD_TANK_ATTACK_QUALIFY_DIFFICULTY", "AD_BRIDGE_ATTACK_MULTIBALL_DIFFICULTY"} <= set(lv[3])
    assert lv[-3]["AD_BALL_SAVE_TIME"] == ("-", 15, 0, 15) and set(lv[-1]) == set(lv[1])
    said = dict(HC.describe(elf, "godzilla_le-1.16"))
    assert said[1] == ["ball save +2 s", "Light Battle Difficulty easier"] and said[-3][0] == "ball save off"
    assert HC._SMo.flipper_buttons(elf) == [60, 59]


@pytest.mark.skipif(not os.path.isfile(GZ["le"]), reason="no Godzilla LE 1.16 program here")
def test_the_handicap_row_takes_a_spare_setting_beside_co_op_play():
    from pinball_decryptor.plugins.stern import menu_settings as M
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    from pinball_decryptor.plugins.stern import engine as E
    t = AdjustmentTable(open(GZ["le"], "rb").read())
    settings, _w, _cat, refused = M.plan_many(t, [E._CoopMenu(lambda *a: None).wanted(),
                                                  E._HandicapMenu(lambda *a: None).wanted()])
    assert not refused
    hand = next(s for s in settings if s.key == M.HANDICAP)
    assert (hand.caption, hand.values, hand.low, hand.default, hand.kind) == ("Handicap", 2, 0, 1, M.onoff_kind(t))
    assert len({s.id for s in settings}) == 2


def test_the_tick_is_kept_in_the_project(tmp_path):
    from pinball_decryptor.plugins.stern import handicap as HC
    assert not HC.load(str(tmp_path))
    assert HC.save(str(tmp_path), True) is False and HC.load(str(tmp_path))
    assert HC.save(str(tmp_path), False) is True and not HC.load(str(tmp_path))


def test_every_latest_build_with_the_co_op_player_bytes_can_have_handicaps():
    from pinball_decryptor.plugins.stern import handicap as HC
    from pinball_decryptor.plugins.stern import mode_project as MP
    profs = list(MP.profiles().values())
    ok = [p for p in profs if not HC.title_refusal(p)]
    assert len(ok) >= 53
    assert all("godzilla_le" not in MP.port_path(p) or not HC.title_refusal(p) for p in profs)


def test_handicap_cfg_rides_with_the_runtime():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mode_install", ROOT / "tools" / "spike2_emu" / "mode_install.py")
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert ("handicap.cfg", 0o100644) in mi.EXTRA_FILES and "handicap.cfg" in mi.STANDALONE_FILES
    for sh in ("cardmodes.sh", "tryit.sh"):
        assert "handicap.cfg" in (ROOT / "tools" / "spike2_emu" / "modes" / sh).read_text(encoding="utf-8"), sh


def test_mode_write_puts_handicap_cfg_beside_the_runtime(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import handicap as HC
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(HC, "_ranges", lambda elf: {"AD_BALL_SAVE_TIME": (94, 0, 15)})
    monkeypatch.setattr(HC._SMo, "flipper_buttons", lambda elf: [60, 59])
    prof = next(p for p in MP.profiles().values() if MP.port_path(p).endswith("godzilla_le-1.16.port"))
    plan = MW.ModePlan(project=str(tmp_path), profile=prof, port=MP.port_path(prof), build=None)
    MW.handicap_into(plan, b"", str(tmp_path / "scratch"), setting=0x7d2000, only=True)
    text = pathlib.Path(plan.handicap_file).read_text(encoding="utf-8")
    assert "handicap on" in text and "setting 0x007d2000" in text and "only" in text.split()
    assert any(x.startswith("handicap +3: ball save +6 s") for x in plan.lines)
    assert any("switched in the service menu (HANDICAP)" in x for x in plan.lines)


def test_the_modes_tab_tick_and_its_levels(tmp_path, monkeypatch):
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import handicap as HC
    from pinball_decryptor.webui.tabs import modes as M
    svc = M.ModesTab.__new__(M.ModesTab)
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "_say", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(HC, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(HC, "title_refusal", lambda prof: "")
    fx = {"cands": [["AD_BALL_SAVE_TIME", 94, 0, 15]],
          "defaults": {"+1": {"AD_BALL_SAVE_TIME": ["+", 2]}, "-1": {"AD_BALL_SAVE_TIME": ["-", 1]}}}
    monkeypatch.setattr(HC, "project_facts", lambda project: ("", fx))
    staged_changes.save(str(tmp_path), {"audio": {"x": "y"}})
    assert svc.set_handicap(True) is True
    assert staged_changes.load(str(tmp_path))[HC.STAGED_KEY] == {"on": True}
    assert state["hand_shown"] is True and state["hand_on"] is True and state["hand_note"] == HC.NOTE
    assert svc.handicap_levels_refresh() is True
    lv = state["hand_levels"]
    assert lv["levels"] == ["+3", "+2", "+1", "-1", "-2", "-3"] and lv["changed"] == 0     # easiest first
    row = lv["grid"][0]
    assert (row["label"], row["lo"], row["hi"]) == ("Ball Save Time", 0, 15)
    assert [c["default"] for c in row["cells"]][2:4] == ["+2 s", "-1 s"]
    # one cell set to a value of the setting's own range, another to the game's own; Defaults clears both
    assert svc.handicap_cell("+1", "AD_BALL_SAVE_TIME", "15") is True
    assert svc.handicap_cell("-1", "AD_BALL_SAVE_TIME", "own") is True
    assert HC.load_custom(str(tmp_path)) == {"+1": {"AD_BALL_SAVE_TIME": 15}, "-1": {"AD_BALL_SAVE_TIME": "own"}}
    assert state["hand_levels"]["changed"] == 2 and state["hand_levels"]["grid"][0]["cells"][2]["custom"] is True
    assert [r["words"] for r in state["hand_levels"]["said"]][2:4] == ["ball save 15 s", "the game's own"]
    assert svc.handicap_cell("+1", "AD_BALL_SAVE_TIME", "") is True                      # back to the app's
    assert HC.load_custom(str(tmp_path)) == {"-1": {"AD_BALL_SAVE_TIME": "own"}}
    assert svc.handicap_defaults() is True and HC.load_custom(str(tmp_path)) == {}
    monkeypatch.setattr(HC, "title_refusal", lambda prof: "no port")
    svc._publish_handicap(str(tmp_path))
    assert state["hand_note_kind"] == "err" and state["hand_shown"] is True              # ticked: shown, in red
    assert svc.set_handicap(False) is True and HC.STAGED_KEY not in staged_changes.load(str(tmp_path))
    assert state["hand_shown"] is False                                                  # a game that cannot: hidden
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    assert 'call("modes.set_handicap", v)' in js and "HandicapLevelsDialog" in js


def test_the_owners_levels(tmp_path, monkeypatch):
    """DoomWalrus666: "customize the settings per handicap level within the scope of what the game difficulty settings
    already offers": a cell reads a value of the setting's own range, or the game's own; the rest stay the app's."""
    from pinball_decryptor.plugins.stern import handicap as HC
    ranges = {"AD_BALL_SAVE_TIME": (94, 0, 15), "AD_A_DIFFICULTY": (180, 0, 2), "AD_X_BALL_SAVE_TIMER": (200, 5, 30),
              "AD_BIG_SCORE": (300, 0, 1000000)}
    monkeypatch.setattr(HC, "_ranges", lambda elf: ranges)
    fx = HC.facts(b"", "mando_le-1.45")
    assert [c[0] for c in fx["cands"]] == ["AD_BALL_SAVE_TIME", "AD_A_DIFFICULTY", "AD_X_BALL_SAVE_TIMER"]
    custom = {"+1": {"AD_A_DIFFICULTY": 0, "AD_X_BALL_SAVE_TIMER": 30, "AD_BALL_SAVE_TIME": "own"},
              "-2": {"AD_A_DIFFICULTY": 9}}                                    # out of its range: left out
    lv = HC.levels_from(fx, custom)
    assert HC.level_line(1, lv[1]) == "level +1 adj:180=0,adj:200=30"         # the runtime's `=`: no range after it
    assert HC.level_line(-2, lv[-2]) == "level -2 adj:94-2:0:15"
    assert dict(HC.describe_levels(lv))[1] == ["A Difficulty 0", "X Ball Save Timer 30"]
    # the project keeps only the cells changed; the tick keeps them when it is unticked
    assert HC.save(str(tmp_path), True) is False
    HC.save_custom(str(tmp_path), "+1", "AD_A_DIFFICULTY", 0)
    HC.save_custom(str(tmp_path), "+1", "AD_BALL_SAVE_TIME", HC.OWN)
    assert HC.load_custom(str(tmp_path)) == {"+1": {"AD_A_DIFFICULTY": 0, "AD_BALL_SAVE_TIME": "own"}}
    HC.save(str(tmp_path), False)
    assert not HC.load(str(tmp_path)) and HC.load_custom(str(tmp_path))["+1"]["AD_A_DIFFICULTY"] == 0
    with pytest.raises(HC.HandicapError):
        HC.save_custom(str(tmp_path), "+4", "AD_A_DIFFICULTY", 0)
    HC.save_custom(str(tmp_path), None, None, None)
    assert HC.load_custom(str(tmp_path)) == {}
