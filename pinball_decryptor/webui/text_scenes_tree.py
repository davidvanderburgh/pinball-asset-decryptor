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
        self._tdraws = []            # the draw list of the last render
        self._tworlds = {}
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
                return card, man
        return None, None

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
        peek = self._tpeek if self._tpeek is not None and self._tpeek == self._tsel else None
        draws = scene_eval.draw_list(man, frame, pins=pins, worlds=worlds, show=peek)
        self._tdraws, self._tworlds, self._tman = draws, worlds, man
        self._tparents = {n["id"]: (par["id"] if par else None)
                          for n, par, _d in _walk_man(man)}
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
        return scene_render.pending_pictures(self.assets_dir)

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
               "text_edits": self._pending_texts(card, None), "colors": self._pending_colors(card),
               "pictures": self._tree_pictures(), "sizes": self._tree_sizes(),
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
                draws = scene_eval.draw_list(job["man"], f, pins=job["pins"], play=True)
                if prev is None or not scene_eval._same(draws, prev):
                    prev = draws
                    scaled = [dict(d, m=scene_eval.compose(shrink, d["m"])) for d in draws]
                    img = scene_render.render_tree(
                        job["assets"], small, draws=scaled, fonts=self._fonts,
                        background=job["bg"], colors=job["colors"],
                        text_edits=job["text_edits"], cache=job["cache"],
                        pictures=job["pictures"], sizes=job["sizes"], inks=inks)
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
                pictures=job.get("pictures"), sizes=job.get("sizes"))
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
        layers = []
        index = scene_edit._man_index(man)
        for n, _parent, depth in _walk_man(man):
            kind = _kind_of(man, n)
            layers.append({"id": n["id"], "name": n["name"], "depth": depth, "kind": kind,
                           "drawn": n["id"] in drawn or n["id"] in self._tworlds,
                           "added": bool(n.get("added")),
                           "hidden": any(op["op"] == "visible" and op.get("node") == n["id"]
                                         for op in ops),
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
                "peek": nid == self._tpeek and nid in self._tworlds}

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
        if node is not None and node not in self._tworlds and not any(
                op["op"] == "visible" and op.get("node") == node
                for op in self._tree_ops(card)):
            self._tpeek = node
            self._render_tree_preview(self._sel)
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
            return self.tree_visible_many(own, False)
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

        def shows(f, pn):
            key = (f, tuple(sorted(pn.items())))
            if key in tried:
                return False
            tried.add(key)
            for d in scene_eval.draw_list(man, f, pins=pn):
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
        self._tree_refresh()
        return True

    @rpc
    def tree_remove(self, node):
        """An ADDED node is removed; the game's own is hidden (its code finds it by name)."""
        node = int(node)
        got = [n for n, _p, _d in _walk_man(self._tman) if n["id"] == node]
        if got and got[0].get("added"):
            return self.tree_reset(node)
        return self.tree_visible(node, False)

    @rpc
    def tree_undo(self):
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if card is None:
            return False
        scene_edit.undo(self.assets_dir, card)
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
        self._tsel = None
        self._tree_refresh()
        return True

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


def _kind_of(man, n):
    kinds = [(man["objects"].get(str(oid)) or {}).get("kind") for _s, oid in n["comps"]]
    kinds = [k for k in kinds if k]
    return kinds[0] if kinds else "Group"


