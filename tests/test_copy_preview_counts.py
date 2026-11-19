"""The Colors bar's Copy count (color.copy_preview): it counts what Copy profile... would change, for a file's own
profile and for the shared files profile (Simon, 2026-11-19: "it doesn't work at all now. Just says 0")."""
import pytest

pytest.importorskip("PIL.Image")

from tests.test_pad439_apply_profile_to_all import CLIPS, _open_on, _video_project  # noqa: E402


def test_the_count_for_a_files_profile_and_for_the_shared_one(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_video import _scan
    proj, mine = _video_project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        for rel, path in zip(CLIPS, mine):
            w.answers.append(str(path))
            assert w.call("video.choose", rel) is True
        # nothing selected: the shared profile to every clip not locked (the three replaced)
        got = w.call("color.copy_preview", "shared", "videos", "all", "this")
        assert got["n"] == 3, got
        # a clip selected: its profile to the other clips
        _open_on(w, "videos", CLIPS[0], "video")
        w.call("color.set_params", {"name": "Custom red", "gain": [1.3, 0.9, 0.9]})
        w.drain()
        got = w.call("color.copy_preview", "file", "videos", "all", "this")
        assert got["n"] == 2, got
