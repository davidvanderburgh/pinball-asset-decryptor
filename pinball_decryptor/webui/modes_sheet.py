"""PAD-664: the Modes tab's Rules sheet... dialog - the printable rules sheet of the project's modes.

The words come from :mod:`..plugins.stern.rules_sheet` (a blocks mode is played on the desk to word it, so the first
look takes a few seconds and runs on a worker; after that each mode's words are kept until its file changes). The
dialog shows the sheet as it prints, and lets the person put a mode's words of their own in place of the app's (one
field at a time: what they write wins, an empty field gives the app's back), leave a mode off, move it up or down,
and change the title, the line under it and the foot. Save as PDF... (Letter or A4, landscape) and Save as HTML...
write the files, by default into the project folder. Print... (PAD-695) prints the preview page through the system's
print dialog; where the window cannot print a page (macOS, Qt) :meth:`sheet_print` opens the sheet's PDF in the
system's viewer to print from.
"""

import os
import re
import tempfile
import threading

from ..plugins.stern import rules_sheet as RS
from . import compat
from .rpc import rpc

SHEET_FIELDS = ("start", "stages", "cash", "tag")
SHEET_SETTINGS = ("title", "intro", "foot", "paper")


class RulesSheetMixin:
    """The Rules sheet dialog's state is ``sheet`` in the tab's store: None while it is closed."""

    def _init_sheet(self):
        self._sheet = None              # rules_sheet.build()'s sheet while the dialog is open
        self._sheet_seq = 0

    def _sheet_args(self):
        project = self.project()
        card = None
        try:
            card = self._title_card(project)[0] if project else None
        except Exception:                                   # noqa: BLE001 - the title is only words here
            card = None
        label = self.get("title_label") or self.get("card_label") or ""
        return project, getattr(self, "_profile", None), label, (card.image if card is not None else "") or ""

    @rpc
    def sheet_open(self):
        """Rules sheet...: build the sheet on a worker and open the dialog on it."""
        project = self.project()
        if not project:
            return
        try:
            self._save_if_edited()                          # the open mode's last edit is on the sheet too
        except Exception:                                   # noqa: BLE001
            pass
        self._sheet_seq += 1
        seq = self._sheet_seq
        self.set(sheet={"busy": True, "seq": seq, "rows": [], "left": []})
        args = self._sheet_args()

        def work():
            try:
                value, ok = RS.build(*args), True
            except Exception as e:                          # noqa: BLE001 - said in the dialog
                value, ok = e, False
            self._post(land, value, ok)

        def land(value, ok):
            if seq != self._sheet_seq or self.get("sheet") is None:
                return
            if not ok:
                self._sheet = None
                self.set(sheet={"busy": False, "seq": seq, "error": "The rules sheet could not be made: %s" % value,
                                "rows": [], "left": []})
                return
            self._sheet = value
            self._sheet_publish()

        threading.Thread(target=work, daemon=True, name="modes-rules-sheet").start()

    @rpc
    def sheet_close(self):
        self._sheet_seq += 1
        self._sheet = None
        self.set(sheet=None)

    def _sheet_rebuild(self):
        """After an edit: the sheet again (each mode's words are kept, so this is quick)."""
        if self._sheet is None:
            return
        try:
            self._sheet = RS.build(*self._sheet_args())
        except Exception as e:                              # noqa: BLE001
            self._say("the rules sheet could not be made again: %s" % e)
            return
        self._sheet_publish()

    def _sheet_publish(self):
        sh = self._sheet
        st = sh["settings"]
        rows = [{"slug": r["slug"], "name": r["name"], "kind": r["kind"], "on": r["on"], "tag": r["tag"],
                 "start": r["start"], "stages": list(r["stages"]), "cash": r["cash"],
                 "gen": {"start": r["gen"]["start"] or "", "stages": list(r["gen"]["stages"] or []),
                         "cash": r["gen"]["cash"] or ""},
                 "own": dict(r["own"])} for r in sh["modes"]]
        self.set(sheet={
            "busy": False, "seq": self._sheet_seq, "error": "",
            "title": sh["title"], "intro": sh["intro"], "foot": sh["foot"], "paper": sh["paper"],
            "own": {k: st.get(k, "") for k in ("title", "intro", "foot")},
            "rows": rows, "left": [{"name": n, "why": w} for n, w in sh["left"]],
            "n_on": len(sh["rows"]), "html": RS.to_html(sh, sh["paper"]),
        })

    @rpc
    def sheet_words(self, slug, field, value):
        """A mode's own words for one field ("" gives the app's back). ``stages``: one stage a line."""
        if self._sheet is None or field not in SHEET_FIELDS:
            return
        project = self.project()
        own = RS.load_mode_words(project, slug)
        own[field] = value
        try:
            RS.save_mode_words(project, slug, own)
        except OSError as e:
            compat.messagebox.showinfo("Rules sheet", "Could not keep those words: %s" % e)
            return
        self._sheet_rebuild()

    @rpc
    def sheet_setting(self, key, value):
        """The sheet's title, line under it, foot ("" gives the app's back) or paper ("letter" / "a4")."""
        if self._sheet is None or key not in SHEET_SETTINGS:
            return
        project = self.project()
        st = RS.load_settings(project)
        st[key] = value
        try:
            RS.save_settings(project, st)
        except OSError as e:
            compat.messagebox.showinfo("Rules sheet", "Could not keep that: %s" % e)
            return
        self._sheet_rebuild()

    @rpc
    def sheet_on(self, slug, on):
        """Put a mode on the sheet or leave it off."""
        if self._sheet is None:
            return
        project = self.project()
        st = RS.load_settings(project)
        off = [s for s in st["off"] if s != slug] + ([] if on else [slug])
        st["off"] = off
        RS.save_settings(project, st)
        self._sheet_rebuild()

    @rpc
    def sheet_move(self, slug, step):
        """Move a mode up (-1) or down (1) the sheet."""
        if self._sheet is None:
            return
        order = [r["slug"] for r in self._sheet["modes"]]
        if slug not in order:
            return
        i = order.index(slug)
        j = max(0, min(len(order) - 1, i + int(step)))
        order.insert(j, order.pop(i))
        project = self.project()
        st = RS.load_settings(project)
        st["order"] = order
        RS.save_settings(project, st)
        self._sheet_rebuild()

    @rpc
    def sheet_print(self):
        """Print... where the window cannot print the preview itself: the sheet's PDF, written to a temporary
        folder, opened in the system's PDF viewer to print from. Returns the path written, or None."""
        sh = self._sheet
        if sh is None:
            return None
        from ..core import desktop
        folder = os.path.join(tempfile.gettempdir(), "pad-rules-sheet")
        path = os.path.join(folder, _stem(sh) + ".pdf")
        try:
            os.makedirs(folder, exist_ok=True)
            with open(path, "wb") as f:
                f.write(RS.to_pdf(sh, sh["paper"]))
        except OSError as e:
            compat.messagebox.showinfo("Rules sheet", "Could not make the sheet to print: %s" % e)
            return None

        def show():                                         # an opener can take a few seconds to answer
            ok, err = desktop.open_path(path)
            self._post(self._say, "opened the rules sheet to print: %s" % path if ok else
                       "could not open the rules sheet to print (%s); it is at %s" % (err, path))
        path = os.path.normpath(path)
        threading.Thread(target=show, daemon=True, name="modes-rules-sheet-print").start()
        return path

    @rpc
    def sheet_save(self, kind="pdf"):
        """Save as PDF... / Save as HTML...: the sheet as it is shown, by default into the project folder. Returns
        the path written, or None."""
        sh = self._sheet
        if sh is None or kind not in ("pdf", "html"):
            return None
        stem = _stem(sh)
        ext = "." + kind
        path = self.window.ask_save(
            "modes_rules_sheet", "Save the rules sheet as %s" % kind.upper(), initialfile=stem + ext,
            filetypes=[("PDF", "*.pdf")] if kind == "pdf" else [("Web page", "*.html")],
            defaultextension=ext, initialdir=self.project() or None)
        if not path:
            return None
        try:
            if kind == "pdf":
                data = RS.to_pdf(sh, sh["paper"])
                with open(path, "wb") as f:
                    f.write(data)
            else:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(RS.to_html(sh, sh["paper"]))
        except OSError as e:
            compat.messagebox.showinfo("Rules sheet", "Could not save it: %s" % e)
            return None
        self._say("saved the rules sheet (%d mode%s) to %s"
                  % (len(sh["rows"]), "" if len(sh["rows"]) == 1 else "s", os.path.normpath(path)))
        return path


def _stem(sheet):
    """The sheet's file name: its title, with what a file name cannot hold made "_"."""
    return re.sub(r'[\\/:*?"<>|]+', "_", sheet["title"]).strip() or "Rules sheet"
