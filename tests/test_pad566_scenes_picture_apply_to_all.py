"""PAD-566 (DragonRR): "You have removed the ability to apply changes to other files?"  The
Colors bar on the Images tab has Apply to all profiled images / Apply to all images, and the
bar on a line of text in Scenes has them for lines of text, but the bar on a PICTURE in Scenes
had neither: its This file box stopped at "Same as the other files".  Now a picture in Scenes
has the Images tab's two buttons, giving the picture's profile (No change too, the card's own
colors back) to the other pictures.
"""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp

pytest.importorskip("PIL.Image")

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")


def test_a_scenes_picture_gives_no_change_to_all_images(tmp_path):
    from tests.test_webui_images import _project as _images, _set_folder, _wait, _settled, BANNER
    from tests.webui_harness import web_app
    assets, _reps = _images(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        assert w.call("images.set_color_unlocked", True)
        assert w.call("color.panel_open")
        # as scenes.js sends a picture layer: attached through the Scenes layer
        assert w.call("color.set_file", "images", BANNER, "unnamed_instance_25", False,
                      {"ns": "scenes", "node": 7})
        w.drain()
        assert w.call("color.preset", "none")
        w.drain()
        svc = w.window.service("images")
        every = w.run(lambda: svc.color_targets("all"))
        assert BANNER in every and len(every) > 1
        w.answers = ["yes"]
        assert w.call("color.apply_to_all", "all") is True
        names = cp.own_profile_names(assets)["images"]
        assert set(names) == set(every) and set(names.values()) == {"No change"}
        assert w.run(lambda: svc.color_targets("profiled")) == dict.fromkeys(every, True)
        assert w.call("color.undo")
        assert set(cp.own_profile_names(assets)["images"]) <= {BANNER}


def test_the_scenes_bar_offers_apply_to_all_on_a_picture():
    with open(os.path.join(_TABS, "color_pane.js"), encoding="utf-8") as f:
        pane = f.read()
    assert 'scenes: ["text", "images"]' in pane
    assert "(ALL_HOSTS[host] || []).includes(f.kind)" in pane
    assert '"on the Images tab"' in pane
