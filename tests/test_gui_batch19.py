"""GUI guards for batch 19 — folder-scoped projects.

Covers: the field collapse (Input→Original and Project-Folder→assets
mirrors, the derived Build Location and its back-off rules), the Project ▾
header menu, anchor materialization (explicit save + folder-state-written),
auto-load on folder pick, and the archived-project open gate.
"""

import os
import tkinter as tk

import pytest

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

from pinball_decryptor.core import project_file, project_registry


pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]


def _pick(app, key="stern"):
    mfr = next(m for m in app._manufacturers if m.key == key)
    app._on_manufacturer_change(mfr)
    app.root.update(); app.root.update()
    return app.window


# ---- Field collapse -------------------------------------------------------

def test_stock_image_mirrors_to_write_original(app):
    w = _pick(app)
    w.extract_input_var.set(r"C:\stock\game.raw")
    assert w.write_upd_var.get() == r"C:\stock\game.raw"


def test_project_folder_mirrors_to_assets(app):
    w = _pick(app)
    w.extract_output_var.set(r"C:\proj\lz")
    assert w.write_assets_var.get() == r"C:\proj\lz"


def test_build_location_derives_from_project_folder(app, tmp_path):
    w = _pick(app)
    folder = str(tmp_path / "proj")
    os.makedirs(folder)
    w.write_output_var.set("")
    w.extract_output_var.set(folder)
    assert w.write_output_var.get() == os.path.join(folder, "build")
    # Re-pointing the project re-derives (the old derived value is "auto").
    folder2 = str(tmp_path / "proj2")
    os.makedirs(folder2)
    w.extract_output_var.set(folder2)
    assert w.write_output_var.get() == os.path.join(folder2, "build")


def test_custom_build_location_not_clobbered(app, tmp_path):
    w = _pick(app)
    w.write_output_var.set(r"D:\fast\builds")
    w._write_output_auto = ""          # custom — not an auto value
    w.extract_output_var.set(str(tmp_path))
    assert w.write_output_var.get() == r"D:\fast\builds"


def test_legacy_parent_default_is_superseded(app, tmp_path):
    """The old 'parent of the original image' default must lose to the
    project derivation, whichever order the fields were filled."""
    w = _pick(app)
    stock = tmp_path / "imgs" / "game.raw"
    stock.parent.mkdir()
    stock.write_bytes(b"x")
    w.write_output_var.set("")
    w._write_output_auto = ""
    w.extract_input_var.set(str(stock))          # legacy default fills
    assert w.write_output_var.get() == str(stock.parent)
    folder = tmp_path / "proj"
    folder.mkdir()
    w.extract_output_var.set(str(folder))        # derivation supersedes
    assert w.write_output_var.get() == os.path.join(str(folder), "build")


def test_anchor_build_override_honoured_by_derivation(app, tmp_path):
    w = _pick(app)
    folder = str(tmp_path / "proj")
    os.makedirs(folder)
    project_file.save(
        project_file.anchor_path(folder), manufacturer_key="stern",
        paths={}, extract_options={}, build_dir=r"D:\elsewhere\build")
    w.write_output_var.set("")
    w._write_output_auto = ""
    w.extract_output_var.set(folder)
    assert w.write_output_var.get() == os.path.normpath(r"D:\elsewhere\build")


# ---- Project ▾ header menu ------------------------------------------------

def test_project_button_exists_and_menu_builds(app):
    w = _pick(app)
    assert w._project_btn.winfo_manager()        # packed (always visible)
    menu = w._build_project_menu()
    labels = []
    for i in range(menu.index(tk.END) + 1):
        if menu.type(i) in ("command", "cascade"):
            labels.append(menu.entrycget(i, "label"))
    joined = "  ".join(labels)
    for expected in ("New project…", "Open project…", "Save project",
                     "Projects…", "Properties…"):
        assert expected in joined
    assert "Recent projects" in joined


def test_gear_menu_no_longer_lists_projects(app):
    w = _pick(app)
    menu = w._build_settings_menu()
    for i in range(menu.index(tk.END) + 1):
        if menu.type(i) == "command":
            assert "project" not in menu.entrycget(i, "label").lower()


# ---- Materialization + auto-load ------------------------------------------

def test_save_project_writes_anchor_and_registry(app, tmp_path):
    w = _pick(app)
    folder = str(tmp_path / "lz122")
    os.makedirs(folder)
    w.extract_input_var.set(r"C:\stock\lz.raw")
    w.extract_output_var.set(folder)
    app._save_project()
    assert project_file.has_anchor(folder)
    data = project_file.load_anchor(folder)
    assert data["manufacturer"] == "stern"
    assert data["stock_image"] == r"C:\stock\lz.raw"
    folders = [e["folder"] for e in project_registry.entries(app._settings)]
    assert folder in folders


def test_folder_state_written_materializes_once(app, tmp_path):
    w = _pick(app)
    folder = str(tmp_path / "beatles")
    os.makedirs(folder)
    w.extract_output_var.set(folder)
    app._on_folder_state_written(folder)
    assert project_file.has_anchor(folder)
    # Second write: no error, anchor stays (update path).
    app._on_folder_state_written(folder)
    assert project_file.has_anchor(folder)


def test_folder_pick_autoloads_project(app, tmp_path):
    w = _pick(app)
    folder = str(tmp_path / "tmnt159")
    os.makedirs(folder)
    w.extract_input_var.set(r"C:\stock\tmnt.raw")
    w.extract_output_var.set(folder)
    w.transcribe_var.set(True)
    app._save_project()
    # Wander off to a different setup, then pick the folder again.
    w.extract_input_var.set("")
    w.extract_output_var.set("")
    w.transcribe_var.set(False)
    app._project_path = None
    app._on_project_folder_picked(folder)
    assert w.extract_output_var.get() == folder
    assert w.extract_input_var.get() == r"C:\stock\tmnt.raw"
    assert w.transcribe_var.get() is True or w.transcribe_var.get() == 1


def test_autoload_skips_plain_folders(app, tmp_path):
    w = _pick(app)
    w.extract_output_var.set("")
    app._project_path = None
    app._on_project_folder_picked(str(tmp_path))   # no anchor → no-op
    assert w.extract_output_var.get() == ""


def test_archived_project_open_declined_is_a_noop(app, tmp_path,
                                                  monkeypatch):
    import pinball_decryptor.app as app_mod
    w = _pick(app)
    folder = str(tmp_path / "arch")
    os.makedirs(folder)
    project_file.save(
        project_file.anchor_path(folder), manufacturer_key="stern",
        paths={}, extract_options={}, archived=True)
    monkeypatch.setattr(app_mod.messagebox, "askyesno",
                        lambda *a, **k: False)
    w.extract_output_var.set("")
    app._project_path = None
    app._open_project_folder_checked(folder)
    assert w.extract_output_var.get() == ""       # hydrate declined → not opened
