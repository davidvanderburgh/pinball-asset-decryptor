"""PAD-1404: a menu picked with the flippers - a list on the screen, the left flipper button up, the right one down,
Action or Start takes it, its time out takes the one highlighted (it opens on the default); the ball held or the
mode's clock standing still while it is open, as Stern's own choose screens do. In blocks (the program's menus,
Open the menu, When the player picks from a menu, the item picked), the build (mode_menus.py), the SDK kit
(intricate_kit.h kit_menu) and the runtime (pm_button_hide: the game does not see the menu's buttons).

Emulator-proven on Uncanny X-Men LE and Pro 0.98 (C:/tmp/PAD-1404: build_set.py, job.sh)."""
import json
import os
import re
import shutil
import subprocess

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_assets as MA
from pinball_decryptor.plugins.stern import mode_menus as MN
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import scene_write as SW
from tests.test_stern_block_modes import play
from tests.test_stern_scene_write import _fake_scene

SDK = os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")
num = lambda v: {"k": "num", "v": v}          # noqa: E731
PICK = {"k": "menu_pick", "menu": "EPISODE"}
ITEMS = ["DAYS OF FUTURE PAST", "DARK PHOENIX", "AGE OF APOCALYPSE", "SENTINELS", "DANGER ROOM", "GENOSHA",
         "MOJOVERSE"]


def _prog(hold="lane", seconds=10, default=2, start="Building", clock=30):
    """EPISODE PICK: a shot starts it, it opens the menu at its start; the pick logs the item and scores 1000 x it."""
    return BM.normalize({
        "name": "EPISODE PICK", "seconds": clock, "screen": False, "game_modes": "stack",
        "menus": [{"name": "EPISODE", "title": "CHOOSE YOUR EPISODE", "items": ITEMS, "default": default,
                   "seconds": seconds, "hold": hold}],
        "scripts": [
            {"hat": {"kind": "shot", "shot": start, "when": "idle"}, "do": [{"op": "start_mode"}]},
            {"hat": {"kind": "mode_start"}, "do": [{"op": "menu_open", "menu": "EPISODE"}]},
            {"hat": {"kind": "menu_pick", "menu": "EPISODE"}, "do": [
                {"op": "log", "text": "EPISODE PICKED"},
                {"op": "score", "points": {"k": "op", "op": "*", "a": PICK, "b": num(1000)}}]},
            {"hat": {"kind": "shot", "shot": "Action button", "when": "running"}, "do": [
                {"op": "log", "text": "ACTION HEARD BY THE MODE"}]}]})


# ---- the program ----------------------------------------------------------------------------------------------------
def test_menus_are_normalized():
    p = BM.normalize({"menus": [{"name": " EPISODE ", "title": "x" * 50, "items": ["A", " B ", None],
                                 "default": 9, "seconds": 500, "hold": "floor", "color": "red"}]})
    (m,) = p["menus"]
    assert m == {"name": "EPISODE", "title": "x" * BM.MENU_TITLE_MAX, "items": ["A", "B", ""], "default": 1,
                 "seconds": BM.MENU_SECONDS_MAX, "hold": "lane", "color": BM.MENU_COLOR}
    assert BM.normalize({})["menus"] == []
    assert BM.normalize({"menus": [{"items": ["A"], "seconds": 1}]})["menus"][0]["seconds"] == BM.MENU_SECONDS_MIN
    assert BM.MENUS_MAX == MN.MENUS_MAX and BM.MENU_ITEMS_MAX == MN.ITEMS_MAX
    assert BM.MENU_TITLE_MAX == MN.TITLE_MAX and BM.MENU_ITEM_MAX == MN.ITEM_MAX


def test_problems_name_what_is_wrong_with_a_menu():
    ok = _prog()
    assert BM.problems(ok) == []
    bad = BM.normalize({"menus": [{"name": "A", "items": []}, {"name": "a", "items": ["X", ""]},
                                  {"name": "9x", "items": ["Y"] * 14}],
                        "scripts": [{"hat": {"kind": "menu_pick", "menu": "NOPE"}, "do": [
                            {"op": "menu_open", "menu": ""},
                            {"op": "score", "points": {"k": "menu_pick", "menu": "GONE"}}]}]})
    out = " | ".join(BM.problems(bad))
    assert "The menu A has nothing to pick" in out
    assert "Two menus are called a." in out and "The menu a has an empty item" in out
    assert "A menu's name '9x' is not one" in out and "has 14 items: 12 at most" in out
    assert "3 menus: 2 at most." in out
    assert "names a menu that is not there: make it under Menus" in out          # the hat, the value
    assert "has no menu chosen" in out                                         # the block
    # a scoop on a title without one
    assert any("holds the ball in the scoop" in s for s in BM.problems(_prog(hold="scoop"), scoop=False))
    assert BM.problems(_prog(hold="scoop"), scoop=True) == []


def test_the_c_declares_its_menus_and_hands_them_the_shots_the_tick_and_the_clock():
    c = BM.to_c(_prog(), "episode_pick")
    assert '#include "intricate_kit.h"' in c
    assert ('static const char *const MENU0_ITEMS[7] = {"DAYS OF FUTURE PAST", "DARK PHOENIX", "AGE OF APOCALYPSE", '
            '"SENTINELS", "DANGER ROOM", "GENOSHA", "MOJOVERSE"};') in c
    assert '{ "CHOOSE YOUR EPISODE", MENU0_ITEMS, 7, 1, 10000UL, 1 },   /* EPISODE */' in c
    assert 'static struct kit_menu menu[N_MENUS] = {{ .scene = "hud", .node = "PadMode_episode_pick_Menu1" }};' in c
    assert "    if (menu_shot(shot)) return;      /* PAD-1404: an open menu's buttons are the menu's */" in c
    assert "menu_got[k] = kit_menu_tick(&menu[k]);" in c
    assert "if (menu_got[0] >= 0) {" in c and "menu_value(0)" in c
    assert "if (RUN_SECONDS && !menu_open_any()) {" in c
    assert c.count("menus_close();") == 2                                       # its end and the ball's
    plain = BM.to_c(BM.normalize({"name": "X", "scripts": []}), "x")
    assert "kit_menu" not in plain and "intricate_kit.h" not in plain


def test_the_assets_carry_what_the_build_needs_and_go_through_the_set(tmp_path):
    project = str(tmp_path / "X-Men LE 0.98 Extract")
    os.makedirs(project)
    card = "uncanny_xmen_le-0_98_0.Release.16G.sdcard.raw"
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, card), "input_name": card}, f)
    slug, _path = BM.new_blocks_mode(project, "EPISODE PICK", example="ramps")
    p = BM.load(project, slug)
    p.update({k: v for k, v in _prog().items() if k in ("menus", "scripts")})
    BM.save(project, slug, p)
    spec = CM.load(project, slug)
    assert spec.menus == [{"title": "CHOOSE YOUR EPISODE", "color": BM.MENU_COLOR}]
    assert spec.has_assets()                     # its screens go through the set, not compiled in alone
    assert os.path.isfile(os.path.join(MP.mode_folder(project, slug), BM.KIT_FILE))
    prof = MP.profile_from_port(os.path.join(PORTS, "uncanny_xmen_le-0.98.port"))
    names = [s["name"] for s in MA._code_screens(project, [(slug, spec)], prof)]
    st = MN.stem(slug)
    assert names[-7:] == [st + "_Menu1"] + [st + "_Menu1_R%d" % j for j in range(1, 6)] + [st + "_Menu1_Foot"]


def test_has_assets_counts_every_screen_of_its_own():
    """PAD-1404 found PAD-1405's meters and fades (and PAD-547's info line) compiled in alone by Try it: no set."""
    for k, v in (("meters", [{"label": "X"}]), ("fades", [{"color": "#000000"}]), ("menus", [{"title": "X"}]),
                 ("info_line", True)):
        assert CM.CodeAssets(screen=False, **{k: v}).has_assets(), k
    assert not CM.CodeAssets(screen=False).has_assets()


# ---- the screens ----------------------------------------------------------------------------------------------------
def test_a_menu_is_a_panel_five_rows_with_a_bar_each_and_a_foot_premultiplied():
    screens = MN.menu_screens("episode_pick", [{"title": "CHOOSE YOUR EPISODE", "color": "#2080ff"}])
    names = MN.names("episode_pick", 1)
    assert [s["name"] for s in screens] == ([names["node"]] + [names["row"](j) for j in range(1, MN.ROWS + 1)]
                                            + [names["foot"]])
    panel = screens[0]
    assert panel["words"] == "CHOOSE YOUR EPISODE" and panel["words_name"] == names["title"].split(".", 1)[1]
    assert (panel["x"], panel["y"]) == MN.panel_at()
    assert panel["x"] + MN.PANEL_W <= MN.GLASS_W and panel["y"] + MN.PANEL_H <= MN.GLASS_H
    for j, row in enumerate(screens[1:6], 1):
        (bar,) = row["layers"]
        assert bar["name"] == names["row_hi"](j).split(".", 1)[1]
        assert row["words_name"] == names["row_words"](j).split(".", 1)[1]
        assert row["y"] - screens[1]["y"] == MN.ROW_GAP * (j - 1)
    for a in [s["art_rgba"] for s in screens] + [s["layers"][0]["rgba"] for s in screens[1:6]]:
        assert a.shape[0] % 4 == 0 and a.shape[1] % 4 == 0
        assert (a[..., :3].max(axis=2) <= a[..., 3]).all()                   # premultiplied: nothing under clear
    bar = screens[1]["layers"][0]["rgba"]
    assert bar[MN.ROW_H // 2, MN.ROW_W // 2, 2] > bar[MN.ROW_H // 2, MN.ROW_W // 2, 0]   # the menu's own colour
    assert len(MN.menu_screens("x", [{}] * 4)) == 2 * 7                       # two menus a mode at most


def test_the_menus_screens_splice_into_a_scene(monkeypatch):
    data, p = _fake_scene(monkeypatch)
    screens = MN.menu_screens("episode_pick", [{"title": "PICK"}, {"title": "ROSTER"}])
    new, infos = SW.add_screens(data, screens)
    assert len(infos) == 14
    assert SW.string("PadMode_episode_pick_Menu2_R5_Hi") in new and SW.string("PadMode_episode_pick_Menu1_Foot") in new


# ---- the kit, on the desk -------------------------------------------------------------------------------------------
def _picked(out):
    return re.findall(r'menu PadMode_episode_pick_Menu1: picked (\d+) "([^"]*)" \(([^,]*),', out)


def test_flippers_move_wrapping_and_action_takes_it(tmp_path):
    out = play(tmp_path, _prog(), "shot", "Building", "ms", 600,
               "shot", "Right flipper button", "shot", "Right flipper button released",   # a release is the menu's too
               "shot", "Right flipper button", "ms", 200,
               "shot", "Left flipper button", "shot", "Left flipper button", "shot", "Left flipper button",
               "shot", "Left flipper button", "ms", 200,          # 2 -> 4 -> 1 -> wraps to 7 (MOJOVERSE)
               "shot", "Action button", "ms", 600, slug="episode_pick")
    assert 'open "CHOOSE YOUR EPISODE", 7 items, on 2, 10000 ms, hold lane' in out
    assert _picked(out) == [("7", "MOJOVERSE", "Action")]
    assert "EPISODE PICKED" in out and "SCORE +7000" in out
    assert "ACTION HEARD BY THE MODE" not in out                    # the menu's button, not the mode's shot
    assert "BTNHIDE 7400000000000000" in out and "BTNHIDE 0 " in out
    # the panel shown at the open, row 5 of the window highlighted at the end (scrolled: 7 items, 5 rows)
    assert "WORDS PadMode_episode_pick_Menu1_Words: CHOOSE YOUR EPISODE" in out
    assert "WORDS PadMode_episode_pick_Menu1_R5_Words: MOJOVERSE" in out
    assert re.search(r"SHOW PadMode_episode_pick_Menu1_R5\.PadMode_episode_pick_Menu1_R5_Hi 1", out)
    assert re.search(r"SHOW PadMode_episode_pick_Menu1 0", out.split("picked 7")[1])   # gone with the pick
    # after the pick the Action button is the mode's again
    out2 = play(tmp_path, _prog(), "shot", "Building", "ms", 300, "shot", "Start button", "ms", 300,
                "shot", "Action button", "ms", 100, slug="episode_pick")
    assert _picked(out2) == [("2", "DARK PHOENIX", "Start")]
    assert "ACTION HEARD BY THE MODE" in out2


def test_its_time_takes_the_one_highlighted_and_the_clock_waits_meanwhile(tmp_path):
    out = play(tmp_path, _prog(seconds=4, clock=10), "shot", "Building", "ms", 500,
               "shot", "Right flipper button", "secs", 5, "secs", 11, slug="episode_pick")
    assert _picked(out) == [("3", "AGE OF APOCALYPSE", "its time ran out")]
    assert "WORDS PadMode_episode_pick_Menu1_Foot_Words: FLIPPERS MOVE   ACTION PICKS   4" in out
    end = int(re.search(r"^\s*(\d+) \[EPISODE PICK\] END \(time ran out\)", out, re.M).group(1))
    assert end >= 14000                                              # its 10 s began after the 4 s menu


def test_a_lane_menu_takes_the_one_shown_when_the_ball_moves_on_and_none_waits(tmp_path):
    out = play(tmp_path, _prog(), "shot", "Building", "ms", 300, "shot", "Right flipper button",
               "shot", "Right flipper button released", "ms", 300, "shot", "Left ramp", "ms", 300, slug="episode_pick")
    assert _picked(out) == [("3", "AGE OF APOCALYPSE", "the ball moved on: Left ramp")]
    out = play(tmp_path, _prog(hold="none", seconds=3), "shot", "Building", "ms", 300, "shot", "Left ramp", "secs", 4,
               slug="episode_pick")
    assert _picked(out) == [("2", "DARK PHOENIX", "its time ran out")]   # a shot leaves an unheld menu open


def test_the_mode_ending_closes_it_with_nothing_picked(tmp_path):
    out = play(tmp_path, _prog(), "shot", "Building", "ms", 300, "ball_end", "ms", 300, slug="episode_pick")
    assert "menu PadMode_episode_pick_Menu1: closed with no pick" in out
    assert _picked(out) == [] and "EPISODE PICKED" not in out


def test_the_kit_is_in_the_shipped_list():
    import hashlib
    kit = open(os.path.join(SDK, "examples", BM.KIT_FILE), "rb").read().replace(b"\r\n", b"\n")
    shipped = open(os.path.join(SDK, "examples", "kit_shipped.txt"), encoding="utf-8").read()
    assert hashlib.sha256(kit).hexdigest() in shipped


# ---- the ARM build --------------------------------------------------------------------------------------------------
def test_it_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    src = tmp_path / "episode_pick.c"
    src.write_text(BM.to_c(_prog(), "episode_pick"), encoding="utf-8")
    shutil.copy(os.path.join(SDK, "examples", BM.KIT_FILE), tmp_path / BM.KIT_FILE)
    r = subprocess.run(["bash", os.path.join(SDK, "build_mode.sh"), "-o", str(tmp_path / "mode.so"), str(src),
                        os.path.join(SDK, "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
