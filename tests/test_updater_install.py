"""In-app update install flow (jim-beam's "extra security pass").

Every release used to mean: browser download -> Mark-of-the-Web ->
SmartScreen "Windows protected your PC" -> UAC -> wizard.  The in-app
flow downloads the installer itself (no MOTW, so no SmartScreen), runs
it silently from the already-elevated app (no UAC), and the installer
relaunches the app (/RELAUNCH=1).  These tests pin the pieces:

  * asset picking — Windows gets the *_Windows.exe asset (+ sha256 from
    the API's digest field), Linux gets its own-arch .AppImage, and macOS
    gets its own-arch .dmg.  macOS used to get None; the browser handoff
    was what set com.apple.quarantine and so produced the "can't be
    verified" wall and the password, once per release.
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
import platform as _platform
from pathlib import Path

import pytest

from pinball_decryptor.core import net, updater

REPO = Path(__file__).resolve().parent.parent
ISS = REPO / "installer" / "pinball_decryptor.iss"


# ---------------------------------------------------------------------------
# Asset picking
# ---------------------------------------------------------------------------

# Real asset names as CI uploads them (build_macos.sh's per-arch DMG
# labels, build.ps1/ISCC's exe, the AppImage) — _release_ready matches
# on these, so the fixture must use the genuine naming convention.
ASSETS = [
    {"name": "Pinball_Asset_Decryptor_v9.0.0_macOS_AppleSilicon.dmg",
     "browser_download_url": "https://example.com/mac_arm.dmg", "size": 1},
    {"name": "Pinball_Asset_Decryptor_v9.0.0_macOS_Intel.dmg",
     "browser_download_url": "https://example.com/mac_intel.dmg", "size": 1},
    {"name": "Pinball_Asset_Decryptor_v9.0.0_Windows.exe",
     "browser_download_url": "https://example.com/win.exe", "size": 42,
     "digest": "sha256:" + "ab" * 32},
    {"name": "Pinball_Asset_Decryptor_v9.0.0_Linux_x86_64.AppImage",
     "browser_download_url": "https://example.com/linux", "size": 1},
]


def test_pick_installer_asset_windows():
    got = updater._pick_installer_asset(ASSETS, platform="win32")
    assert got == {"name": "Pinball_Asset_Decryptor_v9.0.0_Windows.exe",
                   "url": "https://example.com/win.exe",
                   "size": 42, "sha256": "ab" * 32,
                   "kind": "windows-installer"}


def test_pick_installer_asset_no_digest_is_ok():
    assets = [{"name": "Foo_v1_Windows.exe",
               "browser_download_url": "https://example.com/w.exe"}]
    got = updater._pick_installer_asset(assets, platform="win32")
    assert got["sha256"] is None and got["size"] == 0


def test_pick_installer_asset_linux_gets_the_appimage():
    """Linux must get an in-app download.  Its browser handoff was the
    unreliable one: from inside an AppImage the desktop URL opener
    inherits a bundle environment it can't run in, so the banner's
    Download button did nothing at all, silently, for four releases
    (a tester, v0.85-v0.88).  Fetching the file ourselves needs no browser."""
    got = updater._pick_installer_asset(ASSETS, platform="linux",
                                        machine="x86_64")
    assert got == {
        "name": "Pinball_Asset_Decryptor_v9.0.0_Linux_x86_64.AppImage",
        "url": "https://example.com/linux",
        "size": 1, "sha256": None, "kind": "appimage"}


def test_pick_installer_asset_linux_wont_hand_over_a_foreign_arch():
    """An AppImage is a binary — the wrong arch simply won't run, and a
    download that can't run is worse than the release page."""
    assert updater._pick_installer_asset(ASSETS, platform="linux",
                                         machine="aarch64") is None


def test_pick_installer_asset_macos_gets_its_own_arch_dmg():
    """macOS USED TO GET None, on the reasoning that a .dmg has to be mounted
    and dragged by hand so downloading it saved nothing.  What it saves is the
    quarantine flag: ``com.apple.quarantine`` is set by whatever downloads a
    file, so the browser handoff is what produced "can't be opened because
    Apple cannot check it", the Privacy & Security trip and the password, on
    every single release.  urlopen sets no such flag."""
    arm = updater._pick_installer_asset(ASSETS, platform="darwin",
                                        machine="arm64")
    assert arm == {"name": "Pinball_Asset_Decryptor_v9.0.0_macOS_AppleSilicon.dmg",
                   "url": "https://example.com/mac_arm.dmg",
                   "size": 1, "sha256": None, "kind": "macos-dmg"}
    intel = updater._pick_installer_asset(ASSETS, platform="darwin",
                                          machine="x86_64")
    assert intel["url"] == "https://example.com/mac_intel.dmg"


def test_pick_installer_asset_macos_without_its_dmg():
    """An Intel Mac must not be handed the Apple Silicon image just because
    it is the only one that uploaded yet."""
    arm_only = [a for a in ASSETS if "AppleSilicon" in a["name"]]
    assert updater._pick_installer_asset(arm_only, platform="darwin",
                                         machine="x86_64") is None


def test_pick_installer_asset_no_windows_asset():
    non_windows = [a for a in ASSETS
                   if not a["name"].lower().endswith("_windows.exe")]
    assert updater._pick_installer_asset(non_windows,
                                         platform="win32") is None
    assert updater._pick_installer_asset(None, platform="win32") is None


@pytest.mark.parametrize("platform,expected_url", [
    ("win32", "win.exe"),
    ("linux", "https://example.com/linux"),
    # Which of the two Mac images depends on the RUNNER's arch, since
    # check_for_update takes no machine override — so this asserts only that
    # a disk image was chosen.  Naming one would reintroduce exactly the
    # host-dependence this test's docstring is about.
    ("darwin", ".dmg"),
])
def test_check_for_update_carries_installer(monkeypatch, platform,
                                            expected_url):
    """The whole chain, per platform.

    Parametrised rather than branching on the host: the old version
    asked ``if sys.platform == "win32"`` and so only ever exercised the
    one branch the runner happened to be, which is why Linux gaining an
    installer asset broke it on CI and nowhere else.
    """
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
    monkeypatch.setattr(updater.sys, "platform", platform)
    # Pin the arch too, or this reads the runner's own and the Linux case
    # passes on x86_64 CI and fails on an arm64 dev box.
    monkeypatch.setattr(_platform, "machine", lambda: "x86_64")
    _version, _url, _notes, installer = updater.check_for_update("0.1.0")
    if expected_url is None:
        assert installer is None
    else:
        assert installer and installer["url"].endswith(expected_url)


# ---------------------------------------------------------------------------
# Release-readiness gate (v0.69.5: the release row + notes appear the
# moment the tag is published, but the four installers upload from
# independent CI jobs minutes later — the update banner must not point
# at a release page with no download for this platform on it).
# ---------------------------------------------------------------------------


def test_release_ready_per_platform():
    data = {"body": "notes", "assets": ASSETS}
    assert updater._release_ready(data, platform="win32")
    assert updater._release_ready(data, platform="linux")
    assert updater._release_ready(data, platform="darwin", machine="arm64")
    assert updater._release_ready(data, platform="darwin", machine="x86_64")


def test_release_ready_gates_on_own_platform_asset():
    no_win = [a for a in ASSETS
              if not a["name"].lower().endswith("_windows.exe")]
    assert not updater._release_ready(
        {"body": "notes", "assets": no_win}, platform="win32")
    assert updater._release_ready(
        {"body": "notes", "assets": no_win}, platform="linux")
    # The two DMGs upload from separate jobs — each arch waits for its own.
    no_intel = [a for a in ASSETS if "Intel" not in a["name"]]
    assert updater._release_ready(
        {"body": "notes", "assets": no_intel},
        platform="darwin", machine="arm64")
    assert not updater._release_ready(
        {"body": "notes", "assets": no_intel},
        platform="darwin", machine="x86_64")


def test_release_ready_requires_notes():
    assert not updater._release_ready(
        {"body": "", "assets": ASSETS}, platform="win32")
    assert not updater._release_ready(
        {"body": "   ", "assets": ASSETS}, platform="win32")
    assert not updater._release_ready({"assets": ASSETS}, platform="win32")


def test_check_for_update_withheld_until_assets_ready(monkeypatch):
    withheld = []
    body = json.dumps({
        "tag_name": "v99.0.0",
        "html_url": "https://example.com/rel",
        "body": "notes",
        "assets": [],           # release published, uploads still running
    }).encode()
    monkeypatch.setattr(net, "urlopen", lambda req, timeout: _FakeResp(body))
    assert updater.check_for_update(
        "0.1.0", not_ready_cb=withheld.append) is None
    assert withheld == ["99.0.0"]


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


# ---------------------------------------------------------------------------
# Re-check before installing (feedback batch 23)
#
# The banner is filled in by one check 1.5 s after launch and then stands until
# the app restarts, so a window left open across a release keeps offering the
# version that was newest when it opened.  He pressed Install on a laptop
# showing 0.81 and got 0.81 — days stale.  _freshest_update re-asks at the
# moment of the click.
# ---------------------------------------------------------------------------

class _FakeWindow:
    def __init__(self):
        self.lines = []

    def append_log(self, msg, *_a, **_k):
        self.lines.append(msg)


class _FakeApp:
    """Just enough of the App to drive _freshest_update."""

    def __init__(self):
        from pinball_decryptor.app import App
        self._freshest_update = App._freshest_update.__get__(self)
        self.window = _FakeWindow()
        self._current_mfr = None
        self.root = type("R", (), {"update_idletasks": lambda _s: None})()


STALE = {"name": "old.exe", "url": "https://example.com/old.exe", "size": 1}
FRESH = {"name": "new.exe", "url": "https://example.com/new.exe", "size": 2}


def _patch_check(monkeypatch, result):
    def _fake(*_a, **_k):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr("pinball_decryptor.app.check_for_update", _fake)


def test_a_newer_release_is_offered_instead(monkeypatch):
    app = _FakeApp()
    _patch_check(monkeypatch, ("0.86.0", "u", "notes", FRESH))
    monkeypatch.setattr("pinball_decryptor.app.messagebox.askyesno",
                        lambda *a, **k: True)
    assert app._freshest_update("0.81.0", STALE) == ("0.86.0", FRESH)
    assert any("0.86.0" in m and "0.81.0" in m for m in app.window.lines)


def test_declining_the_newer_one_cancels_rather_than_installing_the_stale(
        monkeypatch):
    """Saying "no thanks" to 0.86 must not quietly install 0.81 over the top —
    that is the one outcome he did not ask for."""
    app = _FakeApp()
    _patch_check(monkeypatch, ("0.86.0", "u", "notes", FRESH))
    monkeypatch.setattr("pinball_decryptor.app.messagebox.askyesno",
                        lambda *a, **k: False)
    version, installer = app._freshest_update("0.81.0", STALE)
    assert installer is None
    assert any("cancelled" in m for m in app.window.lines)


def test_banner_already_current_installs_without_asking(monkeypatch):
    app = _FakeApp()
    _patch_check(monkeypatch, ("0.81.0", "u", "notes", FRESH))

    def _no(*_a, **_k):
        raise AssertionError("must not prompt when nothing newer exists")
    monkeypatch.setattr("pinball_decryptor.app.messagebox.askyesno", _no)
    assert app._freshest_update("0.81.0", STALE) == ("0.81.0", STALE)


def test_nothing_newer_at_all_installs_what_the_banner_had(monkeypatch):
    app = _FakeApp()
    _patch_check(monkeypatch, None)
    assert app._freshest_update("0.81.0", STALE) == ("0.81.0", STALE)


def test_a_failed_recheck_does_not_block_the_install(monkeypatch):
    """Being offline is not a reason to refuse an install that was already on
    offer — say so and go ahead."""
    app = _FakeApp()
    _patch_check(monkeypatch, OSError("no route to host"))
    assert app._freshest_update("0.81.0", STALE) == ("0.81.0", STALE)
    assert any("Couldn't re-check" in m for m in app.window.lines)


# ---------------------------------------------------------------------------
# macOS: replacing the bundle in place, with no Gatekeeper prompt
# ---------------------------------------------------------------------------

class _FakeRun:
    """Records argv and answers with a chosen return code."""

    def __init__(self, fail_on=None, mount_dir=None, app_name="Test.app"):
        self.calls = []
        self._fail_on = fail_on
        self._mount = mount_dir
        self._app = app_name

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        rc = 1 if (self._fail_on and argv[0] == self._fail_on) else 0
        if argv[0] == "hdiutil" and argv[1] == "attach" and rc == 0:
            # A real mount makes the bundle appear at the mountpoint.
            import os as _os
            _os.makedirs(_os.path.join(argv[-2], self._app), exist_ok=True)
        if argv[0] == "ditto" and rc == 0:
            import os as _os
            _os.makedirs(argv[2], exist_ok=True)
        return _platform_result(rc)

    def argv_for(self, tool):
        return [c for c in self.calls if c and c[0] == tool]


def _platform_result(rc):
    class R:
        returncode = rc
        stderr = "boom" if rc else ""
        stdout = ""
    return R()


def _bundle(tmp_path):
    b = tmp_path / "Applications" / "Pinball Asset Decryptor.app"
    b.mkdir(parents=True)
    return b


def test_macos_app_bundle_walks_up_from_the_executable(tmp_path):
    """Never guesses /Applications: the user may keep the bundle anywhere,
    and replacing the wrong copy is worse than declining to update."""
    exe = tmp_path / "My App.app" / "Contents" / "MacOS" / "app"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert updater.macos_app_bundle(str(exe)) == str(tmp_path / "My App.app")
    assert updater.macos_app_bundle(str(tmp_path / "plain" / "x")) is None


def test_macos_install_mounts_copies_and_hands_over_the_swap(tmp_path):
    b = _bundle(tmp_path)
    run = _FakeRun()
    started = []
    ok, err = updater.install_update_macos(
        tmp_path / "new.dmg", bundle=str(b), run=run,
        popen=lambda argv, **kw: started.append(list(argv)), pid=4321)
    assert ok and err == ""
    assert run.argv_for("hdiutil")[0][1] == "attach"
    assert run.argv_for("ditto"), "the bundle was never copied out"
    # Detached, always — a mounted image left behind is a stuck volume.
    assert any(c[1] == "detach" for c in run.argv_for("hdiutil"))
    # The quarantine strip is belt and braces for an image that arrived some
    # other way; a self-downloaded one was never flagged.
    assert run.argv_for("xattr") and "com.apple.quarantine" in run.argv_for("xattr")[0]
    assert started and started[0][0] == "/bin/sh"
    script = Path(started[0][1]).read_text()
    assert "kill -0 4321" in script          # waits for THIS process to go
    assert "open " in script                 # and restarts the new one
    assert str(b) in script


def test_macos_install_swap_script_restores_the_old_app_if_the_move_fails(
        tmp_path):
    """The swap moves the old bundle aside first, so a failure at the last
    step puts the working app back rather than leaving the user with none."""
    b = _bundle(tmp_path)
    started = []
    updater.install_update_macos(
        tmp_path / "new.dmg", bundle=str(b), run=_FakeRun(),
        popen=lambda argv, **kw: started.append(list(argv)), pid=1)
    script = Path(started[0][1]).read_text()
    assert ".old" in script
    move_back = [ln for ln in script.splitlines() if "exit 1" in ln]
    assert any(".old" in ln for ln in move_back), script


def test_macos_install_refuses_rather_than_half_doing_it(tmp_path):
    """Each failure leaves the installed app untouched and says why — the
    caller falls back to the browser flow."""
    b = _bundle(tmp_path)
    started = []
    pop = lambda argv, **kw: started.append(1)          # noqa: E731

    ok, err = updater.install_update_macos(
        tmp_path / "n.dmg", bundle=str(b), run=_FakeRun(fail_on="hdiutil"),
        popen=pop)
    assert not ok and "mount" in err

    # An image with no .app in it.
    run = _FakeRun(app_name="readme.txt")
    ok, err = updater.install_update_macos(
        tmp_path / "n.dmg", bundle=str(b), run=run, popen=pop)
    assert not ok and "no application" in err
    assert any(c[1] == "detach" for c in run.argv_for("hdiutil"))

    ok, err = updater.install_update_macos(
        tmp_path / "n.dmg", bundle=None, run=_FakeRun(), popen=pop,
        )
    assert not ok

    assert not started, "nothing may be launched on a failed install"
