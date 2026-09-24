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


@pytest.fixture(autouse=True)
def _isolate_title_cache(tmp_path_factory, monkeypatch):
    """Every test gets its own empty per-build cache (title_reader.cache_dir: ports and
    tables worked out on this machine), so no test reads or writes the developer's own,
    and a port one test works out or reads off a card is not seen by the next."""
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path_factory.mktemp("titles")))
    mp = sys.modules.get("pinball_decryptor.plugins.stern.mode_project")
    if mp is not None and hasattr(mp, "_REMEMBERED"):
        monkeypatch.setattr(mp, "_REMEMBERED", {})


@pytest.fixture(autouse=True)
def _preview_features_off(monkeypatch):
    """Every test starts with every PREVIEW FEATURE switched off (core/preview.py), as a
    copy of the app with no code does - whatever an earlier test in the same worker
    loaded. A test of the mode maker turns it on with ``preview_modes_on``."""
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "_active", frozenset())
    monkeypatch.setattr(preview, "_statuses", [])


@pytest.fixture
def preview_modes_on(monkeypatch):
    """The mode maker's preview switch ON for one test: what a signed code turns on at
    start-up, with no code and no key (the shipped public key is never touched). It holds
    through an App() start-up, which judges the stored codes again."""
    from pinball_decryptor.core import preview
    real = preview.enabled
    monkeypatch.setattr(preview, "enabled",
                        lambda feature: feature == "modes" or real(feature))


@pytest.fixture
def not_macos(monkeypatch):
    """A test of what Windows and Linux do (the SD card size option, the
    games-partition room measured through the kernel's driver, the texts
    that name the Write tab's control), pinned there on the macOS CI leg,
    where the app takes its macOS branches on purpose.  The macOS wording is
    tested by naming the platform."""
    if sys.platform == "darwin":
        monkeypatch.setattr(sys, "platform", "linux")


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
    """Point the Emulate tabs' volume/mute file (item 56) at a temp path for
    the whole run — same reason and same shape as ``_isolate_card_edits``
    above.  A JJP or Spike 1 tab reads it to seed its Volume slider, so a tab
    built anywhere in the suite would otherwise read, and every slider/Mute
    test would otherwise WRITE, the developer's own
    ``%APPDATA%/pinball_decryptor/audio_ctl.json``.  The one definition is
    ``webui/emulate_core.py``'s; the rigs' helpers read it from there."""
    from pinball_decryptor.webui import emulate_core
    emulate_core.AUDIO_CTL_FILE = str(
        tmp_path_factory.mktemp("audio_ctl") / "audio_ctl.json")


@pytest.fixture(scope="session", autouse=True)
def _isolate_title_cache_session(tmp_path_factory):
    """Point the per-build caches (title_reader.cache_dir: ports derived on this machine,
    generated tables) at a temp folder for the whole run, so a port the developer's app
    derived is never read by a test (every port lookup reads that folder) and a test's
    is never left in ``%LOCALAPPDATA%``. A test that wants its own sets the variable."""
    os.environ["PAD_TITLE_CACHE"] = str(tmp_path_factory.mktemp("title_cache"))




# ---------------------------------------------------------------------------
# Multi-gigabyte card images that do not cost multiple gigabytes.
# ---------------------------------------------------------------------------
# The mkmulticard tests build stock 8G card images -- 7.32 GB each, one test
# making three of them -- and only ever touch a few kilobytes of partition
# table and superblock in each.  On Linux and macOS ``truncate`` leaves the
# rest as a hole and the file costs nothing.  On Windows it does not: NTFS
# zero-fills, so those files cost 7.32 GB and 8.6s of real I/O apiece, and
# pytest keeps the last three tmp_path trees alive at once.
#
# That is what exhausted the hosted runner's C: drive on 2026-09-09 ("There
# is not enough space on the disk", four minutes into the suite, on a runner
# that came up with 29.4 GB free).  Marking the file sparse first and then
# extending it with one write at the end costs 0 bytes and 0.03s.
#
# ``truncate`` will NOT do on Windows even after the flag is set -- CPython
# calls _chsize_s, which writes the zeros explicitly and re-allocates every
# block.  The final write is what leaves the hole intact.
_FSCTL_SET_SPARSE = 0x900C4


def _mark_sparse(fh):
    """Ask NTFS to leave this handle's unwritten ranges unallocated."""
    import ctypes
    import ctypes.wintypes
    import msvcrt
    returned = ctypes.wintypes.DWORD()
    return bool(ctypes.windll.kernel32.DeviceIoControl(
        ctypes.wintypes.HANDLE(msvcrt.get_osfhandle(fh.fileno())),
        _FSCTL_SET_SPARSE, None, 0, None, 0, ctypes.byref(returned), None))


def sparse_image(path, size):
    """Create `path` as `size` bytes of zeros without paying for them.

    Falls back to a plain truncate if the filesystem will not take the sparse
    flag (FAT32, a network share, a future runner image) -- correctness never
    depends on the hole, only the disk bill does.
    """
    with open(path, "wb") as f:
        if size and sys.platform == "win32" and _mark_sparse(f):
            f.seek(size - 1)
            f.write(b"\x00")
        else:
            f.truncate(size)
    return path

@pytest.fixture(scope="session")
def all_manufacturers():
    from pinball_decryptor.core.registry import all_manufacturers as _am
    return list(_am())


@pytest.fixture(scope="session")
def manufacturers_by_key(all_manufacturers):
    return {m.key: m for m in all_manufacturers}
