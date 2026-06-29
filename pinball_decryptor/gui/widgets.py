"""Small reusable Tk widgets shared between picker + main window."""

import sys
import tkinter as tk

from .theme import THEMES, platform_font


_SANS_FONT, _MONO_FONT = platform_font()


def _monitor_workarea(x, y, fallback_w, fallback_h):
    """Return ``(left, top, right, bottom)`` of the work area — the screen
    minus the taskbar — of the monitor containing point ``(x, y)``.

    Used to keep pop-ups (tooltips) on-screen.  Falls back to the full primary
    screen (``0, 0, fallback_w, fallback_h``) off Windows or on any failure.
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


class _Tooltip:
    """Minimal hover tooltip — shown below the widget while the mouse
    is over it.  Theme-aware via the ``theme_fn`` callable."""

    def __init__(self, widget, text, theme_fn, bind=True):
        self._widget = widget
        self.text = text
        self._theme_fn = theme_fn
        self._tip = None
        # ``bind=False`` lets a caller drive show()/hide() itself — used by the
        # picker rows, which manage one shared tooltip across several child
        # widgets so the cursor can move between them without flicker.
        if bind:
            widget.bind("<Enter>", self._show)
            widget.bind("<Leave>", self._hide)

    # Public aliases for caller-driven use.
    def show(self, _event=None):
        self._show()

    def hide(self, _event=None):
        self._hide()

    def _show(self, _event=None):
        # Guard against a double-show leaking the prior Toplevel (caller-driven
        # callers may fire show() more than once before a hide()).
        if not self.text or self._tip is not None:
            return
        c = THEMES[self._theme_fn()]
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        # Hidden until measured + positioned so it never flashes at 0,0.
        self._tip.withdraw()
        self._tip.configure(background=c["tooltip_bg"])
        tk.Label(
            self._tip, text=self.text,
            background=c["tooltip_bg"], foreground=c["tooltip_fg"],
            relief="solid", borderwidth=1,
            font=(_SANS_FONT, 9), padx=6, pady=2,
            wraplength=420, justify=tk.LEFT,
        ).pack()
        # Measure, then clamp to the monitor's work area so a long tooltip near
        # a screen edge isn't cut off: centre under the widget, prefer placing
        # below, flip above if it would overflow the bottom, and pin to the top
        # when it's simply taller than the gap (the most content stays visible).
        self._tip.update_idletasks()
        tw, th = self._tip.winfo_reqwidth(), self._tip.winfo_reqheight()
        wx, wy = self._widget.winfo_rootx(), self._widget.winfo_rooty()
        ww, wh = self._widget.winfo_width(), self._widget.winfo_height()
        left, top, right, bottom = _monitor_workarea(
            wx, wy, self._widget.winfo_screenwidth(),
            self._widget.winfo_screenheight())
        m = 4
        x = max(left + m, min(wx + ww // 2 - tw // 2, right - tw - m))
        if wy + wh + m + th <= bottom - m:
            y = wy + wh + m                       # below the widget
        elif wy - th - m >= top + m:
            y = wy - th - m                       # flip above
        else:
            y = max(top + m, bottom - th - m)     # pin so the bottom fits
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.wm_overrideredirect(True)       # re-assert (deiconify can reset it)
        self._tip.deiconify()

    def _hide(self, _event=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None
