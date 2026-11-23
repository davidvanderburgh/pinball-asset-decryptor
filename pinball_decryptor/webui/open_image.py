"""A card image double-clicked in Explorer opens on its write dialog (PAD-1514).

The installer registers PAD for card images (``.raw`` / ``.img`` / ``.iso``),
so Explorer starts the app with the image's path on its command line.  The
app then picks the manufacturer (and era) the image belongs to and opens the
"Flash image" dialog with that image already in it: the only things left are
the SD card / USB stick and the Write button.

A PAD already running takes the image itself: the new launch hands the path
to it through :func:`link_path` (the running app's port and session token,
the same shape as the agent link, PAD-844) and exits, so two copies of the
app never fight over the settings file.

PAD-1522 adds two things to the same registration.  A ``.raw`` / ``.img``
has "Compact with PAD" on its right-click menu, which stores that card
compact where it is in a small window of its own (webui/compact_window.py;
no app window, no Administrator prompt).  And a card's icon says whether it
is already compact: Explorer asks PAD's icon handler per file
(webui/shell_icon.py).
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

from ..core import config

log = logging.getLogger(__name__)

#: the file extensions the installer registers (installer/pinball_decryptor.iss)
IMAGE_EXTENSIONS = (".raw", ".img", ".iso")


def image_arg(argv):
    """The image path on a command line: the first argument that is not a
    flag and is an existing file, else ``None``."""
    for a in argv or ():
        if not a or a.startswith("-"):
            continue
        p = os.path.abspath(a.strip('"'))
        if os.path.isfile(p):
            return p
    return None


def link_path():
    """Where the running app says how a second launch reaches it."""
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), "instance.json")


def write_link(ctx, port):
    path = link_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = {"port": int(port), "token": ctx.token, "pid": os.getpid(),
            "written": time.time()}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f)
    os.replace(tmp, path)
    return path


def remove_link(ctx):
    """Take the link away; only this app's own."""
    path = link_path()
    try:
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
    except (OSError, ValueError):
        return False
    if body.get("token") != getattr(ctx, "token", None):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _pid_alive(pid):
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFO
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == 259                    # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def hand_to_running(path, timeout=10.0):
    """Give *path* to a PAD that is already open.  True when it took it
    (this launch should then exit); False when there is none to take it."""
    try:
        with open(link_path(), encoding="utf-8") as f:
            link = json.load(f)
        port, token, pid = int(link["port"]), str(link["token"]), link["pid"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not _pid_alive(pid):
        return False
    if sys.platform == "win32":
        # a window may only come forward when the launch that asks lets it
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(int(pid))
        except Exception:                               # noqa: BLE001
            pass
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api" % port,
        data=json.dumps({"m": "shell.open_image", "a": [path],
                         "k": {}}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-PAD-Token": token},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reply = json.loads(resp.read().decode("utf-8") or "null")
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return bool(isinstance(reply, dict) and reply.get("ok"))


def detect(manufacturers, path):
    """``(manufacturer, game)`` for the image, or ``(None, None)``: the
    first loaded manufacturer whose detect() reads it."""
    for m in manufacturers:
        try:
            g = m.detect(path)
        except Exception:                               # noqa: BLE001
            continue
        if g:
            return m, g
    return None, None


# ----------------------------------------------------------------------
# Explorer's file association (Windows, per user)
# ----------------------------------------------------------------------
#: the ProgID PAD registers; the uninstaller removes it by this name
PROGID = "PinballAssetDecryptor.CardImage"
#: the right-click verb on every card image
VERB = "PinballAssetDecryptor.Write"
#: the one extension PAD becomes the double-click for.  ``.img`` and ``.iso``
#: belong to Windows' own "Mount" for every other disc image, so PAD only
#: joins their Open with list and right-click menu there.
DEFAULT_FOR = (".raw",)
#: the right-click verb that stores a card compact where it is (PAD-1522),
#: on the extensions core.sparse_card calls a card image
COMPACT_VERB = "PinballAssetDecryptor.Compact"
COMPACT_LABEL = "Compact with PAD"
COMPACT_EXTENSIONS = (".raw", ".img")
#: the launcher's flag for it; launcher.vbs starts this one without the
#: Administrator prompt
COMPACT_FLAG = "--compact"
#: the double-click verb's key under the ProgID, and what it was before
#: PAD-1522 gave it VERB's name (registrations from v1.573 on have that one)
OPEN_KEY = "\\shell\\" + VERB
LEGACY_OPEN_KEY = r"\shell\open"


def _del_tree(root, path):
    """Delete registry key *path* and everything under it; True when there
    was one and it is gone.  Never raises."""
    import winreg
    try:
        with winreg.OpenKey(root, path, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as k:
            while True:
                try:
                    child = winreg.EnumKey(k, 0)
                except OSError:
                    break
                if not _del_tree(root, path + "\\" + child):
                    break
        winreg.DeleteKey(root, path)
        return True
    except OSError:
        return False
#: what Explorer's Open with calls PAD
APP_NAME = "Pinball Asset Decryptor"
#: where Explorer keeps each user's own "Always use this app" per extension
FILEEXTS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"


def install_dir():
    """The installed app's folder (holding ``launcher.vbs``), or None for a
    checkout or a frozen Mac / Linux build."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    if os.path.isfile(os.path.join(here, "launcher.vbs")):
        return here
    return None


def association_values(app_dir, icon_dll=None):
    r"""``[(key under HKCU\Software\Classes, value name, data)]``.

    With *icon_dll* (the staged icon handler, shell_icon.stage) a card's
    icon is asked per file, so a compact card shows its own; without it
    every card has the one plain icon."""
    from . import shell_icon
    launcher = os.path.join(app_dir, "launcher.vbs")
    command = 'wscript.exe "%s" "%%1"' % launcher
    compact = 'wscript.exe "%s" "%s" "%%1"' % (launcher, COMPACT_FLAG)
    icon = os.path.join(app_dir, "pinball_decryptor", "icon.ico")
    # a card image gets a file's icon (an SD card), never the app's own: a
    # desktop of .raw files read as a row of PAD shortcuts (PAD-1518)
    file_icon = os.path.join(app_dir, "pinball_decryptor", "card_image.ico")
    if not os.path.isfile(file_icon) and os.path.isfile(icon):
        file_icon = icon
    compact_icon = os.path.join(app_dir, "pinball_decryptor",
                                shell_icon.ICON_COMPACT)
    if not os.path.isfile(compact_icon):
        compact_icon = icon
    rows = [
        (PROGID, "", "Pinball card image"),
        (PROGID + r"\DefaultIcon", "", file_icon),
        # the double-click verb carries the right-click verb's own NAME:
        # Windows lists a verb once per name, and named "open" here a .raw
        # that opens with PAD showed "Write to a card with PAD" twice
        # (PAD-1522)
        (PROGID + r"\shell", "", VERB),
        (PROGID + OPEN_KEY, "", "Write to a card with PAD"),
        # the command is wscript.exe, so without these Explorer's Open with
        # lists PAD as "Microsoft Windows Based Script Host" (PAD-1518)
        (PROGID + OPEN_KEY, "FriendlyAppName", APP_NAME),
        (PROGID + OPEN_KEY + r"\command", "", command),
        (PROGID + r"\Application", "ApplicationName", APP_NAME),
        (PROGID + r"\Application", "ApplicationIcon", icon),
        (PROGID + r"\Application", "ApplicationDescription",
         "Write a pinball card image to an SD card"),
    ]
    for ext in IMAGE_EXTENSIONS:
        rows.append((ext + r"\OpenWithProgids", PROGID, ""))
        base = r"SystemFileAssociations\%s\shell\%s" % (ext, VERB)
        rows += [(base, "", "Write to a card with PAD"),
                 (base, "Icon", icon),
                 (base + r"\command", "", command)]
    for ext in COMPACT_EXTENSIONS:
        base = r"SystemFileAssociations\%s\shell\%s" % (ext, COMPACT_VERB)
        rows += [(base, "", COMPACT_LABEL),
                 (base, "Icon", compact_icon),
                 (base + r"\command", "", compact)]
    if icon_dll:
        # after the plain DefaultIcon above: the later row is the one kept
        rows += shell_icon.handler_values(PROGID)
        rows += shell_icon.class_values(icon_dll)
    return rows


#: where the association lives under HKEY_CURRENT_USER (tests use their own)
CLASSES = r"Software\Classes"


def _notify():
    try:
        import ctypes
        # SHCNE_ASSOCCHANGED: Explorer re-reads the associations
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:                                   # noqa: BLE001
        pass


def release_windows_choice(ext, fileexts=None):
    """Forget the app the user once picked for *ext* in Windows' "Always use
    this app" when it is not PAD, so the extension's own default (PAD, once
    registered) opens it again.  Windows signs that choice, so no app can
    write its own name there; taking the stale one away is what is left, and
    only the gear switch does it (the user asked PAD to take the files).
    True when no other app's choice remains.  Never raises."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    root = winreg.HKEY_CURRENT_USER
    base = (fileexts or FILEEXTS) + "\\" + ext
    prog = windows_choice(ext, fileexts)
    if not prog or prog == PROGID:
        return True
    for sub in (r"UserChoiceLatest\ProgId", "UserChoiceLatest", "UserChoice"):
        try:
            winreg.DeleteKey(root, base + "\\" + sub)
        except FileNotFoundError:
            pass
        except OSError:
            log.warning("Windows' own choice for %s not released (%s)",
                        ext, sub, exc_info=True)
    return not windows_choice(ext, fileexts)


def windows_choice(ext=".raw", fileexts=None):
    """The ProgID of the user's own "Always use this app" for *ext*, or "".
    Newer Windows 11 builds record it under ``UserChoiceLatest\\ProgId`` and
    may write no ``UserChoice`` at all (seen on build 26300, PAD-1518);
    older ones only under ``UserChoice``."""
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    base = (fileexts or FILEEXTS) + "\\" + ext
    for sub in (r"UserChoiceLatest\ProgId", "UserChoice"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                base + "\\" + sub) as k:
                prog = winreg.QueryValueEx(k, "ProgId")[0]
        except OSError:
            continue
        if prog:
            return str(prog)
    return ""


def _machine_class(dll):
    r"""The icon handler's class under HKEY_LOCAL_MACHINE as well, when this
    run may write there (the installed app runs as Administrator).  Windows
    hides a user's own classes from elevated programs, PAD among them, so
    without this PAD's own file pickers would draw a card with no icon.
    Never raises; a run without the rights leaves it."""
    from . import shell_icon
    try:
        import winreg
        for sub, name, data in shell_icon.class_values(dll):
            path = CLASSES + "\\" + sub
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                    if winreg.QueryValueEx(k, name)[0] == data:
                        continue
            except OSError:
                pass
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, data)
    except (ImportError, OSError):
        pass


def register_association(app_dir=None, take_raw=False, classes=None,
                         fileexts=None, icon_dll=None):
    """Write the association for this user; True when anything changed.

    *icon_dll* is the icon handler to register (tests name their own); left
    out, the real registration stages the shipped one (shell_icon.stage).

    ``.raw`` becomes PAD's double-click when nothing else has it, or with
    *take_raw* (the user ticked it in the gear menu) whatever had it,
    Windows' own remembered choice included.  Never raises."""
    if sys.platform != "win32":
        return False
    app_dir = app_dir or install_dir()
    if not app_dir:
        return False
    try:
        import winreg
    except ImportError:
        return False
    classes = classes or CLASSES
    root = winreg.HKEY_CURRENT_USER
    changed = False
    if icon_dll is None and classes == CLASSES:
        from . import shell_icon
        if shell_icon.supported():
            icon_dll = shell_icon.stage()
        if icon_dll:
            _machine_class(icon_dll)

    def _put(sub, name, data):
        nonlocal changed
        path = classes + "\\" + sub
        try:
            with winreg.OpenKey(root, path) as k:
                if winreg.QueryValueEx(k, name)[0] == data:
                    return
        except OSError:
            pass
        with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, data)
        changed = True

    try:
        values = association_values(app_dir, icon_dll or None)
        # one value per (key, name): a later row replaces an earlier one
        last = {(sub, name): data for sub, name, data in values}
        for (sub, name), data in last.items():
            _put(sub, name, data)
        if _del_tree(root, classes + "\\" + PROGID + LEGACY_OPEN_KEY):
            changed = True
        for ext in DEFAULT_FOR:
            try:
                if classes == CLASSES:
                    current = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, ext)
                else:
                    current = winreg.QueryValue(root, classes + "\\" + ext)
            except OSError:
                current = ""
            if take_raw or not current or current == PROGID:
                _put(ext, "", PROGID)
    except OSError:
        log.warning("file association not written", exc_info=True)
    if take_raw and (classes == CLASSES or fileexts):
        for ext in DEFAULT_FOR:
            if raw_chosen_elsewhere(ext, fileexts):
                changed = release_windows_choice(ext, fileexts) or changed
    if changed and classes == CLASSES:
        _notify()
    return changed


def unregister_association(classes=None):
    """Take every key :func:`register_association` wrote away again (the
    uninstaller's RemoveTheFileAssociation does the same).  Never raises."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    classes = classes or CLASSES
    root = winreg.HKEY_CURRENT_USER

    def _del(path):
        _del_tree(root, path)

    for ext in IMAGE_EXTENSIONS:
        try:
            with winreg.OpenKey(root, classes + "\\" + ext + r"\OpenWithProgids",
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, PROGID)
        except OSError:
            pass
        for verb in (VERB, COMPACT_VERB):
            _del(r"%s\SystemFileAssociations\%s\shell\%s"
                      % (classes, ext, verb))
        try:
            with winreg.OpenKey(root, classes + "\\" + ext, 0,
                                winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                if winreg.QueryValueEx(k, "")[0] == PROGID:
                    winreg.DeleteValue(k, "")
        except OSError:
            pass
    _del(classes + "\\" + PROGID)
    from . import shell_icon
    _del(classes + r"\CLSID" + "\\" + shell_icon.CLSID)
    if classes == CLASSES:
        try:
            winreg.DeleteKey(
                winreg.HKEY_LOCAL_MACHINE,
                CLASSES + r"\CLSID" + "\\" + shell_icon.CLSID + r"\InprocServer32")
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE,
                             CLASSES + r"\CLSID" + "\\" + shell_icon.CLSID)
        except OSError:
            pass
        _notify()
        shell_icon.unstage()
    return True


def is_registered(classes=None):
    """Whether this user's Explorer has PAD's association."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    for key in (OPEN_KEY, LEGACY_OPEN_KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                (classes or CLASSES) + "\\" + PROGID
                                + key + r"\command"):
                return True
        except OSError:
            continue
    return False


def raw_chosen_elsewhere(ext=".raw", fileexts=None):
    """The program the user picked in Windows' own "Always use this app"
    for ``.raw`` when it is not PAD, else "".  Windows keeps that choice
    above anything an app writes; the gear switch takes it away
    (:func:`release_windows_choice`), so this names one only when that
    failed."""
    prog = windows_choice(ext, fileexts)
    if not prog or prog == PROGID:
        return ""
    return app_name(prog)


def raw_is_pads(ext=".raw", fileexts=None):
    """Whether Windows' own choice for *ext* is PAD: the double-click and the
    file's icon are PAD's only then, when any other app also opens *ext*."""
    return windows_choice(ext, fileexts) == PROGID


def ask_windows(ext=".raw"):
    """Open Windows' own "Select an app to open this file" for *ext* and
    wait for it to close.  Windows signs the choice it records there, so the
    user's click on PAD > Always is the one step no app can take for them;
    this brings that question up from PAD's own switch instead of leaving
    it for the next double-click in Explorer (PAD-1518).  Nothing is opened.
    Never raises."""
    if sys.platform != "win32":
        return False
    import tempfile
    folder = tempfile.mkdtemp(prefix="pad-card-")
    path = os.path.join(folder, "Pinball card image" + ext)
    try:
        import ctypes
        from ctypes import wintypes

        class OPENASINFO(ctypes.Structure):
            _fields_ = [("pcszFile", wintypes.LPCWSTR),
                        ("pcszClass", wintypes.LPCWSTR),
                        ("oaifInFlags", ctypes.c_int)]
        with open(path, "wb"):
            pass
        # ALLOW_REGISTRATION | REGISTER_EXT | FORCE_REGISTRATION, never EXEC
        info = OPENASINFO(path, None, 0x1 | 0x2 | 0x8)
        fn = ctypes.windll.shell32.SHOpenWithDialog
        fn.argtypes = [wintypes.HWND, ctypes.POINTER(OPENASINFO)]
        fn.restype = ctypes.c_long
        fn(None, ctypes.byref(info))
        return True
    except Exception:                                   # noqa: BLE001
        log.warning("Windows' app picker not shown", exc_info=True)
        return False
    finally:
        for p, rm in ((path, os.remove), (folder, os.rmdir)):
            try:
                rm(p)
            except OSError:
                pass


def app_name(prog):
    """What Windows calls the app behind *prog*, a UserChoice ProgId: a Store
    app's is ``AppX`` and 32 letters ("AppX9rkaq77s0jzh1tyccadx9ghba15r6t3h"
    is Photos), which says nothing to a reader (PAD-1518).  Falls back to the
    exe of an ``Applications\\foo.exe`` choice, then to *prog* itself."""
    name = _assoc_friendly_app_name(prog)
    if name:
        return name
    if prog.lower().startswith("applications\\"):
        return prog.split("\\", 1)[1]
    return prog


def _assoc_friendly_app_name(prog):
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        fn = ctypes.windll.shlwapi.AssocQueryStringW
        fn.argtypes = [ctypes.c_uint, ctypes.c_int, wintypes.LPCWSTR,
                       wintypes.LPCWSTR, wintypes.LPWSTR,
                       ctypes.POINTER(wintypes.DWORD)]
        fn.restype = ctypes.c_long
        size = wintypes.DWORD(512)
        buf = ctypes.create_unicode_buffer(size.value)
        # 4 = ASSOCSTR_FRIENDLYAPPNAME
        if fn(0, 4, prog, None, buf, ctypes.byref(size)) != 0:
            return ""
        return buf.value.strip()
    except Exception:                                   # noqa: BLE001
        return ""
