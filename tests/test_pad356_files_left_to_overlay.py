"""PAD-356: Recommended on the individual files while the whole screen
overlay is Recommended changes nothing (the overlay already undoes the screen
for the files), so the page and the preview row must say so instead of a bare
"No change"."""

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes


def _project(d):
    staged_changes.save(d, {"image": {"images/x.png": __file__}})
    cp.set_asset_all(d, "images", True)


def test_files_recommended_is_left_to_the_recommended_overlay(tmp_path):
    d = str(tmp_path)
    _project(d)
    assert cp.files_by_overlay(d) is False
    assert cp.preview_parts(d)["files"]["set"] is True
    cp.store(d, None, follow=True)
    assert cp.files_by_overlay(d) is True
    files = cp.preview_parts(d)["files"]
    assert files["set"] is False and files["by_overlay"] is True
    assert files["count"] == 1


def test_a_stored_files_profile_is_not_left_to_the_overlay(tmp_path):
    d = str(tmp_path)
    _project(d)
    cp.store(d, None, follow=True)
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    assert cp.files_by_overlay(d) is False
    assert cp.preview_parts(d)["files"]["by_overlay"] is False


def test_an_overlay_of_its_own_leaves_the_files_their_recommended(tmp_path):
    d = str(tmp_path)
    _project(d)
    cp.store(d, cp.Profile(name="Less red", gain=(0.5, 1.0, 1.0)))
    assert cp.files_by_overlay(d) is False
    assert cp.preview_parts(d)["files"]["set"] is True


def test_no_project_is_never_left_to_the_overlay():
    assert cp.files_by_overlay("") is False
