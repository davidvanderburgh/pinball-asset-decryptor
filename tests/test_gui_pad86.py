"""PAD-86 — how much of a Compare change list the tab is willing to show.

"Would it be possible to display more than the first 12 entries for each
asset category in the Compare tab results?  (Having 25 or 50 entries would be
much more comfortable.)"  He was reading a build that renumbered thousands of
sounds through a dozen-row window.

The report is no longer truncated by the plugin (test_stern_compare.py), so
everything here is about the render: the "Rows per list" setting caps each
listed group, the leftover line opens THAT group, and Copy Report is the way
out to all of it.
"""

import pytest

from pinball_decryptor.core.image_info import group_rows
from pinball_decryptor.gui.main_window import (compare_row_limit_value,
                                               normalize_compare_row_limit)
from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]


def _stern(app, manufacturers_by_key):
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    return app.window


def _moved(n):
    """A Sounds section with one *n*-entry "Moved" group, like a build that
    renumbered its whole sound directory."""
    rows = [("Decoded sounds", "%d (unchanged)" % n), ("Moved", "%d:" % n)]
    rows += [("", "idx%04d.wav  ->  idx%04d.wav" % (i, n - i),
              {"side": "B", "disk": "x%d.wav" % i, "name": "x%d.wav" % i})
             for i in range(n)]
    return [("Sounds", rows)]


def _values(win):
    tree = win._compare_tree
    return [tree.set(iid, "value")
            for section in tree.get_children("")
            for iid in tree.get_children(section)]


# ---------------------------------------------------------------------------
# Grouping — the report's own shape, with no Tk in sight
# ---------------------------------------------------------------------------

def test_a_blank_name_means_an_item_of_the_row_above():
    rows = [("Decoded sounds", "3 (unchanged)"), ("Moved", "2:"),
            ("", "a"), ("", "b"), ("Added", "1:"), ("", "c")]
    assert group_rows(rows) == [
        (("Decoded sounds", "3 (unchanged)"), []),
        (("Moved", "2:"), [("", "a"), ("", "b")]),
        (("Added", "1:"), [("", "c")]),
    ]


def test_a_leading_blank_row_is_kept_not_dropped():
    """The report is never edited on the way to the screen — a row with
    nothing above it to belong to still gets drawn."""
    assert group_rows([("", "orphan")]) == [(("", "orphan"), [])]
    assert group_rows([]) == []


def test_a_hand_edited_setting_falls_back_to_the_default():
    """settings.json is a text file people edit.  A value the dropdown can't
    display would leave the tab showing a number that isn't on its menu."""
    assert normalize_compare_row_limit("25") == "25"
    assert normalize_compare_row_limit("all") == "All"
    assert normalize_compare_row_limit(None) == "50"
    assert normalize_compare_row_limit("900") == "50"
    assert compare_row_limit_value("All") is None
    assert compare_row_limit_value("100") == 100


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------

def test_the_setting_decides_how_many_of_a_group_are_listed(
        app, manufacturers_by_key):
    win = _stern(app, manufacturers_by_key)
    win.compare_limit_var.set("12")
    win._compare_render(_moved(545))

    shown = _values(win)
    # count row + 12 entries + the leftover line
    assert len(shown) == 1 + 1 + 12 + 1
    assert shown[-1] == "… and 533 more — double-click to list them"

    # 50 was what he asked for, and it costs a repaint, not a card read.
    win.compare_limit_var.set("50")
    win._compare_limit_changed()
    shown = _values(win)
    assert len(shown) == 1 + 1 + 50 + 1
    assert shown[-1] == "… and 495 more — double-click to list them"


def test_all_lists_every_entry_and_leaves_no_leftover_line(
        app, manufacturers_by_key):
    win = _stern(app, manufacturers_by_key)
    win.compare_limit_var.set("All")
    win._compare_render(_moved(545))
    assert len(_values(win)) == 1 + 1 + 545
    assert not win._compare_more
    # And every listed row still opens the sound it names.
    assert len(win._compare_refs) == 545


def test_the_leftover_line_opens_that_group_and_nothing_else(
        app, manufacturers_by_key):
    """Two long lists, one click: the other one stays folded.  A report can
    hold several thousand-entry groups, and expanding all of them because the
    user wanted to read one is how the row he was looking at ends up
    somewhere else entirely."""
    win = _stern(app, manufacturers_by_key)
    win.compare_limit_var.set("12")
    sections = _moved(60) + [("Images", [("Modified", "40:")] +
                             [("", "gfx/%d.png" % i) for i in range(40)])]
    win._compare_render(sections)

    assert len(win._compare_more) == 2
    iid = next(i for i, key in win._compare_more.items() if key[0] == 0)
    win._compare_expand_group(iid)

    tree = win._compare_tree
    sounds, images = tree.get_children("")
    assert len(tree.get_children(sounds)) == 1 + 1 + 60   # opened
    assert len(tree.get_children(images)) == 1 + 12 + 1   # still folded


def test_the_leftover_line_is_not_mistaken_for_a_file(app,
                                                      manufacturers_by_key):
    """It carries no ref, so it must never reach the open path."""
    win = _stern(app, manufacturers_by_key)
    win.compare_limit_var.set("12")
    win._compare_render(_moved(20))
    iid = next(iter(win._compare_more))
    assert iid not in win._compare_refs


def test_a_new_report_starts_folded_again(app, manufacturers_by_key):
    """What the user opened on the last pair of cards says nothing about
    this one."""
    win = _stern(app, manufacturers_by_key)
    win.compare_limit_var.set("12")
    win._compare_render(_moved(40))
    win._compare_expand_group(next(iter(win._compare_more)))
    assert not win._compare_more

    win._compare_render(_moved(40))
    assert len(win._compare_more) == 1


def test_the_choice_is_persisted(app, manufacturers_by_key):
    win = _stern(app, manufacturers_by_key)
    win.compare_limit_var.set("100")
    win._compare_limit_changed()
    assert app._settings.get("compare_row_limit") == "100"


def test_copy_report_copies_every_row_not_the_visible_ones(
        app, manufacturers_by_key):
    """The way out to all 3,968 of them: a text report is scrollable and
    searchable in a way the tree is not."""
    win = _stern(app, manufacturers_by_key)
    win.compare_limit_var.set("12")
    win._compare_render(_moved(545))
    win._compare_copy_report()

    text = app.root.clipboard_get()
    assert "idx0000.wav" in text and "idx0544.wav" in text
    assert "more" not in text
    assert text.count("->") == 545
