"""PAD-1193: a folder of the user's own files beside the extract is not slots.

A Guns N' Roses extract with a ``_Replacements/Songs`` folder of the user's
replacement clips added to it: the Video tab listed every clip in there as an
original slot, each flagged "not on this card".  The baseline names every
folder the extract wrote into, so the Replace tabs walk only those.
"""

import hashlib
import os

from pinball_decryptor.core import checksums
from pinball_decryptor.core.audio_slots import scan_audio_slots
from pinball_decryptor.core.image_slots import scan_image_slots
from pinball_decryptor.core.video_slots import scan_video_slots


def _put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _rels(slots):
    return [s.rel_path for s in slots]


def _project(tmp_path):
    proj = tmp_path / "GNR"
    _put(str(proj / "videos" / "songs" / "civil_war.mp4"), b"clip-1")
    _put(str(proj / "videos" / "attract.mp4"), b"clip-2")
    _put(str(proj / "sounds" / "callout.wav"), b"snd")
    _put(str(proj / "images" / "logo.png"), b"pic")
    checksums.generate_checksums(str(proj))
    # the user's own folder, added after the extract
    mine = proj / "_Replacements" / "Songs"
    _put(str(mine / "JJP_Civil War_NY91.webm"), b"mine-1")
    _put(str(mine / "JJP_Coma.wav"), b"mine-2")
    _put(str(mine / "cover.png"), b"mine-3")
    return proj


def test_user_folder_is_not_listed_on_any_replace_tab(tmp_path):
    proj = str(_project(tmp_path))
    assert _rels(scan_video_slots(proj, probe=False)) == [
        "videos/attract.mp4", "videos/songs/civil_war.mp4"]
    assert _rels(scan_audio_slots(proj, probe=False)) == ["sounds/callout.wav"]
    assert _rels(scan_image_slots(proj, probe=False)) == ["images/logo.png"]


def test_user_folder_inside_an_extract_folder_is_skipped_too(tmp_path):
    proj = _project(tmp_path)
    _put(str(proj / "videos" / "my clips" / "new.mp4"), b"mine")
    assert _rels(scan_video_slots(str(proj), probe=False)) == [
        "videos/attract.mp4", "videos/songs/civil_war.mp4"]


def test_a_stray_file_in_an_extract_folder_still_lists(tmp_path):
    # a file dropped next to the card's own still shows (the tab flags it
    # "not on this card"), only whole folders of the user's are skipped
    proj = _project(tmp_path)
    _put(str(proj / "videos" / "songs" / "copied_in.mp4"), b"stray")
    assert "videos/songs/copied_in.mp4" in _rels(
        scan_video_slots(str(proj), probe=False))


def test_no_baseline_walks_every_folder(tmp_path):
    proj = _project(tmp_path)
    os.remove(str(proj / checksums.CHECKSUMS_FILE))
    assert "_Replacements/Songs/JJP_Civil War_NY91.webm" in _rels(
        scan_video_slots(str(proj), probe=False))


def test_jjp_md5sum_baseline_and_folder_case(tmp_path):
    # JJP writes "<md5>  ./path"; Windows folders match whatever the case
    proj = tmp_path / "jjp"
    _put(str(proj / "Videos" / "a.mp4"), b"a")
    _put(str(proj / "Mine" / "b.mp4"), b"b")
    with open(str(proj / checksums.CHECKSUMS_FILE), "w") as f:
        f.write("%s  ./videos/a.mp4\n" % hashlib.md5(b"a").hexdigest())
    assert _rels(scan_video_slots(str(proj), probe=False)) == [
        "Videos/a.mp4"]


def test_plugin_kept_folder_outside_the_baseline_still_lists(tmp_path):
    proj = _project(tmp_path)
    _put(str(proj / "derived" / "x.mp4"), b"d")
    assert "derived/x.mp4" not in _rels(
        scan_video_slots(str(proj), probe=False))
    assert "derived/x.mp4" in _rels(
        scan_video_slots(str(proj), probe=False, keep_dirs=("derived",)))


def test_extract_dirs():
    assert checksums.extract_dirs("", baseline={}) is None
    assert checksums.extract_dirs("", baseline={
        "a/B/c.mp4": "0", "top.wav": "0"}) == {"", "a", "a/b"}


def test_cgc_derived_sound_folders_still_list(tmp_path):
    # CGC leaves dcs_audio/ + new_audio/ out of its baseline on purpose and
    # Write repacks them: the Audio tab must keep listing them
    from pinball_decryptor.plugins.cgc.manufacturer import CGCManufacturer
    from pinball_decryptor.plugins.cgc.pipeline import (
        DCS_SUBDIR, NEW_AUDIO_SUBDIR, _DERIVED_SUBDIRS)
    proj = tmp_path / "cc"
    _put(str(proj / "sound" / "a.wav"), b"a")
    checksums.generate_checksums(str(proj), exclude_dirs=_DERIVED_SUBDIRS)
    _put(str(proj / DCS_SUBDIR / "s001" / "b.wav"), b"b")
    _put(str(proj / NEW_AUDIO_SUBDIR / "c.wav"), b"c")
    _put(str(proj / "My sounds" / "d.wav"), b"d")
    keep = CGCManufacturer().slot_keep_dirs(str(proj))
    assert _rels(scan_audio_slots(str(proj), probe=False,
                                  keep_dirs=keep)) == [
        "dcs_audio/s001/b.wav", "new_audio/c.wav", "sound/a.wav"]


def test_a_delta_folder_after_the_baseline_still_lists(tmp_path):
    # DP / PB baseline the pristine base, then merge update deltas on top:
    # a folder only a delta brings is the card's, not the user's
    import tarfile
    from pinball_decryptor.plugins.pb.pipeline import apply_delta
    proj = tmp_path / "pb"
    _put(str(proj / "media" / "a.mp4"), b"a")
    checksums.generate_checksums(str(proj))
    src = tmp_path / "src"
    _put(str(src / "media" / "new" / "b.mp4"), b"b")
    upd = str(tmp_path / "d.upd")
    with tarfile.open(upd, "w:gz") as tar:
        tar.add(str(src / "media"), arcname="media")
    apply_delta(str(proj), upd)
    _put(str(proj / "mine" / "c.mp4"), b"c")
    assert _rels(scan_video_slots(str(proj), probe=False)) == [
        "media/a.mp4", "media/new/b.mp4"]
    # a fresh extract's baseline starts the record over
    checksums.generate_checksums(str(proj))
    assert not os.path.exists(str(proj / checksums.EXTRACT_DIRS_FILE))


def test_dp_delta_zip_records_its_folders(tmp_path):
    import zipfile
    from pinball_decryptor.plugins.dp.pipeline import _apply_delta_zip
    proj = tmp_path / "dp"
    _put(str(proj / "1.0" / "a.mp4"), b"a")
    checksums.generate_checksums(str(proj))
    z = str(tmp_path / "d.zip")
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("1.1/extra/b.mp4", b"b")
    _apply_delta_zip(str(proj), z, "1.1", "1.0")
    assert "1.0/extra/b.mp4" in _rels(
        scan_video_slots(str(proj), probe=False))


def test_a_hook_that_answers_nonsense_keeps_the_rule(tmp_path):
    from unittest import mock
    proj = _project(tmp_path)
    assert _rels(scan_video_slots(str(proj), probe=False,
                                  keep_dirs=mock.MagicMock())) == [
        "videos/attract.mp4", "videos/songs/civil_war.mp4"]
