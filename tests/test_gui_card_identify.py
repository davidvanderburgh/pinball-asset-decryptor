"""PAD-191 — the Extract tab's card row says which game the card is.

The engine-side probe lives in tests/test_card_identify.py; this file covers
the window: the row only exists for a plugin that can read a connected card,
it shows what the probe found (and why it found nothing), and the ⓘ beside the
dropdown opens the Image Info window on the card rather than refusing it for
not being a file.

The worker half of the probe is deliberately not exercised here, so the tests
drive ``_apply_card_identity``, the UI-loop continuation, directly.  Driven
through the web UI's Extract service (webui/tabs/extract.py); the page shows
the card row and its ⓘ while ``identify`` is set and the drive row is up.
"""

import sys

import pytest

from tests.webui_harness import web_app

DEVICE = r"\\.\PHYSICALDRIVE9" if sys.platform == "win32" else "/dev/sdz9"


class _Drive:
    def __init__(self, display, device):
        self.display = display
        self.device_path = device
        self.model = "Card Reader"
        self.size_bytes = 8 * 10 ** 9
        self.mount_label = ""
        self.bus_type = "USB"


@pytest.fixture(autouse=True)
def _no_real_drives(monkeypatch):
    """Card mode enumerates drives; never touch the real ones."""
    from pinball_decryptor.core import drives as drives_mod
    monkeypatch.setattr(drives_mod, "list_physical_drives", lambda: [])
    monkeypatch.setattr(drives_mod, "pick_best_game_ssd",
                        lambda ds, prefer="ssd": (None, None, None))
    monkeypatch.setattr(drives_mod, "visible_drives",
                        lambda ds, prefer="ssd", keep=(): list(ds))


def _svc(w):
    return w.window.service("extract")


def _apply(w, seq, caption):
    svc = _svc(w)
    w.run(svc._apply_card_identity, seq, svc.mfr, caption)


def _set_seq(w, seq):
    svc = _svc(w)

    def _do():
        svc._card_seq = seq
    w.run(_do)


def test_the_card_row_is_packed_only_in_card_mode(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        st = w.state("extract")
        assert st["identify"] is True
        assert st["ssd"] is False                   # "From card image" mode

        w.call("extract.set_source", "ssd")
        w.drain()
        assert w.state("extract")["ssd"] is True

        w.call("extract.set_source", "iso")
        w.drain()
        assert w.state("extract")["ssd"] is False


def test_a_plugin_that_cannot_read_a_card_gets_neither_row_nor_badge(
        tmp_path, manufacturers_by_key):
    """JJP's Direct medium is a multi-hundred-GB game SSD, not a card the app
    can name — its drive row must stay as it was."""
    if "jjp" not in manufacturers_by_key:
        pytest.skip("JJP plugin not loaded")
    with web_app(tmp_path, mfr="jjp") as w:
        assert w.state("extract")["identify"] is False

        w.call("extract.set_source", "ssd")
        w.drain()
        st = w.state("extract")
        assert st["identify"] is False and st["card_line"] == ""


def test_the_info_badge_sits_on_sterns_card_row(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.state("extract")["identify"] is True


def test_the_row_shows_the_game_the_probe_found(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _set_seq(w, 7)
        _apply(w, 7, "Godzilla Pro")
        assert w.state("extract")["card_line"] == "Card: Godzilla Pro"


def test_a_late_answer_for_the_previous_card_is_dropped(tmp_path):
    """Someone checking a stack of cards swaps them faster than a 32 GB card
    reads; the answer for the one he took out must not land under the one he
    just put in."""
    with web_app(tmp_path, mfr="stern") as w:
        _set_seq(w, 8)
        _apply(w, 8, "Jaws Pro")
        _apply(w, 7, "Godzilla Pro")      # the stale worker
        assert w.state("extract")["card_line"] == "Card: Jaws Pro"


def test_nothing_found_without_admin_names_the_reason(tmp_path, monkeypatch):
    """A blank row reads as "the app can't tell"; the truth on Windows is
    usually that it was never allowed to look."""
    from pinball_decryptor.core import admin
    with web_app(tmp_path, mfr="stern") as w:
        monkeypatch.setattr(admin, "is_admin", lambda: False)
        monkeypatch.setattr(sys, "platform", "win32")
        _set_seq(w, 1)
        _apply(w, 1, "")
        assert "Administrator" in w.state("extract")["card_line"]


def test_nothing_found_as_admin_says_the_card_was_not_recognised(
        tmp_path, monkeypatch):
    from pinball_decryptor.core import admin
    with web_app(tmp_path, mfr="stern") as w:
        monkeypatch.setattr(admin, "is_admin", lambda: True)
        monkeypatch.setattr(sys, "platform", "win32")
        _set_seq(w, 1)
        _apply(w, 1, "")
        text = w.state("extract")["card_line"]
        assert "not recognised" in text and "Administrator" not in text


def test_an_empty_drive_pick_clears_the_row(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _set_seq(w, 3)
        _apply(w, 3, "Godzilla Pro")
        w.run(svc._identify_card_async, "")
        assert w.state("extract")["card_line"] == ""


def test_the_info_window_opens_on_a_card_not_just_a_file(tmp_path,
                                                         monkeypatch):
    """The ⓘ used to refuse anything that wasn't ``os.path.isfile`` — which a
    card in a reader never is, and imaging it first is the copy the ticket is
    about avoiding."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        # Don't let the real (seconds-long) probe run: the window is what's
        # under test, and collect() is covered in tests/test_card_identify.py.
        monkeypatch.setattr(svc, "_info_refresh", lambda *a, **kw: None)

        w.run(svc.extract_drive_var.set, DEVICE)
        assert w.call("extract.open_image_info", "drive") is True
        assert w.asked == []
        assert svc._info_path == DEVICE
        w.call("extract.info_close")


def test_the_info_window_still_refuses_a_path_that_is_neither(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "input", r"C:\nope\not-a-card.raw")
        assert w.call("extract.open_image_info", "input") is False
        assert w.asked and w.asked[-1]["title"] == "File not found"
