"""The Video tab's "Best quality…" window: every replaced clip re-encoded from
its own file at full quality, and the files found when the project doesn't
know them.

A mixin of the Video tab service (``tabs/video.py`` adds it to the class).
Two halves, one button:

* **Best quality** (the tab option, ``video_best_quality`` in the project's
  staged changes): a clip that has to be converted is encoded at constant
  quality instead of being held to the bitrate of the clip it replaces.  That
  only pays off on a card with room for it -- the Write tab's SD card size.
* **Find the source files**: a built card, the stock card and a folder of the
  user's videos in; for every clip the built card replaced, the file under
  that folder it was made from (:mod:`plugins.stern.source_find`).  Ticked
  rows become the slots' replacements, as if picked one by one.

State (``video.best``): ``open``, ``on`` (the option), ``summary`` (what the
project records), ``card``/``stock``/``folder``, ``busy``, ``status``,
``rows`` (``[{"rel", "name", "file", "path", "res", "rate", "len", "match",
"sure", "use", "now", "note"}]``), ``found``, ``can_apply``.
"""

import os
import threading

from . import compat
from .rpc import rpc

BEST_TIP = (
    "Convert every replacement at full quality instead of holding it to the "
    "size of the clip it replaces. Each clip gets the bits its picture "
    "needs: a detailed one comes out bigger than the stock clip, a simple "
    "one can come out smaller. Build for a 16 GB or 32 GB SD card (Write tab "
    "→ SD card size) if they don't fit on 8 GB; a Write that won't fit says "
    "so before it copies anything. A replacement that already suits its "
    "slot still goes on exactly as it is.")

INTRO = (
    "Every replaced clip is re-encoded from your own file at full quality, "
    "instead of being squeezed to the size of the clip it replaces. That "
    "takes room: build for a 16 GB or 32 GB SD card on the Write tab.")

FIND_INTRO = (
    "Don't have the files recorded here, or want the originals behind them? "
    "Pick a card that was built with your videos and the folder they are in. "
    "Every clip on that card is compared with every video in the folder by "
    "what it looks like, so the names don't matter. Where the folder has the "
    "same video more than once, the best copy is used.")


def _rate(bps):
    if not bps:
        return ""
    if bps >= 1e6:
        return "%.1f Mbps" % (bps / 1e6)
    return "%d kbps" % round(bps / 1000)


def _length(secs):
    if not secs:
        return ""
    return "%d:%04.1f" % (int(secs // 60), secs % 60)


class BestQualityMixin:
    def __init__(self, window):
        super().__init__(window)
        self._b_cancel = False
        self._b_run = 0
        self._b_rows = []
        self.set(best=self._best_state(open_=False))

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def _best_state(self, open_=True, **kw):
        st = {"open": bool(open_), "on": False, "summary": "",
              "intro": INTRO, "find_intro": FIND_INTRO,
              "card": "", "stock": "", "folder": "",
              "busy": False, "status": "", "rows": [], "found": 0,
              "can_apply": False, "supported": False}
        st.update(kw)
        return st

    def _best_set(self, **kw):
        b = dict(self.get("best") or self._best_state())
        b.update(kw)
        self.set(best=b)

    def _best_supported(self):
        mfr = self.mfr
        return bool(mfr is not None and getattr(
            mfr.capabilities, "video_source_search", False))

    def _best_summary(self):
        """One line on what this project records for its replacements."""
        live = {rel: p for rel, p in self._assign.items() if p}
        if not self._scan_dir:
            return "Scan the project on this tab first."
        if not live:
            return ("No replacements are picked in this project yet. Pick "
                    "them on this tab, or find them below.")
        here = sum(1 for p in live.values() if os.path.isfile(p))
        gone = len(live) - here
        text = ("%d replaced clip(s) in this project, each with its own "
                "file on this PC." % len(live)) if not gone else (
            "%d of %d replaced clip(s) have their file on this PC; %d point "
            "at files that aren't there (Project ▾ → Relink moved files…, or "
            "find them below)." % (here, len(live), gone))
        return text

    def _best_defaults(self):
        """Built card = the last Write's output, stock = the Write tab's
        original image (or the project's recorded one)."""
        from ..core import project_file
        w = self.window
        card = ""
        try:
            out = (w.write_output_var.get() or "").strip()
            name = (w.write_filename_var.get() or "").strip()
            if out and name and os.path.isfile(os.path.join(out, name)):
                card = os.path.join(out, name)
        except Exception:                                   # noqa: BLE001
            card = ""
        stock = ""
        try:
            stock = (w.write_upd_var.get() or "").strip()
        except Exception:                                   # noqa: BLE001
            stock = ""
        if not os.path.isfile(stock):
            try:
                anchor = project_file.load_anchor(self._assets_path()) or {}
            except (OSError, ValueError):       # a folder with no anchor
                anchor = {}
            stock = str(anchor.get("stock_image") or "")
            if not os.path.isfile(stock):
                stock = ""
        folder = ""
        try:
            folder = self.window.last_browse_dir("video_sources") or ""
        except Exception:                                   # noqa: BLE001
            folder = ""
        return card, stock, folder

    # ------------------------------------------------------------------
    # the option
    # ------------------------------------------------------------------
    @rpc
    def set_best_quality(self, value):
        self.video_best_quality_var.set(bool(value))
        self._save_staged()
        self._best_set(on=bool(value))
        self.log("Replace Video: best quality is %s." % (
            "on — the next Write converts replacements at full quality"
            if value else "off — replacements are held to the size of the "
            "clips they replace"), "info")
        return True

    # ------------------------------------------------------------------
    # the window
    # ------------------------------------------------------------------
    @rpc
    def best_open(self):
        if not self._best_supported():
            return False
        b = self.get("best") or {}
        if b.get("busy") or b.get("rows"):
            self._best_set(open=True, on=bool(
                self.video_best_quality_var.get()),
                summary=self._best_summary())
            return True
        card, stock, folder = self._best_defaults()
        self._b_rows = []
        self.set(best=self._best_state(
            open_=True, on=bool(self.video_best_quality_var.get()),
            summary=self._best_summary(), card=card, stock=stock,
            folder=folder, supported=True,
            status="Pick the built card, the stock card and your folder, "
                   "then press Find."))
        return True

    @rpc
    def best_close(self):
        self._b_cancel = True
        self._b_run += 1
        self._b_rows = []
        self.set(best=self._best_state(open_=False))
        return True

    @rpc
    def best_set(self, field, value):
        if field not in ("card", "stock", "folder"):
            return False
        self._best_set(**{field: (value or "").strip().strip('"')})
        return True

    @rpc
    def best_browse(self, field):
        b = self.get("best") or {}
        cur = b.get(field) or ""
        if field == "folder":
            path = self.window.ask_folder(
                "video_sources", "Choose the folder your videos are in",
                initialdir=self.window._initialdir_for(cur))
        elif field in ("card", "stock"):
            path = self.window.ask_open(
                "video_quality_card",
                "Pick the card image built with your videos" if field ==
                "card" else "Pick the stock card image",
                [("Card images", "*.raw *.img *.bin"), ("All files", "*.*")],
                initialdir=self.window._initialdir_for(cur))
        else:
            return False
        if path:
            self._best_set(**{field: os.path.normpath(path)})
        return path

    @rpc
    def best_find(self):
        """Find, or Stop while a search runs."""
        b = self.get("best") or {}
        if b.get("busy"):
            self._b_cancel = True
            self._best_set(status="Stopping…")
            return True
        card, stock, folder = (b.get("card") or "", b.get("stock") or "",
                               b.get("folder") or "")
        missing = [label for label, ok in (
            ("the built card", os.path.isfile(card)),
            ("the stock card", os.path.isfile(stock)),
            ("the folder your videos are in", os.path.isdir(folder)))
            if not ok]
        if missing:
            compat.messagebox.showwarning(
                "Find your source files",
                "Pick %s first." % " and ".join(missing))
            return False
        assets = self._assets_path()
        if not assets or not self._scan_dir:
            compat.messagebox.showwarning(
                "Find your source files",
                "Scan this project on the Video tab first: its slots are "
                "what the clips on the card are named by.")
            return False
        if os.path.normcase(os.path.abspath(card)) == \
                os.path.normcase(os.path.abspath(stock)):
            compat.messagebox.showwarning(
                "Find your source files",
                "The built card and the stock card are the same file. Pick "
                "the card that was built with your videos.")
            return False
        self._b_run += 1
        run = self._b_run
        self._b_cancel = False
        self._b_rows = []
        self._best_set(busy=True, rows=[], found=0, can_apply=False,
                       status="Reading %s…" % os.path.basename(card))
        mfr = self.mfr
        cache_dir = os.path.join(assets, ".write_cache", "fingerprints")
        post = self.ctx.loop.post

        def on_log(msg, level="info"):
            post(self.log, "Best quality: " + msg, level)

        last = [0.0]

        def on_progress(done, total, text):
            import time
            now = time.monotonic()
            if now - last[0] < 0.4:
                return
            last[0] = now
            msg = ("%s (%d of %d)" % (text, done, total)) if total else text
            post(self._best_progress, run, msg)

        def work():
            res, err = None, ""
            try:
                res = mfr.find_video_sources(
                    card, stock, assets, [folder], cache_dir=cache_dir,
                    log=on_log, progress=on_progress,
                    cancel=lambda: self._b_cancel)
            except Exception as e:                          # noqa: BLE001
                from ..core.source_match import Cancelled
                err = ("Stopped." if isinstance(e, Cancelled)
                       else (str(e) or e.__class__.__name__))
            post(self._best_done, run, res, err)

        threading.Thread(target=work, daemon=True,
                         name="video-source-find").start()
        return True

    def _best_progress(self, run, msg):
        if run == self._b_run:
            self._best_set(status=msg)

    def _best_done(self, run, res, err):
        if run != self._b_run:
            return
        if err:
            self._best_set(busy=False, status=err)
            return
        rows = []
        for rel in sorted((res or {}).get("matches") or {}):
            m = res["matches"][rel]
            clip = res["clips"].get(rel)
            now = self._assign.get(rel) or ""
            # A file that is only the card's own clip again is no reason to
            # replace a pick this project already has on this PC.
            keep_now = bool(m.card_copy and now and os.path.isfile(now))
            row = {"rel": rel, "name": rel.split("/", 1)[-1],
                   "len": _length(clip.duration if clip else 0),
                   "now": os.path.basename(now) if now else "",
                   "sure": bool(m.sure), "trimmed": bool(m.trimmed),
                   "use": m.best is not None and not keep_now,
                   "match": ("%.0f%%" % (max(0.0, m.score) * 100)) if
                   m.best is not None else "not found"}
            if m.best is not None:
                s = m.best
                same = (os.path.normcase(os.path.abspath(now))
                        == os.path.normcase(os.path.abspath(s.path))) \
                    if now else False
                notes = []
                if not m.sure:
                    notes.append("worth a look")
                if m.card_copy:
                    notes.append("already on the card untouched")
                if m.same:
                    notes.append("%d other cop%s" % (
                        len(m.same), "y" if len(m.same) == 1 else "ies"))
                if m.variants:
                    notes.append("%d other version%s" % (
                        len(m.variants), "" if len(m.variants) == 1 else "s"))
                if m.trimmed:
                    notes.append("longer: needs Trim / pad")
                if same:
                    notes.append("already this file")
                row.update(file=os.path.basename(s.path), path=s.path,
                           res="%dx%d" % (s.width, s.height),
                           rate=_rate(s.bitrate), note=", ".join(notes))
            else:
                row.update(file="", path="", res="", rate="", note=(
                    "closest was %.0f%%" % (m.score * 100))
                    if m.score > 0 else "")
            rows.append(row)
        # the ones to look at first: not found, then unsure, then the rest
        rows.sort(key=lambda r: (bool(r["path"]), r["sure"], r["name"]))
        self._b_rows = rows
        found = sum(1 for r in rows if r["path"])
        sure = sum(1 for r in rows if r["path"] and r["sure"])
        unnamed = len((res or {}).get("unnamed") or [])
        status = ("Found the file behind %d of %d replaced clip(s): %d "
                  "certain, %d worth a look (amber)." % (
                      found, len(rows), sure, found - sure))
        if unnamed:
            status += (" %d more replaced clip(s) aren't slots in this "
                       "project (a different game or code version?)."
                       % unnamed)
        if not rows:
            status = "No clip on that card differs from the stock card."
        self._best_set(busy=False, rows=rows, found=found, status=status,
                       can_apply=any(r["use"] and r["path"] for r in rows))

    @rpc
    def best_use_row(self, rel, value):
        for r in self._b_rows:
            if r["rel"] == rel and r["path"]:
                r["use"] = bool(value)
        self._best_set(rows=list(self._b_rows), can_apply=any(
            r["use"] and r["path"] for r in self._b_rows))
        return True

    @rpc
    def best_use_all(self, value):
        for r in self._b_rows:
            if r["path"]:
                r["use"] = bool(value)
        self._best_set(rows=list(self._b_rows), can_apply=any(
            r["use"] and r["path"] for r in self._b_rows))
        return True

    @rpc
    def best_reveal(self, rel):
        from . import video_helpers as vh
        for r in self._b_rows:
            if r["rel"] == rel and r["path"]:
                vh.reveal_in_file_manager(r["path"])
                return True
        return False

    @rpc
    def best_apply(self):
        """Use best quality: the ticked files become the slots'
        replacements and the option goes on."""
        if self._is_running():
            return False
        picked = [(r["rel"], r["path"]) for r in self._b_rows
                  if r["use"] and r["path"] and r["rel"] in self._by_rel]
        longer = [r for r in self._b_rows if r["use"] and r["path"]
                  and r.get("trimmed")]
        if longer and not self.video_trim_var.get():
            # A file longer than its clip was cut down by a Trim / pad
            # build; without it the next Write puts the whole file on.
            if compat.messagebox.askyesno(
                    "Files longer than their clips",
                    "%d of these files run longer than the clip on the card "
                    "(it was cut to its slot's length when it was built).\n\n"
                    "Turn on \"Trim / pad to the original clip length\" so "
                    "they are cut the same way again?\n\nNo leaves those "
                    "%d clip(s) as they are." % (len(longer), len(longer))):
                self.video_trim_var.set(True)
            else:
                skip = {r["rel"] for r in longer}
                picked = [(rel, p) for rel, p in picked if rel not in skip]
        changed = 0
        for rel, path in picked:
            if self._assign.get(rel) != path:
                self._assign[rel] = path
                changed += 1
        was_on = bool(self.video_best_quality_var.get())
        self.video_best_quality_var.set(True)
        self._save_staged()
        self._update_trim_enabled()
        self._refresh_list()
        live = sum(1 for p in self._assign.values() if p)
        if picked:
            self.log("Replace Video: %d clip(s) now use the file found for "
                     "them (%d changed)." % (len(picked), changed), "success")
        self.log("Replace Video: best quality is on — the next Write "
                 "converts %d replacement(s) at full quality. Build for a "
                 "16 GB or 32 GB SD card if they don't fit on 8 GB."
                 % live, "success" if not was_on or picked else "info")
        self._best_set(on=True, summary=self._best_summary(),
                       status=("Done: %d file(s) in use and best quality is "
                               "on. Build on the Write tab." % len(picked))
                       if picked else "Best quality is on. Build on the "
                                      "Write tab.")
        return True
