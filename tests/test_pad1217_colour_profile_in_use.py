"""PAD-1217 (DragonRR): the Colors tab / bar must say which color profile is really in
use.  A newly brought in file has none attached, yet the Start from row lit Recommended
(the profile the file WOULD get), so it looked applied.  Now a starting point is lit only
when it applies (or was picked for the project's files), and the row says "In use: <name>"
or "None set" (``in_use``)."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp

pytest.importorskip("PIL.Image")
pytest.importorskip("numpy")

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")


def test_a_new_file_shows_no_profile_in_use_until_one_is_picked(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_images import _project, _set_folder, _wait, _settled, BANNER
    assets, reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
        assert w.call("images.choose", BANNER) == BANNER
        w.drain()
        w.call("images.select", BANNER)
        assert w.call("color.panel_open")
        # the project's individual files: never picked, on no file -> nothing in use
        assert w.call("color.set_mode", "assets")
        w.drain()
        s = w.state("color")
        assert s["file"] is None and s["active"] is False
        assert s["preset_on"] == "" and s["in_use"] == ""
        # the new picture, its switch off: Recommended waits there but is not lit
        assert w.call("color.set_file", "images", BANNER, "SpaceGodzilla.png", False,
                      {"ns": "images"})
        w.drain()
        s = w.state("color")
        assert s["name"] == "Recommended"
        assert s["preset_on"] == "" and s["in_use"] == ""
        # picking one attaches it: lit, and named as in use
        assert w.call("color.preset", "bw")
        w.drain()
        s = w.state("color")
        assert s["file"]["on"] is True
        assert s["preset_on"] == "bw" and s["in_use"] == "Black and white"
        # Recommended picked on the file: lit and in use (it follows the screen)
        assert w.call("color.preset", "recommended")
        w.drain()
        s = w.state("color")
        assert s["preset_on"] == "recommended" and s["in_use"] == "Recommended"
        # the project's files profile picked but on no file yet: lit (the pick shows),
        # yet not in use
        w.call("color.set_file")
        w.drain()
        assert w.call("color.preset", "bw")
        w.drain()
        s = w.state("color")
        assert cp.asset_stored(assets)
        assert s["preset_on"] == "bw"
        assert s["in_use"] == ("Black and white" if s["active"] else "")
        # the Machine screen always has one in use
        assert w.call("color.set_mode", "screen")
        w.drain()
        assert w.state("color")["in_use"]


def test_the_start_from_row_shows_in_use_or_none_set():
    src = open(os.path.join(_TABS, "color.js"), encoding="utf-8").read()
    assert "export function inUseChip(s)" in src
    row = src[src.index('<span class="lbl">Start from</span>'):]
    assert "${inUseChip(s)}" in row[:800]
    chip = src[src.index("export function inUseChip(s)"):]
    assert "In use: ${s.in_use}" in chip[:600] and "None set" in chip[:600]
