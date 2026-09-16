"""Modes tab — choreograph a game mode of our own and play it in the emulator.

WHAT A MODE IS HERE.  Not code: a FILE.  Item 126 turned ``mode.so`` into an
interpreter over a mode file — the trigger, the clock, the shots that score and
what they pay, the screens, the lights and the callouts all come out of it — and
the object re-reads that file twice a second.  So an edit made here lands in a
RUNNING game inside a second, which is the whole reason this is an editor and
not a form you submit.

WHY ITS OWN TAB.  The Emulate tab runs a card; this one authors a mode and asks
that rig to play it.  They are different jobs on different objects, and item
125's rules (``tools/spike2_emu/modes/MODE_API.md``) are Spike 2's, so the tab
is gated by its own ``modes`` capability rather than riding on ``emulate``.

WHAT THE PANEL IS AND IS NOT.  It owns the mode file and the words on screen.
It does NOT own the rig: launching, stopping and reporting a run belong to the
Emulate panel, and this tab reaches the rig only to copy the mode file in and to
ask for a run with ``PAD_MODE_SO`` set — through :mod:`._rig`, the same seam
every other tab uses, because ``wsl.exe`` re-parses its arguments and ``$var``
expands to nothing on that second pass.

THE FILE FORMAT is key-per-line, not JSON, and that is a constraint from the
other end: ``mode.so`` is built ``-nostdlib`` with libc declared by hand, with
no allocator and no ``stat``.  It parses against fixed buffers, and an unknown
key is logged and skipped — so this tab may write a key an older ``mode.so``
has never heard of without breaking it.
"""

import os
import pathlib
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import _rig
from .widgets import _Tooltip

#: The mode files that ship with the rig, and where a user's own live.
DEFAULT_MODES_DIR = str(
    pathlib.Path(__file__).resolve().parents[2]
    / "tools" / "spike2_emu" / "modes"
)

#: Where the running guest reads its mode from.  The rig's dump directory is
#: already the channel the mode triggers use (``/dump/mode.start``), so the mode
#: file rides the same rail rather than inventing a second one.
GUEST_MODE_FILE = "/dump/mode.cfg"


def modes_dir():
    return os.environ.get("PAD_MODES_DIR") or DEFAULT_MODES_DIR


class ModeFile:
    """One mode, as the file's keys and as values a form can bind to.

    PARSING IS DELIBERATELY FORGIVING, and in both directions.  The runtime
    logs an unknown key and carries on; so does this.  A file a person edited by
    hand, or one written by a newer build of the tab, must survive a round trip
    through this class with nothing silently dropped — so every line that is not
    a key this tab knows is KEPT, in order, and written back out untouched.

    That is why this is a list of lines and not a dict: a dict would quietly
    eat the comments that explain a mode to the next person to open it.
    """

    #: Keys whose value is a NUMBER (decimal, or 0x hex as the runtime accepts).
    NUM_KEYS = ("seconds", "award", "screen_type", "title_msg", "total_msg",
                "restore_after", "light_owner", "callout_count", "callout_end")

    #: Keys whose value is the REST OF THE LINE, verbatim.  A light command is
    #: full of dashes and digits and must not be tokenised on the way through.
    TEXT_KEYS = ("name", "title_words", "total_words", "light_on", "light_off")

    def __init__(self, lines=()):
        self.lines = list(lines)

    # ---- reading ---------------------------------------------------------
    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return cls(f.read().splitlines())

    def get(self, key, default=""):
        """The value of *key*, or *default*.  The LAST one wins, which is what
        the runtime does too: it parses top to bottom and overwrites."""
        found = default
        for line in self.lines:
            k, v = self._split(line)
            if k == key:
                found = v
        return found

    def get_int(self, key, default=0):
        v = self.get(key, "")
        try:
            return int(v, 0) if v else default
        except ValueError:
            return default

    # ---- writing ---------------------------------------------------------
    def set(self, key, value):
        """Set *key*, in place if it is already there, appended if not.

        In place matters: a mode file is commented, and moving a key away from
        the comment that explains it makes the file worse every time it is
        saved.
        """
        text = "%-14s %s" % (key, value)
        for i, line in enumerate(self.lines):
            k, _v = self._split(line)
            if k == key:
                self.lines[i] = text
                return
        self.lines.append(text)

    def save(self, path):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.lines).rstrip("\n") + "\n")

    # ---- the one place that knows the grammar ----------------------------
    @staticmethod
    def _split(line):
        """``(key, value)`` for a data line, ``(None, None)`` for anything
        else.  Blank lines and ``#`` comments are not data; neither is an
        indented line, because the format has no continuations."""
        if not line or line[:1].isspace():
            return None, None
        s = line.strip()
        if not s or s.startswith("#"):
            return None, None
        parts = s.split(None, 1)
        return parts[0], (parts[1].strip() if len(parts) > 1 else "")


class ModesPanel:
    """The Modes tab's widgets, and the two things it asks of the rig.

    IT DOES NOT OWN THE RIG.  Starting, stopping and reporting a run belong to
    the Emulate panel; this one edits a mode and asks that a running guest be
    given it.  Install is therefore a file copy into the guest's dump directory
    and nothing more - which is also why it works while a game is up, instead of
    needing one to be restarted around it.
    """

    #: What this tab's lines are tagged with in the app's shared Log, so they
    #: read beside the other tabs' ("[emulate] ...", "[multi-boot] ...").
    LOG_TAG = "[modes] "

    ABOUT_TIP = (
        "Choreographs a game mode of your own and plays it in the emulator: "
        "what starts it, how long it runs, which shots score and what they "
        "pay, the words on the display, the lights and the callouts. A mode "
        "is a FILE, and the running game re-reads it twice a second - so "
        "Install while a game is up and the change lands in about a second, "
        "without restarting anything. The mode runs on the game's own calls "
        "(its scoring, its light runner, its callouts), so it behaves like a "
        "mode the game shipped with.")

    #: The fields the form binds, in the order they are shown.  Each is
    #: ``(key, label, kind, tip)``; ``kind`` picks the widget and the validator.
    FIELDS = (
        ("name", "Name", "text",
         "What the mode is called. It appears in the run's log, and the tab "
         "lists modes by it."),
        ("trigger", "Starts on", "mask",
         "The shot that starts it, as the game's own shot mask, and how many "
         "of them in one ball. 0x08000000 3 is 'the Maser Target, three "
         "times'. The switch-to-shot-bit map is in MODE_API.md."),
        ("seconds", "Runs for", "int",
         "Seconds. The mode keeps its own clock on the game's 60 Hz tick, "
         "because every one of the game's 30 timers is already taken."),
        ("shots", "Shots that score", "mask",
         "A shot mask: which shots pay while the mode runs. 0x70300000 is the "
         "three powerline targets and both ramps."),
        ("award", "First shot pays", "int",
         "Points for the first shot. The Nth shot pays N times this, so "
         "1000000 pays 1M, 2M, 3M and up. The game's own scoring is used, so "
         "the playfield multiplier applies exactly as it does to its shots."),
        ("title_words", "Title on screen", "text",
         "The words shown while the mode runs. They go behind a message id "
         "the display already knows (below), for as long as the mode lasts."),
        ("total_words", "Total on screen", "text",
         "The words shown with the total when the mode ends."),
        ("light_on", "Lights on", "text",
         "The light command run at the start, in the game's own light "
         "language. It only lights anything if a show event is live, which "
         "the runtime arranges."),
        ("light_off", "Lights off", "text",
         "The light command run at the end - usually a fade back to black."),
        ("callout_end", "Callout at the end", "int",
         "The sound played when time runs out, by the game's own callout id."),
    )

    def __init__(self, parent, log=None, theme_fn=None, badge_fn=None,
                 resize_fn=None, rig_cmd_fn=None, dump_dir_fn=None,
                 emulate_fn=None):
        self._parent = parent
        self._log = log
        self._theme_fn = theme_fn or (lambda: "dark")
        self._badge_fn = badge_fn
        self._resize_fn = resize_fn
        #: How this tab reaches the rig.  Injected rather than imported so a
        #: test can drive the panel without WSL anywhere near it - the same
        #: reason the other panels take their seams as callables.
        self._rig_cmd = rig_cmd_fn or self._default_rig_cmd
        self._dump_dir = dump_dir_fn or (lambda: "")
        #: "Play it" is the Emulate panel's launch, not a second launcher.
        self._emulate_fn = emulate_fn
        self._path = ""
        self._mode = ModeFile()
        self._vars = {}
        self._status = None
        #: Asked of the rig once (see :meth:`dump_dir`): it costs a ~200 ms
        #: round trip and cannot change while the app is up.
        self._dump_cache = None

    # ---- the rig seam ----------------------------------------------------
    @staticmethod
    def _default_rig_cmd(script, *args, env=()):
        rig = str(pathlib.Path(modes_dir()).parent)
        return _rig.rig_cmd(rig, script, *args, env=env)

    def dump_dir(self):
        """Where a running guest reads its mode file from, ASKED OF THE RIG.

        ``padpath.sh`` already owns every rig path, and it works out whose rig
        this is rather than trusting ``$HOME`` - which under ``wsl -u root`` is
        ``/root``, where no rig has ever lived.  Reproducing any of that here
        would be a second definition of one fact, which is the mistake the
        rig's own rules were written about.  So: source it, echo the answer.
        """
        if self._dump_cache is not None:
            return self._dump_cache
        cmd = self._rig_cmd("padpath.sh")
        # padpath.sh is a library, not a command - it is sourced.  Run a shell
        # that sources it and prints the one path wanted.
        cmd = list(cmd[:-2]) + ["bash", "-c",
                                'set -e; . "$0"; printf %s "$ROOT/dump"',
                                cmd[-1]]
        try:
            out = subprocess.run(cmd, check=True, capture_output=True,
                                 text=True, creationflags=_rig.CREATE_FLAGS)
        except (OSError, subprocess.CalledProcessError):
            return ""
        self._dump_cache = (out.stdout or "").strip()
        return self._dump_cache

    def install_cmd(self, path):
        """The command that puts *path* where the running guest reads it.

        A plain copy: the guest polls ``mode.cfg`` twice a second, so arriving
        is all that is needed - which is why this works while a game is up.
        ``cp`` rather than a shell redirect because ``wsl.exe`` re-parses its
        argument line and a redirect would be read on the wrong side of it.
        """
        dump = self._dump_dir() or self.dump_dir()
        if not dump:
            return []
        if os.name == "nt":
            return ["wsl.exe", "-e", "cp", _rig.wsl_path(path),
                    dump + "/mode.cfg"]
        return ["cp", path, dump + "/mode.cfg"]

    def install(self):
        """Copy the current mode to the guest.  Returns a status string."""
        if not self._path:
            return "Save the mode first."
        cmd = self.install_cmd(self._path)
        if not cmd:
            return "No rig to install into - start a run on the Emulate tab."
        try:
            subprocess.run(cmd, check=True, capture_output=True,
                           creationflags=_rig.CREATE_FLAGS)
        except (OSError, subprocess.CalledProcessError) as e:
            return "Could not install it: %s" % e
        self._say("installed %s into the running rig" % os.path.basename(self._path))
        return ("Installed. The game re-reads it within a second, so a mode "
                "already running picks it up as it goes.")

    def _say(self, text):
        if self._log:
            self._log(self.LOG_TAG + text)

    # ---- the mode on disk -------------------------------------------------
    def available(self):
        """Every ``*.mode`` the tab can open, newest name order."""
        d = modes_dir()
        try:
            return sorted(f for f in os.listdir(d) if f.endswith(".mode"))
        except OSError:
            return []

    def open_mode(self, path):
        """Load *path* into the form.  Unknown lines ride along untouched."""
        self._mode = ModeFile.load(path)
        self._path = path
        for key, var in self._vars.items():
            var.set(self._mode.get(key, ""))
        self._say("opened %s" % os.path.basename(path))

    def collect(self):
        """Push the form back into the mode file and return it."""
        for key, var in self._vars.items():
            value = (var.get() or "").strip()
            if value:
                self._mode.set(key, value)
        return self._mode

    def save(self):
        if not self._path:
            return "Nowhere to save it yet."
        self.collect().save(self._path)
        self._say("saved %s" % os.path.basename(self._path))
        return "Saved."

    # ---- the widgets ------------------------------------------------------
    def build(self, frame):
        """Build the tab.  A form, not a timeline: every field is one line of
        the mode file, and the file is the thing being edited."""
        top = ttk.Frame(frame)
        top.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(top, text="Mode:").pack(side=tk.LEFT)
        self._pick = ttk.Combobox(top, state="readonly", width=32,
                                  values=self.available())
        self._pick.pack(side=tk.LEFT, padx=(6, 0))
        self._pick.bind("<<ComboboxSelected>>", lambda _e: self._on_pick())
        ttk.Button(top, text="Open…", command=self._on_open).pack(
            side=tk.LEFT, padx=(6, 0))
        if self._badge_fn is not None:
            badge = self._badge_fn("?")
            if badge is not None:
                lbl = ttk.Label(top, image=badge)
                lbl.image = badge
                lbl.pack(side=tk.LEFT, padx=(8, 0))
                _Tooltip(lbl, self.ABOUT_TIP)

        form = ttk.Frame(frame)
        form.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        form.columnconfigure(1, weight=1)
        for row, (key, label, _kind, tip) in enumerate(self.FIELDS):
            ttk.Label(form, text=label + ":").grid(
                row=row, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar()
            self._vars[key] = var
            entry = ttk.Entry(form, textvariable=var)
            entry.grid(row=row, column=1, sticky=tk.EW, padx=(6, 0), pady=2)
            _Tooltip(entry, tip)

        row = ttk.Frame(frame)
        row.pack(fill=tk.X, padx=10, pady=(4, 10))
        ttk.Button(row, text="Save", command=self._on_save).pack(side=tk.LEFT)
        # INSTALL IS NOT A BUILD.  It copies the file to the running guest,
        # which re-reads it twice a second - so this is the button that makes
        # the tab an editor rather than a form.
        ttk.Button(row, text="Install into the running game",
                   command=self._on_install).pack(side=tk.LEFT, padx=(6, 0))
        if self._emulate_fn is not None:
            ttk.Button(row, text="Play it…",
                       command=self._emulate_fn).pack(side=tk.LEFT, padx=(6, 0))
        self._status = ttk.Label(frame, text="", wraplength=620,
                                 justify=tk.LEFT)
        self._status.pack(fill=tk.X, padx=10, pady=(0, 10))

        modes = self.available()
        if modes:
            self._pick.set(modes[0])
            self._on_pick()

    # ---- what the buttons do ---------------------------------------------
    def _set_status(self, text):
        if self._status is not None:
            self._status.configure(text=text)

    def _on_pick(self):
        name = self._pick.get()
        if name:
            self.open_mode(os.path.join(modes_dir(), name))
            self._set_status("")

    def _on_open(self):
        path = filedialog.askopenfilename(
            title="Open a mode", initialdir=modes_dir(),
            filetypes=[("Mode files", "*.mode"), ("All files", "*.*")])
        if path:
            self.open_mode(path)

    def _on_save(self):
        self._set_status(self.save())

    def _on_install(self):
        self.save()
        self._set_status(self.install())
