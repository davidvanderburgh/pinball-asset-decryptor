"""PAD-454 (DragonRR): "In the comparison section you have two buttons - Original and With
Color Profiles which is excellent. This same method needs to be applied to the main
screen on both the original video and the replacement (if there is one)."

Each of the Video tab's two players gets its own switch: the clip as it is (Original /
Replacement), or drawn through its color profile (its own, else the project's individual
files one), attached or not.  Only that player changes; the palette still does the
attaching.  The Replacement player opens on what the clip is set to, and follows the
palette when it moves; another clip puts both back."""

import os
import time

import pytest

from pinball_decryptor.core import colour_profile as cp
from tests.test_webui_video import _mine, _project, _scan
from tests.webui_harness import web_app

A, B, C = "video/attract.mp4", "video/intro.mp4", "video/sub/boss.mp4"
WARM = cp.Profile(name="Warm", gain=(1.2, 1.0, 0.85), saturation=1.2)
FILES = cp.Profile(name="Files", gamma=(1.2, 1.1, 1.0))

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js", "tabs", "video.js")


def _wait_for(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        st = w.state("video")
        if pred(st):
            return st
        time.sleep(0.05)
    raise AssertionError("timed out: look %r" % (w.state("video").get("look"),))


def _views(w):
    w.drain()
    v = w.state("video")["look"]["views"]
    return {k: (x and x["view"]) for k, x in v.items()}


def _looks(w, d, rel):
    own = w.run(w.window.service("video")._own_colours)
    return {on: (cp.video_look(d, on, own, rel=rel), cp.video_look_exact(d, on, own, rel=rel))
            for on in (True, False)}


def test_a_replaced_clip_shows_each_player_both_ways(tmp_path):
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        cp.store_asset_profile(d, FILES)
        cp.store_own_profile(d, "videos", A, WARM)
        w.answers.append(str(_mine(tmp_path)))
        assert w.call("video.choose", A) is True
        assert w.call("video.set_color", A, True)
        assert w.call("video.select", A)
        w.drain()
        views = w.state("video")["look"]["views"]
        assert views["orig"] == {"plain": "Original", "view": "plain", "name": "Warm",
                                 "on": True, "stock": False}
        assert views["rep"] == {"plain": "Replacement", "view": "profile", "name": "Warm",
                                "on": True, "stock": False}
        look = _looks(w, d, A)
        on_steps, on_exact = look[True]
        off_steps, off_exact = look[False]
        # as it opens: what the tab drew before (the Original as it is, the
        # Replacement with the profile attached to it)
        st = _wait_for(w, lambda s: s["look"]["lut"]["rep"] == cp.look_lut_path(on_exact["rep"]))
        assert st["look"]["orig"] == on_steps["orig"] and st["look"]["rep"] == on_steps["rep"]
        assert st["look"]["rep"][0] == cp.filter_step(WARM)

        # the Original player through the clip's profile
        assert w.call("video.set_pane_view", "orig", "profile")
        st = _wait_for(w, lambda s: s["look"]["lut"]["orig"] == cp.look_lut_path(on_exact["rep"]))
        assert st["look"]["orig"] == on_steps["rep"]
        assert st["look"]["orig"][0] == cp.filter_step(WARM)
        # the Replacement player without it: as if detached
        assert w.call("video.set_pane_view", "rep", "plain")
        st = _wait_for(w, lambda s: s["look"]["lut"]["rep"] == cp.look_lut_path(off_exact["rep"]))
        assert st["look"]["rep"] == off_steps["rep"]
        assert cp.filter_step(WARM) not in st["look"]["rep"]
        assert _views(w) == {"orig": "profile", "rep": "plain"}
        # nothing was attached or detached by it
        row = next(r for r in w.state("video")["rows"] if r["rel"] == A)
        assert row["col"] is True

        # the palette moved: the Replacement player follows it, the Original stays
        assert w.call("video.set_color", A, False)
        assert _views(w) == {"orig": "profile", "rep": "plain"}
        assert w.state("video")["look"]["views"]["rep"]["on"] is False
        assert w.call("video.set_color", A, True)
        assert _views(w) == {"orig": "profile", "rep": "profile"}

        # another clip puts both back; so does coming back to this one
        assert w.call("video.select", B)
        assert _views(w) == {"orig": "plain", "rep": None}
        assert w.state("video")["look"]["views"]["orig"]["name"] == "Files"
        assert w.call("video.select", A)
        assert _views(w) == {"orig": "plain", "rep": "profile"}


def test_a_games_own_clip_turns_between_original_and_its_profile(tmp_path):
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        cp.store_own_profile(d, "videos", C, WARM)
        assert w.call("video.select", C)
        # locked: the Original player can still show it (preview only); no
        # Replacement player to switch
        views = w.state("video")["look"]["views"]
        assert views["orig"]["view"] == "plain" and views["orig"]["on"] is False
        assert views["rep"] is None
        assert w.call("video.set_color_stock", True)
        assert w.call("video.set_color", C, True)
        w.drain()
        rep = w.state("video")["look"]["views"]["rep"]
        assert rep == {"plain": "Original", "view": "profile", "name": "Warm", "on": True,
                       "stock": True}
        on_steps, on_exact = _looks(w, d, C)[True]
        st = _wait_for(w, lambda s: s["look"]["lut"]["rep"] == cp.look_lut_path(on_exact["rep"]))
        assert st["look"]["rep"] == on_steps["rep"]
        # turned to Original: the same as the Original player
        assert w.call("video.set_pane_view", "rep", "plain")
        st = _wait_for(w, lambda s: s["look"]["lut"]["rep"] == s["look"]["lut"]["orig"])
        assert st["look"]["rep"] == st["look"]["orig"] == on_steps["orig"]


def test_no_switch_without_a_profile_to_show(tmp_path):
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        w.answers.append(str(_mine(tmp_path)))
        assert w.call("video.choose", A) is True
        assert w.call("video.select", A)
        # nothing set: the Recommended individual files profile is what attaching gives
        assert _views(w) == {"orig": "plain", "rep": "plain"}
        assert w.state("video")["look"]["views"]["rep"]["name"] == cp.RECOMMENDED
        # set to change nothing: nothing to show
        cp.store_asset_profile(d, cp.Profile(name="No change"))
        assert w.call("video.set_look_part", "files", True)
        assert _views(w) == {"orig": None, "rep": None}
        assert not w.call("video.set_pane_view", "both", "profile")
        assert not w.call("video.set_pane_view", "orig", "sepia")


@pytest.mark.parametrize("needle", [
    'call("video.set_pane_view", side, v)',
    "<${PaneView} side=${side} view=${(look.views || {})[side]} look=${look} />",
    'const PROFILE_WORDS = "With its color profile";',
])
def test_the_page_wires_it(needle):
    with open(_JS, encoding="utf-8") as f:
        assert needle in f.read()
