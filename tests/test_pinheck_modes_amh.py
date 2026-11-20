"""Custom modes on Domino's and Rob Zombie (PAD-1423): their hook tables, the AMH text path,
the per-title port report, and - where the games' own update zips are on this machine - the
modes build and the runtime running inside each game in tools/pinheck_emu.

The games' PRGs are Spooky's and never ship with PAD, so the real-file tests skip without them
(``PAD_SPOOKY_IMAGES``, default D:/Pinball/images/Spooky).
"""
import importlib.util
import os
import struct
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PH_DIR = os.path.join(ROOT, "tools", "spooky_emu", "modes", "pinheck")
MODES = os.path.join(ROOT, "tools", "spooky_emu", "modes")
IMAGES = os.environ.get("PAD_SPOOKY_IMAGES", "D:/Pinball/images/Spooky")
ZIPS = {"DOM_V006": "DOM_v6.zip", "RZO_V026": "rzupdate_V26.zip"}
LABELS = {"DOM_V006": "dominos-V006", "RZO_V026": "rob_zombie-V026"}


def _load(name):
    spec = importlib.util.spec_from_file_location("t1423_" + name, os.path.join(PH_DIR, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load("hooks")
P = _load("pinheck")


def _stock(stem):
    z = os.path.join(IMAGES, ZIPS[stem])
    if not os.path.isfile(z):
        pytest.skip("%s is not on this machine" % z)
    with zipfile.ZipFile(z) as f:
        names = [n for n in f.namelist() if n.upper().endswith(".PRG")]
        assert [os.path.basename(n).upper() for n in names] == [stem + ".PRG"], names
        return f.read(names[0])


def _read_mode(path):
    d = {"file": os.path.basename(path)}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def _examples(stem):
    d = os.path.join(MODES, "examples", LABELS[stem])
    return [_read_mode(os.path.join(d, fn)) for fn in sorted(os.listdir(d)) if fn.endswith(".mode")]


def _port(stem):
    import json
    with open(os.path.join(MODES, "ports", LABELS[stem] + ".json")) as f:
        return json.load(f)


# ------------------------------------------------------------------ the tables, no game files
@pytest.mark.parametrize("stem", sorted(ZIPS))
def test_amh_entries_have_every_link_key(stem):
    t = H.HOOKS[stem]
    for k in H.LINK_KEYS:
        assert k in t, k
        if t[k] is None:
            # only AMH's text has nothing to show or hide
            assert (k, t["text_abi"]) == ("text_show", "amh")
    assert t["video_abi"] == t["text_abi"] == "amh"
    assert t["free_flash"] % 0x10000 == 0 and t["free_flash"] >= H.FLASH + t["size"]
    assert H.FLASH + t["size"] <= t["free_flash"] < H.FLASH + H.FLASH_SIZE
    # every function the runtime calls and the tick site are signed
    for k in ("tick_site", "tick_target", "add_score", "play_sfx", "text_str", "link_send",
              "coil_fire", "video"):
        assert t[k] in t["sigs"], k
    assert t["sigs"][t["tick_site"]] == "%08x" % struct.unpack("<I", struct.pack(">I", H.jal(t["tick_target"])))[0]


def test_amh_tilt_flag_sits_beside_its_warnings():
    # each game keeps the tilt flag in the byte just before the warning count (Jetsons:
    # 0x73C/0x73D); Rob Zombie's 0xA0000318 is a blink phase, not the tilt
    for stem in ("JET_V004", "DOM_V006", "RZO_V026"):
        t = H.HOOKS[stem]
        assert t["tilt_warnings"] == t["tilt"] + 1, stem
    assert H.HOOKS["RZO_V026"]["tilt"] == 0xA00002F4


def test_dominos_globals_are_jetsons_moved_up():
    j, d = H.HOOKS["JET_V004"], H.HOOKS["DOM_V006"]
    for k in ("player", "ball", "ball_active", "phase", "tilt", "tilt_warnings", "players"):
        assert d[k] - j[k] == 0xE4, k


def test_title_length_is_the_builds_panel():
    assert P.title_max("JET_V004") == 16
    assert P.title_max("DOM_V006") == P.title_max("RZO_V026") == 13
    assert P.title_problem("HOT DELIVERY XL", "DOM_V006")       # 15 > 13
    assert P.title_problem("HOT DELIVERY XL", "JET_V004") is None
    assert P.title_problem("HOT DELIVERY XL") is None            # no build: Jetsons' 16


@pytest.mark.parametrize("stem", sorted(ZIPS))
def test_examples_fit_and_pack(stem):
    port = _port(stem)
    assert port["engine"] == "pinheck" and port["prg"] == stem
    assert port["points_round"] == 10 and "multiple of 10" in port["points_note"]
    assert port["dmd"] == [128, 32]
    modes = _examples(stem)
    assert len(modes) == 2
    for m in modes:
        assert P.title_problem(m["title"], stem) is None, m["file"]
        packed = P.pack_mode(m, port)
        assert len(packed) == P.MODE_SIZE
        assert packed[:16].rstrip(b"\0").decode() == m["title"]
    for s in ("sound_start", "sound_shot", "sound_complete", "sound_end"):
        for m in modes:
            if m.get(s):
                assert m[s] in port["sounds"], (m["file"], s)


@pytest.mark.parametrize("stem", sorted(ZIPS))
def test_prebuilt_runtime_is_linked_for_the_build(stem):
    rt, head = P.runtime(stem)
    t = H.HOOKS[stem]
    assert t["free_flash"] < head["entry"] < head["data"]
    # the AMH build has no text-layer call: text_show is not linked
    m = open(P.runtime_path(stem)[:-4] + ".map").read()
    assert "GAME_text_show" not in m
    assert "GAME_text_str" in m and ("0x%08x" % t["text_str"]) in m.lower()


def test_build_passes_the_amh_flag_and_skips_missing_keys():
    sh = open(os.path.join(PH_DIR, "build.sh")).read()
    assert '"-DTEXT_ABI_AMH"' in sh and "t[k] is not None" in sh
    c = open(os.path.join(PH_DIR, "padheck.c")).read()
    assert "GAME_add_score(points, 0)" in c
    assert "#ifdef TEXT_ABI_AMH" in c


# ------------------------------------------------------------------ the real games
@pytest.mark.parametrize("stem", sorted(ZIPS))
def test_stock_prg_is_the_build_the_table_was_read_from(stem):
    prg = _stock(stem)
    t = H.check(prg, stem)
    assert H.identify(prg) == stem
    assert H.word(prg, t["tick_site"]) == H.jal(t["tick_target"])
    bad = bytearray(prg)
    bad[t["add_score"] - H.FLASH] ^= 0xFF
    with pytest.raises(H.Refused):
        H.check(bytes(bad), stem)


@pytest.mark.parametrize("stem", sorted(ZIPS))
def test_modes_build_round_trips_to_stock(stem):
    prg = _stock(stem)
    out = P.build_prg(prg, _examples(stem), _port(stem))
    t = H.HOOKS[stem]
    assert P.is_modes_build(out)
    assert H.word(out, t["tick_site"]) != H.jal(t["tick_target"])
    assert out[:t["size"]] != prg
    assert P.stock_of(out) == prg


@pytest.fixture
def _quiet_unicorn():
    import faulthandler
    was = faulthandler.is_enabled()
    faulthandler.disable()
    yield
    if was:
        faulthandler.enable()


@pytest.mark.parametrize("stem", sorted(ZIPS))
def test_mode_runs_inside_the_game(stem, tmp_path, _quiet_unicorn):
    """The runtime in the emulator: two start hits start the mode, a shot scores through the
    game's own AddScore, and the panel's title goes to the DMD on AMH's text line 0."""
    pytest.importorskip("unicorn")
    prg = P.build_prg(_stock(stem), _examples(stem), _port(stem))
    card = tmp_path / "card"            # no pictures or sounds needed: the packets are logged
    card.mkdir()
    prove = _load("prove")
    nv = tmp_path / "nv"
    # first boot of a blank EEPROM asks for a restart (README): boot once, then play
    prove.run(prg, str(card), 10, [], nvram=str(nv), name=stem + ".PRG")
    r = prove.run(prg, str(card), 29.5,
                  [(26.0, "sw20"), (27.0, "sw43"), (28.5, "sw21")], nvram=str(nv), name=stem + ".PRG")
    log = [w for _, w in r["log"]]
    assert any("STARTED" in w for w in log), log
    shot = [w for w in log if "points scored" in w]
    assert shot and shot[0].strip().endswith("100000"), log
    texts = [w for _, w in r["packets"] if w.startswith("text line 0")]
    title = _examples(stem)[0]["title"]
    assert any(title in w for w in texts), texts
    assert r["score"] >= 100000
