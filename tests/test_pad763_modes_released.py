"""PAD-763: the mode maker is released. Every copy of the app shows the Modes tab for Stern
Spike 2 with no preview code, a Write carries the project's modes, and a code someone
still holds for it says it is no longer needed (core/preview.RELEASED).

The switch's off path, for a feature that is a preview again, keeps its own tests under
the ``preview_modes_off`` fixture (test_preview_switch.py and the rest).
"""
import pytest

from pinball_decryptor.core import preview as P
from tests.mode_examples import form as MX  # noqa: E402
from tests.test_preview_switch import KEYS, TODAY, make_code
from tests.webui_harness import web_app


def test_the_mode_maker_is_on_with_no_code():
    from pinball_decryptor.plugins.stern import mode_write
    assert P.active_features() == frozenset()           # no code loaded
    assert P.enabled("modes") and mode_write.preview_on()
    assert "modes" in P.RELEASED and "modes" not in P.FEATURES
    assert not P.enabled("something-else")


def test_the_modes_tab_shows_for_stern_without_a_code(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["modes"]["visible"]
        assert P.SETTINGS_KEY not in w.app._settings
        ids = [it.get("id") for it in w.state("shell")["settings_items"]]
        assert "preview_features" not in ids
        # every Stern era the picker offers keeps it; another manufacturer never has it
        w.call("ui.pick_manufacturer", "spooky")
        w.drain()
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["modes"]["visible"]


def test_the_write_scan_lists_the_modes_without_a_code(manufacturers_by_key, tmp_path):
    """The Write tab's list names a project's modes as pending, as it did for a tester."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.webui import write_scan
    project = str(tmp_path / "project")
    for _name, spec in MX.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    rows = write_scan.mode_rows(manufacturers_by_key["stern"], project, direct=False)
    assert len(rows) == 2 and all(r[2] == "Pending (Modes)" for r in rows), rows


def test_the_modes_help_shows_without_a_code_and_names_no_preview():
    from pinball_decryptor.webui import help_content as HD
    titles = [t for t, _b in HD.sections_for("Modes")]
    assert "What it's for" in titles and "Asking for more" in titles
    assert "A preview feature" not in titles
    assert not any(t == "Preview features" for t, _b in HD.sections_for("Write"))


def test_a_code_for_the_released_mode_maker_says_it_is_not_needed():
    code = make_code(issued=TODAY)
    with pytest.raises(P.PreviewCodeError, match="in every copy of the app now"):
        P.check(code, TODAY, KEYS)
    # one already stored is listed as no longer needed, and still turns nothing else on
    active, rows = P.judge([code], TODAY, KEYS)
    assert active == frozenset()
    assert rows[0].lines == ["Mode maker: in every copy of the app now, this code is no "
                             "longer needed (code for Test Person)"]
    assert "—" not in rows[0].lines[0]
    assert P.enabled("modes")
