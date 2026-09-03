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
under the window.  Top to bottom, in the order the work happens: ONE card
path first, with the verb that reads it beside it (reading a card you
already built is the usual first move); then a two-column body - a narrow
image list on the left, the PREVIEW on the right, large and always
visible; then ONE action bar; then one status block; then the tools' own
output, folded away.  The detail of one image and of the menu is behind
two modals (:class:`ImageEditorDialog`, :class:`MenuSettingsDialog`),
which is what makes the whole tab fit the ~640 px of content height a
1024x768 desktop leaves for it - David's desktop, and the constraint the
layout is designed around.  The modals bind to the PANEL's own variables,
so there is one form whether a dialog is open or not, and Cancel restores
the snapshot taken when it opened.

THE PATH IS THE CARD'S IDENTITY, and the row carries one of them.  It used
to carry two file pickers and a box: 'Load card…' asked for a card to
read, 'New card…' cleared the form, and 'Card image' named the output -
which after a load was also the card being edited.  Two ways to do one
thing, and a field whose meaning changed with a mode nothing showed
(David, 2026-09-02: "why do i have a browse and input section when i have
a 'new card' and 'load card' one?").  Now the box IS the card, the verb
beside it reads whatever the box names, and EDITING MODE is exactly "the
file at that path has been read into this form" - so typing the box away
from the loaded card leaves editing mode, and nothing can be applied to a
card the box no longer names.  What the path is pointing at, and which of
the two writing buttons that makes live, is said in words on the status
block's second line (see :func:`card_path_state`) - the one place the tab
already had for "what would the button under this do", and the only one
that costs no height.

BUTTONS LIVE IN EXACTLY THREE PLACES: the source row at the top, the
action bar at the bottom, and the two FLIPPERS under the picture - and
that third pair is the MACHINE'S controls rather than the tab's, sitting
under the very menu they move and named by that menu's own footer.  The
image list has none - right-click a row for Add / Edit / Remove / Up /
Down (double-click and Return still open Edit), and a dim line under the
list says so - and the preview has no button of its own: its right-click
menu carries the manual refresh, the 'update automatically' toggle and
the two sound entries.  A tab whose every control is a button reads as
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
loads natively.  'Play' runs the highlighted card's animation: the WHOLE
run comes out of ONE selector run (``--snapshot <pattern> --frames K``,
one media load instead of K) and is then played from memory at the clip's
own frame rate, so after the first pass nothing touches the disk.
Because a preview leaves a sound-less media.json behind, 'Build & verify'
runs a full prepare into that dir first whenever a media set exists - the
card is never built from the preview's half of the media.

THE FLIPPERS, AND THE SOUND.  The picture's own controls are the
machine's, in the machine's own words: the footer drawn INSIDE the
picture says "LEFT / RIGHT FLIPPER: choose", and the two buttons under it
are those - they move the highlight and WRAP, exactly as codeselect.c's
EV_LEFT / EV_RIGHT do (``hl = (hl + n - 1) % n`` / ``hl = (hl + 1) % n``),
and the arrow keys do the same while the picture has the focus.  'Sound'
plays what the menu plays, through :mod:`.preview_audio`: the highlighted
image's music bed, the move click on every flipper press, and - from the
picture's right-click menu - that image's own confirm sound, the one
sound with no other way of being heard before a card is written.  Every
WAV is the one media.json names, so what is heard is what the card will
play.  IT STARTS OFF, and staying off is the point: this app is used in
the same room as a machine that is running, and a tab that starts playing
music because someone clicked an image is exactly what that asks us not
to do.  One click turns it on, and the caption says so once when the
highlighted image has music nobody is hearing.

READING A CARD BACK.  'Load card' runs ``mkmulticard.py inspect`` on the
card the path box names - the tool's table into the pane, the same read as
JSON for the form, and the card's own media extracted into ``<card dir>/
media-<stem>`` - and fills EVERY field from it: the images and where they came
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
so; and because the path box now holds the loaded card, 'Build & verify'
refuses until it is pointed somewhere else rather than copying ~7 GB over
the card being edited.  A card whose media has no source recorded (a v1
card, or a music bed) keeps its file names: they can be kept and drawn, but
not re-rendered, and the tab says which field to re-point before a media
change can be applied.  A load is a CLICK and never a keystroke: it costs a
WSL round trip, writes a media dir beside the card and replaces every
field, and on the way to typing ``x.raw.bak`` you pass through ``x.raw``,
which exists.

COMING BACK AS YOU LEFT IT.  The form is remembered per project, on the
rail the Emulate tab's card path already rides: the hidden ``.pinproj``
anchor, with the global settings as the fallback for having no project
open (see :meth:`MultibootPanel.state` and ``App.restore_multiboot_state``).
The FORM only - never the baseline a load left behind, because the card may
have changed since and Apply's whole legality is decided by that baseline.
A restarted app therefore comes back with the images, the menu and the
path, out of editing mode, and one click on the verb earns editing mode
back honestly.  The preview's Sound box is deliberately not remembered: it
starts off, every time, because this app is used in the room with a machine
that is running.

WHAT IS NOT HERE.  No TOOL runs when the tab is built or restored - the
path box is stat'ed on a worker thread so the row can say what is at it
(:func:`probe_card_path`), and that is the whole of it: nothing reads the
card, nothing runs WSL, and no path is guessed from the Input box.  No two
tool runs overlap either: a build copies ~7 GB per image and the tab is
busy until the run has said PASS or FAIL.
"""

import errno
import hashlib
import json
import os
import queue
import re
import shlex
import stat
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import (asdict, dataclass, field, fields as dc_fields,
                         replace)
from tkinter import colorchooser, filedialog, font as tkfont, messagebox, ttk

from . import _rig
from .emulate_tab import rig_dir
from .preview_audio import PreviewAudio
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
#: THE MENU'S COLOUR THEMES: the selector's own themes.json, one definition -
#: the selector compiles it in, mkmulticard.py writes the keys, this tab shows
#: the picker and the "make your own" colour grid.  Read once, on first use,
#: never at import: a checkout without it must not stop the app; the picker
#: says so and the default theme still draws.
THEMES_JSON = CODESELECT_SRC + "/themes.json"
DEFAULT_THEME = "midnight"
CUSTOM_THEME = "custom"
CUSTOM_TITLE = "Make your own…"

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
#: The art and the animation have no list of their own any more: the Edit
#: image… dialog offers them as ONE choice (:data:`MEDIA_KINDS`), and the
#: words 'auto' / 'none' are what that choice writes into the row.
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

#: The most frames one snapshot run may be asked for - codeselect.c's
#: ANIM_MAX_FRAMES, which is both the number of frames an animation is
#: decoded to and the largest ``--frames`` it accepts (a bigger K is
#: refused, exit 2).  Asking for exactly this is how Play gets a whole
#: animation of unknown length out of ONE run: the selector trims K to what
#: the highlighted image really has, and says so in its log.
PREVIEW_MAX_FRAMES = 30

#: How many DECODED frames the preview keeps in memory.  A frame FILE is
#: cheap to remember (a path in a dict); a frame scaled into a PhotoImage
#: is ~1 MB of RGBA at the sizes this tab draws at, so one animation is
#: ~30 MB and sixteen images' worth would be half a gigabyte.  Play only
#: ever walks ONE image's animation, so one animation and a still or two
#: is the whole working set.
PHOTO_CACHE_MAX = PREVIEW_MAX_FRAMES + 2

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

#: What the step that draws a WHOLE animation is called - in the log pane,
#: in 'Preview failed at …', and in the render's own bookkeeping.  A single
#: frame keeps its own 'frame N' label: they are read back differently
#: (see :meth:`MultibootPanel._render_frames`).
ANIM_LABEL = "animation"


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
    #: The menu's colours: a built-in theme's name, or ``custom`` with every
    #: role in ``colors`` (``{role: rrggbb}``; empty for a built-in).
    theme: str = DEFAULT_THEME
    colors: dict = field(default_factory=dict)


_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_boot_themes = None
#: This checkout, from the package's own place in it - the fallback for a
#: rig that lives elsewhere (or nowhere, on a machine that only browses).
_PKG_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def themes_json_paths():
    """Where themes.json is looked for, in order: the rig's checkout (the
    selector the preview builds and the cards are written from come from
    there), then this package's own."""
    return [os.path.join(repo_dir(), THEMES_JSON),
            os.path.join(_PKG_REPO, THEMES_JSON)]


def boot_themes():
    """themes.json parsed: ``{'roles': [...], 'labels': {role: text},
    'default': name, 'themes': [{'name', 'title', 'about', 'colors': {role:
    rrggbb}}]}``, or None when the file cannot be read.  Read once."""
    global _boot_themes
    if _boot_themes is None:
        try:
            doc = None
            for path in themes_json_paths():
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        doc = json.load(f)
                    break
            if doc is None:
                raise OSError("no themes.json")
            roles = [str(r) for r in doc["roles"]]
            labels = doc.get("labels") or {}
            themes = []
            for t in doc["themes"]:
                colors = {r: _COLOR_RE.match(str(t["colors"][r])).group(1)
                          .lower() for r in roles}
                themes.append({"name": str(t["name"]),
                               "title": str(t.get("title") or t["name"]),
                               "about": str(t.get("about") or ""),
                               "colors": colors})
            _boot_themes = {
                "roles": roles,
                "labels": {r: str(labels.get(r) or r) for r in roles},
                "default": str(doc.get("default") or DEFAULT_THEME),
                "themes": themes}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            _boot_themes = False
    return _boot_themes or None


def theme_roles():
    """The colour roles, in the selector's order; none without the file."""
    th = boot_themes()
    return list(th["roles"]) if th else []


def theme_names():
    """The built-ins' names, the default first; the default alone without
    the file."""
    th = boot_themes()
    return [t["name"] for t in th["themes"]] if th else [DEFAULT_THEME]


def theme_title(name):
    """What the picker shows for a theme name."""
    name = (name or "").strip().lower()
    if name == CUSTOM_THEME:
        return CUSTOM_TITLE
    for t in (boot_themes() or {}).get("themes", []):
        if t["name"] == name:
            return t["title"]
    return name or DEFAULT_THEME


def theme_about(name):
    """A built-in's one-line description; '' for the rest."""
    name = (name or "").strip().lower()
    if name == CUSTOM_THEME:
        return ("Your own colours: start from the theme shown, then change "
                "any of them.")
    for t in (boot_themes() or {}).get("themes", []):
        if t["name"] == name:
            return t["about"]
    return ""


def theme_label(role):
    """A colour role's label ('Card frame, highlighted')."""
    return (boot_themes() or {}).get("labels", {}).get(role, role)


def theme_colors(name):
    """A built-in's ``{role: rrggbb}`` (a copy), or None."""
    name = (name or "").strip().lower()
    for t in (boot_themes() or {}).get("themes", []):
        if t["name"] == name:
            return dict(t["colors"])
    return None


def clean_colors(colors):
    """``{role: rrggbb}`` keeping only the roles the selector knows and the
    values that are six hex digits (a '#' dropped, lower case)."""
    roles = theme_roles()
    out = {}
    if not isinstance(colors, dict):
        return out
    for role, val in colors.items():
        m = _COLOR_RE.match(str(val).strip())
        if role in roles and m:
            out[role] = m.group(1).lower()
    return out


def theme_from_card(theme, colors):
    """A card's ``theme`` / ``colors`` (inspect's answer) -> the form's
    ``(theme, colors)``.  A built-in with no overrides is itself.  Overrides
    on top of anything - the selector allows them on a built-in, this tab
    offers them only as the custom theme - become the custom theme with
    every role spelled out (the base's colours under them), so what the tab
    shows is what the machine draws.  An unknown name is the default."""
    name = (theme or "").strip().lower()
    over = clean_colors(colors)
    base = name if name in theme_names() else DEFAULT_THEME
    if name != CUSTOM_THEME and not over:
        return base, {}
    full = dict(theme_colors(base) or {})
    full.update(over)
    return CUSTOM_THEME, full


def theme_args(form):
    """``--theme NAME`` and, for the custom theme, one ``--color
    ROLE=RRGGBB`` per role in the selector's order - what build and inject
    both carry, so an explicit theme is the whole answer."""
    theme = (form.theme or "").strip().lower() or DEFAULT_THEME
    args = ["--theme", theme]
    if theme == CUSTOM_THEME:
        clean = clean_colors(form.colors)
        for role in theme_roles():
            if role in clean:
                args += ["--color", "%s=%s" % (role, clean[role])]
    return args


def theme_conf_lines(form):
    """The images.conf lines for the form's theme (the preview's conf)."""
    theme = (form.theme or "").strip().lower() or DEFAULT_THEME
    lines = ["theme=" + theme]
    if theme == CUSTOM_THEME:
        clean = clean_colors(form.colors)
        lines += ["color_%s=%s" % (r, clean[r]) for r in theme_roles()
                  if r in clean]
    return lines


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


def _plain(p):
    """A path compared WITHOUT touching the disk: absolute, with the
    platform's own case and separator rules and no link resolution.

    :func:`_norm` is the real answer and every GATE uses it - it resolves
    links, which is how the library junction is caught - but it stats, and
    anything that runs on the Tk thread for every keystroke of an arbitrary
    typed path has to be able to say what it sees without freezing on a
    drive that is not there (the UI-thread freeze class this tree has
    already paid for).  A text match is all a SENTENCE about the path
    needs."""
    p = (p or "").strip().strip('"')
    if not p:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def under_library(path, resolve=True):
    """Whether *path* lies in the card library nothing may write into.

    ``resolve=False`` answers from the text alone (:func:`_plain`), for the
    callers that must not stat - see there.  The gates leave it True."""
    if not path:
        return False
    norm = _norm if resolve else _plain
    sep = "/" if resolve else os.sep
    n = norm(path)
    for pre in LIBRARY_PREFIXES:
        pn = norm(pre)
        if n == pn or n.startswith(pn + sep):
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
    """Where a prepare renders for an output: ``<out dir>/media`` - and
    where the preview renders too, so the two share one cache."""
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


def frame_pattern(preview_dir, fingerprint, highlight):
    """:func:`frame_path` with the FRAME left for the selector to fill in.

    ``--frames K`` (K > 1) makes the ``--snapshot`` value a printf pattern
    taking exactly one bare ``%d`` - and the number it fills in is the frame,
    not the position in the run - so a run that wraps writes exactly the file
    names a frame-at-a-time render would have written, and the same cache and
    the same :data:`_FRAME_RE` sweep hold for both.

    THE DIRECTORY IS ESCAPED INTO THE PATTERN, not joined into it.  The
    selector counts every ``%`` in the value it is given
    (``check_frames_pattern``), not only the one appended here, so a card
    written to a folder with a per-cent in its name - ``D:\\Pinball\\100%
    builds\\card.multi.raw`` - made the whole Play run exit 2 before a byte
    was written, with an error that named the selector and not the folder.
    ``%%`` is the printf spelling of a literal per-cent and is what the
    selector asks for, so ``frame_pattern(d, f, h) % n`` is
    :func:`frame_path` again whatever *d* holds."""
    return os.path.join(preview_dir.replace("%", "%%"),
                        "frame_%s_%d_%%d.ppm" % (fingerprint, highlight))


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
# what the menu would PLAY (the prepared media's own manifest)
# ---------------------------------------------------------------------------

#: The file ``selectmedia.py prepare`` leaves in the media directory, and
#: the only place that says which WAV the menu plays for which image.  The
#: preview reads it rather than working the sounds out from the form: the
#: form holds SPECS ('auto', 'synth', a path on this machine), and what the
#: selector will really open is the file the tools rendered from them.
MEDIA_MANIFEST = "media.json"


def read_manifest(media_dir):
    """``media.json`` out of a prepared media directory, or ``{}``.

    Everything about it is optional: a directory that has not been prepared,
    a card built before the manifest existed and a half-written file are all
    'this media set names no sounds', which is a thing the tab says rather
    than a thing that raises.  NO directory is one of them: an empty output
    box must not turn into a relative path and read whatever media.json the
    app happens to have been started in."""
    if not media_dir:
        return {}
    try:
        with open(os.path.join(media_dir, MEDIA_MANIFEST),
                  encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def manifest_sounds(manifest, media_dir, highlight):
    """``{"music", "move", "confirm"}`` - the WAV behind each of the menu's
    three sounds for image *highlight*, as full paths under *media_dir*, and
    "" for one this media set has not got.

    The fallbacks are the selector's, not ours: an image plays its OWN
    confirm sound when it has one (the seventh images.conf field) and the
    menu-wide one otherwise - codeselect.c's ``own_confirm[i] ? : confirm``.
    A ``--visual-only`` prepare (the one the preview runs for itself) writes
    the music but no move or confirm sound at all, which is why "" here is
    ordinary and has to be said rather than treated as a fault."""
    images = manifest.get("images") or []
    row = images[highlight] if 0 <= highlight < len(images) else None
    row = row if isinstance(row, dict) else {}

    def full(name):
        return os.path.join(media_dir, name) if name and media_dir else ""
    return {"music": full(row.get("music")),
            "move": full(manifest.get("sound_move")),
            "confirm": full(row.get("confirm")
                            or manifest.get("sound_confirm"))}


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
    theme = (form.theme or "").strip().lower() or DEFAULT_THEME
    if theme != CUSTOM_THEME and theme not in theme_names():
        errs.append("The theme %r is not one the selector has." % form.theme)
    if theme == CUSTOM_THEME:
        roles = theme_roles()
        for role, val in sorted((form.colors or {}).items()):
            if role not in roles:
                errs.append("%r is not a colour the menu has." % role)
            elif not _COLOR_RE.match(str(val).strip()):
                errs.append("The %s colour must be six hex digits (RRGGBB), "
                            "not %r." % (theme_label(role).lower(), val))
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
                "this machine - pick something else for it in Edit image… "
                "before building a new card." % (i, what, val))
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


def gif_period_ms(path):
    """How long ONE frame of a rendered animation is on screen, in ms, read
    off the GIF ITSELF - or None when there is no readable GIF there.

    THE ONLY HONEST SOURCE FOR THE RATE.  codeselect.c ticks on the clip's
    own per-frame delay (``next_tick = now + a->delay_ms[frame]``), and the
    file that carries those delays is the one selectmedia rendered - which
    is very often NOT what the form asked for: ``gif_first_plan`` drops the
    frame rate to fit 30 frames, and ``gif_ladder`` drops it again (to 8,
    then 6, then 5) to fit the byte budget.  A row that says 25 fps is
    normally a 10 fps clip.  The mean of the delays, because the encoder
    writes one constant rate and Play holds every frame for the same time;
    a zero delay is the 100 ms art.c gives it (``art.h``: 'n delays; 100
    when the GIF said 0')."""
    if not (_HAVE_PIL and path):
        return None
    delays = []
    try:
        with Image.open(path) as img:
            # A GIF, or nothing: Pillow will happily open the PPM beside it
            # and report one frame of no duration, and a made-up 100 ms is
            # worse than saying the rate is not known.
            if (img.format or "").upper() != "GIF":
                return None
            for n in range(int(getattr(img, "n_frames", 1))):
                img.seek(n)
                delays.append(int(img.info.get("duration") or 0) or 100)
    except Exception:                                   # noqa: BLE001
        return None                     # not there, not a GIF, half written
    if not delays:
        return None
    return int(round(sum(delays) / float(len(delays))))


def anim_period_ms(row, frames=None, delay_ms=None,
                   floor_ms=16, ceiling_ms=2000):
    """How long ONE frame of this row's animation is on screen, in ms.

    THREE ANSWERS, BEST FIRST, because the form is the worst of them.  The
    rendered clip's own delay (*delay_ms*, from :func:`gif_period_ms`) is
    what the machine ticks on and settles it outright.  Without a GIF to
    read, the run's own frame count (*frames*, off the selector's ``frame F
    of N``) over the clip's length is the rate the tool really rendered at,
    which is what the ladder above left it at.  Only with neither is the
    row's FPS field believed - and that is the number selectmedia clamps,
    so it is a first guess for the ticks before the count arrives and not a
    fact.  Clamped either way, because the fields are typed: 0.4 fps is a
    slideshow and 300 fps is a busy loop, and neither is worth letting a
    typo cause."""
    ms = None
    if delay_ms and delay_ms > 0:
        ms = float(delay_ms)
    elif frames and int(frames) > 1:
        try:
            secs = float(_num(getattr(row, "anim_seconds", ""),
                              ANIM_DEFAULTS[1]))
        except (TypeError, ValueError):
            secs = float(ANIM_DEFAULTS[1])
        if secs > 0:
            ms = 1000.0 * secs / int(frames)
    if ms is None:
        try:
            fps = float(_num(getattr(row, "anim_fps", ""), ANIM_DEFAULTS[2]))
        except (TypeError, ValueError):
            fps = float(ANIM_DEFAULTS[2])
        if fps <= 0:
            fps = float(ANIM_DEFAULTS[2])
        ms = 1000.0 / fps
    return max(floor_ms, min(ceiling_ms, int(round(ms))))


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
    ] + theme_args(form)
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
            "--volume", str(int(form.volume))] + theme_args(form)
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
                          rootfs=DEFAULT_ROOTFS, frames=1):
    """``qemu-arm-static -L <rootfs> <codeselect> --snapshot <ppm> ...``:
    ONE menu frame as the machine would show it - the conf, the media,
    highlight N, the animation at frame N, the countdown as if just started,
    no input, no audio, no choice file - then exit.

    ``frames`` > 1 asks for a WHOLE RUN out of that one load: *ppm* is then
    a :func:`frame_pattern` and the selector writes K files, starting at
    *frame* and wrapping at the animation's own length.  K == 1 is left
    alone - no ``--frames`` at all - because that is the byte-for-byte
    single-frame command line, and the one the selector treats the
    ``--snapshot`` value as a plain file NAME for."""
    args = ["qemu-arm-static", "-L", rootfs, binary,
            "--snapshot", wsl(ppm), "--conf", wsl(conf),
            "--media", wsl(media_dir),
            "--highlight", str(int(highlight)),
            "--anim-frame", str(int(frame))]
    if int(frames) > 1:
        args += ["--frames", str(int(frames))]
    return args + ["--input", "none"]


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


#: The selector's own line for every PPM it wrote (``sel_say``, so stdout):
#: ``snapshot: <path> 1360x768, highlight 1 (TMNT 1987) from --highlight,
#: frame 2 of 4, timeout 15 s, invert 0, font …``.  The path is taken up to
#: the ``WxH`` that follows it, because an output path may hold spaces; the
#: frame is anchored on the ``, timeout`` after it, because a menu TITLE
#: sits in the middle of the same line and is somebody's typing.
_SNAP_RE = re.compile(
    r"snapshot: (.+?) \d+x\d+, highlight \d+ .*?, "
    r"frame (\d+) of (\d+), timeout ")


def parse_snapshot_frames(text):
    """``[(path, frame, total), ...]`` - every PPM a snapshot run says it
    wrote, in the order it wrote them; *total* is that image's own frame
    count (0 when it has no animation).

    A ``--frames K`` run decides for ITSELF which frames it writes: it
    starts at ``--anim-frame``, wraps at the animation's length and trims K
    to it.  So the run is read back rather than predicted here - the caller
    knows the pattern, the selector knows what it filled into it."""
    out = []
    for line in (text or "").splitlines():
        m = _SNAP_RE.search(line)
        if m:
            out.append((m.group(1), int(m.group(2)), int(m.group(3))))
    return out


def write_preview_conf(form):
    """The images.conf the preview is drawn from, as text: the form's
    titles, subtitles, media names, default, countdown and theme.  The
    device tokens are placeholders - a picture boots nothing."""
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
    lines += theme_conf_lines(form)
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
                      rootfs=DEFAULT_ROOTFS, cwd=None, frames=1):
    """One snapshot step.  A run of frames is ONE step and is labelled
    :data:`ANIM_LABEL` - what a failure of it is named after, and what the
    finished step's own output is read back through."""
    label = (ANIM_LABEL if int(frames) > 1 else "frame %d" % int(frame))
    return [(label,
             wsl_command(preview_snapshot_args(binary, conf, media_dir, ppm,
                                               highlight, frame, rootfs,
                                               frames),
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
            "can be replaced in Edit image… but not re-made from what made "
            "it.")
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
    theme, colors = theme_from_card(info.get("theme"), info.get("colors"))
    form = MultibootForm(
        images=rows, out=card, sound_move=move, sound_confirm=confirm,
        volume=_int_of("volume", 50), timeout=_int_of("timeout", 15),
        default=_int_of("default", 0), bypass=ticked,
        theme=theme, colors=colors,
        media_dir=media_dir if (media_dir and os.path.isfile(
            os.path.join(media_dir, "media.json"))) else "",
        selector_dir=selector_dir or DEFAULT_SELECTOR_DIR)
    return form, warnings


#: The menu fields an inject rewrites, in the order the tab names them.
#: Everything NOT here is the image list, and that needs a full build.
MENU_FIELD_ORDER = ("title", "subtitle", "art", "animation", "music",
                    "move sound", "confirm sound", "volume", "countdown",
                    "default", "bypass", "theme")

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
    if theme_args(before) != theme_args(after):
        changed.add("theme")
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
    write, or why only a rebuild can.

    ONE BRANCH of :func:`card_path_state` rather than a second opinion: the
    row's verb and the sentence under it are derived from the same call, so
    they cannot come to disagree about which card is being edited."""
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
# what the card path is pointing at
# ---------------------------------------------------------------------------

#: The two labels the row's one verb ever wears.  No ellipsis on either:
#: that is the signal it no longer asks a question - it acts on the path
#: already in the box.


def path_root(path):
    """The drive or share *path* hangs off - what a person plugs in.

    ``D:/Pinball/x.raw`` -> ``D:\\``, ``//server/share/x`` ->
    ``//server/share``.  It is what an 'it is not there' sentence has to
    name: the file is missing because the whole volume is."""
    p = (path or "").strip().strip('"')
    if not p:
        return ""
    drive, _rest = os.path.splitdrive(os.path.abspath(p))
    if len(drive) == 2 and drive[1] == ":":
        return drive + os.sep
    return drive or os.sep


#: What Windows says when the NAME is the problem rather than the drive:
#: ERROR_INVALID_NAME (a ``? * | < > "`` in it), ERROR_BAD_PATHNAME and
#: ERROR_FILENAME_EXCED_RANGE (past MAX_PATH).  None of them is an
#: unplugged drive, and all three arrive as a plain ``OSError``.
_BAD_NAME_WINERR = (123, 161, 206)


def probe_card_path(path, loaded=""):
    """What a STAT says about a card path:
    ``{"kind", "parent", "root", "loaded"}`` - kind being ``missing`` |
    ``file`` | ``dir`` | ``badname`` | ``unreachable``, *parent* whether the
    folder it would be written into is there, *root* its volume, and
    *loaded* whether it is the same file as *loaded* once the links are
    resolved.

    THE LINK RESOLUTION IS THE REASON *loaded* IS ASKED FOR HERE.  Every
    GATE compares with :func:`_norm`, which resolves - and D:\\Pinball\\images
    is a junction on the rig this is written for - while the sentence under
    the row compares with :func:`_plain`, which must not touch the disk on
    the Tk thread.  Two spellings of one card therefore disagreed: the row
    said the path had strayed and greyed Apply, while ``_build_card``'s own
    ``_norm`` saw the loaded card and refused the build, leaving neither
    writing button usable.  So the resolving comparison is made HERE, on
    the worker that is already stat'ing the same file, and handed back for
    the sentence to use.

    IT STATS, AND IT STOPS.  There is no card-shape sniff here and there
    must not be one: the only thing that can tell a multi-boot card from a
    stock single-image card is ``images.conf`` inside the card's ext4, and
    only the tool under WSL can read that - a sector-0 guess would be a
    second copy of layout knowledge in the one module whose docstring
    forbids exactly that, and it would be wrong.  What the tab says about a
    file that exists is therefore only what a stat can support: something is
    there, one button reads it and the other would write over it.  When the
    read then fails, the TOOL's own refusal is what reaches the tab, and it
    is better than anything this app could invent.

    Nothing here opens the file, creates a directory, writes, or runs WSL.
    It is called on a WORKER thread - every one of these stats can block for
    tens of seconds on a dead mapped drive or a sleeping share."""
    path = (path or "").strip().strip('"')
    facts = {"kind": "unknown", "parent": False, "root": path_root(path),
             "loaded": False}
    if not path:
        return facts
    try:
        st = os.stat(path)
    except ValueError:
        # A path Python will not even hand to the OS (an embedded NUL).  It
        # is a NAME problem, and it is caught because an exception here kills
        # the worker thread and leaves the row saying 'Looking at…' for ever.
        facts["kind"] = "badname"
    except OSError as exc:
        # A path that is simply not there yet is the ORDINARY case (it is
        # where a build would write); anything else - a share that is down,
        # a letter with no mapping behind it, a permission wall - is the
        # tab's business to say out loud, because no button can help.
        if isinstance(exc, FileNotFoundError):
            facts["kind"] = "missing"
        elif (getattr(exc, "winerror", None) in _BAD_NAME_WINERR
                or exc.errno in (errno.EINVAL, errno.ENAMETOOLONG)):
            # ...but a name the file system cannot spell is neither of those,
            # and it is the one a person is most likely to type: Windows
            # raises the same class of OSError for a ``?`` in a file name as
            # for a dead share, and calling it 'unreachable' told David to
            # plug in a drive that was plainly sitting there.
            facts["kind"] = "badname"
        else:
            facts["kind"] = "unreachable"
    else:
        facts["kind"] = "dir" if stat.S_ISDIR(st.st_mode) else "file"
    if loaded and facts["kind"] != "badname":
        try:
            facts["loaded"] = _norm(path) == _norm(loaded)
        except (OSError, ValueError):                    # pragma: no cover
            facts["loaded"] = False
    if facts["kind"] == "missing":
        parent = os.path.dirname(os.path.abspath(path))
        try:
            facts["parent"] = os.path.isdir(parent)
        except OSError:                                 # pragma: no cover
            facts["parent"] = False
        # Windows spells "the drive letter has no mapping" as a plain
        # ENOENT, the same as a file that is not there - so a missing path
        # whose own ROOT is missing too is the unplugged case.
        root = facts["root"]
        if root:
            try:
                if not os.path.isdir(root):
                    facts["kind"] = "unreachable"
            except OSError:                             # pragma: no cover
                facts["kind"] = "unreachable"
    return facts


#: What the tab says with the box empty.  Long, because it is the first
#: thing a new tab has to teach now that the row has no second button.
EMPTY_PATH_TEXT = ("No card yet. Add the images below - the path fills "
                   "itself in from the first one - or type where the card "
                   "should be written.")


def card_path_state(field, facts, rows=(), loaded_card="", menu=(),
                    rebuild=()):
    """What the card path is pointing at, in one sentence:
    ``(kind, sentence, tone, can_read)`` - ``can_read`` being whether there
    is a card at this path that reading would make sense of.  It used to
    carry the WORD a verb button would wear as well; that button is gone
    (David: "shouldn't we have just a browse and a new button?") and the
    decision outlived it, because <Return> in the path box still has to
    know, and the sentence beside the box and the key that acts on it must
    never disagree about whether there is anything there to read.

    PURE, and deliberately so: every word the row can say is decided here,
    with no Tk and no disk, from the box's text, the facts a
    :func:`probe_card_path` came back with, the image list and the loaded
    card.  *tone* is a THEMES key (``gray`` / ``fg`` / ``error``).

    The order matters.  The two checks that need no disk at all come first,
    because they are refusals :func:`validate_form` already makes and a
    probe answer must not talk over them; then the loaded card, which
    outranks the probe absolutely (a load is a fact, a stat is a guess about
    the same file); and only then what is at the path.

    THIS IS A DESCRIBER, NOT A GATE.  ``validate_form``,
    ``rebuild_blockers`` and the overwrite confirmation are still the ones
    that decide anything, and they run at press time on the real
    :func:`_norm`; this says early, in words, what they would say then."""
    field = (field or "").strip().strip('"')
    name = os.path.basename(field) or field

    def strayed():
        # IT NAMES NO CONTROL.  This used to end in 'More ▾ ▸ Back to the
        # card being edited', and that menu is gone - a sentence that sends
        # someone looking for a button which is not there is worse than one
        # that says only what is true.  What IS true is that nothing was
        # thrown away and the path is the way back, which is also the only
        # instruction that keeps working however the row is arranged.
        n = len(menu or ()) + len(rebuild or ())
        card = os.path.basename(loaded_card) or loaded_card
        if n:
            why = ("The path no longer names %s, the card you are editing "
                   "(%d unsaved change%s)" % (card, n, "" if n == 1 else "s"))
        else:
            why = ("The path no longer names %s, the card you were editing"
                   % card)
        return why + " — nothing was lost; type that path back to go on "\
                     "editing it."

    if not field:
        if loaded_card:
            return ("strayed", strayed(), "fg", False)
        return ("empty", EMPTY_PATH_TEXT, "gray", False)
    if under_library(field, resolve=False):
        return ("library",
                "That path is in the card library, which nothing here may "
                "write into — copy it out first.", "error", False)
    here = _plain(field)
    for i, row in enumerate(rows or ()):
        if here and _plain(getattr(row, "path", "")) == here:
            return ("is_image",
                    "That file is image %d in the list below — the card "
                    "must be written somewhere else." % i,
                    "error", False)
    # TWO SPELLINGS OF ONE CARD ARE ONE CARD.  The text match answers at
    # once and costs no disk, which is what a per-keystroke sentence needs;
    # the probe's ``loaded`` is the same question asked with the links
    # resolved, on the worker, and it arrives a typing pause later - so a
    # junction spelling of the loaded card lands in editing mode too instead
    # of leaving both writing buttons refusing (see :func:`probe_card_path`).
    if loaded_card and (_plain(loaded_card) == here
                        or (facts or {}).get("loaded")):
        return ("loaded", edit_status_text(loaded_card, menu, rebuild),
                "error" if rebuild else "fg", True)

    kind = (facts or {}).get("kind") or "unknown"
    if kind == "badname":
        state = ("badname",
                 "That is not a name a card can be written to — take the "
                 "? * | < > \" out of it, or shorten the path.",
                 "error", False)
    elif kind == "unreachable":
        sentence = ("%s is not there right now — plug the drive in, or pick "
                    "another folder." % ((facts or {}).get("root") or name))
        state = ("unreachable", sentence, "error", False)
    elif kind == "looking":
        state = ("looking", "Looking at %s…" % name, "gray", False)
    elif kind == "dir":
        state = ("dir", "That path is a folder, not a card.", "error", False)
    elif kind == "file":
        state = ("file",
                 "%s is on disk — Load card reads it into the form; Build & "
                 "verify would write over it." % name, "fg", True)
    elif kind == "missing":
        if (facts or {}).get("parent"):
            sentence = "Build & verify will write a new card at %s." % name
        else:
            folder = os.path.basename(
                os.path.dirname(os.path.abspath(field))) or "the folder"
            sentence = ("Build & verify will write a new card at %s, "
                        "creating %s." % (name, folder))
        state = ("missing", sentence, "gray", False)
    else:
        # NOTHING HAS BEEN ASKED YET (the probe is off, or it has not come
        # back).  Saying nothing is the honest answer, and the verb stays
        # live: pressing it asks the tool, whose refusal is better than a
        # guess this app would have to make to grey the button.
        state = ("unknown", "", "gray", True)
    if loaded_card:
        # The box has been typed away from the card in the form.  NOTHING IS
        # THROWN AWAY by that (see MultibootPanel._update_edit_status) - only
        # what the tab claims changes - so the sentence is about the way
        # back, while ``can_read`` still describes the path now in the box:
        # straying does not stop <Return> reading whatever it now names.
        return ("strayed", strayed(), "fg", state[3])
    return state


# ---------------------------------------------------------------------------
# the tab's saved state
# ---------------------------------------------------------------------------

#: The version stamped into :meth:`MultibootPanel.state`'s document.  A
#: newer app may add fields; every reader here IGNORES what it does not
#: know rather than refusing the document, so an older app opening a
#: project a newer one wrote comes back with the fields it understands
#: instead of an empty tab.
STATE_VERSION = 1

#: A row's fields that hold a PATH when they are not one of the words -
#: the ones a restore has to run resolve_mapped_drive over.  ``art_video``
#: is always a path when it is anything.
_STATE_ROW_PATHS = ("art", "anim", "music", "confirm")


def rows_from_state(images, resolve=None):
    """A saved image list back as :class:`ImageRow`\\ s.

    *resolve* is applied to every value that is a PATH - the source .raw and
    the media fields that are not one of the words - because a ``W:\\...``
    saved in an ordinary session stops resolving under an elevated relaunch
    (core.admin.resolve_mapped_drive, the same treatment every other
    restored path in this app gets).  ``auto@<index>`` is left alone: it
    reads as a path to :func:`is_file_choice` and is not one.

    Unknown keys are dropped and a malformed entry is skipped rather than
    raising - a half-written anchor on a NAS must cost the tab its state,
    never the startup."""
    resolve = resolve or (lambda p: p)
    out = []
    for entry in images or ():
        if not isinstance(entry, dict):
            continue
        kw = {}
        for f in dc_fields(ImageRow):
            if f.name not in entry:
                continue
            val = entry[f.name]
            kw[f.name] = bool(val) if isinstance(f.default, bool) \
                else str("" if val is None else val)
        kw.setdefault("path", "")
        try:
            row = ImageRow(**kw)
        except TypeError:                               # pragma: no cover
            continue
        if row.path:
            row.path = resolve(row.path)
        if row.art_video.strip():
            row.art_video = resolve(row.art_video)
        for name in _STATE_ROW_PATHS:
            val = getattr(row, name)
            if is_file_choice(val) and not _AUTO_IDX_RE.match(val.strip()):
                setattr(row, name, resolve(val))
        out.append(row)
    return out[:MAX_IMAGES]


def menu_from_state(menu):
    """A saved menu block, sanitised: the two sound specs as strings, the
    three numbers as ints, the bypass as a bool.  Anything missing or
    unreadable keeps the tab's own default rather than raising."""
    menu = menu if isinstance(menu, dict) else {}

    def _as_int(key, default):
        try:
            return int(menu[key])
        except (KeyError, TypeError, ValueError):
            return default
    theme = str(menu.get("theme") or DEFAULT_THEME).strip().lower()
    if theme != CUSTOM_THEME and theme not in theme_names():
        theme = DEFAULT_THEME
    return {"move": str(menu.get("move") or "auto"),
            "confirm": str(menu.get("confirm") or "auto"),
            "volume": max(0, min(100, _as_int("volume", 50))),
            "timeout": max(0, _as_int("timeout", 15)),
            "default": max(0, _as_int("default", 0)),
            "bypass": bool(menu.get("bypass", True)),
            "theme": theme,
            "colors": clean_colors(menu.get("colors"))}


# ---------------------------------------------------------------------------
# the size plan
# ---------------------------------------------------------------------------

_FITS_RE = re.compile(
    r"fits Stern\s+(\d+G)\s+image size\s+\d+:\s+(YES|NO)\s*\(spare\s+(-?\d+)\)")
_TOTAL_RE = re.compile(r"^image:\s+\d+\s+sectors\s+=\s+(\d+)\s+bytes")

#: A row of the tool's own VERSION table:
#:     idx device                 title                    version   read from
#: The title is free text, so the version is found by SHAPE (three numbers, or
#: the word the tool prints when it could not read one) rather than by
#: counting columns.
_VERSION_ROW_RE = re.compile(
    r"^\s*(\d+)\s+\S+\s+.*?\s(\d+\.\d+\.\d+|UNKNOWN)(?:\s|$)")


def parse_plan(text):
    """What ``mkmulticard.py plan`` said: ``{"bytes": N or None, "fits":
    {"16G": (True, spare), ...}, "versions": {index: "1.59.0", ...}}``.

    THE VERSIONS ARE WHY THE CODE COLUMN CAN BE FILLED AT ALL for images you
    ADD.  A card you LOAD reports each image's game code version through
    inspect, but a card being assembled has never been read - and the tool
    reads the version off every .raw anyway, on the way to refusing a
    mismatched build, and prints it in a table.  Listening to that costs
    nothing and is the same number by the same route (David: "the code
    column is not being populated for me when i load in images")."""
    info = {"bytes": None, "fits": {}, "versions": {}}
    for line in (text or "").splitlines():
        m = _FITS_RE.search(line)
        if m:
            info["fits"][m.group(1)] = (m.group(2) == "YES", int(m.group(3)))
        m = _TOTAL_RE.match(line.strip())
        if m:
            info["bytes"] = int(m.group(1))
        m = _VERSION_ROW_RE.match(line)
        if m and not line.lstrip().startswith("NOTE"):
            version = m.group(2)
            info["versions"][int(m.group(1))] = (
                "" if version == "UNKNOWN" else version)
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


def _clip_suffix(row):
    """`` @20s 2s 8fps`` when any clip field is set, else ''."""
    start, secs, fps = (_num(row.anim_start), _num(row.anim_seconds),
                        _num(row.anim_fps))
    if start or secs or fps:
        return " @%ss %ss %sfps" % (start or ANIM_DEFAULTS[0],
                                    secs or ANIM_DEFAULTS[1],
                                    fps or ANIM_DEFAULTS[2])
    return ""


def cell_anim(row):
    """The row's animation in full: the word or the clip's name, and the clip
    parameters when any is set (``auto @20s 2s 8fps``)."""
    v = _cell(row.anim)
    if row.anim_on_card:
        return v + " (on the card)"
    if v and v.lower() != "none":
        v += _clip_suffix(row)
    return v


#: THE ONE CHOICE the Edit image… dialog offers for what an image shows
#: (David, 2026-09-02: "we really only have two options here - art or
#: video").  Each kind is a pair of the art / animation specs the builders
#: already speak, so nothing under the dialog changed:
#:
#:   logo     the game's own logo, pulled off the .raw          auto / none
#:   picture  a picture file                                    file / none
#:   attract  the game's own attract clip while highlighted,
#:            its logo as the still                             auto / auto
#:   video    a video file: the clip while highlighted, and
#:            the frame it starts on as the still         file@T / file@T:S:F
#:   none     text only                                         none / none
#:   card     what a LOAD read off the card with no source recorded:
#:            kept as it is, drawn from the media dir, never re-made
#:            (see :func:`on_card_fields`)
#:
#: A still from file A with an animation from file B is not on the list
#: (nobody had made one).  A row that carries such a pair - an older form,
#: or a card - still reads honestly (:func:`cell_media`) and keeps it until
#: its media is edited, when the dialog's one choice replaces both halves.
MEDIA_KINDS = ("logo", "picture", "attract", "video", "none", "card")


def _has_anim(row):
    return (row.anim or "").strip().strip('"').lower() not in ("", "none")


def media_kind(row):
    """Which of :data:`MEDIA_KINDS` a row's art + animation amount to.  A
    still taken off a video with no clip yet is 'video' too: it animates
    the moment it is edited, which is the one thing the flat list dropped."""
    if row.art_on_card or row.anim_on_card:
        return "card"
    art = (row.art or "").strip().strip('"')
    if _has_anim(row):
        anim = (row.anim or "").strip().strip('"').lower()
        return "attract" if anim == "auto" else "video"
    a = art.lower()
    if a == "video frame" or is_video(art):
        return "video"
    if a == "none":
        return "none"
    if a in ("", "auto"):
        return "logo"
    return "picture"


def media_file(row):
    """The file a 'picture' or 'video' row uses; '' for every other kind."""
    kind = media_kind(row)
    art = (row.art or "").strip().strip('"')
    if kind == "picture":
        return art
    if kind != "video":
        return ""
    anim = (row.anim or "").strip().strip('"')
    if anim and anim.lower() not in _WORDS:
        return anim
    if art.lower() == "video frame":
        return (row.art_video or "").strip().strip('"')
    return art


def set_media(row, kind, path="", start="", seconds="", fps=""):
    """The dialog's choice -> the row: only the fields :func:`art_spec` and
    :func:`anim_spec` read.  'card' writes nothing (the row keeps the
    card's own files and the flags that say so); a video is written to
    BOTH halves, its still the frame at *start*."""
    if kind == "card":
        return row
    if kind not in MEDIA_KINDS:
        raise ValueError("not a media kind: %r" % (kind,))
    row.art_on_card = row.anim_on_card = False
    row.art_video = row.art_time = ""
    row.anim_start = row.anim_seconds = row.anim_fps = ""
    path = (path or "").strip()
    if kind == "logo":
        row.art, row.anim = "auto", "none"
    elif kind == "none":
        row.art, row.anim = "none", "none"
    elif kind == "picture":
        row.art, row.anim = path, "none"
    else:
        row.anim_start = (start or "").strip()
        row.anim_seconds = (seconds or "").strip()
        row.anim_fps = (fps or "").strip()
        if kind == "attract":
            row.art, row.anim = "auto", "auto"
        else:
            row.art = row.anim = path
            row.art_time = row.anim_start
    return row


def _same_file(a, b):
    a, b = (a or "").strip().strip('"'), (b or "").strip().strip('"')
    return bool(a) and bool(b) and _norm(a) == _norm(b)


def _moving_word(row):
    """The animation half of :func:`cell_media`."""
    if row.anim_on_card:
        return cell_anim(row)
    anim = (row.anim or "").strip().strip('"')
    if anim.lower() == "auto":
        return "attract video" + _clip_suffix(row)
    return os.path.basename(anim) + _clip_suffix(row)


def cell_media(row):
    """The table's one Picture cell: what the image shows, in the dialog's
    own words - ``logo``, ``attract video @20s 2s 8fps``, ``intro.mp4 @3s
    3s 10fps``, ``logo.png``, ``none`` - and, when the still is not the one
    its animation implies (a pair an older form made, or a card carries),
    both halves: ``attract.mov @21s + attract video @20s 2s 8fps``."""
    kind = media_kind(row)
    if kind == "logo":
        return "logo"
    if kind == "none":
        return "none"
    art = (row.art or "").strip().strip('"')
    if kind == "picture":
        return os.path.basename(art)
    if not row.art_on_card and art.lower() in ("", "auto"):
        still = "logo"
    else:
        still = cell_art(row)
    if not _has_anim(row):
        return still                    # a still off a video, no clip yet
    moving = _moving_word(row)
    if kind == "attract":
        implied = still == "logo"
    elif kind == "video":
        video = media_file(row)
        source = row.art_video if art.lower() == "video frame" else art
        implied = _same_file(source, video) and \
            _num(row.art_time, "0") == _num(row.anim_start, "0")
    else:
        implied = False
    return moving if implied else still + " + " + moving


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
            "bypass %s  ·  theme %s" % (
                sound(form.sound_move), sound(form.sound_confirm),
                int(form.volume),
                "wait for START" if int(form.timeout) == 0
                else "%d s countdown" % int(form.timeout),
                int(form.default), "on" if form.bypass else "off",
                (form.theme or "").strip().lower() or DEFAULT_THEME))


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
    """'Edit image…': one image's menu text, what it shows, and its sounds.

    WHAT IT SHOWS IS ONE FLAT CHOICE (David, 2026-09-02: "the modality here
    is poor. i have to first select 'art: video' to be able to interact
    with the video frame options. it needs to be a 'radio button' type
    choice... why do we have a separate animation section?"): the game's
    own logo, a picture file, the game's own attract clip, a video file, or
    nothing - every option in view, each one's fields live only while it is
    the choice, and no box that quietly unlocks a row beneath it.  A video
    is the animation AND the still (the frame it starts on shows while the
    image is not highlighted), so the Animation section had nothing left
    to say and is gone.  A row a load read off a card with no source
    recorded gets a sixth option, the card's own files, which is where it
    starts (see MEDIA_KINDS)."""

    #: The choices, in the order they are offered: ``(kind, label)``.  The
    #: two stills, then the two videos - so the clip fields sit under the
    #: pair they serve.
    KINDS = (("logo", "The game's own logo"),
             ("picture", "A picture file"),
             ("attract", "The game's own attract video"),
             ("video", "A video file"),
             ("none", "Nothing - text only"))

    #: What the two file rows browse for.
    FILETYPES = {"picture": [("Pictures", "*.png *.jpg *.jpeg")],
                 "video": [("Videos", "*.mp4 *.mov *.mkv *.avi *.gif")]}

    #: What a video shows, STATED rather than offered as controls (David:
    #: "remove the 'start', 'Length' and 'FPS' controls... just state [the
    #: limits]").  It loops a short slice from the start AT THE VIDEO'S OWN
    #: FRAME RATE (David: "10fps sucks... make it the original fps"), cut to
    #: about a second so it stays smooth within the menu's frame budget. Any
    #: common video works - it is re-encoded - so there is no codec to get
    #: right either.
    CLIP_NOTE = ("Shown as a short loop from the start, at the video's own "
                 "frame rate (about a second, kept smooth). Any common video "
                 "works - it is re-encoded.")

    def __init__(self, panel, index, row):
        _Modal.__init__(
            self, panel._parent,
            "Edit image %d — %s" % (index, os.path.basename(
                (row.path or "").strip()) or row.device or "no source"),
            panel._theme_fn, on_ok=panel._image_editor_ok,
            on_cancel=panel._image_editor_cancel)
        self._panel = panel
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

        box = ttk.LabelFrame(b, text="Picture")
        box.pack(fill=tk.X, pady=(12, 0))
        g = ttk.Frame(box)
        g.pack(fill=tk.X, padx=8, pady=6)
        panel._media_entries = {}
        panel._clip_widgets = []
        r = 0
        for kind, label in self.KINDS:
            ttk.Radiobutton(g, text=label, value=kind,
                            variable=panel._ed_media).grid(
                row=r, column=0, sticky=tk.W, pady=3, padx=(0, 10))
            if kind in self.FILETYPES:
                var = panel._ed_picture if kind == "picture" \
                    else panel._ed_video
                entry = ttk.Entry(g, textvariable=var, width=26)
                entry.grid(row=r, column=1, sticky=tk.EW, pady=3)
                panel._media_entries[kind] = entry
                ttk.Button(g, text="Browse…", width=9,
                           command=lambda k=kind: self._browse(k)).grid(
                    row=r, column=2, sticky=tk.W, padx=(4, 0), pady=3)
            r += 1
            if kind == "video":
                # NO Start / Length / FPS CONTROLS (David: "remove the
                # 'start', 'Length' and 'FPS' controls here since they are
                # misleading. We obviously have limits on what we show here,
                # so just state them instead").  A boot-menu clip is a short
                # loop drawn frame by frame, so it is a fixed slice at a
                # fixed rate - the numbers were a request the renderer then
                # clamped anyway - and it is STATED, not offered.  The
                # ``_ed_anim_*`` vars stay (a card loaded with an older
                # custom clip keeps its own values, and the render reads
                # them), they are simply not editable here any more.
                ttk.Label(g, foreground=th["gray"], wraplength=440,
                          justify=tk.LEFT, text=self.CLIP_NOTE).grid(
                    row=r, column=1, columnspan=2, sticky=tk.W, pady=(0, 3))
                r += 1
        names = [val for what, val in on_card_fields(row)
                 if what in ("art", "animation")]
        if names:
            ttk.Radiobutton(g, text="Keep the card's own " + ", ".join(names),
                            value="card", variable=panel._ed_media).grid(
                row=r, column=0, columnspan=3, sticky=tk.W, pady=3)
        g.columnconfigure(1, weight=1)
        ttk.Label(box, foreground=th["gray"], wraplength=500,
                  justify=tk.LEFT,
                  text="A video is the still too: the frame it starts on "
                       "shows while the image is not highlighted.").pack(
            anchor=tk.W, padx=8, pady=(0, 6))

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
                  text="The confirm sound is what plays when THIS image is "
                       "chosen; menu = the one the whole menu uses.").pack(
            anchor=tk.W, pady=(10, 0))

    def _browse(self, kind):
        """Browse… for a picture or a video.  Live whichever option is
        chosen: picking a file IS picking the option."""
        panel = self._panel
        var = panel._ed_picture if kind == "picture" else panel._ed_video
        _browse_into(var, self.FILETYPES[kind])
        if var.get().strip():
            panel._ed_media.set(kind)


class MenuSettingsDialog(_Modal):
    """'Menu settings…': the sounds, the volume, the LOOK (a theme, or your
    own colours), the countdown, the default image, the validator bypass and
    the selector build path - everything that belongs to the MENU rather
    than to one image."""

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

        look = ttk.LabelFrame(b, text="Look")
        look.pack(fill=tk.X, pady=(10, 0))
        g1 = ttk.Frame(look)
        g1.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(g1, text="Theme:", width=15).grid(row=0, column=0,
                                                    sticky=tk.W, pady=3)
        names = theme_names() + [CUSTOM_THEME]
        panel._theme_combo = ttk.Combobox(
            g1, textvariable=panel._theme_pick, state="readonly",
            values=[theme_title(n) for n in names], width=18)
        panel._theme_combo.grid(row=0, column=1, sticky=tk.W, pady=3)
        panel._theme_combo.bind("<<ComboboxSelected>>",
                                lambda _e: panel._theme_picked())
        panel._theme_tip = _Tooltip(panel._theme_combo, "", panel._theme_fn)
        # The grid: three columns of swatch / role / value, so fourteen
        # colours cost five rows and the dialog still fits a 768-high
        # desktop.  The SWATCH is the picker (a click opens the chooser):
        # a Pick… button per colour was a row of buttons and a taller
        # dialog than the desktop.
        roles = theme_roles()
        grid = ttk.Frame(g1)
        grid.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))
        rows = max(1, (len(roles) + 2) // 3)
        for i, role in enumerate(roles):
            r, c = i % rows, (i // rows) * 3
            sw = tk.Canvas(grid, width=16, height=16, highlightthickness=1,
                           highlightbackground=th["gray"], bd=0,
                           cursor="hand2")
            sw.grid(row=r, column=c, padx=(0 if c == 0 else 14, 4), pady=1)
            sw.bind("<Button-1>", lambda _e, k=role: panel._pick_color(k))
            ttk.Label(grid, text=theme_label(role) + ":").grid(
                row=r, column=c + 1, sticky=tk.W, pady=1)
            en = ttk.Entry(grid, textvariable=panel._color_vars[role],
                           width=7)
            en.grid(row=r, column=c + 2, sticky=tk.W, padx=(4, 0), pady=1)
            panel._color_swatches[role] = sw
            panel._color_entries[role] = en
        if roles:
            note = ("Make your own…: start from the theme shown, then "
                    "change any colour - type it (RRGGBB) or click its "
                    "swatch to pick one. The preview redraws as you go.")
        else:
            note = ("The themes file (%s) could not be read: the menu "
                    "keeps its default colours." % THEMES_JSON)
        ttk.Label(g1, foreground=th["gray"], wraplength=560,
                  justify=tk.LEFT, text=note).grid(
            row=2, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
        g1.columnconfigure(1, weight=1)
        panel._sync_theme_states()

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
        g2.columnconfigure(1, weight=1)
        # NO 'Bypass game validation' TICK (David: "why is this even an
        # option? it should always be on") - an unpatched image shows the
        # validation error on the machine, so the bypass is not a choice.
        # ``_bypass_var`` stays pinned True (see MultibootPanel.__init__) and
        # the machinery behind it - bypass_commands, bypass_state, Apply's
        # bypass step - is untouched; only the tick is gone.
        #
        # NO 'Advanced' SECTION EITHER (David: "people are likely to mess it
        # up").  The Selector build path is DEFAULT_SELECTOR_DIR, overridable
        # by the PAD_MULTIBOOT_SELECTOR env var (see MultibootPanel.__init__)
        # rather than an entry box nobody but the rig should touch.


class BuildFlashDialog(_Modal):
    """'Build / flash card…': the one modal that writes the card, and then -
    if you want - flashes it onto an SD card, in the shape the Write tab's
    own Build / flash dialog has (David: "the build and verify also can
    handle flashing... update that to be a modal... mimic what we did in
    the [Write] tab").

    It folds the two writing buttons the tab used to carry - 'Build &
    verify' and 'Apply to card' - into ONE tick whose words the tab
    decides: a loaded card that only needs its menu rewritten APPLIES (an
    inject, seconds); anything else BUILDS a fresh card (every image copied,
    minutes).  The person no longer has to know which of those two words
    their change is (David: "how does that differ?  consolidate").

    The flash tick is live only once there is a finished card to write -
    either one already on disk, or the one this dialog is about to build -
    and hands off to the app's own flash flow (the same one the Write tab
    uses), so the SD-card picker and the Administrator prompt have exactly
    one definition."""

    def __init__(self, panel):
        _Modal.__init__(self, panel._parent, "Build / flash card",
                        panel._theme_fn, on_ok=self._start,
                        on_cancel=panel._forget_build_flash)
        self._panel = panel
        plan = panel._write_plan()
        self._plan = plan
        b = self.body
        th = THEMES.get(panel._theme_fn()) or THEMES["dark"]

        self._write_var = tk.BooleanVar(value=bool(plan["default_write"]))
        self._flash_var = tk.BooleanVar(value=False)

        write = ttk.LabelFrame(b, text="Write the card")
        write.pack(fill=tk.X)
        gw = ttk.Frame(write)
        gw.pack(fill=tk.X, padx=8, pady=6)
        self._write_chk = ttk.Checkbutton(
            gw, text=plan["write_label"], variable=self._write_var,
            command=self._sync)
        self._write_chk.pack(anchor=tk.W)
        if not plan["can_write"]:
            self._write_chk.configure(state=tk.DISABLED)
        ttk.Label(gw, foreground=th["gray"], wraplength=460,
                  justify=tk.LEFT, text=plan["write_detail"]).pack(
            anchor=tk.W, padx=(20, 0), pady=(2, 0))

        flash = ttk.LabelFrame(b, text="Flash to an SD card")
        flash.pack(fill=tk.X, pady=(10, 0))
        gf = ttk.Frame(flash)
        gf.pack(fill=tk.X, padx=8, pady=6)
        self._flash_chk = ttk.Checkbutton(
            gf, text="Write the card onto an SD card", variable=self._flash_var,
            command=self._sync)
        self._flash_chk.pack(anchor=tk.W)
        ttk.Label(gf, foreground=th["gray"], wraplength=460, justify=tk.LEFT,
                  text="Flashing erases and replaces the whole SD card, and "
                       "needs Administrator (approved when the write starts). "
                       "Tick this with 'Write the card' above to build and "
                       "flash in one step.").pack(
            anchor=tk.W, padx=(20, 0), pady=(2, 0))
        if not (plan["can_write"] or plan["have_card"]):
            self._flash_chk.configure(state=tk.DISABLED)
            ttk.Label(gf, foreground=th["gray"], wraplength=460,
                      justify=tk.LEFT,
                      text="There is no finished card to flash yet - build "
                           "one first.").pack(anchor=tk.W, padx=(20, 0))

    def show(self):
        _Modal.show(self)
        # The green button says what it will do, and is dead until at least
        # one box is ticked.
        try:
            self.ok_btn.configure(text="Start")
        except tk.TclError:                             # pragma: no cover
            pass
        self._sync()
        return self

    def _sync(self, *_a):
        """The Start button is live only when there is something to do."""
        on = bool(self._write_var.get() or self._flash_var.get())
        try:
            self.ok_btn.configure(state=tk.NORMAL if on else tk.DISABLED)
        except tk.TclError:                             # pragma: no cover
            pass

    def _start(self):
        self._panel._do_build_flash(bool(self._write_var.get()),
                                    bool(self._flash_var.get()))


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
                   "the flipper buttons under it - and the left and right "
                   "arrow keys, once you have clicked the picture - move the "
                   "highlight the way the machine's do. Right-click it to "
                   "redraw now, to hear the highlighted image's confirm "
                   "sound, or to turn the automatic redraw off.")

    SELECT_TIP = ("START, on the picture: the highlighted image's confirm "
                  "sound, and the screen black for a moment while it plays "
                  "- what the machine does when you choose a card. It is "
                  "the only way to hear that sound, and see that beat, "
                  "before a card is written, and it plays whether or not "
                  "Sound is ticked, because pressing it is the asking.")
    FLIPPER_TIP = ("The machine's own flipper buttons: they move the "
                   "highlight one card and wrap round at the ends, exactly "
                   "as the flippers on the lockdown bar do - and they play "
                   "the menu's move sound when Sound is ticked. The left "
                   "and right arrow keys do the same while the picture has "
                   "the keyboard.")

    #: ...and this is where the long form of everything the 30 px control
    #: strip has no room for lives: the strip gets one line, this gets the
    #: paragraph (see :meth:`_one_line`).
    SOUND_TIP = ("Plays what the menu plays: the highlighted image's music "
                 "loop, and the move sound on every flipper press. The WAVs "
                 "are the prepared media's own, so this is what the card "
                 "will sound like, at the volume in Menu settings. It "
                 "starts OFF on purpose - nothing here opens a sound device "
                 "until you tick it - and untick it to give the device "
                 "back.\n\nThe preview renders pictures and music only while "
                 "this is off, so ticking it is also what asks for the move "
                 "and confirm sounds: the media set is prepared again, in "
                 "full, and the tick takes effect as soon as that run is "
                 "done.")

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
        #: THE SIZE CHECK RUNS ITSELF (see :meth:`_maybe_plan`).
        #: ``_plan_for`` is the image list ``_plan_text`` is about, so the
        #: sentence is blanked the moment the list stops being that one;
        #: ``_plan_job`` is its debounce.  ``PAD_MULTIBOOT_PLAN=0`` is its
        #: own off switch, and the panel flag under it is what the tests
        #: and the screenshot rig set: this is the one thing on the tab
        #: that starts a TOOL without being pressed.
        self._plan_for = None
        self._plan_job = None
        self._auto_plan = os.environ.get("PAD_MULTIBOOT_PLAN", "1") != "0" \
            and os.environ.get("PAD_MULTIBOOT_AUTO", "1") != "0"
        #: The two modals.  Their widgets are built on demand and bound to
        #: the panel's own variables, so the tab has one form whether a
        #: dialog is open or not (and the tests can drive either).
        self._image_dialog = None
        self._menu_dialog = None
        self._buildflash_dialog = None
        self._edit_backup = None        # the row a cancelled edit restores
        self._menu_backup = None
        #: Widgets that live only while a dialog is up: the Edit image…
        #: dialog's picture / video entries by kind, and its clip fields.
        self._media_entries = {}
        self._clip_widgets = ()
        self._default_spin = None
        self._bypass_chk = None
        self._theme_combo = None
        self._theme_tip = None
        self._color_entries = {}
        self._color_swatches = {}
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
        #: A restored card path that has not been read yet - :meth:`on_shown`
        #: reads it the first time the tab is opened.
        self._pending_read = False
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
        # THE VALIDATOR BYPASS IS ALWAYS ON (David: "it should always be
        # on") - an unpatched image fails the game's own validator on the
        # machine.  The var stays, so every diff, command line and test
        # still reads one truth, but it is pinned True: nothing in the UI
        # unticks it, and the loaders below (load_inspect / restore_state)
        # re-pin it after they run so a card saved unpatched, or an older
        # anchor with bypass:false, is brought up to patched.
        self._bypass_var = tk.BooleanVar(value=True)
        # THE SELECTOR BUILD PATH is no longer an entry box (David: the
        # Advanced section - "people are likely to mess it up").  It is the
        # default, overridable only by an env var for the rig.
        self._selector_var = tk.StringVar(
            value=os.environ.get("PAD_MULTIBOOT_SELECTOR")
            or DEFAULT_SELECTOR_DIR)
        #: The menu's colours: the theme's name, what the picker shows for
        #: it, and one var per colour role - the "make your own" grid, which
        #: also shows a chosen built-in's colours (and is what a custom
        #: theme starts from).
        self._theme_var = tk.StringVar(value=DEFAULT_THEME)
        self._theme_pick = tk.StringVar(value=theme_title(DEFAULT_THEME))
        self._theme_prev = DEFAULT_THEME
        self._color_vars = {
            role: tk.StringVar(
                value=(theme_colors(DEFAULT_THEME) or {}).get(role, ""))
            for role in theme_roles()}
        self._ed_title = tk.StringVar()
        self._ed_sub = tk.StringVar()
        #: What the image shows, as the Edit image… dialog asks it: one of
        #: MEDIA_KINDS, the file the 'picture' / 'video' kinds use (each
        #: keeps its own, so switching back and forth loses nothing), and
        #: the clip fields either video kind uses.
        self._ed_media = tk.StringVar(value="logo")
        self._ed_picture = tk.StringVar()
        self._ed_video = tk.StringVar()
        self._ed_music = tk.StringVar(value="none")
        self._ed_confirm = tk.StringVar(value="menu")
        self._ed_anim_start = tk.StringVar()
        self._ed_anim_seconds = tk.StringVar()
        self._ed_anim_fps = tk.StringVar()
        self._ed_media_vars = (self._ed_media, self._ed_picture,
                               self._ed_video, self._ed_anim_start,
                               self._ed_anim_seconds, self._ed_anim_fps)
        for var in (self._ed_title, self._ed_sub, self._ed_music,
                    self._ed_confirm):
            var.trace_add("write", lambda *_a: self._editor_changed())
        # ...and a write to what the image SHOWS is the one time the row's
        # art and animation are derived again from the dialog's choice.
        for var in self._ed_media_vars:
            var.trace_add("write",
                          lambda *_a: self._editor_changed(media=True))
        # ...and the menu's own fields, so the 'what would Apply write' line
        # follows every keystroke while a card is loaded.
        for var in (self._move_var, self._confirm_var, self._volume_var,
                    self._timeout_var, self._default_var, self._bypass_var):
            var.trace_add("write", lambda *_a: self._menu_changed())
        self._theme_var.trace_add("write", lambda *_a: self._theme_changed())
        for var in self._color_vars.values():
            var.trace_add("write", lambda *_a: self._color_changed())
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
        #: (MEDIA fingerprint, media DIR, sounds too?) that is prepared.
        #: The directory belongs in the key: it is derived from the output
        #: path, which media_fingerprint deliberately excludes - so retyping
        #: the output left the prepared media in the OLD directory and the
        #: new one empty, and the next build wrote a text-only card.  The
        #: third field is which HALF: the preview prepares --visual-only,
        #: and a set with no move or confirm sound in it is not the set a
        #: ticked Sound box is asking for.
        self._pv_ready = None
        #: Directories the preview made for itself, so a half-typed output
        #: path does not leave a preview/ and a media/ behind on disk.
        self._pv_made = set()
        self._pv_photo = None           # PhotoImage ref (must stay alive)
        #: THE DECODED FRAMES, by PPM path - what makes Play smooth.  Every
        #: step used to re-read the file and re-scale it; these are already
        #: scaled to the box on screen, so a second pass of an animation
        #: touches no disk at all.  Bounded (see PHOTO_CACHE_MAX), dropped
        #: whenever the box changes size (they are the wrong size then) and
        #: dropped for any frame the selector has just written again.
        self._pv_photos = {}
        self._pv_photo_order = []
        self._pv_shown = None           # (highlight, frame) on the canvas
        self._pv_src = None             # (ppm, highlight, frame, total) shown
        self._pv_caption = ""           # what the strip is saying, and
        self._pv_error = False          # ...whether it is saying it in red
        self._pv_logged = ""            # ...and the last line it sent to the Log
        self._pv_loading = False        # a programmatic write, not a typed one
        self._hl_touched = False        # Highlight typed by hand: stop following Default
        self._play_job = None
        self._play_fp = None
        self._play_hl = 0
        #: THE PREVIEW'S SOUND, AND IT STARTS OFF.  This app is used beside
        #: a machine that is running (David's own rule: bring things up
        #: muted), so nothing here opens an audio device, imports
        #: sounddevice or makes a noise until the Sound box has been
        #: ticked.  ``_audio`` is built on the first sound and kept - the
        #: player releases the device on stop() and takes it again on the
        #: next loop().
        self._sound_var = tk.BooleanVar(value=False)
        self._audio = None
        self._sound_job = None          # the status poll, only while it is on
        self._sound_watch_until = 0.0   # ...and a moment after a one-shot
        self._sound_status = ""         # the last status read off the player
        self._sound_said = None         # ...and the last note put on the caption
        #: (stat key, manifest) - media.json, re-read when the file moves.
        self._manifest_at = (None, {})
        #: (stat key, ms) - the rendered animation's own per-frame delay,
        #: re-read when that GIF moves.  Play asks per frame, so the answer
        #: is kept and only the stat is paid for.
        self._anim_ms_at = (None, None)
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
        #: THE SELECTION'S OWN LATER TURN.  Filling the table selects a row,
        #: and the per-selection work (the editor's highlight, the music, a
        #: cached frame or the 'not drawn yet' caption, a render) runs on
        #: the NEXT loop turn, not synchronously - which is what the
        #: ``ttk.Treeview`` this table replaced did through
        #: ``<<TreeviewSelect>>`` (it "arrives a turn LATER"), and what the
        #: restore below depends on: a refresh it is about to cancel must
        #: not leave a premature 'being drawn' caption on the strip.  This
        #: is that turn's job (see :meth:`_defer_selection`).
        self._select_job = None
        #: ...EXCEPT THE FIRST ONE AFTER A RESTORE.  A restore must start no
        #: tool at all (see :meth:`restore_state`), and cancelling the
        #: render it queued is not enough on its own: filling the table
        #: selects a row, and that later turn asks for another.  So the next
        #: automatic render is swallowed and the flag drops; the first thing
        #: the person then does draws.
        self._pv_idle = False
        #: THE PATH PROBE.  One stat of the box's text, on a worker, so the
        #: row can say what is at the path (see :func:`probe_card_path`).
        #: It is on its own debounce rather than the preview's, and it is
        #: NOT gated by ``_auto_preview``: the screenshot rig and most tests
        #: run with the preview off, and a row that then said nothing at
        #: all would be a dead row in every picture of this tab.
        #: ``PAD_MULTIBOOT_PROBE=0`` is its own off switch.
        #: ``_probe_for`` is the exact text ``_probe_facts`` describes, so
        #: an answer for older text is dropped rather than shown against a
        #: path it is not about (the discipline ``_pv_src`` already uses).
        #: The idle re-measure a height change asks for (see _remeasure).
        self._measure_job = None
        self._probe_job = None
        self._probe_busy = False
        self._probe_gen = 0
        self._probe_text = None         # the text a probe is out about
        self._probe_slow_job = None     # ...and the 'say we are looking' timer
        self._probe_slow = False
        self._probe_for = None
        self._probe_facts = {"kind": "unknown"}
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
        for var in (self._ed_title, self._ed_sub, self._ed_music,
                    self._ed_confirm) + self._ed_media_vars + (
                    self._move_var, self._confirm_var, self._volume_var,
                    self._timeout_var, self._default_var,
                    self._out_var, self._selector_var,
                    self._theme_var) + tuple(self._color_vars.values()):
            var.trace_add("write", lambda *_a: self.schedule_preview())
        # ...and the path box also moves the row's own verb and the sentence
        # under it, which is what makes the mode visible at all.
        self._out_var.trace_add("write", lambda *_a: self._out_changed())

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
        # ``_probe_busy`` belongs here with the other two: the probe hands
        # its answer back through the same queue, and a drain that stopped
        # rescheduling while one was out left the row silently never
        # updating.
        if (self._busy or self._pv_busy or self._probe_busy
                or not self._queue.empty()):
            try:
                self._drain_job = self._timer().after(self.DRAIN_MS,
                                                      self._drain)
            except tk.TclError:
                pass

    def _kick_drain(self):
        """Start the drain if it is not already running - for the callers
        that put work on a thread outside :meth:`_run_commands`."""
        if self._stopped or self._drain_job is not None:
            return
        try:
            self._drain_job = self._timer().after(self.DRAIN_MS, self._drain)
        except tk.TclError:                             # pragma: no cover
            pass

    def _on_destroy(self, event=None):
        if event is not None and str(event.widget) != str(self._parent):
            return
        self._stopped = True
        for attr in ("_drain_job", "_play_job", "_pv_debounce_job",
                     "_probe_job", "_probe_slow_job", "_measure_job",
                     "_sound_job", "_plan_job", "_select_job", "_black_job"):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self._timer().after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
                setattr(self, attr, None)
        # The tab is going: the sound device goes with it, and the player's
        # own thread is joined rather than left playing over the app's exit.
        self._stop_sound()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def build(self, frame):
        """THE SHAPE OF THE TAB - ONE COLUMN, top to bottom, in the order a
        person works:

        1. which card this is - the path, and the one verb that reads it,
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
        # THE STATUS SITS ABOVE THE TABLE, not at the foot of the tab
        # (David, looking at an empty one: "this text should be above the
        # table of images").  Both of its lines talk ABOUT the table - an
        # empty tab's two say "add the images below - the path fills itself
        # in from the first one", which was printed underneath the images it
        # was pointing at - and guidance that names a direction has to be on
        # the right side of the thing it names.
        self._build_status(outer, th)
        self._build_table(outer, th)
        self._build_actions(outer, th)
        frame.bind("<Destroy>", self._on_destroy, add="+")
        outer.bind("<Configure>", self._on_configure, add="+")
        # ...and the two moments a person comes BACK to this row expecting it
        # to have noticed something (see _refresh_facts): the tab being
        # selected again maps this frame, and clicking into the box is the
        # other half of "I have plugged the drive in now".
        outer.bind("<Map>", self._refresh_facts, add="+")
        self._out_entry.bind("<FocusIn>", self._refresh_facts, add="+")
        self._set_busy(False)
        self._sync_editor_states()
        self._update_menu_summary()
        self._refresh_tree()
        self._pv_placeholder()
        self._ok("Browse… to a card you already built and it is read into "
                 "this form, or press + in the table to add the first "
                 "image.")

    # -- 1. where the card comes from ----------------------------------

    #: What the path box itself says it is - and it has to carry what the
    #: two dead buttons' tooltips carried, because it is now the only thing
    #: in the row that names both of the tab's modes.
    PATH_TIP = ("The card this tab is pointing at. A path with a card "
                "already at it is one you can read: Load card fills every "
                "field from it - images, titles, subtitles, art, animation, "
                "music, sounds, volume, countdown, default and bypass - and "
                "Apply to card then writes your changes back into it in "
                "seconds. A path with nothing at it yet is where Build & "
                "verify will write a new card. Browse… does both: it takes "
                "a card that exists and a name that does not. Picking an "
                "existing card in Browse… reads it; a typed path never "
                "does, because a half-typed one names the wrong card.")

    VERB_TIP = ("Reads the card at the path above with the tool's own "
                "inspect: its table into the Log, its menu and images into "
                "the form, and the card's own media extracted into "
                "media-<stem> beside it. The card itself is never written.")

    #: No ellipsis: it opens no dialog and asks for no path.  The confirm
    #: it puts up when there is something to lose is a guard, not a
    #: question about what to do.
    NEW_TIP = ("Empties this tab: no images, the menu back at its defaults, "
               "the path cleared, and the card that was loaded no longer "
               "the one being edited. Nothing on disk is touched. It is a "
               "command of its own because clearing the path by hand must "
               "NOT throw the image list away - a path gets cleared to be "
               "retyped.")

    def _build_source(self, parent, th):
        """The first row, because reading a card you already built is the
        first thing anyone does here.

        ONE PATH AND ONE VERB.  The row used to carry two file pickers and
        a box - 'Load card…' asking for a card to read, 'New card…'
        clearing the form, and 'Card image' naming the output that a load
        then quietly turned into the card being edited - which is two ways
        to do one thing beside a field whose meaning changed with a hidden
        mode.  Now the box is the card's identity and the verb acts on
        whatever it holds.

        AND 'NEW CARD' IS BACK IN IT, from the menu that has gone (see
        :meth:`_build_actions`).  It belongs HERE and nowhere else: it is
        the one command that empties this box, and emptying the box by hand
        must NOT clear the image list (people clear a path to retype it),
        so the field needs the button that means what clearing it looks
        like.  It is not a second file picker - it opens no dialog and asks
        for no path - so the row it makes is one field and three verbs
        about that field: read it, pick it, start over.  Last in the group,
        beside the ?, because it is the rarest and the only one that throws
        anything away.

        The ENTRY IS PACKED LAST so it is the only thing in the row that
        can give way: this app unmaps the last widget of a row it cannot
        fit, without a word, and the one that may shrink has to be the one
        whose content is readable elsewhere."""
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        self._src_row = row
        # "Multi-boot card image", not "Card image": every other tab in this
        # app has a card image too, and this one is a particular kind - the
        # one carrying several games and a menu (David: "let's also label the
        # thing multiboot card image").
        ttk.Label(row, text="Multi-boot card image:").pack(
            side=tk.LEFT, padx=(0, 6))
        # The tab's own "what is this" lives here rather than in a
        # paragraph across the top: the picture below is the subject, and
        # the ? button carries the rest.
        self._about_badge = self._info_badge(row, self.ABOUT_TIP)
        self._about_badge.pack(side=tk.RIGHT, padx=(8, 0))
        self._new_btn = ttk.Button(row, text="New card", width=10,
                                   command=self._new_card_clicked)
        self._new_btn.pack(side=tk.RIGHT)
        self._new_tip = _Tooltip(self._new_btn, self.NEW_TIP, self._theme_fn)
        self._browse_btn = ttk.Button(row, text="Browse…", width=10,
                                      command=self._browse_card)
        self._browse_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self._out_entry = ttk.Entry(row, textvariable=self._out_var)
        self._out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True,
                             padx=(0, 6))
        # THE VERB BUTTON IS GONE (David: "shouldn't we have just a browse
        # and a new button? So, like, when we browse to an existing card, it
        # loads it").  He is right, and Browse… already did exactly that -
        # picking a card that exists in a file dialog IS choosing it, so a
        # second button asking "yes, really?" was the same redundancy that
        # started this row's rewrite, moved along by one.
        #
        # WHAT THE BUTTON WAS COVERING, and where each part went: a path you
        # TYPED or pasted is read by <Return> below, because pressing it is
        # as deliberate as picking a file; and a path RESTORED from a project
        # is read when the tab is opened (see :meth:`on_shown`), which is the
        # moment the answer is wanted and a moment the person is present for.
        # Neither is a keystroke: on the way to typing 'x.raw.bak' you pass
        # through 'x.raw', which exists.
        self._out_entry.bind("<Return>", self._path_committed)
        self._out_entry.bind("<KP_Enter>", self._path_committed)
        self._out_tip = _Tooltip(self._out_entry, self.PATH_TIP,
                                 self._theme_fn)

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
        amount of room; re-measure once the new requested sizes settle.

        The idle job is TRACKED, like every other ``after`` this panel
        holds: an untracked one fires after the toplevel is gone and Tcl
        writes ``invalid command name …_on_configure`` to stderr from
        inside a teardown nothing can catch."""
        self._cancel_remeasure()
        if self._stopped:
            return
        try:
            self._resize_fn()
            self._measure_job = self._timer().after_idle(self._on_configure)
        except tk.TclError:                             # pragma: no cover
            self._measure_job = None

    def _cancel_remeasure(self):
        job = getattr(self, "_measure_job", None)
        self._measure_job = None
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):           # pragma: no cover
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
        # THE MACHINE'S OWN CONTROL, in the machine's own words: the footer
        # drawn INSIDE the picture directly above these says "LEFT / RIGHT
        # FLIPPER: choose", and this is that.  A spinbox was here first,
        # and a number box is not what anyone presses at a pinball machine.
        self._flip_l = ttk.Button(strip, text="◀ Left flipper", width=14,
                                  command=self.flip_left)
        self._flip_l.pack(side=tk.LEFT)
        # BETWEEN THE FLIPPERS, because that is where it is on the machine:
        # the lockdown bar has the two flipper buttons at the sides and START
        # in the middle, and this row is that row.  Pressing it does what
        # pressing START does - the chosen card's confirm sound, then the
        # screen going black while the game loads - which is the only way to
        # hear that sound, and see that beat, before a card is written.
        self._select_btn = ttk.Button(strip, text="Select", width=8,
                                      command=self.press_select)
        self._select_btn.pack(side=tk.LEFT, padx=(4, 0))
        self._select_btn.tip = _Tooltip(self._select_btn, self.SELECT_TIP,
                                        self._theme_fn)
        self._flip_r = ttk.Button(strip, text="Right flipper ▶", width=15,
                                  command=self.flip_right)
        self._flip_r.pack(side=tk.LEFT, padx=(4, 0))
        for btn in (self._flip_l, self._flip_r):
            btn.tip = _Tooltip(btn, self.FLIPPER_TIP, self._theme_fn)
        ttk.Label(strip, text="Frame:").pack(side=tk.LEFT, padx=(10, 3))
        self._frame_spin = ttk.Spinbox(strip, from_=0, to=999, width=4,
                                       textvariable=self._frame_var,
                                       command=self._frame_changed)
        self._frame_spin.pack(side=tk.LEFT)
        self._play_chk = ttk.Checkbutton(strip, text="Play",
                                         variable=self._play_var,
                                         command=self._play_toggled)
        self._play_chk.pack(side=tk.LEFT, padx=(8, 0))
        self._sound_chk = ttk.Checkbutton(strip, text="Sound",
                                          variable=self._sound_var,
                                          command=self._sound_toggled)
        self._sound_chk.pack(side=tk.LEFT, padx=(8, 0))
        self._sound_chk.tip = _Tooltip(self._sound_chk, self.SOUND_TIP,
                                       self._theme_fn)
        self._pv_status = ttk.Label(strip, text="", width=1,
                                    justify=tk.LEFT, anchor=tk.W)
        self._pv_status.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                             padx=(12, 0))
        # ...and where a sentence too long for this ONE line goes.  The
        # strip cannot grow - it is 30 px with pack_propagate off - so what
        # will not fit is cut with an ellipsis (:meth:`_one_line`) and
        # hangs here whole.  Empty while the whole line is on show: a
        # tooltip that only repeats what is already readable is one nobody
        # hovers again.
        self._pv_status_tip = _Tooltip(self._pv_status, "", self._theme_fn)
        self._pv_tip = _Tooltip(self._pv_canvas, self.PREVIEW_TIP,
                                self._theme_fn)
        # ...AND THE ARROW KEYS ARE THE FLIPPERS TOO, bound on the picture
        # and on the two buttons and NOWHERE ELSE: the table walks its rows
        # with them and every text field walks its characters with them, so
        # a binding on the toplevel would take one of those away.
        self._pv_canvas.bind("<Button-1>", self._focus_preview, add="+")
        for widget in (self._pv_canvas, self._flip_l, self._flip_r):
            widget.bind("<Left>", self._key_flip_left)
            widget.bind("<Right>", self._key_flip_right)
        # NO RIGHT-CLICK MENU ON THE PICTURE (David: "in total, we don't
        # need a context menu above the preview at all now).  It had three
        # things and each has gone somewhere better: 'Redraw the preview
        # now' is not something anyone should have to ask for, so the
        # picture draws itself when the tab is opened (:meth:`on_shown`);
        # 'Update the preview automatically' was a setting about whether
        # the tab does its job; and 'Play this image's confirm sound' is
        # the Select button, where it reads as what it is - pressing START.
        #
        # ``_auto_preview`` outlives its menu entry: it is how the tests
        # and the screenshot rig keep a photograph from starting tools
        # (PAD_MULTIBOOT_AUTO=0), which is a developer's switch and was
        # never worth a line in a menu.
        self._sync_flippers()

    def _focus_preview(self, _event=None):
        """A click on the picture gives it the keyboard, so the arrow keys
        reach the flippers rather than whatever was focused before."""
        try:
            self._pv_canvas.focus_set()
        except tk.TclError:                             # pragma: no cover
            pass

    def _key_flip_left(self, _event=None):
        self.flip_left()
        return "break"

    def _key_flip_right(self, _event=None):
        self.flip_right()
        return "break"



    # -- 3. the images table --------------------------------------------

    #: The table's TEXT columns, left to right: ``(id, heading, minwidth,
    #: stretch)``.  The four actions live in their own icon column to the
    #: LEFT of these (David: "all of the icons should be on the far left
    #: side"), drawn by :class:`.image_table.ImageTable`, so they are not
    #: here.  The text columns that carry a name stretch and the short ones
    #: keep their width, so widening the window widens the titles.  ``code``
    #: is filled by whatever reports the game code version of an image;
    #: blank until then, and blank for a row that has none.  There is no
    #: ``#`` column - David: "we don't need the '#' column".
    #: The minwidths sum (with the four icon columns) to a natural table
    #: width a little OVER the ~904 px the Treeview this replaced asked for
    #: - deliberately, not by chance.  The tab is laid out at the table's
    #: natural width (that is how its tests and the fit sweep measure it),
    #: and the preview strip beside the picture takes its caption's
    #: wraplength from what is left of that width: a narrower table gives
    #: the strip less room and cuts a caption that used to fit.  So the
    #: table stays at least as wide as the one before it.
    TABLE_COLUMNS = (
        ("title", "Title", 160, True),
        ("sub", "Subtitle", 170, True),
        ("media", "Picture", 220, True),
        ("music", "Music", 95, True),
        ("sound", "Confirm", 90, False),
        ("code", "Code", 90, False),
    )

    #: The four per-row actions, in the order they sit at the left edge:
    #: ``(kind, tooltip)``.  A pencil (green), a bin (red) and two arrows
    #: (green), each a canvas drawing rather than a character - see
    #: :func:`.widgets.draw_pencil_icon` for why a glyph would not do.  The
    #: tips are INSTANT and FOLLOW THE POINTER (the tooltip's own doing);
    #: an arrow that cannot move (up on the first row, down on the last) is
    #: drawn gray and does nothing.
    ROW_ACTIONS = (
        ("edit", "Edit this image - its title, subtitle, picture and "
                 "sounds. A click on the row's text opens the same editor."),
        ("del", "Take this image off the card."),
        ("up", "Move this image one place earlier in the menu. The first "
               "image is the PRIMARY the machine falls back to."),
        ("down", "Move this image one place later in the menu."),
    )

    def _build_table(self, parent, th):
        """THE IMAGES TABLE.  Wide, so each image's settings are columns
        rather than something hidden in a dialog, and the row is where the
        row is worked on: a pencil, a bin and two arrows at its LEFT edge,
        acting on that row.

        A grid of real widgets (:class:`.image_table.ImageTable`), not a
        ``ttk.Treeview``: the actions have to be coloured one cell at a
        time, the row text has to underline under the pointer and open the
        editor on a single click, and a Treeview can do none of that (David,
        2026-09-02 - the whole of step 2 in the tab's handoff)."""
        from .image_table import ImageTable
        box = ttk.Frame(parent)
        box.pack(fill=tk.X, pady=(8, 0))
        self._table_box = box
        self._table = ImageTable(
            box, self.TABLE_COLUMNS, self.ROW_ACTIONS, self._theme_fn,
            on_select=self._on_table_select,
            on_activate=lambda i: self.edit_image(i),
            on_action=self._table_action,
            on_add=lambda: self._add_image(),
            on_context=self._popup_list_menu,
            add_text=self.ADD_ROW_TEXT, add_tip=self.LIST_TIP,
            visible_rows=LIST_MIN_ROWS, max_rows=LIST_MAX_ROWS)
        self._table.pack(fill=tk.X)
        self._build_list_menu(th)
        self._row_lbl = ttk.Label(parent, foreground=th["gray"], text="",
                                  anchor=tk.W)
        self._row_lbl.pack(fill=tk.X, pady=(3, 0))
        self._row_tip = _Tooltip(self._row_lbl, "", self._theme_fn)

    def _build_list_menu(self, th):
        """The same five commands as the row icons, on a right-click.

        The icons are the way in; this costs nothing, is where a hand
        trained on every other list looks, and is what a keyboard reaches
        (the menu key, and Enter on a row).  The table itself catches the
        right-click and the menu key and calls :meth:`_popup_list_menu`."""
        menu = tk.Menu(self._table, tearoff=0)
        for label, attr, needs_row in self.LIST_ACTIONS:
            if label is None:
                menu.add_separator()
                continue
            menu.add_command(label=label,
                             command=lambda a=attr: getattr(self, a)())
        self._list_menu = menu

    #: The right-click menu, in the order the icons are in.  ``needs_row``
    #: entries are greyed when the click missed every image row, so a
    #: right-click on the template row or on empty space offers Add… alone.
    LIST_ACTIONS = (("Add image…", "_add_image", False),
                    ("Edit image…", "edit_image", True),
                    ("Remove image", "_remove_image", True),
                    (None, None, False),
                    ("Move up", "_move_up", True),
                    ("Move down", "_move_down", True))

    def _popup_list_menu(self, row, x, y):
        """Pop the menu up at ``(x, y)``, over the row the table says the
        click or the menu key landed on (``None`` off any image row).

        The table has already selected that row before calling this, so the
        greying below only has to decide which commands a row-less opening
        offers (Add… alone)."""
        menu = getattr(self, "_list_menu", None)
        if menu is None:
            return None
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
        try:
            menu.tk_popup(int(x), int(y))
        finally:
            try:
                menu.grab_release()
            except tk.TclError:                         # pragma: no cover
                pass
        return "break"

    def _select_row(self, i):
        """Point the table at image *i*.

        The blue row here, the fields in the editor below it and the amber
        card in the picture are three views of ONE choice, so everything
        that moves that choice comes through here - the flippers included.
        Quiet when the table is not built yet (a panel under construction)."""
        table = getattr(self, "_table", None)
        if table is not None:
            table.select(i)

    def _table_action(self, i, kind):
        """One of a row's icons was clicked (or its context-menu twin):
        edit / remove / move.  The table has selected the row first, so the
        remove and the moves read it back through :meth:`_selected`."""
        if kind == "edit":
            self.edit_image(i)
        elif kind == "del":
            self._remove_image()
        elif kind == "up":
            self._move_image(-1)
        elif kind == "down":
            self._move_image(1)

    def _move_up(self):
        self._move_image(-1)

    def _move_down(self):
        self._move_image(1)

    # -- 4. the bottom bar, and the status ------------------------------

    def _build_actions(self, parent, th):
        """THE ONE ACTION BAR - with the source row at the top, the only
        place in the tab a button lives.  Menu settings… on the left with
        what it holds beside it, and on the right ONE green writing button
        and Run in emulator.  THREE ACTIONS AND NOTHING ELSE.

        'Build / flash card…' is the whole of the writing side now (David:
        "consolidate to as few buttons as possible... how does [Apply to
        card] differ [from Build & verify]?").  'Apply to card', 'Build &
        verify' and 'Flash to SD card…' were three buttons a person had to
        tell apart; they are one green button and a modal that decides
        Apply-vs-Build itself and offers the flash in the same place
        (:class:`BuildFlashDialog`), the shape the Write tab's own Build /
        flash dialog has.

        THE 'MORE ▾' MENU IS GONE, and every one of the six things in it
        with it (David, in dark mode: "the 'more' button looks awful ... it
        has two arrows and turns white and illegible. and i don't even
        understand most of these options").  The rendering was the ONLY
        ttk.Menubutton in the app - the dark theme styles no TMenubutton,
        so it fell through to ttk's default colours, and it drew its own
        indicator on top of the one in its label - but styling it would
        have kept six controls that had to justify themselves and could
        not:

        * Check size and Prepare media were work the tab can decide to do
          by itself, and asking for them is asking someone to know when
          they are stale (see :meth:`_maybe_plan` and :meth:`_sound_
          toggled`).
        * Start a new card is a real command and now sits beside the field
          it clears (see :meth:`_build_source`).
        * 'Back to the card being edited' was grey except in a state you
          reach by typing over the path, and typing the path back does the
          same thing - so the sentence in the status block says that
          instead.
        * 'Bypass an existing card…' duplicated what Apply to card already
          does with the Bypass box ticked, and does worse: Apply re-reads
          the card afterwards.  The ``mkmulticard bypass`` subcommand is
          untouched - it is what Apply calls.
        * 'Update the preview automatically' is a setting about the
          picture, and it is on the picture's own right-click menu.

        One row, and every widget in it has an expanding neighbour: a row
        this app overflows loses its last widget without a word."""
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(10, 0))
        self._action_row = row
        self._menu_btn = ttk.Button(row, text="Menu settings…", width=16,
                                    command=self.open_menu_settings)
        self._menu_btn.pack(side=tk.LEFT)
        self._emu_btn = ttk.Button(row, text="Run in emulator", width=16,
                                   command=self._run_emulator)
        self._emu_btn.pack(side=tk.RIGHT, padx=(0, 6))
        # ONE writing button, always green, opening the Build / flash modal
        # (David: "consolidate to as few buttons as possible... build and
        # verify also can handle flashing... mimic what we did in the [Write]
        # tab").  It replaces 'Apply to card', 'Build & verify' AND 'Flash to
        # SD card…': the dialog decides Apply-vs-Build for the person, and
        # can flash in the same step.
        self._buildflash_btn = ttk.Button(
            row, text="Build / flash card…", width=18,
            command=self._open_build_flash, style="Go.TButton")
        self._buildflash_btn.pack(side=tk.RIGHT, padx=(0, 6))
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
            self._buildflash_btn, self._emu_btn,
            self._menu_btn, self._browse_btn, self._new_btn]

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
            # Every frame in memory was scaled to the OLD box: keeping them
            # would draw a resized window at the size before it moved.
            self._drop_photos()
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
        # the padx between them: the right flipper (4,0), Frame: (10,3),
        # Play (8,0), Sound (8,0) and the status label's own (12,0)
        return used + 4 + 13 + 8 + 8 + 12

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
    _cell_media = staticmethod(cell_media)

    #: What the template row says.  Dim, with a green '+': an empty card
    #: shows only this, which is both the way in and the lesson.
    ADD_ROW_TEXT = "Add an image…"

    def _values(self, i, row):
        """ONE ROW OF THE TABLE, as a dict keyed by column id: the title
        (with what is wrong with its .raw when something is), the subtitle,
        what this image shows and its music, the sound that plays when it
        is chosen, and the game code version if anything has reported one.

        The settings are COLUMNS now rather than a phrase: the table has
        the whole width of the tab, and what an image is set to is worth
        more on screen than one word summarising all of it.  The actions
        are drawn by the table itself and are not in here."""
        return {
            "title": list_title(row, i),
            "sub": (row.subtitle or "").strip(),
            "media": cell_media(row),
            "music": _cell(row.music),
            "sound": self._confirm_cell(row),
            "code": (row.version or "").strip(),
        }

    def _refresh_tree(self, select=None):
        """Rebuild the table from ``self._rows`` and settle everything that
        reads off it SYNCHRONOUSLY - the editor, the row label, the flippers,
        the status and the menu summary - and ask for a redraw.

        ``set_rows`` sets the selection SILENTLY; the per-selection work
        that touches the PICTURE (the highlight, the music, a cached frame,
        the caption) runs on the next loop turn (:meth:`_defer_selection`),
        exactly as the old Treeview's ``<<TreeviewSelect>>`` did, so a
        rebuild that a caller is about to cancel (a restore) or that no one
        is watching (a non-interactive test) never leaves a premature
        'being drawn' caption on the strip."""
        table = getattr(self, "_table", None)
        if table is None:
            return
        values = [self._values(i, row) for i, row in enumerate(self._rows)]
        grew = table.count() != len(self._rows)
        prev = table.selected()
        try:
            table.set_rows(values, select=select)
        except tk.TclError:                             # pragma: no cover
            pass
        if grew:
            # The table has a different number of rows, so it is a
            # different height and the picture has a different amount of
            # room; re-measure once the new requested sizes have settled.
            self._remeasure()
        top = max(0, len(self._rows) - 1)
        if self._default_spin is not None:
            try:
                self._default_spin.configure(to=top)
            except tk.TclError:                         # pragma: no cover
                pass
        self._sync_flippers()
        self._load_editor()
        self._update_edit_status()
        self._update_menu_summary()
        self._update_row_label()
        self.schedule_preview()
        if table.selected() != prev:
            self._defer_selection()

    def _on_table_select(self, _i):
        """The table moved the selection by a click, a key or a flipper:
        take the same later turn a rebuild does, so every path into a new
        selection reaches the picture the same way and at the same time."""
        self._defer_selection()

    def _defer_selection(self):
        """Run :meth:`_apply_selection` on the next loop turn, once.

        This is the old ``<<TreeviewSelect>>``: it arrives a turn later, so
        a selection made by a rebuild that is then cancelled, or set with
        ``_pv_idle`` about to go up, does not draw or caption synchronously.
        Coalesced - a burst of selections is one turn's work."""
        self._cancel_selection()
        if self._stopped:
            return
        try:
            self._select_job = self._timer().after_idle(self._apply_selection)
        except tk.TclError:                             # pragma: no cover
            self._apply_selection()

    def _cancel_selection(self):
        job = getattr(self, "_select_job", None)
        self._select_job = None
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):           # pragma: no cover
                pass

    def _update_row_label(self):
        """The one dim line under the table.  It has two jobs and never
        more than one line: which .raw the selected image came from (the
        table has no room for a path, and it is the one fact a row cannot
        show), and - when nothing is selected - the quiet sentence that
        teaches the icons.

        The path is shortened to the WIDTH THE LINE HAS, not a fixed 90
        (David: the path "should span the whole width"): the middle is
        dropped only as far as the line's own pixels require, and the whole
        of it is always in the tooltip."""
        lbl = getattr(self, "_row_lbl", None)
        if lbl is None:
            return
        i = self._selected()
        full = _cell_image(self._rows[i]) if i is not None else ""
        try:
            lbl.configure(text=_shorten(full, self._row_label_chars())
                          if full else self.ROW_HINT)
            self._row_tip.text = full or self.LIST_TIP
        except tk.TclError:
            pass

    def _row_label_chars(self):
        """How many characters the row-path line can show, from the pixels
        it actually has - its own width, or the table's if it has not been
        laid out yet, in its own font.  Falls back wide so a line not on
        screen still shows a whole ordinary path."""
        lbl = getattr(self, "_row_lbl", None)
        if lbl is None:
            return 140
        try:
            px = lbl.winfo_width()
            if px <= 1:
                px = self._table.winfo_width()
        except (tk.TclError, AttributeError):           # pragma: no cover
            px = 0
        if px <= 1:
            return 140
        try:
            ch = max(1, tkfont.Font(font=lbl.cget("font")).measure("0"))
        except tk.TclError:                             # pragma: no cover
            return 140
        return max(40, int(px // ch))

    def _apply_selection(self):
        """The selection's consequences for the PICTURE, run a turn after
        the selection moved (see :meth:`_defer_selection`): load the row
        into the editor, name its .raw under the table, point the preview's
        highlight at it, follow it with the right music, and draw.

        The one place these live, whichever way the selection moved - a
        click or a key on the table, a flipper, or a rebuild.  Reads the
        CURRENT selection rather than a captured index, because the turn
        between the change and here is a turn in which it could move
        again."""
        self._select_job = None
        if self._stopped:
            return
        self._load_editor()
        self._update_row_label()
        i = self._selected()
        if i is not None:
            self._set_var(self._hl_var, i)
            # ...and the music follows the highlight however the highlight
            # moved: a programmatic write skips the 'typed' trace, so the
            # sound is asked for here rather than left to it.
            self._sound_follow()
            self._show_cached()
            self.schedule_preview()

    def _selected(self):
        table = getattr(self, "_table", None)
        if table is None:
            return None
        i = table.selected()
        return i if i is not None and 0 <= i < len(self._rows) else None

    def _load_editor(self):
        """Editor <- the selected row (guarded so the traces stay quiet)."""
        i = self._selected()
        self._loading = True
        try:
            row = self._rows[i] if i is not None else ImageRow("")
            kind, path = media_kind(row), media_file(row)
            self._ed_title.set(row.title)
            self._ed_sub.set(row.subtitle)
            self._ed_media.set(kind)
            self._ed_picture.set(path if kind == "picture" else "")
            self._ed_video.set(path if kind == "video" else "")
            self._ed_music.set(row.music)
            self._ed_confirm.set(row.confirm or "menu")
            # A still taken off a video with no clip yet (an older form)
            # keeps its second as the clip's start.
            self._ed_anim_start.set(row.anim_start or (
                row.art_time if kind == "video" else ""))
            self._ed_anim_seconds.set(row.anim_seconds)
            self._ed_anim_fps.set(row.anim_fps)
        finally:
            self._loading = False
        self._sync_editor_states()

    def _editor_changed(self, media=False):
        """The selected row <- the editor, on every keystroke.  *media*
        says the write was to one of the vars that decide what the image
        shows, which is the one time the row's art and animation are
        derived again from the dialog's choice: a title edit leaves a pair
        the choice cannot spell (see MEDIA_KINDS) exactly as it was."""
        if self._loading:
            return
        self._sync_editor_states()
        i = self._selected()
        if i is None:
            return
        row = self._rows[i]
        # A media field typed over is no longer the card's own file: the
        # value is a spec again, and the tools may render it.
        for attr, flag, var in (("music", "music_on_card", self._ed_music),
                                ("confirm", "confirm_on_card",
                                 self._ed_confirm)):
            if getattr(row, flag) and getattr(row, attr) != var.get():
                setattr(row, flag, False)
        row.title = self._ed_title.get()
        row.subtitle = self._ed_sub.get()
        row.music = self._ed_music.get()
        # "menu" is what the box says and "" is what the row keeps, so a row
        # that inherits compares equal however the dialog spelled it
        conf_v = self._ed_confirm.get()
        row.confirm = "" if conf_v.strip().lower() == "menu" else conf_v
        if media:
            self._apply_media(i, row)
        table = getattr(self, "_table", None)
        if table is not None:
            table.set_row(i, self._values(i, row))
        self._update_edit_status()
        self._update_row_label()

    def _apply_media(self, i, row):
        """Row *i*'s art and animation <- the dialog's one choice.  'card'
        puts back what the load read (the dialog's own backup of the row),
        so a choice tried and untried in one sitting costs nothing."""
        kind = self._ed_media.get().strip() or "logo"
        if kind == "card":
            if self._edit_backup is not None and self._edit_backup[0] == i:
                was = self._edit_backup[1]
                for name in ("art", "anim", "art_video", "art_time",
                             "anim_start", "anim_seconds", "anim_fps",
                             "art_on_card", "anim_on_card"):
                    setattr(row, name, getattr(was, name))
            return
        path = {"picture": self._ed_picture,
                "video": self._ed_video}.get(kind)
        set_media(row, kind, path.get() if path is not None else "",
                  self._ed_anim_start.get(), self._ed_anim_seconds.get(),
                  self._ed_anim_fps.get())

    def _sync_editor_states(self):
        """Each option's fields live only while it is the choice: the
        picture entry for 'picture', the video entry for 'video', the clip
        fields for either video.  (The Browse… buttons stay live: picking a
        file is picking the option.)"""
        kind = self._ed_media.get().strip()
        for name, w in getattr(self, "_media_entries", {}).items():
            try:
                w.configure(state=tk.NORMAL if kind == name else tk.DISABLED)
            except tk.TclError:
                pass
        for w in getattr(self, "_clip_widgets", ()):
            try:
                w.configure(state=tk.NORMAL if kind in ("attract", "video")
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
        """'New card', beside the path box it clears: back to an empty tab -
        no images, the menu at its defaults, editing mode left behind.
        Nothing on disk is touched; the card that was loaded is simply no
        longer the one being edited.

        It is a NAMED COMMAND and not something the path box does, because
        emptying the path must not throw the image list away: people clear a
        path to retype it, and there has to be exactly one way to start
        over."""
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
            self._theme_var.set(DEFAULT_THEME)
            self._seed_colors(theme_colors(DEFAULT_THEME) or {})
        finally:
            self._loading = False
        self._sync_theme_states()
        self._pv_cache.clear()
        self._pv_totals.clear()
        self._pv_shown = None
        self._pv_src = None
        self._pv_ready = None
        self._pv_photo = None
        self._pv_idle = False           # a press: the hold is a restore's
        self._drop_photos()
        self._stop_play(None)
        self._set_var(self._hl_var, 0)
        self._set_var(self._frame_var, 0)
        # There is no card any more, so there is nothing to be playing.
        self._sound_follow()
        self._update_edit_status()
        self._pv_placeholder()
        self._pv_say("")
        self._refresh_tree()
        self._ok("A new card: add the primary (stock) image and one more.")

    # ------------------------------------------------------------------
    # the card path: what is at it, and the one verb that acts on it
    # ------------------------------------------------------------------

    def _on_loaded_path(self):
        """Whether the path box still names the card the form was read from.

        THE ONE RULE of this row: editing mode is exactly "the file at that
        path has been read into this form", so everything that decides
        whether Apply may write asks this and not ``_loaded_card`` alone.
        Without it, ``Card image: Y`` on screen with Apply injecting into X
        was three keystrokes away."""
        if not self._loaded_card:
            return False
        field = self._out_var.get().strip().strip('"')
        return bool(field) and _norm(field) == _norm(self._loaded_card)

    def _out_changed(self):
        """The path box was typed in (or set): re-say what it points at, and
        ask a worker what is really there."""
        # A MEDIA DIR BELONGS TO A CARD, NOT TO THE TAB.  While a card is
        # LOADED the override is that card's own extract and straying the
        # path must not touch it (nothing is thrown away by straying).  With
        # no card loaded the only override there can be is one a restore
        # brought back, and it belongs to the card path that was saved with
        # it - so the moment the box names something else it is wrong, and
        # media_dir() would send a prepare into the old card's extract
        # directory with nothing on screen explaining why.
        if self._media_override and not self._loaded_card:
            field = self._out_var.get().strip().strip('"')
            if _plain(self._media_override) != _plain(loaded_media_dir(field)):
                self._media_override = ""
        self._schedule_probe()
        self._update_edit_status()

    def _facts_now(self, field):
        """What is known about *field* right now - the probe's answer for
        exactly this text, 'looking' once a probe has been out a whole
        second, and 'unknown' otherwise.

        Never the answer for OTHER text: a stale fact shown against a path
        it is not about is worse than no fact at all."""
        if self._probe_for is not None and self._probe_for == field:
            return self._probe_facts
        if self._probe_slow and self._probe_text == field:
            return {"kind": "looking"}
        return {"kind": "unknown"}

    def _schedule_probe(self, refresh=False):
        """Debounce the stat the same way the preview debounces its render:
        one probe per typing pause, not one per keystroke.

        *refresh* asks the same question about the SAME text again - see
        :meth:`_start_probe`, which otherwise trusts the answer it has."""
        if self._stopped or os.environ.get("PAD_MULTIBOOT_PROBE", "1") == "0":
            return
        job = self._probe_job
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):           # pragma: no cover
                pass
        try:
            self._probe_job = self._timer().after(
                PREVIEW_DEBOUNCE_MS, lambda: self._start_probe(refresh))
        except tk.TclError:                             # pragma: no cover
            self._probe_job = None

    def _refresh_facts(self, _event=None):
        """ASK AGAIN.  The stat is a fact with a shelf life and the row used
        to keep its first answer for ever: a card the build had just written
        went on reading 'Build & verify will write a new card' with the verb
        greyed, and a drive that was asleep when the path was typed stayed
        'not there right now' however long ago it was plugged back in - the
        only way out of either was to alter the text.  So it is re-asked at
        the three moments the answer can have changed under us: a run has
        finished, the tab has come back on screen, and the box has been
        clicked into.  Nothing is re-asked about an empty box."""
        if self._out_var.get().strip():
            self._schedule_probe(refresh=True)

    def _start_probe(self, refresh=False):
        """Ask a worker what is at the path.  ALL OF IT IS ON THE WORKER,
        including the stat: an arbitrary typed path can be a share that
        blocks ``os.stat`` for tens of seconds, and the app has already paid
        for freezing the Tk thread on exactly that.

        The answer is kept per text and not asked for twice - one keystroke
        must not cost one stat - so *refresh* is how the callers that KNOW
        the disk may have moved get a fresh one (:meth:`_refresh_facts`)."""
        self._probe_job = None
        if self._stopped:
            return
        text = self._out_var.get().strip().strip('"')
        if not refresh and self._probe_for == text and not self._probe_busy:
            return                      # already answered, for this text
        self._probe_gen += 1
        gen = self._probe_gen
        self._probe_text = text
        self._probe_busy = True
        self._probe_slow = False
        self._arm_slow_probe()
        # Resolved on the worker with the rest of it - see probe_card_path.
        loaded = self._loaded_card

        def work():
            facts = probe_card_path(text, loaded)
            self._ui(lambda: self._probe_done(text, facts, gen))
        threading.Thread(target=work, daemon=True).start()
        self._kick_drain()

    def _arm_slow_probe(self):
        """A probe that answers at once must not make the row flicker
        through 'Looking at…', so that word waits a whole second."""
        self._cancel_slow_probe()

        def slow():
            self._probe_slow_job = None
            if self._probe_busy:
                self._probe_slow = True
                self._update_edit_status()
        try:
            self._probe_slow_job = self._timer().after(1000, slow)
        except tk.TclError:                             # pragma: no cover
            self._probe_slow_job = None

    def _cancel_slow_probe(self):
        job = self._probe_slow_job
        self._probe_slow_job = None
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):           # pragma: no cover
                pass

    def _probe_done(self, path, facts, gen=None):
        """A probe answered.  THE PUBLIC SEAM: the tests hand it a facts
        dict and drive the whole row without a disk.

        *gen* is the probe's own sequence number; an answer for a run a
        later one has overtaken is dropped rather than shown."""
        if gen is not None:
            if gen != self._probe_gen:
                return
            self._probe_busy = False
            self._probe_slow = False
            self._cancel_slow_probe()
        self._probe_for = path
        self._probe_facts = dict(facts or {})
        self._update_edit_status()

    def _unsaved_changes(self):
        """How many changes the form has that the loaded card has not - the
        menu bucket and the rebuild bucket together.  Already computed on
        every keystroke by :meth:`_update_edit_status`; nothing new is
        kept."""
        if not self._loaded_card or self._loaded_form is None:
            return 0
        menu, rebuild = diff_forms(self._loaded_form, self.form())
        return len(menu) + len(rebuild)

    def _confirm_discard(self, target):
        """True to go ahead and read *target*: either nothing would be lost,
        or the person said so.

        Asked BEFORE the read starts, because a read that fails cannot lose
        anything - ``load_inspect`` is what replaces the form.  The two-
        button row used to make it obvious you were leaving; one field is
        less obvious, so it has to ask."""
        name = os.path.basename(target) or target
        n = self._unsaved_changes()
        if n:
            return messagebox.askyesno(
                "Discard your changes?",
                "You have %d unsaved change%s to %s. Reading %s replaces "
                "every field." % (n, "" if n == 1 else "s",
                                  os.path.basename(self._loaded_card), name))
        if not self._loaded_card and self._rows:
            return messagebox.askyesno(
                "Read this card?",
                "Clear the %d image%s you have set up and read %s instead?"
                % (len(self._rows), "" if len(self._rows) == 1 else "s",
                   name))
        return True

    def on_shown(self):
        """The Multi-boot tab has just been opened.

        THIS IS WHERE A RESTORED CARD IS READ.  :meth:`restore_state` puts
        the form back but deliberately reads nothing: the app must not start
        a WSL run merely by being launched, and the rig is a mutex between
        David's sessions, so a startup inspect can collide with a live one.
        That left the tab holding a card it had not read - the state the row
        calls 'there is a card here, and this tab has not looked inside it'
        - which is honest but half a job, and it is why the green button was
        Build & verify, aimed at overwriting the very card that was being
        edited last night.

        Opening the tab is the deliberate act that asks the question, and
        the person who asked is sitting in front of it. So the read happens
        once, here, and only when there is nothing to lose by it: a path
        with a real file at it, no card already read, no run in flight, and
        no unsaved edits (there are none - the form has just come back from
        disk, unchanged since).

        ONCE. The flag is cleared whatever happens, so a card that cannot be
        read is not re-read on every visit to the tab."""
        # THE PICTURE DRAWS ITSELF (David: "we shouldn't have to 'redraw
        # the preview' manually. if we're on this tab after we load the app,
        # it should fire off that event for us").  Opening the tab is the
        # deliberate act; the app still starts no tool merely by launching.
        self.schedule_preview()
        if not getattr(self, "_pending_read", False):
            return False
        self._pending_read = False
        if self._busy or self._loaded_card:
            return False
        path = self._out_var.get().strip().strip('"')
        if not path or not os.path.isfile(path):
            return False
        return bool(self._load_or_reload(confirm=False))

    def _path_committed(self, _event=None):
        """<Return> in the path box: read the card it names.

        The row has no verb button any more, so this is how a TYPED or
        PASTED path is read - and pressing Return is the same kind of act as
        picking a file, which is why it may do what Browse… does.  A path
        that has nothing at it is not an error here: Return on the way to
        building a new card should do nothing at all, quietly."""
        if not self._out_var.get().strip().strip('"'):
            return "break"          # on the way to a new card: say nothing
        if getattr(self, "_can_read", False):
            self._load_or_reload()
        elif self._row_kind == "looking":
            # The probe answers on a worker so a dead drive cannot freeze
            # the tab, and Return can beat it. Silence would read as a key
            # that does nothing.
            self._ok("Still looking at what is at that path - press Return "
                     "again in a moment.")
        return "break"

    def _load_or_reload(self, confirm=True):
        """The row's one verb: read the card the path box names.

        A LOAD IS A CLICK AND NEVER A KEYSTROKE - there is no <Return> and
        no <FocusOut> binding, and there must not be.  A read costs a WSL
        round trip, writes ``media-<stem>/`` beside the card and replaces
        every field, and on the way to typing ``x.raw.bak`` you pass through
        ``x.raw``, which exists.  The row's sentence describes; this
        acts."""
        if self._busy:
            self._error("Wait for the current run to finish first.")
            return False
        path = self._out_var.get().strip().strip('"')
        if not path:
            self._error("Type the card to read into 'Card image', or press "
                        "Browse… to pick one.")
            return False
        # ``confirm=False`` for the restore's own read (see on_shown):
        # nothing is being discarded there. The form came off disk a moment
        # ago and reading the card it NAMES is the second half of putting
        # the tab back, not the replacement of work someone did by hand -
        # asking "discard your changes?" about changes nobody made is the
        # kind of question that teaches people to click through questions.
        if confirm and not self._confirm_discard(path):
            return False
        return self.load_card(path)

    def _browse_card(self):
        """ONE picker for both meanings of this box: the card to read, and
        where a new one would be written.

        ``confirmoverwrite=False`` is load-bearing.  An *open* dialog cannot
        return a name that does not exist, so it could never pick a build
        target; a save dialog with the confirm left on would ask "overwrite?"
        while you are picking a card to READ, which is a lie.  The real
        overwrite gate is still :meth:`_confirm_overwrite`, on the press of
        Build.  The OS button says "Save" either way - the title carries the
        meaning, and the button cannot be renamed portably."""
        cur = self._out_var.get().strip()
        path = filedialog.asksaveasfilename(
            title="The card to read, or where to build a new one",
            defaultextension=".raw", confirmoverwrite=False,
            initialdir=os.path.dirname(cur) if cur else None,
            initialfile=os.path.basename(cur) if cur else None,
            filetypes=[("Card images", "*.raw *.img"), ("All files", "*.*")])
        if not path:
            return False
        # A card that EXISTS is one you meant to read, so read it - unless
        # that would cost something, and then ask first.  This is the move
        # David makes most, and it stays one click.
        #
        # THE QUESTION COMES BEFORE THE BOX IS TOUCHED.  Setting the path
        # first and asking afterwards made 'No, keep my edits' do half the
        # job anyway: the read was skipped, but the box now named the other
        # card, so the tab left editing mode, Apply went grey and the green
        # button flipped to Build & verify - the answer was 'keep my
        # changes' and the tab disabled the only button that could write
        # them.  A refusal now leaves the row exactly as it was.
        if os.path.isfile(path):
            if not self._confirm_discard(path):
                return False
            self._out_var.set(path)
            return self.load_card(path)
        self._out_var.set(path)
        return False

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
        self._media_entries = {}
        self._clip_widgets = ()

    def apply_theme(self, colors=None):
        """The app switched dark/light: re-colour the images table.

        The table is a grid of raw tk widgets (:class:`.image_table.
        ImageTable`) whose colours the ttk styles do not reach, so
        MainWindow._apply_theme calls this.  *colors* is the app theme dict
        it already has; without one the table re-reads it from
        ``self._theme_fn``.  Nothing else on the tab needs it - the rest is
        ttk, or the preview canvas which redraws in its own colours."""
        table = getattr(self, "_table", None)
        if table is not None:
            try:
                table.apply_theme(colors)
            except tk.TclError:                         # pragma: no cover
                pass

    def open_menu_settings(self):
        """'Menu settings…': the sounds, volume, countdown, default image,
        the bypass and the selector build path, in a modal.  The button
        beside it already says what they are (:func:`menu_summary`)."""
        if self._menu_dialog is not None:
            return self._menu_dialog
        self._menu_backup = (self._move_var.get(), self._confirm_var.get(),
                             self._volume_var.get(), self._timeout_var.get(),
                             self._default_var.get(), self._bypass_var.get(),
                             self._selector_var.get(), self._theme_var.get(),
                             {role: var.get()
                              for role, var in self._color_vars.items()})
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
             selector, theme, colors) = self._menu_backup
            self._menu_backup = None
            self._move_var.set(move)
            self._confirm_var.set(confirm)
            self._volume_var.set(vol)
            self._timeout_var.set(timeout)
            self._default_var.set(default)
            self._bypass_var.set(bypass)
            self._selector_var.set(selector)
            # the theme and the grid together, or the theme's trace would
            # re-seed the grid from the built-in and lose the colours
            self._loading = True
            try:
                self._theme_var.set(theme)
                self._seed_colors(colors)
            finally:
                self._loading = False
            self._sync_theme_states()
            self._menu_changed()
        self._update_menu_summary()

    def _forget_menu_dialog(self):
        self._menu_dialog = None
        self._default_spin = None
        self._bypass_chk = None
        self._theme_combo = None
        self._theme_tip = None
        self._color_entries = {}
        self._color_swatches = {}

    # -- the theme ---------------------------------------------------------

    def _theme_changed(self):
        """The theme moved.  A built-in puts its colours into the grid (so
        the grid shows what is on screen, and 'Make your own…' starts from
        it); 'Make your own…' keeps whatever the grid holds, seeded from
        the default only when it is empty.  While a load or a restore is
        filling the form nothing is seeded here - they seed the grid
        themselves, with what was on the card or saved."""
        theme = self._theme_var.get().strip().lower()
        if not self._loading:
            colors = theme_colors(theme)
            if colors is not None:
                self._seed_colors(colors)
            elif theme == CUSTOM_THEME and not any(
                    v.get().strip() for v in self._color_vars.values()):
                self._seed_colors(theme_colors(DEFAULT_THEME) or {})
            self._menu_changed()
        self._theme_prev = theme
        self._sync_theme_states()

    def _seed_colors(self, colors):
        """The colour grid <- ``{role: rrggbb}``, in one go: the vars' own
        traces stay quiet, and a role the dict lacks keeps its value."""
        was = self._loading
        self._loading = True
        try:
            for role, var in self._color_vars.items():
                if role in (colors or {}):
                    var.set(str(colors[role]))
        finally:
            self._loading = was
        self._paint_swatches()

    def _color_changed(self):
        """A colour was typed or picked."""
        if self._loading:
            return
        self._paint_swatches()
        self._menu_changed()

    def _theme_picked(self):
        """The picker's title -> the theme's name."""
        title = self._theme_pick.get()
        for name in theme_names() + [CUSTOM_THEME]:
            if theme_title(name) == title:
                if name != self._theme_var.get().strip().lower():
                    self._theme_var.set(name)
                return

    def _pick_color(self, role):
        """A click on a colour's swatch: the system chooser, seeded with the
        current value.  Only for 'Make your own…' - a built-in's swatches
        show, they do not edit."""
        var = self._color_vars.get(role)
        if var is None or self._theme_var.get().strip().lower() != \
                CUSTOM_THEME:
            return
        cur = clean_colors({role: var.get()}).get(role, "000000")
        parent = self._menu_dialog.top if self._menu_dialog is not None \
            else self._parent
        try:
            rgb = colorchooser.askcolor(
                color="#" + cur, parent=parent,
                title="%s colour" % theme_label(role))[0]
        except tk.TclError:
            rgb = None
        if rgb:
            var.set("%02x%02x%02x" % tuple(int(c) for c in rgb))

    def _sync_theme_states(self):
        """The grid's entries and Pick… buttons live only for 'Make your
        own…'; the picker shows the theme's title and its tip says what it
        looks like."""
        theme = self._theme_var.get().strip().lower()
        custom = theme == CUSTOM_THEME
        for w in self._color_entries.values():
            try:
                w.configure(state=tk.NORMAL if custom else tk.DISABLED)
            except tk.TclError:
                pass
        title = theme_title(theme)
        if self._theme_pick.get() != title:
            self._theme_pick.set(title)
        if self._theme_tip is not None:
            self._theme_tip.text = theme_about(theme)
        self._paint_swatches()

    def _paint_swatches(self):
        """Each swatch is its var's colour; a value that is not one shows
        the error colour, so a typo is seen before it is refused."""
        if not self._color_swatches:
            return
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        for role, cv in self._color_swatches.items():
            val = clean_colors({role: self._color_vars[role].get()}).get(role)
            try:
                cv.configure(bg="#" + val if val else th["error"])
            except tk.TclError:
                pass

    def _menu_changed(self):
        self._update_edit_status()
        self._update_menu_summary()
        self._refresh_sound_cells()
        self._push_volume()

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
        table = getattr(self, "_table", None)
        if table is None:
            return
        for i, row in enumerate(self._rows):
            table.set_cell(i, "sound", self._confirm_cell(row))

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
        theme = self._theme_var.get().strip().lower() or DEFAULT_THEME
        # the custom theme is the grid as typed (validate_form judges it);
        # a built-in carries no colours of its own
        colors = ({role: var.get().strip()
                   for role, var in self._color_vars.items()}
                  if theme == CUSTOM_THEME else {})
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
            or DEFAULT_SELECTOR_DIR,
            theme=theme, colors=colors)

    def _validated_form(self, sources=True):
        form = self.form()
        errs = validate_form(form, sources=sources)
        if errs:
            self._error("\n".join(errs))
            return None
        return form

    # ------------------------------------------------------------------
    # coming back as it was left
    # ------------------------------------------------------------------

    def state(self):
        """The tab's FORM as a plain document, for the project anchor (and
        the global settings when no project is open).

        What is here is what someone would otherwise have to type again: the
        card path, the image list with every field of every row, the menu,
        the selector directory, whether the preview follows the form, and
        the media directory a load extracted.  It is the same
        :class:`ImageRow` the builders read, dumped - not a parallel copy
        that could come to disagree with them - and it carries a version so
        a newer app can add fields without an older one choking on them.

        WHAT IS DELIBERATELY NOT HERE:

        * Everything transient or derived - the rendered frames, the busy
          flag, the media fingerprint caches, whether a run was in flight.
        * ``_loaded_card`` / ``_loaded_form`` / ``_loaded_info``, the
          editing-mode baseline.  The card may have changed while the app
          was shut; Apply's whole legality is decided by that baseline, and
          injecting a diff computed against a stale one is the one mistake
          this tab must not make.  A restart therefore comes back with the
          form and out of editing mode, and one click on the row's verb -
          one real read of the card - earns editing mode back honestly.
        * The preview's Sound box.  It defaults OFF on purpose and comes
          back OFF: this app is used in the room with a machine that is
          running, and "he left it on once" is not a reason to make noise on
          the next launch.  That is a decision, not an oversight.
        """
        return {
            "v": STATE_VERSION,
            "card": self._out_var.get().strip(),
            "images": [asdict(r) for r in self._rows],
            "menu": {"move": self._move_var.get().strip(),
                     "confirm": self._confirm_var.get().strip(),
                     "volume": _int(self._volume_var, 50),
                     "timeout": _int(self._timeout_var, 15),
                     "default": _int(self._default_var, 0),
                     "bypass": bool(self._bypass_var.get()),
                     "theme": self._theme_var.get().strip().lower()
                     or DEFAULT_THEME,
                     "colors": {role: var.get().strip()
                                for role, var in self._color_vars.items()}},
            "selector_dir": self._selector_var.get().strip(),
            "auto_preview": bool(self._auto_preview.get()),
            "media_dir": self._media_override,
        }

    def restore_state(self, doc):
        """Put the form back from a :meth:`state` document.  True when
        anything was restored.

        BEST-EFFORT THROUGHOUT.  An unreadable or half-written anchor on a
        NAS leaves the tab empty; it never fails a startup.  And NO TOOL
        RUNS: the path is set exactly as if it had been typed, so the row's
        stat runs and says what is at it, and nothing reads the card - the
        rig is a mutex between David's sessions and a startup inspect can
        collide with a live one.

        A restored .raw that has moved, or a drive that is not mounted, is
        not repaired here either: the row and the table say what they see
        (``[not on this machine]`` in the Image column, and the tab's own
        refusals at press time), which is the language this tab already
        has for it."""
        # AN EMPTY DOCUMENT IS AN ANSWER, NOT A NO-OP.  "Leaves the tab
        # empty" above has to MEAN empty: a project's value wins absolutely
        # including when it is empty (App.restore_multiboot_state), and an
        # anchor that cannot be READ is handed here as ``{}`` for exactly
        # that reason.  Returning early instead left the LAST project's card
        # path and image list standing - the row went on naming a card
        # belonging to a project that had been closed, Build & verify was
        # aimed at it, and the next quit wrote it into THIS project's anchor.
        # So an empty or unreadable document falls through the whole body
        # below, which clears the form by restoring nothing into it.  False
        # still means "nothing was restored"; it no longer also means "the
        # last project is still on screen".
        try:
            restored = isinstance(doc, dict) and int(doc.get("v") or 0) >= 1
        except (TypeError, ValueError):     # a version that isn't a number
            restored = False
        if not restored:
            doc = {}
        try:
            from ..core.admin import resolve_mapped_drive as _rmd
        except ImportError:                             # pragma: no cover
            def _rmd(p):
                return p
        card = _rmd(str(doc.get("card") or "")) if doc.get("card") else ""
        rows = rows_from_state(doc.get("images"), resolve=_rmd)
        menu = menu_from_state(doc.get("menu"))
        # THE MEDIA DIR IS PER CARD (loaded_media_dir), so one saved for a
        # different card would send a build's prepare into the wrong extract
        # directory.  When it does not belong to this card, drop it and let
        # media_dir_for() answer from the path.
        media = str(doc.get("media_dir") or "")
        if media:
            base = os.path.basename(os.path.normpath(media)).lower()
            if base.startswith("media-") and (
                    not card or _plain(media) != _plain(
                        loaded_media_dir(card))):
                media = ""
        self._rows = rows
        self._media_override = media
        # OUT OF EDITING MODE, SAID OUT LOUD.  :meth:`state` does not carry
        # the baseline, but "not restored" and "left standing" are not the
        # same thing on a live window: this also runs when the project is
        # SWITCHED, and a baseline the last project put there would go on
        # naming its card - with the media dir above just replaced under it.
        # The tab would say "the card you are editing" about a card this
        # project has never heard of, and typing that card's path - which a
        # project whose own card happens to be spelled the same does by
        # itself - would be editing mode again with media_dir() now
        # answering <out dir>/media instead of that card's own extract.
        self._loaded_card = ""
        self._loaded_form = None
        self._loaded_info = None
        self._armed = False
        # The alarm strip is the other half of what a load put on screen,
        # and it is about the card that is no longer loaded.
        self._show_alarm(None)
        # ...AND SO IS THE PICTURE.  Everything below is what load_inspect
        # and new_card already do, for the reason they do it: a restore is
        # the THIRD way into this state and has to leave the tab somewhere
        # those two could also have left it.  The frames on the canvas were
        # drawn for another form (another project's, on a switch); they are
        # keyed by fingerprint so none of them would be SHOWN again, but
        # nothing was clearing the canvas either, so the last project's menu
        # sat there under a caption about this one.
        self._pv_cache.clear()
        self._pv_totals.clear()
        self._pv_shown = None
        self._pv_src = None
        self._pv_ready = None
        self._pv_photo = None
        self._plan_info = None
        self._plan_text = ""
        self._drop_photos()
        self._stop_play(None)
        self._pv_placeholder()
        self._hl_touched = False
        # Inside the guard so twenty traces do not queue twenty previews and
        # twenty probes on the way in; one of each is asked for at the end.
        self._loading = True
        try:
            self._out_var.set(card)
            self._out_auto_value = ""   # a restored path is the USER'S path
            self._move_var.set(menu["move"])
            self._confirm_var.set(menu["confirm"])
            self._volume_var.set(str(menu["volume"]))
            self._timeout_var.set(str(menu["timeout"]))
            self._default_var.set(str(menu["default"]))
            self._bypass_var.set(True)      # always on (David); see __init__
            self._theme_var.set(menu["theme"])
            # a built-in comes back as the file spells it today; a custom
            # theme as it was saved, the default under any role it lacks
            self._seed_colors(theme_colors(menu["theme"]) or dict(
                theme_colors(DEFAULT_THEME) or {}, **menu["colors"]))
            sel = str(doc.get("selector_dir") or "").strip()
            self._selector_var.set(sel or DEFAULT_SELECTOR_DIR)
            # Restored in both directions, but never over the environment's
            # own off switch: the screenshot rig and the tests set it.
            self._auto_preview.set(
                bool(doc.get("auto_preview", True))
                and os.environ.get("PAD_MULTIBOOT_AUTO", "1") != "0")
        finally:
            self._loading = False
        self._set_var(self._hl_var, menu["default"])
        self._set_var(self._frame_var, 0)
        self._refresh_tree(select=min(menu["default"],
                                      max(0, len(self._rows) - 1))
                           if self._rows else None)
        self._update_menu_summary()
        self._update_edit_status()
        self._schedule_probe()
        # ...AND NOT THE SIZE CHECK.  _update_edit_status has just seen a
        # brand-new image list and armed one (_maybe_plan); it is a tool
        # run like any other and it is taken back here for the same reason.
        # The sentence stays blank until the person moves the list, which
        # is honest: nobody has measured this card in this session.
        self._cancel_plan()
        # NO RENDER EITHER.  'NO TOOL RUNS' above is the whole point of this
        # method and the render broke it: with the auto-preview remembered
        # ON (its default), a restore was a `make` of the selector and a
        # selectmedia prepare ~350 ms into the launch - the rig is a mutex
        # between David's sessions, and a startup that reaches for it can
        # collide with a live one.  It is CANCELLED rather than not asked
        # for: every field's trace asks for one, and so does _refresh_tree
        # above.  The picture waits for the first thing the person does, and
        # says so rather than sitting there looking like a preview that
        # agrees with the form.
        self._cancel_preview()
        self._pv_idle = True
        # A different media dir, so whatever was looping belonged to the
        # form that has just gone - the same line load_inspect ends on.
        self._sound_follow()
        if self._rows:
            # The headline does not name a button.  It used to end
            # 'check the card path, then Build & verify', which is advice to
            # overwrite whatever is at the restored path - and the restored
            # path is usually the card that was being EDITED last night,
            # because the box is that card's identity.  The row's own
            # sentence, one line below, says what is actually at it.
            self._ok("%d image%s and the menu came back from last time."
                     % (len(self._rows), "" if len(self._rows) == 1 else "s"))
        # ...and if that path has a card at it, reading it is what makes the
        # tab REALLY be as it was left - editing mode, with Apply live
        # instead of a green Build aimed at the card it would overwrite.
        # Not here, though: see :meth:`on_shown`.
        self._pending_read = bool(card)
        return restored

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

    #: How long the image list has to have been still before the size check
    #: runs itself.  Longer than the preview's debounce on purpose: the
    #: picture is what someone is watching while they work, and this is a
    #: second of tool time that must not get in front of it.
    PLAN_DEBOUNCE_MS = 900

    def _plan_key(self):
        """WHAT THE SIZE ANSWER DEPENDS ON, and nothing else: the image
        list, in order.

        :func:`plan_args` takes the images and the layout and no other
        field of the form, so a title, the countdown, the volume or the
        output path cannot change the answer - which is exactly what makes
        it safe to ask this question on every keystroke."""
        return tuple((r.path or "").strip().strip('"') for r in self._rows)

    def _maybe_plan(self):
        """Keep the size sentence TRUE, without anyone having to ask.

        'Check size' used to be a menu entry, and a menu entry means the
        sentence beside it is whatever the last press found: it went on
        saying a 16 GB card fits after a third image was added, and the
        only way to find out was to remember to ask again.  It writes
        nothing and costs about a second, so the tab asks for it itself -
        when the thing it depends on has moved, and only then.

        THE FOUR RULES, in the order they are enforced.  Not on every
        keystroke: nothing happens unless :meth:`_plan_key` has changed,
        and then only once the list has been still for
        :data:`PLAN_DEBOUNCE_MS`.  Not in front of a real run: it takes the
        preview's light guard, which a write run refuses outright.  Not
        behind one either: a refused attempt re-arms instead of queueing,
        because the answer is only wanted while this list is still the
        list.  And not at all while there is nothing a plan could be run on
        (see :meth:`_plan_now`).

        The stale sentence goes the MOMENT the list moves rather than when
        the new answer arrives - a wrong number is worse than no number."""
        key = self._plan_key()
        if key == self._plan_for:
            return
        self._plan_for = key
        self._plan_info = None
        self._plan_text = ""
        self._cancel_plan()
        if len(key) < 2 or not self._auto_plan:
            return
        try:
            self._plan_job = self._timer().after(self.PLAN_DEBOUNCE_MS,
                                                 self._plan_now)
        except tk.TclError:                             # pragma: no cover
            self._plan_job = None

    def _cancel_plan(self):
        job, self._plan_job = self._plan_job, None
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):           # pragma: no cover
                pass

    def _plan_now(self):
        """The debounce fired: ask ``mkmulticard.py plan`` how big this card
        would be.  True when the run started.

        It CANCELS rather than forgets: this is a public seam the tests
        drive directly, and dropping the id of a job that is still armed
        leaves it to fire into a torn-down interpreter."""
        self._cancel_plan()
        if self._stopped or not self._auto_plan:
            return False
        key = self._plan_key()
        # THE ONLY READINESS THIS RUN NEEDS.  Not validate_form: the plan
        # reads the images and nothing else, so a half-typed title or an
        # output path that is still being typed is no reason to leave the
        # size unknown - and a missing .raw is, because the tool would only
        # print a refusal into the Log nobody asked it to.
        if len(key) < 2 or not all(p and os.path.isfile(p) for p in key):
            return False
        form = self.form()

        def step(label, rc, text):
            # An answer about a list that has since moved is dropped rather
            # than shown: _maybe_plan has already blanked the sentence and
            # armed the next one.
            if label == "plan" and key == self._plan_key():
                self._plan_step(label, rc, text)

        def done(rc, failed, _texts):
            if rc != 0:
                # NOT ON THE STATUS LINE.  Nobody asked for this run, so a
                # failure of it must not take the line that is saying what
                # the buttons would do; the whole of the tool's output is in
                # the Log, where the reason is.
                self._write("the size check failed (exit %d) - the sentence "
                            "beside the status line is left blank." % rc)
        if not self._run_commands(plan_commands(form), on_step=step,
                                  on_done=done, preview=True):
            # The worker is busy.  Ask again in a moment rather than queue.
            try:
                self._plan_job = self._timer().after(self.PLAN_RETRY_MS,
                                                     self._plan_now)
            except tk.TclError:                         # pragma: no cover
                self._plan_job = None
            return False
        return True

    #: ...and how long it waits before asking again when the worker was
    #: busy.  A build holds it for minutes; this is a poll, so it is slow.
    PLAN_RETRY_MS = 2000

    def _plan_step(self, label, rc, text):
        if label != "plan":
            return
        if rc == 0:
            self._plan_info = parse_plan(text)
            self._plan_text = size_plan_text(self._plan_info)
            self._take_versions(self._plan_info.get("versions") or {})
        else:
            self._plan_text = ""
        # WHAT THE SENTENCE NOW DESCRIBES.  Claimed here rather than when
        # the run was asked for, so the build's own plan step - the same
        # answer, about the same images - keeps the tab from asking twice.
        self._plan_for = self._plan_key()
        self._update_edit_status()

    def _take_versions(self, versions):
        """Put the game code versions the tool just read into the table.

        BY INDEX, which is what the tool keys them by and what the list is
        ordered by.  A version is a FACT ABOUT THE .raw, never typed and
        never guessed from a file name, so an answer that does not name a
        row this tab still has is simply dropped - the list can be edited
        while a plan is in flight."""
        if not versions:
            return
        changed = False
        for i, version in versions.items():
            if 0 <= i < len(self._rows) and self._rows[i].version != version:
                self._rows[i].version = version
                changed = True
        if changed:
            self._refresh_tree(select=self._selected())

    def _build_card(self, after=None):
        form = self.form()
        # A LOADED CARD IS NOT AN OUTPUT.  After a load the path box holds
        # the card that was read - it IS that card's identity, which is how
        # Apply and the preview name the same file - and a build into it
        # would copy ~7 GB per image over the very card being edited.  The
        # way out is explicit, not a dialog: point 'Card image' somewhere
        # else, or press Apply.
        if self._loaded_card and _norm(form.out) == _norm(self._loaded_card):
            self._error(
                "Build & verify writes a NEW card, and 'Card image' names "
                "the card you loaded (%s). Point it at a different path to "
                "build a copy - typing this one back goes on editing it - "
                "or press Apply to card, which rewrites the menu of this "
                "one in seconds." % self._loaded_card)
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
                if after is not None:
                    after()
            else:
                self._error("%s failed (exit %d) - see the tool output."
                            % (failed or "the build", rc))
        return self._run_commands(cmds, on_step=self._plan_step, on_done=done)

    def _confirm_overwrite(self, path):
        """The one gate between Build & verify and a card that is already
        there - and it SAYS WHAT IT WOULD DESTROY.

        A restart puts the path box back on the card the last session was
        editing while deliberately not restoring the baseline (see
        :meth:`state`), so 'a loaded card is not an output' cannot fire and
        Build & verify is the green button on a path that names a finished
        card.  A bare 'Rebuild over it?' is not enough to stop that; the
        size and the date of what is at the path are what tell a person
        this is the card they made last night, and that the run underneath
        this question copies every image again."""
        what = ""
        try:
            st = os.stat(path)
            what = " (%.1f GB, written %s)" % (
                st.st_size / 1e9,
                time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)))
        except OSError:                                 # pragma: no cover
            pass
        return messagebox.askyesno(
            "Overwrite that card?",
            "%s already exists%s.\n\nBuild & verify writes a NEW card over "
            "it - every image is copied again, and whatever is on it now is "
            "gone. Overwrite it?" % (path, what))

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

    # THERE IS NO 'BYPASS AN EXISTING CARD…' HERE ANY MORE.  It ran
    # :func:`bypass_commands` on a card picked from a dialog, and Apply to
    # card already runs the very same commands whenever the Bypass box is
    # ticked and some image on the loaded card is still unpatched - by the
    # better road, because Apply re-reads the card afterwards and this did
    # not.  The mkmulticard subcommand behind it stays exactly where it is:
    # it is what Apply calls, and it is the cheap repair for a card that has
    # already been written.

    # ------------------------------------------------------------------
    # loading a card, and writing the menu back into it
    # ------------------------------------------------------------------

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
        # WHO MADE IT MATTERS.  The tool extracts the card's media into this
        # directory and wants it there, so it is created before the run -
        # but Browse… now reads any existing card you pick, and the row
        # cannot tell a multi card from a stock one (probe_card_path stats,
        # and that is all it may do), so a mis-pick is an ordinary event.
        # The refusal branch below takes back what WE made, and only that:
        # a directory that was already there is the last load's, and its
        # media is what a re-read would reuse.
        mine = not os.path.isdir(media)
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
                if mine:
                    # Empty only: a refusal that got as far as writing files
                    # leaves them for the person to look at.
                    try:
                        os.rmdir(media)
                    except OSError:
                        pass
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
            # The LIVE form's bypass is always on (David); the card's own
            # state stays in _loaded_form (form_from_inspect above), so an
            # image loaded unpatched shows a 'bypass' change and Update
            # patches it.
            self._bypass_var.set(True)
            self._theme_var.set(form.theme)
            self._seed_colors(form.colors if form.theme == CUSTOM_THEME
                              else theme_colors(form.theme) or {})
        finally:
            self._loading = False
        self._sync_theme_states()
        # AFTER the path box, not before it: setting the box runs
        # _out_changed, which drops a media dir that does not belong to the
        # card the box now names - and until _loaded_card is set below, the
        # dir this load extracted into is exactly that to it.
        self._media_override = media_dir
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
        self._pv_idle = False           # a read: the hold is a restore's
        self._drop_photos()
        self._set_var(self._hl_var, int(form.default))
        self._stop_play(None)
        self._pv_photo = None
        self._pv_placeholder()
        # A different card, a different media directory: whatever was
        # looping belonged to the last one.
        self._sound_follow()
        self._pv_say("Drawing THIS card's menu - its own media is in %s, so "
                     "nothing is prepared first." % media_dir)
        # The card's OWN default is the row to land on: it is the image the
        # machine would boot, and selecting a row points the preview at it.
        self._refresh_tree(select=min(max(0, int(form.default)),
                                      max(0, len(self._rows) - 1)))
        self._update_edit_status()
        # The probe's answer is keyed on the text AND on which card is
        # loaded (probe_card_path resolves the links); the card that was
        # just loaded is a different answer to the one it may already hold.
        self._schedule_probe(refresh=True)
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
                            "with no source recorded - pick something else "
                            "for it in Edit image… before changing any "
                            "media."
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

    def apply_to_card(self, after=None):
        """'Apply to card': the menu changes into the loaded card with an
        inject (plus a prepare when a media field changed, plus the bypass
        when it is ticked and a tree is still armed), then a last inspect
        that reads the card back.  Seconds, not a rebuild.  False when the
        tab refused."""
        if not self._loaded_card:
            self._error("Load a card first - Apply to card writes into the "
                        "card the form was read from.")
            return False
        # THE INVARIANT, ENFORCED AND NOT ONLY DRAWN.  The button is already
        # grey when the path box has been typed away from the loaded card,
        # but greying a button is a claim and this is the guarantee behind
        # it: an inject into X while the box says Y is the one way this tab
        # could write to a card nothing on screen names.
        if not self._on_loaded_path():
            self._error(
                "'Card image' no longer names %s, the card this form was "
                "read from, so there is nothing to apply to. Nothing was "
                "lost: type that path back and Apply to card is live "
                "again." % self._loaded_card)
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
                "an image means copying the images again - point 'Card "
                "image' at a new path (which leaves editing mode) and press "
                "Build & verify."
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
                # Apply's prepare is the FULL one (apply_commands), so the
                # sounds are in that set - see _render_frames' third field.
                self._pv_ready = (media_fingerprint(form), media, True)
            self._ok("Card updated: %s (%s)%s" % (
                self._loaded_card,
                ", ".join(menu) if menu else "no menu change",
                " - flash it again" if bypass else ""))
            self._update_edit_status()
            if after is not None:
                after()
        return self._run_commands(cmds, on_step=step, on_done=done,
                                  quiet=(INSPECT_JSON,))

    def _update_edit_status(self):
        """THE CONSEQUENCE LINE - the status block's second line: what the
        card path is pointing at, what Apply to card would write (or why
        only a rebuild can), and how big the card would be.  Called after
        every keystroke.

        They share one line because they are one question - what would the
        button under them do - and the block has room for one line each.
        THIS IS ALSO WHERE THE MODE IS SHOWN.  The row lost its two labelled
        buttons, which stated the tab's two modes for free; a sentence here
        states them instead, and costs no pixels because the line was
        already there and empty in every state but editing.

        It also settles what the row's verb says and whether it is live.
        The writing side is one green button now (Build / flash card…) whose
        modal decides Apply-vs-Build for itself (:meth:`_write_plan`), so
        this no longer greens or greys a pair - it only writes the sentence
        and keeps ``_can_read`` / ``_row_kind`` current for the path box."""
        lbl = getattr(self, "_edit_lbl", None)
        if lbl is None:
            return
        # FIRST, because the size sentence is half of the line built below
        # and this is what decides whether it is still true: asking after
        # the label had been written left the stale number on screen until
        # something else redrew it.
        self._maybe_plan()
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        field = self._out_var.get().strip().strip('"')
        menu, rebuild = [], []
        if self._loaded_card and self._loaded_form is not None:
            menu, rebuild = diff_forms(self._loaded_form, self.form())
        kind, text, tone, can_read = card_path_state(
            field, self._facts_now(field), self._rows, self._loaded_card,
            menu, rebuild)
        # (The 'unticking the bypass cannot un-patch a card' note is gone
        # with the bypass tick itself - the bypass is always on now, so it
        # can never be untied.  The Apply-vs-Build decision that used to
        # live here is _write_plan's now, off the same card_path_state.)
        line = "  ·  ".join(p for p in (text, self._plan_text) if p)
        try:
            lbl.configure(text=self._status_line(line), foreground=th[tone])
        except tk.TclError:
            pass
        self._can_read = bool(can_read)
        #: What the probe last said about the path, so <Return> can tell
        #: "there is nothing there" from "the answer has not come back".
        self._row_kind = kind

    def _write_plan(self):
        """What 'Build / flash card…' would do, for the dialog and its own
        Start button: a dict with the checkbox's LABEL and DETAIL, whether
        that write has anything to do (``can_write``), the ``action`` it is
        ('apply' / 'build'), and whether a finished card is already on disk
        to flash (``have_card``).

        This is the Apply-vs-Build decision, in ONE place - the same one the
        consequence line describes: a loaded card the box still names, whose
        only changes an inject can carry, APPLIES; anything else BUILDS."""
        form = self.form()
        field = self._out_var.get().strip().strip('"')
        menu, rebuild = [], []
        if self._loaded_card and self._loaded_form is not None:
            menu, rebuild = diff_forms(self._loaded_form, form)
        # EDITING is decided the SAME WAY the consequence line decides it
        # (card_path_state, off the probe's facts), not by a bare string
        # compare: a junction or case spelling of the loaded card the probe
        # resolved is still that card, and Apply must stay live on it.
        kind, _t, _tone, _cr = card_path_state(
            field, self._facts_now(field), self._rows, self._loaded_card,
            menu, rebuild)
        editing = kind == "loaded"
        have_card = bool(field and os.path.isfile(field))
        if editing and not rebuild:
            name = os.path.basename(self._loaded_card)
            # THE FAST, INCREMENTAL UPDATE (David, 2026-09-03: "a small text
            # correction or different sound selection... the update needs to
            # be performant. the heavy lifting of merging the images together
            # needs to be one-and-done").  The image list is unchanged, so
            # the ~7 GB-per-image merge is NOT redone: only the menu is
            # rewritten in place, and only the changed media re-rendered -
            # seconds, not the minutes a fresh build costs.
            #
            # ``can_write`` is true whenever a card is loaded and the box
            # still names it (re-writing the same values is a harmless
            # second inject, and is how the tab has always let Apply be
            # pressed); ``default_write`` pre-ticks it only when something
            # actually changed, so opening the modal on an untouched card
            # does not offer to re-write it for nothing.
            if menu:
                detail = ("%s - the images are untouched, so only the menu "
                          "is rewritten (and any changed sound re-rendered): "
                          "seconds, not a fresh merge of every image."
                          % "; ".join(menu))
            else:
                detail = ("No change pending - ticking this re-writes the "
                          "same menu into %s (the images are never touched)."
                          % name)
            return {
                "action": "apply",
                "can_write": not self._busy,
                "default_write": bool(menu),
                "have_card": have_card,
                "out": field,
                "write_label": "Update the loaded card in place",
                "write_detail": detail,
            }
        can = bool(self._rows and field) and not self._busy
        if can:
            detail = ("Writes a new card at %s - every image is copied "
                      "(minutes)." % field)
        elif not self._rows:
            detail = "Add at least one image first."
        else:
            detail = "Set a card image path first."
        label = "Build a fresh card"
        if field:
            label += " at %s" % os.path.basename(field)
        return {
            "action": "build",
            "can_write": can,
            "default_write": can,
            "have_card": have_card,
            "out": field,
            "write_label": label,
            "write_detail": detail,
        }

    def _open_build_flash(self):
        """Open the Build / flash modal (:class:`BuildFlashDialog`)."""
        if self._buildflash_dialog is not None:
            return self._buildflash_dialog
        if self._busy:
            self._error("Wait for the current run to finish first.")
            return None
        self._buildflash_dialog = BuildFlashDialog(self)
        return self._buildflash_dialog.show()

    def _forget_build_flash(self):
        self._buildflash_dialog = None

    def _do_build_flash(self, do_write, do_flash):
        """The modal's Start: write the card (apply or build, whichever the
        plan says), then - if asked, and only on success - flash it.

        A flash asked for WITHOUT a write goes straight to the existing
        card; a flash asked for WITH one is chained through the write's
        ``after`` hook, so a failed build never reaches an SD card."""
        self._forget_build_flash()
        after = (lambda: self._flash()) if do_flash else None
        if do_write:
            if self._write_plan()["action"] == "apply":
                self.apply_to_card(after=after)
            else:
                self._build_card(after=after)
        elif do_flash:
            self._flash()

    # ------------------------------------------------------------------
    # the preview
    # ------------------------------------------------------------------

    def _pv_placeholder(self):
        # There is no frame to describe, so there is nothing for a later
        # _recaption to say again either.
        self._pv_caption, self._pv_error = "", False
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

    def _status_font(self):
        """The font the strip's caption is drawn in, BY NAME - so this is
        the interpreter's own font object and not a new one made (and left
        behind) on every measurement."""
        try:
            name = str(self._pv_status.cget("font") or "") or "TkDefaultFont"
            return tkfont.Font(root=self._pv_status, name=name, exists=True)
        except (tk.TclError, ValueError, AttributeError):   # pragma: no cover
            return None

    def _one_line(self, text):
        """*text* cut to the ONE line the control strip can draw.

        The strip is a fixed 30 px with ``pack_propagate(False)`` (see
        :meth:`_build_preview`) and one line of this font is 15, so a
        caption that wraps is drawn with its second line sliced in half by
        the strip's bottom edge - and the half that goes is always the half
        that said what to do about it.  Measured against the label's own
        font and its own wraplength rather than guessed at a character
        count, because the room depends on the window's width; nothing is
        lost by the cut - the whole sentence is in the label's tooltip and
        in the app's Log."""
        if not text:
            return text
        fnt = self._status_font()
        try:
            room = int(self._pv_status.cget("wraplength") or 0)
        except (tk.TclError, ValueError):               # pragma: no cover
            room = 0
        # Before the first <Configure> the label has no wraplength and so
        # no room to measure against: it is not on screen yet either.
        if fnt is None or room <= 0 or fnt.measure(text) <= room:
            return text
        cut = text
        while cut and fnt.measure(cut + "…") > room:
            cut = cut[:-1]
        return (cut.rstrip() + "…") if cut.strip() else text

    def _pv_say(self, msg, error=False, note="", log=True):
        """The preview's status line: ONE line of it on the strip, and the
        whole of it everywhere a whole sentence fits.

        WHAT IT SAYS IS REMEMBERED, because the strip carries more than
        captions - a cache miss saying a frame has not been drawn, a red
        failure - and :meth:`_recaption` re-issues THIS line when the sound
        changes under it.  (Re-issuing the last frame's caption instead
        wiped both of those, ~400 ms after the first sound, without the
        picture having moved.)  *note* is the sound aside riding this one
        line: said once, so never remembered.

        An error still goes to the app's Log, and so does anything the
        strip could only show half of, so 'paste what it said' is one
        paste either way - but never the same line twice running: a
        failure that repeats at the animation's rate would otherwise pour
        sixty lines a second into the Log pane, which is one of this app's
        known ways of freezing its own UI thread."""
        self._pv_caption, self._pv_error = msg, bool(error)
        text = (msg + (note or "")).strip()
        shown = self._one_line(text)
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        try:
            self._pv_status.configure(
                text=shown, foreground=th["error"] if error else th["fg"])
        except tk.TclError:
            pass
        tip = getattr(self, "_pv_status_tip", None)
        if tip is not None:
            tip.text = text if text != shown else ""
        if not log or not text:
            return
        # The note half is already in the Log in full (see _say_sound), so
        # a cut line only owes the Log the caption half.
        line = text if error else (msg if text != shown else "")
        if line and line != self._pv_logged:
            self._pv_logged = line
            self._write("[preview] " + line)

    def _follow_default(self):
        """Highlight follows the Default index until it is typed by hand."""
        if self._hl_touched or self._pv_loading:
            return
        self._set_var(self._hl_var, self._default_var.get())
        self._sound_follow()

    def _set_var(self, var, value):
        """A programmatic write to one of the preview's own variables,
        without the 'typed' trace."""
        self._pv_loading = True
        try:
            var.set(str(value))
        finally:
            self._pv_loading = False

    # -- the flippers ----------------------------------------------------

    @staticmethod
    def _image_label(highlight):
        """An image as THE PICTURE names it.

        codeselect.c draws every card's label ``"IMAGE %d", i + 1``
        (codeselect.c:545), so the words 20 px under that picture count
        from one as well: the flippers walk IMAGE 1, IMAGE 2, IMAGE 3 and a
        caption walking Image 0, Image 1, Image 2 under them is the tab's
        own readout contradicting its own frame.  The INDEX stays 0-based
        everywhere it is a number the tools read (the conf's ``default=``,
        the cache key, the frame file name) - this is the one place it is
        read by a person, beside the picture that numbers it."""
        return "Image %d" % (int(highlight) + 1)

    def flip(self, step):
        """A FLIPPER PRESS: the highlight moves one card and WRAPS, and the
        move sound plays over the music.

        codeselect.c's EV_LEFT / EV_RIGHT and nothing else - ``hl = (hl + n
        - 1) % n`` and ``hl = (hl + 1) % n``, plus ``audio_play(move)`` on
        every press - because the whole point of this preview is that it is
        the machine's own behaviour and not an imitation of it.  The press
        counts as a HAND-TYPED highlight, so from here on the picture stays
        on the card the person chose instead of following the Default
        index.  False when there is nothing to move between."""
        n = len(self._rows)
        if n < 2:
            return False
        hl = _int(self._hl_var, _int(self._default_var, 0))
        if not 0 <= hl < n:
            hl = 0
        # + n before the modulo, the way the C does it: a left press off
        # image 0 lands on the last card and not on -1.
        nxt = (hl + int(step) + n) % n
        # 'a new card: its animation restarts' - the C sets frame = 0 on
        # every highlight change, and a preview that carried frame 7 across
        # to a card with four frames would be showing a frame the machine
        # never shows at that moment.
        self._set_var(self._frame_var, 0)
        if self._play_var.get():
            self._play_hl = nxt         # ...and Play follows the highlight
        # AND THE TABLE FOLLOWS THE PICTURE.  The flippers are the headline
        # way of choosing a card now, and a press that left the blue row and
        # the editor fields on the image the picture had just walked away
        # from put the tab's two answers to 'which image' side by side on
        # screen disagreeing.  First, so its own selection handler writes
        # the highlight before the typed write below marks it chosen by hand.
        self._select_row(nxt)
        self._hl_var.set(str(nxt))                          # a typed write
        self._sound_click()
        return True

    def flip_left(self):
        """The left flipper: the previous card, wrapping to the last."""
        return self.flip(-1)

    def flip_right(self):
        """The right flipper: the next card, wrapping to the first."""
        return self.flip(1)

    def _sync_flippers(self):
        """The flippers are live only while there is somewhere to move TO.

        One image is a menu with nothing to choose between; a button that
        does nothing when pressed is worse than one that says it cannot, and
        the machine has these same two buttons whatever is on the card - so
        they stay where they are and go grey."""
        live = len(self._rows) >= 2
        for name in ("_flip_l", "_flip_r"):
            btn = getattr(self, name, None)
            if btn is None:
                continue
            try:
                btn.configure(state=tk.NORMAL if live else tk.DISABLED)
            except tk.TclError:                         # pragma: no cover
                pass

    def _hl_changed(self, typed=False):
        if self._pv_loading:
            return
        if typed:
            self._hl_touched = True
        self._sound_follow()
        self._show_cached()

    def _frame_changed(self, typed=False):
        if self._pv_loading:
            return
        self._show_cached()

    # -- the sound -------------------------------------------------------
    #
    # THE PICTURE IS THE SELECTOR'S OWN; THE SOUND CANNOT BE.  A --snapshot
    # run draws one frame and exits, and its ALSA sink is on the far side of
    # WSL, so the WAVs are played here - by preview_audio, which is written
    # to match audio.c sample for sample.  Everything below is about WHICH
    # file, and the answer is always the one media.json names: the form
    # holds specs ('auto', 'synth', a path on this machine), and what the
    # machine will really open is what the tools rendered from them.

    #: How often the tab reads the player's own status while Sound is on.
    #: The backend is chosen on the player's worker thread, so what it has
    #: to say - which device answered, a WAV it would not play, that this
    #: machine has no sound at all - is not known when loop() returns.  The
    #: player would call back, but on THAT thread, and nothing but the main
    #: loop may touch a widget here (see _drain) - so the main loop asks
    #: instead.  It costs a string compare while the sound is on, and
    #: nothing at all while it is off.
    SOUND_POLL_MS = 400

    #: ...and how long it keeps going after a sound was asked for while
    #: Sound itself is off (the confirm sound, which plays either way):
    #: the answer to a one-shot - a WAV that will not play, a device that
    #: would not open - reaches the player a moment after the call that
    #: asked for it has returned.
    SOUND_POLL_AFTER_S = 2.0

    def _manifest(self, media_dir):
        """``media.json`` out of *media_dir*, re-read when the file moves.

        Asked for on every highlight change, and rewritten under us by every
        prepare - so it is keyed on the file's own mtime and size rather
        than read once and trusted for the session."""
        if not media_dir:
            return {}                   # never a relative 'media.json'
        try:
            st = os.stat(os.path.join(media_dir, MEDIA_MANIFEST))
            key = (media_dir, st.st_mtime, st.st_size)
        except OSError:
            self._manifest_at = ((media_dir, None, None), {})
            return {}
        if self._manifest_at[0] != key:
            self._manifest_at = (key, read_manifest(media_dir))
        return self._manifest_at[1]

    def menu_sounds(self, highlight=None):
        """What the menu would play for the highlighted image right now -
        ``{"music", "move", "confirm"}``, full paths, "" for a sound this
        media set has not got (see :func:`manifest_sounds`).  The seam the
        preview's own sound, the right-click menu and the tests read."""
        media = self.media_dir()
        hl = (_int(self._hl_var, _int(self._default_var, 0))
              if highlight is None else int(highlight))
        manifest = self._manifest(media)
        sounds = manifest_sounds(manifest, media, hl)
        # THE FORM SAYS WHETHER AN IMAGE HAS A SOUND; the manifest only says
        # which file.  A row set to 'none' since the last prepare still has
        # its old bed - and its old confirm - sitting in that directory, and
        # playing one, or saying it is there, would be describing a card
        # nobody is going to build.  BOTH sounds the form can turn off get
        # the same guard: the confirm was left to the manifest alone, so an
        # image whose Confirm said 'the menu's sound' still offered - and
        # played - the confirm<N>.wav an earlier prepare had left for it.
        row = self._rows[hl] if 0 <= hl < len(self._rows) else None
        if row is not None and _media_value(row.music) in ("", "none"):
            sounds["music"] = ""
        if row is not None and confirm_spec(row) == "none":
            # ...and this is the selector's own fallback re-read off the
            # form: 'none' is how selectmedia spells 'image N has no confirm
            # of its own', so the MENU's confirm is what would play - and
            # when the menu has none either, nothing does.
            name = manifest.get("sound_confirm")
            sounds["confirm"] = os.path.join(media, name) \
                if name and media and self._menu_confirm() != "none" else ""
        return sounds

    def _menu_confirm(self):
        """The menu-wide confirm sound as the form spells it - the value
        :meth:`form` would put in ``sound_confirm``, without building the
        whole form to ask."""
        return _media_value(self._confirm_var.get().strip() or "none")

    def _audio_player(self):
        """The preview's player, made on the FIRST sound and not before.

        preview_audio imports neither sounddevice nor numpy and opens no
        device until it is asked to play something, and this tab does not
        ask until someone has ticked Sound - so a session that never wants
        sound never touches an audio device at all."""
        if self._audio is None:
            self._audio = PreviewAudio(volume=_int(self._volume_var, 50))
        # A sound is about to be asked for: watch for what the player makes
        # of it, whether or not Sound itself is on.
        self._sound_watch_until = time.time() + self.SOUND_POLL_AFTER_S
        self._sound_poll()
        return self._audio

    def _sound_toggled(self):
        """The Sound tick: on plays what the menu plays, off is silence and
        the device handed back.

        AND TICKING IT RENDERS THE SOUNDS.  The preview prepares pictures
        and music only (``--visual-only``), so a set it rendered for itself
        has no move and no confirm sound in it - and what the tab used to do
        about that was tell the person to go and find 'Prepare media' in a
        menu and press it.  Ticking Sound IS the asking; the run it needs is
        this tab's business, not a second instruction."""
        if not self._sound_var.get():
            self._stop_sound()
        else:
            self._prepare_sounds()
            self._sound_follow()
        self._recaption()

    def _prepare_sounds(self):
        """Render the menu's SOUNDS into the media set, if they are not
        there already.  True when a run started.

        The same ``selectmedia prepare`` the preview runs, without
        ``--visual-only`` - so it renders the pictures too, and
        selectmedia's own sidecar cache makes that nearly free for the ones
        that have not changed.  It takes the preview's light guard: this is
        background work about the picture, and it must never grey the tab
        or get in front of a build.

        ONLY THE TICK ASKS FOR IT.  Not a flipper press and not the confirm
        entry: those are one press about one sound, and a press that starts
        a tool nobody asked for is how the old 'Prepare media' entry earned
        its place in the menu that has gone."""
        if self._stopped or self._sounds_ready():
            return False
        form = self.form()
        errs = validate_form(form, sources=self.needs_prepare())
        if errs:
            self._pv_stale(errs[0], len(errs) - 1)
            return False
        media = self.media_dir()          # was already stat'ed by form()
        mfp = media_fingerprint(form)
        try:
            self._makedirs(media)
        except OSError as exc:
            self._pv_say("Cannot create %s: %s" % (media, exc), error=True)
            return False

        def step(label, rc, _text):
            if label == "prepare" and rc == 0:
                self._pv_ready = (mfp, media, True)

        def done(rc, _failed, _texts):
            if rc == 0:
                self._sound_follow()
                self._say_sound(None)   # ...so the next miss is said again
                self._pv_say("The menu's sounds are ready.")
            else:
                self._pv_say("The menu's sounds could not be rendered (exit "
                             "%d) - see the tool output." % rc, error=True)
        if not self._run_commands(prepare_commands(form, media),
                                  on_step=step, on_done=done, preview=True):
            return False
        self._pv_say("Rendering the menu's sounds…")
        return True

    def _sounds_missing(self):
        """Every sound the FORM asks the menu to play that this media set has
        not got, named, in the order the menu uses them.

        THE MOVE SOUND USED TO STAND FOR ALL OF THEM - "the marker for the
        pair, because one prepare writes both" - and it cannot.  One prepare
        writes the two menu sounds AND every image's own music and confirm,
        so a set that had move.wav counted as ready however many beds were
        added afterwards, and the bed never got rendered (David: "i tried
        adding music to a second image and it's not sounding when hovering
        over that").

        ASKED OF THE FILES, not of who wrote them or of the manifest alone.
        A set a load extracted off a card has its sounds, an earlier full
        prepare's has them, and the half-set the preview renders for itself
        (``--visual-only``: the pictures and the music, no menu sounds) does
        not - but so does a set whose prepare was REFUSED half way through,
        which the manifest cannot tell you and the directory can."""
        media = self.media_dir()
        manifest = self._manifest(media) if media else {}

        def gone(asked, name):
            if not asked:
                return False
            if not (media and name):
                return True
            return not os.path.isfile(os.path.join(media, name))

        missing = []
        if gone(_media_value(self._move_var.get().strip() or "none") != "none",
                manifest.get("sound_move")):
            missing.append("the move sound")
        if gone(self._menu_confirm() != "none", manifest.get("sound_confirm")):
            missing.append("the confirm sound")
        rows = manifest.get("images") or []
        for i, row in enumerate(self._rows):
            entry = rows[i] if i < len(rows) and isinstance(rows[i], dict) \
                else {}
            # The images are numbered the way the picture numbers them, from
            # one, because this is said to a person (see _image_label).
            if gone(_media_value(row.music) not in ("", "none"),
                    entry.get("music")):
                missing.append("image %d's music" % (i + 1))
            if gone(confirm_spec(row) != "none", entry.get("confirm")):
                missing.append("image %d's confirm sound" % (i + 1))
        return missing

    def _sounds_ready(self):
        """Whether every sound the form asks for is on disk (see
        :meth:`_sounds_missing`)."""
        return not self._sounds_missing()

    def _sound_follow(self):
        """Play what the menu would be playing NOW: the highlighted image's
        music bed, or silence when it has none.

        A new card's bed takes over at once, and a card whose music is the
        same clip does not restart it - the player keeps codeselect.c's own
        rule for that.  Free and silent while Sound is off, which is why
        every highlight change may call it."""
        if not self._sound_var.get():
            return False
        audio = self._audio_player()
        audio.set_volume(_int(self._volume_var, 50))
        audio.loop(self.menu_sounds()["music"])
        return True

    def _sound_click(self):
        """The move sound a flipper press makes, over the music - what the
        machine does on every EV_LEFT / EV_RIGHT.

        A media set prepared by the PREVIEW has no move sound in it (a
        ``--visual-only`` prepare renders the pictures and the music and
        skips the two menu sounds), so this is the one place that has to say
        'there is no click to play, and here is how to get one'."""
        if not self._sound_var.get():
            return False
        move = self.menu_sounds()["move"]
        if not move:
            # SHORT ENOUGH FOR THE STRIP.  It is one line of 30 px (see
            # :meth:`_one_line`), and this sentence had to say the whole of
            # itself there rather than be cut in half at every window width
            # the tab supports; the long version of why lives in the Sound
            # tooltip, where there is room for it.  It names no control
            # either - 'More ▾ ▸ Prepare media' is gone, and what replaced
            # it is the Sound tick itself, which has already been pressed by
            # anyone reading this - so it says the fact and stops.
            self._sound_aside("No move sound in this media set.")
            return False
        self._audio_player().play(move)
        return True

    #: How long the screen stays black after Select.  The machine's own
    #: gap is however long the game takes to come up, which is far longer;
    #: this is a beat, enough to read as "and then it goes".
    LOADING_MS = 1000

    def press_select(self):
        """START, on the picture: the chosen image's confirm sound, and the
        screen black while it plays.

        The machine draws a LOADING frame, plays that card's confirm sound
        to completion and boots - so the black is not decoration, it is the
        moment the menu hands over.  Hearing the sound against the picture
        it belongs to is the whole point of being able to press this before
        a card exists."""
        self.play_confirm()
        self._blackout()
        return True

    def _blackout(self):
        """Black the canvas for :data:`LOADING_MS`, then put the frame back.

        The picture on screen is not thrown away - it is re-shown from the
        file it was drawn from - so this costs no render and cannot leave
        the preview empty if the tab is torn down mid-beat."""
        canvas = getattr(self, "_pv_canvas", None)
        if canvas is None:                              # pragma: no cover
            return False
        self._cancel_blackout()
        try:
            canvas.delete("all")
        except tk.TclError:                             # pragma: no cover
            return False
        try:
            self._black_job = self._timer().after(self.LOADING_MS,
                                                  self._blackout_over)
        except tk.TclError:                             # pragma: no cover
            self._blackout_over()
        return True

    def _cancel_blackout(self):
        job = getattr(self, "_black_job", None)
        self._black_job = None
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except tk.TclError:                         # pragma: no cover
                pass

    def _blackout_over(self):
        """The beat is over: put back the frame that was on screen."""
        self._black_job = None
        if self._stopped:
            return False
        src = self._pv_src
        if not src:
            self._pv_placeholder()
            return False
        self.load_frame(src[0], src[1], src[2], src[3])
        return True

    def play_confirm(self):
        """'Play this image's confirm sound' - the picture's right-click
        menu, and the only way to hear that sound before a card is written:
        it plays when THAT image is chosen and at no other time.

        It plays whether or not Sound is ticked - choosing it IS the asking
        - and it starts no music: one sound, because one sound is what was
        asked for."""
        hl = _int(self._hl_var, _int(self._default_var, 0))
        confirm = self.menu_sounds(hl)["confirm"]
        if not confirm:
            # The media DIRECTORY is not in this line any more: it is a full
            # path on a loaded card, and the strip is one line - the whole
            # of it went to the Log and the half left on screen named the
            # selector's folder instead of saying what to do.  It names no
            # control now either: the sounds are rendered by the Sound tick
            # (see :meth:`_prepare_sounds`), and one press about one sound
            # is not the place to start a tool.
            self._pv_say("%s has no confirm sound in this media set."
                         % self._image_label(hl))
            return False
        audio = self._audio_player()
        audio.set_volume(_int(self._volume_var, 50))
        # AND THE BED GOES FIRST, because it does on the machine:
        # codeselect.c stops music_voice and only then plays the confirm,
        # which runs alone under the LOADING frame.  Judging this sound over
        # a loop that will not be there is judging the wrong loudness.  Only
        # when Sound is on - with it off there is no bed to stop.
        stopped = bool(self._sound_var.get())
        if stopped:
            audio.loop(None)
        audio.play(confirm)
        self._pv_say("%s's confirm sound: %s%s"
                     % (self._image_label(hl), os.path.basename(confirm),
                        " - the music stops for it, as it does on the "
                        "machine; a flipper press brings it back."
                        if stopped else ""))
        return True

    def _push_volume(self):
        """The menu's volume IS the preview's: media.json's 0-100 means the
        same loudness in the player as it does on the machine (the mixer is
        audio.c's, gain and all).  Only while something is playing - reading
        the box must not be what opens a device."""
        if self._audio is not None and self._sound_var.get():
            self._audio.set_volume(_int(self._volume_var, 50))

    def _stop_sound(self):
        """Silence, and the device given back.  The player is kept: a later
        loop() opens it all again."""
        self._sound_watch_until = 0.0
        self._cancel_sound_poll()
        if self._audio is not None:
            self._audio.stop()

    def _cancel_sound_poll(self):
        """Take back the pending poll, if any.

        It is cancelled rather than forgotten because :meth:`_sound_poll`
        is called from outside the timer too (the first player makes one
        happen at once): dropping the id would leave an ``after`` armed on
        a tab that has gone, which fires into a dead interpreter."""
        job, self._sound_job = self._sound_job, None
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):           # pragma: no cover
                pass

    def _sound_poll(self):
        """Read the player's own status, on the main loop (see
        :data:`SOUND_POLL_MS`), and put anything new on the caption."""
        self._cancel_sound_poll()
        if self._stopped or self._audio is None:
            return
        status = self._audio.status
        if status != self._sound_status:
            self._sound_status = status
            self._recaption()
        if self._sound_var.get() or time.time() < self._sound_watch_until:
            try:
                self._sound_job = self._timer().after(self.SOUND_POLL_MS,
                                                      self._sound_poll)
            except tk.TclError:                         # pragma: no cover
                pass

    def _sound_note(self):
        """The one thing worth saying about sound right now, or "".

        Two things are worth saying, and both are said ONCE (see
        :meth:`_sound_suffix`): that the highlighted image has music nobody
        is hearing, because a feature nobody finds is not a feature; and
        that the sound is on but cannot come out, in the player's own
        words, because a tick that does nothing has to explain itself."""
        if not self._sound_var.get():
            if self.menu_sounds()["music"]:
                # SHORT, because this is the ONE line that says the Sound
                # tick exists and it rides a caption on a 30 px strip: the
                # longer wording was cut in half at every window width
                # below 1024, said once, and never said again.
                return "This image has music - tick Sound to hear it."
            return ""
        if self._audio is None or not self._audio.backend_name:
            return ""                   # not chosen yet; the poll comes back
        if not self._audio.available:
            return self._audio.why_silent
        return ""

    def _sound_suffix(self):
        """What the caption adds about sound - said once, then dropped.

        A sentence repeated on every redraw is noise; a sentence never said
        is a silent feature.  So it rides the FIRST caption after the thing
        it is about changes, and goes to the app's Log in full."""
        return self._say_sound(self._sound_note())

    def _say_sound(self, note):
        """Remember *note* as what has been said about sound and hand it
        back the first time; "" when it is what was said last."""
        if note == self._sound_said:
            return ""
        self._sound_said = note
        if not note:
            return ""
        self._write("[preview] " + note)
        return "  " + note

    def _sound_aside(self, note):
        """Say *note* about the sound NOW, beside whatever the strip
        already says - for the things only a press can find out."""
        text = self._say_sound(note)
        if text:
            self._pv_say(self._pv_caption, error=self._pv_error, note=text,
                         log=False)

    def _recaption(self):
        """Say the line that is UP again, with what the sound has just
        changed about it, and without re-drawing the picture.

        Whatever is up - not the last frame's caption.  The strip carries
        more than captions: 'image N frame M has not been drawn yet' after
        a flipper press, and a red 'Preview failed at …'.  This is called
        on every Sound tick and ~400 ms after the first sound (the player
        picks its backend on a worker and the poll sees the status change),
        so re-issuing an older caption threw both of those away without the
        picture having moved - and with them the instruction the person was
        reading."""
        self._pv_say(self._pv_caption, error=self._pv_error,
                     note=self._sound_suffix(), log=False)

    def _current_key(self, form=None):
        """(fingerprint, highlight, frame) the preview points at, or None
        when the form has nothing to draw."""
        form = form or self.form()
        if not form.images:
            return None
        hl = _int(self._hl_var, int(form.default))
        n = _int(self._frame_var, 0)
        return preview_fingerprint(form), hl, n

    def _on_screen(self, key):
        """Whether the cached frame *key* names is the very picture the
        canvas is holding.

        THE FILE IS THE TEST, not ``_pv_shown``.  That pair is only
        (highlight, frame); the fingerprint - the part of the key that says
        WHICH FORM drew the picture - is not in it.  So: type a title, let
        it draw; type another, let it draw (the first form's frame is spared
        by :meth:`_prune_frames`, because it was the one on screen, so its
        cache entry lives on); then type the first title back, and the key
        hits the cache at the same image and the same frame number while the
        canvas is still holding the OTHER form's picture - and nothing is
        redrawn, silently.  The file name carries the fingerprint (see
        :func:`frame_path`), so comparing it with what :attr:`_pv_src` was
        drawn from settles all three parts of the key at once."""
        path = self._pv_cache.get(key)
        return bool(path and self._pv_src
                    and os.path.abspath(self._pv_src[0])
                    == os.path.abspath(path))

    def _show_cached(self):
        """The highlight or the frame moved: show that frame if it is
        already rendered, and if it is not, SAY SO and ask for it.

        Doing nothing (which is what a cache miss used to do) left the
        control looking broken and the caption describing the frame still
        on screen - which was not the one the tab now named."""
        key = self._current_key()
        if key is None:
            return
        path = self._pv_cache.get(key)
        if path:
            if not self._on_screen(key):
                self.load_frame(path, key[1], key[2],
                                self._pv_totals.get(key[:2]))
            return
        if self._play_var.get():
            return                          # Play draws its own frames
        # ...and it only says 'drawing it' when one really is coming: the
        # first render after a restore is held (see _pv_idle), so an ask
        # that is about to be swallowed must not be reported as a promise.
        coming = self.schedule_preview() and not self._pv_idle
        # SHORT WHEN IT IS NOT COMING.  There is no menu to send anyone to
        # any more, and the strip is one line: a frame nobody is drawing is
        # a fact, not an instruction.
        self._pv_say("%s frame %d %s"
                     % (self._image_label(key[1]), key[2],
                        "is being drawn…" if coming else
                        "has not been drawn yet."))

    def _highlight(self, form):
        """The highlighted image as an index into the form, or None (said)."""
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

        KEPT ONCE DECODED, which is what makes Play smooth: every step used
        to re-read the PPM and re-scale it, so a 10 fps animation was ten
        file reads and ten LANCZOS resizes a second for as long as it ran.
        The cache is by path - the file NAME carries the form, the image and
        the frame (see :func:`frame_path`), so two forms can never share an
        entry - and it is emptied whenever the box changes size (they are
        the wrong size then) or the selector writes that frame again.

        Tk's own PhotoImage halves and thirds and nothing between, which is
        why the box used to be a whole fraction of the selector's frame;
        with Pillow the picture simply takes the width the window gives it.
        The fallback below is that older path, for a machine with no
        Pillow."""
        hit = self._pv_photos.get(os.path.abspath(path))
        if hit is not None:
            return hit
        photo = self._decode_photo(path)
        if photo is not None:
            self._keep_photo(path, photo)
        return photo

    def _keep_photo(self, path, photo):
        """Remember a decoded frame, oldest out first past
        :data:`PHOTO_CACHE_MAX` - one animation's worth, which is the whole
        working set (Play only ever walks one image's)."""
        key = os.path.abspath(path)
        if key not in self._pv_photos:
            self._pv_photo_order.append(key)
        self._pv_photos[key] = photo
        while len(self._pv_photo_order) > PHOTO_CACHE_MAX:
            self._pv_photos.pop(self._pv_photo_order.pop(0), None)

    def _drop_photo(self, path):
        """Forget one decoded frame - its file has just been written again
        (or taken away), so what is in memory is no longer what is on
        disk."""
        key = os.path.abspath(path)
        if self._pv_photos.pop(key, None) is not None:
            try:
                self._pv_photo_order.remove(key)
            except ValueError:                          # pragma: no cover
                pass

    def _drop_photos(self):
        """Forget every decoded frame - the box is a different size, so all
        of them are scaled wrong."""
        self._pv_photos = {}
        self._pv_photo_order = []

    def _decode_photo(self, path):
        """Read one P6 PPM off disk and scale it into the box.  The slow
        half of :meth:`_scaled_photo`, and the half that is done once."""
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
        # ...and the card in the picture is the card in the words: the
        # amber frame above says IMAGE 2, so this says Image 2 (see
        # :meth:`_image_label`).
        caption = "Image ?: %s" % what if highlight is None \
            else "%s: %s" % (self._image_label(highlight), what)
        # Not while Play is running: the caption is rewritten at the clip's
        # own rate there, a note riding one of those frames would flash past
        # unread, and working out whether there is one to say costs a look
        # at media.json.  It waits for the animation to stop.
        self._pv_say(caption, note=("" if self._play_var.get()
                                    else self._sound_suffix()))
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

    def _cancel_preview(self):
        """Take back a queued re-render.  Every field's trace asks for one
        and so does :meth:`_refresh_tree`, so the callers that must draw
        NOTHING have to say so after they have filled the form in - see
        :meth:`restore_state`."""
        job, self._pv_debounce_job = self._pv_debounce_job, None
        self._pv_pending = 0
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):           # pragma: no cover
                pass

    def _auto_render(self):
        """The debounce fired: render the frame the tab is pointing at, if
        there is anything to draw and nothing else is running.

        It CANCELS rather than forgets, because this is a seam the tests
        call directly: dropping the id of a job that is still armed leaves
        it to fire into a torn-down interpreter."""
        self._cancel_preview()
        if self._stopped or not self._auto_preview.get():
            return False
        if self._pv_idle:
            self._pv_idle = False       # the restore's own echo - see there
            return False
        if self._play_var.get():
            # PLAY DRAWS ITS OWN FRAMES - unless the form has moved out from
            # under them, and then this is where that is noticed.  The tick
            # notices it too, but the tick now waits a whole frame of the
            # clip (up to 2 s), while this debounce has already fired at 350
            # ms and used to THROW THE RENDER AWAY: an edit made during a
            # slow animation left the preview stopped on the old picture,
            # with nothing queued and nothing coming.
            if preview_fingerprint(self.form()) == self._play_fp:
                return False
            # Stopped here rather than through _form_moved_under_play: this
            # IS the redraw that method would have to ask for.
            self._stop_play("The form changed - redrawing…", error=False)
        if self._busy or self._pv_busy:
            # Try again once the run in flight is done - a build takes
            # minutes and the preview must not queue behind every keystroke.
            self.schedule_preview()
            return False
        # A DEAD DRIVE MUST NOT FREEZE THE TAB, AND THIS IS ABOVE form()
        # BECAUSE form() IS ONE OF THE STATS.  Every disk call in here runs
        # on the Tk main loop and can block for tens of seconds on an
        # unplugged mapped drive or a sleeping share, the debounce fires
        # them on every typing pause - and form() -> media_dir() ->
        # isfile(media.json) is the FIRST of them, so a guard underneath it
        # had already paid the freeze it was written to prevent.  The path
        # is therefore read straight out of the box here, which is what the
        # probe's answer is keyed on anyway.  Every other guard below stays
        # exactly as it is: they already handle a half-typed path correctly.
        out = self._out_var.get().strip().strip('"')
        if (self._rows and out
                and self._facts_now(out).get("kind") == "unreachable"):
            self._pv_stale("%s is not there right now"
                           % (path_root(out) or "that drive"))
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
            if not self._on_screen(key):
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
        frame the preview points at, whether or not it is cached.

        ASKED FOR, so the restore's one-render hold does not apply."""
        self._pv_idle = False
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
        worker: ensure a selector, prepare the media, then draw.  Each
        finished frame lands in the cache; the one the controls point at is
        shown at once (Play shows its own from the tick).  False when the
        busy guard refused.

        ONE FRAME IS ONE RUN; SEVERAL ARE STILL ONE RUN.  A snapshot spends
        its time LOADING - every PNG, every GIF, the font, the media
        directory - and almost none of it drawing, so a frame-at-a-time
        animation paid that load once per frame: 16 frames measured 1334 ms
        as sixteen runs and 243 ms as one ``--frames 16``, for byte-identical
        PPMs.  So a run of frames is asked for as a run, the selector fills
        the frame number into a :func:`frame_pattern`, and which frames it
        actually wrote is read back off its own log (it wraps at the
        animation's length and trims K to it).

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
        # ...AND WHETHER THE SOUNDS WERE RENDERED WITH IT.  A preview-only
        # prepare is half a media set (--visual-only: the pictures and the
        # music, not the two menu sounds), so 'prepared' is not one answer
        # but two - and with Sound ticked the whole set is what was asked
        # for.  Without this third field, ticking Sound after a render left
        # the tab certain the media was ready and the move sound absent.
        sound = bool(self._sound_var.get())
        if self._pv_ready != (mfp, media, sound):
            if self.needs_prepare(form):
                cmds += (prepare_commands(form, media) if sound
                         else preview_prepare_commands(form, media))
            else:
                # The card's own media, straight out of the extraction: it
                # matches the form because the form came out of the card,
                # sounds and all.
                self._pv_ready = (mfp, media, True)
        wanted = [int(n) for n in frames] or [0]
        # A run of more than one is ONE step, and never longer than the most
        # an animation can hold: past that the selector refuses the whole
        # command (exit 2) rather than trimming, and a refusal draws nothing.
        run = min(len(wanted), PREVIEW_MAX_FRAMES) if len(wanted) > 1 else 1
        first = wanted[0]
        ppm = (frame_pattern(pv, fp, hl) if run > 1
               else frame_path(pv, fp, hl, first))

        def argv(texts):
            binary = parse_selector_path(texts.get("selector", "")) \
                or self._pv_bin
            if not binary:
                raise RuntimeError("the selector step named no binary")
            return snapshot_commands(binary, conf, media, ppm, hl, first,
                                     rootfs, frames=run)[0][1]
        draw = ANIM_LABEL if run > 1 else "frame %d" % first
        cmds.append((draw, argv))

        def keep(n, total):
            """One drawn frame: cached under this form, and the picture in
            memory dropped - that file has just been written again.

            THE FRAME NUMBER NAMES THE FILE, never the path the selector
            echoed.  ``preview_snapshot_args`` hands the tool ``wsl(ppm)``,
            so on Windows every ``snapshot: …`` line it prints back reads
            ``/mnt/c/…`` - a path no Windows call can open.  Caching those
            left Play unable to load a single frame of a run it had just
            drawn correctly, keyed the photo cache and the eviction sweep
            on names nothing else in the tab uses, and it did none of it on
            a Linux desktop, where ``wsl()`` is the identity.  So the run
            is still READ BACK for which frames it wrote (the selector
            decides that, and says so per file) and the name is built here
            out of the same rule the pattern carries."""
            path = frame_path(pv, fp, hl, n)
            self._pv_totals[(fp, hl)] = total or 1
            self._pv_cache[(fp, hl, n)] = path
            self._drop_photo(path)
            return path

        def step(label, rc, text):
            if rc != 0:
                return
            if label == "selector":
                self._pv_bin = parse_selector_path(text)
                self._pv_bin_at = time.time()
            elif label == "prepare":
                self._pv_ready = (mfp, media, sound)
            elif label == ANIM_LABEL:
                # WHICH frames a run wrote is the selector's decision, and
                # it says so once per file: the caller knows the pattern,
                # the selector knows what it filled into it.  Only the
                # NUMBER is taken from it - see keep().
                for _echoed, n, total in parse_snapshot_frames(text):
                    keep(n, total)
            elif label.startswith("frame "):
                total = parse_anim_frames(text, hl)
                keep(first, total)
                key = self._current_key()
                if not self._play_var.get() and key == (fp, hl, first):
                    self.load_frame(ppm, hl, first, total or 1)

        def done(rc, failed, _texts):
            if rc == 0:
                if not self._play_var.get():
                    key = self._current_key()
                    if key in self._pv_cache and not self._on_screen(key):
                        self.load_frame(self._pv_cache[key], key[1], key[2],
                                        self._pv_totals.get(key[:2]))
                # A prepare may just have put this image's music there.
                self._sound_follow()
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
            self._drop_photo(path)
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
            self._stop_play("%s has no animation to play."
                            % self._image_label(hl))
            return
        self._play_fp, self._play_hl = fp, hl
        # THE WHOLE RUN, NOW, so pressing Play is all pressing Play takes:
        # the frames are drawn in one selector run and the ticks below only
        # ever show what is already in hand.
        self._play_run(form, fp, hl, total)
        self._schedule_tick(0)

    def _play_run(self, form, fp, hl, total):
        """Make sure this image's WHOLE animation is drawn, in ONE run.

        The count is not known before the first one - so ask for the most an
        animation can have (:data:`PREVIEW_MAX_FRAMES`) and let the selector
        trim it to what this image really has; it says which frames it wrote
        and how many there were.  False when there was nothing to ask for,
        or when something else has the worker."""
        want = int(total) if total else PREVIEW_MAX_FRAMES
        if all((fp, hl, n) in self._pv_cache for n in range(want)):
            return False
        if self._busy or self._pv_busy:
            return False                # the next tick asks again
        return self._render_frames(form, hl, list(range(want)))

    def _anim_delay_ms(self, hl):
        """The rendered clip's own per-frame delay for image *hl*, or None.

        ``anim<N>.gif`` in the media directory is the file the preview's
        own conf names (:func:`write_preview_conf`) and therefore the file
        the selector loads, so it is the one whose delays the picture is
        ticking on.  Kept against its stat the way media.json is: Play asks
        once a frame and must not re-read a GIF ten times a second."""
        media = self.media_dir()
        if not media:
            return None
        path = os.path.join(media, "anim%d.gif" % int(hl))
        try:
            st = os.stat(path)
            key = (path, st.st_mtime, st.st_size)
        except OSError:
            self._anim_ms_at = ((path, None, None), None)
            return None
        if self._anim_ms_at[0] != key:
            self._anim_ms_at = (key, gif_period_ms(path))
        return self._anim_ms_at[1]

    def _play_ms(self, hl, total=None):
        """How long one frame stays up: THE RENDERED CLIP'S OWN RATE.

        Not the row's FPS field, which is a REQUEST: selectmedia clamps it
        to fit 30 frames and shrinks it again to fit the byte budget, so a
        row asking 25 fps is normally a 10 fps clip and playing it at 40 ms
        runs the preview two and a half times too fast.  The GIF's own
        delay settles it, and the run's frame count is the fallback (see
        :func:`anim_period_ms`)."""
        if not 0 <= hl < len(self._rows):
            return self.PLAY_MS
        return anim_period_ms(self._rows[hl], frames=total,
                              delay_ms=self._anim_delay_ms(hl))

    def _schedule_tick(self, ms=None):
        if self._play_job is not None:
            return
        try:
            self._play_job = self._timer().after(
                self.PLAY_MS if ms is None else ms, self._play_tick)
        except tk.TclError:
            pass

    def _play_tick(self):
        """One step of Play: the next frame, out of memory, at the clip's
        own rate.  Stops when the form no longer matches the frames or a
        render fails; asks for the run again when a frame is missing (the
        first ticks after Play, while the selector is still drawing)."""
        self._play_job = None
        if self._stopped or not self._play_var.get():
            return
        form = self.form()
        fp = preview_fingerprint(form)
        if fp != self._play_fp:
            self._form_moved_under_play()
            return
        hl = self._play_hl
        total = self._pv_totals.get((fp, hl))
        if total is None:
            # Nothing drawn yet: the run is on the worker, or waiting for it.
            self._play_run(form, fp, hl, None)
            self._schedule_tick()
            return
        if total < 2:
            self._stop_play("%s has no animation to play."
                            % self._image_label(hl))
            return
        cur = _int(self._frame_var, 0)
        nxt = (cur + 1) % total
        key = (fp, hl, nxt)
        if key in self._pv_cache:
            self.load_frame(self._pv_cache[key], hl, nxt, total)
        else:
            self._play_run(form, fp, hl, total)     # a gap: fill the run
        self._schedule_tick(self._play_ms(hl, total))

    def _form_moved_under_play(self):
        """The form no longer matches the frames Play is showing: stop, and
        SAY WHAT HAPPENS NEXT.

        Not an error - editing while an animation runs is an ordinary thing
        to do - and never a dead end: the redraw is asked for here, so the
        picture follows the form again by itself.  It names no control,
        because there is none to name: the picture redraws itself."""
        self._stop_play("The form changed - %s"
                        % ("redrawing…" if self.schedule_preview()
                           else "the picture is out of date."),
                        error=False)

    def _stop_play(self, msg, error=True):
        self._play_var.set(False)
        if self._play_job is not None:
            try:
                self._timer().after_cancel(self._play_job)
            except (tk.TclError, ValueError):
                pass
            self._play_job = None
        if msg:
            self._pv_say(msg, error=error)
        elif self._pv_src:
            # The picture stopped on a real frame, so the caption says
            # which one instead of going on claiming to be playing.  Out of
            # memory: the frame it is describing is the one already up.
            self.load_frame(*self._pv_src)

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
        table = getattr(self, "_table", None)
        if table is not None:
            table.set_busy(busy)        # the row icons must not act mid-run
        for btn in list(getattr(self, "_action_btns", ())):
            if btn is None:
                continue
            try:
                btn.configure(state=tk.DISABLED if busy else tk.NORMAL)
            except tk.TclError:
                pass
        if not busy:
            # Greyed for good, not just for the run: a panel built without
            # the app has nowhere to run the card.  (Flashing lives in the
            # Build / flash modal now, whose flash tick refuses on its own
            # when _flash_fn is None, so there is no flash BUTTON to grey.)
            btn = getattr(self, "_emu_btn", None)
            if self._emulate_fn is None and btn is not None:
                try:
                    btn.configure(state=tk.DISABLED)
                except tk.TclError:
                    pass
        if not busy:
            # THE RUN MAY HAVE MOVED THE DISK UNDER THE ROW.  A build writes
            # the card the row was calling missing, an apply changes it, a
            # load that failed may have taken a directory away - and the row
            # reads a CACHED stat, so without this it went on describing the
            # state before the run for ever.
            self._refresh_facts()
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
