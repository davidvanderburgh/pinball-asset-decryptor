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
