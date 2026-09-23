"""Guards for the Defaults tab's "All settings" list (a tester).

Covers what the list promises: every setting is listed with the machine's own
caption, the Menu column separates the three cases, the filter leaves only what
the Adjustments menu can't reach, and a build whose menu couldn't be read says
so instead of flagging anything.

Then the two things a tester asked for on top of it — setting the default of a
setting the curated form doesn't draw (including the hidden ones), and staging
the firmware patch that makes the machine's own menu show them.

Driven through the web UI's Defaults service (webui/tabs/defaults.py); the
list is the ``all`` state the page draws.
"""
import json
import os

from tests.webui_harness import web_app


def _svc(w):
    return w.window.service("defaults")


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
    svc = _svc(w)

    def _do():
        svc._all_rows = list(rows)
        svc._fill_all()
    w.run(_do)
    return list(w.state("defaults")["all"])


def _by_label(got):
    return {o["caption"].split("  (")[0]: o for o in got}


def test_lists_every_setting_with_caption_id_and_menu_column(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        got = _fill(w, ROWS)
        assert len(got) == len(ROWS)
        texts = [o["caption"] for o in got]
        # The machine's own caption, plus the id a tester cross-references
        # against.
        assert "ALLOW TOPPER CHEATS  (0xD4)" in texts
        by_label = _by_label(got)
        assert by_label["FREE PLAY"]["menu"] == "Adjustments"
        assert by_label["MASTER VOLUME SETTING"]["menu"] == "Service menu"
        assert by_label["THIS IS THE WAY DEBUG"]["menu"] == "Debug"
        # A 0/1 setting reads as Off/On, not as a bare number.
        assert by_label["FREE PLAY"]["value"] == "Off"
        assert by_label["FREE PLAY"]["range"] == "off / on"
        assert by_label["MASTER VOLUME SETTING"]["range"] == "0 - 64"
        # Nothing edited yet, so the "New default" column is empty throughout.
        assert {o["new"] for o in got} == {""}


def test_filter_leaves_only_what_the_adjustments_menu_cannot_reach(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _fill(w, ROWS)
        w.call("ui.set", "defaults", "hidden_only", True)
        w.drain()
        got = [o["menu"] for o in w.state("defaults")["all"]]
        assert sorted(got) == ["Debug", "Debug", "Service menu"]
        assert "3 listed" in w.state("defaults")["all_legend"]


def test_unreadable_menu_flags_nothing_and_says_so(tmp_path):
    """James Bond 60th's shape: statuses is None, so no row may claim a
    verdict — the complement of a half-read menu is not a fact."""
    with web_app(tmp_path, mfr="stern") as w:
        rows = [dict(r, status=None) for r in ROWS]
        got = _fill(w, rows)
        assert [o["menu"] for o in got] == ["", "", "", ""]
        legend = w.state("defaults")["all_legend"]
        assert "couldn't be read" in legend
        assert "Debug" not in legend


def test_clearing_the_form_takes_the_list_away(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _fill(w, ROWS)
        w.run(_svc(w)._clear_form)
        assert w.state("defaults")["all"] == []
        assert w.state("defaults")["all_total"] == 0


def test_empty_list_leaves_no_stale_legend(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _fill(w, ROWS)
        got = _fill(w, [])
        assert got == []
        assert w.state("defaults")["all_legend"] == ""


# ---------------------------------------------------------------------------
# Editing a setting the curated form doesn't draw (a tester: "write ... these
# hidden/debug values").
# ---------------------------------------------------------------------------

def _editable(w, folder, rows=ROWS, plan=None):
    """A loaded-looking tab whose staged changes land in *folder*."""
    svc = _svc(w)
    folder.mkdir(exist_ok=True)

    def _do():
        w.window.write_assets_var.set(str(folder))
        svc._table = object()          # only its not-None-ness is used
        svc._every = list(rows)
        svc._menu_plan = plan
        svc._all_rows = list(rows)
        svc._fill_all()
    w.run(_do)
    return svc


def _item(w, label):
    return next(o for o in w.state("defaults")["all"]
                if o["caption"].startswith(label))


def _staged(folder):
    p = os.path.join(str(folder), ".staged_changes.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_editing_a_hidden_setting_stages_it_and_shows_it_in_the_list(
        tmp_path):
    folder = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _editable(w, folder)
        assert w.call("defaults.edit_apply", "AD_ALLOW_TOPPER_CHEATS", 1)
        # Staged under the adjustment's own name, in the firmware's units.
        assert _staged(folder)["settings"] == {"AD_ALLOW_TOPPER_CHEATS": 1}
        # ...and the list says so, without losing the card's own value.
        vals = _item(w, "ALLOW TOPPER CHEATS")
        assert (vals["value"], vals["new"]) == ("Off", "On")
        assert _item(w, "FREE PLAY")["new"] == ""


def test_an_edited_setting_reports_itself_in_the_log(tmp_path, monkeypatch):
    """The list has no field to leave, so the edit has to narrate itself —
    and the FIRST edit after a load counts (it used to be swallowed as
    "the first look at this card")."""
    folder = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _editable(w, folder)
        w.run(svc._apply_staged_overlay)
        lines = []
        monkeypatch.setattr(svc, "log",
                            lambda msg, *a, **k: lines.append(msg))
        w.call("defaults.edit_apply", "AD_THIS_IS_THE_WAY_DEBUG", 1)
        assert any("THIS IS THE WAY DEBUG" in ln and "staged" in ln
                   for ln in lines), lines


def test_back_to_the_card_value_unstages_it(tmp_path):
    folder = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _editable(w, folder)
        w.call("defaults.edit_apply", "AD_ALLOW_TOPPER_CHEATS", 1)
        assert _staged(folder).get("settings")
        w.call("defaults.edit_apply", "AD_ALLOW_TOPPER_CHEATS", None, True)
        assert not _staged(folder).get("settings")
        assert _item(w, "ALLOW TOPPER CHEATS")["new"] == ""


def test_staged_edits_come_back_when_the_card_is_reloaded(tmp_path):
    """A setting the curated form doesn't draw still gets its row back, or
    the next Build would bake in a value the tab no longer shows."""
    folder = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _editable(w, folder)
        from pinball_decryptor.core import staged_changes
        staged_changes.save(str(folder),
                            {"settings": {"AD_ALLOW_TOPPER_CHEATS": 1}})
        w.run(svc._build_form, [])        # no curated rows for this build
        assert _item(w, "ALLOW TOPPER CHEATS")["new"] == "On"
        assert w.window.staged_default_settings(str(folder)) == {
            "AD_ALLOW_TOPPER_CHEATS": 1}


# ---------------------------------------------------------------------------
# Opening the machine's own menu up to them ("...and activate").
# ---------------------------------------------------------------------------

PLAN = {"first": 0x7F, "last": 0xD2, "call": 0, "off": 0, "form": "mov",
        "candidates": [{"id": 0xD3, "name": "AD_THIS_IS_THE_WAY_DEBUG"},
                       {"id": 0xD4, "name": "AD_ALLOW_TOPPER_CHEATS"}]}


def test_the_menu_button_follows_whether_this_build_can_be_widened(tmp_path):
    folder = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _editable(w, folder)
        w.run(svc._build_form, [])
        assert w.state("defaults")["menu_enabled"] is False

        def _plan():
            svc._menu_plan = PLAN
        w.run(_plan)
        w.run(svc._build_form, [])
        assert w.state("defaults")["menu_enabled"] is True


def test_menu_widening_stages_by_name_and_says_so(tmp_path):
    folder = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _editable(w, folder, plan=PLAN)
        assert w.call("defaults.menu_apply", "AD_ALLOW_TOPPER_CHEATS")
        # By NAME, never by id: the same id means something else in another
        # build.
        assert _staged(folder)["menu_expose_through"] == \
            "AD_ALLOW_TOPPER_CHEATS"
        assert w.window.staged_menu_expose(str(folder)) == \
            "AD_ALLOW_TOPPER_CHEATS"
        w.run(svc._apply_staged_overlay)
        assert "ALLOW TOPPER CHEATS" in w.state("defaults")["status"]


def test_reset_fields_clears_the_menu_widening_too(tmp_path):
    folder = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _editable(w, folder, plan=PLAN)
        w.call("defaults.menu_apply", "AD_ALLOW_TOPPER_CHEATS")
        w.call("defaults.edit_apply", "AD_ALLOW_TOPPER_CHEATS", 1)
        w.call("defaults.reset")
        assert w.window.staged_menu_expose(str(folder)) == ""
        assert w.window.staged_default_settings(str(folder)) == {}


def test_no_project_folder_stages_nothing_and_says_why(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.run(w.window.write_assets_var.set, "")
        assert w.run(svc._stage_menu_expose,
                     "AD_ALLOW_TOPPER_CHEATS") is False
        assert "project folder" in w.state("defaults")["status"]
