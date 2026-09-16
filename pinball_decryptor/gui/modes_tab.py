"""Modes tab — choreograph a game mode of our own and play it in the emulator.

WHAT A MODE IS HERE.  Not code: a FILE.  Item 126 turned ``mode.so`` into an
interpreter over a mode file — the trigger, the clock, the shots that score and
what they pay, the screens, the lights and the callouts all come out of it — and
the object re-reads that file twice a second.  So an edit made here lands in a
RUNNING game inside a second, which is the whole reason this is an editor and
not a form you submit.

WHY ITS OWN TAB.  The Emulate tab runs a card; this one authors a mode and asks
that rig to play it.  They are different jobs on different objects, and item
125's rules (``tools/spike2_emu/modes/MODE_API.md``) are Spike 2's, so the tab
is gated by its own ``modes`` capability rather than riding on ``emulate``.

WHAT THE PANEL IS AND IS NOT.  It owns the mode file and the words on screen.
It does NOT own the rig: launching, stopping and reporting a run belong to the
Emulate panel, and this tab reaches the rig only to copy the mode file in and to
ask for a run with ``PAD_MODE_SO`` set — through :mod:`._rig`, the same seam
every other tab uses, because ``wsl.exe`` re-parses its arguments and ``$var``
expands to nothing on that second pass.

THE FILE FORMAT is key-per-line, not JSON, and that is a constraint from the
other end: ``mode.so`` is built ``-nostdlib`` with libc declared by hand, with
no allocator and no ``stat``.  It parses against fixed buffers, and an unknown
key is logged and skipped — so this tab may write a key an older ``mode.so``
has never heard of without breaking it.
"""

import os
import pathlib

#: The mode files that ship with the rig, and where a user's own live.
DEFAULT_MODES_DIR = str(
    pathlib.Path(__file__).resolve().parents[2]
    / "tools" / "spike2_emu" / "modes"
)

#: Where the running guest reads its mode from.  The rig's dump directory is
#: already the channel the mode triggers use (``/dump/mode.start``), so the mode
#: file rides the same rail rather than inventing a second one.
GUEST_MODE_FILE = "/dump/mode.cfg"


def modes_dir():
    return os.environ.get("PAD_MODES_DIR") or DEFAULT_MODES_DIR


class ModeFile:
    """One mode, as the file's keys and as values a form can bind to.

    PARSING IS DELIBERATELY FORGIVING, and in both directions.  The runtime
    logs an unknown key and carries on; so does this.  A file a person edited by
    hand, or one written by a newer build of the tab, must survive a round trip
    through this class with nothing silently dropped — so every line that is not
    a key this tab knows is KEPT, in order, and written back out untouched.

    That is why this is a list of lines and not a dict: a dict would quietly
    eat the comments that explain a mode to the next person to open it.
    """

    #: Keys whose value is a NUMBER (decimal, or 0x hex as the runtime accepts).
    NUM_KEYS = ("seconds", "award", "screen_type", "title_msg", "total_msg",
                "restore_after", "light_owner", "callout_count", "callout_end")

    #: Keys whose value is the REST OF THE LINE, verbatim.  A light command is
    #: full of dashes and digits and must not be tokenised on the way through.
    TEXT_KEYS = ("name", "title_words", "total_words", "light_on", "light_off")

    def __init__(self, lines=()):
        self.lines = list(lines)

    # ---- reading ---------------------------------------------------------
    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return cls(f.read().splitlines())

    def get(self, key, default=""):
        """The value of *key*, or *default*.  The LAST one wins, which is what
        the runtime does too: it parses top to bottom and overwrites."""
        found = default
        for line in self.lines:
            k, v = self._split(line)
            if k == key:
                found = v
        return found

    def get_int(self, key, default=0):
        v = self.get(key, "")
        try:
            return int(v, 0) if v else default
        except ValueError:
            return default

    # ---- writing ---------------------------------------------------------
    def set(self, key, value):
        """Set *key*, in place if it is already there, appended if not.

        In place matters: a mode file is commented, and moving a key away from
        the comment that explains it makes the file worse every time it is
        saved.
        """
        text = "%-14s %s" % (key, value)
        for i, line in enumerate(self.lines):
            k, _v = self._split(line)
            if k == key:
                self.lines[i] = text
                return
        self.lines.append(text)

    def save(self, path):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.lines).rstrip("\n") + "\n")

    # ---- the one place that knows the grammar ----------------------------
    @staticmethod
    def _split(line):
        """``(key, value)`` for a data line, ``(None, None)`` for anything
        else.  Blank lines and ``#`` comments are not data; neither is an
        indented line, because the format has no continuations."""
        if not line or line[:1].isspace():
            return None, None
        s = line.strip()
        if not s or s.startswith("#"):
            return None, None
        parts = s.split(None, 1)
        return parts[0], (parts[1].strip() if len(parts) > 1 else "")
