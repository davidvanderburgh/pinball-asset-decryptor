"""Give a window some other program made its own taskbar icon under WSLg.

    python3 wmicon.py TITLE ICON.argb [--wait SECONDS]

The game's window is Xephyr's (display.sh), and Xephyr sets a WM_CLASS
("Xephyr") but no icon, so WSLg gives its taskbar button the Linux penguin.
_NET_WM_ICON can be set on a window by ANY client, and WSLg follows the
property when it changes (its window manager listens for it), so this puts the
LCD backbox icon - tools/spike2_emu/icons/gamewin.argb, drawn by
installer/make_rig_icons.py - on every top-level window whose name contains
TITLE. The class is left alone: Xephyr's already gives the window a taskbar
group of its own, and that group wears the window's icon.

STDLIB ONLY: libX11 through ctypes, which every distro that can show an X
window already has - no python-xlib, no xprop array juggling, nothing a user
has to install. Best-effort: exits 0 having done nothing when there is no
display, no library or no such window, and 1 only on a bad icon file.

ICON.argb is _NET_WM_ICON's own data - for each size, width, height, then
width*height ARGB pixels - as little-endian 32-bit words. Xlib takes format-32
property data as C longs, so the words are widened on the way in.
"""
import ctypes
import ctypes.util
import os
import struct
import sys
import time

_ulong = ctypes.c_ulong


def _xlib():
    name = ctypes.util.find_library("X11") or "libX11.so.6"
    x = ctypes.CDLL(name)
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = _ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XQueryTree.argtypes = [ctypes.c_void_p, _ulong, ctypes.POINTER(_ulong),
                             ctypes.POINTER(_ulong),
                             ctypes.POINTER(ctypes.POINTER(_ulong)),
                             ctypes.POINTER(ctypes.c_uint)]
    x.XFetchName.argtypes = [ctypes.c_void_p, _ulong,
                             ctypes.POINTER(ctypes.c_void_p)]
    x.XFree.argtypes = [ctypes.c_void_p]
    x.XInternAtom.restype = _ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XChangeProperty.argtypes = [ctypes.c_void_p, _ulong, _ulong, _ulong,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_int]
    x.XFlush.argtypes = [ctypes.c_void_p]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x


def _name(x, dpy, w):
    p = ctypes.c_void_p()
    if not x.XFetchName(dpy, w, ctypes.byref(p)) or not p.value:
        return ""
    try:
        return ctypes.string_at(p.value).decode("utf-8", "replace")
    finally:
        x.XFree(p)


def find(x, dpy, title):
    """Every window under the root whose WM_NAME contains ``title``."""
    out, todo = [], [x.XDefaultRootWindow(dpy)]
    while todo:
        w = todo.pop()
        if title in _name(x, dpy, w):
            out.append(w)
        root, parent = _ulong(), _ulong()
        kids, n = ctypes.POINTER(_ulong)(), ctypes.c_uint()
        if x.XQueryTree(dpy, w, ctypes.byref(root), ctypes.byref(parent),
                        ctypes.byref(kids), ctypes.byref(n)):
            todo.extend(kids[i] for i in range(n.value))
            if kids:
                x.XFree(kids)
    return out


def load(path):
    """The icon's words, checked: every size's pixels must all be there."""
    with open(path, "rb") as f:
        raw = f.read()
    if not raw or len(raw) % 4:
        raise ValueError("%s: not a whole number of 32-bit words" % path)
    words = struct.unpack("<%dI" % (len(raw) // 4), raw)
    i = 0
    while i < len(words):
        if i + 2 > len(words):
            raise ValueError("%s: a size with no width/height" % path)
        w, h = words[i], words[i + 1]
        if not (0 < w <= 1024 and 0 < h <= 1024) or i + 2 + w * h > len(words):
            raise ValueError("%s: truncated at word %d" % (path, i))
        i += 2 + w * h
    return words


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    wait = 5.0
    if "--wait" in args:
        k = args.index("--wait")
        wait = float(args[k + 1])
        del args[k:k + 2]
    if len(args) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 64
    title, path = args
    try:
        words = load(path)
    except (OSError, ValueError) as e:
        print("wmicon: %s" % e, file=sys.stderr)
        return 1
    try:
        x = _xlib()
    except OSError as e:
        print("wmicon: no libX11 (%s); the window keeps its icon" % e)
        return 0
    dpy = x.XOpenDisplay(None)
    if not dpy:
        print("wmicon: cannot open DISPLAY=%s" % os.environ.get("DISPLAY"))
        return 0
    try:
        wins, end = [], time.monotonic() + wait
        while True:
            wins = find(x, dpy, title)
            if wins or time.monotonic() >= end:
                break
            time.sleep(0.25)
        if not wins:
            print("wmicon: no window named %r" % title)
            return 0
        data = (_ulong * len(words))(*words)
        prop = x.XInternAtom(dpy, b"_NET_WM_ICON", 0)
        for w in wins:
            x.XChangeProperty(dpy, w, prop, 6,           # XA_CARDINAL
                              32, 0, data, len(words))  # PropModeReplace
        x.XFlush(dpy)
        print("wmicon: icon set on %d window(s) named %r" % (len(wins), title))
        return 0
    finally:
        x.XCloseDisplay(dpy)


if __name__ == "__main__":
    sys.exit(main())
