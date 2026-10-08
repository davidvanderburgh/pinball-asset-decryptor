"""PAD-453: Undo / Redo on the Video tab.

Every change the page makes to the tab's picks is one step: a replacement chosen or cleared,
Replace from folder, Best quality's files put to use, a clip's conversion, length, colors or
random clips, and the boxes over the list (as-is, Trim / pad, Best quality, Advanced). A step
keeps only what that change moved, slot by slot, as it was and as it became, so Undo puts back
just that and Redo does it again; a change made elsewhere in between (the Colors bar's "Apply
to all", which has an Undo of its own) is left as it is.

The project folder follows the picks the way Clear makes it: a slot Undo leaves with nothing
to build that a build already gave its replacement gets the card's original file back, and a
mode's own clip (PAD-444) is made again when its pick comes back, and dropped when it goes.

The steps are kept per project folder and go with it: a scan of another folder, Revert all
(``clear_replace_assignments``), Load settings from a file, another manufacturer.

Store key (namespace ``video``):
  undo   {undo, redo}: what the next Undo / Redo would take back or do again ("" for nothing)
"""

import functools
import os

from .rpc import rpc

#: steps kept per project folder
UNDO_STEPS = 100

#: the picks' per-slot parts, and the boxes over the list
SLOT_PARTS = ("assign", "asis", "length", "color", "stock_on", "variants")
BOXES = ("trim", "no_conversion", "best_quality", "color_stock")

#: a slot a part had no entry for
_NONE = object()


def undoable(one, many=None):
    """Make an ``@rpc`` change to the picks one Undo step. *one* names it for the buttons
    ("the pick for %s": %s is the clip, when one slot moved); *many* when several did ("%d"
    their number), else *one* with "%d clips" for the clip."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, *a, **kw):
            if self._u_busy:
                return fn(self, *a, **kw)
            before = self._u_picks()
            self._u_busy = True
            try:
                return fn(self, *a, **kw)
            finally:
                self._u_busy = False
                self._u_note(one, many, before)
        return wrapper
    return deco


class UndoMixin:
    """Mixed into :class:`.tabs.video.VideoTab`."""

    def _u_init(self):
        self._u_busy = False
        self._u_undo = []
        self._u_redo = []
        self.set(undo={"undo": "", "redo": ""})

    def _u_reset(self):
        self._u_undo, self._u_redo = [], []
        self._u_publish()

    def _u_publish(self):
        self.set(undo={"undo": self._u_undo[-1]["what"] if self._u_undo else "",
                       "redo": self._u_redo[-1]["what"] if self._u_redo else ""})

    def _u_picks(self):
        return {
            "assign": dict(self._assign),
            "asis": dict(self._asis),
            "length": dict(self._length),
            "color": dict(self._color),
            "stock_on": dict.fromkeys(self._stock_on, True),
            "variants": {rel: tuple(v) for rel, v in self._variants.items() if v},
            "trim": bool(self.video_trim_var.get()),
            "no_conversion": bool(self.video_no_conversion_var.get()),
            "best_quality": bool(self.video_best_quality_var.get()),
            "color_stock": bool(self._color_stock),
        }

    def _u_note(self, one, many, before):
        """What a change moved since *before* becomes an Undo step (nothing moved: none)."""
        after = self._u_picks()
        slots, boxes = {}, {}
        for part in SLOT_PARTS:
            b, a = before[part], after[part]
            moved = {rel: (b.get(rel, _NONE), a.get(rel, _NONE))
                     for rel in set(b) | set(a) if b.get(rel, _NONE) != a.get(rel, _NONE)}
            if moved:
                slots[part] = moved
        for box in BOXES:
            if before[box] != after[box]:
                boxes[box] = (before[box], after[box])
        if not (slots or boxes):
            return
        rels = sorted({rel for moved in slots.values() for rel in moved})
        what = one
        if "%s" in one:
            if len(rels) == 1:
                what = one % os.path.basename(rels[0])
            else:
                what = (many % len(rels) if many and "%d" in many
                        else many or one.replace("%s", "%d clips" % len(rels)))
        self._u_undo.append({"what": what, "slots": slots, "boxes": boxes})
        del self._u_undo[:-UNDO_STEPS]
        self._u_redo = []
        self._u_publish()

    @rpc
    def undo(self, redo=False):
        """Undo (or Redo) the last change to the picks (Ctrl+Z; Ctrl+Y or Ctrl+Shift+Z)."""
        if self._u_busy or self._is_running():
            return False
        src, dst = (self._u_redo, self._u_undo) if redo else (self._u_undo, self._u_redo)
        if not src:
            return False
        step = src.pop()
        self._u_busy = True
        try:
            back = self._u_put(step, 1 if redo else 0)
        finally:
            self._u_busy = False
        dst.append(step)
        self.log("Replace Video: %s %s%s." % (
            "redid" if redo else "undid", step["what"],
            (" (%s the card's original file back in the project folder)"
             % ("its slot has" if len(back) == 1 else "%d slots have" % len(back)))
            if back else ""), "info")
        self._u_publish()
        return True

    def _u_put(self, step, side):
        """Give every part *step* moved its value from *side* (0 as it was, 1 as it became).
        Returns the slots whose original file was put back."""
        slots, boxes = step["slots"], step["boxes"]
        for box, pair in boxes.items():
            if box == "color_stock":
                self._color_stock = pair[side]
            else:
                getattr(self, "video_%s_var" % box).set(pair[side])
        made = False
        for rel, pair in (slots.get("assign") or {}).items():
            path = pair[side]
            if path is _NONE:
                self._assign.pop(rel, None)
            elif rel in self._by_rel:
                if rel in self._m_virtual:
                    # PAD-444: a mode's own clip is made again for its pick
                    if not self._m_materialize(rel):
                        continue
                    made = True
                self._assign[rel] = path
        if made:
            self._m_publish()
        for part in ("asis", "length", "color", "variants"):
            have = getattr(self, "_" + part)
            for rel, pair in (slots.get(part) or {}).items():
                value = pair[side]
                if value is _NONE:
                    have.pop(rel, None)
                elif rel in self._by_rel:
                    have[rel] = list(value) if part == "variants" else value
        for rel, pair in (slots.get("stock_on") or {}).items():
            if pair[side] is _NONE:
                self._stock_on.discard(rel)
            elif rel in self._by_rel:
                self._stock_on.add(rel)
        rels = sorted({rel for moved in slots.values() for rel in moved})
        # a slot left with nothing to build gets its original back, as Clear gives it
        bare = [rel for rel in rels
                if (rel in (slots.get("assign") or {}) or rel in (slots.get("stock_on") or {}))
                and not self._assign.get(rel) and rel not in self._stock_on]
        back = self._put_back(self._applied_rels(bare)) if bare else []
        self._save_staged()
        self._update_trim_enabled()
        if "best_quality" in boxes:
            self._best_set(on=bool(self.video_best_quality_var.get()))
        self._probe_conv_async()
        self._refresh_list()
        cur = self._current
        if cur and (cur in rels or "color_stock" in boxes):
            self._reload_rep_pane(cur)
        if cur:
            self._update_note(cur)
        self._update_clear_all()
        self._color_changed()
        self.publish_look()
        shown = set(self.get("view") or [])
        alive = [rel for rel in rels if self._index.get(rel) in shown]
        if alive:
            self._reselect(alive)
        # PAD-444: a mode's own clip whose pick went follows its shared clip again
        self._m_after_clear(rels)
        return back
