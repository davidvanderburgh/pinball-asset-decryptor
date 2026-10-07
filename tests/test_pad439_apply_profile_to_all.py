"""PAD-439 (DragonRR): "Apply to all videos" / "Apply to all images" on the Colors bar.  The
file on show's color profile goes to every file of its kind its tab offers one on, attached,
after an "Are you sure?", and one Undo (or Redo) on that file takes all of it back."""

import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

pytest.importorskip("PIL.Image")

_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")

CLIPS = ("video/attract.mp4", "video/intro.mp4", "video/sub/boss.mp4")


def _video_project(tmp_path):
    from tests.test_webui_video import _project, _mine
    proj = _project(tmp_path, names=CLIPS)
    return proj, [_mine(tmp_path, "mine%d.mp4" % i) for i in range(len(CLIPS))]


def _open_on(w, kind, rel, ns):
    assert w.call("color.panel_open")
    on = (w.state(ns).get("rows") and next(
        (r["col"] for r in w.state(ns)["rows"] if r["rel"] == rel), None))
    assert w.call("color.set_file", kind, rel, os.path.basename(rel), bool(on), {"ns": ns})
    w.drain()


def test_apply_to_all_videos_asks_first_and_undoes_as_one_step(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_video import _scan
    proj, mine = _video_project(tmp_path)
    assets = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        for rel, path in zip(CLIPS, mine):
            w.answers.append(str(path))
            assert w.call("video.choose", rel) is True
        # one clip of its own profile, attached by the pick; the others have none attached
        _open_on(w, "videos", CLIPS[0], "video")
        w.call("color.set_params", {"name": "Custom red", "gain": [1.3, 0.9, 0.9]})
        w.drain()
        assert staged_changes.load(assets)["video_color_slots"] == {CLIPS[0]: True}
        assert w.call("color.undo") and w.call("color.undo", True)   # its own steps work
        # No: nothing changes
        w.answers.append("no")
        assert w.call("color.apply_to_all") is False
        q = w.asked[-1]
        assert q["title"] == "Apply to all videos"
        assert q["message"].startswith("Are you sure?")
        assert "All 3 videos" in q["message"] and "“Custom red”" in q["message"]
        assert "attached to the 2 that have none" in q["message"]
        assert set(cp.own_profile_names(assets)["videos"]) == {CLIPS[0]}
        # Yes: every clip has it, attached
        w.answers.append("yes")
        assert w.call("color.apply_to_all") is True
        w.drain()
        assert cp.own_profile_names(assets)["videos"] == {r: "Custom red" for r in CLIPS}
        assert all(cp.own_profile(assets, "videos", r).gain == (1.3, 0.9, 0.9)
                   for r in CLIPS)
        assert staged_changes.load(assets)["video_color_slots"] == {r: True for r in CLIPS}
        st = w.state("video")
        assert all(r["col"] is True for r in st["rows"])
        assert w.state("color")["can_undo"] is True
        log = [l["text"] for l in w.run(w.window.log_history)]
        assert any("applied to all 3 videos (attached to 2)" in t for t in log)
        # nothing left to change: a note, no question
        n = len(w.asked)
        assert w.call("color.apply_to_all") is False
        assert len(w.asked) == n
        # Undo: the profiles AND the switches as they were
        assert w.call("color.undo")
        w.drain()
        assert set(cp.own_profile_names(assets)["videos"]) == {CLIPS[0]}
        assert staged_changes.load(assets)["video_color_slots"] == {CLIPS[0]: True}
        assert {r["rel"]: r["col"] for r in w.state("video")["rows"]} == {
            CLIPS[0]: True, CLIPS[1]: False, CLIPS[2]: False}
        # Redo: all of it again
        assert w.call("color.undo", True)
        w.drain()
        assert set(cp.own_profile_names(assets)["videos"]) == set(CLIPS)
        assert staged_changes.load(assets)["video_color_slots"] == {r: True for r in CLIPS}
        # and the one before it still undoes after (the file's own pick)
        assert w.call("color.undo") and w.call("color.undo")
        assert cp.own_profile_names(assets)["videos"] == {}


def test_a_file_with_no_profile_of_its_own_puts_all_back_on_the_projects(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_video import _scan
    proj, mine = _video_project(tmp_path)
    assets = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        for rel, path in zip(CLIPS, mine):
            w.answers.append(str(path))
            assert w.call("video.choose", rel) is True
        cp.store_own_profile(assets, "videos", CLIPS[1], cp.Profile(name="Mine", gain=(1.2, 1, 1)))
        cp.store_own_profile(assets, "videos", CLIPS[2], cp.Profile(name="Other", gain=(1, 1.2, 1)))
        for rel in CLIPS:
            w.call("video.set_color", rel, True)
        _open_on(w, "videos", CLIPS[0], "video")
        assert w.state("color")["file"]["own"] is False
        w.answers.append("yes")
        assert w.call("color.apply_to_all") is True
        assert cp.own_profile_names(assets)["videos"] == {}
        assert "video_color_profiles" not in staged_changes.load(assets)
        assert w.call("color.undo")
        assert set(cp.own_profile_names(assets)["videos"]) == {CLIPS[1], CLIPS[2]}


def test_apply_to_all_images_and_the_lone_file(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_images import _project, _set_folder, _wait, _settled, BANNER, PLAIN
    assets, reps = _project(tmp_path)
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
        w.call("color.set_params", {"name": "Custom red", "gain": [1.3, 0.9, 0.9]})
        w.drain()
        # the only replaced picture: nothing to apply it to, and nothing asked
        n = len(w.asked)
        assert w.call("color.apply_to_all") is False
        assert len(w.asked) == n
        w.answers = [os.path.join(reps, "backglass.jpg")]
        assert w.call("images.choose", PLAIN) == PLAIN
        w.drain()
        w.call("color.set_file", "images", BANNER, "SpaceGodzilla.png", True, {"ns": "images"})
        w.drain()
        w.answers = ["yes"]
        assert w.call("color.apply_to_all") is True
        assert w.asked[-1]["title"] == "Apply to all images"
        assert cp.own_profile_names(assets)["images"] == {BANNER: "Custom red",
                                                          PLAIN: "Custom red"}
        assert staged_changes.load(assets)["image_color_slots"] == {BANNER: True, PLAIN: True}
        assert w.call("color.undo")
        assert cp.own_profile_names(assets)["images"] == {BANNER: "Custom red"}
        assert staged_changes.load(assets)["image_color_slots"] == {BANNER: True}


def test_the_button_is_on_the_images_and_video_bars_only():
    pane = open(os.path.join(_TABS, "color_pane.js"), encoding="utf-8").read()
    assert 'call("color.apply_to_all")' in pane
    assert "Apply to all ${all[1]}…" in pane
    assert 'ALL_HOSTS = { images: "images", video: "videos" }' in pane
    assert "<${FileLine} s=${s} host=${host} />" in pane
