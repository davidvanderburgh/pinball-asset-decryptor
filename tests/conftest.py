"""Shared pytest fixtures + skip helpers."""

import os
import shutil
import subprocess
import sys

import pytest


# ---------------------------------------------------------------------------
# Capability probes
# ---------------------------------------------------------------------------
# Tests use these via @pytest.mark.skipif so the suite degrades cleanly on
# CI runners that don't have every host-side tool.

HAS_GPG = shutil.which("gpg") is not None


def _wsl_usable():
    """True only if WSL can actually execute a command.

    Windows ships `wsl.exe` system-wide as part of the optional WSL
    feature, so `shutil.which("wsl")` finds it on every Windows host
    -- even GitHub Actions runners that don't have a distro
    installed.  We need to verify wsl can actually run something
    before claiming HAS_WSL.
    """
    if sys.platform != "win32":
        return False
    if shutil.which("wsl") is None:
        return False
    try:
        result = subprocess.run(
            ["wsl", "-u", "root", "--", "echo", "ok"],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return False
    return result.returncode == 0


HAS_WSL = _wsl_usable()
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
