"""PAD-1071: the Emulate tab's Sound and video log - every sound and clip the game started, in order.

A field request: run the emulator, see what the game played during a game, and open those sounds
and clips afterwards straight from the list, in a window of its own beside the game.

WHERE THE ROWS COME FROM, two files the playfield window appends to beside the Emulate tab's volume
file during a run (and the tab empties at each Start, so they hold the last run until the next):

* the CLIPS: ``clips_seen_<slot>.jsonl`` (PAD-827, ``tools/spike2_emu/clipwatch.py``): one line per
  clip the game asked the video host for, with the Video tab row it is (:mod:`.clip_seen`'s map),
  the switch made just before it, and a line when it is first seen looping;
* the SOUNDS: ``sounds_seen_<slot>.jsonl`` (``tools/spike2_emu/soundwatch.py``): one line per
  request the game's sound worker took, as the mode runtime logs it (``soundlog.on``), and a line
  saying whether this run's sounds are logged at all (``{"log": "on"|"off", "why"}``).

A sound request is a NUMBER in the game's code; the project's ``sound_requests.tsv`` (Extract,
PAD-635) names it - its Sound Test name, the decoded sounds it plays - and :func:`.clip_sounds.audio_files`
finds those on the Audio tab whatever the files were renamed to. A request the map does not name
(a song in a music bank, a project extracted before the map) is listed by its number.
"""
from __future__ import annotations

import json
import os
import time

from .clip_seen import seen_file as clips_file


def sounds_file(ctl_dir, slot):
    """What the playfield window heard, one JSON line per sound, beside the volume file."""
    return os.path.join(ctl_dir, "sounds_seen_%d.jsonl" % int(slot or 0))


def clear_sounds(ctl_dir, slot):
    """At Start: the last run's sounds go (its clips go with :func:`.clip_seen.write_names`)."""
    try:
        os.remove(sounds_file(ctl_dir, slot))
    except OSError:
        pass


class _Tail:
    """New whole JSON lines of one file since the last look; a file that shrank is a new run's."""

    def __init__(self, path):
        self.path = path
        self.pos = 0
        self.part = b""

    def read(self):
        """``(events, restarted)``."""
        try:
            with open(self.path, "rb") as f:
                st = os.fstat(f.fileno())
                restarted = st.st_size < self.pos
                if restarted:
                    self.pos, self.part = 0, b""
                f.seek(self.pos)
                data = f.read()
                self.pos = f.tell()
        except OSError:
            restarted = self.pos > 0            # taken out at Start
            self.pos, self.part = 0, b""
            return [], restarted
        data = self.part + data
        lines = data.split(b"\n")
        self.part = lines.pop()
        out = []
        for ln in lines:
            try:
                ev = json.loads(ln.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(ev, dict):
                out.append(ev)
        return out, restarted


class Names:
    """How a row is named from the project: ``sound(request)`` -> ``(name, [audio rels])``."""

    def __init__(self, project):
        from .clip_sounds import audio_files, read_requests
        self.project = project or ""
        ok = bool(project and os.path.isdir(project))
        self._req = read_requests(project) if ok else {}
        self._files = audio_files(project) if ok else {}

    def sound(self, request):
        v = self._req.get(int(request))
        if not v:
            return "", []
        rels = [self._files[i] for i in list(v["idx"]) + list(v["also"] or ()) if i in self._files]
        seen = set()
        rels = [r for r in rels if not (r in seen or seen.add(r))]
        return v["name"] or "", rels

    def has_map(self):
        return bool(self._req)


def _clock(t):
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(t)))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


class Log:
    """The window's rows, read as they arrive. ``rows`` is the whole list (oldest first), each
    ``{"i", "t", "at", "kind": "sound"|"video", "name", "what", "rel", "rels", "tip"}``, ``i``
    counting on across runs; ``status`` says what the sound side of this run is ("on", "off", or ""
    before the runtime said, and on a runtime from before PAD-1071, which says nothing)."""

    #: rows kept: a long session's beginning goes first, the window never grows without bound
    KEEP = 20000

    def __init__(self, ctl_dir, slot, project):
        self.sounds = _Tail(sounds_file(ctl_dir, slot))
        self.clips = _Tail(clips_file(ctl_dir, slot))
        self.names = Names(project)
        self.rows = []
        self.first = 0             # the "i" of rows[0]
        self.status, self.why = "", ""

    def reset(self):
        """A new run: the rows go, and the numbering goes on (a page sees ``first`` move)."""
        self.first += len(self.rows)
        self.rows = []
        self.status, self.why = "", ""

    def poll(self):
        """Read what the files gained; True when anything a page shows changed."""
        sev, s_new = self.sounds.read()
        cev, c_new = self.clips.read()
        changed = bool(s_new or c_new)
        if changed:
            self.reset()
        new = []
        for ev in sev:
            if "log" in ev:
                self.status = "on" if ev.get("log") == "on" else "off"
                self.why = str(ev.get("why") or "")
                changed = True
                continue
            row = self._sound_row(ev)
            if row is not None:
                new.append(row)
        for ev in cev:
            row = self._clip_row(ev)
            if row is not None:
                new.append(row)
        new.sort(key=lambda r: r["t"])
        for r in new:
            r["i"] = self.first + len(self.rows)
            self.rows.append(r)
        if len(self.rows) > self.KEEP:
            drop = len(self.rows) - self.KEEP
            self.rows = self.rows[drop:]
            self.first += drop
        return changed or bool(new)

    def _sound_row(self, ev):
        try:
            req = int(ev["request"])
            t = float(ev.get("t") or 0)
        except (KeyError, TypeError, ValueError):
            return None
        name, rels = self.names.sound(req)
        what = "Sound request %d%s" % (req, " (a numbered variant)" if ev.get("n") else "")
        tip = [what]
        if name:
            tip.append("Sound Test name: " + name)
        if rels:
            tip.append("Its files on the Audio tab: " + ", ".join(os.path.basename(r) for r in rels[:6])
                       + (" and %d more" % (len(rels) - 6) if len(rels) > 6 else ""))
        elif self.names.has_map():
            tip.append("None of the Audio tab's files is this request's: it is most likely a song "
                       "from a music bank, or a sound this project does not hold.")
        else:
            tip.append("This project has no record of the game's sound requests, so the sound is "
                       "not named. Extract the card into it again to name them.")
        label = name or (os.path.splitext(os.path.basename(rels[0]))[0] if rels else "Unnamed sound")
        return {"t": t, "at": _clock(t), "kind": "sound", "name": label, "what": "#%d" % req,
                "rel": rels[0] if rels else "", "rels": rels, "tip": tip}

    def _clip_row(self, ev):
        try:
            t = float(ev.get("t") or 0)
        except (TypeError, ValueError):
            return None
        rel = ev.get("rel") if isinstance(ev.get("rel"), str) else ""
        name = ev.get("name") or (os.path.splitext(os.path.basename(rel))[0] if rel else "") \
            or os.path.basename(str(ev.get("path") or "")) or "a clip"
        loop = bool(ev.get("loop"))
        sw = str(ev.get("switch") or "")
        what = "loops" if loop else ("after " + sw if sw else "")
        tip = ["Clip %s%s" % (name, " (seen looping)" if loop else "")]
        if sw:
            tip.append("Started just after the switch " + sw)
        if rel:
            tip.append("Video tab: " + rel)
        else:
            tip.append("Not one of this project's Video tab rows (the run's card is another "
                       "title's, or the project has no video folder).")
        return {"t": t, "at": _clock(t), "kind": "video", "name": name, "what": what,
                "rel": rel, "rels": [rel] if rel else [], "tip": tip}

    def page(self, after=-1):
        """What a page needs to catch up: ``{"first", "rows", "status", "why", "counts"}`` - the
        rows numbered past *after* (all of them for -1). ``first`` is the number of the oldest row
        kept: a page holding rows below it drops them (a new run, or the oldest let go)."""
        rows = [r for r in self.rows if r["i"] > after] if after >= self.first else list(self.rows)
        counts = {"sound": sum(1 for r in self.rows if r["kind"] == "sound"),
                  "video": sum(1 for r in self.rows if r["kind"] == "video")}
        return {"first": self.first, "rows": rows, "status": self.status, "why": self.why,
                "counts": counts}
