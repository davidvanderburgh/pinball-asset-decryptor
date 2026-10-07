"""PAD-440 (DragonRR): Compare on the Video tab.  Up to four clips side by side, big,
beside the Color profiles bar; each player draws through its own clip's colour steps
(core/colour_profile.py video_look), so a profile picked or a slider moved for the clip
clicked shows on it against the others as it is made."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from tests.test_webui_video import _mine, _project, _scan, _wait
from tests.webui_harness import web_app

A, B, C = "video/attract.mp4", "video/intro.mp4", "video/sub/boss.mp4"
RED = cp.Profile(name="Custom red", gain=(1.3, 0.9, 0.9))
BLUE = cp.Profile(name="Cool", gain=(0.8, 0.95, 1.2), saturation=0.8)

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js", "tabs", "video.js")


def _cmp(w):
    w.drain()
    return w.state("video")["compare"]


def _tiles(w):
    return [(t["rel"], t["side"]) for t in _cmp(w)["tiles"]]


def _pick(w, rel, path):
    w.answers.append(str(path))
    assert w.call("video.choose", rel) is True


def test_one_clip_opens_its_original_beside_its_replacement(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="pb") as w:
        _scan(w, proj)
        assert _cmp(w) == {"open": False, "max": 4, "tiles": []}
        _pick(w, A, mine)
        assert w.call("video.compare_open", [A]) == 2
        c = _cmp(w)
        assert c["open"] is True
        assert _tiles(w) == [(A, "orig"), (A, "rep")]
        orig, rep = c["tiles"]
        assert orig["sides"] == [["orig", "Original"], ["rep", "Replacement"]]
        assert os.path.normcase(orig["pane"]["path"]) == os.path.normcase(str(proj / A))
        assert rep["pane"]["path"] == str(mine)
        assert orig["look"] == [] and rep["look"] == []      # no colour profiles off Spike 2
        # one player turned to the other side; a side the clip has not got is refused
        assert w.call("video.compare_side", orig["id"], "rep") is True
        assert _tiles(w) == [(A, "rep"), (A, "rep")]
        assert w.call("video.compare_side", orig["id"], "nope") is False
        # x takes one out, never the last
        assert w.call("video.compare_remove", rep["id"]) is True
        assert w.call("video.compare_remove", orig["id"]) is False
        assert _tiles(w) == [(A, "rep")]
        # a proxy asked for a player that moved on is refused
        assert w.call("video.compare_make_proxy", orig["id"], -1, "mp4") is False
        assert w.call("video.compare_close") is True
        assert _cmp(w) == {"open": False, "max": 4, "tiles": []}
        assert w.call("video.compare_close") is False


def test_several_clips_each_show_their_replacement_else_the_original(tmp_path):
    names = ("video/a.mp4", "video/b.mp4", "video/c.mp4", "video/d.mp4", "video/e.mp4")
    proj = _project(tmp_path, names=names)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="pb") as w:
        _scan(w, proj)
        _pick(w, "video/b.mp4", mine)
        assert w.call("video.compare_open", ["nope", "video/c.mp4", "video/b.mp4",
                                             "video/c.mp4"]) == 2
        assert _tiles(w) == [("video/c.mp4", "orig"), ("video/b.mp4", "rep")]
        assert _cmp(w)["tiles"][0]["sides"] == [["orig", "Original"]]
        # four at a time: the first four selected
        assert w.call("video.compare_open", list(reversed(names))) == 4
        assert [r for r, _s in _tiles(w)] == list(reversed(names))[:4]
        assert w.call("video.compare_open", ["nope"]) == 0
        assert w.call("video.compare_open", []) == 0


def test_a_cleared_replacement_and_a_new_folder_follow(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="pb") as w:
        _scan(w, proj)
        _pick(w, A, mine)
        _pick(w, B, mine)
        assert w.call("video.compare_open", [A, B]) == 2
        assert w.call("video.clear", [A]) == 1
        c = _cmp(w)
        assert _tiles(w) == [(A, "orig"), (B, "rep")]
        assert c["tiles"][0]["sides"] == [["orig", "Original"]]
        assert os.path.normcase(c["tiles"][0]["pane"]["path"]) == os.path.normcase(str(proj / A))
        # another project folder: Compare closes with the old list
        other = _project(tmp_path / "other")
        _scan(w, other)
        _wait(w, lambda st: not st["compare"]["open"])


def test_each_player_draws_through_its_own_clips_colors(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        for rel in (A, B):
            _pick(w, rel, mine)
            assert w.call("video.set_color", rel, True)
        cp.store_asset_profile(d, RED)                   # the project's files profile
        cp.store_own_profile(d, "videos", B, BLUE)       # B has its own
        video = w.window.service("video")
        own = w.run(video._own_colours)

        def want(rel, side, switch=True):
            return cp.video_look(d, switch, own, rel=rel)[side]

        assert w.call("video.compare_open", [A, B, C]) == 3
        t = _cmp(w)["tiles"]
        assert [x["look"] for x in t] == [want(A, "rep"), want(B, "rep"),
                                          want(C, "orig", None)]
        assert t[0]["look"][0] == cp.filter_step(RED)
        assert t[1]["look"][0] == cp.filter_step(BLUE)
        assert t[0]["look"] != t[1]["look"]
        # the Colors bar on the clip clicked: a slider moved there redraws that player only
        assert w.call("color.panel_open")
        assert w.call("color.set_file", "videos", A, "attract.mp4", True, {"ns": "video"})
        w.call("color.set_params", {"name": "Warm", "gain": [1.2, 1.0, 0.8]})
        t = _cmp(w)["tiles"]
        assert cp.own_profile(d, "videos", A).name == "Warm"
        assert t[0]["look"] == want(A, "rep")
        assert t[0]["look"][0] == cp.filter_step(cp.own_profile(d, "videos", A))
        assert t[1]["look"][0] == cp.filter_step(BLUE)
        # its switch off: the profile leaves the player
        assert w.call("video.set_color", A, False)
        assert _cmp(w)["tiles"][0]["look"] == want(A, "rep", False)
        # the Preview colors switches reach every player
        assert w.call("video.set_look_part", "files", False)
        assert all(cp.filter_step(BLUE) not in x["look"] for x in _cmp(w)["tiles"])
        assert w.call("video.set_machine_look", False)
        assert [x["look"] for x in _cmp(w)["tiles"]] == [[], [], []]


def test_a_games_own_clip_with_its_profile_attached(tmp_path):
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        cp.store_asset_profile(d, RED)
        assert w.call("video.compare_open", [C]) == 1
        assert _tiles(w) == [(C, "orig")]
        # Advanced, then its switch: the card gets the original through its profile
        assert w.call("video.set_color_stock", True)
        assert w.call("video.set_color", C, True)
        t = _cmp(w)["tiles"][0]
        assert t["sides"] == [["orig", "Original"], ["rep", "With its color profile"]]
        assert w.call("video.compare_side", t["id"], "rep")
        t = _cmp(w)["tiles"][0]
        assert t["pane"]["title"] == "With its color profile"
        assert os.path.normcase(t["pane"]["path"]) == os.path.normcase(str(proj / C))
        assert t["look"][0] == cp.filter_step(RED)
        # switched off again: back to the original
        assert w.call("video.set_color", C, False)
        assert _tiles(w) == [(C, "orig")]


@pytest.mark.parametrize("needle", [
    'call("video.compare_open", rels)',
    'call("video.compare_make_proxy", t.id, pane.seq, proxyFormat())',
    "muted=${!active}",                       # only the clip clicked is heard
    "filter: url(#${fid})",                   # each player its own colour steps
    "byRel.get(activeTile.rel)",              # the Colors bar follows the clip clicked
    'cls="vid-cmp-open"',
])
def test_the_page_wires_compare(needle):
    with open(_JS, encoding="utf-8") as f:
        assert needle in f.read()
