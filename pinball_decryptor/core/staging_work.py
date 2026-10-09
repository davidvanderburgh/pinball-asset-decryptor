"""How much converting a staging pass has ahead of it, about how long that
takes, and the words for it while it runs (PAD-489).

DragonRR, Emulate with a color profile on every picture and clip of the game:
"I have no sign of a progress bar, no warning that there are a huge number of
files to process and it will take a long time".  Staging bakes the profile
into each of the game's own clips with one ffmpeg encode apiece, about a
second each for Godzilla's 1360x768 clips on a 16-core PC, so the game's 658
clips are a quarter of an hour - and the Emulate tab said "Applying your
replacements..." for all of it, with an empty bar.

Three pieces.  :class:`Work` is what a staging pass will really convert (a
clip the staging cache keeps is not counted: see
:func:`core.video_slots.conversions_due`).  :func:`estimate` prices it from a
model of one conversion, scaled by what this PC measured the last time
(:func:`remember`).  :class:`Tracker` turns the staging's own
``progress_cb(i, total, rel)`` calls into the words and the percentage a tab
shows, with the time left measured as it goes.
"""

import json
import os
import time
from dataclasses import dataclass, field

#: One clip conversion: a fixed part (ffmpeg starting, the probes, the
#: ``.orig/`` copy) and a part per pixel of every frame encoded.  Staging 40
#: Godzilla clips with a color profile on a 16-core PC took 1.16 s a clip,
#: about 220 million pixels a second all in; the rate here is a little slower
#: than that, for a PC with fewer cores.  :func:`remember` corrects it.
CLIP_FIXED_S = 0.3
CLIP_PIXELS_PER_S = 200e6
#: A clip whose size could not be read is priced as an average Godzilla one
#: (1360x768 at 30 fps, 8 s).
CLIP_PIXELS_UNKNOWN = 1360 * 768 * 30 * 8
#: One picture (read, the profile, a PNG written): ~10 ms measured.
PICTURE_S = 0.02
#: Worth asking before it starts: a pass that converts clips and is
#: estimated to take this long (seconds).
ASK_FROM_S = 60.0
#: The measured time left takes over from the estimate once this many clips
#: were converted, or this many seconds were spent on them.
_MEASURED_AFTER = (3, 10.0)


@dataclass
class Work:
    """What a staging pass converts: *clips* ``{rel: pixels}`` (frames x
    width x height of the clip, 0 when it could not be read), *coloured* the
    rels among them that get a color profile baked in, and how many
    *pictures*."""
    clips: dict = field(default_factory=dict)
    coloured: frozenset = frozenset()
    pictures: int = 0

    def __bool__(self):
        return bool(self.clips or self.pictures)

    def says(self):
        """``"658 videos and 5,813 pictures"`` (either may be absent)."""
        parts = []
        if self.clips:
            parts.append(_count(len(self.clips), "video"))
        if self.pictures:
            parts.append(_count(self.pictures, "picture"))
        return " and ".join(parts)


def _count(n, noun):
    return "{:,} {}{}".format(n, noun, "" if n == 1 else "s")


def clip_seconds(pixels):
    """The model's seconds for converting one clip of *pixels*."""
    return CLIP_FIXED_S + (pixels or CLIP_PIXELS_UNKNOWN) / CLIP_PIXELS_PER_S


def estimate(work, factor=None):
    """About how many seconds converting *work* takes on this PC."""
    f = speed_factor() if factor is None else factor
    return (f * sum(clip_seconds(px) for px in work.clips.values())
            + work.pictures * PICTURE_S)


def say_time(seconds):
    """``"about 17 minutes"``, ``"about 1 hour 20 minutes"``, ``"less than a
    minute"``: an estimate's words, never more exact than it is."""
    if seconds < 50:
        return "less than a minute"
    minutes = int(round(seconds / 60.0))
    if minutes <= 1:
        return "about a minute"
    if minutes < 60:
        return "about %d minutes" % minutes
    minutes = int(round(minutes / 5.0)) * 5
    hours, rest = divmod(minutes, 60)
    text = "about %d hour%s" % (hours, "" if hours == 1 else "s")
    return text + (" %d minutes" % rest if rest else "")


# -- this PC's own speed ------------------------------------------------------

def _speed_path():
    from . import config
    return os.path.join(os.path.dirname(config.SETTINGS_FILE),
                        "conversion_speed.json")


def speed_factor():
    """How much slower (above 1) or faster than the model this PC converted
    clips the last time it did, 1.0 before it ever has."""
    try:
        with open(_speed_path(), encoding="utf-8") as f:
            value = float(json.load(f).get("clip_factor"))
    except (OSError, ValueError, TypeError, AttributeError):
        return 1.0
    return min(max(value, 0.1), 20.0) if value > 0 else 1.0


def remember(spent, modelled):
    """A pass spent *spent* seconds on clips the model priced at *modelled*
    (unscaled): the next estimate on this PC goes halfway to that measure.
    Too little to go by (under 5 s of either) is not remembered."""
    if spent < 5.0 or modelled < 5.0:
        return
    measured = spent / modelled
    path = _speed_path()
    if os.path.isfile(path):
        measured = (measured + speed_factor()) / 2.0
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"clip_factor": round(measured, 3)}, f)
        os.replace(tmp, path)
    except OSError:
        pass


# -- a pass under way -----------------------------------------------------------

class Tracker:
    """The words for a staging pass under way.  Fed the staging's own
    ``progress_cb(i, total, rel)`` calls kind by kind (``"videos"``, then
    ``"pictures"``), :meth:`step` says how many are done, about how long is
    left, and how far through the whole pass it is.  :meth:`finish` hands
    what the clips really took to :func:`remember`."""

    def __init__(self, work, factor=None, clock=time.monotonic):
        self.work = work
        self._f = speed_factor() if factor is None else factor
        self._clock = clock
        self._clip_est = {rel: self._f * clip_seconds(px)
                          for rel, px in work.clips.items()}
        self._total = (sum(self._clip_est.values())
                       + work.pictures * PICTURE_S) or 1.0
        self._now = None              # (kind, rel, started) of the item under way
        self._clips_done = 0
        self._clips_left = sum(self._clip_est.values())
        self._clip_spent = 0.0        # measured seconds of the clips converted
        self._clip_priced = 0.0       # what the model said they would take
        self._pics_done = 0
        self._pic_spent = 0.0

    def step(self, kind, i, total, rel=""):
        """Item *i* of *total* of *kind* (*rel*) starts now; ``i == total``
        is the end of that kind.  Returns ``(text, percent)``."""
        now = self._clock()
        self._close(now)
        if i < total:
            self._now = (kind, rel, now)
        pct = int(min(99, 100.0 * self._done() / self._total))
        if kind == "videos" and self.work.clips:
            done = min(self._clips_done, len(self.work.clips))
            text = "Converting videos: {:,} of {:,}".format(
                done, len(self.work.clips))
        elif kind == "videos":
            text = "Checking videos: {:,} of {:,}".format(min(i, total), total)
        else:
            text = "Converting pictures: {:,} of {:,}".format(
                min(i, total), total)
        left = self.left()
        if left is not None and i < total:
            text += " (%s left)" % say_time(left)
        return text, pct

    def _close(self, now):
        """The item that was under way is done."""
        if self._now is None:
            return
        kind, rel, started = self._now
        self._now = None
        if kind == "videos" and rel in self._clip_est:
            est = self._clip_est[rel]
            self._clips_done += 1
            self._clips_left -= est
            self._clip_spent += now - started
            self._clip_priced += est
        elif kind == "pictures":
            self._pics_done += 1
            self._pic_spent += now - started

    def _done(self):
        return (self._total - self._clips_left
                - max(self.work.pictures - self._pics_done, 0) * PICTURE_S)

    def left(self):
        """About how many seconds are left: the model's figure, scaled by
        what the clips converted so far really took once there are enough
        of them to go by."""
        clips = max(self._clips_left, 0.0)
        if (self._clips_done >= _MEASURED_AFTER[0]
                or self._clip_spent >= _MEASURED_AFTER[1]) \
                and self._clip_priced > 0:
            clips *= self._clip_spent / self._clip_priced
        pics_left = max(self.work.pictures - self._pics_done, 0)
        per_pic = (self._pic_spent / self._pics_done
                   if self._pics_done >= 50 else PICTURE_S)
        return clips + pics_left * per_pic

    def finish(self):
        """The pass is over (done, cancelled or failed): what its clips
        took goes into this PC's speed."""
        self._close(self._clock())
        if self._f > 0:
            remember(self._clip_spent, self._clip_priced / self._f)
