"""Lay out a mode's screen in the Scenes editor (PAD-323), its info line (PAD-547) and its scored number (PAD-709).

A mode's screen (its picture or generated panel, and its words) is not in the stock HUD scene
the editor shows: the Write splices it in (:func:`.mode_assets.build`).  "Lay out on the
screen..." on the Modes tab's Show page opens the editor on the title's HUD scene with the
mode's screen added as VIRTUAL layers - a group ``PadMode_<slug>_Screen`` holding the picture
and the words, drawn from the project where the build would put them - and the editor's own
tools work on them: drag or size the picture (the whole screen), move or size the words on
their own, send the screen under the HUD's own pictures.

PAD-547: a code or blocks mode's info line ("SUPER JACKPOT = 53,200,000", a screen of its own the
build adds as ``PadMode_<slug>_Info``) comes in beside it as a second set of virtual layers, placed
where the title's port puts it, and is laid out the same way into the mode's ``info_layout``. A mode
with the line and no screen lays out the line alone. Its picture is clear on the card; here it is a
faint band, so it can be seen and taken hold of.

PAD-709: a words-alone mode's scored number (``PadMode_<slug>_Points``: a shot's points, large under
the status bar while it runs) is a third part, laid out the same way into its ``points_layout``.

Those edits never go into ``scene_edits.json`` (keyed by node ids, which a mode's screen does
not keep: they are handed out at build in slot order).  Each one is turned at once into the
mode's ``screen_layout`` / ``info_layout`` / ``points_layout`` (:data:`.mode_assets.LAYOUT_KEYS`) in its ``mode.json``
- or a code mode's ``assets.json`` - keyed by the mode's folder, and the build reads it from
there; a key left at its automatic value is not written, so an untouched mode builds as before.
"""

import copy
import logging
import math
import os

from . import compat
from .rpc import rpc

log = logging.getLogger(__name__)

#: the virtual layers' preview ids (below scene_edit.FIRST_ADDED_ID: never a stock id or an add)
GROUP_ID = 0x7E000001
ART_ID = 0x7E000003
WORDS_ID = 0x7E000005
#: PAD-547: the info line's
INFO_GROUP_ID = 0x7E000007
INFO_ART_ID = 0x7E000009
INFO_WORDS_ID = 0x7E00000B
#: PAD-709: the scored number's
POINTS_GROUP_ID = 0x7E00000D
POINTS_ART_ID = 0x7E00000F
POINTS_WORDS_ID = 0x7E000011
#: each part a mode lays out: (group, picture, words) ids and the mode file's key for its layout
PART_IDS = {"screen": (GROUP_ID, ART_ID, WORDS_ID), "info": (INFO_GROUP_ID, INFO_ART_ID, INFO_WORDS_ID),
            "points": (POINTS_GROUP_ID, POINTS_ART_ID, POINTS_WORDS_ID)}
LAYOUT_KEY = {"screen": "screen_layout", "info": "info_layout", "points": "points_layout"}
#: what each part is called in the editor's note and its layers
PART_WHAT = {"screen": "screen", "info": "info line", "points": "scored number"}
#: PAD-709: what the scored number's stand-in says
POINTS_SAMPLE = "1,000,000"
VIRTUAL_IDS = tuple(i for ids in PART_IDS.values() for i in ids)
#: the build's words colour (scene_write.screen)
WORDS_RGBA = [1.0, 0.9, 0.0, 1.0]
#: PAD-547: the info line's (PAD-709: and the scored number's) stand-in picture: its strip, faintly, so it can be seen
#: and dragged
INFO_BAND_RGBA = (255, 255, 255, 40)
_ONLY = ("This is %s's own screen: here it can be moved, sized and put over or under the "
         "HUD's pictures. Its picture, colors and words are on the Modes tab's Show page.")


def part_of(nid):
    """The part (``"screen"`` / ``"info"`` / ``"points"``) a virtual layer belongs to, or None."""
    for key, ids in PART_IDS.items():
        if nid in ids:
            return key
    return None


def _hud_profile(card, man):
    """The measured :class:`.scene_write.SceneProfile` of the HUD scene at *card* whose
    insertion point is one of the manifest's root children (several titles share a scene id;
    the one measured on this file names a child it has)."""
    from ..plugins.stern import scene_write as SW
    kids = {(n["id"], n["name"]) for n in man["root"]["kids"]}
    found = None
    for p in SW.PROFILES.values():
        if p.scene_id not in card:
            continue
        ptr, name = p.insert_before
        if p.append or ((ptr & ~SW.FLAG), name) in kids:
            if found is None or not found.append:
                found = p
            if not p.append:
                return p
    return found


def default_order(prof, man):
    """The root index a screen with no ``order`` is drawn at: before the profile's child,
    or after the last one."""
    if prof is None or prof.append:
        return len(man["root"]["kids"])
    ptr, name = prof.insert_before
    for i, n in enumerate(man["root"]["kids"]):
        if n["id"] == ptr & 0x7FFFFFFF and n["name"] == name:
            return i
    return len(man["root"]["kids"])


def _parts(ml):
    """The parts of the session *ml* in the order they are drawn (the line over the screen). A session made before
    PAD-547 (tests build one by hand) is its screen alone."""
    if "parts" in ml:
        return [(k, ml["parts"][k]) for k in ("screen", "info", "points") if ml["parts"].get(k)]
    return [("screen", ml)]


def inject(man, ml, prof):
    """A copy of manifest *man* with the mode's screen (and its info line) in it as virtual
    layers, placed as *ml* (the layout session) says.  The copy shares the stock objects
    (apply_manifest copies it whole before editing)."""
    out = dict(man)
    out["objects"] = dict(man["objects"])
    root = dict(man["root"])
    kids = list(root["kids"])
    root["kids"] = kids
    out["root"] = root
    ox, oy = prof.origin if prof is not None else (0.0, 0.0)
    like = _words_like(man, prof)
    adds = []
    for seq, (key, pt) in enumerate(_parts(ml)):
        g_id, a_id, w_id = PART_IDS[key]
        place = pt["place"] if "place" in pt else ml["place"]
        s = place["scale"]
        w, h = pt["size"]
        art = {"id": a_id, "name": pt["art_name"], "kf": [[1, 1]], "col": [],
               "tr": [[1, [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]]], "comps": [[1, a_id + 1]],
               "virtual": True}
        out["objects"][str(a_id + 1)] = {"kind": "Bitmap", "w": w, "h": h, "tex": None,
                                         "image": pt["pic_rel"]}
        group_kids = [art]
        if like is not None:
            ws = place["words_scale"]
            wx, wy = place["words_at"]
            group_kids.append({"id": w_id, "name": pt["words_name"], "kf": [[1, 1]], "col": [],
                               "tr": [[1, [ws, 0.0, 0.0, ws, wx, wy]]], "comps": [[1, w_id + 1]],
                               "virtual": True})
            txt = copy.deepcopy(like)
            txt.update(text=pt["words"], rect=[0.0, -40.0, float(w), 48.0],
                       rgba=list(pt.get("words_rgba") or WORDS_RGBA),
                       align=prof.text_align, spacing=list(prof.text_spacing), flags=[0, 0])
            out["objects"][str(w_id + 1)] = txt
        out["objects"][str(g_id + 1)] = {"kind": "Sprite", "name": "", "frames": 1,
                                         "labels": [], "kids": group_kids}
        group = {"id": g_id, "name": pt["name"], "kf": [[1, 1]], "col": [],
                 "tr": [[1, [s, 0.0, 0.0, s, place["x"] - ox, place["y"] - oy]]],
                 "comps": [[1, g_id + 1]], "virtual": True}
        at = place["order"] if place["order"] is not None else default_order(prof, man)
        adds.append((max(0, min(len(kids), int(at))), seq, group))
    # each at its index among the stock children: the highest first, so the others' indices still hold; at the same
    # index the later part goes in first, so it ends up after (over) the earlier one
    for at, _seq, group in sorted(adds, key=lambda t: (-t[0], -t[1])):
        kids.insert(at, group)
    return out


def _words_like(man, prof):
    """A Text of the scene in the font the build gives the words (the profile's), or None
    when the scene has no font for them (the build then adds no words line either)."""
    if prof is None or not prof.font:
        return None
    best = None
    for o in man["objects"].values():
        if not o or o.get("kind") != "Text":
            continue
        if o.get("font_id") == prof.font[0]:
            return o
        if best is None and o.get("font_name") == prof.font[1]:
            best = o
    return best


def layout_of(man, ml, prof, key="screen"):
    """The layout the virtual layers of part *key* in the edited manifest *man* stand for: only
    what differs from the automatic placement (the part's ``auto``)."""
    from ..plugins.stern import scene_edit
    g_id, _a_id, w_id = PART_IDS[key]
    pt = dict(_parts(ml)).get(key, ml)
    index = scene_edit._man_index(man)
    auto = pt["auto"]
    ox, oy = prof.origin if prof is not None else (0.0, 0.0)
    out = {}
    g = index.get(g_id)
    if g is not None:
        a, b, _c, _d, tx, ty = g[0]["tr"][0][1]
        x, y, s = tx + ox, ty + oy, math.hypot(a, b)
        if abs(x - auto["x"]) > 0.05 or abs(y - auto["y"]) > 0.05:
            out["x"], out["y"] = round(x, 1), round(y, 1)
        if abs(s - 1.0) > 1e-4:
            out["scale"] = round(s, 4)
        kids = man["root"]["kids"]
        if g[0] in kids:
            pos = kids.index(g[0])
            stock = sum(1 for n in kids[:pos] if not n.get("added") and not n.get("virtual"))
            if stock != auto["order"]:
                out["order"] = stock
    wd = index.get(w_id)
    if wd is not None:
        a, b, _c, _d, tx, ty = wd[0]["tr"][0][1]
        wx, wy = auto["words_at"]
        if abs(tx - wx) > 0.05 or abs(ty - wy) > 0.05:
            out["words_x"], out["words_y"] = round(tx, 1), round(ty, 1)
        ws = math.hypot(a, b)
        if abs(ws - pt.get("words_scale0", 1.0)) > 1e-4:
            out["words_scale"] = round(ws, 4)
    return out


def _and(words):
    """``a``, ``a and b``, ``a, b and c``."""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else ""


def info_words(assets, slug):
    """PAD-547: what the info line's stand-in says in the editor - the blocks program's words and a sample value
    ("SUPER JACKPOT = 1,234,567"), or a plain label for a mode in C."""
    from ..plugins.stern import block_modes as BM
    try:
        info = BM.normalize(BM.load(assets, slug))["info"]
    except Exception:                                # noqa: BLE001 - a mode in C, or no program
        return "INFO LINE = 1,234,567"
    text = info["text"]
    if info["value"] is None:
        return text or "INFO LINE"
    return (text + " = 1,234,567") if text else "1,234,567"


class ModeLayoutMixin:
    """Mixed into ``TextScenesService`` ahead of ``TreeEditMixin``: the layout session."""

    _mlay = None

    # ------------------------------------------------------------------
    # the session
    # ------------------------------------------------------------------
    def open_mode_layout(self, assets, slug):
        """Open the editor on the HUD scene of *assets*' card with mode *slug*'s screen (and
        its info line) in it.  Returns ``(True, "")`` or ``(False, why)``."""
        try:
            ml = self._mlay_build(assets, slug)
        except Exception as e:                       # noqa: BLE001 - said, not raised
            log.exception("mode layout")
            return False, str(e)
        if isinstance(ml, str):
            return False, ml
        self._mlay = ml
        self.open(assets, preselect_dir=ml["scene_dir"])
        card, _man = self._tree_card(ml["scene_dir"])
        if card is None:
            self._mlay = None
            self.set(mode_layout=None)
            return False, ("this project has no drawing of the HUD scene yet: Re-read from card "
                           "on the Scenes tab, then try again")
        if self._sel != ml["scene_dir"]:
            self.select(ml["scene_dir"])
        first = PART_IDS[_parts(ml)[0][0]][0]
        self._tsel, self._tsels = first, [first]
        self._mlay_state()
        self._render_tree_preview(self._sel)
        return True, ""

    def _mlay_part(self, key, screen, layout, pic, pic_rel, words_scale0=1.0):
        """One part of the session from its build screen (:func:`.mode_assets.code_screen` / ``info_screen``)."""
        import numpy as np
        from PIL import Image
        art = np.asarray(screen["art_rgba"], dtype=np.uint8)
        if key in ("info", "points"):                 # clear on the card: a faint band here, to see and to take
            art = np.empty_like(art)
            art[:] = INFO_BAND_RGBA
        Image.fromarray(art, "RGBA").save(pic)
        h, w = art.shape[:2]
        words_at = screen["words_at"] if screen.get("words_at") is not None else (20.0, h + 50.0)
        auto = {"x": screen["x"], "y": screen["y"], "words_at": tuple(words_at), "order": None}
        return {"name": screen["name"], "art_name": screen["name"] + "_Art",
                "words_name": screen["words_name"], "words": screen["words"],
                "words_rgba": list(screen.get("words_rgba") or WORDS_RGBA), "words_scale0": words_scale0,
                "size": (w, h), "pic": pic, "pic_rel": pic_rel,
                "auto": auto, "layout": layout}

    def _mlay_build(self, assets, slug):
        """The session for mode *slug*: where its screen (and its info line) go and what they
        show, or a sentence saying why it cannot be laid out."""
        from ..plugins.stern import code_modes as CM
        from ..plugins.stern import mode_assets as MA
        from ..plugins.stern import mode_project as MP
        folder = MP.mode_folder(assets, slug)
        if os.path.isfile(os.path.join(folder, MP.MODE_FILE)):
            kind, spec = "form", MP.load(os.path.join(folder, MP.MODE_FILE))
            screen = MA.form_screen(assets, slug, spec) if spec.screen else None
        else:
            kind, spec = "code", CM.load(assets, slug)
            screen = MA.code_screen(assets, slug, spec) if spec.screen else None
        has_info = kind == "code" and bool(getattr(spec, "info_line", False))
        # PAD-709: a words-alone screen's scored number, under the bar
        has_points = kind == "code" and screen is not None and getattr(spec, "screen_style", "") == "words"
        if screen is None and not has_info:
            return "%s has no screen of its own: tick Show a screen first" % spec.name
        _card, prof = MP.project_profile(assets, probe=False)
        if prof is None:
            try:
                prof = (MP.profile(spec.title) if kind == "form"
                        else CM.profile_for(assets, [(slug, spec)]))
            except MP.ModeProjectError as e:
                return str(e)
        if prof is None or not prof.can("screen") or not prof.lcd("hud"):
            return "a mode cannot show a screen of its own on this game"
        parts = {}
        if screen is not None:
            parts["screen"] = self._mlay_part("screen", screen, dict(MA.clean_layout(spec.screen_layout)),
                                              os.path.join(self._tmpdir(), "mode_screen_%s.png" % slug),
                                              "padmode_layout/%s.png" % slug,
                                              # PAD-521's words over the video are built twice the size: drawn so here too
                                              screen.get("words_scale", 1.0))
        if has_info:
            info = dict(MA.info_screen(MP.asset_names(slug), prof), words=info_words(assets, slug))
            parts["info"] = self._mlay_part("info", info, dict(MA.clean_layout(getattr(spec, "info_layout", None))),
                                            os.path.join(self._tmpdir(), "mode_info_%s.png" % slug),
                                            "padmode_layout/%s_info.png" % slug, info.get("words_scale", 1.0))
        if has_points:
            pts = dict(MA.points_screen(MP.asset_names(slug), prof), words=POINTS_SAMPLE)
            parts["points"] = self._mlay_part("points", pts, dict(MA.clean_layout(getattr(spec, "points_layout", None))),
                                              os.path.join(self._tmpdir(), "mode_points_%s.png" % slug),
                                              "padmode_layout/%s_points.png" % slug, pts["words_scale"])
        return {"slug": slug, "kind": kind, "mode": spec.name, "assets": assets,
                "scene_dir": "/%s/%s" % (prof.game_dir, prof.lcd("hud")),
                "parts": parts, "undo": [], "redo": []}

    def _mlay_on(self, card):
        ml = self._mlay
        return bool(ml and card and ml["assets"] == self.assets_dir
                    and card.replace("\\", "/").rsplit("/", 1)[0] == ml["scene_dir"])

    def _mlay_layouts(self):
        """Every part's layout now, {key: layout}: one undo step."""
        return {k: dict(pt["layout"]) for k, pt in _parts(self._mlay)}

    def _mlay_place(self, man, prof, pt):
        """Where a part's virtual layers go now: the automatic place with its layout over it."""
        auto, lay = pt["auto"], pt["layout"]
        if auto["order"] is None:
            auto["order"] = default_order(prof, man)
        return {"x": lay.get("x", auto["x"]), "y": lay.get("y", auto["y"]),
                "scale": lay.get("scale", 1.0),
                "words_scale": lay.get("words_scale", pt.get("words_scale0", 1.0)),
                "words_at": ((lay["words_x"], lay["words_y"]) if "words_x" in lay
                             else auto["words_at"]),
                "order": lay.get("order")}

    def _mlay_state(self):
        ml = self._mlay
        if ml is None:
            self.set(mode_layout=None)
            return
        parts = dict(_parts(ml))
        scr = parts.get("screen")
        self.set(mode_layout={
            "mode": ml["mode"], "slug": ml["slug"], "scene_dir": ml["scene_dir"],
            # PAD-547: what is being laid out, for the editor's note
            "what": _and([PART_WHAT[k] for k in ("screen", "info", "points") if k in parts]),
            "laid_out": any(pt["layout"] for pt in parts.values()),
            "under": bool(scr) and scr["layout"].get("order") is not None
                     and scr["layout"]["order"] < (scr["auto"]["order"] or 0)})

    @rpc
    def mode_layout_done(self):
        """Done: the mode's screen leaves the editor (its layout is in the mode already) and
        the Modes tab comes back."""
        self._mlay = None
        self._tsel, self._tsels = None, []
        self._mlay_state()
        if self._sel:
            self._render_tree_preview(self._sel)
        try:
            self.window.select_tab("modes")
        except Exception:                            # noqa: BLE001
            pass
        return True

    @rpc
    def mode_layout_auto(self):
        """Back to the automatic placement: the layouts come out of the mode."""
        if self._mlay is None or not any(pt["layout"] for _k, pt in _parts(self._mlay)):
            return False
        return self._mlay_put({k: {} for k, _pt in _parts(self._mlay)})

    def _mlay_put(self, layouts, step=True):
        """Save *layouts* ({part: layout}) into the mode's file, as one undo step."""
        from ..plugins.stern import code_modes as CM
        from ..plugins.stern import mode_project as MP
        ml = self._mlay
        parts = dict(_parts(ml))
        layouts = {k: dict(v) for k, v in layouts.items() if k in parts}
        if all(parts[k]["layout"] == v for k, v in layouts.items()):
            return False
        before = self._mlay_layouts()
        try:
            if ml["kind"] == "form":
                path = os.path.join(MP.mode_folder(ml["assets"], ml["slug"]), MP.MODE_FILE)
                spec = MP.load(path)
            else:
                spec = CM.load(ml["assets"], ml["slug"])
            for k, v in layouts.items():
                setattr(spec, LAYOUT_KEY[k], dict(v))
            if ml["kind"] == "form":
                MP.save(ml["assets"], ml["slug"], spec)
            else:
                CM.save(ml["assets"], ml["slug"], spec)
        except (OSError, ValueError) as e:
            compat.messagebox.showerror("Mode screen", "The layout could not be saved into %s: %s"
                                        % (ml["mode"], e))
            return False
        if step:
            ml["undo"].append(before)
            ml["redo"] = []
        for k, v in layouts.items():
            parts[k]["layout"] = v
        self._mlay_state()
        self._trev += 1
        self._mlay_modes_changed()
        if self._sel:
            self._render_tree_preview(self._sel)
        return True

    def _mlay_modes_changed(self):
        """The Modes tab shows what the mode's file says: tell it the file changed."""
        try:
            modes = self.window.service("modes")
            fn = getattr(modes, "layout_changed", None)
            if callable(fn):
                fn(self._mlay["slug"])
        except Exception:                            # noqa: BLE001
            log.exception("modes tab")

    def _mlay_ops(self, ops):
        """Edits the page made to the virtual layers, turned into the mode's layouts.  A part's
        picture is that part: moving or sizing it moves or sizes its whole group, as the build
        places the group.  What a mode's screen cannot take is said, not done."""
        from ..plugins.stern import scene_edit
        card, _man = self._tree_card()
        if self._tman is None:
            return False
        index = scene_edit._man_index(self._tman)
        mine, touched = [], []
        for op in ops:
            k = op.get("op")
            node = op.get("node")
            key = part_of(node)
            if key is None or key not in dict(_parts(self._mlay)):
                continue
            g_id, a_id, _w_id = PART_IDS[key]
            group = index.get(g_id)
            a, b, c, d = (group[0]["tr"][0][1][:4] if group and group[0]["tr"]
                          else (1.0, 0.0, 0.0, 1.0))
            if k == "move" and node == a_id:
                # the drag came in the picture's parent's units (the group's own, scaled):
                # the group moves in ITS parent's, so the step is put through the group's matrix
                dx, dy = op["dx"], op["dy"]
                mine.append(dict(op, node=g_id, dx=round(a * dx + c * dy, 3),
                                 dy=round(b * dx + d * dy, 3)))
            elif k in ("move", "scale"):
                # a size about a point of the picture is about the same point of the group:
                # the picture sits at the group's origin, unscaled
                mine.append(dict(op, node=g_id if node == a_id else node))
            elif k == "order" and node == g_id:
                mine.append(op)
            elif k == "order":
                continue                              # the picture and words keep their order
            else:
                compat.messagebox.showinfo("Mode screen", _ONLY % self._mlay["mode"])
                return False
            if key not in touched:
                touched.append(key)
        if not mine:
            return False
        man, notes = scene_edit.apply_manifest(self._tman, mine)
        if notes:
            log.info("mode layout: %s", notes)
        prof = _hud_profile(card, man)
        return self._mlay_put({k: layout_of(man, self._mlay, prof, k) for k in touched})

    # ------------------------------------------------------------------
    # hooks into the tree editor
    # ------------------------------------------------------------------
    def _mlay_owns(self, op):
        return self._mlay is not None and (op.get("node") in VIRTUAL_IDS)

    def _tree_edited(self, card, man):
        if self._mlay_on(card) and man is not None:
            prof = _hud_profile(card, man)
            for _k, pt in _parts(self._mlay):
                pt["place"] = self._mlay_place(man, prof, pt)
            man = inject(man, self._mlay, prof)
        return super()._tree_edited(card, man)

    def _tree_pictures(self):
        pics = super()._tree_pictures()
        if self._mlay is not None:
            pics = dict(pics or {})
            for _k, pt in _parts(self._mlay):
                pics[pt["pic_rel"]] = {"path": pt["pic"], "keep": True}
        return pics

    def _tree_add(self, op):
        if self._mlay_owns(op):
            return self._mlay_ops([op])
        return super()._tree_add(op)

    def _tree_add_group(self, ops):
        mine = [op for op in ops or () if self._mlay_owns(op)]
        if mine:
            done = self._mlay_ops(mine)
            rest = [op for op in ops if not self._mlay_owns(op)]
            return super()._tree_add_group(rest) if rest else done
        return super()._tree_add_group(ops)

    def _tree_props(self, card, man, nid, ops):
        out = super()._tree_props(card, man, nid, ops)
        key = part_of(nid) if self._mlay is not None else None
        pt = dict(_parts(self._mlay)).get(key) if key else None
        if pt is not None:
            lay = pt["layout"]
            s = (lay.get("words_scale", pt.get("words_scale0", 1.0)) if nid == PART_IDS[key][2]
                 else lay.get("scale", 1.0))
            out.update(scale=round(s * 100), scale_y=round(s * 100), mode_screen=True,
                       added=False)
        return out

    def _tree_publish(self, card, man, frame, notes=()):
        super()._tree_publish(card, man, frame, notes)
        if not self._mlay_on(card):
            return
        parts = dict(_parts(self._mlay))
        tv = dict(self.store.get(self.ns, "tree_view") or {})
        layers = []
        for layer in tv.get("layers") or ():
            key = part_of(layer["id"])
            if key in parts:
                what = "the mode's " + PART_WHAT[key]
                layer = dict(layer, mode=True, edits=("laid out by you" if parts[key]["layout"]
                                                      else what + ", placed automatically"))
            layers.append(layer)
        tv["layers"] = layers
        h = (self._tree_hist(card) or {})
        tv["can_undo"] = bool(self._mlay["undo"]) or tv.get("can_undo", False)
        tv["can_redo"] = bool(self._mlay["redo"]) or bool(h.get("redo"))
        self.set(tree_view=tv)

    def _mlay_refuse(self, nodes):
        if self._mlay is not None and any(int(n) in VIRTUAL_IDS for n in nodes):
            compat.messagebox.showinfo("Mode screen", _ONLY % self._mlay["mode"])
            return True
        return False

    @rpc
    def tree_reset(self, node):
        """As made, on the mode's screen or its info line: the picture (the whole part) or the
        words go back to their automatic place."""
        key = part_of(int(node)) if self._mlay is not None else None
        pt = dict(_parts(self._mlay)).get(key) if key else None
        if pt is not None:
            keys = (("words_x", "words_y", "words_scale") if int(node) == PART_IDS[key][2]
                    else ("x", "y", "scale", "order"))
            return self._mlay_put({key: {k: v for k, v in pt["layout"].items() if k not in keys}})
        return super().tree_reset(node)

    @rpc
    def tree_remove(self, node):
        if self._mlay_refuse([node]):
            return False
        return super().tree_remove(node)

    @rpc
    def tree_remove_many(self, nodes):
        if self._mlay_refuse(self._tree_nodes(nodes)):
            return False
        return super().tree_remove_many(nodes)

    @rpc
    def tree_visible(self, node, on):
        if self._mlay_refuse([node]):
            return False
        return super().tree_visible(node, on)

    @rpc
    def tree_visible_many(self, nodes, on):
        if self._mlay_refuse(self._tree_nodes(nodes)):
            return False
        return super().tree_visible_many(nodes, on)

    @rpc
    def tree_game_mark(self, nodes, on):
        if self._mlay_refuse(self._tree_nodes(nodes)):     # before the first-hide warning
            return False
        return super().tree_game_mark(nodes, on)

    @rpc
    def tree_undo(self):
        """Back one step: while a mode's screen is laid out, its layout's steps first."""
        if self._mlay is not None and self._mlay["undo"]:
            ml = self._mlay
            ml["redo"].append(self._mlay_layouts())
            return self._mlay_put(ml["undo"].pop(), step=False) or True
        return super().tree_undo()

    @rpc
    def tree_redo(self):
        if self._mlay is not None and self._mlay["redo"]:
            ml = self._mlay
            ml["undo"].append(self._mlay_layouts())
            return self._mlay_put(ml["redo"].pop(), step=False) or True
        return super().tree_redo()
