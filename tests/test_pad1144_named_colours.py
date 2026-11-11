"""PAD-1144: a one-colour lamp whose name says its colour glows in it.

Spike 3's Star Wars 2025 names its coloured GI strings "TOP GI-BLU (x10)", "BOTTOM GI-RED (x11)" and a few inserts
"R2D2-WHT"; Spike 2's TMNT writes "TOP GI-GRN(X5)". Every other one-colour insert (all of Pokemon's) has no colour
anywhere on the card and stays white. The emulator's window (tools/spike2_emu/cablights.py) and the Modes tab
(pinball_decryptor/plugins/stern/insert_colours.py) each keep the rule, because the rig cannot import the app; this
holds the two together.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools", "spike2_emu"))

import cablights  # noqa: E402
from pinball_decryptor.plugins.stern import insert_colours as IC  # noqa: E402

#: lamp names off the real tables (Spike 3 card stores, Spike 2 tables) and what they must read as
CASES = [
    ("TOP GI-BLU (x10)", "#306eff"),          # star_wars_2025_le / _pro
    ("BOTTOM GI-RED (x11)", "#ff2818"),
    ("TOP GI-WHT (x18)", "#ffffff"),
    ("R2D2-WHT", "#ffffff"),
    ("BICYCLE GIRL FLASH-RED", "#ff2818"),    # walking_dead_remastered_le
    ("TOP GI-GRN(X5)", "#28dc40"),            # turtles_pro
    ("SIDE-YELLOW", "#ffd600"),
    ("LANE - AMB", "#ffb000"),
    ("LEFT BALL SAVE", None),                 # pokemon_le: no colour in the name
    ("PIKACHU CHEEK L", None),
    ("BIG RED", None),                        # no dash: a name, not a colour
    ("REDEMPTION-R", None),                   # an RGB channel, not a colour word
    ("", None),
    (None, None),
]


@pytest.mark.parametrize("name, want", CASES)
def test_the_name_gives_the_colour_in_both_places(name, want):
    assert IC.named_colour(name) == want
    got = cablights.named_colour(name)
    assert ("#%02x%02x%02x" % got if got else None) == want


def test_both_tables_name_the_same_colours():
    assert set(IC.NAMED_COLOURS) == set(cablights.NAMED_COLOURS)
    for k, rgb in cablights.NAMED_COLOURS.items():
        assert IC.NAMED_COLOURS[k] == "#%02x%02x%02x" % rgb, k


def test_the_modes_preview_draws_the_name_colour_until_one_is_set():
    """The Modes tab's Light shows preview: each one-colour insert carries ``own`` (modes.blocks_playfield) and is
    drawn in it while the user's table has none for it."""
    root = os.path.dirname(HERE)
    js = open(os.path.join(root, "pinball_decryptor", "webui", "static", "js", "tabs", "modes_lightshows.js"),
              encoding="utf-8").read()
    assert "monoColour(c, (lens || {})[i.name] || i.own)" in js
    assert 'value=${lens[name] || own[name] || "#ffffff"}' in js
    py = open(os.path.join(root, "pinball_decryptor", "webui", "tabs", "modes.py"), encoding="utf-8").read()
    assert '"own": (IC.named_colour(i["name"]) or "") if i["mono"] else ""' in py
