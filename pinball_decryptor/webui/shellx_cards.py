"""Settings ▸ Manage disk space ▸ "Card images" (PAD-1507): store card images
compact and make them full size again, from the app.

A Spike 3 card image is the whole 64 GB card and only 3-4 GB of it is data.
Stored COMPACT (a sparse file: core.sparse_card) it takes the size of its
data and is still the same .raw: builds, the emulator, extracting and
flashing read it as it is.  Full size is only wanted to put a card on a drive
that cannot hold compact files (exFAT, FAT32 - most USB sticks) or to hand it
to a program that copies it whole.  Four actions, each a worker thread with
the section's own progress bar:

* Compact a folder…  - every card image in it (not its subfolders)
* Compact cards…     - the card images picked
* Add a card compact… - a .raw/.img or its .zip/.xz/.gz/.bz2 download into a
  folder, never full size on disk
* Expand to full size… - a full-size copy somewhere else, or the card itself

State: ``shellx.disk.cards`` (note, status, pct, busy).
"""

import logging
import os
import threading

from ..core import sparse_card
from . import compat
from .rpc import rpc
from .shellx_common import fmt_binary as _fmt

log = logging.getLogger(__name__)

CARDS_NOTE = (
    "Card images can be stored compact: the same .raw file, the same bytes, "
    "but only the card's data takes disk space (a 62 GB Spike 3 card is about "
    "3-4 GB). Builds, the emulator, extracting and flashing use compact cards "
    "as they are. Expand only to copy a card onto a drive that cannot hold "
    "compact files (exFAT or FAT32, like most USB sticks), or for a program "
    "that needs the whole file.")

IMAGE_TYPES = (("Card images", "*.raw *.img"), ("All files", "*.*"))
ADD_TYPES = (("Card images and downloads",
              "*.raw *.img *.zip *.xz *.gz *.bz2"), ("All files", "*.*"))
BROWSE_KEY = "card_images"


def _mb():
    return compat.messagebox


def _gb(n):
    return _fmt(n)


class CardsMixin:
    """Mixed into the ``shellx`` service beside :class:`DiskMixin`."""

    def _cards_view(self, **kw):
        d = self._disk
        if d is None:
            return
        cards = dict(d["view"].get("cards") or {})
        cards.update(kw)
        self._disk_view(cards=cards)

    def _cards_initial(self):
        return {"note": CARDS_NOTE, "status": "", "pct": None, "busy": False}

    def _cards_ready(self):
        d = self._disk
        return d is not None and not d["busy"]

    def _cards_start(self, label, job, done):
        """Run *job(progress)* on a worker; *done(result, err)* on the loop."""
        self._disk_busy(True, label)
        self._cards_view(busy=True, pct=0, status=label)

        def progress(cur, total, text=None):
            pct = (cur * 100 // total) if total else None
            msg = text or label

            def _show():
                if self._disk is not None:
                    self._cards_view(pct=pct, status="%s %s%%" % (msg, pct)
                                     if pct is not None else msg)
            self.ctx.loop.post(_show)

        def _worker():
            try:
                res = job(progress)
                self.ctx.loop.post(self._cards_end, done, res, None)
            except Exception as e:                      # noqa: BLE001
                log.exception("card images: %s", label)
                self.ctx.loop.post(self._cards_end, done, None, str(e))

        threading.Thread(target=_worker, name="pad-shellx-cards",
                         daemon=True).start()
        return True

    def _cards_end(self, done, res, err):
        if self._disk is None:
            return
        self._disk_busy(False, "")
        text = done(res, err)
        self._cards_view(busy=False, pct=None, status=text or "")
        if err:
            _mb().showerror("Card images", err)

    # ------------------------------------------------------------------
    @rpc
    def cards_compact_folder(self):
        if not self._cards_ready():
            return False
        folder = self.window.ask_folder(
            BROWSE_KEY, "Pick the folder of card images to store compact")
        if not folder:
            return False
        names = sorted(n for n in os.listdir(folder) if sparse_card.is_image(n))
        if not names:
            _mb().showinfo("Card images",
                           "There is no .raw or .img card image in\n\n%s"
                           % folder)
            return False
        return self._compact([os.path.join(folder, n) for n in names])

    @rpc
    def cards_compact_files(self):
        if not self._cards_ready():
            return False
        paths = self.window.ask_open(
            BROWSE_KEY, "Pick the card images to store compact",
            filetypes=IMAGE_TYPES, multiple=True)
        if not paths:
            return False
        return self._compact(list(paths))

    def _compact(self, paths):
        n = len(paths)

        def job(progress):
            out = []
            for i, p in enumerate(paths):
                name = os.path.basename(p)
                text = ("Compacting %s (%d of %d)…" % (name, i + 1, n)
                        if n > 1 else "Compacting %s…" % name)
                out.append(sparse_card.compact_file(
                    p, progress=lambda d, t, _x=text: progress(d, t, _x)))
            return out

        def done(rs, err):
            if err:
                return ""
            freed = sum(r.saved for r in rs)
            refused = [os.path.basename(r.path) for r in rs
                       if not r.sparse_ok and r.after >= r.size]
            text = ("%d card image%s compact: %s on disk for %s of cards, "
                    "%s freed." % (len(rs), "" if len(rs) == 1 else "s",
                                   _gb(sum(r.after for r in rs)),
                                   _gb(sum(r.size for r in rs)), _gb(freed)))
            if refused:
                text += (" Left full size (this drive cannot hold compact "
                         "files): %s." % ", ".join(refused))
            return text

        return self._cards_start("Compacting…", job, done)

    @rpc
    def cards_add(self):
        if not self._cards_ready():
            return False
        srcs = self.window.ask_open(
            BROWSE_KEY, "Pick the new card image or its download (.zip, .xz…)",
            filetypes=ADD_TYPES, multiple=True)
        if not srcs:
            return False
        dest = self.window.ask_folder(
            BROWSE_KEY + "_into", "Pick the folder to keep the card in")
        if not dest:
            return False
        srcs = list(srcs)

        def job(progress):
            out = []
            for i, s in enumerate(srcs):
                text = "Adding %s (%d of %d)…" % (os.path.basename(s), i + 1,
                                                  len(srcs))
                out.append(sparse_card.import_card(
                    s, dest, progress=lambda d, t, _x=text:
                    progress(d, t, _x) if t else None))
            return out

        def done(outs, err):
            if err:
                return ""
            return "; ".join(
                "%s added: %s card, %s on disk"
                % (os.path.basename(o), _gb(os.path.getsize(o)),
                   _gb(sparse_card.on_disk_size(o))) for o in outs) + "."

        return self._cards_start("Adding…", job, done)

    @rpc
    def cards_expand(self):
        if not self._cards_ready():
            return False
        src = self.window.ask_open(
            BROWSE_KEY, "Pick the compact card image to make full size",
            filetypes=IMAGE_TYPES)
        if not src:
            return False
        size = os.path.getsize(src)
        ans = _mb().askyesnocancel(
            "Expand to full size",
            "%s is a %s card.\n\nYes: write a FULL-SIZE COPY somewhere else "
            "(a USB drive, for example) and keep this one compact.\n\nNo: make "
            "this card full size where it is (it will take %s on its drive)."
            % (os.path.basename(src), _gb(size), _gb(size)))
        if ans is None:
            return False
        if ans:
            dst = self.window.ask_save(
                BROWSE_KEY + "_expand", "Save the full-size card as",
                initialfile=os.path.basename(src), filetypes=IMAGE_TYPES,
                defaultextension=os.path.splitext(src)[1])
            if not dst:
                return False
            if os.path.normcase(os.path.abspath(dst)) == \
                    os.path.normcase(os.path.abspath(src)):
                ans = False
        name = os.path.basename(src)
        if ans:
            def job(progress):
                return sparse_card.expand_copy(
                    src, dst, progress=lambda d, t: progress(
                        d, t, "Writing the full-size copy of %s…" % name))

            def done(out, err):
                return "" if err else "Full-size copy written: %s (%s)." % (
                    out, _gb(size))
        else:
            def job(progress):
                return sparse_card.expand_file(
                    src, progress=lambda d, t: progress(
                        d, t, "Filling in %s…" % name))

            def done(n, err):
                return "" if err else "%s is full size again (%s filled in)." \
                    % (name, _gb(n or 0))
        return self._cards_start("Expanding…", job, done)
