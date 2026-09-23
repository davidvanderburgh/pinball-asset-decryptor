"""The Fonts window ("Fonts — Preview & Import") as a floating window.

Ported from ``gui/font_studio.py`` (``FontStudioWindow``): see a Spike 2
game font rendered live, fit a desktop font (TTF/OTF) into it, recolour,
blank, revert and undo, with the scene scope an edit lands in.  Opened from
the Images tab (Fonts…), from the Scenes window's font rows, and through the
window attribute ``open_font_studio`` the text tab exports.

Store/call namespace ``text_fonts``; the page component is ``FontsWindow``
in ``static/js/tabs/text_fonts.js``.  Every decision is the Tk window's,
made by the same ``plugins.stern.fontrender`` / ``scene_render`` calls; only
the drawing moved (the preview is a PNG the page shows through ``/media``).
"""

import logging
import os
import shutil
import tempfile

from . import compat
from .rpc import rpc

log = logging.getLogger(__name__)

_PREVIEW_DEFAULT = "THE QUICK BROWN FOX 0123456789"
_COMP_CLEAR = "Remove it (my outline instead)"
_COMP_KEEP = "Leave it as it is"
_UNDO_STEPS = 5
_UNDO_BYTES = 64 * 1024 * 1024
_SHOW_CURRENT = "Current glyphs"
_SHOW_IMPORTED = "Imported (preview)"

TIPS = {
    "scenes": "The scene files whose atlases hold this font — the same "
              "8-character scene shorthand the Images tab's scene groups "
              "use.\n\nEvery scene carries its own copy, so \"only the "
              "scenes I select\" leaves the rest on the stock font. One "
              "font can still only look ONE way: the selection decides "
              "where your import lands, not a different import per scene."
              "\n\nRight-click a scene to go and look at it in the Scenes "
              "window (clicking it here only changes the scope).",
    "text": "Type anything — \\n starts a new line.",
    "behind": "What the letters are shown against. The machine draws on "
              "black; a lighter backdrop (or the checkerboard) is how you "
              "see a black outline, a shadow, or exactly where a letter's "
              "box ends.",
    "color": "Ink color for these letters. Starts on the color sampled "
             "from the game font, so a swap keeps its look — click to "
             "choose your own.\n\nWith a font file imported it colors the "
             "new letters; on its own it repaints the letters already "
             "there, which you then Apply like any other edit.\n\n"
             "Remember the SCENE multiplies this: a font a scene draws "
             "black stays black whatever you pick here. The line under "
             "these controls says which colors this font is drawn in.",
    "stroke": "Outline drawn around each imported letter, in pixels. "
              "Set it to 0 for no outline at all — there is no "
              "\"transparent\" colour to pick, the width is the switch.",
    "scale": "Shrinks the whole letter, height included. Use it to pull "
             "back from a fit that looks too heavy; use Letter width if "
             "you only want the letters to stop touching.",
    "width": "Draws each letter narrower inside the same slot, which is "
             "what puts a gap between neighbours. The letters keep their "
             "HEIGHT — the spacing itself is fixed on the card and an "
             "import can't change it.",
    "comp": "The game draws this outline font in black behind the letters. "
            "Removing it lets your own Outline setting shape the border; "
            "keeping it leaves the ORIGINAL typeface's outline around your "
            "new letters. Either way \"Revert font\" puts it back.",
    "all_sizes": "Apply, Blank font and Revert font all land on every copy "
                 "of this typeface, not just the row selected on the left — "
                 "an import is re-fitted to each copy's own slots.\n\nA "
                 "typeface is baked once per size AND once per scene, so it "
                 "fills several rows here that can look identical. Leave "
                 "this off to change only the selected row.",
    "apply": "Writes the imported letters over this font's glyph PNGs in "
             "the project folder. Build on the Write tab to put them on "
             "the card; Revert font undoes them.",
    "undo": "Steps back through the last few font writes made in this "
            "window — including \"Revert all fonts\". Different from "
            "\"Revert font\", which goes all the way back to the stock "
            "letters.",
    "blank": "Erases every letter of this font so it draws nothing — the "
             "way to drop an outline or shadow font you don't want. The "
             "scene still draws it, it just has nothing to draw.\n\n"
             "It follows the scene choice on the left, so you can blank it "
             "in one scene and leave the rest alone. \"Revert font\" puts "
             "the letters back.",
    "revert": "Restores every letter of this font from its atlas image — "
              "undoes imports and hand edits of the glyph PNGs.",
    "revert_all": "Puts EVERY font in this project back to stock — the way "
                  "to start a restyle over without re-extracting the card.",
}


def scene_label(card_path):
    """The scene's hash dir, 8 characters (the Images tab's shorthand)."""
    parts = card_path.replace("\\", "/").rstrip("/").split("/")
    if len(parts) >= 2:
        return parts[-2][:8]
    return card_path


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(int(c) for c in tuple(rgb)[:3])


def _rgb(hex_color):
    s = (hex_color or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


class TextFontsService:
    ns = "text_fonts"

    def __init__(self, tab):
        self.tab = tab
        self.window = tab.window
        self.ctx = tab.ctx
        self.store = tab.ctx.store
        self.assets_dir = ""
        self._alive = False
        self._fonts = []
        self._by_key = {}
        self._pending = {}       # font key -> (slices, size, kept, ttf_path)
        self._ttf_paths = {}
        self._scene_paths = []
        self._scope_sel = []     # selected scene-list indices ("some" mode)
        self._scope_mode = "all"
        self._companions = {}
        self._loose_outlines = {}
        self._scene_counts = {}
        self._copy_of = {}
        self._undo = []
        self._undo_dir = ""
        self._tints = None
        self._color = (255, 255, 255)
        self._stroke_color = (0, 0, 0)
        self._opts = self._default_opts()
        self._sel = None
        self._search = ""
        self._render_job = None
        self._tmp = None
        self._seq = 0
        self._raise_n = 0
        self._reset_state()

    # ------------------------------------------------------------------
    def set(self, **kw):
        return self.store.set(self.ns, **kw)

    @staticmethod
    def _default_opts():
        try:
            from ..plugins.stern import scene_render
            bg = scene_render.BACKGROUND_NAMES[0]
        except Exception:                            # noqa: BLE001
            bg = "Black"
        return {"text": _PREVIEW_DEFAULT, "zoom": "1x", "show": _SHOW_CURRENT,
                "bg": bg, "auto_color": True, "stroke": 0, "scale": 100,
                "width": 100, "comp": _COMP_CLEAR, "all_sizes": True}

    @staticmethod
    def _bg_names():
        try:
            from ..plugins.stern import scene_render
            return list(scene_render.BACKGROUND_NAMES)
        except Exception:                            # noqa: BLE001
            return ["Black"]

    def _reset_state(self):
        self.set(open=False, alive=False, hint="", search="", fonts=[],
                 sel=None,
                 scenes=[], scope="all", scope_sel=[], scope_lbl="",
                 preview="", preview_bg="#101014", status="",
                 ttf_label="no file chosen", color=_hex(self._color),
                 stroke_color=_hex(self._stroke_color), opts=self._opts,
                 show_options=[_SHOW_CURRENT], bgs=self._bg_names(),
                 tint="", tint_warn=False, comp_text="", comp_warn=False,
                 comp_ctrl=False, comp_options=[_COMP_CLEAR, _COMP_KEEP],
                 all_sizes_label="", can_apply=False, undo_label="Undo",
                 can_undo=False, busy=False, tips=TIPS)

    def is_open(self):
        return self._alive

    def has_pending(self):
        """An import was fitted but never applied (it is only in memory)."""
        return bool(self._alive and self._pending)

    # ------------------------------------------------------------------
    # opening / closing
    # ------------------------------------------------------------------
    def open(self, assets, preselect=None, preselect_rel=None):
        """Tk ``_open_font_studio`` + ``open_font_studio``: optionally on the
        font owning the glyph slice at Images-tab row *preselect_rel*."""
        if preselect is None and preselect_rel:
            rel = preselect_rel.replace("\\", "/")
            if rel.startswith("images/"):
                rel = rel[len("images/"):]
            from ..plugins.stern import fontrender
            try:
                for fo in fontrender.load_fonts(assets):
                    if any(g["rel"] == rel for g in fo["glyphs"].values()):
                        preselect = fo["key"]
                        break
            except Exception:                        # noqa: BLE001
                pass
        if self._alive:
            if self.assets_dir != assets:
                self.assets_dir = assets
                self.reload(preselect)
            elif preselect:
                self.reload(preselect)
        else:
            self._alive = True
            self.assets_dir = assets
            self._search = ""
            self._reset_state()
            self.reload(preselect)
        # Tk: deiconify + lift.  An open Scenes window stays open under this
        # one and is there again when this one closes.
        self._raise()
        return True

    def _raise(self):
        self._raise_n += 1
        self.set(open=True, alive=True, raise_n=self._raise_n)

    @rpc
    def show(self):
        """Bring a stepped-aside window back, in front."""
        if not self._alive:
            return False
        self._raise()
        return True

    @rpc
    def hide(self):
        """Step aside (nothing is closed; an unapplied import is kept)."""
        if self._alive:
            self.set(open=False)
        return True

    @rpc
    def close(self, force=False):
        """Close; an import that was fitted but never applied is asked about
        first (it is NOT in the project folder)."""
        if self._pending and not force:
            names = ", ".join(
                sorted((self._by_key.get(k, {}).get("name") or k)
                       for k in self._pending)[:4])
            if not compat.messagebox.askyesno(
                    "Unapplied import",
                    "%d font(s) have an import that was never applied (%s%s)."
                    "\n\nThose letters are NOT in the project folder and will "
                    "not reach the card. Close anyway?"
                    % (len(self._pending), names,
                       ", …" if len(self._pending) > 4 else "")):
                return False
        self._alive = False
        self._pending = {}
        self._cancel_render()
        self._drop_tmp()
        self._reset_state()
        return True

    def _tmpdir(self):
        if self._tmp is None or not os.path.isdir(self._tmp):
            self._tmp = tempfile.mkdtemp(prefix="pad-fonts-")
        return self._tmp

    def _drop_tmp(self):
        tmp, self._tmp = self._tmp, None
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # data
    # ------------------------------------------------------------------
    def reload(self, preselect=None):
        from ..plugins.stern import fontrender as fr
        self._tints = None
        if self._undo_dir != self.assets_dir:
            # History holds absolute paths in the OLD project.
            self._undo = []
            self._undo_dir = self.assets_dir
            self._sync_undo()
        try:
            self._fonts = fr.load_fonts(self.assets_dir)
        except Exception:                            # noqa: BLE001
            self._fonts = []
        self._by_key = {fo["key"]: fo for fo in self._fonts}
        try:
            self._companions = fr.outline_companions(self.assets_dir,
                                                     self._fonts)
        except Exception:                            # noqa: BLE001
            self._companions = {}
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
            except Exception:                        # noqa: BLE001
                self._scene_counts[fo["key"]] = 0
        self._copy_of = {}
        runs, totals = {}, {}
        for fo in self._fonts:
            k = ((fo["name"] or "").strip().lower(), fo["px"])
            totals[k] = totals.get(k, 0) + 1
        for fo in self._fonts:
            k = ((fo["name"] or "").strip().lower(), fo["px"])
            if totals[k] > 1:
                runs[k] = runs.get(k, 0) + 1
                self._copy_of[fo["key"]] = (runs[k], totals[k])
        if not self._fonts:
            msg = ("No game fonts found in this project folder. Run "
                   "Extract (with Images enabled) on a Stern Spike 2 card "
                   "image first — every font then shows up here.")
        else:
            n_old = sum(1 for fo in self._fonts if not fo["has_metrics"])
            msg = ("%d game font(s) in %s." %
                   (len(self._fonts), self.assets_dir))
            n_copies = len(self._copy_of) - len(
                {(fo["name"] or "").strip().lower() + "|%d" % fo["px"]
                 for fo in self._fonts if fo["key"] in self._copy_of})
            if n_copies:
                msg += (" %d of them are further copies of a font already "
                        "listed (marked \"copy 2 of 3\" and so on): a "
                        "typeface is baked once per size AND once per scene, "
                        "so \"the font\" is usually several rows here. The "
                        "tick by the buttons changes them all at once."
                        % n_copies)
            if n_old:
                msg += (" This extract predates exact font metrics — "
                        "previews use approximate spacing. Re-extract to "
                        "get exact layout.")
        self.set(hint=msg)
        self._refresh_font_list(preselect)

    def reload_if_open(self):
        """Keep an open Fonts window in step with a blank done elsewhere."""
        if self._alive:
            self.reload(self._sel)

    def _refresh_font_list(self, preselect=None):
        from ..plugins.stern import fontrender as fr
        q = (self._search or "").strip().lower()
        rows = []
        for fo in self._fonts:
            label = "%s" % (fo["name"] or fo["key"])
            if q and q not in label.lower() and q not in fo["key"].lower():
                continue
            marks = []
            if fo["key"] in self._pending:
                marks.append("NOT APPLIED")
            if fo["px"] < fr.MIN_RESTYLE_PX:
                marks.append("tiny")
            if self._companions.get(fo["key"]) is not None:
                marks.append("+outline")
            nth = self._copy_of.get(fo["key"])
            if nth:
                marks.append("copy %d of %d" % nth)
            size = "%dpx%s" % (fo["px"],
                               (" · " + " ".join(marks)) if marks else "")
            rows.append({"key": fo["key"], "label": label, "size": size,
                         "chars": len(fo["glyphs"]),
                         "scenes": self._scene_counts.get(fo["key"], 0),
                         "pending": fo["key"] in self._pending})
        keys = [r["key"] for r in rows]
        want = preselect if preselect in keys else (keys[0] if keys else None)
        self.set(fonts=rows, search=self._search)
        self._sel = want
        self._on_select()

    def _current_font(self):
        return self._by_key.get(self._sel) if self._sel else None

    @rpc
    def set_search(self, q):
        self._search = q or ""
        self._refresh_font_list(self._sel)
        return True

    @rpc
    def select(self, key):
        if key not in self._by_key:
            return False
        self._sel = key
        self._on_select()
        return True

    def _on_select(self):
        from ..plugins.stern import fontrender as fr
        fo = self._current_font()
        self._scene_paths = []
        ttf_label = "no file chosen"
        if fo is not None:
            try:
                self._scene_paths = list(fr.scenes_for_font(self.assets_dir,
                                                            fo))
            except Exception:                        # noqa: BLE001
                pass
            self._load_scope(fo)
            if self._opts["auto_color"]:
                try:
                    self._color = fr.font_color(fo)
                except Exception:                    # noqa: BLE001
                    self._color = (255, 255, 255)
            ttf = self._ttf_paths.get(fo["key"])
            if ttf:
                ttf_label = os.path.basename(ttf)
        self.set(sel=self._sel,
                 scenes=[{"card": p, "label": " %s — %s" % (scene_label(p),
                                                            p)}
                         for p in self._scene_paths],
                 ttf_label=ttf_label, color=_hex(self._color))
        self._sync_companion(fo)
        self._sync_tint(fo)
        self._sync_all_sizes(fo)
        self._sync_show_combo()
        self._schedule_render()

    # -- what the scenes do to this font's colour ------------------------
    def _tints_for(self, font):
        from ..plugins.stern import scene_render
        if self._tints is None:
            try:
                self._tints = scene_render.text_tints(
                    scene_render.load_layouts(self.assets_dir))
            except Exception:                        # noqa: BLE001
                self._tints = {}
        per = self._tints.get(font["key"]) if font else None
        return sorted((per or {}).items(), key=lambda kv: -kv[1])

    def _sync_tint(self, font):
        if font is None:
            self.set(tint="", tint_warn=False)
            return
        tints = self._tints_for(font)
        if not tints:
            self.set(tint="", tint_warn=False)
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
            warn = False
        else:
            msg = ("The scenes tint this font: %s. That colour MULTIPLIES the "
                   "ink you import, so your colour only comes out as picked "
                   "where the scene is white%s. To colour a line itself, "
                   "right-click it in the Scenes window."
                   % (listed,
                      " — and not at all on the %d line(s) tinted black"
                      % black if black else ""))
            warn = bool(black)
        self.set(tint=msg, tint_warn=warn)

    # -- outline companion ------------------------------------------------
    def _companion(self, font):
        return self._companions.get(font["key"]) if font else None

    def _sync_companion(self, font):
        from ..plugins.stern import fontrender as fr
        if font is None:
            self.set(comp_text="", comp_warn=False, comp_ctrl=False)
            return
        comp = self._companion(font)
        if comp is not None:
            self.set(comp_text="The game draws \"%s\" (%dpx) in black behind "
                               "these letters. Restyle this font alone and "
                               "that original outline stays around your new "
                               "letters." % (comp["name"] or comp["key"],
                                             comp["px"]),
                     comp_warn=True, comp_ctrl=True)
            return
        base = fr.outline_base(font.get("name"))
        if base:
            self.set(comp_text="This IS an outline font — the game draws it "
                               "in black behind \"%s\" and puts that font's "
                               "letters on top. Restyle \"%s\" instead unless "
                               "you mean to change the border itself."
                               % (base, base),
                     comp_warn=False, comp_ctrl=False)
            return
        loose = self._loose_outlines.get((font.get("name") or "").strip())
        if loose:
            self.set(comp_text="This typeface also has outline font(s) here "
                               "(%s) that draw a black border behind it, but "
                               "none matches this size — restyle or blank "
                               "them from their own row if you see a "
                               "leftover border."
                               % ", ".join("%s %dpx" % (f["name"], f["px"])
                                           for f in loose[:3]),
                     comp_warn=False, comp_ctrl=False)
            return
        self.set(comp_text="", comp_warn=False, comp_ctrl=False)

    # -- scope ------------------------------------------------------------
    def _load_scope(self, font):
        from ..plugins.stern import fontrender as fr
        try:
            cards = fr.get_font_scope(self.assets_dir, font)
        except Exception:                            # noqa: BLE001
            cards = None
        self._scope_sel = []
        if cards:
            self._scope_mode = "some"
            chosen = set(cards)
            self._scope_sel = [i for i, p in enumerate(self._scene_paths)
                               if p in chosen]
        else:
            self._scope_mode = "all"
        self._sync_scope_ui()

    def _sync_scope_ui(self):
        some = self._scope_mode == "some"
        total = len(self._scene_paths)
        if not some:
            lbl = ("An import or glyph edit is written to %s."
                   % ("the 1 scene using this font" if total == 1
                      else "all %d scenes using this font" % total))
        else:
            n = len(self._scope_sel)
            if n:
                lbl = ("Only %d of %d scenes get this font; the rest keep the "
                       "stock one." % (n, total))
            else:
                lbl = ("Pick one or more scenes above — with none selected "
                       "nothing would be written.")
        self.set(scope=self._scope_mode, scope_sel=list(self._scope_sel),
                 scope_lbl=lbl)

    @rpc
    def set_scope_mode(self, mode):
        fo = self._current_font()
        if fo is None or mode not in ("all", "some"):
            return False
        self._scope_mode = mode
        if mode == "some" and not self._scope_sel and self._scene_paths:
            self._scope_sel = [0]                 # a usable starting point
        self._sync_scope_ui()
        self._save_scope()
        return True

    @rpc
    def set_scope_sel(self, indices):
        if self._scope_mode != "some":
            return False
        self._scope_sel = sorted({int(i) for i in (indices or [])
                                  if 0 <= int(i) < len(self._scene_paths)})
        self._sync_scope_ui()
        self._save_scope()
        return True

    def _save_scope(self):
        """Persist the scope to the project folder (read at Build)."""
        fo = self._current_font()
        if fo is None:
            return
        from ..plugins.stern import fontrender as fr
        cards = ([self._scene_paths[i] for i in self._scope_sel
                  if i < len(self._scene_paths)]
                 if self._scope_mode == "some" else None)
        try:
            fr.set_font_scope(self.assets_dir, fo, cards)
        except OSError as e:
            self.set(status="Could not save the scene scope: %s" % e)

    @rpc
    def show_scene(self, index):
        """Right-click a scene → Show "…" in Scenes…"""
        try:
            card = self._scene_paths[int(index)]
        except (TypeError, ValueError, IndexError):
            return False
        # Tk ``_show_scene``: the Scenes window opens in front; this one
        # stays open behind it.
        return self.tab.scenes.open(
            self.assets_dir,
            preselect_dir=card.replace("\\", "/").rsplit("/", 1)[0])

    # -- options -----------------------------------------------------------
    def _custom_color(self):
        return not self._opts["auto_color"]

    def _sync_show_combo(self):
        fo = self._current_font()
        has_pending = fo is not None and fo["key"] in self._pending
        vals = ([_SHOW_CURRENT, _SHOW_IMPORTED] if has_pending
                else [_SHOW_CURRENT])
        if not has_pending:
            self._opts["show"] = _SHOW_CURRENT
        self.set(show_options=vals, opts=dict(self._opts),
                 can_apply=bool(has_pending or (fo is not None
                                                and self._custom_color())))

    @rpc
    def set_opt(self, key, value):
        """A preview / import option changed (Tk: the option row's vars)."""
        if key not in self._opts:
            return False
        if key in ("stroke",):
            try:
                value = max(0, min(6, int(value)))
            except (TypeError, ValueError):
                value = 0
        elif key == "scale":
            value = _clamp_int(value, 50, 100, 100)
        elif key == "width":
            value = _clamp_int(value, 60, 100, 100)
        elif key in ("auto_color", "all_sizes"):
            value = bool(value)
        self._opts[key] = value
        self.set(opts=dict(self._opts))
        if key in ("text", "zoom", "show", "bg"):
            self._schedule_render()
        elif key in ("auto_color", "stroke", "scale", "width"):
            self._on_option_change()
        return True

    @rpc
    def set_color(self, hex_color):
        rgb = _rgb(hex_color)
        if rgb is None:
            return False
        self._color = rgb
        self._opts["auto_color"] = False
        self.set(color=_hex(rgb), opts=dict(self._opts))
        self._on_option_change()
        return True

    @rpc
    def set_stroke_color(self, hex_color):
        rgb = _rgb(hex_color)
        if rgb is None:
            return False
        self._stroke_color = rgb
        self.set(stroke_color=_hex(rgb))
        self._on_option_change()
        return True

    def _on_option_change(self):
        fo = self._current_font()
        if fo is None:
            return
        if self._opts["auto_color"]:
            from ..plugins.stern import fontrender as fr
            try:
                self._color = fr.font_color(fo)
            except Exception:                        # noqa: BLE001
                pass
            self.set(color=_hex(self._color))
        if fo["key"] in self._ttf_paths:
            self._rasterize()
        else:
            self._sync_show_combo()
            self._schedule_render()

    def _import_options(self):
        return {"color": self._color,
                "stroke": max(0, int(self._opts["stroke"] or 0)),
                "stroke_color": self._stroke_color,
                "size_scale": max(50, min(100, int(self._opts["scale"]
                                                   or 100))) / 100.0,
                "width_scale": max(60, min(100, int(self._opts["width"]
                                                    or 100))) / 100.0}

    @rpc
    def pick_ttf(self):
        """Import font file…"""
        fo = self._current_font()
        if fo is None:
            return False
        path = self.window.ask_open(
            "font_file", "Choose a font file",
            [("Fonts", "*.ttf *.otf *.ttc"), ("All files", "*.*")])
        if not path:
            return False
        self._ttf_paths[fo["key"]] = path
        self.set(ttf_label=os.path.basename(path))
        self._rasterize()
        return True

    def _rasterize(self):
        fo = self._current_font()
        if fo is None:
            return
        ttf = self._ttf_paths.get(fo["key"])
        if not ttf:
            return
        from ..plugins.stern import fontrender as fr
        self.set(busy=True)
        try:
            slices, size, kept = fr.rasterize_ttf(fo, ttf,
                                                  **self._import_options())
        except fr.FontError as e:
            compat.messagebox.showerror("Import failed", str(e))
            return
        except Exception as e:                       # noqa: BLE001
            compat.messagebox.showerror("Import failed",
                                        "Couldn't fit this font:\n\n%s" % e)
            return
        finally:
            self.set(busy=False)
        self._pending[fo["key"]] = (slices, size, kept, ttf)
        self._opts["show"] = _SHOW_IMPORTED
        self._sync_show_combo()
        self._refresh_marks()
        self._schedule_render()

    def _refresh_marks(self):
        """The list's "NOT APPLIED" marks follow the pending imports."""
        self._refresh_font_list(self._sel)

    # -- preview -----------------------------------------------------------
    def _cancel_render(self):
        job, self._render_job = self._render_job, None
        if job is not None:
            try:
                self.ctx.loop.after_cancel(job)
            except Exception:                        # noqa: BLE001
                pass

    def _schedule_render(self):
        self._cancel_render()
        self._render_job = self.ctx.loop.after(120, self._render_now)

    def _render_now(self):
        self._render_job = None
        if not self._alive:
            return
        fo = self._current_font()
        if fo is None:
            self.set(preview="")
            return
        from ..plugins.stern import fontrender as fr
        from ..plugins.stern import scene_render
        text = (self._opts["text"] or "").replace("\\n", "\n") or " "
        loader = None
        pend = self._pending.get(fo["key"])
        recolored = False
        if pend and self._opts["show"] != _SHOW_CURRENT:
            slices = pend[0]
            loader = (lambda g: fr.load_slice(g, slices.get(g["char"])))
        elif self._custom_color():
            recolored = True
            rgb = self._color
            loader = (lambda g: fr.tint_slice(fr.load_slice(g), rgb))
        try:
            img, missing = fr.render_text(fo, text, slice_loader=loader)
        except fr.FontError as e:
            self.set(status=str(e))
            return
        except Exception as e:                       # noqa: BLE001
            self.set(status="Preview failed: %s" % e)
            return
        zoom = int((self._opts["zoom"] or "1x")[0])
        if zoom > 1:
            from PIL import Image
            img = img.resize((img.size[0] * zoom, img.size[1] * zoom),
                             Image.NEAREST)
        bg = self._opts["bg"]
        try:
            img = scene_render.flatten_over_background(img, bg)
        except Exception:                            # noqa: BLE001
            pass
        self._seq += 1
        path = os.path.join(self._tmpdir(), "f%d.png" % self._seq)
        try:
            img.save(path)
        except Exception as e:                       # noqa: BLE001
            self.set(status="Preview failed: %s" % e)
            return
        old = self.store.get(self.ns, "preview")
        spec = scene_render.background_spec(bg)
        bits = []
        if recolored:
            bits.append("showing this font's letters in %s — \"Apply to this "
                        "font\" repaints all %d of them"
                        % (_hex(self._color), len(fo["glyphs"])))
        if pend:
            bits.append("import fitted at %dpx (%d letters redrawn%s)"
                        % (pend[1], len(pend[0]),
                           ", %d kept" % len(pend[2]) if pend[2] else ""))
        if missing:
            bits.append("not in this font: %s"
                        % " ".join(sorted(missing)[:20]))
        if not fo["has_metrics"]:
            bits.append("approximate spacing — re-extract for exact layout")
        self.set(preview=path, preview_w=img.size[0], preview_h=img.size[1],
                 preview_bg=(_hex(spec) if isinstance(spec, tuple)
                             else "#96969c"),
                 status="; ".join(bits))
        if old and old != path:
            try:
                os.remove(old)
            except OSError:
                pass

    # -- undo -------------------------------------------------------------
    def _push_undo(self, label, fonts):
        from ..plugins.stern import fontrender as fr
        seen, uniq = set(), []
        for fo in fonts:
            if fo is not None and fo["key"] not in seen:
                seen.add(fo["key"])
                uniq.append(fo)
        if not uniq:
            return
        noisy = len(uniq) > 8

        def tick(done, total):
            if noisy and done % 10 == 0:
                self.set(status="Saving undo state… %d of %d font(s)"
                         % (done + 1, total))
        try:
            snap = fr.snapshot_fonts(uniq, progress=tick if noisy else None)
        except Exception:                            # noqa: BLE001
            return
        self._undo.append((label, snap))
        while len(self._undo) > _UNDO_STEPS or (
                len(self._undo) > 1
                and sum(fr.snapshot_bytes(s) for _l, s in self._undo)
                > _UNDO_BYTES):
            self._undo.pop(0)
        self._sync_undo()

    def _sync_undo(self):
        self.set(can_undo=bool(self._undo),
                 undo_label=("Undo %s" % self._undo[-1][0]) if self._undo
                 else "Undo")

    @rpc
    def undo(self):
        if not self._undo:
            return False
        from ..plugins.stern import fontrender as fr
        label, snap = self._undo.pop()
        self.set(busy=True)
        try:
            n = fr.restore_snapshot(snap)
        finally:
            self.set(busy=False)
        self._pending.clear()
        self._sync_undo()
        self._sync_show_combo()
        self._refresh_font_list(self._sel)
        self._notify_changed()
        self.set(status="Undid %s — %d letter file(s) put back." % (label, n))
        return True

    def _same_typeface(self, font):
        name = (font.get("name") or "").strip()
        if not name:
            return []
        return [f for f in self._fonts
                if f["key"] != font["key"]
                and (f.get("name") or "").strip() == name]

    def _reach(self, font):
        if font is None:
            return []
        return self._same_typeface(font) if self._opts["all_sizes"] else []

    def _sync_all_sizes(self, font):
        sibs = self._same_typeface(font) if font is not None else []
        if not sibs:
            self.set(all_sizes_label="")
            return
        same = sum(1 for f in sibs if f["px"] == font["px"])
        if same == len(sibs):
            what = "same size, other scenes"
        elif same:
            what = "other sizes and other scenes"
        else:
            what = "its other sizes"
        self.set(all_sizes_label="Also change the other %d cop%s of \"%s\" "
                                 "(%s)" % (len(sibs),
                                           "y" if len(sibs) == 1 else "ies",
                                           font.get("name") or font["key"],
                                           what))

    # -- actions -----------------------------------------------------------
    @rpc
    def apply(self):
        """Apply to this font: an import, or (no import) a recolour."""
        fo = self._current_font()
        if fo is None:
            return False
        from ..plugins.stern import fontrender as fr
        pend = self._pending.get(fo["key"])
        recolor = pend is None
        if recolor:
            if not self._custom_color():
                return False
            try:
                self.set(busy=True)
                pend = (fr.recolor_slices(fo, self._color), fo["px"], [],
                        None)
            except Exception as e:                   # noqa: BLE001
                compat.messagebox.showerror(
                    "Recolour failed",
                    "Couldn't repaint these letters:\n\n%s" % e)
                return False
            finally:
                self.set(busy=False)
            self._pending[fo["key"]] = pend
        if not recolor and fo["px"] < fr.MIN_RESTYLE_PX and \
                not compat.messagebox.askyesno(
                    "Small font",
                    "\"%s\" is only %d pixels tall. Below about %d a desktop "
                    "font loses its shape when it is fitted into letters this "
                    "small, and the result usually looks worse than the "
                    "original.\n\nImport into it anyway?"
                    % (fo["name"] or fo["key"], fo["px"],
                       fr.MIN_RESTYLE_PX)):
            return False
        sibs = self._reach(fo)
        self._push_undo(
            "the %s \"%s\"" % ("recolour of" if recolor else "import into",
                               fo["name"] or fo["key"]),
            [fo, self._companion(fo)] + sibs
            + [self._companion(s) for s in sibs])
        restyled = [fo] + sibs
        n, n_comp = self._write_font(fo, pend[0], bodies=restyled)
        comp = self._companion(fo)
        del self._pending[fo["key"]]
        n_sib = n_failed = 0
        errors = []
        if sibs:
            ttf = pend[3]
            self.set(busy=True)
            try:
                for i, sib in enumerate(sibs):
                    self.set(status="%s copy %d of %d…"
                             % ("Repainting" if recolor else
                                "Fitting \"%s\" into"
                                % os.path.basename(ttf),
                                i + 1, len(sibs)))
                    try:
                        if recolor:
                            slices = fr.recolor_slices(sib, self._color)
                        else:
                            slices, _sz, _kept = fr.rasterize_ttf(
                                sib, ttf, **self._import_options())
                    except Exception:                # noqa: BLE001
                        n_failed += 1
                        continue
                    self._write_font(sib, slices, errors, bodies=restyled)
                    self._pending.pop(sib["key"], None)
                    n_sib += 1
            finally:
                self.set(busy=False)
            if errors:
                compat.messagebox.showwarning(
                    "Outline fonts",
                    "The letters were written, but %d outline font(s) could "
                    "not be removed:\n\n%s" % (len(errors),
                                               "\n".join(errors[:6])))
        self._opts["show"] = _SHOW_CURRENT
        self._sync_show_combo()
        self._refresh_font_list(fo["key"])
        self._notify_changed()
        if self._scope_mode == "some":
            where = "%d selected scene(s)" % len(self._scope_sel)
        else:
            where = "all %d scene(s) using this font" % len(self._scene_paths)
        msg = ("%d letter(s) %s in the project folder, for %s"
               % (n, "repainted %s" % _hex(self._color)
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
            msg += ("; %d more cop%s of \"%s\" %s too"
                    % (n_sib, "y" if n_sib == 1 else "ies",
                       fo["name"] or fo["key"],
                       "were repainted" if recolor else "took the same font"))
            if self._scope_mode == "some":
                msg += (" (those keep their own scene choice, which is every "
                        "scene unless you narrow them)")
        if n_failed:
            msg += ("; %d cop%s could not take this font and %s left "
                    "alone" % (n_failed, "y" if n_failed == 1 else "ies",
                               "was" if n_failed == 1 else "were"))
        self.set(status=msg + " — build on the Write tab to put them on the "
                              "card.")
        return True

    def _scope_companion(self, bodies, comp):
        """Limit the companion's blanking to the scenes *bodies* are in."""
        from ..plugins.stern import fontrender as fr
        try:
            mine = set()
            for b in bodies:
                mine |= set(fr.scenes_for_font(self.assets_dir, b))
            theirs = set(fr.scenes_for_font(self.assets_dir, comp))
        except Exception:                            # noqa: BLE001
            return 0
        both = sorted(mine & theirs)
        if not both:
            return 0
        try:
            fr.set_font_scope(self.assets_dir, comp, both)
        except Exception:                            # noqa: BLE001
            return 0
        return len(both)

    def _write_font(self, font, slices, errors=None, bodies=None):
        from ..plugins.stern import fontrender as fr
        n = fr.save_slices(font, slices)
        comp = self._companion(font)
        n_comp = 0
        if comp is not None and self._opts["comp"] == _COMP_CLEAR:
            try:
                self._scope_companion(bodies or [font], comp)
                n_comp = fr.clear_font(comp)
            except Exception as e:                   # noqa: BLE001
                if errors is None:
                    compat.messagebox.showwarning(
                        "Outline font",
                        "The letters were written, but its outline font "
                        "\"%s\" could not be removed:\n\n%s"
                        % (comp["name"], e))
                else:
                    errors.append("%s: %s" % (comp["name"] or comp["key"], e))
        return n, n_comp

    @rpc
    def blank(self):
        """Blank font: erase this font's letters (follows the scope and the
        all-copies tick)."""
        fo = self._current_font()
        if fo is None:
            return False
        from ..plugins.stern import fontrender as fr
        some = self._scope_mode == "some"
        n_sel = len(self._scope_sel)
        if some and not n_sel:
            self.set(status="Pick the scenes to blank it in first, or switch "
                            "to \"Change in all of them\".")
            return False
        sibs = self._reach(fo)
        where = ("the %d scene(s) selected on the left" % n_sel if some
                 else "all %d scene(s) using it" % len(self._scene_paths))
        extra = ("" if not sibs else
                 "\n\nThe other %d cop%s of this typeface in the list "
                 "(%d more scene(s)) are blanked too, so no scene is left "
                 "drawing it."
                 % (len(sibs), "y" if len(sibs) == 1 else "ies",
                    self._sibling_scene_count(sibs)))
        if not compat.messagebox.askyesno(
                "Blank font",
                "Erase every letter of \"%s\" (%dpx) so it draws nothing, in "
                "%s?%s\n\nThe scene still draws this font — it just has "
                "nothing to draw, which is how an outline or shadow is "
                "removed. "
                "\"Revert font\" restores Stern's letters, and \"Undo\" steps "
                "back to whatever was there a moment ago."
                % (fo["name"] or fo["key"], fo["px"], where, extra)):
            return False
        self._push_undo("blanking \"%s\"" % (fo["name"] or fo["key"]),
                        [fo] + sibs)
        try:
            n = fr.clear_font(fo)
        except Exception as e:                       # noqa: BLE001
            compat.messagebox.showerror(
                "Blank font", "Couldn't blank this font:\n\n%s" % e)
            return False
        n_sib = 0
        for sib in sibs:
            try:
                n += fr.clear_font(sib)
            except Exception:                        # noqa: BLE001
                continue
            self._pending.pop(sib["key"], None)
            n_sib += 1
        self._pending.pop(fo["key"], None)
        self._sync_show_combo()
        self._refresh_font_list(fo["key"])
        self._notify_changed()
        msg = "%d letter(s) blanked in %s" % (n, where)
        if n_sib:
            msg += ("; %d more cop%s of \"%s\" blanked too, each in its own "
                    "scenes" % (n_sib, "y" if n_sib == 1 else "ies",
                                fo["name"] or fo["key"]))
        self.set(status=msg + " — build on the Write tab to put it on the "
                              "card.")
        return True

    def _sibling_scene_count(self, sibs):
        from ..plugins.stern import fontrender as fr
        seen = set()
        for f in sibs:
            try:
                seen.update(fr.scenes_for_font(self.assets_dir, f))
            except Exception:                        # noqa: BLE001
                continue
        return len(seen)

    @rpc
    def revert(self):
        """Revert font: every letter back from its atlas image (and its
        outline companion, and the other copies while the tick is on)."""
        fo = self._current_font()
        if fo is None:
            return False
        comp = self._companion(fo)
        sibs = self._reach(fo)
        comps = [c for c in ([comp] + [self._companion(s) for s in sibs])
                 if c is not None]
        extra = ("\n\nIts outline font%s (%s) %s restored too, so a border "
                 "this window removed comes back."
                 % ("" if len(comps) == 1 else "s",
                    ", ".join(sorted({c["name"] or c["key"] for c in comps})),
                    "is" if len(comps) == 1 else "are")) if comps else ""
        if sibs:
            extra += ("\n\nThe other %d cop%s of this typeface in the list "
                      "go back to stock as well."
                      % (len(sibs), "y" if len(sibs) == 1 else "ies"))
        if not compat.messagebox.askyesno(
                "Revert font",
                "Restore every letter of \"%s\" from its atlas image?\n\n"
                "This undoes imported and hand-edited glyph PNGs for this "
                "font.%s" % (fo["name"] or fo["key"], extra)):
            return False
        from ..plugins.stern import fontrender as fr
        self._push_undo("reverting \"%s\"" % (fo["name"] or fo["key"]),
                        [fo] + sibs + comps)
        n = fr.revert_slices(self.assets_dir, fo)
        for f in sibs + comps:
            try:
                n += fr.revert_slices(self.assets_dir, f)
            except Exception:                        # noqa: BLE001
                continue
            self._pending.pop(f["key"], None)
        self._pending.pop(fo["key"], None)
        self._sync_show_combo()
        self._refresh_font_list(fo["key"])
        self._notify_changed()
        self.set(status="%d letter(s) restored%s."
                 % (n, (" across all %d copies of \"%s\""
                        % (len(sibs) + 1, fo["name"] or fo["key"]))
                    if sibs else ""))
        return True

    @rpc
    def revert_all(self):
        """Revert all fonts…: every font in the project back to stock."""
        from ..plugins.stern import fontrender as fr
        if not self._fonts:
            return False
        if not compat.messagebox.askyesno(
                "Revert all fonts",
                "Restore all %d fonts in this project from their atlas "
                "images?\n\nThis undoes every font import, glyph edit and "
                "removed outline in this folder — a clean slate to restyle "
                "from. Nothing else in the project is touched.\n\n"
                "\"Undo\" brings it all back if you change your mind."
                % len(self._fonts)):
            return False
        self._push_undo("reverting all fonts", list(self._fonts))
        n = fonts_done = 0
        self.set(busy=True)
        try:
            for i, fo in enumerate(self._fonts):
                if i % 10 == 0:
                    self.set(status="Restoring font %d of %d…"
                             % (i + 1, len(self._fonts)))
                try:
                    n += fr.revert_slices(self.assets_dir, fo)
                    fonts_done += 1
                except Exception:                    # noqa: BLE001
                    continue
        finally:
            self.set(busy=False)
        self._pending.clear()
        self._sync_show_combo()
        self._refresh_font_list(self._sel)
        self._notify_changed()
        self.set(status="%d letter(s) across %d font(s) restored to stock."
                 % (n, fonts_done))
        return True

    def _notify_changed(self):
        """Glyph files changed on disk: the Images tab's change markers and
        an open Scenes window's preview follow."""
        images = self.window.service("images")
        fn = getattr(images, "_start_change_scan", None)
        if fn is not None:
            try:
                fn()
            except Exception:                        # noqa: BLE001
                log.exception("images change scan")
        scenes = getattr(self.tab, "scenes", None)
        if scenes is not None and scenes.is_open():
            scenes.fonts_changed()


def _clamp_int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default
