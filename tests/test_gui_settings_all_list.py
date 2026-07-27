"""GUI guards for the Defaults tab's read-only "All settings" list (peanuts).

Covers what the list promises: every setting is listed with the machine's own
caption, the Menu column separates the three cases, the filter leaves only what
the Adjustments menu can't reach, and a build whose menu couldn't be read says
so instead of flagging anything.
"""
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
    return {"id": adj_id, "name": "AD_X", "label": label, "default": default,
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
    assert by_label["FREE PLAY"][2] == "Adjustments"
    assert by_label["MASTER VOLUME SETTING"][2] == "Service menu"
    assert by_label["THIS IS THE WAY DEBUG"][2] == "Debug"
    # A 0/1 setting reads as Off/On, not as a bare number.
    assert by_label["FREE PLAY"][0] == "Off"
    assert by_label["FREE PLAY"][1] == "off / on"
    assert by_label["MASTER VOLUME SETTING"][1] == "0 - 64"


def test_filter_leaves_only_what_the_adjustments_menu_cannot_reach(app):
    w = _stern(app)
    _fill(w, ROWS)
    w._settings_hidden_only.set(True)
    w._settings_fill_all_tree()
    got = [w._settings_all_tree.item(k, "values")[2]
           for k in w._settings_all_tree.get_children()]
    assert sorted(got) == ["Debug", "Debug", "Service menu"]
    assert "3 listed" in w._settings_all_legend.cget("text")


def test_unreadable_menu_flags_nothing_and_says_so(app):
    """James Bond 60th's shape: statuses is None, so no row may claim a
    verdict — the complement of a half-read menu is not a fact."""
    w = _stern(app)
    rows = [dict(r, status=None) for r in ROWS]
    got = _fill(w, rows)
    assert [v[2] for _t, v in got] == ["", "", "", ""]
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
