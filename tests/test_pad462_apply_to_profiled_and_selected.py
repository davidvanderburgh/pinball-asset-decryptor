"""PAD-462 (DragonRR): the Colors bar's Apply to all, and what a profile change shows.

1. "Apply To All PROFILED Videos": every video with a color profile attached gets the one on
   show; one without is left alone.
2. "Same as the other files" stays.
3. "Apply to ALL Videos": every video that is not locked gets it, attached (the game's own
   clips too while Advanced unlocks them).
4. Several videos selected and the profile changed: all of them that are not locked get it,
   each palette green.
5. A game's own clip with its profile is shown on its own (Original) player, turned to "With
   its color profile", not as a second copy on the Replacement player; a change to a clip's
   profile turns its player to "With its color profile"."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from tests.test_webui_video import _mine, _project, _scan
from tests.webui_harness import web_app

pytest.importorskip("PIL.Image")

A, B, C = "video/attract.mp4", "video/intro.mp4", "video/sub/boss.mp4"
RED = {"name": "Custom red", "gain": [1.3, 0.9, 0.9]}

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")


def _cols(w):
    w.drain()
    return {r["rel"]: r["col"] for r in w.state("video")["rows"]}


def _on(w, rel, more=()):
    """The bar on *rel* (and the clips selected with it), as video.js sends it."""
    assert w.call("color.panel_open")
    assert w.call("color.set_file", "videos", rel, os.path.basename(rel),
                  bool(_cols(w).get(rel)), {"ns": "video"}, list(more))
    w.drain()


def _replace(w, tmp_path, rels):
    for i, rel in enumerate(rels):
        w.answers.append(str(_mine(tmp_path, "mine%d.mp4" % i)))
        assert w.call("video.choose", rel) is True


def test_apply_to_all_profiled_videos_leaves_the_unattached_alone(tmp_path):
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _replace(w, tmp_path, [A, B, C])
        assert w.call("video.set_color", B, True)
        cp.store_own_profile(d, "videos", B, cp.Profile(name="Old", gain=(1, 1.2, 1)))
        _on(w, A)
        w.call("color.set_params", RED)          # A gets it, attached; C has none attached
        w.drain()
        assert _cols(w) == {A: True, B: True, C: False}
        w.answers.append("yes")
        assert w.call("color.apply_to_all", "profiled") is True
        q = w.asked[-1]
        assert q["title"] == "Apply to all profiled videos"
        assert "All 2 videos with a color profile attached" in q["message"]
        assert "without a color profile attached are left as they are" in q["message"]
        assert cp.own_profile_names(d)["videos"] == {A: "Custom red", B: "Custom red"}
        assert _cols(w) == {A: True, B: True, C: False}
        log = [l["text"] for l in w.run(w.window.log_history)]
        assert any("applied to all 2 profiled videos." in t for t in log)
        # the button with no scope is this one
        n = len(w.asked)
        assert w.call("color.apply_to_all") is False      # nothing left to change
        assert len(w.asked) == n
        assert w.call("color.undo")
        assert cp.own_profile_names(d)["videos"] == {A: "Custom red", B: "Old"}
        # 2. Same as the other files is still there
        assert w.state("color")["file"]["own"] is True
        assert w.call("color.file_shared")
        assert cp.own_profile_names(d)["videos"] == {B: "Old"}


def test_apply_to_all_profiled_with_no_other_attached_asks_nothing(tmp_path):
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _replace(w, tmp_path, [A, B])
        _on(w, A)
        w.call("color.set_params", RED)
        w.drain()
        n = len(w.asked)
        assert w.call("color.apply_to_all", "profiled") is False
        assert len(w.asked) == n


def test_apply_to_all_videos_reaches_the_games_own_clips_with_advanced(tmp_path):
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _replace(w, tmp_path, [A])
        _on(w, A)
        w.call("color.set_params", RED)
        w.drain()
        # locked: only the replaced clips are reached, and A is the only one
        n = len(w.asked)
        assert w.call("color.apply_to_all", "all") is False
        assert len(w.asked) == n
        assert _cols(w) == {A: True, B: None, C: None}
        # Advanced unlocks the game's own clips: they are reached and attached
        assert w.call("video.set_color_stock", True)
        assert _cols(w) == {A: True, B: False, C: False}
        _on(w, A)
        w.answers.append("yes")
        assert w.call("color.apply_to_all", "all") is True
        q = w.asked[-1]
        assert q["title"] == "Apply to all videos"
        assert "Every video that is not locked" in q["message"]
        assert "all 3 of them" in q["message"]
        assert "attached to the 2 that have none" in q["message"]
        assert cp.own_profile_names(d)["videos"] == {r: "Custom red" for r in (A, B, C)}
        assert _cols(w) == {A: True, B: True, C: True}
        assert staged_changes.load(d)["video_color_slots"] == {A: True, B: True, C: True}
        # one Undo: profiles and switches as they were; Redo: all again
        assert w.call("color.undo")
        assert cp.own_profile_names(d)["videos"] == {A: "Custom red"}
        assert _cols(w) == {A: True, B: False, C: False}
        assert w.call("color.undo", True)
        assert _cols(w) == {A: True, B: True, C: True}


def test_several_selected_clips_all_get_the_profile_attached(tmp_path):
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _replace(w, tmp_path, [A, B])
        assert w.call("video.set_color", A, True)
        assert w.call("video.set_color_stock", True)
        cp.store_own_profile(d, "videos", B, cp.Profile(name="Old", gain=(1, 1.2, 1)))
        assert _cols(w) == {A: True, B: False, C: False}
        _on(w, A, more=[B, C])
        f = w.state("color")["file"]
        assert f["rel"] == A and f["count"] == 3 and f["own_n"] == 1
        w.call("color.set_params", RED)
        w.drain()
        # every one of them has it, each palette green
        assert cp.own_profile_names(d)["videos"] == {r: "Custom red" for r in (A, B, C)}
        assert _cols(w) == {A: True, B: True, C: True}
        assert w.state("color")["file"]["own_n"] == 3
        # one slider dragged is one step for all of them
        w.call("color.set_params", {"gain": [1.4, 0.9, 0.9]})
        w.call("color.set_params", {"gain": [1.5, 0.9, 0.9]})
        w.drain()
        assert cp.own_profile(d, "videos", C).gain == (1.5, 0.9, 0.9)
        assert w.call("color.undo")
        w.drain()
        assert all(cp.own_profile(d, "videos", r).gain == (1.3, 0.9, 0.9) for r in (A, B, C))
        # and the next Undo puts the profiles AND the switches as they were
        assert w.call("color.undo")
        w.drain()
        assert cp.own_profile_names(d)["videos"] == {B: "Old"}
        assert _cols(w) == {A: True, B: False, C: False}
        assert w.call("color.undo", True)
        assert _cols(w) == {A: True, B: True, C: True}
        # Same as the other files: all of them drop their own
        assert w.call("color.file_shared")
        assert cp.own_profile_names(d)["videos"] == {}
        assert w.call("color.undo")
        assert set(cp.own_profile_names(d)["videos"]) == {A, B, C}
        # back to one clip: the bar is on it alone again
        _on(w, A)
        assert w.state("color")["file"]["count"] == 1


def test_a_games_own_clip_with_its_profile_is_on_its_original_player(tmp_path):
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        cp.store_own_profile(d, "videos", C, cp.Profile(name="Warm", gain=(1.2, 1, 0.85)))
        assert w.call("video.set_color_stock", True)
        assert w.call("video.select", C)
        assert w.call("video.set_color", C, True)
        w.drain()
        st = w.state("video")
        assert not st["preview"]["rep"].get("path")
        assert st["look"]["views"]["rep"] is None
        assert st["look"]["views"]["orig"]["view"] == "profile"
        # the user turns it off; a change in the bar turns it on again
        assert w.call("video.set_pane_view", "orig", "plain")
        w.drain()
        assert w.state("video")["look"]["views"]["orig"]["view"] == "plain"
        _on(w, C)
        w.call("color.set_params", RED)
        w.drain()
        assert w.state("video")["look"]["views"]["orig"]["view"] == "profile"
        # Compare still shows its two sides
        assert w.call("video.compare_open", [C]) == 2
        w.drain()
        tiles = w.state("video")["compare"]["tiles"]
        assert [t["pane"]["title"] for t in tiles] == ["Original", "With its color profile"]


def test_a_change_turns_a_replaced_clips_player_to_its_profile(tmp_path):
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _replace(w, tmp_path, [A, B])
        assert w.call("video.set_color", A, True)
        assert w.call("video.select", A)
        w.drain()
        views = w.state("video")["look"]["views"]
        assert views["rep"]["view"] == "profile" and views["orig"]["view"] == "plain"
        assert w.call("video.set_pane_view", "rep", "plain")
        w.drain()
        assert w.state("video")["look"]["views"]["rep"]["view"] == "plain"
        _on(w, A)
        w.call("color.set_params", RED)
        w.drain()
        views = w.state("video")["look"]["views"]
        assert views["rep"]["view"] == "profile" and views["orig"]["view"] == "plain"
        # a change to another clip leaves the one on show as it is
        assert w.call("video.set_pane_view", "rep", "plain")
        _on(w, B)
        w.call("color.set_params", {"gain": [0.9, 1.2, 0.9]})
        w.drain()
        assert w.state("video")["look"]["views"]["rep"]["view"] == "plain"


def test_the_page_sends_the_selected_clips_and_both_buttons():
    video = open(os.path.join(_TABS, "video.js"), encoding="utf-8").read()
    assert "more: selOpen.filter((x) => x.rel !== barRow.rel).map((x) => x.rel)" in video
    pane = open(os.path.join(_TABS, "color_pane.js"), encoding="utf-8").read()
    assert "file.attach || null, file.more || [])" in pane
    assert "Apply to all profiled ${all[1]}…" in pane
    assert "Apply to all ${all[1]}…" in pane
    assert ">Same as the other files<//>" in pane


def test_images_apply_to_all_reaches_the_unlocked_game_pictures(tmp_path):
    from tests.test_webui_images import _project as _images, _set_folder, _wait, _settled, BANNER
    assets, reps = _images(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
        assert w.call("images.choose", BANNER) == BANNER
        w.drain()
        assert w.call("color.panel_open")
        assert w.call("color.set_file", "images", BANNER, "SpaceGodzilla.png", False,
                      {"ns": "images"})
        w.drain()
        w.call("color.set_params", RED)
        w.drain()
        assert w.call("images.set_color_unlocked", True)
        svc = w.window.service("images")
        every = w.run(lambda: svc.color_targets("all"))
        assert every[BANNER] is True and len(every) > 1
        assert not any(on for rel, on in every.items() if rel != BANNER)
        assert w.run(lambda: svc.color_targets("profiled")) == {BANNER: True}
        assert w.call("color.apply_to_all", "profiled") is False      # no other attached
        w.answers = ["yes"]
        assert w.call("color.apply_to_all", "all") is True
        assert set(cp.own_profile_names(assets)["images"]) == set(every)
        assert w.run(lambda: svc.color_targets("profiled")) == dict.fromkeys(every, True)
        assert w.call("color.undo")
        assert cp.own_profile_names(assets)["images"] == {BANNER: "Custom red"}
        assert w.run(lambda: svc.color_targets("profiled")) == {BANNER: True}
