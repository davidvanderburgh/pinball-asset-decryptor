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


_SANS_FONT, _MONO_FONT = platform_font()


# Visual identity per plugin key.  Placeholder until we have real
# logo artwork — a coloured square with the first letter of the
# manufacturer is distinctive enough to scan at a glance.
_MFR_VISUALS = {
    "pb":     {"color": "#1e88e5", "letter": "P"},
    "spooky": {"color": "#e64a19", "letter": "S"},
    "bof":    {"color": "#8e24aa", "letter": "B"},
    "jjp":    {"color": "#43a047", "letter": "J"},
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

        title = tk.Label(
            self, text="Choose a manufacturer",
            font=(_SANS_FONT, 18, "bold"),
            background=c["bg"], foreground=c["fg"])
        title.pack(pady=(28, 6))

        subtitle = tk.Label(
            self,
            text="Pick which pinball manufacturer's game assets you want "
                 "to decrypt or modify.",
            font=(_SANS_FONT, 10),
            background=c["bg"], foreground=c["gray"])
        subtitle.pack(pady=(0, 22))

        grid = tk.Frame(self, background=c["bg"])
        grid.pack(padx=24, pady=8)

        cols = 2
        for i, mfr in enumerate(self._manufacturers):
            row, col = divmod(i, cols)
            card = self._build_card(grid, mfr)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            self._cards.append(card)

        for c_idx in range(cols):
            grid.columnconfigure(c_idx, weight=1, minsize=260)

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

        # Coloured letter "logo"
        logo = tk.Label(
            card, text=v["letter"],
            font=(_SANS_FONT, 28, "bold"),
            foreground="#ffffff", background=v["color"],
            width=2, height=1, padx=8, pady=4)
        logo.pack(side=tk.TOP, anchor="w")

        # Manufacturer display name
        name = tk.Label(
            card, text=mfr.display,
            font=(_SANS_FONT, 13, "bold"),
            background=c["button"], foreground=c["fg"])
        name.pack(side=tk.TOP, anchor="w", pady=(10, 2))

        # Game count + accepted file extensions
        n_games = len(mfr.games)
        exts = list(mfr.input_spec.extensions)
        ext_text = ", ".join(exts[:4])
        if len(exts) > 4:
            ext_text += ", ..."
        subtitle_text = (f"{n_games} game{'s' if n_games != 1 else ''}"
                         f"  ·  {ext_text}")
        subtitle = tk.Label(
            card, text=subtitle_text,
            font=(_SANS_FONT, 9),
            background=c["button"], foreground=c["gray"])
        subtitle.pack(side=tk.TOP, anchor="w")

        # Click + hover handlers — apply to every child so the whole
        # card surface is the hot zone, not just the parent Frame.
        def _on_click(_e=None):
            if self._on_select:
                self._on_select(mfr)

        def _on_enter(_e=None):
            card.configure(highlightbackground=c["accent"])

        def _on_leave(_e=None):
            card.configure(highlightbackground=c["border"])

        for w in (card, logo, name, subtitle):
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
