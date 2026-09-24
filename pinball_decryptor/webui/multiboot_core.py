"""Multi-boot tab - one Spike 2 SD card (or one JJP install ISO), several
game images, a menu at power-up (item 90), set up and built from the app.

THIS MODULE HAS NO TK IN IT.  It is the Multi-boot tab's logic: the form,
the pure command builders, validation, the size check, the write plan, the
preview pipeline, the sounds, and :class:`MultibootPanel`, the state machine
behind the tab's buttons.  It was ``gui/multiboot_tab.py`` less every widget
and every Tk dialog; the page (:mod:`.multiboot_panel` and
``tabs/multiboot.py``) is what paints it and what stands in for the dialogs.
The Tk variables the panel keeps are :mod:`.compat`'s, and the few ``tk.``
names the logic still spells (``tk.StringVar``, ``tk.TclError``,
``tk.DISABLED``...) come from the Tk-free :data:`tk` namespace below.

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
loads natively.  EVERY card's animation then plays over that ONE rendered
frame, all the time - there is no Play to press (David, 2026-09-03: "all
boot selections should play video at the same time all the time", "sound
and video should always be on for the preview"): the selector says where
in the frame it blitted each animated card's picture (``pictures
i:x,y,w,h;...`` on its snapshot line), and the tab lays each rendered
GIF's own frames there on one shared clock - the GIF is what the machine
decodes into that very rectangle, so the pixels are the machine's,
without a 3 MB PPM per frame (a 5 s clip is 150 of them).  The menu's
sounds play the same way, always: the highlighted card's music, the move
sound on a flipper, the confirm on Select.  The pictures and the sounds
are rendered by two separate tool runs, and the strip says which of the
two is still loading (Video: / Audio:).
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
image's music bed, the move click on a flipper press (never over itself,
as on the card), and - from the
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
``bypass`` while a games tree is still armed) - seconds, no copy.
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

import bisect
import errno
import hashlib
import io
import json
import ntpath
import os
import queue
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
from dataclasses import (asdict, dataclass, field, fields as dc_fields,
                         replace)

from ..core import config, runtime
from . import compat
from . import rig as _rig
from . import multiboot_docker as _mac
from .emulate_core import rig_dir, wsl_account, wsl_home
from . import preview_audio
from .preview_audio import PreviewAudio
from .theme import THEMES
# THE PLATFORMS (item 118): what this module hard-coded for the Stern card,
# gathered per manufacturer so the same tab builds a JJP multi-boot install
# ISO.  Every builder below takes its backend from the form (``platform``),
# the panel from the manufacturer the app switched to, and the default is
# Stern - so every argv the Stern tests pin is unchanged.
from pinball_decryptor.webui.multiboot_backend import JJP, backend_for

#: Where the JJP builder keeps its scratch (a loop-mounted copy of root A, the
#: re-imaged pieces): a Linux path, never beside the output on a Windows drive.
JJP_WORKDIR = "/var/tmp/pad_jjpmulti_work"

# Pillow reads the preview's frames and the pictures the owner picks.  It
# is a hard dependency of the app, but the guard keeps the module importable
# if it is ever missing (the clips then stay still).
try:
    from PIL import Image
    _HAVE_PIL = True
except ImportError:                                     # pragma: no cover
    _HAVE_PIL = False


class TclError(Exception):
    """The error the ``except tk.TclError`` clauses name.  Nothing here
    raises it (a :mod:`.compat` variable never does); the clauses are kept
    as they were so the logic reads as it did under Tk."""


#: THE TK NAMES THE LOGIC STILL SPELLS, without Tk: the variable classes are
#: :mod:`.compat`'s (the page mirrors them), and the state / anchor words are
#: the strings Tk's constants were.  Everything that would have built a
#: widget is gone from this module.
tk = types.SimpleNamespace(
    StringVar=compat.StringVar, BooleanVar=compat.BooleanVar,
    IntVar=compat.IntVar, DoubleVar=compat.DoubleVar, TclError=TclError,
    NORMAL="normal", DISABLED="disabled", CENTER="center", X="x",
    LEFT="left", RIGHT="right", W="w", EW="ew", END="end")

#: The panel's questions and pickers: the page's (:mod:`.compat`).  The web
#: panel rebinds these names to its own (see :mod:`.multiboot_panel`).
messagebox = compat.messagebox
filedialog = compat.filedialog

#: The tools, relative to the checkout root the command line cd's into.
TOOL_DIR = "tools/spike2_emu"
MKMULTICARD = TOOL_DIR + "/mkmulticard.py"
SELECTMEDIA = TOOL_DIR + "/selectmedia.py"
CODESELECT_SRC = TOOL_DIR + "/codeselect"
#: The rig script that makes sure the menu program is INSTALLED where
#: ``--selector-dir`` looks - ensurebuild.sh's own rules, called rather than
#: copied (see :func:`install_selector_line`).
ENSURESELECT = TOOL_DIR + "/ensureselect.sh"
#: THE MENU'S COLOUR THEMES: the selector's own themes.json, one definition -
#: the selector compiles it in, mkmulticard.py writes the keys, this tab shows
#: the picker and the "make your own" colour grid.  Read once, on first use,
#: never at import: a checkout without it must not stop the app; the picker
#: says so and the default theme still draws.
THEMES_JSON = CODESELECT_SRC + "/themes.json"
DEFAULT_THEME = "midnight"
CUSTOM_THEME = "custom"
CUSTOM_TITLE = "Make your own…"

#: A selector build's home INSIDE the rootfs it was built against - the one
#: place buildselect.sh installs to, the one place the machine carries it,
#: and what tells :func:`rootfs_for` a directory is a rootfs's own.
SELECTOR_SUFFIX = "/usr/local/codeselect"

#: Where the rig installs the ARM selector (buildselect.sh's ``make install
#: DESTDIR=$ROOT``, ROOT = PAD_ROOT else ~/spike2root).  A WSL path, spelled
#: with ``~`` on purpose: the app cannot know the WSL user's home without a
#: probe, and ``~/`` is expanded by bash without a ``$`` for wsl.exe to eat.
DEFAULT_SELECTOR_DIR = "~/spike2root" + SELECTOR_SUFFIX

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

#: THE LINE ACROSS THE TOP OF THE MENU, as the selector draws it when no card
#: asked for anything else - codeselect.c's DEF_HEADING and mkmulticard.py's
#: copy of it, kept in step by name.  It is this tab's DEFAULT rather than a
#: fallback: the form always shows what the card will actually say, so the
#: field reads SELECT GAME CODE on a card nobody has retitled and empty only
#: when somebody meant the top of the menu to be bare.
DEF_HEADING = "SELECT GAME CODE"
#: ...and how much of it the selector's field holds (conf.h's CONF_STR - 1).
HEADING_MAX = 199

#: HOW BIG THE CARDS' TEXT IS DRAWN - images.conf's ``text_size=`` (PAD-183),
#: the two words mkmulticard.py's TEXT_SIZES holds and the selector reads.
#: ``uniform`` is one size for the whole menu, measured over every card;
#: ``per-card`` lets each card fit its own title, which is what every menu did
#: before the key existed.
TEXT_SIZE_UNIFORM = "uniform"
TEXT_SIZE_PER_CARD = "per-card"

#: WHETHER THE CARD COUNTER IS DRAWN - images.conf's ``counter=`` (PAD-190), the
#: two words mkmulticard.py's COUNTERS holds.  The "<  3 / 7  >" line under the
#: cards, which only a carousel (five cards or more) has at all.
COUNTER_ON = "on"
COUNTER_OFF = "off"

#: THE FIRST WORD OF THE COUNTDOWN LINE - images.conf's ``countdown_word=``, and
#: codeselect.c's DEF_COUNTDOWN_WORD.  This tab's DEFAULT rather than a fallback,
#: on DEF_HEADING's rule: the field always names the word the card will say, and
#: reads empty only when somebody meant the countdown to have no word at all.
DEF_COUNTDOWN_WORD = "starting"
#: ...and how much of it the selector's field holds (conf.h's CONF_STR - 1).
COUNTDOWN_WORD_MAX = 199

#: THE INSTRUCTIONS LINE UNDER THE CARDS - images.conf's ``footer=`` (BEN,
#: Discord, PAD-190 round 2: "can you extend this to make the instructions also
#: customizable and/or visible?").  THREE answers, which is why the form needs
#: two fields for it: no key at all = the selector's own wording, and only that
#: one follows the buttons a machine HAS (a lockdown-bar Action button is named
#: only where one is wired); text = those words on every machine; '' = no line.
#: The field is EMPTY for the selector's own - unlike the heading, this tab
#: cannot show what the card will say, because that depends on the machine.
FOOTER_MAX = 199

#: David's card library - never an output (mkmulticard.py refuses the same
#: prefixes after resolving links; the repo's own images/ is a junction into
#: it).  Both spellings, because the form holds Windows paths and the tool
#: sees WSL ones.  tests/test_multiboot_tab.py pins this to the tool's list.
LIBRARY_PREFIXES = ("D:/Pinball/images", "/mnt/d/Pinball/images")

#: images.conf v2 carries up to 16 images.
#: WHAT THE PLAYER SCROLLS THROUGH: one per table row.  A row that carries
#: members is a GROUP card - several games behind one card, which boots a
#: different one of them every power-up (item 106) - so rows and games stopped
#: being the same number.  Both must match mkmulticard's MAX_CARDS / MAX_IMAGES
#: and conf.h's CONF_MAX_CARDS / CONF_MAX_IMAGES.
MAX_IMAGES = 16
MAX_CARDS = 16
#: ...and the games (trees) behind them.  A jukebox of forty song-set variants
#: is forty trees and one row.
MAX_TREES = 64
MAX_GROUPS = 8

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
#: .webm and .flv (item 120): what PAD extracts from a JJP game - 629 of GNR's
#: 648 clips are VP9 .webm - so a JJP image can play one of its own game's
#: clips; ffmpeg reads both, and selectmedia.VIDEO_EXTS must match this.
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv")

#: What a loop plays at until its GIF is there to read - selectmedia.py's
#: GIF_MAX_NATIVE_FPS, the most a source's own rate is rendered at.  The
#: loop's length and rate are the TOOL's contract (up to 5 s at the
#: source's own frame rate); the form never asks for either (David,
#: 2026-09-03: "run at original fps (minimum 30fps would be ideal). we can
#: limit them to 5 second clips").
ANIM_FPS = 30

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
#: Play's fallback rate, before a clip's own delays are read.
PREVIEW_FPS = ANIM_FPS

#: The most frames one snapshot run may be asked for - codeselect.c's
#: ANIM_MAX_FRAMES (5 s at 30 fps), which is both the number of frames an
#: animation is read for and the largest ``--frames`` it accepts (a bigger
#: K is refused, exit 2).  Play no longer asks for a run (it lays the GIF
#: over frame 0 - see the module docstring); the Frame spinbox and a
#: caller of :meth:`MultibootPanel._render_frames` still may.
PREVIEW_MAX_FRAMES = 150

#: How many DECODED frames the preview keeps in memory.  A frame FILE is
#: cheap to remember (a path in a dict); a frame scaled into a PhotoImage
#: is ~1 MB of RGBA at the sizes this tab draws at.  Play walks the GIF,
#: not these, so a few stills and the frames a spinbox visited is the
#: whole working set.
PHOTO_CACHE_MAX = 32

#: How long the preview waits after the last keystroke before it re-renders.
#: Every change inside the window is one render, not N.
PREVIEW_DEBOUNCE_MS = 350

#: How long the card-image PROBE waits before asking about the text that was
#: just typed.  The same 350 ms, and deliberately its OWN constant: these are
#: two unrelated waits that happened to want the same number, and sharing one
#: knob meant neither could be moved without moving the other - which is how a
#: test that pushes the preview debounce out of reach (so it can drive it by
#: hand rather than race it) also silenced the probe it was still waiting for.
PROBE_DEBOUNCE_MS = 350

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

#: ...and what the CARD's own selector step (:func:`install_selector_line`)
#: prints in front of the directory the builder will take the menu out of.
#: The rig script prints the same line - tests/test_multiboot_tab.py holds
#: the two spellings together.
SELECTOR_READY_LINE = "[selector] menu program:"
#: How that step spells a refusal.  A refusal prefix
#: (:data:`_REFUSAL_PREFIXES`), so a run that stops there says the sentence
#: rather than an exit code.
SELECTOR_ERROR = "[selector] error:"

#: THE PREVIEW'S OWN VOLUME AND MUTE (David, 2026-09-03: "a volume slider
#: with mute button next to the preview tab so I can mute the audio if I
#: need to. Use the same volume slider interface that we have in the
#: emulator tab") - the Emulate tab's knob, its own file: this is the
#: PC-side level of the preview, not the menu's ``volume=`` (which goes on
#: the card and stays what media.json says).  Shape {"gain": 0-1,
#: "muted": bool}, beside settings.json like the emulator's audio_ctl.json.
PREVIEW_AUDIO_CTL_FILE = os.path.join(os.path.dirname(config.SETTINGS_FILE),
                                      "preview_audio_ctl.json")


def load_preview_ctl(path=None):
    """``(gain, muted)`` as remembered; unity and unmuted for a machine that
    has never touched the knob."""
    try:
        with open(path or PREVIEW_AUDIO_CTL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        gain = float(data.get("gain", 1.0))
        muted = bool(data.get("muted", False))
    except (OSError, ValueError, TypeError, AttributeError):
        return 1.0, False
    return max(0.0, min(1.0, gain)), muted


def write_preview_ctl(gain, muted, path=None):
    """Remember the knob (atomic: temp + replace).  Never raises - a knob
    that cannot be remembered still works for the session."""
    path = path or PREVIEW_AUDIO_CTL_FILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"gain": gain, "muted": muted}, f)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


#: What the step that draws a WHOLE animation is called - in the log pane,
#: in 'Preview failed at …', and in the render's own bookkeeping.  A single
#: frame keeps its own 'frame N' label: they are read back differently
#: (see :meth:`MultibootPanel._render_frames`).
ANIM_LABEL = "animation"

#: The two halves of the preview's media, as the runs that render them are
#: labelled in the Log and as the strip names them: the pictures (art +
#: animations + music beds, ``prepare --visual-only``) and the sounds (the
#: full prepare, which pulls the move and confirm sounds off the card).
VIDEO_LABEL = "video"
AUDIO_LABEL = "audio"


# ---------------------------------------------------------------------------
# the form
# ---------------------------------------------------------------------------

@dataclass
class MemberRow:
    """One game inside a GROUP row (item 106).  It is a whole games tree on the
    card, exactly like a plain row's, and it gets its own image= line - what the
    group adds is a single card drawn in front of several of them.  It carries
    no media of its own: the card does, and there is one card."""
    path: str
    title: str = ""
    #: read off the .raw, never typed - the same rule as ImageRow.version
    version: str = ""


@dataclass
class ImageRow:
    """ONE CARD in the menu.  Index 0 is the primary (its p1/p2/p3/p5/p6 are
    the card's; the machine boots it when the menu is not honoured).

    A row with `members` is a GROUP card: it draws one picture and one title,
    and confirming it boots one of its members at random, a different one every
    power-up.  Its own `path` is then unused - the members are the games."""
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
    #: Seconds into the clip the loop starts at (blank = 0).  The loop's
    #: LENGTH and RATE are not fields any more: they are the tool's own
    #: contract (up to 5 s at the source's own frame rate, 30 fps at
    #: most), and a row carrying a length and a rate of its own was how a
    #: 13 s / 30 fps ask reached selectmedia and came back as 2 fps
    #: (David, 2026-09-03) - long after the controls that set them were
    #: gone from the dialog.
    anim_start: str = ""
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
    #: A GROUP card's games (item 106).  Empty = an ordinary row, which is
    #: every row that existed before this field did.  default_factory, not
    #: [], because a mutable default is shared by every instance.
    members: list = field(default_factory=list)
    #: ...and whether those games ALSO keep cards of their own, so the menu
    #: offers them beside the random one (David, 2026-09-10: "what if i want
    #: RANDOM|CUSTOM1|CUSTOM2?").  False = the group swallows them, which is
    #: the forty-variant jukebox and stays the default.
    keep: bool = False
    #: HOW IT PICKS: one of ROLL_MODES.  "" reads as the card's own default,
    #: which is what a card built before there was a choice does.
    roll: str = ""


#: HOW A RANDOM CARD PICKS (David, 2026-09-11: "so is it truly random if it is
#: remembering the last choice? ... We should make it truly random instead i
#: think. and make it an option ... to change it to a 'shuffle' type (like
#: perceived random like ipod)").  ``(mode, label)`` in the order the dialog
#: offers them.  THE DIALOG NO LONGER OFFERS THEM ONE FOR ONE: it asks two
#: questions whose answers spell one of these words - see ROLL_DRAWS.
ROLL_MODES = (
    ("any", "Truly random - it can give you the same one twice"),
    ("shuffle", "Shuffle - every game once before any repeats"),
    ("not-last", "Never the one it booted last"),
)
#: What a NEW random card does, which is what the word says on the tin.
ROLL_DEFAULT = "any"
#: ...and what a card with no rule on it does, which is what every card built
#: before there was a choice did.  The two differ on purpose: a card already in
#: the world must not change under its owner, and a new one should do the
#: obvious thing.
ROLL_FALLBACK = "not-last"
ROLL_NAMES = tuple(m for m, _label in ROLL_MODES)

#: ...AND THE TWO QUESTIONS THE DIALOG ASKS INSTEAD (BEN, Discord @ben01434,
#: PAD-185: "Should the last option be a checkbox that would be applied to one
#: of the two options above (Truly random and Shuffle). The last option by
#: itself does not make sense to stand on its own").  He is right, and the
#: three words above were never three peers: there are two ways of DRAWING -
#: the dice, or a deck dealt out - and "never the one it booted last" is not a
#: third one, it is a rule laid over whichever of them was chosen.  So the box
#: is two radio buttons with a tick under them, and the pair spells one of the
#: words a card carries:
#:
#:     any     + tick off  ->  "any"
#:     any     + tick on   ->  "not-last"
#:     shuffle             ->  "shuffle"
#:
#: A shuffle has no say in the tick because it answers it already: a deck
#: never deals the same one twice running (codeselect roll_member, which had
#: to be told that about a KEEPING group's members too).  So the tick is shown
#: ON and greyed there rather than hidden - the rule still holds, and a box
#: that vanished would say it did not.
ROLL_DRAWS = (
    ("any",
     "Truly random - 100% random, so it can give you the same one twice"),
    ("shuffle",
     "Shuffle - cycle through every game before any of them repeats"),
)
ROLL_DRAW_NAMES = tuple(d for d, _label in ROLL_DRAWS)
#: The tick under them, which is the third radio button's own words.
ROLL_REPEAT_LABEL = "Never the one it booted last"


def row_roll(row):
    """How a random card picks, as one of :data:`ROLL_NAMES`."""
    v = (getattr(row, "roll", "") or "").strip().lower()
    return v if v in ROLL_NAMES else ROLL_FALLBACK


def roll_label(mode):
    for m, label in ROLL_MODES:
        if m == mode:
            return label
    return mode


def roll_draw(mode):
    """Which of :data:`ROLL_DRAWS` *mode* draws by - the radio button it is."""
    return "shuffle" if mode == "shuffle" else "any"


def roll_no_repeat(mode):
    """Whether *mode* rules out the build the machine booted last - the tick.
    Only the dice can hand that one straight back."""
    return mode != "any"


def roll_repeat_locked(draw):
    """Whether the tick is *draw*'s own answer rather than a question: a deck
    dealt out never gives the same one twice running, so a shuffle cannot be
    asked to."""
    return draw == "shuffle"


def roll_from_parts(draw, no_repeat):
    """The word a card carries for a (radio button, tick) pair."""
    if draw == "shuffle":
        return "shuffle"
    return "not-last" if no_repeat else "any"


def is_group(row):
    """A row that stands for several games rather than one.

    THE LIST, not its truthiness.  A saved state used to put every non-bool row
    field through ``str()``, and ``str([]) == "[]"`` is a truthy STRING - so an
    ordinary row restored from a state file read as a group with one member
    called "[".  restore fills this field properly now (below), and this check
    is the belt: anything that is not a list of member rows is not a group."""
    members = getattr(row, "members", None)
    return isinstance(members, (list, tuple)) and len(members) > 0


def row_paths(row):
    """The .raw file(s) this row puts on the card, in image order: its own for
    a plain row, its members' for a group."""
    if is_group(row):
        return [(m.path or "").strip().strip(chr(34)) for m in row.members]
    return [(row.path or "").strip().strip(chr(34))]


def form_trees(form):
    """Every GAME the form will write, in image order:
    ``[(image_index, path, row_index, member_index_or_None), ...]``.

    THE TWO INDEX SPACES MEET HERE and nowhere else.  images.conf, the choice
    file, ``--titles`` and ``--art N=`` all count IMAGES; the table, the
    preview and ``--highlight`` count CARDS.  They are the same number until a
    group row makes them differ, and every bug this feature can have is a place
    that used one where it meant the other."""
    out = []
    seen = {}
    for ri, row in enumerate(form.images):
        if is_group(row) and row.keep:
            # A KEEPING GROUP ADDS NO GAMES.  Its members are games other rows
            # already put on the card, so they must not be counted twice - the
            # whole point is one card in front of trees that are already there.
            continue
        if is_group(row):
            for mi, path in enumerate(row_paths(row)):
                seen.setdefault(_norm(path), len(out))
                out.append((len(out), path, ri, mi))
        else:
            path = row_paths(row)[0]
            seen.setdefault(_norm(path), len(out))
            out.append((len(out), path, ri, None))
    return out


def group_member_images(form, row):
    """The IMAGE indexes a keeping group's members resolve to - the games other
    rows put on the card.  -1 for a member no row carries, which validate_form
    is what refuses."""
    where = {}
    for img, path, _ri, _mi in form_trees(form):
        where.setdefault(_norm(path), img)
    return [where.get(_norm(q), -1) for q in row_paths(row)]


def form_groups(form):
    """Every RANDOM card in the form, in the order its flags are written:
    ``[(group_index, row_index, row, [image indexes]), ...]``.

    THE GROUP INDEX IS A THIRD INDEX SPACE, after images and cards - it is the
    ordinal of the group among the groups, which is what ``--group-art G=`` and
    media.json's groups list both count, and what mkmulticard matches its own
    ``--group`` flags against BY POSITION.  All three are the same number on a
    card with one group at the top and none of them is on a card with two."""
    per_row = {}
    for img, _p, ri, mi in form_trees(form):
        if mi is not None:
            per_row.setdefault(ri, []).append(img)
    out = []
    for ri, row in enumerate(form.images):
        if not is_group(row):
            continue
        imgs = [i for i in group_member_images(form, row) if i >= 0] \
            if row.keep else per_row.get(ri, [])
        out.append((len(out), ri, row, imgs))
    return out


def card_media_names(form):
    """The media files each CARD's menu entry names, by row - a row IS a card.
    ``[(art, anim, music, confirm), ...]``, '' where the card has none.

    THE FILES ARE NUMBERED BY IMAGE AND THE CARDS ARE NOT.  `anim3.gif` belongs
    to the card in row 2 the moment a group above it swallows two images, which
    is why this is derived rather than assumed: the preview's conf, and the Play
    overlay that lays a GIF over the rendered frame, both need the card's file
    and had been asking for the card NUMBER's.  A random card's own picture is
    `gart<G>.png` / `ganim<G>.gif`, numbered by GROUP."""
    first = {}
    for img, _p, ri, _mi in form_trees(form):
        first.setdefault(ri, img)
    gi_of = {ri: gi for gi, ri, _row, _imgs in form_groups(form)}
    out = []
    for ri, row in enumerate(form.images):
        if is_group(row):
            gi = gi_of.get(ri, 0)
            art = (row.art or "").strip() if row.art_on_card else (
                "gart%d.png" % gi if group_art_spec(row) != "none" else "")
            anim = (row.anim or "").strip() if row.anim_on_card else (
                "ganim%d.gif" % gi if group_anim_spec(row) != "none" else "")
            music = (row.music or "").strip() if row.music_on_card else (
                "gmusic%d.wav" % gi if _media_value(row.music) != "none" else "")
            confirm = (row.confirm or "").strip() if row.confirm_on_card else (
                "gconfirm%d.wav" % gi if confirm_spec(row) != "none" else "")
        else:
            i = first.get(ri, 0)
            art = "art%d.png" % i if art_spec(row) != "none" else ""
            anim = "anim%d.gif" % i if anim_spec(row) != "none" else ""
            music = "music%d.wav" % i if _media_value(row.music) != "none" else ""
            confirm = "confirm%d.wav" % i if confirm_spec(row) != "none" else ""
        out.append((art, anim, music, confirm))
    return out


def drop_game_from_groups(rows, path):
    """A game leaving the card leaves every RANDOM card that rolled between
    them -> ``(rows, notes)``.

    A KEEPING group's members are games OTHER rows put on the card, so a row
    that goes takes its membership with it; a card left with fewer than two
    games to roll between is not a random card any more and goes as well.  A
    CONSUMING group owns its members outright - they are on no other row - so
    it is not touched here.

    Deleting a row used to leave the membership behind, and the only sign of it
    was the preview quietly refusing to redraw (David, 2026-09-11: "whenever i
    delete an image, i expect the preview to update with it").  Addition
    enforces these rules; deletion has to keep them.
    """
    key = _norm((path or "").strip().strip('"'))
    out, notes = [], []
    if not key:
        return list(rows), notes
    for row in rows:
        if is_group(row) and row.keep:
            left = [m for m in row.members
                    if _norm((m.path or "").strip().strip('"')) != key]
            if len(left) != len(row.members):
                name = (row.title or "").strip() or "The random card"
                if len(left) < 2:
                    notes.append("%s had nothing left to roll between, so its "
                                 "card went too." % name)
                    continue
                notes.append("%s rolls between %d game(s) now."
                             % (name, len(left)))
                row.members = left
        out.append(row)
    return out, notes


def row_first_image(form, row_index):
    """The image index a row's card stands on: its own, or its first member's.
    What ``--highlight`` (which names an IMAGE) is given for a table ROW."""
    for img, _p, ri, _mi in form_trees(form):
        if ri == row_index:
            return img
    # a KEEPING group puts no game on the card, so it has no image of its own;
    # its first member's is what names it
    rows = getattr(form, "images", None) or []
    if 0 <= row_index < len(rows) and is_group(rows[row_index]):
        imgs = [i for i in group_member_images(form, rows[row_index]) if i >= 0]
        if imgs:
            return imgs[0]
    return 0


def form_cards(form):
    """The menu's cards in order, as ``[(row_index, is_group)]`` - which is just
    the rows, because a row IS a card.  Here so the card-index arithmetic the
    conf needs has one home."""
    return [(ri, is_group(r)) for ri, r in enumerate(form.images)]


def row_card_index(form, row_index):
    """A row's CARD index, which is its row number - the two are the same thing
    and this says so where the conf's `default_card=` needs it."""
    return int(row_index)


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
    #: On the machine, play at ITS OWN volume setting - the coin-door MASTER
    #: VOLUME the owner set, read off the card's /data/nv mirror by the
    #: selector - rather than the number above (David, 2026-09-03: "it
    #: should follow the set volume of the actual machine").  The number
    #: is then only how loud the preview plays here.
    machine_volume: bool = True
    #: The compact layout (item 95, OPT-IN, default off - David: "it feels
    #: much riskier than what we already have"): ``--layout store`` stores
    #: every file the images have in common once.  Off = today's layouts,
    #: byte for byte what the tool made before the tick existed.
    compact: bool = False
    timeout: int = 15              # 0 = wait for START
    #: The line across the top of the menu (C FB, PAD-135: "Can there be an
    #: option to change this text?").  '' is a real answer and means no line at
    #: all, so the field always names what the card will say - the selector's
    #: own wording is the DEFAULT here rather than a hidden fallback, because a
    #: box that reads empty when the menu says SELECT GAME CODE is a lie.
    heading: str = DEF_HEADING
    #: SAME TEXT SIZE ON EVERY CARD (BEN, Discord, 2026-09-20: "is there a way
    #: to make the font size consistent across all images in a multiboot?").
    #: On - the selector's own default - the menu measures the title and the
    #: subtitle over every card and draws them all at the smallest any card
    #: needs; off lets each card fit its own, which is what the menu did before
    #: this existed.  Written out either way (``text_size=``), so the card says
    #: what it does rather than leaning on the selector's default.
    same_text_size: bool = True
    #: THE CARD COUNTER, the "<  3 / 7  >" line under the cards (BEN, Discord,
    #: 2026-09-21: "have an option to hide the '< x / y >' line").  On - the
    #: selector's own default - a carousel counts its cards under them; off
    #: takes the line off the glass.  Four cards or fewer never have one.
    show_counter: bool = True
    #: THE FIRST WORD OF THE COUNTDOWN LINE (same report: "have the option to
    #: change this text in case you want something like 'Launching' or
    #: 'Booting'").  '' is a real answer - the countdown is then "<title> in
    #: 9 s" with no word in front of it - so the field always names what the
    #: card will say, exactly as the heading does.
    countdown_word: str = DEF_COUNTDOWN_WORD
    #: THE INSTRUCTIONS LINE, as its two fields (see :data:`FOOTER_MAX`): the
    #: tick is whether the line is drawn at all, and the box is the words.  An
    #: EMPTY box with the tick on is "the menu's own wording", which is what
    #: every card has always had and what the tool writes no key for.
    show_footer: bool = True
    footer: str = ""
    default: int = 0
    # (No bypass field: the validator bypass is ALWAYS ON - build_args and
    # update_args pass it for every image.  David, after the TMNT booted
    # clean on both images: "we tested that this bypass works, we don't need
    # to make it optional. it should always be on now.")
    media_dir: str = ""            # a prepared media dir (holds media.json)
    selector_dir: str = DEFAULT_SELECTOR_DIR
    force: bool = False
    #: The menu's colours: a built-in theme's name, or ``custom`` with every
    #: role in ``colors`` (``{role: rrggbb}``; empty for a built-in).
    theme: str = DEFAULT_THEME
    colors: dict = field(default_factory=dict)
    #: WHICH PLATFORM this form is for (item 118): ``stern`` (the SD card,
    #: mkmulticard.py) or ``jjp`` (a multi-boot install ISO, mkjjpmulti.py).
    #: The command builders read it; a form that never says is a Stern one.
    platform: str = "stern"


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


def heading_args(form):
    """``--heading TEXT`` - always passed, never left off.  The form is the
    record of what the menu says, so a heading cleared here has to reach the
    card as ``heading=`` (no line) rather than as "the flag was absent, keep
    whatever is there"."""
    return ["--heading", (form.heading or "").strip()]


def text_size_args(form):
    """``--text-size uniform|per-card`` - always passed, on heading_args'
    rule: the form is the record of what the menu does, and a tick cleared
    here has to reach the card as the other word rather than as "the flag was
    absent, keep whatever is there"."""
    return ["--text-size", TEXT_SIZE_UNIFORM if form.same_text_size
            else TEXT_SIZE_PER_CARD]


def menu_text_args(form):
    """``--counter on|off``, ``--countdown-word TEXT`` and the instructions
    line's own flag (:func:`footer_args`) - the three lines under the cards the
    owner can change (PAD-190).  Always passed, on heading_args' rule: the form
    is the record of what the menu says, and a word cleared here has to reach
    the card as ``countdown_word=`` rather than as "the flag was absent, keep
    whatever is there"."""
    return (["--counter", COUNTER_ON if form.show_counter else COUNTER_OFF,
             "--countdown-word", (form.countdown_word or "").strip()]
            + footer_args(form))


def footer_args(form):
    """``--footer TEXT`` or ``--footer-own`` - the instructions line's THREE
    answers in the two flags the tools spell them with (PAD-190 round 2).

    The tick off is ``--footer ''`` (no line at all); the tick on with words in
    the box is those words; the tick on with an EMPTY box is ``--footer-own``,
    which takes the key off the card again so the selector draws its own line -
    the only form that can follow the machine's own buttons.  One of the three
    is always passed, on heading_args' rule: the form is the record of what the
    menu says."""
    if not form.show_footer:
        return ["--footer", ""]
    text = (form.footer or "").strip()
    return ["--footer", text] if text else ["--footer-own"]


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


def suggest_title(path, platform="stern"):
    """``turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw`` ->
    ``('turtles_pro-1_59_0', '1987-upscaled')``: the menu title and subtitle
    a fresh row starts with.  A suggestion, not a fact - the user renames.
    A JJP ISO's name is the whole title (``CHAKAs LOTLJ V1.0 GNR LE 3.03``)."""
    return backend_for(platform).suggest_title(path)


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def wsl(path):
    """A form path as the tools see it (``D:\\x`` -> ``/mnt/d/x``).

    On macOS the tools run in a container (:mod:`multiboot_docker`), so the
    same question has a different answer: a bind mount at ``/host`` + the
    path, or ``/tmp`` for the cache.  This is the ONE place the tab turns a
    path into something a tool will read, which is why the container mapping
    belongs here and not in each caller.
    """
    if _mac.enabled():
        return _mac.container_path(path) if path else path
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
    if _mac.enabled():
        return _mac.host_from_container(p)
    return p


def rig_repo_dir():
    """The checkout (or .app bundle) this app is actually running from.

    Distinct from :func:`repo_dir`, which on macOS answers with the staged
    copy inside the container's view.  This one is what that copy is made
    FROM, so it must stay the real thing on every platform.
    """
    return os.path.dirname(os.path.dirname(os.path.normpath(rig_dir())))


def repo_dir():
    """The checkout the rig sits in: ``rig_dir()`` is <repo>/tools/spike2_emu,
    and the tools are run from <repo> so ``pinball_decryptor`` imports."""
    if _mac.enabled():
        # The container cannot see the .app bundle (Docker Desktop does not
        # share /Applications), so the rig is staged into the cache and the
        # tools are run from there instead.
        return _mac.staged_repo()
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


def default_output_path(primary, platform="stern"):
    """``<dir of primary>/multi/<primary basename>.multi.raw`` - and when the
    primary lives IN the library (David's stock cards do), the first folder
    above it that is not: ``D:/Pinball/images/Stern/spike2/x.raw`` ->
    ``D:/Pinball/multi/x.multi.raw``.  A default the tool would refuse is
    no default.  A JJP install ISO ends ``.multi.iso`` the same way."""
    d = os.path.dirname(os.path.abspath(primary))
    while under_library(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(d, "multi", backend_for(platform).output_name(primary))


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
    stem = re.sub(r"\.(raw|img|iso)$", "", os.path.basename(card), flags=re.I)
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
#: ...and the LOADING frame beside them, one per card rather than per frame.
_LOADING_RE = re.compile(r"^loading_([0-9a-f]+)_(\d+)\.ppm$")
#: What the selector says it rolled, on its own `loading:` line.
_ROLL_RE = re.compile(r"card \d+ boots image (\d+)")


def rolled_image(text):
    """The IMAGE a `loading:` line says the card boots, or None."""
    m = _ROLL_RE.search(text or "")
    return int(m.group(1)) if m else None


def game_name(form, image):
    """What to call image *image* of *form* - "title - subtitle" when it has
    one, because a jukebox's members are one title with different song sets and
    the title alone does not tell them apart."""
    for i, path, ri, mi in form_trees(form):
        if i != image:
            continue
        row = form.images[ri]
        if mi is None:
            bits = [(row.title or "").strip() or suggest_title(path)[0],
                    (row.subtitle or "").strip()]
        else:
            bits = [(row.members[mi].title or "").strip()
                    or suggest_title(path)[0], ""]
        return " - ".join(b for b in bits if b)
    return "image %d" % image


def frame_path(preview_dir, fingerprint, highlight, frame):
    """The PPM one snapshot writes:
    ``frame_<fingerprint>_<highlight>_<frame>.ppm``."""
    return os.path.join(preview_dir, "frame_%s_%d_%d.ppm"
                        % (fingerprint, highlight, frame))


def loading_path(preview_dir, fingerprint, highlight):
    """The LOADING frame a snapshot writes beside its menu frame:
    ``loading_<fingerprint>_<highlight>.ppm``.

    ONE PER CARD, not per frame: it is what the machine draws AFTER the card is
    confirmed, and nothing is animating by then.  A RANDOM card rolls for it,
    so the file holds the member THIS render landed on - which is the whole
    reason to be able to see it (David, 2026-09-11: "I want to see this
    especially for how it looks with the random one")."""
    return os.path.join(preview_dir, "loading_%s_%d.ppm"
                        % (fingerprint, highlight))


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
        m = _FRAME_RE.match(name) or _LOADING_RE.match(name)
        if m and m.group(1) != keep:
            out.append(os.path.join(preview_dir, name))
    return out


def rootfs_for(selector_dir):
    """The rootfs a selector build sits in: ``~/spike2root/usr/local/
    codeselect`` -> ``~/spike2root``; :data:`DEFAULT_ROOTFS` otherwise."""
    d = (selector_dir or "").strip().rstrip("/")
    if d.endswith(SELECTOR_SUFFIX) and len(d) > len(SELECTOR_SUFFIX):
        return d[:-len(SELECTOR_SUFFIX)]
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


def manifest_sounds(manifest, media_dir, highlight, group=None):
    """``{"music", "move", "confirm"}`` - the WAV behind each of the menu's
    three sounds for the highlighted CARD, as full paths under *media_dir*, and
    "" for one this media set has not got.

    *group* is the card's GROUP INDEX when it is a random card, and then the
    manifest's `groups` row is what answers - not `images[highlight]`, which is
    some other game's row or none at all.  Reading the image rows for a card
    index is how the bed an owner picked for a random card went unheard (David,
    2026-09-11: "i'm not hearing music that i selected when hovering over the
    random card").

    The fallbacks are the selector's, not ours: an image plays its OWN
    confirm sound when it has one (the seventh images.conf field) and the
    menu-wide one otherwise - codeselect.c's ``own_confirm[i] ? : confirm``.
    A ``--visual-only`` prepare (the one the preview runs for itself) writes
    the music but no move or confirm sound at all, which is why "" here is
    ordinary and has to be said rather than treated as a fault."""
    if group is None:
        rows = manifest.get("images") or []
        idx = highlight
    else:
        rows = manifest.get("groups") or []
        idx = int(group)
    row = rows[idx] if 0 <= idx < len(rows) else None
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


def volume_range_error(form):
    """The sentence both validators give for a menu volume out of range.  A
    Jersey Jack machine plays the boot menu through amplifiers it keeps at
    full (the game turns only its own stream down), so its cap is lower and
    says why (item 120)."""
    be = backend_for(form)
    if be.key == "jjp":
        return ("Volume is 0-%d. A Jersey Jack machine plays the boot menu "
                "through amplifiers it keeps at full power." % be.volume_max)
    return "Volume is 0-%d." % be.volume_max


def validate_form(form, sources=True):
    """Every reason the form cannot be built, as sentences for the tab.
    Empty = build it.  The tool re-checks all of it; this is so a bad form is
    a line on the tab and not a traceback in the log pane.

    ``sources=False`` drops the checks that are about the .raw files the
    images were copied from - a card read back with 'Load card…' names
    sources that may not be on THIS machine, and neither drawing its menu
    nor injecting a new one opens them."""
    errs = []
    be = backend_for(form)
    n = len(form.images)
    if sources and n < 2:
        errs.append("Add at least two images: the primary (stock) and one "
                    "more.")
    if not n:
        errs.append("There are no images.")
    if n > be.max_cards:
        errs.append("At most %d images fit one %s." % (be.max_cards, be.out_noun))
    ngroups = sum(1 for r in form.images if is_group(r))
    if ngroups > MAX_GROUPS:
        errs.append("At most %d random groups fit one card." % MAX_GROUPS)
    if ngroups and not be.groups:
        # A JJP install has two root slots and nothing to roll between (item
        # 118): image 0 is root A, image 1 is root B, and that is the card.
        errs.append("Random groups are not available for a JJP install: it "
                    "holds exactly two images, root A and root B.")
    ntrees = len(form_trees(form))
    if ntrees > MAX_TREES:
        errs.append("That is %d games in %d rows; at most %d fit one card."
                    % (ntrees, n, MAX_TREES))
    if form.images and is_group(form.images[0]) and not form.images[0].keep:
        # A CONSUMING group here would leave the card with no primary at all:
        # the machine boots image 0 when the menu is not honoured, and that has
        # to be one known game rather than a roll.  A KEEPING group adds no
        # games, so the primary is still whichever plain row is first.
        errs.append("The first image is the primary and cannot be a random "
                    "group that hides its games. Tick 'also show each game on "
                    "its own card', or move it down.")
    if form.images and not any(not is_group(r) or not r.keep for r in form.images):
        errs.append("Add at least one plain image: a card made only of random "
                    "groups has no primary to boot.")
    # what the card will actually carry, so a KEEPING group's members can be
    # checked against it rather than counted as games of their own
    games_on_card = set()
    for _img, _path, _ri, _mi in form_trees(form):
        if _path:
            games_on_card.add(_norm(_path))
    seen = set()
    for i, row in enumerate(form.images):
        if is_group(row):
            if len(row.members) < 2:
                errs.append("Image %d is a random group with %d game(s); a "
                            "group needs at least 2." % (i, len(row.members)))
            for mi, m in enumerate(row.members):
                mp = (m.path or "").strip().strip('"')
                if not sources:
                    continue
                if not mp:
                    errs.append("Image %d, game %d has no file." % (i, mi + 1))
                elif not os.path.isfile(mp):
                    errs.append("Image %d, game %d: no such file: %s"
                                % (i, mi + 1, mp))
                elif row.keep:
                    # ITS GAMES ARE OTHER ROWS'.  Being listed elsewhere is the
                    # POINT of a keeping group, so the only thing to check is
                    # that the game really is on the card.
                    if _norm(mp) not in games_on_card:
                        errs.append("Image %d, game %d is not one of the images "
                                    "on this card: %s" % (i, mi + 1, mp))
                else:
                    key = _norm(mp)
                    if key in seen:
                        errs.append("Image %d, game %d is listed twice: %s"
                                    % (i, mi + 1, mp))
                    seen.add(key)
            if row.keep and len(set(_norm(q) for q in row_paths(row))) != len(row.members):
                errs.append("Image %d names the same game twice." % i)
            if row.keep and sources:
                # A GROUP'S MEMBERS MUST BE ONE RUN of image indexes - the
                # builder refuses a gap, because a group= line is written as
                # `<first>-<last>`.  Saying so here is the difference between
                # a red cross in the list and a refusal minutes into a build.
                imgs = sorted(i2 for i2 in group_member_images(form, row) if i2 >= 0)
                if len(imgs) == len(row.members) and imgs and \
                        imgs != list(range(imgs[0], imgs[0] + len(imgs))):
                    errs.append(
                        "Image %d rolls between games that are not next to "
                        "each other on the card; move them together." % i)
            for what, text in (("title", row.title), ("subtitle", row.subtitle)):
                if _BAD_TEXT.search(text or ""):
                    errs.append("Image %d: the %s must not contain | ; $ or `."
                                % (i, what))
            on_card = dict(on_card_fields(row))
            for what, val in media_fields_to_check(row):
                if what in on_card:
                    continue
                if is_file_choice(val) and not os.path.isfile(val.strip()):
                    errs.append("Image %d: %s file not found: %s"
                                % (i, what, val))
            continue
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
        for what, val in media_fields_to_check(row):
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
            why = _bad_number(row.anim_start,
                              "Image %d: the animation start" % i)
            if why:
                errs.append(why)
        if anim_spec(row).startswith("auto") and not backend_for(form).attract_clip:
            errs.append("Image %d: a Jersey Jack image has no attract video "
                        "to pull - pick 'A video file' for it (a clip PAD "
                        "extracted from the game works)." % i)
    for what, val in (("move sound", form.sound_move),
                      ("confirm sound", form.sound_confirm)):
        if is_file_choice(val) and not os.path.isfile(val.strip()):
            errs.append("The %s file was not found: %s" % (what, val))
    if not 0 <= int(form.volume) <= backend_for(form).volume_max:
        errs.append(volume_range_error(form))
    if int(form.timeout) < 0:
        errs.append("The countdown cannot be negative (0 = wait for START).")
    head = (form.heading or "").strip()
    # A NEWLINE WOULD END THE KEY in images.conf and turn the rest of the line
    # into an unknown one, so it is refused here rather than half-written; the
    # length is the selector's own field (PAD-135).
    if any(c in head for c in "\r\n"):
        errs.append("The heading has to be one line.")
    elif len(head.encode("utf-8")) > HEADING_MAX:
        errs.append("The heading is too long (%d characters at most)."
                    % HEADING_MAX)
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
        errs.append("Set the output %s path." % be.out_ext)
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

#: THE NAMES THE CONTROLS REALLY WEAR.  Every sentence in this tab that
#: tells someone what to press says one of these, because 'Apply to card'
#: and 'Build & verify' were buttons that became ONE green button and a
#: modal (see MultibootPanel._build_actions) - and the sentences went on
#: naming the buttons for months afterwards (David: "there is no 'apply to
#: card' option anywhere in the gui. how do i do that?").
#:
#: A sentence that sends someone looking for a control which is not there is
#: worse than one that says only what is true - the rule this tab's own
#: 'strayed' sentence was already rewritten for.  Constants, so the next
#: rename moves them once.
WRITE_BUTTON = "Build / flash card\u2026"
APPLY_TICK = "Build / flash card\u2026 \u25b8 Update the loaded card in place"
READ_VERB = "Browse\u2026 to it (or press Enter in the path box)"


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
    ``@<start>`` appended when the clip starts into its source.

    NO LENGTH AND NO RATE, EVER.  Those are selectmedia's own contract (the
    loop is up to 5 s at the source's frame rate, 30 fps at most), and a
    spec that named them was what the old Start/Length/FPS controls sent -
    ``@0:13:30`` for a clip David had typed 13 s and 30 fps into, which the
    rate-first clamp rendered as 13 s at 2 fps, and which the row went on
    sending after the controls were removed."""
    v = (row.anim or "").strip().strip('"')
    w = v.lower()
    if w in ("none", ""):
        return "none"
    base = "auto" if w == "auto" else wsl(v)
    start = _clip_start(row)
    if start:
        base += "@%s" % start
    return base


def _clip_start(row):
    """The row's clip start as typed, or '' when it is blank or zero (the
    source's own start needs no spelling out; a value that is not a number
    is passed on for validate_form to name)."""
    start = _num(getattr(row, "anim_start", ""))
    if not start:
        return ""
    try:
        if float(start) == 0:
            return ""
    except ValueError:
        pass
    return start


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


def anim_period_ms(row=None, delay_ms=None, floor_ms=16, ceiling_ms=2000):
    """How long ONE frame of an animation is on screen, in ms: the rendered
    clip's own delay (*delay_ms*, from :func:`gif_period_ms`) - what the
    machine ticks on - and until the GIF is there to read, the contract's
    own rate (:data:`ANIM_FPS`).  The row has no say (it carries no rate
    any more); the argument stays so callers read the same.  Clamped,
    because a file can say anything: 0.4 fps is a slideshow and 300 fps
    a busy loop, and neither is worth letting a bad GIF cause."""
    ms = float(delay_ms) if delay_ms and delay_ms > 0 else 1000.0 / ANIM_FPS
    return max(floor_ms, min(ceiling_ms, int(round(ms))))


def gif_frame_delay_ms(img, k):
    """Seek an open Pillow GIF to frame *k* and read its delay (100 where
    the file says 0, as the selector's art.c has it)."""
    img.seek(k)
    return int(img.info.get("duration") or 0) or 100


class ClipFrames(object):
    """The frames of a rendered ``anim<N>.gif``, read with Pillow as Play
    asks for them, each scaled ONCE to the size the preview draws the
    picture at.

    WHY THE GIF AND NOT A PPM PER FRAME.  The selector blits a GIF's frame
    into the card's panel unchanged when the tools made it at the panel's
    size (they do), so the GIF's own pixels at the picture's rectangle ARE
    the machine's frame k; it reports that rectangle on its snapshot line.
    A 5 s clip is 150 frames, and 150 PPMs at 3 MB each per Play - per
    highlight change - was the alternative.  Pillow composes each frame
    onto the last as the file's disposal says, the same way stb does on
    the machine.

    THE FILE IS READ INTO MEMORY AND CLOSED, and Pillow decodes out of the
    bytes.  ``Image.open(path)`` keeps the handle open for as long as the
    image lives, and these live for as long as the picture is playing -
    which is all the time, on every card.  A Windows handle on a file WSL
    is about to unlink is an ``EACCES``, and that is exactly what happened:
    delete an image and the next prepare died on
    ``os.remove(.../anim2.gif)``, so the preview never redrew (David:
    "i deleted an image and the preview didn't regen").  A GIF here is
    capped at 10 MB by the tool that writes it, and the decoded frames this
    object keeps are far bigger, so the copy costs nothing worth having."""

    def __init__(self, path, size):
        self.path = path
        self.size = (max(1, int(size[0])), max(1, int(size[1])))
        with open(path, "rb") as f:
            self._data = f.read()
        self._img = Image.open(io.BytesIO(self._data))
        self._img.load()
        self.n = max(1, int(getattr(self._img, "n_frames", 1)))
        self._frames = {}
        self._delays = {}
        self._period = None
        self._all = None                # every delay, once read
        self._cum = None                # ...and their running sum

    def frame(self, k):
        """Frame *k* (wrapped) as an RGB image at ``size``."""
        k %= self.n
        hit = self._frames.get(k)
        if hit is None:
            self._delays[k] = gif_frame_delay_ms(self._img, k)
            hit = self._img.convert("RGB").resize(self.size, Image.BILINEAR)
            self._frames[k] = hit
        return hit

    def delay_ms(self, k):
        """How long frame *k* is up, per the file (100 where it says 0,
        as the selector's art.c has it)."""
        k %= self.n
        if k not in self._delays:
            self.frame(k)
        return self._delays[k]

    def delays(self):
        """Every frame's delay, in order (one pass over the file, kept)."""
        if self._all is None:
            self._all = [gif_frame_delay_ms(self._img, k) for k in range(self.n)]
            total, self._cum = 0, []
            for d in self._all:
                total += d
                self._cum.append(total)
        return self._all

    def period_ms(self):
        """The loop's frame period: the MEAN delay when the file's delays
        are near-uniform (a constant-rate clip - ffmpeg writes 30/40 ms in
        turn for 33.3), else None (tick on :meth:`delay_ms`).  The same
        rule as the selector's art.c, so the preview keeps the machine's
        time."""
        if self._period is None:
            delays = self.delays()
            self._period = 0.0
            if len(delays) >= 2 and max(delays) <= 2 * min(delays):
                self._period = sum(delays) / float(len(delays))
        return self._period or None

    def loop_ms(self):
        """How long one loop of the clip takes on the machine's clock."""
        p = self.period_ms()
        return p * self.n if p else float(self._cum[-1]) if self.delays() else 100.0

    def frame_at(self, t_ms):
        """The frame showing *t_ms* into a run that started at 0 - the
        clip's OWN timeline, so a late or missed tick lands on the frame
        the machine would be showing, never a frame behind it."""
        if self.n < 2:
            return 0
        p = self.period_ms()
        if p:
            return int(t_ms // p) % self.n
        self.delays()
        t = t_ms % self._cum[-1]
        return min(self.n - 1, bisect.bisect_right(self._cum, t))

    def ms_to_next(self, t_ms):
        """How long, from *t_ms*, until the frame after :meth:`frame_at`."""
        if self.n < 2:
            return 1000.0
        p = self.period_ms()
        if p:
            return p - (t_ms % p)
        self.delays()
        t = t_ms % self._cum[-1]
        return self._cum[min(self.n - 1, bisect.bisect_right(self._cum, t))] - t

    def close(self):
        try:
            self._img.close()
        except Exception:                               # noqa: BLE001
            pass
        self._data = b""
        self._frames = {}


def inherits_confirm(value):
    """Whether an :class:`ImageRow`'s ``confirm`` means "the menu's sound".

    THREE SPELLINGS, ONE STATE: ``''`` is what the row keeps, ``menu`` is
    what the dialog's box says, and ``none`` is what a hand types into that
    box meaning silence - which this format cannot do (see
    :data:`IMAGE_CONFIRM_CHOICES`), so the card plays the menu's sound for
    it.  Every panel that says what an image will play asks THIS, so what
    the list shows, what the dialog shows and what :func:`confirm_spec`
    writes onto the card cannot drift apart."""
    v = (value or "").strip().strip('"').lower()
    return not v or v in ("menu", "none")


def confirm_spec(row):
    """The ``--sound-confirm N=`` value for a row.

    A row that uses the menu's sound is written ``none``, which is how
    selectmedia spells "image N has no confirm of its own": the manifest
    entry comes back null, the seventh images.conf field is empty, and the
    selector falls back to ``sound_confirm=``.  It is EXPLICIT rather than
    left out, so a row that used to have one and no longer does loses it."""
    v = (row.confirm or "").strip().strip('"')
    w = v.lower()
    if inherits_confirm(v):
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


def split_music_source(spec):
    """A ``music_source`` from the card -> an :class:`ImageRow` value.

    The same shape as :func:`split_confirm_source`, and it exists for the
    same reason: what a load puts in the row has to be the spec that MADE
    the sound, not the name of the file it made.  Compare a file name
    against a source and the only possible answer is "these differ", which
    is how a loaded card's music came back as 'not rendered' with the wav
    sitting in the media directory (David: "the audio music and confirms
    are set... what happened?")."""
    t = (spec or "").strip()
    if not t or t.lower() == "none":
        return "none"
    if t.lower() in ("auto", "synth") or _AUTO_IDX_RE.match(t):
        return t.lower()
    return host_path(t)


def form_compact(form):
    """Whether this form builds the compact layout.

    A GROUP FORCES IT.  A jukebox card's games are the same title with a few
    songs changed, so on the older layouts each member costs a full copy: forty
    Beatles variants are about 18 GB of duplicate content the compact build
    holds once.  mkmulticard refuses parts/multi with a group outright; the tab
    ticks the box and disables it, so the reason is visible before the press
    rather than in a refusal after it (David, 2026-09-09)."""
    return bool(form.compact) or any(is_group(r) for r in form.images)


def _media_image_args(form):
    """--primary and --extra for every GAME, and nothing else.

    selectmedia.py renders pictures and sounds for the games on the card; it
    has never heard of a group and does not need to, because a group card's
    media is one of theirs.  It shares no vocabulary with mkmulticard beyond
    these two flags, so handing it `_image_args` made it exit 2 on
    `--group-over` and took the whole preview down with it (David's log,
    2026-09-10: "selectmedia.py: error: unrecognized arguments: --group-over").
    """
    trees = [t[1] for t in form_trees(form)]
    args = ["--primary", wsl(trees[0] if trees else "")]
    for path in trees[1:]:
        args += ["--extra", wsl(path)]
    return args


def group_roll_args(form):
    """``--group-roll G=MODE`` for every random card, spelled out - so what the
    dialog says is what the card does, whatever the conf's own default is."""
    args = []
    for gi, _ri, row, _imgs in form_groups(form):
        args += ["--group-roll", "%d=%s" % (gi, row_roll(row))]
    return args


def _image_args(form):
    """--primary, then each row IN TABLE ORDER as either an --extra or a
    --group with its --member games.  The order matters: mkmulticard reads
    these flags as one ordered sequence, because the only thing that fixes a
    member's image index is where its flag sat (item 106)."""
    trees = form_trees(form)
    primary = next((t[1] for t in trees), "")
    args = ["--primary", wsl(primary)]
    for ri, row in enumerate(form.images):
        if is_group(row) and row.keep:
            # IT ADDS NO GAMES: it names images other rows already put there,
            # and its place among these flags is where its card sits.
            imgs = [i for i in group_member_images(form, row) if i >= 0]
            if len(imgs) >= 2:
                args += ["--group-over", "%d-%d|%s|%s"
                         % (min(imgs), max(imgs), (row.title or "").strip(),
                            (row.subtitle or "").strip())]
            continue
        if is_group(row):
            args += ["--group", "%s|%s" % ((row.title or "").strip(),
                                           (row.subtitle or "").strip())]
            for path in row_paths(row):
                args += ["--member", wsl(path)]
            continue
        if ri == 0:
            continue                      # already given as --primary
        args += ["--extra", wsl(row_paths(row)[0])]
    return args


def group_media_args(form):
    """``--group-members`` / ``--group-art`` / ``--group-anim``, one set per
    RANDOM card, numbered 0..N-1 in row order.  selectmedia draws the card from
    the members' own logos, so it has to be told which images they are."""
    args = []
    for gi, _ri, row, imgs in form_groups(form):
        if not imgs:
            continue
        args += ["--group-members", "%d=%s" % (gi, ",".join(str(i) for i in imgs)),
                 "--group-art", "%d=%s" % (gi, group_art_spec(row)),
                 "--group-anim", "%d=%s" % (gi, group_anim_spec(row)),
                 # A RANDOM CARD IS A CARD: the bed that plays while it is
                 # highlighted and the sound it makes when it is chosen are its
                 # own, not its first member's (David, 2026-09-11: "i'm not
                 # hearing music that i selected when hovering over the random
                 # card").
                 "--group-music", "%d=%s" % (gi, _media_value(row.music)),
                 "--group-confirm", "%d=%s" % (gi, confirm_spec(row))]
    return args


def game_titles(form, platform="stern"):
    """``(titles, subtitles)``, ONE PER GAME, because images.conf's image=
    lines are.  A group card's own title and subtitle do not go here: they
    ride on its --group / --group-over flag, and its members keep their own
    names so the LOADING frame can say which song set the roll landed on.

    Build, update and inject all send these.  Update and inject used to send
    one per table ROW, so a card with a random card over games already on it
    (a row that adds no game) sent one title too many and the tool refused:
    "images.conf: 7 titles / 7 subtitles / 6 media rows for 6 images", which
    left 'Build a fresh card' as the only way to change anything (PAD-202)."""
    titles, subtitles = [], []
    for _i, path, ri, mi in form_trees(form):
        row = form.images[ri]
        if mi is None:
            titles.append((row.title or "").strip() or suggest_title(path, platform)[0])
            subtitles.append((row.subtitle or "").strip())
        else:
            m = row.members[mi]
            titles.append((m.title or "").strip() or suggest_title(path, platform)[0])
            subtitles.append("")
    return titles, subtitles


def default_card_args(form):
    """``--default-card N`` when the highlighted row is a KEEPING group.  Its
    games all keep cards of their own, so no image index resolves to it, and
    a random card the countdown cannot land on is useless for an unattended
    power-up, which is the whole point - so the card index goes too."""
    d = int(form.default)
    if 0 <= d < len(form.images) and is_group(form.images[d]) and form.images[d].keep:
        return ["--default-card", str(row_card_index(form, d))]
    return []


def jjp_selector_dir(selector_dir):
    """The JJP menu program's directory: what the form names, unless that is
    empty or the STERN default the form is born with (a form that never
    said is a Stern form, and its default names an ARM build inside
    ~/spike2root, which is no place for jjpselect)."""
    sel = (selector_dir or "").strip().rstrip("/")
    if not sel or sel == DEFAULT_SELECTOR_DIR.rstrip("/"):
        return JJP.selector_default
    return sel


def _jjp_sound(spec):
    """A sound spec for the JJP media step: 'auto' is the CARD's own sound on
    Stern (pulled off the games partition through the emulator), and a JJP
    ISO has no such catalogue the tools can reach - so 'auto' is the built-in
    synthetic click / chime there.  Everything else passes through."""
    s = _media_value(spec)
    return "synth" if s.lower().startswith("auto") else s


def _jjp_media_args(form, media_dir, visual_only=False):
    """``mkjjpmulti.py media``: the JJP twin of :func:`prepare_args`.  Two
    images, no groups; ``--art N=auto`` is the image's own JJP logo (the
    tool's one seam, plaintext in every JJP root), an 'auto' animation has no
    seam yet (the attract clip sits encrypted in edata) and is rendered as
    none, and 'auto' sounds are the synthetic ones (see :func:`_jjp_sound`).
    The rest is selectmedia's own grammar, which the tool hands through."""
    args = list(JJP.media_tool) + _media_image_args(form) + ["--out", wsl(media_dir)]
    if visual_only:
        args.append("--visual-only")
    for i, _path, ri, _mi in form_trees(form):
        row = form.images[ri]
        anim = anim_spec(row)
        if anim.lower().startswith("auto"):
            anim = "none"
        args += ["--art", "%d=%s" % (i, art_spec(row)),
                 "--anim", "%d=%s" % (i, anim),
                 "--music", "%d=%s" % (i, _media_value(row.music))]
    if not visual_only:
        args += ["--sound-move", _jjp_sound(form.sound_move),
                 "--sound-confirm", _jjp_sound(form.sound_confirm)]
        for i, _path, ri, _mi in form_trees(form):
            args += ["--sound-confirm", "%d=%s" % (i, _jjp_sound(confirm_spec(form.images[ri])))]
    args += ["--volume", str(int(form.volume))]
    return args


def prepare_args(form, media_dir, visual_only=False):
    """``selectmedia.py prepare``: the images (the tool pulls 'auto' art and
    clips off them), then ``--art/--anim/--music N=<value>`` for EVERY image
    - explicit rather than defaulted, so the form and the manifest cannot
    disagree about an index - then the globals.  Rendered into *media_dir*,
    which then holds media.json.  ``visual_only`` is the preview's half: the
    art and animations with the same specs, no move / confirm sound work
    (music entries are still named, so the manifest rows match).  A JJP form
    goes to :func:`_jjp_media_args` (the same manifest out of the JJP tool)."""
    if backend_for(form).key == "jjp":
        return _jjp_media_args(form, media_dir, visual_only)
    args = [SELECTMEDIA, "prepare"] + _media_image_args(form) + [
        "--out", wsl(media_dir),
        # THE PANEL IS SIZED BY THE CARDS: a row is a card, and a random card
        # stands for several images.  Without this a jukebox of forty song sets
        # would have its pictures cut for a forty-panel menu and drawn in a
        # two-panel one.
        "--cards", str(max(1, len(form.images)))] + group_media_args(form)
    if visual_only:
        args.append("--visual-only")
    # THE N= INDEXES ARE IMAGES.  media.json carries one row per games tree,
    # which is what mkmulticard's plan_media expects.  Using the table's row
    # number here would silently shift every media row after the first group.
    #
    # A GROUP'S MEMBER GAMES ASK FOR NOTHING TO LOOK AT.  They have no card of
    # their own - one card stands in front of all of them, with its own picture
    # (--group-art) and its own name - and nothing in the menu ever draws them,
    # the LOADING frame included (it names the member under the CARD's
    # picture).  Forty song sets would otherwise render forty logos and forty
    # copies of one music bed into a 96 MB budget, for a card that shows one.
    # The card's SOUNDS are still the first member's row, which is where
    # mkmulticard reads them from.
    for i, _path, ri, mi in form_trees(form):
        row = form.images[ri]
        if mi is None:
            args += ["--art", "%d=%s" % (i, art_spec(row)),
                     "--anim", "%d=%s" % (i, anim_spec(row)),
                     "--music", "%d=%s" % (i, _media_value(row.music))]
        else:
            # ...and nothing to HEAR either: the card's own bed is prepared
            # against the card (see group_media_args), so a member carrying one
            # would be a second copy of the same wav.
            args += ["--art", "%d=none" % i, "--anim", "%d=none" % i,
                     "--music", "%d=none" % i]
    if not visual_only:
        args += ["--sound-move", _media_value(form.sound_move),
                 "--sound-confirm", _media_value(form.sound_confirm)]
        # ...then each image's own, after the menu-wide one: the bare value
        # and the N= values are one appending option, and the tool tells
        # them apart by the prefix, not by the order.
        for i, _path, ri, mi in form_trees(form):
            args += ["--sound-confirm", "%d=%s"
                     % (i, confirm_spec(form.images[ri]) if mi is None else "none")]
    args += ["--volume", str(int(form.volume))]
    return args


def preview_prepare_args(form, media_dir):
    """The preview's ``prepare --visual-only`` into the build's media dir."""
    return prepare_args(form, media_dir, visual_only=True)


def plan_args(form):
    """``mkmulticard.py plan``: the layout and whether it fits 16G / 32G.
    Writes nothing.  (``mkjjpmulti.py plan`` for a JJP form: the two ISOs'
    pieces and which USB stick they fit.)"""
    be = backend_for(form)
    if be.key == "jjp":
        args = [be.tool, "plan"] + _image_args(form)
        if form.media_dir:
            args += ["--media-dir", wsl(form.media_dir)]
        return args
    return ([MKMULTICARD, "plan"] + _image_args(form) + group_roll_args(form)
            + ["--layout", "store" if form_compact(form) else "auto"] + cache_dir_args())


def _jjp_build_args(form):
    """``mkjjpmulti.py build``: root A from image 0 with the menu staged, root
    B from image 1 verbatim, the installer redirected - the JJP twin of
    :func:`build_args`.  No layout, no bypass, no machine volume: none of
    those exist on a JJP install (item 116)."""
    be = JJP
    titles, subtitles = [], []
    for _i, path, ri, _mi in form_trees(form):
        row = form.images[ri]
        titles.append((row.title or "").strip() or suggest_title(path, be.key)[0])
        subtitles.append((row.subtitle or "").strip())
    args = [be.tool, "build"] + _image_args(form) + [
        "--out", wsl(form.out.strip().strip('"')),
        "--selector-dir", jjp_selector_dir(form.selector_dir),
        # THE SCRATCH STAYS ON THE LINUX SIDE: the build loop-mounts a copy of
        # root A, and a loop device over a file on the Windows drive (virtiofs)
        # is the one place this tool must never put one; the output itself is
        # a plain sequential write and goes where the box says
        "--workdir", JJP_WORKDIR,
        "--titles", ";".join(titles),
        "--timeout", str(int(form.timeout)),
        "--default", str(int(form.default)),
        "--volume", str(int(form.volume)),
    ] + heading_args(form) + text_size_args(form) + menu_text_args(form) \
        + theme_args(form)
    if any(subtitles):
        args += ["--subtitles", ";".join(subtitles)]
    if form.media_dir:
        args += ["--media-dir", wsl(form.media_dir)]
    if form.force:
        args.append("--force")
    return args


def build_args(form):
    """``mkmulticard.py build``.  ``--layout auto`` = today's p7 layout for
    one extra image, the img1/img2/... partition for more.  A JJP form goes
    to :func:`_jjp_build_args`."""
    if backend_for(form).key == "jjp":
        return _jjp_build_args(form)
    titles, subtitles = game_titles(form)
    args = [MKMULTICARD, "build"] + _image_args(form) + group_roll_args(form) + [
        "--out", wsl(form.out.strip().strip('"')),
        "--selector-dir", form.selector_dir or DEFAULT_SELECTOR_DIR,
        "--layout", "store" if form_compact(form) else "auto",
        "--titles", ";".join(titles),
        "--timeout", str(int(form.timeout)),
        # --default names an IMAGE (so does the choice file, and so does the
        # menu's own memory); the tab's number is the highlighted ROW.  A row
        # that is a consuming group is named by its first member, and the
        # selector highlights that member's card - which is the group's.
        "--default", str(row_first_image(form, int(form.default))),
        # The tab's knob is the volume of record: the same number goes into
        # media.json (prepare) and into images.conf here, so a text-only card
        # with no prepared media still carries it.
        "--volume", str(int(form.volume)),
    ] + heading_args(form) + text_size_args(form) + menu_text_args(form) \
        + theme_args(form)
    args += default_card_args(form)
    if form.machine_volume:
        # ...and on the machine the menu plays at ITS setting, not that number
        args.append("--machine-volume")
    if any(subtitles):
        args += ["--subtitles", ";".join(subtitles)]
    # ALWAYS: the validator bypass on every image (David, after the TMNT
    # proved it: "we don't need to make it optional. it should always be on").
    # Since item 98 it also ignores the saved grades at boot, so a GAME
    # VALIDATION ERROR an earlier card left in the machine cannot latch.
    args.append("--bypass-validation")
    if form.media_dir:
        args += ["--media-dir", wsl(form.media_dir)]
    if form.force:
        args.append("--force")
    return args


def verify_args(form):
    """``mkmulticard.py verify``: every copied range against its source,
    every ext4 fsck'd, the injected files against the selector build, the
    bypass state of every games tree.  (``mkjjpmulti.py verify --iso`` for
    a JJP form: the cfg lines, the installer, every piece, root A restored
    and its staged files checked against build.json.)"""
    be = backend_for(form)
    if be.key == "jjp":
        # the deep check restores root A to scratch: the Linux side, as build
        return ([be.tool, "verify", "--iso", wsl(form.out.strip().strip('"'))]
                + _image_args(form) + ["--workdir", JJP_WORKDIR + "_verify"])
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
    be = backend_for(form)
    titles, subtitles = game_titles(form, be.key)
    if be.key == "jjp":
        # mkjjpmulti.py inject --iso: root A restored, re-staged, re-imaged
        # and spliced back into the ISO in place (item 116)
        args = [be.tool, "inject",
                "--iso", wsl(card.strip().strip('"')),
                "--selector-dir", jjp_selector_dir(form.selector_dir),
                "--workdir", JJP_WORKDIR,
                "--titles", ";".join(titles),
                "--subtitles", ";".join(subtitles),
                "--timeout", str(int(form.timeout)),
                "--default", str(int(form.default)),
                "--volume", str(int(form.volume))]
        args += (heading_args(form) + text_size_args(form)
                 + menu_text_args(form) + theme_args(form))
        if form.media_dir:
            args += ["--media-dir", wsl(form.media_dir)]
        return args
    args = [MKMULTICARD, "inject",
            "--card", wsl(card.strip().strip('"')),
            "--selector-dir", form.selector_dir or DEFAULT_SELECTOR_DIR,
            "--titles", ";".join(titles),
            "--subtitles", ";".join(subtitles),
            "--timeout", str(int(form.timeout)),
            "--default", str(row_first_image(form, int(form.default))),
            "--volume", str(int(form.volume))]
    args += default_card_args(form)
    args += (heading_args(form) + text_size_args(form)
             + menu_text_args(form) + theme_args(form))
    if form.machine_volume:
        args.append("--machine-volume")
    if form.media_dir:
        args += ["--media-dir", wsl(form.media_dir)]
    return args


def update_args(form, card, dry_run=False, expect_bytes=None):
    """``mkmulticard.py update --card``: ONLY what changed since the card was
    written - into the loaded card, in place (item 93).  The menu flags are
    inject's (every field spelled out); ``--dry-run`` says what it would
    write and writes nothing; ``--expect-bytes`` is the number the dialog
    showed, and the tool refuses when a source moved under it."""
    titles, subtitles = game_titles(form)
    args = [MKMULTICARD, "update",
            "--card", wsl(card.strip().strip('"'))] + _image_args(form)
    args += group_roll_args(form) + [
            "--selector-dir", form.selector_dir or DEFAULT_SELECTOR_DIR,
            "--titles", ";".join(titles),
            "--subtitles", ";".join(subtitles),
            "--timeout", str(int(form.timeout)),
            # an IMAGE, as build's is (the tab's number is the ROW)
            "--default", str(row_first_image(form, int(form.default))),
            "--volume", str(int(form.volume))]
    args += default_card_args(form)
    args += (heading_args(form) + text_size_args(form)
             + menu_text_args(form) + theme_args(form))
    if form.machine_volume:
        args.append("--machine-volume")
    args.append("--bypass-validation")      # always (see build_args)
    if form.media_dir:
        args += ["--media-dir", wsl(form.media_dir)]
    args += cache_dir_args()
    if dry_run:
        args.append("--dry-run")
    if expect_bytes is not None:
        args += ["--expect-bytes", str(int(expect_bytes))]
    return args


def inspect_args(card, media_out=None, as_json=False, platform="stern"):
    """``mkmulticard.py inspect --card``: what a card carries.  Plain it
    prints a table; ``--json`` prints one object for the tab to read, and
    ``--media-out DIR`` drops the card's media files there so the preview
    can draw them and an inject can put them back.  (``mkjjpmulti.py
    inspect --iso`` for a JJP ISO: the same object, read off the ISO's own
    copy of the menu without a mount.)"""
    be = backend_for(platform)
    args = [be.tool, "inspect", be.card_flag, wsl(card.strip().strip('"'))]
    if as_json:
        args.append("--json")
    if media_out:
        args += ["--media-out", wsl(media_out)]
    return args


def preview_highlight(form, row_index):
    """The ``--highlight-card`` value for a table ROW, which is the row.

    THE PREVIEW HIGHLIGHTS A CARD, NOT AN IMAGE.  `--highlight`, `default=` and
    the choice file all name an image, and that is right for them - they say
    which GAME boots.  The preview says which CARD the player is looking at,
    and a RANDOM card over images that keep their own is not any image: no
    image index resolves to it.  Sending its first member instead lit up that
    member's own card, so the flippers walked past the random one and drew the
    first card twice (David, 2026-09-11: "the left right flippers can't
    highlight the random one").  A row IS a card, so this is the row."""
    return row_card_index(form, int(row_index))


#: THE ARM INTERPRETER, FOUND WHEN THE STEP RUNS rather than named here.
#: ``qemu-arm-static`` is a file Ubuntu 26.04 does not ship: its qemu-user
#: carries the static interpreter as plain ``qemu-arm`` (PAD-139), so naming
#: the old file failed every preview on that release.  The snapshot is a HOST
#: process run with ``-L``, so either one draws the frame; the -static name is
#: tried first because it is what every older machine has.  ``sh -c`` because
#: every word of the step line is quoted (shell_line), which is what keeps this
#: script's ``$`` for the shell that runs it.
QEMU_ARM = ["sh", "-c",
            'q=$(command -v qemu-arm-static || command -v qemu-arm) || '
            '{ echo "no qemu-arm-static or qemu-arm in this Linux" >&2; '
            'exit 127; }; exec "$q" "$@"',
            "qemu-arm"]


def preview_snapshot_args(binary, conf, media_dir, ppm, highlight, frame,
                          rootfs=DEFAULT_ROOTFS, frames=1, loading=None,
                          roll_state=None, platform="stern"):
    """``qemu-arm -L <rootfs> <codeselect> --snapshot <ppm> ...``:
    ONE menu frame as the machine would show it - the conf, the media,
    the CARD highlighted, the animation at frame N, the countdown as if just
    started, no input, no audio, no choice file - then exit.

    ``frames`` > 1 asks for a WHOLE RUN out of that one load: *ppm* is then
    a :func:`frame_pattern` and the selector writes K files, starting at
    *frame* and wrapping at the animation's own length.  K == 1 is left
    alone - no ``--frames`` at all - because that is the byte-for-byte
    single-frame command line, and the one the selector treats the
    ``--snapshot`` value as a plain file NAME for."""
    # jjpselect is a native x86-64 binary (item 114): it draws the frame
    # itself, no interpreter and no rootfs in front of it
    head = [binary] if backend_for(platform).preview_native else QEMU_ARM + ["-L", rootfs, binary]
    args = head + [
            "--snapshot", wsl(ppm), "--conf", wsl(conf),
            "--media", wsl(media_dir),
            # A CARD, not an image: see preview_highlight.  The two are the
            # same number until a group card makes them differ, and then only
            # this one can name the group's.
            "--highlight-card", str(int(highlight)),
            "--anim-frame", str(int(frame))]
    if int(frames) > 1:
        args += ["--frames", str(int(frames))]
    if loading:
        # ...and the frame the machine draws once this card is confirmed.  It
        # costs one more PPM out of a load that has already happened, and it is
        # the only way to see what a RANDOM card says it rolled.
        args += ["--loading-out", wsl(loading)]
    if roll_state:
        # THE ROLL'S MEMORY, which is what makes the preview's roll the
        # machine's roll: what was booted last, and what each shuffle has
        # already dealt.  A snapshot reads no last-choice file - it writes
        # nothing and must not depend on the machine's memory - so the preview
        # names a file of its own and the selector reads and writes THAT one
        # (David, 2026-09-11: "the preview needs to show the same random logic
        # as the machine").
        args += ["--roll-state", wsl(roll_state)]
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
    on Windows, ``bash`` on Linux.

    IN THE APP'S OWN DISTRO when one is installed.  This tab used to be the
    one WSL path deliberately left on the machine's default Linux, because
    the runtime image had not been audited against the card builder's tool
    list.  It has been now - fuser(1) was the one thing missing, and the image
    carries psmisc for it - so this goes where everything else goes.  A card
    built in one Linux and a rig run in another was never a difference anyone
    wanted to reason about."""
    if sys.platform == "win32":
        return runtime.wsl_head() + ["-e", "bash", "-lc", line]
    if _mac.enabled():
        return _mac.exec_argv(line)
    return ["bash", "-lc", line]


def wsl_command(args, cwd=None, exe="python3"):
    """The argv that runs one tool command line.  *cwd* is the checkout root
    in WSL form (derived from the rig's location when not given)."""
    if cwd is None:
        cwd = wsl(repo_dir())
    return wsl_shell(shell_line(args, cwd, exe))


def wsl_shell_root(line, home=None):
    """The argv that runs one shell line AS ROOT: ``wsl -u root`` carrying
    the desktop user's HOME (root's own is /root, where ``~/spike2root`` is
    not - the shape the Emulate tab's checkpointable launch uses), ``sudo
    -n`` on Linux (fails fast rather than waiting for a password a GUI
    cannot type).  A SEPARATE function, never a flag: a wrong argument must
    not be able to turn an ordinary run into a root one (_rig.rig_cmd_root's
    rule)."""
    if sys.platform == "win32":
        head = runtime.wsl_head(root=True) + ["-e"]
        if home:
            head += ["env", "HOME=" + home]
        return head + ["bash", "-lc", line]
    if _mac.enabled():
        # NO sudo at all: the container's own user is root.  This is what
        # makes the macOS route worth having rather than teaching a GUI to
        # ask for a password it could not have spent (PAD-192).  *home* is a
        # WSL concern and means nothing here.
        return _mac.exec_argv(line)
    return ["sudo", "-n", "bash", "-lc", line]


def wsl_command_root(args, cwd=None, exe="python3", home=None):
    if cwd is None:
        cwd = wsl(repo_dir())
    return wsl_shell_root(shell_line(args, cwd, exe), home)


#: What sudo prints when it has nowhere to ask for a password.
_SUDO_NEEDS_PASSWORD = "a password is required"

def sudo_password_note(text):
    """One sentence for a root step that died for want of a password, or ""
    when that is not what happened.

    :func:`wsl_shell_root` asks with ``sudo -n`` on purpose — a GUI has no
    terminal to type into, so failing fast beats hanging on a prompt nobody
    can see.  On a Linux desktop that is usually the end of it, and the
    message names the real fix.

    macOS never reaches here at all any more: its steps run in a container
    whose own user is root (:mod:`multiboot_docker`), so nothing on that
    platform shells out to sudo.
    """
    if _SUDO_NEEDS_PASSWORD not in (text or ""):
        return ""
    return ("This step needs administrator rights and could not get them: "
            "the app asks with `sudo -n`, which never waits for a password. "
            "Give this account passwordless sudo, or start the app from a "
            "terminal where `sudo -v` has already been run.")


#: What Docker prints when a step is run and no container of ours is up:
#: none at all, or one Docker Desktop stopped when it quit (PAD-203).
_NO_CONTAINER = ("No such container", "is not running")


def container_note(text):
    """One sentence for a macOS step that ran before the container was up,
    or "" when that is not what happened.

    A run that WRITES starts the container itself; the preview deliberately
    does not (it redraws on every keystroke and must not build an image
    behind the user), so on a Mac every preview step before the session's
    first build dies on Docker's own "No such container:
    pad-multiboot-worker".  That line reads like a broken app rather than a
    step waiting for one - :meth:`MultibootPanel._run_commands` always meant
    it to "say so, once", and this is what it says.
    """
    if not _mac.enabled() or not any(m in (text or "")
                                     for m in _NO_CONTAINER):
        return ""
    return ("The Linux container this Mac runs the tools in is not up yet. "
            "Build / flash card... starts it (and builds its image the "
            "first time); the preview and the size check never start one "
            "behind you, so they stay blank until it is up.")


def root_command(args, cwd=None, exe="python3"):
    """The argv of a tool step that must run as root (build, update: they
    loop-mount the card's partitions - item 93) - as a CALLABLE the worker
    resolves just before the step, because the desktop user's WSL home is
    two ``wsl.exe`` probes (:func:`emulate_tab.wsl_account`) and must never
    run on the Tk thread.  No answer at all -> the step fails with a
    sentence, not a hang.

    A DISTRO WHOSE DEFAULT ACCOUNT IS ROOT has no desktop home to carry, and
    needs none: ``~`` has meant root's home in every other step of the same
    run (the selector goes to /root/spike2root, and that is where this step
    must look for it), so root's own home is the right one and the run goes
    ahead.  Until PAD-114 that machine got the sentence below instead -
    "check that WSL starts" on a WSL that had just built the menu program,
    rendered the preview and planned the card - and could never build one.
    """
    if sys.platform != "win32":
        return wsl_command_root(args, cwd, exe)

    def later(_texts):
        return wsl_command_root(args, cwd, exe, home=_root_step_home())
    return later


def root_shell_line(line, cwd=None):
    """The argv of a SHELL-LINE step that must run as root - the JJP
    selector step, which mounts the ISO's root to build the menu program
    against (item 118) - as :func:`root_command` shapes it: a callable
    resolved just before the step, the desktop user's WSL home carried."""
    if cwd is None:
        cwd = wsl(repo_dir())
    full = "cd %s && %s" % (_q(cwd), line)
    if sys.platform != "win32":
        return wsl_shell_root(full)

    def later(_texts):
        home = wsl_home()
        if not home:
            user, root_home = wsl_account()
            if user != "root":
                raise RuntimeError(
                    "cannot find your WSL home (wsl.exe -e whoami / getent "
                    "both failed) - this step runs as root and needs it; "
                    "check that WSL starts, then try again")
            home = root_home or None
        return wsl_shell_root(full, home)
    return later


def step_command(label, args, form, cwd=None):
    """One tool step as the form's platform runs it: as root when the
    backend says that step needs it (a JJP build mounts things; a Stern
    build loop-mounts the card's partitions), as the user otherwise."""
    if label in backend_for(form).root_steps:
        return root_command(args, cwd)
    return wsl_command(args, cwd)


def _root_step_home():
    """The HOME a root step carries (see :func:`root_command`): the desktop
    user's, or root's own on a root-default distro - ``None`` when root's
    passwd row could not be read, because ``wsl -u root`` sets that one
    itself.  Raises RuntimeError, in a sentence, when WSL would not say who
    it logs in as.  On the worker only: it is two ``wsl.exe`` probes."""
    home = wsl_home()
    if home:
        return home
    user, root_home = wsl_account()
    if user != "root":
        raise RuntimeError(
            "cannot find your WSL home (wsl.exe -e whoami / getent "
            "both failed) - the card is written as root and needs it "
            "to find ~/spike2root; check that WSL starts, then try "
            "again")
    return root_home or None


def menu_card_image_path(drive):
    """Where the boot menu read off *drive* (a ``core.drives.PhysicalDrive``) lands: a
    sparse image named for the card, under the same TEMP directory the tools' caches use,
    so a re-read of the same card lands in the same place and nothing lands in a project
    folder.  Only the menu's ranges are in it (item 99) - the file is a few hundred MB on
    disk however big the card."""
    model = re.sub(r"[^A-Za-z0-9._-]+", "_", (getattr(drive, "model", "") or "card").strip()) or "card"
    size = int(getattr(drive, "size_bytes", 0) or 0)
    name = "%s-%dG.menu.raw" % (model, round(size / 1e9)) if size else "%s.menu.raw" % model
    return os.path.join(tempfile.gettempdir(), "pinball_spike2_multiboot", "cards", name)


def card_drives():
    """The SD cards a menu can be read off: ``(drives, best, reason)`` from the app's own
    drive picker (core.drives), the small-card preference - the reader, never a backup
    SSD.  Empty when nothing removable is connected."""
    from ..core import drives as _drives
    found = _drives.list_physical_drives()
    best, _conf, why = _drives.pick_best_game_ssd(found, prefer="sd_card")
    shown = _drives.visible_drives(found, prefer="sd_card", keep=(best,) if best else ())
    return list(shown), best, why or ""


def cache_dir_args():
    """``--cache-dir`` for plan/build/update (item 93): where the tools keep
    the hashed manifests of the source cards - the Windows TEMP directory
    seen from WSL, so the same cache serves the user's plan and root's
    build, and nothing lands under either one's $HOME."""
    # macOS: under the container's /tmp mount, not the host's own temp
    # (which is a /var/folders path Docker Desktop does not share).
    base = _mac.cache_root() if _mac.enabled() else tempfile.gettempdir()
    d = os.path.join(base, "pinball_spike2_multiboot")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:                                 # pragma: no cover
        pass
    return ["--cache-dir", wsl(d)]


def ensure_selector_line(selector_dir, src_dir, build_dir=PREVIEW_BUILD_DIR,
                         rootfs=None, card="", platform="stern"):
    """The shell line that ends with ``[preview] selector: <binary>``: build
    the selector from *src_dir* into *build_dir* (``make`` is incremental -
    a no-op once built, so the preview always draws with THIS checkout's
    selector), or when that fails (no cross compiler) fall back to the
    tab's installed selector build; neither installs anything.

    *card* is the one exception, and it is a machine that has no guest
    filesystem at all: see the comment below, where ensureselect.sh unpacks
    one and does install a selector, because nothing can be compiled until
    it has.  No ``$``: wsl.exe would eat it."""
    if backend_for(platform).key == "jjp":
        # ensurejjpselect.sh builds jjpselect, installs it where the builder
        # looks and prints the preview's line as well as the card's (item
        # 118).  --PREVIEW, because this step runs on every load and redraw
        # and must never restore an image: it used to hand a loaded
        # multi-boot ISO to the rig's mount.sh, which restored all 13 GB of
        # it to compile a program the ISO already carries (David, 2026-09-15:
        # "it should just be touching the multi-boot menu portion, not the
        # whole entire image").  With no JJP root on this PC the preview
        # draws with the ISO's own jjpselect, or the installed one; a writing
        # run's step (install_selector_line) still builds a current one.  No
        # ISO is no refusal here: an installed program draws a form that has
        # none yet.
        be = backend_for(platform)
        return "bash %s --preview %s %s" % (_q(be.ensure_tool), _q(card or ""),
                                           _q(jjp_selector_dir(selector_dir)))
    rootfs = rootfs or rootfs_for(selector_dir)
    built = build_dir.rstrip("/") + "/codeselect"
    installed = (selector_dir or DEFAULT_SELECTOR_DIR).rstrip("/") \
        + "/codeselect"
    tag = _q(SELECTOR_LINE)
    lib = rootfs.rstrip("/") + "/usr/lib"
    # A MACHINE THAT HAS NEVER UNPACKED ONE CANNOT BUILD ANYTHING, and that
    # is not what the old sentence said.  The menu program is cross-compiled
    # against the CARD's own headers and libraries (-nostdinc -isystem
    # <rootfs>/usr/include, and the card's own crt1.o), so with no guest
    # filesystem the make dies on `stdio.h: No such file or directory`, the
    # fallback finds no installed selector either, and the preview reported
    #
    #   [preview] error: no selector - the build failed and
    #   ~/spike2root/usr/local/codeselect/codeselect is not there
    #
    # which names the SYMPTOM's path and never the missing filesystem.  A
    # freshly imported runtime is exactly this machine, so somebody who had
    # only ever loaded a card - never run the emulator - could not preview
    # at all (2026-09-09, on a multi-boot card built by somebody else).
    #
    # So ask the question the rest of the app already asks, with the rest of
    # the app's own answer: ensureselect.sh unpacks the filesystem from a
    # card, builds the menu program and installs it (minutes, once).  It is
    # NEVER fatal here - a preview would rather fall through to whatever is
    # installed than stop - and it runs only when the filesystem is missing,
    # so a healthy machine pays one `[ -d ]` per keystroke render.
    ensure = ""
    if card:
        ensure = ("if [ ! -d %s ] && [ -f %s ]; then PAD_ROOT=%s bash %s %s; "
                  "fi; " % (_q(lib), _q(card), _q(rootfs), _q(ENSURESELECT),
                            _q(card)))
    # ...AND THE TOOL THAT RUNS THE BUILD, asked last because it is asked
    # only of a machine where everything else was in place: `make` is what
    # this line's first word IS, so a PC without one fails here with
    # `make: command not found` and then again in the fallback's sentence
    # about a build that "failed", which names no package to install
    # (PAD-126).  Nothing about the emulator needs it, so a machine that runs
    # every title can still be this one.
    return (ensure
            + "if make -C %s BUILD=%s ROOT=%s all; then echo %s %s; "
              "elif [ -x %s ]; then echo %s %s; "
              "elif [ ! -d %s ]; then echo %s; exit 1; "
              "elif ! command -v make >/dev/null 2>&1; then echo %s; exit 1; "
              "else echo %s; exit 1; fi"
            % (_q(src_dir), _q(build_dir), _q(rootfs), tag, _q(built),
               _q(installed), tag, _q(installed), _q(lib),
               _q("[preview] error: no selector - the menu program is built "
                  "against the machine's own filesystem, and this PC has not "
                  "unpacked one yet (nothing at %s). Point the tab at a card "
                  "image that is on this PC and preview again and it is "
                  "built for you, once." % rootfs),
               _q("[preview] error: no selector - the menu program is built "
                  "by a Makefile and this Linux has no make (on "
                  "Debian/Ubuntu: apt install make). Nothing else about the "
                  "emulator needs it, which is why a PC that runs games can "
                  "still be missing it."),
               _q("[preview] error: no selector - the build failed and %s "
                  "is not there" % installed)))


def selector_card(form, loaded_card=""):
    """The card image the selector step may unpack a guest filesystem from,
    or ``''`` when neither candidate is on this machine.

    THE LOADED CARD COMES FIRST, and that order is the whole point: a card
    somebody else built names its images' sources on THEIR machine, so
    ``images[0].path`` is a path that is not here, while the card file the
    tab was just pointed at - the download, or the menu read off the SD
    card - is.  A menu read is p1+p2 and p2 IS the filesystem, so even the
    few-hundred-MB menu image is enough to build one from."""
    rows = getattr(form, "images", None) or []
    first = getattr(rows[0], "path", "") if rows else ""
    for cand in (loaded_card, first):
        cand = (cand or "").strip().strip('"')
        if cand and os.path.isfile(cand):
            return cand
    return ""


def ensure_selector_args(form, cwd=None, card=""):
    """The 'selector' step's argv (see :func:`ensure_selector_line`).  As
    root on JJP: the menu program is built against the ISO's mounted root."""
    if cwd is None:
        cwd = wsl(repo_dir())
    be = backend_for(form)
    line = ensure_selector_line(form.selector_dir, cwd + "/" + CODESELECT_SRC,
                                card=wsl(card) if card else "", platform=be.key)
    if "selector" in be.root_steps:
        return root_shell_line(line, cwd)
    return wsl_shell("cd %s && %s" % (_q(cwd), line))


def parse_selector_path(text):
    """The binary the 'selector' step named, or ''."""
    for line in (text or "").splitlines():
        if line.startswith(SELECTOR_LINE):
            return line[len(SELECTOR_LINE):].strip()
    return ""


def install_selector_line(selector_dir, card="", tool=ENSURESELECT, platform="stern"):
    """THE CARD'S OWN SELECTOR STEP, and the first thing every writing run
    does: make sure the menu program is INSTALLED in the directory
    ``--selector-dir`` names, and build it there when it is not.

    The preview's :func:`ensure_selector_line` builds a selector into a
    scratch directory and installs nothing, so a person could fill this tab
    in, watch their own menu animate, press Build and get the builder's
    refusal seconds later - ``selector dir ~/spike2root/usr/local/codeselect
    is not a directory`` - with nothing in it to act on (PAD-105).  Nothing
    in the app had ever run buildselect.sh.

    ``ensureselect.sh`` is that, and it is the RIG's own answer rather than
    a second copy of it: ensurebuild.sh unpacks the guest filesystem from
    *card* when the machine has none, builds the menu program when it is
    missing, rebuilds it when this app ships newer sources, and leaves what
    is installed alone when a rebuild is not possible.  On Windows it runs
    AS ROOT with the desktop user's HOME (:func:`install_selector_args`,
    PAD-140) and buildselect.sh hands what it installs back to that user,
    so the next rebuild as the user still can.  It writes no card.

    A selector directory that is not a rootfs's own - only
    ``PAD_MULTIBOOT_SELECTOR`` can make one - is CHECKED and never written
    into: the app cannot know what somebody pointed that at.

    JJP (item 118): ``ensurejjpselect.sh <primary ISO> <dir>`` builds
    jjpselect against the ISO's own root (mounted the way the emulator
    mounts it) and installs it in the card's own layout under *dir*; it
    prints the same ready line, and the preview's, so one step serves both.
    """
    be = backend_for(platform)
    if be.key == "jjp":
        sel = jjp_selector_dir(selector_dir)
        if not card:
            return ("echo %s; exit 1"
                    % _q("%s the JJP menu program is built against the primary "
                         "install ISO's own root, and no ISO is on this "
                         "machine to build it from" % SELECTOR_ERROR))
        return "bash %s %s %s" % (_q(be.ensure_tool), _q(card), _q(sel))
    sel = (selector_dir or DEFAULT_SELECTOR_DIR).strip().rstrip("/")
    rootfs = rootfs_for(sel)
    if sel != rootfs + SELECTOR_SUFFIX:
        return ("if [ -x %s ] && [ -f %s ]; then echo %s %s; "
                "else echo %s; exit 1; fi"
                % (_q(sel + "/codeselect"), _q(sel + "/select.sh"),
                   _q(SELECTOR_READY_LINE), _q(sel),
                   _q("%s %s holds no codeselect and select.sh, so a card "
                      "built now would carry no menu. PAD_MULTIBOOT_SELECTOR "
                      "names that directory; clear it to use the one the app "
                      "builds and installs itself." % (SELECTOR_ERROR, sel))))
    return "PAD_ROOT=%s bash %s%s" % (_q(rootfs), _q(tool),
                                      (" " + _q(card)) if card else "")


def install_selector_args(form, cwd=None):
    """The card's 'selector' step argv (see :func:`install_selector_line`).
    The primary image rides along: it is what the guest filesystem is
    unpacked from on a machine that has never made one.

    AS ROOT ON WINDOWS, with the desktop user's HOME - a callable the worker
    resolves, for :func:`root_command`'s reason (PAD-140).  This step
    INSTALLS into the guest filesystem, and on Windows that filesystem is
    usually root's: the Emulate tab's Start is ``wsl -u root`` and debugfs
    unpacks as root, so anybody who had run a game once could never create
    ``/usr/local/codeselect`` in it, and their first multi-boot build
    stopped on coreutils' account of that failed mkdir -

        install: cannot change permissions of
        '/home/home/spike2root/usr/local/codeselect': No such file or directory

    buildselect.sh hands everything it installs back to the owner of HOME,
    so the menu program is the user's either way.  A probe that cannot say
    who WSL logs in as degrades to the user step this used to be (the build
    step after it says the sentence).  Linux keeps the user: nothing there
    unpacks the filesystem as root."""
    if cwd is None:
        cwd = wsl(repo_dir())
    be = backend_for(form)
    card = (form.images[0].path.strip().strip('"') if form.images else "")
    line = install_selector_line(form.selector_dir,
                                 wsl(card) if card else "", platform=be.key)
    if "selector" in be.root_steps:
        return root_shell_line(line, cwd)
    # THE STERN CARD'S STEP exactly as main runs it (PAD-140): root with the
    # desktop user's HOME, the user step when WSL would not say who it logs
    # in as.  install_selector_line's Stern branch is main's line unchanged.
    line = "cd %s && %s" % (_q(cwd), line)
    if sys.platform != "win32":
        return wsl_shell(line)

    def later(_texts):
        try:
            home = _root_step_home()
        except RuntimeError:
            return wsl_shell(line)
        return wsl_shell_root(line, home)
    return later


def install_selector_commands(form, cwd=None):
    """The 'selector' step, as the one-item command list every writing run
    starts with."""
    return [("selector", install_selector_args(form, cwd))]


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
#: ...and at the end of the same line, WHERE EVERY VISIBLE ANIMATED CARD'S
#: PICTURE IS in that frame (``pictures i:x,y,w,h;j:x,y,w,h``, or
#: ``pictures none``): the rectangles the selector blitted the GIF frames
#: into, which is where the clips are laid (see :class:`ClipFrames`).
#: Anchored on the footer's closing quote so a title cannot forge it.
_SNAP_PICTURES_RE = re.compile(r'", pictures (\S+)\s*$')
_PICTURE_RE = re.compile(r'^(\d+):(\d+),(\d+),(\d+),(\d+)$')


def parse_snapshot_pictures(text):
    """``{image: (x, y, w, h)}`` for every visible animated card in the
    LAST frame a snapshot run wrote - ``{}`` when none animates, or the
    selector was built before it said.  The rectangles are the same for
    every frame of one run, so the last line is the run's answer."""
    rects = {}
    for line in (text or "").splitlines():
        if not _SNAP_RE.search(line):
            continue
        rects = {}
        m = _SNAP_PICTURES_RE.search(line)
        if not m or m.group(1) == "none":
            continue
        for item in m.group(1).split(";"):
            p = _PICTURE_RE.match(item)
            if p:
                rects[int(p.group(1))] = tuple(int(v) for v in p.groups()[1:])
    return rects


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
    # ONE image LINE PER GAME and one card per ROW, exactly as the built card
    # has them - a preview that drew a group as a single image line would show
    # the right picture for the wrong reason and would stop matching the moment
    # the member count mattered.  The media names are keyed by IMAGE, because
    # that is how prepare wrote them, and a group card borrows its first
    # member's - the same rule mkmulticard follows.
    be = backend_for(form)
    trees = form_trees(form)
    names = card_media_names(form)
    per_row = {}
    # the conf's own fields, in the selector's order
    for img, path, ri, mi in trees:
        per_row.setdefault(ri, []).append((img, path, mi))
    groups = {ri: imgs for _gi, ri, _row, imgs in form_groups(form)}
    # THE ROWS ARE THE CARDS, so this walks rows: a KEEPING group puts no game
    # on the card at all, and a preview that only walked the games drew David's
    # `C1 | C2 | RANDOM` with no random card in it.
    for ri, row in enumerate(form.images):
        art, anim, music, _confirm = names[ri]
        if is_group(row):
            imgs = groups.get(ri) or []
            if len(imgs) >= 2:
                lines.append("group=%s%s%d-%d|%s|%s|%s|%s|%s" % (
                    "+" if row.keep else "",
                    "" if row_roll(row) == ROLL_FALLBACK else row_roll(row) + ":",
                    min(imgs), max(imgs),
                    (row.title or "").strip() or "GROUP",
                    (row.subtitle or "").strip(), art, anim, music))
            if row.keep:
                continue                      # its games are other rows'
        for img, path, mi in per_row.get(ri, []):
            dev = be.device(img)
            if mi is None:
                title = (row.title or "").strip() or suggest_title(path, be.key)[0]
                lines.append("image=%s|%s|%s|%s|%s|%s" % (
                    dev, title, (row.subtitle or "").strip(), art, anim, music))
            else:
                m = row.members[mi]
                title = (m.title or "").strip() or suggest_title(path, be.key)[0]
                lines.append("image=%s|%s||||" % (dev, title))
    lines += ["default=%d" % row_first_image(form, int(form.default)),
              "timeout=%d" % int(form.timeout),
              "heading=%s" % (form.heading or "").strip(),
              # the preview draws the card's text the size the CARD will:
              # the tick is part of what a frame depends on (PAD-183)
              "text_size=%s" % (TEXT_SIZE_UNIFORM if form.same_text_size
                                else TEXT_SIZE_PER_CARD),
              # ...and the two lines under the cards the same way (PAD-190):
              # a preview that still counted the cards, or still said
              # 'starting', would not be a picture of this card
              "counter=%s" % (COUNTER_ON if form.show_counter
                              else COUNTER_OFF),
              "countdown_word=%s" % (form.countdown_word or "").strip(),
              "volume=%d" % int(form.volume),
              "font=" + be.conf_font]
    # ...and the instructions line, EXCEPT when it is the selector's own: no
    # key is what a card carries for that, and it is what the preview must
    # carry too, or a frame would name buttons the machine may not have
    if not form.show_footer:
        lines.append("footer=")
    elif (form.footer or "").strip():
        lines.append("footer=%s" % (form.footer or "").strip())
    lines += theme_conf_lines(form)
    return "\n".join(lines) + "\n"


def preview_fingerprint(form):
    """What a rendered frame depends on, as a short hash: the conf text
    (titles, subtitles, media names, default, countdown), the images and
    their art / animation specs, the selector and the output.  A frame
    cached under one fingerprint is never shown for another form."""
    data = [write_preview_conf(form),
            [((r.path or "").strip(),
              group_art_spec(r) if is_group(r) else art_spec(r),
              group_anim_spec(r) if is_group(r) else anim_spec(r),
              # a member change is a different picture list, so it must be a
              # different fingerprint or a stale frame is shown for it
              row_paths(r) if is_group(r) else None)
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
    data = [[((r.path or "").strip(),
              group_art_spec(r) if is_group(r) else art_spec(r),
              group_anim_spec(r) if is_group(r) else anim_spec(r),
              _media_value(r.music), confirm_spec(r), bool(r.art_on_card),
              bool(r.anim_on_card), bool(r.music_on_card),
              bool(r.confirm_on_card),
              # A RANDOM CARD'S PICTURE IS DRAWN FROM ITS MEMBERS, so its
              # member list is part of what the media depends on - without it,
              # adding a song set to a jukebox left the old picture up.
              row_paths(r) if is_group(r) else None)
             for r in form.images],
            _media_value(form.sound_move), _media_value(form.sound_confirm),
            int(form.volume)]
    return hashlib.sha1(json.dumps(data).encode("utf-8")).hexdigest()[:12]


def media_source_paths(form):
    """Every FILE the form's media fields name, as typed: pictures, clips,
    music beds and sounds - the words (auto, none, synth, auto@N...) are not
    files and are left out.

    For the Mac container's bind mounts (PAD-196).  The ISOs and the output
    were mounted and these were not, so a picture on the Desktop was "not a
    file" to the prepare inside the container, no media.json was written, and
    the build went on to make a text-only menu for somebody who had picked a
    picture and a song for each image."""
    vals = []
    for r in form.images:
        vals += [r.art, r.art_video, r.anim, r.music, r.confirm]
    vals += [form.sound_move, form.sound_confirm]
    out = []
    for v in vals:
        v = (v or "").strip().strip('"')
        if not v or v.lower() in _WORDS or _AUTO_IDX_RE.match(v):
            continue
        out.append(v)
    return out


def form_wants_media(form):
    """Whether the menu this form describes has anything but text in it: a
    picture, a clip, a music bed or a sound on any image.  A form that asks
    for none of them builds a text-only menu on purpose; any other form
    that reaches a build with no prepared media has lost something."""
    for r in form.images:
        art = group_art_spec(r) if is_group(r) else (r.art or "").strip()
        anim = group_anim_spec(r) if is_group(r) else (r.anim or "").strip()
        for v in (art, anim, r.music):
            if (v or "").strip().strip('"').lower() not in ("", "none"):
                return True
    return any((v or "").strip().strip('"').lower() not in ("", "none")
               for v in (form.sound_move, form.sound_confirm))


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


def build_commands(form, cwd=None, prepare=False):
    """The 'Build & verify' run: the selector (the menu program the card
    will carry, built and installed when this machine has not got one -
    :func:`install_selector_line`), the media when *prepare* asks for it,
    plan (the size, before a byte is written), build - AS ROOT, it
    loop-mounts nothing yet but records the card the way update needs (item
    93) - verify.  ``[(label, argv), ...]``, run in order, stop on failure.

    THE SELECTOR GOES FIRST, before even the media: it is the one thing
    here that a machine can be missing outright, the builder does not ask
    for it until seconds into the build, and a run that cannot get a menu
    program must not first spend a minute rendering pictures for one
    (PAD-105)."""
    cmds = install_selector_commands(form, cwd)
    if prepare:
        cmds += prepare_commands(form, form.media_dir, cwd)
    return cmds + [
        ("plan", step_command("plan", plan_args(form), form, cwd)),
        ("build", step_command("build", build_args(form), form, cwd)),
        ("verify", step_command("verify", verify_args(form), form, cwd))]


#: The label of the size check's second step: ``update --dry-run`` on the
#: loaded card, whose rows say what an in-place update would write.
DRY_RUN = "dry-run"


def measure_commands(form, card=None, cwd=None):
    """The automatic size check: the plan, and - when a card that can be
    updated in place is loaded - what an update of it would write.  Both
    run as the user and write nothing."""
    cmds = plan_commands(form, cwd)
    if card:
        cmds.append((DRY_RUN, wsl_command(update_args(form, card, dry_run=True), cwd)))
    return cmds


def update_commands(form, card, media_dir="", prepare=False, expect_bytes=None, cwd=None):
    """The in-place update run: the selector (``update`` re-injects the menu
    program, so it needs one), the media when a media field changed, then
    ``update`` AS ROOT (it re-injects the menu, patches the validator and
    verifies by itself), then the inspect that reads the card back."""
    cmds = install_selector_commands(form, cwd)
    if prepare:
        cmds += prepare_commands(form, media_dir, cwd)
    cmds.append(("update", root_command(update_args(form, card, expect_bytes=expect_bytes), cwd)))
    cmds += inspect_commands(card, cwd=cwd)
    return cmds


def prepare_commands(form, media_dir, cwd=None):
    return [("prepare", step_command("prepare", prepare_args(form, media_dir), form, cwd))]


def preview_prepare_commands(form, media_dir, cwd=None):
    """The preview's VIDEO step: the pictures, the animations and the
    music beds (``--visual-only``) - what the frame needs to be drawn."""
    return [(VIDEO_LABEL, step_command("prepare", preview_prepare_args(form, media_dir),
                                       form, cwd))]


def audio_prepare_commands(form, media_dir, cwd=None):
    """The preview's AUDIO step: the full prepare, which adds the move and
    confirm sounds (pulled off the card through the emulator's params
    cache - the slow half, and the half that can be refused).  The same
    run as :func:`prepare_commands`, labelled for the strip."""
    return [(AUDIO_LABEL, step_command("prepare", prepare_args(form, media_dir), form, cwd))]


def ensure_selector_commands(form, cwd=None, card=""):
    return [("selector", ensure_selector_args(form, cwd, card))]


def snapshot_commands(binary, conf, media_dir, ppm, highlight, frame,
                      rootfs=DEFAULT_ROOTFS, cwd=None, frames=1, loading=None,
                      roll_state=None, platform="stern"):
    """One snapshot step.  A run of frames is ONE step and is labelled
    :data:`ANIM_LABEL` - what a failure of it is named after, and what the
    finished step's own output is read back through."""
    label = (ANIM_LABEL if int(frames) > 1 else "frame %d" % int(frame))
    return [(label,
             wsl_command(preview_snapshot_args(binary, conf, media_dir, ppm,
                                               highlight, frame, rootfs,
                                               frames, loading, roll_state,
                                               platform=platform),
                         cwd, exe=None))]


def plan_commands(form, cwd=None):
    return [("plan", wsl_command(plan_args(form), cwd))]


def bypass_commands(card, cwd=None):
    return [("bypass", wsl_command(bypass_args(card), cwd))]


#: The label of the inspect run whose stdout is JSON.  Its output is parsed,
#: not echoed (the pane gets the table the plain run prints instead) - see
#: MultibootPanel._run_commands' ``quiet``.
INSPECT_JSON = "inspect json"


def inspect_commands(card, media_out=None, cwd=None, platform="stern"):
    """The 'Load card…' run: the tool's own table into the pane, then the
    same read as JSON (with the media extracted, when asked) for the form.
    Two reads of a few small files - the card is never written."""
    return [("inspect", wsl_command(inspect_args(card, platform=platform), cwd)),
            (INSPECT_JSON, wsl_command(
                inspect_args(card, media_out, as_json=True, platform=platform), cwd))]


def extract_args(card, out_dir, media_out=None, indexes=()):
    """``mkmulticard.py extract --card``: the card's images written back out
    as stock-shaped .raw files of their own (the games tree as p3, the menu
    taken out of p2), each named after the .raw the card records it was
    built from, plus the card's menu media copied flat into *media_out*.
    Reads the card; writes only into *out_dir*."""
    args = [MKMULTICARD, "extract", "--card", wsl(card.strip().strip('"')),
            "--out-dir", wsl(out_dir)]
    for i in indexes:
        args += ["--image", str(int(i))]
    if media_out:
        args += ["--media-out", wsl(media_out)]
    return args


def extract_commands(card, out_dir, media_out=None, indexes=(), cwd=None):
    """The 'Recover images…' run: one tool step, as the user (debugfs and
    mke2fs need no root to read a card and write files)."""
    return [("extract", wsl_command(extract_args(card, out_dir, media_out,
                                                 indexes), cwd))]


#: What the tool prints for each image it wrote out, and for the media.
_EXTRACT_IMAGE_RE = re.compile(r"^\[extract\] image (\d+): (.+)$")
_EXTRACT_MEDIA_RE = re.compile(r"^\[extract\] media: (.+)$")


def parse_extract(text):
    """``({index: host path}, media dir or '')`` from what ``extract``
    printed - the files the rows are pointed at afterwards."""
    mapping, media = {}, ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        m = _EXTRACT_IMAGE_RE.match(line)
        if m:
            mapping[int(m.group(1))] = host_path(m.group(2).strip())
            continue
        m = _EXTRACT_MEDIA_RE.match(line)
        if m:
            media = host_path(m.group(1).strip())
    return mapping, media


def recovered_media_dirname(card):
    """Where a recovery puts the card's own menu media, inside the folder
    chosen for the images: ``<card stem>.menu-media``.  Never plain
    ``media`` - that is where a build at that folder would RENDER, and a
    prepare must never read its inputs out of the directory it writes."""
    base = os.path.basename((card or "").strip().strip('"'))
    stem = re.sub(r"\.(raw|img)$", "", base, flags=re.I) or "card"
    return stem + ".menu-media"


def recoverable_indexes(rows, info):
    """The rows a 'Recover images…' can act on: the .raw is not on this
    machine (or was never recorded) and the loaded card carries the games
    tree - which the reader's menu-only image does not, so a card read that
    way has nothing to recover from until it is read whole."""
    out = []
    images = (info or {}).get("images") or []
    for i, row in enumerate(rows or ()):
        p = (getattr(row, "path", "") or "").strip().strip('"')
        if p and os.path.isfile(p):
            continue
        im = images[i] if i < len(images) and isinstance(images[i], dict) \
            else {}
        if im.get("title_dir"):
            out.append(i)
    return out


def recover_rows(rows, mapping, media_dir="", info=None):
    """Point the rows at what a recovery wrote: image *i*'s path at
    ``mapping[i]``, and every media field that was '(on the card)' - or was
    made from a file that is not on this machine - at the copy of the
    card's own file in *media_dir* (the name the inspect report *info* gives
    that field), a plain file choice from then on.  So a fresh card can be
    built with the pictures and sounds this one has, and a media change
    re-renders from files that are not in the directory the prepare writes
    into.  Applied to the live rows AND the loaded baseline, so a recovery
    is not itself a change.  -> the lines saying what moved."""
    notes = []
    images = (info or {}).get("images") or []
    for i, row in enumerate(rows or ()):
        if i in mapping:
            row.path = mapping[i]
            notes.append("image %d: %s" % (i, mapping[i]))
        if not media_dir:
            continue
        im = images[i] if i < len(images) and isinstance(images[i], dict) \
            else {}
        for what, key in (("art", "art"), ("animation", "anim"),
                          ("music", "music"), ("confirm sound", "confirm")):
            val = (getattr(row, key) or "").strip().strip('"')
            if getattr(row, key + "_on_card"):
                name = val
            else:
                spec = row.art_video if (key == "art" and val.lower()
                                         == "video frame") else val
                if not is_file_choice(spec) or os.path.isfile(spec):
                    continue                # a word, or a file that is here
                name = (im.get(key) or "").strip()
            path = os.path.join(media_dir, name) if name else ""
            if name and os.path.isfile(path):
                setattr(row, key, path)
                setattr(row, key + "_on_card", False)
                if key == "art":
                    row.art_video, row.art_time = "", ""
                elif key == "anim":
                    row.anim_start = ""
                notes.append("image %d: the %s is %s" % (i, what, path))
    return notes


def recover_sound(value, media_dir, name):
    """The menu-wide move / confirm sound after a recovery: when *value* is
    a file that is not on this machine and the card's own WAV (*name*, in
    the recovered media dir) is, that WAV - else None, the field untouched.
    A word ('auto', 'synth', 'none') is never a file and stays."""
    v = (value or "").strip().strip('"')
    if not is_file_choice(v) or os.path.isfile(v) or not media_dir:
        return None
    path = os.path.join(media_dir, name)
    return path if os.path.isfile(path) else None


#: The two menu-wide sounds' file names on the card, by form field.
MENU_SOUND_FILES = (("sound_move", "move.wav"), ("sound_confirm", "confirm.wav"))


#: validate_form's sentences about a media FILE that is not on this machine.
_IMAGE_FILE_ERR_RE = re.compile(r"^Image \d+: (art|animation|music) file not found: ")
_SOUND_FILE_ERR_RE = re.compile(r"^The (move|confirm) sound file was not found: ")


def sound_file_errors(errs):
    """Of :func:`validate_form`'s sentences, the ones about a menu-wide
    sound file that is not on this machine - what a PICTURE never needs:
    the render is --visual-only, and a loaded card's sounds are already in
    its media dir."""
    return [e for e in errs if _SOUND_FILE_ERR_RE.match(e)]


def media_file_errors(errs):
    """...and the ones about ANY media file that is not on this machine -
    what a picture does not need either while nothing has to be rendered
    again: a loaded card whose media fields are still the card's own is
    drawn from the files the load extracted, whatever the videos and WAVs
    they were made from (David's downloaded card: every one on the other
    person's G:, and 'art file not found' stopped the menu being drawn)."""
    return [e for e in errs if _IMAGE_FILE_ERR_RE.match(e) or _SOUND_FILE_ERR_RE.match(e)]


def inject_commands(form, card, cwd=None):
    return [("inject", step_command("inject", inject_args(form, card), form, cwd))]


def apply_commands(form, card, media_dir="", prepare=False, bypass=False,
                   refresh=True, cwd=None):
    """The 'Apply to card' run: the selector (the injection writes the menu
    program itself onto the card, so it needs one), the media when a media
    field changed (into the dir the load extracted, so selectmedia's cache
    keeps the unchanged pictures), the menu injected into the card in place,
    the validator bypass when it is ticked and some tree is still armed, and
    a last inspect that reads the card back."""
    cmds = install_selector_commands(form, cwd)
    if prepare:
        cmds += prepare_commands(form, media_dir, cwd)
    cmds += inject_commands(form, card, cwd)
    if bypass:
        cmds += bypass_commands(card, cwd)
    if refresh:
        cmds += inspect_commands(card, cwd=cwd, platform=backend_for(form).key)
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


#: How a tool spells a refusal.  ``[card] error:`` is what mkmulticard really
#: prints when it will not act (its ``Refused`` handler, on stderr, which the
#: worker merges into the same stream); ``refused:`` is the older spelling and
#: is still what its selftest and the ball tools use.  BOTH, because reading
#: only for the second one is why every failed load on this tab said "see the
#: tool output" and never the reason - the tool had printed the reason.
#: ...and ``[selector] error:`` is ensureselect.sh's, the step that gets the
#: menu program built before any of this runs (:func:`install_selector_line`).
_REFUSAL_PREFIXES = ("[card] error:", SELECTOR_ERROR, "refused:")


def parse_refusal(text, about=""):
    """The tool's own refusal line, without its prefix, or ''.  What a failed
    load says on the tab instead of an exit code.

    *about* is the file the caller names in its own sentence.  The tool leads
    most refusals with the path, and on this tab that is a WSL spelling of a
    path the sentence already carries - long enough to push the actual reason
    off the end of the one line the status block gives it - so a leading path
    that names the same file is dropped."""
    for line in reversed((text or "").splitlines()):
        s = line.strip()
        for prefix in _REFUSAL_PREFIXES:
            if s.lower().startswith(prefix):
                return _drop_path_prefix(s[len(prefix):].strip(), about) or s
    return ""


def _drop_path_prefix(why, about):
    """``'/mnt/c/.../x.raw: no selector on its p2'`` -> ``'no selector on its
    p2'``, and only when the path it leads with names the very file *about*
    does."""
    head, sep, tail = (why or "").partition(": ")
    if (sep and tail.strip() and about
            and os.path.basename(head) == os.path.basename(about)):
        return tail.strip()
    return why


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
    """An ``anim_source`` -> ``(anim, start)``; the reverse of
    :func:`anim_spec`, so a load followed by an apply writes what was read.

    A LENGTH OR RATE ON THE CARD IS DROPPED (``auto@20:2:8`` loads as
    ``auto`` from 20 s): the loop's length and rate are the tool's contract
    now, so the next apply renders that clip the way every other one is -
    the whole 5 s at the source's own frame rate."""
    s = (spec or "").strip()
    if not s or s.lower() == "none":
        return "none", ""
    start = ""
    base, sep, tail = s.rpartition("@")
    if sep and base and tail and _CLIP_RE.match(tail):
        start = tail.split(":")[0]
        s = base
    return ("auto" if s.lower() == "auto" else host_path(s)), start


def split_sound_source(spec, what, source=None):
    """A ``sound_move`` / ``sound_confirm`` from the card -> ``(value,
    note)``.

    *spec* is the WAV the selector plays (``move.wav``) - what images.conf
    and build.json record - and *source* is what MADE it, which the card's
    media.json has recorded since the sounds learned to re-render and which
    ``inspect`` now hands over.  The source wins whenever there is one: a
    field holding the file name it produced is a field that can only ever
    look stale, and it made a loaded card report every sound as missing
    while the wavs sat in its media directory.

    Without one (a card built before media.json carried them) a bare name
    still means 'this card has a move sound, and which file made it is not
    written down': the field shows the tab's default and says so.  Nothing
    acts on it until a media change makes the tools run again, and the sound
    already on the card is untouched until then."""
    src = (source or "").strip()
    if src:
        if src.lower() in _WORDS or _AUTO_IDX_RE.match(src):
            return src.lower(), ""
        # The path comes back AS RECORDED even when it is not on this
        # machine (a drive not plugged in, or a card built on someone
        # else's): the preview draws without the sounds' sources, and a
        # recovery points the field at the card's own WAV (recover_sound).
        return host_path(src), ""
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


def is_menu_image(path):
    """True for an image that holds only the boot MENU read off an SD card
    (:func:`menu_card_image_path`, item 99).  Its games partitions are holes
    by design, so no tree on it can be read - which says nothing about the
    card's game code (PAD-197)."""
    return os.path.basename((path or "").strip().strip('"')).lower() \
        .endswith(".menu.raw")


#: What the Log says instead of the strip when the only finding is one a
#: menu-only image cannot help making.
MENU_ONLY_VERSIONS = ("Only the boot menu was read off the SD card, so the "
                      "game code version of each image is not checked here. "
                      "Nothing is wrong with the card.")


def version_alarm(info, menu_only=False):
    """``(headline, full text)`` for the loudest thing the version gate found
    on this card, or ``None`` when its images agree.

    The headline is the one line the strip can hold; the full text is every
    finding the report carries, in the same order, for the Log and the
    tooltip.  Nothing here is derived: an image's version is read off the
    image, and these sentences are written by the tool that read it.

    *menu_only*: the card is a menu read off an SD card (:func:`is_menu_image`).
    Every tree on it is unreadable by construction, so 'could not be read'
    is not a finding about the card and is left out (PAD-197: a red strip
    about a card nobody had changed)."""
    found = [(head, str(info.get(key)).strip())
             for key, head in VERSION_ALARMS if info.get(key)
             and not (menu_only and key == "unknown_version")]
    if not found:
        return None
    return found[0][0], "\n\n".join(t for _h, t in found)


def bypass_state(info):
    """``(ticked, armed)`` from the per-image bypass states an inspect
    reported: ticked when no tree is still armed, armed when at least one
    is (an inject alone never patches a tree, so Apply runs the bypass)."""
    states = [(im or {}).get("bypass") for im in (info.get("images") or [])]
    # 'half' (item 98): the tick is off but the grade restore is still live -
    # a bypass has something left to do there
    armed = any(st in ("armed", "half") for st in states)
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
            row.anim, row.anim_start = split_anim_source(im["anim_source"])
        elif im.get("anim"):
            row.anim, row.anim_on_card = im["anim"], True
        else:
            row.anim = "none"
        if im.get("music_source"):
            row.music = split_music_source(im["music_source"])
        elif im.get("music"):
            row.music, row.music_on_card = im["music"], True
        else:
            row.music = "none"
        if im.get("confirm_source"):
            row.confirm = split_confirm_source(im["confirm_source"])
        elif im.get("confirm"):
            row.confirm, row.confirm_on_card = im["confirm"], True
        else:
            row.confirm = ""
        # A SOURCE THAT IS ON SOMEBODY ELSE'S MACHINE (a card downloaded
        # from another user records the videos and WAVs its pictures were
        # made from on THEIR disk) comes back AS RECORDED, like a drive that
        # is not plugged in - a load followed by an apply must write what
        # was read.  It is SAID, once per field: the preview draws the
        # card's own rendered file regardless (see media_file_errors), and
        # a recovery points the field at that file (recover_rows).
        for what, key in (("art", "art"), ("animation", "anim"),
                          ("music", "music"), ("confirm sound", "confirm")):
            val = getattr(row, key)
            if what == "art" and (val or "").strip().lower() == "video frame":
                val = row.art_video
            if (getattr(row, key + "_on_card") or not is_file_choice(val)
                    or os.path.isfile((val or "").strip().strip('"'))):
                continue
            warnings.append(
                "Image %d: its %s was made from %s, which is not on this "
                "machine - the card's own %s is drawn and kept until a media "
                "change asks for it again."
                % (i, what, (val or "").strip(),
                   im.get(key) or ("%s file" % what)))
        if not row.path:
            # the device token says which platform's file this was: a JJP
            # root slot holds an install ISO, a Stern partition a .raw
            what = ("install ISO" if (row.device or "").startswith("root")
                    else ".raw")
            warnings.append("Image %d: this card does not record which %s "
                            "it was built from (%s)."
                            % (i, what, row.device or "no device"))
        elif im.get("source_exists") is False or not os.path.isfile(row.path):
            warnings.append("Image %d: %s is not on this machine - the menu "
                            "can still be changed, but the card cannot be "
                            "rebuilt here." % (i, row.path))
        rows.append(row)
    return group_rows(rows, info.get("groups")), warnings


def group_rows(rows, groups):
    """Fold the images a card's ``groups`` block names back into GROUP ROWS.

    inspect reports one entry per game and a separate groups block (which is
    what mkmulticard writes); the tab's list is CARDS, so a load has to put
    them back together or a loaded jukebox card would come up as N ordinary
    rows and an Apply would flatten it.  A group whose members do not all
    exist in the image list is left alone rather than half-folded - a report
    this tool cannot make sense of must not silently change the card."""
    if not groups:
        return rows
    good, owned = [], {}
    for gi, g in enumerate(groups or []):
        members = [m for m in (g.get("members") or [])
                   if isinstance(m, int) and 0 <= m < len(rows)]
        if len(members) != len(g.get("members") or []) or len(members) < 2:
            continue                       # not one this tool can make sense of
        good.append(gi)
        if not g.get("keep"):
            # only a CONSUMING group takes its members' rows away; a keeping
            # one adds a card in front of rows that stay exactly where they are
            for m in members:
                owned[m] = gi

    def card_for(gi):
        g = groups[gi]
        members = [MemberRow(path=rows[m].path, title=rows[m].title,
                             version=rows[m].version)
                   for m in (g.get("members") or [])]
        card = ImageRow(path="", title=g.get("title") or "RANDOM",
                        subtitle=g.get("subtitle") or "", members=members,
                        keep=bool(g.get("keep")),
                        # HOW IT PICKS comes back with it: a card built before
                        # there was a choice reports none, and that reads as
                        # what such a card does (see row_roll).
                        roll=(g.get("roll") or ""))
        # the card's own media is the group's, not its first member's row
        for key in ("art", "anim", "music", "confirm"):
            val = (g.get(key) or "")
            if val:
                setattr(card, key, val)
                setattr(card, key + "_on_card", True)
        return card

    # a group's card sits where the card says it does: `pos` is the image its
    # line came before, and a group with no pos recorded stands where its
    # members were (which is what a consuming one always did)
    at = {}
    for gi in good:
        g = groups[gi]
        pos = g.get("pos")
        if pos is None:
            pos = min(g.get("members") or [0])
        at.setdefault(int(pos), []).append(gi)
    out = []
    for i, row in enumerate(rows):
        for gi in at.get(i, ()):
            out.append(card_for(gi))
        if i in owned:
            continue                       # a consumed member has no row left
        out.append(row)
    for gi in at.get(len(rows), ()):
        out.append(card_for(gi))
    return out


def form_from_inspect(info, card, media_dir="", selector_dir=None, platform="stern"):
    """The whole report as a :class:`MultibootForm`, plus its warnings:
    what 'Load card…' puts in the form and remembers as the baseline the
    live form is diffed against."""
    be = backend_for(platform)
    rows, warnings = rows_from_inspect(info)
    warnings = list(info.get("warnings") or []) + warnings
    if is_menu_image(card):
        # a menu read off an SD card has no games trees to read, by design;
        # one line in the Log says so instead of one per image (PAD-197)
        warnings = [w for w in warnings if "games tree" not in w]
    if any(on_card_fields(r) for r in rows):
        # One line however many fields: the tree marks each of them '(on the
        # card)', and the point is the same for all - kept and drawn as they
        # are, replaceable, not re-makeable.
        warnings.append(
            "Some media on this card has no source recorded (the rows above "
            "mark it '(on the card)'): it is kept and drawn as it is, and "
            "can be replaced in Edit image… but not re-made from what made "
            "it.")
    move, why = split_sound_source(info.get("sound_move"), "move sound",
                                   info.get("sound_move_source"))
    if why:
        warnings.append(why)
    confirm, why = split_sound_source(info.get("sound_confirm"),
                                      "confirm sound",
                                      info.get("sound_confirm_source"))
    if why:
        warnings.append(why)

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
        machine_volume=(info.get("volume") == "machine"),
        compact=(info.get("layout") == "store"),
        # THE CARD'S OWN HEADING.  null in the report = the card never set
        # one, and what it draws is the selector's line - so that is what the
        # field shows; "" = the card asked for a bare top (PAD-135).
        heading=(DEF_HEADING if info.get("heading") is None
                 else str(info["heading"])),
        # ...and its text size.  null = the card never set the key, which the
        # selector draws as one size for every card, so the tick comes up ON
        # for it exactly as it does for a card that says so (PAD-183).
        same_text_size=(info.get("text_size") != TEXT_SIZE_PER_CARD),
        # ...and the two lines under the cards.  null on either = the card never
        # set the key, and what it draws is the selector's own answer - the
        # counter line and the word 'starting' - so that is what the form shows
        # (PAD-190).  "" on the word is a card that asked for no word at all.
        show_counter=(info.get("counter") != COUNTER_OFF),
        countdown_word=(DEF_COUNTDOWN_WORD if info.get("countdown_word") is None
                        else str(info["countdown_word"])),
        # THE INSTRUCTIONS LINE'S THREE ANSWERS, read back as the two fields
        # that ask them: null = the card never set the key and the selector
        # draws its own line (tick on, box empty); "" = the card asked for no
        # line at all (tick off); anything else is the card's own words.
        show_footer=(info.get("footer") != ""),
        footer=("" if info.get("footer") is None
                else str(info["footer"])),
        default=_int_of("default", 0),
        theme=theme, colors=colors,
        media_dir=media_dir if (media_dir and os.path.isfile(
            os.path.join(media_dir, "media.json"))) else "",
        selector_dir=selector_dir or be.selector_default,
        platform=be.key)
    return form, warnings


#: The menu fields an inject rewrites, in the order the tab names them.
#: Everything NOT here is the image list, and that needs a full build.
#: ('bypass' is not a field any more - the bypass is always on - but it is
#: still the change an armed games tree puts in the list, see
#: MultibootPanel._loaded_diff.)
MENU_FIELD_ORDER = ("title", "subtitle", "art", "animation", "music",
                    "move sound", "confirm sound", "volume", "countdown",
                    "heading", "text size", "card counter", "countdown word",
                    "instructions", "default", "bypass", "theme")

#: Of those, the ones the media has to be rendered again for.
MEDIA_FIELDS = ("art", "animation", "music", "move sound", "confirm sound")


def _row_key(row):
    """What makes an image row THE SAME image: its source file, or the card
    device it came from when this machine does not have the file.

    A GROUP ROW IS ITS MEMBERS.  Adding, removing or swapping one of them
    changes which games are on the card, which only a build can do - so the
    key has to move when they do, or a member change would look like a menu
    edit and an inject would leave the card's games as they were."""
    if is_group(row):
        return "group:" + "|".join(_norm(x) if x else "?" for x in row_paths(row))
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
                       ("machine volume", before.machine_volume,
                        after.machine_volume),
                       ("countdown", before.timeout, after.timeout),
                       ("default", before.default, after.default)):
        if int(b) != int(a):
            changed.add(name)
    if (before.heading or "").strip() != (after.heading or "").strip():
        changed.add("heading")
    if bool(before.same_text_size) != bool(after.same_text_size):
        changed.add("text size")
    if bool(before.show_counter) != bool(after.show_counter):
        changed.add("card counter")
    if ((before.countdown_word or "").strip()
            != (after.countdown_word or "").strip()):
        changed.add("countdown word")
    if footer_args(before) != footer_args(after):
        changed.add("instructions")
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
    if bool(before.compact) != bool(after.compact):
        # the card's layout is not a menu field: only a build changes it
        rebuild.append("compact layout %s" % ("on" if after.compact else "off"))
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
    """The tab's one line about a loaded card: what updating it would write,
    or why only a fresh card can.

    ONE BRANCH of :func:`card_path_state` rather than a second opinion: the
    row's verb and the sentence under it are derived from the same call, so
    they cannot come to disagree about which card is being edited."""
    name = os.path.basename(card) or card
    if rebuild:
        msg = ("The image list changed (%s) - only a fresh card can carry "
               "that; %s rewrites the menu of %s and nothing else."
               % ("; ".join(rebuild), APPLY_TICK, name))
        if menu:
            msg += "  %d menu change%s would ride along: %s." % (
                len(menu), "" if len(menu) == 1 else "s", ", ".join(menu))
        return msg
    if not menu:
        return ("Editing %s: no changes yet. Every field above came off the "
                "card; change one and %s writes it back in seconds."
                % (name, APPLY_TICK))
    return "%d menu change%s (%s) -> %s: %s writes it, no rebuild." % (
        len(menu), "" if len(menu) == 1 else "s", ", ".join(menu), name,
        APPLY_TICK)


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


#: THE STATUS ROW'S CHECKS, in the order the work happens.  ``(key, label)``;
#: :func:`status_checks` decides each one's state and the sentence behind it.
#: Four, because these are the four things that have to be true before an SD
#: card can be written and there is nothing else a person has to know: where
#: the card goes, what is going on it, whether it exists, and whether what
#: exists is what the form says.
STATUS_CHECKS = (("card", "Card image"),
                 ("images", "Images"),
                 ("built", "Built"),
                 ("ready", "Ready to flash"))

#: The mark each state wears, and the THEMES colour it wears it in - the
#: footer's own progress chips speak this language already (``set_phase``:
#: filled and green for done, filled and blue for the one running, hollow and
#: grey for pending), so the row reads as the same kind of thing rather than
#: a second vocabulary to learn.  A blocked check is the app's destructive
#: colour, which is the one colour in here that means "this will not work".
CHECK_MARKS = {"ok": "\u2713", "now": "\u25cf", "no": "\u25cb",
               "bad": "\u00d7"}
CHECK_TONES = {"ok": "success", "now": "accent", "no": "gray", "bad": "error"}


def status_checks(rows, path_state, loaded_card, menu=(), rebuild=(),
                  card="none", built_changes=None, running=""):
    """THE WHOLE OF THE STATUS ROW, decided here: ``[(key, label, state,
    detail)]`` in :data:`STATUS_CHECKS` order.

    *state* is ``"ok"`` (done), ``"now"`` (happening), ``"no"`` (not yet) or
    ``"bad"`` (this will not work); *detail* is the sentence behind the mark,
    which the row carries as that check's tooltip.

    The two lines this replaces said the same thing twice in different words
    (David: "we should consolidate these two, they are almost the same
    thing... make the status something more easily legible with some quick
    check marks") - a live message and a consequence, both about what the
    green button would do, both clipped to one line, and between them they
    still could not say what a person actually wants to know at a glance,
    which is how far along they are.

    PURE, like :func:`card_path_state`, whose sentence it carries for the
    first check: no Tk, no disk, no form validation of its own beyond what
    the caller has already worked out.  THIS IS A DESCRIBER, NOT A GATE -
    ``validate_form``, ``rebuild_blockers`` and the overwrite confirmation
    still decide everything, at press time, on the real paths.

    *card* is what is at the output path, and it has THREE values, not two:
    ``"none"`` (nothing), ``"file"`` (something is there, but this tab has
    not confirmed it is a multi-boot card) and ``"card"`` (it read back as
    one, or this session built it).  The middle one is the whole reason for
    the distinction - David, looking at a tab reporting a finished Built
    over a red Ready: "I don't even understand how I got into this error
    state. So I just need to build the image? If so, then why is built
    checked off?"  It was ticked because a FILE was there, which is not what
    the word means.  There was a 17 GB leftover at that path from a build
    whose inject never ran, and the honest reading of that is that he had
    not built the card yet - so Built does not tick, its sentence says what
    IS there, and nothing is red, because nothing is wrong.

    *built_changes* is ``None`` when this session did not build the card at
    this path, and the ``(menu, rebuild)`` pair from the form it was built
    with when it did - which is the only way to know whether a card nobody
    has read back still matches the form."""
    kind, sentence, _tone, _can_read = path_state
    out = []

    # 1. WHERE THE CARD GOES.  Not keyed off the sentence's tone: a loaded
    # card with an image change is drawn in the error colour by
    # card_path_state, and that is a fact about the CARD, not about the path
    # being a place a card may be written.
    if kind == "empty":
        out.append(("card", "Card image", "no", sentence))
    elif kind in ("library", "is_image", "badname", "unreachable", "dir"):
        out.append(("card", "Card image", "bad", sentence))
    else:
        out.append(("card", "Card image", "ok", sentence))

    # 2. WHAT GOES ON IT.  A card that was LOADED names sources that may
    # live on another machine (the same reason validate_form takes
    # ``sources=False`` for one), so their files are not looked for here.
    n = len(rows or ())
    label = "Images" if not n else "%d image%s" % (n, "" if n == 1 else "s")
    if not n:
        out.append(("images", label, "no",
                    "Add the images below - the first one is the primary, "
                    "and the card path fills itself in from it."))
    elif n < 2:
        out.append(("images", label, "bad",
                    "Add at least two images: the primary (stock) and one "
                    "more. One image is a card, but it is not a menu."))
    else:
        why = ""
        seen = set()
        # EVERY GAME BEHIND EVERY ROW, not every row's own file.  A GROUP row
        # has no path of its own - its games are its members - so reading
        # row.path here reported a perfectly good jukebox card as "Image 1 has
        # no file" and put a red cross on the status row (David, 2026-09-10,
        # looking at the first screenshot of it).
        for i, row in enumerate(rows):
            paths = row_paths(row)
            if is_group(row) and len(paths) < 2:
                why = ("Image %d is a random group with %d game(s); a group "
                       "needs at least 2." % (i, len(paths)))
                break
            # A KEEPING GROUP'S GAMES ARE OTHER ROWS'.  Being listed elsewhere
            # is the POINT of it, so it must not be counted as a duplicate -
            # which is what put a red cross on David's perfectly good card.
            keeping = is_group(row) and getattr(row, "keep", False)
            for k, q in enumerate(paths):
                where = ("Image %d, game %d" % (i, k + 1) if is_group(row)
                         else "Image %d" % i)
                if not q:
                    why = "%s has no file." % where
                elif not loaded_card and not os.path.isfile(q):
                    why = "%s is not on this machine: %s" % (where, q)
                elif keeping:
                    continue
                elif _norm(q) in seen:
                    why = "%s is listed twice: %s" % (where, q)
                else:
                    seen.add(_norm(q))
                    continue
                break
            if why:
                break
        ngames = sum(len(row_paths(r)) for r in rows
                     if not (is_group(r) and getattr(r, "keep", False)))
        detail = "%d images, in the order the menu offers them." % n
        if ngames != n:
            detail = ("%d cards over %d games, in the order the menu offers "
                      "them." % (n, ngames))
        out.append(("images", label, "bad" if why else "ok", why or detail))

    # 3. WHETHER THE CARD EXISTS - a CARD, not a file with the right name.
    name = os.path.basename(loaded_card) or "the card"
    if running in ("build", "apply"):
        out.append(("built", "Built", "now", "Writing the card now."))
    elif card == "card":
        out.append(("built", "Built", "ok",
                    "Built and verified in this session."
                    if built_changes is not None and not loaded_card
                    else "%s read back as a multi-boot card." % name))
    elif card == "file" and kind == "unreadable":
        out.append(("built", "Built", "no", sentence
                    + " Build / flash card... writes over it."))
    elif card == "file":
        out.append(("built", "Built", "no",
                    "There is a file at that path, but nothing has looked "
                    "inside it - %s reads it, and %s writes over it."
                    % (READ_VERB, WRITE_BUTTON)))
    else:
        out.append(("built", "Built", "no",
                    "Nothing at that path yet - Build / flash card... "
                    "writes it."))

    # 4. WHETHER WHAT EXISTS IS WHAT THE FORM SAYS.  The one check that is
    # about the card rather than about the tab, and the one worth a glance
    # before reaching for an SD card.
    changes = list(menu or ()) + list(rebuild or ())
    if card != "card":
        # It FOLLOWS from Built, so it says so and nothing more: two marks
        # both shouting about one missing card is how a person ends up
        # hunting for a second problem that is not there.
        out.append(("ready", "Ready to flash", "no",
                    "Build the card first."))
    elif loaded_card and changes:
        out.append(("ready", "Ready to flash", "no",
                    "%d change%s not on %s yet: %s."
                    % (len(changes), "" if len(changes) == 1 else "s",
                       name, "; ".join(changes))))
    elif built_changes is not None and not loaded_card:
        since = list(built_changes[0] or ()) + list(built_changes[1] or ())
        if since:
            out.append(("ready", "Ready to flash", "no",
                        "%d change%s since it was built: %s."
                        % (len(since), "" if len(since) == 1 else "s",
                           "; ".join(since))))
        else:
            out.append(("ready", "Ready to flash", "ok",
                        "Built and verified in this session - flash it."))
    else:
        out.append(("ready", "Ready to flash", "ok",
                    "%s matches this form - flash it." % name))
    return out


def card_path_state(field, facts, rows=(), loaded_card="", menu=(),
                    rebuild=(), platform="stern"):
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
        return ("empty", backend_for(platform).empty_path_text, "gray", False)
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
        why = (facts or {}).get("unreadable")
        if why:
            # It has been read, and it refused.  The sentence says what was
            # found rather than going on offering the load that failed - but
            # it does not forbid another: a half-built card at this path
            # becomes a real one the moment it is built.
            state = ("unreadable",
                     "%s is on disk but is not a multi-boot card: %s"
                     % (name, why), "fg", True)
        else:
            state = ("file",
                     "%s is on disk — %s to read it into the form; %s would "
                     "write over it." % (name, READ_VERB, WRITE_BUTTON),
                     "fg", True)
    elif kind == "missing":
        if (facts or {}).get("parent"):
            sentence = "%s will write a new card at %s." % (WRITE_BUTTON,
                                                             name)
        else:
            folder = os.path.basename(
                os.path.dirname(os.path.abspath(field))) or "the folder"
            sentence = ("%s will write a new card at %s, creating %s."
                        % (WRITE_BUTTON, name, folder))
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
            if f.name == "members":
                # a list of member ROWS, not a string: everything else here is
                # a text field, and str() on a list is how "[]" became a group
                kw[f.name] = [MemberRow(path=str(m.get("path") or ""),
                                        title=str(m.get("title") or ""),
                                        version=str(m.get("version") or ""))
                              for m in (val or ()) if isinstance(m, dict)]
                continue
            kw[f.name] = bool(val) if isinstance(f.default, bool) \
                else str("" if val is None else val)
        kw.setdefault("path", "")
        try:
            row = ImageRow(**kw)
        except TypeError:                               # pragma: no cover
            continue
        if row.path:
            row.path = resolve(row.path)
        for m in row.members:
            if m.path:
                m.path = resolve(m.path)
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
    three numbers as ints.  Anything missing or unreadable keeps the tab's
    own default rather than raising (an older state's ``bypass`` key is
    ignored: the bypass is always on)."""
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
            "machine_volume": bool(menu.get("machine_volume", True)),
            "compact": bool(menu.get("compact", False)),
            "timeout": max(0, _as_int("timeout", 15)),
            # A STATE WRITTEN BEFORE THE FIELD EXISTED has no key, and the
            # menu it describes said SELECT GAME CODE - so the absent key is
            # that, not "no heading" (PAD-135).
            "heading": str(menu.get("heading", DEF_HEADING))[:HEADING_MAX],
            # ...and a state from before the tick describes a menu the
            # selector drew at one size, which is what the tick means
            "same_text_size": bool(menu.get("same_text_size", True)),
            # ...and a state from before these two describes the menu the
            # selector drew with both of its own answers (PAD-190)
            "show_counter": bool(menu.get("show_counter", True)),
            "countdown_word": str(menu.get("countdown_word",
                                           DEF_COUNTDOWN_WORD))[:COUNTDOWN_WORD_MAX],
            # ...and a state from before the instructions field describes a
            # menu drawing the selector's own line: the tick on, the box empty
            "show_footer": bool(menu.get("show_footer", True)),
            "footer": str(menu.get("footer", ""))[:FOOTER_MAX],
            "default": max(0, _as_int("default", 0)),
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


def parse_plan(text, platform="stern"):
    """What ``mkmulticard.py plan`` said: ``{"bytes": N or None, "fits":
    {"16G": (True, spare), ...}, "versions": {index: "1.59.0", ...},
    "sizes": [(index, device, bytes, source), ...], "overhead": N}``.

    THE SIZES ARE WHAT THE STRIP DRAWS.  The tool prints what each game costs
    on the finished card - a whole partition in the one-extra layout, the used
    bytes of its tree inside the shared p7 otherwise - because "which one do I
    drop" is the question a card that does not fit asks, and only the tool can
    answer it: the .raw files on disk are all the same size.

    THE VERSIONS ARE WHY THE CODE COLUMN CAN BE FILLED AT ALL for images you
    ADD.  A card you LOAD reports each image's game code version through
    inspect, but a card being assembled has never been read - and the tool
    reads the version off every .raw anyway, on the way to refusing a
    mismatched build, and prints it in a table.  Listening to that costs
    nothing and is the same number by the same route (David: "the code
    column is not being populated for me when i load in images")."""
    info = {"bytes": None, "fits": {}, "versions": {}, "sizes": [],
            "overhead": None, "free": None, "shared": None}
    be = backend_for(platform)
    fits_re, total_re = be.fits_re, be.total_re
    for line in (text or "").splitlines():
        m = _SIZE_OVER_RE.match(line.strip())
        if m:
            info["overhead"] = int(m.group(1))
            continue
        m = _SIZE_FREE_RE.match(line.strip())
        if m:
            info["free"] = int(m.group(1))
            continue
        m = _SIZE_SHARED_RE.match(line.strip())
        if m:
            info["shared"] = int(m.group(1))
            continue
        m = _SIZE_ROW_RE.match(line.strip())
        if m:
            size = m.group(3)
            info["sizes"].append((int(m.group(1)), m.group(2),
                                  None if size == "?" else int(size),
                                  m.group(4).strip()))
            continue
        m = fits_re.search(line)
        if m:
            info["fits"][m.group(1)] = (m.group(2) == "YES", int(m.group(3)))
        m = total_re.match(line.strip())
        if m:
            info["bytes"] = int(m.group(1))
        m = _VERSION_ROW_RE.match(line)
        if m and not line.lstrip().startswith("NOTE"):
            version = m.group(2)
            info["versions"][int(m.group(1))] = (
                "" if version == "UNKNOWN" else version)
    return info


# ---------------------------------------------------------------------------
# what the compact list and the Menu settings button say
# ---------------------------------------------------------------------------

#: One row of the plan's own per-image size block.  ``image-size`` and not a
#: bare index because the tool's VERSION table also starts with one, and two
#: parsers reading each other's rows is how a size preview ends up naming a
#: game code.
_SIZE_ROW_RE = re.compile(r"^image-size (\d+) (\S+) (\d+|\?)\s*(.*)$")
_SIZE_OVER_RE = re.compile(r"^image-size overhead (\d+)")
#: ...and the room the games partitions keep for in-place updates (item 93):
#: a WORD where the index goes, so the row above cannot read it as an image.
_SIZE_FREE_RE = re.compile(r"^image-size free (\d+)")
#: ...and what the compact layout stores once (item 95): bytes the images
#: share by content, which are NOT on the card - the saving, in a word row.
_SIZE_SHARED_RE = re.compile(r"^image-size shared (\d+)")

_UPDATE_FILES_RE = re.compile(r"^update-files (\d+) (\S+) (\d+) (\d+) (\S+)")
_UPDATE_SOURCE_RE = re.compile(r"^update-source (\d+) (\S+) (\S+)")
_UPDATE_SIZE_RE = re.compile(r"^update-size (\d+)")
_UPDATE_PEAK_RE = re.compile(r"^update-peak (\d+)")
_UPDATE_GROW_RE = re.compile(r"^update-grow (?:(p\d+) (\d+)|none)")
_UPDATE_FITS_RE = re.compile(r"^update-fits (YES|NO)")
_UPDATE_INJECT_RE = re.compile(r"^update-inject (yes|no)")


def parse_update(text):
    """What ``mkmulticard.py update --dry-run`` said: ``{"bytes": N or None,
    "peak": N, "files": {index: (n changed, bytes, action)}, "fits": bool,
    "inject": bool, "grow": (partition, bytes) or None, "missing": [index]}``.
    ``bytes`` None means the rows were not there (a refusal, an old tool)."""
    info = {"bytes": None, "peak": 0, "files": {}, "fits": True,
            "inject": False, "grow": None, "missing": []}
    for line in (text or "").splitlines():
        s = line.strip()
        m = _UPDATE_FILES_RE.match(s)
        if m:
            info["files"][int(m.group(1))] = (
                int(m.group(3)), int(m.group(4)), m.group(5))
            continue
        m = _UPDATE_SOURCE_RE.match(s)
        if m:
            if m.group(3) == "missing":
                info["missing"].append(int(m.group(1)))
            continue
        m = _UPDATE_SIZE_RE.match(s)
        if m:
            info["bytes"] = int(m.group(1))
            continue
        m = _UPDATE_PEAK_RE.match(s)
        if m:
            info["peak"] = int(m.group(1))
            continue
        m = _UPDATE_GROW_RE.match(s)
        if m:
            info["grow"] = (m.group(1), int(m.group(2))) if m.group(1) else None
            continue
        m = _UPDATE_FITS_RE.match(s)
        if m:
            info["fits"] = m.group(1) == "YES"
            continue
        m = _UPDATE_INJECT_RE.match(s)
        if m:
            info["inject"] = m.group(1) == "yes"
    return info


def trees_from_inspect(info):
    """The record a loaded card carries (item 93), as the tab keeps it:
    ``{"free", "dirty", "synced", "changed": {index: True/False/None}}``,
    or None for a card that has no record (built before item 93 - an
    update hashes it once) or none the tool could read."""
    tr = (info or {}).get("trees")
    if not isinstance(tr, dict) or not tr.get("recorded"):
        return None
    return {"free": tr.get("free_bytes"), "dirty": list(tr.get("dirty") or []),
            "synced": list(tr.get("synced") or []),
            "changed": {int(im.get("index", -1)): im.get("source_changed")
                        for im in (tr.get("images") or []) if isinstance(im, dict)}}


#: A line of the build's own work meter.  It is the one line the tab reads for
#: its progress bar and the one line it keeps OUT of the Log: one a second for
#: an hour is not a record of anything.
_PROGRESS_RE = re.compile(r"^\[card\] progress (\d+)/(\d+) ([\d.]+)%\s*(.*)$")


def parse_progress(line):
    """A tool progress line -> ``(done, total, fraction, what)``, or None for
    every other line."""
    m = _PROGRESS_RE.match((line or "").strip())
    if not m:
        return None
    done, total = int(m.group(1)), int(m.group(2))
    frac = min(1.0, max(0.0, done / float(total))) if total else 0.0
    return done, total, frac, m.group(4).strip()


def eta_text(seconds):
    """``'about 12 minutes left'`` - or ``''`` when there is no honest answer.

    Coarse ON PURPOSE.  A build's rate is a copy rate over a card reader and a
    Windows drive; '11 m 43 s left' claims a precision it does not have, and a
    number that jitters by minutes reads as a broken clock.  Under a minute it
    says so instead of counting down to zero."""
    if seconds is None or seconds != seconds or seconds < 0:    # NaN included
        return ""
    if seconds > 24 * 3600:
        return ""                   # not an estimate by then, a bad sum
    if seconds < 60:
        return "less than a minute left"
    mins = int(round(seconds / 60.0))
    if mins < 60:
        return "about %d minute%s left" % (mins, "" if mins == 1 else "s")
    hours, mins = divmod(mins, 60)
    if not mins:
        return "about %d hour%s left" % (hours, "" if hours == 1 else "s")
    return "about %dh %dm left" % (hours, mins)


def _gbytes(n):
    """Bytes the way an SD card is sold - decimal GB, two places."""
    return "%.2f GB" % ((n or 0) / 1e9)


#: The Stern card sizes in the order the size strip offers them - the same
#: three the tool measures the image against.  The label is what a person
#: BUYS; the bytes behind it are Stern's own image size for that card.
CARD_SIZES = (("8G", "8 GB"), ("16G", "16 GB"), ("32G", "32 GB"))


def card_without_room(info, total, free, need, platform="stern"):
    """``(label, bytes)`` of the card this build would need IF the games
    partitions kept no room for updates - but only when that is a smaller
    card than the one it does need.  ``None`` otherwise.

    THE QUESTION THIS ANSWERS is C FB's (PAD-137): "I was wondering why it
    suggested a 32gb card for my images when it looks like it does not break
    16gb".  The games were 10.83 GB and the card was 32 GB, and the strip
    named both numbers without ever joining them up - the 6.21 GB of free
    room between them was the whole answer and read as a footnote.

    The card sizes come out of the plan's own ``fits`` rows (each is
    ``total + spare``), never a table here: two places holding Stern's image
    sizes is one place for them to disagree."""
    fits = info.get("fits") or {}
    for key, label in backend_for(platform).sizes:
        if label == need:
            # the games alone want this card too, so the room is not what
            # pushed it up and there is nothing to explain
            return None
        spare = fits.get(key)
        if spare is None:
            continue
        cap = total + spare[1]
        if total - free <= cap:
            return label, cap
    return None


def card_size_view(info, platform="stern"):
    """WHAT THE SIZE STRIP SHOWS, from the plan's numbers and nothing else.

    ``{"known", "need", "over", "total", "scale", "cap", "spare", "bands",
    "head", "detail", "why"}`` - ``bands`` being ``[(label, bytes, kind), ...]``
    with *kind* ``"image"`` or ``"overhead"``, ``cap`` the biggest card there
    is (where the overflow starts), and ``why`` the paragraph behind the
    sentence when the card you must buy is bigger than the games in it.

    ``scale`` is the card the bar is drawn against - the smallest one that
    fits - so the fill means "this much of the card you need is used" rather
    than a fraction of some arbitrary maximum.  When nothing fits, the scale
    is the image itself and the part past the biggest card is overflow.

    A pure function of the tool's report: the drawing is the part that cannot
    be tested, so it is kept down to placing what this decided."""
    info = info or {}
    total = info.get("bytes")
    fits = info.get("fits") or {}
    view = {"known": bool(total), "need": None, "over": False,
            "total": total or 0, "scale": total or 1, "spare": None,
            "cap": None, "bands": [], "head": "", "detail": "", "saved": 0,
            "why": ""}
    if not total:
        return view
    be = backend_for(platform)
    sizes = be.sizes
    biggest = fits.get(sizes[-1][0])
    if biggest is not None:
        view["cap"] = total + biggest[1]
    for key, label in sizes:
        ok, spare = fits.get(key, (False, 0))
        if ok:
            view["need"], view["spare"] = label, spare
            view["scale"] = total + spare
            break
    else:
        view["over"] = True
        view["scale"] = total
    games = 0
    for idx, dev, size, src in info.get("sizes") or ():
        if size:
            games += size
            view["bands"].append(
                ("Image %d - %s" % (idx, src or dev), size, "image"))
    free = info.get("free")
    if free:
        # the room the games partitions keep for in-place updates (item 93):
        # a hollow band, because it is space nothing has been put in yet
        view["bands"].append(("Free for updates", free, "free"))
    over = info.get("overhead")
    if over:
        view["bands"].append((be.overhead_label, over, "overhead"))
    if view["over"]:
        key, biggest = sizes[-1]
        short = -(fits.get(key) or (False, 0))[1]
        view["head"] = "too big"
        view["detail"] = ("%s of code - %s more than a %s %s. Drop an "
                          "image." % (_gbytes(total), _gbytes(short), biggest,
                                      be.medium_holds))
    elif free is not None and info.get("shared"):
        # the compact layout (items 95/100): the images' rows are what each
        # brings on its own; what they share is stored once - the saving,
        # drawn as a hatched part of the free room (clamped to it)
        view["head"] = view["need"]
        view["saved"] = int(info["shared"])
        view["detail"] = "%s of games, %s saved, %s free." % (
            _gbytes(games), _gbytes(info["shared"]), _gbytes(free))
    elif free is not None:
        view["head"] = view["need"]
        view["detail"] = "%s of games, %s free for updates." % (
            _gbytes(games), _gbytes(free))
        # WHY THE CARD IS BIGGER THAN THE GAMES (PAD-137).  Only when the
        # room is what bought the bigger card: on every other list the two
        # numbers above are the whole story and a second clause about a card
        # nobody has to buy would be noise.
        smaller = card_without_room(info, total, free, view["need"], platform)
        if smaller:
            label, cap = smaller
            view["detail"] = (
                "%s of games + %s free for updates = %s, so %s and not %s."
                % (_gbytes(games), _gbytes(free), _gbytes(total),
                   view["need"], label))
            view["why"] = (
                "A %s card holds %s and this build is %s. The games are only "
                "%s: the rest is the room the games partitions keep free so "
                "an image can be updated in place, and the first image's card "
                "is copied whole - empty space and all. Tick Compact build to "
                "size the card to what is actually in the images."
                % (label, _gbytes(cap), _gbytes(total), _gbytes(games)))
    else:
        view["head"] = view["need"]
        view["detail"] = "%s of code, %s spare on a %s card." % (
            _gbytes(total), _gbytes(view["spare"] or 0), view["need"])
    return view


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
    # A PATH MAY BE QUOTED (it is typed into a box, and a path with a space
    # in it is pasted out of Explorer with its quotes on), and a basename
    # taken through the closing quote is `ComeTogether.wav"`.
    v = (value or "").strip().strip('"').strip()
    # ntpath, NOT os.path: the field is a RECORDED path, and a card built on
    # Windows names its WAVs with backslashes that os.path on a Mac or Linux
    # desktop would hand back whole.  ntpath splits on both separators.
    return v if v.lower() in _WORDS or not v else ntpath.basename(v)


def _cell_image(row):
    """The .raw the image was copied from, said plainly when this machine
    does not have it (a loaded card names sources that may live on another
    disk) and when the card names none at all."""
    if is_group(row):
        # A RANDOM CARD HAS NO SOURCE OF ITS OWN and never will: its games are
        # its members.  Saying "(no source recorded)" about it read as a fault
        # (David, 2026-09-11), when the answer is simply the list of games.
        names = [os.path.basename(q) or "?" for q in row_paths(row)]
        missing = sum(1 for q in row_paths(row) if not q or not os.path.isfile(q))
        shown = ", ".join(names[:3]) + (", …" if len(names) > 3 else "")
        return "rolls between %d game%s: %s%s" % (
            len(names), "" if len(names) == 1 else "s", shown,
            "   [%d not on this machine]" % missing if missing else "")
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
    """`` @20s`` when the clip starts into its source, else ''."""
    start = _clip_start(row)
    return " @%ss" % start if start else ""


def cell_anim(row):
    """The row's animation in full: the word or the clip's name, and where
    the clip starts when it is not the source's start (``auto @20s``)."""
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


def set_media(row, kind, path="", start=""):
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
    row.anim_start = ""
    path = (path or "").strip()
    if kind == "logo":
        row.art, row.anim = "auto", "none"
    elif kind == "none":
        row.art, row.anim = "none", "none"
    elif kind == "picture":
        row.art, row.anim = path, "none"
    else:
        row.anim_start = (start or "").strip()
        if kind == "attract":
            row.art, row.anim = "auto", "auto"
        else:
            row.art = row.anim = path
            row.art_time = row.anim_start
    return row


#: WHAT A RANDOM CARD SHOWS, which is not what an image shows (David,
#: 2026-09-10, looking at the Edit dialog on a group row: "the options for a
#: Random group need to be bespoke to a random group. we should have options
#: like 'stack of logos', 'big ?', etc. come up with some sweet looking ideas
#: for it").  "The game's own logo" has no game to refer to on a card that
#: stands for forty of them, so every one of these is drawn from the MEMBERS'
#: own logos - the card shows the very builds it can boot.
#:
#: ``(kind, label, art style, animation style)``, and the kind IS the style, so
#: what the row stores is what selectmedia is asked for.  The two animated ones
#: carry a still as well, because a card is drawn standing still whenever it is
#: not the highlighted one: `cycling` rests on the pile it deals from, and
#: `reel` rests on the shuffle glyph, which is what a reel that has not been
#: spun yet looks like.
GROUP_MEDIA_KINDS = (
    ("cycling", "Each game's logo in turn", "stack", "cycling"),
    ("reel", "A slot reel, spinning to one of them", "shuffle", "reel"),
    ("fan", "The logos fanned out, like a hand of cards", "fan", "none"),
    ("stack", "The logos in a pile", "stack", "none"),
    ("mosaic", "Every game at once, as a grid", "mosaic", "none"),
    ("question", "A big '?' over the games", "question", "none"),
    ("shuffle", "The shuffle symbol", "shuffle", "none"),
    ("picture", "A picture file", "", "none"),
    ("none", "Nothing - text only", "none", "none"),
)
#: The one a NEW random card starts on.  It moves, which is what makes a card
#: the eye goes to, and it names every game the roll can land on - which is the
#: one question a random card leaves the player with.
GROUP_MEDIA_DEFAULT = "cycling"
GROUP_MEDIA_NAMES = tuple(k for k, _l, _a, _n in GROUP_MEDIA_KINDS)


def _group_kind(kind):
    for k, label, art, anim in GROUP_MEDIA_KINDS:
        if k == kind:
            return k, label, art, anim
    return None


def group_media_kind(row):
    """Which of :data:`GROUP_MEDIA_KINDS` a RANDOM card's art + animation are.

    'card' for a picture a load read off the card, exactly as :func:`media_kind`
    means it.  A row from before this dialog existed carries the plain default
    ``auto``, which meant "its first member's logo"; it reads as the default
    style now rather than as a file called auto."""
    if row.art_on_card or row.anim_on_card:
        return "card"
    art = (row.art or "").strip().strip('"')
    anim = (row.anim or "").strip().strip('"').lower()
    if anim not in ("", "none"):
        for k, _l, _a, n in GROUP_MEDIA_KINDS:
            if n != "none" and anim == n:
                return k
        return GROUP_MEDIA_DEFAULT          # an animation this build cannot draw
    a = art.lower()
    if a in ("", "auto"):
        return GROUP_MEDIA_DEFAULT
    if a == "none":
        return "none"
    for k, _l, style, n in GROUP_MEDIA_KINDS:
        if n == "none" and style and a == style:
            return k
    return "picture"


def set_group_media(row, kind, path=""):
    """The dialog's one choice -> a RANDOM card's row.  'card' writes nothing,
    the way :func:`set_media` leaves a card's own files alone."""
    if kind == "card":
        return row
    found = _group_kind(kind)
    if found is None:
        raise ValueError("not a random card's picture: %r" % (kind,))
    _k, _label, art, anim = found
    row.art_on_card = row.anim_on_card = False
    row.art_video = row.art_time = row.anim_start = ""
    row.art = (path or "").strip().strip('"') if kind == "picture" else art
    row.anim = anim
    return row


def group_media_file(row):
    """The picture file a random card was pointed at; '' for every style."""
    return (row.art or "").strip().strip('"') \
        if group_media_kind(row) == "picture" else ""


def group_art_spec(row):
    """The ``--group-art G=`` value: a style name, a picture file, or none."""
    kind = group_media_kind(row)
    if kind == "picture":
        return wsl(group_media_file(row))
    found = _group_kind(kind)
    return (found[2] if found else "") or "none"


def group_anim_spec(row):
    """The ``--group-anim G=`` value: a style name, or none."""
    found = _group_kind(group_media_kind(row))
    return (found[3] if found else "none") or "none"


def media_fields_to_check(row):
    """The ``(what, value)`` media fields of a row that name a FILE on this
    machine, for the two validators.

    A RANDOM CARD'S PICTURE IS A STYLE, NOT A PATH.  Walking a group row's art
    the way an image's is walked reports "art file not found: stack" about a
    card that is perfectly well formed - the same class of bug as every other
    one this feature has had, which is a place that treats a card as an image.
    A file a LOAD read off the card is still named here, because both
    validators have something to say about one."""
    if not is_group(row):
        return (("art", row.art), ("animation", row.anim), ("music", row.music))
    pairs = []
    if row.art_on_card or group_media_kind(row) == "picture":
        pairs.append(("art", row.art))
    if row.anim_on_card:
        pairs.append(("animation", row.anim))
    pairs.append(("music", row.music))
    return tuple(pairs)


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
    own words - ``logo``, ``attract video @20s``, ``intro.mp4 @3s``,
    ``logo.png``, ``none`` - and, when the still is not the one its
    animation implies (a pair an older form made, or a card carries), both
    halves: ``attract.mov @21s + attract video @20s``.

    A RANDOM CARD says which of its own styles it is drawn in - it has no game
    whose logo could be "the logo"."""
    if is_group(row):
        kind = group_media_kind(row)
        if kind == "card":
            return (row.art or "").strip() + " (on the card)"
        if kind == "picture":
            return os.path.basename(group_media_file(row))
        return kind
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
    if is_group(row):
        # A GROUP ROW SAYS SO IN THE LIST.  Nothing else in this table can
        # tell one from a plain image, and "why does this card have no file"
        # is the first thing a person would otherwise ask.
        missing = [q for q in row_paths(row) if not q or not os.path.isfile(q)]
        cell = "%s  (random, %d sets)" % (title or "image %d" % index,
                                          len(row.members))
        if missing:
            cell += "  [%d not on this machine]" % len(missing)
        return cell
    path = (row.path or "").strip().strip('"')
    if not title:
        title = suggest_title(path)[0] if path else "image %d" % index
    if not path:
        return "%s  [no source recorded]" % title
    if not os.path.isfile(path):
        return "%s  [not on this machine]" % title
    return title


def list_code(row):
    """The list's Code cell for a row: the game code version, or - for a group
    whose members do not agree - `mixed`.  The members of a jukebox card are
    meant to be one title with different songs, so a `mixed` here is worth
    seeing: swapping between two code versions reflashes the node boards."""
    if not is_group(row):
        return (row.version or "").strip()
    known = sorted(set((m.version or "").strip() for m in row.members
                       if (m.version or "").strip()))
    if not known:
        return ""
    # ONLY TWO DIFFERENT KNOWN VERSIONS ARE MIXED.  A version is read off the
    # .raw and a member that has not been read yet is blank, so treating a
    # blank as a disagreement would alarm somebody over nothing.
    return "mixed" if len(known) > 1 else known[0]


def has_own_confirm(row):
    """Whether this image carries a confirm sound OF ITS OWN - the one the
    machine plays instead of the menu's.  The same test the Confirm column
    makes (see ``_confirm_cell``): :func:`inherits_confirm` decides, so all
    three spellings of "the menu's" count as not having one."""
    own = (getattr(row, "confirm", "") or "").strip()
    return bool(getattr(row, "confirm_on_card", False)) or not \
        inherits_confirm(own)


def plain_title(row, index=0):
    """The row's name in a sentence: its menu title, the name the tab would
    fall back to, or ``image N``.  :func:`list_title`'s answer without the
    bracketed complaint about the .raw, which reads as part of the name in
    running text."""
    title = (row.title or "").strip()
    if title:
        return title
    path = (row.path or "").strip().strip('"')
    return suggest_title(path)[0] if path else "image %d" % index


def menu_confirm_now(value):
    """What an image's ``menu`` confirm sound actually is: the menu-wide
    setting, said the way the Confirm column says it.

    C FB, PAD-137: "the confirm sound is both in the image properties and
    the overall properties which seems to not be in synch".  They are the
    same setting - one falls back to the other - but the two panels never
    said so in the same words: the list column already showed the inherited
    value as ``(auto)`` while the dialog behind it showed ``menu``."""
    return _cell((value or "").strip()) or "none"


def own_confirm_note(rows):
    """'' or the sentence Menu settings' own note carries about its Confirm
    sound: which images have one of their own and so never play it.

    The other half of :func:`menu_confirm_now` - each panel says what the
    other one is doing with the setting they share."""
    rows = list(rows or ())
    names = [plain_title(r, i) for i, r in enumerate(rows)
             if has_own_confirm(r)]
    if not names:
        return ""
    shown = ", ".join(names[:3]) + (
        " and %d more" % (len(names) - 3) if len(names) > 3 else "")
    if 1 < len(names) <= 3:
        shown = ", ".join(names[:-1]) + " and " + names[-1]
    one = len(names) == 1
    return ("%d of the %d images %s a confirm sound of %s own - %s - and %s "
            "use this one." % (len(names), len(rows),
                               "has" if one else "have",
                               "its" if one else "their", shown,
                               "does not" if one else "do not"))


def image_confirm_note(value, menu_value):
    """The line under Edit image…'s Confirm sound box: the sound that image
    will actually play, NAMED - the same name the list's Confirm column
    carries for the same row.

    BEN, PAD-184: "the properties of an image on a multiboot game does not
    align with the information on the general table of images with the
    confirm sound.  The properties page does not show the correct sound but
    will play the correct sound with the play button."  The two panels were
    never out of step - they answer two different questions.  The box holds
    the SETTING ('menu', or a whole path, or a name a load read off the
    card); the column holds the ANSWER (the sound's name, bracketed when it
    is the menu's).  A box that says ``menu`` beside a column that says
    ``(ComeTogether.wav)`` reads as two settings that disagree, and ▶ -
    which resolves the setting exactly as the card does - then plays a third
    thing neither of them named.  So the box now carries the answer too, on
    its own line, rebuilt on every keystroke.

    *value* is the image's own setting and *menu_value* the menu-wide one.
    """
    own = (value or "").strip()
    if not inherits_confirm(own):
        return "Plays %s, this image's own." % _cell(own)
    menu = menu_confirm_now(menu_value)
    if menu == "none":
        return ("Plays nothing: neither this image nor the menu has a "
                "confirm sound.")
    return "Plays %s, the menu's own." % menu


def countdown_example(word, title, timeout):
    """The countdown line the menu will draw, as the ``Countdown says`` field's
    example: ``starting The Beatles in 15 s``.

    An empty *word* is the line with no word in front of the game's name, and a
    countdown of 0 is a menu that waits for START - the word is then never seen
    at all, and saying so is more use beside the box than an example of a line
    that will not be drawn (PAD-190)."""
    word = (word or "").strip()
    title = (title or "").strip() or "the game"
    try:
        secs = int(timeout or 0)
    except (TypeError, ValueError):
        secs = 0
    if secs <= 0:
        return "no countdown - the menu waits for START"
    tail = "%s in %d s" % (title, secs)
    return "%s %s" % (word, tail) if word else tail


def footer_example(show, text):
    """What the instructions line under the cards will say, as the field's own
    example: the words typed in it, or a plain sentence for the two answers an
    empty box can be (PAD-190 round 2).

    The selector's own wording cannot be quoted here: it names the buttons the
    MACHINE has, and only the machine knows whether a lockdown-bar Action
    button is wired - so an empty box says which line will be drawn rather than
    pretending to know its words."""
    text = (text or "").strip()
    if not show:
        return "no line under the cards naming the buttons"
    if not text:
        return "the menu's own: the flipper and START buttons this machine has"
    return text


def _one_line_text(text, width):
    """*text* at most *width* characters, ended with an ellipsis when it had
    to be cut - what a summary line quotes a free-text field as."""
    s = " ".join((text or "").split())
    return s if len(s) <= width else s[:max(1, width - 1)] + "…"


def menu_summary(form):
    """The one line beside the 'Menu settings…' button: everything behind it,
    in the order the dialog asks for it."""
    def sound(v):
        v = (v or "").strip() or "none"
        return v if v.lower() in _WORDS else os.path.basename(v)
    head = (form.heading or "").strip()
    word = (form.countdown_word or "").strip()
    foot = (form.footer or "").strip()
    # THE TEXT SIZE ONLY WHEN IT IS NOT THE USUAL ONE: this line is already
    # eight clauses long, and "every card the same" is what every menu does
    # unless somebody turned it off (PAD-183).
    return ("sounds %s / %s  ·  volume %d%s  ·  %s  ·  default %d  ·  "
            "theme %s  ·  %s%s" % (
                sound(form.sound_move), sound(form.sound_confirm),
                int(form.volume),
                " (the machine's own on the card)" if form.machine_volume
                else "",
                "wait for START" if int(form.timeout) == 0
                else "%d s countdown" % int(form.timeout),
                int(form.default),
                (form.theme or "").strip().lower() or DEFAULT_THEME,
                "no heading" if not head else '"%s"' % _one_line_text(head, 28),
                ("" if form.same_text_size
                 else "  ·  each card its own text size")
                # THE OTHER TWO ONLY WHEN THEY ARE NOT THE USUAL ONES, on the
                # text size's rule: this line is long enough already, and both
                # of these are what every menu says unless somebody changed
                # them (PAD-190)
                + ("" if form.show_counter else "  ·  no card counter")
                + ("" if word == DEF_COUNTDOWN_WORD else
                   "  ·  countdown says %s" % (
                       "just the game and the seconds" if not word
                       else '"%s"' % _one_line_text(word, 16)))
                + ("" if form.show_footer and not foot else
                   "  ·  no instructions" if not form.show_footer
                   else "  ·  instructions \u201c%s\u201d"
                        % _one_line_text(foot, 20))))


# ---------------------------------------------------------------------------
# the sounds a menu already uses, and the dialogs' words
# ---------------------------------------------------------------------------


def used_sounds(rows, *menu):
    """Every sound FILE this menu already uses, for the dropdowns to offer.

    C FB, 2026-09-12: "the default audio drop downs only list the 3 built in
    audio suggestions. If I add one (which I want to eventually clone to
    everything), it would be nice to have it as an option in the drop down
    list".  Browsing the same WAV in once per image is the whole complaint,
    so a file chosen ANYWHERE - the menu's two sounds (*menu*) or any image's
    music or confirm - is then one click away in all four boxes.  ONE list
    rather than one per field: a WAV is a WAV, and a rule that offered the
    move sound's file to the move box only would have to be explained.

    ONLY FILES THAT ARE ON THIS MACHINE.  A card built on somebody else's PC
    loads with their paths in it (the sources are recorded, not the files),
    and offering one of those is offering a build that stops on 'file not
    found'.  A value the load could not explain at all (``*_on_card``: a file
    name on the card, which no source string made) is not a path here either.
    """
    out, seen = [], set()
    vals = list(menu)
    for row in rows:
        vals += [v for v, on_card in ((row.music, row.music_on_card),
                                      (row.confirm, row.confirm_on_card))
                 if not on_card]
    for v in vals:
        v = (v or "").strip().strip('"')
        if not is_file_choice(v) or _AUTO_IDX_RE.match(v):
            continue
        key = os.path.normcase(os.path.abspath(v))
        if key in seen or not os.path.isfile(v):
            continue
        seen.add(key)
        out.append(v)
    return sorted(out, key=lambda p: (os.path.basename(p).lower(), p.lower()))


def sound_choices(paths):
    """``[(label, path)]``: how :func:`used_sounds`'s files are OFFERED.

    The label is the file's NAME, not its path.  A ttk dropdown is exactly
    as wide as the box above it (26 characters here), and every path on one
    machine starts with the same few folders, so a list of paths is a list
    of ``C:\\Users\\david\\Doc`` - the same twelve characters, four times.
    Two files that share a name get their folder as well, and a pair that
    shares that too keeps its whole path: a list you pick from must not
    offer the same words twice.
    """
    names = {}
    for p in paths:
        names.setdefault(os.path.basename(p).lower(), []).append(p)
    out, taken = [], set()
    for p in paths:
        label = os.path.basename(p)
        if len(names[label.lower()]) > 1:
            folder = os.path.basename(os.path.dirname(p)) or os.path.dirname(p)
            label = "%s  (%s)" % (label, folder)
        if label in taken:
            label = p
        taken.add(label)
        out.append((label, p))
    return out


#: The Play button's face.  THE WORD AND THE TRIANGLE, not the triangle
#: alone: on its own it came out of the first proof shot as a six-pixel
#: arrowhead beside a button that says "Browse…" in words, which is not a
#: control anybody presses.  PLAY_NAME is how the notes beside it refer to it.
PLAY_NAME = "Play"
PLAY_LABEL = "\u25b6 " + PLAY_NAME
PLAY_TIP = ("Hear this sound now, through the preview's own volume and Mute.\n"
            "A word (auto, synth, menu) plays the file the menu has ready for "
            "it; pick or type a WAV and it plays that.")


#: What a video shows, STATED rather than offered as controls (David:
#: "remove the 'start', 'Length' and 'FPS' controls... just state [the
#: limits]").  It loops the first 5 s AT THE VIDEO'S OWN FRAME RATE (David:
#: "10fps sucks... make it the original fps", then "run at original fps
#: (minimum 30fps would be ideal). we can limit them to 5 second clips") -
#: 30 fps at most, which a 60 fps clip halves to cleanly.  Any common video
#: works - it is re-encoded - so there is no codec to get right either.
CLIP_NOTE = ("Shown as a loop of the first 5 seconds, at the video's own "
             "frame rate (up to 30 fps). Any common video works - it is "
             "re-encoded.")

#: What each choice does, said under the box that makes it.  ONE LIVE LINE,
#: not a paragraph per option (BEN, PAD-187: the dialog was tall enough to
#: push its own OK button off the bottom of the screen).  Each of these used
#: to be either a note standing under the list for ever or a sentence nobody
#: could see until they had picked the option it described.
MEDIA_NOTES = {
    "logo": "The game's own logo, taken off its card when the menu is built.",
    "picture": ("Your own picture, fitted to the card's panel: never "
                "stretched, never cropped."),
    "attract": ("The game's own attract video plays while the image is "
                "highlighted, and its own logo is the still. " + CLIP_NOTE),
    "video": ("A video is the still too: the frame it starts on shows while "
              "the image is not highlighted. " + CLIP_NOTE),
    "none": ("Text only: the card shows its title and subtitle on the menu's "
             "own colours."),
    "card": ("Kept exactly as the card has it: the files the load read, "
             "never re-made from what made them."),
}

#: ...and the one every RANDOM card's style shares, because they are all the
#: same idea: the games behind this one card, drawn seven ways.
GROUP_MEDIA_NOTE = ("Every one of these is drawn from the logos of the games "
                    "this card rolls between, so the card shows what it can "
                    "boot. The moving ones play while the card is "
                    "highlighted.")


def media_note(kind, group=False):
    """The grey line under the Picture box for *kind*: what the option that
    is chosen right now does."""
    if group:
        return MEDIA_NOTES.get(kind, "") if kind in ("picture", "none", "card") \
            else GROUP_MEDIA_NOTE
    return MEDIA_NOTES.get(kind, "")


def manifest_art_source(manifest, name):
    """What the prepared ``art<N>.png`` / ``gart<G>.png`` called *name* was
    made from, as the spec the tools were given ('auto', a style, a path),
    or '' when this media set has no such file.

    BY FILE NAME AND NOT BY INDEX: the art files are numbered by IMAGE and
    a random card's by GROUP, while the rows on the tab are neither (see
    :func:`card_media_names`), so the name is the only thing the two sides
    are sure to agree on."""
    for key in ("images", "groups"):
        for row in manifest.get(key) or []:
            if isinstance(row, dict) and (row.get("art") or "") == name:
                return str(row.get("art_source") or "")
    return ""


def still_for_row(form, index, media_dir, manifest=None):
    """Where the picture of row *index* can be drawn from AT THIS MOMENT,
    as ``(what, value)``:

      ``("file", path)``      a picture the owner chose - the file itself
      ``("video", (path, seconds))``  the frame that video starts on
      ``("rendered", path)``  the art the tools made, and only when they
                              made it from exactly the choice the row
                              carries now
      ``("none", "")``        nothing that can be drawn yet

    THE RENDERED FILE IS ONLY OFFERED WHEN IT IS STILL THE ANSWER.  A media
    directory keeps the last render, so the moment somebody picks another
    style the file beside it is a picture of the choice they have just left:
    showing it would be a preview of the wrong thing, which is worse than
    showing nothing.  The manifest records what each file was made from, so
    the two can be compared rather than assumed."""
    rows = list(getattr(form, "images", ()) or ())
    if not 0 <= index < len(rows):
        return ("none", "")
    row = rows[index]
    group = is_group(row)
    kind = group_media_kind(row) if group else media_kind(row)
    path = (group_media_file(row) if group
            else media_file(row)).strip().strip('"')
    if kind == "picture" and path and os.path.isfile(path):
        return ("file", path)
    if kind == "video" and path and os.path.isfile(path):
        return ("video", (path, _clip_start(row) or _num(row.art_time, "0")))
    names = card_media_names(form)
    name = names[index][0] if index < len(names) else ""
    spec = group_art_spec(row) if group else art_spec(row)
    if name and media_dir and spec not in ("", "none") and \
            manifest_art_source(manifest or {}, name) == spec:
        full = os.path.join(media_dir, name)
        if os.path.isfile(full):
            return ("rendered", full)
    return ("none", "")


#: What the preview draws, in the proportions selectmedia.py builds a card
#: with: a 16:9 panel, ``CARD_PAD`` (24 of the panel's 522) around it and
#: ``TEXT_BLOCK`` (118) under it for the title and the subtitle.  The
#: numbers below are that card at a size that sits beside the dialog's
#: fields without deciding how tall the dialog is.
PREVIEW_ART_W = 200
PREVIEW_ART_H = int(round(PREVIEW_ART_W * 9 / 16.0))
PREVIEW_CARD_PAD = int(round(PREVIEW_ART_W * 24 / 522.0))
PREVIEW_TEXT_H = int(round(PREVIEW_ART_W * 118 / 522.0))
PREVIEW_CARD_W = PREVIEW_ART_W + 2 * PREVIEW_CARD_PAD
PREVIEW_CARD_H = PREVIEW_ART_H + PREVIEW_TEXT_H + 2 * PREVIEW_CARD_PAD
#: The menu around the card, so the card is a card and not a rectangle
#: filling a box.
PREVIEW_MARGIN = 8
#: The card's two lines of text.  The machine draws them in its own fonts;
#: this is a picture of the layout, not of the typeface.
PREVIEW_FONT = "TkDefaultFont"

#: What the preview says when it has nothing to draw - each of them a state
#: the tab is really in, never a failure.
PREVIEW_NOTES = {
    "file": "Your picture, fitted to the card.",
    "video": "The frame this clip starts on.",
    "rendered": "As the menu last drew it.",
    "none": "The picture appears here once the tab has drawn its preview.",
    "missing": "That file is not on this machine.",
    "unreadable": "That file cannot be read as a picture.",
    "text": "This card shows its text and nothing else.",
    "noffmpeg": "ffmpeg is not installed, so the frame cannot be shown here.",
}


class _PageDialog:
    """A dialog the PAGE draws.  This module keeps only what the panel and
    the page read off it (its words, its choices); the web panel
    (:mod:`.multiboot_panel`) rebinds each name to the proxy the panel
    actually constructs."""

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            "%s is drawn by the page (webui.multiboot_panel)"
            % type(self).__name__)


class ImageEditorDialog(_PageDialog):
    """'Edit image…': one image's menu text, what it shows, and its sounds.

    WHAT IT SHOWS IS ONE FLAT CHOICE (David, 2026-09-02: "the modality here
    is poor. i have to first select 'art: video' to be able to interact
    with the video frame options. it needs to be a 'radio button' type
    choice... why do we have a separate animation section?"): the game's
    own logo, a picture file, the game's own attract clip, a video file, or
    nothing - one list, one answer, and no box that quietly unlocks a row
    beneath it.  A video is the animation AND the still (the frame it
    starts on shows while the image is not highlighted), so the Animation
    section had nothing left to say and is gone.  A row a load read off a
    card with no source recorded gets one more option, the card's own
    files, which is where it starts (see MEDIA_KINDS).

    THE LIST IS A LIST BOX AND NOT A COLUMN OF RADIO BUTTONS (BEN, PAD-187:
    "The properties window on a multiboot image properties can go off the
    bottom of the screen hiding critical buttons.  Suggestion, change all
    the radio buttons to a drop down list to save space").  It was a column
    of them, one line each plus a file row for two of them, which on a
    random card is NINE options and 250 px of a dialog that had grown to
    887: taller than a 768-high desktop can show, so OK and Cancel were off
    the bottom of it.  The choice is unchanged - still flat, still one
    answer, each option's file row still live only while it is the choice -
    and what was lost with "every option in view" is more than paid back by
    the PREVIEW beside it, which shows what the option chosen actually
    looks like instead of leaving the other eight names to describe
    themselves.  The two ways a random card PICKS stayed radio buttons:
    they are a pair, each needs a sentence, and two lines is not a height
    problem.

    AND IT SHOWS THE CARD IT IS EDITING (BEN, again: "Add in a preview of
    what it will look like.  Currently you have to select it, and go back
    to the main page to see what it looks like").  See :class:`CardPreview`
    for what that picture is and is not."""

    #: The choices, in the order they are offered: ``(kind, label)``.  The
    #: two stills, then the two videos - so the clip fields sit under the
    #: pair they serve.
    KINDS = (("logo", "The game's own logo"),
             ("picture", "A picture file"),
             ("attract", "The game's own attract video"),
             ("video", "A video file"),
             ("none", "Nothing - text only"))

    @classmethod
    def kinds_for(cls, backend):
        """The picture choices this platform can honour: all of :attr:`KINDS`
        on a Stern card; no "attract video" on a JJP image, whose root has
        no attract clip in the clear - a video file plays instead."""
        return tuple((k, label) for k, label in cls.KINDS
                     if k != "attract" or backend.attract_clip)

    #: ...and what a RANDOM CARD offers instead (David, 2026-09-10: "the
    #: options for a Random group need to be bespoke to a random group").  Not
    #: one of the five above survives the move: each of them names "the game",
    #: and this card is several of them.  See GROUP_MEDIA_KINDS.
    GROUP_KINDS = tuple((k, label) for k, label, _a, _n in GROUP_MEDIA_KINDS)

    #: Under the two rules and the tick they share: what the machine keeps
    #: between power-ups, and why a shuffle answers the tick for you.
    ROLL_NOTE = ("The machine remembers across power-ups: a shuffle deals "
                 "every game once before any of them comes round again, and "
                 "picks up where it left off. It never gives you the one it "
                 "just booted either, so the tick is greyed on for it.")

    #: What the two file rows browse for.
    FILETYPES = {"picture": [("Pictures", "*.png *.jpg *.jpeg")],
                 "video": [("Videos", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.gif")]}

    #: How long the dialog waits after the last keystroke before it asks
    #: ffmpeg for a video's first frame.  The same 350 ms the tab's own
    #: preview waits, and for the same reason: a path is typed a letter at
    #: a time and every letter is a file that does not exist yet.
    FRAME_DEBOUNCE_MS = PREVIEW_DEBOUNCE_MS


class MenuSettingsDialog(_PageDialog):
    """'Menu settings…': the sounds, the volume, the LOOK (a theme, or your
    own colours), the countdown, the default image and the selector build
    path - everything that belongs to the MENU rather than to one image.
    The fields are the panel's own variables."""

    # NO 'Game validator' SECTION.  The bypass is ALWAYS ON.  It went
    # through three shapes - always on; a tick after item 98's latched
    # GAME VALIDATION ERROR (a bypassed image never re-graded); on by
    # default once the bypass also ignored the saved grades at boot -
    # and David closed it after the TMNT booted clean on both images:
    # "we tested that this bypass works, we don't need to make it
    # optional. it should always be on now."  Every build and update
    # passes --bypass-validation; nothing here can turn it off.
    #
    # NO 'Advanced' SECTION EITHER (David: "people are likely to mess it
    # up").  The Selector build path is DEFAULT_SELECTOR_DIR, overridable
    # by the PAD_MULTIBOOT_SELECTOR env var (see MultibootPanel.__init__)
    # rather than an entry box nobody but the rig should touch.


class BuildFlashDialog(_PageDialog):
    """'Build / flash card…': the one modal that writes the card, and then -
    if you want - flashes it onto an SD card.  One tick whose words the
    panel decides (:meth:`MultibootPanel._write_plan`): a loaded card that
    only needs its menu rewritten APPLIES (an inject, seconds); anything
    else BUILDS a fresh card.  The flash tick hands off to the app's own
    flash flow."""


# ---------------------------------------------------------------------------
# the panel
# ---------------------------------------------------------------------------

def _int(var, default):
    try:
        return int(str(var.get()).strip())
    except (ValueError, tk.TclError):
        return default


class CardPickDialog(_PageDialog):
    """Item 99: pick the SD card whose boot menu to read.  A small modal - the
    app's drive picker (core.drives, the SD-card preference: the reader, never
    a backup SSD) in a dropdown, Refresh, Read, Cancel.  The enumeration runs
    off-thread (PowerShell on Windows takes a second)."""

    #: The two reads, as the dialog words them.
    MENU_ONLY_TEXT = ("The boot menu only - titles, pictures, sounds and settings "
                      "(a few hundred MB, about a minute)")
    WHOLE_CARD_TEXT = ("The whole card, into a .raw you name - its images too, so they "
                       "can be recovered, replaced or added to (several minutes)")


class MultibootPanel:
    """The Multi-boot tab's logic and its one worker at a time.

    No widgets: :class:`.multiboot_panel.WebMultibootPanel` is this class
    with the page's store where the Tk widgets were, and it supplies the
    painters (``_draw_checks``, ``_draw_size``, ``_pv_placeholder``...) and
    the four dialogs (:class:`ImageEditorDialog` and the rest) this class
    calls."""

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

    #: ...and what the same badge says on the JJP platform (item 118).
    ABOUT_TIP_JJP = ("Builds ONE JJP install stick that carries two complete "
                     "game installs and a menu at power-up: the flippers "
                     "choose, START boots, a countdown boots the remembered "
                     "choice - stock code and a custom build on the same "
                     "machine without reinstalling. The first image is the "
                     "primary: it goes into the machine's root A with the "
                     "menu, the second into root B exactly as it is, and the "
                     "machine falls back to the first. Both installs share "
                     "one set of settings and scores; installing from the "
                     "stick wipes them once, as every JJP install does. GIVE "
                     "BOTH IMAGES THE SAME GAME CODE: the tool refuses "
                     "otherwise. The ISO is made by the rig's tools under "
                     "WSL; nothing here touches the ISOs you pick.")

    #: The JJP platform's words for the list and the size strip (item 118):
    #: two install ISOs and no random card, a USB stick rather than an SD
    #: card, and no compact layout or in-place update to explain.  Swapped
    #: onto the instance by _apply_platform_words; the Stern class attributes
    #: stay what every Stern test pins.
    ADD_ROW_TEXT_JJP = "Add the second ISO…"
    LIST_TIP_JJP = ("Each row carries its own icons: ✎ edits the image, − takes "
                    "it off the stick, ▲ / ▼ swap the two in the menu's order "
                    "(the outlined arrow means that row cannot go further). "
                    "The last row adds the second install ISO. A double-click "
                    "or Enter opens a row, and a right-click - or the menu key "
                    "- offers the same commands. The first image is the "
                    "PRIMARY: it goes into the machine's root A with the menu, "
                    "the second into root B exactly as it is, and the machine "
                    "falls back to the first. Exactly two fit: JJP's A/B root "
                    "slots hold one install each.")
    SIZE_TIP_JJP = (
        "How big a USB stick this install needs - measured by the tool from "
        "the two ISOs' partition pieces, not guessed from the ISO files. The "
        "bar is the stick you would have to buy: each band is one image's "
        "root as it goes onto the stick (the primary re-imaged with the "
        "menu, the second verbatim), and the grey one at the end is what "
        "the stick spends on itself (the installer's live system, the EFI, "
        "boot and perm pieces and the configs). The stick is FAT32, so every "
        "piece stays under 4 GB. It re-measures itself whenever the image "
        "list changes.")

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
                "right-click - or the menu key - offers the same "
                "commands. The last row also adds a RANDOM card: one card "
                "that boots a different game every power-up, either over "
                "images already in this list or over games of its own. The "
                "first image is the PRIMARY: its boot files "
                "are the card's, and the machine falls back to it. Up to %d "
                "images fit one card; from five the menu scrolls three at a "
                "time, with a counter under them." % MAX_CARDS)

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
                  "before a card is written.")
    FLIPPER_TIP = ("The machine's own flipper buttons: they move the "
                   "highlight one card and wrap round at the ends, exactly "
                   "as the flippers on the lockdown bar do - and they play "
                   "the menu's move sound. The left "
                   "and right arrow keys do the same while the picture has "
                   "the keyboard.")

    #: ...and this is where the long form of everything the 30 px control
    #: strip has no room for lives: the strip gets one line, this gets the
    #: paragraph (see :meth:`_one_line`).
    VOLUME_TIP = ("The preview's own loudness on this PC, and Mute to "
                  "silence it - the Emulate tab's knob, for this tab. It "
                  "scales the menu's volume in Menu settings, which is what "
                  "goes on the card and does not move with this.")

    MEDIA_TIP = ("What the preview has rendered so far. Video: every "
                 "card's picture and clip - they play the moment the frame "
                 "is drawn, all at once, as they do on the machine. Audio: "
                 "the highlighted image's music, the move sound on a "
                 "flipper and the confirm on Select, at the volume in Menu "
                 "settings. The two are rendered by separate tool runs, so "
                 "one can be ready while the other is still loading; the "
                 "sounds need the image's Extract-time cache and say so "
                 "here when they cannot be pulled.")

    def __init__(self, parent, log=None, theme_fn=None, badge_fn=None,
                 resize_fn=None, flash_fn=None, emulate_fn=None,
                 phase_fn=None, status_fn=None, platform="stern"):
        self._parent = parent
        #: WHICH PLATFORM the tab builds for (item 118): Stern's SD card or a
        #: JJP install ISO.  The app switches it with the manufacturer
        #: (:meth:`set_platform`); a panel built on its own is a Stern one.
        self._backend = backend_for(platform)
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
        #: The app's own status line, under the stage row.  Where this tab's
        #: messages go now that the row is checks alone - they were a grey
        #: sentence trailing the checks, saying what the checks' tooltips
        #: said.  A panel built on its own (every test) keeps them in
        #: ``message()`` and nowhere else.
        self._status_fn = status_fn or (lambda msg: None)
        self._msg = ""
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
        self._proc_preview = False      # ...and whose run it belongs to
        #: CANCELLING A RUN.  ``_cancelled`` is set by :meth:`cancel_run` and
        #: stays up until the run's own ``on_done`` has seen it, so the
        #: handler can say 'cancelled' instead of 'failed at build (exit 1)' -
        #: a killed tool is a non-zero exit like any other.  ``_cancel_pending``
        #: is the button's state: one press is enough, and the second one has
        #: nothing left to kill.
        self._cancelled = False
        self._cancel_pending = False
        #: The stage row's index the progress lines belong to, and the recent
        #: (clock, bytes) samples the estimate is made from.  A deque, not a
        #: rate carried forward: a build's speed changes by an order of
        #: magnitude between the debugfs extraction and the raw copy, and an
        #: average over the whole run would still be quoting the first stage's
        #: rate an hour later.
        self._phase_index = 0
        self._prog_hist = []
        #: ...and the clock they are stamped with, injectable the way the
        #: preview's ``_play_clock`` is.  A test that reached into the time
        #: module instead would leave a frozen clock behind it for every
        #: other test in the same worker.
        self._prog_clock = time.monotonic
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
        #: The last plan's report, which is what the size strip under the
        #: images table draws (see :meth:`_build_size`).  None means nobody
        #: has measured THIS list, and the strip says so rather than leaving
        #: the last card's number up: a stale size is worse than no size.
        self._plan_info = None
        #: THE SIZE CHECK RUNS ITSELF (see :meth:`_maybe_plan`).
        #: ``_plan_for`` is the image list ``_plan_info`` is about, so the
        #: strip is blanked the moment the list stops being that one;
        #: ``_plan_job`` is its debounce.  ``PAD_MULTIBOOT_PLAN=0`` is its
        #: own off switch, and the panel flag under it is what the tests
        #: and the screenshot rig set: this is the one thing on the tab
        #: that starts a TOOL without being pressed.
        self._plan_for = None
        self._plan_job = None
        #: ...and whether the last one FAILED, so the strip can say that
        #: instead of showing an empty bar with nothing beside it - together
        #: with the tool's OWN refusal sentence, which is the only thing that
        #: tells anybody what to do about it (C FB, PAD-135: "Error when I
        #: tried to recalculate the size using the compact build option", and
        #: all the strip said was that it had failed).
        self._plan_failed = False
        self._plan_why = ""
        #: ...and the size check that is ON THE WORKER right now (its plan
        #: key), the tool's last meter line about it ``(fraction, stage)``,
        #: and the strip's animation while it waits.  The strip shows it is
        #: thinking rather than an empty bar: the compact plan hashes every
        #: image the first time (David: the tick "took around 20-30 seconds
        #: to compute so we should show the loading state in the size bar").
        self._measuring = None
        self._size_progress = None
        self._size_anim_job = None
        self._size_anim_phase = 0
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
        self._roll_repeat_box = None
        self._default_spin = None
        self._theme_combo = None
        self._theme_tip = None
        #: ...and the Countdown says box with the example line beside it
        self._countdown_word_entry = None
        self._countdown_word_lbl = None
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
        #: The RESTORED form, handed to that read so it can be put back on
        #: top of the card it loads (:meth:`_carry_restored_edits`).  None
        #: for every other read: only the restore's own read is one nobody
        #: asked for, and only it can arrive with work already on the tab.
        self._carry_edits = None
        #: ``(path, why)`` for a card at the output path that would not be
        #: read - what keeps the row's sentence from going on offering a
        #: load the tool has already refused.  Dropped the moment the box
        #: names something else, and after any run that writes (a build
        #: makes that very path into a card).
        self._unreadable = None
        #: ``(path, form)`` for a card THIS SESSION built and verified - the
        #: only way to know whether a card nobody has read back still matches
        #: the form (a build does not put the tab into editing mode, so there
        #: is no ``_loaded_form`` to diff against).  See :func:`status_checks`.
        self._built = None
        #: What the run in flight IS - "build" / "apply" / "load" / "" - so
        #: the Built check can show it happening rather than guessing from
        #: ``_busy``, which a load takes too.
        self._run_kind = ""
        self._loaded_form = None
        self._loaded_info = None
        self._card_device = None            # item 99: the card the loaded image was read off
        self._card_device_name = ""
        #: The record the loaded card carries (item 93; trees_from_inspect),
        #: and what the last dry-run said an update of it would write - or
        #: {"refused": why} when the tool would not.  Neither is persisted:
        #: they are the editing baseline's, and a restore reads nothing.
        self._loaded_trees = None
        self._update_info = None
        self._armed = False
        self._media_override = ""       # the loaded card's media dir
        self._out_var = tk.StringVar()
        self._move_var = tk.StringVar(value="auto")
        self._confirm_var = tk.StringVar(value="auto")
        self._volume_var = tk.StringVar(value=str(self._backend.volume_default))
        self._machine_vol_var = tk.BooleanVar(value=True)
        self._timeout_var = tk.StringVar(value="15")
        #: The line across the top of the menu (PAD-135).  It STARTS as the
        #: selector's own wording rather than empty, because the box has to
        #: read as what the menu says: emptying it is how somebody asks for
        #: no heading at all.
        self._heading_var = tk.StringVar(value=DEF_HEADING)
        #: Same text size on every card (PAD-183): ON, which is what the
        #: selector does when nothing says otherwise.
        self._same_text_var = tk.BooleanVar(value=True)
        #: The card counter under the cards, and the countdown's first word
        #: (PAD-190): both start as what the selector itself draws.
        self._counter_var = tk.BooleanVar(value=True)
        self._countdown_word_var = tk.StringVar(value=DEF_COUNTDOWN_WORD)
        #: ...and the instructions line as its two fields: drawn at all, and
        #: the words (empty = the selector's own, which is what every card
        #: written before this existed carries).
        self._footer_var = tk.BooleanVar(value=True)
        self._footer_text_var = tk.StringVar(value="")
        self._default_var = tk.StringVar(value="0")
        #: The compact layout (item 95): OFF by default, and it stays off
        #: until the user ticks it - never set from a card that is merely
        #: loaded, only from one whose layout inspect reports as 'store'.
        #: Made here unless the size strip (built earlier) already did.
        if not hasattr(self, "_compact_var"):
            self._compact_var = tk.BooleanVar(value=False)
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
        #: HOW A RANDOM CARD PICKS, as the two controls that ask it: which
        #: of ROLL_DRAWS, and the rule over it.  row.roll is the one word the
        #: pair spells (roll_from_parts), so the card's vocabulary is
        #: unchanged - this is only how it is asked.
        self._ed_roll = tk.StringVar(value=roll_draw(ROLL_DEFAULT))
        self._ed_roll_norepeat = tk.BooleanVar(
            value=roll_no_repeat(ROLL_DEFAULT))
        #: What the tick said while it was still a question, so coming back
        #: off a shuffle is the round trip it looks like.  None = nothing to
        #: put back.
        self._roll_norepeat_free = None
        self._ed_picture = tk.StringVar()
        self._ed_video = tk.StringVar()
        self._ed_music = tk.StringVar(value="none")
        self._ed_confirm = tk.StringVar(value="menu")
        self._ed_anim_start = tk.StringVar()
        self._ed_media_vars = (self._ed_media, self._ed_picture,
                               self._ed_video, self._ed_anim_start)
        for var in (self._ed_title, self._ed_sub, self._ed_music,
                    self._ed_confirm, self._ed_roll, self._ed_roll_norepeat):
            var.trace_add("write", lambda *_a: self._editor_changed())
        # ...and a write to what the image SHOWS is the one time the row's
        # art and animation are derived again from the dialog's choice.
        for var in self._ed_media_vars:
            var.trace_add("write",
                          lambda *_a: self._editor_changed(media=True))
        # ...and the menu's own fields, so the 'what would Apply write' line
        # follows every keystroke while a card is loaded.
        for var in (self._move_var, self._confirm_var, self._volume_var,
                    self._machine_vol_var, self._timeout_var,
                    self._heading_var, self._same_text_var, self._counter_var,
                    self._countdown_word_var, self._footer_var,
                    self._footer_text_var, self._default_var):
            var.trace_add("write", lambda *_a: self._menu_changed())
        # Item 100: the compact tick beside the size strip.  Not a menu field
        # (an inject never changes a card's layout: diff_forms puts it in the
        # rebuild bucket), and what it changes is the SIZE - so it re-plans.
        self._compact_var.trace_add("write", lambda *_a: self._compact_changed())
        self._theme_var.trace_add("write", lambda *_a: self._theme_changed())
        for var in self._color_vars.values():
            var.trace_add("write", lambda *_a: self._color_changed())
        # The preview.  Frames are cached per (form fingerprint, highlight,
        # frame index) -> PPM path; the frame counts per (fingerprint,
        # highlight), learned from the selector's own log line.
        self._hl_var = tk.StringVar(value="0")
        self._frame_var = tk.StringVar(value="0")
        #: ALWAYS ON (David, 2026-09-03): there is no Play control any more;
        #: the flag says whether the ticks are running right now (they stop
        #: while a redraw is on its way and start again when it lands).
        self._play_var = tk.BooleanVar(value=True)
        self._pv_cache = {}
        self._pv_totals = {}
        #: (fingerprint, highlight) -> {image: (x, y, w, h)}: where the
        #: selector put every visible animated card's picture in its frame
        #: (the snapshot line's ``pictures``), which is where the clips are
        #: laid.  An empty dict = drawn, and nothing animates.
        self._pv_rects = {}
        #: (media fingerprint, media dir) whose PICTURES are rendered - the
        #: video half; ``_pv_ready`` below is the whole set, sounds too.
        self._pv_visual = None
        #: What the strip's Video / Audio readouts say.
        self._media_state = {"video": "", "audio": ""}
        #: The frame Play composes on, as a Pillow image at the box's size:
        #: ((path, box w, box h), image).  One is enough.
        self._pv_base = None
        #: The clips playing: {image: (key, ClipFrames)}, see _play_clips.
        self._clips = {}
        #: The clips' shared clock (time.monotonic at the first tick): every
        #: clip's frame is where its own timeline is at, so a redraw, a
        #: flipper press or a busy moment never restarts them - the
        #: machine's do not stop either.
        self._play_t0 = None
        #: {image: frame} last composed, so a tick that moves nothing draws
        #: nothing.
        self._play_frames = None
        #: The fingerprint and media directory of the LAST render asked
        #: for - what the ticks read, so that a tick never calls form()
        #: (form() -> media_dir() -> isfile(media.json) is the blocking
        #: stat a dead drive turns into a frozen tab).
        self._pv_fp = None
        self._pv_media = None
        #: The clips' clock; the tests hand in one they control.
        self._play_clock = time.monotonic
        #: What the canvas holds while Play composes: (base PPM, highlight,
        #: frame count) - so stopping, or a resize, can go back to the
        #: rendered frame under it.  None whenever a rendered file is up.
        self._composite = None
        #: When Play's next frame is due (time.monotonic seconds), so the
        #: ticks keep the CLIP's timeline and a late timer does not slow
        #: the loop - what the selector does against its vsync.
        self._play_due = None
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
        self._black_still = None        # the LOADING frame the beat is holding
        self._pv_load_frame = None      # ...and the one the last render wrote
        self._hl_touched = False        # Highlight typed by hand: stop following Default
        self._play_job = None
        self._play_fp = None
        self._play_hl = 0
        #: THE PREVIEW'S SOUND, AND IT IS ALWAYS ON (David, 2026-09-03:
        #: "sound and video should always be on for the preview" - the one
        #: place his bring-things-up-muted rule does not apply, by his own
        #: ask).  Nothing opens a device until there is a sound to play;
        #: ``_audio`` is built on the first one and kept - the player
        #: releases the device on stop() and takes it again on the next
        #: loop().  The flag stays as the tests' seam for silence.
        self._sound_var = tk.BooleanVar(value=True)
        #: ...AND ONLY WHILE THIS TAB IS ON SCREEN (David: "even if I'm not
        #: in the multiboot tab, the audio of the first selection is
        #: already playing. It should only be playing when I'm on the
        #: multiboot tab"): the tab's frame is unmapped behind another tab
        #: and while the window is minimised, and that is when the sounds
        #: stop (see _on_hidden / _on_shown, bound in build()).
        self._pv_hidden = True
        #: The preview's own volume and mute - the Emulate tab's knob, kept
        #: in PREVIEW_AUDIO_CTL_FILE.  Scales the menu's volume; 0 muted.
        gain0, mute0 = load_preview_ctl()
        self._pv_gain_var = tk.DoubleVar(value=gain0 * 100)
        self._pv_mute_var = tk.BooleanVar(value=mute0)
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
                    self._ed_confirm, self._ed_roll,
                    self._ed_roll_norepeat) + self._ed_media_vars + (
                    self._move_var, self._confirm_var, self._volume_var,
                    self._timeout_var, self._heading_var, self._same_text_var,
                    self._counter_var, self._countdown_word_var,
                    self._footer_var, self._footer_text_var,
                    self._default_var, self._out_var, self._selector_var,
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
                     "_sound_job", "_plan_job", "_select_job", "_black_job",
                     "_size_anim_job"):
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

    # ------------------------------------------------------------------
    # the platform (item 118)
    # ------------------------------------------------------------------

    @property
    def platform(self):
        """``stern`` or ``jjp`` - which builder, which words, which medium."""
        return self._backend.key

    def _pk(self):
        """The ``platform=`` keyword for the module functions - and NOTHING
        on the Stern platform, so every call the Stern tests stub with the
        functions' old signatures is made exactly as it always was."""
        return {} if self._backend.key == "stern" else {"platform": self._backend.key}

    def set_platform(self, key):
        """Switch the tab to another manufacturer's multi-boot: the JJP install
        ISO (mkjjpmulti.py) or back to the Stern card.  The form is the other
        platform's, so it is cleared the way New card clears it; the words on
        the tab and the controls that only one platform has follow.  Nothing
        on disk is touched.  Returns True when the platform changed."""
        be = backend_for(key)
        if be.key == self._backend.key:
            return False
        if self._busy:
            self._error("Wait for the current run to finish before switching "
                        "the manufacturer.")
            return False
        self._backend = be
        if getattr(self, "_rows", None) is not None and hasattr(self, "_out_var"):
            self.new_card()
        self._apply_platform_words()
        return True

    def _apply_platform_words(self):
        """Every widget whose text or presence is the platform's: the label
        beside the path box, the size strip's label, the green button, the
        status checks, and the controls only the Stern card has (the reader,
        Recover images…, the compact layout).  Safe before build() and on a
        headless panel: a widget that is not there is skipped."""
        be = self._backend
        self.BUILD_FLASH_TEXT = be.build_flash_text
        # the menu program's directory: the other platform's default is no
        # place for this one's binary, so a default is swapped and a path
        # somebody set (PAD_MULTIBOOT_SELECTOR, or typed) is left alone
        sel = getattr(self, "_selector_var", None)
        if sel is not None:
            cur = sel.get().strip()
            if be.key == "jjp" and (not cur or cur == DEFAULT_SELECTOR_DIR):
                sel.set(be.selector_default)
            elif be.key == "stern" and cur == JJP.selector_default:
                sel.set(os.environ.get("PAD_MULTIBOOT_SELECTOR") or DEFAULT_SELECTOR_DIR)
        about = getattr(getattr(self, "_about_badge", None), "icon_tip", None)
        if about is not None:
            about.text = self.ABOUT_TIP if be.key == "stern" else self.ABOUT_TIP_JJP
        # THE LIST'S AND THE SIZE STRIP'S WORDS: two install ISOs and no
        # random card on JJP, a USB stick rather than an SD card, and no
        # compact layout or in-place update to explain.  Instance attributes
        # over the class's, so a Stern panel keeps the texts its tests pin.
        cls = type(self)
        jjp = be.key == "jjp"
        self.ADD_ROW_TEXT = cls.ADD_ROW_TEXT_JJP if jjp else cls.ADD_ROW_TEXT
        self.LIST_TIP = cls.LIST_TIP_JJP if jjp else cls.LIST_TIP
        self.SIZE_TIP = cls.SIZE_TIP_JJP if jjp else cls.SIZE_TIP
        table = getattr(self, "_table", None)
        if table is not None:
            table.add_text, table.add_tip = self.ADD_ROW_TEXT, self.LIST_TIP
            add_row = getattr(table, "_add_row", None)
            if add_row is not None:
                # the add row takes its words and its tip when it is made:
                # remake it, and the table places it again
                try:
                    add_row.destroy()
                    table._add_row = None
                    table.set_rows(list(getattr(table, "_values", None) or []),
                                   select=getattr(table, "_sel", None))
                except tk.TclError:                     # pragma: no cover
                    pass
        need_tip = getattr(self, "_size_need_tip", None)
        if need_tip is not None:
            need_tip.text = self.SIZE_TIP
        if getattr(self, "_size_canvas", None) is not None:
            self._draw_size()                   # re-reads SIZE_TIP for the strip
        for attr, text in (("_src_lbl", be.out_label),
                           ("_size_lbl", be.medium_needed)):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.configure(text=text)
                except tk.TclError:                     # pragma: no cover
                    pass
        labels = dict(be.status_checks)
        for key, lbl in (getattr(self, "_check_lbls", None) or {}).items():
            try:
                cur = lbl.cget("text")
                mark = cur[:1] if cur else CHECK_MARKS["no"]
                lbl.configure(text="%s %s" % (mark, labels.get(key, cur[2:])))
            except tk.TclError:                         # pragma: no cover
                pass

        def show(attr, wanted, **pack):
            w = getattr(self, attr, None)
            if w is None:
                return
            try:
                if wanted and not w.winfo_manager():
                    w.pack(**pack)
                elif not wanted and w.winfo_manager():
                    w.pack_forget()
            except tk.TclError:                         # pragma: no cover
                pass
        show("_from_card_btn", be.read_card, side=tk.RIGHT, padx=(0, 6))
        menu_btn = getattr(self, "_menu_btn", None)
        show("_recover_btn", be.extract, side=tk.LEFT, padx=(6, 0),
             **({"after": menu_btn} if menu_btn is not None else {}))
        need = getattr(self, "_size_need", None)
        show("_compact_chk", be.compact, side=tk.LEFT, padx=(0, 8),
             **({"after": need} if need is not None else {}))
        if hasattr(self, "_buildflash_btn"):
            self._sync_build_button()
        if getattr(self, "_check_lbls", None):
            self._draw_checks()

    # -- 1. where the card comes from ----------------------------------

    #: What the path box itself says it is - and it has to carry what the
    #: two dead buttons' tooltips carried, because it is now the only thing
    #: in the row that names both of the tab's modes.
    PATH_TIP = ("The card this tab is pointing at. A path with a card "
                "already at it is one you can read: reading it fills every "
                "field from it - images, titles, subtitles, art, animation, "
                "music, sounds, volume, countdown and default - and "
                "'Update the loaded card in place', in the green button's "
                "dialog, then writes your changes back into it in seconds. "
                "A path with nothing at it yet is where that same button "
                "writes a new card. Browse… does both: it takes a card that "
                "exists and a name that does not. Picking an existing card "
                "in Browse… reads it, and so does Enter in this box; a "
                "typed path never does by itself, because a half-typed one "
                "names the wrong card.")

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

    #: What the strip says before the sentence the tool wrote.  A card
    #: whose images disagree still boots and still plays - what it costs is
    #: settings and, at worst, a node board reflash on every swap - so this
    #: is a warning in the app's error colour, not a refusal.  The refusal
    #: is the builder's, and it happens before a byte is written.
    ALARM_PREFIX = "\u26a0 "

    def _version_alarm(self, info):
        """:func:`version_alarm` for the card this tab has loaded - which
        knows whether that card is only a menu read off an SD card."""
        if not info:
            return None
        return version_alarm(info, menu_only=bool(
            getattr(self, "_card_device", None)
            or is_menu_image(getattr(self, "_loaded_card", ""))))

    def _show_alarm(self, info):
        """Put the version gate's finding on the tab, or take it away.

        Called with the report a load read; ``None`` clears it (a new card,
        or one whose images agree).  The whole finding goes to the Log -
        the strip is one line by construction and the reasons run long."""
        found = self._version_alarm(info)
        head, full = found if found else ("", "")
        if info and info.get("unknown_version") \
                and str(info["unknown_version"]).strip() not in full:
            # the finding a menu-only card cannot help making, said calmly
            self._write("[version] " + MENU_ONLY_VERSIONS)
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

    def _cancel_remeasure(self):
        job = getattr(self, "_measure_job", None)
        self._measure_job = None
        if job is not None:
            try:
                self._timer().after_cancel(job)
            except (tk.TclError, ValueError):           # pragma: no cover
                pass

    # -- 2. the preview, full width -------------------------------------

    # -- 3. the images table --------------------------------------------

    #: The table's TEXT columns, left to right: ``(id, heading, minwidth,
    #: stretch)``.  The four actions live in their own icon column to the
    #: LEFT of these (David: "all of the icons should be on the far left
    #: side"), drawn by the table itself (the page), so they are not
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
        ("title", "Title", 175, True),
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

    #: The right-click menu, in the order the icons are in.  ``needs_row``
    #: entries are greyed when the click missed every image row, so a
    #: right-click on the template row or on empty space offers Add… alone.
    LIST_ACTIONS = (("Add image…", "_add_image", False),
                    ("Add random over the images above…", "_add_random_over_existing", False),
                    ("Add random group…", "_add_group", False),
                    ("Add random group from folder…", "_add_group_folder", False),
                    ("Edit image…", "edit_image", True),
                    ("Remove image", "_remove_image", True),
                    (None, None, False),
                    ("Move up", "_move_up", True),
                    ("Move down", "_move_down", True))

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

    #: The bar's height in the strip's one row.
    SIZE_BAR_H = 20

    #: What the strip says while nobody has measured this list yet.  Never a
    #: number: a stale size is worse than no size, which is the rule the
    #: sentence beside the status line already follows.
    SIZE_UNKNOWN = "\u2014"

    SIZE_TIP = (
        "How big an SD card these images need - measured by the tool, not "
        "guessed from the .raw files, which are all the same size whatever "
        "is inside them. The bar is the card you would have to buy: each "
        "band is one image's games, a hollow one is room the card keeps for "
        "updating an image in place, and the grey one at the end is what the "
        "card spends on itself (boot, rootfs, /data, /dump and the "
        "filesystems' own bookkeeping). It re-measures itself whenever the "
        "image list changes, and for a loaded card it also works out what an "
        "update would write. With Compact build ticked each band is what "
        "that image brings on its own, and the hatched part of the free "
        "room is what compact saved - stored once, so not on the card. "
        "Click the strip to measure it again.")

    COMPACT_TIP = (
        "Compact build: one copy of every file the images "
        "have in common, stored once. Smaller card, same games - the bar "
        "shows what it saves as a hatched part of the free room. A card "
        "built this way must be changed with this app, not by a Stern USB "
        "update. Off = the card layouts this app has always made.")

    #: ...and why it cannot be turned off while a random group is in the list.
    COMPACT_TIP_GROUP = (
        "Compact build, and a random group needs it: the games behind one "
        "card are near-identical, so on the older layouts each one would cost "
        "a full copy of the image. Stored once, forty song sets fit a 32 GB "
        "card. Remove the random group to turn this off.")

    def _compact_changed(self):
        """The compact tick moved: the size is a different question now
        (the plan hashes the images to find what they share), and a loaded
        card's edit status counts a layout change as a rebuild."""
        self._update_edit_status()
        self._maybe_plan()

    FROM_CARD_TIP = (
        "Read the SD card in the reader. The boot menu only (a few hundred "
        "MB, about a minute): titles, pictures, sounds, settings and the "
        "images' sources, without an image file - Apply then writes the menu "
        "back onto that card. Or the whole card into a .raw you name: its "
        "images too, so they can be recovered, replaced or added to, like "
        "any card image on disk. Windows asks for administrator access for "
        "the read and the write.")

    def _from_card_clicked(self):
        if self._busy:
            self._error("A run is already in progress.")
            return
        CardPickDialog(self._parent, self._theme_fn, self.load_from_card)

    def _recover_clicked(self):
        """'Recover images\u2026': the loaded card's images this machine lacks,
        written out of the card into a folder the person picks, and the
        rows pointed at them (see :func:`recover_rows`)."""
        if self._busy:
            self._error("A run is already in progress.")
            return False
        want = self.recoverable()
        if not want:
            self._error("Nothing to recover: every image of the loaded card "
                        "is already on this machine, or the card was read "
                        "from the reader as its menu only.")
            return False
        card = self._loaded_card
        try:
            initial = os.path.dirname(os.path.abspath(card))
        except (OSError, ValueError):                   # pragma: no cover
            initial = ""
        out_dir = filedialog.askdirectory(
            title="Folder for the recovered images", initialdir=initial,
            mustexist=False)
        if not out_dir:
            return False
        return self.recover_images(out_dir, want)

    def recover_images(self, out_dir, indexes=None):
        """The run behind Recover images\u2026: ``extract`` into *out_dir* (with
        the card's menu media beside the images), then every recovered row
        pointed at its file.  The public seam the tests drive.  False when
        the tab refused."""
        card = self._loaded_card
        want = list(indexes if indexes is not None else self.recoverable())
        out_dir = os.path.normpath((out_dir or "").strip().strip('"'))
        if not card or not want:
            self._error("Read a card whose images are not on this machine "
                        "first.")
            return False
        if under_library(out_dir):
            self._error("That folder is in the card library (%s); pick one "
                        "outside it." % LIBRARY_PREFIXES[0])
            return False
        if self._busy:
            self._error("A run is already in progress.")
            return False
        media_out = os.path.join(out_dir, recovered_media_dirname(card))
        self._run_kind = "recover"
        self._ok("Recovering image%s %s off %s into %s\u2026"
                 % ("" if len(want) == 1 else "s",
                    ", ".join(str(i) for i in want),
                    os.path.basename(card), out_dir))

        def done(rc, failed, texts):
            if rc != 0:
                if self.run_cancelled():
                    self._ok("Recovering the images was cancelled; whatever "
                             "was written into %s is half a file." % out_dir)
                    return
                why = parse_refusal(texts.get(failed, ""), card) or \
                    "%s failed (exit %d) - see the Log." % (failed, rc)
                self._error("Cannot recover the images: %s" % why)
                return
            mapping, media = parse_extract(texts.get("extract", ""))
            if not mapping:
                self._error("The recovery printed no image paths - see the "
                            "Log.")
                return
            notes = recover_rows(self._rows, mapping, media, self._loaded_info)
            if self._loaded_form is not None:
                # the baseline moves with the rows: a recovery is not a
                # change to the card, and must not read as one
                recover_rows(self._loaded_form.images, mapping, media,
                             self._loaded_info)
            # ...and the two menu-wide sounds, made from WAVs that are not
            # here: the card's own copies, in the field and the baseline
            for attr, var, name in (("sound_move", self._move_var, "move.wav"),
                                    ("sound_confirm", self._confirm_var,
                                     "confirm.wav")):
                got = recover_sound(var.get(), media, name)
                if got:
                    self._loading = True
                    try:
                        var.set(got)
                    finally:
                        self._loading = False
                    if self._loaded_form is not None:
                        setattr(self._loaded_form, attr, got)
                    notes.append("the %s is %s" % (attr.replace("_", " "), got))
            # every frame was keyed on the old specs; the picture is the
            # same, the key is not
            self._pv_cache.clear()
            self._pv_totals.clear()
            self._pv_shown = None
            self._refresh_tree(select=self._selected())
            self._update_edit_status()
            self._schedule_probe(refresh=True)
            self._ok("Recovered %d image%s into %s. %s can update this "
                     "card, rebuild it, or build a fresh one with another "
                     "image added."
                     % (len(mapping), "" if len(mapping) == 1 else "s",
                        out_dir, WRITE_BUTTON))
            for line in notes:
                self._write("[recover] " + line)
        return self._run_commands(
            extract_commands(card, out_dir, media_out, want), on_done=done)

    def load_from_card(self, device_path, drive, whole=False):
        """Read the card at *device_path* (elevated, off-thread) and load
        what was read.  The menu only (the default): into
        :func:`menu_card_image_path`, and the card is remembered so Apply
        writes the menu back onto it.  *whole*: the card image - up to the
        end of its partition table, the games too - into a .raw the person
        names, loaded like any card on disk (so its images can be recovered,
        replaced or added to; flashing it back is the Build / flash dialog's
        flash section).  False when the tab refused."""
        if self._busy:
            self._error("A run is already in progress.")
            return False
        name = getattr(drive, "display", None) or device_path
        if whole:
            path = self._ask_card_image_path(drive)
            if not path:
                return False
            self._pending_device = None
            what = "the card"
        else:
            path = menu_card_image_path(drive)
            self._pending_device = (path, device_path, name)
            what = "the boot menu"
        self._card_device = None
        self._set_busy(True)
        self._run_kind = "load"
        self._ok("Reading %s off %s\u2026" % (what, name))
        self._phase_fn(3, status="Reading %s off the card\u2026" % what)
        last = [0]

        def log(text, level="info"):
            self._ui(lambda: self._log_sink("[card] " + text))

        def progress(done, total, msg=""):
            if total and done - last[0] >= total // 10:
                last[0] = done
                self._ui(lambda: self._status_fn("%s %d%%" % (msg or "Reading\u2026", 100 * done // total)))

        def run():
            from ..core import elevated_flash as _ef
            try:
                if whole:
                    _ef.read_device_with_privileges(device_path, path, log=log, progress=progress,
                                                    extent="card")
                else:
                    _ef.read_device_menu_with_privileges(device_path, path, log=log, progress=progress)
            except Exception as exc:                       # noqa: BLE001 - reported, never lost
                err = exc                                   # the name dies with the except block
                self._ui(lambda: self._from_card_failed(name, err, what))
                return
            self._ui(lambda: self._from_card_read(path))

        threading.Thread(target=run, daemon=True).start()
        self._drain()
        return True

    def _ask_card_image_path(self, drive):
        """Where a whole-card read lands: a .raw the person names, offered
        next to the card in the path box (or in their home) as
        ``<model>-<size>G.sdcard.raw``.  '' when the dialog was cancelled or
        the choice is one the tools would refuse."""
        model = re.sub(r"[^A-Za-z0-9._-]+", "_",
                       (getattr(drive, "model", "") or "card").strip()) or "card"
        size = int(getattr(drive, "size_bytes", 0) or 0)
        initialfile = ("%s-%dG.sdcard.raw" % (model, round(size / 1e9))
                       if size else "%s.sdcard.raw" % model)
        cur = self._out_var.get().strip().strip('"')
        initialdir = os.path.dirname(os.path.abspath(cur)) if cur else \
            os.path.expanduser("~")
        if under_library(initialdir):
            initialdir = os.path.expanduser("~")
        path = filedialog.asksaveasfilename(
            title="Save the card image as", initialdir=initialdir,
            initialfile=initialfile, defaultextension=".raw",
            filetypes=[("Card images", "*.raw *.img"), ("All files", "*.*")])
        path = (path or "").strip()
        if not path:
            return ""
        if under_library(path):
            self._error("That path is in the card library (%s), which "
                        "nothing here may write into - pick another folder."
                        % LIBRARY_PREFIXES[0])
            return ""
        return os.path.normpath(path)

    def _from_card_failed(self, name, exc, what="the boot menu"):
        self._set_busy(False)
        self._pending_device = None
        self._error("Cannot read %s off %s: %s" % (what, name, exc))

    def _from_card_read(self, path):
        self._set_busy(False)
        self._out_var.set(path)
        self.load_card(path)

    def _write_menu_to_device(self, after=None):
        """After an Apply into the image that was read off a card (item 99):
        the menu partition onto that card, elevated, off-thread - the app's
        own menu-only write, which proves the card is that card first."""
        path, device_path, name = self._loaded_card, self._card_device, self._card_device_name
        self._set_busy(True)
        self._ok("Writing the menu onto %s\u2026" % name)
        self._phase_fn(2, status="Writing the boot menu onto the card\u2026")
        last = [0]

        def log(text, level="info"):
            self._ui(lambda: self._log_sink("[card] " + text))

        def progress(done, total, msg=""):
            if total and done - last[0] >= max(1, total // 10):
                last[0] = done
                self._ui(lambda: self._status_fn("%s %d%%" % (msg or "Writing\u2026", 100 * done // total)))

        def run():
            from ..core import elevated_flash as _ef
            try:
                _ef.flash_image_with_privileges(path, device_path, log=log, progress=progress,
                                                menu_only=True)
            except Exception as exc:                       # noqa: BLE001 - reported, never lost
                err = exc
                self._ui(lambda: self._menu_write_done(name, err, after))
                return
            self._ui(lambda: self._menu_write_done(name, None, after))

        threading.Thread(target=run, daemon=True).start()
        self._drain()
        return True

    def _menu_write_done(self, name, exc, after):
        self._set_busy(False)
        if exc is not None:
            self._error("The menu was updated in the image but NOT written onto %s: %s"
                        % (name, exc))
            return
        self._ok("Menu written onto %s - the card can go back in the machine." % name)
        if after is not None:
            after()

    def _remeasure(self, _event=None):
        """Measure this image list again, now - what clicking the size strip
        does.  True when a run was armed.

        It forgets which list was last asked about, so :meth:`_maybe_plan`
        sees the question as new and arms the debounce; the stale number
        goes on the way in, exactly as it does when the list moves."""
        if self._stopped or not self._auto_plan:
            return False
        self._plan_for = None
        self._maybe_plan()
        self._draw_size()
        return self._plan_job is not None

    def size_view(self):
        """What the strip is showing - the seam the tests read."""
        return self._size_view

    #: How much of a sentence the strip's one line takes before the rest of
    #: it moves to the tooltip.  The bar is what would otherwise be squeezed
    #: out: this row gives up the CANVAS first, not the words.
    SIZE_DETAIL_MAX = 92

    #: The head while the strip is thinking: the answer is on its way.
    SIZE_THINKING = "\u2026"

    def _size_state(self):
        """``(state, text)`` of a strip with no measurement: ``missing`` (an
        image is not on this machine), ``measuring`` (the debounce is armed
        or the check is on the worker - the strip shows it is thinking),
        ``failed``, or ``idle`` (nothing to measure, nothing to say)."""
        if len(self._rows) < 1:
            return "idle", ""
        # WHAT IT CANNOT MEASURE COMES FIRST.  A list with a missing .raw
        # still arms the debounce (the check is _plan_now's, a second later),
        # so asking about the job first would say "Measuring..." for ever
        # about a card nothing is going to measure.
        # ...and a row's images are its MEMBERS when it is a random card
        # (PAD-189): the group row's own path is empty by design, so asking
        # it for one said "not on this machine" about a list that was
        # entirely there.
        missing = [r for r in self._rows
                   if not all(q and os.path.isfile(q) for q in row_paths(r))]
        if missing:
            return "missing", ("The images have to be on this machine to be measured."
                               if len(missing) < len(self._rows) else "")
        if self._plan_job is not None or self._plan_busy():
            return "measuring", self._measuring_text()
        if self._plan_failed:
            why = (self._plan_why or "").strip()
            return "failed", ("The size check failed: %s" % why if why
                              else "The size check failed - see the Log.")
        return "idle", ""

    def _size_waiting(self):
        """The strip's line while there is no measurement: what it is waiting
        for, or nothing at all when there is nothing to measure."""
        return self._size_state()[1]

    def _measuring_text(self):
        """'Measuring…' - and with the compact tick on, WHAT is being measured
        and how far along it is.  The compact plan hashes every image the
        first time it sees it (20-30 s for two on David's machine), and a
        bar that says nothing for that long reads as broken."""
        compact = bool(self._compact_var.get()) if hasattr(self, "_compact_var") else False
        text = "Measuring what the images share\u2026" if compact else "Measuring\u2026"
        prog = self._size_progress
        if prog is not None and prog[0] > 0:
            text += " %d%%" % int(prog[0] * 100)
        return text

    def _plan_busy(self):
        """True while the size check itself is on the worker - what tells
        'nobody has measured this' from 'the answer is on its way'."""
        return self._measuring is not None and self._measuring == self._plan_key()

    def size_measuring(self):
        """The strip's thinking state - the seam the tests read: None when it
        is not measuring, else ``{"text", "frac"}`` (``frac`` None until the
        tool's meter has said how far along it is)."""
        state, text = self._size_state()
        if state != "measuring":
            return None
        prog = self._size_progress
        return {"text": text, "frac": prog[0] if prog else None}

    #: The thinking band: how often it moves, how far each move, and its
    #: width as a share of the bar.
    SIZE_ANIM_MS = 60
    SIZE_ANIM_STEP = 5
    SIZE_ANIM_SHARE = 6

    RECOVER_TIP = (
        "Write the loaded card's images back out as .raw files of their own "
        "- for a card someone else built, whose images live on their "
        "machine. Each comes out as a normal card image (the game as p3, the "
        "boot menu taken out), named as the card records it, and the card's "
        "pictures and sounds are copied out beside them; the rows are then "
        "pointed at those files, so the card can be updated, rebuilt or "
        "given another image. Reads the card, writes only into the folder "
        "you pick. Greyed while every image is already on this machine, "
        "and for a card read from the reader as its menu only (read the "
        "whole card for this).")

    #: The green button's two lives.  While a run is up it IS the run's
    #: Cancel - the shape the Write and Extract tabs have had since a tester
    #: hit a second Cancel widget belonging to somebody else's run.
    BUILD_FLASH_TEXT = "Build / flash card\u2026"
    CANCEL_TEXT = "Cancel"
    CANCELLING_TEXT = "Cancelling\u2026"

    BUILD_FLASH_TIP = (
        "Write the card. The dialog decides for you whether that is a full "
        "build (every image copied - the slow one), an update of the card "
        "you loaded (only what changed since it was written - about a "
        "minute), or a menu rewrite (seconds), and it can flash an SD card "
        "in the same step. While the run is going this button is its "
        "Cancel.")

    CANCEL_TIP = (
        "Stop the run in progress. The tool is killed where it stands, so a "
        "card being BUILT is left half-written and has to be built again - "
        "which is the point: a build that is copying three images onto a "
        "card too small for them is an hour you get back. A card being "
        "UPDATED keeps what was already written; pressing the button again "
        "carries on from there.")

    def cancel_run(self):
        """Stop the run in flight.  True when there was one to stop.

        WHAT THIS COSTS, said plainly rather than hidden behind a
        confirmation: the tool is killed where it stands, so a card being
        built is left partly written - it is not a card, and building again
        writes over it.  Nothing else is at risk: the images are read, never
        written, and an Apply that is killed mid-inject leaves the card's own
        selector files half replaced, which the next Apply redoes from
        scratch.

        Killing the Windows-side ``wsl.exe`` DOES take the Linux process with
        it (measured on this machine: the child bash and its debugfs are gone
        within a second), so there is no orphan copying into the card behind
        the tab's back.

        The queued action, if one was waiting for a render, is dropped: a
        press that stops a run must not start the next one."""
        if not self._busy or self._cancel_pending:
            return False
        self._cancel_pending = True
        self._cancelled = True
        self._pending_run = None
        self._write("[multi-boot] cancelling - stopping the tool now.")
        self._ok("Cancelling\u2026")
        self._sync_build_button()
        try:
            self._phase_fn(None, status="Cancelling\u2026")
        except Exception:                               # noqa: BLE001
            pass
        proc, mine = self._proc, not self._proc_preview
        if proc is not None and mine:
            try:
                proc.kill()
            except Exception:                           # noqa: BLE001
                pass            # it finished between the press and the kill
            if _mac.enabled():
                # killing `docker exec` kills the CLIENT; the tool goes on
                # restoring partitions inside the container with nothing
                # watching it.
                _mac.kill_running()
        return True

    def run_cancelled(self):
        """True while the run that has just finished was cancelled - what
        lets a done handler say 'cancelled' instead of 'failed (exit 1)'."""
        return bool(self._cancelled)

    def checks(self):
        """The status row as :func:`status_checks` decided it - the seam the
        tests read, and what :meth:`_draw_checks` paints."""
        field = self._out_var.get().strip().strip('"')
        menu, rebuild = [], []
        if self._loaded_card and self._loaded_form is not None:
            menu, rebuild = self._loaded_diff()
        facts = self._facts_now(field)
        state = card_path_state(field, facts, self._rows, self._loaded_card,
                                menu, rebuild, **self._pk())
        built = None
        if self._built is not None and _plain(self._built[0]) == _plain(field):
            built = diff_forms(self._built[1], self.form())
        # WHAT IS AT THE PATH, in the three values status_checks needs.  A
        # card is one this tab has CONFIRMED - read back, or built here;
        # anything else the probe found is a file, and a file is not a card
        # however it is named.  The probe's answer, never a stat per
        # keystroke.
        if (self._loaded_card
                and _plain(self._loaded_card) == _plain(field)) \
                or built is not None:
            card = "card"
        elif facts.get("kind") == "file":
            card = "file"
        else:
            card = "none"
        return status_checks(self._rows, state, self._loaded_card, menu,
                             rebuild, card, built,
                             self._run_kind if self._busy else "")

    def check_detail(self, key):
        """The sentence behind one check - what the row's second line used to
        say out loud, and what its tooltip says now."""
        for k, _label, _state, detail in self.checks():
            if k == key:
                return detail
        return ""

    def check_state(self, key):
        """One check's state: ok / now / no / bad."""
        for k, _label, state, _detail in self.checks():
            if k == key:
                return state
        return ""

    #: What one status line is worth when the labels cannot be measured yet
    #: (a headless build, a font that has not been laid out).
    STATUS_LINE_H = 20

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
    #: THE TEMPLATE ROW'S WORDS, and they have to FIT: the row sits in the
    #: same grid as every other one and says its
    #: words in the Title column, so a longer label is simply cut off, and
    #: cut off sooner on a narrow window (David, 2026-09-10: "narrow app
    #: window widths, the label for 'add a game image or random group' is
    #: getting cut off").  The full sentence lives in LIST_TIP, which has
    #: no width to fit.
    #:
    #: HOW MANY CHARACTERS THAT IS depends on the FONT, which is why this
    #: label is as short as it is: the column is a pixel minsize divided by
    #: the width of a "0" in TkDefaultFont, so Windows holds 28 of them and
    #: the Linux and macOS CI runners hold 22.  A caption written to the
    #: Windows number ships a cut-off label to everyone else - which is how
    #: the 26-character version got through a green local suite and was
    #: caught by test_the_add_rows_words_fit_the_column_they_sit_in on CI.
    ADD_ROW_TEXT = "Add image or random…"

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
            "code": list_code(row),
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
        self._sync_compact_lock()
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
            if is_group(row):
                kind, path = group_media_kind(row), group_media_file(row)
            else:
                kind, path = media_kind(row), media_file(row)
            self._ed_title.set(row.title)
            self._ed_sub.set(row.subtitle)
            self._ed_media.set(kind)
            self._ed_picture.set(path if kind == "picture" else "")
            self._ed_video.set(path if kind == "video" else "")
            self._ed_music.set(row.music)
            self._ed_confirm.set(row.confirm or "menu")
            self._roll_norepeat_free = None
            self._ed_roll.set(roll_draw(row_roll(row)))
            self._ed_roll_norepeat.set(roll_no_repeat(row_roll(row)))
            # A still taken off a video with no clip yet (an older form)
            # keeps its second as the clip's start.
            self._ed_anim_start.set(row.anim_start or (
                row.art_time if kind == "video" else ""))
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
        self._sync_confirm_note()
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
        if is_group(row):
            draw = self._ed_roll.get().strip()
            if draw not in ROLL_DRAW_NAMES:
                draw = roll_draw(ROLL_DEFAULT)
            row.roll = roll_from_parts(
                draw, bool(self._ed_roll_norepeat.get()))
        was = (row.music, row.confirm)
        row.music = self._ed_music.get()
        # "menu" is what the box says and "" is what the row keeps, so a row
        # that inherits compares equal however the dialog spelled it
        conf_v = self._ed_confirm.get()
        row.confirm = "" if conf_v.strip().lower() == "menu" else conf_v
        if (row.music, row.confirm) != was and self._pv_fp is not None:
            # HEARD NOW, not after the next render: 'none' stops the bed
            # this instant, and a new choice goes quiet until it is
            # rendered (menu_sounds judges the file on disk stale).  Only
            # once the preview is up (_pv_fp): before a frame there is no
            # sound to follow, and no device to open for one.
            self._sound_follow()
        if media:
            self._apply_media(i, row)
        # ...and the card on the right of the dialog follows the row, AFTER
        # the row has been written: it draws what the card will show, which
        # is a question about the row and not about the boxes (PAD-187).
        self._sync_image_preview()
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
        if is_group(row) and kind != "card":
            # THE TWO LISTS SHARE 'picture', 'none' AND 'card' AND NOTHING
            # ELSE, so a choice left over from an image row (the dialog is one
            # set of vars for every row) is not a choice this row can make.
            set_group_media(row, kind if kind in GROUP_MEDIA_NAMES
                            else GROUP_MEDIA_DEFAULT, self._ed_picture.get())
            return
        if kind == "card":
            if self._edit_backup is not None and self._edit_backup[0] == i:
                was = self._edit_backup[1]
                for name in ("art", "anim", "art_video", "art_time",
                             "anim_start", "art_on_card", "anim_on_card"):
                    setattr(row, name, getattr(was, name))
            return
        path = {"picture": self._ed_picture,
                "video": self._ed_video}.get(kind)
        set_media(row, kind, path.get() if path is not None else "",
                  self._ed_anim_start.get())

    def _sync_editor_states(self):
        """Each option's fields live only while it is the choice: the
        picture entry for 'picture', the video entry for 'video', the clip
        fields for either video.  (The Browse… buttons stay live: picking a
        file is picking the option.)"""
        kind = self._ed_media.get().strip()
        dlg = getattr(self, "_image_dialog", None)
        if dlg is not None:
            # ...and the list box shows the choice however it was made -
            # here, in the box itself, or by browsing to a file (PAD-187).
            dlg.sync_kind()
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
        # ...and the same for 'Never the one it booted last', which a shuffle
        # answers itself: greyed ON rather than hidden, so the rule is still
        # visible (PAD-185).  What it said while it was a question is put back
        # when the dice are chosen again, so the round trip is a round trip.
        box = getattr(self, "_roll_repeat_box", None)
        if box is None:
            return
        locked = roll_repeat_locked(self._ed_roll.get().strip())
        if locked:
            if not self._ed_roll_norepeat.get():
                self._roll_norepeat_free = False
                self._ed_roll_norepeat.set(True)
        elif self._roll_norepeat_free is not None:
            free, self._roll_norepeat_free = self._roll_norepeat_free, None
            if bool(self._ed_roll_norepeat.get()) != free:
                self._ed_roll_norepeat.set(free)
        try:
            box.configure(state=tk.DISABLED if locked else tk.NORMAL)
        except tk.TclError:
            pass

    def _sync_confirm_note(self):
        """Edit image…'s 'Plays …' line <- the Confirm sound box, while that
        dialog is up (BEN, PAD-184).  The line lives in the dialog and the
        trace that feeds it lives here, so a closed dialog is simply nothing
        to tell."""
        dlg = getattr(self, "_image_dialog", None)
        if dlg is not None:
            dlg.sync_confirm_note()

    def _sync_image_preview(self):
        """Edit image…'s preview card <- the row, while that dialog is up
        (BEN, PAD-187).  Same shape as the confirm line above: the picture
        lives in the dialog, the traces that feed it live here."""
        dlg = getattr(self, "_image_dialog", None)
        if dlg is not None:
            dlg.sync_preview()

    def menu_colors(self):
        """The menu's colours as they stand - ``{role: rrggbb}``, the grid
        the theme seeded or the owner typed, with the default theme's own
        value for anything blank.  What the dialog's preview draws a card
        in; the card itself is built from the same grid (:meth:`form`)."""
        out = dict(theme_colors(DEFAULT_THEME) or {})
        out.update(clean_colors({role: var.get()
                                 for role, var in self._color_vars.items()}))
        return out

    def add_image(self, path):
        """Append a card image (the public half of Add image…)."""
        path = (path or "").strip().strip('"')
        if not path:
            return
        be = self._backend
        if len(self._rows) >= min(MAX_IMAGES, be.max_cards):
            self._error("At most %d images fit one %s."
                        % (min(MAX_IMAGES, be.max_cards), be.out_noun))
            return
        title, subtitle = suggest_title(path, be.key)
        self._rows.append(ImageRow(path=path, title=title, subtitle=subtitle))
        self._refresh_tree(select=len(self._rows) - 1)
        if len(self._rows) == 1:
            self._maybe_default_output()
        self._ok("")

    #: What the add row at the foot of the list offers, as
    #: ``(label, method name)``.  Pure, so a test can ask what the row would
    #: show without popping a menu.
    ADD_ROW_CHOICES = (("Add image…", "_add_image"),
                       ("Add random over the images above…", "_add_random_over_existing"),
                       ("Add random group…", "_add_group"),
                       ("Add random group from folder…", "_add_group_folder"))

    def add_row_choices(self):
        """The add row's choices, as ``(label, method, enabled, why)``.

        EVERY CHOICE IS ALWAYS SHOWN, and the ones that cannot apply yet are
        greyed with the reason in their label.  The first version offered
        nothing at all on an empty list and went straight to the file dialog,
        which is the right OUTCOME - the first image is the primary and can
        never be a roll - but it means a row promising "image or random group"
        silently does one of them and teaches nobody that the other is there
        (David, 2026-09-10: "left clicking either of these when the selections
        are blank only lets me add a single image first").
        """
        plain = sum(1 for r in self._rows if not is_group(r))
        out = []
        for label, attr in self.ADD_ROW_CHOICES:
            if attr != "_add_image" and not self._backend.groups:
                continue                  # a JJP install has no random cards
            why = ""
            if attr == "_add_random_over_existing" and plain < 2:
                why = "add two images first"
            elif attr != "_add_image" and not self._rows:
                why = "add the primary image first"
            out.append(((label if not why else "%s  (%s)" % (label, why)),
                        attr, not why, why))
        return tuple(out)

    def _add_row_clicked(self):
        """The add row at the foot of the list.

        A GROUP HAD NO DISCOVERABLE WAY IN.  Both group commands were on the
        right-click menu only, while the big obvious row at the bottom of the
        list still added a plain image - so somebody looking for the feature
        would not find it (David, 2026-09-10, on the built branch: "I don't see
        any interface in the GUI for a user to do so").  The row asks now."""
        self._popup_add_menu(self.add_row_choices())

    def _add_image(self):
        path = filedialog.askopenfilename(
            title=self._backend.image_pick_title,
            filetypes=list(self._backend.image_types))
        if path:
            self.add_image(path)

    def add_group(self, paths, title="", subtitle=""):
        """Append a GROUP card: one row the menu draws, several games behind it,
        a different one booted every power-up (item 106).  The public half of
        Add group…, and what the tests drive."""
        paths = [(q or "").strip().strip('"') for q in (paths or [])]
        paths = [q for q in paths if q]
        if not paths:
            return
        if len(self._rows) >= MAX_CARDS:
            self._error("At most %d images fit one card." % MAX_CARDS)
            return
        if not self._rows:
            # image 0 is the primary and the machine boots it when the menu is
            # not honoured, so it cannot be a roll
            self._error("Add the primary (stock) image first: the first image "
                        "cannot be a random group.")
            return
        trees = len(form_trees(self.form())) + len(paths)
        if trees > MAX_TREES:
            self._error("That would be %d games; at most %d fit one card."
                        % (trees, MAX_TREES))
            return
        if sum(1 for r in self._rows if is_group(r)) >= MAX_GROUPS:
            self._error("At most %d random groups fit one card." % MAX_GROUPS)
            return
        # PICKING GAMES THAT ARE ALREADY ON THE CARD MEANS THE OTHER KIND OF
        # RANDOM CARD.  A consuming group would put a second copy of each on the
        # card and the form would refuse itself with "game 1 is listed twice" -
        # which is what David got, and the only sign of it was the preview
        # declining to redraw.  What he asked for by picking them is a card that
        # rolls between the builds that are there, which is the keeping kind.
        on_card = {}
        for ri, r in enumerate(self._rows):
            if not is_group(r):
                for q in row_paths(r):
                    on_card.setdefault(_norm(q), ri)
        already = [q for q in paths if _norm(q) in on_card]
        keep = len(already) == len(paths)
        if already and not keep:
            self._error(
                "%d of these %d games are already on the card (%s). A random "
                "card either rolls between games that are already here, or "
                "brings its own - not both."
                % (len(already), len(paths),
                   ", ".join(os.path.basename(q) for q in already[:3])))
            return
        members = [MemberRow(path=q, title=suggest_title(q)[0]) for q in paths]
        self._rows.append(set_group_media(
            ImageRow(path="", title=title or "RANDOM", subtitle=subtitle,
                     members=members, keep=keep, roll=ROLL_DEFAULT),
            GROUP_MEDIA_DEFAULT))
        self._refresh_tree(select=len(self._rows) - 1)
        # a group forces the compact build; show that in the tick straight away
        self._sync_compact_lock()
        self._ok("")

    def _add_group(self):
        paths = filedialog.askopenfilenames(
            title="Pick the card images this one card will choose between",
            filetypes=[("Card images", "*.raw *.img"), ("All files", "*.*")])
        if paths:
            self.add_group(list(paths))

    def add_random_over_existing(self, title="RANDOM", subtitle=""):
        """A random card over the images ALREADY in the list, which keep their
        own cards (item 106, reopened).  This is David's `C1 | C2 | RANDOM`: the
        menu offers the builds AND a "surprise me" beside them, and it adds not
        one byte to the card because it puts no new game on it."""
        plain = [r for r in self._rows if not is_group(r)]
        if len(plain) < 2:
            self._error("Add at least two images first: a random card chooses "
                        "between images that are already on the card.")
            return
        if len(self._rows) >= MAX_CARDS:
            self._error("At most %d images fit one card." % MAX_CARDS)
            return
        if sum(1 for r in self._rows if is_group(r)) >= MAX_GROUPS:
            self._error("At most %d random groups fit one card." % MAX_GROUPS)
            return
        members = [MemberRow(path=(r.path or "").strip().strip(chr(34)),
                             title=(r.title or "").strip(), version=r.version)
                   for r in plain]
        self._rows.append(set_group_media(
            ImageRow(path="", title=title, subtitle=subtitle, members=members,
                     keep=True, roll=ROLL_DEFAULT), GROUP_MEDIA_DEFAULT))
        self._refresh_tree(select=len(self._rows) - 1)
        self._ok("")

    def _add_random_over_existing(self):
        self.add_random_over_existing()

    def add_group_from_folder(self, folder):
        """Every ``*.raw`` in *folder*, sorted, as one group card.  Forty
        song-set variants are a folder, not a file dialog somebody should have
        to shift-click through - which is the case that filed this item."""
        try:
            names = sorted(n for n in os.listdir(folder)
                           if n.lower().endswith((".raw", ".img")))
        except OSError as e:
            self._error("Cannot read %s: %s" % (folder, e))
            return
        if not names:
            self._error("No .raw card images in %s." % folder)
            return
        self.add_group([os.path.join(folder, n) for n in names],
                       title=os.path.basename(os.path.normpath(folder)).upper())

    def _add_group_folder(self):
        folder = filedialog.askdirectory(
            title="Pick a folder of card images for one random card")
        if folder:
            self.add_group_from_folder(folder)

    def _sync_compact_lock(self):
        """A group forces the compact build, so the tick goes on and greys out
        while one is in the list - with the tooltip saying why.  mkmulticard
        refuses parts/multi with a group outright; this is the same fact where
        a person can see it BEFORE the press (David, 2026-09-09)."""
        chk = getattr(self, "_compact_chk", None)
        if chk is None:
            return
        locked = any(is_group(r) for r in self._rows)
        try:
            if locked:
                self._compact_var.set(True)
                chk.state(["disabled"])
            else:
                chk.state(["!disabled"])
        except tk.TclError:                             # pragma: no cover
            return
        tip = getattr(self, "_compact_tip", None)
        if tip is not None:
            tip.text = self.COMPACT_TIP_GROUP if locked else self.COMPACT_TIP

    def remove_image(self, i):
        """Remove row *i*, AND every random card's claim on the game it took
        with it (see :func:`drop_game_from_groups`).  The public half of the
        list's delete button, and what the tests drive."""
        if not 0 <= i < len(self._rows):
            return
        gone = self._rows[i]
        del self._rows[i]
        notes = []
        if not is_group(gone):
            for q in row_paths(gone):
                self._rows, said = drop_game_from_groups(self._rows, q)
                notes += said
        self._refresh_tree(select=min(i, len(self._rows) - 1))
        self._sync_compact_lock()       # the last group may have just gone
        if i == 0:
            self._maybe_default_output()
        self._ok(" ".join(notes) if notes else "")

    def _remove_image(self):
        i = self._selected()
        if i is not None:
            self.remove_image(i)

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
        new = default_output_path(self._rows[0].path, self._backend.key)
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
        self._built = None
        self._unreadable = None
        self._loaded_form = None
        self._loaded_info = None
        self._card_device = None            # item 99: the card the loaded image was read off
        self._card_device_name = ""
        self._armed = False
        self._media_override = ""
        self._out_auto_value = ""
        self._show_alarm(None)
        self._plan_info = None
        self._hl_touched = False
        self._loading = True
        try:
            self._out_var.set("")
            self._move_var.set("auto")
            self._confirm_var.set("auto")
            self._volume_var.set(str(self._backend.volume_default))
            self._machine_vol_var.set(True)
            self._timeout_var.set("15")
            self._heading_var.set(DEF_HEADING)
            self._same_text_var.set(True)
            self._counter_var.set(True)
            self._countdown_word_var.set(DEF_COUNTDOWN_WORD)
            self._footer_var.set(True)
            self._footer_text_var.set("")
            self._default_var.set("0")
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
        facts = {"kind": "unknown"}
        if self._probe_for is not None and self._probe_for == field:
            facts = dict(self._probe_facts or {})
        elif self._probe_slow and self._probe_text == field:
            facts = {"kind": "looking"}
        bad = self._unreadable
        if bad is not None and _plain(bad[0]) == _plain(field):
            facts["unreadable"] = bad[1]
        return facts

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
                PROBE_DEBOUNCE_MS, lambda: self._start_probe(refresh))
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
        # the person's OWN edits: an armed tree on the card is not one of
        # them (see _loaded_diff), so it never asks "discard changes?"
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
        # AND SO DOES THE SIZE, for exactly the same reason - and it needs
        # asking for, because _maybe_plan will NEVER ask by itself after a
        # restore: restore_state cancels the arm it made but leaves
        # ``_plan_for`` naming that list, so every later call sees the
        # question as already asked and the strip reads "-" for the whole
        # session (David, on a restored two-image Godzilla card: "why isn't
        # the SD card needed / grey bar filled in").  Of the three things
        # this method starts, it is the mildest: the plan READS the images'
        # superblocks and writes nothing, takes no rig lock, and touches no
        # rootfs.
        if self._plan_info is None and not self._plan_failed:
            self._plan_for = None
            self._maybe_plan()
            # ...and the strip says so: _maybe_plan blanks it on the way IN
            # and arms the debounce after, so nothing has drawn the state it
            # is now in ("Measuring...") until something else redraws.
            self._draw_size()
        if not getattr(self, "_pending_read", False):
            return False
        self._pending_read = False
        if self._busy or self._loaded_card:
            return False
        path = self._out_var.get().strip().strip('"')
        if not path or not os.path.isfile(path):
            return False
        # ...AND THE FORM GOES WITH IT.  "No unsaved edits" above is true of
        # the SAVE (nothing has been typed since the app opened) and not of
        # what was saved: a form left mid-edit on a card that was never
        # rebuilt is exactly what this read would replace.  It is handed
        # over rather than compared here, because what the card holds is not
        # known until it has been read - see :meth:`_carry_restored_edits`.
        self._carry_edits = self.state() if self._rows else None
        started = bool(self._load_or_reload(confirm=False, asked=False))
        if not started:
            self._carry_edits = None
        return started

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

    def _load_or_reload(self, confirm=True, asked=True):
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
        return self.load_card(path, asked=asked)

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
        be = self._backend
        path = filedialog.asksaveasfilename(
            title="The %s to read, or where to build a new one" % be.out_noun,
            defaultextension=be.out_ext, confirmoverwrite=False,
            initialdir=os.path.dirname(cur) if cur else None,
            initialfile=os.path.basename(cur) if cur else None,
            filetypes=list(be.image_types))
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

    def used_sounds(self):
        """The sound files this menu already uses, for the four sound boxes
        in the two modals to offer under their words (:func:`used_sounds`).

        The editor writes through to the selected row on every keystroke, so
        this reads the rows and the two menu variables and is right the
        moment a box drops open - including a file browsed into another box
        in the same sitting."""
        return used_sounds(self._rows, self._move_var.get(),
                           self._confirm_var.get())

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
        self._roll_repeat_box = None
        self._roll_norepeat_free = None

    def open_menu_settings(self):
        """'Menu settings…': the sounds, volume, countdown, default image
        and the selector build path, in a modal.  The button
        beside it already says what they are (:func:`menu_summary`)."""
        if self._menu_dialog is not None:
            return self._menu_dialog
        self._menu_backup = (self._move_var.get(), self._confirm_var.get(),
                             self._volume_var.get(),
                             self._machine_vol_var.get(),
                             self._timeout_var.get(),
                             self._heading_var.get(),
                             self._same_text_var.get(),
                             self._counter_var.get(),
                             self._countdown_word_var.get(),
                             self._footer_var.get(),
                             self._footer_text_var.get(),
                             self._default_var.get(),
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
            (move, confirm, vol, machine, timeout, heading, same_text,
             counter, word, foot_on, foot_text, default, selector, theme,
             colors) = self._menu_backup
            self._menu_backup = None
            self._move_var.set(move)
            self._confirm_var.set(confirm)
            self._volume_var.set(vol)
            self._machine_vol_var.set(machine)
            self._timeout_var.set(timeout)
            self._heading_var.set(heading)
            self._same_text_var.set(same_text)
            self._counter_var.set(counter)
            self._countdown_word_var.set(word)
            self._footer_var.set(foot_on)
            self._footer_text_var.set(foot_text)
            self._default_var.set(default)
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
        self._theme_combo = None
        self._countdown_word_entry = None
        self._countdown_word_lbl = None
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

    def _menu_changed(self):
        self._update_edit_status()
        self._update_menu_summary()
        self._say_countdown_word()
        self._refresh_sound_cells()
        self._push_volume()
        if self._pv_fp is not None:
            self._sound_follow()        # a changed menu sound, heard now

    def _confirm_cell(self, row):
        """The Confirm column: the sound that actually plays when THAT row
        is chosen.  A row with one of its own shows it plainly; a row
        without shows the menu's IN PARENTHESES - the column is worth
        nothing if it does not say what will be heard, and the brackets are
        what tells the two apart at a glance (a Treeview colours a row,
        never one cell of it, so the mark has to be in the text).

        'none' TYPED INTO THE BOX IS THE MENU'S TOO (:func:`inherits_confirm`):
        the format has no per-image silence, so a cell that said 'none' was
        promising a quiet START that the card then answered with the menu's
        sound."""
        own = (row.confirm or "").strip()
        if not inherits_confirm(own):
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
            volume=_int(self._volume_var, self._backend.volume_default),
            machine_volume=bool(self._machine_vol_var.get()),
            compact=bool(self._compact_var.get()),
            timeout=_int(self._timeout_var, 15),
            # NOT `or DEF_HEADING`: an empty box is a menu with no heading,
            # which is a thing somebody can ask for (PAD-135)
            heading=self._heading_var.get().strip(),
            same_text_size=bool(self._same_text_var.get()),
            show_counter=bool(self._counter_var.get()),
            show_footer=bool(self._footer_var.get()),
            # NOT `or` anything: an empty box with the tick on is the
            # selector's own instructions line, which is a real answer
            footer=self._footer_text_var.get().strip(),
            # NOT `or DEF_COUNTDOWN_WORD`: an empty box is a countdown with no
            # word in front of the game's name, which is a thing somebody can
            # ask for (PAD-190, the heading's rule)
            countdown_word=self._countdown_word_var.get().strip(),
            default=_int(self._default_var, 0),
            media_dir=media if (media and os.path.isfile(
                os.path.join(media, "media.json"))) else "",
            selector_dir=self._selector_var.get().strip()
            or self._backend.selector_default,
            platform=self._backend.key,
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
                     "machine_volume": bool(self._machine_vol_var.get()),
                     "compact": bool(self._compact_var.get()),
                     "timeout": _int(self._timeout_var, 15),
                     "heading": self._heading_var.get().strip(),
                     "same_text_size": bool(self._same_text_var.get()),
                     "show_counter": bool(self._counter_var.get()),
                     "show_footer": bool(self._footer_var.get()),
                     "footer": self._footer_text_var.get().strip(),
                     "countdown_word":
                         self._countdown_word_var.get().strip(),
                     "default": _int(self._default_var, 0),
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
        self._card_device = None            # item 99: the card the loaded image was read off
        self._card_device_name = ""
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
            self._volume_var.set(str(min(int(menu["volume"]),
                                         self._backend.volume_max)))
            self._machine_vol_var.set(bool(menu.get("machine_volume", True)))
            self._compact_var.set(bool(menu.get("compact", False)))
            self._timeout_var.set(str(menu["timeout"]))
            self._heading_var.set(menu["heading"])
            # a document written before the tick existed is a menu the
            # selector drew at one size anyway, so it comes back ticked
            self._same_text_var.set(bool(menu.get("same_text_size", True)))
            # ...and so is a document from before the counter tick and the
            # countdown word existed: both come back as the selector's own
            self._counter_var.set(bool(menu.get("show_counter", True)))
            self._countdown_word_var.set(menu.get("countdown_word",
                                                  DEF_COUNTDOWN_WORD))
            self._footer_var.set(bool(menu.get("show_footer", True)))
            self._footer_text_var.set(menu.get("footer", ""))
            self._default_var.set(str(menu["default"]))
            self._theme_var.set(menu["theme"])
            # a built-in comes back as the file spells it today; a custom
            # theme as it was saved, the default under any role it lacks
            self._seed_colors(theme_colors(menu["theme"]) or dict(
                theme_colors(DEFAULT_THEME) or {}, **menu["colors"]))
            sel = str(doc.get("selector_dir") or "").strip()
            self._selector_var.set(sel or DEFAULT_SELECTOR_DIR)
            # NOT RESTORED FROM THE DOCUMENT ANY MORE (2026-09-23). The flag
            # was the preview menu's 'Update the preview automatically'
            # entry, and that menu is gone (David: "we don't need a context
            # menu above the preview at all now") - but a form saved while
            # it was unticked kept `"auto_preview": false`, so the picture
            # never drew itself again and nothing on screen could turn it
            # back on: the tab showed its sketch for good. Only the
            # environment's switch turns it off now - the screenshot rig and
            # the tests set PAD_MULTIBOOT_AUTO=0.
            self._auto_preview.set(
                os.environ.get("PAD_MULTIBOOT_AUTO", "1") != "0")
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
        self._draw_size()               # ...and the strip stops thinking with it
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
        """Something did not work: the app's status line says the first
        reason and how many more, and the Log keeps every word.

        IT IS NOT ON THE TAB'S OWN ROW any more - that row is four checks,
        and a check that cannot work is already red with the reason on it.
        A message repeating that in grey beside it was the duplication
        David hit ("the tooltip and the gray text are duplicated")."""
        self._say(msg)
        for line in msg.splitlines():
            self._write(line)

    def _ok(self, msg, extra=True):
        """The live message: the app's status line, and the Log for the rest.

        ``extra=False`` for a caller that has already written the rest
        itself - a load's warnings, which it echoes with their own tag."""
        self._say(msg)
        if extra:
            for line in (msg or "").splitlines()[1:]:
                if line.strip():
                    self._write(line)

    def _say(self, msg):
        """Remember the live message and put it on the app's status line."""
        self._msg = self._status_line(msg)
        try:
            self._status_fn(self._msg)
        except Exception:                               # noqa: BLE001
            pass                        # the window went; the run has not

    def message(self):
        """The live message as the status line has it - one line, with a
        count of the rest.  The seam the tests read now that the tab has no
        label of its own for it."""
        return self._msg

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    #: How long the image list has to have been still before the size check
    #: runs itself.  Longer than the preview's debounce on purpose: the
    #: picture is what someone is watching while they work, and this is a
    #: second of tool time that must not get in front of it.
    PLAN_DEBOUNCE_MS = 900

    def _plan_key(self):
        """WHAT THE SIZE ANSWER DEPENDS ON, and nothing else: the GAMES the
        card will carry, in order.

        :func:`plan_args` takes the images and the layout and no other
        field of the form, so a title, the countdown, the volume or the
        output path cannot change the answer - which is exactly what makes
        it safe to ask this question on every keystroke.

        THE GAMES, NOT THE ROWS (PAD-189).  A random card is ONE row with no
        path of its own and several member games behind it, so a key built
        out of ``row.path`` carried an empty string for it - and an empty
        string is what :meth:`_plan_now` and :meth:`_size_state` both read as
        "an image that is not on this machine", so adding a random set
        blanked the size and nothing ever measured it again (BEN: "when a
        random set is added, this value disappears... nothing seems to
        trigger it to re-calc").  Its MEMBERS are what the plan reads, so
        they are what this counts, and editing them asks again.

        Whether a group KEEPS its members' own cards belongs here too: a
        keeping one adds no games to the card (its members are games other
        rows already put there) and a consuming one adds all of them, which
        is the whole difference between two sizes off the same paths."""
        return (tuple(q for r in self._rows for q in row_paths(r)),
                self._loaded_card if self._loaded_trees else "",
                bool(self._compact_var.get()),
                tuple((i, bool(r.keep)) for i, r in enumerate(self._rows)
                      if is_group(r)))

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
        self._update_info = None
        self._plan_failed = False
        self._plan_why = ""
        self._size_progress = None
        self._draw_size()               # the stale number goes NOW, not later
        self._cancel_plan()
        if len(key[0]) < 1 or not self._auto_plan:
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
        self._draw_size()               # 'Measuring...' while the tool runs
        # THE ONLY READINESS THIS RUN NEEDS.  Not validate_form: the plan
        # reads the images and nothing else, so a half-typed title or an
        # output path that is still being typed is no reason to leave the
        # size unknown - and a missing .raw is, because the tool would only
        # print a refusal into the Log nobody asked it to.  ``key[0]`` is
        # every GAME the card will carry, a random card's members included
        # (PAD-189), not one path per row.
        if len(key[0]) < 1 or not all(p and os.path.isfile(p) for p in key[0]):
            return False
        form = self.form()
        # ...and, for a loaded card that carries a record, what an update
        # of it would write (item 93): the tool compares every source's
        # stamp with the record and hashes only what moved.
        card = (self._loaded_card
                if self._loaded_trees and self._on_loaded_path() else None)

        def step(label, rc, text):
            # An answer about a list that has since moved is dropped rather
            # than shown: _maybe_plan has already blanked the sentence and
            # armed the next one.
            if key != self._plan_key():
                return
            if label == "plan":
                self._plan_step(label, rc, text)
            elif label == DRY_RUN:
                self._update_step(rc, text)

        def tick(label, _done, _total, frac, what):
            # The tool's own meter (the compact plan hashing an image): the
            # strip shows how far along it is, and the Log never sees it.
            if label != "plan" or key != self._plan_key():
                return
            self._size_progress = (max(0.0, min(1.0, float(frac))), what)
            self._draw_size()

        def done(rc, failed, _texts):
            if self._measuring == key:
                self._measuring = None
                self._size_progress = None
                self._draw_size()       # nothing is thinking any more
            if rc != 0 and failed == "plan":
                # NOT ON THE STATUS LINE.  Nobody asked for this run, so a
                # failure of it must not take the line that is saying what
                # the buttons would do; the whole of the tool's output is in
                # the Log, where the reason is.  (A dry-run's refusal is an
                # answer, kept by _update_step, not a failure.)
                self._write("the size check failed (exit %d) - the sentence "
                            "beside the status line is left blank." % rc)
        # an in-place update exists on the Stern card only (item 118)
        if not self._backend.update:
            card = None
        if not self._run_commands(measure_commands(form, card), on_step=step,
                                  on_done=done, preview=True, on_tick=tick):
            # The worker is busy.  Ask again in a moment rather than queue.
            try:
                self._plan_job = self._timer().after(self.PLAN_RETRY_MS,
                                                     self._plan_now)
            except tk.TclError:                         # pragma: no cover
                self._plan_job = None
            return False
        self._measuring = key
        self._draw_size()               # ...and thinking while it is on the worker
        return True

    #: ...and how long it waits before asking again when the worker was
    #: busy.  A build holds it for minutes; this is a poll, so it is slow.
    PLAN_RETRY_MS = 2000

    def _plan_step(self, label, rc, text):
        if label != "plan":
            return
        if rc == 0:
            self._plan_info = parse_plan(text, **self._pk())
            self._plan_failed = False
            self._plan_why = ""
            self._take_versions(self._plan_info.get("versions") or {})
        else:
            self._plan_info = None
            self._plan_failed = True
            # THE TOOL'S OWN SENTENCE, on the strip.  A size check nobody
            # asked for still must not be a dead end: "see the Log" made a
            # tester open a 2 600-line log to find one line saying the
            # content wants a bigger card (PAD-135).
            self._plan_why = parse_refusal(text)
        # WHAT THE SENTENCE NOW DESCRIBES.  Claimed here rather than when
        # the run was asked for, so the build's own plan step - the same
        # answer, about the same images - keeps the tab from asking twice.
        self._plan_for = self._plan_key()
        self._update_edit_status()          # ...which redraws the size strip

    def _update_step(self, rc, text):
        """What the dry-run said an update of the loaded card would write -
        or why it would not (its refusal is the answer, kept for the
        dialog: 'build a fresh card' has a reason)."""
        if rc == 0:
            self._update_info = parse_update(text)
        else:
            why = parse_refusal(text, self._loaded_card or "")
            self._update_info = {"refused": why or "the tool refused (exit %d)" % rc}
        self._update_edit_status()
        dlg = self._buildflash_dialog
        if dlg is not None:
            dlg.refresh(self._write_plan())

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
                "Building writes a NEW card, and 'Card image' names the "
                "card you loaded (%s). Point it at a different path to build "
                "a copy - typing this one back goes on editing it - or tick "
                "'%s', which rewrites the menu of this one in seconds."
                % (self._loaded_card, APPLY_TICK))
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
        self._plan_info = None
        self._update_edit_status()
        # NO PREPARED SET, BUT THE FORM ASKS FOR MEDIA: the preview never got
        # a media.json written (on a Mac its prepare ran in a container that
        # could not see the pictures), and building without one made a
        # text-only menu nobody asked for (PAD-196).  The build prepares it
        # itself, into the dir the preview would have used.
        if not form.media_dir and form_wants_media(form):
            form.media_dir = self.media_dir()
        # A media set exists: prepare it in full, with THIS form's specs.
        # The preview leaves a sound-less media.json in the same dir, and
        # art changed since the last Prepare would otherwise not be on the
        # card; selectmedia's cache keeps this cheap.
        cmds = build_commands(form, prepare=bool(form.media_dir))
        if form.media_dir:
            self._ok("Preparing the media, then building %s…" % form.out)
        else:
            self._ok("Building %s…" % form.out)

        def done(rc, failed, texts):
            if rc == 0:
                # WHAT WAS BUILT, kept against the path: a build does not put
                # the tab into editing mode, so this is the only way the
                # Ready check can tell a card that still matches the form
                # from one the form has moved on from.
                self._built = (form.out, form)
                self._ok("Card built and verified: %s%s" % (
                    form.out, "" if form.media_dir else
                    " (no prepared media - text-only menu)"))
                if after is not None:
                    after()
            elif self.run_cancelled():
                # The half-written file is NOT left unmentioned: it is the
                # size of a card, it is at the path the box names, and the
                # only thing to do with it is build over it.
                self._ok("Build cancelled at %s. %s is unfinished - it is "
                         "not a card; building again writes over it."
                         % (failed or "the start", form.out))
            else:
                # THE TOOL'S OWN SENTENCE, not the exit code.  Every step of
                # this run says why it will not act ("selector dir ... is
                # not a directory" was the one that sent PAD-105 in), and
                # "see the tool output" made a person read a wall of build
                # log for a line the app had already been handed.
                why = parse_refusal(texts.get(failed, ""), form.out)
                self._error("%s failed (exit %d) - %s"
                            % (failed or "the build", rc,
                               why or "see the tool output."))
        self._run_kind = "build"
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
            "%s already exists%s.\n\nBuilding writes a NEW card over "
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

    def image_titles(self):
        """The card's titles in image order, for the flash dialog's "only image
        N" choice (item 124); blanks where a row has none."""
        return [(getattr(r, "title", "") or "") for r in self._rows]

    def _flash(self, fresh=False):
        # *fresh*: the card was only just built or updated, so no SD card
        # holds it yet and the flash dialog writes it whole (PAD-144).
        out = self._finished_card("flash")
        if out is None:
            return
        if self._flash_fn is None:
            self._error("Flashing is not available from a standalone panel.")
            return
        self._ok("Flashing %s…" % out)
        self._flash_fn(out, fresh=fresh)

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

    def load_card(self, path, asked=True):
        """Read an existing multi-image card into the form: two inspects on
        the worker (the tool's table into the pane, the same read as JSON
        for the fields), the card's media extracted beside it, and then
        :meth:`load_inspect`.  False when the tab refused to start.

        *asked* is False for the ONE read nobody asked for - the restored
        path, read when the tab is first opened (:meth:`on_shown`).  A
        refusal of that one is not an error: the path is where a card WILL
        be written as often as it is a card to read, and half a build, a
        stock image or a card made without a selector are all ordinary
        things to find there.  It is said once, in the ordinary colour, and
        the row's own sentence carries it from then on - instead of a red
        line on every launch about a card the person has not built yet
        (David: "why is the red text there?")."""
        path = (path or "").strip().strip('"')
        if not os.path.isfile(path):
            self._error("No such card image: %s" % path)
            return False
        if under_library(path):
            self._error("That card is in the library (%s); copy it out "
                        "first - updating a loaded card writes into the very "
                        "card it read." % LIBRARY_PREFIXES[0])
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
        self._run_kind = "load"
        seen = {}

        def step(label, rc, text):
            if label == INSPECT_JSON and rc == 0:
                seen["info"] = parse_inspect(text)

        def done(rc, failed, texts):
            if rc != 0:
                # Nothing was read, so there is no baseline to put a
                # restored form back on top of (PAD-188).
                self._carry_edits = None
                if self.run_cancelled():
                    # A load only READS the card, so there is nothing to
                    # warn about and nothing to clean up but the empty dir
                    # the branch below removes.
                    self._ok("Reading %s was cancelled." % path)
                    return
                why = parse_refusal(texts.get(failed, ""), path) or \
                    "%s failed (exit %d) - see the tool output." % (failed, rc)
                # WHAT THE ROW SAYS FROM NOW ON.  Remembered against the
                # path, so the sentence under the box stops offering to read
                # a file that has just refused to be read.
                self._unreadable = (path, why)
                if asked:
                    self._error("Cannot read %s: %s" % (path, why))
                else:
                    self._ok("%s is not a card this tab can read: %s"
                             % (os.path.basename(path), why))
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
                self._carry_edits = None
                self._error("Cannot read %s: the inspect printed no JSON "
                            "report - see the tool output." % path)
                return
            self.load_inspect(info, path, media)
        return self._run_commands(inspect_commands(path, media, **self._pk()),
                                  on_step=step, on_done=done, quiet=(INSPECT_JSON,))

    def load_inspect(self, info, card, media_dir=None):
        """Fill the whole form from an inspect report and go into EDITING
        mode.  The public seam: the loader above, the tests and the
        screenshot script all come through here, so none of them needs WSL.
        Returns the warnings it put on the tab."""
        card = (card or "").strip().strip('"')
        media_dir = media_dir if media_dir is not None \
            else loaded_media_dir(card)
        form, warnings = form_from_inspect(
            info, card, media_dir, self._selector_var.get().strip(), **self._pk())
        self._rows = list(form.images)
        # What the CARD holds, kept before anything can be put back on top of
        # it (_carry_restored_edits): the headline is about the card that was
        # read, not about what is on the tab when the sentence is written.
        card_images = len(form.images)
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
            self._machine_vol_var.set(bool(form.machine_volume))
            self._compact_var.set(bool(form.compact))
            self._timeout_var.set(str(int(form.timeout)))
            self._heading_var.set(form.heading)
            self._same_text_var.set(bool(form.same_text_size))
            self._counter_var.set(bool(form.show_counter))
            self._countdown_word_var.set(form.countdown_word)
            self._footer_var.set(bool(form.show_footer))
            self._footer_text_var.set(form.footer)
            self._default_var.set(str(int(form.default)))
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
        pend = getattr(self, "_pending_device", None)
        if pend and _norm(pend[0]) == _norm(card):
            self._card_device, self._card_device_name = pend[1], pend[2]
        else:
            self._card_device, self._card_device_name = None, ""
        self._pending_device = None
        self._loaded_trees = trees_from_inspect(info)
        self._update_info = None
        # THE LOUD ONE.  Everything else a load has to say is a note on the
        # status line; images that are not the same game code get their own
        # strip above the picture, because it is the one finding that costs
        # something after the card is in the machine.
        self._show_alarm(info)
        # The baseline is read back through form(), not the form built above:
        # what every diff compares is what the widgets now hold.
        self._loaded_form = self.form()
        # ...and it is the baseline whether or not the person's own form goes
        # back on top of it, which is why this comes straight after (PAD-188).
        carried = self._carry_restored_edits()
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
            os.path.basename(card), card_images,
            "" if card_images == 1 else "s")
        if carried:
            head += (" Your %d unsaved change%s from last time %s still here."
                     % (carried, "" if carried == 1 else "s",
                        "is" if carried == 1 else "are"))
        # Notes, not failures: a card that loads with things worth saying
        # (an image whose .raw is elsewhere, a sound with no provenance) has
        # still loaded, so the line stays the ordinary colour and says them.
        self._ok(head + ("\n" + "\n".join(warnings) if warnings
                         else " Edit the menu, then %s." % APPLY_TICK),
                 extra=False)
        for line in warnings:
            self._write("[load] " + line)
        return warnings

    def _carry_restored_edits(self):
        """Put the form a RESTORE brought back on top of the card that
        restore's own read has just loaded.  The number of changes carried,
        0 for none.

        :meth:`on_shown` reads the restored path so the tab is really as it
        was left - in editing mode, with Apply live instead of a green Build
        aimed at the very card being edited.  It read it with
        ``confirm=False`` on the grounds that "the form came off disk a
        moment ago, so there is nothing to discard", and that is only true
        when the saved form IS what the card holds.  It is not when somebody
        edited a loaded card and quit without rebuilding it: the read then
        replaced their work with the card's own image list, silently, on
        every launch, and the only trace was a sentence saying the card had
        loaded.  A RANDOM CARD added over a built card's games is exactly
        that edit, which is what was reported (BEN, Discord @ben01434,
        PAD-188: "I updated and went to the multiboot screen. The random
        group I had is gone." - his shots are this tab mid-load, with the
        card's six singles back and the random card missing).

        So the read still happens, because it is what earns the baseline and
        editing mode - and then the person's form goes back on top of it as
        the unsaved changes it always was.  That is a state this tab already
        knows how to be in and to describe: it is where anyone editing a
        loaded card sits.

        A SAVED FORM THAT MATCHES THE CARD IS LEFT ALONE.  The card's rows
        carry facts a saved one cannot have (the code version read off each
        image, which media is the card's own), and re-applying an identical
        form would throw those away to change nothing.
        """
        doc = self._carry_edits
        self._carry_edits = None
        if not isinstance(doc, dict) or not self._loaded_card:
            return 0
        # The box may have been retyped while the read was on the worker; a
        # form saved against another card is not an edit of this one.
        if _norm(str(doc.get("card") or "")) != _norm(self._loaded_card):
            return 0
        # Identical is the common case (nothing was touched last session),
        # and the state document is what both sides are written as, so it is
        # what they are compared as.
        here = self.state()
        if (doc.get("images") == here.get("images")
                and doc.get("menu") == here.get("menu")):
            return 0
        try:
            from ..core.admin import resolve_mapped_drive as _rmd
        except ImportError:                             # pragma: no cover
            def _rmd(p):
                return p
        rows = rows_from_state(doc.get("images"), resolve=_rmd)
        if not rows:
            # An empty image list is not an edit worth keeping over a card
            # that has just been read: it is what a half-written state file
            # looks like.
            return 0
        menu = menu_from_state(doc.get("menu"))
        self._rows = rows
        self._loading = True
        try:
            self._move_var.set(menu["move"])
            self._confirm_var.set(menu["confirm"])
            self._volume_var.set(str(min(int(menu["volume"]),
                                         self._backend.volume_max)))
            self._machine_vol_var.set(bool(menu.get("machine_volume", True)))
            self._compact_var.set(bool(menu.get("compact", False)))
            self._timeout_var.set(str(menu["timeout"]))
            self._heading_var.set(menu["heading"])
            self._same_text_var.set(bool(menu.get("same_text_size", True)))
            self._counter_var.set(bool(menu.get("show_counter", True)))
            self._countdown_word_var.set(menu["countdown_word"])
            self._footer_var.set(bool(menu.get("show_footer", True)))
            self._footer_text_var.set(menu.get("footer", ""))
            self._default_var.set(str(menu["default"]))
            self._theme_var.set(menu["theme"])
            self._seed_colors(theme_colors(menu["theme"]) or dict(
                theme_colors(DEFAULT_THEME) or {}, **menu["colors"]))
        finally:
            self._loading = False
        self._sync_theme_states()
        self._set_var(self._hl_var, menu["default"])
        # The frames on the canvas were drawn for the card's own menu, which
        # is not the menu now in the form.
        self._pv_cache.clear()
        self._pv_totals.clear()
        self._pv_shown = None
        self._pv_src = None
        self._pv_ready = None
        menu_diff, rebuild = diff_forms(self._loaded_form, self.form())
        return len(menu_diff) + len(rebuild)

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
            for what, val in media_fields_to_check(row):
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
            if prepare and is_group(row) and group_art_spec(row) not in ("", "none"):
                # A RANDOM CARD'S PICTURE IS DRAWN FROM ITS MEMBERS' LOGOS, so
                # the hazard 'auto' has on an image row it has on every style
                # here: the .raw files have to be on this machine to pull a
                # logo out of.
                for mi, m in enumerate(row.members):
                    mp = (m.path or "").strip().strip('"')
                    if group_media_kind(row) != "picture" and not os.path.isfile(mp):
                        errs.append(
                            "Image %d, game %d: the random card's picture is "
                            "drawn from this game's logo - and %s is not on "
                            "this machine. Point the card at a picture file, "
                            "or make the change where the game is."
                            % (i, mi + 1, mp or "its image"))
            elif prepare and not os.path.isfile((row.path or "").strip()):
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
        if not 0 <= int(form.volume) <= backend_for(form).volume_max:
            errs.append(volume_range_error(form))
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
            self._error("Read a card first - updating in place writes into "
                        "the card the form was read from.")
            return False
        # THE INVARIANT, ENFORCED AND NOT ONLY DRAWN.  The button is already
        # grey when the path box has been typed away from the loaded card,
        # but greying a button is a claim and this is the guarantee behind
        # it: an inject into X while the box says Y is the one way this tab
        # could write to a card nothing on screen names.
        if not self._on_loaded_path():
            self._error(
                "'Card image' no longer names %s, the card this form was "
                "read from, so there is nothing to update. Nothing was "
                "lost: type that path back and '%s' is offered again."
                % (self._loaded_card, APPLY_TICK))
            return False
        if self._busy:
            self._error("A run is already in progress.")
            return False
        form = self.form()
        menu, rebuild = self._loaded_diff(form)
        if rebuild:
            self._error(
                "The image list changed (%s). Updating in place only "
                "rewrites the menu of %s; adding, removing, reordering or "
                "replacing an image means copying the images again - point "
                "'Card image' at a new path (which leaves editing mode) and "
                "build a fresh card with %s."
                % ("; ".join(rebuild), os.path.basename(self._loaded_card),
                   WRITE_BUTTON))
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
        # a card read off the reader holds only its menu here: the bypass
        # would write into games trees the image does not carry
        bypass = self._armed and not self._card_device
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

        def done(rc, failed, texts):
            if rc != 0:
                if self.run_cancelled():
                    self._ok("The update was cancelled at %s. The card's "
                             "menu may be half written - %s again to finish "
                             "it." % (failed or "the start", WRITE_BUTTON))
                else:
                    # The step's own sentence when it gave one (the selector
                    # step always does) - see _build_card's own done.
                    why = parse_refusal(texts.get(failed, ""),
                                        self._loaded_card or "")
                    self._error("Updating the card failed at %s (exit %d) - %s"
                                % (failed or "the start", rc,
                                   why or "see the tool output."))
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
            if self._card_device:
                self._write_menu_to_device(after)       # item 99: onto the card itself
                return
            if after is not None:
                after()
        self._run_kind = "apply"
        return self._run_commands(cmds, on_step=step, on_done=done,
                                  quiet=(INSPECT_JSON,))

    def update_card(self, after=None):
        """The in-place update (item 93): ``update`` writes ONLY what changed
        since the loaded card was written - a changed image's new files, an
        added image, a removed one - and the menu with it, as root through a
        loop mount of the card's partitions; then the inspect that reads
        the card back.  About a minute.  False when the tab refused."""
        if not self._loaded_card:
            self._error("Read a card first - updating in place writes into "
                        "the card the form was read from.")
            return False
        if not self._on_loaded_path():
            self._error(
                "'Card image' no longer names %s, the card this form was "
                "read from, so there is nothing to update. Nothing was "
                "lost: type that path back and '%s' is offered again."
                % (self._loaded_card, APPLY_TICK))
            return False
        if self._busy:
            self._error("A run is already in progress.")
            return False
        form = self.form()
        menu, rebuild = self._loaded_diff(form)
        prepare = media_specs_changed(self._loaded_form, form)
        errs = validate_form(form) + self._apply_blockers(form, prepare)
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
            form = replace(form, media_dir=media)
        expect = (self._update_info or {}).get("bytes")
        cmds = update_commands(form, self._loaded_card, media, prepare=prepare,
                               expect_bytes=expect)
        self._ok("Updating %s%s…" % (self._loaded_card, " (media first)" if prepare else ""))
        name = os.path.basename(self._loaded_card)

        def step(label, rc, text):
            if label == INSPECT_JSON and rc == 0:
                info = parse_inspect(text)
                if isinstance(info, dict):
                    self._loaded_info = info
                    self._loaded_trees = trees_from_inspect(info)
                    _ticked, self._armed = bypass_state(info)

        def done(rc, failed, texts):
            if rc != 0:
                if self.run_cancelled():
                    self._ok("The update was cancelled at %s. %s may be half "
                             "updated - press %s again: it carries on from "
                             "what was already written, and the images that "
                             "were there still boot."
                             % (failed or "the start", name, WRITE_BUTTON))
                else:
                    why = parse_refusal(texts.get(failed or "update", ""),
                                        self._loaded_card)
                    if why and failed == "selector":
                        # THE MENU PROGRAM, NOT THE CARD.  A fresh card
                        # would need the very same one, so this refusal
                        # must not send anybody off to build one.
                        self._error("Cannot update %s: %s" % (name, why))
                    elif why:
                        self._update_info = {"refused": why}
                        self._error("Cannot update %s: %s - point 'Card "
                                    "image' at a new path to build a fresh "
                                    "card." % (name, why))
                    else:
                        self._error("Updating the card failed at %s (exit %d) "
                                    "- see the tool output."
                                    % (failed or "the start", rc))
                self._update_edit_status()
                return
            self._loaded_form = form
            self._update_info = None
            self._plan_for = None                   # measure the card again
            if prepare:
                self._pv_ready = (media_fingerprint(form), media, True)
            cost = (_gbytes(expect) + " written" if expect else "nothing to copy")
            self._ok("Card updated: %s (%s%s)" % (
                self._loaded_card, cost,
                ", menu rewritten" if (menu or rebuild) else ""))
            self._update_edit_status()
            if after is not None:
                after()
        self._run_kind = "update"
        return self._run_commands(cmds, on_step=step, on_done=done,
                                  quiet=(INSPECT_JSON,))

    def _update_edit_status(self):
        """EVERYTHING THE STATUS ROW AND THE SIZE STRIP SAY, re-decided.
        Called after every keystroke.

        There is no consequence LINE any more: what the card path points at,
        what Apply to card would write, and why only a rebuild can, are the
        sentences behind the four checks (:func:`status_checks`), and the
        card's size is the strip under the table (:meth:`_build_size`).
        Both are redrawn from here because this is what runs when the things
        they describe may have moved.

        It also settles whether the path box's <Return> has anything to
        read.  The writing side is one green button (Build / flash card…)
        whose modal decides Apply-vs-Build for itself (:meth:`_write_plan`),
        so this greens or greys nothing - it keeps ``_can_read`` and
        ``_row_kind`` current, and paints the row."""
        if not getattr(self, "_check_lbls", None):
            return
        # FIRST, because it is what decides whether the size on screen is
        # still about this list: asking after the strip had been drawn left
        # the stale number up until something else redrew it.
        self._maybe_plan()
        field = self._out_var.get().strip().strip('"')
        menu, rebuild = [], []
        if self._loaded_card and self._loaded_form is not None:
            menu, rebuild = self._loaded_diff()
        kind, _text, _tone, can_read = card_path_state(
            field, self._facts_now(field), self._rows, self._loaded_card,
            menu, rebuild, **self._pk())
        # (The 'unticking the bypass cannot un-patch a card' note is gone
        # with the bypass tick itself - the bypass is always on now, so it
        # can never be untied.  The Apply-vs-Build decision that used to
        # live here is _write_plan's now, off the same card_path_state.)
        self._draw_size()       # the size the plan found, under the images
        self._draw_checks()     # ...and the four marks above them
        self._can_read = bool(can_read)
        #: What the probe last said about the path, so <Return> can tell
        #: "there is nothing there" from "the answer has not come back".
        self._row_kind = kind
        self._sync_recover_button()

    def recoverable(self):
        """The image indexes 'Recover images…' would write out now."""
        if not self._loaded_card or self._card_device:
            return []
        return recoverable_indexes(self._rows, self._loaded_info)

    def _loaded_diff(self, form=None):
        """``(menu, rebuild)`` between the loaded card and *form* (the live
        form by default) - with 'bypass' among the menu changes while a games
        tree on the loaded card is still armed, or half patched (item 98).
        The bypass is always on, so an unpatched tree IS a change, one Apply
        / Update carries even when no field moved; a card read off the reader
        holds no games trees here, so nothing is pending on it."""
        menu, rebuild = diff_forms(self._loaded_form,
                                   form if form is not None else self.form())
        if self._armed and not self._card_device and "bypass" not in menu:
            menu = list(menu) + ["bypass"]
        return menu, rebuild

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
            menu, rebuild = self._loaded_diff(form)
        # EDITING is decided the SAME WAY the consequence line decides it
        # (card_path_state, off the probe's facts), not by a bare string
        # compare: a junction or case spelling of the loaded card the probe
        # resolved is still that card, and Apply must stay live on it.
        kind, _t, _tone, _cr = card_path_state(
            field, self._facts_now(field), self._rows, self._loaded_card,
            menu, rebuild, **self._pk())
        editing = kind == "loaded"
        have_card = bool(field and os.path.isfile(field))
        if editing and self._card_device and rebuild:
            return {
                "action": "build",
                "can_write": False,
                "default_write": False,
                "have_card": False,
                "out": field,
                "write_label": "Build a fresh card",
                "write_detail": ("The image list changed (%s). This form was read off the "
                                 "card in the reader, which holds only its menu here: Apply "
                                 "can change the menu, and nothing else. To change its "
                                 "images, point 'Card image' at a new path, build a fresh "
                                 "card from the sources and flash it." % "; ".join(rebuild)),
            }
        upd = self._update_info if (editing and not self._card_device) else None
        refused = (upd or {}).get("refused") if upd else None
        stale = [i for i, (n, nbytes, action) in ((upd or {}).get("files") or {}).items()
                 if not refused and (nbytes > 0 or action in ("new", "remove", "rename", "sync"))]
        updatable = editing and self._loaded_trees is not None
        if editing and updatable and refused:
            # THE TOOL WOULD NOT UPDATE THIS CARD IN PLACE, and said why: a
            # parts-layout list change, a primary that is another build, no
            # room, a source not on this machine.  The way on is a fresh card
            # at another path - never a build over the loaded one.
            name = os.path.basename(self._loaded_card)
            return {
                "action": "build",
                "can_write": False,
                "default_write": False,
                "have_card": have_card,
                "out": field,
                "write_label": "Build a fresh card",
                "write_detail": ("%s cannot be updated in place: %s. Point "
                                 "'Card image' at a new path and %s writes a "
                                 "fresh card there (every image copied)."
                                 % (name, refused, WRITE_BUTTON)),
            }
        if editing and updatable and (rebuild or stale):
            # THE IN-PLACE UPDATE (item 93): only what changed since the card
            # was written goes onto it - a changed image's new files, an
            # added image, a removed one's space back - and the menu with it.
            name = os.path.basename(self._loaded_card)
            what = "; ".join(list(rebuild) + [
                "image %d changed on disk" % i for i in stale
                if (upd["files"][i][2] == "sync")])
            if upd and upd.get("bytes") is not None:
                nfiles = sum(n for (n, b, a) in upd["files"].values())
                plural = "" if nfiles == 1 else "s"
                cost = ("%d file%s, %s to write" % (nfiles, plural, _gbytes(upd["bytes"]))
                        if upd["bytes"] else "nothing to copy")
                detail = ("%s: %s - only that goes onto %s, and the menu with "
                          "it (%s); nothing else is copied."
                          % (what or "changed", cost, name,
                             "; ".join(menu) if menu else "no menu change"))
                if upd.get("grow"):
                    detail += (" The card grows by %s to make room."
                               % _gbytes(upd["grow"][1]))
            else:
                detail = ("%s - working out what has to be written into %s…"
                          % (what or "changed", name))
            return {
                "action": "update",
                "can_write": not self._busy,
                "default_write": True,
                "have_card": have_card,
                "out": field,
                "write_label": "Update the loaded card in place",
                "write_detail": detail,
            }
        if editing and rebuild and not updatable:
            # A card written before item 93 carries no record: its image
            # list can only change in a fresh card.  Said here, in the
            # dialog, rather than by a refusal after the press.
            name = os.path.basename(self._loaded_card)
            return {
                "action": "build",
                "can_write": False,
                "default_write": False,
                "have_card": have_card,
                "out": field,
                "write_label": "Build a fresh card",
                "write_detail": ("The image list changed (%s), and %s was "
                                 "written before cards could be updated in "
                                 "place. Point 'Card image' at a new path and "
                                 "%s writes a fresh card there (every image "
                                 "copied)." % ("; ".join(rebuild), name, WRITE_BUTTON)),
            }
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
                          "same menu into %s, AND the boot selector itself, "
                          "which is how a newer selector reaches a card you "
                          "have already built (the images are never "
                          "touched)." % name)
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
        if not do_write:
            if do_flash:
                self._flash()
            return
        action = self._write_plan()["action"]
        # A card just BUILT, or UPDATED (game files rewritten inside it), is
        # on no SD card yet, so it reaches the flash dialog as fresh and is
        # written whole.  An APPLY changes only the menu, which is exactly
        # what that dialog's menu-only write is for.
        after = ((lambda: self._flash(fresh=action != "apply"))
                 if do_flash else None)
        if action == "apply":
            self.apply_to_card(after=after)
        elif action == "update":
            self.update_card(after=after)
        else:
            self._build_card(after=after)

    # ------------------------------------------------------------------
    # the preview
    # ------------------------------------------------------------------

    def pv_status_text(self):
        """The WHOLE of the strip's current line - what :meth:`_pv_say` was
        given, before :meth:`_one_line` cut it to the strip's width.  The
        cut depends on the font and the window, so the tests read THIS and
        not the label (a CI runner's wider font ellipsised sentences the
        desktop showed whole); the label's tooltip carries the same text."""
        return getattr(self, "_pv_full", "")

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
        self._pv_full = text
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
        # The animations keep running through a press - every card's plays
        # all the time, on one clock, as on the machine - so no frame is
        # reset here; the next tick composes them over the new highlight's
        # frame once it is drawn.
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
        # A RANDOM CARD'S SOUNDS ARE ITS OWN ROW's, and a card index is not an
        # image index the moment one exists.
        gi = {ri: g for g, ri, _row, _imgs in form_groups(self.form())}.get(hl)
        sounds = manifest_sounds(manifest, media, hl, group=gi)
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
        # A SOUND THE FORM HAS MOVED AWAY FROM IS NOT THE SOUND TO PLAY.
        # The manifest records what each WAV was rendered FROM; when that
        # is no longer what the form asks for, the file on disk is the OLD
        # choice, and playing it (David: "it doesn't immediately stop or
        # update to the new music selection") describes a card nobody is
        # going to build.  Silence until the new one is rendered - the
        # audio step follows a change by itself (see _auto_render).
        rows = manifest.get("groups") if gi is not None else manifest.get("images")
        rows = rows or []
        key = gi if gi is not None else hl
        entry = rows[key] if 0 <= key < len(rows) and isinstance(rows[key], dict) else {}
        if row is not None and sounds["music"]:
            was = entry.get("music_source")
            if was is not None and was != _media_value(row.music):
                sounds["music"] = ""
        if row is not None and sounds["confirm"] and confirm_spec(row) != "none":
            was = entry.get("confirm_source")
            if was is not None and was != confirm_spec(row):
                sounds["confirm"] = ""
        if sounds["confirm"] and (row is None or confirm_spec(row) == "none"):
            was = manifest.get("sound_confirm_source")
            if was is not None and was != self._menu_confirm():
                sounds["confirm"] = ""
        if sounds["move"]:
            was = manifest.get("sound_move_source")
            now = _media_value(self._move_var.get().strip() or "none")
            if was is not None and was != now:
                sounds["move"] = ""
        return sounds

    def _menu_confirm(self):
        """The menu-wide confirm sound as the form spells it - the value
        :meth:`form` would put in ``sound_confirm``, without building the
        whole form to ask."""
        return _media_value(self._confirm_var.get().strip() or "none")

    #: Which of :meth:`menu_sounds`' three a sound row stands for, by the
    #: label the row carries - the only thing that tells a word like ``auto``
    #: on the Music row from the same word on the Confirm row.
    SOUND_ROW_KEYS = {"Music": "music", "Confirm sound": "confirm",
                      "Move sound": "move"}

    def play_sound_choice(self, what, var, image=None):
        """The ▶ beside a sound row: play what that row names, now.

        C FB, PAD-135: "Could there be an option to preview the audio clip
        selected? I have no idea to hear what these sound like without using
        an external audio player."

        WHAT IT PLAYS IS WHAT THE MENU WOULD PLAY, resolved the same two ways
        the card resolves it.  A row holding a PATH plays that file straight
        off disk - which is the case the ask is about: a clip nobody has heard
        yet and nothing has rendered.  A row holding one of the WORDS (auto,
        synth, menu) has no file of its own until a prepare has made one, so
        the media directory's WAV for THAT row is played instead - the sound
        the card will actually carry.  Either way it goes out through the
        preview's own volume and Mute, so what comes out is what the strip's
        knob says.

        *image* IS THE ROW THE BUTTON BELONGS TO, and Edit image… passes it:
        a word on ONE image's Music or Confirm row resolves to that image's
        own rendered WAV, and the preview's highlight is some other image
        whenever the dialog was opened from a row the picture is not on.
        None (Menu settings…, whose two sounds are the whole menu's) leaves it
        to the highlight, which is what the menu itself would be playing.

        NOTHING HERE RAISES AND NOTHING BLOCKS: the answer - including "there
        is no file to play yet, and why" - is one line in the Log, which is
        where the rest of this tab's answers are.  A modal is up while this
        runs, so a message box on top of it would be a second thing to
        dismiss for something the button did not manage to do.
        """
        value = (var.get() or "").strip().strip('"')
        label = (what or "Sound").strip()
        # AN IMAGE'S CONFIRM ROW HAS NO SILENCE TO PLAY: '', 'menu' and a
        # typed 'none' all mean the menu's sound there (:func:`inherits_
        # confirm`), which is what the line under the box says it will play
        # and what the card does with it - so ▶ must not answer that row
        # with "it is set to none" (BEN, PAD-184).
        if image is not None and label == "Confirm sound" \
                and inherits_confirm(value):
            value = "menu"
        if not value or value.lower() == "none":
            self._write("%s: nothing to play - it is set to none." % label)
            return False
        path, why = self._sound_choice_path(label, value, image)
        if not path:
            self._write("%s: %s" % (label, why))
            return False
        # THE CONTRACT IS CHECKED HERE so the Log can say what is wrong with
        # the file.  play() is fire-and-forget on the player's own worker, and
        # a refusal there would only reach the preview strip - which is behind
        # the dialog the button is in.
        try:
            head = preview_audio.wav_header(path)
            bad = preview_audio.wav_refusal(head)
        except preview_audio.WavRefused as exc:
            self._write("%s: %s" % (label, exc))
            return False
        if bad:
            # NOT A REASON THE CARD WOULD REFUSE IT: the build converts the
            # file when it renders the card's media, so this says what will
            # happen rather than what is broken.
            self._write("%s: %s cannot be played here - %s. The build "
                        "converts it to 44100 Hz 16-bit; this preview plays "
                        "files as they are."
                        % (label, os.path.basename(path), bad))
            return False
        audio = self._audio_player()
        audio.set_volume(self._effective_volume())
        audio.play(path)
        self._write("%s: playing %s (%.2f s)%s"
                    % (label, os.path.basename(path), head["seconds"],
                       " - Mute is on, so nothing will be heard"
                       if self._pv_mute_var.get() else ""))
        return True

    def _sound_choice_path(self, label, value, image=None):
        """``(path, why)`` for one sound row: the WAV to play, or '' and the
        sentence saying why there is none yet."""
        if is_file_choice(value):
            if not os.path.isfile(value):
                return "", "%s was not found." % value
            return value, ""
        # A WORD, so the file it stands for is whatever the last prepare wrote
        # for THIS row.  menu_sounds resolves an image's own confirm and the
        # menu-wide fallback exactly as the selector does, and gives "" for a
        # sound this media set has not got.
        media = self.media_dir()
        if not media or not os.path.isfile(os.path.join(media, "media.json")):
            return "", ("%s is rendered when the card's media is prepared. "
                        "Tick Sound beside the preview, or pick a WAV here, "
                        "and %s plays it." % (value, PLAY_NAME))
        key = self.SOUND_ROW_KEYS.get(label)
        sounds = self.menu_sounds(highlight=image) if key else {}
        path = (sounds or {}).get(key) or ""
        if not path or not os.path.isfile(path):
            return "", ("%s has nothing rendered for it yet. Tick Sound "
                        "beside the preview and it is made." % value)
        return path, ""

    def _audio_player(self):
        """The preview's player, made on the FIRST sound and not before.

        preview_audio imports neither sounddevice nor numpy and opens no
        device until it is asked to play something, and this tab does not
        ask until someone has ticked Sound - so a session that never wants
        sound never touches an audio device at all."""
        if self._audio is None:
            self._audio = PreviewAudio(volume=self._effective_volume())
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
        if self._pv_ready == (mfp, media, True):
            return False                  # the whole set is there already
        try:
            self._makedirs(media)
        except OSError as exc:
            self._pv_say("Cannot create %s: %s" % (media, exc), error=True)
            return False

        def step(label, rc, _text):
            if label == AUDIO_LABEL and rc == 0:
                self._pv_visual = (mfp, media)
                self._pv_ready = (mfp, media, True)

        def done(rc, _failed, texts):
            if rc == 0:
                # SAID ON THE AUDIO READOUT, not the caption: the caption
                # is describing the frame that is up and playing.
                self._media_say("audio", self._audio_state())
                self._sound_follow()
                self._say_sound(None)   # ...so the next miss is said again
                self._write("[preview] the menu's sounds are ready")
            else:
                # NOT a failure of the preview: the picture is up and
                # playing.  The strip's Audio readout carries the reason
                # (the tool's own refusal line when it gave one - a cold
                # Extract-time cache is the usual one).  parse_refusal has
                # already taken the prefix off, whichever of the two the
                # tool used.
                why = parse_refusal(texts.get(AUDIO_LABEL, ""))
                self._media_say("audio", "unavailable - %s"
                                % (why or "exit %d, see the Log" % rc))
                self._write("[preview] the menu's sounds could not be "
                            "rendered (exit %d) - see the lines above" % rc)
        if not self._run_commands(audio_prepare_commands(form, media),
                                  on_step=step, on_done=done, preview=True):
            return False
        self._media_say("audio", "loading…")
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
        _UNSET = object()

        def gone(asked, name, was=_UNSET, now=None):
            """Whether a sound the form asks for is not ready: not asked for
            is never missing; asked but no file (or no manifest) is; and a
            file that IS there but was rendered from a DIFFERENT source than
            the form now asks for is STALE, which counts as missing (David:
            "i changed the move sound, but it's not playing... had to press
            redraw").  A manifest too old to record the source (``was`` is
            None) cannot be judged stale - the file's presence stands."""
            if not asked:
                return False
            if not (media and name):
                return True
            if not os.path.isfile(os.path.join(media, name)):
                return True
            if was is not _UNSET and was is not None and was != now:
                return True
            return False

        missing = []
        move_now = _media_value(self._move_var.get().strip() or "none")
        if gone(move_now != "none", manifest.get("sound_move"),
                manifest.get("sound_move_source"), move_now):
            missing.append("the move sound")
        confirm_now = _media_value(self._confirm_var.get().strip() or "none")
        if gone(self._menu_confirm() != "none", manifest.get("sound_confirm"),
                manifest.get("sound_confirm_source"), confirm_now):
            missing.append("the confirm sound")
        # A ROW IS A CARD, and the manifest has two kinds of row: one per GAME
        # and one per RANDOM CARD.  Reading the games' rows at a card's number
        # said a random card's music was never rendered, for ever (David,
        # 2026-09-11: the strip reading "not rendered (image 3's music)").
        imgs = manifest.get("images") or []
        grps = manifest.get("groups") or []
        first = {}
        for img, _p, ri, _mi in form_trees(self.form()):
            first.setdefault(ri, img)
        gi_of = {ri: g for g, ri, _row, _imgs in form_groups(self.form())}
        for i, row in enumerate(self._rows):
            if i in gi_of:
                rows, key = grps, gi_of[i]
                what = "the random card's"
            else:
                rows, key = imgs, first.get(i, i)
                # The images are numbered the way the picture numbers them,
                # from one, because this is said to a person (see _image_label).
                what = "image %d's" % (i + 1)
            entry = rows[key] if 0 <= key < len(rows) and isinstance(rows[key], dict) \
                else {}
            music_now = _media_value(row.music)
            if gone(music_now not in ("", "none"), entry.get("music"),
                    entry.get("music_source"), music_now):
                missing.append("%s music" % what)
            confirm_now = confirm_spec(row)
            if gone(confirm_now != "none", entry.get("confirm"),
                    entry.get("confirm_source"), confirm_now):
                missing.append("%s confirm sound" % what)
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
        if not self._sound_var.get() or self._pv_hidden:
            return False
        music = self.menu_sounds()["music"]
        if not music and self._audio is None:
            return False                # nothing to play: open nothing
        audio = self._audio_player()
        audio.set_volume(self._effective_volume())
        audio.loop(music or None)
        return True

    def _effective_volume(self):
        """What the player is told: the menu's volume (0-100, the machine's
        own loudness, media.json's number) scaled by the preview's knob,
        and 0 while Mute is ticked."""
        if self._pv_mute_var.get():
            return 0
        try:
            gain = max(0.0, min(1.0, float(self._pv_gain_var.get()) / 100.0))
        except (tk.TclError, ValueError):
            gain = 1.0
        return int(round(_int(self._volume_var, 50) * gain))

    def _on_preview_volume(self, *_args):
        """The knob moved (a Scale drag calls back per tick with the value;
        the Mute tick with nothing): remember it, and reach the sound that
        is playing now."""
        try:
            gain = max(0.0, min(1.0, float(self._pv_gain_var.get()) / 100.0))
        except (tk.TclError, ValueError):
            gain = 1.0
        write_preview_ctl(gain, bool(self._pv_mute_var.get()))
        self._push_volume()

    def _on_shown(self, _event=None):
        """The tab (or the window) is back on screen: what the menu plays
        plays again, and the clips tick again."""
        self._pv_hidden = False
        if self._stopped:
            return
        self._sound_follow()
        self._play_start()

    def _on_hidden(self, _event=None):
        """The tab went behind another, or the window was minimised:
        silence, and the device given back.  The clips' clock keeps
        running, so they come back where the machine's would be."""
        self._pv_hidden = True
        self._stop_sound()

    def _sound_click(self):
        """The move sound a flipper press makes, over the music - what the
        machine does on every EV_LEFT / EV_RIGHT.

        A media set prepared by the PREVIEW has no move sound in it (a
        ``--visual-only`` prepare renders the pictures and the music and
        skips the two menu sounds), so this is the one place that has to say
        'there is no click to play, and here is how to get one'."""
        if not self._sound_var.get() or self._pv_hidden:
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
        """START, on the picture: the chosen card's confirm sound, and the
        LOADING frame the machine draws while it plays.

        THE LOADING FRAME IS WHERE A RANDOM CARD SAYS WHAT IT ROLLED - the one
        moment the player is told which build they got (David, 2026-09-11: "I
        want to see this especially for how it looks with the random one") - so
        the preview shows the real one the selector drew.  A black beat stood in
        for it before, and still does when there is no frame to show: an older
        selector, or a render that has not finished."""
        self.play_confirm()
        # A RANDOM CARD ROLLS AGAIN ON EVERY PRESS, and showing the frame the
        # LAST roll drew while this one is rendering put two different builds on
        # screen in quick succession (David, 2026-09-11).  So the beat stays
        # black for a random card until its own roll lands - which is what the
        # machine shows in that moment anyway - and an ordinary card, whose
        # frame cannot change, is drawn at once.
        rolling = self._roll_loading()
        if not rolling:
            self._blackout(self._loading_frame())
        else:
            self._blackout()
        return True

    def _roll_loading(self):
        """Ask the selector for the LOADING frame again, so a random card rolls
        again - and show it when it lands.

        It is one snapshot out of a load that is already cheap (the same step
        the preview runs on a keystroke), and only on a deliberate press.  It
        asks for nothing when there is no pipeline yet, when the card on screen
        is not a random one (an ordinary card's frame cannot change), or when
        the worker is busy: the beat then holds whatever the last render drew,
        which is what it always showed."""
        if not self._pv_bin or not self._pv_fp or self._stopped:
            return False
        form = self.form()
        hl = _int(self._hl_var, 0)
        if not (0 <= hl < len(form.images) and is_group(form.images[hl])):
            return False
        pv = preview_dir_for(form.out)
        conf = os.path.join(pv, "images.conf")
        if not pv or not os.path.isfile(conf):
            return False
        path = loading_path(pv, self._pv_fp, hl)
        ppm = os.path.join(pv, "roll_%d.ppm" % hl)
        cmds = snapshot_commands(self._pv_bin, conf, self.media_dir(), ppm,
                                 preview_highlight(form, hl), 0,
                                 rootfs_for(form.selector_dir),
                                 loading=path,
                                 roll_state=self._roll_state_path(),
                                 **self._pk())

        def done(rc, failed, texts):
            img = rolled_image(texts.get(cmds[0][0], "")) if rc == 0 else None
            if img is not None:
                # SAY WHICH ONE, where a person can see it: the two builds of a
                # jukebox share a title, so the frame alone can leave you
                # guessing whether it rolled at all.
                self._pv_say("The random card rolled %s."
                             % game_name(form, img))
            if rc == 0 and os.path.isfile(path) and not self._stopped:
                # THE DECODED FRAME IS CACHED BY PATH, and the reroll writes the
                # same path: without this the file changed and the picture did
                # not, so ten presses showed one roll ten times (David,
                # 2026-09-11: "i just pressed the random button 10 times in a
                # row and each time the result was the same").
                self._drop_photo(path)
                self._blackout(path)        # the new roll, and a fresh beat

        return bool(self._run_commands(cmds, on_done=done, preview=True,
                                       quiet=[c[0] for c in cmds]))

    def _roll_state_path(self):
        """The preview's OWN copy of the roll's memory - what was booted last
        and what each shuffle has dealt.

        The machine keeps this on the card, beside its last choice; the preview
        keeps one in its own directory, so pressing Select walks the same deck
        the machine would without ever reading or writing the machine's."""
        pv = preview_dir_for(self.form().out)
        return os.path.join(pv, "roll.state") if pv else ""

    def _loading_frame(self, card=None):
        """The LOADING frame for the card on screen, or None.

        KEYED ON THE CARD THAT IS HIGHLIGHTED NOW, not on the last render: a
        redraw happens only when something changed, so the render's own answer
        is the last card that needed drawing - which is how pressing Select on
        an ordinary image showed the random card's loading frame (David,
        2026-09-11).  One file per (form, card), so the right one is on disk
        whenever that card has been drawn under this form."""
        fp = self._pv_fp
        pv = preview_dir_for(self.form().out) if fp else ""
        if not pv:
            return None
        hl = _int(self._hl_var, 0) if card is None else int(card)
        path = loading_path(pv, fp, hl)
        return path if os.path.isfile(path) else None

    def _blackout(self, still=None):
        """Hold *still* (the LOADING frame) for :data:`LOADING_MS`, or black
        when there is none, then put the frame back.

        The picture on screen is not thrown away - it is re-shown from the
        file it was drawn from - so this costs no render and cannot leave
        the preview empty if the tab is torn down mid-beat."""
        canvas = getattr(self, "_pv_canvas", None)
        if canvas is None:                              # pragma: no cover
            return False
        self._cancel_blackout()
        self._black_still = still or None
        try:
            canvas.delete("all")
        except tk.TclError:                             # pragma: no cover
            return False
        if still:
            # drawn WITHOUT touching _pv_src: the beat ends by putting back
            # whatever was on screen, which is the menu frame
            photo = self._scaled_photo(still)
            if photo is not None:
                self._pv_photo = photo
                try:
                    canvas.create_image(self._pv_w // 2 + 1, self._pv_h // 2 + 1,
                                        image=photo, anchor=tk.CENTER)
                except tk.TclError:                     # pragma: no cover
                    pass
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
        audio.set_volume(self._effective_volume())
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
            self._audio.set_volume(self._effective_volume())

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
        # FRAME 0, always: the selector draws the menu as it first appears
        # and every clip is laid over that by the ticks (the frame counter
        # is the playing clip's readout, not a request)
        return preview_fingerprint(form), hl, 0

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
        if self._pv_base is not None and self._pv_base[0][0] == key:
            self._pv_base = None
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
        self._pv_base = None

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
        self._composite = None
        if highlight is not None:
            self._set_var(self._hl_var, highlight)
        self._set_var(self._frame_var, frame)
        if total is not None:
            key = self._current_key()
            if key is not None:
                self._pv_totals[key[:2]] = total
        # NO CAPTION.  The strip used to name the card and count the frame
        # ("Image 1: frame 139 of 150, 1 other clip playing"), which was
        # developer telemetry from when a frame was something you asked for
        # one at a time; now that every card animates all the time it is a
        # number changing thirty times a second under a picture that is
        # already showing you what it says (David: "this feedback here for
        # image playing is super distracting and unnecessary. remove it").
        #
        # The strip is still the preview's status line - a render that
        # FAILED, a form that has changed under the picture, a cache miss,
        # and the sound note below all still land here.  Writing the empty
        # caption is what CLEARS one of those when the picture comes good.
        self._pv_say("", note=self._sound_suffix())
        return True

    def _redraw_shown(self):
        """The box changed size: draw the frame that is up again at the new
        scale (or the placeholder, when nothing has been rendered yet).  A
        Play composite goes back to its rendered frame; the next tick lays
        the clip over it again at the new size."""
        if self._composite:
            base, hl, total = self._composite
            if os.path.isfile(base):
                self.load_frame(base, hl, 0, total)
                return
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
        if self._play_var.get() and preview_fingerprint(form) != self._play_fp:
            # THE CLIPS ARE PLAYING over the frame that is up, and the FORM
            # moved under them: stop them here - this IS the redraw
            # _form_moved_under_play would have to ask for - and the render
            # that lands starts them again.  UNDER the drive guard above,
            # because form() is the first stat.  A HIGHLIGHT change is not
            # this (the fingerprint has no highlight in it): it falls
            # through to the cache check below, which draws that card's
            # frame if it is not there yet - the ticks idle until it lands.
            # (An early return here on an unchanged fingerprint is what
            # froze the preview on the first card, David 2026-09-03.)
            self._stop_play("The form changed - redrawing…", error=False)
        out = (form.out or "").strip().strip('"')
        if len(form.images) < 1 or not out:
            return False
        # A render writes its conf and its frames under <out dir>/preview.
        # Half a path, typed on the way to a real one, must not leave a
        # trail of directories behind it: an output only draws by itself
        # once it names a card image in a folder that exists (or one folder
        # below one that does - <out dir> is where the card goes anyway).
        # Anything else waits for Render now, which creates what it needs.
        # THE PLATFORM SAYS WHAT AN OUTPUT ENDS IN: a Stern card is a .raw,
        # a JJP multi-boot install is an .iso - hard-coding the first here
        # left the JJP tab saying "not a .raw" about the ISO it had just
        # loaded, and never drawing it (David, 2026-09-13).
        be = self._backend
        out_dir = os.path.dirname(os.path.abspath(out))
        if not (out.lower().endswith(be.image_exts)
                and (os.path.isdir(out_dir)
                     or os.path.isdir(os.path.dirname(out_dir)))):
            self._pv_stale("the %s path is not a %s in a folder that "
                           "exists yet" % (be.out_noun, be.out_ext))
            return False
        # NOT RED, BUT NOT SILENT EITHER.  An unfinished form is the normal
        # state while someone is typing, so this must not paint the status
        # block red on every keystroke - but the debounce has already
        # waited for the typing to STOP, and a preview that quietly stops
        # following the form from then on is the worst of both.  So the
        # picture's own caption says it is out of date, and why.
        prepare = self.needs_prepare(form)
        errs = validate_form(form, sources=prepare)
        # THE PICTURE DOES NOT NEED THE MEDIA'S SOURCES.  A card someone
        # else built records the videos and WAVs its media was made from on
        # their disk, and 'art file not found' was stopping the whole menu
        # from being drawn - while nothing has to be rendered again, the
        # card's own files are what is drawn; and the two sounds' sources
        # are never needed for a --visual-only render.
        skip = sound_file_errors(errs) if prepare else media_file_errors(errs)
        errs = [e for e in errs if e not in skip]
        if errs:
            self._pv_stale(errs[0], len(errs) - 1)
            return False
        hl = _int(self._hl_var, int(form.default))
        if not 0 <= hl < len(form.images):
            self._pv_stale("the image to highlight must be one of 0..%d"
                           % (len(form.images) - 1))
            return False
        n = 0                           # see _current_key
        key = (preview_fingerprint(form), hl, n)
        if key in self._pv_cache:
            if not self._on_screen(key):
                self.load_frame(self._pv_cache[key], hl, n,
                                self._pv_totals.get(key[:2]))
            # THE SOUNDS CAN MOVE WITHOUT THE PICTURE.  A music or confirm
            # change is not in the picture's fingerprint (nothing on the
            # frame changes), so it never reached a render - and the
            # render was the only thing that asked for the audio half
            # (David: "when I changed the confirm sound, it is not
            # regenerating the preview").  Ask for it here, on its own.
            if self._pv_visual is not None and self._sounds_missing():
                self._prepare_sounds()
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
        return self._render_frames(form, hl, [0])

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
        self._pv_fp, self._pv_media, self._play_fp = fp, media, fp
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
            cmds += ensure_selector_commands(
                form, card=selector_card(form, self._loaded_card))
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
        # THE VIDEO HALF FIRST, and only that: the frame needs the pictures
        # and nothing else, so the sounds (the slow half, pulled off the
        # card) are rendered in a run of their own AFTER the picture is up
        # (see done() below), and the strip says which is loading.
        if self._pv_visual != (mfp, media) and self._pv_ready != (mfp, media, True):
            if self.needs_prepare(form):
                cmds += preview_prepare_commands(form, media)
            else:
                # The card's own media, straight out of the extraction: it
                # matches the form because the form came out of the card,
                # sounds and all.
                self._pv_visual = (mfp, media)
                self._pv_ready = (mfp, media, True)
        wanted = [int(n) for n in frames] or [0]
        # A run of more than one is ONE step, and never longer than the most
        # an animation can hold: past that the selector refuses the whole
        # command (exit 2) rather than trimming, and a refusal draws nothing.
        run = min(len(wanted), PREVIEW_MAX_FRAMES) if len(wanted) > 1 else 1
        first = wanted[0]
        ppm = (frame_pattern(pv, fp, hl) if run > 1
               else frame_path(pv, fp, hl, first))
        # THE LOADING FRAME IS REMEMBERED, not derived again later: it is the
        # file THIS render asked the selector for, and what the Select button
        # shows.  Deriving it from the form afterwards means guessing which
        # highlight the render used, and the answer is here.
        self._pv_load_frame = loading_path(pv, fp, hl)

        def argv(texts):
            binary = parse_selector_path(texts.get("selector", "")) \
                or self._pv_bin
            if not binary:
                raise RuntimeError("the selector step named no binary")
            # hl is a table ROW, and a row IS a card (see preview_highlight),
            # which is what the cache key above keeps too.
            return snapshot_commands(binary, conf, media, ppm,
                                     preview_highlight(form, hl), first,
                                     rootfs, frames=run,
                                     loading=loading_path(pv, fp, hl),
                                     **self._pk())[0][1]
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
            elif label == VIDEO_LABEL:
                self._pv_visual = (mfp, media)
            elif label == ANIM_LABEL:
                # WHICH frames a run wrote is the selector's decision, and
                # it says so once per file: the caller knows the pattern,
                # the selector knows what it filled into it.  Only the
                # NUMBER is taken from it - see keep().
                for _echoed, n, total in parse_snapshot_frames(text):
                    keep(n, total)
                self._keep_rect(fp, hl, text)
            elif label.startswith("frame "):
                total = parse_anim_frames(text, hl)
                keep(first, total)
                self._keep_rect(fp, hl, text)
                key = self._current_key()
                # shown the moment it lands (the clips are laid over it
                # by the next tick), and the caption names it
                if key == (fp, hl, first):
                    self.load_frame(ppm, hl, first, total or 1)

        def done(rc, failed, _texts):
            if rc == 0:
                key = self._current_key()
                if key in self._pv_cache and not self._on_screen(key):
                    self.load_frame(self._pv_cache[key], key[1], key[2],
                                    self._pv_totals.get(key[:2]))
                self._media_say("video", self._video_state(form))
                # A prepare may just have put this image's music there.
                self._sound_follow()
                # ...and the clips play over the frame from here on.
                self._play_start()
                # THE AUDIO HALF, now that the picture is up: the move and
                # confirm sounds are a run of their own, said as such.
                if not self._prepare_sounds():
                    self._media_say("audio", self._audio_state())
                return
            # ANY failed step forgets the prepared media, a frame render
            # included: a snapshot that failed on broken media would
            # otherwise keep failing, because the next render would skip
            # prepare and hand the selector the same broken files. Preparing
            # again costs almost nothing - selectmedia's sidecar cache reuses
            # every unchanged picture (measured 0.13 s for a two-image set).
            self._pv_ready = None
            self._pv_visual = None
            self._stop_play(None)
            self._media_say("video", "failed - see the Log")
            self._pv_say("Preview failed at %s (exit %d) - see the tool "
                         "output." % (failed or "the start", rc), error=True)

        self._media_say("video", "loading…")
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

    def _keep_rect(self, fp, hl, text):
        """Remember where a run put every visible animated card's picture
        (its snapshot line's ``pictures``) - an empty dict when nothing on
        that frame animates."""
        self._pv_rects[(fp, hl)] = parse_snapshot_pictures(text)

    def _media_say(self, kind, state):
        """The strip's Video / Audio readout: what the preview has of each
        half right now - loading, ready, none, or why not (David: "indicate
        when the videos / audio are loading separately for the preview")."""
        self._media_state[kind] = state
        lbl = getattr(self, "_%s_lbl" % kind, None)
        if lbl is None:
            return
        try:
            lbl.configure(text="%s: %s" % (kind.capitalize(), state)
                          if state else "")
        except tk.TclError:                             # pragma: no cover
            pass

    def _video_state(self, form=None):
        """What Video says once the frame is drawn: how many clips play, or
        that nothing on this menu animates."""
        form = form or self.form()
        n = sum(1 for r in form.images if anim_spec(r) != "none")
        if not n:
            return "none"
        return "ready (%d clip%s)" % (n, "" if n == 1 else "s")

    def _audio_state(self):
        """What Audio says when no run is up: ready, none asked for, or
        which sounds are still not rendered."""
        missing = self._sounds_missing()
        if missing:
            return "not rendered (%s)" % ", ".join(missing)
        wants = (_media_value(self._move_var.get().strip() or "none") != "none"
                 or self._menu_confirm() != "none"
                 or any(_media_value(r.music) not in ("", "none")
                        or confirm_spec(r) != "none" for r in self._rows))
        return "ready" if wants else "none"

    def _play_toggled(self):
        """The tests' seam: ``_play_var`` on starts the ticks, off stops
        them.  Nothing on the strip sets it any more - the clips play
        whenever the preview has a frame."""
        if self._play_var.get():
            self._play_start()
        else:
            self._stop_play(None)

    #: How often the ticks look again while there is nothing to draw - no
    #: frame yet, nothing animates, a Select's black beat, or nobody is
    #: looking at the tab.
    PLAY_IDLE_MS = 250

    def _anim_delay_ms(self, hl):
        """The rendered clip's own mean per-frame delay for image *hl*, or
        None - read off ``anim<N>.gif`` in the media directory (the file
        the selector decodes), kept against its stat."""
        media = self._pv_media or self.media_dir()
        if not media:
            return None
        names = card_media_names(self.form())
        name = names[hl][1] if 0 <= hl < len(names) else ""
        if not name:
            return None
        path = os.path.join(media, name)
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
        """How long one frame stays up, on average: THE RENDERED CLIP'S
        OWN RATE (the GIF's mean delay, see :func:`anim_period_ms`), the
        contract's 30 fps until the GIF is there.  The tick itself uses the
        clip's per-frame delay (a 30 fps GIF alternates 30 and 40 ms);
        this is the one answer for a caller that wants a number."""
        if not 0 <= hl < len(self._rows):
            return self.PLAY_MS
        return anim_period_ms(self._rows[hl],
                              delay_ms=self._anim_delay_ms(hl))

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
        """Stop the ticks (a redraw is on its way, or the tab is going);
        the clips' clock keeps running, so they resume where the
        machine's would be."""
        self._play_var.set(False)
        self._play_frames = None
        if self._play_job is not None:
            try:
                self._timer().after_cancel(self._play_job)
            except (tk.TclError, ValueError):
                pass
            self._play_job = None
        if msg:
            self._pv_say(msg, error=error)
        elif self._composite:
            # The clip was up: back to the RENDERED frame it was laid over
            # (frame 0), so what is on screen is a frame the selector drew
            # and the caption says which one instead of going on claiming
            # to be playing.
            base, hl, total = self._composite
            self.load_frame(base, hl, 0, total)
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
            # ...every one but the green one, which becomes the run's Cancel
            # rather than going grey with the rest (see _sync_build_button).
            if btn is None or btn is getattr(self, "_buildflash_btn", None):
                continue
            try:
                btn.configure(state=tk.DISABLED if busy else tk.NORMAL)
            except tk.TclError:
                pass
        self._sync_build_button()
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
            self._run_kind = ""
            # THE RUN MAY HAVE MOVED THE DISK UNDER THE ROW.  A build writes
            # the card the row was calling missing, an apply changes it, a
            # load that failed may have taken a directory away - and the row
            # reads a CACHED stat, so without this it went on describing the
            # state before the run for ever.  The same goes for "that file
            # is not a multi-boot card": a build at that path has just made
            # it one.  (A load's own refusal is recorded in its ``on_done``,
            # which runs after this - see _start_worker's finish.)
            self._unreadable = None
            self._refresh_facts()
        # ...and Apply to card is only ever live for a loaded card whose
        # image list still matches it.
        self._update_edit_status()

    #: What each tool step means on the tab's OWN stage row (Media, Copy,
    #: Inject, Verify - MainWindow.MULTIBOOT_PHASES).  Both writing buttons
    #: read honestly on it: Build & verify walks all four, Apply to card
    #: only the last two (plus Media when a media field moved).
    PHASE_OF = {"selector": 0, "prepare": 0, "plan": 0, DRY_RUN: 0,
                "build": 1, "update": 1, "extract": 1,
                "inject": 2, "bypass": 2, "verify": 3, "inspect": 3,
                INSPECT_JSON: 3}

    #: ...and what the footer's status line says while it is there.
    PHASE_STATUS = {
        "selector": "Checking the menu program…",
        "prepare": "Rendering the menu's media…",
        "plan": "Planning the card's layout…",
        "build": "Copying the images into the card…",
        "update": "Writing what changed into the card…",
        "extract": "Copying the card's images out…",
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
        # The stage the progress lines that follow belong to, and a clean
        # slate for the estimate: the rate of the step that just ended says
        # nothing about the one starting (a debugfs extraction and a raw
        # copy are an order of magnitude apart).
        self._phase_index = index
        self._prog_hist = []
        try:
            self._phase_fn(index, status=self.PHASE_STATUS.get(label))
        except Exception:                               # noqa: BLE001
            pass                        # the window went; the run has not

    #: How long a window of samples the estimate is made from.  Long enough
    #: that a chunk boundary does not swing it, short enough that it follows
    #: a real change of stage within a few lines.
    PROGRESS_WINDOW_S = 45.0

    def _progress_tick(self, done, total, frac, what):
        """One line of the build's own work meter: move the bar, and say how
        far along it is and how long is left.

        THE ESTIMATE COMES FROM THE RECENT RATE and nothing else - no stage
        weights, no remembered speed from the last build.  The bytes are the
        tool's; the clock is ours, because the tool's own line is a snapshot
        and the interval between two of them is what a rate is."""
        now = self._prog_clock()
        hist = self._prog_hist
        hist.append((now, done))
        while len(hist) > 2 and now - hist[0][0] > self.PROGRESS_WINDOW_S:
            del hist[0]
        eta = ""
        if len(hist) >= 2:
            span, moved = now - hist[0][0], done - hist[0][1]
            if span > 0 and moved > 0:
                eta = eta_text((total - done) / (moved / span))
        pct = "%d%%" % int(frac * 100)
        line = " - ".join(p for p in (pct, what, eta) if p)
        try:
            # A FRACTIONAL STAGE INDEX: the chips still light one stage at a
            # time, and the bar moves inside it.  See
            # MainWindow.set_multiboot_phase, which is where the two are told
            # apart - a signature with a 'fraction' argument would have had
            # to be threaded through every stub that stands in for it.
            self._phase_fn(self._phase_index + min(1.0, max(0.0, frac)),
                           status=line)
        except Exception:                               # noqa: BLE001
            pass
        self._say(line)

    def _phase_cancelled(self):
        try:
            self._phase_fn(None, status="Cancelled")
        except Exception:                               # noqa: BLE001
            pass

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
                      preview=False, on_tick=None):
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

        A run that writes drives the footer's meter with the tool's progress
        lines.  A ``preview`` run has no footer; with ``on_tick(label, done,
        total, fraction, what)`` its progress lines go there instead (the
        size strip, for the compact plan's hashing), and without it they are
        ordinary output.
        """
        # macOS runs its steps in a container, so one has to be up and able
        # to see this run's ISOs before the first step starts.  Only for a
        # WRITING run: the preview redraws on every keystroke and must not
        # build an image or start a container behind one: it either finds a
        # container already up (a build earlier in the session) or its step
        # fails and says so, once.
        if not preview and _mac.enabled():
            try:
                _mac.ensure_container(self._run_paths(), rig_repo_dir(),
                                      log=self._append)
            except Exception as exc:                    # noqa: BLE001
                self._error(str(exc))
                return False
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
            self._cancelled = self._cancel_pending = False
            self._set_busy(True)
            if self._pv_busy:
                self._pv_cancel = True
                self._pending_run = (cmds, on_step, on_done, frozenset(quiet))
                self._drain()       # the render's finish starts it
                return True
        self._start_worker(cmds, on_step, on_done, frozenset(quiet), preview,
                           on_tick)
        return True

    def _start_worker(self, cmds, on_step, on_done, quiet, preview, on_tick=None):
        """The worker itself - see :meth:`_run_commands`, which owns the
        guards.  Split out so a queued action can be started from the
        render's own finish without going through them again."""
        def run():
            rc = 0
            failed = None
            texts = {}
            for label, argv in cmds:
                if not preview and self._cancelled:
                    # Cancel was pressed between two steps: stop here rather
                    # than start the next tool.
                    break
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
                self._proc, self._proc_preview = proc, preview
                lines = []
                echo = label not in quiet
                try:
                    for raw in proc.stdout:
                        line = raw.decode("utf-8", "replace").rstrip()
                        tick = parse_progress(line)
                        if tick is not None and not preview:
                            # The work meter: it drives the bar and stops
                            # there.  One line a second for an hour is not a
                            # record of anything, and putting it in the Log
                            # would bury the lines that are.
                            self._ui(lambda t=tick: self._progress_tick(*t))
                            continue
                        if tick is not None and on_tick is not None:
                            # A background run's meter (the size check's
                            # compact plan hashing an image) goes to whoever
                            # asked for it - the size strip - and nowhere else.
                            self._ui(lambda lab=label, t=tick: on_tick(lab, *t))
                            continue
                        lines.append(line)
                        if echo:
                            self._append(line)
                except Exception:                       # noqa: BLE001
                    pass                                # pipe closed under us
                rc = proc.wait()
                self._proc = None
                if not preview and self._cancelled:
                    # The kill IS the non-zero exit; the run stops here and
                    # the finish below says cancelled, not failed.
                    texts[label] = "\n".join(lines)
                    failed = label
                    break
                texts[label] = "\n".join(lines)
                if not echo and rc != 0:
                    for line in lines:                  # it failed: say why
                        self._append(line)
                self._append("%s: exit %d" % (label, rc))
                if rc != 0:
                    self._say_once(sudo_password_note(texts[label]))
                    self._say_once(container_note(texts[label]))
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
                    cancelled = self._cancelled
                    self._cancel_pending = False
                    self._set_busy(False)
                    if cancelled:
                        self._phase_cancelled()
                    else:
                        self._phase_done(rc, failed)
                if on_done is not None:
                    on_done(rc, failed, texts)
                if not preview:
                    # Held until HERE so the handler above could see it.
                    self._cancelled = False
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

    def _run_paths(self):
        """Every host path a run reads or writes, for the container's bind
        mounts.  Over-listing is cheap (a mount it never touches costs
        nothing); under-listing is a tool that cannot see its own ISO."""
        paths = []
        try:
            form = self.form()
        except Exception:                               # noqa: BLE001
            return paths
        for row in (form.images or []):
            paths += [p for p in row_paths(row) if p]
        # ...and the pictures, clips and sounds the prepare reads (PAD-196)
        paths += media_source_paths(form)
        for p in (form.out, form.selector_dir):
            if p:
                paths.append(p.strip().strip('"'))
        try:
            md = self.media_dir()
        except Exception:                               # noqa: BLE001
            md = ""
        if md:
            paths.append(md)
        return paths

    def _append(self, line):
        """A tool line, from the worker.  Queued for the main loop, because
        that is where the app's Log lives."""
        self._ui(lambda: self._write(line))

    def _say_once(self, note):
        """Append *note* the first time it comes up, and never again.

        For the sentences that EXPLAIN a refusal rather than report it
        (:func:`sudo_password_note`).  The preview redraws on every
        keystroke, so a note appended per failure would replace the
        reporter's wall of "sudo: a password is required" with a wall of
        three-sentence paragraphs - louder than the thing it explains
        (PAD-192).  Empty notes say nothing, and a DIFFERENT refusal still
        gets its own sentence.
        """
        if not note:
            return False
        said = getattr(self, "_notes_said", None)
        if said is None:
            said = self._notes_said = set()
        if note in said:
            return False
        said.add(note)
        self._append(note)
        return True

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
