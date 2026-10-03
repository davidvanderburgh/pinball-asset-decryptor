"""PAD-341: the Machine screen starts from DragonRR's tuned profile (ranges and
curves included), and Save a copy names its file after the mode on show."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp

np = pytest.importorskip("numpy")

REC = dict(cp.SCREEN_PRESETS)["screen_recommended"]


def test_the_recommended_screen_is_the_tuned_profile():
    prof, problems = cp.parse(cp.SCREEN_DEFAULT_TEXT)
    assert problems == [] and prof == REC
    assert REC.name == "Recommended screen"
    assert REC.ranges == ((195.0, 60.0, 30.0, 10.0, 0.87, 1.33, 0.15),
                          (30.0, 40.0, 20.0, 0.0, 0.9, 1.0, 0.05))
    assert [ch for ch, _ in REC.curves] == ["rgb", "r", "g", "b"]
    assert dict(REC.curves)["rgb"][3] == (128.0, 180.0)
    # it round-trips through Save a copy / Load
    assert cp.parse(cp.to_text(REC))[0] == REC


def test_a_new_project_previews_through_it(tmp_path):
    d = str(tmp_path)
    shown, stored = cp.screen_shown(d)
    assert shown == REC and stored is False
    rgb = np.full((1, 1, 3), 128, np.uint8)
    assert tuple(cp.machine_view(d)(rgb)[0, 0]) == tuple(REC.apply_array(rgb)[0, 0])
    # never in a build: the screen is the preview's alone
    assert cp.for_project(d) is None


def test_save_a_copy_names_the_file_after_the_mode(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    names = []
    with web_app(tmp_path, mfr="stern") as w:
        w.window.ask_save = lambda *a, **k: names.append(k["initialfile"]) or ""
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        for mode in ("screen", "assets", "display"):
            assert w.call("color.set_mode", mode) == mode
            w.drain()
            assert w.call("color.save_copy") is False
        assert names == ["Machine Color Profile.txt", "File Color Profile.txt",
                         "Overlay Profile.txt"]
        # and the file it writes is the Recommended screen, extras and all
        w.call("color.set_mode", "screen")
        w.drain()
        out = str(tmp_path / "Machine Color Profile.txt")
        w.window.ask_save = lambda *a, **k: out
        assert w.call("color.save_copy") is True
        assert os.path.isfile(out) and cp.read_file(out)[0] == REC
