"""Compare tab (Tk: ``MainWindow._build_compare_tab`` and its ``_compare_*``
methods).

Pick two card images of the same game, press Compare, read the plugin's
sectioned what-changed report (``mfr.compare_images``), fold / unfold long
change lists ("Rows per list"), double-click a listed file to pull it off the
right card and open it with the desktop (``mfr.extract_report_file``), copy
the WHOLE report as text (``core.image_info.as_text``), or Extract Both (the
run logic's ``_start_extract_both``, through the ``on_extract_both`` callback).

The report is kept whole in memory (``_sections``); what the page shows is a
flat ``rows`` list painted from it at the current limit, so the limit, a
folded group or a collapsed section costs a repaint, never a card read.
"""

import os
import threading

from .. import compat
from .base import TabService, rpc

#: Tk gui/main_window.py COMPARE_ROW_LIMIT_* (kept here: the Tk module is
#: deleted at the cut-over, and these are display choices, not report logic).
ROW_LIMIT_CHOICES = ("12", "25", "50", "100", "All")
ROW_LIMIT_DEFAULT = "50"

INTRO = ("Compare two card images of the same game — two releases, or a "
         "modded card against its stock base. Files are diffed by the cards' "
         "own validation digests and the adjustment / high-score defaults "
         "come from each card's game firmware, so the report needs no "
         "Extract. The packed sounds are the exception: run Extract Both and "
         "compare again, and every changed sound is listed by name. "
         "Double-click a listed file to open it — it is pulled off the card "
         "and handed to whatever you normally view or play it with.")

EXTRACT_BOTH_TIP = (
    "Extract image A and then image B into one folder you pick — a "
    "sub-folder per card, named after the card.\n\nThe report above "
    "diffs the cards' own digests, which is instant but cannot play "
    "you a sound or show you a scene. Two extracts can, and this "
    "queues both without you re-picking anything.\n\nWhen they "
    "finish, press Compare again: the Sounds section then lists the "
    "sounds that actually changed, and double-clicking one plays it.")

LIMIT_TIP = (
    "How many entries of each change list (modified images, moved "
    "sounds, …) the report shows before the rest are folded into "
    "one line.\n\nNothing is thrown away: double-click that line to "
    "list the rest of THAT group, or press Copy Report, which always "
    "copies every row.\n\nChanging this re-draws the report you are "
    "looking at — the cards are not read again.")


def normalize_row_limit(value):
    """A stored "Rows per list" choice as one of :data:`ROW_LIMIT_CHOICES`
    (Tk ``normalize_compare_row_limit``)."""
    text = str(value or "").strip()
    for choice in ROW_LIMIT_CHOICES:
        if text.lower() == choice.lower():
            return choice
    return ROW_LIMIT_DEFAULT


def row_limit_value(choice):
    """The choice as a row count, or ``None`` for "All"."""
    choice = normalize_row_limit(choice)
    return None if choice == "All" else int(choice)


class CompareTab(TabService):
    ns = "compare"
    key = "Compare"
    label = "Compare"
    group = "Inspect"
    icon = "compare"
    exports = ("compare_a_var", "compare_b_var", "compare_limit_var",
               "_compare_reset")

    def __init__(self, window):
        super().__init__(window)
        self.compare_a_var = self.var("a")
        self.compare_b_var = self.var("b")
        self.compare_limit_var = self.var(
            "limit", value=normalize_row_limit(
                self.window.cb.get("initial_compare_row_limit")))
        self._seq = 0
        self._sections = []
        self._refs = {}             # row id -> the plugin's file ref
        self._more = {}             # row id -> (section, group)
        self._expanded = set()      # (section, group) listed in full
        self._collapsed = set()     # section indexes folded shut
        self._open_busy = False
        # ``report`` counts reports: row ids are positional (s0g2…), so the
        # page drops its selected row whenever a different report (or none)
        # replaces the one it was picked in -- Tk's repaint deleted every
        # item, selection included.
        self._report = 0
        self.set(intro=INTRO, extract_both_tip=EXTRACT_BOTH_TIP,
                 limit_tip=LIMIT_TIP, limit_choices=list(ROW_LIMIT_CHOICES),
                 rows=[], running=False, has_report=False, status="",
                 hist_a=[], hist_b=[], report=0, widths=None)

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        self._compare_reset()
        self._push_history()

    def on_show(self):
        self._push_history()

    def _push_history(self):
        self.set(hist_a=self.window.path_history("compare_a"),
                 hist_b=self.window.path_history("compare_b"))

    def _compare_reset(self):
        """Drop the report + any in-flight worker (a manufacturer switch: a
        previous manufacturer's diff must not survive)."""
        self._seq += 1
        self._sections = []
        self._refs = {}
        self._more = {}
        self._expanded = set()
        self._collapsed = set()
        self._report += 1
        self.set(rows=[], running=False, has_report=False, status="",
                 report=self._report)

    # ------------------------------------------------------------------
    # pickers
    # ------------------------------------------------------------------
    def _paths(self):
        """Both boxes, stripped, with a mapped drive letter this session
        cannot see rewritten to its UNC target (the Tk path box did that on
        focus-out)."""
        out = []
        for var in (self.compare_a_var, self.compare_b_var):
            v = (var.get() or "").strip()
            if v:
                try:
                    from ...core.admin import resolve_mapped_drive
                    fixed = resolve_mapped_drive(v)
                except Exception:                # noqa: BLE001
                    fixed = v
                if fixed != v:
                    var.set(fixed)
                    v = fixed
            out.append(v)
        return out[0], out[1]

    def _input_filetypes(self):
        mfr = self.mfr
        spec = getattr(mfr, "input_spec", None) if mfr is not None else None
        if spec is None or not spec.extensions:
            return [("All files", "*.*")]
        joined = " ".join("*%s" % ext for ext in spec.extensions)
        return [(spec.label, joined), ("All files", "*.*")]

    @rpc
    def browse(self, side):
        var = self.compare_a_var if side == "a" else self.compare_b_var
        ext_var = getattr(self.window, "extract_input_var", None)
        path = self.window.ask_open(
            "compare_" + side, "Select card image", self._input_filetypes(),
            initialdir=self.window._initialdir_for(
                var.get(), ext_var.get() if ext_var is not None else ""))
        if path:
            var.set(os.path.normpath(path))
        return path

    # ------------------------------------------------------------------
    # compare
    # ------------------------------------------------------------------
    def _extract_roots(self, a, b):
        """Where to look for the two cards' extract folders (Tk
        ``_compare_extract_roots``): the Extract Both parent, the Extract
        tab's output and its parent, the project folder, and each card's own
        folder; each is checked itself and one level up."""
        def _v(name):
            var = getattr(self.window, name, None)
            try:
                return ((var.get() if var is not None else "") or "").strip()
            except Exception:                    # noqa: BLE001
                return ""
        cands = [self.window.last_browse_dir("extract_both"),
                 _v("extract_output_var"), _v("write_assets_var")]
        cands += [os.path.dirname(os.path.abspath(p)) for p in (a, b) if p]
        roots = []
        for cand in cands:
            if not cand:
                continue
            for d in (cand, os.path.dirname(cand)):
                if d and os.path.isdir(d) and d not in roots:
                    roots.append(d)
        return roots

    @rpc
    def run(self):
        """Diff the two picked images on a worker and paint the report."""
        a, b = self._paths()
        if not a or not b:
            compat.messagebox.showinfo(
                "Pick two images", "Pick both card images to compare first.")
            return False
        for side, p in (("A", a), ("B", b)):
            if not os.path.isfile(p):
                compat.messagebox.showerror("File not found",
                                            "Image %s:\n\n%s" % (side, p))
                return False
        mfr = self.mfr
        if mfr is None:
            return False
        cb = self.window.cb.get("on_compare_run")
        if cb is not None:
            cb(a, b)
        self._push_history()

        self._seq += 1
        seq = self._seq
        roots = self._extract_roots(a, b)

        def _worker():
            from ...core import extract_source
            try:
                sections = mfr.compare_images(
                    a, b,
                    assets_a=extract_source.find_extract_for(a, roots),
                    assets_b=extract_source.find_extract_for(b, roots)) or []
            except Exception as e:               # noqa: BLE001
                sections = [("Error", [("Could not compare", str(e))])]
            try:
                self.ctx.loop.post(self._landed, seq, sections)
            except Exception:                    # noqa: BLE001
                pass

        self._sections = []
        self._refs = {}
        self._more = {}
        self._expanded = set()
        self._collapsed = set()
        self._report += 1
        self.set(rows=[], running=True, has_report=False,
                 status="Comparing images…", report=self._report)
        threading.Thread(target=_worker, daemon=True,
                         name="pad-compare").start()
        return True

    def _landed(self, seq, sections):
        if seq != self._seq:
            return                              # superseded / mfr switched
        self.render(sections)

    def render(self, sections):
        """Take a finished report (Tk ``_compare_render``): kept WHOLE, drawn
        at the current limit, nothing expanded."""
        self._sections = list(sections or [])
        self._expanded = set()
        self._collapsed = set()
        self._report += 1
        self._paint()
        self.set(running=False, has_report=bool(self._sections), status="",
                 report=self._report)

    def _paint(self):
        """Flatten the stored report at the current "Rows per list"."""
        from ...core.image_info import group_rows
        self._refs = {}
        self._more = {}
        limit = row_limit_value(self.compare_limit_var.get())
        rows = []

        def _row(rid, kind, sec, r):
            item = {"id": rid, "kind": kind, "sec": sec,
                    "change": str(r[0]), "details": str(r[1]),
                    "open": len(r) > 2}
            if len(r) > 2:
                self._refs[rid] = r[2]
            rows.append(item)

        for s_i, (title, srows) in enumerate(self._sections):
            shut = s_i in self._collapsed
            rows.append({"id": "s%d" % s_i, "kind": "section", "sec": s_i,
                         "change": str(title), "details": "",
                         "open": False, "shut": shut,
                         "count": len(srows)})
            if shut:
                continue
            for g_i, (head, items) in enumerate(group_rows(srows)):
                key = (s_i, g_i)
                _row("s%dg%d" % key, "head", s_i, head)
                full = limit is None or key in self._expanded
                shown = items if full else items[:limit]
                for k, r in enumerate(shown):
                    _row("s%dg%di%d" % (s_i, g_i, k), "item", s_i, r)
                hidden = len(items) - len(shown)
                if hidden:
                    rid = "s%dg%dm" % key
                    rows.append({
                        "id": rid, "kind": "more", "sec": s_i, "change": "",
                        "details": "… and %s more — double-click to list "
                                   "them" % format(hidden, ","),
                        "open": False})
                    self._more[rid] = key
        self.set(rows=rows)

    @rpc
    def set_limit(self, choice):
        """"Rows per list" picked: repaint and remember the choice."""
        choice = normalize_row_limit(choice)
        self.compare_limit_var.set(choice)
        if self._sections:
            self._paint()
        cb = self.window.cb.get("on_compare_row_limit_change")
        if cb is not None:
            cb(choice)
        return choice

    @rpc
    def expand(self, rid):
        """A "… and N more" row: list the rest of THAT group only."""
        key = self._more.get(rid)
        if key is None:
            return False
        self._expanded.add(key)
        self._paint()
        return True

    @rpc
    def toggle_section(self, sec):
        sec = int(sec)
        if sec in self._collapsed:
            self._collapsed.discard(sec)
        else:
            self._collapsed.add(sec)
        self._paint()
        return True

    @rpc
    def set_all_sections(self, shut):
        self._collapsed = (set(range(len(self._sections))) if shut
                           else set())
        self._paint()
        return True

    @rpc
    def set_widths(self, widths):
        """The Change column's width after a header drag (every
        ttk.Treeview header resized its column).  Kept for the session, as
        Tk did for this tree: it never saved them under column_widths."""
        clean = {str(k): int(v) for k, v in (widths or {}).items()
                 if k == "change"
                 and isinstance(v, (int, float)) and 20 <= v <= 4000}
        self.set(widths=clean or None)
        return bool(clean)

    @rpc
    def copy_report(self):
        """Copy the WHOLE report, every row of every list."""
        from ...core import image_info
        if not self._sections:
            return False
        text = image_info.as_text(self._sections, title="Compare Report")
        root = getattr(self.app, "root", None)
        if root is not None:
            root.clipboard_clear()
            root.clipboard_append(text)
        self.set(status="Report copied to clipboard — every row, not just "
                        "the ones shown.")
        return text

    # ------------------------------------------------------------------
    # opening a listed file
    # ------------------------------------------------------------------
    @rpc
    def activate(self, rid):
        """Double-click: a fold row lists the rest of its group; a file row
        opens that file; anything else says why nothing happened."""
        if rid in self._more:
            return self.expand(rid)
        if rid.startswith("s") and rid[1:].isdigit():
            return self.toggle_section(int(rid[1:]))
        return self.open_row(rid)

    def _open_target(self, rid):
        ref = self._refs.get(rid)
        if ref is None:
            self.set(status="Only the listed files open — double-click one "
                            "of the file rows.")
            return None
        side = (ref.get("side") or "B").upper()
        image = ((self.compare_a_var.get() if side == "A"
                  else self.compare_b_var.get()) or "").strip()
        if not image or not os.path.isfile(image):
            compat.messagebox.showerror(
                "Open %s" % (ref.get("name") or "file"),
                "Image %s is no longer at:\n\n%s" % (side, image))
            return None
        return side, image, ref

    @rpc
    def open_row(self, rid):
        """Pull the listed file off its card into a temp folder and open it
        with the desktop (Tk ``_compare_open_iid``)."""
        if self._open_busy:
            return False
        mfr = self.mfr
        target = self._open_target(rid) if mfr is not None else None
        if target is None:
            return False
        side, image, ref = target
        name = ref.get("name") or "file"
        self._open_busy = True
        self.set(status="Opening %s from image %s…" % (name, side))

        def _worker():
            import tempfile
            path = err = None
            try:
                out = tempfile.mkdtemp(prefix="spike2_compare_")
                path = mfr.extract_report_file(image, ref, out)
            except Exception as e:               # noqa: BLE001
                err = e
            try:
                self.ctx.loop.post(self._open_finished, name, side, path, err)
            except Exception:                    # noqa: BLE001
                pass

        threading.Thread(target=_worker, daemon=True,
                         name="pad-compare-open").start()
        return True

    def _open_finished(self, name, side, path, err):
        from ...core import desktop
        self._open_busy = False
        if err is not None:
            self.set(status="")
            compat.messagebox.showerror(
                "Open %s" % name,
                "That file couldn't be read off image %s:\n\n%s" % (side, err))
            return
        ok, why = desktop.open_path(path)
        if ok:
            self.set(status="Opened %s from image %s." % (name, side))
        else:
            self.set(status="")
            compat.messagebox.showinfo(
                "Open %s" % name,
                "The file was copied here, but the desktop wouldn't open "
                "it:\n\n%s\n\n%s" % (path, why))

    # ------------------------------------------------------------------
    # Extract Both
    # ------------------------------------------------------------------
    @rpc
    def extract_both(self):
        """Hand the pair to the run logic's Extract Both after the Tk tab's
        checks (two real, different images)."""
        a, b = self._paths()
        if not a or not b:
            compat.messagebox.showinfo(
                "Pick two images",
                "Pick both card images first — Extract Both extracts the "
                "pair.")
            return False
        for side, p in (("A", a), ("B", b)):
            if not os.path.isfile(p):
                compat.messagebox.showerror("File not found",
                                            "Image %s:\n\n%s" % (side, p))
                return False
        if os.path.normcase(os.path.abspath(a)) == os.path.normcase(
                os.path.abspath(b)):
            compat.messagebox.showinfo(
                "Same image twice",
                "Images A and B are the same file, so there is only one "
                "extract to run — use the Extract tab.")
            return False
        cb = self.window.cb.get("on_extract_both")
        if cb is not None:
            cb(a, b)
        return True


TAB = CompareTab
