"""boxctl.py <dir> - the box's half of the Emulate tab's control folder (PAD-1129).

On Windows and Linux the playfield window and the Emulate tab share one folder:
the tab's audio_ctl.json (Volume / Mute), the run's clip names, and what the
window leaves for the tab - a Restart game request, the clips and sounds it
saw. On a Mac the window runs inside the container, where that folder is not,
so it was started with no PAD_AUDIO_CTL and its page left out Volume, Mute and
Restart game altogether.

The box now has a folder of its own (<dir>, handed to the window as
PAD_AUDIO_CTL=<dir>/audio_ctl.json) and this keeps it level with the Mac's.
It runs in the box under ``docker exec -i``, started by padbox.sh's ctl_sync:

* stdin, from the Mac:  ``PUT ctl <base64>`` / ``PUT names <base64>`` - the
  tab's volume file and the run's clip names, sent whenever they change.
  Written beside and moved into place, so nothing reads half of one.
* stdout, to the Mac:   ``CTL <json>`` - the window moved Volume or Mute (a
  change of the file this did not write itself); ``REQ`` - the window asked
  for Restart game (the request is taken, so it is said once);
  ``ADD clips|sounds <line>`` - a line the window appended to its record.

A copy over docker exec and not a mount of the Mac's folder, for PAD-957's
reasons: a mounted folder's changes reach the box when the container engine
says so, and whether the box's user may write into it is up to the engine too.
docker exec is the path every other step of a Mac run already rides.

The sound relay reads the same audio_ctl.json, so the window's Volume moves
the sound inside the box at once, and the Mac's copy follows for the tab.
"""
import base64
import json
import os
import sys
import threading
import time

POLL_S = 0.1


def slot():
    try:
        return max(0, int(os.environ.get("PAD_SLOT") or 0))
    except ValueError:
        return 0


class BoxCtl:
    def __init__(self, d, out=None):
        self.d = d
        self.out = out or sys.stdout
        n = slot()
        self.ctl = os.path.join(d, "audio_ctl.json")
        self.names = os.path.join(d, "clip_names_%d.json" % n)
        self.req = os.path.join(d, "restart_game_%d.req" % n)
        self.seen = {"clips": os.path.join(d, "clips_seen_%d.jsonl" % n),
                     "sounds": os.path.join(d, "sounds_seen_%d.jsonl" % n)}
        self.pos = {k: 0 for k in self.seen}
        self.part = {k: b"" for k in self.seen}
        self.lock = threading.Lock()
        self.ours = None           # the volume file as this last wrote it
        self.last = None           # as this last read it
        os.makedirs(d, exist_ok=True)
        # the window may run as the box's user while this runs as root; not
        # sticky, or the window could not replace a file root wrote
        os.chmod(d, 0o777)

    def say(self, line):
        self.out.write(line + "\n")
        self.out.flush()

    def put(self, what, data):
        """A file from the Mac, into place."""
        path = {"ctl": self.ctl, "names": self.names}.get(what)
        if path is None:
            return
        tmp = path + ".box.tmp"
        with self.lock:
            with open(tmp, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o666)
            os.replace(tmp, path)
            if what == "ctl":
                self.ours = self.last = data

    def feed(self, lines):
        for line in lines:
            parts = line.strip().split(" ", 2)
            if len(parts) != 3 or parts[0] != "PUT":
                continue
            try:
                self.put(parts[1], base64.b64decode(parts[2]))
            except (ValueError, OSError):
                pass

    def _read(self, path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def poll(self):
        with self.lock:
            cur = self._read(self.ctl)
            if cur is not None and cur != self.last:
                self.last = cur
                if cur != self.ours:
                    try:
                        self.say("CTL " + json.dumps(json.loads(cur.decode("utf-8"))))
                    except (ValueError, UnicodeDecodeError):
                        pass
        if os.path.exists(self.req):
            try:
                os.remove(self.req)
            except OSError:
                pass
            else:
                self.say("REQ")
        for kind, path in self.seen.items():
            try:
                with open(path, "rb") as f:
                    f.seek(self.pos[kind])
                    got = f.read()
            except OSError:
                continue
            self.pos[kind] += len(got)
            buf = self.part[kind] + got
            *done, self.part[kind] = buf.split(b"\n")
            for line in done:
                line = line.decode("utf-8", "replace").strip()
                if line:
                    self.say("ADD %s %s" % (kind, line))


def main(argv):
    if len(argv) != 2:
        print("usage: boxctl.py <dir>", file=sys.stderr)
        return 2
    box = BoxCtl(argv[1])
    t = threading.Thread(target=box.feed, args=(sys.stdin,), daemon=True)
    t.start()
    try:
        while True:
            box.poll()
            time.sleep(POLL_S)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
