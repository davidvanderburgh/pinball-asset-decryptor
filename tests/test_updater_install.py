"""In-app update install flow (jim-beam's "extra security pass").

Every release used to mean: browser download -> Mark-of-the-Web ->
SmartScreen "Windows protected your PC" -> UAC -> wizard.  The in-app
flow downloads the installer itself (no MOTW, so no SmartScreen), runs
it silently from the already-elevated app (no UAC), and the installer
relaunches the app (/RELAUNCH=1).  These tests pin the pieces:

  * asset picking — Windows gets the *_Windows.exe asset (+ sha256 from
    the API's digest field); other platforms get None and keep the
    browser flow.
  * download — streamed with progress, cancellable, digest-verified,
    and NEVER leaves a partial/corrupt exe behind on any failure (the
    caller runs the destination file elevated).
  * launch — unattended Inno switches, silent + no-restart + relaunch.
  * .iss — the relaunch [Run] entry and its /RELAUNCH gate must exist,
    routed through launcher.vbs like every other entry point.
"""

import hashlib
import io
import json
from pathlib import Path

import pytest

from pinball_decryptor.core import net, updater

REPO = Path(__file__).resolve().parent.parent
ISS = REPO / "installer" / "pinball_decryptor.iss"


# ---------------------------------------------------------------------------
# Asset picking
# ---------------------------------------------------------------------------

ASSETS = [
    {"name": "Pinball_Asset_Decryptor_v9.0.0_macOS_arm64.dmg",
     "browser_download_url": "https://example.com/mac.dmg", "size": 1},
    {"name": "Pinball_Asset_Decryptor_v9.0.0_Windows.exe",
     "browser_download_url": "https://example.com/win.exe", "size": 42,
     "digest": "sha256:" + "ab" * 32},
    {"name": "Pinball_Asset_Decryptor_v9.0.0_Linux.AppImage",
     "browser_download_url": "https://example.com/linux", "size": 1},
]


def test_pick_installer_asset_windows():
    got = updater._pick_installer_asset(ASSETS, platform="win32")
    assert got == {"name": "Pinball_Asset_Decryptor_v9.0.0_Windows.exe",
                   "url": "https://example.com/win.exe",
                   "size": 42, "sha256": "ab" * 32}


def test_pick_installer_asset_no_digest_is_ok():
    assets = [{"name": "Foo_v1_Windows.exe",
               "browser_download_url": "https://example.com/w.exe"}]
    got = updater._pick_installer_asset(assets, platform="win32")
    assert got["sha256"] is None and got["size"] == 0


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_pick_installer_asset_non_windows_gets_none(platform):
    # macOS/Linux keep the browser-download flow (no silent-install path
    # for a .dmg / AppImage) — auto-install must not be offered there.
    assert updater._pick_installer_asset(ASSETS, platform=platform) is None


def test_pick_installer_asset_no_windows_asset():
    assert updater._pick_installer_asset(
        [ASSETS[0], ASSETS[2]], platform="win32") is None
    assert updater._pick_installer_asset(None, platform="win32") is None


def test_check_for_update_carries_installer(monkeypatch):
    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    body = json.dumps({
        "tag_name": "v99.0.0",
        "html_url": "https://example.com/rel",
        "body": "notes",
        "assets": ASSETS,
    }).encode()
    monkeypatch.setattr(net, "urlopen",
                        lambda req, timeout: FakeResp(body))
    version, url, notes, installer = updater.check_for_update("0.1.0")
    if updater.sys.platform == "win32":
        assert installer and installer["url"].endswith("win.exe")
    else:
        assert installer is None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener_for(payload):
    def opener(req, timeout):
        return _FakeResp(payload)
    return opener


def test_download_streams_verifies_and_reports_progress(tmp_path):
    payload = bytes(range(256)) * 4096  # 1 MiB, multiple chunks
    dest = tmp_path / "setup.exe"
    seen = []
    n = updater.download_installer(
        "https://example.com/win.exe", dest,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        progress_cb=seen.append,
        opener=_opener_for(payload))
    assert n == len(payload)
    assert dest.read_bytes() == payload
    assert seen and seen[-1] == len(payload)
    assert seen == sorted(seen)


def test_download_digest_mismatch_deletes_partial(tmp_path):
    dest = tmp_path / "setup.exe"
    with pytest.raises(ValueError, match="integrity"):
        updater.download_installer(
            "https://example.com/win.exe", dest,
            expected_sha256="0" * 64,
            opener=_opener_for(b"evil bytes"))
    # A corrupt exe must never be left where the caller might run it.
    assert not dest.exists()


def test_download_cancel_deletes_partial(tmp_path):
    dest = tmp_path / "setup.exe"
    with pytest.raises(InterruptedError):
        updater.download_installer(
            "https://example.com/win.exe", dest,
            cancel_cb=lambda: True,
            opener=_opener_for(b"x" * 10))
    assert not dest.exists()


def test_download_network_error_deletes_partial(tmp_path):
    dest = tmp_path / "setup.exe"

    class DropsMidway(_FakeResp):
        def read(self, n=-1):
            raise OSError("connection reset")

    with pytest.raises(OSError):
        updater.download_installer(
            "https://example.com/win.exe", dest,
            opener=lambda req, timeout: DropsMidway(b""))
    assert not dest.exists()


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def test_launch_uses_unattended_inno_switches(tmp_path):
    calls = []

    def fake_shell_execute(hwnd, verb, path, args, cwd, show):
        calls.append((verb, path, args))
        return 42  # > 32 == success

    ok = updater.launch_installer_windows(
        tmp_path / "setup.exe", shell_execute=fake_shell_execute)
    assert ok
    (verb, path, args), = calls
    assert verb == "open" and path.endswith("setup.exe")
    # The full unattended recipe: silent, never reboot, tolerate our
    # own process still holding files, relaunch the app after, and skip
    # the prerequisites pass (Inno remembers a first-install "Install
    # prerequisites" tick per AppId and would re-run WSL2/partclone/gpg
    # on every silent update otherwise).
    for switch in ("/SILENT", "/NORESTART",
                   "/FORCECLOSEAPPLICATIONS", "/RELAUNCH=1",
                   '/MERGETASKS="!runprereqs"'):
        assert switch in args.split()


def test_launch_failure_is_reported():
    assert not updater.launch_installer_windows(
        "x.exe", shell_execute=lambda *a: 5)  # SE_ERR_ACCESSDENIED


# ---------------------------------------------------------------------------
# Installer script — the receiving end of /RELAUNCH=1
# ---------------------------------------------------------------------------

def test_iss_relaunches_after_silent_update():
    """The silent in-app update must end with the app back on screen.

    The normal post-install launch entry is (correctly) skipifsilent,
    so the .iss needs the dedicated /RELAUNCH=1-gated [Run] entry —
    without it, "Install update" closes the app and nothing reopens,
    which reads as a failed update.  It must route through launcher.vbs
    (self-elevation) like every other entry point.
    """
    iss = ISS.read_text(encoding="utf-8", errors="replace")
    assert "RelaunchRequested" in iss, (
        "pinball_decryptor.iss lost its RelaunchRequested check — the "
        "in-app updater's silent install would finish with the app "
        "closed and nothing reopening.")
    assert "{param:RELAUNCH|0}" in iss, (
        "RelaunchRequested must read the /RELAUNCH=1 command-line flag "
        "(updater.INSTALLER_ARGS passes it).")
    relaunch_lines = [
        ln for ln in iss.splitlines()
        if "Check: RelaunchRequested" in ln
        and not ln.lstrip().startswith(";")]
    assert relaunch_lines, (
        "no [Run] entry gated on RelaunchRequested — the flag is parsed "
        "but nothing relaunches the app.")
    for ln in relaunch_lines:
        assert "launcher.vbs" in ln, (
            f"the relaunch entry must go through launcher.vbs "
            f"(self-elevation), not straight at the exe: {ln}")


def test_iss_prereq_task_name_matches_mergetasks_switch():
    """updater.INSTALLER_ARGS deselects the prereq task by name.

    If the .iss ever renames the ``runprereqs`` task, the
    /MERGETASKS="!runprereqs" switch would silently stop matching and
    every in-app update would re-run the full prerequisites pass again
    (the original clickless-update complaint).  Pin the name on both
    sides.
    """
    assert '/MERGETASKS="!runprereqs"' in updater.INSTALLER_ARGS
    iss = ISS.read_text(encoding="utf-8", errors="replace")
    assert 'Name: "runprereqs"' in iss, (
        "the .iss prereq task was renamed/removed — update "
        "updater.INSTALLER_ARGS' /MERGETASKS switch to match.")
