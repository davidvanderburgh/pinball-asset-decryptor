"""Guards for batch 19 (folder-scoped projects), on the web UI.

Covers: the derived Build Location and its back-off rules, anchor
materialization (explicit save + folder-state-written), auto-load on folder
pick, and the archived-project open gate.
"""

import os

from tests.webui_harness import web_app

from pinball_decryptor.core import project_file, project_registry


def _set(w, var, value):
    w.run(lambda: getattr(w.window, var).set(value))


def _get(w, var):
    return w.run(lambda: getattr(w.window, var).get())


def _clear_auto(w):
    """The Build Location holds a custom value, not an auto-derived one."""
    w.run(lambda: setattr(w.window.service("write"), "_write_output_auto",
                          ""))


# ---- Field collapse -------------------------------------------------------

def test_build_location_derives_from_project_folder(tmp_path):
    folder = str(tmp_path / "proj")
    os.makedirs(folder)
    folder2 = str(tmp_path / "proj2")
    os.makedirs(folder2)
    with web_app(tmp_path, mfr="stern") as w:
        _set(w, "write_output_var", "")
        _set(w, "extract_output_var", folder)
        assert _get(w, "write_output_var") == os.path.join(folder, "build")
        # Re-pointing the project re-derives (the old derived value is
        # "auto").
        _set(w, "extract_output_var", folder2)
        assert _get(w, "write_output_var") == os.path.join(folder2, "build")


def test_custom_build_location_not_clobbered(tmp_path):
    custom = os.path.join(os.sep + "fast", "builds")
    with web_app(tmp_path, mfr="stern") as w:
        _set(w, "write_output_var", custom)
        _clear_auto(w)
        _set(w, "extract_output_var", str(tmp_path))
        assert _get(w, "write_output_var") == custom


def test_legacy_parent_default_is_superseded(tmp_path):
    """The old 'parent of the original image' default must lose to the
    project derivation, whichever order the fields were filled."""
    stock = tmp_path / "imgs" / "game.raw"
    stock.parent.mkdir()
    stock.write_bytes(b"x")
    folder = tmp_path / "proj"
    folder.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _set(w, "write_output_var", "")
        _clear_auto(w)
        _set(w, "extract_input_var", str(stock))       # legacy default fills
        assert _get(w, "write_output_var") == str(stock.parent)
        _set(w, "extract_output_var", str(folder))     # derivation supersedes
        assert _get(w, "write_output_var") == os.path.join(str(folder),
                                                           "build")


def test_anchor_build_override_honoured_by_derivation(tmp_path):
    folder = str(tmp_path / "proj")
    os.makedirs(folder)
    elsewhere = os.path.join(str(tmp_path), "elsewhere", "build")
    project_file.save(
        project_file.anchor_path(folder), manufacturer_key="stern",
        paths={}, extract_options={}, build_dir=elsewhere)
    with web_app(tmp_path, mfr="stern") as w:
        _set(w, "write_output_var", "")
        _clear_auto(w)
        _set(w, "extract_output_var", folder)
        assert _get(w, "write_output_var") == os.path.normpath(elsewhere)


# ---- Materialization + auto-load ------------------------------------------

def test_save_project_writes_anchor_and_registry(tmp_path):
    folder = str(tmp_path / "lz122")
    os.makedirs(folder)
    stock = os.path.join(str(tmp_path), "stock", "lz.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _set(w, "extract_input_var", stock)
        _set(w, "extract_output_var", folder)
        w.run(w.app._save_project)
        assert project_file.has_anchor(folder)
        data = project_file.load_anchor(folder)
        assert data["manufacturer"] == "stern"
        assert data["stock_image"] == stock
        folders = [e["folder"]
                   for e in project_registry.entries(w.app._settings)]
        assert folder in folders


def test_folder_state_written_materializes_once(tmp_path):
    folder = str(tmp_path / "beatles")
    os.makedirs(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _set(w, "extract_output_var", folder)
        w.run(lambda: w.app._on_folder_state_written(folder))
        assert project_file.has_anchor(folder)
        # Second write: no error, anchor stays (update path).
        w.run(lambda: w.app._on_folder_state_written(folder))
        assert project_file.has_anchor(folder)


def test_folder_pick_autoloads_project(tmp_path):
    folder = str(tmp_path / "tmnt159")
    os.makedirs(folder)
    stock = os.path.join(str(tmp_path), "stock", "tmnt.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _set(w, "extract_input_var", stock)
        _set(w, "extract_output_var", folder)
        _set(w, "transcribe_var", True)
        w.run(w.app._save_project)
        # Wander off to a different setup, then pick the folder again.
        _set(w, "extract_input_var", "")
        _set(w, "extract_output_var", "")
        _set(w, "transcribe_var", False)
        w.run(lambda: setattr(w.app, "_project_path", None))
        w.run(lambda: w.app._on_project_folder_picked(folder))
        assert _get(w, "extract_output_var") == folder
        assert _get(w, "extract_input_var") == stock
        assert _get(w, "transcribe_var") in (True, 1)


def test_autoload_skips_plain_folders(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _set(w, "extract_output_var", "")
        w.run(lambda: setattr(w.app, "_project_path", None))
        w.run(lambda: w.app._on_project_folder_picked(str(tmp_path)))
        assert _get(w, "extract_output_var") == ""   # no anchor -> no-op


def test_archived_project_open_declined_is_a_noop(tmp_path, monkeypatch):
    import pinball_decryptor.app as app_mod
    folder = str(tmp_path / "arch")
    os.makedirs(folder)
    project_file.save(
        project_file.anchor_path(folder), manufacturer_key="stern",
        paths={}, extract_options={}, archived=True)
    with web_app(tmp_path, mfr="stern") as w:
        monkeypatch.setattr(app_mod.messagebox, "askyesno",
                            lambda *a, **k: False)
        _set(w, "extract_output_var", "")
        w.run(lambda: setattr(w.app, "_project_path", None))
        w.run(lambda: w.app._open_project_folder_checked(folder))
        # hydrate declined -> not opened
        assert _get(w, "extract_output_var") == ""
