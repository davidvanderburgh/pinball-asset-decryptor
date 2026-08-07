"""Where to put a window or a dropdown, on a machine with more than one screen.

WHY THIS MODULE EXISTS. Five dialogs and two menus each carried their own copy
of "centre it over the parent, then clamp it onto the screen", and every copy
had the same defect: ``winfo_screenwidth()`` is the PRIMARY display, not the
display the app is on.

The symptom was reported as two different bugs on the same dual-monitor Mac.
The Tips window "showed briefly and closed" - it had not closed, it had been
dragged onto the other monitor, because the app was on the second display and
the clamp decided the centred position was off screen. The four dialogs that
clamp with only ``max(0, x)`` have the mirror-image fault: they teleport when
the app is on a display to the LEFT of the primary, where root coordinates are
negative.

The irony is that the rig already knew how to do this properly - tooltips have
used ``monitor_workarea()`` and its real ``MonitorFromPoint`` lookup for
releases. It lived in widgets.py, nothing but the tooltip called it, and every
dialog rolled its own single-screen version instead. So it moves here, where
the two callers that need it can share it, and everything about screens is
answered in one file.

WHAT EACH PLATFORM GETS. On Windows the work area is the true rectangle of the
monitor the point is on, so clamping to it is always correct. Elsewhere there is
no monitor API and the rectangle IS the primary screen - so the clamp is applied
only when the parent is wholly inside it, and skipped otherwise. A window
centred on a parent the user can see is visible by construction; it needs no
rescuing, and rescuing it is what broke it.
"""

import sys
import tkinter as tk


def monitor_workarea(x, y, fallback_w, fallback_h):
    """``(left, top, right, bottom)`` of the work area - the screen minus the
    taskbar - of the monitor containing point ``(x, y)``.

    Falls back to the full primary screen (``0, 0, fallback_w, fallback_h``)
    off Windows or on any failure.  Callers that must know whether the answer
    is real ask :func:`on_primary_display` as well.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            class _MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD),
                            ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD)]

            MONITOR_DEFAULTTONEAREST = 2
            hmon = user32.MonitorFromPoint(
                wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                r = mi.rcWork
                return (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass
    return (0, 0, fallback_w, fallback_h)


def on_primary_display(win):
    """Whether *win* lies wholly inside the primary display's bounds.

    False is the interesting answer: it means the window is on some other
    monitor (or straddling two), so nothing computed from
    ``winfo_screenwidth()`` applies to it.
    """
    try:
        x, y = win.winfo_rootx(), win.winfo_rooty()
        return (x >= 0 and y >= 0
                and x + win.winfo_width() <= win.winfo_screenwidth()
                and y + win.winfo_height() <= win.winfo_screenheight())
    except tk.TclError:
        return True             # unknowable; behave as before


def _clamp_applies(win):
    """Whether a work-area clamp can be trusted for *win*.

    On Windows the rectangle is the parent's own monitor, so always.  Elsewhere
    it is the primary screen, so only when the parent is actually on it.
    """
    return sys.platform == "win32" or on_primary_display(win)


def centered_over(parent, w, h):
    """``(x, y)`` for a *w* x *h* window centred over *parent*.

    Falls back to the middle of the primary display when the parent has no
    usable geometry yet - a dialog built before its parent is mapped reports a
    width of 1, and centring on that would pin it to the top-left corner.
    """
    try:
        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        if pw <= 1 or ph <= 1:
            return ((parent.winfo_screenwidth() - w) // 2,
                    (parent.winfo_screenheight() - h) // 2)
        x = parent.winfo_rootx() + (pw - w) // 2
        y = parent.winfo_rooty() + (ph - h) // 2
        if _clamp_applies(parent):
            left, top, right, bottom = monitor_workarea(
                parent.winfo_rootx() + pw // 2,
                parent.winfo_rooty() + ph // 2,
                parent.winfo_screenwidth(), parent.winfo_screenheight())
            x = max(left, min(x, right - w))
            y = max(top, min(y, bottom - h))
        return x, y
    except tk.TclError:
        return 0, 0


def dropdown_position(menu, btn):
    """``(x, y)`` for posting *menu* as a dropdown under *btn*.

    Right-aligned to the button, so a menu hanging off a control at the
    window's right edge opens inwards instead of over the edge.

    TWO THINGS MAKE THIS PLATFORM-DEPENDENT, and both were wrong on macOS:

    * an unmapped ``tk.Menu`` has no computed geometry, so ``winfo_reqwidth()``
      answers 1 until something makes it lay itself out.  Subtracting 1 from the
      button's right edge posts the menu AT that edge, opening rightwards -
      which is what "the dropdown appears all the way over on the right" was.
    * on Aqua a ``tk.Menu`` IS a native NSMenu.  Its requested width is not a
      meaningful Tk value and no amount of idle-task pumping makes it one, so
      the alignment is not attempted there - macOS keeps a posted menu on screen
      by itself, which is the job this arithmetic was doing.
    """
    y = btn.winfo_rooty() + btn.winfo_height()
    if sys.platform == "darwin":
        return btn.winfo_rootx(), y
    menu.update_idletasks()             # without this, reqwidth is 1
    w = menu.winfo_reqwidth()
    x = btn.winfo_rootx() + btn.winfo_width() - w
    if _clamp_applies(btn):
        left, _t, right, _b = monitor_workarea(
            btn.winfo_rootx(), btn.winfo_rooty(),
            btn.winfo_screenwidth(), btn.winfo_screenheight())
        x = max(left, min(x, right - w))
    return x, y
