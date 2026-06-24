"""Manufacturer picker — the entry screen.

Renders a vertical list of compact manufacturer rows — one logo-height
each, with a one-line peek of the games and the full list on hover — so
every manufacturer fits on screen without scrolling even as the catalog
grows.  Clicking a row commits the user to that manufacturer and hands
off to the main extract/write view.  Forcing this up-front choice
(instead of a dropdown that's silently pre-selected) also prevents the
"I started Spooky, switched to JJP mid-run" class of confusion.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .theme import THEMES, platform_font
from .widgets import _Tooltip


_SANS_FONT, _MONO_FONT = platform_font()


# Visual identity per plugin key.  Colors picked to evoke each
# manufacturer's actual branding:
#   pb     - Pinball Brothers: metallic / brushed-gold accents
#   spooky - Spooky Pinball:   Halloween orange
#   bof    - Barrels of Fun:   their site uses bright blue
#   jjp    - Jersey Jack:      red is their flagship colour
# These are placeholder "letter logos"; switching to actual bitmap logos
# would be straightforward once we have artwork (nominative fair use
# typically covers third-party tools like this, but a "not affiliated"
# README disclaimer is the standard hedge).
_MFR_VISUALS = {
    "pb":       {"color": "#d4a017", "letter": "PB"},
    "spooky":   {"color": "#e64a19", "letter": "S"},
    "bof":      {"color": "#1565c0", "letter": "BoF"},
    "jjp":      {"color": "#c62828", "letter": "JJP"},
    # Williams classic logo is the cursive red "Williams" script; a
    # deep red mirrors that without colliding with JJP's slightly
    # brighter red.
    "williams": {"color": "#a01818", "letter": "W"},
    # CGC's brand uses a chrome/silver palette; muted blue-grey reads
    # as "premium remake" and stays distinct from BOF's saturated blue.
    "cgc":      {"color": "#37474f", "letter": "C"},
    # American Pinball's brand leans on a flag-inspired navy/red/silver
    # palette; deep navy reads patriotic without clashing with BOF's
    # brighter blue.
    "ap":       {"color": "#1a237e", "letter": "AP"},
    # Dutch Pinball's logo is a tulip-orange on black; a warm amber-orange
    # evokes the Dutch national colour and stays distinct from Spooky's
    # redder Halloween orange.
    "dp":       {"color": "#ff6f00", "letter": "DP"},
    # Stern Pinball's brand red (the "STERN" wordmark).  Shares the letter "S"
    # with Spooky but is a saturated true-red vs Spooky's orange, and the card's
    # name label disambiguates.
    "stern":    {"color": "#d9001c", "letter": "S"},
    # Data East — classic-DMD era (PinMAME).  A distinct teal keeps it clear
    # of the several reds/blues already in use.
    "data_east": {"color": "#00838f", "letter": "DE"},
    # Sega Pinball (classic Whitestar DMD, 1995-1999) — a bright Sega blue,
    # distinct from BOF's darker blue and AP's navy.
    "sega": {"color": "#0089cf", "letter": "SEGA"},
}


class ManufacturerPicker(ttk.Frame):
    """A vertical list of compact rows, one per registered manufacturer.

    Clicking any row fires ``on_select(mfr)`` and the parent shell is
    expected to swap to that manufacturer's working view.
    """

    def __init__(self, parent, manufacturers, on_select, theme_fn, **kw):
        super().__init__(parent, **kw)
        self._manufacturers = manufacturers
        self._on_select = on_select
        self._theme_fn = theme_fn
        self._cards = []
        self._build()

    def _build(self):
        c = THEMES[self._theme_fn()]

        # Page header.  The "Pinball Asset Decryptor" label used to
        # appear above this; now that we've hidden that redundant
        # element (window title bar already says it), this title gets
        # to breathe.
        title = tk.Label(
            self,
            text="Choose a manufacturer",
            font=(_SANS_FONT, 14, "bold"),
            background=c["bg"], foreground=c["fg"])
        title.pack(pady=(14, 10))

        # Vertical stack of full-width cards inside a scrollable canvas.
        # Cards size naturally to their content; the canvas handles any
        # overflow so the picker still works when more manufacturers /
        # games are added in the future.
        scroll_wrap = tk.Frame(self, background=c["bg"])
        scroll_wrap.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 8))

        self._canvas = tk.Canvas(
            scroll_wrap, background=c["bg"],
            highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(
            scroll_wrap, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Scrollbar is packed/unpacked dynamically based on whether the
        # content actually overflows — no point taking up screen real
        # estate when everything already fits.
        self._scrollbar = scrollbar
        self._scrollbar_visible = False

        stack = tk.Frame(self._canvas, background=c["bg"])
        self._stack_window_id = self._canvas.create_window(
            (0, 0), window=stack, anchor="nw")

        def _update_scrollbar():
            bbox = self._canvas.bbox("all")
            if bbox is None:
                return
            content_h = bbox[3] - bbox[1]
            visible_h = self._canvas.winfo_height()
            needs = content_h > visible_h + 1  # +1 for rounding tolerance
            if needs and not self._scrollbar_visible:
                self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                self._scrollbar_visible = True
            elif not needs and self._scrollbar_visible:
                self._scrollbar.pack_forget()
                self._scrollbar_visible = False

        # Update scrollregion + scrollbar visibility whenever the
        # stack's natural size changes (e.g. cards rebuilt on theme
        # change) or the canvas is resized.  Also keep the stack's
        # width matched to the canvas so cards fill horizontally.
        def _on_stack_configure(_e):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
            _update_scrollbar()
        stack.bind("<Configure>", _on_stack_configure)

        def _on_canvas_configure(e):
            self._canvas.itemconfig(self._stack_window_id, width=e.width)
            _update_scrollbar()
        self._canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse-wheel scrolling — bound on Enter/Leave so it only fires
        # when the cursor is over the picker (not when the user is
        # scrolling a log pane in another view).
        def _on_mousewheel(e):
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self._canvas.bind("<Enter>",
                          lambda _e: self._canvas.bind_all("<MouseWheel>",
                                                           _on_mousewheel))
        self._canvas.bind("<Leave>",
                          lambda _e: self._canvas.unbind_all("<MouseWheel>"))

        for mfr in self._manufacturers:
            card = self._build_card(stack, mfr)
            card.pack(fill=tk.X, padx=0, pady=4)
            self._cards.append(card)

    @staticmethod
    def _peek_text(games, budget=72):
        """One-line comma-joined game names that fit within *budget* chars,
        with a "+N more" tail for the remainder.  Always shows at least the
        first name even if it alone exceeds the budget."""
        names = [g.display for g in games]
        shown, used = [], 0
        for nm in names:
            sep = 2 if shown else 0
            if shown and used + sep + len(nm) > budget:
                break
            shown.append(nm)
            used += sep + len(nm)
        text = ", ".join(shown)
        leftover = len(names) - len(shown)
        if leftover:
            text += f", +{leftover} more"
        return text

    @staticmethod
    def _tooltip_text(mfr):
        """Full game list for the hover tooltip — supported games marked
        with "+", unsupported with "✕" plus the reason when known."""
        lines = [mfr.display, ""]
        for g in mfr.games:
            if g.supported:
                lines.append(f"  +  {g.display}")
            else:
                reason = (f"  —  {g.unsupported_reason}"
                          if g.unsupported_reason else "")
                lines.append(f"  ✕  {g.display}{reason}")
        return "\n".join(lines)

    def _build_card(self, parent, mfr):
        c = THEMES[self._theme_fn()]
        v = _MFR_VISUALS.get(mfr.key, {"color": c["accent"], "letter": "?"})

        # Row container: a tk.Frame so we can use highlightthickness for
        # the hover ring (ttk.Frame doesn't expose those options reliably).
        card = tk.Frame(
            parent,
            background=c["button"],
            highlightthickness=2,
            highlightbackground=c["border"],
            cursor="hand2",
            padx=14, pady=10,
        )

        # ----- Letter logo (left), centred against the 2-line text ----
        # Fixed-size colour chip so 1-, 2- and 3-character codes (e.g. "S",
        # "DE", "JJP", "BoF") stay a uniform square down the list; the glyph
        # font scales down for longer codes so they fit without overflowing.
        letter = v["letter"]
        logo_box = tk.Frame(card, background=v["color"], width=44, height=38)
        logo_box.pack(side=tk.LEFT, padx=(0, 12))
        logo_box.pack_propagate(False)
        _logo_pt = 20 if len(letter) <= 2 else 14 if len(letter) == 3 else 11
        logo = tk.Label(
            logo_box, text=letter,
            font=(_SANS_FONT, _logo_pt, "bold"),
            foreground="#ffffff", background=v["color"])
        # All-caps codes have no descenders, so centring the font's
        # line-box leaves them looking a hair top-heavy; a 1px downward
        # nudge optically centres the glyphs (more overshoots low).
        logo.place(relx=0.5, rely=0.5, anchor="center", y=1)

        text_block = tk.Frame(card, background=c["button"])
        text_block.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ----- Top line: name + badge (left)  ·  stats (right) --------
        top = tk.Frame(text_block, background=c["button"])
        top.pack(fill=tk.X, anchor="w")

        n_games = len(mfr.games)
        n_unsup = sum(1 for g in mfr.games if not g.supported)
        exts = list(mfr.input_spec.extensions)
        ext_text = ", ".join(exts[:3])
        if len(exts) > 3:
            ext_text += ", …"
        subtitle_parts = [f"{n_games} game{'s' if n_games != 1 else ''}",
                          ext_text]
        if n_unsup:
            subtitle_parts.append(f"{n_unsup} unsupported")
        # Stats pinned right so the names left-align in a clean column.
        subtitle = tk.Label(
            top, text="  ·  ".join(subtitle_parts),
            font=(_SANS_FONT, 9),
            background=c["button"], foreground=c["gray"])
        subtitle.pack(side=tk.RIGHT)

        name = tk.Label(
            top, text=mfr.display,
            font=(_SANS_FONT, 13, "bold"),
            background=c["button"], foreground=c["fg"])
        name.pack(side=tk.LEFT)

        # Corner badge — a custom ``badge`` (e.g. "EXTRACT ONLY") takes
        # precedence, otherwise ``beta = True`` shows an amber "BETA" pill.
        badge_text = (getattr(mfr, "badge", "")
                      or ("BETA" if getattr(mfr, "beta", False) else ""))
        badge_widget = None
        if badge_text:
            badge_color = "#e6a700" if badge_text == "BETA" else "#546e7a"
            badge_widget = tk.Label(
                top, text=badge_text,
                font=(_SANS_FONT, 8, "bold"),
                foreground="#ffffff", background=badge_color,
                padx=5, pady=0)
            badge_widget.pack(side=tk.LEFT, padx=(8, 0))

        # ----- Peek line: one truncated row of game names -------------
        peek = tk.Label(
            text_block, text=self._peek_text(mfr.games),
            font=(_SANS_FONT, 9), anchor="w", justify=tk.LEFT,
            background=c["button"], foreground=c["gray"])
        peek.pack(fill=tk.X, anchor="w", pady=(3, 0))

        # The whole row is the hot zone — click + hover bindings go on
        # every widget so there are no dead spots between the labels.
        all_widgets = [card, logo_box, logo, text_block, top, name,
                       subtitle, peek]
        if badge_widget is not None:
            all_widgets.append(badge_widget)

        # One shared tooltip (full game list) for the whole row.  We drive
        # show/hide ourselves (bind=False) with a short hide-debounce so the
        # cursor crossing between the row's children doesn't flicker or tear
        # down the tip; a re-enter within the window cancels the pending hide.
        tip = _Tooltip(card, self._tooltip_text(mfr),
                       lambda: self._theme_fn(), bind=False)
        hide_job = [None]

        def _cancel_hide():
            if hide_job[0] is not None:
                card.after_cancel(hide_job[0])
                hide_job[0] = None

        def _on_click(_e=None):
            _cancel_hide()
            tip.hide()
            if self._on_select:
                self._on_select(mfr)

        def _on_enter(_e=None):
            _cancel_hide()
            card.configure(highlightbackground=c["accent"])
            tip.show()

        def _on_leave(_e=None):
            _cancel_hide()

            def _do_hide():
                hide_job[0] = None
                if not card.winfo_exists():
                    return
                card.configure(highlightbackground=c["border"])
                tip.hide()
            hide_job[0] = card.after(50, _do_hide)

        for w in all_widgets:
            w.bind("<Button-1>", _on_click)
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)

        return card

    def apply_theme(self):
        """Tear down + rebuild on theme change so colours stay in sync."""
        for child in self.winfo_children():
            child.destroy()
        self._cards = []
        self._build()
