"""The Scenes tab ("what each scene is made of"; it was a floating window until PAD-251).

Ported from ``gui/scene_browser.py`` (``SceneBrowserWindow`` and its
``_LayoutDialog``).  The Replace Text tab opens it ("Show in Scenes…"); the
Images and Video tabs open it too in Tk, and can here through the text tab's
``_open_scene_browser`` (exported on the window).  The page is ``ScenesPage`` in
``static/js/tabs/text_scenes.js``, shown by the Scenes tab (``tabs/scenes.py``): opening
the scenes brings that tab forward.

State lives in the store namespace ``text_scenes``; calls are
``text_scenes.<method>``.  Everything the Tk window computed is computed the
same way here, from the same plugin modules (``scene_render``,
``text_colors``, ``text_layout``, ``fontrender``, ``core.video``); only the
drawing moved: rendered frames are written to a scratch folder and the page
shows them through ``/media``.
"""

import logging
import os
import re
import shutil
import tempfile
import threading

from . import compat
from .rpc import rpc
from .scene_mode_layout import ModeLayoutMixin
from .text_scenes_tree import TreeEditMixin

log = logging.getLogger(__name__)

_RADIMG_NAME = re.compile(r"^radimg_(.+)_\d+x\d+_[0-9a-f]{8}\.png$",
                          re.IGNORECASE)
#: A TMNT static loop is ~1900 frames; the preview plays the first 60.
_MAX_PREVIEW_FRAMES = 60
_FPS_FROM_FILE = "Scene rate"
_ALL_SCREENS = "All screens"
_CAPTION_CHARS = 96
_FPS_CHOICES = (_FPS_FROM_FILE, "60 fps", "30 fps", "24 fps", "20 fps",
                "15 fps", "12 fps", "8 fps", "4 fps", "2 fps")
#: The page's preview frames are this size at most (the saved previews are
#: always full size).
_DISPLAY_SIZE = (960, 544)

HINT = ("Every scene on the card, with the images, fonts and on-screen text "
        "it is built from. Double-click an item to jump to it on the "
        "matching tab; this tab keeps its place for when you come back. "
        "Click a picture or a line of text in the preview to move, resize, tint, hide or "
        "re-layer it; right-click an item to recolour a line of text or blank a font out "
        "of the picture.")
HINT_EMPTY = ("No scene manifests found in this project folder. Run Extract "
              "(with Images and Text enabled) on a Stern Spike 2 card image "
              "first.")

TIPS = {
    "list": "Scene names come from the scene's own sprite names plus the "
            "8-character scene id — the same shorthand the Images tab's "
            "\"Group by scene\" and the Replace Text Scene column use.",
    "save": "A picture of this scene for you to keep or share (not needed for your "
            "edits: they are kept as you make them, and Write puts them on the card).\n\n"
            "The scene is written out full size, a 1360x768 frame. A still scene saves as a PNG. One that "
            "moves offers an MP4 video: the whole scene, every frame at its own "
            "frame rate, drawn as it shows here (your edits, the preview eyes, the "
            "backdrop and the Machine screen included). It needs ffmpeg installed. "
            "The frame on the preview can be saved as a PNG instead.",
    "save_all": "Pictures of the scenes for you to keep or share (not needed for your "
                "edits). One PNG per scene into a folder you pick — every "
                "scene the list is showing, so a Search narrows the batch."
                "\n\nAn animated scene is saved as its resting frame; "
                "\"Export all videos…\" writes the whole of each one as an MP4.",
    "save_all_video": "A video of every scene the list is showing (a Search narrows the "
                      "batch), in one go: one MP4 per scene that moves, every frame at the "
                      "scene's own frame rate, into a folder you pick. A scene that does "
                      "not move is saved as a PNG. Needs ffmpeg installed; the button "
                      "becomes Cancel while it runs.",
    "rebuild": "Re-read the scenes from the card image on the Extract "
               "tab, so an improved preview reaches this project folder. Your scene edits are "
               "kept: this is not a reset (Reset, under the preview, is)."
               "\n\nTakes a few seconds and rewrites only the layout file — "
               "your images, glyph slices and font imports are left alone "
               "(a full re-extract would overwrite them).",
    "screen": "Which of the scene's screens to show.\n\nOne scene file holds "
              "every screen a mode can put up — its intro, each award, the "
              "phase and victory screens — and the machine shows one at a "
              "time as the game runs. Drawn together they overlap into a "
              "pile, so pick one to see it by itself. The names are the "
              "scene's own.\n\n◀ and ▶ step through them without opening the "
              "list.",
    "speed": "How fast an animated scene plays.\n\n\"Scene rate\" is the "
             "frame rate written in the scene itself — it really is per "
             "scene (12, 24, 30 and 60 all appear on one card). Pick a fixed "
             "rate to slow a fast sequence down for a closer look, or if a "
             "scene's own rate looks wrong: how long each individual frame "
             "is held is still undecoded, so a sequence with held frames "
             "plays faster here than on the machine.",
    "behind": "What the scene is laid over.\n\nThe machine draws on BLACK, "
              "so that is the true picture — but a black outline on a black "
              "frame is as invisible here as it is there. Pick a light "
              "backdrop (or the checkerboard) to see the black borders and "
              "the edges of the art; nothing about the scene itself changes, "
              "only what shows through behind it.",
    "preview": "Composited from THIS project folder — replace an image or "
               "import a font and the preview redraws with your version."
               "\n\nIt is a still frame: the scene's animation timeline "
               "isn't decoded, so anything that slides or fades in is shown "
               "where it comes to rest.",
}


def _safe_stem(label):
    return "".join(c if (c.isalnum() or c in "-_") else "_"
                   for c in (label or "scene")) or "scene"


def _unique_name(label, used, ext="png"):
    """``<label>.<ext>``, suffixed ``_2``, ``_3``… while the stem is already in *used* (two
    scenes that sanitise alike must not overwrite each other)."""
    stem = _safe_stem(label)
    name, n = stem, 2
    while name.lower() in used:
        name, n = "%s_%d" % (stem, n), n + 1
    used.add(name.lower())
    return "%s.%s" % (name, ext)


def _unique_png(label, used):
    return _unique_name(label, used, "png")


def collect_scenes(assets_dir):
    """The Scenes window's grouping of the extract manifests by scene
    directory (``gui/scene_browser.collect_scenes``, which goes away with
    the Tk window; tests/test_webui_text.py checks the two agree)."""
    return _collect_scenes(assets_dir)


def _rows(assets_dir, *parts):
    try:
        with open(os.path.join(assets_dir, *parts), encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if line and not line.startswith("#"):
                    yield line.split("\t")
    except OSError:
        return


def _collect_scenes(assets_dir):
    """``scene_browser.collect_scenes`` verbatim (see there for the why of
    every step): ``{scene_dir: {"label", "images": [(order, rel)],
    "fonts": {table: (name, px)}, "texts": [str], "videos": [rel]}}``, and
    ``"program": True`` on the game program's strings (PAD-468)."""
    scenes = {}

    def scene_for(d):
        sc = scenes.get(d)
        if sc is None:
            sc = scenes[d] = {"label": "", "hint": "", "images": [],
                              "fonts": {}, "texts": [], "videos": []}
        return sc

    atlas_scenes = {}
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
    try:
        from ..core import text_manifest
        for row in text_manifest.load(assets_dir):
            p = (row.get("path") or "").replace("\\", "/")
            if p:
                sc = scene_for(p.rsplit("/", 1)[0])
                sc["texts"].append(row.get("original") or "")
                if not p.lower().endswith(".radium"):
                    # the game program's own strings (/godzilla_le/game): listed as one
                    # "scene", but no scene draws them as they are (PAD-468)
                    sc["program"] = True
    except Exception:                                # noqa: BLE001
        pass
    scene_font_px = {}
    try:
        from ..plugins.stern import scene_render as _sr
        for card, lay in (_sr.load_layouts(assets_dir) or {}).items():
            d = card.replace("\\", "/").rsplit("/", 1)[0]
            for t in (lay or {}).get("texts") or ():
                if t.get("font") and t.get("font_px"):
                    scene_font_px[(d, t["font"])] = int(t["font_px"])
    except Exception:                                # noqa: BLE001
        pass
    size_px, rep_px = {}, {}
    try:
        from ..plugins.stern import fontrender as _fr
        for fo in _fr.load_fonts(assets_dir):
            rep_px[fo["key"]] = fo["px"]
            for sid, v in (fo.get("sizes") or {}).items():
                size_px[(fo["key"], sid)] = v["px"]
    except Exception:                                # noqa: BLE001
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


_SORT_KEYS = {
    "#0": lambda sc: sc["label"].lower(),
    "imgs": lambda sc: len(sc["images"]),
    "fonts": lambda sc: len(sc["fonts"]),
    "texts": lambda sc: len(sc["texts"]),
    "vids": lambda sc: len(sc["videos"]),
}


def glyph_atlas_rel(assets, rel):
    """A glyph slice's atlas PNG rel (``images/…``) via the glyph manifest
    (Tk ``_glyph_atlas_rel``): scene lookups group by atlas, not slice."""
    want = rel[len("images/"):] if rel.startswith("images/") else rel
    try:
        with open(os.path.join(assets, "images", "scene_textures",
                               "glyph_images.txt"), encoding="utf-8") as f:
            for line in f:
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) >= 2 and cols[0] == want:
                    return "images/" + cols[1]
    except OSError:
        pass
    return None


class TextScenesService(ModeLayoutMixin, TreeEditMixin):
    ns = "text_scenes"

    def __init__(self, tab):
        self.tab = tab
        self.window = tab.window
        self.ctx = tab.ctx
        self.store = tab.ctx.store
        self.assets_dir = ""
        self._alive = False           # the Tk window exists
        self._scenes = {}
        self._layouts = {}
        self._fonts = None
        self._text_changes = None
        self._sort_col, self._sort_rev = "#0", False
        self._search = ""
        self._sel = None
        self._listed = []
        self._focus_want = None
        self._find_at = None          # the search match Previous / Next is on (PAD-429)
        self._find_stepping = False   # Previous / Next is picking its line (PAD-468)
        self._token = 0
        self._frames_full = []
        self._preview_full = None
        self._preview_dir = None
        self._screen = _ALL_SCREENS
        self._fps_choice = _FPS_FROM_FILE
        self._bg = self._bg_names()[0]
        self._live_layout = None
        self._live_job = None
        self._export = None
        self._bulk = None
        self._vbulk = None            # "Export all videos…" running (PAD-365)
        self._rebuild = None
        self._tmp = None
        self._raise_n = 0
        self._auto_tried = None
        self._tree_init()
        self._reset_state()

    # ------------------------------------------------------------------
    def set(self, **kw):
        return self.store.set(self.ns, **kw)

    @staticmethod
    def _bg_names():
        try:
            from ..plugins.stern import scene_render
            return list(scene_render.BACKGROUND_NAMES)
        except Exception:                            # noqa: BLE001
            return ["Black"]

    def _reset_state(self):
        self.set(open=False, alive=False, hint=HINT, search="", scenes=[], find=None,
                 sel=None,
                 sort={"col": "#0", "rev": False}, contents=None, item=None,
                 thumb="", detail="", caption="", caption_full="",
                 frames=[], fps=0, canvas_msg="", can_save=False,
                 screens=[], screen=_ALL_SCREENS, animated=False,
                 fps_choice=_FPS_FROM_FILE, fps_choices=list(_FPS_CHOICES),
                 bg=self._bg, bgs=self._bg_names(), bg_rgb=self._bg_rgb(),
                 machine_look=any(self._look_sw().values()),
                 exporting=False, bulk=False, rebuilding=False,
                 can_video=False, bulk_video=False, export_msg="",
                 rebuild_msg="", layout_dialog=None, tips=TIPS,
                 tree=False, tree_view=None, tree_layers=None, tree_busy=False,
                 tree_loading=False, tree_img_rev=0, preparing=None, tree_live=None,
                 card_note="", pic_note="", tree_play=None, mode_layout=None)

    def is_open(self):
        return self._alive

    # ------------------------------------------------------------------
    # opening / closing
    # ------------------------------------------------------------------
    def open(self, assets, preselect_rel=None, preselect_video=None,
             preselect_dir=None, focus_text=None, search=None):
        """Tk ``_open_scene_browser`` + ``open_scene_browser``; *search* goes in
        the search box (a game-program line several screens hold, PAD-485)."""
        preselect = preselect_dir
        if preselect is None and (preselect_rel or preselect_video):
            rel = (preselect_rel or preselect_video).replace("\\", "/")
            if preselect_rel and "/glyphs/" in rel:
                rel = glyph_atlas_rel(assets, rel) or rel
            try:
                for d, sc in collect_scenes(assets).items():
                    if preselect_video:
                        hit = rel in sc["videos"]
                    else:
                        hit = any(r == rel for _o, r in sc["images"])
                    if hit:
                        preselect = d
                        break
            except Exception:                        # noqa: BLE001
                pass
        if self._mlay is not None and self._mlay["assets"] != assets:
            self._mlay = None                  # PAD-323: another project's scenes
        if self._alive:
            if search is not None:
                self._search = search
            if self.assets_dir != assets:
                self.assets_dir = assets
                self.reload(preselect, focus_text)
            elif preselect or focus_text:
                self.reload(preselect, focus_text)
        else:
            self._alive = True
            self.assets_dir = assets
            self._sort_col, self._sort_rev = "#0", False
            self._search = search or ""
            self._screen = _ALL_SCREENS
            self._fps_choice = _FPS_FROM_FILE
            self._bg = self._bg_names()[0]
            self._reset_state()
            self.reload(preselect, focus_text)
        self._publish_look()
        self._raise()
        return True

    def _raise(self):
        """PAD-251: the scenes are a tab now; opening them brings the Scenes tab forward."""
        self._raise_n += 1
        self.set(open=True, alive=True, raise_n=self._raise_n)
        window = self.window
        try:
            if window.service("scenes") is not None and                     self.store.get("shell", "tab") != "scenes":
                window.select_tab("scenes")
        except Exception:                            # noqa: BLE001
            log.exception("scenes tab")

    @rpc
    def show(self):
        """Bring the scenes forward (the Scenes tab)."""
        if not self._alive:
            return False
        self._raise()
        return True

    @rpc
    def hide(self):
        """Nothing to step aside any more: the scenes are a tab of their own and a jump to
        another tab simply leaves it (nothing is closed or reset)."""
        return True

    @rpc
    def close(self):
        """Close: a bulk save stops (it writes files the user can see), a
        layout dialog is dropped, the preview frames are deleted."""
        if self._bulk is not None:
            self._bulk["cancel"] = True
        if self._vbulk is not None:
            self._vbulk["cancel"] = True
        if self._export is not None:
            self._export["cancel"] = True
        self._live_layout = None
        self._cancel_live_job()
        self._mlay = None
        self._token += 1
        self._alive = False
        self._sel = None
        self._drop_tmp()
        self._reset_state()
        return True

    def _tmpdir(self):
        if self._tmp is None or not os.path.isdir(self._tmp):
            self._tmp = tempfile.mkdtemp(prefix="pad-scenes-")
        return self._tmp

    def _drop_tmp(self):
        tmp, self._tmp = self._tmp, None
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # data
    # ------------------------------------------------------------------
    def reload(self, preselect=None, focus_text=None):
        from ..plugins.stern import scene_render
        try:
            self._scenes = collect_scenes(self.assets_dir)
        except Exception:                            # noqa: BLE001
            self._scenes = {}
        self._layouts = scene_render.load_layouts(self.assets_dir)
        self._tree_reset()
        self._fonts = None
        self._text_changes = None
        self.set(hint=HINT if self._scenes else HINT_EMPTY, card_note="")
        self._refresh_list(preselect, focus_text, jump=True)
        self._auto_trees()
        self._check_card()

    def _project_games(self):
        """The game folder(s) this project's scenes are on (``godzilla_le``), from their
        card paths."""
        return {d.replace("\\", "/").strip("/").split("/")[0].lower()
                for d in self._scenes if d.strip("/")}

    def _check_card(self):
        """DragonRR: the Extract tab can name one game (Godzilla) while the project folder
        holds another's extract (Kong), and nothing said so.  The Extract tab's card is read
        for its title (its .sidx names, milliseconds) off the UI thread; a project of another
        game gets a warning over the preview."""
        card = self.card_image_path()
        games = self._project_games()
        if not card or not os.path.isfile(card) or not games:
            return
        assets = self.assets_dir

        def work():
            try:
                from ..plugins.stern import engine
                names = engine.card_title_index(card)
            except Exception:                        # noqa: BLE001
                names = ()
            titles = {n.lower().rsplit(".", 1)[0].split("-")[0] for n in names}
            try:
                from ..core.extract_source import card_relation
                rel = card_relation(card, assets, measure=True) or {}
            except Exception:                        # noqa: BLE001
                rel = {}
            self.ctx.loop.post(self._card_checked, assets, card, games, titles, rel)

        threading.Thread(target=work, daemon=True, name="scene-card").start()

    def _card_checked(self, assets, card, games, titles, rel=None):
        if assets != self.assets_dir:
            return
        rel = rel or {}
        if (not titles or games & titles) and rel.get("source_name")                 and rel.get("kind") in ("other", "other_build"):
            # PAD-421: the same game, but another card (a custom one over the stock extract)
            self.set(card_note=(
                "This project folder holds the extract of %s, not of %s (the card on the "
                "Extract tab). What you see and edit here is %s's; %s's own pictures "
                "are not in this project. To work on %s, extract it into a new project "
                "folder." % (rel["source_name"], os.path.basename(card), rel["source_name"],
                             os.path.basename(card), os.path.basename(card))))
            return
        if not titles or games & titles:
            return
        self.set(card_note=(
            "This project folder holds the scenes of %s, but the card on the Extract tab is "
            "%s (%s). What you see and edit here is %s's. To work on %s, open its own "
            "project folder (the project menu at the top), or extract that card into a new "
            "one." % (" / ".join(sorted(games)), " / ".join(sorted(titles)),
                      os.path.basename(card), " / ".join(sorted(games)),
                      " / ".join(sorted(titles)))))

    def _auto_trees(self):
        """PAD-251: a project extracted before the scene editor has previews but no
        ``scene_tree.json``, and the window would quietly show the old preview.  When the
        Extract tab's card is there, the trees are read off it now, in the background (the
        same few seconds as Re-read from card); the editor takes over when they land."""
        if self._rebuild is not None or not self._scenes:
            return
        tex = os.path.join(self.assets_dir, "images", "scene_textures")
        upgrade = False
        if os.path.isfile(os.path.join(tex, "scene_tree.json")):
            # a manifest from an older editor (before text flags, say) still draws, a little
            # less like the machine: re-read it quietly when the card is at hand
            if self._tree_version() >= self._tree_version_now():
                return
            upgrade = True
        if not os.path.isfile(os.path.join(tex, "radium_images.txt")):
            return
        card = self.card_image_path()
        if upgrade and (not card or not os.path.isfile(card)):
            return
        if not card or not os.path.isfile(card):
            self.set(rebuild_msg="To edit the scenes, set the Extract tab's Input to this "
                                 "project's card image and press Re-read from card.")
            return
        if self._auto_tried == (self.assets_dir, card):
            return                  # read once already (it failed: its message is showing)
        self._auto_tried = (self.assets_dir, card)
        self.rebuild(quiet="upgrade" if upgrade else True)

    def _tree_version(self):
        trees = self._load_trees() or {}
        for man in trees.values():
            try:
                return int(man.get("v") or 0)
            except (TypeError, ValueError, AttributeError):
                return 0
        return 0

    @staticmethod
    def _tree_version_now():
        from ..plugins.stern import scene_eval
        return scene_eval.MANIFEST_VERSION

    def _scene_states(self):
        """``{scene dir: "edited" | "written"}`` (DragonRR: colour the list by what is not
        written to a card yet and what is)."""
        try:
            from ..plugins.stern import scene_edit
            return {card.replace("\\", "/").rsplit("/", 1)[0]: st
                    for card, st in scene_edit.scene_states(self.assets_dir).items()}
        except Exception:                            # noqa: BLE001
            return {}

    def _restate_list(self):
        """The list's colours again (after an edit, a Reset, a Write), rows unchanged."""
        rows = self.store.get(self.ns, "scenes") or []
        states = self._scene_states()
        new = [dict(r, state=states.get(r["d"], "")) for r in rows]
        if new != rows:
            self.set(scenes=new)

    def _sorted_dirs(self):
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

    def _line_extras(self):
        """The words the scenes' lines show besides the card's own (PAD-468), as
        ``({scene dir: {original: new words}}, {scene dir: [(node, words)]})``: the edits made
        to their lines (on the Text tab or in the Words box) and the lines added in the scene
        editor, so a search finds a line by the words it shows now too."""
        reps = {}
        for path, pairs in (self._load_text_changes() or {}).items():
            p = (path or "").replace("\\", "/")
            if p.lower().endswith(".radium"):
                reps.setdefault(p.rsplit("/", 1)[0], {}).update(pairs)
        added = {}
        try:
            from ..plugins.stern import scene_edit
            for card, ops in scene_edit.load(self.assets_dir).items():
                d = card.replace("\\", "/").rsplit("/", 1)[0]
                for op in ops:
                    if op.get("op") == "add_text" and op.get("id") is not None:
                        added.setdefault(d, []).append((int(op["id"]), op.get("text") or ""))
        except Exception:                            # noqa: BLE001
            pass
        return reps, added

    def _haystack(self, d, extras=None):
        sc = self._scenes[d]
        reps, added = extras if extras is not None else self._line_extras()
        return (sc["label"] + " " + d + " "
                + " ".join(n for n, _p in sc["fonts"].values()) + " "
                + " ".join(sc["texts"]) + " "
                + " ".join((reps.get(d) or {}).values()) + " "
                + " ".join(t for _n, t in added.get(d) or ())).lower()

    def _refresh_list(self, preselect=None, focus_text=None, jump=False):
        q = (self._search or "").strip().lower()
        extras = self._line_extras() if q else None
        # A jump in beats a search left in this window.  Only a jump: typing a search while a
        # scene it does not match was picked used to wipe the search (DragonRR, PAD-429).
        if jump and q and preselect in self._scenes and q not in self._haystack(
                preselect, extras):
            self._search = ""
            q = ""
        rows = []
        states = self._scene_states()
        for d in self._sorted_dirs():
            sc = self._scenes[d]
            if q and q not in self._haystack(d, extras):
                continue
            rows.append({"d": d, "label": sc["label"],
                         "imgs": len(sc["images"]), "fonts": len(sc["fonts"]),
                         "texts": len(sc["texts"]),
                         "vids": len(sc["videos"]),
                         "state": states.get(d, "")})
        self._listed = [r["d"] for r in rows]
        want = preselect if preselect in self._listed else (
            self._listed[0] if self._listed else None)
        self._focus_want = (want, focus_text) if (want and focus_text) \
            else None
        self._find_at = None
        self.set(scenes=rows, search=self._search,
                 sort={"col": self._sort_col, "rev": self._sort_rev})
        if want != self._sel:
            self._drop_live_edit()
        self._sel = want
        self._on_select()
        self._find_sync()

    @rpc
    def set_search(self, q):
        self._search = q or ""
        self._refresh_list(preselect=self._sel)
        return True

    def _find_hits(self):
        """Every match of the search, in the list's order (DragonRR, PAD-429): each line of
        on-screen text the words are in, as ``(scene, line)``, *line* the index of one of the
        scene's own lines or ``("add", node)`` for a line added in the scene editor; a line
        is found by the card's words or the words it shows now.  A scene listed for its name
        or a font only is one match of its own, ``(scene, None)``.

        With nothing typed, every line of text of every scene, in turn (DragonRR, PAD-468:
        proof-read them all without the game); the game program's own strings are not a
        scene's, so they are left to the Text tab."""
        q = (self._search or "").strip().lower()
        reps, added = self._line_extras()
        hits = []
        for d in self._listed:
            sc = self._scenes[d]
            if not q and sc.get("program"):
                continue
            rep = reps.get(d) or {}
            lines = [(d, i) for i, t in enumerate(sc["texts"])
                     if (t or "").strip() and (not q or q in t.lower()
                                               or q in (rep.get(t) or "").lower())]
            lines += [(d, ("add", n)) for n, t in added.get(d) or ()
                      if not q or q in t.lower()]
            hits.extend(lines or ([(d, None)] if q else []))
        return hits

    def _line_of_node(self, node):
        """The line of text (a :meth:`_find_hits` entry) that layer *node* of the scene
        showing draws, or None for a layer that is not a line of text: :meth:`_find_layer`
        the other way round."""
        d = self._sel
        if node is None or d not in self._scenes or self._tman is None \
                or not self.store.get(self.ns, "tree"):
            return None
        from .text_scenes_tree import _walk_man, _kind_of, _text_of
        walk = [n for n, _p, _d in _walk_man(self._tman)]
        n = next((x for x in walk if x["id"] == node), None)
        if n is None or _kind_of(self._tman, n) != "Text":
            return None
        if n.get("added"):
            return (d, ("add", node))
        flat = lambda t: " ".join((t or "").split())             # noqa: E731
        words = flat(_text_of(self._tman, n, "Text"))
        same = [x["id"] for x in walk if flat(_text_of(self._tman, x, _kind_of(self._tman, x)))
                == words]
        lines = [i for i, t in enumerate(self._scenes[d]["texts"]) if flat(t) == words]
        if not words or not lines or node not in same:
            return None
        return (d, lines[min(same.index(node), len(lines) - 1)])

    def _find_sync(self):
        """Say where Previous / Next stand ("3 of 40").  A line of text picked in the scene
        editor is where they go on from (PAD-468): picked by hand, or by a step."""
        hits = self._find_hits()
        here = self._line_of_node(self._tsel)
        if here is not None:
            self._find_at = here if here in hits else None
        pos = hits.index(self._find_at) + 1 if self._find_at in hits else 0
        self.set(find={"pos": pos, "n": len(hits)})

    def _find_follow(self, node):
        """A layer was picked in the scene editor (the mixin's ``tree_select``): a line of text
        picked by hand moves Previous / Next to it; a picture leaves them where they were."""
        if not self._find_stepping and self._line_of_node(node) is not None:
            self._find_sync()

    @rpc
    def find_step(self, delta=1):
        """Previous / Next beside the search (and beside a line's Words): go to the next
        match, the scene and the line of text in it, round from the last to the first.  The
        first press lands on the first match in the scene that is showing."""
        hits = self._find_hits()
        if not hits:
            self.set(find={"pos": 0, "n": 0})
            return False
        step = -1 if int(delta or 1) < 0 else 1
        if self._find_at in hits:
            pos = (hits.index(self._find_at) + step) % len(hits)
        else:
            here = [n for n, h in enumerate(hits) if h[0] == self._sel]
            pos = (here[0] if step > 0 else here[-1]) if here else (0 if step > 0 else -1)
            pos %= len(hits)
        d, line = hits[pos]
        self._find_stepping = True
        try:
            if d != self._sel:
                self.select(d)
            self._find_at = hits[pos]
            self.set(find={"pos": pos + 1, "n": len(hits)})
            if line is None:
                return True
            if isinstance(line, tuple):
                # a line added here is a layer of the scene editor only
                self.set(item=None, thumb="")
                if self.store.get(self.ns, "tree"):
                    self.tree_select(line[1])
                return True
            self.set(item="txt::%d" % line, thumb="")
            self._find_layer(d, line)
        finally:
            self._find_stepping = False
        return True

    def _find_layer(self, d, line):
        """In the scene editor the line is its Text layer: pick it (the n-th layer with these
        words, for a scene that shows the same words more than once)."""
        if not self.store.get(self.ns, "tree") or self._tman is None:
            return
        # the text list has a layer's lines run together ("START TERROR OF +3 SECONDS")
        flat = lambda t: " ".join((t or "").split())             # noqa: E731
        texts = [flat(t) for t in self._scenes[d]["texts"]]
        words = texts[line]
        nth = texts[:line].count(words)
        from .text_scenes_tree import _walk_man, _kind_of, _text_of
        same = [n["id"] for n, _p, _d in _walk_man(self._tman)
                if flat(_text_of(self._tman, n, _kind_of(self._tman, n))) == words]
        if same:
            self.tree_select(same[min(nth, len(same) - 1)])

    @rpc
    def sort_by(self, col):
        """Counts start descending (the big scenes are the ones worth
        finding), names start A-Z; a second click flips."""
        if col not in _SORT_KEYS:
            return False
        if col == self._sort_col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col, self._sort_rev = col, (col != "#0")
        self._refresh_list(preselect=self._sel)
        return True

    @rpc
    def select(self, d):
        if d not in self._scenes:
            return False
        if d != self._sel:
            self._focus_want = None
            self._drop_live_edit()
        self._tree_unselect()
        self._sel = d
        self._on_select()
        if not self._find_stepping and self._find_at and self._find_at[0] != d:
            # another scene picked by hand: Next goes to its first line (PAD-468)
            self._find_at = None
            self._find_sync()
        return True

    def _drop_live_edit(self):
        """Another scene was picked while Move… / Font size… was open: the
        edit was for a line of the previous scene, so it is cancelled (its
        fields sit in this window's side column)."""
        if self.store.get(self.ns, "layout_dialog"):
            self.set(layout_dialog=None)
        self._live_layout = None
        self._cancel_live_job()

    # ------------------------------------------------------------------
    # the contents list
    # ------------------------------------------------------------------
    def _on_select(self):
        from ..plugins.stern import scene_render, text_colors, text_layout
        sel = self._sel
        if not sel or self._scenes.get(sel) is None:
            self._token += 1
            self._preview_full = None
            self._frames_full = []
            self.set(sel=None, contents=None, item=None, thumb="",
                     detail="", frames=[], canvas_msg="", can_save=False,
                     can_video=False, caption="", caption_full="", screens=[],
                     animated=False)
            return
        sc = self._scenes[sel]
        groups = []
        groups.append({"key": "img", "title": "Images (%d)"
                       % len(sc["images"]), "open": True, "items": [
                           {"id": "img::" + rel,
                            "text": os.path.basename(rel),
                            "info": "double-click: show on Images tab"}
                           for _off, rel in sc["images"]]})
        fonts = [{"id": "font::" + table, "text": "%s (%dpx)"
                  % (name or table, px),
                  "info": "double-click: open in Fonts window"}
                 for table, (name, px) in sorted(
                     sc["fonts"].items(), key=lambda kv: kv[1][0].lower())]
        if not sc["fonts"] and sc["texts"]:
            fonts.append({"id": None, "text": "no font — this scene draws "
                          "its letters as images",
                          "info": "see the Images list above"})
        groups.append({"key": "font", "title": "Fonts (%d)"
                       % len(sc["fonts"]), "open": True, "items": fonts})
        stock, picked = self._scene_text_colors(sel)
        card, lay = scene_render.layout_for_scene_dir(self._layouts, sel)
        layouts = self._pending_layouts(card)
        texts = self._pending_texts(card, lay)
        facts = self._scene_text_facts(sel)
        items = []
        for i, s in enumerate(sc["texts"]):
            src = stock.get(s)
            ly = layouts.get(s)
            shown = texts.get(s)
            if src is None:
                info = "double-click: find on Replace Text"
            elif s in picked:
                info = "%s → %s" % (text_colors.to_hex(src),
                                    text_colors.to_hex(picked[s]))
            else:
                info = text_colors.to_hex(src)
            if ly:
                info = "%s · %s" % (info, text_layout.describe(ly))
            if shown is not None:
                info = ('shows: "%s"' % shown
                        + (" · " + info if src is not None else ""))
            if s in picked or ly or shown is not None:
                info += " (not built yet)"
            elif src is not None:
                info += " · right-click to recolour"
            items.append({
                "id": "txt::%d" % i, "text": s, "info": info,
                "picked": s in picked, "has_layout": s in layouts,
                "align": ((ly or {}).get("align")
                          or facts.get(s, (0, None))[1] or ""),
                "swatch": text_colors.to_hex(picked.get(s, src))
                if src is not None else ""})
        groups.append({"key": "txt", "title": "Text (%d)" % len(sc["texts"]),
                       "open": len(sc["texts"]) <= 12, "items": items})
        groups.append({"key": "vid", "title": "Videos (%d)"
                       % len(sc["videos"]), "open": True, "items": [
                           {"id": "vid::" + rel,
                            "text": os.path.basename(rel),
                            "info": "double-click: show on Video tab"}
                           for rel in sc["videos"]]})
        item = None
        if self._focus_want:
            scene, line = self._focus_want
            if scene == sel:
                for it in items:
                    if it["text"] == line:
                        item = it["id"]
                        groups[2]["open"] = True
                        break
            else:
                self._focus_want = None
        self.set(sel=sel, detail=sel, contents={"path": sel,
                                                "groups": groups},
                 item=item, thumb="")
        self._render_preview(sel)

    @rpc
    def select_item(self, iid):
        """A contents row was picked: an image shows as a thumbnail."""
        thumb = ""
        if iid and iid.startswith("img::"):
            rel = iid[5:]
            path = os.path.join(self.assets_dir, *rel.split("/"))
            if os.path.isfile(path):
                thumb = path
        self.set(item=iid, thumb=thumb)
        if iid and iid.startswith("txt::") and self._item_text(iid) is not None:
            # a line picked by hand: Previous / Next go on from it (PAD-468)
            hits = self._find_hits()
            hit = (self._sel, int(iid[5:]))
            if hit in hits:
                self._find_at = hit
                self.set(find={"pos": hits.index(hit) + 1, "n": len(hits)})
        return True

    # ------------------------------------------------------------------
    # pending edits the preview draws
    # ------------------------------------------------------------------
    def _scene_text_colors(self, scene_dir):
        from ..plugins.stern import scene_render, text_colors
        card, layout = scene_render.layout_for_scene_dir(self._layouts,
                                                         scene_dir)
        stock = {}
        for tx in (layout or {}).get("texts") or ():
            stock.setdefault(tx.get("text") or "",
                             text_colors.from_floats(tx.get("rgba") or ()))
        picked = self._pending_colors(card) if card else {}
        return stock, picked

    def _pending_colors(self, card):
        from ..plugins.stern import text_colors
        try:
            return text_colors.colors_for(self.assets_dir, card) if card \
                else {}
        except Exception:                            # noqa: BLE001
            return {}

    def _pending_layouts(self, card):
        from ..plugins.stern import text_layout
        try:
            out = text_layout.layout_for(self.assets_dir, card) if card \
                else {}
        except Exception:                            # noqa: BLE001
            out = {}
        live = self._live_layout
        if live and card and live[0] == card:
            if text_layout.is_neutral(live[2]):
                out.pop(live[1], None)
            else:
                out[live[1]] = dict(live[2])
        return out

    def _load_text_changes(self):
        if self._text_changes is None:
            try:
                from ..core import text_manifest
                self._text_changes = text_manifest.changed(self.assets_dir)
            except Exception:                        # noqa: BLE001
                self._text_changes = {}
        return self._text_changes

    def _pending_texts(self, card, layout=None):
        """``{display string: replacement}`` the preview of *card* draws: its
        own Replace Text rows plus every game-program row whose original the
        scene draws (decoded on both sides).  A scene line reading the same
        but for a closing ``!``, ``.`` or ``?`` is a stand-in for the program
        line too (PAD-485: the jackpot screen's "GIGAN JACKPOT" for the
        game's "GIGAN JACKPOT!").  A program edit wins over the scene's own
        row, as the game writes over the stand-in, and a program line
        reading exactly the same wins over a near one."""
        if not card:
            return {}
        changed = self._load_text_changes()
        if not changed:
            return {}
        out = {}
        for orig, rep in changed.get(card) or ():
            out[orig] = rep
        if layout is None:
            layout = self._layouts.get(card)
        drawn = {tx.get("text") for tx in (layout or {}).get("texts") or ()}
        drawn.discard(None)
        if not drawn:
            return out
        from ..plugins.stern import progtext
        from .text_rules import stand_in_words
        near = {}
        for t in drawn:
            near.setdefault(stand_in_words(t, True), []).append(t)
        near.pop("", None)
        exact, loose = {}, {}
        for path, pairs in changed.items():
            if (path or "").lower().endswith(".radium"):
                continue
            for orig, rep in pairs:
                o = progtext.decode_text(orig)
                if o in drawn:
                    exact[o] = progtext.decode_text(rep)
                else:
                    for t in near.get(stand_in_words(o, True)) or ():
                        loose.setdefault(t, progtext.decode_text(rep))
        out.update(loose)
        out.update(exact)
        return out

    def fonts_changed(self):
        """The Fonts window wrote glyph files: re-read them and redraw."""
        self._fonts = None
        if self._alive and self._sel:
            self._render_preview(self._sel)

    def text_edits_changed(self):
        """The Text tab applied / reverted an edit: re-read and redraw."""
        self._text_changes = None
        if self._alive:
            self._on_select()

    def _scene_text_facts(self, scene_dir):
        from ..plugins.stern import scene_render, text_layout
        _card, layout = scene_render.layout_for_scene_dir(self._layouts,
                                                          scene_dir)
        out = {}
        for tx in (layout or {}).get("texts") or ():
            text = tx.get("text") or ""
            if not text or text in out:
                continue
            try:
                px = int(tx.get("font_px") or 0)
            except (TypeError, ValueError):
                px = 0
            out[text] = (px, text_layout.align_name(tx.get("align", 1)))
        return out

    def _folder_state_written(self):
        cb = self.window.cb.get("on_folder_state_written")
        if cb is not None:
            try:
                cb(self.assets_dir)
            except Exception:                        # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # text colour
    # ------------------------------------------------------------------
    @rpc
    def color_start(self, text):
        """Text colour…: the colour to start the picker on, or None after
        saying why the line can't be recoloured."""
        from ..plugins.stern import scene_render, text_colors
        if not self._sel:
            return None
        card, _lay = scene_render.layout_for_scene_dir(self._layouts,
                                                       self._sel)
        stock, picked = self._scene_text_colors(self._sel)
        src = stock.get(text)
        if card is None or src is None:
            compat.messagebox.showinfo(
                "Text colour",
                "This line's colour isn't in the recorded scene layout, so "
                "there is nothing to change it from.\n\nRun \"Rebuild "
                "previews…\" (or re-extract with Images enabled) and try "
                "again.")
            return None
        return {"text": text, "start": text_colors.to_hex(
            picked.get(text, src)), "stock": text_colors.to_hex(src),
            "title": "Colour for \"%s\"" % text[:40]}

    @rpc
    def set_color(self, text, hex_color=None):
        """Recolour (or, with no colour, restore) one line of the scene."""
        from ..plugins.stern import scene_render, text_colors
        if not self._sel:
            return False
        card, _lay = scene_render.layout_for_scene_dir(self._layouts,
                                                       self._sel)
        stock, _picked = self._scene_text_colors(self._sel)
        src = stock.get(text)
        if card is None or src is None:
            return False
        new = text_colors.parse_hex(hex_color) if hex_color else None
        if hex_color and new is None:
            return False
        try:
            text_colors.set_color(self.assets_dir, card, text, src, new)
        except OSError as e:
            compat.messagebox.showerror("Text colour", str(e))
            return False
        self._folder_state_written()
        self._on_select()
        return True

    @rpc
    def reset_color(self, text):
        return self.set_color(text, None)

    # ------------------------------------------------------------------
    # text layout (move / align / size)
    # ------------------------------------------------------------------
    def _layout_target(self, text, title):
        from ..plugins.stern import scene_render
        if not self._sel:
            return None
        card, _lay = scene_render.layout_for_scene_dir(self._layouts,
                                                       self._sel)
        if card is None or text not in self._scene_text_facts(self._sel):
            compat.messagebox.showinfo(
                title,
                "This line isn't in the recorded scene layout, so there is "
                "nothing to move it from.\n\nRun \"Re-read from card…\" (or "
                "re-extract with Images enabled) and try again.")
            return None
        return card

    def _set_text_layout(self, text, dx=None, dy=None, align=None,
                         size=None):
        from ..plugins.stern import text_layout
        card = self._layout_target(text, "Text layout")
        if card is None:
            return None
        try:
            row = text_layout.set_layout(self.assets_dir, card, text, dx=dx,
                                         dy=dy, align=align, size=size)
        except OSError as e:
            compat.messagebox.showerror("Text layout", str(e))
            return None
        self._folder_state_written()
        self._on_select()
        return row

    @rpc
    def align_text(self, text, name):
        return self._set_text_layout(text, align=name) is not None

    @rpc
    def reset_layout(self, text):
        from ..plugins.stern import scene_render, text_layout
        if not self._sel:
            return False
        card, _lay = scene_render.layout_for_scene_dir(self._layouts,
                                                       self._sel)
        if card is None:
            return False
        try:
            text_layout.reset(self.assets_dir, card, text)
        except OSError as e:
            compat.messagebox.showerror("Text layout", str(e))
            return False
        self._folder_state_written()
        self._on_select()
        return True

    @rpc
    def layout_start(self, text, kind):
        """Move… / Font size…: open the dialog's values, or None after
        saying why the line can't be laid out."""
        from ..plugins.stern import text_layout
        title = "Move" if kind == "move" else "Font size"
        card = self._layout_target(text, title)
        if card is None:
            return None
        px = self._scene_text_facts(self._sel).get(text, (0, None))[0]
        edit = self._pending_layouts(card).get(text) or \
            text_layout.normalize({})
        edit = text_layout.normalize(edit)
        short = text if len(text) <= 40 else text[:39] + "…"
        dlg = {"text": text, "kind": kind, "card": card, "px": int(px or 0),
               "dx": _fmt_num(edit.get("dx")), "dy": _fmt_num(edit.get("dy")),
               "size": int(edit.get("size") or 100),
               "title": ("Move \"%s\"" if kind == "move"
                         else "Font size for \"%s\"") % short}
        self.set(layout_dialog=dlg)
        return dlg

    def _dialog_edit(self, dlg, values):
        """The edit the dialog shows: the pending row with the dialog's
        fields replaced (``_LayoutDialog.current``)."""
        from ..plugins.stern import text_layout
        fields = dict(text_layout.normalize(
            self._stored_layout(dlg["card"], dlg["text"]) or {}))
        keys = ("dx", "dy") if dlg["kind"] == "move" else ("size",)
        for k in keys:
            if k in (values or {}):
                fields[k] = values[k]
        return text_layout.normalize(fields), keys

    def _stored_layout(self, card, text):
        from ..plugins.stern import text_layout
        try:
            return (text_layout.layout_for(self.assets_dir, card) or {}).get(
                text)
        except Exception:                            # noqa: BLE001
            return None

    @rpc
    def layout_preview(self, values):
        """A dialog value changed: draw the scene with it (debounced; the
        file only changes on Apply)."""
        dlg = self.store.get(self.ns, "layout_dialog")
        if not dlg:
            return False
        edit, _keys = self._dialog_edit(dlg, values)
        self._live_layout = (dlg["card"], dlg["text"], dict(edit))
        self._cancel_live_job()
        self._live_job = self.ctx.loop.after(120, self._live_rerender)
        return self._px_text(dlg, edit)

    @staticmethod
    def _px_text(dlg, edit):
        if dlg["kind"] != "size":
            return ""
        pct = edit.get("size") or 100
        if dlg["px"]:
            return "%d px → %d px" % (dlg["px"],
                                      int(round(dlg["px"] * pct / 100.0)))
        return "%d %% of the size this scene draws it at" % pct

    @rpc
    def layout_px(self, values):
        dlg = self.store.get(self.ns, "layout_dialog")
        if not dlg:
            return ""
        edit, _keys = self._dialog_edit(dlg, values)
        return self._px_text(dlg, edit)

    def _cancel_live_job(self):
        job, self._live_job = self._live_job, None
        if job is not None:
            try:
                self.ctx.loop.after_cancel(job)
            except Exception:                        # noqa: BLE001
                pass

    def _live_rerender(self):
        self._live_job = None
        if self._alive and self._sel:
            self._render_preview(self._sel)

    @rpc
    def layout_done(self, values=None):
        """Apply (the dialog's *values*) or Cancel (None)."""
        dlg = self.store.get(self.ns, "layout_dialog")
        self.set(layout_dialog=None)
        self._live_layout = None
        self._cancel_live_job()
        if not dlg:
            return False
        if values is None:
            if self._sel:
                self._render_preview(self._sel)
            return True
        edit, keys = self._dialog_edit(dlg, values)
        out = {}
        for key in keys:
            v = edit.get(key)
            out[key] = (100 if v is None else v) if key == "size" else (v or 0)
        return self._set_text_layout(dlg["text"], **out) is not None

    # ------------------------------------------------------------------
    # fonts
    # ------------------------------------------------------------------
    @rpc
    def blank_font(self, table_key, this_scene_only):
        """Erase every letter of a font so it draws nothing (in this scene
        only, or everywhere it is used)."""
        from ..plugins.stern import fontrender as fr
        if not self._sel:
            return False
        scene_dir = self._sel
        try:
            fonts = fr.load_fonts(self.assets_dir)
        except Exception as e:                       # noqa: BLE001
            compat.messagebox.showerror("Blank font", str(e))
            return False
        font = next((f for f in fonts if f["key"] == table_key), None)
        if font is None:
            compat.messagebox.showinfo(
                "Blank font",
                "This font isn't in the project folder's glyph manifest — "
                "re-extract with Images enabled to edit it.")
            return False
        try:
            used_in = fr.scenes_for_font(self.assets_dir, font)
        except Exception:                            # noqa: BLE001
            used_in = []
        here = [p for p in used_in
                if p.replace("\\", "/").rsplit("/", 1)[0] == scene_dir]
        name = font.get("name") or font["key"]
        if this_scene_only and not here:
            compat.messagebox.showinfo(
                "Blank font",
                "Couldn't work out which scene file this font belongs to, so "
                "blanking it here would blank it everywhere. Use \"everywhere "
                "it is used\" if that is what you want.")
            return False
        where = ("this scene only (it is used in %d)" % len(used_in)
                 if this_scene_only
                 else "all %d scene(s) that use it" % max(1, len(used_in)))
        if not compat.messagebox.askyesno(
                "Blank font",
                "Erase every letter of \"%s\" (%dpx) so it draws nothing, in "
                "%s?\n\nThis is the way to drop an outline or shadow font. "
                "\"Revert font\" in the Fonts window puts the letters back "
                "from the atlas image."
                % (name, font.get("px", 0), where)):
            return False
        try:
            fr.set_font_scope(self.assets_dir, font, here if this_scene_only
                              else None)
            n = fr.clear_font(font)
        except Exception as e:                       # noqa: BLE001
            compat.messagebox.showerror(
                "Blank font", "Couldn't blank \"%s\":\n\n%s" % (name, e))
            return False
        self._fonts = None
        self._render_preview(self._sel)
        fonts = getattr(self.tab, "fonts", None)
        if fonts is not None:
            fonts.reload_if_open()           # an open Fonts window follows
        fn = getattr(self.window.service("images"), "_start_change_scan",
                     None)
        if fn is not None:
            try:
                fn()
            except Exception:                        # noqa: BLE001
                log.exception("images change scan")
        self._set_caption(
            "Blanked %d letter(s) of \"%s\" — %s. Build on the Write tab "
            "to put it on the card." % (n, name, where))
        return True

    # ------------------------------------------------------------------
    # jumps to the other tabs
    # ------------------------------------------------------------------
    @rpc
    def activate(self, iid):
        """The double-click action (and the menu's "Show on…" items)."""
        if not iid or not self._alive:
            return False
        try:
            if iid.startswith("txt::"):
                text = self._item_text(iid)
                if text is None:
                    return False
                self._step_aside_for_jump()
                return bool(self.tab.reveal_text_string(text))
            if iid.startswith("str::"):
                # PAD-384: a Layers row's text, its words carried in the id
                self._step_aside_for_jump()
                return bool(self.tab.reveal_text_string(iid[5:], self._sel))
            if iid.startswith("img::"):
                name, noun, what = "reveal_image_slot", "Images", "tab"
                args, kw = (iid[5:],), {}
            elif iid.startswith("vid::"):
                name, noun, what = "reveal_video_slot", "Video", "tab"
                args, kw = (iid[5:],), {}
            elif iid.startswith("font::"):
                # Tk: open_font_studio(app, assets_dir, preselect=table key)
                return bool(self.tab.fonts.open(self.assets_dir,
                                                preselect=iid[6:]))
            else:
                return False
            fn = getattr(self.window, name, None)
            if fn is None:
                # the same words the Images tab uses for a window not yet
                # moved over
                compat.messagebox.showinfo(
                    noun,
                    "The %s %s has not been moved to this version of the app "
                    "yet. The previous version still has it: start the app "
                    "with PAD_UI=tk set." % (noun, what))
                return False
            self._step_aside_for_jump()
            fn(*args, **kw)
            return True
        except Exception:                            # noqa: BLE001
            log.exception("scenes jump %s", iid)
            return False

    def _step_aside_for_jump(self):
        """Tk ``MainWindow._step_aside_for_jump``: every open tool window
        (this one and the Fonts window) moves out of the way so the tab the
        jump lands on can be seen; nothing is closed or reset."""
        self.hide()
        fonts = getattr(self.tab, "fonts", None)
        if fonts is not None and fonts.is_open():
            fonts.hide()

    def _item_text(self, iid):
        try:
            i = int(iid.split("::", 1)[1])
            return self._scenes[self._sel]["texts"][i]
        except (ValueError, IndexError, KeyError, TypeError):
            return None

    # ------------------------------------------------------------------
    # the preview
    # ------------------------------------------------------------------
    def _bg_rgb(self):
        try:
            from ..plugins.stern import scene_render
            spec = scene_render.background_spec(self._bg)
        except Exception:                            # noqa: BLE001
            spec = (0, 0, 0)
        rgb = spec if isinstance(spec, tuple) else (128, 128, 132)
        return "#%02x%02x%02x" % tuple(rgb[:3])

    def _current_layout(self):
        from ..plugins.stern import scene_render
        if not self._sel:
            return None
        return scene_render.layout_for_scene_dir(self._layouts, self._sel)[1]

    def _screen_index(self, layout):
        from ..plugins.stern import scene_render
        names = scene_render.group_names(layout)
        want = self._screen
        if not want or want == _ALL_SCREENS or want not in names:
            return None
        return names.index(want)

    def _effective_fps(self, layout):
        from ..plugins.stern import scene_render
        choice = self._fps_choice
        if choice and choice != _FPS_FROM_FILE:
            try:
                return float(choice.split()[0])
            except (ValueError, IndexError):
                pass
        return scene_render.frame_rate(layout)

    def _set_caption(self, text, lead=None):
        """One sentence on screen, the whole caption behind the "?"."""
        text = text or ""
        head = (lead or text).split(". ")
        short = head[0] + ("." if len(head) > 1 else "")
        if len(short) > _CAPTION_CHARS:
            short = short[:_CAPTION_CHARS - 1].rstrip() + "…"
        self.set(caption=short, caption_full=text)

    def _render_layout(self, layout, **kw):
        kw.setdefault("view", self._machine_view())
        from ..plugins.stern import scene_render
        return scene_render.render_layout(self.assets_dir, layout, **kw)

    def _render_preview(self, scene_dir):
        """Composite the selected scene on a worker; a token makes stale
        results from fast clicking discard themselves."""
        from ..plugins.stern import scene_render
        self._token += 1
        token = self._token
        self._frames_full = []
        self._preview_full = None
        if self._tree_available(scene_dir):
            # PAD-251: drawn from the scene's tree, as the machine draws it, and editable
            self._preview_dir = scene_dir
            self._set_caption(
                "Drawn from the scene itself, as the machine draws it. Click a picture or a "
                "line of text to select it; drag to move, drag a corner to resize.")
            self._render_tree_preview(scene_dir)
            return
        self._tshown_card = None
        self.set(tree=False, tree_view=None, tree_layers=None, tree_busy=False,
                 tree_loading=False)
        if self._rebuild is not None and self._rebuild.get("quiet") is True:
            self._render_preview_idle()
            return
        card, layout = scene_render.layout_for_scene_dir(self._layouts,
                                                         scene_dir)
        new_scene = scene_dir != self._preview_dir
        if new_scene:
            self._screen = _ALL_SCREENS
        self._preview_dir = scene_dir
        if layout is None:
            self._set_caption(
                "No preview for this scene."
                + ("" if self._layouts else
                   " This project was extracted before previews existed"
                   " — re-extract with Images enabled to get them."))
            self.set(frames=[], canvas_msg="no preview for this scene",
                     can_save=False, can_video=False, screens=[], animated=False)
            return
        self._set_caption("Drawing…")
        # Tk cleared the canvas and wrote "drawing…" on it: a near-black
        # leftover from the previous scene reads as the wrong scene.  A new
        # scene also drops the previous one's screen list.
        self.set(canvas_msg="drawing…", can_save=False, can_video=False, frames=[],
                 animated=False)
        if new_scene:
            self.set(screens=[], screen=_ALL_SCREENS)
        bg = self._bg
        colors = self._pending_colors(card)
        layout_edits = self._pending_layouts(card)
        text_edits = self._pending_texts(card, layout)
        group = self._screen_index(layout)
        tmp = self._tmpdir()

        def work():
            try:
                if self._fonts is None:
                    from ..plugins.stern import fontrender as fr
                    self._fonts = fr.load_fonts(self.assets_dir)
                n = scene_render.frame_count(layout, 0, group)
                frames = []
                for i in range(min(n, _MAX_PREVIEW_FRAMES)):
                    if token != self._token:
                        return
                    frames.append(self._render_layout(
                        layout, fonts=self._fonts, frame=i, background=bg,
                        colors=colors, group=group,
                        layout_edits=layout_edits, text_edits=text_edits))
            except Exception:                        # noqa: BLE001
                log.exception("scene render")
                frames = []
            frames = [f for f in frames if f is not None]
            paths = []
            try:
                from PIL import Image
                for i, f in enumerate(frames):
                    if token != self._token:
                        return
                    shown = f.copy()
                    shown.thumbnail(_DISPLAY_SIZE, Image.LANCZOS)
                    p = os.path.join(tmp, "s%d_%d.png" % (token, i))
                    shown.save(p, compress_level=1)
                    paths.append(p)
            except Exception:                        # noqa: BLE001
                log.exception("scene preview frames")
                paths = []
            self.ctx.loop.post(self._show_preview, token, frames, paths,
                               layout, group)

        threading.Thread(target=work, daemon=True,
                         name="scene-preview").start()

    def _show_preview(self, token, frames, paths, layout, group=None):
        from ..plugins.stern import scene_render
        if token != self._token or not self._alive:
            return
        # the previous render's files are no longer shown
        self._prune_tmp(token)
        note = scene_render.describe(layout, 0, group)
        lead = scene_render.caption_lead(layout, 0, group)
        names = list(scene_render.group_names(layout))
        many = len(names) > 1
        animated = len(frames) > 1
        self.set(screens=([_ALL_SCREENS] + names) if many else [],
                 screen=(_ALL_SCREENS if group is None else names[group])
                 if many else _ALL_SCREENS, animated=animated)
        if not frames:
            self._set_caption(
                "This scene's layout is known but it could not be drawn "
                "(a missing image or font in this project folder).")
            self.set(frames=[], canvas_msg="nothing could be drawn",
                     can_save=False, can_video=False)
            return
        self._preview_full = frames[0]
        self._frames_full = frames
        n_all = scene_render.frame_count(layout, 0, group)
        if len(frames) > 1 and n_all > len(frames):
            note += (" Playing the first %d of them — \"Export picture…\" writes"
                     " all %d to MP4." % (len(frames), n_all))
        self._set_caption(note, lead=lead)
        self.set(frames=paths, canvas_msg="" if paths else
                 "nothing could be drawn", can_save=True, can_video=animated,
                 fps=self._effective_fps(layout))

    def _prune_tmp(self, keep_token):
        tmp = self._tmp
        if not tmp or not os.path.isdir(tmp):
            return
        prefix = "s%d_" % keep_token
        for name in os.listdir(tmp):
            if name.startswith("s") and not name.startswith(prefix):
                try:
                    os.remove(os.path.join(tmp, name))
                except OSError:
                    pass

    @rpc
    def set_screen(self, name):
        self._screen = name or _ALL_SCREENS
        if self._sel:
            self._render_preview(self._sel)
        return True

    @rpc
    def step_screen(self, delta):
        """◀ / ▶: walk the screens, "All screens" first, wrapping."""
        from ..plugins.stern import scene_render
        layout = self._current_layout()
        names = [_ALL_SCREENS] + list(scene_render.group_names(layout))
        if len(names) < 2:
            return False
        try:
            cur = names.index(self._screen)
        except ValueError:
            cur = 0
        self._screen = names[(cur + int(delta)) % len(names)]
        if self._sel:
            self._render_preview(self._sel)
        return True

    @rpc
    def set_fps(self, choice):
        """Speed: restart the animation at the new rate (no re-render)."""
        self._fps_choice = choice if choice in _FPS_CHOICES \
            else _FPS_FROM_FILE
        self.set(fps_choice=self._fps_choice,
                 fps=self._effective_fps(self._current_layout()))
        return True

    @rpc
    def set_bg(self, name):
        """Behind: redraw over another backdrop."""
        if name not in self._bg_names():
            return False
        self._bg = name
        self.set(bg=name, bg_rgb=self._bg_rgb())
        if self._sel:
            self._render_preview(self._sel)
        return True

    # ------------------------------------------------------------------
    # Export picture… / Export all pictures… / Re-read from card…
    # ------------------------------------------------------------------
    def _tree_showing(self):
        """The scene on the canvas is drawn from its tree (the editor), not a layout."""
        if not self._sel or self._tman is None or self._tshown_card is None:
            return False
        return self._tree_available(self._sel)

    @rpc
    def save_preview(self):
        """Write the full-size render out: PNG for a still scene; MP4 (the
        whole scene, re-rendered) or GIF (what is playing) for one that
        moves.  While an MP4 is written the button cancels it.

        PAD-365: a scene drawn from its tree (the editor) exports its whole timeline as an
        MP4 too, drawn as Play shows it, full size."""
        from ..plugins.stern import scene_render
        img = self._preview_full
        if img is None:
            return False
        if self._export is not None:
            self._export["cancel"] = True
            self._set_caption("Stopping the export…")
            self.set(export_msg="Stopping…")
            return True
        frames = [f for f in (self._frames_full or ()) if f is not None]
        tree = self._tree_showing()
        layout = None if tree else self._current_layout()
        group = None if tree else self._screen_index(layout)
        n_all = self._tree_frame_count(self._tman) if tree else \
            scene_render.frame_count(layout, 0, group)
        animated = (n_all > 1) if tree else (len(frames) > 1)
        base = (self._scenes.get(self._sel, {}).get("label")
                if self._sel else "") or "scene"
        safe = _safe_stem(base)
        types = [("PNG image", "*.png")]
        if animated:
            if not tree:
                types.insert(0, ("Animated GIF", "*.gif"))
            types.insert(0, ("MP4 video", "*.mp4"))
        ext = "mp4" if animated else "png"
        path = self.window.ask_save(
            "scene_preview", "Save scene as a video" if animated else "Save scene preview",
            initialfile="%s.%s" % (safe, ext), filetypes=types,
            defaultextension="." + ext)
        if not path:
            return False
        if animated and path.lower().endswith(".mp4"):
            if tree:
                self._export_tree_mp4(path)
            else:
                self._export_mp4(path, layout, group, n_all, self._effective_fps(layout))
            return True
        try:
            if animated and not tree and path.lower().endswith(".gif"):
                fps = self._effective_fps(layout)
                frames[0].save(
                    path, save_all=True, append_images=frames[1:], loop=0,
                    duration=max(20, int(round(1000.0 / max(1.0, fps)))))
            else:
                img.save(path)
        except (OSError, ValueError) as e:
            compat.messagebox.showerror("Save failed", str(e))
            return False
        self._set_caption("Saved %s" % os.path.basename(path))
        self.set(export_msg="Saved %s" % os.path.basename(path))
        return True

    def _export_start(self, path, n_all):
        state = self._export = {"cancel": False}
        self.set(exporting=True)
        msg = "Writing %s — frame 1 of %d…" % (os.path.basename(path), n_all)
        self._set_caption(msg)
        self.set(export_msg=msg)

        def progress(cur):
            if state is not self._export or (cur % 10 and cur != n_all):
                return
            self.ctx.loop.post(self._export_tick, state, path, cur, n_all)
        return state, progress

    def _export_mp4(self, path, layout, group, n_all, fps):
        from ..core import video
        from ..plugins.stern import scene_render
        bg = self._bg
        card, lay = scene_render.layout_for_scene_dir(self._layouts,
                                                      self._preview_dir)
        colors = self._pending_colors(card)
        layout_edits = self._pending_layouts(card)
        text_edits = self._pending_texts(card, lay)
        state, progress = self._export_start(path, n_all)

        def work():
            def render():
                for i in range(n_all):
                    if state["cancel"]:
                        return
                    yield self._render_layout(
                        layout, fonts=self._fonts, frame=i, background=bg,
                        colors=colors, group=group,
                        layout_edits=layout_edits, text_edits=text_edits)
            try:
                n = video.encode_frames_to_mp4(render(), path, fps=fps,
                                               progress=progress)
                err = None
            except Exception as e:                   # noqa: BLE001
                n, err = 0, e
            self.ctx.loop.post(self._export_done, state, path, n, fps, err)

        threading.Thread(target=work, daemon=True,
                         name="scene-mp4").start()

    def _export_tree_mp4(self, path):
        """PAD-365: the scene on the canvas (drawn from its tree), every frame of its timeline,
        full size, as an MP4 at the scene's own rate."""
        from ..core import video
        job = self._tree_video_job(self._tshown_card, self._tman)
        state, progress = self._export_start(path, job["frames"])

        def work():
            try:
                n = video.encode_frames_to_mp4(self._tree_frames(job, state), path,
                                               fps=job["fps"], progress=progress)
                err = None
            except Exception as e:                   # noqa: BLE001
                n, err = 0, e
            self.ctx.loop.post(self._export_done, state, path, n, job["fps"], err)

        threading.Thread(target=work, daemon=True, name="scene-mp4").start()

    def _export_tick(self, state, path, cur, total):
        if state is self._export:
            msg = "Writing %s — frame %d of %d…" % (os.path.basename(path), cur, total)
            self._set_caption(msg)
            self.set(export_msg=msg)

    def _export_done(self, state, path, n, fps, err):
        if state is not self._export:
            return
        self._export = None
        self.set(exporting=False)
        if state["cancel"]:
            try:
                os.remove(path)
            except OSError:
                pass
            msg = "Stopped — %s not written." % os.path.basename(path)
            self._set_caption(msg)
            self.set(export_msg=msg)
            return
        if err is not None or not n:
            self._set_caption("Could not write %s" % os.path.basename(path))
            self.set(export_msg="Could not write %s" % os.path.basename(path))
            compat.messagebox.showerror(
                "Save failed", str(err or "") or "Nothing could be rendered.")
            return
        msg = "Saved %s — %d frame%s at %g fps" % (
            os.path.basename(path), n, "" if n == 1 else "s", fps)
        self._set_caption(msg)
        self.set(export_msg=msg)

    @rpc
    def save_all(self):
        """One PNG per listed scene (the Search narrows the batch) into a
        folder the user picks; while it runs the button cancels."""
        if self._bulk is not None:
            self._bulk["cancel"] = True
            self._set_caption("Stopping…")
            return True
        dirs = [d for d in self._listed if d in self._scenes]
        if not dirs:
            compat.messagebox.showinfo("Export all pictures",
                                       "No scenes are listed to save.")
            return False
        out = self.window.ask_folder(
            "scene_previews", "Save every listed scene preview into…")
        if not out:
            return False
        state = self._bulk = {
            "cancel": False, "out": out, "dirs": dirs, "bg": self._bg,
            "labels": {d: (self._scenes[d].get("label") or d) for d in dirs}}
        self.set(bulk=True)
        self._set_caption("Saving %d scene preview%s…"
                          % (len(dirs), "" if len(dirs) == 1 else "s"))

        def work():
            written, skipped, err = self._save_all_work(state)
            self.ctx.loop.post(self._save_all_done, state, out, written,
                               skipped, err)

        threading.Thread(target=work, daemon=True,
                         name="scene-save-all").start()
        return True

    def _save_all_work(self, state):
        """Worker body (Tk-free): ``(written, skipped, error)``."""
        from ..plugins.stern import scene_render
        dirs, labels = state["dirs"], state["labels"]
        out, bg = state["out"], state["bg"]
        written, skipped, used, err = 0, 0, set(), None
        try:
            if self._fonts is None:
                from ..plugins.stern import fontrender as fr
                self._fonts = fr.load_fonts(self.assets_dir)
            pictures = scene_render.pending_pictures(self.assets_dir)
            sizes = scene_render.picture_sizes(self.assets_dir)
            for i, d in enumerate(dirs):
                if state["cancel"]:
                    break
                card, layout = scene_render.layout_for_scene_dir(
                    self._layouts, d)
                img = None
                tcard, tman = self._tree_card(d)
                if tman is not None:
                    # PAD-251: drawn from the tree, with the scene's edits
                    try:
                        from ..plugins.stern import scene_edit
                        man, _n = scene_edit.apply_manifest(
                            tman, scene_edit.to_apply(self.assets_dir, tcard, tman))
                        img = scene_render.render_tree(
                            self.assets_dir, man, fonts=self._fonts, background=bg,
                            colors=self._pending_colors(tcard),
                            text_edits=self._pending_texts(tcard, None),
                            pictures=pictures, sizes=sizes)
                    except Exception:                # noqa: BLE001
                        img = None
                    layout = None
                if layout is not None:
                    try:
                        img = self._render_layout(
                            layout, fonts=self._fonts, frame=0,
                            background=bg,
                            colors=self._pending_colors(card), group=None,
                            layout_edits=self._pending_layouts(card),
                            text_edits=self._pending_texts(card, layout))
                    except Exception:                # noqa: BLE001
                        img = None
                if img is None:
                    skipped += 1
                else:
                    try:
                        img.save(os.path.join(
                            out, _unique_png(labels[d], used)))
                        written += 1
                    except (OSError, ValueError):
                        skipped += 1
                cur = i + 1
                if not (cur % 5) or cur == len(dirs):
                    self.ctx.loop.post(self._bulk_tick, state, cur,
                                       len(dirs))
        except Exception as e:                       # noqa: BLE001
            err = e
        return written, skipped, err

    def _bulk_tick(self, state, cur, total):
        if state is self._bulk:
            self._set_caption("Saving previews — scene %d of %d…"
                              % (cur, total))

    def _save_all_done(self, state, out, written, skipped, err):
        if state is not self._bulk:
            return
        self._bulk = None
        self.set(bulk=False)
        if err is not None:
            self._set_caption("Could not save the previews.")
            compat.messagebox.showerror("Export all pictures", str(err))
            return
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

    # ------------------------------------------------------------------
    # Export all videos… (PAD-365: "export all the scenes as videos, in one click")
    # ------------------------------------------------------------------
    @rpc
    def save_all_videos(self):
        """One MP4 per listed scene that moves (every frame, at the scene's own rate) and a
        PNG of each still one, into a folder the user picks; while it runs the button
        cancels.  Drawn as the Scenes tab draws them: the edits, the preview eyes, the
        backdrop and the Machine screen included."""
        from ..core import video
        from ..plugins.stern import scene_render
        if self._vbulk is not None:
            self._vbulk["cancel"] = True
            self._set_caption("Stopping…")
            self.set(export_msg="Stopping…")
            return True
        dirs = [d for d in self._listed if d in self._scenes]
        if not dirs:
            compat.messagebox.showinfo("Export all videos",
                                       "No scenes are listed to save.")
            return False
        if not video.find_ffmpeg():
            compat.messagebox.showerror(
                "Export all videos",
                "ffmpeg is needed to write an MP4 and it isn't installed here. "
                "Install ffmpeg and try again.")
            return False
        out = self.window.ask_folder(
            "scene_videos", "Save a video of every listed scene into…")
        if not out:
            return False
        # gathered here, on the UI thread: the worker never reads the editor's state
        jobs = []
        for d in dirs:
            label = self._scenes[d].get("label") or d
            tcard, tman = self._tree_card(d)
            if tman is not None:
                jobs.append({"dir": d, "label": label, "tree": True, "card": tcard,
                             "stock": tman, "hidden": set(self._tree_view_hidden(tcard)),
                             "unveil": set(self._tree_hidden(tcard)),
                             "pins": dict(self._tpins.get(tcard) or {}),
                             "text_edits": self._pending_texts(tcard, None),
                             "colors": self._pending_colors(tcard)})
                continue
            card, layout = scene_render.layout_for_scene_dir(self._layouts, d)
            jobs.append({"dir": d, "label": label, "tree": False, "card": card,
                         "layout": layout,
                         "colors": self._pending_colors(card) if layout else None,
                         "layout_edits": self._pending_layouts(card) if layout else None,
                         "text_edits": self._pending_texts(card, layout) if layout else None})
        state = self._vbulk = {
            "cancel": False, "out": out, "jobs": jobs, "bg": self._bg,
            "view": self._machine_view(), "as_made": self._as_made(),
            "pictures": self._tree_pictures(), "sizes": self._tree_sizes()}
        self.set(bulk_video=True)
        msg = "Writing videos — scene 1 of %d…" % len(jobs)
        self._set_caption(msg)
        self.set(export_msg=msg)

        def work():
            videos, stills, skipped, err = self._save_all_videos_work(state)
            self.ctx.loop.post(self._save_all_videos_done, state, out, videos, stills,
                               skipped, err)

        threading.Thread(target=work, daemon=True, name="scene-save-videos").start()
        return True

    def _save_all_videos_work(self, state):
        """Worker body: ``(videos, stills, skipped, error)``."""
        from ..core import video
        from ..plugins.stern import scene_edit, scene_render
        jobs, out, bg = state["jobs"], state["out"], state["bg"]
        videos, stills, skipped, used, err = 0, 0, 0, set(), None
        total = len(jobs)
        try:
            if self._fonts is None:
                from ..plugins.stern import fontrender as fr
                self._fonts = fr.load_fonts(self.assets_dir)
            for i, j in enumerate(jobs):
                if state["cancel"]:
                    break
                cur = i + 1
                self.ctx.loop.post(self._vbulk_tick, state, cur, total, 0, 0)

                def tick(f, n, _cur=cur):
                    if f % 10 == 0 or f == n:
                        self.ctx.loop.post(self._vbulk_tick, state, _cur, total, f, n)
                frames, n_all, fps = None, 0, 30.0
                try:
                    if j["tree"]:
                        man, _notes = scene_edit.apply_manifest(
                            j["stock"], scene_edit.to_apply(self.assets_dir, j["card"],
                                                            j["stock"]))
                        tj = {"man": man, "pins": j["pins"],
                              "frames": self._tree_frame_count(man),
                              "fps": self._tree_fps(man), "bg": bg,
                              "unveil": j["unveil"], "hidden": j["hidden"],
                              "text_edits": j["text_edits"], "colors": j["colors"],
                              "pictures": state["pictures"], "sizes": state["sizes"],
                              "view": state["view"], "as_made": state["as_made"],
                              "assets": self.assets_dir, "cache": self._tcache}
                        n_all, fps = tj["frames"], tj["fps"]
                        frames = self._tree_frames(tj, state, lambda f, _n=n_all: tick(f, _n))
                    elif j["layout"] is not None:
                        layout = j["layout"]
                        n_all = scene_render.frame_count(layout, 0, None)
                        fps = scene_render.frame_rate(layout)

                        def render(_j=j, _layout=layout, _n=n_all):
                            for f in range(_n):
                                if state["cancel"]:
                                    return
                                tick(f + 1, _n)
                                yield self._render_layout(
                                    _layout, fonts=self._fonts, frame=f, background=bg,
                                    colors=_j["colors"], group=None,
                                    layout_edits=_j["layout_edits"],
                                    text_edits=_j["text_edits"])
                        frames = render()
                except Exception:                    # noqa: BLE001
                    log.exception("scene video job")
                    frames = None
                if frames is None:
                    skipped += 1
                    continue
                try:
                    if n_all > 1:
                        path = os.path.join(out, _unique_name(j["label"], used, "mp4"))
                        n = video.encode_frames_to_mp4(frames, path, fps=fps)
                        if state["cancel"]:
                            try:
                                os.remove(path)
                            except OSError:
                                pass
                            break
                        if n:
                            videos += 1
                        else:
                            skipped += 1
                    else:
                        img = next(iter(frames), None)
                        if img is None:
                            skipped += 1
                        else:
                            img.save(os.path.join(out, _unique_name(j["label"], used, "png")))
                            stills += 1
                except Exception as e:               # noqa: BLE001
                    if state["cancel"]:
                        break
                    if isinstance(e, RuntimeError) and "ffmpeg" in str(e).lower():
                        raise
                    log.exception("scene video")
                    skipped += 1
        except Exception as e:                       # noqa: BLE001
            err = e
        return videos, stills, skipped, err

    def _vbulk_tick(self, state, cur, total, frame, frames):
        if state is not self._vbulk:
            return
        msg = "Writing videos — scene %d of %d" % (cur, total)
        if frame and frames:
            msg += ", frame %d of %d" % (frame, frames)
        msg += "…"
        self._set_caption(msg)
        self.set(export_msg=msg)

    def _save_all_videos_done(self, state, out, videos, stills, skipped, err):
        if state is not self._vbulk:
            return
        self._vbulk = None
        self.set(bulk_video=False)
        if err is not None:
            self._set_caption("Could not save the videos.")
            self.set(export_msg="Could not save the videos.")
            compat.messagebox.showerror("Export all videos", str(err))
            return
        tail = ("" if not skipped
                else "  %d scene%s could not be drawn." % (
                    skipped, "" if skipped == 1 else "s"))
        count = "%d video%s" % (videos, "" if videos == 1 else "s")
        if stills:
            count += " and %d still%s (PNG)" % (stills, "" if stills == 1 else "s")
        if state["cancel"]:
            msg = "Stopped — %s written.%s" % (count, tail)
        else:
            msg = "Saved %s to %s.%s" % (
                count, os.path.basename(out.rstrip("/\\")) or out, tail)
        self._set_caption(msg)
        self.set(export_msg=msg)

    def card_image_path(self):
        """The Extract tab's Input: the card this project came from."""
        var = getattr(self.window, "extract_input_var", None)
        try:
            return (var.get() or "").strip() if var is not None else ""
        except Exception:                            # noqa: BLE001
            return ""

    @rpc
    def rebuild(self, quiet=False):
        """Re-read from card…: re-read the scene layouts off the card image
        (a few seconds, one file rewritten); while it runs it cancels.
        *quiet* (the window's own first run, :meth:`_auto_trees`) says what happened in the
        window instead of a message box."""
        if self._rebuild is not None:
            self._rebuild["cancel"] = True
            self.set(rebuild_msg="Stopping…")
            return True
        card = self.card_image_path()
        if not card or not os.path.isfile(card):
            compat.messagebox.showinfo(
                "Re-read from card",
                "Set the Extract tab's Input to the card image this project "
                "folder was extracted from — the scene layouts are read back "
                "off the card.")
            return False
        card = self._project_card(card, quiet)
        if not card:
            return False
        state = self._rebuild = {"cancel": False, "quiet": quiet or False}
        self.set(rebuilding=True, rebuild_msg=(
            "Re-reading the scenes for the latest editor…" if quiet == "upgrade"
            else "" if quiet else "Reading the card…"))
        if quiet is True:
            # the page shows this in place of the preview until the editor can take over
            self.set(preparing={"cur": 0, "total": 0})
            self._render_preview_idle()
        assets = self.assets_dir

        def progress(cur, total, _d=""):
            if state is not self._rebuild or (cur % 10 and cur + 1 != total):
                return
            self.ctx.loop.post(self._rebuild_tick, state, cur + 1, total)

        def work():
            from ..plugins.stern import engine
            msgs = []
            try:
                n = engine.rebuild_scene_layouts_from_card(
                    card, assets,
                    log=lambda m, lvl="info": msgs.append((m, lvl)),
                    progress=progress, cancel=lambda: state["cancel"])
                err = None
            except Exception as e:                   # noqa: BLE001
                n, err = 0, e
            self.ctx.loop.post(self._rebuild_done, state, n, err, msgs)

        threading.Thread(target=work, daemon=True,
                         name="scene-rebuild").start()
        return True

    def _project_card(self, card, quiet):
        """PAD-421: the card to re-read, or ``""`` to stop.  A scene re-read has to come off
        the card this project was extracted from: the project's picture list names where
        each picture sits in THAT card's scenes, and a card built since (or another card
        altogether) lays them out differently, so every such scene came back empty
        (DragonRR's 1.96 card over the stock card's extract).  A card built from this
        project reads its source card without asking; another card asks first; with the
        source card gone, a built card is read as it is (the engine refuses scenes that do
        not line up) and another card is refused with the reason."""
        from ..core.extract_source import card_relation
        try:
            rel = card_relation(card, self.assets_dir)
        except Exception:                            # noqa: BLE001
            rel = None
        kind = (rel or {}).get("kind")
        if kind not in ("build", "other", "other_build") or not rel.get("source_name"):
            return card
        name, src = os.path.basename(card), rel.get("source") or ""
        if kind == "build":
            return src or card
        if src:
            if quiet or compat.messagebox.askyesno(
                    "Re-read from card",
                    "This project folder was extracted from %s, not from %s (the card picked "
                    "on the Select card tab). The project's pictures are laid out for %s's "
                    "scenes, so reading %s's would leave them empty.\n\nRe-read the scenes "
                    "from %s, the card this project came from?" % (
                        rel["source_name"], name, rel["source_name"], name,
                        rel["source_name"])):
                return src
            return ""
        msg = ("This project folder was extracted from %s, not from %s (the card picked on "
               "the Select card tab), and %s is no longer where it was. Pick %s on the Select "
               "card tab to re-read the scenes." % (
                   rel["source_name"], name, rel["source_name"], rel["source_name"]))
        if quiet:
            self.set(rebuild_msg=msg)
        else:
            compat.messagebox.showwarning("Re-read from card", msg)
        return ""

    def _rebuild_tick(self, state, cur, total):
        if state is not self._rebuild:
            return
        if state.get("quiet") is True:
            self.set(preparing={"cur": cur, "total": total})
        else:
            self.set(rebuild_msg="Scene %d of %d…" % (cur, total))

    def _render_preview_idle(self):
        """While the editor is being prepared nothing is drawn the old way: the page shows
        the preparation instead of a preview that is about to be replaced."""
        self._token += 1
        self._frames_full = []
        self._preview_full = None
        self.set(frames=[], canvas_msg="", can_save=False, animated=False)

    def _rebuild_done(self, state, n, err, msgs):
        if state is not self._rebuild:
            return
        self._rebuild = None
        self.set(rebuilding=False, preparing=None)
        failed = state["cancel"] or err is not None or not n
        if state.get("quiet") and failed and self._alive and self._sel:
            self._render_preview(self._sel)          # the preview it held back
        if state["cancel"]:
            self.set(rebuild_msg="Stopped — layouts unchanged.")
            return
        if err is not None or not n:
            why = next((m for m, lvl in msgs if lvl == "warning"), None)
            self.set(rebuild_msg="Could not rebuild.")
            if state.get("quiet"):
                self.set(rebuild_msg="The scenes could not be read off the Extract tab's "
                                     "card: " + (why or str(err or "") or "no scenes found"))
                return
            compat.messagebox.showwarning(
                "Re-read from card", why or str(err or "")
                or "No scene layouts could be read from that card image.")
            return
        self.set(rebuild_msg="" if state.get("quiet") else "Rebuilt %d scene layout(s)." % n)
        if self._alive:
            self.reload(self._sel)


def _fmt_num(f):
    """A float for a number box: ``10.0`` shows as ``10``."""
    try:
        return "%g" % float(f or 0)
    except (TypeError, ValueError):
        return "0"
