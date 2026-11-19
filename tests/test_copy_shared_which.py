"""The Colors bar's one Copy in the running app (Simon, 2026-11-19, his design): the shared profile given to the clips
"that don't have a profile AND are unlocked" leaves the ones with a profile of their own alone; "With a profile" gives
it to those, switching nothing new on; one Undo puts each back."""
import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

pytest.importorskip("PIL.Image")

from tests.test_pad439_apply_profile_to_all import CLIPS, _video_project    # noqa: E402


def test_shared_profile_to_the_clips_without_and_with_a_profile(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_video import _scan
    proj, mine = _video_project(tmp_path)
    assets = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        for rel, path in zip(CLIPS, mine):
            w.answers.append(str(path))
            assert w.call("video.choose", rel) is True
        # clip 0 tuned by hand and switched on; clips 1 and 2 raw (switched off)
        cp.store_own_profile(assets, "videos", CLIPS[0], cp.Profile(name="Mine", gain=(1.2, 1, 1)))
        w.call("video.set_color", CLIPS[0], True)
        for rel in CLIPS[1:]:
            w.call("video.set_color", rel, False)
        w.drain()
        assert w.call("color.panel_open")
        w.drain()
        # the count says what APPLY will do
        r = w.call("color.copy_preview", "shared", "videos", "off", "this")
        assert r["n"] == 2 and "with no profile attached" in r["text"]
        w.answers.append("yes")
        assert w.call("color.copy_profile", "shared", "videos", "off", "this") is True
        w.drain()
        q = w.asked[-1]
        assert q["message"].startswith("WARNING: THIS WILL GIVE THE PROFILE") and "2 VIDEOS" in q["message"]
        slots = staged_changes.load(assets)["video_color_slots"]
        assert slots == {r: True for r in CLIPS}                  # the two raw ones switched on
        assert set(cp.own_profile_names(assets)["videos"]) == {CLIPS[0]}   # the hand-tuned one kept
        assert w.call("color.undo")
        w.drain()
        assert staged_changes.load(assets)["video_color_slots"] == {CLIPS[0]: True, CLIPS[1]: False,
                                                                     CLIPS[2]: False}
        # With a profile: only clip 0 (switched on) gets the shared profile - its own is dropped, nothing switched on
        assert w.call("color.copy_preview", "shared", "videos", "profiled", "this")["n"] == 1
        w.answers.append("yes")
        assert w.call("color.copy_profile", "shared", "videos", "profiled", "this") is True
        w.drain()
        assert cp.own_profile_names(assets)["videos"] == {}
        assert staged_changes.load(assets)["video_color_slots"][CLIPS[1]] is False
