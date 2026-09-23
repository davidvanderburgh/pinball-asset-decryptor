"""A window of the app's own with a taskbar button and icon of its own.

Spike 1's display and switch panel are pywebview windows IN THE APP'S
PROCESS (``emulate_jjp_spike1view.ViewWindows``), and that costs them twice:
pywebview gives every window of a process the one icon it was started with,
and Windows files every window of a process under one taskbar button unless a
window names a group of its own.  So they sat under the PAD button wearing
the PAD icon.  :func:`brand` fixes both for one window: the icon from the
rig's ``icons/`` (``installer/make_rig_icons.py``) and a per-window
AppUserModelID, the documented way to split a window into its own button.

The group names are shared with the playfield process (``pfweb.py`` names
itself :data:`PLAYFIELD`), so a switch panel and a playfield group together.

Windows only: everywhere else :func:`brand` does nothing and says so.
Nothing here raises; a window that cannot be branded keeps what it had.
"""

import ctypes
import logging
import os
import pathlib
import sys
import uuid

log = logging.getLogger(__name__)

#: where the icons are: the Spike 2 rig's folder, the one every packaging
#: carries (make_rig_icons.py says why)
ICONS = str(pathlib.Path(__file__).resolve().parents[2]
            / "tools" / "spike2_emu" / "icons")

#: taskbar groups.  PLAYFIELD is pfweb.py's process-wide id too.
PLAYFIELD = "PinballAssetDecryptor.Playfield"
GAME_SCREEN = "PinballAssetDecryptor.GameScreen"


def icon_path(name):
    """``icons/<name>.ico``, or None when it is not there."""
    p = os.path.join(ICONS, name + ".ico")
    return p if os.path.isfile(p) else None


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16),
                ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]


def _guid(text):
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    # 24 bytes on x64: vt, three reserved words, then the value union
    _fields_ = [("vt", ctypes.c_uint16), ("r1", ctypes.c_uint16),
                ("r2", ctypes.c_uint16), ("r3", ctypes.c_uint16),
                ("pwsz", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


_IID_IPropertyStore = "886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"
_PKEY_AppUserModel_ID = ("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3", 5)
_VT_LPWSTR = 31


def set_app_id(hwnd, app_id):
    """Put window ``hwnd`` in taskbar group ``app_id``.  True on success.

    SHGetPropertyStoreForWindow + IPropertyStore::SetValue/Commit, called
    through the COM vtable (slots 6 and 7; 2 is Release) because there is no
    pywin32 here and none may be asked for."""
    if sys.platform != "win32" or not hwnd:
        return False
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, 0x2)       # STA; S_FALSE / RPC_E_CHANGED_MODE
    store = ctypes.c_void_p()                          # are both fine here
    iid = _guid(_IID_IPropertyStore)
    hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(
        ctypes.c_void_p(hwnd), ctypes.byref(iid), ctypes.byref(store))
    if hr != 0 or not store:
        return False
    vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    vtbl = vtbl.contents
    proto = ctypes.WINFUNCTYPE
    set_value = proto(ctypes.c_long, ctypes.c_void_p,
                      ctypes.POINTER(_PROPERTYKEY),
                      ctypes.POINTER(_PROPVARIANT))(vtbl[6])
    commit = proto(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
    release = proto(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    try:
        key = _PROPERTYKEY(_guid(_PKEY_AppUserModel_ID[0]),
                           _PKEY_AppUserModel_ID[1])
        value = _PROPVARIANT()
        value.vt = _VT_LPWSTR
        value.pwsz = app_id
        hr = set_value(store, ctypes.byref(key), ctypes.byref(value))
        if hr == 0:
            hr = commit(store)
        return hr == 0
    finally:
        release(store)


def _hwnd(win):
    """The native window handle of a pywebview (WinForms) window, or 0."""
    try:
        return int(win.native.Handle.ToInt64())
    except Exception:                                   # noqa: BLE001
        return 0


def _set_icon(win, ico):
    """The form's own Icon, set on its GUI thread (a WinForms property: it
    survives the handle being recreated, which a bare WM_SETICON would not)."""
    form = win.native
    import clr  # noqa: F401  (pywebview's WinForms backend has loaded it)
    from System import Action
    from System.Drawing import Icon

    def _go():
        form.Icon = Icon(ico)
    if form.InvokeRequired:
        form.Invoke(Action(_go))
    else:
        _go()


def brand(win, icon_name, app_id):
    """Give pywebview window ``win`` the icon ``icons/<icon_name>.ico`` and
    taskbar group ``app_id``.  True when both took."""
    if sys.platform != "win32" or getattr(win, "native", None) is None:
        return False
    ok = True
    ico = icon_path(icon_name)
    try:
        if ico:
            _set_icon(win, ico)
        else:
            ok = False
    except Exception:                                   # noqa: BLE001
        log.warning("could not set the %s icon", icon_name, exc_info=True)
        ok = False
    try:
        if not set_app_id(_hwnd(win), app_id):
            ok = False
    except Exception:                                   # noqa: BLE001
        log.warning("could not give the window its own taskbar button",
                    exc_info=True)
        ok = False
    return ok
