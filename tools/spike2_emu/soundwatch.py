"""soundwatch.py - WHICH SOUNDS THE GAME PLAYS, FOR THE SOUND AND VIDEO LOG (PAD-1071).

The Emulate tab's Sound and video log lists every sound and clip the game
started, in order, so a sound heard in play can be found and played again.
The clips come from padvid.log (clipwatch.py writes them); this is the sounds.

WHERE IT COMES FROM: only the game's own sound worker knows which sound it was
asked for, so the mode runtime hooks it and writes one line per request to
/dump/mode.log - "<ms> [pad] sound <request> <n>" (n = 1 for a numbered
variant) - when the rig put /dump/soundlog.on there (modes/soundlog.sh; a
boot with no runtime of its own gets one that hooks the sound worker and
nothing else). Read here by offset with a reopen per look, the playfield's
rule over \\\\wsl.localhost (a held handle reads a stale cache).

WHAT IT WRITES, beside the Emulate tab's volume file (sounds_seen_<slot>.jsonl,
emptied by the tab at each Start): one JSON line per sound,
{"t": wall clock, "request": n, "n": 0|1}, one per recording it played,
{"t", "key": the record's 16 hex digits} (the record key the engine looked
up just after; the app names the file from the project's sound_keys.tsv),
and one when the runtime says
whether this run's sounds are logged at all, {"t", "log": "on"|"off", "why"},
so the window can say why a run lists no sounds. The tab names each request
from the project (its Sound Test name and Audio tab file).
"""
import json
import os
import re
import time
import zlib

SOUND = re.compile(r"^\s*\d+ \[pad\] sound (\d+) (\d+)\s*$")
#: the recording the request played (round 2): the record key the engine looked up next
KEY = re.compile(r"^\s*\d+ \[pad\] sound key ([0-9a-f]{16})\s*$")
#: round 4: a recording looked up later, with no request of its own - a song's next part
NEXT = re.compile(r"^\s*\d+ \[pad\] sound next ([0-9a-f]{16})\s*$")
#: the runtime's own words for the sound log, and for a port it will not use
ON = re.compile(r"\[pad\] sound log: every request")
#: round 2: this run's runtime logs the recording each request played (its key lines)
KEYS = re.compile(r"\[pad\] sound log: and the recording each one played")
OFF = re.compile(r"\[pad\] (?:sound log: off - (.*)|.*NOT THIS GAME'S PORT.*)$")
#: how often the log is read (seconds)
POLL_S = 0.25
#: how much of the log's start tells one run's log from the next's
HEAD = 64
#: round 4: a log nothing wrote to this long before the window started is an EARLIER run's (the window
#: opens beside a boot whose install has not cleared it yet): it is skipped until a new boot rewrites it
STALE_S = 5.0
#: the runtime's own clock at a line's start, which with the log's first bytes names the line for good
#: (a window reopened mid-run reads the log again from the top; the app drops what it already has)
MS = re.compile(r"^\s*(\d+) ")


class SoundWatch:
    """`log_path` is the run's mode.log, `seen_path` the record (None: none)."""

    def __init__(self, log_path, seen_path=None):
        self.log_path, self.seen_path = log_path, seen_path
        self.pos = 0
        self.part = ""
        self.head = b""
        self._next = 0.0
        self.count = 0
        self.started = time.time()
        self.boot = ""

    def poll(self, now):
        """Read what mode.log gained; how many sounds it held."""
        if now < self._next:
            return 0
        self._next = now + POLL_S
        try:
            with open(self.log_path, "rb") as f:
                head = f.read(HEAD)
                f.seek(0, 2)
                end = f.tell()
                # a new boot's install took the old log out: shorter, or its first line is another
                if end < self.pos or (self.head and head[:len(self.head)] != self.head):
                    self.pos, self.part = 0, ""
                elif not self.head and os.fstat(f.fileno()).st_mtime < self.started - STALE_S:
                    self.pos = end              # an earlier run's log: wait for this run's
                self.head = head
                self.boot = "%08x" % (zlib.crc32(head) & 0xffffffff)
                f.seek(self.pos)
                data = f.read()
                self.pos = f.tell()
        except OSError:
            return 0
        if not data:
            return 0
        text = self.part + data.decode("utf-8", "replace")
        lines = text.split("\n")
        self.part = lines.pop()
        events = []
        for ln in lines:
            ev = line_event(ln)
            if ev is not None:
                m = MS.match(ln)
                if m:
                    ev["ms"], ev["boot"] = int(m.group(1)), self.boot
                events.append(ev)
        self._record(events)
        n = sum(1 for ev in events if "request" in ev)
        self.count += n
        return n

    def _record(self, events):
        if not self.seen_path or not events:
            return
        t = round(time.time(), 3)
        try:
            with open(self.seen_path, "a", encoding="utf-8") as f:
                for ev in events:
                    ev["t"] = t
                    f.write(json.dumps(ev) + "\n")
        except OSError:
            pass


def line_event(ln):
    """The record of one mode.log line, or None for a line about something else."""
    m = SOUND.match(ln)
    if m:
        return {"request": int(m.group(1)), "n": int(m.group(2))}
    m = KEY.match(ln)
    if m:
        return {"key": m.group(1)}
    m = NEXT.match(ln)
    if m:
        return {"next": m.group(1)}
    if ON.search(ln):
        return {"log": "on"}
    if KEYS.search(ln):
        return {"log": "keys"}
    m = OFF.search(ln)
    if m:
        return {"log": "off", "why": (m.group(1) or "the port is not this game's").strip()}
    return None
