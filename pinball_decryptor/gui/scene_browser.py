"""Scene Browser — what each Spike 2 scene is made of (Peter).

The extract manifests already record, per on-card ``scene.radium``, every
embedded image (in play order), every font atlas and every editable display
string — but only as flat files an asset at a time.  "Where does this image
come from, what fonts and text does this scene use?" had no answer in the
app.  This window groups all of it by scene: pick a scene on the left, see
its images / fonts / text on the right, and double-click to jump to the
matching row on the Images tab, the Fonts window, or the Replace Text tab.

A true WYSIWYG scene renderer would need the radium node graph (transforms,
z-order, timelines) — not reverse-engineered; this browser is the honest
subset: complete contents + navigation, no layout.

Read-only over the manifests; singleton tool window like Image Info.
"""

import os
import re
import tkinter as tk
from tkinter import ttk

from .theme import THEMES, platform_font
from .widgets import _Tooltip, center_over

_RADIMG_NAME = re.compile(r"^radimg_(.+)_\d+x\d+_[0-9a-f]{8}\.png$",
                          re.IGNORECASE)


def _rows(assets_dir, *parts):
    try:
        with open(os.path.join(assets_dir, *parts), encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if line and not line.startswith("#"):
                    yield line.split("\t")
    except OSError:
        return


def collect_scenes(assets_dir):
    """Group the extract manifests by scene directory.

    Returns ``{scene_dir: scene}`` where scene = ``{"label", "images":
    [(order, rel)], "fonts": {table_key: (name, px)}, "texts": [str]}``.
    Pure text parsing (a few thousand rows), no Tk — unit-tested apart from
    the window."""
    scenes = {}

    def scene_for(d):
        sc = scenes.get(d)
        if sc is None:
            sc = scenes[d] = {"label": "", "hint": "",
                              "images": [], "fonts": {}, "texts": []}
        return sc

    # Radium-embedded images (one row per occurrence): scene = the radium's
    # directory; data offset = play order; first hint names the scene.
    atlas_scenes = {}          # atlas out_rel -> [scene_dir, ...]
    for cols in _rows(assets_dir, "images", "scene_textures",
                      "radium_images.txt"):
        if len(cols) < 3:
            continue
        card = cols[1]
        try:
            off = int(cols[2])
        except ValueError:
            continue
        d = card.rsplit("/", 1)[0]
        sc = scene_for(d)
        rel = "images/" + cols[0]
        if rel not in (r for _o, r in sc["images"]):
            sc["images"].append((off, rel))
        atlas_scenes.setdefault(cols[0], []).append(d)
        if not sc["hint"]:
            m = _RADIMG_NAME.match(os.path.basename(cols[0]))
            if m:
                sc["hint"] = m.group(1)

    # scene.assets textures: scene = the directory holding scene.assets.
    for idx, cols in enumerate(_rows(assets_dir, "images", "scene_textures",
                                     "manifest.txt")):
        if len(cols) < 2:
            continue
        card = cols[1]
        if "/scene.assets/" in card:
            d = card.rsplit("/scene.assets/", 1)[0]
        else:
            d = card.rsplit("/", 1)[0] or card
        sc = scene_for(d)
        rel = "images/" + cols[0]
        if rel not in (r for _o, r in sc["images"]):
            sc["images"].append((10 ** 9 + idx, rel))

    # Fonts: glyph manifest rows name each atlas's font + whole-font table
    # key; the atlas occurrences above say which scenes draw it.
    font_px = {}
    for cols in _rows(assets_dir, "images", "scene_textures",
                      "glyph_images.txt"):
        if len(cols) < 8:
            continue
        atlas, name = cols[1], cols[7]
        stem = cols[0].replace("\\", "/").split("/")[-2]
        table = cols[14] if len(cols) >= 15 and cols[14] else stem
        try:
            px = float(cols[10]) if len(cols) >= 11 else float(cols[6])
        except ValueError:
            px = 0
        font_px[table] = max(font_px.get(table, 0), px)
        for d in atlas_scenes.get(atlas, ()):
            scene_for(d)["fonts"].setdefault(table, name)

    # Editable display text, per radium.
    try:
        from ..core import text_manifest
        for row in text_manifest.load(assets_dir):
            p = (row.get("path") or "").replace("\\", "/")
            if p:
                scene_for(p.rsplit("/", 1)[0])["texts"].append(
                    row.get("original") or "")
    except Exception:
        pass

    for d, sc in scenes.items():
        sc["images"].sort()
        sc["fonts"] = {t: (n, int(font_px.get(t, 0)))
                       for t, n in sc["fonts"].items()}
        base = d.rstrip("/").rsplit("/", 1)[-1][:8] or d
        sc["label"] = ("%s · %s" % (sc["hint"], base)) if sc["hint"] else base
    return scenes


class SceneBrowserWindow:
    """The Scenes tool window.  One per app; ``open_scene_browser`` re-uses
    it."""

    def __init__(self, app, assets_dir, preselect=None):
        self.app = app
        self.assets_dir = assets_dir
        self._scenes = {}
        self._photo = None
        self._sans, _mono = platform_font()
        self._build()
        self.reload(preselect)

    def _theme(self):
        return THEMES.get(getattr(self.app, "_current_theme", "light"),
                          THEMES["light"])

    def _build(self):
        win = tk.Toplevel(self.app.root)
        self.win = win
        win.withdraw()
        win.title("Scenes — what each scene is made of")
        win.transient(self.app.root)
        self.app._theme_toplevel(win)
        win.protocol("WM_DELETE_WINDOW", self._close)
        win.bind("<Escape>", lambda _e: self._close())

        th = self._theme()
        body = ttk.Frame(win, padding=(10, 8))
        body.pack(fill=tk.BOTH, expand=True)
        self._hint = ttk.Label(
            body,
            text="Every scene on the card, with the images, fonts and "
                 "on-screen text it is built from. Double-click an item to "
                 "jump to it on the matching tab.",
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=980, justify=tk.LEFT)
        self._hint.pack(anchor=tk.W, pady=(0, 6))

        panes = ttk.Frame(body)
        panes.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(panes)
        left.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 8))
        srow = ttk.Frame(left)
        srow.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(srow, text="Search:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_a: self._refresh_list())
        ttk.Entry(srow, textvariable=self._search_var, width=18).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        self._tree = ttk.Treeview(
            lf, columns=("imgs", "fonts", "texts"), height=22,
            selectmode="browse")
        self._tree.heading("#0", text="Scene", anchor=tk.W)
        self._tree.heading("imgs", text="Images", anchor=tk.W)
        self._tree.heading("fonts", text="Fonts", anchor=tk.W)
        self._tree.heading("texts", text="Text", anchor=tk.W)
        self._tree.column("#0", width=240, minwidth=140)
        self._tree.column("imgs", width=56, minwidth=44, stretch=False)
        self._tree.column("fonts", width=48, minwidth=40, stretch=False)
        self._tree.column("texts", width=44, minwidth=36, stretch=False)
        sc1 = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sc1.set)
        sc1.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        _Tooltip(self._tree,
                 "Scene names come from the scene's own sprite names plus "
                 "the 8-character scene id — the same shorthand the Images "
                 "tab's \"Group by scene\" and the Replace Text Scene column "
                 "use.",
                 lambda: getattr(self.app, "_current_theme", "light"))

        right = ttk.Frame(panes)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rf = ttk.Frame(right)
        rf.pack(fill=tk.BOTH, expand=True)
        self._detail = ttk.Treeview(rf, columns=("info",), height=18,
                                    selectmode="browse")
        self._detail.heading("#0", text="Contents", anchor=tk.W)
        self._detail.heading("info", text="", anchor=tk.W)
        self._detail.column("#0", width=380, minwidth=200)
        self._detail.column("info", width=180, minwidth=80)
        sc2 = ttk.Scrollbar(rf, orient=tk.VERTICAL,
                            command=self._detail.yview)
        self._detail.configure(yscrollcommand=sc2.set)
        sc2.pack(side=tk.RIGHT, fill=tk.Y)
        self._detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._detail.bind("<<TreeviewSelect>>", lambda _e: self._on_detail())
        self._detail.bind("<Double-1>", self._on_detail_double)

        bottom = ttk.Frame(right)
        bottom.pack(fill=tk.X, pady=(6, 0))
        self._thumb = tk.Canvas(bottom, width=200, height=112,
                                bg="#101014", highlightthickness=1)
        self._thumb.pack(side=tk.LEFT)
        self._detail_lbl = ttk.Label(bottom, text="", font=(self._sans, 9),
                                     foreground=th["gray"], wraplength=480,
                                     justify=tk.LEFT)
        self._detail_lbl.pack(side=tk.LEFT, fill=tk.X, padx=(8, 0))

        brow = ttk.Frame(body)
        brow.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(brow, text="Close", command=self._close).pack(side=tk.RIGHT)

        center_over(self.app.root, win, 1040, 640)
        win.deiconify()
        win.lift()

    def _close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # -- data ------------------------------------------------------------

    def reload(self, preselect=None):
        try:
            self._scenes = collect_scenes(self.assets_dir)
        except Exception:
            self._scenes = {}
        if not self._scenes:
            self._hint.configure(
                text="No scene manifests found in this project folder. Run "
                     "Extract (with Images and Text enabled) on a Stern "
                     "Spike 2 card image first.")
        self._refresh_list(preselect)

    def _refresh_list(self, preselect=None):
        tree = self._tree
        tree.delete(*tree.get_children())
        q = (self._search_var.get() or "").strip().lower()
        for d in sorted(self._scenes,
                        key=lambda d: self._scenes[d]["label"].lower()):
            sc = self._scenes[d]
            hay = (sc["label"] + " " + d + " "
                   + " ".join(n for n, _p in sc["fonts"].values()) + " "
                   + " ".join(sc["texts"])).lower()
            if q and q not in hay:
                continue
            tree.insert("", tk.END, iid=d, text=sc["label"],
                        values=(len(sc["images"]), len(sc["fonts"]),
                                len(sc["texts"])))
        kids = tree.get_children()
        want = preselect if preselect in (kids or ()) else (
            kids[0] if kids else None)
        if want:
            tree.selection_set(want)
            tree.see(want)
        self._on_select()

    def _on_select(self):
        det = self._detail
        det.delete(*det.get_children())
        self._thumb.delete("all")
        self._detail_lbl.configure(text="")
        sel = self._tree.selection()
        if not sel:
            return
        sc = self._scenes.get(sel[0])
        if sc is None:
            return
        self._detail_lbl.configure(text=sel[0])
        n_img = det.insert("", tk.END, text="Images (%d)" % len(sc["images"]),
                           open=True)
        for _off, rel in sc["images"]:
            det.insert(n_img, tk.END, iid="img::" + rel,
                       text=os.path.basename(rel),
                       values=("double-click: show on Images tab",))
        n_f = det.insert("", tk.END, text="Fonts (%d)" % len(sc["fonts"]),
                         open=True)
        for table, (name, px) in sorted(sc["fonts"].items(),
                                        key=lambda kv: kv[1][0].lower()):
            det.insert(n_f, tk.END, iid="font::" + table,
                       text="%s (%dpx)" % (name or table, px),
                       values=("double-click: open in Fonts window",))
        n_t = det.insert("", tk.END, text="Text (%d)" % len(sc["texts"]),
                         open=len(sc["texts"]) <= 12)
        for i, s in enumerate(sc["texts"]):
            det.insert(n_t, tk.END, iid="txt::%d" % i, text=s,
                       values=("double-click: find on Replace Text",))

    def _on_detail(self):
        self._thumb.delete("all")
        sel = self._detail.selection()
        if not sel or not sel[0].startswith("img::"):
            return
        rel = sel[0][5:]
        path = os.path.join(self.assets_dir, *rel.split("/"))
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((200, 112))
            self._photo = ImageTk.PhotoImage(img)
            self._thumb.create_image(100, 56, image=self._photo)
        except Exception:
            pass

    def _on_detail_double(self, _event):
        sel = self._detail.selection()
        if not sel:
            return
        iid = sel[0]
        try:
            if iid.startswith("img::"):
                self.app.reveal_image_slot(iid[5:])
            elif iid.startswith("font::"):
                from .font_studio import open_font_studio
                open_font_studio(self.app, self.assets_dir,
                                 preselect=iid[6:])
            elif iid.startswith("txt::"):
                text = self._detail.item(iid, "text")
                self.app.reveal_text_string(text)
        except Exception:
            pass


def open_scene_browser(app, assets_dir, preselect=None):
    """Open (or re-use and refocus) the app's Scenes window."""
    win = getattr(app, "_scene_browser", None)
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
    win = SceneBrowserWindow(app, assets_dir, preselect=preselect)
    app._scene_browser = win
    return win
