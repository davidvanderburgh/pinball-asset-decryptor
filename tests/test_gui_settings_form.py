"""Guards for the Defaults tab's editable settings form (a tester b23).

The batch-23 report: two settings he had never opened were staged for the next
Build while he typed a player name, and the log said so again on every
keystroke without naming a single value.  The cause was Stern shipping a
default OUTSIDE the range the same descriptor declares (Led Zeppelin 1.22's
ELECTRIC MAGIC FRENZY / MULTIBALL champions default to 2,000,000 against a
minimum of 5,000,000), which the form clamped and then read back as an edit.

Also covers what the form now promises about arrangement: score adjustments
live under High Scores whether or not the ELF carries a name record for them,
and the rest are drawn under their group heading.

Driven through the web UI's Defaults service (webui/tabs/defaults.py).
"""
from pinball_decryptor.webui.tabs.defaults import range_text
from tests.webui_harness import web_app


def _row(name, label, group, default, lo, hi, kind="number", status=""):
    return {"name": name, "label": label, "kind": kind, "help": "",
            "scale": 1, "labels": None, "group": group, "status": status,
            "default": default, "min": lo, "max": hi, "step": 1}


# One in-range setting, one whose shipped default is below its own minimum
# (the Led Zeppelin shape), and one champion score with no name record.
ROWS = [
    _row("AD_FREE_PLAY", "Free Play", "Game", 0, 0, 1, kind="toggle"),
    _row("AD_SOUND_MASTER_VOLUME_SETTING", "Master Volume", "Sound",
         64, 0, 64, status="service"),
    _row("AD_BLACK_DOG_CHAMPION", "Black Dog Champion", "High scores",
         10_000_000, 5_000_000, 1_000_000_000),
    _row("AD_ELECTRIC_MAGIC_FRENZY_CHAMPION", "Electric Magic Frenzy Champion",
         "High scores", 2_000_000, 5_000_000, 1_000_000_000),
]


def _build(w, rows=ROWS):
    svc = w.window.service("defaults")

    def _do():
        svc._table = object()          # only truthiness is used here
        svc._hstd = None               # no name records in this fixture
        svc._every = []
        svc._build_form([dict(r) for r in rows])
    w.run(_do)
    return svc


def _changes(w, svc):
    return w.run(svc._changes)


def test_a_default_outside_its_own_range_is_not_an_edit(tmp_path):
    """The whole batch-23 bug in one line: nothing was touched, so nothing is
    staged — not even the row the firmware ships out of range."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _build(w)
        assert _changes(w, svc) == {}


def test_editing_one_row_stages_only_that_row(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _build(w)
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        assert _changes(w, svc) == {"AD_FREE_PLAY": 1}


def test_out_of_range_row_still_edits_and_clamps_into_range(tmp_path):
    """It is editable like any other; the value written is pulled into the
    range the firmware itself declares, because patched_bytes rejects
    anything else."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _build(w)
        name = "AD_ELECTRIC_MAGIC_FRENZY_CHAMPION"
        w.call("defaults.set_value", name, 3_000_000)   # still under 5,000,000
        assert _changes(w, svc) == {name: 5_000_000}
        default = next(r for r in svc._rows if r["name"] == name)["default"]
        w.call("defaults.set_value", name, default)   # back to the card's own
        assert _changes(w, svc) == {}


def test_reset_fields_does_not_introduce_a_change(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _build(w)
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        w.call("defaults.reset")
        assert _changes(w, svc) == {}


def test_range_names_a_default_the_firmware_ships_out_of_range():
    rows = {r["name"]: r for r in ROWS}
    txt = range_text(rows["AD_ELECTRIC_MAGIC_FRENZY_CHAMPION"])
    assert "outside its own range" in txt and "2,000,000" in txt
    assert "outside" not in range_text(rows["AD_BLACK_DOG_CHAMPION"])


def _form_labels(w):
    return [it["label"] for it in w.state("defaults")["form"]]


def test_score_rows_leave_the_settings_grid_for_high_scores(tmp_path):
    """Every champion belongs with the board, including the ones the ELF has
    no initials/player-name record for (a tester's red circle)."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _build(w)
        hs = w.state("defaults")["hs"]
        # drawn inside the High Scores block, score-only
        assert "Black Dog Champion" in [it["display"] for it in hs
                                        if it["type"] == "score"]
        assert "Black Dog Champion" not in _form_labels(w)
        # Registered as an ordinary row, so staging/presets/Reset still reach
        # it.
        assert any(r["name"] == "AD_BLACK_DOG_CHAMPION" for r in svc._rows)


def test_group_headings_are_drawn(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _build(w)
        groups = [it["label"] for it in w.state("defaults")["form"]
                  if it["type"] == "group"]
        assert "Game" in groups and "Sound" in groups


def _logging(w, svc, monkeypatch):
    def _adopt():
        svc._logged = svc._log_state()      # adopt the loaded state
    w.run(_adopt)
    lines = []
    monkeypatch.setattr(svc, "log", lambda msg, *_a, **_k: lines.append(msg))
    return lines


def test_log_names_the_setting_and_both_values(tmp_path, monkeypatch):
    """a tester: "the log might be more useful if it states the previous
    value and the new value"."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _build(w)
        lines = _logging(w, svc, monkeypatch)
        w.call("defaults.set_value", "AD_SOUND_MASTER_VOLUME_SETTING", 48)
        w.run(svc._flush_log)
        assert len(lines) == 1
        assert "Master Volume" in lines[0]
        assert "64" in lines[0] and "48" in lines[0]


def test_log_says_when_a_field_goes_back_to_the_card_value(tmp_path,
                                                           monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _build(w)
        lines = _logging(w, svc, monkeypatch)
        w.call("defaults.set_value", "AD_SOUND_MASTER_VOLUME_SETTING", 48)
        w.run(svc._flush_log)
        w.call("defaults.set_value", "AD_SOUND_MASTER_VOLUME_SETTING", 64)
        w.run(svc._flush_log)
        assert "no longer staged" in lines[-1]


def test_log_stays_quiet_when_nothing_moved(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _build(w)
        lines = _logging(w, svc, monkeypatch)
        w.run(svc._flush_log)
        w.run(svc._flush_log)
        assert lines == []
