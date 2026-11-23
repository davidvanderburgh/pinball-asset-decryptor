"""A card image's icon in Explorer says whether it is stored compact
(PAD-1522).

A compact card (core.sparse_card) is the same ``.raw`` as a full-size one,
so nothing on a desktop of cards said which were already compact.  Windows
draws one icon per file TYPE unless a shell icon handler answers per file;
``pinball_decryptor/shell/padicon64.dll`` (tools/padicon) is that handler.
Explorer asks it for each card image, and it names ``card_image.ico`` or,
for a card that takes less disk than its size, ``card_image_compact.ico``.

Explorer loads the handler into its own process and keeps it open, so it is
never run from the install folder (an open file there would stop an update):
:func:`stage` copies the DLL and the two icons to
``%LOCALAPPDATA%\\pinball_decryptor\\shell\\<hash>`` and that copy is what is
registered.  A new version gets a new folder; the old one goes once nothing
holds it.

The badge itself is an icon OVERLAY where Explorer has one loaded
(PAD-1526).  Explorer keeps the icon it was given for a file for as long as
the file's name, size and modified time stay the same, and compacting or
expanding a card changes none of them, so an icon that carried the badge
stayed wrong in an open window until Explorer restarted.  An overlay is
asked again whenever Explorer is told the file changed
(sparse_card.shell_refresh).  The same class is the overlay identifier
(:func:`overlay_values`, one key under HKEY_LOCAL_MACHINE, so only an
Administrator run can write it); Explorer reads that list when it starts, so
a freshly registered overlay shows from the next sign-in.  Until then, and on
a machine whose overlay slots other programs have filled, the icon carries
the badge as before.

Windows on ARM runs a native Explorer that cannot load this x64 DLL, and
there the card keeps its one plain icon (:func:`supported`).
"""

import hashlib
import logging
import os
import shutil
import sys

log = logging.getLogger(__name__)

#: the handler's class id; tools/padicon/padicon.c CLSID_PadCardIcon and the
#: uninstaller (installer/pinball_decryptor.iss) name the same one
CLSID = "{6E1B5C0A-52D4-4F0B-9C55-1A1522CA4D01}"
DLL = "padicon64.dll"
ICON = "card_image.ico"
ICON_COMPACT = "card_image_compact.ico"
#: the compact badge alone: the overlay Explorer draws over the plain card
ICON_BADGE = "card_compact_badge.ico"
#: where Windows lists icon overlay identifiers (HKEY_LOCAL_MACHINE only)
OVERLAY_KEY = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer"
               r"\ShellIconOverlayIdentifiers")
#: our name in that list.  Windows takes the list in name order and stops
#: when its slots are full, so the leading spaces sort it early;
#: tools/padicon/padicon.c OVERLAY_NAME says the same
OVERLAY_NAME = "     PinballCardCompact"
CLASS_NAME = "Pinball card image icon"


def _pkg():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sources(pkg=None):
    """``[(name, path)]`` of the files a staged handler is made of."""
    pkg = pkg or _pkg()
    return [(DLL, os.path.join(pkg, "shell", DLL)),
            (ICON, os.path.join(pkg, ICON)),
            (ICON_COMPACT, os.path.join(pkg, ICON_COMPACT)),
            (ICON_BADGE, os.path.join(pkg, ICON_BADGE))]


def stage_root():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "pinball_decryptor", "shell")


def _native_arm64():
    """True on Windows on ARM, whatever this Python was built for."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        proc, native = ctypes.c_ushort(0), ctypes.c_ushort(0)
        if not k32.IsWow64Process2(ctypes.c_void_p(k32.GetCurrentProcess()),
                                   ctypes.byref(proc), ctypes.byref(native)):
            return False
        return native.value == 0xAA64
    except Exception:                                   # noqa: BLE001
        return False


def supported():
    """Whether this PC's Explorer can load the handler."""
    return sys.platform == "win32" and not _native_arm64()


def stage(pkg=None, root=None):
    """Copy the handler and its icons where Explorer may keep them open;
    returns the staged DLL's path, or None when it cannot be (a file missing
    from this build, no room, no rights).  The same files stage to the same
    folder, so a second call changes nothing.  Never raises."""
    try:
        files = sources(pkg)
        h = hashlib.sha256()
        for _name, path in files:
            with open(path, "rb") as f:
                h.update(f.read())
        root = root or stage_root()
        folder = os.path.join(root, h.hexdigest()[:12])
        os.makedirs(folder, exist_ok=True)
        for name, path in files:
            dst = os.path.join(folder, name)
            if os.path.isfile(dst) and \
                    os.path.getsize(dst) == os.path.getsize(path):
                continue
            tmp = dst + ".tmp"
            shutil.copyfile(path, tmp)
            os.replace(tmp, dst)
        _sweep(root, keep=folder)
        return os.path.join(folder, DLL)
    except OSError:
        log.warning("card icon handler not staged", exc_info=True)
        return None


def _sweep(root, keep=None):
    """Take the other versions' folders away; one Explorer still holds stays
    (its files refuse) and goes on a later start."""
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        folder = os.path.join(root, name)
        if keep and os.path.normcase(folder) == os.path.normcase(keep):
            continue
        if not os.path.isdir(folder):
            continue
        try:
            # the DLL first: when Explorer holds it, nothing else is touched
            dll = os.path.join(folder, DLL)
            if os.path.exists(dll):
                os.remove(dll)
            shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def unstage(root=None):
    """Remove every staged copy that nothing holds.  Never raises."""
    _sweep(root or stage_root())
    try:
        os.rmdir(root or stage_root())
    except OSError:
        pass


def class_values(dll):
    """``[(key under ...\\Software\\Classes, value name, data)]`` that make
    *dll* the class Explorer loads."""
    base = "CLSID\\" + CLSID
    return [(base, "", CLASS_NAME),
            (base + r"\InprocServer32", "", dll),
            (base + r"\InprocServer32", "ThreadingModel", "Apartment")]


def overlay_values():
    """``[(key under HKEY_LOCAL_MACHINE, value name, data)]`` that list the
    class as an icon overlay identifier."""
    return [(OVERLAY_KEY + "\\" + OVERLAY_NAME, "", CLSID)]


def handler_values(progid):
    """The rows that hand *progid*'s icon to the handler."""
    return [(progid + r"\DefaultIcon", "", "%1"),
            (progid + r"\ShellEx\IconHandler", "", CLSID)]


def icon_for(path):
    """The icon file a staged handler would name for *path* (the same rule,
    in Python): what a test or a proof compares the DLL's answer with."""
    from ..core import sparse_card
    return ICON_COMPACT if sparse_card.takes_less(path) else ICON


# ----------------------------------------------------------------------
# is Explorer drawing the badge yet?  (PAD-1526)
# ----------------------------------------------------------------------
#: overlay identifiers Windows loads, in name order (padicon.c OVERLAY_SLOTS)
OVERLAY_SLOTS = 11


def _overlay_written():
    """When our overlay key was last written, as a Windows file time (100 ns
    since 1601), or None when it is not listed or sorts past the slots
    Windows loads."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, OVERLAY_KEY) as k:
            names = []
            for i in range(winreg.QueryInfoKey(k)[0]):
                names.append(winreg.EnumKey(k, i))
        mine = OVERLAY_NAME.lower()
        if mine not in [n.lower() for n in names]:
            return None
        if sum(1 for n in names if n.lower() < mine) >= OVERLAY_SLOTS:
            return None
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            OVERLAY_KEY + "\\" + OVERLAY_NAME) as k:
            return winreg.QueryInfoKey(k)[2]
    except (ImportError, OSError):
        return None


def _explorer():
    """``(pid, start as a Windows file time)`` of the Explorer that is the
    desktop and taskbar, or None."""
    try:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        u32.GetShellWindow.restype = wintypes.HWND
        hwnd = u32.GetShellWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD(0)
        u32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if not pid.value:
            return None
        k32.OpenProcess.restype = wintypes.HANDLE
        # PROCESS_QUERY_LIMITED_INFORMATION
        h = k32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return None
        try:
            made, a, b, c = (wintypes.FILETIME() for _ in range(4))
            if not k32.GetProcessTimes(wintypes.HANDLE(h), ctypes.byref(made),
                                       ctypes.byref(a), ctypes.byref(b),
                                       ctypes.byref(c)):
                return None
            return pid.value, (made.dwHighDateTime << 32) | made.dwLowDateTime
        finally:
            k32.CloseHandle(wintypes.HANDLE(h))
    except Exception:                                   # noqa: BLE001
        return None


def badge_waits_for_explorer(written=None, explorer=None):
    """True when the compact badge is listed for Explorer but the Explorer
    that is running started before it was: it shows the badge live only once
    it has restarted (it reads the list when it starts).  False when the
    badge is live, when it is not listed at all, and off Windows."""
    if sys.platform != "win32":
        return False
    written = _overlay_written() if written is None else written
    if written is None:
        return False
    explorer = _explorer() if explorer is None else explorer
    if not explorer:
        return False
    return explorer[1] < written


def open_folders():
    """The folders Explorer has open in windows now, as paths it opens
    again (a drive path, or ``::{...}`` for a place like Home).  Empty when
    they cannot be listed (a Python without pywin32).  Never raises."""
    out = []
    try:
        import win32com.client
        for w in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                path = w.Document.Folder.Self.Path
            except Exception:                           # noqa: BLE001
                continue
            if path and path not in out:
                out.append(path)
    except Exception:                                   # noqa: BLE001
        return []
    return out


#: how long Explorer gets to close when asked, then to be back, in seconds
EXPLORER_CLOSE_WAIT = 6.0
EXPLORER_BACK_WAIT = 20.0


def _ask_explorer_to_exit(pid, wait):
    """Ask the desktop's Explorer to close the way its own "Exit Explorer"
    does (it saves its settings first); end it if it has not gone within
    *wait* seconds.  True once the process is gone."""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    # SYNCHRONIZE | PROCESS_TERMINATE
    h = k32.OpenProcess(0x00100000 | 0x0001, False, pid)
    if not h:
        return False
    try:
        u32.FindWindowW.restype = wintypes.HWND
        tray = u32.FindWindowW("Shell_TrayWnd", None)
        if tray:
            # the taskbar's own "Exit Explorer" (WM_USER + 436)
            u32.PostMessageW(wintypes.HWND(tray), 0x0400 + 436, 0, 0)
        if k32.WaitForSingleObject(wintypes.HANDLE(h),
                                   int(wait * 1000)) == 0:
            return True
        k32.TerminateProcess(wintypes.HANDLE(h), 1)
        return k32.WaitForSingleObject(wintypes.HANDLE(h), 5000) == 0
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


def _start_explorer():
    import subprocess
    windir = os.environ.get("SystemRoot") or os.environ.get("WINDIR") \
        or r"C:\Windows"
    subprocess.Popen([os.path.join(windir, "explorer.exe")], close_fds=True)


def _open_folder(path):
    import ctypes
    # SW_SHOWNOACTIVATE: the folders come back without taking the keyboard
    ctypes.windll.shell32.ShellExecuteW(None, "open", path, None, None, 4)


def restart_explorer(sleep=None):
    """Restart the Explorer that is the desktop and taskbar, and open the
    folder windows it had again.  It is asked to close (ended if it will
    not), started again when Windows has not already done so, and each
    folder that was open and did not come back by itself is opened.  True
    when a new Explorer is the desktop.  Never raises.

    Only for a run that is NOT elevated: an Explorer started by an
    Administrator process would be one too."""
    if sys.platform != "win32":
        return False
    import time
    sleep = sleep or time.sleep
    try:
        old = _explorer()
        if not old:
            return False
        folders = open_folders()
        if not _ask_explorer_to_exit(old[0], EXPLORER_CLOSE_WAIT):
            return False
        new, started, waited = None, False, 0.0
        while waited < EXPLORER_BACK_WAIT:
            new = _explorer()
            if new and new[0] != old[0]:
                break
            new = None
            # Windows brings a shell that was ended back itself; one that
            # closed when asked stays away until it is started
            if not started and waited >= 2.0:
                _start_explorer()
                started = True
            sleep(0.25)
            waited += 0.25
        if not new:
            return False
        if folders:
            sleep(2.0)                  # let it open what it restores itself
            back = open_folders()
            for path in folders:
                if path not in back:
                    _open_folder(path)
        return True
    except Exception:                                   # noqa: BLE001
        log.warning("Explorer not restarted", exc_info=True)
        return False
