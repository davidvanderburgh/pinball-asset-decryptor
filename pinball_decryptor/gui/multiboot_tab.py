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

THE PREVIEW.  'Render preview' shows the boot menu as the machine will draw
it: the selector itself is built from this checkout (``make`` into a scratch
dir, never installed - the tab's 'Selector build' path is the fallback when
the cross compiler is missing), the media is prepared ``--visual-only`` into
the SAME ``<out dir>/media`` the build uses (selectmedia's sidecar cache
keeps the art and GIFs between the two, so a preview after a text change
costs nothing and the card carries exactly what was previewed), an
``images.conf`` for the picture is written under ``<out dir>/preview``, and
one ``qemu-arm-static -L <rootfs> codeselect --snapshot`` run per frame
writes a P6 PPM that Tk loads natively.  'Play' steps the highlighted card's
animation, rendering frames as it goes and keeping them per (form, highlight,
frame) until the form changes.  Because a preview leaves a sound-less
media.json behind, 'Build & verify' runs a full prepare into that dir first
whenever a media set exists - the card is never built from the preview's
half of the media.

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
import tkinter as tk
from dataclasses import dataclass, field, replace
from tkinter import filedialog, messagebox, ttk

from . import _rig
from .emulate_tab import rig_dir
from .theme import THEMES, platform_font
from .widgets import _Tooltip

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

#: The non-file choices each media field accepts.  Anything else is a path.
ART_CHOICES = ("auto", "none", "video frame")
ANIM_CHOICES = ("none", "auto")
MUSIC_CHOICES = ("none",)
SOUND_CHOICES = ("auto", "synth", "none")
_WORDS = frozenset(("auto", "none", "synth", "video frame"))

#: A picture taken from a video: ``--art N=<video>@<seconds>``.
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi")

#: selectmedia.py's own clip defaults (its --start / --seconds / --fps).  A
#: blank field in the editor means "the tool's default"; when any of the
#: three is given all three are spelled out, explicit rather than defaulted.
ANIM_DEFAULTS = ("0", "3", "10")

#: The selector's frame, and the box the preview shows it in (an integer
#: subsample of 2 - Tk PhotoImage has no other scaling).
FRAME_W, FRAME_H = 1360, 768
PREVIEW_W, PREVIEW_H = 680, 384
PREVIEW_FPS = 8

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
    art_video: str = ""      # 'video frame': the clip the picture comes from
    art_time: str = ""       # ...and the second it is taken at (blank = 0)
    anim_start: str = ""     # seconds into the clip (blank = the tool's default)
    anim_seconds: str = ""   # the clip's length
    anim_fps: str = ""


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


def preview_dir_for(out):
    """Where the preview's conf and frames go: ``<out dir>/preview``."""
    out = (out or "").strip()
    return os.path.join(os.path.dirname(os.path.abspath(out)), "preview") \
        if out else ""


def frame_path(preview_dir, highlight, frame):
    """The PPM one snapshot writes: ``frame_<highlight>_<frame>.ppm``."""
    return os.path.join(preview_dir, "frame_%d_%d.ppm" % (highlight, frame))


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


def fit_factors(w, h, box_w=PREVIEW_W, box_h=PREVIEW_H):
    """``(subsample, zoom)`` - the integer factors (Tk PhotoImage's only
    scaling) that fit a *w* x *h* frame into the box: 1360x768 -> (2, 1) =
    680x384; a small test frame is zoomed up instead."""
    if w <= 0 or h <= 0:
        return 1, 1
    if w <= box_w and h <= box_h:
        return 1, max(1, min(box_w // w, box_h // h))
    return max(-(-w // box_w), -(-h // box_h)), 1


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

    #: Play's frame period (~8 fps).
    PLAY_MS = 1000 // PREVIEW_FPS

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
        self._ed_art_video = tk.StringVar()
        self._ed_art_time = tk.StringVar()
        self._ed_anim_start = tk.StringVar()
        self._ed_anim_seconds = tk.StringVar()
        self._ed_anim_fps = tk.StringVar()
        for var in (self._ed_title, self._ed_sub, self._ed_art,
                    self._ed_anim, self._ed_music, self._ed_art_video,
                    self._ed_art_time, self._ed_anim_start,
                    self._ed_anim_seconds, self._ed_anim_fps):
            var.trace_add("write", lambda *_a: self._editor_changed())
        # The preview.  Frames are cached per (form fingerprint, highlight,
        # frame index) -> PPM path; the frame counts per (fingerprint,
        # highlight), learned from the selector's own log line.
        self._hl_var = tk.StringVar(value="0")
        self._frame_var = tk.StringVar(value="0")
        self._play_var = tk.BooleanVar(value=False)
        self._pv_cache = {}
        self._pv_totals = {}
        self._pv_bin = ""               # the selector the last run named
        self._pv_ready = None           # fingerprint whose media is prepared
        self._pv_photo = None           # PhotoImage ref (must stay alive)
        self._pv_shown = None           # (highlight, frame) on the canvas
        self._pv_loading = False        # a programmatic spinbox write
        self._hl_touched = False        # Highlight typed by hand: stop following Default
        self._play_job = None
        self._play_fp = None
        self._play_hl = 0
        self._default_var.trace_add("write", lambda *_a: self._follow_default())
        self._hl_var.trace_add("write", lambda *_a: self._hl_changed(typed=True))
        self._frame_var.trace_add("write",
                                  lambda *_a: self._frame_changed(typed=True))

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
        for attr in ("_drain_job", "_play_job"):
            job = getattr(self, attr)
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
        self._build_preview(frame, pad)
        self._build_log(frame, pad)
        frame.bind("<Destroy>", self._on_destroy, add="+")
        self._set_busy(False)
        self._sync_editor_states()

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
                ("art", "Art", 110, False), ("anim", "Animation", 150, False),
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
        text = ttk.Frame(ed)
        text.pack(fill=tk.X)
        ttk.Label(text, text="Title:", width=13).grid(row=0, column=0,
                                                      sticky=tk.W, pady=2)
        self._ed_title_entry = ttk.Entry(text, textvariable=self._ed_title,
                                         width=30)
        self._ed_title_entry.grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(text, text="Subtitle:").grid(row=0, column=2, sticky=tk.W,
                                               padx=(12, 4), pady=2)
        ttk.Entry(text, textvariable=self._ed_sub, width=44).grid(
            row=0, column=3, sticky=tk.EW, pady=2)
        text.columnconfigure(3, weight=1)
        # Two independent stacks under the text: the picture on the left,
        # the clip on the right.  Each grids its own columns, so the video
        # frame's time field and the clip's three numbers widen nothing
        # but their own stack.
        stacks = ttk.Frame(ed)
        stacks.pack(fill=tk.X)
        left = ttk.Frame(stacks)
        left.pack(side=tk.LEFT, anchor=tk.N)
        right = ttk.Frame(stacks)
        right.pack(side=tk.LEFT, anchor=tk.N, padx=(24, 0))
        self._media_row(left, 0, 0, "Art:", self._ed_art, ART_CHOICES,
                        [("Pictures", "*.png *.jpg *.jpeg"),
                         ("Videos", "*.mp4 *.mov *.mkv *.avi")])
        # 13, not 12: "Video frame:" is twelve characters and a 12-wide ttk
        # label clips the colon (the tab's first screenshot lost "Move
        # soun" the same way at 10).
        ttk.Label(left, text="Video frame:", width=13).grid(
            row=1, column=0, sticky=tk.W, pady=2)
        self._video_entry = ttk.Entry(left, textvariable=self._ed_art_video,
                                      width=27)
        self._video_entry.grid(row=1, column=1, sticky=tk.W, pady=2)
        self._video_btn = ttk.Button(
            left, text="Browse…", width=9,
            command=lambda: self._browse_media(
                self._ed_art_video, [("Videos", "*.mp4 *.mov *.mkv *.avi")]))
        self._video_btn.grid(row=1, column=2, sticky=tk.W, padx=(4, 0), pady=2)
        vt = ttk.Frame(left)
        vt.grid(row=1, column=3, sticky=tk.W, padx=(8, 0), pady=2)
        ttk.Label(vt, text="at (s):").pack(side=tk.LEFT)
        self._video_time = ttk.Spinbox(vt, from_=0, to=36000, increment=0.5,
                                       width=6, textvariable=self._ed_art_time)
        self._video_time.pack(side=tk.LEFT, padx=(4, 0))
        self._media_row(left, 2, 0, "Music:", self._ed_music, MUSIC_CHOICES,
                        [("WAV audio", "*.wav")])
        self._media_row(right, 0, 0, "Animation:", self._ed_anim,
                        ANIM_CHOICES,
                        [("Animations", "*.gif *.mp4 *.mov *.mkv *.avi")])
        ttk.Label(right, text="Clip:").grid(row=1, column=0, sticky=tk.W,
                                            pady=2)
        clip = ttk.Frame(right)
        clip.grid(row=1, column=1, columnspan=3, sticky=tk.W, pady=2)
        self._clip_widgets = []
        for label, var, width in (("Start (s):", self._ed_anim_start, 6),
                                  ("Length (s):", self._ed_anim_seconds, 5),
                                  ("FPS:", self._ed_anim_fps, 4)):
            ttk.Label(clip, text=label).pack(side=tk.LEFT,
                                             padx=(0 if not self._clip_widgets
                                                   else 10, 4))
            sp = ttk.Spinbox(clip, from_=0, to=36000, width=width,
                             textvariable=var)
            sp.pack(side=tk.LEFT)
            self._clip_widgets.append(sp)
        ttk.Label(right, foreground="#888", wraplength=560, justify=tk.LEFT,
                  text="auto = the image's own logo / attract clip; none = "
                       "text only. Clip fields left blank = the tool's "
                       "defaults (from 0 s, 3 s long, 10 fps)").grid(
            row=2, column=0, columnspan=4, sticky=tk.W, pady=2)

    def _media_row(self, parent, row, col, label, var, choices, filetypes):
        """Label + editable combobox (the words, or a typed path) + Browse."""
        # 13, not 10: "Move sound:" is eleven characters and a 10-wide ttk
        # label showed "Move soun" (the first screenshot of the tab).
        kw = {"width": 13} if col == 0 else {}
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
        ttk.Label(g, text="Volume:", width=13).grid(row=2, column=0,
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
        ttk.Label(g, text="Default:", width=13).grid(row=3, column=0,
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

    def _build_preview(self, frame, pad):
        box = ttk.LabelFrame(frame, text="Preview - the boot menu as the "
                                         "machine will draw it")
        box.pack(fill=tk.X, **pad)
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        inner = ttk.Frame(box)
        inner.pack(fill=tk.X, padx=8, pady=6)
        self._pv_canvas = tk.Canvas(
            inner, width=PREVIEW_W, height=PREVIEW_H, bg="#0b0e14",
            highlightthickness=1, highlightbackground=th["border"])
        self._pv_canvas.pack(side=tk.LEFT)
        self._pv_placeholder()
        side = ttk.Frame(inner)
        side.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
        self._render_btn = ttk.Button(side, text="Render preview", width=16,
                                      command=self.render_preview)
        self._render_btn.grid(row=0, column=0, columnspan=2, sticky=tk.W,
                              pady=(0, 8))
        ttk.Label(side, text="Highlight:").grid(row=1, column=0, sticky=tk.W,
                                                pady=2)
        hl = ttk.Frame(side)
        hl.grid(row=1, column=1, sticky=tk.W, pady=2)
        self._hl_spin = ttk.Spinbox(hl, from_=0, to=0, width=5,
                                    textvariable=self._hl_var,
                                    command=self._hl_changed)
        self._hl_spin.pack(side=tk.LEFT)
        ttk.Label(hl, text="image index (follows Default until typed)",
                  foreground="#888").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(side, text="Animation frame:").grid(row=2, column=0,
                                                      sticky=tk.W, pady=2)
        fr = ttk.Frame(side)
        fr.grid(row=2, column=1, sticky=tk.W, pady=2)
        self._frame_spin = ttk.Spinbox(fr, from_=0, to=999, width=5,
                                       textvariable=self._frame_var,
                                       command=self._frame_changed)
        self._frame_spin.pack(side=tk.LEFT)
        self._play_chk = ttk.Checkbutton(fr, text="Play",
                                         variable=self._play_var,
                                         command=self._play_toggled)
        self._play_chk.pack(side=tk.LEFT, padx=(10, 0))
        self._pv_status = ttk.Label(side, text="", wraplength=380,
                                    justify=tk.LEFT)
        self._pv_status.grid(row=3, column=0, columnspan=2, sticky=tk.W,
                             pady=(8, 0))
        ttk.Label(side, foreground="#888", wraplength=380, justify=tk.LEFT,
                  text=("Drawn by the selector itself (built from this "
                        "checkout, run under qemu against the card rootfs) "
                        "from the form above: the same titles, art and "
                        "animation the card will carry, the countdown as "
                        "if the menu had just appeared. Play steps the "
                        "highlighted card's animation - frames are rendered "
                        "as it goes and kept until the form changes. The "
                        "media it prepares is the build's, so the card "
                        "matches the picture.")).grid(
            row=4, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))

    def _build_log(self, frame, pad):
        box = ttk.LabelFrame(frame, text="Tool output")
        box.pack(fill=tk.BOTH, expand=True, **pad)
        th = THEMES.get(self._theme_fn()) or THEMES["dark"]
        _sans, mono = platform_font()
        inner = ttk.Frame(box)
        inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self._log_text = tk.Text(
            inner, height=8, wrap=tk.NONE, state=tk.DISABLED,
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

    @staticmethod
    def _cell_art(row):
        """The Art column: the word, a picture's name, or ``<video> @3s``."""
        v = (row.art or "").strip()
        if v.lower() == "video frame":
            name = os.path.basename((row.art_video or "").strip()) or "video?"
            return "%s @%ss" % (name, _num(row.art_time, "0"))
        if is_video(v):
            return "%s @%ss" % (os.path.basename(v), _num(row.art_time, "0"))
        return MultibootPanel._cell(v)

    @staticmethod
    def _cell_anim(row):
        """The Animation column: the word or the clip's name, and the clip
        parameters when any is set (``auto @20s 2s 8fps``)."""
        v = MultibootPanel._cell(row.anim)
        if v and v.lower() != "none":
            start, secs, fps = (_num(row.anim_start), _num(row.anim_seconds),
                                _num(row.anim_fps))
            if start or secs or fps:
                v += " @%ss %ss %sfps" % (start or ANIM_DEFAULTS[0],
                                          secs or ANIM_DEFAULTS[1],
                                          fps or ANIM_DEFAULTS[2])
        return v

    def _values(self, i, row):
        return (i, row.path, row.title, row.subtitle, self._cell_art(row),
                self._cell_anim(row), self._cell(row.music))

    def _refresh_tree(self, select=None):
        try:
            for item in self._tree.get_children():
                self._tree.delete(item)
            for i, row in enumerate(self._rows):
                self._tree.insert("", tk.END, iid=str(i),
                                  values=self._values(i, row))
            if select is not None and 0 <= select < len(self._rows):
                self._tree.selection_set(str(select))
                self._tree.focus(str(select))
            top = max(0, len(self._rows) - 1)
            self._default_spin.configure(to=top)
            self._hl_spin.configure(to=top)
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
        row.title = self._ed_title.get()
        row.subtitle = self._ed_sub.get()
        row.art = self._ed_art.get()
        row.anim = self._ed_anim.get()
        row.music = self._ed_music.get()
        row.art_video = self._ed_art_video.get()
        row.art_time = self._ed_art_time.get()
        row.anim_start = self._ed_anim_start.get()
        row.anim_seconds = self._ed_anim_seconds.get()
        row.anim_fps = self._ed_anim_fps.get()
        try:
            self._tree.item(str(i), values=self._values(i, row))
        except tk.TclError:
            pass

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
    # the preview
    # ------------------------------------------------------------------

    def _pv_placeholder(self):
        c = self._pv_canvas
        try:
            c.delete("all")
            c.create_text(PREVIEW_W // 2, PREVIEW_H // 2, fill="#667",
                          font=("", 11), justify=tk.CENTER,
                          text="Render preview draws the boot menu here\n"
                               "(1360x768 shown at half size)")
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
            self._log_sink("[multiboot] preview: " + msg)

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
        """A spinbox moved: show that frame if it is already rendered."""
        key = self._current_key()
        if key is None:
            return
        path = self._pv_cache.get(key)
        if path and self._pv_shown != key[1:]:
            self.load_frame(path, key[1], key[2],
                            self._pv_totals.get(key[:2]))

    def _highlight(self, form):
        """The Highlight spinbox as an index into the form, or None (said)."""
        hl = _int(self._hl_var, int(form.default))
        if not 0 <= hl < len(form.images):
            self._pv_say("Highlight must be one of 0..%d."
                         % (len(form.images) - 1), error=True)
            return None
        return hl

    def load_frame(self, path, highlight=None, frame=0, total=None):
        """Show one rendered frame: a P6 PPM (Tk reads those natively),
        subsampled to fit the box.  ``total`` = the animation's frame count
        when known.  The public seam: the pipeline, the screenshot script
        and the tests all come through here.  False (and the status says
        why) when Tk cannot read the file."""
        try:
            photo = tk.PhotoImage(file=path)
        except tk.TclError as exc:
            self._pv_say("Cannot load %s: %s" % (path, exc), error=True)
            return False
        sub, zoom = fit_factors(photo.width(), photo.height())
        if sub > 1:
            photo = photo.subsample(sub, sub)
        if zoom > 1:
            photo = photo.zoom(zoom, zoom)
        self._pv_photo = photo
        c = self._pv_canvas
        try:
            c.delete("all")
            c.create_image(PREVIEW_W // 2 + 1, PREVIEW_H // 2 + 1,
                           image=photo, anchor=tk.CENTER)
        except tk.TclError:
            return False
        self._pv_shown = (highlight, frame)
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
        self._pv_say("Highlight %s: %s" % (
            "?" if highlight is None else highlight, what))
        return True

    def render_preview(self):
        """The Render preview button: the frame the spinboxes point at."""
        form = self._validated_form()
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
        worker: ensure a selector, prepare the media (both skipped while
        the form's fingerprint is the one already prepared), then one
        snapshot per frame.  Each finished frame lands in the cache; the
        one the spinboxes point at is shown at once (Play shows its own
        from the tick).  False when the busy guard refused."""
        fp = preview_fingerprint(form)
        pv = preview_dir_for(form.out)
        media = media_dir_for(form.out)
        conf = os.path.join(pv, "images.conf")
        try:
            os.makedirs(pv, exist_ok=True)
            os.makedirs(media, exist_ok=True)
            with open(conf, "w", encoding="utf-8", newline="\n") as f:
                f.write(write_preview_conf(form))
        except OSError as exc:
            self._pv_say("Cannot write the preview files: %s" % exc,
                         error=True)
            return False
        rootfs = rootfs_for(form.selector_dir)
        cmds = []
        fresh = self._pv_ready != fp or not self._pv_bin
        if fresh:
            cmds += ensure_selector_commands(form)
            cmds += preview_prepare_commands(form, media)
        paths = {}
        for n in frames:
            ppm = frame_path(pv, hl, n)
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
            elif label == "prepare":
                self._pv_ready = fp
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
        if not self._run_commands(cmds, on_step=step, on_done=done):
            self._pv_say("A run is already in progress - wait for it.",
                         error=True)
            return False
        return True

    def _play_toggled(self):
        if not self._play_var.get():
            self._stop_play(None)
            return
        form = self.form()
        errs = validate_form(form)
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
        elif not self._busy:
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
        self._busy = busy
        for btn in list(getattr(self, "_action_btns", ())) + [
                getattr(self, "_render_btn", None)]:
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

    def _run_commands(self, cmds, on_step=None, on_done=None):
        """Run ``[(label, argv), ...]`` in order on a worker, streaming every
        line into the pane; stop at the first failure.  An *argv* may be a
        callable ``fn(texts)`` - evaluated on the worker just before its
        turn, from what the earlier steps printed (the preview's snapshot
        needs the binary the selector step named).  ``on_step(label, rc,
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
                if callable(argv):
                    try:
                        argv = argv(texts)
                    except Exception as exc:                # noqa: BLE001
                        self._append("[multiboot] %s: %s" % (label, exc))
                        rc, failed = 1, label
                        break
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
