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

from .theme import THEMES, platform_font
from .widgets import _Tooltip, center_over

_PREVIEW_DEFAULT = "THE QUICK BROWN FOX 0123456789"
_PREVIEW_BG = "#101014"


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
        self._tree.column("px", width=52, minwidth=40, stretch=False)
        self._tree.column("chars", width=52, minwidth=40, stretch=False)
        self._tree.column("scenes", width=56, minwidth=40, stretch=False)
        tsc = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=tsc.set)
        tsc.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        ttk.Label(left, text="Used in scenes:", font=(self._sans, 9)).pack(
            anchor=tk.W, pady=(6, 0))
        self._scenes_list = tk.Listbox(
            left, height=5, activestyle="none",
            bg=th["field_bg"], fg=th["fg"], highlightthickness=0)
        self._scenes_list.pack(fill=tk.X)
        _Tooltip(self._scenes_list,
                 "The scene files whose atlases hold this font — the same "
                 "8-character scene shorthand the Images tab's scene groups "
                 "use.",
                 lambda: getattr(self.app, "_current_theme", "light"))

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
        self._show_combo.pack(side=tk.LEFT, padx=(2, 0))
        self._show_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self._schedule_render())

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
                 "Ink color for the imported letters. Starts on the color "
                 "sampled from the game font, so the swap keeps its look — "
                 "click to choose your own.",
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
        self._stroke_btn.pack(side=tk.LEFT, padx=(2, 12))
        self._stroke_btn.bind("<Button-1>", lambda _e: self._pick_stroke())
        self._stroke_color = (0, 0, 0)
        ttk.Label(orow, text="Size:").pack(side=tk.LEFT)
        self._scale_var = tk.IntVar(value=100)
        sc = ttk.Spinbox(orow, from_=50, to=100, increment=5, width=4,
                         textvariable=self._scale_var,
                         command=self._on_option_change)
        sc.pack(side=tk.LEFT, padx=(4, 2))
        ttk.Label(orow, text="% of the auto-fitted size").pack(side=tk.LEFT)

        brow = ttk.Frame(imp)
        brow.pack(fill=tk.X, padx=8, pady=(4, 8))
        self._apply_btn = ttk.Button(brow, text="Apply to this font",
                                     command=self._apply, state="disabled")
        self._apply_btn.pack(side=tk.LEFT)
        _Tooltip(self._apply_btn,
                 "Writes the imported letters over this font's glyph PNGs in "
                 "the project folder. Build on the Write tab to put them on "
                 "the card; Revert font undoes them.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        self._revert_btn = ttk.Button(brow, text="Revert font",
                                      command=self._revert)
        self._revert_btn.pack(side=tk.LEFT, padx=(8, 0))
        _Tooltip(self._revert_btn,
                 "Restores every letter of this font from its atlas image — "
                 "undoes imports and hand edits of the glyph PNGs.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        ttk.Button(brow, text="Close", command=self._close).pack(side=tk.RIGHT)

        self._paint_swatches()
        center_over(self.app.root, win, 1040, 620)
        win.deiconify()
        win.lift()

    def _close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # -- data ------------------------------------------------------------

    def reload(self, preselect=None):
        """(Re)load the fonts from the assets folder and refresh the list."""
        from ..plugins.stern import fontrender as fr
        try:
            self._fonts = fr.load_fonts(self.assets_dir)
        except Exception:
            self._fonts = []
        self._by_key = {fo["key"]: fo for fo in self._fonts}
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
        tree = self._tree
        tree.delete(*tree.get_children())
        q = (self._search_var.get() or "").strip().lower()
        for fo in self._fonts:
            label = "%s" % (fo["name"] or fo["key"])
            if q and q not in label.lower() and q not in fo["key"].lower():
                continue
            tree.insert("", tk.END, iid=fo["key"], text=label,
                        values=("%dpx" % fo["px"], len(fo["glyphs"]),
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

    # -- preview ---------------------------------------------------------

    def _on_select(self):
        fo = self._current_font()
        self._scenes_list.delete(0, tk.END)
        if fo is not None:
            from ..plugins.stern import fontrender as fr
            try:
                for p in fr.scenes_for_font(self.assets_dir, fo):
                    self._scenes_list.insert(tk.END, " %s — %s"
                                             % (scene_label(p), p))
            except Exception:
                pass
            if self._auto_color_var.get():
                try:
                    self._color = fr.font_color(fo)
                except Exception:
                    self._color = (255, 255, 255)
                self._paint_swatches()
            ttf = self._ttf_paths.get(fo["key"])
            self._ttf_lbl.configure(
                text=os.path.basename(ttf) if ttf else "no file chosen")
        self._sync_show_combo()
        self._schedule_render()

    def _sync_show_combo(self):
        fo = self._current_font()
        has_pending = fo is not None and fo["key"] in self._pending
        vals = (("Current glyphs", "Imported (preview)") if has_pending
                else ("Current glyphs",))
        self._show_combo.configure(values=vals)
        if not has_pending:
            self._show_var.set("Current glyphs")
        self._apply_btn.configure(
            state="normal" if has_pending else "disabled")

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
        if pend and self._show_var.get().startswith("Imported"):
            slices = pend[0]
            loader = (lambda g: fr.load_slice(g, slices.get(g["char"])))
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
        try:
            from PIL import ImageTk
            self._photo = ImageTk.PhotoImage(img)
        except Exception as e:
            self._status.configure(text="Preview failed: %s" % e)
            return
        canvas.create_image(8, 8, image=self._photo, anchor=tk.NW)
        canvas.configure(scrollregion=(0, 0, img.size[0] + 16,
                                       img.size[1] + 16))
        bits = []
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
            slices, size, kept = fr.rasterize_ttf(
                fo, ttf, color=self._color,
                stroke=max(0, int(self._stroke_var.get() or 0)),
                stroke_color=self._stroke_color,
                size_scale=max(50, min(100,
                               int(self._scale_var.get() or 100))) / 100.0)
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

    def _apply(self):
        fo = self._current_font()
        if fo is None:
            return
        pend = self._pending.get(fo["key"])
        if not pend:
            return
        from ..plugins.stern import fontrender as fr
        n = fr.save_slices(fo, pend[0])
        del self._pending[fo["key"]]
        self._show_var.set("Current glyphs")
        self._sync_show_combo()
        self._schedule_render()
        self._notify_changed()
        self._status.configure(
            text="%d letter(s) written to the project folder — build on the "
                 "Write tab to put them on the card." % n)

    def _revert(self):
        fo = self._current_font()
        if fo is None:
            return
        if not messagebox.askyesno(
                "Revert font",
                "Restore every letter of \"%s\" from its atlas image?\n\n"
                "This undoes imported and hand-edited glyph PNGs for this "
                "font." % (fo["name"] or fo["key"]), parent=self.win):
            return
        from ..plugins.stern import fontrender as fr
        n = fr.revert_slices(self.assets_dir, fo)
        self._pending.pop(fo["key"], None)
        self._sync_show_combo()
        self._schedule_render()
        self._notify_changed()
        self._status.configure(text="%d letter(s) restored." % n)

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
