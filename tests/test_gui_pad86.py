"""PAD-86 — how much of a Compare change list the tab is willing to show.

"Would it be possible to display more than the first 12 entries for each
asset category in the Compare tab results?  (Having 25 or 50 entries would be
much more comfortable.)"  He was reading a build that renumbered thousands of
sounds through a dozen-row window.

The report is no longer truncated by the plugin (test_stern_compare.py), so
everything here is about the render: the "Rows per list" setting caps each
listed group, the leftover line opens THAT group, and Copy Report is the way
out to all of it.  Driven through the web UI's Compare service
(webui/tabs/compare.py).
"""

from pinball_decryptor.core.image_info import group_rows
from pinball_decryptor.webui.tabs.compare import (normalize_row_limit,
                                                  row_limit_value)
from tests.webui_harness import web_app


def _svc(w):
    return w.window.service("compare")


def _moved(n):
    """A Sounds section with one *n*-entry "Moved" group, like a build that
    renumbered its whole sound directory."""
    rows = [("Decoded sounds", "%d (unchanged)" % n), ("Moved", "%d:" % n)]
    rows += [("", "idx%04d.wav  ->  idx%04d.wav" % (i, n - i),
              {"side": "B", "disk": "x%d.wav" % i, "name": "x%d.wav" % i})
             for i in range(n)]
    return [("Sounds", rows)]


def _values(w):
    """The Details cell of every row under a section header."""
    return [r["details"] for r in w.state("compare")["rows"]
            if r["kind"] != "section"]


def _per_section(w):
    counts = {}
    for r in w.state("compare")["rows"]:
        if r["kind"] != "section":
            counts[r["sec"]] = counts.get(r["sec"], 0) + 1
    return counts


def _render(w, sections, limit):
    svc = _svc(w)
    w.run(svc.compare_limit_var.set, limit)
    w.run(svc.render, sections)
    return svc


# ---------------------------------------------------------------------------
# Grouping — the report's own shape
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
    assert normalize_row_limit("25") == "25"
    assert normalize_row_limit("all") == "All"
    assert normalize_row_limit(None) == "50"
    assert normalize_row_limit("900") == "50"
    assert row_limit_value("All") is None
    assert row_limit_value("100") == 100


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------

def test_the_setting_decides_how_many_of_a_group_are_listed(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _render(w, _moved(545), "12")

        shown = _values(w)
        # count row + 12 entries + the leftover line
        assert len(shown) == 1 + 1 + 12 + 1
        assert shown[-1] == "… and 533 more — double-click to list them"

        # 50 was what he asked for, and it costs a repaint, not a card read.
        w.call("compare.set_limit", "50")
        shown = _values(w)
        assert len(shown) == 1 + 1 + 50 + 1
        assert shown[-1] == "… and 495 more — double-click to list them"


def test_all_lists_every_entry_and_leaves_no_leftover_line(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _render(w, _moved(545), "All")
        assert len(_values(w)) == 1 + 1 + 545
        assert not svc._more
        # And every listed row still opens the sound it names.
        assert len(svc._refs) == 545


def test_the_leftover_line_opens_that_group_and_nothing_else(tmp_path):
    """Two long lists, one click: the other one stays folded.  A report can
    hold several thousand-entry groups, and expanding all of them because the
    user wanted to read one is how the row he was looking at ends up
    somewhere else entirely."""
    with web_app(tmp_path, mfr="stern") as w:
        sections = _moved(60) + [("Images", [("Modified", "40:")] +
                                 [("", "gfx/%d.png" % i) for i in range(40)])]
        svc = _render(w, sections, "12")

        assert len(svc._more) == 2
        rid = next(i for i, key in svc._more.items() if key[0] == 0)
        assert w.call("compare.expand", rid) is True

        counts = _per_section(w)
        assert counts[0] == 1 + 1 + 60          # opened
        assert counts[1] == 1 + 12 + 1          # still folded


def test_the_leftover_line_is_not_mistaken_for_a_file(tmp_path):
    """It carries no ref, so it must never reach the open path."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _render(w, _moved(20), "12")
        rid = next(iter(svc._more))
        assert rid not in svc._refs


def test_a_new_report_starts_folded_again(tmp_path):
    """What the user opened on the last pair of cards says nothing about
    this one."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _render(w, _moved(40), "12")
        w.call("compare.expand", next(iter(svc._more)))
        assert not svc._more

        w.run(svc.render, _moved(40))
        assert len(svc._more) == 1


def test_the_choice_is_persisted(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("compare.set_limit", "100")
        assert w.app._settings.get("compare_row_limit") == "100"


def test_copy_report_copies_every_row_not_the_visible_ones(tmp_path):
    """The way out to all 3,968 of them: a text report is scrollable and
    searchable in a way the list is not."""
    with web_app(tmp_path, mfr="stern") as w:
        _render(w, _moved(545), "12")
        text = w.call("compare.copy_report")

        assert w.app.root._clip == text
        assert "idx0000.wav" in text and "idx0544.wav" in text
        assert "more" not in text
        assert text.count("->") == 545
