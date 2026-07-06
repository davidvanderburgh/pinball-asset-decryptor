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
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from ..core.checksums import TRACKING_SIDECARS
from ..core.config import EXTRACT_PHASES, WRITE_PHASES
from ..core.extract_source import stale_source_message
from ..core.staged_originals import ORIG_DIR
from .theme import THEMES, detect_system_theme, platform_font

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
from .widgets import _Tooltip  # noqa: E402


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

# Replace-Audio "Group duplicates" parent-row iid prefix — same collision
# guarantee as _IMG_GROUP_IID (slot iids are relative paths, never ::-led).
_AUD_DUP_GROUP_IID = "::dupgrp::"

# Fully-transparent 16×16 RGBA PNG — the "Blank all images" group action
# assigns it to every slot in a scene so the whole element renders as nothing;
# Write's normal staging rescales/re-encodes it per slot like any replacement.
_BLANK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAEklEQVR42mNgGAWjYBSM"
    "AggAAAQQAAGvRYgsAAAAAElFTkSuQmCC")


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
        self._tick_job = None     # after() id for the position timer
        self._render_id = 0       # bump to drop stale async renders
        self._spec_img = None     # PhotoImage ref (must stay alive)
        self._hint = ""           # message shown when nothing is loaded

        self.frame = ttk.Frame(parent)
        ttk.Label(self.frame, text=title, font=(_SANS_FONT, 9)).pack(
            pady=(2, 1))
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
        self._start_pos = pos
        self._start_t = time.monotonic()
        self.pos = pos
        self.playing = True
        self._set_play_btn(True)
        self._schedule_tick()

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
        self.pos = self._start_pos + (time.monotonic() - self._start_t)
        # Stop at the trim point if there is one, else the file's end.
        stop_at = self.limit if self.limit is not None else self.dur
        ended = (proc is None or proc.poll() is not None
                 or (stop_at > 0 and self.pos >= stop_at))
        if ended:
            # ffplay -t exits itself at the cap, but the OS-native fallback
            # can't -- kill it so the preview really stops at the trim point.
            from ..core import audio as _audio
            _audio.stop_audio(proc)
            self._proc = None
            self.playing = False
            self.pos = 0.0  # reset so ▶ replays from the start
            self._set_play_btn(False)
            self._draw_playhead()
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
        self._disp_w = self.MAX_W  # frame-canvas draw size (aspect-fit)
        self._disp_h = self.MAX_H
        self._tick_job = None     # after() id for the playback timer
        self._scrub_job = None    # debounce: decode a frame while scrubbing
        self._hint = ""           # message shown when nothing is loaded

        self.frame = ttk.Frame(parent)
        ttk.Label(self.frame, text=title, font=(_SANS_FONT, 9)).pack(
            pady=(2, 1))
        self.canvas = tk.Canvas(
            self.frame, width=self.MAX_W, height=self.MAX_H,
            highlightthickness=1, bd=0, background="#000000")
        self.canvas.pack(pady=(0, 2))
        self.canvas.bind("<Configure>", self._on_canvas_resize, add="+")
        # Seek bar: click or drag to seek; the playhead tracks playback.
        self.seek_canvas = tk.Canvas(
            self.frame, height=16, highlightthickness=1, bd=0, cursor="hand2")
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
        self.path = path
        info = _video.detect_video_info(path)
        self.info = info
        dur = (info.duration if info and info.duration > 0
               else _video.probe_video_duration(path))
        self.dur = dur or 0.0
        self.pos = 0.0
        self._compute_disp_size(info)
        # Poster a representative frame, not the frame at 0.0 -- many clips
        # open on a black leader frame, which looked like a broken/empty
        # preview.  Grab mid-clip when the duration is known, else a small
        # offset in.  The playhead stays at 0.0; this only changes the still.
        poster_pos = self.dur * 0.5 if self.dur > 0.2 else 0.5
        self._render_poster(poster_pos)
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

    def _render_poster(self, pos):
        """Decode a single frame at *pos* on a worker thread, then show it.
        Stale renders (clip/seek changed) are dropped via a counter."""
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
            self._win._tk_root().after(0, self._show_poster, png, rid)

        threading.Thread(target=_work, daemon=True).start()

    def _show_poster(self, png, rid):
        if self._render_id != rid:
            return
        canvas = self.canvas
        canvas.delete("all")
        cw = canvas.winfo_width() or self.MAX_W
        ch = canvas.winfo_height() or self.MAX_H
        if png and _HAVE_PIL:
            try:
                import io
                img = Image.open(io.BytesIO(png)).convert("RGB")
                self._frame_img = ImageTk.PhotoImage(img)
                canvas.create_image(cw // 2, ch // 2, anchor=tk.CENTER,
                                    image=self._frame_img, tags=("frame",))
            except Exception:
                self._frame_img = None
        else:
            canvas.create_text(cw // 2, ch // 2, fill="#888888",
                               text="(preview needs ffmpeg)")
        self._draw_playhead()

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
            canvas.create_image(cw // 2, ch // 2, anchor=tk.CENTER,
                                image=self._frame_img, tags=("frame",))
        except Exception:
            pass

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
        self.stop_playback()
        self.pos = 0.0
        self._draw_playhead()
        if self.path:
            self._render_poster(0.0)

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
                self._render_poster(0.0)
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
                 initial_fda_acknowledged=False,
                 on_fda_acknowledge=None,
                 initial_column_widths=None,
                 on_column_widths_change=None,
                 initial_admin_warning_collapsed=False,
                 on_admin_warning_collapsed_change=None,
                 initial_voice_quality=None,
                 on_voice_quality_change=None):
        self.root = root
        self._manufacturers = manufacturers   # list[Manufacturer]
        self._on_manufacturer_change = on_manufacturer_change
        self._on_extract = on_extract
        self._on_extract_cancel = on_extract_cancel
        self._on_write = on_write
        self._on_write_cancel = on_write_cancel
        self._on_apply_delta = on_apply_delta
        self._on_revert_all = on_revert_all
        self._on_flash_image = on_flash_image
        self._on_recheck_prereqs = on_recheck_prereqs
        self._on_install_prereqs = on_install_prereqs
        self._on_back = on_back
        self._on_export = on_export
        self._on_import = on_import
        self._on_transfer_mods = on_transfer_mods
        self._on_theme_change = on_theme_change
        self._on_check_updates = on_check_updates
        # Per-tree column widths the user dragged, persisted across restarts via
        # ``on_column_widths_change`` (settings.json).  ``{tree_key: {col: px}}``.
        self._saved_column_widths = dict(initial_column_widths or {})
        self._on_column_widths_change = on_column_widths_change
        # Recent paths per field (``{field_key: [paths, most recent first]}``)
        # backing the path boxes' dropdown history (monkeybug: "any text box
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
        # settings.json via ``on_voice_quality_change`` (monkeybug: "dial in
        # better voice recognition at the expense of processing time").
        vq = initial_voice_quality
        if vq not in {v for v, _ in VOICE_QUALITY_CHOICES}:
            vq = VOICE_QUALITY_CHOICES[0][0]
        self.voice_quality_var = tk.StringVar(value=vq)
        self._on_voice_quality_change = on_voice_quality_change
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
        self.write_output_var = tk.StringVar()
        # Replace-Audio tab state (capabilities.replace_audio plugins).
        # The tab scans the assets folder for .wav/.ogg slots and lets the
        # user assign a replacement track per slot; staging writes the
        # converted replacements over the originals so Write repacks them.
        self.audio_search_var = tk.StringVar()
        # Click-header sort state: (column_id, descending).  Defaults to the
        # name column ascending — matches the old "Name" dropdown default.
        self._audio_sort = ("#0", False)
        # Off by default: most users replacing *music* want their whole
        # track, not one clipped to the original slot's length.  Games that
        # require exact-length slots (JJP/Spooky) already trim/pad in their
        # own Write step regardless of this toggle.
        self.audio_trim_var = tk.BooleanVar(value=False)
        self.audio_status_var = tk.StringVar(value="")
        self._audio_slots = []           # list[AudioSlot] from last scan
        self._audio_slots_by_rel = {}    # rel_path -> AudioSlot
        self._audio_assignments = {}     # rel_path -> replacement file path
        self._audio_loop_flags = {}      # rel_path -> bool (BOF loop-inject)
        self._audio_keep_full_flags = {}  # rel_path -> bool (JJP keep-full-len)
        self._audio_loop_tip = None      # Loop/keep-column hover tooltip Toplevel
        self._audio_scan_id = 0          # bump-counter to drop stale scans
        self._audio_scan_dir = ""        # folder the current slots came from
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
        # Preview players: Original + Replacement side-by-side panes
        # (_AudioPreviewPane), built with the tab; None for plugins without it.
        self._audio_pane_orig = None
        self._audio_pane_rep = None
        self._audio_select_job = None    # debounce: load preview on select
        self._audio_current_rel = None   # the slot loaded in the preview panes
        self.audio_search_var.trace_add(
            "write", lambda *a: self._refresh_audio_list())
        # Replace-Video tab state (capabilities.replace_video plugins).
        # Mirrors the audio tab, but the preview is an embedded player: a
        # decode thread streams raw frames from ffmpeg to a canvas while
        # ffplay carries the sound, both seeked together.
        self.video_search_var = tk.StringVar()
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
        # Replace-Image tab state (capabilities.replace_image plugins).
        # Mirrors the video tab, but the preview is a single static thumbnail
        # on a canvas — no embedded player / threads / ffmpeg / seek bar.
        self.image_search_var = tk.StringVar()
        self._image_sort = ("#0", False)  # (column_id, descending)
        self.image_status_var = tk.StringVar(value="")
        # List-view toggles: show only assigned/changed slots, and group the
        # rows under their scene/animation container (Stern manifests; every
        # uncovered slot falls back to its parent folder).  Persisted per
        # assets folder with the other Replace toggles (see
        # _save_staged_changes / _populate_image_after_scan).
        self.image_changed_only_var = tk.BooleanVar(value=False)
        self.image_group_by_scene_var = tk.BooleanVar(value=False)
        self._image_slots = []           # list[ImageSlot] from last scan
        self._image_slots_by_rel = {}    # rel_path -> ImageSlot
        self._image_assignments = {}     # rel_path -> replacement file path
        # Manifest-derived grouping from the last scan (see
        # _scan_image_groups): rel_path -> (group_key, label_base, order).
        self._image_groups = {}
        self._image_group_occ = {}       # rel_path -> on-card occurrence count
        # User-authored display names for scene groups (group_key -> name,
        # <=50 chars) — the vendor's own element names are mostly
        # "unnamed_instance_N" (monkeybug).  Persisted in the staged-changes
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
        self.image_changed_only_var.trace_add(
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
        self._text_rows = []             # list[{path, original, replacement}]
        self._text_scan_dir = ""         # folder the rows were loaded from
        self._text_scan_id = 0           # bump-counter (parity w/ other tabs)
        self._text_current_iid = None    # selected row iid (str(index))
        self._text_sort = ("#0", False)  # (column_id, descending)
        self.text_search_var.trace_add(
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
        # up across firmware versions, where slot indexes shift (monkeybug).
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

        # Generic per-type Extract selection (capabilities.extract_categories):
        # one default-on checkbox per (key, label) the plugin advertises, built
        # dynamically in apply_manufacturer().  Stern uses Audio/Video/Images/
        # Text; app.py reads these and passes extract_categories={key: bool} to
        # the extract factory.  key -> BooleanVar.
        self._extract_category_vars = {}
        # Persisted Extract-tab options for the current manufacturer
        # (monkeybug: the auto-name checkboxes "do not stick between
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
        # as each tab is built so _set_tab_scanning() can disable + relabel them
        # while a (possibly slow, network-share) scan runs.
        self._scan_buttons = {}
        self._browse_buttons = {}

        # Intro/description labels whose wraplength tracks the window width so
        # they reflow wider instead of leaving dead space when the window grows
        # (each entry: (label, margin, minimum)).
        self._responsive_wrap_labels = []

        self._build_ui()
        self._init_phase_steps()
        self._apply_theme(self._current_theme)

        self.extract_input_var.trace_add("write", self._update_extract_badge)
        self.write_upd_var.trace_add("write", self._update_write_badge)
        # Default the Write Output Folder off the original image's location
        # the first time an original is picked (monkeybug: the box starting
        # blank forced an extra Browse; the -modified suffix already prevents
        # name clashes with the source).
        self.write_upd_var.trace_add(
            "write", lambda *_: self._maybe_default_write_output())
        self.write_upd_var.trace_add(
            "write", lambda *_: self._update_write_filename())
        self.write_output_var.trace_add(
            "write", lambda *_: self._update_write_filename())
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
        # header's ?/⚙ icon set (monkeybug): Segoe MDL2 "Home" on Windows
        # (same font/style as the gear — see the glyph comment below), text
        # "⌂" elsewhere.  The tooltip carries the words the icon dropped.
        home_glyph = "" if sys.platform == "win32" else "⌂"
        self._back_btn = ttk.Button(
            top, text=home_glyph, width=3, style="Icon.TButton",
            command=self._handle_back)
        _Tooltip(self._back_btn, "Back to game selection",
                 lambda: self._current_theme)
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
        # "⚙" settings menu — the one always-visible header control (monkeybug:
        # the old Check-for-updates / Manage-disk-space / theme button row was
        # permanent top-bar clutter for things you touch once in a while).
        # Everything app-wide lives in its dropdown: theme, update check, disk
        # space, voice-recognition quality, prerequisites.
        # Glyphs: on Windows BOTH header icons ("?" tips + gear) come from
        # Segoe MDL2 Assets — the OS's own Settings gear (U+2699 in Segoe UI
        # renders as the flowery emoji gear) and its matching Help "?" — one
        # font + one style so the two buttons are pixel-identical in size
        # (David).  Elsewhere: text glyphs, ⚙ forced to text presentation.
        if sys.platform == "win32":
            self._gear_glyph = ""          # MDL2 "Settings" gear
            self._gear_badge_glyph = ""    # MDL2 "Warning" triangle
            self._help_glyph = ""          # MDL2 "Help" question mark
        else:
            self._gear_glyph = "⚙︎"    # text-presentation ⚙
            self._gear_badge_glyph = "⚠"    # ⚠
            self._help_glyph = "?"
        self._gear_btn = ttk.Button(top, text=self._gear_glyph, width=3,
                                    style="Icon.TButton",
                                    command=self._open_settings_menu)
        self._gear_btn.pack(side=tk.RIGHT)
        _Tooltip(self._gear_btn, "Settings", lambda: self._current_theme)
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
        # "?" tips button — per-tab help window (monkeybug: collect the
        # scattered inline tips somewhere a user can pull up on demand).
        # Created here, but packed only in show_mfr_view(): the picker has
        # no tabs so the button would have nothing to explain there.
        self._help_btn = ttk.Button(top, text=self._help_glyph, width=3,
                                    style="Icon.TButton",
                                    command=self._open_tab_help)
        _Tooltip(self._help_btn, "Tips for this tab",
                 lambda: self._current_theme)
        # The single per-app tips window (monkeybug round 2: "?" used to
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
            # dead band on the right when widened (monkeybug).
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
            # shorter — that height goes to the log below (monkeybug's ask).
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

        self._notebook.add(self._tab_extract, text="  Extract  ")
        self._notebook.add(self._tab_audio, text="  Replace Audio  ")
        self._notebook.add(self._tab_video, text="  Replace Video  ")
        self._notebook.add(self._tab_image, text="  Replace Images  ")
        self._notebook.add(self._tab_text, text="  Replace Text  ")
        self._notebook.add(self._tab_write, text="  Write  ")
        self._notebook.add(self._tab_modpack, text="  Mod Pack  ")

        self._build_extract_tab()
        self._build_audio_tab()
        self._build_video_tab()
        self._build_image_tab()
        self._build_text_tab()
        self._build_write_tab()
        self._build_modpack_tab()

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
        ttk.Button(self._extract_input_row, text="Browse...",
                   command=self._browse_extract_input).pack(
            side=tk.LEFT, padx=(8, 0))
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

        # "Detected: <game>" badge.  Wrapped in a row with a field-label-width
        # spacer so its left edge lines up under the path entry fields (not the
        # labels) — see the path rows above, which all lead with a width=14
        # anchor=W label.  The ROW is the positioned element (the source toggle
        # in _on_input_source_change packs/forgets it); the badge stays inside.
        self._extract_badge_row = ttk.Frame(f)
        self._extract_badge_row.pack(fill=tk.X, padx=10, pady=(0, 2))
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
        ttk.Label(self._extract_output_row_ref,
                  text="Output Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._path_combo(self._extract_output_row_ref,
                         self.extract_output_var, "extract_output").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._extract_output_row_ref, text="Browse...",
                   command=self._browse_extract_output).pack(
            side=tk.LEFT, padx=(8, 0))

        # NOTE: a red "Output folder is not empty — files may be overwritten."
        # label used to live here, but the Extract click already raises a
        # confirm dialog for that case, so the always-on inline warning was
        # redundant noise eating a row of vertical space (monkeybug).

        # BOF-only callout — explains the custom-format conversion the
        # Extract pipeline does behind the scenes.  Built but not packed;
        # apply_manufacturer() packs it when the user picks BOF and
        # hides it otherwise.  Stands out from the surrounding controls
        # via a yellow background + amber border, matching the "tip"
        # callout convention used elsewhere in the app.
        self._extract_bof_banner = tk.Frame(
            f, bg="#3a3416", padx=12, pady=10,
            highlightbackground="#a08020", highlightthickness=1)
        tk.Label(
            self._extract_bof_banner, bg="#3a3416", fg="#ffd966",
            font=(_SANS_FONT, 10, "bold"),
            anchor=tk.W, justify=tk.LEFT,
            text="About BOF Extract",
        ).pack(anchor=tk.W)
        tk.Label(
            self._extract_bof_banner, bg="#3a3416", fg="#e8d8a0",
            font=(_SANS_FONT, 9), anchor=tk.W, justify=tk.LEFT,
            wraplength=720,
            text=(
                "Starting with the April 2026 firmware (Winchester 4/29, "
                "Dune 5/13), BOF ships its games in a custom Godot PCK "
                "format that no public extractor — including GDRE Tools — "
                "can read. Older .fun files use stock Godot and work with "
                "GDRE; this newer format needs the Pinball Asset Decryptor."
            ),
        ).pack(anchor=tk.W, pady=(4, 6))
        tk.Label(
            self._extract_bof_banner, bg="#3a3416", fg="#e8d8a0",
            font=(_SANS_FONT, 9), anchor=tk.W, justify=tk.LEFT,
            wraplength=720,
            text=(
                "During Extract, the app will:\n"
                "   • Decrypt the .fun and pull out the Godot binary\n"
                "   • Patch BOF's custom PCK magic markers back to stock Godot\n"
                "   • Walk BOF's sequential file layout (no traditional directory)\n"
                "   • Decompress fonts from BOF's Zstd \"RSCC\" container\n"
                "   • Decode QOA-compressed audio → standard WAV\n"
                "   • Unwrap textures (GST2 + WebP) → standard WEBP\n"
                "   • Save everything to pck/_EDITABLE ASSETS/, organised "
                "into audio/, images/, video/, and fonts/ subfolders"
            ),
        ).pack(anchor=tk.W, pady=(0, 6))
        tk.Label(
            self._extract_bof_banner, bg="#3a3416", fg="#a8e8a0",
            font=(_SANS_FONT, 9, "italic"), anchor=tk.W, justify=tk.LEFT,
            wraplength=720,
            text=(
                "After Extract, open _EDITABLE ASSETS/ — every audio file "
                "is playable in VLC / Audacity, every texture in any image "
                "viewer. Edit anything, then use the Write tab to repack "
                "your changes back into a new .fun for the machine."
            ),
        ).pack(anchor=tk.W)

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

        # The Extract action button and the inline option checkboxes share one
        # bottom row: the checkbox cluster sits on the left (aligned under the
        # path fields), the Extract button anchors right (under the Browse
        # column).  Created here — unpacked — so the option frames below can
        # parent into the left cluster; the row is packed at the very end of
        # this method (after every option frame exists).
        self._extract_action_row = ttk.Frame(f)
        self._extract_options_row = ttk.Frame(self._extract_action_row)

        # Second, separate "Options:" row for the auto-name / length-prefix
        # cluster (monkeybug: sharing one row with the category checkboxes
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
            self._extract_action_row, text="Extract", command=self._on_extract)
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

        # NOTE: a static per-manufacturer intro label (mfr.write_intro()) used
        # to lead this tab, but it doubled up with the mode-aware description
        # below the source toggle (_write_desc) — one paragraph of guidance on
        # the tab is enough; the rest lives in the "?" tips window (monkeybug).

        # Write-destination toggle (hidden for plugins without
        # direct_ssd).  Action-oriented language here — writes have
        # a destination, not a source, so "Build USB ISO" /
        # "Write to SSD" reads more naturally than "From ISO" /
        # "From SSD".  Mirrors the standalone JJP decryptor.
        self._write_source_frame = ttk.Frame(f)
        self._write_iso_radio = ttk.Radiobutton(
            self._write_source_frame, text="Build USB ISO",
            value="iso",
            variable=self.write_input_source_var,
            command=lambda: self._on_input_source_change("write"),
        )
        self._write_iso_radio.pack(side=tk.LEFT, padx=(10, 12))
        self._write_ssd_radio = ttk.Radiobutton(
            self._write_source_frame, text="Write to SSD",
            value="ssd",
            variable=self.write_input_source_var,
            command=lambda: self._on_input_source_change("write"),
        )
        self._write_ssd_radio.pack(side=tk.LEFT)

        # The Write tab's field-label column.  Everything created with
        # width=16 below registers here so apply_manufacturer can widen the
        # whole column in lockstep when a manufacturer noun overflows it
        # (Stern's "Original Card image:" truncated at 16 — monkeybug 5).
        self._write_col_labels = []

        # ISO original file row.
        self._write_upd_row = ttk.Frame(f)
        self._write_original_lbl = ttk.Label(
            self._write_upd_row, text="Original:", width=16, anchor=tk.W)
        self._write_original_lbl.pack(side=tk.LEFT)
        self._write_col_labels.append(self._write_original_lbl)
        self._path_combo(self._write_upd_row,
                         self.write_upd_var, "write_original").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._write_upd_row, text="Browse...",
                   command=self._browse_write_upd).pack(
            side=tk.LEFT, padx=(8, 0))
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

        # Per-mode description that swaps text when the radio flips.
        # In ISO mode it explains the USB-install flow; in SSD mode
        # it spells out the in-place encrypt + audio trim/pad
        # behaviour the JJP standalone called out specifically.  This
        # is the kind of cue users read before clicking the button.
        self._write_desc = ttk.Label(
            f,
            text="Re-pack modified assets into an installable update file.",
            foreground="#888888",
            font=(_SANS_FONT, 9),
            wraplength=720, justify=tk.LEFT)

        # "Detected: …" badge — indented with a width-16 spacer so it lines
        # up with the entry fields (which follow width-16 labels), matching
        # the Extract tab (monkeybug 4.8) instead of the old fixed padx.
        self._write_badge_row = ttk.Frame(f)
        self._write_badge_row.pack(fill=tk.X, padx=10, pady=(0, 2))
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
                                text="Modified Assets:", width=16, anchor=tk.W)
        _assets_lbl.pack(side=tk.LEFT)
        self._write_col_labels.append(_assets_lbl)
        self._path_combo(self._write_assets_row_ref,
                         self.write_assets_var, "write_assets").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._write_assets_row_ref, text="Browse...",
                   command=self._browse_write_assets).pack(
            side=tk.LEFT, padx=(8, 0))

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
        _out_lbl = ttk.Label(self._write_output_row_ref,
                             text="Output Folder:", width=16, anchor=tk.W)
        _out_lbl.pack(side=tk.LEFT)
        self._write_col_labels.append(_out_lbl)
        self._path_combo(self._write_output_row_ref,
                         self.write_output_var, "write_output").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self._write_output_row_ref, text="Browse...",
                   command=self._browse_write_output).pack(
            side=tk.LEFT, padx=(8, 0))

        self._write_filename_lbl = ttk.Label(f, text="",
                                             font=(_SANS_FONT, 9, "italic"))
        self._write_filename_lbl.pack(anchor=tk.W, padx=26)

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

        # Toolbar across the top of the preview frame.  The Refresh button
        # re-scans when the user edits assets in another window (cheaper than
        # file-watching); monkeybug 4.3/4.5 also moved the primary Build +
        # Revert actions up here — right-aligned as Build ▸ Revert ▸ Refresh —
        # so every "act on these changes" control is grouped in one place
        # instead of a separate button row below the frame.
        preview_toolbar = ttk.Frame(self._write_preview_frame)
        preview_toolbar.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._write_preview_refresh_btn = ttk.Button(
            preview_toolbar, text="🔄  Refresh",
            command=self._scan_write_preview)
        self._write_preview_refresh_btn.pack(side=tk.RIGHT)
        # The single Build button doubles as a live Cancel while a build runs
        # (monkeybug 4.4 — no separate Cancel widget any more); its label and
        # command are driven by _set_write_button_running.
        self._write_btn = ttk.Button(
            preview_toolbar, text="Build update",
            command=self._on_write_clicked)
        self._write_btn.pack(side=tk.RIGHT, padx=(0, 6))
        # Revert is gated to plugins with a Replace surface in
        # apply_manufacturer, which re-packs it just left of Build.
        self._revert_all_btn = ttk.Button(
            preview_toolbar, text="Revert all changes…",
            command=self._revert_all_clicked)
        self._revert_all_btn.pack(
            side=tk.RIGHT, padx=(0, 6), before=self._write_btn)

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
        # separate imaging tool.  Distinct from Build/Write above: those modify
        # assets; this replaces the entire card.  Opens a small modal that
        # collects the image + target card and confirms before the write runs
        # through the normal status area.
        self._flash_frame = ttk.LabelFrame(f, text="Flash Image to SD Card")
        # Two rows: the buttons right-aligned on their own row, and the
        # description on a full-width row below.  An earlier single-row layout
        # (label left, button right) truncated the description once a second
        # button ("Card diagnostics…") was added — the two buttons ate the
        # width budget the paragraph needed, clipping it mid-sentence.  A
        # dedicated full-width description row can't be squeezed.
        btn_row = ttk.Frame(self._flash_frame)
        btn_row.pack(fill=tk.X, padx=8, pady=(4, 0))
        self._flash_btn = ttk.Button(
            btn_row, text="Flash image to SD card…",
            command=self._open_flash_dialog)
        self._flash_btn.pack(side=tk.RIGHT)
        # "Card diagnostics…" — only for manufacturers implementing
        # diagnose_card (CGC): reads the on-machine installer's log back off
        # a failed card (read-only).  Packed/hidden in apply_manufacturer().
        self._diagnose_btn = ttk.Button(
            btn_row, text="Card diagnostics…",
            command=self._open_diagnose_dialog)
        _flash_lbl = ttk.Label(
            self._flash_frame,
            text=("Write a complete, pre-built SD-card image (.img / .raw) "
                  "directly onto a card — handy after Build SD-card image, or "
                  "to restore a backup. The whole card is erased and replaced, "
                  "and the built-in size check refuses an image too big for the "
                  "card. Requires Administrator."),
            font=(_SANS_FONT, 9), justify=tk.LEFT, wraplength=760)
        _flash_lbl.pack(side=tk.TOP, fill=tk.X, expand=True, padx=8,
                        pady=(2, 6), anchor=tk.W)
        # Re-wrap to the width actually allocated so the full paragraph always
        # shows (taller when narrow) instead of clipping.
        _flash_lbl.bind(
            "<Configure>",
            lambda e, lbl=_flash_lbl: lbl.configure(
                wraplength=max(200, e.width - 4)))

    def _build_modpack_tab(self):
        f = self._tab_modpack
        pad = {"padx": 10, "pady": 6}

        ttk.Label(f,
                  text="Share or apply mod packs — zips containing only your "
                  "modified files.",
                  font=(_SANS_FONT, 9, "italic")).pack(anchor=tk.W, **pad)

        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(row, text="Mod Folder:", width=12, anchor=tk.W).pack(
            side=tk.LEFT)
        self._path_combo(row, self.write_assets_var, "write_assets").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse...",
                   command=self._browse_write_assets).pack(
            side=tk.LEFT, padx=(8, 0))
        ttk.Label(f, text="(shared with the Write tab's Modified Assets path)",
                  font=(_SANS_FONT, 8, "italic")).pack(anchor=tk.W, padx=24)

        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=8)

        export_frame = ttk.LabelFrame(f, text="Export Mod Pack")
        export_frame.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(export_frame,
                  text="Create a zip of only your modified files to share.",
                  font=(_SANS_FONT, 9)).pack(anchor=tk.W, padx=8, pady=(4, 2))
        ttk.Button(export_frame, text="Export Mod Pack...",
                   command=self._on_export).pack(
            anchor=tk.W, padx=8, pady=(2, 6))

        import_frame = ttk.LabelFrame(f, text="Import Mod Pack")
        import_frame.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(import_frame,
                  text="Apply a mod pack zip from another user.",
                  font=(_SANS_FONT, 9)).pack(anchor=tk.W, padx=8, pady=(4, 2))
        ttk.Button(import_frame, text="Import Mod Pack...",
                   command=self._on_import).pack(
            anchor=tk.W, padx=8, pady=(2, 6))

        # Gated per-plugin (caps.mod_transfer) in apply_manufacturer — this tab
        # is shared, but the feature (and its wording) only fits plugins whose
        # vendor re-lays-out the card across versions, e.g. Stern Spike 2.
        self._modpack_transfer_frame = ttk.LabelFrame(
            f, text="Transfer Mods to New Version")
        ttk.Label(
            self._modpack_transfer_frame,
            text="New game code shipped? Pull your mods from your old extract "
                 "onto a fresh extract of the new version, then build the new "
                 "version's card with your mods on it. Fill the two required "
                 "folders (and, if you have it, the optional one for a more "
                 "accurate transfer). Works even for code modded outside this "
                 "app.",
            font=(_SANS_FONT, 9), wraplength=560, justify=tk.LEFT).pack(
            anchor=tk.W, padx=8, pady=(4, 2))
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

        def _picker(row, label, var, browse, ver_var=None):
            ttk.Label(tf, text=label).grid(
                row=row, column=0, sticky=tk.W, pady=2)
            ttk.Entry(tf, textvariable=var).grid(
                row=row, column=1, sticky=tk.EW, padx=6, pady=2)
            ttk.Button(tf, text="Browse...", command=browse).grid(
                row=row, column=2, pady=2)
            if ver_var is not None:
                ttk.Label(tf, textvariable=ver_var, foreground="#4a90d9",
                          font=(_SANS_FONT, 8)).grid(
                    row=row, column=3, sticky=tk.W, padx=(6, 0))

        _picker(0, "1. Old extract (has your mods):",
                self.transfer_src_var, self._browse_transfer_src,
                self.transfer_src_ver_var)
        _picker(1, "2. New extract (stock, new version):",
                self.transfer_dst_var, self._browse_transfer_dst,
                self.transfer_dst_ver_var)
        _picker(2, "3. Stock extract of the OLD version (optional):",
                self.transfer_oldstock_var, self._browse_transfer_oldstock)
        ttk.Label(
            tf,
            text="     Leave empty to compare your old extract straight "
                 "against the new one (finds image + video mods). Provide a "
                 "clean, unmodified extract of the SAME old version to also "
                 "carry AUDIO and TEXT and to avoid mistaking the factory's "
                 "own between-version changes for your mods.",
            font=(_SANS_FONT, 8, "italic"), wraplength=560,
            justify=tk.LEFT).grid(row=3, column=0, columnspan=4,
                                  sticky=tk.W, pady=(0, 4))
        _picker(4, "4. New version card image (.raw) to build onto:",
                self.transfer_newimg_var, self._browse_transfer_newimg,
                self.transfer_img_ver_var)
        ttk.Label(tf, textvariable=self.transfer_output_var,
                  font=(_SANS_FONT, 8, "italic"), wraplength=560,
                  justify=tk.LEFT).grid(row=5, column=0, columnspan=4,
                                        sticky=tk.W, pady=(0, 2))

        ttk.Button(self._modpack_transfer_frame,
                   text="Transfer mods → new version...",
                   command=(self._on_transfer_mods
                            if self._on_transfer_mods else lambda: None)).pack(
            anchor=tk.W, padx=8, pady=(2, 2))
        # Filled after a successful transfer with the exact next step (also
        # written to the log, so it survives once this panel scrolls away).
        ttk.Label(self._modpack_transfer_frame,
                  textvariable=self.transfer_next_var, foreground="#3aa76d",
                  font=(_SANS_FONT, 9, "bold"), wraplength=560,
                  justify=tk.LEFT).pack(anchor=tk.W, padx=8, pady=(0, 6))

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
        # (monkeybug: the multi-line paragraphs crowded every tab).
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
        ttk.Label(row, text="Assets Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._path_combo(row, self.write_assets_var, "write_assets").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._make_assets_scan_buttons(row, "audio",
                                       self._scan_audio_slots_async)
        ttk.Label(f, text="(the folder Extract produced — shared with the "
                          "Write tab)",
                  font=(_SANS_FONT, 8, "italic")).pack(anchor=tk.W, padx=24)

        # Search + sort toolbar.
        tools = ttk.Frame(f); tools.pack(fill=tk.X, padx=10, pady=(8, 2))
        ttk.Label(tools, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(tools, textvariable=self.audio_search_var, width=24).pack(
            side=tk.LEFT, padx=(4, 12))
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
        self._audio_sort_hint_lbl = ttk.Label(
            tools, text="(click a column header to sort)",
            font=(_SANS_FONT, 8, "italic"))
        self._audio_sort_hint_lbl.pack(side=tk.LEFT)
        self._audio_status_lbl = ttk.Label(
            tools, textvariable=self.audio_status_var,
            font=(_SANS_FONT, 9))
        self._audio_status_lbl.pack(side=tk.RIGHT)

        # Slot list.
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 4))
        # "loop" and "keep" are optional toggle columns shown per capability
        # (apply_manufacturer sets displaycolumns) — "loop" for
        # audio_loop_inject (BOF), "keep" for audio_keep_length_override (JJP).
        # They never show together (different plugins).  displaycolumns places
        # whichever is active just BEFORE "rep" so the narrow toggle is never
        # the rightmost (clippable) column; the values tuple still follows this
        # `columns` order (vals[3]=loop, vals[4]=keep) regardless of display
        # order.
        self._audio_tree = ttk.Treeview(
            list_frame, columns=("len", "fmt", "rep", "loop", "keep"),
            height=12, selectmode="browse")
        self._audio_tree.heading("#0", text="Original Track", anchor=tk.W)
        self._audio_tree.heading("len", text="Length", anchor=tk.W)
        self._audio_tree.heading("fmt", text="Format", anchor=tk.W)
        self._audio_tree.heading("rep", text="Replacement", anchor=tk.W)
        self._audio_tree.heading("loop", text="Loop", anchor=tk.CENTER)
        self._audio_tree.heading("keep", text="Full", anchor=tk.CENTER)
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
        self._persist_tree_columns(
            self._audio_tree, "audio",
            ("#0", "len", "fmt", "rep", "loop", "keep"))
        # Click-header sort: (col_id, base heading text, default-descending).
        # Numeric columns default to descending (longest/looped first) the way
        # the old "Longest first" option did; text columns ascending.
        self._audio_sort_cfg = [
            ("#0", "Original Track", False), ("len", "Length", True),
            ("fmt", "Format", False), ("rep", "Replacement", False),
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
        # Hover over the Loop column → tooltip explaining the feature.
        self._audio_tree.bind("<Motion>", self._audio_on_tree_motion, add="+")
        self._audio_tree.bind(
            "<Leave>", lambda _e: self._hide_audio_loop_tip(), add="+")

        self._audio_empty = ttk.Label(
            list_frame,
            text="Pick your extracted assets folder above, then click Scan.",
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
        self._audio_pane_orig.frame.grid(row=0, column=0, sticky="ew",
                                         padx=(0, 4))
        self._audio_pane_rep.frame.grid(row=0, column=1, sticky="ew",
                                        padx=(4, 0))
        self._audio_pane_rep.clear("no replacement assigned")

        # Length-matching option + per-manufacturer guidance note.  The
        # checkbox is forced on + disabled for plugins whose Write always
        # length-matches regardless (audio_forces_length_match), set in
        # apply_manufacturer.
        self._audio_trim_cb = ttk.Checkbutton(
            f, text="Trim / pad replacements to the original slot length",
            variable=self.audio_trim_var, command=self._save_staged_changes)
        self._audio_trim_cb.pack(anchor=tk.W, padx=12, pady=(6, 0))
        # Hover tooltip — its text is set per-manufacturer in apply_manufacturer
        # (esp. WHY it's disabled for size-neutral formats like Spike 2).
        self._audio_trim_tip = _Tooltip(
            self._audio_trim_cb, "", lambda: self._current_theme)
        self._audio_length_note_lbl = ttk.Label(
            f, text="", font=(_SANS_FONT, 8, "italic"),
            foreground="#888888", wraplength=720, justify=tk.LEFT)
        self._audio_length_note_lbl.pack(anchor=tk.W, padx=30, pady=(0, 2))

        # No explicit "stage" step: the replacements you assign are applied
        # (converted + written into the assets folder) automatically when you
        # build the update on the Write tab.
        ttk.Label(
            f,
            text="Assigned replacements are applied automatically when you "
                 "build the update on the Write tab — no extra step.",
            font=(_SANS_FONT, 9), foreground="#888888",
            wraplength=720, justify=tk.LEFT).pack(
            anchor=tk.W, padx=12, pady=(8, 8))

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
            self._refresh_audio_list()
            self._audio_empty.configure(
                text="Pick your extracted assets folder above, then click Scan.")
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
            if self._audio_scan_id != scan_id:
                return
            self._tk_root().after(
                0, self._populate_audio_after_scan,
                slots, scan_id, assets_path)

        self._set_tab_scanning("audio", True)
        threading.Thread(target=_work, daemon=True).start()

    def _populate_audio_after_scan(self, slots, scan_id, scan_dir):
        """Main-thread: store scan results and refresh the list."""
        if self._audio_scan_id != scan_id:
            return
        self._set_tab_scanning("audio", False)
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
            saved_loops = staged.get("audio_loop") or {}
            saved_keep = staged.get("audio_keep") or {}
            persisted_trim = bool(staged.get("audio_trim", False))
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

    # ---- Replace tabs: click-header sorting (shared) -----------------

    @staticmethod
    def _double_click_on_rows(tree, event):
        """True if a <Double-1> landed on a data row (region "tree"/"cell").

        Clicking a sortable column header fast enough registers as a
        double-click too; without this guard it falls through to the row
        action — the image tab popped "No Slot Selected" mid-sort
        (monkeybug).  A None event (programmatic call) is allowed through."""
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

    def _refresh_audio_list(self):
        """Apply the search filter + sort and repopulate the slot tree — flat,
        or two-level when "Group duplicates" is on and the bank duplicate scan
        has run for this folder: one collapsed parent per group of
        byte-identical factory audio (longest first, the dup scan's order),
        its member slots nested, every unique slot flat below the groups."""
        tree = getattr(self, "_audio_tree", None)
        if tree is None:
            return
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
        slots = [s for s in self._audio_slots
                 if not query or query in s.rel_path.lower()]
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
            tree.insert(parent, tk.END, iid=s.rel_path, text=s.rel_path,
                        values=(s.duration_str(), s.format_summary(),
                                rep_disp, loop_disp, keep_disp),
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
                visible = [m for m in members
                           if not query or query in m.rel_path.lower()]
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
                            "", ""))
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
        path = filedialog.askopenfilename(
            title=f"Choose a replacement for {rel}",
            filetypes=[("Audio files",
                        "*.wav *.ogg *.mp3 *.flac *.m4a *.aac *.opus "
                        "*.wma *.aiff *.aif"),
                       ("All files", "*.*")])
        if not path:
            return
        self._audio_assignments[rel] = path
        self._save_staged_changes()
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
        if ((self._audio_pane_orig and self._audio_pane_orig.playing)
                or (self._audio_pane_rep and self._audio_pane_rep.playing)):
            return  # don't yank a track that's currently playing
        rel = self._audio_selected_rel()
        if rel is None or rel == self._audio_current_rel:
            return
        self._audio_load_track(rel)  # shows both seek bars, no play

    def _audio_on_tree_double(self, _event=None):
        if not self._double_click_on_rows(self._audio_tree, _event):
            return
        self._cancel_audio_select_job()
        self._audio_play_original()

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
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _audio_clear_selected(self):
        rel = self._audio_selected_rel()
        if rel is not None and rel in self._audio_assignments:
            del self._audio_assignments[rel]
            self._save_staged_changes()
            self._refresh_audio_list()
            if rel == self._audio_current_rel:
                self._audio_load_rep_pane(rel)  # back to "no replacement"
            try:
                self._audio_tree.selection_set(rel)
            except tk.TclError:
                pass

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

    def _audio_load_track(self, rel, autoplay=None):
        """Load *rel* into both preview panes — its original on the left, its
        assigned replacement (if any) on the right.  *autoplay* names the
        pane to start ("orig"/"rep"), or None to just show the seek strips."""
        if rel not in self._audio_slots_by_rel:
            return
        from ..core import audio as _audio
        self._audio_current_rel = rel
        slot = self._audio_slots_by_rel.get(rel)
        opath = slot.abs_path if slot else None
        if opath and os.path.isfile(opath):
            self._audio_pane_orig.load(
                opath, _audio.probe_duration(opath) or 0.0, None,
                autoplay=(autoplay == "orig"))
        else:
            self._audio_pane_orig.clear()
        self._audio_load_rep_pane(rel, autoplay=(autoplay == "rep"))

    def _audio_load_rep_pane(self, rel, autoplay=False):
        """(Re)load the Replacement pane for *rel* — after a track change or
        an assign/clear/revert of the currently-loaded slot."""
        from ..core import audio as _audio
        rpath = self._audio_assignments.get(rel) if rel else None
        if rpath and os.path.isfile(rpath):
            rdur = _audio.probe_duration(rpath) or 0.0
            self._audio_pane_rep.load(
                rpath, rdur, self._audio_compute_preview_limit(rel, rdur),
                autoplay=autoplay)
        else:
            self._audio_pane_rep.clear("no replacement assigned")

    def _audio_activate_pane(self, side):
        """▶ pressed on an empty pane: load the selected row, then play the
        pane that asked."""
        rel = self._audio_selected_rel()
        if rel is not None:
            self._audio_load_track(rel, autoplay=side)

    def _draw_audio_icon(self, canvas, kind):
        """Draw a crisp, borderless transport icon (play triangle / pause two
        bars / stop square) filled with the theme foreground — one visual
        family, identical sizing."""
        canvas.delete("all")
        c = THEMES.get(self._current_theme, {})
        fg = c.get("fg", "#dddddd")
        try:
            s = int(canvas.cget("width"))
        except (tk.TclError, ValueError):
            s = 26
        m = s * 0.27  # margin so all three icons share the same bounding box
        if kind == "play":
            canvas.create_polygon(m, m, m, s - m, s - m, s / 2.0,
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

    def _audio_stop_playback(self):
        """Stop both preview panes (keeps their playheads where they landed)."""
        for pane in (self._audio_pane_orig, self._audio_pane_rep):
            if pane is not None:
                pane.stop_playback()

    def _audio_clear_preview(self):
        """Reset both preview panes entirely (used on manufacturer switch)."""
        self._cancel_audio_select_job()
        self._audio_current_rel = None
        if self._audio_pane_orig is not None:
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
        ttk.Label(row, text="Assets Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._path_combo(row, self.write_assets_var, "write_assets").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._make_assets_scan_buttons(row, "video",
                                       self._scan_video_slots_async)
        ttk.Label(f, text="(the folder Extract produced — shared with the "
                          "Write tab)",
                  font=(_SANS_FONT, 8, "italic")).pack(anchor=tk.W, padx=24)

        # Search + sort toolbar.
        tools = ttk.Frame(f); tools.pack(fill=tk.X, padx=10, pady=(8, 2))
        ttk.Label(tools, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(tools, textvariable=self.video_search_var, width=24).pack(
            side=tk.LEFT, padx=(4, 12))
        ttk.Label(tools, text="(click a column header to sort)",
                  font=(_SANS_FONT, 8, "italic")).pack(side=tk.LEFT)
        self._video_status_lbl = ttk.Label(
            tools, textvariable=self.video_status_var,
            font=(_SANS_FONT, 9))
        self._video_status_lbl.pack(side=tk.RIGHT)

        # Slot list.
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 4))
        self._video_tree = ttk.Treeview(
            list_frame, columns=("len", "res", "fmt", "rep"),
            height=9, selectmode="browse")
        self._video_tree.heading("#0", text="Original Video", anchor=tk.W)
        self._video_tree.heading("len", text="Length", anchor=tk.W)
        self._video_tree.heading("res", text="Resolution", anchor=tk.W)
        self._video_tree.heading("fmt", text="Format", anchor=tk.W)
        self._video_tree.heading("rep", text="Replacement", anchor=tk.W)
        self._video_tree.column("#0", width=300, minwidth=160)
        self._video_tree.column("len", width=56, minwidth=46, anchor=tk.W)
        self._video_tree.column("res", width=90, minwidth=70, anchor=tk.W)
        self._video_tree.column("fmt", width=140, minwidth=80)
        self._video_tree.column("rep", width=200, minwidth=110)
        self._persist_tree_columns(
            self._video_tree, "video", ("#0", "len", "res", "fmt", "rep"))
        self._video_sort_cfg = [
            ("#0", "Original Video", False), ("len", "Length", True),
            ("res", "Resolution", True), ("fmt", "Format", False),
            ("rep", "Replacement", False)]
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
            text="Pick your extracted assets folder above, then click Scan.",
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

        self._video_no_conversion_cb = ttk.Checkbutton(
            f, text="No conversion — use my file as-is (it must already match "
                    "the original's format)",
            variable=self.video_no_conversion_var,
            command=self._video_on_no_conversion_toggle)
        self._video_no_conversion_cb.pack(anchor=tk.W, padx=12, pady=(6, 0))
        _Tooltip(
            self._video_no_conversion_cb,
            "Skip re-encoding: the replacement is copied in byte-for-byte, so "
            "it must already be the original clip's container, codec, "
            "resolution and frame rate (a different container is rejected). "
            "Faster and lossless, but the file has to be game-ready. Leave this "
            "off to have the app auto-convert any video to match the slot.",
            lambda: self._current_theme)

        self._video_trim_cb = ttk.Checkbutton(
            f, text="Trim / pad replacements to the original clip length",
            variable=self.video_trim_var,
            command=self._save_staged_changes)
        self._video_trim_cb.pack(anchor=tk.W, padx=12, pady=(6, 0))
        self._video_length_note_lbl = ttk.Label(
            f, text="", font=(_SANS_FONT, 8, "italic"),
            foreground="#888888", wraplength=720, justify=tk.LEFT)
        self._video_length_note_lbl.pack(anchor=tk.W, padx=30, pady=(0, 2))
        # Trim/pad only applies during a re-encode, so grey it out when
        # "No conversion" is on (reflects any restored staged state too).
        self._update_video_trim_enabled()

        ttk.Label(
            f,
            text="Assigned replacements are applied automatically when you "
                 "build the update on the Write tab — no extra step.",
            font=(_SANS_FONT, 9), foreground="#888888",
            wraplength=720, justify=tk.LEFT).pack(
            anchor=tk.W, padx=12, pady=(8, 8))

        self._refresh_video_ffmpeg_warning()

    def _video_on_no_conversion_toggle(self):
        """No-conversion copies the file through verbatim, so trim/pad (a
        re-encode-time option) doesn't apply — grey it out while it's on, then
        persist the choice with the other staged settings."""
        self._update_video_trim_enabled()
        self._save_staged_changes()

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
                text="Pick your extracted assets folder above, then click Scan.")
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
            if "video_trim" in staged:
                self.video_trim_var.set(bool(staged["video_trim"]))
            if "video_no_conversion" in staged:
                self.video_no_conversion_var.set(
                    bool(staged["video_no_conversion"]))
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
        tree = getattr(self, "_video_tree", None)
        if tree is None or not tree.exists(rel):
            return
        rep = self._video_assignments.get(rel)
        rep_disp = os.path.basename(rep) if rep else "Choose…"
        tree.item(rel, values=(slot.duration_str(), slot.resolution_str(),
                               slot.format_summary(), rep_disp))

    def _refresh_video_list(self):
        """Apply the search filter + sort and repopulate the slot tree."""
        tree = getattr(self, "_video_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())

        query = (self.video_search_var.get() or "").strip().lower()
        slots = [s for s in self._video_slots
                 if not query or query in s.rel_path.lower()]
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
            if col == "rep":
                rep = self._video_assignments.get(s.rel_path)
                if rep:
                    return (0, os.path.basename(rep).lower())
                return (1, "") if s.rel_path in changed else (2, "")
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
                length, res = "…", "…"  # metadata still loading
            else:
                length, res = s.duration_str(), s.resolution_str()
            tree.insert("", tk.END, iid=s.rel_path, text=s.rel_path,
                        values=(length, res, s.format_summary(), rep_disp),
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
            tree, "video", ("#0", "len", "res", "fmt", "rep"))

    def _default_assets_from_extract(self):
        """Default the (shared) assets folder to the Extract tab's output when
        it's still empty — the common case is extract then immediately swap
        audio/video, so they shouldn't have to re-pick the same folder."""
        if (self.write_assets_var.get() or "").strip():
            return
        out = (self.extract_output_var.get() or "").strip()
        if out and os.path.isdir(out):
            self.write_assets_var.set(out)

    def invalidate_asset_scans(self):
        """Force the Replace tabs to re-scan on their next visit, even when the
        assets-folder path is unchanged.  The per-tab auto-scan is keyed on the
        folder path (``assets_path != self._*_scan_dir``), so a fresh extract
        that repopulates a folder the tab already scanned would otherwise show
        stale (often empty) results until the user manually re-browses.  Clearing
        the stamps makes the next ``_maybe_rescan_*`` behave like a Browse."""
        self._audio_scan_dir = ""
        self._video_scan_dir = ""
        self._image_scan_dir = ""
        self._text_scan_dir = ""

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
        self.invalidate_asset_scans()
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
        (monkeybug's request — it tells the user it isn't relevant).  When the
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
                self._scan_write_preview()
            except tk.TclError:
                pass
        # The Replace Text tab reads straight from the manifest; reload it.
        if getattr(self, "_text_scan_dir", ""):
            self._text_scan_dir = ""

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
                subprocess.Popen(["xdg-open", folder])
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
        path = filedialog.askopenfilename(
            title=f"Choose a replacement for {rel}",
            filetypes=[("Video files",
                        "*.mp4 *.mov *.m4v *.webm *.ogv *.avi *.mkv *.mpg "
                        "*.mpeg *.wmv *.flv *.ts *.3gp *.gif"),
                       ("All files", "*.*")])
        if not path:
            return
        self._video_assignments[rel] = path
        self._save_staged_changes()
        self._refresh_video_list()
        if rel == self._video_current_rel:
            self._video_load_rep_pane(rel)  # show the new pick right away
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
        if ((self._video_pane_orig and self._video_pane_orig.playing)
                or (self._video_pane_rep and self._video_pane_rep.playing)):
            return  # don't yank a clip that's currently playing
        rel = self._video_selected_rel()
        if rel is None or rel == self._video_current_rel:
            return
        self._video_load_track(rel)  # posters both panes, no play

    def _video_on_tree_double(self, _event=None):
        if not self._double_click_on_rows(self._video_tree, _event):
            return
        self._cancel_video_select_job()
        self._video_play_original()

    def _video_on_tree_click(self, event):
        tree = self._video_tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        row = tree.identify_row(event.y)
        col = tree.identify_column(event.x)  # cols=(len,res,fmt,rep) -> #1..#4
        if row and col == "#4":
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
        slot = self._video_slots_by_rel.get(row)
        if slot is not None:
            menu.add_separator()
            menu.add_command(
                label=self._reveal_menu_label(),
                command=lambda p=slot.abs_path: self._reveal_in_file_manager(p))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _video_clear_selected(self):
        rel = self._video_selected_rel()
        if rel is not None and rel in self._video_assignments:
            del self._video_assignments[rel]
            self._save_staged_changes()
            self._refresh_video_list()
            if rel == self._video_current_rel:
                self._video_load_rep_pane(rel)  # back to "no replacement"
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
        self._video_current_rel = rel
        slot = self._video_slots_by_rel.get(rel)
        opath = slot.abs_path if slot else None
        if opath and os.path.isfile(opath):
            self._video_pane_orig.load(opath, autoplay=(autoplay == "orig"))
        else:
            self._video_pane_orig.clear()
        self._video_load_rep_pane(rel, autoplay=(autoplay == "rep"))

    def _video_load_rep_pane(self, rel, autoplay=False):
        """(Re)load the Replacement pane for *rel* — after a clip change or
        an assign/clear of the currently-loaded slot."""
        rpath = self._video_assignments.get(rel) if rel else None
        if rpath and os.path.isfile(rpath):
            self._video_pane_rep.load(rpath, autoplay=autoplay)
        else:
            self._video_pane_rep.clear("no replacement assigned")

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

    def _video_clear_preview(self):
        """Reset both preview panes entirely (used on manufacturer switch)."""
        self._cancel_video_select_job()
        self._video_current_rel = None
        if self._video_pane_orig is not None:
            self._video_pane_orig.clear()
        if self._video_pane_rep is not None:
            self._video_pane_rep.clear("no replacement assigned")

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
        ttk.Label(row, text="Assets Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._path_combo(row, self.write_assets_var, "write_assets").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._make_assets_scan_buttons(row, "image",
                                       self._scan_image_slots_async)
        ttk.Label(f, text="(the folder Extract produced — shared with the "
                          "Write tab)",
                  font=(_SANS_FONT, 8, "italic")).pack(anchor=tk.W, padx=24)

        # Search + sort toolbar.
        tools = ttk.Frame(f); tools.pack(fill=tk.X, padx=10, pady=(8, 2))
        ttk.Label(tools, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(tools, textvariable=self.image_search_var, width=24).pack(
            side=tk.LEFT, padx=(4, 12))
        # Source filter (monkeybug): narrow the list to one of the image
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
        self._image_changed_only_cb = ttk.Checkbutton(
            tools, text="Changed only",
            variable=self.image_changed_only_var,
            command=self._save_staged_changes)
        self._image_changed_only_cb.pack(side=tk.LEFT, padx=(0, 8))
        _Tooltip(
            self._image_changed_only_cb,
            "Show only the images with a pending replacement or already "
            "changed on disk by a previous build.",
            lambda: self._current_theme)
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
        ttk.Label(tools, text="(click a column header to sort)",
                  font=(_SANS_FONT, 8, "italic")).pack(side=tk.LEFT)
        self._image_status_lbl = ttk.Label(
            tools, textvariable=self.image_status_var,
            font=(_SANS_FONT, 9))
        self._image_status_lbl.pack(side=tk.RIGHT)

        # Slot list.
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 4))
        # "src" tells the three image stores apart (monkeybug: file-system
        # PNGs, scene textures and radium-embedded images were indistinguishable
        # beyond their paths) — see _image_source_label.
        self._image_tree = ttk.Treeview(
            list_frame, columns=("res", "fmt", "src", "rep"),
            height=9, selectmode="browse")
        self._image_tree.heading("#0", text="Original Image", anchor=tk.W)
        self._image_tree.heading("res", text="Resolution", anchor=tk.W)
        self._image_tree.heading("fmt", text="Format", anchor=tk.W)
        self._image_tree.heading("src", text="Source", anchor=tk.W)
        self._image_tree.heading("rep", text="Replacement", anchor=tk.W)
        self._image_tree.column("#0", width=300, minwidth=160)
        self._image_tree.column("res", width=90, minwidth=70, anchor=tk.W)
        self._image_tree.column("fmt", width=140, minwidth=80)
        self._image_tree.column("src", width=100, minwidth=70, anchor=tk.W,
                                stretch=False)
        self._image_tree.column("rep", width=200, minwidth=110)
        self._persist_tree_columns(
            self._image_tree, "image", ("#0", "res", "fmt", "src", "rep"))
        self._image_sort_cfg = [
            ("#0", "Original Image", False), ("res", "Resolution", True),
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
            text="Pick your extracted assets folder above, then click Scan.",
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
        ttk.Label(panes, text="Original", font=(_SANS_FONT, 9)).grid(
            row=0, column=0, pady=(2, 1))
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

        ttk.Label(
            f,
            text="Assigned replacements are applied automatically when you "
                 "build the update on the Write tab — no extra step.",
            font=(_SANS_FONT, 9), foreground="#888888",
            wraplength=720, justify=tk.LEFT).pack(
            anchor=tk.W, padx=12, pady=(8, 8))

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
            self._refresh_image_list()
            self._image_empty.configure(
                text="Pick your extracted assets folder above, then click Scan.")
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
                groups, group_occ = self._scan_image_groups(assets_path)
            except Exception:
                groups, group_occ = {}, {}
            if self._image_scan_id != scan_id:
                return
            self._tk_root().after(
                0, self._populate_image_after_scan,
                slots, scan_id, assets_path, groups, group_occ)

        self._set_tab_scanning("image", True)
        threading.Thread(target=_work, daemon=True).start()

    def _populate_image_after_scan(self, slots, scan_id, scan_dir,
                                   groups=None, group_occ=None):
        """Main-thread: store scan results and refresh the list."""
        if self._image_scan_id != scan_id:
            return
        self._set_tab_scanning("image", False)
        self._image_slots = slots
        self._image_slots_by_rel = {s.rel_path: s for s in slots}
        self._image_groups = groups or {}
        self._image_group_occ = group_occ or {}
        # Restore assignments persisted for a freshly-scanned folder; a re-scan
        # of the same folder keeps the live in-memory ones (see audio above).
        from ..core import staged_changes
        if scan_dir != self._image_scan_dir:
            staged = self._load_staged_changes(scan_dir)
            self._image_assignments = staged_changes.live_assignments(
                staged.get("image"), self._image_slots_by_rel)
            if "image_changed_only" in staged:
                self.image_changed_only_var.set(
                    bool(staged["image_changed_only"]))
            if "image_group_by_scene" in staged:
                self.image_group_by_scene_var.set(
                    bool(staged["image_group_by_scene"]))
            tags = staged.get("image_group_tags")
            self._image_group_tags = (
                {str(k): str(v).strip()[:50] for k, v in tags.items()
                 if str(v).strip()}
                if isinstance(tags, dict) else {})
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
        tree.item(rel, values=(slot.resolution_str(), slot.format_summary(),
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
        """Which of the image stores *rel_path* came from (monkeybug: make
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
        order)}, {rel_path: occurrences})``.

        Grouping identity is the on-card container: the radium card path for
        radium-embedded images (ordered by data offset = the animation's
        frame/play order), the scene directory for scene.assets textures, and
        the card directory for loose images.  Radium PNGs are extracted
        content-deduplicated across containers — the FIRST manifest row is a
        PNG's home group, and *occurrences* remembers how many on-card slots
        it patches.  Cheap text parsing (a few thousand tab rows), run on the
        scan worker thread; a slot no manifest covers (every non-Stern plugin)
        falls back to its parent folder in :meth:`_image_group_of`."""
        import re as _re

        groups, occ = {}, {}

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
        labels = {}
        for card, members in per_card.items():
            label = ""
            for _off, mrel in sorted(members):
                m = name_re.match(os.path.basename(mrel))
                if m:
                    label = m.group(1)
                    break
            id8 = os.path.basename(os.path.dirname(card))[:8] or card
            labels[card] = ("%s · %s" % (label, id8)) if label else id8
        for rel, (card, off) in primary.items():
            groups[rel] = ("rad::" + card, labels[card], off)

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
            label = card_dir or "(root)"
            groups.setdefault("images/" + cols[0],
                              ("dir::" + label, label, idx))

        return groups, occ

    def _image_group_of(self, rel):
        """``(group_key, label_base, order)`` for slot *rel*: the
        manifest-derived container from the last scan, or the parent-folder
        fallback for slots no manifest covers (every non-Stern plugin)."""
        g = self._image_groups.get(rel)
        if g is not None:
            return g
        folder = os.path.dirname(rel).replace("\\", "/") or "(root)"
        return ("dir::" + folder, folder, 0)

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
        changed = self._image_changed_on_disk
        touched = set(self._image_assignments) | changed

        slots = self._image_slots
        if self.image_changed_only_var.get():
            slots = [s for s in slots if s.rel_path in touched]
        srcf = self.image_source_filter_var.get()
        if srcf and srcf != "All sources":
            slots = [s for s in slots
                     if self._image_source_label(s.rel_path) == srcf]
        if grouped:
            # The search matches the group label too — the manifest name
            # AND the user's rename (see _image_group_rename) — so
            # "Char_Select" or a custom tag finds a whole animation whose
            # member files are just hashes.
            def _match(s):
                if query in s.rel_path.lower():
                    return True
                key, label, _o = self._image_group_of(s.rel_path)
                return (query in label.lower()
                        or query in self._image_group_tags.get(
                            key, "").lower())
            slots = [s for s in slots if not query or _match(s)]
        else:
            slots = [s for s in slots
                     if not query or query in s.rel_path.lower()]
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
            tree.insert(parent, tk.END, iid=s.rel_path, text=s.rel_path,
                        values=(res, s.format_summary(),
                                self._image_source_label(s.rel_path),
                                rep_disp),
                        tags=(tag,) if tag else ())

        if grouped:
            by_grp = {}                    # key -> (label_base, [slots])
            for s in slots:
                key, label, _order = self._image_group_of(s.rel_path)
                by_grp.setdefault(key, (label, []))[1].append(s)
            # Groups stay label-sorted; a header click re-sorts the children
            # WITHIN each group.  The default "#0" sort means play order here
            # (the manifests' frame sequence), not the flat path sort.
            # A user rename (_image_group_rename) replaces the display label
            # AND the sort key, so renamed groups land where you'd look.
            def _disp(k):
                return self._image_group_tags.get(k) or by_grp[k][0]
            for key in sorted(by_grp, key=lambda k: (_disp(k).lower(), k)):
                members = by_grp[key][1]
                label = _disp(key)
                if col == "#0":
                    members.sort(
                        key=lambda s: (self._image_group_of(s.rel_path)[2],
                                       s.rel_path.lower()),
                        reverse=desc)
                else:
                    members.sort(key=_key, reverse=desc)
                giid = _IMG_GROUP_IID + key
                n = len(members)
                tree.insert(
                    "", tk.END, iid=giid, open=(giid in open_groups),
                    text="%s — %d image%s" % (label, n,
                                              "" if n == 1 else "s"))
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
            filetypes=[("Image files", spec), ("All files", "*.*")])
        if not path:
            return
        self._image_assignments[rel] = path
        self._save_staged_changes()
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
            # (the search / Changed-only filters have already been applied).
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
            slot = self._image_slots_by_rel.get(row)
            if slot is not None:
                menu.add_separator()
                menu.add_command(
                    label=self._reveal_menu_label(),
                    command=lambda p=slot.abs_path:
                        self._reveal_in_file_manager(p))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ---- Replace Image: group bulk actions ---------------------------

    def _image_group_rename(self, group_iid):
        """Right-click → Rename group…: give a scene/animation group a
        custom display name.  The vendor's own scene-element names are
        mostly generic ("unnamed_instance_14"), so there's nothing better
        to extract automatically (monkeybug).  Stored per assets folder in
        the staged-changes sidecar; a blank (or unchanged-generic) entry
        restores the manifest name.  The rename also becomes the group's
        sort key and a Search match."""
        from tkinter import simpledialog
        key = group_iid[len(_IMG_GROUP_IID):]
        generic = next(
            (label for gkey, label, _o in self._image_groups.values()
             if gkey == key), "")
        if not generic and key.startswith("dir::"):
            generic = key[len("dir::"):]      # folder-fallback groups
        name = simpledialog.askstring(
            "Rename Group",
            "Display name for this group\n"
            "(blank restores \"%s\"):" % (generic or "the original name"),
            initialvalue=self._image_group_tags.get(key, generic),
            parent=self._tk_root())
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
        self._refresh_image_list()
        if self._image_current_rel in set(rels):
            self._image_render_preview(self._image_current_rel)
        try:
            self._image_tree.selection_set(group_iid)
            self._image_tree.see(group_iid)
        except tk.TclError:
            pass    # the Changed-only filter may have dropped the group

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
        image by clearing the affected canvas."""
        slot = self._image_slots_by_rel.get(rel) if rel is not None else None
        rep = self._image_assignments.get(rel) if rel is not None else None
        self._image_render_thumb(
            getattr(self, "_image_canvas", None),
            slot.abs_path if slot else None, "_image_preview_img_orig")
        self._image_render_thumb(
            getattr(self, "_image_canvas_rep", None), rep,
            "_image_preview_img_rep",
            empty_text=("(no replacement assigned — double-click the row "
                        "to pick one)" if slot else ""))

    def _image_clear_preview(self):
        """Reset the static previews entirely (used on manufacturer switch)."""
        self._image_current_rel = None
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
        """Force the Trim/pad checkbox on + disabled when this plugin's Write
        always length-matches, else leave it a free toggle.

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
        caps = getattr(mfr, "capabilities", None)
        try:
            forces = mfr.audio_forces_length_match(assets_dir)
        except TypeError:
            # A plugin still on the old no-arg signature.
            forces = mfr.audio_forces_length_match()
        if forces:
            self.audio_trim_var.set(True)
        else:
            self.audio_trim_var.set(bool(persisted_trim))
        self._audio_trim_cb.configure(
            state=(tk.DISABLED if forces else tk.NORMAL))
        if hasattr(self, "_audio_trim_tip"):
            note = (mfr.audio_length_note() or "").strip()
            if forces and getattr(caps, "audio_keep_length_override", False):
                # Plugins that ALSO offer a per-slot "Full" override (JJP)
                # aren't size-neutral — they trim by default but a longer file
                # is valid; don't claim the size-neutral rationale (it
                # contradicts the Full column).
                self._audio_trim_tip.text = (
                    "On by default — every replacement is trimmed or padded "
                    "to its original slot length on Write.\n\nTo keep one "
                    "track's full length instead, tick the “Full” box on "
                    "that slot in the list."
                    + (("\n\n" + note) if note else ""))
            elif forces:
                self._audio_trim_tip.text = (
                    "Always on for this format — it can't be turned off.\n\n"
                    "Write fits each replacement into the original sound's "
                    "exact slot in place (size-neutral), so every replacement "
                    "is automatically matched to the original length; a "
                    "different length would strand every later offset."
                    + (("\n\n" + note) if note else ""))
            else:
                self._audio_trim_tip.text = (
                    "When on, a replacement longer or shorter than the "
                    "original is trimmed or padded to the original slot "
                    "length before Write. When off, the replacement is used "
                    "as-is.")
        return forces

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
        if _live(self._audio_scan_dir):
            data["audio"] = dict(self._audio_assignments)
            data["audio_loop"] = dict(self._audio_loop_flags)
            data["audio_keep"] = dict(self._audio_keep_full_flags)
            data["audio_trim"] = bool(self.audio_trim_var.get())
        if _live(self._video_scan_dir):
            data["video"] = dict(self._video_assignments)
            data["video_trim"] = bool(self.video_trim_var.get())
            data["video_no_conversion"] = bool(
                self.video_no_conversion_var.get())
        if _live(self._image_scan_dir):
            data["image"] = dict(self._image_assignments)
            data["image_changed_only"] = bool(
                self.image_changed_only_var.get())
            data["image_group_by_scene"] = bool(
                self.image_group_by_scene_var.get())
            data["image_group_tags"] = {
                k: v for k, v in self._image_group_tags.items() if v}
            data["image_source_filter"] = self.image_source_filter_var.get()
        staged_changes.save(assets_dir, data)

    # ==================================================================
    # Replace Text tab — edit the player-facing on-screen strings Extract
    # pulled out to text/strings.tsv.  Unlike the audio/video/image tabs,
    # there are no in-memory "pending assignments": edits are written
    # straight back to the manifest, and Write re-reads it to patch every
    # matching string in place (size-neutral).
    # ==================================================================

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
                 "menu labels, status text. Pick your extracted folder, click a "
                 "string, type the new text, and Apply. Each replacement must "
                 "fit the original's length (it's space-padded for you), so "
                 "shorter-or-equal works and longer is rejected. Build the "
                 "update on the Write tab when you're done.",
            font=(_SANS_FONT, 9, "italic"),
            wraplength=720, justify=tk.LEFT)
        _text_desc.pack(anchor=tk.W, **pad)
        self._register_responsive_wrap(_text_desc)

        # Assets folder row (shared with the Write / other Replace tabs).
        row = ttk.Frame(f); row.pack(fill=tk.X, padx=10, pady=4)
        self._text_assets_row = row
        ttk.Label(row, text="Assets Folder:", width=14, anchor=tk.W).pack(
            side=tk.LEFT)
        self._path_combo(row, self.write_assets_var, "write_assets").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self._make_assets_scan_buttons(row, "text", self._scan_text_strings)
        ttk.Label(f, text="(the folder Extract produced — shared with the "
                          "Write tab)",
                  font=(_SANS_FONT, 8, "italic")).pack(anchor=tk.W, padx=24)

        # Search + status toolbar.
        tools = ttk.Frame(f); tools.pack(fill=tk.X, padx=10, pady=(8, 2))
        ttk.Label(tools, text="Search:").pack(side=tk.LEFT)
        ttk.Entry(tools, textvariable=self.text_search_var, width=24).pack(
            side=tk.LEFT, padx=(4, 12))
        ttk.Button(tools, text="Clear all edits",
                   command=self._text_clear_all).pack(side=tk.LEFT)
        self._text_status_lbl = ttk.Label(
            tools, textvariable=self.text_status_var, font=(_SANS_FONT, 9))
        self._text_status_lbl.pack(side=tk.RIGHT)

        # String list.
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 4))
        self._text_tree = ttk.Treeview(
            list_frame, columns=("new", "max", "scene"),
            height=8, selectmode="browse")
        self._text_tree.heading("#0", text="On-Screen Text", anchor=tk.W)
        self._text_tree.heading("new", text="New Text", anchor=tk.W)
        self._text_tree.heading("max", text="Max", anchor=tk.W)
        self._text_tree.heading("scene", text="Scene", anchor=tk.W)
        self._text_tree.column("#0", width=300, minwidth=160)
        self._text_tree.column("new", width=230, minwidth=120)
        self._text_tree.column("max", width=50, minwidth=40, anchor=tk.E)
        self._text_tree.column("scene", width=150, minwidth=80)
        self._persist_tree_columns(
            self._text_tree, "text", ("#0", "new", "max", "scene"))
        self._text_sort_cfg = [
            ("#0", "On-Screen Text", False), ("new", "New Text", False),
            ("max", "Max", True), ("scene", "Scene", False)]
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
            text="Pick your extracted assets folder above, then click Scan.",
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

        self._text_scene_full_var = tk.StringVar(value="")
        ttk.Label(edit, textvariable=self._text_scene_full_var,
                  font=(_SANS_FONT, 8, "italic"), foreground="#888888",
                  wraplength=700, justify=tk.LEFT).pack(
            anchor=tk.W, padx=8, pady=(0, 4))

        ttk.Label(
            f,
            text="Your edits are saved to text/strings.tsv as you Apply them "
                 "and are written to the card automatically when you build the "
                 "update on the Write tab — no extra step.",
            font=(_SANS_FONT, 9), foreground="#888888",
            wraplength=720, justify=tk.LEFT).pack(
            anchor=tk.W, padx=12, pady=(6, 8))

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
        parent = parts[-2] if len(parts) >= 2 else ""
        if len(parent) > 14:
            parent = parent[:5] + "…" + parent[-4:]
        return parent + "/" + name if parent else name

    @staticmethod
    def _text_byte_len(s):
        """Byte length of *s* as the engine measures it for the size budget."""
        return len(s.encode("latin1", "replace"))

    def _text_is_edited(self, r):
        return bool(r["replacement"]) and r["replacement"] != r["original"]

    # ---- Replace Text: scanning / list -------------------------------

    def _scan_text_strings(self):
        """Load ``text/strings.tsv`` from the assets folder into the list.  A
        replacement equal to its original is normalised to '' (unchanged) so the
        New-Text column reads blank for everything the user hasn't touched."""
        from ..core import text_manifest
        assets_path = (self.write_assets_var.get() or "").strip()
        self._text_scan_id += 1

        if not assets_path or not os.path.isdir(assets_path):
            self._text_rows = []
            self._text_scan_dir = ""
            self._text_clear_edit_panel()
            self._refresh_text_list()
            self._text_empty.configure(
                text="Pick your extracted assets folder above, then click Scan.")
            self._text_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            return

        try:
            loaded = text_manifest.load(assets_path)
        except Exception as e:
            loaded = []
            messagebox.showerror(
                "Couldn't read text",
                "Couldn't read the on-screen-text manifest:\n%s" % e)
        rows = []
        for r in loaded:
            rep = r["replacement"]
            if rep == r["original"]:
                rep = ""                     # rep == orig => unchanged
            rows.append({"path": r["path"], "original": r["original"],
                         "replacement": rep})
        self._text_rows = rows
        self._text_scan_dir = assets_path
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
        """Apply the search filter and repopulate the string tree."""
        tree = getattr(self, "_text_tree", None)
        if tree is None:
            return
        tree.delete(*tree.get_children())

        query = (self.text_search_var.get() or "").strip().lower()
        total = len(self._text_rows)
        edited = sum(1 for r in self._text_rows if self._text_is_edited(r))
        col, desc = self._text_sort

        def _key(pair):
            _i, r = pair
            if col == "new":
                return ((r["replacement"] or "").lower(), r["original"].lower())
            if col == "max":
                return (self._text_byte_len(r["original"]),)
            if col == "scene":
                return (self._text_scene_label(r["path"]).lower(),
                        r["original"].lower())
            return (r["original"].lower(),)  # "#0" on-screen text

        # Filter first, then sort — but keep each row's ORIGINAL index as its
        # iid (other handlers map the iid back via self._text_rows[int(iid)]),
        # so sorting only changes display order, never identity.
        visible = [
            (i, r) for i, r in enumerate(self._text_rows)
            if not (query and query not in r["original"].lower()
                    and (not r["replacement"]
                         or query not in r["replacement"].lower()))]
        visible.sort(key=_key, reverse=desc)
        self._show_sort_arrows(tree, self._text_sort_cfg, self._text_sort)
        shown = len(visible)
        for i, r in visible:
            tree.insert(
                "", tk.END, iid=str(i), text=r["original"],
                values=(r["replacement"], self._text_byte_len(r["original"]),
                        self._text_scene_label(r["path"])),
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
        self._text_scene_full_var.set("Scene: " + r["path"])
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
        orig_len = self._text_byte_len(r["original"])
        new_len = self._text_byte_len(self.text_new_var.get())
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
        if self._text_byte_len(new) > self._text_byte_len(orig):
            messagebox.showwarning(
                "Replacement too long",
                "“%s” is %d bytes but the original is only %d. On-screen text "
                "is patched in place, so a replacement has to fit the "
                "original's length — use a shorter string."
                % (new, self._text_byte_len(new), self._text_byte_len(orig)))
            return
        eff = "" if new == orig else new       # new == orig => unchanged
        if self.text_apply_all_var.get():
            targets = [rr for rr in self._text_rows if rr["original"] == orig]
        else:
            targets = [r]
        for rr in targets:
            rr["replacement"] = eff
        self._save_text_manifest()
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
        if self.text_apply_all_var.get():
            targets = [rr for rr in self._text_rows if rr["original"] == orig]
        else:
            targets = [r]
        for rr in targets:
            rr["replacement"] = ""
        self._save_text_manifest()
        self.text_new_var.set(orig)
        self._refresh_text_list()
        try:
            self._text_tree.selection_set(iid)
            self._text_tree.see(iid)
        except tk.TclError:
            pass
        self._text_update_budget()

    def _text_clear_all(self):
        if not any(r["replacement"] for r in self._text_rows):
            return
        if not messagebox.askyesno(
                "Clear all edits",
                "Remove every on-screen-text edit and restore the originals?"):
            return
        for r in self._text_rows:
            r["replacement"] = ""
        self._save_text_manifest()
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
        idx = self._notebook.index(self._notebook.select())
        tab_id = self._notebook.tabs()[idx]
        text = self._notebook.tab(tab_id, "text").strip()
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
        # (monkeybug: "the older help text remains").
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
            # window. Re-apply the scroll geometry now (matches monkeybug's
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
        # Pack Back left of the title, then re-pack title so it sits
        # to the right of the Back button.
        self._back_btn.pack(side=tk.LEFT, padx=(0, 8))
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
        self._back_btn.configure(state=tk.NORMAL if enabled else tk.DISABLED)

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
        # "Original Card imag" — monkeybug 5).  All the column's labels move
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
        # The Mod Pack tab is shared, but the "Transfer Mods to New Version"
        # section only fits plugins whose vendor re-lays-out the card across
        # versions (Stern) — show it only for those, hide it for the rest.
        if hasattr(self, "_modpack_transfer_frame"):
            if getattr(caps, "mod_transfer", False):
                self._modpack_transfer_frame.pack(fill=tk.X, padx=10, pady=4)
                self._prefill_transfer_dst()
            else:
                self._modpack_transfer_frame.pack_forget()
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
                self._audio_tree["displaycolumns"] = ("len", "fmt", "loop",
                                                      "rep")
            elif getattr(caps, "audio_keep_length_override", False):
                self._audio_tree["displaycolumns"] = ("len", "fmt", "keep",
                                                      "rep")
            else:
                self._audio_tree["displaycolumns"] = ("len", "fmt", "rep")
        # "Group duplicates" checkbox: only for plugins that implement the
        # duplicate scan (CGC).
        if hasattr(self, "_audio_dup_group_cb"):
            if getattr(mfr, "find_duplicate_sounds", None):
                if not self._audio_dup_group_cb.winfo_ismapped():
                    self._audio_dup_group_cb.pack(
                        side=tk.LEFT, padx=(0, 12),
                        before=self._audio_sort_hint_lbl)
            else:
                self._audio_dup_group_cb.pack_forget()
        self._audio_clear_preview()
        self._refresh_audio_list()
        if hasattr(self, "_audio_length_note_lbl"):
            self._audio_length_note_lbl.configure(
                text=mfr.audio_length_note() or "")
        # Force the Trim/pad checkbox on + disabled for plugins whose Write
        # always length-matches (e.g. JJP, Spike 2, CGC's Pulp Fiction), so the
        # toggle isn't misleading.  No extract is scanned yet here, so a plugin
        # whose answer is per-extract (CGC) reports its default; the lock is
        # re-applied against the real folder after an audio scan.
        self._apply_audio_trim_lock(mfr)
        # Same clean slate for the video tab.
        self._video_slots = []
        self._video_slots_by_rel = {}
        self._video_assignments = {}
        self._video_scan_dir = ""
        self._video_clear_preview()
        self._refresh_video_list()
        if hasattr(self, "_video_length_note_lbl"):
            self._video_length_note_lbl.configure(
                text=mfr.video_length_note() or "")
        # Same clean slate for the image tab.
        self._image_slots = []
        self._image_slots_by_rel = {}
        self._image_assignments = {}
        self._image_scan_dir = ""
        self._image_clear_preview()
        self._refresh_image_list()
        if hasattr(self, "_image_note_lbl"):
            self._image_note_lbl.configure(text=mfr.image_note() or "")

        # BOF-only Extract callout — pack just below the Extract tab's
        # warning label so users see it before they hit Extract.  Other
        # manufacturers don't need this preamble; their extracts use
        # standard tools (or none at all).  Checking mfr.key directly is
        # OK here because the banner copy is BOF-specific (mentions Dune
        # / Winchester / Labyrinth by name, references "GBOF" magic,
        # etc.); promoting this to a generic capability would mean
        # plumbing per-plugin banner text through the manifest, more
        # surface area for one banner.
        if mfr.key == "bof":
            self._extract_bof_banner.pack(
                fill=tk.X, padx=10, pady=(6, 6),
                after=self._extract_output_row_ref)
        else:
            self._extract_bof_banner.pack_forget()

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
            # The per-mode description is JJP-specific; hide it for
            # plugins whose Write tab is the ISO-build flow.
            self._write_desc.pack_forget()
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
            # 3-step spacing look uneven (monkeybug Extract #1).
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

        # Flash-image action (Stern Spike 2) — write a whole pre-built image
        # onto a card.  Independent of the Build/Write destination toggle.
        if caps.flash_image:
            self._flash_frame.pack(fill=tk.X, padx=10, pady=(8, 4))
        else:
            self._flash_frame.pack_forget()
        # Card diagnostics — manufacturers that can read a failed install's
        # on-card log back (CGC's diagnose_card).  Lives inside the flash
        # frame, so it can only show when that frame is visible.
        if caps.flash_image and getattr(mfr, "diagnose_card", None):
            self._diagnose_btn.pack(side=tk.RIGHT, padx=(8, 0), anchor=tk.N,
                                    after=self._flash_btn)
        else:
            self._diagnose_btn.pack_forget()

        # "Revert all changes…" — only meaningful when this plugin has a Replace
        # surface (the assets folder is where staged edits live).
        has_replace = (caps.replace_audio or caps.replace_video
                       or caps.replace_image or caps.replace_text)
        if has_replace and self._on_revert_all is not None:
            self._revert_all_btn.pack(
                side=tk.RIGHT, padx=(0, 6), before=self._write_btn)
        else:
            self._revert_all_btn.pack_forget()

        # Refresh detect badges (file might already be selected from
        # the previous manufacturer's settings — unusual but possible).
        self._update_extract_badge()
        self._update_write_badge()

        # If we're entering a direct_ssd plugin in SSD mode without
        # admin, make sure the Extract / Apply buttons are disabled.
        self._refresh_ssd_run_buttons()

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

    # ---- Persisted Extract options (monkeybug: checkboxes don't stick) ----

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

        if extract_ssd and mfr.direct_ssd_extract_phases:
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
        # distance apart (monkeybug: the gaps were visibly unequal).
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

    def _configure_tab(self, label, visible):
        for tab_id in self._notebook.tabs():
            if self._notebook.tab(tab_id, "text").strip() == label:
                if visible:
                    self._notebook.tab(tab_id, state="normal")
                else:
                    self._notebook.tab(tab_id, state="hidden")
                return

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
        folder — monkeybug's "default to the folder that is listed".  Walks
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

    def _path_combo(self, parent, var, field):
        """An editable path box with a recent-paths dropdown.

        Drop-in replacement for the plain ``ttk.Entry`` the path rows used:
        same textvariable wiring (typing + traces unchanged), plus a dropdown
        of this manufacturer's recent paths for *field*.  Values refresh on
        every open (``postcommand``) so a path recorded mid-session appears
        without any explicit widget update."""
        combo = ttk.Combobox(parent, textvariable=var)
        combo.configure(postcommand=lambda c=combo, f=field: c.configure(
            values=tuple(self._path_history.get(f, ()))))
        return combo

    def set_path_history(self, history):
        """Swap in the current manufacturer's recent-paths dict
        (``{field_key: [paths]}``).  Called by the App on mfr switch and
        after it records a new path."""
        self._path_history = dict(history or {})

    def _browse_extract_input(self):
        path = filedialog.askopenfilename(
            title="Select input file", filetypes=self._input_filetypes(),
            initialdir=self._initialdir_for(self.extract_input_var.get()))
        if path:
            # Tk's file dialogs return forward slashes even on Windows;
            # normalize so path fields don't mix //server/share with
            # \\server\share styles (monkeybug 5.5).
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
                self._extract_badge_row.pack(
                    fill=tk.X, padx=10, pady=(0, 2),
                    before=self._extract_output_row())
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
            self._write_desc.pack_forget()
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
                # this is what silently emptied monkeybug's preview after a
                # relaunch-as-admin.
                if sys.platform == "win32" and is_admin():
                    self._write_admin_unc_hint.pack(
                        anchor=tk.W, padx=10, pady=(0, 4),
                        before=self._write_filename_lbl)
                # SSD mode: explain in-place write behaviour so users
                # know what to expect before they click Apply
                # Modifications.  Per-manufacturer (medium-aware) wording.
                self._write_desc.configure(
                    text=self._current_mfr.direct_write_description())
                self._write_desc.pack(
                    anchor=tk.W, padx=10, pady=(2, 6),
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
                # IS the output.  Hide the Output Folder row.
                if hasattr(self, "_write_output_row_ref"):
                    self._write_output_row_ref.pack_forget()
                # Kick a preview scan in the background so the user
                # sees the modified files without a separate click.
                self._scan_write_preview()
            else:
                # ISO layout: source → original ISO → badge → assets
                # → output folder.  Dynamic rows go BEFORE the
                # assets row (because the original ISO sits above
                # the modified-assets folder in this flow).
                self._write_upd_row.pack(
                    fill=tk.X, padx=10, pady=4,
                    before=self._write_assets_row())
                self._write_badge_row.pack(
                    fill=tk.X, padx=10, pady=(0, 2),
                    before=self._write_assets_row())
                self._write_desc.configure(
                    text=self._current_mfr.build_write_description())
                self._write_desc.pack(
                    anchor=tk.W, padx=10, pady=(2, 6),
                    before=self._write_assets_row())
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

    def _set_extract_button_running(self, running):
        """Drive the single Extract/Cancel button.

        While a job is in flight the Extract button doubles as a live Cancel
        (there's no separate Cancel widget any more); otherwise it's "Extract",
        enabled only when the inputs are ready (see _refresh_extract_enabled).
        """
        if running:
            self._extract_btn.configure(
                text="Cancel", command=self._on_extract_cancel,
                state=tk.NORMAL)
            self._extract_btn_tip.text = (
                "Cancel the operation in progress — it stops as soon as it's "
                "safe to.")
        else:
            self._extract_btn.configure(
                text="Extract", command=self._on_extract)
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

    def _set_write_button_running(self, running):
        """Drive the single Build/Cancel button.

        Mirrors _set_extract_button_running: while a build/write runs the
        Build button doubles as a live Cancel (monkeybug 4.4 — there's no
        separate Cancel widget any more); otherwise it shows the mode's build
        label and re-arms the write action.
        """
        if running:
            self._write_btn.configure(
                text="Cancel", command=self._on_write_cancel,
                state=tk.NORMAL)
        else:
            self._write_btn.configure(
                text=self._current_write_button_label(),
                command=self._on_write_clicked, state=tk.NORMAL)

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
        import hashlib
        import os
        import re as _re
        import threading

        assets_path = (self.write_assets_var.get() or "").strip()
        # Clear whatever's there from a prior scan.
        self._write_preview_tree.delete(
            *self._write_preview_tree.get_children())

        # Bump the scan-id up front so any older in-flight scan stops posting
        # results AND the pending rows below share the id with the on-disk scan.
        self._write_preview_scan_id += 1
        scan_id = self._write_preview_scan_id

        # In-memory Replace-Audio / Replace-Video assignments are staged onto
        # disk only at build time, so the MD5 scan below can't see them yet.
        # List them up front as "Pending" so the preview reflects what the
        # build will actually apply (otherwise a staged replacement looks like
        # nothing's changed).
        pending_n = self._add_pending_preview_rows(assets_path, scan_id)

        # We just superseded any in-flight scan (its finish is now guarded
        # out), so nothing else will restore the button — idle it on every
        # path that returns without launching the worker.
        if not assets_path or not os.path.isdir(assets_path):
            self._set_preview_scanning(False)
            if not pending_n:
                self._write_preview_empty.configure(
                    text="Select your modified assets folder above to preview "
                         "changed files.")
                self._write_preview_empty.place(
                    relx=0.5, rely=0.5, anchor=tk.CENTER)
            return
        checksums_file = os.path.join(assets_path, ".checksums.md5")
        if not os.path.isfile(checksums_file):
            self._set_preview_scanning(False)
            if not pending_n:
                self._write_preview_empty.configure(
                    text=("Pick a folder produced by Extract first "
                          "(no .checksums.md5 found)."))
                self._write_preview_empty.place(
                    relx=0.5, rely=0.5, anchor=tk.CENTER)
            return

        if not pending_n:
            self._write_preview_empty.configure(
                text="Scanning for modified files…")
            self._write_preview_empty.place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)

        def _scan():
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
                # Couldn't read the baseline after all — restore the button.
                self._tk_root().after(
                    0, self._finish_write_preview_scan, 0, scan_id)
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

            changed = []
            for root_dir, dirs, files in os.walk(assets_path):
                # Skip the .orig snapshot mirror (core.staged_originals): its
                # files aren't in the baseline anyway, but pruning avoids
                # hashing a backup copy of every edited asset.
                dirs[:] = [d for d in dirs if d != ORIG_DIR]
                for name in files:
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
                    h = hashlib.md5()
                    try:
                        with open(full, "rb") as fh:
                            for chunk in iter(
                                    lambda: fh.read(65536), b""):
                                h.update(chunk)
                    except OSError:
                        continue
                    if h.hexdigest() == saved[rel]:
                        continue
                    if self._write_preview_scan_id != scan_id:
                        return  # superseded — drop this scan
                    changed.append(rel)
                    ext = os.path.splitext(name)[1].lstrip(".") or "?"
                    self._tk_root().after(
                        0, self._add_write_preview_row,
                        rel, ext, "Modified", scan_id)

            if self._write_preview_scan_id == scan_id:
                self._tk_root().after(
                    0, self._finish_write_preview_scan,
                    len(changed), scan_id)

        # Flip the Refresh button to a disabled "Scanning…" state so the
        # walk is visibly in progress — over a network share the per-file
        # MD5 trickles rows in slowly, which without this looks frozen
        # (monkeybug saw rows appear with no indication anything was running).
        self._set_preview_scanning(True)
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

    def _persist_tree_columns(self, tree, tree_key, col_ids):
        """Restore *tree*'s saved column widths and keep them saved as the user
        drags them — so a layout the user tuned survives a restart (monkeybug:
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
        ``_AUTOSIZE_MAX_PX`` (monkeybug 4.2: long names sat ellipsized while
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
        right of the per-tab intro text when the window was widened (monkeybug).
        Applies the current width immediately (best-effort)."""
        self._responsive_wrap_labels.append((label, margin, minimum))
        try:
            w = self._mfr_view_canvas.winfo_width()
            if w > 1:
                label.configure(wraplength=max(minimum, w - margin))
        except (tk.TclError, AttributeError):
            pass

    def _make_assets_scan_buttons(self, row, tab_key, scan_cmd):
        """Build the shared *Browse… / Scan* pair for a Replace tab's assets
        row and register them under *tab_key* so :meth:`_set_tab_scanning` can
        disable + relabel them while a scan runs.  All four Replace tabs share
        the same two buttons (Browse is always the folder picker); only the
        Scan command differs."""
        browse = ttk.Button(row, text="Browse...",
                            command=self._browse_write_assets)
        browse.pack(side=tk.LEFT, padx=(8, 0))
        scan = ttk.Button(row, text="Scan", command=scan_cmd)
        scan.pack(side=tk.LEFT, padx=(4, 0))
        self._browse_buttons[tab_key] = browse
        self._scan_buttons[tab_key] = scan

    def _set_tab_scanning(self, tab_key, active):
        """Disable + relabel a Replace tab's Scan/Browse buttons while its scan
        runs (mirrors the Write-preview Refresh button) so a slow scan over a
        network share can't look idle — the very glitch monkeybug hit.  Tolerant
        of tabs/layouts where a button doesn't exist."""
        scan = self._scan_buttons.get(tab_key)
        browse = self._browse_buttons.get(tab_key)
        try:
            if scan is not None:
                scan.configure(text="⏳  Scanning…" if active else "Scan",
                               state=tk.DISABLED if active else tk.NORMAL)
            if browse is not None:
                browse.configure(state=tk.DISABLED if active else tk.NORMAL)
        except tk.TclError:
            pass

    def _set_preview_scanning(self, active):
        """Toggle the preview Refresh button between idle and a disabled
        "Scanning…" state so a slow (e.g. network-share) scan is visibly
        in progress.  Tolerant of layouts where the button doesn't exist."""
        btn = getattr(self, "_write_preview_refresh_btn", None)
        if btn is None:
            return
        try:
            if active:
                btn.configure(text="⏳  Scanning…", state=tk.DISABLED)
            else:
                btn.configure(text="🔄  Refresh", state=tk.NORMAL)
        except tk.TclError:
            pass

    def _finish_write_preview_scan(self, n_changed, scan_id):
        """End-of-scan housekeeping (main-thread only)."""
        if self._write_preview_scan_id != scan_id:
            return
        # Latest scan finished — restore the Refresh button.
        self._set_preview_scanning(False)
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
        try:
            idx = self._notebook.index(self._notebook.select())
            tab_id = self._notebook.tabs()[idx]
            if self._notebook.tab(tab_id, "text").strip() != "Write":
                return
        except (tk.TclError, IndexError):
            return
        self._scan_write_preview()

    def _browse_extract_output(self):
        path = filedialog.askdirectory(
            title="Select output folder",
            initialdir=self._initialdir_for(
                self.extract_output_var.get(), self.extract_input_var.get()))
        if path:
            self.extract_output_var.set(os.path.normpath(path))

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
                "     After transfer, the Write tab builds: %s%s%s"
                % (stem, suffix, ext))
        else:
            self.transfer_output_var.set("")

    def _browse_write_upd(self):
        path = filedialog.askopenfilename(
            title="Select original update file",
            filetypes=self._input_filetypes(),
            initialdir=self._initialdir_for(self.write_upd_var.get()))
        if path:
            self.write_upd_var.set(os.path.normpath(path))

    def _browse_write_assets(self):
        path = filedialog.askdirectory(
            title="Select modified assets folder",
            initialdir=self._initialdir_for(
                self.write_assets_var.get(), self.extract_output_var.get()))
        if not path:
            return
        # If the picked folder has no `.checksums.md5` but a parent
        # within a couple of levels does, the user almost certainly
        # drilled into a subfolder of the Extract output by mistake
        # (e.g. picked `sound/` when the real folder is its parent).
        # Offer to use the parent rather than silently accepting a
        # path that'll fail at Scan time.
        if not os.path.isfile(os.path.join(path, ".checksums.md5")):
            parent_with_checksums = self._find_checksums_ancestor(path)
            if parent_with_checksums:
                use_parent = messagebox.askyesno(
                    "Use parent folder?",
                    "The folder you picked doesn't contain a "
                    "`.checksums.md5` baseline, but its parent "
                    f"`{parent_with_checksums}` does — that's the "
                    "folder Extract produced.\n\n"
                    "Use the parent folder instead?")
                if use_parent:
                    path = parent_with_checksums
        self.write_assets_var.set(os.path.normpath(path))
        # Picking a folder is a strong signal the user wants to work with it —
        # kick off the scan for whichever replace tab is open instead of making
        # them click Scan separately.
        self._autoscan_active_assets_tab()

    def _autoscan_active_assets_tab(self):
        """Scan the assets folder for whichever tab is currently visible."""
        try:
            idx = self._notebook.index(self._notebook.select())
            text = self._notebook.tab(self._notebook.tabs()[idx], "text").strip()
        except Exception:
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
                text = self._notebook.tab(tab_id, "text").strip()
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
        try:
            return bool(tree.get_children())
        except tk.TclError:
            return True

    def _on_write_clicked(self):
        """Build-button click.  Warn (but allow) when the preview shows no
        changes — building an unmodified card just makes a copy of the
        original, which monkeybug flagged as easy to do by accident — then
        defer to the app's write callback."""
        if (not self._is_running()
                and not self._has_pending_write_changes()):
            if not messagebox.askyesno(
                "Nothing modified",
                "No modified files were detected, so this will build a copy "
                "of the original image with no changes.\n\nBuild anyway?",
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
        menu = self._build_settings_menu()
        try:
            self.root.update_idletasks()
            x = (self._gear_btn.winfo_rootx()
                 + self._gear_btn.winfo_width()
                 - menu.winfo_reqwidth())
            y = self._gear_btn.winfo_rooty() + self._gear_btn.winfo_height()
            menu.tk_popup(max(0, x), y)
        finally:
            menu.grab_release()

    def _build_settings_menu(self):
        """Construct the ⚙ dropdown.

        Built fresh on every click so the dynamic bits (theme direction,
        update-check busy state, disk badge, prerequisite summary) are always
        current — a Menu is cheap to construct and needs no invalidation
        plumbing that way."""
        c = THEMES[self._current_theme]
        # No explicit font — Tk's TkMenuFont is the platform's native menu
        # font/metrics; forcing our own renders visibly "off" next to real
        # context menus (monkeybug/David).
        kw = dict(tearoff=0, bg=c["bg"], fg=c["fg"],
                  activebackground=c["accent"], activeforeground="#ffffff",
                  disabledforeground=c["gray"])
        menu = tk.Menu(self.root, **kw)

        # A found update leads the menu (matches the ● on the gear) so it's
        # still reachable after the banner is dismissed.
        if self._update_available:
            version, url = self._update_available
            menu.add_command(
                label=f"● Download update v{version}…",
                command=lambda u=url: webbrowser.open(u))
            menu.add_separator()

        # Theme — a dynamic verb label (monkeybug: the bare ☀/☽ glyph wasn't
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

        # Voice recognition quality — the faster-whisper model Auto-name
        # call-outs uses.  App-wide (persisted), shown even for plugins
        # without transcribe so the setting is always discoverable.
        vq_menu = tk.Menu(menu, **kw)
        for value, label in VOICE_QUALITY_CHOICES:
            vq_menu.add_radiobutton(
                label=label, value=value,
                variable=self.voice_quality_var,
                command=self._on_voice_quality_pick)
        # Escape hatch for a damaged model download (monkeybug): clears the
        # huggingface cache dirs so the next run re-downloads clean.  Locked
        # out mid-run — a transcribe in flight holds its model files open.
        vq_menu.add_separator()
        vq_menu.add_command(
            label="Clear downloaded voice models…",
            command=self._clear_voice_models,
            state=(tk.DISABLED if self._is_running() else tk.NORMAL))
        menu.add_cascade(label="Voice recognition quality", menu=vq_menu)
        menu.add_separator()

        # Prerequisites — one cascade, like the voice-quality submenu above
        # (monkeybug: three loose prerequisite lines read as clutter).  The
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
        menu.add_cascade(label=summary, menu=prereq_menu)
        return menu

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
        try:
            idx = self._notebook.index(self._notebook.select())
            tab = self._notebook.tab(self._notebook.tabs()[idx], "text").strip()
        except (tk.TclError, IndexError):
            tab = "Extract"
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
        """Open the modal that collects (image, target card) for a flash.

        The dialog hands the choice to the app's ``on_flash_image`` callback,
        which runs the flash through the normal status area.  Refuses while a
        run is in flight (the status area is busy)."""
        if self._on_flash_image is None:
            return
        if self._is_running():
            messagebox.showinfo(
                "Busy",
                "Finish or cancel the current operation before flashing a "
                "card.")
            return
        # Flash writes a whole pre-built / backup image and is independent of
        # this session's edits, so a "nothing modified" state is legitimate
        # (restoring a backup, writing an image built earlier).  monkeybug
        # still wanted a heads-up so an accidental no-change flash is caught.
        if not self._has_pending_write_changes():
            if not messagebox.askyesno(
                "Nothing modified",
                "Nothing was modified this session.\n\nFlashing writes a "
                "whole pre-built or backup image onto the card, independent "
                "of any edits here — expected if you're restoring a backup "
                "or writing an image you built earlier. To apply changes "
                "instead, build the SD-card image first.\n\nOpen the flash "
                "dialog anyway?",
                icon="warning"):
                return
        from .flash_dialog import FlashImageDialog
        FlashImageDialog(
            self._tk_root(),
            manufacturer=self._current_mfr,
            theme_name=self._current_theme,
            on_flash=self._on_flash_image)

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
        """Compose the gear button's notification marks: ● when an update is
        available, the warning glyph when staging cleanup is pending."""
        text = self._gear_glyph
        width = 3
        if self._update_available:
            text += " ●"
            width += 2
        if self._disk_badge_suffix:
            text += " " + self._gear_badge_glyph
            width += 2
        try:
            self._gear_btn.configure(text=text, width=width)
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

    def _browse_write_output(self):
        path = filedialog.askdirectory(
            title="Select output folder",
            initialdir=self._initialdir_for(
                self.write_output_var.get(), self.write_assets_var.get()))
        if path:
            self.write_output_var.set(os.path.normpath(path))

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
            extra = f" — {game.notes}" if game.notes else ""
            # Era-switching plugins carry an era-agnostic picker badge (Stern's
            # "SPIKE 2"), so it can't say that *this* file's era is capture/
            # extract-only.  Flag it here when the era-resolved capabilities
            # expose no Write/Replace surface (e.g. Stern Whitestar ROMs).
            caps = mfr.capabilities
            if hasattr(mfr, "set_era") and not caps.write and not (
                    caps.replace_audio or caps.replace_video
                    or caps.replace_image or caps.replace_text):
                extra += "  (extract only)"
            label.configure(text=f"Detected: {game.display}{extra}")
            return

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

    def set_prereq_result(self, name, ok, message):
        """Update one indicator with the probe's result."""
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
        if not ok and p.install_hint:
            tip += f"\n\nFix: {p.install_hint}"
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

    def _update_write_filename(self):
        # SD-card-image plugins (Stern / CGC, capabilities.flash_image) already
        # show the Output Folder; the extra "Output: …/name.raw" line just
        # repeats it (monkeybug 4.6), so keep it blank there — UNLESS the
        # plugin renames the build (write_output_suffix), where the distinct
        # name is exactly what the user needs to see.  The label widget
        # itself stays as the layout anchor other rows pack `before=`.
        mfr = getattr(self, "_current_mfr", None)
        suffix = getattr(mfr, "write_output_suffix", "") if mfr else ""
        if mfr is not None and getattr(mfr.capabilities, "flash_image", False):
            upd = self.write_upd_var.get().strip()
            if suffix and upd:
                stem, ext = os.path.splitext(os.path.basename(upd))
                self._write_filename_lbl.configure(
                    text=f"Builds: {stem}{suffix}{ext}")
            else:
                self._write_filename_lbl.configure(text="")
            return
        # Direct-SD write has no output file (the card itself is the
        # destination) and the file-mode "Original" input row is hidden, so
        # don't surface its (possibly stale, e.g. a prior session's) filename.
        if (getattr(self, "write_input_source_var", None) is not None
                and self.write_input_source_var.get() == "ssd"):
            self._write_filename_lbl.configure(text="")
            return
        upd = self.write_upd_var.get().strip()
        out = self.write_output_var.get().strip()
        name = os.path.basename(upd) if upd else ""
        if name and suffix:
            stem, ext = os.path.splitext(name)
            name = f"{stem}{suffix}{ext}"
        if name and out:
            spec_ext = (self._current_mfr.input_spec.extensions[0].lower()
                        if self._current_mfr else ".upd")
            full = out if out.lower().endswith(spec_ext) else os.path.join(
                out, name)
            self._write_filename_lbl.configure(text=f"Output: {full}")
        elif name:
            self._write_filename_lbl.configure(text=f"Filename: {name}")
        else:
            self._write_filename_lbl.configure(text="")

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
        menu.add_command(label="Save As…",
                         command=lambda w=widget: self._log_save_as(w))
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

    def append_log(self, text, level="info"):
        # Calls before any mfr is selected (e.g. update-check on startup
        # while picker is showing) are buffered against the first mfr's
        # widget once one is selected.  For now, silently drop them.
        ts = time.strftime("%H:%M:%S")
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

    def append_log_link(self, text, url):
        ts = time.strftime("%H:%M:%S")
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
                                lambda e, u=url: webbrowser.open(u))
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
        """User clicked Cancel: disable BOTH cancel buttons (one press is
        enough — the press cancels the running job and every queued follow-up)
        and show feedback.  The action buttons stay disabled; they're re-enabled
        only when the job actually stops, via ``set_running(False)``."""
        # The single Extract / Build buttons are showing "Cancel" right now —
        # freeze both and flag the in-progress stop; set_running(False)
        # restores their idle labels.
        self._extract_btn.configure(state=tk.DISABLED, text="Cancelling…")
        self._write_btn.configure(state=tk.DISABLED, text="Cancelling…")
        self.set_status("Cancelling...")

    def set_running(self, running, mode="extract"):
        # Authoritative run flag (read by _is_running()); set before any widget
        # state so a re-entrant refresh sees the right value.
        self._running = running
        if running:
            # New run → new namespace for in-place keyed log lines.
            self._log_line_run += 1
            # (Re-theming is a heavy synchronous re-style; the ⚙ menu greys
            # out its theme entry while running so clicks can't queue up.)
            self._set_extract_button_running(True)
            self._set_write_button_running(True)
            if hasattr(self, "_revert_all_btn"):
                self._revert_all_btn.configure(state=tk.DISABLED)
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
            # Revert button tracks the change count, not a blanket re-enable —
            # disabled when there's nothing to revert (see _update_revert_btn_state).
            self._update_revert_btn_state()
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
        # Download button — opens the release page in the browser.
        # tk.Button (not ttk) so its bg color sticks; ttk's themed
        # blue would clash with the banner background on light mode.
        tk.Button(
            self._update_banner, text="Download",
            bg="#3794ff", fg="#ffffff",
            activebackground="#5fa5ff", activeforeground="#ffffff",
            relief="flat", padx=10, pady=2, borderwidth=0,
            cursor="hand2",
            command=self._open_update_url,
        ).pack(side=tk.LEFT, padx=4, pady=4)
        # Dismiss × — closes the banner for this session.
        tk.Button(
            self._update_banner, text="✕",
            bg="#1e4a8a", fg="#ffffff",
            activebackground="#3a5a8a", activeforeground="#ffffff",
            relief="flat", padx=6, pady=2, borderwidth=0,
            cursor="hand2",
            command=self._dismiss_update_banner,
        ).pack(side=tk.LEFT, padx=(0, 6), pady=4)
        # The URL to open when the Download button is clicked.
        # Populated by show_update_banner.
        self._update_banner_url = None

    def show_update_banner(self, version, url):
        """Display the 'update available' banner.

        Called from :meth:`App._check_for_update` on the main thread
        (via ``root.after(0, ...)``) when the GitHub release feed
        reports a newer version.  Idempotent — re-calling with the
        same args just re-shows / updates the banner; the user can
        still dismiss it after.
        """
        from pinball_decryptor import __version__ as _current
        self._update_banner_url = url
        # The gear carries a ● notification too, so the news survives a
        # dismissed banner (its menu gets a "Download update…" entry).
        self._update_available = (version, url)
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
        if not self._update_banner_url:
            return
        import webbrowser
        webbrowser.open(self._update_banner_url)

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
        tk.Button(
            self._stale_source_banner, text="✕",
            bg="#5a4416", fg="#ffffff",
            activebackground="#6a5426", activeforeground="#ffffff",
            relief="flat", padx=6, pady=2, borderwidth=0,
            cursor="hand2",
            command=self._dismiss_stale_source_banner,
        ).pack(side=tk.LEFT, padx=(0, 6), pady=4)
        # The warning text the user dismissed; suppresses re-show until the
        # staleness clears (re-Extract) and recurs.
        self._stale_source_dismissed_msg = None

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
            self._stale_source_dismissed_msg = None
        show = bool(on_asset_tab and stale
                    and stale != self._stale_source_dismissed_msg)
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
        """Hide the banner for this session (until the staleness recurs)."""
        self._stale_source_dismissed_msg = (
            self._stale_source_banner_text.cget("text"))
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
        style.configure("TLabelframe", background=c["bg"], foreground=c["fg"])
        style.configure("TLabelframe.Label", background=c["bg"],
                        foreground=c["fg"])
        style.configure("TButton", background=c["button"], foreground=c["fg"])
        style.map("TButton",
                  background=[("active", c["accent"]), ("pressed", c["accent"])],
                  foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])
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

        # Header icon buttons ("?" tips + gear settings) — one shared style
        # so they render pixel-identical (David); on Windows both glyphs come
        # from Segoe MDL2 Assets.  Negative font size = pixels, keeping the
        # two fonts' line heights equal.  Hover matches every other button's
        # accent-blue treatment.
        icon_font = (("Segoe MDL2 Assets", -14) if sys.platform == "win32"
                     else (_SANS_FONT, -14))
        style.configure("Icon.TButton", font=icon_font, padding=(4, 3),
                        foreground=c["fg"], background=c["button"])
        style.map("Icon.TButton",
                  background=[("active", c["accent"]),
                              ("pressed", c["accent"])],
                  foreground=[("active", "#ffffff"),
                              ("pressed", "#ffffff")])

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
