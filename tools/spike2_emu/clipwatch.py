"""clipwatch.py - WHICH CLIP IS THE GAME PLAYING, AND WHAT SET IT OFF (PAD-827).

The playfield window's CLIPS list. A battle plays a dozen clips named like
gigan_ghidorah_vs_godzilla13, and the one thing that tells them apart is what
the game does with each: the shot that starts it, whether it loops.

WHERE IT COMES FROM, all of it already on disk during every Spike 2 run:

  * the CLIP: every file the game opens reaches padvidhost.py as a path, and
    its `serving` line in padvid.log names it (the rate at the end since
    PAD-827). Read here by offset, a reopen per look - the same rule as the
    window's other reads over \\\\wsl.localhost (playfield.py: a held handle
    reads a stale cache).
  * its NAME: the Emulate tab writes the project's names beside its volume
    file (clip_names_<slot>.json: guest path -> [Video tab row, name]), from
    the project's video/manifest.txt, so a clip is called what its Video tab
    row is called. Without that file a clip is its file under scene.assets.
  * WHAT SET IT OFF: the switches the window reads anyway (read_merged), as
    edges. The switch made last within TRIGGER_S before a clip starts is its
    trigger, and it is used up by that clip, so the clips that follow it on
    their own are not credited with the same shot.
  * a LOOP: the same file asked for again on the same channel as it ends (its
    length from frames / rate, LOOP_SLACK_S either side). A file asked for
    twice at once (padvidhost serves the attract clip twice) is one play.

WHAT IT WRITES: one JSON line per clip start, and one when a clip is first
seen looping, to clips_seen_<slot>.jsonl beside the names file; the Emulate
tab folds them into the project (plugins/stern/clip_seen.py), where the Video
tab shows them.
"""
import collections
import json
import os
import re
import time

LINE = re.compile(
    r"\[padvid\s+([\d.]+)\]\s+ch(\d+) serving \d+x\d+ (\d+) frames "
    r"(?:\(acked [^)]*\) )?(\S+)(.*)$")
FPS = re.compile(r"\(([\d.]+) fps\)")
#: a switch made this long before a clip starts can be what started it
TRIGGER_S = 2.5
#: a loop is the same file asked for again within this of its length
LOOP_SLACK_S = 1.5
#: the same file asked for twice this close together is one play
SAME_S = 0.3
#: how many clips the list keeps
KEEP = 12
#: how often the log is read (seconds)
POLL_S = 0.25
#: how much of the log's start tells one run's log from the next's (its first
#: line carries the time it was written to the hundredth of a second)
HEAD = 64
#: switches made all game long that start no clip of their own: the
#: flippers' buttons and end-of-stroke, the trough's ball counting, the door
NOT_TRIGGERS = re.compile(r"flipper|\beos\b|end of stroke|trough|coin door", re.I)


def short(p):
    i = p.find("scene.assets/")
    return p[i + len("scene.assets/"):] if i >= 0 else p


def load_names(path, game=""):
    """{guest path: [rel, name]} from the Emulate tab's file, or {} - also
    when the file is another title's (a project of one card, a run of another:
    two titles' banks can share a scene hash and its clip numbers)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if game and data.get("game") and data["game"] != game:
            return {}
        names = data.get("names") or {}
        return {k: v for k, v in names.items()
                if isinstance(v, list) and len(v) == 2}
    except (OSError, ValueError, AttributeError):
        return {}


class Clip:
    __slots__ = ("path", "name", "rel", "ch", "t", "dur", "switch", "loops",
                 "plays", "seen")

    def __init__(self, path, name, rel, ch, t, dur, switch, seen):
        self.path, self.name, self.rel, self.ch = path, name, rel, ch
        self.t, self.dur, self.switch = t, dur, switch
        self.loops, self.plays, self.seen = False, 1, seen

    def row(self, now_path):
        return {"name": self.name, "sw": self.switch or "", "loop": self.loops,
                "n": self.plays, "now": self.path == now_path}


class ClipWatch:
    """The list, the switch edges and the record. `log_path` is padvid.log;
    `names_path` / `seen_path` the Emulate tab's files (None: none)."""

    def __init__(self, log_path, names_path=None, seen_path=None, names=None,
                 game=""):
        self.log_path, self.names_path, self.seen_path = log_path, names_path, seen_path
        self.game = game
        self.pos = 0
        self.part = ""
        self.head = b""                 # the log's first bytes: a new run's differ
        self.clips = collections.deque(maxlen=KEEP)
        self.last = {}                  # channel -> its last Clip
        self.now_path = None
        self.edges = collections.deque(maxlen=32)   # (monotonic, switch name)
        self._prev = None
        self._next = 0.0
        self._names = names
        self._names_mtime = None
        self.dirty = True

    # ---- the names --------------------------------------------------------
    def names(self):
        if self._names is not None and self.names_path is None:
            return self._names
        try:
            m = os.path.getmtime(self.names_path) if self.names_path else None
        except OSError:
            m = None
        if m != self._names_mtime:
            self._names_mtime = m
            self._names = load_names(self.names_path, self.game) if m else {}
        return self._names or {}

    # ---- the switches -----------------------------------------------------
    def feed_switches(self, mrg, names, now):
        """The merged switch array as the window last read it; `names` is
        {id: name}. Every switch that went from open to made is an edge."""
        if mrg is None:
            return
        prev, self._prev = self._prev, bytes(mrg)
        if prev is None or len(prev) != len(mrg):
            return
        for sid in range(len(mrg)):
            if mrg[sid] and not prev[sid]:
                name = names.get(sid)
                if name and not NOT_TRIGGERS.search(name):
                    self.edges.append((now, name))

    def _trigger(self, now):
        """The switch made last within TRIGGER_S of `now`, used up."""
        if not self.edges:
            return ""
        t, name = self.edges[-1]
        self.edges.clear()
        return name if now - t <= TRIGGER_S else ""

    # ---- the log ----------------------------------------------------------
    def poll(self, now):
        """Read what padvid.log gained; True when the list changed."""
        if now < self._next:
            return False
        self._next = now + POLL_S
        try:
            with open(self.log_path, "rb") as f:
                head = f.read(HEAD)
                f.seek(0, 2)
                end = f.tell()
                # a new run rewrote it: shorter, or its first line is another
                if end < self.pos or (self.head and head[:len(self.head)] != self.head):
                    self.pos, self.part = 0, ""
                    self.last.clear()
                self.head = head
                f.seek(self.pos)
                data = f.read()
                self.pos = f.tell()
        except OSError:
            return False
        if not data:
            return False
        text = self.part + data.decode("utf-8", "replace")
        lines = text.split("\n")
        self.part = lines.pop()
        changed = False
        for ln in lines:
            changed |= self.line(ln, now)
        return changed

    def line(self, ln, now):
        m = LINE.search(ln)
        if not m:
            return False
        t, ch, frames, path, rest = (float(m.group(1)), int(m.group(2)),
                                     int(m.group(3)), m.group(4), m.group(5))
        f = FPS.search(rest)
        fps = float(f.group(1)) if f else 30.0
        dur = frames / fps if fps > 0 else 0.0
        prev = self.last.get(ch)
        if prev is not None and prev.path == path:
            gap = t - prev.t
            if gap <= SAME_S:
                return False
            if prev.dur and gap <= prev.dur + LOOP_SLACK_S \
                    and gap >= prev.dur - LOOP_SLACK_S:
                prev.t = t
                if not prev.loops:
                    prev.loops = True
                    self._record({"path": path, "rel": prev.rel,
                                  "name": prev.name, "loop": True})
                    self.dirty = True
                    return True
                return False
        rel, name = (self.names().get(path) or [None, None])
        clip = Clip(path, name or short(path), rel, ch, t, dur,
                    self._trigger(now), now)
        self.last[ch] = clip
        self.now_path = path
        same = next((c for c in self.clips if c.path == path), None)
        if same is not None and same.switch == clip.switch:
            self.clips.remove(same)
            same.plays += 1
            same.t, same.dur, same.seen = t, dur, now
            self.last[ch] = same
            self.clips.appendleft(same)
        else:
            self.clips.appendleft(clip)
        self._record({"path": path, "rel": rel, "name": clip.name,
                      "switch": clip.switch})
        self.dirty = True
        return True

    def _record(self, ev):
        if not self.seen_path:
            return
        ev["t"] = round(time.time(), 3)
        try:
            with open(self.seen_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        except OSError:
            pass

    def dyn(self):
        return [c.row(self.now_path) for c in self.clips]
