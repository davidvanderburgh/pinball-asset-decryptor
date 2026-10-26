#!/usr/bin/env python3
"""bootprog.py - HOW FAR THE GAME HAS BOOTED (PAD-744), read off the run's logs.

    python3 bootprog.py [<logdir>]      # boot_pct=<n> and boot_words=<text>

David: "it would be good to show progress here [the playfield window] while
the emulator is booting up (like we do in the app window) since it can be at
80% for a bit while node boards come up". The app's footer had four fixed
steps (Boot 55, Node boards 80, Ready 100), and Node boards is most of the
wait: 12-16 s on a fast PC. Timed on four titles (godzilla_pro, jaws_le,
star_wars_le, aerosmith), that stage is, in order:

  1. the boot screen up, nothing countable for ~7 s (scenes loading);
  2. `[nbsched] playfield nodes: 4 1 8 9 ...` - the boards the game expects,
     all of them identifying at once (so counting boards would jump 0 to N);
  3. the game retrying the boards this model has not got: `ExchangeData: read
     failed`, 2988-3575 of them over ~4 s, the count itself is the motion;
  4. autoattract.sh's Service Back press (padauto.log), then attract.

The stages are gamestate.sh's: booted = 3 `[gst] factory_make`, past Tech
Alerts = `[led] light show running` (that file says why, at length). This
reads the same lines; it only adds the steps between. watch.sh truncates both
logs on every launch, a Restart game's included, so a log that shrank is a new
boot. The playfield window (a Windows process reading through
\\\\wsl.localhost) follows it incrementally; status.sh asks it once per poll
while the game boots, so the app and the window say the same thing.
"""

import os
import sys

#: The retry count that ends the node stage, roughly (2988-3575 measured): the
#: bar moves through its slice in proportion and stops short of the press.
EXPECT_PROBES = 3000

#: (pct) per step; Boot and Node boards start where the app's footer has
#: always put them (window.py _EMULATE_KINDS), Ready is 100.
PCT_BOOT, PCT_NODES, PCT_LISTED, PCT_PROBES_END, PCT_PRESSED = 55, 80, 84, 92, 95

_BOOTED = "gst] factory_make"
_ATTRACT = "[led] light show running"
_NODES = "[nbsched] playfield nodes:"
_PROBE = "ExchangeData: read failed"


class BootLog:
    """The game log, read as it grows. ``poll()`` reads what is new and
    returns ``progress()``; a file that shrank (a new launch truncated it)
    starts the count over."""

    def __init__(self, logdir):
        self.logdir = logdir
        self.log = os.path.join(logdir, "gzwatch.log") if logdir else None
        self.auto = os.path.join(logdir, "padauto.log") if logdir else None
        self._reset()

    def _reset(self):
        self.off = 0
        self.tail = b""
        self.booted = 0
        self.attract = False
        self.nodes = None
        self.probes = 0

    def _feed(self, data):
        lines = (self.tail + data).split(b"\n")
        self.tail = lines.pop()
        for raw in lines:
            ln = raw.decode("utf-8", "replace")
            if _BOOTED in ln:
                self.booted += 1
            if _PROBE in ln:
                self.probes += 1
            if self.nodes is None and _NODES in ln:
                ids = ln.split(_NODES, 1)[1].split("(", 1)[0].split()
                self.nodes = len(ids)
            if _ATTRACT in ln:
                self.attract = True

    def poll(self):
        try:
            size = os.stat(self.log).st_size
        except (OSError, TypeError):
            return None
        if size < self.off:
            self._reset()
        if size > self.off and not self.attract:
            try:
                with open(self.log, "rb") as f:
                    f.seek(self.off)
                    data = f.read(size - self.off)
            except OSError:
                return None
            self.off += len(data)
            self._feed(data)
        return self.progress()

    def _auto_text(self):
        try:
            with open(self.auto, "rb") as f:
                return f.read(65536).decode("utf-8", "replace")
        except (OSError, TypeError):
            return ""

    def progress(self):
        """(state, pct, words): state is gamestate.sh's word."""
        if self.attract:
            return "attract", 100, "Ready"
        if self.booted < 3:
            return "booting", PCT_BOOT, "Booting the game…"
        auto = self._auto_text()
        if "presses did not clear it" in auto or "gave up" in auto:
            return "techalerts", PCT_PRESSED, "Stuck at Tech Alerts: press Service Back (Esc)"
        if "pressing Service Back" in auto:
            return "techalerts", PCT_PRESSED, "Passing Tech Alerts…"
        found = (" %d found" % self.nodes) if self.nodes else ""
        if self.probes:
            p = min(self.probes, EXPECT_PROBES) / EXPECT_PROBES
            return ("techalerts",
                    PCT_LISTED + int(round((PCT_PROBES_END - PCT_LISTED) * p)),
                    "Node boards:%s, checking the rest (%d)"
                    % (found, self.probes))
        if self.nodes:
            return "techalerts", PCT_LISTED, "Node boards:%s" % found
        return "techalerts", PCT_NODES, "Bringing up node boards…"


def main(argv):
    logdir = argv[1] if len(argv) > 1 else os.environ.get("PAD_LOGDIR")
    got = BootLog(logdir).poll()
    if got is None:
        return 0
    _state, pct, words = got
    print("boot_pct=%d" % pct)
    print("boot_words=%s" % words)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
