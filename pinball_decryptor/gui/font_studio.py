"""Font Preview & Import window — see a Spike 2 game font rendered live, and
fit a desktop font (TTF/OTF) into it (Peter).

The Images tab already extracts every radium font into per-character glyph
slice PNGs; editing those files IS the mod path (Write splices the changed
BC blocks back into the atlas).  What was missing is everything around that:
seeing a whole string in a font (not 90 loose PNGs), knowing how big each
character may be, and producing correctly-sized bitmaps from a normal desktop
font — hand-fitting each letter into its atlas rectangle is why font swaps
kept failing.

This window renders preview text with the CURRENT slice PNGs (so pending
edits show), lays out with the metrics recorded at Extract (see
``fontrender``), and imports a desktop font at one auto-fitted uniform size,
baseline-aligned into each character's slot.  Apply just writes the slice
PNGs — the normal Images-tab change tracking, build and revert flows all see
it like any hand edit.

Singleton tool window (not a modal): pick fonts while the main window stays
usable, same pattern as Image Info.
"""

import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from ..plugins.stern import scene_render as _scene_render
from .theme import THEMES, platform_font
from .widgets import _Tooltip, center_over

_PREVIEW_DEFAULT = "THE QUICK BROWN FOX 0123456789"
_PREVIEW_BG = "#101014"
_SCENE_BG_NAMES = _scene_render.BACKGROUND_NAMES
_COMP_CLEAR = "Remove it (my outline instead)"
_COMP_KEEP = "Leave it as it is"
# How much undo history to keep.  A whole-project snapshot is ~20 MB (27,567
# slices at 738 bytes), so the byte budget is what actually bounds this — the
# step count only stops a long run of small edits growing without end.
_UNDO_STEPS = 5
_UNDO_BYTES = 64 * 1024 * 1024


def scene_label(card_path):
    """A short display label for a radium card path: the scene's hash dir
    (the same 8-char shorthand the Images tab's scene groups use)."""
    parts = card_path.replace("\\", "/").rstrip("/").split("/")
    if len(parts) >= 2:
        return parts[-2][:8]
    return card_path


class FontStudioWindow:
    """The Fonts tool window.  One per app; ``open_for`` re-uses it."""

    def __init__(self, app, assets_dir, preselect=None):
        self.app = app
        self.assets_dir = assets_dir
        self._fonts = []
        self._by_key = {}
        self._pending = {}       # font key -> (slices, size, kept, ttf_path)
        self._ttf_paths = {}     # font key -> last chosen ttf
        self._scene_paths = []   # listbox row -> radium card path (scope)
        self._companions = {}    # body font key -> its outline companion font
        self._undo = []          # [(label, {abs path: bytes or None})]
        self._undo_dir = assets_dir   # the folder that history belongs to
        self._tints = None       # font key -> {rgb: lines}, read on demand
        self._photo = None       # PhotoImage ref (must stay alive)
        self._render_job = None
        self._color = (255, 255, 255)
        self._sans, _mono = platform_font()
        self._build()
        self.reload(preselect)

    # -- window ----------------------------------------------------------

    def _theme(self):
        return THEMES.get(getattr(self.app, "_current_theme", "light"),
                          THEMES["light"])

    def _build(self):
        win = tk.Toplevel(self.app.root)
        self.win = win
        win.withdraw()
        win.title("Fonts — Preview & Import")
        win.transient(self.app.root)
        self.app._theme_toplevel(win)
        win.protocol("WM_DELETE_WINDOW", self._close)
        win.bind("<Escape>", lambda _e: self._close())

        th = self._theme()
        body = ttk.Frame(win, padding=(10, 8))
        body.pack(fill=tk.BOTH, expand=True)

        self._hint = ttk.Label(
            body, text="", font=(self._sans, 9), foreground=th["gray"],
            wraplength=980, justify=tk.LEFT)
        self._hint.pack(anchor=tk.W, pady=(0, 6))

        panes = ttk.Frame(body)
        panes.pack(fill=tk.BOTH, expand=True)

        # ---- left: font list + used-in-scenes --------------------------
        left = ttk.Frame(panes)
        left.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 8))
        srow = ttk.Frame(left)
        srow.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(srow, text="Search:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write",
                                   lambda *_a: self._refresh_font_list())
        ttk.Entry(srow, textvariable=self._search_var, width=18).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        tf = ttk.Frame(left)
        tf.pack(fill=tk.BOTH, expand=True)
        self._tree = ttk.Treeview(
            tf, columns=("px", "chars", "scenes"), height=16,
            selectmode="browse")
        self._tree.heading("#0", text="Font", anchor=tk.W)
        self._tree.heading("px", text="Size", anchor=tk.W)
        self._tree.heading("chars", text="Chars", anchor=tk.W)
        self._tree.heading("scenes", text="Scenes", anchor=tk.W)
        self._tree.column("#0", width=230, minwidth=140)
        self._tree.column("px", width=104, minwidth=54, stretch=False)
        self._tree.column("chars", width=52, minwidth=40, stretch=False)
        self._tree.column("scenes", width=56, minwidth=40, stretch=False)
        tsc = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=tsc.set)
        tsc.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        ttk.Label(left, text="Used in scenes:", font=(self._sans, 9)).pack(
            anchor=tk.W, pady=(6, 0))
        # Scenes embed their own copy of the font, so an edit can go to all of
        # them (restyle the game) or just the ones picked here (Peter: restyle
        # only the training scene).  All = the long-standing behaviour.
        self._scope_var = tk.StringVar(value="all")
        srow2 = ttk.Frame(left)
        srow2.pack(fill=tk.X, pady=(2, 2))
        ttk.Radiobutton(srow2, text="Change in all of them",
                        variable=self._scope_var, value="all",
                        command=self._on_scope_mode).pack(anchor=tk.W)
        ttk.Radiobutton(srow2, text="Change only the scenes I select",
                        variable=self._scope_var, value="some",
                        command=self._on_scope_mode).pack(anchor=tk.W)
        self._scenes_list = tk.Listbox(
            left, height=5, activestyle="none", exportselection=False,
            bg=th["field_bg"], fg=th["fg"], highlightthickness=0)
        self._scenes_list.pack(fill=tk.X)
        self._scenes_list.bind("<<ListboxSelect>>",
                               lambda _e: self._on_scope_select())
        for seq in ("<Button-3>", "<Button-2>"):     # Windows/Linux, macOS
            self._scenes_list.bind(seq, self._scene_popup)
        _Tooltip(self._scenes_list,
                 "The scene files whose atlases hold this font — the same "
                 "8-character scene shorthand the Images tab's scene groups "
                 "use.\n\nEvery scene carries its own copy, so \"only the "
                 "scenes I select\" leaves the rest on the stock font. One "
                 "font can still only look ONE way: the selection decides "
                 "where your import lands, not a different import per scene."
                 "\n\nRight-click a scene to go and look at it in the Scenes "
                 "window (clicking it here only changes the scope).",
                 lambda: getattr(self.app, "_current_theme", "light"))
        self._scope_lbl = ttk.Label(left, text="", font=(self._sans, 8),
                                    foreground=th["gray"], wraplength=400,
                                    justify=tk.LEFT)
        self._scope_lbl.pack(anchor=tk.W, pady=(2, 0))

        # ---- right: preview + import ------------------------------------
        right = ttk.Frame(panes)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        prow = ttk.Frame(right)
        prow.pack(fill=tk.X)
        ttk.Label(prow, text="Preview text:").pack(side=tk.LEFT)
        self._text_var = tk.StringVar(value=_PREVIEW_DEFAULT)
        self._text_var.trace_add("write", lambda *_a: self._schedule_render())
        ent = ttk.Entry(prow, textvariable=self._text_var)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 8))
        _Tooltip(ent, "Type anything — \\n starts a new line.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        ttk.Label(prow, text="Zoom:").pack(side=tk.LEFT)
        self._zoom_var = tk.StringVar(value="1x")
        zc = ttk.Combobox(prow, textvariable=self._zoom_var, width=4,
                          state="readonly", values=("1x", "2x", "3x", "4x"))
        zc.pack(side=tk.LEFT, padx=(2, 8))
        zc.bind("<<ComboboxSelected>>", lambda _e: self._schedule_render())
        ttk.Label(prow, text="Show:").pack(side=tk.LEFT)
        self._show_var = tk.StringVar(value="Current glyphs")
        self._show_combo = ttk.Combobox(
            prow, textvariable=self._show_var, width=16, state="readonly",
            values=("Current glyphs",))
        self._show_combo.pack(side=tk.LEFT, padx=(2, 8))
        self._show_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self._schedule_render())
        # A black outline on a black preview is as invisible here as it is on
        # the machine, which is no use when the outline is what you are looking
        # at (Peter).
        ttk.Label(prow, text="Behind:").pack(side=tk.LEFT)
        self._bg_var = tk.StringVar(value=_SCENE_BG_NAMES[0])
        bgc = ttk.Combobox(prow, textvariable=self._bg_var, width=12,
                           state="readonly", values=list(_SCENE_BG_NAMES))
        bgc.pack(side=tk.LEFT, padx=(2, 0))
        bgc.bind("<<ComboboxSelected>>", lambda _e: self._schedule_render())
        _Tooltip(bgc,
                 "What the letters are shown against. The machine draws on "
                 "black; a lighter backdrop (or the checkerboard) is how you "
                 "see a black outline, a shadow, or exactly where a letter's "
                 "box ends.",
                 lambda: getattr(self.app, "_current_theme", "light"))

        cv_frame = ttk.Frame(right)
        cv_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 2))
        self._canvas = tk.Canvas(cv_frame, height=240, bg=_PREVIEW_BG,
                                 highlightthickness=1)
        hsc = ttk.Scrollbar(cv_frame, orient=tk.HORIZONTAL,
                            command=self._canvas.xview)
        vsc = ttk.Scrollbar(cv_frame, orient=tk.VERTICAL,
                            command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=hsc.set, yscrollcommand=vsc.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsc.grid(row=0, column=1, sticky="ns")
        hsc.grid(row=1, column=0, sticky="ew")
        cv_frame.rowconfigure(0, weight=1)
        cv_frame.columnconfigure(0, weight=1)

        self._status = ttk.Label(right, text="", font=(self._sans, 9),
                                 foreground=th["gray"], wraplength=700,
                                 justify=tk.LEFT)
        self._status.pack(anchor=tk.W, pady=(0, 4))

        imp = ttk.LabelFrame(right, text=" Import a desktop font ")
        imp.pack(fill=tk.X, pady=(2, 0))
        irow = ttk.Frame(imp)
        irow.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Button(irow, text="Import font file…",
                   command=self._pick_ttf).pack(side=tk.LEFT)
        self._ttf_lbl = ttk.Label(irow, text="no file chosen",
                                  font=(self._sans, 9),
                                  foreground=th["gray"])
        self._ttf_lbl.pack(side=tk.LEFT, padx=(8, 0))

        orow = ttk.Frame(imp)
        orow.pack(fill=tk.X, padx=8, pady=(4, 2))
        ttk.Label(orow, text="Color:").pack(side=tk.LEFT)
        self._color_btn = tk.Canvas(orow, width=22, height=16,
                                    highlightthickness=1, cursor="hand2")
        self._color_btn.pack(side=tk.LEFT, padx=(4, 2))
        self._color_btn.bind("<Button-1>", lambda _e: self._pick_color())
        _Tooltip(self._color_btn,
                 "Ink color for these letters. Starts on the color sampled "
                 "from the game font, so a swap keeps its look — click to "
                 "choose your own.\n\nWith a font file imported it colors the "
                 "new letters; on its own it repaints the letters already "
                 "there, which you then Apply like any other edit.\n\n"
                 "Remember the SCENE multiplies this: a font a scene draws "
                 "black stays black whatever you pick here. The line under "
                 "these controls says which colors this font is drawn in.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        self._auto_color_var = tk.BooleanVar(value=True)
        acb = ttk.Checkbutton(orow, text="match original",
                              variable=self._auto_color_var,
                              command=self._on_option_change)
        acb.pack(side=tk.LEFT, padx=(2, 12))
        ttk.Label(orow, text="Outline:").pack(side=tk.LEFT)
        self._stroke_var = tk.IntVar(value=0)
        st = ttk.Spinbox(orow, from_=0, to=6, width=3,
                         textvariable=self._stroke_var,
                         command=self._on_option_change)
        st.pack(side=tk.LEFT, padx=(4, 2))
        self._stroke_btn = tk.Canvas(orow, width=22, height=16,
                                     highlightthickness=1, cursor="hand2")
        self._stroke_btn.pack(side=tk.LEFT, padx=(2, 2))
        self._stroke_btn.bind("<Button-1>", lambda _e: self._pick_stroke())
        self._stroke_color = (0, 0, 0)
        # Peter looked for a "transparent" entry in the colour picker; the
        # answer is a width of 0, which the picker can't express.
        ttk.Label(orow, text="px (0 = none)", font=(self._sans, 8),
                  foreground=th["gray"]).pack(side=tk.LEFT, padx=(0, 12))
        for w in (st, self._stroke_btn):
            _Tooltip(w,
                     "Outline drawn around each imported letter, in pixels. "
                     "Set it to 0 for no outline at all — there is no "
                     "\"transparent\" colour to pick, the width is the "
                     "switch.",
                     lambda: getattr(self.app, "_current_theme", "light"))
        # What the SCENES do to this font's ink.  Peter, after painting an
        # atlas: "as i understand the Font color is in the scene itself... maybe
        # something to switch the color to turtle green... does the color thing
        # on your font menu work[?] i played around with it, but it did not
        # produce what i wanted."  It works — it is just multiplied by a tint
        # the glyph files say nothing about, so this line says what that is.
        self._tint_lbl = ttk.Label(imp, text="", font=(self._sans, 8),
                                   foreground=th["gray"], wraplength=620,
                                   justify=tk.LEFT)

        srow3 = ttk.Frame(imp)
        srow3.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(srow3, text="Size:").pack(side=tk.LEFT)
        self._scale_var = tk.IntVar(value=100)
        sc = ttk.Spinbox(srow3, from_=50, to=100, increment=5, width=4,
                         textvariable=self._scale_var,
                         command=self._on_option_change)
        sc.pack(side=tk.LEFT, padx=(4, 2))
        ttk.Label(srow3, text="% of the auto-fitted size").pack(
            side=tk.LEFT, padx=(0, 12))
        _Tooltip(sc,
                 "Shrinks the whole letter, height included. Use it to pull "
                 "back from a fit that looks too heavy; use Letter width if "
                 "you only want the letters to stop touching.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        # The game lays text out with the CARD's advances, which an import must
        # not change, so a letter that fills its slot sits hard against its
        # neighbour (Peter: "some of the letters are very near together").
        ttk.Label(srow3, text="Letter width:").pack(side=tk.LEFT)
        self._width_var = tk.IntVar(value=100)
        wsp = ttk.Spinbox(srow3, from_=60, to=100, increment=5, width=4,
                          textvariable=self._width_var,
                          command=self._on_option_change)
        wsp.pack(side=tk.LEFT, padx=(4, 2))
        ttk.Label(srow3, text="% (lower = more space between letters)").pack(
            side=tk.LEFT)
        _Tooltip(wsp,
                 "Draws each letter narrower inside the same slot, which is "
                 "what puts a gap between neighbours. The letters keep their "
                 "HEIGHT — the spacing itself is fixed on the card and an "
                 "import can't change it.",
                 lambda: getattr(self.app, "_current_theme", "light"))

        # ---- outline companion ------------------------------------------
        # A Stern title is an outline instance with a fill instance on top, and
        # the outline comes from its OWN font.  Restyling only the fill leaves
        # the old typeface's black silhouette showing round the new letters —
        # which is unfindable from here unless the window says so (Peter spent
        # three rounds on it, blaming his stroke colour).
        self._comp_row = ttk.Frame(imp)
        self._comp_lbl = ttk.Label(self._comp_row, text="",
                                   font=(self._sans, 9), wraplength=560,
                                   justify=tk.LEFT)
        self._comp_lbl.pack(anchor=tk.W)
        crow = self._comp_ctrl = ttk.Frame(self._comp_row)
        ttk.Label(crow, text="Its outline:").pack(side=tk.LEFT)
        self._comp_var = tk.StringVar(value=_COMP_CLEAR)
        self._comp_combo = ttk.Combobox(
            crow, textvariable=self._comp_var, width=34, state="readonly",
            values=(_COMP_CLEAR, _COMP_KEEP))
        self._comp_combo.pack(side=tk.LEFT, padx=(6, 0))
        _Tooltip(
            self._comp_combo,
            "The game draws this outline font in black behind the letters. "
            "Removing it lets your own Outline setting shape the border; "
            "keeping it leaves the ORIGINAL typeface's outline around your "
            "new letters. Either way \"Revert font\" puts it back.",
            lambda: getattr(self.app, "_current_theme", "light"))

        # ---- apply to every size of the typeface --------------------------
        # The same typeface is baked at many sizes and each is its own font
        # here: TMNT lists Stern_CCZoinks 94 times and Stern_Impact 94 times.
        # Peter "replaced the font wherever i found it" and still saw stock
        # letters in places — nobody is doing 94 imports by hand.
        arow = self._arow = ttk.Frame(imp)
        arow.pack(fill=tk.X, padx=8, pady=(2, 0))
        self._all_sizes_var = tk.BooleanVar(value=True)
        self._all_sizes_cb = ttk.Checkbutton(
            arow, text="", variable=self._all_sizes_var)
        self._all_sizes_cb.pack(side=tk.LEFT)
        _Tooltip(self._all_sizes_cb,
                 "Fits the same font file into every size of this typeface, "
                 "each at its own auto-fitted size. Leave it off to restyle "
                 "only the size selected on the left.",
                 lambda: getattr(self.app, "_current_theme", "light"))

        brow = self._brow = ttk.Frame(imp)
        brow.pack(fill=tk.X, padx=8, pady=(4, 8))
        self._apply_btn = ttk.Button(brow, text="Apply to this font",
                                     command=self._apply, state="disabled")
        self._apply_btn.pack(side=tk.LEFT)
        _Tooltip(self._apply_btn,
                 "Writes the imported letters over this font's glyph PNGs in "
                 "the project folder. Build on the Write tab to put them on "
                 "the card; Revert font undoes them.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        # Undo is NOT Revert: Revert goes back to stock, Undo goes back one
        # step — to the import you had before this one, and out of an
        # accidental "Revert all fonts" after an afternoon of restyling.
        self._undo_btn = ttk.Button(brow, text="Undo", command=self._undo_last,
                                    state="disabled")
        self._undo_btn.pack(side=tk.LEFT, padx=(8, 0))
        _Tooltip(self._undo_btn,
                 "Steps back through the last few font writes made in this "
                 "window — including \"Revert all fonts\". Different from "
                 "\"Revert font\", which goes all the way back to the stock "
                 "letters.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        # Blanking used to happen only as a side effect of importing into the
        # font an outline sits behind, which is no help when the font you want
        # gone is the one you are looking at (Peter: "Not sure what i want to do
        # with Outline/shadow fonts. Is there an easy way to blank it out?").
        self._blank_btn = ttk.Button(brow, text="Blank font",
                                     command=self._blank)
        self._blank_btn.pack(side=tk.LEFT, padx=(8, 0))
        _Tooltip(self._blank_btn,
                 "Erases every letter of this font so it draws nothing — the "
                 "way to drop an outline or shadow font you don't want. The "
                 "scene still draws it, it just has nothing to draw.\n\n"
                 "It follows the scene choice on the left, so you can blank it "
                 "in one scene and leave the rest alone. \"Revert font\" puts "
                 "the letters back.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        self._revert_btn = ttk.Button(brow, text="Revert font",
                                      command=self._revert)
        self._revert_btn.pack(side=tk.LEFT, padx=(8, 0))
        _Tooltip(self._revert_btn,
                 "Restores every letter of this font from its atlas image — "
                 "undoes imports and hand edits of the glyph PNGs.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        self._revert_all_btn = ttk.Button(brow, text="Revert all fonts…",
                                          command=self._revert_all)
        self._revert_all_btn.pack(side=tk.LEFT, padx=(8, 0))
        _Tooltip(self._revert_all_btn,
                 "Puts EVERY font in this project back to stock — the way to "
                 "start a restyle over without re-extracting the card (Peter: "
                 "\"i think i have to start from scratch\").",
                 lambda: getattr(self.app, "_current_theme", "light"))
        ttk.Button(brow, text="Close", command=self._close).pack(side=tk.RIGHT)

        self._paint_swatches()
        center_over(self.app.root, win, 1040, 620)
        win.deiconify()
        win.lift()

    def _close(self):
        # An import that was fitted but never applied is invisible once the
        # window is gone, and the user finds out on the machine (Peter: "on
        # some i have forgotten to press the apply font").
        if self._pending:
            names = ", ".join(
                sorted((self._by_key.get(k, {}).get("name") or k)
                       for k in self._pending)[:4])
            if not messagebox.askyesno(
                    "Unapplied import",
                    "%d font(s) have an import that was never applied (%s%s)."
                    "\n\nThose letters are NOT in the project folder and will "
                    "not reach the card. Close anyway?"
                    % (len(self._pending), names,
                       ", …" if len(self._pending) > 4 else ""),
                    parent=self.win):
                return
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # -- data ------------------------------------------------------------

    def reload(self, preselect=None):
        """(Re)load the fonts from the assets folder and refresh the list."""
        from ..plugins.stern import fontrender as fr
        self._tints = None
        if self._undo_dir != self.assets_dir:
            # History holds absolute paths in the OLD project; undoing after a
            # switch would write files back into a folder the user has left.
            self._undo = []
            self._undo_dir = self.assets_dir
            self._sync_undo()
        try:
            self._fonts = fr.load_fonts(self.assets_dir)
        except Exception:
            self._fonts = []
        self._by_key = {fo["key"]: fo for fo in self._fonts}
        try:
            self._companions = fr.outline_companions(self.assets_dir,
                                                     self._fonts)
        except Exception:
            self._companions = {}
        # Outline fonts that no body font could be matched to — still worth
        # naming, since the user will see their border and have nowhere to
        # look; just not something to act on automatically.
        self._loose_outlines = {}
        paired = {fo["key"] for fo in self._companions.values()}
        for fo in self._fonts:
            base = fr.outline_base(fo.get("name"))
            if base and fo["key"] not in paired:
                self._loose_outlines.setdefault(base, []).append(fo)
        self._scene_counts = {}
        for fo in self._fonts:
            try:
                self._scene_counts[fo["key"]] = len(
                    fr.scenes_for_font(self.assets_dir, fo))
            except Exception:
                self._scene_counts[fo["key"]] = 0
        if not self._fonts:
            self._hint.configure(
                text="No game fonts found in this project folder. Run "
                     "Extract (with Images enabled) on a Stern Spike 2 card "
                     "image first — every font then shows up here.")
        else:
            n_old = sum(1 for fo in self._fonts if not fo["has_metrics"])
            msg = ("%d game font(s) in %s." %
                   (len(self._fonts), self.assets_dir))
            if n_old:
                msg += (" This extract predates exact font metrics — "
                        "previews use approximate spacing. Re-extract to "
                        "get exact layout.")
            self._hint.configure(text=msg)
        self._refresh_font_list(preselect)

    def _refresh_font_list(self, preselect=None):
        from ..plugins.stern import fontrender as fr
        tree = self._tree
        tree.delete(*tree.get_children())
        q = (self._search_var.get() or "").strip().lower()
        for fo in self._fonts:
            label = "%s" % (fo["name"] or fo["key"])
            if q and q not in label.lower() and q not in fo["key"].lower():
                continue
            # The size column carries the two things that decide whether a
            # font is worth restyling at all: too small to hold a typeface,
            # and whether an outline font will fight the result.  A font can
            # be both, so neither marker hides the other.
            marks = []
            if fo["key"] in self._pending:
                # Peter: "on some i have forgotten to press the apply font :("
                marks.append("NOT APPLIED")
            if fo["px"] < fr.MIN_RESTYLE_PX:
                marks.append("tiny")
            if self._companions.get(fo["key"]) is not None:
                marks.append("+outline")
            size = "%dpx%s" % (fo["px"],
                               (" · " + " ".join(marks)) if marks else "")
            tree.insert("", tk.END, iid=fo["key"], text=label,
                        values=(size, len(fo["glyphs"]),
                                self._scene_counts.get(fo["key"], 0)))
        kids = tree.get_children()
        want = preselect if preselect in (kids or ()) else (
            kids[0] if kids else None)
        if want:
            tree.selection_set(want)
            tree.see(want)
        self._on_select()

    def _current_font(self):
        sel = self._tree.selection()
        return self._by_key.get(sel[0]) if sel else None

    # -- go and look at a scene this font is in ---------------------------

    def _scene_popup(self, event):
        """Right-click a scene in the list: open it in the Scenes window.

        Right-click and not double-click on purpose — the selection in this
        listbox IS the font's scene scope, and a jump must not quietly
        rewrite which scenes an import lands in."""
        if not self._scene_paths:
            return
        i = self._scenes_list.nearest(event.y)
        if not 0 <= i < len(self._scene_paths):
            return
        card = self._scene_paths[i]
        th = self._theme()
        menu = tk.Menu(self._scenes_list, tearoff=0)
        try:
            menu.configure(background=th.get("field_bg"),
                           foreground=th.get("fg"),
                           activebackground=th.get("select_bg"),
                           activeforeground="#ffffff")
        except tk.TclError:
            pass
        menu.add_command(label="Show \"%s\" in Scenes…" % scene_label(card),
                         command=lambda c=card: self._show_scene(c))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_scene(self, card):
        from .scene_browser import open_scene_browser
        open_scene_browser(
            self.app, self.assets_dir,
            preselect=card.replace("\\", "/").rsplit("/", 1)[0])

    # -- preview ---------------------------------------------------------

    def _on_select(self):
        fo = self._current_font()
        self._scenes_list.delete(0, tk.END)
        self._scene_paths = []
        if fo is not None:
            from ..plugins.stern import fontrender as fr
            try:
                for p in fr.scenes_for_font(self.assets_dir, fo):
                    self._scene_paths.append(p)
                    self._scenes_list.insert(tk.END, " %s — %s"
                                             % (scene_label(p), p))
            except Exception:
                pass
            self._load_scope(fo)
            if self._auto_color_var.get():
                try:
                    self._color = fr.font_color(fo)
                except Exception:
                    self._color = (255, 255, 255)
                self._paint_swatches()
            ttf = self._ttf_paths.get(fo["key"])
            self._ttf_lbl.configure(
                text=os.path.basename(ttf) if ttf else "no file chosen")
        self._sync_companion(fo)
        self._sync_tint(fo)
        self._sync_all_sizes(fo)
        self._sync_show_combo()
        self._schedule_render()

    # -- what the scenes do to this font's colour --------------------------

    def _tints_for(self, font):
        """``[((r, g, b), lines)]`` the scenes draw *font* in, commonest first.

        Read from the recorded scene layouts, lazily — the file is small but
        there is no point touching it for a project that has none."""
        if self._tints is None:
            try:
                self._tints = _scene_render.text_tints(
                    _scene_render.load_layouts(self.assets_dir))
            except Exception:
                self._tints = {}
        per = self._tints.get(font["key"]) if font else None
        return sorted((per or {}).items(), key=lambda kv: -kv[1])

    def _sync_tint(self, font):
        """Say what the game multiplies this font's ink by, and what that means
        for the colour picker above."""
        th = self._theme()
        self._tint_lbl.pack_forget()
        if font is None:
            return
        tints = self._tints_for(font)
        if not tints:
            return
        total = sum(n for _c, n in tints)
        white = sum(n for c, n in tints if min(c) >= 250)
        black = sum(n for c, n in tints if max(c) <= 5)
        listed = ", ".join(
            "%s x%d" % ("white" if min(c) >= 250 else
                        ("black" if max(c) <= 5 else "#%02x%02x%02x" % c), n)
            for c, n in tints[:5])
        if white == total:
            msg = ("The scenes draw this font white (%d line%s), so the ink "
                   "colour above is exactly what shows on the machine."
                   % (total, "" if total == 1 else "s"))
            fg = th["gray"]
        else:
            msg = ("The scenes tint this font: %s. That colour MULTIPLIES the "
                   "ink you import, so your colour only comes out as picked "
                   "where the scene is white%s. To colour a line itself, "
                   "right-click it in the Scenes window."
                   % (listed,
                      " — and not at all on the %d line(s) tinted black"
                      % black if black else ""))
            fg = th["warning"] if black else th["gray"]
        self._tint_lbl.configure(text=msg, foreground=fg)
        # ...above the buttons: packed in call order it lands under them and
        # runs off the bottom of the window.
        self._tint_lbl.pack(anchor=tk.W, fill=tk.X, padx=8, pady=(2, 0),
                            before=self._arow)

    # -- outline companion ------------------------------------------------

    def _companion(self, font):
        """The outline font drawn behind *font*, or None."""
        return self._companions.get(font["key"]) if font else None

    def _sync_companion(self, font):
        """Say what sits behind this font — or what this font sits behind."""
        from ..plugins.stern import fontrender as fr
        th = self._theme()
        self._comp_row.pack_forget()
        self._comp_ctrl.pack_forget()
        if font is None:
            return
        comp = self._companion(font)
        if comp is not None:
            self._comp_lbl.configure(
                text="The game draws \"%s\" (%dpx) in black behind these "
                     "letters. Restyle this font alone and that original "
                     "outline stays around your new letters."
                     % (comp["name"] or comp["key"], comp["px"]),
                foreground=th["warning"])
            self._comp_row.pack(fill=tk.X, padx=8, pady=(2, 0),
                                before=self._arow)
            self._comp_ctrl.pack(fill=tk.X, pady=(3, 0))
            return
        base = fr.outline_base(font.get("name"))
        if base:
            self._comp_lbl.configure(
                text="This IS an outline font — the game draws it in black "
                     "behind \"%s\" and puts that font's letters on top. "
                     "Restyle \"%s\" instead unless you mean to change the "
                     "border itself." % (base, base),
                foreground=th["gray"])
            self._comp_row.pack(fill=tk.X, padx=8, pady=(2, 0),
                                before=self._arow)
            return
        loose = self._loose_outlines.get((font.get("name") or "").strip())
        if loose:
            self._comp_lbl.configure(
                text="This typeface also has outline font(s) here (%s) that "
                     "draw a black border behind it, but none matches this "
                     "size — restyle or blank them from their own row if you "
                     "see a leftover border."
                     % ", ".join("%s %dpx" % (f["name"], f["px"])
                                 for f in loose[:3]),
                foreground=th["gray"])
            self._comp_row.pack(fill=tk.X, padx=8, pady=(2, 0),
                                before=self._arow)

    # -- scope (which scenes an edit lands in) ---------------------------

    def _load_scope(self, font):
        """Reflect *font*'s saved scope in the radio + listbox selection."""
        from ..plugins.stern import fontrender as fr
        try:
            cards = fr.get_font_scope(self.assets_dir, font)
        except Exception:
            cards = None
        self._scenes_list.selection_clear(0, tk.END)
        if cards:
            self._scope_var.set("some")
            chosen = set(cards)
            for i, p in enumerate(self._scene_paths):
                if p in chosen:
                    self._scenes_list.selection_set(i)
        else:
            self._scope_var.set("all")
        self._sync_scope_ui()

    def _sync_scope_ui(self):
        """Enable the picker only in "some" mode and explain the current
        scope in one line."""
        some = self._scope_var.get() == "some"
        try:
            self._scenes_list.configure(
                selectmode=tk.EXTENDED if some else tk.BROWSE,
                state=tk.NORMAL)
        except tk.TclError:
            pass
        total = len(self._scene_paths)
        if not some:
            self._scope_lbl.configure(
                text="An import or glyph edit is written to %s."
                     % ("the 1 scene using this font" if total == 1
                        else "all %d scenes using this font" % total))
            return
        n = len(self._scenes_list.curselection())
        if n:
            # "the rest" sidesteps singular/plural agreement on the remainder.
            self._scope_lbl.configure(
                text="Only %d of %d scenes get this font; the rest keep the "
                     "stock one." % (n, total))
        else:
            self._scope_lbl.configure(
                text="Pick one or more scenes above — with none selected "
                     "nothing would be written.")

    def _on_scope_mode(self):
        fo = self._current_font()
        if fo is None:
            return
        if self._scope_var.get() == "some" and \
                not self._scenes_list.curselection() and self._scene_paths:
            self._scenes_list.selection_set(0)   # a usable starting point
        self._sync_scope_ui()
        self._save_scope()

    def _on_scope_select(self):
        if self._scope_var.get() != "some":
            return
        self._sync_scope_ui()
        self._save_scope()

    def _save_scope(self):
        """Persist the scope to the project folder (it is read at Build, so it
        must survive closing this window)."""
        fo = self._current_font()
        if fo is None:
            return
        from ..plugins.stern import fontrender as fr
        if self._scope_var.get() == "some":
            cards = [self._scene_paths[i]
                     for i in self._scenes_list.curselection()
                     if i < len(self._scene_paths)]
        else:
            cards = None
        try:
            fr.set_font_scope(self.assets_dir, fo, cards)
        except OSError as e:
            self._status.configure(text="Could not save the scene scope: %s" % e)

    def _custom_color(self):
        """True when the user has chosen an ink colour of their own.

        It is a SETTING, not a per-font edit: once picked it follows you down
        the font list and every preview shows it, because "what colour are my
        letters" is a decision about the restyle, not about one 96px entry
        (David: "when i change the font selection, the color preview does not
        carry over")."""
        try:
            return not self._auto_color_var.get()
        except tk.TclError:
            return False

    def _sync_show_combo(self):
        fo = self._current_font()
        has_pending = fo is not None and fo["key"] in self._pending
        vals = (("Current glyphs", "Imported (preview)") if has_pending
                else ("Current glyphs",))
        self._show_combo.configure(values=vals)
        if not has_pending:
            self._show_var.set("Current glyphs")
        # A colour on its own is enough to apply: it repaints the letters that
        # are already there, no font file needed.
        self._apply_btn.configure(
            state="normal" if (has_pending or (fo is not None
                                               and self._custom_color()))
            else "disabled")

    def _schedule_render(self):
        if self._render_job is not None:
            try:
                self.win.after_cancel(self._render_job)
            except tk.TclError:
                return
        self._render_job = self.win.after(120, self._render_now)

    def _render_now(self):
        self._render_job = None
        fo = self._current_font()
        canvas = self._canvas
        canvas.delete("all")
        if fo is None:
            return
        from ..plugins.stern import fontrender as fr
        text = self._text_var.get().replace("\\n", "\n") or " "
        loader = None
        pend = self._pending.get(fo["key"])
        recolored = False
        if pend and self._show_var.get() != "Current glyphs":
            slices = pend[0]
            loader = (lambda g: fr.load_slice(g, slices.get(g["char"])))
        elif self._custom_color():
            # Show the chosen ink on THIS font's own letters.  Only the glyphs
            # actually drawn are repainted, so moving down a 300-font list stays
            # instant — the full repaint happens once, on Apply.
            recolored = True
            rgb = self._color
            loader = (lambda g: fr.tint_slice(fr.load_slice(g), rgb))
        try:
            img, missing = fr.render_text(fo, text, slice_loader=loader)
        except fr.FontError as e:
            self._status.configure(text=str(e))
            return
        except Exception as e:
            self._status.configure(text="Preview failed: %s" % e)
            return
        zoom = int((self._zoom_var.get() or "1x")[0])
        if zoom > 1:
            from PIL import Image
            img = img.resize((img.size[0] * zoom, img.size[1] * zoom),
                             Image.NEAREST)
        bg = self._bg_var.get()
        try:
            img = _scene_render.flatten_over_background(img, bg)
        except Exception:
            pass                      # a preview is never worth an exception
        try:
            from PIL import ImageTk
            self._photo = ImageTk.PhotoImage(img)
        except Exception as e:
            self._status.configure(text="Preview failed: %s" % e)
            return
        spec = _scene_render.background_spec(bg)
        try:
            canvas.configure(bg=("#%02x%02x%02x" % spec
                                 if isinstance(spec, tuple) else "#96969c"))
        except tk.TclError:
            pass
        canvas.create_image(8, 8, image=self._photo, anchor=tk.NW)
        canvas.configure(scrollregion=(0, 0, img.size[0] + 16,
                                       img.size[1] + 16))
        bits = []
        if recolored:
            bits.append("showing this font's letters in %s — \"Apply to this "
                        "font\" repaints all %d of them"
                        % ("#%02x%02x%02x" % self._color, len(fo["glyphs"])))
        if pend:
            bits.append("import fitted at %dpx (%d letters redrawn%s)"
                        % (pend[1], len(pend[0]),
                           ", %d kept" % len(pend[2]) if pend[2] else ""))
        if missing:
            bits.append("not in this font: %s"
                        % " ".join(sorted(missing)[:20]))
        if not fo["has_metrics"]:
            bits.append("approximate spacing — re-extract for exact layout")
        self._status.configure(text="; ".join(bits))

    # -- import ----------------------------------------------------------

    def _paint_swatches(self):
        for cv, rgb in ((self._color_btn, self._color),
                        (self._stroke_btn, self._stroke_color)):
            cv.delete("all")
            cv.configure(bg="#%02x%02x%02x" % tuple(rgb))

    def _pick_color(self):
        rgb = colorchooser.askcolor(color="#%02x%02x%02x" % self._color,
                                    parent=self.win)[0]
        if rgb:
            self._color = tuple(int(c) for c in rgb)
            self._auto_color_var.set(False)
            self._paint_swatches()
            self._on_option_change()

    def _pick_stroke(self):
        rgb = colorchooser.askcolor(
            color="#%02x%02x%02x" % self._stroke_color, parent=self.win)[0]
        if rgb:
            self._stroke_color = tuple(int(c) for c in rgb)
            self._paint_swatches()
            self._on_option_change()

    def _pick_ttf(self):
        fo = self._current_font()
        if fo is None:
            return
        path = filedialog.askopenfilename(
            parent=self.win, title="Choose a font file",
            filetypes=[("Fonts", "*.ttf *.otf *.ttc"), ("All files", "*.*")])
        if not path:
            return
        self._ttf_paths[fo["key"]] = path
        self._ttf_lbl.configure(text=os.path.basename(path))
        self._rasterize()

    def _on_option_change(self):
        fo = self._current_font()
        if fo is None:
            return
        if self._auto_color_var.get():
            from ..plugins.stern import fontrender as fr
            try:
                self._color = fr.font_color(fo)
            except Exception:
                pass
            self._paint_swatches()
        if fo["key"] in self._ttf_paths:
            self._rasterize()
        else:
            # No font file: the colour is previewed straight onto this font's
            # own letters, and Apply is what writes it.
            self._sync_show_combo()
            self._schedule_render()

    def _import_options(self):
        """The rasterizer settings the option row currently shows.  One place,
        because "apply to every size" has to fit the SAME choices into each
        size's own slots."""
        def pct(var, lo):
            return max(lo, min(100, int(var.get() or 100))) / 100.0
        return {"color": self._color,
                "stroke": max(0, int(self._stroke_var.get() or 0)),
                "stroke_color": self._stroke_color,
                "size_scale": pct(self._scale_var, 50),
                "width_scale": pct(self._width_var, 60)}

    def _rasterize(self):
        fo = self._current_font()
        if fo is None:
            return
        ttf = self._ttf_paths.get(fo["key"])
        if not ttf:
            return
        from ..plugins.stern import fontrender as fr
        try:
            self.win.configure(cursor="watch")
            self.win.update_idletasks()
            slices, size, kept = fr.rasterize_ttf(fo, ttf,
                                                  **self._import_options())
        except fr.FontError as e:
            messagebox.showerror("Import failed", str(e), parent=self.win)
            return
        except Exception as e:
            messagebox.showerror("Import failed",
                                 "Couldn't fit this font:\n\n%s" % e,
                                 parent=self.win)
            return
        finally:
            try:
                self.win.configure(cursor="")
            except tk.TclError:
                pass
        self._pending[fo["key"]] = (slices, size, kept, ttf)
        self._show_var.set("Imported (preview)")
        self._sync_show_combo()
        self._schedule_render()

    # -- undo -------------------------------------------------------------

    def _push_undo(self, label, fonts):
        """Remember how *fonts* look right now, before something writes them.

        Taken BEFORE the write, so undo restores whatever was there — a
        previous import, a hand edit, or stock — rather than assuming stock the
        way Revert does."""
        from ..plugins.stern import fontrender as fr
        seen, uniq = set(), []
        for fo in fonts:
            if fo is not None and fo["key"] not in seen:
                seen.add(fo["key"])
                uniq.append(fo)
        if not uniq:
            return
        # Reading thousands of slices cold is slow enough to look like a hang
        # (35 s for a whole project on a OneDrive folder), so say what it is.
        noisy = len(uniq) > 8
        if noisy:
            self.win.configure(cursor="watch")

        def tick(done, total):
            if noisy and done % 10 == 0:
                self._status.configure(
                    text="Saving undo state… %d of %d font(s)"
                         % (done + 1, total))
                self.win.update_idletasks()
        try:
            snap = fr.snapshot_fonts(uniq, progress=tick if noisy else None)
        except Exception:
            return                       # never let bookkeeping block the edit
        finally:
            if noisy:
                try:
                    self.win.configure(cursor="")
                except tk.TclError:
                    pass
        self._undo.append((label, snap))
        # Bound the history by BYTES first: one "Revert all fonts" snapshot is
        # the whole project, and five of those is not a sensible thing to hold.
        while len(self._undo) > _UNDO_STEPS or (
                len(self._undo) > 1
                and sum(fr.snapshot_bytes(s) for _l, s in self._undo)
                > _UNDO_BYTES):
            self._undo.pop(0)
        self._sync_undo()

    def _sync_undo(self):
        try:
            self._undo_btn.configure(
                state="normal" if self._undo else "disabled",
                text=("Undo %s" % self._undo[-1][0]) if self._undo else "Undo")
        except tk.TclError:
            pass

    def _undo_last(self):
        """Put the last write back the way it was."""
        if not self._undo:
            return
        from ..plugins.stern import fontrender as fr
        label, snap = self._undo.pop()
        self.win.configure(cursor="watch")
        try:
            n = fr.restore_snapshot(snap)
        finally:
            try:
                self.win.configure(cursor="")
            except tk.TclError:
                pass
        self._pending.clear()
        self._sync_undo()
        self._sync_show_combo()
        self._refresh_font_list(
            self._tree.selection()[0] if self._tree.selection() else None)
        self._schedule_render()
        self._notify_changed()
        self._status.configure(
            text="Undid %s — %d letter file(s) put back." % (label, n))

    def _same_typeface(self, font):
        """The OTHER entries of this typeface — the same name at other sizes,
        each its own glyph table with its own slots."""
        name = (font.get("name") or "").strip()
        if not name:
            return []
        return [f for f in self._fonts
                if f["key"] != font["key"]
                and (f.get("name") or "").strip() == name]

    def _sync_all_sizes(self, font):
        """Label the all-sizes tick with the real count, and hide it for a
        typeface that only exists once."""
        sibs = self._same_typeface(font) if font is not None else []
        if not sibs:
            self._all_sizes_cb.pack_forget()
            return
        self._all_sizes_cb.configure(
            text="Also apply to the other %d size%s of \"%s\""
                 % (len(sibs), "" if len(sibs) == 1 else "s",
                    font.get("name") or font["key"]))
        self._all_sizes_cb.pack(side=tk.LEFT)

    def _apply(self):
        fo = self._current_font()
        if fo is None:
            return
        from ..plugins.stern import fontrender as fr
        pend = self._pending.get(fo["key"])
        # No import staged, but a colour of the user's own is on screen: Apply
        # means "repaint this font's letters in it".  Computed HERE rather than
        # when the colour was picked, so browsing the font list never pays for
        # a repaint the user didn't ask to keep.
        recolor = pend is None
        if recolor:
            if not self._custom_color():
                return
            try:
                self.win.configure(cursor="watch")
                self.win.update_idletasks()
                pend = (fr.recolor_slices(fo, self._color), fo["px"], [], None)
            except Exception as e:
                messagebox.showerror(
                    "Recolour failed",
                    "Couldn't repaint these letters:\n\n%s" % e,
                    parent=self.win)
                return
            finally:
                try:
                    self.win.configure(cursor="")
                except tk.TclError:
                    pass
            self._pending[fo["key"]] = pend
        # Restyling a font too small to carry a typeface is Peter's "smaller
        # fonts do look more and more strange the smaller they get"; say so
        # once, with the number, rather than refusing.  A recolour is exempt:
        # it keeps every letter's shape, so size has nothing to do with it.
        if not recolor and fo["px"] < fr.MIN_RESTYLE_PX and not messagebox.askyesno(
                "Small font",
                "\"%s\" is only %d pixels tall. Below about %d a desktop font "
                "loses its shape when it is fitted into letters this small, "
                "and the result usually looks worse than the original.\n\n"
                "Import into it anyway?"
                % (fo["name"] or fo["key"], fo["px"], fr.MIN_RESTYLE_PX),
                parent=self.win):
            return
        sibs_planned = (self._same_typeface(fo)
                        if self._all_sizes_var.get() else [])
        self._push_undo(
            "the %s \"%s\"" % ("recolour of" if recolor else "import into",
                               fo["name"] or fo["key"]),
            [fo, self._companion(fo)] + sibs_planned
            + [self._companion(s) for s in sibs_planned])
        n, n_comp = self._write_font(fo, pend[0])
        comp = self._companion(fo)
        del self._pending[fo["key"]]

        # …and the same font file into every other size of this typeface, each
        # fitted to its own slots.  Without this a restyle only reaches the one
        # size that happened to be selected.
        sibs = sibs_planned
        n_sib = n_failed = 0
        errors = []
        if sibs:
            ttf = pend[3]
            self.win.configure(cursor="watch")
            try:
                for i, sib in enumerate(sibs):
                    self._status.configure(
                        text="%s size %d of %d…"
                             % ("Repainting" if recolor else
                                "Fitting \"%s\" into" % os.path.basename(ttf),
                                i + 1, len(sibs)))
                    self.win.update_idletasks()
                    try:
                        if recolor:
                            slices = fr.recolor_slices(sib, self._color)
                        else:
                            slices, _sz, _kept = fr.rasterize_ttf(
                                sib, ttf, **self._import_options())
                    except Exception:
                        # One size that can't take the font must not abandon
                        # the rest; the count below says how many missed.
                        n_failed += 1
                        continue
                    self._write_font(sib, slices, errors)
                    self._pending.pop(sib["key"], None)
                    n_sib += 1
            finally:
                try:
                    self.win.configure(cursor="")
                except tk.TclError:
                    pass
            if errors:
                messagebox.showwarning(
                    "Outline fonts",
                    "The letters were written, but %d outline font(s) could "
                    "not be removed:\n\n%s" % (len(errors),
                                               "\n".join(errors[:6])),
                    parent=self.win)

        self._show_var.set("Current glyphs")
        self._sync_show_combo()
        self._refresh_font_list(fo["key"])
        self._schedule_render()
        self._notify_changed()
        if self._scope_var.get() == "some":
            where = ("%d selected scene(s)"
                     % len(self._scenes_list.curselection()))
        else:
            where = "all %d scene(s) using this font" % len(self._scene_paths)
        msg = ("%d letter(s) %s in the project folder, for %s"
               % (n, "repainted %s" % ("#%02x%02x%02x" % self._color)
                  if recolor else "written", where))
        if n_comp:
            msg += ("; its outline font \"%s\" was blanked (%d letter(s)) so "
                    "the old border is gone — only in the scenes this font is "
                    "in, so the same outline stays put everywhere else"
                    % (comp["name"] or comp["key"], n_comp))
        elif comp is not None:
            msg += ("; its outline font \"%s\" was left as it is"
                    % (comp["name"] or comp["key"]))
        if n_sib:
            msg += ("; %d more size(s) of \"%s\" %s too"
                    % (n_sib, fo["name"] or fo["key"],
                       "were repainted" if recolor else "took the same font"))
            if self._scope_var.get() == "some":
                msg += (" (those keep their own scene choice, which is every "
                        "scene unless you narrow them)")
        if n_failed:
            msg += ("; %d size(s) could not take this font and were left "
                    "alone" % n_failed)
        self._status.configure(
            text=msg + " — build on the Write tab to put them on the card.")

    def _scope_companion(self, font, comp):
        """Limit the companion's blanking to the scenes this font is in.

        Blanking is otherwise CARD-WIDE: one atlas is shared by every scene
        that draws it, and on TMNT a paired outline font turns up 440 times in
        scenes where its body font ISN'T — so a plain blank strips outlines off
        screens the user never touched.  Peter did exactly this by hand and
        reported "i did remove to much shadow, now on the normal font some are
        missing too".  Scoping it to the overlap keeps the rest stock."""
        from ..plugins.stern import fontrender as fr
        try:
            mine = set(fr.scenes_for_font(self.assets_dir, font))
            theirs = set(fr.scenes_for_font(self.assets_dir, comp))
        except Exception:
            return 0
        both = sorted(mine & theirs)
        if not both:
            return 0
        try:
            fr.set_font_scope(self.assets_dir, comp, both)
        except Exception:
            return 0
        return len(both)

    def _write_font(self, font, slices, errors=None):
        """Write one font's slices and handle its outline companion.  Returns
        ``(letters written, companion letters blanked)``.

        Companion failures are COLLECTED, not shown: this runs once per size,
        and a typeface with 94 of them would otherwise stack 94 dialogs."""
        from ..plugins.stern import fontrender as fr
        n = fr.save_slices(font, slices)
        comp = self._companion(font)
        n_comp = 0
        if comp is not None and self._comp_var.get() == _COMP_CLEAR:
            try:
                self._scope_companion(font, comp)
                n_comp = fr.clear_font(comp)
            except Exception as e:
                if errors is None:
                    messagebox.showwarning(
                        "Outline font",
                        "The letters were written, but its outline font "
                        "\"%s\" could not be removed:\n\n%s"
                        % (comp["name"], e), parent=self.win)
                else:
                    errors.append("%s: %s" % (comp["name"] or comp["key"], e))
        return n, n_comp

    def _blank(self):
        """Erase this font's letters so it draws nothing.

        Deliberately NOT the same as reverting: revert goes back to Stern's
        letters, this leaves the font in place with empty ones.  It is how an
        outline or shadow font is removed, and it honours the scene scope
        chosen on the left — blanking is card-wide otherwise, which is how
        Peter lost borders on screens he had never opened."""
        fo = self._current_font()
        if fo is None:
            return
        from ..plugins.stern import fontrender as fr
        some = self._scope_var.get() == "some"
        n_sel = len(self._scenes_list.curselection())
        if some and not n_sel:
            self._status.configure(
                text="Pick the scenes to blank it in first, or switch to "
                     "\"Change in all of them\".")
            return
        where = ("the %d scene(s) selected on the left" % n_sel if some
                 else "all %d scene(s) using it" % len(self._scene_paths))
        if not messagebox.askyesno(
                "Blank font",
                "Erase every letter of \"%s\" (%dpx) so it draws nothing, in "
                "%s?\n\nThe scene still draws this font — it just has nothing "
                "to draw, which is how an outline or shadow is removed. "
                "\"Revert font\" restores Stern's letters, and \"Undo\" steps "
                "back to whatever was there a moment ago."
                % (fo["name"] or fo["key"], fo["px"], where), parent=self.win):
            return
        self._push_undo("blanking \"%s\"" % (fo["name"] or fo["key"]), [fo])
        try:
            n = fr.clear_font(fo)
        except Exception as e:
            messagebox.showerror("Blank font",
                                 "Couldn't blank this font:\n\n%s" % e,
                                 parent=self.win)
            return
        self._pending.pop(fo["key"], None)
        self._sync_show_combo()
        self._schedule_render()
        self._notify_changed()
        self._status.configure(
            text="%d letter(s) blanked in %s — build on the Write tab to put "
                 "it on the card." % (n, where))

    def _revert(self):
        fo = self._current_font()
        if fo is None:
            return
        comp = self._companion(fo)
        extra = ("\n\nIts outline font \"%s\" is restored too, so a border "
                 "this window removed comes back."
                 % (comp["name"] or comp["key"])) if comp is not None else ""
        if not messagebox.askyesno(
                "Revert font",
                "Restore every letter of \"%s\" from its atlas image?\n\n"
                "This undoes imported and hand-edited glyph PNGs for this "
                "font.%s" % (fo["name"] or fo["key"], extra),
                parent=self.win):
            return
        from ..plugins.stern import fontrender as fr
        self._push_undo("reverting \"%s\"" % (fo["name"] or fo["key"]),
                        [fo, comp])
        n = fr.revert_slices(self.assets_dir, fo)
        # Apply can blank the companion, so Revert has to be able to undo
        # that too — otherwise the only way back is a full re-extract, which
        # would take the user's other work with it.
        if comp is not None:
            n += fr.revert_slices(self.assets_dir, comp)
        self._pending.pop(fo["key"], None)
        self._sync_show_combo()
        self._schedule_render()
        self._notify_changed()
        self._status.configure(text="%d letter(s) restored." % n)

    def _revert_all(self):
        """Put every font in the project back to stock.

        Peter, mid-restyle: "i think i have to start from scratch, so much
        changes."  Reverting 300-odd fonts one at a time is not a route, and
        re-extracting is worse — it rewrites every image in the project and
        would take his other work with it."""
        from ..plugins.stern import fontrender as fr
        if not self._fonts:
            return
        if not messagebox.askyesno(
                "Revert all fonts",
                "Restore all %d fonts in this project from their atlas "
                "images?\n\nThis undoes every font import, glyph edit and "
                "removed outline in this folder — a clean slate to restyle "
                "from. Nothing else in the project is touched.\n\n"
                "\"Undo\" brings it all back if you change your mind."
                % len(self._fonts), parent=self.win):
            return
        self._push_undo("reverting all fonts", list(self._fonts))
        n = fonts_done = 0
        self.win.configure(cursor="watch")
        try:
            for i, fo in enumerate(self._fonts):
                if i % 10 == 0:
                    self._status.configure(
                        text="Restoring font %d of %d…" % (i + 1,
                                                           len(self._fonts)))
                    self.win.update_idletasks()
                try:
                    n += fr.revert_slices(self.assets_dir, fo)
                    fonts_done += 1
                except Exception:
                    continue
        finally:
            try:
                self.win.configure(cursor="")
            except tk.TclError:
                pass
        self._pending.clear()
        self._sync_show_combo()
        self._refresh_font_list(
            self._tree.selection()[0] if self._tree.selection() else None)
        self._schedule_render()
        self._notify_changed()
        self._status.configure(
            text="%d letter(s) across %d font(s) restored to stock."
                 % (n, fonts_done))

    def _notify_changed(self):
        """Tell the main window glyph files changed on disk so the Images
        tab's change markers stay honest."""
        try:
            self.app._start_change_scan("image")
        except Exception:
            pass


def open_font_studio(app, assets_dir, preselect=None):
    """Open (or re-use and refocus) the app's Fonts window."""
    win = getattr(app, "_font_studio", None)
    if win is not None:
        try:
            if win.win.winfo_exists():
                if win.assets_dir != assets_dir:
                    win.assets_dir = assets_dir
                    win.reload(preselect)
                elif preselect:
                    win.reload(preselect)
                win.win.deiconify()
                win.win.lift()
                win.win.focus_set()
                return win
        except tk.TclError:
            pass
    win = FontStudioWindow(app, assets_dir, preselect=preselect)
    app._font_studio = win
    return win
