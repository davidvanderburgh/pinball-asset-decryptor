"""Scene Browser — what each Spike 2 scene is made of (a tester).

The extract manifests already record, per on-card ``scene.radium``, every
embedded image (in play order), every font atlas and every editable display
string — but only as flat files an asset at a time.  "Where does this image
come from, what fonts and text does this scene use?" had no answer in the
app.  This window groups all of it by scene: pick a scene on the left, see
its images / fonts / text on the right, and double-click to jump to the
matching row on the Images tab, the Fonts window, or the Replace Text tab.

It also SHOWS the scene: the radium node graph is read to a layout at extract
time (:mod:`plugins.stern.scene_layout`) and composited here from the project
folder's current files, so a replaced image or an imported font appears in the
preview.  "Rebuild previews…" re-reads those layouts off the card alone — a
few seconds against a full re-extract, and it leaves every PNG and glyph slice
untouched, which a re-extract would not.

Read-only over the manifests otherwise; singleton tool window like Image Info.
"""

import os
import re
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from ..core import video
from ..plugins.stern import scene_render, text_colors
from .theme import THEMES, platform_font
from .widgets import _Tooltip, center_over

_RADIMG_NAME = re.compile(r"^radimg_(.+)_\d+x\d+_[0-9a-f]{8}\.png$",
                          re.IGNORECASE)
# A TMNT TV-static loop is ~1900 frames; rendering every one to preview it
# would stall the window and eat memory for a motion you can read in a second.
_MAX_PREVIEW_FRAMES = 60

# Playback speed: the scene's own stage rate by default, with manual rates for
# looking closely at a fast animation (and because a frame's HOLD time is still
# undecoded, so the file rate can run a sequence faster than the machine does).
_FPS_FROM_FILE = "Scene rate"

# The Screen picker's "don't isolate anything" entry: the scene as the layout
# composites it, which is what the preview has always drawn.
_ALL_SCREENS = "All screens"


def _safe_stem(label):
    """A scene label as a filename stem — every non-alphanumeric replaced, so
    the ` · ` separator and the odd punctuation in a scene name can't produce
    a path the OS refuses."""
    return "".join(c if (c.isalnum() or c in "-_") else "_"
                   for c in (label or "scene")) or "scene"


def _unique_png(label, used):
    """``<label>.png``, suffixed when a batch holds two scenes whose labels
    sanitise to the same stem — an overwrite there would silently drop one
    scene from a folder that claims to hold them all.  *used* is the set of
    stems already handed out, and is updated."""
    stem = _safe_stem(label)
    name, n = stem, 2
    while name.lower() in used:
        name, n = "%s_%d" % (stem, n), n + 1
    used.add(name.lower())
    return name + ".png"


# Longest caption line kept on screen; the rest lives on its "?" button.  The
# caption used to wrap to one, two or three lines depending on what a scene had
# to admit, so the pane jumped every time you stepped to another screen.
_CAPTION_CHARS = 96
_FPS_CHOICES = (_FPS_FROM_FILE, "60 fps", "30 fps", "24 fps", "20 fps",
                "15 fps", "12 fps", "8 fps", "4 fps", "2 fps")

# Which scene-list column each heading sorts on, and how to read a row for it.
_SORT_KEYS = {
    "#0": lambda sc: sc["label"].lower(),
    "imgs": lambda sc: len(sc["images"]),
    "fonts": lambda sc: len(sc["fonts"]),
    "texts": lambda sc: len(sc["texts"]),
    "vids": lambda sc: len(sc["videos"]),
}


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
    [(order, rel)], "fonts": {table_key: (name, px)}, "texts": [str],
    "videos": [rel]}``.  Pure text parsing (a few thousand rows), no Tk —
    unit-tested apart from the window."""
    scenes = {}

    def scene_for(d):
        sc = scenes.get(d)
        if sc is None:
            sc = scenes[d] = {"label": "", "hint": "", "images": [],
                              "fonts": {}, "texts": [], "videos": []}
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

    # Videos: the LCD clips a scene plays.  ``video/manifest.txt`` rows are
    # (file name, card path, bytes) and a clip lives under the scene's own
    # scene.assets, so the scene is derivable exactly as it is for textures —
    # no new parsing, and a scene's video is the most visible thing in it.
    for cols in _rows(assets_dir, "video", "manifest.txt"):
        if len(cols) < 2:
            continue
        card = cols[1].replace("\\", "/")
        if "/scene.assets/" in card:
            d = card.rsplit("/scene.assets/", 1)[0]
        else:
            d = card.rsplit("/", 1)[0]
        rel = "video/" + cols[0]
        sc = scene_for(d)
        if rel not in sc["videos"]:
            sc["videos"].append(rel)

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

    # The size a scene draws a font at, straight from its layout.  One atlas is
    # commonly baked at several sizes, so the manifest's card-wide maximum is
    # the size of the BIGGEST scene using that typeface, not this one's — it
    # labelled JAWS' "MODE TITLE / LINE 0..8" screen 140px when it draws at 45.
    scene_font_px = {}
    try:
        from ..plugins.stern import scene_render as _sr
        for card, lay in (_sr.load_layouts(assets_dir) or {}).items():
            d = card.replace("\\", "/").rsplit("/", 1)[0]
            for t in (lay or {}).get("texts") or ():
                if t.get("font") and t.get("font_px"):
                    scene_font_px[(d, t["font"])] = int(t["font_px"])
    except Exception:
        pass

    # The number printed must be the FONT LIST's number for the same font.
    # The layout's size is the radium's NOMINAL size id, while the Fonts
    # window prints fontrender's measured px (ascent + descent) — quoting the
    # nominal here made one font read "83px" in this window and "94px" in
    # that one, and a tester went hunting for a font that was never missing.
    # So the nominal id is translated through the same variants the Fonts
    # window reads, and only picks WHICH size to name, never the label itself.
    size_px, rep_px = {}, {}
    try:
        from ..plugins.stern import fontrender as _fr
        for fo in _fr.load_fonts(assets_dir):
            rep_px[fo["key"]] = fo["px"]
            for sid, v in (fo.get("sizes") or {}).items():
                size_px[(fo["key"], sid)] = v["px"]
    except Exception:
        pass

    def _label_px(d, t):
        sid = scene_font_px.get((d, t))
        if sid is not None and (t, sid) in size_px:
            return size_px[(t, sid)]
        return rep_px.get(t) or font_px.get(t, 0)

    for d, sc in scenes.items():
        sc["images"].sort()
        sc["fonts"] = {t: (n, int(_label_px(d, t)))
                       for t, n in sc["fonts"].items()}
        base = d.rstrip("/").rsplit("/", 1)[-1][:8] or d
        sc["label"] = ("%s · %s" % (sc["hint"], base)) if sc["hint"] else base
    return scenes


class SceneBrowserWindow:
    """The Scenes tool window.  One per app; ``open_scene_browser`` re-uses
    it."""

    def __init__(self, app, assets_dir, preselect=None, focus_text=None):
        self.app = app
        self.assets_dir = assets_dir
        self._suspend_search = False   # guards the search-var trace
        self._focus_want = None        # (scene, line) to pick out on rebuild
        self._scenes = {}
        self._photo = None
        self._layouts = {}         # card path -> static layout (from extract)
        self._fonts = None         # fontrender fonts, parsed once on demand
        self._preview_img = None   # PhotoImage ref (must stay alive)
        self._preview_full = None  # full-size frame 1, for Save preview…
        self._frames_full = []     # every full-size frame (GIF export)
        self._frame_imgs = []      # canvas-sized PhotoImages, one per frame
        self._preview_item = None  # canvas item the animation retargets
        self._play_job = None      # pending after() for the animation
        self._preview_token = 0    # discards superseded renders
        self._sort_col = "#0"      # scene-list sort column / direction
        self._sort_rev = False
        self._rebuild = None       # {"cancel": bool} while a rebuild runs
        self._export = None        # {"cancel": bool} while an MP4 is written
        self._bulk = None          # {"cancel": bool} while every scene saves
        self._sans, _mono = platform_font()
        self._build()
        self.reload(preselect, focus_text)

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
                 "jump to it on the matching tab — this window steps behind "
                 "the main one so you can see where you landed, and the "
                 "Scenes… button brings it back. Right-click an item to "
                 "recolour a line of text or blank a font out of the picture.",
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
        self._search_var.trace_add(
            "write",
            lambda *_a: None if self._suspend_search else self._refresh_list())
        ttk.Entry(srow, textvariable=self._search_var, width=18).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        self._tree = ttk.Treeview(
            lf, columns=("imgs", "fonts", "texts", "vids"), height=22,
            selectmode="browse")
        # Every heading sorts: "which scenes have the most images / any video"
        # is how you find the interesting ones in a list of 300.
        self._headings = (("#0", "Scene"), ("imgs", "Images"),
                          ("fonts", "Fonts"), ("texts", "Text"),
                          ("vids", "Video"))
        for col, title in self._headings:
            self._tree.heading(
                col, text=title, anchor=tk.W,
                command=lambda c=col: self._sort_by(c))
        self._tree.column("#0", width=220, minwidth=140)
        self._tree.column("imgs", width=56, minwidth=44, stretch=False)
        self._tree.column("fonts", width=48, minwidth=40, stretch=False)
        self._tree.column("texts", width=44, minwidth=36, stretch=False)
        self._tree.column("vids", width=46, minwidth=38, stretch=False)
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
        self._detail = ttk.Treeview(rf, columns=("info",), height=13,
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
        # Right-click acts ON the scene — recolour a line of its text, blank a
        # font out of it.  A tester, about an outline font he wanted gone: "Is
        # there an easy way to blank it out from the scene menu? when i do
        # doubleclick on it, it will go the import windows, but it will not
        # blank it out there."
        self._menu = tk.Menu(self._detail, tearoff=0)
        for seq in ("<Button-3>", "<Button-2>"):    # Windows/Linux, macOS
            self._detail.bind(seq, self._popup_menu)

        # ---- preview: the scene as the machine draws it -----------------
        prev = ttk.Frame(right)
        prev.pack(fill=tk.X, pady=(6, 0))
        self._preview = tk.Canvas(prev, width=384, height=217,
                                  bg="#101014", highlightthickness=1)
        self._preview.pack(side=tk.LEFT)
        pside = ttk.Frame(prev)
        pside.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))
        ttk.Label(pside, text="Scene preview", font=(self._sans, 9, "bold")
                  ).pack(anchor=tk.W)
        self._save_btn = ttk.Button(pside, text="Save preview…",
                                    command=self._save_preview,
                                    state="disabled")
        self._save_btn.pack(anchor=tk.W, pady=(4, 0))
        # ONE PICTURE PER SCENE, FOR EVERY SCENE IN THE LIST. "Save preview…"
        # is one scene at a time, and a card carries a few hundred — a tester
        # comparing a modded card against stock: "a bulk Save Preview feature
        # would be very helpful".  Deliberately next to the single save (they
        # are the same job at two sizes), and it honours the Search box, so
        # the batch is whatever the list is showing.
        self._save_all_btn = ttk.Button(pside, text="Save all previews…",
                                        command=self._save_all_previews)
        self._save_all_btn.pack(anchor=tk.W, pady=(4, 0))
        _Tooltip(self._save_all_btn,
                 "Write one PNG per scene into a folder you pick — every "
                 "scene the list is showing, so a Search narrows the batch."
                 "\n\nAn animated scene is saved as its first frame; use "
                 "\"Save preview…\" on that scene for the whole thing as MP4.",
                 lambda: getattr(self.app, "_current_theme", "light"))
        self._rebuild_btn = ttk.Button(pside, text="Rebuild previews…",
                                       command=self._rebuild_previews)
        self._rebuild_btn.pack(anchor=tk.W, pady=(4, 0))
        self._rebuild_lbl = ttk.Label(pside, text="", font=(self._sans, 8),
                                      foreground=th["gray"], wraplength=200,
                                      justify=tk.LEFT)
        self._rebuild_lbl.pack(anchor=tk.W, pady=(2, 0))
        # A mode's radium holds every SCREEN that mode can show, and the
        # machine displays one at a time under game control.  Drawn together
        # they are an unreadable pile, and the scene names them itself, so
        # this offers them by name.  David, on a scene holding nine: "seeing
        # the preview like this is not useful. how can i see the different
        # states by themselves? there is no control for that."
        self._screen_row = ttk.Frame(pside)
        self._screen_shown = False
        self._fps_shown = False
        ttk.Label(self._screen_row, text="Screen", font=(self._sans, 8),
                  width=6).pack(side=tk.LEFT)
        self._screen_var = tk.StringVar(value=_ALL_SCREENS)
        # Narrow enough that the label, the box, ◀ ▶ and the "?" all fit the
        # side column — at 20 chars the "?" was pushed off the pane entirely.
        self._screen_box = ttk.Combobox(
            self._screen_row, textvariable=self._screen_var, width=12,
            state="readonly", values=[_ALL_SCREENS])
        self._screen_box.pack(side=tk.LEFT, padx=(4, 0))
        self._screen_box.bind("<<ComboboxSelected>>",
                              lambda _e: self._on_screen_pick())
        # Stepping beats re-opening a drop-down when you want to walk a scene's
        # screens one by one (David).  Wraps at both ends, and "All screens"
        # is the entry before the first, so ◀ from the first screen returns to
        # the composite.
        # Borderless canvas triangles, the audio preview's transport
        # convention (David) — not glyphs boxed in square buttons.
        _sb = dict(width=22, height=22, highlightthickness=0, bd=0,
                   cursor="hand2", takefocus=0)
        self._prev_btn = tk.Canvas(self._screen_row, **_sb)
        self._prev_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._prev_btn.bind("<Button-1>", lambda _e: self._step_screen(-1))
        self._next_btn = tk.Canvas(self._screen_row, **_sb)
        self._next_btn.pack(side=tk.LEFT)
        self._next_btn.bind("<Button-1>", lambda _e: self._step_screen(1))
        self._draw_step_icons()
        self._info(
            self._screen_row,
            "Which of the scene's screens to show.\n\n"
            "One scene file holds every screen a mode can put up — its intro, "
            "each award, the phase and victory screens — and the machine shows "
            "one at a time as the game runs. Drawn together they overlap into "
            "a pile, so pick one to see it by itself. The names are the "
            "scene's own.\n\n"
            "◀ and ▶ step through them without opening the list.")

        # Playback only makes sense for a scene that actually moves; showing a
        # Speed box on a still picture implied there was animation to play
        # (David).  _set_preview_controls packs this row only when there is.
        self._fps_row = frow = ttk.Frame(pside)
        ttk.Label(frow, text="Speed", font=(self._sans, 8), width=6).pack(
            side=tk.LEFT)
        self._fps_var = tk.StringVar(value=_FPS_FROM_FILE)
        self._fps_box = ttk.Combobox(frow, textvariable=self._fps_var,
                                     values=list(_FPS_CHOICES), width=10,
                                     state="readonly")
        self._fps_box.pack(side=tk.LEFT, padx=(4, 0))
        self._fps_box.bind("<<ComboboxSelected>>",
                           lambda _e: self._restart_animation())
        self._info(
            frow,
            "How fast an animated scene plays.\n\n"
            "\"Scene rate\" is the frame rate written in the scene itself — "
            "it really is per scene (12, 24, 30 and 60 all appear on one "
            "card). Pick a fixed rate to slow a fast sequence down for a "
            "closer look, or if a scene's own rate looks wrong: how long each "
            "individual frame is held is still undecoded, so a sequence with "
            "held frames plays faster here than on the machine.")
        # a tester: "would it be possible to do some different backgrounds? The
        # black does work most, but if you want to check the black border stuff
        # something different may help."
        self._bg_row = bgrow = ttk.Frame(pside)
        bgrow.pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(bgrow, text="Behind", font=(self._sans, 8), width=6).pack(
            side=tk.LEFT)
        self._bg_var = tk.StringVar(value=scene_render.BACKGROUND_NAMES[0])
        self._bg_box = ttk.Combobox(
            bgrow, textvariable=self._bg_var, width=12, state="readonly",
            values=list(scene_render.BACKGROUND_NAMES))
        self._bg_box.pack(side=tk.LEFT, padx=(4, 0))
        self._bg_box.bind("<<ComboboxSelected>>",
                          lambda _e: self._rerender())
        self._info(
            bgrow,
            "What the scene is laid over.\n\n"
            "The machine draws on BLACK, so that is the true picture — but a "
            "black outline on a black frame is as invisible here as it is "
            "there. Pick a light backdrop (or the checkerboard) to see the "
            "black borders and the edges of the art; nothing about the scene "
            "itself changes, only what shows through behind it.")
        _Tooltip(
            self._save_btn,
            "Write the scene out full size — the canvas here is a thumbnail "
            "of a 1360x768 frame.\n\n"
            "A still scene saves as a PNG. One that moves offers MP4 or GIF: "
            "the MP4 is the whole scene at its own frame rate, re-rendered "
            "for the export, and needs ffmpeg installed. The GIF is what is "
            "playing in the preview.",
            lambda: getattr(self.app, "_current_theme", "light"))
        _Tooltip(
            self._rebuild_btn,
            "Re-read the scene layouts from the card image on the Extract "
            "tab, so an improved preview reaches this project folder.\n\n"
            "Takes a few seconds and rewrites only the layout file — your "
            "images, glyph slices and font imports are left alone (a full "
            "re-extract would overwrite them).",
            lambda: getattr(self.app, "_current_theme", "light"))
        # Full width under the canvas: the caption says what is and isn't in
        # the frame, and it doesn't fit beside a 384px preview.
        # ONE line, never wrapped, with the full caption behind the "?".  It
        # used to wrap to one, two or three lines depending on how much a scene
        # had to admit, so the whole pane jumped every time you stepped to
        # another screen — "the area gets resized between different screens and
        # it is jarring" (David).  A fixed-height row keeps the summary in
        # sight without moving anything under it.
        caprow = ttk.Frame(right)
        caprow.pack(fill=tk.X, anchor=tk.W, pady=(3, 0))
        self._preview_lbl = ttk.Label(
            caprow, text="", font=(self._sans, 8), foreground=th["gray"],
            justify=tk.LEFT, anchor=tk.W)
        self._preview_lbl.pack(side=tk.LEFT)
        # Directly after the text, not floated to the far right, or it reads
        # as belonging to nothing.  _set_caption caps the visible line so this
        # button cannot be pushed out of view.
        self._caption_tip = self._info(caprow, "", side=tk.LEFT, padx=(6, 0))
        _Tooltip(self._preview,
                 "Composited from THIS project folder — replace an image or "
                 "import a font and the preview redraws with your version.\n\n"
                 "It is a still frame: the scene's animation timeline isn't "
                 "decoded, so anything that slides or fades in is shown where "
                 "it comes to rest.",
                 lambda: getattr(self.app, "_current_theme", "light"))

        bottom = ttk.Frame(right)
        bottom.pack(fill=tk.X, pady=(6, 0))
        self._thumb = tk.Canvas(bottom, width=160, height=90,
                                bg="#101014", highlightthickness=1)
        self._thumb.pack(side=tk.LEFT)
        self._detail_lbl = ttk.Label(bottom, text="", font=(self._sans, 9),
                                     foreground=th["gray"], wraplength=560,
                                     justify=tk.LEFT)
        self._detail_lbl.pack(side=tk.LEFT, fill=tk.X, padx=(8, 0))

        brow = ttk.Frame(body)
        brow.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(brow, text="Close", command=self._close).pack(side=tk.RIGHT)

        self._apply_canvas_bg()
        center_over(self.app.root, win, 1100, 800)
        win.deiconify()
        win.lift()

    def _close(self):
        # A bulk save is the one background job here that WRITES FILES the
        # user can see, so closing the window stops it rather than leaving
        # PNGs appearing in a folder minutes after the window went away.
        if self._bulk is not None:
            self._bulk["cancel"] = True
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # -- data ------------------------------------------------------------

    def reload(self, preselect=None, focus_text=None):
        try:
            self._scenes = collect_scenes(self.assets_dir)
        except Exception:
            self._scenes = {}
        self._layouts = scene_render.load_layouts(self.assets_dir)
        # Glyph slices may have changed since the last look (a font import),
        # so drop the cache and re-read them on the next preview.
        self._fonts = None
        if not self._scenes:
            self._hint.configure(
                text="No scene manifests found in this project folder. Run "
                     "Extract (with Images and Text enabled) on a Stern "
                     "Spike 2 card image first.")
        self._refresh_list(preselect, focus_text)

    def _sort_by(self, col):
        """Heading click: sort on *col*, or flip the direction if it is already
        the sort column.  Counts start descending (the big scenes are the ones
        worth finding), names start A-Z."""
        if col == self._sort_col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col, self._sort_rev = col, (col != "#0")
        sel = self._tree.selection()
        self._refresh_list(preselect=sel[0] if sel else None)

    def _sorted_dirs(self):
        """Scene dirs in the current sort order.  The label is always the tie
        break so equal counts stay in a stable, readable order."""
        key = _SORT_KEYS.get(self._sort_col, _SORT_KEYS["#0"])
        scenes = self._scenes

        def rank(d):
            sc = scenes[d]
            return (key(sc), sc["label"].lower()) if self._sort_col != "#0" \
                else (sc["label"].lower(),)

        out = sorted(scenes, key=rank)
        if self._sort_rev:
            out.reverse()
        return out

    def _haystack(self, d):
        """Everything the Search box matches a scene on."""
        sc = self._scenes[d]
        return (sc["label"] + " " + d + " "
                + " ".join(n for n, _p in sc["fonts"].values()) + " "
                + " ".join(sc["texts"])).lower()

    def _quiet_search(self, value):
        """Set the Search box without re-entering ``_refresh_list`` through
        its own trace."""
        self._suspend_search = True
        try:
            self._search_var.set(value)
        finally:
            self._suspend_search = False

    def _refresh_list(self, preselect=None, focus_text=None):
        tree = self._tree
        tree.delete(*tree.get_children())
        arrow = " ▾" if self._sort_rev else " ▴"
        for col, title in self._headings:
            tree.heading(col,
                         text=title + (arrow if col == self._sort_col else ""))
        q = (self._search_var.get() or "").strip().lower()
        # A jump in from another tab beats a search left in this window: with
        # the filter still on, the scene asked for isn't in the list at all
        # and the fallback below would quietly land on a different one.
        if q and preselect in self._scenes and q not in self._haystack(
                preselect):
            self._quiet_search("")
            q = ""
        for d in self._sorted_dirs():
            sc = self._scenes[d]
            if q and q not in self._haystack(d):
                continue
            tree.insert("", tk.END, iid=d, text=sc["label"],
                        values=(len(sc["images"]), len(sc["fonts"]),
                                len(sc["texts"]), len(sc["videos"])))
        kids = tree.get_children()
        want = preselect if preselect in (kids or ()) else (
            kids[0] if kids else None)
        # Remembered rather than selected here: ``selection_set`` below
        # delivers <<TreeviewSelect>> on the NEXT event-loop turn, so the
        # contents pane is rebuilt once more after this function returns and
        # anything picked out now would be wiped.  ``_on_select`` applies it
        # every time it builds THAT scene's contents, and drops it as soon as
        # another scene is selected.
        self._focus_want = (want, focus_text) if (want and focus_text) else None
        if want:
            tree.selection_set(want)
            tree.see(want)
        self._on_select()

    def _focus_text_row(self, text):
        """Pick out one display string in the contents list — the landing
        spot for "Show in Scenes…" on the Replace Text tab.  The Text group
        is collapsed on a scene with many lines, so open it first."""
        det = self._detail
        for grp in det.get_children():
            for kid in det.get_children(grp):
                if kid.startswith("txt::") and det.item(kid, "text") == text:
                    det.item(grp, open=True)
                    det.selection_set(kid)
                    det.see(kid)
                    self._on_detail()
                    return True
        return False

    def _on_select(self):
        det = self._detail
        det.delete(*det.get_children())
        self._thumb.delete("all")
        self._detail_lbl.configure(text="")
        sel = self._tree.selection()
        if not sel or self._scenes.get(sel[0]) is None:
            self._preview_token += 1          # abandon any in-flight render
            self._preview.delete("all")
            self._preview_img = self._preview_full = None
            self._set_caption("")
            self._save_btn.configure(state="disabled")
            return
        sc = self._scenes[sel[0]]
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
        if not sc["fonts"] and sc["texts"]:
            # Not a parser gap: these scenes draw each letter as its own
            # sprite (Letter_On/Letter_Off states) and carry no font at all.
            det.insert(n_f, tk.END,
                       text="no font — this scene draws its letters as images",
                       values=("see the Images list above",))
        n_t = det.insert("", tk.END, text="Text (%d)" % len(sc["texts"]),
                         open=len(sc["texts"]) <= 12)
        stock, picked = self._scene_text_colors(sel[0])
        for i, s in enumerate(sc["texts"]):
            # The colour is the scene's, not the font's, so it belongs on the
            # line and not in the Fonts window — say what it is and what it
            # will become.
            src = stock.get(s)
            if src is None:
                info = "double-click: find on Replace Text"
            elif s in picked:
                info = "%s → %s (not built yet)" % (text_colors.to_hex(src),
                                                    text_colors.to_hex(
                                                        picked[s]))
            else:
                info = "%s · right-click to recolour" % text_colors.to_hex(src)
            det.insert(n_t, tk.END, iid="txt::%d" % i, text=s, values=(info,))
        n_v = det.insert("", tk.END, text="Videos (%d)" % len(sc["videos"]),
                         open=True)
        for rel in sc["videos"]:
            det.insert(n_v, tk.END, iid="vid::" + rel,
                       text=os.path.basename(rel),
                       values=("double-click: show on Video tab",))
        if self._focus_want:
            scene, line = self._focus_want
            if scene == sel[0]:
                self._focus_text_row(line)
            else:
                self._focus_want = None     # the user moved on
        self._render_preview(sel[0])

    # -- preview ---------------------------------------------------------

    def _render_preview(self, scene_dir):
        """Composite the selected scene off the UI thread.

        Rendering itself is quick, but the first one has to parse the glyph
        manifest (100k+ rows on a big card), so it all goes to a worker and
        the fonts are cached for the window's lifetime.  A *token* makes stale
        results from fast clicking discard themselves."""
        self._preview_img = None
        self._frame_imgs = []
        self._frames_full = []
        self._preview.delete("all")
        self._save_btn.configure(state="disabled")
        self._preview_token += 1          # also stops any running animation
        token = self._preview_token
        card, layout = scene_render.layout_for_scene_dir(
            self._layouts, scene_dir)
        if layout is None:
            self._set_caption(
                "No preview for this scene."
                + ("" if self._layouts else
                   " This project was extracted before previews existed"
                   " — re-extract with Images enabled to get them."))
            # An empty canvas is near-black and so is a rendered night scene:
            # say which this is ON the canvas, or "no preview" reads as "this
            # scene is black" (David).
            self._canvas_message("no preview for this scene")
            return
        self._set_caption("Drawing…")
        self._canvas_message("drawing…")
        # Read the Tk vars HERE: the render runs on a worker thread and Tk is
        # not safe to touch from one.
        bg = self._background_name()
        colors = self._pending_colors(card)
        # A different scene starts at its first state; re-rendering the SAME
        # one (a state pick, a backdrop change) keeps where the user is.
        if scene_dir != getattr(self, "_preview_dir", None):
            try:
                self._screen_var.set(_ALL_SCREENS)
            except tk.TclError:
                pass
        self._preview_dir = scene_dir
        group = self._screen_index(layout)

        def work():
            try:
                if self._fonts is None:
                    from ..plugins.stern import fontrender as fr
                    self._fonts = fr.load_fonts(self.assets_dir)
                n = scene_render.frame_count(layout, 0, group)
                frames = [scene_render.render_layout(
                    self.assets_dir, layout, fonts=self._fonts, frame=i,
                    background=bg, colors=colors, group=group)
                    for i in range(min(n, _MAX_PREVIEW_FRAMES))]
            except Exception:
                frames = []
            try:
                self.app._tk_root().after(
                    0, lambda: self._show_preview(token, frames, layout,
                                                  group))
            except (tk.TclError, RuntimeError):
                # The window (or the whole app) closed while this render was
                # in flight — there is nothing left to draw on, and raising
                # here only surfaces as a stray worker-thread traceback.
                pass

        threading.Thread(target=work, daemon=True).start()

    # -- text colour -------------------------------------------------------

    def _scene_text_colors(self, scene_dir):
        """``(stock, picked)`` for one scene: the colour the game draws each
        line in (from the recorded layout) and any colour the user has chosen
        but not built yet."""
        card, layout = scene_render.layout_for_scene_dir(self._layouts,
                                                         scene_dir)
        stock = {}
        for tx in (layout or {}).get("texts") or ():
            stock.setdefault(tx.get("text") or "",
                             text_colors.from_floats(tx.get("rgba") or ()))
        picked = self._pending_colors(card) if card else {}
        return stock, picked

    def _pending_colors(self, card):
        try:
            return text_colors.colors_for(self.assets_dir, card) if card else {}
        except Exception:
            return {}

    def _pick_text_color(self, text, reset=False):
        """Recolour (or restore) one line of the selected scene's text."""
        sel = self._tree.selection()
        if not sel:
            return
        card, _layout = scene_render.layout_for_scene_dir(self._layouts, sel[0])
        stock, picked = self._scene_text_colors(sel[0])
        src = stock.get(text)
        if card is None or src is None:
            messagebox.showinfo(
                "Text colour",
                "This line's colour isn't in the recorded scene layout, so "
                "there is nothing to change it from.\n\nRun \"Rebuild "
                "previews…\" (or re-extract with Images enabled) and try "
                "again.", parent=self.win)
            return
        if reset:
            new = None
        else:
            start = picked.get(text, src)
            rgb = colorchooser.askcolor(
                color=text_colors.to_hex(start), parent=self.win,
                title="Colour for \"%s\"" % text[:40])[0]
            if not rgb:
                return
            new = tuple(int(c) for c in rgb)
        try:
            text_colors.set_color(self.assets_dir, card, text, src, new)
        except OSError as e:
            messagebox.showerror("Text colour", str(e), parent=self.win)
            return
        self._folder_state_written()
        self._on_select()               # re-lists the rows AND re-renders

    def _folder_state_written(self):
        """Tell the main window this project folder's pending edits changed, so
        the Write tab's preview picks the recolour up."""
        cb = getattr(self.app, "_on_folder_state_written", None)
        if cb is not None:
            try:
                cb(self.assets_dir)
            except Exception:
                pass

    def _background_name(self):
        """The chosen backdrop, read on the main thread."""
        try:
            return self._bg_var.get()
        except tk.TclError:
            return scene_render.BACKGROUND_NAMES[0]

    def _apply_canvas_bg(self):
        """Match the canvas letterbox to the backdrop, so a preview narrower
        than the canvas doesn't sit in a black frame that isn't part of it."""
        spec = scene_render.background_spec(self._background_name())
        rgb = spec if isinstance(spec, tuple) else (128, 128, 132)
        try:
            self._preview.configure(bg="#%02x%02x%02x" % rgb)
        except tk.TclError:
            pass

    def _rerender(self):
        """Redraw the selected scene (a backdrop or colour change — the layout
        itself is unchanged, so there is nothing to reload)."""
        self._apply_canvas_bg()
        sel = self._tree.selection()
        if sel:
            self._render_preview(sel[0])

    def _canvas_message(self, text):
        """Write a word on the preview canvas itself."""
        try:
            self._preview.delete("all")
            self._preview.create_text(
                int(self._preview.cget("width")) // 2,
                int(self._preview.cget("height")) // 2,
                text=text, fill="#6b6b76", font=(self._sans, 10))
        except tk.TclError:
            pass

    def _set_caption(self, text, lead=None):
        """Put ONE sentence of the caption on screen and the whole of it behind
        the "?".

        The caption admits whatever a scene couldn't decode, so it ran to one,
        two or three wrapped lines depending on the scene — and the pane under
        it jumped every time you stepped to another screen.  One unwrapped line
        is a fixed height; the detail is a hover away.

        *lead* names which sentence that should be, for the callers that have a
        layout to ask (``scene_render.caption_lead``).  Without it the first
        sentence is used, which is right for the status texts ("Saved x.mp4",
        "Drawing…") that are only one sentence anyway.
        """
        text = text or ""
        self._caption_tip.text = text
        head = (lead or text).split(". ")
        short = head[0] + ("." if len(head) > 1 else "")
        # Capped so the row can never grow wide enough to push the "?" out of
        # the window (nor the pane wider) — the full text is on the button.
        if len(short) > _CAPTION_CHARS:
            short = short[:_CAPTION_CHARS - 1].rstrip() + "…"
        try:
            self._preview_lbl.configure(text=short)
        except tk.TclError:
            pass

    def _info(self, parent, text, side=tk.LEFT, padx=(6, 0)):
        """The app's round blue ⓘ badge, with its tooltip opening BESIDE it.

        A tooltip bound to a combobox lands exactly where the drop-down opens,
        so hovering to read it covered the control you were about to click and
        the picker was unusable (David).  The explanation hangs off its own
        badge instead — the same one the Extract tab uses, not a square glyph
        button — and the tip is side-placed so it never covers the row.

        Returns the :class:`_Tooltip` so a caller can keep its text current."""
        mk = getattr(self.app, "_make_round_icon", None)
        if mk is None:                     # not the main window (a bare test)
            btn = ttk.Label(parent, text="i", width=2)
            btn.pack(side=side, padx=padx)
            tip = _Tooltip(btn, text,
                           lambda: getattr(self.app, "_current_theme",
                                           "light"), place="side")
            return tip
        badge = mk(parent, "i", self.app._INFO_BADGE_FILL,
                   self.app._INFO_BADGE_HOVER, text,
                   lambda: None, size=18,
                   font=("Georgia", 10, "bold italic"),
                   tooltip_place="side")
        # Clicking shows it too: on a short hover (or a touch screen) the badge
        # would otherwise do nothing at all, which reads as broken.
        badge.bind("<Button-1>", lambda _e: badge.icon_tip.show(), add="+")
        badge.pack(side=side, padx=padx)
        return badge.icon_tip

    def _screen_index(self, layout):
        """Which named screen to draw, or ``None`` for the composite."""
        names = scene_render.group_names(layout)
        try:
            want = self._screen_var.get()
        except tk.TclError:
            return None
        if not want or want == _ALL_SCREENS or want not in names:
            return None
        return names.index(want)

    def _set_preview_controls(self, layout, group, animated):
        """Show only the controls this scene can actually use.

        A Speed box on a still picture implied there was animation being
        withheld, and a scene holding several screens had no way to show them
        one at a time (David).  Both rows are packed on demand."""
        names = scene_render.group_names(layout)
        many = len(names) > 1
        self._draw_step_icons()
        # Tracked explicitly rather than via winfo_ismapped(): a widget in an
        # unmapped window reports 0 forever, so that would re-pack every time.
        try:
            if many:
                self._screen_box.configure(values=[_ALL_SCREENS] + list(names))
                self._screen_var.set(_ALL_SCREENS if group is None
                                     else names[group])
            if many != self._screen_shown:
                self._screen_shown = many
                if many:
                    # above the backdrop picker: which screen you are looking
                    # at matters more than what is behind it
                    self._screen_row.pack(anchor=tk.W, pady=(8, 0),
                                          before=self._bg_row)
                else:
                    self._screen_row.pack_forget()
            if bool(animated) != self._fps_shown:
                self._fps_shown = bool(animated)
                if self._fps_shown:
                    self._fps_row.pack(anchor=tk.W, pady=(8, 0),
                                       before=self._bg_row)
                else:
                    self._fps_row.pack_forget()
        except tk.TclError:
            pass

    def _draw_step_icons(self):
        """Paint the ◀ ▶ triangles in the theme foreground.

        Redrawn on every render so a theme switch while this window is open
        repaints them; they are canvases, not themed ttk widgets."""
        draw = getattr(self.app, "_draw_audio_icon", None)
        if draw is None:
            return
        for canvas, kind in ((self._prev_btn, "prev"), (self._next_btn,
                                                        "next")):
            try:
                canvas.configure(
                    bg=THEMES[getattr(self.app, "_current_theme",
                                      "light")]["bg"])
                draw(canvas, kind)
            except (tk.TclError, KeyError):
                pass

    def _step_screen(self, delta):
        """Move to the next/previous screen and redraw.

        Walking a nine-screen scene by re-opening the drop-down each time is
        the slow way round (David), so ◀/▶ step the same list.  "All screens"
        is entry 0, and the ends wrap, so you can keep pressing one button."""
        layout = self._current_layout()
        names = [_ALL_SCREENS] + list(scene_render.group_names(layout))
        if len(names) < 2:
            return
        try:
            cur = names.index(self._screen_var.get())
        except (ValueError, tk.TclError):
            cur = 0
        try:
            self._screen_var.set(names[(cur + delta) % len(names)])
        except tk.TclError:
            return
        self._on_screen_pick()

    def _on_screen_pick(self):
        """A different screen was chosen — re-render, keeping the selection."""
        sel = self._tree.selection()
        if sel:
            self._render_preview(sel[0])

    def _show_preview(self, token, frames, layout, group=None):
        """Main thread: put a finished render on the canvas (ignoring one that
        a newer selection has already superseded).  Several frames = an
        animation, which then plays."""
        if token != self._preview_token:
            return
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        frames = [f for f in frames or () if f is not None]
        note = scene_render.describe(layout, 0, group)
        # The one sentence that goes ON SCREEN is chosen by the same code that
        # builds the paragraph, not by "take the first one" here — on a scene
        # with something to admit the first sentence is the flattering one.
        lead = scene_render.caption_lead(layout, 0, group)
        self._set_preview_controls(layout, group, len(frames) > 1)
        if not frames:
            self._set_caption(
                "This scene's layout is known but it could not be drawn "
                "(a missing image or font in this project folder).")
            self._canvas_message("nothing could be drawn")
            return
        self._preview_full = frames[0]
        self._frames_full = frames
        cw = int(self._preview.cget("width"))
        chh = int(self._preview.cget("height"))
        try:
            from PIL import Image, ImageTk
            self._frame_imgs = []
            for f in frames:
                shown = f.copy()
                shown.thumbnail((cw, chh), Image.LANCZOS)
                self._frame_imgs.append(ImageTk.PhotoImage(shown))
        except Exception:
            self._set_caption(note, lead=lead)
            return
        self._preview_img = self._frame_imgs[0]
        self._preview.delete("all")
        self._preview_item = self._preview.create_image(
            cw // 2, chh // 2, image=self._preview_img)
        # describe() counts every frame the layout has; say so when the render
        # cap means fewer are actually on screen, or the caption over-promises.
        # Save preview… is where the rest exist: the MP4 export re-renders the
        # scene in full (the GIF is what is playing here, all it can be).
        n_all = scene_render.frame_count(layout, 0, group)
        if len(frames) > 1 and n_all > len(frames):
            note += (" Playing the first %d of them — \"Save preview…\" writes"
                     " all %d to MP4." % (len(frames), n_all))
        self._set_caption(note, lead=lead)
        self._save_btn.configure(state="normal")
        if len(self._frame_imgs) > 1:
            self._play(token, 0, self._effective_fps(layout))

    def _effective_fps(self, layout):
        """The rate to play at: the Speed box's fixed choice, else the rate
        the scene itself carries."""
        try:
            choice = self._fps_var.get()
        except tk.TclError:
            choice = _FPS_FROM_FILE
        if choice and choice != _FPS_FROM_FILE:
            try:
                return float(choice.split()[0])
            except (ValueError, IndexError):
                pass
        return scene_render.frame_rate(layout)

    def _restart_animation(self):
        """Speed changed: kill the running chain (its pending after() IS the
        chain) and start again at the new rate, without re-rendering."""
        if self._play_job is not None:
            try:
                self.win.after_cancel(self._play_job)
            except (tk.TclError, ValueError):
                pass
            self._play_job = None
        if len(self._frame_imgs) > 1:
            self._play(self._preview_token, 0,
                       self._effective_fps(self._current_layout()))

    def _play(self, token, i, fps):
        """Step the animation.  Keyed on the render token so switching scenes
        stops the old one dead rather than leaving two loops running."""
        if token != self._preview_token or not self._frame_imgs:
            return
        try:
            if not self.win.winfo_exists():
                return
            self._preview_img = self._frame_imgs[i % len(self._frame_imgs)]
            self._preview.itemconfigure(self._preview_item,
                                        image=self._preview_img)
        except tk.TclError:
            return
        # Floor of 10ms, not 30: a 30ms floor silently capped every scene at
        # 33 fps, so a 60 fps one played at half speed no matter what the rate
        # said.  Tk's timer granularity still limits how close to 60 we get.
        delay = max(10, int(round(1000.0 / max(1.0, fps))))
        self._play_job = self.win.after(
            delay, lambda: self._play(token, i + 1, fps))

    def _save_preview(self):
        """Write the full-size render out — the canvas is a thumbnail of a
        1360x768 frame, and it deserves a proper look.  An animated scene
        offers MP4 and GIF so the motion survives the export.

        MP4 is the default for one that moves, and the only export that is
        the WHOLE scene: it is re-rendered frame by frame straight into
        ffmpeg (:func:`core.video.encode_frames_to_mp4`), so it is neither
        capped at the :data:`_MAX_PREVIEW_FRAMES` the canvas plays nor held
        in memory.  A GIF stays what the preview holds — a 1900-frame one
        would be a few hundred MB of a format that stores 8-bit palettes and
        10ms delays.  A tester: "It would be cool to have the option to
        export the rendered scenes as MP4 files"."""
        img = getattr(self, "_preview_full", None)
        if img is None:
            return
        if self._export is not None:      # writing one: the button cancels
            self._export["cancel"] = True
            self._save_btn.configure(state="disabled")
            self._set_caption("Stopping the export…")
            return
        frames = [f for f in (self._frames_full or ()) if f is not None]
        layout = self._current_layout()
        group = self._screen_index(layout)
        n_all = scene_render.frame_count(layout, 0, group)
        animated = len(frames) > 1
        sel = self._tree.selection()
        base = (self._scenes.get(sel[0], {}).get("label") if sel else "") or "scene"
        safe = _safe_stem(base)
        types = [("PNG image", "*.png")]
        if animated:
            types.insert(0, ("Animated GIF", "*.gif"))
            types.insert(0, ("MP4 video", "*.mp4"))
        ext = "mp4" if animated else "png"
        path = filedialog.asksaveasfilename(
            parent=self.win, title="Save scene preview",
            defaultextension="." + ext,
            initialfile="%s.%s" % (safe, ext),
            filetypes=types)
        if not path:
            return
        fps = self._effective_fps(layout)
        if animated and path.lower().endswith(".mp4"):
            self._export_mp4(path, layout, group, n_all, fps)
            return
        try:
            if animated and path.lower().endswith(".gif"):
                # GIF frame delays are stored in 10ms units and most viewers
                # clamp anything under 20ms, so that is the honest floor here
                # even when the scene asks for 60 fps.
                frames[0].save(
                    path, save_all=True, append_images=frames[1:], loop=0,
                    duration=max(20, int(round(1000.0 / max(1.0, fps)))))
            else:
                img.save(path)
        except (OSError, ValueError) as e:
            messagebox.showerror("Save failed", str(e), parent=self.win)
            return
        self._set_caption("Saved %s" % os.path.basename(path))

    def _export_mp4(self, path, layout, group, n_all, fps):
        """Re-render the whole scene into an MP4 off the UI thread.

        Rendering is the slow half (a frame is a composite of the project
        folder's own PNGs), so it runs on a worker and reports frames as they
        go — the same shape as "Rebuild previews…", cancel button included:
        a long scene is a minute of work and the window would otherwise sit
        there with no way out of it."""
        bg = self._background_name()
        card, _lay = scene_render.layout_for_scene_dir(self._layouts,
                                                       self._preview_dir)
        colors = self._pending_colors(card)
        state = self._export = {"cancel": False}
        self._save_btn.configure(text="Cancel")
        self._set_caption("Writing %s — frame 1 of %d…"
                          % (os.path.basename(path), n_all))

        def work():
            def render():
                for i in range(n_all):
                    if state["cancel"]:
                        return
                    yield scene_render.render_layout(
                        self.assets_dir, layout, fonts=self._fonts, frame=i,
                        background=bg, colors=colors, group=group)

            try:
                n = video.encode_frames_to_mp4(
                    render(), path, fps=fps,
                    progress=lambda c: self._export_progress(state, c, n_all))
                err = None
            except Exception as e:          # no ffmpeg, bad path, ffmpeg died
                n, err = 0, e
            try:
                self.app._tk_root().after(
                    0, lambda: self._export_done(state, path, n, fps, err))
            except (tk.TclError, RuntimeError):
                pass                        # window closed mid-export

        threading.Thread(target=work, daemon=True).start()

    def _export_progress(self, state, cur, total):
        """Worker thread: report progress ~every 10 frames (a label update per
        frame of a 1900-frame scene is all jitter)."""
        if state is not self._export or (cur % 10 and cur != total):
            return
        try:
            self.app._tk_root().after(
                0, lambda: self._export_tick(state, cur, total))
        except (tk.TclError, RuntimeError):
            pass

    def _export_tick(self, state, cur, total):
        if state is not self._export:
            return
        try:
            self._set_caption("Writing the MP4 — frame %d of %d…"
                              % (cur, total))
        except tk.TclError:
            pass

    def _export_done(self, state, path, n, fps, err):
        if state is not self._export:
            return
        self._export = None
        try:
            self._save_btn.configure(text="Save preview…", state="normal")
        except tk.TclError:
            return
        if state["cancel"]:
            # ffmpeg closed a truncated stream cleanly, so there IS a file —
            # a half-length one nobody asked for.  Take it away rather than
            # leave a silently short scene on disk.
            try:
                os.remove(path)
            except OSError:
                pass
            self._set_caption("Stopped — %s not written."
                              % os.path.basename(path))
            return
        if err is not None or not n:
            self._set_caption("Could not write %s" % os.path.basename(path))
            messagebox.showerror(
                "Save failed", str(err) or "Nothing could be rendered.",
                parent=self.win)
            return
        self._set_caption("Saved %s — %d frame%s at %g fps"
                          % (os.path.basename(path), n,
                             "" if n == 1 else "s", fps))

    # -- save every scene's preview ---------------------------------------

    def _save_all_previews(self):
        """Write one PNG per listed scene into a folder the user picks.

        THE BATCH IS WHAT THE LIST IS SHOWING, not every scene on the card:
        the Search box already exists to narrow a card's few hundred scenes to
        the ones being worked on, and silently exporting the other 280 would
        be the "no silent extra work" version of the same surprise.

        FRAME 0 OF THE COMPOSITE, and the summary says so.  An animated scene
        is one still here — the whole thing is what "Save preview…" writes as
        MP4, one scene at a time, and doing that for 300 scenes unattended is
        a different (much longer) job than the one being asked for.

        Same shape as "Rebuild previews…" and the MP4 export: rendering runs
        on a worker (a frame is a composite of the project folder's own PNGs)
        and the button becomes a live Cancel, so a big card is not a window
        with no way out of it.
        """
        if self._bulk is not None:            # running: the button cancels
            self._bulk["cancel"] = True
            self._save_all_btn.configure(state="disabled")
            self._set_caption("Stopping…")
            return
        dirs = [d for d in self._tree.get_children("") if d in self._scenes]
        if not dirs:
            messagebox.showinfo(
                "Save all previews",
                "No scenes are listed to save.", parent=self.win)
            return
        out = filedialog.askdirectory(
            parent=self.win, title="Save every listed scene preview into…")
        if not out:
            return
        # Tk is not safe off the main thread, so everything the render needs
        # from a widget is read HERE (the MP4 export's rule, same reason).
        # The batch travels ON the state, so what was dispatched is one
        # readable fact rather than three closure variables.
        state = self._bulk = {
            "cancel": False, "out": out, "dirs": dirs,
            "bg": self._background_name(),
            "labels": {d: (self._scenes[d].get("label") or d) for d in dirs}}
        self._save_all_btn.configure(text="Cancel")
        self._set_caption("Saving %d scene preview%s…"
                          % (len(dirs), "" if len(dirs) == 1 else "s"))

        def work():
            written, skipped, err = self._save_all_work(state)
            try:
                self.app._tk_root().after(
                    0, lambda: self._save_all_done(state, out, written,
                                                   skipped, err))
            except (tk.TclError, RuntimeError):
                pass                          # window closed mid-export

        threading.Thread(target=work, daemon=True).start()

    def _save_all_work(self, state):
        """Worker body: render each scene in *state*'s batch and write it.
        ``(written, skipped, error)``.

        A SEPARATE, TK-FREE METHOD ON PURPOSE.  Every widget value it needs
        was read onto *state* on the main thread, so the batch can be driven
        straight in a test — a worker thread cannot reach Tk at all outside
        ``mainloop()`` (``after`` from one raises ``RuntimeError: main thread
        is not in main loop``), which makes the threaded shape untestable and
        this half not.
        """
        dirs, labels = state["dirs"], state["labels"]
        out, bg = state["out"], state["bg"]
        written, skipped, used, err = 0, 0, set(), None
        try:
            if self._fonts is None:
                from ..plugins.stern import fontrender as fr
                self._fonts = fr.load_fonts(self.assets_dir)
            for i, d in enumerate(dirs):
                if state["cancel"]:
                    break
                card, layout = scene_render.layout_for_scene_dir(
                    self._layouts, d)
                img = None
                if layout is not None:
                    try:
                        img = scene_render.render_layout(
                            self.assets_dir, layout, fonts=self._fonts,
                            frame=0, background=bg,
                            colors=self._pending_colors(card), group=None)
                    except Exception:
                        img = None
                if img is None:
                    # A scene with no recorded layout, or one whose images are
                    # not in this folder: counted, never guessed at.
                    skipped += 1
                else:
                    try:
                        img.save(os.path.join(
                            out, _unique_png(labels[d], used)))
                        written += 1
                    except (OSError, ValueError):
                        skipped += 1
                self._bulk_progress(state, i + 1, len(dirs))
        except Exception as e:                # no fonts, unreadable folder…
            err = e
        return written, skipped, err

    def _bulk_progress(self, state, cur, total):
        """Worker thread: report ~every 5 scenes (a label update per scene on
        a 300-scene card is all jitter)."""
        if state is not self._bulk or (cur % 5 and cur != total):
            return
        try:
            self.app._tk_root().after(
                0, lambda: self._bulk_tick(state, cur, total))
        except (tk.TclError, RuntimeError):
            pass

    def _bulk_tick(self, state, cur, total):
        if state is not self._bulk:
            return
        try:
            self._set_caption("Saving previews — scene %d of %d…"
                              % (cur, total))
        except tk.TclError:
            pass

    def _save_all_done(self, state, out, written, skipped, err):
        if state is not self._bulk:
            return
        self._bulk = None
        try:
            self._save_all_btn.configure(text="Save all previews…",
                                         state="normal")
        except tk.TclError:
            return
        if err is not None:
            self._set_caption("Could not save the previews.")
            messagebox.showerror("Save all previews", str(err),
                                 parent=self.win)
            return
        # The skipped count is never rounded away: a folder of 240 PNGs from a
        # 300-scene list has to say what happened to the other 60.
        tail = ("" if not skipped
                else "  %d scene%s could not be drawn." % (
                    skipped, "" if skipped == 1 else "s"))
        if state["cancel"]:
            self._set_caption("Stopped — %d preview(s) written.%s"
                              % (written, tail))
            return
        self._set_caption(
            "Saved %d preview%s to %s (first frame of each).%s"
            % (written, "" if written == 1 else "s",
               os.path.basename(out.rstrip("/\\")) or out, tail))

    # -- rebuild previews -------------------------------------------------

    def card_image_path(self):
        """The card image the previews would be rebuilt from — the Extract
        tab's Input, which is where this project folder came from."""
        var = getattr(self.app, "extract_input_var", None)
        try:
            return (var.get() or "").strip() if var is not None else ""
        except tk.TclError:
            return ""

    def _rebuild_previews(self):
        """Re-read the card's scene graphs and rewrite scene_layout.json.

        An improved parser otherwise only reaches an existing project folder
        through a full re-extract, which takes minutes AND overwrites every
        atlas PNG and glyph slice — throwing away an imported font.  Parsing
        the node graphs alone takes a few seconds and writes exactly one
        file."""
        if self._rebuild is not None:            # running: the button cancels
            self._rebuild["cancel"] = True
            self._rebuild_btn.configure(state="disabled")
            self._rebuild_lbl.configure(text="Stopping…")
            return
        card = self.card_image_path()
        if not card or not os.path.isfile(card):
            messagebox.showinfo(
                "Rebuild previews",
                "Set the Extract tab's Input to the card image this project "
                "folder was extracted from — the scene layouts are read back "
                "off the card.", parent=self.win)
            return
        state = self._rebuild = {"cancel": False}
        self._rebuild_btn.configure(text="Cancel")
        self._rebuild_lbl.configure(text="Reading the card…")

        def work():
            from ..plugins.stern import engine
            msgs = []
            try:
                n = engine.rebuild_scene_layouts_from_card(
                    card, self.assets_dir,
                    log=lambda m, lvl="info": msgs.append((m, lvl)),
                    progress=lambda c, t, d="": self._rebuild_progress(
                        state, c, t),
                    cancel=lambda: state["cancel"])
                err = None
            except Exception as e:                # unreadable card, no perms…
                n, err = 0, e
            try:
                self.app._tk_root().after(
                    0, lambda: self._rebuild_done(state, n, err, msgs))
            except (tk.TclError, RuntimeError):
                pass                     # window closed mid-rebuild

        threading.Thread(target=work, daemon=True).start()

    def _rebuild_progress(self, state, cur, total):
        """Worker thread: show how far along we are, ~every 10 scenes (301 on
        a TMNT card, and a label update per scene is all jitter)."""
        if state is not self._rebuild or (cur % 10 and cur + 1 != total):
            return
        try:
            self.app._tk_root().after(
                0, lambda: self._rebuild_tick(state, cur + 1, total))
        except (tk.TclError, RuntimeError):
            pass                         # window closed mid-rebuild

    def _rebuild_tick(self, state, cur, total):
        if state is not self._rebuild:
            return
        try:
            self._rebuild_lbl.configure(text="Scene %d of %d…" % (cur, total))
        except tk.TclError:
            pass

    def _rebuild_done(self, state, n, err, msgs):
        """Main thread: report, then reload so the new layouts are on screen."""
        if state is not self._rebuild:
            return
        self._rebuild = None
        try:
            self._rebuild_btn.configure(text="Rebuild previews…",
                                        state="normal")
        except tk.TclError:
            return
        if state["cancel"]:
            self._rebuild_lbl.configure(text="Stopped — layouts unchanged.")
            return
        if err is not None or not n:
            # The engine's own warning says WHY (no image manifest, no
            # drawable scene); an unexpected exception has no such line.
            why = next((m for m, lvl in msgs if lvl == "warning"), None)
            self._rebuild_lbl.configure(text="Could not rebuild.")
            messagebox.showwarning(
                "Rebuild previews", why or str(err)
                or "No scene layouts could be read from that card image.",
                parent=self.win)
            return
        self._rebuild_lbl.configure(text="Rebuilt %d scene layout(s)." % n)
        sel = self._tree.selection()
        self.reload(sel[0] if sel else None)

    def _current_layout(self):
        sel = self._tree.selection()
        if not sel:
            return None
        return scene_render.layout_for_scene_dir(self._layouts, sel[0])[1]

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
            img.thumbnail((160, 90))
            self._photo = ImageTk.PhotoImage(img)
            self._thumb.create_image(80, 45, image=self._photo)
        except Exception:
            pass

    # -- right-click actions ----------------------------------------------

    def _popup_menu(self, event):
        """Build the menu for the row under the cursor and post it."""
        iid = self._detail.identify_row(event.y)
        if not iid or "::" not in iid:
            return
        self._detail.selection_set(iid)
        m = self._menu
        m.delete(0, tk.END)
        if iid.startswith("txt::"):
            text = self._detail.item(iid, "text")
            sel = self._tree.selection()
            _stock, picked = (self._scene_text_colors(sel[0]) if sel
                              else ({}, {}))
            m.add_command(label="Text colour…",
                          command=lambda: self._pick_text_color(text))
            if text in picked:
                m.add_command(
                    label="Back to the original colour",
                    command=lambda: self._pick_text_color(text, reset=True))
            m.add_separator()
            m.add_command(label="Find on the Replace Text tab",
                          command=lambda: self._jump(iid))
        elif iid.startswith("font::"):
            key = iid[6:]
            m.add_command(label="Blank this font in this scene",
                          command=lambda: self._blank_font(key, True))
            m.add_command(label="Blank this font everywhere it is used",
                          command=lambda: self._blank_font(key, False))
            m.add_separator()
            m.add_command(label="Open in the Fonts window",
                          command=lambda: self._jump(iid))
        elif iid.startswith("img::"):
            m.add_command(label="Show on the Images tab",
                          command=lambda: self._jump(iid))
        elif iid.startswith("vid::"):
            m.add_command(label="Show on the Video tab",
                          command=lambda: self._jump(iid))
        else:
            return
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _blank_font(self, table_key, this_scene_only):
        """Erase every letter of a font so it draws nothing.

        This is how an outline / shadow font gets removed: the game still
        draws it, it just has nothing to draw.  Blanking is otherwise CARD-WIDE
        — one atlas serves every scene using it — so "in this scene" writes a
        scene scope first, which is the difference between losing one border
        and losing it on several hundred screens you never opened."""
        from ..plugins.stern import fontrender as fr
        sel = self._tree.selection()
        if not sel:
            return
        scene_dir = sel[0]
        try:
            fonts = fr.load_fonts(self.assets_dir)
        except Exception as e:
            messagebox.showerror("Blank font", str(e), parent=self.win)
            return
        font = next((f for f in fonts if f["key"] == table_key), None)
        if font is None:
            messagebox.showinfo(
                "Blank font",
                "This font isn't in the project folder's glyph manifest — "
                "re-extract with Images enabled to edit it.", parent=self.win)
            return
        try:
            used_in = fr.scenes_for_font(self.assets_dir, font)
        except Exception:
            used_in = []
        here = [p for p in used_in
                if p.replace("\\", "/").rsplit("/", 1)[0] == scene_dir]
        name = font.get("name") or font["key"]
        if this_scene_only and not here:
            messagebox.showinfo(
                "Blank font",
                "Couldn't work out which scene file this font belongs to, so "
                "blanking it here would blank it everywhere. Use \"everywhere "
                "it is used\" if that is what you want.", parent=self.win)
            return
        where = ("this scene only (it is used in %d)" % len(used_in)
                 if this_scene_only
                 else "all %d scene(s) that use it" % max(1, len(used_in)))
        if not messagebox.askyesno(
                "Blank font",
                "Erase every letter of \"%s\" (%dpx) so it draws nothing, in "
                "%s?\n\nThis is the way to drop an outline or shadow font. "
                "\"Revert font\" in the Fonts window puts the letters back "
                "from the atlas image."
                % (name, font.get("px", 0), where), parent=self.win):
            return
        try:
            fr.set_font_scope(self.assets_dir, font, here if this_scene_only
                              else None)
            n = fr.clear_font(font)
        except Exception as e:
            messagebox.showerror("Blank font",
                                 "Couldn't blank \"%s\":\n\n%s" % (name, e),
                                 parent=self.win)
            return
        self._fonts = None              # the preview must re-read the glyphs
        self._rerender()
        self._refresh_font_studio()
        try:
            self.app._start_change_scan("image")
        except Exception:
            pass
        self._set_caption(
            "Blanked %d letter(s) of \"%s\" — %s. Build on the Write tab "
            "to put it on the card." % (n, name, where))

    def _refresh_font_studio(self):
        """Keep an open Fonts window in step with a blank done from here."""
        fs = getattr(self.app, "_font_studio", None)
        try:
            if fs is not None and fs.win.winfo_exists():
                fs.reload()
        except Exception:
            pass

    def _jump(self, iid):
        """The double-click action, reachable from the menu too."""
        try:
            if iid.startswith("img::"):
                self.app.reveal_image_slot(iid[5:])
            elif iid.startswith("font::"):
                from .font_studio import open_font_studio
                open_font_studio(self.app, self.assets_dir,
                                 preselect=iid[6:])
            elif iid.startswith("txt::"):
                self.app.reveal_text_string(self._detail.item(iid, "text"))
            elif iid.startswith("vid::"):
                self.app.reveal_video_slot(iid[5:])
        except Exception:
            pass

    def _on_detail_double(self, _event):
        sel = self._detail.selection()
        if sel:
            self._jump(sel[0])


def open_scene_browser(app, assets_dir, preselect=None, focus_text=None):
    """Open (or re-use and refocus) the app's Scenes window."""
    win = getattr(app, "_scene_browser", None)
    if win is not None:
        try:
            if win.win.winfo_exists():
                if win.assets_dir != assets_dir:
                    win.assets_dir = assets_dir
                    win.reload(preselect, focus_text)
                elif preselect or focus_text:
                    win.reload(preselect, focus_text)
                win.win.deiconify()
                # lift() also undoes a _step_aside_for_jump() that pushed this
                # window behind the main one.
                win.win.lift()
                win.win.focus_set()
                return win
        except tk.TclError:
            pass
    win = SceneBrowserWindow(app, assets_dir, preselect=preselect,
                             focus_text=focus_text)
    app._scene_browser = win
    return win
