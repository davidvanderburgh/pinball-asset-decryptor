"""Feedback batch 35 — a mod pack imported into the wrong card's extract.

The tester extracted his Pro card into a new folder and imported the pack he
had exported from his LE project.  The import wrote all 232 files; only 23 of
them were files the Pro card has, so the other 209 sat in the folder as slots
no build could ever use — his Audio tab showed 750 slots for a 549-sound card,
each phantom row marked "changed on disk" and previewing his own mod as the
card's original.  See tests/test_modpack_export.py for the import itself; this
file covers the two window-level pieces:

* the Images tab dropped its stale preview only when a scan LANDED, so a rescan
  that takes minutes left the previous file's art sitting over an emptied list
  ("it was scanning but still had the artifact preview from the last time I was
  in this tab");
* nothing re-read the folder's staged settings after an import, so Defaults
  kept showing the card's stock values even once the pack's had been merged in.
"""

import os

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
    app.root.update(); app.root.update()
    return app.window


def test_image_scan_clears_the_previous_preview_at_the_start(
        app, tmp_path, monkeypatch):
    import threading

    w = _stern(app)
    assets = str(tmp_path / "extract")
    os.makedirs(os.path.join(assets, "images"))
    w.write_assets_var.set(assets)

    # Pretend a row is loaded, the way it is when the tab is left and returned
    # to: header retitled, current rel set.
    w._image_current_rel = "images/old.png"
    w._image_set_orig_header("Current file (already modified)")
    assert w._image_hdr_orig["text"] != "Original"

    # Don't let the real walk run — the clearing must happen before it.
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda s: None})())
    w._scan_image_slots_async()

    assert w._image_current_rel is None
    assert w._image_hdr_orig["text"] == "Original"


def test_reloading_the_tabs_re_reads_the_staged_defaults(app, monkeypatch):
    """A mod-pack import merges the pack's Defaults into the folder sidecar,
    which is the same file the Defaults form overlays — but only when the form
    is (re)built, so the tab kept showing stock until the app was restarted."""
    w = _stern(app)
    called = []
    monkeypatch.setattr(w, "_rescan_all_assets_tabs", lambda: None)
    monkeypatch.setattr(w, "_settings_apply_staged_overlay",
                        lambda: called.append(True))
    w.reload_assets_tabs()
    assert called == [True]


# ---------------------------------------------------------------------------
# The two follow-ups from the same thread: the count line has to admit the
# on-disk diff is still running, and a Replacement pane with nothing to show
# has to say why.  Both are plain-attribute methods, so duck-typed stubs
# exercise them (the batch 34 approach) rather than a Tk window.
# ---------------------------------------------------------------------------

from pinball_decryptor.core import checksums, staged_originals  # noqa: E402
from pinball_decryptor.gui.main_window import (_CHANGE_SCAN_NOTE,  # noqa: E402
                                               MainWindow)


class _Var:
    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class _NoteStub:
    _mark_change_scan = MainWindow._mark_change_scan
    _change_scan_note = MainWindow._change_scan_note

    def __init__(self, text="11677 images, 0 changed"):
        self._change_scan_running = set()
        self.image_status_var = _Var(text)


def test_count_line_admits_the_change_diff_is_still_running():
    """The slot scan lands long before the diff that MD5s every slot behind it
    (minutes for 11 677 images on a share), and the tab claimed "0 changed"
    the whole time — the tester switched tabs and back to shake it loose."""
    me = _NoteStub()
    me._mark_change_scan("image", True)
    assert me.image_status_var.get().endswith(_CHANGE_SCAN_NOTE)
    assert me._change_scan_note("image") == _CHANGE_SCAN_NOTE
    me._mark_change_scan("image", False)
    assert me.image_status_var.get() == "11677 images, 0 changed"
    assert me._change_scan_note("image") == ""


def test_marking_the_same_scan_twice_appends_one_note():
    me = _NoteStub()
    me._mark_change_scan("image", True)
    me._mark_change_scan("image", True)
    assert me.image_status_var.get().count(_CHANGE_SCAN_NOTE) == 1


def test_the_change_scan_note_is_per_kind():
    me = _NoteStub()
    me.audio_status_var = _Var("0 of 750 slots changed")
    me._mark_change_scan("image", True)
    assert me.audio_status_var.get() == "0 of 750 slots changed"
    assert me._change_scan_note("audio") == ""


def test_an_empty_tab_gets_no_note():
    """A tab with no slots has a blank status line, and "still checking" alone
    would read as a scan about to fill it."""
    me = _NoteStub(text="")
    me._mark_change_scan("image", True)
    assert me.image_status_var.get() == ""


class _PaneStub:
    _rep_pane_empty_text = MainWindow._rep_pane_empty_text
    _slot_changed_on_disk = MainWindow._slot_changed_on_disk
    _slot_not_on_card = MainWindow._slot_not_on_card

    def __init__(self, scan_dir):
        self._audio_scan_dir = scan_dir
        self._audio_changed_on_disk = set()
        self._audio_foreign_rels = set()


_DEFAULT_HINT = "no replacement assigned"


def _one_slot_folder(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "audio"))
    with open(os.path.join(str(tmp_path), "audio", "a.wav"), "wb") as f:
        f.write(b"stock")
    checksums.generate_checksums(str(tmp_path))
    return str(tmp_path)


def test_untouched_slot_keeps_the_plain_replacement_hint(tmp_path):
    me = _PaneStub(_one_slot_folder(tmp_path))
    assert me._rep_pane_empty_text(
        "audio", "audio/a.wav", _DEFAULT_HINT) == _DEFAULT_HINT


def test_changed_slot_without_a_snapshot_says_where_the_change_is(tmp_path):
    """These have the change on the LEFT with no pristine copy to show
    instead, and a bare "no replacement assigned" beside it read as the mod
    having been lost ("I assumed the left was always the Stern stock file and
    the right was always the latest replacement")."""
    me = _PaneStub(_one_slot_folder(tmp_path))
    me._audio_changed_on_disk = {"audio/a.wav"}
    text = me._rep_pane_empty_text("audio", "audio/a.wav", _DEFAULT_HINT)
    assert text != _DEFAULT_HINT
    assert "on the left" in text and "next build" in text


def test_changed_slot_with_a_snapshot_keeps_the_plain_hint(tmp_path):
    """With a snapshot the panes already read Original | Replacement, so an
    empty pane here really does mean nothing new is assigned."""
    scan_dir = _one_slot_folder(tmp_path)
    md5 = checksums.read_baseline_any(scan_dir)["audio/a.wav"]
    assert staged_originals.snapshot(scan_dir, "audio/a.wav", md5)
    me = _PaneStub(scan_dir)
    me._audio_changed_on_disk = {"audio/a.wav"}
    assert me._rep_pane_empty_text(
        "audio", "audio/a.wav", _DEFAULT_HINT) == _DEFAULT_HINT


def test_no_row_selected_keeps_the_plain_hint(tmp_path):
    me = _PaneStub(_one_slot_folder(tmp_path))
    assert me._rep_pane_empty_text("audio", None, _DEFAULT_HINT) == _DEFAULT_HINT
