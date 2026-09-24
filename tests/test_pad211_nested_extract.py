"""PAD-211: another card's extract nested inside a project is not this card's.

Extract Both, pointed at the 1.31 project, put the 1.27 stock and modded
extracts in sub-folders of it.  The Write took every ``idxNNNN.wav`` in there
as an edit of the same idx on the 1.31 card (2664 "edited" sounds, an hour of
re-encoding the wrong audio), and the Replace tabs listed thousands of strays.
"""

import os

from pinball_decryptor.core import checksums
from pinball_decryptor.core.audio_slots import scan_audio_slots
from pinball_decryptor.core.image_slots import scan_image_slots
from pinball_decryptor.core.video_slots import scan_video_slots
from pinball_decryptor.plugins.stern import engine


def _put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _project(tmp_path):
    """A project with idx0000/idx0001, baselined, then a nested extract."""
    proj = tmp_path / "SW_131"
    _put(str(proj / "audio" / "idx0000.wav"), b"new-0")
    _put(str(proj / "audio" / "idx0001.wav"), b"new-1")
    _put(str(proj / "video" / "clip.mov"), b"clip")
    _put(str(proj / "images" / "pic.png"), b"pic")
    checksums.generate_checksums(str(proj))
    old = proj / "star_wars_le-1_27_0.Boris_Release.8G.sdcard"
    _put(str(old / "audio" / "idx0000.wav"), b"old-0")
    _put(str(old / "audio" / "idx0001.wav"), b"old-1")
    _put(str(old / "video" / "AM_SCENE_001.mov"), b"old clip")
    _put(str(old / "images" / "boot_screen" / "SternLogo.png"), b"old pic")
    checksums.generate_checksums(str(old))
    return proj


def test_write_does_not_take_a_nested_extracts_sounds_as_edits(tmp_path):
    proj = _project(tmp_path)
    baseline = checksums.read_checksums(str(proj))
    assert engine._select_changed_idx_wavs(str(proj), baseline) == {}


def test_real_edit_beside_a_nested_extract_still_found(tmp_path):
    proj = _project(tmp_path)
    _put(str(proj / "audio" / "idx0001.wav"), b"edited")
    baseline = checksums.read_checksums(str(proj))
    edits = engine._select_changed_idx_wavs(str(proj), baseline)
    assert list(edits) == [1]
    assert os.path.dirname(edits[1]) == str(proj / "audio")


def test_replace_tabs_do_not_list_a_nested_extract(tmp_path):
    proj = str(_project(tmp_path))
    assert [s.rel_path for s in scan_audio_slots(proj, probe=False)] == [
        "audio/idx0000.wav", "audio/idx0001.wav"]
    assert [s.rel_path for s in scan_video_slots(proj, probe=False)] == [
        "video/clip.mov"]
    assert [s.rel_path for s in scan_image_slots(proj, probe=False)] == [
        "images/pic.png"]


def test_re_extract_does_not_baseline_a_nested_extract(tmp_path):
    proj = _project(tmp_path)
    checksums.generate_checksums(str(proj))
    rels = set(checksums.read_checksums(str(proj)))
    assert not any(r.startswith("star_wars_le") for r in rels)
    assert "audio/idx0000.wav" in rels
