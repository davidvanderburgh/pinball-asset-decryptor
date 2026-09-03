"""Small reusable Tk widgets shared between picker + main window."""

import sys
import tkinter as tk

from . import placement
from .theme import THEMES, platform_font


_SANS_FONT, _MONO_FONT = platform_font()


#: Kept as a module-level name because the tooltip below has always called it
#: that.  It now lives in placement.py, with the dialog and dropdown rules that
#: need the same answer — this was the only correct multi-monitor lookup in the
#: app, and every dialog rolled its own single-screen version beside it.
_monitor_workarea = placement.monitor_workarea


class _Tooltip:
    """Minimal hover tooltip — shown below the widget while the mouse
    is over it, AT THE CURSOR and moving with it.  Theme-aware via the
    ``theme_fn`` callable.

    IT FOLLOWS THE POINTER (David: "all tooltips should follow the
    cursor").  It used to be pinned under, or beside, the widget, which is
    fine for a button and wrong for anything big: on a wide row of a table
    the tip appeared under the ROW rather than under the thing the cursor
    was actually on, so it explained the row while you pointed at one cell
    of it.  Following the cursor also lets one tooltip serve a whole row of
    cells and still say where you are.

    The tip is offset down and right of the pointer and never sits under
    it, so it cannot swallow the click you were lining up; near a screen
    edge it flips to the other side rather than being clamped over the
    top."""

    def __init__(self, widget, text, theme_fn, bind=True, place="below"):
        self._widget = widget
        self.text = text
        self._theme_fn = theme_fn
        self._tip = None
        # ``place="side"`` puts the tip beside the widget instead of under it.
        # A tip UNDER a combobox lands exactly where its drop-down opens, so
        # hovering to click covered the thing being clicked and the control was
        # unusable (David).  Anything hover-explained that you also have to
        # operate wants the side placement — or better, an info button next to
        # it that carries the tip instead.
        # ``place`` is what the tip does when it has no pointer to follow -
        # a show() driven by a caller rather than by the mouse.
        self._place = place
        #: Where the pointer was last seen, in screen coordinates.
        self._at = None
        # ``bind=False`` lets a caller drive show()/hide() itself — used by the
        # picker rows, which manage one shared tooltip across several child
        # widgets so the cursor can move between them without flicker.
        if bind:
            widget.bind("<Enter>", self._show)
            widget.bind("<Leave>", self._hide)
            widget.bind("<Motion>", self._moved)

    # Public aliases for caller-driven use.
    def show(self, _event=None):
        self._show()

    def hide(self, _event=None):
        self._hide()

    def _moved(self, event=None):
        """The pointer moved over the widget: carry the tip along with it."""
        if event is not None:
            self._at = (event.x_root, event.y_root)
        if self._tip is not None:
            self._position()

    def _show(self, event=None):
        # Guard against a double-show leaking the prior Toplevel (caller-driven
        # callers may fire show() more than once before a hide()).
        if event is not None and getattr(event, "x_root", None) is not None:
            self._at = (event.x_root, event.y_root)
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
        self._position()
        self._tip.wm_overrideredirect(True)       # re-assert (deiconify resets)
        self._tip.deiconify()

    def _position(self):
        """Put the tip where it can be read: at the cursor when there is one,
        else under the widget the way it always was."""
        if self._tip is None:                             # pragma: no cover
            return
        self._tip.update_idletasks()
        tw, th = self._tip.winfo_reqwidth(), self._tip.winfo_reqheight()
        wx, wy = self._widget.winfo_rootx(), self._widget.winfo_rooty()
        ww, wh = self._widget.winfo_width(), self._widget.winfo_height()
        left, top, right, bottom = _monitor_workarea(
            wx, wy, self._widget.winfo_screenwidth(),
            self._widget.winfo_screenheight())
        m = 4
        if self._at is not None:
            # AT THE CURSOR, never under it: the gap is bigger than a
            # pointer so the tip cannot eat the click being lined up, and
            # near an edge it flips rather than being clamped over the top.
            px, py = self._at
            gap_x, gap_y = 16, 20
            x = px + gap_x
            if x + tw > right - m:
                x = max(left + m, px - gap_x - tw)
            y = py + gap_y
            if y + th > bottom - m:
                y = max(top + m, py - gap_y - th)
            self._tip.wm_geometry("+%d+%d" % (int(x), int(y)))
            return
        if self._place == "side":
            # Beside the widget, top-aligned: to the right when it fits, else
            # to the left, so the widget itself is never covered.
            if wx + ww + m + tw <= right - m:
                x = wx + ww + m
            else:
                x = max(left + m, wx - tw - m)
            y = max(top + m, min(wy, bottom - th - m))
        else:
            x = max(left + m, min(wx + ww // 2 - tw // 2, right - tw - m))
            if wy + wh + m + th <= bottom - m:
                y = wy + wh + m                   # below the widget
            elif wy - th - m >= top + m:
                y = wy - th - m                   # flip above
            else:
                y = max(top + m, bottom - th - m)  # pin so the bottom fits
        self._tip.wm_geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        self._at = None
        if self._tip:
            self._tip.destroy()
            self._tip = None


def draw_folder_icon(cv, size):
    """Draw a folder silhouette on canvas *cv*, white, sized to *size*.

    THE GLYPH WAS THE BUG.  The Project button typed U+1F5C0 (🗀) off Windows,
    and macOS's system font has no glyph for it — so the button rendered as the
    empty box a missing glyph draws, reported as "the project icon is missing".
    Every other header icon (⌂, ⚙, ?) happens to exist in that font, which is
    why it was the only one broken.

    Reaching for a different character is the same gamble again: what a font
    contains is not knowable from here, and the next platform gets to lose it
    too.  Six points are not a gamble.  Colour emoji is not an option either —
    Tk 8.6 renders none, which is why these icons are canvas discs at all.
    """
    s = size / 24.0
    pts = [(5, 18), (5, 7), (10.5, 7), (12.5, 9), (19, 9), (19, 18)]
    cv.create_polygon([c * s for p in pts for c in p],
                      fill="#ffffff", outline="")


#: The design grid every icon below is drawn on.  Twenty-four units, scaled
#: to whatever pixel size the caller asks for, so one set of coordinates
#: serves a 16 px row icon and a 32 px button.
ICON_GRID = 24.0


def _scaled(pts, s):
    """A flat coordinate list for ``create_polygon``, scaled by *s*."""
    return [c * s for p in pts for c in p]


def draw_pencil_icon(cv, size, color):
    """Draw a pencil on canvas *cv*, in *color*, sized to *size*.

    A PENCIL AND NOT A CHARACTER.  The Edit column used to be U+270E (✎),
    which on this machine's Tk renders in whatever fallback font has it -
    David read it as a feather, not a pencil ("the edit button is hidden
    behind the 'feather' icon which doesn't make sense. make it a pencil").
    That is the same gamble :func:`draw_folder_icon` documents: what a glyph
    looks like is the font's decision, not ours, and Tk 8.6 draws no colour
    emoji at all - so an icon that has to be GREEN cannot be a character
    either way.  Six points are not a gamble.

    The shaft runs corner to corner so the diagonal is long enough to read
    at 16 px, with the nib as its own triangle: at this size a single
    polygon's point disappears into the shaft.
    """
    s = size / ICON_GRID
    cv.create_polygon(_scaled([(15.5, 3.5), (20.5, 8.5),
                               (8.5, 20.5), (3.5, 15.5)], s),
                      fill=color, outline="")
    cv.create_polygon(_scaled([(3.5, 15.5), (8.5, 20.5), (2.5, 21.5)], s),
                      fill=color, outline="")


def draw_trash_icon(cv, size, color, bg=None):
    """Draw a waste bin on canvas *cv*, in *color*, sized to *size*.

    The lid, its handle and the tapered can - and, when *bg* is given, two
    slots cut out of the can in the row's own background, which is what
    makes it read as a bin rather than a bucket.  A minus sign used to do
    this job and said 'less', not 'gone' (David: "the remove should be a
    trash icon and red").
    """
    s = size / ICON_GRID
    cv.create_rectangle(4.5 * s, 6 * s, 19.5 * s, 8.5 * s,
                        fill=color, outline="")
    cv.create_rectangle(9.5 * s, 3 * s, 14.5 * s, 6 * s,
                        fill=color, outline="")
    cv.create_polygon(_scaled([(6.5, 9), (17.5, 9), (16, 21), (8, 21)], s),
                      fill=color, outline="")
    if bg:
        for x in (10, 12, 14):
            cv.create_line(x * s, 11.5 * s, x * s, 18.5 * s,
                           fill=bg, width=max(1, int(round(s))))


def draw_plus_icon(cv, size, color):
    """Draw a plus on canvas *cv*, in *color*, sized to *size*.

    Two bars and not the ``+`` character: it sits in the same column as the
    pencil and the trash on the rows above it, and has to be the same green.
    """
    s = size / ICON_GRID
    cv.create_rectangle(11 * s, 4.5 * s, 13 * s, 19.5 * s,
                        fill=color, outline="")
    cv.create_rectangle(4.5 * s, 11 * s, 19.5 * s, 13 * s,
                        fill=color, outline="")


def draw_arrow_icon(cv, size, color, down=False):
    """Draw a solid triangle on canvas *cv*, pointing up or *down*.

    Full-size rather than the small ▴ ▾ this replaces: in an 18 px cell the
    little ones are a weak thing to aim at, and a filled triangle needs no
    font to exist.
    """
    s = size / ICON_GRID
    pts = ([(12, 19), (4, 8.5), (20, 8.5)] if down
           else [(12, 5), (4, 15.5), (20, 15.5)])
    cv.create_polygon(_scaled(pts, s), fill=color, outline="")


def flat_button(parent, text, bg, fg, active_bg, command,
                padx=10, pady=2):
    """A flat coloured button whose colours survive every platform.

    ``tk.Button`` is the obvious widget and it is wrong on macOS: Aqua draws
    buttons natively and IGNORES ``bg`` / ``activebackground`` outright, so the
    update banner's blue buttons came out as default grey slabs sitting on a
    dark blue strip ("the download and close buttons in the update banner are
    unstyled").  A Label honours its background everywhere, so on macOS the
    button becomes a Label carrying the two bindings a Button would have given
    for free.

    The returned widget answers ``pack`` / ``pack_forget`` /
    ``winfo_ismapped`` / ``configure(text=…)`` either way, which is the whole
    surface the banner uses.
    """
    if sys.platform != "darwin":
        return tk.Button(parent, text=text, bg=bg, fg=fg,
                         activebackground=active_bg, activeforeground=fg,
                         relief="flat", padx=padx, pady=pady, borderwidth=0,
                         cursor="hand2", command=command)
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg, padx=padx, pady=pady,
                   cursor="hand2")
    lbl.bind("<Button-1>", lambda _e: command())
    lbl.bind("<Enter>", lambda _e: lbl.configure(bg=active_bg))
    lbl.bind("<Leave>", lambda _e: lbl.configure(bg=bg))
    return lbl


def center_over(parent, win, min_w=0, min_h=0):
    """Center *win* over *parent*'s window — the app-wide modal-positioning
    rule (David: every modal appears centered over the app).  Same math the
    flash/disk/diagnose dialogs' private ``_center`` methods established:
    requested size (floored to *min_w*/*min_h*), parent-centered, falling
    back to screen-center while the parent is unmapped (startup), clamped
    to the top-left so a huge dialog never opens off-screen.

    With no minimums the geometry sets POSITION only — pinning a WxH would
    stop Tk auto-resizing a dialog whose content later changes (e.g. the
    New-project structure preview).

    THE CLAMP MOVED OUT to placement.centered_over, and it changed meaning on
    the way: this used to finish with ``max(0, x)``, which is only correct on a
    single-screen machine.  Root coordinates are NEGATIVE on a display to the
    left of the primary one, so on a multi-monitor setup that clamp did not
    rescue a stray dialog, it dragged a correctly-placed one onto the wrong
    monitor."""
    try:
        win.update_idletasks()
        dw = max(win.winfo_reqwidth(), min_w)
        dh = max(win.winfo_reqheight(), min_h)
        x, y = placement.centered_over(parent, dw, dh)
        pos = "+%d+%d" % (x, y)
        if min_w or min_h:
            win.geometry("%dx%d%s" % (dw, dh, pos))
        else:
            win.geometry(pos)
    except tk.TclError:
        pass
