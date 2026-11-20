"""PAD-1420: Spooky modes on the P-ROC titles (Rick and Morty): the runtime's mode logic (a
stand-in game), the check's round-up-to-100, config.yaml's runtime line, the .pkg build (an AES
ZIP: members copied as they are), Write's ZIP and the app's title lookups."""
import importlib.util
import os
import shutil
import types
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = os.path.join(ROOT, "tools", "spooky_emu", "modes")
LABEL = "rick_and_morty-2022.09.02"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mk():
    return _load("pad_mkspkmodes_t1420", os.path.join(MODES, "mkspkmodes.py"))


@pytest.fixture(scope="module")
def port(mk):
    return mk.load_port(LABEL)


def _modes(tmp_path, **mode):
    d = tmp_path / "modes"
    d.mkdir(exist_ok=True)
    (d / "title.cfg").write_text("game = rick_and_morty\n")
    body = {"name": "Rush", "start": "leftInlane", "shots": "slingRight", "points": "250000"}
    body.update(mode)
    (d / "1_rush.mode").write_text("".join("%s = %s\n" % kv for kv in body.items()))
    return str(d)


# ============================================================================ port and check
def test_port_is_the_proc_runtime(mk, port):
    assert mk.engine(port) == "proc" and mk.load_of(port) == "pinproc_class"
    assert port["points_round"] == 100 and port["points_round_up"] and port["points_scale"] == 1
    assert port["update_container"] == "aes_zip" and port["aes_key"] == "rm_pkg"
    assert "slingRight" in port["switches"] and "mb_start_1" in port["sounds"]
    assert port["switch_labels"]["coin1"] == "Left Coin Slot"
    rt = mk.runtime_files(port)
    assert rt[0].endswith(os.path.join("proc", "padmodes_proc.py"))


def test_starter_modes_check_clean(mk, port):
    modes, problems = mk.check_modes(os.path.join(MODES, "examples", LABEL), port)
    assert problems == [] and [m["name"] for m in modes] == ["Portal Rush", "Spinner Frenzy"]


def test_points_round_up_to_100(mk, port, tmp_path):
    _m, problems = mk.check_modes(_modes(tmp_path, points="250050"), port)
    assert any("rounds every award up to 100, so it would score 250,100" in p for p in problems)


def test_unknown_switch_and_sound_refused(mk, port, tmp_path):
    _m, problems = mk.check_modes(_modes(tmp_path, start="noSuchSwitch", sound_start="nope"), port)
    assert any("noSuchSwitch" in p for p in problems) and any("nope" in p for p in problems)


def test_config_yaml_line(mk, port):
    text = "font_path:\n#pinproc_class: procgame.fakepinproc.FakePinPROC # real P-ROC\ndmd_framerate: 24"
    new, n = mk.patch_config_yaml(text)
    assert n == 1 and new.count("pinproc_class: pad.padmodes_proc.PinPROC") == 1
    assert "#pinproc_class: procgame.fakepinproc" in new           # a comment stays
    again, _ = mk.patch_config_yaml(new)                            # a modes build built again
    assert again.count("\npinproc_class:") == 1
    # only the game folder's own config.yaml
    assert mk.patch_file("config/config.yaml", b"x: 1\n", port) == (b"x: 1\n", 0)
    assert mk.patch_file("config.yaml", b"x: 1\n", port)[1] == 1


def test_pad_files_are_a_package(mk, port, tmp_path):
    rels = [f[0] for f in mk.pad_files(_modes(tmp_path), port)]
    assert rels[:2] == ["__init__.py", "padmodes_proc.py"] and "modes/1_rush.mode" in rels
    assert "modes/title.cfg" in rels and mk.top_files(port) == []


# ============================================================================ the .pkg build
def _stock_pkg(path, extra=()):
    from pinball_decryptor.plugins.spooky import crypto
    z = str(path) + ".zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("RMGame.pyc", b"\x03\xf3game")
        zf.writestr("config.yaml", "dmd_framerate: 24\n#pinproc_class: procgame.fakepinproc.FakePinPROC\n")
        zf.writestr("config/RM_PROTOTYPE1.yaml", "PRSwitches: {}\n")
        zi = zipfile.ZipInfo("assets/sound/big.wav")
        zi.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(zi, b"RIFF" + bytes(range(256)) * 400)
        zf.writestr("assets/stored.bin", os.urandom(5000))
        for name, data in extra:
            zf.writestr(name, data)
    crypto.encrypt_aes_pkg(z, str(path), crypto.AES_KEYS["rm_pkg"])
    os.remove(z)
    return str(path)


def _decrypt(path, tmp_path):
    from pinball_decryptor.plugins.spooky import crypto
    out = str(tmp_path / "out.zip")
    crypto.decrypt_aes_pkg(path, out, crypto.AES_KEYS["rm_pkg"])
    return zipfile.ZipFile(out)


def test_build_pkg(mk, port, tmp_path):
    stock = _stock_pkg(tmp_path / "rm-gamecode-20220902.pkg", extra=[("pad/old.txt", b"old")])
    out = str(tmp_path / "PAD modes" / "rm-gamecode-20220902.pkg")
    os.makedirs(os.path.dirname(out))
    lines = []
    mk.build(stock, _modes(tmp_path), out, port, log=lines.append)
    with _decrypt(out, tmp_path) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert "pad/old.txt" not in names
        for n in ("pad/__init__.py", "pad/padmodes_proc.py", "pad/modes/1_rush.mode", "pad/modes/title.cfg"):
            assert n in names
        assert z.read("config.yaml").decode().rstrip().endswith("pinproc_class: pad.padmodes_proc.PinPROC")
        assert z.read("assets/sound/big.wav") == b"RIFF" + bytes(range(256)) * 400
        assert z.getinfo("assets/sound/big.wav").compress_type == zipfile.ZIP_DEFLATED   # copied as it was
        assert "points_scale = 1" in z.read("pad/modes/title.cfg").decode()
    assert any("added pad/" in l for l in lines)


def test_build_refuses_other_games(mk, port, tmp_path):
    from pinball_decryptor.plugins.spooky import crypto
    z = str(tmp_path / "x.zip")
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ACGame.py", b"")
        zf.writestr("config.yaml", b"")
    pkg = str(tmp_path / "rm-gamecode-20220902.pkg")
    crypto.encrypt_aes_pkg(z, pkg, crypto.AES_KEYS["rm_pkg"])
    with pytest.raises(mk.Refused, match="RMGame.pyc"):
        mk.build(pkg, _modes(tmp_path), str(tmp_path / "out.pkg"), port, log=lambda *_: None)


# ============================================================================ the app
@pytest.fixture
def sm(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SPOOKY_MODES_DIR", str(tmp_path / "spooky_modes"))
    from pinball_decryptor.plugins.spooky import custom_modes
    return custom_modes


def test_version_and_title(sm, tmp_path):
    assert sm.version_of("rm-gamecode-20220902.pkg") == "2022.09.02"
    assert sm.version_of("v2025.12.01.09.scooby") == "2025.12.01.09"
    t = next(t for t in sm.titles() if t["label"] == LABEL)
    assert t["can_run"] and t["name"] == "Rick and Morty 2022.09.02"
    assert "config.yaml" in sm.loads_how(LABEL)
    assert "first start after the update" in sm.install_note(LABEL)


def test_label_for_card(sm, tmp_path):
    p = _stock_pkg(tmp_path / "rm-gamecode-20220902.pkg")
    assert sm.label_for_card(p) == LABEL
    lib = tmp_path / "lib"
    lib.mkdir()
    shutil.copy(p, lib / "rm-gamecode-20220902.pkg")
    (lib / "ac-gamecode.pkg").write_bytes(b"x")
    assert sm.find_stock(LABEL, [str(lib)]).endswith("rm-gamecode-20220902.pkg")


def test_extract_label_from_source_name(sm, tmp_path):
    meta = {"game": "Rick and Morty", "format": "rm_pkg", "source": "rm-gamecode-20220902.pkg"}
    assert sm.label_for_extract(str(tmp_path), meta) == LABEL
    assert sm.label_for_extract(str(tmp_path), dict(meta, source="rm-gamecode-20990101.pkg")) == ""


def test_write_zip_carries_the_modes(sm, tmp_path):
    folder = tmp_path / "extract"
    (folder / "config").mkdir(parents=True)
    (folder / "RMGame.pyc").write_bytes(b"g")
    (folder / "config.yaml").write_text("dmd_framerate: 24\n")
    (folder / "config" / "asset_list.yaml").write_text("Audio: {}\n")
    (folder / "pad").mkdir()
    (folder / "pad" / "stale.txt").write_text("from an old build")
    sm.title_dir(LABEL)                                    # seeded from the starter modes
    pm = sm.write_pad_modes(LABEL, str(folder))
    assert pm and pm[2] == "pad" and pm[3] == []
    from pinball_decryptor.plugins.spooky.formats import create_zip
    out = str(tmp_path / "w.zip")
    create_zip(str(folder), out, pad_modes=pm)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "pad/stale.txt" not in names and "pad/padmodes_proc.py" in names
        assert "pad/modes/1_portal_rush.mode" in names and "RMGame.pyc" in names
        assert z.read("config.yaml").decode().count("pinproc_class: pad.padmodes_proc.PinPROC") == 1
        assert "pinproc_class" not in z.read("config/asset_list.yaml").decode()


def test_pipeline_packs_modes_for_rm_pkg():
    src = open(os.path.join(ROOT, "pinball_decryptor", "plugins", "spooky", "pipeline.py"), encoding="utf-8").read()
    assert '"rm_pkg", "ac_pkg"' in src and "pad_modes=self.pad_modes)" in src.split("def _build_aes_pkg")[1][:900]


# ============================================================================ the runtime (stand-in game)
class _Sw:
    def __init__(self, name, number):
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


class _Game:
    def __init__(self):
        self.switches = [_Sw(n, i) for i, n in enumerate(["leftInlane", "rightInlane", "slingRight", "spinner"])]
        self.player = _Player()
        self.game_tilted = False
        self.modes = []
        self.ball = 1
        self.played = []
        self.sound = types.SimpleNamespace(
            sounds={"mb_start_1": {"is_voice": True, "sound_list": []}, "zap": {"is_voice": False}},
            play_voice=lambda k: self.played.append(("voice", k)), play=lambda k: self.played.append(("sfx", k)))

    def current_player(self):
        return self.player

    def score(self, points):
        x = points if points % 100 == 0 else points + 100 - points % 100
        self.player.score += x
        return x


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_MODES_LOG", str(tmp_path / "padmodes.log"))
    pm = _load("pad_padmodes_proc_t1420", os.path.join(MODES, "proc", "padmodes_proc.py"))
    d = tmp_path / "m"
    d.mkdir()
    (d / "title.cfg").write_text("game = rick_and_morty\n")
    (d / "1_a.mode").write_text("name = A\nstart = leftInlane rightInlane\nstart_count = 2\nshots = slingRight\n"
                                "points = 250000\nseconds = 30\ncomplete = 3\ncomplete_points = 2000000\n"
                                "sound_start = mb_start_1\nsound_shot = zap\n")
    (d / "2_b.mode").write_text("name = B\nstart = 3\nshots = spinner\npoints = 50000\nseconds = 10\n")
    game = _Game()
    modes, title = pm.load_modes(game, str(d))
    monkeypatch.setattr(pm, "panel_layer", lambda g, m, secs: ("panel", m["title"], m["total"], secs))
    clock = [1000.0]
    monkeypatch.setattr(pm.time, "time", lambda: clock[0])
    r = pm._runtime_class(_Mode)(game, modes, title)
    r.evt_game_starting()
    r.evt_ball_starting()
    r.clock = clock
    r.log = (tmp_path / "padmodes.log")
    return r


def _hit(r, name):
    r.pad_switch(_Sw(name, 0))


def test_runtime_start_shots_complete(rt):
    g = rt.game
    assert sorted(h[0] for h in rt.handlers) == ["leftInlane", "rightInlane", "slingRight", "spinner"]
    assert all(h[1] == "active" for h in rt.handlers)
    a = rt.pad_modes[0]
    _hit(rt, "slingRight")                                    # not running: no score
    assert g.player.score == 0
    _hit(rt, "leftInlane")
    assert not a["running"]
    _hit(rt, "rightInlane")
    assert a["running"] and ("voice", "mb_start_1") in g.played
    assert rt.layer == ("panel", "A", 0, 30)
    for _ in range(3):
        _hit(rt, "slingRight")
    assert not a["running"] and a["total"] == 3 * 250000 + 2000000 == g.player.score
    assert g.played.count(("sfx", "zap")) == 3 and rt.layer is None
    assert "A: COMPLETED, bonus 2000000" in rt.log.read_text()


def test_runtime_time_ball_tilt_and_new_game(rt):
    b = rt.pad_modes[1]
    _hit(rt, "slingRight")                                    # B starts on switch number 3 = spinner
    _hit(rt, "spinner")
    assert b["running"] and rt.layer[1] == "B"
    rt.mode_tick()
    for _ in range(11):
        rt.clock[0] += 1.0
        rt.mode_tick()
    assert not b["running"] and "B: ended (time ran out)" in rt.log.read_text()
    _hit(rt, "spinner")
    rt.evt_ball_ending((False, False))
    assert not b["running"] and "ended (the ball ended)" in rt.log.read_text()
    _hit(rt, "spinner")                                       # no ball in play: nothing
    assert not b["running"]
    rt.evt_ball_starting()
    _hit(rt, "spinner")
    rt.evt_tilt(False)
    assert not b["running"] and "ended (tilt)" in rt.log.read_text()
    a = rt.pad_modes[0]
    rt.evt_ball_starting()
    _hit(rt, "leftInlane")
    rt.evt_game_starting()
    assert a["hits"] == 0
    rt.evt_ball_starting()
    rt.game.game_tilted = True
    _hit(rt, "leftInlane")
    assert a["hits"] == 0


def test_runtime_off_and_bad_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_MODES_LOG", str(tmp_path / "l.log"))
    pm = _load("pad_padmodes_proc_t1420b", os.path.join(MODES, "proc", "padmodes_proc.py"))
    d = tmp_path / "m"
    d.mkdir()
    (d / "1.mode").write_text("start = nope leftInlane\n")
    modes, _ = pm.load_modes(_Game(), str(d))
    assert modes[0]["start"] == ["leftInlane"] and "nope is not one of this game's switches" in (tmp_path / "l.log").read_text()
    (d / "off").write_text("")
    assert pm.load_modes(_Game(), str(d)) == ([], {})


def test_runtime_is_python2_syntax():
    """The machine runs Python 2.7: no f-strings, no keyword-only arguments, no print()."""
    src = open(os.path.join(MODES, "proc", "padmodes_proc.py"), encoding="utf-8").read()
    import re
    assert not re.search(r"\bf\"|\bf'", src)
    assert "nonlocal" not in src and ":=" not in src and "print(" not in src
