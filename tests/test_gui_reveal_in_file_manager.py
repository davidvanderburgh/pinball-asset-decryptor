"""Guard for the Replace tabs' "Show in File Explorer" context-menu action.

``MainWindow._reveal_in_file_manager`` shells out to the native file manager
(Explorer / Finder / xdg-open) with the original asset selected.  These tests
exercise it headlessly -- it touches no ``self`` state, so we call it unbound
with a stub ``self`` and stub the launcher -- to confirm it dispatches the right
tool for an existing file, falls back to the folder for a missing one, and
no-ops on an empty path (instead of raising into the Tk callback).
"""

import os
import subprocess

from pinball_decryptor.gui import main_window as mw


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: calls.append(a[0]))
    # os.startfile is Windows-only; stub it so the test is uniform cross-platform.
    monkeypatch.setattr(os, "startfile",
                        lambda p: calls.append(p), raising=False)
    return calls


def _flat(calls):
    """Join every launch argument (string command line OR arg list) into one
    string we can substring-match -- avoids repr's backslash double-escaping."""
    out = []
    for c in calls:
        if isinstance(c, (list, tuple)):
            out.extend(str(x) for x in c)
        else:
            out.append(str(c))
    return "\n".join(out)


def test_reveal_existing_file_launches_with_path(tmp_path, monkeypatch):
    f = tmp_path / "idx0001.wav"
    f.write_bytes(b"\x00")
    calls = _capture(monkeypatch)

    mw.MainWindow._reveal_in_file_manager(object(), str(f))

    assert calls, "no file-manager launcher was invoked"
    flat = _flat(calls)
    # The file itself (Windows/macOS select) or its folder (Linux) is referenced.
    assert os.path.basename(str(f)) in flat or str(tmp_path) in flat


def test_reveal_missing_file_falls_back_to_folder(tmp_path, monkeypatch):
    missing = tmp_path / "gone.wav"          # folder exists, file does not
    calls = _capture(monkeypatch)

    mw.MainWindow._reveal_in_file_manager(object(), str(missing))

    assert calls, "missing file should still open the containing folder"
    assert str(tmp_path) in _flat(calls)


def test_reveal_empty_path_is_noop(monkeypatch):
    calls = _capture(monkeypatch)
    mw.MainWindow._reveal_in_file_manager(object(), "")
    mw.MainWindow._reveal_in_file_manager(object(), None)
    assert calls == []
