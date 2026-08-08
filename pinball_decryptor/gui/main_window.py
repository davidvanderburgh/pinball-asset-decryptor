"""Main window for the unified Pinball Asset Decryptor.

Shape:
  [ Manufacturer ▾ ]                                     [ ☀/☽ ]
  Tabs: Extract | Write | Mod Pack   (tabs gated by capabilities)
  Phase indicators
  Progress bar
  Status row
  Log
"""

import base64
import os
import re
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core.checksums import TRACKING_SIDECARS
from ..core.config import EXTRACT_PHASES, WRITE_PHASES
from ..core.extract_source import (dismiss_stale_source, stale_dismissed,
                                   stale_source_message)
from ..core.staged_originals import ORIG_DIR
from ..core import desktop, session_log
from .theme import (THEMES, dark_titlebar, detect_system_theme,
                    platform_font)

# PIL lazy-imported on demand for the live DMD preview — keeping the
# import here so a missing Pillow doesn't break the rest of the GUI.
try:
    from PIL import Image, ImageTk
    _HAVE_PIL = True
except ImportError:
    _HAVE_PIL = False

_SANS_FONT, _MONO_FONT = platform_font()

# _Tooltip used to live here; moved to gui/widgets.py so picker.py can
# also use it without importing main_window (circular).
from . import placement  # noqa: E402
from .widgets import (_Tooltip, center_over, draw_folder_icon,  # noqa: E402
                      flat_button)


# Hover-tooltip text for the generic per-type Extract checkboxes
# (capabilities.extract_categories — currently Stern Spike 2's Audio / Video /
# Images / Text).  Keyed by category key; an unknown key falls back to a
# generic "Include <label> when extracting." string.
_EXTRACT_CATEGORY_TIPS = {
    "audio": "Decode every packed sound to an individual WAV.",
    "video": "Pull out the game's video clips (H.264 .mov).",
    "images": "Export the loose image / texture assets (PNG / DDS).",
    "text": "Export the on-screen display-text strings for editing.",
}

# "Voice recognition quality" choices in the ⚙ settings menu: the
# faster-whisper model Auto-name call-outs transcribes with.  (value, label);
# first entry is the default.  Bigger models transcribe noticeably better but
# run several times slower and download a bigger one-time model.
VOICE_QUALITY_CHOICES = (
    ("tiny.en", "Standard — fastest (~75 MB model)"),
    ("small.en", "High — better accuracy, ~4× slower (~500 MB model)"),
    ("medium.en", "Highest — best accuracy, ~10× slower (~1.5 GB model)"),
)

# Replace-Image "Group by scene" parent-row iid prefix.  Image-row iids are
# the slot rel_path (relative, so it can never start with a colon); this
# prefix guarantees a group header's iid can't collide with any slot.
_IMG_GROUP_IID = "::grp::"

# Partition Explorer: suffix marking a directory node's lazy-load placeholder
# child (a NUL can't appear in a real POSIX path, so it never collides).
_PEX_PLACEHOLDER = "\x00__lazy__"

# Partition Explorer preview: the file types worth drawing rather than dumping
# as bytes, and how much of one we'll pull off the card to do it.  A card's UI
# art is a few hundred KB to a couple of MB; the cap is what keeps a click on a
# multi-gigabyte video from reading it into RAM to "preview" it.
_PEX_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tga", ".webp")
_PEX_FONT_EXTS = (".ttf", ".otf")
_PEX_RENDER_CAP = 12 << 20


class _PexCancelled(Exception):
    """Partition Explorer extract cancelled — raised inside the worker's
    progress callbacks so the ext4 walk unwinds at its next tick."""

# Replace-Audio "Group duplicates" parent-row iid prefix — same collision
# guarantee as _IMG_GROUP_IID (slot iids are relative paths, never ::-led).
_AUD_DUP_GROUP_IID = "::dupgrp::"

# Fully-transparent 16×16 RGBA PNG — the "Blank all images" group action
# assigns it to every slot in a scene so the whole element renders as nothing;
# Write's normal staging rescales/re-encodes it per slot like any replacement.
_BLANK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAEklEQVR42mNgGAWjYBSM"
    "AggAAAQQAAGvRYgsAAAAAElFTkSuQmCC")


def _pil_tk_hint():
    """What to tell the user when Pillow can't hand an image to Tk.

    The advice has to split on frozen: "install python3-pil.imagetk" is
    right for a source checkout and useless inside an AppImage or .app,
    where there is no site-packages to install into and the missing
    piece is something the BUILD dropped (--collect-all PIL, see
    installer/build_linux.sh).  A tester got the apt advice from an AppImage
    and it could not have helped him.
    """
    if getattr(sys, "frozen", False):
        return ("(This build is missing part of Pillow's Tk support — "
                "please report it; updating to the next release should "
                "fix it.)")
    return ("(Pillow's Tk support may be missing — on Linux install "
            "python3-pil.imagetk)")


def _update_action_verb(installer):
    """Label for the banner/gear in-app update button.

    Windows genuinely installs (silent setup exe over the top); Linux
    downloads an AppImage and offers to start it, installing nothing —
    promising an install there would be a lie about where the user's
    files end up.
    """
    if (installer or {}).get("kind") == "appimage":
        return "Download update"
    return "Install update"


def _render_pinmame_frame(data, w, h, depth, scale, color):
    """Render a libpinmame RAW DMD frame to an amber-tinted PIL image.

    PinMAME RAW mode hands one byte per pixel where each byte holds a
    brightness value in 0..(2**depth - 1).  We:

      1. Build a per-level RGB LUT (so we don't pay the multiply per
         pixel — there are only ``levels`` distinct shades).
      2. Map the raw bytes through the LUT in one pass into an RGB
         buffer.
      3. ``Image.frombytes`` + ``resize(NEAREST)`` to scale up.
    """
    if not _HAVE_PIL:
        return None
    levels = max(1, (1 << depth) - 1)
    r, g, b = color
    # 256-entry LUT — covers any byte value we might see, clamped to
    # the depth's brightness range.
    lut = bytearray(256 * 3)
    for i in range(256):
        lv = min(i, levels)
        ratio = lv / levels
        lut[3 * i + 0] = int(r * ratio)
        lut[3 * i + 1] = int(g * ratio)
        lut[3 * i + 2] = int(b * ratio)
    n = w * h
    src = data[:n]
    rgb = bytearray(n * 3)
    j = 0
    for px in src:
        k = 3 * px
        rgb[j] = lut[k]
        rgb[j + 1] = lut[k + 1]
        rgb[j + 2] = lut[k + 2]
        j += 3
    img = Image.frombytes("RGB", (w, h), bytes(rgb))
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    return img


class _AudioPreviewPane:
    """One self-contained audio preview player: a seekable spectrogram strip
    with its own play/stop transport.  The Replace Audio tab shows two of
    these side by side — Original and Replacement — so a slot and its
    assigned track can be compared directly, replacing the old single player
    with a Source A/B switch (David).  Starting one pane pauses its sibling
    so the two streams never play over each other.

    *win* is the MainWindow (theme, Tk root, shared icon drawing);
    *on_activate* is called when ▶ is pressed with nothing loaded yet (the
    window loads the selected row's files, then autoplays this pane)."""

    def __init__(self, win, parent, title, on_activate=None):
        self._win = win
        self._on_activate = on_activate
        # Called with this pane when a clip finishes ON ITS OWN.  Deliberately
        # NOT called by stop_playback: a user pressing ■, switching tabs or
        # loading another slot is not the track ending, and auditioning a whole
        # card would otherwise run away from whoever tried to stop it.
        self.on_finished = None
        self.sibling = None       # the other pane; paused when this one plays
        self.path = None          # file currently loaded in the strip
        self.dur = 0.0            # its duration (s)
        # Effective stop point (s) when Write will trim this file to its slot
        # length — None when the whole file plays (originals are always None).
        self.limit = None
        self.pos = 0.0            # playhead position (s)
        self.playing = False
        self._start_pos = 0.0     # ffplay -ss offset in flight
        self._start_t = 0.0       # monotonic clock at playback start
        self._proc = None         # ffplay handle, if any
        # True while the running player caps its own playback (ffplay, via
        # -autoexit / -t).  The OS-native fallback can't, so only that case
        # gets the wall-clock kill in _tick — see start_playback.
        self._self_capping = False
        self._tick_job = None     # after() id for the position timer
        self._render_id = 0       # bump to drop stale async renders
        self._spec_img = None     # PhotoImage ref (must stay alive)
        self._hint = ""           # message shown when nothing is loaded

        self.frame = ttk.Frame(parent)
        # Title carries the loaded file's name ("Original — idx0258.wav") so
        # the user always knows exactly what the player is holding (a tester
        # batch 14).
        self.base_title = title
        self.title_var = tk.StringVar(value=title)
        ttk.Label(self.frame, textvariable=self.title_var,
                  font=(_SANS_FONT, 9)).pack(pady=(2, 1))
        # Spectrogram = the seek bar.  Click or drag anywhere to seek; the
        # playhead tracks playback.  Rendered by ffmpeg, shown via Pillow.
        self.spec_canvas = tk.Canvas(
            self.frame, height=90, highlightthickness=1, bd=0, cursor="hand2")
        self.spec_canvas.pack(fill=tk.X, expand=True, pady=(0, 2))
        self.spec_canvas.bind("<Button-1>", self._seek_click)
        self.spec_canvas.bind("<B1-Motion>", self._seek_click)
        self.spec_canvas.bind("<Configure>", self._on_canvas_resize, add="+")

        transport = ttk.Frame(self.frame)
        transport.pack(fill=tk.X)
        _ib = dict(width=26, height=26, highlightthickness=0, bd=0,
                   cursor="hand2", takefocus=0)
        self.play_canvas = tk.Canvas(transport, **_ib)
        self.play_canvas.pack(side=tk.LEFT)
        self.play_canvas.bind("<Button-1>", lambda _e: self.toggle_play())
        self.stop_canvas = tk.Canvas(transport, **_ib)
        self.stop_canvas.pack(side=tk.LEFT, padx=(2, 0))
        self.stop_canvas.bind("<Button-1>", lambda _e: self.stop_to_start())
        self.time_var = tk.StringVar(value="0:00 / 0:00")
        ttk.Label(transport, textvariable=self.time_var,
                  font=(_MONO_FONT, 9)).pack(side=tk.LEFT, padx=(10, 0))
        self._set_play_btn(False)
        win._draw_audio_icon(self.stop_canvas, "stop")

    # ---- loading ------------------------------------------------------

    def load(self, path, dur, limit=None, autoplay=False):
        """Load *path* into the strip.  *dur* is its probed duration (s);
        *limit* is the trim stop point (s), or None to play the whole file."""
        self.stop_playback()
        self.path = path
        self.dur = dur or 0.0
        self.limit = limit
        self.pos = 0.0
        self._hint = ""
        try:
            self.title_var.set("%s — %s" % (self.base_title,
                                            os.path.basename(path)))
        except Exception:
            pass
        self._render_spectrogram(path)
        self._update_time()
        if autoplay:
            self.start_playback(0.0)

    def clear(self, hint=""):
        """Empty the strip; *hint* is shown centered (e.g. the Replacement
        pane's 'no replacement assigned')."""
        self.stop_playback()
        self.path = None
        self.dur = 0.0
        self.limit = None
        self.pos = 0.0
        self._render_id += 1  # drop any in-flight render
        self._spec_img = None
        self._hint = hint
        try:
            self.title_var.set(self.base_title)
        except Exception:
            pass
        self._draw_hint()
        self._update_time()

    def _draw_hint(self):
        canvas = self.spec_canvas
        canvas.delete("all")
        if not self._hint:
            return
        w = canvas.winfo_width()
        h = canvas.winfo_height() or 90
        if w <= 10:  # not mapped yet; <Configure> re-draws once it is
            return
        canvas.create_text(w // 2, h // 2, fill="#888888", text=self._hint)

    def _on_canvas_resize(self, _event=None):
        if self.path is None:
            self._draw_hint()

    def _render_spectrogram(self, path):
        """Render the full-track spectrogram on a worker thread, then draw
        it.  Stale renders (track changed) are dropped via a counter."""
        canvas = self.spec_canvas
        self._render_id += 1
        rid = self._render_id
        w = max(200, canvas.winfo_width())
        h = 90  # fixed canvas height (widget is created height=90)
        canvas.delete("all")
        if not _HAVE_PIL:
            canvas.create_text(w // 2, h // 2, fill="#888888",
                               text="(install Pillow to see the spectrogram)")
            return
        canvas.create_text(w // 2, h // 2, fill="#888888",
                           text="rendering preview…", tags=("hint",))

        import threading
        from ..core import audio as _audio

        def _work():
            png = _audio.render_spectrogram_png(path, w, h)
            if self._render_id != rid:
                return
            self._win._tk_root().after(
                0, self._show_spectrogram, png, rid, w, h)

        threading.Thread(target=_work, daemon=True).start()

    def _show_spectrogram(self, png, rid, w, h):
        if self._render_id != rid:
            return
        canvas = self.spec_canvas
        canvas.delete("all")
        if png:
            try:
                import io
                img = Image.open(io.BytesIO(png)).convert("RGB")
                self._spec_img = ImageTk.PhotoImage(img)
                canvas.create_image(0, 0, anchor=tk.NW,
                                    image=self._spec_img, tags=("spec",))
            except Exception:
                self._spec_img = None
        else:
            canvas.create_text(w // 2, h // 2, fill="#888888",
                               text="(preview needs ffmpeg)")
        self._draw_cut_marker()
        self._draw_playhead()

    def _draw_cut_marker(self):
        """Mark where a trimmed replacement stops: a dashed line at the slot
        length with the trimmed tail hatched out, so the spectrogram shows
        exactly what the machine will play."""
        canvas = self.spec_canvas
        canvas.delete("cutmark")
        lim, dur = self.limit, self.dur
        if lim is None or dur <= 0:
            return
        w = max(1, canvas.winfo_width())
        h = canvas.winfo_height() or 90
        x = max(0, min(w, int((lim / dur) * w)))
        # Hatch the trimmed tail (stipple = pseudo-transparency in Tk) and
        # draw a red cut line + a small label.
        canvas.create_rectangle(x, 0, w, h, fill="#000000", outline="",
                                stipple="gray50", tags=("cutmark",))
        canvas.create_line(x, 0, x, h, fill="#ff6b6b", width=1,
                           dash=(3, 2), tags=("cutmark",))
        if x < w - 24:
            canvas.create_text(x + 3, 8, anchor=tk.W, fill="#ff9d9d",
                               text="trimmed", tags=("cutmark",))

    # ---- transport ----------------------------------------------------

    def toggle_play(self):
        """Play/pause.  ffplay (-nodisp) can't pause in place, so pause =
        stop + remember position; resume = restart ffplay at that position."""
        if self.path is None:
            if self._on_activate is not None:
                self._on_activate()
            return
        if self.playing:
            self.stop_playback()  # pause, keeps position
        else:
            stop_at = self.limit if self.limit is not None else self.dur
            if stop_at > 0 and self.pos >= stop_at - 0.05:
                self.pos = 0.0  # replay from start
            self.start_playback(self.pos)

    def stop_to_start(self):
        """■ silences BOTH panes, not just this one — sequential play may
        have moved the sound to the sibling, and stop on the pane in front
        of you must not leave the other one playing ("tie the stop buttons
        together (like slings!)" — a tester).  Only this pane rewinds; the
        sibling keeps its playhead."""
        # ■ ends the audition too: a clip that finished a moment ago has its
        # "play the next row" step already queued, and that would restart the
        # sound a fraction of a second after the press.
        self._win._cancel_audio_advance()
        if self.sibling is not None:
            self.sibling.stop_playback()
        self.stop_playback()
        self.pos = 0.0
        self._draw_playhead()

    def _set_play_btn(self, playing):
        self._win._draw_audio_icon(self.play_canvas,
                                   "pause" if playing else "play")

    def start_playback(self, pos):
        import time
        from ..core import audio as _audio
        if self.sibling is not None:
            self.sibling.stop_playback()  # never talk over the other pane
        _audio.stop_audio(self._proc)
        proc = _audio.play_audio_file(self.path, start=pos, limit=self.limit)
        if proc is None:
            self.playing = False
            self._set_play_btn(False)
            messagebox.showwarning(
                "Can't Preview",
                "Audio preview needs ffplay, which ships with the FULL ffmpeg "
                "build but NOT the \"essentials\" build.\n\n"
                "Fix it one of these ways:\n"
                "  • Use \"Install Missing\" above the tabs (installs the full "
                "build), then restart this app, or\n"
                "  • Download the full ffmpeg build and drop ffplay.exe in the "
                "same folder as ffmpeg.exe (run `where ffmpeg` to find it), "
                "then restart.\n\n"
                "Preview is optional -- it doesn't affect building the update; "
                "your replacements still get staged and written.")
            return
        self._proc = proc
        self._self_capping = bool(_audio.find_ffplay())
        self._start_pos = pos
        self._start_t = time.monotonic()
        self.pos = pos
        self.playing = True
        self._set_play_btn(True)
        self._schedule_tick()

    # Seconds of slack past a self-capping player's own stop point before we
    # kill it anyway.  Covers ffplay's spawn + audio-device latency (the whole
    # reason the wall clock can't be the end signal) and still catches a
    # player that wedged and never exited.
    _SELF_CAP_GRACE = 3.0

    def _schedule_tick(self):
        if self._tick_job is not None:
            try:
                self._win._tk_root().after_cancel(self._tick_job)
            except Exception:
                pass
        self._tick_job = self._win._tk_root().after(60, self._tick)

    def _tick(self):
        import time
        self._tick_job = None
        if not self.playing:
            return
        proc = self._proc
        elapsed = time.monotonic() - self._start_t
        self.pos = self._start_pos + elapsed
        # Stop at the trim point if there is one, else the file's end.
        stop_at = self.limit if self.limit is not None else self.dur
        if self._self_capping:
            # ffplay caps ITSELF (-autoexit, and -t for a trim point), so the
            # process exiting is the only honest end-of-playback signal.  The
            # wall clock starts at spawn, but audio doesn't come out until
            # ffplay has started and opened the device (~0.2-0.4 s) — killing
            # on `pos >= stop_at` therefore cut the tail off every clip, which
            # on a short callout ("Jackpot!", 0.7 s) is most of it (a tester
            # batch 22).  _SELF_CAP_GRACE is only a runaway guard for a player
            # that never exits.
            ended = proc is None or proc.poll() is not None or (
                stop_at > 0 and elapsed >= stop_at - self._start_pos
                + self._SELF_CAP_GRACE)
            # Don't let the playhead / clock run past the end while we wait
            # for the process to go away.
            if stop_at > 0:
                self.pos = min(self.pos, stop_at)
        else:
            # OS-native fallback (afplay / aplay / paplay): it can't cap, so
            # the wall clock is all we have.
            ended = (proc is None or proc.poll() is not None
                     or (stop_at > 0 and self.pos >= stop_at))
        if ended:
            # The fallback player has to be killed to honor a trim point; a
            # self-capping ffplay has normally exited on its own already.
            from ..core import audio as _audio
            _audio.stop_audio(proc)
            self._proc = None
            self.playing = False
            self.pos = 0.0  # reset so ▶ replays from the start
            self._set_play_btn(False)
            self._draw_playhead()
            if self.on_finished is not None:
                self.on_finished(self)
            return
        self._draw_playhead()
        self._schedule_tick()

    def _draw_playhead(self):
        canvas = self.spec_canvas
        canvas.delete("playhead")
        if self.dur > 0 and self.path:
            w = max(1, canvas.winfo_width())
            h = canvas.winfo_height() or 90
            x = int((self.pos / self.dur) * w)
            x = max(0, min(w, x))
            canvas.create_line(x, 0, x, h, fill="#ffffff", width=1,
                               tags=("playhead",))
        self._update_time()

    def _update_time(self):
        def _fmt(s):
            s = max(0, int(s))
            return f"{s // 60}:{s % 60:02d}"
        if self.path and self.dur > 0:
            if self.limit is not None:
                # The machine plays only up to the trim point -- show that as
                # the length, and note the full clip length that got cut.
                self.time_var.set(
                    f"{_fmt(self.pos)} / {_fmt(self.limit)}  "
                    f"(trimmed from {_fmt(self.dur)})")
            else:
                self.time_var.set(f"{_fmt(self.pos)} / {_fmt(self.dur)}")
        else:
            self.time_var.set("0:00 / 0:00")

    def _seek_click(self, event):
        if not self.path or self.dur <= 0:
            return
        w = max(1, self.spec_canvas.winfo_width())
        frac = max(0.0, min(1.0, event.x / w))
        pos = frac * self.dur
        # A click in the trimmed (hatched) tail has nothing to play -- clamp
        # to just before the cut so the playhead stays in the audible region.
        if self.limit is not None:
            pos = min(pos, max(0.0, self.limit - 0.05))
        self.pos = pos
        if self.playing:
            self.start_playback(self.pos)  # live re-seek
        else:
            self._draw_playhead()

    def stop_playback(self):
        """Stop playback (keeps the strip + playhead where it landed)."""
        from ..core import audio as _audio
        _audio.stop_audio(self._proc)
        self._proc = None
        self.playing = False
        if self._tick_job is not None:
            try:
                self._win._tk_root().after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        self._set_play_btn(False)
        self._draw_playhead()

    def apply_theme(self, c):
        """Re-skin after a theme change (canvas chrome + transport icons)."""
        self.spec_canvas.configure(background=c["field_bg"],
                                   highlightbackground=c["border"])
        for cv in (self.play_canvas, self.stop_canvas):
            cv.configure(background=c["bg"])
        self._set_play_btn(self.playing)
        self._win._draw_audio_icon(self.stop_canvas, "stop")


class _VideoPreviewPane:
    """One self-contained embedded video player: a frame canvas (a decode
    thread streams raw frames here while ffplay carries the sound), a seek
    bar, and its own play/stop transport.  The Replace Video tab shows two
    of these side by side — Original and Replacement — replacing the old
    single player with a Source A/B switch (David).  Starting one pane
    pauses its sibling so the soundtracks never overlap."""

    MAX_W, MAX_H = 320, 180

    # Where to look for the poster still, as a fraction of the clip, tried in
    # turn while the decoded frame comes back solid black.  A clip that opens
    # or closes on a fade would otherwise poster as an empty pane — and an
    # empty pane is indistinguishable from a preview that isn't working at
    # all, which is exactly the confusion a field report ran into.  Only the
    # still moves; the playhead stays where it was.
    POSTER_FRACTIONS = (0.5, 0.25, 0.75, 0.08)

    def __init__(self, win, parent, title, on_activate=None):
        self._win = win
        self._on_activate = on_activate
        self.sibling = None       # the other pane; paused when this one plays
        self.path = None          # file currently loaded in the player
        self.info = None          # its VideoInfo (dims / fps / alpha)
        self.dur = 0.0            # duration (s)
        self.pos = 0.0            # playhead position (s)
        self.playing = False
        self._start_pos = 0.0     # decode/audio -ss offset in flight
        self._start_t = 0.0       # monotonic clock at playback start
        self._audio_proc = None   # ffplay handle carrying the sound
        self._decode_proc = None  # ffmpeg raw-frame stream handle
        self._decode_thread = None
        self._stop_event = None   # signals the decode thread to exit
        self._frame_q = None      # queue of (idx, rgb_bytes) frames
        self._session = 0         # bump to invalidate a play session
        self._render_id = 0       # bump to drop stale single-frame renders
        self._frame_img = None    # PhotoImage ref (must stay alive)
        self._frame_err = False   # a draw failure was already reported
        self._disp_w = self.MAX_W  # frame-canvas draw size (aspect-fit)
        self._disp_h = self.MAX_H
        self._tick_job = None     # after() id for the playback timer
        self._scrub_job = None    # debounce: decode a frame while scrubbing
        self._hint = ""           # message shown when nothing is loaded

        self.frame = ttk.Frame(parent)
        # Title carries the loaded file's name ("Original — idx0258.wav") so
        # the user always knows exactly what the player is holding (a tester
        # batch 14).
        self.base_title = title
        self.title_var = tk.StringVar(value=title)
        ttk.Label(self.frame, textvariable=self.title_var,
                  font=(_SANS_FONT, 9)).pack(pady=(2, 1))
        self.canvas = tk.Canvas(
            self.frame, width=self.MAX_W, height=self.MAX_H,
            highlightthickness=1, bd=0, background="#000000")
        self.canvas.pack(pady=(0, 2))
        self.canvas.bind("<Configure>", self._on_canvas_resize, add="+")
        # Seek bar: click or drag to seek; the playhead tracks playback.  It
        # asks for the frame canvas's width even though it stretches to fill —
        # left to Tk's default a bare canvas requests 378px, which quietly made
        # every pane 58px wider than the video in it.
        self.seek_canvas = tk.Canvas(
            self.frame, width=self.MAX_W, height=16, highlightthickness=1,
            bd=0, cursor="hand2")
        self.seek_canvas.pack(fill=tk.X, pady=(0, 2))
        self.seek_canvas.bind("<Button-1>", self._seek_click)
        self.seek_canvas.bind("<B1-Motion>", self._seek_click)

        transport = ttk.Frame(self.frame)
        transport.pack(fill=tk.X)
        _ib = dict(width=26, height=26, highlightthickness=0, bd=0,
                   cursor="hand2", takefocus=0)
        self.play_canvas = tk.Canvas(transport, **_ib)
        self.play_canvas.pack(side=tk.LEFT)
        self.play_canvas.bind("<Button-1>", lambda _e: self.toggle_play())
        self.stop_canvas = tk.Canvas(transport, **_ib)
        self.stop_canvas.pack(side=tk.LEFT, padx=(2, 0))
        self.stop_canvas.bind("<Button-1>", lambda _e: self.stop_to_start())
        self.time_var = tk.StringVar(value="0:00 / 0:00")
        ttk.Label(transport, textvariable=self.time_var,
                  font=(_MONO_FONT, 9)).pack(side=tk.LEFT, padx=(10, 0))
        self._set_play_btn(False)
        win._draw_audio_icon(self.stop_canvas, "stop")

    # ---- loading ------------------------------------------------------

    def load(self, path, autoplay=False):
        """Load *path* into the player and poster a representative frame."""
        from ..core import video as _video
        self._cancel_scrub()
        self.stop_playback()
        self._hint = ""
        self._frame_err = False
        self.path = path
        try:
            self.title_var.set("%s — %s" % (self.base_title,
                                            os.path.basename(path)))
        except Exception:
            pass
        info = _video.detect_video_info(path)
        self.info = info
        dur = (info.duration if info and info.duration > 0
               else _video.probe_video_duration(path))
        self.dur = dur or 0.0
        self.pos = 0.0
        self._compute_disp_size(info)
        self._render_representative_poster()
        self._update_time()
        if autoplay:
            self.start_playback(0.0)

    def clear(self, hint=""):
        """Reset the player entirely; *hint* is shown centered on the frame
        canvas (e.g. the Replacement pane's 'no replacement assigned')."""
        self._cancel_scrub()
        self.stop_playback()
        self.path = None
        self.info = None
        self.dur = 0.0
        self.pos = 0.0
        self._render_id += 1  # drop any in-flight render
        self._frame_img = None
        self._hint = hint
        try:
            self.title_var.set(self.base_title)
        except Exception:
            pass
        self._draw_hint()
        self.seek_canvas.delete("all")
        self._update_time()

    def _draw_hint(self):
        canvas = self.canvas
        canvas.delete("all")
        if not self._hint:
            return
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw <= 10:  # not mapped yet; <Configure> re-draws once it is
            cw, ch = self.MAX_W, self.MAX_H
        canvas.create_text(cw // 2, ch // 2, fill="#888888", width=cw - 16,
                           text=self._hint)

    def _on_canvas_resize(self, _event=None):
        if self.path is None:
            self._draw_hint()

    def _compute_disp_size(self, info):
        """Aspect-fit the clip inside the frame canvas; store the even-numbered
        draw size used by both the poster render and the decode stream."""
        max_w, max_h = self.MAX_W, self.MAX_H
        if info and info.width > 0 and info.height > 0:
            w, h = info.width, info.height
        else:
            w, h = 16, 9
        scale = min(max_w / w, max_h / h)
        dw = max(16, int(w * scale))
        dh = max(16, int(h * scale))
        self._disp_w = dw - (dw % 2)
        self._disp_h = dh - (dh % 2)

    def _render_representative_poster(self):
        """Poster a representative frame, not the frame at 0.0 -- many clips
        open on a black leader frame or a fade-in, which looked like a
        broken/empty preview.  Grab mid-clip when the duration is known, else
        a small offset in, and keep looking if that frame is black too.  The
        playhead is left where the caller put it; this only changes the
        still."""
        if self.dur > 0.2:
            spots = [self.dur * f for f in self.POSTER_FRACTIONS]
        else:
            spots = [0.5]
        self._render_poster(spots[0], fallbacks=spots[1:], sampling=True)

    def _render_poster(self, pos, fallbacks=None, sampling=False):
        """Decode a single frame at *pos* on a worker thread, then show it.
        Stale renders (clip/seek changed) are dropped via a counter.

        *fallbacks* are further positions to try if the frame at *pos* comes
        back solid black (see :data:`POSTER_FRACTIONS`).  *sampling* marks
        this render as part of that hunt for a representative frame, so only
        the hunt can conclude the whole clip is black — a one-off render (a
        scrub) that lands on a black frame speaks for that frame alone."""
        canvas = self.canvas
        path = self.path
        self._render_id += 1
        rid = self._render_id
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw <= 10:
            cw, ch = self.MAX_W, self.MAX_H
        canvas.delete("all")
        if not _HAVE_PIL:
            canvas.create_text(cw // 2, ch // 2, fill="#bbbbbb",
                               width=cw - 16,
                               text="Install Pillow to preview frames in-app "
                                    "(Play still opens an ffplay window).")
            return
        canvas.create_text(cw // 2, ch // 2, fill="#888888",
                           text="loading frame…")

        import threading
        from ..core import video as _video

        def _work():
            png = _video.extract_frame_png(
                path, pos, self._disp_w, self._disp_h)
            if self._render_id != rid:
                return
            self._win._tk_root().after(0, self._show_poster, png, rid,
                                       fallbacks, sampling)

        threading.Thread(target=_work, daemon=True).start()

    def _show_poster(self, png, rid, fallbacks=None, sampling=False):
        if self._render_id != rid:
            return
        canvas = self.canvas
        cw = canvas.winfo_width() or self.MAX_W
        ch = canvas.winfo_height() or self.MAX_H
        if png and _HAVE_PIL:
            try:
                import io
                img = Image.open(io.BytesIO(png)).convert("RGB")
            except Exception as e:  # noqa: BLE001 — any decode failure
                canvas.delete("all")
                self._frame_img = None
                self._draw_canvas_note("Couldn't show this frame: %s" % e)
                self._draw_playhead()
                return
            # An all-black still is where "the preview is broken" and "the
            # clip is black here" look identical.  Try the next sample spot,
            # and if the clip is black everywhere we looked, say so rather
            # than leaving a bare black rectangle.
            if img.getbbox() is None:
                if fallbacks:
                    self._render_poster(fallbacks[0], fallbacks[1:],
                                        sampling=True)
                    return
                canvas.delete("all")
                self._frame_img = None
                if sampling:
                    self._draw_canvas_note(
                        "Every frame sampled is black — this clip may be an "
                        "overlay that only shows over the scene behind it. "
                        "Press ▶ to play it through.")
                else:
                    # One frame, asked for by position (a scrub).  Saying
                    # "every frame" here read as a verdict on the whole clip,
                    # and a tester whose replacement plays perfectly well got
                    # it just for landing on the fade at 0:00.
                    self._draw_canvas_note(
                        "This frame is black. Drag the bar or press ▶ to see "
                        "the rest of the clip.")
                self._draw_playhead()
                return
            canvas.delete("all")
            try:
                self._frame_img = ImageTk.PhotoImage(img)
                canvas.create_image(cw // 2, ch // 2, anchor=tk.CENTER,
                                    image=self._frame_img, tags=("frame",))
            except Exception as e:  # noqa: BLE001 — Tk/Pillow mismatch
                self._frame_img = None
                self._draw_canvas_note(
                    "Couldn't draw this frame: %s\n%s"
                    % (e, _pil_tk_hint()))
        else:
            canvas.delete("all")
            self._draw_canvas_note(
                "Couldn't decode a frame from this clip — check that ffmpeg "
                "is installed and that the file plays in a video player.")
        self._draw_playhead()

    def _draw_canvas_note(self, text):
        """Centre *text* on the frame canvas.  Used wherever a frame can't be
        shown: a bare black canvas gives the user nothing to act on, and
        reads as a broken app even when the clip itself is the problem."""
        canvas = self.canvas
        cw = canvas.winfo_width() or self.MAX_W
        ch = canvas.winfo_height() or self.MAX_H
        if cw <= 10:
            cw, ch = self.MAX_W, self.MAX_H
        canvas.create_text(cw // 2, ch // 2, fill="#bbbbbb", width=cw - 16,
                           justify=tk.CENTER, text=text, tags=("note",))

    def _show_frame_rgb(self, data):
        """Display one raw rgb24 frame (from the decode thread) on the canvas."""
        if not _HAVE_PIL:
            return
        w, h = self._disp_w, self._disp_h
        if not data or len(data) != w * h * 3:
            return
        try:
            img = Image.frombytes("RGB", (w, h), data)
            self._frame_img = ImageTk.PhotoImage(img)
            canvas = self.canvas
            cw = canvas.winfo_width() or self.MAX_W
            ch = canvas.winfo_height() or self.MAX_H
            canvas.delete("frame")
            canvas.delete("note")
            canvas.create_image(cw // 2, ch // 2, anchor=tk.CENTER,
                                image=self._frame_img, tags=("frame",))
        except Exception as e:  # noqa: BLE001 — report once, don't spam
            if not self._frame_err:
                self._frame_err = True
                self.canvas.delete("all")
                self._draw_canvas_note(
                    "Couldn't draw this clip's frames: %s\n%s"
                    % (e, _pil_tk_hint()))

    # ---- transport ----------------------------------------------------

    def toggle_play(self):
        if self.path is None:
            if self._on_activate is not None:
                self._on_activate()
            return
        if self.playing:
            self.stop_playback()  # pause, keeps position
            self._draw_playhead()
        else:
            if self.dur > 0 and self.pos >= self.dur - 0.05:
                self.pos = 0.0  # replay from start
            self.start_playback(self.pos)

    def stop_to_start(self):
        # ■ stops the sibling too — same tied-together rule as the audio
        # panes (a tester); the sibling keeps its playhead.
        if self.sibling is not None:
            self.sibling.stop_playback()
        self.stop_playback()
        self.pos = 0.0
        self._draw_playhead()
        if self.path:
            # Back to the still the pane opened with, NOT the frame at 0.0:
            # rewinding a clip that fades in from black used to swap the
            # picture for the "every frame sampled is black" note (a tester,
            # whose replacement had played fine seconds earlier).
            self._render_representative_poster()

    def _set_play_btn(self, playing):
        self._win._draw_audio_icon(self.play_canvas,
                                   "pause" if playing else "play")

    def start_playback(self, pos):
        import threading
        import queue
        import time
        from ..core import audio as _audio
        from ..core import video as _video

        self.stop_playback()  # tear down any prior session
        if self.sibling is not None:
            self.sibling.stop_playback()  # never talk over the other pane
        path = self.path
        if not path:
            return
        info = self.info
        fps = info.fps if (info and info.fps > 0) else 30.0
        w, h = self._disp_w, self._disp_h

        proc = (_video.open_raw_stream(path, w, h, fps, start=pos)
                if _HAVE_PIL else None)
        if proc is None:
            # No ffmpeg frame stream (or no Pillow): fall back to a windowed
            # ffplay that plays video + audio in its own window.
            ap = _video.play_video_windowed(path, start=pos)
            if ap is None:
                messagebox.showwarning(
                    "Can't Preview",
                    "Video preview needs ffmpeg / ffplay on your PATH.\n\n"
                    "Install ffmpeg to preview clips before staging.")
                return
            self._audio_proc = ap
        else:
            self._session += 1
            self._decode_proc = proc
            stop_event = threading.Event()
            self._stop_event = stop_event
            q = queue.Queue(maxsize=int(max(8, fps)))  # ~1s of frames
            self._frame_q = q
            framesize = w * h * 3
            t = threading.Thread(
                target=self._decode_worker,
                args=(proc, framesize, q, stop_event), daemon=True)
            self._decode_thread = t
            t.start()
            # Sound: ffplay -nodisp carries the audio track.  Most formats play
            # their own audio; a custom backend (.cdmd) points at a sibling
            # .wav instead.
            if info is None or info.has_audio:
                asrc = _video.audio_source_for(path)
                if asrc:
                    self._audio_proc = _audio.play_audio_file(asrc, start=pos)

        self._start_pos = pos
        self._start_t = time.monotonic()
        self.pos = pos
        self.playing = True
        self._set_play_btn(True)
        self._schedule_tick()

    def _decode_worker(self, proc, framesize, q, stop_event):
        """Worker thread: read raw rgb24 frames from ffmpeg into *q* until the
        stream ends or the session is cancelled."""
        import queue as _q
        idx = 0
        try:
            stdout = proc.stdout
            while not stop_event.is_set():
                data = stdout.read(framesize)
                if not data or len(data) < framesize:
                    break
                while not stop_event.is_set():
                    try:
                        q.put((idx, data), timeout=0.2)
                        break
                    except _q.Full:
                        continue
                idx += 1
        except (OSError, ValueError):
            pass
        finally:
            try:
                q.put((None, None), timeout=0.2)  # sentinel: stream ended
            except Exception:
                pass

    def _schedule_tick(self):
        info = self.info
        fps = info.fps if (info and info.fps > 0) else 30.0
        # Poll a bit faster than the frame rate so the queue stays drained.
        interval = int(1000 / (fps * 1.3))
        interval = max(10, min(45, interval))
        if self._tick_job is not None:
            try:
                self._win._tk_root().after_cancel(self._tick_job)
            except Exception:
                pass
        self._tick_job = self._win._tk_root().after(interval, self._tick)

    def _tick(self):
        import time
        import queue as _q
        self._tick_job = None
        if not self.playing:
            return

        self.pos = self._start_pos + (time.monotonic() - self._start_t)
        info = self.info
        fps = info.fps if (info and info.fps > 0) else 30.0

        ended = False
        q = self._frame_q
        if q is not None:
            # Drain up to the frame the clock has reached; show the latest.
            desired = int((self.pos - self._start_pos) * fps)
            frame = None
            while True:
                try:
                    idx, data = q.get_nowait()
                except _q.Empty:
                    break
                if idx is None:
                    ended = True
                    break
                frame = data
                if idx >= desired:
                    break
            if frame is not None:
                self._show_frame_rgb(frame)
        else:
            # Windowed-ffplay fallback: end when that process exits.
            ap = self._audio_proc
            if ap is not None and ap.poll() is not None:
                ended = True

        if not ended and self.dur > 0 and self.pos >= self.dur:
            ended = True

        if ended:
            self.stop_playback()
            self.pos = 0.0  # so ▶ replays from the start
            self._draw_playhead()
            if self.path:
                self._render_representative_poster()  # same as ■; see above
            return

        self._draw_playhead()
        self._schedule_tick()

    def _draw_playhead(self):
        canvas = self.seek_canvas
        canvas.delete("all")
        w = max(1, canvas.winfo_width())
        h = canvas.winfo_height() or 16
        c = THEMES.get(self._win._current_theme, {})
        canvas.create_rectangle(0, 0, w, h,
                                fill=c.get("field_bg", "#222222"), outline="")
        if self.dur > 0 and self.path:
            x = int((self.pos / self.dur) * w)
            x = max(0, min(w, x))
            canvas.create_rectangle(0, 0, x, h,
                                    fill=c.get("select_bg", "#3a6ea5"),
                                    outline="")
            canvas.create_line(x, 0, x, h, fill="#ffffff", width=2)
        self._update_time()

    def _update_time(self):
        def _fmt(s):
            s = max(0, int(s))
            return f"{s // 60}:{s % 60:02d}"
        if self.path and self.dur > 0:
            self.time_var.set(f"{_fmt(self.pos)} / {_fmt(self.dur)}")
        else:
            self.time_var.set("0:00 / 0:00")

    def _seek_click(self, event):
        if not self.path or self.dur <= 0:
            return
        w = max(1, self.seek_canvas.winfo_width())
        frac = max(0.0, min(1.0, event.x / w))
        self.pos = frac * self.dur
        if self.playing:
            self.start_playback(self.pos)  # live re-seek
        else:
            self._draw_playhead()
            self._schedule_scrub()  # decode the frame at rest (debounced)

    def _schedule_scrub(self):
        self._cancel_scrub()
        self._scrub_job = self._win._tk_root().after(120, self._do_scrub)

    def _cancel_scrub(self):
        if self._scrub_job is not None:
            try:
                self._win._tk_root().after_cancel(self._scrub_job)
            except Exception:
                pass
            self._scrub_job = None

    def _do_scrub(self):
        self._scrub_job = None
        if self.playing or not self.path:
            return
        self._render_poster(self.pos)

    def stop_playback(self):
        """Stop playback: cancel the session, kill the decode + audio
        processes, and stop the timer (keeps the playhead where it landed)."""
        from ..core import audio as _audio
        self._session += 1  # invalidate any in-flight session
        if self._stop_event is not None:
            self._stop_event.set()
        if self._decode_proc is not None:
            try:
                if self._decode_proc.poll() is None:
                    self._decode_proc.terminate()
            except OSError:
                pass
        self._decode_proc = None
        _audio.stop_audio(self._audio_proc)
        self._audio_proc = None
        self._decode_thread = None
        self._stop_event = None
        self._frame_q = None
        self.playing = False
        if self._tick_job is not None:
            try:
                self._win._tk_root().after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        self._set_play_btn(False)

    def apply_theme(self, c):
        """Re-skin after a theme change (canvas chrome + transport icons)."""
        self.canvas.configure(highlightbackground=c["border"])
        self.seek_canvas.configure(highlightbackground=c["border"])
        for cv in (self.play_canvas, self.stop_canvas):
            cv.configure(background=c["bg"])
        self._set_play_btn(self.playing)
        self._win._draw_audio_icon(self.stop_canvas, "stop")
        self._draw_playhead()


class MainWindow:
    """Single-window Tk GUI; manufacturer-aware via apply_manufacturer()."""

    def __init__(self, root, app_title, manufacturers,
                 on_manufacturer_change,
                 on_extract, on_extract_cancel,
                 on_write, on_write_cancel,
                 on_export, on_import,
                 on_transfer_mods=None,
                 on_apply_delta=None,
                 on_revert_all=None,
                 on_flash_image=None,
                 on_recheck_prereqs=None, on_install_prereqs=None,
                 on_back=None,
                 on_theme_change=None, initial_theme=None,
                 on_check_updates=None,
                 on_install_update=None,
                 initial_fda_acknowledged=False,
                 on_fda_acknowledge=None,
                 initial_column_widths=None,
                 on_column_widths_change=None,
                 initial_admin_warning_collapsed=False,
                 on_admin_warning_collapsed_change=None,
                 initial_voice_quality=None,
                 on_voice_quality_change=None,
                 initial_audio_advanced=None,
                 on_audio_advanced_change=None,
                 on_detected_game_change=None,
                 on_audio_profile=None,
                 on_partition_image_opened=None,
                 on_compare_run=None,
                 initial_default_presets=None,
                 on_default_presets_change=None,
                 initial_flash_choices=None,
                 on_flash_choices_change=None,
                 on_build_flash=None,
                 on_save_project=None,
                 on_load_project=None,
                 on_new_project=None,
                 on_save_project_as=None,
                 on_project_properties=None,
                 on_open_project_manager=None,
                 on_open_recent_project=None,
                 recent_projects_provider=None,
                 on_project_folder_picked=None,
                 on_folder_state_written=None,
                 initial_show_log_history=True,
                 on_show_log_history_change=None):
        self.root = root
        self._install_callback_error_logger(root)
        # Default Settings presets: {"presets": {name: {AD_name: value}},
        # "active": name}.  Persisted via on_default_presets_change.
        self._default_presets = dict(initial_default_presets or {})
        self._on_default_presets_change = on_default_presets_change
        self._manufacturers = manufacturers   # list[Manufacturer]
        self._on_manufacturer_change = on_manufacturer_change
        self._on_extract = on_extract
        self._on_extract_cancel = on_extract_cancel
        self._on_write = on_write
        self._on_write_cancel = on_write_cancel
        self._on_apply_delta = on_apply_delta
        self._on_revert_all = on_revert_all
        self._on_flash_image = on_flash_image
        # Build-then-flash chain (the two-section Build / flash dialog):
        # ``on_build_flash(build_path, device_path_or_None)``.
        self._on_build_flash = on_build_flash
        self._on_save_project = on_save_project
        self._on_load_project = on_load_project
        # Batch 19 project callbacks (all app-side): the Project ▾ menu's
        # actions, the Recent-projects provider (returns registry entries),
        # and the two materialization hooks (folder picked / folder state
        # written).
        self._on_new_project = on_new_project
        self._on_save_project_as = on_save_project_as
        self._on_project_properties = on_project_properties
        self._on_open_project_manager = on_open_project_manager
        self._on_open_recent_project = on_open_recent_project
        self._recent_projects_provider = recent_projects_provider
        self._on_project_folder_picked = on_project_folder_picked
        self._on_folder_state_written = on_folder_state_written
        self._on_recheck_prereqs = on_recheck_prereqs
        self._on_install_prereqs = on_install_prereqs
        self._on_back = on_back
        self._on_export = on_export
        self._on_import = on_import
        self._on_transfer_mods = on_transfer_mods
        self._on_theme_change = on_theme_change
        self._on_check_updates = on_check_updates
        # In-app "Install update" (Windows): app.py downloads the setup
        # exe and runs it silently — set only where that flow exists.
        self._on_install_update = on_install_update
        # Per-tree column widths the user dragged, persisted across restarts via
        # ``on_column_widths_change`` (settings.json).  ``{tree_key: {col: px}}``.
        self._saved_column_widths = dict(initial_column_widths or {})
        self._on_column_widths_change = on_column_widths_change
        # Which Build / flash sections the user last ran, per manufacturer
        # (``{mfr_key: {"build": bool, "write": bool}}``), persisted via
        # ``on_flash_choices_change`` — a tester who builds here and writes the
        # card elsewhere had to untick the write section every single time.
        # Per manufacturer because the two sections don't mean the same thing
        # across plugins (Stern writes a raw SD image, JJP formats a stick).
        self._saved_flash_choices = dict(initial_flash_choices or {})
        self._on_flash_choices_change = on_flash_choices_change
        # Recent paths per field (``{field_key: [paths, most recent first]}``)
        # backing the path boxes' dropdown history (a tester: "any text box
        # showing a file path should have a history").  Owned + persisted by
        # the App per manufacturer; set via set_path_history() on mfr switch.
        self._path_history = {}
        # macOS FDA banner state.  Persisted in settings.json via
        # ``on_fda_acknowledge`` so the dismissal survives restarts —
        # the previous "always show" behaviour was out of sync with
        # the actual TCC state and felt broken once a user had
        # already granted Full Disk Access in System Settings.  We
        # auto-set this to True on the first successful Direct-SSD
        # run (proof that FDA works); the user can also click the
        # "Hide this notice" link in the banner to dismiss manually.
        self._fda_acknowledged = bool(initial_fda_acknowledged)
        self._on_fda_acknowledge = on_fda_acknowledge
        # Admin-warning panel: the big red banner heading stays put, but its
        # how-to-fix body is collapsible and the choice persists (settings.json
        # via ``on_admin_warning_collapsed_change``) so returning users who've
        # read it once aren't shown the whole wall of text every time.  Shared
        # across the Extract + Write copies; both register in this list.
        self._admin_warning_collapsed = bool(initial_admin_warning_collapsed)
        self._on_admin_warning_collapsed_change = (
            on_admin_warning_collapsed_change)
        self._admin_warning_frames = []
        # Voice-recognition (auto-name call-outs) quality — the faster-whisper
        # model size, picked in the ⚙ settings menu and persisted in
        # settings.json via ``on_voice_quality_change`` (a tester: "dial in
        # better voice recognition at the expense of processing time").
        vq = initial_voice_quality
        if vq not in {v for v, _ in VOICE_QUALITY_CHOICES}:
            vq = VOICE_QUALITY_CHOICES[0][0]
        self.voice_quality_var = tk.StringVar(value=vq)
        self._on_voice_quality_change = on_voice_quality_change
        # Advanced audio options (head/tail modes + anti-pop seed +
        # machine-render previews) — experiment levers for the Spike 2
        # trigger-pop hunt.  Persisted via ``on_audio_advanced_change``; the
        # App mirrors them into the encoder's env vars.  (The
        # match-to-callouts shaper and its fade/cap/roll-off knobs lived here
        # too until feedback batch 20 — retired: it never fixed the click it
        # chased; the blip-free firmware patch did, and that now has a checkbox
        # of its own here — on by default, and as of v0.94.0 the patch lives in
        # a memory mapping of its own instead of borrowing the game's, which is
        # what had it landing on Elvira's node board table.)
        self._audio_advanced = dict(initial_audio_advanced or {})
        self._on_audio_advanced_change = on_audio_advanced_change
        # Fired with a short caption ("Led Zeppelin v1.22 LE") when the
        # Extract input detects a game, and with None when it no longer does —
        # the App shows it in the title bar (batch 20: the tab's "Detected:"
        # badge said the same thing three ways).
        self._on_detected_game_change = on_detected_game_change
        self._on_audio_profile = on_audio_profile
        # Fired with the image path when the Partition Explorer successfully
        # opens a card — the App records it into the field's recent-paths
        # dropdown (a tester: same "last 5" memory as the Extract screen).
        self._on_partition_image_opened = on_partition_image_opened
        # Fired with (path_a, path_b) when a Compare run starts — the App
        # records both into recent-paths history and persists them.
        self._on_compare_run = on_compare_run
        # Seed each log pane with the previous sessions' history (dimmed,
        # above a cut line)?  ⚙-menu checkbutton; OFF = a clean per-session
        # log for users who don't want the past in view.  Persisted in
        # settings.json via ``on_show_log_history_change``; the on-disk
        # history keeps collecting either way, so flipping it back ON
        # restores the past instantly.
        self.show_log_history_var = tk.BooleanVar(
            value=bool(initial_show_log_history))
        self._on_show_log_history_change = on_show_log_history_change
        self._app_title = app_title

        self._current_mfr = None
        self._suppress_mfr_event = False
        # Per-mfr log widgets — created lazily, swapped on mfr select.
        # Each manufacturer keeps its own scrollback so going Back +
        # Forward to the same mfr restores their full log history.
        self._log_widgets = {}    # mfr.key -> tk.Text
        self._log_text = None     # alias for the currently-packed widget
        # Lines logged before any mfr is selected (e.g. the startup update
        # check while the picker is showing) — flushed into the first log
        # widget that appears.  Entries: ("line", ts, text, level) or
        # ("link", ts, text, url).
        self._pending_log = []
        # Run counter namespacing the in-place keyed log lines (see
        # update_log_line); bumped on each run start so re-runs don't edit the
        # previous run's lines.
        self._log_line_run = 0

        # Default size picked so the picker fits all 4 current cards
        # (incl. Spooky's 14-game list) without scrolling on a typical
        # 1080p display.  Height bumped in v0.7.11 from 940 → 1060 so
        # the macOS FDA banner doesn't push the log frame below the
        # viewport on the Extract / Write tabs; bumped again to 1200 so the
        # Replace-Audio tab's preview player (spectrogram + transport) fits
        # without the mfr-view scrollbar.  minsize stays small — when the
        # window is shorter, the scrollable mfr-view lets the user reach
        # everything anyway.
        # First-launch default height.  1080 fits the working view (tabs + log)
        # comfortably without the old 1200 that stretched to ~100% vertical on a
        # 1080p screen.  Clamped to the screen workarea so it still fits a
        # shorter display, and the tab body scrolls if a little taller than the
        # window.  Only matters on the very first launch — the app restores the
        # user's saved size + position on every subsequent launch
        # (App._restore_window_geometry).
        default_h = min(1080, max(700, root.winfo_screenheight() - 80))
        root.geometry("820x%d" % default_h)
        root.minsize(720, 700)

        if sys.platform == "win32":
            ico = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "icon.ico")
            if os.path.isfile(ico):
                try:
                    root.iconbitmap(ico)
                except tk.TclError:
                    pass

        self._start_time = None
        self._timer_id = None
        self._current_theme = initial_theme or detect_system_theme()

        # Tk vars
        self.extract_input_var = tk.StringVar()
        self.extract_output_var = tk.StringVar()
        # Optional delta updates to merge during Extract (chain_deltas
        # plugins, e.g. Dutch Pinball).  The list holds the chosen paths;
        # the StringVar shows a short summary.
        self.extract_delta_paths = []
        self.extract_deltas_display_var = tk.StringVar(value="No updates added")
        # Re-evaluate game-specific Extract controls (DMD shader, delta
        # merge) when the chosen input changes — a multi-game plugin shows
        # them for some games (TBL) and not others (AAIW).
        self.extract_input_var.trace_add(
            "write", lambda *a: self._on_extract_input_changed())
        self.write_upd_var = tk.StringVar()
        self.write_assets_var = tk.StringVar()
        # The Replace tabs' project-folder mirror labels track this var: the
        # shared project folder, or a pointer at the Extract tab while no
        # project is loaded (a bare empty label reads as broken — batch 20).
        self._project_mirror_var = tk.StringVar()
        self.write_assets_var.trace_add(
            "write", lambda *a: self._project_mirror_var.set(
                (self.write_assets_var.get() or "").strip()
                or "(no project yet — extract into one on the Extract tab)"))
        self._project_mirror_var.set(
            "(no project yet — extract into one on the Extract tab)")
        self.write_output_var = tk.StringVar()
        # Editable name for the file Write builds.  Defaults to the original's
        # name plus the plugin's distinguishing suffix (e.g. "…-modified.raw"),
        # but the user can rename it to keep several builds side by side in one
        # folder.  ``_write_filename_auto`` remembers the last auto-filled
        # default so we keep tracking the original until the user types a name
        # of their own (then we stop clobbering it).
        self.write_filename_var = tk.StringVar()
        self._write_filename_auto = ""
        # Round icon buttons (ⓘ badges, header home/?/⚙) — plain Canvases,
        # collected so _apply_theme can re-skin their backdrops.  Their
        # anti-aliased disc images are cached per (size, fill, bg, dots);
        # instance-level on purpose (PhotoImages die with this Tk interp).
        self._round_icons = []
        self._disc_img_cache = {}
        # Image Info window state (the round ⓘ badge next to the image
        # pickers opens one singleton Toplevel, built on demand).
        self._info_win = None
        self._info_path = ""
        self._info_seq = 0           # bump-counter: drops stale worker results
        self._info_sections = []     # last rendered sections (Copy Report)
        self._info_shown_key = None  # (path, assets) the tree currently shows
        # Compare tab state (capabilities.compare plugins): two card pickers
        # and a worker-built what-changed report (a tester's wish list).
        # The vars live here, not in the tab builder, so the App can restore
        # saved paths regardless of build order.
        self.compare_a_var = tk.StringVar()
        self.compare_b_var = tk.StringVar()
        self._compare_seq = 0        # bump-counter, same shape as _info_seq
        self._compare_sections = []  # last rendered sections (Copy Report)
        # Replace-Audio tab state (capabilities.replace_audio plugins).
        # The tab scans the assets folder for .wav/.ogg slots and lets the
        # user assign a replacement track per slot; staging writes the
        # converted replacements over the originals so Write repacks them.
        self.audio_search_var = tk.StringVar()
        # "Type" filter (All types / Music / Sound FX / Callouts / Other) —
        # a tester: "I am working on callouts so I want to hide everything
        # else".  Categories are derived per scan (core.audio_categories);
        # the dropdown hides itself for folders where nothing classifies.
        self.audio_type_var = tk.StringVar(value="All types")
        # Change-state filter: All / Changed / Unchanged.  Was a "Changed only"
        # checkbox (batch 16); batch 28 made it a dropdown because half-way
        # through a card the useful view is the OTHER one — "If I could select
        # unchanged, I could then filter out the ones I have already dealt with
        # instead of scrolling up and down" (a tester with 90% of his callouts
        # replaced).  Persisted per assets folder with the other Replace
        # toggles.
        self.audio_change_filter_var = tk.StringVar(value="All")
        self._audio_categories = {}      # rel_path -> music/sfx/callouts/other
        # Click-header sort state: (column_id, descending).  Defaults to the
        # name column ascending — matches the old "Name" dropdown default.
        self._audio_sort = ("#0", False)
        # Off by default: most users replacing *music* want their whole
        # track, not one clipped to the original slot's length.  Games that
        # require exact-length slots (JJP/Spooky) already trim/pad in their
        # own Write step regardless of this toggle.
        self.audio_trim_var = tk.BooleanVar(value=False)
        # Audition mode: a finished clip selects and plays the next visible
        # row.  Session-only (not persisted) — it is a thing you switch on to
        # listen through a card, not a preference.
        self.audio_play_through_var = tk.BooleanVar(value=False)
        # Play-through plays the replacement instead of the original wherever
        # one exists (batch 24: a tester auditioning the whole card to catch
        # the clips he still meant to replace).
        self.audio_play_subst_var = tk.BooleanVar(value=False)
        self.audio_status_var = tk.StringVar(value="")
        self._audio_slots = []           # list[AudioSlot] from last scan
        self._audio_slots_by_rel = {}    # rel_path -> AudioSlot
        self._audio_assignments = {}     # rel_path -> replacement file path
        self._audio_loop_flags = {}      # rel_path -> bool (BOF loop-inject)
        self._audio_keep_full_flags = {}  # rel_path -> bool (JJP keep-full-len)
        self._audio_loop_tip = None      # Loop/keep-column hover tooltip Toplevel
        self._audio_scan_id = 0          # bump-counter to drop stale scans
        self._audio_scan_dir = ""        # folder the current slots came from
        # Folder each tab's in-memory assignments were made against, kept
        # across invalidate_asset_scans() (which clears the scan stamps but
        # not the assignments).  Lets the Build/Export folder-mismatch check
        # name the real folder instead of "(unknown)" — and recognise a
        # same-folder re-extract as a match (a tester).
        self._scan_dir_prev = {"audio": "", "video": "", "image": ""}
        # "Group duplicates" (CGC banks): cluster slots that carry
        # byte-identical factory audio under one parent row.  The grouping
        # comes from the plugin's duplicate scan (~10 s on a full PF
        # extract), cached per folder; ticking the box with a cold cache
        # kicks the scan and shows a busy overlay until it lands.  NOT
        # persisted — off by default each session so a folder load never
        # auto-kicks the scan.
        self.audio_group_dups_var = tk.BooleanVar(value=False)
        self.audio_group_dups_var.trace_add(
            "write", lambda *a: self._refresh_audio_list())
        self._audio_dup_groups = None    # [(label, dur_str, [rel, …]), …]
        self._audio_dup_scan_dir = ""    # folder the dup groups came from
        self._audio_dup_scan_id = 0      # bump-counter to drop stale scans
        self._audio_dup_scanning = False
        # Slots whose on-disk bytes differ from the Extract baseline even though
        # the user hasn't assigned a replacement *this* session — i.e. edits
        # already staged by a previous build (or hand-edited).  The Write step
        # repacks these, so the Replace tabs surface + count them too (computed
        # by a background diff so the slot list still appears instantly).  Keyed
        # the same as the slot maps; shared across the three Replace tabs.
        self._audio_changed_on_disk = set()
        self._video_changed_on_disk = set()
        self._image_changed_on_disk = set()
        self._change_scan_id = 0         # bump-counter for the background diff
        # Replace-Video "Convert" column: (rel, replacement, no_conversion,
        # trim) -> "As-is" / "Repackage" / "Re-encode" / "".  A row can cost an
        # ffprobe of the replacement, so it's resolved on a background pass
        # (_video_probe_conv_async) and cached until a pick or flag changes.
        self._video_conv_cache = {}
        # (scan_dir, rel) pairs already given their "this slot holds an
        # unplayable clip" log line, so re-scans don't repeat it all session.
        self._video_unplayable_warned = set()
        self._video_conv_pass_id = 0
        # Preview players: Original + Replacement side-by-side panes
        # (_AudioPreviewPane), built with the tab; None for plugins without it.
        self._audio_pane_orig = None
        self._audio_pane_rep = None
        self._audio_select_job = None    # debounce: load preview on select
        # Queued "play the next row" step from sequential play (see
        # _audio_on_clip_finished) — tracked so anything that stops playback
        # can drop it instead of letting one more clip start.
        self._audio_advance_job = None
        self._audio_current_rel = None   # the slot loaded in the preview panes
        self.audio_search_var.trace_add(
            "write", lambda *a: self._refresh_audio_list())
        self.audio_change_filter_var.trace_add(
            "write", lambda *a: self._refresh_audio_list())
        # Replace-Video tab state (capabilities.replace_video plugins).
        # Mirrors the audio tab, but the preview is an embedded player: a
        # decode thread streams raw frames from ffmpeg to a canvas while
        # ffplay carries the sound, both seeked together.
        self.video_search_var = tk.StringVar()
        # Change-state filter — mirrors the audio + image dropdown (a tester).
        self.video_change_filter_var = tk.StringVar(value="All")
        self._video_sort = ("#0", False)  # (column_id, descending)
        self.video_trim_var = tk.BooleanVar(value=False)
        # "No conversion": copy the replacement through as-is (it must already be
        # in the slot's format) instead of re-encoding it to match.  Greys out
        # the trim/pad option, which only applies during a re-encode.
        self.video_no_conversion_var = tk.BooleanVar(value=False)
        self.video_status_var = tk.StringVar(value="")
        self._video_slots = []           # list[VideoSlot] from last scan
        self._video_slots_by_rel = {}    # rel_path -> VideoSlot
        self._video_assignments = {}     # rel_path -> replacement file path
        self._video_scan_id = 0          # bump-counter to drop stale scans
        self._video_scan_dir = ""        # folder the current slots came from
        # Preview players: Original + Replacement side-by-side panes
        # (_VideoPreviewPane), built with the tab; None for plugins without it.
        self._video_pane_orig = None
        self._video_pane_rep = None
        self._video_select_job = None    # debounce: load preview on select
        self._video_current_rel = None   # slot loaded in the preview panes
        self.video_search_var.trace_add(
            "write", lambda *a: self._refresh_video_list())
        self.video_change_filter_var.trace_add(
            "write", lambda *a: self._refresh_video_list())
        # Replace-Image tab state (capabilities.replace_image plugins).
        # Mirrors the video tab, but the preview is a single static thumbnail
        # on a canvas — no embedded player / threads / ffmpeg / seek bar.
        self.image_search_var = tk.StringVar()
        self._image_sort = ("#0", False)  # (column_id, descending)
        self.image_status_var = tk.StringVar(value="")
        # List-view controls: the change-state filter (All / Changed /
        # Unchanged), and group the rows under their scene/animation container
        # (Stern manifests; every uncovered slot falls back to its parent
        # folder).  Persisted per assets folder with the other Replace toggles
        # (see _save_staged_changes / _populate_image_after_scan).
        self.image_change_filter_var = tk.StringVar(value="All")
        self.image_group_by_scene_var = tk.BooleanVar(value=False)
        self._image_slots = []           # list[ImageSlot] from last scan
        self._image_slots_by_rel = {}    # rel_path -> ImageSlot
        self._image_assignments = {}     # rel_path -> replacement file path
        # Manifest-derived grouping from the last scan (see
        # _scan_image_groups): rel_path -> (group_key, label_base, order).
        self._image_groups = {}
        self._image_group_occ = {}       # rel_path -> on-card occurrence count
        # rel_path -> every container it occurs in (home first); a shared
        # radium image has several.  Search/grouping use it so a scene id
        # finds its images even when they're filed under another scene.
        self._image_groups_all = {}
        # group_key(lower) -> the part of the key that DISTINGUISHES it from
        # its siblings (common card-path prefix stripped) — what the search
        # matches instead of the raw key.  See _compute_image_key_tails.
        self._image_group_key_tails = {}
        # User-authored display names for scene groups (group_key -> name,
        # <=50 chars) — the vendor's own element names are mostly
        # "unnamed_instance_N" (a tester).  Persisted in the staged-changes
        # sidecar per assets folder.
        self._image_group_tags = {}
        # "Source" column filter: All sources / File / Scene texture / Radium
        # / Glyph.
        self.image_source_filter_var = tk.StringVar(value="All sources")
        self.image_source_filter_var.trace_add(
            "write", lambda *a: self._refresh_image_list())
        self._image_scan_id = 0          # bump-counter to drop stale scans
        self._image_scan_dir = ""        # folder the current slots came from
        # Tk PhotoImage refs (must stay alive while drawn on the canvases).
        self._image_preview_img_orig = None
        self._image_preview_img_rep = None
        self._image_current_rel = None   # slot shown in the static preview
        self.image_search_var.trace_add(
            "write", lambda *a: self._refresh_image_list())
        self.image_change_filter_var.trace_add(
            "write", lambda *a: self._refresh_image_list())
        self.image_group_by_scene_var.trace_add(
            "write", lambda *a: self._refresh_image_list())
        # Replace-Text tab state (capabilities.replace_text plugins).  Unlike the
        # audio/video/image tabs (which hold in-memory assignments staged at
        # build), text edits persist straight back to text/strings.tsv, so the
        # model here IS the manifest: each row is {path, original, replacement}
        # ('' replacement = unchanged), saved on every Apply.
        self.text_search_var = tk.StringVar()
        self.text_status_var = tk.StringVar(value="")
        self.text_new_var = tk.StringVar()      # edit-panel "New text" entry
        self.text_budget_var = tk.StringVar(value="")   # "N / M bytes"
        self.text_apply_all_var = tk.BooleanVar(value=False)
        # Same Show dropdown the audio/video/image tabs have (batch 29 asked
        # for it here too), plus a Scene one: on a card this size the useful
        # question is "just this scene" or "just the game program".
        self.text_change_filter_var = tk.StringVar(value="All")
        self.text_scene_filter_var = tk.StringVar(value=self._TEXT_SCENE_ALL)
        self._text_rows = []             # list[{path, original, replacement}]
        self._text_scan_dir = ""         # folder the rows were loaded from
        self._text_scan_id = 0           # bump-counter (parity w/ other tabs)
        self._text_current_iid = None    # selected row iid (str(index))
        self._text_sort = ("#0", False)  # (column_id, descending)
        # Scene dropdown/Name column state: {display: scene path} and its
        # inverse, rebuilt on every list refresh; the friendly names are the
        # SAME store the Images tab's "Rename group…" writes.
        self._text_scene_choices = {}
        self._text_scene_displays = {}
        self._text_scene_names = {}      # {"rad::<card path>": name}
        self.text_search_var.trace_add(
            "write", lambda *a: self._refresh_text_list())
        self.text_change_filter_var.trace_add(
            "write", lambda *a: self._refresh_text_list())
        self.text_scene_filter_var.trace_add(
            "write", lambda *a: self._refresh_text_list())
        self.text_new_var.trace_add(
            "write", lambda *a: self._text_update_budget())
        # Williams-only: "Use PinMAME runtime capture" toggle on the
        # Extract tab.  When ON, the Extract button kicks off the
        # libpinmame-driven capture pipeline (composed cinematics +
        # audio) instead of the static asset extractor.
        # "Basic extract" — the static ROM asset bitmap scanner.  On
        # by default.  Users with limited disk who only want the
        # PinMAME capture cinematics can untick this.
        self.static_extract_var = tk.BooleanVar(value=True)
        self.capture_mode_var = tk.BooleanVar(value=False)
        # 180s gives the scripted gameplay tour (18-21 moments per
        # rich game) enough time to play through without truncating
        # the final scenes.  Plus ~25s boot/credit/start overhead.
        self.capture_duration_var = tk.StringVar(value="180")
        self.capture_gameplay_var = tk.BooleanVar(value=True)
        # CGC-only: "Generate callouts.csv after Extract" toggle on the
        # Extract tab.  When ON, a successful Extract triggers the
        # transcribe pipeline against the output folder.  Default OFF
        # because the model download (~75 MB) is opt-in.
        # When ON, the transcribe pass also renames each speech WAV to
        # "<original> - <transcript>.wav" (Write picks up the renamed files via
        # prefix-matching in _diff_assets, so the round trip still works).  The
        # "Auto-name call-outs" checkbox drives both transcribe + rename, so
        # this just mirrors transcribe_var now (kept so app.py reads one flag).
        self.transcribe_var = tk.BooleanVar(value=False)
        # Music ID (Stern band pins): when ON, a successful Extract chains an
        # online AcoustID + MusicBrainz lookup of each full music track and
        # renames it by song title (preferring the pin's band).
        self.music_id_var = tk.BooleanVar(value=False)
        # Length-prefixed extract names (capabilities.audio_duration_names):
        # when ON, extracted audio is named "01m22s235 - idx0001.wav" so a
        # name sort orders by play length — the stable key for lining sounds
        # up across firmware versions, where slot indexes shift (a tester).
        self.duration_names_var = tk.BooleanVar(value=False)
        # Whether the currently-selected extract input is a game whose
        # audio we can export (drives the Auto-transcribe controls +
        # the "Extract audio" phase).  Re-probed on every input change;
        # True when no file is selected yet so the UI isn't pre-hidden.
        self._extract_audio_supported = True
        # CGC-only: "Decode DMD scenes (experimental)" toggle on the
        # Extract tab.  When ON, the Extract pipeline decodes the
        # bundled Williams WPC ROM into PNG scenes + MP4 animations
        # under output_dir/dmd/.  Default OFF -- experimental and slow.
        self.decode_dmd_var = tk.BooleanVar(value=False)

        # BOF-only (capabilities.write_version_date): the "Update version
        # date" control on the Write tab.  Auto (default) lets the pipeline
        # stamp one day past the installed code; unticking it enables the
        # entry so the user can force an explicit YYYY.MM.DD (e.g. to
        # reinstall official code over a higher-dated mod).  The entry
        # always shows the concrete date — auto-computed from the assets
        # folder when Auto is on, user-typed when it's off.
        self.write_version_auto_var = tk.BooleanVar(value=True)
        self.write_version_date_var = tk.StringVar()
        # Stock baseline date read from the assets folder (for the hint).
        self._write_version_baseline = None

        # JJP-only (capabilities.asset_filters): per-category Extract
        # checkboxes — Graphics / Sounds / File System.  Match the
        # standalone JJP decryptor's defaults: assets on, full
        # filesystem dump off (it's the slow path).  Plumbed into the
        # JJP pipeline as ``extract_graphics`` / ``extract_sounds`` /
        # ``full_dump``.  Hidden for plugins without the capability.
        self.extract_graphics_var = tk.BooleanVar(value=True)
        self.extract_sounds_var = tk.BooleanVar(value=True)
        self.extract_filesystem_var = tk.BooleanVar(value=False)

        # JJP-only (capabilities.dongle_extract): advanced "Decrypt using the
        # game's HASP dongle" checkbox.  Off by default; when on, app.py routes
        # the ISO extract through the dongle pipeline (runs the game under an
        # LD_PRELOAD shim so it decrypts itself via the plugged-in key) — the
        # escape hatch for a title whose cipher isn't reverse-engineered yet.
        # Hidden for plugins without the capability.
        self.extract_dongle_var = tk.BooleanVar(value=False)

        # Generic per-type Extract selection (capabilities.extract_categories):
        # one default-on checkbox per (key, label) the plugin advertises, built
        # dynamically in apply_manufacturer().  Stern uses Audio/Video/Images/
        # Text; app.py reads these and passes extract_categories={key: bool} to
        # the extract factory.  key -> BooleanVar.
        self._extract_category_vars = {}
        # Persisted Extract-tab options for the current manufacturer
        # (a tester: the auto-name checkboxes "do not stick between
        # sessions").  Set via set_extract_options() on mfr switch; also
        # re-applied inside apply_manufacturer() because the category
        # checkboxes are rebuilt (default-on) on every apply/era switch.
        self._saved_extract_options = {}

        # JJP-only (capabilities.direct_ssd): "From ISO / From SSD"
        # radio toggles between the file picker and the physical-drive
        # picker.  Default "iso" so plugins without direct_ssd see no
        # change.  Drive var holds the selected drive's device_path
        # (the value the pipeline accepts); drive_display_var is the
        # combobox's selected label.  Partition override is the
        # optional escape hatch — leave blank to auto-discover.
        self.extract_input_source_var = tk.StringVar(value="iso")
        self.extract_drive_var = tk.StringVar()
        self.extract_drive_display_var = tk.StringVar()
        self.extract_partition_override_var = tk.StringVar()
        self.write_input_source_var = tk.StringVar(value="iso")
        self.write_drive_var = tk.StringVar()
        self.write_drive_display_var = tk.StringVar()
        self.write_partition_override_var = tk.StringVar()
        # Caches of PhysicalDrive — kept in step with the combobox so
        # selecting a label can look up its device_path without
        # re-enumerating.  Refilled by _refresh_drives.
        self._extract_drives_cache = []
        self._write_drives_cache = []

        # Cross-manufacturer auto-detect: when the current mfr doesn't
        # recognise a browsed file but exactly one other mfr does, we
        # store that mfr here so a click on the badge can switch to it.
        self._extract_suggested_mfr = None
        self._write_suggested_mfr = None

        # Per-mfr prereq indicators: name -> dict(label, tooltip, prereq).
        # Rebuilt by reset_prereqs() each time the manufacturer changes.
        self._prereq_indicators = {}

        # Replace-tab Scan/Browse buttons (tab_key -> ttk.Button), registered
        # as each tab is built so _set_tab_scanning() can blank the list, run a
        # scanning animation, and turn Scan into Cancel while a (possibly slow,
        # network-share) scan runs.
        self._scan_buttons = {}
        self._browse_buttons = {}
        self._scan_cmds = {}            # tab_key -> Scan command (restore after Cancel)
        self._scan_idle_labels = {}     # tab_key -> idle button label (default "Scan")
        self._scan_spinner_after = {}   # tab_key -> after-id of the running spinner
        self._scan_msgs = {}            # tab_key -> message the spinner animates
        # tab_key -> why the next scan was started, appended to its log line
        # and consumed by it (batch 22 — an unexplained scan reads as the app
        # doing needless work).
        self._scan_reasons = {}
        self._scan_empty_font = {}      # tab_key -> normal empty-label font to restore

        # Intro/description labels whose wraplength tracks the window width so
        # they reflow wider instead of leaving dead space when the window grows
        # (each entry: (label, margin, minimum)).
        self._responsive_wrap_labels = []

        self._build_ui()
        self._init_phase_steps()
        self._apply_theme(self._current_theme)

        self.extract_input_var.trace_add("write", self._update_extract_badge)
        self.write_upd_var.trace_add("write", self._update_write_badge)
        # Batch 19 field collapse: the Extract tab is the project's single
        # source of truth.  Its Input IS the stock image (the Write tab's
        # Original mirrors it read-only) and its Project Folder IS the
        # shared assets folder (every Replace/Write/Mod-pack row mirrors it
        # read-only).  One-way mirrors — the mirrored vars have no other
        # writers left in the UI.
        self.extract_input_var.trace_add(
            "write", lambda *_: self._mirror_stock_image())
        self.extract_output_var.trace_add(
            "write", lambda *_: self._mirror_project_folder())
        # Build output derives from the project folder (<project>/build, or
        # the anchor's build_dir override) — tracked like the File Name
        # auto-fill so a custom location is never clobbered.
        self._write_output_auto = ""
        self.write_assets_var.trace_add(
            "write", lambda *_: self._derive_build_output())
        # Default the Write Output Folder off the original image's location
        # the first time an original is picked (a tester: the box starting
        # blank forced an extra Browse; the -modified suffix already prevents
        # name clashes with the source).
        self.write_upd_var.trace_add(
            "write", lambda *_: self._maybe_default_write_output())
        self.write_upd_var.trace_add(
            "write", lambda *_: self._update_write_filename())
        self.write_output_var.trace_add(
            "write", lambda *_: self._update_write_filename())
        # A user edit to the name box only affects the collision hint — the
        # default-fill logic in _update_write_filename backs off once the box
        # diverges from the auto value, so this never fights the typing.
        self.write_filename_var.trace_add(
            "write", lambda *_: self._update_write_filename_hint())
        # Re-scan the Modified Files Preview whenever the assets
        # folder changes, but only if the user is actually looking at
        # the SSD-mode Write tab — otherwise we'd be churning hashing
        # work on every keystroke into the Browse field.
        self.write_assets_var.trace_add(
            "write", lambda *_: self._maybe_rescan_write_preview())
        self.write_assets_var.trace_add(
            "write", lambda *_: self._refresh_write_assets_warning())
        self.write_assets_var.trace_add(
            "write", lambda *_: self._refresh_write_version_field())

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root

        # ---- Update-available banner (top of window) ----------------
        # Persistent across picker ↔ working-view switches; only
        # visible once the GitHub update check turns up a newer
        # release.  Lives ABOVE the back/title row so it's
        # impossible to miss regardless of which view is showing.
        # Dismissible per-session via the × button; reappears on
        # next launch if still applicable.
        self._build_update_banner(root)
        # Amber "source image changed" banner — shown on entry to a Replace /
        # Write tab when the assets folder's recorded source image no longer
        # matches what's on disk (e.g. the user reverted the .raw).  Created
        # here, packed on demand by _refresh_stale_source_banner().
        self._build_stale_source_banner(root)

        # ---- Top bar: Back, title, theme toggle ----------------------
        top = ttk.Frame(root)
        self._top_bar = top  # banner uses this as `before=` anchor
        top.pack(fill=tk.X, padx=10, pady=(8, 0))
        # Back-to-picker button — hidden until the user has picked a
        # manufacturer.  A house glyph rather than "< Back" so it matches the
        # header's ?/⚙ icon set (a tester): Segoe MDL2 "Home" on Windows
        # (same font/style as the gear — see the glyph comment below), text
        # "⌂" elsewhere.  The tooltip carries the words the icon dropped.
        home_glyph = "" if sys.platform == "win32" else "⌂"
        self._back_btn = self._make_round_icon(
            top, home_glyph, "#e67e22", "#ec9540",
            "Back to game selection", self._handle_back)
        # not packed yet — show_mfr_view() does that
        self._title_lbl = ttk.Label(
            top, text=self._app_title,
            font=(_SANS_FONT, 13, "bold"))
        self._title_lbl.pack(side=tk.LEFT)
        # Era switcher — a segmented row of clickable pills right of the title,
        # shown only for multi-era plugins (Stern Spike 2 / Whitestar).  The
        # pills are (re)built per-manufacturer in apply_manufacturer(); the frame
        # is packed by show_mfr_view() and hidden in the picker.
        self._era_badges_frame = ttk.Frame(top)
        self._era_badge_widgets = {}   # era_key -> tk.Label pill
        # "⚙" settings menu — the one always-visible header control (a tester:
        # the old Check-for-updates / Manage-disk-space / theme button row was
        # permanent top-bar clutter for things you touch once in a while).
        # Everything app-wide lives in its dropdown: theme, update check, disk
        # space, voice-recognition quality, prerequisites.
        # Glyphs: on Windows the header icons come from Segoe MDL2 Assets —
        # the OS's own Settings gear (U+2699 in Segoe UI renders as the
        # flowery emoji gear) and its matching Help "?".  Elsewhere: text
        # glyphs, ⚙ forced to text presentation.  Each is drawn white on a
        # _make_round_icon color circle (David: round colorful icons).
        if sys.platform == "win32":
            self._gear_glyph = ""          # MDL2 "Settings" gear
            self._help_glyph = ""          # MDL2 "Help" question mark
        else:
            self._gear_glyph = "⚙︎"    # text-presentation ⚙
            self._help_glyph = "?"
        self._gear_btn = self._make_round_icon(
            top, self._gear_glyph, "#7e57c2", "#9575cd",
            "Settings", self._open_settings_menu)
        self._gear_btn.pack(side=tk.RIGHT)
        # Project button — the fourth round header icon (batch 19).  Blue
        # folder, LEFT cluster right of the home button (David: it feels at
        # home there — it's navigation/context, not a settings-side
        # control).  Projects moved OUT of the gear: the gear's charter is
        # app-wide once-in-a-while settings, a project is the all-day
        # working context (a tester point 1 — and he named "an icon" as
        # the expected shape).  Always visible, INCLUDING the picker screen
        # (where home hides): Open/Recent + auto-load jump straight into a
        # project without picking a manufacturer first.
        # U+E8B7 = Segoe MDL2 "Folder" (an escape, not a literal, so the
        # private-use char cannot be dropped by an editor).  Off Windows the
        # folder is DRAWN rather than typed: the U+1F5C0 that used to be here
        # is absent from macOS's system font, so the button rendered as an
        # empty missing-glyph box.  See widgets.draw_folder_icon.
        win_icons = sys.platform == "win32"
        self._project_btn = self._make_round_icon(
            top, "\ue8b7" if win_icons else "", "#2980b9", "#4aa3df",
            "Project", self._open_project_menu,
            draw=None if win_icons else draw_folder_icon)
        # before=title puts it ahead of the title in the LEFT pack order;
        # show_mfr_view packs the home button before=this, giving
        # [home] [project] [title] in the working view and [project] [title]
        # on the picker.
        self._project_btn.pack(side=tk.LEFT, padx=(0, 8),
                               before=self._title_lbl)
        # Notification marks over the gear circle's corners: red dot =
        # update available, amber dot = staging cleanup pending.  Composited
        # into the gear's anti-aliased disc image by _set_icon_dot (an oval
        # item on top rendered jagged) — hidden until _refresh_gear_badge
        # adds them; the amounts/details live in the ⚙ menu entries.
        # Same geometry as the old ovals: (16,1)-(23,8) and (16,16)-(23,23).
        self._GEAR_UPDATE_DOT = (19.5, 4.5, 3.5, "#e74c3c")
        self._GEAR_WARN_DOT = (19.5, 19.5, 3.5, "#f39c12")
        # "Check for updates" busy flag — while the GitHub fetch is in flight
        # the menu entry reads "Checking…" and is disabled (the menu is built
        # fresh on every click, so a flag is all the state we need).
        self._update_check_busy = False
        # Disk-staging badge (Windows): "" or a short "⚠ 1.2 GB" suffix shown
        # on the gear button + the Manage-disk-space menu entry when leftover
        # staging is found.
        self._disk_badge_suffix = ""
        # (version, url) once the update check finds a newer release — puts a
        # ● notification on the gear and a Download entry at the top of its
        # menu (persists even after the banner is dismissed).
        self._update_available = None
        # "?" tips button — per-tab help window (a tester: collect the
        # scattered inline tips somewhere a user can pull up on demand).
        # Created here, but packed only in show_mfr_view(): the picker has
        # no tabs so the button would have nothing to explain there.
        self._help_btn = self._make_round_icon(
            top, self._help_glyph, "#27ae60", "#44bd7c",
            "Tips for this tab", self._open_tab_help)
        # The single per-app tips window (a tester round 2: "?" used to
        # stack a new window per click).  Created lazily on first "?" click.
        self._help_window = None
        if sys.platform == "win32":
            # Passive startup check: badge the gear when leftover staging is
            # found (crash/cancel leftovers that need a human to clear).
            # Deferred + backgrounded so it never blocks launch, and it only
            # scans WSL if WSL is already running (never spins it up).
            self.root.after(1500, self._start_disk_badge_check)

        # ---- Picker view (the entry screen) --------------------------
        from .picker import ManufacturerPicker
        self._picker_view = ManufacturerPicker(
            root,
            manufacturers=self._manufacturers,
            on_select=self._on_picker_select,
            theme_fn=lambda: self._current_theme)
        # Packed in show_picker() — leaving the placement for later so
        # the App can decide the initial view.

        # ---- Manufacturer working view (decryption UI) ---------------
        # Everything below this is parented to _mfr_view so we can hide
        # the whole thing with one pack_forget() and show the picker
        # instead.  Created but not packed; show_mfr_view() does that.
        #
        # As of v0.7.11 the working view lives inside a vertical
        # scrollable canvas so tall content (macOS FDA banner +
        # admin banner + capability matrix + log) can't push the
        # log frame below the visible area on smaller windows.  When
        # the content fits the window, the scrollbar stays hidden;
        # when it doesn't, the bar appears on the right and the
        # user can scroll the whole working view.
        self._mfr_view_wrapper = ttk.Frame(root)
        self._mfr_view_canvas = tk.Canvas(
            self._mfr_view_wrapper,
            highlightthickness=0, borderwidth=0)
        self._mfr_view_scroll = ttk.Scrollbar(
            self._mfr_view_wrapper, orient="vertical",
            command=self._mfr_view_canvas.yview)
        self._mfr_view_canvas.configure(
            yscrollcommand=self._mfr_view_scroll.set)
        self._mfr_view_canvas.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Scrollbar is packed-on-demand by ``_update_mfr_scroll``.
        self._mfr_view = ttk.Frame(self._mfr_view_canvas)
        self._mfr_view_id = self._mfr_view_canvas.create_window(
            (0, 0), window=self._mfr_view, anchor="nw")

        def _update_mfr_scroll(_e=None):
            bbox = self._mfr_view_canvas.bbox("all")
            if bbox is None:
                return
            self._mfr_view_canvas.configure(scrollregion=bbox)
            visible = self._mfr_view_canvas.winfo_height()
            content_h = bbox[3] - bbox[1]
            if content_h > visible + 2:
                self._mfr_view_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                self._mfr_view_scroll.pack_forget()

        self._mfr_view.bind("<Configure>", _update_mfr_scroll)

        def _resize_mfr_view(e):
            # Force the inner canvas-window to be at least as tall as
            # the canvas itself.  Otherwise the inner frame keeps its
            # natural content height, leaving any extra canvas area
            # painted in the canvas's bg — and, more importantly, the
            # log frame (which packs with expand=True) has nothing
            # extra to expand into.  When content is naturally taller
            # than the canvas (small window), keep the content size
            # so scrolling still works.
            inner_h = self._mfr_view.winfo_reqheight()
            self._mfr_view_canvas.itemconfig(
                self._mfr_view_id, width=e.width,
                height=max(e.height, inner_h))
            # Reflow the registered intro/description labels to the new width so
            # the per-tab help text uses the full window instead of leaving a
            # dead band on the right when widened (a tester).
            for lbl, margin, minimum in self._responsive_wrap_labels:
                try:
                    lbl.configure(wraplength=max(minimum, e.width - margin))
                except tk.TclError:
                    pass
            _update_mfr_scroll()

        self._mfr_view_canvas.bind("<Configure>", _resize_mfr_view)

        # Mouse-wheel scroll the outer view when the pointer is over
        # any non-scrollable region.  The inner log Text widget has
        # its own scrollbar, so we explicitly forward wheel events
        # ONLY when the pointer isn't inside the log frame — keeps
        # log scrolling intuitive when there's a long extraction
        # history to read.
        def _on_mousewheel(event):
            try:
                widget_under = self.root.winfo_containing(
                    event.x_root, event.y_root)
            except Exception:
                widget_under = None
            w = widget_under
            while w is not None:
                if w is getattr(self, "_log_text", None):
                    return  # let the log handle its own wheel
                w = getattr(w, "master", None)
            # Cross-platform wheel: macOS / Windows send delta; X11
            # uses Button-4 / Button-5.
            if event.num == 5 or getattr(event, "delta", 0) < 0:
                self._mfr_view_canvas.yview_scroll(1, "units")
            elif event.num == 4 or getattr(event, "delta", 0) > 0:
                self._mfr_view_canvas.yview_scroll(-1, "units")

        self._mfr_view_canvas.bind_all(
            "<MouseWheel>", _on_mousewheel, add="+")
        self._mfr_view_canvas.bind_all(
            "<Button-4>", _on_mousewheel, add="+")
        self._mfr_view_canvas.bind_all(
            "<Button-5>", _on_mousewheel, add="+")
        mv = self._mfr_view

        # mfr_var stays for compatibility (some helpers read it) — but
        # there's no combobox any more; the title bar shows the choice.
        self.mfr_var = tk.StringVar()

        # Per-manufacturer prerequisite indicators.
        self._prereqs_frame = ttk.LabelFrame(mv, text="Prerequisites")
        self._prereqs_inner = ttk.Frame(self._prereqs_frame)
        self._prereqs_inner.pack(side=tk.LEFT, fill=tk.X, expand=True,
                                 padx=4, pady=4)
        # The Re-check / Install Missing buttons are Windows/Linux-only.  On
        # the frozen macOS app there's nothing to install -- every Python dep
        # plus ffmpeg (via imageio-ffmpeg) is bundled, and a frozen .app can't
        # pip-install anything anyway, so macOS "Install Missing" only ever
        # popped a dead-end Docker/Homebrew dialog.  Drop both buttons there;
        # the prerequisite indicators still show (and should all be green).
        if sys.platform != "darwin":
            prereq_btns = ttk.Frame(self._prereqs_frame)
            prereq_btns.pack(side=tk.RIGHT, padx=4, pady=4)
            # Side by side (not stacked) so the Prerequisites frame is one row
            # shorter — that height goes to the log below (a tester's ask).
            ttk.Button(
                prereq_btns, text="Re-check",
                command=lambda: (self._on_recheck_prereqs()
                                 if self._on_recheck_prereqs else None)
            ).pack(side=tk.LEFT)
            ttk.Button(
                prereq_btns, text="Install Missing",
                command=lambda: (self._on_install_prereqs()
                                 if self._on_install_prereqs else None)
            ).pack(side=tk.LEFT, padx=(4, 0))

        # Tabs
        self._notebook = ttk.Notebook(mv)
        self._notebook.pack(fill=tk.X, expand=False, padx=10, pady=(8, 0))

        self._tab_extract = ttk.Frame(self._notebook)
        self._tab_audio = ttk.Frame(self._notebook)
        self._tab_video = ttk.Frame(self._notebook)
        self._tab_image = ttk.Frame(self._notebook)
        self._tab_text = ttk.Frame(self._notebook)
        self._tab_write = ttk.Frame(self._notebook)
        self._tab_modpack = ttk.Frame(self._notebook)
        self._tab_partition = ttk.Frame(self._notebook)
        self._tab_settings = ttk.Frame(self._notebook)
        self._tab_compare = ttk.Frame(self._notebook)
        self._tab_emulate = ttk.Frame(self._notebook)

        # Order: Extract → the Replace tabs → Default Settings (set defaults
        # before building) → Write → Mod Pack → Partitions.  Display labels are
        # short so the strip fits a normal window without sideways scroll; all
        # tab LOGIC keys off the stable identifiers in ``self._tab_keys`` (see
        # _tab_key), not the visible text, so labels stay cosmetic.
        _tabs = [
            (self._tab_extract, "Extract", "Extract"),
            (self._tab_audio, "Audio", "Replace Audio"),
            (self._tab_video, "Video", "Replace Video"),
            (self._tab_image, "Images", "Replace Images"),
            (self._tab_text, "Text", "Replace Text"),
            (self._tab_settings, "Defaults", "Default Settings"),
            (self._tab_write, "Write", "Write"),
            (self._tab_modpack, "Mod Pack", "Mod Pack"),
            (self._tab_partition, "Partitions", "Partition Explorer"),
            (self._tab_compare, "Compare", "Compare"),
            (self._tab_emulate, "Emulate", "Emulate"),
        ]
        self._tab_keys = {}
        for _frame, _label, _key in _tabs:
            self._notebook.add(_frame, text=" %s " % _label)
            self._tab_keys[str(_frame)] = _key

        self._build_extract_tab()
        self._build_audio_tab()
        self._build_video_tab()
        self._build_image_tab()
        self._build_text_tab()
        self._build_write_tab()
        self._build_modpack_tab()
        self._build_partition_tab()
        self._build_settings_tab()
        self._build_compare_tab()
        self._build_emulate_tab()

        # Phase indicators + progress bar
        status_frame = ttk.Frame(mv)
        # Kept as an anchor so the live DMD preview can be packed directly
        # above it (the preview lives in mv, not the notebook tab).
        self._status_frame = status_frame
        status_frame.pack(fill=tk.X, padx=10, pady=(4, 0))

        self._extract_phases_frame = ttk.Frame(status_frame)
        self._extract_phases_frame.pack(fill=tk.X)
        self._write_phases_frame = ttk.Frame(status_frame)

        self._progress_bar = ttk.Progressbar(status_frame, mode="determinate",
                                             maximum=100)
        self._progress_bar.pack(fill=tk.X, pady=(4, 2))

        status_row = ttk.Frame(status_frame)
        status_row.pack(fill=tk.X)
        self._status_label = ttk.Label(status_row, text="Ready",
                                       font=(_SANS_FONT, 9))
        self._status_label.pack(side=tk.LEFT)
        self._elapsed_label = ttk.Label(status_row, text="",
                                        font=(_SANS_FONT, 9))
        self._elapsed_label.pack(side=tk.RIGHT)

        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Log section.  We keep ONE log LabelFrame, but its contents
        # (the Text widget + its scrollbar) are swapped per-manufacturer
        # by _swap_log_widget() so each mfr has its own scrollback.
        self._log_frame = ttk.LabelFrame(mv, text="Log")
        self._log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 8))

    def _build_extract_tab(self):
        f = self._tab_extract
        pad = {"padx": 10, "pady": 4}

        # NOTE: a per-mfr description label used to live here, but the
        # picker page already shows every game the mfr handles, and
        # the prereqs row above the tabs already lists runtime tools,
        # so it was redundant + got clipped when the text was long.

        # JJP-only (capabilities.direct_ssd): "From ISO" / "From SSD"
        # radio toggles between the file picker below and the
        # physical-drive picker frame.  Hidden in apply_manufacturer
        # for plugins without direct_ssd.  Layout mirrors the
        # standalone JJP decryptor so users moving over see the same
        # shape.
        self._extract_source_frame = ttk.Frame(f)
        self._extract_iso_radio = ttk.Radiobutton(
            self._extract_source_frame, text="From ISO",
            value="iso",
            variable=self.extract_input_source_var,
            command=lambda: self._on_input_source_change("extract"),
        )
        self._extract_iso_radio.pack(side=tk.LEFT, padx=(10, 12))
        self._extract_ssd_radio = ttk.Radiobutton(
            self._extract_source_frame, text="From SSD",
            value="ssd",
            variable=self.extract_input_source_var,
            command=lambda: self._on_input_source_change("extract"),
        )
        self._extract_ssd_radio.pack(side=tk.LEFT)

        # ISO file-picker row — shown when source == "iso".
        self._extract_input_row = ttk.Frame(f)
        self._extract_input_lbl = ttk.Label(
            self._extract_input_row, text="Input:", width=14, anchor=tk.W)
        self._extract_input_lbl.pack(side=tk.LEFT)
        self._path_combo(self._extract_input_row,
                         self.extract_input_var, "extract_input").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        # ⓘ — round colorful badge opening the Image Info window for the
        # picked file; sits between the path box and Browse (David).
        self._make_info_badge(self._extract_input_row,
                              self.extract_input_var).pack(
            side=tk.LEFT, padx=(6, 0))
        ttk.Button(self._extract_input_row, text="Browse...",
                   command=self._browse_extract_input).pack(
            side=tk.LEFT, padx=(6, 0))
        self._extract_input_row.pack(fill=tk.X, **pad)

        # SSD drive-picker row — shown when source == "ssd".  Created
        # but not packed; _on_input_source_change toggles it in.
        self._extract_drive_row = ttk.Frame(f)
        ttk.Label(self._extract_drive_row,
                  text="Game SSD:", width=14, anchor=tk.W).pack(side=tk.LEFT)
        self._extract_drive_combo = ttk.Combobox(
            self._extract_drive_row,
            textvariable=self.extract_drive_display_var,
            state="readonly")
        self._extract_drive_combo.pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._extract_drive_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._on_drive_selected("extract"))
        ttk.Button(self._extract_drive_row, text="Refresh",
                   command=lambda: self._refresh_drives("extract")).pack(
            side=tk.LEFT, padx=(8, 0))

        # We previously surfaced a "Force partition #" entry here, but
        # it spooked users — a numeric override field next to a
        # red-warning panel makes the SSD flow feel risky.  The
        # content-verify loop in DirectSSDDecryptPipeline.\
        # _mount_ssd_windows now tries every Linux candidate in size
        # order, so the auto-pick handles every drive layout we've
        # seen.  If something exotic comes up we can re-expose the
        # override later.

        # Red warning shown only in SSD mode — mirrors the standalone
        # JJP decryptor's prompt.  Pulling an SSD that's still bolted
        # into a powered-on machine risks the host filesystem and the
        # SSD; remind users every time.
        self._extract_ssd_warn = ttk.Label(
            f,
            text="⚠ Remove the SSD from the pinball machine before "
                 "connecting. Always keep the original ISO as a backup.",
            foreground="#f44747",
            font=(_SANS_FONT, 9))

        # Elevation warning — Direct-SSD on Windows needs admin (both
        # Set-Disk and wsl --mount are gated by Windows itself).
        # Designed to be impossible to miss: bold heading, multi-line
        # how-to-fix, contrasting red background.  Shown only when
        # SSD mode is selected AND the app isn't running as admin;
        # the Extract button is *disabled* in that state so users
        # can't kick off a doomed run.
        self._extract_admin_frame = self._build_admin_warning_frame(f)
        # macOS Full Disk Access guidance — analogous warning for the
        # other Direct-SSD-blocking platform constraint.  See the
        # helper for the full explanation.
        self._extract_macos_fda_frame = (
            self._build_macos_fda_warning_frame(f))

        # Detect-badge row — now warnings-only ("Looks like…", "Not
        # recognised…", extract-only): the happy-path "Detected: <game>" moved
        # to the title bar (batch 20).  Wrapped in a row with a
        # field-label-width spacer so its left edge lines up under the path
        # entry fields (not the labels) — see the path rows above, which all
        # lead with a width=14 anchor=W label.  The ROW is the positioned
        # element; built UNPACKED — _sync_badge_row packs it only while the
        # badge carries text.
        self._extract_badge_row = ttk.Frame(f)
        ttk.Label(self._extract_badge_row, text="", width=14).pack(side=tk.LEFT)
        self._extract_badge = ttk.Label(self._extract_badge_row, text="",
                                        font=(_SANS_FONT, 9, "italic"))
        self._extract_badge.pack(side=tk.LEFT, anchor=tk.W)
        self._extract_badge.bind(
            "<Button-1>", lambda _e: self._auto_switch("extract"))
        self._extract_badge.bind(
            "<Enter>", lambda _e: self._update_badge_cursor("extract", True))
        self._extract_badge.bind(
            "<Leave>", lambda _e: self._update_badge_cursor("extract", False))

        self._extract_output_row_ref = ttk.Frame(f)
        self._extract_output_row_ref.pack(fill=tk.X, **pad)
        # "Project Folder", not "Output Folder" (batch 19): this folder IS
        # the project — extraction lands here, every Replace/Write tab works
        # out of it (their rows are read-only mirrors of this one), and a
        # folder containing a project anchor auto-loads that project.  That
        # explanation lives in the Browse tooltip + the "?" help now — the
        # always-on caption under the row burned a line after first read
        # (batch 20).
        _proj_lbl = ttk.Label(self._extract_output_row_ref,
                              text="Project Folder:", width=14, anchor=tk.W)
        _proj_lbl.pack(side=tk.LEFT)
        _proj_tip = ("The project folder — extraction lands here, and every "
                     "other tab works out of it. A folder that already holds "
                     "a project loads that project when picked.")
        _Tooltip(_proj_lbl, _proj_tip, lambda: self._current_theme)
        self._path_combo(self._extract_output_row_ref,
                         self.extract_output_var, "extract_output").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        # ⓘ — project stats (asset counts, size on disk, change counts,
        # start date) for the current project folder; mirrors the Card
        # image row's ⓘ badge (batch 20).
        self._make_round_icon(
            self._extract_output_row_ref, "i", self._INFO_BADGE_FILL,
            self._INFO_BADGE_HOVER, "Stats about this project folder",
            self._open_project_info, size=18,
            font=("Georgia", 10, "bold italic")).pack(
            side=tk.LEFT, padx=(6, 0))
        _browse_btn = ttk.Button(self._extract_output_row_ref,
                                 text="Browse...",
                                 command=self._browse_extract_output)
        _browse_btn.pack(side=tk.LEFT, padx=(6, 0))
        _Tooltip(_browse_btn, _proj_tip, lambda: self._current_theme)

        # NOTE: a red "Output folder is not empty — files may be overwritten."
        # label used to live here, but the Extract click already raises a
        # confirm dialog for that case, so the always-on inline warning was
        # redundant noise eating a row of vertical space (a tester).

        # NOTE: a tall yellow "About BOF Extract" callout used to live here,
        # walking through the custom-PCK conversion Extract does behind the
        # scenes.  It was reference material, not something you act on while
        # filling in two paths, and it pushed the actual controls up off the
        # window (a tester).  The same explanation now lives in the README's
        # Barrels of Fun section.
        #
        # JJP-only (capabilities.asset_filters): per-category Extract
        # filters.  Mirrors the standalone JJP decryptor: an "Extract:"
        # label followed by Graphics / Sounds / File System
        # checkboxes inline.  Hidden in apply_manufacturer() for
        # plugins without the capability.  Built but not packed.
        self._asset_filters_frame = ttk.Frame(f)
        ttk.Label(
            self._asset_filters_frame, text="Extract:",
            font=(_SANS_FONT, 9)).pack(side=tk.LEFT, padx=(10, 8))
        ttk.Checkbutton(
            self._asset_filters_frame, text="Graphics",
            variable=self.extract_graphics_var,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            self._asset_filters_frame, text="Sounds",
            variable=self.extract_sounds_var,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            self._asset_filters_frame, text="File System",
            variable=self.extract_filesystem_var,
        ).pack(side=tk.LEFT, padx=(0, 12))

        # JJP-only (capabilities.dongle_extract): advanced dongle-decrypt row.
        # Built unpacked; shown in apply_manufacturer() for plugins that expose
        # it.  Toggling it re-labels the phase steps (the dongle flow has more
        # phases than the dongle-free one), so it fires the phase refresh.
        self._dongle_extract_frame = ttk.Frame(f)
        ttk.Checkbutton(
            self._dongle_extract_frame,
            text="Decrypt using the game's HASP dongle (advanced — for titles "
                 "not yet supported dongle-free)",
            variable=self.extract_dongle_var,
            command=self._on_dongle_extract_toggle,
        ).pack(side=tk.LEFT, padx=(10, 8))

        # The Extract action button and the inline option checkboxes share one
        # bottom row: the checkbox cluster sits on the left (aligned under the
        # path fields), the Extract button anchors right (under the Browse
        # column).  Created here — unpacked — so the option frames below can
        # parent into the left cluster; the row is packed at the very end of
        # this method (after every option frame exists).
        self._extract_action_row = ttk.Frame(f)
        self._extract_options_row = ttk.Frame(self._extract_action_row)

        # Second, separate "Options:" row for the auto-name / length-prefix
        # cluster (a tester: sharing one row with the category checkboxes
        # AND the Extract button cut the labels off at narrow widths).
        # Packed on demand by _update_extract_options_row_visibility — most
        # non-Stern plugins show none of the three options, and an empty
        # row would leave a stray label.
        self._extract_optnames_row = ttk.Frame(f)
        ttk.Label(self._extract_optnames_row, text="Options:",
                  width=14, anchor=tk.W,
                  font=(_SANS_FONT, 9)).pack(side=tk.LEFT)

        # Generic per-type Extract checkboxes (capabilities.extract_categories).
        # Children are (re)built per-plugin in apply_manufacturer(); built empty
        # here and pack-managed there.  Stern: Audio / Video / Images / Text.
        self._extract_categories_frame = ttk.Frame(self._extract_options_row)

        # Williams-only: extract-mode checkboxes.  Both hidden in
        # apply_manufacturer() for manufacturers without
        # capabilities.capture (other plugins always run their
        # default extract).
        self._basic_extract_frame = ttk.Frame(f)
        self._basic_extract_check = ttk.Checkbutton(
            self._basic_extract_frame,
            text="Basic extract (raw ROM asset bitmaps + animation MP4s)",
            variable=self.static_extract_var,
            command=self._on_extract_mode_toggle)
        self._basic_extract_check.pack(side=tk.LEFT, padx=(24, 8))

        self._capture_frame = ttk.Frame(f)
        self._capture_check = ttk.Checkbutton(
            self._capture_frame,
            text="Use PinMAME runtime capture (composed cinematics + audio)",
            variable=self.capture_mode_var,
            command=self._on_extract_mode_toggle)
        self._capture_check.pack(side=tk.LEFT, padx=(24, 8))
        ttk.Label(
            self._capture_frame, text="Duration (s):",
            font=(_SANS_FONT, 9)).pack(side=tk.LEFT)
        self._capture_dur_entry = ttk.Entry(
            self._capture_frame, textvariable=self.capture_duration_var,
            width=6)
        self._capture_dur_entry.pack(side=tk.LEFT, padx=(4, 0))
        self._capture_gameplay_check = ttk.Checkbutton(
            self._capture_frame,
            text="Simulate gameplay",
            variable=self.capture_gameplay_var)
        self._capture_gameplay_check.pack(side=tk.LEFT, padx=(12, 0))
        self._capture_help = ttk.Label(
            f, text="",
            font=(_SANS_FONT, 9, "italic"),
            foreground="#888888",
            wraplength=620, justify=tk.LEFT)
        self._capture_help.pack(anchor=tk.W, padx=24, pady=(2, 0))

        # ---- Live DMD preview ------------------------------------
        # While the capture pipeline runs, we show the actual DMD
        # frames PinMAME is rendering — invaluable for "is the game
        # in attract, stuck on ball-search, or actually playing?"
        # diagnostics.  The image label is created here but kept
        # hidden until ``on_dmd_frame`` receives the first frame.
        # Parented to the manufacturer view (NOT the Extract tab) so the
        # full-height preview isn't clipped by the fixed-size notebook;
        # it's packed in just above the phase indicators during capture.
        self._dmd_preview_frame = ttk.Frame(self._mfr_view)
        self._dmd_preview_label = tk.Label(
            self._dmd_preview_frame,
            background="#000000",
            borderwidth=1, relief="solid")
        self._dmd_preview_label.pack(side=tk.LEFT, padx=(24, 8))
        self._dmd_preview_caption = ttk.Label(
            self._dmd_preview_frame,
            text="Live DMD (PinMAME)",
            font=(_SANS_FONT, 9, "italic"),
            foreground="#888888")
        self._dmd_preview_caption.pack(side=tk.LEFT, padx=(0, 0),
                                       anchor="s", pady=(0, 4))
        # Latest frame slot — written from the libpinmame display
        # thread (no GIL contention concerns since dict/tuple writes
        # are atomic in CPython).  The Tk after()-pump reads it.
        self._dmd_latest = None      # (data, w, h, depth) or None
        self._dmd_preview_tkimage = None  # PhotoImage retained as ref
        self._dmd_preview_visible = False
        self._dmd_preview_pump_id = None

        # ---- Diagnostic switch matrix (Williams capture mode) ----
        # When PinMAME is running, expose a clickable grid of every
        # defined switch in the active game.  Lets the user manually
        # press switches to see how the ROM responds (useful when
        # the scripted playthrough doesn't trigger expected cinemas).
        self._switch_matrix_frame = ttk.LabelFrame(
            f, text="Switch matrix (click to press)")
        # Wrap the grid in a scrollable Canvas so games with 60+
        # switches (ToM, STTNG, etc.) work without forcing a wide
        # window.  Vertical scrollbar appears on demand.
        self._switch_matrix_canvas = tk.Canvas(
            self._switch_matrix_frame,
            height=140, highlightthickness=0, borderwidth=0)
        self._switch_matrix_scroll = ttk.Scrollbar(
            self._switch_matrix_frame, orient="vertical",
            command=self._switch_matrix_canvas.yview)
        self._switch_matrix_canvas.configure(
            yscrollcommand=self._switch_matrix_scroll.set)
        self._switch_matrix_canvas.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._switch_matrix_inner = tk.Frame(self._switch_matrix_canvas)
        self._switch_matrix_inner_id = (
            self._switch_matrix_canvas.create_window(
                (0, 0), window=self._switch_matrix_inner, anchor="nw"))

        def _update_matrix_scroll(_e=None):
            bbox = self._switch_matrix_canvas.bbox("all")
            if bbox is None:
                return
            self._switch_matrix_canvas.configure(scrollregion=bbox)
            visible = self._switch_matrix_canvas.winfo_height()
            content_h = bbox[3] - bbox[1]
            if content_h > visible + 2:
                self._switch_matrix_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                self._switch_matrix_scroll.pack_forget()

        self._switch_matrix_inner.bind(
            "<Configure>", _update_matrix_scroll)
        self._switch_matrix_canvas.bind(
            "<Configure>",
            lambda e: self._switch_matrix_canvas.itemconfig(
                self._switch_matrix_inner_id, width=e.width))
        # ``_manual_press_fn`` is set by ``on_capture_ready`` when
        # PinMAME boots; the matrix grid uses it for each button.
        self._manual_press_fn = None
        self._switch_matrix_buttons = []

        # Two post-extract "auto-name" options (only shown for manufacturers
        # that advertise the matching capability).  "Call-outs" combines
        # transcribe + rename into a single action; "music" is the AcoustID
        # lookup.  Both sit on the second "Options:" row; their former
        # one-line descriptions now live in hover tooltips so the log
        # area stays tall.
        self._transcribe_frame = ttk.Frame(self._extract_optnames_row)
        self._transcribe_check = ttk.Checkbutton(
            self._transcribe_frame,
            text="Auto-name call-outs",
            variable=self.transcribe_var)
        self._transcribe_check.pack(side=tk.LEFT)
        _Tooltip(
            self._transcribe_check,
            "Transcribe each spoken WAV (faster-whisper) and rename it by "
            "what's said — e.g. “Super jackpot!”. Also writes callouts.csv.",
            lambda: self._current_theme)

        # Music-ID: identify each full music track online via AcoustID +
        # MusicBrainz and rename it by song.  Chained after transcribe.
        self._music_id_frame = ttk.Frame(self._extract_optnames_row)
        self._music_id_check = ttk.Checkbutton(
            self._music_id_frame,
            text="Auto-name music",
            variable=self.music_id_var)
        self._music_id_check.pack(side=tk.LEFT)
        _Tooltip(
            self._music_id_check,
            "Identify each full song online (AcoustID) and rename it by "
            "artist + title — e.g. “Led Zeppelin - Kashmir”. Needs internet.",
            lambda: self._current_theme)

        # Length-prefix names (capabilities.audio_duration_names) — see the
        # duration_names_var comment for what it does and why.
        self._duration_names_frame = ttk.Frame(self._extract_optnames_row)
        self._duration_names_check = ttk.Checkbutton(
            self._duration_names_frame,
            text="Length-prefix names",
            variable=self.duration_names_var)
        self._duration_names_check.pack(side=tk.LEFT)
        _Tooltip(
            self._duration_names_check,
            "Lead each extracted sound's filename with its play length — "
            "e.g. “01m22s235 - idx0001.wav” — so sorting by name lines the "
            "same sounds up across firmware versions (slot numbers shift "
            "between releases; play lengths rarely do).",
            lambda: self._current_theme)

        # Decode DMD checkbox -- packed only when the active manufacturer
        # has capabilities.decode_dmd (currently just CGC).  When ON,
        # Extract decodes the bundled Williams WPC ROM into PNG scenes
        # + MP4 animations under output_dir/dmd/.  Off by default since
        # the decode adds a few minutes to Extract and the output isn't
        # writable back to the installer.
        self._decode_dmd_frame = ttk.Frame(f)
        self._decode_dmd_check = ttk.Checkbutton(
            self._decode_dmd_frame,
            text=("Decode DMD scenes to PNG/MP4 "
                  "(experimental, extract-only)"),
            variable=self.decode_dmd_var)
        self._decode_dmd_check.pack(side=tk.LEFT, padx=(24, 8))

        # Chain-deltas — optional "supply full image + delta(s)" merge.
        # Packed only when the active manufacturer advertises
        # ``capabilities.chain_deltas`` (Dutch Pinball).  Extract auto-applies
        # the added delta updates on top of the full image input above.
        self._extract_deltas_frame = ttk.LabelFrame(
            f, text="Optional: updates to merge on top")
        self._extract_deltas_desc = ttk.Label(
            self._extract_deltas_frame,
            text=("Supply a full image as the Input above, then add the delta "
                  "update(s) needed to reach the version you want — Extract "
                  "merges them automatically, in version order."),
            font=(_SANS_FONT, 9), justify=tk.LEFT, wraplength=620)
        self._extract_deltas_desc.pack(anchor=tk.W, padx=8, pady=(4, 2))
        _deltas_row = ttk.Frame(self._extract_deltas_frame)
        _deltas_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(_deltas_row, text="Add updates...",
                   command=self._browse_extract_deltas).pack(side=tk.LEFT)
        ttk.Button(_deltas_row, text="Clear",
                   command=self._clear_extract_deltas).pack(
            side=tk.LEFT, padx=(6, 0))
        ttk.Label(_deltas_row, textvariable=self.extract_deltas_display_var,
                  font=(_SANS_FONT, 9)).pack(side=tk.LEFT, padx=(10, 0))

        # Assemble + pack the shared action row.  The Extract button anchors
        # right (under the Browse column); the option cluster fills the space
        # to its left.  There's no separate Cancel button any more — the single
        # Extract button flips to "Cancel" while a run is in flight (see
        # _set_extract_button_running) and is gated otherwise (see
        # _refresh_extract_enabled).
        self._extract_btn = ttk.Button(
            self._extract_action_row, text="Extract",
            command=self._on_extract, style="Go.TButton")
        self._extract_btn.pack(side=tk.RIGHT)
        self._extract_btn_tip = _Tooltip(
            self._extract_btn, "", lambda: self._current_theme)
        self._extract_options_row.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # Top pad matches the path rows' pady=4 so the gap above the Extract
        # button equals the gap between the Input and Output rows (the extra
        # top padding here read as an unbalanced space below Output Folder).
        self._extract_action_row.pack(fill=tk.X, padx=10, pady=(4, 4))
        # Re-evaluate the button gate whenever the input source / output folder
        # changes (manual typing, Browse, drive pick, radio flip, or a
        # programmatic set).
        for _var in (self.extract_input_var, self.extract_output_var,
                     self.extract_drive_display_var,
                     self.extract_input_source_var):
            _var.trace_add(
                "write", lambda *_a: self._refresh_extract_enabled())

    def _build_write_tab(self):
        f = self._tab_write
        pad = {"padx": 10, "pady": 4}

        # NOTE: a static per-manufacturer intro label (mfr.write_intro()) and
        # then a mode-aware description below the source toggle used to lead
        # this tab; both are gone — all of that guidance lives in the "?" tips
        # window now (a tester, batches 4 + 8: reduce the tab's footprint).

        # Write-destination toggle (hidden for plugins without
        # direct_ssd).  Action-oriented language here — writes have
        # a destination, not a source, so "Build USB ISO" /
        # "Write to SSD" reads more naturally than "From ISO" /
        # "From SSD".  Mirrors the standalone JJP decryptor.
        # feedback batch 22 read this pair as a duplicate of the
        # "Build / flash SD card…" dialog's two checkboxes.  It isn't: the
        # dialog builds a whole image and dd-writes the ENTIRE card, while this
        # mode patches only the changed files onto a connected card in place.
        # Tooltips spell that out on each radio so the two never read as the
        # same choice again.
        self._write_source_frame = ttk.Frame(f)
        self._write_iso_radio = ttk.Radiobutton(
            self._write_source_frame, text="Build USB ISO",
            value="iso",
            variable=self.write_input_source_var,
            command=lambda: self._on_input_source_change("write"),
        )
        self._write_iso_radio.pack(side=tk.LEFT, padx=(10, 12))
        self._write_iso_tip = _Tooltip(
            self._write_iso_radio, "", lambda: self._current_theme)
        self._write_ssd_radio = ttk.Radiobutton(
            self._write_source_frame, text="Write to SSD",
            value="ssd",
            variable=self.write_input_source_var,
            command=lambda: self._on_input_source_change("write"),
        )
        self._write_ssd_radio.pack(side=tk.LEFT)
        self._write_ssd_tip = _Tooltip(
            self._write_ssd_radio, "", lambda: self._current_theme)

        # The Write tab's field-label column.  Everything created with
        # width=16 below registers here so apply_manufacturer can widen the
        # whole column in lockstep when a manufacturer noun overflows it
        # (Stern's "Original Card image:" truncated at 16 — a tester 5).
        self._write_col_labels = []

        # ISO original file row.
        self._write_upd_row = ttk.Frame(f)
        self._write_original_lbl = ttk.Label(
            self._write_upd_row, text="Original:", width=16, anchor=tk.W)
        self._write_original_lbl.pack(side=tk.LEFT)
        self._write_col_labels.append(self._write_original_lbl)
        # Batch 19: read-only mirror of the Extract tab's Input — the stock
        # image is ONE shared file, referenced, never a second copy to keep
        # in sync (the ⓘ badge still opens Image Info on it).  Batch 21:
        # plain label, no "Set on Extract tab" button.
        _orig_mirror = ttk.Label(self._write_upd_row,
                                 textvariable=self.write_upd_var, anchor=tk.W)
        # NOT fill/expand: the ⓘ badge belongs right after the path text, and
        # an expanding label shoved it to the far edge of the window — on a
        # short path that left a huge gap between the two (feedback batch 22).
        _orig_mirror.pack(side=tk.LEFT)
        _Tooltip(_orig_mirror,
                 "The master card image — it is set on the Extract tab.",
                 lambda: self._current_theme)
        self._make_info_badge(self._write_upd_row,
                              self.write_upd_var).pack(
            side=tk.LEFT, padx=(6, 0))
        self._write_upd_row.pack(fill=tk.X, **pad)

        # SSD drive picker.
        self._write_drive_row = ttk.Frame(f)
        _drive_lbl = ttk.Label(self._write_drive_row,
                               text="Game SSD:", width=16, anchor=tk.W)
        _drive_lbl.pack(side=tk.LEFT)
        self._write_col_labels.append(_drive_lbl)
        self._write_drive_combo = ttk.Combobox(
            self._write_drive_row,
            textvariable=self.write_drive_display_var,
            state="readonly")
        self._write_drive_combo.pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._write_drive_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._on_drive_selected("write"))
        ttk.Button(self._write_drive_row, text="Refresh",
                   command=lambda: self._refresh_drives("write")).pack(
            side=tk.LEFT, padx=(8, 0))

        # See the extract tab for why the "Force partition #" field
        # is intentionally absent.  Same content-verify auto-pick.

        # Red SSD-mode warning (write is even more dangerous than
        # read since changes go straight to the SSD).
        self._write_ssd_warn = ttk.Label(
            f,
            text="⚠ Remove the SSD from the pinball machine before "
                 "connecting. Always keep the original ISO as a backup.",
            foreground="#f44747",
            font=(_SANS_FONT, 9))

        # Same elevation warning as Extract — see comments there.
        self._write_admin_frame = self._build_admin_warning_frame(f)
        # Same macOS FDA warning as Extract.
        self._write_macos_fda_frame = (
            self._build_macos_fda_warning_frame(f))

        # Detect-badge row (warnings-only, like the Extract tab's — batch 20;
        # built unpacked, _sync_badge_row packs it while it has text) —
        # indented with a width-16 spacer so it lines up with the entry
        # fields (which follow width-16 labels), matching the Extract tab
        # (a tester 4.8) instead of the old fixed padx.
        self._write_badge_row = ttk.Frame(f)
        _badge_spacer = ttk.Label(self._write_badge_row, text="", width=16)
        _badge_spacer.pack(side=tk.LEFT)
        self._write_col_labels.append(_badge_spacer)
        self._write_badge = ttk.Label(self._write_badge_row, text="",
                                      font=(_SANS_FONT, 9, "italic"))
        self._write_badge.pack(side=tk.LEFT, anchor=tk.W)
        self._write_badge.bind(
            "<Button-1>", lambda _e: self._auto_switch("write"))
        self._write_badge.bind(
            "<Enter>", lambda _e: self._update_badge_cursor("write", True))
        self._write_badge.bind(
            "<Leave>", lambda _e: self._update_badge_cursor("write", False))

        self._write_assets_row_ref = ttk.Frame(f)
        self._write_assets_row_ref.pack(fill=tk.X, **pad)
        _assets_lbl = ttk.Label(self._write_assets_row_ref,
                                text="Project Folder:", width=16, anchor=tk.W)
        _assets_lbl.pack(side=tk.LEFT)
        self._write_col_labels.append(_assets_lbl)
        self._project_path_display(self._write_assets_row_ref,
                                   self.write_assets_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)

        # Inline warning that appears when the picked Modified Assets
        # folder doesn't contain a `.checksums.md5` baseline (the user
        # most likely pointed at a subfolder of the Extract output).
        # Sits directly under the Modified Assets row so the warning
        # is impossible to miss — the same condition also surfaces in
        # the Modified Files Preview empty state, but that pane is
        # easy to overlook when focused on the path field.
        # Pack-managed by _refresh_write_assets_warning().
        self._write_assets_warning = ttk.Label(
            f, text="", foreground="#d04040",
            font=(_SANS_FONT, 9),
            wraplength=720, justify=tk.LEFT)

        # Admin/UNC hint — Windows hides a user's mapped network drives
        # (e.g. W:) from an elevated process, so when the app is relaunched
        # "as administrator" to write straight to the card, those letters
        # vanish from both the Browse dialog and any saved path, silently
        # leaving the Modified Files Preview empty.  Spell out the UNC
        # workaround.  Pack-managed by _on_input_source_change (win32 + admin
        # + SD-card mode only).
        self._write_admin_unc_hint = ttk.Label(
            f,
            text=("Running as administrator: Windows hides mapped network "
                  "drive letters (e.g. W:) from elevated apps. If your "
                  "modified assets live on a network share, paste the full "
                  "\\\\server\\share path into the field above instead of "
                  "browsing to a drive letter."),
            foreground="#c08a3e",
            font=(_SANS_FONT, 9, "italic"),
            wraplength=720, justify=tk.LEFT)

        # Editable-folder hint — appears as a subtle italic line below
        # the Modified Assets row.  For BOF May code the Extract step
        # creates a pck/_EDITABLE ASSETS/ folder with WAV / WEBP / OGV
        # / TTF files that mirror the imported binaries; editing those
        # is the main modding workflow.  Other plugins (JJP, CGC, PB,
        # Spooky) have no auto re-encode step — replacement files must
        # already be in the game's native format — so apply_manufacturer
        # packs this hint only when mfr.key == "bof".
        self._write_editable_hint = ttk.Label(
            f,
            text=("Tip: edit your audio (.wav), images (.webp), and video (.ogv) "
                  "files in pck/_EDITABLE ASSETS/ inside your Modified Assets "
                  "folder. Write auto-detects changes there and re-encodes them."),
            foreground="#888888",
            font=(_SANS_FONT, 9, "italic"),
            wraplength=720, justify=tk.LEFT)

        # BOF-only: update-version date control.  The game only applies a
        # .fun whose version date (line 2 of updated_bash_profile /
        # updated_updatecode) is newer than what's installed, so Write
        # advances it.  This row shows the concrete date that will be
        # stamped and lets the user override it.  Pack-managed by
        # apply_manufacturer (BOF only); see write_version_date capability.
        self._write_version_frame = ttk.Frame(f)
        _version_lbl = ttk.Label(self._write_version_frame,
                                 text="Update version:", width=16, anchor=tk.W)
        _version_lbl.pack(side=tk.LEFT)
        self._write_col_labels.append(_version_lbl)
        self._write_version_auto_check = ttk.Checkbutton(
            self._write_version_frame, text="Auto",
            variable=self.write_version_auto_var,
            command=self._on_write_version_auto_toggle)
        self._write_version_auto_check.pack(side=tk.LEFT)
        self._write_version_entry = ttk.Entry(
            self._write_version_frame,
            textvariable=self.write_version_date_var, width=12)
        self._write_version_entry.pack(side=tk.LEFT, padx=(8, 0))
        self._write_version_hint = ttk.Label(
            self._write_version_frame, text="",
            foreground="#888888", font=(_SANS_FONT, 9, "italic"))
        self._write_version_hint.pack(side=tk.LEFT, padx=(8, 0))

        self._write_output_row_ref = ttk.Frame(f)
        self._write_output_row_ref.pack(fill=tk.X, **pad)
        # Batch 21 merged "Build Location" + "File Name" into one "Build
        # Image" row showing the full destination path; Change… is a single
        # Save-As picker that sets both the folder (remembered as this
        # project's build_dir override — batch 19) and the file name.  The
        # underlying write_output_var / write_filename_var stay the state
        # the build flow reads; this row shows their join with the plugin's
        # forced extension applied (which also retired the old standalone
        # "saved as .raw" reminder).
        _out_lbl = ttk.Label(self._write_output_row_ref,
                             text="Build Image:", width=16, anchor=tk.W)
        _out_lbl.pack(side=tk.LEFT)
        self._write_col_labels.append(_out_lbl)
        self._write_build_path_var = tk.StringVar()
        ttk.Entry(self._write_output_row_ref,
                  textvariable=self._write_build_path_var,
                  state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._write_output_row_ref, text="Change...",
                   command=self._change_build_location).pack(
            side=tk.LEFT, padx=(8, 0))
        self.write_output_var.trace_add(
            "write", self._refresh_build_path_display)
        self.write_filename_var.trace_add(
            "write", self._refresh_build_path_display)
        self._refresh_build_path_display()

        # Flush-left with the "File Name:" / "Output Folder:" row labels (padx
        # matches the rows' `pad`), not indented under the entry -- a tester
        # found the old 26px indent read as off-centre / non-standard.
        self._write_filename_lbl = ttk.Label(f, text="",
                                             font=(_SANS_FONT, 9, "italic"))
        self._write_filename_lbl.pack(anchor=tk.W, padx=10)

        # JJP Direct-SSD-only: "Modified Files Preview" — same shape
        # as the standalone JJP decryptor.  Walks the assets folder
        # comparing each file's MD5 against the .checksums.md5 the
        # Extract phase emitted; anything that doesn't match shows up
        # as "Modified".  Gives users a sanity check before they
        # click Apply Modifications and commit changes to a real SSD.
        # Hidden by apply_manufacturer() for plugins without
        # direct_ssd; populated by _scan_write_preview() on tab show.
        self._write_preview_frame = ttk.LabelFrame(
            f, text=" Modified Files ", padding=4)
        # Pack-managed by apply_manufacturer + _on_input_source_change.

        # Toolbar across the top of the preview frame.  Batch 9 put the SCAN
        # control on the LEFT and the "act on these changes" actions —
        # Flash ▸ Revert ▸ Build — on the RIGHT, so the scan Cancel couldn't
        # be mistaken for a run Cancel.  Batch 22: a tester asked for the
        # scan button right-justified like every other tab's, so it joins the
        # right-hand group as its LEFTMOST member with a wide gap before the
        # action buttons — same reading order, still visibly a separate group
        # (and "Cancel scan" vs a run's "Cancel" keeps them apart in words).
        preview_toolbar = ttk.Frame(self._write_preview_frame)
        preview_toolbar.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._write_preview_toolbar = preview_toolbar
        self._write_preview_refresh_btn = ttk.Button(
            preview_toolbar, text="Refresh",
            command=self._rescan_write_preview_clicked)
        self._write_preview_refresh_btn.pack(side=tk.RIGHT, padx=(0, 24))
        # Register with the shared scan-state machinery so the preview scan
        # gets the same treatment as the Replace tabs — list blanked, big
        # animated spinner, Refresh flips to a live Cancel (feedback batch 8:
        # the old disabled "⏳ Scanning…" button looked like nothing else).
        self._scan_buttons["write_preview"] = self._write_preview_refresh_btn
        self._scan_cmds["write_preview"] = self._rescan_write_preview_clicked
        self._scan_idle_labels["write_preview"] = "Refresh"
        # The single Build button doubles as a live Cancel while a build runs
        # (a tester 4.4 — no separate Cancel widget any more); its label and
        # command are driven by _set_write_button_running.
        self._write_btn = ttk.Button(
            preview_toolbar, text="Build update",
            command=self._on_write_clicked, style="Go.TButton")
        self._write_btn.pack(side=tk.RIGHT)
        # Revert is gated to plugins with a Replace surface in
        # apply_manufacturer, which re-packs it just left of Build.
        # Danger-styled: it rewrites files on disk (David: red for
        # delete-like actions).
        self._revert_all_btn = ttk.Button(
            preview_toolbar, text="Revert all changes…",
            command=self._revert_all_clicked, style="Danger.TButton")
        self._revert_all_btn.pack(
            side=tk.RIGHT, padx=(0, 6), after=self._write_btn)

        preview_inner = ttk.Frame(self._write_preview_frame)
        preview_inner.pack(fill=tk.BOTH, expand=True)

        self._write_preview_tree = ttk.Treeview(
            preview_inner, columns=("type", "status"),
            height=6, selectmode="browse")
        self._write_preview_tree.heading("#0", text="File", anchor=tk.W)
        self._write_preview_tree.heading(
            "type", text="Type", anchor=tk.W)
        self._write_preview_tree.heading(
            "status", text="Status", anchor=tk.W)
        self._write_preview_tree.column(
            "#0", width=400, minwidth=200)
        self._write_preview_tree.column(
            "type", width=60, minwidth=40)
        self._write_preview_tree.column(
            "status", width=200, minwidth=100)
        self._persist_tree_columns(
            self._write_preview_tree, "write_preview",
            ("#0", "type", "status"))
        preview_scroll = ttk.Scrollbar(
            preview_inner, orient=tk.VERTICAL,
            command=self._write_preview_tree.yview)
        self._write_preview_tree.configure(
            yscrollcommand=preview_scroll.set)
        preview_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._write_preview_tree.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Placeholder shown when the tree is empty (no scan yet, or
        # scan returned no changes).  Floats centred on top of the
        # tree via .place; the scan code shows/hides it.
        self._write_preview_empty = ttk.Label(
            preview_inner,
            text="Select your modified assets folder above to preview changed files.",
            foreground="#888888",
            anchor=tk.CENTER, justify=tk.CENTER)
        self._write_preview_empty.place(
            relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Status strip under the tree (feedback batch 9).  Left: the legend
        # for the two Status words.  Right: "Total changes: N" — a running
        # tally of every Modified + Pending row so the user doesn't have to
        # count/scroll the list (blank when empty; the placeholder already
        # covers that state).
        #
        # Batch 9 also put a live scan-activity label here, because rows
        # trickling into the tree hid the big spinner overlay for most of a
        # long MD5 walk.  Batch 22 holds the rows back until the scan
        # finishes, so the overlay (with its running "N found") is visible the
        # whole time and this second, smaller indicator is gone — a tester
        # read the two as inconsistent with every other tab.
        preview_status_row = ttk.Frame(self._write_preview_frame)
        preview_status_row.pack(fill=tk.X, padx=4, pady=(2, 0))
        legend = ttk.Label(
            preview_status_row,
            text="Pending = staged this session, applied when you Build · "
                 "Modified = file on disk already differs from the extract",
            font=(_SANS_FONT, 8, "italic"), foreground="#888888")
        legend.pack(side=tk.LEFT, padx=(12, 0))
        self._write_preview_count_lbl = ttk.Label(
            preview_status_row, text="", font=(_SANS_FONT, 9))
        self._write_preview_count_lbl.pack(side=tk.RIGHT)

        # Bump-counter to invalidate in-flight scans when the user
        # changes the assets folder before a previous scan finishes.
        self._write_preview_scan_id = 0

        # (Build / Revert / Refresh live in the preview-frame toolbar above;
        # the Build button also serves as the run-time Cancel — see
        # _set_write_button_running.  No separate bottom button row.)

        # Apply-delta — gated by capability flag in apply_manufacturer().
        self._delta_frame = ttk.LabelFrame(
            f, text="Optional: Apply Delta on Top")
        ttk.Label(
            self._delta_frame,
            text="Layer a delta update on top of the extracted assets before "
            "rebuilding.  Files in the delta overwrite or get added on top of "
            "your assets folder.",
            font=(_SANS_FONT, 9), justify=tk.LEFT, wraplength=600,
        ).pack(anchor=tk.W, padx=8, pady=(4, 2))
        ttk.Button(self._delta_frame, text="Apply Delta...",
                   command=lambda: self._on_apply_delta() if self._on_apply_delta else None
                   ).pack(anchor=tk.W, padx=8, pady=(2, 6))

        # Install instructions — populated per manufacturer.
        self._install_frame = ttk.LabelFrame(f, text="How to Install")
        self._install_lbl = ttk.Label(
            self._install_frame, text="", font=(_SANS_FONT, 9),
            justify=tk.LEFT, wraplength=600)
        self._install_lbl.pack(anchor=tk.W, padx=8, pady=6)

        # Flash-image — gated by capabilities.flash_image in
        # apply_manufacturer().  A dd-style whole-image write so users can put a
        # pre-built (or backed-up) card image straight onto a card without a
        # separate imaging tool.  Distinct from Build/Write: those modify
        # assets; this replaces the entire card.  Opens a small modal that
        # collects the image + target card and confirms before the write runs
        # through the normal status area.  Joins the right-hand action group
        # of the preview toolbar, left of Revert/Build (feedback batch 9) —
        # its old LabelFrame + description paragraph moved to the "?" tips
        # window (feedback batch 8: tighter footprint, actions group
        # logically).
        # While a flash runs the button doubles as its live Cancel — see
        # set_flash_running.
        self._flash_btn = ttk.Button(
            preview_toolbar, text=self._FLASH_BTN_TEXT,
            command=self._open_flash_dialog, style="Go.TButton")
        self._flash_btn_tip = _Tooltip(
            self._flash_btn, self._FLASH_BTN_TIP,
            lambda: self._current_theme)
        # "Card diagnostics…" — only for manufacturers implementing
        # diagnose_card (CGC): reads the on-machine installer's log back off
        # a failed card (read-only).  Packed/hidden in apply_manufacturer().
        self._diagnose_btn = ttk.Button(
            preview_toolbar, text="Card diagnostics…",
            command=self._open_diagnose_dialog)

    def _build_modpack_tab(self):
        f = self._tab_modpack

        # Batch 22: the tab's intro paragraph and the "(the project folder —
        # every Replace tab…)" gloss under the path both moved into the "?"
        # tips window — the tab is two actions and one transfer form, and the
        # prose was costing rows a tester wanted for the form.

        # Same label as the Replace tabs — it's the SAME folder (one shared
        # path variable), and two names for one thing read as two things
        # (feedback batch 14).
        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=(8, 4))
        ttk.Label(row, text="Project Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._project_path_display(row, self.write_assets_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)

        # One "Mod Pack" box with both buttons, right-aligned like every other
        # tab's action row (batch 22 — two stacked LabelFrames each holding one
        # sentence and one left-aligned button burned six rows to say one
        # thing).  The sentence each frame carried is now the button's tooltip.
        pack_frame = ttk.LabelFrame(f, text="Mod Pack")
        pack_frame.pack(fill=tk.X, padx=10, pady=(4, 4))
        pack_row = ttk.Frame(pack_frame)
        pack_row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(pack_row,
                  text="Share your changes as a zip, or apply someone else's.",
                  font=(_SANS_FONT, 9)).pack(side=tk.LEFT)
        _import_btn = ttk.Button(pack_row, text="Import Mod Pack...",
                                 command=self._on_import, style="Go.TButton")
        _import_btn.pack(side=tk.RIGHT)
        _Tooltip(_import_btn,
                 "Apply a mod pack zip from another user onto this project's "
                 "extracted assets.", lambda: self._current_theme)
        _export_btn = ttk.Button(pack_row, text="Export Mod Pack...",
                                 command=self._on_export, style="Go.TButton")
        _export_btn.pack(side=tk.RIGHT, padx=(0, 6))
        _Tooltip(_export_btn,
                 "Create a zip holding only your modified files, small enough "
                 "to share.", lambda: self._current_theme)

        # Gated per-plugin (caps.mod_transfer) in apply_manufacturer — this tab
        # is shared, but the feature (and its wording) only fits plugins whose
        # vendor re-lays-out the card across versions, e.g. Stern Spike 2.
        self._modpack_transfer_frame = ttk.LabelFrame(
            f, text="Transfer Mods to New Version")
        _transfer_intro = ttk.Label(
            self._modpack_transfer_frame,
            text="New game code shipped? Pull your mods from your old extract "
                 "onto a fresh extract of the new version, then build the new "
                 "version's card with your mods on it. Fill the two required "
                 "folders (and, if you have it, the optional one for a more "
                 "accurate transfer). Works even for code modded outside this "
                 "app.",
            font=(_SANS_FONT, 9), justify=tk.LEFT)
        _transfer_intro.pack(anchor=tk.W, fill=tk.X, padx=8, pady=(4, 2))
        self._register_responsive_wrap(_transfer_intro)
        self.transfer_src_var = tk.StringVar()
        self.transfer_dst_var = tk.StringVar()
        # Optional stock extract of the OLD version — its presence (not a
        # modal) chooses the accurate baseline route; empty = direct compare.
        self.transfer_oldstock_var = tk.StringVar()
        # The NEW version's card image (.raw): the base the build patches your
        # mods onto, and what the output is named after.  Auto-filled from the
        # new extract's recorded source so it can't drift to the old version
        # (the mistake that produced an old-version-named build).
        self.transfer_newimg_var = tk.StringVar()
        # Read-only hints recomputed by _transfer_refresh_meta.
        self.transfer_src_ver_var = tk.StringVar()
        self.transfer_dst_ver_var = tk.StringVar()
        self.transfer_img_ver_var = tk.StringVar()
        self.transfer_output_var = tk.StringVar()
        self.transfer_next_var = tk.StringVar()

        tf = ttk.Frame(self._modpack_transfer_frame)
        tf.pack(fill=tk.X, padx=8, pady=(2, 2))
        tf.columnconfigure(1, weight=1)

        # Version hints live in the row's own trailing column.  feedback batch
        # 22 asked whether they were worth showing: they are — every one is
        # parsed from a source filename and they are the only on-screen check
        # that field 2 and field 4 are the SAME new version — so they stay, but
        # as a compact chip that can't stretch the grid (the entry column owns
        # the slack), with a tooltip saying where the number comes from.
        def _picker(row, label, var, browse, ver_var=None, tip=None):
            lbl = ttk.Label(tf, text=label)
            lbl.grid(row=row, column=0, sticky=tk.W, pady=2)
            if tip:
                _Tooltip(lbl, tip, lambda: self._current_theme)
            ttk.Entry(tf, textvariable=var).grid(
                row=row, column=1, sticky=tk.EW, padx=6, pady=2)
            ttk.Button(tf, text="Browse...", command=browse).grid(
                row=row, column=2, pady=2)
            if ver_var is not None:
                vl = ttk.Label(tf, textvariable=ver_var, foreground="#4a90d9",
                               font=(_SANS_FONT, 8), anchor=tk.W, width=22)
                vl.grid(row=row, column=3, sticky=tk.W, padx=(6, 0))
                _Tooltip(vl, "Version guessed from this item's own file name "
                             "— a cross-check, not something the card stores. "
                             "Fields 2 and 4 should show the SAME version.",
                         lambda: self._current_theme)

        _picker(0, "1. Old extract (has your mods):",
                self.transfer_src_var, self._browse_transfer_src,
                self.transfer_src_ver_var)
        _picker(1, "2. New extract (stock, new version):",
                self.transfer_dst_var, self._browse_transfer_dst,
                self.transfer_dst_ver_var)
        _picker(2, "3. Stock extract of the OLD version (optional):",
                self.transfer_oldstock_var, self._browse_transfer_oldstock,
                tip="Not an alternative to field 1, and never in conflict "
                    "with it: field 1 is where your mods come FROM; this is "
                    "an unmodified twin of that same version, used only as "
                    "the reference your old extract is compared against.")
        # Full-width hint (feedback batch 22: it was capped at 560px inside a
        # much wider tab) — the responsive wrap tracks the content width.
        # Batch 24: he read fields 1 and 3 as two ways to provide the same
        # thing and asked which wins — so the hint now leads with the ROLE
        # (a clean reference copy), not with what happens when it's empty.
        _oldstock_hint = ttk.Label(
            tf,
            text="A clean, unmodified extract of the SAME old version as "
                 "field 1 — used only as a reference to compare field 1 "
                 "against, so the factory's own between-version changes "
                 "aren't mistaken for your mods, and AUDIO and TEXT mods "
                 "can be carried too. Leave empty to compare your old "
                 "extract straight against the new one (finds image + "
                 "video mods).",
            font=(_SANS_FONT, 8, "italic"), justify=tk.LEFT)
        _oldstock_hint.grid(row=3, column=1, columnspan=3,
                            sticky=tk.EW, padx=6, pady=(0, 4))
        self._register_responsive_wrap(_oldstock_hint, margin=330)
        # Field 4 is NOT an alternative to field 2 — feedback batch 22 read
        # the folder and the .raw as two ways to say the same thing and asked
        # which won.  Both are required and they do different jobs, so the
        # label says which one it is derived from.
        _picker(4, "4. New version card image (.raw) to build onto:",
                self.transfer_newimg_var, self._browse_transfer_newimg,
                self.transfer_img_ver_var,
                tip="The stock image the new extract came from — the base the "
                    "build patches your transferred mods onto. Auto-filled "
                    "from field 2's extract; it is needed as well as field 2, "
                    "not instead of it.")
        _newimg_hint = ttk.Label(
            tf,
            text="Auto-filled from field 2 (the new extract records the image "
                 "it came from). Both fields are required.",
            font=(_SANS_FONT, 8, "italic"), justify=tk.LEFT)
        _newimg_hint.grid(row=5, column=1, columnspan=3, sticky=tk.EW,
                          padx=6, pady=(0, 2))
        self._register_responsive_wrap(_newimg_hint, margin=330)

        # Action row: button right-aligned like every other tab, with the
        # output-name preview on its left.  That preview answers "what am I
        # about to end up with" (feedback batch 22 asked if it was still
        # relevant — it is the only place the built file's NAME appears before
        # the build), so it stays, beside the button that causes it.
        arow = ttk.Frame(self._modpack_transfer_frame)
        arow.pack(fill=tk.X, padx=8, pady=(4, 2))
        ttk.Button(arow, text="Transfer mods → new version...",
                   command=(self._on_transfer_mods
                            if self._on_transfer_mods else lambda: None),
                   style="Go.TButton").pack(side=tk.RIGHT)
        ttk.Label(arow, textvariable=self.transfer_output_var,
                  font=(_SANS_FONT, 8, "italic"),
                  justify=tk.LEFT).pack(side=tk.LEFT)
        # Filled after a successful transfer with the exact next step (also
        # written to the log, so it survives once this panel scrolls away).
        _next_lbl = ttk.Label(
            self._modpack_transfer_frame,
            textvariable=self.transfer_next_var, foreground="#3aa76d",
            font=(_SANS_FONT, 9, "bold"), justify=tk.LEFT)
        _next_lbl.pack(anchor=tk.W, fill=tk.X, padx=8, pady=(0, 6))
        self._register_responsive_wrap(_next_lbl)

        # Recompute version hints + output name whenever a field changes; the
        # new-extract field also auto-fills the base image (row 4).
        for _v in (self.transfer_src_var, self.transfer_dst_var,
                   self.transfer_newimg_var):
            _v.trace_add("write", lambda *_a: self._transfer_refresh_meta())

    # ------------------------------------------------------------------
    # Replace Audio tab (capabilities.replace_audio plugins)
    # ------------------------------------------------------------------

    def _build_audio_tab(self):
        """Build the 'Replace Audio' tab: a searchable list of the audio
        files in the extracted assets folder, each a slot the user can
        assign + preview a replacement track for.  Staging converts the
        replacements to each slot's native format and writes them over the
        originals so the normal Write step repacks them."""
        f = self._tab_audio
        pad = {"padx": 10, "pady": 4}

        # One-line intro; the full behaviour notes live in the "?" tips window
        # (a tester: the multi-line paragraphs crowded every tab).
        _audio_desc = ttk.Label(
            f,
            text="Assign a replacement track to any slot — almost any audio "
                 "format is accepted and auto-converted — then build the "
                 "update on the Write tab.",
            font=(_SANS_FONT, 9, "italic"),
            wraplength=720, justify=tk.LEFT)
        _audio_desc.pack(anchor=tk.W, **pad)
        self._register_responsive_wrap(_audio_desc)

        # ffmpeg-missing banner.  Same-format swaps (.wav→.wav) work without
        # ffmpeg, but converting other formats / matching sample-rate needs
        # it.  Pack-managed by _refresh_audio_ffmpeg_warning(); positioned
        # before the assets row.
        self._audio_ffmpeg_warn = ttk.Label(
            f,
            text="⚠ ffmpeg not found — you can still swap files already in the "
                 "game's format (.wav→.wav, .ogg→.ogg), but converting other "
                 "formats (mp3, flac, …) or matching sample rate needs ffmpeg. "
                 "Install it with “Install Missing” above the tabs.",
            foreground="#d04040", font=(_SANS_FONT, 9),
            wraplength=720, justify=tk.LEFT)

        # Assets folder row (shared with the Write / Mod Pack tabs).
        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        self._audio_assets_row = row
        ttk.Label(row, text="Project Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._project_mirror_label(row).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._make_assets_scan_buttons(row, "audio",
                                       self._scan_audio_slots_async)

        # Search + sort toolbar.
        tools = ttk.Frame(f); tools.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(tools, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(tools, textvariable=self.audio_search_var, width=24).pack(
            side=tk.LEFT, padx=(4, 12))
        # "Type" filter — packed by _refresh_audio_type_filter only when the
        # scanned folder actually classifies (a folder with no Auto-name
        # artifacts is all "Other", so the dropdown would do nothing).
        self._audio_type_frame = ttk.Frame(tools)
        ttk.Label(self._audio_type_frame, text="Type:").pack(side=tk.LEFT)
        self._audio_type_combo = ttk.Combobox(
            self._audio_type_frame, textvariable=self.audio_type_var,
            state="readonly", width=9,
            values=("All types", "Music", "Sound FX", "Callouts", "Other"))
        self._audio_type_combo.pack(side=tk.LEFT, padx=(4, 12))
        self._audio_type_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_audio_list())
        _Tooltip(
            self._audio_type_combo,
            "Show only one kind of audio. Music = the game's song/bank "
            "tracks plus anything at least 20 seconds long (some pins store "
            "their songs as Sound-Test-named sequences, so a long \"SE FX\" "
            "track shows under both Music and Sound FX). Sound FX = effects "
            "named by the game's own Sound Test menu. Callouts = spoken "
            "lines found by Auto-name call-outs. Other = the rest — short "
            "unnamed effects.",
            lambda: self._current_theme)
        # "Group duplicates" — created here, packed per-manufacturer next to
        # the sort hint (apply_manufacturer, CGC only).
        self._audio_dup_group_cb = ttk.Checkbutton(
            tools, text="Group duplicates",
            variable=self.audio_group_dups_var,
            command=self._on_audio_group_dups_toggle)
        _Tooltip(
            self._audio_dup_group_cb,
            "Group the slots that carry byte-identical factory audio under "
            "one row, so every copy of a sound sits together. The first "
            "tick scans the sound banks (about ten seconds). The game may "
            "play any copy of a duplicated sound, so mod them together — "
            "assign a replacement to one copy, then right-click it and "
            "choose \"Apply to all copies\".",
            lambda: self._current_theme)
        # "Show: All / Changed / Unchanged" — same dropdown as the Images and
        # Video tabs.  It is always visible, so it doubles as the stable
        # `before=` anchor for the optional Type / Group-duplicates widgets
        # packed later.
        self._build_change_filter(tools, "audio").pack(side=tk.LEFT)
        # Button rightmost (flush with the list edge), counter to its left
        # (feedback batch 21).
        self._audio_csv_btn = ttk.Button(
            tools, text="Export CSV", command=self._audio_export_csv)
        self._audio_csv_btn.pack(side=tk.RIGHT)
        self._audio_status_lbl = ttk.Label(
            tools, textvariable=self.audio_status_var,
            font=(_SANS_FONT, 9))
        self._audio_status_lbl.pack(side=tk.RIGHT, padx=(0, 10))
        _Tooltip(
            self._audio_csv_btn,
            "Save the whole audio table (every slot, not just the filtered "
            "view) as a CSV — name, length, format, type, replacement and "
            "changed-on-disk status — for tracking a big replacement project "
            "in a spreadsheet.",
            lambda: self._current_theme)

        # Slot list.
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        # "loop" and "keep" are optional toggle columns shown per capability
        # (apply_manufacturer sets displaycolumns) — "loop" for
        # audio_loop_inject (BOF), "keep" for audio_keep_length_override (JJP).
        # They never show together (different plugins).  displaycolumns places
        # whichever is active just BEFORE "rep" so the narrow toggle is never
        # the rightmost (clippable) column; the values tuple still follows this
        # `columns` order (vals[3]=loop, vals[4]=keep) regardless of display
        # order.
        self._audio_tree = ttk.Treeview(
            list_frame, columns=("len", "fmt", "rep", "loop", "keep", "type"),
            height=12, selectmode="browse")
        self._audio_tree.heading("#0", text="Original Track", anchor=tk.W)
        self._audio_tree.heading("len", text="Length", anchor=tk.W)
        self._audio_tree.heading("fmt", text="Format", anchor=tk.W)
        self._audio_tree.heading("rep", text="Replacement", anchor=tk.W)
        self._audio_tree.heading("loop", text="Loop", anchor=tk.CENTER)
        self._audio_tree.heading("keep", text="Full", anchor=tk.CENTER)
        self._audio_tree.heading("type", text="Type", anchor=tk.W)
        # ttk has no horizontal scroll: when the total column width exceeds the
        # widget it clips the rightmost column, and stretch only ever *grows*
        # columns, never shrinks them.  Only the track-name (#0) and
        # Replacement columns stretch to absorb extra width; the rest are fixed
        # and compact.  The Replacement column is the rightmost (via
        # displaycolumns) so it — not the toggle column — absorbs any overflow.
        self._audio_tree.column("#0", width=150, minwidth=80, stretch=True)
        # Wide enough for the m:ss.mmm length (e.g. "12:34.567").
        self._audio_tree.column("len", width=80, minwidth=66, anchor=tk.W,
                                stretch=False)
        self._audio_tree.column("fmt", width=124, minwidth=104, stretch=False)
        self._audio_tree.column("rep", width=150, minwidth=110, stretch=True)
        self._audio_tree.column("loop", width=44, minwidth=40, anchor=tk.CENTER,
                                stretch=False)
        self._audio_tree.column("keep", width=44, minwidth=40, anchor=tk.CENTER,
                                stretch=False)
        self._audio_tree.column("type", width=78, minwidth=64, anchor=tk.W,
                                stretch=False)
        self._persist_tree_columns(
            self._audio_tree, "audio",
            ("#0", "len", "fmt", "rep", "loop", "keep", "type"))
        # Click-header sort: (col_id, base heading text, default-descending).
        # Numeric columns default to descending (longest/looped first) the way
        # the old "Longest first" option did; text columns ascending.
        self._audio_sort_cfg = [
            ("#0", "Original Track", False), ("len", "Length", True),
            ("fmt", "Format", False), ("type", "Type", False),
            ("rep", "Replacement", False),
            ("loop", "Loop", True), ("keep", "Full", True)]
        self._wire_sort_headings(self._audio_tree, self._audio_sort_cfg,
                                 "_audio_sort", self._refresh_audio_list)
        audio_scroll = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self._audio_tree.yview)
        self._audio_tree.configure(yscrollcommand=audio_scroll.set)
        audio_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._audio_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Double-click a row → play its original (and show the seek bar).
        self._audio_tree.bind("<Double-1>", self._audio_on_tree_double)
        # Click in the Replacement column → open the file picker (the column
        # acts as a per-row "Choose…" button).
        self._audio_tree.bind("<Button-1>", self._audio_on_tree_click, add="+")
        # Right-click → context menu (replace / play / clear).  Button-2 +
        # Control-click cover macOS.
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self._audio_tree.bind(seq, self._audio_on_tree_right)
        # Selecting a row loads its original into the seek-bar strip (no
        # autoplay), debounced so arrowing through the list doesn't thrash.
        self._audio_tree.bind("<<TreeviewSelect>>", self._audio_on_tree_select)
        # Spacebar = play/pause, audio-editor style (feedback batch 14):
        # click a row, tap space to listen, arrow on.  "break" stops the
        # Treeview's own space handling from re-toggling the selection.
        self._audio_tree.bind("<space>", self._audio_space_toggle)
        # F2 = Properties (rename / Type), the Explorer-standard rename key —
        # feedback batch 22 kept reaching for it while renaming a batch of
        # callouts.  Same gate as the context-menu entry: decode-shaped names
        # only (see _audio_on_tree_right).
        self._audio_tree.bind("<F2>", self._audio_properties_shortcut)
        # Hover over the Loop column → tooltip explaining the feature.
        self._audio_tree.bind("<Motion>", self._audio_on_tree_motion, add="+")
        self._audio_tree.bind(
            "<Leave>", lambda _e: self._hide_audio_loop_tip(), add="+")

        self._audio_empty = ttk.Label(
            list_frame,
            text="Set the project folder on the Extract tab, then click Scan.",
            foreground="#888888", anchor=tk.CENTER, justify=tk.CENTER)
        self._audio_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # --- Preview players: Original and Replacement side by side (like
        # the image tab), each a media-player-style panel with its own
        # spectrogram seek bar and transport — replacing the old single
        # player + Source A/B switch (David).  Starting one pane pauses the
        # other so the two tracks never play over each other. ---
        player = ttk.LabelFrame(f, text=" Preview ")
        player.pack(fill=tk.X, padx=10, pady=(4, 2))
        panes = ttk.Frame(player)
        panes.pack(fill=tk.X, padx=6, pady=(2, 6))
        panes.columnconfigure(0, weight=1, uniform="audiopane")
        panes.columnconfigure(1, weight=1, uniform="audiopane")
        self._audio_pane_orig = _AudioPreviewPane(
            self, panes, "Original",
            on_activate=lambda: self._audio_activate_pane("orig"))
        self._audio_pane_rep = _AudioPreviewPane(
            self, panes, "Replacement",
            on_activate=lambda: self._audio_activate_pane("rep"))
        self._audio_pane_orig.sibling = self._audio_pane_rep
        self._audio_pane_rep.sibling = self._audio_pane_orig
        self._audio_pane_orig.on_finished = self._audio_on_clip_finished
        self._audio_pane_rep.on_finished = self._audio_on_clip_finished
        self._audio_pane_orig.frame.grid(row=0, column=0, sticky="ew",
                                         padx=(0, 4))
        self._audio_pane_rep.frame.grid(row=0, column=1, sticky="ew",
                                        padx=(4, 0))
        self._audio_pane_rep.clear("no replacement assigned")

        # Length-matching option + the Stern experiment buttons share one row:
        # the Trim/pad checkbox on the left, Advanced… / Profile vs stock on the
        # right.  The checkbox is HIDDEN for plugins whose Write always
        # length-matches (audio_forces_length_match, via _apply_audio_trim_lock
        # — batch 20: a forced-on disabled checkbox still read as a setting the
        # user should worry about); the buttons are Stern-only
        # (apply_manufacturer hides them elsewhere).
        self._audio_opts_row = ttk.Frame(f)
        # padx 10, not 12: lines the checkboxes up with the preview frame and
        # the Project Folder / Search rows above (batch 24).
        self._audio_opts_row.pack(anchor=tk.W, fill=tk.X, padx=10, pady=(4, 4))
        self._audio_trim_cb = ttk.Checkbutton(
            self._audio_opts_row,
            text="Trim / pad replacements to the original slot length",
            variable=self.audio_trim_var, command=self._save_staged_changes)
        self._audio_trim_cb.pack(side=tk.LEFT)
        # Hover tooltip — its text is set per-manufacturer in apply_manufacturer.
        self._audio_trim_tip = _Tooltip(
            self._audio_trim_cb, "", lambda: self._current_theme)
        # Audition the card hands-free (feedback batch 23: "select a file and
        # it starts playing the next file in the list ... to run through all
        # the audio files without manual intervention").  Batch 25 renamed
        # both boxes to two-word labels ("Play through list" and "substitute
        # replacements" read wordy — his suggestion).
        self._audio_playthrough_cb = ttk.Checkbutton(
            self._audio_opts_row, text="Play sequentially",
            variable=self.audio_play_through_var)
        self._audio_playthrough_cb.pack(side=tk.LEFT, padx=(18, 0))
        _Tooltip(self._audio_playthrough_cb,
                 "When a clip finishes, select and play the next row in the "
                 "list, following whatever sort, search and Type filter are "
                 "showing.\n\nStops at the end of the list, and any ■ (or "
                 "clicking another row) stops it.",
                 lambda: self._current_theme)
        # Batch 24: audition the card as it will be BUILT — rows with a
        # replacement play the replacement, the rest play the original, so a
        # clip that still sounds stock is one he forgot to replace.
        self._audio_play_subst_cb = ttk.Checkbutton(
            self._audio_opts_row, text="Play replacements",
            variable=self.audio_play_subst_var,
            command=self._audio_on_play_subst_toggle)
        self._audio_play_subst_cb.pack(side=tk.LEFT, padx=(18, 0))
        _Tooltip(self._audio_play_subst_cb,
                 "While playing sequentially, a row that has a replacement "
                 "(picked now, or already changed on disk) plays the "
                 "replacement instead of the original — the whole list "
                 "sounds the way the built card will.\n\nSo anything that "
                 "still sounds stock is a clip you haven't replaced yet.\n\n"
                 "Ticking this turns on \"Play sequentially\" too — it only "
                 "acts while sequential play is stepping through the list.",
                 lambda: self._current_theme)
        # Experiment levers for the trigger-pop hunt (Stern-only): per-knob
        # encode overrides + a stock characterization report.
        self._audio_adv_btn = ttk.Button(
            self._audio_opts_row, text="Advanced…", width=12,
            command=self._open_audio_advanced)
        _Tooltip(self._audio_adv_btn,
                 "Fine-tune how replacements are encoded: experimental "
                 "head/tail block handling and the anti-pop codec seed — plus "
                 "machine-render preview WAVs on Build.\n\nThese are levers "
                 "for chasing clicks heard on the real machine. Defaults "
                 "match the standard behavior.\n\nA * on the button means at "
                 "least one option is currently OFF its default (they persist "
                 "between sessions) — open the dialog to see which, or to set "
                 "everything back.",
                 lambda: self._current_theme)
        self._audio_profile_btn = ttk.Button(
            self._audio_opts_row, text="Profile vs stock", width=15,
            command=self._audio_profile_click)
        # Right-align the two buttons (the checkbox stays left): pack Profile
        # first so it sits at the right edge, Advanced to its left.
        self._audio_profile_btn.pack(side=tk.RIGHT)
        self._audio_adv_btn.pack(side=tk.RIGHT, padx=(0, 6))
        _Tooltip(self._audio_profile_btn,
                 "Characterize every sound in the scanned extract folder — "
                 "lead-in, fade-out, peak/RMS level, DC offset, spectral "
                 "brightness — and flag replacements that deviate from the "
                 "game's own callout style. Writes audio_profile.csv into "
                 "the extract folder.",
                 lambda: self._current_theme)
        # A persisted experiment setting from a previous session must be
        # visible immediately (the RAW-toggle lesson).
        self._refresh_audio_adv_marker()

        self._refresh_audio_ffmpeg_warning()

    def _refresh_audio_ffmpeg_warning(self):
        """Show the ffmpeg-missing banner only when ffmpeg can't be found.

        Re-probes on each tab visit (the cache is cleared first) so installing
        ffmpeg mid-session via 'Install Missing' clears the banner next time
        the user opens the tab — no app restart needed."""
        warn = getattr(self, "_audio_ffmpeg_warn", None)
        if warn is None:
            return
        from ..core import audio as _audio
        _audio._ffmpeg_path = None  # force a fresh probe, not the cached result
        if _audio.find_ffmpeg():
            warn.pack_forget()
        elif not warn.winfo_ismapped():
            warn.pack(fill=tk.X, padx=12, pady=(0, 4),
                      before=self._audio_assets_row)

    # ---- Replace Audio: scanning -------------------------------------

    def _scan_audio_slots_async(self):
        """Scan the assets folder for audio slots on a worker thread, then
        repopulate the list.  Stale scans are dropped via a bump-counter."""
        import threading
        from ..core.audio_slots import scan_audio_slots

        assets_path = (self.write_assets_var.get() or "").strip()
        self._audio_scan_id += 1
        scan_id = self._audio_scan_id

        if not assets_path or not os.path.isdir(assets_path):
            self._audio_slots = []
            self._audio_slots_by_rel = {}
            self._audio_categories = {}
            self._refresh_audio_type_filter()
            self._refresh_audio_list()
            self._audio_empty.configure(
                text="Set the project folder on the Extract tab, then click Scan.")
            self._audio_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            self._set_tab_scanning("audio", False)
            return

        self._audio_empty.configure(text="Scanning for audio files…")
        self._audio_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Let the plugin narrow the scan to its real audio edit surface
        # (CGC: whole tree; BoF: only _EDITABLE ASSETS/).  Default None
        # scans everything.  Computed in the worker since it walks the tree.
        mfr = self._current_mfr

        def _work():
            try:
                roots = mfr.audio_slot_dirs(assets_path) if mfr else None
            except Exception:
                roots = None
            try:
                exts = mfr.audio_slot_exts(assets_path) if mfr else None
            except Exception:
                exts = None
            try:
                # Fast walk: list slots instantly; per-file format/duration
                # headers are filled in afterwards on a background pass.  A
                # cloud-offloaded (iCloud "Optimize Mac Storage") or network
                # folder makes even the small header reads crawl — the walk
                # itself never opens a file, so the list always appears.
                slots = scan_audio_slots(assets_path, roots=roots, exts=exts,
                                         probe=False)
            except Exception:
                slots = []
            # Type-filter categories: filename rules + the two Auto-name CSVs
            # (two small reads — done here so a slow folder never stalls Tk).
            try:
                from ..core import audio_categories
                cats = audio_categories.classify(
                    assets_path, [s.rel_path for s in slots])
            except Exception:
                cats = {}
            if self._audio_scan_id != scan_id:
                return
            self._tk_root().after(
                0, self._populate_audio_after_scan,
                slots, scan_id, assets_path, cats)

        self._set_tab_scanning("audio", True)
        threading.Thread(target=_work, daemon=True).start()

    def _populate_audio_after_scan(self, slots, scan_id, scan_dir, cats=None):
        """Main-thread: store scan results and refresh the list."""
        if self._audio_scan_id != scan_id:
            return
        self._set_tab_scanning("audio", False)
        self._audio_categories = cats or {}
        if scan_dir != self._audio_scan_dir:
            # A different folder's filter pick means nothing here.
            self.audio_type_var.set("All types")
        self._refresh_audio_type_filter()
        # Same-folder rescan: carry over already-probed metadata for
        # unchanged files so a rescan (transcribe renames, manual Scan)
        # doesn't reset every Length cell to "—" and re-read every header.
        if scan_dir == self._audio_scan_dir:
            old = self._audio_slots_by_rel
            for s in slots:
                prev = old.get(s.rel_path)
                if (prev is not None and prev.info is not None
                        and s.info is None and s.size == prev.size):
                    s.info = prev.info
        self._audio_slots = slots
        self._audio_slots_by_rel = {s.rel_path: s for s in slots}
        # A new folder invalidates any in-memory assignments aimed at the old
        # one — but the new folder may carry assignments persisted from a prior
        # session (its .staged_changes.json sidecar), so restore those.  A
        # re-scan of the SAME folder keeps the live in-memory assignments (newer
        # than the sidecar) and just prunes vanished slots.
        from ..core import staged_changes
        saved_loops = {}
        saved_keep = {}
        # Trim/pad value to restore when the plugin doesn't force the lock:
        # a new folder restores its saved choice (default off); a same-folder
        # re-scan preserves the current one.
        persisted_trim = bool(self.audio_trim_var.get())
        if scan_dir != self._audio_scan_dir:
            staged = self._load_staged_changes(scan_dir)
            self._audio_assignments = staged_changes.live_assignments(
                staged.get("audio"), self._audio_slots_by_rel)
            self._warn_dropped_assignments(
                "audio", staged.get("audio"), self._audio_slots_by_rel,
                scan_dir)
            saved_loops = staged.get("audio_loop") or {}
            saved_keep = staged.get("audio_keep") or {}
            persisted_trim = bool(staged.get("audio_trim", False))
            self._restore_change_filter("audio", staged)
            # "Group duplicates" is NOT persisted/restored: it's off by
            # default and opt-in per session, so a new folder never
            # auto-kicks the (~10 s) bank scan on load.
            self.audio_group_dups_var.set(False)
        else:
            self._audio_assignments = {
                rel: rep for rel, rep in self._audio_assignments.items()
                if rel in self._audio_slots_by_rel}
        # Per-slot Loop flag (BOF): a persisted flag (restored above) wins;
        # otherwise keep any flag the user already toggled, else default ON for
        # "LOOP"-named tracks.
        self._audio_loop_flags = {
            s.rel_path: (bool(saved_loops[s.rel_path])
                         if s.rel_path in saved_loops
                         else self._audio_loop_flags.get(
                             s.rel_path,
                             "loop" in os.path.basename(s.rel_path).lower()))
            for s in slots}
        # Per-slot "keep full length" flag (JJP): a persisted flag wins;
        # otherwise keep any flag the user already toggled this session, else
        # default OFF (every slot is trimmed to the original length unless the
        # user opts a specific one out).
        self._audio_keep_full_flags = {
            s.rel_path: (bool(saved_keep[s.rel_path])
                         if s.rel_path in saved_keep
                         else self._audio_keep_full_flags.get(s.rel_path, False))
            for s in slots}
        self._audio_scan_dir = scan_dir
        # Now that the real extract folder is known, lock the Trim/pad toggle
        # for plugins whose Write is size-neutral for THIS extract (CGC's Pulp
        # Fiction bank slots), or restore the saved/preserved choice otherwise.
        self._apply_audio_trim_lock(self._current_mfr, scan_dir,
                                    persisted_trim=persisted_trim)
        # Drop the previous folder's diff until this folder's background scan
        # repopulates it (avoids a flash of stale "changed" markers).
        self._audio_changed_on_disk = set()
        # Duplicate-group cache: a different folder invalidates it outright;
        # a same-folder rescan keeps it unless a cached member vanished
        # (transcribe renames slots out from under the cached rel_paths).
        if self._audio_dup_scan_dir and self._audio_dup_scan_dir != scan_dir:
            self._audio_dup_groups = None
        elif (self._audio_dup_groups is not None
              and any(r not in self._audio_slots_by_rel
                      for _lbl, _dur, rels in self._audio_dup_groups
                      for r in rels)):
            self._audio_dup_groups = None
        if self.audio_group_dups_var.get():
            self._ensure_audio_dup_groups(quiet=True)
        self._refresh_audio_list()
        # Default to the first slot so a fresh scan shows a preview, matching
        # the Video / Images tabs (feedback batch 21).
        self._select_first_tree_row(self._audio_tree, self._audio_on_tree_select)
        self._start_change_scan("audio")
        # Now fill in duration / format on a background thread so the list is
        # usable immediately even when the folder's contents are slow to read.
        self._probe_audio_metadata_async(scan_id)

    def _run_probe_pass(self, scan_id, current_id_fn, pending, detect,
                        apply_fn):
        """Read per-file metadata for *pending* slots on a worker pool and
        land every result on the main thread.  Shared by the audio / video /
        image background probes.

        Workers NEVER touch Tk: results go into a queue that a main-thread
        after()-loop drains in batches.  The old shape posted each result
        with a cross-thread ``after(0, ...)``, which raises "main thread is
        not in main loop" whenever the main thread spends over ~1 s inside
        one callback — a 2562-row tree rebuild plus the first row's
        spectrogram render does exactly that — and a single raise killed the
        whole pass through its blanket except, leaving every row's metadata
        "—" forever (David's Guardians extract).  A stale pass (a newer scan
        started) stops via *current_id_fn*.
        """
        import queue as queue_mod
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        q = queue_mod.SimpleQueue()
        done = threading.Event()

        def _coordinator():
            try:
                workers = min(8, (os.cpu_count() or 4))
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(detect, s.abs_path): s for s in pending}
                    for fut in as_completed(futs):
                        if current_id_fn() != scan_id:
                            for f in futs:
                                f.cancel()
                            return
                        try:
                            info = fut.result()
                        except Exception:
                            info = None
                        q.put((futs[fut].rel_path, info))
            except Exception:
                pass
            finally:
                done.set()

        def _drain():
            if current_id_fn() != scan_id:
                return
            for _ in range(500):       # bounded per tick: keep the UI live
                try:
                    rel, info = q.get_nowait()
                except queue_mod.Empty:
                    break
                apply_fn(scan_id, rel, info)
            if not (done.is_set() and q.empty()):
                try:
                    self._tk_root().after(100, _drain)
                except tk.TclError:
                    pass                # window torn down

        threading.Thread(target=_coordinator, daemon=True).start()
        _drain()                        # we're on the main thread post-scan

    def _probe_audio_metadata_async(self, scan_id):
        """Read each just-scanned slot's format/duration header off the main
        thread (the probe=False scan walk never opens files), landing each
        row's info via _run_probe_pass."""
        from ..core.audio import detect_audio_info
        pending = [s for s in self._audio_slots if s.info is None]
        if pending:
            self._run_probe_pass(scan_id, lambda: self._audio_scan_id,
                                 pending, detect_audio_info,
                                 self._apply_audio_meta)

    def _apply_audio_meta(self, scan_id, rel, info):
        """Main-thread: store a probed slot's metadata and update its row."""
        if self._audio_scan_id != scan_id:
            return
        slot = self._audio_slots_by_rel.get(rel)
        if slot is None:
            return
        slot.info = info
        tree = getattr(self, "_audio_tree", None)
        if tree is None or not tree.exists(rel):
            return
        tree.set(rel, "len", slot.duration_str())
        tree.set(rel, "fmt", slot.format_summary())

    # ---- Replace Audio: duplicate grouping (CGC banks) ----------------

    def _on_audio_group_dups_toggle(self):
        """Checkbox click: warm the group cache (not persisted — off by
        default each session)."""
        if self.audio_group_dups_var.get():
            self._ensure_audio_dup_groups()

    def _audio_dup_siblings(self, rel):
        """The other present slots that share *rel*'s duplicate group (byte
        -identical factory audio), or [] when the dup scan hasn't run or
        *rel* isn't in a multi-slot group.  Drives the right-click "Apply to
        all copies" fan-out — the action that keeps the machine from playing
        a still-stock twin of a modded sound."""
        if not self._audio_dup_groups:
            return []
        for _label, _dur, rels in self._audio_dup_groups:
            if rel in rels:
                return [r for r in rels
                        if r != rel and r in self._audio_slots_by_rel]
        return []

    def _audio_fanout_to_copies(self, rel):
        """Assign *rel*'s replacement to every other copy in its duplicate
        group, so one edit covers all the identical-audio slots the game
        might play.  No-op (with a nudge) if the slot has no replacement or
        no duplicates."""
        rep = self._audio_assignments.get(rel)
        siblings = self._audio_dup_siblings(rel)
        if not rep or not siblings:
            return
        for sib in siblings:
            self._audio_assignments[sib] = rep
        self._save_staged_changes()
        self.append_log(
            "Replace Audio: applied %s to %d duplicate cop%s of %s"
            % (os.path.basename(rep), len(siblings),
               "y" if len(siblings) == 1 else "ies", rel), "info")
        self._refresh_audio_list()
        self.audio_status_var.set(
            "Applied to %d duplicate copy%s of this sound."
            % (len(siblings), "" if len(siblings) == 1 else "ies"))

    def _ensure_audio_dup_groups(self, quiet=False):
        """Start the bank duplicate scan unless the cache already matches
        the current folder.  Runs on a worker thread (~10 s on a full PF
        extract); the list stays flat until the groups land.  *quiet*
        suppresses the error popup (used by the automatic re-check after a
        slot scan, where a modal would interrupt unprompted)."""
        import threading
        assets = (self._audio_scan_dir
                  or (self.write_assets_var.get() or "").strip())
        mfr = self._current_mfr
        if (not assets or not os.path.isdir(assets)
                or getattr(mfr, "find_duplicate_sounds", None) is None):
            return
        if (self._audio_dup_groups is not None
                and self._audio_dup_scan_dir == assets):
            self._refresh_audio_list()
            return
        if self._audio_dup_scanning:
            return
        self._audio_dup_scan_id += 1
        my_id = self._audio_dup_scan_id
        self._audio_dup_scanning = True
        # The bank scan takes ~10 s and the list can't group until it lands,
        # so show an immediate busy state instead of a dead pause: clear the
        # list to a centred "scanning" overlay (the same shape as the slot
        # scan) so the click visibly does something right away.
        self._set_audio_dup_scanning(True)

        def _work():
            # Off the main thread: never touch Tk here.
            try:
                res = mfr.find_duplicate_sounds(assets)
            except Exception as e:  # noqa: BLE001 — surfaced on main thread
                res = e
            try:
                self._tk_root().after(
                    0, self._apply_audio_dup_groups, my_id, assets, res,
                    quiet)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _set_audio_dup_scanning(self, active):
        """Show/clear the "grouping duplicates" busy state on the audio list.

        While active, the list is replaced by a centred overlay so the
        checkbox click reacts instantly (the bank scan runs on a worker
        thread for ~10 s).  Clearing is handled by the next
        :meth:`_refresh_audio_list`, which hides the overlay once slots are
        drawn again — so this only needs to paint the busy state."""
        if not active:
            return
        tree = getattr(self, "_audio_tree", None)
        if tree is not None:
            try:
                tree.delete(*tree.get_children())
            except tk.TclError:
                pass
        self.audio_status_var.set("Grouping duplicates…")
        if hasattr(self, "_audio_empty"):
            self._audio_empty.configure(
                text="⏳  Scanning the sound banks for duplicates…\n"
                     "(about ten seconds)")
            self._audio_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _apply_audio_dup_groups(self, my_id, assets, res, quiet=False):
        """Main-thread: store the dup-scan result as ``(label, dur_str,
        [rel_path, …])`` tuples keyed like the slot list, or untick and
        surface the scan error (e.g. a WPC-remake extract has no banks)."""
        if my_id != self._audio_dup_scan_id:
            return
        self._audio_dup_scanning = False
        if isinstance(res, Exception):
            self._audio_dup_groups = []            # nothing to group
            self.audio_group_dups_var.set(False)   # trace refreshes the list
            self._refresh_audio_list()             # ensure overlay clears
            if not quiet:
                messagebox.showinfo("Can't group duplicates", str(res))
            return

        def _dur(sec):
            m, s = divmod(max(0.0, float(sec or 0)), 60)
            return "%d:%06.3f" % (int(m), s)

        groups = []
        for g in getattr(res, "groups", ()):
            # Slots without a resolvable WAV (missing file / stale v1
            # decode dir) have no row in this tab — drop them; a group
            # needs 2+ present rows to be worth a parent.
            rels = [os.path.relpath(s.wav_path, assets).replace(os.sep, "/")
                    for s in g.slots if s.wav_path]
            if len(rels) >= 2:
                stem = os.path.splitext(os.path.basename(rels[0]))[0]
                groups.append((stem, _dur(g.duration_seconds), rels))
        self._audio_dup_groups = groups
        self._audio_dup_scan_dir = assets
        self._refresh_audio_list()

    # ---- Replace tabs: on-disk change diff (shared) ------------------

    def _start_change_scan(self, kind):
        """Background-diff the *kind* (audio/video/image) slots against the
        Extract baseline so the tab can flag + count slots already changed on
        disk by a previous build, matching the Write tab and the actual build.

        Runs off the UI thread (the slot list is already shown), then updates
        ``self._<kind>_changed_on_disk`` and refreshes the list.  Snapshotted
        slots are known-changed and skipped from hashing; the rest are MD5'd."""
        import threading
        from ..core import checksums, staged_originals

        assets_path = (self.write_assets_var.get() or "").strip()
        slots = getattr(self, "_%s_slots" % kind, [])
        rels = [s.rel_path for s in slots]
        refresh = {"audio": self._refresh_audio_list,
                   "video": self._refresh_video_list,
                   "image": self._refresh_image_list}.get(kind)
        self._change_scan_id += 1
        scan_id = self._change_scan_id
        if not assets_path or not os.path.isdir(assets_path) or not rels:
            setattr(self, "_%s_changed_on_disk" % kind, set())
            return
        root = self.root

        def _work():
            try:
                baseline = checksums.read_baseline_any(assets_path)
                rel_set = set(rels)
                snaps = {r for r in staged_originals.snapshot_rels(assets_path)
                         if r in rel_set}
                to_hash = [r for r in rels if r not in snaps]
                changed = snaps | checksums.changed_rels(
                    assets_path, to_hash, baseline=baseline)
            except Exception:
                changed = set()

            def _apply():
                if self._change_scan_id != scan_id:
                    return            # superseded by a newer scan
                setattr(self, "_%s_changed_on_disk" % kind, changed)
                if refresh:
                    refresh()
            # A busy main thread (>1 s inside one callback — big tree
            # rebuild, spectrogram render) makes this cross-thread after()
            # raise RuntimeError; retry until it lands so the changed-marks
            # aren't silently lost.  TclError = window torn down: give up.
            import time as _time
            for _ in range(50):
                try:
                    root.after(0, _apply)
                    break
                except RuntimeError:
                    _time.sleep(0.2)
                except tk.TclError:
                    break

        # Spawn through the event loop (after-idle) rather than synchronously, so
        # a caller that builds + tears down the window without running the loop
        # (the GUI tests) never leaks a worker thread that would race Tcl during
        # teardown — the fixture's pending-after cancel sweeps this away.
        def _spawn():
            threading.Thread(target=_work, daemon=True).start()
        try:
            root.after(0, _spawn)
        except (tk.TclError, RuntimeError):
            pass

    def _slot_changed_on_disk(self, kind, rel):
        """Whether *kind* (audio/video/image) slot *rel* is already modified
        on disk: flagged by the background change scan, or carrying a ``.orig``
        snapshot — which is proof of a staged change all by itself and is
        available IMMEDIATELY.  The change scan MD5s every slot (minutes over
        a NAS share), and until it lands the previews treated a modified slot
        as pristine: a tester clicked his attract slot inside that window
        and the "Original" pane played his previous replacement (batch 25)."""
        if rel in getattr(self, "_%s_changed_on_disk" % kind, ()):
            return True
        from ..core import staged_originals
        return staged_originals.snapshot_path(
            getattr(self, "_%s_scan_dir" % kind, None), rel) is not None

    # ---- Replace tabs: change-state filter (shared) -------------------

    # The three modes of the audio / video / image "Show" dropdown.
    _CHANGE_FILTER_VALUES = ("All", "Changed", "Unchanged")

    def _build_change_filter(self, parent, kind, tip=None):
        """Build the "Show: All / Changed / Unchanged" dropdown for a Replace
        tab and return its frame (unpacked — the caller places it).

        The list refresh comes off the variable's own trace (set up with the
        tab's other filters), so this only has to persist the choice.  *tip*
        overrides the tooltip for a tab where "changed" means something else
        (Text: an edited string, not a staged file)."""
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="Show:").pack(side=tk.LEFT)
        combo = ttk.Combobox(
            frame, textvariable=getattr(self, "%s_change_filter_var" % kind),
            state="readonly", width=10, values=self._CHANGE_FILTER_VALUES)
        combo.pack(side=tk.LEFT, padx=(4, 0))
        combo.bind("<<ComboboxSelected>>",
                   lambda _e: self._save_staged_changes())
        _Tooltip(
            combo,
            tip or
            "Narrow the list by what you've already done to it. Changed = the "
            "slots with a pending replacement or already changed on disk by a "
            "previous build. Unchanged = everything you haven't touched yet, "
            "so a part-finished pass is what's left in front of you instead "
            "of something to scroll past.",
            lambda: self._current_theme)
        setattr(self, "_%s_change_filter_frame" % kind, frame)
        setattr(self, "_%s_change_filter_combo" % kind, combo)
        return frame

    def _change_filter_pred(self, kind):
        """A ``predicate(rel_path)`` for *kind*'s Show filter, or None for
        "All" (nothing to filter).

        "Changed" is a pending assignment OR a slot already changed on disk by
        a previous build — the same set the status line counts — and
        "Unchanged" is exactly its complement, so the two views together are
        always the whole folder."""
        mode = getattr(self, "%s_change_filter_var" % kind).get()
        if mode not in ("Changed", "Unchanged"):
            return None
        touched = (set(getattr(self, "_%s_assignments" % kind))
                   | getattr(self, "_%s_changed_on_disk" % kind))
        want_changed = (mode == "Changed")
        return lambda rel: (rel in touched) == want_changed

    def _restore_change_filter(self, kind, staged):
        """Restore *kind*'s Show filter from a folder's staged-changes sidecar.

        Sidecars written before the dropdown existed carry the "changed only"
        boolean it replaced; a ticked box restores as "Changed"."""
        var = getattr(self, "%s_change_filter_var" % kind)
        val = staged.get("%s_change_filter" % kind)
        if val in self._CHANGE_FILTER_VALUES:
            var.set(val)
        elif "%s_changed_only" % kind in staged:
            var.set("Changed" if staged["%s_changed_only" % kind] else "All")

    # ---- Replace tabs: click-header sorting (shared) -----------------

    @staticmethod
    def _double_click_on_rows(tree, event):
        """True if a <Double-1> landed on a data row (region "tree"/"cell").

        Clicking a sortable column header fast enough registers as a
        double-click too; without this guard it falls through to the row
        action — the image tab popped "No Slot Selected" mid-sort
        (a tester).  A None event (programmatic call) is allowed through."""
        if event is None:
            return True
        return tree.identify_region(event.x, event.y) in ("tree", "cell")

    def _sort_click(self, state_attr, col, default_desc, refresh_fn):
        """Header-click handler: toggle direction when already sorting by
        *col*, otherwise switch to *col* at its default direction, then
        re-sort + rebuild via *refresh_fn*."""
        cur = getattr(self, state_attr, None)
        desc = (not cur[1]) if (cur and cur[0] == col) else default_desc
        setattr(self, state_attr, (col, desc))
        refresh_fn()

    def _wire_sort_headings(self, tree, config, state_attr, refresh_fn):
        """Attach a click-to-sort command to each header in *config*
        (list of ``(col_id, base_text, default_desc)``).  Only the command is
        set — the heading's existing text/anchor is left intact; the ▲/▼
        arrow is applied per-refresh by :meth:`_show_sort_arrows`."""
        for col_id, _base, default_desc in config:
            tree.heading(
                col_id,
                command=lambda c=col_id, d=default_desc:
                    self._sort_click(state_attr, c, d, refresh_fn))

    @staticmethod
    def _show_sort_arrows(tree, config, active):
        """Render a ▲/▼ suffix on the active sort column's header (plain text
        on the others).  Setting only ``text`` preserves each column's anchor.
        """
        col, desc = active
        arrow = "  ▼" if desc else "  ▲"
        for col_id, base, _d in config:
            tree.heading(col_id, text=(base + arrow) if col_id == col else base)

    _AUDIO_TYPE_KEYS = {"Music": "music", "Sound FX": "sfx",
                        "Callouts": "callouts", "Other": "other"}

    def _audio_type_filter(self):
        """The active Type filter's internal key, or None for "All types"."""
        return self._AUDIO_TYPE_KEYS.get(self.audio_type_var.get())

    def _refresh_audio_type_filter(self):
        """Show the Type dropdown only when the scanned folder classifies —
        an extract with no Auto-name artifacts is all "Other", and a filter
        that can't split anything is just clutter."""
        frame = getattr(self, "_audio_type_frame", None)
        if frame is None:
            return
        useful = any(c != "other" for c in self._audio_categories.values())
        if useful and not frame.winfo_ismapped():
            frame.pack(side=tk.LEFT, before=self._audio_change_filter_frame)
        elif not useful and frame.winfo_ismapped():
            frame.pack_forget()
        if not useful:
            self.audio_type_var.set("All types")

    def _refresh_audio_list(self):
        """Apply the search filter + sort and repopulate the slot tree — flat,
        or two-level when "Group duplicates" is on and the bank duplicate scan
        has run for this folder: one collapsed parent per group of
        byte-identical factory audio (longest first, the dup scan's order),
        its member slots nested, every unique slot flat below the groups."""
        tree = getattr(self, "_audio_tree", None)
        if tree is None:
            return

        _CAT_DISP = {"music": "Music", "sfx": "Sound FX",
                     "callouts": "Callouts"}

        def _cat_disp(rel):
            return _CAT_DISP.get(self._audio_categories.get(rel), "Other")
        # Keep the groups the user expanded open across a rebuild (assigning,
        # filtering and sorting all funnel through here).
        open_groups = set()
        for iid in tree.get_children():
            if iid.startswith(_AUD_DUP_GROUP_IID):
                try:
                    if tree.item(iid, "open") in (1, True, "true"):
                        open_groups.add(iid)
                except tk.TclError:
                    pass
        tree.delete(*tree.get_children())

        query = (self.audio_search_var.get() or "").strip().lower()
        type_key = self._audio_type_filter()
        cats = self._audio_categories
        from ..core import audio_categories as _ac
        change_ok = self._change_filter_pred("audio")

        def _passes(s):
            if query and query not in s.rel_path.lower():
                return False
            if change_ok is not None and not change_ok(s.rel_path):
                return False
            if type_key is None:
                return True
            # Duration from the probed header, else instantly from a
            # Length-prefix name — the Music filter is duration-aware.
            dur = s.duration or _ac.name_duration_seconds(
                os.path.basename(s.rel_path)) or 0.0
            return _ac.matches_filter(
                cats.get(s.rel_path, "other"), dur, type_key)

        slots = [s for s in self._audio_slots if _passes(s)]
        col, desc = self._audio_sort

        changed = self._audio_changed_on_disk

        def _key(s):
            if col == "len":
                return (s.duration,)
            if col == "fmt":
                return (s.format_summary().lower(), s.rel_path.lower())
            if col == "rep":
                rep = self._audio_assignments.get(s.rel_path)
                # Assigned (and already-changed-on-disk) rows group together; the
                # rest fall to the bottom (ascending) regardless of direction.
                if rep:
                    return (0, os.path.basename(rep).lower())
                if s.rel_path in changed:
                    return (1, "")
                return (2, "")
            if col == "loop":
                return (1 if self._audio_loop_flags.get(s.rel_path) else 0,)
            if col == "keep":
                return (1 if self._audio_keep_full_flags.get(s.rel_path)
                        else 0,)
            if col == "type":
                return (_cat_disp(s.rel_path), s.rel_path.lower())
            return (s.rel_path.lower(),)  # "#0" name/path

        self._show_sort_arrows(tree, self._audio_sort_cfg, self._audio_sort)

        def _insert(parent, s):
            rep = self._audio_assignments.get(s.rel_path)
            is_changed = s.rel_path in changed
            if rep:
                # green = staged (a pick not built yet); blue = already built
                # into the working copy.  Same colours as the Write tab.
                rep_disp = os.path.basename(rep)
                tag = "changed" if is_changed else "assigned"
            elif is_changed:
                # Differs from the Extract baseline but wasn't reassigned this
                # session — a previous build OR a hand-edit in the folder.  It
                # WILL still be in the next build (Write repacks anything that
                # differs from the baseline), so surface it: the count matches
                # the Write tab; right-click → Revert to undo it.
                rep_disp, tag = "✓ changed on disk", "changed"
            else:
                rep_disp, tag = "Choose…", ""
            loop_disp = "☑" if self._audio_loop_flags.get(s.rel_path) else "☐"
            keep_disp = ("☑" if self._audio_keep_full_flags.get(s.rel_path)
                         else "☐")
            # NOTE: user-renamed rows used to get their own (warning-hue)
            # colour — batch 14.  Batch 20 reversed it: a colour change should
            # mean "modified", full stop; with auto-naming recolouring half
            # the list, the signal read as noise.  Only staged (green) and
            # changed-on-disk (blue) rows colour now.
            tree.insert(parent, tk.END, iid=s.rel_path, text=s.rel_path,
                        values=(s.duration_str(), s.format_summary(),
                                rep_disp, loop_disp, keep_disp,
                                _cat_disp(s.rel_path)),
                        tags=(tag,) if tag else ())

        grouped = (bool(self.audio_group_dups_var.get())
                   and self._audio_dup_groups is not None
                   and self._audio_dup_scan_dir == self._audio_scan_dir)
        if grouped:
            # Duplicate groups first (dup-scan order = longest first), then
            # everything unique flat below.  Members keep the scan's
            # bank/slot order on the default sort; a header click re-sorts
            # WITHIN each group, like the image tab's scene grouping.  The
            # group iid is the group's position in the cached list, so the
            # open-state survives filtering/sorting rebuilds.
            in_groups = set()
            for gidx, (label, dur_str, rels) in enumerate(
                    self._audio_dup_groups):
                members = [self._audio_slots_by_rel[r] for r in rels
                           if r in self._audio_slots_by_rel]
                visible = [m for m in members if _passes(m)]
                if len(members) < 2 or not visible:
                    continue
                in_groups.update(m.rel_path for m in visible)
                if col == "#0":
                    if desc:
                        visible = list(reversed(visible))
                else:
                    visible = sorted(visible, key=_key, reverse=desc)
                touched_n = sum(
                    1 for m in members
                    if m.rel_path in self._audio_assignments
                    or m.rel_path in changed)
                giid = _AUD_DUP_GROUP_IID + str(gidx)
                tree.insert(
                    "", tk.END, iid=giid, open=(giid in open_groups),
                    text="%s — %d copies" % (label, len(members)),
                    values=(dur_str, "",
                            ("%d of %d modded" % (touched_n, len(members))
                             if touched_n else ""),
                            "", "", ""))
                for m in visible:
                    _insert(giid, m)
            rest = [s for s in slots if s.rel_path not in in_groups]
            rest.sort(key=_key, reverse=desc)
            for s in rest:
                _insert("", s)
        else:
            slots.sort(key=_key, reverse=desc)
            for s in slots:
                _insert("", s)

        total = len(self._audio_slots)
        # Count what the build will actually change: assignments made this
        # session PLUS files already changed on disk (earlier builds / hand
        # edits).  This is what the Write tab and the build apply.
        changed_total = len(set(self._audio_assignments) | changed)
        if total == 0:
            self.audio_status_var.set("")
            self._audio_empty.configure(
                text="No .wav / .ogg audio found in this folder.")
            self._audio_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            shown = len(slots)
            extra = f"  ({shown} shown)" if shown != total else ""
            self.audio_status_var.set(
                f"{changed_total} of {total} slots changed{extra}")
            if shown == 0:
                # Everything filtered out — say so, or an empty list reads
                # like a failed scan.  An empty category that an Auto-name
                # pass would populate says which one (David's LZ extract:
                # blank Callouts pane because transcription never ran).
                hint = "Nothing matches the Search / Show / Type filters."
                if not query and type_key == "callouts":
                    hint = ("No call-outs identified in this folder yet.\n"
                            "Tick \"Auto-name call-outs\" on the Extract tab "
                            "to transcribe and name the speech files.")
                elif not query and type_key == "music":
                    hint = ("No music identified in this folder — no music "
                            "banks, no track 20 seconds or longer, and no "
                            "Auto-name music results.")
                elif not query and type_key is None:
                    # An empty change-state view is an answer, not a dead end:
                    # "nothing left to do" and "nothing done yet" both read as
                    # a failed scan without this.
                    mode = self.audio_change_filter_var.get()
                    if mode == "Unchanged":
                        hint = ("Every slot in this folder has a replacement "
                                "or already differs from the extract — "
                                "nothing is left unchanged.")
                    elif mode == "Changed":
                        hint = "Nothing in this folder has been changed yet."
                self._audio_empty.configure(text=hint)
                self._audio_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            else:
                self._audio_empty.place_forget()
        # Fit-to-content column widths (the toggle columns stay fixed).
        self._autosize_tree_columns(tree, "audio", ("#0", "len", "fmt", "rep"))

    def _maybe_rescan_audio(self):
        """Auto-scan when the Replace Audio tab becomes visible and the
        folder has changed since the last scan."""
        if self._current_mfr is None:
            return
        if not getattr(self._current_mfr.capabilities, "replace_audio", False):
            return
        assets_path = (self.write_assets_var.get() or "").strip()
        if assets_path and assets_path != self._audio_scan_dir:
            self._scan_audio_slots_async()

    # ---- Replace Audio: per-slot actions -----------------------------

    def _audio_selected_rel(self):
        sel = self._audio_tree.selection() if hasattr(self, "_audio_tree") else ()
        return sel[0] if sel else None

    def _audio_assign_selected(self):
        rel = self._audio_selected_rel()
        if rel is None:
            messagebox.showinfo(
                "No Slot Selected",
                "Select a track in the list first, then choose a replacement.")
            return
        self._audio_assign_rel(rel)

    def _audio_assign_rel(self, rel):
        """Open the replacement picker for *rel* and record the assignment."""
        if not rel or rel not in self._audio_slots_by_rel:
            return
        # Nothing may still be playing behind the picker (batch 28) — see
        # stop_playback_for_picker.
        self.stop_playback_for_picker()
        path = filedialog.askopenfilename(
            title=f"Choose a replacement for {rel}",
            initialdir=self.last_browse_dir("audio_replacement"),
            filetypes=[("Audio files",
                        "*.wav *.ogg *.mp3 *.flac *.m4a *.aac *.opus "
                        "*.wma *.aiff *.aif"),
                       ("All files", "*.*")])
        if not path:
            return
        self.remember_browse_dir("audio_replacement", path)
        self._audio_assignments[rel] = path
        self._save_staged_changes()
        # Staged replacements get a log line so the run can be double-checked
        # afterwards (feedback batch 11).
        self.append_log("Replace Audio: %s ← %s"
                        % (rel, os.path.basename(path)), "info")
        self._refresh_audio_list()
        if rel == self._audio_current_rel:
            self._audio_load_rep_pane(rel)  # show the new pick right away
        try:
            self._audio_tree.selection_set(rel)
            self._audio_tree.see(rel)
        except tk.TclError:
            pass

    # ---- Replace Audio: table interactions ---------------------------

    def _cancel_audio_select_job(self):
        if self._audio_select_job is not None:
            try:
                self._tk_root().after_cancel(self._audio_select_job)
            except Exception:
                pass
            self._audio_select_job = None

    def _audio_on_tree_select(self, _event=None):
        # Debounce: render the selected original's seek-bar strip after a
        # short idle, so arrowing through the list doesn't fire ffmpeg per row.
        self._cancel_audio_select_job()
        self._audio_select_job = self._tk_root().after(
            250, self._audio_preview_selected)

    def _audio_preview_selected(self):
        self._audio_select_job = None
        rel = self._audio_selected_rel()
        if rel is None or rel == self._audio_current_rel:
            return
        # Selecting a different row while something plays stops it and loads
        # the new row right away (feedback batch 14: needing a second click
        # left the OLD sample in the player, and near the end of a play it
        # wasn't obvious the new row hadn't loaded).  Resume playing on the
        # same pane so click-through listening keeps flowing.
        resume = None
        if self._audio_pane_orig and self._audio_pane_orig.playing:
            resume = "orig"
        elif self._audio_pane_rep and self._audio_pane_rep.playing:
            resume = "rep"
        self._audio_load_track(rel, autoplay=resume)

    def _audio_on_tree_double(self, _event=None):
        # Double-click = choose a replacement, same as the Images tab (playback
        # lives on the right-click menu + the preview panes' transport buttons;
        # single click still previews).  Feedback batch 11: double-click did
        # replace-dialog on images/text but PLAYED on audio/video.  The first
        # click of the double already selected the row.
        if not self._double_click_on_rows(self._audio_tree, _event):
            return
        self._cancel_audio_select_job()
        self._audio_assign_selected()

    def _audio_on_tree_click(self, event):
        # A click in the Replacement column opens the picker (the column is a
        # per-row "Choose…" button); a click in the Loop or Full column toggles
        # that slot's flag.  Other columns fall through to normal selection.
        # Resolve the clicked display column to its data-column NAME so it works
        # regardless of which optional columns are shown (displaycolumns).
        tree = self._audio_tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        row = tree.identify_row(event.y)
        if not row:
            return
        name = self._audio_tree_col_name(tree.identify_column(event.x))
        if name == "rep":
            tree.selection_set(row)
            self._cancel_audio_select_job()
            self._audio_assign_rel(row)
        elif name == "loop":
            self._audio_toggle_loop(row)
        elif name == "keep":
            self._audio_toggle_keep(row)

    def _audio_tree_col_name(self, display_col):
        """Map a Treeview display-column id ('#1', '#2', …) to its data-column
        NAME, honoring the current displaycolumns.  Returns None for '#0' or an
        out-of-range id."""
        tree = self._audio_tree
        if not display_col or display_col == "#0":
            return None
        disp = tree["displaycolumns"]
        cols = tree["columns"] if disp in ("#all", (), "") else disp
        try:
            i = int(display_col[1:]) - 1
        except (ValueError, IndexError):
            return None
        return cols[i] if 0 <= i < len(cols) else None

    def _audio_toggle_loop(self, rel):
        """Flip a slot's Loop flag and redraw just its glyph."""
        if rel not in self._audio_slots_by_rel:
            return
        new = not self._audio_loop_flags.get(rel, False)
        self._audio_loop_flags[rel] = new
        self._save_staged_changes()
        try:
            vals = list(self._audio_tree.item(rel, "values"))
            if len(vals) >= 4:
                vals[3] = "☑" if new else "☐"
                self._audio_tree.item(rel, values=vals)
        except tk.TclError:
            pass

    def _audio_toggle_keep(self, rel):
        """Flip a slot's "keep full length" flag and redraw just its glyph."""
        if rel not in self._audio_slots_by_rel:
            return
        new = not self._audio_keep_full_flags.get(rel, False)
        self._audio_keep_full_flags[rel] = new
        self._save_staged_changes()
        try:
            vals = list(self._audio_tree.item(rel, "values"))
            if len(vals) >= 5:
                vals[4] = "☑" if new else "☐"
                self._audio_tree.item(rel, values=vals)
        except tk.TclError:
            pass

    _AUDIO_LOOP_TIP_TEXT = (
        "Loop this replacement in-game.\n\n"
        "These music stems normally play once — there's no built-in loop — so "
        "a replacement that's shorter than the original goes silent partway "
        "through its mode. Ticking Loop bakes a forward-loop flag into the "
        "rebuilt audio (the same loop_mode flag Godot's importer would set), "
        "so the engine repeats your clip to fill the mode; the game stops or "
        "fades it on the next song change.\n\n"
        "Defaults ON for tracks with \"LOOP\" in the name (the mode music). "
        "Leave it OFF for one-shot sound effects and callouts.")

    _AUDIO_KEEP_TIP_TEXT = (
        "Keep this replacement's full length.\n\n"
        "By default every track is trimmed (or padded) to its original slot "
        "length on Write. Tick Full to skip that for this one slot, so a longer "
        "replacement plays at its full length.\n\n"
        "The file validates and boots at any length (the game's checksums are "
        "re-forged regardless of size). Whether it actually plays to the end is "
        "up to the game: best for a cue nothing plays over — e.g. the "
        "end-of-game track before attract — since the show may still cut it "
        "short. Test on the machine.")

    def _audio_on_tree_motion(self, event):
        """Show the Loop- or Full-column explainer tooltip while hovering it."""
        tree = self._audio_tree
        region = tree.identify_region(event.x, event.y)
        name = (self._audio_tree_col_name(tree.identify_column(event.x))
                if region in ("cell", "heading") else None)
        if name == "loop":
            self._show_audio_loop_tip(event, self._AUDIO_LOOP_TIP_TEXT)
        elif name == "keep":
            self._show_audio_loop_tip(event, self._AUDIO_KEEP_TIP_TEXT)
        else:
            self._hide_audio_loop_tip()

    def _show_audio_loop_tip(self, event, text=None):
        if self._audio_loop_tip is not None:
            return
        try:
            c = THEMES[self._current_theme]
            tip = tk.Toplevel(self._audio_tree)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(
                f"+{event.x_root + 14}+{event.y_root + 18}")
            tip.configure(background=c["tooltip_bg"])
            tk.Label(
                tip, text=text or self._AUDIO_LOOP_TIP_TEXT,
                background=c["tooltip_bg"], foreground=c["tooltip_fg"],
                relief="solid", borderwidth=1, font=(_SANS_FONT, 9),
                padx=6, pady=4, wraplength=360, justify=tk.LEFT).pack()
            self._audio_loop_tip = tip
        except tk.TclError:
            self._audio_loop_tip = None

    def _hide_audio_loop_tip(self):
        if self._audio_loop_tip is not None:
            try:
                self._audio_loop_tip.destroy()
            except tk.TclError:
                pass
            self._audio_loop_tip = None

    def _audio_on_tree_right(self, event):
        tree = self._audio_tree
        row = tree.identify_row(event.y)
        if not row:
            return
        if row not in self._audio_slots_by_rel:
            return  # "Group duplicates" parent row — no per-slot actions
        tree.selection_set(row)
        menu = tk.Menu(tree, tearoff=0)
        c = THEMES.get(self._current_theme, {})
        try:
            menu.configure(
                background=c.get("field_bg"), foreground=c.get("fg"),
                activebackground=c.get("select_bg"),
                activeforeground="#ffffff")
        except tk.TclError:
            pass
        menu.add_command(label="▶  Play original",
                         command=self._audio_play_original)
        menu.add_command(label="Choose replacement…",
                         command=lambda r=row: self._audio_assign_rel(r))
        # Properties (rename + Type): only decode-shaped names (idx#### /
        # music_cat##_####) — the index prefix is preserved so Write still
        # maps the slot; every other plugin keys audio by its full path,
        # which a rename would break.  Was "Rename…", but the dialog also
        # recategorizes, which that label hid (a tester).
        from ..core import name_memory as _nmem
        if _nmem.split_decode_name(os.path.basename(row)):
            menu.add_command(label="Properties…  (name / type)",
                             command=lambda r=row: self._audio_rename_slot(r))
        has_assignment = bool(self._audio_assignments.get(row))
        is_built = row in self._audio_changed_on_disk
        if has_assignment:
            menu.add_command(label="▶  Play replacement",
                             command=self._audio_play_replacement)
        # Fan-out: push this slot's replacement onto every copy that shares
        # its factory audio, so the machine can't play a still-stock twin.
        # Needs the duplicate scan (Group duplicates) to have run.
        siblings = self._audio_dup_siblings(row)
        if has_assignment and siblings:
            menu.add_command(
                label="⧉  Apply to all %d copies of this sound"
                      % (len(siblings) + 1),
                command=lambda r=row: self._audio_fanout_to_copies(r))
        # One undo action, by state — never both (they confused users):
        #   * built into the working copy → "Revert to original" restores the
        #     file on disk (and drops any pick);
        #   * a pick not built yet → "Remove replacement" just drops the pick
        #     (there's nothing on disk to restore).
        if is_built:
            menu.add_separator()
            menu.add_command(label="↺  Revert to original",
                             command=self._audio_revert_selected)
        elif has_assignment:
            menu.add_separator()
            menu.add_command(label="Remove replacement",
                             command=self._audio_clear_selected)
        slot = self._audio_slots_by_rel.get(row)
        if slot is not None:
            menu.add_separator()
            menu.add_command(
                label=self._reveal_menu_label(),
                command=lambda p=slot.abs_path: self._reveal_in_file_manager(p))
            self._add_find_in_partition_item(menu, "audio", row)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _add_find_in_partition_item(self, menu, kind, rel):
        """Add "Find in Partition Explorer" to a Replace-tab row menu, for the
        plugins whose extracts record on-card locations (Stern Spike 2)."""
        if not self._tab_visible("Partition Explorer"):
            return
        menu.add_command(
            label="Find in Partition Explorer",
            command=lambda k=kind, r=rel: self._asset_find_in_partition(k, r))

    def _audio_clear_selected(self):
        rel = self._audio_selected_rel()
        if rel is not None and rel in self._audio_assignments:
            del self._audio_assignments[rel]
            self._save_staged_changes()
            self.append_log("Replace Audio: cleared replacement for %s" % rel,
                            "info")
            self._refresh_audio_list()
            if rel == self._audio_current_rel:
                self._audio_load_rep_pane(rel)  # back to "no replacement"
            try:
                self._audio_tree.selection_set(rel)
            except tk.TclError:
                pass

    def _load_sound_test_suggestions(self):
        """The game's own Sound-Test menu names from the assets folder's
        ``sound_test_names.csv`` (written by Extract), for the Rename dialog's
        suggestion list.  [] when the folder has none (non-Stern, older
        extract)."""
        import csv
        path = os.path.join(self._audio_scan_dir or "", "sound_test_names.csv")
        if not self._audio_scan_dir or not os.path.isfile(path):
            return []
        rows = []
        try:
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    nm = (row.get("name") or "").strip()
                    num = (row.get("sound_number") or "").strip()
                    if nm:
                        rows.append((int(num) if num.isdigit() else 10**9,
                                     nm))
        except Exception:
            return []
        # Numeric menu order; the "#num" lead means typing "87" jumps to the
        # entry you just played on the machine's Sound Test.
        return ["#%d  %s" % (n, nm) if n < 10**9 else nm
                for n, nm in sorted(rows)]

    _AUDIO_CAT_NAMES = (("music", "Music"), ("sfx", "Sound FX"),
                        ("callouts", "Callouts"), ("other", "Other"))

    def _ask_audio_name(self, prompt, initial, suggestions, category="other"):
        """Modal rename prompt: an editable combo seeded with the game's
        Sound-Test menu names (pick one or type your own) plus a Type picker
        so a mis-bucketed slot can be recategorized in the same step
        (feedback batch 14: an SFX classed as a callout).  Returns
        ``(text, category_key)``, or None on cancel."""
        root = self._tk_root()
        dlg = tk.Toplevel(root)
        dlg.title("Audio Properties")
        dlg.transient(root)
        dlg.resizable(False, False)
        self._theme_toplevel(dlg)
        ttk.Label(dlg, text=prompt, justify=tk.LEFT).pack(
            anchor=tk.W, padx=12, pady=(12, 4))
        if suggestions:
            ttk.Label(
                dlg, text="Pick one of the game's own Sound Test names, or "
                          "type anything:",
                font=(_SANS_FONT, 8, "italic")).pack(anchor=tk.W, padx=12)
        var = tk.StringVar(value=initial)
        combo = ttk.Combobox(dlg, textvariable=var,
                             values=tuple(suggestions or ()), width=52)
        combo.pack(fill=tk.X, padx=12, pady=(2, 8))
        cat_disp = dict(self._AUDIO_CAT_NAMES)
        cat_keys = {v: k for k, v in self._AUDIO_CAT_NAMES}
        cat_row = ttk.Frame(dlg)
        cat_row.pack(fill=tk.X, padx=12, pady=(0, 8))
        ttk.Label(cat_row, text="Type:").pack(side=tk.LEFT)
        cat_var = tk.StringVar(value=cat_disp.get(category, "Other"))
        ttk.Combobox(cat_row, textvariable=cat_var, state="readonly",
                     width=10,
                     values=[v for _k, v in self._AUDIO_CAT_NAMES]).pack(
            side=tk.LEFT, padx=(6, 0))
        ttk.Label(cat_row, text="(the Type is remembered with the name)",
                  font=(_SANS_FONT, 8, "italic")).pack(
            side=tk.LEFT, padx=(8, 0))
        result = []

        def _ok(_e=None):
            text = var.get()
            # A picked suggestion carries its "#num  " prefix — strip it; the
            # number is for finding the entry, not part of the name.
            m = re.match(r"^#\d+\s+(.*)$", text)
            result.append((m.group(1) if m else text,
                           cat_keys.get(cat_var.get(), "other")))
            dlg.destroy()

        def _cancel(_e=None):
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=12, pady=(0, 12))
        ttk.Button(btns, text="OK", command=_ok,
                   style="Go.TButton").pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=_cancel,
                   style="Danger.TButton").pack(side=tk.RIGHT, padx=(0, 6))
        dlg.bind("<Return>", _ok)
        dlg.bind("<Escape>", _cancel)
        combo.focus_set()
        center_over(root, dlg)
        dlg.grab_set()
        root.wait_window(dlg)
        return result[0] if result else None

    def _audio_rename_slot(self, rel):
        """Right-click → Properties…: set the name after the slot's decode
        index and/or its Type bucket.

        The label is also remembered against the sound's FACTORY content hash
        (the extract baseline md5), so the next extract of this sound —
        same card or a newer firmware that carries the bytes over — reapplies
        it before Whisper ever listens (a tester: Whisper mis-names the same
        file on every extract).  Blank restores the stock decode name and
        forgets the remembered one."""
        from ..core import name_memory
        from ..core.audio_slots import replace_with_retry
        from ..core.checksums import rename_in_baseline
        slot = self._audio_slots_by_rel.get(rel)
        if slot is None:
            return
        parts = name_memory.split_decode_name(os.path.basename(rel))
        if parts is None:
            return
        prefix, label, ext = parts
        prompt = ("Name for this sound — remembered for future extracts\n"
                  "(blank restores \"%s\" and forgets it):" % (prefix + ext))
        suggestions = self._load_sound_test_suggestions()
        cur_cat = self._audio_categories.get(rel) or "other"
        res = self._ask_audio_name(prompt, label, suggestions, cur_cat)
        if res is None:
            return                            # cancelled
        name, new_cat = res
        new_label = name_memory.sanitize_label(name)
        if new_label == label:
            if new_cat == cur_cat:
                return
            # Type-only change: no file ops.  A custom name is the memory
            # key, so without one the new bucket lasts this session only.
            md5 = name_memory.baseline_md5(self._audio_scan_dir, rel)
            if md5 is None and rel not in self._audio_changed_on_disk:
                md5 = name_memory.file_md5(slot.abs_path)
            self._audio_categories[rel] = new_cat
            if md5 and new_label:
                name_memory.remember(md5, new_label, category=new_cat)
                note = " (remembered)"
            else:
                note = (" (this session only — give the slot a name to "
                        "remember its Type across extracts)")
            self.append_log("Replace Audio: %s Type → %s%s"
                            % (rel, new_cat, note), "info")
            self._refresh_audio_type_filter()
            self._refresh_audio_list()
            return
        new_base = ("%s - %s%s" % (prefix, new_label, ext) if new_label
                    else prefix + ext)
        folder = rel.rpartition("/")[0]
        new_rel = (folder + "/" + new_base) if folder else new_base
        dst = os.path.join(os.path.dirname(slot.abs_path), new_base)
        if os.path.exists(dst):
            messagebox.showerror(
                "Audio Properties",
                "A file named\n%s\nalready exists in that folder." % new_base)
            return
        # The factory hash BEFORE the baseline entry moves; also release any
        # preview handle on the file so the rename can't hit a sharing lock.
        md5 = name_memory.baseline_md5(self._audio_scan_dir, rel)
        if md5 is None and rel not in self._audio_changed_on_disk:
            md5 = name_memory.file_md5(slot.abs_path)
        self._audio_stop_playback()
        try:
            replace_with_retry(slot.abs_path, dst)
        except OSError as e:
            messagebox.showerror("Audio Properties", "Rename failed:\n%s" % e)
            return
        # From here on the file is ALREADY renamed on disk, so nothing below
        # may abort the update of what the user is looking at.  Re-pointing the
        # baseline opens it for writing, which on a NAS share can fail; when it
        # threw, the exception took the list refresh with it and the slot both
        # kept its old row and came back from the next scan marked "changed on
        # disk" — the two halves of a tester's batch-23 report.  Say what
        # happened and carry on.
        try:
            rename_in_baseline(self._audio_scan_dir, {rel: new_rel})
        except OSError as e:
            self.append_log(
                "Replace Audio: renamed the file, but couldn't re-point the "
                "extract baseline (%s) — the slot will read as \"changed on "
                "disk\" until the next Extract, even though its audio is "
                "untouched." % e, "error")
        if md5:
            # Record the bucket picked in the dialog with the name, so the
            # renamed file keeps (or moves to) its Type on future extracts
            # (an SFX he renames stays under Sound FX — a tester's report of
            # a rename turning into a "callout").
            try:
                name_memory.remember(md5, new_label,   # blank forgets
                                     category=new_cat)
            except OSError as e:
                self.append_log(
                    "Replace Audio: couldn't remember \"%s\" for future "
                    "extracts (%s)." % (new_label, e), "error")
        # Re-key every bit of session state pinned to the old rel, then update
        # the slot IN PLACE and re-sort the visible list.  No folder rescan:
        # only this one file changed, and the full re-walk both took minutes
        # on big cards and briefly showed the renamed row at the wrong sort
        # position until the metadata probe caught up (feedback batch 14).
        for d in (self._audio_assignments, self._audio_loop_flags,
                  self._audio_keep_full_flags, self._audio_categories):
            if rel in d:
                d[new_rel] = d.pop(rel)
        if rel in self._audio_changed_on_disk:
            self._audio_changed_on_disk.discard(rel)
            self._audio_changed_on_disk.add(new_rel)
        self._audio_categories[new_rel] = new_cat
        slot.rel_path = new_rel
        slot.abs_path = dst
        self._audio_slots_by_rel.pop(rel, None)
        self._audio_slots_by_rel[new_rel] = slot
        # The duplicate-group cache holds rel paths too, and it is only rebuilt
        # by a folder rescan — leaving the old one in it dropped the renamed
        # slot out of its own group and broke "Apply to all copies" for every
        # other copy in it.
        self._audio_rekey_dup_groups(rel, new_rel)
        if self._audio_current_rel == rel:
            self._audio_clear_preview()        # reselecting reloads the pane
        # Repaint BEFORE persisting.  The rename is already done on disk and in
        # memory at this point, so the list must show it no matter what the
        # sidecar write does; when this ran the other way round, a save that
        # raised (the assets folder is routinely a NAS share) left the tree
        # holding the pre-rename rows — old name, old Type, and an iid no
        # longer in _audio_slots_by_rel, so clicking the row loaded nothing
        # and only a rescan fixed it (feedback batch 23).
        self._refresh_audio_type_filter()
        self._refresh_audio_list()             # re-applies the active sort
        try:                                   # keep the renamed row in view
            self._audio_tree.selection_set(new_rel)
            self._audio_tree.see(new_rel)
        except tk.TclError:
            pass
        if not md5:
            note = " (not remembered: the slot is modded and has no baseline)"
        elif new_label:
            note = " (remembered for future extracts)"
        else:
            note = " (forgotten)"
        self.append_log("Replace Audio: renamed %s → %s%s"
                        % (rel, new_base, note), "info")
        self._save_staged_changes()

    def _audio_rekey_dup_groups(self, old_rel, new_rel):
        """Follow a renamed slot into the cached duplicate groups.

        The cache is keyed by rel path and is otherwise only rebuilt by a
        folder rescan, so without this a rename silently evicts the slot from
        its own group (see _refresh_audio_list / _audio_dup_siblings)."""
        groups = getattr(self, "_audio_dup_groups", None)
        if not groups:
            return
        for _label, _dur, rels in groups:
            for i, r in enumerate(rels):
                if r == old_rel:
                    rels[i] = new_rel

    def _audio_export_csv(self):
        """Save the audio table as a CSV — every slot with its metadata,
        type bucket, replacement assignment and changed-on-disk status, so a
        big replacement project can be tracked in a spreadsheet instead of
        scrolling the list (feedback batch 14)."""
        import csv
        if not self._audio_slots:
            messagebox.showinfo("Export CSV",
                                "Scan an assets folder first — the audio "
                                "table is empty.")
            return
        path = filedialog.asksaveasfilename(
            title="Save audio table as CSV",
            defaultextension=".csv",
            initialdir=self.last_browse_dir("audio_csv"),
            initialfile="audio_slots.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        self.remember_browse_dir("audio_csv", path)
        cat_names = {"music": "Music", "sfx": "Sound FX",
                     "callouts": "Callouts"}
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Original Track", "Length", "Format", "Type",
                            "Replacement", "Changed On Disk", "Loop",
                            "Full Length"])
                for s in sorted(self._audio_slots, key=lambda q: q.rel_path):
                    rel = s.rel_path
                    rep = self._audio_assignments.get(rel, "")
                    w.writerow([
                        rel, s.duration_str(), s.format_summary(),
                        cat_names.get(self._audio_categories.get(rel),
                                      "Other"),
                        rep,
                        "yes" if rel in self._audio_changed_on_disk else "",
                        "yes" if self._audio_loop_flags.get(rel) else "",
                        "yes" if self._audio_keep_full_flags.get(rel) else "",
                    ])
        except OSError as e:
            messagebox.showerror("Export CSV", "Couldn't write the CSV:\n%s"
                                 % e)
            return
        self.append_log("Audio table exported: %d slot(s) → %s"
                        % (len(self._audio_slots), os.path.normpath(path)),
                        "success")

    def _audio_revert_selected(self):
        """Revert the selected slot to its extracted original.

        Clears any assignment made this session, then — if the file was already
        staged to disk — restores it from its ``.orig`` snapshot (instant).  A
        file changed before snapshots existed has no backup here, so we point the
        user at 'Revert all changes' on the Write tab (which can re-derive it
        from the source card) rather than failing silently."""
        from ..core import staged_originals
        rel = self._audio_selected_rel()
        if rel is None:
            return
        assets_dir = (self.write_assets_var.get() or "").strip()
        had_assignment = rel in self._audio_assignments
        if had_assignment:
            del self._audio_assignments[rel]
        restored = False
        on_disk = rel in self._audio_changed_on_disk
        if on_disk and assets_dir:
            restored = staged_originals.revert(assets_dir, rel)
        if restored:
            self._audio_changed_on_disk.discard(rel)
        self._save_staged_changes()
        if had_assignment or restored:
            self.append_log("Replace Audio: reverted %s to the extracted "
                            "original" % rel, "info")
        self._refresh_audio_list()
        if rel == self._audio_current_rel:
            # Both sides may have changed: the assignment is gone AND the
            # original file on disk may have just been restored.
            self._audio_load_track(rel)
        try:
            self._audio_tree.selection_set(rel)
        except tk.TclError:
            pass
        if on_disk and not restored:
            messagebox.showinfo(
                "No saved original",
                "This track was changed on disk without a per-edit backup — "
                "edited outside the app, or before this version started keeping "
                "backups — so there's no saved original to restore here.\n\n"
                "Use “Revert all changes…” on the Write tab to rebuild it from "
                "the source card, or re-extract the card.")

    def _audio_play_original(self):
        rel = self._audio_selected_rel()
        if rel is None:
            messagebox.showinfo("No Slot Selected",
                                "Select a track to preview.")
            return
        self._audio_load_track(rel, autoplay="orig")

    def _audio_play_replacement(self):
        rel = self._audio_selected_rel()
        if not (rel and self._audio_assignments.get(rel)):
            messagebox.showinfo(
                "No Replacement",
                "Assign a replacement to this slot first.")
            return
        self._audio_load_track(rel, autoplay="rep")

    # ---- Replace Audio: preview panes (Original | Replacement) -------

    def _audio_visible_rels(self):
        """Every slot row the tree is currently showing, top to bottom.

        Duplicate-group parents are containers, not slots, so only their
        children count — and the order is the tree's own, which is whatever
        the active sort, search and Type filter produced."""
        tree = getattr(self, "_audio_tree", None)
        if tree is None:
            return []
        out = []
        for iid in tree.get_children():
            if iid.startswith(_AUD_DUP_GROUP_IID):
                out.extend(tree.get_children(iid))
            else:
                out.append(iid)
        return out

    def _audio_next_visible_rel(self, rel):
        """The row after *rel* in the list, or None at the end of it."""
        rels = self._audio_visible_rels()
        try:
            i = rels.index(rel)
        except ValueError:
            return None
        return rels[i + 1] if i + 1 < len(rels) else None

    def _audio_on_play_subst_toggle(self):
        """"Play replacements" only acts while sequential play is stepping
        through the list — ticked alone it did nothing (batch 25: "Logically
        this does nothing. Maybe auto select the first option"), so ticking
        it switches "Play sequentially" on too.  Unticking either box leaves
        the other alone."""
        if (self.audio_play_subst_var.get()
                and not self.audio_play_through_var.get()):
            self.audio_play_through_var.set(True)

    def _audio_on_clip_finished(self, pane):
        """A preview finished on its own — step to the next row when "Play
        through the list" is on (feedback batch 23).

        Only the pane that was actually playing drives this, and only while
        the Audio tab still owns the slot it just played, so a finished clip
        can't hijack a selection the user has since moved."""
        if not self.audio_play_through_var.get():
            return
        rel = self._audio_current_rel
        if rel is None:
            return
        side = "rep" if pane is self._audio_pane_rep else "orig"
        nxt = self._audio_next_visible_rel(rel)
        if nxt is None:
            self.append_log(
                "Replace Audio: played through to the end of the list.",
                "info")
            return
        # "Substitute replacements": per-row side — the replacement wherever
        # one exists, the original elsewhere — instead of sticking to the
        # side the user started on (batch 24).
        if self.audio_play_subst_var.get():
            side = "rep" if self._audio_rep_available(nxt) else "orig"

        def _advance():
            self._audio_advance_job = None
            # Selecting the row drives the usual debounced preview load, so
            # the list, the panes and the title all stay in step; ask it to
            # keep playing on the same side.
            try:
                self._audio_tree.selection_set(nxt)
                self._audio_tree.see(nxt)
            except tk.TclError:
                return
            self._cancel_audio_select_job()
            self._audio_load_track(nxt, autoplay=side)
        # Off the player's own callback: _tick is mid-teardown of the process
        # that just exited, and starting the next one from inside it races
        # that cleanup.
        try:
            self._audio_advance_job = self._tk_root().after(120, _advance)
        except tk.TclError:
            pass

    def _audio_load_track(self, rel, autoplay=None):
        """Load *rel* into both preview panes — its original on the left, its
        assigned replacement (if any) on the right.  *autoplay* names the
        pane to start ("orig"/"rep"), or None to just show the seek strips."""
        if rel not in self._audio_slots_by_rel:
            return
        from ..core import audio as _audio
        from ..core import staged_originals
        self._audio_current_rel = rel
        slot = self._audio_slots_by_rel.get(rel)
        opath = slot.abs_path if slot else None
        # A slot already changed on disk (built or staged in an earlier
        # session) holds the REPLACEMENT bytes — playing that as "Original"
        # made both panes identical (feedback batch 14).  The .orig snapshot
        # taken when the change was staged is the true original; fall back to
        # the on-disk file when no snapshot exists (pre-snapshot builds).
        snap_used = False
        changed = self._slot_changed_on_disk("audio", rel)
        if changed:
            snap = staged_originals.snapshot_path(self._audio_scan_dir, rel)
            if snap:
                opath = snap
                snap_used = True
        # Honest title: with no snapshot, an already-changed slot's on-disk
        # bytes ARE the replacement — don't call them "Original" (a tester
        # read his imported mod as a missing replacement).
        self._audio_pane_orig.base_title = (
            "Current file (already modified)" if changed and not snap_used
            else "Original")
        if opath and os.path.isfile(opath):
            self._audio_pane_orig.load(
                opath, _audio.probe_duration(opath) or 0.0, None,
                autoplay=(autoplay == "orig"))
        else:
            self._audio_pane_orig.clear()
        self._audio_load_rep_pane(rel, autoplay=(autoplay == "rep"))

    def _audio_rep_available(self, rel):
        """Whether the Replacement pane would have something to play for
        *rel* — a live assignment, or a slot already changed on disk whose
        on-disk file IS the replacement.  Mirrors _audio_load_rep_pane's
        branches, so play-through's "Substitute replacements" never lands on
        an empty pane (which would end the run early)."""
        from ..core import staged_originals
        rpath = self._audio_assignments.get(rel)
        if rpath and os.path.isfile(rpath):
            return True
        if staged_originals.snapshot_path(self._audio_scan_dir, rel):
            slot = self._audio_slots_by_rel.get(rel)
            return bool(slot and slot.abs_path
                        and os.path.isfile(slot.abs_path))
        return False

    def _audio_load_rep_pane(self, rel, autoplay=False):
        """(Re)load the Replacement pane for *rel* — after a track change or
        an assign/clear/revert of the currently-loaded slot."""
        from ..core import audio as _audio
        from ..core import staged_originals
        rpath = self._audio_assignments.get(rel) if rel else None
        if rpath and os.path.isfile(rpath):
            rdur = _audio.probe_duration(rpath) or 0.0
            self._audio_pane_rep.load(
                rpath, rdur, self._audio_compute_preview_limit(rel, rdur),
                autoplay=autoplay)
            return
        # No new assignment, but the slot is already changed on disk and the
        # true original is on the left (its .orig snapshot): the on-disk file
        # IS the replacement that will build — show it here instead of
        # "no replacement assigned" (a tester read that as a lost mod).
        # The snapshot alone is the test — the change scan may still be
        # hashing (see _slot_changed_on_disk).
        if staged_originals.snapshot_path(self._audio_scan_dir, rel):
            slot = self._audio_slots_by_rel.get(rel)
            cur = slot.abs_path if slot else None
            if cur and os.path.isfile(cur):
                self._audio_pane_rep.load(
                    cur, _audio.probe_duration(cur) or 0.0, None,
                    autoplay=autoplay)
                return
        self._audio_pane_rep.clear("no replacement assigned")

    def _audio_activate_pane(self, side):
        """▶ pressed on an empty pane: load the selected row, then play the
        pane that asked."""
        rel = self._audio_selected_rel()
        if rel is not None:
            self._audio_load_track(rel, autoplay=side)

    def _audio_space_toggle(self, _event=None):
        """Spacebar on the audio list: pause whichever pane is playing, else
        play the loaded original (loading the selected row first if the
        select-debounce hasn't fired yet)."""
        for pane in (self._audio_pane_orig, self._audio_pane_rep):
            if pane and pane.playing:
                pane.toggle_play()
                return "break"
        rel = self._audio_selected_rel()
        if rel is not None and rel != self._audio_current_rel:
            self._cancel_audio_select_job()
            self._audio_load_track(rel, autoplay="orig")
        elif self._audio_pane_orig and self._audio_pane_orig.path:
            self._audio_pane_orig.toggle_play()
        return "break"

    def _audio_properties_shortcut(self, _event=None):
        """F2 on the audio list → the selected slot's Properties dialog (name
        / Type), the same action as the context menu's entry.  Silently does
        nothing on a row that can't be renamed (a duplicate-group parent, or a
        plugin whose audio isn't decode-named — see _audio_on_tree_right)."""
        from ..core import name_memory as _nmem
        rel = self._audio_selected_rel()
        if (rel is None or rel not in self._audio_slots_by_rel
                or not _nmem.split_decode_name(os.path.basename(rel))):
            return "break"
        self._audio_rename_slot(rel)
        return "break"

    def _draw_audio_icon(self, canvas, kind):
        """Draw a crisp, borderless transport icon (play triangle / pause two
        bars / stop square / prev-next triangles) filled with the theme
        foreground — one visual family, identical sizing.

        ``prev``/``next`` are the same family used to step the Scenes window's
        screens: David asked for the audio-preview convention there rather than
        glyphs boxed in square buttons."""
        canvas.delete("all")
        c = THEMES.get(self._current_theme, {})
        fg = c.get("fg", "#dddddd")
        try:
            s = int(canvas.cget("width"))
        except (tk.TclError, ValueError):
            s = 26
        m = s * 0.27  # margin so all three icons share the same bounding box
        if kind in ("play", "next"):
            canvas.create_polygon(m, m, m, s - m, s - m, s / 2.0,
                                  fill=fg, outline=fg)
        elif kind == "prev":
            canvas.create_polygon(s - m, m, s - m, s - m, m, s / 2.0,
                                  fill=fg, outline=fg)
        elif kind == "pause":
            bw, gap = s * 0.17, s * 0.11
            canvas.create_rectangle(s / 2 - gap - bw, m, s / 2 - gap, s - m,
                                    fill=fg, outline=fg)
            canvas.create_rectangle(s / 2 + gap, m, s / 2 + gap + bw, s - m,
                                    fill=fg, outline=fg)
        elif kind == "stop":
            canvas.create_rectangle(m, m, s - m, s - m, fill=fg, outline=fg)

    def _audio_compute_preview_limit(self, rel, rep_dur):
        """Stop point (s) for *rel*'s REPLACEMENT (duration *rep_dur*), or
        None to play the whole file.  A replacement that Write will TRIM to
        its slot length previews only up to that length, so the preview
        matches the machine.  (A shorter replacement is padded with silence
        on Write -- nothing to hear -- so it just plays to its own end, no
        cap.)  The original always plays in full; only the Replacement pane
        gets a limit."""
        if rel is None:
            return None
        # No cap when trimming is off, or this slot is exempted ("Full").
        if not self.audio_trim_var.get():
            return None
        if self._audio_keep_full_flags.get(rel):
            return None
        slot = self._audio_slots_by_rel.get(rel)
        slot_dur = slot.duration if slot else 0.0
        # Only cap when the replacement is actually longer than the slot.
        if slot_dur > 0 and rep_dur > slot_dur + 0.02:
            return slot_dur
        return None

    def _cancel_audio_advance(self):
        """Drop a queued sequential-play step, so a clip that has just finished
        can't start the next one after something else asked for silence."""
        if getattr(self, "_audio_advance_job", None) is not None:
            try:
                self._tk_root().after_cancel(self._audio_advance_job)
            except Exception:
                pass
            self._audio_advance_job = None

    def _audio_stop_playback(self):
        """Stop both preview panes (keeps their playheads where they landed)."""
        self._cancel_audio_advance()
        for pane in (self._audio_pane_orig, self._audio_pane_rep):
            if pane is not None:
                pane.stop_playback()

    def _audio_clear_preview(self):
        """Reset both preview panes entirely (used on manufacturer switch)."""
        self._cancel_audio_select_job()
        self._audio_current_rel = None
        if self._audio_pane_orig is not None:
            self._audio_pane_orig.base_title = "Original"
            self._audio_pane_orig.clear()
        if self._audio_pane_rep is not None:
            self._audio_pane_rep.clear("no replacement assigned")

    # ---- Replace Audio: pending assignments (applied at Write time) --

    def pending_audio_assignments(self, assets_dir):
        """Return ``(slots_by_rel, assignments, trim, keep_full)`` of
        replacements the user assigned for *assets_dir*, or ``None`` when
        there's nothing to apply.  *keep_full* is the set of rel_paths the user
        ticked "Full" (keep full length) on — exempt from *trim*.  Called by the
        Write flow to auto-stage edits just before it repacks — there is no
        manual "stage" step.

        Guarded so it only fires when the folder being written is the same one
        the assignments were made against (so stale assignments from a
        different extract can't leak in)."""
        mfr = self._current_mfr
        if mfr is None or not getattr(
                mfr.capabilities, "replace_audio", False):
            return None
        if not assets_dir:
            return None
        scanned = self._audio_scan_dir or ""
        if (os.path.normcase(os.path.normpath(assets_dir))
                != os.path.normcase(os.path.normpath(scanned))):
            return None
        assignments = {rel: rep for rel, rep in self._audio_assignments.items()
                       if rep and rel in self._audio_slots_by_rel}
        if not assignments:
            return None
        keep_full = frozenset(
            rel for rel in assignments
            if self._audio_keep_full_flags.get(rel))
        return (dict(self._audio_slots_by_rel), assignments,
                bool(self.audio_trim_var.get()), keep_full)

    def audio_keep_full_rels(self, assets_dir):
        """Set of rel_paths the user marked "Full" (keep full length) AND
        assigned a replacement for in *assets_dir*.  app.py passes this to the
        write pipeline so those slots skip the trim-to-original-length.  Same
        folder-match guard as pending_audio_assignments()."""
        mfr = self._current_mfr
        if mfr is None or not getattr(
                mfr.capabilities, "audio_keep_length_override", False) \
                or not assets_dir:
            return frozenset()
        scanned = self._audio_scan_dir or ""
        if (os.path.normcase(os.path.normpath(assets_dir))
                != os.path.normcase(os.path.normpath(scanned))):
            return frozenset()
        return frozenset(
            rel for rel, rep in self._audio_assignments.items()
            if rep and rel in self._audio_slots_by_rel
            and self._audio_keep_full_flags.get(rel))

    def audio_loop_basenames(self, assets_dir):
        """Set of editable source filenames the user marked "Loop" (and
        assigned a replacement for) in *assets_dir*.  app.py passes this to the
        write pipeline so the inverse converter loops just those .sample files.
        Same folder-match guard as pending_audio_assignments()."""
        mfr = self._current_mfr
        if mfr is None or not getattr(
                mfr.capabilities, "audio_loop_inject", False) or not assets_dir:
            return frozenset()
        scanned = self._audio_scan_dir or ""
        if (os.path.normcase(os.path.normpath(assets_dir))
                != os.path.normcase(os.path.normpath(scanned))):
            return frozenset()
        return frozenset(
            os.path.basename(rel)
            for rel, rep in self._audio_assignments.items()
            if rep and rel in self._audio_slots_by_rel
            and self._audio_loop_flags.get(rel))

    def replacement_folder_mismatches(self, assets_dir):
        """Return ``[(label, count, scanned_dir), ...]`` for each Replace
        surface that has live in-memory assignments made against a folder
        OTHER than *assets_dir*.

        The Write flow only stages assignments whose scan folder matches the
        folder being built (the ``pending_*_assignments`` guard).  If the user
        assigned replacements and then re-pointed the assets folder, those
        assignments are silently dropped and the build is an unmodified image.
        The Write controller calls this up front to warn instead.  Empty list
        when everything lines up (or nothing is assigned)."""
        if not assets_dir:
            return []
        target = os.path.normcase(os.path.normpath(assets_dir))
        out = []
        for label, assigns, slots, scanned in (
                ("audio", self._audio_assignments,
                 self._audio_slots_by_rel, self._audio_scan_dir),
                ("video", self._video_assignments,
                 self._video_slots_by_rel, self._video_scan_dir),
                ("image", self._image_assignments,
                 self._image_slots_by_rel, self._image_scan_dir)):
            live = [rel for rel, rep in (assigns or {}).items()
                    if rep and rel in (slots or {})]
            if not live:
                continue
            # A cleared scan stamp (invalidate_asset_scans after an extract /
            # transfer) doesn't orphan the assignments: they still belong to
            # the folder remembered in _scan_dir_prev — compare and report
            # with that instead of "(unknown)".
            scanned = scanned or self._scan_dir_prev.get(label, "")
            scanned_norm = os.path.normcase(os.path.normpath(scanned or ""))
            if scanned_norm != target:
                out.append((label, len(live), scanned or "(unknown)"))
        return out

    # ==================================================================
    # Replace Video tab
    # ==================================================================

    def _build_video_tab(self):
        """Build the 'Replace Video' tab: a searchable list of the video files
        in the extracted assets folder, each a slot the user can assign + an
        embedded-preview a replacement clip for.  Staging copies a matching
        replacement through as-is, else re-encodes it to its slot's
        container/codec/resolution, and writes it over the original so the
        normal Write step repacks it."""
        f = self._tab_video
        pad = {"padx": 10, "pady": 4}

        # One-line intro; the full behaviour notes live in the "?" tips window.
        _video_desc = ttk.Label(
            f,
            text="Assign a replacement clip to any slot — a matching clip is "
                 "used as-is, anything else is auto-re-encoded — then build "
                 "the update on the Write tab.",
            font=(_SANS_FONT, 9, "italic"),
            wraplength=720, justify=tk.LEFT)
        _video_desc.pack(anchor=tk.W, **pad)
        self._register_responsive_wrap(_video_desc)

        # ffmpeg-missing banner.  Video matching is always a re-encode, so
        # ffmpeg is effectively required here.  Pack-managed by
        # _refresh_video_ffmpeg_warning(); positioned before the assets row.
        self._video_ffmpeg_warn = ttk.Label(
            f,
            text="⚠ ffmpeg not found — replacing video needs ffmpeg to "
                 "re-encode + preview clips. Install it with “Install "
                 "Missing” above the tabs.",
            foreground="#d04040", font=(_SANS_FONT, 9),
            wraplength=720, justify=tk.LEFT)

        # Assets folder row (shared with the Write / Replace Audio tabs).
        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        self._video_assets_row = row
        ttk.Label(row, text="Project Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._project_mirror_label(row).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._make_assets_scan_buttons(row, "video",
                                       self._scan_video_slots_async)

        # Search + sort toolbar.
        tools = ttk.Frame(f); tools.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(tools, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(tools, textvariable=self.video_search_var, width=24).pack(
            side=tk.LEFT, padx=(4, 12))
        self._build_change_filter(tools, "video").pack(side=tk.LEFT)
        # Button rightmost (flush with the list edge), counter to its left
        # (feedback batch 21).
        self._video_csv_btn = ttk.Button(
            tools, text="Export CSV", command=self._video_export_csv)
        self._video_csv_btn.pack(side=tk.RIGHT)
        self._video_status_lbl = ttk.Label(
            tools, textvariable=self.video_status_var,
            font=(_SANS_FONT, 9))
        self._video_status_lbl.pack(side=tk.RIGHT, padx=(0, 10))
        _Tooltip(
            self._video_csv_btn,
            "Save the whole video table (every slot, not just the filtered "
            "view) as a CSV — name, length, resolution, format, audio, "
            "replacement and changed-on-disk status — for tracking a big "
            "replacement project in a spreadsheet.",
            lambda: self._current_theme)

        # Slot list.
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        self._video_tree = ttk.Treeview(
            list_frame, columns=("len", "res", "fmt", "aud", "rep", "conv"),
            height=9, selectmode="browse")
        self._video_tree.heading("#0", text="Original Video", anchor=tk.W)
        self._video_tree.heading("len", text="Length", anchor=tk.W)
        self._video_tree.heading("res", text="Resolution", anchor=tk.W)
        self._video_tree.heading("fmt", text="Format", anchor=tk.W)
        self._video_tree.heading("aud", text="Audio", anchor=tk.W)
        self._video_tree.heading("rep", text="Replacement", anchor=tk.W)
        # What Write will DO with the assigned clip.  It was only ever
        # visible as a log line at pick time, so re-doing a batch of videos
        # meant scrolling the log to find which ones went in untouched
        # (feedback batch 22).
        self._video_tree.heading("conv", text="Convert", anchor=tk.W)
        self._video_tree.column("#0", width=300, minwidth=160)
        self._video_tree.column("len", width=56, minwidth=46, anchor=tk.W)
        self._video_tree.column("res", width=90, minwidth=70, anchor=tk.W)
        self._video_tree.column("fmt", width=140, minwidth=80)
        self._video_tree.column("aud", width=104, minwidth=70, anchor=tk.W,
                                stretch=False)
        self._video_tree.column("rep", width=200, minwidth=110)
        self._video_tree.column("conv", width=84, minwidth=60, anchor=tk.W,
                                stretch=False)
        self._persist_tree_columns(
            self._video_tree, "video",
            ("#0", "len", "res", "fmt", "aud", "rep", "conv"))
        self._video_sort_cfg = [
            ("#0", "Original Video", False), ("len", "Length", True),
            ("res", "Resolution", True), ("fmt", "Format", False),
            ("aud", "Audio", False), ("rep", "Replacement", False),
            ("conv", "Convert", False)]
        self._wire_sort_headings(self._video_tree, self._video_sort_cfg,
                                 "_video_sort", self._refresh_video_list)
        video_scroll = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self._video_tree.yview)
        self._video_tree.configure(yscrollcommand=video_scroll.set)
        video_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._video_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._video_tree.bind("<Double-1>", self._video_on_tree_double)
        self._video_tree.bind("<Button-1>", self._video_on_tree_click, add="+")
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self._video_tree.bind(seq, self._video_on_tree_right)
        self._video_tree.bind("<<TreeviewSelect>>", self._video_on_tree_select)

        self._video_empty = ttk.Label(
            list_frame,
            text="Set the project folder on the Extract tab, then click Scan.",
            foreground="#888888", anchor=tk.CENTER, justify=tk.CENTER)
        self._video_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # --- Embedded preview players: Original and Replacement side by side
        # (like the image tab), each a frame canvas (a decode thread streams
        # frames there while ffplay carries the sound) with its own seek bar
        # and transport — replacing the old single player + Source A/B switch
        # (David).  Starting one pane pauses the other so the soundtracks
        # never overlap. ---
        player = ttk.LabelFrame(f, text=" Preview ")
        player.pack(fill=tk.X, padx=10, pady=(4, 2))
        panes = ttk.Frame(player)
        panes.pack(padx=6, pady=(2, 6))
        self._video_pane_orig = _VideoPreviewPane(
            self, panes, "Original",
            on_activate=lambda: self._video_activate_pane("orig"))
        self._video_pane_rep = _VideoPreviewPane(
            self, panes, "Replacement",
            on_activate=lambda: self._video_activate_pane("rep"))
        self._video_pane_orig.sibling = self._video_pane_rep
        self._video_pane_rep.sibling = self._video_pane_orig
        self._video_pane_orig.frame.grid(row=0, column=0, sticky="n",
                                         padx=(0, 4))
        self._video_pane_rep.frame.grid(row=0, column=1, sticky="n",
                                        padx=(4, 0))
        self._video_pane_rep.clear("no replacement assigned")
        # Big wrong-format callout under the panes.  The Format column's ⚠ and
        # its log line were easy to scroll past, and the "✗ wrong format" text
        # only exists on rows with a live pick — a slot whose CURRENT clip is
        # unplayable showed just the tiny glyph (batch 25: "What about putting
        # a bigger indicator under the video to make it really stand out?").
        # Text + color are set per-selection by _video_update_preview_note;
        # packed only while there is something to say.
        self._video_preview_note = ttk.Label(
            player, text="", justify=tk.LEFT, anchor=tk.W,
            font=(_SANS_FONT, 10, "bold"))
        self._register_responsive_wrap(self._video_preview_note)

        # The conversion options get a row of their own under the preview box,
        # like the audio tab's.  They used to sit in the box's left margin
        # (feedback batch 21), but there is no spare margin: two 320px panes
        # already fill the default 820px window, so the column stole width from
        # the panes and the Replacement pane hung off the right edge — which is
        # exactly what a longer label made obvious (David).  Beneath the panes
        # the labels can say what they mean without crowding the video.
        self._video_opts_row = ttk.Frame(f)
        # padx 10, not 12: same alignment fix as the audio tab (batch 24).
        self._video_opts_row.pack(anchor=tk.W, fill=tk.X, padx=10, pady=(4, 4))

        # This applies to EVERY replacement, not to the slot on screen — it sat
        # beside the preview, which read as per-clip, and a tester thought
        # changing it meant re-picking all his files one by one (batch 23).
        # The label says so, and flipping it re-answers the Convert column for
        # the whole list on the spot.
        self._video_no_conversion_cb = ttk.Checkbutton(
            self._video_opts_row,
            text="Use my files as-is — never re-encode (all slots)",
            variable=self.video_no_conversion_var,
            command=self._video_on_no_conversion_toggle)
        self._video_no_conversion_cb.pack(side=tk.LEFT)
        _Tooltip(
            self._video_no_conversion_cb,
            "Applies to every replacement you have picked, not just the "
            "selected one — tick or untick it any time and the Convert column "
            "re-answers for the whole list. Nothing has to be picked again.\n\n"
            "On: replacements are copied in byte-for-byte, so each one has to "
            "already be the clip's container, codec, resolution and frame "
            "rate. Lossless and fast, but the file has to be game-ready — a "
            "clip the machine can't decode plays its sound over a black "
            "picture, and the Convert column says \"✗ wrong format\" when it "
            "can see that coming.\n\nOff: anything that isn't already a match "
            "is converted to suit the slot, at full size — and a clip that is "
            "already this slot's video in the wrong container is repackaged "
            "rather than re-encoded, so it loses nothing either.",
            lambda: self._current_theme)

        self._video_trim_cb = ttk.Checkbutton(
            self._video_opts_row,
            text="Trim / pad to the original clip length",
            variable=self.video_trim_var,
            command=self._on_video_trim_toggle)
        self._video_trim_cb.pack(side=tk.LEFT, padx=(18, 0))
        # Hover tooltip — per-plugin guidance is appended in
        # apply_manufacturer.
        self._video_trim_tip = _Tooltip(
            self._video_trim_cb, "", lambda: self._current_theme)
        # Trim/pad only applies during a re-encode, so grey it out when
        # "No conversion" is on (reflects any restored staged state too).
        self._update_video_trim_enabled()

        self._refresh_video_ffmpeg_warning()

    def _video_noconv_conflict(self, rel, path, deep=True):
        """Why *path* can't be copied through as-is for slot *rel* under
        'No conversion', or None if it's fine.  Used to warn at pick/toggle
        time instead of letting the mismatch surface only as a build-time
        failure (a tester).

        This checks what the MACHINE needs, not just what Write will accept.
        Write only refuses the wrong container; everything else it copies
        through byte-for-byte because the user vouched for it — and an i.MX6
        VPU handed ProRes, HEVC, 10-bit, or the wrong geometry finds the sound
        and shows a black picture, which is what a tester's attract video did
        (batch 23).  Same rules as the build's own drop-in gate
        (plugins.stern.engine._intact_copy_source), applied where he can still
        do something about it.

        *deep* controls the ffprobe-backed half.  It costs one probe per file,
        which is fine for the one clip just picked but not for the whole
        assignment list at once — the bulk callers pass ``deep=False`` and let
        the Convert column's background pass answer instead."""
        slot = self._video_slots_by_rel.get(rel)
        if slot is None:
            return None
        from ..core.video_slots import backend_for
        if backend_for(slot.abs_path) is not None:
            return ("%s is a custom %s format that always needs a re-encode"
                    % (rel, slot.ext))
        rep_ext = os.path.splitext(path)[1].lower()
        if rep_ext != slot.ext:
            return ("%s needs a %s file, but %s is %s" % (
                rel, slot.ext, os.path.basename(path),
                rep_ext or "extension-less"))
        if not deep:
            return None
        return (self._video_playability_conflict(slot, path)
                or self._video_extra_audio(slot, path))

    @staticmethod
    def _video_playability_conflict(slot, path):
        """Why the machine wouldn't play *path* in *slot*, or None.

        Touches no Tk state, so the Convert column's worker thread can call it.
        Best-effort: without ffprobe there is nothing to measure, and a file
        we can't read is not evidence of a problem — both return None rather
        than guessing."""
        from ..core import video as _video
        name = os.path.basename(path)
        info = _video.detect_video_info(path)
        if info is None:
            return None
        codec = (info.vcodec or "").lower()
        if codec and codec != "h264":
            return ("%s is %s and the machine plays H.264"
                    % (name, codec.upper()))
        pix = info.pix_fmt or ""
        if pix and pix not in _video.SAFE_PIX_FMTS:
            return ("%s is %s and the machine's decoder handles only 8-bit "
                    "4:2:0" % (name, pix))
        sinfo = getattr(slot, "info", None)
        if sinfo is None or not sinfo.width or not sinfo.height:
            return None
        if info.width and info.height and (
                (info.width, info.height) != (sinfo.width, sinfo.height)):
            return ("%s is %dx%d and this slot's clip is %dx%d"
                    % (name, info.width, info.height,
                       sinfo.width, sinfo.height))
        if sinfo.fps > 0 and info.fps > 0 and abs(info.fps - sinfo.fps) > 0.5:
            return ("%s runs at %.3g fps and this slot's clip is %.3g fps"
                    % (name, info.fps, sinfo.fps))
        rank = _video.profile_rank(info)
        slot_rank = _video.profile_rank(sinfo)
        if rank is not None and slot_rank is not None and rank > slot_rank:
            return ("%s is H.264 %s profile and this slot's clip is %s — above "
                    "what the slot proves the machine decodes"
                    % (name, info.profile, sinfo.profile))
        return None

    def _slot_unplayable(self, slot):
        """Whether the slot's CURRENT on-disk clip is a format the machine
        can't decode — i.e. an earlier as-is build already baked in ProRes /
        HEVC / 10-bit (the pick-time gate only arrived in v0.95).  A tester
        had exactly this: his ProRes attract went on as-is before the gate
        existed, and afterwards nothing anywhere pointed at the slots he
        needed to redo (batch 24: "there are other files labelled as MOV
        Prores ... I will need to go back and adjust them").

        Stern-only: the H.264 / 8-bit 4:2:0 ceiling is a Spike 2 VPU fact
        (census: 2251 stock clips across five titles, H.264 every one), so a
        stock folder can never trip it.  Other manufacturers' machines decode
        more, so no claim is made for them."""
        if getattr(self._current_mfr, "key", "") != "stern":
            return None
        info = getattr(slot, "info", None)
        if info is None:
            return None
        from ..core import video as _video
        if _video.backend_for(slot.abs_path) is not None:
            return None
        codec = (info.vcodec or "").lower()
        if codec and codec != "h264":
            return "is %s and the machine plays H.264" % codec.upper()
        pix = info.pix_fmt or ""
        if pix and pix not in _video.SAFE_PIX_FMTS:
            return ("is %s and the machine's decoder handles only 8-bit "
                    "4:2:0" % pix)
        return None

    def _video_fmt_cell(self, slot):
        """The Format column's text for a slot: its format summary, plus a ⚠
        when the clip sitting in the slot right now is one the machine can't
        play (see _slot_unplayable).  The ⚠ is explained by a log line the
        metadata probe emits when it lands."""
        s = slot.format_summary()
        return (s + "  ⚠") if self._slot_unplayable(slot) else s

    def _warn_unplayable_slot(self, rel, slot):
        """One red log line (per folder+slot per session) for a slot whose
        current clip the machine can't decode, so the user can find every
        slot that needs redoing instead of spotting ⚠ rows by scrolling."""
        why = self._slot_unplayable(slot)
        if not why:
            return
        key = (self._video_scan_dir, rel)
        if key in self._video_unplayable_warned:
            return
        self._video_unplayable_warned.add(key)
        self.append_log(
            'Video slot "%s" currently holds a clip that %s — on the machine '
            'it will play its sound over a black picture. Assign a good '
            'replacement (or revert the slot) before building.' % (rel, why),
            "error")

    @staticmethod
    def _video_extra_audio(slot, path):
        """Why *path*'s soundtrack is a problem for *slot*, or None.

        Kept apart from :meth:`_video_playability_conflict` because it is not
        a decode failure — the picture plays perfectly.  The machine just also
        plays the audio track the file brought with it, on top of whatever the
        game is doing.  Judged against THIS slot's clip rather than a blanket
        rule: most Spike 2 clips are silent, but not all of them are (Deadpool
        1.14 LE has audio on 7 of its 99), so only a silent slot getting a
        noisy replacement is worth mentioning (a tester: "I forgot to drop
        the audio off some files")."""
        from ..core import video as _video
        sinfo = getattr(slot, "info", None)
        if sinfo is None or sinfo.has_audio:
            return None
        info = _video.detect_video_info(path)
        if info is None or not info.has_audio:
            return None
        return ("%s carries an audio track and this slot's clip has none, so "
                "the machine will play it over the game's own sound"
                % os.path.basename(path))

    # Values shown in the video list's "Convert" column.
    _VIDEO_CONV_ASIS = "As-is"
    _VIDEO_CONV_REENC = "Re-encode"
    # The clip IS this slot's video, just wrapped in the wrong container — a
    # stream copy fixes the wrapper and every frame survives untouched, so
    # it belongs with "As-is", not with the re-encodes (a tester's 1360x768 H.264
    # .mp4 for a QuickTime slot).
    _VIDEO_CONV_REPACK = "Repackage"
    # "No conversion" is on and this pick would go on the card untouched but
    # the machine can't play it, or Write would refuse it outright.  The column
    # used to go BLANK for both, which is why 27 of a tester's 29 rows said
    # nothing at all and he asked why only one was "As-is" (batch 23).
    # Worded "wrong format", not "won't play": the file itself is perfectly
    # playable on a PC, it is its FORMAT the machine's decoder can't take —
    # "won't play" read as "the file is corrupt" (batch 24).
    _VIDEO_CONV_REJECT = "✗ wrong format"
    _VIDEO_CONV_WRONG_TYPE = "✗ needs %s"
    # Goes on as-is and the picture is right, but it brings a soundtrack the
    # slot's own clip doesn't have and the machine will play it.
    _VIDEO_CONV_ASIS_NOISY = "As-is ⚠ audio"

    @staticmethod
    def _video_conv_mode(slot, path, no_conversion, trim):
        """What Write will do with *path* for *slot*: copy it in verbatim
        (``As-is``), rewrite only its container (``Repackage`` — lossless too)
        or re-encode it (``Re-encode``); "" when it can't be determined (no
        ffprobe, unreadable file, or a pick the copy-through would reject —
        the pick-time warning covers that one).

        Mirrors :meth:`_video_conversion_note`'s branch order, but takes the
        two option flags as plain arguments and touches no Tk state, so the
        background pass can call it off the main thread."""
        from ..core.video_slots import (_already_matches, _remuxable,
                                        backend_for, find_ffmpeg)
        if slot is None or not path:
            return ""
        rep_ext = os.path.splitext(path)[1].lower()
        if no_conversion:
            if backend_for(slot.abs_path) is not None:
                return MainWindow._VIDEO_CONV_REJECT
            if rep_ext != slot.ext:
                return MainWindow._VIDEO_CONV_WRONG_TYPE % slot.ext
            # It WILL be copied on untouched — so the honest answer is whether
            # the machine can play what's being copied, not just whether Write
            # will accept it.
            if MainWindow._video_playability_conflict(slot, path):
                return MainWindow._VIDEO_CONV_REJECT
            if MainWindow._video_extra_audio(slot, path):
                # The picture is fine; it is the extra soundtrack that isn't.
                return MainWindow._VIDEO_CONV_ASIS_NOISY
            return MainWindow._VIDEO_CONV_ASIS
        if backend_for(slot.abs_path) is not None:
            return MainWindow._VIDEO_CONV_REENC
        try:
            matches = _already_matches(slot, path, rep_ext, match_length=trim)
        except Exception:
            return ""
        if matches:
            return MainWindow._VIDEO_CONV_ASIS
        if find_ffmpeg():
            try:
                repack = _remuxable(slot, path, match_length=trim)
            except Exception:
                repack = False
            return (MainWindow._VIDEO_CONV_REPACK if repack
                    else MainWindow._VIDEO_CONV_REENC)
        if rep_ext == slot.ext:
            # No ffmpeg to re-encode with, but the container already fits, so
            # Write copies it in unchanged.
            return MainWindow._VIDEO_CONV_ASIS
        return ""

    def _video_conv_key(self, rel, path):
        """Cache key for a row's Convert answer — it changes with the pick,
        with either option flag, and with the picked FILE's bytes (size +
        mtime).  The last part is what lets a re-export under the same name
        get a fresh verdict: a tester re-exported his ProRes pick as H.264
        over the same .mov and the column kept serving the old file's
        "✗ won't play" — through re-picks and re-scans — because nothing in
        the key had changed (batch 24)."""
        try:
            st = os.stat(path)
            ident = (st.st_size, st.st_mtime_ns)
        except OSError:
            ident = (0, 0)
        return (rel, path, ident,
                bool(self.video_no_conversion_var.get()),
                bool(self.video_trim_var.get()))

    def _video_conv_cached(self, rel, path):
        """The Convert column's text for a row, from cache only.  Rows with no
        replacement show nothing; an unresolved row shows "…" until the
        background pass answers it."""
        if not path:
            return ""
        return self._video_conv_cache.get(self._video_conv_key(rel, path), "…")

    def _video_probe_conv_async(self):
        """Resolve the Convert column for every assigned row that isn't cached
        yet, on a worker thread (each answer can cost an ffprobe of the
        replacement file), then repaint just those rows.

        Kept apart from the slot-metadata pass because it keys off the
        REPLACEMENT file, not the slot, and re-runs whenever a pick or an
        option flag changes."""
        import threading
        self._video_conv_pass_id += 1
        pass_id = self._video_conv_pass_id
        no_conv = bool(self.video_no_conversion_var.get())
        trim = bool(self.video_trim_var.get())
        # Keys are built HERE (main thread) via _video_conv_key so they carry
        # the picked file's size+mtime — the worker must store its answer
        # under the same key the repaint will look up.
        pending = [(self._video_conv_key(rel, path), rel, path)
                   for rel, path in sorted(self._video_assignments.items())]
        pending = [p for p in pending if p[0] not in self._video_conv_cache]
        if not pending:
            return
        slots = {rel: self._video_slots_by_rel.get(rel)
                 for _k, rel, _p in pending}

        def _work():
            out = []
            for key, rel, path in pending:
                if self._video_conv_pass_id != pass_id:
                    return
                out.append((key,
                            self._video_conv_mode(slots.get(rel), path,
                                                  no_conv, trim)))
            try:
                self._tk_root().after(0, self._apply_video_conv, pass_id, out)
            except (tk.TclError, RuntimeError):
                pass                      # window closed mid-pass

        threading.Thread(target=_work, daemon=True).start()

    def _apply_video_conv(self, pass_id, results):
        """Main thread: store the resolved Convert answers and repaint their
        rows in place (a full list refresh would fight the user's scroll)."""
        if self._video_conv_pass_id != pass_id:
            return
        tree = getattr(self, "_video_tree", None)
        for key, mode in results:
            self._video_conv_cache[key] = mode
            rel = key[0]
            if rel == self._video_current_rel:
                # The loaded slot's pick just got its verdict — the callout
                # under the preview may change wording (or appear).
                self._video_update_preview_note(rel)
            if tree is None:
                continue
            try:
                if not tree.exists(rel):
                    continue
                vals = list(tree.item(rel, "values"))
                if len(vals) >= 6:
                    vals[5] = mode
                    tree.item(rel, values=vals)
            except tk.TclError:
                pass

    def _video_conversion_note(self, rel, path):
        """Short note on what Write will DO to *path* for slot *rel*: copy it
        through untouched, or re-encode it.

        feedback batch 16: "I imported video I think was already in the right
        format but I can't tell if PAD converted it."  The staging detail only
        appears at build time, so mirror stage_replacement's branch order here
        and say so at pick time.  Returns "" when it can't be determined
        (no ffprobe / unreadable file) rather than guessing."""
        slot = self._video_slots_by_rel.get(rel)
        if slot is None:
            return ""
        from ..core.video_slots import (_already_matches, _remuxable,
                                        backend_for, find_ffmpeg)
        rep_ext = os.path.splitext(path)[1].lower()
        if self.video_no_conversion_var.get():
            # A rejectable pick is reported by the caller's own warning.
            return ("will be copied in as-is — no conversion"
                    if self._video_noconv_conflict(rel, path) is None else "")
        if backend_for(slot.abs_path) is not None:
            return "will be converted to the game's %s format" % slot.ext
        try:
            matches = _already_matches(
                slot, path, rep_ext,
                match_length=bool(self.video_trim_var.get()))
        except Exception:
            return ""
        if matches:
            return "already matches this slot — will be copied in, no re-encode"
        if find_ffmpeg():
            try:
                repack = _remuxable(
                    slot, path, match_length=bool(self.video_trim_var.get()))
            except Exception:
                repack = False
            if repack:
                return ("already this slot's video — only its %s container "
                        "will be repackaged, no re-encode" % slot.ext)
            return "will be re-encoded to match this slot"
        if rep_ext == slot.ext:
            return "will be copied in unchanged (no ffmpeg — not re-encoded)"
        return ""

    def _on_video_trim_toggle(self):
        """Trim/pad also decides whether a clip counts as already matching its
        slot, so flipping it can flip the Convert column — persist, then
        redraw so the column agrees with the checkbox."""
        self._save_staged_changes()
        self._refresh_video_list()

    def _video_on_no_conversion_toggle(self):
        """No-conversion copies the file through verbatim, so trim/pad (a
        re-encode-time option) doesn't apply — grey it out while it's on, then
        persist the choice with the other staged settings."""
        self._update_video_trim_enabled()
        self._save_staged_changes()
        # Turning it ON with replacements already picked: flag any that the
        # verbatim copy would reject, now rather than at build time.  Shallow
        # (no ffprobe per file) — this runs over every assignment on the main
        # thread, and the deeper "would the machine play it?" answer arrives in
        # the Convert column from its own worker pass.
        if self.video_no_conversion_var.get():
            bad = [w for w in (
                self._video_noconv_conflict(rel, p, deep=False)
                for rel, p in sorted(self._video_assignments.items()))
                if w is not None]
            if bad:
                messagebox.showwarning(
                    "Using your files as-is",
                    "These assigned replacements can't be used as-is and "
                    "would be rejected at build time:\n\n%s\n\nUntick \"Use "
                    "my files as-is\" to have them converted automatically."
                    % "\n".join("  • %s" % w for w in bad))
        # The flag decides every row's Convert answer — redraw so the column
        # tracks the checkbox.
        self._refresh_video_list()

    def _update_video_trim_enabled(self):
        """Enable the trim/pad checkbox only when we'll actually re-encode
        (i.e. 'No conversion' is off)."""
        cb = getattr(self, "_video_trim_cb", None)
        if cb is None:
            return
        try:
            cb.state(["disabled"] if self.video_no_conversion_var.get()
                     else ["!disabled"])
        except tk.TclError:
            pass

    def _refresh_video_ffmpeg_warning(self):
        """Show the ffmpeg-missing banner only when ffmpeg can't be found.
        Re-probes on each tab visit so installing ffmpeg mid-session clears
        the banner next time the tab is opened."""
        warn = getattr(self, "_video_ffmpeg_warn", None)
        if warn is None:
            return
        from ..core import audio as _audio
        _audio._ffmpeg_path = None  # force a fresh probe, not the cached result
        if _audio.find_ffmpeg():
            warn.pack_forget()
        elif not warn.winfo_ismapped():
            warn.pack(fill=tk.X, padx=12, pady=(0, 4),
                      before=self._video_assets_row)

    # ---- Replace Video: scanning -------------------------------------

    def _scan_video_slots_async(self):
        """Scan the assets folder for video slots on a worker thread, then
        repopulate the list.  Stale scans are dropped via a bump-counter."""
        import threading
        from ..core.video_slots import scan_video_slots

        assets_path = (self.write_assets_var.get() or "").strip()
        self._video_scan_id += 1
        scan_id = self._video_scan_id

        if not assets_path or not os.path.isdir(assets_path):
            self._video_slots = []
            self._video_slots_by_rel = {}
            self._refresh_video_list()
            self._video_empty.configure(
                text="Set the project folder on the Extract tab, then click Scan.")
            self._video_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            self._set_tab_scanning("video", False)
            return

        self._video_empty.configure(text="Scanning for video files…")
        self._video_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        mfr = self._current_mfr

        def _work():
            try:
                roots = mfr.video_slot_dirs(assets_path) if mfr else None
            except Exception:
                roots = None
            try:
                exts = mfr.video_slot_exts(assets_path) if mfr else None
            except Exception:
                exts = None
            try:
                # Fast walk: list slots instantly; ffprobe metadata is filled
                # in afterwards on a background pass (a folder can hold
                # hundreds of clips and one ffprobe per file would hang).
                slots = scan_video_slots(assets_path, roots=roots, exts=exts,
                                         probe=False)
            except Exception:
                slots = []
            if self._video_scan_id != scan_id:
                return
            self._tk_root().after(
                0, self._populate_video_after_scan,
                slots, scan_id, assets_path)

        self._set_tab_scanning("video", True)
        threading.Thread(target=_work, daemon=True).start()

    def _populate_video_after_scan(self, slots, scan_id, scan_dir):
        """Main-thread: store scan results and refresh the list."""
        if self._video_scan_id != scan_id:
            return
        self._set_tab_scanning("video", False)
        self._video_slots = slots
        self._video_slots_by_rel = {s.rel_path: s for s in slots}
        # Restore assignments persisted for a freshly-scanned folder; a re-scan
        # of the same folder keeps the live in-memory ones (see audio above).
        from ..core import staged_changes
        if scan_dir != self._video_scan_dir:
            staged = self._load_staged_changes(scan_dir)
            self._video_assignments = staged_changes.live_assignments(
                staged.get("video"), self._video_slots_by_rel)
            self._warn_dropped_assignments(
                "video", staged.get("video"), self._video_slots_by_rel,
                scan_dir)
            if "video_trim" in staged:
                self.video_trim_var.set(bool(staged["video_trim"]))
            if "video_no_conversion" in staged:
                self.video_no_conversion_var.set(
                    bool(staged["video_no_conversion"]))
            self._restore_change_filter("video", staged)
            self._update_video_trim_enabled()
        else:
            self._video_assignments = {
                rel: rep for rel, rep in self._video_assignments.items()
                if rel in self._video_slots_by_rel}
        folder_changed = scan_dir != self._video_scan_dir
        self._video_scan_dir = scan_dir
        self._video_changed_on_disk = set()
        if folder_changed:
            # Drop the previous card's preview so it doesn't linger (and so the
            # new first row's select isn't short-circuited by a matching rel).
            self._video_clear_preview()
        self._refresh_video_list()
        # Default to the first clip so a poster frame shows on a fresh scan.
        self._select_first_tree_row(self._video_tree, self._video_on_tree_select)
        self._start_change_scan("video")
        # Now fill in duration / resolution / codec on a background thread so
        # the list is usable immediately even with hundreds of clips.
        self._probe_video_metadata_async(scan_id)

    def _probe_video_metadata_async(self, scan_id):
        """Probe ffprobe metadata for the just-scanned slots off the main
        thread.  Backend (.cdmd) slots are already populated by the scan, so
        only ffmpeg-format slots are probed.  See _run_probe_pass."""
        from ..core.video import backend_for, detect_video_info
        pending = [s for s in self._video_slots
                   if s.info is None and backend_for(s.abs_path) is None]
        if pending:
            self._run_probe_pass(scan_id, lambda: self._video_scan_id,
                                 pending, detect_video_info,
                                 self._apply_video_meta)

    def _apply_video_meta(self, scan_id, rel, info):
        """Main-thread: store a probed slot's metadata and update its row."""
        if self._video_scan_id != scan_id:
            return
        slot = self._video_slots_by_rel.get(rel)
        if slot is None:
            return
        slot.info = info
        slot.probed = True
        # A baked-in unplayable clip is worth a log line even when the row is
        # filtered out of view right now.
        self._warn_unplayable_slot(rel, slot)
        if rel == self._video_current_rel:
            # The loaded slot's playability just became answerable.
            self._video_update_preview_note(rel)
        tree = getattr(self, "_video_tree", None)
        if tree is None or not tree.exists(rel):
            return
        rep = self._video_assignments.get(rel)
        if rep:
            rep_disp = os.path.basename(rep)
        elif rel in self._video_changed_on_disk:
            rep_disp = "✓ changed on disk"
        else:
            rep_disp = "Choose…"
        tree.item(rel, values=(slot.duration_str(), slot.resolution_str(),
                               self._video_fmt_cell(slot),
                               slot.info.audio_summary() if slot.info else "",
                               rep_disp, self._video_conv_cached(rel, rep)))

    def _refresh_video_list(self):
        """Apply the search filter + sort and repopulate the slot tree."""
        tree = getattr(self, "_video_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())

        query = (self.video_search_var.get() or "").strip().lower()
        slots = [s for s in self._video_slots
                 if not query or query in s.rel_path.lower()]
        change_ok = self._change_filter_pred("video")
        if change_ok is not None:
            slots = [s for s in slots if change_ok(s.rel_path)]
        col, desc = self._video_sort

        changed = self._video_changed_on_disk

        def _key(s):
            if col == "len":
                return (s.duration,)
            if col == "res":
                wh = (s.info.width * s.info.height) if s.info else -1
                return (wh,)
            if col == "fmt":
                return (s.format_summary().lower(), s.rel_path.lower())
            if col == "aud":
                a = s.info.audio_summary() if s.info else ""
                return (a.lower(), s.rel_path.lower())
            if col == "rep":
                rep = self._video_assignments.get(s.rel_path)
                if rep:
                    return (0, os.path.basename(rep).lower())
                return (1, "") if s.rel_path in changed else (2, "")
            if col == "conv":
                mode = self._video_conv_cached(
                    s.rel_path, self._video_assignments.get(s.rel_path))
                # Unassigned / not-yet-determined rows sort last, so the
                # answered ones group at the top.
                return ((0, mode) if mode else (1, ""), s.rel_path.lower())
            return (s.rel_path.lower(),)  # "#0" name/path

        slots.sort(key=_key, reverse=desc)
        self._show_sort_arrows(tree, self._video_sort_cfg, self._video_sort)

        for s in slots:
            rep = self._video_assignments.get(s.rel_path)
            is_changed = s.rel_path in changed
            if rep:
                rep_disp = os.path.basename(rep)
                tag = "changed" if is_changed else "assigned"
            elif is_changed:
                rep_disp, tag = "✓ changed on disk", "changed"
            else:
                rep_disp, tag = "Choose…", ""
            if s.info is None and not s.probed:
                length, res, aud = "…", "…", "…"  # metadata still loading
            else:
                length, res = s.duration_str(), s.resolution_str()
                aud = s.info.audio_summary() if s.info else ""
            tree.insert("", tk.END, iid=s.rel_path, text=s.rel_path,
                        values=(length, res, self._video_fmt_cell(s), aud,
                                rep_disp,
                                self._video_conv_cached(s.rel_path, rep)),
                        tags=(tag,) if tag else ())

        total = len(self._video_slots)
        changed_total = len(set(self._video_assignments) | changed)
        if total == 0:
            self.video_status_var.set("")
            self._video_empty.configure(
                text="No replaceable video found in this folder.")
            self._video_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            shown = len(slots)
            extra = f"  ({shown} shown)" if shown != total else ""
            self.video_status_var.set(
                f"{changed_total} of {total} slots changed{extra}")
            self._video_empty.place_forget()
        self._autosize_tree_columns(
            tree, "video", ("#0", "len", "res", "fmt", "aud", "rep", "conv"))
        # Fill in any "…" Convert cells the rebuild just drew.
        self._video_probe_conv_async()
        # Option toggles funnel through here and can flip a cached verdict
        # instantly — keep the callout under the preview in step.
        self._video_update_preview_note()

    def _video_export_csv(self):
        """Save the video table as a CSV — the audio tab's Export CSV, mirrored
        for video (feedback batch 16)."""
        import csv
        if not self._video_slots:
            messagebox.showinfo("Export CSV",
                                "Scan an assets folder first — the video "
                                "table is empty.")
            return
        path = filedialog.asksaveasfilename(
            title="Save video table as CSV",
            defaultextension=".csv",
            initialdir=self.last_browse_dir("video_csv"),
            initialfile="video_slots.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        self.remember_browse_dir("video_csv", path)
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Original Video", "Length", "Resolution", "Format",
                            "Audio", "Replacement", "Convert",
                            "Changed On Disk"])
                for s in sorted(self._video_slots, key=lambda q: q.rel_path):
                    rel = s.rel_path
                    rep = self._video_assignments.get(rel, "")
                    w.writerow([
                        rel, s.duration_str(), s.resolution_str(),
                        self._video_fmt_cell(s),
                        s.info.audio_summary() if s.info else "",
                        rep,
                        self._video_conv_cache.get(
                            self._video_conv_key(rel, rep), "") if rep else "",
                        "yes" if rel in self._video_changed_on_disk else "",
                    ])
        except OSError as e:
            messagebox.showerror("Export CSV", "Couldn't write the CSV:\n%s"
                                 % e)
            return
        self.append_log("Video table exported: %d slot(s) → %s"
                        % (len(self._video_slots), os.path.normpath(path)),
                        "success")

    def _default_assets_from_extract(self):
        """Default the (shared) assets folder to the Extract tab's output when
        it's still empty — the common case is extract then immediately swap
        audio/video, so they shouldn't have to re-pick the same folder."""
        if (self.write_assets_var.get() or "").strip():
            return
        out = (self.extract_output_var.get() or "").strip()
        if out and os.path.isdir(out):
            self.write_assets_var.set(out)

    def invalidate_asset_scans(self, rescan_visible=True):
        """Force the Replace tabs to re-scan on their next visit, even when the
        assets-folder path is unchanged.  The per-tab auto-scan is keyed on the
        folder path (``assets_path != self._*_scan_dir``), so a fresh extract
        that repopulates a folder the tab already scanned would otherwise show
        stale (often empty) results until the user manually re-browses.  Clearing
        the stamps makes the next ``_maybe_rescan_*`` behave like a Browse.

        The stamps are remembered in ``_scan_dir_prev`` so the in-memory
        assignments (which this does NOT clear — the next scan re-homes them
        from the folder's sidecar) keep their folder identity for the
        Build/Export folder-mismatch warning.

        *rescan_visible* also re-scans the tab that is on screen right now;
        callers that go on to re-scan every tab anyway pass False."""
        for key, cur in (("audio", self._audio_scan_dir),
                         ("video", self._video_scan_dir),
                         ("image", self._image_scan_dir)):
            if cur:
                self._scan_dir_prev[key] = cur
        self._audio_scan_dir = ""
        self._video_scan_dir = ""
        self._image_scan_dir = ""
        self._text_scan_dir = ""
        # A cleared stamp only makes the NEXT tab visit re-scan — and the tab
        # you are already looking at never gets a <<NotebookTabChanged>>, so
        # after a Save As / Open project it kept showing the old project's
        # slots until you left the tab and came back (feedback batch 22, on a
        # fork).  Re-scan the visible tab here so what's on screen always
        # belongs to the project that's loaded.
        if rescan_visible:
            try:
                self._scan_assets_tab_by_name(self._current_tab_key())
            except (tk.TclError, AttributeError):
                pass

    def reload_assets_tabs(self):
        """Drop every Replace tab's scan stamp and re-scan ALL assets tabs
        against the current folder, so freshly-transferred assignments (written
        to the folder's sidecar / strings.tsv out-of-band) load into every tab
        at once.

        Scanning only the visible tab left the others holding stale in-memory
        assignments from a previously scanned folder, which then tripped the
        Write "replacements won't be applied" folder-mismatch warning even
        though the transfer had written its edits to the new folder's sidecar
        (and the build would apply them via the sidecar fallback).  Re-scanning
        every tab re-points each one's assignments at the new folder so the tabs,
        the warning check, and the build all agree."""
        self.invalidate_asset_scans(rescan_visible=False)
        try:
            self._rescan_all_assets_tabs()
        except Exception:
            pass

    # ---- Revert all changes (Write tab button -> app callback) -------

    def _revert_all_clicked(self):
        """Hand the current assets folder to the app's revert orchestration."""
        if self._on_revert_all is None:
            return
        assets_dir = (self.write_assets_var.get() or "").strip()
        self._on_revert_all(assets_dir)

    def _update_revert_btn_state(self):
        """Enable 'Revert all changes…' only when there's something to revert.

        The Write preview tree (Modified + Pending rows) is the change-count
        signal: an empty tree means nothing to revert, so the button greys out
        (a tester's request — it tells the user it isn't relevant).  When the
        preview tree isn't shown for this plugin, leave the button enabled (we
        have no count to gate on).  Never overrides the running-state disable."""
        btn = getattr(self, "_revert_all_btn", None)
        if btn is None or self._is_running():
            return
        tree = getattr(self, "_write_preview_tree", None)
        try:
            if tree is not None and tree.winfo_ismapped():
                state = tk.NORMAL if tree.get_children() else tk.DISABLED
            else:
                state = tk.NORMAL
            btn.configure(state=state)
        except tk.TclError:
            pass

    def clear_replace_assignments(self, assets_dir):
        """Drop every in-memory Replace-Audio/Video/Image assignment and wipe the
        staged-changes sidecar, so a revert leaves no assignment that would
        re-apply on the next build.  Called by the app's revert flow."""
        from ..core import staged_changes
        self._audio_assignments = {}
        self._video_assignments = {}
        self._image_assignments = {}
        staged_changes.save(assets_dir, {})

    def refresh_after_revert(self):
        """Re-sync the Replace tabs + Write preview after a revert changed the
        on-disk asset bytes (and cleared every assignment)."""
        self._audio_changed_on_disk = set()
        self._video_changed_on_disk = set()
        self._image_changed_on_disk = set()
        for fn in (getattr(self, "_refresh_audio_list", None),
                   getattr(self, "_refresh_video_list", None),
                   getattr(self, "_refresh_image_list", None)):
            if fn:
                try:
                    fn()
                except tk.TclError:
                    pass
        # Re-diff the still-loaded slots (their bytes changed) + re-scan the
        # Write preview so both reflect the reverted state.
        for kind in ("audio", "video", "image"):
            if getattr(self, "_%s_slots" % kind, None):
                self._start_change_scan(kind)
        if hasattr(self, "_write_preview_tree"):
            try:
                self._scan_reasons["write_preview"] = "after Revert all changes"
                self._scan_write_preview()
            except tk.TclError:
                pass
        # The Replace Text tab reads straight from the manifest, which the
        # revert just wiped.  If it had been scanned, actively reload it now —
        # only clearing the scan marker (the old behaviour) left the "New Text"
        # column showing the reverted edits until the user left and returned to
        # the tab.  Blank the marker too so a lazy re-scan still fires if the
        # active reload can't run (tab not built yet).
        if getattr(self, "_text_scan_dir", ""):
            self._text_scan_dir = ""
            if getattr(self, "_text_tree", None) is not None:
                try:
                    self._scan_text_strings()
                except tk.TclError:
                    pass

    def _reveal_menu_label(self):
        """OS-appropriate wording for the 'show this file in the file manager'
        context-menu item."""
        if sys.platform == "darwin":
            return "Reveal in Finder"
        if sys.platform == "win32":
            return "Show in File Explorer"
        return "Show in File Manager"

    def _reveal_in_file_manager(self, path):
        """Open the native file manager with *path* selected so the user can
        grab the original extracted asset and edit it in another tool.  Selects
        the file on Windows (Explorer) and macOS (Finder); Linux file managers
        have no portable 'select a file' verb, so we open its containing folder.
        Falls back to the folder when the file is missing, and never lets an
        error escape into the Tk callback."""
        import subprocess
        if not path:
            return
        path = os.path.abspath(path)
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        try:
            if sys.platform == "win32":
                if os.path.isfile(path):
                    subprocess.Popen(
                        'explorer /select,"%s"' % os.path.normpath(path))
                else:
                    os.startfile(folder)            # Windows-only; folder view
            elif sys.platform == "darwin":
                subprocess.Popen(
                    ["open", "-R", path] if os.path.isfile(path)
                    else ["open", folder])
            else:
                # Not a bare xdg-open: in a frozen/AppImage build the file
                # manager has to be launched with the bundle scrubbed out
                # of the environment or it dies on our bundled libs.
                ok, err = desktop.open_path(folder)
                if not ok:
                    raise RuntimeError(err)
        except Exception as e:
            messagebox.showwarning(
                "Couldn't open file manager",
                "Couldn't reveal this file:\n%s\n\n%s" % (path, e))

    def _maybe_rescan_video(self):
        """Auto-scan when the Replace Video tab becomes visible and the folder
        has changed since the last scan."""
        if self._current_mfr is None:
            return
        if not getattr(self._current_mfr.capabilities, "replace_video", False):
            return
        assets_path = (self.write_assets_var.get() or "").strip()
        if assets_path and assets_path != self._video_scan_dir:
            self._scan_video_slots_async()

    # ---- Replace Video: per-slot actions -----------------------------

    def _video_selected_rel(self):
        sel = self._video_tree.selection() if hasattr(self, "_video_tree") else ()
        return sel[0] if sel else None

    def _video_assign_rel(self, rel):
        """Open the replacement picker for *rel* and record the assignment."""
        if not rel or rel not in self._video_slots_by_rel:
            return
        self.stop_playback_for_picker()   # same as audio (batch 28)
        path = filedialog.askopenfilename(
            title=f"Choose a replacement for {rel}",
            initialdir=self.last_browse_dir("video_replacement"),
            filetypes=[("Video files",
                        "*.mp4 *.mov *.m4v *.webm *.ogv *.avi *.mkv *.mpg "
                        "*.mpeg *.wmv *.flv *.ts *.3gp *.gif"),
                       ("All files", "*.*")])
        if not path:
            return
        self.remember_browse_dir("video_replacement", path)
        # "No conversion" + a file the copy-through would reject used to fail
        # silently until build time ("✗ … needs a .mov") — a tester hit it.
        # Surface the mismatch here, while the user can still act on it.
        if self.video_no_conversion_var.get():
            why = self._video_noconv_conflict(rel, path)
            if why is not None:
                if messagebox.askyesno(
                        "Using your files as-is",
                        "%s.\n\nWith \"Use my files as-is\" ticked, this file "
                        "goes onto the card exactly as it is.\n\nUntick it so "
                        "replacements are converted to suit the slot?"
                        % why, icon="warning"):
                    self.video_no_conversion_var.set(False)
                    self._video_on_no_conversion_toggle()
                else:
                    self.append_log(
                        "Replace Video: %s — %s; it goes on the card as it is "
                        "unless 'Use my files as-is' is unticked."
                        % (rel, why), "error")
        self._video_assignments[rel] = path
        self._save_staged_changes()
        note = self._video_conversion_note(rel, path)
        self.append_log("Replace Video: %s ← %s%s"
                        % (rel, os.path.basename(path),
                           ("  (%s)" % note) if note else ""), "info")
        self._refresh_video_list()
        if rel == self._video_current_rel:
            self._video_load_rep_pane(rel)  # show the new pick right away
            self._video_update_preview_note(rel)
        try:
            self._video_tree.selection_set(rel)
            self._video_tree.see(rel)
        except tk.TclError:
            pass

    # ---- Replace Video: table interactions ---------------------------

    def _cancel_video_select_job(self):
        if self._video_select_job is not None:
            try:
                self._tk_root().after_cancel(self._video_select_job)
            except Exception:
                pass
            self._video_select_job = None

    def _video_on_tree_select(self, _event=None):
        self._cancel_video_select_job()
        self._video_select_job = self._tk_root().after(
            250, self._video_preview_selected)

    def _video_preview_selected(self):
        self._video_select_job = None
        rel = self._video_selected_rel()
        if rel is None or rel == self._video_current_rel:
            return
        # Selecting a different row while a clip plays stops it and loads the
        # new row right away, resuming on the same pane (feedback batch 14 —
        # same flow as the audio tab).
        resume = None
        if self._video_pane_orig and self._video_pane_orig.playing:
            resume = "orig"
        elif self._video_pane_rep and self._video_pane_rep.playing:
            resume = "rep"
        self._video_load_track(rel, autoplay=resume)

    def _video_on_tree_double(self, _event=None):
        # Double-click = choose a replacement (see _audio_on_tree_double).
        if not self._double_click_on_rows(self._video_tree, _event):
            return
        self._cancel_video_select_job()
        rel = self._video_selected_rel()
        if rel is None:
            messagebox.showinfo(
                "No Slot Selected",
                "Select a clip in the list first, then choose a replacement.")
            return
        self._video_assign_rel(rel)

    def _video_on_tree_click(self, event):
        tree = self._video_tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        row = tree.identify_row(event.y)
        # cols=(len,res,fmt,aud,rep) -> #1..#5; Replacement is #5.
        col = tree.identify_column(event.x)
        if row and col == "#5":
            tree.selection_set(row)
            self._cancel_video_select_job()
            self._video_assign_rel(row)

    def _video_on_tree_right(self, event):
        tree = self._video_tree
        row = tree.identify_row(event.y)
        if not row:
            return
        tree.selection_set(row)
        menu = tk.Menu(tree, tearoff=0)
        c = THEMES.get(self._current_theme, {})
        try:
            menu.configure(
                background=c.get("field_bg"), foreground=c.get("fg"),
                activebackground=c.get("select_bg"),
                activeforeground="#ffffff")
        except tk.TclError:
            pass
        menu.add_command(label="▶  Play original",
                         command=self._video_play_original)
        menu.add_command(label="Choose replacement…",
                         command=lambda r=row: self._video_assign_rel(r))
        if self._video_assignments.get(row):
            menu.add_command(label="▶  Play replacement",
                             command=self._video_play_replacement)
            menu.add_separator()
            menu.add_command(label="Clear replacement",
                             command=self._video_clear_selected)
        if getattr(self._current_mfr, "key", "") == "stern":
            # Same route the Images tab offers: a clip belongs to one scene,
            # and the Scenes window is where you see what plays around it.
            menu.add_separator()
            menu.add_command(
                label="Show scene contents…",
                command=lambda r=row: self._open_scene_browser(
                    preselect_video=r))
        slot = self._video_slots_by_rel.get(row)
        if slot is not None:
            menu.add_separator()
            menu.add_command(
                label="What this slot needs…",
                command=lambda r=row: self._video_show_target_spec(r))
            menu.add_command(
                label=self._reveal_menu_label(),
                command=lambda p=slot.abs_path: self._reveal_in_file_manager(p))
            self._add_find_in_partition_item(menu, "video", row)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _video_show_target_spec(self, rel):
        """"What this slot needs…": the exact shape of a drop-in for *rel*,
        plus an ffmpeg command that produces one.

        A tester encodes his own clips on purpose — he tunes the key-frame
        interval so long videos play smoothly on the machine — and avoids the
        app's conversion for that reason.  He was doing it blind: his attract
        clip was ProRes in a .mov, which the i.MX6's decoder cannot touch, so
        it went on the card as-is and played its sound over a black picture.
        The clip already in the slot is the authority on what the machine
        accepts, so this just reads it out."""
        from ..core import video as _video
        slot = self._video_slots_by_rel.get(rel)
        if slot is None:
            return
        info = slot.info
        if info is None:
            messagebox.showinfo(
                "What this slot needs",
                "This clip hasn't been probed yet — its Length / Resolution / "
                "Format cells still read \"…\".\n\nGive the scan a moment and "
                "try again. (Without ffmpeg on this machine the app can't "
                "read the clip's format at all.)")
            return
        spec = _video.dropin_spec(info, slot.ext)
        cmd = _video.dropin_ffmpeg_command(info, slot.ext)

        dlg = tk.Toplevel(self._tk_root())
        dlg.title("What this slot needs")
        dlg.transient(self._tk_root())
        self._theme_toplevel(dlg)
        ttk.Label(dlg, text=rel, font=(_SANS_FONT, 10, "bold")).pack(
            anchor=tk.W, padx=12, pady=(12, 2))
        ttk.Label(
            dlg, justify=tk.LEFT, wraplength=560,
            text="A replacement matching this goes onto the card untouched, "
                 "at full quality. Anything else has to be converted first — "
                 "untick \"Use my files as-is\" and the app will do it.").pack(
            anchor=tk.W, padx=12, pady=(0, 8))
        grid = ttk.Frame(dlg)
        grid.pack(anchor=tk.W, padx=12)
        for i, (label, value) in enumerate(spec or ()):
            ttk.Label(grid, text=label + ":", foreground="#888888").grid(
                row=i, column=0, sticky="w", padx=(0, 10), pady=1)
            ttk.Label(grid, text=value).grid(row=i, column=1, sticky="w",
                                             pady=1)
        if cmd:
            ttk.Label(
                dlg, justify=tk.LEFT, wraplength=560,
                text="To encode your own, start from this and tune whatever "
                     "you like around it (bitrate, key-frame interval, "
                     "preset) — the flags below are the parts that have to "
                     "match:").pack(anchor=tk.W, padx=12, pady=(10, 4))
            _c = THEMES.get(self._current_theme, {})
            box = tk.Text(dlg, height=3, wrap=tk.WORD, width=68,
                          font=(_MONO_FONT, 9), relief=tk.FLAT,
                          bg=_c.get("field_bg"), fg=_c.get("fg"),
                          selectbackground=_c.get("select_bg"),
                          highlightthickness=1,
                          highlightbackground=_c.get("border"))
            box.insert("1.0", cmd)
            box.configure(state=tk.DISABLED)   # selectable, not editable
            box.pack(fill=tk.X, padx=12)
            if not info.has_audio:
                ttk.Label(
                    dlg, justify=tk.LEFT, wraplength=560,
                    font=(_SANS_FONT, 8),
                    text="The -an is deliberate: this slot's clip has no "
                         "audio track, and one you add will be played.").pack(
                    anchor=tk.W, padx=12, pady=(2, 0))

        row = ttk.Frame(dlg)
        row.pack(fill=tk.X, padx=12, pady=12)

        def _copy():
            try:
                self._tk_root().clipboard_clear()
                self._tk_root().clipboard_append(cmd)
            except tk.TclError:
                return
            self.append_log("Copied the ffmpeg command for %s." % rel, "info")
        if cmd:
            ttk.Button(row, text="Copy command", command=_copy).pack(
                side=tk.LEFT)
        ttk.Button(row, text="Close", command=dlg.destroy,
                   style="Go.TButton").pack(side=tk.RIGHT)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        center_over(self._tk_root(), dlg)
        dlg.resizable(False, False)

    def _video_clear_selected(self):
        rel = self._video_selected_rel()
        if rel is not None and rel in self._video_assignments:
            del self._video_assignments[rel]
            self._save_staged_changes()
            self.append_log("Replace Video: cleared replacement for %s" % rel,
                            "info")
            self._refresh_video_list()
            if rel == self._video_current_rel:
                self._video_load_rep_pane(rel)  # back to "no replacement"
                self._video_update_preview_note(rel)
            try:
                self._video_tree.selection_set(rel)
            except tk.TclError:
                pass

    def _video_play_original(self):
        rel = self._video_selected_rel()
        if rel is None:
            messagebox.showinfo("No Slot Selected",
                                "Select a clip to preview.")
            return
        self._video_load_track(rel, autoplay="orig")

    def _video_play_replacement(self):
        rel = self._video_selected_rel()
        if not (rel and self._video_assignments.get(rel)):
            messagebox.showinfo("No Replacement",
                                "Assign a replacement to this slot first.")
            return
        self._video_load_track(rel, autoplay="rep")

    # ---- Replace Video: preview panes (Original | Replacement) -------

    def _video_load_track(self, rel, autoplay=None):
        """Load *rel* into both preview panes — its original on the left, its
        assigned replacement (if any) on the right.  *autoplay* names the
        pane to start ("orig"/"rep"), or None to just poster the frames."""
        if rel not in self._video_slots_by_rel:
            return
        from ..core import staged_originals
        self._video_current_rel = rel
        slot = self._video_slots_by_rel.get(rel)
        opath = slot.abs_path if slot else None
        # Already-changed slots hold replacement bytes; the .orig snapshot is
        # the true original (see _audio_load_track).
        snap_used = False
        changed = self._slot_changed_on_disk("video", rel)
        if changed:
            snap = staged_originals.snapshot_path(self._video_scan_dir, rel)
            if snap:
                opath = snap
                snap_used = True
        # Honest title when there's no snapshot (see _audio_load_track).
        self._video_pane_orig.base_title = (
            "Current file (already modified)"
            if changed and not snap_used
            else "Original")
        if opath and os.path.isfile(opath):
            self._video_pane_orig.load(opath, autoplay=(autoplay == "orig"))
        else:
            self._video_pane_orig.clear()
        self._video_load_rep_pane(rel, autoplay=(autoplay == "rep"))
        self._video_update_preview_note(rel)

    def _video_load_rep_pane(self, rel, autoplay=False):
        """(Re)load the Replacement pane for *rel* — after a clip change or
        an assign/clear of the currently-loaded slot."""
        from ..core import staged_originals
        rpath = self._video_assignments.get(rel) if rel else None
        if rpath and os.path.isfile(rpath):
            self._video_pane_rep.load(rpath, autoplay=autoplay)
            return
        # Already-changed slot with its true original on the left: the
        # on-disk file is the effective replacement (see audio twin).  The
        # snapshot alone is the test — the change scan may still be hashing
        # (see _slot_changed_on_disk).
        if staged_originals.snapshot_path(self._video_scan_dir, rel):
            slot = self._video_slots_by_rel.get(rel)
            cur = slot.abs_path if slot else None
            if cur and os.path.isfile(cur):
                self._video_pane_rep.load(cur, autoplay=autoplay)
                return
        self._video_pane_rep.clear("no replacement assigned")

    # Convert answers that mean "the machine will get something it can play".
    _VIDEO_CONV_GOOD = (_VIDEO_CONV_ASIS, _VIDEO_CONV_REENC,
                        _VIDEO_CONV_REPACK, _VIDEO_CONV_ASIS_NOISY)

    def _video_update_preview_note(self, rel=None):
        """Show/hide the big callout under the preview panes for the loaded
        slot (batch 25: the ⚠ glyph alone didn't stand out, and a slot whose
        current clip is unplayable had no visible text at all).

        Three states, cheapest-first — nothing here probes a file, so it can
        run on every selection / list refresh:
          * the slot's CURRENT clip is unplayable and a good replacement is
            already picked → amber: the Format/Audio columns keep describing
            the clip that is in the slot until the next build (batch 25: he
            read the unchanged "prores" cell as the app mis-probing his fresh
            H.264 pick);
          * unplayable with no good pick yet → red, act before building;
          * the pick itself would be rejected as-is → red.
        """
        lbl = getattr(self, "_video_preview_note", None)
        if lbl is None:
            return
        if rel is None:
            rel = self._video_current_rel
        slot = self._video_slots_by_rel.get(rel) if rel else None
        text = color_key = None
        if slot is not None:
            why = self._slot_unplayable(slot)
            rep = self._video_assignments.get(rel)
            mode = self._video_conv_cached(rel, rep) if rep else ""
            if why:
                if mode in self._VIDEO_CONV_GOOD:
                    text = ("⚠  The clip in this slot right now %s — the "
                            "Format and Audio columns describe that clip "
                            "until you build. Your replacement goes on at "
                            "the next build and fixes it." % why)
                    color_key = "warning"
                else:
                    text = ("⚠  WRONG FORMAT — the clip in this slot %s. On "
                            "the machine it will play its sound over a black "
                            "picture. Assign a good replacement (or "
                            "right-click → revert the slot) before building."
                            % why)
                    color_key = "error"
            elif rep and mode in (self._VIDEO_CONV_REJECT,
                                  self._VIDEO_CONV_ASIS_NOISY):
                conflict = self._video_noconv_conflict(rel, rep, deep=False)
                if mode == self._VIDEO_CONV_ASIS_NOISY:
                    text = ("⚠  %s brings its own audio track and this "
                            "slot's clip has none — the machine will play it "
                            "over the game's sound."
                            % os.path.basename(rep))
                    color_key = "warning"
                else:
                    text = ("✗  WRONG FORMAT — %s. As-is it will play its "
                            "sound over a black picture on the machine. "
                            "Untick \"Use my files as-is\" to have it "
                            "converted, or pick a game-ready file."
                            % (conflict or ("%s can't play on the machine "
                                            "as it is"
                                            % os.path.basename(rep))))
                    color_key = "error"
        if not text:
            lbl.pack_forget()
            return
        c = THEMES.get(self._current_theme, {})
        try:
            lbl.configure(text=text,
                          foreground=c.get(color_key) or c.get("fg"))
        except tk.TclError:
            return
        if not lbl.winfo_manager():
            lbl.pack(fill=tk.X, padx=8, pady=(0, 6))

    def _video_activate_pane(self, side):
        """▶ pressed on an empty pane: load the selected row, then play the
        pane that asked."""
        rel = self._video_selected_rel()
        if rel is not None:
            self._video_load_track(rel, autoplay=side)

    def _video_stop_playback(self):
        """Stop both preview panes (keeps their playheads where they landed)."""
        for pane in (self._video_pane_orig, self._video_pane_rep):
            if pane is not None:
                pane.stop_playback()

    def stop_all_preview_playback(self):
        """Stop every preview pane (Replace Audio + Replace Video, Original
        and Replacement sides) and kill their ffplay/ffmpeg children.  Called
        on every tab change and on app close so a playing song/clip never
        outlives the tab it was started on -- an ffplay child is a detached
        OS process that otherwise keeps playing after the window is gone.
        Idempotent and safe for plugins that never built either player (the
        pane handles default to None in __init__)."""
        try:
            self._audio_stop_playback()
        except Exception:
            pass
        try:
            self._video_stop_playback()
        except Exception:
            pass

    def stop_playback_for_picker(self):
        """Silence every preview before a modal "choose a replacement" dialog
        opens.

        A modal file dialog does NOT stop Tk's timers, so an audition running
        under "Play sequentially" kept playing — and kept STEPPING DOWN THE
        LIST — behind the open picker, which then handed the row back with a
        different track loaded in the preview (a tester: "if I am playing audio
        files sequentially and I double click to open the file replace dialog
        on anything, the sounds just keeps going down the list").  Sequential
        play stays ticked; pressing ▶ again resumes it from where you are."""
        self.stop_all_preview_playback()

    def _video_clear_preview(self):
        """Reset both preview panes entirely (used on manufacturer switch)."""
        self._cancel_video_select_job()
        self._video_current_rel = None
        if self._video_pane_orig is not None:
            self._video_pane_orig.base_title = "Original"
            self._video_pane_orig.clear()
        if self._video_pane_rep is not None:
            self._video_pane_rep.clear("no replacement assigned")
        note = getattr(self, "_video_preview_note", None)
        if note is not None:
            try:
                note.pack_forget()
            except tk.TclError:
                pass

    # ---- Replace Video: pending assignments (applied at Write time) --

    def pending_video_assignments(self, assets_dir):
        """Return ``(slots_by_rel, assignments, trim, no_conversion)`` of
        replacements the user assigned for *assets_dir*, or ``None`` when
        there's nothing to apply.  Called by the Write flow to auto-stage edits
        just before it repacks — there is no manual "stage" step.

        Guarded so it only fires when the folder being written is the same one
        the assignments were made against."""
        mfr = self._current_mfr
        if mfr is None or not getattr(
                mfr.capabilities, "replace_video", False):
            return None
        if not assets_dir:
            return None
        scanned = self._video_scan_dir or ""
        if (os.path.normcase(os.path.normpath(assets_dir))
                != os.path.normcase(os.path.normpath(scanned))):
            return None
        assignments = {rel: rep for rel, rep in self._video_assignments.items()
                       if rep and rel in self._video_slots_by_rel}
        if not assignments:
            return None
        return (dict(self._video_slots_by_rel), assignments,
                bool(self.video_trim_var.get()),
                bool(self.video_no_conversion_var.get()))

    # ==================================================================
    # Replace Image tab — mirrors Replace Video, but the preview is a
    # single static thumbnail (no player / threads / ffmpeg / seek bar).
    # ==================================================================

    def _build_image_tab(self):
        """Build the 'Replace Image' tab: a searchable list of the image files
        in the extracted assets folder, each a slot the user can assign a
        replacement for, with a static thumbnail preview.  Staging scales each
        replacement to its slot's pixel dimensions/format and writes it over the
        original so the normal Write step repacks it."""
        f = self._tab_image
        pad = {"padx": 10, "pady": 4}

        # One-line intro; the full behaviour notes live in the "?" tips window.
        _image_desc = ttk.Label(
            f,
            text="Assign a replacement image to any slot — it's auto-scaled "
                 "and converted to the slot's format — then build the update "
                 "on the Write tab.",
            font=(_SANS_FONT, 9, "italic"),
            wraplength=720, justify=tk.LEFT)
        _image_desc.pack(anchor=tk.W, **pad)
        self._register_responsive_wrap(_image_desc)

        # Pillow-missing banner.  Image matching is always a re-encode, so
        # Pillow is effectively required here.  Pack-managed by
        # _refresh_image_pillow_warning(); positioned before the assets row.
        self._image_pillow_warn = ttk.Label(
            f,
            text="⚠ Pillow not found — replacing images needs Pillow to scale "
                 "+ re-encode images. Install it with “Install Missing” above "
                 "the tabs.",
            foreground="#d04040", font=(_SANS_FONT, 9),
            wraplength=720, justify=tk.LEFT)

        # Assets folder row (shared with the Write / Replace Audio/Video tabs).
        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        self._image_assets_row = row
        ttk.Label(row, text="Project Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._project_mirror_label(row).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._make_assets_scan_buttons(row, "image",
                                       self._scan_image_slots_async)

        # Search + sort toolbar.
        tools = ttk.Frame(f); tools.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(tools, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(tools, textvariable=self.image_search_var, width=24).pack(
            side=tk.LEFT, padx=(4, 12))
        # Source filter (a tester): narrow the list to one of the image
        # stores; the values mirror the Source column's labels.
        self._image_source_combo = ttk.Combobox(
            tools, textvariable=self.image_source_filter_var,
            state="readonly", width=13,
            values=("All sources", "File", "Scene texture", "Radium",
                    "Glyph"))
        self._image_source_combo.pack(side=tk.LEFT, padx=(0, 12))
        self._image_source_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._save_staged_changes())
        _Tooltip(
            self._image_source_combo,
            "Show only images from one store: plain files on the card, "
            "scene.assets textures, radium-embedded images, or per-character "
            "font glyph slices (the Source column).",
            lambda: self._current_theme)
        self._build_change_filter(tools, "image").pack(
            side=tk.LEFT, padx=(0, 8))
        self._image_group_cb = ttk.Checkbutton(
            tools, text="Group by scene",
            variable=self.image_group_by_scene_var,
            command=self._save_staged_changes)
        self._image_group_cb.pack(side=tk.LEFT, padx=(0, 12))
        _Tooltip(
            self._image_group_cb,
            "Group the images under the scene / animation they belong to "
            "(in play order), so a whole animation can be reviewed — or "
            "bulk-replaced via right-click — as one unit.",
            lambda: self._current_theme)
        # Fonts / Scenes tool windows (a tester): preview + import whole game
        # fonts, and browse what each scene is made of.
        fonts_btn = ttk.Button(tools, text="Fonts…", width=7,
                               command=self._open_font_studio)
        fonts_btn.pack(side=tk.LEFT, padx=(0, 4))
        _Tooltip(
            fonts_btn,
            "Preview any game font (type your own text, rendered from the "
            "real glyphs) and import a desktop font into it — letters are "
            "auto-fitted into the space each character has. Stern Spike 2.",
            lambda: self._current_theme)
        scenes_btn = ttk.Button(tools, text="Scenes…", width=8,
                                command=self._open_scene_browser)
        scenes_btn.pack(side=tk.LEFT, padx=(0, 12))
        _Tooltip(
            scenes_btn,
            "Browse the card scene by scene: the images, fonts and on-screen "
            "text each scene is built from, with jumps to the matching rows "
            "here and on Replace Text. Stern Spike 2.",
            lambda: self._current_theme)
        self._image_status_lbl = ttk.Label(
            tools, textvariable=self.image_status_var,
            font=(_SANS_FONT, 9))
        self._image_status_lbl.pack(side=tk.RIGHT)

        # Slot list.
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        # "src" tells the three image stores apart (a tester: file-system
        # PNGs, scene textures and radium-embedded images were indistinguishable
        # beyond their paths) — see _image_source_label.
        # "n" (Images) is grouped-mode only: the per-group member count as its
        # own sortable column (a tester: the count baked into the header text
        # couldn't be sorted on) — _refresh_image_list toggles displaycolumns.
        self._image_tree = ttk.Treeview(
            list_frame, columns=("n", "res", "fmt", "src", "rep"),
            height=9, selectmode="browse")
        self._image_tree.heading("#0", text="Original Image", anchor=tk.W)
        self._image_tree.heading("n", text="Images", anchor=tk.W)
        self._image_tree.heading("res", text="Resolution", anchor=tk.W)
        self._image_tree.heading("fmt", text="Format", anchor=tk.W)
        self._image_tree.heading("src", text="Source", anchor=tk.W)
        self._image_tree.heading("rep", text="Replacement", anchor=tk.W)
        self._image_tree.column("#0", width=300, minwidth=160)
        self._image_tree.column("n", width=70, minwidth=50, anchor=tk.W,
                                stretch=False)
        self._image_tree.column("res", width=90, minwidth=70, anchor=tk.W)
        self._image_tree.column("fmt", width=140, minwidth=80)
        self._image_tree.column("src", width=100, minwidth=70, anchor=tk.W,
                                stretch=False)
        self._image_tree.column("rep", width=200, minwidth=110)
        self._image_tree["displaycolumns"] = ("res", "fmt", "src", "rep")
        self._persist_tree_columns(
            self._image_tree, "image", ("#0", "n", "res", "fmt", "src", "rep"))
        self._image_sort_cfg = [
            ("#0", "Original Image", False), ("n", "Images", True),
            ("res", "Resolution", True),
            ("fmt", "Format", False), ("src", "Source", False),
            ("rep", "Replacement", False)]
        self._wire_sort_headings(self._image_tree, self._image_sort_cfg,
                                 "_image_sort", self._refresh_image_list)
        image_scroll = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self._image_tree.yview)
        self._image_tree.configure(yscrollcommand=image_scroll.set)
        image_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._image_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._image_tree.bind("<Double-1>", self._image_on_tree_double)
        self._image_tree.bind("<Button-1>", self._image_on_tree_click, add="+")
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self._image_tree.bind(seq, self._image_on_tree_right)
        self._image_tree.bind("<<TreeviewSelect>>", self._image_on_tree_select)

        self._image_empty = ttk.Label(
            list_frame,
            text="Set the project folder on the Extract tab, then click Scan.",
            foreground="#888888", anchor=tk.CENTER, justify=tk.CENTER)
        self._image_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # --- Static preview: original and assigned replacement side-by-side,
        # so a transferred/assigned slot can be reviewed at a glance (the old
        # single thumbnail showed the replacement INSTEAD of the original).
        # No seek bar / transport. ---
        preview = ttk.LabelFrame(f, text=" Preview ")
        preview.pack(fill=tk.X, padx=10, pady=(4, 2))
        panes = ttk.Frame(preview)
        panes.pack(padx=6, pady=(2, 6))
        # Kept as attributes so the preview loader can retitle the left pane
        # honestly for a slot that's already changed on disk (a tester).
        self._image_hdr_orig = ttk.Label(panes, text="Original",
                                         font=(_SANS_FONT, 9))
        self._image_hdr_orig.grid(row=0, column=0, pady=(2, 1))
        ttk.Label(panes, text="Replacement", font=(_SANS_FONT, 9)).grid(
            row=0, column=1, pady=(2, 1))
        self._image_canvas = tk.Canvas(
            panes, width=320, height=214, highlightthickness=1, bd=0,
            background="#000000")
        self._image_canvas.grid(row=1, column=0, padx=(0, 4))
        self._image_canvas_rep = tk.Canvas(
            panes, width=320, height=214, highlightthickness=1, bd=0,
            background="#000000")
        self._image_canvas_rep.grid(row=1, column=1, padx=(4, 0))

        self._image_note_lbl = ttk.Label(
            f, text="", font=(_SANS_FONT, 8, "italic"),
            foreground="#888888", wraplength=720, justify=tk.LEFT)
        self._image_note_lbl.pack(anchor=tk.W, padx=30, pady=(0, 2))


        self._refresh_image_pillow_warning()

    def _refresh_image_pillow_warning(self):
        """Show the Pillow-missing banner only when Pillow can't be imported.
        Re-probes on each tab visit so installing Pillow mid-session clears the
        banner next time the tab is opened."""
        warn = getattr(self, "_image_pillow_warn", None)
        if warn is None:
            return
        from ..core import image as _image
        if _image.pil_available():
            warn.pack_forget()
        elif not warn.winfo_ismapped():
            warn.pack(fill=tk.X, padx=12, pady=(0, 4),
                      before=self._image_assets_row)

    # ---- Replace Image: scanning -------------------------------------

    def _scan_image_slots_async(self):
        """Scan the assets folder for image slots on a worker thread, then
        repopulate the list.  Stale scans are dropped via a bump-counter."""
        import threading
        from ..core.image_slots import scan_image_slots

        assets_path = (self.write_assets_var.get() or "").strip()
        self._image_scan_id += 1
        scan_id = self._image_scan_id

        if not assets_path or not os.path.isdir(assets_path):
            self._image_slots = []
            self._image_slots_by_rel = {}
            self._image_groups = {}
            self._image_group_occ = {}
            self._image_groups_all = {}
            self._image_group_key_tails = {}
            self._refresh_image_list()
            self._image_empty.configure(
                text="Set the project folder on the Extract tab, then click Scan.")
            self._image_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            self._set_tab_scanning("image", False)
            return

        self._image_empty.configure(text="Scanning for image files…")
        self._image_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        mfr = self._current_mfr

        def _work():
            try:
                roots = mfr.image_slot_dirs(assets_path) if mfr else None
            except Exception:
                roots = None
            try:
                exts = mfr.image_slot_exts(assets_path) if mfr else None
            except Exception:
                exts = None
            try:
                # Fast walk: list slots instantly; Pillow metadata is filled in
                # afterwards on a background pass.
                slots = scan_image_slots(assets_path, roots=roots, exts=exts,
                                         probe=False)
            except Exception:
                slots = []
            try:
                groups, group_occ, group_all = self._scan_image_groups(
                    assets_path)
            except Exception:
                groups, group_occ, group_all = {}, {}, {}
            if self._image_scan_id != scan_id:
                return
            self._tk_root().after(
                0, self._populate_image_after_scan,
                slots, scan_id, assets_path, groups, group_occ, group_all)

        self._set_tab_scanning("image", True)
        threading.Thread(target=_work, daemon=True).start()

    def _populate_image_after_scan(self, slots, scan_id, scan_dir,
                                   groups=None, group_occ=None,
                                   group_all=None):
        """Main-thread: store scan results and refresh the list."""
        if self._image_scan_id != scan_id:
            return
        self._set_tab_scanning("image", False)
        self._image_slots = slots
        self._image_slots_by_rel = {s.rel_path: s for s in slots}
        self._image_groups = groups or {}
        self._image_group_occ = group_occ or {}
        self._image_groups_all = group_all or {}
        self._image_group_key_tails = self._compute_image_key_tails(
            self._image_groups, self._image_groups_all)
        # Restore assignments persisted for a freshly-scanned folder; a re-scan
        # of the same folder keeps the live in-memory ones (see audio above).
        from ..core import staged_changes
        if scan_dir != self._image_scan_dir:
            staged = self._load_staged_changes(scan_dir)
            self._image_assignments = staged_changes.live_assignments(
                staged.get("image"), self._image_slots_by_rel)
            self._warn_dropped_assignments(
                "image", staged.get("image"), self._image_slots_by_rel,
                scan_dir)
            self._restore_change_filter("image", staged)
            if "image_group_by_scene" in staged:
                self.image_group_by_scene_var.set(
                    bool(staged["image_group_by_scene"]))
            tags = staged.get("image_group_tags")
            self._image_group_tags = (
                {str(k): str(v).strip()[:50] for k, v in tags.items()
                 if str(v).strip()}
                if isinstance(tags, dict) else {})
            self._seed_group_tags_from_library(scan_dir)
            srcf = staged.get("image_source_filter")
            if srcf in ("All sources", "File", "Scene texture", "Radium",
                        "Glyph"):
                self.image_source_filter_var.set(srcf)
        else:
            self._image_assignments = {
                rel: rep for rel, rep in self._image_assignments.items()
                if rel in self._image_slots_by_rel}
        folder_changed = scan_dir != self._image_scan_dir
        self._image_scan_dir = scan_dir
        self._image_changed_on_disk = set()
        if folder_changed:
            # A new folder's slots supersede the previous card's — drop the stale
            # preview so it doesn't keep showing the old image (and so selecting
            # the new first row isn't short-circuited by a matching current_rel).
            self._image_clear_preview()
        self._refresh_image_list()
        # Default to the first image so the preview isn't blank on a fresh scan.
        self._select_first_tree_row(self._image_tree, self._image_on_tree_select)
        self._start_change_scan("image")
        # Fill in dimensions / format on a background thread so the list is
        # usable immediately even with hundreds of images.
        self._probe_image_metadata_async(scan_id)

    def _probe_image_metadata_async(self, scan_id):
        """Probe Pillow metadata for the just-scanned slots off the main
        thread.  See _run_probe_pass."""
        from ..core.image import detect_image_info
        pending = [s for s in self._image_slots if s.info is None]
        if pending:
            self._run_probe_pass(scan_id, lambda: self._image_scan_id,
                                 pending, detect_image_info,
                                 self._apply_image_meta)

    def _apply_image_meta(self, scan_id, rel, info):
        """Main-thread: store a probed slot's metadata and update its row."""
        if self._image_scan_id != scan_id:
            return
        slot = self._image_slots_by_rel.get(rel)
        if slot is None:
            return
        slot.info = info
        slot.probed = True
        tree = getattr(self, "_image_tree", None)
        if tree is None or not tree.exists(rel):
            return
        rep = self._image_assignments.get(rel)
        rep_disp = os.path.basename(rep) if rep else "Choose…"
        tree.item(rel, values=("", slot.resolution_str(),
                               slot.format_summary(),
                               self._image_source_label(rel), rep_disp))

    def _select_first_tree_row(self, tree, on_select=None):
        """Select (and reveal) the first row of *tree* so a fresh scan shows a
        default preview instead of a blank pane.  No-op on an empty tree.  Calls
        *on_select* explicitly since a programmatic ``selection_set`` doesn't
        reliably fire ``<<TreeviewSelect>>`` across Tk versions."""
        if tree is None:
            return
        children = tree.get_children()
        if not children:
            return
        first = children[0]
        try:
            tree.selection_set(first)
            tree.focus(first)
            tree.see(first)
        except tk.TclError:
            return
        if on_select is not None:
            on_select()

    @staticmethod
    def _image_source_label(rel_path):
        """Which of the image stores *rel_path* came from (a tester: make
        them tell-apart-able + sortable).  Derived purely from the extract
        layout: the Stern engine lands decoded scene textures under
        ``scene_textures/`` (radium-embedded ones named ``radimg_*``,
        per-character font slices under ``glyphs/``); every other image is a
        plain file copied off the card.  Non-Stern plugins simply show "File"
        throughout."""
        parts = rel_path.replace("\\", "/").lower().split("/")
        if "scene_textures" in parts:
            if "glyphs" in parts:
                return "Glyph"
            if os.path.basename(rel_path).lower().startswith("radimg"):
                return "Radium"
            return "Scene texture"
        return "File"

    @staticmethod
    def _scan_image_groups(assets_path):
        """Parse the Stern extractor's image manifests (all optional) into the
        "Group by scene" mapping: ``({rel_path: (group_key, label_base,
        order)}, {rel_path: occurrences}, {rel_path: [every occurrence's
        (group_key, label_base, order)]})``.

        Grouping identity is the on-card container: the radium card path for
        radium-embedded images (ordered by data offset = the animation's
        frame/play order), the scene directory for scene.assets textures, and
        the card directory for loose images.  Radium PNGs are extracted
        content-deduplicated across containers — the FIRST manifest row is a
        PNG's home group, and *occurrences* remembers how many on-card slots
        it patches.  Cheap text parsing (a few thousand tab rows), run on the
        scan worker thread; a slot no manifest covers (every non-Stern plugin)
        falls back to its parent folder in :meth:`_image_group_of`.

        The third mapping exists because a home group alone makes a shared
        image findable under ONE scene only — a scene whose every image is
        first seen elsewhere then has no row anywhere and searching its id
        finds nothing (a tester's training scene).  Search and grouping use it to
        show an image under whichever of its scenes you asked for."""
        import re as _re

        groups, occ, where = {}, {}, {}

        def _rows(*parts):
            try:
                with open(os.path.join(assets_path, *parts),
                          encoding="utf-8") as f:
                    for line in f:
                        line = line.rstrip("\r\n")
                        if line and not line.startswith("#"):
                            yield line.split("\t")
            except OSError:
                return

        # Radium-embedded images: one row per on-card occurrence
        # (output, radium card path, data offset, length, pad_w, pad_h, fmt).
        primary = {}                # rel -> (card, data_off) of its first row
        per_card = {}               # card -> [(data_off, rel), ...]
        for cols in _rows("images", "scene_textures", "radium_images.txt"):
            if len(cols) < 3:
                continue
            try:
                off = int(cols[2])
            except ValueError:
                continue
            rel = "images/" + cols[0]
            occ[rel] = occ.get(rel, 0) + 1
            primary.setdefault(rel, (cols[1], off))
            per_card.setdefault(cols[1], []).append((off, rel))
        # A group's friendly name: the element-name hint baked into the first
        # member's filename (radimg_<Name>_<WxH>_<hash8>.png — see the
        # extractor's naming), plus the container's scene-hash parent dir
        # shortened to 8 chars (the Replace Text Scene-column shorthand).
        # The hash half is not decoration: element hints repeat across
        # sibling containers (TMNT's four char-select scenes all lead with
        # the same sprite name) and hash-named members carry no hint at all,
        # so neither half alone is unique or searchable.
        name_re = _re.compile(
            r"^radimg_(.+)_\d+x\d+_[0-9a-f]{8}\.png$", _re.IGNORECASE)
        # A font atlas carries an element-name hint too — the FONT family,
        # which Stern prefixes with "Stern_..." — and a font is often the
        # first named node in its radium, so a scene led by its font was
        # labeled after the font, and every hash-named member then matched a
        # search for the font's name through a label that isn't on screen
        # (a tester searched "stern" on Jaws: 758 such rows).  Every
        # extracted atlas has a glyphs/<atlas-stem>/ dir; those members
        # never supply the label hint.  The slicer's manifest names each
        # atlas too (second column), so a project whose glyphs folder was
        # pruned still knows its fonts.
        try:
            atlases = set(os.listdir(os.path.join(
                assets_path, "images", "scene_textures", "glyphs")))
            sliced = True
        except OSError:
            atlases, sliced = set(), False
        for cols in _rows("images", "scene_textures", "glyph_images.txt"):
            if len(cols) >= 2:
                atlases.add(os.path.splitext(os.path.basename(cols[1]))[0])
                sliced = True
        labels = {}
        for card, members in per_card.items():
            label = ""
            # An extract that predates the glyph slicer has NO record of
            # which members are fonts, so no member may supply a hint at
            # all: on such a project the atlas-skip above was a no-op and
            # "stern" still phantom-matched ~44% of a card's rows (a
            # tester's older Led Zeppelin extract).  Hash-only labels are
            # honest; re-extracting brings the names back.
            if sliced:
                for _off, mrel in sorted(members):
                    base = os.path.basename(mrel)
                    if os.path.splitext(base)[0] in atlases:
                        continue
                    m = name_re.match(base)
                    if m:
                        label = m.group(1)
                        break
            id8 = os.path.basename(os.path.dirname(card))[:8] or card
            labels[card] = ("%s · %s" % (label, id8)) if label else id8
        for rel, (card, off) in primary.items():
            groups[rel] = ("rad::" + card, labels[card], off)
        # Every container each image appears in, home group first (so a search
        # that matches nothing in particular still lands on the home group).
        for card, members in per_card.items():
            for off, mrel in members:
                entry = ("rad::" + card, labels[card], off)
                lst = where.setdefault(mrel, [])
                if entry not in lst:
                    lst.append(entry)
        for rel, lst in where.items():
            home = groups.get(rel)
            if home in lst:
                lst.remove(home)
                lst.insert(0, home)

        # scene.assets textures (output, card path, bytes, w, h, fmt): group =
        # the scene directory; manifest order stands in for play order.
        for idx, cols in enumerate(
                _rows("images", "scene_textures", "manifest.txt")):
            if len(cols) < 2:
                continue
            card = cols[1]
            if "/scene.assets/" in card:
                scene = card.rsplit("/scene.assets/", 1)[0]
            else:
                scene = card.rsplit("/", 1)[0] or card
            label = scene.rstrip("/").rsplit("/", 1)[-1][:8] or scene
            groups.setdefault("images/" + cols[0],
                              ("scn::" + scene, label, idx))

        # Loose images (output, card path, bytes): group = the card directory
        # (mirrors the rel-path parent, but named as the card names it).
        for idx, cols in enumerate(_rows("images", "manifest.txt")):
            if len(cols) < 2:
                continue
            card_dir = cols[1].rsplit("/", 1)[0] if "/" in cols[1] else ""
            folder = card_dir or "(root)"
            # Display without the manifest's leading "/" (a tester: the other
            # tabs show no leading slash) — the group KEY keeps the slash so
            # names saved under the old key still match.
            label = folder.lstrip("/") or "(root)"
            groups.setdefault("images/" + cols[0],
                              ("dir::" + folder, label, idx))

        return groups, occ, where

    def _image_group_of(self, rel):
        """``(group_key, label_base, order)`` for slot *rel*: the
        manifest-derived container from the last scan, or the parent-folder
        fallback for slots no manifest covers (every non-Stern plugin)."""
        g = self._image_groups.get(rel)
        if g is not None:
            return g
        folder = os.path.dirname(rel).replace("\\", "/") or "(root)"
        return ("dir::" + folder, folder, 0)

    def _image_groups_of(self, rel):
        """Every container *rel* occurs in, home group first — one entry for
        anything but a shared radium image."""
        return self._image_groups_all.get(rel) or [self._image_group_of(rel)]

    @staticmethod
    def _compute_image_key_tails(groups, groups_all):
        """``{group_key(lower): distinguishing tail}`` — each key minus the
        card-path prefix its whole namespace shares.

        The search matches container card paths so a scene hash from a file
        listing finds its images (a tester) — but on a real card every radium
        container lives under the same mount root, and a word sitting in that
        SHARED prefix matches every group at once while naming none of them.
        Batch 25: a tester searched "stern" for the Stern loading screen and
        got ~5000 radimg rows, matched through invisible on-card paths.  Only
        the part that differs between sibling keys carries any information,
        so that's all the search reads.  Prefixes are cut at a "/" so a
        partial path component is never split; namespaces (``rad::`` /
        ``scn::`` / ``dir::``) are handled separately since their prefixes
        differ."""
        keys = {g[0] for g in groups.values()}
        for lst in groups_all.values():
            keys.update(g[0] for g in lst)
        by_ns = {}
        for k in keys:
            by_ns.setdefault(k.split("::", 1)[0], []).append(k.lower())
        tails = {}
        for ns, ks in by_ns.items():
            if len(ks) < 2:
                # A lone container has no siblings to differ from — keep its
                # whole path (minus the namespace tag) searchable.
                for k in ks:
                    tails[k] = k.split("::", 1)[-1]
                continue
            prefix = os.path.commonprefix(ks)
            cut = prefix.rfind("/") + 1
            for k in ks:
                tails[k] = k[cut:]
        return tails

    @staticmethod
    def _image_search_hits_path(rel_path, query):
        """Whether a search *query* may match through *rel_path* itself.

        A glyph slice lives at ``glyphs/<atlas-stem>/U+0041_A.png`` — its
        parent folder IS the font atlas's filename, and Stern prefixes
        font names with "Stern_...".  So on a fresh (sliced) extract a
        search for "stern" matched every letter tile through a folder name
        that is the font's name, not the tile's: 3652 of 3710 hits on a
        real Jaws extract (a tester's re-test after the pre-slicer fix).
        A glyph matches on its own filename only; a query with a path
        separator is a deliberate path search and still matches the whole
        path — same contract as _image_group_matches."""
        rel = rel_path.replace("\\", "/").lower()
        if "/" in query or "\\" in query:
            return query.replace("\\", "/") in rel
        if "glyphs" in rel.split("/"):
            return query in os.path.basename(rel)
        return query in rel

    @staticmethod
    def _image_slot_search_hit(rel_path, query, group_hit):
        """The full slot-level search decision: the path rule first, then
        the container match — except glyph rows, whose fallback container
        is the very glyphs/<atlas-stem>/ folder the path rule just vetoed,
        so they get no second chance through it.  *group_hit* is a
        zero-arg callable so the (dearer) container walk only runs when
        the path said no."""
        if MainWindow._image_search_hits_path(rel_path, query):
            return True
        if "glyphs" in rel_path.replace("\\", "/").lower().split("/"):
            return False
        return group_hit()

    def _image_group_matches(self, group, query):
        """True when *query* hits this container's display label, its user
        rename, or the distinguishing part of its card path (so a scene hash
        from a file listing works, not just the 8-char shorthand — while a
        word in the mount prefix every container shares matches nothing; see
        _compute_image_key_tails).  A query with a path separator is a
        deliberate full-path search and still matches the whole key."""
        key, label, _order = group
        if (query in label.lower()
                or query in self._image_group_tags.get(key, "").lower()):
            return True
        k = key.lower()
        if "/" in query or "\\" in query:
            return query.replace("\\", "/") in k
        return query in self._image_group_key_tails.get(k, k)

    def _refresh_image_list(self):
        """Apply the search filter + sort and repopulate the slot tree — flat
        (exactly the audio/video tabs' behaviour), or two-level when "Group by
        scene" is on: one collapsed parent per scene/animation container, its
        images nested beneath in play order."""
        tree = getattr(self, "_image_tree", None)
        if tree is None:
            return
        # Keep the groups the user expanded open across a rebuild (assigning,
        # filtering and sorting all funnel through here).
        open_groups = set()
        for iid in tree.get_children():
            if iid.startswith(_IMG_GROUP_IID):
                try:
                    if tree.item(iid, "open") in (1, True, "true"):
                        open_groups.add(iid)
                except tk.TclError:
                    pass
        tree.delete(*tree.get_children())

        query = (self.image_search_var.get() or "").strip().lower()
        grouped = bool(self.image_group_by_scene_var.get())
        # The per-group "Images" count column only exists in grouped mode
        # (a tester: a sortable count column beats a count baked into the
        # header text); flat mode hides it rather than show an empty column.
        tree["displaycolumns"] = (("n", "res", "fmt", "src", "rep") if grouped
                                  else ("res", "fmt", "src", "rep"))
        changed = self._image_changed_on_disk
        touched = set(self._image_assignments) | changed

        slots = self._image_slots
        change_ok = self._change_filter_pred("image")
        if change_ok is not None:
            slots = [s for s in slots if change_ok(s.rel_path)]
        srcf = self.image_source_filter_var.get()
        if srcf and srcf != "All sources":
            slots = [s for s in slots
                     if self._image_source_label(s.rel_path) == srcf]
        # The search matches a container too — the manifest name, the user's
        # rename (see _image_group_rename) and the card path — so
        # "Char_Select", a custom tag, or a scene id/hash finds a whole
        # animation whose member files are just hashes.  It matches ANY scene
        # an image appears in, not only its home group: a shared image belongs
        # to one group but lives in many scenes, and searching for one of the
        # others used to come up empty (a tester).
        def _matched_group(s):
            for g in self._image_groups_of(s.rel_path):
                if self._image_group_matches(g, query):
                    return g
            return None

        def _match(s):
            return self._image_slot_search_hit(
                s.rel_path, query, lambda: _matched_group(s) is not None)
        if query:
            slots = [s for s in slots if _match(s)]
        col, desc = self._image_sort

        def _key(s):
            if col == "res":
                wh = (s.info.width * s.info.height) if s.info else -1
                return (wh,)
            if col == "fmt":
                return (s.format_summary().lower(), s.rel_path.lower())
            if col == "src":
                return (self._image_source_label(s.rel_path),
                        s.rel_path.lower())
            if col == "rep":
                rep = self._image_assignments.get(s.rel_path)
                if rep:
                    return (0, os.path.basename(rep).lower())
                return (1, "") if s.rel_path in changed else (2, "")
            return (s.rel_path.lower(),)  # "#0" name/path

        self._show_sort_arrows(tree, self._image_sort_cfg, self._image_sort)

        def _insert(parent, s):
            rep = self._image_assignments.get(s.rel_path)
            is_changed = s.rel_path in changed
            if rep:
                rep_disp = os.path.basename(rep)
                tag = "changed" if is_changed else "assigned"
            elif is_changed:
                rep_disp, tag = "✓ changed on disk", "changed"
            else:
                rep_disp, tag = "Choose…", ""
            if s.info is None and not s.probed:
                res = "…"  # metadata still loading
            else:
                res = s.resolution_str()
            # In grouped mode the parent row already names the folder, so show
            # just the filename (a tester); flat mode keeps the full path.
            disp = os.path.basename(s.rel_path) if parent else s.rel_path
            tree.insert(parent, tk.END, iid=s.rel_path, text=disp,
                        values=("", res, s.format_summary(),
                                self._image_source_label(s.rel_path),
                                rep_disp),
                        tags=(tag,) if tag else ())

        if grouped:
            # A search for a scene shows its images UNDER THAT SCENE, even
            # when their home group is another one — otherwise the hits
            # scatter across the groups that happen to own them and the scene
            # you asked for isn't on screen at all.
            disp = {}                      # rel_path -> displayed container
            for s in slots:
                g = _matched_group(s) if query else None
                disp[s.rel_path] = g or self._image_group_of(s.rel_path)
            by_grp = {}                    # key -> (label_base, [slots])
            for s in slots:
                key, label, _order = disp[s.rel_path]
                by_grp.setdefault(key, (label, []))[1].append(s)
            # Groups stay label-sorted; a header click re-sorts the children
            # WITHIN each group — except "Images", which sorts the GROUPS by
            # member count (the column belongs to the group rows).  The
            # default "#0" sort means play order here (the manifests' frame
            # sequence), not the flat path sort.  A user rename
            # (_image_group_rename) replaces the display label AND the sort
            # key, so renamed groups land where you'd look.
            def _disp(k):
                return self._image_group_tags.get(k) or by_grp[k][0]
            if col == "n":
                group_order = sorted(
                    by_grp, key=lambda k: (len(by_grp[k][1]),
                                           _disp(k).lower(), k),
                    reverse=desc)
            else:
                group_order = sorted(by_grp,
                                     key=lambda k: (_disp(k).lower(), k))
            for key in group_order:
                members = by_grp[key][1]
                label = _disp(key)
                if col in ("#0", "n"):
                    members.sort(
                        key=lambda s: (disp[s.rel_path][2],
                                       s.rel_path.lower()),
                        reverse=desc if col == "#0" else False)
                else:
                    members.sort(key=_key, reverse=desc)
                giid = _IMG_GROUP_IID + key
                n = len(members)
                tree.insert(
                    "", tk.END, iid=giid, open=(giid in open_groups),
                    text=label,
                    values=("%d image%s" % (n, "" if n == 1 else "s"),))
                for s in members:
                    _insert(giid, s)
        else:
            slots.sort(key=_key, reverse=desc)
            for s in slots:
                _insert("", s)

        total = len(self._image_slots)
        changed_total = len(set(self._image_assignments) | changed)
        if total == 0:
            self.image_status_var.set("")
            self._image_empty.configure(
                text="No replaceable image found in this folder.")
            self._image_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            shown = len(slots)
            extra = f"  ({shown} shown)" if shown != total else ""
            self.image_status_var.set(
                f"{total} images, {changed_total} changed{extra}")
            self._image_empty.place_forget()
        self._autosize_tree_columns(
            tree, "image", ("#0", "res", "fmt", "src", "rep"))

    def _maybe_rescan_image(self):
        """Auto-scan when the Replace Image tab becomes visible and the folder
        has changed since the last scan."""
        if self._current_mfr is None:
            return
        if not getattr(self._current_mfr.capabilities, "replace_image", False):
            return
        assets_path = (self.write_assets_var.get() or "").strip()
        if assets_path and assets_path != self._image_scan_dir:
            self._scan_image_slots_async()

    # ---- Replace Image: per-slot actions -----------------------------

    def _image_selected_rel(self):
        # NB: in grouped mode this can be a group header's iid
        # (``_IMG_GROUP_IID`` prefix), not a slot rel_path.
        sel = self._image_tree.selection() if hasattr(self, "_image_tree") else ()
        return sel[0] if sel else None

    def _image_assign_rel(self, rel):
        """Open the replacement picker for *rel* and record the assignment."""
        if not rel or rel not in self._image_slots_by_rel:
            return
        from ..core.image import REPLACEMENT_EXTS
        spec = " ".join(f"*{e}" for e in REPLACEMENT_EXTS)
        path = filedialog.askopenfilename(
            title=f"Choose a replacement for {rel}",
            initialdir=self.last_browse_dir("image_replacement"),
            filetypes=[("Image files", spec), ("All files", "*.*")])
        if not path:
            return
        self.remember_browse_dir("image_replacement", path)
        self._image_assignments[rel] = path
        self._save_staged_changes()
        self.append_log("Replace Images: %s ← %s"
                        % (rel, os.path.basename(path)), "info")
        self._refresh_image_list()
        if rel == self._image_current_rel:
            self._image_render_preview(rel)
        try:
            self._image_tree.selection_set(rel)
            self._image_tree.see(rel)
        except tk.TclError:
            pass

    # ---- Replace Image: table interactions ---------------------------

    def _image_on_tree_select(self, _event=None):
        rel = self._image_selected_rel()
        if rel is None:
            return
        if rel.startswith(_IMG_GROUP_IID):
            # A group header: preview its first shown child's original so the
            # click isn't a dead end; no single replacement applies, so the
            # replacement pane clears.
            kids = self._image_tree.get_children(rel)
            slot = self._image_slots_by_rel.get(kids[0]) if kids else None
            self._image_current_rel = None
            self._image_set_orig_header("Original")
            self._image_render_thumb(
                getattr(self, "_image_canvas", None),
                slot.abs_path if slot else None, "_image_preview_img_orig")
            self._image_render_thumb(
                getattr(self, "_image_canvas_rep", None), None,
                "_image_preview_img_rep")
            return
        if rel == self._image_current_rel:
            return
        self._image_current_rel = rel
        self._image_render_preview(rel)

    def _image_on_tree_double(self, _event=None):
        if not self._double_click_on_rows(self._image_tree, _event):
            return
        rel = self._image_selected_rel()
        if rel is not None and rel.startswith(_IMG_GROUP_IID):
            return          # double-click toggles the group (Tk's default)
        if rel is None:
            messagebox.showinfo("No Slot Selected",
                                "Select an image to assign.")
            return
        self._image_assign_rel(rel)

    def _image_on_tree_click(self, event):
        tree = self._image_tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        row = tree.identify_row(event.y)
        col = tree.identify_column(event.x)  # cols=(res,fmt,src,rep) -> #1..#4
        if row and col == "#4" and not row.startswith(_IMG_GROUP_IID):
            tree.selection_set(row)
            self._image_assign_rel(row)

    def _image_on_tree_right(self, event):
        tree = self._image_tree
        row = tree.identify_row(event.y)
        if not row:
            return
        tree.selection_set(row)
        menu = tk.Menu(tree, tearoff=0)
        c = THEMES.get(self._current_theme, {})
        try:
            menu.configure(
                background=c.get("field_bg"), foreground=c.get("fg"),
                activebackground=c.get("select_bg"),
                activeforeground="#ffffff")
        except tk.TclError:
            pass
        if row.startswith(_IMG_GROUP_IID):
            # Group header: bulk actions over the children currently shown
            # (the search / Show filters have already been applied).
            kids = tuple(tree.get_children(row))
            n = len(kids)
            plural = "" if n == 1 else "s"
            menu.add_command(
                label="Assign replacement to all %d image%s…" % (n, plural),
                command=lambda g=row, k=kids: self._image_group_assign(g, k))
            menu.add_command(
                label="Blank all %d image%s (transparent)…" % (n, plural),
                command=lambda g=row, k=kids: self._image_group_blank(g, k))
            if any(k in self._image_assignments for k in kids):
                menu.add_separator()
                menu.add_command(
                    label="Clear replacements in group",
                    command=lambda g=row, k=kids:
                        self._image_group_apply(g, k, None))
            menu.add_separator()
            menu.add_command(
                label="Rename group…",
                command=lambda g=row: self._image_group_rename(g))
        else:
            menu.add_command(label="Choose replacement…",
                             command=lambda r=row: self._image_assign_rel(r))
            if self._image_assignments.get(row):
                menu.add_separator()
                menu.add_command(label="Clear replacement",
                                 command=self._image_clear_selected)
            src = self._image_source_label(row)
            if src in ("Glyph", "Radium", "Scene texture"):
                menu.add_separator()
                if src == "Glyph":
                    menu.add_command(
                        label="Open in Fonts window…",
                        command=lambda r=row: self._open_font_studio(
                            preselect_rel=r))
                menu.add_command(
                    label="Show scene contents…",
                    command=lambda r=row: self._open_scene_browser(
                        preselect_rel=r))
            slot = self._image_slots_by_rel.get(row)
            if slot is not None:
                menu.add_separator()
                menu.add_command(
                    label=self._reveal_menu_label(),
                    command=lambda p=slot.abs_path:
                        self._reveal_in_file_manager(p))
                self._add_find_in_partition_item(menu, "image", row)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ---- Fonts / Scenes tool windows (a tester) --------------------------

    def _image_assets_dir_or_warn(self, noun):
        """The Images-tab assets folder, or None with a friendly nudge."""
        assets = (self.write_assets_var.get() or "").strip()
        if not assets or not os.path.isdir(assets):
            messagebox.showinfo(
                noun, "Pick your extracted project folder first (Extract "
                      "tab) — the %s window works on an extracted Stern "
                      "Spike 2 card." % noun)
            return None
        return assets

    def _open_font_studio(self, preselect_rel=None):
        """Open the Fonts window, optionally preselecting the font that owns
        the glyph slice at Images-tab row *preselect_rel*."""
        assets = self._image_assets_dir_or_warn("Fonts")
        if assets is None:
            return
        preselect = None
        if preselect_rel:
            rel = preselect_rel.replace("\\", "/")
            if rel.startswith("images/"):
                rel = rel[len("images/"):]
            from ..plugins.stern import fontrender
            try:
                for fo in fontrender.load_fonts(assets):
                    if any(g["rel"] == rel for g in fo["glyphs"].values()):
                        preselect = fo["key"]
                        break
            except Exception:
                pass
        from .font_studio import open_font_studio
        open_font_studio(self, assets, preselect=preselect)

    def _open_scene_browser(self, preselect_rel=None, preselect_video=None,
                            preselect_dir=None, focus_text=None):
        """Open the Scenes window, optionally on the scene that holds the
        image at Images-tab row *preselect_rel*, the clip at Video-tab row
        *preselect_video*, or the scene directory *preselect_dir* outright —
        with *focus_text* selected in its contents list."""
        assets = self._image_assets_dir_or_warn("Scenes")
        if assets is None:
            return
        from .scene_browser import collect_scenes, open_scene_browser
        preselect = preselect_dir
        if preselect is None and (preselect_rel or preselect_video):
            rel = (preselect_rel or preselect_video).replace("\\", "/")
            if preselect_rel and "/glyphs/" in rel:
                rel = self._glyph_atlas_rel(assets, rel) or rel
            try:
                for d, sc in collect_scenes(assets).items():
                    if preselect_video:
                        hit = rel in sc["videos"]
                    else:
                        hit = any(r == rel for _o, r in sc["images"])
                    if hit:
                        preselect = d
                        break
            except Exception:
                pass
        open_scene_browser(self, assets, preselect=preselect,
                           focus_text=focus_text)

    @staticmethod
    def _glyph_atlas_rel(assets, rel):
        """A glyph slice's atlas PNG rel (``images/…``) via the glyph
        manifest — scene lookups group by atlas, not slice."""
        want = rel[len("images/"):] if rel.startswith("images/") else rel
        try:
            with open(os.path.join(assets, "images", "scene_textures",
                                   "glyph_images.txt"),
                      encoding="utf-8") as f:
                for line in f:
                    cols = line.rstrip("\r\n").split("\t")
                    if len(cols) >= 2 and cols[0] == want:
                        return "images/" + cols[1]
        except OSError:
            pass
        return None

    def _tool_windows(self):
        """The Fonts / Scenes tool windows that are open right now."""
        out = []
        for attr in ("_scene_browser", "_font_studio"):
            w = getattr(self, attr, None)
            try:
                if w is not None and w.win.winfo_exists():
                    out.append(w.win)
            except (AttributeError, tk.TclError):
                pass
        return out

    def _step_aside_for_jump(self):
        """Move any open tool window out from in front of the main window.

        A tester: "when you have the font / scene folder open and jump to it with
        a double click, it will visit the page in the background, it was hard
        for me to find out that it did jump there."  The Fonts and Scenes
        windows are ``transient`` children of the main window, and Windows
        keeps an owned window above its owner — so raising the main window
        cannot uncover the tab the jump landed on.  Lowering the tool window
        below the root does work, and survives the user clicking the main
        window afterwards.

        TWO STEPS, IN THIS ORDER (measured — the z-order probes in this
        session's scratchpad):

        1. ``focus_force()`` the main window.  A double-click arrives while
           the TOOL window is the active one, and Windows will not push the
           foreground window below its own owner — lowering it alone is
           silently ignored, which is exactly what a tester saw.
        2. only then lower each tool window below the root.

        Do NOT ``lift()`` the root instead: that re-applies the owner rule and
        drags the tool window straight back on top.  Nothing is closed or
        reset either — the Fonts… / Scenes… buttons (and Show in Scenes… on
        the Replace Text tab) lift the window back exactly as it was."""
        try:
            root = self._tk_root()
            root.focus_force()
        except (AttributeError, tk.TclError):
            return
        for win in self._tool_windows():
            try:
                win.lower(root)
            except tk.TclError:
                pass

    @staticmethod
    def _land_on_row(tree, iid):
        """Select *iid*, scroll it into view and give the tree keyboard focus,
        so a cross-window jump ends somewhere visibly selected."""
        try:
            tree.selection_set(iid)
            tree.see(iid)
            tree.focus(iid)
            tree.focus_set()
        except tk.TclError:
            pass

    def reveal_image_slot(self, rel):
        """Scene Browser: show one image slot on the Images tab (clearing
        any filters that would hide it)."""
        self._step_aside_for_jump()
        self._notebook.select(self._tab_image)
        tree = getattr(self, "_image_tree", None)
        if tree is None:
            return
        if not tree.exists(rel):
            self.image_search_var.set("")
            self.image_source_filter_var.set("All sources")
            self.image_change_filter_var.set("All")
            self._refresh_image_list()
        if tree.exists(rel):
            self._land_on_row(tree, rel)
            self._image_on_tree_select()

    def reveal_video_slot(self, rel):
        """Scene Browser: show one video slot on the Video tab (clearing any
        filter that would hide it)."""
        self._step_aside_for_jump()
        self._notebook.select(self._tab_video)
        tree = getattr(self, "_video_tree", None)
        if tree is None:
            return
        if not tree.exists(rel):
            self.video_search_var.set("")
            self.video_change_filter_var.set("All")
            self._refresh_video_list()
        if tree.exists(rel):
            self._land_on_row(tree, rel)

    def reveal_text_string(self, text):
        """Scene Browser: find one display string on the Replace Text tab
        (clearing any filter that would hide it)."""
        self._step_aside_for_jump()
        self._notebook.select(self._tab_text)
        tree = getattr(self, "_text_tree", None)
        if tree is not None and not tree.get_children():
            try:
                self._scan_text_strings()
            except Exception:
                pass
        self.text_change_filter_var.set("All")
        self.text_scene_filter_var.set(self._TEXT_SCENE_ALL)
        self.text_search_var.set(text)
        # The search alone leaves nothing selected, which reads as "nothing
        # happened" — land on the row itself.
        if tree is not None:
            for i, r in enumerate(self._text_rows):
                if r["original"] == text and tree.exists(str(i)):
                    self._land_on_row(tree, str(i))
                    self._text_on_tree_select()
                    break

    # ---- Replace Image: group bulk actions ---------------------------

    def _image_group_rename(self, group_iid):
        """Right-click → Rename group…: give a scene/animation group a
        custom display name.  The vendor's own scene-element names are
        mostly generic ("unnamed_instance_14"), so there's nothing better
        to extract automatically (a tester).  Stored per assets folder in
        the staged-changes sidecar; a blank (or unchanged-generic) entry
        restores the manifest name.  The rename also becomes the group's
        sort key and a Search match."""
        key = group_iid[len(_IMG_GROUP_IID):]
        generic = next(
            (label for gkey, label, _o in self._image_groups.values()
             if gkey == key), "")
        if not generic and key.startswith("dir::"):
            generic = key[len("dir::"):]      # folder-fallback groups
        name = self._ask_text(
            "Rename Group",
            "Display name for this group\n"
            "(blank restores \"%s\"):" % (generic or "the original name"),
            initialvalue=self._image_group_tags.get(key, generic))
        if name is None:
            return                            # cancelled
        name = " ".join(name.split())[:50]
        if not name or name == generic:
            self._image_group_tags.pop(key, None)
        else:
            self._image_group_tags[key] = name
        self._save_staged_changes()
        self._refresh_image_list()
        try:
            self._image_tree.selection_set(group_iid)
            self._image_tree.see(group_iid)
        except tk.TclError:
            pass       # renamed group may have re-sorted out of view

    def _image_group_apply(self, group_iid, rels, rep_path):
        """Record *rep_path* as the replacement for every slot in *rels*
        (``None`` clears instead), then persist + refresh once and put the
        selection back on the group row.  Pure assignment plumbing — the
        actual pixel scaling/re-encode happens at Write, per slot, exactly
        like a single-row assignment."""
        changed_any = False
        for rel in rels:
            if rel not in self._image_slots_by_rel:
                continue
            if rep_path is None:
                changed_any |= (
                    self._image_assignments.pop(rel, None) is not None)
            else:
                self._image_assignments[rel] = rep_path
                changed_any = True
        if not changed_any:
            return
        self._save_staged_changes()
        self.append_log(
            "Replace Images: %s %d slot(s) in group"
            % ("cleared" if rep_path is None
               else "assigned %s to" % os.path.basename(rep_path),
               len(rels)), "info")
        self._refresh_image_list()
        if self._image_current_rel in set(rels):
            self._image_render_preview(self._image_current_rel)
        try:
            self._image_tree.selection_set(group_iid)
            self._image_tree.see(group_iid)
        except tk.TclError:
            pass    # the Show filter may have dropped the group

    def _image_group_assign(self, group_iid, rels):
        """Group menu: one picker, assigned to every shown slot in the group
        (each is still scaled/converted to its own slot format at Write)."""
        if not rels:
            return
        from ..core.image import REPLACEMENT_EXTS
        spec = " ".join(f"*{e}" for e in REPLACEMENT_EXTS)
        path = filedialog.askopenfilename(
            title="Choose a replacement for %d images" % len(rels),
            filetypes=[("Image files", spec), ("All files", "*.*")])
        if not path:
            return
        self._image_group_apply(group_iid, rels, path)

    def _image_group_blank(self, group_iid, rels):
        """Group menu: assign a fully-transparent image to every shown slot so
        the whole scene/animation renders as nothing in-game."""
        if not rels:
            return
        n = len(rels)
        if not messagebox.askyesno(
                "Blank Images",
                "Assign a transparent image to all %d image%s in this "
                "group?\n\nThey'll render as fully transparent once you "
                "build the update on the Write tab (and can be cleared "
                "again from this menu until then)."
                % (n, "" if n == 1 else "s")):
            return
        blank = self._ensure_blank_image()
        if not blank:
            messagebox.showerror(
                "Blank Images",
                "Couldn't create the transparent placeholder image in the "
                "assets folder — check the folder is writable.")
            return
        self._image_group_apply(group_iid, rels, blank)

    def _ensure_blank_image(self):
        """Path to a fully-transparent 16×16 RGBA PNG inside the scanned
        assets folder (created on first use), or ``""`` on failure.  It lives
        IN the assets folder so the sidecar's assignments travel with the
        extract; the dot name keeps it out of slot scans and checksum diffs
        (same rule as .staged_changes.json)."""
        assets = self._image_scan_dir or (
            self.write_assets_var.get() or "").strip()
        if not assets or not os.path.isdir(assets):
            return ""
        path = os.path.join(assets, ".blank.png")
        if os.path.isfile(path):
            return path
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(_BLANK_PNG_B64))
        except OSError:
            return ""
        return path

    def _image_clear_selected(self):
        rel = self._image_selected_rel()
        if rel is not None and rel in self._image_assignments:
            del self._image_assignments[rel]
            self._save_staged_changes()
            self.append_log("Replace Images: cleared replacement for %s" % rel,
                            "info")
            self._refresh_image_list()
            if rel == self._image_current_rel:
                self._image_render_preview(rel)
            try:
                self._image_tree.selection_set(rel)
            except tk.TclError:
                pass

    # ---- Replace Image: static preview -------------------------------

    def _image_render_thumb(self, canvas, path, ref_attr, empty_text=""):
        """Draw *path*'s thumbnail centered on *canvas*, keeping the Tk image
        alive on ``self.<ref_attr>``.  A missing/unreadable *path* (or missing
        Pillow) clears the canvas, showing *empty_text* instead."""
        if canvas is None:
            return
        canvas.delete("all")
        setattr(self, ref_attr, None)
        from ..core.image import thumbnail_png
        try:
            w = int(canvas.cget("width"))
            h = int(canvas.cget("height"))
        except (tk.TclError, ValueError):
            w, h = 320, 214
        png = thumbnail_png(path, w - 8, h - 8) if path else None
        if not png:
            if empty_text:
                canvas.create_text(w // 2, h // 2, text=empty_text,
                                   fill="#888888", font=(_SANS_FONT, 9),
                                   width=w - 24, justify=tk.CENTER)
            return
        try:
            img = tk.PhotoImage(data=base64.b64encode(png))
            setattr(self, ref_attr, img)
            canvas.create_image(w // 2, h // 2, anchor=tk.CENTER, image=img)
        except tk.TclError:
            setattr(self, ref_attr, None)

    def _image_render_preview(self, rel):
        """Render *rel*'s original and assigned replacement side-by-side on
        the two preview canvases.  Tolerates a missing Pillow / unreadable
        image by clearing the affected canvas.

        A slot already changed on disk (imported mod pack, earlier build)
        holds the REPLACEMENT bytes: prefer its ``.orig`` snapshot as the true
        original and show the on-disk file on the replacement side — and when
        no snapshot exists, retitle the left pane instead of calling modified
        bytes "Original" (a tester read his imported logo as a lost mod)."""
        from ..core import staged_originals
        slot = self._image_slots_by_rel.get(rel) if rel is not None else None
        rep = self._image_assignments.get(rel) if rel is not None else None
        opath = slot.abs_path if slot else None
        changed = (self._slot_changed_on_disk("image", rel)
                   if rel is not None else False)
        snap = None
        if changed:
            snap = staged_originals.snapshot_path(self._image_scan_dir, rel)
            if snap:
                opath = snap
        # Identical copies across scenes extract to ONE PNG, so a replacement
        # lands in every scene that carries it — say so where the user is
        # about to replace it, not only in the Scenes window (a tester read the
        # dedup as the app mixing unrelated scenes together).
        hdr = ("Current file (already modified)" if changed and not snap
               else "Original")
        n_occ = self._image_group_occ.get(rel, 0) if rel is not None else 0
        if n_occ > 1:
            hdr += ("  ·  shared by %d scenes (replacing it changes all of "
                    "them)" % n_occ)
        self._image_set_orig_header(hdr)
        if rep is None and changed and snap and slot:
            rep = slot.abs_path
        self._image_render_thumb(
            getattr(self, "_image_canvas", None), opath,
            "_image_preview_img_orig")
        self._image_render_thumb(
            getattr(self, "_image_canvas_rep", None), rep,
            "_image_preview_img_rep",
            empty_text=("(no replacement assigned — double-click the row "
                        "to pick one)" if slot else ""))

    def _image_set_orig_header(self, text):
        hdr = getattr(self, "_image_hdr_orig", None)
        if hdr is not None:
            try:
                hdr.configure(text=text)
            except tk.TclError:
                pass

    def _image_clear_preview(self):
        """Reset the static previews entirely (used on manufacturer switch)."""
        self._image_current_rel = None
        self._image_set_orig_header("Original")
        self._image_preview_img_orig = None
        self._image_preview_img_rep = None
        for attr in ("_image_canvas", "_image_canvas_rep"):
            canvas = getattr(self, attr, None)
            if canvas is not None:
                canvas.delete("all")

    # ---- Replace Image: pending assignments (applied at Write time) --

    def pending_image_assignments(self, assets_dir):
        """Return ``(slots_by_rel, assignments)`` of replacements the user
        assigned for *assets_dir*, or ``None`` when there's nothing to apply.
        Called by the Write flow to auto-stage edits just before it repacks.

        Guarded so it only fires when the folder being written is the same one
        the assignments were made against."""
        mfr = self._current_mfr
        if mfr is None or not getattr(
                mfr.capabilities, "replace_image", False):
            return None
        if not assets_dir:
            return None
        scanned = self._image_scan_dir or ""
        if (os.path.normcase(os.path.normpath(assets_dir))
                != os.path.normcase(os.path.normpath(scanned))):
            return None
        assignments = {rel: rep for rel, rep in self._image_assignments.items()
                       if rep and rel in self._image_slots_by_rel}
        if not assignments:
            return None
        return (dict(self._image_slots_by_rel), assignments)

    # ---- Staged-changes persistence (survives quit / relaunch) -------
    # The Replace tabs keep each assignment in memory and apply it at Write;
    # this mirrors the whole set into a .staged_changes.json sidecar in the
    # assets folder so closing the app no longer loses pending edits.  See
    # core.staged_changes.

    def _load_staged_changes(self, assets_dir):
        """Read the staged-changes sidecar for *assets_dir* (``{}`` if none)."""
        from ..core import staged_changes
        return staged_changes.load(assets_dir)

    def _warn_dropped_assignments(self, kind, saved, slots_by_rel, scan_dir):
        """Log the sidecar assignments a restore had to drop (slot gone, or
        replacement source file unreachable), so a disconnected NAS drive or a
        re-extract that renamed slots doesn't silently read as "nothing
        assigned" (a tester).  The sidecar keeps the entries until the user
        changes an assignment, so fixing the cause and re-scanning restores
        them.

        A slot that was already changed on disk (it has a .orig snapshot) gets
        a calm info line instead of red: the replacement IS in the project
        folder — losing track of the source file it was made from only matters
        for a re-apply (batch 24: a tester read the red line as a clip that
        "cannot be loaded from my NAS", while it played fine, because the
        change itself was long since applied)."""
        from ..core import staged_changes, staged_originals
        dropped = staged_changes.dropped_assignments(saved, slots_by_rel)
        if not dropped:
            return
        any_pending = False
        for rel, path, why in dropped[:6]:
            # Same name with another extension sitting right there = the clip
            # was re-exported in a new container; say so under the path, or
            # the note reads as a false alarm (batch 25).
            alt = staged_changes.same_stem_sibling(path)
            hint = ('\n        (a file named "%s" IS in that folder — same '
                    "name, different extension. If that's this clip "
                    "re-exported, re-pick it.)" % alt) if alt else ""
            if staged_originals.snapshot_path(scan_dir, rel):
                self.append_log(
                    'Note: "%s" already holds its %s replacement (changed on '
                    'disk) — nothing is lost.  But the source file it was '
                    'made from wasn\'t found (%s), so it can\'t be '
                    're-applied until it\'s re-picked:\n        %s%s'
                    % (rel, kind, why, path, hint), "info")
            else:
                any_pending = True
                self.append_log(
                    'Saved %s replacement for "%s" wasn\'t restored — %s:\n'
                    '        %s%s' % (kind, rel, why, path, hint), "error")
        if len(dropped) > 6:
            self.append_log("…and %d more saved %s replacement(s) like this."
                            % (len(dropped) - 6, kind),
                            "error" if any_pending else "info")

    def _seed_group_tags_from_library(self, scan_dir):
        """Fill in group names the user gave a PREVIOUS extract of this same
        card (the per-folder sidecar is blank on a fresh extract).

        The library is scoped by the source card's file name (game + version),
        so only same-version re-extracts are seeded — cross-version carry-over
        stays Mod Transfer's job.  The folder's own sidecar always wins; the
        library only fills groups that have no name yet.  Seeded names are
        written straight back into this folder's sidecar so they also ride a
        later Mod Transfer / reopen, not just this session.  Best-effort."""
        try:
            from ..core import staged_changes, tag_library
            present = {self._image_group_of(s.rel_path)[0]
                       for s in self._image_slots}
            seeded = tag_library.seed_tags(scan_dir, present)
            added = False
            for key, name in seeded.items():
                if key not in self._image_group_tags:
                    self._image_group_tags[key] = name
                    added = True
            if added:
                data = staged_changes.load(scan_dir)
                data["image_group_tags"] = {
                    k: v for k, v in self._image_group_tags.items() if v}
                staged_changes.save(scan_dir, data)
        except Exception:
            pass

    def _audio_trim_forced(self):
        """True when the Trim/pad checkbox is force-disabled for this plugin
        (size-neutral formats like Spike 2) — so a restore must not flip it."""
        cb = getattr(self, "_audio_trim_cb", None)
        try:
            return cb is not None and str(cb.cget("state")) == "disabled"
        except tk.TclError:
            return False

    def _apply_audio_trim_lock(self, mfr, assets_dir=None,
                               persisted_trim=None):
        """Force Trim/pad on — and HIDE its checkbox — when this plugin's
        Write always length-matches, else show it as a free toggle.

        Batch 20 (a tester): for formats where length-matching is structural
        (Spike 2's size-neutral slots, JJP, CGC's Pulp Fiction banks) it's
        standard behavior, not a choice — a forced-on disabled checkbox still
        read as a setting to worry about, so it's not shown at all.  The
        checkbox stays (`state` NORMAL) only where a longer replacement is
        genuinely valid (loose-WAV formats).

        Re-callable: the manufacturer-select path passes no *assets_dir* (the
        plugin's default), and an audio scan passes the scanned folder so a
        plugin whose answer is per-extract (CGC: Pulp Fiction's fixed-length
        bank slots vs the WPC remakes' loose WAVs) can lock only when it
        applies.  *persisted_trim* is the checkbox value to restore when the
        lock is NOT in effect (from the folder's saved state, or the current
        value on a same-folder re-scan); None means default off.
        """
        if not hasattr(self, "_audio_trim_cb") or mfr is None:
            return False
        try:
            forces = mfr.audio_forces_length_match(assets_dir)
        except TypeError:
            # A plugin still on the old no-arg signature.
            forces = mfr.audio_forces_length_match()
        if forces:
            self.audio_trim_var.set(True)
        else:
            self.audio_trim_var.set(bool(persisted_trim))
        # The disabled state stays the source of truth for
        # _audio_trim_forced() even while the widget is unmapped.
        self._audio_trim_cb.configure(
            state=(tk.DISABLED if forces else tk.NORMAL))
        if forces:
            self._audio_trim_cb.pack_forget()
        elif not self._audio_trim_cb.winfo_manager():
            # winfo_manager, not winfo_ismapped: "packed" survives the tab
            # being hidden, so an already-packed box isn't re-packed.
            self._audio_trim_cb.pack(side=tk.LEFT)
        if hasattr(self, "_audio_trim_tip"):
            note = (mfr.audio_length_note() or "").strip()
            # Tooltip only matters when the checkbox is visible (free toggle).
            self._audio_trim_tip.text = (
                "When on, a replacement longer or shorter than the "
                "original is trimmed or padded to the original slot "
                "length before Write. When off, the replacement is used "
                "as-is." + (("\n\n" + note) if note else ""))
        return forces

    # Keep in step with App._AUDIO_ADV_DEFAULTS.
    _AUDIO_ADV_DEFAULTS = {
        "head_mode": "encode", "leadout": "silence", "previews": False,
        "experiment_idxs": "", "slot_seed": False, "slot_seed_db": 65,
        "blip_free_optin": False,
    }
    _AUDIO_HEAD_CHOICES = (
        ("encode", "Re-encode from the first sample (default)"),
        ("stock", "Keep the stock head block (experimental, first 4.5 ms)"),
    )
    _AUDIO_LEADOUT_CHOICES = (
        ("silence", "Encode the tail block to silence (default)"),
        ("stock", "Keep the stock tail scrap (pre-v0.71.1 behavior)"),
    )

    # Description labels wrap at the dialog's natural width (set by the
    # head/tail rows) instead of a narrower column, so no dead space is left
    # to their right (feedback batch 20 item 4).
    _AUDIO_ADV_WRAP = 640

    def _open_audio_advanced(self):
        """Advanced audio options: per-knob encode overrides for the Spike 2
        click hunt.  Values at their defaults leave the standard behavior
        untouched; everything is persisted and applied via
        ``on_audio_advanced_change`` (the App mirrors them into env vars)."""
        root = self._tk_root()
        dlg = tk.Toplevel(root)
        dlg.title("Advanced Audio Options")
        dlg.transient(root)
        dlg.resizable(False, False)
        self._theme_toplevel(dlg)
        cfg = dict(self._AUDIO_ADV_DEFAULTS)
        cfg.update({k: v for k, v in self._audio_advanced.items()
                    if v is not None})
        wrap = self._AUDIO_ADV_WRAP

        ttk.Label(
            dlg, justify=tk.LEFT, wraplength=wrap,
            text="Experiment levers for how Stern Spike 2 audio replacements "
                 "are encoded. Defaults match the standard behavior; change "
                 "one thing at a time when chasing a click on the real "
                 "machine.").pack(anchor=tk.W, padx=12, pady=(12, 8))

        # Horizontal rules between the option groups break up the wall of
        # text-and-knobs (feedback batch 20 item 5).
        def _rule():
            ttk.Separator(dlg, orient=tk.HORIZONTAL).pack(
                fill=tk.X, padx=12, pady=(2, 8))

        _rule()

        grid = ttk.Frame(dlg)
        grid.pack(fill=tk.X, padx=12)

        head_var = tk.StringVar(value=dict(self._AUDIO_HEAD_CHOICES)[
            cfg["head_mode"] if cfg["head_mode"] in
            dict(self._AUDIO_HEAD_CHOICES) else "encode"])
        lead_var = tk.StringVar(value=dict(self._AUDIO_LEADOUT_CHOICES)[
            cfg["leadout"] if cfg["leadout"] in
            dict(self._AUDIO_LEADOUT_CHOICES) else "silence"])
        ttk.Label(grid, text="Head block (first 4.5 ms):").grid(
            row=0, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(grid, textvariable=head_var, state="readonly", width=48,
                     values=[v for _k, v in self._AUDIO_HEAD_CHOICES]).grid(
            row=0, column=1, columnspan=2, sticky=tk.W, padx=(8, 0), pady=2)
        ttk.Label(grid, text="Tail block (last 4.5 ms):").grid(
            row=1, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(grid, textvariable=lead_var, state="readonly", width=48,
                     values=[v for _k, v in self._AUDIO_LEADOUT_CHOICES]).grid(
            row=1, column=1, columnspan=2, sticky=tk.W, padx=(8, 0), pady=2)

        idxs_var = tk.StringVar(value=str(cfg.get("experiment_idxs") or ""))
        ttk.Label(grid, text="Only these idx numbers:").grid(
            row=2, column=0, sticky=tk.W, pady=2)
        ttk.Entry(grid, textvariable=idxs_var, width=24).grid(
            row=2, column=1, sticky=tk.W, padx=(8, 0), pady=2)
        ttk.Label(grid, text="head/tail modes only, e.g. 231, 258 — blank "
                             "= all; lets one card carry treated slots and "
                             "untouched controls",
                  font=(_SANS_FONT, 8, "italic")).grid(
            row=2, column=2, sticky=tk.W, padx=(8, 0), pady=2)

        _rule()

        # Anti-pop codec seed (the LZ start-pop fix).
        seed_var = tk.BooleanVar(value=bool(cfg.get("slot_seed")))
        seed_db_var = tk.StringVar(value=str(cfg.get("slot_seed_db") or 65))
        seed_row = ttk.Frame(dlg)
        seed_row.pack(fill=tk.X, padx=12)
        ttk.Checkbutton(
            seed_row, variable=seed_var,
            text="Anti-pop codec seed for silent / quiet callouts").pack(
            side=tk.LEFT)
        ttk.Label(seed_row, text="level -").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Spinbox(seed_row, textvariable=seed_db_var, from_=40, to=90,
                    increment=5, width=5).pack(side=tk.LEFT)
        ttk.Label(seed_row, text="dBFS").pack(side=tk.LEFT, padx=(2, 0))
        ttk.Label(
            dlg, justify=tk.LEFT, wraplength=wrap,
            font=(_SANS_FONT, 8, "italic"),
            text="Mixes an inaudible low tone (default -65 dBFS) into "
                 "replacements so a callout is never completely silent. On some "
                 "machines a silent or very quiet replacement clicks at the "
                 "start while audible ones and the stock callouts do not — the "
                 "machine's audio output adds that pop on dead silence (the "
                 "decoded audio itself is correct). Keeping a whisper-level "
                 "signal present is meant to stop that. Turn on if silent or "
                 "quiet replacements click at the start; combine with the "
                 "'only these idx numbers' box above to seed some slots and "
                 "leave others as an on-card A/B. Experimental, "
                 "hardware-unverified.").pack(anchor=tk.W, padx=12, pady=(2, 8))

        _rule()

        # Blip-free callouts (the master-directory scrap fix).  OFF by default
        # since v0.104.0: the firmware cave has now boot-looped the same machine
        # on three releases and has never been confirmed to boot on any, so it
        # is offered as an experiment rather than shipped as the standard build.
        blip_var = tk.BooleanVar(value=bool(cfg.get("blip_free_optin", False)))
        ttk.Checkbutton(
            dlg, variable=blip_var,
            text="Blip-free callouts: patch the game firmware so a replaced "
                 "sound plays your audio for its whole length (default off, "
                 "hardware-unverified)"
        ).pack(anchor=tk.W, padx=12)
        ttk.Label(
            dlg, justify=tk.LEFT, wraplength=wrap,
            font=(_SANS_FONT, 8, "italic"),
            text="What it does, technically. At boot the game reads two ~512-"
                 "byte windows out of every sound's body to work out that "
                 "sound's decoder settings, and each result feeds the next, so "
                 "the whole sound bank is one forward chain. Re-encoding a "
                 "sound changes those bytes and desyncs the chain, which makes "
                 "the machine reboot the moment any audio plays. The safe "
                 "fallback is to put the original bytes back in just those two "
                 "windows — but they sit inside the audible part, so you hear a "
                 "~6 ms scrap of the ORIGINAL sound twice inside every "
                 "replacement (the \"blip\"). Instead of that, this stashes a "
                 "copy of the original window bytes inside the firmware and "
                 "adds a small piece of ARM code that points the boot-time read "
                 "at the copy, for the replaced sounds only. The chain then "
                 "sees exactly what it saw on a stock card while the card "
                 "itself carries your audio end to end. The added code needs "
                 "somewhere to live: it is appended to the game binary and "
                 "given a memory mapping of its own, at an address no part of "
                 "the game claims. (Before v0.94.0 it was tucked into a run of "
                 "zero bytes inside the game's own data instead, which on some "
                 "titles turned out to be memory the game was using — on "
                 "Elvira, the node board table — and those cards booted slowly "
                 "and threw node board errors.) Because the binary gets longer, "
                 "this needs the Linux filesystem driver, the same as full-size "
                 "video replacement, and it is skipped for a direct-SD write. "
                 "Every build re-derives all the sounds' settings from the "
                 "patched firmware first and falls back to the plain "
                 "stock-byte restore if anything would drift. "
                 "Why it is off. On the one machine this has ever been tried "
                 "on, a card built this way reboots partway through the "
                 "startup screen and loops there. Two faults in the added code "
                 "were found and fixed in v0.102.5 and the same machine still "
                 "does it, so the cause is something not yet identified, and "
                 "no card built this way has been confirmed to boot on any "
                 "machine. Everything that says otherwise is a test on this PC, "
                 "which cannot see how a real machine loads a patched game "
                 "binary. Leaving it off costs you a ~6 ms scrap of the "
                 "original sound at two points inside each replacement, which "
                 "at least one tester listening for it could not hear. Tick it "
                 "only if you want to help find the fault and are willing to "
                 "rebuild the card from your original image afterwards.").pack(
            anchor=tk.W, padx=12, pady=(2, 8))

        _rule()

        prev_var = tk.BooleanVar(value=bool(cfg["previews"]))
        ttk.Checkbutton(
            dlg, variable=prev_var,
            text="On Build, export machine-render WAVs of every changed "
                 "sound (hear exactly what the card will play)").pack(
            anchor=tk.W, padx=12)
        ttk.Label(
            dlg, justify=tk.LEFT, wraplength=wrap,
            font=(_SANS_FONT, 8, "italic"),
            text="Previews land in a <build name>_machine_previews folder "
                 "next to the built image. Note: they show what our decoder "
                 "renders — an artifact the real machine adds on its own "
                 "cannot appear in a preview.").pack(
            anchor=tk.W, padx=12, pady=(2, 8))

        def _collect():
            def num(var, lo, hi, dflt):
                try:
                    v = float(var.get())
                except (TypeError, ValueError):
                    return dflt
                return int(min(max(v, lo), hi))
            keys_h = {v: k for k, v in self._AUDIO_HEAD_CHOICES}
            keys_l = {v: k for k, v in self._AUDIO_LEADOUT_CHOICES}
            idxs = ",".join(t.strip() for t in
                            idxs_var.get().replace(";", ",").split(",")
                            if t.strip().isdigit())
            return {
                "head_mode": keys_h.get(head_var.get(), "encode"),
                "leadout": keys_l.get(lead_var.get(), "silence"),
                "previews": bool(prev_var.get()),
                "experiment_idxs": idxs,
                "slot_seed": bool(seed_var.get()),
                "slot_seed_db": num(seed_db_var, 40, 90, 65),
                "blip_free_optin": bool(blip_var.get()),
            }

        def _ok(_e=None):
            self._audio_advanced = _collect()
            if self._on_audio_advanced_change:
                self._on_audio_advanced_change(dict(self._audio_advanced))
            self._refresh_audio_adv_marker()
            dlg.destroy()

        def _defaults():
            head_var.set(dict(self._AUDIO_HEAD_CHOICES)["encode"])
            lead_var.set(dict(self._AUDIO_LEADOUT_CHOICES)["silence"])
            prev_var.set(False)
            idxs_var.set("")
            seed_var.set(False)
            seed_db_var.set("65")
            blip_var.set(False)         # the standard build is the default

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=12, pady=(4, 12))
        # Plain grey OK / Cancel — the green/red pair read as a different
        # convention from every other dialog (feedback batch 20 item 8).
        ttk.Button(btns, text="OK", command=_ok).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(
            side=tk.RIGHT, padx=(0, 6))
        ttk.Button(btns, text="Restore defaults", command=_defaults).pack(
            side=tk.LEFT)
        dlg.bind("<Return>", _ok)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        # Center over the main window (not the top-left of the monitor).
        dlg.update_idletasks()
        px, py = root.winfo_rootx(), root.winfo_rooty()
        pw, ph = root.winfo_width(), root.winfo_height()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        dlg.geometry("+%d+%d" % (px + (pw - w) // 2, py + (ph - h) // 2))
        dlg.grab_set()

    def _refresh_audio_adv_marker(self):
        """Star the Advanced button when any option is off its default, so a
        forgotten experiment setting is visible at a glance (the RAW-toggle
        lesson: a persisted A/B leftover silently shaped every later card)."""
        btn = getattr(self, "_audio_adv_btn", None)
        if btn is None:
            return
        d = dict(self._AUDIO_ADV_DEFAULTS)
        d.update({k: v for k, v in self._audio_advanced.items()
                  if k in self._AUDIO_ADV_DEFAULTS and v is not None})
        off_default = d != self._AUDIO_ADV_DEFAULTS
        btn.config(text="Advanced…*" if off_default else "Advanced…")

    def _audio_profile_click(self):
        """Audio tab -> Profile vs stock: hand the scanned extract folder to
        the App's worker (engine.audio_profile_report)."""
        assets = self._audio_scan_dir
        if not assets:
            messagebox.showinfo(
                "Profile vs stock",
                "Scan an extract folder on the Audio tab first — the report "
                "characterizes the sounds in that folder.")
            return
        if self._on_audio_profile:
            self._on_audio_profile(assets)

    def _save_staged_changes(self):
        """Persist the current Replace assignments for the active assets folder.

        Writes the audio/video/image sections for whichever tabs are currently
        live for that folder (their scan matches it); sections for tabs not yet
        scanned for this folder are preserved from the existing sidecar so one
        tab's save never wipes another's pending edits.  Best-effort — any I/O
        failure is swallowed by core.staged_changes.save."""
        from ..core import staged_changes
        assets_dir = (self.write_assets_var.get() or "").strip()
        if not assets_dir or not os.path.isdir(assets_dir):
            return

        def _live(scan_dir):
            return bool(scan_dir) and (
                os.path.normcase(os.path.normpath(scan_dir))
                == os.path.normcase(os.path.normpath(assets_dir)))

        data = staged_changes.load(assets_dir)
        # Every pick/re-pick/clear (and build-shaping toggle flip) also lands
        # in the folder's own append-only .history.log with the old and new
        # source, so "changed on disk" months later still says what it was
        # changed WITH (batch 24).  The diff is against the sidecar being
        # replaced — the same data, so no extra I/O beyond one append.
        from ..core import history_log
        hist = []
        if _live(self._audio_scan_dir):
            hist += history_log.diff_assignments(
                "audio", data.get("audio"), self._audio_assignments)
            hist.append(history_log.diff_scalar(
                'audio  option "Trim / pad replacements to the original '
                'slot length"',
                data.get("audio_trim"), bool(self.audio_trim_var.get())))
            data["audio"] = dict(self._audio_assignments)
            data["audio_loop"] = dict(self._audio_loop_flags)
            data["audio_keep"] = dict(self._audio_keep_full_flags)
            data["audio_trim"] = bool(self.audio_trim_var.get())
            data["audio_change_filter"] = self.audio_change_filter_var.get()
        if _live(self._video_scan_dir):
            hist += history_log.diff_assignments(
                "video", data.get("video"), self._video_assignments)
            hist.append(history_log.diff_scalar(
                'video  option "Trim / pad to the original clip length"',
                data.get("video_trim"), bool(self.video_trim_var.get())))
            hist.append(history_log.diff_scalar(
                'video  option "Use my files as-is — never re-encode"',
                data.get("video_no_conversion"),
                bool(self.video_no_conversion_var.get())))
            data["video"] = dict(self._video_assignments)
            data["video_trim"] = bool(self.video_trim_var.get())
            data["video_no_conversion"] = bool(
                self.video_no_conversion_var.get())
            data["video_change_filter"] = self.video_change_filter_var.get()
        if _live(getattr(self, "_text_scan_dir", "")):
            # The Text tab stages nothing (edits go straight to strings.tsv),
            # but its two view filters are folder state like everyone else's.
            data["text_change_filter"] = self.text_change_filter_var.get()
            data["text_scene_filter"] = self.text_scene_filter_var.get()
        if _live(self._image_scan_dir):
            hist += history_log.diff_assignments(
                "image", data.get("image"), self._image_assignments)
            data["image"] = dict(self._image_assignments)
            data["image_change_filter"] = self.image_change_filter_var.get()
            data["image_group_by_scene"] = bool(
                self.image_group_by_scene_var.get())
            data["image_group_tags"] = {
                k: v for k, v in self._image_group_tags.items() if v}
            data["image_source_filter"] = self.image_source_filter_var.get()
            # Mirror the names into the per-card library so a fresh re-extract
            # of this same card can restore them (see tag_library).
            try:
                from ..core import tag_library
                known = {self._image_group_of(s.rel_path)[0]
                         for s in self._image_slots}
                known |= set(self._image_group_tags)
                tag_library.remember(
                    assets_dir, self._image_group_tags, known)
            except Exception:
                pass
        staged_changes.save(assets_dir, data)
        history_log.record(assets_dir, [h for h in hist if h])
        # Batch 19 anchor materialization: a staged change is the app
        # writing state into the folder, which is exactly when a folder
        # becomes a project (same rule as extract — never on read-only
        # browsing).  The app-side hook no-ops if the anchor exists.
        if self._on_folder_state_written:
            self._on_folder_state_written(assets_dir)

    # ==================================================================
    # Replace Text tab — edit the player-facing on-screen strings Extract
    # pulled out to text/strings.tsv.  Unlike the audio/video/image tabs,
    # there are no in-memory "pending assignments": edits are written
    # straight back to the manifest, and Write re-reads it to patch every
    # matching string in place (size-neutral).
    # ==================================================================

    # ==================================================================
    # Partition Explorer tab — read-only browse of a raw card image's MBR
    # partitions + ext4 filesystem(s), with file/folder extract to disk.
    # For pulling radium/.sh files out of an old modded card, or dumping
    # folders to diff a modded card vs stock, without a mount+map cycle
    # (a tester).  Composes plugins.stern.explorer.CardImage; nothing on
    # the card is written.
    # ==================================================================

    def _build_partition_tab(self):
        """Build the read-only 'Partition Explorer' tab: pick a raw card image,
        pick a partition, browse its ext4 tree (lazily), preview small text
        files, and extract any file or folder to disk."""
        f = self._tab_partition
        self._pex_card = None            # the open CardImage (browse handle)
        self._pex_image_path = None
        self._pex_part_index = None
        self._pex_dirs = set()           # tree iids that are directories
        self._pex_populated = set()      # dir iids whose children were loaded
        self._pex_busy = False           # an extract is running
        self._pex_part_labels = {}       # combobox label -> Partition
        self._pex_changed_marks = {}     # on-card path -> "replaced <date>"
        self._pex_preview_seq = 0        # discards a superseded async preview
        self._pex_preview_img = None     # keeps the rendered PhotoImage alive
        self.partition_image_var = tk.StringVar()
        self.partition_part_var = tk.StringVar()
        self.partition_show_var = tk.StringVar(value="All")

        intro = ttk.Label(
            f, text="Browse a raw Stern card image (.raw / .img): view its "
                    "partitions and files, preview images, fonts and text, "
                    "extract any file or folder to disk, "
                    "and (right-click) replace any file with one of your own — "
                    "a same-size file is written straight into its slot, and a "
                    "bigger or smaller one is resized on the card through the "
                    "Linux filesystem driver (needs WSL2). Validation records "
                    "are refreshed automatically. Browsing never changes the "
                    "card; only an explicit Replace writes to it. Changed marks "
                    "the files you have replaced here, remembered per card "
                    "image — an edit made outside PAD leaves no trace to find.",
            font=(_SANS_FONT, 9, "italic"), justify=tk.LEFT)
        intro.pack(anchor=tk.W, fill=tk.X, padx=10, pady=4)
        # Rewrap to the actual window width instead of a fixed 720px
        # (a tester: "the text should flow into that area").
        intro.bind("<Configure>", lambda e: intro.configure(
            wraplength=max(300, e.width - 8)))

        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(row, text="Card Image:", width=12, anchor=tk.W).pack(
            side=tk.LEFT)
        ent = self._path_combo(row, self.partition_image_var,
                               "partition_image")
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent.bind("<Return>", lambda _e: self._pex_open_image())
        # Picking a recent path opens it right away (typed paths go through
        # Return), and Browse… opens whatever it picks — a separate Open
        # button read as "what does this do?" (feedback batch 10).
        ent.bind("<<ComboboxSelected>>",
                 lambda _e: self._pex_open_image(), add="+")
        ttk.Button(row, text="Browse…", command=self._pex_browse_image).pack(
            side=tk.LEFT, padx=(6, 0))

        prow = ttk.Frame(f); prow.pack(fill=tk.X, padx=10, pady=(2, 4))
        ttk.Label(prow, text="Partition:", width=12, anchor=tk.W).pack(
            side=tk.LEFT)
        self._pex_part_combo = ttk.Combobox(
            prow, textvariable=self.partition_part_var, state="readonly",
            width=46)
        self._pex_part_combo.pack(side=tk.LEFT)
        self._pex_part_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._pex_on_partition_select())
        # Show filter — the same All / Changed / Unchanged the Replace tabs
        # got, over the files this card image has had replaced (batch 30).
        ttk.Label(prow, text="Show:").pack(side=tk.LEFT, padx=(14, 4))
        self._pex_show_combo = ttk.Combobox(
            prow, textvariable=self.partition_show_var, state="readonly",
            width=11, values=("All", "Changed", "Unchanged"))
        self._pex_show_combo.pack(side=tk.LEFT)
        self._pex_show_combo.bind("<<ComboboxSelected>>",
                                  lambda _e: self._pex_apply_show())
        # place="side": a tip under a combobox lands where its drop-down opens.
        _Tooltip(self._pex_show_combo,
                 "Changed = the files you have replaced on this card image "
                 "with PAD (it remembers them per image, so they are still "
                 "marked next session).\nUnchanged = the rest of the tree "
                 "with those files left out.",
                 lambda: self._current_theme, place="side")
        # (No partition-count label here — the dropdown already shows every
        # partition; extract results land next to the extract buttons below.)
        # Find-in-partition: substring over full paths, Enter / "Find Next"
        # cycles matches and reveals each in the lazy tree (a tester
        # batch 10 wishlist: PE search).
        self.partition_search_var = tk.StringVar()
        self._pex_find_btn = ttk.Button(prow, text="Find Next",
                                        command=self._pex_find_next,
                                        state=tk.DISABLED)
        self._pex_find_btn.pack(side=tk.RIGHT)
        find_ent = ttk.Entry(prow, textvariable=self.partition_search_var,
                             width=22)
        find_ent.pack(side=tk.RIGHT, padx=(12, 6))
        find_ent.bind("<Return>", lambda _e: self._pex_find_next())
        ttk.Label(prow, text="Find:").pack(side=tk.RIGHT)
        self._pex_search_cache = None      # (image, part) -> sorted paths
        self._pex_search_state = ("", -1)  # (query, last match index)

        body = ttk.Frame(f); body.pack(fill=tk.BOTH, expand=True, padx=10,
                                       pady=(2, 4))
        left = ttk.Frame(body); left.pack(side=tk.LEFT, fill=tk.BOTH,
                                          expand=True)
        self._pex_tree = ttk.Treeview(
            left, columns=("size", "type", "changed"), height=14,
            selectmode="browse")
        self._pex_tree.heading("#0", text="Name", anchor=tk.W)
        self._pex_tree.heading("size", text="Size", anchor=tk.E)
        self._pex_tree.heading("type", text="Type", anchor=tk.W)
        self._pex_tree.heading("changed", text="Changed", anchor=tk.W)
        self._pex_tree.column("#0", width=320, minwidth=160)
        self._pex_tree.column("size", width=90, minwidth=60, anchor=tk.E,
                              stretch=False)
        self._pex_tree.column("type", width=160, minwidth=90, anchor=tk.W,
                              stretch=False)
        self._pex_tree.column("changed", width=150, minwidth=90, anchor=tk.W,
                              stretch=False)
        self._pex_tree.tag_configure(
            "pex_changed", foreground=THEMES[self._current_theme]["warning"])
        vs = ttk.Scrollbar(left, orient="vertical",
                           command=self._pex_tree.yview)
        self._pex_tree.configure(yscrollcommand=vs.set)
        self._pex_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vs.pack(side=tk.LEFT, fill=tk.Y)
        self._pex_tree.bind("<<TreeviewOpen>>", self._pex_on_tree_open)
        self._pex_tree.bind("<<TreeviewSelect>>", self._pex_on_tree_select)
        # Right-click → Properties (full on-card path for mount workflows,
        # size, partition) + quick Extract (feedback batch 14).
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self._pex_tree.bind(seq, self._pex_on_tree_right)
        # Big animated "Extracting…" overlay, placed over the tree while an
        # extract runs — the same large spinner the Replace tabs' scans use
        # (a tester: "the same large swirly font as the other screens").
        self._pex_busy_lbl = ttk.Label(left, font=(_SANS_FONT, 18, "bold"))

        right = ttk.Frame(body); right.pack(side=tk.LEFT, fill=tk.BOTH,
                                            padx=(8, 0))
        self._pex_preview_frame = right
        ttk.Label(right, text="Preview", font=(_SANS_FONT, 9, "bold")).pack(
            anchor=tk.W)
        # What the pane is showing ("PNG · 1360 × 768 · 162.1 KB") — a rendered
        # image says nothing about its real dimensions once it's been scaled to
        # fit, and those are exactly what a replacement has to match.
        self._pex_preview_caption = ttk.Label(right, text="",
                                              font=(_SANS_FONT, 9))
        self._pex_preview_caption.pack(anchor=tk.W)
        # Raw tk widgets, so they need explicit colours — ttk styling doesn't
        # reach them and they otherwise render as white panels inside the dark
        # tab.  _apply_theme re-colours them on a live theme switch.
        _pc = THEMES[self._current_theme]
        # Images and fonts render on the canvas, everything else stays text;
        # only one of the two is ever packed (see _pex_show_*_preview).
        self._pex_preview_canvas = tk.Canvas(
            right, width=330, height=250, bg=_pc["field_bg"],
            highlightthickness=1, highlightbackground=_pc["border"],
            relief=tk.FLAT)
        self._pex_preview_canvas.bind("<Configure>", self._pex_centre_preview)
        self._pex_preview = tk.Text(right, width=46, height=10, wrap="none",
                                    state="disabled", font=(_MONO_FONT, 9),
                                    bg=_pc["field_bg"], fg=_pc["fg"],
                                    insertbackground=_pc["fg"],
                                    selectbackground=_pc["select_bg"],
                                    highlightthickness=1,
                                    highlightbackground=_pc["border"],
                                    relief=tk.FLAT)
        self._pex_preview.pack(fill=tk.BOTH, expand=True)

        arow = ttk.Frame(f); arow.pack(fill=tk.X, padx=10, pady=(0, 8))
        # No trailing "…" on the extract buttons — it read as truncated text
        # rather than the opens-a-dialog convention (feedback batch 14).
        self._pex_extract_btn = ttk.Button(
            arow, text="Extract Selected", command=self._pex_extract_selected,
            state=tk.DISABLED, style="Go.TButton")
        self._pex_extract_btn.pack(side=tk.LEFT)
        self._pex_extract_part_btn = ttk.Button(
            arow, text="Extract Whole Partition",
            command=self._pex_extract_partition, state=tk.DISABLED,
            style="Go.TButton")
        self._pex_extract_part_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._pex_extract_all_btn = ttk.Button(
            arow, text="Extract All Partitions",
            command=self._pex_extract_all, state=tk.DISABLED,
            style="Go.TButton")
        self._pex_extract_all_btn.pack(side=tk.LEFT, padx=(6, 0))
        # Extract results show right next to the buttons that made them
        # (they used to land top-right by the partition combo, where they
        # read as unrelated — feedback batch 10).
        self._pex_action_status = ttk.Label(arow, text="",
                                            font=(_SANS_FONT, 9))
        self._pex_action_status.pack(side=tk.LEFT, padx=(10, 0))

    # ---- Partition Explorer: open + partitions -----------------------

    def _pex_default_from_extract(self):
        """A blank Card Image box defaults to the Extract tab's input image
        and opens it right away (a tester: "defaults to the raw image
        selected on the Extract screen").  Never overrides a path the user
        already put here."""
        if self._pex_busy or (self.partition_image_var.get() or "").strip():
            return
        src = (self.extract_input_var.get() or "").strip()
        if (src and src.lower().endswith((".raw", ".img", ".bin"))
                and os.path.isfile(src)):
            self.partition_image_var.set(os.path.normpath(src))
            self._pex_open_image()

    def _pex_browse_image(self):
        cur = (self.partition_image_var.get() or "").strip()
        path = filedialog.askopenfilename(
            title="Select a card image",
            filetypes=[("Card image", "*.raw *.img *.bin"),
                       ("All files", "*.*")],
            initialdir=(os.path.dirname(cur) if cur else None))
        if path:
            self.partition_image_var.set(os.path.normpath(path))
            self._pex_open_image()

    def _pex_open_image(self):
        """Open the card image at the current path and fill the partition combo,
        selecting the first browsable ext partition."""
        if self._pex_busy:
            messagebox.showinfo(
                "Extract in progress",
                "An extract is still running — cancel it before opening "
                "another image.")
            return
        path = (self.partition_image_var.get() or "").strip()
        if not path:
            return
        if not os.path.isfile(path):
            self.append_log("Could not open %s: file not found." % path,
                            "error")
            messagebox.showerror("File not found", "No file at:\n\n%s" % path)
            return
        self._pex_close_card()
        try:
            from ..plugins.stern.explorer import CardImage
            card = CardImage(path)
        except Exception as e:
            self.append_log("Could not open %s: %s" % (path, e), "error")
            messagebox.showerror(
                "Not a card image",
                "Couldn't open this file as a raw card image:\n\n%s\n\n%s"
                % (path, e))
            return
        self._pex_card = card
        self._pex_image_path = path
        if self._on_partition_image_opened:
            # Only real, opened images enter the recent-paths dropdown.
            self._on_partition_image_opened(path)
        parts = card.partitions()
        self._pex_part_labels = {}
        labels = []
        for p in parts:
            # Linux-style device names (sda1 = MBR slot 0) — the naming users
            # already know from mounting these cards by hand (a tester
            # batch 14).
            label = "sda%d — %s (%s)%s" % (
                p.index + 1, p.label, self._pex_human(p.size),
                "" if p.browsable else " — not browsable")
            self._pex_part_labels[label] = p
            labels.append(label)
        self._pex_part_combo["values"] = labels
        first = next((lbl for lbl, p in self._pex_part_labels.items()
                      if p.browsable), None)
        self.append_log(
            "Opened %s — %d partition%s."
            % (path, len(parts), "" if len(parts) == 1 else "s"), "info")
        if first:
            self.partition_part_var.set(first)
            self._pex_on_partition_select()
        else:
            self.partition_part_var.set(labels[0] if labels else "")
            self._clear_pex_tree()
            self.append_log(
                "No browsable ext filesystem on this image.", "warning")
            messagebox.showwarning(
                "Nothing to browse",
                "This image has no browsable ext filesystem.")

    def _pex_on_partition_select(self):
        if self._pex_busy:
            # Mid-extract the action buttons are Cancel / waiting — don't
            # let a partition switch clear the tree under them; snap back.
            cur = next((lbl for lbl, p in self._pex_part_labels.items()
                        if p.index == self._pex_part_index), None)
            if cur:
                self.partition_part_var.set(cur)
            return
        p = self._pex_part_labels.get(self.partition_part_var.get())
        if p is None or self._pex_card is None:
            return
        self._clear_pex_tree()
        if not p.browsable:
            self._pex_action_status.configure(
                text="This partition isn't a browsable ext filesystem.")
            return
        self._pex_action_status.configure(text="")
        self._pex_part_index = p.index
        self._pex_extract_part_btn.config(state=tk.NORMAL)
        self._pex_find_btn.config(state=tk.NORMAL)
        if any(q.browsable for q in self._pex_part_labels.values()):
            self._pex_extract_all_btn.config(state=tk.NORMAL)
        self._pex_refresh_changed_marks()
        if self.partition_show_var.get() == "Changed":
            self._pex_fill_changed_only()
        else:
            self._pex_populate_dir("", "/")     # the partition root's children

    # ---- Partition Explorer: find ------------------------------------

    def _pex_find_next(self):
        """Find the next full-path substring match in the current partition
        and reveal it — the path list is walked once per (image, partition)
        and cached, so repeated Find Next presses are instant."""
        if self._pex_card is None or self._pex_part_index is None:
            return
        query = (self.partition_search_var.get() or "").strip().lower()
        if not query:
            return
        self._pex_unfilter_for_reveal()
        key = (self._pex_image_path, self._pex_part_index)
        cache = self._pex_search_cache
        if not cache or cache[0] != key:
            reader = self._pex_card.reader(self._pex_part_index)
            paths = []
            try:
                for rel, _ino, _node in reader.iter_regular_files(
                        max_depth=64, min_size=0):
                    paths.append("/" + rel.strip("/"))
            except Exception:
                pass
            paths.sort()
            self._pex_search_cache = cache = (key, paths)
        paths = cache[1]
        last_q, last_i = self._pex_search_state
        start = last_i + 1 if last_q == query else 0
        order = list(range(start, len(paths))) + list(range(0, start))
        for i in order:
            if query in paths[i].lower():
                self._pex_search_state = (query, i)
                self._pex_reveal(paths[i])
                self._pex_action_status.configure(text="")
                return
        self._pex_search_state = (query, -1)
        self._pex_action_status.configure(
            text="No file path contains “%s”."
                 % self.partition_search_var.get().strip())

    # ---- Find in Partition Explorer (from a Replace tab) ---------------

    def _pex_partition_paths(self, part_index):
        """Sorted absolute file paths in *part_index*, using the same walk +
        cache Find Next uses (one walk per image+partition)."""
        key = (self._pex_image_path, part_index)
        cache = self._pex_search_cache
        if cache and cache[0] == key:
            return cache[1]
        paths = []
        try:
            reader = self._pex_card.reader(part_index)
            for rel, _ino, _node in reader.iter_regular_files(max_depth=64,
                                                              min_size=0):
                paths.append("/" + rel.strip("/"))
        except Exception:
            return []
        paths.sort()
        self._pex_search_cache = (key, paths)
        return paths

    def _asset_find_in_partition(self, kind, rel):
        """Jump from a Replace-tab row to the file it came from on the card.

        Opens the Partition Explorer on the extract's own source image,
        selects the partition holding the file and expands the tree down to
        it.  Sounds and radium-embedded images aren't standalone files on the
        card, so those reveal their CONTAINER and say so (feedback batch 16).
        """
        from ..core import card_paths
        assets_dir = ""
        if kind == "audio":
            assets_dir = self._audio_scan_dir
        elif kind == "video":
            assets_dir = self._video_scan_dir
        else:
            assets_dir = self._image_scan_dir

        # Resolve the row to something findable on the card.
        want_basename = None
        if kind == "video":
            target, note = card_paths.video_card_path(assets_dir, rel)
        elif kind == "image":
            target, note = card_paths.image_card_path(assets_dir, rel)
        else:
            want_basename, note = card_paths.audio_card_hint(rel)
            target = None
            if want_basename is None:
                messagebox.showinfo("Find in Partition Explorer", note)
                return
        if kind in ("video", "image") and target is None:
            messagebox.showinfo("Find in Partition Explorer", note)
            return

        # Make sure an image is open (defaults to the Extract tab's input).
        self._notebook.select(self._tab_partition)
        if self._pex_card is None:
            self._pex_default_from_extract()
        if self._pex_card is None:
            messagebox.showinfo(
                "Find in Partition Explorer",
                "Pick the card image these assets were extracted from "
                "(the Card Image box at the top of this tab), then try "
                "again.")
            return

        # Search the current partition first, then the rest — Stern keeps the
        # game assets on the data partition, but don't hard-code that.
        order = [p.index for p in self._pex_part_labels.values() if p.browsable]
        if self._pex_part_index in order:
            order.remove(self._pex_part_index)
            order.insert(0, self._pex_part_index)
        hit = hit_part = None
        for idx in order:
            paths = self._pex_partition_paths(idx)
            if target is not None:
                if target in paths:
                    hit, hit_part = target, idx
                    break
            else:
                match = next((p for p in paths
                              if os.path.basename(p) == want_basename), None)
                if match:
                    hit, hit_part = match, idx
                    break
        if hit is None:
            missing = target or want_basename
            self.append_log(
                "Find in Partition: %s isn't on %s."
                % (missing, os.path.basename(self._pex_image_path or "")),
                "warning")
            messagebox.showinfo(
                "Find in Partition Explorer",
                "Couldn't find\n\n%s\n\non %s.\n\nThe open card image may be a "
                "different game or firmware than these assets were extracted "
                "from." % (missing, os.path.basename(
                    self._pex_image_path or "this image")))
            return

        if hit_part != self._pex_part_index:
            label = next((lbl for lbl, p in self._pex_part_labels.items()
                          if p.index == hit_part), None)
            if label:
                self.partition_part_var.set(label)
                self._pex_on_partition_select()
        self._pex_unfilter_for_reveal()
        self._pex_reveal(hit)
        self._pex_action_status.configure(text=note or "")
        self.append_log("Find in Partition: %s → %s%s"
                        % (rel, hit, ("  (%s)" % note) if note else ""),
                        "info")

    def _pex_unfilter_for_reveal(self):
        """Drop back to Show: All before revealing a path.

        A filtered tree doesn't hold every path, and it deliberately doesn't
        lazy-load into itself — so a Find for something the filter left out
        would quietly do nothing.  Finding it is what the user asked for; the
        filter isn't."""
        if self.partition_show_var.get() != "All":
            self.partition_show_var.set("All")
            self._pex_apply_show()

    def _pex_reveal(self, path):
        """Expand the lazy tree down to *path* and select it."""
        tree = self._pex_tree
        parts = [p for p in path.strip("/").split("/") if p]
        fs = ""
        for name in parts[:-1]:
            fs = fs + "/" + name
            if fs in self._pex_dirs and fs not in self._pex_populated:
                self._pex_populate_dir(fs, fs)
            try:
                tree.item(fs, open=True)
            except tk.TclError:
                return
        try:
            tree.selection_set(path)
            tree.see(path)
            tree.focus(path)
        except tk.TclError:
            pass

    # ---- Partition Explorer: tree ------------------------------------

    def _pex_populate_dir(self, parent_iid, path):
        """Insert *path*'s children under the tree node *parent_iid* (``""`` for
        the partition root).  Each directory gets a placeholder child so it
        shows an expander and loads lazily on open.

        Honours the Show filter: on "Unchanged" the files this card image has
        had replaced are left out as they're loaded, which keeps the tree's
        shape and its laziness (folders always stay — whether one still holds
        an unchanged file isn't knowable without walking it)."""
        tree = self._pex_tree
        hide_changed = self.partition_show_var.get() == "Unchanged"
        marks = self._pex_changed_marks
        for c in tree.get_children(parent_iid):
            if c.endswith(_PEX_PLACEHOLDER):
                tree.delete(c)
        try:
            entries = self._pex_card.list_dir(self._pex_part_index, path)
        except Exception as e:
            self.append_log("Could not list %s: %s" % (path, e), "error")
            self._pex_action_status.configure(text="Error: %s" % e)
            return
        for e in entries:
            iid = e.path
            if e.is_dir:
                tree.insert(parent_iid, tk.END, iid=iid, text=e.name,
                            values=("", "folder", ""))
                tree.insert(iid, tk.END, iid=iid + _PEX_PLACEHOLDER, text="")
                self._pex_dirs.add(iid)
            else:
                mark = marks.get(iid, "")
                if mark and hide_changed:
                    continue
                typ = ("symlink → " + (e.link_target or "?")
                       if e.is_symlink else "file")
                tree.insert(parent_iid, tk.END, iid=iid, text=e.name,
                            values=(self._pex_human(e.size), typ, mark),
                            tags=("pex_changed",) if mark else ())
        self._pex_populated.add(parent_iid)

    def _pex_refresh_changed_marks(self):
        """Reload the current image+partition's "replaced by you" marks from
        :mod:`core.card_edits` (the journal the Replace writes)."""
        from ..core import card_edits
        marks = {}
        if self._pex_image_path and self._pex_part_index is not None:
            try:
                for p, e in card_edits.replaced(
                        self._pex_image_path, self._pex_part_index).items():
                    when = str(e.get("when") or "")[:10]
                    marks[p] = ("replaced %s" % when) if when else "replaced"
            except Exception:
                marks = {}
        self._pex_changed_marks = marks

    def _pex_apply_show(self):
        """Rebuild the tree for the Show filter (All / Changed / Unchanged)."""
        if self._pex_busy or self._pex_card is None:
            return
        part = self._pex_part_index
        if part is None:
            return
        self._pex_refresh_changed_marks()
        self._clear_pex_tree()
        # Pinned back deliberately: only _pex_close_card drops the partition
        # today, and a filter switch must never be the thing that loses it.
        self._pex_part_index = part
        self._pex_extract_part_btn.config(state=tk.NORMAL)
        self._pex_find_btn.config(state=tk.NORMAL)
        if any(q.browsable for q in self._pex_part_labels.values()):
            self._pex_extract_all_btn.config(state=tk.NORMAL)
        if self.partition_show_var.get() == "Changed":
            self._pex_fill_changed_only()
        else:
            self._pex_populate_dir("", "/")

    def _pex_fill_changed_only(self):
        """Show just the files replaced on this image, each under its own
        folders, fully expanded.

        Built from the journal rather than by walking the card — the set is
        small and known, so this is instant even on the 6 GB data partition."""
        tree = self._pex_tree
        paths = sorted(self._pex_changed_marks)
        if not paths:
            self._pex_action_status.configure(
                text="Nothing replaced on this partition yet — Show: Changed "
                     "lists the files you replace here.")
            return
        made = set()
        missing = 0
        for p in paths:
            names = [n for n in p.strip("/").split("/") if n]
            if not names:
                continue
            fs = ""
            for name in names[:-1]:
                parent, fs = fs, fs + "/" + name
                if fs not in made:
                    tree.insert(parent, tk.END, iid=fs, text=name,
                                values=("", "folder", ""), open=True)
                    made.add(fs)
                    self._pex_dirs.add(fs)
                    # Nothing lazy-loads into a filtered view.
                    self._pex_populated.add(fs)
            try:
                size = self._pex_human(
                    self._pex_card.file_size(self._pex_part_index, p))
                typ = "file"
            except Exception:
                # Recorded against this image but not on it any more (the file
                # was renamed, or the image was replaced by another copy).
                size, typ = "", "not on the card now"
                missing += 1
            tree.insert(p.rsplit("/", 1)[0], tk.END, iid=p,
                        text=names[-1], values=(size, typ,
                                                self._pex_changed_marks[p]),
                        tags=("pex_changed",))
        self._pex_populated.add("")
        self._pex_action_status.configure(
            text="%d file%s replaced on this partition%s."
                 % (len(paths), "" if len(paths) == 1 else "s",
                    " (%d no longer on the card)" % missing if missing else ""))

    def _pex_on_tree_open(self, _event=None):
        """Lazily populate a just-expanded directory node.

        Deferred to ``after_idle``: on some Tk builds the ``<<TreeviewOpen>>``
        handler runs BEFORE the node's ``-open`` state is committed, so reading
        it synchronously would skip the folder the user just expanded and leave
        its blank placeholder row showing."""
        self._tk_root().after_idle(self._pex_fill_open_dirs)

    def _pex_fill_open_dirs(self):
        """Populate every open, not-yet-loaded directory node."""
        tree = getattr(self, "_pex_tree", None)
        if tree is None:
            return
        stack = list(tree.get_children(""))
        while stack:
            iid = stack.pop()
            try:
                is_open = str(tree.item(iid, "open")).lower() in ("1", "true")
            except tk.TclError:
                continue          # node vanished (folder switched mid-expand)
            if not is_open:
                continue
            if iid in self._pex_dirs and iid not in self._pex_populated:
                self._pex_populate_dir(iid, iid)     # iid == fs path
            stack.extend(tree.get_children(iid))

    def _pex_on_tree_select(self, _event=None):
        sel = self._pex_tree.selection()
        if not sel:
            if not self._pex_busy:      # while busy the button is Cancel
                self._pex_extract_btn.config(state=tk.DISABLED)
            return
        iid = sel[0]
        if not self._pex_busy:
            self._pex_extract_btn.config(state=tk.NORMAL)
        if iid in self._pex_dirs:
            self._pex_set_preview("")
            return
        self._pex_preview_seq += 1          # supersede any in-flight render
        ext = os.path.splitext(iid)[1].lower()
        if _HAVE_PIL and ext in (_PEX_IMAGE_EXTS + _PEX_FONT_EXTS):
            self._pex_render_preview(iid, ext, self._pex_preview_seq)
            return
        try:
            data = self._pex_card.preview(self._pex_part_index, iid)
        except Exception as e:
            self._pex_set_preview("(error: %s)" % e)
            return
        if data is None:
            self._pex_set_preview(
                "(binary or too large to preview — extract it to view)")
        else:
            self._pex_set_preview(self._pex_decode_preview(data))

    def _pex_render_preview(self, iid, ext, seq):
        """Draw *iid* — an image or a font — into the preview canvas.

        The read happens on a worker: the text preview's 256 KB cap is small
        enough to pull on the Tk thread, but a card's PNGs run into megabytes
        and the image may be sitting on a NAS.  *seq* is checked before
        anything is drawn, so clicking down a list only ever shows the row
        that's still selected.
        """
        import threading

        from ..core import image as image_mod
        card, part = self._pex_card, self._pex_part_index
        self._pex_set_preview("(reading %s…)" % os.path.basename(iid))
        w, h = self._pex_preview_box()
        is_font = ext in _PEX_FONT_EXTS

        def _work():
            png = caption = err = None
            try:
                data = card.preview(part, iid, cap=_PEX_RENDER_CAP)
            except Exception as e:
                data = None
                err = "(error: %s)" % e
            if data is None and err is None:
                err = ("(too big to preview here — over %s; extract it to "
                       "view)" % self._pex_human(_PEX_RENDER_CAP))
            elif data is not None:
                if is_font:
                    png = image_mod.font_sample_png(data, w, h)
                    caption = "%s · %s" % (ext.lstrip(".").upper(),
                                           self._pex_human(len(data)))
                    if png is None:
                        err = "(not a font Pillow can read)"
                else:
                    png = image_mod.thumbnail_png_bytes(data, w, h)
                    info = image_mod.detect_image_info_bytes(data, iid)
                    if info is not None:
                        caption = "%s · %d × %d · %s" % (
                            info.fmt or ext.lstrip(".").upper(), info.width,
                            info.height, self._pex_human(len(data)))
                    if png is None:
                        err = "(not an image Pillow can read)"

            def _done():
                if seq != self._pex_preview_seq:
                    return                  # a later selection won
                if png is None:
                    self._pex_set_preview(err or "(nothing to preview)")
                    return
                self._pex_show_canvas_preview(png, caption or "")
            try:
                self._tk_root().after(0, _done)
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=_work, daemon=True).start()

    @staticmethod
    def _pex_decode_preview(data):
        sample = data[:4096]
        nonprint = sum(1 for b in sample if b < 9 or 13 < b < 32)
        if sample and nonprint > len(sample) * 0.02:
            return "(binary file — %d bytes; extract it to view)" % len(data)
        return data.decode("utf-8", "replace")

    def _pex_set_preview(self, text):
        """Show *text* in the preview pane (and put the text widget back in
        front of the image canvas if a render had swapped it in)."""
        canvas = getattr(self, "_pex_preview_canvas", None)
        if canvas is not None and canvas.winfo_ismapped():
            canvas.delete("all")
            canvas.pack_forget()
            self._pex_preview_img = None
        cap = getattr(self, "_pex_preview_caption", None)
        if cap is not None:
            cap.configure(text="")
        w = self._pex_preview
        if not w.winfo_ismapped():
            w.pack(fill=tk.BOTH, expand=True)
        w.config(state="normal")
        w.delete("1.0", tk.END)
        w.insert("1.0", text)
        w.config(state="disabled")

    def _pex_preview_box(self):
        """``(w, h)`` the preview canvas has to draw inside.

        Its laid-out size once Tk has one, else the size it was created at — an
        unmapped Tk widget reports a width of 1, which would scale every
        preview down to a thumbnail of a thumbnail.
        """
        c = self._pex_preview_canvas
        try:
            w, h = c.winfo_width(), c.winfo_height()
        except tk.TclError:
            w = h = 0
        if w <= 1 or h <= 1:
            try:
                w, h = int(c.cget("width")), int(c.cget("height"))
            except (tk.TclError, ValueError):
                w, h = 330, 250
        return max(80, w - 10), max(80, h - 10)

    def _pex_show_canvas_preview(self, png, caption):
        """Swap the text pane for the image canvas and centre *png* on it."""
        canvas = self._pex_preview_canvas
        if self._pex_preview.winfo_ismapped():
            self._pex_preview.pack_forget()
        if not canvas.winfo_ismapped():
            canvas.pack(fill=tk.BOTH, expand=True)
        canvas.delete("all")
        self._pex_preview_caption.configure(text=caption)
        try:
            img = tk.PhotoImage(data=base64.b64encode(png))
        except tk.TclError:
            self._pex_preview_img = None
            self._pex_set_preview("(could not draw this preview)")
            return
        self._pex_preview_img = img          # keep the reference alive
        # The canvas was packed a moment ago (or the pane was resized), so its
        # geometry isn't settled yet — centring against a stale width drew the
        # preview into the top-left corner and clipped it.
        try:
            canvas.update_idletasks()
        except tk.TclError:
            pass
        self._pex_centre_preview()

    def _pex_centre_preview(self, _event=None):
        """Put the rendered preview back in the middle of the canvas — also the
        <Configure> handler, so dragging the window keeps it centred."""
        canvas = getattr(self, "_pex_preview_canvas", None)
        img = self._pex_preview_img
        if canvas is None or img is None or not canvas.winfo_ismapped():
            return
        try:
            cw, ch = self._pex_preview_box()
            canvas.delete("preview")
            canvas.create_image(cw // 2 + 5, ch // 2 + 5, anchor=tk.CENTER,
                                image=img, tags="preview")
        except tk.TclError:
            pass

    # ---- Partition Explorer: extract ---------------------------------

    def _pex_extract_selected(self):
        if self._pex_busy or self._pex_card is None:
            return
        sel = self._pex_tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid in self._pex_dirs:
            out_dir = filedialog.askdirectory(
                title="Choose a folder to extract this directory into")
            if out_dir:
                self._pex_run_extract("dir", iid, out_dir,
                                      self._pex_extract_btn)
        else:
            out = filedialog.asksaveasfilename(
                title="Extract file as…",
                initialfile=(os.path.basename(iid) or "file"))
            if out:
                self._pex_run_extract("file", iid, out,
                                      self._pex_extract_btn)

    def _pex_extract_partition(self):
        if self._pex_busy or self._pex_part_index is None:
            return
        out_dir = filedialog.askdirectory(
            title="Choose a folder to extract the whole partition into")
        if out_dir:
            # Land under "<dest>\sdaN", not a generic "root" — two partitions
            # extracted into one folder used to mix together there (a tester
            # batch 10); the folder name matches the combo's device-style
            # partition label (batch 14).
            self._pex_run_extract(
                "dir", "/", out_dir, self._pex_extract_part_btn,
                top_name="sda%d" % (self._pex_part_index + 1))

    def _pex_extract_all(self):
        """Extract every browsable partition into its own ``sdaN`` subfolder
        of one chosen destination — the one-click dump-the-whole-card flow
        (feedback batch 14)."""
        if self._pex_busy or self._pex_card is None:
            return
        parts = [p for p in self._pex_part_labels.values() if p.browsable]
        parts.sort(key=lambda p: p.index)
        if not parts:
            return
        out_dir = filedialog.askdirectory(
            title="Choose a folder to extract all partitions into")
        if out_dir:
            self._pex_run_extract("all", parts, out_dir,
                                  self._pex_extract_all_btn)

    def _pex_on_tree_right(self, event):
        tree = self._pex_tree
        row = tree.identify_row(event.y)
        if not row or row.endswith(_PEX_PLACEHOLDER):
            return
        tree.selection_set(row)
        menu = tk.Menu(tree, tearoff=0)
        c = THEMES.get(self._current_theme, {})
        try:
            menu.configure(
                background=c.get("field_bg"), foreground=c.get("fg"),
                activebackground=c.get("select_bg"),
                activeforeground="#ffffff")
        except tk.TclError:
            pass
        menu.add_command(label="Properties…",
                         command=lambda r=row: self._pex_show_properties(r))
        menu.add_command(
            label="Copy path",
            command=lambda r=row: (self._tk_root().clipboard_clear(),
                                   self._tk_root().clipboard_append(r)))
        if not self._pex_busy:
            menu.add_separator()
            menu.add_command(label="Extract…",
                             command=self._pex_extract_selected)
            if row not in self._pex_dirs:
                menu.add_command(
                    label="Replace with…",
                    command=lambda r=row: self._pex_replace_selected(r))
        menu.tk_popup(event.x_root, event.y_root)

    def _pex_show_properties(self, iid):
        """Small read-only Properties view: the file's full on-card path (the
        path it has when the partition is mounted — for lining PAD edits up
        with hand-mount workflows), device-style partition, size and type.
        Folders get their recursive size, computed on a worker (batch 10
        wishlist: folder sizes)."""
        import threading
        dev = ("sda%d" % (self._pex_part_index + 1)
               if self._pex_part_index is not None else "?")
        try:
            size = self._pex_tree.set(iid, "size")
            ftype = self._pex_tree.set(iid, "type")
        except tk.TclError:
            size = ftype = ""
        is_dir = iid in self._pex_dirs
        kind = "Folder" if is_dir else (ftype or "File")

        def _show(size_line):
            lines = ["Name:       %s" % (os.path.basename(iid) or iid),
                     "Kind:       %s" % kind]
            if size_line:
                lines.append("Size:       %s" % size_line)
            lines += ["Partition:  %s" % dev,
                      "Path:       %s" % iid,
                      "Mounted at: <mount point>%s" % iid]
            # What PAD has already done to this file on this image — the point
            # of a per-file history being "keep track of all changes" (batch
            # 30), including what each swap came from.
            for ev in self._pex_replace_history(iid):
                lines.append("Replaced:   %s" % ev)
            messagebox.showinfo("Properties — %s"
                                % (os.path.basename(iid) or iid),
                                "\n".join(lines))

        if not is_dir:
            _show(size)
            return
        # Recursive folder size on a worker (a deep tree walk over a network
        # image shouldn't freeze Tk); the dialog opens when it lands.
        card, part = self._pex_card, self._pex_part_index
        self._pex_action_status.configure(text="Sizing %s…"
                                          % (os.path.basename(iid) or iid))

        def _work():
            try:
                n, b = card.dir_stats(part, iid)
                line = "%s in %d file%s" % (self._pex_human(b), n,
                                            "" if n == 1 else "s")
            except Exception as e:
                line = "(unavailable: %s)" % e

            def _done():
                self._pex_action_status.configure(text="")
                _show(line)
            try:
                self._tk_root().after(0, _done)
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _pex_replace_history(self, card_path):
        """Human lines for every replace PAD has made to *card_path* on the
        open image, oldest first (``[]`` when it hasn't touched it)."""
        from ..core import card_edits
        out = []
        part = self._pex_part_index
        for e in card_edits.edits_for(self._pex_image_path):
            if e.get("path") != card_path:
                continue
            if (part is not None and e.get("partition") is not None
                    and e.get("partition") != part):
                continue
            sizes = ""
            old, new = e.get("old_size"), e.get("new_size")
            if isinstance(old, int) and isinstance(new, int):
                sizes = " (%s → %s)" % (self._pex_human(old),
                                        self._pex_human(new))
            src = e.get("source") or ""
            out.append("%s%s%s" % (e.get("when") or "?", sizes,
                                   ("\n            from " + src) if src else ""))
        return out

    def _pex_replace_selected(self, iid):
        """Right-click → Replace with…: write one file into the card image,
        with the Spike 2 .sidx record refreshed (the a tester wishlist item
        this whole tab started from).

        A same-size file goes into its existing slot; a different-size one is
        resized on the card by the ext4 driver, which is a bigger deal (it
        moves blocks, and needs WSL2) — so the confirmation says which of the
        two is about to happen and what it costs.
        """
        if self._pex_busy or self._pex_card is None or iid in self._pex_dirs:
            return
        try:
            cur_size = self._pex_card.file_size(self._pex_part_index, iid)
        except Exception:
            cur_size = None
        src = filedialog.askopenfilename(
            title="Replace %s" % (os.path.basename(iid) or iid),
            initialdir=self.last_browse_dir("pex_replace"))
        if not src:
            return
        self.remember_browse_dir("pex_replace", src)
        try:
            new_size = os.path.getsize(src)
        except OSError:
            new_size = None
        if cur_size is None or new_size is None or new_size == cur_size:
            note = ("The file's validation record is refreshed "
                    "automatically.")
        else:
            note = (
                "This file is a different size (%s → %s), so it is %s on the "
                "card: the card image is mounted through the Linux filesystem "
                "driver (WSL2) and the file's blocks are re-allocated, exactly "
                "like a full-size video replacement. Its validation record — "
                "digests AND stored size — is refreshed automatically."
                % (self._pex_human(cur_size), self._pex_human(new_size),
                   "grown" if new_size > cur_size else "shrunk"))
        if not messagebox.askyesno(
                "Replace on card",
                "This WRITES to the card image:\n\n  %s\n\nreplacing\n\n"
                "  %s  (%s)\n\nwith\n\n  %s\n\n%s  Keep a backup of the image "
                "if it's precious.\n\nReplace it?"
                % (os.path.normpath(self.partition_image_var.get() or ""),
                   iid,
                   self._pex_human(cur_size) if cur_size is not None
                   else "size unknown",
                   os.path.normpath(src), note),
                icon="warning"):
            return
        self._pex_run_replace(iid, src, cur_size)

    def _pex_run_replace(self, iid, src, cur_size=None):
        """Worker-thread replace with the shared busy overlay.  No mid-run
        Cancel: the extent writes are quick, and a resize is one ``cp`` under
        the kernel's own driver — interrupting either is worse than finishing
        it.

        The worker never touches Tk, so the ext4 driver's progress lines are
        buffered and appended to the log when the run lands."""
        import threading
        self._pex_busy = True
        part = self._pex_part_index
        image_path = self._pex_image_path
        state = {"note": "", "done": None, "log": []}
        for b in (self._pex_extract_btn, self._pex_extract_part_btn,
                  self._pex_extract_all_btn):
            b.config(state=tk.DISABLED)
        self._pex_action_status.configure(text="")
        self.append_log("Replacing %s on partition sda%s…"
                        % (iid, (part + 1) if part is not None else "?"),
                        "info")
        self._pex_busy_lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        def _work():
            try:
                from ..plugins.stern.explorer import CardImage
                with CardImage(image_path) as c:
                    n, refreshed = c.replace_file(
                        part, iid, src, allow_resize=True,
                        log=lambda m, lvl="info": state["log"].append((m, lvl)))
                state["n"] = n
                resized = ""
                if cur_size is not None and n != cur_size:
                    resized = (" — %s on the card from %s"
                               % ("grown" if n > cur_size else "shrunk",
                                  self._pex_human(cur_size)))
                state["done"] = (
                    "Replaced %s (%s)%s%s." % (
                        iid, self._pex_human(n), resized,
                        ", validation record refreshed" if refreshed
                        else "; not in the validation manifest — no record "
                             "to refresh"))
            except Exception as e:
                state["done"] = "Replace failed: %s" % e

        def _tick(i):
            if state["done"] is not None:
                msg = state["done"]
                for line, lvl in state["log"]:
                    self.append_log(line, lvl)
                self._pex_finish_extract(msg)
                if not msg.startswith("Replace failed"):
                    # Remember the swap against this image BEFORE re-opening:
                    # the reopen rebuilds the tree, and the Changed column is
                    # filled from this journal (core.card_edits).  It is also
                    # what stops the "source image changed — re-run Extract"
                    # banner firing on an edit PAD just made itself.
                    from ..core import card_edits
                    card_edits.record_replace(
                        image_path, part, iid, cur_size,
                        state.get("n"), src)
                    self._pex_report_extract_impact(image_path, iid)
                    # Re-open the card so the browse handle, preview and any
                    # cached reads see the new bytes.  That reselects the
                    # partition, which blanks the status line — so put the
                    # result back afterwards, or the one operation on this tab
                    # that WRITES is the only one to report nothing.
                    self._pex_open_image()
                    self._pex_action_status.configure(text=msg)
                return
            frame = self._SCAN_SPINNER[i % len(self._SCAN_SPINNER)]
            try:
                self._pex_busy_lbl.configure(text="%s  Replacing…" % frame)
                self._tk_root().after(90, _tick, i + 1)
            except tk.TclError:
                pass

        threading.Thread(target=_work, daemon=True).start()
        _tick(0)

    def _pex_report_extract_impact(self, image_path, card_path):
        """Say in the log whether a just-finished Replace makes the open
        extract stale.

        Replacing a file on the card moves the image's mtime, and the asset
        tabs' banner used to read that as "your extract is out of date, re-run
        Extract" — for a file (``/usr/local/spike/SternLogo.png`` on the OS
        partition) that no extracted asset came from.  The banner knows better
        now (core.extract_source); this puts the same verdict in the log at the
        moment of the write, where the user is looking.
        """
        from ..core import card_paths, extract_source
        assets = (self.write_assets_var.get() or "").strip()
        if not assets:
            return
        rec = extract_source.read_extract_source(assets) or {}
        recorded = rec.get("input_path") or ""
        if (not recorded or os.path.normcase(os.path.abspath(recorded))
                != os.path.normcase(os.path.abspath(image_path))):
            return                  # a different image than the extract's
        if card_paths.is_extract_source(assets, card_path):
            self.append_log(
                "This image is where %s was extracted from, and %s is one of "
                "the files those assets came from — re-run Extract so the "
                "Replace tabs match the card."
                % (os.path.basename(assets), card_path), "warning")
        else:
            self.append_log(
                "This image is where %s was extracted from, but %s is not one "
                "of the files those assets came from — no re-Extract needed."
                % (os.path.basename(assets), card_path), "info")

    def _pex_do_extract(self, kind, path, dest, part=None, image_path=None,
                        tree_prog=None, file_prog=None, chunk_prog=None,
                        top_name=None):
        """Synchronous extract over a FRESH card handle (isolated from the
        browse handle so a long extract can't race the tree's reads) — runs on
        the worker thread and never touches Tk.  *part*/*image_path* are
        snapshotted at click time so switching partition or image mid-extract
        can't redirect the run.  Returns a human result string."""
        from ..plugins.stern.explorer import CardImage
        part = self._pex_part_index if part is None else part
        image_path = image_path or self._pex_image_path
        with CardImage(image_path) as c:
            if kind == "file":
                n = c.extract_file(part, path, dest, progress=file_prog)
                return "Extracted %s (%s)." % (os.path.basename(dest),
                                               self._pex_human(n))
            if kind == "all":
                # *path* = list of browsable Partitions; each lands in its
                # own device-named subfolder of *dest*.
                nf = nb = 0
                for p in path:
                    f_, b_ = c.extract_tree(
                        p.index, "/", dest, progress=tree_prog,
                        chunk_progress=chunk_prog,
                        top_name="sda%d" % (p.index + 1))
                    nf += f_; nb += b_
                return ("Extracted %d partition%s — %d file%s (%s) to %s." % (
                    len(path), "" if len(path) == 1 else "s",
                    nf, "" if nf == 1 else "s", self._pex_human(nb),
                    os.path.normpath(dest)))
            nf, nb = c.extract_tree(part, path, dest, progress=tree_prog,
                                    chunk_progress=chunk_prog,
                                    top_name=top_name)
            shown = os.path.normpath(
                os.path.join(dest, top_name) if top_name else dest)
            return "Extracted %d file%s (%s) to %s." % (
                nf, "" if nf == 1 else "s", self._pex_human(nb), shown)

    def _pex_run_extract(self, kind, path, dest, btn, top_name=None):
        """Extract on a worker thread with a live Cancel.

        The worker NEVER touches Tk: cross-thread ``after(0, ...)`` raises
        "main thread is not in main loop" whenever the main thread is busy,
        and one raise kills the worker (see _run_probe_pass).  Instead the
        worker reports through a plain dict that a main-thread after()-loop
        polls — the same loop animates the big spinner overlay."""
        import threading
        self._pex_busy = True
        cancel = threading.Event()
        self._pex_cancel = cancel
        self._pex_cancel_btn = btn
        part = self._pex_part_index          # snapshot against mid-run switches
        image_path = self._pex_image_path
        state = {"note": "", "done": None}   # worker → poll-loop mailbox

        def _check_cancel():
            if cancel.is_set():
                raise _PexCancelled()

        def _tree_prog(nf, nb, _rel):        # per extracted file
            _check_cancel()
            state["note"] = "%d file%s (%s)" % (
                nf, "" if nf == 1 else "s", self._pex_human(nb))

        def _file_prog(written, size):       # per chunk of a single file
            _check_cancel()
            state["note"] = "%s / %s" % (self._pex_human(written),
                                         self._pex_human(size))

        def _work():
            try:
                msg = self._pex_do_extract(
                    kind, path, dest, part, image_path,
                    tree_prog=_tree_prog, file_prog=_file_prog,
                    chunk_prog=lambda _w, _s: _check_cancel(),
                    top_name=top_name)
            except _PexCancelled:
                msg = "Extract cancelled — partial files may remain."
            except Exception as e:
                msg = "Extract failed: %s" % e
            state["done"] = msg

        # The launching button flips to a live Cancel; the others wait.
        # Plain "Cancel" — the ✕ glyph read as inconsistent with every other
        # button (feedback batch 10, same call as the scan buttons got).
        for b in (self._pex_extract_btn, self._pex_extract_part_btn,
                  self._pex_extract_all_btn):
            if b is not btn:
                b.config(state=tk.DISABLED)
        btn.config(text="Cancel", state=tk.NORMAL,
                   command=self._pex_cancel_extract, style="Danger.TButton")
        self._pex_action_status.configure(text="")
        # normpath: Tk's pickers hand back forward-slash paths that turned
        # into mixed-slash log lines on Windows, which couldn't be pasted
        # into Explorer (feedback batch 14).
        what = ("all %d partitions" % len(path) if kind == "all"
                else top_name if top_name
                else "%s from partition %s" % (path, part))
        self.append_log("Extracting %s to %s…"
                        % (what, os.path.normpath(dest)), "info")
        self._pex_busy_lbl.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        threading.Thread(target=_work, daemon=True).start()
        self._pex_extract_tick(state, 0)

    def _pex_cancel_extract(self):
        cancel = getattr(self, "_pex_cancel", None)
        if cancel is not None:
            cancel.set()
        # The worker notices at its next progress tick; freeze the button so
        # a second click can't do anything.
        try:
            self._pex_cancel_btn.config(text="Cancelling…",
                                        state=tk.DISABLED)
        except tk.TclError:
            pass

    def _pex_extract_tick(self, state, i):
        """Main-thread poll loop while an extract runs: animates the spinner
        overlay with the worker's latest progress note and lands its result."""
        if state["done"] is not None:
            self._pex_finish_extract(state["done"])
            return
        frame = self._SCAN_SPINNER[i % len(self._SCAN_SPINNER)]
        note = state["note"]
        try:
            self._pex_busy_lbl.configure(text="%s  Extracting…%s" % (
                frame, ("  " + note) if note else ""))
            self._tk_root().after(90, self._pex_extract_tick, state, i + 1)
        except tk.TclError:
            pass                             # window torn down mid-extract

    def _pex_finish_extract(self, msg):
        self._pex_busy = False
        self._pex_busy_lbl.place_forget()
        self._pex_extract_btn.config(
            text="Extract Selected", command=self._pex_extract_selected,
            style="Go.TButton",
            state=(tk.NORMAL if self._pex_tree.selection() else tk.DISABLED))
        self._pex_extract_part_btn.config(
            text="Extract Whole Partition",
            command=self._pex_extract_partition, style="Go.TButton",
            state=(tk.NORMAL if self._pex_part_index is not None
                   else tk.DISABLED))
        self._pex_extract_all_btn.config(
            text="Extract All Partitions", command=self._pex_extract_all,
            style="Go.TButton",
            state=(tk.NORMAL if any(
                q.browsable for q in self._pex_part_labels.values())
                else tk.DISABLED))
        self._pex_action_status.configure(text=msg)
        self.append_log(
            msg, "error" if ("failed" in msg.split(":")[0].lower())
            else "info")

    # ---- Partition Explorer: lifecycle -------------------------------

    def _pex_close_card(self):
        if self._pex_card is not None:
            try:
                self._pex_card.close()
            except Exception:
                pass
        self._pex_card = None
        self._pex_part_index = None
        self._clear_pex_tree()

    def _clear_pex_tree(self):
        self._pex_tree.delete(*self._pex_tree.get_children(""))
        self._pex_dirs.clear()
        self._pex_populated.clear()
        self._pex_preview_seq += 1          # drop any in-flight image render
        self._pex_set_preview("")
        self._pex_extract_btn.config(state=tk.DISABLED)
        self._pex_extract_part_btn.config(state=tk.DISABLED)
        self._pex_extract_all_btn.config(state=tk.DISABLED)
        self._pex_find_btn.config(state=tk.DISABLED)
        self._pex_search_cache = None
        self._pex_search_state = ("", -1)

    @staticmethod
    def _pex_human(n):
        size = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return ("%d %s" % (int(size), unit) if unit == "B"
                        else "%.1f %s" % (size, unit))
            size /= 1024.0

    # ==================================================================
    # Settings tab — preset the game firmware's compiled operator-adjustment
    # DEFAULTS (free play, volume, pricing, …) inside a card image.  These
    # apply on a fresh flash / factory reset; a configured machine keeps its
    # board-NVRAM values (settings aren't on the card).  Composes
    # plugins.stern.explorer (find/read/patch game_real + sidx refresh) and
    # plugins.stern.adjustments (decode the table).  A tester wishlist #2.
    # ==================================================================

    def _build_settings_tab(self):
        f = self._tab_settings
        self._settings_image_path = None
        self._settings_part = None
        self._settings_fw_path = None
        self._settings_table = None
        self._settings_busy = False
        self._settings_loading = False   # True while the form is being filled
        self._settings_stage_job = None  # debounced auto-stage timer id
        self._settings_log_job = None    # debounced "say what changed" timer
        # Field state as of the last log line — None until a card is loaded,
        # which is how the first look adopts what's already staged in silence
        # (see _settings_flush_log).
        self._settings_logged = None
        self._settings_rows = []          # [{name,label,kind,var,default,min,max}]
        # Factory high-score board (plugins.stern.high_scores) + its per-slot
        # initials/name entry vars — batch 22.  None when this build's table
        # can't be located; the tab then edits scores only, as before.
        self._settings_hstd = None
        self._settings_hstd_vars = []
        self.settings_image_var = tk.StringVar()

        # Batch 21: the explainer paragraph moved into Help, and the card
        # image is a read-only mirror of the Extract tab's master image —
        # the tab always edits the project's card, like every other tab.
        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(row, text="Card Image:", width=12, anchor=tk.W).pack(
            side=tk.LEFT)
        mirror = ttk.Label(row, textvariable=self.settings_image_var,
                           anchor=tk.W)
        mirror.pack(side=tk.LEFT, fill=tk.X, expand=True)
        _Tooltip(mirror, "The master card image these defaults are read "
                         "from — it is set on the Extract tab.",
                 lambda: self._current_theme)

        # Preset bar: save a set of defaults once and reuse (or auto-apply) it
        # so a user never has to revisit this tab for every card.
        self.settings_preset_var = tk.StringVar()
        self.settings_autoapply_var = tk.BooleanVar()
        prow = ttk.Frame(f); prow.pack(fill=tk.X, padx=10, pady=(0, 4))
        ttk.Label(prow, text="Preset:", width=12, anchor=tk.W).pack(
            side=tk.LEFT)
        self._settings_preset_combo = ttk.Combobox(
            prow, textvariable=self.settings_preset_var, state="readonly",
            width=22, values=[])
        self._settings_preset_combo.pack(side=tk.LEFT)
        self._settings_preset_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._settings_load_preset(self.settings_preset_var.get()))
        ttk.Button(prow, text="Save As…",
                   command=self._settings_save_preset).pack(
            side=tk.LEFT, padx=(6, 0))
        self._settings_preset_del_btn = ttk.Button(
            prow, text="Delete", command=self._settings_delete_preset)
        self._settings_preset_del_btn.pack(side=tk.LEFT, padx=(6, 0))
        # The checkbox marks WHICH saved preset is the standing default —
        # it's an attribute of the selected preset, not a parallel feature,
        # so its label says so and it stays greyed until a preset exists
        # (a tester saw the two as overlapping).
        self._settings_auto_cb = ttk.Checkbutton(
            prow, text="Apply this preset automatically to every card I build",
            variable=self.settings_autoapply_var,
            command=self._settings_auto_toggle)
        self._settings_auto_cb.pack(side=tk.LEFT, padx=(16, 0))
        _Tooltip(
            self._settings_auto_cb,
            "When on, the selected preset's defaults are baked into every "
            "card you build on the Write tab automatically — only the "
            "settings a given game actually has are applied, so one preset "
            "works across titles. Save a preset first to enable this.",
            lambda: self._current_theme)

        # Scrollable form of one row per exposed setting.  The canvas hugs the
        # form's height (capped) instead of expanding into a sea of blank
        # space below the rows (feedback batch 21) — the freed height flows
        # to the Log pane via _resize_notebook_to_current_tab.
        body = ttk.Frame(f); body.pack(fill=tk.X, padx=10, pady=(4, 4))
        self._settings_canvas = tk.Canvas(
            body, highlightthickness=0, bd=0, height=60,
            bg=THEMES.get(self._current_theme, {}).get("bg", "#2d2d2d"))
        sb = ttk.Scrollbar(body, orient="vertical",
                           command=self._settings_canvas.yview)
        self._settings_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._settings_form = ttk.Frame(self._settings_canvas)
        self._settings_form_win = self._settings_canvas.create_window(
            (0, 0), window=self._settings_form, anchor="nw")
        self._settings_form.bind(
            "<Configure>", lambda e: self._settings_canvas.configure(
                scrollregion=self._settings_canvas.bbox("all"),
                height=min(e.height, 520)))
        self._settings_canvas.bind(
            "<Configure>", lambda e: self._settings_canvas.itemconfigure(
                self._settings_form_win, width=e.width))
        self._settings_empty = ttk.Label(
            self._settings_form,
            text="Set the card image on the Extract tab to edit its default "
                 "settings.",
            foreground="#888888")
        self._settings_empty.grid(row=0, column=0, padx=6, pady=20, sticky="w")

        # Every setting the firmware carries, flagged with whether the
        # machine's own menu can reach it (a tester).  The form above is the
        # curated set with friendly units and help; this is everything else,
        # editable by double-click since a tester asked to set the hidden and
        # debug ones too.  It lives outside the scrolling canvas so it scrolls
        # itself instead of nesting two scroll regions.
        self._settings_all_frame = ttk.Frame(f)
        hdr = ttk.Frame(self._settings_all_frame)
        hdr.pack(fill=tk.X, padx=10, pady=(8, 2))
        title = ttk.Label(hdr, text="All settings on this image",
                          font=(_SANS_FONT, 10, "bold"))
        title.pack(side=tk.LEFT)
        _Tooltip(title,
                 "Every adjustment the firmware carries, with the caption the "
                 "machine itself prints. Double-click one to set the default "
                 "it ships with — including the ones the machine's menus "
                 "never show.",
                 lambda: self._current_theme)
        self._settings_hidden_only = tk.BooleanVar(value=False)
        self._settings_hidden_cb = ttk.Checkbutton(
            hdr, text="Only settings not in the Adjustments menu",
            variable=self._settings_hidden_only,
            command=self._settings_fill_all_tree)
        self._settings_hidden_cb.pack(side=tk.LEFT, padx=(16, 0))
        _Tooltip(self._settings_hidden_cb,
                 "Leaves the settings the machine's Adjustments menu can't "
                 "reach: the ones it edits on another service screen, and the "
                 "factory/debug ones it never shows at all.",
                 lambda: self._current_theme)
        # Widening the operator menu so the machine SHOWS its debug settings —
        # a firmware code patch, so it is its own deliberate action rather
        # than something a value edit does behind the user's back.
        self._settings_menu_btn = ttk.Button(
            hdr, text="Show hidden settings in the machine's menu…",
            command=self._settings_menu_dialog, state=tk.DISABLED)
        self._settings_menu_btn.pack(side=tk.RIGHT)
        _Tooltip(self._settings_menu_btn,
                 "Extends the machine's Feature Adjustments page so the "
                 "settings below can be found and changed on the machine "
                 "itself, instead of only being preset from here.",
                 lambda: self._current_theme)
        tbody = ttk.Frame(self._settings_all_frame)
        tbody.pack(fill=tk.BOTH, expand=True, padx=10)
        self._settings_all_tree = ttk.Treeview(
            tbody, columns=("value", "new", "range", "status"), height=12,
            selectmode="browse")
        self._settings_all_tree.heading("#0", text="Setting", anchor=tk.W)
        self._settings_all_tree.heading("value", text="On card", anchor=tk.W)
        self._settings_all_tree.heading("new", text="New default", anchor=tk.W)
        self._settings_all_tree.heading("range", text="Range", anchor=tk.W)
        self._settings_all_tree.heading("status", text="Menu", anchor=tk.W)
        self._settings_all_tree.column("#0", width=320, minwidth=180)
        self._settings_all_tree.column("value", width=130, minwidth=80,
                                       stretch=False)
        self._settings_all_tree.column("new", width=130, minwidth=80,
                                       stretch=False)
        self._settings_all_tree.column("range", width=150, minwidth=80,
                                       stretch=False)
        self._settings_all_tree.column("status", width=130, minwidth=90,
                                       stretch=False)
        self._settings_all_tree.bind("<Double-1>", self._settings_all_edit)
        self._settings_all_tree.bind("<Return>", self._settings_all_edit)
        avs = ttk.Scrollbar(tbody, orient="vertical",
                            command=self._settings_all_tree.yview)
        self._settings_all_tree.configure(yscrollcommand=avs.set)
        self._settings_all_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        avs.pack(side=tk.LEFT, fill=tk.Y)
        self._settings_all_legend = ttk.Label(
            self._settings_all_frame, text="", foreground="#888888",
            font=(_SANS_FONT, 8))
        self._settings_all_legend.pack(fill=tk.X, padx=10, pady=(2, 0))
        self._settings_all_rows = []
        self._settings_all_items = {}     # tree item id -> its row
        # menu_visibility.widen_plan for the loaded image (None = this build's
        # menu can't be widened, or has nothing hidden to expose).
        self._settings_menu_plan = None

        # Changes stage themselves as you edit (batch 21 — the explicit
        # Apply / Clear buttons are gone); Reset Fields is the one action:
        # back to the image's own defaults, nothing staged.
        arow = ttk.Frame(f); arow.pack(fill=tk.X, padx=10, pady=(0, 8))
        self._settings_arow = arow
        self._settings_reset_btn = ttk.Button(
            arow, text="Reset Fields", command=self._settings_reset,
            state=tk.DISABLED)
        self._settings_reset_btn.pack(side=tk.LEFT)
        _Tooltip(
            self._settings_reset_btn,
            "Put every field back to the image's current defaults and clear "
            "anything staged for the next Build.",
            lambda: self._current_theme)
        self._settings_status = ttk.Label(arow, text="",
                                          font=(_SANS_FONT, 9))
        self._settings_status.pack(side=tk.LEFT, padx=(10, 0))
        self._settings_refresh_presets()

    # ---- Default Settings: presets ----------------------------------
    def _presets_blob(self):
        b = self._default_presets
        b.setdefault("presets", {})
        b.setdefault("active", None)
        return b

    def _settings_persist_presets(self):
        if self._on_default_presets_change:
            self._on_default_presets_change(self._presets_blob())

    def _settings_refresh_presets(self):
        b = self._presets_blob()
        names = sorted(b["presets"])
        self._settings_preset_combo["values"] = names
        active = b.get("active")
        # Reflect the active/auto preset in the dropdown + checkbox.
        if active in b["presets"]:
            self.settings_preset_var.set(active)
            self.settings_autoapply_var.set(True)
        else:
            if self.settings_preset_var.get() not in names:
                self.settings_preset_var.set("")
            self.settings_autoapply_var.set(False)
        self._settings_update_auto_cb()

    def _settings_update_auto_cb(self):
        """Auto-apply is a property of the SELECTED preset — grey the
        checkbox out until one is selected so it can't read as an
        independent feature."""
        cb = getattr(self, "_settings_auto_cb", None)
        if cb is None:
            return
        ok = self.settings_preset_var.get() in self._presets_blob()["presets"]
        try:
            cb.state(["!disabled"] if ok else ["disabled"])
        except tk.TclError:
            pass

    def _settings_load_preset(self, name):
        self._settings_update_auto_cb()
        vals = self._presets_blob()["presets"].get(name)
        if not vals or not self._settings_rows:
            return
        for r in self._settings_rows:
            if r["name"] in vals:
                # Preset holds internal units; show them in display units.
                self._settings_set_row(
                    r, int(vals[r["name"]]) // r.get("scale", 1))
        self._settings_status.configure(
            text="Loaded preset \"%s\"." % name)

    def _settings_save_preset(self):
        if not self._settings_rows:
            messagebox.showinfo(
                "Save preset", "Load a card image first, then set the values "
                "you want to save as a preset.")
            return
        name = self._ask_text(
            "Save preset", "Name this preset (e.g. \"My route\"):")
        if not name or not name.strip():
            return
        name = name.strip()
        # Store INTERNAL values (display * scale) so a preset means the same
        # thing across titles and the build-time auto-apply writes it directly.
        vals = {r["name"]: int(r["var"].get()) * r.get("scale", 1)
                for r in self._settings_rows}
        self._presets_blob()["presets"][name] = vals
        self.settings_preset_var.set(name)
        self._settings_persist_presets()
        self._settings_refresh_presets()
        self._settings_status.configure(
            text="Saved preset \"%s\" (%d settings)." % (name, len(vals)))

    def _settings_delete_preset(self):
        name = self.settings_preset_var.get()
        b = self._presets_blob()
        if name not in b["presets"]:
            return
        if not messagebox.askyesno("Delete preset",
                                   "Delete preset \"%s\"?" % name):
            return
        del b["presets"][name]
        if b.get("active") == name:
            b["active"] = None
        self.settings_preset_var.set("")
        self._settings_persist_presets()
        self._settings_refresh_presets()
        self._settings_status.configure(text="Deleted preset \"%s\"." % name)

    def _settings_auto_toggle(self):
        b = self._presets_blob()
        name = self.settings_preset_var.get()
        if self.settings_autoapply_var.get():
            if name not in b["presets"]:
                messagebox.showinfo(
                    "Auto-apply", "Pick or save a preset first, then tick this "
                    "to bake it into every card you build.")
                self.settings_autoapply_var.set(False)
                return
            b["active"] = name
            self._settings_status.configure(
                text="\"%s\" will be applied to every card you build." % name)
        else:
            b["active"] = None
        self._settings_persist_presets()

    def _settings_open_image(self):
        path = (self.settings_image_var.get() or "").strip()
        if not path or not os.path.isfile(path) or self._settings_busy:
            return
        self._settings_busy = True
        self._settings_menu_plan = None
        self._settings_clear_form()
        # Same big animated indicator the Replace tabs' scans use, so the
        # (possibly slow, NAS-bound) firmware read never looks idle
        # (a tester asked for the swirl here).
        self._settings_empty.grid()
        try:
            self._scan_empty_font.setdefault(
                "settings", str(self._settings_empty.cget("font")))
            self._settings_empty.configure(font=(_SANS_FONT, 18, "bold"))
        except tk.TclError:
            pass
        self._scan_msgs["settings"] = "Reading the image's firmware…"
        self._start_scan_spinner("settings")
        self._settings_status.configure(text="")
        self._settings_reset_btn.config(state=tk.DISABLED)
        import threading
        state = {"done": None}

        def _work():
            try:
                from ..plugins.stern.explorer import CardImage
                from ..plugins.stern.adjustments import all_rows, curated_rows
                from ..plugins.stern.menu_visibility import (statuses,
                                                             widen_plan)
                with CardImage(path) as c:
                    table, part, fw = c.adjustment_table()
                    elf = c.read_firmware(part, fw)
                # Which settings the machine's own menu can reach.  Best-effort
                # by design: a build whose menu can't be read still gets the
                # list and the editor, just without the flags (never with
                # wrong ones).
                try:
                    menu = statuses(table)
                except Exception:
                    menu = {}
                # ...and whether that menu can be widened to reach the hidden
                # ones.  Same read of the same pages, so it costs nothing extra
                # and is equally refused on a build that wasn't fully read.
                try:
                    plan = widen_plan(table)
                except Exception:
                    plan = None
                rows = curated_rows(table, menu)
                try:
                    every = all_rows(table, menu)
                except Exception:
                    every = []
                # The factory high-score board (initials + player names) is a
                # separate table in the same ELF — batch 22.  Best-effort: a
                # build we can't locate it in still gets the scores-only
                # editor it had before.
                try:
                    from ..plugins.stern.high_scores import HighScoreDefaults
                    hstd = HighScoreDefaults(elf, table)
                except Exception:
                    hstd = None
                state["done"] = ("ok", table, part, fw, rows, path, hstd,
                                 every, plan)
            except Exception as e:
                state["done"] = ("err", e)

        def _poll():
            if state["done"] is None:
                try:
                    self._tk_root().after(120, _poll)
                except tk.TclError:
                    pass
                return
            self._settings_busy = False
            # Firmware read over — stop the swirl and put the empty label's
            # normal font back before any (small) message goes into it.
            self._stop_scan_spinner("settings")
            try:
                self._settings_empty.configure(
                    font=self._scan_empty_font.get("settings", ""))
            except tk.TclError:
                pass
            res = state["done"]
            # The Card Image box changed while this load ran (a dropped
            # request) — reload so the form never shows one card's values
            # under another card's path.
            live = (self.settings_image_var.get() or "").strip()
            if live and live != path:
                self._settings_open_image()
                return
            if res[0] == "err":
                self._settings_table = None
                self._settings_reset_btn.config(state=tk.DISABLED)
                self._settings_empty.configure(
                    text="Couldn't read settings from this image:\n%s\n\n"
                         "(The Extract tab's card image must be a Stern "
                         "Spike 2 card. Some newer game builds aren't "
                         "decoded yet.)" % res[1])
                self._settings_empty.grid()
                return
            _ok, table, part, fw, rows, ipath, hstd, every, plan = res
            self._settings_table = table
            self._settings_part = part
            self._settings_fw_path = fw
            self._settings_image_path = ipath
            self._settings_hstd = hstd
            self._settings_every = every
            self._settings_menu_plan = plan
            self._settings_build_form(rows)

        threading.Thread(target=_work, daemon=True).start()
        _poll()

    def _settings_clear_form(self):
        # Destroying a focused field fires <FocusOut>, which is one of the
        # things that flushes the staged-edit log — so tearing the form down
        # would narrate the outgoing card on the way out.  The loading flag is
        # what tells the log "these values are not somebody typing".
        was_loading = self._settings_loading
        self._settings_loading = True
        try:
            for w in self._settings_form.winfo_children():
                if w is not self._settings_empty:
                    w.destroy()
        finally:
            self._settings_loading = was_loading
        job, self._settings_log_job = (
            getattr(self, "_settings_log_job", None), None)
        if job is not None:
            try:
                self._tk_root().after_cancel(job)
            except tk.TclError:
                pass
        # A different card's fields are a different conversation — the next
        # flush adopts them silently instead of reporting the old card's
        # edits as if they had just been made.
        self._settings_logged = None
        self._settings_rows = []
        self._settings_hstd_vars = []
        self._settings_all_rows = []
        self._settings_all_items = {}
        # _settings_menu_plan is NOT cleared here: the loader sets it before
        # building the form, and the form is what reads it (same as
        # _settings_every).  It is cleared when a load starts instead.
        try:
            self._settings_menu_btn.config(state=tk.DISABLED)
            self._settings_all_frame.pack_forget()
            self._settings_all_tree.delete(*self._settings_all_tree.get_children())
        except (tk.TclError, AttributeError):
            pass

    # Status -> what the reference list calls it.  "service" is still a real
    # operator setting, just edited on a different service-menu screen, so it
    # must not read as "debug" (see plugins/stern/menu_visibility.py).
    _SETTINGS_STATUS_TEXT = {"": "Adjustments", "service": "Service menu",
                             "debug": "Debug", None: ""}

    def _settings_pending(self):
        """``{AD_name: internal value}`` for every field currently set away
        from the image's own default — whichever editor set it."""
        out = {}
        for r in self._settings_rows:
            try:
                v = int(r["var"].get())
            except (tk.TclError, ValueError):
                continue
            scale = r.get("scale", 1)
            if v != r["default"]:
                out[r["name"]] = v * scale
        return out

    def _settings_all_value_text(self, r, v):
        """A value from the all-settings list, the way the machine shows it."""
        if r["min"] == 0 and r["max"] == 1:
            return "On" if v else "Off"
        if r.get("labels") and v in r["labels"]:
            return "%d - %s" % (v, r["labels"][v])
        return self._settings_fmt_num(v)

    def _settings_fill_all_tree(self):
        """(Re)populate the all-settings list from the last load."""
        tree = self._settings_all_tree
        # An edit refills the whole list, so remember which setting the user
        # was on — losing it would move the selection out from under a second
        # double-click on the same row.
        was = self._settings_all_items.get(tree.focus())
        was = was["name"] if was else None
        keep = None
        tree.delete(*tree.get_children())
        self._settings_all_items = {}
        rows = self._settings_all_rows
        if not rows:
            self._settings_all_legend.configure(text="")
            return
        known = rows[0].get("status") is not None
        only_hidden = bool(self._settings_hidden_only.get())
        pending = self._settings_pending()
        shown = 0
        for r in rows:
            st = r.get("status")
            if only_hidden and st in ("", None):
                continue
            val = self._settings_all_value_text(r, r["default"])
            rng = ("off / on" if r["min"] == 0 and r["max"] == 1
                   else self._settings_range_text(r))
            new = pending.get(r["name"])
            if new == r["default"]:       # a scaled row that round-trips
                new = None
            item = tree.insert(
                "", "end", text="%s  (0x%02X)" % (r["label"], r["id"]),
                values=(val,
                        "" if new is None
                        else self._settings_all_value_text(r, new),
                        rng, self._SETTINGS_STATUS_TEXT.get(st, "")),
                tags=(st or "unknown",))
            self._settings_all_items[item] = r
            if r["name"] == was:
                keep = item
            shown += 1
        if keep:
            tree.focus(keep)
            tree.selection_set(keep)
            tree.see(keep)
        if not known:
            self._settings_all_legend.configure(
                text="%d setting(s) — double-click one to change the default "
                     "it ships with. This build's operator menu couldn't be "
                     "read, so settings hidden from it aren't flagged."
                     % len(rows))
            return
        n_dbg = sum(1 for r in rows if r["status"] == "debug")
        n_svc = sum(1 for r in rows if r["status"] == "service")
        self._settings_all_legend.configure(
            text="%d setting(s)%s — double-click one to change the default it "
                 "ships with. \"Adjustments\" = in the machine's Adjustments "
                 "menu; \"Service menu\" = %d edited on another service screen "
                 "(volume, speakers, software update, tournament, "
                 "redemption); \"Debug\" = %d the machine never shows at all."
                 % (len(rows),
                    ", %d listed" % shown if only_hidden else "",
                    n_svc, n_dbg))

    # ---- Default Settings: editing anything in the all-settings list ----
    # a tester asked to set the values the machine hides as well as read them.
    # The curated form stays the friendly path (display units, help text,
    # presets); this is the long tail, edited one at a time through a dialog
    # rather than 500 live widgets.  An edited row joins _settings_rows like
    # any other, so staging, the log, presets and Reset Fields need no cases.

    def _settings_add_extra_row(self, all_row):
        """Register a setting from the all-settings list as an editable row.

        It has no widget of its own — the list is its editor — and it is in
        the firmware's own internal units, so ``scale`` is 1 and the value
        shown is the value written."""
        labels = all_row.get("labels")
        if all_row["min"] == 0 and all_row["max"] == 1:
            kind = "toggle"
        elif labels:
            kind = "enum"
        else:
            kind = "number"
        row = {"name": all_row["name"], "label": all_row["label"],
               "kind": kind, "help": "", "scale": 1, "labels": labels,
               "group": None, "status": all_row.get("status"),
               "default": all_row["default"], "min": all_row["min"],
               "max": all_row["max"], "step": all_row.get("step") or 1,
               "var": tk.IntVar(value=all_row["default"]), "widget": None,
               "extra": True}
        row["var"].trace_add(
            "write", lambda *_a: self._settings_schedule_autostage())
        self._settings_rows.append(row)
        return row

    def _settings_all_edit(self, _event=None):
        """Double-click / Return on the all-settings list: set that setting's
        default."""
        tree = self._settings_all_tree
        item = ""
        if _event is not None and getattr(_event, "num", 0) == 1:
            item = tree.identify_row(_event.y)      # the row clicked on
        row = self._settings_all_items.get(item or tree.focus())
        if row is None or self._settings_table is None:
            return
        value = self._settings_ask_value(row)
        if value is None:
            return
        existing = next((r for r in self._settings_rows
                         if r["name"] == row["name"]), None)
        if existing is None:
            existing = self._settings_add_extra_row(row)
        self._settings_set_row(existing, int(value) // existing.get("scale", 1))
        self._settings_fill_all_tree()
        # There is no field to leave here, so report it now rather than
        # waiting for a focus change that will never come.
        self._settings_flush_log()

    def _settings_ask_value(self, row):
        """Modal editor for one setting's default.  Returns the new value in
        the firmware's internal units, or None if nothing changed."""
        root = self._tk_root()
        dlg = tk.Toplevel(root)
        dlg.title("Default setting")
        dlg.transient(root)
        dlg.resizable(False, False)
        self._theme_toplevel(dlg)
        ttk.Label(dlg, text="%s  (0x%02X)" % (row["label"], row["id"]),
                  font=(_SANS_FONT, 10, "bold")).pack(
            anchor=tk.W, padx=12, pady=(12, 0))
        ttk.Label(dlg, text=row["name"], foreground="#888888",
                  font=(_SANS_FONT, 8)).pack(anchor=tk.W, padx=12)
        ttk.Label(dlg, text="On card: %s        %s"
                           % (self._settings_all_value_text(row,
                                                            row["default"]),
                              self._settings_range_text(row)),
                  font=(_SANS_FONT, 9)).pack(anchor=tk.W, padx=12, pady=(6, 0))
        note = None
        if row.get("status") == "debug":
            note = ("The machine's menus never show this one, so it can only "
                    "be set from here — unless you also open the menu up to "
                    "it with the button above the list.")
        elif row.get("status") == "service":
            note = ("The machine edits this on a different service screen, "
                    "so what it shows there may not match this default.")
        ttk.Label(dlg, text="A fresh flash or a factory reset picks this up; "
                            "a machine that already has a value keeps it.",
                  foreground="#888888", font=(_SANS_FONT, 8),
                  wraplength=380, justify=tk.LEFT).pack(
            anchor=tk.W, padx=12, pady=(6, 0))
        if note:
            ttk.Label(dlg, text=note, foreground="#888888",
                      font=(_SANS_FONT, 8), wraplength=380,
                      justify=tk.LEFT).pack(anchor=tk.W, padx=12, pady=(4, 0))
        cur = self._settings_pending().get(row["name"], row["default"])
        var = tk.IntVar(value=cur)
        erow = ttk.Frame(dlg)
        erow.pack(fill=tk.X, padx=12, pady=(10, 8))
        ttk.Label(erow, text="New default:").pack(side=tk.LEFT)
        if row["min"] == 0 and row["max"] == 1:
            w = ttk.Checkbutton(erow, variable=var, text="On")
        elif row.get("labels"):
            opts = ["%d - %s" % (v, row["labels"].get(v, v))
                    for v in range(row["min"], row["max"] + 1)]
            w = ttk.Combobox(erow, state="readonly", values=opts, width=22)
            if row["min"] <= cur <= row["max"]:
                w.current(cur - row["min"])
            w.bind("<<ComboboxSelected>>",
                   lambda _e, _w=w: var.set(row["min"] + _w.current()))
        else:
            w = ttk.Spinbox(erow, from_=min(row["min"], row["default"]),
                            to=max(row["max"], row["default"]),
                            textvariable=var,
                            width=max(8, len("%d" % row["max"]) + 1),
                            increment=row.get("step") or 1)
        w.pack(side=tk.LEFT, padx=(8, 0))
        out = []

        def _ok(_e=None):
            try:
                v = int(var.get())
            except (tk.TclError, ValueError):
                return
            out.append(max(row["min"], min(row["max"], v))
                       if v != row["default"] else v)
            dlg.destroy()

        def _card(_e=None):
            out.append(row["default"])
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=12, pady=(0, 12))
        ttk.Button(btns, text="OK", command=_ok,
                   style="Go.TButton").pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=dlg.destroy,
                   style="Danger.TButton").pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(btns, text="Back to card value", command=_card).pack(
            side=tk.LEFT)
        dlg.bind("<Return>", _ok)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        w.focus_set()
        center_over(root, dlg)
        dlg.grab_set()
        root.wait_window(dlg)
        return out[0] if out else None

    # ---- Default Settings: showing hidden settings on the machine -------
    # menu_visibility.widen_plan reads the operator menu's Feature Adjustments
    # page; raising its last id is one instruction and exposes the debug tail
    # above it.  Staged by NAME so a rebuild on another game version can't
    # expose whatever that id happens to mean there.

    def _settings_expose_label(self, name):
        """The machine's caption for a staged expose-through name."""
        for r in self._settings_all_rows:
            if r["name"] == name:
                return r["label"]
        return name

    def staged_menu_expose(self, assets_dir):
        """The ``AD_`` name the machine's Adjustments menu is staged to be
        opened up to, or ``""``.  Read by the app's Write flow after a
        successful build."""
        from ..core import staged_changes
        val = staged_changes.load(assets_dir).get("menu_expose_through")
        return str(val) if isinstance(val, str) and val else ""

    def _settings_stage_menu_expose(self, name):
        """Record (or clear, with ``name=""``) the menu widening."""
        assets_dir = self._settings_staged_dir()
        if not assets_dir:
            self._settings_status.configure(
                text="Set the project folder on the Extract tab first — "
                     "changes stage with the project.")
            return False
        from ..core import staged_changes
        data = staged_changes.load(assets_dir)
        if name:
            data["menu_expose_through"] = name
        elif "menu_expose_through" in data:
            del data["menu_expose_through"]
        else:
            return True
        staged_changes.save(assets_dir, data)
        if self._on_folder_state_written:
            self._on_folder_state_written(assets_dir)
        return True

    def _settings_menu_dialog(self):
        """Pick how far to open the machine's Adjustments menu."""
        plan = self._settings_menu_plan
        if not plan:
            return
        root = self._tk_root()
        cands = plan["candidates"]
        labels = {r["name"]: r["label"] for r in self._settings_all_rows}
        dlg = tk.Toplevel(root)
        dlg.title("Show hidden settings in the machine's menu")
        dlg.transient(root)
        self._theme_toplevel(dlg)
        ttk.Label(dlg, text="Show hidden settings in the machine's menu",
                  font=(_SANS_FONT, 10, "bold")).pack(
            anchor=tk.W, padx=12, pady=(12, 4))
        ttk.Label(
            dlg,
            text="The machine's Feature Adjustments page stops at setting "
                 "0x%02X, which is the only reason the settings below can't be "
                 "reached on the machine. Picking one moves that stopping "
                 "point: everything down to and including your pick becomes "
                 "visible in the Adjustments menu, and can be changed there "
                 "like any other setting.\n\nThe page is a straight run, so "
                 "settings above your pick come with it — you can't skip one."
                 % plan["last"],
            wraplength=520, justify=tk.LEFT).pack(anchor=tk.W, padx=12)
        ttk.Label(
            dlg,
            text="This edits the game's code, not just a value. It has been "
                 "verified against the firmware but not yet on a real "
                 "machine — the settings it exposes include factory test and "
                 "bookkeeping entries the game never expected an operator to "
                 "change.",
            wraplength=520, justify=tk.LEFT, foreground="#c07830",
            font=(_SANS_FONT, 8)).pack(anchor=tk.W, padx=12, pady=(8, 4))
        box = ttk.Frame(dlg)
        box.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 4))
        tree = ttk.Treeview(box, columns=("id",), height=min(10, len(cands)),
                            selectmode="browse")
        tree.heading("#0", text="Show through this setting", anchor=tk.W)
        tree.heading("id", text="Id", anchor=tk.W)
        tree.column("#0", width=380, minwidth=200)
        tree.column("id", width=60, minwidth=50, stretch=False)
        vs = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vs.pack(side=tk.LEFT, fill=tk.Y)
        items = {}
        for c in cands:
            items[tree.insert("", "end",
                              text=labels.get(c["name"], c["name"]),
                              values=("0x%02X" % c["id"],))] = c
        count = ttk.Label(dlg, text="", foreground="#888888",
                          font=(_SANS_FONT, 8))
        count.pack(anchor=tk.W, padx=12)

        def _sel(_e=None):
            c = items.get(tree.focus())
            if c is None:
                count.configure(text="")
                return
            n = sum(1 for x in cands if x["id"] <= c["id"])
            count.configure(
                text="The machine will show %d setting(s) it normally "
                     "hides, ending at \"%s\"."
                     % (n, labels.get(c["name"], c["name"])))
        tree.bind("<<TreeviewSelect>>", _sel)
        staged = self.staged_menu_expose(self._settings_staged_dir())
        pre = next((i for i, c in items.items() if c["name"] == staged), None)
        if pre is None:
            # Default to the last entry that isn't one of the game's internal
            # "…_CHANGED" bookkeeping flags: those are state the game keeps for
            # itself, and stopping before them is the useful default on the
            # titles whose tail ends in a run of them.
            useful = [i for i, c in items.items()
                      if not c["name"].endswith("_CHANGED")]
            pre = useful[-1] if useful else list(items)[-1]
        tree.selection_set(pre)
        tree.focus(pre)
        tree.see(pre)
        _sel()

        def _apply(_e=None):
            c = items.get(tree.focus())
            if c is None:
                return
            if self._settings_stage_menu_expose(c["name"]):
                n = sum(1 for x in cands if x["id"] <= c["id"])
                self.append_log(
                    "Defaults: the machine's Adjustments menu will show %d "
                    "hidden setting(s), through \"%s\" — staged for the next "
                    "Build." % (n, labels.get(c["name"], c["name"])), "info")
                self._settings_status.configure(
                    text="The machine's menu will be opened up to \"%s\" on "
                         "the next Build." % labels.get(c["name"], c["name"]))
            dlg.destroy()

        def _clear(_e=None):
            if self._settings_stage_menu_expose(""):
                if staged:
                    self.append_log(
                        "Defaults: the machine's menu will be left as the "
                        "game ships it.", "info")
                self._settings_status.configure(
                    text="The machine's menu will be left as the game ships "
                         "it.")
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=12, pady=(4, 12))
        ttk.Button(btns, text="Show them", command=_apply,
                   style="Go.TButton").pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=dlg.destroy,
                   style="Danger.TButton").pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(btns, text="Leave the menu alone", command=_clear).pack(
            side=tk.LEFT)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        center_over(root, dlg)
        dlg.grab_set()
        root.wait_window(dlg)

    @staticmethod
    def _settings_fmt_num(v):
        """Group thousands once a value is big enough to be hard to read at a
        glance — high-score defaults run to ten digits (feedback batch 22)."""
        return "{:,}".format(v) if abs(v) >= 100000 else str(v)

    @classmethod
    def _settings_range_text(cls, r):
        """The "Range" cell for a row — ``min - max``, plus a note when the
        card's own default falls outside it.

        Stern does ship those: Led Zeppelin 1.22's ELECTRIC MAGIC FRENZY and
        MULTIBALL champions default to 2,000,000 against a declared minimum of
        5,000,000.  Saying so is the difference between "the app is showing me
        a wrong number" and "the firmware really is like that"."""
        rng = "%s - %s" % (cls._settings_fmt_num(r["min"]),
                           cls._settings_fmt_num(r["max"]))
        if not (r["min"] <= r["default"] <= r["max"]):
            rng += "  (card ships %s, outside its own range)" % (
                cls._settings_fmt_num(r["default"]))
        return rng

    @classmethod
    def _settings_fmt_value(cls, r, v):
        """A row's value the way the operator menu shows it."""
        if r["kind"] == "toggle":
            return "On" if v else "Off"
        if r.get("labels") and v in r["labels"]:
            return "%d - %s" % (v, r["labels"][v])
        return cls._settings_fmt_num(v)

    def _settings_build_form(self, rows):
        self._settings_clear_form()
        # The reference list stands on its own: a build with no *editable*
        # settings still gets it, so "what does this firmware carry?" is always
        # answerable.
        self._settings_all_rows = list(getattr(self, "_settings_every", None)
                                       or [])
        if self._settings_all_rows:
            self._settings_all_frame.pack(fill=tk.BOTH, expand=True,
                                          before=self._settings_arow)
            self._settings_fill_all_tree()
        try:
            self._settings_menu_btn.config(
                state=tk.NORMAL if self._settings_menu_plan else tk.DISABLED)
        except tk.TclError:
            pass
        if not rows:
            # Only the curated form is empty — the all-settings list below it
            # still edits everything this firmware has, so this can't say
            # "no editable settings" and stop.
            self._settings_empty.configure(
                text="None of the settings with friendly units and help are "
                     "in this firmware — use the full list below.")
            self._settings_empty.grid()
            self._settings_apply_staged_overlay()
            return
        self._settings_empty.grid_remove()
        form = self._settings_form
        # High-score slots get their own block below (score AND initials AND
        # player name in one row per slot — batch 22), so hold their score
        # adjustments back from the generic grid rather than listing each one
        # twice.  They still register in _settings_rows, so staging, presets
        # and Reset Fields keep working on them unchanged.
        from ..plugins.stern.adjustments import is_score_adjustment
        hstd = getattr(self, "_settings_hstd", None)
        hs_adj = {r["adjustment"] for r in hstd.rows} if hstd else set()
        hs_adj.discard(None)
        # EVERY board score goes to the High Scores block, not just the ones
        # whose initials/player-name record we found.  Matching only on the
        # record left Led Zeppelin's BLACK DOG CHAMPION sitting alone up in
        # the settings grid (a tester: "these items seem outside the score
        # area") — it has no record, but it is still a champion score and
        # belongs with the rest.
        grid_rows = [r for r in rows
                     if r["name"] not in hs_adj
                     and not is_score_adjustment(r["name"])]
        by_adj = {r["name"]: r for r in rows if r["name"] in hs_adj}
        extra_scores = [r for r in rows
                        if r["name"] not in hs_adj
                        and is_score_adjustment(r["name"])]
        if not grid_rows and not by_adj and not extra_scores:
            grid_rows = rows
        rows = grid_rows
        # ONE column of settings (David, batch 22).  This used to wrap into
        # two or three side-by-side groups to use the tab's width, but the
        # form window is pinned to the canvas width and there is no horizontal
        # scrollbar, so on anything but a very wide window the right-hand
        # group's entries were simply cropped — you had to widen the window to
        # reach controls you couldn't see were there.  A single column can't
        # overflow at any width, and it reads the same way as the High Scores
        # block below it; the canvas scrolls vertically as it always has.
        base = 0
        accent = THEMES.get(self._current_theme, {}).get("link", "#d78f2c")
        for col, txt, tip in (
                (0, "Setting", None),
                (1, "On card", "The default currently baked into this "
                    "image — Stern's factory value unless it was changed "
                    "here before."),
                (2, "New default", "What the machine will use on a fresh "
                    "flash or after a factory reset, once saved to the "
                    "image.")):
            h = ttk.Label(form, text=txt, font=(_SANS_FONT, 9, "bold"))
            h.grid(row=0, column=col, sticky="w", padx=6, pady=(2, 4))
            if tip:
                _Tooltip(h, tip, lambda: self._current_theme)
        ttk.Label(form, text="Range", font=(_SANS_FONT, 8),
                  foreground="#888888").grid(
            row=0, column=4, sticky="w", padx=6, pady=(2, 4))
        grow = 0
        group = None
        for r in rows:
            # A heading whenever the block changes, so the running order has
            # a visible reason (a tester asked what the logic was).
            if r.get("group") and r["group"] != group:
                group = r["group"]
                grow += 1
                ttk.Label(form, text=group,
                          font=(_SANS_FONT, 10, "bold")).grid(
                    row=grow, column=0, columnspan=3, sticky="w", padx=6,
                    pady=(10, 2))
            grow += 1
            lbl = ttk.Label(form, text=r["label"], anchor="w")
            lbl.grid(row=grow, column=base, sticky="w", padx=6, pady=2)
            help_text = r["help"]
            # Say when the machine will not show this one in its Adjustments
            # menu.  It is still worth setting from the card (the firmware
            # reads the same default either way), but "I changed it and the
            # operator menu doesn't agree" has a real answer — the master
            # volume is the one a tester hit.
            if r.get("status") == "service":
                help_text = (help_text + "\n\n" if help_text else "") + (
                    "This machine edits this on a different service screen, "
                    "not in the Adjustments menu — so the value there may "
                    "not match what you set here.")
            elif r.get("status") == "debug":
                help_text = (help_text + "\n\n" if help_text else "") + (
                    "This machine's menus never show this setting at all.")
            if help_text:
                _Tooltip(lbl, help_text, lambda: self._current_theme)
            ttk.Label(form, text=self._settings_fmt_value(r, r["default"]),
                      foreground="#888888").grid(
                row=grow, column=base + 1, sticky="w", padx=6, pady=2)
            var = tk.IntVar(value=r["default"])
            rng = self._settings_range_text(r)
            if r["kind"] == "toggle":
                w = ttk.Checkbutton(form, variable=var, text="On")
                rng = "off / on"
            elif r["kind"] == "enum" and r.get("labels"):
                # Dropdown of "N - Label" so the label is friendly but the exact
                # index the machine stores is never hidden.  The combobox index
                # maps to value min+index; a hidden IntVar carries the value.
                labels = r["labels"]
                opts = ["%d - %s" % (v, labels[v])
                        for v in range(r["min"], r["max"] + 1)]
                w = ttk.Combobox(form, state="readonly", values=opts, width=16)
                # A shipped default outside its own range has no option to
                # select — leave the box blank rather than picking the wrong
                # end of the list (see _settings_changes).
                if r["min"] <= r["default"] <= r["max"]:
                    w.current(r["default"] - r["min"])

                def _sel(_e=None, _w=w, _v=var, _lo=r["min"]):
                    _v.set(_lo + _w.current())
                w.bind("<<ComboboxSelected>>", _sel)
                rng = "%d options" % len(opts)
            else:
                # Step + width come from the adjustment itself: high-score
                # defaults run to 1,000,000,000 and step by a million, so a
                # width-8 box with increment=1 was unusable for them
                # (feedback batch 22).
                # The spinner's own travel stretches to take in a shipped
                # default that sits outside the declared range, so the arrows
                # can always get back to the value the card actually has.
                w = ttk.Spinbox(
                    form, from_=min(r["min"], r["default"]),
                    to=max(r["max"], r["default"]), textvariable=var,
                    width=max(8, len("%d" % r["max"]) + 1),
                    increment=r.get("step", 1))
            w.grid(row=grow, column=base + 2, sticky="w", padx=6, pady=2)
            self._settings_bind_commit(w)
            # "●" lights up while the field deviates from the on-card value —
            # the at-a-glance answer to "am I changing anything here?".
            mark = ttk.Label(form, text=" ", foreground=accent, width=2)
            mark.grid(row=grow, column=base + 3, sticky="w", pady=2)

            def _remark(*_a, _r=r, _v=var, _m=mark):
                try:
                    changed = int(_v.get()) != _r["default"]
                except (tk.TclError, ValueError):
                    changed = False
                try:
                    _m.configure(text="●" if changed else " ")
                except tk.TclError:
                    pass
                # Every edit re-stages the tab's diffs (debounced) — batch 21
                # replaced the explicit Apply button with auto-staging.
                self._settings_schedule_autostage()
            var.trace_add("write", _remark)
            ttk.Label(form, text=rng, font=(_SANS_FONT, 8),
                      foreground="#888888").grid(
                row=grow, column=base + 4, sticky="w", padx=6, pady=2)
            self._settings_rows.append(dict(r, var=var, widget=w))
        self._settings_build_hstd_block(by_adj, accent, extra_scores)
        self._settings_apply_staged_overlay()

    def _settings_apply_staged_overlay(self):
        """Put the standing preset and the folder's staged edits into the
        freshly built form, and say what's pending.

        Overlaid in build-time order — the auto-apply preset first, then the
        staged values on top (staged wins at Build too) — so the fields show
        exactly what the next Build will bake in.  The loading flag keeps
        these programmatic sets from re-staging."""
        self._settings_reset_btn.config(state=tk.NORMAL)
        self._settings_refresh_presets()
        staged = self.staged_default_settings(self._settings_staged_dir())
        expose = self.staged_menu_expose(self._settings_staged_dir())
        self._settings_loading = True
        try:
            active = self._presets_blob().get("active")
            if active in self._presets_blob()["presets"]:
                self._settings_load_preset(active)
            for r in self._settings_rows:
                if r["name"] in staged:
                    self._settings_set_row(
                        r, int(staged[r["name"]]) // r.get("scale", 1))
            # A staged setting the curated form doesn't draw was edited in the
            # all-settings list — give it its row back so it keeps staging,
            # logging and resetting like any other.
            have = {r["name"] for r in self._settings_rows}
            by_name = {a["name"]: a for a in self._settings_all_rows}
            for name, val in staged.items():
                if name in have or name not in by_name:
                    continue
                self._settings_set_row(
                    self._settings_add_extra_row(by_name[name]), int(val))
        finally:
            self._settings_loading = False
        self._settings_fill_all_tree()
        bits = []
        if staged:
            bits.append("%d setting(s) staged for the next Build"
                        % len(staged))
        if expose:
            bits.append("the machine's menu will be opened up to \"%s\""
                        % self._settings_expose_label(expose))
        if active in self._presets_blob()["presets"]:
            bits.append("preset \"%s\" is baked into every card you Build"
                        % active)
        self._settings_status.configure(
            text=("; ".join(bits) + ".") if bits else "")
        # This card's state is now the baseline the session log reports
        # against: without adopting it here the first edit after a load was
        # swallowed as "the first look at this card" and never narrated.
        self._settings_logged = self._settings_log_state()
        # The form height changed — shrink the tab around it so the freed
        # space flows to the Log pane instead of sitting blank.
        try:
            self._tk_root().after_idle(self._resize_notebook_to_current_tab)
        except tk.TclError:
            pass

    def _settings_build_hstd_block(self, by_adj, accent, extra_scores=()):
        """The "High Scores" block: one row per slot on the machine's
        high-score board — initials, player name and (where the firmware
        exposes it as an adjustment) the default score.

        feedback batch 22 asked to edit "the name or score".  The scores are
        ordinary adjustments; the initials and names are their own string
        table in the same ELF (see plugins.stern.high_scores) and are patched
        in place, so each field is capped at the room its slot actually has.

        *extra_scores* are curated score rows the ELF has no name record for
        (Led Zeppelin's BLACK DOG CHAMPION); they are drawn as score-only
        lines so every champion is in one place.
        """
        hstd = getattr(self, "_settings_hstd", None)
        self._settings_hstd_vars = []
        hs_rows = list(hstd.rows) if hstd is not None else []
        # Champion scores with no initials/player-name record of their own get
        # a score-only line here rather than being stranded in the settings
        # grid (see is_score_adjustment).
        extra_scores = list(extra_scores or [])
        if not hs_rows and not extra_scores:
            return
        form = self._settings_form
        base_row = form.grid_size()[1] + 1
        ttk.Separator(form, orient=tk.HORIZONTAL).grid(
            row=base_row, column=0, columnspan=12, sticky="ew", pady=(10, 6))
        head = ttk.Label(form, text="High Scores",
                         font=(_SANS_FONT, 10, "bold"))
        head.grid(row=base_row + 1, column=0, columnspan=3, sticky="w",
                  padx=6)
        _Tooltip(head,
                 "The board the machine starts with on a fresh flash or after "
                 "a factory reset — Stern ships it filled with the design "
                 "team's initials. A machine that already has scores stored "
                 "keeps them and ignores these.",
                 lambda: self._current_theme)
        base_row += 2
        # Same column order as the settings grid above — reference value
        # first, then the field you edit.  It used to trail the row as bare
        # grey "on card 75,000,000" text with no header, which read as a
        # duplicate of the box beside it rather than as the card's own value
        # (a tester: "is this useful information?").
        for col, txt, tip in (
                (0, "Slot", None),
                (1, "Initials", None),
                (2, "Player name", None),
                (3, "On card", "The default score currently baked into this "
                    "image — Stern's factory value unless it was changed "
                    "here before."),
                (4, "Default score", "What the machine will seed this place "
                    "with on a fresh flash or after a factory reset.")):
            h = ttk.Label(form, text=txt, font=(_SANS_FONT, 9, "bold"))
            h.grid(row=base_row, column=col, sticky="w", padx=6, pady=(2, 4))
            if tip:
                _Tooltip(h, tip, lambda: self._current_theme)
        def _score_widgets(grow, score):
            """Draw one slot's on-card value + editable default, and register
            it as an ordinary settings row so staging, presets and Reset
            Fields keep working on it unchanged."""
            ttk.Label(form, text=self._settings_fmt_num(score["default"]),
                      foreground="#888888").grid(
                row=grow, column=3, sticky="w", padx=6, pady=2)
            svar = tk.IntVar(value=score["default"])
            sw = ttk.Spinbox(
                form, from_=min(score["min"], score["default"]),
                to=max(score["max"], score["default"]), textvariable=svar,
                width=max(8, len("%d" % score["max"]) + 1),
                increment=score.get("step", 1))
            sw.grid(row=grow, column=4, sticky="w", padx=6, pady=2)
            self._settings_bind_commit(sw)
            mark = ttk.Label(form, text=" ", foreground=accent, width=2)
            mark.grid(row=grow, column=5, sticky="w", pady=2)

            def _remark(*_a, _r=score, _v=svar, _m=mark):
                try:
                    changed = int(_v.get()) != _r["default"]
                except (tk.TclError, ValueError):
                    changed = False
                try:
                    _m.configure(text="●" if changed else " ")
                except tk.TclError:
                    pass
                self._settings_schedule_autostage()
            svar.trace_add("write", _remark)
            ttk.Label(form, text=self._settings_range_text(score),
                      font=(_SANS_FONT, 8), foreground="#888888").grid(
                row=grow, column=6, sticky="w", padx=6, pady=2)
            self._settings_rows.append(dict(score, var=svar, widget=sw))

        for i, rec in enumerate(hs_rows):
            grow = base_row + 1 + i
            ttk.Label(form, text=rec["display"], anchor="w").grid(
                row=grow, column=0, sticky="w", padx=6, pady=2)
            entry_vars = {}
            for col, key, width in ((1, "initials", 5), (2, "name", 14)):
                cap = rec["%s_max" % key]
                var = tk.StringVar(value=rec[key])
                ent = ttk.Entry(form, textvariable=var,
                                width=min(width, max(4, cap + 1)))
                ent.grid(row=grow, column=col, sticky="w", padx=6, pady=2)
                if cap <= 0:
                    ent.state(["disabled"])
                self._settings_bind_commit(ent)
                _Tooltip(ent, "On card: \"%s\".\nUp to %d character(s) — the "
                              "text is written into the slot's own space in "
                              "the firmware, so it can't grow."
                              % (rec[key], cap),
                         lambda: self._current_theme)
                entry_vars[key] = var

                def _on_edit(*_a, _v=var, _cap=cap, _k=key):
                    # Hard-cap as you type: a too-long value would only fail
                    # later, at build time.
                    t = _v.get()
                    if len(t) > _cap:
                        _v.set(t[:_cap])
                        return          # the truncating set re-enters here
                    self._settings_schedule_autostage()
                var.trace_add("write", _on_edit)
            score = by_adj.get(rec["adjustment"])
            if score is not None:
                _score_widgets(grow, score)
            self._settings_hstd_vars.append(
                {"label": rec["label"], "record": rec, "vars": entry_vars})
        for j, score in enumerate(extra_scores):
            grow = base_row + 1 + len(hs_rows) + j
            ttk.Label(form, text=score["label"], anchor="w").grid(
                row=grow, column=0, sticky="w", padx=6, pady=2)
            _score_widgets(grow, score)

    def _settings_hstd_changes(self):
        """``{slot label: {initials, name}}`` for high-score slots whose text
        differs from the image's — only the changed FIELDS are listed."""
        out = {}
        for row in getattr(self, "_settings_hstd_vars", []):
            diff = {}
            for key, var in row["vars"].items():
                try:
                    val = var.get()
                except tk.TclError:
                    continue
                if val != row["record"][key]:
                    diff[key] = val
            if diff:
                out[row["label"]] = diff
        return out

    def staged_high_scores(self, assets_dir):
        """``{slot label: {initials, name}}`` staged for *assets_dir*, or
        ``{}``.  Read by the app's Write flow after a successful build."""
        from ..core import staged_changes
        vals = staged_changes.load(assets_dir).get("high_scores")
        if not isinstance(vals, dict):
            return {}
        out = {}
        for label, fields in vals.items():
            if isinstance(fields, dict):
                clean = {k: str(v) for k, v in fields.items()
                         if k in ("initials", "name")}
                if clean:
                    out[str(label)] = clean
        return out

    def _settings_set_row(self, r, display_value):
        """Set a row to a DISPLAY value, keeping an enum's dropdown in sync.

        The row's own on-card default always goes in verbatim: clamping it
        would turn "put this back the way the card has it" into an edit on
        the rows whose shipped default sits outside their declared range (see
        :meth:`_settings_changes`), so Reset Fields staged them instead of
        clearing them."""
        v = (int(display_value) if int(display_value) == r["default"]
             else max(r["min"], min(r["max"], int(display_value))))
        r["var"].set(v)
        w = r.get("widget")
        if r["kind"] == "enum" and isinstance(w, ttk.Combobox):
            try:
                w.current(v - r["min"])
            except tk.TclError:
                pass

    def _settings_reset(self):
        """Back to the image's own defaults AND nothing staged — with
        auto-staging the two are one action (batch 21)."""
        self._settings_loading = True
        try:
            for r in self._settings_rows:
                self._settings_set_row(r, r["default"])
            for row in getattr(self, "_settings_hstd_vars", []):
                for key, var in row["vars"].items():
                    var.set(row["record"][key])
        finally:
            self._settings_loading = False
        n = 0
        menu = False
        assets_dir = self._settings_staged_dir()
        if assets_dir:
            from ..core import staged_changes
            data = staged_changes.load(assets_dir)
            n = len(data.get("settings") or {}) + len(
                data.get("high_scores") or {})
            menu = bool(data.get("menu_expose_through"))
            if ("settings" in data or "high_scores" in data
                    or "menu_expose_through" in data):
                data.pop("settings", None)
                data.pop("high_scores", None)
                data.pop("menu_expose_through", None)
                staged_changes.save(assets_dir, data)
                if self._on_folder_state_written:
                    self._on_folder_state_written(assets_dir)
        self._settings_fill_all_tree()
        cleared = []
        if n:
            cleared.append("%d staged setting(s)" % n)
        if menu:
            cleared.append("the menu widening")
        self._settings_status.configure(
            text="Fields reset to the image's current defaults%s."
                 % (" — cleared " + " and ".join(cleared) if cleared else ""))
        if cleared:
            self.append_log("Defaults: cleared %s."
                            % " and ".join(cleared), "info")

    # ---- Default Settings: staged-for-Build flow ---------------------
    # Changed defaults are recorded (auto-staged, debounced — batch 21) in
    # the shared assets folder's .staged_changes.json (key "settings",
    # internal units) and the Write flow bakes them into the OUTPUT image
    # after a successful build — the same staged model as every Replace tab,
    # so the master image on disk is never modified (a tester).

    def _settings_staged_dir(self):
        """The shared assets folder staged settings ride with ('' if unset)."""
        d = (self.write_assets_var.get() or "").strip()
        return d if d and os.path.isdir(d) else ""

    def staged_default_settings(self, assets_dir):
        """``{AD_name: internal_value}`` staged for *assets_dir*, or ``{}``.
        Called by the app's Write flow after a successful build."""
        from ..core import staged_changes
        vals = staged_changes.load(assets_dir).get("settings")
        if not isinstance(vals, dict):
            return {}
        out = {}
        for name, v in vals.items():
            try:
                out[str(name)] = int(v)
            except (TypeError, ValueError):
                continue
        return out

    def _settings_schedule_autostage(self):
        """Debounce an auto-stage: field edits arrive per keystroke / spinner
        click, so the actual staging write runs once things settle."""
        if self._settings_loading or self._settings_table is None:
            return
        job = getattr(self, "_settings_stage_job", None)
        if job is not None:
            try:
                self._tk_root().after_cancel(job)
            except tk.TclError:
                pass
        try:
            self._settings_stage_job = self._tk_root().after(
                500, self._settings_autostage)
        except tk.TclError:
            self._settings_stage_job = None

    # ---- Defaults: what the session log says about staged edits -------
    # The log used to fire off the debounced stage itself and name only the
    # raw AD_ ids of the whole staged SET, so a half-typed player name emitted
    # "2 setting(s) staged (AD_ELECTRIC_MAGIC_FRENZY_CHAMPION, …)" — settings
    # a tester had never opened, no values, and again on the next keystroke.
    # Logging is its own step now: one line per field that actually moved,
    # with the caption and the old and new value, and only once the field is
    # done being edited (focus left it, Return/Tab, or it went quiet).

    def _settings_bind_commit(self, widget):
        """Flush the staged-edit log the moment *widget* is done being edited
        — focus left it, or Return/Tab committed it."""
        for seq in ("<FocusOut>", "<Return>", "<KP_Enter>"):
            try:
                widget.bind(seq, self._settings_flush_log, add="+")
            except tk.TclError:
                pass

    def _settings_log_state(self):
        """The edited fields as ``{key: (what, old_display, new_display)}``.

        One entry per field that differs from the card, keyed so the diff
        against the previously logged state names exactly what moved."""
        state = {}
        for r in self._settings_rows:
            try:
                v = int(r["var"].get())
            except (tk.TclError, ValueError):
                continue
            if v == r["default"]:
                continue
            state[("set", r["name"])] = (
                r["label"], self._settings_fmt_value(r, r["default"]),
                self._settings_fmt_value(r, v))
        for row in getattr(self, "_settings_hstd_vars", []):
            for key, var in row["vars"].items():
                try:
                    val = var.get()
                except tk.TclError:
                    continue
                old = row["record"][key]
                if val == old:
                    continue
                state[("hs", row["label"], key)] = (
                    "%s %s" % (row["label"],
                               "initials" if key == "initials" else "name"),
                    '"%s"' % old, '"%s"' % val)
        return state

    def _settings_schedule_log(self, delay=1400):
        """Say what changed once the field settles — a longer wait than the
        stage write, so typing a name logs the name, not each letter."""
        job = getattr(self, "_settings_log_job", None)
        if job is not None:
            try:
                self._tk_root().after_cancel(job)
            except tk.TclError:
                pass
        try:
            self._settings_log_job = self._tk_root().after(
                delay, self._settings_flush_log)
        except tk.TclError:
            self._settings_log_job = None

    def _settings_flush_log(self, _event=None):
        """Log every field that moved since the last time we said so.

        Bound to the fields' <FocusOut>/<Return> as well as the idle timer:
        leaving a field is the moment the user is done with it, which is what
        a tester asked for ("doesn't fire off until you exit the text box").

        A stage write still waiting on its own debounce is brought forward
        first, so leaving a field records it AND reports it in one step and
        the log can never describe an edit that isn't staged yet."""
        self._settings_log_job = None
        if self._settings_loading or self._settings_table is None:
            return
        if getattr(self, "_settings_stage_job", None) is not None:
            try:
                self._tk_root().after_cancel(self._settings_stage_job)
            except tk.TclError:
                pass
            self._settings_stage_job = None
            self._settings_autostage()        # re-schedules a log job…
            job, self._settings_log_job = self._settings_log_job, None
            if job is not None:
                try:
                    self._tk_root().after_cancel(job)   # …which is this call
                except tk.TclError:
                    pass
        state = self._settings_log_state()
        before = getattr(self, "_settings_logged", None)
        if before is None:
            # First look at this card: adopt the state (a preset or an
            # already-staged folder) without narrating it — the status line
            # and the form's ● marks already say what's staged.
            self._settings_logged = state
            return
        if state == before:
            return
        for key in sorted(set(state) | set(before), key=lambda k: k[1:]):
            now, was = state.get(key), before.get(key)
            if now == was:
                continue
            if now is None:
                what, card, _prev = was
                self.append_log(
                    "Defaults: %s back to the card's %s — no longer staged."
                    % (what, card), "info")
            else:
                what, card, val = now
                self.append_log(
                    "Defaults: %s %s → %s staged for the next Build "
                    "(card has %s)." % (what, (was or now)[2], val, card),
                    "info")
        self._settings_logged = state

    def _settings_autostage(self):
        """Record the form's diffs as staged-for-Build (or clear the record
        when the fields are back at the image's defaults)."""
        self._settings_stage_job = None
        if self._settings_busy or self._settings_table is None:
            return
        # The all-settings list shows the same pending values in its "New
        # default" column, whichever editor set them.
        self._settings_fill_all_tree()
        changes = self._settings_changes()
        hstd = self._settings_hstd_changes()
        assets_dir = self._settings_staged_dir()
        if not assets_dir:
            if changes or hstd:
                self._settings_status.configure(
                    text="Set the project folder on the Extract tab first — "
                         "changes stage with the project.")
            return
        from ..core import staged_changes
        data = staged_changes.load(assets_dir)
        before = data.get("settings") or {}
        before_hs = data.get("high_scores") or {}
        new = {k: int(v) for k, v in changes.items()}
        if new == before and hstd == before_hs:
            return
        if new:
            data["settings"] = new
        elif "settings" in data:
            del data["settings"]
        if hstd:
            data["high_scores"] = hstd
        elif "high_scores" in data:
            del data["high_scores"]
        staged_changes.save(assets_dir, data)
        # Project history (batch 24): staged default-settings edits, with the
        # previous staged value where one existed.
        from ..core import history_log
        hist = []
        for k in sorted(set(before) | set(new)):
            o, n = before.get(k), new.get(k)
            if o == n:
                continue
            if n is None:
                hist.append("defaults  %s  un-staged (back to the card's "
                            "default, was staged: %s)" % (k, o))
            elif o is None:
                hist.append("defaults  %s  staged: %s" % (k, n))
            else:
                hist.append("defaults  %s  staged: %s  (was staged: %s)"
                            % (k, n, o))
        def _hs(d):
            return ", ".join("%s=%s" % kv for kv in sorted(
                (d or {}).items()))
        for k in sorted(set(before_hs) | set(hstd)):
            o, n = before_hs.get(k), hstd.get(k)
            if o == n:
                continue
            if n is None:
                hist.append("defaults  high score %s  un-staged  (was: %s)"
                            % (k, _hs(o)))
            else:
                hist.append("defaults  high score %s  staged: %s%s"
                            % (k, _hs(n),
                               ("  (was: %s)" % _hs(o)) if o else ""))
        history_log.record(assets_dir, hist)
        # Staged settings are folder state too — see _save_staged_changes.
        if self._on_folder_state_written:
            self._on_folder_state_written(assets_dir)
        total = len(new) + len(hstd)
        self._settings_status.configure(
            text=("%d change(s) staged — baked into the next card you "
                  "Build." % total) if total else "Nothing staged.")
        # What to SAY about it is decided separately, once the field settles
        # — see _settings_flush_log.
        self._settings_schedule_log()

    def _settings_changes(self):
        """``{AD_name: internal_value}`` for rows whose display value differs
        from the image's current default.  Values are converted from the
        machine-facing display units back to the firmware's internal units
        (internal = display * scale) — that's what gets written.

        The "is this row changed?" test is the RAW one — the field against the
        on-card default, exactly what the ``●`` marker shows — and only a row
        that really is changed then gets clamped into the adjustment's own
        range for writing.  Clamping first was a bug: Stern ships some
        defaults OUTSIDE the range the same descriptor declares (Led Zeppelin
        1.22's ELECTRIC MAGIC FRENZY / MULTIBALL champions default to
        2,000,000 with a minimum of 5,000,000), so the clamp moved the value
        off its own default and every one of those rows staged itself the
        moment the tab loaded, with no ● lit and nothing touched — a tester
        saw two settings he never opened staged while typing a player name."""
        out = {}
        for r in self._settings_rows:
            try:
                v = int(r["var"].get())
            except (tk.TclError, ValueError):
                continue
            if v == r["default"]:
                continue                  # untouched, in range or not
            v = max(r["min"], min(r["max"], v))
            if v == r["default"]:
                continue                  # edit landed back on the default
            out[r["name"]] = v * r.get("scale", 1)
        return out


    # ---- Image Info dialog ------------------------------------------

    def _smooth_disc_image(self, size, fill, bg, dots=()):
        """An anti-aliased filled disc as a ``tk.PhotoImage`` — Tk 8.6's
        ``create_oval`` has no anti-aliasing, so the round header icons /
        ⓘ badges rendered with visibly stair-stepped edges (David: "chunky").

        Per-pixel analytic coverage (distance from the disc edge, clamped to
        a 1-px feather) blended against the flat *bg* the canvas sits on —
        an opaque pre-blend, so no reliance on partial-alpha display and no
        Pillow dependency.  *dots* = ((cx, cy, r, "#color"), ...) composites
        the gear's corner notification dots into the same image, which keeps
        their edges smooth both over the disc and over the backdrop.

        Cached per (size, fill, bg, dots) on the instance — PhotoImages die
        with this window's interp, so the cache must not be class-level."""
        key = (size, fill, bg, tuple(dots))
        img = self._disc_img_cache.get(key)
        if img is not None:
            return img

        def rgb(c):
            return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)

        def lerp(a, b, t):
            return tuple(int(round(x + (y - x) * t))
                         for x, y in zip(a, b))

        bgc, fillc = rgb(bg), rgb(fill)
        dotc = [(dx, dy, dr, rgb(dcol)) for dx, dy, dr, dcol in dots]
        centre = size / 2.0
        radius = (size - 2) / 2.0     # same footprint as the old oval
        rows = []
        for y in range(size):
            row = []
            py = y + 0.5
            for x in range(size):
                px = x + 0.5
                d = ((px - centre) ** 2 + (py - centre) ** 2) ** 0.5
                cov = min(1.0, max(0.0, radius - d + 0.5))
                c = lerp(bgc, fillc, cov)
                for dx, dy, dr, dcol in dotc:
                    dd = ((px - dx) ** 2 + (py - dy) ** 2) ** 0.5
                    dcov = min(1.0, max(0.0, dr - dd + 0.5))
                    if dcov:
                        c = lerp(c, dcol, dcov)
                row.append("#%02x%02x%02x" % c)
            rows.append("{" + " ".join(row) + "}")
        img = tk.PhotoImage(master=self.root, width=size, height=size)
        img.put(" ".join(rows))
        self._disc_img_cache[key] = img
        return img

    def _refresh_round_icon(self, cv):
        """Re-render a round icon's disc image from its current state
        (fill/hover/disabled color, theme backdrop, notification dots)."""
        dots = tuple(v for _k, v in sorted(cv.icon_dots.items()))
        cv.itemconfigure(cv.icon_img, image=self._smooth_disc_image(
            cv.icon_size, cv.icon_current, cv.icon_bg, dots))

    def _set_icon_dot(self, cv, key, dot):
        """Add/replace (*dot* = ``(cx, cy, r, "#color")``) or remove (*dot*
        None) a notification dot on a round icon, keyed so independent dots
        (gear: update vs staging) don't fight."""
        if dot is None:
            cv.icon_dots.pop(key, None)
        else:
            cv.icon_dots[key] = tuple(dot)
        self._refresh_round_icon(cv)

    def _make_round_icon(self, parent, glyph, fill, hover, tooltip_text,
                         command, size=24, font=None, tooltip_place="below",
                         draw=None):
        """A round colorful icon button — colored circle, white glyph — the
        app's icon-button look (David: round colorful icons instead of
        square glyph buttons; drawn on a Canvas because Tk 8.6 renders no
        color emoji).  The disc is a pre-rendered anti-aliased image
        (_smooth_disc_image) — a Tk oval item drew chunky stair-stepped
        edges.  Hover lightens the circle; the hand cursor marks it
        clickable; *tooltip_text* rides the shared _Tooltip.  The canvas
        carries ``icon_fill`` / ``icon_hover`` / ``icon_enabled`` /
        ``icon_dots`` so callers can restyle it (gear notification dots via
        _set_icon_dot, back-button disable via _set_round_icon_enabled), and
        registers in _round_icons so _apply_theme keeps its backdrop — and
        the pre-blended disc — on the theme."""
        bg = THEMES[self._current_theme]["bg"]
        cv = tk.Canvas(parent, width=size, height=size,
                       highlightthickness=0, borderwidth=0, cursor="hand2",
                       bg=bg)
        cv.icon_fill, cv.icon_hover = fill, hover
        cv.icon_enabled = True
        cv.icon_size = size
        cv.icon_bg = bg
        cv.icon_current = fill
        cv.icon_dots = {}
        cv.icon_img = cv.create_image(
            0, 0, anchor=tk.NW, image=self._smooth_disc_image(size, fill, bg))
        if font is None:
            # Same glyph fonts the old square Icon.TButtons used: Segoe
            # MDL2 Assets on Windows, text glyphs elsewhere (negative
            # size = pixels).
            font = (("Segoe MDL2 Assets", -13) if sys.platform == "win32"
                    else (_SANS_FONT, -13))
        if draw is not None:
            # DRAWN, not typed — for an icon whose character does not exist in
            # every platform's system font.  See widgets.draw_folder_icon.
            draw(cv, size)
        else:
            cv.create_text(size // 2, size // 2, text=glyph, fill="#ffffff",
                           font=font)

        def _set_fill(color):
            cv.icon_current = color
            self._refresh_round_icon(cv)

        cv.bind("<Button-1>",
                lambda _e: command() if cv.icon_enabled else None)
        cv.bind("<Enter>", lambda _e: (cv.icon_enabled
                                       and _set_fill(cv.icon_hover)))
        cv.bind("<Leave>", lambda _e: (cv.icon_enabled
                                       and _set_fill(cv.icon_fill)))
        # ``tooltip_place="side"`` is for a badge sitting next to a control the
        # user also has to operate — a tip under a combobox opens exactly where
        # its drop-down does.  The tip is kept on the canvas so a caller can
        # keep its text current (the Scenes window's caption badge does).
        cv.icon_tip = _Tooltip(cv, tooltip_text, lambda: self._current_theme,
                               place=tooltip_place)
        self._round_icons.append(cv)
        return cv

    def _set_round_icon_enabled(self, cv, enabled):
        """Enable/disable a _make_round_icon canvas: gray circle + arrow
        cursor while disabled (its click handler checks icon_enabled)."""
        cv.icon_enabled = bool(enabled)
        cv.icon_current = cv.icon_fill if enabled else "#9aa0a6"
        self._refresh_round_icon(cv)
        cv.configure(cursor="hand2" if enabled else "arrow")

    _INFO_BADGE_FILL = "#2f80ed"     # the classic "info blue"
    _INFO_BADGE_HOVER = "#5296f2"

    def _make_info_badge(self, parent, var):
        """The small round ⓘ badge — blue circle, white ``i`` — that opens
        the Image Info window for the path in *var*."""
        return self._make_round_icon(
            parent, "i", self._INFO_BADGE_FILL, self._INFO_BADGE_HOVER,
            "Technical details about this image",
            lambda: self._open_image_info(var), size=18,
            font=("Georgia", 10, "bold italic"))

    # ---- Project Info popup (ⓘ on the Extract tab's project row) -----

    @staticmethod
    def _collect_project_stats(folder):
        """Walk *folder* and return the stats the Project Info popup shows,
        as ``[(name, value), ...]``.  Worker-thread only (a NAS project can
        take seconds to walk); touches no Tk."""
        from ..core import project_file, staged_changes, staged_originals

        audio_ext = {".wav", ".ogg", ".mp3", ".flac"}
        video_ext = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".m4v",
                     ".mpg", ".mpeg"}
        image_ext = {".png", ".jpg", ".jpeg", ".webp", ".dds", ".bmp",
                     ".gif"}
        counts = {"audio": [0, 0], "video": [0, 0],
                  "image": [0, 0], "other": [0, 0]}
        total_files = 0
        total_bytes = 0
        for root_, _dirs, files in os.walk(folder):
            rel = os.path.relpath(root_, folder)
            in_hidden = (rel != "." and any(
                p.startswith(".") for p in rel.split(os.sep)))
            for fn in files:
                try:
                    sz = os.path.getsize(os.path.join(root_, fn))
                except OSError:
                    continue
                total_files += 1
                total_bytes += sz
                if in_hidden or fn.startswith("."):
                    # Bookkeeping (baseline, .orig snapshots, anchor) counts
                    # toward size on disk but isn't a project asset.
                    continue
                ext = os.path.splitext(fn)[1].lower()
                kind = ("audio" if ext in audio_ext
                        else "video" if ext in video_ext
                        else "image" if ext in image_ext else "other")
                counts[kind][0] += 1
                counts[kind][1] += sz

        human = MainWindow._pex_human

        def _files(kind):
            n, sz = counts[kind]
            return "%d file(s)  —  %s" % (n, human(sz)) if n else "none"

        try:
            data = staged_changes.load(folder)
            staged = sum(len(data.get(k) or {})
                         for k in ("audio", "video", "image"))
        except Exception:
            staged = 0
        try:
            built = len(list(staged_originals.snapshot_rels(folder)))
        except Exception:
            built = 0
        if staged or built:
            changed = []
            if staged:
                changed.append("%d staged for the next build" % staged)
            if built:
                changed.append("%d changed by earlier builds" % built)
            changed = ";  ".join(changed)
        else:
            changed = "nothing changed yet"

        anchor = project_file.anchor_path(folder)
        started = ""
        try:
            src = anchor if os.path.isfile(anchor) else folder
            started = time.strftime("%Y-%m-%d",
                                    time.localtime(os.stat(src).st_ctime))
        except OSError:
            pass

        rows = [("Audio", _files("audio")),
                ("Video", _files("video")),
                ("Images", _files("image")),
                ("Other files", _files("other")),
                ("Total", "%d file(s)  —  %s on disk"
                          % (total_files, human(total_bytes))),
                ("Changed", changed)]
        if started:
            rows.append(("Project started", started))
        return rows

    def _open_project_info(self):
        """Stats popup for the project folder (feedback batch 20: "fun
        stats" behind a ⓘ like the Card image row's): what's in the project
        (audio/video/images counts + sizes), its size on disk, how much of it
        is changed, and when it started.  One singleton Toplevel; collection
        runs on a worker thread with the Image-Info-style spinner + stale
        results dropped by a bump-counter."""
        folder = ((self.extract_output_var.get() or "").strip()
                  or (self.write_assets_var.get() or "").strip())
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo(
                "No project folder",
                "Pick (or extract into) a project folder first — the stats "
                "describe that folder.")
            return
        folder = os.path.normpath(folder)

        win = getattr(self, "_proj_info_win", None)
        if win is None or not win.winfo_exists():
            win = tk.Toplevel(self.root)
            self._proj_info_win = win
            win.title("Project Info")
            win.transient(self.root)
            win.resizable(False, False)
            self._theme_toplevel(win)
            self._proj_info_path_lbl = ttk.Label(
                win, text="", font=(_SANS_FONT, 9, "bold"), wraplength=460,
                justify=tk.LEFT)
            self._proj_info_path_lbl.pack(anchor=tk.W, padx=12, pady=(12, 6))
            self._proj_info_grid = ttk.Frame(win)
            self._proj_info_grid.pack(fill=tk.X, padx=12)
            self._proj_info_status = ttk.Label(win, text="",
                                               font=(_SANS_FONT, 9, "italic"))
            self._proj_info_status.pack(anchor=tk.W, padx=12, pady=(4, 0))
            btns = ttk.Frame(win)
            btns.pack(fill=tk.X, padx=12, pady=(8, 12))
            ttk.Button(btns, text="Close", command=win.destroy).pack(
                side=tk.RIGHT)
            win.bind("<Escape>", lambda _e: win.destroy())
            win.update_idletasks()
            px, py = self.root.winfo_rootx(), self.root.winfo_rooty()
            pw, ph = self.root.winfo_width(), self.root.winfo_height()
            win.geometry("+%d+%d" % (px + max((pw - 480) // 2, 0),
                                     py + max((ph - 240) // 3, 0)))
        else:
            win.deiconify()
            win.lift()
        win.focus_set()
        self._proj_info_path_lbl.configure(text=folder)
        for child in self._proj_info_grid.winfo_children():
            child.destroy()

        self._proj_info_seq = getattr(self, "_proj_info_seq", 0) + 1
        seq = self._proj_info_seq
        holder = {}

        def _worker():
            try:
                holder["rows"] = self._collect_project_stats(folder)
            except Exception as e:    # never leave the window on the spinner
                holder["rows"] = [("Error", str(e))]

        import threading
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        def _poll(i=0):
            if (seq != self._proj_info_seq or win is None
                    or not win.winfo_exists()):
                return                # superseded / closed
            if t.is_alive():
                try:
                    self._proj_info_status.configure(
                        text="%s  Collecting…"
                             % self._SCAN_SPINNER[i % len(self._SCAN_SPINNER)])
                except tk.TclError:
                    return
                self.root.after(120, _poll, i + 1)
                return
            self._proj_info_status.configure(text="")
            for r, (name, value) in enumerate(holder.get("rows") or ()):
                ttk.Label(self._proj_info_grid, text=name + ":",
                          font=(_SANS_FONT, 9, "bold")).grid(
                    row=r, column=0, sticky=tk.W, padx=(0, 12), pady=1)
                ttk.Label(self._proj_info_grid, text=value, wraplength=360,
                          justify=tk.LEFT).grid(
                    row=r, column=1, sticky=tk.W, pady=1)

        self.root.after(60, _poll)

    def _open_image_info(self, var):
        """Open (or retarget) the Image Info window for the image path in
        *var* — everything the app knows about it in one place: file facts,
        what was detected, the plugin's firmware/partition details, and
        (after an Extract) asset counts, with a copy-pasteable report for
        comparing releases and filing bug reports (a tester).

        A window, not a tab: the notebook was getting wide (David).  One
        singleton Toplevel, launched from the small "Info" button next to
        each image picker; an open window is re-pointed at the new path."""
        path = (var.get() or "").strip()
        if not path:
            messagebox.showinfo(
                "No image selected",
                "Pick an image in the box next to the Info button first.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("File not found", "No file at:\n\n%s" % path)
            return
        self._info_path = os.path.normpath(path)
        if self._info_win is not None and self._info_win.winfo_exists():
            self._info_win.deiconify()
            self._info_win.lift()
            self._info_win.focus_set()
            self._info_refresh()
            return
        self._build_info_window()
        self._info_refresh()

    def _build_info_window(self):
        win = tk.Toplevel(self.root)
        win.title("Image Info")
        win.transient(self.root)
        # Starts tall enough for a typical report; _info_fit_height then
        # grows the window to the collected content (screen-capped) so a
        # full Spike 2 report needs no vertical scrolling (a tester).
        # Opens centered over the app like every dialog (David).
        center_over(self.root, win, 780, 560)
        win.minsize(520, 300)
        self._theme_toplevel(win)
        self._info_win = win

        f = ttk.Frame(win, padding=(10, 8))
        f.pack(fill=tk.BOTH, expand=True)

        # The file this window currently describes (it can outlive picker
        # changes, so it must say what it's showing).
        self._info_path_lbl = ttk.Label(f, text="", font=(_SANS_FONT, 9),
                                        justify=tk.LEFT)
        self._info_path_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
        self._info_path_lbl.bind(
            "<Configure>", lambda e: self._info_path_lbl.configure(
                wraplength=max(300, e.width - 8)))

        body = ttk.Frame(f)
        body.pack(fill=tk.BOTH, expand=True)
        self._info_tree = ttk.Treeview(body, columns=("value",), height=26,
                                       selectmode="browse")
        self._info_tree.heading("#0", text="Property", anchor=tk.W)
        self._info_tree.heading("value", text="Value", anchor=tk.W)
        self._info_tree.column("#0", width=200, minwidth=140, stretch=False)
        self._info_tree.column("value", width=480, minwidth=200)
        self._info_tree.tag_configure("section",
                                      font=(_SANS_FONT, 9, "bold"))
        vs = ttk.Scrollbar(body, orient="vertical",
                           command=self._info_tree.yview)
        self._info_tree.configure(yscrollcommand=vs.set)
        self._info_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vs.pack(side=tk.LEFT, fill=tk.Y)

        # Loading overlay: the collect() probe can take a while on big
        # images / network shares, and a blank tree looked hung — float the
        # same big animated indicator the Replace tabs' scans use over it.
        self._info_empty = ttk.Label(body, text="",
                                     font=(_SANS_FONT, 18, "bold"),
                                     foreground="#888888",
                                     anchor=tk.CENTER, justify=tk.CENTER)

        arow = ttk.Frame(f)
        arow.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(arow, text="Refresh",
                   command=lambda: self._info_refresh(force=True)).pack(
            side=tk.LEFT)
        self._info_copy_btn = ttk.Button(
            arow, text="Copy Report", command=self._info_copy_report,
            state=tk.DISABLED)
        self._info_copy_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._info_status = ttk.Label(arow, text="", font=(_SANS_FONT, 9))
        self._info_status.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(arow, text="Close",
                   command=self._info_reset).pack(side=tk.RIGHT)
        win.protocol("WM_DELETE_WINDOW", self._info_reset)

    def _info_assets_dir(self):
        """The current extracted-assets folder, fed to the plugin's
        image_info hook (BOF's update-version date lives only in the
        extract output): the Write tab's folder, else the Extract output."""
        assets = ((self.write_assets_var.get() or "").strip()
                  or (self.extract_output_var.get() or "").strip())
        return assets if assets and os.path.isdir(assets) else None

    def _info_reset(self):
        """Close the Image Info window and drop its state (window Close, and
        manufacturer switch — a previous mfr's details must not survive under
        the new one's name)."""
        self._info_seq += 1          # invalidate any in-flight probe
        self._info_sections = []
        self._info_shown_key = None
        self._info_path = ""
        win, self._info_win = self._info_win, None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def _info_refresh(self, force=False):
        """(Re)collect the details for the window's image on a worker thread
        and render them.  Skips when the tree already shows this exact
        path + assets pair (the Info button re-fires this on every click);
        the probe itself never touches Tk — results come back via an
        after() poll, stale ones dropped by the bump-counter."""
        import threading
        from ..core import image_info as _info_mod

        if self._info_win is None or not self._info_win.winfo_exists():
            return
        tree = self._info_tree
        path = self._info_path
        self._info_path_lbl.configure(text=path)
        assets = self._info_assets_dir()
        key = (os.path.normcase(path), assets)
        if not force and key == self._info_shown_key:
            return
        mfr = self._current_mfr

        self._info_seq += 1
        seq = self._info_seq
        # A probe is now in flight — the tree no longer shows anything
        # trustworthy, so a retarget back to the old path must re-probe
        # rather than skip onto the blanked list.
        self._info_shown_key = None
        holder = {}

        def _worker():
            try:
                holder["sections"] = _info_mod.collect(mfr, path, assets)
            except Exception as e:   # never leave the window on "Reading…"
                holder["sections"] = [("Error", [("Could not read", str(e))])]

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        tree.delete(*tree.get_children())
        self._info_copy_btn.configure(state=tk.DISABLED)
        self._info_status.configure(text="Reading image…")
        self._info_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        def _poll(i=0):
            if seq != self._info_seq:    # superseded / window closed
                return
            if t.is_alive():
                try:                     # animate the overlay so a long
                    self._info_empty.configure(   # probe visibly moves
                        text="%s  Reading image…"
                             % self._SCAN_SPINNER[i % len(self._SCAN_SPINNER)])
                except tk.TclError:
                    return
                self.root.after(120, _poll, i + 1)
                return
            if self._info_win is None or not self._info_win.winfo_exists():
                return
            self._info_empty.place_forget()
            self._info_shown_key = key
            self._info_sections = holder.get("sections") or []
            tree.delete(*tree.get_children())
            for title, rows in self._info_sections:
                parent = tree.insert("", tk.END, text=title, open=True,
                                     tags=("section",))
                for name, value in rows:
                    tree.insert(parent, tk.END, text=name, values=(value,))
            self._info_copy_btn.configure(
                state=tk.NORMAL if self._info_sections else tk.DISABLED)
            self._info_status.configure(text="")
            self._info_fit_height()

        self.root.after(120, _poll)

    def _info_fit_height(self):
        """Grow the Image Info window so the whole report is visible without
        vertical scrolling (a tester), capped to the screen.  Only ever grows —
        a user who shrank the window keeps their size for shorter reports."""
        win, tree = self._info_win, self._info_tree
        if win is None or not win.winfo_exists():
            return
        win.update_idletasks()
        rows = 0
        for sec in tree.get_children(""):
            rows += 1 + len(tree.get_children(sec))
        first = tree.get_children("")
        bb = tree.bbox(first[0]) if first else None
        rowheight = bb[3] if bb else 20
        # +1 row of slack for the heading; everything around the tree (path
        # label, buttons, padding) keeps its measured height.
        need = (rows + 1) * rowheight + 24 - tree.winfo_height()
        if need <= 0:
            return
        screen_h = win.winfo_screenheight()
        new_h = min(win.winfo_height() + need, screen_h - 80)
        if new_h <= win.winfo_height():
            return
        # Keep the grown window fully on-screen: pull it up if its bottom
        # would run past the display (48px ≈ titlebar + taskbar slack).
        y = win.winfo_rooty()
        if y + new_h > screen_h - 48:
            y = max(8, screen_h - new_h - 48)
        win.geometry("%dx%d+%d+%d"
                     % (win.winfo_width(), new_h, win.winfo_rootx(), y))

    def _info_copy_report(self):
        from ..core import image_info as _info_mod
        if not self._info_sections:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(_info_mod.as_text(self._info_sections))
        self._info_status.configure(text="Report copied to clipboard.")

    def _build_emulate_tab(self):
        """Build the 'Emulate' tab: start / stop the Stern Spike 2 emulator and
        report what it is doing.

        All the substance lives in :mod:`..gui.emulate_tab`, and the emulator
        itself lives outside the repo entirely (a rig of shell scripts, an
        LD_PRELOAD hardware shim and a native GL host, under ``c:\\tmp``).  This
        method is only the seam.  Note the tab acts on the RIG, not on the image
        in the Input box — see the module docstring for why that is called out
        on the tab itself."""
        from .emulate_tab import EmulatePanel
        # The card path is a WINDOW variable so the app can persist it in the
        # project anchor and restore it on project load, exactly like the
        # Extract/Write path fields.
        self.emulate_card_var = tk.StringVar()
        self._emulate_panel = EmulatePanel(self._tab_emulate,
                                           log=self.append_log,
                                           card_var=self.emulate_card_var)
        self._emulate_panel.build(self._tab_emulate)

    def emulate_shutdown(self):
        """App-quit hook: take the emulator down with the app (blocking,
        bounded).  A quit must not leave the game, Controls and playfield
        windows orphaned behind a vanished control surface."""
        panel = getattr(self, "_emulate_panel", None)
        if panel is not None:
            panel.shutdown_sync()

    def _build_compare_tab(self):
        """Build the 'Compare' tab: pick two card images (two releases, or a
        modded card against its stock base) and get a what-changed report —
        added / modified / deleted files per asset type by the cards' own
        validation digests, sound counts, adjustment defaults and high-score
        boards (a tester's wish list).  Read-only, no Extract: the report is
        the plugin's compare_images(), run on a worker thread like the Image
        Info probe."""
        f = self._tab_compare

        intro = ttk.Label(
            f, text="Compare two card images of the same game — two "
                    "releases, or a modded card against its stock base. "
                    "Everything is read straight off the cards (no Extract): "
                    "files are diffed by the cards' own validation digests, "
                    "and the adjustment / high-score defaults come from each "
                    "card's game firmware.",
            font=(_SANS_FONT, 9, "italic"), justify=tk.LEFT)
        intro.pack(anchor=tk.W, fill=tk.X, padx=10, pady=4)
        intro.bind("<Configure>", lambda e: intro.configure(
            wraplength=max(300, e.width - 8)))

        for label, var, field in (
                ("Image A:", self.compare_a_var, "compare_a"),
                ("Image B:", self.compare_b_var, "compare_b")):
            row = ttk.Frame(f)
            row.pack(fill=tk.X, padx=10, pady=4)
            ttk.Label(row, text=label, width=12, anchor=tk.W).pack(
                side=tk.LEFT)
            ent = self._path_combo(row, var, field)
            ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ent.bind("<Return>", lambda _e: self._compare_run())
            ttk.Button(row, text="Browse…",
                       command=lambda v=var: self._compare_browse(v)).pack(
                side=tk.LEFT, padx=(6, 0))

        arow = ttk.Frame(f)
        arow.pack(fill=tk.X, padx=10, pady=(2, 4))
        self._compare_btn = ttk.Button(arow, text="Compare",
                                       command=self._compare_run)
        self._compare_btn.pack(side=tk.LEFT)
        self._compare_copy_btn = ttk.Button(
            arow, text="Copy Report", command=self._compare_copy_report,
            state=tk.DISABLED)
        self._compare_copy_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._compare_status = ttk.Label(arow, text="", font=(_SANS_FONT, 9))
        self._compare_status.pack(side=tk.LEFT, padx=(10, 0))

        body = ttk.Frame(f)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 6))
        self._compare_tree = ttk.Treeview(body, columns=("value",),
                                          height=22, selectmode="browse")
        self._compare_tree.heading("#0", text="Change", anchor=tk.W)
        self._compare_tree.heading("value", text="Details", anchor=tk.W)
        self._compare_tree.column("#0", width=210, minwidth=140,
                                  stretch=False)
        self._compare_tree.column("value", width=640, minwidth=240)
        self._compare_tree.tag_configure("section",
                                         font=(_SANS_FONT, 9, "bold"))
        vs = ttk.Scrollbar(body, orient="vertical",
                           command=self._compare_tree.yview)
        self._compare_tree.configure(yscrollcommand=vs.set)
        self._compare_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vs.pack(side=tk.LEFT, fill=tk.Y)
        # Same floating "working…" overlay the Image Info window uses — a
        # two-card probe takes a little while and a blank tree looks hung.
        self._compare_empty = ttk.Label(body, text="",
                                        font=(_SANS_FONT, 18, "bold"),
                                        foreground="#888888",
                                        anchor=tk.CENTER, justify=tk.CENTER)

    def _compare_browse(self, var):
        path = filedialog.askopenfilename(
            title="Select card image", filetypes=self._input_filetypes(),
            initialdir=self._initialdir_for(var.get(),
                                            self.extract_input_var.get()))
        if path:
            var.set(os.path.normpath(path))

    def _compare_reset(self):
        """Drop the Compare tab's report + any in-flight worker (manufacturer
        switch — a previous manufacturer's diff must not survive)."""
        self._compare_seq += 1
        self._compare_sections = []
        if hasattr(self, "_compare_tree"):
            try:
                self._compare_tree.delete(
                    *self._compare_tree.get_children())
                self._compare_empty.place_forget()
                self._compare_btn.configure(state=tk.NORMAL)
                self._compare_copy_btn.configure(state=tk.DISABLED)
                self._compare_status.configure(text="")
            except tk.TclError:
                pass

    def _compare_run(self):
        """Diff the two picked card images on a worker thread and render the
        report — the same thread + after()-poll + bump-counter shape as the
        Image Info window (the probe never touches Tk off-thread)."""
        import threading

        a = (self.compare_a_var.get() or "").strip()
        b = (self.compare_b_var.get() or "").strip()
        if not a or not b:
            messagebox.showinfo(
                "Pick two images",
                "Pick both card images to compare first.")
            return
        for side, p in (("A", a), ("B", b)):
            if not os.path.isfile(p):
                messagebox.showerror(
                    "File not found", "Image %s:\n\n%s" % (side, p))
                return
        mfr = self._current_mfr
        if mfr is None:
            return
        if self._on_compare_run:
            self._on_compare_run(a, b)

        self._compare_seq += 1
        seq = self._compare_seq
        holder = {}

        def _worker():
            try:
                holder["sections"] = mfr.compare_images(a, b) or []
            except Exception as e:  # never leave the tab on "Comparing…"
                holder["sections"] = [
                    ("Error", [("Could not compare", str(e))])]

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        tree = self._compare_tree
        tree.delete(*tree.get_children())
        self._compare_sections = []
        self._compare_btn.configure(state=tk.DISABLED)
        self._compare_copy_btn.configure(state=tk.DISABLED)
        self._compare_status.configure(text="Comparing images…")
        self._compare_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        def _poll(i=0):
            if seq != self._compare_seq:    # superseded / mfr switched
                return
            if t.is_alive():
                try:
                    self._compare_empty.configure(
                        text="%s  Comparing images…"
                        % self._SCAN_SPINNER[i % len(self._SCAN_SPINNER)])
                except tk.TclError:
                    return
                self.root.after(120, _poll, i + 1)
                return
            try:
                self._compare_empty.place_forget()
            except tk.TclError:
                return
            self._compare_sections = holder.get("sections") or []
            tree.delete(*tree.get_children())
            for title, rows in self._compare_sections:
                parent = tree.insert("", tk.END, text=title, open=True,
                                     tags=("section",))
                for name, value in rows:
                    tree.insert(parent, tk.END, text=name, values=(value,))
            self._compare_btn.configure(state=tk.NORMAL)
            self._compare_copy_btn.configure(
                state=tk.NORMAL if self._compare_sections else tk.DISABLED)
            self._compare_status.configure(text="")

        self.root.after(120, _poll)

    def _compare_copy_report(self):
        from ..core import image_info as _info_mod
        if not self._compare_sections:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(_info_mod.as_text(
            self._compare_sections, title="Compare Report"))
        self._compare_status.configure(text="Report copied to clipboard.")

    def _build_text_tab(self):
        """Build the 'Replace Text' tab: a searchable list of the editable
        on-screen strings from ``text/strings.tsv``, each with an in-place
        editor below.  Edits are saved straight to the manifest so the Write
        step patches them into their scene files (size-neutral)."""
        f = self._tab_text
        pad = {"padx": 10, "pady": 4}

        _text_desc = ttk.Label(
            f,
            text="Edit the words shown on the machine's display — high scores, "
                 "menu labels, status text, and the game program's own strings "
                 "(mode titles, battle names — Scene column: \"game program\"). "
                 "Pick your extracted folder, click a string, type the new "
                 "text, and Apply. Each replacement must fit its byte budget "
                 "(the Max column). Some names are the tail end of a longer "
                 "line (EBIRAH inside GODZILLA VS EBIRAH) — edit both rows so "
                 "the line ends with the new name. Build the update on the "
                 "Write tab when you're done.",
            font=(_SANS_FONT, 9, "italic"),
            wraplength=720, justify=tk.LEFT)
        _text_desc.pack(anchor=tk.W, **pad)
        self._register_responsive_wrap(_text_desc)

        # Assets folder row (shared with the Write / other Replace tabs).
        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        self._text_assets_row = row
        ttk.Label(row, text="Project Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._project_mirror_label(row).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._make_assets_scan_buttons(row, "text", self._scan_text_strings)

        # Search + status toolbar.
        tools = ttk.Frame(f); tools.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(tools, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(tools, textvariable=self.text_search_var, width=24).pack(
            side=tk.LEFT, padx=(4, 12))
        ttk.Button(tools, text="Clear all edits",
                   command=self._text_clear_all).pack(side=tk.LEFT)
        # a tester: "Could you jump from the text tab into the scene?"  The
        # Scenes window already jumps here; this is the way back, and it is
        # how you get from a line of text to a picture of where it appears.
        self._text_scene_btn = ttk.Button(
            tools, text="Show in Scenes…", command=self._text_show_in_scene)
        self._text_scene_btn.pack(side=tk.LEFT, padx=(8, 0))
        _Tooltip(
            self._text_scene_btn,
            "Open the Scenes window on the scene that draws the selected "
            "line, with the line picked out — so you can see it in place, "
            "and recolour it there. Stern Spike 2.",
            lambda: self._current_theme)
        # Show: All / Changed / Unchanged — the same dropdown the other
        # Replace tabs got in batch 28, asked for here in batch 29.
        self._build_change_filter(
            tools, "text",
            tip="Narrow the list by what you've already done to it. Changed = "
                "the lines you have edited (they show your new text and are "
                "written on the next build). Unchanged = everything you "
                "haven't touched yet, so a part-finished pass is what's left "
                "in front of you instead of something to scroll past."
        ).pack(side=tk.LEFT, padx=(12, 0))
        # Scene: All / Game program / one scene.  Not every row is a scene —
        # the game program draws its own strings — and a card this size is
        # only workable one scene at a time (batch 29).
        sframe = ttk.Frame(tools)
        sframe.pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(sframe, text="Scene:").pack(side=tk.LEFT)
        self._text_scene_combo = ttk.Combobox(
            sframe, textvariable=self.text_scene_filter_var, state="readonly",
            width=30, values=(self._TEXT_SCENE_ALL,))
        self._text_scene_combo.pack(side=tk.LEFT, padx=(4, 0))
        self._text_scene_combo.bind("<<ComboboxSelected>>",
                                    lambda _e: self._save_staged_changes())
        _Tooltip(
            self._text_scene_combo,
            "Narrow the list to one screen's worth of text. \"Game program\" "
            "is the text the game code draws itself (mode titles, battle "
            "names) — everything else is one scene file, listed with how many "
            "strings it holds. A scene's folder name never changes, so a name "
            "you give it (right-click a row → Name this scene…) sticks, and "
            "it's the same name the Images tab shows for that scene.",
            lambda: self._current_theme)
        self._text_status_lbl = ttk.Label(
            tools, textvariable=self.text_status_var, font=(_SANS_FONT, 9))
        self._text_status_lbl.pack(side=tk.RIGHT)

        # String list.
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        self._text_tree = ttk.Treeview(
            list_frame, columns=("new", "max", "scene", "name"),
            height=8, selectmode="browse")
        self._text_tree.heading("#0", text="On-Screen Text", anchor=tk.W)
        self._text_tree.heading("new", text="New Text", anchor=tk.W)
        self._text_tree.heading("max", text="Max", anchor=tk.W)
        self._text_tree.heading("scene", text="Scene", anchor=tk.W)
        self._text_tree.heading("name", text="Name", anchor=tk.W)
        self._text_tree.column("#0", width=300, minwidth=160)
        self._text_tree.column("new", width=230, minwidth=120)
        # Max: left-aligned and fixed-width.  It used to right-align its
        # numbers in a column that stretched with the window, so the header
        # sat hundreds of pixels from its own numbers and the numbers ended
        # up hard against the Scene column — they read as part of it (batch
        # 29).  Header and numbers now sit together and stay put.
        self._text_tree.column("max", width=56, minwidth=44, anchor=tk.W,
                               stretch=False)
        self._text_tree.column("scene", width=170, minwidth=90, stretch=False)
        self._text_tree.column("name", width=170, minwidth=90)
        self._persist_tree_columns(
            self._text_tree, "text", ("#0", "new", "max", "scene", "name"))
        self._text_sort_cfg = [
            ("#0", "On-Screen Text", False), ("new", "New Text", False),
            ("max", "Max", True), ("scene", "Scene", False),
            ("name", "Name", False)]
        self._wire_sort_headings(self._text_tree, self._text_sort_cfg,
                                 "_text_sort", self._refresh_text_list)
        text_scroll = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self._text_tree.yview)
        self._text_tree.configure(yscrollcommand=text_scroll.set)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._text_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._text_tree.bind("<<TreeviewSelect>>", self._text_on_tree_select)
        self._text_tree.bind("<Double-1>", self._text_on_tree_double)
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self._text_tree.bind(seq, self._text_on_tree_right)

        self._text_empty = ttk.Label(
            list_frame,
            text="Set the project folder on the Extract tab, then click Scan.",
            foreground="#888888", anchor=tk.CENTER, justify=tk.CENTER)
        self._text_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # --- In-place editor for the selected string. ---
        edit = ttk.LabelFrame(f, text=" Edit selected string ")
        edit.pack(fill=tk.X, padx=10, pady=(4, 2))

        orow = ttk.Frame(edit); orow.pack(fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(orow, text="Original:", width=10, anchor=tk.W).pack(
            side=tk.LEFT)
        self._text_orig_var = tk.StringVar(value="")
        self._text_orig_entry = ttk.Entry(
            orow, textvariable=self._text_orig_var, state="readonly")
        self._text_orig_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        nrow = ttk.Frame(edit); nrow.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(nrow, text="New text:", width=10, anchor=tk.W).pack(
            side=tk.LEFT)
        self._text_new_entry = ttk.Entry(
            nrow, textvariable=self.text_new_var, state=tk.DISABLED)
        self._text_new_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._text_new_entry.bind("<Return>", self._text_apply_edit)

        brow = ttk.Frame(edit); brow.pack(fill=tk.X, padx=6, pady=(2, 6))
        self._text_budget_lbl = ttk.Label(
            brow, textvariable=self.text_budget_var, font=(_SANS_FONT, 8))
        self._text_budget_lbl.pack(side=tk.LEFT)
        self._text_apply_all_chk = ttk.Checkbutton(
            brow, text="Apply to every scene with the same original text",
            variable=self.text_apply_all_var)
        self._text_apply_all_chk.pack(side=tk.LEFT, padx=(12, 0))
        # Clarify the matching rule: it keys on the *original* (as-extracted)
        # text, not the current/edited value — so a row you already renamed to
        # coincidentally match another's text is NOT swept up by this.
        _Tooltip(
            self._text_apply_all_chk,
            "Matches scenes by the selected row's ORIGINAL (as-extracted) "
            "text, not its current edited value. Rows you've already changed "
            "to read the same thing keep their own original and aren't "
            "affected.",
            lambda: self._current_theme)
        self._text_apply_btn = ttk.Button(
            brow, text="Apply", state=tk.DISABLED,
            command=self._text_apply_edit)
        self._text_apply_btn.pack(side=tk.RIGHT)
        self._text_revert_btn = ttk.Button(
            brow, text="Revert", state=tk.DISABLED,
            command=self._text_clear_selected)
        self._text_revert_btn.pack(side=tk.RIGHT, padx=(0, 4))

        # Both of these carried a fixed wraplength, so on a wide window they
        # wrapped in the left half with 600px of empty space beside them
        # (batch 29: "the text to the left wraps early").  They follow the
        # window now, like the tab's own intro text.
        self._text_scene_full_var = tk.StringVar(value="")
        _scene_note = ttk.Label(
            edit, textvariable=self._text_scene_full_var,
            font=(_SANS_FONT, 8, "italic"), foreground="#888888",
            wraplength=700, justify=tk.LEFT)
        _scene_note.pack(anchor=tk.W, padx=8, pady=(0, 4))
        self._register_responsive_wrap(_scene_note, margin=60)

        _saved_note = ttk.Label(
            f,
            text="Your edits are saved to text/strings.tsv as you Apply them "
                 "and are written to the card automatically when you build the "
                 "update on the Write tab — no extra step.",
            font=(_SANS_FONT, 9), foreground="#888888",
            wraplength=720, justify=tk.LEFT)
        _saved_note.pack(anchor=tk.W, padx=12, pady=(6, 8))
        self._register_responsive_wrap(_saved_note, margin=48)

    # ---- Replace Text: helpers ---------------------------------------

    @staticmethod
    def _text_scene_label(path):
        """A compact, distinguishing label for a scene path (the full path is
        shown in the editor on select).  Spike 2 scenes are all named
        ``scene.radium`` under an opaque hash dir, so show ``…hash/scene.radium``.
        """
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            return path
        name = parts[-1]
        if name in ("game", "game_real"):
            return "game program"
        parent = parts[-2] if len(parts) >= 2 else ""
        if len(parent) > 14:
            parent = parent[:5] + "…" + parent[-4:]
        return parent + "/" + name if parent else name

    @staticmethod
    def _text_byte_len(s):
        """Byte length of *s* as the engine measures it for the size budget."""
        return len(s.encode("latin1", "replace"))

    @classmethod
    def _text_row_len(cls, r, s):
        """Byte length of *s* for row *r*'s budget check.  Game-program rows
        (the ones carrying an explicit budget) write ``\\n`` as ONE byte — a
        real line break in a multi-line title."""
        if r.get("budget"):
            s = s.replace("\\n", "\n")
        return cls._text_byte_len(s)

    @staticmethod
    def _text_row_budget(r):
        """The row's replacement byte budget: the explicit game-program budget
        when present, else the original's own length (radium in-place rule)."""
        return r.get("budget") or len(r["original"].encode("latin1", "replace"))

    def _text_is_edited(self, r):
        return bool(r["replacement"]) and r["replacement"] != r["original"]

    # ---- Replace Text: scene identity, names + filters ----------------

    # The two fixed entries in the Scene dropdown.  _TEXT_SCENE_PROGRAM
    # doubles as the "not a scene file" selector inside the row filter.
    _TEXT_SCENE_ALL = "All scenes"
    _TEXT_SCENE_PROGRAM = "Game program"

    @staticmethod
    def _text_scene_key(path):
        """The shared container key for a scene path — the SAME key the
        Replace Images tab tags its radium groups under, so a name given on
        either tab is the one name for that scene.  Spike 2 scene folders are
        content hashes that never change, so the key is stable across
        sessions (and across a re-extract of the same card)."""
        return "rad::" + (path or "")

    def _text_scene_name(self, path):
        """The user's friendly name for a scene, or "" — never for the game
        program, which isn't a scene."""
        if not (path or "").lower().endswith(".radium"):
            return ""
        return self._text_scene_names.get(self._text_scene_key(path), "")

    @classmethod
    def _text_row_matches(cls, r, query, want_changed, scene):
        """True when row *r* survives the Text tab's three filters.

        *query* is the lower-cased search box ("" = off) and matches the
        original or the user's new text; *want_changed* is True/False for
        Show = Changed/Unchanged (None = All); *scene* is a scene's card path,
        ``_TEXT_SCENE_PROGRAM`` for the game program, or None for all.
        Deliberately free of Tk so the whole filter is testable."""
        if query:
            if (query not in r["original"].lower()
                    and query not in (r["replacement"] or "").lower()):
                return False
        if want_changed is not None:
            edited = bool(r["replacement"]) and r["replacement"] != r["original"]
            if edited != want_changed:
                return False
        if scene is not None:
            is_scene_file = (r["path"] or "").lower().endswith(".radium")
            if scene == cls._TEXT_SCENE_PROGRAM:
                return not is_scene_file
            return r["path"] == scene
        return True

    def _text_scene_selection(self):
        """What the Scene dropdown currently selects: a scene's card path,
        ``_TEXT_SCENE_PROGRAM``, or None for "All scenes" (also None when the
        saved choice names a scene this folder doesn't have)."""
        choice = (self.text_scene_filter_var.get() or "").strip()
        if not choice or choice == self._TEXT_SCENE_ALL:
            return None
        if choice == self._TEXT_SCENE_PROGRAM:
            return self._TEXT_SCENE_PROGRAM
        return self._text_scene_choices.get(choice)

    @classmethod
    def _text_scene_menu(cls, rows, names):
        """``([display…], {display: path})`` for the Scene dropdown over
        *rows*, given the ``{key: friendly name}`` map.

        Named scenes sort first (they're the ones the user cares about), then
        the rest by their hash label; each entry carries its string count so
        a scene worth opening is obvious before you pick it."""
        counts, labels = {}, {}
        program = 0
        for r in rows:
            path = r["path"] or ""
            if not path.lower().endswith(".radium"):
                program += 1
                continue
            counts[path] = counts.get(path, 0) + 1
            if path not in labels:
                name = names.get(cls._text_scene_key(path), "")
                labels[path] = (name, cls._text_scene_label(path))
        order = sorted(counts,
                       key=lambda p: (not labels[p][0], labels[p][0].lower(),
                                      labels[p][1].lower()))
        values = [cls._TEXT_SCENE_ALL]
        by_display = {}
        if program:
            values.append(cls._TEXT_SCENE_PROGRAM)
        for path in order:
            name, label = labels[path]
            display = "%s — %s (%d)" % (name, label, counts[path]) if name \
                else "%s (%d)" % (label, counts[path])
            values.append(display)
            by_display[display] = path
        return values, by_display

    def _text_rebuild_scene_menu(self):
        """Refresh the Scene dropdown's values from the loaded rows."""
        values, by_display = self._text_scene_menu(
            self._text_rows, self._text_scene_names)
        self._text_scene_choices = by_display
        self._text_scene_displays = {p: d for d, p in by_display.items()}
        combo = getattr(self, "_text_scene_combo", None)
        if combo is not None:
            try:
                combo.configure(values=values)
            except tk.TclError:
                pass

    def _text_scene_rename(self, iid=None):
        """Right-click → Name this scene…: give a scene a name of your own.

        Spike 2 names every scene folder with a content hash, so the Scene
        column is 40 hex characters that mean nothing until you've opened
        them (batch 29).  The name is stored against the scene's container
        key in the folder's own sidecar — the same store the Images tab's
        "Rename group…" uses, so naming a scene here names it there too."""
        if iid is None:
            sel = self._text_tree.selection()
            iid = sel[0] if sel else self._text_current_iid
        try:
            r = self._text_rows[int(iid)]
        except (TypeError, ValueError, IndexError):
            return
        path = r["path"] or ""
        if not path.lower().endswith(".radium"):
            messagebox.showinfo(
                "Name this scene",
                "This is a game-program string — the game code draws it at "
                "runtime, so there's no scene file to name.")
            return
        key = self._text_scene_key(path)
        name = self._ask_text(
            "Name this scene",
            "A name for the scene %s\n(blank clears it):"
            % self._text_scene_label(path),
            initialvalue=self._text_scene_names.get(key, ""))
        if name is None:
            return                              # cancelled
        self._text_set_scene_name(key, " ".join(name.split())[:50])

    def _text_set_scene_name(self, key, name):
        """Store (or clear, on a blank *name*) a scene's friendly name and
        write it straight to the folder's sidecar, keeping the Replace Images
        tab in step when it's looking at the same folder."""
        from ..core import staged_changes
        was = self._text_scene_selection()
        if name:
            self._text_scene_names[key] = name
        else:
            self._text_scene_names.pop(key, None)
        scan_dir = self._text_scan_dir
        if scan_dir and os.path.isdir(scan_dir):
            data = staged_changes.load(scan_dir)
            tags = {str(k): str(v) for k, v in
                    (data.get("image_group_tags") or {}).items()
                    if str(v).strip()}
            if name:
                tags[key] = name
            else:
                tags.pop(key, None)
            data["image_group_tags"] = tags
            staged_changes.save(scan_dir, data)
            if self._same_folder(getattr(self, "_image_scan_dir", ""),
                                 scan_dir):
                self._image_group_tags = dict(tags)
                if hasattr(self, "_image_tree"):
                    self._refresh_image_list()
        self._text_rebuild_scene_menu()
        # A rename rewrites the scene's own entry in the dropdown, so follow
        # it — filtering to a scene and naming it must not drop the filter.
        followed = False
        if was and was != self._TEXT_SCENE_PROGRAM:
            display = self._text_scene_displays.get(was)
            if display and display != self.text_scene_filter_var.get():
                self.text_scene_filter_var.set(display)   # traces the refresh
                followed = True
        if not followed:
            self._refresh_text_list()
        # The refresh rebuilds every row, which drops the selection — put the
        # user back on the line they right-clicked.
        self._text_reselect(getattr(self, "_text_current_iid", None))

    def _text_reselect(self, iid):
        """Re-select row *iid* after a refresh rebuilt the tree (no-op when
        it's gone — a filter may now hide it)."""
        tree = getattr(self, "_text_tree", None)
        if tree is None or iid is None:
            return
        try:
            if tree.exists(str(iid)):
                tree.selection_set(str(iid))
                tree.focus(str(iid))
                tree.see(str(iid))
        except tk.TclError:
            pass

    @staticmethod
    def _same_folder(a, b):
        """True when two paths name the same existing folder (case/sep
        insensitive) — both empty never matches."""
        if not a or not b:
            return False
        return (os.path.normcase(os.path.normpath(a))
                == os.path.normcase(os.path.normpath(b)))

    # ---- Replace Text: scanning / list -------------------------------

    def _scan_text_strings(self):
        """Load ``text/strings.tsv`` from the assets folder into the list.  A
        replacement equal to its original is normalised to '' (unchanged) so the
        New-Text column reads blank for everything the user hasn't touched.

        Runs the read on a worker thread behind the same big animated
        indicator + Cancel-scan button as the other Replace tabs — it used to
        be synchronous, so a manifest on a slow share froze the window with no
        sign anything was happening (feedback batch 22)."""
        import threading
        from ..core import text_manifest
        assets_path = (self.write_assets_var.get() or "").strip()
        self._text_scan_id += 1
        scan_id = self._text_scan_id

        if not assets_path or not os.path.isdir(assets_path):
            self._text_rows = []
            self._text_scan_dir = ""
            self._text_clear_edit_panel()
            self._refresh_text_list()
            self._text_empty.configure(
                text="Set the project folder on the Extract tab, then click Scan.")
            self._text_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            self._set_tab_scanning("text", False)
            return

        self._text_empty.configure(text="Scanning for on-screen text…")
        self._text_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        def _work():
            try:
                loaded, err = text_manifest.load(assets_path), None
            except Exception as e:
                loaded, err = [], e
            if self._text_scan_id != scan_id:
                return
            try:
                self._tk_root().after(
                    0, self._populate_text_after_scan,
                    loaded, err, scan_id, assets_path)
            except (tk.TclError, RuntimeError):
                pass                       # window closed mid-scan

        self._set_tab_scanning("text", True)
        threading.Thread(target=_work, daemon=True).start()

    def _populate_text_after_scan(self, loaded, err, scan_id, scan_dir):
        """Main thread: store the loaded manifest and refresh the list."""
        if self._text_scan_id != scan_id:
            return
        self._set_tab_scanning("text", False)
        if err is not None:
            messagebox.showerror(
                "Couldn't read text",
                "Couldn't read the on-screen-text manifest:\n%s" % err)
        rows = []
        for r in loaded:
            rep = r["replacement"]
            if rep == r["original"]:
                rep = ""                     # rep == orig => unchanged
            row = {"path": r["path"], "original": r["original"],
                   "replacement": rep}
            # Game-program strings carry an explicit byte budget (a standalone
            # name can outgrow its own text — it lives inside a longer line).
            if r.get("budget"):
                row["budget"] = r["budget"]
            rows.append(row)
        self._text_rows = rows
        if not self._same_folder(scan_dir, self._text_scan_dir):
            # New folder: take its filters and its scene names off its own
            # sidecar (the names are the Images tab's group tags — one store,
            # so a scene named on either tab reads the same on both).
            staged = self._load_staged_changes(scan_dir)
            # Default both filters back to "everything" first: a filter
            # carried over from the last project would open the new one
            # looking empty for no visible reason.
            self.text_change_filter_var.set("All")
            self._restore_change_filter("text", staged)
            tags = staged.get("image_group_tags")
            self._text_scene_names = (
                {str(k): str(v).strip()[:50] for k, v in tags.items()
                 if str(v).strip()} if isinstance(tags, dict) else {})
            saved_scene = staged.get("text_scene_filter")
            self.text_scene_filter_var.set(
                saved_scene if isinstance(saved_scene, str) and saved_scene
                else self._TEXT_SCENE_ALL)
        self._text_scan_dir = scan_dir
        self._text_clear_edit_panel()
        self._refresh_text_list()
        if not rows:
            self._text_empty.configure(
                text="No editable on-screen text found in this folder.\n"
                     "Run Extract on a Spike 2 card first — it writes "
                     "text/strings.tsv.")
            self._text_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _maybe_rescan_text(self):
        """Auto-load when the Replace Text tab becomes visible and the folder
        has changed since the last scan."""
        if self._current_mfr is None:
            return
        if not getattr(self._current_mfr.capabilities, "replace_text", False):
            return
        assets_path = (self.write_assets_var.get() or "").strip()
        if assets_path and assets_path != self._text_scan_dir:
            self._scan_text_strings()

    def _refresh_text_list(self):
        """Apply the search box + the Show / Scene filters and repopulate the
        string tree."""
        tree = getattr(self, "_text_tree", None)
        if tree is None:
            return
        self._text_rebuild_scene_menu()
        choice = (self.text_scene_filter_var.get() or "").strip()
        scene = self._text_scene_selection()
        if scene is None and choice and choice != self._TEXT_SCENE_ALL:
            # A saved scene this folder doesn't have (or one whose strings
            # are all filtered out): fall back to All rather than an
            # inexplicably empty list.  The set re-enters through the trace.
            self.text_scene_filter_var.set(self._TEXT_SCENE_ALL)
            return
        tree.delete(*tree.get_children())

        query = (self.text_search_var.get() or "").strip().lower()
        mode = self.text_change_filter_var.get()
        want_changed = (mode == "Changed") if mode in ("Changed",
                                                       "Unchanged") else None
        total = len(self._text_rows)
        edited = sum(1 for r in self._text_rows if self._text_is_edited(r))
        col, desc = self._text_sort

        def _key(pair):
            _i, r = pair
            if col == "new":
                return ((r["replacement"] or "").lower(), r["original"].lower())
            if col == "max":
                return (self._text_row_budget(r),)
            if col == "scene":
                return (self._text_scene_label(r["path"]).lower(),
                        r["original"].lower())
            if col == "name":
                # Unnamed scenes sort last, not first under a blank string.
                name = self._text_scene_name(r["path"])
                return (not name, name.lower(), r["original"].lower())
            return (r["original"].lower(),)  # "#0" on-screen text

        # Filter first, then sort — but keep each row's ORIGINAL index as its
        # iid (other handlers map the iid back via self._text_rows[int(iid)]),
        # so sorting only changes display order, never identity.
        visible = [
            (i, r) for i, r in enumerate(self._text_rows)
            if self._text_row_matches(r, query, want_changed, scene)]
        visible.sort(key=_key, reverse=desc)
        self._show_sort_arrows(tree, self._text_sort_cfg, self._text_sort)
        shown = len(visible)
        for i, r in visible:
            tree.insert(
                "", tk.END, iid=str(i), text=r["original"],
                values=(r["replacement"], self._text_row_budget(r),
                        self._text_scene_label(r["path"]),
                        self._text_scene_name(r["path"])),
                tags=("assigned",) if self._text_is_edited(r) else ())

        if total == 0:
            self.text_status_var.set("")
            self._text_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            try:
                self._text_empty.place_forget()
            except tk.TclError:
                pass
            extra = "  (%d shown)" % shown if shown != total else ""
            self.text_status_var.set(
                "%d string(s), %d edited%s" % (total, edited, extra))

    # ---- Replace Text: editor ----------------------------------------

    def _text_on_tree_select(self, _event=None):
        sel = self._text_tree.selection()
        if not sel:
            return
        iid = sel[0]
        try:
            r = self._text_rows[int(iid)]
        except (ValueError, IndexError):
            return
        self._text_current_iid = iid
        self._text_orig_var.set(r["original"])
        if (r["path"] or "").lower().endswith(".radium"):
            name = self._text_scene_name(r["path"])
            self._text_scene_full_var.set(
                ("Scene “%s”: " % name if name else "Scene: ") + r["path"])
        else:
            self._text_scene_full_var.set(
                "Game program: %s — drawn by game code (mode titles, battle "
                "names). \\n in a string is a real line break. Names shown on "
                "their own may be the END of a longer line; edit both rows so "
                "the line ends with the new name." % r["path"])
        # Pre-fill the entry with the current effective text (the edit, or the
        # original if untouched) so the user edits from what's shown today.
        self.text_new_var.set(r["replacement"] or r["original"])
        self._text_enable_edit(True)
        self._text_update_budget()

    def _text_on_tree_double(self, _event=None):
        if not self._double_click_on_rows(self._text_tree, _event):
            return
        if self._text_current_iid is not None:
            self._text_new_entry.focus_set()

    def _text_on_tree_right(self, event):
        tree = self._text_tree
        row = tree.identify_row(event.y)
        if not row:
            return
        tree.selection_set(row)
        menu = tk.Menu(tree, tearoff=0)
        c = THEMES.get(self._current_theme, {})
        try:
            menu.configure(
                background=c.get("field_bg"), foreground=c.get("fg"),
                activebackground=c.get("select_bg"),
                activeforeground="#ffffff")
        except tk.TclError:
            pass
        menu.add_command(label="Edit…",
                         command=lambda: self._text_new_entry.focus_set())
        menu.add_command(label="Show in Scenes…",
                         command=lambda r=row: self._text_show_in_scene(r))
        menu.add_command(label="Name this scene…",
                         command=lambda r=row: self._text_scene_rename(r))
        try:
            edited = self._text_is_edited(self._text_rows[int(row)])
        except (ValueError, IndexError):
            edited = False
        if edited:
            menu.add_separator()
            menu.add_command(label="Revert this string",
                             command=self._text_clear_selected)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _text_show_in_scene(self, iid=None):
        """a tester: "Could you jump from the text tab into the scene?"

        Open the Scenes window on the scene that draws the selected string,
        with the line itself picked out in the contents list — the scene is
        already the row's own ``path``, so this is the same lookup the Scene
        column shows, not a new search."""
        if iid is None:
            sel = self._text_tree.selection()
            iid = sel[0] if sel else self._text_current_iid
        try:
            r = self._text_rows[int(iid)]
        except (TypeError, ValueError, IndexError):
            messagebox.showinfo(
                "Scenes",
                "Pick a line of text first — the Scenes window then opens on "
                "the scene that draws it.")
            return
        if not (r["path"] or "").lower().endswith(".radium"):
            messagebox.showinfo(
                "Scenes",
                "This is a game-program string — the game code draws it at "
                "runtime, so there's no scene file to show. (It still writes "
                "to the card like any other text edit.)")
            return
        scene_dir = (r["path"] or "").replace("\\", "/").rsplit("/", 1)[0]
        if not scene_dir:
            messagebox.showinfo(
                "Scenes", "This string isn't recorded against a scene file.")
            return
        self._open_scene_browser(preselect_dir=scene_dir,
                                 focus_text=r["original"])

    def _text_enable_edit(self, on):
        state = tk.NORMAL if on else tk.DISABLED
        for w in (getattr(self, "_text_new_entry", None),
                  getattr(self, "_text_apply_btn", None),
                  getattr(self, "_text_revert_btn", None)):
            if w is not None:
                try:
                    w.configure(state=state)
                except tk.TclError:
                    pass

    def _text_clear_edit_panel(self):
        self._text_current_iid = None
        if hasattr(self, "_text_orig_var"):
            self._text_orig_var.set("")
            self._text_scene_full_var.set("")
        self.text_new_var.set("")
        self.text_budget_var.set("")
        self._text_enable_edit(False)

    def _text_update_budget(self, *_a):
        """Refresh the 'N / M bytes' budget readout + Apply enable for the
        current edit (red + disabled when the replacement is too long)."""
        lbl = getattr(self, "_text_budget_lbl", None)
        if lbl is None:
            return
        iid = self._text_current_iid
        if iid is None:
            self.text_budget_var.set("")
            return
        try:
            r = self._text_rows[int(iid)]
        except (ValueError, IndexError):
            return
        orig_len = self._text_row_budget(r)
        new_len = self._text_row_len(r, self.text_new_var.get())
        over = new_len > orig_len
        self.text_budget_var.set(
            "%d / %d bytes%s" % (new_len, orig_len,
                                 "  — too long" if over else ""))
        c = THEMES.get(self._current_theme, {})
        lbl.configure(foreground="#d04040" if over else c.get("fg", "#888888"))
        if hasattr(self, "_text_apply_btn"):
            self._text_apply_btn.configure(
                state=tk.DISABLED if over else tk.NORMAL)

    def _text_apply_edit(self, _event=None):
        iid = self._text_current_iid
        if iid is None:
            return
        try:
            r = self._text_rows[int(iid)]
        except (ValueError, IndexError):
            return
        orig = r["original"]
        new = self.text_new_var.get()
        if self._text_row_len(r, new) > self._text_row_budget(r):
            messagebox.showwarning(
                "Replacement too long",
                "“%s” is %d bytes but only %d fit. On-screen text is patched "
                "in place, so a replacement has to fit the available length "
                "— use a shorter string."
                % (new, self._text_row_len(r, new), self._text_row_budget(r)))
            return
        eff = "" if new == orig else new       # new == orig => unchanged
        prev = r.get("replacement") or ""
        if self.text_apply_all_var.get():
            targets = [rr for rr in self._text_rows if rr["original"] == orig]
        else:
            targets = [r]
        for rr in targets:
            rr["replacement"] = eff
        self._save_text_manifest()
        # Project history (batch 24): full strings, not ellipsized — the file
        # is for grepping months later.
        if eff != prev:
            from ..core import history_log
            copies = ("  (%d copies)" % len(targets)
                      if len(targets) > 1 else "")
            was = ('  (was: "%s")' % prev) if prev else ""
            history_log.record(
                self._text_scan_dir,
                ('text  "%s"  changed to: "%s"%s%s' % (orig, eff, was, copies))
                if eff else
                ('text  "%s"  reverted to original%s%s' % (orig, was, copies)))
        if eff:
            self.append_log(
                'Replace Text: "%s" → "%s"%s'
                % (self._ellipsize(orig), self._ellipsize(eff),
                   " (%d copies)" % len(targets) if len(targets) > 1 else ""),
                "info")
        self._refresh_text_list()
        try:
            self._text_tree.selection_set(iid)
            self._text_tree.see(iid)
        except tk.TclError:
            pass
        self._text_update_budget()

    def _text_clear_selected(self):
        """Revert the selected string (and same-text siblings if 'apply to all'
        is ticked) back to its original."""
        iid = self._text_current_iid
        if iid is None:
            return
        try:
            r = self._text_rows[int(iid)]
        except (ValueError, IndexError):
            return
        orig = r["original"]
        prev = r.get("replacement") or ""
        if self.text_apply_all_var.get():
            targets = [rr for rr in self._text_rows if rr["original"] == orig]
        else:
            targets = [r]
        for rr in targets:
            rr["replacement"] = ""
        self._save_text_manifest()
        if prev:
            from ..core import history_log
            history_log.record(
                self._text_scan_dir,
                'text  "%s"  reverted to original  (was: "%s")%s'
                % (orig, prev,
                   "  (%d copies)" % len(targets) if len(targets) > 1 else ""))
        self.append_log(
            'Replace Text: reverted "%s"%s'
            % (self._ellipsize(orig),
               " (%d copies)" % len(targets) if len(targets) > 1 else ""),
            "info")
        self.text_new_var.set(orig)
        self._refresh_text_list()
        try:
            self._text_tree.selection_set(iid)
            self._text_tree.see(iid)
        except tk.TclError:
            pass
        self._text_update_budget()

    @staticmethod
    def _ellipsize(s, n=40):
        """Trim a string for a one-line log message."""
        return s if len(s) <= n else s[:n - 1] + "…"

    def _text_clear_all(self):
        n_edited = sum(1 for r in self._text_rows if r["replacement"])
        if not n_edited:
            return
        if not messagebox.askyesno(
                "Clear all edits",
                "Remove every on-screen-text edit and restore the originals?"):
            return
        for r in self._text_rows:
            r["replacement"] = ""
        self._save_text_manifest()
        self.append_log("Replace Text: cleared all %d edit(s)" % n_edited,
                        "info")
        self._refresh_text_list()
        if self._text_current_iid is not None:
            try:
                r = self._text_rows[int(self._text_current_iid)]
                self.text_new_var.set(r["original"])
            except (ValueError, IndexError):
                pass
        self._text_update_budget()

    def _save_text_manifest(self):
        """Persist the full row set back to text/strings.tsv (the manifest is the
        model — Write re-reads it).  Returns the edited-string count."""
        from ..core import text_manifest
        if not self._text_scan_dir:
            return 0
        try:
            text_manifest.save(self._text_scan_dir, self._text_rows)
            # Staged text edits are folder state — see _save_staged_changes.
            if self._on_folder_state_written:
                self._on_folder_state_written(self._text_scan_dir)
        except Exception as e:
            messagebox.showerror(
                "Couldn't save",
                "Couldn't write the on-screen-text manifest:\n%s" % e)
            return 0
        return sum(1 for r in self._text_rows if self._text_is_edited(r))

    def _build_phase_steps(self, parent, phases, mode):
        labels = []
        for name in phases:
            lbl = ttk.Label(parent, text=f"○ {name}", font=(_SANS_FONT, 8))
            lbl.pack(side=tk.LEFT, padx=(0, 12))
            labels.append(lbl)
        if mode == "extract":
            self._extract_phase_labels = labels
        else:
            self._write_phase_labels = labels

    def _init_phase_steps(self):
        # Initial labels — apply_manufacturer rebuilds them per-mfr later.
        self._extract_phases = tuple(EXTRACT_PHASES)
        self._write_phases = tuple(WRITE_PHASES)
        self._build_phase_steps(self._extract_phases_frame,
                                self._extract_phases, "extract")
        self._build_phase_steps(self._write_phases_frame,
                                self._write_phases, "write")

    def _rebuild_phase_steps(self, extract_phases, write_phases):
        """Tear down + rebuild the phase indicator widgets when the
        active manufacturer's phase set changes."""
        self._extract_phases = tuple(extract_phases)
        self._write_phases = tuple(write_phases)
        for w in self._extract_phases_frame.winfo_children():
            w.destroy()
        for w in self._write_phases_frame.winfo_children():
            w.destroy()
        self._build_phase_steps(self._extract_phases_frame,
                                self._extract_phases, "extract")
        self._build_phase_steps(self._write_phases_frame,
                                self._write_phases, "write")

    def _on_tab_changed(self, _event=None):
        text = self._current_tab_key()   # stable key, not the short label
        # Switching tabs means leaving whatever preview was playing.  Each tab
        # owns its own player (Replace Audio's spectrogram transport, Replace
        # Video's embedded clip); an ffplay child keeps the sound going under
        # the new tab -- or after the app exits -- unless it's killed here.
        # Entering a tab never auto-plays, so stopping both is always safe.
        self.stop_all_preview_playback()
        if text == "Write":
            self._extract_phases_frame.pack_forget()
            self._write_phases_frame.pack(fill=tk.X, before=self._progress_bar)
            # Auto-scan the assets folder when the Write tab is selected so
            # the Modified Files Preview is populated by the time the user
            # looks at it.  _maybe_rescan_write_preview() applies the correct
            # per-plugin gating and is a no-op when the folder isn't set yet.
            self._maybe_rescan_write_preview()
            # Re-evaluate the ".checksums.md5 missing" warning against the
            # current disk state.  Extract points the assets var at its output
            # dir *before* it writes .checksums.md5, so the trace-driven warning
            # is stale (shows "missing" even though Extract has since created
            # it).  The var never changes again, so refresh it on tab entry.
            self._refresh_write_assets_warning()
        elif text == "Replace Audio":
            # The phase indicators don't apply to the audio tab — staging is
            # a single quick step, not a multi-phase pipeline.
            self._extract_phases_frame.pack_forget()
            self._write_phases_frame.pack_forget()
            self._refresh_audio_ffmpeg_warning()
            self._default_assets_from_extract()
            self._maybe_rescan_audio()
        elif text == "Replace Video":
            self._extract_phases_frame.pack_forget()
            self._write_phases_frame.pack_forget()
            self._refresh_video_ffmpeg_warning()
            self._default_assets_from_extract()
            self._maybe_rescan_video()
        elif text == "Replace Images":
            # The static preview has no player of its own; just refresh the
            # Pillow banner / auto-scan the folder (playback stopped above).
            self._extract_phases_frame.pack_forget()
            self._write_phases_frame.pack_forget()
            self._refresh_image_pillow_warning()
            self._default_assets_from_extract()
            self._maybe_rescan_image()
        elif text == "Replace Text":
            # No player / preview to manage -- just default the folder and
            # (re)load the strings manifest (playback stopped above).
            self._extract_phases_frame.pack_forget()
            self._write_phases_frame.pack_forget()
            self._default_assets_from_extract()
            self._maybe_rescan_text()
        elif text == "Partition Explorer":
            # Read-only browse — the Extract/Write phase strip doesn't apply
            # here (a tester asked what it was for on this tab: nothing).
            self._extract_phases_frame.pack_forget()
            self._write_phases_frame.pack_forget()
            self._pex_default_from_extract()
        elif text == "Default Settings":
            self._extract_phases_frame.pack_forget()
            self._write_phases_frame.pack_forget()
            # The card image mirrors the Extract tab (batch 21 — it's not a
            # separate picker any more): resync on every visit and (re)load
            # whenever it changed.
            src = (self.extract_input_var.get() or "").strip()
            if src and os.path.isfile(src):
                self.settings_image_var.set(os.path.normpath(src))
            img = (self.settings_image_var.get() or "").strip()
            if (img and os.path.isfile(img) and not self._settings_busy
                    and img != getattr(self, "_settings_image_path", None)):
                self._settings_open_image()
        else:
            # Extract / Capture etc. -- no preview player of their own
            # (any audio/video playback was stopped above).
            self._write_phases_frame.pack_forget()
            self._extract_phases_frame.pack(
                fill=tk.X, before=self._progress_bar)

        # Warn (amber top banner) if the source image these assets came from
        # has since changed on disk — only on the asset-editing tabs.
        self._refresh_stale_source_banner(
            on_asset_tab=text in ("Write", "Replace Audio", "Replace Video",
                                  "Replace Images", "Replace Text"))

        # Keep an open tips window in step with the tab now showing
        # (a tester: "the older help text remains").
        self._refresh_tab_help(text)

        # Size the notebook to the tab now showing so a short tab (e.g.
        # Extract) doesn't reserve the tallest tab's height -- the freed
        # space then flows to the expand=True Log pane below.
        self._notebook.after_idle(self._resize_notebook_to_current_tab)

    def _resize_notebook_to_current_tab(self):
        """Set the notebook's pane height to the currently-selected tab's
        natural height.  ttk.Notebook otherwise sizes every tab to the
        tallest one (here the Replace Audio/Video tabs), leaving dead space
        on shorter tabs; pinning it to the current tab lets the Log pane
        flex into that space instead."""
        try:
            cur = self._notebook.nametowidget(self._notebook.select())
        except Exception:
            return
        cur.update_idletasks()
        h = cur.winfo_reqheight()
        if h > 1:
            self._notebook.configure(height=h)
            # Switching to a taller tab (e.g. Write) grows the mfr-view content,
            # but the canvas <Configure> that shows the scrollbar only fires on a
            # manual window resize — so without this the Write tab's lower
            # controls stay clipped with no scrollbar until the user drags the
            # window. Re-apply the scroll geometry now (matches a tester's
            # "controls off the bottom until I resize again").
            self.root.after_idle(self._refresh_mfr_scrollregion)

    # ------------------------------------------------------------------
    # View navigation (picker <-> manufacturer working view)
    # ------------------------------------------------------------------

    def show_picker(self):
        """Display the manufacturer picker and hide the working view."""
        # Leaving the working view (Back button) must also stop any preview
        # still playing -- the notebook tab isn't changing, so _on_tab_changed
        # won't fire to catch it.  No-op on the initial startup call.
        self.stop_all_preview_playback()
        # The scrollable wrapper, not the inner frame, is what's
        # actually packed into the window — un-pack the wrapper so
        # both the canvas and its (sometimes-packed) scrollbar
        # disappear together.
        self._mfr_view_wrapper.pack_forget()
        self._back_btn.pack_forget()
        self._help_btn.pack_forget()
        # Hide the app-title label entirely — the window title bar
        # already says "Pinball Asset Decryptor" so showing it again in
        # the body is just noise (the picker view is header-less too;
        # the manufacturer cards speak for themselves).
        self._title_lbl.pack_forget()
        self._era_badges_frame.pack_forget()
        self._picker_view.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

    def show_mfr_view(self):
        """Display the working view for the currently-selected mfr."""
        self._picker_view.pack_forget()
        # Pack Back (home) leftmost — before the project button, which is
        # already in the left group — then re-pack title so the left
        # cluster reads [home] [project] [title] (David).
        self._back_btn.pack(side=tk.LEFT, padx=(0, 8),
                            before=self._project_btn)
        self._title_lbl.pack_forget()
        self._title_lbl.pack(side=tk.LEFT)
        # Era switcher sits just right of the title (only for multi-era plugins;
        # apply_manufacturer has already built/cleared the pills).
        self._era_badges_frame.pack_forget()
        if self._era_badge_widgets:
            self._era_badges_frame.pack(side=tk.LEFT, padx=(12, 0))
        # "?" tips button joins the right-side header cluster (leftmost of
        # it — the theme/update/disk buttons were packed RIGHT at build time,
        # so a later RIGHT pack lands left of them).
        if not self._help_btn.winfo_manager():
            self._help_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self._mfr_view_wrapper.pack(fill=tk.BOTH, expand=True)
        # Right-size the notebook to the visible tab so the Log pane fills
        # any leftover vertical space (see _resize_notebook_to_current_tab).
        self._notebook.after_idle(self._resize_notebook_to_current_tab)

    def _build_era_badges(self, mfr):
        """(Re)build the header era-switcher pills for *mfr*.  Hidden unless the
        plugin lists more than one era."""
        for child in self._era_badges_frame.winfo_children():
            child.destroy()
        self._era_badge_widgets = {}
        eras = tuple(getattr(mfr, "eras", ()) or ())
        if len(eras) < 2:
            self._era_badges_frame.pack_forget()
            return
        for key, label in eras:
            pill = tk.Label(
                self._era_badges_frame, text=label,
                font=(_SANS_FONT, 8, "bold"), padx=7, pady=1, cursor="hand2")
            pill.pack(side=tk.LEFT, padx=(0, 4))
            pill.bind("<Button-1>",
                      lambda _e, k=key: self._on_era_badge_click(k))
            self._era_badge_widgets[key] = pill
        self._refresh_era_badges()

    def _refresh_era_badges(self):
        """Colour each era pill: the active era stands out (accent), the rest
        recede (muted).  Theme-aware so it follows light/dark switches."""
        if not self._era_badge_widgets:
            return
        c = THEMES[self._current_theme]
        active = (getattr(self._current_mfr, "current_era", "")
                  if self._current_mfr else "")
        for key, pill in self._era_badge_widgets.items():
            if key == active:
                pill.configure(background=c["accent"], foreground="#ffffff")
            else:
                pill.configure(background=c["button"], foreground=c["gray"])

    def _on_era_badge_click(self, era_key):
        """Switch the active plugin to *era_key*.  Clears the Extract input (a
        Spike 2 image isn't a Whitestar ROM, and vice-versa) and re-applies the
        era-specific layout.  Ignored mid-run or when already on that era."""
        mfr = self._current_mfr
        if (mfr is None or self._is_running()
                or not hasattr(mfr, "set_era")
                or getattr(mfr, "current_era", "") == era_key):
            return
        mfr.set_era(era_key)
        self.extract_input_var.set("")
        self.apply_manufacturer(mfr, reset_era=False)
        # The new era has its own prerequisites, and apply_manufacturer only
        # reset the indicators to "[?]" — kick the App's probe worker so they
        # actually run instead of sitting greyed out.
        if self._on_recheck_prereqs is not None:
            self._on_recheck_prereqs()

    def set_back_enabled(self, enabled):
        """Enable / disable the Back button — called by App while a
        pipeline is running so the user can't navigate away mid-extract."""
        self._set_round_icon_enabled(self._back_btn, enabled)

    def _on_picker_select(self, mfr):
        # Forward to the App; it'll call apply_manufacturer + show_mfr_view.
        if self._on_manufacturer_change:
            self._on_manufacturer_change(mfr)

    def _handle_back(self):
        if self._on_back:
            self._on_back()
        else:
            self.show_picker()

    # ------------------------------------------------------------------
    # Per-manufacturer log widgets
    # ------------------------------------------------------------------

    def _swap_log_widget(self, mfr):
        """Show *mfr*'s log widget; create it on first access."""
        for w in self._log_frame.winfo_children():
            w.pack_forget()

        bundle = self._log_widgets.get(mfr.key)
        if bundle is None:
            text = tk.Text(self._log_frame, wrap=tk.WORD,
                           font=(_MONO_FONT, 9), state=tk.DISABLED,
                           height=8)
            scroll = ttk.Scrollbar(self._log_frame, command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            self._apply_log_theme(text)
            # Right-click → Copy / Save As… / Clear (Button-2 + Control-Click
            # cover the Mac trackpad / one-button conventions, matching the
            # Replace trees above).
            for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
                text.bind(seq, self._log_context_menu)
            # Seed the fresh pane with the previous sessions' log tail
            # (dimmed, above a cut line) — the log "keeps" across restarts
            # and in-place updates right where the user already looks
            # (feedback batch 18).  Before the pending-line flush below, so
            # this session's buffered lines land under the cut.
            self._seed_log_history(text)
            bundle = {"text": text, "scroll": scroll}
            self._log_widgets[mfr.key] = bundle

        bundle["scroll"].pack(side=tk.RIGHT, fill=tk.Y)
        bundle["text"].pack(fill=tk.BOTH, expand=True)
        self._log_text = bundle["text"]  # alias for append_log/append_log_link
        # Flush anything logged while the picker was showing (the startup
        # update check) into the first log widget to appear, keeping the
        # timestamps of when the events actually happened.
        if self._pending_log:
            pending, self._pending_log = self._pending_log, []
            for kind, ts, text, extra in pending:
                if kind == "link":
                    self._write_log_link(ts, text, extra)
                else:
                    self._write_log_line(ts, text, extra)

    def _seed_log_history(self, text):
        """Load the previous sessions' log into the TOP of a log widget,
        dimmed, closed out by a cut line — so what happened before a
        restart/update reads as history, not as this session's output.
        Everything before the current session goes in (the file itself is
        size-capped by the roll, so this tops out at a couple of MB); one
        bulk insert keeps even a full file instant.  The pane ends up
        scrolled to the cut line; scroll up for the past.

        Gated on the ⚙-menu "Show previous sessions in the log" toggle and
        idempotent (the cut line marks a seeded pane), so it serves both
        widget creation and re-enabling the toggle mid-session."""
        if not self.show_log_history_var.get():
            return
        if text.tag_ranges("cut"):
            return                      # already seeded
        lines = session_log.previous_tail()
        if not lines:
            return
        text.configure(state=tk.NORMAL)
        # Cut line first, then the history above it — two inserts at "1.0"
        # land in visual order history → cut, above any live lines already
        # in the widget (the mid-session re-enable case).
        text.insert(
            "1.0",
            "──────────── earlier sessions above · this session below "
            "────────────\n", "cut")
        text.insert("1.0", "\n".join(lines) + "\n", "hist")
        text.configure(state=tk.DISABLED)
        text.see(tk.END)

    def _remove_log_history(self, text):
        """Strip the seeded history + cut line from a pane (the ⚙ toggle
        turned off) — live session lines are untouched.  The tags cover
        exactly what seeding inserted, trailing newlines included."""
        text.configure(state=tk.NORMAL)
        # "cut" sits below "hist"; delete it first so the hist indices
        # (earlier in the widget) stay valid.
        for tag in ("cut", "hist"):
            rng = text.tag_ranges(tag)
            for i in range(len(rng) - 2, -1, -2):
                text.delete(rng[i], rng[i + 1])
        text.configure(state=tk.DISABLED)

    def _on_toggle_log_history(self):
        """⚙ → "Show previous sessions in the log" flipped: apply to every
        existing pane immediately (they're per-manufacturer) and persist."""
        show = bool(self.show_log_history_var.get())
        for bundle in self._log_widgets.values():
            if show:
                self._seed_log_history(bundle["text"])
            else:
                self._remove_log_history(bundle["text"])
        if self._on_show_log_history_change:
            self._on_show_log_history_change(show)

    def _apply_log_theme(self, text_widget):
        c = THEMES[self._current_theme]
        text_widget.configure(
            background=c["field_bg"], foreground=c["fg"],
            insertbackground=c["fg"], selectbackground=c["select_bg"])
        text_widget.tag_configure("info", foreground=c["fg"])
        text_widget.tag_configure("success", foreground=c["success"])
        text_widget.tag_configure("error", foreground=c["error"])
        text_widget.tag_configure("ts", foreground=c["timestamp"])
        text_widget.tag_configure("link", foreground=c["link"])
        # Previous-session history: dimmed like timestamps so it visibly
        # reads as "the past"; the cut line a touch stronger.
        text_widget.tag_configure("hist", foreground=c["timestamp"])
        text_widget.tag_configure("cut", foreground=c["gray"])

    # ------------------------------------------------------------------
    # Manufacturer switching
    # ------------------------------------------------------------------

    def apply_manufacturer(self, mfr, reset_era=True):
        """Reconfigure the UI for *mfr*.  Called on initial load + on switch.

        ``reset_era`` (default True) resets an era-switching manufacturer
        (Stern) to its default era so a fresh switch shows the default
        layout; the era-driven re-apply in ``_set_badge`` passes False so it
        keeps the just-detected era.
        """
        self._current_mfr = mfr
        if reset_era and hasattr(mfr, "set_era"):
            mfr.set_era("")          # "" => the manufacturer's default era
        caps = mfr.capabilities
        # Reset audio-export support to the optimistic default; the
        # extract-badge refresh later in this method re-probes it for
        # the actual selected file.
        self._extract_audio_supported = True

        self._suppress_mfr_event = True
        self.mfr_var.set(mfr.display)
        self._suppress_mfr_event = False

        # Title bar shows just the mfr name (window title bar already
        # has the app name).  The hardware-generation badge (e.g. Stern's
        # "SPIKE 2") lives on the picker card, not here — see picker.py.
        self._title_lbl.configure(text=mfr.display)
        # Era switcher pills (multi-era plugins only) — rebuilt here so the
        # active era is highlighted after both a manual switch and an
        # auto-detected one (both route through apply_manufacturer).
        self._build_era_badges(mfr)

        # Per-mfr phase indicators (defaults to core EXTRACT/WRITE_PHASES).
        self._rebuild_phase_steps(mfr.extract_phases, mfr.write_phases)

        # Per-mfr prereq indicators - start in "checking" state.  The
        # App's worker thread fills in actual results via
        # set_prereq_result() shortly after.
        self.reset_prereqs(mfr.prerequisites)

        # Per-mfr log: each mfr keeps its own scrollback across switches.
        self._swap_log_widget(mfr)

        # Make sure the working view is visible (and the picker isn't).
        self.show_mfr_view()

        # Per-format label phrasing.  A manufacturer may set a human noun
        # (``extract_input_label``, e.g. Stern's "Card image") that wins over
        # the raw primary extension (".upd:" / ".img:") or the generic "Input:".
        noun = getattr(mfr, "extract_input_label", None)
        primary_ext = (mfr.input_spec.extensions[0]
                       if mfr.input_spec.extensions else "file")
        if noun:
            self._extract_input_lbl.configure(text=f"{noun}:")
            self._write_original_lbl.configure(text=f"Original {noun}:")
        else:
            self._extract_input_lbl.configure(
                text=f"{primary_ext}:" if primary_ext.startswith(".")
                else "Input:")
            self._write_original_lbl.configure(
                text=f"Original {primary_ext}:" if primary_ext.startswith(".")
                else "Original:")

        # Widen the Write tab's whole label column when the noun overflows the
        # default 16 chars (Stern's "Original Card image:" was clipping to
        # "Original Card imag" — a tester 5).  All the column's labels move
        # together so the entry fields stay aligned.
        col_w = max(16, len(str(self._write_original_lbl.cget("text"))) + 1)
        for _lbl in getattr(self, "_write_col_labels", []):
            _lbl.configure(width=col_w)

        # Show/hide tabs by capability.
        self._configure_tab("Replace Audio", caps.replace_audio)
        self._configure_tab("Replace Video", caps.replace_video)
        self._configure_tab("Replace Images", caps.replace_image)
        self._configure_tab("Replace Text", caps.replace_text)
        self._configure_tab("Write", caps.write)
        self._configure_tab("Mod Pack", caps.modpack)
        self._configure_tab("Partition Explorer",
                            getattr(caps, "partition_explorer", False))
        self._configure_tab("Default Settings",
                            getattr(caps, "settings_editor", False))
        self._configure_tab("Compare", getattr(caps, "compare", False))
        self._configure_tab("Emulate", getattr(caps, "emulate", False))
        # The Mod Pack tab is shared, but the "Transfer Mods to New Version"
        # section only fits plugins whose vendor re-lays-out the card across
        # versions (Stern) — show it only for those, hide it for the rest.
        if hasattr(self, "_modpack_transfer_frame"):
            if getattr(caps, "mod_transfer", False):
                self._modpack_transfer_frame.pack(fill=tk.X, padx=10, pady=4)
                self._prefill_transfer_dst()
            else:
                self._modpack_transfer_frame.pack_forget()
        # New mfr: close the Image Info window so a previous manufacturer's
        # report can't sit open under the new one's name.
        self._info_reset()
        # New mfr: drop the Compare tab's report the same way (its tree
        # would otherwise show a previous manufacturer's diff).
        self._compare_reset()
        # New mfr: drop any text rows loaded for the previous one so a stale
        # manifest can't leak across a manufacturer switch.
        self._text_rows = []
        self._text_scan_dir = ""
        if hasattr(self, "_text_tree"):
            self._text_clear_edit_panel()
            self._refresh_text_list()
        # New mfr: clear any audio slots/assignments from the previous one
        # so a stale list can't leak across a manufacturer switch.
        self._audio_slots = []
        self._audio_slots_by_rel = {}
        self._audio_assignments = {}
        self._audio_loop_flags = {}
        self._audio_keep_full_flags = {}
        self._audio_scan_dir = ""
        self._audio_dup_groups = None
        self._audio_dup_scan_dir = ""
        self.audio_group_dups_var.set(False)  # off by default per mfr
        # Show the per-track "Loop" column only for plugins that support
        # resource-level loop injection (BOF), and the "Full" (keep full length)
        # column only for plugins with a per-slot length override (JJP).  They
        # never show together; hide both for everyone else.
        # The optional toggle column sits BEFORE the stretchy Replacement
        # column, not after it.  ttk has no horizontal scroll, so when the
        # total column width exceeds the widget it clips the rightmost column;
        # keeping the narrow toggle ahead of the stretch column means it's
        # always drawn and only Replacement (which stretches anyway) absorbs
        # any overflow — the JJP "Full" / BOF "Loop" column no longer vanishes
        # on initial load.
        if hasattr(self, "_audio_tree"):
            if getattr(caps, "audio_loop_inject", False):
                self._audio_tree["displaycolumns"] = ("len", "fmt", "type",
                                                      "loop", "rep")
            elif getattr(caps, "audio_keep_length_override", False):
                self._audio_tree["displaycolumns"] = ("len", "fmt", "type",
                                                      "keep", "rep")
            else:
                self._audio_tree["displaycolumns"] = ("len", "fmt", "type",
                                                      "rep")
        # "Group duplicates" checkbox: only for plugins that implement the
        # duplicate scan (CGC).
        if hasattr(self, "_audio_dup_group_cb"):
            if getattr(mfr, "find_duplicate_sounds", None):
                if not self._audio_dup_group_cb.winfo_ismapped():
                    self._audio_dup_group_cb.pack(
                        side=tk.LEFT, padx=(0, 12),
                        before=self._audio_change_filter_frame)
            else:
                self._audio_dup_group_cb.pack_forget()
        self._audio_clear_preview()
        self._refresh_audio_list()
        # Force the Trim/pad checkbox on + disabled for plugins whose Write
        # always length-matches (e.g. JJP, Spike 2, CGC's Pulp Fiction), so the
        # toggle isn't misleading.  No extract is scanned yet here, so a plugin
        # whose answer is per-extract (CGC) reports its default; the lock is
        # re-applied against the real folder after an audio scan.
        self._apply_audio_trim_lock(mfr)
        # The Advanced… / Profile vs stock buttons drive env vars read solely
        # by the Spike 2 encoder, so show them for Stern and hide them
        # elsewhere rather than offer inert controls.  They share a row with the
        # Trim/pad checkbox, which stays for every manufacturer.
        if hasattr(self, "_audio_adv_btn"):
            if mfr.key == "stern":
                if not self._audio_profile_btn.winfo_ismapped():
                    self._audio_profile_btn.pack(side=tk.RIGHT)
                    self._audio_adv_btn.pack(side=tk.RIGHT, padx=(0, 6))
            else:
                self._audio_adv_btn.pack_forget()
                self._audio_profile_btn.pack_forget()
        # Same clean slate for the video tab.
        self._video_slots = []
        self._video_slots_by_rel = {}
        self._video_assignments = {}
        self._video_scan_dir = ""
        self._video_clear_preview()
        self._refresh_video_list()
        if hasattr(self, "_video_trim_tip"):
            # Per-plugin length guidance lives in the Trim checkbox's hover
            # tooltip (the old visible note label wrapped awkwardly and
            # squeezed the log — feedback batches 14 and 16).
            note = (mfr.video_length_note() or "").strip()
            self._video_trim_tip.text = (
                "When on, a replacement longer or shorter than the original "
                "clip is trimmed or padded to the original length during the "
                "re-encode. When off, the replacement's own length is kept."
                + (("\n\n" + note) if note else ""))
        # Same clean slate for the image tab.
        self._image_slots = []
        self._image_slots_by_rel = {}
        self._image_assignments = {}
        self._image_scan_dir = ""
        self._image_clear_preview()
        self._refresh_image_list()
        if hasattr(self, "_image_note_lbl"):
            note = mfr.image_note() or ""
            self._image_note_lbl.configure(text=note)
            # Hide the row entirely when there's no note, so the tab doesn't
            # carry an empty gap (a tester: the fitting-rules line moved to
            # Help).  Plugins that DO return a note still show it.
            if note:
                self._image_note_lbl.pack(anchor=tk.W, padx=30, pady=(0, 2))
            else:
                self._image_note_lbl.pack_forget()

        # Write-tab editable-folder hint is BOF-only — see widget
        # construction comment for why.  Showing it on JJP/CGC/PB/Spooky
        # actively misleads users into thinking the app re-encodes
        # arbitrary input formats (it doesn't on those plugins —
        # replacements must already be in the game's native format).
        if mfr.key == "bof" and caps.write:
            if not self._write_editable_hint.winfo_ismapped():
                self._write_editable_hint.pack(
                    anchor=tk.W, padx=26, pady=(0, 4),
                    before=self._write_output_row_ref)
        else:
            self._write_editable_hint.pack_forget()

        # Update-version date control (BOF) — sits just above the output
        # row.  Refresh its concrete date from the current assets folder.
        if getattr(caps, "write_version_date", False) and caps.write:
            if not self._write_version_frame.winfo_ismapped():
                self._write_version_frame.pack(
                    fill=tk.X, padx=10, pady=(2, 2),
                    before=self._write_output_row_ref)
            self._refresh_write_version_field()
        else:
            self._write_version_frame.pack_forget()

        # JJP (or any future plugin with caps.direct_ssd) gets an extra
        # "From ISO / From SSD" radio row above the input rows on both
        # the Extract and Write tabs.  Everyone else: reset the source
        # to "iso" and hide the radio + the SSD-only frames.
        if caps.direct_ssd:
            # Per-manufacturer wording for the source/destination toggle (Stern
            # Spike is an SD card, JJP an ISO/SSD; see Manufacturer defaults).
            self._extract_iso_radio.configure(
                text=getattr(mfr, "extract_iso_label", "From ISO"))
            self._extract_ssd_radio.configure(
                text=getattr(mfr, "extract_ssd_label", "From SSD"))
            self._write_iso_radio.configure(
                text=getattr(mfr, "write_iso_label", "Build USB ISO"))
            self._write_ssd_radio.configure(
                text=getattr(mfr, "write_ssd_label", "Write to SSD"))
            # Say what each destination actually DOES — batch 22 (a tester
            # thought these repeated the Build / flash dialog's checkboxes).
            _noun = getattr(mfr, "direct_medium_noun", "SSD")
            self._write_iso_tip.text = (
                "Build a modified copy of the whole image to a FILE on this "
                "PC. Nothing is written to a %s — use \"Build / flash %s…\" "
                "below to put the finished image onto one (that erases and "
                "rewrites the entire %s)." % (_noun, _noun, _noun))
            self._write_ssd_tip.text = (
                "Write your changed files straight onto a connected %s, in "
                "place — no image file, and the rest of the %s is left alone. "
                "This is NOT the same as flashing: \"Build / flash %s…\" "
                "replaces the whole %s with a fresh image."
                % (_noun, _noun, _noun, _noun))
            # Medium-aware red safety banner + admin panel (JJP=SSD/ISO,
            # Stern=SD card); fall back to the JJP-flavoured defaults.
            safety = getattr(mfr, "direct_safety_text", None)
            if safety:
                self._extract_ssd_warn.configure(text=safety)
                self._write_ssd_warn.configure(text=safety)
            admin_body = self._admin_body_text(mfr)
            for _admin_fr in (self._extract_admin_frame,
                              self._write_admin_frame):
                _lbl = getattr(_admin_fr, "body_label", None)
                if _lbl is not None:
                    _lbl.configure(text=admin_body)
            self._extract_source_frame.pack(
                fill=tk.X, padx=10, pady=(6, 0),
                before=self._extract_input_row)
            self._write_source_frame.pack(
                fill=tk.X, padx=10, pady=(6, 0),
                before=self._write_upd_row)
            # Re-apply whichever source the user last had selected so
            # the right rows are visible.
            self._on_input_source_change("extract")
            self._on_input_source_change("write")
        else:
            self._extract_source_frame.pack_forget()
            self._write_source_frame.pack_forget()
            self.extract_input_source_var.set("iso")
            self.write_input_source_var.set("iso")
            # Force the ISO layout in case we're switching FROM a
            # direct_ssd plugin TO one without it.
            self._extract_drive_row.pack_forget()
            self._extract_ssd_warn.pack_forget()
            self._extract_admin_frame.pack_forget()
            self._extract_macos_fda_frame.pack_forget()
            self._write_drive_row.pack_forget()
            self._write_ssd_warn.pack_forget()
            self._write_admin_frame.pack_forget()
            self._write_admin_unc_hint.pack_forget()
            self._write_macos_fda_frame.pack_forget()
            # Modified Files Preview — shown for every plugin that can
            # build an update (JJP also gets it in SSD mode, handled in the
            # direct_ssd branch above) so modders can see exactly which
            # files they've edited since Extract before hitting Write.
            if mfr.capabilities.write:
                self._write_preview_frame.pack(
                    fill=tk.BOTH, expand=True, padx=10, pady=(4, 4),
                    before=self._write_filename_lbl)
                # Kick a scan so users see the tree populated when they
                # switch tabs.  Has no effect if the assets folder
                # isn't set yet — the scan will re-fire when the
                # textbox is filled in.
                self._scan_write_preview()
            else:
                self._write_preview_frame.pack_forget()
            # Restore the build-mode button label (plugins without a
            # destination toggle only ever build an update).
            self._write_btn.configure(
                text=getattr(mfr, "write_build_button", "Build update"))
            # Make sure the ISO rows are visible — _on_input_source_change
            # would unpack/repack them, but a non-direct_ssd plugin may
            # have inherited an unpacked state from a prior switch.
            try:
                self._extract_input_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._extract_output_row())
            except tk.TclError:
                pass
            try:
                self._write_upd_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_assets_row())
            except tk.TclError:
                pass
            if self._write_output_row_ref:
                self._write_output_row_ref.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_filename_lbl)

        # Show/hide the per-category Extract filters (JJP).  Packed
        # just below the output-folder warning so it sits above the
        # phase indicator — same shape as the standalone JJP
        # decryptor.  Plugins without the capability never see it.
        if caps.asset_filters:
            self._asset_filters_frame.pack(
                fill=tk.X, padx=10, pady=(4, 0),
                before=self._extract_action_row)
        else:
            self._asset_filters_frame.pack_forget()

        # Advanced dongle-decrypt checkbox (JJP).  Off by default; sits just
        # below the asset filters.  Reset the toggle on every mfr switch so it
        # never carries a stale ON into a plugin that doesn't support it.
        if getattr(caps, "dongle_extract", False):
            self._dongle_extract_frame.pack(
                fill=tk.X, padx=10, pady=(0, 0),
                before=self._extract_action_row)
        else:
            self._dongle_extract_frame.pack_forget()
            self.extract_dongle_var.set(False)

        # Generic per-type Extract checkboxes (capabilities.extract_categories).
        # Rebuilt each time so the labels match the active plugin; default all
        # on.  These live inline in the action row's option cluster: an
        # "Extract:" label sized like the field-label column (so the checkboxes
        # line up under the path entries) followed by one checkbox per type.
        for child in self._extract_categories_frame.winfo_children():
            child.destroy()
        self._extract_category_vars = {}
        cats = tuple(getattr(caps, "extract_categories", ()) or ())
        if cats:
            ttk.Label(self._extract_categories_frame, text="Extract:",
                      width=14, anchor=tk.W,
                      font=(_SANS_FONT, 9)).pack(side=tk.LEFT)
            for key, label in cats:
                var = tk.BooleanVar(value=True)
                self._extract_category_vars[key] = var
                chk = ttk.Checkbutton(
                    self._extract_categories_frame, text=label, variable=var,
                    command=self._update_autoname_state)
                chk.pack(side=tk.LEFT, padx=(0, 12))
                _Tooltip(chk, _EXTRACT_CATEGORY_TIPS.get(
                    key, f"Include {label.lower()} when extracting."),
                    lambda: self._current_theme)
            self._extract_categories_frame.pack(side=tk.LEFT)
        else:
            self._extract_categories_frame.pack_forget()
        # Restore the persisted per-mfr Extract options onto the vars just
        # (re)built above — the category checkboxes start default-on every
        # apply/era switch, so this is where the saved state lands.  Also
        # runs _update_autoname_state() (auto-name options operate on
        # extracted audio, so they gray out when Audio is unchecked).
        self._apply_saved_extract_options()

        # Show/hide the capture toggles on the Extract tab.
        if caps.capture:
            # Capture-primary plugins (capture but NO static extract, e.g.
            # Data East — their DMD animations are compressed and only
            # render under emulation): hide the "Basic extract" toggle and
            # the gameplay-sim checkbox, and default capture on, since
            # capture is their only path.
            capture_primary = not caps.extract
            if capture_primary:
                self._basic_extract_frame.pack_forget()
                self.static_extract_var.set(False)
                self.capture_mode_var.set(True)
                self._capture_gameplay_check.pack_forget()
            else:
                self._basic_extract_frame.pack(
                    fill=tk.X, padx=10, pady=(6, 0),
                    before=self._extract_action_row)
                self._capture_gameplay_check.pack(side=tk.LEFT, padx=(12, 0))
            self._capture_frame.pack(fill=tk.X, padx=10, pady=(2, 0),
                                     before=self._extract_action_row)
            # Re-show the capture-help line (the non-capture branch forgets it)
            # just below the capture controls.
            self._capture_help.pack(anchor=tk.W, padx=24, pady=(2, 0),
                                    before=self._extract_action_row)
            self._update_capture_help_text()
            # Mount the DMD preview (in the mfr view, just above the phase
            # indicators) so it's ready to surface on the first frame and
            # has full room — the notebook tab would clip its height.
            self._dmd_preview_frame.pack(
                fill=tk.X, padx=10, pady=(4, 0),
                before=self._status_frame)
            self.root.after_idle(self._refresh_mfr_scrollregion)
            # Switch matrix is mounted on capture_ready (after the
            # active script is known).
        else:
            self._basic_extract_frame.pack_forget()
            self._capture_frame.pack_forget()
            # Fully remove the capture-help line (not just blank its text) so it
            # doesn't reserve an empty line between the Output-folder warning and
            # the Extract row — that stray gap pushed Extract down and made the
            # 3-step spacing look uneven (a tester Extract #1).
            self._capture_help.pack_forget()
            self._capture_help.configure(text="")
            self.capture_mode_var.set(False)
            # Restore basic-extract default for non-Williams plugins
            # (they always run their normal extract).
            self.static_extract_var.set(True)
            self._dmd_preview_frame.pack_forget()
            self._stop_dmd_preview_pump()
            self._switch_matrix_frame.pack_forget()
            self._manual_press_fn = None
            self.root.after_idle(self._refresh_mfr_scrollregion)

        # Show/hide the auto-transcribe checkboxes.  They build a
        # callouts.csv from the extracted WAVs — and only the basic/
        # static extract emits standalone WAVs, so for capture-capable
        # plugins they sit under "Basic extract" and track it.
        self._update_transcribe_visibility()
        self._update_music_id_visibility()
        self._update_duration_names_visibility()
        self._update_decode_dmd_visibility()
        self._update_chain_deltas_visibility()

        # Show/hide apply-delta + install help inside Write tab
        if caps.apply_delta:
            self._delta_frame.pack(fill=tk.X, padx=10, pady=(8, 4))
        else:
            self._delta_frame.pack_forget()

        install = mfr.write_install_help()
        if install and caps.write:
            self._install_lbl.configure(text=install)
            self._install_frame.pack(fill=tk.X, padx=10, pady=(8, 4))
        else:
            self._install_frame.pack_forget()

        # Build / flash (Stern Spike 2, CGC) — for flash-capable plugins
        # this dialog is the SINGLE build entry point: its build-only mode
        # is the old Build button, so the plain Build button hides here
        # (David: "Build / flash SD card…" next to "Build SD-card image"
        # read as two build buttons).  Everyone else keeps the plain Build
        # button and no flash action.  Repacked from scratch so the
        # right-hand action group's order is deterministic across mfr
        # switches (`after=` on a side=RIGHT pack places a widget visually
        # LEFT of its anchor).
        for btn in (self._flash_btn, self._diagnose_btn,
                    self._revert_all_btn):
            btn.pack_forget()
        if caps.flash_image:
            self._write_btn.pack_forget()
            # Label + tooltip are manufacturer-flavoured: Stern/CGC keep the
            # dd-style "Build / flash SD card…", JJP reads as USB-stick prep
            # (format + copy the installer files, not a raw image write).
            self._flash_btn.configure(text=self._flash_btn_text())
            self._flash_btn_tip.text = (
                getattr(mfr, "flash_button_tip", None)
                or self._FLASH_BTN_TIP)
            self._flash_btn.pack(side=tk.RIGHT)
        elif not self._write_btn.winfo_manager():
            self._write_btn.pack(side=tk.RIGHT)
        # Card diagnostics — manufacturers that can read a failed install's
        # on-card log back (CGC's diagnose_card).  Beside Flash, so it can
        # only show when flashing does too.
        if caps.flash_image and getattr(mfr, "diagnose_card", None):
            self._diagnose_btn.pack(side=tk.RIGHT, padx=(0, 6),
                                    after=self._flash_btn)
        else:
            self._diagnose_btn.pack_forget()

        # "Revert all changes…" — only meaningful when this plugin has a Replace
        # surface (the assets folder is where staged edits live).  Anchors on
        # whichever primary action button this plugin shows.
        has_replace = (caps.replace_audio or caps.replace_video
                       or caps.replace_image or caps.replace_text)
        if has_replace and self._on_revert_all is not None:
            anchor = (self._flash_btn if caps.flash_image
                      else self._write_btn)
            self._revert_all_btn.pack(
                side=tk.RIGHT, padx=(0, 6), after=anchor)
        else:
            self._revert_all_btn.pack_forget()

        # The scan control goes LAST in the right-hand group's packing order,
        # which for side=RIGHT puts it at the group's LEFT end (batch 22:
        # right-justified like every other tab's Scan, but still visibly
        # separate from the action buttons via the wide trailing gap).
        self._write_preview_refresh_btn.pack_forget()
        self._write_preview_refresh_btn.pack(side=tk.RIGHT, padx=(0, 24))

        # Refresh detect badges (file might already be selected from
        # the previous manufacturer's settings — unusual but possible).
        self._update_extract_badge()
        self._update_write_badge()

        # If we're entering a direct_ssd plugin in SSD mode without
        # admin, make sure the Extract / Apply buttons are disabled.
        self._refresh_ssd_run_buttons()

        # Populate / refresh the File Name box for the newly-applied plugin:
        # its suffix (and thus the default build name) may differ from the
        # previous one even when the original is unchanged.
        self._update_write_filename()

    def _update_autoname_state(self):
        """Gray out the Auto-name call-outs / music options when the Audio
        Extract category is unchecked — they rename extracted audio, so there's
        nothing for them to do without it.  No-op for plugins that don't expose
        an Audio category (the options stay enabled)."""
        audio_var = self._extract_category_vars.get("audio")
        enabled = audio_var is None or bool(audio_var.get())
        flag = "!disabled" if enabled else "disabled"
        for chk in (getattr(self, "_transcribe_check", None),
                    getattr(self, "_music_id_check", None),
                    getattr(self, "_duration_names_check", None)):
            if chk is not None:
                try:
                    chk.state([flag])
                except tk.TclError:
                    pass

    # ---- Persisted Extract options (a tester: checkboxes don't stick) ----

    def set_extract_options(self, opts):
        """Restore this manufacturer's saved Extract-tab options.

        Called by the App on every manufacturer switch with the settings.json
        section (``{}`` when nothing was saved → clean defaults).  Missing
        keys fall back to the build defaults: auto-name off, every category
        on, JJP filesystem dump off."""
        self._saved_extract_options = dict(opts or {})
        self._apply_saved_extract_options()

    def get_extract_options(self):
        """Snapshot the Extract-tab options for persistence (inverse of
        :meth:`set_extract_options`)."""
        opts = {
            "auto_name_callouts": bool(self.transcribe_var.get()),
            "auto_name_music": bool(self.music_id_var.get()),
            "duration_names": bool(self.duration_names_var.get()),
        }
        if self._extract_category_vars:
            opts["categories"] = {k: bool(v.get())
                                  for k, v in
                                  self._extract_category_vars.items()}
        caps = getattr(self._current_mfr, "capabilities", None)
        if caps is not None and getattr(caps, "asset_filters", False):
            opts["asset_filters"] = {
                "graphics": bool(self.extract_graphics_var.get()),
                "sounds": bool(self.extract_sounds_var.get()),
                "filesystem": bool(self.extract_filesystem_var.get()),
            }
        return opts

    def _apply_saved_extract_options(self):
        """Push the stashed options onto the Tk vars.  Runs both from
        set_extract_options() and at the end of apply_manufacturer()'s
        category rebuild (which resets those vars to default-on)."""
        opts = self._saved_extract_options
        self.transcribe_var.set(bool(opts.get("auto_name_callouts", False)))
        self.music_id_var.set(bool(opts.get("auto_name_music", False)))
        self.duration_names_var.set(bool(opts.get("duration_names", False)))
        cats = opts.get("categories", {})
        for key, var in self._extract_category_vars.items():
            var.set(bool(cats.get(key, True)))
        filt = opts.get("asset_filters", {})
        self.extract_graphics_var.set(bool(filt.get("graphics", True)))
        self.extract_sounds_var.set(bool(filt.get("sounds", True)))
        self.extract_filesystem_var.set(bool(filt.get("filesystem", False)))
        self._update_autoname_state()

    def _on_extract_mode_toggle(self):
        """Either Basic-extract or Capture checkbox toggled."""
        self._update_capture_help_text()
        self._refresh_extract_phases()
        # Transcribe is only meaningful when the basic extract runs.
        self._update_transcribe_visibility()
        self._update_music_id_visibility()
        self._update_duration_names_visibility()

    def _on_dongle_extract_toggle(self):
        """The advanced 'Decrypt using the game's HASP dongle' checkbox was
        toggled — the dongle flow has a different phase list, so refresh the
        step indicator."""
        self._refresh_extract_phases()

    def _refresh_extract_phases(self):
        """Rebuild the extract phase indicator for the current extract
        mode and the detected game's audio-export support.

        The Basic-extract and Capture checkboxes are independent —
        four states matter:

          * basic ON,  capture ON  → combined phases (static + capture)
          * basic ON,  capture OFF → static-only (default)
          * basic OFF, capture ON  → capture-only (no static)
          * basic OFF, capture OFF → nothing to do; warn but allow
                                     the toggle so the user can fix it

        On top of that, the dedicated DCS "Extract audio" phase is
        dropped for games whose audio we can't export (pre-DCS).
        """
        if self._current_mfr is None:
            return
        mfr = self._current_mfr
        # SSD-mode swap: when the source radio is on "ssd", the
        # Direct-SSD pipeline skips the ISO extract/build phases.
        # Same logic for write below.
        extract_ssd = (mfr.capabilities.direct_ssd
                       and self.extract_input_source_var.get() == "ssd")
        write_ssd = (mfr.capabilities.direct_ssd
                     and self.write_input_source_var.get() == "ssd")
        # Dongle-decrypt (ISO mode only): the dongle-bearing pipeline runs the
        # extra Chroot / Dongle / Compile phases, so it has its own step list.
        extract_dongle = (getattr(mfr.capabilities, "dongle_extract", False)
                          and not extract_ssd
                          and self.extract_dongle_var.get())

        if extract_dongle and getattr(mfr, "dongle_extract_phases", None):
            phases = mfr.dongle_extract_phases
        elif extract_ssd and mfr.direct_ssd_extract_phases:
            phases = mfr.direct_ssd_extract_phases
        else:
            basic = self.static_extract_var.get()
            capture = (self.capture_mode_var.get()
                       and mfr.capabilities.capture)
            if basic and capture:
                phases = mfr.combined_phases or mfr.extract_phases
            elif capture and not basic:
                phases = mfr.capture_phases or mfr.extract_phases
            else:  # basic only, or neither (treated as basic for display)
                phases = mfr.extract_phases
            if not self._extract_audio_supported:
                phases = tuple(p for p in phases if p != "Extract audio")

        if write_ssd and mfr.direct_ssd_write_phases:
            wphases = mfr.direct_ssd_write_phases
        else:
            wphases = mfr.write_phases
        self._rebuild_phase_steps(phases, wphases)

    # Back-compat shim — older code paths may still reference the
    # original toggle name.
    _on_capture_toggle = _on_extract_mode_toggle


    def _update_music_id_visibility(self):
        """Show the music-ID checkbox only when the active manufacturer
        advertises ``music_id`` and standalone WAVs will exist.

        Mirrors ``_update_transcribe_visibility`` (same audio-supported /
        basic-extract gating), and sits just below the transcribe frame so
        the post-extract audio options group together.
        """
        if self._current_mfr is None:
            return
        caps = self._current_mfr.capabilities
        show = (getattr(caps, "music_id", False)
                and self._extract_audio_supported
                and (not caps.capture or self.static_extract_var.get()))
        if not show:
            self._music_id_frame.pack_forget()
            self.music_id_var.set(False)
            self._update_extract_options_row_visibility()
            return
        # On the "Options:" row, right of the call-outs checkbox (call-outs
        # is packed first, so side=LEFT lands music after).  Trailing
        # (0, 12) keeps the whole checkbox row evenly spaced.
        self._music_id_frame.pack(side=tk.LEFT, padx=(0, 12))
        self._update_extract_options_row_visibility()

    def _update_duration_names_visibility(self):
        """Show the "Length-prefix names" checkbox only when the active
        manufacturer advertises ``audio_duration_names`` and an audio extract
        will actually run — same gating as the auto-name options."""
        if self._current_mfr is None:
            return
        caps = self._current_mfr.capabilities
        show = (getattr(caps, "audio_duration_names", False)
                and self._extract_audio_supported
                and (not caps.capture or self.static_extract_var.get()))
        if not show:
            self._duration_names_frame.pack_forget()
            self.duration_names_var.set(False)
            self._update_extract_options_row_visibility()
            return
        # Rightmost of the option cluster (transcribe + music pack first).
        self._duration_names_frame.pack(side=tk.LEFT, padx=(0, 12))
        self._update_extract_options_row_visibility()

    def _update_transcribe_visibility(self):
        """Show the auto-transcribe checkboxes only when a transcribable
        extract will actually run.

        Three conditions must all hold:
          * the manufacturer supports transcribe at all;
          * the selected game's audio is exportable (pre-DCS Williams
            titles have none — see _refresh_extract_audio_support);
          * standalone WAVs will be produced — only the basic/static
            extract emits those, so for capture-capable plugins the
            checkboxes sit under "Basic extract" and track it.

        Plugins without a Basic-extract toggle (CGC) always pass the
        third condition.
        """
        if self._current_mfr is None:
            return
        caps = self._current_mfr.capabilities
        show = (caps.transcribe and self._extract_audio_supported
                and (not caps.capture or self.static_extract_var.get()))
        if not show:
            self._transcribe_frame.pack_forget()
            # Hidden means it won't run — don't let a stale tick chain
            # transcribe onto an output that has no WAVs.
            self.transcribe_var.set(False)
            self._update_extract_options_row_visibility()
            return
        # First of the "Options:" row's cluster.  Trailing padx matches the
        # category checkboxes' (0, 12) so every checkbox sits the same
        # distance apart (a tester: the gaps were visibly unequal).
        self._transcribe_frame.pack(side=tk.LEFT, padx=(0, 12))
        self._update_extract_options_row_visibility()

    def _update_extract_options_row_visibility(self):
        """Pack the second "Options:" row only while at least one of the
        auto-name / length-prefix options is showing — most non-Stern
        plugins show none of the three, and an empty row would leave a
        stray "Options:" label under the action row."""
        row = self._extract_optnames_row
        any_shown = any(
            fr.winfo_manager()
            for fr in (self._transcribe_frame, self._music_id_frame,
                       self._duration_names_frame))
        if any_shown:
            if not row.winfo_manager():
                # Right under the action row, matching its horizontal pad so
                # "Options:" aligns with the "Extract:" label column above.
                row.pack(fill=tk.X, padx=10, pady=(0, 4),
                         after=self._extract_action_row)
        else:
            row.pack_forget()

    def _update_decode_dmd_visibility(self):
        """Show the "Decode DMD scenes" checkbox only when the active
        manufacturer advertises ``capabilities.decode_dmd`` (CGC).
        """
        if self._current_mfr is None:
            return
        # Game-aware: a multi-game plugin (Dutch Pinball) hides this for the
        # input games it doesn't apply to (AAIW), via decode_dmd_applies().
        applies = self._current_mfr.decode_dmd_applies(
            self.extract_input_var.get().strip())
        if not applies:
            self._decode_dmd_frame.pack_forget()
            self.decode_dmd_var.set(False)
            return
        # The label is game-specific (CGC decodes a ROM; Dutch Pinball shows
        # a dot-matrix shader for TBL and a ProRes->MP4 convert for AAIW).
        self._decode_dmd_check.configure(
            text=self._current_mfr.decode_dmd_label_for(
                self.extract_input_var.get().strip()))
        self._decode_dmd_frame.pack(fill=tk.X, padx=10, pady=(2, 0),
                                    before=self._extract_action_row)

    def _update_capture_help_text(self):
        basic = self.static_extract_var.get()
        capture = self.capture_mode_var.get()
        caps = self._current_mfr.capabilities if self._current_mfr else None
        if caps is not None and caps.capture and not caps.extract:
            # Capture-primary plugins (Data East): there is no static path.
            self._capture_help.configure(
                text=("Runs the game in attract mode under PinMAME and "
                      "records the DMD animations + audio as the firmware "
                      "renders them.  These games' animations are "
                      "compressed and only appear at runtime, so capture "
                      "is the extraction method.  Requires libpinmame."),
                foreground="#888888")
            return
        if basic and capture:
            self._capture_help.configure(text=(
                "Combined: runs the basic ROM asset extract (sprites, "
                "fonts, splash bitmaps, animation MP4s) AND the "
                "PinMAME runtime capture (per-scene cinematics with "
                "synced DCS audio) into the same output folder.  "
                "Capture requires libpinmame.dll installed.\n\n"
                "\"Simulate gameplay\" (recommended ON): drives "
                "coin + Start + Launch + the per-game scripted shot "
                "sequences (Big-O-Beam, Stroke of Luck, multiball, "
                "etc.) so the game actually enters play.  OFF = "
                "attract-mode only — leaves PinMAME idle, capturing "
                "just the attract reel."))
        elif capture and not basic:
            self._capture_help.configure(text=(
                "Capture only: PinMAME runtime capture without the "
                "static ROM asset extract.  Output is just the "
                "per-scene cinematics + DCS audio.  Faster + uses "
                "less disk than the combined run, useful when you "
                "already have the static assets or only want the "
                "live cinematics."))
        elif basic and not capture:
            self._capture_help.configure(text=(
                "Basic only: scans the ROM for raw asset bitmaps "
                "(sprites, font glyphs, splash screens, paired "
                "4-shade composites).  Tick \"Use PinMAME\" too to "
                "ALSO record live gameplay cinematics."))
        else:
            self._capture_help.configure(
                text="Tick at least one box above to run an extract.",
                foreground="#f44747")
            return
        # Restore normal help color (the "neither" branch sets red).
        self._capture_help.configure(foreground="#888888")

    # ------------------------------------------------------------------
    # Live DMD preview (Williams capture mode)
    # ------------------------------------------------------------------

    # WPC / DE DMDs are 128x32 — too tiny to read on a modern display.
    # This is the per-dot scale we render the live preview at.  7 =
    # ~896x224, large enough to clearly read the animation as it plays.
    _DMD_PREVIEW_SCALE = 7
    _DMD_AMBER = (255, 130, 0)   # match the orange we use elsewhere

    def on_dmd_frame(self, data, width, height, depth):
        """Receive a live DMD frame from the capture thread.

        Called from libpinmame's display callback on the C side's
        thread — MUST be quick and MUST NOT touch Tk widgets here.
        We just stash the latest frame; the Tk-after pump renders it.
        """
        # Tuple assignment is atomic in CPython, so concurrent reader
        # always sees a coherent slot.
        self._dmd_latest = (data, width, height, depth)

    def _refresh_mfr_scrollregion(self):
        """Re-apply the scrollable mfr-view geometry after a tall widget
        (the live DMD preview) is packed/unpacked, so it isn't clipped and
        the scrollbar appears only when content overflows."""
        try:
            c = self._mfr_view_canvas
            c.update_idletasks()
            bbox = c.bbox("all")
            if not bbox:
                return
            c.configure(scrollregion=bbox)
            inner_h = self._mfr_view.winfo_reqheight()
            ch = c.winfo_height()
            c.itemconfig(self._mfr_view_id, height=max(ch, inner_h))
            if (bbox[3] - bbox[1]) > ch + 2:
                self._mfr_view_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            else:
                self._mfr_view_scroll.pack_forget()
        except Exception:
            pass

    def reset_dmd_preview(self):
        """Forget the previous capture's last frame + start the pump.

        Called by app.py right before a new capture run.
        """
        self._dmd_latest = None
        if _HAVE_PIL:
            self._start_dmd_preview_pump()

    def _start_dmd_preview_pump(self):
        if self._dmd_preview_pump_id is not None:
            return
        # 33ms ≈ 30 fps redraw — generous; the underlying capture
        # callback is already throttled to ~20 fps so we'll mostly
        # be repainting the same image.
        self._dmd_preview_pump_id = self.root.after(
            33, self._pump_dmd_preview)

    def _stop_dmd_preview_pump(self):
        if self._dmd_preview_pump_id is not None:
            try:
                self.root.after_cancel(self._dmd_preview_pump_id)
            except Exception:
                pass
            self._dmd_preview_pump_id = None

    def _pump_dmd_preview(self):
        """Tk-after redraw loop: pulls the latest frame slot, renders,
        updates the preview label."""
        try:
            latest = self._dmd_latest
            if latest is not None and _HAVE_PIL:
                data, w, h, depth = latest
                img = _render_pinmame_frame(
                    data, w, h, depth,
                    self._DMD_PREVIEW_SCALE, self._DMD_AMBER)
                tkimg = ImageTk.PhotoImage(img)
                self._dmd_preview_tkimage = tkimg  # keep reference!
                self._dmd_preview_label.configure(image=tkimg)
                if not self._dmd_preview_visible:
                    self._dmd_preview_visible = True
        except Exception:
            # GUI must not crash on a malformed frame.
            pass
        # Re-arm — capture-cancel + new-capture loop both rely on
        # this self-rearm behaviour.
        self._dmd_preview_pump_id = self.root.after(
            33, self._pump_dmd_preview)

    # ------------------------------------------------------------------
    # Diagnostic switch matrix (Williams capture mode)
    # ------------------------------------------------------------------

    def on_capture_ready(self, manual_press_fn, active_script):
        """Called by the capture pipeline once PinMAME is initialized
        and the active script is known.

        Stashes the manual-press function and builds a labeled grid
        of clickable switch buttons for the active game.  Called from
        the capture thread — schedule the actual widget build on the
        Tk main thread.
        """
        self._manual_press_fn = manual_press_fn
        self.root.after(0, self._build_switch_matrix, active_script)

    def _build_switch_matrix(self, script):
        """Build the clickable switch-matrix grid from the active
        game's raw switch map."""
        # Tear down previous buttons.
        for w in self._switch_matrix_buttons:
            try:
                w.destroy()
            except Exception:
                pass
        self._switch_matrix_buttons = []

        raw = script.profile.get("raw", {}) if script else {}
        named_by_sw = {int(sw): name for name, sw in raw.items()}
        # Sort the named entries by switch number for stable layout.
        named_entries = sorted(raw.items(), key=lambda kv: int(kv[1]))
        # ALSO surface every standard WPC playfield position (sw#41
        # through sw#88) that isn't already in the raw map.  Sparse
        # prelim-sim games (NF, MB, CC, CV, etc.) only declare the
        # cabinet + trough + a couple of slings — but the real
        # playfield has ramps + saucers + targets at the conventional
        # positions.  Adding buttons for those lets the user fire
        # them manually for diagnostics, even though they're unlabeled.
        unknown_sws = []
        for sw_n in range(11, 89):
            if sw_n in named_by_sw:
                continue
            # Skip slot positions outside the conventional matrix
            # (column 9+, row 0).  WPC matrix is 8 cols × 8 rows so
            # any sw#NN where N%10 == 0 or N%10 > 8 is invalid.
            if sw_n % 10 == 0 or sw_n % 10 > 8:
                continue
            unknown_sws.append(sw_n)
        if not named_entries and not unknown_sws:
            self._switch_matrix_frame.configure(
                text="Switch matrix (no switches defined)")
            self._switch_matrix_frame.pack(
                fill=tk.X, padx=10, pady=(4, 0))
            return
        self._switch_matrix_frame.configure(
            text=f"Switch matrix — {script.title} "
                 f"({len(named_entries)} named + "
                 f"{len(unknown_sws)} unlabeled WPC positions, "
                 "click to press)")
        # 8 columns of compact buttons.
        cols = 8
        # Section 1: named switches.
        idx = 0
        for name, sw in named_entries:
            sw_n = int(sw)
            row, col = divmod(idx, cols)
            short = name.replace("sw", "", 1).strip()
            btn = ttk.Button(
                self._switch_matrix_inner,
                text=f"{sw_n:>2} {short[:8]}",
                width=12,
                command=lambda s=sw_n, n=short:
                    self._on_manual_switch_press(s, n))
            btn.grid(row=row, column=col, padx=1, pady=1, sticky="w")
            self._switch_matrix_buttons.append(btn)
            _Tooltip(btn, f"sw#{sw_n} — {short}",
                     lambda: self._current_theme)
            idx += 1

        # Separator row before the unlabeled positions.
        if unknown_sws:
            # Round up to next row boundary.
            while idx % cols != 0:
                idx += 1
            sep = ttk.Label(
                self._switch_matrix_inner,
                text="── Standard WPC playfield positions (not declared "
                     "in this game's sim — try them to see what's wired here)",
                font=(_SANS_FONT, 9, "italic"))
            sep.grid(row=idx // cols, column=0,
                     columnspan=cols, sticky="w",
                     padx=2, pady=(6, 2))
            self._switch_matrix_buttons.append(sep)
            idx = (idx // cols + 1) * cols
            for sw_n in unknown_sws:
                row, col = divmod(idx, cols)
                btn = ttk.Button(
                    self._switch_matrix_inner,
                    text=f"{sw_n:>2}  ?",
                    width=12,
                    command=lambda s=sw_n:
                        self._on_manual_switch_press(s, f"sw#{s}"))
                btn.grid(row=row, column=col, padx=1, pady=1, sticky="w")
                self._switch_matrix_buttons.append(btn)
                _Tooltip(btn,
                         f"sw#{sw_n} (col {sw_n // 10}, row {sw_n % 10}) "
                         f"— unlabeled standard WPC position",
                         lambda: self._current_theme)
                idx += 1
        # Make the matrix visible.
        self._switch_matrix_frame.pack(fill=tk.X, padx=10, pady=(4, 0))

    def _on_manual_switch_press(self, sw_no: int, label: str):
        """User clicked a switch button — fire the manual press."""
        fn = self._manual_press_fn
        if fn is None:
            return
        try:
            fn(sw_no, 120)
        except Exception as e:
            # Don't let a bad press crash the GUI.
            try:
                self.append_log(
                    f"manual press sw#{sw_no} ({label}) failed: {e}",
                    "warning")
            except Exception:
                pass

    def _tab_key(self, tab_id):
        """Stable identifier for a notebook tab (e.g. "Replace Audio"),
        independent of its short visible label (e.g. "Audio")."""
        return self._tab_keys.get(str(tab_id),
                                  self._notebook.tab(tab_id, "text").strip())

    def _current_tab_key(self):
        try:
            return self._tab_key(self._notebook.select())
        except tk.TclError:
            return None

    def _configure_tab(self, key, visible):
        for tab_id in self._notebook.tabs():
            if self._tab_key(tab_id) == key:
                if visible:
                    self._notebook.tab(tab_id, state="normal")
                else:
                    self._notebook.tab(tab_id, state="hidden")
                return

    def _tab_visible(self, key):
        """Whether the tab *key* is currently shown for this manufacturer —
        the read side of _configure_tab, so features that cross-link to
        another tab can hide themselves when it isn't there."""
        for tab_id in self._notebook.tabs():
            if self._tab_key(tab_id) == key:
                try:
                    return self._notebook.tab(tab_id, "state") != "hidden"
                except tk.TclError:
                    return False
        return False

    # ------------------------------------------------------------------
    # Browse helpers (file-filter pulled from current manufacturer)
    # ------------------------------------------------------------------

    def _input_filetypes(self):
        if self._current_mfr is None:
            return [("All files", "*.*")]
        spec = self._current_mfr.input_spec
        if not spec.extensions:
            return [("All files", "*.*")]
        joined = " ".join(f"*{ext}" for ext in spec.extensions)
        return [(spec.label, joined), ("All files", "*.*")]

    def _initialdir_for(self, *values):
        """Best ``initialdir`` for a Browse dialog.

        Points the OS file/folder picker at the path already in the field
        (or, for a file field, the folder containing it) so re-browsing
        lands where the user last was instead of a stale Windows MRU
        folder — a tester's "default to the folder that is listed".  Walks
        *values* in priority order and returns the first that resolves to
        an existing directory; ``None`` (the picker's own default) when
        none do.
        """
        for v in values:
            v = (v or "").strip()
            if not v:
                continue
            if os.path.isdir(v):
                return v
            parent = os.path.dirname(v)
            if parent and os.path.isdir(parent):
                return parent
        return None

    # Per-type "where was I last" for the replacement/mod-pack pickers: audio
    # picks live in one folder, video in another, mod packs a third — each
    # picker type reopens on its own last folder instead of the OS MRU
    # (feedback batch 14).  Persisted in settings.json by the app.
    def last_browse_dir(self, key):
        d = getattr(self, "_last_browse_dirs", None) or {}
        v = d.get(key)
        return v if v and os.path.isdir(v) else None

    def remember_browse_dir(self, key, path):
        if not path:
            return
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if not (folder and os.path.isdir(folder)):
            return
        if getattr(self, "_last_browse_dirs", None) is None:
            self._last_browse_dirs = {}
        self._last_browse_dirs[key] = folder

    def _path_combo(self, parent, var, field):
        """An editable path box with a recent-paths dropdown.

        Drop-in replacement for the plain ``ttk.Entry`` the path rows used:
        same textvariable wiring (typing + traces unchanged), plus a dropdown
        of this manufacturer's recent paths for *field*.  Values refresh on
        every open (``postcommand``) so a path recorded mid-session appears
        without any explicit widget update.

        A typed or picked path on a mapped drive letter the current session
        can't see (running elevated — mappings are per logon session) is
        rewritten to its UNC target once the box is left, so the action
        buttons get a path that actually resolves.  On focus-out rather
        than per keystroke: rewriting under the caret while the user is
        still typing "W:\\…" would fight them mid-word."""
        combo = ttk.Combobox(parent, textvariable=var)
        combo.configure(postcommand=lambda c=combo, f=field: c.configure(
            values=tuple(self._path_history.get(f, ()))))

        def _unmap(_e=None, v=var):
            from ..core.admin import resolve_mapped_drive
            cur = v.get()
            fixed = resolve_mapped_drive(cur)
            if fixed != cur:
                v.set(fixed)
        combo.bind("<FocusOut>", _unmap)
        combo.bind("<<ComboboxSelected>>", _unmap)
        return combo

    def set_path_history(self, history):
        """Swap in the current manufacturer's recent-paths dict
        (``{field_key: [paths]}``).  Called by the App on mfr switch and
        after it records a new path.  Entries on a mapped drive letter this
        session can't see (elevated process) are shown pre-translated to
        their UNC target so picking one just works."""
        from ..core.admin import resolve_mapped_drive
        self._path_history = {
            f: [resolve_mapped_drive(p) for p in paths]
            for f, paths in (history or {}).items()}

    def _browse_extract_input(self):
        path = filedialog.askopenfilename(
            title="Select input file", filetypes=self._input_filetypes(),
            initialdir=self._initialdir_for(self.extract_input_var.get()))
        if path:
            # Tk's file dialogs return forward slashes even on Windows;
            # normalize so path fields don't mix //server/share with
            # \\server\share styles (a tester 5.5).
            self.extract_input_var.set(os.path.normpath(path))

    def _browse_extract_deltas(self):
        paths = filedialog.askopenfilenames(
            title="Select delta update(s) to merge on top",
            filetypes=self._input_filetypes(),
            initialdir=self._initialdir_for(
                self.extract_input_var.get(), self.extract_output_var.get()))
        for p in paths:
            p = os.path.normpath(p) if p else p
            if p and p not in self.extract_delta_paths:
                self.extract_delta_paths.append(p)
        self._refresh_deltas_display()

    def _clear_extract_deltas(self):
        self.extract_delta_paths = []
        self._refresh_deltas_display()

    def _refresh_deltas_display(self):
        n = len(self.extract_delta_paths)
        if not n:
            self.extract_deltas_display_var.set("No updates added")
            return
        names = ", ".join(os.path.basename(p) for p in self.extract_delta_paths)
        self.extract_deltas_display_var.set(
            f"{n} update(s): {names}" if len(names) <= 70
            else f"{n} update(s) added")

    def _on_extract_input_changed(self):
        """Re-run game-specific Extract control visibility when the input
        path changes (e.g. switching between a TBL .zip and an AAIW .img
        within the Dutch Pinball plugin)."""
        # Default the Write tab's "Original" file to whatever was just picked
        # for Extract (Write rebuilds a copy of the file you extracted from).
        # Only when it's still empty, so a path set by hand on the Write tab is
        # never clobbered; a full extract re-syncs it outright (see
        # PinballDecryptorApp._start_extract).
        if (self._current_mfr is not None
                and getattr(self._current_mfr.capabilities, "write", False)
                and getattr(self, "write_upd_var", None) is not None
                and not self.write_upd_var.get().strip()):
            self.write_upd_var.set(self.extract_input_var.get().strip())
        if self._current_mfr is None or not hasattr(self, "_decode_dmd_frame"):
            return
        self._update_decode_dmd_visibility()
        self._update_chain_deltas_visibility()

    def _update_chain_deltas_visibility(self):
        """Show the optional 'updates to merge' picker only for plugins that
        advertise ``capabilities.chain_deltas`` (Dutch Pinball)."""
        if self._current_mfr is None:
            return
        # Game-aware: hidden for plugin inputs it doesn't apply to (AAIW).
        if not self._current_mfr.chain_deltas_applies(
                self.extract_input_var.get().strip()):
            self._extract_deltas_frame.pack_forget()
            self.extract_delta_paths = []
            self._refresh_deltas_display()
            return
        self._extract_deltas_desc.configure(
            text=getattr(self._current_mfr, "chain_deltas_help",
                         self._extract_deltas_desc.cget("text")))
        self._extract_deltas_frame.pack(fill=tk.X, padx=10, pady=(2, 0),
                                        before=self._extract_action_row)

    # ------------------------------------------------------------------
    # Direct-SSD source toggle + drive picker (caps.direct_ssd plugins)
    # ------------------------------------------------------------------

    def _on_input_source_change(self, mode):
        """Swap between the ISO file picker and the SSD drive picker.

        ``mode`` is "extract" or "write".  Called by the radio
        buttons.  Re-packs the visible row in the right order so the
        layout reads top-to-bottom even after multiple toggles.
        """
        if mode == "extract":
            source = self.extract_input_source_var.get()
            self._extract_input_row.pack_forget()
            self._extract_drive_row.pack_forget()
            self._extract_ssd_warn.pack_forget()
            self._extract_admin_frame.pack_forget()
            self._extract_macos_fda_frame.pack_forget()
            self._extract_badge_row.pack_forget()
            if source == "ssd":
                self._extract_drive_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._extract_output_row())
                self._extract_ssd_warn.pack(
                    anchor=tk.W, padx=10, pady=(4, 2),
                    before=self._extract_output_row())
                # Platform-specific Direct-SSD preconditions:
                #   * Windows: app must run as Administrator
                #     (wsl --mount + Set-Disk -IsOffline both gated).
                #   * macOS:   Full Disk Access on the app + debugfs
                #     + e2fsck (TCC blocks raw-disk reads otherwise).
                # Linux just uses sudo prompts mid-run, no preflight
                # banner required.
                import sys
                from ..core.admin import is_admin
                if sys.platform == "win32" and not is_admin():
                    self._extract_admin_frame.pack(
                        fill=tk.X, padx=10, pady=(4, 8),
                        before=self._extract_output_row())
                elif (sys.platform == "darwin"
                        and not self._fda_acknowledged):
                    self._extract_macos_fda_frame.pack(
                        fill=tk.X, padx=10, pady=(4, 8),
                        before=self._extract_output_row())
                # Kick off enumeration on a worker thread so the UI
                # never blocks on PowerShell/diskutil startup.  First
                # toggle of the radio always re-enumerates so a
                # freshly-plugged SSD shows up without a Refresh click.
                self._refresh_drives_async("extract")
            else:
                self._extract_input_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._extract_output_row())
                # Badge row only if it currently carries a warning (the
                # happy-path detection lives in the title bar — batch 20).
                self._sync_badge_row("extract")
            self._refresh_extract_phases()
            # Re-evaluate the Extract button gate after a source flip.
            self._refresh_ssd_run_buttons()
            # A source flip changes the tab's content height (the SSD mode adds
            # the drive row + warning/admin banners); re-size the notebook so
            # the bottom controls — the auto-name checkboxes — aren't left
            # clipped by the previously-pinned height.
            self._notebook.after_idle(self._resize_notebook_to_current_tab)
        else:  # write
            source = self.write_input_source_var.get()
            self._write_upd_row.pack_forget()
            self._write_drive_row.pack_forget()
            self._write_ssd_warn.pack_forget()
            self._write_admin_frame.pack_forget()
            self._write_admin_unc_hint.pack_forget()
            self._write_macos_fda_frame.pack_forget()
            self._write_badge_row.pack_forget()
            self._write_preview_frame.pack_forget()
            if source == "ssd":
                # SSD layout matches the standalone JJP decryptor:
                # Assets → Game SSD → Warning → Description →
                # Modified Files Preview.  Everything dynamic packs
                # `before=filename_lbl` so the order is:
                # [build-time assets row] [dynamic rows] [filename
                # lbl] [btn row].
                self._write_drive_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_filename_lbl)
                self._write_ssd_warn.pack(
                    anchor=tk.W, padx=10, pady=(4, 2),
                    before=self._write_filename_lbl)
                # Platform preconditions — see Extract branch for
                # the rationale.  Windows admin / macOS FDA.
                import sys
                from ..core.admin import is_admin
                if sys.platform == "win32" and not is_admin():
                    self._write_admin_frame.pack(
                        fill=tk.X, padx=10, pady=(4, 8),
                        before=self._write_filename_lbl)
                elif (sys.platform == "darwin"
                        and not self._fda_acknowledged):
                    self._write_macos_fda_frame.pack(
                        fill=tk.X, padx=10, pady=(4, 8),
                        before=self._write_filename_lbl)
                # When we ARE elevated (the state writing to a card requires),
                # warn that mapped network-drive letters won't be visible —
                # this is what silently emptied a tester's preview after a
                # relaunch-as-admin.
                if sys.platform == "win32" and is_admin():
                    self._write_admin_unc_hint.pack(
                        anchor=tk.W, padx=10, pady=(0, 4),
                        before=self._write_filename_lbl)
                # Modified Files Preview (shown in both ISO and SSD
                # modes; the ISO branch packs its own copy below).
                self._write_preview_frame.pack(
                    fill=tk.BOTH, expand=True, padx=10, pady=(4, 4),
                    before=self._write_filename_lbl)
                self._write_btn.configure(
                    text=getattr(self._current_mfr, "write_direct_button",
                                 "Apply Modifications"))
                self._refresh_drives_async("write")
                # SSD-write doesn't produce an output file — the SSD
                # IS the output.  Hide the Build Image row.
                if hasattr(self, "_write_output_row_ref"):
                    self._write_output_row_ref.pack_forget()
                # Kick a preview scan in the background so the user
                # sees the modified files without a separate click.
                self._scan_reasons["write_preview"] = "write destination changed"
                self._scan_write_preview()
            else:
                # ISO layout: source → original ISO → badge → assets
                # → output folder.  Dynamic rows go BEFORE the
                # assets row (because the original ISO sits above
                # the modified-assets folder in this flow).
                self._write_upd_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_assets_row())
                # Badge row only if it currently carries a warning (batch 20).
                self._sync_badge_row("write")
                self._write_btn.configure(
                    text=getattr(self._current_mfr, "write_build_button",
                                 "Build update"))
                if hasattr(self, "_write_output_row_ref"):
                    self._write_output_row_ref.pack(
                        fill=tk.X, padx=10, pady=4,
                        before=self._write_filename_lbl)
                # Modified Files Preview in ISO mode too — useful for
                # confirming hand-edited or Replace-Audio-staged files
                # registered as changes before building the update.
                self._write_preview_frame.pack(
                    fill=tk.BOTH, expand=True, padx=10, pady=(4, 4),
                    before=self._write_filename_lbl)
                self._scan_reasons["write_preview"] = "write destination changed"
                self._scan_write_preview()
            # The filename/output label is source-dependent (blank in
            # SD-card mode) — refresh it now that the source flipped.
            self._update_write_filename()
            # Either branch may have changed the phase indicator
            # shape — refresh both extract and write phases.
            self._refresh_extract_phases()
            # Also re-evaluate the Extract/Apply Modifications
            # button gates: SSD + non-admin disables them so the
            # user can't kick off a doomed run.
            self._refresh_ssd_run_buttons()
            # Re-size the notebook to the new content height (SSD mode adds the
            # drive row + warning/preview) so nothing is left clipped.
            self._notebook.after_idle(self._resize_notebook_to_current_tab)

    def _extract_output_row(self):
        """Output Folder row — anchor for ``before=`` repacks."""
        return getattr(self, "_extract_output_row_ref", None)

    def _write_assets_row(self):
        """Modified Assets row — anchor for write-tab SSD repacks."""
        return getattr(self, "_write_assets_row_ref", None)

    def _refresh_drives(self, mode):
        """Public Refresh-button handler — kicks off async enumeration."""
        self._refresh_drives_async(mode)

    def _refresh_drives_async(self, mode):
        """Enumerate physical drives on a worker thread.

        PowerShell's first-launch cost (~1-2s) blocks the Tk event
        loop if we run it inline — which is what made the "From SSD"
        radio feel like the app had hung.  We park the subprocess
        call on a daemon thread and hand the result back via
        ``root.after`` so all widget updates happen on the main
        thread.

        While the enumeration runs, the combobox shows a placeholder
        so the user has visual feedback that something is happening.
        """
        combo = (self._extract_drive_combo if mode == "extract"
                 else self._write_drive_combo)
        display_var = (self.extract_drive_display_var
                       if mode == "extract"
                       else self.write_drive_display_var)
        combo["values"] = ["Detecting drives…"]
        display_var.set("Detecting drives…")
        # Bias the auto-pick toward the active plugin's medium (a small SD
        # card for Stern, a large game SSD for JJP).  Read on the main
        # thread before the worker starts.
        prefer = getattr(self._current_mfr, "direct_target_kind", "ssd")

        def _worker():
            try:
                from ..core.drives import (list_physical_drives,
                                           pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives, prefer=prefer)
            except Exception:
                drives, pick = [], (None, None, None)
            # Hop back to the main thread before touching Tk widgets.
            self._tk_root().after(
                0, self._apply_drives, mode, drives, pick)

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _tk_root(self):
        """Return the Tk root — used by worker-thread .after() calls.

        ttk.Frame doesn't expose .after directly on this class, but
        any widget can call .after on its toplevel.
        """
        # ``self.master`` or the title label both work; pick a known-
        # existing widget that's created before any threaded work.
        return self._title_lbl.winfo_toplevel()

    def _theme_toplevel(self, win):
        """Paint a Toplevel's own background with the active theme.

        ttk children are styled by _apply_theme, but the Toplevel itself is a
        raw Tk widget: without this its system-default (light) background
        bleeds through every padx/pady margin and flashes on open/resize
        (feedback batch 16: "dark mode isn't 100% on popups").  Windows also
        needs the DWM call to darken the title bar."""
        try:
            win.configure(bg=THEMES[self._current_theme]["bg"])
        except tk.TclError:
            return
        dark_titlebar(win, self._current_theme == "dark")

    def _ask_text(self, title, prompt, initialvalue="", width=44):
        """Themed replacement for tkinter.simpledialog.askstring.

        simpledialog builds plain tk widgets with no styling hooks, so in dark
        mode it opens as a white box with black text (feedback batch 16).
        Same contract: returns the string, or None if cancelled."""
        root = self._tk_root()
        dlg = tk.Toplevel(root)
        dlg.title(title)
        dlg.transient(root)
        dlg.resizable(False, False)
        self._theme_toplevel(dlg)
        ttk.Label(dlg, text=prompt, justify=tk.LEFT).pack(
            anchor=tk.W, padx=12, pady=(12, 4))
        var = tk.StringVar(value=initialvalue or "")
        entry = ttk.Entry(dlg, textvariable=var, width=width)
        entry.pack(fill=tk.X, padx=12, pady=(0, 8))
        result = []

        def _ok(_e=None):
            result.append(var.get())
            dlg.destroy()

        def _cancel(_e=None):
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=12, pady=(0, 12))
        ttk.Button(btns, text="OK", command=_ok,
                   style="Go.TButton").pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=_cancel,
                   style="Danger.TButton").pack(side=tk.RIGHT, padx=(0, 6))
        dlg.bind("<Return>", _ok)
        dlg.bind("<Escape>", _cancel)
        entry.focus_set()
        entry.selection_range(0, tk.END)
        center_over(root, dlg)
        dlg.grab_set()
        root.wait_window(dlg)
        return result[0] if result else None

    def _apply_drives(self, mode, drives, pick):
        """Main-thread continuation of _refresh_drives_async.

        Populates the combobox, auto-selects the best-match drive,
        logs the discovery so the user can see exactly what was
        picked and why.  ``pick`` is the
        ``(drive, confidence, reason)`` triple from
        ``pick_best_game_ssd``.
        """
        combo = (self._extract_drive_combo if mode == "extract"
                 else self._write_drive_combo)
        display_var = (self.extract_drive_display_var
                       if mode == "extract"
                       else self.write_drive_display_var)

        def _set_cache(value):
            if mode == "extract":
                self._extract_drives_cache = value
            else:
                self._write_drives_cache = value

        if not drives:
            _set_cache([])
            combo["values"] = ["(no drives found — click Refresh)"]
            display_var.set(combo["values"][0])
            self._log_ssd_pick(
                "No physical drives detected.  Check that the SSD "
                "is connected and click Refresh.", level="error")
            return

        best, confidence, reason = pick
        # Hide drives far larger than any game SD card for SD-card media
        # (Stern) so the dropdown isn't cluttered with the user's backup
        # disks — but always keep the auto-picked drive so the selection
        # exists in the list.  Large-SSD media (JJP) keep every drive.
        from ..core.drives import visible_drives
        prefer = getattr(self._current_mfr, "direct_target_kind", "ssd")
        keep = (best,) if best is not None else ()
        shown = visible_drives(drives, prefer=prefer, keep=keep)
        hidden = len(drives) - len(shown)

        _set_cache(shown)
        combo["values"] = [d.display for d in shown]
        if best is not None:
            display_var.set(best.display)
            self._on_drive_selected(mode)
            tag = "success" if confidence == "high" else "info"
            self._log_ssd_pick(
                f"Selected SSD: {best.display}", level=tag)
            if reason:
                self._log_ssd_pick(f"  ({reason})", level="info")
            if confidence != "high":
                noun = getattr(self._current_mfr,
                               "direct_medium_noun", "SSD")
                self._log_ssd_pick(
                    f"  If this isn't the {noun}, pick it manually "
                    "from the dropdown.", level="info")
        else:
            # pick_best_game_ssd returned (None, None, None) — should
            # only happen on an empty list which we handled above.
            display_var.set(shown[0].display)
            self._on_drive_selected(mode)
        if hidden > 0:
            self._log_ssd_pick(
                f"  (hid {hidden} drive(s) too large to be a game SD card; "
                f"connect the card and click Refresh if you don't see it)",
                level="info")

    def _build_macos_fda_warning_frame(self, parent):
        """macOS Full Disk Access guidance banner for Direct-SSD mode.

        macOS Sonoma+ blocks raw block-device reads at the TCC layer
        — even from root subprocesses — unless every binary that
        touches ``/dev/rdiskN`` is on the Full Disk Access list.  Our
        Direct-SSD pipeline shells out to ``debugfs`` and ``e2fsck``
        from ``e2fsprogs``, so users need to grant access to BOTH
        helpers plus the app itself.  This banner spells out the
        exact steps so users don't have to learn TCC the hard way
        (operation-not-permitted, password-loop, etc.).

        Dismissible: the original "always shown" design fell out of
        sync with the actual TCC state — a user who had already
        granted everything in System Settings still saw the warning
        and assumed the app didn't know.  The "Hide this notice"
        link sets a persistent flag; the same flag is auto-set on
        the first successful Direct-SSD run, since that's empirical
        proof that FDA is working.
        """
        frame = tk.Frame(
            parent, bg="#5a1a1a", padx=12, pady=10,
            highlightbackground="#f44747", highlightthickness=2)
        header = tk.Frame(frame, bg="#5a1a1a")
        header.pack(fill=tk.X, anchor=tk.W)
        tk.Label(
            header,
            text="⚠  macOS FULL DISK ACCESS REQUIRED",
            bg="#5a1a1a", fg="#ffd1d1",
            font=(_SANS_FONT, 11, "bold"),
            anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True,
                              anchor=tk.W)
        # Dismiss link — styled as a clickable label rather than a
        # ttk button so it blends with the banner's red colour
        # scheme.  Cursor flips to a pointer on hover so it reads
        # as interactive.
        dismiss = tk.Label(
            header,
            text="Hide this notice ✕",
            bg="#5a1a1a", fg="#ffd1d1",
            font=(_SANS_FONT, 9, "underline"),
            cursor="hand2")
        dismiss.pack(side=tk.RIGHT, anchor=tk.E)
        dismiss.bind("<Button-1>",
                     lambda _e: self._dismiss_macos_fda_banner())
        tk.Label(
            frame,
            text=(
                "Direct-SSD on macOS reads raw disk blocks via "
                "Homebrew's e2fsprogs.  macOS Sonoma+ blocks this "
                "at the TCC layer until every binary involved is on "
                "the Full Disk Access list — even with admin "
                "password.\n\n"
                "To grant (one-time setup):\n"
                "   1.   System Settings → Privacy & Security → "
                "Full Disk Access.\n"
                "   2.   Click + and add each of these:\n"
                "          •   Pinball Asset Decryptor.app\n"
                "          •   debugfs  (usually "
                "/opt/homebrew/opt/e2fsprogs/sbin/debugfs on Apple "
                "Silicon, /usr/local/opt/e2fsprogs/sbin/debugfs on "
                "Intel)\n"
                "          •   e2fsck   (same folder as debugfs)\n"
                "   3.   Toggle each one ON.\n"
                "   4.   Fully quit this app (⌘Q) and reopen.\n\n"
                "Tip:  the binaries are in hidden folders.  In the "
                "Full Disk Access file picker, press ⌘⇧G and paste "
                "the full path.\n\n"
                "Already granted?  Click \"Hide this notice\" above "
                "— it'll stay hidden across restarts.  The notice "
                "auto-hides after your first successful SSD extract."),
            bg="#5a1a1a", fg="#ffffff",
            font=(_SANS_FONT, 9),
            justify=tk.LEFT, anchor=tk.W,
            wraplength=720).pack(fill=tk.X, anchor=tk.W, pady=(6, 0))
        return frame

    def _dismiss_macos_fda_banner(self):
        """Hide the FDA banner everywhere it might currently be packed
        and persist the dismissal via the app callback."""
        self._fda_acknowledged = True
        if self._on_fda_acknowledge is not None:
            try:
                self._on_fda_acknowledge(True)
            except Exception:
                pass
        for attr in ("_extract_macos_fda_frame",
                     "_write_macos_fda_frame"):
            frame = getattr(self, attr, None)
            if frame is not None:
                frame.pack_forget()

    def acknowledge_macos_fda(self):
        """Public API for the app to mark FDA as proven-working
        (called after a successful Direct-SSD run).  Idempotent."""
        if not self._fda_acknowledged:
            self._dismiss_macos_fda_banner()

    def _admin_body_text(self, mfr):
        """Body copy for the "Administrator required" panel.

        Kept to a single short paragraph (steps inline) so it fits the
        pinned notebook height — the older 2-paragraph + 4-numbered-step
        version overflowed and got clipped.  Wording is medium-aware: JJP
        reads from an SSD, Stern Spike from an SD card, so the noun and the
        source-toggle label come from the manufacturer.
        """
        noun = getattr(mfr, "direct_medium_noun", "SSD") if mfr else "SSD"
        ssd_label = (getattr(mfr, "extract_ssd_label", "From SSD")
                     if mfr else "From SSD")
        return (
            f"Reading directly from the {noun} needs Windows Administrator "
            "privileges — Windows gates raw disk access behind elevation. "
            "Close the app, right-click the \"Pinball Asset Decryptor\" "
            "shortcut, choose \"Run as administrator\", then re-select "
            f"\"{ssd_label}\" — your drive and output folder are remembered.")

    def _build_admin_warning_frame(self, parent):
        """Build the prominent "Administrator required" warning panel.

        Uses raw ``tk.Frame`` / ``tk.Label`` (not ttk) so we can set
        the background colour directly — ttk styling per-widget is
        themable but harder to override locally, and the goal here
        is the opposite of "blend in".  Returns the unpacked frame;
        ``_on_input_source_change`` decides when to pack it.  The body
        label is stashed on the frame so ``apply_manufacturer`` can swap
        in medium-aware wording.

        The how-to-fix body is collapsible: the heading row carries a
        disclosure chevron, and the collapsed/expanded choice is shared across
        every copy of the panel and persisted (see _toggle_admin_warning) so a
        returning user who's already read it isn't shown the wall of text every
        time.  The banner heading itself always stays visible.
        """
        frame = tk.Frame(
            parent, bg="#5a1a1a", padx=12, pady=10,
            highlightbackground="#f44747", highlightthickness=2)
        # Heading row: warning text on the left, a click-to-toggle chevron on
        # the right.  The whole row is clickable so the hit target is large.
        header = tk.Frame(frame, bg="#5a1a1a")
        header.pack(fill=tk.X)
        heading = tk.Label(
            header,
            text="⚠  ADMINISTRATOR PRIVILEGES REQUIRED",
            bg="#5a1a1a", fg="#ffd1d1",
            font=(_SANS_FONT, 11, "bold"),
            anchor=tk.W)
        heading.pack(side=tk.LEFT, anchor=tk.W)
        chevron = tk.Label(
            header, text="", bg="#5a1a1a", fg="#ffd1d1",
            font=(_SANS_FONT, 11, "bold"), cursor="hand2")
        chevron.pack(side=tk.RIGHT)
        body = tk.Label(
            frame,
            text=self._admin_body_text(None),
            bg="#5a1a1a", fg="#ffffff",
            font=(_SANS_FONT, 9),
            justify=tk.LEFT, anchor=tk.W,
            wraplength=720)
        # body is packed/unpacked by _apply_admin_warning_collapsed().
        frame.body_label = body
        frame.chevron_label = chevron
        for w in (header, heading, chevron):
            w.bind("<Button-1>", lambda _e: self._toggle_admin_warning())
        self._admin_warning_frames.append(frame)
        self._apply_admin_warning_collapsed(frame)
        return frame

    def _apply_admin_warning_collapsed(self, frame):
        """Reflect the shared collapsed state on one admin-warning panel:
        show/hide the body and point the chevron the right way (▼ = click to
        expand, ▲ = click to collapse)."""
        collapsed = self._admin_warning_collapsed
        frame.chevron_label.configure(text="▼" if collapsed else "▲")
        if collapsed:
            frame.body_label.pack_forget()
        else:
            frame.body_label.pack(fill=tk.X, anchor=tk.W, pady=(6, 0))

    def _toggle_admin_warning(self):
        """Flip the collapsed/expanded state for every admin-warning panel and
        persist the choice so it sticks across restarts."""
        self._admin_warning_collapsed = not self._admin_warning_collapsed
        for frame in self._admin_warning_frames:
            self._apply_admin_warning_collapsed(frame)
        if self._on_admin_warning_collapsed_change:
            self._on_admin_warning_collapsed_change(
                self._admin_warning_collapsed)

    def _refresh_ssd_run_buttons(self):
        """Disable Extract / Apply Modifications when SSD + not admin.

        Windows-only gate: the elevation requirement comes from
        ``wsl --mount`` + ``Set-Disk -IsOffline``, both of which are
        Windows-specific.  macOS / Linux handle elevation in-process
        via osascript / sudo prompts in
        :meth:`_debugfs_run_elevated`, so we should NOT disable the
        Extract button there — the user runs the app normally and
        types their password into the system dialog when prompted.

        Re-enabled the moment the user switches the radio back to ISO
        mode, or when ``is_admin()`` flips True (which only happens
        on a re-launched elevated process — same process can't gain
        admin mid-life).
        """
        import sys
        from ..core.admin import is_admin
        admin = is_admin()
        mfr = self._current_mfr
        needs_admin = (
            sys.platform == "win32"
            and mfr is not None
            and mfr.capabilities.direct_ssd
            and not admin)
        block_write = (
            needs_admin
            and self.write_input_source_var.get() == "ssd")
        # Don't fight whatever set_running() may have set — only
        # touch state if we're not in the middle of a run.
        if not self._is_running():
            # The Extract button state is owned by _refresh_extract_enabled —
            # it folds in this same admin check plus the input/output gate.
            self._refresh_extract_enabled()
            self._write_btn.configure(
                state=(tk.DISABLED if block_write else tk.NORMAL))

    def _is_running(self):
        """True when a pipeline is mid-flight (either tab)."""
        return getattr(self, "_running", False)

    def _set_extract_button_running(self, running, active=True):
        """Drive the single Extract/Cancel button.

        While an extract is in flight the Extract button doubles as a live
        Cancel (there's no separate Cancel widget any more); otherwise it's
        "Extract", enabled only when the inputs are ready (see
        _refresh_extract_enabled).  *active* says whether the running job is
        the Extract one: only the tab that STARTED the run gets the Cancel —
        a tester hit "Cancel" on the Write tab during an extract and killed
        the extract (batch 9), so the other tab's button now just greys out
        with its idle label.
        """
        if running and active:
            self._extract_btn.configure(
                text="Cancel", command=self._on_extract_cancel,
                state=tk.NORMAL, style="Danger.TButton")
            self._extract_btn_tip.text = (
                "Cancel the operation in progress — it stops as soon as it's "
                "safe to.")
        elif running:
            self._extract_btn.configure(
                text="Extract", command=self._on_extract,
                state=tk.DISABLED, style="Go.TButton")
            self._extract_btn_tip.text = (
                "Another operation is running — cancel it or let it finish "
                "first.")
        else:
            self._extract_btn.configure(
                text="Extract", command=self._on_extract,
                style="Go.TButton")
            self._refresh_extract_enabled()

    def _current_write_button_label(self):
        """The idle label for the single Build button — mode- and
        manufacturer-aware ("Build SD-card image" / "Apply Modifications" /
        "Build update").  Used to restore the button after it served as a
        live Cancel."""
        mfr = self._current_mfr
        if mfr is None:
            return "Build update"
        ssd = (getattr(self, "write_input_source_var", None) is not None
               and self.write_input_source_var.get() == "ssd")
        if ssd:
            return getattr(mfr, "write_direct_button", "Apply Modifications")
        return getattr(mfr, "write_build_button", "Build update")

    def _set_write_button_running(self, running, active=True):
        """Drive the single Build/Cancel button.

        Mirrors _set_extract_button_running: while a build/write runs the
        Build button doubles as a live Cancel (a tester 4.4 — there's no
        separate Cancel widget any more); otherwise it shows the mode's build
        label and re-arms the write action.  *active* is False when the
        running job belongs to the Extract tab — the Build button then keeps
        its idle label but greys out, instead of becoming a second "Cancel"
        that kills someone else's run (feedback batch 9).
        """
        if running and active:
            self._write_btn.configure(
                text="Cancel", command=self._on_write_cancel,
                state=tk.NORMAL, style="Danger.TButton")
        elif running:
            self._write_btn.configure(
                text=self._current_write_button_label(),
                command=self._on_write_clicked, state=tk.DISABLED,
                style="Go.TButton")
        else:
            self._write_btn.configure(
                text=self._current_write_button_label(),
                command=self._on_write_clicked, state=tk.NORMAL,
                style="Go.TButton")
        self._sync_flash_button_for_write_run(running, active)

    _FLASH_BTN_TEXT = "Build / flash SD card…"
    _FLASH_BTN_TIP = (
        "Build a fresh image and/or write one onto an SD card — tick "
        "both in the dialog to build and flash in one step. Flashing "
        "erases and replaces the whole card, and needs Administrator "
        "(approved when the write starts).")

    def _flash_btn_text(self):
        """Idle label for the consolidated flash button — manufacturer-
        overridable (JJP's "flash" is a format-and-copy USB-stick prep, so
        it says so instead of "flash SD card")."""
        return (getattr(self._current_mfr, "flash_button_text", None)
                or self._FLASH_BTN_TEXT)

    def _sync_flash_button_for_write_run(self, running, active):
        """For consolidated (flash_image) plugins the Build / flash button
        IS the write-side action button — the plain Build button is hidden
        there (David: two build buttons) — so mirror Build's Cancel/parked
        role onto it during write runs.  A real flash run owns the button
        through set_flash_running (which runs after this and must win), so
        while ``_flash_running`` is up this stays hands-off."""
        btn = getattr(self, "_flash_btn", None)
        mfr = self._current_mfr
        if (btn is None or mfr is None
                or not getattr(mfr.capabilities, "flash_image", False)
                or getattr(self, "_flash_running", False)):
            return
        try:
            if running and active:
                btn.configure(text="Cancel", command=self._on_write_cancel,
                              state=tk.NORMAL, style="Danger.TButton")
            else:
                btn.configure(text=self._flash_btn_text(),
                              command=self._open_flash_dialog,
                              state=(tk.DISABLED if running else tk.NORMAL),
                              style="Go.TButton")
        except tk.TclError:
            pass

    def set_flash_running(self, running):
        """While a flash run is in flight, the "Build / flash SD card…"
        button doubles as its live Cancel, same as the Build and Extract
        buttons (feedback batch 8).  The app flips this on when it starts a
        flash pipeline; ``set_running(False)`` restores the opener
        unconditionally, so an aborted run can't leave a stuck Cancel."""
        self._flash_running = running
        btn = getattr(self, "_flash_btn", None)
        if btn is None:
            return
        try:
            if running:
                btn.configure(text="Cancel", command=self._on_write_cancel,
                              state=tk.NORMAL, style="Danger.TButton")
                # A flash starts via set_running(mode="write"), which armed
                # the Build button as the run's Cancel — but the Flash button
                # owns that role now.  Park Build disabled on its idle label
                # so there's exactly one Cancel on screen (feedback batch 9).
                self._set_write_button_running(True, active=False)
            else:
                btn.configure(text=self._flash_btn_text(),
                              command=self._open_flash_dialog,
                              state=tk.NORMAL, style="Go.TButton")
        except tk.TclError:
            pass

    def _have_extract_input(self):
        """True when the Extract tab has a source selected — a file in ISO/image
        mode, or a drive in Direct-SSD mode."""
        mfr = self._current_mfr
        if (mfr is not None and mfr.capabilities.direct_ssd
                and self.extract_input_source_var.get() == "ssd"):
            return bool(self.extract_drive_display_var.get().strip())
        return bool(self.extract_input_var.get().strip())

    def _extract_block_reason(self):
        """Why the Extract button is disabled, or '' when it's ready to run.

        Precedence: admin elevation (Windows Direct-SSD) > no input source >
        no output folder.  Doubles as the button's tooltip text so the user
        sees a one-line 'do this first' hint instead of a dead button.
        """
        import sys
        from ..core.admin import is_admin
        mfr = self._current_mfr
        ssd_mode = (mfr is not None and mfr.capabilities.direct_ssd
                    and self.extract_input_source_var.get() == "ssd")
        # Medium / input nouns are manufacturer- + era-specific (Stern Spike 2 =
        # "SD card" / "Card image"; Whitestar = a "ROM zip"; JJP = "SSD"), so
        # the hints read them off the plugin instead of hardcoding SD-card lingo.
        medium = getattr(mfr, "direct_medium_noun", "SSD") if mfr else "SSD"
        if sys.platform == "win32" and ssd_mode and not is_admin():
            return (f"Administrator privileges are required to read the "
                    f"{medium} directly — see the warning above.")
        if not self._have_extract_input():
            if ssd_mode:
                return f"Select the {medium} to read from first."
            noun = getattr(mfr, "extract_input_label", None) if mfr else None
            article = "an" if noun and noun[:1].lower() in "aeiou" else "a"
            thing = f"{article} {noun}" if noun else "a file"
            return f"Pick {thing} to extract first."
        if not self.extract_output_var.get().strip():
            return "Choose an output folder first."
        return ""

    def _refresh_extract_enabled(self):
        """Gate the Extract button on having both an input source and an output
        folder.  No-op mid-run (the button is a live Cancel then); folds in the
        Windows Direct-SSD admin gate via _extract_block_reason."""
        if not hasattr(self, "_extract_btn") or self._is_running():
            return
        reason = self._extract_block_reason()
        self._extract_btn.configure(
            state=(tk.DISABLED if reason else tk.NORMAL))
        self._extract_btn_tip.text = reason

    def _log_ssd_pick(self, text, level="info"):
        """Write a Direct-SSD discovery line to the current mfr's log.

        Routes through the same append_log path the pipelines use, so
        the user sees the SSD-pick reasoning in the same console
        they'll watch for the actual decrypt/encrypt run.
        """
        try:
            self.append_log(text, level=level)
        except Exception:
            # Pre-mfr-selected start-up state — the log widget may not
            # be active yet.  Best-effort; the same info will appear
            # when the pipeline runs anyway (the pipeline logs the
            # device + partition picks too).
            pass

    def _on_drive_selected(self, mode):
        """Map the selected combobox label back to its device_path.

        The combobox stores the *display* string (model + size + path);
        the pipeline needs the bare device_path.  We look it up from
        the cached PhysicalDrive list — keying on display is fine
        because the display includes the device_path verbatim, so
        duplicates are impossible.
        """
        display_var = (self.extract_drive_display_var
                       if mode == "extract"
                       else self.write_drive_display_var)
        device_var = (self.extract_drive_var if mode == "extract"
                      else self.write_drive_var)
        cache = (self._extract_drives_cache if mode == "extract"
                 else self._write_drives_cache)
        label = display_var.get()
        match = next((d for d in cache if d.display == label), None)
        device_var.set(match.device_path if match else "")

    # ------------------------------------------------------------------
    # Direct-SSD Modified Files Preview (JJP-only)
    # ------------------------------------------------------------------

    def _scan_write_preview(self):
        """Populate the Modified Files Preview tree on a worker thread.

        Walks the user's assets folder and MD5-compares each file
        against the baseline ``.checksums.md5`` the Extract phase
        emitted; anything that doesn't match shows up as "Modified"
        in the tree.  Ported almost verbatim from the standalone
        JJP decryptor (which is where users with the file already
        know the format from).

        Silently no-ops when:
          * the assets folder isn't set or doesn't exist (nothing to
            scan yet);
          * no .checksums.md5 is present (user pointed at a folder
            that didn't come from this app's Decrypt phase).

        Cancellable via ``_write_preview_scan_id`` — a re-scan
        invalidates any in-flight work so two scans don't race to
        populate the tree.
        """
        import os
        import re as _re
        import threading

        # One live Cancel at a time: while a run (build / flash / revert /
        # extract) is in flight, its button is the Cancel — starting a scan
        # would put a second "Cancel scan" next to it (feedback batch 10).
        # Defer to when the run finishes (set_running(False) re-fires this).
        if self._is_running():
            self._rescan_preview_after_run = True
            return

        assets_path = (self.write_assets_var.get() or "").strip()

        # Bump the scan-id up front so any older in-flight scan stops posting
        # results AND the pending rows below share the id with the on-disk scan.
        self._write_preview_scan_id += 1
        scan_id = self._write_preview_scan_id

        # Enter the shared scanning state (same treatment as the Replace tabs
        # — feedback batch 8): blanks the tree, overlays the big animated
        # spinner, and flips Refresh into a live Cancel.  Batch 22: rows are
        # now held back until the walk finishes (see _finish_write_preview_scan)
        # so the big indicator stays up for the WHOLE scan, exactly like every
        # other tab — the old trickle-in hid it after the first hit and left a
        # small line in the toolbar as the only sign of life.
        self._write_preview_empty.configure(
            text="Scanning for modified files…")
        self._set_tab_scanning("write_preview", True)

        # Every early return below leaves no worker running — drop back out of
        # the scanning state, list the pending rows (there'll be no on-disk
        # ones) and show the right placeholder instead.
        if not assets_path or not os.path.isdir(assets_path):
            pending_n = self._add_pending_preview_rows(assets_path, scan_id)
            self._set_tab_scanning("write_preview", False)
            if not pending_n:
                self._write_preview_empty.configure(
                    text="Select your modified assets folder above to preview "
                         "changed files.")
                self._write_preview_empty.place(
                    relx=0.5, rely=0.5, anchor=tk.CENTER)
            return
        checksums_file = os.path.join(assets_path, ".checksums.md5")
        if not os.path.isfile(checksums_file):
            pending_n = self._add_pending_preview_rows(assets_path, scan_id)
            self._set_tab_scanning("write_preview", False)
            if not pending_n:
                self._write_preview_empty.configure(
                    text=("Pick a folder produced by Extract first "
                          "(no .checksums.md5 found)."))
                self._write_preview_empty.place(
                    relx=0.5, rely=0.5, anchor=tk.CENTER)
            return

        def _scan():
            def _post(fn, *args):
                """Hop to the UI thread, unless the window has gone.
                A scan outlives its window on close, and raising from
                the worker only shows as a stray traceback."""
                try:
                    self._tk_root().after(0, fn, *args)
                except (tk.TclError, RuntimeError):
                    pass

            # ``.checksums.md5`` ships in two flavours depending on
            # which plugin wrote it:
            #   * JJP / md5sum style   — "<md5>  <path>"  (md5 first)
            #   * BOF style            — "<path>\t<md5>"  (path first)
            # Detect per-line: if the line starts with 32 hex chars,
            # treat as md5sum; otherwise split on the last tab.
            saved = {}
            md5sum_re = _re.compile(r'^([a-f0-9]{32})\s+\*?(.+)$')
            try:
                with open(checksums_file, "r", encoding="utf-8",
                          errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        m = md5sum_re.match(line)
                        if m:
                            md5_val = m.group(1)
                            fp = m.group(2)
                        elif "\t" in line:
                            fp, md5_val = line.rsplit("\t", 1)
                            md5_val = md5_val.strip()
                            if not _re.fullmatch(r'[a-f0-9]{32}', md5_val):
                                continue
                        else:
                            continue
                        if fp.startswith("./"):
                            fp = fp[2:]
                        saved[fp.replace("\\", "/")] = md5_val
            except OSError:
                # Couldn't read the baseline after all — restore the button
                # (staged edits still list; there are just no on-disk hits).
                _post(self._finish_write_preview_scan, 0, scan_id, assets_path)
                return

            # BOF only: hide the imported-cache subtree from the
            # preview.  Those files are pipeline-managed derivatives
            # of the user's edits to ``_EDITABLE ASSETS/`` (the Write
            # step re-encodes WAV/WEBP/etc. → .sample/.ctex/etc.), and
            # they also accumulate stale state from prior cancelled or
            # partial Write runs — both produce noise the user can't
            # act on directly.  Practice-mode modders aren't affected:
            # script edits live in ``pck/scripts``, scenes in
            # ``pck/.godot/exported``, .tres in ``pck/assets`` — none
            # of those paths are under ``pck/.godot/imported``.  The
            # Write pipeline still MD5-scans the full tree (including
            # imported/) so anything that genuinely differs there
            # still ships into the binary.
            current_mfr = self._current_mfr
            hide_imported_cache = (
                current_mfr is not None and current_mfr.key == "bof")

            # Size+mtime MD5 cache: unchanged files skip the re-hash, so a
            # re-scan of a mostly-unchanged folder takes seconds, not the
            # minutes of the full hash walk (feedback batch 14).
            from ..core import hashcache
            hcache = hashcache.load(assets_path)

            changed = []
            for root_dir, dirs, files in os.walk(assets_path):
                # Skip the .orig snapshot mirror (core.staged_originals): its
                # files aren't in the baseline anyway, but pruning avoids
                # hashing a backup copy of every edited asset.  Batch 19 also
                # prunes the project's build output (a multi-GB image that
                # would list as "modified") and the .hydrate parking lot
                # (whose nested files don't start with "." themselves).
                dirs[:] = [d for d in dirs
                           if d != ORIG_DIR
                           and not (root_dir == assets_path
                                    and d in ("build", ".hydrate"))]
                for name in files:
                    # Superseded (re-scan or Cancel) → stop hashing NOW.  The
                    # old check only ran when a changed file turned up, so a
                    # cancelled clean scan kept grinding through the whole
                    # tree (minutes on a network share).
                    if self._write_preview_scan_id != scan_id:
                        return
                    if (name.startswith(".")
                            or name == "fl_decrypted.dat"
                            or name.endswith(".img")
                            or name in TRACKING_SIDECARS):
                        # Skip dotfiles, the decrypted-blob scratch file, raw
                        # images, and the auto-name tracking sidecars
                        # (callouts.csv / music_titles.csv) — none are card
                        # assets the user can act on here.
                        continue
                    full = os.path.join(root_dir, name)
                    rel = os.path.relpath(
                        full, assets_path).replace("\\", "/")
                    if rel not in saved:
                        continue
                    if (hide_imported_cache
                            and rel.startswith("pck/.godot/imported/")):
                        continue
                    digest = hashcache.md5_for(full, rel, hcache)
                    if digest is None or digest == saved[rel]:
                        continue
                    if self._write_preview_scan_id != scan_id:
                        hashcache.save(assets_path, hcache)
                        return  # superseded — drop this scan
                    ext = os.path.splitext(name)[1].lstrip(".") or "?"
                    changed.append((rel, ext))
                    # No row insert here — the whole batch lands at the end so
                    # the big scanning indicator isn't hidden mid-walk.  The
                    # running count goes into the indicator's own text instead,
                    # so a long walk still visibly progresses.
                    _post(self._write_preview_progress, len(changed), scan_id)

            hashcache.save(assets_path, hcache)
            if self._write_preview_scan_id == scan_id:
                _post(self._finish_write_preview_scan, changed, scan_id,
                      assets_path)

        # The scanning UI (spinner + Cancel button) has been active since the
        # top of this method — just launch the walk.
        threading.Thread(target=_scan, daemon=True).start()

    def _add_pending_preview_rows(self, assets_path, scan_id):
        """List in-memory Replace-Audio / Replace-Video assignments for
        *assets_path* as "Pending" preview rows (they're staged to disk only at
        build time, so the MD5 scan can't see them).  Returns the count added."""
        import os
        n = 0
        got = {}
        for key, getter, label in (
                ("audio", self.pending_audio_assignments, "Replace Audio"),
                ("video", self.pending_video_assignments, "Replace Video"),
                ("image", self.pending_image_assignments, "Replace Images")):
            try:
                pend = getter(assets_path)
            except Exception:
                pend = None
            got[key] = bool(pend)
            if not pend:
                continue
            assignments = pend[1]
            for rel in sorted(assignments):
                ext = os.path.splitext(rel)[1].lstrip(".") or "?"
                self._add_write_preview_row(
                    rel, ext, f"Pending ({label})", scan_id, tag="pending")
                n += 1
        # Sidecar-recorded assignments no tab has restored yet (mods just
        # transferred in, or the app reopened straight onto Write): the build
        # stages these via the app's sidecar fallback, so the preview must
        # show them too — only for categories with no live in-memory state
        # (when a tab HAS scanned this folder, its memory is authoritative
        # and the sidecar mirrors it).
        if assets_path and not all(got.values()):
            from ..core import staged_changes
            try:
                saved = staged_changes.load(assets_path)
            except Exception:
                saved = {}
            mfr = self._current_mfr
            for key, cap, label in (
                    ("audio", "replace_audio", "Replace Audio"),
                    ("video", "replace_video", "Replace Video"),
                    ("image", "replace_image", "Replace Images")):
                if got.get(key) or mfr is None or not getattr(
                        mfr.capabilities, cap, False):
                    continue
                for rel, repl in sorted((saved.get(key) or {}).items()):
                    if not (isinstance(repl, str) and os.path.isfile(repl)
                            and os.path.isfile(os.path.join(
                                assets_path, rel.replace("/", os.sep)))):
                        continue
                    ext = os.path.splitext(rel)[1].lstrip(".") or "?"
                    self._add_write_preview_row(
                        rel, ext, f"Pending ({label})", scan_id, tag="pending")
                    n += 1
        # Edited on-screen text persists straight to text/strings.tsv (no
        # in-memory assignment), so read the edits back from the manifest and
        # list each changed string as a pending "original → new" row.
        mfr = self._current_mfr
        if mfr is not None and getattr(
                mfr.capabilities, "replace_text", False):
            try:
                from ..core import text_manifest
                changed = text_manifest.changed(assets_path)
            except Exception:
                changed = {}
            for _path, pairs in changed.items():
                for original, repl in pairs:
                    self._add_write_preview_row(
                        f"{original}  →  {repl}", "text",
                        "Pending (Replace Text)", scan_id, tag="pending")
                    n += 1
            # Recoloured text lives in its own manifest (the colour is a scene
            # property, not a font one) but it is still a pending text edit and
            # belongs in the same list, or a colour-only build looks like
            # nothing to write.
            try:
                from ..plugins.stern import text_colors
                recolored = text_colors.load(assets_path)
            except Exception:
                recolored = {}
            for _path, per_text in recolored.items():
                for text, (src, dst) in per_text.items():
                    self._add_write_preview_row(
                        "%s  —  %s → %s" % (text, text_colors.to_hex(src),
                                            text_colors.to_hex(dst)),
                        "text", "Pending (text colour)", scan_id,
                        tag="pending")
                    n += 1
        return n

    def _add_write_preview_row(self, rel, ext, status, scan_id, tag="modified"):
        """Insert one row into the preview tree (main-thread only)."""
        if self._write_preview_scan_id != scan_id:
            return
        # Once we've added a real row, hide the placeholder.
        try:
            self._write_preview_empty.place_forget()
        except tk.TclError:
            pass
        self._write_preview_tree.insert(
            "", tk.END, text=rel, values=(ext, status),
            tags=(tag,))
        # Tag colour is set in _apply_theme so it tracks dark/light
        # mode; nothing per-row here.
        # A row means there's something to revert — light the button up now
        # (don't wait for the scan to finish).
        self._update_revert_btn_state()
        self._update_write_preview_count()

    def _update_write_preview_count(self):
        """Keep the "Total changes: N" readout in step with the preview tree
        (feedback batch 9).  Blank when the tree is empty — the placeholder
        text already covers that state."""
        lbl = getattr(self, "_write_preview_count_lbl", None)
        if lbl is None:
            return
        try:
            n = len(self._write_preview_tree.get_children())
            lbl.configure(text=f"Total changes: {n}" if n else "")
        except tk.TclError:
            pass

    def _persist_tree_columns(self, tree, tree_key, col_ids):
        """Restore *tree*'s saved column widths and keep them saved as the user
        drags them — so a layout the user tuned survives a restart (a tester:
        "persist column resizes").  *col_ids* lists the column ids including
        ``"#0"``.  Idempotent + tolerant of a tree that's since been destroyed.
        """
        saved = self._saved_column_widths.get(tree_key) or {}
        for col in col_ids:
            w = saved.get(col)
            if isinstance(w, int) and w > 0:
                try:
                    tree.column(col, width=w)
                except tk.TclError:
                    pass
        # ButtonRelease fires on any click; we only write when a width actually
        # changed (a separator drag), so row-selection clicks are free.
        tree.bind("<ButtonRelease-1>",
                  lambda _e: self._save_tree_columns(tree, tree_key, col_ids),
                  add="+")

    def _save_tree_columns(self, tree, tree_key, col_ids):
        """Snapshot *tree*'s current column widths; if they differ from what's
        stored, update + persist via the settings callback."""
        try:
            widths = {col: int(tree.column(col, "width")) for col in col_ids}
        except tk.TclError:
            return
        if self._saved_column_widths.get(tree_key) == widths:
            return
        self._saved_column_widths[tree_key] = widths
        if self._on_column_widths_change:
            try:
                self._on_column_widths_change(dict(self._saved_column_widths))
            except Exception:
                pass

    # Pixel ceiling for auto-sized tree columns — roughly 60 characters of
    # the default UI font.  Content wider than this stays ellipsized.
    _AUTOSIZE_MAX_PX = 480

    def _autosize_tree_columns(self, tree, tree_key, col_ids):
        """Fit each column in *col_ids* to its widest cell, capped at
        ``_AUTOSIZE_MAX_PX`` (a tester 4.2: long names sat ellipsized while
        fixed-width columns wasted the space).  Called after a list refresh.
        A column the user has dragged themselves (persisted by
        :meth:`_persist_tree_columns`) keeps the user's width; each column's
        configured minwidth still applies.  No-op on an empty tree."""
        # Include nested rows (the image tab's "Group by scene" mode) — a
        # flat tree yields the same top-level list as before.
        rows = []
        stack = list(tree.get_children())
        while stack:
            r = stack.pop()
            rows.append(r)
            stack.extend(tree.get_children(r))
        if not rows:
            return
        saved = self._saved_column_widths.get(tree_key) or {}
        try:
            import tkinter.font as tkfont
            name = ttk.Style().lookup("Treeview", "font") or "TkDefaultFont"
            try:
                fnt = tkfont.nametofont(name)
            except tk.TclError:
                fnt = tkfont.Font(font=name)
            for col in col_ids:
                if col in saved:
                    continue               # the user's tuned width wins
                # Header first (plus room for the ▲/▼ sort suffix), then the
                # cells; stop early once the cap is reached.
                wmax = fnt.measure(tree.heading(col, "text")) + 24
                for r in rows:
                    if col == "#0":
                        # A child row's text sits one indent level deeper.
                        pad = 48 if tree.parent(r) else 28
                        w = fnt.measure(tree.item(r, "text")) + pad
                    else:
                        w = fnt.measure(tree.set(r, col)) + 16
                    if w > wmax:
                        wmax = w
                        if wmax >= self._AUTOSIZE_MAX_PX:
                            break
                try:
                    minw = int(tree.column(col, "minwidth"))
                except tk.TclError:
                    minw = 20
                tree.column(col, width=max(minw,
                                           min(wmax, self._AUTOSIZE_MAX_PX)))
        except tk.TclError:
            pass                            # tree torn down mid-refresh

    def _register_responsive_wrap(self, label, margin=44, minimum=420):
        """Track *label* so :meth:`_resize_mfr_view` keeps its ``wraplength`` in
        step with the content width — a fixed wraplength left a dead band to the
        right of the per-tab intro text when the window was widened (a tester).
        Applies the current width immediately (best-effort)."""
        self._responsive_wrap_labels.append((label, margin, minimum))
        try:
            w = self._mfr_view_canvas.winfo_width()
            if w > 1:
                label.configure(wraplength=max(minimum, w - margin))
        except (tk.TclError, AttributeError):
            pass

    def _make_assets_scan_buttons(self, row, tab_key, scan_cmd):
        """Build the *Scan* button for a Replace tab's project-folder row and
        register it under *tab_key* so :meth:`_set_tab_scanning` can disable +
        relabel it while a scan runs.  Batch 19 removed the per-tab folder
        Browse (the folder IS the project folder, set once on the Extract
        tab); batch 20 removed its "Set on Extract tab" replacement too — the
        row is a plain read-only mirror now, and anyone who reaches a Replace
        tab already knows where the folder is set (a tester)."""
        scan = ttk.Button(row, text="Scan", command=scan_cmd)
        scan.pack(side=tk.LEFT, padx=(8, 0))
        self._scan_buttons[tab_key] = scan
        self._scan_cmds[tab_key] = scan_cmd   # restore after a Cancel

    def _project_mirror_label(self, parent):
        """The read-only project-folder mirror the Replace tabs show: a link
        tracking the shared project variable — visibly NOT an editable field
        (batch 20: a readonly Entry still looked like per-tab state you could
        change here).  A tooltip says where the value is actually set."""
        return self._folder_link_label(
            parent, self._project_mirror_var,
            "The project folder — shared by every tab. It is set on the "
            "Extract tab.", path_var=self.write_assets_var)

    def _folder_link_label(self, parent, var, tip, path_var=None):
        """A folder path shown as a link: clicking it opens the folder in the
        OS file browser, same as the two paths in Project properties.

        Batch 29 asked whether the links had been reverted — they had only
        ever been in Properties, so every Project Folder row is one now.  The
        path is still read-only: the click opens it, it never edits it.

        *path_var* is the folder to open when the label shows something other
        than a bare path (the Replace tabs' mirror carries a "set it on the
        Extract tab" note while no project is loaded)."""
        lbl = ttk.Label(parent, textvariable=var, anchor=tk.W)
        src = path_var if path_var is not None else var
        lbl.bind("<Button-1>", lambda _e, v=src: self._open_folder_link(v))
        _Tooltip(lbl, tip + " Click to open it.", lambda: self._current_theme)
        self._style_folder_link(lbl, src)
        src.trace_add("write",
                      lambda *_a, l=lbl, v=src: self._style_folder_link(l, v))
        return lbl

    def _style_folder_link(self, lbl, var):
        """Dress *lbl* as a link only while there's somewhere to go — with no
        project loaded the row carries a note, not a path, and an underlined
        blue note reads as a broken link."""
        live = bool((var.get() or "").strip())
        try:
            lbl.configure(style="Link.TLabel" if live else "TLabel",
                          cursor="hand2" if live else "")
        except tk.TclError:
            pass

    def _open_folder_link(self, var):
        """Click handler for a folder link: open the path in the file manager,
        or say plainly why there's nothing to open."""
        path = (var.get() or "").strip()
        if not path:
            messagebox.showinfo(
                "Open folder",
                "No project folder yet — set it on the Extract tab.")
            return
        if not os.path.exists(path):
            messagebox.showinfo(
                "Open folder",
                "This folder doesn't exist yet:\n%s" % path)
            return
        self._reveal_in_file_manager(path)

    _SCAN_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"     # braille frames for the scanning animation
    _SCAN_LABELS = {"audio": "Audio", "video": "Video", "image": "Images",
                    "text": "Text", "write_preview": "Write change"}

    def _set_tab_scanning(self, tab_key, active):
        """Toggle a Replace tab into / out of its scanning state.

        While a scan runs the list is blanked, a big animated indicator shows
        over it, and the Scan button turns into Cancel (a tester) — so a slow
        scan over a network share can't look idle and can be aborted.  Tolerant
        of tabs/layouts where a widget doesn't exist.

        Every scan's start and finish (with its duration) is also logged, so
        slow scans are traceable after the fact (feedback batch 14 — his
        Write scan crawled after a mod-pack transfer and nothing recorded
        when or how long)."""
        label = self._SCAN_LABELS.get(tab_key, tab_key)
        t0s = getattr(self, "_scan_t0", None)
        if t0s is None:
            t0s = self._scan_t0 = {}
        if active:
            if tab_key not in t0s:      # re-entrant starts: keep first t0
                t0s[tab_key] = time.monotonic()
                # Say WHY, when the caller set a reason.  feedback batch 22
                # saw a 40-second Write change scan start on its own right
                # after saving a project and read it as the save doing needless
                # work; the save triggers nothing, but a bare "scan started"
                # gave him no way to tell that.
                why = self._scan_reasons.pop(tab_key, None)
                self.append_log(
                    "%s scan started%s." % (label, " (%s)" % why if why else ""),
                    "info")
            self._begin_scan_ui(tab_key)
        else:
            t0 = t0s.pop(tab_key, None)
            if t0 is not None:
                self.append_log("%s scan finished in %.1f s." %
                                (label, time.monotonic() - t0), "info")
            self._end_scan_ui(tab_key)

    def _begin_scan_ui(self, tab_key):
        tree = getattr(self, "_%s_tree" % tab_key, None)
        empty = getattr(self, "_%s_empty" % tab_key, None)
        if tree is not None:
            try:                       # blank the list so a cancel can't leave
                tree.delete(*tree.get_children())   # it looking half-filled
            except tk.TclError:
                pass
            if tab_key == "write_preview":
                self._update_write_preview_count()
        if empty is not None:
            try:
                self._scan_empty_font.setdefault(
                    tab_key, str(empty.cget("font")))
                self._scan_msgs[tab_key] = empty.cget("text") or "Scanning…"
                empty.configure(font=(_SANS_FONT, 18, "bold"))
                empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            except tk.TclError:
                pass
        self._start_scan_spinner(tab_key)
        self._toggle_scan_button(tab_key, scanning=True)

    def _end_scan_ui(self, tab_key):
        self._stop_scan_spinner(tab_key)
        empty = getattr(self, "_%s_empty" % tab_key, None)
        if empty is not None:
            try:                       # restore the normal (small) label font
                empty.configure(font=self._scan_empty_font.get(tab_key, ""))
            except tk.TclError:
                pass
        self._toggle_scan_button(tab_key, scanning=False)

    def _toggle_scan_button(self, tab_key, scanning):
        scan = self._scan_buttons.get(tab_key)
        browse = self._browse_buttons.get(tab_key)
        try:
            if scan is not None:
                if scanning:
                    # "Cancel scan", not a bare "Cancel": the run buttons
                    # (Extract / Build / Flash) also read "Cancel" mid-run,
                    # and a tester hit both at once with no way to tell
                    # which cancelled what (batch 9; the ✕ glyph also read
                    # as inconsistent with every other button).
                    scan.configure(
                        text="Cancel scan", state=tk.NORMAL,
                        command=lambda k=tab_key: self._cancel_scan(k))
                else:
                    scan.configure(
                        text=self._scan_idle_labels.get(tab_key, "Scan"),
                        state=tk.NORMAL,
                        command=self._scan_cmds.get(tab_key))
            if browse is not None:
                browse.configure(state=tk.DISABLED if scanning else tk.NORMAL)
        except tk.TclError:
            pass

    def _start_scan_spinner(self, tab_key):
        """Animate the tab's empty-state label with a braille spinner so a
        long scan visibly moves."""
        self._stop_scan_spinner(tab_key)

        def _tick(i=0):
            empty = getattr(self, "_%s_empty" % tab_key, None)
            if empty is None:
                return
            try:
                frame = self._SCAN_SPINNER[i % len(self._SCAN_SPINNER)]
                text = "%s  %s" % (
                    frame, self._scan_msgs.get(tab_key, "Scanning…"))
                empty.configure(text=text)
                # Tabs with a toolbar scan-status label (write_preview) get
                # the same animated text there — rows landing in the tree
                # hide the big overlay, and without this the rest of a long
                # scan has no visible activity at all (feedback batch 9).
                status = getattr(self, "_%s_scan_status" % tab_key, None)
                if status is not None:
                    status.configure(text=text)
            except tk.TclError:
                return
            self._scan_spinner_after[tab_key] = self._tk_root().after(
                90, _tick, i + 1)

        _tick()

    def _stop_scan_spinner(self, tab_key):
        aid = self._scan_spinner_after.pop(tab_key, None)
        if aid is not None:
            try:
                self._tk_root().after_cancel(aid)
            except Exception:
                pass
        # Scan over (finished or cancelled) — blank the toolbar activity text.
        status = getattr(self, "_%s_scan_status" % tab_key, None)
        if status is not None:
            try:
                status.configure(text="")
            except tk.TclError:
                pass

    def _cancel_scan(self, tab_key):
        """Cancel-button handler: invalidate the running scan (its result is
        dropped by the scan-id guard when the worker returns) and reset the tab
        to idle with a blank list.

        The scan's start-stamp is cleared AND the cancel is logged: leaving
        the stamp made the next Scan click count as re-entrant — no "started"
        line — and its "finished" line then reported the time since the
        CANCELLED scan began (batch 25: a tester's 35 s Images scan logged
        as 2173.4 s, with his cancel and restart invisible in between)."""
        attr = "_%s_scan_id" % tab_key
        setattr(self, attr, getattr(self, attr, 0) + 1)
        t0 = (getattr(self, "_scan_t0", None) or {}).pop(tab_key, None)
        if t0 is not None:
            self.append_log(
                "%s scan cancelled after %.1f s."
                % (self._SCAN_LABELS.get(tab_key, tab_key),
                   time.monotonic() - t0), "info")
        self._stop_scan_spinner(tab_key)
        tree = getattr(self, "_%s_tree" % tab_key, None)
        if tree is not None:
            try:
                tree.delete(*tree.get_children())
            except tk.TclError:
                pass
            if tab_key == "write_preview":
                self._update_write_preview_count()
        empty = getattr(self, "_%s_empty" % tab_key, None)
        if empty is not None:
            try:
                empty.configure(
                    font=self._scan_empty_font.get(tab_key, ""),
                    text="Scan cancelled — click %s to try again."
                         % self._scan_idle_labels.get(tab_key, "Scan"))
                empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            except tk.TclError:
                pass
        self._toggle_scan_button(tab_key, scanning=False)

    def begin_revert_view(self):
        """Blank the Modified Files list the moment a revert starts — its
        rows are about to become stale one by one, and leaving them up read
        as "nothing happened" (feedback batch 10).  The end-of-revert
        rescan repopulates whatever genuinely remains."""
        if not hasattr(self, "_write_preview_tree"):
            return
        if "write_preview" in self._scan_spinner_after:
            self._cancel_scan("write_preview")
        else:
            self._write_preview_scan_id += 1    # drop queued scan results
            try:
                self._write_preview_tree.delete(
                    *self._write_preview_tree.get_children())
            except tk.TclError:
                pass
            self._update_write_preview_count()
        try:
            self._write_preview_empty.configure(text="Reverting…")
            self._write_preview_empty.place(relx=0.5, rely=0.5,
                                            anchor=tk.CENTER)
        except tk.TclError:
            pass

    def _write_preview_progress(self, n_found, scan_id):
        """Keep the running "N found" inside the big scanning indicator's text
        while the MD5 walk runs (main-thread only).  The spinner ticker reads
        ``_scan_msgs`` on its next frame, so this only has to update it."""
        if self._write_preview_scan_id != scan_id:
            return
        self._scan_msgs["write_preview"] = (
            "Scanning for modified files…   %d found" % n_found)

    def _finish_write_preview_scan(self, changed, scan_id, assets_path=None):
        """End-of-scan housekeeping (main-thread only).

        *changed* is the list of ``(rel, ext)`` files the walk found modified
        on disk (or a bare count from the baseline-unreadable path).  Batch 22:
        the rows are inserted HERE rather than trickling in during the walk, so
        the tab keeps the same big scanning indicator as every other tab for
        the whole scan."""
        if self._write_preview_scan_id != scan_id:
            return
        if isinstance(changed, int):        # baseline unreadable — nothing found
            n_changed, changed = changed, []
        else:
            n_changed = len(changed)
        # Staged Replace-Audio/Video/Image/Text edits live only in memory (or
        # the folder's sidecar) until build time, so the MD5 walk can't see
        # them — list them alongside the on-disk hits.
        if assets_path is not None:
            self._add_pending_preview_rows(assets_path, scan_id)
        for rel, ext in changed:
            self._add_write_preview_row(rel, ext, "Modified", scan_id)
        # Latest scan finished — leave the scanning state (spinner stops,
        # Cancel flips back to Refresh; the duration is logged there), and
        # log what it found so slow scans + change counts are traceable.
        self._set_tab_scanning("write_preview", False)
        total_rows = len(self._write_preview_tree.get_children())
        self.append_log("Write change scan: %d modified on disk, %d total "
                        "change(s) for the next build." %
                        (n_changed, total_rows), "info")
        self._write_scan_fingerprint = self._current_write_fingerprint()
        self._update_write_preview_count()
        # Base the empty state on the actual tree contents — pending
        # Replace-Audio/Video rows count too, so "No modified files" only
        # shows when truly nothing (on disk or staged) is going to change.
        if self._write_preview_tree.get_children():
            try:
                self._write_preview_empty.place_forget()
            except tk.TclError:
                pass
        else:
            self._write_preview_empty.configure(
                text="No modified files detected.")
            self._write_preview_empty.place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)
        # Authoritative end-of-scan state for the Revert button.
        self._update_revert_btn_state()

    def _rescan_write_preview_clicked(self):
        """The Modified Files "Refresh" button — a plain scan, tagged so its
        log line says the user asked for it."""
        self._scan_reasons["write_preview"] = "Refresh clicked"
        self._scan_write_preview()

    def _maybe_rescan_write_preview(self):
        """Re-scan only when the Write tab is the active view AND the
        current plugin shows the preview tree.

        The ``write_assets_var`` trace fires on every keystroke, on
        every settings-restore, and on programmatic ``set()``; we
        don't want to spin up a hashing thread for any of those when
        the user isn't even looking at the preview.
        """
        mfr = self._current_mfr
        if mfr is None:
            return
        # The preview now shows for every write-capable plugin in both
        # ISO and SSD modes.  Plugins that can't build an update (e.g.
        # Williams) have no preview tree.
        if not mfr.capabilities.write:
            return
        # Only scan if the Write tab is the currently-selected tab —
        # otherwise the user can't see the preview anyway.
        if self._current_tab_key() != "Write":
            return
        # Skip the re-hash when nothing that feeds the preview has changed
        # since the last completed scan (feedback batch 14: switching tabs
        # re-ground through a minutes-long MD5 walk every single time).  The
        # fingerprint covers staged assignments, text edits, per-tab on-disk
        # change sets, and every finished run; the Refresh button still
        # always scans (it calls _scan_write_preview directly).
        fp = self._current_write_fingerprint()
        if (getattr(self, "_write_scan_fingerprint", None) is not None
                and fp == self._write_scan_fingerprint):
            return
        self._scan_reasons.setdefault(
            "write_preview", "staged changes differ from the last scan")
        self._scan_write_preview()

    def _current_write_fingerprint(self):
        """Cheap equality summary of everything that can change the Write
        change list: the assets folder, staged in-memory/sidecar replacement
        assignments, on-screen text edits, the Replace tabs' changed-on-disk
        sets, and a counter bumped after every finished run (build / export /
        revert all stage or restore files on disk)."""
        assets_path = (self.write_assets_var.get() or "").strip()
        parts = [assets_path, getattr(self, "_write_disk_epoch", 0)]
        for getter in (self.pending_audio_assignments,
                       self.pending_video_assignments,
                       self.pending_image_assignments):
            try:
                pend = getter(assets_path)
                parts.append(tuple(sorted((pend[1] or {}).items()))
                             if pend else ())
            except Exception:
                parts.append(None)
        for attr in ("_audio_changed_on_disk", "_video_changed_on_disk",
                     "_image_changed_on_disk"):
            val = getattr(self, attr, None)
            parts.append(tuple(sorted(val)) if val else ())
        try:
            from ..core import text_manifest
            changed = text_manifest.changed(assets_path)
            parts.append(sorted((p, list(pairs))
                                for p, pairs in changed.items()))
        except Exception:
            parts.append(None)
        try:
            from ..plugins.stern import text_colors
            parts.append(sorted(
                (p, sorted(per.items()))
                for p, per in text_colors.load(assets_path).items()))
        except Exception:
            parts.append(None)
        return parts

    def _browse_extract_output(self):
        path = filedialog.askdirectory(
            title="Select project folder",
            initialdir=self._initialdir_for(
                self.extract_output_var.get(), self.extract_input_var.get()))
        if not path:
            return
        # Drilled-into-a-subfolder correction (ported from the old
        # per-tab assets Browse): a picked folder with no `.checksums.md5`
        # but an ancestor that has one is almost certainly a subfolder of
        # an existing extraction (e.g. `sound/` instead of its parent).
        # Offer the real project folder rather than silently accepting a
        # path that'll scan empty.
        if not os.path.isfile(os.path.join(path, ".checksums.md5")):
            parent_with_checksums = self._find_checksums_ancestor(path)
            if parent_with_checksums and messagebox.askyesno(
                    "Use parent folder?",
                    "The folder you picked doesn't contain a "
                    "`.checksums.md5` baseline, but its parent "
                    f"`{parent_with_checksums}` does — that's the "
                    "folder Extract produced.\n\n"
                    "Use the parent folder instead?"):
                path = parent_with_checksums
        path = os.path.normpath(path)
        self.extract_output_var.set(path)
        # Batch 19 auto-load: a picked folder that already IS a project
        # (has the hidden anchor) restores that whole project — the 1:1
        # folder↔project rule (a tester).  The app decides whether to
        # apply silently (same manufacturer) or ask first (it switches).
        if self._on_project_folder_picked:
            self._on_project_folder_picked(path)

    def _browse_transfer_src(self):
        path = filedialog.askdirectory(
            title="Select your OLD extract folder (the one with your mods)",
            initialdir=self._initialdir_for(
                self.transfer_src_var.get(), self.transfer_dst_var.get(),
                self.write_assets_var.get()))
        if path:
            self.transfer_src_var.set(os.path.normpath(path))

    def _browse_transfer_dst(self):
        path = filedialog.askdirectory(
            title="Select the NEW version's extract folder (freshly extracted)",
            initialdir=self._initialdir_for(
                self.transfer_dst_var.get(), self.write_assets_var.get(),
                self.transfer_src_var.get()))
        if path:
            self.transfer_dst_var.set(os.path.normpath(path))

    def _browse_transfer_oldstock(self):
        path = filedialog.askdirectory(
            title="Select a STOCK (unmodified) extract of the OLD version "
                  "— optional",
            initialdir=self._initialdir_for(
                self.transfer_oldstock_var.get(), self.transfer_src_var.get()))
        if path:
            self.transfer_oldstock_var.set(os.path.normpath(path))

    def _browse_transfer_newimg(self):
        path = filedialog.askopenfilename(
            title="Select the NEW version's card image (.raw/.img) to build "
                  "onto",
            filetypes=[("Card image", "*.raw *.img *.bin"),
                       ("All files", "*.*")],
            initialdir=self._initialdir_for(
                os.path.dirname(self.transfer_newimg_var.get() or ""),
                self.transfer_dst_var.get()))
        if path:
            self.transfer_newimg_var.set(os.path.normpath(path))

    def _prefill_transfer_dst(self):
        """Default the transfer destination to the Mod Folder (the usual flow:
        the user points the app at the NEW extract, then pulls mods into it).
        Only fills an empty field — never overwrites what the user picked."""
        if not (self.transfer_dst_var.get() or "").strip():
            cur = (self.write_assets_var.get() or "").strip()
            if cur:
                self.transfer_dst_var.set(cur)
        self._transfer_refresh_meta()

    def _transfer_refresh_meta(self):
        """Recompute the read-only version hints and the output-name preview
        from the current field values, and auto-fill the base card image (row
        4) from the new extract's recorded source.

        The card stores no game-version string, so every version hint is parsed
        from a source FILENAME (shown as a hint, not ground truth).  Auto-
        filling the base image from the NEW extract's ``.extract_source.json``
        is what keeps the build on the new version — the old-version image can
        never sneak in as the base."""
        from ..core import extract_source

        src = (self.transfer_src_var.get() or "").strip()
        dst = (self.transfer_dst_var.get() or "").strip()

        def _dir_ver(d):
            v = extract_source.version_hint_for_dir(d) if d else None
            return ("version ~ " + v) if v else ""
        self.transfer_src_ver_var.set(_dir_ver(src))
        self.transfer_dst_ver_var.set(_dir_ver(dst))

        # Auto-fill the base image from the new extract's recorded source,
        # unless the user has typed their own path.
        if dst and not (self.transfer_newimg_var.get() or "").strip():
            rec = extract_source.read_extract_source(dst)
            recorded = (rec or {}).get("input_path")
            if recorded and os.path.isfile(recorded):
                # Setting the var re-enters this method via its trace; the
                # guard above (field now non-empty) stops the recursion.
                self.transfer_newimg_var.set(os.path.normpath(recorded))
                return

        img = (self.transfer_newimg_var.get() or "").strip()
        img_ver = (extract_source.version_hint_from_name(os.path.basename(img))
                   if img else None)
        self.transfer_img_ver_var.set(("version ~ " + img_ver)
                                      if img_ver else "")
        if img:
            suffix = getattr(self._current_mfr, "write_output_suffix",
                             "-modified") or "-modified"
            stem, ext = os.path.splitext(os.path.basename(img))
            self.transfer_output_var.set(
                "After transfer, the Write tab builds: %s%s%s"
                % (stem, suffix, ext))
        else:
            self.transfer_output_var.set("")

    # (_browse_write_upd / _browse_write_assets removed in batch 19 — the
    # Write Original and every assets row are read-only mirrors of the
    # Extract tab now; the subfolder correction moved into
    # _browse_extract_output.)

    def _autoscan_active_assets_tab(self):
        """Scan the assets folder for whichever tab is currently visible."""
        text = self._current_tab_key()
        if text is None:
            return
        self._scan_assets_tab_by_name(text)

    def _scan_assets_tab_by_name(self, text):
        """(Re-)scan the tab named *text* against the current assets folder.
        Shared by the active-tab autoscan and the transfer flow's scan-every-tab
        resync so both dispatch off one mapping."""
        if text == "Replace Video":
            self._scan_video_slots_async()
        elif text == "Replace Audio":
            self._scan_audio_slots_async()
        elif text == "Replace Images":
            self._scan_image_slots_async()
        elif text == "Replace Text":
            self._scan_text_strings()
        elif text == "Write":
            self._maybe_rescan_write_preview()
        elif text == "Mod Pack":
            self._prefill_transfer_dst()

    def _rescan_all_assets_tabs(self):
        """Re-scan every tab present in the notebook, not just the visible one,
        so all Replace tabs share one view of the current assets folder.  Only
        tabs actually in the notebook are touched, so a plugin that omits a
        Replace tab is skipped automatically."""
        try:
            tabs = self._notebook.tabs()
        except Exception:
            return
        for tab_id in tabs:
            try:
                text = self._tab_key(tab_id)
            except Exception:
                continue
            self._scan_assets_tab_by_name(text)

    def _find_checksums_ancestor(self, path, max_levels=3):
        """Walk up from *path* looking for a directory that contains
        `.checksums.md5`.  Returns the matching directory or None.

        Limited to ``max_levels`` hops so we don't suggest an
        unrelated ancestor far up the tree.
        """
        current = path
        for _ in range(max_levels):
            parent = os.path.dirname(current)
            if not parent or parent == current:
                return None
            if os.path.isfile(os.path.join(parent, ".checksums.md5")):
                return parent
            current = parent
        return None

    def _refresh_write_assets_warning(self):
        """Show/hide the inline warning under the Modified Assets row.

        Visible when a path is set, exists, and lacks `.checksums.md5`
        at its root — the same precondition that makes the Write
        phase fail with "No .checksums.md5 found".
        """
        label = getattr(self, "_write_assets_warning", None)
        if label is None:
            return
        path = (self.write_assets_var.get() or "").strip()
        if (path and os.path.isdir(path)
                and not os.path.isfile(
                    os.path.join(path, ".checksums.md5"))):
            ancestor = self._find_checksums_ancestor(path)
            if ancestor:
                msg = ("⚠ No `.checksums.md5` here. Did you mean the "
                       f"parent folder `{ancestor}`?")
            else:
                msg = ("⚠ No `.checksums.md5` here. Pick the folder "
                       "produced by Extract (it should contain "
                       "`.checksums.md5` at the root).")
            label.configure(text=msg)
            if not label.winfo_ismapped():
                # Anchor on the assets-row frame (always packed) rather
                # than the editable hint (BOF-only) so the warning still
                # appears on non-BOF plugins where the hint is hidden.
                label.pack(anchor=tk.W, padx=26, pady=(0, 4),
                           after=self._write_assets_row_ref)
        else:
            label.configure(text="")
            if label.winfo_ismapped():
                label.pack_forget()

    # ------------------------------------------------------------------
    # Flash-image dialog (caps.flash_image plugins, e.g. Stern Spike 2)
    # ------------------------------------------------------------------

    def _has_pending_write_changes(self):
        """True if the Modified Files Preview currently lists any change.

        Single source of truth the Build / Flash "nothing modified" warnings
        share — reflects the last preview scan (staged Replace rows + on-disk
        edits).  Returns True (assume changes) when the tree doesn't exist or
        can't be read, so the warning only ever fires when we're *confident*
        nothing changed — never as a false alarm the user can't clear.
        """
        tree = getattr(self, "_write_preview_tree", None)
        if tree is None:
            return True
        # A preview scan still in flight hasn't listed on-disk edits yet —
        # assume changes so building mid-scan never trips a false "nothing
        # modified" alarm (the build stages/diffs everything itself; the scan
        # is only the preview).
        if "write_preview" in getattr(self, "_scan_t0", {}):
            return True
        try:
            return bool(tree.get_children())
        except tk.TclError:
            return True

    def _on_write_clicked(self):
        """Build-button click.  Warn (but allow) when the preview shows no
        changes — building an unmodified card just makes a copy of the
        original, which a tester flagged as easy to do by accident — and
        confirm an overwrite of an existing output file at the moment it
        matters instead of only a passive red label (feedback batch 14),
        then defer to the app's write callback."""
        if (not self._is_running()
                and not self._has_pending_write_changes()):
            if not messagebox.askyesno(
                "Nothing modified",
                "No modified files were detected, so this will build a copy "
                "of the original image with no changes.\n\nBuild anyway?",
                icon="warning"):
                return
        if not self._is_running():
            target = self._target_write_path()
            original = (self.write_upd_var.get() or "").strip()
            if (target and os.path.exists(target)
                    and not (original
                             and os.path.abspath(original) == target)):
                if not messagebox.askyesno(
                    "File exists",
                    "%s already exists in the output folder.\n\n"
                    "Overwrite it?" % os.path.basename(target),
                    icon="warning"):
                    return
        if self._on_write is not None:
            self._on_write()

    # ------------------------------------------------------------------
    # ⚙ settings menu (header gear)
    # ------------------------------------------------------------------

    def _open_settings_menu(self):
        """Post the settings dropdown under the header gear.  Dropped just
        under the button, right-aligned to it so it never runs off the
        window's right edge."""
        self._post_header_menu(self._build_settings_menu(), self._gear_btn)

    def _open_project_menu(self):
        """Post the Project dropdown under the blue folder icon (batch 19).
        Same themed popup mechanism as the gear — a native menubar can't be
        themed (stays light on the dark theme), so header icons + built-
        fresh Menus are the app's menu idiom."""
        self._post_header_menu(self._build_project_menu(), self._project_btn)

    def _post_header_menu(self, menu, btn):
        # placement.dropdown_position owns the arithmetic, and it is not as
        # simple as it looks: this used to read menu.winfo_reqwidth() off a
        # Menu that had never been laid out, which answers 1, so the menu was
        # posted at the button's right edge and opened rightwards instead of
        # tucking under it.  On macOS it is worse - a tk.Menu there is a native
        # NSMenu whose requested width is not a Tk value at all.
        try:
            self.root.update_idletasks()
            x, y = placement.dropdown_position(menu, btn)
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _header_menu_kw(self):
        """The shared style kwargs for header dropdown Menus — see the
        color comments in _build_settings_menu."""
        c = THEMES[self._current_theme]
        return dict(tearoff=0, bg=c["bg"], fg=c["fg"],
                    activebackground=c["accent"], activeforeground="#ffffff",
                    disabledforeground=c["gray"], selectcolor=c["fg"])

    def _build_project_menu(self):
        """Construct the Project ▾ dropdown (batch 19): New / Open / Save /
        Save As / Recent ▸ / Projects… / Properties….  Built fresh per click
        like the gear menu.  In their own menu, Save/Load ARE at the top —
        a tester's point 5 about ordering, solved by the move itself."""
        kw = self._header_menu_kw()
        menu = tk.Menu(self.root, **kw)
        running = self._is_running()
        have_project = bool((self.write_assets_var.get() or "").strip()
                            and self._current_mfr is not None)

        def _entry(label, cb, enabled=True):
            menu.add_command(
                label=label,
                command=(lambda c=cb: c() if c else None),
                state=(tk.NORMAL if cb and enabled and not running
                       else tk.DISABLED))

        _entry("New project…", self._on_new_project)
        _entry("Open project…", self._on_load_project)
        menu.add_separator()
        _entry("Save project", self._on_save_project, enabled=have_project)
        _entry("Save project as…  (fork)", self._on_save_project_as,
               enabled=have_project)
        menu.add_separator()
        # Recent projects — the last few registry entries, folder basename
        # as the label with the full path as a mercy tooltip-ish suffix.
        # Plain cascade label, NOT _cascade_label (David: the appended
        # arrow doubled up with the native one and read as a wrong font),
        # and the entry stays ENABLED even when empty (a disabled item gets
        # the Windows embossed rendering) — an empty list shows one
        # disabled "(nothing yet)" child instead.
        recent = (self._recent_projects_provider()
                  if self._recent_projects_provider else [])
        rec_menu = tk.Menu(menu, **kw)
        if recent:
            for ent in recent:
                folder = ent.get("folder", "")
                if not folder:
                    continue
                label = os.path.basename(folder.rstrip("\\/")) or folder
                rec_menu.add_command(
                    label="%s    (%s)" % (label, folder),
                    command=(lambda f=folder:
                             self._on_open_recent_project(f)
                             if self._on_open_recent_project else None),
                    state=(tk.DISABLED if running else tk.NORMAL))
        else:
            rec_menu.add_command(label="(nothing yet)", state=tk.DISABLED)
        menu.add_cascade(label="Recent projects", menu=rec_menu)
        _entry("Projects…", self._on_open_project_manager)
        menu.add_separator()
        _entry("Properties…", self._on_project_properties,
               enabled=have_project)
        _entry("Change history…", self._open_change_history,
               enabled=have_project)
        return menu

    def _open_change_history(self):
        """Project ▾ → Change history…: open the project folder's append-only
        change record (core.history_log) in the OS's text viewer.  Every
        replacement pick/re-pick/clear (with the previous source file), text
        edit, staged default, build and revert lands there with a date+time —
        so "changed on disk" months later still says what it was changed with
        (batch 24)."""
        from ..core import history_log
        assets_dir = (self.write_assets_var.get() or "").strip()
        if not assets_dir:
            return
        path = history_log.path_for(assets_dir)
        if not os.path.isfile(path):
            messagebox.showinfo(
                "Change history",
                "Nothing recorded for this folder yet.\n\nFrom now on, every "
                "replacement pick (with what it replaced), text edit, staged "
                "default, build and revert is appended with a timestamp "
                "to:\n\n%s" % path)
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as e:
            messagebox.showerror(
                "Change history", "Couldn't open %s:\n%s" % (path, e))

    def _build_settings_menu(self):
        """Construct the ⚙ dropdown.

        Built fresh on every click so the dynamic bits (theme direction,
        update-check busy state, disk badge, prerequisite summary) are always
        current — a Menu is cheap to construct and needs no invalidation
        plumbing that way."""
        c = THEMES[self._current_theme]
        # No explicit font — Tk's TkMenuFont is the platform's native menu
        # font/metrics; forcing our own renders visibly "off" next to real
        # context menus (a tester/David).
        # selectcolor draws the ✓ / radio indicators — Tk's default is
        # near-black, which vanishes on the dark theme's menu background
        # (David: "can't see the check marks"); the theme fg is visible on
        # both themes' menus.
        kw = dict(tearoff=0, bg=c["bg"], fg=c["fg"],
                  activebackground=c["accent"], activeforeground="#ffffff",
                  disabledforeground=c["gray"], selectcolor=c["fg"])
        menu = tk.Menu(self.root, **kw)

        # A found update leads the menu (matches the ● on the gear) so it's
        # still reachable after the banner is dismissed.
        if self._update_available:
            version, url, installer = self._update_available
            if installer and self._on_install_update:
                # One-click in-app update (see _build_update_banner).
                menu.add_command(
                    label="● %s v%s…" % (_update_action_verb(installer),
                                         version),
                    command=self._install_update_clicked)
            else:
                menu.add_command(
                    label=f"● Download update v{version}…",
                    command=lambda u=url: self.open_link(
                        u, what="the release page"))
            menu.add_separator()

        # Theme — a dynamic verb label (a tester: the bare ☀/☽ glyph wasn't
        # self-explanatory).  Re-theming re-styles the whole widget tree
        # synchronously on the UI thread, so it's locked out mid-run to stop
        # users hammering it while a pipeline floods the main loop.
        to_dark = self._current_theme == "light"
        menu.add_command(
            label=("Switch to dark theme" if to_dark
                   else "Switch to light theme"),
            command=self._toggle_theme,
            state=(tk.DISABLED if self._is_running() else tk.NORMAL))
        menu.add_separator()

        # Update check — reads "Checking…" while the GitHub fetch is in
        # flight so the click is visibly received and can't be queued twice.
        menu.add_command(
            label=("Checking for updates…" if self._update_check_busy
                   else "Check for updates"),
            command=self._handle_check_updates,
            state=(tk.DISABLED if self._update_check_busy else tk.NORMAL))

        # Disk space (Windows-only; see _build_ui).  Carries the leftover-
        # staging badge so the warning survives the move into the menu.
        if sys.platform == "win32":
            label = "Manage disk space…"
            if self._disk_badge_suffix:
                label += f"   {self._disk_badge_suffix}"
            menu.add_command(label=label, command=self._open_disk_dialog)

        # Logs — one cascade for the log settings (David), same shape as the
        # voice-quality submenu: the rolling on-disk history viewer (also on
        # the log pane's right-click menu) + the seed-the-pane toggle (off =
        # a clean per-session log; the file keeps collecting either way).
        logs_menu = tk.Menu(menu, **kw)
        logs_menu.add_command(label="View log history…",
                              command=self._open_log_history)
        logs_menu.add_checkbutton(
            label="Show previous sessions in the log",
            variable=self.show_log_history_var,
            command=self._on_toggle_log_history)
        menu.add_cascade(label=self._cascade_label("Logs"), menu=logs_menu)
        menu.add_separator()

        # (Save/Load project moved to the Project ▾ header menu — batch 19.
        # The gear is back to its charter: app-wide once-in-a-while
        # settings.)

        # Voice recognition quality — the faster-whisper model Auto-name
        # call-outs uses.  App-wide (persisted), shown even for plugins
        # without transcribe so the setting is always discoverable.
        vq_menu = tk.Menu(menu, **kw)
        for value, label in VOICE_QUALITY_CHOICES:
            vq_menu.add_radiobutton(
                label=label, value=value,
                variable=self.voice_quality_var,
                command=self._on_voice_quality_pick)
        # Escape hatch for a damaged model download (a tester): clears the
        # huggingface cache dirs so the next run re-downloads clean.  Locked
        # out mid-run — a transcribe in flight holds its model files open.
        vq_menu.add_separator()
        vq_menu.add_command(
            label="Clear downloaded voice models…",
            command=self._clear_voice_models,
            state=(tk.DISABLED if self._is_running() else tk.NORMAL))
        menu.add_cascade(
            label=self._cascade_label("Voice recognition quality"),
            menu=vq_menu)
        menu.add_separator()

        # Prerequisites — one cascade, like the voice-quality submenu above
        # (a tester: three loose prerequisite lines read as clutter).  The
        # cascade LABEL is the status summary, so the state is visible without
        # opening it; the submenu holds the Re-check / Install actions.  The
        # strip under the title tucks itself away once everything is green,
        # so this is where a returning user finds them.
        summary, any_missing = self._prereq_menu_summary()
        has_prereqs = bool(self._prereq_indicators)
        prereq_menu = tk.Menu(menu, **kw)
        prereq_menu.add_command(
            label="Re-check prerequisites",
            command=lambda: (self._on_recheck_prereqs()
                             if self._on_recheck_prereqs else None),
            state=(tk.NORMAL if has_prereqs and self._on_recheck_prereqs
                   else tk.DISABLED))
        # The auto-installer is Windows/Linux-only (frozen macOS bundles
        # everything and can't pip-install anyway) — same rule as the strip.
        if sys.platform != "darwin":
            prereq_menu.add_command(
                label="Install missing prerequisites…",
                command=lambda: (self._on_install_prereqs()
                                 if self._on_install_prereqs else None),
                state=(tk.NORMAL if any_missing and self._on_install_prereqs
                       else tk.DISABLED))
        menu.add_cascade(label=self._cascade_label(summary),
                         menu=prereq_menu)

        # The first-launch disclaimer, re-readable on demand (David) —
        # About-style reference material, so it sits last.
        menu.add_separator()
        menu.add_command(label="View disclaimer…",
                         command=self._show_disclaimer)
        return menu

    def _show_disclaimer(self):
        """Gear "View disclaimer…" — re-open the first-launch terms in
        review mode (one Close button; nothing to accept or decline)."""
        from .disclaimer import show_disclaimer_dialog
        show_disclaimer_dialog(self.root, theme_name=self._current_theme,
                               review=True)

    def _cascade_label(self, label):
        """Cascade-entry label, with a dark-theme arrow glyph appended.

        Windows Tk draws the native cascade ▶ in the SYSTEM menu-text
        color, ignoring the menu's -foreground, and offers no option to
        change it — so on the dark theme it's black-on-dark and invisible
        (David).  Dark mode therefore carries its own arrow inside the
        label text (drawn in the label's fg, so it follows active/normal
        colors too); light mode keeps the native arrow and adds nothing."""
        if self._current_theme == "dark":
            return label + "   ▸"
        return label

    def _prereq_menu_summary(self):
        """(label, any_missing) for the settings menu's prerequisite line."""
        entries = self._prereq_indicators
        if not entries:
            return "Prerequisites: none for this view", False
        oks = [e.get("ok") for e in entries.values()]
        missing = sum(1 for ok in oks if ok is False)
        if any(ok is None for ok in oks):
            return "Prerequisites: checking…", missing > 0
        if missing:
            return f"Prerequisites: {missing} missing ✗", True
        return f"Prerequisites: all {len(oks)} ready ✓", False

    def _on_voice_quality_pick(self):
        if self._on_voice_quality_change:
            self._on_voice_quality_change(self.voice_quality_var.get())

    def _clear_voice_models(self):
        """⚙ → Voice recognition quality → Clear downloaded voice models."""
        if not messagebox.askyesno(
                "Clear Downloaded Voice Models",
                "Delete all downloaded voice-recognition models?\n\n"
                "The next Auto-name call-outs run downloads its model "
                "again. This is the fix when a damaged download keeps "
                "failing with a \"model.bin\" error."):
            return
        from ..core.transcribe import clear_whisper_cache
        try:
            n, freed = clear_whisper_cache()
        except Exception as e:
            messagebox.showerror(
                "Clear Downloaded Voice Models",
                f"Could not clear the voice-model cache:\n{e}")
            return
        if n:
            mb = freed / 1e6
            size = ("%.1f GB" % (mb / 1000.0)) if mb >= 1000 else (
                "%.0f MB" % mb)
            messagebox.showinfo(
                "Clear Downloaded Voice Models",
                f"Removed {n} cached model folder(s), freeing {size}.\n\n"
                f"The model re-downloads on the next Auto-name "
                f"call-outs run.")
        else:
            messagebox.showinfo("Clear Downloaded Voice Models",
                                "No downloaded voice models found.")

    def _open_tab_help(self):
        """Open (or surface) the tips window for the visible notebook tab."""
        tab = self._current_tab_key() or "Extract"
        if self._help_window is None:
            from .help_dialog import TabHelpWindow
            self._help_window = TabHelpWindow(
                self.root, lambda: self._current_theme)
        self._help_window.show(tab)

    def _refresh_tab_help(self, tab_name):
        """Re-render the tips window (if open) for *tab_name* — called on
        notebook tab switches so the open window never shows stale text."""
        if self._help_window is not None:
            self._help_window.refresh(tab_name)

    def _open_flash_dialog(self):
        """Open the two-section Build / flash modal.

        Section 1 builds a fresh image (the Write tab's normal Build, path
        pre-filled from Output Folder + File Name); section 2 flashes an
        image onto a card; both = build-then-flash in one click (a tester:
        testing on the machine was always a two-step).  The dialog hands the
        choice to the app's ``on_build_flash`` / ``on_flash_image``
        callbacks, which run the pipelines through the normal status area.
        Refuses while a run is in flight (the status area is busy)."""
        if self._on_flash_image is None:
            return
        if self._is_running():
            messagebox.showinfo(
                "Busy",
                "Finish or cancel the current operation before flashing a "
                "card.")
            return
        # The build section needs everything the Build button needs; when
        # something's missing it's shown disabled with a "set these on the
        # Write tab" hint instead of failing after the dialog closes.
        target = self._target_write_path()
        missing = []
        if not self.write_upd_var.get().strip():
            missing.append("the original image")
        if not self.write_assets_var.get().strip():
            missing.append("the assets folder")
        if not target:
            missing.append("the build location")
        reason = ("Set %s on the Write tab first." % " and ".join(missing)
                  if missing else "")
        caps = getattr(self._current_mfr, "capabilities", None)
        can_build = (not missing
                     and bool(caps is not None
                              and getattr(caps, "write", False)))
        # Pre-fill the flash box with the image the Output Folder + File Name
        # boxes point at, when it's already been built — flashing what you
        # just built is the overwhelmingly common case (feedback batch 8).
        initial = target if (target and os.path.isfile(target)) else None
        mfr_key = getattr(self._current_mfr, "key", "")
        from .flash_dialog import FlashImageDialog
        FlashImageDialog(
            self._tk_root(),
            manufacturer=self._current_mfr,
            theme_name=self._current_theme,
            on_flash=self._on_flash_image,
            initial_image=initial,
            on_build_flash=self._on_build_flash,
            build_target=target,
            can_build=can_build,
            cannot_build_reason=reason,
            has_pending_changes=self._has_pending_write_changes(),
            initial_choices=self._saved_flash_choices.get(mfr_key),
            on_choices=lambda c, k=mfr_key: self._remember_flash_choices(k, c))

    def _remember_flash_choices(self, mfr_key, choices):
        """Persist the Build / flash dialog's ticked sections for *mfr_key*.

        Merged, not replaced: the dialog omits ``build`` when the box was
        disabled, and that has to leave the previous answer standing rather
        than record a False the user never chose."""
        if not mfr_key or not choices:
            return
        current = dict(self._saved_flash_choices.get(mfr_key) or {})
        current.update(choices)
        if current == self._saved_flash_choices.get(mfr_key):
            return
        self._saved_flash_choices[mfr_key] = current
        if self._on_flash_choices_change:
            try:
                self._on_flash_choices_change(dict(self._saved_flash_choices))
            except Exception:
                pass

    def _open_diagnose_dialog(self):
        """Open the read-only card-diagnostics modal (mfr.diagnose_card).

        Unlike flash, this never writes, so it only refuses while a run is
        in flight (the drive may be busy being flashed)."""
        if self._is_running():
            messagebox.showinfo(
                "Busy",
                "Finish or cancel the current operation before reading a "
                "card.")
            return
        if getattr(self._current_mfr, "diagnose_card", None) is None:
            return
        from .diagnose_dialog import DiagnoseCardDialog
        DiagnoseCardDialog(
            self._tk_root(),
            manufacturer=self._current_mfr,
            theme_name=self._current_theme)


    # ------------------------------------------------------------------
    # WSL disk-space management (Windows; all native-tool plugins)
    # ------------------------------------------------------------------

    def _open_disk_dialog(self):
        """Open the disk-management modal (WSL + Windows-temp staging cleanup,
        reclaim-to-Windows).  Independent of the picker/working view; the modal
        does its own background scan and gates destructive actions behind
        confirmations.  Re-checks the toolbar badge when it closes."""
        from .disk_dialog import DiskManagerDialog
        DiskManagerDialog(self._tk_root(), theme_name=self._current_theme,
                          on_close=self._start_disk_badge_check)

    def _start_disk_badge_check(self):
        """Kick off a passive, backgrounded scan and badge the disk button if
        leftover staging exists.  Host temp is always scanned (local, instant);
        WSL only when it's already running (so we never start it for a badge)."""
        if sys.platform != "win32":
            return

        def _worker():
            count, total = 0, 0
            try:
                from ..core import host_temp
                for e in host_temp.scan():
                    count += 1
                    total += e["size"]
            except Exception:
                pass
            try:
                from ..core import wsl_disk
                if wsl_disk.is_running():
                    for e in wsl_disk.scan_staging():
                        count += 1
                        total += e["size"]
            except Exception:
                pass
            try:
                self.root.after(0, lambda: self._apply_disk_badge(count, total))
            except (RuntimeError, tk.TclError):
                pass

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _apply_disk_badge(self, count, total):
        """Badge the gear button when staging cleanup is pending (main
        thread).  The suffix also lands on the ⚙ menu's Manage-disk-space
        entry so the amount is visible before opening the dialog."""
        if count > 0:
            from .disk_dialog import _fmt
            self._disk_badge_suffix = "⚠ %s" % _fmt(total)
        else:
            self._disk_badge_suffix = ""
        self._refresh_gear_badge()

    def _refresh_gear_badge(self):
        """Show/hide the gear's notification dots: red when an update is
        available, amber when staging cleanup is pending (the amounts and
        actions live in the ⚙ menu entries)."""
        try:
            self._set_icon_dot(
                self._gear_btn, "update",
                self._GEAR_UPDATE_DOT if self._update_available else None)
            self._set_icon_dot(
                self._gear_btn, "warn",
                self._GEAR_WARN_DOT if self._disk_badge_suffix else None)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # BOF update-version date field
    # ------------------------------------------------------------------

    def _on_write_version_auto_toggle(self):
        """Auto checkbox flipped: lock the entry to the computed date, or
        unlock it for a manual override (seeded with the auto date so the
        user edits from a sensible starting point)."""
        # Seed the value only when switching to a blank manual field; in
        # Auto mode the refresh always mirrors the computed date.
        seed = (not self.write_version_auto_var.get()
                and not (self.write_version_date_var.get() or "").strip())
        self._refresh_write_version_field(force_value=seed)

    def _refresh_write_version_field(self, force_value=False):
        """Recompute the concrete update-version date from the current
        assets folder and refresh the entry + hint.

        In Auto mode the entry mirrors what the pipeline will stamp and is
        read-only; with Auto off it's editable and only seeded (not
        overwritten) so the user's typing survives folder re-scans.
        """
        frame = getattr(self, "_write_version_frame", None)
        if frame is None:
            return
        from ..plugins.bof.pipeline import peek_next_update_version

        path = (self.write_assets_var.get() or "").strip()
        baseline, next_str = (None, None)
        if path and os.path.isdir(path):
            try:
                baseline, next_str = peek_next_update_version(path)
            except Exception:
                baseline, next_str = (None, None)
        self._write_version_baseline = baseline

        auto = self.write_version_auto_var.get()
        try:
            self._write_version_entry.configure(
                state="readonly" if auto else "normal")
        except tk.TclError:
            pass

        if auto or force_value:
            self.write_version_date_var.set(next_str or "")

        if next_str is None:
            hint = ("(select your extracted assets folder — the date is read "
                    "from it)")
        elif auto:
            hint = (f"auto: one day past installed code "
                    f"({baseline.strftime('%Y.%m.%d')})")
        else:
            hint = (f"installed code is {baseline.strftime('%Y.%m.%d')} — "
                    f"enter a newer date to install")
        try:
            self._write_version_hint.configure(text=hint)
        except tk.TclError:
            pass

    def write_version_override(self):
        """Return the explicit YYYY.MM.DD the pipeline should stamp, or None
        in Auto mode (pipeline computes it).  Called by app.py on Write."""
        if self.write_version_auto_var.get():
            return None
        return (self.write_version_date_var.get() or "").strip() or None

    def write_version_validation_error(self):
        """Return a user-facing error string if a manual version date is
        invalid, else None.  Auto mode never errors."""
        if self.write_version_auto_var.get():
            return None
        from ..plugins.bof.pipeline import parse_update_date
        raw = (self.write_version_date_var.get() or "").strip()
        if not raw:
            return ("Enter an update version date as YYYY.MM.DD, or re-check "
                    "Auto to let the app pick one.")
        d = parse_update_date(raw)
        if d is None:
            return (f"'{raw}' isn't a valid date. Use the format "
                    f"YYYY.MM.DD (e.g. 2026.01.15).")
        base = self._write_version_baseline
        if base is not None and d <= base:
            return (f"{raw} isn't newer than the installed code "
                    f"({base.strftime('%Y.%m.%d')}). The game only installs "
                    f"a newer date — pick something after it.")
        return None

    # (_browse_write_output removed in batch 19 — the Build Location
    # derives from the project folder; _change_build_location is the
    # explicit override picker.)

    # ------------------------------------------------------------------
    # Dynamic badges
    # ------------------------------------------------------------------

    def _update_extract_badge(self, *_):
        self._set_badge(self._extract_badge, self.extract_input_var.get(),
                        mode="extract")
        self._refresh_extract_audio_support()

    def _refresh_extract_audio_support(self):
        """Re-probe whether the selected extract input is a game whose
        audio we can export, then refresh the audio-dependent UI (the
        Auto-transcribe checkboxes and the "Extract audio" phase) when
        that answer changes."""
        path = (self.extract_input_var.get() or "").strip()
        if self._current_mfr is None:
            supported = False
        elif path and os.path.isfile(path):
            try:
                supported = bool(
                    self._current_mfr.audio_export_supported(path))
            except Exception:
                supported = False
        else:
            # No file picked yet — don't pre-hide the audio UI; it
            # only hides once an unsupported game is actually chosen.
            supported = True
        if supported == self._extract_audio_supported:
            return
        self._extract_audio_supported = supported
        self._refresh_extract_phases()
        self._update_transcribe_visibility()
        self._update_music_id_visibility()
        self._update_duration_names_visibility()

    def _update_write_badge(self, *_):
        self._set_badge(self._write_badge, self.write_upd_var.get(),
                        mode="write")

    def _set_badge(self, label, path, mode):
        path = (path or "").strip()
        # Reset suggestion state for this mode each call.
        self._set_suggested_mfr(mode, None)

        if not path or not os.path.isfile(path) or self._current_mfr is None:
            label.configure(text="")
            self._notify_detected_game(mode, None)
            self._sync_badge_row(mode)
            return

        # 1. Try the current manufacturer first — happy path.
        try:
            game = self._current_mfr.detect(path)
        except Exception:
            game = None
        if game:
            # Era-switching manufacturers (Stern: Spike 2 SD-card vs Whitestar
            # MAME zip): when the loaded file's era differs from the current
            # one, re-apply the capability-dependent layout for it.  The era
            # now matches, so apply_manufacturer's own badge refresh won't
            # recurse.  Only the Extract input drives the layout.
            era = getattr(game, "era", "")
            mfr = self._current_mfr
            if (mode == "extract" and era and hasattr(mfr, "set_era")
                    and getattr(mfr, "_era", "") != era):
                mfr.set_era(era)
                self.apply_manufacturer(mfr, reset_era=False)
                # The detected era brings its own prerequisites — re-run the
                # probes so they don't sit greyed out (apply_manufacturer only
                # reset the indicators to "[?]").
                if self._on_recheck_prereqs is not None:
                    self._on_recheck_prereqs()
                return
            # Happy path: the detected game now lives in the TITLE BAR (via
            # the App), not in a tab badge — "Detected: Led Zeppelin (Spike 2)
            # — Spike 2 card image" repeated the header pills and burned a row
            # (feedback batch 20).  The badge keeps only genuine warnings.
            try:
                caption = mfr.title_caption(path, game)
            except Exception:
                caption = game.display
            self._notify_detected_game(mode, caption)
            # Era-switching plugins carry an era-agnostic picker badge
            # (Stern's "SPIKE 2"), so it can't say that *this* file's era is
            # capture/extract-only.  Flag it here when the era-resolved
            # capabilities expose no Write/Replace surface (e.g. Stern
            # Whitestar ROMs).
            caps = mfr.capabilities
            if hasattr(mfr, "set_era") and not caps.write and not (
                    caps.replace_audio or caps.replace_video
                    or caps.replace_image or caps.replace_text):
                label.configure(
                    text="Extract only — this format has no Write/Replace "
                         "support.")
            else:
                label.configure(text="")
            self._sync_badge_row(mode)
            return
        self._notify_detected_game(mode, None)

        # 2. Walk every other registered manufacturer.  If exactly one
        #    matches, offer to switch.  More than one match is ambiguous;
        #    none means the file is unrecognised by any plugin.
        other_hits = []
        for m in self._manufacturers:
            if m.key == self._current_mfr.key:
                continue
            try:
                g = m.detect(path)
            except Exception:
                continue
            if g:
                other_hits.append((m, g))

        if len(other_hits) == 1:
            m, g = other_hits[0]
            self._set_suggested_mfr(mode, m)
            label.configure(
                text=f"Looks like {g.display} ({m.display}) — "
                     f"click to switch")
        elif len(other_hits) > 1:
            names = ", ".join(m.display for m, _ in other_hits)
            label.configure(
                text=f"Matches multiple manufacturers: {names}")
        else:
            label.configure(
                text=f"Not recognised as {self._current_mfr.display}")
        self._sync_badge_row(mode)

    def _notify_detected_game(self, mode, caption):
        """Forward the detected-game caption to the App (title bar).  Only the
        Extract input drives it — the Write tab's Original is a read-only
        mirror of the same file, so letting it fire too would just double-set
        (and, mid-mirror, flicker) the title."""
        if mode == "extract" and self._on_detected_game_change:
            self._on_detected_game_change(caption)

    def _sync_badge_row(self, mode):
        """Pack a detect-badge row only while it carries text.  The happy path
        keeps the badge empty now (the game moved to the title bar — batch
        20), and an empty row just burned a line of vertical space.  SSD
        source mode keeps its row hidden regardless, matching
        _on_input_source_change (which also owns the pack position)."""
        if mode == "extract":
            row, badge = self._extract_badge_row, self._extract_badge
            anchor = self._extract_output_row()
            ssd = (getattr(self, "extract_input_source_var", None) is not None
                   and self.extract_input_source_var.get() == "ssd")
        else:
            row, badge = self._write_badge_row, self._write_badge
            anchor = self._write_assets_row()
            ssd = (getattr(self, "write_input_source_var", None) is not None
                   and self.write_input_source_var.get() == "ssd")
        want = bool(badge.cget("text")) and not ssd
        try:
            if want and not row.winfo_manager() and anchor is not None:
                row.pack(fill=tk.X, padx=10, pady=(0, 2), before=anchor)
            elif not want and row.winfo_manager():
                row.pack_forget()
        except tk.TclError:
            pass

    def _set_suggested_mfr(self, mode, mfr):
        if mode == "extract":
            self._extract_suggested_mfr = mfr
        else:
            self._write_suggested_mfr = mfr

    def _update_badge_cursor(self, mode, hovering):
        badge = self._extract_badge if mode == "extract" else self._write_badge
        suggested = (self._extract_suggested_mfr if mode == "extract"
                     else self._write_suggested_mfr)
        badge.configure(cursor="hand2" if (hovering and suggested) else "")

    def _auto_switch(self, mode):
        """Click handler: swap to the suggested manufacturer, preserving
        the just-browsed path so the user doesn't have to re-pick it.

        The App's `_save_manufacturer_paths` won't persist this path
        under the *old* mfr (its `detect()` won't claim it), so we just
        switch and re-set the path afterwards — the new mfr's saved
        settings get loaded during the switch and would otherwise blank
        out the field.
        """
        suggested = (self._extract_suggested_mfr if mode == "extract"
                     else self._write_suggested_mfr)
        if suggested is None:
            return
        var = (self.extract_input_var if mode == "extract"
               else self.write_upd_var)
        path = var.get()
        if self._on_manufacturer_change:
            self._on_manufacturer_change(suggested)
        var.set(path)

    # ------------------------------------------------------------------
    # Prerequisite indicators
    # ------------------------------------------------------------------

    def reset_prereqs(self, prereqs):
        """Replace the indicator row for the new manufacturer.

        Each prereq starts in "checking" state ([?] name); the App's
        worker thread fills in real results via :meth:`set_prereq_result`.
        The strip itself stays hidden until a probe confirms something is
        actually missing — flashing a "checking…" row that vanishes a moment
        later just draws the eye for nothing.  The ⚙ menu always carries the
        live status either way.
        """
        for w in self._prereqs_inner.winfo_children():
            w.destroy()
        self._prereq_indicators = {}
        self._prereqs_frame.pack_forget()

        if not prereqs:
            return

        c = THEMES[self._current_theme]
        for p in prereqs:
            lbl = tk.Label(
                self._prereqs_inner,
                text=f"[?] {p.name}",
                font=(_SANS_FONT, 9),
                background=c["bg"], foreground=c["gray"],
                padx=4, pady=2,
            )
            lbl.pack(side=tk.LEFT, padx=2)
            tooltip = _Tooltip(
                lbl,
                f"{p.name}\n\nChecking...\n\nWhy: {p.reason}",
                lambda: self._current_theme,
            )
            self._prereq_indicators[p.name] = {
                "label": lbl, "tooltip": tooltip, "prereq": p,
                "ok": None,   # None = still checking; drives strip auto-hide
            }

    def set_prereq_result(self, name, ok, message, install_hint=None):
        """Update one indicator with the probe's result.

        *install_hint* is the RESULT's hint — for WSL probes the check may
        swap the static hint for a state-specific one (which step of the
        WSL2 install is actually missing, PAD-17).  None falls back to the
        prerequisite's static hint.
        """
        entry = self._prereq_indicators.get(name)
        if not entry:
            return
        c = THEMES[self._current_theme]
        icon = "✓" if ok else "✗"
        color = c["success"] if ok else c["error"]
        entry["label"].configure(text=f"[{icon}] {name}", foreground=color)
        entry["ok"] = bool(ok)
        p = entry["prereq"]
        status = "OK" if ok else "MISSING"
        tip = (f"{p.name}\n\n"
               f"Status: {status}\n"
               f"{message}\n\n"
               f"Why: {p.reason}")
        hint = p.install_hint if install_hint is None else install_hint
        if not ok and hint:
            tip += f"\n\nFix: {hint}"
        entry["tooltip"].text = tip
        self._refresh_prereqs_visibility()

    def _refresh_prereqs_visibility(self):
        """Show the Prerequisites strip only once a probe has CONFIRMED a
        missing prerequisite.  While checks are still running (or when all
        came back green) it stays hidden — no flash-then-vanish on tab entry;
        the ⚙ menu carries the status + actions either way."""
        entries = self._prereq_indicators
        if not entries:
            return   # reset_prereqs already decided the empty case
        any_missing = any(e.get("ok") is False for e in entries.values())
        if not any_missing:
            self._prereqs_frame.pack_forget()
        elif not self._prereqs_frame.winfo_manager():
            self._prereqs_frame.pack(fill=tk.X, padx=10, pady=(6, 0),
                                     before=self._notebook)

    def _maybe_default_write_output(self):
        """Fill an EMPTY Write Output Folder with the original image's folder
        when an original is picked (Browse, post-extract default, or a typed
        path).  A non-empty box — including one restored from settings — is
        the user's choice and is never overwritten."""
        if self.write_output_var.get().strip():
            return
        upd = self.write_upd_var.get().strip()
        if upd and os.path.isfile(upd):
            parent = os.path.dirname(os.path.normpath(upd))
            if parent and os.path.isdir(parent):
                self.write_output_var.set(parent)

    # ------------------------------------------------------------------
    # Batch 19 — project-folder field collapse (see the traces in __init__)
    # ------------------------------------------------------------------

    def _mirror_stock_image(self):
        """Write-tab Original follows the Extract tab's Input — they were
        always the same file in practice (Write rebuilds a copy of what you
        extracted from), and two boxes meant two copies to keep in sync."""
        val = self.extract_input_var.get()
        if self.write_upd_var.get() != val:
            self.write_upd_var.set(val)

    def _mirror_project_folder(self):
        """The shared assets folder follows the Extract tab's Project
        Folder — the Replace/Write/Mod-pack rows are read-only views of it."""
        val = self.extract_output_var.get()
        if self.write_assets_var.get() != val:
            self.write_assets_var.set(val)

    def _derive_build_output(self):
        """Point the Build Location at ``<project>/build`` (or the anchor's
        build_dir override) whenever the project folder changes.

        Same back-off contract as the File Name auto-fill: an empty box or
        one still holding the last derived value re-derives; anything else
        is the user's (or a legacy setting's) choice and is left alone —
        that's what keeps a pre-batch-19 custom build location building to
        yesterday's folder."""
        folder = (self.write_assets_var.get() or "").strip()
        if not folder:
            return
        from ..core import project_file
        try:
            derived = os.path.normpath(project_file.project_build_dir(folder))
        except Exception:
            derived = os.path.normpath(os.path.join(folder, "build"))
        current = self.write_output_var.get().strip()
        if current == derived:
            # e.g. restored from settings — adopt it as "derived" so the
            # next project-folder change re-derives instead of sticking.
            self._write_output_auto = derived
            return
        # The pre-batch-19 default ("parent of the original image",
        # _maybe_default_write_output) is an auto value too — the project
        # derivation supersedes it, whichever order the fields were filled.
        legacy_auto = ""
        upd = (self.write_upd_var.get() or "").strip()
        if upd:
            legacy_auto = os.path.normpath(
                os.path.dirname(os.path.normpath(upd)))
        if (not current or current == self._write_output_auto
                or (legacy_auto and current == legacy_auto)):
            self._write_output_auto = derived
            self.write_output_var.set(derived)

    def _change_build_location(self):
        """Build Image "Change…": one Save-As picker for the merged
        folder + file-name row (batch 21).  The folder part is remembered as
        this project's build_dir override (plain stored path — no links) so
        the derivation honours it from now on — a NAS-hosted project can
        build to a local drive this way."""
        mfr = getattr(self, "_current_mfr", None)
        ext = ""
        if mfr is not None:
            try:
                ext = mfr.write_output_ext() or ""
            except Exception:
                ext = ""
        initial = ((self.write_filename_var.get() or "").strip()
                   or self._default_write_filename())
        path = filedialog.asksaveasfilename(
            title="Build image as",
            initialdir=self._initialdir_for(self.write_output_var.get(),
                                            self.write_assets_var.get()),
            initialfile=initial,
            defaultextension=(ext or ""),
            filetypes=(([("Card image", "*" + ext)] if ext else [])
                       + [("All files", "*.*")]),
            confirmoverwrite=False)   # Build itself asks before overwriting
        if not path:
            return
        path = os.path.normpath(path)
        folder_part, name_part = os.path.split(path)
        if mfr is not None:
            name_part = mfr.force_write_ext(name_part)
        self.write_output_var.set(folder_part)
        self.write_filename_var.set(name_part)
        self._write_output_auto = ""       # custom — derivation backs off
        folder = (self.write_assets_var.get() or "").strip()
        from ..core import project_file
        if folder and project_file.has_anchor(folder):
            default = os.path.normpath(os.path.join(folder, "build"))
            override = "" if folder_part == default else folder_part
            if project_file.update_anchor(folder, build_dir=override):
                self.append_log(
                    "Project build location %s" % (
                        "reset to the default build\\ folder" if not override
                        else "set to %s" % folder_part), "info")
        self._update_write_filename_hint()

    def _refresh_build_path_display(self, *_a):
        """Keep the Build Image row's text = the exact file Write will
        produce (folder + name with the plugin's forced extension)."""
        var = getattr(self, "_write_build_path_var", None)
        if var is None:
            return
        target = ""
        try:
            target = self._target_write_path()
        except Exception:
            target = ""
        if not target:
            out = (self.write_output_var.get() or "").strip()
            name = (self.write_filename_var.get() or "").strip()
            target = os.path.join(out, name) if out and name else out
        var.set(target)

    def _project_path_display(self, parent, var):
        """The read-only path row the Replace/Write/Mod-pack tabs show for
        project-derived fields: a link mirroring *var* — visibly not an
        editable field, matching the Replace tabs' project mirror.  The
        old "Set on Extract tab" jump button is gone (batch 21: both rows
        only ever led back to the Extract tab, so labels say it instead)."""
        return self._folder_link_label(
            parent, var,
            "Shared by every tab — it is set on the Extract tab.")

    def _default_write_filename(self):
        """The name Write gives the built file before the user renames it: the
        original's basename plus the plugin's distinguishing suffix
        (``write_output_suffix``, e.g. Stern's "-modified").  ``flash_image``
        plugins build a raw card image the user flashes themselves, so the name
        carries no meaning to the machine — those get a "-modified" default even
        when the plugin set no explicit suffix, so the default never silently
        collides with the original sitting in the same folder."""
        upd = self.write_upd_var.get().strip()
        if not upd:
            return ""
        name = os.path.basename(upd)
        mfr = getattr(self, "_current_mfr", None)
        suffix = getattr(mfr, "write_output_suffix", "") if mfr else ""
        if (not suffix and mfr is not None
                and getattr(mfr.capabilities, "flash_image", False)):
            suffix = "-modified"
        if suffix:
            stem, ext = os.path.splitext(name)
            name = f"{stem}{suffix}{ext}"
        # Pin the plugin's required extension (Stern Spike 2 = .raw, CGC = .img)
        # so the default lands in the right format even when the original was
        # named differently (e.g. a .img card image builds as …-modified.raw).
        if mfr is not None:
            name = mfr.force_write_ext(name)
        return name

    def _target_write_path(self):
        """Absolute path Write will build to given the Output Folder + File Name
        boxes, or "" when either is empty or not applicable (Direct-SSD).
        Mirrors the resolution in ``app.WriteApp._start_write`` so the collision
        hint and the actual build always agree on the destination."""
        if (getattr(self, "write_input_source_var", None) is not None
                and self.write_input_source_var.get() == "ssd"):
            return ""
        out = self.write_output_var.get().strip()
        name = self.write_filename_var.get().strip()
        if not out or not name:
            return ""
        mfr = getattr(self, "_current_mfr", None)
        # Same extension forcing the actual build applies, so the collision
        # hint reflects the real destination (…/name.raw, not …/name).
        if mfr is not None:
            name = mfr.force_write_ext(name)
        spec_ext = ""
        if mfr is not None and mfr.input_spec.extensions:
            spec_ext = mfr.input_spec.extensions[0].lower()
        # Legacy: a full file path typed into the Output Folder box is honoured
        # as the destination directly (the File Name box is then moot).
        if spec_ext and out.lower().endswith(spec_ext):
            return os.path.abspath(out)
        return os.path.abspath(os.path.join(out, name))

    def _maybe_default_write_filename(self):
        """Keep the File Name box tracking ``original + suffix`` until the user
        types a name of their own.  Refill while the box is empty or still holds
        the last value we auto-filled; back off the instant it diverges so we
        never clobber a custom name."""
        default = self._default_write_filename()
        if not default:
            return
        current = self.write_filename_var.get().strip()
        if not current or current == self._write_filename_auto:
            self._write_filename_auto = default
            if default != current:
                self.write_filename_var.set(default)

    def _update_write_filename(self):
        # Direct-SD write has no output file (the card itself is the
        # destination), so there's no name to manage there.
        if (getattr(self, "write_input_source_var", None) is not None
                and self.write_input_source_var.get() == "ssd"):
            self._write_filename_lbl.configure(text="")
            return
        self._maybe_default_write_filename()
        # The plugin's forced extension shows in the Build Image path itself
        # (batch 21 — the old standalone "saved as .raw" label is gone).
        self._refresh_build_path_display()
        self._update_write_filename_hint()

    def _update_write_filename_hint(self):
        """Amber warning under the File Name box when the chosen name would
        overwrite an existing file (or the original itself); blank otherwise —
        the Output Folder + File Name boxes already say where the build lands,
        so a redundant "Output: …" line was noise (a tester 4.6).  The label
        stays put as the layout anchor other rows pack ``before=``."""
        lbl = getattr(self, "_write_filename_lbl", None)
        if lbl is None:
            return
        target = self._target_write_path()
        if not target:
            lbl.configure(text="")
            return
        original = self.write_upd_var.get().strip()
        if original and os.path.abspath(original) == target:
            lbl.configure(
                text="⚠ This name matches the original — rename the build or "
                     "the folder so it isn't overwritten.",
                foreground="#d04040")
        elif os.path.exists(target):
            # Informational, not alarming: Build now asks before overwriting
            # (feedback batch 14), so the standing label just states the
            # fact.
            lbl.configure(
                text=f"{os.path.basename(target)} already exists here — "
                     "Build will ask before overwriting.",
                foreground="#888888")
        else:
            # Explicit-extension feedback: when Write will add or change the
            # typed name's extension to satisfy the plugin's required format,
            # spell out the exact file it will build so the user isn't surprised
            # by a name that differs from what they typed.
            typed = self.write_filename_var.get().strip()
            final = os.path.basename(target)
            if typed and final != typed:
                lbl.configure(text=f"Will build: {final}",
                              foreground="#888888")
            else:
                lbl.configure(text="")

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def _log_context_menu(self, event):
        """Right-click menu on the log pane: Copy / Save As… / Clear."""
        widget = event.widget
        menu = tk.Menu(widget, tearoff=0)
        c = THEMES.get(self._current_theme, {})
        try:
            menu.configure(
                background=c.get("field_bg"), foreground=c.get("fg"),
                activebackground=c.get("select_bg"),
                activeforeground="#ffffff")
        except tk.TclError:
            pass
        has_sel = bool(widget.tag_ranges("sel"))
        menu.add_command(label="Copy" if has_sel else "Copy all",
                         command=lambda w=widget: self._log_copy(w))
        menu.add_command(label="Copy current session log",
                         command=lambda w=widget: self._log_copy_session(w))
        menu.add_command(label="Save As…",
                         command=lambda w=widget: self._log_save_as(w))
        menu.add_command(label="View log history…",
                         command=self._open_log_history)
        menu.add_separator()
        menu.add_command(label="Clear",
                         command=lambda w=widget: self._log_clear(w))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _log_copy(self, widget):
        """Copy the selection (or the whole log if nothing is selected)."""
        try:
            text = widget.get("sel.first", "sel.last")
        except tk.TclError:
            text = widget.get("1.0", "end-1c")
        if not text:
            return
        widget.clipboard_clear()
        widget.clipboard_append(text)

    def _log_copy_session(self, widget):
        """Copy only THIS session's lines — everything below the cut line,
        skipping the seeded previous-session history.  With no cut line in
        the pane (history hidden or none existed) the whole pane IS the
        current session, so it all copies."""
        rng = widget.tag_ranges("cut")
        start = rng[-1] if rng else "1.0"
        text = widget.get(start, "end-1c").lstrip("\n")
        if not text:
            return
        widget.clipboard_clear()
        widget.clipboard_append(text)

    def _log_save_as(self, widget):
        path = filedialog.asksaveasfilename(
            title="Save log as…", defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(widget.get("1.0", "end-1c"))
        except OSError as exc:
            messagebox.showerror("Save log", "Couldn't save the log:\n%s" % exc)

    def _log_clear(self, widget):
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.configure(state=tk.DISABLED)

    def _open_log_history(self):
        """Open the rolling on-disk session log (every line from every
        session, capped by size/age — see core.session_log) in the system's
        default text viewer.  Right-click menu + ⚙ menu both land here."""
        path = session_log.log_path()
        if not os.path.isfile(path):
            messagebox.showinfo(
                "Log history",
                "No log history yet — it starts collecting from now on.\n\n"
                "Everything the log pane shows is also saved to:\n%s" % path)
            return
        import subprocess
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                ok, err = desktop.open_path(path)
                if not ok:
                    raise RuntimeError(err)
        except Exception:
            # No default .log association / no opener — show the folder so
            # the user can still get at the file.
            self._reveal_in_file_manager(path)

    def append_log(self, text, level="info"):
        # Calls before any mfr is selected (e.g. update-check on startup
        # while picker is showing) are buffered against the first mfr's
        # widget once one is selected.  For now, silently drop them.
        ts = time.strftime("%H:%M:%S")
        # Every pane line is also mirrored into the rolling on-disk history
        # (survives restarts and in-place updates — a tester), including
        # buffered lines: the file wants the real event time, not the flush.
        session_log.append(text, level)
        if self._log_text is None:
            # Picker is showing (no mfr log yet) — buffer; _swap_log_widget
            # flushes into the first log widget that appears.
            self._pending_log.append(("line", ts, text, level))
            return
        self._write_log_line(ts, text, level)

    def _write_log_line(self, ts, text, level):
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "ts")
        self._log_text.insert(tk.END, text + "\n", level)
        self._log_text.configure(state=tk.DISABLED)
        self._log_text.see(tk.END)

    def update_log_line(self, key, text, level="info"):
        """Create-or-update a single *keyed* log line in place (live per-sound
        decode progress: one animating line per sound, not a line per tick).

        The first call for a key appends a new line and remembers its span via a
        per-key tag; later calls rewrite just that span.  Keys are namespaced by
        a run counter (bumped on each run start) so a re-run never edits the
        previous run's lines left in the scrollback."""
        t = self._log_text
        if t is None:
            return
        tag = "ll_%d_%s" % (self._log_line_run, key)
        t.configure(state=tk.NORMAL)
        rng = t.tag_ranges(tag)
        if rng:
            t.delete(rng[0], rng[1])
            t.insert(rng[0], text, (tag, level))
        else:
            t.insert(tk.END, text, (tag, level))
            t.insert(tk.END, "\n")
            t.see(tk.END)
        t.configure(state=tk.DISABLED)

    def _install_callback_error_logger(self, root):
        """Send exceptions raised inside Tk callbacks to the session log.

        Tk's default handler prints the traceback to stderr, which a windowed
        build has nowhere to show — so a button or an edit that half-completed
        looked to the user like a dead control with no error anywhere.  That is
        how a tester's F2 rename read: the file was renamed but the exception
        skipped the list refresh, leaving a row with the old name that clicked
        into nothing (batch 23).  One line in the log, and the traceback in the
        session log for a bug report.

        Best-effort and non-fatal: the handler never raises out of itself, and
        an interpreter that won't take the assignment is left as it was."""
        import traceback

        def _report(exc_type, exc_value, exc_tb):
            try:
                detail = "".join(traceback.format_exception(
                    exc_type, exc_value, exc_tb))
                session_log.append(detail)
                self.append_log(
                    "Internal error in %s: %s — the action may be half done; "
                    "re-scan the folder to be sure of what the list shows. "
                    "The details are in the session log."
                    % (getattr(exc_type, "__name__", "?"), exc_value),
                    "error")
            except Exception:
                pass
        try:
            root.report_callback_exception = _report
        except Exception:
            pass

    def append_log_link(self, text, url):
        ts = time.strftime("%H:%M:%S")
        session_log.append("%s (%s)" % (text, url))
        if self._log_text is None:
            self._pending_log.append(("link", ts, text, url))
            return
        self._write_log_link(ts, text, url)

    def _write_log_link(self, ts, text, url):
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"[{ts}] ", "ts")
        tag = f"link_{id(url)}"
        self._log_text.tag_configure(
            tag, foreground=THEMES[self._current_theme]["link"], underline=True)
        self._log_text.tag_bind(tag, "<Button-1>",
                                lambda e, u=url: self.open_link(u))
        self._log_text.tag_bind(tag, "<Enter>",
                                lambda e: self._log_text.configure(cursor="hand2"))
        self._log_text.tag_bind(tag, "<Leave>",
                                lambda e: self._log_text.configure(cursor=""))
        self._log_text.insert(tk.END, text + "\n", tag)
        self._log_text.configure(state=tk.DISABLED)
        self._log_text.see(tk.END)

    # ------------------------------------------------------------------
    # Phases / progress
    # ------------------------------------------------------------------

    def set_phase(self, index, mode="extract"):
        labels = (self._extract_phase_labels if mode == "extract"
                  else self._write_phase_labels)
        c = THEMES[self._current_theme]
        for i, lbl in enumerate(labels):
            text = lbl.cget("text") or ""
            name = text.lstrip("○● ").strip()
            if i < index:
                lbl.configure(text=f"● {name}", foreground=c["success"])
            elif i == index:
                lbl.configure(text=f"● {name}", foreground=c["accent"])
            else:
                lbl.configure(text=f"○ {name}", foreground=c["gray"])

    def reset_steps(self, mode="extract"):
        phases = (self._extract_phases if mode == "extract"
                  else self._write_phases)
        labels = (self._extract_phase_labels if mode == "extract"
                  else self._write_phase_labels)
        c = THEMES[self._current_theme]
        for lbl, name in zip(labels, phases):
            lbl.configure(text=f"○ {name}", foreground=c["gray"])
        self._progress_bar["value"] = 0

    def set_write_phases(self, phases):
        """Swap the Write phase row to an arbitrary ``phases`` tuple and reset
        it to all-pending — used for the flash-image run, whose Check/Write/
        Flush steps differ from the standard Build/Direct-SD write phases.  The
        next manufacturer or source change restores the standard tuple via
        ``apply_manufacturer`` / ``_refresh_extract_phases``."""
        if not phases:
            return
        self._rebuild_phase_steps(self._extract_phases, phases)
        self.reset_steps(mode="write")

    def show_chained_phases(self, phases):
        """Swap the Extract phase row to an arbitrary ``phases`` tuple — the
        chained Auto-transcribe / Music-ID step lists — and reset it to all
        pending, so each post-extract step shows its OWN chips advancing instead
        of leaving the extract row (e.g. "Checksums") stuck active.  The next
        Extract run restores the standard tuple via ``_refresh_extract_phases``.
        A falsy ``phases`` leaves the row untouched (no empty chip strip)."""
        if not phases:
            return
        self._rebuild_phase_steps(phases, self._write_phases)
        self.reset_steps(mode="extract")

    def set_progress(self, current, total, desc="", mode="extract"):
        if total > 0:
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate")
            self._progress_bar["value"] = int(100 * current / total)
        else:
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start(12)
        if desc:
            self.set_status(desc)

    def set_status(self, text):
        self._status_label.configure(text=text)

    # ------------------------------------------------------------------
    # Running state
    # ------------------------------------------------------------------

    def set_cancelling(self):
        """User clicked Cancel: freeze the run's Cancel button (one press is
        enough — the press cancels the running job and every queued follow-up)
        and show feedback.  The action buttons stay disabled; they're re-enabled
        only when the job actually stops, via ``set_running(False)``."""
        # Only the initiating side's button shows "Cancel" (the others are
        # parked disabled on their idle labels) — flip just that one to
        # "Cancelling…" so idle labels don't get clobbered; set_running(False)
        # restores everything.
        for btn in (self._extract_btn, self._write_btn,
                    getattr(self, "_flash_btn", None)):
            if btn is None:
                continue
            try:
                if str(btn.cget("text")) == "Cancel":
                    btn.configure(text="Cancelling…")
                btn.configure(state=tk.DISABLED)
            except tk.TclError:
                pass
        self.set_status("Cancelling...")

    def set_running(self, running, mode="extract"):
        # Authoritative run flag (read by _is_running()); set before any widget
        # state so a re-entrant refresh sees the right value.
        self._running = running
        if not running:
            # A finished run may have staged, built, or reverted files on
            # disk — invalidate the Write change-scan fingerprint so the next
            # visit to the tab really re-scans.
            self._write_disk_epoch = getattr(self, "_write_disk_epoch", 0) + 1
        if running:
            # New run → new namespace for in-place keyed log lines.
            self._log_line_run += 1
            # Replace the previous run's terminal status ("Complete!" /
            # "Failed") right away — it used to linger well into the new run
            # until the first progress callback, which read as "already done"
            # (feedback batch 8).
            self.set_status("Starting…")
            # (Re-theming is a heavy synchronous re-style; the ⚙ menu greys
            # out its theme entry while running so clicks can't queue up.)
            # Only the initiating side's button becomes the live Cancel; the
            # other greys out with its idle label (feedback batch 9 — two
            # simultaneous "Cancel"s, and the Write one killed his extract).
            self._set_extract_button_running(True, active=(mode == "extract"))
            self._set_write_button_running(True, active=(mode == "write"))
            if hasattr(self, "_revert_all_btn"):
                self._revert_all_btn.configure(state=tk.DISABLED)
            # One live Cancel at a time: kill any in-flight Modified Files
            # scan (its "Cancel scan" would sit next to the run's "Cancel" —
            # feedback batch 10) and grey Refresh for the run's duration.
            # The scan re-fires when the run ends.
            if "write_preview" in self._scan_spinner_after:
                self._cancel_scan("write_preview")
                self._rescan_preview_after_run = True
                try:
                    self._write_preview_empty.configure(
                        text="Scan paused — it re-runs when this "
                             "operation finishes.")
                except tk.TclError:
                    pass
            scan_btn = self._scan_buttons.get("write_preview")
            if scan_btn is not None:
                try:
                    scan_btn.configure(state=tk.DISABLED)
                except tk.TclError:
                    pass
            # Lock the Back button while work is in flight - we don't want
            # the user navigating away from a running pipeline.
            self.set_back_enabled(False)
            # Start the progress bar marching immediately so the user
            # gets visual feedback before the first progress callback
            # arrives — some plugins (Williams DMD scan) take a few
            # seconds of CPU spin-up before they emit any progress.
            # The first set_progress() with total>0 switches it to
            # determinate.
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start(12)
            # Cancel any prior tick chain before starting a new one.
            # Without this, a stale chain (e.g. from a back-to-back
            # extract-then-transcribe with two set_running(True) calls)
            # keeps ticking even after set_running(False) cancels what
            # _timer_id points to — orphan _tick_timer chains rewrite
            # the elapsed label indefinitely.
            if self._timer_id:
                self.root.after_cancel(self._timer_id)
                self._timer_id = None
            self._start_time = time.time()
            self._tick_timer()
        else:
            self._set_extract_button_running(False)
            self._set_write_button_running(False)
            # Unconditional: restores the Flash opener whether or not this run
            # was a flash (no-op otherwise).
            self.set_flash_running(False)
            # Revert button tracks the change count, not a blanket re-enable —
            # disabled when there's nothing to revert (see _update_revert_btn_state).
            self._update_revert_btn_state()
            # Restore the Modified Files Refresh button and re-fire any scan
            # the run pre-empted (or that was requested mid-run).
            scan_btn = self._scan_buttons.get("write_preview")
            if scan_btn is not None:
                try:
                    scan_btn.configure(state=tk.NORMAL)
                except tk.TclError:
                    pass
            if getattr(self, "_rescan_preview_after_run", False):
                self._rescan_preview_after_run = False
                self._scan_reasons["write_preview"] = "the run just finished"
                self._maybe_rescan_write_preview()
            self.set_back_enabled(True)
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate")
            if self._timer_id:
                self.root.after_cancel(self._timer_id)
                self._timer_id = None
            # Belt-and-suspenders: clear _start_time so any orphan
            # tick that slipped past the cancel becomes a no-op for
            # the elapsed label update.
            self._start_time = None
            self._elapsed_label.configure(text="")
            # Stop the live DMD-preview after-pump.  The label keeps
            # the last frame on screen as a static snapshot of where
            # capture ended (useful when reviewing what went wrong).
            self._stop_dmd_preview_pump()

    def _tick_timer(self):
        if self._start_time is None:
            # Pipeline finished -- don't re-schedule.  Leaving the
            # chain alive would burn CPU forever and (worse) reach in
            # to rewrite an elapsed label that we already cleared.
            self._timer_id = None
            return
        elapsed = int(time.time() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._elapsed_label.configure(text=f"{m:02d}:{s:02d}")
        self._timer_id = self.root.after(1000, self._tick_timer)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _toggle_theme(self):
        new = "light" if self._current_theme == "dark" else "dark"
        self._apply_theme(new)
        if self._on_theme_change:
            self._on_theme_change(new)

    # ------------------------------------------------------------------
    # Update-available banner
    # ------------------------------------------------------------------

    def _build_update_banner(self, parent):
        """Build the persistent 'update available' banner widget.

        Created but not packed.  ``show_update_banner`` packs it
        above the back-button row using ``before=self._top_bar`` so
        it stays at the very top of the window across picker ↔
        working-view transitions.

        Uses raw ``tk`` widgets (not ttk) so the contrasting blue
        background + light-blue border stick regardless of the
        current theme — the banner is intentionally hard to miss.
        """
        self._update_banner = tk.Frame(
            parent, bg="#1e4a8a",
            highlightbackground="#3794ff", highlightthickness=1)
        # Lightning-bolt icon on the left.
        tk.Label(
            self._update_banner,
            text="⚡",
            bg="#1e4a8a", fg="#ffd700",
            font=(_SANS_FONT, 14, "bold")
        ).pack(side=tk.LEFT, padx=(10, 6), pady=4)
        self._update_banner_text = tk.Label(
            self._update_banner,
            text="",
            bg="#1e4a8a", fg="#ffffff",
            font=(_SANS_FONT, 10),
            anchor=tk.W)
        self._update_banner_text.pack(
            side=tk.LEFT, padx=0, pady=4, fill=tk.X, expand=True)
        # Install button — the in-app update path, on the platforms that
        # have one.  Windows downloads the setup exe itself (no browser
        # download => no Mark-of-the-Web => no SmartScreen "Windows
        # protected your PC" pass on every release) and runs it silently;
        # Linux downloads the AppImage and offers to start it, because
        # from inside an AppImage a browser handoff is unreliable enough
        # that the Download button did nothing at all (a tester).  Built here
        # but packed only by show_update_banner when the release carries
        # this platform's asset and app.py wired the flow (jim-beam).
        # Its verb is set there too — Linux installs nothing.
        # flat_button, not tk.Button: Aqua draws buttons natively and ignores
        # bg/activebackground, so on macOS all three of these came out as
        # default grey slabs on the blue strip.  See widgets.flat_button.
        self._update_install_btn = flat_button(
            self._update_banner, "Install update",
            bg="#3794ff", fg="#ffffff", active_bg="#5fa5ff",
            command=self._install_update_clicked,
        )
        # Download button — opens the release page in the browser.
        # Relabelled "Release notes" when the Install button is shown.
        # tk.Button (not ttk) so its bg color sticks; ttk's themed
        # blue would clash with the banner background on light mode.
        self._update_download_btn = flat_button(
            self._update_banner, "Download",
            bg="#3794ff", fg="#ffffff", active_bg="#5fa5ff",
            command=self._open_update_url,
        )
        self._update_download_btn.pack(side=tk.LEFT, padx=4, pady=4)
        # Dismiss × — closes the banner for this session.
        flat_button(
            self._update_banner, "✕",
            bg="#1e4a8a", fg="#ffffff", active_bg="#3a5a8a",
            command=self._dismiss_update_banner, padx=6,
        ).pack(side=tk.LEFT, padx=(0, 6), pady=4)
        # The URL to open when the Download button is clicked.
        # Populated by show_update_banner.
        self._update_banner_url = None

    def show_update_banner(self, version, url, installer=None):
        """Display the 'update available' banner.

        Called from :meth:`App._check_for_update` on the main thread
        (via ``root.after(0, ...)``) when the GitHub release feed
        reports a newer version.  Idempotent — re-calling with the
        same args just re-shows / updates the banner; the user can
        still dismiss it after.

        ``installer`` (updater._pick_installer_asset dict) enables the
        one-click update button; without it the banner keeps the plain
        open-the-release-page Download button.
        """
        from pinball_decryptor import __version__ as _current
        self._update_banner_url = url
        can_auto = bool(installer and self._on_install_update)
        # The gear carries a ● notification too, so the news survives a
        # dismissed banner (its menu gets an install/download entry).
        self._update_available = (version, url,
                                  installer if can_auto else None)
        if can_auto:
            if not self._update_install_btn.winfo_ismapped():
                self._update_install_btn.pack(
                    side=tk.LEFT, padx=4, pady=4,
                    before=self._update_download_btn)
            self._update_install_btn.configure(
                text=_update_action_verb(installer))
            self._update_download_btn.configure(text="Release notes")
        else:
            self._update_install_btn.pack_forget()
            self._update_download_btn.configure(text="Download")
        self._refresh_gear_badge()
        self._update_banner_text.configure(
            text=f"Pinball Asset Decryptor v{version} is available "
                 f"— you're on v{_current}.")
        # Anchor above the back-button row so the banner sits at the
        # very top of the window regardless of which view (picker /
        # mfr) is currently shown.
        try:
            self._update_banner.pack(
                fill=tk.X, side=tk.TOP,
                before=self._top_bar)
        except tk.TclError:
            # Top bar not built yet — defer; this method runs on the
            # main thread from a startup-time worker so the widgets
            # should exist by now, but be defensive anyway.
            self._update_banner.pack(fill=tk.X, side=tk.TOP)

    def _dismiss_update_banner(self):
        """Hide the update banner for this session."""
        self._update_banner.pack_forget()

    def _open_update_url(self):
        """Open the release page in the user's default browser."""
        self.open_link(self._update_banner_url,
                       what="the release page")

    def open_link(self, url, what="that link"):
        """Open *url* in the browser, and say so when it doesn't work.

        Off the main thread because the launch waits a beat to see
        whether the opener actually survived (core.desktop), and Tk must
        not freeze mid-click.  A failure isn't silent: on a Linux
        AppImage the desktop's opener can be missing or refuse the
        bundle's environment entirely (a tester), so we put the URL on the
        clipboard and show it, rather than leaving a dead button.
        """
        if not url:
            return
        import threading

        def _work():
            ok, err = desktop.open_url(url)
            try:
                self.root.after(0, lambda: self._link_opened(url, what,
                                                             ok, err))
            except Exception:
                pass                       # window gone mid-flight

        threading.Thread(target=_work, daemon=True).start()

    def _link_opened(self, url, what, ok, err):
        if ok:
            return
        session_log.append("Could not open %s: %s (%s)" % (what, url, err),
                           "warn")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            copied = "\n\nThe link has been copied to your clipboard."
        except Exception:
            copied = ""
        messagebox.showwarning(
            "Couldn't open your browser",
            "Nothing here could open %s.\n\n%s%s\n\n(%s)"
            % (what, url, copied, err or "no details"))

    def _install_update_clicked(self):
        """Banner / gear "Install update" — hand off to app.py's flow."""
        if not (self._update_available and self._on_install_update):
            return
        version, _url, installer = self._update_available
        if installer:
            self._on_install_update(version, installer)

    def open_update_download_dialog(self, version, on_cancel):
        """Small 'Downloading update…' progress window.

        Returns a handle with ``set_progress(done, total)`` and
        ``close()`` — both main-thread only (app.py marshals its worker
        thread's progress through ``root.after``).  Closing the window
        or clicking Cancel calls ``on_cancel`` (the download loop then
        aborts and app.py closes the dialog).
        """
        from types import SimpleNamespace
        c = THEMES[self._current_theme]
        win = tk.Toplevel(self.root)
        win.title("Downloading update")
        win.configure(bg=c["bg"])
        win.transient(self.root)
        win.resizable(False, False)
        label = tk.Label(
            win, text=f"Downloading Pinball Asset Decryptor v{version}…",
            bg=c["bg"], fg=c["fg"], font=(_SANS_FONT, 10))
        label.pack(padx=16, pady=(14, 6))
        bar = ttk.Progressbar(win, length=380, mode="indeterminate")
        bar.pack(padx=16, pady=2)
        bar.start(12)
        detail = tk.Label(win, text="Starting download…",
                          bg=c["bg"], fg=c["gray"], font=(_SANS_FONT, 9))
        detail.pack(padx=16, pady=(2, 4))
        state = {"cancelled": False, "determinate": False}

        def _cancel():
            if state["cancelled"]:
                return
            state["cancelled"] = True
            detail.configure(text="Cancelling…")
            on_cancel()

        cancel_btn = ttk.Button(win, text="Cancel", command=_cancel,
                                style="Danger.TButton")
        cancel_btn.pack(pady=(2, 12))
        win.protocol("WM_DELETE_WINDOW", _cancel)
        # Center over the main window.
        win.update_idletasks()
        px, py = self.root.winfo_rootx(), self.root.winfo_rooty()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        w, h = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

        def set_progress(done, total):
            if state["cancelled"] or not win.winfo_exists():
                return
            if total > 0:
                if not state["determinate"]:
                    state["determinate"] = True
                    bar.stop()
                    bar.configure(mode="determinate", maximum=100)
                bar.configure(value=done * 100 / total)
                detail.configure(
                    text=f"{done / 1048576:.0f} of "
                         f"{total / 1048576:.0f} MB")
            else:
                detail.configure(text=f"{done / 1048576:.0f} MB")

        def close():
            if win.winfo_exists():
                win.destroy()

        return SimpleNamespace(set_progress=set_progress, close=close)

    # ------------------------------------------------------------------
    # "Source image changed" banner
    # ------------------------------------------------------------------

    def _build_stale_source_banner(self, parent):
        """Build the persistent amber 'source image changed' banner.

        Created but not packed.  :meth:`_refresh_stale_source_banner` packs it
        ``before=self._top_bar`` (same anchor as the update banner) when the
        current assets folder's recorded source image no longer matches disk.
        Raw ``tk`` widgets so the amber colours stick across themes.
        """
        self._stale_source_banner = tk.Frame(
            parent, bg="#5a4416",
            highlightbackground="#e0a836", highlightthickness=1)
        tk.Label(
            self._stale_source_banner, text="⚠",
            bg="#5a4416", fg="#ffd966",
            font=(_SANS_FONT, 14, "bold")
        ).pack(side=tk.LEFT, padx=(10, 6), pady=4)
        self._stale_source_banner_text = tk.Label(
            self._stale_source_banner, text="",
            bg="#5a4416", fg="#ffe9b0",
            font=(_SANS_FONT, 10),
            anchor=tk.W, justify=tk.LEFT, wraplength=820)
        self._stale_source_banner_text.pack(
            side=tk.LEFT, padx=0, pady=4, fill=tk.X, expand=True)
        # A WORD, not a bare ✕ (a tester asked for "a dismiss button" for this
        # banner while running a build that already had one).  The glyph sat
        # at the far right of a wide window, a couple of rows under the
        # window's own ✕, and read as title-bar chrome rather than a control
        # of the strip it was on.  Same right-hand slot, same flat_button as
        # the update banner's Download / Install (tk.Button is ignored by Aqua
        # — see widgets.flat_button), now in the accent colour so it reads as
        # a button on the amber.
        flat_button(
            self._stale_source_banner, "Dismiss",
            bg="#e0a836", fg="#3a2a08", active_bg="#f0c464",
            command=self._dismiss_stale_source_banner, padx=10,
        ).pack(side=tk.LEFT, padx=(8, 10), pady=4)
        # (assets folder, warning text) the user dismissed this session —
        # suppresses re-show until the staleness clears (re-Extract) and
        # recurs.  Per folder so dismissing one project's banner can't silence
        # another's.  The durable half lives in that folder's own sidecar
        # (core.extract_source.dismiss_stale_source); this is what still works
        # when the folder can't be written to.
        self._stale_source_dismissed = None

    def _refresh_stale_source_banner(self, *, on_asset_tab=True):
        """Show/hide the source-changed banner against current disk state.

        Called on entry to the Write / Replace tabs.  ``on_asset_tab=False``
        (Extract/other tabs) always hides it — the warning is about editing
        stale assets, which only applies on the asset-editing tabs.
        """
        banner = getattr(self, "_stale_source_banner", None)
        if banner is None:
            return
        path = (self.write_assets_var.get() or "").strip()
        stale = None
        if path:
            try:
                stale = stale_source_message(path)
            except Exception:
                stale = None
        if stale is None:
            # Source matches (or no sidecar) — clear any prior dismissal so a
            # later swap re-surfaces the warning.
            self._stale_source_dismissed = None
        show = bool(on_asset_tab and stale
                    and self._stale_source_dismissed != (path, stale))
        if show:
            # Dismissed in an earlier session: the sidecar remembers which
            # source-image state was waved through, so the same one stays
            # quiet after a restart.  (Reaching here means `path` is set —
            # an empty one leaves `stale` None and `show` False.)
            try:
                show = not stale_dismissed(path)
            except Exception:
                pass
        if show:
            self._stale_source_banner_text.configure(text=stale)
            if not banner.winfo_ismapped():
                try:
                    banner.pack(fill=tk.X, side=tk.TOP, before=self._top_bar)
                except tk.TclError:
                    banner.pack(fill=tk.X, side=tk.TOP)
        elif banner.winfo_ismapped():
            banner.pack_forget()

    def _dismiss_stale_source_banner(self):
        """Hide the banner, and remember that this image state was accepted.

        Dismissing used to last only until the next launch, which for a user
        who has looked and knows the change is harmless means meeting the same
        warning every session forever.  The acknowledgement is now written
        into the extract's own sidecar against the source image's current
        signature, so it survives a restart — and the next change to that
        image doesn't match it, so a genuinely new one still gets through.
        """
        path = (self.write_assets_var.get() or "").strip()
        self._stale_source_dismissed = (
            path, self._stale_source_banner_text.cget("text"))
        if path:
            try:
                dismiss_stale_source(path)
            except Exception:
                pass          # read-only folder — the session flag still holds
        self._stale_source_banner.pack_forget()

    def _handle_check_updates(self):
        """Manual 'Check for updates' button click."""
        if self._on_check_updates:
            self._on_check_updates()

    def set_update_check_running(self, running):
        """Flag the update check as in flight.

        The ⚙ menu is built fresh per click, so all this needs to do is
        remember the state: while ``True`` the menu's entry reads
        "Checking for updates…" and is disabled so the user can't queue up
        concurrent requests.
        """
        self._update_check_busy = bool(running)

    def show_up_to_date_toast(self):
        """Inform the user the manual check found nothing.

        Called from app.py when ``check_for_update`` returns None on
        a manual request.  Auto-check runs at startup silently no-op
        in this case; only a user-initiated check triggers a
        modal so they have feedback that the click was received.
        """
        from pinball_decryptor import __version__ as _current
        messagebox.showinfo(
            "Up to date",
            f"You're on the latest version (v{_current}).")

    def _apply_theme(self, theme):
        c = THEMES[theme]
        self._current_theme = theme

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=c["bg"], foreground=c["fg"],
                        fieldbackground=c["field_bg"], bordercolor=c["border"],
                        troughcolor=c["trough"], selectbackground=c["select_bg"],
                        selectforeground="#ffffff", insertcolor=c["fg"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        # Folder paths shown as links.  Project properties turned its two
        # paths into links (batch 21: "reveal" read as jargon, and a link on
        # the path itself says where the click goes) — batch 29 asked why the
        # Project Folder rows on the tabs hadn't followed, so they have now.
        style.configure("Link.TLabel", background=c["bg"], foreground=c["link"],
                        font=(_SANS_FONT, 9, "underline"))
        style.configure("TLabelframe", background=c["bg"], foreground=c["fg"])
        style.configure("TLabelframe.Label", background=c["bg"],
                        foreground=c["fg"])
        style.configure("TButton", background=c["button"], foreground=c["fg"])
        style.map("TButton",
                  background=[("active", c["accent"]), ("pressed", c["accent"])],
                  foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])
        # Color-coded action buttons (David): "Go.TButton" = green
        # go/confirm actions (Extract, Build, Build / flash, dialog Start);
        # "Danger.TButton" = red destructive ones (live run Cancels, Revert
        # all changes).  Neutral buttons (Browse, Refresh, …) stay on plain
        # TButton.  Clam draws flat fills, so this is a solid chip with a
        # hover/pressed shade; DISABLED falls back to the neutral gray so a
        # parked button doesn't stay loudly colored ("disabled" listed
        # first — ttk.map takes the first matching state).
        for name, fill, hot in (("Go.TButton", c["go_btn"], c["go_btn_hot"]),
                                ("Danger.TButton", c["danger_btn"],
                                 c["danger_btn_hot"])):
            style.configure(name, background=fill, foreground="#ffffff")
            style.map(name,
                      background=[("disabled", c["button"]),
                                  ("pressed", hot), ("active", hot)],
                      foreground=[("disabled", c["gray"]),
                                  ("pressed", "#ffffff"),
                                  ("active", "#ffffff")])
        # ttk.Checkbutton — clam's default flips the background to
        # white on hover/active, which makes our light-grey text
        # invisible in dark mode.  Pin the background to our panel
        # color in every state; convey hover via the indicator
        # accent colour instead.
        style.configure("TCheckbutton",
                        background=c["bg"], foreground=c["fg"],
                        focuscolor=c["bg"])
        style.map("TCheckbutton",
                  background=[("active", c["bg"]),
                              ("selected", c["bg"]),
                              ("pressed", c["bg"])],
                  foreground=[("active", c["accent"]),
                              ("disabled", c["gray"])],
                  indicatorcolor=[("selected", c["accent"]),
                                  ("!selected", c["field_bg"])],
                  indicatorbackground=[("active", c["field_bg"])])
        # ttk.Radiobutton has the same clam-default hover bug.
        style.configure("TRadiobutton",
                        background=c["bg"], foreground=c["fg"],
                        focuscolor=c["bg"])
        style.map("TRadiobutton",
                  background=[("active", c["bg"]),
                              ("selected", c["bg"]),
                              ("pressed", c["bg"])],
                  foreground=[("active", c["accent"]),
                              ("disabled", c["gray"])],
                  indicatorcolor=[("selected", c["accent"]),
                                  ("!selected", c["field_bg"])])
        style.configure("TEntry", fieldbackground=c["field_bg"],
                        foreground=c["fg"])
        # ttk.Combobox with state="readonly" otherwise renders as
        # disabled (gray-on-dark, illegible).  Force the readonly state
        # to use our normal field colors.  The dropdown popup is a Tk
        # Listbox (not ttk), so set it via the option DB.
        style.configure("TCombobox", fieldbackground=c["field_bg"],
                        foreground=c["fg"], background=c["bg"],
                        arrowcolor=c["fg"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", c["field_bg"]),
                                   ("disabled", c["field_bg"])],
                  foreground=[("readonly", c["fg"]),
                              ("disabled", c["gray"])],
                  selectbackground=[("readonly", c["select_bg"])],
                  selectforeground=[("readonly", "#ffffff")],
                  background=[("readonly", c["bg"])],
                  arrowcolor=[("readonly", c["fg"])])
        self.root.option_add("*TCombobox*Listbox.background",      c["field_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground",      c["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["select_bg"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        # The round icon buttons (ⓘ badges, header home/?/⚙) are plain
        # Canvases, invisible to ttk styling — keep their backdrops on the
        # theme's panel color AND re-blend their anti-aliased disc images
        # against it (the discs are pre-blended opaque, so a theme flip
        # would otherwise leave a halo of the old backdrop).
        for _badge in self._round_icons:
            _badge.configure(bg=c["bg"])
            _badge.icon_bg = c["bg"]
            self._refresh_round_icon(_badge)
        # The Default Settings scroll canvas is a raw tk.Canvas (ttk can't
        # host a scrollable frame), so it needs its backdrop set explicitly or
        # it renders as a big white box in dark mode.
        if hasattr(self, "_settings_canvas"):
            self._settings_canvas.configure(bg=c["bg"])
        style.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
        style.configure("TNotebook.Tab", background=c["button"],
                        foreground=c["fg"], padding=(10, 4))
        style.map("TNotebook.Tab",
                  background=[("selected", c["tab_selected"]),
                              ("active", c["accent"])],
                  foreground=[("selected", c["fg"]), ("active", "#ffffff")])
        style.configure("Horizontal.TProgressbar",
                        troughcolor=c["trough"], background=c["accent"])
        style.configure("TSeparator", background=c["border"])
        # ttk.Treeview — default clam theme leaves rows white-on-black
        # text even when everything else around it is dark; the
        # Modified Files Preview tree on the Write tab needs explicit
        # styling.  Three style names matter: the body, the column
        # headers, and the selected-row state.
        style.configure(
            "Treeview",
            background=c["field_bg"],
            foreground=c["fg"],
            fieldbackground=c["field_bg"],
            bordercolor=c["border"],
            lightcolor=c["field_bg"],
            darkcolor=c["field_bg"])
        style.configure(
            "Treeview.Heading",
            background=c["button"],
            foreground=c["fg"],
            relief="flat")
        style.map(
            "Treeview.Heading",
            background=[("active", c["accent"])],
            foreground=[("active", "#ffffff")])
        style.map(
            "Treeview",
            background=[("selected", c["select_bg"])],
            foreground=[("selected", "#ffffff")])
        # Re-bind the row tag colors to the new theme so the tree
        # rows recolor when the user toggles dark/light mid-session.
        if hasattr(self, "_write_preview_tree"):
            self._write_preview_tree.tag_configure(
                "modified", foreground=c["link"])
            # Pending Replace-Audio/Video rows — staged at build, not on disk
            # yet; use the "success" hue to read as queued-and-ready.
            self._write_preview_tree.tag_configure(
                "pending", foreground=c["success"])
        if hasattr(self, "_audio_tree"):
            self._audio_tree.tag_configure("assigned", foreground=c["success"])
            # Already changed on disk by an earlier build — same hue as the
            # Write tab's "Modified" rows so the two views read as one truth.
            self._audio_tree.tag_configure("changed", foreground=c["link"])
        for pane in (getattr(self, "_audio_pane_orig", None),
                     getattr(self, "_audio_pane_rep", None)):
            if pane is not None:
                pane.apply_theme(c)

        if hasattr(self, "_video_tree"):
            self._video_tree.tag_configure("assigned", foreground=c["success"])
            self._video_tree.tag_configure("changed", foreground=c["link"])
        for pane in (getattr(self, "_video_pane_orig", None),
                     getattr(self, "_video_pane_rep", None)):
            if pane is not None:
                pane.apply_theme(c)

        if hasattr(self, "_image_tree"):
            self._image_tree.tag_configure("assigned", foreground=c["success"])
            self._image_tree.tag_configure("changed", foreground=c["link"])
        for _attr in ("_image_canvas", "_image_canvas_rep"):
            _cv = getattr(self, _attr, None)
            if _cv is not None:
                _cv.configure(highlightbackground=c["border"])

        if hasattr(self, "_text_tree"):
            self._text_tree.tag_configure("assigned", foreground=c["success"])
            # Refresh the byte-budget readout's normal colour for the new theme.
            self._text_update_budget()

        # Partition Explorer's preview is a raw tk.Text over a raw tk.Canvas
        # (see _build_partition_tab).
        if getattr(self, "_pex_preview", None) is not None:
            self._pex_preview.configure(
                bg=c["field_bg"], fg=c["fg"], insertbackground=c["fg"],
                selectbackground=c["select_bg"],
                highlightbackground=c["border"])
        if getattr(self, "_pex_preview_canvas", None) is not None:
            self._pex_preview_canvas.configure(
                bg=c["field_bg"], highlightbackground=c["border"])
        if getattr(self, "_pex_tree", None) is not None:
            self._pex_tree.tag_configure("pex_changed",
                                         foreground=c["warning"])

        # Any open Image Info window keeps its own bg (raw Toplevel).
        _info = getattr(self, "_info_win", None)
        if _info is not None:
            try:
                if _info.winfo_exists():
                    self._theme_toplevel(_info)
            except tk.TclError:
                pass

        self.root.configure(background=c["bg"])
        # Re-skin EVERY cached per-mfr log widget — not just the currently-
        # visible one — so switching mfrs after a theme change still looks
        # right.
        for bundle in self._log_widgets.values():
            self._apply_log_theme(bundle["text"])
        # Rebuild the picker cards with the new theme colors.
        if hasattr(self, "_picker_view"):
            self._picker_view.apply_theme()
        # Re-skin the header era-switcher pills (raw tk.Labels with explicit
        # colours) so the active/muted contrast follows the new theme.
        if hasattr(self, "_era_badge_widgets"):
            self._refresh_era_badges()

        # (The header icons are round _make_round_icon canvases now — no
        # Icon.TButton style needed; their backdrop re-skin is above.)

        # An open tips window re-renders with the new palette.
        if self._help_window is not None:
            self._help_window.refresh()

        # Match the Windows title bar to the theme via DWM's immersive
        # dark mode.  Walk to the actual title-bearing HWND: Tk's
        # winfo_id() returns the inner client-area HWND on Windows;
        # GetParent walks up to the toplevel that owns the title bar.
        # Earlier versions called GetForegroundWindow() instead, which
        # at startup is whatever the user was focused on (a terminal,
        # the launcher, Explorer) — so the dark title bar usually
        # landed on the wrong window or was silently skipped.
        if sys.platform == "win32":
            try:
                import ctypes
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                value = ctypes.c_int(1 if theme == "dark" else 0)
                inner_hwnd = self.root.winfo_id()
                title_hwnd = (ctypes.windll.user32.GetParent(inner_hwnd)
                              or inner_hwnd)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    title_hwnd,
                    DWMWA_USE_IMMERSIVE_DARK_MODE,
                    ctypes.byref(value),
                    ctypes.sizeof(value))
            except Exception:
                pass

        # Repaint the scrollable mfr-view canvas to the theme bg.  Tk
        # canvases default to system white, which otherwise shows
        # through as an empty white strip below the log whenever the
        # window is taller than the inner content.
        if hasattr(self, "_mfr_view_canvas"):
            try:
                self._mfr_view_canvas.configure(background=c["bg"])
            except Exception:
                pass
