"""PAD-430: a tab whose import hits a locked file (a virus scanner reading
numpy's DLL right after an update) is retried instead of left as a
"This tab failed to load" placeholder."""

import importlib
import sys

import pytest

from pinball_decryptor.webui import tabs as T


LOCKED = ImportError(
    "IMPORTANT: PLEASE READ THIS FOR ADVICE ON HOW TO SOLVE THIS ISSUE! "
    "Original error was: DLL load failed while importing _multiarray_umath:"
    " The process cannot access the file because it is being used by "
    "another process.")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(T.time, "sleep", lambda s: None)


def test_locked_import_is_retried(monkeypatch):
    calls = []
    real = importlib.import_module

    def flaky(name):
        calls.append(name)
        if len(calls) < 3:
            sys.modules["pad430_half_loaded"] = object()
            raise LOCKED
        return real("json")

    monkeypatch.setattr(T.importlib, "import_module", flaky)
    mod = T._import_tab("x")
    assert mod.__name__ == "json"
    assert len(calls) == 3
    # what the failed attempts left half-imported was dropped
    assert "pad430_half_loaded" not in sys.modules


def test_still_locked_gives_up(monkeypatch):
    calls = []

    def locked(name):
        calls.append(name)
        raise LOCKED

    monkeypatch.setattr(T.importlib, "import_module", locked)
    with pytest.raises(ImportError):
        T._import_tab("x")
    assert len(calls) == len(T._LOCKED_RETRY_WAITS) + 1


def test_other_errors_not_retried(monkeypatch):
    calls = []

    def broken(name):
        calls.append(name)
        raise ImportError("No module named 'nothing'")

    monkeypatch.setattr(T.importlib, "import_module", broken)
    with pytest.raises(ImportError):
        T._import_tab("x")
    assert len(calls) == 1


def test_winerror_32_in_cause_chain():
    inner = OSError(32, "in use")
    inner.winerror = 32
    try:
        try:
            raise inner
        except OSError as e:
            raise ImportError("wrapped") from e
    except ImportError as outer:
        assert T._file_locked(outer)
    assert not T._file_locked(ImportError("DLL load failed: not found"))
