"""Modes tab - make a game mode of your own, as part of the card project (item 127).

WHAT A MODE IS HERE. A folder in the project, ``<project>/modes/<name>/``, holding
``mode.json`` and the mode's own art, clip and sound (:mod:`..plugins.stern.mode_project`).
The person picks shots BY NAME, colours and titles; nothing on this tab is a hex mask, a
message id or a raw light command (those hide under Advanced). The file ``mode.so``
reads is generated from it at build time, with the names of the screen and clip the
build adds (:mod:`..plugins.stern.mode_assets`).

HOW IT SAVES. Like the Defaults tab: every change saves itself about half a second after
you stop typing. A mode belongs to the project and reaches a card through Write
(David, 2026-09-16), so there is no Save button to forget.

WHY ITS OWN TAB, AND WHERE. A mode runs on a preloaded object built for Spike 2, so the
tab has its own ``modes`` capability. It sits after Defaults and before Write: a mode is
one more change a card build applies.
"""

import os
import shutil
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from ..plugins.stern import mode_assets as MA
from ..plugins.stern import mode_project as MP
# item 127, Try it
import subprocess
import sys
from tkinter import simpledialog

from ..plugins.stern import mode_runtime as MR
from ..plugins.stern import mode_tryit as MT
from .theme import THEMES
from .widgets import _Tooltip

SAVE_DELAY_MS = 500


class ModesPanel:
    """The Modes tab's widgets over the project's modes."""

    LOG_TAG = "[modes] "

    ABOUT_TIP = (
        "Make a game mode of your own: what starts it, how long it runs, which shots "
        "score, and what the display, lights and speakers do while it runs. Modes are "
        "saved in this project and put on the card by Write, like the other tabs' "
        "changes. A card holds up to %d modes; one runs at a time." % MP.MAX_MODES)

    def __init__(self, parent, log=None, theme_fn=None, badge_fn=None, resize_fn=None,
                 project_fn=None, emulate_fn=None, **_ignored):
        self._parent = parent
        self._log = log
        self._theme_fn = theme_fn or (lambda: "dark")
        self._badge_fn = badge_fn
        self._resize_fn = resize_fn
        #: The project folder, asked each time (the Extract tab can change it).
        self._project_fn = project_fn or (lambda: "")
        self._emulate_fn = emulate_fn
        self._slugs = []              # list order -> slug
        self._slug = None             # the mode in the form
        self._spec = None
        #: The project the open mode came from. Saves go HERE, not to whatever the
        #: project is now: when the Extract tab switches projects, the edit in flight
        #: belongs to the old one.
        self._open_project = ""
        self._loading = False         # True while the form is being filled
        self._save_job = None
        self._widget = None           # any built widget, for after()
        self._preview_img = None
        self.v = {}
        self._init_tryit(_ignored)
        #: item 145: told when this tab stages an adjustment in the project's Defaults
        #: settings, so the Defaults form (whose autostage replaces them) adopts it
        self._settings_staged_fn = _ignored.get("settings_staged_fn")

    # ---- the project -------------------------------------------------------------
    def project(self):
        p = (self._project_fn() or "").strip()
        return p if p and os.path.isdir(p) else ""

    def _say(self, text):
        if not self._log:
            return
        msg = self.LOG_TAG + text
        pending = self._say_pending
        if threading.current_thread() is threading.main_thread() or self._widget is None:
            while pending:                      # what a worker said first, in order
                self._log(pending.pop(0))
            self._log(msg)
            return
        # FROM A WORKER (Try it's preparation runs on the Emulate tab's start worker, the
        # rig commands on threads of the tab's own): the app's log is a Tk Text widget, and
        # Tk may only be touched from the main loop (EmulatePanel._log's rule). QUEUED, and
        # written by the main loop's _tryit_watch, which runs while that work does - not
        # after(), which from a worker stalls a second and raises unless a mainloop() is
        # dispatching
        pending.append(msg)
        if not self._tryit_watches:
            # nobody is watching (a worker this tab did not start): ask the main loop
            try:
                self._widget.winfo_toplevel().after(0, self._tryit_flush)
            except (tk.TclError, RuntimeError):
                pass

    # ---- build ------------------------------------------------------------------------
    def build(self, frame):
        self._widget = frame
        top = ttk.Frame(frame)
        top.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(top, text="Modes in this project:").pack(side=tk.LEFT)
        if self._badge_fn is not None:
            badge = self._badge_fn(top, "i", "#2f80ed", "#5296f2", self.ABOUT_TIP, lambda: None,
                                   size=18, font=("Georgia", 10, "bold italic"),
                                   tooltip_place="side")
            badge.pack(side=tk.LEFT, padx=(8, 0))
            badge.bind("<Button-1>", lambda _e: badge.icon_tip.show(), add="+")
        self._project_label = ttk.Label(top, text="", anchor=tk.W)
        self._project_label.pack(side=tk.LEFT, padx=(12, 0), fill=tk.X, expand=True)
        self._build_title_section(frame)

        body = ttk.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # the list of modes
        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        # a plain Tk listbox takes no ttk style, so it is coloured by hand like the
        # combobox drop-downs are (David, 2026-09-16: the dark theme was barely legible)
        th = THEMES.get(self._theme_fn(), THEMES["dark"])
        self._list = tk.Listbox(left, height=8, width=24, exportselection=False,
                                activestyle="none", bg=th["field_bg"], fg=th["fg"],
                                selectbackground=th["select_bg"], selectforeground="#ffffff",
                                highlightthickness=1, highlightbackground=th["border"],
                                highlightcolor=th["accent"], relief=tk.FLAT)
        self._list.pack(fill=tk.Y, expand=True)
        self._list.bind("<<ListboxSelect>>", lambda _e: self._on_select())
        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(6, 0))
        self._new_btn = ttk.Button(btns, text="New", command=self._on_new, width=6)
        self._new_btn.pack(side=tk.LEFT)
        # ready-made modes, KAIJU RUSH first - the one that ran on a machine
        self._ex_btn = ttk.Menubutton(btns, text="Examples", width=9)
        menu = self._ex_menu = tk.Menu(self._ex_btn, tearoff=0)
        for name, _spec in MP.example_specs():
            menu.add_command(label=name, command=lambda n=name: self._on_example(n))
        self._add_code_examples(menu)
        self._ex_btn.configure(menu=menu)
        self._ex_btn.pack(side=tk.LEFT, padx=(4, 0))
        btns2 = ttk.Frame(left)
        btns2.pack(fill=tk.X, pady=(4, 0))
        self._dup_btn = ttk.Button(btns2, text="Duplicate", command=self._on_duplicate, width=9)
        self._dup_btn.pack(side=tk.LEFT)
        self._del_btn = ttk.Button(btns2, text="Delete", command=self._on_delete, width=7)
        self._del_btn.pack(side=tk.LEFT, padx=(4, 0))

        # the editor, two columns of sections
        self._editor = ttk.Frame(body)
        self._editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        col_a = ttk.Frame(self._editor)
        col_a.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        col_b = ttk.Frame(self._editor)
        col_b.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._build_mode_section(col_a)
        self._build_shots_section(col_a)
        self._build_lights_section(col_a)
        self._build_display_lights_section(col_a)
        self._build_starts_section(col_a)
        self._build_stacking_section(col_a)
        self._build_advanced_section(col_a)
        self._build_trigger_section(col_a)
        self._build_screen_section(col_b)
        self._build_clip_section(col_b)
        self._build_sound_section(col_b)
        self._build_own_sounds_section(col_b)
        self._build_film_section(col_b)
        self._build_tryit_section(frame)
        self._build_code_modes_section(frame)
        self._build_stock_modes_section(frame)

        self._status = ttk.Label(frame, text="", wraplength=900, justify=tk.LEFT)
        self._status.pack(fill=tk.X, padx=10, pady=(4, 10))
        self.refresh()

    def _var(self, key, kind=tk.StringVar, value=""):
        var = kind(value=value)
        var.trace_add("write", lambda *_a: self._changed())
        self.v[key] = var
        return var

    def _tip(self, widget, text):
        _Tooltip(widget, text, self._theme_fn)

    def _row(self, parent, label, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)

    def _build_mode_section(self, parent):
        box = ttk.LabelFrame(parent, text=" Mode ")
        box.pack(fill=tk.X, pady=(0, 6))
        box.columnconfigure(1, weight=1)
        self._row(box, "Name", 0)
        e = ttk.Entry(box, textvariable=self._var("name"))
        e.grid(row=0, column=1, columnspan=3, sticky=tk.EW, padx=6, pady=2)
        self._tip(e, "What the mode is called. It is the title on its screen and clip "
                     "unless you give those their own.")
        self._row(box, "Starts on", 1)
        shots = [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
        c = self._start_combo = ttk.Combobox(box, state="readonly", values=shots, width=18,
                         textvariable=self._var("start_shot"))
        c.grid(row=1, column=1, sticky=tk.W, padx=6, pady=2)
        self._tip(c, "The shot that starts the mode.")
        s = ttk.Spinbox(box, from_=1, to=20, width=4, textvariable=self._var("start_count"))
        s.grid(row=1, column=2, sticky=tk.W, pady=2)
        ttk.Label(box, text="times in one ball").grid(row=1, column=3, sticky=tk.W, padx=(4, 6))
        self._row(box, "Runs for", 2)
        s = ttk.Spinbox(box, from_=1, to=300, width=6, textvariable=self._var("seconds"))
        s.grid(row=2, column=1, sticky=tk.W, padx=6, pady=2)
        ttk.Label(box, text="seconds").grid(row=2, column=2, columnspan=2, sticky=tk.W)
        self._row(box, "First shot pays", 3)
        e = ttk.Entry(box, width=14, textvariable=self._var("award"))
        e.grid(row=3, column=1, sticky=tk.W, padx=6, pady=2)
        self._tip(e, "Points for the first scoring shot. The second pays twice this, the "
                     "third three times, and so on. The game's own scoring is used, so its "
                     "playfield multiplier applies. Advanced can change this: Award ladder "
                     "Fixed pays every shot once, and Points per shot gives a shot its own "
                     "points.")

    def _build_shots_section(self, parent):
        box = self._shots_box = ttk.LabelFrame(parent, text=" Shots that score while it runs ")
        box.pack(fill=tk.X, pady=(0, 6))
        self._shot_vars = {}
        for i, (name, _mask) in enumerate(MP.GODZILLA_PRO_1_15.shots):
            var = tk.BooleanVar(value=False)
            var.trace_add("write", lambda *_a: self._changed())
            self._shot_vars[name] = var
            ttk.Checkbutton(box, text=name, variable=var).grid(
                row=i // 2, column=i % 2, sticky=tk.W, padx=6, pady=1)

    def _color_button(self, parent, key, title):
        var = self._var(key, value="#000000")
        btn = tk.Button(parent, width=3, relief=tk.GROOVE, bd=1,
                        command=lambda: self._pick_color(key, title))
        self._swatches = getattr(self, "_swatches", {})
        self._swatches[key] = btn
        var.trace_add("write", lambda *_a: self._paint_swatch(key))
        return btn

    def _paint_swatch(self, key):
        value = self.v[key].get()
        if len(value) == 7 and value.startswith("#"):
            try:
                self._swatches[key].configure(bg=value, activebackground=value)
            except tk.TclError:
                pass

    def _pick_color(self, key, title):
        rgb = colorchooser.askcolor(color=self.v[key].get() or "#000000", title=title,
                                    parent=self._widget)
        if rgb and rgb[1]:
            self.v[key].set(rgb[1])

    def _build_lights_section(self, parent):
        box = self._lights_box = ttk.LabelFrame(parent, text=" Lights ")
        box.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(box, text="Sweep the playfield in a colour while it runs",
                        variable=self._var("lights", tk.BooleanVar, False)).grid(
            row=0, column=0, columnspan=3, sticky=tk.W, padx=6)
        ttk.Label(box, text="Colour").grid(row=1, column=0, sticky=tk.W, padx=6)
        self._color_button(box, "light_color", "Light colour").grid(row=1, column=1, sticky=tk.W)
        adv = ttk.Checkbutton(box, text="Advanced", variable=self._var("advanced", tk.BooleanVar, False),
                              command=self._show_advanced)
        adv.grid(row=1, column=2, sticky=tk.W, padx=12)
        self._adv = ttk.Frame(box)
        ttk.Label(self._adv, text="On command").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(self._adv, width=40, textvariable=self._var("light_on_raw")).grid(
            row=0, column=1, sticky=tk.EW, padx=4, pady=1)
        ttk.Label(self._adv, text="Off command").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(self._adv, width=40, textvariable=self._var("light_off_raw")).grid(
            row=1, column=1, sticky=tk.EW, padx=4, pady=1)
        self._tip(adv, "Replace the colour sweep with light commands of your own, in the "
                       "game's own light language (blele ...). Leave both empty to use the "
                       "colour above.")

    def _show_advanced(self):
        if self.v["advanced"].get():
            self._adv.grid(row=2, column=0, columnspan=3, sticky=tk.EW, padx=6, pady=(2, 4))
        else:
            self._adv.grid_remove()
        if self._resize_fn:
            self._resize_fn()

    # ---- item 147: what starts it and what ends it -------------------------------------
    def _event_choices(self):
        """(label, name) for every event the title's port carries, in the profile's order."""
        return [(MP.EVENT_LABELS.get(n, n), n) for n in MP.GODZILLA_PRO_1_15.events]

    def _build_trigger_section(self, parent):
        box = ttk.LabelFrame(parent, text=" Starts and ends ")
        box.pack(fill=tk.X, pady=(0, 6))
        box.columnconfigure(2, weight=1)
        labels = [label for label, _n in self._event_choices()]
        ttk.Label(box, text="Starts on").grid(row=0, column=0, sticky=tk.W, padx=6, pady=2)
        starts = self._var("starts_kind", value="shot")
        r = ttk.Radiobutton(box, text="Its shot (above)", value="shot", variable=starts)
        r.grid(row=0, column=1, columnspan=2, sticky=tk.W, pady=2)
        self._tip(r, "The mode starts when its shot is made that many times in one ball.")
        ttk.Radiobutton(box, text="An event", value="event", variable=starts).grid(
            row=1, column=1, sticky=tk.W, pady=2)
        c = ttk.Combobox(box, state="readonly", values=labels, width=26,
                         textvariable=self._var("start_event"))
        c.grid(row=1, column=2, sticky=tk.W, padx=6, pady=2)
        self._tip(c, "Something the game itself does: a ball starting, a multiball starting, "
                     "the skill shot being made. The mode starts the moment the game does it.")
        ttk.Label(box, text="Ends on").grid(row=2, column=0, sticky=tk.W, padx=6, pady=2)
        ends = self._var("ends_kind", value="drain")
        r = ttk.Radiobutton(box, text="Its clock, or the ball draining", value="drain", variable=ends)
        r.grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=2)
        self._tip(r, "The mode ends when its time runs out, or sooner if the ball drains.")
        r = ttk.Radiobutton(box, text="Its clock only", value="clock", variable=ends)
        r.grid(row=3, column=1, columnspan=2, sticky=tk.W, pady=2)
        self._tip(r, "The mode keeps running into the next ball until its time runs out.")
        ttk.Radiobutton(box, text="An event", value="event", variable=ends).grid(
            row=4, column=1, sticky=tk.W, pady=2)
        c = ttk.Combobox(box, state="readonly", values=labels, width=26,
                         textvariable=self._var("end_event"))
        c.grid(row=4, column=2, sticky=tk.W, padx=6, pady=2)
        self._tip(c, "The mode ends when the game does this, when its time runs out, or when "
                     "the ball drains, whichever comes first.")

    def _open_trigger(self, spec):
        by_name = {n: label for label, n in self._event_choices()}
        start = MP.starts_on_event(spec)
        self.v["starts_kind"].set("event" if start else "shot")
        self.v["start_event"].set(by_name.get(start, start or ""))
        kind, name = MP.ends_on_parts(spec)
        self.v["ends_kind"].set(kind if kind in ("drain", "clock", "event") else "drain")
        self.v["end_event"].set(by_name.get(name, name or ""))

    def _collect_trigger(self, spec):
        by_label = {label: n for label, n in self._event_choices()}

        def name_of(key):
            value = self.v[key].get().strip()
            return by_label.get(value, value)

        if self.v["starts_kind"].get() == "event":
            spec.starts_on = ("event %s" % name_of("start_event")).strip()
        else:
            spec.starts_on = "shot"
        kind = self.v["ends_kind"].get()
        spec.ends_on = ("event %s" % name_of("end_event")).strip() if kind == "event" else (kind or "drain")

    def _build_screen_section(self, parent):
        box = self._screen_box = ttk.LabelFrame(parent, text=" Screen ")
        box.pack(fill=tk.X, pady=(0, 6))
        box.columnconfigure(1, weight=1)
        ttk.Checkbutton(box, text="Show a screen of its own while it runs",
                        variable=self._var("screen", tk.BooleanVar, True)).grid(
            row=0, column=0, columnspan=4, sticky=tk.W, padx=6)
        self._row(box, "Title", 1)
        e = ttk.Entry(box, textvariable=self._var("screen_title"))
        e.grid(row=1, column=1, columnspan=3, sticky=tk.EW, padx=6, pady=2)
        self._tip(e, "The title on the panel. Empty uses the mode's name. Under it, the "
                     "mode writes what each shot paid, and the total at the end.")
        self._row(box, "Picture", 2)
        art = self._var("art_mode", value="panel")
        ttk.Radiobutton(box, text="A panel in these colours", value="panel", variable=art).grid(
            row=2, column=1, sticky=tk.W, padx=6)
        ttk.Radiobutton(box, text="My picture…", value="file", variable=art,
                        command=self._choose_art).grid(row=2, column=2, sticky=tk.W)
        colors = ttk.Frame(box)
        colors.grid(row=3, column=1, columnspan=3, sticky=tk.W, padx=6, pady=2)
        ttk.Label(colors, text="Panel").pack(side=tk.LEFT)
        self._color_button(colors, "panel_color", "Panel colour").pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(colors, text="Title").pack(side=tk.LEFT)
        self._color_button(colors, "title_color", "Title colour").pack(side=tk.LEFT, padx=4)
        self._art_label = ttk.Label(box, text="")
        self._art_label.grid(row=4, column=1, columnspan=3, sticky=tk.W, padx=6)
        self._preview = ttk.Label(box)
        self._preview.grid(row=5, column=0, columnspan=4, pady=(4, 4))

    def _build_clip_section(self, parent):
        box = self._clip_box = ttk.LabelFrame(parent, text=" Clip ")
        box.pack(fill=tk.X, pady=(0, 6))
        box.columnconfigure(1, weight=1)
        clip = self._var("clip", value="none")
        r = ttk.Frame(box)
        r.grid(row=0, column=0, columnspan=4, sticky=tk.W, padx=6)
        ttk.Radiobutton(r, text="None", value="none", variable=clip).pack(side=tk.LEFT)
        ttk.Radiobutton(r, text="A title card", value="title", variable=clip).pack(side=tk.LEFT, padx=8)
        ttk.Radiobutton(r, text="My video…", value="file", variable=clip,
                        command=self._choose_clip).pack(side=tk.LEFT)
        self._row(box, "Card title", 1)
        e = ttk.Entry(box, textvariable=self._var("clip_title"))
        e.grid(row=1, column=1, sticky=tk.EW, padx=6, pady=2)
        self._tip(e, "The title card's words, over the panel colour with a sweep in the "
                     "title colour. Empty uses the mode's name.")
        ttk.Spinbox(box, from_=1, to=30, width=4, textvariable=self._var("clip_seconds")).grid(
            row=1, column=2, sticky=tk.W)
        ttk.Label(box, text="seconds").grid(row=1, column=3, sticky=tk.W, padx=(4, 6))
        self._clip_label = ttk.Label(box, text="")
        self._clip_label.grid(row=2, column=1, columnspan=3, sticky=tk.W, padx=6)
        self._row(box, "Plays", 3)
        when = self._var("clip_when", value="start")
        w = ttk.Frame(box)
        w.grid(row=3, column=1, columnspan=3, sticky=tk.W, padx=6)
        ttk.Radiobutton(w, text="When it starts", value="start", variable=when).pack(side=tk.LEFT)
        ttk.Radiobutton(w, text="When it ends", value="end", variable=when).pack(side=tk.LEFT, padx=8)

    def _build_sound_section(self, parent):
        box = self._sound_box = ttk.LabelFrame(parent, text=" Sound ")
        box.pack(fill=tk.X, pady=(0, 6))
        self._countdown_chk = ttk.Checkbutton(box, text="Count down the last seconds in the game's own voice",
                                              variable=self._var("countdown", tk.BooleanVar, True))
        self._countdown_chk.grid(
            row=0, column=0, columnspan=3, sticky=tk.W, padx=6)
        end = self._var("end_mode", value="game")
        ttk.Label(box, text="When time is up").grid(row=1, column=0, sticky=tk.W, padx=6)
        ttk.Radiobutton(box, text="The game's own call", value="game", variable=end).grid(
            row=1, column=1, sticky=tk.W)
        self._own_sound_radio = ttk.Radiobutton(box, text="My sound…", value="file", variable=end,
                                                command=self._choose_sound)
        self._own_sound_radio.grid(row=1, column=2, sticky=tk.W, padx=8)
        self._sound_label = ttk.Label(box, text="")
        self._sound_label.grid(row=2, column=1, columnspan=2, sticky=tk.W)

    # ---- a mode's own sounds (item 150) ------------------------------------------------
    #: (spec field, radio variable, the label under it, file stem in the mode folder, words)
    _OWN_SOUNDS = (("sound_start", "start_sound_mode", "When it starts", "start"),
                   ("sound_shot", "shot_sound_mode", "On a scoring shot", "shot"),
                   ("music", "music_mode", "Music underneath", "music"))

    def _build_own_sounds_section(self, parent):
        box = ttk.LabelFrame(parent, text=" Sounds of its own ")
        box.pack(fill=tk.X, pady=(0, 6))
        self._own_sound_labels = {}
        row = 0
        for attr, mode_var, words, _stem in self._OWN_SOUNDS:
            var = self._var(mode_var, value="none")
            ttk.Label(box, text=words).grid(row=row, column=0, sticky=tk.W, padx=6)
            ttk.Radiobutton(box, text="Nothing", value="none", variable=var).grid(row=row, column=1, sticky=tk.W)
            ttk.Radiobutton(box, text="My sound…", value="file", variable=var,
                            command=lambda a=attr: self._choose_own_sound(a)).grid(
                row=row, column=2, sticky=tk.W, padx=8)
            label = ttk.Label(box, text="")
            label.grid(row=row + 1, column=1, columnspan=3, sticky=tk.W)
            self._own_sound_labels[attr] = label
            row += 2
            if attr == "sound_shot":
                every = ttk.Frame(box)
                every.grid(row=row, column=1, columnspan=3, sticky=tk.W)
                ttk.Label(every, text="on every").pack(side=tk.LEFT)
                ttk.Spinbox(every, from_=1, to=20, width=4,
                            textvariable=self._var("sound_shot_every", value="1")).pack(side=tk.LEFT, padx=4)
                ttk.Label(every, text="scoring shot(s)").pack(side=tk.LEFT)
                row += 1
        note = ttk.Label(box, text="Each plays in place of a stock call the game never makes. "
                                   "Write puts them on the card, and names any it cannot carry.",
                         wraplength=380)
        note.grid(row=row, column=0, columnspan=4, sticky=tk.W, padx=6, pady=(2, 4))
        self._own_sounds_note = note

    def _open_own_sounds(self, spec):
        for attr, mode_var, _words, _stem in self._OWN_SOUNDS:
            self.v[mode_var].set("file" if getattr(spec, attr) else "none")
        self.v["sound_shot_every"].set(str(max(1, int(spec.sound_shot_every or 1))))

    def _collect_own_sounds(self, spec):
        for attr, mode_var, _words, _stem in self._OWN_SOUNDS:
            if self.v[mode_var].get() != "file":
                setattr(spec, attr, "")
        try:
            spec.sound_shot_every = int(self.v["sound_shot_every"].get().strip())
        except ValueError:
            spec.sound_shot_every = 0

    def _own_sounds_labels(self, spec):
        for attr, _mode_var, _words, _stem in self._OWN_SOUNDS:
            name = getattr(spec, attr)
            self._own_sound_labels[attr].configure(text=name and "Sound: %s" % name or "")

    def _choose_own_sound(self, attr):
        for a, mode_var, words, stem in self._OWN_SOUNDS:
            if a == attr:
                self._choose("Choose the sound: %s" % words.lower(), [("WAV sounds", "*.wav")],
                             stem, attr, mode_var, "none")

    # ---- how often it can start (item 139) ----------------------------------------------
    def _build_starts_section(self, parent):
        box = ttk.LabelFrame(parent, text=" How often it can start ")
        box.pack(fill=tk.X, pady=(0, 6))
        policy = self._var("starts_policy", value="unlimited")
        ttk.Radiobutton(box, text="Once a game", value="once_per_game", variable=policy).grid(
            row=0, column=0, sticky=tk.W, padx=6)
        ttk.Radiobutton(box, text="Once a ball", value="once_per_ball", variable=policy).grid(
            row=0, column=1, sticky=tk.W, padx=6)
        ttk.Radiobutton(box, text="Any number of times", value="unlimited", variable=policy).grid(
            row=1, column=0, sticky=tk.W, padx=6)
        up = ttk.Frame(box)
        up.grid(row=1, column=1, sticky=tk.W, padx=6)
        ttk.Radiobutton(up, text="Up to", value="count", variable=policy).pack(side=tk.LEFT)
        ttk.Spinbox(up, from_=1, to=MP.STARTS_MAX, width=4,
                    textvariable=self._var("starts_count", value="2")).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(up, text="times a game").pack(side=tk.LEFT)
        wait = ttk.Frame(box)
        wait.grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=6, pady=(4, 0))
        ttk.Label(wait, text="Wait").pack(side=tk.LEFT)
        s = ttk.Spinbox(wait, from_=0, to=MP.COOLDOWN_MAX, width=5,
                        textvariable=self._var("cooldown", value="0"))
        s.pack(side=tk.LEFT, padx=4)
        ttk.Label(wait, text="seconds after it ends before it can start again").pack(side=tk.LEFT)
        self._tip(s, "0 = no wait. The wait runs from the moment the mode ends, and carries "
                     "on through the end of a ball.")
        self._starts_words = ttk.Label(box, text="", wraplength=380, justify=tk.LEFT)
        self._starts_words.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=(2, 4))
        self._tip(box, "Counted for each player. Once a ball starts again on the player's next "
                       "ball; once a game, and up to N times, start again in the next game.")
        for key in ("starts_policy", "starts_count", "cooldown"):
            self.v[key].trace_add("write", lambda *_a: self._show_starts_words())
        self._show_starts_words()

    def _form_starts(self):
        """``(starts, cooldown)`` as the form has them: a number, a policy name, or the
        text typed when it is not a number (so validate() can say what is wrong)."""
        policy = self.v["starts_policy"].get()
        if policy == "count":
            text = self.v["starts_count"].get().strip()
            starts = int(text) if text.isdigit() else text
        else:
            starts = policy
        text = self.v["cooldown"].get().strip()
        cooldown = int(text) if text.isdigit() else (text or 0)
        return starts, cooldown

    def _show_starts_words(self):
        starts, cooldown = self._form_starts()
        self._starts_words.configure(text=MP.starts_words(MP.ModeSpec(starts=starts, cooldown=cooldown)))

    def _open_starts(self, spec):
        starts = spec.starts
        if isinstance(starts, int) and not isinstance(starts, bool):
            self.v["starts_policy"].set("count")
            self.v["starts_count"].set(str(starts))
        else:
            self.v["starts_policy"].set(starts if starts in MP.STARTS_POLICIES else "unlimited")
        self.v["cooldown"].set(str(spec.cooldown))

    def _collect_starts(self, spec):
        spec.starts, spec.cooldown = self._form_starts()

    # ---- stacking with the game's own modes (item 140) ------------------------------
    def _build_stacking_section(self, parent):
        box = ttk.LabelFrame(parent, text=" The game's own modes ")
        box.pack(fill=tk.X, pady=(0, 6))
        c = ttk.Checkbutton(box, text="Can run during the game's own modes",
                            variable=self._var("stack", tk.BooleanVar, True))
        c.grid(row=0, column=0, sticky=tk.W, padx=6)
        self._tip(c, "On: the mode starts whenever its shot is made, even during one of the "
                     "game's own battles or multiballs. Off: it waits until the game's own "
                     "battle or multiball ends, and the next start shot after that starts it.")

    def _open_stacking(self, spec):
        self.v["stack"].set(bool(getattr(spec, "stack", True)))

    def _collect_stacking(self, spec):
        spec.stack = bool(self.v["stack"].get())

    # ---- the lit shots and the display priority (item 157) ------------------------------
    #: the patterns the lit shots can take, as the form names them
    _LIGHT_PATTERN_WORDS = (("solid", "Solid"), ("blink", "Blink"), ("pulse", "Pulse"), ("chase", "Chase"))

    def _build_display_lights_section(self, parent):
        box = self._display_lights_box = ttk.LabelFrame(parent, text=" On the playfield and the screen ")
        box.pack(fill=tk.X, pady=(0, 6))
        lit = ttk.Checkbutton(box, text="Light the shots that score",
                              variable=self._var("light_shots_on", tk.BooleanVar, False))
        lit.grid(row=0, column=0, sticky=tk.W, padx=6)
        self._color_button(box, "light_shots_color", "Colour of the lit shots").grid(row=0, column=1, sticky=tk.W)
        pattern = ttk.Combobox(box, state="readonly", width=7,
                               values=[w for _k, w in self._LIGHT_PATTERN_WORDS],
                               textvariable=self._var("light_shots_pattern", value="Blink"))
        pattern.grid(row=0, column=2, sticky=tk.W, padx=(6, 6))
        self._tip(lit, "While the mode runs, the insert in front of every shot that scores (and every "
                       "shot with its own points) shows this colour and pattern, over the game's own "
                       "light shows; every other insert keeps doing what the game wants. They go back "
                       "to the game the moment the mode ends. Blink and Pulse repeat about twice a "
                       "second and every 1.6 s; Chase lights one of them at a time. Godzilla's ports "
                       "name the inserts; on a title whose port does not, nothing is lit.")
        ttk.Label(box, text="Display priority").grid(row=1, column=0, sticky=tk.W, padx=6, pady=(2, 4))
        prio = ttk.Spinbox(box, from_=0, to=255, width=5, textvariable=self._var("priority", value="0"))
        prio.grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=(2, 4))
        ttk.Label(box, text="0 = none, %d = over the game's shot awards" % MP.DISPLAY_PRIORITY_MODE).grid(
            row=2, column=0, columnspan=3, sticky=tk.W, padx=6, pady=(0, 4))
        self._tip(prio, "How the mode's screen and clip sit among the game's own displays while it runs, "
                        "on the game's own scale (1-255). At 180 the game's full-screen shot awards "
                        "(LOOPS) and BATTLE IS LIT wait until the mode ends; its jackpots, multiball "
                        "and battle starts and the tilt warning still come through, and the mode's "
                        "screen is back when they end. Higher holds more back (190: starts and "
                        "jackpots wait too). 0 leaves the game's display order as it is.")

    def _open_display_lights(self, spec):
        colour = spec.light_shots if isinstance(spec.light_shots, str) else ""
        self.v["light_shots_on"].set(bool(colour))
        self.v["light_shots_color"].set(colour or "#ff6000")
        words = dict(self._LIGHT_PATTERN_WORDS)
        self.v["light_shots_pattern"].set(words.get(spec.light_shots_pattern, spec.light_shots_pattern))
        self.v["priority"].set(str(spec.priority))

    def _collect_display_lights(self, spec):
        keys = {w: k for k, w in self._LIGHT_PATTERN_WORDS}
        spec.light_shots = self.v["light_shots_color"].get() if self.v["light_shots_on"].get() else ""
        shown = self.v["light_shots_pattern"].get()
        spec.light_shots_pattern = keys.get(shown, shown)
        text = self.v["priority"].get().strip()
        spec.priority = int(text) if text.isdigit() else (text or 0)

    # ---- the list ------------------------------------------------------------------
    def refresh(self, select=None):
        """Re-read the project's modes into the list, keeping (or choosing) a selection."""
        project = self.project()
        if self._slug is not None and project != self._open_project:
            self._save_if_edited()              # finish the old project's edit first
            self._slug, self._spec = None, None
        self._project_label.configure(
            text=("Saved in %s" % os.path.join(project, MP.MODES_DIRNAME)) if project
            else "Open or extract a card project first (Extract tab) - modes are saved in it.")
        found, broken = MP.list_modes(project) if project else ([], [])
        self._refresh_code_modes(project)
        self._slugs = [s for s, _ in found]
        self._list.delete(0, tk.END)
        for _slug, spec in found:
            self._list.insert(tk.END, spec.name)
        for slug, err in broken:
            self._say("could not read the mode in %s: %s" % (slug, err))
        state = tk.NORMAL if project and len(found) < MP.MAX_MODES else tk.DISABLED
        self._new_btn.configure(state=state)
        self._ex_btn.configure(state=state)
        self._apply_project_title(project)
        want = select if select in self._slugs else (self._slug if self._slug in self._slugs else None)
        if want is None and self._slugs:
            want = self._slugs[0]
        if want is None:
            self._slug, self._spec = None, None
            self._blank_form()
            self._set_editor_state(False)
            self._status.configure(text="" if not project else
                                   "No modes yet. Press New for a blank mode, or pick one under "
                                   "Examples - KAIJU RUSH is the one that has run on a machine.")
            self._note_no_port_in_status()
            return
        i = self._slugs.index(want)
        self._list.selection_clear(0, tk.END)
        self._list.selection_set(i)
        self._open(want, dict(found)[want])

    #: what an empty editor greys out: the widgets a person types in or clicks. Labels
    #: and frames are left alone - a disabled ttk.Label in the dark theme draws its
    #: text in the disabled grey against the dark panel, and that is what made the whole
    #: form "barely legible" with no mode open (David, 2026-09-16).
    _INTERACTIVE = (ttk.Entry, ttk.Checkbutton, ttk.Radiobutton, ttk.Button, tk.Button)

    def _set_editor_state(self, on):
        for btn in (self._dup_btn, self._del_btn):
            btn.configure(state=tk.NORMAL if on else tk.DISABLED)

        def walk(w):
            for child in w.winfo_children():
                if isinstance(child, self._INTERACTIVE):      # Combobox and Spinbox are Entries
                    enabled = "readonly" if isinstance(child, ttk.Combobox) else tk.NORMAL
                    try:
                        child.configure(state=enabled if on else tk.DISABLED)
                    except tk.TclError:
                        pass
                walk(child)
        walk(self._editor)
        self._grey_what_the_title_cannot(on)

    def _on_select(self):
        sel = self._list.curselection()
        if not sel or sel[0] >= len(self._slugs):
            return
        slug = self._slugs[sel[0]]
        if slug == self._slug:
            return
        self._save_if_edited()
        found = dict(MP.list_modes(self.project())[0])
        if slug in found:
            self._open(slug, found[slug])

    # ---- the form <-> the spec ----------------------------------------------------
    def _open(self, slug, spec):
        spec = self._retarget_for_title(spec)
        self._slug, self._spec = slug, spec
        self._open_project = self.project()
        self._loading = True
        try:
            for key in ("name", "start_shot", "screen_title", "panel_color", "title_color",
                        "clip", "clip_title", "clip_when", "light_color", "light_on_raw",
                        "light_off_raw"):
                self.v[key].set(getattr(spec, key))
            for key in ("start_count", "seconds", "award"):
                self.v[key].set(str(int(getattr(spec, key))))
            self.v["clip_seconds"].set("%g" % float(spec.clip_seconds))
            for key in ("screen", "countdown", "lights"):
                self.v[key].set(bool(getattr(spec, key)))
            self.v["art_mode"].set("file" if spec.screen_art else "panel")
            self.v["end_mode"].set("file" if spec.end_sound else "game")
            self.v["advanced"].set(bool(spec.light_on_raw or spec.light_off_raw))
            for name, var in self._shot_vars.items():
                var.set(name in spec.scoring_shots)
            self._open_own_sounds(spec)
            self._open_starts(spec)
            self._open_stacking(spec)
            self._open_advanced(spec)
            self._open_trigger(spec)
            self._open_display_lights(spec)
        finally:
            self._loading = False
        self._show_advanced()
        self._set_editor_state(True)
        self._dirty = False                 # item 148: as saved, until the person edits it
        self._after_change()

    def collect(self):
        """The form as a ModeSpec (the one being edited, updated in place)."""
        spec = self._spec
        if spec is None:
            return None

        def num(key, cast=int):
            try:
                return cast(self.v[key].get().replace(",", "").strip())
            except ValueError:
                return 0

        for key in ("name", "start_shot", "screen_title", "panel_color", "title_color", "clip",
                    "clip_title", "clip_when", "light_color", "light_on_raw", "light_off_raw"):
            setattr(spec, key, self.v[key].get())
        spec.start_count, spec.seconds, spec.award = num("start_count"), num("seconds"), num("award")
        spec.clip_seconds = num("clip_seconds", float)
        for key in ("screen", "countdown", "lights"):
            setattr(spec, key, bool(self.v[key].get()))
        spec.scoring_shots = [n for n, var in self._shot_vars.items() if var.get()]
        if self.v["art_mode"].get() != "file":
            spec.screen_art = ""
        if self.v["end_mode"].get() != "file":
            spec.end_sound = ""
        if not self.v["advanced"].get():
            spec.light_on_raw = spec.light_off_raw = ""
        self._collect_own_sounds(spec)
        self._collect_starts(spec)
        self._collect_stacking(spec)
        self._collect_advanced(spec)
        self._collect_trigger(spec)
        self._collect_display_lights(spec)
        return spec

    def _changed(self):
        if self._loading or self._spec is None or self._widget is None:
            return
        self._dirty = True                  # item 148: an edit on the form; only an edit is saved
        if self._save_job is not None:
            self._widget.after_cancel(self._save_job)
        self._save_job = self._widget.after(SAVE_DELAY_MS, self.save_now)

    def save_now(self):
        """Save the mode being edited, now. Called by the debounce and before switching."""
        if self._save_job is not None and self._widget is not None:
            self._widget.after_cancel(self._save_job)
        self._save_job = None
        project = self._open_project
        if not project or not os.path.isdir(project) or self._slug is None or self._spec is None:
            return
        if getattr(self, "_no_port", ""):
            return                          # item 148: shown read-only, nothing to save
        spec = self.collect()
        MP.save(project, self._slug, spec)
        self._dirty = False
        if getattr(self, "_retarget_note", ""):
            self._retarget_saved = self._slug   # the status says the file now has the card's shots
        i = self._slugs.index(self._slug) if self._slug in self._slugs else -1
        if 0 <= i < self._list.size() and self._list.get(i) != spec.name:
            self._list.delete(i)
            self._list.insert(i, spec.name)
            self._list.selection_set(i)
        self._after_change()
        self._tryit_saved(project, self._slug, spec)

    def _save_if_edited(self):
        """Item 148: before moving to another mode or project, pressing New or Duplicate, or
        opening a film cut - save the open mode only if the person edited it. Opening a mode
        on another title's card matches its shots by name IN THE FORM; with no edit that must
        not reach mode.json (a build refuses a mode naming shots the card lacks until the
        person picks them). An edit is saved as before."""
        if getattr(self, "_dirty", False):
            self.save_now()
        elif self._save_job is not None and self._widget is not None:
            self._widget.after_cancel(self._save_job)
            self._save_job = None

    def _after_change(self):
        spec = self.collect()
        folder = (MP.mode_folder(self._open_project, self._slug)
                  if self._open_project and self._slug else None)
        problems = MP.validate(spec, folder) if spec else []
        self._status.configure(
            text=("Ready to build." if not problems else "To fix before it can be built: " + " ".join(problems)))
        self._art_label.configure(text=spec.screen_art and "Picture: %s" % spec.screen_art or "")
        self._clip_label.configure(text=spec.clip == "file" and spec.clip_file and "Video: %s" % spec.clip_file or "")
        self._sound_label.configure(
            text=spec.end_sound and "Sound: %s (added to the card when you Write)" % spec.end_sound or "")
        self._own_sounds_labels(spec)
        self._update_preview(spec, folder)
        self._note_no_port_in_status()
        self._note_retarget_in_status()
        self._update_film_label(spec)

    def _update_preview(self, spec, folder):
        try:
            from PIL import Image, ImageTk
            if not spec.screen:
                self._preview.configure(image="", text="")
                self._preview_img = None
                return
            if spec.screen_art and folder and os.path.isfile(os.path.join(folder, spec.screen_art)):
                arr = MA.load_art(os.path.join(folder, spec.screen_art))
            else:
                arr = MA.panel_art(spec.screen_title or spec.name, spec.panel_color, spec.title_color)
            img = Image.fromarray(arr)
            img.thumbnail((360, 120))
            self._preview_img = ImageTk.PhotoImage(img)
            self._preview.configure(image=self._preview_img)
        except (ValueError, OSError, tk.TclError):
            self._preview.configure(image="", text="(no preview)")

    # ---- files into the mode folder ---------------------------------------------------
    def _copy_in(self, src, dest_name):
        folder = MP.mode_folder(self._open_project, self._slug)
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, dest_name)
        if os.path.abspath(src) != os.path.abspath(dest):
            shutil.copyfile(src, dest)
        return dest_name

    def _choose(self, title, types, dest_stem, attr, mode_var, fallback):
        if self._spec is None:
            return
        path = filedialog.askopenfilename(title=title, filetypes=types, parent=self._widget)
        if not path:
            if not getattr(self._spec, attr):
                self.v[mode_var].set(fallback)
            return
        name = self._copy_in(path, dest_stem + os.path.splitext(path)[1].lower())
        setattr(self._spec, attr, name)
        self._say("%s: copied %s into the mode's folder" % (self._spec.name, os.path.basename(path)))
        self.save_now()

    def _choose_art(self):
        self._choose("Choose the screen's picture", [("PNG pictures", "*.png")], "art",
                     "screen_art", "art_mode", "panel")

    def _choose_clip(self):
        self._choose("Choose a video", [("Videos", "*.mp4 *.mov *.m4v *.mkv *.avi *.webm"),
                                         ("All files", "*.*")], "clip", "clip_file", "clip", "none")

    def _choose_sound(self):
        self._choose("Choose the sound", [("WAV sounds", "*.wav")], "end", "end_sound",
                     "end_mode", "game")

    # ---- New / Duplicate / Delete ------------------------------------------------------
    def new_mode(self, name="NEW MODE", spec=None):
        """A blank mode, or a copy of ``spec`` (an example) under ``name``. Returns the slug."""
        project = self.project()
        if not project:
            return None
        self._save_if_edited()
        slug, _spec = MP.new_mode(project, name, spec if spec is not None else self._blank_spec())
        self._say("%s (modes/%s)" % ("added the example" if spec else "made a new mode", slug))
        self.refresh(select=slug)
        return slug

    def _on_new(self):
        try:
            self.new_mode()
        except MP.ModeProjectError as e:
            messagebox.showinfo("New mode", str(e), parent=self._widget)

    def _on_example(self, name):
        try:
            self.new_mode(name, MP.example(name))
        except MP.ModeProjectError as e:
            messagebox.showinfo("Example mode", str(e), parent=self._widget)

    def _on_duplicate(self):
        if self._slug is None:
            return
        self._save_if_edited()
        try:
            slug, _spec = MP.duplicate_mode(self.project(), self._slug)
        except MP.ModeProjectError as e:
            messagebox.showinfo("Duplicate mode", str(e), parent=self._widget)
            return
        self._say("duplicated %s as modes/%s" % (self._slug, slug))
        self.refresh(select=slug)

    def delete_mode(self, slug):
        MP.delete_mode(self.project(), slug)
        self._say("deleted modes/%s" % slug)
        if slug == self._slug:
            self._slug, self._spec = None, None
        self.refresh()

    def _on_delete(self):
        if self._slug is None:
            return
        name = self._spec.name if self._spec else self._slug
        if messagebox.askyesno("Delete mode",
                               "Delete %s, with its picture, clip and sound?" % name,
                               parent=self._widget):
            if self._save_job is not None:
                self._widget.after_cancel(self._save_job)
                self._save_job = None
            self.delete_mode(self._slug)

    # ---- Try it: the project's modes in the emulator (item 127) -----------------------
    #
    # ONE LAUNCHER. Try it hands a preparation to the Emulate tab's own Start
    # (EmulatePanel.launch_with, through the window's try_fn): the card is the one in that
    # tab's box, the run is that tab's run, and its Stop stops it. The preparation runs on
    # that tab's start worker: it builds the modes set with WRITE'S OWN CODE (item 149:
    # plugins/stern/mode_tryit.py hands it to mode_write.build_tryit_set, so the run is what
    # a card Written from the project carries), puts the object, the port and the mode files where the
    # rig reads them (modes/tryit.sh, through the Emulate tab's rig_cmd, so it is the same
    # Linux and the same rig as the run), and returns the run's extra environment.
    #
    # WHILE THE GAME RUNS, an autosave pushes the regenerated mode file for that mode's
    # slot, and the runtime re-reads it within half a second. A change to a screen or a
    # clip is a change to built game files, so those say they apply at the next Try it.
    #
    # Every command is built by a PURE method, so the tests read the lists without
    # launching anything.

    TRYIT_TIP = (
        "Try it builds this project's modes as Write puts them on a card (their screens, "
        "clips and own sounds, from the card itself) and starts the card in the Emulate tab "
        "with them. Then start a game: a "
        "mode starts on its shots, or at once with Start mode now. Edits you make while the "
        "game runs reach it within a second.")

    def _init_tryit(self, extra):
        #: main_window._modes_try(prepare): the Emulate tab's launch_with.
        self._try_fn = extra.get("try_fn")
        #: whether the emulator is up (the Emulate panel's own answer).
        self._running_fn = extra.get("running_fn") or (lambda: False)
        #: emulate_tab.rig_cmd, or a stand-in (tests).
        self._rig_cmd_fn = extra.get("rig_cmd_fn")
        #: subprocess.run, or a stand-in (tests).
        self._run_fn = extra.get("run_fn")
        #: opens a document (MODE_SDK.md).
        self._opener = extra.get("opener")
        #: asks for a name (New code mode).
        self._ask_fn = extra.get("ask_fn")
        #: asks for the films' folder (the code-mode Examples), or a stand-in (tests).
        self._ask_dir_fn = extra.get("ask_dir_fn")
        self._ffmpeg_fn = extra.get("ffmpeg_fn")
        self._tryit_base = extra.get("tryit_base") or MT.tryit_dir()
        #: what the last successful install put in the rig: project, slug -> slot, and
        #: each mode's asset signature then (screen and clip fields).
        self._tryit_live = None
        self._tryit_project = ""
        self._tryit_pending = []          # notes from worker threads, for the main loop
        self._say_pending = []            # log lines from worker threads, likewise (_say)
        self._tryit_watches = 0           # _tryit_watch loops running (they write both)
        self._tryit_working = False       # a preparation handed to the Emulate tab is pending
        #: the Emulate panel's launch number (EmulatePanel._launch_serial): the Try it
        #: record belongs to the launch its preparation ran in, and to no later one.
        #: None (no such panel) skips that check.
        self._run_id_fn = extra.get("run_id_fn") or (lambda: None)
        #: the host (sys.platform, or a stand-in in tests): Try it is not on macOS yet
        self._platform = extra.get("platform") or sys.platform

    # ---- the commands (pure) ----------------------------------------------------------
    def _rig_cmd(self, script, *args):
        fn = self._rig_cmd_fn
        if fn is None:
            from . import emulate_tab
            fn = emulate_tab.rig_cmd
        return fn(script, *args)

    @staticmethod
    def _linux_path(path):
        from . import _rig
        return _rig.wsl_path(path) if sys.platform == "win32" else path

    def tryit_env(self):
        """The environment Try it adds to the Emulate tab's launch when its set holds game
        files (a screen or a clip); :func:`mode_tryit.run_env` picks per built set."""
        return MT.try_env(MT.set_dir(self._tryit_base))

    def install_cmd(self, stage):
        return self._rig_cmd("modes/tryit.sh", "install", self._linux_path(stage))

    def trigger_cmd(self, slot):
        return self._rig_cmd("modes/tryit.sh", "start", str(int(slot)))

    def stop_cmd(self, codes=()):
        """End mode: ``mode.stop`` for the form modes, and ``<folder>.stop`` for each CODE
        mode named in ``codes`` (a code mode reads only its own trigger)."""
        return self._rig_cmd("modes/tryit.sh", "stop", *codes)

    def push_cmd(self, path, slot):
        return self._rig_cmd("modes/tryit.sh", "push", self._linux_path(path), str(int(slot)))

    def compile_cmd(self, out, sources):
        """build_mode.sh: the project's code modes with the mode-file interpreter, so the
        tab's mode files keep working beside them."""
        interp = os.path.join(MR.sdk_dir(), "mode_file.c")
        return self._rig_cmd("modes/sdk/build_mode.sh", "-o", self._linux_path(out),
                             *[self._linux_path(s) for s in sources],
                             self._linux_path(interp))

    def _run(self, cmd, timeout=600):
        """``(ok, output)``. Never on the UI thread: a wsl.exe can take seconds."""
        if not cmd:
            return False, "no command"
        run = self._run_fn or subprocess.run
        try:
            r = run(cmd, capture_output=True, text=True, timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()

    # ---- the section ------------------------------------------------------------------
    def _build_tryit_section(self, parent):
        box = ttk.LabelFrame(parent, text=" Try it in the emulator ")
        box.pack(fill=tk.X, padx=10, pady=(4, 0))
        row = ttk.Frame(box)
        row.pack(fill=tk.X, padx=6, pady=(4, 2))
        self._try_btn = ttk.Button(row, text="Try it", command=self._on_try)
        self._try_btn.pack(side=tk.LEFT)
        self._tip(self._try_btn, self.TRYIT_TIP)
        self._start_btn = ttk.Button(row, text="Start mode now", command=self._on_start_now)
        self._start_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._tip(self._start_btn, "Start the mode open on the left in the running game, "
                                   "without its starting shots. A game must be in play.")
        self._end_btn = ttk.Button(row, text="End mode", command=self._on_end_now)
        self._end_btn.pack(side=tk.LEFT, padx=(4, 0))
        self._tip(self._end_btn, "End whichever of this project's modes is running.")
        ttk.Separator(row, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        self._code_btn = ttk.Button(row, text="New code mode…", command=self._on_new_code_mode)
        self._code_btn.pack(side=tk.LEFT)
        self._tip(self._code_btn, "A mode written in C, for what the form cannot do: a copy "
                                  "of the Mode SDK's template in this project's modes folder. "
                                  "Try it builds it in with the others.")
        self._sdk_btn = ttk.Button(row, text="Open MODE_SDK.md", command=self.open_sdk_doc)
        self._sdk_btn.pack(side=tk.LEFT, padx=(4, 0))
        self._tryit_status = ttk.Label(box, text="", wraplength=900, justify=tk.LEFT)
        self._tryit_status.pack(fill=tk.X, padx=6, pady=(0, 4))

    def _tryit_note(self, text):
        """Say ``text`` in the log and on the section's line. Safe from a worker thread:
        there it is queued, and the main loop's :meth:`_tryit_watch` shows it (Tk may only
        be touched from the main thread)."""
        self._say("Try it: " + text)
        self._tryit_pending.append(text)
        if threading.current_thread() is threading.main_thread():
            self._tryit_flush()

    def _tryit_flush(self):
        while self._say_pending and self._log:  # log lines a worker queued (_say)
            self._log(self._say_pending.pop(0))
        while self._tryit_pending:
            text = self._tryit_pending.pop(0)
            try:
                self._tryit_status.configure(text=text)
            except (tk.TclError, AttributeError):
                pass

    def _tryit_watch(self, alive, deadline=None):
        """MAIN THREAD: show queued notes every 150 ms while ``alive()``, then once more."""
        import time
        if deadline is None:                    # a new watch (not its own next tick)
            deadline = time.monotonic() + 900
            self._tryit_watches += 1
        self._tryit_flush()
        if alive() and time.monotonic() < deadline and self._widget is not None:
            try:
                # on the TOPLEVEL: an after() is a Tcl command owned by the widget it was
                # made on, and a root-level after_cancel sweep (app shutdown) must be
                # able to delete it
                self._widget.winfo_toplevel().after(
                    150, lambda: self._tryit_watch(alive, deadline))
                return
            except (tk.TclError, RuntimeError):
                pass
        self._tryit_watches = max(0, self._tryit_watches - 1)
        self._tryit_flush()

    # ---- Try it -----------------------------------------------------------------------
    #: Why Try it does not run on this host, or absent. On macOS the rig runs in padbox.sh's
    #: container, which mounts neither the Try it folder (the install reads the object,
    #: port and mode files from it) nor forwards PAD_MODE_SO: the run would start with no
    #: mode in it. A sentence, not a rig error.
    TRYIT_UNSUPPORTED = {
        "darwin": ("Try it runs on Windows and Linux for now: on a Mac the emulator's "
                   "container cannot see the modes yet. Your modes are saved in the "
                   "project."),
    }

    def _on_try(self):
        # item 148: only an EDIT is saved. Opening a mode on the project's card matches its
        # shots in the form; an unedited mode must keep its file (Try it matches it the same
        # way, mode_tryit.modes_for_the_card)
        self._save_if_edited()
        project = self.project()
        if self._platform in self.TRYIT_UNSUPPORTED:
            self._tryit_note(self.TRYIT_UNSUPPORTED[self._platform])
            return False
        if not project:
            self._tryit_note("open or extract a card project first: modes live in it.")
            return False
        if self._try_fn is None:
            self._tryit_note("there is no Emulate tab to run it in.")
            return False
        if not MP.list_modes(project)[0] and not MT.code_mode_sources(project):
            # a project of CODE modes only goes ahead: _tryit_prepare_code_only
            self._tryit_note("there are no modes in this project yet.")
            return False
        self._tryit_project = project
        self._tryit_note("building the modes and starting the card in the Emulate tab…")
        self._tryit_working = True
        handed = self._try_fn(self.tryit_prepare)
        if handed:
            self._tryit_watch(lambda: self._tryit_working)
        else:
            self._tryit_working = False
            self._tryit_note("the Emulate tab did not start the run; it says why there (pick "
                             "a card, stop a run that is up, or untick \"apply my edits\").")
        return handed

    def tryit_prepare(self, card):
        """The Emulate tab's start worker calls this with its card: build the set, put
        the object, port and mode files in the rig, and return the run's extra env - or
        None, having said why, to stop the run starting."""
        try:
            return self._tryit_prepare(card)
        finally:
            self._tryit_working = False

    def _tryit_prepare(self, card):
        project = self._tryit_project or self.project()
        ffmpeg = None
        try:
            if self._ffmpeg_fn is not None:
                ffmpeg = self._ffmpeg_fn()
            else:
                from ..core.audio import find_ffmpeg
                ffmpeg = find_ffmpeg()
        except Exception:                                   # noqa: BLE001
            ffmpeg = None
        if not card or not os.path.isfile(card):
            self._tryit_note("pick a card image in the Emulate tab first (a %s card)."
                             % MT.project_title(project).label)
            return None
        found_modes, broken = MP.list_modes(project) if project else ([], [])
        try:
            with_assets = MT.code_modes_with_assets(project) if project else []
        except MT.TryItError as e:
            self._tryit_note(str(e))
            return None
        if not found_modes and not broken and MT.code_mode_sources(project) and not with_assets:
            return self._tryit_prepare_code_only(project, card)
        try:
            ts = MT.build_set(project, card, base=self._tryit_base, ffmpeg=ffmpeg,
                              log=lambda m: self._say("Try it: " + m))
        except (MT.TryItError, MP.ModeProjectError, OSError, ValueError) as e:
            self._tryit_note(str(e))
            return None
        codes = MT.code_mode_sources(project)
        if codes and not getattr(ts, "code_object", False):
            # Write's set compiled them when it carried their assets; otherwise build them in here
            ok, out = self._run(self.compile_cmd(os.path.join(ts.stage_dir, MT.OBJECT_NAME),
                                                 [p for _s, p in codes]))
            if not ok:
                self._tryit_note("the code modes did not build: %s" % out[-400:])
                return None
            self._say("Try it: built %d code mode(s) with the mode files: %s"
                      % (len(codes), ", ".join(s for s, _p in codes)))
        ok, out = self._run(self.install_cmd(ts.stage_dir))
        if not ok:
            self._tryit_note("could not put the modes in the emulator: %s" % out[-400:])
            return None
        # the modes AS THIS RUN HAS THEM: matched to the project's card (item 148), which is
        # what the form shows and what an autosave pushes
        found = dict(ts.specs) or dict(MP.list_modes(project)[0])
        self._tryit_live = {
            "project": project,
            "slots": {slug: slot for slot, slug, _name in ts.slots},
            "signatures": {slug: MT.asset_signature(found[slug]) for _s, slug, _n in ts.slots
                           if slug in found},
            "sounds": {slug: MT.sound_signature(found[slug]) for _s, slug, _n in ts.slots
                       if slug in found},
            "stage": ts.stage_dir,
            "run": self._run_id_fn(),
            "codes": self._tryit_code_triggers(codes),
            # the own sounds Write's set carries: an edit pushed while the game runs keeps
            # naming the same carriers (item 149)
            "own": dict(getattr(ts, "own_sounds", None) or {}),
        }
        if ts.slots:
            ready = ("%d mode(s) ready (%s). Start a game, then play the starting shots or press "
                     "Start mode now." % (len(ts.slots), ", ".join(n for _s, _g, n in ts.slots)))
        else:
            # a project of code modes only (the showcase): no form mode, nothing for Start
            # mode now; each code mode starts on its own starting shots
            ready = "Ready. Start a game, then play each mode's starting shots."
        self._tryit_note(ready
                         + self._tryit_code_note(codes)
                         + self._tryit_sound_note(MT.sounds_left_out(ts)))
        if not MT.title_files(ts):
            # nothing of the title in the set (no screen, no clip, no sound, no game
            # program): run_game.sh would refuse a set that binds nothing before boot, so
            # this run takes the object alone (mode_tryit.run_env)
            self._say("Try it: nothing of the game's own files to change, so the run takes "
                      "no override set, only the mode object")
        return MT.run_env(ts)

    @staticmethod
    def _tryit_sound_note(names):
        """The ready line's words for modes with sounds of their own (items 131 and 150)
        that the set does not carry: Try it's set is Write's, so a card Written from the
        project would not carry them either (the log says why), and the run plays the
        game's own calls for them."""
        if not names:
            return ""
        return (" Own sounds of %s are not in this run, nor on a card Written from this "
                "project (the log says why): the game's own calls play." % ", ".join(names))

    @staticmethod
    def _tryit_code_note(codes):
        """The ready line's words for the CODE modes built in: they are not in the list
        (no mode.json), so Start mode now cannot reach them; each has its own trigger. A card
        Written from the project carries them too (compiled into its mode.so, with their own
        clip, screen, music and calls from assets.json), so this run is what the card does."""
        if not codes:
            return ""
        return (" Code mode(s) built in: %s (each starts on its own starting shots, or on "
                "its test trigger /dump/<folder>.start). A card Written from this project "
                "carries them the same way, with their own clip, screen, music and calls."
                % ", ".join(s for s, _p in codes))

    def _tryit_prepare_code_only(self, project, card):
        """A project whose only modes are CODE modes (New code mode, nothing made in the
        form): there is no set to build - no form mode, so no screen or clip - only the
        object compiled from them with the mode-file interpreter, the card's port, and
        PAD_MODE_SO. A code mode runs on the port, so any title the SDK has a port for
        will do."""
        codes = MT.code_mode_sources(project)
        try:
            game_dir, version, _part = MT.card_title(card)
        except MT.TryItError as e:
            self._tryit_note(str(e))
            return None
        port = MR.port_file(game_dir, version)
        if not port:
            self._tryit_note("The Mode SDK has no port for %s %s, so no mode can run on it."
                             % (game_dir or "this card", version))
            return None
        stage = MT.stage_dir(self._tryit_base)
        try:
            if os.path.isdir(stage):
                shutil.rmtree(stage)
            os.makedirs(stage)
            shutil.copyfile(port, os.path.join(stage, MT.PORT_NAME))
        except OSError as e:
            self._tryit_note("could not make the Try it folder %s: %s" % (stage, e))
            return None
        ok, out = self._run(self.compile_cmd(os.path.join(stage, MT.OBJECT_NAME),
                                             [p for _s, p in codes]))
        if not ok:
            self._tryit_note("the code modes did not build: %s" % out[-400:])
            return None
        ok, out = self._run(self.install_cmd(stage))
        if not ok:
            self._tryit_note("could not put the modes in the emulator: %s" % out[-400:])
            return None
        self._tryit_live = {"project": project, "slots": {}, "signatures": {},
                            "stage": stage, "run": self._run_id_fn(),
                            "codes": self._tryit_code_triggers(codes)}
        self._tryit_note("no modes made in the form, so no screens or clips to build. Start "
                         "a game on %s %s." % (game_dir, version)
                         + self._tryit_code_note(codes))
        return ["PAD_MODE_SO=%s" % MT.GUEST_OBJECT]

    # ---- in the running game ------------------------------------------------------------
    def _tryit_live_now(self):
        """What Try it put in the game that is UP now, or None. The record belongs to the
        launch its preparation ran in: once the Emulate tab has launched again (its own
        Start, which carries no modes), it is forgotten; while no run is up it says
        nothing."""
        live = self._tryit_live
        if not live:
            return None
        run = live.get("run")
        if run is not None and self._run_id_fn() != run:
            self._tryit_live = None
            return None
        return live if self._running_fn() else None

    def _selected_slot(self):
        """The open mode's slot IN THE RUNNING GAME, or None. Never the slot the project's
        order would give it now: a mode added after Try it would name another mode's slot
        (the game's slot K is whatever Try it installed there)."""
        project = self._open_project or self.project()
        live = self._tryit_live_now()
        if live and live.get("project") == project and self._slug in live["slots"]:
            return live["slots"][self._slug]
        return None

    def _not_in_game_reason(self, name):
        """Why the open mode cannot be started in the game that is up."""
        project = self._open_project or self.project()
        live = self._tryit_live_now()
        if not live:
            return ("the run that is up was not started by Try it, so none of these modes "
                    "is in it: stop it, then press Try it.")
        if live.get("project") != project:
            return ("the running game has another project's modes: stop the run, then press "
                    "Try it.")
        return ("%s is not in the running game yet: stop the run and press Try it again."
                % name)

    def _in_background(self, cmd, done):
        def work():
            ok, out = self._run(cmd, timeout=60)
            done(ok, out)
        t = threading.Thread(target=work, daemon=True)
        t.start()
        self._tryit_watch(t.is_alive)

    def _on_start_now(self):
        if not self._slug:
            self._tryit_note("open a mode first.")
            return None
        if not self._running_fn():
            self._tryit_note("the emulator is not running: press Try it first.")
            return None
        name = self._spec.name if self._spec else self._slug
        slot = self._selected_slot()
        if slot is None:
            # never a guessed slot: it would start ANOTHER mode and name this one
            self._tryit_note(self._not_in_game_reason(name))
            return None
        cmd = self.trigger_cmd(slot)
        self._in_background(cmd, lambda ok, out: self._tryit_note(
            ("asked the game to start %s (slot %d). A game must be in play." % (name, slot))
            if ok else "could not reach the emulator: %s" % out[-300:]))
        return cmd

    def _on_end_now(self):
        if not self._running_fn():
            self._tryit_note("the emulator is not running.")
            return None
        live = self._tryit_live_now()
        if live is None:
            self._tryit_note("the run that is up was not started by Try it, so it has no "
                             "modes of this tab's to end.")
            return None
        codes = list(live.get("codes") or [])
        cmd = self.stop_cmd(codes)
        self._in_background(cmd, lambda ok, out: self._tryit_note(
            self._end_note(bool(live.get("slots")), codes) if ok
            else "could not reach the emulator: %s" % out[-300:]))
        return cmd

    @staticmethod
    def _end_note(form_modes, codes):
        """What End mode asked for: the form modes' ``mode.stop``, and each code mode's own
        trigger (a code mode never reads ``mode.stop``)."""
        if not codes:
            return "asked the game to end the running mode."
        names = ", ".join(codes)
        if form_modes:
            return "asked the game to end the running mode, and the code mode(s) %s." % names
        return "asked the game to end the code mode(s) %s." % names

    @staticmethod
    def _tryit_code_triggers(codes):
        """The CODE modes End mode can reach: their folder names, which name their test
        triggers (``/dump/<folder>.start`` and ``.stop``, as New code mode writes them).
        Only a plain name (``[a-z0-9_]``, what New code mode makes) goes to the rig: a
        folder made by hand with other characters is not a trigger tryit.sh will write."""
        import re
        return [s for s, _p in codes if re.fullmatch(r"[a-z0-9_]+", s)]

    def _tryit_saved(self, project, slug, spec):
        """After an autosave: while a Try it run is up, push this mode's regenerated file."""
        live = self._tryit_live_now()           # None while no run is up, or another launch's
        if not live or live.get("project") != project or slug not in live["slots"]:
            return None
        slot = live["slots"][slug]
        waits = MT.asset_signature(spec) != live["signatures"].get(slug)
        sounds = live.setdefault("sounds", {})
        if MT.sound_signature(spec) != sounds.get(slug, MT.sound_signature(spec)):
            # a mode's own sounds are built into the set's sound bank, so a change to one
            # cannot reload live, and nothing else would say so
            sounds[slug] = MT.sound_signature(spec)
            self._tryit_note("%s: a change to its own sounds reaches the game at the next "
                             "Try it." % spec.name)
        own = (live.get("own") or {}).get(slug) or {}
        try:
            text = MP.runtime_cfg(spec, slug, own_sounds=own.get("requests") or None,
                                  own_sound_ms=own.get("ms") or None)
        except MP.ModeProjectError:
            return None                        # not valid yet: the status line says why
        if text == self._tryit_game_has(live, slug, slot):
            # nothing new for the game: selecting another mode saves this one first, and
            # run 2 (2026-09-17) showed every such click saying "updated in the running
            # game" over an identical file and a wsl.exe start
            return None
        folder = os.path.join(live["stage"], "push")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, MA.mode_file_name(slot))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        cmd = self.push_cmd(path, slot)
        note = ("%s updated in the running game." % spec.name
                + (" Its screen or clip changes at the next Try it." if waits else ""))

        def pushed(ok, out):
            if ok:
                live.setdefault("texts", {})[slug] = text     # what the game has now
            self._tryit_note(note if ok else "could not update the running game: %s" % out[-300:])
        self._in_background(cmd, pushed)
        return cmd

    @staticmethod
    def _tryit_game_has(live, slug, slot):
        """The mode file the running game was last given for ``slug``: the last push, or
        the one Try it installed from its stage. None when neither can be read."""
        text = live.get("texts", {}).get(slug)
        if text is not None:
            return text
        try:
            with open(os.path.join(live["stage"], MA.mode_file_name(slot)),
                      encoding="utf-8", newline="") as f:
                return f.read()
        except OSError:
            return None

    # ---- code modes and the SDK ---------------------------------------------------------
    def new_code_mode(self, name):
        """Copy the SDK's template into ``modes/<slug>/<slug>.c``. Returns the path."""
        slug, path = MT.new_code_mode(self.project(), name)
        self._tryit_note("made modes/%s/%s.c from the Mode SDK's template. Edit it, then "
                         "Try it builds it in; its test trigger is /dump/%s.start."
                         % (slug, slug, slug))
        return path

    def _on_new_code_mode(self):
        if not self.project():
            self._tryit_note("open or extract a card project first: modes live in it.")
            return None
        ask = self._ask_fn or (lambda: simpledialog.askstring(
            "New code mode", "What is the mode called?", parent=self._widget))
        name = ask()
        if not name or not name.strip():
            return None
        try:
            path = self.new_code_mode(name.strip())
        except (MT.TryItError, OSError) as e:
            self._tryit_note(str(e))
            return None
        self.open_path(path)
        return path

    def sdk_doc(self):
        return os.path.join(MR.sdk_dir(), "MODE_SDK.md")

    def open_path(self, path):
        opener = self._opener
        try:
            if opener is not None:
                opener(path)
            elif self._platform == "win32":
                os.startfile(path)                          # noqa: S606
            else:
                subprocess.Popen(["open" if self._platform == "darwin" else "xdg-open", path])
        except (OSError, AttributeError) as e:
            how = self._open_as_text(path)
            if how:
                self._tryit_note("opened %s %s (nothing on this computer opens a %s file by "
                                 "itself)." % (os.path.basename(path), how,
                                               os.path.splitext(path)[1] or "plain"))
                return
            self._tryit_note("could not open %s: %s" % (path, e))

    def _open_as_text(self, path):
        """When the desktop has nothing for a file's type (a Windows PC with no ``.md``
        association says only "No application is associated"): MODE_SDK.md and a code
        mode's ``.c`` are plain text, so open them in Notepad on Windows, or in the web
        browser elsewhere. Returns how it was opened ("in Notepad", "in the web browser"),
        or "" when that failed too."""
        import pathlib
        import webbrowser
        try:
            if self._platform == "win32":
                subprocess.Popen(["notepad.exe", path])             # noqa: S603,S607
                return "in Notepad"
            if webbrowser.open(pathlib.Path(os.path.abspath(path)).as_uri()):
                return "in the web browser"
        except (OSError, ValueError, RuntimeError, webbrowser.Error):
            pass
        return ""

    def open_sdk_doc(self):
        self.open_path(self.sdk_doc())


    # ---- the title: which card, which port (item 148) ------------------------------------
    #: the sections a title may be unable to do, and the part of a mode each one is
    _PART_SECTIONS = (("lights", "_lights_box"), ("screen", "_screen_box"), ("clip", "_clip_box"))
    #: above this many shots the checkboxes go in three columns, not two (Jaws has 27)
    _TWO_COLUMN_SHOTS = 18

    def _build_title_section(self, frame):
        """Which card the project is for, and whose port its modes run on - or, for a card
        with no port, the message that says how to make one. Godzilla Pro 1.15 until the
        project names a card, as before item 148."""
        self._profile = MP.GODZILLA_PRO_1_15
        self._applied_key = MP.GODZILLA_PRO_1_15.key
        self._card_bound = False
        self._shown = None
        self._no_port = ""
        self._probing = set()
        self._reason_labels = {}
        box = ttk.Frame(frame)
        box.pack(fill=tk.X, padx=10, pady=(0, 2))
        self._title_label = ttk.Label(box, text="", anchor=tk.W, justify=tk.LEFT, wraplength=900)
        self._title_label.pack(fill=tk.X)
        self._title_note = ttk.Label(box, text="", anchor=tk.W, justify=tk.LEFT, wraplength=900)
        self._title_note.pack(fill=tk.X)

    def _apply_project_title(self, project):
        """Find the project's card and its port, then show that title's shots and examples
        and grey what it cannot do. A card with no port turns New and Examples off."""
        card = MP.project_card(project) if project else None
        profile, text, note, no_port = MP.GODZILLA_PRO_1_15, "", "", ""
        if card is None:
            if project:
                text = ("This project names no card, so its modes are made for %s."
                        % MP.GODZILLA_PRO_1_15.label)
        elif not card.game_dir:
            probed = MP.probed_card_title(card.image) if card.image else None
            if (probed is None and card.image and os.path.isfile(card.image)
                    and card.image not in getattr(self, "_probe_gave_up", ())):
                self._probe_card(card.image)
                text = "Card: %s. Reading which game it is from the card..." % MP.file_name(card.image)
                no_port = "Reading which game the card is."
                profile = None
            else:
                text = ("Card: %s. Which game it is could not be read, so its modes are made for %s."
                        % (MP.file_name(card.image), MP.GODZILLA_PRO_1_15.label))
        else:
            found = MP.profile_for_card(card.game_dir, card.version)
            name = MP.file_name(card.image)
            if found is None:
                label = MP.title_label(card.game_dir, card.version)
                text = "Card: %s, %s (from %s)." % (name, label, card.source)
                no_port = MP.NO_PORT_HELP % label
                note = no_port
                profile = None
            else:
                profile = found
                text = ("Card: %s, %s (from %s). Modes run on its port, %s, with its %d shots."
                        % (name, found.label, card.source, found.port, len(found.shots)))
                note = "" if found.proven else "Unproven: " + found.proven_note
        self._title_label.configure(text=text)
        self._title_note.configure(text=note)
        self._no_port = no_port
        if no_port:
            self._new_btn.configure(state=tk.DISABLED)
            self._ex_btn.configure(state=tk.DISABLED)
        self._profile = profile
        # only a card's own port retargets a mode; otherwise each mode shows the title it
        # was made for, so no other title's shot list can overwrite its shots
        self._card_bound = bool(card is not None and card.game_dir and profile is not None)
        self._shown = None
        if profile is not None and profile.key != self._applied_key:
            self._apply_profile(profile)
        elif profile is None and not self._slugs and self._applied_key is not None:
            self._clear_shots()             # nothing to show: never the last project's names
        self._grey_what_the_title_cannot(self._spec is not None)

    def _probe_card(self, image):
        """Read a renamed card's title from its own index, OFF the UI thread (it opens the
        image), then refresh. The answer is cached in mode_project."""
        if image in self._probing or self._widget is None:
            return
        self._probing.add(image)
        threading.Thread(target=MP.probe_card_title, args=(image,), daemon=True,
                         name="modes-card-probe").start()
        self._widget.after(250, lambda: self._poll_probe(image))

    #: how long the tab waits for a card probe before it stops asking (250 ms a try)
    _PROBE_TRIES = 240

    def _poll_probe(self, image, tries=0):
        if (MP.probed_card_title(image) is None and os.path.isfile(image)
                and tries < self._PROBE_TRIES):
            self._widget.after(250, lambda: self._poll_probe(image, tries + 1))
            return
        # answered, or the image went away or never answered: refresh either way, and do
        # not probe that file again this session
        self._probing.discard(image)
        if MP.probed_card_title(image) is None:
            self._probe_gave_up = getattr(self, "_probe_gave_up", set()) | {image}
        self.refresh()

    def _apply_profile(self, p, said=None):
        """Show title ``p``: its shots in the start combobox and the checkboxes, and the
        ready-made modes of the project's title (``p`` when the project has none) under
        Examples. ``said`` replaces the log line (a mode shown on its own title)."""
        names = [n for n, _m in p.shots]
        self._start_combo.configure(values=names)
        for child in self._shots_box.winfo_children():
            child.destroy()
        self._shot_vars = {}
        cols = 2 if len(names) <= self._TWO_COLUMN_SHOTS else 3
        for i, name in enumerate(names):
            var = tk.BooleanVar(value=False)
            var.trace_add("write", lambda *_a: self._changed())
            self._shot_vars[name] = var
            ttk.Checkbutton(self._shots_box, text=name, variable=var).grid(
                row=i // cols, column=i % cols, sticky=tk.W, padx=6, pady=1)
        self._ex_menu.delete(0, tk.END)
        for name, _spec in MP.examples_for(getattr(self, "_profile", None) or p):
            self._ex_menu.add_command(label=name, command=lambda n=name: self._on_title_example(n))
        self._add_code_examples(self._ex_menu, getattr(self, "_profile", None) or p)
        self._applied_key = p.key
        self._say(said or "modes here are for %s: %d shots, from %s" % (p.label, len(names), p.port))
        on = self._spec is not None
        for child in self._shots_box.winfo_children():
            child.configure(state=tk.NORMAL if on else tk.DISABLED)
        self._apply_profile_to_advanced(p, on)
        if self._resize_fn:
            self._resize_fn()

    def _reason(self, box, key, text):
        """A legible line inside ``box`` saying why its section is greyed ("" hides it)."""
        label = self._reason_labels.get(key)
        if not text:
            if label is not None:
                label.grid_remove()
            return
        if label is None:
            label = ttk.Label(box, text="", justify=tk.LEFT, wraplength=380)
            self._reason_labels[key] = label
        label.configure(text="Not on this game: " + text)
        label.grid(row=90, column=0, columnspan=4, sticky=tk.W, padx=6, pady=(2, 4))

    def _grey_what_the_title_cannot(self, on=True):
        """Grey each section the title cannot do, with the reason in words. Called after
        the editor's own state is set, so it never re-enables a section the title lacks."""
        p = getattr(self, "_shown", None) or getattr(self, "_profile", None) or MP.GODZILLA_PRO_1_15
        if not hasattr(self, "_reason_labels"):
            return

        def disable(w):
            for child in w.winfo_children():
                if isinstance(child, self._INTERACTIVE):
                    try:
                        child.configure(state=tk.DISABLED)
                    except tk.TclError:
                        pass
                disable(child)

        for part, attr in self._PART_SECTIONS:
            box = getattr(self, attr, None)
            if box is None:
                continue
            why = p.why_not(part)
            if why:
                disable(box)
            self._reason(box, part, why)
        sound = []
        if p.why_not("countdown"):
            self._countdown_chk.configure(state=tk.DISABLED)
            sound.append(p.why_not("countdown"))
        if p.why_not("own_sound"):
            self._own_sound_radio.configure(state=tk.DISABLED)
        if not p.callout_time_up:
            for child in self._modes_walk(self._sound_box):     # nothing plays: no live choice
                if isinstance(child, ttk.Radiobutton) and str(child.cget("value")) == "game":
                    child.configure(state=tk.DISABLED)
            sound.append("%s's port names no time-up callout, so nothing plays when time is up "
                         "and a sound of the mode's own has no call to replace." % p.label)
        elif p.why_not("own_sound"):
            sound.append(p.why_not("own_sound"))
        self._reason(self._sound_box, "sound", " ".join(sound))
        self._note_unheard_sound(p)
        self._grey_second_clip(p)
        self._grey_stacking_and_film(p)
        self._grey_events(p)
        if getattr(self, "_no_port", "") and getattr(self, "_editor", None) is not None:
            # no port, or the card is still being read: the open mode is shown read-only
            # (Delete stays), since nothing made here could be built for this card yet
            disable(self._editor)
            self._dup_btn.configure(state=tk.DISABLED)

    def _retarget_for_title(self, spec):
        """The mode for the project's title, its shots matched by name. Names the title
        does not have are dropped, and the log says which."""
        p = getattr(self, "_profile", None)
        self._retarget_note, self._retarget_saved = "", None
        if spec is None:
            return spec
        if not getattr(self, "_card_bound", False):
            return self._show_on_its_own_title(spec)
        new, dropped = MP.retarget(spec, p)
        self._retarget_refuses = bool(dropped)     # a moved callout alone builds as it is
        self._retarget_note = self._retarget_words(spec, new, dropped, p)
        if spec.title != p.key or dropped:
            self._say("%s now runs on %s%s" % (
                spec.name, p.label,
                "; " + self._retarget_note if self._retarget_note else ""))
        return new

    @staticmethod
    def _retarget_words(old, new, dropped, p):
        """What opening ``old`` on title ``p`` changed in the form, in words: a start shot the
        title lacks and the shot that replaced it, and the scoring shots left out. "" when
        every shot it names is there."""
        words = []
        if old.start_shot and new.start_shot != old.start_shot:
            words.append("%s is not a shot on %s, so it starts on %s until you pick one" % (
                old.start_shot, p.label, new.start_shot))
        gone = [s for s in old.scoring_shots if s in dropped]
        if gone:
            words.append("%s %s not on %s, so %s left out of the shots that score" % (
                ", ".join(gone), "is" if len(gone) == 1 else "are", p.label,
                "it is" if len(gone) == 1 else "they are"))
        words += ModesPanel._retarget_advanced_words(old, new, dropped, p)
        return "; ".join(words)

    @staticmethod
    def _retarget_advanced_words(old, new, dropped, p):
        """The Advanced section's part of :meth:`_retarget_words` (family sweep): per-shot
        points and an early-ending shot on shots the title lacks, and another title's callout
        ids, dropped or moved to the same callout on this title."""
        words = []
        rows = old.shot_award if isinstance(old.shot_award, list) else []
        paid = []
        for row in rows:
            if (isinstance(row, (list, tuple)) and len(row) == 2 and row[0] in dropped
                    and row[0] not in paid):
                paid.append(row[0])
        if paid:
            words.append("%s %s not on %s, so %s own points %s left out" % (
                ", ".join(paid), "is" if len(paid) == 1 else "are", p.label,
                "its" if len(paid) == 1 else "their", "are"))
        if isinstance(old.end_shot, str) and old.end_shot and not new.end_shot:
            words.append("%s is not on %s, so no shot ends the mode early until you pick one" % (
                old.end_shot, p.label))
        calls = MP.dropped_callouts(dropped)
        if calls:
            words.append("%s %s a sound number of another game and no callout measured on %s, "
                         "so %s left out" % (", ".join(calls), "is" if len(calls) == 1 else "are each",
                                              p.label, "it is" if len(calls) == 1 else "they are"))
        before = old.callout_at if isinstance(old.callout_at, list) else []
        moved = ["callout %s is %s" % (a[1], b[1]) for a, b in zip(
            [r for r in before if isinstance(r, (list, tuple)) and len(r) == 2
             and MP.CALLOUT_DROPPED % MP._int_or_none(r[1]) not in calls],
            [r for r in new.callout_at if isinstance(r, (list, tuple)) and len(r) == 2])
            if MP._int_or_none(a[1]) != MP._int_or_none(b[1])]
        if moved:
            words.append("%s on %s, the same call" % (", ".join(moved), p.label))
        return words

    def _note_retarget_in_status(self):
        """After the status line: what opening the mode on this card's title changed, and
        that its file stays as it was until the person edits it."""
        note = getattr(self, "_retarget_note", "")
        if not note or self._spec is None or getattr(self, "_no_port", ""):
            return
        text = self._status.cget("text")
        saved = getattr(self, "_retarget_saved", "") == self._slug
        ready = "Ready to build."
        refuses = getattr(self, "_retarget_refuses", True)
        if not saved and refuses and text.startswith(ready):
            text = "Ready to build once saved: any edit here saves it." + text[len(ready):]
        tail = ("Its file now has this card's shots." if saved
                else "Until then its file is unchanged, and a build refuses it." if refuses
                else "Its file is unchanged until an edit; a build uses this card's numbers.")
        self._status.configure(text="%s %s%s. %s" % (text, note[0].upper(), note[1:], tail))

    def _show_on_its_own_title(self, spec):
        """A project whose card has no port (or is still being read, or names no card):
        the mode is shown on the title it was made for, unchanged, so the checkboxes are
        that title's and a save writes back the shots it had."""
        try:
            own = MP.profile(spec.title)
        except MP.ModeProjectError:
            own = MP.GODZILLA_PRO_1_15
        self._shown = own
        if own.key != self._applied_key:
            self._apply_profile(own, said="%s is shown with the shots of %s, the game it was made for"
                                % (spec.name, own.label))
        return spec

    def _grey_events(self, p):
        """Item 148 with item 147: on a title whose port names none of the game's events, the
        two "An event" choices and their lists in "Starts and ends" are greyed, with the
        reason; its shot and its clock or the drain stay."""
        var = self.v.get("start_event")
        if var is None or getattr(self, "_editor", None) is None:
            return
        box = None
        for child in self._modes_walk(self._editor):
            if isinstance(child, ttk.Combobox) and str(child.cget("textvariable")) == str(var):
                box = child.master
                break
        if box is None:
            return
        why = p.why_not("events")
        if why:
            for child in self._modes_walk(box):
                if isinstance(child, ttk.Combobox) or (
                        isinstance(child, ttk.Radiobutton) and str(child.cget("value")) == "event"):
                    child.configure(state=tk.DISABLED)
        self._reason(box, "events", why)

    def _clear_shots(self):
        """No title to show (a card with no port and no mode open): no shot names at all,
        rather than the last project's."""
        for child in self._shots_box.winfo_children():
            child.destroy()
        self._shot_vars = {}
        self._start_combo.configure(values=[])
        self._advanced_shots([])                     # nor in Advanced's points per shot
        loading, self._loading = self._loading, True
        try:
            self.v["start_shot"].set("")             # nor the last project's start shot
        finally:
            self._loading = loading
        self._applied_key = None
        reading = getattr(self, "_no_port", "") != self._title_note.cget("text")
        ttk.Label(self._shots_box, text="(no shots yet: reading which game the card is)" if reading
                  else "(no shots: this card's game has no port)").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=1)

    def _note_unheard_sound(self, p):
        """A line under Sound where the title's callouts ran in the emulator but were never
        heard (the rig is always muted): the countdown and a sound of the mode's own stay
        live, and the person is told what is not known yet."""
        label = self._reason_labels.get("sound_unheard")
        note = getattr(p, "sound_note", "")
        if not note or not (p.can("countdown") or p.can("own_sound")):
            if label is not None:
                label.grid_remove()
            return
        if label is None:
            label = ttk.Label(self._sound_box, text="", justify=tk.LEFT, wraplength=380)
            self._reason_labels["sound_unheard"] = label
        label.configure(text="Not heard yet: " + note)
        label.grid(row=91, column=0, columnspan=4, sticky=tk.W, padx=6, pady=(2, 4))

    def _apply_profile_to_advanced(self, p, on):
        """Item 148 with items 141 and 147: the Advanced section's per-shot points and its
        early-ending shot list title ``p``'s own shots, its callout picks ``p``'s own measured
        callouts, and "An event" ``p``'s own events - never Godzilla Pro 1.15's on another
        game. Built once for Pro 1.15; rebuilt here when the shown title changes."""
        frame = getattr(self, "_params_frame", None)
        if getattr(self, "_shot_award_vars", None) is None or frame is None:
            return
        self._advanced_shots([n for n, _m in p.shots], on)
        choices = [(label, number) for label, number in MP.callout_choices(p) if number]
        picks = [c for c in self._modes_walk(frame)
                 if isinstance(c, ttk.Menubutton) and str(c.cget("text")) == "Pick"]
        for (_secs, cid), pick in zip(getattr(self, "_callout_rows", []), picks):
            menu = pick.nametowidget(pick.cget("menu"))
            menu.delete(0, tk.END)
            for label, number in choices:
                menu.add_command(label="%s (%d)" % (label, number),
                                 command=lambda v=cid, n=number: self._pick_callout(v, n))
            if not choices:
                menu.add_command(label="(no callouts measured on %s: type an id)" % p.label,
                                 state=tk.DISABLED)
        events = [MP.EVENT_LABELS.get(n, n) for n in p.events]
        for key in ("start_event", "end_event"):
            var = self.v.get(key)
            for child in self._modes_walk(self._editor) if var is not None and events else ():
                if isinstance(child, ttk.Combobox) and str(child.cget("textvariable")) == str(var):
                    child.configure(values=events)

    def _advanced_shots(self, names, on=False):
        """The Advanced section's "Points per shot" rows and "Ends early when hit" list, for
        the shot ``names`` (none on a card with no port)."""
        awards = getattr(self, "_shot_award_vars", None)
        frame = getattr(self, "_params_frame", None)
        if awards is None or frame is None:
            return
        grid, end_combo = getattr(self, "_award_grid", None), None
        first = next(iter(awards.values()), None)
        for child in self._modes_walk(frame):
            if grid is None and first is not None and isinstance(child, ttk.Entry) \
                    and not isinstance(child, ttk.Spinbox) and str(child.cget("textvariable")) == str(first):
                grid = self._award_grid = child.master
            if isinstance(child, ttk.Combobox) and str(child.cget("textvariable")) == str(self.v["end_shot"]):
                end_combo = child
        if grid is not None and list(awards) != list(names):
            for child in grid.winfo_children():
                child.destroy()
            self._shot_award_vars = {}
            for i, name in enumerate(names):
                var = tk.StringVar(value="")
                var.trace_add("write", lambda *_a: self._changed())
                self._shot_award_vars[name] = var
                ttk.Label(grid, text=name).grid(row=i // 2, column=(i % 2) * 2, sticky=tk.W, padx=(0, 4))
                e = ttk.Entry(grid, width=10, textvariable=var, state=tk.NORMAL if on else tk.DISABLED)
                e.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky=tk.W, padx=(0, 10), pady=1)
                self._tip(e, "What %s pays instead of the first shot's points. Blank = the usual "
                             "points. A shot with its own points scores even when it is not ticked "
                             "under Shots that score." % name)
            if not names:                # a frame left with no children keeps its old height
                ttk.Label(grid, text="(no shots)").grid(row=0, column=0, sticky=tk.W)
        if end_combo is not None:
            end_combo.configure(values=[self.PARAM_NEVER] + list(names))

    def _grey_second_clip(self, p):
        """Advanced's "Second clip" plays at the other end from the mode's clip, so a title
        that cannot add a clip greys it too, with the reason."""
        var = self.v.get("clip_both")
        frame = getattr(self, "_params_frame", None)
        if var is None or frame is None:
            return
        why = "" if p.can("clip") else "a second clip, since %s cannot add a clip (Clip says why)." % p.label
        keys = {str(self.v[k]) for k in ("clip_both", "clip_both_title", "clip_both_seconds") if k in self.v}
        for child in self._modes_walk(frame):
            if why and isinstance(child, (ttk.Radiobutton, ttk.Entry)):
                key = "variable" if isinstance(child, ttk.Radiobutton) else "textvariable"
                if str(child.cget(key)) in keys:
                    child.configure(state=tk.DISABLED)
        self._reason(frame, "clip_both", why)

    def _blank_form(self):
        """No mode open: the greyed form shows no values of the mode that was open before
        (a project switched to with no modes kept the last one's name, seconds and shots)."""
        loading, self._loading = self._loading, True
        try:
            for key in ("name", "start_shot", "start_count", "seconds", "award", "screen_title",
                        "clip_title", "clip_seconds", "light_on_raw", "light_off_raw", "clip_both_title"):
                if key in self.v:
                    self.v[key].set("")
            for var in list(self._shot_vars.values()) + list(getattr(self, "_shot_award_vars", {}).values()):
                var.set(False if isinstance(var, tk.BooleanVar) else "")
            for secs, cid in getattr(self, "_callout_rows", []):
                secs.set("")
                cid.set("")
        finally:
            self._loading = loading
        for label in (self._art_label, self._clip_label, self._sound_label):
            label.configure(text="")
        if getattr(self, "_film_label", None) is not None:
            self._film_label.configure(text="")
        self._preview.configure(image="", text="")
        self._preview_img = None

    def _blank_spec(self):
        return MP.blank_spec(getattr(self, "_profile", None) or MP.GODZILLA_PRO_1_15)

    def _on_title_example(self, name):
        spec = dict(MP.examples_for(getattr(self, "_profile", None) or MP.GODZILLA_PRO_1_15)).get(name)
        try:
            self.new_mode(name, spec)
        except MP.ModeProjectError as e:
            messagebox.showinfo("Example mode", str(e), parent=self._widget)

    def _note_no_port_in_status(self):
        no_port = getattr(self, "_no_port", "")
        if no_port:
            self._status.configure(text="Modes cannot be built for this card yet: %s%s" % (
                "it has no port (see above)." if no_port == self._title_note.cget("text") else no_port,
                " The mode is shown as it was saved, read-only." if self._spec is not None else ""))

    #: the film buttons (item 142) and the part of a mode each cut is for
    _FILM_PARTS = (("clip", "clip", "a clip"), ("still", "screen", "a picture for the screen"),
                   ("sound", "own_sound", "a sound"))

    def _stacking_box(self):
        """The "game's own modes" section (item 140): the frame holding the checkbox that
        edits ``stack``, found by its variable."""
        var = self.v.get("stack")
        if var is None or getattr(self, "_editor", None) is None:
            return None
        for child in self._modes_walk(self._editor):
            if isinstance(child, ttk.Checkbutton) and str(child.cget("variable")) == str(var):
                return child.master
        return None

    @staticmethod
    def _modes_walk(widget):
        for child in widget.winfo_children():
            yield child
            yield from ModesPanel._modes_walk(child)

    def _grey_stacking_and_film(self, p):
        """Grey what other sections offer that title ``p`` cannot do, with the reason: the
        game's own modes (``stack``) on a port with no stock mode queries, and the film cuts
        for a clip, a screen picture or a sound the title cannot use."""
        box = self._stacking_box()
        if box is not None:
            why = p.why_not("stack")
            if why:
                for child in self._modes_walk(box):
                    if isinstance(child, self._INTERACTIVE):
                        child.configure(state=tk.DISABLED)
            self._reason(box, "stack", why)
        btns = getattr(self, "_film_btns", None) or {}
        off = []
        for take, part, words in self._FILM_PARTS:
            btn = btns.get(take)
            if btn is not None and not p.can(part):
                btn.configure(state=tk.DISABLED)
                off.append(words)
        label = getattr(self, "_film_label", None)
        if label is not None:
            text = ""
            if off:
                what = off[0] if len(off) == 1 else ", ".join(off[:-1]) + " or " + off[-1]
                text = ("cutting %s from a film, because %s cannot use %s (the sections above "
                        "say why)." % (what, p.label, "it" if len(off) == 1 else "them"))
            self._reason(label.master, "film", text)

    # ---- From a film (item 142) --------------------------------------------------------
    FILM_TIP = ("Cut this mode's clip, its sound or its screen's picture from a film: pick "
                "the film, a start time and a length (up to 30 seconds), and whether to keep "
                "the film's letterbox or fill the frame. The mode keeps only the cut "
                "(clip.mp4, end.wav, art.png), never the film.")

    def _build_film_section(self, parent):
        box = ttk.LabelFrame(parent, text=" From a film ")
        box.pack(fill=tk.X, pady=(0, 6))
        row = ttk.Frame(box)
        row.grid(row=0, column=0, sticky=tk.W, padx=6, pady=(2, 2))
        ttk.Label(row, text="Cut from a film:").pack(side=tk.LEFT)
        self._film_btns = {}
        for text, take in (("Clip…", "clip"), ("Sound…", "sound"), ("Picture…", "still")):
            btn = ttk.Button(row, text=text, width=9, command=lambda t=take: self._open_film_cut(t))
            btn.pack(side=tk.LEFT, padx=(6, 0))
            self._tip(btn, self.FILM_TIP)
            self._film_btns[take] = btn
        self._film_label = ttk.Label(box, text="", wraplength=440, justify=tk.LEFT)
        self._film_label.grid(row=1, column=0, sticky=tk.W, padx=6, pady=(0, 4))

    def _update_film_label(self, spec):
        label = getattr(self, "_film_label", None)
        if label is None or spec is None:
            return
        from .film_cut_dialog import describe
        label.configure(text=describe(spec) or "Nothing cut from a film yet.")

    def _open_film_cut(self, take):
        """The "From a film" dialog for the open mode, on the film and times it last used."""
        if self._spec is None or not self._open_project:
            return None
        from .film_cut_dialog import FilmCutDialog, FilmCutForm
        self._save_if_edited()
        form = FilmCutForm.from_spec(self._spec, take)
        return FilmCutDialog(self._widget, self._theme_fn(), form,
                             MP.mode_folder(self._open_project, self._slug), self.apply_film_cut)

    @staticmethod
    def _film_cut_into(spec, result):
        from .film_cut_dialog import PROVENANCE
        if result.get("clip_file"):
            spec.clip, spec.clip_file = "file", result["clip_file"]
        if result.get("end_sound"):
            spec.end_sound = result["end_sound"]
        if result.get("screen_art"):
            spec.screen_art = result["screen_art"]
        for key in PROVENANCE:
            if key in result:
                setattr(spec, key, result[key])

    def apply_film_cut(self, result):
        """Make a cut (:meth:`FilmCutForm.apply`'s result) the mode's clip, end sound and
        picture, with where each came from, and save. A cut made for a mode that is no
        longer open goes into THAT mode's file."""
        folder = result.get("mode_folder") or ""
        here = (MP.mode_folder(self._open_project, self._slug)
                if self._open_project and self._slug else "")
        if folder and os.path.normcase(os.path.abspath(folder)) != os.path.normcase(os.path.abspath(here or "")):
            path = os.path.join(folder, MP.MODE_FILE)
            if os.path.isfile(path):
                spec = MP.load(path)
                self._film_cut_into(spec, result)
                MP.save(os.path.dirname(os.path.dirname(folder)), os.path.basename(folder), spec)
            return
        if self._spec is None:
            return
        self._loading = True
        try:
            if result.get("clip_file"):
                self.v["clip"].set("file")
            if result.get("end_sound"):
                self.v["end_mode"].set("file")
            if result.get("screen_art"):
                self.v["art_mode"].set("file")
        finally:
            self._loading = False
        self._film_cut_into(self._spec, result)
        self._say("%s: %s" % (self._spec.name, result.get("summary") or "cut from a film"))
        self.save_now()

    # ---- Advanced: every other parameter the runtime has (item 141) -----------------
    #: callout rows the section offers; the runtime takes 8 callout_at lines, one of them
    #: the countdown's
    PARAM_CALLOUT_ROWS = 4
    PARAM_NEVER = "(only when time runs out)"
    PARAM_SECOND_CLIP = (("none", "None"), ("same", "The same clip"), ("title", "A title card"),
                         ("file", "My video…"))

    def _build_advanced_section(self, parent):
        box = ttk.LabelFrame(parent, text=" Advanced: scoring, ending, clips, callouts ")
        box.pack(fill=tk.X, pady=(0, 6))
        box.columnconfigure(0, weight=1)
        # a plain variable: showing the section is not an edit to the mode
        self._params_show = tk.BooleanVar(value=False)
        show = ttk.Checkbutton(box, text="Show every other setting", variable=self._params_show,
                               command=self._show_parameters)
        show.grid(row=0, column=0, sticky=tk.W, padx=6)
        self._tip(show, "What each shot pays, a shot that ends the mode early, a clip at both "
                        "ends, callouts at chosen seconds, and how long the screen stays up.")
        f = self._params_frame = ttk.Frame(box)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Award ladder").grid(row=0, column=0, sticky=tk.W, pady=2)
        ladder = self._var("award_ladder", value="rising")
        r = ttk.Frame(f)
        r.grid(row=0, column=1, columnspan=3, sticky=tk.W, padx=6)
        b = ttk.Radiobutton(r, text="Rising", value="rising", variable=ladder)
        b.pack(side=tk.LEFT)
        self._tip(b, "The Nth scoring shot pays N times its points: 1x, 2x, 3x...")
        b = ttk.Radiobutton(r, text="Fixed", value="fixed", variable=ladder)
        b.pack(side=tk.LEFT, padx=8)
        self._tip(b, "Every scoring shot pays its points once.")

        ttk.Label(f, text="Points per shot").grid(row=1, column=0, sticky=tk.NW, pady=2)
        grid = ttk.Frame(f)
        grid.grid(row=1, column=1, columnspan=3, sticky=tk.W, padx=6)
        self._shot_award_vars = {}
        for i, (name, _mask) in enumerate(MP.GODZILLA_PRO_1_15.shots):
            var = tk.StringVar(value="")
            var.trace_add("write", lambda *_a: self._changed())
            self._shot_award_vars[name] = var
            ttk.Label(grid, text=name).grid(row=i // 2, column=(i % 2) * 2, sticky=tk.W, padx=(0, 4))
            e = ttk.Entry(grid, width=10, textvariable=var)
            e.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky=tk.W, padx=(0, 10), pady=1)
            self._tip(e, "What %s pays instead of the first shot's points. Blank = the usual "
                         "points. A shot with its own points scores even when it is not ticked "
                         "under Shots that score." % name)

        ttk.Label(f, text="Ends early when hit").grid(row=2, column=0, sticky=tk.W, pady=2)
        c = ttk.Combobox(f, state="readonly", width=24, textvariable=self._var("end_shot", value=self.PARAM_NEVER),
                         values=[self.PARAM_NEVER] + [n for n, _m in MP.GODZILLA_PRO_1_15.shots])
        c.grid(row=2, column=1, columnspan=3, sticky=tk.W, padx=6)
        self._tip(c, "A shot that ends the mode at once. It pays first if it is a scoring shot.")

        ttk.Label(f, text="Second clip").grid(row=3, column=0, sticky=tk.W, pady=2)
        both = self._var("clip_both", value="none")
        r = ttk.Frame(f)
        r.grid(row=3, column=1, columnspan=3, sticky=tk.W, padx=6)
        for value, text in self.PARAM_SECOND_CLIP:
            ttk.Radiobutton(r, text=text, value=value, variable=both,
                            command=self._choose_second_clip if value == "file" else None).pack(
                side=tk.LEFT, padx=(0, 6))
        self._tip(r, "A clip at the OTHER end from the one under Clip: at the end when that one "
                     "plays at the start, and the other way round.")
        ttk.Label(f, text="Its title").grid(row=4, column=0, sticky=tk.W, pady=2)
        e = ttk.Entry(f, textvariable=self._var("clip_both_title"))
        e.grid(row=4, column=1, sticky=tk.EW, padx=6)
        self._tip(e, "The second title card's words. Empty uses the mode's name.")
        ttk.Spinbox(f, from_=1, to=30, width=4, textvariable=self._var("clip_both_seconds", value="4")).grid(
            row=4, column=2, sticky=tk.W)
        ttk.Label(f, text="seconds").grid(row=4, column=3, sticky=tk.W, padx=(4, 6))
        self._clip2_file = ""
        self._clip2_label = ttk.Label(f, text="")
        self._clip2_label.grid(row=5, column=1, columnspan=3, sticky=tk.W, padx=6)
        self._clip2_label.grid_remove()                  # a row only when there is a video

        ttk.Label(f, text="Callouts").grid(row=6, column=0, sticky=tk.NW, pady=2)
        rows = ttk.Frame(f)
        rows.grid(row=6, column=1, columnspan=3, sticky=tk.W, padx=6)
        self._callout_rows = []
        choices = MP.callout_choices(MP.GODZILLA_PRO_1_15)
        for i in range(self.PARAM_CALLOUT_ROWS):
            secs = self._var("callout_secs_%d" % i)
            cid = self._var("callout_id_%d" % i)
            ttk.Label(rows, text="at").grid(row=i, column=0, sticky=tk.W)
            s = ttk.Spinbox(rows, from_=0, to=300, width=5, textvariable=secs)
            s.grid(row=i, column=1, sticky=tk.W, padx=4, pady=1)
            ttk.Label(rows, text="s left, callout").grid(row=i, column=2, sticky=tk.W)
            # an Entry, not a Combobox: the empty editor makes every Combobox readonly, and
            # an id no one has named yet must still be typed
            e = ttk.Entry(rows, width=7, textvariable=cid)
            e.grid(row=i, column=3, sticky=tk.W, padx=4)
            pick = ttk.Menubutton(rows, text="Pick", width=5)
            menu = tk.Menu(pick, tearoff=0)
            for label, number in choices:
                menu.add_command(label="%s (%d)" % (label, number),
                                 command=lambda v=cid, n=number: self._pick_callout(v, n))
            pick.configure(menu=menu)
            pick.grid(row=i, column=4, sticky=tk.W)
            self._callout_rows.append((secs, cid))
        self._tip(rows, "One of the game's own callouts, by number, when that many seconds are "
                        "left. Pick names the ones measured to play on this game; the countdown "
                        "under Sound adds its own.")

        ttk.Label(f, text="Screen stays up").grid(row=7, column=0, sticky=tk.W, pady=2)
        r = ttk.Frame(f)
        r.grid(row=7, column=1, columnspan=3, sticky=tk.W, padx=6)
        ttk.Spinbox(r, from_=1, to=MP.RESTORE_AFTER_MAX, width=4,
                    textvariable=self._var("restore_after", value="6")).pack(side=tk.LEFT)
        ttk.Label(r, text="seconds after it ends").pack(side=tk.LEFT, padx=(4, 0))
        self._tip(r, "How long the mode's own screen (Screen, above) shows its total after the "
                     "mode ends. With no screen of its own this does nothing.")
        # a control the user sets forgets the raw value _open_advanced kept for it
        for key in ("award_ladder", "end_shot", "clip_both"):
            self.v[key].trace_add("write", lambda *_a, k=key: getattr(self, "_params_raw", {}).pop(k, None))

    def _show_parameters(self):
        if self._params_show.get():
            self._params_frame.grid(row=1, column=0, sticky=tk.EW, padx=6, pady=(2, 4))
        else:
            self._params_frame.grid_remove()
        if self._resize_fn:
            self._resize_fn()

    def _show_clip2_file(self):
        self._clip2_label.configure(text=self._clip2_file and "Video: %s" % self._clip2_file or "")
        if self._clip2_file:
            self._clip2_label.grid()
        else:
            self._clip2_label.grid_remove()

    def _pick_callout(self, var, number):
        if self._spec is not None:
            var.set(str(number))

    def _choose_second_clip(self):
        if self._spec is None:
            return
        path = filedialog.askopenfilename(title="Choose the second clip's video",
                                          filetypes=[("Videos", "*.mp4 *.mov *.m4v *.mkv *.avi *.webm"),
                                                     ("All files", "*.*")], parent=self._widget)
        if not path:
            if not self._clip2_file:
                self.v["clip_both"].set("none")
            return
        self._clip2_file = self._copy_in(path, "clip2" + os.path.splitext(path)[1].lower())
        self._show_clip2_file()
        self._say("%s: copied %s into the mode's folder" % (self._spec.name, os.path.basename(path)))
        self.save_now()

    def _open_advanced(self, spec):
        """The form from the spec's Advanced fields. What the form cannot show (a shot this
        title does not name, a second award for one shot, callouts past the rows or not
        [seconds, id], an unknown ladder, end shot or second clip) is kept, and written back
        as it was unless that control is changed."""
        names = dict(MP.GODZILLA_PRO_1_15.shots)
        names = self._shot_award_vars or names          # item 148: the shown title's shots

        def named(shot):
            return isinstance(shot, str) and shot in names

        # field -> the raw value the form cannot show; _collect_advanced writes it back, and a
        # write to that control (the traces in _build_advanced_section) forgets it
        raw = {}
        self._params_raw = {}
        if spec.award_ladder not in MP.AWARD_LADDERS:
            raw["award_ladder"] = spec.award_ladder
        self.v["award_ladder"].set(spec.award_ladder if spec.award_ladder in MP.AWARD_LADDERS else "rising")
        awards = spec.shot_award if isinstance(spec.shot_award, list) else []
        shown, self._params_kept_awards = {}, []
        for r in awards:                 # the runtime pays a shot's FIRST line, so the form shows it
            if isinstance(r, (list, tuple)) and len(r) == 2 and named(r[0]) and r[0] not in shown:
                shown[r[0]] = r[1]
            else:
                self._params_kept_awards.append(r)
        for name, var in self._shot_award_vars.items():
            var.set("" if name not in shown else str(shown[name]))
        if spec.end_shot and not named(spec.end_shot):
            raw["end_shot"] = spec.end_shot
        self.v["end_shot"].set(spec.end_shot if named(spec.end_shot) else self.PARAM_NEVER)
        both = spec.clip_both if isinstance(spec.clip_both, dict) else {}
        kind = both.get("clip") if both.get("clip") in MP.SECOND_CLIP_KINDS else "none"
        if spec.clip_both and kind == "none":
            raw["clip_both"] = spec.clip_both
        self.v["clip_both"].set(kind)
        self.v["clip_both_title"].set(both.get("title", ""))
        self.v["clip_both_seconds"].set("%g" % float(both.get("seconds", 4.0))
                                        if isinstance(both.get("seconds", 4.0), (int, float))
                                        else str(both.get("seconds")))
        self._clip2_file = both.get("file", "") or ""
        self._show_clip2_file()
        calls = spec.callout_at if isinstance(spec.callout_at, list) else []
        rows = [r for r in calls if isinstance(r, (list, tuple)) and len(r) == 2][:self.PARAM_CALLOUT_ROWS]
        self._params_kept_callouts = [r for r in calls if not any(r is s for s in rows)]
        for i, (secs, cid) in enumerate(self._callout_rows):
            row = rows[i] if i < len(rows) else ("", "")
            secs.set(str(row[0]))
            cid.set(str(row[1]))
        self.v["restore_after"].set(str(spec.restore_after))
        self._params_show.set(self._params_show.get() or bool(
            spec.award_ladder != "rising" or awards or spec.end_shot or spec.clip_both or calls
            or str(spec.restore_after) != "6"))
        self._show_parameters()
        self._params_raw = raw           # last: the sets above fired the forgetting traces

    def _collect_advanced(self, spec):
        """The Advanced fields from the form. A value that is not a number is kept as typed,
        so the status names it rather than the form quietly dropping it."""
        def number(text, cast=int):
            s = text.replace(",", "").strip()
            try:
                return cast(s)
            except ValueError:
                return s

        spec.award_ladder = self.v["award_ladder"].get()
        spec.shot_award = [[name, number(var.get())] for name, var in self._shot_award_vars.items()
                           if var.get().strip()] + list(getattr(self, "_params_kept_awards", []))
        end = self.v["end_shot"].get()
        spec.end_shot = "" if end == self.PARAM_NEVER else end
        kind = self.v["clip_both"].get()
        if kind == "same":
            spec.clip_both = {"clip": "same"}
        elif kind == "title":
            spec.clip_both = {"clip": "title", "title": self.v["clip_both_title"].get(),
                              "seconds": number(self.v["clip_both_seconds"].get(), float)}
        elif kind == "file":
            spec.clip_both = {"clip": "file", "file": self._clip2_file}
        else:
            spec.clip_both = {}
        rows = []
        for secs, cid in self._callout_rows:
            if secs.get().strip() or cid.get().strip():
                rows.append([number(secs.get()), number(cid.get())])
        spec.callout_at = rows + list(getattr(self, "_params_kept_callouts", []))
        spec.restore_after = number(self.v["restore_after"].get())
        for key, raw in getattr(self, "_params_raw", {}).items():
            setattr(spec, key, raw)                  # untouched: what the form could not show stays

    # ---- the game's own modes (item 145) ---------------------------------------------------
    # The modes the game shipped with are compiled into its program, so what can change is a
    # NUMBER: a timer or an award that is one word the code loads, or an operator setting.
    # The table of which word holds what comes from item 144 (plugins/stern/stock_mode_tables);
    # a change stages with the project like the Defaults tab's and Write puts it on the card.

    STOCK_TIP = (
        "The timers and awards of the modes the game shipped with. Pick a row, type a new "
        "value and press Set. Changes are saved with this project and put on the card by "
        "Write, like the Defaults tab. A timer that is an operator setting is the same number "
        "the Defaults tab shows (a machine still on the game's default takes the new one when "
        "it boots). A "
        "number the game works out in code can't be changed here; the row says why. To rename "
        "a mode, edit its title on the Text tab.")

    # ---- code modes with their own assets, and the code-mode Examples ------------------------
    #
    # A code mode (modes/<slug>/<slug>.c) is not in the list on the left (it has no mode.json and
    # no form). Its own clip, screen picture, music and calls sit beside it, named in its
    # assets.json (plugins/stern/code_modes.py); Try it and Write carry them like a form mode's.
    # The Examples menu offers the Mode SDK's five intricate modes as code modes: each brings its
    # code and a RECIPE naming the film times its assets are cut from, and the app's film cutter
    # cuts them from the person's own copy of the films. Nothing of a film is in the app.

    CODE_EXAMPLE_SUFFIX = " (code mode)"

    def _add_code_examples(self, menu, p=None):
        """The code-mode Examples under the form ones, for a Godzilla title (their shots are
        Godzilla's)."""
        from ..plugins.stern import code_modes as CM
        if p is not None and not str(getattr(p, "game_dir", "")).startswith("godzilla"):
            return
        names = CM.example_names()
        if not names:
            return
        menu.add_separator()
        for name in names:
            menu.add_command(label=name + self.CODE_EXAMPLE_SUFFIX,
                             command=lambda n=name: self._on_code_example(n))

    def _build_code_modes_section(self, parent):
        box = ttk.LabelFrame(parent, text=" Code modes ")
        box.pack(fill=tk.X, padx=10, pady=(4, 0))
        row = ttk.Frame(box)
        row.pack(fill=tk.X, padx=6, pady=(2, 4))
        self._code_label = ttk.Label(row, text="", wraplength=760, justify=tk.LEFT)
        self._code_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._cut_btn = ttk.Button(row, text="Cut film assets…", command=self._on_cut_films)
        self._cut_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._tip(self._cut_btn, "Cut the code-mode examples' clip, picture, music and calls from "
                                 "your own copy of the Godzilla films, with the film cutter. Pick the "
                                 "folder that holds the films.")

    def code_modes_words(self, project):
        """The section's line: each code mode and what it carries of its own."""
        from ..plugins.stern import code_modes as CM
        try:
            code = CM.list_code(project) if project else []
        except CM.CodeModeError as e:
            return str(e)
        if not code:
            return ("No code modes in this project. New code mode… starts one from the SDK's "
                    "template; Examples has five written in C, with clips, music and calls cut "
                    "from the films.")
        parts = []
        for slug, spec in code:
            have = [w for w, on in (("clip", spec.clip), ("picture", spec.screen_art),
                                    ("music", spec.music)) if on]
            if spec.calls:
                have.append("%d call(s)" % len(spec.calls))
            recipe = (spec.film or {}).get("recipe")
            if have:
                parts.append("%s (%s)" % (spec.name, ", ".join(have)))
            elif recipe:
                parts.append("%s (its film assets are not cut yet)" % spec.name)
            else:
                parts.append("%s (the game's own sounds)" % spec.name)
        return ("Code modes: %s. Try it and Write carry each one's own clip, picture, music and "
                "calls; edit a mode in modes/<folder>/<folder>.c." % "; ".join(parts))

    def _refresh_code_modes(self, project):
        label = getattr(self, "_code_label", None)
        if label is None:
            return
        try:
            label.configure(text=self.code_modes_words(project))
            self._cut_btn.configure(state=tk.NORMAL if project else tk.DISABLED)
        except tk.TclError:
            pass

    def _ffmpeg_path(self):
        try:
            if self._ffmpeg_fn is not None:
                return self._ffmpeg_fn()
            from ..core.audio import find_ffmpeg
            return find_ffmpeg()
        except Exception:                                   # noqa: BLE001
            return None

    def _ask_films_dir(self, why):
        """The folder that holds the films, asked with *why* as the title; "" when cancelled."""
        fn = getattr(self, "_ask_dir_fn", None)
        if fn is not None:
            return fn(why) or ""
        return filedialog.askdirectory(parent=self._widget, title=why, mustexist=True) or ""

    def add_code_example(self, name, dirs=None, wait=False):
        """Add code-mode example *name* to the project: its code, its assets.json, and its assets
        cut from the films found in *dirs* (plus the folders :func:`code_modes.film_dirs` knows).
        The cutting runs off the UI thread; *wait* joins it (tests). Returns the worker thread, or
        None when nothing was started (the tab says why)."""
        from ..plugins.stern import code_modes as CM
        project = self.project()
        if not project:
            self._tryit_note("open or extract a card project first: modes live in it.")
            return None
        ex = CM.example(name)
        if ex is None:
            return None
        if os.path.exists(MP.mode_folder(project, ex["slug"])):
            self._tryit_note("%s is already in this project (modes/%s)." % (name, ex["slug"]))
            return None
        dirs = list(dirs or ()) + CM.film_dirs(project)
        ffmpeg = self._ffmpeg_path()
        self._tryit_note("adding the example %s (code mode)…" % name)

        def work():
            try:
                slug, missing = CM.add_example(project, name, dirs=dirs, ffmpeg=ffmpeg,
                                               log=lambda m, *a: self._say(m))
            except Exception as e:                          # noqa: BLE001 - a sentence for the person
                self._tryit_note("%s could not be added: %s" % (name, e))
                return
            self._tryit_note(self._code_example_note(name, slug, missing, CM))

        t = threading.Thread(target=work, daemon=True)
        t.start()
        if wait:
            t.join()
            self._tryit_flush()
            self._refresh_code_modes(project)
        else:
            self._tryit_watch(t.is_alive)
            self._code_refresh_later(t)
        return t

    def _code_refresh_later(self, t):
        """Refresh the section's line once the worker is done (main thread)."""
        try:
            if t.is_alive():
                self._widget.winfo_toplevel().after(200, lambda: self._code_refresh_later(t))
            else:
                self._refresh_code_modes(self.project())
        except (tk.TclError, RuntimeError, AttributeError):
            pass

    @staticmethod
    def _code_example_note(name, slug, missing, CM):
        if missing:
            return ("added the example %s as modes/%s with its code. Its clip, picture, music and "
                    "calls are cut from your copy of %s, which was not found, so for now it plays "
                    "the game's own sounds on a plain panel. Press Cut film assets… and pick the "
                    "folder that holds the film%s." % (name, slug, CM.missing_words(missing),
                                                       "s" if len(missing) > 1 else ""))
        return ("added the example %s as modes/%s: its code, and its own clip, picture, music and "
                "calls cut from the films. Try it builds it in; Write puts it on the card."
                % (name, slug))

    def _on_code_example(self, name):
        from ..plugins.stern import code_modes as CM
        project = self.project()
        ex = CM.example(name)
        if not project or ex is None:
            return self.add_code_example(name)
        dirs = CM.film_dirs(project)
        missing = [k for k in CM.recipe_films(ex) if not CM.find_film(k, dirs)]
        extra = []
        if missing:
            got = self._ask_films_dir("Where are the films? %s's assets are cut from %s"
                                      % (name, CM.missing_words(missing)))
            if got:
                extra = [got]
        return self.add_code_example(name, dirs=extra)

    def recut_code_modes(self, dirs, wait=False):
        """Cut every code-mode example of the project again from the films in *dirs*. Returns the
        worker thread."""
        from ..plugins.stern import code_modes as CM
        project = self.project()
        if not project:
            return None
        try:
            code = [(s, c) for s, c in CM.list_code(project) if (c.film or {}).get("recipe")]
        except CM.CodeModeError as e:
            self._tryit_note(str(e))
            return None
        if not code:
            self._tryit_note("no code mode here has a film recipe to cut from.")
            return None
        ffmpeg = self._ffmpeg_path()

        def work():
            done, left = [], {}
            for slug, spec in code:
                try:
                    missing = CM.recut_example(project, slug, list(dirs) + CM.film_dirs(project),
                                               ffmpeg=ffmpeg, log=lambda m, *a: self._say(m))
                except Exception as e:                      # noqa: BLE001
                    self._tryit_note("%s could not be cut: %s" % (spec.name, e))
                    continue
                if missing:
                    left[spec.name] = missing
                else:
                    done.append(spec.name)
            words = []
            if done:
                words.append("cut the film assets of %s" % ", ".join(done))
            for n, m in left.items():
                words.append("%s needs %s, which is not in that folder" % (n, CM.missing_words(m)))
            self._tryit_note("; ".join(words) + ".")

        t = threading.Thread(target=work, daemon=True)
        t.start()
        if wait:
            t.join()
            self._tryit_flush()
            self._refresh_code_modes(project)
        else:
            self._tryit_watch(t.is_alive)
            self._code_refresh_later(t)
        return t

    def _on_cut_films(self):
        if not self.project():
            self._tryit_note("open or extract a card project first: modes live in it.")
            return None
        got = self._ask_films_dir("Pick the folder that holds the Godzilla films")
        if not got:
            return None
        return self.recut_code_modes([got])

    def _build_stock_modes_section(self, frame):
        from ..plugins.stern import stock_modes as SM
        self._SM = SM
        box = ttk.LabelFrame(frame, text=" The game's own modes ")
        box.pack(fill=tk.X, padx=10, pady=(4, 0))
        self._stock_box = box
        head = ttk.Frame(box)
        head.pack(fill=tk.X, padx=6, pady=(2, 2))
        self._stock_msg = ttk.Label(head, text="", wraplength=900, justify=tk.LEFT)
        self._stock_msg.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._tip(self._stock_msg, self.STOCK_TIP)

        body = ttk.Frame(box)
        body.pack(fill=tk.X, padx=6, pady=2)
        cols = ("number", "value", "stock", "where")
        tree = ttk.Treeview(body, columns=cols, height=6, selectmode="browse")
        tree.heading("#0", text="Mode", anchor=tk.W)
        tree.column("#0", width=250, stretch=False)
        for c, title, width in (("number", "Number", 180), ("value", "Value", 110),
                                ("stock", "Stock", 110), ("where", "Where it lives", 300)):
            tree.heading(c, text=title, anchor=tk.W)
            tree.column(c, width=width, stretch=(c == "where"))
        sb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        tree.bind("<<TreeviewSelect>>", lambda _e: self._on_stock_select())
        self._stock_tree = tree

        ctl = ttk.Frame(box)
        ctl.pack(fill=tk.X, padx=6, pady=(2, 6))
        ttk.Label(ctl, text="New value").pack(side=tk.LEFT)
        self._stock_value = tk.StringVar(value="")
        self._stock_entry = ttk.Entry(ctl, width=14, textvariable=self._stock_value)
        self._stock_entry.pack(side=tk.LEFT, padx=(6, 4))
        self._stock_entry.bind("<Return>", lambda _e: self._on_stock_set())
        self._stock_set_btn = ttk.Button(ctl, text="Set", width=6, command=self._on_stock_set)
        self._stock_set_btn.pack(side=tk.LEFT)
        self._stock_reset_btn = ttk.Button(ctl, text="Stock", width=7, command=self._on_stock_reset)
        self._stock_reset_btn.pack(side=tk.LEFT, padx=(4, 0))
        self._tip(self._stock_reset_btn, "Put the selected number back to the game's own value.")
        self._stock_all_btn = ttk.Button(ctl, text="All to stock", command=self._on_stock_all)
        self._stock_all_btn.pack(side=tk.LEFT, padx=(12, 0))
        self._stock_note = ttk.Label(ctl, text="", wraplength=560, justify=tk.LEFT)
        self._stock_note.pack(side=tk.LEFT, padx=(12, 0), fill=tk.X, expand=True)
        self._stock_rows = {}          # tree iid -> Number
        self._stock_build = None
        box.bind("<Map>", lambda _e: self.refresh_stock_modes(), add="+")
        self.refresh_stock_modes()

    def _stock_project(self):
        return self.project()

    def refresh_stock_modes(self):
        """Re-read the project's table and staged values into the list."""
        if getattr(self, "_stock_tree", None) is None:
            return
        SM = self._SM
        tree = self._stock_tree
        keep = tree.selection()
        tree.delete(*tree.get_children())
        self._stock_rows = {}
        project = self._stock_project()
        build = SM.table_for_project(project) if project else None
        self._stock_build = build
        if not project:
            self._stock_msg.configure(text="Open or extract a card project first (Extract tab) - "
                                           "changes to the game's own modes are saved in it.")
            self._stock_controls(False)
            return
        if build is None:
            pb = SM.project_build(project)
            known = ", ".join(b.id for b in SM.tables())
            self._stock_msg.configure(
                text="The app doesn't know the timers and awards of %s's own modes yet (it "
                     "knows %s)." % ("%s %s" % pb if pb else "this project's game", known))
            self._stock_controls(False)
            return
        rec = SM.staged(project)
        from ..core import staged_changes
        settings = staged_changes.load(project).get(SM.SETTINGS_KEY) or {}
        other_build = rec["build"] not in (None, build.id)
        seen_adj = set()
        n_changed = 0
        for num in build.numbers:
            if not num.is_player_facing:
                continue
            if num.kind == "adj":
                if num.adj_name in seen_adj:
                    continue
                seen_adj.add(num.adj_name)
            staged = None
            if num.is_adjustment and num.adj_name in settings:
                staged = settings[num.adj_name]
            elif num.is_word and not other_build and num.row_key in rec["values"]:
                staged = rec["values"][num.row_key]
            stock = "?" if num.value is None else format(num.value, ",")
            if not num.editable:
                value = stock
                where = "%s (read-only)" % num.where_text()
            else:
                value = format(int(staged), ",") + "  ●" if staged is not None else stock
                where = num.where_text()
            if staged is not None:
                n_changed += 1
            tree.insert("", tk.END, iid=num.row_key, text=build.mode_name(num.mode_id),
                        values=(build.row_label(num), value, stock, where),
                        tags=("changed",) if staged is not None else
                        (("readonly",) if not num.editable else ()))
            self._stock_rows[num.row_key] = num
        th = THEMES.get(self._theme_fn(), THEMES["dark"])
        try:
            tree.tag_configure("readonly", foreground=th.get("muted", th.get("fg")))
        except (tk.TclError, KeyError):
            pass
        msg = ("%s: %d number(s) of the game's own modes. %s" % (
            build.id, len(self._stock_rows),
            "%d change(s) staged for the next Write." % n_changed if n_changed else
            "Nothing changed - every number is the game's own."))
        if other_build and rec["values"]:
            msg += (" %d change(s) were staged for %s, not this card, and are not written."
                    % (len(rec["values"]), rec["build"]))
        self._stock_msg.configure(text=msg + " Rename a mode on the Text tab.")
        self._stock_controls(True)
        for iid in keep:
            if tree.exists(iid):
                tree.selection_set(iid)
                tree.see(iid)
        self._on_stock_select()

    def _stock_controls(self, on):
        for w in (self._stock_entry, self._stock_set_btn, self._stock_reset_btn, self._stock_all_btn):
            try:
                w.configure(state=tk.NORMAL if on else tk.DISABLED)
            except tk.TclError:
                pass
        if not on:
            self._stock_note.configure(text="")

    def _stock_selected(self):
        sel = self._stock_tree.selection()
        return self._stock_rows.get(sel[0]) if sel else None

    def _on_stock_select(self):
        num = self._stock_selected()
        if num is None:
            self._stock_note.configure(text="")
            return
        why = num.why_read_only()
        state = tk.DISABLED if why else tk.NORMAL
        for w in (self._stock_entry, self._stock_set_btn, self._stock_reset_btn):
            w.configure(state=state)
        if why:
            self._stock_value.set("")
            self._stock_note.configure(text="Read-only: %s." % why)
            return
        cur = self._stock_tree.set(num.row_key, "value").replace("●", "").strip()
        self._stock_value.set(cur)
        if num.is_adjustment:
            rng = num.adj_range
            self._stock_note.configure(
                text="An operator setting (%s)%s: the same number as on the Defaults tab. A "
                     "machine still on the game's default takes the new one when it boots."
                     % (num.adj_name, ", %d to %d" % rng if rng else ""))
        else:
            self._stock_note.configure(
                text="One word in the game program (%s)%s." % (
                    num.where(), "; it is shared by %d modes, so changing it changes all of them" % num.shared
                    if num.shared else ""))

    def stage_stock_value(self, row_key, value):
        """Stage *value* for the row; returns the message shown (the tests call this)."""
        SM = self._SM
        num = self._stock_rows.get(row_key)
        build = self._stock_build
        if num is None or build is None:
            return ""
        try:
            got = SM.stage(self._stock_project(), build, num, value)
        except SM.StockModeError as e:
            self._stock_note.configure(text=str(e))
            return str(e)
        label = "%s %s" % (build.mode_name(num.mode_id), build.row_label(num).lower())
        if got is None:
            text = "%s is back to the game's own %s." % (label, format(num.value, ","))
        else:
            text = "%s: %s -> %s staged for the next Write." % (
                label, format(num.value, ","), format(got, ","))
        self._say(text)
        if num.is_adjustment and self._settings_staged_fn is not None:
            try:
                self._settings_staged_fn(num.adj_name)
            except Exception:                    # the Defaults form is a courtesy
                pass
        self.refresh_stock_modes()
        self._stock_note.configure(text=text)
        return text

    def _on_stock_set(self):
        num = self._stock_selected()
        if num is not None:
            self.stage_stock_value(num.row_key, self._stock_value.get())

    def _on_stock_reset(self):
        num = self._stock_selected()
        if num is not None and num.editable:
            self.stage_stock_value(num.row_key, num.value)

    def _on_stock_all(self):
        build = self._stock_build
        project = self._stock_project()
        if build is None or not project:
            return
        n = self._SM.unstage_all(project, build)
        self._say("the game's own modes: %d change(s) put back to stock" % n)
        if self._settings_staged_fn is not None:
            for name in build.adjustment_numbers():
                try:
                    self._settings_staged_fn(name)
                except Exception:
                    pass
        self.refresh_stock_modes()
        self._stock_note.configure(text="Every number is back to the game's own (%d change(s) "
                                        "undone)." % n)
