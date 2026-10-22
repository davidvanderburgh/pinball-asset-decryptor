"""PAD-668: single-colour inserts, as the machine shows them.

A single-colour insert takes one level - the colour's brightest part (pad_mode_runtime.c lamp_write) - and glows in
its own LED's colour, which no file of the game names. The user gives each its colour once, in a table both the
emulator's playfield window (tools/spike2_emu/playfield.py) and the Modes tab's Light shows preview read
(plugins/stern/insert_colours.py), and a Real LEDs / All RGB switch in both picks between the machine's look and the
every-insert-RGB one. (The playfield window's half is tests/test_spike2_playfield_web.py.)
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
JS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "modes_lightshows.js")
PORTS = os.path.join(RIG, "modes", "sdk", "ports")

from pinball_decryptor.plugins.stern import insert_colours as IC  # noqa: E402
from pinball_decryptor.plugins.stern import playfield_art as PA  # noqa: E402


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert IC.state_path() == os.path.join(str(tmp_path), ".pad_playfield.json")
    return tmp_path


def test_the_table_and_the_switch_are_kept_per_game_beside_the_window_s_own_keys(home):
    (home / ".pad_playfield.json").write_text(json.dumps({"art_look": "drawing", "playfield_pos": [1, 2]}))
    assert IC.table("godzilla_le") == {} and IC.look() == "real"
    assert IC.set_colour("godzilla_le", "MASER", "#FF2000") == {"MASER": "#ff2000"}
    assert IC.set_colour("godzilla_le", "BRIDGE", "teal") == {"MASER": "#ff2000"}          # not a colour: white
    assert IC.table("godzilla_pro") == {}
    assert IC.set_look("rgb") == "rgb" and IC.look() == "rgb"
    assert IC.set_look("nonsense") == "real"
    st = json.loads((home / ".pad_playfield.json").read_text())
    assert st["art_look"] == "drawing" and st["playfield_pos"] == [1, 2]                  # the window's, untouched
    assert IC.set_colour("godzilla_le", "MASER", None) == {}


def test_the_app_and_the_playfield_window_share_one_table(home, monkeypatch):
    """A colour set in the Modes tab is the one the emulator's window draws, and the other way round."""
    sys.path.insert(0, RIG)
    import playfield
    monkeypatch.setattr(playfield, "STATE", IC.state_path())
    monkeypatch.setattr(playfield, "_LENS", None)
    IC.set_colour("godzilla_le", "MASER", "#00ff80")
    IC.set_look("rgb")
    assert playfield.lens_colours("godzilla_le") == {"MASER": (0, 255, 128)}
    assert playfield.insert_look() == "rgb"
    playfield.save_lens_colour("BRIDGE", "#0040ff", title="godzilla_le")
    assert IC.table("godzilla_le") == {"MASER": "#00ff80", "BRIDGE": "#0040ff"}


def test_the_port_says_which_inserts_are_single_colour():
    places = {p["name"]: p for p in PA.insert_places(os.path.join(PORTS, "godzilla_le-1.16.port"))}
    assert places["MASER"]["mono"] is True                       # one light id
    assert places["LEFT RAMP"]["mono"] is False                  # 346,347,348: RGB
    assert sum(p["mono"] for p in places.values()) > 40


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="no node")
def test_the_preview_shows_a_single_colour_insert_at_the_colour_s_brightest_part_in_its_own_colour(tmp_path):
    src = open(JS, encoding="utf-8").read()
    engine = src[src.index("const i32 ="):src.index("// A step as the C's table row holds it")]
    mono = src[src.index("export function monoColour"):]
    mono = mono[:mono.index("\n}\n") + 3]
    drv = "\n".join([engine.replace("export ", ""), mono.replace("export ", ""), "console.log([",
                     "  monoColour(0xff0000, null), monoColour(0xff0000, '#00ff80'), monoColour(0x400010, null),",
                     "  monoColour(0x000000, '#ff0000'), monoColour(0x20ff20, '#ff8000'),",
                     "].map((c) => c.toString(16).padStart(6, '0')).join(' '));", ""])
    (tmp_path / "m.mjs").write_text(drv, encoding="utf-8")
    out = subprocess.run([NODE, str(tmp_path / "m.mjs")], capture_output=True, text=True, check=True).stdout.split()
    assert out[0] == "ffffff"            # full red on an unset insert: white, full
    assert out[1] == "00ff80"            # ...on a green insert: green, not red
    assert out[2] == "404040"            # a dim colour: its brightest part (0x40) of white
    assert out[3] == "000000"            # dark is dark
    assert out[4] == "ff8000"            # full green on an orange insert: orange


def test_the_preview_has_the_switch_and_the_table():
    src = open(JS, encoding="utf-8").read()
    assert 'if (c && i.mono && look !== "rgb") c = monoColour(c, (lens || {})[i.name]);' in src
    assert 'call("modes.blocks_insert_look", k)' in src and 'call("modes.blocks_insert_colour", pf ? pf.game : "", name, colour)' in src
    assert '[["real", "Real LEDs"], ["rgb", "All RGB"]]' in src
    from pinball_decryptor.webui.tabs import modes
    assert hasattr(modes.ModesTab if hasattr(modes, "ModesTab") else object, "__name__")
    text = open(modes.__file__, encoding="utf-8").read()
    assert 'out["game"], out["lens"], out["look"] = game, IC.table(game), IC.look()' in text
    assert "def blocks_insert_colour(self, game, name, colour):" in text and "def blocks_insert_look(self, look):" in text


def test_an_open_playfield_window_picks_up_a_change_made_in_the_modes_tab(home, monkeypatch):
    sys.path.insert(0, RIG)
    import playfield
    monkeypatch.setattr(playfield, "STATE", IC.state_path())
    monkeypatch.setattr(playfield, "_LENS", None)
    monkeypatch.setattr(playfield, "_STATE_SEEN", [None, 0.0])
    IC.set_colour("godzilla_le", "MASER", "#00ff80")
    monkeypatch.setattr(playfield, "GAME", "godzilla_le")
    assert playfield.lens_of("MASER") == (0, 255, 128)
    playfield.state_changed(every=0)                               # the window has seen the file as it is
    assert playfield.state_changed(every=0) is False
    st = json.loads(open(IC.state_path()).read())
    st["lens_colours"]["godzilla_le"]["MASER"] = "#ff0000"
    with open(IC.state_path(), "w") as f:                          # the Modes tab writes it
        json.dump(st, f)
    os.utime(IC.state_path(), (1, 1))
    assert playfield.state_changed(every=0) is True
    assert playfield.lens_of("MASER") == (255, 0, 0)
