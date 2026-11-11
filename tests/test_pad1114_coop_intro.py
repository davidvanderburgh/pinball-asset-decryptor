"""PAD-1114: the co-op and team games' intro video - kept in the project, carried by the co-op settings file."""
import os

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    return str(p)


def _video(tmp_path, name="intro.mp4", data=b"not really a video"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_intro_kept_without_characters(project, tmp_path):
    chars = CP.save_intro(project, _video(tmp_path))
    assert chars["intro"] == "coop/intro_video.mp4"
    assert CP.load_characters(project)["intro"] == "coop/intro_video.mp4"
    assert CP.intro_path(project) == os.path.join(project, "coop", "intro_video.mp4")
    assert CP.load_characters(project)["list"] == []


def test_intro_other_extension_replaces(project, tmp_path):
    CP.save_intro(project, _video(tmp_path))
    CP.save_intro(project, _video(tmp_path, "intro.mov"))
    assert sorted(os.listdir(os.path.join(project, "coop"))) == ["intro_video.mov"]
    assert CP.intro_path(project).endswith("intro_video.mov")


def test_intro_forgotten(project, tmp_path):
    CP.save_intro(project, _video(tmp_path))
    CP.save_intro(project, None)
    assert "intro" not in CP.load_characters(project)
    assert CP.intro_path(project) == ""


def test_not_a_video_refused(project, tmp_path):
    with pytest.raises(CP.CoopError):
        CP.save_intro(project, _video(tmp_path, "intro.txt"))


def test_settings_file_carries_intro(project, tmp_path):
    from pinball_decryptor.plugins.stern import coop_play
    coop_play.save(project, True)
    CP.save_intro(project, _video(tmp_path, data=b"intro bytes"))
    zpath = str(tmp_path / "coop.zip")
    CP.export_settings(project, zpath)
    other = tmp_path / "other"
    other.mkdir()
    got = CP.import_settings(str(other), zpath)
    assert got["pictures"] == 1
    assert CP.load_characters(str(other))["intro"] == "coop/intro_video.mp4"
    with open(CP.intro_path(str(other)), "rb") as f:
        assert f.read() == b"intro bytes"
