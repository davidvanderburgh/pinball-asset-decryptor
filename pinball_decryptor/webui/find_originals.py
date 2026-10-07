"""The Audio and Images tabs' "Find originals…" window: the files the
replacements on the tab were made from, found in a folder by content.

PAD-443 (DoomWalrus666): the Video tab can find the files a built card's
clips were made from; this is the same for sounds and pictures.  A project
whose picks are copies off a card -- "Transfer Mods to New Version" from an
extract of a built card picks the card's own copy of every replaced file --
gets the user's own files back, so the next Write converts those instead of
converting the card's copies a second time.  The matching is
:mod:`core.original_match`; nothing reads a card image.

What is searched for: every slot on the tab with a replacement picked whose
file is on this PC, and every slot a Write already changed on disk with no
pick left (its own file is the copy).  A pick that is already a file of the
user's own is searched too, but a file found for it starts unticked: it is
only a different copy.

A mixin of a Replace tab service, which supplies (``_orig_*``):

  _orig_kind          core.original_match.SOUND or PICTURE
  _orig_label         "Replace Audio" / "Replace Images"
  _orig_picks()       {slot rel: picked path} (live picks)
  _orig_changed()     slots changed on disk
  _orig_slot_path()   a slot's own file
  _orig_project()     the scanned project folder, or ""
  _orig_busy()        a Write (or another run) is going
  _orig_use(pairs)    make *pairs* ({rel: path}) the slots' picks
  _orig_trim()        (shown, on) of the tab's Trim / pad option, or None
  _orig_set_trim()    turn it on
  _orig_keep_size()   a slot keeps its replacement's own size (pictures)

State (``<ns>.originals``): ``open``, ``kind``, ``title``, ``intro``,
``summary``, ``folder``, ``busy``, ``status``, ``rows`` (``[{"rel", "name",
"now", "ref", "file", "path", "match", "sure", "use", "info", "len",
"note"}]``; ``ref`` is the file looked for, ``path`` the one found, both
shown side by side), ``found``, ``can_apply``.
"""

import os
import threading
import time

from . import compat
from .rpc import rpc

INTRO = {
    "sound": (
        "Every sound picked on this tab is compared with every sound file "
        "in the folder by how it sounds, so the names don't matter, and "
        "neither do the level, the sample rate or the file type. Where the "
        "folder has the same sound more than once, the best copy is used. "
        "Files that are part of an extract (copies off a card) are never "
        "offered."),
    "picture": (
        "Every picture picked on this tab is compared with every picture in "
        "the folder by how it looks, so the names don't matter, and neither "
        "do the size or the file type. Where the folder has the same "
        "picture more than once, the biggest best copy is used. Files that "
        "are part of an extract (copies off a card) are never offered."),
}

_NOUN = {"sound": ("sound", "sounds"), "picture": ("picture", "pictures")}


def _length(secs):
    if not secs:
        return ""
    return "%d:%04.1f" % (int(secs // 60), secs % 60)


def _sound_info(c):
    ext = os.path.splitext(c.path)[1].lstrip(".").upper()
    bits = [ext]
    if c.rate:
        bits.append(("%g kHz" % (c.rate / 1000.0)))
    if c.channels:
        bits.append({1: "mono", 2: "stereo"}.get(c.channels,
                                                 "%d ch" % c.channels))
    return " ".join(bits)


def _picture_info(c):
    ext = os.path.splitext(c.path)[1].lstrip(".").upper()
    return ("%dx%d %s" % (c.width, c.height, ext)) if c.width else ext


def _norm(p):
    return os.path.normcase(os.path.abspath(p)) if p else ""


class FindOriginalsMixin:
    _orig_kind = "sound"
    _orig_label = ""

    def __init__(self, window):
        super().__init__(window)
        self._o_cancel = False
        self._o_run = 0
        self._o_rows = []
        self._o_project = ""
        self.set(originals=self._orig_state(open_=False))

    # ------------------------------------------------------------------
    # host hooks (the tab overrides these)
    # ------------------------------------------------------------------
    def _orig_trim(self):
        return None

    def _orig_set_trim(self):
        pass

    def _orig_keep_size(self, rel):
        return False

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def _orig_state(self, open_=True, **kw):
        kind = self._orig_kind
        st = {"open": bool(open_), "kind": kind,
              "title": "Find your original %s" % _NOUN[kind][1],
              "intro": INTRO[kind], "summary": "", "folder": "",
              "busy": False, "status": "", "rows": [], "found": 0,
              "can_apply": False}
        st.update(kw)
        return st

    def _orig_set(self, **kw):
        o = dict(self.get("originals") or self._orig_state())
        o.update(kw)
        self.set(originals=o)

    def _orig_refs(self):
        """``(refs, mine, missing)``: ``{rel: the file to match}``, the rels
        whose pick is already a file of the user's own, and how many picks
        point at files that aren't on this PC (with nothing changed on disk
        to stand in for them)."""
        from ..core.original_match import CardFiles
        cards = CardFiles()
        picks = self._orig_picks()
        changed = self._orig_changed()
        refs, mine, missing = {}, set(), 0
        for rel in sorted(set(picks) | set(changed)):
            pick = picks.get(rel) or ""
            if pick and os.path.isfile(pick):
                refs[rel] = pick
                if not cards.is_card_file(pick):
                    mine.add(rel)
            elif rel in changed:
                slot = self._orig_slot_path(rel)
                if slot and os.path.isfile(slot):
                    refs[rel] = slot
            elif pick:
                missing += 1
        return refs, mine, missing

    def _orig_summary(self):
        if not self._orig_project():
            return "Scan the project on this tab first."
        refs, mine, missing = self._orig_refs()
        one, many = _NOUN[self._orig_kind]
        if not refs and not missing:
            return ("No replacements are picked on this tab yet, so there "
                    "is nothing to find the originals of.")
        copies = len(refs) - len(mine)
        parts = ["%d %s to look for" % (len(refs), one if len(refs) == 1
                                        else many)]
        if copies:
            parts.append("%d are copies off a card" % copies)
        if mine:
            parts.append("%d are already files of your own" % len(mine))
        text = ": ".join([parts[0], ", ".join(parts[1:])]) if \
            len(parts) > 1 else parts[0]
        text += "."
        if missing:
            text += (" %d more point at files that aren't on this PC "
                     "(Project ▾ → Relink moved files…)." % missing)
        return text

    # ------------------------------------------------------------------
    # the window
    # ------------------------------------------------------------------
    @rpc
    def originals_open(self):
        o = self.get("originals") or {}
        if o.get("busy") or o.get("rows"):
            self._orig_set(open=True, summary=self._orig_summary())
            return True
        folder = ""
        try:
            folder = self.window.last_browse_dir(
                "%s_originals" % self._orig_kind) or ""
        except Exception:                                   # noqa: BLE001
            folder = ""
        self._o_rows = []
        self.set(originals=self._orig_state(
            open_=True, summary=self._orig_summary(), folder=folder,
            status="Pick the folder your own files are in, then press "
                   "Find."))
        return True

    @rpc
    def originals_close(self):
        self._o_cancel = True
        self._o_run += 1
        self._o_rows = []
        self.set(originals=self._orig_state(open_=False))
        return True

    @rpc
    def originals_set(self, field, value):
        if field != "folder":
            return False
        self._orig_set(folder=(value or "").strip().strip('"'))
        return True

    @rpc
    def originals_browse(self):
        o = self.get("originals") or {}
        cur = o.get("folder") or ""
        path = self.window.ask_folder(
            "%s_originals" % self._orig_kind,
            "Choose the folder your own %s are in" % _NOUN[self._orig_kind][1],
            initialdir=self.window._initialdir_for(cur))
        if path:
            self._orig_set(folder=os.path.normpath(path))
        return path

    @rpc
    def originals_find(self):
        """Find, or Stop while a search runs."""
        from ..core import original_match
        o = self.get("originals") or {}
        if o.get("busy"):
            self._o_cancel = True
            self._orig_set(status="Stopping…")
            return True
        title = o.get("title") or "Find your originals"
        folder = o.get("folder") or ""
        if not os.path.isdir(folder):
            compat.messagebox.showwarning(
                title, "Pick the folder your own %s are in first."
                % _NOUN[self._orig_kind][1])
            return False
        project = self._orig_project()
        if not project:
            compat.messagebox.showwarning(
                title, "Scan this project on this tab first: its "
                       "replacements are what is looked for.")
            return False
        refs, mine, _missing = self._orig_refs()
        if not refs:
            compat.messagebox.showinfo(
                title, "No replacements are picked on this tab, so there is "
                       "nothing to find the originals of.")
            return False
        self._o_run += 1
        run = self._o_run
        self._o_cancel = False
        self._o_rows = []
        self._o_project = project
        self._orig_set(busy=True, rows=[], found=0, can_apply=False,
                       summary=self._orig_summary(),
                       status="Looking in %s…" % folder)
        kind = self._orig_kind
        cache_dir = os.path.join(project, ".write_cache", "fingerprints",
                                 kind + "s")
        post = self.ctx.loop.post
        label = self._orig_label

        def on_log(msg, level="info"):
            post(self.log, "%s: %s" % (label, msg), level)

        last = [0.0]

        def on_progress(done, total, text):
            now = time.monotonic()
            if now - last[0] < 0.4 and (not total or done < total):
                return
            last[0] = now
            msg = ("%s (%d of %d)…" % (text, done, total)) if total else text
            post(self._orig_progress, run, msg)

        def work():
            res, err = None, ""
            try:
                res = original_match.find_originals(
                    kind, refs, [folder], cache_dir=cache_dir, log=on_log,
                    progress=on_progress, cancel=lambda: self._o_cancel)
            except Exception as e:                          # noqa: BLE001
                err = ("Stopped." if isinstance(e, original_match.Cancelled)
                       else (str(e) or e.__class__.__name__))
            post(self._orig_done, run, res, err, refs, mine)

        threading.Thread(target=work, daemon=True,
                         name="%s-original-find" % kind).start()
        return True

    def _orig_progress(self, run, msg):
        if run == self._o_run:
            self._orig_set(status=msg)

    def _orig_done(self, run, res, err, refs, mine):
        if run != self._o_run:
            return
        if err:
            self._orig_set(busy=False, status=err)
            return
        kind = self._orig_kind
        one, many = _NOUN[kind]
        trim = self._orig_trim()
        # a Write cuts a longer file when the option is on, or always when
        # the tab doesn't offer it (Stern forces it)
        trims = trim is not None and (trim[1] or not trim[0])
        picks = self._orig_picks()
        rows, own_only = [], 0
        matches = (res or {}).get("matches") or {}
        for rel in sorted(matches):
            m = matches[rel]
            is_mine = rel in mine
            if m.best is None and is_mine:
                own_only += 1
                continue
            now = picks.get(rel) or ""
            row = {"rel": rel, "name": rel.split("/")[-1],
                   "now": os.path.basename(now) if now else
                   "(changed on disk)",
                   "ref": refs.get(rel) or "",
                   "sure": bool(m.sure), "use": False,
                   "len": _length(m.ref.duration if m.ref else 0)
                   if kind == "sound" else "",
                   "match": ("%.0f%%" % (max(0.0, m.score) * 100))
                   if m.best is not None else "not found"}
            if m.best is None:
                row.update(file="", path="", info="", note=(
                    "closest was %.0f%%" % (m.score * 100))
                    if m.score > 0 else "")
                rows.append(row)
                continue
            b = m.best
            notes = []
            if not m.sure:
                notes.append("worth a look")
            if m.same:
                notes.append("%d other cop%s" % (
                    len(m.same), "y" if len(m.same) == 1 else "ies"))
            if m.variants:
                notes.append("%d at another length" % len(m.variants))
            if m.longer:
                notes.append("longer: cut to the slot's length on Write"
                             if trims else "longer: needs Trim / pad")
            if m.identical:
                notes.append("the same bytes as the file picked now")
            if is_mine:
                notes.append("a file of your own is picked now")
            use = not is_mine
            if kind == "picture" and self._orig_keep_size(rel) and m.ref \
                    and (b.width, b.height) != (m.ref.width, m.ref.height):
                notes.append("Keep size is on: it would go on at %dx%d, "
                             "not %dx%d" % (b.width, b.height, m.ref.width,
                                            m.ref.height))
                use = False
            row.update(file=os.path.basename(b.path), path=b.path,
                       info=(_sound_info(b) if kind == "sound"
                             else _picture_info(b)),
                       use=use, note=", ".join(notes))
            if kind == "sound" and b.duration:
                row["len"] = _length(b.duration)
            rows.append(row)
        # the ones to look at first: not found, then unsure, then the rest
        rows.sort(key=lambda r: (bool(r["path"]), r["sure"], r["name"]))
        self._o_rows = rows
        found = sum(1 for r in rows if r["path"])
        sure = sum(1 for r in rows if r["path"] and r["sure"])
        if not rows:
            status = ("Nothing to change: every %s here is already a file "
                      "of your own." % one) if own_only else \
                "Nothing found."
        else:
            status = ("Found the file behind %d of %d %s: %d certain, %d "
                      "worth a look (amber)." % (
                          found, len(rows), one if len(rows) == 1 else many,
                          sure, found - sure))
            if own_only:
                status += (" %d more already use files of your own and "
                           "aren't listed." % own_only)
        unreadable = len((res or {}).get("unreadable") or [])
        if unreadable:
            status += " %d picked file(s) couldn't be read." % unreadable
        if not (res or {}).get("sources"):
            status += (" The folder has no %s files to compare (files in "
                       "an extract folder are copies off a card and don't "
                       "count)." % one)
        self._orig_set(busy=False, rows=rows, found=found, status=status,
                       summary=self._orig_summary(),
                       can_apply=any(r["use"] and r["path"] for r in rows))

    @rpc
    def originals_use_row(self, rel, value):
        for r in self._o_rows:
            if r["rel"] == rel and r["path"]:
                r["use"] = bool(value)
        self._orig_set(rows=list(self._o_rows), can_apply=any(
            r["use"] and r["path"] for r in self._o_rows))
        return True

    @rpc
    def originals_use_all(self, value):
        for r in self._o_rows:
            if r["path"]:
                r["use"] = bool(value)
        self._orig_set(rows=list(self._o_rows), can_apply=any(
            r["use"] and r["path"] for r in self._o_rows))
        return True

    @rpc
    def originals_reveal(self, rel):
        from . import video_helpers as vh
        for r in self._o_rows:
            if r["rel"] == rel and r["path"]:
                vh.reveal_in_file_manager(r["path"])
                return True
        return False

    @rpc
    def originals_apply(self):
        """The ticked files become their slots' replacements."""
        if self._orig_busy():
            return False
        o = self.get("originals") or {}
        title = o.get("title") or "Find your originals"
        if _norm(self._orig_project()) != _norm(self._o_project):
            compat.messagebox.showwarning(
                title, "The project on this tab changed since the search. "
                       "Press Find again.")
            return False
        picked = [r for r in self._o_rows if r["use"] and r["path"]]
        trim = self._orig_trim()
        longer = [r for r in picked if "needs Trim / pad" in r["note"]]
        if longer and trim is not None and trim[0] and not trim[1]:
            # A file longer than the sound on the card was cut by a Trim /
            # pad build; without it the next Write puts the whole file on.
            if compat.messagebox.askyesno(
                    "Files longer than the sounds on the card",
                    "%d of these files run longer than the sound picked now "
                    "(it was cut to its slot's length when it was built).\n\n"
                    "Turn on \"Trim / pad replacements to the original slot "
                    "length\" so they are cut the same way again?\n\nNo "
                    "leaves those %d slot(s) as they are."
                    % (len(longer), len(longer))):
                self._orig_set_trim()
            else:
                skip = {r["rel"] for r in longer}
                picked = [r for r in picked if r["rel"] not in skip]
        if not picked:
            self._orig_set(status="Nothing ticked to use.")
            return False
        pairs = {r["rel"]: r["path"] for r in picked}
        changed = self._orig_use(pairs)
        self.log("%s: %d slot(s) now use the file of your own found for them "
                 "(%d changed). The next Write converts from those."
                 % (self._orig_label, len(pairs), changed), "success")
        for r in self._o_rows:
            if r["rel"] in pairs:
                r["now"], r["ref"] = r["file"], r["path"]
                r["use"] = False
        self._orig_set(rows=list(self._o_rows), can_apply=False,
                       summary=self._orig_summary(),
                       status="Done: %d file(s) of your own in use. Build "
                              "on the Write tab." % len(pairs))
        return True
