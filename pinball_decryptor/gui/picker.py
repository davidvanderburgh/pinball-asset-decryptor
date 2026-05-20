"""Manufacturer picker — the entry screen.

Renders a 2x2 grid of manufacturer cards.  Clicking a card commits the
user to that manufacturer and hands off to the main extract/write view.
Forcing this up-front choice (instead of a dropdown that's silently
pre-selected) also prevents the "I started Spooky, switched to JJP
mid-run" class of confusion.
"""

import tkinter as tk
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
    "pb":       {"color": "#d4a017", "letter": "P"},
    "spooky":   {"color": "#e64a19", "letter": "S"},
    "bof":      {"color": "#1565c0", "letter": "B"},
    "jjp":      {"color": "#c62828", "letter": "J"},
    # Williams classic logo is the cursive red "Williams" script; a
    # deep red mirrors that without colliding with JJP's slightly
    # brighter red.
    "williams": {"color": "#a01818", "letter": "W"},
    # CGC's brand uses a chrome/silver palette; muted blue-grey reads
    # as "premium remake" and stays distinct from BOF's saturated blue.
    "cgc":      {"color": "#37474f", "letter": "C"},
}


class ManufacturerPicker(ttk.Frame):
    """A grid of cards, one per registered manufacturer.

    Clicking any card fires ``on_select(mfr)`` and the parent shell is
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
            card.pack(fill=tk.X, padx=0, pady=6)
            self._cards.append(card)

    def _build_card(self, parent, mfr):
        c = THEMES[self._theme_fn()]
        v = _MFR_VISUALS.get(mfr.key, {"color": c["accent"], "letter": "?"})

        # Card container: a tk.Frame so we can use highlightthickness for
        # the hover ring (ttk.Frame doesn't expose those options reliably).
        card = tk.Frame(
            parent,
            background=c["button"],
            highlightthickness=2,
            highlightbackground=c["border"],
            cursor="hand2",
            padx=18, pady=14,
        )

        # ----- Header row: letter logo + name/subtitle stacked --------
        header = tk.Frame(card, background=c["button"])
        header.pack(side=tk.TOP, fill=tk.X, anchor="w")

        logo = tk.Label(
            header, text=v["letter"],
            font=(_SANS_FONT, 22, "bold"),
            foreground="#ffffff", background=v["color"],
            width=2, height=1, padx=6, pady=2)
        logo.pack(side=tk.LEFT, anchor="n")

        title_block = tk.Frame(header, background=c["button"])
        title_block.pack(side=tk.LEFT, padx=(10, 0), anchor="n")

        name_row = tk.Frame(title_block, background=c["button"])
        name_row.pack(anchor="w")

        name = tk.Label(
            name_row, text=mfr.display,
            font=(_SANS_FONT, 13, "bold"),
            background=c["button"], foreground=c["fg"])
        name.pack(side=tk.LEFT)

        # Beta badge — small inline pill for plugins with the
        # ``beta = True`` flag.  Helps set expectations that the
        # pipeline is actively being tuned and rough edges are
        # expected.
        if getattr(mfr, "beta", False):
            beta_badge = tk.Label(
                name_row, text="BETA",
                font=(_SANS_FONT, 8, "bold"),
                foreground="#ffffff", background="#e6a700",
                padx=5, pady=0)
            beta_badge.pack(side=tk.LEFT, padx=(8, 0))

        n_games = len(mfr.games)
        n_unsup = sum(1 for g in mfr.games if not g.supported)
        exts = list(mfr.input_spec.extensions)
        ext_text = ", ".join(exts[:4])
        if len(exts) > 4:
            ext_text += ", ..."
        subtitle_parts = [
            f"{n_games} game{'s' if n_games != 1 else ''}",
            ext_text,
        ]
        if n_unsup:
            subtitle_parts.append(f"{n_unsup} unsupported")
        subtitle = tk.Label(
            title_block, text="  ·  ".join(subtitle_parts),
            font=(_SANS_FONT, 9),
            background=c["button"], foreground=c["gray"])
        subtitle.pack(anchor="w")

        # ----- Game list (2-column grid) -----------------------------
        games_box = tk.Frame(card, background=c["button"])
        games_box.pack(side=tk.TOP, fill=tk.X, anchor="w", pady=(10, 0))

        # Track every widget on the card so the click + hover bindings
        # can be applied to all of them (the whole card surface is the
        # hot zone).
        all_widgets = [card, header, logo, title_block, name_row, name,
                       subtitle, games_box]
        if getattr(mfr, "beta", False):
            all_widgets.append(beta_badge)
        game_labels = []

        # 3-column layout — wide enough to fit most game names while
        # cutting the row count of bigger lists by 1/3 vs. 2 cols.
        cols = 3
        for col in range(cols):
            games_box.columnconfigure(col, weight=1, uniform="games")

        for i, game in enumerate(mfr.games):
            row, col = divmod(i, cols)
            row_frame = tk.Frame(games_box, background=c["button"])
            row_frame.grid(row=row, column=col, sticky="w",
                           padx=(0, 14), pady=1)
            all_widgets.append(row_frame)

            if game.supported:
                marker = "+"
                fg = c["fg"]
                font = (_SANS_FONT, 9)
            else:
                marker = "x"
                fg = c["gray"]
                font = (_SANS_FONT, 9, "overstrike")

            game_lbl = tk.Label(
                row_frame, text=f"{marker} {game.display}",
                font=font, foreground=fg, background=c["button"])
            game_lbl.pack(side=tk.LEFT, anchor="w")
            game_labels.append((game_lbl, game))
            all_widgets.append(game_lbl)

            # Hover tooltip on unsupported games explaining why.
            if not game.supported and game.unsupported_reason:
                _Tooltip(game_lbl,
                         f"{game.display}\n\nUnsupported: "
                         f"{game.unsupported_reason}",
                         lambda: self._theme_fn())

        # ----- Click + card-level hover -----------------------------
        def _on_click(_e=None):
            if self._on_select:
                self._on_select(mfr)

        def _on_enter(_e=None):
            card.configure(highlightbackground=c["accent"])

        def _on_leave(_e=None):
            card.configure(highlightbackground=c["border"])

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
