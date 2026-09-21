"""PAD-191 — the Extract tab's card row says which game the card is.

The engine-side probe lives in tests/test_card_identify.py; this file covers
the window: the row only exists for a plugin that can read a connected card,
it shows what the probe found (and why it found nothing), and the ⓘ beside the
dropdown opens the Image Info window on the card rather than refusing it for
not being a file.

The worker half of the probe is deliberately not exercised here — a thread's
``after()`` never runs without a mainloop (see tests/test_gui_audio_rename.py
for the same split), so the tests drive ``_apply_card_identity``, the
main-thread continuation, directly.
"""

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)


pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]

DEVICE = r"\\.\PHYSICALDRIVE9"


def _view(app, key):
    mfr = next(m for m in app._manufacturers if m.key == key)
    app._on_manufacturer_change(mfr)
    app.root.update()
    return app.window


def test_the_card_row_is_packed_only_in_card_mode(app):  # noqa: F811
    w = _view(app, "stern")
    assert w._identify_card_supported() is True
    assert not w._extract_card_row.winfo_manager()   # "From card image" mode

    w.extract_input_source_var.set("ssd")
    w._on_input_source_change("extract")
    app.root.update()
    assert w._extract_card_row.winfo_manager()

    w.extract_input_source_var.set("iso")
    w._on_input_source_change("extract")
    app.root.update()
    assert not w._extract_card_row.winfo_manager()


def test_a_plugin_that_cannot_read_a_card_gets_neither_row_nor_badge(
        app, manufacturers_by_key):  # noqa: F811
    """JJP's Direct medium is a multi-hundred-GB game SSD, not a card the app
    can name — its drive row must stay as it was."""
    if "jjp" not in manufacturers_by_key:
        pytest.skip("JJP plugin not loaded")
    w = _view(app, "jjp")
    assert w._identify_card_supported() is False
    assert not w._extract_drive_info_badge.winfo_manager()

    w.extract_input_source_var.set("ssd")
    w._on_input_source_change("extract")
    app.root.update()
    assert not w._extract_card_row.winfo_manager()


def test_the_info_badge_sits_on_sterns_card_row(app):  # noqa: F811
    w = _view(app, "stern")
    assert w._extract_drive_info_badge.winfo_manager()


def test_the_row_shows_the_game_the_probe_found(app):  # noqa: F811
    w = _view(app, "stern")
    w._card_id_seq = 7
    w._apply_card_identity(7, "Godzilla Pro")
    assert w._extract_card_lbl.cget("text") == "Card: Godzilla Pro"


def test_a_late_answer_for_the_previous_card_is_dropped(app):  # noqa: F811
    """Someone checking a stack of cards swaps them faster than a 32 GB card
    reads; the answer for the one he took out must not land under the one he
    just put in."""
    w = _view(app, "stern")
    w._card_id_seq = 8
    w._apply_card_identity(8, "Jaws Pro")
    w._apply_card_identity(7, "Godzilla Pro")      # the stale worker
    assert w._extract_card_lbl.cget("text") == "Card: Jaws Pro"


def test_nothing_found_without_admin_names_the_reason(app, monkeypatch):  # noqa: F811,E501
    """A blank row reads as "the app can't tell"; the truth on Windows is
    usually that it was never allowed to look."""
    import sys

    w = _view(app, "stern")
    from pinball_decryptor.core import admin
    monkeypatch.setattr(admin, "is_admin", lambda: False)
    monkeypatch.setattr(sys, "platform", "win32")
    w._card_id_seq = 1
    w._apply_card_identity(1, "")
    assert "Administrator" in w._extract_card_lbl.cget("text")


def test_nothing_found_as_admin_says_the_card_was_not_recognised(
        app, monkeypatch):  # noqa: F811
    import sys

    w = _view(app, "stern")
    from pinball_decryptor.core import admin
    monkeypatch.setattr(admin, "is_admin", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    w._card_id_seq = 1
    w._apply_card_identity(1, "")
    text = w._extract_card_lbl.cget("text")
    assert "not recognised" in text and "Administrator" not in text


def test_an_empty_drive_pick_clears_the_row(app):  # noqa: F811
    w = _view(app, "stern")
    w._card_id_seq = 3
    w._apply_card_identity(3, "Godzilla Pro")
    w._identify_card_async("")
    assert w._extract_card_lbl.cget("text") == ""


def test_the_info_window_opens_on_a_card_not_just_a_file(app, monkeypatch):  # noqa: F811,E501
    """The ⓘ used to refuse anything that wasn't ``os.path.isfile`` — which a
    card in a reader never is, and imaging it first is the copy the ticket is
    about avoiding."""
    from pinball_decryptor.gui import main_window as mw

    w = _view(app, "stern")
    shown = []
    monkeypatch.setattr(mw.messagebox, "showerror",
                        lambda *a, **kw: shown.append(a))
    monkeypatch.setattr(mw.messagebox, "showinfo",
                        lambda *a, **kw: shown.append(a))
    # Don't let the real (seconds-long) probe run: the window is what's
    # under test, and collect() is covered in tests/test_card_identify.py.
    monkeypatch.setattr(w, "_info_refresh", lambda *a, **kw: None)

    w.extract_drive_var.set(DEVICE)
    w._open_image_info(w.extract_drive_var)
    assert shown == []
    assert w._info_path == DEVICE
    w._info_reset()


def test_the_info_window_still_refuses_a_path_that_is_neither(
        app, monkeypatch):  # noqa: F811
    from pinball_decryptor.gui import main_window as mw

    w = _view(app, "stern")
    errors = []
    monkeypatch.setattr(mw.messagebox, "showerror",
                        lambda *a, **kw: errors.append(a))
    w.extract_input_var.set(r"C:\nope\not-a-card.raw")
    w._open_image_info(w.extract_input_var)
    assert errors and "File not found" in errors[0][0]
