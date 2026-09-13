#!/usr/bin/env python3
"""Report the matrix's keys pressed in the EMULATED GAME'S window.

The switch matrix (jjpsw.py) is a Tk window on the desktop's own X server, and
its keys - the flippers, Start, the menu buttons, Plunge / Drain - are Tk
bindings on that window, so they only worked while the matrix had the focus.
The game and the multi-boot menu draw into the NESTED X server (Xephyr, :1),
and a key pressed while that window has the focus goes into :1, where nothing
listened (David, 2026-09-13: "i should be able to focus either window for the
keyboard events to register").

This runs as a child of the matrix.  It takes a passive grab on the root
window of the nested display for exactly the keys named on its command line -
a grab on the root is activated whichever window inside :1 has the focus, the
game's or the menu's - and prints one line per press:

    ready :1 17
    press Left 0
    press Right 1          <- the number is the X modifier state (1 = Shift)

The matrix reads those lines and applies each with the handler its own Tk
binding uses, so both windows mean the same thing and there is one keymap.
Neither the game nor the menu reads the keyboard (a JJP machine has none), so
the grab takes nothing from either.

A separate PROCESS, not a thread in the matrix, on purpose: Xlib ends the
whole process when its connection breaks (Xephyr stopped), and that must not
take the matrix window with it.  ctypes over libX11, so nothing new is
installed; libX11 is already there for Tk.

    jjpkeys.py --display :1 Left Right 1 ...
"""
import argparse
import ctypes
import ctypes.util
import sys

KEY_PRESS = 2
ANY_MODIFIER = 1 << 15
GRAB_MODE_ASYNC = 1
#: XKeyEvent on x86-64: type @0 (int), serial @8, send_event @16, display @24,
#: window @32, root @40, subwindow @48, time @56, x/y @64/68, x_root/y_root
#: @72/76, state @80 (unsigned int), keycode @84 (unsigned int).
STATE_OFF, KEYCODE_OFF = 80, 84
XEVENT_SIZE = 192

_ERRORS = []


def _libx11():
    lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XDefaultRootWindow.restype = ctypes.c_ulong
    lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    lib.XStringToKeysym.restype = ctypes.c_ulong
    lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
    lib.XKeysymToKeycode.restype = ctypes.c_ubyte
    lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    lib.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint,
                             ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return lib


#: A protocol error (BadAccess: another client already grabbed that key) must
#: not end the process - Xlib's default handler prints and exits.  Recorded.
_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _on_error(_display, _event):
    _ERRORS.append(1)
    return 0


_HANDLER_REF = _ERROR_HANDLER(_on_error)


def keycode_names(pairs):
    """``[(name, keycode)]`` -> ``{keycode: first name}``.  Two names on one
    keycode ('d' and 'D') are one physical key; the first one names it."""
    out = {}
    for name, code in pairs:
        if code and code not in out:
            out[code] = name
    return out


def press_line(event_bytes, names):
    """The line to print for one raw XEvent, or None when it is not a press
    of a grabbed key."""
    if int.from_bytes(event_bytes[0:4], "little") != KEY_PRESS:
        return None
    code = int.from_bytes(event_bytes[KEYCODE_OFF:KEYCODE_OFF + 4], "little")
    name = names.get(code)
    if name is None:
        return None
    state = int.from_bytes(event_bytes[STATE_OFF:STATE_OFF + 4], "little")
    return "press %s %d" % (name, state)


def main(argv=None):
    ap = argparse.ArgumentParser(description="report the matrix's keys pressed in the game window")
    ap.add_argument("--display", default=":1")
    ap.add_argument("keys", nargs="+", help="X keysym names (Left, Right, 1, space, ...)")
    args = ap.parse_args(argv)

    x = _libx11()
    x.XSetErrorHandler(_HANDLER_REF)
    dpy = x.XOpenDisplay(args.display.encode())
    if not dpy:
        sys.stderr.write("jjpkeys: cannot open display %s\n" % args.display)
        return 3
    root = x.XDefaultRootWindow(dpy)
    pairs = []
    for name in args.keys:
        sym = x.XStringToKeysym(name.encode())
        pairs.append((name, x.XKeysymToKeycode(dpy, sym) if sym else 0))
    names = keycode_names(pairs)
    grabbed = 0
    for code in names:
        before = len(_ERRORS)
        x.XGrabKey(dpy, code, ANY_MODIFIER, root, 0, GRAB_MODE_ASYNC, GRAB_MODE_ASYNC)
        x.XSync(dpy, 0)
        if len(_ERRORS) == before:
            grabbed += 1
        else:
            sys.stderr.write("jjpkeys: %s is already grabbed on %s\n" % (names[code], args.display))
    print("ready %s %d" % (args.display, grabbed), flush=True)

    ev = ctypes.create_string_buffer(XEVENT_SIZE)
    while True:
        x.XNextEvent(dpy, ev)
        line = press_line(ev.raw, names)
        if line is not None:
            try:
                print(line, flush=True)
            except (BrokenPipeError, OSError):
                return 0             # the matrix is gone; so is our reason to grab


if __name__ == "__main__":
    sys.exit(main())
