"""PAD-354 (DragonRR): Undo / Redo on the Color profiles (the Scenes bar and the tab).
Each profile keeps its own steps, one slider dragged is one step, and Undo puts back
exactly what the profile was stored as (No change, Recommended following the screen, or
numbers)."""

import json

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.webui.tabs import color as color_tab


def _open(w, proj):
    w.call("ui.set", "extract", "output", str(proj))
    w.call("ui.select_tab", "scenes")
    w.drain()
    w.call("color.panel_open")
    w.drain()


def test_one_drag_is_one_step_and_undo_puts_it_back(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, proj)
        assert w.call("color.set_mode", "assets") == "assets"
        w.drain()
        assert not w.state("color")["can_undo"]
        assert not cp.asset_stored(str(proj))           # Recommended, following the screen
        for g in (0.9, 0.8, 0.7):                        # one drag of Blue
            w.call("color.set_params", {"gamma": [1.0, 1.0, g]})
        w.drain()
        assert cp.asset_profile(str(proj)).gamma == (1.0, 1.0, 0.7)
        assert w.state("color")["can_undo"] and not w.state("color")["can_redo"]
        assert w.call("color.undo") is True
        w.drain()
        assert not cp.asset_stored(str(proj))            # back to Recommended itself
        s = w.state("color")
        assert not s["can_undo"] and s["can_redo"]
        assert w.call("color.undo", True) is True        # Redo
        w.drain()
        assert cp.asset_profile(str(proj)).gamma == (1.0, 1.0, 0.7)


def test_starting_points_are_steps_and_each_profile_keeps_its_own(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, proj)
        w.call("color.set_params", {"gamma": [1.2, 1.0, 1.0]})
        w.drain()
        w.call("color.preset", "none")                   # No change on the overlay
        w.drain()
        assert cp.for_project(str(proj)) is None
        # another slider is another step, even straight after
        assert w.call("color.set_mode", "screen") == "screen"
        w.drain()
        assert not w.state("color")["can_undo"]          # the screen has none of the overlay's
        w.call("color.set_params", {"gain": [1.0, 0.9, 1.0]})
        w.call("color.set_params", {"lift": 0.02})
        w.drain()
        assert w.call("color.undo") is True
        w.drain()
        assert cp.screen_profile(str(proj)).lift == (0.0, 0.0, 0.0)
        assert cp.screen_profile(str(proj)).gain == (1.0, 0.9, 1.0)
        assert w.call("color.set_mode", "display") == "display"
        w.drain()
        assert w.call("color.undo") is True              # No change undone
        w.drain()
        assert cp.for_project(str(proj)).gamma == (1.2, 1.0, 1.0)
        assert w.state("color")["gamma"] == [1.2, 1.0, 1.0]
        assert w.call("color.undo") is True
        w.drain()
        assert cp.for_project(str(proj)) is None
        assert w.call("color.undo") is False             # nothing left
        # a new change drops the Redo steps
        w.call("color.set_params", {"saturation": 0.5})
        w.drain()
        assert not w.state("color")["can_redo"]


def test_a_slider_moved_again_later_is_a_new_step(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    clock = [100.0]
    monkeypatch.setattr(color_tab.time, "monotonic", lambda: clock[0])
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, proj)
        w.call("color.set_params", {"brightness": 1.1})
        clock[0] += color_tab.UNDO_GROUP_S + 1
        w.call("color.set_params", {"brightness": 1.2})
        w.drain()
        assert w.call("color.undo") is True
        w.drain()
        data = staged_changes.load(str(proj))
        assert json.loads(json.dumps(data[cp.KEY]))["brightness"] == 1.1
