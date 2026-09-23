""""From a film" for the web Modes tab: the Tk-free half of ``gui/film_cut_dialog.py``.

:class:`FilmCutForm` (the dialog's state and logic: the film, a start time, a length up to
30 s, the crop, what to take, a separate span for the sound, the picture's time),
:func:`stage_folder`, :func:`commit_cut`, :func:`discard_stage` and :func:`describe` are
moved here UNCHANGED from the Tk dialog module, whose file goes with the Tk code at the
cut-over. The work itself is :mod:`..plugins.stern.film_cut`'s; the page's dialog is
``static/js/tabs/modes_film.js`` and the service's ``film_*`` calls (tabs/modes.py).

The mode keeps the CUT (``clip.mp4``, ``end.wav``, ``art.png``), never the film.
"""

import copy
import os
import shutil
import tempfile
import threading

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
