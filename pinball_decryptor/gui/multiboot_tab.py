"""Multi-boot tab - one Spike 2 SD card, several game images, a menu at
power-up (item 90), set up and built from the app.

The pieces it drives already exist, and they are the ONLY places that know
how a multi-image card is put together:

* ``tools/spike2_emu/selectmedia.py prepare`` renders the menu's media - a
  picture (or an animated GIF) per image, the move / confirm sounds, an
  optional music loop - into one flat directory with a ``media.json``.
* ``tools/spike2_emu/mkmulticard.py`` plans, builds and verifies the card,
  and on an existing card applies the validator bypass (``bypass --card``).

This module is a control surface for those two tools and nothing more: it
collects the form, turns it into command lines (PURE functions, so the tests
can read the argv without WSL), streams the tools' stdout into a pane on the
tab, and hands the finished image to the app's own Build / flash flow or to
the Emulate tab.  It deliberately reimplements none of the layout arithmetic,
the media budgets or the validation - a second copy of any of them is how two
tools come to disagree about one card (the rig's own hardest-won rule).

WHERE THE TOOLS RUN.  Both are Linux programs (debugfs, mke2fs, ffmpeg, the
ext4 reader) and are reached the way the Emulate tab reaches the rig: through
``wsl.exe`` on Windows, directly on a Linux desktop.  Windows paths cross the
boundary through :func:`.._rig.wsl_path`, the app's one spelling of that
translation.  The command line is ``bash -lc 'cd <checkout> && python3
tools/spike2_emu/<tool>.py ...'`` with every argument shell-quoted: the tools
import ``pinball_decryptor`` (the validator bypass uses plugins/stern/valpatch
and sidx), so they run from the checkout root.  ``$`` and backticks are
refused in titles rather than escaped - ``wsl.exe`` re-parses its argument
line and both expand to nothing on that second pass (the JJP executor's
lesson), and no quoting from this side survives that.

WHAT IS NOT HERE.  No probe runs when the tab is built, no path is guessed
from the Input box, and no two tool runs overlap: a build copies ~7 GB per
image and the tab is busy until the run has said PASS or FAIL.
"""

import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, ttk

from . import _rig
from .emulate_tab import rig_dir
from .theme import THEMES, platform_font
from .widgets import _Tooltip

#: The two tools, relative to the checkout root the command line cd's into.
TOOL_DIR = "tools/spike2_emu"
MKMULTICARD = TOOL_DIR + "/mkmulticard.py"
SELECTMEDIA = TOOL_DIR + "/selectmedia.py"

#: Where the rig installs the ARM selector (buildselect.sh's ``make install
#: DESTDIR=$ROOT``, ROOT = PAD_ROOT else ~/spike2root).  A WSL path, spelled
#: with ``~`` on purpose: the app cannot know the WSL user's home without a
#: probe, and ``~/`` is expanded by bash without a ``$`` for wsl.exe to eat.
DEFAULT_SELECTOR_DIR = "~/spike2root/usr/local/codeselect"

#: David's card library - never an output (mkmulticard.py refuses the same
#: prefixes after resolving links; the repo's own images/ is a junction into
#: it).  Both spellings, because the form holds Windows paths and the tool
#: sees WSL ones.  tests/test_multiboot_tab.py pins this to the tool's list.
LIBRARY_PREFIXES = ("D:/Pinball/images", "/mnt/d/Pinball/images")

#: images.conf v2 carries up to 16 images.
MAX_IMAGES = 16

#: The non-file choices each media field accepts.  Anything else is a path.
ART_CHOICES = ("auto", "none")
ANIM_CHOICES = ("none", "auto")
MUSIC_CHOICES = ("none",)
SOUND_CHOICES = ("auto", "synth", "none")
_WORDS = frozenset(("auto", "none", "synth"))


# ---------------------------------------------------------------------------
# the form
# ---------------------------------------------------------------------------

@dataclass
class ImageRow:
    """One image on the card.  Index 0 is the primary (its p1/p2/p3/p5/p6 are
    the card's; the machine boots it when the menu is not honoured)."""
    path: str
    title: str = ""
    subtitle: str = ""
    art: str = "auto"        # auto | none | <png/jpg file>
    anim: str = "none"       # none | auto (the attract clip) | <gif/mp4/mov>
    music: str = "none"      # none | <wav file>


@dataclass
class MultibootForm:
    images: list = field(default_factory=list)
    out: str = ""
    sound_move: str = "auto"       # auto | synth | none | <wav>
    sound_confirm: str = "auto"
    volume: int = 50
    timeout: int = 15              # 0 = wait for START
    default: int = 0
    bypass: bool = True
    media_dir: str = ""            # a prepared media dir (holds media.json)
    selector_dir: str = DEFAULT_SELECTOR_DIR
    force: bool = False


def is_file_choice(value):
    """Whether a media field holds a path rather than one of the words."""
    v = (value or "").strip()
    return bool(v) and v.lower() not in _WORDS


def suggest_title(path):
    """``turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw`` ->
    ``('turtles_pro-1_59_0', '1987-upscaled')``: the menu title and subtitle
    a fresh row starts with.  A suggestion, not a fact - the user renames."""
    b = os.path.basename(path or "")
    b = re.sub(r"\.(raw|img|bin|iso)$", "", b, flags=re.I)
    b = re.sub(r"\.\d+G\.sdcard$", "", b, flags=re.I)
    b = re.sub(r"\.sdcard$", "", b, flags=re.I)
    head, _, tail = b.partition(".")
    return head, tail


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def wsl(path):
    """A form path as the tools see it (``D:\\x`` -> ``/mnt/d/x``)."""
    return _rig.wsl_path(path)


def repo_dir():
    """The checkout the rig sits in: ``rig_dir()`` is <repo>/tools/spike2_emu,
    and the tools are run from <repo> so ``pinball_decryptor`` imports."""
    return os.path.dirname(os.path.dirname(os.path.normpath(rig_dir())))


def _norm(p):
    """mkmulticard.py's own normalisation: absolute, link-resolved, forward
    slashes, lower case; an output that does not exist yet has its parent
    resolved and the basename re-joined."""
    a = os.path.abspath(p)
    if os.path.exists(a):
        r = os.path.realpath(a)
    else:
        r = os.path.join(os.path.realpath(os.path.dirname(a)),
                         os.path.basename(a))
    return os.path.normpath(r).replace("\\", "/").lower()


def under_library(path):
    """Whether *path* lies in the card library nothing may write into."""
    if not path:
        return False
    n = _norm(path)
    for pre in LIBRARY_PREFIXES:
        pn = _norm(pre)
        if n == pn or n.startswith(pn + "/"):
            return True
    return False


def default_output_path(primary):
    """``<dir of primary>/multi/<primary basename>.multi.raw`` - and when the
    primary lives IN the library (David's stock cards do), the first folder
    above it that is not: ``D:/Pinball/images/Stern/spike2/x.raw`` ->
    ``D:/Pinball/multi/x.multi.raw``.  A default the tool would refuse is
    no default."""
    d = os.path.dirname(os.path.abspath(primary))
    while under_library(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    base = os.path.basename(primary)
    stem = re.sub(r"\.(raw|img)$", "", base, flags=re.I)
    return os.path.join(d, "multi", stem + ".multi.raw")


def media_dir_for(out):
    """Where 'Prepare media' renders for an output: ``<out dir>/media``."""
    out = (out or "").strip()
    return os.path.join(os.path.dirname(os.path.abspath(out)), "media") \
        if out else ""


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

_BAD_TEXT = re.compile(r"[|;$`]")


def validate_form(form):
    """Every reason the form cannot be built, as sentences for the tab.
    Empty = build it.  The tool re-checks all of it; this is so a bad form is
    a line on the tab and not a traceback in the log pane."""
    errs = []
    n = len(form.images)
    if n < 2:
        errs.append("Add at least two images: the primary (stock) and one "
                    "more.")
    if n > MAX_IMAGES:
        errs.append("At most %d images fit one card." % MAX_IMAGES)
    seen = set()
    for i, row in enumerate(form.images):
        p = (row.path or "").strip().strip('"')
        if not p:
            errs.append("Image %d has no file." % i)
        elif not os.path.isfile(p):
            errs.append("Image %d: no such file: %s" % (i, p))
        else:
            key = _norm(p)
            if key in seen:
                errs.append("Image %d is listed twice: %s" % (i, p))
            seen.add(key)
        for what, text in (("title", row.title), ("subtitle", row.subtitle)):
            if _BAD_TEXT.search(text or ""):
                errs.append("Image %d: the %s must not contain | ; $ or `."
                            % (i, what))
        for what, val in (("art", row.art), ("animation", row.anim),
                          ("music", row.music)):
            if is_file_choice(val) and not os.path.isfile(val.strip()):
                errs.append("Image %d: %s file not found: %s"
                            % (i, what, val))
    for what, val in (("move sound", form.sound_move),
                      ("confirm sound", form.sound_confirm)):
        if is_file_choice(val) and not os.path.isfile(val.strip()):
            errs.append("The %s file was not found: %s" % (what, val))
    if not 0 <= int(form.volume) <= 100:
        errs.append("Volume is 0-100.")
    if int(form.timeout) < 0:
        errs.append("The countdown cannot be negative (0 = wait for START).")
    if n and not 0 <= int(form.default) < n:
        errs.append("The default image must be one of 0..%d." % (n - 1))
    out = (form.out or "").strip().strip('"')
    if not out:
        errs.append("Set the output .raw path.")
    else:
        if under_library(out):
            errs.append("The output must not be under the card library (%s) "
                        "- pick another folder." % LIBRARY_PREFIXES[0])
        if any(_norm(out) == _norm(r.path)
               for r in form.images if (r.path or "").strip()):
            errs.append("The output is one of the input images.")
    return errs


# ---------------------------------------------------------------------------
# command lines (pure)
# ---------------------------------------------------------------------------

def _media_value(value):
    """A media field for the tools: the word as is, a path in WSL form."""
    v = (value or "").strip().strip('"')
    return v.lower() if v.lower() in _WORDS else wsl(v)


def _image_args(form):
    args = ["--primary", wsl(form.images[0].path.strip().strip('"'))]
    for row in form.images[1:]:
        args += ["--extra", wsl(row.path.strip().strip('"'))]
    return args


def prepare_args(form, media_dir):
    """``selectmedia.py prepare``: the images (the tool pulls 'auto' art and
    clips off them), then ``--art/--anim/--music N=<value>`` for EVERY image
    - explicit rather than defaulted, so the form and the manifest cannot
    disagree about an index - then the globals.  Rendered into *media_dir*,
    which then holds media.json."""
    args = [SELECTMEDIA, "prepare"] + _image_args(form) + [
        "--out", wsl(media_dir)]
    for i, row in enumerate(form.images):
        args += ["--art", "%d=%s" % (i, _media_value(row.art)),
                 "--anim", "%d=%s" % (i, _media_value(row.anim)),
                 "--music", "%d=%s" % (i, _media_value(row.music))]
    args += ["--sound-move", _media_value(form.sound_move),
             "--sound-confirm", _media_value(form.sound_confirm),
             "--volume", str(int(form.volume))]
    return args


def plan_args(form):
    """``mkmulticard.py plan``: the layout and whether it fits 16G / 32G.
    Writes nothing."""
    return [MKMULTICARD, "plan"] + _image_args(form) + ["--layout", "auto"]


def build_args(form):
    """``mkmulticard.py build``.  ``--layout auto`` = today's p7 layout for
    one extra image, the img1/img2/... partition for more."""
    titles = [(r.title or "").strip() or suggest_title(r.path)[0]
              for r in form.images]
    subtitles = [(r.subtitle or "").strip() for r in form.images]
    args = [MKMULTICARD, "build"] + _image_args(form) + [
        "--out", wsl(form.out.strip().strip('"')),
        "--selector-dir", form.selector_dir or DEFAULT_SELECTOR_DIR,
        "--layout", "auto",
        "--titles", ";".join(titles),
        "--timeout", str(int(form.timeout)),
        "--default", str(int(form.default)),
        # The tab's knob is the volume of record: the same number goes into
        # media.json (prepare) and into images.conf here, so a text-only card
        # with no prepared media still carries it.
        "--volume", str(int(form.volume)),
    ]
    if any(subtitles):
        args += ["--subtitles", ";".join(subtitles)]
    if form.bypass:
        args.append("--bypass-validation")
    if form.media_dir:
        args += ["--media-dir", wsl(form.media_dir)]
    if form.force:
        args.append("--force")
    return args


def verify_args(form):
    """``mkmulticard.py verify``: every copied range against its source,
    every ext4 fsck'd, the injected files against the selector build, the
    bypass state of every games tree."""
    args = [MKMULTICARD, "verify", "--card",
            wsl(form.out.strip().strip('"'))] + _image_args(form)
    if form.selector_dir:
        args += ["--selector-dir", form.selector_dir]
    if form.media_dir:
        args += ["--media-dir", wsl(form.media_dir)]
    return args


def bypass_args(card):
    """``mkmulticard.py bypass --card``: the validator bypass on every games
    tree of an EXISTING card - what fixes a card already flashed without a
    rebuild."""
    return [MKMULTICARD, "bypass", "--card", wsl(card.strip().strip('"'))]


def _q(arg):
    """Shell-quote one argument, keeping a leading ``~/`` outside the quotes
    so bash still expands it (``~/'a b'`` is ``/home/x/a b``)."""
    if arg.startswith("~/"):
        return "~/" + shlex.quote(arg[2:])
    return shlex.quote(arg)


def shell_line(args, cwd):
    """``cd <cwd> && python3 <args...>``, every argument quoted."""
    return "cd %s && python3 %s" % (_q(cwd), " ".join(_q(a) for a in args))


def wsl_command(args, cwd=None):
    """The argv that runs one tool command line on THIS platform: through
    ``wsl.exe`` on Windows, ``bash`` on Linux.  *cwd* is the checkout root in
    WSL form (derived from the rig's location when not given)."""
    if cwd is None:
        cwd = wsl(repo_dir())
    line = shell_line(args, cwd)
    if sys.platform == "win32":
        return ["wsl.exe", "-e", "bash", "-lc", line]
    return ["bash", "-lc", line]


def build_commands(form, cwd=None):
    """The 'Build & verify' run: plan (the size, before a byte is written),
    build, verify.  ``[(label, argv), ...]``, run in order, stop on failure."""
    return [("plan", wsl_command(plan_args(form), cwd)),
            ("build", wsl_command(build_args(form), cwd)),
            ("verify", wsl_command(verify_args(form), cwd))]


def prepare_commands(form, media_dir, cwd=None):
    return [("prepare", wsl_command(prepare_args(form, media_dir), cwd))]


def plan_commands(form, cwd=None):
    return [("plan", wsl_command(plan_args(form), cwd))]


def bypass_commands(card, cwd=None):
    return [("bypass", wsl_command(bypass_args(card), cwd))]


# ---------------------------------------------------------------------------
# the size plan
# ---------------------------------------------------------------------------

_FITS_RE = re.compile(
    r"fits Stern\s+(\d+G)\s+image size\s+\d+:\s+(YES|NO)\s*\(spare\s+(-?\d+)\)")
_TOTAL_RE = re.compile(r"^image:\s+\d+\s+sectors\s+=\s+(\d+)\s+bytes")


def parse_plan(text):
    """What ``mkmulticard.py plan`` said about size: ``{"bytes": N or None,
    "fits": {"16G": (True, spare), ...}}``.  Only those lines - everything
    else the plan prints is for the log pane."""
    info = {"bytes": None, "fits": {}}
    for line in (text or "").splitlines():
        m = _FITS_RE.search(line)
        if m:
            info["fits"][m.group(1)] = (m.group(2) == "YES", int(m.group(3)))
        m = _TOTAL_RE.match(line.strip())
        if m:
            info["bytes"] = int(m.group(1))
    return info


def size_plan_text(info):
    """One sentence for the tab: the smallest Stern card size the image fits
    ('fits a 16 GB card', 'needs a 32 GB card'), or that none does."""
    fits = (info or {}).get("fits") or {}
    if not fits:
        return ""
    size = (info or {}).get("bytes")
    head = "Card image %.2f GB. " % (size / 1e9) if size else ""
    for key, word in (("8G", "Fits an 8 GB card"), ("16G", "Fits a 16 GB card"),
                      ("32G", "Needs a 32 GB card")):
        ok, spare = fits.get(key, (False, 0))
        if ok:
            return head + "%s (%.2f GB spare)." % (word, spare / 1e9)
    return head + "Does not fit a 32 GB card - drop an image."


# ---------------------------------------------------------------------------
# the panel
# ---------------------------------------------------------------------------

def _int(var, default):
    try:
        return int(str(var.get()).strip())
    except (ValueError, tk.TclError):
        return default


class MultibootPanel:
    """The Multi-boot tab's widgets and its one worker at a time."""

    #: Lines kept in the tab's own pane.  The app log keeps the rest.
    LOG_KEEP = 3000

    #: How often the main loop drains the worker's queue while a run is up.
    DRAIN_MS = 50

    BYPASS_TIP = ("Neuters the game's validator in EVERY image on the card "
                  "(a bx lr at validation_exec, and that image's .sidx "
                  "record refreshed). Needed so the machine's GAME "
                  "VALIDATION ERROR stays off: the two images share one "
                  "grade state, and the stock one fails it once a second "
                  "image is beside it. The same patch the Insider-clean "
                  "1987 card carries.")

    def __init__(self, parent, log=None, theme_fn=None, badge_fn=None,
                 resize_fn=None, flash_fn=None, emulate_fn=None):
        self._parent = parent
        self._log_sink = log or (lambda msg: None)
        self._theme_fn = theme_fn or (lambda: "dark")
        self._badge_fn = badge_fn
        self._resize_fn = resize_fn or (lambda: None)
        #: The app's Build / flash flow, handed the finished .raw.  None
        #: (a panel built on its own, every test) greys the button.
        self._flash_fn = flash_fn
        #: The Emulate tab's launch, handed the finished .raw: it sets the
        #: card, ticks Boot selector (PAD_SELECT=1) and starts the rig.
        self._emulate_fn = emulate_fn
        self._rows = []                 # list[ImageRow], card order
        self._busy = False
        self._proc = None
        self._stopped = False
        #: Worker -> main-loop handoff.  THE WORKER NEVER TOUCHES TK: it puts
        #: callables here and _drain, an ``after`` timer that runs only while
        #: a run is up, calls them.  Not ``widget.after(0, ...)`` from the
        #: thread, which is what the Emulate panel does: _tkinter only
        #: marshals a cross-thread call while the main thread is inside
        #: mainloop(), and raises "main thread is not in main loop" under
        #: anything else - an update() loop in a test, for one.
        self._queue = queue.Queue()
        self._drain_job = None
        self._loading = False           # editor <- row, not row <- editor
        self._out_auto_value = ""       # the last output path WE filled in
        self._plan_info = None
        self._out_var = tk.StringVar()
        self._move_var = tk.StringVar(value="auto")
        self._confirm_var = tk.StringVar(value="auto")
        self._volume_var = tk.StringVar(value="50")
        self._timeout_var = tk.StringVar(value="15")
        self._default_var = tk.StringVar(value="0")
        self._bypass_var = tk.BooleanVar(value=True)
        self._selector_var = tk.StringVar(value=DEFAULT_SELECTOR_DIR)
        self._ed_title = tk.StringVar()
        self._ed_sub = tk.StringVar()
        self._ed_art = tk.StringVar(value="auto")
        self._ed_anim = tk.StringVar(value="none")
        self._ed_music = tk.StringVar(value="none")
        for var in (self._ed_title, self._ed_sub, self._ed_art,
                    self._ed_anim, self._ed_music):
            var.trace_add("write", lambda *_a: self._editor_changed())

    # ------------------------------------------------------------------
    # plumbing shared with the Emulate panel
    # ------------------------------------------------------------------

    def _timer(self):
        """The widget ``after`` jobs hang off - the toplevel, which outlives
        every tab (see EmulatePanel._timer for the teardown reason)."""
        return self._parent.winfo_toplevel()

    def _ui(self, fn):
        """Queue *fn* for the Tk main loop, from any thread (see _queue)."""
        if not self._stopped:
            self._queue.put(fn)

    def _drain(self):
        """Main loop only: run what the worker queued, and come back while a
        run is up or anything is still queued."""
        self._drain_job = None
        if self._stopped:
            return
        for _ in range(1000):
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except tk.TclError:
                pass
        if self._busy or not self._queue.empty():
            try:
                self._drain_job = self._timer().after(self.DRAIN_MS,
                                                      self._drain)
            except tk.TclError:
                pass

    def _on_destroy(self, event=None):
        if event is not None and str(event.widget) != str(self._parent):
            return
        self._stopped = True
        if self._drain_job is not None:
            try:
                self._timer().after_cancel(self._drain_job)
            except (tk.TclError, ValueError):
                pass
            self._drain_job = None

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def build(self, frame):
        pad = {"padx": 10, "pady": 4}
        ttk.Label(
            frame, justify=tk.LEFT, wraplength=820,
            text=("Builds ONE SD card that carries several complete game "
                  "images and a menu at power-up: flippers choose, START "
                  "boots - stock code and a custom build on the same machine "
                  "without swapping cards.\n"
                  "The first image is the primary (its boot files are the "
                  "card's, and the machine falls back to it). Media and the "
                  "card are made by the rig's tools under WSL; nothing here "
                  "touches the images you pick.")).pack(anchor=tk.W, **pad)
        self._build_images(frame, pad)
        self._build_menu(frame, pad)
        self._build_output(frame, pad)
        self._build_actions(frame, pad)
        self._plan_lbl = ttk.Label(frame, justify=tk.LEFT, wraplength=820,
                                   text="")
        self._plan_lbl.pack(anchor=tk.W, **pad)
        self._hint = ttk.Label(frame, justify=tk.LEFT, wraplength=820,
                               foreground="#888", text="")
        self._hint.pack(anchor=tk.W, **pad)
        self._build_log(frame, pad)
        frame.bind("<Destroy>", self._on_destroy, add="+")
        self._set_busy(False)

    def _build_images(self, frame, pad):
        box = ttk.LabelFrame(
            frame, text="Images on the card (first = primary, the stock one)")
        box.pack(fill=tk.X, **pad)
        top = ttk.Frame(box)
        top.pack(fill=tk.X, padx=8, pady=(6, 2))
        cols = ("idx", "image", "title", "subtitle", "art", "anim", "music")
        self._tree = ttk.Treeview(top, columns=cols, show="headings",
                                  height=4, selectmode="browse")
        for col, head, width, stretch in (
                ("idx", "#", 28, False), ("image", "Image", 300, True),
                ("title", "Title", 130, False),
                ("subtitle", "Subtitle", 150, True),
                ("art", "Art", 70, False), ("anim", "Animation", 90, False),
                ("music", "Music", 80, False)):
            self._tree.heading(col, text=head)
            self._tree.column(col, width=width, stretch=stretch,
                              anchor=tk.W)
        sb = ttk.Scrollbar(top, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._load_editor())

        btns = ttk.Frame(box)
        btns.pack(fill=tk.X, padx=8, pady=2)
        self._add_btn = ttk.Button(btns, text="Add image…", width=12,
                                   command=self._add_image)
        self._add_btn.pack(side=tk.LEFT)
        self._remove_btn = ttk.Button(btns, text="Remove", width=9,
                                      command=self._remove_image)
        self._remove_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._up_btn = ttk.Button(btns, text="Up", width=6,
                                  command=lambda: self._move_image(-1))
        self._up_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._down_btn = ttk.Button(btns, text="Down", width=6,
                                    command=lambda: self._move_image(1))
        self._down_btn.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(btns, foreground="#888",
                  text="Select a row to edit its menu text and media below."
                  ).pack(side=tk.LEFT, padx=(16, 0))

        ed = ttk.Frame(box)
        ed.pack(fill=tk.X, padx=8, pady=(2, 6))
        ttk.Label(ed, text="Title:", width=10).grid(row=0, column=0,
                                                    sticky=tk.W, pady=2)
        self._ed_title_entry = ttk.Entry(ed, textvariable=self._ed_title,
                                         width=30)
        self._ed_title_entry.grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(ed, text="Subtitle:").grid(row=0, column=2, sticky=tk.W,
                                             padx=(12, 4), pady=2)
        ttk.Entry(ed, textvariable=self._ed_sub, width=44).grid(
            row=0, column=3, columnspan=3, sticky=tk.EW, pady=2)
        self._media_row(ed, 1, 0, "Art:", self._ed_art, ART_CHOICES,
                        [("Pictures", "*.png *.jpg *.jpeg")])
        self._media_row(ed, 1, 3, "Animation:", self._ed_anim, ANIM_CHOICES,
                        [("Animations", "*.gif *.mp4 *.mov")])
        self._media_row(ed, 2, 0, "Music:", self._ed_music, MUSIC_CHOICES,
                        [("WAV audio", "*.wav")])
        ttk.Label(ed, foreground="#888",
                  text="auto = the image's own logo / attract clip; "
                       "none = text only").grid(
            row=2, column=3, columnspan=3, sticky=tk.W, padx=(12, 0))
        ed.columnconfigure(5, weight=1)

    def _media_row(self, parent, row, col, label, var, choices, filetypes):
        """Label + editable combobox (the words, or a typed path) + Browse."""
        kw = {"width": 10} if col == 0 else {}
        ttk.Label(parent, text=label, **kw).grid(
            row=row, column=col, sticky=tk.W, padx=(0 if col == 0 else 12, 4),
            pady=2)
        cb = ttk.Combobox(parent, textvariable=var, values=list(choices),
                          width=24)
        cb.grid(row=row, column=col + 1, sticky=tk.W, pady=2)
        ttk.Button(parent, text="Browse…", width=9,
                   command=lambda: self._browse_media(var, filetypes)).grid(
            row=row, column=col + 2, sticky=tk.W, padx=(4, 0), pady=2)
        return cb

    def _build_menu(self, frame, pad):
        box = ttk.LabelFrame(frame, text="Menu")
        box.pack(fill=tk.X, **pad)
        g = ttk.Frame(box)
        g.pack(fill=tk.X, padx=8, pady=6)
        self._media_row(g, 0, 0, "Move sound:", self._move_var, SOUND_CHOICES,
                        [("WAV audio", "*.wav")])
        self._media_row(g, 0, 3, "Confirm sound:", self._confirm_var,
                        SOUND_CHOICES, [("WAV audio", "*.wav")])
        ttk.Label(g, foreground="#888",
                  text="auto = a click and a stinger pulled from the primary "
                       "image; synth = generated tones. The confirm sound "
                       "plays to the end before the game starts.").grid(
            row=1, column=0, columnspan=6, sticky=tk.W, pady=(0, 4))
        ttk.Label(g, text="Volume:", width=10).grid(row=2, column=0,
                                                    sticky=tk.W, pady=2)
        ttk.Spinbox(g, from_=0, to=100, width=5,
                    textvariable=self._volume_var).grid(
            row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(g, text="Countdown (s):").grid(row=2, column=3, sticky=tk.W,
                                                 padx=(12, 4), pady=2)
        cd = ttk.Frame(g)
        cd.grid(row=2, column=4, columnspan=2, sticky=tk.W, pady=2)
        ttk.Spinbox(cd, from_=0, to=600, width=5,
                    textvariable=self._timeout_var).pack(side=tk.LEFT)
        ttk.Label(cd, text="0 = wait for START", foreground="#888").pack(
            side=tk.LEFT, padx=(6, 0))
        ttk.Label(g, text="Default:", width=10).grid(row=3, column=0,
                                                     sticky=tk.W, pady=2)
        di = ttk.Frame(g)
        di.grid(row=3, column=1, columnspan=2, sticky=tk.W, pady=2)
        self._default_spin = ttk.Spinbox(di, from_=0, to=0, width=5,
                                         textvariable=self._default_var)
        self._default_spin.pack(side=tk.LEFT)
        ttk.Label(di, text="image index highlighted at power-up (the last "
                           "choice wins once one was made)",
                  foreground="#888").pack(side=tk.LEFT, padx=(6, 0))
        byp = ttk.Frame(g)
        byp.grid(row=4, column=0, columnspan=6, sticky=tk.W, pady=(4, 0))
        self._bypass_chk = ttk.Checkbutton(
            byp, text="Bypass game validation on every image",
            variable=self._bypass_var)
        self._bypass_chk.pack(side=tk.LEFT)
        self._bypass_badge = self._info_badge(byp, self.BYPASS_TIP)
        self._bypass_badge.pack(side=tk.LEFT, padx=(6, 0))

    def _build_output(self, frame, pad):
        box = ttk.LabelFrame(frame, text="Output")
        box.pack(fill=tk.X, **pad)
        g = ttk.Frame(box)
        g.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(g, text="Card image:", width=14).grid(row=0, column=0,
                                                        sticky=tk.W, pady=2)
        self._out_entry = ttk.Entry(g, textvariable=self._out_var)
        self._out_entry.grid(row=0, column=1, sticky=tk.EW, pady=2)
        ttk.Button(g, text="Browse…", width=10, command=self._browse_out).grid(
            row=0, column=2, sticky=tk.W, padx=(6, 0), pady=2)
        ttk.Label(g, text="Selector build:", width=14).grid(
            row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(g, textvariable=self._selector_var).grid(
            row=1, column=1, sticky=tk.EW, pady=2)
        ttk.Label(g, foreground="#888",
                  text="WSL path of the built selector (the rig installs it "
                       "there on the first Boot-selector run)").grid(
            row=2, column=1, sticky=tk.W)
        g.columnconfigure(1, weight=1)

    def _build_actions(self, frame, pad):
        row = ttk.Frame(frame)
        row.pack(fill=tk.X, **pad)
        self._plan_btn = ttk.Button(row, text="Check size", width=11,
                                    command=self._check_size)
        self._plan_btn.pack(side=tk.LEFT)
        self._prepare_btn = ttk.Button(row, text="Prepare media", width=14,
                                       command=self._prepare_media)
        self._prepare_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._build_btn = ttk.Button(row, text="Build & verify", width=14,
                                     command=self._build_card)
        self._build_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._flash_btn = ttk.Button(row, text="Flash to SD card…", width=17,
                                     command=self._flash)
        self._flash_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._emu_btn = ttk.Button(row, text="Run in emulator", width=15,
                                   command=self._run_emulator)
        self._emu_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._bypass_btn = ttk.Button(row, text="Bypass an existing card…",
                                      width=24, command=self._bypass_existing)
        self._bypass_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._action_btns = [self._plan_btn, self._prepare_btn,
                             self._build_btn, self._flash_btn, self._emu_btn,
                             self._bypass_btn, self._add_btn,
                             self._remove_btn, self._up_btn, self._down_btn]

    def _build_log(self, frame, pad):
        box = ttk.LabelFrame(frame, text="Tool output")
        box.pack(fill=tk.BOTH, expand=True, **pad)
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        _sans, mono = platform_font()
        inner = ttk.Frame(box)
        inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self._log_text = tk.Text(
            inner, height=9, wrap=tk.NONE, state=tk.DISABLED,
            font=(mono, 9), bg=th["field_bg"], fg=th["fg"],
            insertbackground=th["fg"], relief=tk.FLAT,
            highlightthickness=1, highlightbackground=th["border"])
        sb = ttk.Scrollbar(inner, orient=tk.VERTICAL,
                           command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)

    def _info_badge(self, parent, tip):
        """The app's round blue (i) badge, or a plain marker without the
        app - EmulatePanel._info_badge's shape, degraded the same way."""
        if self._badge_fn is None:
            lbl = ttk.Label(parent, text="(i)", foreground="#2f80ed")
            lbl.icon_tip = _Tooltip(lbl, tip, self._theme_fn, place="side")
            return lbl
        badge = self._badge_fn(parent, "i", "#2f80ed", "#5296f2",
                               tip, lambda: None, size=18,
                               font=("Georgia", 10, "bold italic"),
                               tooltip_place="side")
        badge.bind("<Button-1>", lambda _e: badge.icon_tip.show(), add="+")
        return badge

    # ------------------------------------------------------------------
    # the image list
    # ------------------------------------------------------------------

    @staticmethod
    def _cell(value):
        v = (value or "").strip()
        return v if v.lower() in _WORDS or not v else os.path.basename(v)

    def _refresh_tree(self, select=None):
        try:
            for item in self._tree.get_children():
                self._tree.delete(item)
            for i, row in enumerate(self._rows):
                self._tree.insert("", tk.END, iid=str(i), values=(
                    i, row.path, row.title, row.subtitle, self._cell(row.art),
                    self._cell(row.anim), self._cell(row.music)))
            if select is not None and 0 <= select < len(self._rows):
                self._tree.selection_set(str(select))
                self._tree.focus(str(select))
            self._default_spin.configure(to=max(0, len(self._rows) - 1))
        except tk.TclError:
            pass
        self._load_editor()

    def _selected(self):
        try:
            sel = self._tree.selection()
        except tk.TclError:
            return None
        if not sel:
            return None
        try:
            i = int(sel[0])
        except ValueError:
            return None
        return i if 0 <= i < len(self._rows) else None

    def _load_editor(self):
        """Editor <- the selected row (guarded so the traces stay quiet)."""
        i = self._selected()
        self._loading = True
        try:
            row = self._rows[i] if i is not None else ImageRow("")
            self._ed_title.set(row.title)
            self._ed_sub.set(row.subtitle)
            self._ed_art.set(row.art)
            self._ed_anim.set(row.anim)
            self._ed_music.set(row.music)
        finally:
            self._loading = False

    def _editor_changed(self):
        """The selected row <- the editor, on every keystroke."""
        if self._loading:
            return
        i = self._selected()
        if i is None:
            return
        row = self._rows[i]
        row.title = self._ed_title.get()
        row.subtitle = self._ed_sub.get()
        row.art = self._ed_art.get()
        row.anim = self._ed_anim.get()
        row.music = self._ed_music.get()
        try:
            self._tree.item(str(i), values=(
                i, row.path, row.title, row.subtitle, self._cell(row.art),
                self._cell(row.anim), self._cell(row.music)))
        except tk.TclError:
            pass

    def add_image(self, path):
        """Append a card image (the public half of Add image…)."""
        path = (path or "").strip().strip('"')
        if not path:
            return
        if len(self._rows) >= MAX_IMAGES:
            self._error("At most %d images fit one card." % MAX_IMAGES)
            return
        title, subtitle = suggest_title(path)
        self._rows.append(ImageRow(path=path, title=title, subtitle=subtitle))
        self._refresh_tree(select=len(self._rows) - 1)
        if len(self._rows) == 1:
            self._maybe_default_output()
        self._ok("")

    def _add_image(self):
        path = filedialog.askopenfilename(
            title="Pick a Spike 2 card image for the card",
            filetypes=[("Card images", "*.raw *.img"), ("All files", "*.*")])
        if path:
            self.add_image(path)

    def _remove_image(self):
        i = self._selected()
        if i is None:
            return
        del self._rows[i]
        self._refresh_tree(select=min(i, len(self._rows) - 1))
        if i == 0:
            self._maybe_default_output()

    def _move_image(self, delta):
        i = self._selected()
        if i is None:
            return
        j = i + delta
        if not 0 <= j < len(self._rows):
            return
        self._rows[i], self._rows[j] = self._rows[j], self._rows[i]
        self._refresh_tree(select=j)
        if 0 in (i, j):
            self._maybe_default_output()

    def _maybe_default_output(self):
        """Fill the output from the primary unless the user typed their own
        (a path we filled in earlier counts as ours and is replaced)."""
        cur = self._out_var.get().strip()
        if cur and cur != self._out_auto_value:
            return
        if not self._rows:
            return
        new = default_output_path(self._rows[0].path)
        self._out_auto_value = new
        self._out_var.set(new)

    def _browse_media(self, var, filetypes):
        path = filedialog.askopenfilename(
            title="Pick a media file",
            filetypes=list(filetypes) + [("All files", "*.*")])
        if path:
            var.set(path)

    def _browse_out(self):
        cur = self._out_var.get().strip()
        path = filedialog.asksaveasfilename(
            title="Where to write the multi-image card",
            defaultextension=".raw",
            initialdir=os.path.dirname(cur) if cur else None,
            initialfile=os.path.basename(cur) if cur else None,
            filetypes=[("Card images", "*.raw"), ("All files", "*.*")])
        if path:
            self._out_var.set(path)

    # ------------------------------------------------------------------
    # the form
    # ------------------------------------------------------------------

    def form(self):
        """The form as a :class:`MultibootForm` - what every command line is
        built from.  ``media_dir`` is set only when a prepared media set is
        actually there (media.json), so a build never names a dir the tool
        would refuse."""
        out = self._out_var.get().strip().strip('"')
        media = media_dir_for(out)
        return MultibootForm(
            images=[ImageRow(r.path, r.title, r.subtitle, r.art, r.anim,
                             r.music) for r in self._rows],
            out=out,
            sound_move=self._move_var.get().strip() or "none",
            sound_confirm=self._confirm_var.get().strip() or "none",
            volume=_int(self._volume_var, 50),
            timeout=_int(self._timeout_var, 15),
            default=_int(self._default_var, 0),
            bypass=bool(self._bypass_var.get()),
            media_dir=media if (media and os.path.isfile(
                os.path.join(media, "media.json"))) else "",
            selector_dir=self._selector_var.get().strip()
            or DEFAULT_SELECTOR_DIR)

    def _validated_form(self):
        form = self.form()
        errs = validate_form(form)
        if errs:
            self._error("\n".join(errs))
            return None
        return form

    def _error(self, msg):
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        try:
            self._hint.configure(text=msg, foreground=th["error"])
        except tk.TclError:
            pass
        for line in msg.splitlines():
            self._log_sink("[multiboot] " + line)

    def _ok(self, msg):
        try:
            self._hint.configure(text=msg, foreground="#888")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def _check_size(self):
        form = self._validated_form()
        if form is None:
            return
        self._ok("Planning the layout…")
        self._run_commands(plan_commands(form), on_step=self._plan_step,
                           on_done=lambda rc, failed, _t: self._ok(
                               "" if rc == 0 else "The plan failed - see "
                               "the tool output."))

    def _plan_step(self, label, rc, text):
        if label != "plan":
            return
        if rc == 0:
            self._plan_info = parse_plan(text)
            self._plan_lbl.configure(text=size_plan_text(self._plan_info))
        else:
            self._plan_lbl.configure(text="")

    def _prepare_media(self):
        form = self._validated_form()
        if form is None:
            return
        media = media_dir_for(form.out)
        try:
            os.makedirs(media, exist_ok=True)
        except OSError as exc:
            self._error("Cannot create %s: %s" % (media, exc))
            return
        self._ok("Preparing media into %s…" % media)
        self._run_commands(
            prepare_commands(form, media),
            on_done=lambda rc, failed, _t: self._ok(
                "Media ready in %s - Build & verify will carry it." % media
                if rc == 0 else
                "Media preparation failed - see the tool output."))

    def _build_card(self):
        form = self._validated_form()
        if form is None:
            return
        if os.path.exists(form.out):
            if not self._confirm_overwrite(form.out):
                return
            form.force = True
        self._plan_lbl.configure(text="")
        self._ok("Building %s…" % form.out)

        def done(rc, failed, _text):
            if rc == 0:
                self._ok("Card built and verified: %s%s" % (
                    form.out, "" if form.media_dir else
                    " (no prepared media - text-only menu)"))
            else:
                self._error("%s failed (exit %d) - see the tool output."
                            % (failed or "the build", rc))
        self._run_commands(build_commands(form), on_step=self._plan_step,
                           on_done=done)

    def _confirm_overwrite(self, path):
        return messagebox.askyesno(
            "Overwrite?", "%s exists. Rebuild over it?" % path)

    def _finished_card(self, verb):
        """The built card, or None with the reason on the tab."""
        out = self._out_var.get().strip().strip('"')
        if not out:
            self._error("Set the output path and build the card first.")
            return None
        if not os.path.isfile(out):
            self._error("Build the card first - nothing at %s yet." % out)
            return None
        if self._busy:
            self._error("Wait for the current run to finish before you %s."
                        % verb)
            return None
        return out

    def _flash(self):
        out = self._finished_card("flash")
        if out is None:
            return
        if self._flash_fn is None:
            self._error("Flashing is not available from a standalone panel.")
            return
        self._ok("Flashing %s…" % out)
        self._flash_fn(out)

    def _run_emulator(self):
        out = self._finished_card("run it")
        if out is None:
            return
        if self._emulate_fn is None:
            self._error("The emulator is not available from a standalone "
                        "panel.")
            return
        self._ok("Starting the emulator on %s with the boot selector…" % out)
        self._emulate_fn(out)

    def _bypass_existing(self):
        if self._busy:
            self._error("Wait for the current run to finish first.")
            return
        path = filedialog.askopenfilename(
            title="Pick the multi-image card to bypass validation on",
            filetypes=[("Card images", "*.raw *.img"), ("All files", "*.*")])
        if path:
            self.bypass_card(path)

    def bypass_card(self, path):
        """``mkmulticard.py bypass --card`` on an existing card image."""
        path = (path or "").strip().strip('"')
        if not os.path.isfile(path):
            self._error("No such card image: %s" % path)
            return
        if under_library(path):
            self._error("That card is in the library (%s); copy it out "
                        "first." % LIBRARY_PREFIXES[0])
            return
        self._ok("Bypassing the validator on every image of %s…" % path)
        self._run_commands(
            bypass_commands(path),
            on_done=lambda rc, failed, _t: self._ok(
                "Validator bypassed on %s - flash it again." % path
                if rc == 0 else "The bypass failed - see the tool output."))

    # ------------------------------------------------------------------
    # running the tools
    # ------------------------------------------------------------------

    def _set_busy(self, busy):
        self._busy = busy
        for btn in getattr(self, "_action_btns", ()):
            try:
                btn.configure(state=tk.DISABLED if busy else tk.NORMAL)
            except tk.TclError:
                pass
        if not busy:
            # Greyed for good, not just for the run: a panel built without
            # the app has nowhere to hand the card.
            for fn, btn in ((self._flash_fn, getattr(self, "_flash_btn", None)),
                            (self._emulate_fn, getattr(self, "_emu_btn", None))):
                if fn is None and btn is not None:
                    try:
                        btn.configure(state=tk.DISABLED)
                    except tk.TclError:
                        pass

    def _run_commands(self, cmds, on_step=None, on_done=None):
        """Run ``[(label, argv), ...]`` in order on a worker, streaming every
        line into the pane; stop at the first failure.  ``on_step(label, rc,
        text)`` and ``on_done(rc, failed_label, {label: text})`` are called
        on the main loop.  False when a run is already in flight - the busy
        guard, and the only one: two builds into one file is a corrupt card.
        """
        if self._busy:
            self._error("A run is already in progress.")
            return False
        self._set_busy(True)

        def run():
            rc = 0
            failed = None
            texts = {}
            for label, argv in cmds:
                self._append("$ " + argv[-1])
                try:
                    proc = subprocess.Popen(
                        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        creationflags=_rig.CREATE_FLAGS)
                except Exception as exc:                # noqa: BLE001
                    self._append("[multiboot] cannot start %s: %s"
                                 % (label, exc))
                    rc, failed = 1, label
                    break
                self._proc = proc
                lines = []
                try:
                    for raw in proc.stdout:
                        line = raw.decode("utf-8", "replace").rstrip()
                        lines.append(line)
                        self._append(line)
                except Exception:                       # noqa: BLE001
                    pass                                # pipe closed under us
                rc = proc.wait()
                self._proc = None
                texts[label] = "\n".join(lines)
                self._append("[multiboot] %s: exit %d" % (label, rc))
                if on_step is not None:
                    self._ui(lambda l=label, r=rc, t=texts[label]:
                             on_step(l, r, t))
                if rc != 0:
                    failed = label
                    break

            def finish():
                self._set_busy(False)
                if on_done is not None:
                    on_done(rc, failed, texts)
            self._ui(finish)

        threading.Thread(target=run, daemon=True).start()
        # Start the drain from HERE (the main thread - this is a button
        # handler); it re-arms itself until the worker's finish has run.
        if self._drain_job is not None:
            try:
                self._timer().after_cancel(self._drain_job)
            except (tk.TclError, ValueError):
                pass
            self._drain_job = None
        self._drain()
        return True

    def _append(self, line):
        """A tool line, from the worker: the tab's pane AND the app log (so
        'paste what it said' is one paste)."""
        self._ui(lambda: self._write(line))
        self._ui(lambda: self._log_sink("[multiboot] " + line))

    def _write(self, line):
        try:
            self._log_text.configure(state=tk.NORMAL)
            self._log_text.insert(tk.END, line + "\n")
            n = int(self._log_text.index("end-1c").split(".")[0])
            if n > self.LOG_KEEP:
                self._log_text.delete("1.0", "%d.0" % (n - self.LOG_KEEP))
            self._log_text.configure(state=tk.DISABLED)
            self._log_text.see(tk.END)
        except tk.TclError:
            pass
