"""Save with color profile (PAD-604): the Images and Video tabs save pictures
or clips as files of their own, each with its color profile baked in
(:mod:`core.colour_export`), into a folder the user picks.  Nothing in the
project changes.

A tab using :class:`ColourSaveMixin` gives:

- ``_cs_kind``: "images" or "videos" (the colour profile kind)
- ``_cs_noun``: ("picture", "pictures") or ("clip", "clips")
- ``_cs_project()``: the project folder
- ``_cs_source(rel)``: the file *rel*'s profile is baked into (its
  replacement, else the game's own, from the pristine snapshot where a build
  changed it), or ``None``
- ``_cs_profiled()``: the rels with a color profile attached
- ``_per_file_colour()``: whether each file has a profile of its own

and gets the rpcs ``colour_save(rels=None, folder=None)`` (*rels* None:
every file with a profile attached) and ``colour_save_cancel()``, and the
state key ``csave`` (``{"text", "pct"}`` while it runs, else ``None``).
"""
import logging
import os
import threading

from . import compat
from .rpc import rpc

log = logging.getLogger(__name__)

TITLE = "Save with color profile"


class ColourSaveMixin:
    def __init__(self, window):
        super().__init__(window)
        self._cs_cancel = None
        self.set(csave=None)

    def _cs_profile_of(self, rels):
        """``{rel: Profile or None}``: what a build bakes into each file (its
        own profile, else the project's individual files one; where the files
        have none of their own, the project's whole profile)."""
        from ..core import colour_profile as cp
        folder = self._cs_project()
        if self._per_file_colour():
            resolve = cp.asset_resolver(folder)
            return {rel: resolve(self._cs_kind, rel) for rel in rels}
        prof = cp.active(folder) if folder else None
        return {rel: prof for rel in rels}

    def _cs_menu_label(self, n):
        one, many = self._cs_noun
        return ("Save this %s with its color profile…" % one if n == 1
                else "Save %d %s with their color profiles…" % (n, many))

    @rpc
    def colour_save(self, rels=None, folder=None):
        """Save *rels* (``None``: every file with a color profile attached)
        with their color profiles baked in, into *folder* (asked for when not
        given).  Runs off the loop; returns True once started."""
        one, many = self._cs_noun
        if self._cs_cancel is not None:
            compat.messagebox.showinfo(TITLE, "A save is still running.")
            return False
        project = self._cs_project()
        if rels is None:
            rels = sorted(self._cs_profiled())
            if not rels:
                compat.messagebox.showinfo(
                    TITLE, "No %s has a color profile attached. Attach one "
                    "(the palette in the Color column), or select %s, "
                    "right-click and save them." % (one, many))
                return False
        profs = self._cs_profile_of(rels)
        items, left = [], []
        for rel in rels:
            prof = profs.get(rel)
            src = self._cs_source(rel)
            if src is None or not os.path.isfile(src):
                left.append((rel, "its file is not on this PC"))
            elif prof is None:
                left.append((rel, "its color profile changes nothing"))
            else:
                items.append((rel, src, prof))
        if not items:
            compat.messagebox.showinfo(
                TITLE, "Nothing to save:\n\n" + _lines(left))
            return False
        if not folder:
            folder = self.window.ask_folder(
                "colour_save_" + self._cs_kind,
                "Save %d %s with %s color profile%s into…" % (
                    len(items), one if len(items) == 1 else many,
                    "its" if len(items) == 1 else "their",
                    "" if len(items) == 1 else "s"))
        if not folder:
            return False
        folder = os.path.normpath(folder)
        if project and _inside(folder, project):
            compat.messagebox.showinfo(
                TITLE, "Pick a folder outside the project folder: the files "
                "in it are the ones the card is built from.")
            return False
        from ..core import colour_export as ce
        srcs = [src for _r, src, _p in items]
        clash = ce.existing(self._cs_kind, srcs, folder)
        replace = False
        if clash:
            ans = compat.messagebox.askyesnocancel(
                TITLE, "%d file%s of the same name %s already in %s.\n\n"
                "Yes: replace %s.  No: keep %s and save numbered copies."
                % (clash, "" if clash == 1 else "s",
                   "is" if clash == 1 else "are", folder,
                   "it" if clash == 1 else "them",
                   "it" if clash == 1 else "them"))
            if ans is None:
                return False
            replace = bool(ans)
        dsts = ce.plan_names(self._cs_kind, srcs, folder, replace=replace)
        work = [(rel, src, dst, prof)
                for (rel, src, prof), dst in zip(items, dsts)]
        stop = threading.Event()
        self._cs_cancel = stop
        noun = many if len(work) > 1 else one
        self.set(csave={"text": "Saving %d %s with color profiles…"
                        % (len(work), noun), "pct": 0})
        self.log("Saving %d %s with their color profiles into %s."
                 % (len(work), noun, folder), "info")

        def progress(done, total, rel):
            self.ctx.loop.post(self._cs_progress, stop, done, total, rel)

        def logged(text, level="info"):
            self.ctx.loop.post(self.log, text, level)

        def run():
            try:
                res = ce.save_all(self._cs_kind, work, log_cb=logged,
                                  progress_cb=progress,
                                  cancel_cb=stop.is_set)
            except Exception as e:                      # noqa: BLE001
                log.exception("colour save")
                res = {"saved": [], "failed": [("", str(e))],
                       "cancelled": False}
            self.ctx.loop.post(self._cs_done, stop, folder, res, left)

        threading.Thread(target=run, daemon=True,
                         name="pad-colour-save").start()
        return True

    def _cs_progress(self, stop, done, total, rel):
        if self._cs_cancel is not stop or stop.is_set():
            return
        one, many = self._cs_noun
        text = ("Saving %s %d of %d with its color profile: %s"
                % (one, done + 1, total, os.path.basename(rel))
                if done < total else "Saved.")
        self.set(csave={"text": text,
                        "pct": int(100 * done / total) if total else 100})

    @rpc
    def colour_save_cancel(self):
        stop = self._cs_cancel
        if stop is None:
            return False
        stop.set()
        cur = dict(self.get("csave") or {})
        cur["text"] = "Canceling…"
        self.set(csave=cur)
        return True

    def _cs_done(self, stop, folder, res, left):
        if self._cs_cancel is stop:
            self._cs_cancel = None
        self.set(csave=None)
        one, many = self._cs_noun
        saved, failed = res["saved"], list(res["failed"]) + list(left)
        n = len(saved)
        head = ("Saved %d %s with %s color profile%s into %s." % (
            n, one if n == 1 else many, "its" if n == 1 else "their",
            "" if n == 1 else "s", folder)) if n else "Nothing was saved."
        if res["cancelled"]:
            head = "Canceled. " + head
        self.log(head, "success" if n and not failed else "warn")
        body = head
        if failed:
            body += "\n\nNot saved:\n" + _lines(failed)
        if n:
            if compat.messagebox.askyesno(TITLE, body + "\n\nOpen the folder?"):
                from .shellx_common import open_in_default_app_or_warn
                open_in_default_app_or_warn(folder)
        else:
            compat.messagebox.showinfo(TITLE, body)


def _lines(pairs, cap=10):
    rows = ["%s: %s" % (os.path.basename(rel) or "?", why)
            for rel, why in pairs[:cap]]
    if len(pairs) > cap:
        rows.append("and %d more" % (len(pairs) - cap))
    return "\n".join(rows)


def _inside(path, folder):
    """Is *path* *folder* or a folder inside it?"""
    try:
        a = os.path.normcase(os.path.realpath(path))
        b = os.path.normcase(os.path.realpath(folder))
        return a == b or os.path.commonpath([a, b]) == b
    except ValueError:                                  # other drives
        return False
