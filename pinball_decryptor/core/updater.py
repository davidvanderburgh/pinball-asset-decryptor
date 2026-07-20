"""Auto-update checker — checks the GitHub releases API on startup.

Also home to the Windows in-app installer flow ("Install update" on the
banner): the app downloads the release's ``*_Windows.exe`` itself and
runs it silently.  Downloading through the app instead of a browser
matters — files a browser saves carry the Mark-of-the-Web, so every
release (a brand-new unsigned binary with zero reputation) makes the
user re-run the SmartScreen "Windows protected your PC" gauntlet.  A
file the app writes has no MOTW, and the app already runs elevated
(launcher.vbs), so the whole update is zero extra security prompts.
"""

import hashlib
import json
import os
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


def _pick_installer_asset(assets, platform=None):
    """The release asset the running platform can auto-install, or None.

    Only Windows has an auto-install path today (silent Inno Setup
    install-over-the-top); macOS/Linux keep the browser-download flow.
    Returns ``{"name", "url", "size", "sha256"}`` — ``sha256`` comes from
    the GitHub asset ``digest`` field ("sha256:<hex>", present on newer
    uploads) and is ``None`` when the API doesn't provide one.
    """
    plat = platform if platform is not None else sys.platform
    if plat != "win32":
        return None
    for asset in assets or []:
        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")
        if not url or not name.lower().endswith(_WINDOWS_ASSET_SUFFIX):
            continue
        digest = asset.get("digest") or ""
        sha256 = (digest[len("sha256:"):]
                  if digest.startswith("sha256:") else None)
        return {"name": name, "url": url,
                "size": asset.get("size") or 0, "sha256": sha256}
    return None


def check_for_update(current_version, repo=None, not_ready_cb=None):
    """Return (latest_version, download_url, notes, installer) if newer,
    else None.

    ``installer`` is :func:`_pick_installer_asset`'s dict when this
    platform can auto-install the release, else ``None`` (the GUI then
    falls back to the plain open-in-browser Download button).

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
