""""From a film" - cut a mode's clip, sound and picture from a film (item 142).

:class:`FilmCutForm` is everything the dialog decides, with no Tk in it: the film, a start
time (m:ss), a length (up to 30 s), the crop (keep the letterbox or fill the frame), what
to take (the clip, its sound, a picture), a separate span for the sound, the picture's
time; :meth:`FilmCutForm.problems` names what is wrong, :meth:`FilmCutForm.preview` draws
the frame at the start as the clip will show it, and :meth:`FilmCutForm.apply` cuts into
the mode's folder (:mod:`..plugins.stern.film_cut`) and returns what the mode now uses
plus where each cut came from. The mode keeps the CUT (``clip.mp4``, ``end.wav``,
``art.png``), never the film.

:class:`FilmCutDialog` is a thin view over a form. Probing a film, drawing a preview and
cutting all read a 3 GB file on a drive that may be asleep, so every one runs on a worker
thread whose answer a main-thread ``after()`` timer drains (the UI-thread freeze class:
never on the Tk thread, and a worker never touches Tk). Each worker gets a SNAPSHOT of the
form, so an edit while it runs cannot change what it does. The dialog's cut is made in a
staging folder and moved into the mode's folder only if the dialog is still open
(:func:`stage_folder`, :func:`commit_cut`): Cancel during a cut leaves the mode as it was.
"""

import copy
import os
import queue
import shutil
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from ..plugins.stern import film_cut as FC

CLIP_NAME = "clip.mp4"
SOUND_NAME = "end.wav"
ART_NAME = "art.png"
TAKES = ("clip", "sound", "still")
PROVENANCE = ("clip_source", "clip_from", "clip_length", "sound_source", "sound_from",
              "sound_length", "art_source", "art_from", "clip_crop", "art_crop")
CUT_FILES = ("clip_file", "end_sound", "screen_art")
STAGE_PREFIX = "pad-film-cut-"
FILM_TYPES = [("Films", "*.mp4 *.mkv *.mov *.m4v *.avi *.webm *.ts"), ("All files", "*.*")]


def _secs_text(x):
    return ("%.3f" % float(x)).rstrip("0").rstrip(".")


def short_name(name, limit=44):
    """A film's file name cut to ``limit`` characters for a label, keeping its extension."""
    if len(name) <= limit:
        return name
    stem, ext = os.path.splitext(name)
    return stem[:max(8, limit - len(ext) - 1)] + "…" + ext


class FilmCutForm:
    """The dialog's state and logic. Times are TEXT, as typed."""

    def __init__(self, film="", start="0:00", length="6", crop="letterbox", take_clip=True,
                 take_sound=False, take_still=False, sound_same=True, sound_start="",
                 sound_length="", still_at="", channels=1):
        self.film = film
        self.start = start
        self.length = length
        self.crop = crop
        self.take_clip = take_clip
        self.take_sound = take_sound
        self.take_still = take_still
        self.sound_same = sound_same
        self.sound_start = sound_start
        self.sound_length = sound_length
        self.still_at = still_at
        self.channels = channels             # a mode's own sound record is mono
        # what the film is, found once per file; SHARED by every snapshot of this form, and
        # the lock makes a second worker wait for the first one's answer instead of
        # probing the same film again
        self._cache = {}
        self._lock = threading.RLock()

    def snapshot(self):
        """A copy of the form as it is now, for a worker: later edits to this form do not
        reach it. It shares this form's probe cache."""
        return copy.copy(self)

    @classmethod
    def from_spec(cls, spec, take="clip"):
        """A form for ``spec``, opened on the film, times and crop its cut of ``take`` last
        came from (the other cuts' when ``take`` was never cut), with only ``take`` ticked."""
        cuts = {"clip": (spec.clip_source, spec.clip_from, spec.clip_length,
                         getattr(spec, "clip_crop", "")),
                "sound": (spec.sound_source, spec.sound_from, spec.sound_length, ""),
                "still": (spec.art_source, spec.art_from, None, getattr(spec, "art_crop", ""))}
        order = [take if take in cuts else "clip"]
        order += [k for k in TAKES if k not in order]
        film, start, length, crop = "", "0:00", "6", ""
        for kind in order:
            source, at, secs, _crop = cuts[kind]
            if source:
                film, start = source, FC.format_time(at or 0)
                if secs:
                    length = _secs_text(secs)
                break
        for kind in order:                   # the crop the opened cut used, else another's
            if cuts[kind][0] and cuts[kind][3] in FC.CROPS:
                crop = cuts[kind][3]
                break
        return cls(film=film, start=start, length=length, crop=crop or "letterbox",
                   take_clip=take == "clip", take_sound=take == "sound", take_still=take == "still",
                   still_at=FC.format_time(spec.art_from) if spec.art_source and take == "still" else "")

    # ---- the film -------------------------------------------------------------------
    def _probed(self):
        path = (self.film or "").strip()
        try:
            key = (path, os.path.getsize(path), os.path.getmtime(path))
        except OSError:
            key = (path, None, None)
        with self._lock:
            hit = self._cache.get("info")
            if hit is None or hit[0] != key:
                hit = (key, FC.probe(path))
                self._cache["info"] = hit
            return hit

    def info(self):
        """The film's :class:`film_cut.FilmInfo`, probed once per file. Raises
        :class:`film_cut.FilmCutError`."""
        return self._probed()[1]

    def picture(self, ffmpeg=None):
        """The film's picture inside black bars burned into its frame, ``(w, h, x, y)``, or
        None; found once per file (:func:`film_cut.detect_picture`)."""
        with self._lock:
            key, info = self._probed()
            hit = self._cache.get("picture")
            if hit is None or hit[0] != key:
                hit = (key, FC.detect_picture(info.path, ffmpeg, duration=info.duration))
                self._cache["picture"] = hit
            return hit[1]

    def describe_film(self, ffmpeg=None):
        """The dialog's line about the film: its frame, length and sound, and its bars."""
        text = self.info().summary()
        pic = self.picture(ffmpeg)
        if pic:
            text += "; the picture is %dx%d inside black bars, which every cut leaves out" % pic[:2]
        return text

    # ---- the spans ---------------------------------------------------------------------
    def _time(self, text, label, out, default=None):
        if default is not None and not str(text or "").strip():
            return default
        try:
            return FC.parse_time(text)
        except FC.FilmCutError as e:
            out.append("%s: %s" % (label, e))
            return None

    def spans(self):
        """``(problems, {"clip": (start, length), "sound": (start, length), "still": at})``
        for what is taken, without touching the film."""
        out, spans = [], {}
        start = self._time(self.start, "Start", out)
        length = self._time(self.length, "Length", out)
        if self.take_clip and start is not None and length is not None:
            spans["clip"] = (start, length)
        if self.take_sound:
            if self.sound_same:
                if start is not None and length is not None:
                    spans["sound"] = (start, length)
            else:
                s = self._time(self.sound_start, "Sound start", out)
                n = self._time(self.sound_length, "Sound length", out)
                if s is not None and n is not None:
                    spans["sound"] = (s, n)
        if self.take_still and start is not None:
            at = self._time(self.still_at, "Picture at", out, default=start)
            if at is not None:
                spans["still"] = at
        return out, spans

    def problems(self):
        """Everything that stops the cut, as sentences. Empty = ready. Probes the film."""
        if not (self.film or "").strip():
            return ["Choose a film."]
        if not (self.take_clip or self.take_sound or self.take_still):
            return ["Tick at least one of the clip, the sound and the picture."]
        if self.crop not in FC.CROPS:
            return ["The crop is letterbox or fill."]
        out, spans = self.spans()
        try:
            info = self.info()
        except FC.FilmCutError as e:
            return out + [str(e)]
        for label, key in (("The clip", "clip"), ("The sound", "sound")):
            if key in spans:
                out += ["%s: %s" % (label, p) for p in FC.span_problems(*spans[key], duration=info.duration)]
        if "sound" in spans and not info.has_audio:
            out.append("The film has no sound to cut.")
        if "still" in spans and info.duration and spans["still"] >= info.duration:
            out.append("The picture: the film is only %s long." % FC.format_time(info.duration))
        return out

    # ---- doing it ----------------------------------------------------------------------
    def preview(self, ffmpeg=None, box=(480, 270)):
        """The frame at the start, as the clip will show it (the crop applied)."""
        problems, _spans = self.spans()
        if problems:
            raise FC.FilmCutError(" ".join(problems))
        return FC.preview_frame(self.film, FC.parse_time(self.start), ffmpeg, box=box, crop=self.crop,
                                picture=self.picture(ffmpeg))

    def apply(self, mode_folder, ffmpeg=None):
        """Cut what is taken into ``mode_folder``. Returns the mode's new keys (``clip_file``,
        ``end_sound``, ``screen_art``), where each came from (:data:`PROVENANCE`), the
        ``mode_folder`` and a ``summary`` sentence. Raises :class:`film_cut.FilmCutError`
        naming every problem, before anything is written."""
        problems = self.problems()
        if problems:
            raise FC.FilmCutError(" ".join(problems))
        _p, spans = self.spans()
        os.makedirs(mode_folder, exist_ok=True)
        film = os.path.abspath(self.film.strip())
        picture = self.picture(ffmpeg) if ("clip" in spans or "still" in spans) else None
        result = {"mode_folder": mode_folder}
        if "clip" in spans:
            start, length = spans["clip"]
            FC.cut_clip(film, start, length, os.path.join(mode_folder, CLIP_NAME), ffmpeg, crop=self.crop,
                        picture=picture)
            result.update(clip_file=CLIP_NAME, clip_source=film, clip_from=start, clip_length=length,
                          clip_crop=self.crop)
        if "sound" in spans:
            start, length = spans["sound"]
            cut = FC.cut_sound(film, start, length, os.path.join(mode_folder, SOUND_NAME), ffmpeg,
                               channels=self.channels)
            result.update(end_sound=SOUND_NAME, sound_source=film, sound_from=start, sound_length=length,
                          sound_gain_db=round(cut.gain_db, 1), sound_limited=cut.limited)
        if "still" in spans:
            FC.grab_still(film, spans["still"], os.path.join(mode_folder, ART_NAME), ffmpeg, crop=self.crop,
                          picture=picture)
            result.update(screen_art=ART_NAME, art_source=film, art_from=spans["still"], art_crop=self.crop)
        result["summary"] = describe(result)
        return result


def stage_folder():
    """A new, empty folder a dialog's cut is made in before it joins the mode (the
    system's temporary folder, so a crash never leaves a half cut in a project)."""
    return tempfile.mkdtemp(prefix=STAGE_PREFIX)


def commit_cut(result, mode_folder):
    """Move a cut :meth:`FilmCutForm.apply` made in a staging folder (its
    ``result["mode_folder"]``) into ``mode_folder``, each file landing whole (a rename, or
    a copy to ``.part`` and a rename when the staging folder is on another drive).
    Returns the result, now naming ``mode_folder``. Raises :class:`film_cut.FilmCutError`
    when that folder is gone (the mode was deleted during the cut): the cut is not kept."""
    stage = result["mode_folder"]
    if not os.path.isdir(mode_folder):
        raise FC.FilmCutError("The mode was deleted while the cut was made, so the cut was not kept.")
    for key in CUT_FILES:
        name = result.get(key)
        if not name:
            continue
        src, dst = os.path.join(stage, name), os.path.join(mode_folder, name)
        try:
            os.replace(src, dst)
        except OSError:
            part = dst + ".part"
            try:
                shutil.copyfile(src, part)
                os.replace(part, dst)
            except OSError:
                try:
                    os.remove(part)
                except OSError:
                    pass
                raise
    return dict(result, mode_folder=mode_folder)


def discard_stage(stage):
    """Remove a staging folder and whatever is left in it."""
    if stage and os.path.basename(os.path.normpath(stage)).startswith(STAGE_PREFIX):
        shutil.rmtree(stage, ignore_errors=True)


def describe(spec):
    """One plain line naming what was cut from where, for a spec or a result dict; ""
    when nothing was. A cut the mode no longer uses (the clip set to a title card, the
    game's own call instead of the sound, a generated panel) is left out."""
    get = spec.get if isinstance(spec, dict) else (lambda k, d=None: getattr(spec, k, d))
    in_use = {"Clip": get("clip", "file") == "file" and bool(get("clip_file")),
              "Sound": bool(get("end_sound")), "Picture": bool(get("screen_art"))}
    parts, films = [], []
    for noun, source, start, length in (("Clip", "clip_source", "clip_from", "clip_length"),
                                        ("Sound", "sound_source", "sound_from", "sound_length"),
                                        ("Picture", "art_source", "art_from", None)):
        film = get(source) or ""
        if not film or not in_use[noun]:
            continue
        name = os.path.basename(str(film).replace("\\", "/"))
        if name not in films:
            films.append(name)
        at = FC.format_time(get(start) or 0)
        if length:
            parts.append("%s: %s s from %s" % (noun, _secs_text(get(length) or 0), at))
        else:
            parts.append("%s: the frame at %s" % (noun, at))
    if not parts:
        return ""
    return "%s. Cut from %s." % (". ".join(parts), " and ".join(short_name(f) for f in films))


class _CutJob:
    """A dialog cut's state, shared by the Tk thread and the cut's worker:
    None, ``cutting``, ``committing`` (being moved into the mode) or ``cancelled``."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = None


class FilmCutDialog:
    """The "From a film" dialog over a :class:`FilmCutForm`. ``on_done(result)`` is called
    on the Tk thread after a successful cut, whose files are then in the mode's folder.

    Closing the dialog (Cancel, Escape, the window's X) during a cut abandons the cut:
    nothing reaches the mode's folder. Only a cut already being moved in when the dialog
    closed still lands, and then ``on_done`` still runs, so the mode's file always names
    what its folder holds."""

    POLL_MS = 80
    PREVIEW_BOX = (480, 270)

    def __init__(self, parent, theme_name, form, mode_folder, on_done, ffmpeg_fn=None, title=None):
        from .theme import THEMES, dark_titlebar
        self._parent = parent
        self._theme = THEMES.get(theme_name) or THEMES["dark"]
        self.form = form
        self._mode_folder = mode_folder
        self._on_done = on_done
        self._ffmpeg_fn = ffmpeg_fn
        self._q = queue.Queue()
        self._tokens = {}                    # kind -> the newest request of that kind
        self._busy = False
        self._closed = False
        # the cut's state, shared with its worker. A worker holds only plain objects like
        # this one, never the dialog: the last reference to a Tk variable dropped on a
        # worker thread is freed there, and Tk must only ever be called from its own thread.
        self._cut_job = _CutJob()
        self._preview_img = None
        self._poll_job = None
        dlg = tk.Toplevel(parent)
        self.win = dlg
        dlg.withdraw()
        dlg.title(title or "Cut from a film")
        dlg.configure(bg=self._theme["bg"])
        dark_titlebar(dlg, self._theme is THEMES["dark"])
        dlg.transient(parent)
        dlg.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._center()
        dlg.bind("<Escape>", lambda _e: self.close())
        dlg.deiconify()
        dlg.lift()
        # the timer lives on the PARENT: a cut being moved in when the dialog closes still
        # has to reach on_done after the dialog's own window is gone
        self._poll_job = parent.after(self.POLL_MS, self._drain)
        if form.film:
            self._probe()

    # ---- the widgets ----------------------------------------------------------------
    def _build(self):
        f = self.form
        body = ttk.Frame(self.win, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)
        self.v = {
            "film": tk.StringVar(value=f.film), "start": tk.StringVar(value=f.start),
            "length": tk.StringVar(value=f.length), "crop": tk.StringVar(value=f.crop),
            "take_clip": tk.BooleanVar(value=f.take_clip), "take_sound": tk.BooleanVar(value=f.take_sound),
            "take_still": tk.BooleanVar(value=f.take_still),
            "sound_same": tk.StringVar(value="same" if f.sound_same else "other"),
            "sound_start": tk.StringVar(value=f.sound_start), "sound_length": tk.StringVar(value=f.sound_length),
            "still_at": tk.StringVar(value=f.still_at),
        }
        ttk.Label(body, text="Film").grid(row=0, column=0, sticky=tk.W, pady=2)
        e = ttk.Entry(body, textvariable=self.v["film"], width=64)
        e.grid(row=0, column=1, sticky=tk.EW, padx=6, pady=2)
        e.bind("<Return>", lambda _e: self._probe())
        e.bind("<FocusOut>", lambda _e: self._probe())
        ttk.Button(body, text="Choose…", command=self._choose).grid(row=0, column=2, sticky=tk.W)
        self._info = ttk.Label(body, text="", foreground=self._theme["gray"], wraplength=560,
                               justify=tk.LEFT)
        self._info.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=6)

        ttk.Label(body, text="Start at").grid(row=2, column=0, sticky=tk.W, pady=2)
        span = ttk.Frame(body)
        span.grid(row=2, column=1, columnspan=2, sticky=tk.W, padx=6)
        ttk.Entry(span, textvariable=self.v["start"], width=10).pack(side=tk.LEFT)
        ttk.Label(span, text="(m:ss)   for").pack(side=tk.LEFT, padx=(4, 4))
        ttk.Spinbox(span, from_=1, to=int(FC.MAX_SECONDS), width=5,
                    textvariable=self.v["length"]).pack(side=tk.LEFT)
        ttk.Label(span, text="seconds (up to %d)" % FC.MAX_SECONDS).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(body, text="Crop").grid(row=3, column=0, sticky=tk.W, pady=2)
        crop = ttk.Frame(body)
        crop.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=6)
        ttk.Radiobutton(crop, text="Keep the letterbox", value="letterbox",
                        variable=self.v["crop"]).pack(side=tk.LEFT)
        ttk.Radiobutton(crop, text="Fill the frame", value="fill",
                        variable=self.v["crop"]).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(body, text="Take").grid(row=4, column=0, sticky=tk.W, pady=2)
        take = ttk.Frame(body)
        take.grid(row=4, column=1, columnspan=2, sticky=tk.W, padx=6)
        ttk.Checkbutton(take, text="The clip", variable=self.v["take_clip"]).pack(side=tk.LEFT)
        ttk.Checkbutton(take, text="The sound", variable=self.v["take_sound"]).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Checkbutton(take, text="A picture", variable=self.v["take_still"]).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(body, text="Sound").grid(row=5, column=0, sticky=tk.W, pady=2)
        snd = ttk.Frame(body)
        snd.grid(row=5, column=1, columnspan=2, sticky=tk.W, padx=6)
        ttk.Radiobutton(snd, text="The same span", value="same", variable=self.v["sound_same"]).pack(side=tk.LEFT)
        ttk.Radiobutton(snd, text="From", value="other", variable=self.v["sound_same"]).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Entry(snd, textvariable=self.v["sound_start"], width=10).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(snd, text="for").pack(side=tk.LEFT, padx=4)
        ttk.Entry(snd, textvariable=self.v["sound_length"], width=5).pack(side=tk.LEFT)
        ttk.Label(snd, text="seconds").pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(body, text="Picture at").grid(row=6, column=0, sticky=tk.W, pady=2)
        pic = ttk.Frame(body)
        pic.grid(row=6, column=1, columnspan=2, sticky=tk.W, padx=6)
        ttk.Entry(pic, textvariable=self.v["still_at"], width=10).pack(side=tk.LEFT)
        ttk.Label(pic, text="(empty = the start)").pack(side=tk.LEFT, padx=(4, 0))

        prev = ttk.Frame(body)
        prev.grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=(8, 2))
        self._preview_btn = ttk.Button(prev, text="Preview the start", command=self._preview)
        self._preview_btn.pack(side=tk.LEFT, anchor=tk.N)
        w, h = FC.preview_size(self.PREVIEW_BOX)
        holder = tk.Frame(prev, width=w, height=h, bg="#000000")
        holder.pack(side=tk.LEFT, padx=(10, 0))
        holder.pack_propagate(False)
        self._preview_label = tk.Label(holder, bg="#000000", fg=self._theme["gray"],
                                       text="The frame at the start shows here.")
        self._preview_label.pack(fill=tk.BOTH, expand=True)

        self._status = ttk.Label(body, text="The mode keeps only the cut, never the film.",
                                 wraplength=620, justify=tk.LEFT)
        self._status.grid(row=8, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))
        btns = ttk.Frame(body)
        btns.grid(row=9, column=0, columnspan=3, sticky=tk.E, pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.close).pack(side=tk.RIGHT)
        self._ok = ttk.Button(btns, text="Cut", command=self._cut)
        self._ok.pack(side=tk.RIGHT, padx=(0, 8))

    def _center(self):
        from .placement import centered_over
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x, y = centered_over(self._parent, w, h)
        # position only: the film line wraps once the probe answers, and a fixed size
        # would cut the buttons off
        self.win.geometry("+%d+%d" % (x, y))

    def sync(self):
        """Copy the widgets into the form."""
        f, v = self.form, self.v
        f.film = v["film"].get().strip()
        for key in ("start", "length", "crop", "sound_start", "sound_length", "still_at"):
            setattr(f, key, v[key].get())
        for key in ("take_clip", "take_sound", "take_still"):
            setattr(f, key, bool(v[key].get()))
        f.sound_same = v["sound_same"].get() == "same"
        return f

    def _say(self, text, error=False):
        self._status.configure(text=text, foreground=self._theme["error"] if error else self._theme["fg"])

    # ---- the workers ----------------------------------------------------------------
    def _run(self, kind, fn):
        """Run ``fn`` on a worker; its answer comes back through the queue, tagged with a
        token PER KIND, so only an answer superseded by a newer request of the same kind
        (an older probe, an older preview) is dropped."""
        token = self._tokens.get(kind, 0) + 1
        self._tokens[kind] = token
        q = self._q

        def work():
            try:
                q.put((kind, token, True, fn()))
            except Exception as e:              # every failure is reported, never raised in Tk
                q.put((kind, token, False, e))
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        return thread

    def _ffmpeg(self):
        """The function a worker calls for ffmpeg (a plain function, not the dialog)."""
        if self._ffmpeg_fn is not None:
            return self._ffmpeg_fn
        from ..core.audio import find_ffmpeg
        return find_ffmpeg

    def _drain(self):
        self._poll_job = None
        try:
            while True:
                kind, token, ok, value = self._q.get_nowait()
                if kind == "cut":
                    self._cut_done(ok, value)
                elif not self._closed and token == self._tokens.get(kind):
                    getattr(self, "_%s_done" % kind)(ok, value)
        except queue.Empty:
            pass
        if self._closed and self._cut_job.state != "committing":
            return                              # closed, and nothing still owed to on_done
        try:
            self._poll_job = self._parent.after(self.POLL_MS, self._drain)
        except tk.TclError:
            self._poll_job = None

    def _choose(self):
        start = os.path.dirname(self.v["film"].get()) or None
        path = filedialog.askopenfilename(title="Choose a film", filetypes=FILM_TYPES,
                                          initialdir=start, parent=self.win)
        if path:
            self.v["film"].set(path)
            self._probe()

    def _probe(self):
        if self._closed:                    # a FocusOut can arrive while the window goes
            return
        form = self.sync().snapshot()
        if not form.film:
            return
        self._info.configure(text="Reading the film…")
        ffmpeg = self._ffmpeg()
        self._run("probe", lambda: form.describe_film(ffmpeg()))

    def _probe_done(self, ok, value):
        self._info.configure(text=value if ok else str(value))

    def _preview(self):
        if self._closed:
            return
        form = self.sync().snapshot()
        self._say("Drawing the frame at the start…")
        ffmpeg, box = self._ffmpeg(), self.PREVIEW_BOX
        self._run("preview", lambda: (form.start.strip(), form.preview(ffmpeg(), box)))

    def _preview_done(self, ok, value):
        if not ok:
            self._say(str(value), error=True)
            return
        start, image = value
        try:
            from PIL import ImageTk
            self._preview_img = ImageTk.PhotoImage(image)
            self._preview_label.configure(image=self._preview_img, text="")
            self._say("The frame at %s, as the clip will show it." % start)
        except (tk.TclError, ImportError) as e:
            self._say("No preview: %s" % e, error=True)

    def _cut(self):
        if self._busy or self._closed:
            return None
        form = self.sync().snapshot()
        self._busy = True
        job = self._cut_job
        with job.lock:
            job.state = "cutting"
        self._ok.configure(state=tk.DISABLED)
        self._say("Cutting… a clip takes a few seconds.")
        folder, ffmpeg = self._mode_folder, self._ffmpeg()

        def cut():
            stage = stage_folder()
            try:
                result = form.apply(stage, ffmpeg())
                with job.lock:
                    if job.state == "cancelled":
                        return None                 # the dialog closed: nothing reaches the mode
                    job.state = "committing"
                return commit_cut(result, folder)
            finally:
                discard_stage(stage)
        return self._run("cut", cut)

    def _cut_done(self, ok, value):
        with self._cut_job.lock:
            state, self._cut_job.state = self._cut_job.state, None
        self._busy = False
        if self._closed:
            # closed during the cut: only a cut already moved in is owed to on_done
            if ok and value is not None and state == "committing" and self._on_done is not None:
                self._on_done(value)
            return
        try:
            self._ok.configure(state=tk.NORMAL)
        except tk.TclError:
            return
        if not ok:
            self._say(str(value), error=True)
            return
        self.close()
        if self._on_done is not None:
            self._on_done(value)

    def close(self):
        """Close the dialog. A cut still being made is abandoned (see the class)."""
        job = self._cut_job
        with job.lock:
            if job.state == "cutting":
                job.state = "cancelled"
            owed = job.state == "committing"
        self._closed = True
        if self._poll_job is not None and not owed:
            try:
                self._parent.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
