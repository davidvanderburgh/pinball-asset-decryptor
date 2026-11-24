"""The JJP screen layout editor (PAD-1515): plugins/jjp/screen_layout.py, the new place keys in the
checker (tools/jjp_emu/mkjjpmodes.py) and the runtime (jjpmodes.c), and the Modes tab's calls that
write a dragged box.  The runtime drawing every place is proven on the Wonka emulator
(tools/jjp_emu/proof/pad1515)."""
import os
import re

import pytest

from pinball_decryptor.plugins.jjp import custom_modes as CM
from pinball_decryptor.plugins.jjp import screen_layout as SL
from tests.test_webui_modes_jjp import _jjp, _open_wonka, preview_on, select_card  # noqa: F401
from tests.webui_harness import web_app

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "jjp_emu")


def _src():
    return open(os.path.join(RIG, "jjpmodes.c"), encoding="utf-8").read()


def _body(src, start, end):
    return src[src.index(start):src.index(end, src.index(start))]


# ------------------------------------------------------------------ the model
def test_a_box_reads_and_writes_as_the_runtime_takes_it():
    assert SL.parse_box("3 5 34 40") == [3.0, 5.0, 34.0, 40.0]
    assert SL.parse_box("3% 5%,34 40") == [3.0, 5.0, 34.0, 40.0]
    assert SL.parse_box("-2 5 34 40") == [-2.0, 5.0, 34.0, 40.0]
    for bad in ("", "1 2 3", "1 2 0 4", "a b c d", "1 2 3 4 5"):
        assert SL.parse_box(bad) is None, bad
    assert SL.box_text([3.0, 5.126, 34.0, 40.333]) == "3 5.13 34 40.33"
    assert SL.box_text([-0.001, 0, 100, 100]) == "0 0 100 100"
    assert SL.clamp_box([1, 2, 0.1, 900]) == [1.0, 2.0, 0.5, 400.0]


def test_a_progress_line_takes_a_box_of_its_own_and_gives_it_back():
    v = "cl_mode a.png a_off.png\nMikeTeaveeMode b.png"
    v2 = SL.progress_with_box(v, 1, [18, 2, 15, 15.5])
    assert v2 == "cl_mode a.png a_off.png\nMikeTeaveeMode b.png 18 2 15 15.5"
    assert [p["box"] for p in SL.progress_lines(v2)] == [None, [18.0, 2.0, 15.0, 15.5]]
    v3 = SL.progress_with_box(v2, 0, [2, 2, 15, 15])
    assert SL.progress_lines(v3)[0] == {"mode": "cl_mode", "lit": "a.png", "unlit": "a_off.png", "box": [2.0, 2.0, 15.0, 15.0]}
    assert SL.progress_with_box(v3, 1, None) == "cl_mode a.png a_off.png 2 2 15 15\nMikeTeaveeMode b.png"
    with pytest.raises(ValueError):
        SL.progress_with_box(v, 5, [1, 1, 1, 1])


def test_the_default_places_are_where_the_runtime_draws():
    """The editor's default boxes are the runtime's own numbers: a change to draw_screen /
    draw_menu that is not made here too shows up as this test failing."""
    src = _src()
    screen = _body(src, "static void panel_box(", "/* PAD-1512: the game type menu")
    for n in ("H * 0.70f", "H * 0.03f", "H * 0.36f", "W * 0.16f", "W * 0.84f", "H * 0.27f",
              "{ 0.02f, 0.12f, 0.07f }", "x1 - W * 0.05f", "gx_text(rgba[i], x, y0 + H * by[i], 4, 1"):
        assert n in screen, n
    menu = _body(src, "static void draw_menu(", "static void draw_progress(")
    for n in ("H * 0.24f + n * rowh", "rowh = H * 0.075f", "x0 = W * 0.22f, x1 = W * 0.78f", "(x1 - x0) * 0.054f",
              "y0 + H * 0.055f * s, 5,", "H * 0.13f * s", "H * 0.012f * s", "H * 0.022f * s",
              "y1 - H * 0.065f * s, 2.5f", "rh * 0.867f", "rh * 0.555f", "y0 + H * 0.006f * s"):
        assert n in menu, n
    assert SL.PANEL_PLACES == {"middle": [16, 36, 68, 27], "bottom": [16, 70, 68, 27], "top": [16, 3, 68, 27]}
    t = SL.text_defaults(SL.PANEL_PLACES["middle"])
    # the title's built-in text: its top 0.02 of the screen into a panel 0.27 of it, 32 px of 768 tall
    assert t["title_at"] == [0.0, round(2 / 27 * 100, 2), 100.0, round(32 / 768 / 0.27 * 100, 2)]
    assert t["value_at"][1] == round(12 / 27 * 100, 2)
    cx = t["timer_at"][0] + t["timer_at"][2] / 2      # the timer centred 5 % of the screen in from the right
    assert abs(cx - (0.68 - 0.05) / 0.68 * 100) < 0.02
    d = SL.menu_defaults(3)
    assert d["game_type_at"] == [22.0, round((1 - 0.465) / 2 * 100, 2), 56.0, 46.5]
    assert d["game_type_lines_at"][1] == round(0.118 / 0.465 * 100, 2)
    assert d["game_type_lines_at"][3] == round(3 * 0.075 / 0.465 * 100, 2)
    # its bars scale with a box of its own, as draw_menu's s does
    m = SL.game_menu({"game_type_at": "4 10 40 70"}, ["A", "B"])
    menu = {e["key"]: e for e in m["elements"]}["game_type_at"]
    assert menu["bar_h"] == round(0.6 * 0.70 / (0.24 + 3 * 0.075), 3)


def test_the_mode_screen_inherits_the_titles_places_and_moves_text_with_its_panel():
    title = {"panel_at": "10 10 50 30", "title_at": "0 0 100 20", "title_color": "ff0000"}
    s = SL.mode_screen({"title": "Golden", "value_at": "5 50 40 20", "panel": "bottom"}, title, scope="mode",
                       defaults=CM.DEFAULTS)
    els = {e["key"]: e for e in s["elements"]}
    assert els["panel_at"]["box"] == [10.0, 10.0, 50.0, 30.0] and els["panel_at"]["where"] == "title"
    assert els["title_at"]["where"] == "title" and els["title_at"]["parent"] == "panel_at"
    assert els["title_at"]["text"] == "Golden" and els["title_at"]["color"] == "#ff0000ff"
    assert els["value_at"]["set"] and els["value_at"]["where"] == "own"
    assert not els["timer_at"]["set"] and els["timer_at"]["box"] == SL.text_defaults([10, 10, 50, 30])["timer_at"]
    assert "picture_at" not in els                       # no picture of its own: nothing to place
    off = SL.mode_screen({"panel": "none"}, {}, scope="mode")
    assert all(e["off"] for e in off["elements"] if e["key"] in ("panel_at", "title_at"))


def test_the_menu_lists_its_lines_as_the_game_does():
    m = SL.game_menu({"game_type_normal": "REGULAR", "game_type_hint": "none"}, ["WIZARD GAME", "PRACTICE"],
                     defaults=CM.DEFAULTS)
    els = {e["key"]: e for e in m["elements"]}
    assert els["game_type_lines_at"]["rows"] == ["REGULAR", "WIZARD GAME", "PRACTICE"]
    assert els["game_type_lines_at"]["box"] == SL.menu_defaults(3)["game_type_lines_at"]
    assert "game_type_hint_at" not in els                 # "none" hides it, as in the runtime
    assert els["game_type_title_at"]["text"] == "GAME TYPE"


# ------------------------------------------------------------------ the checker and the runtime
def test_the_checker_takes_the_place_keys_and_a_panes_own_box():
    mk = CM.mk()
    for k in ("panel_at", "title_at", "value_at", "timer_at"):
        assert mk.KEYS[k] == "box"
    for k in ("game_type_title_at", "game_type_lines_at", "game_type_hint_at"):
        assert mk.TITLE_KEYS[k] == "box"
    assert mk.check_value("progress", "cl_mode a.png b.png 2 2 15 15") is None
    assert mk.check_value("progress", "cl_mode a.png 2 2 15 15") is None
    assert "box" in mk.check_value("progress", "cl_mode a.png b.png 2 2 0 15")
    assert mk.check_value("progress", "cl_mode a.png b.png c.png") is not None
    assert mk.check_value("box", "3 5 34 40") is None


def test_the_runtime_draws_every_place_key():
    src = _src()
    kv = _body(src, "static void apply_kv(", "static int load_file(")
    for k, field in (("panel_at", "m->has_panel_at"), ("title_at", "m->has_txt_at[0]"), ("value_at", "m->has_txt_at[1]"),
                     ("timer_at", "m->has_txt_at[2]"), ("game_type_title_at", "gtl.has_t"),
                     ("game_type_lines_at", "gtl.has_l"), ("game_type_hint_at", "gtl.has_h")):
        assert re.search(r'!strcmp\(k, "%s"\)\) %s = parse_box' % (k, re.escape(field)), kv), k
    assert "m->prog[i].has_at ? m->prog[i].at : m->prog_at" in src
    assert "if (m->panel == 3) { gx_end(); return; }" in src     # none hides the panel, a box or not


# ------------------------------------------------------------------ the Modes tab
def test_a_dragged_box_is_written_and_comes_back(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        lay = j["layout"]
        assert lay["size"] == [1360, 768]
        assert {e["key"] for e in lay["mode"]["elements"]} >= {"panel_at", "title_at", "value_at", "timer_at"}
        assert lay["menu"]["scope"] == "title" and lay["title_mode"]["scope"] == "title"
        w.call("modes.jjp_place", "mode", "panel_at", [3, 5.123, 34, 40])
        j = _jjp(w)
        assert j["form"]["panel_at"] == "3 5.12 34 40"
        el = {e["key"]: e for e in j["layout"]["mode"]["elements"]}["panel_at"]
        assert el["set"] and el["box"] == [3.0, 5.12, 34.0, 40.0]
        assert j["check"]["ok"], j["check"]
        w.call("modes.jjp_place", "mode", "panel_at", None)          # Default place
        assert not _jjp(w)["form"].get("panel_at")
        w.call("modes.jjp_place", "title", "game_type_title_at", [0, 82, 100, 12])
        assert _jjp(w)["title_cfg"]["game_type_title_at"] == "0 82 100 12"
        with pytest.raises(Exception):
            w.call("modes.jjp_place", "mode", "points", [1, 2, 3, 4])


def test_a_panel_place_takes_the_panels_own_box_away(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        _open_wonka(w)
        w.call("modes.jjp_place", "mode", "panel_at", [3, 5, 34, 40])
        w.call("modes.jjp_panel_word", "mode", "top")
        j = _jjp(w)
        assert j["form"].get("panel") == "top" and not j["form"].get("panel_at")
        el = {e["key"]: e for e in j["layout"]["mode"]["elements"]}["panel_at"]
        assert el["box"] == SL.PANEL_PLACES["top"] and el["word"] == "top"


def test_a_wizards_panes_and_the_backdrops(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        folder = j["folder"]
        for fn in ("a.png", "b.png", "clip.webm"):
            open(os.path.join(folder, fn), "wb").close()
        os.makedirs(os.path.join(folder, SL.FRAMES_DIR), exist_ok=True)
        open(os.path.join(folder, SL.FRAMES_DIR, "attract.png"), "wb").close()
        w.call("modes.jjp_set", "start_all", "CandyLaneMode DotsMode")
        w.call("modes.jjp_set", "progress", "CandyLaneMode a.png\nDotsMode b.png")
        lay = _jjp(w)["layout"]
        keys = [e["key"] for e in lay["progress"]["elements"]]
        assert keys == ["progress_at", "progress#0", "progress#1"]
        w.call("modes.jjp_place", "mode", "progress#1", [18, 2, 15, 15])
        j = _jjp(w)
        assert j["form"]["progress"] == "CandyLaneMode a.png\nDotsMode b.png 18 2 15 15"
        assert j["check"]["ok"], j["check"]
        labels = [b["label"] for b in j["layout"]["backdrops"]]
        assert labels[0] == "The game's screen: attract" and {"a.png", "clip.webm"} <= set(labels)


# ------------------------------------------------------------------ the game's own screen
def _census(folder, label="game", parts=None):
    import json
    d = os.path.join(folder, SL.FRAMES_DIR)
    os.makedirs(d, exist_ok=True)
    parts = parts if parts is not None else [
        {"name": "sp_brat_charlie", "kind": "picture", "box": [136, 76.8, 272, 153.6], "draws": 1, "text": ""},
        {"name": "font_balls_in_play", "kind": "font", "box": [680, 600, 100, 40], "draws": 2, "text": "BALL 1"},
        {"name": "bitmap 64x64", "kind": "unnamed", "box": [10, 10, 64, 64], "draws": 1, "text": ""},
        {"name": "deff_backdrop", "kind": "picture", "box": [0, 0, 1360, 768], "draws": 1, "text": ""}]
    with open(os.path.join(d, label + ".json"), "w") as f:
        json.dump({"label": label, "size": [1360, 768], "picture": True, "parts": parts}, f)
    open(os.path.join(d, label + ".png"), "wb").close()


def test_a_census_lays_out_the_games_parts(tmp_path):
    _census(str(tmp_path))
    g = SL.game_screen(str(tmp_path), {"screen_move": "sp_brat_charlie 5 -2 1.5", "screen_hide": "font_balls_in_play"})
    els = {e["name"]: e for e in g["elements"]}
    assert g["label"] == "game" and g["censuses"] == ["game"]
    assert "deff_backdrop" not in els                    # the whole screen: its backdrop, not a part to drag
    assert els["bitmap 64x64"]["fixed"] and not els["sp_brat_charlie"]["fixed"]
    c = els["sp_brat_charlie"]
    assert c["orig"] == [10.0, 10.0, 20.0, 20.0] and c["set"]
    assert c["box"] == [5.0 + 5, -2.0 + 5, 30.0, 30.0]     # its centre moved 5, -2; one and a half times its size
    assert els["font_balls_in_play"]["hidden"] and els["font_balls_in_play"]["label"] == 'font_balls_in_play "BALL 1"'


def test_a_dragged_part_becomes_its_move_and_back():
    census = {"size": [1360, 768], "parts": [{"name": "sp_a", "box": [136, 76.8, 272, 153.6]}]}
    assert SL.move_for(census, "sp_a", [15, 12, 20, 20]) == (5.0, 2.0, 1.0, 20.0, 20.0)
    move = SL.move_for(census, "sp_a", [15, 12, 30, 30])
    assert move == (10.0, 7.0, 1.5, 20.0, 20.0)          # scaled about its centre (20 %, 20 %)
    t = SL.with_screen_line({"screen_move": "sp_b 1 1"}, "sp_a", move=move)
    assert t["screen_move"] == "sp_b 1 1\nsp_a 10 7 1.5 20 20" and t["screen_hide"] == ""
    assert SL.screen_lines(t)["sp_a"]["anchor"] == [20.0, 20.0]
    # not scaled: no centre to scale about
    assert SL.with_screen_line({}, "sp_a", move=(5.0, 2.0, 1.0, 20.0, 20.0))["screen_move"] == "sp_a 5 2"
    assert SL.with_screen_line(t, "sp_a", move=(0, 0, 1), hide=False)["screen_move"] == "sp_b 1 1"
    assert SL.with_screen_line(t, "sp_a", hide=True)["screen_hide"] == "sp_a"
    with pytest.raises(ValueError):
        SL.with_screen_line({}, "bitmap 64x64", hide=True)
    with pytest.raises(ValueError):
        SL.move_for(census, "sp_z", [1, 1, 1, 1])


def test_the_checker_takes_screen_lines():
    import json
    mk = CM.mk()
    port = json.load(open(os.path.join(RIG, "modes", "ports", "Wonka-v03.03.json")))
    assert mk.check_value("screen_move", "sp_brat_charlie 5 -3", port) is None
    assert mk.check_value("screen_move", "font_balls_in_play 1 2 1.5", port) is None
    assert mk.check_value("screen_move", "atlas_playerup 1 2 1.15 54.67 84.9", port) is None
    assert mk.check_value("screen_move", "atlas_playerup 1 2 1.15 54.67", port) is not None
    assert "fonts" in mk.check_value("screen_move", "font_nope 1 2", port)
    assert "off the screen" in mk.check_value("screen_move", "sp_x 120 0", port)
    assert "scale" in mk.check_value("screen_move", "sp_x 1 1 20", port)
    assert mk.check_value("screen_hide", "sp_x", port) is None
    assert mk.check_value("screen_hide", "sp_x 1", port) is not None


def test_screen_lines_in_title_cfg_are_counted_as_the_runtime_takes_them(tmp_path):
    d = tmp_path / "m"
    d.mkdir()
    (d / "1.mode").write_text("name = A\nstart = switch_target_tv\n")
    (d / "title.cfg").write_text("".join("screen_move = sp_x%d 1 1\n" % i for i in range(65)))
    _modes, problems = CM.mk().check_modes(str(d))
    assert any("more than 64 screen_move" in p for p in problems)
    (d / "title.cfg").write_text("screen_move = sp_a 1 1\nscreen_hide = sp_b\nscreen_move = sp_c 2 2\n")
    _modes, problems = CM.mk().check_modes(str(d))
    assert not problems, problems
    vals = CM.read_cfg(str(d / "title.cfg"))
    assert vals["screen_move"] == "sp_a 1 1\nsp_c 2 2"


def test_the_runtime_sees_the_games_draws_and_leaves_its_own_alone():
    src = _src()
    for fn in ("al_draw_bitmap", "al_draw_tinted_bitmap", "al_draw_bitmap_region", "al_draw_tinted_bitmap_region",
               "al_draw_scaled_bitmap", "al_draw_tinted_scaled_bitmap", "al_draw_rotated_bitmap",
               "al_draw_tinted_rotated_bitmap", "al_draw_scaled_rotated_bitmap", "al_draw_tinted_scaled_rotated_bitmap",
               "al_draw_tinted_scaled_rotated_bitmap_region", "al_draw_text", "al_draw_ustr", "al_draw_justified_text"):
        body = _body(src, "\nvoid %s(" % fn, "\n}\n")
        assert 'gs_real("%s")' % fn in body and "gs_draw(" in body, fn
    assert "gs_ours = 1;" in _body(src, "static int gx_begin(", "static void gx_end(")
    assert "gs_ours = 0;" in _body(src, "static void gx_end(", "\n")
    kv = _body(src, "static void apply_kv(", "static int load_file(")
    assert 'strcmp(k, "screen_move")) gs_parse' in kv and 'strcmp(k, "screen_hide")) gs_parse' in kv
    assert re.search(r"#define GS_MOVES (\d+)", src).group(1) == str(CM.mk().MAX_SCREEN_LINES)


def test_the_tab_lays_out_the_games_own_screen(tmp_path, preview_on):
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        assert j["layout"]["game"]["elements"] == []         # no census yet: the editor says how to take one
        _census(j["folder"])
        select_card(w, "Wonka-v03.03")
        g = _jjp(w)["layout"]["game"]
        key = next(e["key"] for e in g["elements"] if e["name"] == "sp_brat_charlie")
        w.call("modes.jjp_place", "title", key, [15, 12, 30, 30])
        j = _jjp(w)
        assert j["title_cfg"]["screen_move"] == "sp_brat_charlie 10 7 1.5 20 20"
        assert j["check"]["ok"], j["check"]
        w.call("modes.jjp_screen_part", "font_balls_in_play", "hide")
        assert _jjp(w)["title_cfg"]["screen_hide"] == "font_balls_in_play"
        w.call("modes.jjp_screen_part", "sp_brat_charlie", "back")
        assert not _jjp(w)["title_cfg"].get("screen_move")


def test_show_it_in_the_game_opens_the_menu_and_starts_the_mode(tmp_path, preview_on, monkeypatch):
    from pinball_decryptor.webui import modes_jjp
    # never the real stock ISO on this PC: the button must not start a game from a test
    monkeypatch.setattr(modes_jjp.JjpModesMixin, "_jjp_build_state", lambda self: {"iso": "", "out": ""})
    monkeypatch.setattr(modes_jjp.JjpModesMixin, "jjp_screens_argv", lambda self, iso, rt: pytest.fail("a game was started"))
    with web_app(tmp_path, mfr="jjp") as w:
        j = _open_wonka(w)
        label, fn = j["label"], j["open"]
        to = lambda p: "/L" + p.replace("\\", "/")
        argv = CM.screens_args(r"D:\Wonka-v03.03.iso", r"C:\rt.so", label, to)
        assert argv[0] == "tools/jjp_emu/jjpscreens.sh" and "--menu" not in argv and "--start" not in argv
        assert argv[argv.index("--out") + 1].endswith("/" + SL.FRAMES_DIR)
        w.call("modes.jjp_set", "game_type", "PAD GAME")
        w.call("modes.jjp_set", "start", "switch_target_tv switch_spinner")
        w.call("modes.jjp_set", "start_count", "3")
        argv = CM.screens_args(r"D:\Wonka-v03.03.iso", r"C:\rt.so", label, to, fn)
        assert "--menu" in argv and argv[argv.index("--start") + 1] == "switch_target_tv 3"
        sh = open(os.path.join(RIG, "jjpscreens.sh"), encoding="utf-8").read()
        assert "PAD_HIDDEN=1 PAD_AUDIO=0" in sh                # hidden and muted, always
        for step in ("census attract", "census game", "in_game_menu.png", "in_game_mode.png"):
            assert step in sh, step
        # no ISO under Build: the button says what it waits for
        with pytest.raises(Exception):
            w.call("modes.jjp_show_in_game")
