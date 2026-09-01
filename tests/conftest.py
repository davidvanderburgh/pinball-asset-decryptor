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


def _bash_usable():
    r"""True only if `bash` is present AND can run a command.

    Same trap as _wsl_usable() one level down: on Windows the `bash` on
    PATH is often the WSL launcher (C:\Windows\System32\bash.exe),
    which exists on every Windows host and fails every command when no
    distro is installed.  A plain which("bash") is therefore not enough
    -- that is what broke the v0.6.1 CI on the Windows runner.
    """
    if shutil.which("bash") is None:
        return False
    try:
        return subprocess.run(
            ["bash", "-c", "exit 0"],
            capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


HAS_WSL = _wsl_usable()
HAS_BASH = _bash_usable()
HAS_DOCKER = shutil.which("docker") is not None


@pytest.fixture(autouse=True)
def _isolate_rig_dirs(tmp_path_factory, monkeypatch):
    """Point both emulator rigs at an empty directory, for every test.

    The Emulate tab shells the REAL rig on a card pick (item 74's
    ``cardmount.sh --precache``), and a test that set a card path while the
    repo's rig was reachable fired a real wsl.exe that wrote a 16-byte
    pytest card into the developer's LIVE ``~/cardcache`` (found 2026-08-23,
    item 77).  With these pointed at an empty dir, ``rig_available()`` is
    False by default and nothing can reach the real rig or its cache; tests
    that want a rig monkeypatch ``rig_available`` or build their own
    directory, exactly as they already do.  Source-reading tests are
    unaffected — they use the ``DEFAULT_RIG_DIR`` constant, not the env.
    """
    d = tmp_path_factory.mktemp("no-rig")
    monkeypatch.setenv("PAD_EMU_DIR", str(d))
    monkeypatch.setenv("PAD_JJP_EMU_DIR", str(d))


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


# ---------------------------------------------------------------------------
# Nothing in the suite may write to the user's real app-data stores.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _isolate_card_edits(tmp_path_factory):
    """Point the card-edit journal at a temp file for the whole run.

    The Partition Explorer's Replace records what it swapped (core.card_edits),
    and the GUI smoke tests drive a real Replace — which dropped entries for
    pytest's throwaway card images into the developer's own
    ``%APPDATA%/pinball_decryptor/card_edits.json``.
    """
    from pinball_decryptor.core import card_edits
    card_edits.CARD_EDITS_FILE = str(
        tmp_path_factory.mktemp("card_edits") / "card_edits.json")


@pytest.fixture(scope="session", autouse=True)
def _isolate_audio_ctl(tmp_path_factory):
    """Point the Emulate tab's volume/mute file (item 56) at a temp path for
    the whole run — same reason and same shape as ``_isolate_card_edits``
    above.  ``EmulatePanel.__init__`` reads it unconditionally (to seed the
    Volume slider), so a panel built anywhere in the suite would otherwise
    read, and every slider/Mute test would otherwise WRITE, the developer's
    own ``%APPDATA%/pinball_decryptor/audio_ctl.json``."""
    from pinball_decryptor.gui import emulate_tab
    emulate_tab.AUDIO_CTL_FILE = str(
        tmp_path_factory.mktemp("audio_ctl") / "audio_ctl.json")


# ---------------------------------------------------------------------------
# Real-Tk tests all ride ONE xdist worker (--dist loadgroup).
# ---------------------------------------------------------------------------
# Under plain pytest the suite builds and destroys its Tk roots serially, and
# has been stable that way for months.  Several xdist workers doing it
# concurrently is the regime that crashed a macOS CI worker mid-Toplevel
# (2026-08-31, the first -n auto runs) - and, measured 2026-09-01 on the
# 16-core Windows dev box, it is SLOWER too: the Tk-touching subset ran
# ~100-130s serial but 172s spread over 8 workers, because window
# create/map/destroy serializes at the desktop layer whatever the process
# count.  Spreading Tk work anti-helps everywhere it was tried, so every
# tkinter-touching module rides ONE xdist_group on every platform, and the
# other workers parallelize the rest of the suite.
#
# MEMBERSHIP IS THE PART THAT WAS WRONG (2026-09-01).  The original sniff
# looked only for the literal string "tkinter", which missed every file that
# reaches Tk through the shared `app` fixture (they import it from
# test_gui_smoke and never say "tkinter") - so the batch17/32/35/36/37
# family had been racing UNGROUPED across workers since the day the group
# was added.  That race is where the first -n auto run's one ERROR lived,
# and racing Tk window churn is also a wall-clock tax on everything else.
# The sniff now catches both ways a file reaches Tk.  It is still sniffed
# from module source rather than hand-marked, so a new GUI test file is
# grouped the day it appears; the marker is inert without xdist.

_TK_SNIFF_CACHE = {}


def _touches_tk(path):
    p = str(path)
    hit = _TK_SNIFF_CACHE.get(p)
    if hit is None:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                src = f.read()
            hit = "tkinter" in src or "test_gui_smoke" in src
        except OSError:
            hit = False
        _TK_SNIFF_CACHE[p] = hit
    return hit


# tryfirst: xdist's own pytest_collection_modifyitems (remote.py) is what
# folds the marker into the scheduling id, so this hook must run before it
# or the marker arrives after the train has left.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    for item in items:
        if _touches_tk(item.path):
            item.add_marker(pytest.mark.xdist_group("tk"))


def make_tk_root(tk_mod, attempts=4):
    """Create a Tk root, retrying the transient Tcl-script race.

    Under parallel workers, Tk creation sources its runtime scripts from
    disk every time, and on Windows those reads occasionally fail ENOENT on
    files that demonstrably exist (the AV/indexer briefly in the way; one
    2026-09-01 run caught init.tcl, ttk.tcl and vistaTheme.tcl each doing
    it).  Measured, the failure is per-attempt, NOT poisoning: creates on
    the same worker succeed immediately afterwards.  Before this helper, a
    module-scoped root fixture that hit the race once skipped its WHOLE
    module (pytest caches a module fixture's skip), which is how one
    transient read miss became 25 silently-lost tests on the release gate.
    Retry with a short backoff and only give up when it genuinely persists.
    """
    import time as _time
    last = None
    for i in range(attempts):
        try:
            return tk_mod.Tk()
        except Exception as exc:                            # noqa: BLE001
            last = exc
            _time.sleep(0.1 * (i + 1))
    raise last


@pytest.fixture(scope="session")
def all_manufacturers():
    from pinball_decryptor.core.registry import all_manufacturers as _am
    return list(_am())


@pytest.fixture(scope="session")
def manufacturers_by_key(all_manufacturers):
    return {m.key: m for m in all_manufacturers}
