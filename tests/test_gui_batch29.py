"""Feedback batch 29 — the Spike 2 tester, on the Replace Text tab.

He went looking for the string behind a custom message, noticed the Scene
column wasn't all scenes, and sent four things back.  The two with logic
behind them are under test here (no window: the rules in
``webui/text_rules.py`` are called directly, the Text tab's own methods run
on duck-typed stubs):

* Filters.  "What about some filters so if I want to see
  'changed/unchanged/all' or 'scene\\program\\all'.  Even going further you
  could have the dropdown show 'all\\program\\[every scene]' so you can narrow
  it down to one scene."  The Text tab now has both dropdowns, and the row
  filter has to compose search + Show + Scene without either one leaking.

* Scene names.  "It could be useful to name/tag the scene in a new property?
  You could show the hex number and another column for the user friendly
  name.  The radium files as far as I know will never change their unique
  folder/file name."  Names are stored against the scene's container key —
  the SAME key the Replace Images tab tags its groups under — so a scene
  named on either tab reads the same on both, and survives a re-open.

The other two (the Project Folder link, the header/number alignment and the
early-wrapping help text) are layout, and are covered by the before/after
screenshots instead.

Naming a scene (the tag store it writes, a blank name clearing it, the
filter following a rename) is driven end to end in test_webui_text.py
(test_naming_a_scene_writes_the_shared_tag_store and
test_a_scene_named_here_survives_the_images_tab).
"""

from types import SimpleNamespace

from pinball_decryptor.core import staged_changes
from pinball_decryptor.webui import text_rules as R
from pinball_decryptor.webui.tabs.text import TextTab


class _Var:
    """The bits of a tab variable these helpers use."""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


SCENE_A = "/godzilla_pro/assets/lcd/auto_loaded/aaaa1111bbbb2222/scene.radium"
SCENE_B = "/godzilla_pro/assets/lcd/auto_loaded/cccc3333dddd4444/scene.radium"
PROGRAM = "/godzilla_pro/game"


def _row(path, original, replacement=""):
    return {"path": path, "original": original, "replacement": replacement}


ROWS = [
    _row(SCENE_A, "BALL SAVE"),
    _row(SCENE_A, "SHOOT BRIDGE", "SHOOT THE BRIDGE"),
    _row(SCENE_B, "REPLAY"),
    _row(PROGRAM, "BRIDGE ATTACK"),
]


# ---------------------------------------------------------------------------
# The row filter: search + Show + Scene, composed
# ---------------------------------------------------------------------------

def test_no_filters_keeps_every_row():
    assert all(R.row_matches(r, "", None, None) for r in ROWS)


def test_changed_is_an_edit_and_unchanged_is_its_exact_complement():
    changed = [r for r in ROWS if R.row_matches(r, "", True, None)]
    unchanged = [r for r in ROWS if R.row_matches(r, "", False, None)]
    assert [r["original"] for r in changed] == ["SHOOT BRIDGE"]
    assert len(changed) + len(unchanged) == len(ROWS)
    assert not [r for r in changed if r in unchanged]


def test_a_replacement_equal_to_the_original_is_not_a_change():
    same = _row(SCENE_A, "REPLAY", "REPLAY")
    assert not R.row_matches(same, "", True, None)
    assert R.row_matches(same, "", False, None)


def test_scene_filter_narrows_to_one_scene_file():
    kept = [r["original"] for r in ROWS
            if R.row_matches(r, "", None, SCENE_A)]
    assert kept == ["BALL SAVE", "SHOOT BRIDGE"]


def test_game_program_filter_is_everything_that_is_not_a_scene():
    kept = [r["original"] for r in ROWS
            if R.row_matches(r, "", None, R.SCENE_PROGRAM)]
    assert kept == ["BRIDGE ATTACK"]


def test_search_matches_the_original_or_the_new_text():
    # "the bridge" only exists in the replacement column of row 2.
    kept = [r["original"] for r in ROWS
            if R.row_matches(r, "the bridge", None, None)]
    assert kept == ["SHOOT BRIDGE"]


def test_the_three_filters_compose():
    # Unchanged strings on scene A that mention "ball".
    kept = [r["original"] for r in ROWS
            if R.row_matches(r, "ball", False, SCENE_A)]
    assert kept == ["BALL SAVE"]
    # ... and the edited one on that scene is not swept in by the search.
    assert not [r for r in ROWS
                if R.row_matches(r, "ball", True, SCENE_A)]


# ---------------------------------------------------------------------------
# The Scene dropdown
# ---------------------------------------------------------------------------

def test_menu_lists_all_then_program_then_each_scene_with_its_count():
    values, by_display = R.scene_menu(ROWS, {})
    assert values[0] == R.SCENE_ALL
    assert values[1] == R.SCENE_PROGRAM
    assert len(values) == 4                       # All, program, 2 scenes
    assert sorted(by_display.values()) == sorted([SCENE_A, SCENE_B])
    assert [v for v in values if by_display.get(v) == SCENE_A][0].endswith("(2)")
    assert [v for v in values if by_display.get(v) == SCENE_B][0].endswith("(1)")


def test_menu_omits_game_program_when_the_card_has_no_program_strings():
    values, _ = R.scene_menu(ROWS[:3], {})
    assert R.SCENE_PROGRAM not in values


def test_named_scenes_sort_first_and_show_their_name():
    names = {R.scene_key(SCENE_B): "Replay banner"}
    values, by_display = R.scene_menu(ROWS, names)
    scenes = [v for v in values if v in by_display]
    assert scenes[0].startswith("Replay banner — ")
    assert by_display[scenes[0]] == SCENE_B


def test_selection_resolves_a_display_back_to_its_scene_path():
    values, by_display = R.scene_menu(ROWS, {})
    disp = [v for v in values if by_display.get(v) == SCENE_A][0]
    stub = SimpleNamespace(text_scene_filter_var=_Var(disp),
                           _scene_choices=by_display)
    assert TextTab._scene_selection(stub) == SCENE_A
    stub.text_scene_filter_var.set(R.SCENE_ALL)
    assert TextTab._scene_selection(stub) is None
    stub.text_scene_filter_var.set(R.SCENE_PROGRAM)
    assert TextTab._scene_selection(stub) == R.SCENE_PROGRAM


def test_a_scene_this_folder_does_not_have_reads_as_no_selection():
    """A filter saved against another card must not silently blank the list —
    the tab's list refresh drops back to "All scenes" on exactly this None."""
    stub = SimpleNamespace(text_scene_filter_var=_Var("some other card (7)"),
                           _scene_choices={})
    assert TextTab._scene_selection(stub) is None


# ---------------------------------------------------------------------------
# Scene names: one store, shared with Replace Images
# ---------------------------------------------------------------------------

def test_the_scene_key_is_the_images_tab_radium_group_key():
    # engine.extract_radium_text records the radium's card path, and
    # _compute_image_groups keys that same container "rad::" + card path.
    assert R.scene_key(SCENE_A) == "rad::" + SCENE_A


def test_only_scene_files_carry_a_name():
    stub = SimpleNamespace(
        _scene_names={R.scene_key(SCENE_A): "Ball save banner",
                      R.scene_key(PROGRAM): "not a scene"})
    assert TextTab._scene_name(stub, SCENE_A) == "Ball save banner"
    assert TextTab._scene_name(stub, SCENE_B) == ""
    assert TextTab._scene_name(stub, PROGRAM) == ""


def _name_stub(folder):
    stub = SimpleNamespace(
        _text_scan_dir=str(folder), _scene_names={}, _text_rows=ROWS,
        _scene_choices={}, _scene_displays={}, _suspend=0,
        text_scene_filter_var=_Var(R.SCENE_ALL),
        set=lambda **_kw: None,
        _images_follow=lambda _scan_dir, _tags: None,
        _refresh_list=lambda rebuild_rows=False: None)
    stub._rebuild_scene_menu = lambda: TextTab._rebuild_scene_menu(stub)
    stub._scene_selection = lambda: TextTab._scene_selection(stub)
    return stub


def test_naming_a_scene_leaves_the_rest_of_the_sidecar_alone(tmp_path):
    staged_changes.save(str(tmp_path), {"audio": {"a.wav": "b.wav"},
                                        "image_group_tags": {"rad::x": "Keep"}})
    stub = _name_stub(tmp_path)
    stub._scene_names = {"rad::x": "Keep"}
    TextTab._set_scene_name(stub, R.scene_key(SCENE_A), "Ball save")

    saved = staged_changes.load(str(tmp_path))
    assert saved["audio"] == {"a.wav": "b.wav"}
    assert saved["image_group_tags"]["rad::x"] == "Keep"
    assert saved["image_group_tags"][R.scene_key(SCENE_A)] == "Ball save"
