"""The app's entries on Windows 11's SHORT right-click menu (PAD-1523).

Windows 11's first right-click menu lists none of the verbs the app writes
for card images (webui/open_image.py) but the file type's default one, so
"Compact with PAD" was only under "Show more options".  What that menu does
list are handlers a PACKAGE declares; ``pinball_decryptor/shell/padmenu.msix``
(tools/padmenu) is a sparse package that declares ``padmenu64.dll``, a
handler that shows "Compact with PAD" there, with its icon, on a card that
is not compact yet, and runs the same verb the classic menu runs (it reads
label, icon and command from the registry, so the two cannot disagree).
"Write to a card with PAD" needs nothing: as a ``.raw``'s default verb it is
already the first entry of that menu.

Windows lists a packaged entry under "Show more options" too, so while the
package is registered the classic Compact verb is marked
``ProgrammaticAccessOnly`` (:func:`hide_classic`): out of every menu, still
there for the handler to read.  Without the package it shows as before.

Per user, like the verbs it bridges to: :func:`register` stages the DLL under
``%LOCALAPPDATA%\\pinball_decryptor\\shell_menu\\<hash>`` (the surrogate that
loads it keeps it open, and an open file in the install folder would stop an
update) and adds the package with that folder as its external location.
The package is signed with the app's own certificate, which the installer
puts in the machine's Trusted People; without it there (a checkout, an
install from before it) Windows would refuse the package, so nothing is
tried.  Windows 10 has no short menu and keeps the classic verbs alone.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)

#: the package's name (tools/padmenu/AppxManifest.xml Identity Name)
NAME = "PinballAssetDecryptor.ShellMenu"
DLL = "padmenu64.dll"
MSIX = "padmenu.msix"
CER = "padmenu.cer"
STAMP = "padmenu64.json"
#: the record of what this user has registered, in the stage root
RECORD = "registered.json"
#: Windows 11's first build: the short menu came with it
FIRST_BUILD = 22000
#: where Windows lists a user's packages (one key per package full name)
REPOSITORY = (r"Software\Classes\Local Settings\Software\Microsoft\Windows"
              r"\CurrentVersion\AppModel\Repository\Packages")
#: where the machine's Trusted People certificates live, by thumbprint
TRUSTED_PEOPLE = (r"SOFTWARE\Microsoft\SystemCertificates\TrustedPeople"
                  r"\Certificates")
_NO_WINDOW = 0x08000000                                  # CREATE_NO_WINDOW


def _shell_dir(pkg=None):
    pkg = pkg or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(pkg, "shell")


def stamp(pkg=None):
    """The shipped build's stamp (version, thumbprint, hashes), or {}"""
    try:
        with open(os.path.join(_shell_dir(pkg), STAMP), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def stage_root():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "pinball_decryptor", "shell_menu")


def windows_build():
    """This Windows' build number, 0 off Windows"""
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except AttributeError:
        return 0


def supported():
    """Whether this PC has the short menu and can load the handler"""
    from . import shell_icon
    return windows_build() >= FIRST_BUILD and shell_icon.supported()


def trusted(thumbprint):
    """Whether the machine trusts the package's certificate (the installer
    puts it there).  Read from the registry: no PowerShell for a no."""
    if not thumbprint or sys.platform != "win32":
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            TRUSTED_PEOPLE + "\\" + thumbprint.upper()))
        return True
    except OSError:
        return False


def installed(version=None):
    """Full names of this user's registered copies of the package (only
    the given *version*'s, with one)."""
    if sys.platform != "win32":
        return []
    import winreg
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REPOSITORY) as k:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                if name.startswith(NAME + "_") and (
                        version is None
                        or name.split("_")[1] == version):
                    out.append(name)
    except OSError:
        pass
    return out


def stage(pkg=None, root=None):
    """Copy the handler where its surrogate may keep it open; the staged
    folder, or None.  Never raises."""
    try:
        src = os.path.join(_shell_dir(pkg), DLL)
        h = hashlib.sha256()
        for name in (DLL, MSIX):
            with open(os.path.join(_shell_dir(pkg), name), "rb") as f:
                h.update(f.read())
        root = root or stage_root()
        folder = os.path.join(root, h.hexdigest()[:12])
        os.makedirs(folder, exist_ok=True)
        dst = os.path.join(folder, DLL)
        if not (os.path.isfile(dst)
                and os.path.getsize(dst) == os.path.getsize(src)):
            shutil.copyfile(src, dst + ".tmp")
            os.replace(dst + ".tmp", dst)
        return folder
    except OSError:
        log.warning("short-menu handler not staged", exc_info=True)
        return None


def _sweep(root, keep=None):
    """Take other versions' folders away; one still held stays for later"""
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        folder = os.path.join(root, name)
        if not os.path.isdir(folder) or (
                keep and os.path.normcase(folder) == os.path.normcase(keep)):
            continue
        try:
            dll = os.path.join(folder, DLL)
            if os.path.exists(dll):
                os.remove(dll)
            shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def _record(root):
    try:
        with open(os.path.join(root, RECORD), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _ps(script, timeout=120):
    """Run *script* in a hidden PowerShell; (ok, its last error line)"""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    err = [ln for ln in (r.stderr or "").splitlines() if ln.strip()]
    return r.returncode == 0, (err[0] if err else "")


def _q(path):
    return "'" + path.replace("'", "''") + "'"


def hide_classic(hide):
    """Take the classic Compact verb off the menus (*hide*) or put it back.
    Never raises."""
    if sys.platform != "win32":
        return
    import winreg
    from . import open_image
    for ext in open_image.COMPACT_EXTENSIONS:
        path = r"%s\SystemFileAssociations\%s\shell\%s" % (
            open_image.CLASSES, ext, open_image.COMPACT_VERB)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                                winreg.KEY_SET_VALUE) as k:
                if hide:
                    winreg.SetValueEx(k, "ProgrammaticAccessOnly", 0,
                                      winreg.REG_SZ, "")
                else:
                    winreg.DeleteValue(k, "ProgrammaticAccessOnly")
        except OSError:
            pass


def register(pkg=None, root=None):
    """Put the app's entries on this user's short menu; True when it
    changed anything.  Never raises."""
    try:
        return _register(pkg, root)
    except Exception:                                   # noqa: BLE001
        log.warning("short-menu entries not registered", exc_info=True)
        return False


def _register(pkg, root):
    if not supported():
        hide_classic(False)
        return False
    info = stamp(pkg)
    version = info.get("version")
    if not version or not trusted(info.get("thumbprint")):
        log.info("short-menu entries skipped: the package's certificate "
                 "is not trusted here (the installer adds it)")
        hide_classic(bool(installed()))
        return False
    root = root or stage_root()
    folder = stage(pkg, root)
    if not folder:
        hide_classic(bool(installed()))
        return False
    rec = _record(root)
    if (rec.get("version") == version
            and os.path.normcase(rec.get("folder", "")) ==
            os.path.normcase(folder)
            and installed(version)):
        hide_classic(True)
        _sweep(root, keep=folder)
        return False
    msix = os.path.join(_shell_dir(pkg), MSIX)
    # an older copy goes first: a sparse package's folder is fixed when it
    # is added, and this one's may be another
    script = ("$ErrorActionPreference = 'Stop'; "
              "Get-AppxPackage -Name %s | Remove-AppxPackage; "
              "Add-AppxPackage -Path %s -ExternalLocation %s"
              % (NAME, _q(msix), _q(folder)))
    ok, err = _ps(script)
    if not ok:
        log.warning("short-menu package not added: %s", err)
        hide_classic(bool(installed()))
        return False
    hide_classic(True)
    try:
        with open(os.path.join(root, RECORD), "w", encoding="utf-8") as f:
            json.dump({"version": version, "folder": folder}, f)
    except OSError:
        pass
    _sweep(root, keep=folder)
    log.info("short-menu entries registered (package %s)", version)
    return True


def unregister(root=None):
    """Take the package away for this user, and its staged copies.  Never
    raises; True when there was one."""
    root = root or stage_root()
    hide_classic(False)
    had = bool(installed())
    if had:
        ok, err = _ps("Get-AppxPackage -Name %s | Remove-AppxPackage" % NAME)
        if not ok:
            log.warning("short-menu package not removed: %s", err)
    try:
        os.remove(os.path.join(root, RECORD))
    except OSError:
        pass
    _sweep(root)
    try:
        os.rmdir(root)
    except OSError:
        pass
    return had
