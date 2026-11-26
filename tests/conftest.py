"""Shared pytest fixtures + skip helpers."""

import os
import shutil
import subprocess
import sys

import pytest

from tests import _worker_budget


# ---------------------------------------------------------------------------
# PAD-1536: `-n auto` takes a share of one machine-wide worker budget, so
# two tickets testing at once share the CPU instead of each taking every
# core.  A run alone still gets the full count.  tests/_worker_budget.py.
# ---------------------------------------------------------------------------

@pytest.hookimpl(tryfirst=True)
def pytest_xdist_auto_num_workers(config):
    if hasattr(config, "workerinput") or not _worker_budget.enabled():
        return None                  # None: xdist's own count
    from xdist.plugin import pytest_xdist_auto_num_workers as xdist_count
    total = _worker_budget.budget(xdist_count(config))
    capman = config.pluginmanager.getplugin("capturemanager")

    def say(msg):
        if capman is not None:
            with capman.global_and_fixture_disabled():
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
        else:
            sys.stderr.write(msg + "\n")

    n = _worker_budget.claim(
        total, where=_worker_budget.where_label(config.rootpath), say=say)
    if n < total:
        say("test workers: %d of %d (sharing the machine with other runs)"
            % (n, total))
    config._pad_budget_claimed = True
    return n


def pytest_configure(config):
    if hasattr(config, "workerinput") or not _worker_budget.enabled():
        return
    n = getattr(config.option, "numprocesses", None)
    if (isinstance(n, int) and n > 0
            and not getattr(config, "_pad_budget_claimed", False)):
        _worker_budget.record_fixed(
            n, where=_worker_budget.where_label(config.rootpath))


def pytest_unconfigure(config):
    if not hasattr(config, "workerinput"):
        _worker_budget.release()


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


@pytest.fixture(scope="session", autouse=True)
def _private_temp_dir(tmp_path_factory):
    """The temp folder is the session's own, inside pytest's (which keeps
    the last few runs and drops the rest).

    PAD-1596: code the tests drive makes its scratch with
    ``tempfile.mkdtemp`` / ``gettempdir()``, and what a test did not clean
    up stayed in the developer's real ``%TEMP%`` - 452 ``spike2_grow_*``
    build folders of untitled test builds were found there, which the app's
    own space keeper then counted as a user's leftovers.  Child processes
    get it too (``TEMP`` / ``TMP`` / ``TMPDIR``)."""
    import tempfile
    d = tmp_path_factory.getbasetemp() / "systemp"
    d.mkdir(exist_ok=True)
    keys = ("TEMP", "TMP", "TMPDIR")
    was = tempfile.tempdir, {k: os.environ.get(k) for k in keys}
    tempfile.tempdir = str(d)
    for k in keys:
        os.environ[k] = str(d)
    try:
        yield str(d)
    finally:
        tempfile.tempdir = was[0]
        for k, v in was[1].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(scope="session", autouse=True)
def _private_space_keeper_state(tmp_path_factory):
    """The space keeper's record (what it removed, the give-back's dates) is
    the session's own.  PAD-1600: a Manage disk space test that cleaned 19 GB
    marked a give-back owed in the developer's REAL space_keeper.json.  A
    test that sets ``PAD_SPACE_STATE`` itself still wins."""
    p = tmp_path_factory.getbasetemp() / "space_keeper.json"
    was = os.environ.get("PAD_SPACE_STATE")
    os.environ["PAD_SPACE_STATE"] = str(p)
    try:
        yield str(p)
    finally:
        if was is None:
            os.environ.pop("PAD_SPACE_STATE", None)
        else:
            os.environ["PAD_SPACE_STATE"] = was


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
    monkeypatch.setenv("PAD_BOF_EMU_DIR", str(d))
    monkeypatch.setenv("PAD_DP_EMU_DIR", str(d))
    monkeypatch.setenv("PAD_AP_EMU_DIR", str(d))
    monkeypatch.setenv("PAD_SPOOKY_EMU_DIR", str(d))
    monkeypatch.setenv("PAD_PB_EMU_DIR", str(d))


@pytest.fixture(autouse=True)
def _no_rig_slot(monkeypatch):
    """Every test starts on rig 0 with no ticket label and no board of its own
    (docs/plans/rig_slots.md), whatever the developer's shell or an earlier test
    in the same worker left behind.  Set-then-delete so teardown restores the
    ORIGINAL state: a bare delenv of a variable the app itself set mid-test
    (rigslot.claim_for_ticket) records the app's value and puts it BACK, which
    sent every later rig test in that worker to a rig 1 or 2 with no rootfs
    (the v1.23.0 tests run, 2026-09-27)."""
    for k in ("PAD_SLOT", "PAD_PATHS_SLOT", "PAD_LABEL", "PAD_TICKET", "PAD_BOARD"):
        monkeypatch.setenv(k, "")
        monkeypatch.delenv(k)


@pytest.fixture(autouse=True)
def _not_a_session(monkeypatch):
    """Every test is David's own app, not one a Claude Code session started.
    The suite runs from sessions (CLAUDECODE=1) as well as from CI, and a
    session's app hides and mutes its emulator runs (rigslot.hidden,
    PAD-309) - the same test must not mean two things."""
    for k in ("CLAUDECODE", "PAD_HIDDEN", "PAD_VISIBLE", "PAD_AUDIO"):
        monkeypatch.setenv(k, "")
        monkeypatch.delenv(k)


@pytest.fixture(autouse=True)
def _no_linux_root(monkeypatch):
    """Every test is a Linux desktop with no password-free root (PAD-871),
    whatever the machine running it: a CI runner's sudo asks no password, and
    asked for real it would turn on the root launch under tests that never
    meant one.  A test of that launch pins ``_LINUX_ROOT`` itself."""
    from pinball_decryptor.webui import emulate_core
    monkeypatch.setattr(emulate_core, "_LINUX_ROOT", [None, True])


@pytest.fixture(autouse=True)
def _isolate_card_record(tmp_path_factory, monkeypatch):
    """Every test gets its own empty record of what was written to which card
    (rawdevice.CardRecord, PAD-1584), so no test reads or writes the
    developer's own, and one test's card is not remembered in the next."""
    monkeypatch.setenv("PAD_CARD_RECORD", str(
        tmp_path_factory.mktemp("cards") / "card_writes.json"))
    monkeypatch.delenv("PAD_WRITE_EVERY_CHUNK", raising=False)


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
def preview_modes_off(monkeypatch):
    """The mode maker back as a PREVIEW, switched off: how every copy without a code ran
    it until PAD-763 released it (``preview.RELEASED``). The tests of the switch's off
    path - which a feature that is a preview again takes - run under this."""
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "RELEASED", {})
    monkeypatch.setattr(preview, "FEATURES", {"modes": "Mode maker"})


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
def _isolate_wsl_memory(tmp_path_factory):
    """PAD-1457: the runtime's remembered manifest and the remembered WSL
    prerequisite passes live beside the settings; a test must never write
    the developer's.  And "is WSL running?" reads as yes for the suite, so
    every poll and probe test drives the path it was written for (the
    PAD-1457 tests set PAD_WSL_UP, or patch core.wsl_up, themselves).""" 
    from pinball_decryptor.core import prereqs, runtime, wsl_up
    d = tmp_path_factory.mktemp("wsl_memory")
    # the registry is the real machine's: read as unavailable, so the list
    # comes from the wsl.exe a test fakes (runtime._run), as it always did
    wsl_up.registered_distros = lambda: None
    runtime._manifest_file = lambda: str(d / "runtime_manifest.json")
    prereqs._pass_file = lambda: str(d / "wsl_probe_passes.json")
    os.environ.setdefault("PAD_WSL_UP", "1")


@pytest.fixture(scope="session", autouse=True)
def _isolate_card_prints(tmp_path_factory):
    """Same for the card fingerprint cache (PAD-427, core.lineage): an
    extract or build driven by a test would fingerprint pytest's throwaway
    cards into the developer's own ``card_prints.json``."""
    from pinball_decryptor.core import lineage
    lineage.PRINT_CACHE = str(
        tmp_path_factory.mktemp("card_prints") / "card_prints.json")


@pytest.fixture(scope="session", autouse=True)
def _isolate_pad_ssh_key(tmp_path_factory):
    """PAD-1397: this computer's remote-access key and the machines it has met
    (core/pad_ssh_key.py) live beside settings.json; a build with remote access
    on makes the key, so a test would otherwise make one in the developer's
    own app-data folder."""
    from pinball_decryptor.core import pad_ssh_key
    pad_ssh_key.KEY_DIR = str(tmp_path_factory.mktemp("remote_access"))


@pytest.fixture(autouse=True)
def _forget_machines():
    """PAD-1427: the machines this computer remembers (a list now) and their identities start empty in every
    test, whichever test ran before it on the same worker; the key itself stays for the session."""
    from pinball_decryptor.core import pad_ssh_key
    for name in ("machines.json", "known_hosts.json"):
        try:
            os.remove(os.path.join(pad_ssh_key.KEY_DIR, name))
        except OSError:
            pass


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
    # PAD-1307: a test that starts a rig must never turn off timesyncd in the
    # developer's own distros (core/timesync.py runs real wsl.exe calls).
    os.environ["PAD_KEEP_TIMESYNC"] = "1"
    # PAD-1595: a successful install prunes the payload download cache, so no
    # test may ever see the developer's real one.
    os.environ["PAD_PAYLOAD_DIR"] = str(tmp_path_factory.mktemp("payloads"))




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
