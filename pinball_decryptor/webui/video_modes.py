"""PAD-444: the Video tab's "Played in": which of the game's modes plays each clip, the clips
the game never plays, a filter to list one mode's clips, and a ROW FOR EACH MODE of a clip two
modes share.

The reading is :mod:`..plugins.stern.clip_modes`' (the card's game program, read once per card
off the UI thread and cached on disk); this mixin is the tab's side.

A CLIP TWO MODES SHARE (Godzilla's battle vs Gigan and the Ghidorah and Gigan tag team play two
of the same clips) is listed once per mode. The first mode's row is the clip itself; each other
mode's row is a FOLLOWER: it plays the same clip ("Same clip as <mode>") until a replacement is
chosen for it. Choosing one makes the follower a clip of its own - the shared clip's file copied
to ``video/<clip>_<mode slug>.<ext>`` and recorded in ``.staged_changes.json`` (``own_clips``),
which Write turns into a new clip on the card and that mode alone plays. Clearing that
replacement makes it a follower again (the copy and its record go). A follower has no file of
its own until then: its row reads the shared clip's slot (the Original pane plays that clip).

A copy an earlier build put on the card, extracted again, is a real slot recognised by its name;
"Use the same clip as <mode> again" (row menu, and the callout) points its mode back at the
shared clip on the next Write (a ``state: "shared"`` record), and choosing a replacement for it
undoes that.

Store keys (namespace ``video``):
  modes        {ready, busy, note, list: [{id, label, n}], filter}; filter ids are mode classes,
               OTHER (code that is no one mode's) and UNPLAYED (nothing plays it)
  rows[i]      + modes (labels), pair (a row of a shared clip), follow (the lead mode's label: a
               follower), copy (a mode's own clip), unplayed, other
  preview      + modes: {rel, kind: lead|follow|copy|unplayed, text, back} or None
               + sounds: {rel, head, items: [{text, how, tip}], more, foot} or None - the
               sounds the game plays with the clip (:mod:`..plugins.stern.clip_sounds`),
               named by the extract's ``sound_requests.tsv`` and audio files
"""

import os
import shutil
import threading
from dataclasses import replace

from . import compat
from .tabs.base import rpc

#: the filter's two lists beside the modes
OTHER = "__other__"
UNPLAYED = "__unplayed__"
OTHER_LABEL = "Other parts of the game"
UNPLAYED_LABEL = "Not played by the game"

#: what the callout under the panes says (one place, for the tests)
LEAD_TEXT = "%s play this clip, so it has a row for each. This row is %s's. %s"
LEAD_ONE = ("%s's row below plays whatever this row plays until you choose a replacement "
            "in it.")
LEAD_MANY = ("The rows of %s below play whatever this row plays until you choose a "
             "replacement in them.")
FOLLOW_TEXT = ("%s plays the same clip as %s until you choose a replacement in this row. Then "
               "only %s plays your clip: the card gets it as a new clip of its own on an image "
               "build (a direct SD write leaves it out).")
COPY_TEXT = ("%s has a clip of its own: only it plays this replacement (the card gets it as a "
             "new clip on an image build). Clear the replacement and it plays the same clip as "
             "%s again.")
CARD_COPY_TEXT = ("%s plays a clip of its own that an earlier build gave it; %s plays %s.")
BACK_TEXT = ("%s plays the same clip as %s again after the next Write. Choose a replacement in "
             "this row to keep a clip of its own.")
UNPLAYED_TEXT = ("The game never plays this clip: nothing in its program asks for it by name, "
                 "so a replacement here changes nothing on the machine.")
#: the callout's sounds part: the kinds of :mod:`..plugins.stern.clip_sounds` pairing the
#: emulator proved (record 38 of 38, next 16 of 18, name 94 of 106), each in words
SOUNDS_HEAD = "Sounds the game plays with this clip (read from its program):"
SOUNDS_MAX = 8
SOUNDS_HOW = {"record": "kept with the clip", "next": "asked for right after it",
              "name": "named after it"}
SOUNDS_FOOT = ("Extract the card again to see which sound files these are: the extract writes "
               "sound_requests.tsv.")


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
        self._m_filter = ""           # a mode class, OTHER, UNPLAYED, or "" for every clip
        self._m_clear_state()
        self.set(modes={"ready": False, "busy": False, "note": "", "list": [], "filter": ""})

    def _m_clear_state(self):
        self._m_modes = {}            # rel -> [mode class] the row stands for
        self._m_lead = {}             # rel of a shared clip -> [follower mode classes]
        self._m_follow = {}           # rel -> the mode whose clip it plays (a follower)
        self._m_virtual = {}          # follower rel with no file yet -> its record-to-be
        self._m_copy = {}             # rel -> the record of a mode's own clip
        self._m_unplayed = set()
        self._m_other = set()
        self._m_of = {}               # follower / copy rel -> the shared clip's rel
        self._m_sr = None             # clip_sounds.SoundReading of the card, read once
        self._m_names = None          # (sound_requests.tsv rows, {idx: audio file}) of the project

    def _m_reset(self):
        self._m_run += 1
        self._m_clips = None
        self._m_key = None
        self._m_filter = ""
        self._m_drop_virtual()
        self._m_clear_state()
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

    def _m_label(self, mode):
        clips = self._m_clips
        if clips is not None:
            return clips.reading.label(mode)
        from ..plugins.stern import clip_modes as CM
        return CM.mode_label(mode)

    def _m_sorted(self, modes):
        return sorted(set(modes), key=lambda m: (self._m_label(m).lower(), m))

    def _m_publish(self):
        """Each row's modes - the project's copies counted as they will be on the card after
        the next Write - the followers of each shared clip, and the toolbar's list."""
        from ..plugins.stern import clip_modes as CM
        clips = self._m_clips
        self._m_drop_virtual()
        self._m_clear_state()
        if clips is None:
            return
        reading = clips.reading
        real = set(s.rel_path for s in self._slots)
        by_name = {n: rel for rel, n in clips.name_of.items()}
        for rel, name in clips.name_of.items():
            ms = reading.modes_of(name)
            if ms:
                self._m_modes[rel] = list(ms)
            if reading.elsewhere(name):
                self._m_other.add(rel)
        self._m_unplayed = {by_name[n] for n in clips.unplayed if n in by_name}
        recs = self._m_records()
        named = {r["name"] for r in recs}
        for rel, name in clips.name_of.items():
            # a copy an earlier build put on the card, extracted again: still a copy
            got = None if name in named else CM.copy_of(name, by_name, reading.labels)
            if got and got[1] in self._m_modes.get(rel, ()):
                self._m_copy[rel] = {"name": name, "clip": got[0], "mode": got[1], "rel": rel,
                                     "of": by_name.get(got[0], ""), "state": "own"}
        back = {}                                   # (shared rel, mode) -> on-card copy rel
        for rec in recs:
            of = rec.get("of") or by_name.get(rec["clip"])
            mine = rec.get("rel") or by_name.get(rec["name"])
            if rec.get("state") == "shared":
                if of:
                    self._m_modes[of] = self._m_sorted(self._m_modes.get(of, []) + [rec["mode"]])
                if mine:
                    self._m_modes[mine] = [rec["mode"]]
                    self._m_unplayed.discard(mine)
                    back[(of, rec["mode"])] = mine
                continue
            if of in self._m_modes:
                self._m_modes[of] = [m for m in self._m_modes[of] if m != rec["mode"]]
            if mine:
                self._m_modes[mine] = [rec["mode"]]
                self._m_copy[mine] = rec
        for rel, rec in self._m_copy.items():
            self._m_of[rel] = rec.get("of") or by_name.get(rec["clip"], "")
        # a shared clip: its first mode's row is the clip, every other mode follows it
        taken = set(clips.bank_of) | named
        for rel in sorted(self._m_modes):
            ms = self._m_sorted(self._m_modes[rel])
            if len(ms) < 2 or rel in self._m_copy or rel not in real:
                continue
            # the first mode leads; a mode the project pointed back here from a clip of its
            # own on the card follows, in that clip's row
            lead = ([m for m in ms if (rel, m) not in back] or ms)[0]
            ms = [lead] + [m for m in ms if m != lead]
            self._m_modes[rel] = [lead]
            self._m_lead[rel] = ms[1:]
            clip = clips.name_of.get(rel)
            for mode in ms[1:]:
                mine = back.get((rel, mode))
                if mine is None:
                    name = CM.own_name(clip, mode, taken)
                    taken.add(name)
                    mine = "%s/%s%s" % (os.path.dirname(rel) or "video", name,
                                        os.path.splitext(rel)[1])
                    if mine in real:            # its file is in the folder already
                        continue
                    self._m_virtual[mine] = {"name": name, "clip": clip, "mode": mode,
                                             "rel": mine, "of": rel, "state": "own"}
                self._m_follow[mine] = ms[0]
                self._m_modes[mine] = [mode]
                self._m_of[mine] = rel
        self._m_sync_virtual()
        counts = {}
        for rel, ms in self._m_modes.items():
            if rel in self._by_rel:
                for m in ms:
                    counts[m] = counts.get(m, 0) + 1
        modes = sorted(counts, key=lambda m: (reading.label(m).lower(), m))
        extra = []
        n_other = sum(1 for r in self._m_other if r in real and not self._m_modes.get(r))
        n_un = sum(1 for r in self._m_unplayed if r in real)
        if n_other:
            extra.append({"id": OTHER, "label": OTHER_LABEL, "n": n_other})
        if n_un:
            extra.append({"id": UNPLAYED, "label": UNPLAYED_LABEL, "n": n_un})
        ids = set(counts) | {e["id"] for e in extra}
        if self._m_filter and self._m_filter not in ids:
            self._m_filter = ""
        note = clips.note or ("" if modes else "no clip of this card is one of its modes'")
        self.set(modes={"ready": True, "busy": False, "note": note,
                        "list": [{"id": m, "label": reading.label(m), "n": counts[m]}
                                 for m in modes] + extra,
                        "filter": self._m_filter})

    # -- the followers' rows ---------------------------------------------------------------
    def _m_drop_virtual(self):
        for rel in list(getattr(self, "_m_virtual", {}) or {}):
            slot = self._by_rel.get(rel)
            if slot is not None and getattr(slot, "_pad_virtual", False):
                del self._by_rel[rel]

    def _m_sync_virtual(self):
        """A follower with no file yet reads its shared clip's slot (the metadata the probe
        filled in since included)."""
        for rel, rec in self._m_virtual.items():
            orig = self._by_rel.get(rec["of"])
            if orig is None or getattr(orig, "_pad_virtual", False):
                continue
            slot = replace(orig, rel_path=rel)
            slot._pad_virtual = True
            self._by_rel[rel] = slot

    def _m_slots(self):
        """The list's slots: the scanned ones and each follower that has no file yet."""
        self._m_sync_virtual()
        return list(self._slots) + [self._by_rel[r] for r in self._m_virtual
                                    if r in self._by_rel]

    def _m_meta(self, rel):
        """The shared clip *rel* was probed: its followers' rows show the same."""
        for vrel, rec in self._m_virtual.items():
            if rec["of"] == rel:
                self._m_sync_virtual()
                i = self._index.get(vrel)
                if i is not None:
                    self._put_row(i, self._row(self._by_rel[vrel]))

    def _m_real(self, rels):
        """*rels* less the followers that have no file (no pick can be made for those)."""
        return [r for r in rels if r not in self._m_virtual]

    def _m_row(self, rel):
        """The row's Played in cells (they override the slot's own where a follower shows
        its shared clip's name and the clip it follows)."""
        ms = self._m_modes.get(rel) or []
        out = {"modes": [self._m_label(m) for m in ms],
               "pair": bool(rel in self._m_lead or rel in self._m_follow or rel in self._m_copy),
               "follow": "", "copy": bool(rel in self._m_copy),
               "unplayed": rel in self._m_unplayed and not ms,
               "other": rel in self._m_other and not ms}
        of = self._m_of.get(rel)
        if of:
            out["name"] = os.path.basename(of)
        lead = self._m_follow.get(rel)
        if lead and not self._assign.get(rel):
            out["follow"] = self._m_label(lead)
            out["rep"] = "Same clip as %s" % self._m_label(lead)
            out["rep_cls"] = "follow"
        return out

    def _m_keep(self, rel):
        """Whether the mode filter keeps *rel* in the list."""
        f = self._m_filter
        if not f:
            return True
        ms = self._m_modes.get(rel) or ()
        if f == OTHER:
            return rel in self._m_other and not ms
        if f == UNPLAYED:
            return rel in self._m_unplayed and not ms
        return f in ms

    def _m_follow_text(self, rel):
        """The Replacement pane's words on a follower with no replacement, or None."""
        lead = self._m_follow.get(rel)
        if not lead or self._assign.get(rel):
            return None
        return "same clip as %s until you choose one for this row" % self._m_label(lead)

    def _m_preview(self, rel):
        """The callout's Played in part for the row on show, or None."""
        if not rel or self._m_clips is None:
            return None
        ms = self._m_modes.get(rel) or []
        if rel in self._m_lead:
            mine = self._m_label(ms[0]) if ms else ""
            others = [self._m_label(m) for m in self._m_lead[rel]]
            tail = LEAD_ONE % others[0] if len(others) == 1 else LEAD_MANY % _and(others)
            return {"rel": rel, "kind": "lead", "back": "",
                    "text": LEAD_TEXT % (_and([mine] + others), mine, tail)}
        lead = self._m_follow.get(rel)
        if lead and not self._assign.get(rel):
            label = self._m_label(ms[0]) if ms else ""
            if rel in self._m_virtual:
                return {"rel": rel, "kind": "follow", "back": "",
                        "text": FOLLOW_TEXT % (label, self._m_label(lead), label)}
            return {"rel": rel, "kind": "follow", "back": "",
                    "text": BACK_TEXT % (label, self._m_label(lead))}
        copy = self._m_copy.get(rel)
        if copy is not None:
            label = self._m_label(copy["mode"])
            of = self._m_of.get(rel) or ""
            others = [self._m_label(m) for m in self._m_modes.get(of, ()) if m != copy["mode"]]
            on_card = rel in ((self._m_clips.name_of or {}))
            if on_card:
                return {"rel": rel, "kind": "copy", "back": _and(others) or "",
                        "text": CARD_COPY_TEXT % (label, _and(others) or "every other mode",
                                                  copy["clip"])}
            return {"rel": rel, "kind": "copy", "back": "",
                    "text": COPY_TEXT % (label, _and(others) or "the other modes")}
        if rel in self._m_unplayed and not ms:
            return {"rel": rel, "kind": "unplayed", "back": "", "text": UNPLAYED_TEXT}
        return None

    # -- the sounds the game plays with a clip -----------------------------------------------
    def _m_sound_reading(self):
        if self._m_sr is None and self._m_clips is not None:
            self._m_sr = self._m_clips.sound_reading
        return self._m_sr

    def _m_sound_names(self):
        """``(sound_requests.tsv rows, {idx: "audio/<file>"})`` of the project, read once."""
        if self._m_names is None:
            from ..plugins.stern import clip_sounds as CS
            project = self._scan_dir or ""
            self._m_names = (CS.read_requests(project), CS.audio_files(project))
        return self._m_names

    def _m_sound_words(self, snd):
        """``(text, tip)`` for one of a clip's sounds: its audio file where the extract mapped
        its request, else its Sound Test name, else its request number."""
        req, audio = self._m_sound_names()
        r = snd["request"]
        row = req.get(r) or {}
        files = [audio[i] for i in row.get("idx", ()) if i in audio]
        name = snd["name"] or row.get("name", "")
        if files:
            text = os.path.basename(files[0])
            if len(files) > 1:
                text += " (+%d)" % (len(files) - 1)
        else:
            text = name or "sound request %d" % r
        lines = ["Sound request %d" % r]
        if name:
            lines.append("Sound Test: %s" % name)
        lines += [os.path.basename(f) for f in files]
        if not files and row.get("idx"):
            lines.append("idx " + ", ".join("%04d" % i for i in row["idx"]))
        return text, {"head": text, "lines": lines}

    def _m_sounds(self, rel):
        """The callout's sounds part for the row on show, or None."""
        if not rel or self._m_clips is None or not self._m_clips.sounds:
            return None
        reading = self._m_sound_reading()
        names = self._m_clips.name_of
        name = names.get(rel) or names.get(self._m_of.get(rel) or "")
        if not name:
            return None
        sounds = reading.sounds_of(name)
        if not sounds:
            if reading.note and not reading.pairs and rel not in self._m_unplayed:
                return {"rel": rel, "head": SOUNDS_HEAD, "items": [], "more": "",
                        "foot": "None found: %s." % reading.note}
            return None
        # "function" (a call elsewhere in the code naming the clip) was right 6 times in 28
        shown = [snd for snd in sounds if snd["how"] in SOUNDS_HOW]
        if not shown:
            return None
        items = []
        for snd in shown[:SOUNDS_MAX]:
            text, tip = self._m_sound_words(snd)
            items.append({"text": text, "how": SOUNDS_HOW[snd["how"]], "tip": tip})
        more = len(shown) - SOUNDS_MAX
        req, _audio = self._m_sound_names()
        return {"rel": rel, "head": SOUNDS_HEAD, "items": items,
                "more": "And %d more." % more if more > 0 else "",
                "foot": "" if req else SOUNDS_FOOT}

    # -- the filter ------------------------------------------------------------------------
    @rpc
    def set_mode_filter(self, mode):
        self._m_filter = str(mode or "")
        cur = dict(self.get("modes") or {})
        cur["filter"] = self._m_filter
        self.set(modes=cur)
        self._refresh_list()
        return True

    # -- a follower gets a clip of its own, and gives it back --------------------------------
    def _m_materialize(self, rel):
        """A replacement was chosen for the follower *rel*: make its clip its own (the shared
        clip's file copied under its own name, and the record Write reads). A copy the card
        already has that the project had pointed back at the shared clip keeps its file and
        only loses that record. Returns whether *rel* is now a clip of its own."""
        from ..plugins.stern import clip_modes as CM
        project = self._scan_dir
        recs = self._m_records()
        rec = self._m_virtual.get(rel)
        if rec is None:
            if rel not in self._m_follow:
                return True
            # an on-card copy pointed back: keep it
            CM.save_records(project, [r for r in recs if not (
                r.get("state") == "shared" and (r.get("rel") == rel))])
            self._m_history("video  %s plays its own clip %s again"
                            % (self._m_label(self._m_modes[rel][0]), os.path.basename(rel)))
            return True
        src = os.path.join(project, *rec["of"].split("/"))
        dst = os.path.join(project, *rel.split("/"))
        label = self._m_label(rec["mode"])
        if os.path.exists(dst):
            compat.messagebox.showerror(
                "A clip of its own for %s" % label,
                "%s is already in the project folder, so %s's own clip can't be made under "
                "that name. Move it out of the video folder and try again." % (rel, label))
            return False
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            compat.messagebox.showerror("A clip of its own for %s" % label,
                                        "%s's own clip could not be made: %s" % (label, e))
            return False
        recs = [r for r in recs if not (r["clip"] == rec["clip"] and r["mode"] == rec["mode"])]
        recs.append(dict(rec))
        CM.save_records(project, recs)
        # the row is a slot with a file of its own now, not its shared clip's
        slot = replace(self._by_rel[rel], rel_path=rel, abs_path=dst,
                       size=os.path.getsize(dst))
        self._by_rel[rel] = slot
        self._slots.append(slot)
        self._slots.sort(key=lambda s: s.rel_path.lower())
        del self._m_virtual[rel]
        self._m_copy[rel] = dict(rec)
        self._m_history("video  %s gets a clip of its own (%s) instead of %s"
                        % (label, rec["name"], rec["clip"]))
        self.log("%s gets a clip of its own (%s) instead of sharing %s: the next image build "
                 "puts it on the card as a new clip." % (label, rec["name"], rec["clip"]),
                 "info")
        return True

    def _m_after_clear(self, rels):
        """Replacements were cleared: a mode's own clip that only this project made follows
        its shared clip again (its file and record go)."""
        from ..plugins.stern import clip_modes as CM
        project = self._scan_dir
        on_card = (self._m_clips.name_of if self._m_clips else {}) or {}
        gone = [r for r in rels if r in self._m_copy and r not in on_card
                and not self._assign.get(r)]
        if not gone or not project:
            return
        drop = {self._m_copy[r]["name"] for r in gone}
        CM.save_records(project, [r for r in self._m_records() if r["name"] not in drop])
        for rel in gone:
            try:
                os.remove(os.path.join(project, *rel.split("/")))
            except OSError:
                pass
            self._m_history("video  %s plays the shared clip %s again"
                            % (self._m_label(self._m_copy[rel]["mode"]),
                               self._m_copy[rel]["clip"]))
        self._m_after_change(gone)

    @rpc
    def shared_again(self, rel, confirm=True):
        """"Use the same clip as <mode> again" on a mode's own clip an earlier build put on the
        card: the next Write points its mode back at the shared clip (the card keeps the file,
        unplayed). A copy only this project made goes back by clearing its replacement."""
        from ..plugins.stern import clip_modes as CM
        copy = self._m_copy.get(rel)
        project = self._scan_dir
        on_card = rel in ((self._m_clips.name_of if self._m_clips else {}) or {})
        if copy is None or not project or self._is_running():
            return False
        if not on_card:
            # a clip of its own only this project made: clearing it is the way back
            if self._assign.get(rel):
                self._clear_picks([rel])
            else:
                self._m_after_clear([rel])
            return True
        label = self._m_label(copy["mode"])
        of = self._m_of.get(rel) or ""
        lead = _and([self._m_label(m) for m in self._m_modes.get(of, ())
                     if m != copy["mode"]]) or "the other modes"
        if confirm and not compat.messagebox.askyesno(
                "Use the same clip again",
                "%s plays the same clip as %s (%s) again after the next Write. The card keeps "
                "its own clip, unplayed." % (label, lead, copy["clip"])):
            return False
        recs = [r for r in self._m_records()
                if not (r["name"] == copy["name"] and r["mode"] == copy["mode"])]
        recs.append(dict(copy, state="shared", rel=rel))
        if self._assign.pop(rel, None):
            self._save_staged()
        CM.save_records(project, recs)
        self._m_history("video  %s plays the shared clip %s again" % (label, copy["clip"]))
        self._m_after_change([rel])
        return True

    def _m_history(self, line):
        try:
            from ..core import history_log
            history_log.record(self._scan_dir, line)
        except Exception:                                   # noqa: BLE001
            pass

    def _m_after_change(self, select):
        """A clip of its own made or dropped: rescan, then show *select*."""
        self._m_select_after = [r for r in select if r]
        self.scan()
