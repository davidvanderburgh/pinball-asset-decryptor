"""GUI construction smoke tests.

These exercise the picker -> mfr-view navigation flow and per-mfr log
swapping without actually running pipelines.  Skipped when Tk can't
open a display (typical for headless Linux CI without xvfb).
"""

import pytest

from tests.conftest import HAS_DISPLAY


pytestmark = pytest.mark.skipif(
    not HAS_DISPLAY, reason="no Tk display available")


@pytest.fixture
def app():
    """Build an App() instance + tear it down cleanly per-test."""
    from pinball_decryptor.app import App
    a = App()
    a.root.update()
    yield a
    # Cancel every pending after() callback before destroying so the
    # _poll_queue / _check_for_update closures don't fire against a
    # freed Tk interpreter (otherwise we get noisy
    # 'invalid command name "...poll_queue"' stderr at test teardown).
    # _poll_queue reschedules itself every 100ms, so a single sweep
    # can race against the next reschedule -- loop until nothing
    # pending remains.  Note: tk.call("after", "info") returns a TUPLE
    # of strings on most Tk builds (and an empty string on some), so
    # accept either.
    for _ in range(20):
        try:
            pending = a.root.tk.call("after", "info")
        except Exception:
            break
        if not pending:
            break
        if isinstance(pending, str):
            ids = pending.split()
        else:
            ids = list(pending)
        for after_id in ids:
            try:
                a.root.after_cancel(after_id)
            except Exception:
                pass
    a.root.destroy()


def _mfr_view_visible(window):
    """Return True iff the manufacturer working view is currently shown.

    v0.7.11 wrapped ``_mfr_view`` inside a Canvas (for the
    scrollable working-view introduced for the macOS FDA-banner-
    plus-log layout).  Tk's ``winfo_ismapped()`` on a canvas-item
    widget returns 1 the moment the widget is registered via
    ``create_window``, regardless of whether the canvas itself is
    currently visible — so ``_mfr_view.winfo_ismapped()`` is no
    longer a reliable visibility signal.  ``_mfr_view_wrapper``
    is the directly-packed widget and is what actually reflects
    user-visible state.
    """
    return bool(window._mfr_view_wrapper.winfo_ismapped())


def test_app_starts_on_picker(app):
    assert app.window._picker_view.winfo_ismapped()
    assert not _mfr_view_visible(app.window)
    assert app._current_mfr is None


def test_picker_has_all_manufacturer_cards(app):
    """The picker should have one card per registered manufacturer."""
    picker = app.window._picker_view
    assert len(picker._cards) == len(app._manufacturers)


def test_mfr_select_switches_to_mfr_view(app, manufacturers_by_key):
    spooky = manufacturers_by_key["spooky"]
    app._on_manufacturer_change(spooky)
    app.root.update(); app.root.update()
    assert app._current_mfr.key == "spooky"
    assert _mfr_view_visible(app.window)
    assert not app.window._picker_view.winfo_ismapped()


def test_back_returns_to_picker(app, manufacturers_by_key):
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    app._on_back_to_picker()
    app.root.update()
    assert app.window._picker_view.winfo_ismapped()
    assert not _mfr_view_visible(app.window)


def test_per_mfr_log_persists_across_switches(app, manufacturers_by_key):
    """Each mfr keeps its own Text widget; logs survive Back + re-pick."""
    spooky = manufacturers_by_key["spooky"]
    jjp = manufacturers_by_key["jjp"]

    app._on_manufacturer_change(spooky)
    app.root.update()
    app.window.append_log("spooky-test-line", "info")

    app._on_back_to_picker()
    app._on_manufacturer_change(jjp)
    app.root.update()
    app.window.append_log("jjp-test-line", "info")

    # Spooky's log still has its content cached
    spooky_log = app.window._log_widgets["spooky"]["text"].get("1.0", "end-1c")
    jjp_log = app.window._log_widgets["jjp"]["text"].get("1.0", "end-1c")
    assert "spooky-test-line" in spooky_log
    assert "spooky-test-line" not in jjp_log
    assert "jjp-test-line" in jjp_log
    assert "jjp-test-line" not in spooky_log


def test_prereq_indicators_render_for_current_mfr(app, manufacturers_by_key):
    """When a mfr is selected, its prereqs get [?] placeholder labels."""
    spooky = manufacturers_by_key["spooky"]
    app._on_manufacturer_change(spooky)
    app.root.update()
    # Indicator names should match the manufacturer's declared prereqs
    expected_names = {p.name for p in spooky.prerequisites}
    rendered_names = set(app.window._prereq_indicators.keys())
    assert rendered_names == expected_names


def test_manufacturer_picker_alphabetical_order(app):
    displays = [m.display for m in app._manufacturers]
    assert displays == sorted(displays, key=str.lower)


# ---------------------------------------------------------------------------
# BOF update-version date field (capabilities.write_version_date)
# ---------------------------------------------------------------------------

def _seed_bof_assets(tmp_path):
    marker = "# Update check string\n"
    (tmp_path / "updated_bash_profile").write_text(
        marker + "# 2025.06.23 \n", encoding="utf-8")
    (tmp_path / "updated_updatecode").write_text(
        marker + "# 2025.06.20 \n", encoding="utf-8")
    (tmp_path / ".checksums.md5").write_text("", encoding="utf-8")
    return str(tmp_path)


def test_version_field_shown_for_bof_hidden_otherwise(
        app, manufacturers_by_key):
    # winfo_manager() == "pack" means the row is laid out on the Write tab
    # (winfo_ismapped() would read 0 unless that tab is the raised one).
    app._on_manufacturer_change(manufacturers_by_key["bof"])
    app.root.update()
    assert app.window._write_version_frame.winfo_manager() == "pack"

    app._on_back_to_picker()
    app._on_manufacturer_change(manufacturers_by_key["spooky"])
    app.root.update()
    assert app.window._write_version_frame.winfo_manager() == ""


def test_version_field_auto_shows_concrete_date(
        app, manufacturers_by_key, tmp_path):
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["bof"])
    app.root.update()
    w.write_assets_var.set(_seed_bof_assets(tmp_path))
    app.root.update()
    # Auto on by default → entry shows baseline+1, read-only, no override.
    assert w.write_version_auto_var.get() is True
    assert w.write_version_date_var.get() == "2025.06.24"
    assert w.write_version_override() is None
    assert w.write_version_validation_error() is None


def test_version_field_manual_override_and_validation(
        app, manufacturers_by_key, tmp_path):
    w = app.window
    app._on_manufacturer_change(manufacturers_by_key["bof"])
    app.root.update()
    w.write_assets_var.set(_seed_bof_assets(tmp_path))
    app.root.update()

    # Uncheck Auto → manual mode; a too-old date is rejected.
    w.write_version_auto_var.set(False)
    w._on_write_version_auto_toggle()
    w.write_version_date_var.set("2025.06.10")  # older than installed 06.23
    assert w.write_version_validation_error() is not None

    # A newer explicit date validates and is returned as the override.
    w.write_version_date_var.set("2026.01.15")
    assert w.write_version_validation_error() is None
    assert w.write_version_override() == "2026.01.15"

    # Garbage is rejected.
    w.write_version_date_var.set("not-a-date")
    assert w.write_version_validation_error() is not None
