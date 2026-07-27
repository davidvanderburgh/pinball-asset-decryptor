"""GUI guards for the Defaults tab's editable settings form (monkeybug b23).

The batch-23 report: two settings he had never opened were staged for the next
Build while he typed a player name, and the log said so again on every
keystroke without naming a single value.  The cause was Stern shipping a
default OUTSIDE the range the same descriptor declares (Led Zeppelin 1.22's
ELECTRIC MAGIC FRENZY / MULTIBALL champions default to 2,000,000 against a
minimum of 5,000,000), which the form clamped and then read back as an edit.

Also covers what the form now promises about arrangement: score adjustments
live under High Scores whether or not the ELF carries a name record for them,
and the rest are drawn under their group heading.
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


def _build(app, rows=ROWS):
    w = _stern(app)
    w._settings_table = object()          # only truthiness is used here
    w._settings_hstd = None               # no name records in this fixture
    w._settings_every = []
    w._settings_build_form(list(rows))
    app.root.update()
    return w


def test_a_default_outside_its_own_range_is_not_an_edit(app):
    """The whole batch-23 bug in one line: nothing was touched, so nothing is
    staged — not even the row the firmware ships out of range."""
    w = _build(app)
    assert w._settings_changes() == {}


def test_editing_one_row_stages_only_that_row(app):
    w = _build(app)
    row = next(r for r in w._settings_rows if r["name"] == "AD_FREE_PLAY")
    row["var"].set(1)
    assert w._settings_changes() == {"AD_FREE_PLAY": 1}


def test_out_of_range_row_still_edits_and_clamps_into_range(app):
    """It is editable like any other; the value written is pulled into the
    range the firmware itself declares, because patched_bytes rejects
    anything else."""
    w = _build(app)
    row = next(r for r in w._settings_rows
               if r["name"] == "AD_ELECTRIC_MAGIC_FRENZY_CHAMPION")
    row["var"].set(3_000_000)             # still under the 5,000,000 minimum
    assert w._settings_changes() == {
        "AD_ELECTRIC_MAGIC_FRENZY_CHAMPION": 5_000_000}
    row["var"].set(row["default"])        # back to the card's own value
    assert w._settings_changes() == {}


def test_reset_fields_does_not_introduce_a_change(app):
    w = _build(app)
    next(r for r in w._settings_rows
         if r["name"] == "AD_FREE_PLAY")["var"].set(1)
    w._settings_reset()
    assert w._settings_changes() == {}


def test_range_names_a_default_the_firmware_ships_out_of_range(app):
    w = _build(app)
    rows = {r["name"]: r for r in ROWS}
    txt = w._settings_range_text(rows["AD_ELECTRIC_MAGIC_FRENZY_CHAMPION"])
    assert "outside its own range" in txt and "2,000,000" in txt
    assert "outside" not in w._settings_range_text(
        rows["AD_BLACK_DOG_CHAMPION"])


def _form_texts(w):
    """Every label/heading the form drew, in no particular order."""
    out = []
    for child in w._settings_form.winfo_children():
        try:
            out.append(child.cget("text"))
        except Exception:
            pass
    return out


def test_score_rows_leave_the_settings_grid_for_high_scores(app):
    """Every champion belongs with the board, including the ones the ELF has
    no initials/player-name record for (monkeybug's red circle)."""
    w = _build(app)
    texts = _form_texts(w)
    assert "High Scores" in texts          # the block's own heading
    assert "Black Dog Champion" in texts   # drawn inside it, score-only
    # Registered as an ordinary row, so staging/presets/Reset still reach it.
    assert any(r["name"] == "AD_BLACK_DOG_CHAMPION"
               for r in w._settings_rows)


def test_group_headings_are_drawn(app):
    w = _build(app)
    texts = _form_texts(w)
    assert "Game" in texts and "Sound" in texts


def test_log_names_the_setting_and_both_values(app):
    """monkeybug: "the log might be more useful if it states the previous
    value and the new value"."""
    w = _build(app)
    w._settings_logged = w._settings_log_state()      # adopt the loaded state
    lines = []
    w.append_log = lambda msg, *_a, **_k: lines.append(msg)
    next(r for r in w._settings_rows
         if r["name"] == "AD_SOUND_MASTER_VOLUME_SETTING")["var"].set(48)
    w._settings_flush_log()
    assert len(lines) == 1
    assert "Master Volume" in lines[0]
    assert "64" in lines[0] and "48" in lines[0]


def test_log_says_when_a_field_goes_back_to_the_card_value(app):
    w = _build(app)
    w._settings_logged = w._settings_log_state()
    lines = []
    w.append_log = lambda msg, *_a, **_k: lines.append(msg)
    row = next(r for r in w._settings_rows
               if r["name"] == "AD_SOUND_MASTER_VOLUME_SETTING")
    row["var"].set(48)
    w._settings_flush_log()
    row["var"].set(64)
    w._settings_flush_log()
    assert "no longer staged" in lines[-1]


def test_log_stays_quiet_when_nothing_moved(app):
    w = _build(app)
    w._settings_logged = w._settings_log_state()
    lines = []
    w.append_log = lambda msg, *_a, **_k: lines.append(msg)
    w._settings_flush_log()
    w._settings_flush_log()
    assert lines == []
