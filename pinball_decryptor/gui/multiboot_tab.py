"""Multi-boot tab - one Spike 2 SD card, several game images, a menu at
power-up (item 90), set up and built from the app.

The pieces it drives already exist, and they are the ONLY places that know
how a multi-image card is put together:

* ``tools/spike2_emu/selectmedia.py prepare`` renders the menu's media - a
  picture (or an animated GIF) per image, the move / confirm sounds, an
  optional music loop - into one flat directory with a ``media.json``.
* ``tools/spike2_emu/mkmulticard.py`` plans, builds and verifies the card,
  and on an existing card applies the validator bypass (``bypass --card``).
* ``tools/spike2_emu/codeselect`` - the ARM selector the card boots - draws
  the menu, and with ``--snapshot`` draws ONE frame of it to a PPM file.

This module is a control surface for those tools and nothing more: it
collects the form, turns it into command lines (PURE functions, so the tests
can read the argv without WSL), streams the tools' stdout into a pane on the
tab, and hands the finished image to the app's own Build / flash flow or to
the Emulate tab.  It deliberately reimplements none of the layout arithmetic,
the media budgets or the validation - a second copy of any of them is how two
tools come to disagree about one card (the rig's own hardest-won rule).

WHERE THE TOOLS RUN.  All are Linux programs (debugfs, mke2fs, ffmpeg, the
ext4 reader, an ARM binary under qemu) and are reached the way the Emulate
tab reaches the rig: through ``wsl.exe`` on Windows, directly on a Linux
desktop.  Windows paths cross the boundary through :func:`.._rig.wsl_path`,
the app's one spelling of that translation.  The command line is ``bash -lc
'cd <checkout> && python3 tools/spike2_emu/<tool>.py ...'`` with every
argument shell-quoted: the tools import ``pinball_decryptor`` (the validator
bypass uses plugins/stern/valpatch and sidx), so they run from the checkout
root.  ``$`` and backticks are refused in titles rather than escaped -
``wsl.exe`` re-parses its argument line and both expand to nothing on that
second pass (the JJP executor's lesson), and no quoting from this side
survives that.

THE LAYOUT.  ONE arrangement at every width - the structure never changes
under the window.  Top to bottom, in the order the work happens: 'Load
card…' / 'New card…' and the card path first (reading a card you already
built is the usual first move); then a two-column body - a narrow image
list on the left, the PREVIEW on the right, large and always visible;
then ONE action bar; then one status block; then the tools' own output,
folded away.  The detail of one image and of the menu is behind two
modals (:class:`ImageEditorDialog`, :class:`MenuSettingsDialog`), which
is what makes the whole tab fit the ~640 px of content height a 1024x768
desktop leaves for it - David's desktop, and the constraint the layout is
designed around.  The modals bind to the PANEL's own variables, so there
is one form whether a dialog is open or not, and Cancel restores the
snapshot taken when it opened.

BUTTONS LIVE IN EXACTLY TWO PLACES: the source row at the top and the
action bar at the bottom.  The image list has none - right-click a row
for Add / Edit / Remove / Up / Down (double-click and Return still open
Edit), and a dim line under the list says so - and the preview has none:
its right-click menu carries the manual refresh and the 'update
automatically' toggle.  A tab whose every control is a button reads as
busy, and the two menus lose nothing: every entry is the button that was
there, and every keyboard path still works.

THE PREVIEW'S SIZE.  The canvas is a FIXED height (half the selector's
768) and takes whatever width its column gives it, so the tab's height
never moves as the window is dragged.  The picture is scaled smoothly
into it with Pillow, aspect kept and centred; without Pillow it falls
back to Tk's PhotoImage, which only scales by whole numbers.

THE PREVIEW.  It shows the boot menu as the machine will draw it, and it
follows the form by itself: every field schedules a re-render ~350 ms
after the last keystroke, coalesced into one run.  The selector is built
from this checkout (``make`` into a scratch dir, never installed - the
'Selector build' path is the fallback when the cross compiler is missing)
once per session; the media is prepared ``--visual-only`` into the SAME
``<out dir>/media`` the build uses, and ONLY when the media fingerprint
moved (see :func:`media_fingerprint`) - so a title, a subtitle, the
countdown or the default costs one ``qemu-arm-static -L <rootfs>
codeselect --snapshot`` run and nothing else, while art, clips, music and
the sounds pay for selectmedia's prepare (cached; 0.13 s for a two-image
set when nothing changed).  The conf the picture is drawn from is written
under ``<out dir>/preview``, and each snapshot writes a P6 PPM that Tk
loads natively.  'Play' steps the highlighted card's animation, rendering
frames as it goes and keeping them per (form, highlight, frame) until the
form changes.  Because a preview leaves a sound-less media.json behind,
'Build & verify' runs a full prepare into that dir first whenever a media
set exists - the card is never built from the preview's half of the media.

READING A CARD BACK.  'Load card…' runs ``mkmulticard.py inspect`` on a card
that already exists - the tool's table into the pane, the same read as JSON
for the form, and the card's own media extracted into ``<card dir>/media-
<stem>`` - and fills EVERY field from it: the images and where they came
from, the titles and subtitles, the art / animation / music (as the spec
strings the card records, so the tools can render them again), the sounds,
volume, countdown, default and the bypass state of every games tree.  The
tab is then in EDITING MODE: the loaded card and the form as it was read are
remembered, every keystroke is diffed against that baseline, and the status
block says which of the two things can happen - and which of the two
writing buttons is the green one.  'Apply to card' writes the menu
back with ``inject`` (plus a ``prepare`` when a media field changed, plus
``bypass`` when it is ticked and a tree is still armed) - seconds, no copy.
The image LIST - how many images, in what order, from which files - is the
one thing an inject cannot change, so changing it disables Apply and says
so; and because the output box now holds the loaded card, 'Build & verify'
refuses until a different output path is set rather than copying ~7 GB over
the card being edited.  A card whose media has no source recorded (a v1
card, or a music bed) keeps its file names: they can be kept and drawn, but
not re-rendered, and the tab says which field to re-point before a media
change can be applied.

WHAT IS NOT HERE.  No probe runs when the tab is built, no path is guessed
from the Input box, and no two tool runs overlap: a build copies ~7 GB per
image and the tab is busy until the run has said PASS or FAIL.
"""

import hashlib
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field, replace
from tkinter import filedialog, messagebox, ttk

from . import _rig
from .emulate_tab import rig_dir
from .theme import THEMES, dark_titlebar
from .widgets import _Tooltip, center_over

# Pillow scales the preview smoothly (Tk's own PhotoImage only halves and
# thirds).  It is a hard dependency of the app - the same guarded import
# main_window.py, scene_browser.py and font_studio.py use - but the
# fallback below keeps the tab drawing if it is ever missing.
try:
    from PIL import Image, ImageTk
    _HAVE_PIL = True
except ImportError:                                     # pragma: no cover
    _HAVE_PIL = False

#: The tools, relative to the checkout root the command line cd's into.
TOOL_DIR = "tools/spike2_emu"
MKMULTICARD = TOOL_DIR + "/mkmulticard.py"
SELECTMEDIA = TOOL_DIR + "/selectmedia.py"
CODESELECT_SRC = TOOL_DIR + "/codeselect"

#: Where the rig installs the ARM selector (buildselect.sh's ``make install
#: DESTDIR=$ROOT``, ROOT = PAD_ROOT else ~/spike2root).  A WSL path, spelled
#: with ``~`` on purpose: the app cannot know the WSL user's home without a
#: probe, and ``~/`` is expanded by bash without a ``$`` for wsl.exe to eat.
DEFAULT_SELECTOR_DIR = "~/spike2root/usr/local/codeselect"

#: The card rootfs copy the selector is built against and run in (the
#: Makefile's ROOT, qemu's ``-L``) when the selector build path does not
#: say otherwise (``<rootfs>/usr/local/codeselect`` names it).
DEFAULT_ROOTFS = "~/spike2root"

#: Where the preview's own selector is built.  A scratch dir: nothing is
#: installed and nothing under the rootfs is written.
PREVIEW_BUILD_DIR = "~/emusrc/codeselect-preview"

#: The font the card carries; inside the rootfs, where qemu's ``-L`` prefix
#: resolves it (the same file the machine reads).
CONF_FONT = "/usr/local/codeselect/font.ttf"

#: David's card library - never an output (mkmulticard.py refuses the same
#: prefixes after resolving links; the repo's own images/ is a junction into
#: it).  Both spellings, because the form holds Windows paths and the tool
#: sees WSL ones.  tests/test_multiboot_tab.py pins this to the tool's list.
LIBRARY_PREFIXES = ("D:/Pinball/images", "/mnt/d/Pinball/images")

#: images.conf v2 carries up to 16 images.
MAX_IMAGES = 16

#: The image list is as tall as it has rows, between these two: eight rows
#: of empty box under two images is a hole in the tab, and a list that
#: grows for every image would push the tab past its height budget.
LIST_MIN_ROWS, LIST_MAX_ROWS = 4, 8

#: The non-file choices each media field accepts.  Anything else is a path.
ART_CHOICES = ("auto", "none", "video frame")
ANIM_CHOICES = ("none", "auto")
MUSIC_CHOICES = ("none",)
SOUND_CHOICES = ("auto", "synth", "none")
#: An IMAGE'S OWN confirm sound.  'menu' is the default and means "whatever
#: the menu's confirm sound is" - there is no per-image 'none', because the
#: tools spell 'this image has no confirm of its own' the same way, and a
#: choice that reads as silence but plays the menu's sound would be a lie.
IMAGE_CONFIRM_CHOICES = ("menu", "auto", "synth")
_WORDS = frozenset(("auto", "none", "synth", "video frame", "menu"))

#: ``auto@<index>`` - a specific sound out of that image's own catalogue.
#: The tab never writes one, but a card prepared by hand may carry it, and a
#: load must hand it back unchanged rather than mistake it for a path.
_AUTO_IDX_RE = re.compile(r"(?i)^auto@\d+$")

#: A picture taken from a video: ``--art N=<video>@<seconds>``.
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi")

#: selectmedia.py's own clip defaults (its --start / --seconds / --fps).  A
#: blank field in the editor means "the tool's default"; when any of the
#: three is given all three are spelled out, explicit rather than defaulted.
ANIM_DEFAULTS = ("0", "3", "10")

#: The selector's own frame, and the box the preview draws it in.  The box
#: is the height the rest of the tab does not need (up to half the
#: machine's 768) and exactly the width that height's own 16:9 asks for -
#: so the canvas IS the picture, with no black bars around it, and the
#: tab's height stays put as the window is dragged sideways.
FRAME_W, FRAME_H = 1360, 768
PREVIEW_W, PREVIEW_H = FRAME_W // 2, FRAME_H // 2
#: The narrowest and shortest the picture may get: a menu smaller than this
#: says nothing anyway.
PREVIEW_MIN_W = 240
PREVIEW_MIN_H = 150
#: The smallest whole-number step the PhotoImage fallback may shrink to
#: (only reached without Pillow - see :func:`preview_box`).
PREVIEW_MIN_K = 4
PREVIEW_FPS = 8

#: How long the preview waits after the last keystroke before it re-renders.
#: Every change inside the window is one render, not N.
PREVIEW_DEBOUNCE_MS = 350

#: The most height the tab may ask for on a 1024x768 desktop - what is
#: left inside the notebook once the app's own title bar, header, tab
#: strip, footer and a line of Log have taken theirs.  The tab is never
#: taller than this on that desktop, at any width.
TAB_BUDGET_H = 640

#: ...and what the app takes around the notebook, so a TALLER window can
#: be measured the same way: the budget is the window's height less this,
#: which is 640 exactly on a 768-high desktop.  The window's height is set
#: by the person using it and never by this tab (the notebook is pinned to
#: the tab's requested height, and nothing resizes the toplevel), so
#: reading it here is not a loop.
APP_CHROME_H = 128

#: What the selector-ensuring step prints in front of the binary it chose.
SELECTOR_LINE = "[preview] selector:"


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
    art: str = "auto"        # auto | none | video frame | <png/jpg/video file>
    anim: str = "none"       # none | auto (the attract clip) | <gif/mp4/mov>
    music: str = "none"      # none | <wav file>
    #: THIS image's own confirm sound: "" or "menu" = the menu's, else
    #: auto | synth | auto@<index> | <wav file>.
    confirm: str = ""
    art_video: str = ""      # 'video frame': the clip the picture comes from
    art_time: str = ""       # ...and the second it is taken at (blank = 0)
    anim_start: str = ""     # seconds into the clip (blank = the tool's default)
    anim_seconds: str = ""   # the clip's length
    anim_fps: str = ""
    #: The game code version of this image, when something has reported one
    #: - the table shows it in its own column and leaves the cell blank
    #: until then.  Never typed: it is a fact about the .raw, read off it.
    version: str = ""
    # Filled by a LOAD (see 'reading a card back'), never typed.
    device: str = ""             # the card device this row was read from
    art_on_card: bool = False    # the value is a file name already on the
    anim_on_card: bool = False   # card that no source string explains, so
    music_on_card: bool = False  # nothing here can re-render it
    confirm_on_card: bool = False


def on_card_fields(row):
    """The row's media fields that came off a card with no source recorded -
    ``[(what, value), ...]``.  They can be kept (the file is on the card, and
    in the media dir a load extracted) but not re-rendered: selectmedia would
    have to read them out of the very directory it writes."""
    return [(what, val) for what, val, flag in
            (("art", row.art, row.art_on_card),
             ("animation", row.anim, row.anim_on_card),
             ("music", row.music, row.music_on_card),
             ("confirm sound", row.confirm, row.confirm_on_card)) if flag]


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


def is_video(path):
    """Whether a typed art path is a video (a frame of it is the picture)."""
    return (path or "").strip().strip('"').lower().endswith(VIDEO_EXTS)


def _num(value, default=""):
    """A numeric field as typed, stripped; blank -> *default*."""
    v = (value or "").strip()
    return v or default


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


def host_path(path):
    """The reverse of :func:`wsl`, for what a card recorded: ``/mnt/d/x`` ->
    ``D:/x`` on Windows, unchanged on a Linux desktop (and unchanged for a
    path that is not under /mnt/<drive>, a WSL home for one)."""
    p = (path or "").strip().replace("\\", "/")
    if sys.platform == "win32":
        m = re.match(r"^/mnt/([a-zA-Z])(?=/|$)", p)
        if m:
            return m.group(1).upper() + ":" + p[len(m.group(0)):]
    return p


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
    """Where 'Prepare media' renders for an output: ``<out dir>/media`` -
    and where the preview renders too, so the two share one cache."""
    out = (out or "").strip()
    return os.path.join(os.path.dirname(os.path.abspath(out)), "media") \
        if out else ""


def loaded_media_dir(card):
    """Where a LOADED card's media is extracted: ``<card dir>/media-<stem>``.

    Per card, not the plain ``media`` of :func:`media_dir_for`: David keeps
    several multi cards in one folder, and loading the second one must not
    write over the media the first one was built from."""
    card = (card or "").strip().strip('"')
    if not card:
        return ""
    stem = re.sub(r"\.(raw|img)$", "", os.path.basename(card), flags=re.I)
    return os.path.join(os.path.dirname(os.path.abspath(card)),
                        "media-" + stem)


def preview_dir_for(out):
    """Where the preview's conf and frames go: ``<out dir>/preview``."""
    out = (out or "").strip()
    return os.path.join(os.path.dirname(os.path.abspath(out)), "preview") \
        if out else ""


#: What a preview frame file is called.  THE FINGERPRINT IS IN THE NAME.
#: It has to be: the in-memory cache is keyed by (fingerprint, highlight,
#: frame), so changing a title and changing it back leaves the reverted
#: form with no cache entry and a render is queued - and if that render
#: wrote to the same file name the newer form had already written, either
#: form could be shown the other's picture.  Two forms, two names.
_FRAME_RE = re.compile(r"^frame_([0-9a-f]+)_(\d+)_(\d+)\.ppm$")


def frame_path(preview_dir, fingerprint, highlight, frame):
    """The PPM one snapshot writes:
    ``frame_<fingerprint>_<highlight>_<frame>.ppm``."""
    return os.path.join(preview_dir, "frame_%s_%d_%d.ppm"
                        % (fingerprint, highlight, frame))


def stale_frames(preview_dir, keep):
    """Every frame file in *preview_dir* that is not *keep*'s - the ones no
    form on the tab can ask for again.  ``preview/`` would otherwise grow a
    file per (form, image, frame) for as long as the tab is open."""
    try:
        names = os.listdir(preview_dir)
    except OSError:
        return []
    out = []
    for name in names:
        m = _FRAME_RE.match(name)
        if m and m.group(1) != keep:
            out.append(os.path.join(preview_dir, name))
    return out


def rootfs_for(selector_dir):
    """The rootfs a selector build sits in: ``~/spike2root/usr/local/
    codeselect`` -> ``~/spike2root``; :data:`DEFAULT_ROOTFS` otherwise."""
    d = (selector_dir or "").strip().rstrip("/")
    suffix = "/usr/local/codeselect"
    if d.endswith(suffix) and len(d) > len(suffix):
        return d[:-len(suffix)]
    return DEFAULT_ROOTFS


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

_BAD_TEXT = re.compile(r"[|;$`]")


def _bad_number(value, what, integer=False, positive=False):
    """Why a numeric field cannot be used, or None (blank is fine)."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        num = int(v) if integer else float(v)
    except ValueError:
        return "%s must be a %s, not %r." % (
            what, "whole number" if integer else "number", v)
    if positive and num <= 0:
        return "%s must be more than 0." % what
    if num < 0:
        return "%s cannot be negative." % what
    return None


def validate_form(form, sources=True):
    """Every reason the form cannot be built, as sentences for the tab.
    Empty = build it.  The tool re-checks all of it; this is so a bad form is
    a line on the tab and not a traceback in the log pane.

    ``sources=False`` drops the checks that are about the .raw files the
    images were copied from - a card read back with 'Load card…' names
    sources that may not be on THIS machine, and neither drawing its menu
    nor injecting a new one opens them."""
    errs = []
    n = len(form.images)
    if sources and n < 2:
        errs.append("Add at least two images: the primary (stock) and one "
                    "more.")
    if not n:
        errs.append("There are no images.")
    if n > MAX_IMAGES:
        errs.append("At most %d images fit one card." % MAX_IMAGES)
    seen = set()
    for i, row in enumerate(form.images):
        p = (row.path or "").strip().strip('"')
        if not sources:
            pass
        elif not p:
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
        on_card = dict(on_card_fields(row))
        for what, val in (("art", row.art), ("animation", row.anim),
                          ("music", row.music)):
            # A file name a load read off the card is not a path on this
            # machine and is not looked for: it is already in the media dir
            # the load extracted, and the preview draws it from there.
            if what in on_card:
                continue
            if is_file_choice(val) and not os.path.isfile(val.strip()):
                errs.append("Image %d: %s file not found: %s"
                            % (i, what, val))
        art = (row.art or "").strip()
        if art.lower() == "video frame":
            vid = (row.art_video or "").strip().strip('"')
            if not vid:
                errs.append("Image %d: pick the video the art frame is "
                            "taken from." % i)
            elif not os.path.isfile(vid):
                errs.append("Image %d: video not found: %s" % (i, vid))
        if art.lower() == "video frame" or is_video(art):
            why = _bad_number(row.art_time, "Image %d: the video frame time"
                              % i)
            if why:
                errs.append(why)
        if anim_spec(row) != "none":
            for val, what, kw in (
                    (row.anim_start, "animation start", {}),
                    (row.anim_seconds, "animation length",
                     {"positive": True}),
                    (row.anim_fps, "animation FPS",
                     {"integer": True, "positive": True})):
                why = _bad_number(val, "Image %d: the %s" % (i, what), **kw)
                if why:
                    errs.append(why)
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
        if sources and any(_norm(out) == _norm(r.path)
                           for r in form.images if (r.path or "").strip()):
            errs.append("The output is one of the input images.")
    return errs


def rebuild_blockers(form):
    """Why this form cannot be BUILT into a new card, over and above
    :func:`validate_form` - the media a load read off a card and nothing can
    re-render.  Injecting the same form back into the card it came from is
    fine; writing a fresh card from it is not."""
    errs = []
    for i, row in enumerate(form.images):
        for what, val in on_card_fields(row):
            errs.append(
                "Image %d: the %s (%s) is a file on the loaded card, not on "
                "this machine - choose auto, none or a file for it before "
                "building a new card." % (i, what, val))
    return errs


# ---------------------------------------------------------------------------
# command lines (pure)
# ---------------------------------------------------------------------------

def _media_value(value):
    """A media field for the tools: the word as is, a path in WSL form."""
    v = (value or "").strip().strip('"')
    return v.lower() if v.lower() in _WORDS else wsl(v)


def art_spec(row):
    """The ``--art N=`` value for a row: ``auto`` | ``none`` | ``<png>`` |
    ``<video>@<seconds>`` (the 'video frame' choice, or a typed video)."""
    v = (row.art or "").strip().strip('"')
    w = v.lower()
    if w in ("auto", "none", ""):
        return w or "auto"
    if w == "video frame":
        return "%s@%s" % (wsl((row.art_video or "").strip().strip('"')),
                          _num(row.art_time, "0"))
    if is_video(v):
        return "%s@%s" % (wsl(v), _num(row.art_time, "0"))
    return wsl(v)


def anim_spec(row):
    """The ``--anim N=`` value: ``none`` | ``auto`` | ``<file>``, with
    ``@<start>:<seconds>:<fps>`` appended when any of the three is set."""
    v = (row.anim or "").strip().strip('"')
    w = v.lower()
    if w in ("none", ""):
        return "none"
    base = "auto" if w == "auto" else wsl(v)
    start, secs, fps = (_num(row.anim_start), _num(row.anim_seconds),
                        _num(row.anim_fps))
    if start or secs or fps:
        base += "@%s:%s:%s" % (start or ANIM_DEFAULTS[0],
                               secs or ANIM_DEFAULTS[1],
                               fps or ANIM_DEFAULTS[2])
    return base


def confirm_spec(row):
    """The ``--sound-confirm N=`` value for a row.

    A row that uses the menu's sound is written ``none``, which is how
    selectmedia spells "image N has no confirm of its own": the manifest
    entry comes back null, the seventh images.conf field is empty, and the
    selector falls back to ``sound_confirm=``.  It is EXPLICIT rather than
    left out, so a row that used to have one and no longer does loses it."""
    v = (row.confirm or "").strip().strip('"')
    w = v.lower()
    if not v or w in ("menu", "none"):
        return "none"
    if w in ("auto", "synth") or _AUTO_IDX_RE.match(w):
        return w
    return wsl(v)


def split_confirm_source(spec):
    """A ``confirm_source`` from the card -> an :class:`ImageRow` value; the
    reverse of :func:`confirm_spec`, so a load followed by an apply writes
    back what was read.  ``none`` and a missing source both mean the menu's
    sound, which the row spells ``""``."""
    s = (spec or "").strip()
    if not s or s.lower() in ("none", "menu"):
        return ""
    if s.lower() in ("auto", "synth") or _AUTO_IDX_RE.match(s):
        return s.lower()
    return host_path(s)


def _image_args(form):
    args = ["--primary", wsl(form.images[0].path.strip().strip('"'))]
    for row in form.images[1:]:
        args += ["--extra", wsl(row.path.strip().strip('"'))]
    return args


def prepare_args(form, media_dir, visual_only=False):
    """``selectmedia.py prepare``: the images (the tool pulls 'auto' art and
    clips off them), then ``--art/--anim/--music N=<value>`` for EVERY image
    - explicit rather than defaulted, so the form and the manifest cannot
    disagree about an index - then the globals.  Rendered into *media_dir*,
    which then holds media.json.  ``visual_only`` is the preview's half: the
    art and animations with the same specs, no move / confirm sound work
    (music entries are still named, so the manifest rows match)."""
    args = [SELECTMEDIA, "prepare"] + _image_args(form) + [
        "--out", wsl(media_dir)]
    if visual_only:
        args.append("--visual-only")
    for i, row in enumerate(form.images):
        args += ["--art", "%d=%s" % (i, art_spec(row)),
                 "--anim", "%d=%s" % (i, anim_spec(row)),
                 "--music", "%d=%s" % (i, _media_value(row.music))]
    if not visual_only:
        args += ["--sound-move", _media_value(form.sound_move),
                 "--sound-confirm", _media_value(form.sound_confirm)]
        # ...then each image's own, after the menu-wide one: the bare value
        # and the N= values are one appending option, and the tool tells
        # them apart by the prefix, not by the order.
        for i, row in enumerate(form.images):
            args += ["--sound-confirm", "%d=%s" % (i, confirm_spec(row))]
    args += ["--volume", str(int(form.volume))]
    return args


def preview_prepare_args(form, media_dir):
    """The preview's ``prepare --visual-only`` into the build's media dir."""
    return prepare_args(form, media_dir, visual_only=True)


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


def inject_args(form, card):
    """``mkmulticard.py inject --card``: the menu alone, rewritten into an
    EXISTING card's p2 in seconds.  Every field is spelled out (the tool
    keeps the card's own value for a flag left off, and here the form is the
    record) - subtitles included, so clearing them clears them."""
    titles = [(r.title or "").strip() or suggest_title(r.path)[0]
              for r in form.images]
    subtitles = [(r.subtitle or "").strip() for r in form.images]
    args = [MKMULTICARD, "inject",
            "--card", wsl(card.strip().strip('"')),
            "--selector-dir", form.selector_dir or DEFAULT_SELECTOR_DIR,
            "--titles", ";".join(titles),
            "--subtitles", ";".join(subtitles),
            "--timeout", str(int(form.timeout)),
            "--default", str(int(form.default)),
            "--volume", str(int(form.volume))]
    if form.media_dir:
        args += ["--media-dir", wsl(form.media_dir)]
    return args


def inspect_args(card, media_out=None, as_json=False):
    """``mkmulticard.py inspect --card``: what a card carries.  Plain it
    prints a table; ``--json`` prints one object for the tab to read, and
    ``--media-out DIR`` drops the card's media files there so the preview
    can draw them and an inject can put them back."""
    args = [MKMULTICARD, "inspect", "--card", wsl(card.strip().strip('"'))]
    if as_json:
        args.append("--json")
    if media_out:
        args += ["--media-out", wsl(media_out)]
    return args


def preview_snapshot_args(binary, conf, media_dir, ppm, highlight, frame,
                          rootfs=DEFAULT_ROOTFS):
    """``qemu-arm-static -L <rootfs> <codeselect> --snapshot <ppm> ...``:
    ONE menu frame as the machine would show it - the conf, the media,
    highlight N, the animation at frame N, the countdown as if just started,
    no input, no audio, no choice file - then exit."""
    return ["qemu-arm-static", "-L", rootfs, binary,
            "--snapshot", wsl(ppm), "--conf", wsl(conf),
            "--media", wsl(media_dir),
            "--highlight", str(int(highlight)),
            "--anim-frame", str(int(frame)),
            "--input", "none"]


def _q(arg):
    """Shell-quote one argument, keeping a leading ``~/`` outside the quotes
    so bash still expands it (``~/'a b'`` is ``/home/x/a b``)."""
    if arg.startswith("~/"):
        return "~/" + shlex.quote(arg[2:])
    return shlex.quote(arg)


def shell_line(args, cwd, exe="python3"):
    """``cd <cwd> && python3 <args...>``, every argument quoted.  ``exe=None``
    runs *args* as they are (the first word is the program)."""
    words = ([exe] if exe else []) + list(args)
    return "cd %s && %s" % (_q(cwd), " ".join(_q(a) for a in words))


def wsl_shell(line):
    """The argv that runs one shell line on THIS platform: through ``wsl.exe``
    on Windows, ``bash`` on Linux."""
    if sys.platform == "win32":
        return ["wsl.exe", "-e", "bash", "-lc", line]
    return ["bash", "-lc", line]


def wsl_command(args, cwd=None, exe="python3"):
    """The argv that runs one tool command line.  *cwd* is the checkout root
    in WSL form (derived from the rig's location when not given)."""
    if cwd is None:
        cwd = wsl(repo_dir())
    return wsl_shell(shell_line(args, cwd, exe))


def ensure_selector_line(selector_dir, src_dir, build_dir=PREVIEW_BUILD_DIR,
                         rootfs=None):
    """The shell line that ends with ``[preview] selector: <binary>``: build
    the selector from *src_dir* into *build_dir* (``make`` is incremental -
    a no-op once built, so the preview always draws with THIS checkout's
    selector), or when that fails (no cross compiler) fall back to the
    tab's installed selector build; neither installs anything.  No ``$``:
    wsl.exe would eat it."""
    rootfs = rootfs or rootfs_for(selector_dir)
    built = build_dir.rstrip("/") + "/codeselect"
    installed = (selector_dir or DEFAULT_SELECTOR_DIR).rstrip("/") \
        + "/codeselect"
    tag = _q(SELECTOR_LINE)
    return ("if make -C %s BUILD=%s ROOT=%s all; then echo %s %s; "
            "elif [ -x %s ]; then echo %s %s; else echo %s; exit 1; fi"
            % (_q(src_dir), _q(build_dir), _q(rootfs), tag, _q(built),
               _q(installed), tag, _q(installed),
               _q("[preview] error: no selector - the build failed and %s "
                  "is not there" % installed)))


def ensure_selector_args(form, cwd=None):
    """The 'selector' step's argv (see :func:`ensure_selector_line`)."""
    if cwd is None:
        cwd = wsl(repo_dir())
    line = ensure_selector_line(form.selector_dir, cwd + "/" + CODESELECT_SRC)
    return wsl_shell("cd %s && %s" % (_q(cwd), line))


def parse_selector_path(text):
    """The binary the 'selector' step named, or ''."""
    for line in (text or "").splitlines():
        if line.startswith(SELECTOR_LINE):
            return line[len(SELECTOR_LINE):].strip()
    return ""


_ANIM_RE = re.compile(
    r"anim: image (\d+) (?:(\d+) frames|stopped after (\d+) frame)")


def parse_anim_frames(text, highlight):
    """How many frames image *highlight*'s animation has, from the selector's
    ``anim: image N F frames WxH`` (or ``stopped after F frame(s)``) log
    line; None when it logged none (no animation on that image)."""
    for line in (text or "").splitlines():
        m = _ANIM_RE.search(line)
        if m and int(m.group(1)) == highlight:
            return int(m.group(2) or m.group(3))
    return None


def write_preview_conf(form):
    """The images.conf the preview is drawn from, as text: the form's
    titles, subtitles, media names, default and countdown.  The device
    tokens are placeholders - a picture boots nothing."""
    lines = ["# written by the Multi-boot tab for its preview; the devices "
             "are placeholders,", "# everything else is the form"]
    for i, row in enumerate(form.images):
        dev = "p3" if i == 0 else ("p7" if i == 1 else "p7:img%d" % i)
        title = (row.title or "").strip() or suggest_title(row.path)[0]
        art = "art%d.png" % i if art_spec(row) != "none" else ""
        anim = "anim%d.gif" % i if anim_spec(row) != "none" else ""
        lines.append("image=%s|%s|%s|%s|%s|" % (
            dev, title, (row.subtitle or "").strip(), art, anim))
    lines += ["default=%d" % int(form.default),
              "timeout=%d" % int(form.timeout),
              "volume=%d" % int(form.volume),
              "font=" + CONF_FONT]
    return "\n".join(lines) + "\n"


def preview_fingerprint(form):
    """What a rendered frame depends on, as a short hash: the conf text
    (titles, subtitles, media names, default, countdown), the images and
    their art / animation specs, the selector and the output.  A frame
    cached under one fingerprint is never shown for another form."""
    data = [write_preview_conf(form),
            [((r.path or "").strip(), art_spec(r), anim_spec(r))
             for r in form.images],
            form.selector_dir, (form.out or "").strip()]
    return hashlib.sha1(json.dumps(data).encode("utf-8")).hexdigest()[:12]


def media_fingerprint(form):
    """What the PREPARED MEDIA depends on, as a short hash: the images, the
    art / animation / music specs, the two sounds and the volume.

    Not the titles, the subtitles, the countdown or the default - those
    reach the picture through images.conf, which the preview rewrites for
    every snapshot.  This is the whole point of the split: retyping a title
    costs one snapshot (~80 ms of selector time), and only a media change
    pays for selectmedia's prepare."""
    data = [[((r.path or "").strip(), art_spec(r), anim_spec(r),
              _media_value(r.music), confirm_spec(r), bool(r.art_on_card),
              bool(r.anim_on_card), bool(r.music_on_card),
              bool(r.confirm_on_card))
             for r in form.images],
            _media_value(form.sound_move), _media_value(form.sound_confirm),
            int(form.volume)]
    return hashlib.sha1(json.dumps(data).encode("utf-8")).hexdigest()[:12]


def scaled_size(w, h, box_w, box_h):
    """``(w, h)`` - *w* x *h* scaled to fit the box with its aspect ratio
    kept, up or down.  The smooth path (Pillow); at least 1x1."""
    if w <= 0 or h <= 0 or box_w <= 0 or box_h <= 0:
        return max(1, w), max(1, h)
    k = min(box_w / float(w), box_h / float(h))
    return max(1, int(round(w * k))), max(1, int(round(h * k)))


def fit_factors(w, h, box_w=PREVIEW_W, box_h=PREVIEW_H):
    """``(subsample, zoom)`` - the integer factors (Tk PhotoImage's only
    scaling) that fit a *w* x *h* frame into the box: 1360x768 -> (2, 1) =
    680x384; a small test frame is zoomed up instead.  The fallback for a
    machine with no Pillow; :func:`scaled_size` is what normally runs."""
    if w <= 0 or h <= 0:
        return 1, 1
    if w <= box_w and h <= box_h:
        return 1, max(1, min(box_w // w, box_h // h))
    return max(-(-w // box_w), -(-h // box_h)), 1


def preview_box(avail_w, avail_h, frame_w=FRAME_W, frame_h=FRAME_H,
                max_k=PREVIEW_MIN_K):
    """``(w, h, k)`` - the biggest whole-number fraction of the selector's
    frame that fits the room the window has given the preview.  Whole
    numbers because that is the only scaling Tk's PhotoImage does: half a
    frame is crisp, 0.62 of one is not available at all.  (The canvas is
    sized by :meth:`MultibootPanel._on_configure` now; this is what the
    no-Pillow fallback still measures the PICTURE with.)

    The size is rounded UP (1360 over 3 is 454, not 453): that is what
    ``subsample`` actually produces - it keeps every third pixel and the
    last one counts - and a box a pixel short of the picture would clip a
    column off every frame."""
    def _step(k):
        return -(-frame_w // k), -(-frame_h // k)
    for k in range(1, max_k + 1):
        w, h = _step(k)
        if w <= avail_w and h <= avail_h:
            return w, h, k
    w, h = _step(max_k)
    return w, h, max_k


def build_commands(form, cwd=None):
    """The 'Build & verify' run: plan (the size, before a byte is written),
    build, verify.  ``[(label, argv), ...]``, run in order, stop on failure."""
    return [("plan", wsl_command(plan_args(form), cwd)),
            ("build", wsl_command(build_args(form), cwd)),
            ("verify", wsl_command(verify_args(form), cwd))]


def prepare_commands(form, media_dir, cwd=None):
    return [("prepare", wsl_command(prepare_args(form, media_dir), cwd))]


def preview_prepare_commands(form, media_dir, cwd=None):
    return [("prepare", wsl_command(preview_prepare_args(form, media_dir),
                                    cwd))]


def ensure_selector_commands(form, cwd=None):
    return [("selector", ensure_selector_args(form, cwd))]


def snapshot_commands(binary, conf, media_dir, ppm, highlight, frame,
                      rootfs=DEFAULT_ROOTFS, cwd=None):
    return [("frame %d" % int(frame),
             wsl_command(preview_snapshot_args(binary, conf, media_dir, ppm,
                                               highlight, frame, rootfs),
                         cwd, exe=None))]


def plan_commands(form, cwd=None):
    return [("plan", wsl_command(plan_args(form), cwd))]


def bypass_commands(card, cwd=None):
    return [("bypass", wsl_command(bypass_args(card), cwd))]


#: The label of the inspect run whose stdout is JSON.  Its output is parsed,
#: not echoed (the pane gets the table the plain run prints instead) - see
#: MultibootPanel._run_commands' ``quiet``.
INSPECT_JSON = "inspect json"


def inspect_commands(card, media_out=None, cwd=None):
    """The 'Load card…' run: the tool's own table into the pane, then the
    same read as JSON (with the media extracted, when asked) for the form.
    Two reads of a few small files - the card is never written."""
    return [("inspect", wsl_command(inspect_args(card), cwd)),
            (INSPECT_JSON, wsl_command(
                inspect_args(card, media_out, as_json=True), cwd))]


def inject_commands(form, card, cwd=None):
    return [("inject", wsl_command(inject_args(form, card), cwd))]


def apply_commands(form, card, media_dir="", prepare=False, bypass=False,
                   refresh=True, cwd=None):
    """The 'Apply to card' run: the media first when a media field changed
    (into the dir the load extracted, so selectmedia's cache keeps the
    unchanged pictures), the menu injected into the card in place, the
    validator bypass when it is ticked and some tree is still armed, and a
    last inspect that reads the card back."""
    cmds = []
    if prepare:
        cmds += prepare_commands(form, media_dir, cwd)
    cmds += inject_commands(form, card, cwd)
    if bypass:
        cmds += bypass_commands(card, cwd)
    if refresh:
        cmds += inspect_commands(card, cwd=cwd)
    return cmds


# ---------------------------------------------------------------------------
# reading a card back (Load card… / Apply to card)
# ---------------------------------------------------------------------------

def parse_inspect(text):
    """The JSON object ``inspect --json`` printed, or None.  The object is
    found rather than assumed to be the whole of stdout: a stray line from
    the shell profile in front of it must not lose the report."""
    s = (text or "").strip()
    start, end = s.find("{"), s.rfind("}")
    for chunk in (s,
                  s[start:] if start > 0 else None,
                  s[start:end + 1] if 0 <= start < end else None):
        if not chunk:
            continue
        try:
            return json.loads(chunk)
        except ValueError:
            pass
    return None


def parse_refusal(text):
    """The tool's own ``refused: ...`` line, or ''.  What a failed load says
    on the tab instead of an exit code."""
    for line in reversed((text or "").splitlines()):
        s = line.strip()
        if s.lower().startswith("refused:"):
            return s
    return ""


_TIME_RE = re.compile(r"^\d+(\.\d+)?$")
_CLIP_RE = re.compile(r"^\d*(\.\d+)?(:\d*(\.\d+)?){0,2}$")


def split_art_source(spec):
    """An ``art_source`` from the card -> ``(art, art_video, art_time)`` for
    an :class:`ImageRow`.  A video keeps its seconds (``clip.mov@21`` is the
    same row the 'video frame' choice builds, typed straight into Art)."""
    s = (spec or "").strip()
    if not s:
        return "auto", "", ""
    if s.lower() in ("auto", "none"):
        return s.lower(), "", ""
    base, sep, tail = s.rpartition("@")
    if sep and base and is_video(base) and _TIME_RE.match(tail):
        return host_path(base), "", tail
    return host_path(s), "", ""


def split_anim_source(spec):
    """An ``anim_source`` -> ``(anim, start, seconds, fps)``; the reverse of
    :func:`anim_spec`, so a load followed by an apply writes what was read."""
    s = (spec or "").strip()
    if not s or s.lower() == "none":
        return "none", "", "", ""
    start = seconds = fps = ""
    base, sep, tail = s.rpartition("@")
    if sep and base and tail and _CLIP_RE.match(tail):
        parts = (tail.split(":") + ["", "", ""])[:3]
        start, seconds, fps = parts
        s = base
    return ("auto" if s.lower() == "auto" else host_path(s),
            start, seconds, fps)


def split_sound_source(spec, what):
    """A ``sound_move`` / ``sound_confirm`` from the card -> ``(value,
    note)``.

    What a card carries here is the WAV the selector plays (``move.wav``),
    not the spec that made it - images.conf and build.json both record the
    file name, and selectmedia's manifest records no source for the sounds.
    So a bare name means 'this card has a move sound, and which file made it
    is not written down': the field shows the tab's default and says so.
    Nothing acts on it until a media change makes the tools run again, and
    the sound already on the card is untouched until then."""
    s = (spec or "").strip()
    if not s:
        return "none", ""
    if s.lower() in _WORDS:
        return s.lower(), ""
    if "/" not in s and "\\" not in s:
        return "auto", ("The %s on this card is %s; which file made it is "
                        "not recorded, so the field shows 'auto'. It is only "
                        "re-made if you change some media." % (what, s))
    return host_path(s), ""


#: The version gate's findings, worst first.  ``inspect`` writes each of
#: these as a finished sentence or null, so the tab shows what the tool
#: decided rather than deciding it again - and a card whose images disagree
#: about their TITLE is a worse thing to have built than one that disagrees
#: about the version, which is worse than one that only ships different node
#: board firmware.
VERSION_ALARMS = (
    ("title_mismatch", "These images are not the same game."),
    ("version_mismatch", "These images are not the same game code version."),
    ("node_fw_mismatch", "These images carry different node board firmware."),
    ("unknown_version", "The game code version of an image could not be "
                        "read."),
)


def version_alarm(info):
    """``(headline, full text)`` for the loudest thing the version gate found
    on this card, or ``None`` when its images agree.

    The headline is the one line the strip can hold; the full text is every
    finding the report carries, in the same order, for the Log and the
    tooltip.  Nothing here is derived: an image's version is read off the
    image, and these sentences are written by the tool that read it."""
    found = [(head, str(info.get(key)).strip())
             for key, head in VERSION_ALARMS if info.get(key)]
    if not found:
        return None
    return found[0][0], "\n\n".join(t for _h, t in found)


def bypass_state(info):
    """``(ticked, armed)`` from the per-image bypass states an inspect
    reported: ticked when no tree is still armed, armed when at least one
    is (an inject alone never patches a tree, so Apply runs the bypass)."""
    states = [(im or {}).get("bypass") for im in (info.get("images") or [])]
    armed = any(st == "armed" for st in states)
    return (not armed and any(st == "bypassed" for st in states)), armed


def rows_from_inspect(info):
    """``(rows, warnings)`` - the image list of an inspect report as form
    rows.  A missing source is kept as a row (its device names it); media
    with a recorded source becomes a spec the tools can render again, media
    without one keeps the card's file name (see :func:`on_card_fields`)."""
    rows, warnings = [], []
    for i, im in enumerate(info.get("images") or []):
        im = im or {}
        row = ImageRow(path=host_path(im.get("source") or ""),
                       title=im.get("title") or "",
                       subtitle=im.get("subtitle") or "",
                       device=im.get("device") or "",
                       # read off the image itself, never typed and never
                       # guessed from a file name
                       version=(im.get("version") or "").strip())
        if im.get("art_source"):
            row.art, row.art_video, row.art_time = \
                split_art_source(im["art_source"])
        elif im.get("art"):
            row.art, row.art_on_card = im["art"], True
        else:
            row.art = "none"
        if im.get("anim_source"):
            (row.anim, row.anim_start, row.anim_seconds, row.anim_fps) = \
                split_anim_source(im["anim_source"])
        elif im.get("anim"):
            row.anim, row.anim_on_card = im["anim"], True
        else:
            row.anim = "none"
        if im.get("music"):
            row.music, row.music_on_card = im["music"], True
        else:
            row.music = "none"
        if im.get("confirm_source"):
            row.confirm = split_confirm_source(im["confirm_source"])
        elif im.get("confirm"):
            row.confirm, row.confirm_on_card = im["confirm"], True
        else:
            row.confirm = ""
        if not row.path:
            warnings.append("Image %d: this card does not record which .raw "
                            "it was built from (%s)."
                            % (i, row.device or "no device"))
        elif im.get("source_exists") is False or not os.path.isfile(row.path):
            warnings.append("Image %d: %s is not on this machine - the menu "
                            "can still be changed, but the card cannot be "
                            "rebuilt here." % (i, row.path))
        rows.append(row)
    return rows, warnings


def form_from_inspect(info, card, media_dir="", selector_dir=None):
    """The whole report as a :class:`MultibootForm`, plus its warnings:
    what 'Load card…' puts in the form and remembers as the baseline the
    live form is diffed against."""
    rows, warnings = rows_from_inspect(info)
    warnings = list(info.get("warnings") or []) + warnings
    if any(on_card_fields(r) for r in rows):
        # One line however many fields: the tree marks each of them '(on the
        # card)', and the point is the same for all - kept and drawn as they
        # are, replaceable, not re-makeable.
        warnings.append(
            "Some media on this card has no source recorded (the rows above "
            "mark it '(on the card)'): it is kept and drawn as it is, and "
            "can be replaced - choose auto, none or a file - but not re-made "
            "from what made it.")
    move, why = split_sound_source(info.get("sound_move"), "move sound")
    if why:
        warnings.append(why)
    confirm, why = split_sound_source(info.get("sound_confirm"),
                                      "confirm sound")
    if why:
        warnings.append(why)
    ticked, _armed = bypass_state(info)

    def _int_of(key, default):
        val = info.get(key)
        try:
            return default if val is None else int(val)
        except (TypeError, ValueError):
            return default
    form = MultibootForm(
        images=rows, out=card, sound_move=move, sound_confirm=confirm,
        volume=_int_of("volume", 50), timeout=_int_of("timeout", 15),
        default=_int_of("default", 0), bypass=ticked,
        media_dir=media_dir if (media_dir and os.path.isfile(
            os.path.join(media_dir, "media.json"))) else "",
        selector_dir=selector_dir or DEFAULT_SELECTOR_DIR)
    return form, warnings


#: The menu fields an inject rewrites, in the order the tab names them.
#: Everything NOT here is the image list, and that needs a full build.
MENU_FIELD_ORDER = ("title", "subtitle", "art", "animation", "music",
                    "move sound", "confirm sound", "volume", "countdown",
                    "default", "bypass")

#: Of those, the ones the media has to be rendered again for.
MEDIA_FIELDS = ("art", "animation", "music", "move sound", "confirm sound")


def _row_key(row):
    """What makes an image row THE SAME image: its source file, or the card
    device it came from when this machine does not have the file."""
    p = (row.path or "").strip().strip('"')
    return _norm(p) if p else "device:" + (row.device or "?")


def _menu_fields(before, after):
    """The set of menu field names that differ between two forms."""
    changed = set()
    for b, a in zip(before.images, after.images):
        if (b.title or "").strip() != (a.title or "").strip():
            changed.add("title")
        if (b.subtitle or "").strip() != (a.subtitle or "").strip():
            changed.add("subtitle")
        if art_spec(b) != art_spec(a) or b.art_on_card != a.art_on_card:
            changed.add("art")
        if anim_spec(b) != anim_spec(a) or b.anim_on_card != a.anim_on_card:
            changed.add("animation")
        if (_media_value(b.music) != _media_value(a.music)
                or b.music_on_card != a.music_on_card):
            changed.add("music")
        if (confirm_spec(b) != confirm_spec(a)
                or b.confirm_on_card != a.confirm_on_card):
            changed.add("confirm sound")
    if _media_value(before.sound_move) != _media_value(after.sound_move):
        changed.add("move sound")
    if _media_value(before.sound_confirm) != _media_value(after.sound_confirm):
        changed.add("confirm sound")
    for name, b, a in (("volume", before.volume, after.volume),
                       ("countdown", before.timeout, after.timeout),
                       ("default", before.default, after.default)):
        if int(b) != int(a):
            changed.add(name)
    if bool(before.bypass) != bool(after.bypass):
        changed.add("bypass")
    return changed


def diff_forms(before, after):
    """``(menu, rebuild)`` - what changed since the card was loaded, in the
    two buckets the tab acts on: *menu* is what 'Apply to card' writes with
    an inject, *rebuild* is what only 'Build & verify' can do (the image
    list: its length, its order, the files themselves)."""
    rebuild = []
    b_keys = [_row_key(r) for r in before.images]
    a_keys = [_row_key(r) for r in after.images]
    if len(b_keys) != len(a_keys):
        rebuild.append("%d image%s -> %d" % (len(b_keys),
                                             "" if len(b_keys) == 1 else "s",
                                             len(a_keys)))
    elif b_keys != a_keys:
        rebuild.append("reordered" if sorted(b_keys) == sorted(a_keys)
                       else "an image was replaced")
    menu = [f for f in MENU_FIELD_ORDER if f in _menu_fields(before, after)]
    return menu, rebuild


def media_specs_changed(before, after):
    """Whether the media has to be rendered again before an inject - the
    art, animation, music and the two sounds.  The volume is not here: it
    reaches the card through images.conf, which the inject writes."""
    if len(before.images) != len(after.images):
        return True
    return any(f in MEDIA_FIELDS for f in _menu_fields(before, after))


def edit_status_text(card, menu, rebuild):
    """The tab's one line about a loaded card: what Apply to card would
    write, or why only a rebuild can."""
    name = os.path.basename(card) or card
    if rebuild:
        msg = ("The image list changed (%s) - Build & verify writes a new "
               "card; Apply to card only rewrites the menu of %s."
               % ("; ".join(rebuild), name))
        if menu:
            msg += "  %d menu change%s would ride along: %s." % (
                len(menu), "" if len(menu) == 1 else "s", ", ".join(menu))
        return msg
    if not menu:
        return ("Editing %s: no changes yet. Every field above came off the "
                "card; change one and Apply to card writes it back in "
                "seconds." % name)
    return "Apply to card: %d menu change%s (%s) -> %s, no rebuild." % (
        len(menu), "" if len(menu) == 1 else "s", ", ".join(menu), name)


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
# what the compact list and the Menu settings button say
# ---------------------------------------------------------------------------

def _shorten(text, width=40):
    """*text* with its middle replaced by ``…`` so it cannot widen a column.
    The end is what identifies a path, so the end is what is kept."""
    text = text or ""
    if len(text) <= width or width < 6:
        return text
    head = max(3, width // 3)
    return text[:head] + "…" + text[-(width - head - 1):]


def _cell(value):
    """A media field as one word or one file name."""
    v = (value or "").strip()
    return v if v.lower() in _WORDS or not v else os.path.basename(v)


def _cell_image(row):
    """The .raw the image was copied from, said plainly when this machine
    does not have it (a loaded card names sources that may live on another
    disk) and when the card names none at all."""
    p = (row.path or "").strip()
    if not p:
        return "(no source recorded%s)" % (
            " - " + row.device if row.device else "")
    if not os.path.isfile(p):
        return p + "   [not on this machine]"
    return p


def cell_art(row):
    """The row's art in full: the word, a picture's name, or ``<video> @3s``.
    What the Edit image… dialog's own summary would say."""
    v = (row.art or "").strip()
    if row.art_on_card:
        return v + " (on the card)"
    if v.lower() == "video frame":
        name = os.path.basename((row.art_video or "").strip()) or "video?"
        return "%s @%ss" % (name, _num(row.art_time, "0"))
    if is_video(v):
        return "%s @%ss" % (os.path.basename(v), _num(row.art_time, "0"))
    return _cell(v)


def cell_anim(row):
    """The row's animation in full: the word or the clip's name, and the clip
    parameters when any is set (``auto @20s 2s 8fps``)."""
    v = _cell(row.anim)
    if row.anim_on_card:
        return v + " (on the card)"
    if v and v.lower() != "none":
        start, secs, fps = (_num(row.anim_start), _num(row.anim_seconds),
                            _num(row.anim_fps))
        if start or secs or fps:
            v += " @%ss %ss %sfps" % (start or ANIM_DEFAULTS[0],
                                      secs or ANIM_DEFAULTS[1],
                                      fps or ANIM_DEFAULTS[2])
    return v


def list_title(row, index=0):
    """The list's Title cell: the menu title (or the name the tab would fall
    back to), and - because a list with no Image column must still say it -
    what is wrong with the .raw this image came from."""
    title = (row.title or "").strip()
    path = (row.path or "").strip().strip('"')
    if not title:
        title = suggest_title(path)[0] if path else "image %d" % index
    if not path:
        return "%s  [no source recorded]" % title
    if not os.path.isfile(path):
        return "%s  [not on this machine]" % title
    return title


def menu_summary(form):
    """The one line beside the 'Menu settings…' button: everything behind it,
    in the order the dialog asks for it."""
    def sound(v):
        v = (v or "").strip() or "none"
        return v if v.lower() in _WORDS else os.path.basename(v)
    return ("sounds %s / %s  ·  volume %d  ·  %s  ·  default %d  ·  "
            "bypass %s" % (
                sound(form.sound_move), sound(form.sound_confirm),
                int(form.volume),
                "wait for START" if int(form.timeout) == 0
                else "%d s countdown" % int(form.timeout),
                int(form.default), "on" if form.bypass else "off"))


# ---------------------------------------------------------------------------
# the two modals the detail lives behind
# ---------------------------------------------------------------------------

def _browse_into(var, filetypes, title="Pick a media file"):
    """A file picker that writes the chosen path into *var*."""
    path = filedialog.askopenfilename(
        title=title, filetypes=list(filetypes) + [("All files", "*.*")])
    if path:
        var.set(path)


def _media_row(parent, row, col, label, var, choices, filetypes,
               label_w=13, combo_w=26):
    """Label + editable combobox (the words, or a typed path) + Browse.
    ``(combobox, browse button)``."""
    # 13, not 10: "Move sound:" is eleven characters and a 10-wide ttk label
    # showed "Move soun" (the tab's first screenshot).
    kw = {"width": label_w} if col == 0 else {}
    ttk.Label(parent, text=label, **kw).grid(
        row=row, column=col, sticky=tk.W, padx=(0 if col == 0 else 12, 4),
        pady=3)
    cb = ttk.Combobox(parent, textvariable=var, values=list(choices),
                      width=combo_w)
    cb.grid(row=row, column=col + 1, sticky=tk.EW, pady=3)
    btn = ttk.Button(parent, text="Browse…", width=9,
                     command=lambda: _browse_into(var, filetypes))
    btn.grid(row=row, column=col + 2, sticky=tk.W, padx=(4, 0), pady=3)
    return cb, btn


class _Modal:
    """The app's modal shape, in one place: a transient, grabbed Toplevel
    centred over the window, OK / Cancel at the bottom right, Escape and the
    window's close box both meaning Cancel.

    The dialogs below edit the panel's OWN variables (the same ones the tab
    has always carried, so every trace, every diff and every test still sees
    one source of truth) and hand back a snapshot to restore on Cancel."""

    def __init__(self, parent, title, theme_fn, on_ok=None, on_cancel=None):
        self._parent = parent
        self._theme_fn = theme_fn
        self._on_ok = on_ok
        self._on_cancel = on_cancel
        self._closed = False
        th = THEMES.get(theme_fn()) or THEMES["dark"]
        top = tk.Toplevel(parent)
        self.top = top
        # Hidden until built and positioned, or it flashes at the default
        # spot first (the app's own rule - see disk_dialog).
        top.withdraw()
        top.title(title)
        try:
            top.configure(bg=th["bg"])
        except tk.TclError:
            pass
        dark_titlebar(top, th is THEMES.get("dark"))
        try:
            top.transient(parent.winfo_toplevel())
        except tk.TclError:
            pass
        top.protocol("WM_DELETE_WINDOW", self.cancel)
        top.bind("<Escape>", lambda _e: self.cancel())
        top.resizable(False, False)
        self.body = ttk.Frame(top, padding=14)
        self.body.pack(fill=tk.BOTH, expand=True)

    def show(self):
        """Add the OK / Cancel row, place the window and take the grab."""
        row = ttk.Frame(self.body)
        row.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(row, text="Cancel", width=10,
                   command=self.cancel).pack(side=tk.RIGHT)
        self.ok_btn = ttk.Button(row, text="OK", width=10, command=self.ok,
                                 style="Go.TButton")
        self.ok_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self.top.bind("<Return>", lambda _e: self.ok())
        center_over(self._parent, self.top)
        try:
            self.top.deiconify()
            self.top.grab_set()
            self.top.focus_set()
        except tk.TclError:
            pass
        # Again, and this time the window exists: DWM ignores the immersive
        # dark-mode attribute set on a withdrawn Toplevel, and a light title
        # bar over a dark dialog is exactly the complaint theme.py's
        # dark_titlebar was written for.
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        dark_titlebar(self.top, th is THEMES.get("dark"))
        return self

    def ok(self):
        self._close(True)

    def cancel(self):
        self._close(False)

    def _close(self, accepted):
        if self._closed:
            return
        self._closed = True
        cb = self._on_ok if accepted else self._on_cancel
        for fn in (self.top.grab_release, self.top.destroy):
            try:
                fn()
            except tk.TclError:
                pass
        if cb is not None:
            cb()


class ImageEditorDialog(_Modal):
    """'Edit image…': one image's menu text and its three media fields.

    Everything that used to be a permanent editor strip under the list -
    title, subtitle, art (including the 'video frame' pair), animation
    (including the clip's start / length / fps) and music."""

    def __init__(self, panel, index, row):
        _Modal.__init__(
            self, panel._parent,
            "Edit image %d — %s" % (index, os.path.basename(
                (row.path or "").strip()) or row.device or "no source"),
            panel._theme_fn, on_ok=panel._image_editor_ok,
            on_cancel=panel._image_editor_cancel)
        b = self.body
        th = THEMES.get(panel._theme_fn()) or THEMES["dark"]
        ttk.Label(b, text=_cell_image(row), foreground=th["gray"],
                  wraplength=520, justify=tk.LEFT).pack(anchor=tk.W,
                                                        pady=(0, 10))
        text = ttk.Frame(b)
        text.pack(fill=tk.X)
        ttk.Label(text, text="Title:", width=13).grid(row=0, column=0,
                                                      sticky=tk.W, pady=3)
        ttk.Entry(text, textvariable=panel._ed_title, width=34).grid(
            row=0, column=1, sticky=tk.EW, pady=3)
        ttk.Label(text, text="Subtitle:", width=13).grid(row=1, column=0,
                                                         sticky=tk.W, pady=3)
        ttk.Entry(text, textvariable=panel._ed_sub, width=34).grid(
            row=1, column=1, sticky=tk.EW, pady=3)
        text.columnconfigure(1, weight=1)

        art = ttk.LabelFrame(b, text="Picture")
        art.pack(fill=tk.X, pady=(12, 0))
        g = ttk.Frame(art)
        g.pack(fill=tk.X, padx=8, pady=6)
        _media_row(g, 0, 0, "Art:", panel._ed_art, ART_CHOICES,
                   [("Pictures", "*.png *.jpg *.jpeg"),
                    ("Videos", "*.mp4 *.mov *.mkv *.avi")])
        # 13, not 12: "Video frame:" is twelve characters and a 12-wide ttk
        # label clips the colon.
        ttk.Label(g, text="Video frame:", width=13).grid(
            row=1, column=0, sticky=tk.W, pady=3)
        panel._video_entry = ttk.Entry(g, textvariable=panel._ed_art_video,
                                       width=26)
        panel._video_entry.grid(row=1, column=1, sticky=tk.EW, pady=3)
        panel._video_btn = ttk.Button(
            g, text="Browse…", width=9,
            command=lambda: _browse_into(
                panel._ed_art_video,
                [("Videos", "*.mp4 *.mov *.mkv *.avi")]))
        panel._video_btn.grid(row=1, column=2, sticky=tk.W, padx=(4, 0),
                              pady=3)
        vt = ttk.Frame(g)
        vt.grid(row=2, column=1, sticky=tk.W, pady=3)
        ttk.Label(vt, text="frame at (s):").pack(side=tk.LEFT)
        panel._video_time = ttk.Spinbox(vt, from_=0, to=36000, increment=0.5,
                                        width=7,
                                        textvariable=panel._ed_art_time)
        panel._video_time.pack(side=tk.LEFT, padx=(6, 0))
        g.columnconfigure(1, weight=1)

        clipbox = ttk.LabelFrame(b, text="Animation")
        clipbox.pack(fill=tk.X, pady=(10, 0))
        g2 = ttk.Frame(clipbox)
        g2.pack(fill=tk.X, padx=8, pady=6)
        _media_row(g2, 0, 0, "Animation:", panel._ed_anim, ANIM_CHOICES,
                   [("Animations", "*.gif *.mp4 *.mov *.mkv *.avi")])
        ttk.Label(g2, text="Clip:", width=13).grid(row=1, column=0,
                                                   sticky=tk.W, pady=3)
        clip = ttk.Frame(g2)
        clip.grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=3)
        panel._clip_widgets = []
        for label, var, width in (("Start (s):", panel._ed_anim_start, 6),
                                  ("Length (s):", panel._ed_anim_seconds, 5),
                                  ("FPS:", panel._ed_anim_fps, 4)):
            ttk.Label(clip, text=label).pack(
                side=tk.LEFT, padx=(0 if not panel._clip_widgets else 10, 4))
            sp = ttk.Spinbox(clip, from_=0, to=36000, width=width,
                             textvariable=var)
            sp.pack(side=tk.LEFT)
            panel._clip_widgets.append(sp)
        g2.columnconfigure(1, weight=1)

        soundbox = ttk.LabelFrame(b, text="Sounds")
        soundbox.pack(fill=tk.X, pady=(10, 0))
        snd = ttk.Frame(soundbox)
        snd.pack(fill=tk.X, padx=8, pady=6)
        # 15, not 13: "Confirm sound:" is fourteen characters, the same
        # measurement Menu settings… already had to make for this label.
        _media_row(snd, 0, 0, "Music:", panel._ed_music, MUSIC_CHOICES,
                   [("WAV audio", "*.wav")], label_w=15)
        _media_row(snd, 1, 0, "Confirm sound:", panel._ed_confirm,
                   IMAGE_CONFIRM_CHOICES, [("WAV audio", "*.wav")],
                   label_w=15)
        snd.columnconfigure(1, weight=1)
        ttk.Label(b, foreground=th["gray"], wraplength=520, justify=tk.LEFT,
                  text="auto = this image's own logo and attract clip, pulled "
                       "off the .raw; none = text only. Clip fields left "
                       "blank use the tool's defaults (from 0 s, 3 s long, "
                       "10 fps). The confirm sound is what plays when THIS "
                       "image is chosen; menu = the one the whole menu "
                       "uses.").pack(anchor=tk.W, pady=(10, 0))


class MenuSettingsDialog(_Modal):
    """'Menu settings…': the sounds, the volume, the countdown, the default
    image, the validator bypass and the selector build path - everything
    that belongs to the MENU rather than to one image."""

    def __init__(self, panel, images):
        _Modal.__init__(self, panel._parent, "Menu settings",
                        panel._theme_fn, on_ok=panel._menu_settings_ok,
                        on_cancel=panel._menu_settings_cancel)
        b = self.body
        th = THEMES.get(panel._theme_fn()) or THEMES["dark"]
        sounds = ttk.LabelFrame(b, text="Sounds")
        sounds.pack(fill=tk.X)
        g = ttk.Frame(sounds)
        g.pack(fill=tk.X, padx=8, pady=6)
        # 15, not 13: "Confirm sound:" is fourteen characters and a 13-wide
        # ttk label showed "Confirm sounc" (the first shot of this dialog).
        _media_row(g, 0, 0, "Move sound:", panel._move_var, SOUND_CHOICES,
                   [("WAV audio", "*.wav")], label_w=15)
        _media_row(g, 1, 0, "Confirm sound:", panel._confirm_var,
                   SOUND_CHOICES, [("WAV audio", "*.wav")], label_w=15)
        ttk.Label(g, text="Volume:", width=15).grid(row=2, column=0,
                                                    sticky=tk.W, pady=3)
        vol = ttk.Frame(g)
        vol.grid(row=2, column=1, sticky=tk.W, pady=3)
        ttk.Spinbox(vol, from_=0, to=100, width=5,
                    textvariable=panel._volume_var).pack(side=tk.LEFT)
        ttk.Label(vol, text="0-100", foreground=th["gray"]).pack(
            side=tk.LEFT, padx=(6, 0))
        ttk.Label(g, foreground=th["gray"], wraplength=430, justify=tk.LEFT,
                  text="auto = a click and a stinger pulled from the primary "
                       "image; synth = generated tones. The confirm sound "
                       "plays to the end before the game starts.").grid(
            row=3, column=0, columnspan=3, sticky=tk.W, pady=(4, 0))
        g.columnconfigure(1, weight=1)

        boot = ttk.LabelFrame(b, text="At power-up")
        boot.pack(fill=tk.X, pady=(10, 0))
        g2 = ttk.Frame(boot)
        g2.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(g2, text="Countdown (s):", width=15).grid(
            row=0, column=0, sticky=tk.W, pady=3)
        cd = ttk.Frame(g2)
        cd.grid(row=0, column=1, sticky=tk.W, pady=3)
        ttk.Spinbox(cd, from_=0, to=600, width=5,
                    textvariable=panel._timeout_var).pack(side=tk.LEFT)
        ttk.Label(cd, text="0 = wait for START",
                  foreground=th["gray"]).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(g2, text="Default image:", width=15).grid(
            row=1, column=0, sticky=tk.W, pady=3)
        di = ttk.Frame(g2)
        di.grid(row=1, column=1, sticky=tk.W, pady=3)
        panel._default_spin = ttk.Spinbox(
            di, from_=0, to=max(0, images - 1), width=5,
            textvariable=panel._default_var)
        panel._default_spin.pack(side=tk.LEFT)
        ttk.Label(di, text="highlighted at power-up (the last choice wins "
                           "once one was made)",
                  foreground=th["gray"]).pack(side=tk.LEFT, padx=(6, 0))
        byp = ttk.Frame(g2)
        byp.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        panel._bypass_chk = ttk.Checkbutton(
            byp, text="Bypass game validation on every image",
            variable=panel._bypass_var)
        panel._bypass_chk.pack(side=tk.LEFT)
        panel._bypass_badge = panel._info_badge(byp, panel.BYPASS_TIP)
        panel._bypass_badge.pack(side=tk.LEFT, padx=(6, 0))
        g2.columnconfigure(1, weight=1)

        adv = ttk.LabelFrame(b, text="Advanced")
        adv.pack(fill=tk.X, pady=(10, 0))
        g3 = ttk.Frame(adv)
        g3.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(g3, text="Selector build:", width=15).grid(
            row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(g3, textvariable=panel._selector_var, width=40).grid(
            row=0, column=1, sticky=tk.EW, pady=3)
        ttk.Label(g3, foreground=th["gray"], wraplength=430, justify=tk.LEFT,
                  text="WSL path of the built selector (the rig installs it "
                       "there on the first Boot-selector run)").grid(
            row=1, column=1, sticky=tk.W)
        g3.columnconfigure(1, weight=1)


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

    #: What the tab's lines are tagged with in the app's shared Log, so
    #: they read beside the other tabs' ("[emulate] …" and the rest).
    LOG_TAG = "[multi-boot] "

    #: How many of them the panel keeps for itself (:meth:`log_lines`).
    #: The app's Log keeps its own, longer, history.
    LOG_KEEP = 3000

    #: How often the main loop drains the worker's queue while a run is up.
    DRAIN_MS = 50

    #: Play's frame period (~8 fps).
    PLAY_MS = 1000 // PREVIEW_FPS

    #: How long the selector the preview draws with is taken on trust
    #: before the ``make`` step is run again (see _render_frames).
    SELECTOR_TTL_S = 300

    ABOUT_TIP = ("Builds ONE SD card that carries several complete game "
                 "images and a menu at power-up: the flippers choose, START "
                 "boots, a countdown boots the remembered choice - stock "
                 "code and a custom build on the same machine without "
                 "swapping cards. The first image in the list is the "
                 "primary: its boot files are the card's, and the machine "
                 "falls back to it. The media and the card itself are made "
                 "by the rig's tools under WSL; nothing here touches the "
                 "images you pick. GIVE EVERY IMAGE THE SAME GAME CODE "
                 "VERSION: the machine keeps one set of settings, audits and "
                 "scores for the game, and one set of node board firmware, "
                 "so images that disagree cost you settings and can reflash "
                 "the boards on every swap. The version is read off each "
                 "image and shown in the Code column. Press ? for the whole "
                 "story.")

    # USER-FACING COPY IS GENERIC.  Nothing the tab says names a title, a
    # build or a version as an example (David, 2026-09-02: most people
    # using this have never heard of the card it was written for) - what a
    # control does, and why, in words that hold for any Spike 2 card.
    BYPASS_TIP = ("Neuters the game's validator in every image on the card "
                  "(a four-byte patch at the validator's entry, with that "
                  "image's package index record refreshed). Without it the "
                  "machine can show GAME VALIDATION ERROR, because the "
                  "images share one grade state and an unpatched image "
                  "fails once a second image sits beside it.")

    #: The one quiet line under the table while nothing is selected.  It is
    #: all the teaching the icons need; the rest is in the tooltip.
    ROW_HINT = ("The icons on each row edit, remove and reorder it — the "
                "first image is the primary the machine falls back to.")

    LIST_TIP = ("Each row carries its own icons: ✎ edits the image, − takes "
                "it off the card, ▲ / ▼ move it in the menu's order (the "
                "outlined arrow means that row cannot go further). The last "
                "row adds one. A double-click or Enter opens a row, and a "
                "right-click - or the menu key - offers the same five "
                "commands. The first image is the PRIMARY: its boot files "
                "are the card's, and the machine falls back to it.")

    PREVIEW_TIP = ("The boot menu as the machine will draw it. It redraws "
                   "itself about a third of a second after you stop typing; "
                   "right-click it to redraw now or to turn that off.")

    def __init__(self, parent, log=None, theme_fn=None, badge_fn=None,
                 resize_fn=None, flash_fn=None, emulate_fn=None,
                 phase_fn=None):
        self._parent = parent
        self._log_sink = log or (lambda msg: None)
        self._theme_fn = theme_fn or (lambda: "dark")
        self._badge_fn = badge_fn
        self._resize_fn = resize_fn or (lambda: None)
        #: The app's footer, as far as this tab is concerned: the stage row
        #: that belongs to THIS tab's buttons and the bar beside it
        #: (MainWindow.set_multiboot_phase).  A panel built on its own -
        #: every test - drives nothing.
        self._phase_fn = phase_fn or (lambda index, total=None, status=None:
                                      None)
        #: The app's Build / flash flow, handed the finished .raw.  None
        #: (a panel built on its own, every test) greys the button.
        self._flash_fn = flash_fn
        #: The Emulate tab's launch, handed the finished .raw: it sets the
        #: card, ticks Boot selector (PAD_SELECT=1) and starts the rig.
        self._emulate_fn = emulate_fn
        self._rows = []                 # list[ImageRow], card order
        #: The guard on the runs that WRITE something (build, apply, load,
        #: bypass): one at a time, and every action control greyed while
        #: one is up.  The preview has its own, lighter one - see
        #: ``_pv_busy``: a background redraw must not disable the tab.
        self._busy = False
        self._pv_busy = False           # a preview render is on the worker
        self._pv_cancel = False         # ...and an action is waiting for it
        self._pending_run = None        # the action waiting (_run_commands)
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
        #: The size sentence the last plan printed.  It shares the status
        #: block's second line with 'what Apply to card would write': the
        #: block is two lines, and both of these are the same question -
        #: what the button under them would do.
        self._plan_text = ""
        #: The two modals.  Their widgets are built on demand and bound to
        #: the panel's own variables, so the tab has one form whether a
        #: dialog is open or not (and the tests can drive either).
        self._image_dialog = None
        self._menu_dialog = None
        self._edit_backup = None        # the row a cancelled edit restores
        self._menu_backup = None
        #: Widgets that live only while a dialog is up.
        self._video_entry = self._video_btn = self._video_time = None
        self._clip_widgets = ()
        self._default_spin = None
        self._bypass_chk = None
        #: Every line the tools print, in the order they printed it.  The
        #: tab has NO output pane of its own: the lines go to the app's Log
        #: at the foot of the window, the one log the whole app writes to
        #: (David, 2026-09-02: "why is the tool output separate from the
        #: logs section at the bottom?").  This is the same list, kept so a
        #: message the one-line status block had to clip can still be
        #: read back - and so the tests can read what was said.
        self._lines = []
        #: EDITING MODE.  Set by a load: the card the form came off, the
        #: directory its media was extracted into, the form as it was read
        #: (the baseline every diff is against), the report itself, and
        #: whether any games tree is still un-bypassed.  ``_loaded_card`` is
        #: "" for the ordinary build-a-new-card flow.
        self._loaded_card = ""
        self._loaded_form = None
        self._loaded_info = None
        self._armed = False
        self._media_override = ""       # the loaded card's media dir
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
        self._ed_confirm = tk.StringVar(value="menu")
        self._ed_art_video = tk.StringVar()
        self._ed_art_time = tk.StringVar()
        self._ed_anim_start = tk.StringVar()
        self._ed_anim_seconds = tk.StringVar()
        self._ed_anim_fps = tk.StringVar()
        for var in (self._ed_title, self._ed_sub, self._ed_art,
                    self._ed_anim, self._ed_music, self._ed_confirm,
                    self._ed_art_video, self._ed_art_time,
                    self._ed_anim_start, self._ed_anim_seconds,
                    self._ed_anim_fps):
            var.trace_add("write", lambda *_a: self._editor_changed())
        # ...and the menu's own fields, so the 'what would Apply write' line
        # follows every keystroke while a card is loaded.
        for var in (self._move_var, self._confirm_var, self._volume_var,
                    self._timeout_var, self._default_var, self._bypass_var):
            var.trace_add("write", lambda *_a: self._menu_changed())
        # The preview.  Frames are cached per (form fingerprint, highlight,
        # frame index) -> PPM path; the frame counts per (fingerprint,
        # highlight), learned from the selector's own log line.
        self._hl_var = tk.StringVar(value="0")
        self._frame_var = tk.StringVar(value="0")
        self._play_var = tk.BooleanVar(value=False)
        self._pv_cache = {}
        self._pv_totals = {}
        self._pv_bin = ""               # the selector the last run named
        self._pv_bin_at = 0.0           # ...and when it named it
        #: (MEDIA fingerprint, media DIR) that is prepared.  The directory
        #: belongs in the key: it is derived from the output path, which
        #: media_fingerprint deliberately excludes - so retyping the output
        #: left the prepared media in the OLD directory and the new one
        #: empty, and the next build wrote a text-only card.
        self._pv_ready = None
        #: Directories the preview made for itself, so a half-typed output
        #: path does not leave a preview/ and a media/ behind on disk.
        self._pv_made = set()
        self._pv_photo = None           # PhotoImage ref (must stay alive)
        self._pv_shown = None           # (highlight, frame) on the canvas
        self._pv_src = None             # (ppm, highlight, frame, total) shown
        self._pv_loading = False        # a programmatic spinbox write
        self._hl_touched = False        # Highlight typed by hand: stop following Default
        self._play_job = None
        self._play_fp = None
        self._play_hl = 0
        #: THE PREVIEW FOLLOWS THE FORM.  Every field schedules a re-render
        #: ~350 ms after the last keystroke, coalesced into one run: a text
        #: change costs one snapshot, only a media change pays for a
        #: prepare (see :func:`media_fingerprint`).  ``PAD_MULTIBOOT_AUTO=0``
        #: and the panel flag both turn it off - the screenshot rig and most
        #: tests want a tab that starts no tools by itself.
        self._auto_preview = tk.BooleanVar(
            value=os.environ.get("PAD_MULTIBOOT_AUTO", "1") != "0")
        self._pv_debounce_job = None
        self._pv_pending = 0            # renders coalesced by the debounce
        #: The size of the preview box the window currently has room for.
        self._pv_w, self._pv_h = PREVIEW_W, PREVIEW_H
        #: A corrected 'Selector build' path, or one the rig has just
        #: installed, must be picked up - the binary the last run named is
        #: not the answer for a different path.
        self._selector_var.trace_add("write",
                                     lambda *_a: setattr(self, "_pv_bin", ""))
        self._default_var.trace_add("write", lambda *_a: self._follow_default())
        self._hl_var.trace_add("write", lambda *_a: self._hl_changed(typed=True))
        self._frame_var.trace_add("write",
                                  lambda *_a: self._frame_changed(typed=True))
        # ...and everything that changes the picture asks for a re-render.
        for var in (self._ed_title, self._ed_sub, self._ed_art, self._ed_anim,
                    self._ed_music, self._ed_confirm, self._ed_art_video,
                    self._ed_art_time, self._ed_anim_start,
                    self._ed_anim_seconds, self._ed_anim_fps,
                    self._move_var, self._confirm_var, self._volume_var,
                    self._timeout_var, self._default_var,
                    self._out_var, self._selector_var):
            var.trace_add("write", lambda *_a: self.schedule_preview())

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
        if self._busy or self._pv_busy or not self._queue.empty():
            try:
                self._drain_job = self._timer().after(self.DRAIN_MS,
                                                      self._drain)
            except tk.TclError:
                pass

    def _on_destroy(self, event=None):
        if event is not None and str(event.widget) != str(self._parent):
            return
        self._stopped = True
        for attr in ("_drain_job", "_play_job", "_pv_debounce_job"):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self._timer().after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
                setattr(self, attr, None)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def build(self, frame):
        """THE SHAPE OF THE TAB - ONE COLUMN, top to bottom, in the order a
        person works:

        1. where the card comes from - Load card… / New card… and the path,
        2. the PREVIEW, the full width of the tab and the centre of it,
        3. the IMAGES TABLE right underneath, as wide as the tab: one row
           per image carrying that image's own settings in columns, four
           icon columns at the right edge that act on the row they sit in,
           and a dim '+ Add an image…' row at the bottom that adds one,
        4. one bottom bar - Menu settings… on the left, the actions on the
           right - and the status under it.

        No side-by-side columns and no reflow: the arrangement is the same
        at every width, and the width the window gives goes to the picture
        and to the table's own columns.  The detail the table has no room
        for is behind two modals, and the tools' own output goes to the
        app's Log at the foot of the window - the one log the whole app
        writes to - rather than to a pane of this tab's own."""
        self._frame = frame
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        outer = ttk.Frame(frame)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 6))
        self._outer = outer
        self._build_source(outer, th)
        self._build_alarm(outer, th)
        self._build_preview(outer, th)
        self._build_table(outer, th)
        self._build_actions(outer, th)
        self._build_status(outer, th)
        frame.bind("<Destroy>", self._on_destroy, add="+")
        outer.bind("<Configure>", self._on_configure, add="+")
        self._set_busy(False)
        self._sync_editor_states()
        self._update_menu_summary()
        self._refresh_tree()
        self._pv_placeholder()
        self._ok("Load a card you already built, or press + in the table to "
                 "add the first image.")

    # -- 1. where the card comes from ----------------------------------

    def _build_source(self, parent, th):
        """The first row, because loading a card you already built is the
        first thing anyone does here."""
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        self._src_row = row
        self._load_btn = ttk.Button(row, text="Load card…", width=12,
                                    command=self._load_card_dialog)
        self._load_btn.pack(side=tk.LEFT)
        self._load_tip = _Tooltip(
            self._load_btn,
            "Reads a multi-image card you already built and fills every "
            "field from it - images, titles, subtitles, art, animation, "
            "music, sounds, volume, countdown, default and bypass. The "
            "preview then draws THAT card's menu, and Apply to card writes "
            "your changes back into it in seconds.", self._theme_fn)
        self._new_btn = ttk.Button(row, text="New card…", width=11,
                                   command=self._new_card_clicked)
        self._new_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._new_tip = _Tooltip(
            self._new_btn,
            "Starts a fresh card: clears the images and the menu, and "
            "leaves editing mode so Build & verify writes a new image.",
            self._theme_fn)
        ttk.Label(row, text="Card image:").pack(side=tk.LEFT, padx=(16, 6))
        # The tab's own "what is this" lives here rather than in a
        # paragraph across the top: the picture below is the subject, and
        # the ? button carries the rest.
        self._about_badge = self._info_badge(row, self.ABOUT_TIP)
        self._about_badge.pack(side=tk.RIGHT, padx=(8, 0))
        self._browse_btn = ttk.Button(row, text="Browse…", width=10,
                                      command=self._browse_out)
        self._browse_btn.pack(side=tk.RIGHT)
        self._out_entry = ttk.Entry(row, textvariable=self._out_var)
        self._out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True,
                             padx=(0, 6))

    #: What the strip says before the sentence the tool wrote.  A card
    #: whose images disagree still boots and still plays - what it costs is
    #: settings and, at worst, a node board reflash on every swap - so this
    #: is a warning in the app's error colour, not a refusal.  The refusal
    #: is the builder's, and it happens before a byte is written.
    ALARM_PREFIX = "\u26a0 "

    def _build_alarm(self, parent, th):
        """The version banner: nothing at all until a card's images
        disagree, and then a filled bar across the whole tab, directly above
        the picture.

        A BAR RATHER THAN COLOURED TEXT.  The first version of this was one
        red line above a large dark picture and it read as a footnote; what
        this is warning about is a card that costs you settings and can
        reflash the node boards on every swap, so it gets the weight of the
        app's destructive-action colour and the full width.

        It takes vertical space only when there is something wrong, which is
        what lets it be loud - the tab still fits a 768-high desktop in the
        ordinary case, and a mismatch is not the ordinary case.  Raw tk
        rather than ttk: a filled background is what makes it a banner, and
        ttk styles it per style rather than per widget.  The colours are
        re-read on every raise, so a theme change follows on the next load
        (the same bargain the preview canvas makes)."""
        self._alarm_box = tk.Frame(parent, bg=th["danger_btn"])
        self._alarm = tk.Label(self._alarm_box, text="", bg=th["danger_btn"],
                               fg="#ffffff", anchor=tk.W, justify=tk.LEFT,
                               padx=10, pady=5,
                               font=("Segoe UI", 9, "bold"))
        self._alarm.pack(fill=tk.X)
        self._alarm_tip = _Tooltip(self._alarm, "", self._theme_fn)
        self._alarm_text = ""

    def _show_alarm(self, info):
        """Put the version gate's finding on the tab, or take it away.

        Called with the report a load read; ``None`` clears it (a new card,
        or one whose images agree).  The whole finding goes to the Log -
        the strip is one line by construction and the reasons run long."""
        found = version_alarm(info or {}) if info else None
        head, full = found if found else ("", "")
        if full and full != getattr(self, "_alarm_text", ""):
            for line in full.splitlines():
                if line.strip():
                    self._write("[version] " + line)
        self._alarm_text = full
        box, lbl = (getattr(self, "_alarm_box", None),
                    getattr(self, "_alarm", None))
        if box is None or lbl is None:                  # pragma: no cover
            return
        try:
            if not full:
                box.pack_forget()
                return
            th = THEMES.get(self._theme_fn()) or THEMES["dark"]
            box.configure(bg=th["danger_btn"])
            lbl.configure(text=self._status_line(self.ALARM_PREFIX + head),
                          bg=th["danger_btn"])
            self._alarm_tip.text = full
            if not box.winfo_manager():
                # BEFORE the preview, not at the end of the tab: pack()
                # appends, and this belongs between the card and its picture
                # where the eye goes first.
                box.pack(fill=tk.X, pady=(6, 0), before=self._pv_wrap)
        except tk.TclError:                             # pragma: no cover
            pass
        self._remeasure()

    def _remeasure(self):
        """The tab is a different height, so the picture has a different
        amount of room; re-measure once the new requested sizes settle."""
        try:
            self._resize_fn()
            self._timer().after_idle(self._on_configure)
        except tk.TclError:                             # pragma: no cover
            pass

    # -- 2. the preview, full width -------------------------------------

    def _build_preview(self, parent, th):
        """The preview: the boot menu as the machine will draw it, the
        whole width of the tab, re-rendered by itself whenever a field
        changes.  No button of its own - the redraw and the auto-update
        toggle are on its right-click menu, where a control nobody needs
        twice a session belongs."""
        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.X, pady=(8, 0))
        self._pv_wrap = wrap
        holder = ttk.Frame(wrap)
        holder.pack(fill=tk.X)
        self._pv_holder = holder
        # Not packed with fill: the canvas is sized to the PICTURE (see
        # _on_configure), so there are no black bars around it, and it is
        # centred in whatever width is left over.
        self._pv_canvas = tk.Canvas(
            holder, width=self._pv_w, height=self._pv_h, bg="#0b0e14",
            highlightthickness=1, highlightbackground=th["border"], bd=0)
        self._pv_canvas.pack()
        strip = ttk.Frame(wrap, height=30)
        strip.pack(fill=tk.X, pady=(4, 0))
        strip.pack_propagate(False)
        self._pv_strip = strip
        ttk.Label(strip, text="Image:").pack(side=tk.LEFT, padx=(0, 3))
        self._hl_spin = ttk.Spinbox(strip, from_=0, to=0, width=4,
                                    textvariable=self._hl_var,
                                    command=self._hl_changed)
        self._hl_spin.pack(side=tk.LEFT)
        ttk.Label(strip, text="Frame:").pack(side=tk.LEFT, padx=(10, 3))
        self._frame_spin = ttk.Spinbox(strip, from_=0, to=999, width=4,
                                       textvariable=self._frame_var,
                                       command=self._frame_changed)
        self._frame_spin.pack(side=tk.LEFT)
        self._play_chk = ttk.Checkbutton(strip, text="Play",
                                         variable=self._play_var,
                                         command=self._play_toggled)
        self._play_chk.pack(side=tk.LEFT, padx=(8, 0))
        self._pv_status = ttk.Label(strip, text="", width=1,
                                    justify=tk.LEFT, anchor=tk.W)
        self._pv_status.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                             padx=(12, 0))
        self._pv_tip = _Tooltip(self._pv_canvas, self.PREVIEW_TIP,
                                self._theme_fn)
        self._build_preview_menu()

    def _build_preview_menu(self):
        """'Redraw now' and 'Update automatically', on the picture itself.
        There is no Render now BUTTON: the preview follows the form by
        itself, and a manual redraw is a once-a-session thing."""
        menu = tk.Menu(self._pv_canvas, tearoff=0)
        menu.add_command(label="Redraw the preview now",
                         command=self.render_preview)
        menu.add_checkbutton(label="Update the preview automatically",
                             variable=self._auto_preview,
                             command=self.schedule_preview)
        self._pv_menu = menu
        for widget in (self._pv_canvas, self._pv_strip):
            widget.bind("<Button-3>", self._popup_preview_menu)

    def _popup_preview_menu(self, event=None):
        menu = getattr(self, "_pv_menu", None)
        if menu is None:
            return None
        try:
            menu.entryconfigure(0, state=tk.DISABLED if self._busy
                                else tk.NORMAL)
        except tk.TclError:                             # pragma: no cover
            pass
        x = getattr(event, "x_root", self._pv_canvas.winfo_rootx() + 20)
        y = getattr(event, "y_root", self._pv_canvas.winfo_rooty() + 20)
        try:
            menu.tk_popup(int(x), int(y))
        finally:
            try:
                menu.grab_release()
            except tk.TclError:                         # pragma: no cover
                pass
        return "break"

    # -- 3. the images table --------------------------------------------

    #: The table, left to right: ``(id, heading, width, minwidth,
    #: stretch)``.  The two text columns stretch and everything else keeps
    #: its width, so widening the window widens the TITLES - and the four
    #: icon columns stay pinned to the right edge where the hand expects
    #: them.  ``code`` is filled by whatever reports the game code version
    #: of an image; blank until then, and blank for a row that has none.
    TABLE_COLUMNS = (
        ("idx", "#", 30, 30, False),
        ("title", "Title", 150, 70, True),
        ("sub", "Subtitle", 160, 60, True),
        ("art", "Picture", 110, 60, True),
        ("anim", "Animation", 130, 60, True),
        ("music", "Music", 90, 50, True),
        ("sound", "Confirm", 80, 50, False),
        ("code", "Code", 90, 50, False),
        ("edit", "", 26, 26, False),
        ("del", "", 26, 26, False),
        ("up", "", 26, 26, False),
        ("down", "", 26, 26, False),
    )

    #: The four icon columns: ``(column id, glyph, dimmed glyph, method)``.
    #: The dimmed glyph is what the cell shows when the action cannot do
    #: anything from that row - the first row cannot move up, the last
    #: cannot move down - so the arrow says so instead of silently doing
    #: nothing.  Outline / filled rather than colour: a Treeview colours a
    #: ROW, never one cell of it.
    #: CHECKED IN THE SCREENSHOT, which is the only place the font fallback
    #: shows itself: all four draw as ordinary monochrome text on Windows
    #: (the colour fringing a 4x crop shows on them is ClearType's, and it
    #: is on the minus sign and the digits too).  The FULL-SIZE triangles,
    #: not the small ▴ ▾ the 'More ▾' button uses: in a 26 px column the
    #: small ones are a weak thing to aim at.
    ROW_ICONS = (("edit", "✎", "✎", "_icon_edit"),
                 ("del", "−", "−", "_icon_remove"),
                 ("up", "▲", "△", "_icon_up"),
                 ("down", "▼", "▽", "_icon_down"))

    #: The iid of the template row - the last row of the table, dim, with a
    #: '+': an empty card shows just that row, which teaches the control.
    ADD_ROW = "add"

    def _build_table(self, parent, th):
        """THE IMAGES TABLE.  Wide, so each image's settings are columns
        rather than something hidden in a dialog, and the row is where the
        row is worked on: a pencil, a minus and two arrows at its right
        edge, acting on that row.  A Treeview holds no widgets, so the
        icons are narrow glyph columns and one <Button-1> binding that asks
        which row and which column the click landed in - the standard way,
        and it reads as icons."""
        box = ttk.Frame(parent)
        box.pack(fill=tk.X, pady=(8, 0))
        self._table_box = box
        cols = tuple(c[0] for c in self.TABLE_COLUMNS)
        self._tree = ttk.Treeview(box, columns=cols, show="headings",
                                  height=LIST_MIN_ROWS, selectmode="browse")
        for name, head, width, minwidth, stretch in self.TABLE_COLUMNS:
            self._tree.heading(name, text=head)
            centred = name == "idx" or not head      # the index, the icons
            self._tree.column(name, width=width, minwidth=minwidth,
                              stretch=stretch,
                              anchor=tk.CENTER if centred else tk.W)
        self._tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb = ttk.Scrollbar(box, orient=tk.VERTICAL, command=self._tree.yview)
        self._list_sb = sb
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        # The template row is dim, so it reads as an invitation rather than
        # as an image that is already on the card.
        self._tree.tag_configure("add", foreground=th["gray"])
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._row_selected())
        self._tree.bind("<Button-1>", self._table_click)
        self._tree.bind("<Double-1>", self._table_double_click)
        self._tree.bind("<Return>", lambda _e: self.edit_image())
        self._build_list_menu(th)
        self._row_lbl = ttk.Label(parent, foreground=th["gray"], text="",
                                  anchor=tk.W)
        self._row_lbl.pack(fill=tk.X, pady=(3, 0))
        self._row_tip = _Tooltip(self._row_lbl, "", self._theme_fn)

    def _build_list_menu(self, th):
        """The same five commands as the row icons, on a right-click.

        The icons are the way in; this costs nothing, is where a hand
        trained on every other list looks, and is what a keyboard reaches
        (the menu key, and Enter on a row)."""
        menu = tk.Menu(self._tree, tearoff=0)
        for label, attr, needs_row in self.LIST_ACTIONS:
            if label is None:
                menu.add_separator()
                continue
            menu.add_command(label=label,
                             command=lambda a=attr: getattr(self, a)())
        self._list_menu = menu
        self._tree.bind("<Button-3>", self._popup_list_menu)
        for seq in ("<App>", "<Shift-F10>"):
            try:
                self._tree.bind(seq, self._popup_list_menu)
            except tk.TclError:                         # pragma: no cover
                pass

    #: The right-click menu, in the order the icons are in.  ``needs_row``
    #: entries are greyed when the click missed every image row, so a
    #: right-click on the template row or on empty space offers Add… alone.
    LIST_ACTIONS = (("Add image…", "_add_image", False),
                    ("Edit image…", "edit_image", True),
                    ("Remove image", "_remove_image", True),
                    (None, None, False),
                    ("Move up", "_move_up", True),
                    ("Move down", "_move_down", True))

    def _popup_list_menu(self, event=None):
        """Pop the menu up under the pointer, over the row it landed on."""
        menu = getattr(self, "_list_menu", None)
        if menu is None:
            return None
        row = None
        if event is not None and getattr(event, "x_root", None) is not None:
            item = self._row_at(event)
            if item is not None:
                self._select_row(item)
                row = item
        if row is None:
            row = self._selected()
        i = 0
        for label, _attr, needs_row in self.LIST_ACTIONS:
            if label is None:
                i += 1
                continue
            live = (row is not None) if needs_row else True
            if live and self._busy:
                live = False        # a run is writing the card being edited
            try:
                menu.entryconfigure(i, state=tk.NORMAL if live
                                    else tk.DISABLED)
            except tk.TclError:                         # pragma: no cover
                pass
            i += 1
        x = getattr(event, "x_root", None)
        y = getattr(event, "y_root", None)
        if x is None or y is None:                      # a keyboard opening
            x = self._tree.winfo_rootx() + 20
            y = self._tree.winfo_rooty() + 20
        try:
            menu.tk_popup(int(x), int(y))
        finally:
            try:
                menu.grab_release()
            except tk.TclError:                         # pragma: no cover
                pass
        return "break"

    def _row_at(self, event):
        """The image index the pointer is over, or None (the template row,
        the heading and empty space are all None)."""
        try:
            item = self._tree.identify_row(event.y)
        except tk.TclError:                             # pragma: no cover
            return None
        try:
            i = int(item)
        except (TypeError, ValueError):
            return None
        return i if 0 <= i < len(self._rows) else None

    def _column_at(self, event):
        """The id of the column the pointer is over ('title', 'up', …), or
        '' when it is not over a cell."""
        try:
            if self._tree.identify_region(event.x, event.y) != "cell":
                return ""
            col = self._tree.identify_column(event.x)
        except tk.TclError:                             # pragma: no cover
            return ""
        try:
            n = int(str(col).lstrip("#")) - 1
        except ValueError:
            return ""
        if 0 <= n < len(self.TABLE_COLUMNS):
            return self.TABLE_COLUMNS[n][0]
        return ""

    def _select_row(self, i):
        try:
            self._tree.selection_set(str(i))
            self._tree.focus(str(i))
        except tk.TclError:                             # pragma: no cover
            pass

    def _table_click(self, event):
        """One click in the table: the template row adds an image, an icon
        column acts on ITS row, everything else selects as usual."""
        try:
            item = self._tree.identify_row(event.y)
        except tk.TclError:                             # pragma: no cover
            return None
        if item == self.ADD_ROW:
            self._add_image()
            return "break"
        i = self._row_at(event)
        if i is None:
            return None
        col = self._column_at(event)
        for name, _glyph, _dim, attr in self.ROW_ICONS:
            if name == col:
                self._select_row(i)
                getattr(self, attr)(i)
                return "break"
        return None

    def _table_double_click(self, event):
        """A double-click still opens the editor - on a row, and on the
        template row it is simply a second Add."""
        try:
            if self._tree.identify_row(event.y) == self.ADD_ROW:
                return "break"          # the single click already added one
        except tk.TclError:                             # pragma: no cover
            pass
        if self._column_at(event) in [c[0] for c in self.ROW_ICONS]:
            return "break"              # the icon already acted, once
        self.edit_image()
        return "break"

    def _icon_edit(self, i=None):
        self.edit_image(self._selected() if i is None else i)

    def _icon_remove(self, i=None):
        self._remove_image()

    def _icon_up(self, i=None):
        self._move_image(-1)

    def _icon_down(self, i=None):
        self._move_image(1)

    def _move_up(self):
        self._move_image(-1)

    def _move_down(self):
        self._move_image(1)

    # -- 4. the bottom bar, and the status ------------------------------

    def _build_actions(self, parent, th):
        """THE ONE ACTION BAR - with the source row at the top, the only
        place in the tab a button lives.  Menu settings… on the left with
        what it holds beside it, the two that write a card and the two
        handoffs on the right (the contextual one green), and the rare
        things behind one menu button.

        One row, and every widget in it has an expanding neighbour: a row
        this app overflows loses its last widget without a word."""
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(10, 0))
        self._action_row = row
        self._menu_btn = ttk.Button(row, text="Menu settings…", width=16,
                                    command=self.open_menu_settings)
        self._menu_btn.pack(side=tk.LEFT)
        self._more_btn = ttk.Menubutton(row, text="More  ▾", width=9)
        menu = tk.Menu(self._more_btn, tearoff=0)
        menu.add_command(label="Check size", command=self._check_size)
        menu.add_command(label="Prepare media", command=self._prepare_media)
        menu.add_separator()
        menu.add_command(label="Bypass an existing card…",
                         command=self._bypass_existing)
        menu.add_separator()
        menu.add_checkbutton(label="Update the preview automatically",
                             variable=self._auto_preview,
                             command=self.schedule_preview)
        self._more_btn.configure(menu=menu)
        self._more_menu = menu
        self._more_btn.pack(side=tk.RIGHT)
        self._emu_btn = ttk.Button(row, text="Run in emulator", width=16,
                                   command=self._run_emulator)
        self._emu_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self._flash_btn = ttk.Button(row, text="Flash to SD card…", width=18,
                                     command=self._flash)
        self._flash_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self._build_btn = ttk.Button(row, text="Build & verify", width=15,
                                     command=self._build_card,
                                     style="Go.TButton")
        self._build_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self._apply_btn = ttk.Button(row, text="Apply to card", width=14,
                                     command=self.apply_to_card)
        self._apply_btn.pack(side=tk.RIGHT, padx=(0, 6))
        # What Menu settings… holds, in the space between the two groups -
        # packed LAST and expanding, because this app unmaps the last
        # widget of a row it cannot fit and the thing that gives way first
        # has to be the one that can be read elsewhere (its tooltip).
        self._menu_lbl = ttk.Label(row, foreground=th["gray"], text="",
                                   width=1, anchor=tk.W)
        self._menu_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True,
                            padx=(10, 10))
        self._menu_tip = _Tooltip(self._menu_lbl, "", self._theme_fn)
        self._action_btns = [
            self._apply_btn, self._build_btn, self._flash_btn, self._emu_btn,
            self._more_btn, self._load_btn, self._new_btn, self._menu_btn,
            self._browse_btn]

    def _build_status(self, parent, th):
        """The status under the bar: what just happened, and what the two
        writing buttons would do about it.

        TWO LINES, of a pinned height.  One is the live message - the state
        and the errors, which is what the eye wants next to the buttons -
        and the second is the consequence: what Apply to card would write,
        or why only a rebuild can, with the card's size beside it.  The
        height is pinned to what those lines really MEASURE (56 px over
        three ~19 px labels was a pixel short in every state, and a box a
        pixel short unmaps the last thing packed into it), and each label
        is clipped to one line - a message that wrapped used to take its
        neighbour's row with it and lose 'what Apply to card would write'
        exactly when there was most to say.  Every word of every message is
        in the app's Log at the foot of the window."""
        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.X, pady=(8, 0))
        wrap.pack_propagate(False)
        self._status_wrap = wrap
        self._hint = ttk.Label(wrap, justify=tk.LEFT, anchor=tk.W, text="",
                               foreground=th["gray"])
        self._hint.pack(fill=tk.X)
        self._edit_lbl = ttk.Label(wrap, justify=tk.LEFT, anchor=tk.W,
                                   text="")
        self._edit_lbl.pack(fill=tk.X)
        self._status_lines = (self._hint, self._edit_lbl)
        self._status_h = 0
        self._fit_status_height()

    #: What one status line is worth when the labels cannot be measured yet
    #: (a headless build, a font that has not been laid out).
    STATUS_LINE_H = 20

    def _fit_status_height(self):
        """Pin the status box to its lines' REAL height.  Measured, not
        guessed, and re-measured on every <Configure> because the font can
        change under a theme switch or a DPI change."""
        wrap = getattr(self, "_status_wrap", None)
        if wrap is None:
            return
        line = 0
        for lbl in self._status_lines:
            try:
                line = max(line, lbl.winfo_reqheight())
            except tk.TclError:                         # pragma: no cover
                pass
        line = max(line, self.STATUS_LINE_H)
        want = line * len(self._status_lines) + 2       # a hair, not a guess
        if want != self._status_h:
            self._status_h = want
            try:
                wrap.configure(height=want)
            except tk.TclError:                         # pragma: no cover
                pass

    @staticmethod
    def _status_line(msg):
        """A message as ONE line for the status block: the first line, and
        a count of the rest (which are in the app's Log, in full).

        The block is a fixed height, and a label that wraps or carries a
        newline eats its neighbour's row - so nothing that reaches it is
        allowed more than one line."""
        lines = [ln.strip() for ln in (msg or "").splitlines() if ln.strip()]
        if not lines:
            return ""
        if len(lines) == 1:
            return lines[0]
        return "%s  (+%d more - see the Log below)" % (lines[0],
                                                       len(lines) - 1)

    # -- responsive ------------------------------------------------------

    def _chrome_h(self):
        """Every pixel of the tab that is NOT the picture.

        Measured from the rows themselves, and deliberately not from the
        tab's own requested height: that is computed FROM the picture, so
        measuring the picture against it is a loop (it was, twice).  None
        of these depends on the canvas."""
        h = 14 + 8 + 8 + 10 + 8         # the pads between the five rows
        h += 4 + 2                      # the strip's pad, the canvas border
        # The version banner, ONLY while it is up: it is not part of the
        # ordinary tab, and when it appears the picture is what pays for it
        # (the alternative is the tab growing past the desktop it is
        # designed for, on the one card that most needs reading).
        alarm = getattr(self, "_alarm_box", None)
        if alarm is not None and alarm.winfo_manager():
            h += alarm.winfo_reqheight() + 6            # its own top pad
        for name in ("_src_row", "_pv_strip", "_table_box", "_action_row",
                     "_status_wrap", "_row_lbl"):
            widget = getattr(self, name, None)
            if widget is None:
                continue
            try:
                h += widget.winfo_reqheight()
            except tk.TclError:                         # pragma: no cover
                pass
        return h + 3                    # the row label's own pad

    def _on_configure(self, event=None):
        """The window changed size.  NOTHING MOVES BUT THE PICTURE: the
        arrangement is the same at every width, and the preview takes the
        height the rest of the tab does not need and the width that height
        allows - so the canvas is exactly the picture, with no black bars
        around it, and the tab's own height stays where it is."""
        try:
            width = self._outer.winfo_width()
            window_h = self._parent.winfo_toplevel().winfo_height()
        except tk.TclError:
            return
        if width <= 1:
            return
        # THE PICTURE TAKES THE ROOM THE REST OF THE TAB DOES NOT NEED, and
        # the room the tab has is the window's height less the app around
        # it - 640 px on a 1024x768 desktop, more on a taller window, so
        # the preview really does grow with the window instead of sitting
        # at whatever a constant said.  Never past half the machine's own
        # frame: bigger than that is upscaling.
        budget = TAB_BUDGET_H if window_h <= 1 else window_h - APP_CHROME_H
        h = max(PREVIEW_MIN_H, min(PREVIEW_H, budget - self._chrome_h()))
        # ...and only as wide as that height's own frame: 1360x768 at this
        # height, or the window when the window is narrower than that.
        w = min(max(PREVIEW_MIN_W, width), int(round(h * FRAME_W / FRAME_H)))
        if (w, h) != (self._pv_w, self._pv_h):
            self._pv_w, self._pv_h = w, h
            try:
                self._pv_canvas.configure(width=w, height=h)
            except tk.TclError:
                pass
            self._redraw_shown()
            self._resize_fn()
        self._fit_status_height()
        try:
            self._pv_status.configure(
                wraplength=max(120, width - self._strip_w()))
            # ONE line each, so no message can take its neighbour's row
            # with it: the block is a fixed height (see _build_status).
            for lbl in self._status_lines:
                lbl.configure(wraplength=0)
        except tk.TclError:
            pass

    def _strip_w(self):
        """What the preview's control strip spends on everything that is
        not the status label - measured, so the label's wraplength is the
        space it actually gets.  (Assumed, it was 13 px too generous and
        the caption wrapped a word past the end of the strip.)"""
        used = 0
        try:
            for child in self._pv_strip.winfo_children():
                if child is not self._pv_status:
                    used += child.winfo_reqwidth()
        except tk.TclError:                             # pragma: no cover
            return 330
        # the padx between them: Image: (0,3), Frame: (10,3), Play (8,0),
        # and the status label's own (12,0)
        return used + 3 + 13 + 8 + 12

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

    #: The full-detail cells, kept as module functions so the Edit image…
    #: dialog and the tests can read them without a tree.
    _cell = staticmethod(_cell)
    _cell_image = staticmethod(_cell_image)
    _cell_art = staticmethod(cell_art)
    _cell_anim = staticmethod(cell_anim)

    #: What the last row of the table says.  Dim, with a '+': an empty card
    #: shows only this, which is both the way in and the lesson.
    ADD_ROW_TEXT = "Add an image…"

    def _values(self, i, row):
        """ONE ROW OF THE TABLE, in the column order of TABLE_COLUMNS: the
        index, the title (with what is wrong with its .raw when something
        is), the subtitle, this image's picture / animation / music, the
        sound that plays when it is chosen, the game code version if
        anything has reported one - and then the four icons that act on
        this row.

        The settings are COLUMNS now rather than a phrase: the table has
        the whole width of the tab, and what an image is set to is worth
        more on screen than one word summarising all of it."""
        last = len(self._rows) - 1
        icons = []
        for name, glyph, dim, _attr in self.ROW_ICONS:
            live = not (name == "up" and i == 0) and \
                not (name == "down" and i >= last)
            icons.append(glyph if live else dim)
        return (i, list_title(row, i), (row.subtitle or "").strip(),
                cell_art(row), cell_anim(row), _cell(row.music),
                self._confirm_cell(row), (row.version or "").strip(),
                ) + tuple(icons)

    def _add_row_values(self):
        """The template row: a '+' where the index is and the invitation
        where the title is, and nothing in the rest."""
        return ("+", self.ADD_ROW_TEXT) + ("",) * (
            len(self.TABLE_COLUMNS) - 2)

    def _refresh_tree(self, select=None):
        try:
            for item in self._tree.get_children():
                self._tree.delete(item)
            for i, row in enumerate(self._rows):
                self._tree.insert("", tk.END, iid=str(i),
                                  values=self._values(i, row))
            self._tree.insert("", tk.END, iid=self.ADD_ROW, tags=("add",),
                              values=self._add_row_values())
            # As tall as it HAS rows (the template row included), between
            # LIST_MIN_ROWS and LIST_MAX_ROWS: eight rows of empty box
            # under two images is a hole in the tab, and sixteen images
            # would leave the picture nothing.
            rows = max(LIST_MIN_ROWS,
                       min(LIST_MAX_ROWS, len(self._rows) + 1))
            if int(self._tree.cget("height")) != rows:
                self._tree.configure(height=rows)
                # The table is a different height, so the picture has a
                # different amount of room; re-measure once the new
                # requested sizes have settled.
                self._resize_fn()
                try:
                    self._timer().after_idle(self._on_configure)
                except tk.TclError:                     # pragma: no cover
                    pass
            if select is not None and 0 <= select < len(self._rows):
                self._tree.selection_set(str(select))
                self._tree.focus(str(select))
            top = max(0, len(self._rows) - 1)
            if self._default_spin is not None:
                self._default_spin.configure(to=top)
            self._hl_spin.configure(to=top)
        except tk.TclError:
            pass
        self._load_editor()
        self._update_edit_status()
        self._update_menu_summary()
        self._update_row_label()
        self.schedule_preview()

    def _update_row_label(self):
        """The one dim line under the table.  It has two jobs and never
        more than one line: which .raw the selected image came from (the
        table has no room for a path, and it is the one fact a row cannot
        show), and - when nothing is selected - the quiet sentence that
        teaches the icons."""
        lbl = getattr(self, "_row_lbl", None)
        if lbl is None:
            return
        i = self._selected()
        full = _cell_image(self._rows[i]) if i is not None else ""
        try:
            lbl.configure(text=_shorten(full, 90) if full else self.ROW_HINT)
            self._row_tip.text = full or self.LIST_TIP
        except tk.TclError:
            pass

    def _row_selected(self):
        """A row was picked: load it into the editor variables AND point the
        preview's highlight at it, so the image being edited is the one on
        screen."""
        self._load_editor()
        self._update_row_label()
        i = self._selected()
        if i is not None:
            self._set_var(self._hl_var, i)
            self._show_cached()
            self.schedule_preview()

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
            self._ed_confirm.set(row.confirm or "menu")
            self._ed_art_video.set(row.art_video)
            self._ed_art_time.set(row.art_time)
            self._ed_anim_start.set(row.anim_start)
            self._ed_anim_seconds.set(row.anim_seconds)
            self._ed_anim_fps.set(row.anim_fps)
        finally:
            self._loading = False
        self._sync_editor_states()

    def _editor_changed(self):
        """The selected row <- the editor, on every keystroke."""
        if self._loading:
            return
        self._sync_editor_states()
        i = self._selected()
        if i is None:
            return
        row = self._rows[i]
        # A media field typed over is no longer the card's own file: the
        # value is a spec again, and the tools may render it.
        for attr, flag, var in (("art", "art_on_card", self._ed_art),
                                ("anim", "anim_on_card", self._ed_anim),
                                ("music", "music_on_card", self._ed_music),
                                ("confirm", "confirm_on_card",
                                 self._ed_confirm)):
            if getattr(row, flag) and getattr(row, attr) != var.get():
                setattr(row, flag, False)
        row.title = self._ed_title.get()
        row.subtitle = self._ed_sub.get()
        row.art = self._ed_art.get()
        row.anim = self._ed_anim.get()
        row.music = self._ed_music.get()
        # "menu" is what the box says and "" is what the row keeps, so a row
        # that inherits compares equal however the dialog spelled it
        conf_v = self._ed_confirm.get()
        row.confirm = "" if conf_v.strip().lower() == "menu" else conf_v
        row.art_video = self._ed_art_video.get()
        row.art_time = self._ed_art_time.get()
        row.anim_start = self._ed_anim_start.get()
        row.anim_seconds = self._ed_anim_seconds.get()
        row.anim_fps = self._ed_anim_fps.get()
        try:
            self._tree.item(str(i), values=self._values(i, row))
        except tk.TclError:
            pass
        self._update_edit_status()
        self._update_row_label()

    def _sync_editor_states(self):
        """The video-frame fields live only for the 'video frame' art (the
        time also for a typed video); the clip fields for any animation."""
        widgets = (getattr(self, "_video_entry", None),
                   getattr(self, "_video_btn", None),
                   getattr(self, "_video_time", None))
        if any(w is None for w in widgets):
            return
        art = self._ed_art.get().strip().lower()
        pick = art == "video frame"
        timed = pick or is_video(art)
        for w, on in zip(widgets, (pick, pick, timed)):
            try:
                w.configure(state=tk.NORMAL if on else tk.DISABLED)
            except tk.TclError:
                pass
        anim = self._ed_anim.get().strip().lower()
        for w in getattr(self, "_clip_widgets", ()):
            try:
                w.configure(state=tk.NORMAL if anim not in ("", "none")
                            else tk.DISABLED)
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
        if self._loaded_card:
            return          # a loaded card owns the output box
        cur = self._out_var.get().strip()
        if cur and cur != self._out_auto_value:
            return
        if not self._rows:
            return
        new = default_output_path(self._rows[0].path)
        self._out_auto_value = new
        self._out_var.set(new)

    def _new_card_clicked(self):
        if self._busy:
            self._error("Wait for the current run to finish first.")
            return
        if self._rows and not messagebox.askyesno(
                "New card?", "Clear the image list and the menu and start a "
                             "new card?"):
            return
        self.new_card()

    def new_card(self):
        """'New card…': back to an empty tab - no images, the menu at its
        defaults, editing mode left behind.  Nothing on disk is touched; the
        card that was loaded is simply no longer the one being edited."""
        self._rows = []
        self._loaded_card = ""
        self._loaded_form = None
        self._loaded_info = None
        self._armed = False
        self._media_override = ""
        self._out_auto_value = ""
        self._show_alarm(None)
        self._plan_info = None
        self._plan_text = ""
        self._hl_touched = False
        self._loading = True
        try:
            self._out_var.set("")
            self._move_var.set("auto")
            self._confirm_var.set("auto")
            self._volume_var.set("50")
            self._timeout_var.set("15")
            self._default_var.set("0")
            self._bypass_var.set(True)
        finally:
            self._loading = False
        self._pv_cache.clear()
        self._pv_totals.clear()
        self._pv_shown = None
        self._pv_src = None
        self._pv_ready = None
        self._pv_photo = None
        self._stop_play(None)
        self._set_var(self._hl_var, 0)
        self._set_var(self._frame_var, 0)
        self._update_edit_status()
        self._pv_placeholder()
        self._pv_say("")
        self._refresh_tree()
        self._ok("A new card: add the primary (stock) image and one more.")

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
    # the two modals
    # ------------------------------------------------------------------

    def edit_image(self, index=None):
        """'Edit image…' (also a double-click on the row): the selected
        image's title, subtitle and media in a modal.  Returns the dialog,
        or None when there is no row to edit.

        The dialog's widgets are bound to the panel's OWN editor variables,
        so every keystroke still writes through to the row and still moves
        the preview; Cancel puts the row back the way it was."""
        if self._image_dialog is not None:
            return self._image_dialog
        i = self._selected() if index is None else index
        if i is None and self._rows:
            i = 0
            self._refresh_tree(select=0)
        if i is None or not 0 <= i < len(self._rows):
            self._error("Add an image first, then select it to edit.")
            return None
        if self._selected() != i:
            self._refresh_tree(select=i)
        self._edit_backup = (i, replace(self._rows[i]))
        self._image_dialog = ImageEditorDialog(self, i, self._rows[i])
        self._sync_editor_states()
        return self._image_dialog.show()

    def _image_editor_ok(self):
        self._forget_image_dialog()
        self._refresh_tree(select=self._edit_backup[0]
                           if self._edit_backup else None)
        self._edit_backup = None
        self.schedule_preview(now=True)

    def _image_editor_cancel(self):
        self._forget_image_dialog()
        if self._edit_backup is not None:
            i, row = self._edit_backup
            if 0 <= i < len(self._rows):
                self._rows[i] = row
            self._edit_backup = None
            self._refresh_tree(select=i)

    def _forget_image_dialog(self):
        self._image_dialog = None
        self._video_entry = self._video_btn = self._video_time = None
        self._clip_widgets = ()

    def open_menu_settings(self):
        """'Menu settings…': the sounds, volume, countdown, default image,
        the bypass and the selector build path, in a modal.  The button
        beside it already says what they are (:func:`menu_summary`)."""
        if self._menu_dialog is not None:
            return self._menu_dialog
        self._menu_backup = (self._move_var.get(), self._confirm_var.get(),
                             self._volume_var.get(), self._timeout_var.get(),
                             self._default_var.get(), self._bypass_var.get(),
                             self._selector_var.get())
        self._menu_dialog = MenuSettingsDialog(self, len(self._rows))
        return self._menu_dialog.show()

    def _menu_settings_ok(self):
        self._forget_menu_dialog()
        self._update_menu_summary()
        self.schedule_preview(now=True)

    def _menu_settings_cancel(self):
        self._forget_menu_dialog()
        if self._menu_backup is not None:
            (move, confirm, vol, timeout, default, bypass,
             selector) = self._menu_backup
            self._menu_backup = None
            self._move_var.set(move)
            self._confirm_var.set(confirm)
            self._volume_var.set(vol)
            self._timeout_var.set(timeout)
            self._default_var.set(default)
            self._bypass_var.set(bypass)
            self._selector_var.set(selector)
        self._update_menu_summary()

    def _forget_menu_dialog(self):
        self._menu_dialog = None
        self._default_spin = None
        self._bypass_chk = None

    def _menu_changed(self):
        self._update_edit_status()
        self._update_menu_summary()
        self._refresh_sound_cells()

    def _update_menu_summary(self):
        """What Menu settings… holds, beside its button.  Clipped to the
        space between the two groups of the action bar; the whole of it is
        the label's tooltip, and none of it is anywhere else."""
        lbl = getattr(self, "_menu_lbl", None)
        if lbl is None:
            return
        text = menu_summary(self.form())
        try:
            lbl.configure(text=text)
            self._menu_tip.text = text
        except tk.TclError:
            pass

    def _confirm_cell(self, row):
        """The Confirm column: the sound that actually plays when THAT row
        is chosen.  A row with one of its own shows it plainly; a row
        without shows the menu's IN PARENTHESES - the column is worth
        nothing if it does not say what will be heard, and the brackets are
        what tells the two apart at a glance (a Treeview colours a row,
        never one cell of it, so the mark has to be in the text)."""
        own = (row.confirm or "").strip()
        if own and own.lower() != "menu":
            return _cell(own)
        if getattr(row, "confirm_on_card", False):      # pragma: no cover
            return _cell(own)
        return "(%s)" % _cell(self._confirm_var.get())

    def _refresh_sound_cells(self):
        """The menu's confirm sound changed, so every row that INHERITS it
        now says something else; the rows with one of their own do not
        move."""
        tree = getattr(self, "_tree", None)
        if tree is None:
            return
        try:
            for i, row in enumerate(self._rows):
                tree.set(str(i), "sound", self._confirm_cell(row))
        except tk.TclError:                             # pragma: no cover
            pass

    # ------------------------------------------------------------------
    # the form
    # ------------------------------------------------------------------

    def media_dir(self):
        """Where this tab's media set lives: the directory a load extracted
        the card's own media into while a card is loaded, else ``<out
        dir>/media``.  One answer for the prepare, the build, the preview
        and the inject - they must never disagree about it."""
        return self._media_override or media_dir_for(
            self._out_var.get().strip().strip('"'))

    def form(self):
        """The form as a :class:`MultibootForm` - what every command line is
        built from.  ``media_dir`` is set only when a prepared media set is
        actually there (media.json), so a build never names a dir the tool
        would refuse."""
        out = self._out_var.get().strip().strip('"')
        media = self.media_dir()
        return MultibootForm(
            images=[replace(r) for r in self._rows],
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

    def _validated_form(self, sources=True):
        form = self.form()
        errs = validate_form(form, sources=sources)
        if errs:
            self._error("\n".join(errs))
            return None
        return form

    def _error(self, msg):
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        try:
            self._hint.configure(text=self._status_line(msg),
                                 foreground=th["error"])
        except tk.TclError:
            pass
        # The status block is a fixed height and this label gets ONE of
        # its two lines, so a long list of reasons is SUMMED there and said
        # in full here - the app's Log keeps every word, and the line above
        # says how many there were.
        for line in msg.splitlines():
            self._write(line)

    def _ok(self, msg, extra=True):
        """The live line.  One line on the tab (the block cannot hold two
        without dropping the sentence under it); anything past the first
        goes to the app's Log, where it is kept in full.

        ``extra=False`` for a caller that has already written the rest
        itself - a load's warnings, which it echoes with their own tag."""
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        try:
            self._hint.configure(text=self._status_line(msg),
                                 foreground=th["gray"])
        except tk.TclError:
            pass
        if extra:
            for line in (msg or "").splitlines()[1:]:
                if line.strip():
                    self._write(line)

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
            self._plan_text = size_plan_text(self._plan_info)
        else:
            self._plan_text = ""
        self._update_edit_status()

    def _prepare_media(self):
        form = self.form()
        errs = validate_form(form) + rebuild_blockers(form)
        if errs:
            self._error("\n".join(errs))
            return
        media = self.media_dir()
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
        form = self.form()
        # A LOADED CARD IS NOT AN OUTPUT.  After a load the output box holds
        # the card that was read, so that Apply and the preview name the
        # same file; a build into it would copy ~7 GB per image over the
        # very card being edited.  The way out is explicit, not a dialog:
        # type a different output path (Browse… writes it), or press Apply.
        if self._loaded_card and _norm(form.out) == _norm(self._loaded_card):
            self._error(
                "Build & verify writes a NEW card, and the output is the "
                "card you loaded (%s). Set 'Card image' to a different path "
                "to build a copy - or press Apply to card, which rewrites "
                "the menu of this one in seconds." % self._loaded_card)
            return
        # Every reason at once: the form's own, and the media a loaded card
        # carries that nothing here can render into a new one.
        errs = validate_form(form) + rebuild_blockers(form)
        if errs:
            self._error("\n".join(errs))
            return
        if os.path.exists(form.out):
            if not self._confirm_overwrite(form.out):
                return
            form.force = True
        self._plan_text = ""
        self._update_edit_status()
        cmds = build_commands(form)
        if form.media_dir:
            # A media set exists: prepare it in full first, with THIS form's
            # specs.  The preview leaves a sound-less media.json in the same
            # dir, and art changed since the last Prepare would otherwise
            # not be on the card; selectmedia's cache keeps this cheap.
            cmds = prepare_commands(form, form.media_dir) + cmds
            self._ok("Preparing the media, then building %s…" % form.out)
        else:
            self._ok("Building %s…" % form.out)

        def done(rc, failed, _text):
            if rc == 0:
                self._ok("Card built and verified: %s%s" % (
                    form.out, "" if form.media_dir else
                    " (no prepared media - text-only menu)"))
            else:
                self._error("%s failed (exit %d) - see the tool output."
                            % (failed or "the build", rc))
        self._run_commands(cmds, on_step=self._plan_step, on_done=done)

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
    # loading a card, and writing the menu back into it
    # ------------------------------------------------------------------

    def _load_card_dialog(self):
        if self._busy:
            self._error("Wait for the current run to finish first.")
            return
        path = filedialog.askopenfilename(
            title="Pick the multi-image card to read into the form",
            filetypes=[("Card images", "*.raw *.img"), ("All files", "*.*")])
        if path:
            self.load_card(path)

    def load_card(self, path):
        """Read an existing multi-image card into the form: two inspects on
        the worker (the tool's table into the pane, the same read as JSON
        for the fields), the card's media extracted beside it, and then
        :meth:`load_inspect`.  False when the tab refused to start."""
        path = (path or "").strip().strip('"')
        if not os.path.isfile(path):
            self._error("No such card image: %s" % path)
            return False
        if under_library(path):
            self._error("That card is in the library (%s); copy it out "
                        "first - Apply to card writes into the card it "
                        "read." % LIBRARY_PREFIXES[0])
            return False
        if self._busy:
            self._error("A run is already in progress.")
            return False
        media = loaded_media_dir(path)
        try:
            os.makedirs(media, exist_ok=True)
        except OSError as exc:
            self._error("Cannot create %s: %s" % (media, exc))
            return False
        self._ok("Reading %s…" % path)
        seen = {}

        def step(label, rc, text):
            if label == INSPECT_JSON and rc == 0:
                seen["info"] = parse_inspect(text)

        def done(rc, failed, texts):
            if rc != 0:
                why = parse_refusal(texts.get(failed, "")) or \
                    "%s failed (exit %d) - see the tool output." % (failed, rc)
                self._error("Cannot read %s: %s" % (path, why))
                return
            info = seen.get("info")
            if not isinstance(info, dict):
                self._error("Cannot read %s: the inspect printed no JSON "
                            "report - see the tool output." % path)
                return
            self.load_inspect(info, path, media)
        return self._run_commands(inspect_commands(path, media), on_step=step,
                                  on_done=done, quiet=(INSPECT_JSON,))

    def load_inspect(self, info, card, media_dir=None):
        """Fill the whole form from an inspect report and go into EDITING
        mode.  The public seam: the loader above, the tests and the
        screenshot script all come through here, so none of them needs WSL.
        Returns the warnings it put on the tab."""
        card = (card or "").strip().strip('"')
        media_dir = media_dir if media_dir is not None \
            else loaded_media_dir(card)
        form, warnings = form_from_inspect(
            info, card, media_dir, self._selector_var.get().strip())
        self._rows = list(form.images)
        self._media_override = media_dir
        # Before the fields are written: Default's trace moves Highlight only
        # while it has not been typed, and this card's default is the one to
        # follow whatever was typed for the last one.
        self._hl_touched = False
        self._loading = True
        try:
            self._out_var.set(card)
            self._out_auto_value = ""
            self._move_var.set(form.sound_move)
            self._confirm_var.set(form.sound_confirm)
            self._volume_var.set(str(int(form.volume)))
            self._timeout_var.set(str(int(form.timeout)))
            self._default_var.set(str(int(form.default)))
            self._bypass_var.set(bool(form.bypass))
        finally:
            self._loading = False
        _ticked, self._armed = bypass_state(info)
        self._loaded_card = card
        self._loaded_info = info
        # THE LOUD ONE.  Everything else a load has to say is a note on the
        # status line; images that are not the same game code get their own
        # strip above the picture, because it is the one finding that costs
        # something after the card is in the machine.
        self._show_alarm(info)
        # The baseline is read back through form(), not the form built above:
        # what every diff compares is what the widgets now hold.
        self._loaded_form = self.form()
        # The preview's frames were drawn for the form that was there before;
        # the media dir has changed under them, so none of them is this card.
        self._pv_cache.clear()
        self._pv_totals.clear()
        self._pv_shown = None
        self._pv_src = None
        self._pv_ready = None
        self._set_var(self._hl_var, int(form.default))
        self._stop_play(None)
        self._pv_photo = None
        self._pv_placeholder()
        self._pv_say("Drawing THIS card's menu - its own media is in %s, so "
                     "nothing is prepared first." % media_dir)
        # The card's OWN default is the row to land on: it is the image the
        # machine would boot, and selecting a row points the preview at it.
        self._refresh_tree(select=min(max(0, int(form.default)),
                                      max(0, len(self._rows) - 1)))
        self._update_edit_status()
        head = "Loaded %s: %d image%s." % (
            os.path.basename(card), len(self._rows),
            "" if len(self._rows) == 1 else "s")
        # Notes, not failures: a card that loads with things worth saying
        # (an image whose .raw is elsewhere, a sound with no provenance) has
        # still loaded, so the line stays the ordinary colour and says them.
        self._ok(head + ("\n" + "\n".join(warnings) if warnings
                         else " Edit the menu, then Apply to card."),
                 extra=False)
        for line in warnings:
            self._write("[load] " + line)
        return warnings

    def _apply_blockers(self, form, prepare):
        """Why the loaded card cannot be injected with this form.  Not
        :func:`validate_form`: an inject opens none of the .raw sources, so
        a source that is not on this machine is no reason to refuse."""
        errs = []
        if not os.path.isfile(self._loaded_card):
            errs.append("The card is gone: %s" % self._loaded_card)
        for i, row in enumerate(form.images):
            for what, text in (("title", row.title),
                               ("subtitle", row.subtitle)):
                if _BAD_TEXT.search(text or ""):
                    errs.append("Image %d: the %s must not contain | ; $ "
                                "or `." % (i, what))
            on_card = dict(on_card_fields(row))
            for what, val in (("art", row.art), ("animation", row.anim),
                              ("music", row.music)):
                if what in on_card:
                    if prepare:
                        errs.append(
                            "Image %d: the %s (%s) is the card's own file, "
                            "with no source recorded - choose auto, none or "
                            "a file for it before changing any media."
                            % (i, what, val))
                elif is_file_choice(val) and not os.path.isfile(val.strip()):
                    errs.append("Image %d: %s file not found: %s"
                                % (i, what, val))
            if prepare and not os.path.isfile((row.path or "").strip()):
                for what, spec in (("art", art_spec(row)),
                                   ("animation", anim_spec(row))):
                    if spec == "auto" or spec.startswith("auto@"):
                        errs.append(
                            "Image %d: the %s is 'auto', which is rendered "
                            "from %s - and that file is not on this machine. "
                            "Point it at a file, or make the change where "
                            "the image is." % (i, what, row.path or
                                               row.device or "its image"))
        primary = (form.images[0].path or "").strip() if form.images else ""
        for what, val in (("move sound", form.sound_move),
                          ("confirm sound", form.sound_confirm)):
            if is_file_choice(val) and not os.path.isfile(val.strip()):
                errs.append("The %s file was not found: %s" % (what, val))
            elif (prepare and (val or "").strip().lower() == "auto"
                  and not os.path.isfile(primary)):
                # 'auto' decodes the sound off the PRIMARY image.
                errs.append(
                    "The %s is 'auto', which is decoded from the primary "
                    "image (%s) - and that file is not on this machine. Pick "
                    "'synth', 'none' or a WAV before changing any media."
                    % (what, primary or "not recorded"))
        n = len(form.images)
        if not 0 <= int(form.volume) <= 100:
            errs.append("Volume is 0-100.")
        if int(form.timeout) < 0:
            errs.append("The countdown cannot be negative (0 = wait for "
                        "START).")
        if n and not 0 <= int(form.default) < n:
            errs.append("The default image must be one of 0..%d." % (n - 1))
        return errs

    def apply_to_card(self):
        """'Apply to card': the menu changes into the loaded card with an
        inject (plus a prepare when a media field changed, plus the bypass
        when it is ticked and a tree is still armed), then a last inspect
        that reads the card back.  Seconds, not a rebuild.  False when the
        tab refused."""
        if not self._loaded_card:
            self._error("Load a card first - Apply to card writes into the "
                        "card the form was read from.")
            return False
        if self._busy:
            self._error("A run is already in progress.")
            return False
        form = self.form()
        menu, rebuild = diff_forms(self._loaded_form, form)
        if rebuild:
            self._error(
                "The image list changed (%s). Apply to card only rewrites "
                "the menu of %s; adding, removing, reordering or replacing "
                "an image means copying the images again - set 'Card image' "
                "to a new path and press Build & verify."
                % ("; ".join(rebuild), os.path.basename(self._loaded_card)))
            return False
        prepare = media_specs_changed(self._loaded_form, form)
        errs = self._apply_blockers(form, prepare)
        if errs:
            self._error("\n".join(errs))
            return False
        media = self.media_dir()
        if prepare:
            try:
                os.makedirs(media, exist_ok=True)
            except OSError as exc:
                self._error("Cannot create %s: %s" % (media, exc))
                return False
            # The prepare writes media.json into that dir; the inject must
            # name it even when the card carried no media before.
            form = replace(form, media_dir=media)
        bypass = bool(form.bypass) and self._armed
        cmds = apply_commands(form, self._loaded_card, media,
                              prepare=prepare, bypass=bypass)
        self._ok("Writing the menu into %s%s…" % (
            self._loaded_card, " (media first)" if prepare else ""))

        def step(label, rc, text):
            if label == INSPECT_JSON and rc == 0:
                info = parse_inspect(text)
                if isinstance(info, dict):
                    self._loaded_info = info
                    _ticked, self._armed = bypass_state(info)

        def done(rc, failed, _texts):
            if rc != 0:
                self._error("Apply to card failed at %s (exit %d) - see the "
                            "tool output." % (failed or "the start", rc))
                self._update_edit_status()
                return
            # The card now says what the form says: the tools wrote it and
            # the inject printed the conf.  So the baseline becomes the form
            # that was applied - re-deriving it from the card would show
            # phantom changes for the media it cannot describe (a music bed
            # is a file name on the card, whatever file it came from).
            self._loaded_form = form
            if prepare:
                self._pv_ready = (media_fingerprint(form), media)
            self._ok("Card updated: %s (%s)%s" % (
                self._loaded_card,
                ", ".join(menu) if menu else "no menu change",
                " - flash it again" if bypass else ""))
            self._update_edit_status()
        return self._run_commands(cmds, on_step=step, on_done=done,
                                  quiet=(INSPECT_JSON,))

    def _update_edit_status(self):
        """THE CONSEQUENCE LINE - the status block's second line: what Apply
        to card would write (or why only a rebuild can), and how big the
        card would be.  Called after every keystroke.

        The two share one line because they are one question - what would
        the button under them do - and the block has room for one line
        each.  It also decides which of the two writing buttons is THE
        action right now: while a card is loaded and an inject can carry
        the changes, Apply to card is the green one; otherwise Build &
        verify is."""
        lbl = getattr(self, "_edit_lbl", None)
        btn = getattr(self, "_apply_btn", None)
        if lbl is None or btn is None:
            return
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        rebuild = []
        text = ""
        if self._loaded_card and self._loaded_form is not None:
            menu, rebuild = diff_forms(self._loaded_form, self.form())
            text = edit_status_text(self._loaded_card, menu, rebuild)
            if self._loaded_form.bypass and not self.form().bypass:
                text += ("  (Unticking the bypass cannot un-patch a card - "
                         "build a fresh one for that.)")
        line = "  ·  ".join(p for p in (text, self._plan_text) if p)
        try:
            lbl.configure(text=self._status_line(line),
                          foreground=th["error"] if rebuild
                          else th["gray"] if not text else th["fg"])
            btn.configure(state=tk.DISABLED
                          if (rebuild or self._busy or not self._loaded_card
                              or self._loaded_form is None) else tk.NORMAL)
        except tk.TclError:
            pass
        self._primary_button(build=bool(rebuild) or not self._loaded_card)

    def _primary_button(self, build):
        """Exactly one green button: the one that would actually be pressed."""
        for btn, on in ((getattr(self, "_build_btn", None), build),
                        (getattr(self, "_apply_btn", None), not build)):
            if btn is None:
                continue
            try:
                btn.configure(style="Go.TButton" if on else "TButton")
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # the preview
    # ------------------------------------------------------------------

    def _pv_placeholder(self):
        c = self._pv_canvas
        try:
            c.delete("all")
            c.create_text(self._pv_w // 2, self._pv_h // 2, fill="#667",
                          font=("", 11), justify=tk.CENTER,
                          text="The boot menu is drawn here, by the selector "
                               "itself.\nAdd two images and it appears; every "
                               "change redraws it.")
        except tk.TclError:
            pass

    def _pv_say(self, msg, error=False):
        """The preview's status line; an error also goes to the tool pane
        and the app log, so 'paste what it said' is still one paste."""
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        try:
            self._pv_status.configure(
                text=msg, foreground=th["error"] if error else th["fg"])
        except tk.TclError:
            pass
        if error and msg:
            self._write("[preview] " + msg)

    def _follow_default(self):
        """Highlight follows the Default index until it is typed by hand."""
        if self._hl_touched or self._pv_loading:
            return
        self._set_var(self._hl_var, self._default_var.get())

    def _set_var(self, var, value):
        """A programmatic spinbox write, without the 'typed' trace."""
        self._pv_loading = True
        try:
            var.set(str(value))
        finally:
            self._pv_loading = False

    def _hl_changed(self, typed=False):
        if self._pv_loading:
            return
        if typed:
            self._hl_touched = True
        self._show_cached()

    def _frame_changed(self, typed=False):
        if self._pv_loading:
            return
        self._show_cached()

    def _current_key(self, form=None):
        """(fingerprint, highlight, frame) the spinboxes point at, or None
        when the form has nothing to draw."""
        form = form or self.form()
        if not form.images:
            return None
        hl = _int(self._hl_var, int(form.default))
        n = _int(self._frame_var, 0)
        return preview_fingerprint(form), hl, n

    def _show_cached(self):
        """A spinbox moved: show that frame if it is already rendered, and
        if it is not, SAY SO and ask for it.

        Doing nothing (which is what a cache miss used to do) left the
        stepper looking broken and the caption describing the frame still
        on screen - which was not the one the boxes now named."""
        key = self._current_key()
        if key is None:
            return
        path = self._pv_cache.get(key)
        if path:
            if self._pv_shown != key[1:]:
                self.load_frame(path, key[1], key[2],
                                self._pv_totals.get(key[:2]))
            return
        if self._play_var.get():
            return                          # Play draws its own frames
        self._pv_say("Image %d frame %d has not been drawn yet - %s"
                     % (key[1], key[2],
                        "drawing it…" if self.schedule_preview() else
                        "right-click the preview to redraw."))

    def _highlight(self, form):
        """The Highlight spinbox as an index into the form, or None (said)."""
        hl = _int(self._hl_var, int(form.default))
        if not 0 <= hl < len(form.images):
            self._pv_say("The image to highlight must be one of 0..%d."
                         % (len(form.images) - 1), error=True)
            return None
        return hl

    def _scaled_photo(self, path):
        """The frame at *path*, scaled SMOOTHLY into the current box with
        its aspect ratio kept - Pillow, the way the DMD preview and the
        scene browser do it.  None when the file cannot be read.

        Tk's own PhotoImage halves and thirds and nothing between, which is
        why the box used to be a whole fraction of the selector's frame;
        with Pillow the picture simply takes the width the window gives it.
        The fallback below is that older path, for a machine with no
        Pillow."""
        if _HAVE_PIL:
            try:
                with Image.open(path) as img:
                    img.load()
                    size = scaled_size(img.width, img.height,
                                       self._pv_w, self._pv_h)
                    shown = img.convert("RGB").resize(size, Image.LANCZOS)
                return ImageTk.PhotoImage(shown)
            except Exception as exc:                    # noqa: BLE001
                self._pv_say("Cannot load %s: %s" % (path, exc), error=True)
                return None
        try:
            photo = tk.PhotoImage(file=path)
        except tk.TclError as exc:
            self._pv_say("Cannot load %s: %s" % (path, exc), error=True)
            return None
        sub, zoom = fit_factors(photo.width(), photo.height(),
                                self._pv_w, self._pv_h)
        if sub > 1:
            photo = photo.subsample(sub, sub)
        if zoom > 1:
            photo = photo.zoom(zoom, zoom)
        return photo

    def load_frame(self, path, highlight=None, frame=0, total=None):
        """Show one rendered frame: the P6 PPM a snapshot wrote, scaled into
        the box.  ``total`` = the animation's frame count when known.  The
        public seam: the pipeline, the screenshot script and the tests all
        come through here.  False (and the status says why) when the file
        cannot be read."""
        photo = self._scaled_photo(path)
        if photo is None:
            return False
        self._pv_photo = photo
        c = self._pv_canvas
        try:
            c.delete("all")
            c.create_image(self._pv_w // 2 + 1, self._pv_h // 2 + 1,
                           image=photo, anchor=tk.CENTER)
        except tk.TclError:
            return False
        self._pv_shown = (highlight, frame)
        self._pv_src = (path, highlight, frame, total)
        if highlight is not None:
            self._set_var(self._hl_var, highlight)
        self._set_var(self._frame_var, frame)
        if total is not None:
            key = self._current_key()
            if key is not None:
                self._pv_totals[key[:2]] = total
            try:
                self._frame_spin.configure(to=max(0, total - 1))
            except tk.TclError:
                pass
        if total is None:
            what = "frame %d" % frame
        elif total < 2:
            what = "a still (no animation on this image)"
        else:
            what = "frame %d of %d%s" % (
                frame, total, " - playing" if self._play_var.get() else "")
        self._pv_say("Image %s: %s" % (
            "?" if highlight is None else highlight, what))
        return True

    def _redraw_shown(self):
        """The box changed size: draw the frame that is up again at the new
        scale (or the placeholder, when nothing has been rendered yet)."""
        if not self._pv_src:
            self._pv_placeholder()
            return
        path, highlight, frame, total = self._pv_src
        if os.path.isfile(path):
            self.load_frame(path, highlight, frame, total)
        else:
            self._pv_placeholder()

    # -- the preview follows the form -----------------------------------

    def schedule_preview(self, now=False):
        """Ask for a re-render ~350 ms from now, coalescing everything that
        happens in between into ONE run: typing a title fires this per
        keystroke, and one snapshot is what it costs.

        ``now=True`` (a modal's OK) still goes through the debounce, so an
        OK that lands mid-typing does not queue a second run."""
        if self._stopped:
            return False
        if not self._auto_preview.get():
            return False
        self._pv_pending += 1
        job = self._pv_debounce_job
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            self._pv_debounce_job = None
        try:
            self._pv_debounce_job = self._timer().after(
                1 if now else PREVIEW_DEBOUNCE_MS, self._auto_render)
        except tk.TclError:
            return False
        return True

    def _auto_render(self):
        """The debounce fired: render the frame the tab is pointing at, if
        there is anything to draw and nothing else is running."""
        self._pv_debounce_job = None
        self._pv_pending = 0
        if self._stopped or not self._auto_preview.get():
            return False
        if self._play_var.get():
            return False            # Play is driving its own frames
        if self._busy or self._pv_busy:
            # Try again once the run in flight is done - a build takes
            # minutes and the preview must not queue behind every keystroke.
            self.schedule_preview()
            return False
        form = self.form()
        out = (form.out or "").strip().strip('"')
        if len(form.images) < 1 or not out:
            return False
        # A render writes its conf and its frames under <out dir>/preview.
        # Half a path, typed on the way to a real one, must not leave a
        # trail of directories behind it: an output only draws by itself
        # once it names a card image in a folder that exists (or one folder
        # below one that does - <out dir> is where the card goes anyway).
        # Anything else waits for Render now, which creates what it needs.
        out_dir = os.path.dirname(os.path.abspath(out))
        if not (out.lower().endswith((".raw", ".img"))
                and (os.path.isdir(out_dir)
                     or os.path.isdir(os.path.dirname(out_dir)))):
            self._pv_stale("the card path is not a .raw in a folder that "
                           "exists yet")
            return False
        # NOT RED, BUT NOT SILENT EITHER.  An unfinished form is the normal
        # state while someone is typing, so this must not paint the status
        # block red on every keystroke - but the debounce has already
        # waited for the typing to STOP, and a preview that quietly stops
        # following the form from then on is the worst of both.  So the
        # picture's own caption says it is out of date, and why.
        errs = validate_form(form, sources=self.needs_prepare(form))
        if errs:
            self._pv_stale(errs[0], len(errs) - 1)
            return False
        hl = _int(self._hl_var, int(form.default))
        if not 0 <= hl < len(form.images):
            self._pv_stale("the image to highlight must be one of 0..%d"
                           % (len(form.images) - 1))
            return False
        n = _int(self._frame_var, 0)
        key = (preview_fingerprint(form), hl, n)
        if key in self._pv_cache:
            if self._pv_shown != key[1:]:
                self.load_frame(self._pv_cache[key], hl, n,
                                self._pv_totals.get(key[:2]))
            return False
        return self._render_frames(form, hl, [n])

    def _pv_stale(self, why, more=0):
        """The picture no longer matches the form, and here is why.

        Said on the preview's own caption, in the ordinary colour: this is
        a normal state (a field being filled in), not a failure - but it is
        never left unsaid, because a preview that has quietly stopped
        following the form looks exactly like one that is up to date."""
        text = "Preview not updated: %s." % why.rstrip(".")
        if more > 0:
            text += "  (+%d more)" % more
        self._pv_say(text)

    def needs_prepare(self, form=None):
        """Whether the preview has to render the media before it can draw.

        NO for a card just loaded whose media fields are still the card's
        own: those files are already in the dir the load extracted, and a
        prepare would only copy them over themselves (a 'file' spec pointing
        into the directory selectmedia writes).  YES the moment one of them
        is changed, and always outside editing mode."""
        if not self._loaded_card or self._loaded_form is None:
            return True
        form = self.form() if form is None else form
        return media_specs_changed(self._loaded_form, form)

    def render_preview(self):
        """'Redraw the preview now' (the preview's right-click menu): the
        frame the spinboxes point at, whether or not it is cached."""
        # A loaded card whose media has not been touched draws from the card
        # itself, so the .raw files it was built from need not be here.
        form = self._validated_form(sources=self.needs_prepare())
        if form is None:
            self._pv_say("Fix the form first - see the line above.",
                         error=True)
            return False
        hl = self._highlight(form)
        if hl is None:
            return False
        return self._render_frames(form, hl, [_int(self._frame_var, 0)])

    def _render_frames(self, form, hl, frames):
        """Render *frames* of the menu with image *hl* highlighted, on the
        worker: ensure a selector, prepare the media, then one snapshot per
        frame.  Each finished frame lands in the cache; the one the
        spinboxes point at is shown at once (Play shows its own from the
        tick).  False when the busy guard refused.

        WHAT MAKES THIS CHEAP ENOUGH TO RUN ON EVERY KEYSTROKE: the two
        expensive steps are skipped by their own tests, not by the frame's.
        The selector is built once per session (``make`` is incremental
        anyway).  The media is prepared only when the MEDIA fingerprint
        moved - the art, the clips, the music, the two sounds - and never
        for a loaded card whose media fields are still the card's own (see
        :meth:`needs_prepare`).  A title, a subtitle, the countdown or the
        default changes none of that: the conf below is rewritten and one
        snapshot draws it."""
        fp = preview_fingerprint(form)
        mfp = media_fingerprint(form)
        pv = preview_dir_for(form.out)
        media = self.media_dir()
        conf = os.path.join(pv, "images.conf")
        self._forget_old_dirs(pv, media)
        try:
            self._makedirs(pv)
            self._makedirs(media)
            with open(conf, "w", encoding="utf-8", newline="\n") as f:
                f.write(write_preview_conf(form))
        except OSError as exc:
            self._pv_say("Cannot write the preview files: %s" % exc,
                         error=True)
            return False
        self._prune_frames(pv, fp)
        rootfs = rootfs_for(form.selector_dir)
        cmds = []
        # THE SELECTOR IS CACHED, BUT NOT FOREVER.  Skipping the make step
        # is what makes a keystroke render cheap; never running it again
        # meant a codeselect rebuilt beside the app was not picked up until
        # the app was restarted.  So it is re-checked when the cached
        # answer is older than SELECTOR_TTL_S (make is incremental: a
        # no-op once built), and at once when the build PATH changes.
        if (not self._pv_bin
                or time.time() - self._pv_bin_at > self.SELECTOR_TTL_S):
            cmds += ensure_selector_commands(form)
        # THE DIRECTORY IS PART OF THE KEY.  media_fingerprint leaves the
        # output path out on purpose (a retyped output does not change what
        # the media IS), but the directory the media is written into comes
        # straight off it - so without this a new output path kept the old
        # dir's 'prepared' answer, left the new one empty, and Build &
        # verify wrote a text-only card.
        if self._pv_ready != (mfp, media):
            if self.needs_prepare(form):
                cmds += preview_prepare_commands(form, media)
            else:
                # The card's own media, straight out of the extraction: it
                # matches the form because the form came out of the card.
                self._pv_ready = (mfp, media)
        paths = {}
        for n in frames:
            ppm = frame_path(pv, fp, hl, n)
            paths[n] = ppm

            def argv(texts, n=n, ppm=ppm):
                binary = parse_selector_path(texts.get("selector", "")) \
                    or self._pv_bin
                if not binary:
                    raise RuntimeError("the selector step named no binary")
                return snapshot_commands(binary, conf, media, ppm, hl, n,
                                         rootfs)[0][1]
            cmds.append(("frame %d" % n, argv))

        def step(label, rc, text):
            if rc != 0:
                return
            if label == "selector":
                self._pv_bin = parse_selector_path(text)
                self._pv_bin_at = time.time()
            elif label == "prepare":
                self._pv_ready = (mfp, media)
            elif label.startswith("frame "):
                n = int(label.split()[1])
                total = parse_anim_frames(text, hl)
                self._pv_totals[(fp, hl)] = total or 1
                self._pv_cache[(fp, hl, n)] = paths[n]
                key = self._current_key()
                if not self._play_var.get() and key == (fp, hl, n):
                    self.load_frame(paths[n], hl, n, total or 1)

        def done(rc, failed, _texts):
            if rc == 0:
                if not self._play_var.get():
                    key = self._current_key()
                    if key in self._pv_cache and self._pv_shown != key[1:]:
                        self.load_frame(self._pv_cache[key], key[1], key[2],
                                        self._pv_totals.get(key[:2]))
                return
            # ANY failed step forgets the prepared media, a frame render
            # included: a snapshot that failed on broken media would
            # otherwise keep failing, because the next render would skip
            # prepare and hand the selector the same broken files. Preparing
            # again costs almost nothing - selectmedia's sidecar cache reuses
            # every unchanged picture (measured 0.13 s for a two-image set).
            self._pv_ready = None
            self._stop_play(None)
            self._pv_say("Preview failed at %s (exit %d) - see the tool "
                         "output." % (failed or "the start", rc), error=True)

        self._pv_say("rendering…")
        if not self._run_commands(cmds, on_step=step, on_done=done,
                                  preview=True):
            self._pv_say("A run is already in progress - wait for it.",
                         error=True)
            return False
        return True

    def _makedirs(self, path):
        """``os.makedirs``, remembering what WE created - so a directory the
        preview made for a path that was only half typed can be taken away
        again (:meth:`_forget_old_dirs`).  A directory that was already
        there is never remembered and never removed."""
        if path and not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            self._pv_made.add(os.path.normcase(os.path.abspath(path)))

    def _forget_old_dirs(self, pv, media):
        """Take back the preview/ and media/ directories WE made under an
        output path that is no longer the one in the box.

        Typing ``D:/Pinball/mul`` on the way to ``D:/Pinball/multi`` used to
        leave a preview/ and a media/ behind under every prefix that
        happened to render.  Only our own directories, only our own files,
        and only while they hold nothing else."""
        keep = {os.path.normcase(os.path.abspath(p)) for p in (pv, media) if p}
        for made in sorted(self._pv_made - keep, key=len, reverse=True):
            try:
                for name in os.listdir(made):
                    if _FRAME_RE.match(name) or name == "images.conf":
                        os.remove(os.path.join(made, name))
                os.rmdir(made)              # refuses a dir with anything in
            except OSError:
                pass                        # in use, or not ours to judge
            self._pv_made.discard(made)
            parent = os.path.dirname(made)
            pkey = os.path.normcase(os.path.abspath(parent))
            if pkey in self._pv_made and pkey not in keep:
                try:
                    os.rmdir(parent)
                    self._pv_made.discard(pkey)
                except OSError:
                    pass

    def _prune_frames(self, pv, fp):
        """Drop the frame files of every form but this one - preview/ would
        otherwise grow a file per (form, image, frame) for as long as the
        tab is open.  The picture ON SCREEN is kept whatever form drew it:
        a resize redraws from that very file."""
        shown = os.path.abspath(self._pv_src[0]) if self._pv_src else ""
        for path in stale_frames(pv, fp):
            if os.path.abspath(path) == shown:
                continue
            try:
                os.remove(path)
            except OSError:
                continue
            for key, cached in list(self._pv_cache.items()):
                if cached == path:
                    self._pv_cache.pop(key, None)

    def _play_toggled(self):
        if not self._play_var.get():
            self._stop_play(None)
            return
        form = self.form()
        errs = validate_form(form, sources=self.needs_prepare(form))
        if errs:
            self._stop_play("Fix the form first - see the line above.")
            self._error("\n".join(errs))
            return
        hl = self._highlight(form)
        if hl is None:
            self._stop_play(None)
            return
        fp = preview_fingerprint(form)
        total = self._pv_totals.get((fp, hl))
        if total is not None and total < 2:
            self._stop_play("Image %d has no animation to play." % hl)
            return
        self._play_fp, self._play_hl = fp, hl
        self._schedule_tick(0)

    def _schedule_tick(self, ms=None):
        if self._play_job is not None:
            return
        try:
            self._play_job = self._timer().after(
                self.PLAY_MS if ms is None else ms, self._play_tick)
        except tk.TclError:
            pass

    def _play_tick(self):
        """One step of Play: the next cached frame, or a render of the
        frames still missing (in play order, one run) while this one stays
        up.  Stops when the form no longer matches the frames or a render
        fails."""
        self._play_job = None
        if self._stopped or not self._play_var.get():
            return
        form = self.form()
        fp = preview_fingerprint(form)
        if fp != self._play_fp:
            self._stop_play("The form changed - press Render preview.")
            return
        hl = self._play_hl
        total = self._pv_totals.get((fp, hl))
        if total is not None and total < 2:
            self._stop_play("Image %d has no animation to play." % hl)
            return
        cur = _int(self._frame_var, 0)
        nxt = (cur + 1) % total if total else cur
        key = (fp, hl, nxt)
        if key in self._pv_cache:
            self.load_frame(self._pv_cache[key], hl, nxt, total)
        elif not (self._busy or self._pv_busy):
            if total is None:
                missing = [cur]
            else:
                missing = [(nxt + k) % total for k in range(total)
                           if (fp, hl, (nxt + k) % total) not in self._pv_cache]
            if missing:
                self._render_frames(form, hl, missing)
        self._schedule_tick()

    def _stop_play(self, msg):
        self._play_var.set(False)
        if self._play_job is not None:
            try:
                self._timer().after_cancel(self._play_job)
            except (tk.TclError, ValueError):
                pass
            self._play_job = None
        if msg:
            self._pv_say(msg, error=True)

    # ------------------------------------------------------------------
    # running the tools
    # ------------------------------------------------------------------

    def _set_busy(self, busy):
        """The guard on the runs that WRITE: every action control greyed
        while one is up.  A preview render never comes through here - it is
        a background redraw of a picture, and greying the whole tab once
        per typing pause (which is what it did) makes Apply, Build, Flash,
        Run and the two menus swallow clicks while someone types a title."""
        self._busy = busy
        for btn in list(getattr(self, "_action_btns", ())):
            if btn is None:
                continue
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
        # ...and Apply to card is only ever live for a loaded card whose
        # image list still matches it.
        self._update_edit_status()

    #: What each tool step means on the tab's OWN stage row (Media, Copy,
    #: Inject, Verify - MainWindow.MULTIBOOT_PHASES).  Both writing buttons
    #: read honestly on it: Build & verify walks all four, Apply to card
    #: only the last two (plus Media when a media field moved).
    PHASE_OF = {"prepare": 0, "plan": 0, "build": 1, "inject": 2,
                "bypass": 2, "verify": 3, "inspect": 3, INSPECT_JSON: 3}

    #: ...and what the footer's status line says while it is there.
    PHASE_STATUS = {
        "prepare": "Rendering the menu's media…",
        "plan": "Planning the card's layout…",
        "build": "Copying the images into the card…",
        "inject": "Writing the menu into the card…",
        "bypass": "Patching the game validator…",
        "verify": "Verifying the card…",
        "inspect": "Reading the card back…",
        INSPECT_JSON: "Reading the card back…",
    }

    def _phase_step(self, label):
        """A tool step is about to run: light its stage in the footer."""
        index = self.PHASE_OF.get(label)
        if index is None:
            return
        try:
            self._phase_fn(index, status=self.PHASE_STATUS.get(label))
        except Exception:                               # noqa: BLE001
            pass                        # the window went; the run has not

    def _phase_done(self, rc, failed):
        try:
            if rc == 0:
                self._phase_fn(-1, status="Ready")
            else:
                self._phase_fn(None,
                               status="%s failed" % (failed or "the run"))
        except Exception:                               # noqa: BLE001
            pass

    def _run_commands(self, cmds, on_step=None, on_done=None, quiet=(),
                      preview=False):
        """Run ``[(label, argv), ...]`` in order on a worker, streaming every
        line into the pane; stop at the first failure.  An *argv* may be a
        callable ``fn(texts)`` - evaluated on the worker just before its
        turn, from what the earlier steps printed (the preview's snapshot
        needs the binary the selector step named).  ``on_step(label, rc,
        text)`` and ``on_done(rc, failed_label, {label: text})`` are called
        on the main loop.

        TWO GUARDS, NOT ONE.  A run that WRITES (build, apply, load,
        bypass) is one at a time and greys every action control while it is
        up: two builds into one file is a corrupt card.  ``preview=True``
        is the background redraw, and takes its own light guard instead -
        one render at a time, and nothing disabled.  An action asked for
        while a render is in flight is not refused: the render is told to
        stop after the step it is on, and the action starts the moment it
        lets go (the action's own guard is taken now, so a second one is
        still refused).  False when the guard refused.

        A label in *quiet* is still run and still captured, but its lines
        do not go into the pane while it succeeds: the load's JSON report is
        for the form, and the table beside it is what a person reads.  A
        quiet step that FAILS prints everything it said.
        """
        if preview:
            # A render never queues behind anything: it is cheap, and the
            # next keystroke asks for another one anyway.
            if self._busy or self._pv_busy:
                return False
            self._pv_cancel = False
            self._pv_busy = True
        else:
            if self._busy:
                self._error("A run is already in progress.")
                return False
            self._set_busy(True)
            if self._pv_busy:
                self._pv_cancel = True
                self._pending_run = (cmds, on_step, on_done, frozenset(quiet))
                self._drain()       # the render's finish starts it
                return True
        self._start_worker(cmds, on_step, on_done, frozenset(quiet), preview)
        return True

    def _start_worker(self, cmds, on_step, on_done, quiet, preview):
        """The worker itself - see :meth:`_run_commands`, which owns the
        guards.  Split out so a queued action can be started from the
        render's own finish without going through them again."""
        def run():
            rc = 0
            failed = None
            texts = {}
            for label, argv in cmds:
                if preview and self._pv_cancel:
                    # An action is waiting for the worker: stop between
                    # steps rather than mid-tool, and say nothing - the
                    # picture is redrawn once the action is done.
                    break
                if not preview:
                    # The tab's own stage row: this step is starting.
                    self._ui(lambda lab=label: self._phase_step(lab))
                if callable(argv):
                    try:
                        argv = argv(texts)
                    except Exception as exc:                # noqa: BLE001
                        self._append("[multi-boot] %s: %s" % (label, exc))
                        rc, failed = 1, label
                        break
                self._append("$ " + argv[-1])
                try:
                    proc = subprocess.Popen(
                        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        creationflags=_rig.CREATE_FLAGS)
                except Exception as exc:                # noqa: BLE001
                    self._append("[multi-boot] cannot start %s: %s"
                                 % (label, exc))
                    rc, failed = 1, label
                    break
                self._proc = proc
                lines = []
                echo = label not in quiet
                try:
                    for raw in proc.stdout:
                        line = raw.decode("utf-8", "replace").rstrip()
                        lines.append(line)
                        if echo:
                            self._append(line)
                except Exception:                       # noqa: BLE001
                    pass                                # pipe closed under us
                rc = proc.wait()
                self._proc = None
                texts[label] = "\n".join(lines)
                if not echo and rc != 0:
                    for line in lines:                  # it failed: say why
                        self._append(line)
                self._append("%s: exit %d" % (label, rc))
                if on_step is not None:
                    self._ui(lambda l=label, r=rc, t=texts[label]:
                             on_step(l, r, t))
                if rc != 0:
                    failed = label
                    break

            def finish():
                if preview:
                    self._pv_busy = False
                    cancelled = self._pv_cancel
                    self._pv_cancel = False
                    pending = self._pending_run
                    self._pending_run = None
                    if pending is not None:
                        # The action that was waiting: its guard was taken
                        # when it asked, so nothing else got in.
                        self._pv_say("")
                        p_cmds, p_step, p_done, p_quiet = pending

                        def done_then_redraw(r, f, t, _d=p_done):
                            if _d is not None:
                                _d(r, f, t)
                            self.schedule_preview()
                        self._start_worker(p_cmds, p_step, done_then_redraw,
                                           p_quiet, False)
                        return
                    if cancelled:
                        self._pv_say("")
                        return
                else:
                    self._set_busy(False)
                    self._phase_done(rc, failed)
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

    def _append(self, line):
        """A tool line, from the worker.  Queued for the main loop, because
        that is where the app's Log lives."""
        self._ui(lambda: self._write(line))

    def _write(self, line):
        """One line into the app's Log at the foot of the window - THE one
        log, tagged so it reads beside the other tabs' lines.

        This tab used to keep a folded-away 'Tool output' pane of its own,
        which meant two places to look and one of them hidden.  The pane is
        gone; the tag is what tells the lines apart."""
        self._lines.append(line)
        if len(self._lines) > self.LOG_KEEP:
            del self._lines[:len(self._lines) - self.LOG_KEEP]
        try:
            self._log_sink(self.LOG_TAG + line)
        except Exception:                               # noqa: BLE001
            pass                    # a sink that has gone with its window

    def log_lines(self):
        """Everything the tools have said, in order - what the status
        block's one line had to leave out.  The app's Log has the same
        lines; this is the seam the tests read."""
        return list(self._lines)
