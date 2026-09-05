"""The images table on the Multi-boot tab: one row of real widgets each.

WHY THIS IS NOT A ``ttk.Treeview``.  It was one, and a Treeview cannot do
what the table has to do.  It colours a ROW and never one cell of it, it
holds no widgets, and it cannot underline text under the pointer - so the
row's actions had to be monochrome glyph columns whose meaning lived in a
docstring (David, 2026-09-02: *"the edit button is hidden behind the
'feather' icon which doesn't make sense. make it a pencil… the edit icon
should stand out (like green). and the remove should be a trash icon and
red. the up and down arrows should also be green. all of the icons should
be on the far left side… clicking any of the column entries should just
bring up the edit modal (and show the text being underlined when hovered
on)"*).  Every one of those is a per-cell colour, a widget, or a hover
state.  With at most sixteen images a grid of labels inside a scrolled
frame is the right shape, and it is not much code.

The icons are CANVAS DRAWINGS, not characters - see
:func:`..widgets.draw_pencil_icon`, which carries the reason.  Green and
red are the theme's own ``success`` / ``error``, the same hues the log uses
for the same two meanings, and an action that cannot do anything from this
row (up on the first, down on the last) is drawn in ``gray`` instead of
silently doing nothing.

HOW THE COLUMNS STAY ALIGNED with the headings above them.  Two grids in
two frames align only if neither can be widened by its own content, so
every cell label is given a fixed width in CHARACTERS derived from its
column's pixel minsize, in the one font both grids use.  A label that has
been given a width clips what will not fit, which is what a table should
do; the whole text is in the tooltip and, for the selected row, on the
line under the table.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .theme import THEMES
from .widgets import (_Tooltip, draw_arrow_icon, draw_pencil_icon,
                      draw_plus_icon, draw_trash_icon)


#: The pixel box one row icon is drawn in, and the gap around it.  Eighteen
#: is the smallest the trash's slots survive at 100% scaling.
ICON_PX = 18
ICON_PAD = 3

#: Fallback row height, for a table asked how tall it is before Tk has laid
#: a single row out (the screenshot rig, and every test that never maps the
#: window).
ROW_PX = 21

#: How wide a cell's text may be, as a fraction of the column: the label's
#: character width is the column's pixels divided by the font's widest
#: digit, and a proportional font fits rather more than that per line.  The
#: cell clips, so erring wide is what fills the column.
CELL_FUDGE = 1.15


class _Cell(tk.Label):
    """One text cell: clips, underlines under the pointer, opens the row."""

    def __init__(self, table, parent, row, col, **kw):
        tk.Label.__init__(self, parent, anchor=tk.W, padx=5, pady=2,
                          bd=0, highlightthickness=0, **kw)
        self._table = table
        self.row = row
        self.col = col
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        for seq in ("<Button-3>", "<Button-2>"):
            self.bind(seq, self._context)

    def _context(self, event=None):
        self._table.context(self.row, event)
        return "break"

    def _enter(self, _event=None):
        # UNDERLINED UNDER THE POINTER because the click does something:
        # every cell of a row opens that image, and a table whose text is
        # secretly clickable is a table nobody clicks.
        if self["text"].strip():
            self.configure(font=self._table.font_hover, cursor="hand2")

    def _leave(self, _event=None):
        self.configure(font=self._table.font, cursor="")

    def _click(self, _event=None):
        self._table.cell_clicked(self.row)
        return "break"


class _Icon(tk.Canvas):
    """One row action, drawn rather than typed."""

    def __init__(self, table, parent, row, kind, tip, bg):
        tk.Canvas.__init__(self, parent, width=ICON_PX, height=ICON_PX,
                           bd=0, highlightthickness=0, bg=bg,
                           takefocus=0)
        self._table = table
        self.row = row
        self.kind = kind
        self.live = True
        self.bind("<Button-1>", self._click)
        for seq in ("<Button-3>", "<Button-2>"):
            self.bind(seq, self._context)
        self.tip = _Tooltip(self, tip, table.theme_fn, place="below")

    def _context(self, event=None):
        self._table.context(self.row, event)
        return "break"

    def paint(self, color, bg, live):
        """Redraw in *color* on *bg*; *live* colours a dead action gray."""
        self.live = bool(live)
        try:
            self.configure(bg=bg, cursor="hand2" if live else "")
            self.delete("all")
        except tk.TclError:                             # pragma: no cover
            return
        if self.kind == "edit":
            draw_pencil_icon(self, ICON_PX, color)
        elif self.kind == "del":
            draw_trash_icon(self, ICON_PX, color, bg)
        elif self.kind == "add":
            draw_plus_icon(self, ICON_PX, color)
        else:
            draw_arrow_icon(self, ICON_PX, color, down=self.kind == "down")

    def _click(self, _event=None):
        if self.live:
            self._table.icon_clicked(self.row, self.kind)
        return "break"


class _Row(object):
    """The widgets of one line of the table, reused across refreshes.

    REUSED, not rebuilt: a refresh happens on every add, remove, reorder and
    load, and tearing down a hundred widgets to put a hundred back flickers
    and loses whatever the pointer was over.
    """

    def __init__(self, table, index, add=False):
        self.table = table
        self.index = index
        self.add = add
        self.icons = []
        self.cells = []
        body = table.body
        # THE TEMPLATE ROW IS A ROW, in the same grid and the same columns:
        # a wide label spanning the icons would be the one cell able to
        # widen a column, and every heading above would come unstuck from
        # what it names.  So it gets a green '+' where the pencils are and
        # says its words in the Title column.
        specs = [("add", table.add_tip)] if add else table.actions
        for c, (kind, tip) in enumerate(specs):
            ic = _Icon(table, body, index, kind, tip, table.colors["bg"])
            ic.grid(row=index, column=c, padx=ICON_PAD, pady=1)
            self.icons.append(ic)
        for j, spec in enumerate(table.columns):
            cell = _Cell(table, body, index, spec[0],
                         font=table.font, width=table.cell_chars[j])
            cell.grid(row=index, column=len(table.actions) + j, sticky="ew")
            self.cells.append(cell)
        self.lead = self.cells[0] if self.cells else None

    def widgets(self):
        return self.icons + self.cells

    def place(self, index):
        """Move every widget of this row to grid row *index*."""
        self.index = index
        for w in self.widgets():
            w.row = index
            try:
                w.grid_configure(row=index)
            except tk.TclError:                         # pragma: no cover
                pass

    def destroy(self):
        for w in self.widgets():
            try:
                w.destroy()
            except tk.TclError:                         # pragma: no cover
                pass


class ImageTable(ttk.Frame):
    """A table of images: icons on the left, text columns, one add row.

    *columns* is ``((id, heading, minwidth, stretch), …)`` and *actions* is
    ``((kind, tooltip), …)`` with *kind* in ``edit`` / ``del`` / ``up`` /
    ``down``.  The callbacks are the whole contract: *on_select* when the
    pointed-at row changes, *on_activate* when a row is opened (any cell, a
    double-click, or Enter), *on_action* with ``(index, kind)`` for an
    icon, *on_add* for the template row, and *on_context* with
    ``(index, x_root, y_root)`` for a right-click or the menu key (index is
    ``None`` off any image row) so the owner can pop its own menu - the
    icons are the visible way in, this is the one a hand trained on every
    other list and the keyboard reach for.
    """

    def __init__(self, parent, columns, actions, theme_fn,
                 on_select=None, on_activate=None, on_action=None,
                 on_add=None, on_context=None, add_text="Add…", add_tip="",
                 visible_rows=4, max_rows=8):
        ttk.Frame.__init__(self, parent)
        self.columns = tuple(columns)
        self.actions = tuple(actions)
        self.theme_fn = theme_fn
        self._on_select = on_select
        self._on_activate = on_activate
        self._on_action = on_action
        self._on_add = on_add
        self._on_context = on_context
        self.add_text = add_text
        self.add_tip = add_tip
        self._min_rows = visible_rows
        self._max_rows = max_rows
        self._sel = None
        self._rows = []
        self._add_row = None
        self._values = []
        self._locked = False
        self.colors = self._palette()

        self.font = tkfont.Font(font="TkDefaultFont")
        self.font_hover = tkfont.Font(font="TkDefaultFont")
        self.font_hover.configure(underline=1)
        digit = max(4, self.font.measure("0"))
        self.cell_chars = [max(3, int(spec[2] * CELL_FUDGE) // digit)
                           for spec in self.columns]

        self._build()
        self.set_rows([])

    # -- construction ---------------------------------------------------

    def _palette(self):
        try:
            name = self.theme_fn() if self.theme_fn else "dark"
        except Exception:                               # pragma: no cover
            name = "dark"
        return THEMES.get(name) or THEMES["dark"]

    def _build(self):
        th = self.colors
        # The headings sit in their own frame so they do not scroll away,
        # pinned to the same width as the canvas below it (see
        # ``pack_propagate`` below) - which is what makes two grids with
        # the same column configuration line up.
        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        self.head = ttk.Frame(top)
        self.head.pack(side=tk.LEFT, fill=tk.Y)
        # HEAD IS PINNED TO THE CANVAS'S WIDTH, not left to size itself.
        # A grid frame's natural width is the sum of its own columns'
        # minsizes - the same total as the body's grid, since the two are
        # configured identically - and pack's fill/expand only ever GROWS
        # a widget to fill spare cavity, never shrinks it below that
        # natural size.  So no spacer, however wide, could ever make
        # ``head`` narrower than its own content wants: two attempts at
        # sizing a spacer (a guessed constant, then the scrollbar's own
        # measured width, tried on both sides of it) all left ``head`` at
        # its full natural width regardless, because nothing was actually
        # capping IT.
        #
        # ``pack_propagate(False)`` hands that cap to us and STILL was not
        # enough on its own - ``head``'s children are placed with grid,
        # not pack, and Tk's propagation flag is PER GEOMETRY MANAGER: a
        # frame that only ever packs itself into its own master but grids
        # its own children needs BOTH turned off, or the grid side alone
        # keeps inflating the frame back up to its columns' total no
        # matter what the pack side is told (measured: still full width).
        # :meth:`_canvas_resized` then sets the number - every time the
        # canvas resizes - to the SAME pixel width ``body`` just got,
        # which is the one place it is actually measured (mid's own width
        # minus the scrollbar's).
        self.head.pack_propagate(False)
        self.head.grid_propagate(False)

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(mid, bd=0, highlightthickness=0,
                                bg=th["bg"], height=self._min_rows * ROW_PX)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # NO SCROLLBAR (David: "remove... the scrollbar").  Cards run to a
        # handful of images and the table shows up to max_rows of them; the
        # rare card with more is reached with the mouse wheel (bound below),
        # so the scrollregion stays live - there is just no bar drawn for it.
        self.body = tk.Frame(self.canvas, bd=0, highlightthickness=0,
                             bg=th["bg"])
        self._window = self.canvas.create_window((0, 0), window=self.body,
                                                 anchor="nw", tags="body")
        self.canvas.bind("<Configure>", self._canvas_resized)
        self.body.bind("<Configure>", self._body_resized)
        # The wheel is bound while the pointer is inside and released when
        # it leaves: a wheel binding that outlives the pointer scrolls this
        # table from the other side of the tab.
        self.canvas.bind("<Enter>", self._wheel_on)
        self.canvas.bind("<Leave>", self._wheel_off)
        # The keyboard reaches the table through the canvas, which takes
        # focus on a click: Enter opens the selected row, the arrows walk
        # the selection, and the menu key pops the context menu over it -
        # the same five things the icons and the right-click do.
        self.canvas.configure(takefocus=1)
        self.canvas.bind("<Button-1>", lambda _e: self.canvas.focus_set())
        self.canvas.bind("<Return>", self._key_activate)
        self.canvas.bind("<KP_Enter>", self._key_activate)
        self.canvas.bind("<Up>", lambda _e: self._key_step(-1))
        self.canvas.bind("<Down>", lambda _e: self._key_step(1))
        for seq in ("<App>", "<Shift-F10>", "<Button-3>", "<Button-2>"):
            try:
                self.canvas.bind(seq, self._canvas_context)
            except tk.TclError:                         # pragma: no cover
                pass

        # <Configure> on the canvas pins the heading width from here on.
        # For the very first paint (nothing has resized the canvas yet) it
        # is set to the table's natural width below, once that is known -
        # NOT by forcing an ``update_idletasks()`` here, which would flush
        # the whole tab's pending <Configure> events mid-construction,
        # including the preview strip's: it would then measure its
        # wraplength against a half-built window and cut every caption.
        self.head.configure(height=ROW_PX)

        for c, (kind, tip) in enumerate(self.actions):
            lbl = ttk.Label(self.head, text="", width=0)
            lbl.grid(row=0, column=c, padx=ICON_PAD)
            self.head.grid_columnconfigure(
                c, minsize=ICON_PX + 2 * ICON_PAD, weight=0)
            self.body.grid_columnconfigure(
                c, minsize=ICON_PX + 2 * ICON_PAD, weight=0)
        natural = len(self.actions) * (ICON_PX + 2 * ICON_PAD)
        for j, (name, head, width, stretch) in enumerate(self.columns):
            col = len(self.actions) + j
            lbl = tk.Label(self.head, text=head, anchor=tk.W, padx=5, pady=2,
                           bd=0, highlightthickness=0, font=self.font,
                           width=self.cell_chars[j], bg=th["bg"],
                           fg=th["gray"])
            lbl.grid(row=0, column=col, sticky="ew")
            for grid in (self.head, self.body):
                grid.grid_columnconfigure(col, minsize=width,
                                          weight=1 if stretch else 0)
            natural += width
        # THE TABLE REQUESTS A WIDTH OF ITS OWN - the sum of every column's
        # minsize - rather than leaving the canvas at its default (a canvas
        # asks for almost nothing).  Without this the whole tab collapsed to
        # the width of its OTHER rows when packed at its natural size (which
        # is how the tab's tests and the fit sweep measure it), and the
        # preview strip beside it, told it had only that much room, cut
        # every caption to a stub.  The Treeview it replaced requested the
        # sum of its column widths for the same reason; this restores that.
        # ``grid_propagate`` on ``head`` and the <Configure> pin still let
        # ``fill=x`` grow it past this with the window.
        try:
            self.canvas.configure(width=natural)
            self.head.configure(width=natural)     # aligned on the first paint
        except tk.TclError:                             # pragma: no cover
            pass
        self._natural_width = natural

    # -- geometry -------------------------------------------------------

    def _canvas_resized(self, event):
        """The canvas changed width: pin ``body`` (the scrolled rows) AND
        ``head`` (the fixed heading above them) to that same number of
        pixels, so the one place a width is actually measured is the one
        place both grids take it from."""
        try:
            self.canvas.itemconfigure("body", width=event.width)
        except tk.TclError:                             # pragma: no cover
            pass
        try:
            self.head.configure(width=max(1, event.width))
        except tk.TclError:                             # pragma: no cover
            pass

    def _body_resized(self, _event=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except tk.TclError:                             # pragma: no cover
            pass
        self._fit()

    def row_height(self):
        """One GRID row's height in pixels, once Tk has laid the body out.

        Measured off the body's own requested height divided by its rows,
        NOT a single cell's: the icon column grids with a pady the text
        cells do not, so a grid row is a pixel or two taller than a cell,
        and sizing the canvas to the cell height alone left it a few pixels
        short of the body - enough to arm the scrollbar with a table whose
        rows all fit.  Falls back to a cell's requested height, then to
        :data:`ROW_PX`, before the body is laid out."""
        nrows = len(self._rows) + (1 if self._add_row is not None else 0)
        if nrows > 0:
            try:
                bh = self.body.winfo_reqheight()
                if bh > nrows:
                    return int(round(bh / float(nrows)))
            except tk.TclError:                         # pragma: no cover
                pass
        for row in self._rows + ([self._add_row] if self._add_row else []):
            try:
                h = row.cells[0].winfo_reqheight()
            except (tk.TclError, IndexError):           # pragma: no cover
                continue
            if h > 1:
                return h
        return ROW_PX

    def _fit(self):
        """As tall as the table HAS rows, between its two limits.

        Eight rows of empty box under two images is a hole in the tab, and
        sixteen images would leave the picture nothing."""
        want = max(self._min_rows,
                   min(self._max_rows, len(self._rows) + 1))
        px = want * self.row_height()
        try:
            if int(self.canvas.cget("height")) != px:
                self.canvas.configure(height=px)
                return True
        except tk.TclError:                             # pragma: no cover
            pass
        return False

    # -- the wheel ------------------------------------------------------

    def _wheel_on(self, _event=None):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.canvas.bind_all(seq, self._wheel)
            except tk.TclError:                         # pragma: no cover
                pass

    def _wheel_off(self, _event=None):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.canvas.unbind_all(seq)
            except tk.TclError:                         # pragma: no cover
                pass

    def _wheel(self, event):
        delta = getattr(event, "delta", 0)
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            step = -1 if delta > 0 else 1
        try:
            self.canvas.yview_scroll(step, "units")
        except tk.TclError:                             # pragma: no cover
            pass
        return "break"

    # -- the rows -------------------------------------------------------

    def count(self):
        """How many image rows the table has (the add row is not one)."""
        return len(self._rows)

    def set_rows(self, values, select=None):
        """Replace the table's contents.

        *values* is one dict per image, keyed by column id; a missing key is
        an empty cell.  *select* points the table at a row afterwards, and
        ``None`` keeps whatever was selected if it still exists.
        """
        values = [dict(v) for v in values]
        keep = self._sel if select is None else select
        while len(self._rows) > len(values):
            self._rows.pop().destroy()
        while len(self._rows) < len(values):
            self._rows.append(_Row(self, len(self._rows)))
        if self._add_row is None:
            self._add_row = _Row(self, 0, add=True)
        self._add_row.place(len(self._rows))
        if self._add_row.lead is not None:
            self._add_row.lead.configure(text=self.add_text)
        self._values = values
        for i, row in enumerate(self._rows):
            for cell in row.cells:
                cell.configure(text=str(values[i].get(cell.col, "") or ""))
        if keep is not None and not (0 <= keep < len(values)):
            keep = len(values) - 1 if values else None
        self._sel = keep if keep is not None and keep >= 0 else None
        self._repaint()
        self._fit()

    def set_row(self, i, values):
        """One row's cells <- *values* (a dict), leaving the rest alone."""
        if not (0 <= i < len(self._rows)):
            return False
        self._values[i] = dict(values)
        for cell in self._rows[i].cells:
            cell.configure(text=str(self._values[i].get(cell.col, "") or ""))
        return True

    def set_cell(self, i, col, text):
        """One cell of one row."""
        if not (0 <= i < len(self._rows)):
            return False
        self._values[i][col] = text
        for cell in self._rows[i].cells:
            if cell.col == col:
                cell.configure(text=str(text or ""))
        return True

    def cell(self, i, col):
        """What row *i*'s *col* cell says - the table's own text, so a test
        reads exactly what is on screen."""
        if not (0 <= i < len(self._rows)):
            return None
        for c in self._rows[i].cells:
            if c.col == col:
                return c.cget("text")
        return None

    def row_values(self, i):
        """Row *i*'s cells as a dict, in column order."""
        if not (0 <= i < len(self._rows)):
            return None
        return dict((c.col, c.cget("text")) for c in self._rows[i].cells)

    def icon(self, i, kind):
        """Row *i*'s *kind* icon widget, for the tests and the tooltips."""
        if not (0 <= i < len(self._rows)):
            return None
        for ic in self._rows[i].icons:
            if ic.kind == kind:
                return ic
        return None

    def cell_widget(self, i, col):
        if not (0 <= i < len(self._rows)):
            return None
        for c in self._rows[i].cells:
            if c.col == col:
                return c
        return None

    # -- selection and colour -------------------------------------------

    def selected(self):
        return self._sel

    def select(self, i, notify=True):
        """Point the table at image *i*.

        The row here, the fields in the editor and the amber card in the
        picture are three views of ONE choice, so everything that moves that
        choice comes through here - the flippers included."""
        if i is None or not (0 <= i < len(self._rows)):
            return False
        changed = self._sel != i
        self._sel = i
        self._repaint()
        self._show(i)
        if notify and changed and self._on_select and not self._locked:
            self._on_select(i)
        return True

    def _show(self, i):
        """Scroll row *i* into the viewport if it is not in it."""
        row = self._rows[i] if 0 <= i < len(self._rows) else None
        if row is None or not row.cells:
            return
        try:
            top = row.cells[0].winfo_y()
            h = self.row_height()
            view = int(self.canvas.cget("height"))
            first = self.canvas.canvasy(0)
            if top < first:
                self.canvas.yview_moveto(
                    float(top) / max(1, self.body.winfo_height()))
            elif top + h > first + view:
                self.canvas.yview_moveto(
                    float(top + h - view) / max(1, self.body.winfo_height()))
        except (tk.TclError, ValueError):               # pragma: no cover
            pass

    def _repaint(self):
        # NO SELECTED-ROW HIGHLIGHT (David: "remove the blue highlight").
        # Every row is on the panel background; the selection still exists
        # (the flippers, the editor and the preview's amber card all read
        # it), it is just not painted as a blue bar - a click on any cell
        # opens that row's editor regardless, so the bar was saying little.
        th = self.colors
        bg = th["bg"]
        for i, row in enumerate(self._rows):
            for cell in row.cells:
                try:
                    cell.configure(bg=bg, fg=th["fg"], font=self.font)
                except tk.TclError:                     # pragma: no cover
                    pass
            last = len(self._rows) - 1
            for ic in row.icons:
                live = not (ic.kind == "up" and i == 0) and \
                    not (ic.kind == "down" and i >= last)
                ic.paint(self._icon_color(ic.kind, live), bg, live)
        if self._add_row is not None:
            for cell in self._add_row.cells:
                try:
                    cell.configure(bg=th["bg"], fg=th["gray"],
                                   font=self.font)
                except tk.TclError:                     # pragma: no cover
                    pass
            for ic in self._add_row.icons:
                ic.paint(th["success"], th["bg"], True)
        try:
            self.canvas.configure(bg=th["bg"])
            self.body.configure(bg=th["bg"])
        except tk.TclError:                             # pragma: no cover
            pass

    def _icon_color(self, kind, live):
        th = self.colors
        if not live:
            return th["gray"]
        # GREEN for the three that build the menu up and RED for the one
        # that takes an image off it - the log's own two hues for those two
        # meanings, so nothing has to be learned twice.
        return th["error"] if kind == "del" else th["success"]

    def apply_theme(self, colors=None):
        """Re-colour every row.  Called on a live dark/light switch: these
        are tk widgets carrying explicit colours, so no ttk style reaches
        them."""
        self.colors = dict(colors) if colors else self._palette()
        th = self.colors
        for child in self.head.winfo_children():
            try:
                child.configure(bg=th["bg"], fg=th["gray"])
            except tk.TclError:                         # a ttk spacer label
                pass
        self._repaint()
        return True

    # -- what a click means ---------------------------------------------

    def cell_clicked(self, i):
        """A CELL OPENS ITS IMAGE.  Every column does, because there is
        nothing else a row's text could be clicked for and a table that
        needs a double-click teaches nobody it has one (David: "it's hidden
        that double-clicking brings up the edit menu")."""
        if self._add_row is not None and i == len(self._rows):
            return self.add_clicked()
        if not (0 <= i < len(self._rows)):
            return None
        self.select(i)
        if self._on_activate:
            self._on_activate(i)
        return "break"

    def icon_clicked(self, i, kind):
        if kind == "add":
            return self.add_clicked()
        if not (0 <= i < len(self._rows)):
            return None
        self.select(i)
        if self._locked:            # a run is writing the card being edited
            return "break"
        if self._on_action:
            self._on_action(i, kind)
        return "break"

    def add_clicked(self):
        if self._locked:
            return "break"
        if self._on_add:
            self._on_add()
        return "break"

    def context(self, i, event=None):
        """A right-click on a row: select it and hand the owner the row and
        the pointer, to pop its own menu."""
        if 0 <= i < len(self._rows):
            self.select(i)
        row = i if 0 <= i < len(self._rows) else None
        if self._on_context:
            x, y = self._pointer(event)
            self._on_context(row, x, y)
        return "break"

    def _canvas_context(self, event=None):
        """A right-click on empty table space, or the menu key: no row."""
        if self._on_context:
            x, y = self._pointer(event)
            self._on_context(self.selected(), x, y)
        return "break"

    def _pointer(self, event):
        """Where to pop a menu: the event's own coordinates, or - for a
        keyboard opening that has none - just inside the table."""
        x = getattr(event, "x_root", None)
        y = getattr(event, "y_root", None)
        if x is None or y is None:
            try:
                x = self.canvas.winfo_rootx() + 20
                y = self.canvas.winfo_rooty() + 20
            except tk.TclError:                         # pragma: no cover
                x, y = 0, 0
        return int(x), int(y)

    def _key_activate(self, _event=None):
        i = self._sel
        if i is not None and self._on_activate and not self._locked:
            self._on_activate(i)
        return "break"

    def _key_step(self, delta):
        if not self._rows:
            return "break"
        cur = self._sel if self._sel is not None else 0
        self.select(max(0, min(len(self._rows) - 1, cur + delta)))
        return "break"

    def set_busy(self, busy):
        """While a run is writing the card being edited the icons must not
        act; the text still opens the editor, which is read-only enough."""
        self._locked = bool(busy)
        return self._locked
