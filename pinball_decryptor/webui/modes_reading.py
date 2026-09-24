"""Reading a card's game build for the web Modes tab, on a worker, with progress and Cancel.

Which game a mode is for comes from the card: the project's card, else the "Try it on"
card. The first time the tab sees a card image it reads it with
:func:`..plugins.stern.title_reader.read_card` (the game program, where that build keeps
what a mode needs, and the game's own modes), OFF the UI loop. Its progress is published
at ``modes.reading``::

    {"state": "reading" | "failed" | "cancelled" | "done" | "",
     "label": "The Beatles 1.29.0", "card": "<file name>",
     "step": "port", "text": "<the step's words>", "pct": 0..100,
     "steps": [{"key", "words", "state": "todo" | "doing" | "done" | "failed"}],
     "error": "", "seconds": 12.4, "started": <epoch>, "notes": [...]}

and the page draws it as a bar and a step checklist, with Cancel. A card read once is
kept for the session by (path, size, time), and the reader's own helpers keep what they
worked out on this machine by the program's SHA-1, so a second look is instant.

Everything here runs only while the tab is shown with the preview switch on. The log
lines it writes name no feature (they say what was read, and how long it took).
"""

import os
import re
import threading
import time

from ..plugins.stern import mode_project as MP

#: how much of the bar each step takes (port derivation is the slow one)
STEP_WEIGHTS = {"program": 1.0, "port": 6.0, "stock": 2.0}
#: the fewest seconds between two progress posts from the worker (a step change always posts)
POST_EVERY = 0.1


def _reader():
    from ..plugins.stern import title_reader
    return title_reader


def card_key(image):
    """What a read is kept by: the image's path, size and time; None when it is not there."""
    try:
        st = os.stat(image)
    except (OSError, TypeError, ValueError):
        return None
    return os.path.normcase(os.path.abspath(image)), st.st_size, int(st.st_mtime)


def overall_pct(step, fraction, steps=None):
    """The whole read's percent from the step it is on and how far into that step."""
    steps = tuple(steps or _reader().STEPS)
    total = sum(STEP_WEIGHTS.get(s, 1.0) for s in steps) or 1.0
    done = 0.0
    for s in steps:
        if s == step:
            done += STEP_WEIGHTS.get(s, 1.0) * max(0.0, min(1.0, float(fraction or 0.0)))
            break
        done += STEP_WEIGHTS.get(s, 1.0)
    return int(round(100.0 * done / total))


#: The reader's progress words in the words the tab uses (port_derive speaks of "ports": what
#: the app ships or works out per game build, a word a person cannot act on).
_PLAIN_STEPS = (
    (re.compile(r"^Lining this build up with (\d+) ports?$"),
     lambda m: "Checking this build against %s known game%s" % (
         m.group(1), "" if m.group(1) == "1" else "s")),
    (re.compile(r"^Looking for a port shipped for this build$"),
     lambda m: "Looking for what the app ships for this build"),
    (re.compile(r"^Looking for a port derived earlier$"),
     lambda m: "Looking for what was worked out on this PC before"),
    (re.compile(r"^Checking the port against the program$"),
     lambda m: "Checking what was found against the program"),
    (re.compile(r"^Writing the port$"), lambda m: "Saving what was found"),
)


def plain_step_text(text):
    """A progress line with the reader's internal words put plainly (the log keeps nothing of
    these: they are shown while a read runs)."""
    text = str(text or "")
    for rx, words in _PLAIN_STEPS:
        m = rx.match(text)
        if m:
            return words(m)
    return re.sub(r"\b(reference )?ports?\b", "known games", text)


class TitleReadMixin:
    """Mixed into :class:`.tabs.modes.ModesTab`: the per-card read and its progress."""

    READ_LOG_TAG = "[card] "

    def _init_reading(self):
        self._reads = {}               # card_key -> TitleRead
        self._read_errors = {}         # card_key -> ("failed" | "cancelled", words)
        self._read_job = None          # the read running now (a dict), or None
        self.set(reading={"state": "", "steps": []})

    # ---- what the tab asks ---------------------------------------------------------------
    def _may_read(self):
        """A read starts only while the tab is shown to someone with the preview switch."""
        return bool(getattr(self, "_visible", False)) and self._preview_on()

    def title_read(self, card):
        """``(kind, value)`` for a :class:`ProjectCard` whose game is known:
        ``("done", TitleRead)``, ``("reading", None)`` (a read runs now, perhaps just
        started), ``("failed" | "cancelled", words)``, or ``("none", None)`` when the
        image is not on this computer (or the tab may not read it now)."""
        key = card_key(card.image) if card is not None and card.image else None
        if key is None:
            return "none", None
        if key in self._reads:
            return "done", self._reads[key]
        if key in self._read_errors:
            return self._read_errors[key]
        job = self._read_job
        if job is not None and job["key"] == key:
            return "reading", None
        if not self._may_read():
            return "none", None
        self._start_read(card, key)
        return "reading", None

    # ---- the worker ----------------------------------------------------------------------
    def _start_read(self, card, key):
        old = self._read_job
        if old is not None:
            old["cancel"] = "moved"         # the tab moved to another card
        tr_mod = _reader()
        label = MP.title_label(card.game_dir, card.version)
        job = {"key": key, "image": card.image, "label": label, "cancel": False,
               "step": tr_mod.STEPS[0], "fraction": 0.0, "text": "", "last": 0.0,
               "started": time.time(), "done": set(), "posted": False}
        self._read_job = job
        self._publish_reading(job)

        def progress(step, fraction, text):
            now = time.monotonic()
            changed = step != job["step"]
            if changed:
                job["done"].add(job["step"])
            job["step"], job["fraction"], job["text"] = step, fraction, text
            if fraction >= 1.0:
                job["done"].add(step)
            if changed or fraction >= 1.0 or now - job["last"] >= POST_EVERY:
                job["last"] = now
                self.ctx.loop.post(self._reading_tick, job)

        def work():
            try:
                tr = tr_mod.read_card(card.image, progress=progress,
                                      cancel=lambda: job["cancel"])
                result = ("done", tr)
            except tr_mod.Cancelled:
                result = ("cancelled", "")
            except Exception as e:                          # noqa: BLE001
                result = ("failed", str(e) or e.__class__.__name__)
            self.ctx.loop.post(self._reading_over, job, result)

        threading.Thread(target=work, daemon=True, name="modes-title-read").start()

    def _reading_tick(self, job):
        if self._read_job is job:
            self._publish_reading(job)

    def _reading_over(self, job, result):
        kind, value = result
        current = self._read_job is job
        if current:
            self._read_job = None
        seconds = time.time() - job["started"]
        name = MP.file_name(job["image"])
        if kind == "done":
            self._reads[job["key"]] = value
            self._read_errors.pop(job["key"], None)
            self._say_read("read %s (%s) in %.1f s" % (name, job["label"], seconds))
            for note in getattr(value, "notes", ()) or ():
                self._say_read(str(note))         # the reader's own words stay in the log
        if not current:
            return                          # another card's read is shown now
        if kind == "cancelled":
            self._read_errors[job["key"]] = ("cancelled", "")
            self._say_read("stopped reading %s after %.1f s" % (name, seconds))
        elif kind == "failed":
            self._read_errors[job["key"]] = ("failed", value)
            self._say_read("could not read %s: %s" % (name, value))
        self._publish_reading(job, kind=kind, value=value, seconds=seconds)
        self._refresh_after_read()

    def _say_read(self, text):
        msg = self.READ_LOG_TAG + text
        if self._on_loop():
            self.window.append_log(msg)
        else:
            self.ctx.loop.post(self.window.append_log, msg)

    def _refresh_after_read(self):
        """The read landed: the title, the list and the game's own modes again."""
        self._save_if_edited()
        self.refresh()
        self.refresh_stock_modes()

    # ---- the store ------------------------------------------------------------------------
    def _publish_reading(self, job, kind="reading", value=None, seconds=None):
        tr_mod = _reader()
        steps = []
        for s in tr_mod.STEPS:
            if kind == "done" or s in job["done"]:
                state = "done"
            elif s == job["step"]:
                state = "failed" if kind == "failed" else (
                    "todo" if kind == "cancelled" else "doing")
            else:
                state = "todo"
            steps.append({"key": s, "words": tr_mod.STEP_WORDS.get(s, s), "state": state})
        out = {"state": kind, "label": job["label"], "card": MP.file_name(job["image"]),
               "step": job["step"],
               "text": plain_step_text(job["text"]) or tr_mod.STEP_WORDS.get(job["step"], ""),
               "pct": 100 if kind == "done" else overall_pct(job["step"], job["fraction"],
                                                            tr_mod.STEPS),
               "steps": steps, "error": value if kind == "failed" else "",
               "started": job["started"], "seconds": seconds, "notes": []}
        if kind == "done" and value is not None:
            out["notes"] = list(getattr(value, "notes", ()) or ())
            out["seconds"] = seconds
        self.set(reading=out)

    def _clear_reading(self):
        if (self.get("reading") or {}).get("state"):
            self.set(reading={"state": "", "steps": []})

    # ---- the page's calls -------------------------------------------------------------------
    def reading_cancel(self):
        job = self._read_job
        if job is None:
            return False
        job["cancel"] = True
        cur = dict(self.get("reading") or {})
        cur["text"] = "Stopping at the next step…"
        self.set(reading=cur)
        return True

    def reading_again(self):
        """Read the card again after a failure or a Cancel."""
        for key, (kind, _w) in list(self._read_errors.items()):
            if kind in ("failed", "cancelled"):
                self._read_errors.pop(key, None)
        self._clear_reading()
        self.refresh()
        self.refresh_stock_modes()
        return True

    def read_of(self, card):
        """The finished :class:`TitleRead` of ``card``, or None."""
        key = card_key(card.image) if card is not None and card.image else None
        return self._reads.get(key) if key is not None else None
