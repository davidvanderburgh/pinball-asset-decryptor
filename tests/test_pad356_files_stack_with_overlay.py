"""PAD-356: the individual files' Recommended is the user's to stack with
the whole screen overlay's Recommended.  It used to change nothing while the
overlay was Recommended (PAD-346's no double correction), which greyed the
preview's Individual files switch; DragonRR wants both to apply."""

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes


def _project(d):
    staged_changes.save(d, {"image": {"images/x.png": __file__}})
    cp.set_asset_all(d, "images", True)


def test_files_recommended_stacks_with_the_recommended_overlay(tmp_path):
    d = str(tmp_path)
    _project(d)
    alone = cp.asset_profile(d)
    cp.store(d, None, follow=True)
    assert cp.asset_profile(d) == alone == cp.for_project(d)
    assert cp.asset_active(d) is not None
    files = cp.preview_parts(d)["files"]
    assert files["set"] is True and files["count"] == 1
    assert files["name"] == cp.RECOMMENDED


def test_no_change_on_the_files_still_greys_the_switch(tmp_path):
    d = str(tmp_path)
    _project(d)
    cp.store(d, None, follow=True)
    cp.store_asset_profile(d, cp.Profile(name="No change"))
    assert cp.asset_active(d) is None
    assert cp.preview_parts(d)["files"]["set"] is False
