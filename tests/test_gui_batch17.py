"""GUI guards for monkeybug batch 17 (the lost-audio post-mortem batch).

Covers: the folder-mismatch warning keeping a real folder name across
invalidate_asset_scans (no more "(unknown)"), the Defaults tab's staged
Apply-at-Next-Build flow, and the honest preview labels for slots that are
already changed on disk.
"""

import os

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)


pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]


class _Slot:
    def __init__(self, rel, abs_path=None):
        self.rel_path = rel
        self.abs_path = abs_path or os.path.join("C:\\nope", rel)
        self.duration = 1.0
        self.info = None
        self.probed = True

    def duration_str(self):
        return "0:01.000"

    def format_summary(self):
        return "WAV 44.1kHz mono"


def _stern(app):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update(); app.root.update()
    return app.window


# ---- folder-mismatch warning survives invalidate_asset_scans --------------

def test_mismatch_warning_names_folder_after_invalidate(app, tmp_path):
    """invalidate_asset_scans (after an Extract) clears the scan stamps but
    not the in-memory assignments — the Build/Export mismatch check must
    still name the folder they were made against, not "(unknown)"
    (monkeybug's export warning), and must treat the SAME folder as a
    match."""
    w = _stern(app)
    old = str(tmp_path / "old_extract"); os.makedirs(old)
    new = str(tmp_path / "new_extract"); os.makedirs(new)
    rep = tmp_path / "logo_replacement.png"
    rep.write_bytes(b"png")

    w._image_slots_by_rel = {"images/logo.png": _Slot("images/logo.png")}
    w._image_assignments = {"images/logo.png": str(rep)}
    w._image_scan_dir = old

    w.invalidate_asset_scans()                 # what Extract-completion does
    assert w._image_scan_dir == ""

    out = w.replacement_folder_mismatches(new)
    assert out == [("image", 1, old)], \
        "the warning must name the real folder the assignment was made for"
    assert w.replacement_folder_mismatches(old) == [], \
        "same-folder (re-extract) must not warn"


# ---- Defaults tab: staged Apply-at-Next-Build flow ------------------------

def _settings_form(w):
    class _FakeTable:
        node = "SYS"
    w._settings_table = _FakeTable()
    rows = [
        {"name": "AD_FREE_PLAY", "label": "Free Play", "kind": "toggle",
         "help": "", "default": 0, "min": 0, "max": 1},
        {"name": "AD_SOUND_MASTER_VOLUME_SETTING", "label": "Master Volume",
         "kind": "number", "help": "", "default": 64, "min": 0, "max": 64},
    ]
    w._settings_build_form(rows)
    return {r["name"]: r for r in w._settings_rows}


def test_settings_stage_clear_roundtrip(app, tmp_path):
    from pinball_decryptor.core import staged_changes

    w = _stern(app)
    assets = str(tmp_path / "extract"); os.makedirs(assets)
    w.write_assets_var.set(assets)
    by = _settings_form(w)

    assert str(w._settings_stage_btn["state"]) == "normal"
    assert str(w._settings_clear_staged_btn["state"]) == "disabled"

    by["AD_FREE_PLAY"]["var"].set(1)
    by["AD_SOUND_MASTER_VOLUME_SETTING"]["var"].set(40)
    w._settings_stage()

    # Staged into the folder's sidecar, in internal units, other keys intact.
    assert w.staged_default_settings(assets) == {
        "AD_FREE_PLAY": 1, "AD_SOUND_MASTER_VOLUME_SETTING": 40}
    assert str(w._settings_clear_staged_btn["state"]) == "normal"
    assert "(2)" in str(w._settings_clear_staged_btn["text"])

    # Staging must not wipe the Replace tabs' sections of the sidecar.
    data = staged_changes.load(assets)
    data["audio"] = {"audio/a.wav": "C:\\rep.wav"}
    staged_changes.save(assets, data)
    by["AD_FREE_PLAY"]["var"].set(1)
    w._settings_stage()
    data = staged_changes.load(assets)
    assert data["audio"] == {"audio/a.wav": "C:\\rep.wav"}
    assert "settings" in data

    w._settings_clear_staged()
    assert w.staged_default_settings(assets) == {}
    assert staged_changes.load(assets)["audio"] == {
        "audio/a.wav": "C:\\rep.wav"}
    assert str(w._settings_clear_staged_btn["state"]) == "disabled"


def test_settings_stage_without_changes_stages_nothing(app, tmp_path):
    w = _stern(app)
    assets = str(tmp_path / "extract2"); os.makedirs(assets)
    w.write_assets_var.set(assets)
    _settings_form(w)
    w._settings_stage()                          # nothing edited
    assert w.staged_default_settings(assets) == {}


def test_staged_default_settings_ignores_garbage(app, tmp_path):
    from pinball_decryptor.core import staged_changes

    w = _stern(app)
    assets = str(tmp_path / "extract3"); os.makedirs(assets)
    staged_changes.save(assets, {"settings": {"AD_X": "12", "AD_Y": "nope"}})
    assert w.staged_default_settings(assets) == {"AD_X": 12}
    staged_changes.save(assets, {"settings": ["not", "a", "dict"]})
    assert w.staged_default_settings(assets) == {}


# ---- honest preview labels for changed-on-disk slots ----------------------

def test_image_preview_header_honest_without_snapshot(app, tmp_path):
    """A changed-on-disk slot with no .orig snapshot holds replacement bytes:
    the left pane must not call them "Original" (monkeybug read his imported
    logo as a lost mod).  With a snapshot the true original is shown and the
    header stays "Original"."""
    w = _stern(app)
    assets = str(tmp_path / "x"); os.makedirs(assets)
    rel = "images/logo.png"
    w._image_scan_dir = assets
    w._image_slots_by_rel = {rel: _Slot(rel)}
    w._image_changed_on_disk = {rel}

    w._image_render_preview(rel)
    assert w._image_hdr_orig["text"] == "Current file (already modified)"

    # Drop a snapshot in place — the header goes back to "Original".
    snap = os.path.join(assets, ".orig", "images")
    os.makedirs(snap)
    with open(os.path.join(snap, "logo.png"), "wb") as f:
        f.write(b"png")
    w._image_render_preview(rel)
    assert w._image_hdr_orig["text"] == "Original"

    # An unchanged slot is always plain "Original".
    w._image_changed_on_disk = set()
    w._image_current_rel = None
    w._image_render_preview(rel)
    assert w._image_hdr_orig["text"] == "Original"


def test_audio_pane_title_honest_without_snapshot(app, tmp_path):
    w = _stern(app)
    assets = str(tmp_path / "y"); os.makedirs(assets)
    rel = "audio/idx0001.wav"
    w._audio_scan_dir = assets
    w._audio_slots_by_rel = {rel: _Slot(rel)}     # abs_path doesn't exist
    w._audio_changed_on_disk = {rel}

    w._audio_load_track(rel)
    assert w._audio_pane_orig.base_title == "Current file (already modified)"

    w._audio_changed_on_disk = set()
    w._audio_current_rel = None
    w._audio_load_track(rel)
    assert w._audio_pane_orig.base_title == "Original"
