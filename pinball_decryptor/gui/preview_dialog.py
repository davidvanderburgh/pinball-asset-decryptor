"""Settings > Preview features: paste a preview code, Unlock, see what is on.

A preview feature (the mode maker first) is in every copy of the app, switched off. A
code from the app's author switches it on for the person it names, until the date it
names (:mod:`..core.preview` checks the signature). This window is the whole of the
switch: a box to paste a code into, Unlock, the codes this copy holds with what each
turns on ("Mode maker: on for <name>, until <date>", or that it has expired), and Remove.

The codes live in settings.json (the App saves them through *set_codes*); what they
switch on is judged again when they change, and at every start-up.
"""
from __future__ import annotations

import tkinter as tk

from ..core import preview
from .placement import centered_over
from .theme import THEMES, dark_titlebar, platform_font

TITLE = "Preview features"

INTRO = ("Some features are tried out by a few people before everyone gets them. They "
         "are in every copy of the app, switched off. A preview code from the app's "
         "author switches one on in this copy, for the person it names and until the "
         "date it names.")


class PreviewFeaturesDialog:
    """The window. *get_codes()* returns the stored codes; *set_codes(codes)* saves a
    new list (and makes it this run's state). *today* and *public_keys* are for tests."""

    def __init__(self, parent, theme_name="light", get_codes=None, set_codes=None,
                 today=None, public_keys=None):
        self._get = get_codes or (lambda: [])
        self._set = set_codes or (lambda codes: None)
        self._today = today
        self._keys = public_keys
        self.rows = []
        theme = THEMES.get(theme_name) or THEMES["light"]
        self._theme = theme
        sans, _mono = platform_font()
        self.win = dlg = tk.Toplevel(parent)
        dlg.title(TITLE)
        dlg.configure(bg=theme["bg"])
        dark_titlebar(dlg, theme is THEMES["dark"])
        dlg.transient(parent)
        box = tk.Frame(dlg, bg=theme["bg"], padx=18, pady=14)
        box.pack(fill="both", expand=True)
        tk.Label(box, text=INTRO, wraplength=520, justify="left", anchor="w",
                 bg=theme["bg"], fg=theme["fg"], font=(sans, 10)).pack(fill="x")
        tk.Label(box, text="Paste a code:", anchor="w", bg=theme["bg"], fg=theme["fg"],
                 font=(sans, 10, "bold")).pack(fill="x", pady=(12, 2))
        self.entry = tk.Text(box, height=4, width=64, wrap="char", undo=True,
                             bg=theme["field_bg"], fg=theme["fg"],
                             insertbackground=theme["fg"], relief="flat",
                             highlightthickness=1, highlightbackground=theme["border"],
                             highlightcolor=theme["accent"], font=(sans, 9))
        self.entry.pack(fill="x")
        row = tk.Frame(box, bg=theme["bg"])
        row.pack(fill="x", pady=(6, 0))
        self.unlock_btn = self._button(row, "Unlock", self.unlock, primary=True)
        self.unlock_btn.pack(side="left")
        self.message = tk.StringVar(value="")
        self.message_lbl = tk.Label(row, textvariable=self.message, wraplength=420,
                                    justify="left", anchor="w", bg=theme["bg"],
                                    fg=theme["fg"], font=(sans, 9))
        self.message_lbl.pack(side="left", fill="x", expand=True, padx=(10, 0))
        tk.Label(box, text="In this copy of the app:", anchor="w", bg=theme["bg"],
                 fg=theme["fg"], font=(sans, 10, "bold")).pack(fill="x", pady=(14, 2))
        self.listbox = tk.Listbox(box, height=5, activestyle="none", exportselection=False,
                                  bg=theme["field_bg"], fg=theme["fg"],
                                  selectbackground=theme["select_bg"],
                                  selectforeground="#ffffff", relief="flat",
                                  highlightthickness=1, highlightbackground=theme["border"],
                                  font=(sans, 10))
        self.listbox.pack(fill="both", expand=True)
        bottom = tk.Frame(box, bg=theme["bg"])
        bottom.pack(fill="x", pady=(10, 0))
        self._button(bottom, "Close", self.close).pack(side="right")
        self.remove_btn = self._button(bottom, "Remove", self.remove_selected)
        self.remove_btn.pack(side="right", padx=(0, 8))
        dlg.bind("<Escape>", lambda _e: self.close())
        dlg.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        try:
            parent.update_idletasks()
            dlg.update_idletasks()
            w, h = max(dlg.winfo_reqwidth(), 600), max(dlg.winfo_reqheight(), 420)
            x, y = centered_over(parent, w, h)
            dlg.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except tk.TclError:
            pass
        self.entry.focus_set()

    # ---- widgets ----------------------------------------------------------------------
    def _button(self, parent, text, command, primary=False):
        t = self._theme
        bg = t["accent"] if primary else t["button"]
        fg = "#ffffff" if primary else t["fg"]
        hot = t["select_bg"] if primary else t["border"]
        sans, _mono = platform_font()
        lbl = tk.Label(parent, text=text, bg=bg, fg=fg, padx=16, pady=5, cursor="hand2",
                       font=(sans, 10, "bold" if primary else "normal"))
        lbl.bind("<Button-1>", lambda _e: command())
        lbl.bind("<Enter>", lambda _e: lbl.configure(bg=hot))
        lbl.bind("<Leave>", lambda _e: lbl.configure(bg=bg))
        return lbl

    def _say(self, text, ok):
        self.message.set(text)
        self.message_lbl.configure(fg=self._theme["success" if ok else "error"])

    # ---- what it does -------------------------------------------------------------------
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def lift(self):
        try:
            self.win.deiconify()
            self.win.lift()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    def refresh(self):
        """List the stored codes, each as the lines :func:`preview.describe` gives."""
        _active, self.rows = preview.judge(self._get(), self._today, self._keys)
        self.listbox.delete(0, tk.END)
        self._row_of_line = []
        for i, st in enumerate(self.rows):
            for line in st.lines:
                self.listbox.insert(tk.END, line)
                self._row_of_line.append(i)
        if not self.rows:
            self.listbox.insert(tk.END, "No preview features are switched on.")
            self._row_of_line.append(None)

    def unlock(self, text=None):
        """Check the pasted code (or *text*) and keep it. Returns True when it switched
        something on."""
        if text is None:
            text = self.entry.get("1.0", tk.END)
        try:
            codes, grant = preview.add_code(self._get(), text, self._today, self._keys)
        except preview.PreviewCodeError as e:
            self._say(str(e), False)
            return False
        self._set(codes)
        self.entry.delete("1.0", tk.END)
        self.refresh()
        self._say("Unlocked. " + "; ".join(preview.describe(grant, self._today)) + ".", True)
        return True

    def remove_selected(self, index=None):
        """Remove the selected code (or the one on list line *index*). Returns True when
        a code was removed."""
        if index is None:
            sel = self.listbox.curselection()
            if not sel:
                self._say("Pick a code in the list first, then Remove.", False)
                return False
            index = sel[0]
        row = self._row_of_line[index] if 0 <= index < len(self._row_of_line) else None
        if row is None:
            return False
        st = self.rows[row]
        self._set(preview.remove_code(self._get(), st.code))
        self.refresh()
        who = st.grant.name if st.grant else "a code that did not check out"
        self._say("Removed the code for %s." % who, True)
        return True
