"""Feedback batch 29 — the Spike 2 tester, on the Replace Text tab.

He went looking for the string behind a custom message, noticed the Scene
column wasn't all scenes, and sent four things back.  The two with logic
behind them are under test here (no Tk window; duck-typed stubs the way
test_gui_batch26 / test_gui_batch28 do it):

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
"""

import json

from types import SimpleNamespace

from pinball_decryptor.core import staged_changes
from pinball_decryptor.gui.main_window import MainWindow

W = MainWindow


class _Var:
    """The bits of tk.StringVar these helpers use."""

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
    assert all(W._text_row_matches(r, "", None, None) for r in ROWS)


def test_changed_is_an_edit_and_unchanged_is_its_exact_complement():
    changed = [r for r in ROWS if W._text_row_matches(r, "", True, None)]
    unchanged = [r for r in ROWS if W._text_row_matches(r, "", False, None)]
    assert [r["original"] for r in changed] == ["SHOOT BRIDGE"]
    assert len(changed) + len(unchanged) == len(ROWS)
    assert not [r for r in changed if r in unchanged]


def test_a_replacement_equal_to_the_original_is_not_a_change():
    same = _row(SCENE_A, "REPLAY", "REPLAY")
    assert not W._text_row_matches(same, "", True, None)
    assert W._text_row_matches(same, "", False, None)


def test_scene_filter_narrows_to_one_scene_file():
    kept = [r["original"] for r in ROWS
            if W._text_row_matches(r, "", None, SCENE_A)]
    assert kept == ["BALL SAVE", "SHOOT BRIDGE"]


def test_game_program_filter_is_everything_that_is_not_a_scene():
    kept = [r["original"] for r in ROWS
            if W._text_row_matches(r, "", None, W._TEXT_SCENE_PROGRAM)]
    assert kept == ["BRIDGE ATTACK"]


def test_search_matches_the_original_or_the_new_text():
    # "the bridge" only exists in the replacement column of row 2.
    kept = [r["original"] for r in ROWS
            if W._text_row_matches(r, "the bridge", None, None)]
    assert kept == ["SHOOT BRIDGE"]


def test_the_three_filters_compose():
    # Unchanged strings on scene A that mention "ball".
    kept = [r["original"] for r in ROWS
            if W._text_row_matches(r, "ball", False, SCENE_A)]
    assert kept == ["BALL SAVE"]
    # ... and the edited one on that scene is not swept in by the search.
    assert not [r for r in ROWS
                if W._text_row_matches(r, "ball", True, SCENE_A)]


# ---------------------------------------------------------------------------
# The Scene dropdown
# ---------------------------------------------------------------------------

def test_menu_lists_all_then_program_then_each_scene_with_its_count():
    values, by_display = W._text_scene_menu(ROWS, {})
    assert values[0] == W._TEXT_SCENE_ALL
    assert values[1] == W._TEXT_SCENE_PROGRAM
    assert len(values) == 4                       # All, program, 2 scenes
    assert sorted(by_display.values()) == sorted([SCENE_A, SCENE_B])
    assert [v for v in values if by_display.get(v) == SCENE_A][0].endswith("(2)")
    assert [v for v in values if by_display.get(v) == SCENE_B][0].endswith("(1)")


def test_menu_omits_game_program_when_the_card_has_no_program_strings():
    values, _ = W._text_scene_menu(ROWS[:3], {})
    assert W._TEXT_SCENE_PROGRAM not in values


def test_named_scenes_sort_first_and_show_their_name():
    names = {W._text_scene_key(SCENE_B): "Replay banner"}
    values, by_display = W._text_scene_menu(ROWS, names)
    scenes = [v for v in values if v in by_display]
    assert scenes[0].startswith("Replay banner — ")
    assert by_display[scenes[0]] == SCENE_B


def test_selection_resolves_a_display_back_to_its_scene_path():
    values, by_display = W._text_scene_menu(ROWS, {})
    disp = [v for v in values if by_display.get(v) == SCENE_A][0]
    stub = SimpleNamespace(text_scene_filter_var=_Var(disp),
                           _text_scene_choices=by_display,
                           _TEXT_SCENE_ALL=W._TEXT_SCENE_ALL,
                           _TEXT_SCENE_PROGRAM=W._TEXT_SCENE_PROGRAM)
    assert W._text_scene_selection(stub) == SCENE_A
    stub.text_scene_filter_var.set(W._TEXT_SCENE_ALL)
    assert W._text_scene_selection(stub) is None
    stub.text_scene_filter_var.set(W._TEXT_SCENE_PROGRAM)
    assert W._text_scene_selection(stub) == W._TEXT_SCENE_PROGRAM


def test_a_scene_this_folder_does_not_have_reads_as_no_selection():
    """A filter saved against another card must not silently blank the list —
    _refresh_text_list drops back to "All scenes" on exactly this None."""
    stub = SimpleNamespace(text_scene_filter_var=_Var("some other card (7)"),
                           _text_scene_choices={},
                           _TEXT_SCENE_ALL=W._TEXT_SCENE_ALL,
                           _TEXT_SCENE_PROGRAM=W._TEXT_SCENE_PROGRAM)
    assert W._text_scene_selection(stub) is None


# ---------------------------------------------------------------------------
# Scene names: one store, shared with Replace Images
# ---------------------------------------------------------------------------

def test_the_scene_key_is_the_images_tab_radium_group_key():
    # engine.extract_radium_text records the radium's card path, and
    # _compute_image_groups keys that same container "rad::" + card path.
    assert W._text_scene_key(SCENE_A) == "rad::" + SCENE_A


def test_only_scene_files_carry_a_name():
    stub = SimpleNamespace(
        _text_scene_names={W._text_scene_key(SCENE_A): "Ball save banner",
                           W._text_scene_key(PROGRAM): "not a scene"},
        _text_scene_key=W._text_scene_key)
    assert W._text_scene_name(stub, SCENE_A) == "Ball save banner"
    assert W._text_scene_name(stub, SCENE_B) == ""
    assert W._text_scene_name(stub, PROGRAM) == ""


def _name_stub(folder):
    stub = SimpleNamespace(
        _text_scan_dir=str(folder), _text_scene_names={}, _text_rows=ROWS,
        _text_scene_choices={}, _text_scene_displays={}, _image_scan_dir="",
        text_scene_filter_var=_Var(W._TEXT_SCENE_ALL),
        _TEXT_SCENE_ALL=W._TEXT_SCENE_ALL,
        _TEXT_SCENE_PROGRAM=W._TEXT_SCENE_PROGRAM,
        _text_scene_key=W._text_scene_key,
        _text_scene_label=W._text_scene_label,
        _same_folder=W._same_folder,
        _refresh_text_list=lambda: None,
        _text_reselect=lambda _iid: None)
    stub._text_scene_menu = W._text_scene_menu
    stub._text_rebuild_scene_menu = lambda: W._text_rebuild_scene_menu(stub)
    stub._text_scene_selection = lambda: W._text_scene_selection(stub)
    return stub


def test_naming_a_scene_writes_the_images_tab_tag_store(tmp_path):
    stub = _name_stub(tmp_path)
    key = W._text_scene_key(SCENE_A)
    W._text_set_scene_name(stub, key, "Ball save banner")

    saved = staged_changes.load(str(tmp_path))
    assert saved["image_group_tags"] == {key: "Ball save banner"}
    # ... and the dropdown shows it straight away.
    assert any(d.startswith("Ball save banner — ")
               for d in stub._text_scene_choices)


def test_naming_a_scene_leaves_the_rest_of_the_sidecar_alone(tmp_path):
    staged_changes.save(str(tmp_path), {"audio": {"a.wav": "b.wav"},
                                        "image_group_tags": {"rad::x": "Keep"}})
    stub = _name_stub(tmp_path)
    stub._text_scene_names = {"rad::x": "Keep"}
    W._text_set_scene_name(stub, W._text_scene_key(SCENE_A), "Ball save")

    saved = staged_changes.load(str(tmp_path))
    assert saved["audio"] == {"a.wav": "b.wav"}
    assert saved["image_group_tags"]["rad::x"] == "Keep"
    assert saved["image_group_tags"][W._text_scene_key(SCENE_A)] == "Ball save"


def test_a_blank_name_clears_it(tmp_path):
    stub = _name_stub(tmp_path)
    key = W._text_scene_key(SCENE_A)
    W._text_set_scene_name(stub, key, "Ball save banner")
    W._text_set_scene_name(stub, key, "")

    assert stub._text_scene_names == {}
    saved = staged_changes.load(str(tmp_path))
    assert saved["image_group_tags"] == {}
    assert json.loads(
        (tmp_path / staged_changes.SIDE_CAR).read_text(encoding="utf-8")
    )["image_group_tags"] == {}


def test_renaming_the_scene_you_are_filtered_to_keeps_the_filter(tmp_path):
    """The rename rewrites that scene's entry in the dropdown, so the saved
    display string would otherwise go stale and drop the user back to All."""
    stub = _name_stub(tmp_path)
    stub._text_rebuild_scene_menu()
    disp = [d for d, p in stub._text_scene_choices.items() if p == SCENE_A][0]
    stub.text_scene_filter_var.set(disp)

    W._text_set_scene_name(stub, W._text_scene_key(SCENE_A), "Ball save banner")

    assert W._text_scene_selection(stub) == SCENE_A
    assert stub.text_scene_filter_var.get().startswith("Ball save banner — ")
