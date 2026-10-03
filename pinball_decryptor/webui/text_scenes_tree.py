"""The Scenes window's scene EDITOR (PAD-251): a scene drawn from its tree, edited on the canvas.

When the project has a scene's tree (``scene_tree.json``, written by Extract and Rebuild
previews) the window draws that scene as the machine does (:mod:`plugins.stern.scene_eval`,
:func:`scene_render.render_tree`) at one MOMENT - a frame of its timeline, and the state the
game's code would seek each labelled sprite to - and lets the user select any picture or line
of text on the canvas and move, resize, tint, hide, re-layer or remove it, or add a picture or
a line of text.  Every edit is an operation in ``scene_edits.json`` (:mod:`scene_edit`), drawn
at once and written to the card by the Write.

The page's half is ``TreeCanvas`` / ``TreeSide`` / ``TreeLayers`` in
``static/js/tabs/text_scenes.js``; this mixin is :class:`TextScenesService`'s.
"""

import json
import logging
import math
import os
import re
import threading

from . import compat
from .rpc import rpc

log = logging.getLogger(__name__)

_TREE_DISPLAY = (1360, 768)          # the canvas image is drawn full size: it is edited on
_ORDER = ("up", "down", "front", "back")


#: a sprite state that is on its way in or out (tree_show tries these last)
_PASSING = re.compile(r"fade|intro|reveal|enter|appear|slide|out|exit|leave", re.I)


class TreeEditMixin:
    """Mixed into ``TextScenesService``; uses its ``assets_dir``, ``_sel``, ``set``,
    ``ctx``, ``_tmpdir``, ``_bg``, ``_fonts``, ``_pending_texts``, ``_folder_state_written``."""

    # ------------------------------------------------------------------
    # data
    # ------------------------------------------------------------------
    def _tree_init(self):
        self._trees = None           # {card path: manifest} (lazy)
        self._tframe = {}            # card -> root frame shown
        self._tpins = {}             # card -> {node id: frame}
        self._tsel = None            # selected node id (the last one picked)
        self._tsels = []             # every selected node, in the order picked (PAD-279)
        self._tanchor = None         # where a Shift-click range in Layers starts
        self._tpeek = None           # a selected layer the game is not drawing now, drawn on top
        self._tforce = {}            # {card: node ids turned on in the preview only} (PAD-276)
        self._tview = {}             # (project, card) -> node ids hidden in the preview only
        self._tsolo = {}             # (project, card) -> (node shown alone, eyes, ons) before
        self._tstate_off = set()     # layers off only because of a switchable part's pick
        self._teye_off = set()       # ... and not turned on in the preview by their eye
        self._thead = set()          # ... the looks themselves, not what sits inside them
        self._tpart_off = set()      # layers inside a look that is off (their eye is their own)
        self._tdraws = []            # the draw list of the last render
        self._tworlds = {}
        self._tlit = {}              # what is drawn without a peek (the game's + the eyes')
        self._tparents = {}
        self._tman = None
        self._tonce = []             # notes for the next picture only (tree_show)
        self._ttoken = 0
        self._tdefault = {}          # card -> the stock scene's resting frame (costly to find)
        self._tcache = {}            # pictures read for the renders, kept while unchanged
        self._tlock = threading.Lock()
        self._tjob = None            # the newest render asked for (the worker takes it)
        self._trunning = False       # the render worker is up
        self._trev = 0               # bumped by every edit: the page knows when an image is new
        self._tshown_card = None     # the scene whose picture the canvas shows
        self._tplay = None           # the playback being drawn: {"cancel": bool, ...}
        self._tlive = {}             # card -> (push result, "HH:MM:SS") handed to a running game
        self._tlive_job = None
        self._tlive_lock = threading.Lock()
        self._thist = {}             # (project, card) -> undo / redo lists of whole op lists

    def _tree_reset(self):
        self._trees = None
        self._tdefault = {}
        self._tcache = {}
        self._tshown_card = None

    def _load_trees(self):
        if self._trees is None:
            path = os.path.join(self.assets_dir, "images", "scene_textures",
                                "scene_tree.json")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._trees = json.load(f)
            except (OSError, ValueError):
                self._trees = {}
        return self._trees

    def _tree_card(self, scene_dir=None):
        """``(card path, stock manifest)`` of the scene in *scene_dir* (default: selected)."""
        want = (scene_dir or self._sel or "").replace("\\", "/").rstrip("/")
        if not want:
            return None, None
        for card, man in self._load_trees().items():
            if card.replace("\\", "/").rsplit("/", 1)[0] == want:
                if scene_dir is None and self._tree_hist(card) is None:
                    self._tree_track(card)
                return card, man
        return None, None

    # -- undo / redo (PAD-283) ---------------------------------------------
    # Every change to a scene's op list is one step, whatever made it (a drag, Draw 1:1, Show,
    # As shipped, a new tint), so Undo puts back the list as it was and Redo the one it undid.
    def _tree_hist(self, card):
        return self._thist.get((self.assets_dir, card))

    def _tree_track(self, card):
        """Note *card*'s op list; a change since it was last noted becomes an undo step."""
        ops = self._tree_ops(card)
        h = self._tree_hist(card)
        if h is None:
            self._thist[(self.assets_dir, card)] = {"now": ops, "undo": [], "redo": []}
        elif ops != h["now"]:
            h["undo"].append(h["now"])
            del h["undo"][:-self._UNDO_STEPS]
            h["redo"] = []
            h["now"] = ops
        return self._tree_hist(card)

    #: undo steps kept per scene
    _UNDO_STEPS = 200

    def _tree_ops(self, card):
        from ..plugins.stern import scene_edit
        return scene_edit.ops_for(self.assets_dir, card)

    def _tree_edited(self, card, man):
        from ..plugins.stern import scene_edit
        edited, notes = scene_edit.apply_manifest(man, self._tree_ops(card))
        return edited, notes

    def _tree_default(self, card):
        """The stock scene's resting frame (:func:`scene_eval.default_frame` draws every frame
        where something changes, so it is found once per scene)."""
        from ..plugins.stern import scene_eval
        if card not in self._tdefault:
            stock = self._load_trees().get(card)
            self._tdefault[card] = scene_eval.default_frame(stock) if stock else 1
        return self._tdefault[card]

    def _tree_frame(self, card, man):
        if card not in self._tframe:
            self._tframe[card] = self._tree_default(card)
        return self._tframe[card]

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------
    def _tree_available(self, scene_dir):
        return self._tree_card(scene_dir)[0] is not None

    def _render_tree_preview(self, scene_dir, quiet=False):
        """Draw the scene (and the selected node's layers) on the render worker.  The picture
        on the canvas stays until the new one is ready - an edit never blanks it; the page
        shows it is updating (``tree_busy``), or, for a scene not drawn yet, that it is being
        drawn (``tree_loading``).  *quiet*: only the selection's layers change."""
        from ..plugins.stern import scene_eval
        card, stock = self._tree_card(scene_dir)
        if not quiet:
            self._play_stop()
        self._ttoken += 1
        token = self._ttoken
        man, notes = self._tree_edited(card, stock)
        frame = self._tree_frame(card, stock)
        pins = dict(self._tpins.get(card) or {})
        worlds = {}
        self._tparents = {n["id"]: (par["id"] if par else None)
                          for n, par, _d in _walk_man(man)}
        peek = self._tpeek if self._tpeek is not None and self._tpeek == self._tsel else None
        force = self._tree_force_set(card, peek)
        # the sprites a peek sits in are only its way in: drawing them whole showed every
        # other layer in them (DragonRR, PAD-284)
        through = self._tree_ancestors(peek) - self._tree_force_set(card) if peek else set()
        # the game's eye (red) never changes the preview: a layer hidden in the game is drawn
        # as the game would without it; the preview's own eye (blue) hides it here (DragonRR,
        # PAD-293).  A picked sprite shows every layer in it, those hidden with the preview's
        # eye too, and a picked layer is seen through the sprites it sits in; the eyes are not
        # changed (DragonRR, PAD-286, PAD-289)
        unveil = self._tree_hidden(card)
        view = self._tree_view_hidden(card)
        if peek is not None:
            gone = view - {peek} - self._tree_inside(peek, view) - self._tree_ancestors(peek)
        else:
            gone = view
        draws = scene_eval.draw_list(man, frame, pins=pins, worlds=worlds, show=peek,
                                     force=force, through=through, unveil=unveil,
                                     hidden=gone)
        self._fit_kept(draws, worlds)
        # what the eyes show: a layer the eye turned on is on, even though the plain draw has
        # it off (DragonRR, PAD-280: the eyes stayed crossed); a peek is only while selected
        mine = self._tree_force_set(card) if peek is not None else force
        if peek is None:
            lit = worlds
        else:
            lit = {}
            scene_eval.draw_list(man, frame, pins=pins, worlds=lit, force=mine,
                                 unveil=unveil, hidden=view)
        # only a look itself has the eye that turns it on; what sits inside it keeps its own
        # eye (DragonRR, PAD-285: "as Fusion would")
        self._tstate_off, self._thead = self._state_off(man, lit)
        self._teye_off = (self._tstate_off & self._thead) - set(lit)
        self._tpart_off = self._tstate_off - self._thead - set(lit)
        self._tlit = lit
        self._tdraws, self._tworlds, self._tman = draws, worlds, man
        new_scene = card != self._tshown_card
        state = {"tree": True, "animated": False, "screens": []}
        if new_scene:
            state.update(frames=[], tree_layers=None, tree_loading=True, tree_busy=False,
                         can_save=False, canvas_msg="")
        elif not quiet:
            state.update(tree_busy=True)
        self.set(**state)
        once, self._tonce = self._tonce, []
        self._tree_publish(card, man, frame, list(notes) + once)
        self.set(pic_note=self._missing_note(draws))
        sels = self._tree_sels()
        sel = sels[0] if len(sels) == 1 else ",".join(str(n) for n in sels) or None
        split = self._tree_split(draws, sels) if sels else set()
        job = {"token": token, "rev": self._trev, "card": card, "man": man, "frame": frame,
               "pins": pins, "draws": draws, "bg": self._bg, "sel": sel if split else None,
               "view": self._machine_view(), "as_made": self._as_made(),
               "split": split, "text_edits": self._pending_texts(card, None),
               "colors": self._pending_colors(card), "tmp": self._tmpdir(),
               "cache": self._tcache, "assets": self.assets_dir,
               "pictures": self._tree_pictures(), "sizes": self._tree_sizes()}
        with self._tlock:
            self._tjob = job
            start = not self._trunning
            self._trunning = True
        if start:
            threading.Thread(target=self._tree_worker, daemon=True, name="scene-tree").start()

    def _tree_ancestors(self, nid):
        """The sprites *nid* sits in, up to the root."""
        out, p, hops = set(), self._tparents.get(nid), 0
        while p is not None and hops < 256:
            out.add(p)
            p, hops = self._tparents.get(p), hops + 1
        return out

    def _tree_hidden(self, card):
        """The nodes hidden in the game (Write leaves them out; their row's card mark)."""
        return {op.get("node") for op in self._tree_ops(card) if op["op"] == "visible"}

    def _tree_view_hidden(self, card):
        """The nodes hidden in the preview with their eye (the card is not changed).  As in
        Photoshop or Fusion the eye is the view only; hiding in the game is its own mark (a
        struck-through row, like Fusion's Suppress).  A scene opened for the first time starts
        with its eyes shut on what the game hides; after that the two are apart until the
        scene is reset (DragonRR, PAD-293)."""
        key = (self.assets_dir, card)
        if key not in self._tview:
            self._tview[key] = set(self._tree_hidden(card))
        return self._tview[key]

    def _tree_view_reset(self, card=None):
        """The preview's eyes back to the game's: for *card*, or every scene."""
        for store in (self._tview, self._tsolo):
            for key in [k for k in store
                        if k[0] == self.assets_dir and (card is None or k[1] == card)]:
                del store[key]
        for c in [c for c in self._tforce if card is None or c == card]:
            del self._tforce[c]

    def _tree_inside(self, nid, nodes):
        """Those of *nodes* that sit inside *nid*, however deep."""
        return {n for n in nodes if nid in self._tree_ancestors(n)}

    def _tree_hidden_in(self, man, nid, hidden):
        """The name of the nearest sprite *nid* sits in that is one of *hidden*, or ""."""
        p, hops = self._tparents.get(nid), 0
        while p is not None and hops < 256:
            if p in hidden:
                got = [n for n, _par, _d in _walk_man(man) if n["id"] == p]
                return got[0]["name"] if got else ""
            p, hops = self._tparents.get(p), hops + 1
        return ""

    def _tree_force_set(self, card, peek=None):
        """The layers turned on in the preview, and a selected layer that is off only because
        of a switchable part's pick with the sprites it sits in: a picture inside a sprite that
        is off has to have that sprite on to be seen while it is selected.  A selected layer
        inside a sprite hidden with its eye is seen through it too (DragonRR, PAD-286: "it
        should override and show"; it said the game never draws it).  A layer turned on by its
        eye does not turn on the part it sits in: it shows when that part is on, as in an
        editor's layers (DragonRR, PAD-285: "only if the head of that tree is made
        visible").  What counts as hidden here is the preview's eye (PAD-293)."""
        hidden = self._tree_view_hidden(card)
        out = set(self._tforce.get(card) or ())
        veiled = self._tree_ancestors(peek) & hidden if peek is not None else set()
        if peek is not None and (peek in self._tstate_off or veiled):
            p, hops = peek, 0
            while p is not None and hops < 256:
                out.add(p)
                p, hops = self._tparents.get(p), hops + 1
        return out - (hidden - veiled)

    def _state_off(self, man, worlds):
        """``(off, heads)``: the layers the game is not drawing at this moment only because a
        switchable part (a sprite the game's code picks a look of: the energy meter's Level
        0..6) shows another of its looks - there at every moment, unlike a layer the timeline
        has not reached (DragonRR, PAD-276: "PAD is choosing, not the game") - and of those,
        the looks themselves (the heads); the rest sit inside a look that is off."""
        from ..plugins.stern import scene_eval
        seek = {nid for nid, _p, _l, _f in scene_eval.seekable(man)}
        out, heads = set(), set()
        for n, par, _d in _walk_man(man):
            if n["id"] in worlds or par is None:
                continue
            if par["id"] in worlds:
                if par["id"] in seek and any(v for _f, v in n["kf"]):
                    out.add(n["id"])
                    heads.add(n["id"])
            elif par["id"] in out:
                out.add(n["id"])
        return out, heads

    @rpc
    def tree_force(self, node, on):
        """Turn a layer that is off only because of a switchable part's pick on (or back off)
        in the preview, where it sits in the layers; the card is not changed."""
        card, _man = self._tree_card()
        if card is None:
            return False
        node = int(node)
        self._tsolo.pop((self.assets_dir, card), None)     # an eye click ends a solo
        got = self._tforce.setdefault(card, set())
        if on:
            got.add(node)
        else:
            got.discard(node)
        self._render_tree_preview(self._sel)
        return True

    @rpc
    def tree_view(self, node, on):
        """A layer's eye (DragonRR, PAD-293): hide it in the preview, or show it again,
        without changing the card.  A layer off only because of a switchable part's pick is
        turned on (or back off) with :meth:`tree_force`."""
        return self.tree_view_many([node], on)

    @rpc
    def tree_view_solo(self, node):
        """Alt+click on an eye, as in Photoshop: the preview shows that layer alone (with
        the sprites it sits in and what is inside it); Alt+click it again and every eye is
        as it was.  Alt+click on another layer's eye moves the solo there.  The card is not
        changed."""
        card, man = self._tree_card()
        if card is None or self._tman is None:
            return False
        node = int(node)
        key = (self.assets_dir, card)
        got = self._tsolo.get(key)
        if got is not None and got[0] == node:
            del self._tsolo[key]
            self._tview[key] = set(got[1])
            self._tforce[card] = set(got[2])
        else:
            if got is None:
                got = (None, set(self._tree_view_hidden(card)),
                       set(self._tforce.get(card) or ()))
            self._tsolo[key] = (node, got[1], got[2])
            chain = {node} | self._tree_ancestors(node)
            everything = {n["id"] for n, _p, _d in _walk_man(self._tman)}
            keep = chain | self._tree_inside(node, everything)
            self._tview[key] = everything - keep
            self._tforce[card] = set(got[2]) | (chain & self._tstate_off)
        self._render_tree_preview(self._sel)
        return True

    @rpc
    def tree_view_many(self, nodes, on):
        card, _man = self._tree_card()
        if card is None:
            return False
        view = self._tree_view_hidden(card)
        self._tsolo.pop((self.assets_dir, card), None)     # an eye click ends a solo
        for node in self._tree_nodes(nodes):
            if on:
                view.discard(node)
            else:
                view.add(node)
        self._render_tree_preview(self._sel)
        return True

    @rpc
    def tree_view_reset(self):
        """The preview's eyes back to the game's for this scene (the card is not changed)."""
        card, _man = self._tree_card()
        if card is None:
            return False
        self._tree_view_reset(card)
        self._render_tree_preview(self._sel)
        return True

    def _missing_note(self, draws):
        """DragonRR's missing background: pictures the scene draws that this project folder
        does not have (an extract without Images) are left out of the preview - say so."""
        picks = self._tree_pictures()
        missing = set()
        for d in draws:
            rel = d.get("image") if d["kind"] in ("bitmap", "flip") else None
            if not rel or (picks.get(rel) or {}).get("path"):
                continue
            if not os.path.isfile(os.path.join(self.assets_dir, "images", *rel.split("/"))):
                missing.add(rel)
        if not missing:
            return ""
        n = len(missing)
        return ("%d picture%s this scene draws %s not in this project folder, so the preview "
                "leaves %s out (a background can be one of them). Extract the card again with "
                "Images ticked on the Extract tab to see %s." % (
                    n, "" if n == 1 else "s", "is" if n == 1 else "are",
                    "it" if n == 1 else "them", "it" if n == 1 else "them"))

    def _tree_pictures(self):
        """The Images tab's picks (read each time: they change on another tab)."""
        from ..plugins.stern import scene_render
        return scene_render.pending_pictures(self.assets_dir,
                                             bake=self._look_sw()["files"])

    def _look_sw(self):
        """The preview's three switches (PAD-330): the whole screen overlay, the
        individual files correction and the machine screen, each on or off."""
        sw = getattr(self, "_lsw", None)
        if sw is None:
            sw = self._lsw = {"overlay": True, "files": True, "screen": True}
        return sw

    def _machine_view(self):
        """How the machine's screen will show the frame (PAD-312), through the preview's
        overlay and screen switches (PAD-330); None with both off."""
        sw = self._look_sw()
        if not (sw["overlay"] or sw["screen"]):
            return None
        try:
            from ..core import colour_profile
            return colour_profile.machine_view(self.assets_dir, overlay_on=sw["overlay"],
                                               screen_on=sw["screen"])
        except Exception:                            # noqa: BLE001
            log.exception("machine view")
            return None

    def _publish_look(self):
        """The switches and what each one names, for the row under the preview."""
        parts = None
        try:
            from ..core import colour_profile
            parts = colour_profile.preview_parts(self.assets_dir)
        except Exception:                            # noqa: BLE001
            log.exception("preview parts")
        sw = dict(self._look_sw())
        self.set(look={"sw": sw, "parts": parts}, machine_look=any(sw.values()))

    def _look_changed(self):
        self._publish_look()
        if self._sel:
            self._trev = getattr(self, "_trev", 0) + 1
            self._render_preview(self._sel)

    @rpc
    def set_look_part(self, part, on):
        """One of the preview's three switches: "overlay", "files" or "screen".  Only the
        preview changes; nothing staged for the card moves."""
        if part not in ("overlay", "files", "screen"):
            return False
        self._look_sw()[part] = bool(on)
        self._look_changed()
        return True

    def _as_made(self):
        """⚙ Scenes: switched-off files in their own colors (PAD-325, on by default)."""
        var = getattr(self.window, "scenes_own_colours_var", None)
        try:
            return True if var is None else bool(var.get())
        except Exception:                            # noqa: BLE001
            return True

    @rpc
    def set_machine_look(self, on):
        """All three preview switches at once: as on the machine, or the PC's own colours
        (what the single As on the machine tick did before PAD-330)."""
        sw = self._look_sw()
        for k in sw:
            sw[k] = bool(on)
        self._look_changed()
        return True

    def _tree_sizes(self):
        from ..plugins.stern import scene_render
        if getattr(self, "_tsizes", None) is None or self._tsizes[0] != self.assets_dir:
            self._tsizes = (self.assets_dir, scene_render.picture_sizes(self.assets_dir))
        return self._tsizes[1]

    def refresh_view(self):
        """The Scenes tab came forward again: another tab may have replaced a picture or
        imported a font since this scene was drawn, so draw it again (fonts re-read)."""
        if not self._alive or not self._sel:
            return
        self._fonts = None
        self._tsizes = None
        self._tree_unselect()                    # it comes back with nothing selected (PAD-294)
        self._restate_list()                     # a Write since: its scenes are written now
        if self._tree_available(self._sel):
            self._render_tree_preview(self._sel, quiet=True)
        else:
            self._render_preview(self._sel)

    # ------------------------------------------------------------------
    # playing the animation (DragonRR: "play the animation as well as step through it")
    # ------------------------------------------------------------------
    _PLAY_SCALE = 0.5                # frames are drawn at half size: 4x fewer pixels

    def _play_stop(self):
        if self._tplay is not None:
            self._tplay["cancel"] = True
            self._tplay = None
            self.set(tree_play=None)

    @rpc
    def tree_play(self, on=True):
        """Play the scene's timeline on the canvas: every frame drawn once in the background
        (identical frames drawn once, at half size), handed to the page as they are ready; the
        page plays them at the scene's own frame rate.  *on* False stops."""
        from ..plugins.stern import scene_eval
        self._play_stop()
        if not on:
            return True
        card, stock = self._tree_card()
        if card is None or self._tman is None:
            return False
        man = self._tman
        frames = int(man["root"].get("frames") or 1)
        if frames < 2:
            return False
        pins = dict(self._tpins.get(card) or {})
        fps = float((man.get("stage") or [0, 0, 30])[2] or 30)
        state = self._tplay = {"cancel": False}
        job = {"man": man, "pins": pins, "frames": frames, "bg": self._bg,
               "unveil": set(self._tree_hidden(card)),
               "hidden": set(self._tree_view_hidden(card)),
               "text_edits": self._pending_texts(card, None), "colors": self._pending_colors(card),
               "pictures": self._tree_pictures(), "sizes": self._tree_sizes(),
               "view": self._machine_view(), "as_made": self._as_made(),
               "tmp": self._tmpdir(), "assets": self.assets_dir, "cache": self._tcache}
        self.set(tree_play={"run": "p%d" % id(state), "fps": fps, "frames": frames,
                            "map": [], "srcs": [], "done": False})
        threading.Thread(target=self._play_draw, args=(state, job), daemon=True,
                         name="scene-play").start()
        return True

    def _play_draw(self, state, job):
        import time
        from ..plugins.stern import scene_eval, scene_render
        s = self._PLAY_SCALE
        w, h = job["man"]["stage"][0], job["man"]["stage"][1]
        small = dict(job["man"], stage=[round(w * s), round(h * s)] + list(job["man"]["stage"][2:]))
        shrink = (s, 0.0, 0.0, s, 0.0, 0.0)
        tag = "p%d" % id(state)                     # = tree_play's "run"
        srcs, index, last, prev = [], [], 0.0, None
        inks = {}                    # every line of text laid out once for the whole play
        try:
            if self._fonts is None:
                from ..plugins.stern import fontrender as fr
                self._fonts = fr.load_fonts(job["assets"])
            # each frame drawn as soon as it is worked out (a held stretch is drawn once), so
            # the first is on the page at once, not after the whole timeline is (PAD-261:
            # Godzilla's credits waited ~5 s for all 120)
            for f in range(1, job["frames"] + 1):
                if state["cancel"]:
                    return
                draws = scene_eval.draw_list(job["man"], f, pins=job["pins"], play=True,
                                             unveil=job["unveil"], hidden=job["hidden"])
                if prev is None or not scene_eval._same(draws, prev):
                    prev = draws
                    scaled = [dict(d, m=scene_eval.compose(shrink, d["m"])) for d in draws]
                    img = scene_render.render_tree(
                        job["assets"], small, draws=scaled, fonts=self._fonts,
                        background=job["bg"], colors=job["colors"],
                        text_edits=job["text_edits"], cache=job["cache"],
                        pictures=job["pictures"], sizes=job["sizes"], inks=inks,
                        view=job.get("view"), as_made=job.get("as_made", False))
                    path = os.path.join(job["tmp"], "%s_%d.png" % (tag, len(srcs)))
                    if img is not None:
                        img.save(path, compress_level=1)
                    srcs.append(path if img is not None else "")
                index.append(len(srcs) - 1)
                now = time.time()
                if f == 1 or now - last > 0.4 or f == job["frames"]:
                    last = now
                    self.ctx.loop.post(self._play_publish, state, list(index), list(srcs),
                                       f == job["frames"])
        except Exception:                            # noqa: BLE001
            if state["cancel"]:
                return                               # stopped (a close drops the folder)
            log.exception("scene play")
            self.ctx.loop.post(self._play_publish, state, list(index), list(srcs), True)

    def _play_publish(self, state, index, srcs, done):
        if state is not self._tplay or state["cancel"]:
            return
        cur = dict(self.store.get(self.ns, "tree_play") or {})
        if not cur:
            return
        cur.update(map=index, srcs=srcs, done=done)
        self.set(tree_play=cur)

    def _tree_split(self, draws, nids):
        """The indices of *draws* the nodes *nids* draw (themselves and what is inside them):
        they run together in draw order, or the canvas gets no layers for them."""
        nids = {nids} if isinstance(nids, int) else set(nids)
        got = []
        for i, d in enumerate(draws):
            p, hops = d["node"], 0
            while p is not None and p not in nids and hops < 256:
                p, hops = self._tparents.get(p), hops + 1
            if p in nids:
                got.append(i)
        if not got or got[-1] - got[0] + 1 != len(got):
            return set()
        return set(got)

    def _tree_worker(self):
        """One render at a time, always the newest asked for: a burst of edits draws once
        for the last of them, not once each."""
        while True:
            with self._tlock:
                job, self._tjob = self._tjob, None
                if job is None:
                    self._trunning = False
                    return
            img, paths = self._tree_draw(job)
            with self._tlock:
                newer = self._tjob is not None
            if not newer:
                self.ctx.loop.post(self._tree_show, job, img, paths)

    def _tree_draw(self, job):
        from ..plugins.stern import scene_render
        got = None
        try:
            if self._fonts is None:
                from ..plugins.stern import fontrender as fr
                self._fonts = fr.load_fonts(job["assets"])
            got = scene_render.render_tree(
                job["assets"], job["man"], job["frame"], pins=job["pins"], fonts=self._fonts,
                background=job["bg"], colors=job["colors"], text_edits=job["text_edits"],
                draws=job["draws"], cache=job["cache"], split=job["split"] or None,
                pictures=job.get("pictures"), sizes=job.get("sizes"), view=job.get("view"),
                as_made=job.get("as_made", False))
        except Exception:                            # noqa: BLE001
            log.exception("scene tree render")
        if got is None:
            return None, {}
        parts = got if isinstance(got, dict) else {"full": got}
        paths = {}
        for key in ("full", "under", "sel", "over"):
            if key not in parts:
                continue
            path = os.path.join(job["tmp"], "t%d%s.png" % (
                job["token"], "" if key == "full" else "_" + key))
            try:
                parts[key].save(path, compress_level=1)
            except OSError:
                break
            paths[key] = path
        if "full" not in paths:
            return None, {}
        return parts["full"], paths

    def _tree_show(self, job, img, paths):
        if job["token"] != self._ttoken or not self._alive:
            return
        full = paths.get("full", "")
        self._preview_full = img
        self._frames_full = [img] if img is not None else []
        self._tshown_card = job["card"]
        layers = None
        if job["sel"] is not None and all(k in paths for k in ("under", "sel", "over")):
            layers = {"node": job["sel"], "under": paths["under"], "sel": paths["sel"],
                      "over": paths["over"]}
        self.set(frames=[full] if full else [], tree_layers=layers, tree_busy=False,
                 tree_loading=False, tree_img_rev=job["rev"], can_save=img is not None,
                 canvas_msg="" if full else "nothing could be drawn")
        keep = {os.path.basename(p) for p in paths.values()}
        tmp = self._tmpdir()
        for name in os.listdir(tmp):
            if name.startswith("t") and name not in keep:
                try:
                    os.remove(os.path.join(tmp, name))
                except OSError:
                    pass

    def _tree_publish(self, card, man, frame, notes=()):
        """Everything the page shows about the scene's tree: the moment, the states, the
        outlines to pick from, the layers and the selection."""
        from ..plugins.stern import scene_edit, scene_eval
        w, h = int(man["stage"][0]), int(man["stage"][1])
        hits = []
        for d in self._tdraws:
            if d["mul"][3] <= 0.01 or d["kind"] not in ("bitmap", "text", "flip"):
                continue
            hits.append({"id": d["node"], "name": d["path"][-1], "kind": d["kind"],
                         "path": " › ".join(d["path"]),
                         "pts": [[round(x, 1), round(y, 1)] for x, y in
                                 scene_eval.outline(d)]})
        rest = self._tree_default(card)
        moments = [{"value": "f:%d" % rest, "label": "Resting (frame %d)" % rest}]
        for name, f in sorted(man["root"]["labels"], key=lambda x: x[1]):
            moments.append({"value": "f:%d" % f, "label": "%s (frame %d)" % (name, f)})
        pins = self._tpins.get(card) or {}
        states = []
        for nid, path, labels, frames in scene_eval.seekable(man):
            opts = [{"value": "", "label": "As it rests"}]
            opts += [{"value": str(f), "label": "%s (%d)" % (n, f)}
                     for n, f in sorted(labels, key=lambda x: x[1])]
            states.append({"node": nid, "name": path[-1], "path": " › ".join(path),
                           "value": str(pins[nid]) if nid in pins else "", "options": opts})
        ops = self._tree_ops(card)
        edited_nodes = {}
        for op in ops:
            key = op.get("node", op.get("id"))
            edited_nodes.setdefault(key, []).append(scene_edit.describe(op))
        drawn = {d["node"] for d in self._tdraws}
        view = self._tree_view_hidden(card)
        layers = []
        index = scene_edit._man_index(man)
        have, memo = {}, {}
        # PAD-312: each picture's colour switch (the chosen-files profile baked into it)
        from ..core import colour_profile as _cp
        settings = _cp.asset_settings(self.assets_dir)
        picks = self._tree_pictures()
        added_ops = {int(op["id"]): op for op in ops
                     if op.get("op") == "add_picture" and op.get("id") is not None}
        for n, _parent, depth in _walk_man(man):
            kind = _kind_of(man, n)
            pics = []
            for rel in _pics_of(man, n, memo):
                if rel not in have:
                    have[rel] = os.path.isfile(
                        os.path.join(self.assets_dir, "images", *rel.split("/")))
                if have[rel]:
                    pics.append(rel)
            layers.append({"id": n["id"], "name": n["name"], "depth": depth, "kind": kind,
                           "pics": ["images/" + rel for rel in pics],
                           "color": _colour_switch(n, kind, pics, picks, settings,
                                                   added_ops.get(n["id"])),
                           "drawn": n["id"] in drawn or n["id"] in self._tworlds,
                           "state_off": n["id"] in self._teye_off,
                           "part_off": n["id"] in self._tpart_off,
                           "shown": n["id"] in (self._tforce.get(card) or ()),
                           "added": bool(n.get("added")),
                           "hidden": any(op["op"] == "visible" and op.get("node") == n["id"]
                                         for op in ops),
                           "view_off": n["id"] in view,
                           "edits": "; ".join(edited_nodes.get(n["id"], []))})
        sel = self._tsel if self._tsel in index else None
        self._tsel = sel
        sels = self._tree_sels()
        multi = len(sels) > 1
        self.set(tree_live=self._live_note(card))
        self.set(tree=True, tree_view={
            "card": card, "stage": [w, h], "frame": frame,
            "frames": int(man["root"].get("frames") or 1),
            "moment": "f:%d" % frame, "moments": moments, "states": states,
            "hits": hits, "layers": layers, "sel": sel, "sels": sels,
            "sel_boxes": [[round(b[0]), round(b[1]), round(b[2] - b[0]), round(b[3] - b[1])]
                          for b in map(self._tree_box, sels) if b] if multi else [],
            "props": self._tree_props(card, man, sel, ops) if sel is not None else None,
            "edits": len(ops), "notes": list(notes), "rev": self._trev,
            # PAD-290: an eye hide is a card edit; the status line names every one
            "hidden_names": [l["name"] for l in layers if l["hidden"]],
            # PAD-293: the preview's eyes differ from the game's (Reset puts them back)
            "view_apart": view != self._tree_hidden(card) or bool(self._tforce.get(card)),
            "solo": (self._tsolo.get((self.assets_dir, card)) or (None,))[0],
            "can_undo": bool(ops or (self._tree_hist(card) or {}).get("undo")),
            "can_redo": bool((self._tree_hist(card) or {}).get("redo")),
            "all_edits": scene_edit.count(self.assets_dir),
            "built": _built_state(scene_edit.built_ops(self.assets_dir, card), ops)})

    def _tree_props(self, card, man, nid, ops):
        from ..plugins.stern import scene_edit
        index = scene_edit._man_index(man)
        n, sibs = index[nid]
        scale = scale_y = 1.0
        rotate = 0.0
        mul = [1.0, 1.0, 1.0, 1.0]
        for op in ops:
            if op.get("node") != nid:
                continue
            if op["op"] == "rotate":
                rotate += op["deg"]
            if op["op"] == "scale":
                scale *= op["s"]
                scale_y *= op.get("sy", op["s"])
            elif op["op"] == "tint":
                mul = [mul[i] * op["mul"][i] for i in range(4)]
        box = self._tree_box(nid)
        return {"id": nid, "name": n["name"], "kind": _kind_of(man, n),
                "added": bool(n.get("added")),
                "x": round(box[0]) if box else None, "y": round(box[1]) if box else None,
                "w": round(box[2] - box[0]) if box else None,
                "h": round(box[3] - box[1]) if box else None,
                "scale": round(scale * 100), "scale_y": round(scale_y * 100),
                "rotate": round(rotate, 2),
                "tint": "#%02x%02x%02x" % tuple(int(round(min(1, c) * 255)) for c in mul[:3]),
                "alpha": round(mul[3] * 100),
                "hidden": any(op["op"] == "visible" and op.get("node") == nid for op in ops),
                "layer": sibs.index(n) + 1, "layers": len(sibs),
                "drawn": nid in self._tworlds,
                "peek": nid == self._tpeek and nid in self._tworlds and nid not in self._tlit,
                "view_off": nid in self._tree_view_hidden(card),
                "hid_in": self._tree_hidden_in(man, nid, self._tree_hidden(card)),
                "view_in": self._tree_hidden_in(man, nid, self._tree_view_hidden(card)),
                "pic": self._tree_pic_props(nid)}

    def _tree_picture(self, nid):
        """``(draw, (w, h))``: the one picture node *nid* itself draws now and the picture's
        own pixel size (a pick that keeps its own size, else the card's texture), or None."""
        pics = [d for d in self._tdraws
                if d["node"] == nid and d["kind"] in ("bitmap", "flip") and d.get("image")]
        if len(pics) != 1:
            return None
        d = pics[0]
        size = _kept_size(self._tree_pictures().get(d["image"]) or {}, self.assets_dir,
                          d["image"], self._tree_sizes().get(d["image"]))
        if size is None:
            size = self._tree_sizes().get(d["image"])
        if size is None:
            size = _file_size(os.path.join(self.assets_dir, "images", *d["image"].split("/")))
        if size is None:
            size = (d["w"], d["h"])
        return d, (int(size[0]), int(size[1]))

    def _tree_pic_props(self, nid):
        """DragonRR (PAD-277): a picture's own size and the scale the game draws it at - Stern
        often ships a big picture and lets the game shrink it (Credits_Text: 1044 x 264 drawn
        near 40%), which leaves jagged edges."""
        got = self._tree_picture(nid)
        if got is None:
            return None
        d, (w, h) = got
        a, b, c, dd = d["m"][:4]
        return {"w": w, "h": h, "sx": round(math.hypot(a, b) * 100, 1),
                "sy": round(math.hypot(c, dd) * 100, 1)}

    def _fit_kept(self, draws, worlds):
        """A pick that keeps its own size is written at that size (the Write regrows the
        picture's record and every sprite that names it, PAD-154), so the box it draws on the
        glass is the pick's size, not the stock one.  Only a Bitmap drawn by its own node: a
        Shape's fill is stretched to the shape's rect whatever its size."""
        picks = self._tree_pictures()
        sizes = self._tree_sizes()
        for d in draws:
            own = (worlds.get(d["node"]) or (None, None))[1]
            if d["kind"] != "bitmap" or not d.get("image") or own is None \
                    or tuple(d["m"]) != tuple(own):
                continue
            size = _kept_size(picks.get(d["image"]) or {}, self.assets_dir, d["image"],
                              sizes.get(d["image"]))
            if size is not None:
                d["w"], d["h"] = size

    def _tree_unselect(self):
        """Nothing selected: a scene opens, and the Scenes tab comes forward, with no layer
        picked, since a selected one is drawn on top (DragonRR, PAD-294)."""
        self._tsel = None
        self._tsels = []
        self._tanchor = None
        self._tpeek = None

    def _tree_sels(self):
        """Every selected node, the last one picked (``_tsel``) last.  Whatever selects a
        node on its own (``_tsel`` set elsewhere) leaves just that one selected."""
        index = self._tparents
        if self._tsel is None or self._tsel not in index:
            self._tsels = []
            return []
        sels = [n for n in self._tsels if n in index and n != self._tsel]
        if self._tsel not in self._tsels:
            sels = []
        self._tsels = sels + [self._tsel]
        return list(self._tsels)

    def _tree_top(self, nodes):
        """*nodes* less those inside another of them: moving a sprite moves what is in it."""
        got = set(nodes)
        out = []
        for n in nodes:
            p, hops = self._tparents.get(n), 0
            while p is not None and p not in got and hops < 256:
                p, hops = self._tparents.get(p), hops + 1
            if p is None:
                out.append(n)
        return out

    def _tree_box(self, nid):
        """The glass box ``(x0, y0, x1, y1)`` of everything node *nid* draws now."""
        from ..plugins.stern import scene_eval
        pts = []
        for d in self._tdraws:
            p, hops = d["node"], 0
            while p is not None and p != nid and hops < 256:
                p, hops = self._tparents.get(p), hops + 1
            if p == nid:
                pts += scene_eval.outline(d)
        if not pts:
            return None
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def _tree_refresh(self):
        card, _man = self._tree_card()
        if card is not None:
            self._tree_track(card)                   # the edit just made is one undo step
        self._trev += 1
        self._folder_state_written()
        self._restate_list()
        if self._sel:
            self._render_tree_preview(self._sel)
            self._live_kick()

    # ------------------------------------------------------------------
    # the running emulator ("on the fly", PAD-251)
    # ------------------------------------------------------------------
    def _live_target(self):
        emu = None
        try:
            emu = self.window.service("emulate")
        except Exception:                            # noqa: BLE001
            emu = None
        fn = getattr(emu, "live_scene_target", None)
        if not callable(fn):
            return None, None
        try:
            return emu, fn(self.assets_dir)
        except Exception:                            # noqa: BLE001
            return None, None

    def _live_note(self, card):
        """What an edit to *card* does to the game running in the Emulate tab now, or None
        when no game runs this project's edits."""
        from ..plugins.stern import engine
        _emu, out = self._live_target()
        if out is None or not card:
            return None
        restart = "Stop, then Start, on the Emulate tab"
        if not engine.scene_loads_on_demand(card):
            return {"kind": "boot", "text": "The running game loaded this scene when it started, "
                    "so your edits show after a restart (%s)." % restart}
        if not os.path.isfile(engine._override_path(out, card)):
            return {"kind": "later", "text": "The running game started before this scene had "
                    "edits, so they show after a restart (%s)." % restart}
        got = self._tlive.get(card)
        if got and got[0] == "failed":
            return {"kind": "failed", "text": "The running game could not be reached (the log "
                    "says why); your edits show after a restart (%s)." % restart}
        if got and got[0] == "sent":
            return {"kind": "live", "text": "Live: sent to the running game at %s. It shows "
                    "the next time this scene comes up." % got[1]}
        return {"kind": "live", "text": "Live: edits here reach the running game, which shows "
                "them the next time this scene comes up."}

    def _live_publish(self):
        card = self._tree_card()[0] if self._sel else None
        self.set(tree_live=self._live_note(card))

    def _live_kick(self):
        """After an edit: hand the running game this scene, once the edits pause."""
        if self._tlive_job is not None:
            try:
                self.ctx.loop.after_cancel(self._tlive_job)
            except Exception:                        # noqa: BLE001
                pass
            self._tlive_job = None
        card = self._tree_card()[0] if self._sel else None
        note = self._live_note(card)
        self.set(tree_live=note)
        if not note or note["kind"] not in ("live", "failed"):
            return
        self._tlive_job = self.ctx.loop.after(350, self._live_send, card)

    def _live_send(self, card):
        import time
        from ..plugins.stern import engine
        self._tlive_job = None
        emu, out = self._live_target()
        if out is None:
            self._live_publish()
            return
        assets = self.assets_dir

        def work():
            with self._tlive_lock:
                try:
                    data = engine.scene_live_bytes(out, assets, card)
                    res = "not_in_set" if data is None else emu.push_live_scene(card, data)
                except Exception:                    # noqa: BLE001
                    log.exception("live scene")
                    res = "failed"
            self.ctx.loop.post(self._live_done, card, res, time.strftime("%H:%M:%S"))

        threading.Thread(target=work, daemon=True, name="scene-live").start()

    def _live_done(self, card, res, when):
        self._tlive[card] = (res, when)
        if self._alive:
            self._live_publish()

    # ------------------------------------------------------------------
    # the moment and the states
    # ------------------------------------------------------------------
    @rpc
    def tree_moment(self, value):
        card, man = self._tree_card()
        if card is None:
            return False
        try:
            f = int(str(value).split(":", 1)[-1])
        except ValueError:
            return False
        frames = int(man["root"].get("frames") or 1)
        self._tframe[card] = max(1, min(frames, f))
        self._render_tree_preview(self._sel)
        return True

    @rpc
    def tree_state(self, node, frame):
        card, _man = self._tree_card()
        if card is None:
            return False
        pins = self._tpins.setdefault(card, {})
        if frame in ("", None):
            pins.pop(int(node), None)
        else:
            pins[int(node)] = int(frame)
        self._render_tree_preview(self._sel)
        return True

    @rpc
    def tree_select(self, node=None, how=""):
        """Select a layer.  One the game is not drawing at this moment is drawn on top, where
        it sits, for as long as it stays selected (DragonRR, PAD-276: clicking a greyed layer
        went to another moment of the scene, and greyed the one that was showing); only when
        the sprite it sits in is off now too does the preview go to where the game shows it.

        *how* picks several at once (DragonRR, PAD-279: "a line of words" moved together):
        ``add`` (Ctrl-click) adds the node to the selection or takes it out again, ``range``
        (Shift-click in Layers) selects every layer from the last one clicked to this one."""
        card, _man = self._tree_card()
        if card is None:
            return False
        node = int(node) if node not in (None, "") else None
        if how in ("add", "range") and node is not None and self._tsel is not None:
            return self._tree_select_more(card, node, how)
        peeked, self._tpeek = self._tpeek, None
        self._tsel = node
        self._tsels = [node] if node is not None else []
        self._tanchor = node
        if node is not None and node == peeked:
            self._tpeek = node
            self._render_tree_preview(self._sel, quiet=True)
            return True
        if node is not None:
            # whatever it is - on the screen, hidden with its eye, not drawn now - it is drawn
            # on top while it is picked, and a sprite with every layer in it; no eye changes
            # (DragonRR, PAD-289)
            self._tpeek = node
            self._render_tree_preview(self._sel, quiet=node in self._tlit)
            if node in self._tworlds:
                return True
            self._tpeek = None
            return self.tree_show(node)
        if peeked is not None:
            self._render_tree_preview(self._sel)
        elif self._tsel is not None and self._tsel in self._tworlds:
            # the picture is unchanged; the selection's own layers are drawn for live dragging
            self._render_tree_preview(self._sel, quiet=True)
        else:
            self._tree_publish(card, self._tman, self._tree_frame(card, _man))
        return True

    def _tree_select_more(self, card, node, how):
        sels = self._tree_sels()
        if how == "add":
            if node in sels:
                sels.remove(node)
                if not sels:
                    return self.tree_select(None)
            else:
                sels.append(node)
            self._tanchor = node
        else:
            order = [n["id"] for n, _p, _d in _walk_man(self._tman)]
            anchor = self._tanchor if self._tanchor in order else sels[-1]
            if node not in order or anchor not in order:
                return False
            a, b = order.index(anchor), order.index(node)
            step = 1 if b >= a else -1
            sels = order[a:b + step if b + step >= 0 else None:step]
        if len(sels) == 1:
            anchor = self._tanchor
            self.tree_select(sels[0])
            self._tanchor = anchor
            return True
        peeked, self._tpeek = self._tpeek, None
        self._tsels, self._tsel = sels, sels[-1]
        # the picture changes only when a layer shown on top while picked stops being picked
        self._render_tree_preview(self._sel, quiet=peeked is None)
        return True

    # ------------------------------------------------------------------
    # edits
    # ------------------------------------------------------------------
    def _tree_add_group(self, ops):
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None or not ops:
            return False
        try:
            scene_edit.add_group(self.assets_dir, card, ops)
        except OSError as e:
            compat.messagebox.showerror("Scene edit", str(e))
            return False
        self._tree_refresh()
        return True

    def _tree_nodes(self, nodes):
        if isinstance(nodes, (int, str)):
            nodes = [nodes]
        return [int(n) for n in nodes or ()]

    @rpc
    def tree_move_many(self, nodes, dx, dy):
        """Move several nodes by the same (dx, dy) glass pixels: one edit, one undo step.  A
        node inside another that is moving too is left to move with it."""
        from ..plugins.stern import scene_eval
        ops = []
        for node in self._tree_top(self._tree_nodes(nodes)):
            parent = (self._tworlds.get(node) or (scene_eval.IDENTITY,))[0]
            lx, ly = scene_eval.to_parent(parent, float(dx), float(dy))
            if abs(lx) >= 1e-6 or abs(ly) >= 1e-6:
                ops.append({"op": "move", "node": node, "dx": round(lx, 3), "dy": round(ly, 3)})
        return self._tree_add_group(ops)

    @rpc
    def tree_visible_many(self, nodes, on):
        """Hide (or show again) several nodes at once."""
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        nodes = self._tree_nodes(nodes)
        if on:
            for node in nodes:
                scene_edit.drop(self.assets_dir, card, node, "visible")
            self._tree_refresh()
            return True
        hidden = {op.get("node") for op in self._tree_ops(card) if op["op"] == "visible"}
        return self._tree_add_group([{"op": "visible", "node": n, "on": False}
                                     for n in nodes if n not in hidden])

    @rpc
    def tree_remove_many(self, nodes):
        """Delete on a multiple selection: ADDED nodes are removed, the game's own hidden."""
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        nodes = self._tree_top(self._tree_nodes(nodes))
        added = {n["id"] for n, _p, _d in _walk_man(self._tman) if n.get("added")}
        for node in nodes:
            if node in added:
                scene_edit.reset_node(self.assets_dir, card, node)
        own = [n for n in nodes if n not in added]
        if own:
            return self._tree_delete(own)
        self._tree_refresh()
        return True

    def _tree_add(self, op):
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        try:
            scene_edit.add(self.assets_dir, card, op)
        except OSError as e:
            compat.messagebox.showerror("Scene edit", str(e))
            return False
        self._tree_refresh()
        return True

    @rpc
    def tree_move(self, node, dx, dy):
        """A drag of (dx, dy) glass pixels, in the node's own units."""
        from ..plugins.stern import scene_eval
        node = int(node)
        parent = (self._tworlds.get(node) or (scene_eval.IDENTITY,))[0]
        lx, ly = scene_eval.to_parent(parent, float(dx), float(dy))
        if abs(lx) < 1e-6 and abs(ly) < 1e-6:
            return False
        return self._tree_add({"op": "move", "node": node, "dx": round(lx, 3),
                               "dy": round(ly, 3)})

    @rpc
    def tree_scale(self, node, factor, factor_y=None):
        """Resize by *factor* (and, when given, the height by *factor_y*) about the middle of
        what the node draws."""
        from ..plugins.stern import scene_eval
        node = int(node)
        factor = float(factor)
        fy = factor if factor_y in (None, "") else float(factor_y)
        if factor <= 0.01 or fy <= 0.01 or (abs(factor - 1.0) < 1e-4 and abs(fy - 1.0) < 1e-4):
            return False
        box = self._tree_box(node)
        world = (self._tworlds.get(node) or (None, scene_eval.IDENTITY))[1]
        px = py = 0.0
        if box is not None:
            inv = scene_eval.invert(world)
            if inv is not None:
                px, py = scene_eval.apply(inv, (box[0] + box[2]) / 2.0,
                                          (box[1] + box[3]) / 2.0)
        op = {"op": "scale", "node": node, "s": round(factor, 6),
              "px": round(px, 3), "py": round(py, 3)}
        if abs(fy - factor) > 1e-6:
            op["sy"] = round(fy, 6)
        return self._tree_add(op)

    def _tree_pivot(self, node):
        """The middle of what *node* draws now, in the node's own units (0, 0 if nothing)."""
        from ..plugins.stern import scene_eval
        box = self._tree_box(node)
        world = (self._tworlds.get(node) or (None, scene_eval.IDENTITY))[1]
        if box is not None:
            inv = scene_eval.invert(world)
            if inv is not None:
                return scene_eval.apply(inv, (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        return 0.0, 0.0

    @rpc
    def tree_rotate(self, node, deg):
        """Turn it *deg* degrees clockwise about the middle of what it draws (DragonRR:
        "graphics can be rotated"): the scene's own transform, as the game's tilted tiles."""
        node = int(node)
        try:
            deg = float(deg)
        except (TypeError, ValueError):
            return False
        if abs(deg % 360.0) < 1e-4:
            return False
        px, py = self._tree_pivot(node)
        return self._tree_add({"op": "rotate", "node": node, "deg": round(deg, 4),
                               "px": round(px, 3), "py": round(py, 3)})

    @rpc
    def tree_set_rotation(self, node, deg):
        """The Turn box: *deg* is how far from as shipped it should be turned."""
        card, _man = self._tree_card()
        if card is None:
            return False
        try:
            want = float(deg)
        except (TypeError, ValueError):
            return False
        cur = self._tree_props(card, self._tman, int(node), self._tree_ops(card))["rotate"]
        return self.tree_rotate(node, want - cur)

    #: a new drop shadow: this far down and right on the screen, black at this opacity
    _SHADOW_PX = 4.0
    _SHADOW_ALPHA = 0.6

    @rpc
    def tree_shadow(self, node):
        """A drop shadow under a line of text (DragonRR: "can text have drop shadows?"): the
        Text has no shadow setting, so it is drawn the way the game draws its outlines - a
        second copy of the same text just beneath it, here moved a few pixels down and right
        and darkened.  The shadow is selected, to move, tint or remove like any layer."""
        from ..plugins.stern import scene_edit, scene_eval
        card, _man = self._tree_card()
        if card is None or self._tman is None:
            return False
        node = int(node)
        got = scene_edit._man_index(self._tman).get(node)
        if got is None or _kind_of(self._tman, got[0]) != "Text":
            return False
        parent = (self._tworlds.get(node) or (scene_eval.IDENTITY,))[0]
        dx, dy = scene_eval.to_parent(parent, self._SHADOW_PX, self._SHADOW_PX)
        nid = scene_edit.new_id(self._tman, self._tree_ops(card))
        self._tsel = nid
        return self._tree_add({"op": "shadow", "node": node, "id": nid,
                               "dx": round(dx, 3), "dy": round(dy, 3),
                               "mul": [0.0, 0.0, 0.0, self._SHADOW_ALPHA]})

    @rpc
    def tree_set_scale(self, node, pct):
        card, man = self._tree_card()
        if card is None:
            return False
        cur = self._tree_props(card, self._tman, int(node), self._tree_ops(card))["scale"]
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            return False
        if pct <= 1 or cur <= 0:
            return False
        return self.tree_scale(node, pct / float(cur))

    @rpc
    def tree_set_pixels(self, node, w_px=None, h_px=None, keep_shape=True):
        """An exact size in screen pixels (DragonRR: "set the exact size I am after rather
        than %"): the width and/or height of what the element draws now, on the 1360x768
        glass.  With *keep_shape* one of them sets both in proportion."""
        node = int(node)
        box = self._tree_box(node)
        if box is None:
            return False
        cur_w, cur_h = box[2] - box[0], box[3] - box[1]
        try:
            w = float(w_px) if w_px not in (None, "") else None
            h = float(h_px) if h_px not in (None, "") else None
        except (TypeError, ValueError):
            return False
        if (w is not None and w < 1) or (h is not None and h < 1) or (w is None and h is None):
            return False
        fw = w / cur_w if w is not None and cur_w > 0 else None
        fh = h / cur_h if h is not None and cur_h > 0 else None
        if keep_shape:
            f = fw if fw is not None else fh
            if f is None:
                return False
            fw = fh = f
        return self.tree_scale(node, fw if fw is not None else 1.0,
                               fh if fh is not None else 1.0)

    @rpc
    def tree_set_size(self, node, w_pct=None, h_pct=None):
        """Width % and height % on their own (a picture stretched), each against the size
        the game ships."""
        card, _man = self._tree_card()
        if card is None:
            return False
        p = self._tree_props(card, self._tman, int(node), self._tree_ops(card))
        try:
            fw = float(w_pct) / p["scale"] if w_pct not in (None, "") else 1.0
            fh = float(h_pct) / p["scale_y"] if h_pct not in (None, "") else 1.0
        except (TypeError, ValueError, ZeroDivisionError):
            return False
        return self.tree_scale(node, fw, fh)

    @rpc
    def tree_one_to_one(self, node):
        """Draw the picture pixel for pixel (DragonRR, PAD-277: the game's own shrinking of a
        big picture leaves jagged edges; a picture made at the size it shows, kept at its own
        size on the Images tab, then needs the scene's scale taken off).  Its top-left corner
        stays where it is."""
        from ..plugins.stern import scene_eval
        node = int(node)
        got = self._tree_picture(node)
        if got is None:
            return False
        d = got[0]
        a, b, c, dd = d["m"][:4]
        sx, sy = math.hypot(a, b), math.hypot(c, dd)
        if sx < 1e-6 or sy < 1e-6 or (abs(sx - 1.0) < 1e-3 and abs(sy - 1.0) < 1e-3):
            return False
        world = (self._tworlds.get(node) or (None, scene_eval.IDENTITY))[1]
        inv = scene_eval.invert(world)
        if inv is None:
            return False
        px, py = scene_eval.apply(inv, *scene_eval.apply(d["m"], 0.0, 0.0))
        op = {"op": "scale", "node": node, "s": round(1.0 / sx, 6),
              "px": round(px, 3), "py": round(py, 3)}
        if abs(sx - sy) > 1e-6:
            op["sy"] = round(1.0 / sy, 6)
        return self._tree_add(op)

    @rpc
    def tree_tint(self, node, hex_color, alpha=100):
        """Tint (the node's colour track) to *hex_color* at *alpha* %, replacing its tint."""
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        node = int(node)
        try:
            hx = str(hex_color).lstrip("#")
            rgb = [int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
            a = max(0.0, min(1.0, float(alpha) / 100.0))
        except (ValueError, IndexError):
            return False
        scene_edit.drop(self.assets_dir, card, node, "tint")
        if rgb == [1.0, 1.0, 1.0] and a >= 0.999:
            self._tree_refresh()
            return True
        return self._tree_add({"op": "tint", "node": node,
                               "mul": [round(c, 4) for c in rgb] + [round(a, 4)]})

    #: how many moments tree_show tries before it gives up
    _SHOW_TRIES = 400

    @rpc
    def tree_show(self, node):
        """Bring a layer the game is not drawing at this moment into view (DragonRR: the
        greyed eyes, "force them to show"): the nearest moment where the game DOES draw it -
        another state of a sprite it sits in (Gigan's tile: the kaiju picker on Gigan), then
        another frame of the scene.  The preview goes there and selects it; nothing on the
        card changes.  False when the game never draws it (a note says so)."""
        from ..plugins.stern import scene_eval
        card, _stock = self._tree_card()
        man = self._tman
        if card is None or man is None:
            return False
        node = int(node)
        pins = dict(self._tpins.get(card) or {})
        frame = self._tree_frame(card, man)
        frames = int(man["root"].get("frames") or 1)
        # the sprites it sits in (itself first), nearest first, with their states
        chain, p, hops = [], node, 0
        while p is not None and hops < 256:
            chain.append(p)
            p, hops = self._tparents.get(p), hops + 1
        seek = {nid: labels for nid, _path, labels, _f in scene_eval.seekable(man)}
        # a state the game HOLDS first (Gigan_Selected_Start), then its comings and goings
        # (Gigan_FadeIn_Start draws the tile still transparent)
        states = [(nid, f) for nid in chain if nid in seek
                  for _n, f in sorted(seek[nid], key=lambda x: (bool(_PASSING.search(x[0] or "")),
                                                                x[1]))]
        root_frames = [frame] + sorted({f for _n, f in man["root"]["labels"]})
        root_frames += list(range(1, frames + 1, max(1, frames // 60)))
        tried = set()
        # what the user hid with an eye is looked for too: picking it shows it (PAD-289)
        veiled = self._tree_hidden(card)

        def shows(f, pn):
            key = (f, tuple(sorted(pn.items())))
            if key in tried:
                return False
            tried.add(key)
            for d in scene_eval.draw_list(man, f, pins=pn, unveil=veiled):
                if d["mul"][3] <= 0.01:
                    continue
                q, hops = d["node"], 0            # it, or something inside it, shows
                while q is not None and q != node and hops < 256:
                    q, hops = self._tparents.get(q), hops + 1
                if q == node:
                    return True
            return False

        found = None
        for f in dict.fromkeys(root_frames):
            for extra in [None] + states:
                if len(tried) >= self._SHOW_TRIES:
                    break
                pn = dict(pins)
                if extra is not None:
                    pn[extra[0]] = extra[1]
                if shows(f, pn):
                    found = (f, pn)
                    break
            if found or len(tried) >= self._SHOW_TRIES:
                break
        if found is None:
            self._tonce = ["The game does not draw that at any moment of this scene"]
            self._render_tree_preview(self._sel)
            return False
        self._tframe[card] = found[0]
        self._tpins[card] = found[1]
        self._tsel = node
        self._tsels = [node]
        self._tpeek = node
        self._render_tree_preview(self._sel)
        return True

    @rpc
    def tree_visible(self, node, on):
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        node = int(node)
        if on:
            scene_edit.drop(self.assets_dir, card, node, "visible")
            self._tree_refresh()
            return True
        return self._tree_add({"op": "visible", "node": node, "on": False})

    @rpc
    def tree_color(self, node, on):
        """A layer's colour switch (PAD-312): the chosen-files profile is baked into its
        picture (an added one, or an Images-tab replacement), or the picture goes on the card
        in its own colours.  The game's own pictures have no switch: Stern made them for the
        machine's screen; replace one on the Images tab to correct it."""
        from ..plugins.stern import scene_edit
        card, man = self._tree_card()
        if card is None:
            return False
        node = int(node)
        ops = self._tree_ops(card)
        if any(op.get("op") == "add_picture" and op.get("id") == node for op in ops):
            new = [dict(op) for op in ops]
            for op in new:
                if op.get("op") == "add_picture" and op.get("id") == node:
                    op["color"] = bool(on)
            scene_edit.set_ops(self.assets_dir, card, new)
            self._tree_refresh()
            return True
        index = scene_edit._man_index(man)
        if node not in index:
            return False
        pics = _pics_of(man, index[node][0], {})
        if len(pics) != 1:
            return False
        rel = "images/" + pics[0]
        images = self.window.service("images")
        done = False
        try:
            done = bool(images.set_color(rel, bool(on)))
        except Exception:                                # noqa: BLE001
            log.exception("scene colour switch")
        if not done:
            # the Images tab has not scanned this folder: its own record is the file
            from ..core import colour_profile as _cp
            _cp.set_asset_slot(self.assets_dir, "images", rel, bool(on))
            try:
                images.color_all_changed()
            except Exception:                            # noqa: BLE001
                pass
        # drawn again here, whichever way the switch was recorded (DragonRR: the palette and
        # the picture only changed after a tab switch)
        self.pictures_changed()
        return True

    def pictures_changed(self):
        """The Images tab moved a picture's colour switch: this scene is drawn again
        (the preview shows a switched-on file the way the Write bakes it)."""
        if getattr(self, "_alive", False):
            self._publish_look()                     # a profile's name or its count moved
        if not getattr(self, "_alive", False) or not self._sel:
            return
        self._trev += 1
        if self._tree_available(self._sel):
            self._render_tree_preview(self._sel)

    @rpc
    def tree_order(self, node, where):
        from ..plugins.stern import scene_edit
        if where not in _ORDER:
            return False
        node = int(node)
        got = scene_edit._man_index(self._tman).get(node)
        if got is None:
            return False
        n, sibs = got
        cur = sibs.index(n)
        to = {"up": cur + 1, "down": cur - 1, "front": len(sibs) - 1, "back": 0}[where]
        to = max(0, min(len(sibs) - 1, to))
        if to == cur:
            return False
        return self._tree_add({"op": "order", "node": node, "index": to})

    @rpc
    def tree_reset(self, node):
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        scene_edit.reset_node(self.assets_dir, card, int(node))
        # its preview eye goes back to the game's too (PAD-293)
        self._tree_view_hidden(card).discard(int(node))
        (self._tforce.get(card) or set()).discard(int(node))
        self._tree_refresh()
        return True

    @rpc
    def tree_remove(self, node):
        """An ADDED node is removed; the game's own is hidden (its code finds it by name)."""
        node = int(node)
        got = [n for n, _p, _d in _walk_man(self._tman) if n["id"] == node]
        if got and got[0].get("added"):
            return self.tree_reset(node)
        return self._tree_delete([node])

    def _tree_delete(self, nodes):
        """Delete on the game's own layers: hidden in the game, and in the preview too, since
        a deleted layer that stayed on the screen would look like Delete did nothing (the
        eyes alone keep the two apart, PAD-293)."""
        card, _man = self._tree_card()
        if card is None:
            return False
        self._tree_view_hidden(card).update(nodes)
        if not self.tree_visible_many(nodes, False):     # hidden in the game already
            self._render_tree_preview(self._sel)
        return True

    @rpc
    def tree_undo(self):
        """Back one step.  Edits made before the app was started (no steps noted for them)
        come off the end of the list one at a time."""
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        h = self._tree_hist(card)
        was = h["undo"].pop() if h["undo"] else scene_edit.undone(h["now"])
        if was == h["now"]:
            return False
        h["redo"].append(h["now"])
        return self._tree_put(card, h, was)

    @rpc
    def tree_redo(self):
        """Forward again over the last undo (Ctrl+Y, Ctrl+Shift+Z); any new edit ends it."""
        card, _man = self._tree_card()
        if card is None:
            return False
        h = self._tree_hist(card)
        if not h["redo"]:
            return False
        h["undo"].append(h["now"])
        return self._tree_put(card, h, h["redo"].pop())

    def _tree_put(self, card, h, ops):
        from ..plugins.stern import scene_edit
        try:
            scene_edit.set_ops(self.assets_dir, card, ops)
        except OSError as e:
            compat.messagebox.showerror("Scene edit", str(e))
            return False
        h["now"] = self._tree_ops(card)
        self._tree_refresh()
        return True

    @rpc
    def tree_revert_built(self):
        """Back to what the last Write put on the card, for this scene."""
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        built = scene_edit.built_ops(self.assets_dir, card)
        if built is None:
            compat.messagebox.showinfo(
                "Scene edits", "No Write has been made from this project folder since the scene "
                "editor arrived, so there is no last Write to go back to. \"As shipped\" puts "
                "the scene back the way the game shipped it.")
            return False
        if built == self._tree_ops(card):
            return False
        if not compat.messagebox.askyesno(
                "Scene edits", "Put this scene back the way the last Write put it on the card? "
                "Every edit made to it since then is dropped."):
            return False
        scene_edit.restore_built(self.assets_dir, card)
        self._tree_view_reset(card)
        self._tsel = None
        self._tree_refresh()
        return True

    @rpc
    def tree_clear_all(self):
        """Every scene back the way the game shipped it."""
        from ..plugins.stern import scene_edit
        edits = scene_edit.load(self.assets_dir)
        n = sum(len(v) for v in edits.values())
        if not n:
            return False
        if not compat.messagebox.askyesno(
                "Scene edits", "Put EVERY scene back the way the game shipped it? That drops "
                "all %d edit(s) in %d scene(s): moves, resizes, tints, layer changes and added "
                "pictures and text." % (n, len(edits))):
            return False
        scene_edit.clear(self.assets_dir)
        self._tree_view_reset()
        self._tsel = None
        self._tree_refresh()
        return True

    @rpc
    def edits_save(self, which="this"):
        """Save edits to a file... (PAD-281): this scene's edits (``which`` "this") or every
        edited scene's ("all"), with the pictures they add, in a zip to keep or to share.
        Returns the zip's path, or None."""
        from ..plugins.stern import scene_edit
        if not self.assets_dir:
            return None
        cards = None
        stem = os.path.basename(os.path.normpath(self.assets_dir)) + " scene edits"
        if which == "this":
            card, _man = self._tree_card()
            if card is None or not self._tree_ops(card):
                return None
            cards = [card]
            stem = (self._scenes.get(self._sel, {}).get("label") or "scene") + " edits"
        elif not scene_edit.count(self.assets_dir):
            return None
        stem = re.sub(r'[\\/:*?"<>|·]+', "_", stem).strip() or "scene edits"
        path = self.window.ask_save(
            "scene_edits_file", "Save %s to a file" % (
                "this scene's edits" if which == "this" else "every scene's edits"),
            initialfile=stem + ".zip", filetypes=[("PAD scene edits", "*.zip")],
            defaultextension=".zip")
        if not path:
            return None
        try:
            n = scene_edit.export_edits(self.assets_dir, path, cards)
        except (scene_edit.SceneEditError, OSError) as e:
            compat.messagebox.showerror("Save scene edits", str(e))
            return None
        self._set_caption("Saved the edits of %d scene%s to %s"
                          % (n, "" if n == 1 else "s", os.path.basename(path)))
        return path

    @rpc
    def edits_load(self, path=None):
        """Load edits from a file... (PAD-281): each scene in a file Save edits to a file...
        wrote takes the file's edits in place of its own, when this card has that scene.
        Returns the scene paths loaded, or None."""
        from ..plugins.stern import scene_edit
        if not self.assets_dir:
            return None
        if not path:
            path = self.window.ask_open(
                "scene_edits_file", "Load scene edits from a file",
                filetypes=[("PAD scene edits", "*.zip"), ("All files", "*.*")])
        if not path:
            return None
        try:
            scenes = scene_edit.read_share(path)
            got, missing = scene_edit.match_cards(scenes, self._load_trees().keys())
            mine = scene_edit.load(self.assets_dir)
            over = [c for c in got if mine.get(c)]
            if not got:
                compat.messagebox.showinfo(
                    "Load scene edits", "None of the %d scene%s in %s %s on this card, so "
                    "nothing was loaded." % (len(scenes), "" if len(scenes) == 1 else "s",
                                             os.path.basename(path),
                                             "is" if len(scenes) == 1 else "are"))
                return None
            if over and not compat.messagebox.askyesno(
                    "Load scene edits", "%d of the scenes in this file %s edits here already. "
                    "Loading puts the file's edits in their place. Go ahead?"
                    % (len(over), "has" if len(over) == 1 else "have")):
                return None
            got, missing = scene_edit.import_edits(self.assets_dir, path,
                                                   self._load_trees().keys())
        except (scene_edit.SceneEditError, OSError) as e:
            compat.messagebox.showerror("Load scene edits", str(e))
            return None
        self._tsel = None
        self._tree_refresh()
        words = "Loaded the edits of %d scene%s from %s." % (
            len(got), "" if len(got) == 1 else "s", os.path.basename(path))
        if missing:
            words += (" %d scene%s in the file %s not on this card and %s left out."
                      % (len(missing), "" if len(missing) == 1 else "s",
                         "is" if len(missing) == 1 else "are",
                         "was" if len(missing) == 1 else "were"))
        self._set_caption(words)
        if missing:
            compat.messagebox.showinfo("Load scene edits", words)
        return sorted(got)

    @rpc
    def tree_clear(self):
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None or not self._tree_ops(card):
            return False
        if not compat.messagebox.askyesno(
                "Scene edits", "Put this scene back the way the game shipped it? Every move, "
                "resize, tint, layer change and added picture or text in it is dropped."):
            return False
        scene_edit.clear(self.assets_dir, card)
        self._tree_view_reset(card)
        self._tsel = None
        self._tree_refresh()
        return True

    def _tree_parent_for_add(self):
        """``(parent node id or None, the parent's glass affine)`` for something added now:
        inside the selected group, or beside the selected element, or on the root."""
        from ..plugins.stern import scene_eval
        man = self._tman
        sel = self._tsel
        if sel is not None:
            n = next((n for n, _p, _d in _walk_man(man) if n["id"] == sel), None)
            if n is not None and _kind_of(man, n) in ("Sprite", "StreamingFlipbook"):
                return sel, (self._tworlds.get(sel) or (None, scene_eval.IDENTITY))[1]
            for m, parent, _d in _walk_man(man):
                if m["id"] == sel and parent is not None:
                    return parent["id"], (self._tworlds.get(sel) or (scene_eval.IDENTITY,))[0]
        return None, scene_eval.IDENTITY

    def _new_node_place(self, w, h):
        """Local (x, y) that puts a w x h thing in the middle of the glass."""
        from ..plugins.stern import scene_eval
        parent, pw = self._tree_parent_for_add()
        sw, sh = self._tman["stage"][:2]
        inv = scene_eval.invert(pw) or scene_eval.IDENTITY
        x, y = scene_eval.apply(inv, (sw - w) / 2.0, (sh - h) / 2.0)
        return parent, round(x, 2), round(y, 2)

    @rpc
    def tree_add_picture(self):
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        src = self.window.ask_open("scene_add_picture", "Add a picture to this scene",
                                   filetypes=[("Pictures", "*.png *.jpg *.jpeg *.webp"),
                                              ("All files", "*.*")])
        if not src:
            return False
        try:
            from PIL import Image
            img = Image.open(src).convert("RGBA")
        except Exception as e:                       # noqa: BLE001
            compat.messagebox.showerror("Add picture", "That file isn't a picture PAD can "
                                        "read (%s)." % e)
            return False
        if img.size[0] > 2048 or img.size[1] > 2048:
            img.thumbnail((2048, 2048))
        stem = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in os.path.splitext(os.path.basename(src))[0])[:40] or "picture"
        rel_dir = os.path.join("scene_textures", "added")
        out_dir = os.path.join(self.assets_dir, "images", rel_dir)
        os.makedirs(out_dir, exist_ok=True)
        i = 1
        while os.path.exists(os.path.join(out_dir, "%s_%d.png" % (stem, i))):
            i += 1
        name = "%s_%d.png" % (stem, i)
        img.save(os.path.join(out_dir, name))
        ops = self._tree_ops(card)
        nid = scene_edit.new_id(self._tman, ops)
        w, h = img.size
        parent, x, y = self._new_node_place(w, h)
        self._tsel = nid
        return self._tree_add({
            "op": "add_picture", "parent": parent, "index": 1 << 20, "id": nid,
            "name": "PAD_%s" % stem, "image": "scene_textures/added/" + name,
            "w": w, "h": h, "x": x, "y": y})

    @rpc
    def tree_add_text(self, text, like=None):
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        text = (text or "").strip()
        if card is None or not text:
            return False
        texts = [d for d in self._tdraws if d["kind"] == "text"]
        like_id = None
        if like not in (None, ""):
            like_id = int(like)
        elif self._tsel is not None and any(d["node"] == self._tsel for d in texts):
            like_id = self._tsel
        elif texts:
            like_id = texts[0]["node"]
        if like_id is None:
            compat.messagebox.showinfo(
                "Add text", "This scene draws no text of its own at this moment, so there is "
                "no font in it to write with. Pick a moment where some text shows.")
            return False
        src = next(d for d in texts if d["node"] == like_id) if any(
            d["node"] == like_id for d in texts) else None
        rect = (src or {}).get("rect") or (0, 0, 400, 60)
        ops = self._tree_ops(card)
        nid = scene_edit.new_id(self._tman, ops)
        parent, x, y = self._new_node_place(rect[2] - rect[0], rect[3] - rect[1])
        self._tsel = nid
        return self._tree_add({
            "op": "add_text", "parent": parent, "index": 1 << 20, "id": nid,
            "name": "PAD_Text", "text": text, "x": x - rect[0], "y": y - rect[1],
            "like": like_id})


def _built_state(built, ops):
    """What "Back to the last Write" can do for a scene: ``none`` (no Write recorded),
    ``same`` (nothing changed since it) or ``changed``."""
    if built is None:
        return "none"
    return "same" if built == ops else "changed"


def _file_size(path):
    """A picture file's pixel size (its header only), or None."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:                                # noqa: BLE001
        return None


def _colour_switch(n, kind, pics, picks, settings, added_op):
    """A layer's colour switch for the Layers list (PAD-312): ``{"on", "own"}`` for a
    picture the chosen-files profile can reach (an added one, or one with an Images-tab
    replacement), ``{"locked": True}`` for the game's own picture, ``None`` for a layer that
    draws no single picture."""
    from ..core import colour_profile as _cp
    if added_op is not None:
        own = added_op.get("color")
        return {"on": _cp.asset_applies(settings, "images", added_op.get("image") or "",
                                        own=own),
                "own": own is not None, "added": True}
    if len(pics) != 1:
        return None
    rel = pics[0]
    if (picks.get(rel) or {}).get("path"):
        full = "images/" + rel
        return {"on": _cp.asset_applies(settings, "images", full),
                "own": settings["images"].get(full) is not None, "rel": full}
    if kind in ("Bitmap", "Shape", "StreamingFlipbook"):
        return {"locked": True}
    return None


def _kept_size(pick, assets_dir, rel, stock=None):
    """The size a picture is written at when it keeps its own size, else None.  A pick that
    keeps its own size is written at its file's size.  With no pick file the project's own
    file is drawn (scene_render._picture), which a Write has already made that size: the box
    is that file's size when the pick still says keep (DragonRR, PAD-332: the box stayed the
    stock size, up and left of the picture), or when the file is not the card's *stock*
    texture size, since a Write keeps such a file's size with no pick at all (DragonRR,
    PAD-337: picking one picture dropped the others' keep marks, and their boxes and
    pictures went back to the stock size)."""
    from ..plugins.stern import scene_render
    if pick.get("path"):
        return _file_size(pick["path"]) if pick.get("keep") else None
    size = _file_size(os.path.join(assets_dir, "images", *rel.split("/")))
    if pick.get("keep") or scene_render.own_size(size, stock):
        return size
    return None


def _walk_man(man):
    """``(node, parent node or None, depth)`` over a manifest's staged nodes, draw order."""
    out = []
    seen = set()

    def run(kids, parent, depth):
        for n in kids:
            out.append((n, parent, depth))
            for _s, oid in n["comps"]:
                o = man["objects"].get(str(oid)) or {}
                if o.get("kids") is not None and oid not in seen:
                    seen.add(oid)
                    run(o["kids"], n, depth + 1)

    run(man["root"]["kids"], None, 0)
    return out


def _pics_of(man, n, memo):
    """The pictures (rels under images/) node *n* draws, itself or through what it holds, in
    drawing order, each once: the Layers list's button to them on the Images tab (PAD-287).
    *memo* keeps each object's list for the next node that shows it."""
    objects = man["objects"]
    out = []
    for _s, oid in n["comps"]:
        if oid not in memo:
            memo[oid] = []                          # a group that holds itself stops here
            o = objects.get(str(oid)) or {}
            k = o.get("kind")
            if k == "Bitmap":
                rels = [o.get("image")]
            elif k == "Shape" and o.get("fill") is not None:
                rels = [(objects.get(str(o["fill"])) or {}).get("image")]
            elif k == "StreamingFlipbook":
                rels = [fr.get("image") for fr in o.get("seq") or () if fr]
            else:
                rels = []
            for kid in o.get("kids") or ():
                rels += _pics_of(man, kid, memo)
            memo[oid] = rels
        out += memo[oid]
    return list(dict.fromkeys(rel for rel in out if rel))


def _kind_of(man, n):
    kinds = [(man["objects"].get(str(oid)) or {}).get("kind") for _s, oid in n["comps"]]
    kinds = [k for k in kinds if k]
    return kinds[0] if kinds else "Group"


