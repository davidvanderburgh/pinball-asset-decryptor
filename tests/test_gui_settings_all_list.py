"""GUI guards for the Defaults tab's "All settings" list (peanuts).

Covers what the list promises: every setting is listed with the machine's own
caption, the Menu column separates the three cases, the filter leaves only what
the Adjustments menu can't reach, and a build whose menu couldn't be read says
so instead of flagging anything.

Then the two things peanuts asked for on top of it — setting the default of a
setting the curated form doesn't draw (including the hidden ones), and staging
the firmware patch that makes the machine's own menu show them.
"""
import json
import os

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]


def _stern(app):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update()
    return app.window


def _row(label, status, default=0, lo=0, hi=1, adj_id=1):
    return {"id": adj_id, "name": "AD_" + label.replace(" ", "_"),
            "label": label, "default": default,
            "min": lo, "max": hi, "step": 1, "labels": None, "status": status}


ROWS = [
    _row("FREE PLAY", "", adj_id=0x54),
    _row("MASTER VOLUME SETTING", "service", 64, 0, 64, adj_id=0x10),
    _row("ALLOW TOPPER CHEATS", "debug", adj_id=0xD4),
    _row("THIS IS THE WAY DEBUG", "debug", adj_id=0xD3),
]


def _fill(w, rows):
    w._settings_all_rows = list(rows)
    w._settings_fill_all_tree()
    tree = w._settings_all_tree
    return [(tree.item(k, "text"), tree.item(k, "values"))
            for k in tree.get_children()]


def test_lists_every_setting_with_caption_id_and_menu_column(app):
    w = _stern(app)
    got = _fill(w, ROWS)
    assert len(got) == len(ROWS)
    texts = [t for t, _v in got]
    # The machine's own caption, plus the id peanuts cross-references against.
    assert "ALLOW TOPPER CHEATS  (0xD4)" in texts
    by_label = {t.split("  (")[0]: v for t, v in got}
    assert by_label["FREE PLAY"][3] == "Adjustments"
    assert by_label["MASTER VOLUME SETTING"][3] == "Service menu"
    assert by_label["THIS IS THE WAY DEBUG"][3] == "Debug"
    # A 0/1 setting reads as Off/On, not as a bare number.
    assert by_label["FREE PLAY"][0] == "Off"
    assert by_label["FREE PLAY"][2] == "off / on"
    assert by_label["MASTER VOLUME SETTING"][2] == "0 - 64"
    # Nothing edited yet, so the "New default" column is empty throughout.
    assert {v[1] for _t, v in got} == {""}


def test_filter_leaves_only_what_the_adjustments_menu_cannot_reach(app):
    w = _stern(app)
    _fill(w, ROWS)
    w._settings_hidden_only.set(True)
    w._settings_fill_all_tree()
    got = [w._settings_all_tree.item(k, "values")[3]
           for k in w._settings_all_tree.get_children()]
    assert sorted(got) == ["Debug", "Debug", "Service menu"]
    assert "3 listed" in w._settings_all_legend.cget("text")


def test_unreadable_menu_flags_nothing_and_says_so(app):
    """James Bond 60th's shape: statuses is None, so no row may claim a
    verdict — the complement of a half-read menu is not a fact."""
    w = _stern(app)
    rows = [dict(r, status=None) for r in ROWS]
    got = _fill(w, rows)
    assert [v[3] for _t, v in got] == ["", "", "", ""]
    legend = w._settings_all_legend.cget("text")
    assert "couldn't be read" in legend
    assert "Debug" not in legend


def test_clearing_the_form_takes_the_list_away(app):
    w = _stern(app)
    _fill(w, ROWS)
    w._settings_clear_form()
    assert w._settings_all_tree.get_children() == ()
    assert not w._settings_all_frame.winfo_ismapped()


def test_empty_list_leaves_no_stale_legend(app):
    w = _stern(app)
    _fill(w, ROWS)
    got = _fill(w, [])
    assert got == []
    assert w._settings_all_legend.cget("text") == ""


# ---------------------------------------------------------------------------
# Editing a setting the curated form doesn't draw (peanuts: "write ... these
# hidden/debug values").
# ---------------------------------------------------------------------------

def _editable(w, tmp_path, rows=ROWS):
    """A loaded-looking tab whose staged changes land in *tmp_path*."""
    w.write_assets_var.set(str(tmp_path))
    w._settings_table = object()          # only its not-None-ness is used
    w._settings_every = list(rows)
    _fill(w, rows)
    return w


def _item(w, label):
    tree = w._settings_all_tree
    return next(k for k in tree.get_children()
                if tree.item(k, "text").startswith(label))


def _staged(tmp_path):
    p = os.path.join(str(tmp_path), ".staged_changes.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_editing_a_hidden_setting_stages_it_and_shows_it_in_the_list(
        app, tmp_path, monkeypatch):
    w = _editable(_stern(app), tmp_path)
    item = _item(w, "ALLOW TOPPER CHEATS")
    w._settings_all_tree.focus(item)
    monkeypatch.setattr(w, "_settings_ask_value", lambda row: 1)
    w._settings_all_edit()
    # Staged under the adjustment's own name, in the firmware's units.
    assert _staged(tmp_path)["settings"] == {"AD_ALLOW_TOPPER_CHEATS": 1}
    # ...and the list says so, without losing the card's own value.
    vals = w._settings_all_tree.item(_item(w, "ALLOW TOPPER CHEATS"), "values")
    assert (vals[0], vals[1]) == ("Off", "On")
    assert w._settings_all_tree.item(_item(w, "FREE PLAY"), "values")[1] == ""


def test_an_edited_setting_reports_itself_in_the_log(app, tmp_path,
                                                     monkeypatch):
    """The list has no field to leave, so the edit has to narrate itself —
    and the FIRST edit after a load counts (it used to be swallowed as
    "the first look at this card")."""
    w = _editable(_stern(app), tmp_path)
    w._settings_apply_staged_overlay()
    lines = []
    monkeypatch.setattr(w, "append_log", lambda msg, *a, **k: lines.append(msg))
    monkeypatch.setattr(w, "_settings_ask_value", lambda row: 1)
    w._settings_all_tree.focus(_item(w, "THIS IS THE WAY DEBUG"))
    w._settings_all_edit()
    assert any("THIS IS THE WAY DEBUG" in ln and "staged" in ln
               for ln in lines), lines


def test_back_to_the_card_value_unstages_it(app, tmp_path, monkeypatch):
    w = _editable(_stern(app), tmp_path)
    w._settings_all_tree.focus(_item(w, "ALLOW TOPPER CHEATS"))
    monkeypatch.setattr(w, "_settings_ask_value", lambda row: 1)
    w._settings_all_edit()
    assert _staged(tmp_path).get("settings")
    monkeypatch.setattr(w, "_settings_ask_value", lambda row: row["default"])
    w._settings_all_edit()
    assert not _staged(tmp_path).get("settings")
    assert w._settings_all_tree.item(_item(w, "ALLOW TOPPER CHEATS"),
                                     "values")[1] == ""


def test_staged_edits_come_back_when_the_card_is_reloaded(app, tmp_path):
    """A setting the curated form doesn't draw still gets its row back, or
    the next Build would bake in a value the tab no longer shows."""
    w = _editable(_stern(app), tmp_path)
    from pinball_decryptor.core import staged_changes
    staged_changes.save(str(tmp_path), {"settings": {"AD_ALLOW_TOPPER_CHEATS": 1}})
    w._settings_build_form([])            # no curated rows for this build
    assert w._settings_all_tree.item(_item(w, "ALLOW TOPPER CHEATS"),
                                     "values")[1] == "On"
    assert w.staged_default_settings(str(tmp_path)) == {
        "AD_ALLOW_TOPPER_CHEATS": 1}


# ---------------------------------------------------------------------------
# Opening the machine's own menu up to them ("...and activate").
# ---------------------------------------------------------------------------

PLAN = {"first": 0x7F, "last": 0xD2, "call": 0, "off": 0, "form": "mov",
        "candidates": [{"id": 0xD3, "name": "AD_THIS_IS_THE_WAY_DEBUG"},
                       {"id": 0xD4, "name": "AD_ALLOW_TOPPER_CHEATS"}]}


def test_the_menu_button_follows_whether_this_build_can_be_widened(app,
                                                                   tmp_path):
    w = _editable(_stern(app), tmp_path)
    w._settings_menu_plan = None
    w._settings_build_form([])
    assert str(w._settings_menu_btn["state"]) == "disabled"
    w._settings_menu_plan = PLAN
    w._settings_build_form([])
    assert str(w._settings_menu_btn["state"]) == "normal"


def test_menu_widening_stages_by_name_and_says_so(app, tmp_path):
    w = _editable(_stern(app), tmp_path)
    assert w._settings_stage_menu_expose("AD_ALLOW_TOPPER_CHEATS")
    # By NAME, never by id: the same id means something else in another build.
    assert _staged(tmp_path)["menu_expose_through"] == "AD_ALLOW_TOPPER_CHEATS"
    assert w.staged_menu_expose(str(tmp_path)) == "AD_ALLOW_TOPPER_CHEATS"
    w._settings_apply_staged_overlay()
    assert "ALLOW TOPPER CHEATS" in w._settings_status.cget("text")


def test_reset_fields_clears_the_menu_widening_too(app, tmp_path, monkeypatch):
    w = _editable(_stern(app), tmp_path)
    w._settings_stage_menu_expose("AD_ALLOW_TOPPER_CHEATS")
    monkeypatch.setattr(w, "_settings_ask_value", lambda row: 1)
    w._settings_all_tree.focus(_item(w, "ALLOW TOPPER CHEATS"))
    w._settings_all_edit()
    w._settings_reset()
    assert w.staged_menu_expose(str(tmp_path)) == ""
    assert w.staged_default_settings(str(tmp_path)) == {}


def test_no_project_folder_stages_nothing_and_says_why(app):
    w = _stern(app)
    w.write_assets_var.set("")
    assert w._settings_stage_menu_expose("AD_ALLOW_TOPPER_CHEATS") is False
    assert "project folder" in w._settings_status.cget("text")
