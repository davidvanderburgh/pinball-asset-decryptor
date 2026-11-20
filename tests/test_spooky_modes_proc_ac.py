"""PAD-1421: Spooky modes on Alice Cooper's Nightmare Castle (the P-ROC runtime of PAD-1420): its
port report (round up to 10, the Unity-player screen, the dateless update), the check refusing the
Screen keys its screen cannot show, the build of its .pkg, the app's lookups and form, and the
runtime's panel as the game's own text on its Unity player (a stand-in game and client)."""
import importlib.util
import os
import types
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = os.path.join(ROOT, "tools", "spooky_emu", "modes")
LABEL = "alice_cooper-1.1.0.5"
RM = "rick_and_morty-2022.09.02"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mk():
    return _load("pad_mkspkmodes_t1421", os.path.join(MODES, "mkspkmodes.py"))


@pytest.fixture(scope="module")
def port(mk):
    return mk.load_port(LABEL)


def _modes(tmp_path, title="game = alice_cooper\n", **mode):
    d = tmp_path / "modes"
    d.mkdir(exist_ok=True)
    (d / "title.cfg").write_text(title)
    body = {"name": "Rush", "start": "inlaneLeft", "shots": "slingl", "points": "250000"}
    body.update(mode)
    (d / "1_rush.mode").write_text("".join("%s = %s\n" % kv for kv in body.items()))
    return str(d)


# ============================================================================ port and check
def test_port_is_alice_coopers(mk, port):
    assert port["engine"] == "proc" and port["game_class"] == "ACGame"
    assert port["aes_key"] == "ac_pkg" and port["marker"] == "ACGame.py"
    assert port["screen"] == "unity_player" and port["display"] == [684, 384]
    assert port["points_round"] == 10 and port["points_round_up"] and port["points_scale"] == 1
    assert "mainFunctions._score" in port["points_note"] and "Billion Dollar Babies" in port["points_note"]
    assert port["update_name"] == "ac-gamecode.pkg" and port["version_match"] == ["ac-gamecode.pkg"]
    assert port["fonts"] == [] and len(port["switches"]) == 125
    for n in ("inlaneLeft", "inlaneRight", "slingl", "slingr", "spinner", "target1"):
        assert n in port["switches"]
    for s in ("combo_1", "sling", "combosound", "target"):
        assert s in port["sounds"]
    assert mk.runtime_files(port)[0].endswith("padmodes_proc.py")


def test_starter_modes_check_clean(mk, port):
    modes, problems = mk.check_modes(os.path.join(MODES, "examples", LABEL), port)
    assert problems == [] and [m["name"] for m in modes] == ["Sling Rush", "Spinner Frenzy"]


def test_points_round_up_to_10(mk, port, tmp_path):
    _m, problems = mk.check_modes(_modes(tmp_path, points="1005"), port)
    assert any("rounds every award up to 10, so it would score 1,010" in p for p in problems)
    assert mk.check_modes(_modes(tmp_path, points="1010"), port)[1] == []


def test_screen_keys_refused_by_name(mk, port, tmp_path):
    d = _modes(tmp_path, title="game = alice_cooper\nfont_title = neo_128\n", panel_color="000000c0",
               title_color="ff2020")
    _m, problems = mk.check_modes(d, port)
    assert len(problems) == 2
    assert problems[0].startswith("title.cfg:2: font_title: Alice Cooper's Nightmare Castle's screen is its Unity player")
    assert problems[1].startswith("1_rush.mode:5: panel_color:") and "box colour" in problems[1]
    _m, problems = mk.check_modes(_modes(tmp_path, title_color="ff202080", value_color="ffdc00ff"), port)
    assert len(problems) == 1 and "title_color" in problems[0] and "cannot be see-through" in problems[0]
    rm = mk.load_port(RM)                                   # Rick and Morty draws its own panel: fonts are fine
    assert not any("Unity player" in p for p in mk.check_modes(
        _modes(tmp_path, title="game = rick_and_morty\nfont_title = neo_128\n", start="leftInlane",
               shots="slingRight", panel_color="000000c0"), rm)[1])


def test_make_port_records_the_dateless_stock(mk, tmp_path):
    stock = tmp_path / "ac-gamecode.pkg"
    stock.write_bytes(b"x" * 1234)
    raw = {"engine": "proc", "switches": ["a"], "points_scale_measured": {"asked": 1000, "scored": 1000,
                                                                            "multiplier": 1}}
    p = mk.make_port(raw, LABEL, "Alice Cooper's Nightmare Castle", ".pkg", stock=str(stock))
    assert (p["update_name"], p["update_size"], p["version_match"]) == ("ac-gamecode.pkg", 1234, ["ac-gamecode.pkg"])
    assert p["points_round"] == 10 and p["aes_key"] == "ac_pkg"
    assert mk.make_port(raw, RM, "Rick and Morty", ".pkg")["points_round"] == 100


# ============================================================================ the .pkg build
def _stock_pkg(path):
    from pinball_decryptor.plugins.spooky import crypto
    z = str(path) + ".zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ACGame.py", b"import mainFunctions as mf\n")
        zf.writestr("config.yaml", "dmd_dots_w: 684\n#pinproc_class: procgame.fakepinproc.FakePinPROC\n")
        zf.writestr("config/alice.yaml", "PRSwitches: {}\n")
    crypto.encrypt_aes_pkg(z, str(path), crypto.AES_KEYS["ac_pkg"])
    os.remove(z)
    return str(path)


def test_build_pkg(mk, port, tmp_path):
    from pinball_decryptor.plugins.spooky import crypto
    stock = _stock_pkg(tmp_path / "ac-gamecode.pkg")
    out = str(tmp_path / "PAD modes" / "ac-gamecode.pkg")
    os.makedirs(os.path.dirname(out))
    mk.build(stock, os.path.join(MODES, "examples", LABEL), out, port, log=lambda *_: None)
    dec = str(tmp_path / "out.zip")
    crypto.decrypt_aes_pkg(out, dec, crypto.AES_KEYS["ac_pkg"])
    with zipfile.ZipFile(dec) as z:
        names = z.namelist()
        for n in ("pad/__init__.py", "pad/padmodes_proc.py", "pad/modes/1_sling_rush.mode",
                  "pad/modes/2_spinner_frenzy.mode", "pad/modes/title.cfg", "ACGame.py"):
            assert n in names
        assert z.read("config.yaml").decode().rstrip().endswith("pinproc_class: pad.padmodes_proc.PinPROC")
        assert "unity_panel" in z.read("pad/padmodes_proc.py").decode()


# ============================================================================ the app
@pytest.fixture
def sm(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SPOOKY_MODES_DIR", str(tmp_path / "spooky_modes"))
    from pinball_decryptor.plugins.spooky import custom_modes
    return custom_modes


def test_title_and_card(sm, tmp_path, monkeypatch):
    t = next(t for t in sm.titles() if t["label"] == LABEL)
    assert t["can_run"] and t["name"].startswith("Alice Cooper")
    p = tmp_path / "ac-gamecode.pkg"
    p.write_bytes(b"x")
    monkeypatch.setattr(sm, "game_of", lambda path: "alice_cooper")
    assert sm.version_of(str(p)) == "" and sm.label_for_card(str(p)) == LABEL
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "ac-gamecode.pkg").write_bytes(b"x")              # not the stock size: not the stock update
    assert sm.find_stock(LABEL, [str(lib)]) == ""


def test_extract_label_from_source_name(sm, tmp_path):
    meta = {"game": sm.GAME_NAMES["alice_cooper"], "format": "ac_pkg", "source": "ac-gamecode.pkg"}
    assert sm.label_for_extract(str(tmp_path), meta) == LABEL


def test_write_zip_carries_the_modes(sm, tmp_path):
    folder = tmp_path / "extract"
    (folder / "config").mkdir(parents=True)
    (folder / "ACGame.py").write_text("import mainFunctions as mf\n")
    (folder / "config.yaml").write_text("dmd_dots_w: 684\n")
    sm.title_dir(LABEL)                                    # seeded from the starter modes
    pm = sm.write_pad_modes(LABEL, str(folder))
    assert pm and pm[2] == "pad"
    from pinball_decryptor.plugins.spooky.formats import create_zip
    out = str(tmp_path / "w.zip")
    create_zip(str(folder), out, pad_modes=pm)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "pad/padmodes_proc.py" in names and "pad/modes/1_sling_rush.mode" in names
        assert z.read("config.yaml").decode().count("pinproc_class: pad.padmodes_proc.PinPROC") == 1


def test_form_leaves_out_what_the_screen_cannot_show(sm):
    ac, rm = sm.load_port(LABEL), sm.load_port(RM)
    screen = dict(sm.form_groups(ac))["Screen"]
    assert screen == ("panel", "title_color", "value_color", "timer_color")
    assert sm.title_form(ac) == screen
    assert dict(sm.form_groups(rm))["Screen"] == dict(sm.FORM_GROUPS)["Screen"]
    assert sm.title_form(rm) == sm.TITLE_FORM and sm.title_form(None) == sm.TITLE_FORM


# ============================================================================ the runtime's Unity panel
class _Sw:
    def __init__(self, name, number=0):
        self.name, self.number = name, number


class _Player:
    score = 0


class _Mode(object):
    Game = 2

    def __init__(self, game, priority, mode_type=3):
        self.game, self.priority, self.mode_type = game, priority, mode_type
        self.handlers = []

    def add_switch_handler(self, name, event_type, delay, handler):
        self.handlers.append((name, event_type, handler))

    def mode_tick(self):
        return None


class _Unity:
    """Alice Cooper's tcpclient: what is on the player's screen, by text name."""

    def __init__(self):
        self.texts = {}

    def append_text(self, name, x, y, z, text, size, red=1.0, green=1.0, blue=1.0, justify="center",
                    layer="base_layer"):
        self.texts[name] = dict(x=x, y=y, z=z, text=text, size=size, rgb=(red, green, blue), justify=justify,
                                layer=layer)

    def remove_text(self, name):
        self.texts.pop(name, None)

    def remove_all_text(self):
        self.texts.clear()


class _ACGame:
    """ACGame as the runtime sees it: no display_width, a tcpclient, mf._score's rounding."""

    def __init__(self):
        self.switches = [_Sw(n, i) for i, n in enumerate(["inlaneLeft", "inlaneRight", "slingl", "spinner"])]
        self.player = _Player()
        self.game_tilted = False
        self.modes = []
        self.ball = 1
        self.tcpclient = _Unity()
        self.sound = types.SimpleNamespace(sounds={}, play_voice=lambda k: None, play=lambda k: None)

    def current_player(self):
        return self.player

    def score(self, points, **kw):                          # mf._score: rounds up to 10, returns None
        self.player.score += -(-points // 10) * 10


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_MODES_LOG", str(tmp_path / "padmodes.log"))
    pm = _load("pad_padmodes_proc_t1421", os.path.join(MODES, "proc", "padmodes_proc.py"))
    d = tmp_path / "m"
    d.mkdir()
    (d / "title.cfg").write_text("game = alice_cooper\n")
    (d / "1_a.mode").write_text("name = A\ntitle = SLING'S RUSH\nstart = inlaneLeft\nshots = slingl\n"
                                "points = 250005\nseconds = 30\ncomplete = 2\ntitle_color = ff2020\n")
    (d / "2_b.mode").write_text("name = B\nstart = inlaneRight\nshots = spinner\npoints = 50000\nseconds = 0\n"
                                "panel = bottom\n")
    game = _ACGame()
    modes, title = pm.load_modes(game, str(d))
    clock = [1000.0]
    monkeypatch.setattr(pm.time, "time", lambda: clock[0])
    r = pm._runtime_class(_Mode)(game, modes, title)
    r.evt_game_starting()
    r.evt_ball_starting()
    r.pm, r.clock, r.log = pm, clock, tmp_path / "padmodes.log"
    return r


def _tick(r, s):
    r.clock[0] += s
    r.mode_tick()


def test_unity_panel_rows_and_shadows(rt):
    on = rt.game.tcpclient.texts
    rt.pad_switch(_Sw("inlaneLeft"))
    assert set(on) == {"pad_title", "pad_title_b", "pad_value", "pad_value_b", "pad_timer", "pad_timer_b"}
    t, b = on["pad_title"], on["pad_title_b"]
    assert t["text"] == "SLINGS RUSH"                       # no quote may break the player's message
    assert t["rgb"] == (1.0, 32 / 255.0, 32 / 255.0) and b["rgb"] == (0, 0, 0)
    assert (t["x"], t["layer"], t["justify"]) == (342, "quick_layer", "center")
    assert (b["x"], b["y"], b["z"]) == (t["x"] + 3, t["y"] + 3, t["z"] + 1)
    assert on["pad_value"]["text"] == "0" and on["pad_timer"]["text"] == "30"
    rt.pad_switch(_Sw("slingl"))
    assert rt.game.player.score == 250010 and on["pad_value"]["text"] == "250,010"
    _tick(rt, 0.5)                                          # the first tick starts the clock
    _tick(rt, 0.6)
    assert on["pad_timer"]["text"] == "30"
    _tick(rt, 0.6)
    assert on["pad_timer"]["text"] == "29"
    assert "panel failed" not in rt.log.read_text()


def test_unity_panel_comes_back_after_the_game_clears_its_screen(rt):
    on = rt.game.tcpclient.texts
    rt.pad_switch(_Sw("inlaneRight"))                      # B: until the ball ends, bottom
    assert "pad_timer" not in on and on["pad_title"]["text"] == "B"
    y_bottom = on["pad_title"]["y"]
    rt.game.tcpclient.remove_all_text()                    # the game starts one of its modes
    _tick(rt, 0.4)
    assert on == {}                                         # sent again once a second, not every tick
    _tick(rt, 0.7)
    assert on["pad_title"]["text"] == "B" and on["pad_title"]["y"] == y_bottom
    rt.evt_ball_ending()
    assert on == {}                                         # the ball ended: the panel is gone


def test_unity_panel_goes_on_completion(rt):
    on = rt.game.tcpclient.texts
    rt.pad_switch(_Sw("inlaneLeft"))
    rt.pad_switch(_Sw("slingl"))
    rt.pad_switch(_Sw("slingl"))
    assert not rt.pad_modes[0]["running"] and on == {}
    assert rt.game.player.score == 2 * 250010


def test_port_report_names_the_unity_screen(rt):
    p = rt.pm.port_report(rt.game)
    assert p["screen"] == "unity_player" and p["display"] == [684, 384] and p["game_class"] == "_ACGame"
