"""PAD-444: the Video tab's "Played in": which of the game's own modes plays each clip, a
filter to list one mode's clips, and a mode's own copy of a clip it shares with another.

The reading is :mod:`..plugins.stern.clip_modes`' (the card's game program, read once per card
off the UI thread and cached on disk); this mixin is the tab's side: the rows' ``modes`` cell,
the ``modes`` namespace key the toolbar and the callout under the panes read, and the two
actions. A copy is a new file in the project's ``video`` folder - the shared clip's file,
copied - recorded in ``.staged_changes.json`` (``own_clips``), so it is a slot like any other:
a replacement is picked for it on this tab, and Write makes it a clip of its own on the card.

Store keys (namespace ``video``):
  modes        {ready, busy, note, list: [{id, label, n}], filter}
  rows[i]      + modes (labels), shared (bool), copy (the mode whose copy the row is, a label)
  preview      + modes: {rel, shared: [{id, label}], copy: {label, of, on_card}} or None
"""

import os
import shutil
import threading

from . import compat
from .tabs.base import rpc

#: what the callout under the panes says, and the confirmation (one place, for the tests)
SHARED_TEXT = ("Played in %s. Give one of them its own copy, then choose a replacement for "
               "that copy: only that mode changes.")
COPY_TEXT = ("%s's own copy of %s. Choose a replacement for it like any clip: %s plays it "
             "and %s keeps the shared clip. The card gets it as a new clip on an image build "
             "(a direct SD write leaves it out).")
CONFIRM = ("Give %s its own copy of %s?\n\nThe copy starts as the same footage, as a new row "
           "on this tab (%s). Choose a replacement for that row and only %s plays it; %s keeps "
           "%s.\n\nWrite puts the copy on the card as a new clip, so it needs an image build, "
           "not a direct SD write.")
NOT_HERE = ("Played in: the card the project was extracted from is needed to tell which "
            "mode plays which clip")


def _and(words):
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


class ModesMixin:
    """Mixed into :class:`.tabs.video.VideoTab`."""

    def _m_init(self):
        self._m_clips = None          # clip_modes.CardClips of the project's card
        self._m_key = None            # (project, card, its size and time) it was read for
        self._m_run = 0
        self._m_filter = ""           # a mode class, "" for every clip
        self._m_modes = {}            # rel -> [mode class], copies counted
        self._m_copy = {}             # rel -> the record of the copy the row is
        self.set(modes={"ready": False, "busy": False, "note": "", "list": [], "filter": ""})

    def _m_reset(self):
        self._m_run += 1
        self._m_clips = None
        self._m_key = None
        self._m_modes = {}
        self._m_copy = {}
        self._m_filter = ""
        self.set(modes={"ready": False, "busy": False, "note": "", "list": [], "filter": ""})

    # -- reading the card ------------------------------------------------------------------
    def _m_card(self, project):
        try:
            from ..plugins.stern import mode_project as MP
            card = MP.project_card(project)
        except Exception:                                   # noqa: BLE001
            card = None
        return getattr(card, "image", "") or ""

    def _m_kick(self, project):
        """After a scan: read which mode plays each clip, once per card (Stern only)."""
        if self._mfr_key() != "stern" or not project:
            self._m_reset()
            return
        card = self._m_card(project)
        try:
            st = os.stat(card) if card else None
        except OSError:
            st = None
        key = (os.path.normcase(project), card, st.st_size if st else 0,
               int(st.st_mtime) if st else 0)
        if key == self._m_key and self._m_clips is not None:
            self._m_publish()
            return
        self._m_run += 1
        run = self._m_run
        self._m_key = key
        cur = dict(self.get("modes") or {})
        cur.update(busy=True, ready=False)
        self.set(modes=cur)

        def _work():
            from ..plugins.stern import clip_modes as CM
            try:
                got = CM.read_card(card, CM.manifest_rows(project),
                                   cancel=lambda: self._m_run != run)
            except Exception as e:                          # noqa: BLE001 - never break the tab
                got = CM.CardClips(card=card, note="the card could not be read (%s)" % e)

            def _apply():
                if self._m_run != run:
                    return
                self._m_clips = got
                self._m_publish()
                self._refresh_list()
                if self._current:
                    self._update_note()
            self.ctx.loop.post(_apply)

        threading.Thread(target=_work, daemon=True, name="video-modes").start()

    def _m_records(self):
        from ..plugins.stern import clip_modes as CM
        return CM.records(self._scan_dir) if self._scan_dir else []

    def _m_publish(self):
        """Each row's modes (the copies the project holds counted as they will be on the
        card after the next Write) and the toolbar's list."""
        clips = self._m_clips
        self._m_modes, self._m_copy = {}, {}
        if clips is None:
            return
        reading = clips.reading
        for rel, name in clips.name_of.items():
            ms = reading.modes_of(name)
            if ms:
                self._m_modes[rel] = list(ms)
        by_name = {n: rel for rel, n in clips.name_of.items()}
        from ..plugins.stern import clip_modes as CM
        recs = self._m_records()
        named = {r["name"] for r in recs}
        for rel, name in clips.name_of.items():
            # a copy an earlier build put on the card, extracted again: still a copy
            got = None if name in named else CM.copy_of(name, by_name, reading.labels)
            if got and got[1] in self._m_modes.get(rel, ()):
                self._m_copy[rel] = {"name": name, "clip": got[0], "mode": got[1], "rel": rel,
                                     "of": by_name.get(got[0], ""), "state": "own"}
        for rec in recs:
            of = rec.get("of") or by_name.get(rec["clip"])
            mine = rec.get("rel") or by_name.get(rec["name"])
            if rec.get("state") == "shared":
                if of and rec["mode"] not in self._m_modes.get(of, []):
                    self._m_modes.setdefault(of, []).append(rec["mode"])
                if mine:
                    self._m_modes[mine] = [m for m in self._m_modes.get(mine, [])
                                           if m != rec["mode"]]
                continue
            if of in self._m_modes:
                self._m_modes[of] = [m for m in self._m_modes[of] if m != rec["mode"]]
            if mine:
                self._m_modes[mine] = [rec["mode"]]
                self._m_copy[mine] = rec
        counts = {}
        for rel, ms in self._m_modes.items():
            if rel in self._by_rel:
                for m in ms:
                    counts[m] = counts.get(m, 0) + 1
        modes = sorted(counts, key=lambda m: (reading.label(m).lower(), m))
        if self._m_filter and self._m_filter not in counts:
            self._m_filter = ""
        note = clips.note or ("" if modes else "no clip of this card is one of its modes'")
        self.set(modes={"ready": True, "busy": False, "note": note,
                        "list": [{"id": m, "label": reading.label(m), "n": counts[m]}
                                 for m in modes],
                        "filter": self._m_filter})

    def _m_label(self, mode):
        clips = self._m_clips
        if clips is not None:
            return clips.reading.label(mode)
        from ..plugins.stern import clip_modes as CM
        return CM.mode_label(mode)

    def _m_row(self, rel):
        """The row's Played in cells."""
        ms = self._m_modes.get(rel) or []
        copy = self._m_copy.get(rel)
        return {"modes": [self._m_label(m) for m in ms], "shared": len(ms) > 1,
                "copy": self._m_label(copy["mode"]) if copy else ""}

    def _m_keep(self, rel):
        """Whether the mode filter keeps *rel* in the list."""
        return not self._m_filter or self._m_filter in (self._m_modes.get(rel) or ())

    def _m_preview(self, rel):
        """The callout's Played in part for the row on show, or None."""
        if not rel or self._m_clips is None:
            return None
        copy = self._m_copy.get(rel)
        if copy is not None:
            of = copy.get("of") or ""
            on_card = rel in (self._m_clips.name_of or {})
            others = [self._m_label(m) for m in self._m_modes.get(of, ())
                      if m != copy["mode"]]
            label = self._m_label(copy["mode"])
            return {"rel": rel, "shared": [],
                    "copy": {"label": label, "of": os.path.basename(of) or copy["clip"],
                             "on_card": on_card,
                             "text": COPY_TEXT % (label, copy["clip"], label,
                                                  _and(others) or "every other mode")}}
        ms = self._m_modes.get(rel) or []
        if len(ms) < 2:
            return None
        labels = [self._m_label(m) for m in ms]
        return {"rel": rel, "copy": None,
                "shared": [{"id": m, "label": lab} for m, lab in zip(ms, labels)],
                "text": SHARED_TEXT % _and(labels)}

    # -- the filter ------------------------------------------------------------------------
    @rpc
    def set_mode_filter(self, mode):
        self._m_filter = str(mode or "")
        cur = dict(self.get("modes") or {})
        cur["filter"] = self._m_filter
        self.set(modes=cur)
        self._refresh_list()
        return True

    # -- a mode's own copy -----------------------------------------------------------------
    @rpc
    def own_copy(self, rel, mode, confirm=True):
        """Give *mode* its own copy of the clip *rel* (which it shares). Returns the copy's
        rel, or "" when nothing was made."""
        from ..plugins.stern import clip_modes as CM
        clips = self._m_clips
        project = self._scan_dir
        if (clips is None or not project or self._is_running()
                or mode not in (self._m_modes.get(rel) or ())
                or len(self._m_modes.get(rel) or ()) < 2 or rel in self._m_copy):
            return ""
        clip = clips.name_of.get(rel)
        if not clip:
            return ""
        recs = self._m_records()
        back = next((r for r in recs if r["clip"] == clip and r["mode"] == mode
                     and r.get("state") == "shared"), None)
        if back is not None:
            # the card already has this mode's copy and the project had put it back: the
            # card's copy again, nothing new to make
            CM.save_records(project, [r for r in recs if r is not back])
            self._m_history("video  %s plays its copy %s again" % (self._m_label(mode),
                                                                  back["name"]))
            self._m_after_change([back.get("rel") or ""])
            return back.get("rel") or ""
        taken = set(clips.bank_of) | {r["name"] for r in recs}
        name = CM.own_name(clip, mode, taken)
        ext = os.path.splitext(rel)[1]
        new_rel = "%s/%s%s" % (os.path.dirname(rel) or "video", name, ext)
        src = os.path.join(project, *rel.split("/"))
        dst = os.path.join(project, *new_rel.split("/"))
        label = self._m_label(mode)
        others = [self._m_label(m) for m in self._m_modes.get(rel, ()) if m != mode]
        if confirm:
            answer = compat.ctx().dialogs.message(
                "question", "Give %s its own copy" % label,
                CONFIRM % (label, clip, os.path.basename(new_rel), label,
                           _and(others), clip),
                [{"id": "copy", "label": "Make the copy", "style": "primary"},
                 {"id": "cancel", "label": "Cancel"}], default="copy")
            if answer != "copy":
                return ""
        if os.path.exists(dst):
            compat.messagebox.showerror(
                "Give %s its own copy" % label,
                "%s is already in the project folder, so the copy can't be made under that "
                "name. Move it out of the video folder and try again." % new_rel)
            return ""
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            compat.messagebox.showerror("Give %s its own copy" % label,
                                        "The copy could not be made: %s" % e)
            return ""
        recs = [r for r in recs if not (r["clip"] == clip and r["mode"] == mode)]
        recs.append({"name": name, "clip": clip, "mode": mode, "rel": new_rel, "of": rel,
                     "state": "own"})
        CM.save_records(project, recs)
        self._m_history("video  %s gets its own copy %s of %s" % (label, name, clip))
        self.log("%s now has its own copy of %s: %s. Choose a replacement for it; "
                        "the next image build puts it on the card as a new clip."
                        % (label, clip, new_rel), "success")
        self._m_after_change([new_rel])
        return new_rel

    @rpc
    def shared_again(self, rel, confirm=True):
        """Back to the shared clip: the copy *rel* is dropped (or, when the card already has
        it, its mode is pointed at the shared clip again by the next Write)."""
        from ..plugins.stern import clip_modes as CM
        copy = self._m_copy.get(rel)
        project = self._scan_dir
        if copy is None or not project or self._is_running():
            return False
        label = self._m_label(copy["mode"])
        on_card = rel in ((self._m_clips.name_of if self._m_clips else {}) or {})
        picked = bool(self._assign.get(rel))
        if confirm:
            text = ("%s plays %s again, as the game shipped." % (label, copy["clip"]))
            if not on_card:
                text += (" The copy (%s) is deleted from the project folder%s."
                         % (os.path.basename(rel),
                            " and its replacement pick is dropped (your own file is "
                            "untouched)" if picked else ""))
            else:
                text += (" The card keeps the copy as a clip nothing plays; the next Write "
                         "points %s back at the shared clip." % label)
            if not compat.messagebox.askyesno("Back to the shared clip", text):
                return False
        recs = [r for r in self._m_records()
                if not (r["name"] == copy["name"] and r["mode"] == copy["mode"])]
        if on_card:
            recs.append(dict(copy, state="shared", rel=rel))
        elif picked:
            self._assign.pop(rel, None)
            self._save_staged()
        CM.save_records(project, recs)
        if not on_card:
            try:
                os.remove(os.path.join(project, *rel.split("/")))
            except OSError:
                pass
        self._m_history("video  %s plays the shared clip %s again" % (label, copy["clip"]))
        self._m_after_change([copy.get("of") or ""])
        return True

    def _m_history(self, line):
        try:
            from ..core import history_log
            history_log.record(self._scan_dir, line)
        except Exception:                                   # noqa: BLE001
            pass

    def _m_after_change(self, select):
        """A copy made or dropped: rescan, then show *select*."""
        self._m_select_after = [r for r in select if r]
        self.scan()
