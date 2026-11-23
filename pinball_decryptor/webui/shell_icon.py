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
CLASS_NAME = "Pinball card image icon"


def _pkg():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sources(pkg=None):
    """``[(name, path)]`` of the three files a staged handler is made of."""
    pkg = pkg or _pkg()
    return [(DLL, os.path.join(pkg, "shell", DLL)),
            (ICON, os.path.join(pkg, ICON)),
            (ICON_COMPACT, os.path.join(pkg, ICON_COMPACT))]


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


def handler_values(progid):
    """The rows that hand *progid*'s icon to the handler."""
    return [(progid + r"\DefaultIcon", "", "%1"),
            (progid + r"\ShellEx\IconHandler", "", CLSID)]


def icon_for(path):
    """The icon file a staged handler would name for *path* (the same rule,
    in Python): what a test or a proof compares the DLL's answer with."""
    from ..core import sparse_card
    return ICON_COMPACT if sparse_card.takes_less(path) else ICON
