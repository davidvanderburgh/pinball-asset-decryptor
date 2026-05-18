"""Shared pytest fixtures + skip helpers."""

import os
import shutil
import sys

import pytest


# ---------------------------------------------------------------------------
# Capability probes
# ---------------------------------------------------------------------------
# Tests use these via @pytest.mark.skipif so the suite degrades cleanly on
# CI runners that don't have every host-side tool.

HAS_GPG = shutil.which("gpg") is not None
HAS_WSL = (sys.platform == "win32") and (shutil.which("wsl") is not None)
HAS_DOCKER = shutil.which("docker") is not None


def _tk_works():
    """Return True if we can instantiate a hidden Tk root.

    Headless Linux without xvfb has no DISPLAY and tk.Tk() raises
    `_tkinter.TclError: no display name`.  Mac / Windows runners can
    always open one.  Used to skip GUI smoke tests when no display is
    available.
    """
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


HAS_DISPLAY = _tk_works()


# ---------------------------------------------------------------------------
# Plugin loading is process-wide.  Force it once per session.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _load_plugins_once():
    from pinball_decryptor.core.registry import load_plugins
    load_plugins()


@pytest.fixture(scope="session")
def all_manufacturers():
    from pinball_decryptor.core.registry import all_manufacturers as _am
    return list(_am())


@pytest.fixture(scope="session")
def manufacturers_by_key(all_manufacturers):
    return {m.key: m for m in all_manufacturers}
