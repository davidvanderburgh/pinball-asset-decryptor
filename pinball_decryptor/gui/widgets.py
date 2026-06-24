"""Small reusable Tk widgets shared between picker + main window."""

import tkinter as tk

from .theme import THEMES, platform_font


_SANS_FONT, _MONO_FONT = platform_font()


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
        x = self._widget.winfo_rootx() + self._widget.winfo_width() // 2
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.configure(background=c["tooltip_bg"])
        tk.Label(
            self._tip, text=self.text,
            background=c["tooltip_bg"], foreground=c["tooltip_fg"],
            relief="solid", borderwidth=1,
            font=(_SANS_FONT, 9), padx=6, pady=2,
            wraplength=420, justify=tk.LEFT,
        ).pack()

    def _hide(self, _event=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None
