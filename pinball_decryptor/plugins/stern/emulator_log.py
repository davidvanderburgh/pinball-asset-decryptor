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

WHICH RECORDING (round 2: "the very short ones are missing here and there"). Every request the game
makes reaches the log (emulator-proven, bursts of four a second too), but nearly half of them play
one of several recordings (Deadpool Pro 1.16: 377 of 853; a spinner's four in turn), and a row that
named and played the first one sent the user looking for the one he heard. The runtime now logs the
record key the engine looked up just after the request (``{"key"}`` lines), and the project's
``sound_keys.tsv`` (Extract writes it) turns the key into the Audio tab file: the row names and plays
that one. A row of several recordings waits up to :data:`HOLD_S` for its key before it is shown, so
a row is whole when the page gets it; a project extracted before the keys file shows the first, and
its tip says so.

AND WHICH REQUESTS DID NOT SOUND. The same run showed the other side: the game asks for sounds it then
does not play - Deadpool's Colossus line four times in a second while a call it ranks higher held the
voice, two requests in one millisecond of which one sounded. With the keys known, a request that plays
always shows its recording's key, so a row of the project's sounds with none within :data:`HOLD_S`
is marked ``unplayed`` ("not played", dimmed), and the list is what was heard.
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
    """How a row is named from the project: ``sound(request)`` -> ``(name, [audio rels], [their idx])``,
    ``idx_of_key(key)`` -> the decoded sound a recording's record key is (or None)."""

    def __init__(self, project):
        from .clip_sounds import audio_files, read_keys, read_requests
        self.project = project or ""
        ok = bool(project and os.path.isdir(project))
        self._req = read_requests(project) if ok else {}
        self._files = audio_files(project) if ok else {}
        self._keys = read_keys(project) if ok else {}

    def sound(self, request):
        v = self._req.get(int(request))
        if not v:
            return "", [], []
        rels, idxs = [], []
        for i in list(v["idx"]) + list(v["also"] or ()):
            if i in self._files and i not in idxs:
                rels.append(self._files[i])
                idxs.append(i)
        return v["name"] or "", rels, idxs

    def idx_of_key(self, key):
        return self._keys.get(str(key or "").lower())

    def has_map(self):
        return bool(self._req)

    def has_keys(self):
        return bool(self._keys)


def _clock(t):
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(t)))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


#: how long a row of several recordings waits for the key of the one it played (the runtime logs it
#: 1-5 ms after the request; the playfield reads the log four times a second)
HOLD_S = 1.0


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
        self.pending = []          # rows read, not yet shown: a sound of several recordings waits for its key
        self.status, self.why = "", ""
        self.keyed = False         # this run's runtime logs the recording each request played

    def reset(self):
        """A new run: the rows go, and the numbering goes on (a page sees ``first`` move)."""
        self.first += len(self.rows)
        self.rows = []
        self.pending = []
        self.status, self.why = "", ""
        self.keyed = False

    def poll(self, now=None):
        """Read what the files gained; True when anything a page shows changed."""
        now = time.time() if now is None else now
        sev, s_new = self.sounds.read()
        cev, c_new = self.clips.read()
        changed = bool(s_new or c_new)
        if changed:
            self.reset()
        for ev in sev:
            if ev.get("log") == "keys":
                self.keyed = True
            elif "log" in ev:
                self.status = "on" if ev.get("log") == "on" else "off"
                self.why = str(ev.get("why") or "")
                changed = True
            elif "key" in ev:
                self._played(ev)
            else:
                row = self._sound_row(ev)
                if row is not None:
                    self.pending.append(row)
        for ev in cev:
            row = self._clip_row(ev)
            if row is not None:
                self.pending.append(row)
        return self._release(now) or changed

    def _played(self, ev):
        """A recording the engine looked up: the newest waiting row of a request that plays it."""
        idx = self.names.idx_of_key(ev.get("key"))
        if idx is None:
            return
        try:
            t = float(ev.get("t") or 0)
        except (TypeError, ValueError):
            return
        for r in reversed(self.pending):
            if r["kind"] == "sound" and r.get("played") is None and idx in r["idxs"] and t - r["t"] <= HOLD_S:
                k = r["idxs"].index(idx)
                r["played"] = k
                r["rel"] = r["rels"][k]
                if r.pop("named_by_file", False):
                    r["name"] = os.path.splitext(os.path.basename(r["rel"]))[0]
                if len(r["rels"]) > 1:
                    r["what"] += "  %d of %d" % (k + 1, len(r["rels"]))
                    r["tip"] = [r["tip"][0]] + ["Played this time: %s (%d of its %d recordings)"
                                                 % (os.path.basename(r["rel"]), k + 1, len(r["rels"]))] + r["tip"][1:]
                return

    def _release(self, now):
        """The waiting rows in the order they started, up to the first still waiting for its key."""
        self.pending.sort(key=lambda r: r["t"])
        out = 0
        while self.pending:
            r = self.pending[0]
            if r.get("hold") and r.get("played") is None and now - r["t"] < HOLD_S:
                break
            self.pending.pop(0)
            if r.get("hold") and r.get("played") is None:
                r["unplayed"] = True
                r["what"] += "  not played"
                r["tip"] = [r["tip"][0]] + ["Asked for, but the game did not play it this time: it was "
                                             "playing a sound it ranks higher, or this one already."] + r["tip"][1:]
            r.pop("hold", None)
            r.pop("named_by_file", None)
            r["i"] = self.first + len(self.rows)
            self.rows.append(r)
            out += 1
        if len(self.rows) > self.KEEP:
            drop = len(self.rows) - self.KEEP
            self.rows = self.rows[drop:]
            self.first += drop
        return bool(out)

    def _sound_row(self, ev):
        try:
            req = int(ev["request"])
            t = float(ev.get("t") or 0)
        except (KeyError, TypeError, ValueError):
            return None
        name, rels, idxs = self.names.sound(req)
        what = "Sound request %d%s" % (req, " (a numbered variant)" if ev.get("n") else "")
        tip = [what]
        if name:
            tip.append("Sound Test name: " + name)
        if len(rels) > 1:
            tip.append("It plays one of %d recordings each time: %s" % (
                len(rels), ", ".join(os.path.basename(r) for r in rels[:6])
                + (" and %d more" % (len(rels) - 6) if len(rels) > 6 else "")))
            if not self.names.has_keys():
                tip.append("Which one played is not known for this project, so the first is the one "
                           "played and opened. Extract the card into it again to see which one played.")
            elif not self.keyed:
                tip.append("Which one played is not known for this run (an emulator from before this "
                           "log named it), so the first is the one played and opened.")
        elif rels:
            tip.append("Its file on the Audio tab: " + os.path.basename(rels[0]))
        elif self.names.has_map():
            tip.append("None of the Audio tab's files is this request's: it is most likely a song "
                       "from a music bank, or a sound this project does not hold.")
        else:
            tip.append("This project has no record of the game's sound requests, so the sound is "
                       "not named. Extract the card into it again to name them.")
        label = name or (os.path.splitext(os.path.basename(rels[0]))[0] if rels else "Unnamed sound")
        return {"t": t, "at": _clock(t), "kind": "sound", "name": label, "what": "#%d" % req,
                "rel": rels[0] if rels else "", "rels": rels, "idxs": idxs, "played": None,
                "hold": bool(rels) and self.names.has_keys() and self.keyed,
                "named_by_file": not name and bool(rels),
                "tip": tip}

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
