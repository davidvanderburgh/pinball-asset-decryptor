"""The image sets picker (Simon, 2026-11-18): the project's sets by name, made, renamed, moved and removed, set 1
always the project itself; whatever a set holds moves with it."""
import pytest

from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import scene_variants as SV

CARD = "/games/godzilla_le/auto_loaded/" + "c" * 40 + "/scene.radium"


def test_a_project_starts_with_one_set(tmp_path):
    assert SV.set_names(str(tmp_path)) == ["Standard"]
    assert SV.set_names("") == ["Standard"]


def test_add_rename_and_the_ceiling(tmp_path):
    p = str(tmp_path)
    assert SV.add_set(p, "Dark") == 2
    assert SV.add_set(p) == 3
    assert SV.set_names(p) == ["Standard", "Dark", "Set 3"]
    SV.rename_set(p, 1, "Heisei")
    assert SV.set_names(p)[0] == "Heisei"
    with pytest.raises(SV.SceneVariantError):
        SV.rename_set(p, 3, "dark")                     # names are unique, whatever their case
    with pytest.raises(SV.SceneVariantError):
        SV.add_set(p, "   ")                            # an empty name is refused, not defaulted
    while len(SV.set_names(p)) < SV.MAX_SETS:
        SV.add_set(p)
    with pytest.raises(SV.SceneVariantError):
        SV.add_set(p)


def test_removing_a_set_moves_the_later_ones_and_their_variants_up(tmp_path):
    p = str(tmp_path)
    SV.add_set(p, "Dark")
    SV.add_set(p, "Red")
    side = staged_changes.load(p)
    side[SV.STAGED_KEY]["scenes"] = {CARD: {"2": {"card": True}, "3": {"file": "red.radium"}}}
    staged_changes.save(p, side)
    SV.remove_set(p, 2)
    assert SV.set_names(p) == ["Standard", "Red"]
    assert SV.load(p)["scenes"] == {CARD: {2: {"file": "red.radium"}}}
    with pytest.raises(SV.SceneVariantError):
        SV.remove_set(p, 1)


def test_moving_a_set_takes_its_variants(tmp_path):
    p = str(tmp_path)
    SV.add_set(p, "Dark")
    SV.add_set(p, "Red")
    side = staged_changes.load(p)
    side[SV.STAGED_KEY]["scenes"] = {CARD: {"2": {"file": "dark.radium"}}}
    staged_changes.save(p, side)
    SV.move_set(p, 2, 3)
    assert SV.set_names(p) == ["Standard", "Red", "Dark"]
    assert SV.load(p)["scenes"] == {CARD: {3: {"file": "dark.radium"}}}
    with pytest.raises(SV.SceneVariantError):
        SV.move_set(p, 2, 1)                            # set 1 stays the project itself


def test_back_to_one_default_set_leaves_no_trace(tmp_path):
    p = str(tmp_path)
    SV.add_set(p, "Dark")
    SV.remove_set(p, 2)
    assert SV.STAGED_KEY not in staged_changes.load(p)


def test_the_tab_rows_are_registered_hidden():
    from pinball_decryptor.webui.tabs import TABS
    assert ("image_sets", "imgsets", "", "", "", "") in TABS


def test_themes_stay_hidden_until_switched_on(tmp_path):
    """Simon: "hide ... image alternates behind an advanced curtain" - a project shows themes once switched on."""
    p = str(tmp_path)
    assert not SV.themes_on(p)
    SV.set_themes_on(p, True)
    assert SV.themes_on(p)
    assert SV.set_names(p) == ["Standard"]
    SV.set_themes_on(p, False)
    assert not SV.themes_on(p) and SV.STAGED_KEY not in staged_changes.load(p)


def test_themes_cannot_be_switched_off_while_there_are_others(tmp_path):
    p = str(tmp_path)
    SV.set_themes_on(p, True)
    SV.add_set(p, "Dark")
    with pytest.raises(SV.SceneVariantError, match="remove the other themes first"):
        SV.set_themes_on(p, False)
    SV.remove_set(p, 2)
    SV.set_themes_on(p, False)
    assert not SV.themes_on(p)
