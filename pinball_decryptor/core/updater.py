"""Auto-update checker — checks the GitHub releases API on startup.

Also home to the in-app download flow behind the banner's Install /
Download update button, on the two platforms where fetching the release
asset ourselves beats sending the user to a browser:

Windows
    Downloads ``*_Windows.exe`` and runs it silently.  Files a browser
    saves carry the Mark-of-the-Web, so every release (a brand-new
    unsigned binary with zero reputation) would make the user re-run the
    SmartScreen "Windows protected your PC" gauntlet.  A file the app
    writes has no MOTW, and the app already runs elevated
    (launcher.vbs), so the whole update is zero extra security prompts.

Linux
    Downloads the ``.AppImage`` and offers to start it.  Here the reason
    is simpler: from inside an AppImage, handing a URL to the desktop's
    browser opener is unreliable enough that the Download button did
    nothing at all, with no error, for a tester across four releases.  We
    can always fetch a file; we cannot always open a browser.
"""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request

from . import net
from .config import GITHUB_REPO

REQUEST_TIMEOUT = 5
# Generous cap for the installer download itself — the Windows setup exe
# is a few hundred MB (bundled Python + whisper stack) and GitHub's CDN
# can be slow; this is a per-read timeout, not a whole-download one.
DOWNLOAD_TIMEOUT = 60
_CHUNK = 256 * 1024

# The Windows release asset build.ps1/ISCC produce:
# Pinball_Asset_Decryptor_v{X.Y.Z}_Windows.exe (see pinball_decryptor.iss
# OutputBaseFilename).
_WINDOWS_ASSET_SUFFIX = "_windows.exe"

# Lowercased name suffix of the release asset each platform downloads
# (build_macos.sh names DMGs by arch; PyInstaller can't cross-build, so
# an Apple Silicon user must wait for the AppleSilicon DMG specifically).
_MAC_ARM_SUFFIX = "_macos_applesilicon.dmg"
_MAC_INTEL_SUFFIX = "_macos_intel.dmg"
_LINUX_ASSET_SUFFIX = ".appimage"


def _release_ready(data, platform=None, machine=None):
    """True when the latest release is complete enough to announce to
    *this* platform: it has release notes and the installer asset this
    platform would download.

    The GitHub release row exists the moment the tag + notes are
    published, but CI uploads the installers minutes later (longer when
    an upload fails and needs a re-run) — v0.69.5's banner pointed at a
    release page with no downloads on it.  Each platform gates on its
    own asset because the four installers upload from independent CI
    jobs that finish (or fail) separately.
    """
    if not (data.get("body") or "").strip():
        return False
    plat = platform if platform is not None else sys.platform
    if plat == "win32":
        suffix = _WINDOWS_ASSET_SUFFIX
    elif plat == "darwin":
        import platform as _plat_mod
        mach = (machine if machine is not None
                else _plat_mod.machine()).lower()
        suffix = _MAC_ARM_SUFFIX if mach == "arm64" else _MAC_INTEL_SUFFIX
    else:
        suffix = _LINUX_ASSET_SUFFIX
    return any((asset.get("name") or "").lower().endswith(suffix)
               and asset.get("browser_download_url")
               for asset in data.get("assets") or [])


def _parse_version(version_str):
    v = version_str.strip().lstrip("v")
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


def _pick_installer_asset(assets, platform=None, machine=None):
    """The release asset the app can fetch for the running platform, or None.

    Returns ``{"name", "url", "size", "sha256", "kind"}`` — ``sha256``
    comes from the GitHub asset ``digest`` field ("sha256:<hex>", present
    on newer uploads) and is ``None`` when the API doesn't provide one.

    ``kind`` says what the caller may then DO with the file, and the two
    are not the same thing:

    ``windows-installer``
        The Inno setup exe, run silently over the top (see
        :func:`launch_installer_windows`).

    ``appimage``
        The Linux AppImage.  There is nothing to install — the file *is*
        the app — so the caller saves it and offers to start it.  Linux
        is here at all because the browser-download flow it used to have
        was not a flow: inside an AppImage the desktop's URL opener
        inherits a bundle environment it can't run in, and the banner's
        Download button did nothing at all, silently, for a tester across
        v0.85 through v0.88.  Fetching the file ourselves needs no
        browser, so there is nothing left to fail.

    ``macos-dmg``
        The disk image.  Mounted, the bundle inside it copied over the
        installed one, and the app relaunched — see
        :func:`install_update_macos`.

        THIS USED TO RETURN ``None``, on the reasoning that macOS ``open``
        works fine from a bundle and "a .dmg still has to be mounted and
        dragged by hand, so downloading it for the user saves nothing".
        The second half is what was wrong, and it is the same point the
        Windows path is built on: ``com.apple.quarantine`` is applied by
        the DOWNLOADING application.  A browser sets it, ``urlopen`` does
        not.  So the browser handoff is precisely what produces "can't be
        opened because Apple cannot check it", the trip to Privacy &
        Security and the password — every release, forever.  Fetching the
        file ourselves removes the flag's cause rather than working around
        its effect, exactly as self-downloading dodges SmartScreen on
        Windows.  Mounting the image is a two-line job the app can do.
    """
    plat = platform if platform is not None else sys.platform
    if plat == "win32":
        suffix, kind = _WINDOWS_ASSET_SUFFIX, "windows-installer"
    elif plat.startswith("linux"):
        suffix, kind = _LINUX_ASSET_SUFFIX, "appimage"
    elif plat == "darwin":
        import platform as _plat_mod
        mach = (machine if machine is not None
                else _plat_mod.machine()).lower()
        suffix = _MAC_ARM_SUFFIX if mach == "arm64" else _MAC_INTEL_SUFFIX
        kind = "macos-dmg"
    else:
        return None
    matches = [a for a in assets or []
               if a.get("browser_download_url")
               and (a.get("name") or "").lower().endswith(suffix)]
    if not matches:
        return None
    asset = matches[0]
    if kind == "appimage":
        # CI names AppImages per arch (..._Linux_x86_64.AppImage). Only
        # x86_64 is built today, but an aarch64 user must never be handed
        # an x86_64 image just because it sorted first.
        import platform as _plat_mod
        mach = (machine if machine is not None
                else _plat_mod.machine()).lower()
        arch_matches = [a for a in matches
                        if mach and mach in (a.get("name") or "").lower()]
        if not arch_matches:
            return None
        asset = arch_matches[0]
    digest = asset.get("digest") or ""
    sha256 = (digest[len("sha256:"):]
              if digest.startswith("sha256:") else None)
    return {"name": asset["name"], "url": asset["browser_download_url"],
            "size": asset.get("size") or 0, "sha256": sha256, "kind": kind}


def check_for_update(current_version, repo=None, not_ready_cb=None):
    """Return (latest_version, download_url, notes, installer) if newer,
    else None.

    ``installer`` is :func:`_pick_installer_asset`'s dict when the app
    can fetch this platform's release asset itself, else ``None`` (the
    GUI then falls back to the plain open-in-browser Download button).

    A newer release whose installers haven't finished uploading (see
    :func:`_release_ready`) is treated as "no update yet" — the banner
    must never point at a download that isn't there.  ``not_ready_cb``,
    when given, is called with the withheld version string so the app
    can log/say "publishing now" instead of a false "up to date".

    Raises on network/API failure (URLError, timeout, bad JSON) so the
    caller can tell "couldn't check" apart from "checked, no newer
    version" — the app logs the two outcomes differently.
    """
    target_repo = repo or GITHUB_REPO
    url = f"https://api.github.com/repos/{target_repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Pinball-Asset-Decryptor-UpdateCheck",
        },
    )
    # net.urlopen, not a bare urlopen: the frozen macOS app has no
    # OpenSSL default CA path, so the default context can't verify
    # api.github.com and every check fails (see core/net.py).
    with net.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())

    tag = data.get("tag_name", "")
    html_url = data.get("html_url", "")
    if not tag or not html_url:
        return None

    latest = _parse_version(tag)
    current = _parse_version(current_version)
    if latest and current and latest > current:
        if not _release_ready(data):
            if not_ready_cb:
                not_ready_cb(tag.lstrip("v"))
            return None
        return (tag.lstrip("v"), html_url, data.get("body", "") or "",
                _pick_installer_asset(data.get("assets")))
    return None


def download_installer(url, dest_path, *, expected_sha256=None,
                       progress_cb=None, cancel_cb=None, opener=None):
    """Stream the installer to ``dest_path``; return the total bytes read.

    ``progress_cb(bytes_done)`` fires per chunk; ``cancel_cb()`` truthy
    aborts.  A cancelled, short, or digest-mismatched download deletes
    the partial file and raises — never leave a half-written exe where
    the caller might run it.
    """
    do_open = opener or net.urlopen
    req = urllib.request.Request(
        url, headers={"User-Agent": "Pinball-Asset-Decryptor-UpdateCheck"})
    digest = hashlib.sha256()
    done = 0
    try:
        with do_open(req, timeout=DOWNLOAD_TIMEOUT) as resp, \
                open(dest_path, "wb") as out:
            while True:
                if cancel_cb and cancel_cb():
                    raise InterruptedError("download cancelled")
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done)
        if expected_sha256 and digest.hexdigest() != expected_sha256:
            raise ValueError(
                "installer download failed integrity check "
                f"(sha256 {digest.hexdigest()[:12]}… != published "
                f"{expected_sha256[:12]}…)")
    except BaseException:
        try:
            os.unlink(dest_path)
        except OSError:
            pass
        raise
    return done


# Inno Setup switches for the unattended install-over-the-top:
#   /SILENT                   progress window only, no wizard
#   /NORESTART                never reboot out from under the user
#   /FORCECLOSEAPPLICATIONS   let Setup close our python process if it's
#                             somehow still holding files when the copy
#                             starts (we exit right after launching, but
#                             this makes the race harmless)
#   /RELAUNCH=1               custom flag the .iss reads to reopen the
#                             app when the silent install finishes
#   /MERGETASKS="!runprereqs" Inno remembers task selections per AppId,
#                             so a user who ticked "Install prerequisites"
#                             on their first install would silently re-run
#                             the whole WSL2/partclone/gpg pass on every
#                             in-app update.  Force it off here (the app
#                             probes prereqs at runtime and offers
#                             "Install Missing" if any are actually gone);
#                             MERGETASKS keeps the user's other remembered
#                             choices (e.g. desktop icon) intact.
INSTALLER_ARGS = ('/SILENT /NORESTART /FORCECLOSEAPPLICATIONS /RELAUNCH=1 '
                  '/MERGETASKS="!runprereqs"')


def launch_installer_windows(path, shell_execute=None):
    """Run the downloaded setup exe unattended; True on successful launch.

    Uses ShellExecuteW so the exe's requireAdministrator manifest is
    honoured.  The app itself already runs elevated (launcher.vbs), so
    no UAC prompt appears; if it ever runs unelevated, the same call
    just raises the standard consent dialog instead of failing.
    """
    if shell_execute is None:
        import ctypes
        shell_execute = ctypes.windll.shell32.ShellExecuteW  # noqa
    ret = shell_execute(None, "open", str(path), INSTALLER_ARGS, None, 1)
    # Per the ShellExecute contract, values > 32 mean success.
    return int(ret) > 32


def macos_app_bundle(start=None):
    """The ``.app`` this process is running from, or None.

    Walks up from the executable rather than guessing ``/Applications``: the
    user may have put the bundle anywhere, and replacing the wrong copy is a
    far worse outcome than declining to update.
    """
    p = os.path.abspath(start or sys.executable)
    while True:
        if p.endswith(".app"):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


#: Swaps the bundle once this process has exited, then starts the new one.
#: A SEPARATE PROCESS is not a style choice: a running app cannot delete the
#: bundle it is executing from, so something has to outlive it.  `kill -0`
#: polls for the pid rather than sleeping a guessed interval; the script
#: removes itself last so nothing is left in the temp directory.
_MAC_SWAP_SCRIPT = """#!/bin/sh
while kill -0 %(pid)d 2>/dev/null; do sleep 0.3; done
rm -rf %(old)s.old
mv %(old)s %(old)s.old || exit 1
mv %(new)s %(old)s || { mv %(old)s.old %(old)s; exit 1; }
rm -rf %(old)s.old
open %(old)s
rm -f "$0"
"""


def install_update_macos(dmg_path, bundle=None, run=None, popen=None,
                         pid=None):
    """Replace the running ``.app`` with the one inside *dmg_path*.

    Returns ``(True, "")`` once the swap has been handed to a detached helper,
    or ``(False, reason)`` with nothing changed.

    NO GATEKEEPER PROMPT COMES OUT OF THIS, which is the entire point.  The
    quarantine flag that produces "can't be opened because Apple cannot check
    it for malicious software" is set by whatever downloads a file; the app's
    own ``urlopen`` does not set it, so the bundle copied out of this image
    was never quarantined.  The ``xattr -dr`` below is belt and braces for an
    image that arrived some other way.

    The swap runs after this process exits (see ``_MAC_SWAP_SCRIPT``) and moves
    the old bundle aside before moving the new one in, so a failure at the last
    step puts the working app back rather than leaving no app at all.
    """
    import shutil
    import stat
    import tempfile

    run = run or subprocess.run
    popen = popen or subprocess.Popen
    bundle = bundle or macos_app_bundle()
    if not bundle:
        return False, "could not work out which application bundle to replace"
    parent = os.path.dirname(bundle)
    if not os.access(parent, os.W_OK):
        # The one case that genuinely needs a password.  Say so and let the
        # caller fall back to the browser rather than half-doing it.
        return False, "%s is not writable by you" % parent

    mnt = tempfile.mkdtemp(prefix="pad-update-")
    staged = os.path.join(parent, ".%s.new" % os.path.basename(bundle))
    try:
        r = run(["hdiutil", "attach", "-nobrowse", "-readonly",
                 "-mountpoint", mnt, str(dmg_path)],
                capture_output=True, text=True)
        if getattr(r, "returncode", 1) != 0:
            return False, ("could not mount the disk image: %s"
                           % (getattr(r, "stderr", "") or "").strip())
        try:
            apps = sorted(n for n in os.listdir(mnt) if n.endswith(".app"))
            if not apps:
                return False, "the disk image contains no application"
            shutil.rmtree(staged, ignore_errors=True)
            r = run(["ditto", os.path.join(mnt, apps[0]), staged],
                    capture_output=True, text=True)
            if getattr(r, "returncode", 1) != 0:
                shutil.rmtree(staged, ignore_errors=True)
                return False, ("could not copy the new version out of the "
                               "image: %s"
                               % (getattr(r, "stderr", "") or "").strip())
        finally:
            run(["hdiutil", "detach", mnt, "-quiet"],
                capture_output=True, text=True)
    finally:
        shutil.rmtree(mnt, ignore_errors=True)

    run(["xattr", "-dr", "com.apple.quarantine", staged],
        capture_output=True, text=True)

    fd, script = tempfile.mkstemp(prefix="pad-swap-", suffix=".sh")
    with os.fdopen(fd, "w", newline="\n") as f:
        f.write(_MAC_SWAP_SCRIPT % {
            "pid": pid if pid is not None else os.getpid(),
            "old": _shquote(bundle), "new": _shquote(staged)})
    os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
    popen(["/bin/sh", script], start_new_session=True)
    return True, ""


def _shquote(path):
    """Single-quote *path* for /bin/sh — bundle paths contain spaces."""
    return "'" + str(path).replace("'", "'\\''") + "'"
